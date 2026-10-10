"""The vocabulary both desks speak, and the one file every other module in this feature imports.

Nothing here computes anything or calls anything. It exists so that `app.tradingagents`,
`app.vibedesk`, `app.agentdesk.evidence`, `app.agentdesk.grounding`, `app.agentdesk.store` and the
two API routers can be written against a fixed set of field names -- the alternative, discovered the
hard way on this project, is that two halves of an interface get built in parallel and each ships a
guess about the other.

**Money is a `Decimal` here and a string on the wire.** Same rule as everywhere else in this
codebase: a cost or a price crosses HTTP as a decimal string, never a JSON number, so it never
passes through an IEEE double. The API routers do that conversion; nothing in this package returns
a float.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.models import AgentBudget, AgentRole
from app.config import Settings

__all__ = [
    "MAX_GROUNDING_ATTEMPTS",
    "RUN_ID_MAX_LENGTH",
    "RUN_ID_PATTERN",
    "DeskKind",
    "DeskRun",
    "EvidenceItem",
    "EvidencePack",
    "EvidenceSection",
    "GroundingIssue",
    "GroundingVerdict",
    "RunState",
    "StageRecord",
    "StageState",
    "agentdesk_dir",
    "memory_log_path",
    "run_dir",
    "runs_dir",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


#: How many times a stage whose prose fails the grounding check is re-asked before it is released
#: marked `degraded`. Three, matching Vibe-Trading's own `revision_cap`: the first retry catches a
#: model that rounded a figure, the second catches one that invented a comparison, and a third
#: failure is a signal about the stage's prompt rather than about this call -- retrying past that
#: burns budget to produce the same rejection.
MAX_GROUNDING_ATTEMPTS = 3

DeskKind = Literal["tradingagents", "vibedesk", "workflow", "manager"]
"""Which desk a run belongs to. The first two share this package, a run store and a grounding gate;
they do not share an orchestration model -- one is a fixed pipeline with two bounded debate loops,
the other a preset-defined DAG -- which is why they are two modules and not one parameterised one.

`"workflow"` is a third kind, added later: an *orchestrator* that runs its own staged pipeline and,
within it, launches child `tradingagents` and `vibedesk` runs via their service functions (never
HTTP), then executes an entry plan on a persistent paper book. It reuses this package's run store,
grounding gate and job registry verbatim; the registry's one-slot-per-kind rule (`app.agentdesk.jobs`)
is what lets a workflow run and the child runs it starts occupy different slots. See
`app.workflow` and `docs/AGENT-DESK-CONTRACT.md`."""

RunState = Literal["queued", "running", "succeeded", "failed", "cancelled"]
"""The run as a whole. `"succeeded"` means every stage reached a terminal non-failed state and a
final report was produced -- it does *not* mean nothing degraded; check `DeskRun.degraded`."""

StageState = Literal[
    "pending",
    "running",
    "succeeded",
    "degraded",
    "failed",
    "blocked",
    "skipped",
]
"""One stage's outcome, with three distinctions this project has paid for before.

`"degraded"` is not `"succeeded"`: the stage produced prose but it failed the grounding check
:data:`MAX_GROUNDING_ATTEMPTS` times, so its numbers are not verified and the UI must say so.

`"blocked"` is not `"failed"`: an upstream stage failed, so this one never ran. Vibe-Trading draws
the same line, and this codebase has its own scar for eliding it -- a loop reported "running" while
failing 1,644 times in a row because per-iteration resilience hid the aggregate. A blocked stage is
evidence about its upstream, not about itself.

`"skipped"` is a configuration outcome, not a failure: the analyst was deselected, or the debate
round count meant this turn never happened.
"""


# ---------------------------------------------------------------------------
# Evidence -- the facts a stage is given, and the set its prose is checked against
# ---------------------------------------------------------------------------


class EvidenceItem(_Frozen):
    """One fact, with its provenance attached.

    `value` is a string even when it is a number, for the same reason money is: the pack is rendered
    into a prompt and compared against model prose as text, and a float round-trip would make the
    rendered figure differ from the stored one in the last digit -- which is precisely the
    difference the grounding check is looking for.
    """

    key: str
    """Stable machine name, unique within its section -- `"close"`, `"rsi_14"`, `"headline_count"`."""

    label: str
    """How the fact is written into the prompt: `"Close"`, `"RSI(14)"`."""

    value: str
    """The figure or short string, exactly as it should appear in prose."""

    unit: str = ""
    """`"USD"`, `"%"`, `"shares"`. Empty for a dimensionless index or a string value."""

    as_of: str = ""
    """ISO date or timestamp this fact was true at. Rendered next to the value, because a figure
    without an as-of is the failure mode both upstream systems spend the most machinery preventing."""

    source: str = ""
    """Which provider produced it -- `"yahoo"`, `"stooq"`, `"sec-edgar"`, `"fred"`, `"stocktwits"`,
    `"polymarket"`, `"duckdb-store"`. Carried so the UI can show a fact's origin without the API
    having to re-derive it."""


class EvidenceSection(_Frozen):
    """A titled group of facts, plus any prose the group needs that is not itself a fact.

    `text` exists for headlines, filing titles and rule expressions -- content a stage must read but
    which contains no figure the stage is entitled to quote. Numbers appearing only in `text` are
    **not** added to the grounded set; see `app.agentdesk.grounding` for why quoting a number out of
    a headline is exactly the case the gate is meant to catch.
    """

    title: str
    items: tuple[EvidenceItem, ...] = ()
    text: str = ""
    """Free prose. Rendered to the model, never treated as grounding evidence."""


class EvidencePack(_Frozen):
    """Everything one stage is allowed to know, assembled deterministically before the call.

    Built by `app.agentdesk.evidence`, rendered into the user turn, and then held for the lifetime
    of the stage so `app.agentdesk.grounding` can check the response against it. A stage with an
    empty pack is legal and means exactly what it says -- the data layer returned nothing -- in which
    case the stage's prompt must tell it to report unavailability rather than estimate. That
    instruction is TradingAgents' `NO_DATA_AVAILABLE` sentinel contract, restated: *do not estimate
    or fabricate values; report that data is unavailable for this symbol.*
    """

    symbol: str = ""
    """Empty for a pack that is not about one instrument (a macro or market-wide pack)."""

    as_of: dt.date | None = None
    sections: tuple[EvidenceSection, ...] = ()

    warnings: tuple[str, ...] = ()
    """Staleness, a provider that failed, a section that came back empty. Rendered to the model and
    surfaced in the UI -- a warning the reader never sees is a warning that did not happen."""

    @property
    def is_empty(self) -> bool:
        return not any(section.items or section.text for section in self.sections)


# ---------------------------------------------------------------------------
# The grounding verdict
# ---------------------------------------------------------------------------


class GroundingIssue(_Frozen):
    """One reason a stage's prose was rejected."""

    kind: Literal["ungrounded_number", "no_evidence", "empty_output"]
    detail: str
    """Human-readable, and quoted back to the model verbatim on the retry -- so it must name the
    offending token, not merely say that one existed."""


class GroundingVerdict(_Frozen):
    """Whether a stage's prose survived the gate, and what it cost to find out."""

    ok: bool
    issues: tuple[GroundingIssue, ...] = ()

    attempts: int = 1
    """How many calls this stage took, including the accepted one. Greater than 1 means the model
    was corrected; the run's cost reflects every attempt, not just the last."""

    degraded: bool = False
    """True when the prose was released despite failing -- `ok` is False and the output is shown with
    its issues attached. Never silently: `DeskRun.degraded` is set from this."""

    checked_tokens: int = 0
    """How many numeric tokens the gate examined. Zero with `ok=True` means the stage wrote prose
    containing no figures at all, which is a legitimate pass and a useful thing to be able to see."""


# ---------------------------------------------------------------------------
# A run, and one stage of it
# ---------------------------------------------------------------------------


class StageRecord(_Frozen):
    """One agent turn: what it was, what it produced, and what it cost.

    The same type serves both desks. A TradingAgents pipeline stage has `depends_on` holding its
    single predecessor and `layer` counting position in the pipeline; a VibeDesk task has its
    preset-declared dependencies and its topological layer. Nothing downstream -- neither router nor
    page -- needs to know which desk produced a record.
    """

    stage_id: str
    """Unique within the run. For TradingAgents these are fixed (`"market_analyst"`,
    `"bull_1"`, `"risk_neutral_2"`, `"portfolio_manager"`); for VibeDesk they are the preset's own
    task ids."""

    role: AgentRole
    label: str
    """What the UI calls it -- `"Market Analyst"`, `"Bull Researcher (round 2)"`."""

    seat: str = ""
    """VibeDesk only: the preset's agent id (`"bull_advocate"`, `"risk_officer"`). Empty for
    TradingAgents, whose seats are the roles themselves. Kept out of `AgentRole` on purpose -- adding
    a preset must not require a Python edit."""

    state: StageState = "pending"
    layer: int = 0
    depends_on: tuple[str, ...] = ()

    started_at: dt.datetime | None = None
    completed_at: dt.datetime | None = None

    output_md: str = ""
    """The stage's report, rendered markdown. Empty until the stage completes."""

    summary: str = ""
    """One or two sentences. This -- never `output_md` -- is what downstream stages receive, matching
    Vibe-Trading's swarm, where workers pass summaries and only artifacts pass by path. Keeping the
    full text out of downstream prompts is what stops a ten-stage run from quadratic prompt growth."""

    grounding: GroundingVerdict | None = None
    call_ids: tuple[str, ...] = ()
    """Every `AgentCall.call_id` this stage produced, retries included, in order. The archived call
    records under `data/loop/agent_calls/` are the audit trail; this is the pointer into it."""

    cost_usd: Decimal = Decimal(0)
    error: str = ""
    """Why it failed or was blocked. Empty on success."""


class DeskRun(_Frozen):
    """One end-to-end desk run, and the object the API serialises.

    Immutable, like everything else here: `app.agentdesk.store` writes a new snapshot per stage
    transition rather than mutating, so a poll that lands mid-run reads a consistent picture instead
    of a half-updated one.
    """

    run_id: str
    kind: DeskKind
    state: RunState = "queued"

    created_at: dt.datetime
    completed_at: dt.datetime | None = None

    config: dict[str, Any] = Field(default_factory=dict)
    """The request that started the run, verbatim -- ticker, date, rounds, preset, model, budget cap.
    Kept whole so a run can be read a month later without the caller's parameters being reconstructed
    from the stage list."""

    stages: tuple[StageRecord, ...] = ()

    final_md: str = ""
    """The run's report. For TradingAgents the portfolio manager's decision; for VibeDesk the last
    topological layer's output."""

    final_rating: str = ""
    """TradingAgents only: one of Buy / Overweight / Hold / Underweight / Sell, extracted from
    `final_md` by a deterministic regex -- never by a second model call, matching upstream's own
    `parse_rating`. Empty for VibeDesk, which produces a research report and no rating."""

    budget: AgentBudget
    degraded: bool = False
    """True if any stage was released ungrounded. Surfaced at run level so the UI can badge the
    whole report, not only the stage that caused it."""

    error: str = ""

    @property
    def cost_usd(self) -> Decimal:
        return self.budget.spent_usd


# ---------------------------------------------------------------------------
# Where a run lives on disk
# ---------------------------------------------------------------------------


#: The one shape a desk run id (or a job id keyed the same way) may take at an HTTP boundary.
#:
#: Every id this application generates for a run is `uuid.uuid4().hex` -- 32 lowercase hex characters
#: (`app.manager.service.start_brief`, `app.vibedesk.service.start_run`,
#: `app.tradingagents.service.start_run`, `app.workflow.service.start_workflow_run`,
#: `app.tournament.jobs`, `app.timeframes.jobs`). The alphabet here is deliberately wider than that,
#: because ids written by hand or by a smoke script also live on disk beside them --
#: `data/agentdesk/manager/runs/` holds `smoke-095628`, so a hyphen has to be legal -- and because a
#: caller mistyping one character should read as this router's own "not found", not as a validation
#: error the caller has to interpret differently for the same underlying mistake.
#:
#: What it must never admit is a path: no `/`, no `\`, and no id that *is* `.` or `..`, since
#: `run_dir` joins this string straight onto a directory. Requiring the first character to be
#: alphanumeric is what rules the last two out. A `%5C`-encoded backslash reached
#: `runs_dir(...) / run_id` before this constant existed and resolved to another desk's run tree.
RUN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"

#: Length bound applied alongside `RUN_ID_PATTERN`. 32 is what a uuid hex needs; 64 leaves room for
#: a prefixed or suffixed id without letting a caller push an unbounded string into a filesystem call.
RUN_ID_MAX_LENGTH = 64


def agentdesk_dir(settings: Settings) -> Path:
    """`data/agentdesk/` -- this feature's whole footprint.

    Deliberately not under `data/loop/`, which belongs to the evolution loop and is pruned and
    reasoned about on that loop's terms. The one thing the desks *do* write into the loop's tree is
    the `AgentCall` archive, via `app.agents.client`, because that archive is the audit trail for
    every model call this application makes regardless of which feature made it.
    """
    return settings.data_dir / "agentdesk"


def runs_dir(settings: Settings, kind: DeskKind) -> Path:
    """`data/agentdesk/<kind>/runs/`."""
    return agentdesk_dir(settings) / kind / "runs"


def run_dir(settings: Settings, kind: DeskKind, run_id: str) -> Path:
    """One run's directory. `run.json` is the `DeskRun` snapshot; per-stage markdown sits alongside.

    Raises `ValueError` if `run_id` would not name a directory sitting *directly* inside
    `runs_dir(settings, kind)`. The HTTP boundary already refuses ids with separators or dot segments
    (`RUN_ID_PATTERN`, applied by every router that takes one), so this is the defence-in-depth half:
    whatever the caller, an id can never name a directory outside the desk it was meant to index.
    `resolve()` on both sides so `..`, a Windows backslash, and a symlinked runs tree all collapse to
    a real location before the containment check -- the same shape as
    `app.evolution.dossier._card_path_under`, which learned this for genome ids.
    """
    base = runs_dir(settings, kind)
    candidate = (base / run_id).resolve()
    if candidate.parent != base.resolve():
        raise ValueError(f"run id does not name a run under this desk: {run_id!r}")
    return candidate


def memory_log_path(settings: Settings) -> Path:
    """`data/agentdesk/tradingagents/decisions.jsonl` -- the decision log whose entries are resolved
    against realized return on a later run of the same ticker.

    JSONL rather than TradingAgents' single markdown file: the upstream format needs an
    `<!-- ENTRY_END -->` delimiter and a whole-file atomic rewrite to resolve a pending entry, which
    is a lot of machinery to work around a format that was not chosen for the job. One JSON object
    per line resolves by rewriting the file the same way, without needing a delimiter an LLM cannot
    emit.
    """
    return agentdesk_dir(settings) / "tradingagents" / "decisions.jsonl"
