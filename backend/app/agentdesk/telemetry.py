"""Token and cost totals off the archived `AgentCall` ledger -- the primitive both desk-level and
workflow-level telemetry are built from.

`app.agents.client._archive_call` writes one JSON file per model call to `agent_calls_dir(settings)`,
regardless of which desk made it (`app.agentdesk.models.DeskKind` covers all three). `StageRecord.
call_ids` is a stage's pointer into that archive -- see its own docstring in `app.agentdesk.models`.
This module is the read side: given a list of call ids, look each one up and add together what it
cost, in tokens and in dollars.

**Never raises on a missing or corrupt call file.** A call archived weeks ago that was since pruned,
or a file truncated by a crash mid-write, must not take down a telemetry report the way it would not
be allowed to take down `app.agentdesk.store.RunStore.list_runs` -- see that module's own docstring
for the identical choice. `load_call` returns `None` for such a file (logged, not raised);
`summarize_calls` simply skips it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.agents.models import AgentCall, agent_calls_dir
from app.config import Settings

__all__ = ["CallCostSummary", "load_call", "summarize_calls"]

logger = logging.getLogger(__name__)


class CallCostSummary(BaseModel):
    """Token and cost totals over some set of calls -- a stage's `call_ids`, a child run's every
    stage, or a whole workflow run's own stages plus every child's. Frozen, like every other wire
    model in this feature."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_count: int
    """How many of the requested call ids actually resolved to a readable `AgentCall` -- may be less
    than the number of ids passed in, when one could not be read (see the module docstring)."""

    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    cost_usd: Decimal


def load_call(call_id: str, *, settings: Settings) -> AgentCall | None:
    """The archived `AgentCall` for `call_id`, or `None` if its file does not exist or cannot be
    parsed. Mirrors `RunStore.load`'s own "not found is a valid answer for a direct lookup" contract
    -- logged as a warning when the file exists but fails to parse, silent when it is simply absent
    (an id from an old run whose archive was pruned is not a bug worth a log line)."""
    path = agent_calls_dir(settings) / f"{call_id}.json"
    if not path.is_file():
        return None
    try:
        return AgentCall.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("agentdesk telemetry: could not read call %r: %s", call_id, exc)
        return None


def summarize_calls(call_ids: Sequence[str], *, settings: Settings) -> CallCostSummary:
    """Sum tokens and cost over every call in `call_ids` that can still be read.

    Tolerates missing or unreadable call files -- see `load_call` and the module docstring -- by
    skipping them rather than raising, so one pruned or corrupt archive entry costs the summary
    exactly one call's worth of undercount, never the whole report.
    """
    call_count = 0
    input_tokens = 0
    output_tokens = 0
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0
    cost_usd = Decimal(0)

    for call_id in call_ids:
        call = load_call(call_id, settings=settings)
        if call is None:
            continue
        call_count += 1
        input_tokens += call.input_tokens
        output_tokens += call.output_tokens
        cache_read_input_tokens += call.cache_read_input_tokens
        cache_creation_input_tokens += call.cache_creation_input_tokens
        cost_usd += call.cost_usd

    return CallCostSummary(
        call_count=call_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cost_usd=cost_usd,
    )
