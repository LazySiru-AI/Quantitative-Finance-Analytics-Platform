"""The one structured output every swarm worker produces.

A preset task is a single model turn: read the shared evidence, read the summaries of whatever it
depends on, write a report. There is no reason for that turn's shape to vary by preset -- a bull
advocate and a risk aggregator both produce "a report, and a short summary of it" -- so one frozen
type serves every task in every preset, the same way `app.tradingagents` gives each of its stages a
role-specific output type only where the *shape* of the answer actually differs (a rating, a debate
turn). Vibe Trading's presets never differ in shape, only in prose content, so a second type would be
a distinction with no caller that needs it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.agentdesk.models import DeskKind, RunState

__all__ = [
    "DeskRunSummary",
    "PresetAgentOut",
    "PresetDetail",
    "PresetSummary",
    "PresetTaskOut",
    "PresetVariableOut",
    "PresetsResponse",
    "RunsResponse",
    "StartSwarmRequest",
    "WorkerOutput",
    "worker_prose",
]


class WorkerOutput(BaseModel):
    """What one preset task's model call returns.

    `report` is the stage's full markdown -- what a reader sees if they open this stage's output.
    `summary` is the one-or-two sentence digest spliced into a dependent task's prompt instead of the
    full report, per the rule in `app.vibedesk`'s own module docstring: passing full text downstream
    makes prompt size grow with the square of the desk.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    report: str
    """The stage's full markdown report."""

    summary: str
    """A one-or-two sentence digest of `report`, written for a reader who will never see the full
    text -- this is what `depends_on` splices into a downstream task's prompt."""


def worker_prose(output: WorkerOutput) -> str:
    """The text `app.agentdesk.grounding.check` validates a `WorkerOutput` against.

    Both fields are checked -- a model that fabricates a figure only in `summary` (which is what a
    downstream task and the UI's stage list actually read first) must be caught exactly as readily as
    one that fabricates it in `report`.
    """
    return f"{output.report} {output.summary}"


# ---------------------------------------------------------------------------
# Wire types -- see docs/AGENT-DESK-CONTRACT.md's "Vibe Trading" section.
#
# `DeskRunSummary` duplicates the shape documented as shared between the two desks rather than
# importing a common definition, because no such shared Python type exists (the contract is pinned in
# prose, not in `app.agentdesk.models`, which this package may only import from -- see this package's
# scope fence). This mirrors the frontend's own documented convention of one local copy per API
# module rather than a shared cross-module import.
# ---------------------------------------------------------------------------


class _FrozenWire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class PresetVariableOut(_FrozenWire):
    """One entry of `PresetDetail.variables`."""

    name: str
    label: str
    required: bool
    default: str


class PresetAgentOut(_FrozenWire):
    """One entry of `PresetDetail.agents` -- the seat's id/label/blurb only; its `system` prompt and
    `evidence` sections are implementation detail, not shown to the page."""

    id: str
    label: str
    blurb: str


class PresetTaskOut(_FrozenWire):
    """One entry of `PresetDetail.tasks`."""

    id: str
    agent_id: str
    depends_on: tuple[str, ...]
    layer: int


class PresetSummary(_FrozenWire):
    """`GET /api/vibedesk/presets` list entry."""

    name: str
    label: str
    blurb: str
    agent_count: int
    layer_count: int


class PresetDetail(PresetSummary):
    """`GET /api/vibedesk/presets/{name}` response body."""

    agents: tuple[PresetAgentOut, ...]
    tasks: tuple[PresetTaskOut, ...]
    variables: tuple[PresetVariableOut, ...]


class PresetsResponse(_FrozenWire):
    presets: tuple[PresetSummary, ...]


class StartSwarmRequest(_FrozenWire):
    """`POST /api/vibedesk/runs` request body."""

    preset: str
    symbol: str = ""
    question: str = ""
    variables: dict[str, str] = Field(default_factory=dict)
    budget_usd: str = "5.00"
    """Decimal string, per this codebase's money convention -- never a JSON number."""
    model: str | None = None


class DeskRunSummary(_FrozenWire):
    """What `GET /api/vibedesk/runs` returns per run -- never `stages`, `final_md` or `config`."""

    run_id: str
    kind: DeskKind
    state: RunState
    label: str
    created_at: str
    completed_at: str | None
    degraded: bool
    error: str
    final_rating: str
    cost_usd: str
    stages_total: int
    stages_done: int


class RunsResponse(_FrozenWire):
    runs: tuple[DeskRunSummary, ...]
