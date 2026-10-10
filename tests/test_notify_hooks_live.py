"""The live-decision notification hook in `backend/app/agentdesk/live_loop.py`.

`decide()` itself makes a real model call, so these drive `_notify_decision` with hand-built
`LiveDecisionRecord`s -- which is where every filter that matters lives. The one thing that cannot be
asserted here is that `decide` calls it; that wiring is a single line immediately after `_append`, and
`TestWiring` pins its position rather than paying for a mocked agent stack to re-derive it.
"""

from __future__ import annotations

import datetime as dt
import inspect

import pytest

import app.notify as notify_pkg
from app.agentdesk import live_loop
from app.agentdesk.live_loop import LiveDecisionRecord
from app.config import Settings
from app.notify import events as notify_events

_DECIDED_AT = dt.datetime(2026, 9, 10, 14, 30, tzinfo=dt.UTC)


def _record(
    *,
    stance: str = "buy",
    degraded: bool = False,
    price: str | None = "123.45",
    symbol: str = "NVDA",
    rationale: str = "Volume is running ahead of the 20-day average.",
) -> LiveDecisionRecord:
    return LiveDecisionRecord(
        decided_at=_DECIDED_AT,
        symbol=symbol,
        stance=stance,
        confidence=0.7,
        rationale=rationale,
        horizon="days",
        price=price,
        grounded=not degraded,
        degraded=degraded,
    )


class TestActionableStances:
    def test_a_buy_emits_one_attention_event(self, settings: Settings) -> None:
        live_loop._notify_decision(_record(), settings=settings, source="manual")
        emitted = notify_events.list_since(settings)
        assert len(emitted) == 1
        event = emitted[0]
        assert event.kind == "signal.live"
        assert event.severity == "attention"
        assert event.headline == "Live signal: BUY NVDA @ 123.45"
        assert event.detail == "Volume is running ahead of the 20-day average."
        assert event.refs == ("symbol:NVDA",)
        assert event.source == "live_loop:manual"
        assert event.id == f"signal.live:NVDA:{_DECIDED_AT.isoformat()}"

    def test_a_sell_emits_too_and_the_daemon_source_is_carried(self, settings: Settings) -> None:
        live_loop._notify_decision(_record(stance="sell"), settings=settings, source="daemon")
        event = notify_events.list_since(settings)[0]
        assert event.headline == "Live signal: SELL NVDA @ 123.45"
        assert event.source == "live_loop:daemon"

    def test_a_decision_with_no_quote_says_so_rather_than_printing_none(
        self, settings: Settings
    ) -> None:
        live_loop._notify_decision(_record(price=None), settings=settings, source="manual")
        assert notify_events.list_since(settings)[0].headline == "Live signal: BUY NVDA @ no quote"

    def test_a_long_rationale_is_clipped_to_the_detail_budget(self, settings: Settings) -> None:
        live_loop._notify_decision(
            _record(rationale="x" * 500), settings=settings, source="manual"
        )
        assert len(notify_events.list_since(settings)[0].detail) == 300


class TestSilentCases:
    @pytest.mark.parametrize("stance", ["hold", "no_action"])
    def test_hold_and_no_action_never_notify(self, settings: Settings, stance: str) -> None:
        live_loop._notify_decision(_record(stance=stance), settings=settings, source="daemon")
        assert notify_events.list_since(settings) == []

    def test_a_degraded_buy_never_notifies(self, settings: Settings) -> None:
        live_loop._notify_decision(
            _record(stance="buy", degraded=True), settings=settings, source="manual"
        )
        assert notify_events.list_since(settings) == []

    def test_a_broken_emit_is_swallowed(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("notify is broken")

        monkeypatch.setattr(notify_pkg, "emit", _boom)
        live_loop._notify_decision(_record(), settings=settings, source="manual")
        assert notify_events.list_since(settings) == []


class TestWiring:
    def test_decide_notifies_after_it_has_filed_the_record(self) -> None:
        source = inspect.getsource(live_loop.decide)
        append_at = source.index("_append(record, settings=settings)")
        notify_at = source.index("_notify_decision(record, settings=settings")
        assert append_at < notify_at
