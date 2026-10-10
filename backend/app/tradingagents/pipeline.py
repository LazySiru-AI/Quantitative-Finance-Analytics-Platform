"""The fourteen-stage orchestration itself -- see `app.tradingagents`'s own module docstring for why
this is a plain sequence with two bounded counting loops rather than a graph runtime.

**One `AgentBudget` threads through the whole run.** Every stage's call spends against the same
running total, and `DeskRun.budget` is updated on every single stage transition (not just at the
end) so a poll landing mid-run sees live spend -- see `_run_role_stage`, the one function that both
calls a stage and persists that update.

**Fail-fast, not fault-tolerant.** Unlike `app.vibedesk.runtime.run_swarm`, which keeps driving a
preset's DAG through other branches after one task fails (a defensible choice for a DAG with
independent branches), this pipeline is a strict sequence: a debate turn with no trader proposal to
stress, or a portfolio manager with no risk panel to weigh, is not a smaller version of the report --
it is a different, broken one. So a stage that raises `BudgetExhausted` or `AgentUnavailable` fails
the run outright: that stage is marked `"failed"`, every later stage is marked `"blocked"`, and
`run_pipeline` returns immediately. A stage that merely fails its grounding check after
`MAX_GROUNDING_ATTEMPTS` retries is a different outcome entirely -- `"degraded"`, not `"failed"` --
and the pipeline continues, because `run_grounded` itself never raises for that case (see its own
docstring).

**What each stage is allowed to see.** Analysts each build their own narrow `EvidencePack` (see
`_ANALYST_SECTIONS`). Every stage downstream of the analysts -- both researchers, the research
manager, the trader, the risk panel and the portfolio manager -- shares one wider pack, built once and
reused, covering the union of what an analyst read (`_UNION_SECTIONS`) so their numbers stay
verifiable through the whole rest of the run. Downstream stages receive upstream *summaries*, never
full reports, in the user turn -- matching `StageRecord.summary`'s own contract, restated here for
`app.tradingagents` specifically because there is no shared "swarm" abstraction doing it generically
the way `app.vibedesk.runtime._build_user_turn` does for presets.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import cast

from pydantic import BaseModel

from app.agentdesk import evidence
from app.agentdesk.grounding import run_grounded
from app.agentdesk.models import DeskRun, EvidencePack, EvidenceSection, StageRecord, StageState
from app.agentdesk.store import RunStore, with_stage
from app.agents.models import AgentBudget, AgentRole, AgentUnavailable, BudgetExhausted
from app.config import Settings
from app.market import livefeed
from app.tradingagents import memory, prompts, schemas

__all__ = [
    "MAX_ROUNDS",
    "PipelineConfig",
    "analyst_sections",
    "build_stage_plan",
    "clamp_rounds",
    "run_pipeline",
    "union_sections",
]

logger = logging.getLogger(__name__)

#: The contract's own ceiling on `debate_rounds`/`risk_rounds` -- see `docs/AGENT-DESK-CONTRACT.md`'s
#: `TradingAgentsConfig.max_rounds`.
MAX_ROUNDS = 3


def clamp_rounds(rounds: int) -> int:
    """A debate/risk round count, clamped to the pipeline's supported `1..MAX_ROUNDS` range."""
    return max(1, min(MAX_ROUNDS, rounds))


@dataclass(frozen=True)
class PipelineConfig:
    """One run's parameters -- what `app.tradingagents.service.start_run` builds from
    `StartRunRequest` before handing the run to the job registry."""

    symbol: str
    trade_date: dt.date | None
    analysts: tuple[str, ...]
    debate_rounds: int
    risk_rounds: int
    budget_usd: Decimal
    model: str

    live: bool = False
    """Whether this run reads the *current* market as well as the stored session.

    Defaulted `False` so a run built the way every caller before this feature built one is unchanged
    in every respect -- same sections, same `As of:` line, same prompt bytes. When `True` the market
    and sentiment analysts additionally see `live_quote` and `intraday`, the shared downstream pack
    gains `live_quote`, and the `As of:` line names the wall clock instead of a session (see
    `analyst_sections`, `union_sections` and `_as_of_line`). A live run is therefore explicitly *not*
    reproducible: two runs a minute apart read different quotes, which is the whole point and is why
    it is opt-in per run rather than a setting.

    `app.tradingagents.service.start_run` refuses `live=True` together with a past `trade_date` --
    the two live evidence sections return empty for a historical `as_of` anyway (see
    `app.agentdesk.evidence._is_historical`), so such a run would silently be a non-live run wearing
    a live label.
    """


# ---------------------------------------------------------------------------
# The stage plan -- fixed ids/labels/layers, per docs/AGENT-DESK-CONTRACT.md
# ---------------------------------------------------------------------------

_ANALYST_DEFS: tuple[tuple[str, str, str], ...] = (
    ("market", "market_analyst", "Market Analyst"),
    ("sentiment", "sentiment_analyst", "Sentiment Analyst"),
    ("news", "news_analyst", "News Analyst"),
    ("fundamentals", "fundamentals_analyst", "Fundamentals Analyst"),
)


def build_stage_plan(config: PipelineConfig) -> tuple[StageRecord, ...]:
    """Every stage this run will ever touch, all `"pending"`, in the fixed order
    `docs/AGENT-DESK-CONTRACT.md`'s stage table pins.

    `depends_on` holds each stage's single predecessor -- see `StageRecord.depends_on`'s own docstring
    for why a TradingAgents stage carries exactly one, unlike a VibeDesk task's preset-declared set:
    this pipeline is a strict sequence, and the analyst stages that look independent are simply the
    first few links in it, run one after another rather than concurrently.
    """
    stages: list[StageRecord] = []
    previous_id: str | None = None

    def _add(stage_id: str, role: str, label: str, layer: int) -> None:
        nonlocal previous_id
        depends_on = (previous_id,) if previous_id is not None else ()
        stages.append(
            StageRecord(
                stage_id=stage_id,
                role=cast("AgentRole", role),
                label=label,
                layer=layer,
                depends_on=depends_on,
            )
        )
        previous_id = stage_id

    for key, stage_id, label in _ANALYST_DEFS:
        if key in config.analysts:
            _add(stage_id, stage_id, label, 0)

    debate_rounds = clamp_rounds(config.debate_rounds)
    for n in range(1, debate_rounds + 1):
        _add(f"bull_{n}", "bull_researcher", f"Bull Researcher (round {n})", 1)
        _add(f"bear_{n}", "bear_researcher", f"Bear Researcher (round {n})", 1)

    _add("research_manager", "research_manager", "Research Manager", 2)
    _add("trader", "trader", "Trader", 3)

    risk_rounds = clamp_rounds(config.risk_rounds)
    for n in range(1, risk_rounds + 1):
        _add(f"risk_aggressive_{n}", "risk_aggressive", f"Aggressive Analyst (round {n})", 4)
        _add(f"risk_conservative_{n}", "risk_conservative", f"Conservative Analyst (round {n})", 4)
        _add(f"risk_neutral_{n}", "risk_neutral", f"Neutral Analyst (round {n})", 4)

    _add("portfolio_manager", "portfolio_manager", "Portfolio Manager", 5)

    return tuple(stages)


# ---------------------------------------------------------------------------
# Evidence sections per stage kind
# ---------------------------------------------------------------------------

_ANALYST_SECTIONS: dict[str, tuple[str, ...]] = {
    "market_analyst": ("price", "indicators"),
    "sentiment_analyst": ("price", "indicators", "social"),
    "news_analyst": ("news", "macro", "events"),
    "fundamentals_analyst": ("fundamentals",),
}

#: The pack every stage from the debate onward shares -- the union of what an analyst read, so a
#: researcher's, judge's or risk analyst's own numbers stay checkable against the same facts.
_UNION_SECTIONS: tuple[str, ...] = ("price", "indicators", "news", "fundamentals")

#: What a live run adds, in `app.agentdesk.evidence.SECTION_KEYS` order. Given to the two analysts
#: whose subject is the tape itself -- market (price action) and sentiment (how the tape is being
#: read) -- and not to the news or fundamentals analysts, whose sources do not move minute to minute
#: and who would only gain a number they have no use for.
_LIVE_SECTIONS: tuple[str, ...] = ("live_quote", "intraday")

#: Which live sections reach the shared downstream pack. `live_quote` only: the debate, the trader and
#: the risk panel need the current price to check an analyst's claim about it, but the intraday bar
#: table is analyst-level detail that would push the same twenty-four rows into every one of a dozen
#: later prompts for nothing.
_LIVE_UNION_SECTIONS: tuple[str, ...] = ("live_quote",)

#: The analysts a live run widens. See `_LIVE_SECTIONS`.
_LIVE_ANALYSTS: frozenset[str] = frozenset({"market_analyst", "sentiment_analyst"})


def analyst_sections(stage_id: str, *, live: bool = False) -> tuple[str, ...]:
    """The evidence sections one analyst stage reads, given whether this is a live run.

    A non-live run returns `_ANALYST_SECTIONS[stage_id]` unchanged -- byte-identical to what the
    pipeline built before the live opt-in existed, which `tests/test_tradingagents.py` pins directly.
    """
    base = _ANALYST_SECTIONS[stage_id]
    if live and stage_id in _LIVE_ANALYSTS:
        return (*base, *_LIVE_SECTIONS)
    return base


def union_sections(*, live: bool = False) -> tuple[str, ...]:
    """The shared downstream pack's sections. `_UNION_SECTIONS` unchanged unless this run is live."""
    return (*_UNION_SECTIONS, *_LIVE_UNION_SECTIONS) if live else _UNION_SECTIONS


# ---------------------------------------------------------------------------
# Mutable run context -- everything a later stage needs from an earlier one
# ---------------------------------------------------------------------------


@dataclass
class _RunContext:
    settings: Settings
    config: PipelineConfig
    analyst_summaries: dict[str, str] = field(default_factory=dict)
    analyst_pack_union: EvidencePack | None = None
    debate_transcript: list[str] = field(default_factory=list)
    research_plan: schemas.ResearchPlan | None = None
    trader_proposal: schemas.TraderProposal | None = None
    risk_transcript: list[str] = field(default_factory=list)


def _round_number(stage_id: str) -> int:
    return int(stage_id.rsplit("_", 1)[-1])


def _find_stage(run: DeskRun, stage_id: str) -> StageRecord:
    return next(stage for stage in run.stages if stage.stage_id == stage_id)


def _mark_stages(run: DeskRun, stage_ids: Sequence[str], *, state: StageState, error: str = "") -> DeskRun:
    for stage_id in stage_ids:
        run = with_stage(run, stage_id, state=state, error=error)
    return run


def _as_of_line(trade_date: dt.date | None, *, live: bool = False) -> str:
    """The `As of:` value in an analyst's user turn.

    A live run names the wall clock -- `live · 2026-09-08T14:32:05.123456+00:00` -- rather than a
    session, because that is literally what the pack it is about to read was built against, and an
    analyst told "as of the latest stored session" while holding a quote from thirty seconds ago has
    been handed two different answers to the same question. The timestamp is a full ISO-8601 UTC one,
    which `app.agentdesk.grounding` scrubs whole before extracting numeric tokens, so an analyst that
    quotes its own as-of stamp back is not degraded for it.
    """
    if live:
        return f"live · {dt.datetime.now(dt.UTC).isoformat()}"
    return trade_date.isoformat() if trade_date else "the latest stored session"


# ---------------------------------------------------------------------------
# One stage: call, grade, persist
# ---------------------------------------------------------------------------


def _run_role_stage[T: BaseModel](
    run: DeskRun,
    store: RunStore,
    stage_id: str,
    *,
    role: AgentRole,
    system: str,
    user: str,
    pack: EvidencePack,
    output_format: type[T],
    prose_of: Callable[[T], str],
    render: Callable[[T], str],
    summary: Callable[[T], str],
    settings: Settings,
    budget: AgentBudget,
    model: str,
) -> tuple[DeskRun, AgentBudget, T]:
    """Run one stage's grounded call and persist its outcome, in the two saves every stage gets: one
    marking it `"running"` (visible to a poll mid-call), one recording its result.

    Raises `BudgetExhausted`/`AgentUnavailable` straight through -- this function never marks the
    stage `"failed"` itself, because `run_pipeline`'s own caller needs the exception's `spent_usd`
    (for `BudgetExhausted`) before it can build the correct terminal `AgentBudget`; see
    `run_pipeline`'s own docstring.
    """
    run = with_stage(run, stage_id, state="running", started_at=dt.datetime.now(dt.UTC))
    store.save(run)

    result = run_grounded(
        role=role,
        system=system,
        user=user,
        output_format=output_format,
        prose_of=prose_of,
        pack=pack,
        settings=settings,
        budget=budget,
        model=model,
    )

    state: StageState = "succeeded" if result.verdict.ok else "degraded"
    cost = sum((call.cost_usd for call in result.calls), Decimal(0))
    run = with_stage(
        run,
        stage_id,
        state=state,
        completed_at=dt.datetime.now(dt.UTC),
        output_md=render(result.value),
        summary=summary(result.value),
        grounding=result.verdict,
        call_ids=tuple(call.call_id for call in result.calls),
        cost_usd=cost,
    )
    run_update: dict[str, object] = {"budget": result.budget}
    if state == "degraded":
        run_update["degraded"] = True
    run = run.model_copy(update=run_update)
    store.save(run)
    return run, result.budget, result.value


# ---------------------------------------------------------------------------
# Per-stage-kind dispatch
# ---------------------------------------------------------------------------


def _run_analyst(
    run: DeskRun, store: RunStore, stage: StageRecord, ctx: _RunContext, budget: AgentBudget
) -> tuple[DeskRun, AgentBudget]:
    sections = analyst_sections(stage.stage_id, live=ctx.config.live)
    pack = evidence.build_pack(ctx.config.symbol, ctx.config.trade_date, settings=ctx.settings, sections=sections)
    user = (
        f"Instrument: {ctx.config.symbol}\n"
        f"As of: {_as_of_line(ctx.config.trade_date, live=ctx.config.live)}\n\n"
        f"EVIDENCE:\n{evidence.render_pack(pack)}"
    )
    run, budget, _value = _run_role_stage(
        run, store, stage.stage_id,
        role=stage.role, system=prompts.SYSTEM_FOR_ROLE[stage.role], user=user, pack=pack,
        output_format=schemas.AnalystReport, prose_of=schemas.prose_of_analyst_report,
        render=schemas.render_analyst_report, summary=schemas.summary_analyst_report,
        settings=ctx.settings, budget=budget, model=ctx.config.model,
    )
    ctx.analyst_summaries[stage.label] = _find_stage(run, stage.stage_id).summary
    return run, budget


def _run_debate_turn(
    run: DeskRun, store: RunStore, stage: StageRecord, ctx: _RunContext, budget: AgentBudget
) -> tuple[DeskRun, AgentBudget]:
    assert ctx.analyst_pack_union is not None
    pack = ctx.analyst_pack_union
    round_n = _round_number(stage.stage_id)
    side = "Bull" if stage.stage_id.startswith("bull_") else "Bear"
    summaries_block = "\n\n".join(
        f"### {label}\n{text}" for label, text in ctx.analyst_summaries.items()
    ) or "(no analyst reports were selected for this run)"
    history_block = "\n\n".join(ctx.debate_transcript) or "(this is the opening turn)"
    user = (
        f"Instrument: {ctx.config.symbol}\n"
        f"Debate round {round_n} -- your turn as the {side.lower()} researcher.\n\n"
        f"ANALYST SUMMARIES:\n{summaries_block}\n\n"
        f"DEBATE SO FAR:\n{history_block}\n\n"
        f"EVIDENCE:\n{evidence.render_pack(pack)}"
    )
    run, budget, _value = _run_role_stage(
        run, store, stage.stage_id,
        role=stage.role, system=prompts.SYSTEM_FOR_ROLE[stage.role], user=user, pack=pack,
        output_format=schemas.DebateArgument, prose_of=schemas.prose_of_debate_argument,
        render=schemas.render_debate_argument, summary=schemas.summary_debate_argument,
        settings=ctx.settings, budget=budget, model=ctx.config.model,
    )
    output = _find_stage(run, stage.stage_id).output_md
    ctx.debate_transcript.append(f"**{side} researcher, round {round_n}:**\n{output}")
    return run, budget


def _run_research_manager(
    run: DeskRun, store: RunStore, stage: StageRecord, ctx: _RunContext, budget: AgentBudget
) -> tuple[DeskRun, AgentBudget]:
    assert ctx.analyst_pack_union is not None
    pack = ctx.analyst_pack_union
    summaries_block = "\n\n".join(
        f"### {label}\n{text}" for label, text in ctx.analyst_summaries.items()
    ) or "(no analyst reports were selected for this run)"
    debate_block = "\n\n".join(ctx.debate_transcript) or "(no debate was run)"
    user = (
        f"Instrument: {ctx.config.symbol}\n\n"
        f"ANALYST SUMMARIES:\n{summaries_block}\n\n"
        f"FULL BULL/BEAR DEBATE:\n{debate_block}\n\n"
        f"EVIDENCE:\n{evidence.render_pack(pack)}"
    )
    run, budget, value = _run_role_stage(
        run, store, stage.stage_id,
        role="research_manager", system=prompts.SYSTEM_FOR_ROLE["research_manager"], user=user, pack=pack,
        output_format=schemas.ResearchPlan, prose_of=schemas.prose_of_research_plan,
        render=schemas.render_research_plan, summary=schemas.summary_research_plan,
        settings=ctx.settings, budget=budget, model=ctx.config.model,
    )
    ctx.research_plan = value
    return run, budget


def _run_trader(
    run: DeskRun, store: RunStore, stage: StageRecord, ctx: _RunContext, budget: AgentBudget
) -> tuple[DeskRun, AgentBudget]:
    assert ctx.analyst_pack_union is not None and ctx.research_plan is not None
    pack = ctx.analyst_pack_union
    user = (
        f"Instrument: {ctx.config.symbol}\n\n"
        f"RESEARCH PLAN:\n{schemas.render_research_plan(ctx.research_plan)}\n\n"
        f"EVIDENCE:\n{evidence.render_pack(pack)}"
    )
    run, budget, value = _run_role_stage(
        run, store, stage.stage_id,
        role="trader", system=prompts.SYSTEM_FOR_ROLE["trader"], user=user, pack=pack,
        output_format=schemas.TraderProposal, prose_of=schemas.prose_of_trader_proposal,
        render=schemas.render_trader_proposal, summary=schemas.summary_trader_proposal,
        settings=ctx.settings, budget=budget, model=ctx.config.model,
    )
    ctx.trader_proposal = value
    return run, budget


def _run_risk_turn(
    run: DeskRun, store: RunStore, stage: StageRecord, ctx: _RunContext, budget: AgentBudget
) -> tuple[DeskRun, AgentBudget]:
    assert ctx.analyst_pack_union is not None and ctx.trader_proposal is not None
    pack = ctx.analyst_pack_union
    round_n = _round_number(stage.stage_id)
    history_block = "\n\n".join(ctx.risk_transcript) or "(this is the opening turn)"
    user = (
        f"Instrument: {ctx.config.symbol}\n"
        f"Risk panel round {round_n}.\n\n"
        f"TRADER PROPOSAL:\n{schemas.render_trader_proposal(ctx.trader_proposal)}\n\n"
        f"PANEL DISCUSSION SO FAR:\n{history_block}\n\n"
        f"EVIDENCE:\n{evidence.render_pack(pack)}"
    )
    run, budget, _value = _run_role_stage(
        run, store, stage.stage_id,
        role=stage.role, system=prompts.SYSTEM_FOR_ROLE[stage.role], user=user, pack=pack,
        output_format=schemas.RiskArgument, prose_of=schemas.prose_of_risk_argument,
        render=schemas.render_risk_argument, summary=schemas.summary_risk_argument,
        settings=ctx.settings, budget=budget, model=ctx.config.model,
    )
    output = _find_stage(run, stage.stage_id).output_md
    ctx.risk_transcript.append(f"**{stage.label}:**\n{output}")
    return run, budget


def _run_portfolio_manager(
    run: DeskRun, store: RunStore, stage: StageRecord, ctx: _RunContext, budget: AgentBudget
) -> tuple[DeskRun, AgentBudget]:
    assert (
        ctx.analyst_pack_union is not None
        and ctx.research_plan is not None
        and ctx.trader_proposal is not None
    )
    base_pack = ctx.analyst_pack_union

    lessons_text = memory.lessons_for_prompt(ctx.config.symbol, settings=ctx.settings)
    lessons_items = memory.lessons_evidence_items(ctx.config.symbol, settings=ctx.settings)
    if lessons_items:
        memory_section = EvidenceSection(title="Desk memory", items=lessons_items)
        pack = base_pack.model_copy(update={"sections": (*base_pack.sections, memory_section)})
    else:
        pack = base_pack

    risk_block = "\n\n".join(ctx.risk_transcript) or "(no risk panel discussion)"
    lessons_block = lessons_text or "This desk has no resolved past decisions on this or any instrument yet."
    user = (
        f"Instrument: {ctx.config.symbol}\n\n"
        f"RESEARCH PLAN:\n{schemas.render_research_plan(ctx.research_plan)}\n\n"
        f"TRADER PROPOSAL:\n{schemas.render_trader_proposal(ctx.trader_proposal)}\n\n"
        f"RISK PANEL DISCUSSION:\n{risk_block}\n\n"
        f"PAST DECISIONS (this desk's memory):\n{lessons_block}\n\n"
        f"EVIDENCE:\n{evidence.render_pack(pack)}"
    )
    run, budget, _value = _run_role_stage(
        run, store, stage.stage_id,
        role="portfolio_manager", system=prompts.SYSTEM_FOR_ROLE["portfolio_manager"], user=user, pack=pack,
        output_format=schemas.PortfolioDecision, prose_of=schemas.prose_of_portfolio_decision,
        render=schemas.render_portfolio_decision, summary=schemas.summary_portfolio_decision,
        settings=ctx.settings, budget=budget, model=ctx.config.model,
    )
    return run, budget


def _dispatch_stage(
    run: DeskRun, store: RunStore, stage: StageRecord, ctx: _RunContext, budget: AgentBudget
) -> tuple[DeskRun, AgentBudget]:
    stage_id = stage.stage_id
    if stage_id in _ANALYST_SECTIONS:
        return _run_analyst(run, store, stage, ctx, budget)
    if stage_id.startswith("bull_") or stage_id.startswith("bear_"):
        return _run_debate_turn(run, store, stage, ctx, budget)
    if stage_id == "research_manager":
        return _run_research_manager(run, store, stage, ctx, budget)
    if stage_id == "trader":
        return _run_trader(run, store, stage, ctx, budget)
    if stage_id.startswith("risk_"):
        return _run_risk_turn(run, store, stage, ctx, budget)
    if stage_id == "portfolio_manager":
        return _run_portfolio_manager(run, store, stage, ctx, budget)
    raise AssertionError(f"unhandled tradingagents stage id {stage_id!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# The job target
# ---------------------------------------------------------------------------


def run_pipeline(run_id: str, config: PipelineConfig, *, settings: Settings, cancel: threading.Event) -> None:
    """Drive one run's stages to completion, cancellation, or failure, saving a new `DeskRun`
    snapshot after every stage transition -- the job target `app.tradingagents.service.start_run`
    hands to `app.agentdesk.jobs.registry()`.

    Assumes `run_id` already has a persisted `DeskRun` (written by `start_run`) whose `stages` match
    `build_stage_plan(config)` exactly; this function only ever transitions those stages, never
    invents or drops one.
    """
    store = RunStore(settings, "tradingagents")
    run = store.load(run_id)
    if run is None:  # pragma: no cover - defensive; start_run always saves before starting the job
        logger.error("tradingagents pipeline: run %r vanished from the store before it could start", run_id)
        return

    run = run.model_copy(update={"state": "running"})
    store.save(run)

    if config.live:
        # Best-effort, and deliberately not fatal: `watch` only tells the keep-warm daemon to hold
        # this symbol open from its next tick, so a failure here (or a daemon that is not running at
        # all, the default) costs a cold synchronous fetch per section, not the run. The evidence
        # layer's own `live_quote` section fetches on demand either way.
        try:
            livefeed.watch([config.symbol])
        except Exception:
            logger.warning("tradingagents: could not watch %s for a live run", config.symbol, exc_info=True)

    ctx = _RunContext(settings=settings, config=config)
    ctx.analyst_pack_union = evidence.build_pack(
        config.symbol, config.trade_date, settings=settings, sections=union_sections(live=config.live)
    )

    budget = run.budget
    stage_ids = [stage.stage_id for stage in run.stages]

    for index, stage in enumerate(run.stages):
        if cancel.is_set():
            run = _mark_stages(run, stage_ids[index:], state="skipped", error="run cancelled")
            run = run.model_copy(
                update={"state": "cancelled", "completed_at": dt.datetime.now(dt.UTC), "budget": budget}
            )
            store.save(run)
            return

        try:
            run, budget = _dispatch_stage(run, store, stage, ctx, budget)
        except BudgetExhausted as exc:
            # `exc.spent_usd` is the true running total, including whatever this stage's own
            # `run_grounded` retry loop already spent before the cap was hit -- see
            # `_run_role_stage`'s own docstring for why this function, not that one, recovers it.
            budget = AgentBudget(cap_usd=exc.cap_usd, spent_usd=exc.spent_usd, calls=budget.calls)
            run = with_stage(run, stage.stage_id, state="failed", error=str(exc), completed_at=dt.datetime.now(dt.UTC))
            run = _mark_stages(
                run, stage_ids[index + 1 :], state="blocked",
                error="blocked: an earlier stage in the pipeline failed",
            )
            run = run.model_copy(
                update={"state": "failed", "error": str(exc), "completed_at": dt.datetime.now(dt.UTC), "budget": budget}
            )
            store.save(run)
            return
        except AgentUnavailable as exc:
            # No cost was incurred on this stage's own account -- `call_structured` raises
            # `AgentUnavailable` for every transport/auth failure before a response exists to price.
            run = with_stage(run, stage.stage_id, state="failed", error=str(exc), completed_at=dt.datetime.now(dt.UTC))
            run = _mark_stages(
                run, stage_ids[index + 1 :], state="blocked",
                error="blocked: an earlier stage in the pipeline failed",
            )
            run = run.model_copy(
                update={"state": "failed", "error": str(exc), "completed_at": dt.datetime.now(dt.UTC), "budget": budget}
            )
            store.save(run)
            return

    final_stage = run.stages[-1]
    run = run.model_copy(
        update={
            "state": "succeeded",
            "completed_at": dt.datetime.now(dt.UTC),
            "final_md": final_stage.output_md,
            "final_rating": schemas.parse_rating(final_stage.output_md),
            "budget": budget,
        }
    )
    store.save(run)
    memory.append_pending(run, config, settings=settings)
