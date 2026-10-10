"""The eight-stage orchestration: regime -> strategy -> scan -> research -> follow-up -> vibe ->
entry plan -> stage orders.

**The orchestrator is deterministic; every model call lives inside a child run it launches.** This is
the load-bearing design choice of the whole feature. The stages here classify a regime, pick a card,
evaluate rule signals, derive template questions, combine gate verdicts and stage orders -- all pure
functions of stored data and the child runs' own outputs. The language-model work -- the actual
research -- happens inside the `tradingagents` and `vibedesk` runs this pipeline starts, which is
exactly where it belongs: those desks already ground, budget and audit every call. Keeping the
orchestrator itself free of sampling means the only nondeterminism in the four-arm study is inside
the gates the study is trying to measure, which is the difference between a clean paired comparison
and one confounded by the orchestrator's own coin flips.

**Fault-tolerant per symbol, fail-fast on the spine.** The three run-level stages before the fan-out
(`regime_call`, `strategy_select`, `candidate_scan`) are a strict sequence: without a card there is
nothing to scan, without a scan there is nothing to research, so a failure there fails the run. But a
single symbol's child run failing -- a Trading Agents run that errors, a Vibe run that never emits a
verdict -- degrades only that symbol's stage and drops it from the gated arms; the run continues with
the symbols that did resolve. A DAG of independent research branches is `app.vibedesk.runtime`'s
model, not `app.tradingagents.pipeline`'s, and the fan-out here is the former shape.

**Budget is a whole-run cap spent across children.** Each child gets `per_child_budget_usd`; the
workflow stops launching research children once the remaining whole-run budget cannot fund one more.
A child's realised cost is read back from its own `DeskRun.cost_usd` and accumulated, so the
workflow's reported spend is the true sum of what its children spent, not an estimate.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, cast

from app.agentdesk.models import DeskRun, StageRecord, StageState
from app.agentdesk.store import RunStore, with_stage
from app.agents.models import AgentBudget, AgentRole
from app.config import Settings
from app.discovery import clusters as clusters_mod
from app.indicators.volatility import atr as atr_indicator
from app.market import store as market_store
from app.market.models import Interval
from app.paper.mandate import default_mandate
from app.paper.marketdata import AsOfMarket, UnpricedSymbol
from app.rules import evaluate as rule_evaluate
from app.rules import grammar
from app.tournament.models import StrategyCard

# Child desks -- imported as modules so a test can monkeypatch `start_run` on each without this
# module having compiled a reference to the function object.
from app.tradingagents import service as tradingagents_service
from app.vibedesk import service as vibedesk_service
from app.workflow import book as book_mod
from app.workflow import candidates as candidates_mod
from app.workflow import regime as regime_mod
from app.workflow import research_cache as research_cache_mod
from app.workflow import taxcheck as taxcheck_mod
from app.workflow import universe as universe_mod
from app.workflow import verdict as verdict_mod
from app.workflow.book_models import BookState, OrderPlan, WorkflowArm
from app.workflow.candidates import SKIP_REASONS, CandidateObservation, GateDecision

__all__ = [
    "ALL_ARMS",
    "DEFAULT_BUDGET_USD",
    "DEFAULT_MAX_RESEARCH_SYMBOLS",
    "DEFAULT_PER_CHILD_BUDGET_USD",
    "FOLLOWUP_PRESET",
    "SCREENED_ARMS",
    "WorkflowConfig",
    "build_stage_plan",
    "run_workflow",
]

logger = logging.getLogger(__name__)

ALL_ARMS: tuple[WorkflowArm, ...] = ("raw_signal", "ta_gated", "vibe_gated", "full_workflow")

#: The two arms `universe_mode="screen"` runs are allowed to enable -- `app.workflow.service` enforces
#: this at request validation. `ta_gated`/`vibe_gated` re-test the gate question the static 4-arm study
#: already isolates, at 2x research cost, with no new information about *selection*; screen mode's own
#: question is whether a dynamically screened universe beats the card's static one, which `raw_signal`
#: (no gate) and `full_workflow` (both gates) already bracket. Exported so any future caller that needs
#: "which arms screen mode permits" has one definition to import rather than re-deriving it.
SCREENED_ARMS: tuple[WorkflowArm, ...] = ("raw_signal", "full_workflow")

DEFAULT_BUDGET_USD = Decimal("20.00")
DEFAULT_PER_CHILD_BUDGET_USD = Decimal("4.00")
DEFAULT_MAX_RESEARCH_SYMBOLS = 3

#: The Vibe preset the follow-up gate runs. Ships as pure JSON (`followup_review.json`); its prompts
#: interpolate `{question}`, the one thing that seam needed.
FOLLOWUP_PRESET = "followup_review"

#: Starting cash every arm's book is seeded with. The four arms must start identical for the paired
#: comparison to mean anything, so this is a constant, not a per-run parameter -- a different balance
#: per run would make two runs' arms incomparable.
STARTING_CASH = Decimal("100000")

#: Trading-Agents ratings that count as a buy for the `ta_gated` arm. Overweight is included because
#: the desk's own `parse_rating` treats it as a positive call distinct from Hold; excluding it would
#: make the gate stricter than the rating scale it reads.
_TA_PASS_RATINGS = frozenset({"Buy", "Overweight"})

#: How long a child run may take before the workflow gives up waiting and degrades that symbol. Long
#: enough for a real pipeline (several grounded calls with retries) and for a user's own manually
#: started run of the same desk to finish and free the single registry slot; short enough that one
#: wedged child cannot hang the whole workflow indefinitely.
#:
#: Raised from 15 to 25 minutes after a measured failure: a real TradingAgents child (full analyst +
#: debate + risk rounds) took 17.4 min, so the 15-min deadline cancelled a *healthy, nearly-finished*
#: child. Because `_await_child` cancels on timeout but the single-registry lock still saw that run
#: "active", the next research stages that session died with "a tradingagents run is already active"
#: -- only 1 of 3 screened names got researched. 25 min clears the observed ~17-min runtime with a
#: margin while capping the wait on a genuinely wedged child far lower than 40 min (a 40-min trial ran
#: sessions to ~2h and still had one child wedge, so the extra headroom bought nothing but wall-clock).
_CHILD_TIMEOUT_S = 25 * 60
_CHILD_POLL_S = 2.0

_TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})


@dataclass(frozen=True)
class WorkflowConfig:
    """One workflow run's parameters, built by `app.workflow.service.start_workflow_run`."""

    agent_card_id: str | None
    trade_date: dt.date | None
    budget_usd: Decimal
    per_child_budget_usd: Decimal
    max_research_symbols: int
    analysts: tuple[str, ...] | None
    debate_rounds: int | None
    risk_rounds: int | None
    arms_enabled: tuple[WorkflowArm, ...]
    model: str

    universe_mode: str = "card"
    """`"card"` (default) or `"screen"`. `"card"` reproduces `card.universe` unchanged through
    `_stage_universe_select` -- every existing caller of `WorkflowConfig` that omits this field keeps
    today's behaviour byte-for-byte. `"screen"` runs `app.workflow.universe.resolve_universe` instead.
    Kept as a plain `str` (not a `Literal`) here so this module never has to import the wire-side
    `Literal["card","screen"]` type from `app.workflow.schemas` -- `app.workflow.service` is the one
    place that validates the value; this dataclass just carries whatever it was handed."""

    selector_id: str | None = None
    """One of `app.discovery.workflow_selectors.SELECTOR_IDS` when `universe_mode == "screen"`; the
    primary screen path, validated by `app.workflow.service`. Takes precedence over
    `candidate_pool`/`rank_key` at the `universe_select` stage."""

    candidate_pool: str | None = None
    """One of `app.workflow.universe.CANDIDATE_POOLS` -- the raw screen-mode fallback used only when
    `selector_id` is unset."""

    rank_key: str | None = None
    """One of `app.discovery.selector.RANK_KEYS` -- paired with `candidate_pool` for the raw fallback
    path; ignored when `selector_id` is set."""

    screen_top_n: int | None = None
    """Shortlist size for the raw fallback path (`app.discovery.selector.select`'s own `top_n`)."""

    screen_entry_rule: str | None = None
    """A rules-DSL expression evaluated in place of the chosen card's `entry` when
    `universe_mode == "screen"` -- the less-restrictive screen-mode entry used to accrue study
    candidates faster than a card's own (often event-based, rare-firing) rule. `None` uses the card's
    own entry unchanged. Validated by `app.workflow.service`; ignored in card mode."""

    weekly_budget_usd: Decimal = Decimal("100")
    """The trailing-7-day research-spend ceiling a future necessity-gate stage evaluates against (see
    `docs/WORKFLOW-RESEARCH-SPEND-SPEC.md`). Threaded through and persisted here now so the field
    exists for that stage to read; this shard does not implement the gate itself."""


# ---------------------------------------------------------------------------
# The stage plan
# ---------------------------------------------------------------------------

#: The run-level stages, fixed and always present. `universe_select` sits between `strategy_select` and
#: `candidate_scan` -- see `_stage_universe_select`'s docstring for why it must run after the card is
#: chosen (screen mode's shortlist is regime/card-conditioned) and before the scan (which now iterates
#: whichever universe this stage picked). Per-symbol `research_<SYM>` (layer 4) and `vibe_<SYM>`
#: (layer 6) stages are spliced in after the scan, when the symbols are known -- the contract pins those
#: as templates, not a fixed count, because the count is a property of the scan, not the request.
_FIXED_STAGES: tuple[tuple[str, AgentRole, str, int], ...] = (
    ("regime_call", "market_analyst", "Regime Call", 0),
    ("strategy_select", "research_manager", "Strategy Selection", 1),
    ("universe_select", "trader", "Universe Selection", 2),
    ("candidate_scan", "trader", "Candidate Scan", 3),
    ("followup_questions", "research_manager", "Follow-up Questions", 5),
    ("entry_plan", "portfolio_manager", "Entry Plan", 7),
    ("stage_orders", "portfolio_manager", "Stage Orders", 8),
)


def build_stage_plan(config: WorkflowConfig) -> tuple[StageRecord, ...]:
    """Every run-level stage, all `"pending"`, in the fixed order the contract pins. Per-symbol
    stages are added during the run by `_splice_symbol_stages`; `config` is accepted for signature
    symmetry with the other desks' `build_stage_plan` even though the fixed plan does not vary with
    it."""
    del config
    stages: list[StageRecord] = []
    previous_id: str | None = None
    for stage_id, role, label, layer in _FIXED_STAGES:
        depends_on = (previous_id,) if previous_id is not None else ()
        stages.append(
            StageRecord(
                stage_id=stage_id,
                role=role,
                label=label,
                layer=layer,
                depends_on=depends_on,
            )
        )
        previous_id = stage_id
    return tuple(stages)


def _splice_symbol_stages(run: DeskRun, symbols: Sequence[str]) -> DeskRun:
    """Insert one `research_<SYM>` (layer 3) and one `vibe_<SYM>` (layer 5) stage per researched
    symbol, after `candidate_scan` and before `followup_questions`/`entry_plan` respectively.

    Rebuilds the stage tuple rather than mutating it -- `StageRecord` and `DeskRun` are frozen. The
    ordering keeps the progress board readable: research stages sit in their own layer between the
    scan and the follow-up questions, and the vibe stages in theirs between the questions and the
    plan, so a poll sees the fan-out grouped, not interleaved with the spine.
    """
    research_role: AgentRole = "research_manager"
    vibe_role: AgentRole = "risk_neutral"
    research = [
        StageRecord(
            stage_id=f"research_{sym}",
            role=research_role,
            label=f"Research · {sym}",
            layer=4,
            depends_on=("candidate_scan",),
        )
        for sym in symbols
    ]
    vibe = [
        StageRecord(
            stage_id=f"vibe_{sym}",
            role=vibe_role,
            label=f"Vibe Review · {sym}",
            layer=6,
            depends_on=("followup_questions",),
        )
        for sym in symbols
    ]
    existing = list(run.stages)
    scan_idx = next(i for i, s in enumerate(existing) if s.stage_id == "candidate_scan")
    followup_idx = next(i for i, s in enumerate(existing) if s.stage_id == "followup_questions")
    rebuilt = (
        existing[: scan_idx + 1]
        + research
        + existing[scan_idx + 1 : followup_idx + 1]
        + vibe
        + existing[followup_idx + 1 :]
    )
    return run.model_copy(update={"stages": tuple(rebuilt)})


# ---------------------------------------------------------------------------
# Run context
# ---------------------------------------------------------------------------


@dataclass
class _Candidate:
    symbol: str
    entry_rank: int
    ta_rating: str = ""
    ta_run_id: str = ""
    ta_ok: bool = False
    question: str = ""
    vibe_verdict: verdict_mod.VibeVerdict = "INCONCLUSIVE"
    vibe_explicit: bool = False
    vibe_run_id: str = ""

    # -- research-spend necessity gates (docs/WORKFLOW-RESEARCH-SPEND-SPEC.md) --

    skip_reason: str | None = None
    """One of `app.workflow.candidates.SKIP_REASONS`, set by `_apply_necessity_gates` when this
    candidate is refused *before* any child run is even considered. `None` means the candidate was
    admitted -- it may still have been served from cache (see `ta_source`/`vibe_source`), which is not
    a skip; see that constant's own docstring on why `"cache_hit"` is deliberately not in the set."""

    skip_detail: str = ""
    """Human-readable elaboration on `skip_reason` -- which arm's book was full, the correlated symbol
    a duplicate skip fired against, and so on. Empty when `skip_reason` is `None`."""

    avoided_cost_usd: Decimal = Decimal("0")
    """Dollars this candidate's fresh research would have cost, saved by reusing a cached verdict --
    the sum of every `ResearchVerdictCacheEntry.research_cost_usd` this candidate's TA and/or Vibe
    gate-2 lookup actually reused this cycle."""

    ta_source: Literal["fresh", "cached"] = "fresh"
    """Whether `ta_rating` came from a fresh child run this cycle or a still-valid cache hit --
    `GateDecision(gate="ta_gated").verdict_source`'s source of truth."""

    vibe_source: Literal["fresh", "cached"] = "fresh"
    """Whether `vibe_verdict` came from a fresh child run this cycle or a still-valid cache hit --
    `GateDecision(gate="vibe_gated").verdict_source`'s source of truth."""


@dataclass
class _Ctx:
    settings: Settings
    config: WorkflowConfig
    trade_date: dt.date
    regime: regime_mod.RegimeCall | None = None
    card: StrategyCard | None = None
    switch: taxcheck_mod.SwitchVerdict | None = None
    universe: tuple[str, ...] = field(default_factory=tuple)
    candidates: list[_Candidate] = field(default_factory=list)
    """Narrowed to the *kept* set by `_apply_necessity_gates`, right after `_stage_candidate_scan` --
    this is what the fan-out (`_splice_symbol_stages`, `_stage_research`, `_stage_followup`,
    `_stage_vibe`, `_stage_entry_plan`) iterates. See `all_candidates` for the full scanned set."""
    all_candidates: list[_Candidate] = field(default_factory=list)
    """Every candidate `_stage_candidate_scan` produced, kept *and* hard-skipped alike, in entry-rank
    order -- fixed once, never narrowed. `_stage_orders` logs from this list (the study's refused set
    lives here, per `app.workflow.candidates`' own module docstring) and stages the `raw_signal` arm's
    orders from it too, since that arm is the study's null and must trade every fired candidate
    regardless of what the necessity-gate chain decided about *researching* it -- see
    `_passes_gate`'s own docstring for why `raw_signal` ignores TA/Vibe entirely."""
    plans: dict[str, object] = field(default_factory=dict)  # symbol -> EntryPlan
    child_runs: dict[str, str] = field(default_factory=dict)  # stage_id -> child run_id


# ---------------------------------------------------------------------------
# Card loading and signal scanning (deterministic)
# ---------------------------------------------------------------------------


def _book_source(ctx: _Ctx) -> candidates_mod.UniverseSource:
    """Which book family this run reads and writes: the screen books in `universe_mode="screen"`, the
    card books otherwise. Every `load_book`/`save_book` in the run must key off this, or a screen run
    would stage its orders into (and overwrite) the card-mode books the in-flight 4-arm study owns --
    books are identified by the pair `(arm, universe_source)`, never `arm` alone."""
    return "screen" if ctx.config.universe_mode == "screen" else "card"


def _load_card(agent_id: str, *, settings: Settings) -> StrategyCard | None:
    """Load one strategy card by `agent_id` from the library, searching the tiered subfolders.

    Returns `None` when no file named `<agent_id>.json` parses as a `StrategyCard` -- the
    ladder/allocation tiers hold a different card shape and are simply not workflow-eligible, the
    same way `app.workflow.regime.load_regime_map` treats them.
    """
    for path in sorted(settings.library_dir.rglob(f"{agent_id}.json")):
        try:
            return StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
    return None


def _scan_signals(
    card: StrategyCard,
    *,
    settings: Settings,
    as_of: dt.date,
    universe: Sequence[str] | None = None,
    entry_rule: str | None = None,
) -> list[str]:
    """Every universe symbol whose entry rule fires at `as_of`, in scan order.

    Uses the same construction as `app.paperdesk.desk._rule_fires` -- full history, unknown truth
    (warmup/gap/no bar) becomes `False`, never raises -- so the workflow's candidates agree with what
    the engine would actually decide. Ranking by the card's `rank_by` is deliberately not applied
    here; the raw universe order is the entry order for a card that sets no ranking, and applying a
    partial ranking would make the workflow's candidate order disagree with the engine's for exactly
    the cards that set one. Ranking, if wanted, is a later refinement.

    `universe`, when given, replaces `card.universe` as the symbols scanned -- the entry rule still
    gates every one of them, so passing a screened shortlist here is what makes the entry rule a hard
    filter over the screened set rather than a separate check. `None` (the default) scans
    `card.universe` unchanged, which is what keeps `universe_mode="card"` byte-for-byte identical to
    today.

    `entry_rule`, when given, is a rules-DSL expression evaluated in place of `card.entry` -- the
    screen-mode option to accrue candidates faster than a card's own (often event-based, rare-firing)
    entry, by scanning a less-restrictive trending *state* instead. `None` uses the card's own entry,
    unchanged. An unparseable override degrades to no candidates with a warning, exactly as an
    unparseable card entry does -- `app.workflow.service` validates it up front so this branch is a
    defensive floor, not the normal rejection path.
    """
    market = AsOfMarket(as_of=as_of, settings=settings)
    rule_source = entry_rule if entry_rule is not None else card.entry
    try:
        entry_tree = grammar.parse(rule_source)
    except ValueError:
        logger.warning(
            "workflow: %s entry rule is unparseable; no candidates",
            "screen override" if entry_rule is not None else f"card {card.agent_id}",
        )
        return []
    firing: list[str] = []
    scan_universe = universe if universe is not None else card.universe
    for symbol in scan_universe:
        bars = market.history(symbol, lookback_days=None)
        if bars.empty:
            continue
        try:
            signal = rule_evaluate.evaluate(entry_tree, bars, interval=Interval.DAY)
        except ValueError:
            continue
        if bool(signal.fillna(False).iloc[-1]):
            firing.append(symbol)
    return firing


# ---------------------------------------------------------------------------
# Child runs
# ---------------------------------------------------------------------------


@dataclass
class _TARequest:
    """A structural `app.tradingagents.service.StartRunRequest` -- the child TA desk validates it.

    Not frozen: that service's `StartRunRequest` Protocol declares its members as settable variables,
    and a frozen dataclass's read-only attributes do not satisfy that structural requirement.
    """

    symbol: str
    trade_date: dt.date | None
    analysts: list[str] | None
    debate_rounds: int | None
    risk_rounds: int | None
    budget_usd: str | None
    model: str | None


def _launch_ta(symbol: str, *, ctx: _Ctx, budget_usd: Decimal) -> str:
    req = _TARequest(
        symbol=symbol,
        trade_date=ctx.trade_date,
        analysts=list(ctx.config.analysts) if ctx.config.analysts is not None else None,
        debate_rounds=ctx.config.debate_rounds,
        risk_rounds=ctx.config.risk_rounds,
        budget_usd=str(budget_usd),
        model=ctx.config.model,
    )
    run = tradingagents_service.start_run(req, settings=ctx.settings)
    return run.run_id


def _launch_vibe(symbol: str, question: str, *, ctx: _Ctx, budget_usd: Decimal) -> str:
    from app.vibedesk.schemas import StartSwarmRequest

    req = StartSwarmRequest(
        preset=FOLLOWUP_PRESET,
        symbol=symbol,
        question=question,
        budget_usd=str(budget_usd),
        model=ctx.config.model,
    )
    run = vibedesk_service.start_run(req, settings=ctx.settings)
    return run.run_id


def _await_child(
    kind: str, run_id: str, *, settings: Settings, cancel: threading.Event
) -> DeskRun | None:
    """Poll a child run's store snapshot until it reaches a terminal state, is cancelled, or times
    out. Returns the terminal `DeskRun`, or `None` on timeout/cancel/vanish.

    Polling the persisted snapshot rather than joining the thread is deliberate: the snapshot is the
    same immutable object the child's own API serves, so what the workflow reads is exactly what a
    user watching the child desk would see, and a torn read is impossible by the store's design.
    """
    store = RunStore(settings, cast("object", kind))  # type: ignore[arg-type]
    deadline = time.monotonic() + _CHILD_TIMEOUT_S
    while True:
        if cancel.is_set():
            from app.agentdesk.jobs import registry

            registry().cancel(run_id)
            return None
        run = store.load(run_id)
        if run is not None and run.state in _TERMINAL_STATES:
            return run
        if time.monotonic() >= deadline:
            logger.warning("workflow: child %s run %s timed out after %ss", kind, run_id, _CHILD_TIMEOUT_S)
            from app.agentdesk.jobs import registry

            registry().cancel(run_id)
            return None
        time.sleep(_CHILD_POLL_S)


# ---------------------------------------------------------------------------
# Follow-up questions (deterministic template)
# ---------------------------------------------------------------------------


def _followup_question(candidate: _Candidate, card: StrategyCard) -> str:
    """One testable question for the Vibe gate, built from the card's own thesis and the TA rating.

    Deterministic and template-based on purpose: the question must be the same for the same inputs so
    the `vibe_gated` arm is reproducible, and it must probe the specific risk the strategy is exposed
    to, not a generic prompt. Phrased as a falsifiable claim the Vibe committee can support or refute,
    per `docs/WORKFLOW-STUDY-PLAN.md`'s discrimination framing.
    """
    return (
        f"The strategy '{card.agent_id}' wants to enter {candidate.symbol} now "
        f"(its thesis: {card.thesis}). The Trading Agents desk rated it "
        f"{candidate.ta_rating or 'no rating'}. Does the current evidence support entering "
        f"{candidate.symbol} at this point, given the strategy's stated invalidation "
        f"({card.falsification})?"
    )


# ---------------------------------------------------------------------------
# Order staging per arm (deterministic gating)
# ---------------------------------------------------------------------------


def _passes_gate(arm: WorkflowArm, candidate: _Candidate) -> bool:
    """Whether `candidate` survives `arm`'s gate. The one point the four arms diverge."""
    if arm == "raw_signal":
        return True
    if arm == "ta_gated":
        return candidate.ta_ok and candidate.ta_rating in _TA_PASS_RATINGS
    if arm == "vibe_gated":
        return candidate.vibe_verdict == "SUPPORT"
    # full_workflow: both gates must agree.
    return (
        candidate.ta_ok
        and candidate.ta_rating in _TA_PASS_RATINGS
        and candidate.vibe_verdict == "SUPPORT"
    )


def _verdict_source_for(
    gate: Literal["ta_gated", "vibe_gated", "full_workflow"], candidate: _Candidate
) -> Literal["fresh", "cached", "mixed"]:
    """`GateDecision.verdict_source` for one gate's ruling on `candidate` -- read straight off
    `candidate.ta_source`/`vibe_source`, which `_stage_research`/`_stage_vibe` set to `"cached"`
    exactly when gate 2 was hit. `full_workflow` is `"fresh"` only when both children were fresh this
    cycle, `"cached"` only when both were cache-served, and `"mixed"` otherwise -- the linked-
    invalidation case (TA cache hit, but the Vibe cache was separately invalidated and ran fresh, or
    vice versa)."""
    if gate == "ta_gated":
        return "fresh" if candidate.ta_source == "fresh" else "cached"
    if gate == "vibe_gated":
        return "fresh" if candidate.vibe_source == "fresh" else "cached"
    if candidate.ta_source == "fresh" and candidate.vibe_source == "fresh":
        return "fresh"
    if candidate.ta_source == "cached" and candidate.vibe_source == "cached":
        return "cached"
    return "mixed"


def _notional_for(card: StrategyCard) -> Decimal:
    """Equal-weight notional per name, from the card's own sizing. Deterministic and identical across
    arms so a name that passes two arms is sized the same in both -- the arms must differ in *which*
    names they hold, not in how big each position is, or the comparison confounds selection with
    sizing."""
    return (STARTING_CASH * card.position_pct).quantize(Decimal("0.01"))


def _entry_plan_for(candidate: _Candidate, card: StrategyCard, ctx: _Ctx) -> object:
    """Synthesise one symbol's entry plan from the card and the two gate outcomes -- deterministic.

    The thesis and invalidation come from the card (the broker's mandate rejects an order without
    both), annotated with what the research found, so the order the `full_workflow` arm places
    carries the chain's actual reasoning rather than a generic string.
    """
    from app.workflow.schemas import EntryPlan

    thesis = (
        f"{card.thesis} Trading Agents: {candidate.ta_rating or 'n/a'}; "
        f"Vibe: {candidate.vibe_verdict}."
    )
    return EntryPlan(
        symbol=candidate.symbol,
        notional=_notional_for(card),
        thesis=thesis,
        invalidation=card.falsification or "",
        stop_level=None,
        conviction=None,
        regime=ctx.regime.label if ctx.regime else "",
    )


# ---------------------------------------------------------------------------
# The job target
# ---------------------------------------------------------------------------


def _cancel_remaining(run: DeskRun, from_index: int, *, budget: AgentBudget) -> DeskRun:
    stage_ids = [s.stage_id for s in run.stages][from_index:]
    for sid in stage_ids:
        run = with_stage(run, sid, state="skipped", error="run cancelled")
    return run.model_copy(
        update={"state": "cancelled", "completed_at": dt.datetime.now(dt.UTC), "budget": budget}
    )


def run_workflow(
    run_id: str, config: WorkflowConfig, *, settings: Settings, cancel: threading.Event
) -> None:
    """Drive one workflow run to completion, cancellation, or failure.

    The job target `app.workflow.service.start_workflow_run` hands to the registry. Saves a new
    snapshot after every stage transition, exactly like the other desks, so a 2s poll always reads a
    consistent picture.
    """
    store = RunStore(settings, "workflow")
    run = store.load(run_id)
    if run is None:  # pragma: no cover - defensive
        logger.error("workflow: run %r vanished before it could start", run_id)
        return

    run = run.model_copy(update={"state": "running"})
    store.save(run)

    trade_date = config.trade_date or _newest_session(settings)
    ctx = _Ctx(settings=settings, config=config, trade_date=trade_date)
    budget = run.budget

    def _cancelled(current: DeskRun) -> bool:
        # A cancel-handling stage returns a run already marked cancelled but does not persist it --
        # persisting a terminal state is the worker's own responsibility (the registry has no DeskRun
        # to mark), so the save happens here, once, wherever cancellation surfaces.
        if current.state == "cancelled":
            store.save(current)
            return True
        return False

    try:
        run = _stage_regime(run, store, ctx, cancel)
        if _cancelled(run):
            return
        run = _stage_strategy_select(run, store, ctx, cancel)
        if _cancelled(run):
            return
        run = _stage_universe_select(run, store, ctx, cancel)
        if _cancelled(run):
            return
        run, scan_proceed = _stage_candidate_scan(run, store, ctx, cancel)
        if _cancelled(run):
            return
        gate_proceed = False
        if scan_proceed:
            kept, _skipped = _apply_necessity_gates(ctx)
            ctx.candidates = kept
            gate_proceed = bool(kept)
        if gate_proceed:
            run = _splice_symbol_stages(run, [c.symbol for c in ctx.candidates])
            store.save(run)
            run, budget = _stage_research(run, store, ctx, cancel, budget)
            if _cancelled(run):
                return
            run = _stage_followup(run, store, ctx, cancel)
            if _cancelled(run):
                return
            run, budget = _stage_vibe(run, store, ctx, cancel, budget)
            if _cancelled(run):
                return
            run = _stage_entry_plan(run, store, ctx, cancel)
            if _cancelled(run):
                return
        else:
            # No candidates fired, or every fired candidate was refused by the necessity-gate chain
            # (see `_apply_necessity_gates`) -- the fan-out stages have nothing to do. Distinguishing
            # the two messages matters: "no entry candidates fired" is a quiet, ordinary day; "every
            # candidate refused" while candidates *did* fire is exactly the failure-mode signal
            # `docs/WORKFLOW-RESEARCH-SPEND-SPEC.md` §6 asks for -- a silently-starved research policy
            # must never look identical to a policy with nothing to research at all.
            if scan_proceed and ctx.all_candidates:
                error = (
                    f"every fired candidate ({len(ctx.all_candidates)}) was refused by the "
                    "research-spend necessity gates -- see each candidate's skip_reason"
                )
            else:
                error = "no entry candidates fired"
            for sid in ("followup_questions", "entry_plan"):
                run = with_stage(run, sid, state="skipped", error=error)
            store.save(run)
        run = _stage_orders(run, store, ctx, cancel)
    except Exception as exc:
        logger.exception("workflow: run %s failed", run_id)
        current = next((s.stage_id for s in run.stages if s.state == "running"), None)
        if current is not None:
            run = with_stage(run, current, state="failed", error=str(exc), completed_at=dt.datetime.now(dt.UTC))
        run = run.model_copy(
            update={"state": "failed", "error": str(exc), "completed_at": dt.datetime.now(dt.UTC), "budget": budget}
        )
        store.save(run)
        return

    final = next((s for s in run.stages if s.stage_id == "stage_orders"), None)
    run = run.model_copy(
        update={
            "state": "succeeded",
            "completed_at": dt.datetime.now(dt.UTC),
            "final_md": final.output_md if final else "",
            "budget": budget,
        }
    )
    store.save(run)


def _newest_session(settings: Settings) -> dt.date:
    """The trade date a run with no `trade_date` decides against -- the newest stored SPY session,
    the same anchor the regime call reads. Falls back to today only if the store is empty."""
    frame = market_store.read_frame("SPY", Interval.DAY, settings=settings)
    if frame is not None and not frame.empty:
        return cast("dt.date", frame["ts"].dt.date.iloc[-1])
    return dt.date.today()


def _next_business_day(day: dt.date) -> dt.date:
    """The next weekday after `day` -- the "fill next open" session for an order staged on `day`.

    **Why not `day + timedelta(days=1)`.** The staged `fill_date` is not a display placeholder: it is
    written straight through to `Fill.trade_date` and, via `book.held_lots`, to the tax lot's
    `acquired_date` (see `app.workflow.book._order_to_fill` and its `held_lots`), and `execute_pending`
    never re-resolves it to a real session -- it just fills once `fill_date <= today`. A bare calendar
    +1 day therefore stamps a *Saturday* acquisition date on every Friday session, corrupting the
    holding-period (short- vs long-term) boundary and the 61-day wash-sale window that math sits on --
    exactly the "a write date is not a trading session" defect this project has already had to fix once.

    Weekday arithmetic, not an exchange calendar, and for the same reason `app.paper.paperbroker.
    _add_business_days` gives: a market holiday that slips the next open by one more day does not change
    any decision this harness records, and reaching for the session calendar would couple this stage to
    a run-wide object it otherwise does not need. Avoiding the weekend is the part that carries tax
    consequences; the residual holiday case does not.
    """
    nxt = day + dt.timedelta(days=1)
    while nxt.weekday() >= 5:  # Saturday (5) / Sunday (6)
        nxt += dt.timedelta(days=1)
    return nxt


# ---------------------------------------------------------------------------
# Individual stages
# ---------------------------------------------------------------------------


def _stage_regime(run: DeskRun, store: RunStore, ctx: _Ctx, cancel: threading.Event) -> DeskRun:
    if cancel.is_set():
        return _cancel_remaining(run, 0, budget=run.budget)
    run = with_stage(run, "regime_call", state="running", started_at=dt.datetime.now(dt.UTC))
    store.save(run)
    call = regime_mod.classify(settings=ctx.settings, as_of=ctx.trade_date)
    ctx.regime = call
    lines = [f"# Regime: {call.label}", "", f"Confidence (vote share): {call.confidence}", ""]
    for inp in call.inputs:
        mark = "✓" if inp.contributed else "·"
        lines.append(f"- {mark} **{inp.name}** = {inp.value}  ({inp.source})")
    if call.warnings:
        lines += ["", "**Warnings:**"] + [f"- {w}" for w in call.warnings]
    run = with_stage(
        run, "regime_call", state="succeeded", completed_at=dt.datetime.now(dt.UTC),
        output_md="\n".join(lines), summary=f"Regime: {call.label} (confidence {call.confidence}).",
    )
    store.save(run)
    return run


def _stage_strategy_select(run: DeskRun, store: RunStore, ctx: _Ctx, cancel: threading.Event) -> DeskRun:
    if cancel.is_set():
        idx = next(i for i, s in enumerate(run.stages) if s.stage_id == "strategy_select")
        return _cancel_remaining(run, idx, budget=run.budget)
    run = with_stage(run, "strategy_select", state="running", started_at=dt.datetime.now(dt.UTC))
    store.save(run)
    assert ctx.regime is not None

    incumbent_book = book_mod.load_book(
        ctx.settings, "full_workflow", starting_cash=STARTING_CASH,
        card_id=ctx.config.agent_card_id or "", universe_source=_book_source(ctx),
    )
    chosen_id, note = _choose_card(ctx, incumbent_book)
    card = _load_card(chosen_id, settings=ctx.settings) if chosen_id else None
    if card is None:
        raise RuntimeError(f"strategy selection produced no loadable card (chose {chosen_id!r})")
    ctx.card = card

    out = [f"# Strategy: {card.agent_id}", "", f"Regime: {ctx.regime.label}", "", note, "",
           f"Thesis: {card.thesis}", f"Universe: {', '.join(card.universe)}"]
    run = with_stage(
        run, "strategy_select", state="succeeded", completed_at=dt.datetime.now(dt.UTC),
        output_md="\n".join(out), summary=f"Selected {card.agent_id} for {ctx.regime.label}. {note}",
    )
    store.save(run)
    return run


def _stage_universe_select(run: DeskRun, store: RunStore, ctx: _Ctx, cancel: threading.Event) -> DeskRun:
    """Populate `ctx.universe` -- the symbols `_stage_candidate_scan` scans next.

    Runs after `_stage_strategy_select` (so the card, and in `"screen"` mode the regime label, are
    known) and before `_stage_candidate_scan` (so the scan has something to iterate). Deterministic,
    exactly like every other stage before the fan-out -- see `app.workflow.universe.resolve_universe`.
    In `universe_mode="card"` this reproduces `card.universe` unchanged; the pipeline's behaviour,
    output and every persisted artifact are byte-for-byte identical to a build without this stage.
    """
    if cancel.is_set():
        idx = next(i for i, s in enumerate(run.stages) if s.stage_id == "universe_select")
        return _cancel_remaining(run, idx, budget=run.budget)
    run = with_stage(run, "universe_select", state="running", started_at=dt.datetime.now(dt.UTC))
    store.save(run)
    assert ctx.card is not None and ctx.regime is not None

    # Live hysteresis: a named selector in screen mode reads its own prior run's shortlist so its
    # day-over-day state (mom12_1_hysteresis's rank bands, breakout_atr's cooldown, ...) actually
    # engages. Card mode and the raw candidate_pool/rank_key path carry no such state, so neither reads
    # nor writes the store. A backtest replay never reaches here -- it threads prior_picks itself.
    screen_selector = ctx.config.universe_mode == "screen" and bool(ctx.config.selector_id)
    prior_picks: tuple[str, ...] = ()
    if screen_selector:
        prior_picks = universe_mod.load_prior_shortlist(
            ctx.settings, selector_id=ctx.config.selector_id or "", universe_source="screen"
        )

    ctx.universe = universe_mod.resolve_universe(
        universe_mode=ctx.config.universe_mode,
        selector_id=ctx.config.selector_id,
        candidate_pool=ctx.config.candidate_pool,
        rank_key=ctx.config.rank_key,
        screen_top_n=ctx.config.screen_top_n,
        regime_label=ctx.regime.label,
        card=ctx.card,
        settings=ctx.settings,
        as_of=ctx.trade_date,
        prior_picks=prior_picks,
    )

    if screen_selector:
        universe_mod.save_prior_shortlist(
            ctx.settings,
            selector_id=ctx.config.selector_id or "",
            universe_source="screen",
            as_of=ctx.trade_date,
            picks=ctx.universe,
        )

    if ctx.config.universe_mode != "screen":
        out = [f"# Universe: card ({ctx.card.agent_id})", "",
               f"Using the card's own universe unchanged: {', '.join(ctx.universe)}"]
        summary = f"Card universe: {len(ctx.universe)} symbol(s)."
    else:
        label = ctx.config.selector_id or f"{ctx.config.candidate_pool}/{ctx.config.rank_key}"
        out = [f"# Universe: screened ({label})", "",
               f"Shortlist: {', '.join(ctx.universe) if ctx.universe else '(none)'}"]
        summary = f"Screened universe ({label}): {len(ctx.universe)} symbol(s)."

    run = with_stage(
        run, "universe_select", state="succeeded", completed_at=dt.datetime.now(dt.UTC),
        output_md="\n".join(out), summary=summary,
    )
    store.save(run)
    return run


def _positions_for_taxcheck(
    book: BookState, ctx: _Ctx
) -> tuple[taxcheck_mod.PositionLot, ...]:
    """The incumbent book's held lots, priced at the decision date, as `taxcheck.PositionLot`s.

    This is what makes the tax switch check real rather than toothless: the wash-sale and
    near-long-term rules can only fire against actual open lots, and before this the check was called
    with an empty list. Lots come from `book.held_lots` (FIFO over the fill history, carrying each
    lot's true acquisition date); each is marked at `ctx.trade_date`'s close via `AsOfMarket`. A lot
    whose symbol cannot be priced at the decision date is marked at its own cost basis -- a neutral
    price that shows neither gain nor loss, so an unpriceable name never manufactures a spurious block
    nor hides a real one; it simply abstains from the decision.
    """
    lots = book_mod.held_lots(book)
    if not lots:
        return ()
    market = AsOfMarket(as_of=ctx.trade_date, settings=ctx.settings)
    out: list[taxcheck_mod.PositionLot] = []
    for lot in lots:
        per_share_basis = lot.cost_basis / lot.quantity if lot.quantity else Decimal(0)
        try:
            bars = market.history(lot.symbol, lookback_days=None)
            price = Decimal(str(bars["close"].iloc[-1])) if not bars.empty else per_share_basis
        except Exception:
            price = per_share_basis
        out.append(
            taxcheck_mod.PositionLot(
                symbol=lot.symbol,
                quantity=lot.quantity,
                cost_basis=lot.cost_basis,
                acquired_date=lot.acquired_date,
                current_price=price,
            )
        )
    return tuple(out)


def _choose_card(ctx: _Ctx, incumbent_book: BookState) -> tuple[str, str]:
    """Pick the card to trade, respecting an explicit request, the regime map, and the tax gate.

    Returns `(agent_id, human_note)`. When the request pins a card, that card is used unconditionally
    -- the owner asked for it by name. Otherwise the regime's top-ranked candidate is chosen, and a
    switch away from the book's incumbent card must clear `taxcheck.evaluate_switch`; a blocked switch
    keeps the incumbent, recorded in the note so the board shows the tax reason.
    """
    if ctx.config.agent_card_id:
        return ctx.config.agent_card_id, "Card pinned by request."

    assert ctx.regime is not None
    regime_map = regime_mod.load_regime_map(ctx.settings)
    candidates = regime_map.get(ctx.regime.label, ())
    if not candidates:
        raise RuntimeError(f"regime map has no cards for {ctx.regime.label!r}")
    target = candidates[0]

    incumbent = incumbent_book.current_card_id
    if not incumbent or incumbent == target:
        return target, f"Auto-selected {target} for {ctx.regime.label} (no switch)."

    target_card = _load_card(target, settings=ctx.settings)
    if target_card is None:
        return target, f"Auto-selected {target}; incumbent {incumbent} not loadable to compare."
    verdict = taxcheck_mod.evaluate_switch(
        positions=_positions_for_taxcheck(incumbent_book, ctx),
        target_card=taxcheck_mod.TargetCardSpec(card_id=target, universe=frozenset(target_card.universe)),
        incumbent_card_id=incumbent,
        today=ctx.trade_date,
        card_adopted_date=incumbent_book.card_adopted_date,
        settings=ctx.settings,
        regime_changed=True,
    )
    ctx.switch = verdict
    if verdict.allowed:
        return target, f"Switched {incumbent} -> {target}: {verdict.reason}"
    return incumbent, f"Switch to {target} blocked ({verdict.outcome}): {verdict.reason}. Kept {incumbent}."


def _stage_candidate_scan(
    run: DeskRun, store: RunStore, ctx: _Ctx, cancel: threading.Event
) -> tuple[DeskRun, bool]:
    if cancel.is_set():
        idx = next(i for i, s in enumerate(run.stages) if s.stage_id == "candidate_scan")
        return _cancel_remaining(run, idx, budget=run.budget), False
    run = with_stage(run, "candidate_scan", state="running", started_at=dt.datetime.now(dt.UTC))
    store.save(run)
    assert ctx.card is not None

    # In screen mode a less-restrictive `screen_entry_rule` (a trending state, not the card's own
    # crossover event) may stand in for the card's entry, so the screened study accrues candidates fast
    # enough to measure. Card mode always uses the card's own entry.
    entry_rule = ctx.config.screen_entry_rule if ctx.config.universe_mode == "screen" else None
    firing = _scan_signals(
        ctx.card, settings=ctx.settings, as_of=ctx.trade_date, universe=ctx.universe, entry_rule=entry_rule
    )
    cap = ctx.config.max_research_symbols
    chosen = firing[:cap]
    overflow = firing[cap:]
    # Only the capped set is gated and researched -- unchanged, and the assumption
    # `app.workflow.power_analysis.estimate_candidate_arrival_rate` models. The names that fired beyond
    # the cap are still recorded in the observation log (below, via `ctx.all_candidates`), pre-marked
    # `skip_reason="over_cap"` so `_apply_necessity_gates` leaves them untouched -- the study's
    # negative-observation record is then complete instead of silently missing every name a busy
    # session fires past the cap, without changing which names get researched, the budget, or staging.
    capped_cands = [_Candidate(symbol=sym, entry_rank=i + 1) for i, sym in enumerate(chosen)]
    overflow_cands = [
        _Candidate(
            symbol=sym,
            entry_rank=len(chosen) + j + 1,
            skip_reason="over_cap",
            skip_detail=(
                f"fired at rank {len(chosen) + j + 1}; only the top {cap} (max_research_symbols) "
                "are gated or researched this session"
            ),
        )
        for j, sym in enumerate(overflow)
    ]
    ctx.candidates = capped_cands
    ctx.all_candidates = capped_cands + overflow_cands

    dropped = len(overflow)
    out = [f"# Candidate scan · {ctx.card.agent_id}", "",
           f"Fired: {', '.join(firing) if firing else '(none)'}", "",
           f"Researching top {len(chosen)}: {', '.join(chosen) if chosen else '(none)'}"]
    if dropped > 0:
        out.append(f"\n{dropped} further candidate(s) fired but exceed max_research_symbols "
                   f"({cap}); logged as `over_cap` observations, not researched.")
    run = with_stage(
        run, "candidate_scan", state="succeeded", completed_at=dt.datetime.now(dt.UTC),
        output_md="\n".join(out),
        summary=f"{len(firing)} fired; researching {len(chosen)}.",
    )
    store.save(run)
    return run, bool(chosen)


# ---------------------------------------------------------------------------
# Research-spend necessity gates (docs/WORKFLOW-RESEARCH-SPEND-SPEC.md)
#
# Every gate here is free -- a pure read of already-computed state, a deterministic disk read, or
# arithmetic over stored bar history. The only thing that costs money is `_launch_ta`/`_launch_vibe`
# themselves, and both sit strictly downstream of everything in this section.
# ---------------------------------------------------------------------------

#: How many stored workflow runs `_trailing_weekly_research_spend` scans looking for the trailing 7
#: days. Generous relative to a realistic run cadence (at most a few runs a day) so a busy week is
#: never truncated by `RunStore.list_runs`'s own default `limit=25`.
_WEEKLY_SPEND_LOOKBACK_RUNS = 500

#: Correlation threshold gate 5 refuses a candidate at -- imported for gate 5's own docstring rather
#: than restated as a second constant; `app.discovery.clusters.DEFAULT_THRESHOLD` is what actually
#: gets passed to `correlation_groups` below.


def _trailing_weekly_research_spend(settings: Settings, *, now: dt.datetime | None = None) -> Decimal:
    """Sum of `DeskRun.cost_usd` (== `budget.spent_usd`) across every stored workflow run whose
    `created_at` falls inside the trailing 7 calendar days -- gate 0's own input. `now` is a keyword
    purely so a test can pin "now" rather than seeding fixture runs relative to the wall clock at
    collection time; every real caller omits it and gets `dt.datetime.now(dt.UTC)`.
    """
    reference = now if now is not None else dt.datetime.now(dt.UTC)
    cutoff = reference - dt.timedelta(days=7)
    store = RunStore(settings, "workflow")
    runs = store.list_runs(limit=_WEEKLY_SPEND_LOOKBACK_RUNS)
    return sum((run.cost_usd for run in runs if run.created_at >= cutoff), Decimal(0))


def _held_symbols_by_arm(ctx: _Ctx) -> dict[WorkflowArm, set[str]]:
    """Every symbol currently held (any open lot) in each of `ctx.config.arms_enabled`'s books --
    gate 3 and gate 5's shared input. A preview read only: `book_mod.load_book` never writes, and
    nothing here touches the books `_stage_orders` later loads and stages orders against."""
    assert ctx.card is not None
    out: dict[WorkflowArm, set[str]] = {}
    for arm in ctx.config.arms_enabled:
        book = book_mod.load_book(
            ctx.settings, arm, starting_cash=STARTING_CASH, card_id=ctx.card.agent_id,
            universe_source=_book_source(ctx),
        )
        out[arm] = {lot.symbol for lot in book_mod.held_lots(book)}
    return out


def _has_book_capacity(symbol: str, *, held_by_arm: dict[WorkflowArm, set[str]], notional: Decimal) -> bool:
    """Gate 3: at least one enabled arm's book has structural room for `symbol` -- either the symbol
    is already held there, or that book has not yet reached `mandate.max_positions` -- **and** the
    card's own equal-weight clip clears `mandate.min_clip_notional`. Deliberately not a full replay of
    `PaperBroker._check_buy`'s weight-cap rule (that needs a live equity mark this static precheck does
    not want to pay for) -- see `docs/WORKFLOW-RESEARCH-SPEND-SPEC.md` §1, gate 3, for why that
    asymmetry (a false-admit costs one wasted research spend; a false-reject silently starves a
    legitimate candidate) is the right one to accept here.
    """
    mandate = default_mandate()
    if notional < mandate.min_clip_notional:
        return False
    return any(
        symbol in held or len(held) < mandate.max_positions for held in held_by_arm.values()
    )


def _tax_gate_blocked(ctx: _Ctx) -> tuple[bool, str]:
    """Gate 4: does `ctx.switch` (the once-per-run `SwitchVerdict` from `_choose_card`) hard-block
    every candidate this run? Only `"blocked_wash_sale"` does -- a guaranteed IRC §1091 disallowance.
    `"blocked_near_long_term"`/`"blocked_churn"` are soft blocks that still allow research (and still
    cache it, per gate 2), and `"allowed"`/`ctx.switch is None` (no switch attempted) never block at
    all. See `docs/WORKFLOW-RESEARCH-SPEND-SPEC.md` §1, gate 4, for the full four-outcome mapping.
    """
    if ctx.switch is not None and ctx.switch.outcome == "blocked_wash_sale":
        return True, (
            f"card-switch tax check blocked this run on a wash-sale disallowance: {ctx.switch.reason}"
        )
    return False, ""


def _apply_necessity_gates(ctx: _Ctx) -> tuple[list[_Candidate], list[_Candidate]]:
    """Gates 0, 1, 3, 4, 5 -- the shared, per-candidate admission precheck, run once at the seam
    between `_stage_candidate_scan` and the symbol-stage splice, narrowing `ctx.all_candidates` (every
    candidate the scan produced) down to the *kept* set. Gate 2 (the cache) is evaluated separately,
    per child kind, inside `_stage_research`/`_stage_vibe` themselves -- see those functions' own
    docstrings for why gate 2 cannot live in this shared precheck (TA and Vibe caches invalidate on
    different schedules, and Vibe's linked-invalidation rule needs *this cycle's* effective TA rating,
    which is not yet known before `_stage_research` has actually run). Gate 6 (the remaining-budget
    backstop) likewise stays exactly where it already lives, inside the two per-child stage loops --
    it is a backstop precisely because every cheaper reason to say no gets its chance first.

    Returns `(kept, skipped)`. Every candidate in `ctx.all_candidates` ends up in exactly one of the
    two lists; `kept` is the list the caller assigns to `ctx.candidates`.
    """
    kept: list[_Candidate] = []
    skipped: list[_Candidate] = []

    def _skip(cand: _Candidate, reason: str, detail: str) -> None:
        assert reason in SKIP_REASONS, f"not a recognised skip_reason: {reason!r}"
        cand.skip_reason = reason
        cand.skip_detail = detail
        skipped.append(cand)

    # --- Gate 0: weekly circuit breaker (run-level, checked once, before any candidate is looked at)
    trailing = _trailing_weekly_research_spend(ctx.settings)
    if trailing >= ctx.config.weekly_budget_usd:
        detail = (
            f"trailing 7-day workflow research spend ${trailing} >= this run's weekly cap "
            f"${ctx.config.weekly_budget_usd}"
        )
        for cand in ctx.all_candidates:
            # A name already skipped before gating (`over_cap`) keeps its own, more specific reason --
            # it was never going to be researched regardless of the weekly cap. Everything else the cap
            # would have admitted is refused here.
            if cand.skip_reason is None:
                _skip(cand, "weekly_budget_exhausted", detail)
            else:
                skipped.append(cand)
        return kept, skipped

    # --- Gate 1: entry rule fires. Trivially true for every member of `ctx.all_candidates` -- already
    # enforced by `_scan_signals` inside `_stage_candidate_scan`. Asserted, not re-evaluated, so a
    # future caller that hands this function a candidate list from elsewhere cannot skip verifying it.
    assert all(c.entry_rank > 0 for c in ctx.all_candidates)

    if not ctx.all_candidates:
        return kept, skipped

    assert ctx.card is not None
    held_by_arm = _held_symbols_by_arm(ctx)
    held_symbols: set[str] = set()
    for held in held_by_arm.values():
        held_symbols |= held
    notional = _notional_for(ctx.card)
    mandate = default_mandate()
    tax_blocked, tax_detail = _tax_gate_blocked(ctx)

    # Restricted to the gated (non-`over_cap`) candidates plus held names, so gate 5's correlation
    # universe is byte-identical to before this change -- an over-cap name is never gated or admitted,
    # so it must not enter the group computation the capped set's duplicate check runs against.
    all_symbols = sorted(
        held_symbols | {c.symbol for c in ctx.all_candidates if c.skip_reason is None}
    )
    groups = (
        clusters_mod.correlation_groups(all_symbols, ctx.trade_date, settings=ctx.settings)
        if all_symbols
        else ()
    )
    group_of = {symbol: group for group in groups for symbol in group}

    kept_symbols: set[str] = set()
    for cand in ctx.all_candidates:
        # Pre-skipped before gating (`over_cap`): logged as an observation but never gated or
        # researched, so it bypasses gates 3/4/5 entirely and carries its own reason into `skipped`.
        if cand.skip_reason is not None:
            skipped.append(cand)
            continue

        # Gate 3: book capacity.
        if not _has_book_capacity(cand.symbol, held_by_arm=held_by_arm, notional=notional):
            _skip(
                cand, "no_book_capacity",
                f"no enabled arm has room for {cand.symbol}: clip ${notional} vs "
                f"min_clip_notional ${mandate.min_clip_notional}, or every arm already "
                f"holds max_positions ({mandate.max_positions})",
            )
            continue

        # Gate 4: tax-switch gate.
        if tax_blocked:
            _skip(cand, "tax_wash_sale_blocked", tax_detail)
            continue

        # Gate 5: not a correlation-duplicate of an already-held or already-admitted symbol.
        group = group_of.get(cand.symbol, (cand.symbol,))
        collision = next(
            (s for s in group if s != cand.symbol and (s in held_symbols or s in kept_symbols)), None
        )
        if collision is not None:
            _skip(
                cand, "correlation_duplicate",
                f"{cand.symbol} correlates (rho >= {clusters_mod.DEFAULT_THRESHOLD}) with {collision}, "
                "already held or already admitted ahead of it this run",
            )
            continue

        kept_symbols.add(cand.symbol)
        kept.append(cand)

    return kept, skipped


def _price_and_atr14(symbol: str, ctx: _Ctx) -> tuple[Decimal, Decimal] | None:
    """`(close, ATR14)` for `symbol` as of `ctx.trade_date` -- what gate 2's cache reads and writes
    need to check/record trigger B. `None` when the symbol cannot be priced or ATR has not settled
    (too little history) -- the caller treats that the same as any other cache miss: fall back to
    fresh research rather than trust a check this function could not actually perform.
    """
    market = AsOfMarket(as_of=ctx.trade_date, settings=ctx.settings)
    try:
        close = market.close(symbol)
    except (UnpricedSymbol, FileNotFoundError):
        return None
    bars = market.history(symbol, lookback_days=None)
    if bars.empty:
        return None
    atr_series = atr_indicator(bars, period=14).iloc[:, 0]
    if atr_series.empty:
        return None
    last_atr = atr_series.iloc[-1]
    if last_atr != last_atr:  # NaN check -- a NaN never equals itself; avoids a bare pandas/numpy import
        return None
    return close, Decimal(str(float(last_atr)))


def _check_research_cache(
    ctx: _Ctx, cand: _Candidate, *, child_kind: research_cache_mod.ChildKind
) -> research_cache_mod.CacheCheckResult:
    """Gate 2, one child kind at a time -- see `research_cache.check_verdict_cache`'s own docstring
    for the exact check order. The Vibe lookup additionally passes this cycle's effective TA rating
    (`cand.ta_rating`, already final by the time `_stage_vibe` runs, whether fresh or itself cached)
    for the linked-invalidation rule.
    """
    assert ctx.card is not None and ctx.regime is not None
    priced = _price_and_atr14(cand.symbol, ctx)
    current_close = priced[0] if priced is not None else None
    ta_rating_for_linked_check = cand.ta_rating if child_kind == "vibedesk" else None
    return research_cache_mod.check_verdict_cache(
        cand.symbol, ctx.card.agent_id, child_kind,
        settings=ctx.settings, today=ctx.trade_date, regime_label=ctx.regime.label,
        current_close=current_close, ta_rating_for_linked_check=ta_rating_for_linked_check,
    )


def _write_research_cache(
    ctx: _Ctx, cand: _Candidate, *, child_kind: research_cache_mod.ChildKind, cost_usd: Decimal
) -> None:
    """Write a fresh cache entry right after a TA or Vibe child succeeds. Silently does nothing when
    the symbol cannot be priced/ATR'd today -- see `_price_and_atr14` -- which just means the *next*
    run pays for fresh research again, the safe default when this module cannot vouch for its own
    invalidation inputs."""
    assert ctx.card is not None and ctx.regime is not None
    priced = _price_and_atr14(cand.symbol, ctx)
    if priced is None:
        return
    price, atr14 = priced
    research_cache_mod.write_entry(
        symbol=cand.symbol, agent_card_id=ctx.card.agent_id, child_kind=child_kind,
        decision_date=ctx.trade_date, regime_label=ctx.regime.label,
        price_at_cache=price, atr14_at_cache=atr14,
        ta_rating=cand.ta_rating if child_kind == "tradingagents" else "",
        ta_run_id=cand.ta_run_id if child_kind == "tradingagents" else "",
        vibe_verdict=cand.vibe_verdict if child_kind == "vibedesk" else None,
        vibe_explicit=cand.vibe_explicit if child_kind == "vibedesk" else True,
        vibe_run_id=cand.vibe_run_id if child_kind == "vibedesk" else "",
        ta_rating_at_cache=cand.ta_rating if child_kind == "vibedesk" else "",
        research_cost_usd=cost_usd,
        settings=ctx.settings,
    )


def _stage_research(
    run: DeskRun, store: RunStore, ctx: _Ctx, cancel: threading.Event, budget: AgentBudget
) -> tuple[DeskRun, AgentBudget]:
    per_child = ctx.config.per_child_budget_usd
    for cand in ctx.candidates:
        stage_id = f"research_{cand.symbol}"
        if cancel.is_set():
            idx = next(i for i, s in enumerate(run.stages) if s.stage_id == stage_id)
            return _cancel_remaining(run, idx, budget=budget), budget

        # Gate 2 (TA side): a still-valid cached verdict is reused instead of paying for a fresh
        # child -- $0 spend, `verdict_source="cached"` downstream. See `_check_research_cache`.
        cache = _check_research_cache(ctx, cand, child_kind="tradingagents")
        if cache.valid:
            entry = cache.entry
            assert entry is not None
            cand.ta_rating = entry.ta_rating
            cand.ta_ok = True
            cand.ta_run_id = entry.ta_run_id
            cand.ta_source = "cached"
            cand.avoided_cost_usd += entry.research_cost_usd
            run = with_stage(
                run, stage_id, state="succeeded",
                started_at=dt.datetime.now(dt.UTC), completed_at=dt.datetime.now(dt.UTC),
                output_md=f"Reused cached TA verdict from {entry.decision_date.isoformat()}: "
                          f"{entry.ta_rating or 'n/a'}.",
                summary=f"Cache hit: rating {entry.ta_rating or 'n/a'} "
                        f"(cached {entry.decision_date.isoformat()}; saved ${entry.research_cost_usd}).",
                cost_usd=Decimal("0"),
            )
            store.save(run)
            continue

        # Gate 6 (backstop, unchanged): only launch if the whole-run cap can fund one more child. The
        # stage's own `error` wording is preserved byte-for-byte (an existing caller may already parse
        # it); `skip_reason`/`skip_detail` are new, feeding the same event into the observation log --
        # but only when this candidate has not already been tagged by an earlier gate (it always will
        # not have been: only kept candidates reach this loop at all).
        remaining = budget.cap_usd - budget.spent_usd
        if remaining < per_child:
            detail = f"workflow budget exhausted ({remaining} < {per_child})"
            run = with_stage(run, stage_id, state="skipped", error=detail)
            store.save(run)
            if cand.skip_reason is None:
                cand.skip_reason = "budget_exhausted"
                cand.skip_detail = detail
            continue
        run = with_stage(run, stage_id, state="running", started_at=dt.datetime.now(dt.UTC))
        store.save(run)
        try:
            child_id = _launch_ta(cand.symbol, ctx=ctx, budget_usd=per_child)
        except Exception as exc:
            run = with_stage(run, stage_id, state="degraded", error=f"could not start research: {exc}",
                             completed_at=dt.datetime.now(dt.UTC))
            store.save(run)
            continue
        cand.ta_run_id = child_id
        ctx.child_runs[stage_id] = child_id
        run = _persist_child_runs(run, ctx)
        child = _await_child("tradingagents", child_id, settings=ctx.settings, cancel=cancel)
        run, budget = _record_child(run, store, stage_id, child, budget, cand, ctx, is_ta=True)
        if cancel.is_set():
            idx = next(i for i, s in enumerate(run.stages) if s.stage_id == stage_id)
            return _cancel_remaining(run, idx + 1, budget=budget), budget
    return run, budget


def _persist_child_runs(run: DeskRun, ctx: _Ctx) -> DeskRun:
    """Write the `{stage_id: child_run_id}` map into the run's persisted config.

    The map is tracked in `ctx` as children launch, but the *study* reads it back off the persisted
    `DeskRun.config["child_runs"]` to bill each arm's research spend (`app.workflow.study.
    _research_cost_usd`). If it is only ever held in memory, every arm's `research_cost_usd` computes
    to zero in a real run -- which silently defeats the whole "net of research cost" comparison the
    study is built on. So it is persisted the moment a child id is known, not at the end.
    """
    return run.model_copy(
        update={"config": {**run.config, "child_runs": dict(ctx.child_runs)}}
    )


def _record_child(
    run: DeskRun, store: RunStore, stage_id: str, child: DeskRun | None,
    budget: AgentBudget, cand: _Candidate, ctx: _Ctx, *, is_ta: bool,
) -> tuple[DeskRun, AgentBudget]:
    if child is None:
        run = with_stage(run, stage_id, state="degraded",
                         error="child run did not complete (timeout or cancel)",
                         completed_at=dt.datetime.now(dt.UTC))
        store.save(run)
        return run, budget
    # Accumulate the child's realised cost into the workflow budget.
    budget = AgentBudget(
        cap_usd=budget.cap_usd,
        spent_usd=budget.spent_usd + child.cost_usd,
        calls=budget.calls,
    )
    if is_ta:
        cand.ta_rating = child.final_rating
        cand.ta_ok = child.state == "succeeded"
        summary = f"Rating: {child.final_rating or 'n/a'} (child {child.state})."
    else:
        v, explicit = verdict_mod.parse_verdict(child.final_md)
        cand.vibe_verdict = v
        cand.vibe_explicit = explicit
        cand.vibe_run_id = child.run_id
        summary = f"Verdict: {v} ({'explicit' if explicit else 'defaulted'}; child {child.state})."
    state: StageState = "succeeded" if child.state == "succeeded" else "degraded"
    run = with_stage(
        run, stage_id, state=state, completed_at=dt.datetime.now(dt.UTC),
        output_md=child.final_md, summary=summary, cost_usd=child.cost_usd,
    )
    if state == "degraded":
        run = run.model_copy(update={"degraded": True})
    run = run.model_copy(update={"budget": budget})
    store.save(run)
    # Gate 2's write side: a fresh, successful child's verdict is cached so a later cycle can reuse it
    # instead of paying again. A degraded/failed child writes nothing -- there is no verdict worth
    # caching, and the next run should simply try fresh research again.
    if state == "succeeded":
        _write_research_cache(
            ctx, cand,
            child_kind="tradingagents" if is_ta else "vibedesk",
            cost_usd=child.cost_usd,
        )
    return run, budget


def _stage_followup(run: DeskRun, store: RunStore, ctx: _Ctx, cancel: threading.Event) -> DeskRun:
    if cancel.is_set():
        idx = next(i for i, s in enumerate(run.stages) if s.stage_id == "followup_questions")
        return _cancel_remaining(run, idx, budget=run.budget)
    run = with_stage(run, "followup_questions", state="running", started_at=dt.datetime.now(dt.UTC))
    store.save(run)
    assert ctx.card is not None
    lines = ["# Follow-up questions", ""]
    for cand in ctx.candidates:
        cand.question = _followup_question(cand, ctx.card)
        lines += [f"**{cand.symbol}:** {cand.question}", ""]
    run = with_stage(
        run, "followup_questions", state="succeeded", completed_at=dt.datetime.now(dt.UTC),
        output_md="\n".join(lines), summary=f"Derived {len(ctx.candidates)} follow-up question(s).",
    )
    store.save(run)
    return run


def _stage_vibe(
    run: DeskRun, store: RunStore, ctx: _Ctx, cancel: threading.Event, budget: AgentBudget
) -> tuple[DeskRun, AgentBudget]:
    per_child = ctx.config.per_child_budget_usd
    for cand in ctx.candidates:
        stage_id = f"vibe_{cand.symbol}"
        if cancel.is_set():
            idx = next(i for i, s in enumerate(run.stages) if s.stage_id == stage_id)
            return _cancel_remaining(run, idx, budget=budget), budget

        # Gate 2 (Vibe side): checked independently of TA's own cache, against `cand.ta_rating` --
        # already final for this cycle, fresh or itself cache-served -- for the linked-invalidation
        # rule. See `_check_research_cache` and `research_cache.check_verdict_cache`.
        cache = _check_research_cache(ctx, cand, child_kind="vibedesk")
        if cache.valid:
            entry = cache.entry
            assert entry is not None
            cand.vibe_verdict = entry.vibe_verdict or "INCONCLUSIVE"
            cand.vibe_explicit = entry.vibe_explicit
            cand.vibe_run_id = entry.vibe_run_id
            cand.vibe_source = "cached"
            cand.avoided_cost_usd += entry.research_cost_usd
            run = with_stage(
                run, stage_id, state="succeeded",
                started_at=dt.datetime.now(dt.UTC), completed_at=dt.datetime.now(dt.UTC),
                output_md=f"Reused cached Vibe verdict from {entry.decision_date.isoformat()}: "
                          f"{entry.vibe_verdict or 'n/a'}.",
                summary=f"Cache hit: verdict {entry.vibe_verdict or 'n/a'} "
                        f"(cached {entry.decision_date.isoformat()}; saved ${entry.research_cost_usd}).",
                cost_usd=Decimal("0"),
            )
            store.save(run)
            continue

        remaining = budget.cap_usd - budget.spent_usd
        if remaining < per_child:
            detail = f"workflow budget exhausted ({remaining} < {per_child})"
            run = with_stage(run, stage_id, state="skipped", error=detail)
            store.save(run)
            if cand.skip_reason is None:
                cand.skip_reason = "budget_exhausted"
                cand.skip_detail = detail
            continue
        run = with_stage(run, stage_id, state="running", started_at=dt.datetime.now(dt.UTC))
        store.save(run)
        try:
            child_id = _launch_vibe(cand.symbol, cand.question, ctx=ctx, budget_usd=per_child)
        except Exception as exc:
            run = with_stage(run, stage_id, state="degraded", error=f"could not start vibe review: {exc}",
                             completed_at=dt.datetime.now(dt.UTC))
            store.save(run)
            continue
        ctx.child_runs[stage_id] = child_id
        run = _persist_child_runs(run, ctx)
        child = _await_child("vibedesk", child_id, settings=ctx.settings, cancel=cancel)
        run, budget = _record_child(run, store, stage_id, child, budget, cand, ctx, is_ta=False)
    return run, budget


def _stage_entry_plan(run: DeskRun, store: RunStore, ctx: _Ctx, cancel: threading.Event) -> DeskRun:
    if cancel.is_set():
        idx = next(i for i, s in enumerate(run.stages) if s.stage_id == "entry_plan")
        return _cancel_remaining(run, idx, budget=run.budget)
    run = with_stage(run, "entry_plan", state="running", started_at=dt.datetime.now(dt.UTC))
    store.save(run)
    assert ctx.card is not None
    lines = ["# Entry plan (full-workflow arm)", ""]
    for cand in ctx.candidates:
        if _passes_gate("full_workflow", cand):
            plan = _entry_plan_for(cand, ctx.card, ctx)
            ctx.plans[cand.symbol] = plan
            lines += [f"**{cand.symbol}** — notional {plan.notional}; {plan.thesis}"]  # type: ignore[attr-defined]
    if len(lines) == 2:
        lines.append("(no candidate cleared both gates)")
    run = with_stage(
        run, "entry_plan", state="succeeded", completed_at=dt.datetime.now(dt.UTC),
        output_md="\n".join(lines), summary=f"{len(ctx.plans)} name(s) cleared the full chain.",
    )
    store.save(run)
    return run


def _stage_orders(run: DeskRun, store: RunStore, ctx: _Ctx, cancel: threading.Event) -> DeskRun:
    run = with_stage(run, "stage_orders", state="running", started_at=dt.datetime.now(dt.UTC))
    store.save(run)
    card = ctx.card
    fill_date = _next_business_day(ctx.trade_date)

    # Record every candidate -- kept *and* hard-skipped by the necessity-gate chain alike -- and every
    # gate ruling BEFORE staging any order. The study's refused set lives here and nowhere else (see
    # app.workflow.candidates); a necessity-gate skip is refused just as surely as a `ta_gated`/
    # `vibe_gated` "no" is, so it must appear in this same log with its own reason, not be silently
    # absent from it.
    observations = [
        CandidateObservation(
            obs_id=uuid.uuid4().hex,
            run_id=run.run_id,
            symbol=cand.symbol,
            decision_date=ctx.trade_date,
            agent_card_id=card.agent_id if card else "",
            regime=ctx.regime.label if ctx.regime else "",
            entry_rank=cand.entry_rank,
            universe_source=cast("candidates_mod.UniverseSource", ctx.config.universe_mode),
            skip_reason=cand.skip_reason,
            skip_detail=cand.skip_detail,
            avoided_cost_usd=cand.avoided_cost_usd,
            gates=(
                GateDecision(gate="ta_gated", passed=_passes_gate("ta_gated", cand),
                             detail=cand.ta_rating or "n/a", was_explicit=cand.ta_ok,
                             verdict_source=_verdict_source_for("ta_gated", cand)),
                GateDecision(gate="vibe_gated", passed=_passes_gate("vibe_gated", cand),
                             detail=cand.vibe_verdict, was_explicit=cand.vibe_explicit,
                             verdict_source=_verdict_source_for("vibe_gated", cand)),
                GateDecision(gate="full_workflow", passed=_passes_gate("full_workflow", cand),
                             detail=f"{cand.ta_rating or 'n/a'}/{cand.vibe_verdict}",
                             was_explicit=cand.ta_ok and cand.vibe_explicit,
                             verdict_source=_verdict_source_for("full_workflow", cand)),
            ),
        )
        for cand in ctx.all_candidates
    ]
    candidates_mod.append_observations(observations, settings=ctx.settings)

    staged_counts: dict[WorkflowArm, int] = {}
    for arm in ctx.config.arms_enabled:
        book = book_mod.load_book(
            ctx.settings, arm, starting_cash=STARTING_CASH,
            card_id=card.agent_id if card else "",
            card_adopted_date=ctx.trade_date, universe_source=_book_source(ctx),
        )
        # **No pyramiding: never stage a buy for a symbol this arm's book already holds.** This is
        # the invariant `app.workflow.book.held_lots` states in its own docstring ("the workflow only
        # stages buys today"), enforced here at the one place buys are actually staged. Without it the
        # null arm re-buys every held name on every session its entry rule stays true -- a rule like
        # `close > sma(200)` fires for weeks on end -- and each re-buy is refused by the broker's
        # single-name weight cap, filling the book's ledger with rejections that say nothing about the
        # strategy (a backfill produced 117 such rejects against 5 real fills). The researched arms
        # were already protected upstream by the necessity gate's own held check; the null arm, which
        # bypasses that gate by design, was not. Checking the persisted book here covers every arm on
        # the one path that matters.
        held_symbols = {lot.symbol for lot in book_mod.held_lots(book)}
        plans: list[OrderPlan] = []
        # `raw_signal` is the study's null -- it ignores TA/Vibe (and therefore the necessity-gate
        # chain) entirely and trades every symbol whose entry rule fired, per `_passes_gate`'s own
        # docstring, so this loop runs over `ctx.all_candidates` (kept and necessity-gate-skipped alike),
        # not the narrowed `ctx.candidates`. For the three researched arms `_passes_gate` still refuses
        # any candidate whose `ta_ok`/`vibe_verdict` never got set because it was skipped upstream, so
        # nothing here changes their behaviour.
        for cand in ctx.all_candidates:
            # `over_cap` names are carried in `ctx.all_candidates` for the observation log ONLY -- they
            # fired beyond `max_research_symbols` and were never part of this session's traded universe,
            # so no arm stages them, the null arm included. This is the one skip_reason the null arm
            # does NOT trade through: every other is a necessity-gate refusal it deliberately ignores,
            # but an over-cap name simply is not in scope this session (before this record existed it
            # was truncated away entirely, and staging must stay byte-identical to that).
            if cand.skip_reason == "over_cap":
                continue
            if not _passes_gate(arm, cand):
                continue
            if cand.symbol in held_symbols:
                continue
            notional = (
                ctx.plans[cand.symbol].notional  # type: ignore[attr-defined]
                if arm == "full_workflow" and cand.symbol in ctx.plans
                else _notional_for(card) if card else Decimal("0")
            )
            plans.append(OrderPlan(
                agent_card_id=card.agent_id if card else "",
                symbol=cand.symbol, side="buy", notional=notional,
                thesis=card.thesis if card else "",
                invalidation=(card.falsification or "") if card else "",
                stop_level=None, regime=ctx.regime.label if ctx.regime else "",
                conviction=None, evidence=(),
            ))
        book = book_mod.stage_orders(book, plans, decision_date=ctx.trade_date, fill_date=fill_date, run_id=run.run_id)
        book_mod.save_book(ctx.settings, book)
        staged_counts[arm] = len(plans)

    lines = ["# Staged orders (fill next open)", "", f"Fill date: {fill_date.isoformat()}", ""]
    for arm in ctx.config.arms_enabled:
        lines.append(f"- **{arm}**: {staged_counts.get(arm, 0)} order(s)")
    run = with_stage(
        run, "stage_orders", state="succeeded", completed_at=dt.datetime.now(dt.UTC),
        output_md="\n".join(lines),
        summary="; ".join(f"{arm}={staged_counts.get(arm, 0)}" for arm in ctx.config.arms_enabled),
    )
    store.save(run)
    return run
