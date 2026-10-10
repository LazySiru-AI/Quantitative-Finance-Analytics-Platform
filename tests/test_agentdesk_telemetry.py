"""Tests for `backend/app/agentdesk/telemetry.py` -- `load_call`/`summarize_calls`, the primitive
every desk- and workflow-level telemetry report is built from.

Every `AgentCall` this file needs is written directly to `agent_calls_dir(settings)` as JSON, the
same convention `tests/test_agents_cli_transport.py` and `tests/test_agents_designer.py` use --
never through a real model call.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.agentdesk.telemetry import CallCostSummary, load_call, summarize_calls
from app.agents.models import AgentCall, agent_calls_dir
from app.config import Settings


def _write_call(
    settings: Settings,
    *,
    call_id: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    cost_usd: str = "0",
) -> AgentCall:
    call = AgentCall(
        call_id=call_id,
        role="market_analyst",
        model="claude-opus-5",
        created_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
        system="sys",
        user="user",
        raw_response="response",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cost_usd=Decimal(cost_usd),
    )
    directory = agent_calls_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{call_id}.json").write_text(call.model_dump_json(indent=2), encoding="utf-8")
    return call


# ---------------------------------------------------------------------------
# load_call
# ---------------------------------------------------------------------------


class TestLoadCall:
    def test_returns_the_archived_call(self, settings: Settings) -> None:
        written = _write_call(settings, call_id="call-1", input_tokens=10, cost_usd="0.05")
        loaded = load_call("call-1", settings=settings)
        assert loaded == written

    def test_returns_none_for_a_call_id_with_no_archive_file(self, settings: Settings) -> None:
        assert load_call("never-written", settings=settings) is None

    def test_returns_none_and_does_not_raise_for_a_corrupt_archive_file(self, settings: Settings) -> None:
        directory = agent_calls_dir(settings)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "corrupt.json").write_text("{not valid json", encoding="utf-8")
        assert load_call("corrupt", settings=settings) is None


# ---------------------------------------------------------------------------
# summarize_calls
# ---------------------------------------------------------------------------


class TestSummarizeCalls:
    def test_sums_tokens_and_cost_across_multiple_calls(self, settings: Settings) -> None:
        _write_call(
            settings, call_id="c1", input_tokens=100, output_tokens=50,
            cache_read_input_tokens=10, cache_creation_input_tokens=5, cost_usd="0.10",
        )
        _write_call(
            settings, call_id="c2", input_tokens=200, output_tokens=75,
            cache_read_input_tokens=20, cache_creation_input_tokens=15, cost_usd="0.25",
        )
        result = summarize_calls(["c1", "c2"], settings=settings)
        assert result == CallCostSummary(
            call_count=2,
            input_tokens=300,
            output_tokens=125,
            cache_read_input_tokens=30,
            cache_creation_input_tokens=20,
            cost_usd=Decimal("0.35"),
        )

    def test_empty_call_id_list_summarizes_to_all_zero(self, settings: Settings) -> None:
        result = summarize_calls([], settings=settings)
        assert result == CallCostSummary(
            call_count=0, input_tokens=0, output_tokens=0,
            cache_read_input_tokens=0, cache_creation_input_tokens=0, cost_usd=Decimal(0),
        )

    def test_a_missing_call_file_is_skipped_not_raised(self, settings: Settings) -> None:
        """The pinned contract: `summarize_calls` must tolerate missing/unreadable call files."""
        _write_call(settings, call_id="real-1", input_tokens=100, cost_usd="0.10")
        # "ghost-call" was never written -- e.g. its archive was pruned, or the id came from a stage
        # whose call never actually completed.
        result = summarize_calls(["real-1", "ghost-call"], settings=settings)
        assert result.call_count == 1
        assert result.input_tokens == 100
        assert result.cost_usd == Decimal("0.10")

    def test_a_corrupt_call_file_is_skipped_not_raised(self, settings: Settings) -> None:
        _write_call(settings, call_id="real-2", input_tokens=50, cost_usd="0.02")
        directory = agent_calls_dir(settings)
        (directory / "corrupt-2.json").write_text("not json at all", encoding="utf-8")
        result = summarize_calls(["real-2", "corrupt-2"], settings=settings)
        assert result.call_count == 1
        assert result.input_tokens == 50

    def test_all_calls_missing_summarizes_to_zero_not_an_error(self, settings: Settings) -> None:
        result = summarize_calls(["ghost-a", "ghost-b"], settings=settings)
        assert result.call_count == 0
        assert result.cost_usd == Decimal(0)
