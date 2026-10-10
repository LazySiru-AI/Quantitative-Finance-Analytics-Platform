"""The persona-note notification hook in `backend/app/personas/store.py`.

`VaultStore.write_note` is the one door every note goes through, and notes are immutable, so the
properties worth pinning are: one event per note, `fyi` severity (a backfill writes dozens at a time),
nothing emitted when the write is refused, and a note still written when notify is broken.
"""

from __future__ import annotations

import datetime as dt

import pytest

import app.notify as notify_pkg
from app.config import Settings
from app.notify import events as notify_events
from app.personas.models import EpisodicNote
from app.personas.store import VaultStore

_UTC = dt.UTC


def _note(
    *,
    note_id: str = "abc123",
    persona: str = "creator-a",
    title: str | None = "September Market Headwinds",
) -> EpisodicNote:
    return EpisodicNote(
        note_id=note_id,
        persona=persona,
        source_id="yt:UCaaaaaaaaaaaaaaaaaaaaaa",
        published=dt.datetime(2026, 9, 1, tzinfo=_UTC),
        ingested_at=dt.datetime(2026, 9, 1, 23, 40, tzinfo=_UTC),
        url=f"https://www.youtube.com/watch?v={note_id}",
        title=title,
        kind="video_transcript",
        transcript_source="auto",
        lang="en",
        summary="The influencer discussed NVDA earnings.",
        path="placeholder",
    )


class TestEmit:
    def test_writing_a_note_emits_one_fyi_event(self, settings: Settings) -> None:
        VaultStore(settings).write_note(_note())
        emitted = notify_events.list_since(settings)
        assert len(emitted) == 1
        event = emitted[0]
        assert event.kind == "persona.note"
        assert event.severity == "fyi"
        assert event.headline == "New note for creator-a: September Market Headwinds"
        assert event.detail == "The influencer discussed NVDA earnings."
        assert event.refs == ("persona:creator-a",)
        assert event.source == "personas.store"
        assert event.id == "persona.note:creator-a:abc123"

    def test_an_untitled_note_falls_back_to_its_url(self, settings: Settings) -> None:
        VaultStore(settings).write_note(_note(title=None))
        assert notify_events.list_since(settings)[0].headline == (
            "New note for creator-a: https://www.youtube.com/watch?v=abc123"
        )

    def test_a_refused_duplicate_write_emits_nothing_further(self, settings: Settings) -> None:
        store = VaultStore(settings)
        store.write_note(_note())
        with pytest.raises(ValueError):
            store.write_note(_note())
        assert len(notify_events.list_since(settings)) == 1

    def test_each_note_of_a_backfill_gets_its_own_event(self, settings: Settings) -> None:
        store = VaultStore(settings)
        for index in range(3):
            store.write_note(_note(note_id=f"vid{index}"))
        assert [event.id for event in notify_events.list_since(settings)] == [
            "persona.note:creator-a:vid0",
            "persona.note:creator-a:vid1",
            "persona.note:creator-a:vid2",
        ]

    def test_the_note_is_still_written_when_emit_raises(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("notify is broken")

        monkeypatch.setattr(notify_pkg, "emit", _boom)
        store = VaultStore(settings)
        path = store.write_note(_note())

        assert path.is_file()
        assert store.load_note("creator-a", "abc123") is not None
        assert notify_events.list_since(settings) == []
