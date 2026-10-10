"""Tests for the `http(s)`-or-empty url guard on `app.personas.models`' three `url` fields:
`FollowedSource.url`, `EpisodicNote.url`, `TimelineEntry.url`.

The empty string is a deliberate, pre-existing sentinel on these fields -- see
`app.personas.models._require_http_url`'s own docstring -- for a manually-followed source with no
channel link (`app.personas.service._resolve_source`) and a manual drop with text but no url
(`app.personas.service._plan_items`). The guard must reject an unsafe scheme without also rejecting
that legitimate absence.
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from app.personas.models import EpisodicNote, FollowedSource, TimelineEntry

_NOW = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)

_BAD_URLS = ["javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "not-a-url-at-all"]


class TestFollowedSourceUrl:
    def test_javascript_and_data_urls_are_rejected(self) -> None:
        for bad in _BAD_URLS:
            with pytest.raises(ValidationError):
                FollowedSource(
                    source_id="yt:UCabc", platform="youtube", handle="h",
                    channel_id="UCabc", url=bad, added_at=_NOW,
                )

    def test_an_https_url_is_accepted(self) -> None:
        source = FollowedSource(
            source_id="yt:UCabc", platform="youtube", handle="h",
            channel_id="UCabc", url="https://www.youtube.com/channel/UCabc", added_at=_NOW,
        )
        assert source.url == "https://www.youtube.com/channel/UCabc"

    def test_empty_url_is_accepted_the_manual_source_sentinel(self) -> None:
        """`app.personas.service._resolve_source` constructs a manual source with `url=""` -- there
        is no channel link for a manually-added source, the same way `channel_id` is `None` there.
        The guard must not turn that pre-existing, legitimate state into a validation failure."""
        source = FollowedSource(
            source_id="manual:abc123", platform="manual", handle="h",
            channel_id=None, url="", added_at=_NOW,
        )
        assert source.url == ""


def _note_kwargs(url: str) -> dict[str, object]:
    """Kwargs for a minimal `EpisodicNote`, so each test only overrides `url`."""
    return dict(
        note_id="abc123",
        persona="creator-a",
        source_id="yt:UCabc",
        published=_NOW,
        ingested_at=_NOW,
        url=url,
        title="t",
        kind="video_transcript",
        transcript_source="auto",
        lang="en",
        summary="s",
        path="placeholder",
    )


class TestEpisodicNoteUrl:
    def test_javascript_and_data_urls_are_rejected(self) -> None:
        for bad in _BAD_URLS:
            with pytest.raises(ValidationError):
                EpisodicNote(**_note_kwargs(bad))

    def test_an_https_url_is_accepted(self) -> None:
        note = EpisodicNote(**_note_kwargs("https://www.youtube.com/watch?v=abc123"))
        assert note.url == "https://www.youtube.com/watch?v=abc123"

    def test_empty_url_is_accepted_the_manual_drop_sentinel(self) -> None:
        """`app.personas.service._plan_items` builds a manual-drop note with `url=""` when the owner
        pastes text with no source link -- a drop needs *either* text or a url, not both."""
        note = EpisodicNote(**_note_kwargs(""))
        assert note.url == ""


class TestTimelineEntryUrl:
    def test_javascript_url_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TimelineEntry(note_id="n1", published=_NOW, title="t", summary="s", url=_BAD_URLS[0])

    def test_an_https_url_is_accepted(self) -> None:
        entry = TimelineEntry(
            note_id="n1", published=_NOW, title="t", summary="s", url="https://example.com/a"
        )
        assert entry.url == "https://example.com/a"

    def test_empty_url_is_accepted_relaying_a_manual_drop_note(self) -> None:
        entry = TimelineEntry(note_id="n1", published=_NOW, title="t", summary="s", url="")
        assert entry.url == ""
