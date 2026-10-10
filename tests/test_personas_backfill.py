"""Tests for `app.personas.backfill`: discover un-ingested videos, render task packets, write files.

Uses the `settings` fixture from `tests/conftest.py` (vault redirected into `tmp_path`) and monkeypatches
the three `app.personas.sources.youtube` functions `discover_tasks` calls, so nothing here touches the
network or a real channel. The whole module is model-free by design, so there is no agent to stub.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest

from app.config import Settings
from app.personas import backfill
from app.personas.models import EpisodicNote, FollowedSource, Persona
from app.personas.sources import youtube as youtube_mod
from app.personas.sources.base import (
    FetchedTranscript,
    SourceError,
    TranscriptUnavailable,
    VideoRef,
)
from app.personas.store import VaultStore

_UTC = dt.UTC
_NOW = dt.datetime(2026, 9, 1, tzinfo=_UTC)


def _persona_with_youtube(store: VaultStore, *, slug: str = "creator-a") -> Persona:
    persona = Persona(
        slug=slug,
        display_name="Creator A",
        sources=(
            FollowedSource(
                source_id="yt:UCabc",
                platform="youtube",
                handle=slug,
                channel_id="UCabc",
                url=f"https://www.youtube.com/@{slug}",
                added_at=_NOW,
            ),
        ),
        created_at=_NOW,
    )
    store.save_persona(persona)
    return persona


def _mark_ingested(store: VaultStore, *, slug: str, video_id: str) -> None:
    store.write_note(
        EpisodicNote(
            note_id=video_id,
            persona=slug,
            source_id="yt:UCabc",
            published=_NOW,
            ingested_at=_NOW,
            url=f"https://www.youtube.com/watch?v={video_id}",
            title="already done",
            kind="video_transcript",  # type: ignore[arg-type]
            transcript_source="auto",  # type: ignore[arg-type]
            lang="ko",
            summary="s",
            themes=(),
            quotes=(),
            mentions=(),
            path="placeholder",
            degraded=False,
        ),
        transcript_text="old transcript",
    )


def _stub_youtube(
    monkeypatch: pytest.MonkeyPatch,
    *,
    listed: list[VideoRef],
    transcripts: dict[str, FetchedTranscript | Exception],
) -> None:
    monkeypatch.setattr(youtube_mod, "list_videos", lambda key, *, limit: tuple(listed[:limit]))

    def fake_transcript(video_id: str, **_: object) -> FetchedTranscript:
        result = transcripts[video_id]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(youtube_mod, "fetch_transcript", fake_transcript)
    monkeypatch.setattr(
        youtube_mod, "fetch_video_meta",
        lambda video_id: VideoRef(
            video_id=video_id, title=f"Title {video_id}",
            url=f"https://www.youtube.com/watch?v={video_id}", duration_s=600, published=_NOW,
        ),
    )


def test_discover_returns_only_un_ingested_videos(settings: Settings, monkeypatch) -> None:
    store = VaultStore(settings)
    _persona_with_youtube(store)
    _mark_ingested(store, slug="creator-a", video_id="vold")

    _stub_youtube(
        monkeypatch,
        listed=[
            VideoRef(video_id="vnew", title="New one", url="https://youtu.be/vnew", duration_s=1, published=None),
            VideoRef(video_id="vold", title="Old one", url="https://youtu.be/vold", duration_s=1, published=None),
        ],
        transcripts={
            "vnew": FetchedTranscript(video_id="vnew", text="fresh transcript body", lang="ko", generated=True),
        },
    )

    tasks = backfill.discover_tasks(settings)

    assert [t.video_id for t in tasks] == ["vnew"]
    task = tasks[0]
    assert task.persona_slug == "creator-a"
    assert task.transcript == "fresh transcript body"
    assert task.lang == "ko" and task.generated is True
    # fetch_video_meta backfilled the published date the flat listing lacked.
    assert task.published == _NOW


def test_discover_skips_videos_whose_transcript_is_unavailable(settings: Settings, monkeypatch) -> None:
    store = VaultStore(settings)
    _persona_with_youtube(store)
    _stub_youtube(
        monkeypatch,
        listed=[
            VideoRef(video_id="vgood", title="g", url="u", duration_s=1, published=None),
            VideoRef(video_id="vbad", title="b", url="u", duration_s=1, published=None),
        ],
        transcripts={
            "vgood": FetchedTranscript(video_id="vgood", text="ok", lang="en", generated=False),
            "vbad": TranscriptUnavailable("captions disabled", provider="youtube"),
        },
    )

    tasks = backfill.discover_tasks(settings)
    assert [t.video_id for t in tasks] == ["vgood"]  # the caption-less video is skipped, not fatal


def test_discover_survives_a_dead_channel_listing(settings: Settings, monkeypatch) -> None:
    store = VaultStore(settings)
    _persona_with_youtube(store)
    monkeypatch.setattr(
        youtube_mod, "list_videos",
        lambda key, *, limit: (_ for _ in ()).throw(SourceError("channel gone", provider="youtube")),
    )
    # No raise -- a listing failure degrades to an empty result for that persona.
    assert backfill.discover_tasks(settings) == []


def test_discover_clamps_limit_per_persona(settings: Settings, monkeypatch) -> None:
    store = VaultStore(settings)
    _persona_with_youtube(store)
    listed = [
        VideoRef(video_id=f"v{i}", title=str(i), url="u", duration_s=1, published=None) for i in range(5)
    ]
    _stub_youtube(
        monkeypatch,
        listed=listed,
        transcripts={f"v{i}": FetchedTranscript(video_id=f"v{i}", text="t", lang="ko", generated=True) for i in range(5)},
    )
    tasks = backfill.discover_tasks(settings, limit_per_persona=2)
    assert len(tasks) == 2


def _sample_task() -> backfill.BackfillTask:
    return backfill.BackfillTask(
        persona_slug="creator-a",
        persona_name="Creator A",
        source_id="yt:UCabc",
        video_id="vnew",
        url="https://www.youtube.com/watch?v=vnew",
        title="September Market View",
        published=_NOW,
        lang="ko",
        transcript="오늘은 엔비디아에 대해 이야기하겠습니다.",
        generated=True,
    )


def test_render_task_markdown_carries_the_contract_and_transcript() -> None:
    md = backfill.render_task_markdown(_sample_task(), summary_lang="en")
    # Task id (the video id) is present so the owner pastes it back with the result.
    assert "`vnew`" in md
    # The JSON output contract and its field names are present.
    assert "```json" in md
    for field in ("summary", "themes", "quotes", "mentions", "stance", "horizon", "reasoning"):
        assert field in md
    # The number-grounding guardrail the result-ingest depends on is stated.
    assert "Only state numbers that appear in the transcript" in md
    # The transcript itself is embedded, verbatim.
    assert "엔비디아" in md


def test_task_from_transcript_builds_a_packet_without_youtube() -> None:
    # The IP-block escape hatch: a packet from a transcript already in hand, no network call. Attribution
    # comes off the persona; the video watch-url is derived from the id.
    persona = Persona(
        slug="creator-a",
        display_name="Creator A",
        sources=(
            FollowedSource(source_id="yt:UCabc", platform="youtube", handle="creator-a",
                           channel_id="UCabc", url="https://www.youtube.com/channel/UCabc",
                           added_at=_NOW),
        ),
        created_at=_NOW,
    )
    task = backfill.task_from_transcript(
        persona, video_id="VIDEOID005", transcript="오늘은 엔비디아 이야기입니다.", lang="ko"
    )
    assert task.persona_slug == "creator-a"
    assert task.persona_name == "Creator A"
    assert task.source_id == "yt:UCabc"
    assert task.url == "https://www.youtube.com/watch?v=VIDEOID005"
    assert task.transcript == "오늘은 엔비디아 이야기입니다."
    md = backfill.render_task_markdown(task, summary_lang="en")
    assert "VIDEOID005" in md and "엔비디아" in md


def test_write_task_files_writes_one_per_task_plus_index(settings: Settings, tmp_path) -> None:
    tasks = [_sample_task()]
    out_dir = tmp_path / "packets"
    written = backfill.write_task_files(tasks, out_dir, summary_lang="en")

    assert written == [out_dir / "creator-a__vnew.md"]
    assert written[0].is_file()
    index = (out_dir / "index.md").read_text(encoding="utf-8")
    assert "creator-a__vnew.md" in index
    assert "1 task(s)" in index


# --- reading packets back ---------------------------------------------------------
#
# The writer above and the reader below are one symmetric pair, so every test here goes through
# `write_task_files` rather than a hand-built fixture string: a header line reworded in the renderer
# must break these, not silently stop parsing in production.


def test_list_task_packets_returns_the_ref_for_each_written_packet(tmp_path) -> None:
    out_dir = tmp_path / "packets"
    backfill.write_task_files([_sample_task()], out_dir, summary_lang="en")

    refs = backfill.list_task_packets(out_dir)

    assert len(refs) == 1  # index.md is not a task
    ref = refs[0]
    assert ref.persona_slug == "creator-a"
    assert ref.persona_name == "Creator A"
    assert ref.video_id == "vnew"
    assert ref.title == "September Market View"
    assert ref.url == "https://www.youtube.com/watch?v=vnew"
    assert ref.published == "2026-09-01"
    assert ref.filename == "creator-a__vnew.md"
    assert ref.path == out_dir / "creator-a__vnew.md"


def test_list_task_packets_sorts_newest_published_first(tmp_path) -> None:
    older = dataclasses.replace(
        _sample_task(), video_id="vold", published=dt.datetime(2026, 8, 1, tzinfo=_UTC)
    )
    unknown = dataclasses.replace(_sample_task(), video_id="vunk", published=None)
    out_dir = tmp_path / "packets"
    backfill.write_task_files([older, _sample_task(), unknown], out_dir, summary_lang="en")

    assert [r.video_id for r in backfill.list_task_packets(out_dir)] == ["vnew", "vold", "vunk"]
    # An unknown date is the empty string, never a stand-in value.
    assert backfill.list_task_packets(out_dir)[-1].published == ""


def test_read_task_packet_recovers_the_transcript_and_identity(tmp_path) -> None:
    out_dir = tmp_path / "packets"
    written = backfill.write_task_files([_sample_task()], out_dir, summary_lang="en")

    packet = backfill.read_task_packet(written[0])

    assert packet.ref.persona_slug == "creator-a"
    assert packet.ref.video_id == "vnew"
    # The transcript comes back verbatim -- it is what the result-ingest grounds a reply against.
    assert packet.transcript == "오늘은 엔비디아에 대해 이야기하겠습니다."
    assert packet.lang == "ko"
    assert packet.generated is True
    assert "## Transcript" in packet.markdown


def test_read_task_packet_rejects_a_file_that_is_not_a_packet(tmp_path) -> None:
    bogus = tmp_path / "notes.md"
    bogus.write_text("# just some markdown\n", encoding="utf-8")
    with pytest.raises(ValueError):
        backfill.read_task_packet(bogus)


def test_find_task_packet_finds_by_video_id_alone(tmp_path) -> None:
    out_dir = tmp_path / "packets"
    backfill.write_task_files([_sample_task()], out_dir, summary_lang="en")

    found = backfill.find_task_packet(out_dir, "vnew")
    assert found is not None and found.ref.persona_slug == "creator-a"


def test_find_task_packet_on_a_missing_id_returns_none(tmp_path) -> None:
    out_dir = tmp_path / "packets"
    backfill.write_task_files([_sample_task()], out_dir, summary_lang="en")
    assert backfill.find_task_packet(out_dir, "nosuchid") is None


@pytest.mark.parametrize("video_id", ["*", "?", "[vnew]", "vn*w", "*__vnew.md"])
def test_find_task_packet_rejects_glob_metacharacters_rather_than_globbing(
    tmp_path, video_id: str
) -> None:
    """`find_task_packet` used to pass `video_id` straight into `Path.glob` -- a caller-supplied `*`
    (or `?`/`[...]`) would then match every packet in the directory instead of naming exactly one.
    Even though the API boundary (`ValidateRequest.video_id`/`VideoIdPath`) now also rejects these
    characters, this function must refuse them on its own too -- a direct caller (not just the HTTP
    router) must never turn a video id into a directory listing."""
    out_dir = tmp_path / "packets"
    backfill.write_task_files([_sample_task()], out_dir, summary_lang="en")
    assert backfill.find_task_packet(out_dir, video_id) is None


def test_list_task_packets_on_a_missing_dir_returns_empty(tmp_path) -> None:
    # No packets generated yet is a normal state for the page and the CLI, not an error.
    assert backfill.list_task_packets(tmp_path / "nope") == []
    assert backfill.find_task_packet(tmp_path / "nope", "vnew") is None


def test_list_task_packets_skips_an_unparseable_file(tmp_path) -> None:
    out_dir = tmp_path / "packets"
    backfill.write_task_files([_sample_task()], out_dir, summary_lang="en")
    (out_dir / "mangled.md").write_text("someone edited this by hand\n", encoding="utf-8")

    # One bad file must not hide every other pending task -- the store's own listing discipline.
    assert [r.video_id for r in backfill.list_task_packets(out_dir)] == ["vnew"]


def test_packet_path_matches_what_write_task_files_wrote(tmp_path) -> None:
    out_dir = tmp_path / "packets"
    written = backfill.write_task_files([_sample_task()], out_dir, summary_lang="en")
    assert backfill.packet_path(out_dir, "creator-a", "vnew") == written[0]
