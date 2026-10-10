"""Unit tests for `app.agentdesk.live_loop` -- the opt-in daemon that records grounded model
*decisions* on a live tape and never trades.

No test here makes a real model call or a real HTTP request. `run_grounded` is monkeypatched to a fake
returning a scripted `GroundedResult[LiveDecision]`, `app.agentdesk.evidence.build_pack` is
monkeypatched away from the real providers, and `app.market.livefeed` is monkeypatched at the two
functions this module calls (`snapshot`, `latest_with_snapshot`) -- mirroring
`tests/test_tradingagents.py`'s own convention for the sibling desks.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

from app.agentdesk import evidence, live_loop
from app.agentdesk.grounding import GroundedResult
from app.agentdesk.models import EvidencePack, GroundingVerdict
from app.agents.models import AgentBudget, AgentCall, AgentUnavailable, BudgetExhausted
from app.agents.spend import LEDGER, SpendCapExceeded
from app.config import Settings

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "data_dir": tmp_path / "data",
        "live_decisions_cap_usd": Decimal("1.00"),
        "model_spend_daily_cap_usd": Decimal("25"),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concrete proof this file never falls through to a real request. Patched at
    `httpx.HTTPTransport` rather than at the socket layer for the reason
    `tests/test_market_refresh.py` documents: blocking `socket.connect` breaks `asyncio`'s own
    self-pipe on Windows, which has nothing to do with the network."""
    import httpx

    def _blocked(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"test_agentdesk_live_loop.py attempted a real HTTP request: {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)


@pytest.fixture(autouse=True)
def _no_real_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test in this module may reach the real market-data/news providers."""
    monkeypatch.setattr(
        evidence,
        "build_pack",
        lambda symbol, as_of, *, settings, sections: EvidencePack(symbol=symbol, sections=()),
    )


@pytest.fixture(autouse=True)
def _clean_module_state() -> Iterator[None]:
    """Module counters do not leak between tests -- one test's tick must not be another's history."""
    live_loop.reset()
    LEDGER.reset()
    yield
    live_loop.reset()
    LEDGER.reset()


@dataclass
class _FakeQuote:
    symbol: str
    price: Decimal
    ts: dt.datetime


@dataclass
class _FakeSnapshot:
    market_state: str


def _fake_quote(symbol: str = "AAPL", price: str = "191.25") -> _FakeQuote:
    return _FakeQuote(symbol=symbol, price=Decimal(price), ts=dt.datetime(2026, 9, 8, 18, 5, tzinfo=dt.UTC))


def _stub_livefeed(
    monkeypatch: pytest.MonkeyPatch, *, market_state: str = "REGULAR", quote: object | None = None
) -> None:
    snap = _FakeSnapshot(market_state=market_state)
    monkeypatch.setattr(live_loop.livefeed, "snapshot", lambda symbols: snap)
    monkeypatch.setattr(
        live_loop.livefeed,
        "latest_with_snapshot",
        lambda symbol: (quote if quote is not None else _fake_quote(symbol), snap),
    )


def _fake_call(call_id: str = "call-1", cost: str = "0.01") -> AgentCall:
    return AgentCall(
        call_id=call_id,
        role="trader",
        model="claude-haiku-4-5-20251001",
        created_at=dt.datetime.now(dt.UTC),
        system="s",
        user="u",
        raw_response="r",
        cost_usd=Decimal(cost),
    )


def _fake_run_grounded(
    *, stance: str = "hold", degraded: bool = False, cost: str = "0.01", raises: Exception | None = None
):
    calls: list[str] = []

    def fake(*, role, system, user, output_format, prose_of, pack, settings, budget, model, **kwargs):
        calls.append(role)
        if raises is not None:
            raise raises
        value = output_format(
            stance=stance, confidence=0.4, rationale="the evidence is thin", horizon="intraday"
        )
        verdict = GroundingVerdict(ok=not degraded, degraded=degraded, attempts=1)
        new_budget = AgentBudget(
            cap_usd=budget.cap_usd, spent_usd=budget.spent_usd + Decimal(cost), calls=budget.calls + 1
        )
        return GroundedResult(
            value=value, verdict=verdict, calls=(_fake_call(cost=cost),), budget=new_budget
        )

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


def _decisions_file(settings: Settings, day: dt.date | None = None) -> Path:
    day = day or dt.datetime.now(dt.UTC).date()
    return settings.data_dir / "agentdesk" / "live_decisions" / f"{day.isoformat()}.jsonl"


# ---------------------------------------------------------------------------
# decide
# ---------------------------------------------------------------------------


class TestDecide:
    def test_decide_persists_a_record_and_reports_the_live_quote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path)
        _stub_livefeed(monkeypatch)
        monkeypatch.setattr(live_loop, "run_grounded", _fake_run_grounded(stance="buy"))

        record = live_loop.decide("aapl", settings=settings)

        assert record.symbol == "AAPL"
        assert record.stance == "buy"
        assert record.horizon == "intraday"
        assert record.price == "191.25"
        assert record.market_state == "REGULAR"
        assert record.grounded is True
        assert record.degraded is False
        assert record.source == "manual"
        assert record.cost_usd == "0.01"
        assert record.call_ids == ("call-1",)

        path = _decisions_file(settings)
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["symbol"] == "AAPL"

    def test_decide_rejects_a_non_symbol(self, tmp_path: Path) -> None:
        with pytest.raises(live_loop.InvalidSymbol):
            live_loop.decide("not a ticker!", settings=_settings(tmp_path))

    def test_decide_records_a_degraded_verdict_without_raising(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path)
        _stub_livefeed(monkeypatch)
        monkeypatch.setattr(live_loop, "run_grounded", _fake_run_grounded(degraded=True))

        record = live_loop.decide("AAPL", settings=settings)
        assert record.grounded is False
        assert record.degraded is True

    def test_decide_is_none_safe_when_no_quote_is_available(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path)
        monkeypatch.setattr(live_loop.livefeed, "latest_with_snapshot", lambda symbol: (None, None))
        monkeypatch.setattr(live_loop, "run_grounded", _fake_run_grounded(stance="no_action"))

        record = live_loop.decide("AAPL", settings=settings)
        assert record.price is None
        assert record.quoted_at is None
        assert record.market_state is None

    def test_decide_checks_the_rolling_daily_spend_cap_before_calling(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, model_spend_daily_cap_usd=Decimal("1"))
        _stub_livefeed(monkeypatch)
        fake = _fake_run_grounded()
        monkeypatch.setattr(live_loop, "run_grounded", fake)
        LEDGER.record(Decimal("5"))

        with pytest.raises(SpendCapExceeded):
            live_loop.decide("AAPL", settings=settings)
        assert fake.calls == []  # checked *before* the model call, never after


# ---------------------------------------------------------------------------
# run_once
# ---------------------------------------------------------------------------


class TestRunOnce:
    def test_no_watchlist_skips_without_calling_the_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path)
        monkeypatch.setattr(live_loop, "_resolve_symbols", lambda settings: ())
        fake = _fake_run_grounded()
        monkeypatch.setattr(live_loop, "run_grounded", fake)

        summary = live_loop.run_once(settings)
        assert summary.skipped_reason == "no_symbols"
        assert summary.decided == 0
        assert fake.calls == []

    def test_a_closed_market_skips_without_calling_the_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, live_decisions_symbols="AAPL,MSFT")
        _stub_livefeed(monkeypatch, market_state="CLOSED")
        fake = _fake_run_grounded()
        monkeypatch.setattr(live_loop, "run_grounded", fake)

        summary = live_loop.run_once(settings)
        assert summary.skipped_reason == "market_closed"
        assert summary.market_state == "CLOSED"
        assert summary.symbols == ("AAPL", "MSFT")
        assert fake.calls == []

    def test_an_unreachable_feed_skips_rather_than_spending(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, live_decisions_symbols="AAPL")

        def _boom(symbols: object) -> object:
            raise RuntimeError("feed down")

        monkeypatch.setattr(live_loop.livefeed, "snapshot", _boom)
        fake = _fake_run_grounded()
        monkeypatch.setattr(live_loop, "run_grounded", fake)

        summary = live_loop.run_once(settings)
        assert summary.skipped_reason == "market_closed"
        assert summary.market_state is None
        assert fake.calls == []

    def test_a_regular_session_decides_every_symbol_and_persists_jsonl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, live_decisions_symbols="AAPL,MSFT")
        _stub_livefeed(monkeypatch)
        monkeypatch.setattr(live_loop, "run_grounded", _fake_run_grounded())

        summary = live_loop.run_once(settings)
        assert summary.skipped_reason is None
        assert summary.decided == 2
        assert summary.failures == 0
        assert summary.market_state == "REGULAR"

        lines = _decisions_file(settings).read_text(encoding="utf-8").strip().splitlines()
        assert [json.loads(line)["symbol"] for line in lines] == ["AAPL", "MSFT"]
        assert all(json.loads(line)["source"] == "daemon" for line in lines)

    def test_budget_exhaustion_stops_the_tick_partway(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A $0.02 per-tick cap against $0.01 calls: two symbols decide, the third finds the budget
        # already exhausted and the tick stops rather than walking the rest of the watchlist.
        settings = _settings(
            tmp_path, live_decisions_symbols="AAPL,MSFT,NVDA,TSLA", live_decisions_cap_usd=Decimal("0.02")
        )
        _stub_livefeed(monkeypatch)
        monkeypatch.setattr(live_loop, "run_grounded", _fake_run_grounded())

        summary = live_loop.run_once(settings)
        assert summary.decided == 2
        assert summary.skipped_reason == "spend_cap"

    def test_a_raised_budget_exhausted_stops_the_tick(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, live_decisions_symbols="AAPL,MSFT")
        _stub_livefeed(monkeypatch)
        monkeypatch.setattr(
            live_loop,
            "run_grounded",
            _fake_run_grounded(raises=BudgetExhausted(Decimal("1"), Decimal("1"))),
        )

        summary = live_loop.run_once(settings)
        assert summary.decided == 0
        assert summary.skipped_reason == "spend_cap"
        assert summary.failures == 0  # a cap is not a fault

    def test_a_failing_symbol_is_counted_and_the_tick_continues(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, live_decisions_symbols="AAPL,MSFT")
        _stub_livefeed(monkeypatch)
        monkeypatch.setattr(
            live_loop, "run_grounded", _fake_run_grounded(raises=AgentUnavailable("no credential"))
        )

        summary = live_loop.run_once(settings)
        assert summary.decided == 0
        assert summary.failures == 2
        assert summary.skipped_reason is None  # every symbol was attempted

    def test_run_once_never_raises_on_an_unexpected_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, live_decisions_symbols="AAPL")
        _stub_livefeed(monkeypatch)
        monkeypatch.setattr(live_loop, "run_grounded", _fake_run_grounded(raises=RuntimeError("boom")))

        summary = live_loop.run_once(settings)
        assert summary.failures == 1


# ---------------------------------------------------------------------------
# _resolve_symbols
# ---------------------------------------------------------------------------


class TestResolveSymbols:
    def test_an_explicit_list_wins_and_is_normalised(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path, live_decisions_symbols=" aapl , msft ,aapl, ")
        assert live_loop._resolve_symbols(settings) == ("AAPL", "MSFT")

    def test_an_empty_list_falls_back_to_held_symbols_capped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.market import refresh

        monkeypatch.setattr(refresh, "_held_symbols", lambda cfg: ["A", "B", "C", "D"])
        settings = _settings(tmp_path, live_decisions_max_symbols=2)
        assert live_loop._resolve_symbols(settings) == ("A", "B")


# ---------------------------------------------------------------------------
# health / status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_answers_with_exactly_the_twelve_pinned_keys(self, tmp_path: Path) -> None:
        live_loop.start(_settings(tmp_path))  # disabled: records the settings, starts nothing
        payload = live_loop.status()
        assert set(payload) == {
            "enabled",
            "running",
            "healthy",
            "market_state",
            "last_tick_at",
            "next_wake_at",
            "ticks",
            "decisions_today",
            "consecutive_failures",
            "symbols",
            "interval_minutes",
            "cap_usd",
        }
        assert payload["enabled"] is False
        assert payload["running"] is False
        assert payload["healthy"] is None  # no tick yet is neither healthy nor unhealthy
        assert payload["ticks"] == 0
        assert payload["decisions_today"] == 0
        assert payload["cap_usd"] == "1.00"
        assert payload["interval_minutes"] == 30.0

    def test_consecutive_failing_ticks_flip_healthy_to_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, live_decisions_symbols="AAPL")
        live_loop.start(settings)  # disabled; only records the settings status() reads
        _stub_livefeed(monkeypatch)
        monkeypatch.setattr(live_loop, "run_grounded", _fake_run_grounded(raises=RuntimeError("boom")))

        live_loop.run_once(settings)
        assert live_loop.status()["healthy"] is True  # one bad tick is not an outage

        for _ in range(live_loop._MAX_CONSECUTIVE_FAILURES - 1):
            live_loop.run_once(settings)

        payload = live_loop.status()
        assert payload["healthy"] is False
        assert payload["consecutive_failures"] == live_loop._MAX_CONSECUTIVE_FAILURES
        assert payload["ticks"] == live_loop._MAX_CONSECUTIVE_FAILURES

    def test_a_successful_tick_clears_the_streak(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, live_decisions_symbols="AAPL")
        live_loop.start(settings)
        _stub_livefeed(monkeypatch)
        monkeypatch.setattr(live_loop, "run_grounded", _fake_run_grounded(raises=RuntimeError("boom")))
        live_loop.run_once(settings)
        monkeypatch.setattr(live_loop, "run_grounded", _fake_run_grounded())
        live_loop.run_once(settings)

        payload = live_loop.status()
        assert payload["consecutive_failures"] == 0
        assert payload["healthy"] is True
        assert payload["decisions_today"] == 1
        assert payload["market_state"] == "REGULAR"


# ---------------------------------------------------------------------------
# start / stop
# ---------------------------------------------------------------------------


class TestStartStop:
    def test_start_is_a_no_op_when_the_flag_is_off(self, tmp_path: Path) -> None:
        live_loop.start(_settings(tmp_path))
        assert live_loop.status()["running"] is False
        live_loop.stop()  # safe with nothing running

    def test_start_launches_a_daemon_thread_when_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, live_decisions_enabled=True, live_decisions_symbols="AAPL")
        # The thread must never reach the model: the first thing it does is tick, so the tick is
        # stubbed to a skip before the daemon is ever started.
        monkeypatch.setattr(live_loop, "_resolve_symbols", lambda settings: ())
        live_loop.start(settings)
        try:
            assert live_loop.status()["running"] is True
            assert live_loop.status()["enabled"] is True
        finally:
            live_loop.stop(timeout=5.0)
        assert live_loop.status()["running"] is False

    def test_the_interval_setting_refuses_a_sub_minute_cadence(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            _settings(tmp_path, live_decisions_interval_minutes=0.1)


# ---------------------------------------------------------------------------
# list_decisions
# ---------------------------------------------------------------------------


class TestListDecisions:
    def _write(self, settings: Settings, *records: live_loop.LiveDecisionRecord) -> None:
        for record in records:
            live_loop._append(record, settings=settings)

    def _record(self, symbol: str, minutes_ago: int) -> live_loop.LiveDecisionRecord:
        return live_loop.LiveDecisionRecord(
            decided_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=minutes_ago),
            symbol=symbol,
            stance="hold",
            confidence=0.5,
            rationale="r",
            horizon="days",
        )

    def test_empty_when_nothing_was_ever_decided(self, tmp_path: Path) -> None:
        assert live_loop.list_decisions(_settings(tmp_path)) == []

    def test_newest_first_filtered_and_limited(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        self._write(
            settings,
            self._record("AAPL", 30),
            self._record("MSFT", 20),
            self._record("AAPL", 10),
        )

        everything = live_loop.list_decisions(settings)
        assert [r.symbol for r in everything] == ["AAPL", "MSFT", "AAPL"]
        assert everything[0].decided_at > everything[1].decided_at

        only_aapl = live_loop.list_decisions(settings, symbol="aapl")
        assert [r.symbol for r in only_aapl] == ["AAPL", "AAPL"]

        assert len(live_loop.list_decisions(settings, limit=1)) == 1

    def test_an_unreadable_line_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        self._write(settings, self._record("AAPL", 5))
        path = _decisions_file(settings)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("{not json\n")

        assert [r.symbol for r in live_loop.list_decisions(settings)] == ["AAPL"]

    def test_yesterdays_file_is_included(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        yesterday = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
        record = live_loop.LiveDecisionRecord(
            decided_at=yesterday, symbol="NVDA", stance="buy", confidence=0.7, rationale="r", horizon="days"
        )
        live_loop._append(record, settings=settings)
        assert [r.symbol for r in live_loop.list_decisions(settings)] == ["NVDA"]
