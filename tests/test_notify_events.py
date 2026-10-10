"""The append-only event log: emit, dedupe, and the two forms of the `since` cursor.

Delivery is not exercised here at all -- `sender.dispatch` is monkeypatched to a no-op recorder in
every test, so a policy change can never make a log test go red. `tests/test_notify_sender.py` owns
the other half.
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.notify import events


@pytest.fixture(autouse=True)
def _no_delivery(monkeypatch: pytest.MonkeyPatch) -> list[events.NotifyEvent]:
    """Replace the sender with a recorder. Returned as a list so a test that wants to assert *that*
    dispatch was offered an event (not what happened to it) can request the fixture by name."""
    seen: list[events.NotifyEvent] = []

    def _fake(settings: Settings, event: events.NotifyEvent) -> bool:
        seen.append(event)
        return False

    monkeypatch.setattr("app.notify.sender.dispatch", _fake)
    return seen


def _emit(
    settings: Settings,
    headline: str,
    *,
    kind: str = "manager.change",
    severity: events.Severity = "notable",
    detail: str = "",
    refs: tuple[str, ...] = (),
    source: str = "",
    dedupe_id: str | None = None,
) -> events.NotifyEvent | None:
    return events.emit(
        settings,
        kind=kind,
        severity=severity,
        headline=headline,
        detail=detail,
        refs=refs,
        source=source,
        dedupe_id=dedupe_id,
    )


class TestEmit:
    def test_writes_one_jsonl_line_with_the_pinned_fields(self, settings: Settings) -> None:
        event = _emit(
            settings,
            "Cash fell 4%",
            detail="taxable cash 12,400 -> 11,900",
            refs=("txn:1", "txn:2"),
            source="manager:account:cash_drift",
        )
        assert event is not None

        path = settings.data_dir / "notify" / "events.jsonl"
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row == {
            "id": event.id,
            "ts": event.ts,
            "kind": "manager.change",
            "severity": "notable",
            "headline": "Cash fell 4%",
            "detail": "taxable cash 12,400 -> 11,900",
            "refs": ["txn:1", "txn:2"],
            "source": "manager:account:cash_drift",
        }

    def test_derived_id_is_stable_for_the_same_kind_and_headline_today(
        self, settings: Settings
    ) -> None:
        first = _emit(settings, "Cash fell 4%")
        assert first is not None
        # Same derivation material -> same id -> the second emit is a duplicate.
        assert _emit(settings, "Cash fell 4%") is None
        assert len(events.list_since(settings)) == 1

    def test_a_different_headline_is_a_different_event(self, settings: Settings) -> None:
        assert _emit(settings, "Cash fell 4%") is not None
        assert _emit(settings, "Cash fell 9%") is not None
        assert len(events.list_since(settings)) == 2

    def test_explicit_dedupe_id_wins_over_the_derivation(self, settings: Settings) -> None:
        first = _emit(settings, "Cash fell 4%", dedupe_id="chg-7")
        assert first is not None and first.id == "chg-7"
        # Different headline, same explicit id -> still a duplicate, which is the point of passing
        # a producer's own stable id (a re-worded ChangeItem is not a new change).
        assert _emit(settings, "Cash fell 4.2%", dedupe_id="chg-7") is None

    def test_dispatch_is_offered_every_new_event_and_never_a_duplicate(
        self, settings: Settings, _no_delivery: list[events.NotifyEvent]
    ) -> None:
        _emit(settings, "one")
        _emit(settings, "one")
        _emit(settings, "two")
        assert [event.headline for event in _no_delivery] == ["one", "two"]

    def test_a_raising_sender_does_not_break_the_producer(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(settings: Settings, event: events.NotifyEvent) -> bool:
            raise RuntimeError("channel exploded")

        monkeypatch.setattr("app.notify.sender.dispatch", _boom)
        event = _emit(settings, "still logged")
        assert event is not None
        assert [e.headline for e in events.list_since(settings)] == ["still logged"]

    def test_overlong_text_is_clipped_rather_than_rejected(self, settings: Settings) -> None:
        event = _emit(settings, "h" * 400, detail="d" * 900)
        assert event is not None
        assert len(event.headline) == 160
        assert len(event.detail) == 320

    def test_seen_set_is_a_separate_file_from_the_log(self, settings: Settings) -> None:
        _emit(settings, "Cash fell 4%", dedupe_id="chg-7")
        seen = json.loads((settings.data_dir / "notify" / "seen.json").read_text(encoding="utf-8"))
        assert "chg-7" in seen


class TestListSince:
    @pytest.fixture
    def three(self, settings: Settings) -> list[events.NotifyEvent]:
        out = [_emit(settings, f"item {n}") for n in range(3)]
        assert all(event is not None for event in out)
        return [event for event in out if event is not None]

    def test_no_cursor_returns_everything_newest_last(
        self, settings: Settings, three: list[events.NotifyEvent]
    ) -> None:
        assert [event.headline for event in events.list_since(settings)] == [
            "item 0",
            "item 1",
            "item 2",
        ]

    def test_since_an_event_id_returns_strictly_what_followed_it(
        self, settings: Settings, three: list[events.NotifyEvent]
    ) -> None:
        after = events.list_since(settings, since=three[0].id)
        assert [event.headline for event in after] == ["item 1", "item 2"]

    def test_since_the_last_id_returns_nothing(
        self, settings: Settings, three: list[events.NotifyEvent]
    ) -> None:
        assert events.list_since(settings, since=three[-1].id) == []

    def test_since_an_iso_timestamp_returns_what_came_after_it(
        self, settings: Settings, three: list[events.NotifyEvent]
    ) -> None:
        after = events.list_since(settings, since=three[1].ts)
        assert [event.headline for event in after] == ["item 2"]

    def test_since_an_unknown_id_degrades_to_everything_rather_than_erroring(
        self, settings: Settings, three: list[events.NotifyEvent]
    ) -> None:
        # A poller whose cursor has aged out must re-sync, not wedge. An unknown id is read as a
        # timestamp, and one that sorts below every ts yields the whole log.
        assert len(events.list_since(settings, since="0000-not-an-id")) == 3

    def test_limit_bounds_both_the_cursor_and_the_no_cursor_form(
        self, settings: Settings, three: list[events.NotifyEvent]
    ) -> None:
        assert [e.headline for e in events.list_since(settings, limit=2)] == ["item 1", "item 2"]
        assert [
            e.headline for e in events.list_since(settings, since=three[0].id, limit=1)
        ] == ["item 1"]

    def test_an_empty_log_is_an_empty_list_not_a_missing_file_error(
        self, settings: Settings
    ) -> None:
        assert events.list_since(settings) == []

    def test_an_unparseable_line_is_skipped_not_fatal(
        self, settings: Settings, three: list[events.NotifyEvent]
    ) -> None:
        path = settings.data_dir / "notify" / "events.jsonl"
        path.write_text(path.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
        assert len(events.list_since(settings)) == 3


class TestStatus:
    def test_reports_the_configuration_and_the_log_size(self, settings: Settings) -> None:
        event = _emit(settings, "Cash fell 4%")
        assert event is not None

        report = events.status(settings)
        assert report["enabled"] is False  # the shipped default
        assert report["channel"] == "log"
        assert report["total"] == 1
        assert report["last_event_ts"] == event.ts
        # Nothing was delivered: `_no_delivery` returns False, so the sender recorded a suppression.
        assert report["last_sent_ts"] is None
        assert report["sent_today"] == 0

    def test_is_answerable_before_anything_has_ever_happened(self, settings: Settings) -> None:
        report = events.status(settings)
        assert report["total"] == 0
        assert report["last_event_ts"] is None
        assert report["last_sent_ts"] is None
        assert report["sent_today"] == 0
        assert report["suppressed_today"] == 0
