"""Pinned shapes for the manager desk. **Nothing else in `app.manager` or the frontend defines a
shape; they import from here.** Field names are the contract (`docs/MANAGER-DESK-PLAN.md` §3 and the
"Manager Desk" section of `docs/AGENT-DESK-CONTRACT.md`) -- a name changed here without changing the
TS mirror is the exact drift the persona feature's contract docs exist to prevent.

Conventions, identical to every other desk: money and rates are decimal STRINGS on the wire;
timestamps are ISO-8601 strings or `None`; every model is frozen with `extra="forbid"`;
`GroundingVerdict` is reused verbatim from `app.agentdesk.models`, never redefined.

The snapshot is deliberately *generic-but-typed*: every source renders into the same
`SnapshotSection` shape (a `text` the model reads, `figures` the grounding gate mints, `items` the diff
keys on). That is what lets layer A (sources) and layer B (rules) be built by different workers
against one shape: a rule only needs `section.key`, an item's `id`, and the figure keys named in
`FIGURE_KEYS` below -- so those keys are pinned here too, not invented per module.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agentdesk.models import GroundingVerdict, agentdesk_dir
from app.config import Settings

__all__ = [
    "AREAS",
    "COMMISSION_KINDS",
    "FIGURE_KEYS",
    "MANAGER_STAGES",
    "RULES",
    "Area",
    "Brief",
    "BriefBullet",
    "Caps",
    "ChangeItem",
    "ChangeSet",
    "Commission",
    "CommissionKind",
    "CommissionState",
    "DataHealth",
    "ManagerChatThread",
    "ManagerChatTurn",
    "ManagerConfig",
    "ManagerSnapshot",
    "Scope",
    "SectionItem",
    "Severity",
    "SnapshotSection",
    "SourceRef",
    "Synthesis",
    "Window",
    "chats_dir",
    "manager_dir",
    "snapshots_dir",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Closed vocabularies -- pinned literals, mirrored as TS unions
# ---------------------------------------------------------------------------

Scope = Literal["owner", "member"]
Window = Literal["yesterday", "week", "custom"]
Severity = Literal["attention", "notable", "fyi"]

Area = Literal[
    "account", "tax", "paperdesk", "persona_books", "persona_traders", "research",
    "desks", "live", "personas", "market", "events", "news", "data", "activity",
]
#: Every `Area`, in the order the tab renders them. `sources.collect` produces at most one section
#: per area; a missing one is named in `ManagerSnapshot.warnings` / `ChangeSet.sections_missing`.
AREAS: Final[tuple[str, ...]] = (
    "account", "tax", "paperdesk", "persona_books", "persona_traders", "research",
    "desks", "live", "personas", "market", "events", "news", "data", "activity",
)

#: Figure keys a section's `items[].figures` / `section.figures` may carry, per area. Layer A writes
#: exactly these names; layer B's rules read exactly these names. Values are always decimal strings
#: (a fraction like "0.031" for a rate, never a pre-multiplied percent; days as "2"; counts as "3").
FIGURE_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "account": ("weight_pct", "day_change_pct", "market_value", "unrealized_pct", "quantity",
                "total_market_value", "total_day_change_pct", "cash_balance", "unpriced_count"),
    "tax": ("ytd_short_gain", "ytd_long_gain", "ytd_net_gain", "deferred_disallowed",
            "permanently_disallowed", "open_window_count", "days_until_safe", "loss_amount"),
    "paperdesk": ("equity", "total_return", "excess_return", "max_drawdown", "open_positions",
                  "rejection_count"),
    "persona_books": ("equity", "return_pct", "open_count", "trade_count"),
    "persona_traders": ("equity", "return_pct", "benchmark_return_pct", "excess_pct",
                        "decision_count", "positions"),
    "research": ("generation", "promoted_count", "pending_seats", "median_excess", "q_value"),
    "desks": ("cost_usd", "stages_done", "stages_total"),
    "live": ("confidence", "price", "cost_usd"),
    "personas": ("note_count", "bullish_count", "bearish_count", "risk_on", "risk_off", "mixed"),
    "market": ("value", "change_day", "change_week", "change_month", "fear_greed"),
    "events": ("days_until",),
    "news": ("count",),
    "data": ("age_seconds", "stale_count", "unknown_count"),
    "activity": ("quantity", "amount"),
}

#: The change-detector catalogue `rules.diff` runs, pinned so the frontend can map a rule id to a
#: label/glyph and a test can assert exactly which rules fired. One pure function per id in
#: `app.manager.rules`; a rule's default `Severity` lives beside its function, not here.
RULES: Final[tuple[str, ...]] = (
    # account
    "position_weight_moved", "position_day_move", "symbol_became_unpriced", "equity_incomplete",
    "new_tax_warning_group", "cash_below_floor",
    # tax
    "wash_window_opened", "wash_window_closing", "ytd_net_gain_crossed", "new_permanent_disallowance",
    # paperdesk / persona books / traders
    "seat_excess_moved", "seat_promoted", "seat_rejected_orders", "trader_decision_traded",
    "book_drawdown_deepened",
    # research
    "generation_finished", "pending_seat_added", "blocker_added", "promotion_recorded",
    # desks / live
    "desk_run_finished", "desk_run_failed", "live_decision_made",
    # personas
    "stance_flipped_on_holding", "persona_new_notes", "watchlist_entrant", "watchlist_leaver",
    "regime_tally_changed", "persona_profile_stale",
    # market / events
    "macro_beyond_week_range", "fear_greed_regime_changed", "event_entering_window",
    # data
    "source_went_stale", "refresh_sweep_failed", "social_daemon_unhealthy",
)

CommissionKind = Literal["tradingagents", "vibedesk", "workflow", "persona_chat"]
COMMISSION_KINDS: Final[tuple[str, ...]] = ("tradingagents", "vibedesk", "workflow", "persona_chat")
CommissionState = Literal[
    "proposed", "approved", "running", "succeeded", "failed", "cancelled", "declined",
]

#: Fixed stage ids of one manager `DeskRun`, in order. `collect` and `commission` are deterministic;
#: the other four are grounded model stages.
MANAGER_STAGES: Final[tuple[str, ...]] = (
    "collect", "triage", "synthesis", "research_plan", "commission", "brief",
)


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------


class SourceRef(_Frozen):
    """A typed pointer the UI can turn into a jump chip. `kind` is closed; `id` is the target's own
    id (a run_id, note_id, symbol, ...); `label` is the short text the chip shows."""

    kind: Literal["run", "note", "symbol", "event", "gen", "snapshot", "txn", "persona", "seat"]
    id: str
    label: str


# ---------------------------------------------------------------------------
# Layer A -- the snapshot
# ---------------------------------------------------------------------------


class SectionItem(_Frozen):
    """One row of a section: a position, a wash-sale symbol, a desk seat, a run, a note, an event.
    `id` is stable across snapshots (a symbol, a run_id, a note_id) so the diff can pair rows."""

    id: str
    label: str
    figures: dict[str, str] = Field(default_factory=dict)   # keys ⊆ FIGURE_KEYS[area]
    observed_at: str | None = None                          # ISO; the row's own timestamp when it has one
    refs: tuple[SourceRef, ...] = ()
    text: str = ""                                          # one dense line the model may read


class SnapshotSection(_Frozen):
    """One area of the snapshot. `ok=False` means the source failed to collect; `warnings` says why,
    and `items`/`figures` are then empty -- never a fabricated zero."""

    key: Area
    ok: bool
    as_of: str | None = None
    text: str = ""                                          # the section's summary the model reads
    figures: dict[str, str] = Field(default_factory=dict)   # section-level figures (totals etc.)
    items: tuple[SectionItem, ...] = ()
    warnings: tuple[str, ...] = ()


class ManagerSnapshot(_Frozen):
    scope: Scope
    as_of: str                                              # ISO date the snapshot describes
    generated_at: str                                       # ISO datetime it was collected
    sections: tuple[SnapshotSection, ...] = ()
    warnings: tuple[str, ...] = ()

    def section(self, key: str) -> SnapshotSection | None:
        for s in self.sections:
            if s.key == key:
                return s
        return None


# ---------------------------------------------------------------------------
# Layer B -- the change set
# ---------------------------------------------------------------------------


class ChangeItem(_Frozen):
    id: str
    area: Area
    rule: str                                               # ∈ RULES
    severity: Severity
    headline: str = Field(max_length=160)                   # dense; the tab's row
    detail: str = Field(default="", max_length=320)         # the "why"
    as_of: str | None = None
    observed_at: str | None = None
    figures: dict[str, str] = Field(default_factory=dict)
    source_refs: tuple[SourceRef, ...] = ()


class ChangeSet(_Frozen):
    window: Window
    since: str | None                                       # prior snapshot's as_of; None => streams only
    until: str                                              # current snapshot's as_of
    scope: Scope
    items: tuple[ChangeItem, ...] = ()
    sections_missing: tuple[str, ...] = ()                  # areas whose source failed, named
    prior_snapshot: str | None = None                       # the file the diff ran against, or None
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Layer C -- commissions, synthesis, brief
# ---------------------------------------------------------------------------


class Commission(_Frozen):
    commission_id: str
    kind: CommissionKind
    params: dict[str, Any] = Field(default_factory=dict)    # the child's own request fields
    rationale: str = ""
    budget_usd: str = "0"
    state: CommissionState = "proposed"
    child_run_id: str | None = None
    child_summary: str = ""
    source_refs: tuple[SourceRef, ...] = ()


class BriefBullet(_Frozen):
    text: str
    source_refs: tuple[SourceRef, ...] = ()


class Synthesis(_Frozen):
    """The situation assessment. **Deliberately has no field for what the owner should do with their
    account** -- there is nowhere for an instruction to land, which is the structural half of the
    not-advice guarantee (the prompt is the other half)."""

    assessment: tuple[BriefBullet, ...] = ()
    agreements: tuple[BriefBullet, ...] = ()
    conflicts: tuple[BriefBullet, ...] = ()
    risks: tuple[BriefBullet, ...] = ()
    open_questions: tuple[BriefBullet, ...] = ()
    caveat: str = ""                                        # fixed text; see pipeline.CAVEAT


class DataHealth(_Frozen):
    stale: tuple[str, ...] = ()                             # freshness source keys
    unknown: tuple[str, ...] = ()


class Brief(_Frozen):
    brief_id: str
    run_id: str
    scope: Scope
    window: Window
    as_of: str
    generated_at: str
    attention: tuple[ChangeItem, ...] = ()                  # triage's ranked "look today" list
    changes: ChangeSet
    synthesis: Synthesis
    commissions: tuple[Commission, ...] = ()
    data_health: DataHealth = DataHealth()
    degraded: bool = False
    grounding: GroundingVerdict = GroundingVerdict(ok=True, checked_tokens=0)
    cost_usd: str = "0"
    final_md: str = ""


class Caps(_Frozen):
    brief_usd: str
    commission_usd: str
    chat_usd: str
    daily_usd: str


class ManagerConfig(_Frozen):
    agent_available: bool
    agent_reason: str
    autonomy: str                                           # "propose" | "auto_bounded"
    unattended_kinds: tuple[str, ...] = ()
    autopilot_enabled: bool = False
    brief_time_et: str = "09:45"
    caps: Caps
    last_brief_at: str | None = None
    last_snapshot_at: str | None = None
    spent_today_usd: str = "0"


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ManagerChatTurn(_Frozen):
    turn_id: str
    asked_at: str
    question: str
    answer: str
    source_refs: tuple[SourceRef, ...] = ()
    commissions: tuple[Commission, ...] = ()                # proposed/started from this turn
    refreshed: bool = False                                 # re-collected before answering
    grounding: GroundingVerdict = GroundingVerdict(ok=True, checked_tokens=0)
    degraded: bool = False
    cost_usd: str = "0"


class ManagerChatThread(_Frozen):
    thread_id: str
    title: str
    created_at: str
    updated_at: str
    turn_count: int = 0
    spent_usd: str = "0"
    turns: tuple[ManagerChatTurn, ...] = ()                 # oldest first; [] on the list endpoint


# ---------------------------------------------------------------------------
# On-disk layout -- `data/agentdesk/manager/`
# ---------------------------------------------------------------------------


def manager_dir(settings: Settings) -> Path:
    """`data/agentdesk/manager/` -- runs live in `runs/` via the standard `RunStore(kind="manager")`."""
    return agentdesk_dir(settings) / "manager"


def snapshots_dir(settings: Settings) -> Path:
    """`data/agentdesk/manager/snapshots/<YYYY-MM-DD>.<scope>.json`."""
    return manager_dir(settings) / "snapshots"


def chats_dir(settings: Settings) -> Path:
    """`data/agentdesk/manager/chats/<thread_id>.json`."""
    return manager_dir(settings) / "chats"


def snapshot_path(settings: Settings, as_of: dt.date, scope: str) -> Path:
    return snapshots_dir(settings) / f"{as_of.isoformat()}.{scope}.json"
