"""The wire and config types for the Agent Workflow desk.

Kept in one small module, apart from `pipeline` and `service`, for the same reason
`app.vibedesk.schemas` is: the request shape and the config payload are the contract surface, and a
router should be able to import them without pulling in the orchestration machinery or the paper
broker. `DeskRunSummary` is defined here too -- a copy of the shared wire type, exactly as
`app.tradingagents.service` and `app.vibedesk.schemas` each keep their own, because
`app.agentdesk.models` is a frozen shared contract this feature does not own.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.agentdesk.models import DeskKind
from app.workflow.book_models import WorkflowArm

__all__ = [
    "ARM_DEFS",
    "DeskRunSummary",
    "EntryPlan",
    "WorkflowRunRequest",
]


class _FrozenWire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


#: The four arms, with the copy the page shows. The order is the reading order of the study: the null
#: first, then the two single-tool gates, then the full chain -- so a reader compares each gate
#: against the raw arm to its left before reaching the arm that combines them.
ARM_DEFS: tuple[tuple[WorkflowArm, str, str], ...] = (
    (
        "raw_signal",
        "Raw Signal",
        "Every candidate the strategy fires is staged. The study's null -- not a coin flip, but the "
        "same strategy with no research gate at all.",
    ),
    (
        "ta_gated",
        "Trading-Agents Gated",
        "Only candidates the Trading Agents pipeline rates Buy or Overweight are staged.",
    ),
    (
        "vibe_gated",
        "Vibe Gated",
        "Only candidates a Vibe follow-up review returns SUPPORT for are staged.",
    ),
    (
        "full_workflow",
        "Full Workflow",
        "The whole chain: regime-selected strategy, both research gates, and entry-plan sizing.",
    ),
)


class WorkflowRunRequest(_FrozenWire):
    """The body of `POST /api/workflow/runs`.

    Concrete rather than a `Protocol` (unlike `app.tradingagents.service.StartRunRequest`): this
    feature owns both the router and the service, so there is no parallel-build hazard to insulate
    against, and a frozen model gives the 422 validation one place to live.
    """

    agent_card_id: str | None = None
    """Which strategy card the desk trades. `None` means auto-select from the regime call -- the
    feature the owner asked for, where the desk chooses its own strategy for the conditions."""

    trade_date: dt.date | None = None
    """The decision session. `None` is the newest stored session, matching every other desk."""

    budget_usd: str | None = None
    """Whole-run cap in dollars, decimal string. Spent across every child Trading Agents and Vibe
    run this workflow launches -- a workflow that chains several children can cost several times a
    single desk run, so the cap is at the workflow level, not per child."""

    per_child_budget_usd: str | None = None
    """Cap handed to each child run. The workflow stops launching research children once the
    remaining whole-run budget cannot fund one more at this rate -- a bounded-spend guarantee that a
    per-child cap alone would not give."""

    max_research_symbols: int | None = None
    """Ceiling on how many candidates get the full research treatment. The scan can surface up to a
    card's whole universe; researching all of them is neither affordable nor necessary, so the
    top-ranked few are chosen and the rest are staged by the raw arm only."""

    analysts: list[str] | None = None
    debate_rounds: int | None = None
    risk_rounds: int | None = None
    """Passed through to every child Trading Agents run, validated by that desk, not this one."""

    arms_enabled: list[str] | None = None
    """Which of the four arms to run. `None` is all four. Fewer arms is cheaper and is how a run that
    only wants the full workflow, without the comparison, is expressed."""

    model: str | None = None

    universe_mode: Literal["card", "screen"] | None = None
    """`None`/omitted defaults to `"card"` -- byte-for-byte today's behaviour, so the in-flight 4-arm
    study's existing callers (and every stored run's replay) are untouched. `"screen"` runs the new
    discovery-selector shortlist through the `universe_select` stage instead of the card's own
    universe. `Literal[...] | None` rather than a plain `str | None`: `_FrozenWire`'s `extra="forbid"`
    already rejects unknown top-level keys, but `universe_mode` names its own closed two-value
    vocabulary, so pinning it as a `Literal` gives the 422 for a typo'd value for free, before
    `app.workflow.service` (which resolves the omitted-vs-explicit distinction and the three
    screen-mode sub-fields below) is ever reached."""

    candidate_pool: str | None = None
    """Required (validated by `app.workflow.service`, not here) when `universe_mode == "screen"`;
    ignored otherwise. One of `app.workflow.universe.CANDIDATE_POOLS` (`"sector-etf"` |
    `"theme-etf"`). Kept as a plain `str` rather than a `Literal` naming the two pools directly: this
    module does not import `app.workflow.universe` (which itself must not import back from this
    package's orchestrator -- see `docs/WORKFLOW-UNIVERSE-BUILD-SPEC.md` recon #1 on the circular-
    import hazard that constrains where that module's own config type lives), so the closed-vocabulary
    check happens one layer down instead."""

    rank_key: str | None = None
    """Required when `universe_mode == "screen"`; ignored otherwise. One of
    `app.discovery.selector.RANK_KEYS` (`"mom12_1"` | `"mom6"` | `"trend"`), validated at the same
    place and for the same reason as `candidate_pool`. Ignored when `selector_id` is set (a named
    frozen selector owns its own ranking)."""

    selector_id: str | None = None
    """The primary `"screen"`-mode path: one of the eight frozen Round-33 selectors
    (`app.discovery.workflow_selectors.SELECTOR_IDS` -- `"mom12_1_hysteresis"`, `"breakout_atr"`,
    `"meanrev_rsi"`, `"trend_sticky"`, `"signal_density"`, `"divers_mom6"`, `"control_card_universe"`,
    `"control_week_rotation"`), validated one layer down in `app.workflow.service` exactly like
    `candidate_pool`/`rank_key`. When set it takes precedence over `candidate_pool`/`rank_key` and the
    `universe_select` stage runs `app.discovery.workflow_selectors.select_for_workflow`, which chooses
    the pool and applies hysteresis/regime-conditioning internally per `strategy-program/ROUND-33-PLAN.md`
    -- the only path that can faithfully reproduce the six frozen selectors that are not a bare
    `rank_key`. `candidate_pool`/`rank_key` remain the raw fallback for ad-hoc `discovery.select` runs
    when `selector_id` is omitted. `screen_top_n`, if set, still overrides the shortlist size."""

    screen_top_n: int | None = None
    """Required (or defaulted) when `universe_mode == "screen"`; ignored otherwise. The shortlist size
    handed to `app.discovery.selector.select`'s own `top_n`. Validated positive here (not deferred to
    `service.py`) because "a non-positive shortlist size" is a shape defect independent of whichever
    mode resolution `service.py` performs -- the same reasoning `WorkflowRunRequest`'s existing
    integer fields would apply if any of them carried a validator today."""

    screen_entry_rule: str | None = None
    """Optional less-restrictive entry rule for `universe_mode == "screen"`: a rules-DSL expression
    (`app.rules.grammar`) evaluated in place of the chosen card's own `entry` when scanning the screened
    shortlist. The card's own entry is often an event -- e.g. `... crosses_above ...` -- that fires on a
    single day and so accrues study candidates too slowly to measure; a trending *state* like
    `close > sma(200) and ema(20) > ema(50)` fires far more often. `None` uses the card's entry
    unchanged. Ignored in card mode. Parsed/validated by `app.workflow.service` (a 422 on a bad
    expression, before any run is created)."""

    weekly_budget_usd: Decimal = Decimal("100")
    """The trailing-7-day research-spend ceiling this run's own weekly circuit breaker (gate 0, see
    `docs/WORKFLOW-RESEARCH-SPEND-SPEC.md` §1) is evaluated against. Unlike `budget_usd`/
    `per_child_budget_usd` (kept as decimal strings, parsed and validated by `app.workflow.service`'s
    `_parse_positive_decimal`), this field is typed `Decimal` directly with its own validator below --
    it is not optional (every run has a weekly ceiling whether or not the caller states one), so there
    is no per-call parsing branch for `service.py` to own the way there is for the two nullable budget
    strings. Pydantic already round-trips `Decimal` through a JSON string by default (see
    `app.workflow.book_models`'s own module docstring on why that is this codebase's one safe crossing
    point for money), so a caller may send either a JSON string or a JSON number and get the same
    validated `Decimal` back. Default `Decimal("100")` is the top of the owner's stated $80-100 weekly
    range (`docs/WORKFLOW-RESEARCH-SPEND-SPEC.md` §1 proposes $90 as its own module-level constant
    default for the case no request overrides it -- the two defaults are independent knobs, not a
    typo: this field is the per-request override a caller may set, that constant is the fallback a
    caller who sends nothing effectively gets today since nothing yet reads this field)."""

    @field_validator("screen_top_n")
    @classmethod
    def _screen_top_n_is_positive(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError(f"screen_top_n must be >= 1: {value}")
        return value

    @field_validator("weekly_budget_usd")
    @classmethod
    def _weekly_budget_is_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError(f"weekly_budget_usd must be > 0: {value}")
        return value


class EntryPlan(_FrozenWire):
    """One symbol's synthesised entry decision -- the structured output of the `entry_plan` stage and
    what `stage_orders` turns into an `OrderPlan` per arm.

    The thesis and invalidation are not optional: the paper broker's mandate rejects an order that
    carries neither (`missing_thesis` / `missing_invalidation`), by design, because an entry nobody
    can state a reason to exit is not a plan. So the plan the desk commits to must carry both before
    an order is ever built from it.
    """

    symbol: str
    notional: Decimal
    thesis: str
    invalidation: str
    stop_level: Decimal | None = None
    conviction: Decimal | None = None
    regime: str = ""


class DeskRunSummary(_FrozenWire):
    """`DeskRunSummary` in the shared wire types -- this desk's own copy; see the module docstring."""

    run_id: str
    kind: DeskKind
    state: str
    label: str
    created_at: dt.datetime
    completed_at: dt.datetime | None
    degraded: bool
    error: str
    final_rating: str
    cost_usd: Decimal
    stages_total: int
    stages_done: int
