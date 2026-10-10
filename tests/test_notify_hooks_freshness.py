"""The `fresh`/`live` -> `stale` notification hook in `backend/app/market/freshness.py`.

`report()` is called on every load of Data > Health, so the property under test is not "a stale source
produces an event" but "a stale source produces an event *once*, on the transition". These tests drive
the real `report()` where they can and `_notify_flips` directly where a status has to be forced -- the
catalog measures real directories, and there is no honest way to make eleven live sources flip on cue.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

import app.notify as notify_pkg
from app.config import Settings
from app.market import freshness
from app.notify import events as notify_events


def _row(key: str, status: str, *, detail: str = "", policy: str = "daily") -> freshness.SourceFreshness:
    return freshness.SourceFreshness(
        key=key,
        freshness_class="scheduled",
        policy=policy,
        provider="test",
        last_updated=None,
        age_seconds=None,
        status=status,
        detail=detail,
        refreshable=True,
        enabled=True,
    )


_NOW = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.UTC)


class TestTransition:
    def test_fresh_to_stale_emits_once_and_stale_to_stale_does_not(self, settings: Settings) -> None:
        freshness._notify_flips(settings, [_row("bars_daily", "fresh")], as_of=_NOW)
        assert notify_events.list_since(settings) == []

        freshness._notify_flips(
            settings, [_row("bars_daily", "stale", detail="4 days behind")], as_of=_NOW
        )
        emitted = notify_events.list_since(settings)
        assert len(emitted) == 1
        event = emitted[0]
        assert event.kind == "data.stale"
        assert event.severity == "notable"
        assert event.headline == "Data stale: bars_daily"
        assert event.detail == "4 days behind"
        assert event.refs == ("data:bars_daily",)
        assert event.source == "market.freshness"
        assert event.id == "data.stale:bars_daily:2026-09-10"

        # Still stale on the next report: the edge already fired, and this must stay quiet.
        freshness._notify_flips(settings, [_row("bars_daily", "stale")], as_of=_NOW)
        assert len(notify_events.list_since(settings)) == 1

    def test_live_counts_as_a_healthy_previous_status(self, settings: Settings) -> None:
        freshness._notify_flips(settings, [_row("live_quotes", "live")], as_of=_NOW)
        freshness._notify_flips(settings, [_row("live_quotes", "stale")], as_of=_NOW)
        assert [event.headline for event in notify_events.list_since(settings)] == [
            "Data stale: live_quotes"
        ]

    def test_unknown_and_disabled_are_not_a_healthy_previous_status(
        self, settings: Settings
    ) -> None:
        freshness._notify_flips(
            settings, [_row("a", "unknown"), _row("b", "disabled")], as_of=_NOW
        )
        freshness._notify_flips(settings, [_row("a", "stale"), _row("b", "stale")], as_of=_NOW)
        assert notify_events.list_since(settings) == []

    def test_first_ever_report_baselines_without_announcing(self, settings: Settings) -> None:
        """Everything already stale on a fresh install has not *just* broken."""
        freshness._notify_flips(settings, [_row("bars_daily", "stale")], as_of=_NOW)
        assert notify_events.list_since(settings) == []
        recorded = json.loads(
            freshness._last_status_path(settings).read_text(encoding="utf-8")
        )
        assert recorded == {"bars_daily": "stale"}

    def test_dedupe_key_bounds_a_flapping_source_to_one_event_a_day(
        self, settings: Settings
    ) -> None:
        for status in ("fresh", "stale", "fresh", "stale"):
            freshness._notify_flips(settings, [_row("bars_daily", status)], as_of=_NOW)
        assert len(notify_events.list_since(settings)) == 1


class TestReportIsUnaffected:
    def test_report_returns_its_normal_shape_and_writes_the_last_status_file(
        self, settings: Settings
    ) -> None:
        body = freshness.report(settings)
        assert set(body) == {"as_of", "sources", "refresh", "live"}
        keys = [row["key"] for row in body["sources"]]
        recorded = json.loads(
            freshness._last_status_path(settings).read_text(encoding="utf-8")
        )
        assert sorted(recorded) == sorted(keys)

    def test_report_still_answers_when_emit_raises(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("notify is broken")

        # `app.notify.emit`, not `app.notify.events.emit`: every hook calls the re-export, which is a
        # separate binding made at import time -- patching the defining module would not reach it.
        monkeypatch.setattr(notify_pkg, "emit", _boom)
        freshness._notify_flips(settings, [_row("bars_daily", "fresh")], as_of=_NOW)
        body = freshness.report(settings)
        assert body["sources"]
