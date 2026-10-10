"""The idea scout: reads counted news facts for a lane's own pool and asks the model which tickers
are worth testing this generation, and why.

**Never a forecast.** `app.market.news`'s own contract (see that module's docstring) is that a
provider "may only report what it counted, never what it concluded" -- headline counts, publisher
names, labelled/unlabelled social message counts. This module hands the model exactly that, nothing
more, and the system prompt says explicitly that `ScoutPick.why` must stay about *coverage and
narrative* -- how much is being written, by whom, what the pieces are about -- never a prediction of
what a ticker will do. A scout that let a forecast slip through would break the one rule the news
layer exists to enforce, one layer up.

**Candidates come from the lane's own pool, never the model's imagination.** A card built from a
hallucinated ticker fails far downstream with a confusing error (no bars, no universe membership), or
worse, silently crosses a Roth/taxable boundary `app.evolution.universe` exists to keep disjoint. So
`scout_symbols` builds the candidate list itself -- from `app.evolution.universe.pool_for(purpose)`
unless the caller passed an explicit `candidates` tuple -- and re-checks every pick the model returns
against that same list afterward. A pick naming a symbol outside it is dropped, silently to the
caller's return value but never silently in the log.

**Degrades to `picks=()` rather than raising, at every failure boundary.** No credentials, no
`anthropic` package, an exhausted budget, a dead news chain, a refusal, a malformed response: all of
these leave the scout with nothing to say, which is a valid answer -- the loop is free to run a
generation with no news bias exactly as it would if `LoopConfig.use_news` were off. `ScoutReport.call`
is still required (see that model's own docstring) even when no model call was actually made; in that
case this module records a synthetic `AgentCall` whose `stop_reason` names why the call was never
attempted, so a reader of the audit trail sees "no credentials" rather than a call that mysteriously
returned nothing.
"""

from __future__ import annotations

import datetime as dt
import importlib
import uuid

from pydantic import BaseModel

from app.agents.models import (
    DEFAULT_MODEL,
    AgentBudget,
    AgentCall,
    AgentDisabled,
    AgentUnavailable,
    BudgetExhausted,
    ScoutPick,
    ScoutReport,
)
from app.config import Settings
from app.evolution.models import LoopConfig
from app.tournament.purposes import Purpose

__all__ = ["scout_symbols"]

#: Headlines pulled per candidate before being folded into the prompt. Small -- this is a scout
#: skimming coverage, not a research report -- and capped so a generation-sized candidate list (up to
#: twelve tickers, `ProposedCard.universe`'s own ceiling times a few) does not balloon the prompt.
_NEWS_LIMIT_PER_SYMBOL = 8

_SYSTEM_PROMPT = """You are the idea scout for an automated strategy-search loop. You are shown, for \
each candidate ticker in one investment lane's pool, the news headlines and social-message counts a \
market-data layer actually observed -- never a synthesized opinion, never a price forecast.

Your job is to say which of these tickers are worth the search spending a generation's compute \
testing this round, and why. `why` must be about *coverage and narrative only*: how much is being \
written about a name, by whom, what the pieces are about, whether there is more or less chatter than \
usual. `why` must never be a forecast, a price target, a buy/sell call, or any claim about what a \
ticker will do next -- that judgement belongs to the backtest that follows, not to you. If nothing in \
the pool stands out, return an empty pick list rather than inventing a reason.

Only ever name a ticker from the candidate list you were given. Never propose a symbol that is not in \
that list."""


class _ScoutOutput(BaseModel):
    """The shape `app.agents.client.call_structured` is asked to parse the model's JSON into.

    Deliberately not `ScoutReport` itself: `ScoutReport.call` is filled in here, after the call
    returns, from the `AgentCall` the client hands back -- the model is never asked to describe its
    own call.
    """

    picks: tuple[ScoutPick, ...] = ()
    theme: str = ""


def _resolved_model(config: LoopConfig) -> str:
    return config.agent_model or DEFAULT_MODEL


def _synthetic_call(*, model: str, reason: str) -> AgentCall:
    """An audit record for a scout report produced with no model call, so the trail says *why* the
    picks are empty instead of leaving that to be inferred from an absent record.

    Not a lie: `system`/`user`/`raw_response` are left empty (nothing was sent or returned), and
    `stop_reason` carries the actual reason the call was never attempted -- the one field on
    `AgentCall` documented as "checked before the response is read", which makes it the natural place
    to record "there was no response to read."
    """
    return AgentCall(
        call_id=f"scout-skipped-{uuid.uuid4().hex}",
        role="scout",
        model=model,
        created_at=dt.datetime.now(dt.UTC),
        system="",
        user="",
        raw_response="",
        stop_reason=reason,
    )


def _empty_report(*, model: str, reason: str) -> ScoutReport:
    return ScoutReport(picks=(), theme="", call=_synthetic_call(model=model, reason=reason))


def _summarize_candidate(symbol: str, settings: Settings) -> tuple[str, bool]:
    """One candidate's counted news facts, rendered as the prompt lines the model sees for it, plus
    whether the lookup actually produced anything (`False` only when `build_ticker_panel` itself
    raised -- a panel that came back with no headlines and no social data, but *did* come back, still
    counts as `True`, since that is a real, if empty, observation rather than a failure to observe).

    `build_ticker_panel` is documented to never raise a `ProviderError` past its own boundary (see
    that module's docstring) -- a dead upstream degrades into an empty section plus a warning, not an
    exception. The `except Exception` below therefore only ever catches a genuinely unexpected failure
    (a bug in this module's own formatting, or a caller-error `ValueError` from a naive `as_of` --
    neither of which this function passes). It exists anyway because "the news layer throws" has to
    degrade the same way every other failure boundary in this module does: caught here, reported to
    the caller via the `bool`, never raised.
    """
    from app.market.news import build_ticker_panel

    try:
        panel = build_ticker_panel(settings, symbol, limit=_NEWS_LIMIT_PER_SYMBOL)
    except Exception as exc:
        return f"### {symbol}\n- news unavailable ({type(exc).__name__}: {exc})", False

    lines = [f"### {symbol}"]
    if panel.news:
        lines.append(f"- {len(panel.news)} headline(s), source={panel.news_source or 'unknown'}:")
        for item in panel.news[:5]:
            publisher = item.publisher or item.source
            lines.append(f'  - "{item.title}" ({publisher}, {item.published.date().isoformat()})')
    else:
        lines.append("- no headlines available")

    if panel.social is not None:
        snap = panel.social.snapshot
        lines.append(
            f"- social counts: {snap.bullish} bullish / {snap.bearish} bearish / "
            f"{snap.neutral} unlabelled (source={snap.source})"
        )
    else:
        lines.append("- social counts unavailable")

    if panel.warnings:
        lines.append(f"- warnings: {'; '.join(w.message for w in panel.warnings)}")

    return "\n".join(lines), True


def scout_symbols(
    *,
    purpose: Purpose,
    config: LoopConfig,
    settings: Settings,
    budget: AgentBudget,
    limit: int = 6,
    candidates: tuple[str, ...] | None = None,
) -> tuple[ScoutReport, AgentBudget]:
    """Which of this lane's pool tickers are worth biasing this generation toward, and why.

    `candidates` defaults to `None`, which resolves to `app.evolution.universe.pool_for(purpose).
    all_symbols()` -- imported lazily so a Roth lane can never accidentally be handed a taxable
    ticker by a caller who forgot to scope it, and so this module does not pay for importing the
    universe package until a scout call actually happens. Passing `candidates` explicitly (what this
    module's own tests do) bypasses the pool lookup entirely.

    Returns `(report, budget)` rather than mutating `budget` in place -- `AgentBudget` is frozen (see
    its own docstring on why `app.agents.client` returns a new one per call), and the caller (the
    evolution loop) is expected to replace its own tracked budget with whatever this function hands
    back, spent or not.

    Never raises. Every failure boundary below -- no candidates, the `app.agents` package or its
    credentials unavailable, an exhausted budget, the model call itself failing in any way -- returns
    `picks=()` with a synthetic, unspent-or-passthrough budget rather than propagating an exception
    into the loop that called this.
    """
    model = _resolved_model(config)

    if candidates is not None:
        candidate_symbols = tuple(candidates)
    else:
        from app.evolution.universe import pool_for

        candidate_symbols = pool_for(purpose).all_symbols()

    if not candidate_symbols:
        return _empty_report(model=model, reason="no candidate symbols for this lane's pool"), budget

    # `importlib.import_module`, not `from app.agents import client`, for the same reason
    # `app.api.agents.health` uses it -- deterministic behaviour against `sys.modules` both when the
    # module is genuinely absent and when a test double stands in for it.
    try:
        client_module = importlib.import_module("app.agents.client")
    except ModuleNotFoundError as exc:
        return _empty_report(model=model, reason=f"app.agents.client not importable: {exc}"), budget

    available, availability_reason = client_module.is_available()
    if not available:
        return _empty_report(model=model, reason=f"unavailable: {availability_reason}"), budget

    if budget.exhausted:
        return _empty_report(model=model, reason="agent budget exhausted"), budget

    summaries = [_summarize_candidate(symbol, settings) for symbol in candidate_symbols]
    if not any(ok for _text, ok in summaries):
        # Every candidate's news lookup failed outright -- not "no news today" (that degrades into a
        # normal, if sparse, section) but the news layer itself throwing for every single symbol.
        # Sending the model a wall of "unavailable" lines and asking it to pick anyway would invite it
        # to invent coverage it never actually saw, so this returns empty rather than call at all.
        return _empty_report(model=model, reason="news layer unavailable for every candidate"), budget

    sections = "\n\n".join(text for text, _ok in summaries)
    user = (
        f"Lane: {purpose.value}\n"
        f"Candidate tickers (only these are valid picks): {', '.join(candidate_symbols)}\n"
        f"Return at most {limit} pick(s).\n\n"
        f"{sections}"
    )

    try:
        result, call, new_budget = client_module.call_structured(
            role="scout",
            system=_SYSTEM_PROMPT,
            user=user,
            output_format=_ScoutOutput,
            model=model,
            settings=settings,
            budget=budget,
        )
    except (AgentUnavailable, BudgetExhausted, AgentDisabled) as exc:
        return _empty_report(model=model, reason=f"{type(exc).__name__}: {exc}"), budget
    except Exception as exc:  # a refusal, a malformed response, a timeout -- degrade, never raise
        return _empty_report(model=model, reason=f"{type(exc).__name__}: {exc}"), budget

    valid = set(candidate_symbols)
    # Reject any pick naming a symbol outside the candidate list -- a hallucinated ticker must not
    # reach the proposer. Silent to the caller's return value (a dropped pick just is not there); not
    # silent to the audit trail, since `call.raw_response` still carries what the model actually said.
    picks = tuple(pick for pick in result.picks if pick.symbol in valid)[:limit]

    return ScoutReport(picks=picks, theme=result.theme, call=call), new_budget
