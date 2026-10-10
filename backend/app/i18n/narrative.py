"""Translate model-written narrative prose from English to Korean, one call per uncached sentence.

**Off by default, and a true no-op when off.** `Settings.translate_narratives` gates every path here:
when it is `False`, :func:`translate_texts` returns `[None] * len(texts)` without reading the cache or
importing anything from `app.agents` -- the same "degrades to nothing, never raises" shape
`app.agents` itself uses throughout (see that package's module docstring), applied one layer up so a
deployment that never opts in pays nothing, not even a cache read.

**The number-preservation gate is the whole point of this module existing.** A mistranslated number in
financial narrative prose -- a dropped `%`, a corrupted date, an altered ticker -- is worse than no
translation at all, so every model response is checked with `app.agentdesk.grounding.numeric_tokens`
before it is trusted: every numeric token the source sentence carries must still appear, verbatim,
somewhere in the Korean response. A translation that drops or alters even one token is rejected --
`None` is returned and nothing is cached -- rather than shown with a silently wrong figure. This reuses
`numeric_tokens` rather than inventing a second number-extraction pass specifically so the two features
can never disagree about what counts as a groundable number.

**One call per uncached text, budgeted across the whole batch.** `translate_texts` threads one
`AgentBudget` through every text in the request -- `app.agents.client.call_structured` returns a new,
updated budget each call, and that new budget (not the original) is what the next iteration checks and
passes on. Once it is exhausted, every remaining uncached text gets `None` with no further model call,
the same fail-open shape `app.agents.designer`/`app.agents.reviewer` use when their own per-run budget
runs out.

**Every failure is `None`, never an exception.** A missing credential, a malformed response, a refusal,
a transport error, an exhausted budget -- `app.agents.client.call_structured` can raise several
different exception types for these (`AgentUnavailable` and its subclasses, `BudgetExhausted`), and
this module catches all of them at the single per-text call site rather than asking a caller (the
`/api/i18n/translate` route, ultimately a page render) to know the agent layer's exception hierarchy.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from app.agentdesk.grounding import numeric_tokens
from app.agents.client import call_structured
from app.agents.models import DEFAULT_MODEL, AgentBudget
from app.agents.spend import LEDGER
from app.config import Settings
from app.i18n.cache import get_cached, set_cached

__all__ = ["translate_texts"]

_SYSTEM_PROMPT = """You translate financial dashboard narrative prose from English to natural, \
professional Korean.

Preserve every number, percentage, ticker symbol, date and identifier VERBATIM and unchanged -- copy \
these tokens exactly as they appear in the source, character for character. Translate only the \
surrounding natural-language words. Do not add, remove, round, reformat or otherwise alter any number, \
percentage, ticker symbol, date or identifier.

Return only the Korean translation, with no preamble, no explanation, and no quotation marks around it."""


class _KoreanText(BaseModel):
    """The shape `call_structured` parses the model's response into: the Korean translation, and
    nothing else -- no self-reported confidence, no echoed source text, so there is exactly one field
    for the number-preservation check below to read."""

    korean: str


def _translate_one(text: str, *, settings: Settings, budget: AgentBudget) -> tuple[str | None, AgentBudget]:
    """One model call for one already-stripped, non-empty, cache-missed text.

    Returns the accepted Korean string (or `None` on any rejection/failure) alongside the budget to
    carry into the next call -- unchanged on every failure path, since a call that never reached the
    model (budget already exhausted) or that raised before `call_structured` returned a new budget
    spent nothing beyond what `budget` already reflects.
    """
    if budget.exhausted:
        return None, budget

    try:
        parsed, _call, new_budget = call_structured(
            role="translator",
            system=_SYSTEM_PROMPT,
            user=text,
            output_format=_KoreanText,
            model=DEFAULT_MODEL,
            settings=settings,
            budget=budget,
        )
    except Exception:
        # Any transport/auth/parse failure (AgentUnavailable and its subclasses, BudgetExhausted, or
        # anything else `call_structured` might raise) degrades to "not translated" -- see this
        # module's own docstring for why every failure here is None rather than an exception.
        return None, budget

    korean = parsed.korean.strip()
    if not korean:
        return None, new_budget

    source_tokens = numeric_tokens(text)
    translated_tokens = set(numeric_tokens(korean))
    if any(token not in translated_tokens for token in source_tokens):
        # The model dropped or altered a source number -- reject rather than cache or return a
        # translation that could misstate a figure. See the module docstring's number-preservation
        # paragraph.
        return None, new_budget

    return korean, new_budget


def translate_texts(texts: Sequence[str], *, locale: str, settings: Settings) -> list[str | None]:
    """Translate each of `texts` to `locale` (currently only `"ko"` is ever passed by the router), one
    result per input text, in the same order, `None` wherever translation did not happen.

    Cache key is `(locale, sha256(text))` (see `app.i18n.cache.cache_key`); a hit returns the cached
    string without any model call. A miss calls the model once, budgeted against one `AgentBudget`
    shared across the whole batch (`settings.translate_budget_usd` is its cap) -- see the module
    docstring for how the budget threads across calls and how every failure becomes `None`.

    Before any cache-miss actually reaches the model, `app.agents.spend.LEDGER.check` is consulted
    against `settings.model_spend_daily_cap_usd` -- the aggregate cap across every translate + persona
    call, distinct from `translate_budget_usd` above (see that setting's own docstring). Unlike a
    per-text model failure, this is not degraded to `None`: `app.agents.spend.SpendCapExceeded`
    propagates out of this function so `app.api.i18n.translate` can answer `429` rather than silently
    reporting "not translated" for a condition the caller can actually do something about (wait and
    retry). A batch that is entirely cache hits never calls `check` at all and cannot be rejected by it.
    """
    if not settings.translate_narratives:
        return [None] * len(texts)

    budget = AgentBudget(cap_usd=settings.translate_budget_usd)
    results: list[str | None] = []

    for text in texts:
        stripped = text.strip()
        if not stripped:
            results.append(None)
            continue

        cached = get_cached(stripped, locale=locale, data_dir=settings.data_dir)
        if cached is not None:
            results.append(cached)
            continue

        LEDGER.check(settings.model_spend_daily_cap_usd)
        translated, budget = _translate_one(stripped, settings=settings, budget=budget)
        if translated is not None:
            set_cached(stripped, translated, locale=locale, data_dir=settings.data_dir)
        results.append(translated)

    return results
