"""The two manager hooks: a snapshot announces its changes, a brief announces itself.

Neither test calls a model or collects a real snapshot. `snapshot_now`'s collaborators (`collect`,
`snapshots.save`, `changes`) are patched at their call sites in `app.manager.service`, and the brief
hook is driven with a hand-built `Brief`. What is under test is the *wiring* -- which `kind`, which
`dedupe_id`, and that a notify failure cannot take the manager down with it -- not the manager's own
behaviour, which its own suite owns.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app.config import Settings
from app.manager import pipeline, service
from app.manager.models import (
    Brief,
    ChangeItem,
    ChangeSet,
    ManagerSnapshot,
    SourceRef,
    Synthesis,
)
from app.notify import events


@pytest.fixture(autouse=True)
def _no_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.notify.sender.dispatch", lambda settings, event: False)


def _item(item_id: str, severity: str = "notable") -> ChangeItem:
    return ChangeItem(
        id=item_id,
        area="account",
        rule="cash_drift",
        severity=severity,  # type: ignore[arg-type]
        headline=f"Cash moved ({item_id})",
        detail="taxable cash 12,400 -> 11,900",
        source_refs=(SourceRef(kind="txn", id="t1", label="Txn t1"),),
    )


class TestSnapshotHook:
    @pytest.fixture
    def stubbed(self, monkeypatch: pytest.MonkeyPatch) -> list[ChangeItem]:
        """Replace `snapshot_now`'s three collaborators; `changes()` returns whatever the test puts
        in the returned list."""
        items: list[ChangeItem] = []
        snapshot = ManagerSnapshot(as_of="2026-09-10", scope="owner", generated_at="2026-09-10T12:00:00+00:00")

        monkeypatch.setattr(service, "collect", lambda settings, **kw: snapshot)
        monkeypatch.setattr(service.snapshots, "save", lambda settings, snap: None)
        monkeypatch.setattr(
            service,
            "changes",
            lambda settings, **kw: ChangeSet(
                window="yesterday", since=None, until="2026-09-10", scope="owner",
                items=tuple(items),
            ),
        )
        return items

    def test_each_change_item_becomes_one_event_keyed_on_its_own_id(
        self, settings: Settings, stubbed: list[ChangeItem]
    ) -> None:
        stubbed.extend([_item("chg-a"), _item("chg-b", severity="attention")])
        service.snapshot_now(settings)

        logged = events.list_since(settings)
        assert [event.id for event in logged] == ["chg-a", "chg-b"]
        assert all(event.kind == "manager.change" for event in logged)
        assert [event.severity for event in logged] == ["notable", "attention"]
        assert logged[0].headline == "Cash moved (chg-a)"
        assert logged[0].detail == "taxable cash 12,400 -> 11,900"
        assert logged[0].source == "manager:account:cash_drift"
        assert len(logged[0].refs) == 1

    def test_taking_the_same_snapshot_twice_announces_each_change_once(
        self, settings: Settings, stubbed: list[ChangeItem]
    ) -> None:
        # The dedupe key is the item's own id, which is exactly why a snapshot taken three times in
        # an afternoon does not notify three times.
        stubbed.append(_item("chg-a"))
        service.snapshot_now(settings)
        service.snapshot_now(settings)
        service.snapshot_now(settings)
        assert [event.id for event in events.list_since(settings)] == ["chg-a"]

    def test_no_changes_emits_nothing(
        self, settings: Settings, stubbed: list[ChangeItem]
    ) -> None:
        service.snapshot_now(settings)
        assert events.list_since(settings) == []

    def test_the_snapshot_still_returns_when_notify_raises(
        self, settings: Settings, stubbed: list[ChangeItem], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stubbed.append(_item("chg-a"))

        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("notify directory is read-only")

        monkeypatch.setattr("app.notify.emit", _boom)
        snapshot = service.snapshot_now(settings)
        assert snapshot.as_of == "2026-09-10"

    def test_the_snapshot_still_returns_when_the_change_feed_raises(
        self, settings: Settings, stubbed: list[ChangeItem], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("no prior snapshot")

        monkeypatch.setattr(service, "changes", _boom)
        assert service.snapshot_now(settings).as_of == "2026-09-10"


def _brief(*, attention: tuple[ChangeItem, ...], brief_id: str = "brf-1") -> Brief:
    return Brief(
        brief_id=brief_id,
        run_id="run-1",
        scope="owner",
        window="yesterday",
        as_of="2026-09-10",
        generated_at=dt.datetime(2026, 9, 10, 13, tzinfo=dt.UTC).isoformat(),
        attention=attention,
        changes=ChangeSet(
            window="yesterday", since=None, until="2026-09-10", scope="owner", items=attention
        ),
        synthesis=Synthesis(),
        final_md="# brief",
    )


class TestBriefHook:
    def test_one_event_per_brief_headlining_the_attention_count(
        self, settings: Settings
    ) -> None:
        pipeline._notify_brief(settings, _brief(attention=(_item("a"), _item("b"))))
        (event,) = events.list_since(settings)
        assert event.kind == "manager.brief"
        assert event.severity == "attention"
        assert event.headline == "Manager brief: 2 attention item(s)"
        assert event.id == "manager.brief:brf-1"
        assert event.source == "manager:brief"

    def test_the_detail_is_the_first_three_attention_headlines(
        self, settings: Settings
    ) -> None:
        items = tuple(_item(f"chg-{n}") for n in range(5))
        pipeline._notify_brief(settings, _brief(attention=items))
        (event,) = events.list_since(settings)
        assert event.detail == "Cash moved (chg-0) · Cash moved (chg-1) · Cash moved (chg-2)"

    def test_the_detail_respects_the_320_character_limit(self, settings: Settings) -> None:
        items = tuple(
            _item("x").model_copy(update={"id": f"c{n}", "headline": "H" * 150}) for n in range(3)
        )
        pipeline._notify_brief(settings, _brief(attention=items))
        (event,) = events.list_since(settings)
        assert len(event.detail) <= 320

    def test_a_brief_with_nothing_at_attention_still_announces_itself(
        self, settings: Settings
    ) -> None:
        pipeline._notify_brief(settings, _brief(attention=()))
        (event,) = events.list_since(settings)
        assert event.headline == "Manager brief: 0 attention item(s)"
        assert event.detail == ""

    def test_the_same_brief_is_announced_once(self, settings: Settings) -> None:
        brief = _brief(attention=(_item("a"),))
        pipeline._notify_brief(settings, brief)
        pipeline._notify_brief(settings, brief)
        assert len(events.list_since(settings)) == 1

    def test_a_notify_failure_does_not_propagate_into_the_pipeline(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("disk full")

        monkeypatch.setattr("app.notify.emit", _boom)
        pipeline._notify_brief(settings, _brief(attention=()))  # must not raise
