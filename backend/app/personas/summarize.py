"""Turns one ingested influencer item -- a YouTube transcript or a pasted drop -- into a structured
note draft: a summary, a handful of themes, verbatim quotes, and the tickers the influencer named
together with THEIR stance on each.

This module does not call a model API directly. It builds an `EvidencePack` out of the item's own
text and hands the call to `app.agentdesk.grounding.run_grounded`, the same retry-and-degrade loop
`app.tradingagents` and `app.vibedesk` already use -- see that module's docstring for the mechanism.
The only work that belongs here is (1) building the right evidence pack and prompt for *this* shape
of input, and (2) enforcing the two guardrails the wire contract (`docs/INFLUENCER-CONTRACT.md`) puts
on this feature specifically: a symbol must be validated before it leaves this module, and a note
must never rewrite the influencer's own words.

**How grounding actually applies to a transcript, not a fetched data pack.** Every other caller of
`run_grounded` hands it an `EvidencePack` built from numbers a data provider already measured --
a close, an RSI, a headline count -- via `EvidenceItem.value`. A transcript has no such structure: it
is one long block of prose, and `app.agentdesk.grounding.grounded_values` only ever reads
`EvidenceItem.value`, never `EvidenceSection.text` (see that function's own docstring on why quoting a
number *out of* free prose is exactly the fabrication the gate exists to catch). Feeding the whole
transcript in as a single `EvidenceItem.value` would not work either: it is not itself a decimal, so
`grounded_values` would just fail to parse it and skip it, leaving nothing grounded and rejecting
every number the model ever states -- including the ones the influencer actually said.

The fix used here is to extract every numeric token the source text itself contains, with
`app.agentdesk.grounding.numeric_tokens` -- the *exact* function `check()` later runs over the model's
own prose -- and mint one `EvidenceItem` per distinct token. That makes the two sides of the gate
symmetric by construction: a number the extractor would recognise as "a number worth checking" in the
model's output (not a bare small integer, not a date, not an indicator window) is exactly the class of
number admitted from the source, because the same function decided both. A number the influencer
never said has no matching item and is rejected; a number they did say, however the model chooses to
restate it (rounded, signed, computed as a difference -- see `grounded_values`' own tolerances), is
admitted. The full source text still goes to the model, verbatim, as the evidence section's free
`text` and the bulk of the user turn -- the per-token items exist purely to make the mechanical check
possible, not to change what the model is shown.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from app.agentdesk.grounding import numeric_tokens, run_grounded
from app.agentdesk.models import EvidenceItem, EvidencePack, EvidenceSection, GroundingVerdict
from app.agents.models import DEFAULT_MODEL, AgentBudget, AgentCall, AgentRole
from app.config import Settings
from app.personas.models import TickerMention

__all__ = [
    "MAX_SOURCE_CHARS",
    "NoteDraft",
    "SummaryResult",
    "summarize_item",
]

_log = logging.getLogger(__name__)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# The model's output shape
# ---------------------------------------------------------------------------


class NoteDraft(_Frozen):
    """What the model returns for one item, before ticker validation is applied.

    This is *not* `app.personas.models.EpisodicNote` -- it carries no ids, no timestamps, no vault
    path, none of the bookkeeping the caller (the ingest pipeline, owned by another worker) attaches
    once a note is actually persisted. It is the model's structured answer and nothing else.
    """

    summary: str
    """In `Settings.persona_summary_lang`, never the source language, even when the source is
    English -- a persona's notes should read consistently regardless of which channel they came
    from."""

    themes: tuple[str, ...]
    """2-5 short bullets: what the influencer is trading, watching, or focused on in this item. In
    `Settings.persona_summary_lang`. Not validated to that exact range here -- a model that returns
    one or six bullets on an unusually short or dense item is still a usable draft, and rejecting it
    outright would burn a grounding-retry attempt over a count, not a fact."""

    quotes: tuple[str, ...]
    """Verbatim, in the SOURCE language -- never translated, never paraphrased. See the module
    docstring's guardrail section and the contract's own "never rewritten" rule for episodic notes."""

    mentions: tuple[TickerMention, ...]
    """Every symbol the influencer named, with THEIR stance -- before this module's own validation
    pass. `summarize_item` drops entries whose `symbol` does not pass `symbol_validator`; what is
    still here on return from `run_grounded` is the model's raw claim, unfiltered."""


@dataclass(frozen=True)
class SummaryResult:
    """What `summarize_item` hands back: the (ticker-validated) draft, the grounding verdict that
    released it, and the full cost accounting -- mirroring `app.agentdesk.grounding.GroundedResult`,
    which this wraps rather than re-exposes directly (that type is keyed to `run_grounded`'s generic
    `T`, and callers of this module want a name specific to a persona note, not a bare `GroundedResult
    [NoteDraft]`)."""

    draft: NoteDraft
    verdict: GroundingVerdict
    budget: AgentBudget
    calls: tuple[AgentCall, ...]


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

#: A 21k-character transcript is the owner's own stated normal case, and some run considerably
#: longer. 60k characters is roughly a 90-minute video's worth of auto-caption text -- generous
#: enough that truncation is the exception, not the rule -- while still bounding the prompt (and the
#: per-call token cost `AgentBudget` is metered against) for the small number of outlier livestream
#: transcripts that would otherwise run for hours. Chosen as a plain module constant, not a
#: `Settings` field, because it is a prompt-engineering bound on this one call, not a piece of
#: deployment configuration anyone would reasonably want to override per install.
MAX_SOURCE_CHARS = 60_000


def _truncate(text: str) -> str:
    """`text`, capped at `MAX_SOURCE_CHARS` with an explicit marker when it was cut.

    Truncates the *tail*, not the head: a transcript's opening minutes are where a video states what
    it is about, and losing that would make the summary worse than losing the closing minutes would.
    The marker names how much was cut rather than just noting that it was, so a reader (and the model
    itself, since the marker sits inside the text it is asked to read) can tell how much of the source
    it never saw.
    """
    if len(text) <= MAX_SOURCE_CHARS:
        return text
    omitted = len(text) - MAX_SOURCE_CHARS
    marker = f"\n\n...[TRUNCATED -- {omitted} more character(s) of source omitted here]...\n"
    return text[:MAX_SOURCE_CHARS] + marker


# ---------------------------------------------------------------------------
# Evidence pack
# ---------------------------------------------------------------------------


def _build_evidence_pack(source_text: str) -> EvidencePack:
    """One `EvidencePack` whose single section carries the (possibly truncated) source verbatim as
    free `text`, plus one `EvidenceItem` per distinct numeric token the source contains -- see the
    module docstring for why the items, not the text, are what makes those numbers "grounded"."""
    tokens = sorted(set(numeric_tokens(source_text)))
    items = tuple(
        EvidenceItem(key=f"source_figure_{i}", label="Number stated in the source", value=token)
        for i, token in enumerate(tokens)
    )
    section = EvidenceSection(title="Source material", items=items, text=source_text)
    return EvidencePack(sections=(section,))


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

#: The role this call archives under. `AgentRole` (`app.agents.models`, pinned) is a closed set with
#: no member for the persona feature -- summarising an influencer item is not any of TradingAgents'
#: fixed pipeline roles, and it is not `app.evolution`'s designer/scout/reviewer either. `"swarm_worker"`
#: is VibeDesk's own precedent for exactly this situation: that package's own docstring says "every
#: preset worker archives under one role... which *seat* it was is preset data, not a code-level enum,
#: so it is recorded on the run's own task record rather than here." The same reasoning applies one
#: level up: *which persona* or *which source* this call served is recorded on the ingest job/note,
#: not on `AgentCall.role` -- widening the pinned `Literal` per feature would make adding a persona
#: source a Python edit in a file this shard is explicitly forbidden to touch.
_ROLE: AgentRole = "swarm_worker"

_SYSTEM_PROMPT = """You are a research-notes assistant. You read one piece of content from a financial-market \
influencer -- a YouTube video transcript (often auto-generated captions, which mangle names and tickers) or a \
pasted post -- and produce a structured note about what THEY said. You never add your own market opinion, \
forecast, price target, or recommendation anywhere in your output: your job is faithful reporting of one \
person's stated views, not analysis of your own.

LANGUAGE. The source may be in any language -- read it in whichever language it is actually written in, most \
often Korean or English. Write `summary` and every entry of `themes` in {lang}, regardless of the source \
language. Every entry of `quotes`, by contrast, must stay verbatim in the SOURCE's own original language -- \
never translate a quote, and never let a quote drift into paraphrase. A quote should be a short, load-bearing \
sentence or clause, not an entire paragraph.

TICKERS AND STANCE. For every publicly-traded instrument the speaker actually names or unambiguously refers \
to, add one entry to `mentions`:
- `symbol`: the ticker as best you can render it, uppercase. Auto-generated captions frequently mangle tickers \
  into ordinary words (e.g. a ticker rendered as a common English or Korean word) or invent plausible-looking \
  garbage -- if you are not reasonably confident of the actual ticker, still report your best reading; a \
  downstream check independently validates every symbol and drops anything that is not real, so guessing \
  the wrong sequence of letters here is far safer than inventing a stance for a ticker you dropped instead.
- `stance`: THE SPEAKER's own position -- "bullish", "bearish", "neutral", or "unclear". This field records \
  their call, never yours. If they merely discuss a name without committing to a direction, hedge, or you \
  cannot tell, use "unclear" rather than guessing a direction they did not actually state.
- `reasoning`: a short paraphrase of why, written in {lang}; you may embed one brief verbatim quote in quotes.
- `horizon`: the HOLDING HORIZON the speaker implied for this specific call -- "intraday" (a day-trade, \
  closed same session), "swing" (days to weeks), "position" (weeks to months), "long_term" (months or \
  longer, a core/conviction holding), or "unclear". A day-trader calling a name "bullish" for a scalp is an \
  intraday view, not a position to hold -- judge this from how THEY frame their own time frame for the \
  trade (their own words: "today", "this week", "for the next few months", "core holding", etc.), never from \
  the instrument or the stance alone. Use "unclear" whenever the speaker does not say how long they intend to \
  hold -- do not guess a horizon they never stated.
Never invent a ticker or an opinion the speaker did not express. If they name a company but say nothing \
resembling a view on it, still record the mention with `stance: "unclear"` and `horizon: "unclear"`.

NUMBERS. State a number -- a price, a level, a percentage, a count, a date -- only when it is actually spoken \
or written in the source. Never estimate one, round it to a plausible-sounding figure, or supply a number the \
source does not contain. If you want to reference a magnitude you are not sure is exactly as stated, describe \
it in words ("near its recent high") instead of writing a digit you are not certain of.

THEMES. 2 to 5 short bullets on what the speaker is trading, watching, or focused on in this item, in {lang}.

Respond with only the fields the schema asks for -- no extra commentary before or after."""


def _build_user_prompt(*, source_text: str, title: str | None, url: str, lang: str, summary_lang: str) -> str:
    """The user turn: the source verbatim (already truncated by the caller), plus the per-item
    framing `_SYSTEM_PROMPT` refers back to. Kept separate from `_build_evidence_pack` -- which reads
    the same `source_text` -- so there is exactly one truncated copy of the transcript, not two that
    could drift if truncation logic ever changed in only one place."""
    lang_hint = lang or "unknown -- identify it from the text itself"
    return (
        f"Title: {title or '(untitled)'}\n"
        f"URL: {url}\n"
        f"Source language hint: {lang_hint}\n"
        "\n"
        "--- SOURCE START ---\n"
        f"{source_text}\n"
        "--- SOURCE END ---\n"
        "\n"
        f"Summarize this item per your instructions. Write `summary` and `themes` in {summary_lang}. "
        "Keep every entry of `quotes` verbatim, in the source's own original language."
    )


def _draft_prose(draft: NoteDraft) -> str:
    """The text `run_grounded` checks for ungrounded numbers: `summary`, every theme, and every
    mention's `reasoning`, joined. Deliberately excludes `quotes` -- a quote is, by construction,
    copied verbatim from the source, so it can only ever restate a number that is already there, and
    running it through the same check a second time adds nothing but a chance for a transcription
    artefact (an auto-caption spacing a number differently than `numeric_tokens` expects) to degrade
    an otherwise-faithful note over text the model did not compose."""
    parts = [draft.summary, *draft.themes, *(m.reasoning for m in draft.mentions)]
    return "\n".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# Ticker validation -- ours to enforce, never the model's to self-police
# ---------------------------------------------------------------------------

#: 1-5 uppercase letters/digits/`.`/`-`, starting with a letter -- a conservative superset of the
#: instrument symbols this application actually trades (`BRK.B`, `BF-B`), applied only when the
#: caller has not supplied its own `symbol_validator` (the real instrument-table check, which lives
#: with `service.py`/`store.py`, outside this shard's scope fence). This default exists so the module
#: is safe to call standalone -- in a test, or before the real validator is wired up -- without ever
#: letting an auto-caption's mangled word (`"light"`, `"소수"`) through for want of a validator.
_DEFAULT_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,4}$")


def _default_symbol_ok(symbol: str) -> bool:
    return 1 <= len(symbol) <= 5 and bool(_DEFAULT_SYMBOL_RE.match(symbol))


def _validate_mentions(
    mentions: tuple[TickerMention, ...],
    symbol_validator: Callable[[str], bool] | None,
    *,
    url: str,
) -> tuple[TickerMention, ...]:
    """Drop every mention whose `symbol` fails validation; never guess a correction.

    This is the enforcement point the contract's guardrails name explicitly: auto-generated captions
    on 4 of the 5 seed channels mangle tickers badly enough that a Korean or English caption can
    render `"LITE"` as the ordinary word "light" and hallucinate a symbol out of nothing. The model is
    asked to report its best reading anyway (see `_SYSTEM_PROMPT`) because a downstream check -- this
    one -- is what actually decides whether a symbol is real; the model second-guessing itself before
    that check runs would just suppress mentions this function would have kept.

    Every drop is logged, not silently discarded -- `GroundingVerdict.issues` cannot carry this
    information itself: `GroundingIssue.kind` is a closed three-value `Literal` on the pinned
    `app.agentdesk.models`, and "a ticker failed validation" is not one of the three grounding
    failure kinds it enumerates. A module-level logger is the channel the task brief itself names as
    the alternative.
    """
    kept: list[TickerMention] = []
    dropped: list[str] = []
    validator = symbol_validator or _default_symbol_ok
    for mention in mentions:
        if validator(mention.symbol):
            kept.append(mention)
        else:
            dropped.append(mention.symbol)
    if dropped:
        _log.warning(
            "summarize_item(%s): dropped %d unvalidated ticker mention(s): %s",
            url, len(dropped), ", ".join(dropped),
        )
    return tuple(kept)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def summarize_item(
    *,
    text: str,
    title: str | None,
    url: str,
    settings: Settings,
    budget: AgentBudget,
    lang: str = "",
    symbol_validator: Callable[[str], bool] | None = None,
    model: str = DEFAULT_MODEL,
) -> SummaryResult:
    """Summarise one influencer item into a `NoteDraft`, grounded against its own text.

    **Never raises for a grounding failure.** `run_grounded` itself documents this: a stage that
    still fails its check on the last attempt is returned with `verdict.ok=False,
    verdict.degraded=True`, carrying whatever the model actually produced, and that is exactly what
    this function passes through on `SummaryResult` -- it does not re-interpret or upgrade the
    verdict. `AgentUnavailable` (no credential, a refusal) and `BudgetExhausted` (the run's spend
    ceiling) are a different kind of failure -- not a grounding outcome, but a reason this call could
    not be attempted or completed at all -- and `run_grounded` raises both unchanged; this function
    does not catch either, so they propagate to the caller exactly as documented.

    Ticker validation always runs, even on a degraded draft: a note released with unverified prose is
    still not licence to carry an unvalidated symbol into the vault.
    """
    truncated = _truncate(text)
    pack = _build_evidence_pack(truncated)
    summary_lang = settings.persona_summary_lang or "en"

    system = _SYSTEM_PROMPT.format(lang=summary_lang)
    user = _build_user_prompt(
        source_text=truncated, title=title, url=url, lang=lang, summary_lang=summary_lang,
    )

    grounded = run_grounded(
        role=_ROLE,
        system=system,
        user=user,
        output_format=NoteDraft,
        prose_of=_draft_prose,
        pack=pack,
        settings=settings,
        budget=budget,
        model=model,
    )

    validated_mentions = _validate_mentions(grounded.value.mentions, symbol_validator, url=url)
    draft = grounded.value.model_copy(update={"mentions": validated_mentions})

    return SummaryResult(
        draft=draft, verdict=grounded.verdict, budget=grounded.budget, calls=grounded.calls,
    )
