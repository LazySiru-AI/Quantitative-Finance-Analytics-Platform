"""Tests for the YouTube source layer (`app.personas.sources.youtube`).

No test in this file makes a network call. `resolve_handle` is driven through an
`httpx.MockTransport`; `list_videos`/`fetch_video_meta` monkeypatch `yt_dlp.YoutubeDL` with a fake
context manager; `fetch_transcript` monkeypatches `YouTubeTranscriptApi.list`/`.fetch` with fake
track objects. The two captured HTML fixtures under `tests/fixtures/personas/` are synthetic --
trimmed to the two fields (`externalId`, `og:title`) this module's regexes actually read -- rather
than a full page dump, since a real `youtube.com/@<handle>` response is tens of thousands of lines
of unrelated inline JSON.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from youtube_transcript_api import (
    AgeRestricted,
    InvalidVideoId,
    IpBlocked,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)
from yt_dlp.utils import DownloadError

from app.personas.sources.base import (
    FetchedTranscript,
    ResolvedChannel,
    SourceNotFound,
    SourceUnavailable,
    TranscriptUnavailable,
    VideoRef,
)
from app.personas.sources.youtube import (
    fetch_transcript,
    fetch_video_meta,
    list_videos,
    resolve_handle,
)

FIXTURES = Path(__file__).parent / "fixtures" / "personas"


def _load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _load_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _client_returning(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def _client_html(status_code: int, body: str) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=body)

    return _client_returning(handler)


def _client_raising(exc: Exception) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return _client_returning(handler)


# ---------------------------------------------------------------------------
# base.py -- the error/data vocabulary itself
# ---------------------------------------------------------------------------


class TestBaseTypes:
    def test_source_error_carries_provider(self) -> None:
        exc = SourceUnavailable("boom", provider="youtube")
        assert exc.provider == "youtube"
        assert str(exc) == "boom"

    def test_error_hierarchy(self) -> None:
        assert issubclass(SourceUnavailable, Exception)
        assert issubclass(SourceNotFound, Exception)
        assert issubclass(TranscriptUnavailable, Exception)

    def test_dataclasses_are_frozen(self) -> None:
        channel = ResolvedChannel(
            channel_id="UCaaaaaaaaaaaaaaaaaaaaaa",
            display_name="Creator A",
            handle="creator-a",
            url="https://www.youtube.com/@creator-a",
        )
        with pytest.raises(AttributeError):
            channel.channel_id = "UCother"  # type: ignore[misc]

        ref = VideoRef(video_id="v1", title="t", url="u", duration_s=10, published=None)
        with pytest.raises(AttributeError):
            ref.title = "other"  # type: ignore[misc]

        transcript = FetchedTranscript(video_id="v1", text="hi", lang="en", generated=True)
        with pytest.raises(AttributeError):
            transcript.text = "bye"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# resolve_handle
# ---------------------------------------------------------------------------


class TestResolveHandle:
    @pytest.mark.parametrize(
        "raw",
        ["@creator-a", "creator-a", "https://www.youtube.com/@creator-a", "  @creator-a  "],
    )
    def test_handle_variants_all_resolve_the_same(self, raw: str) -> None:
        html = _load_text("youtube_channel_creator_a.html")
        client = _client_html(200, html)

        channel = resolve_handle(raw, client=client)

        assert channel.channel_id == "UCaaaaaaaaaaaaaaaaaaaaaa"
        assert channel.display_name == "Creator A"
        assert channel.handle == "creator-a"
        assert channel.url == "https://www.youtube.com/@creator-a"

    def test_url_encoded_korean_handle_resolves(self) -> None:
        """One seed channel's handle is exactly this Korean, percent-encoded string -- verified
        2026-09-01 to work through the live resolver. Must not be url-decoded incorrectly or
        garbled when rebuilt into the outgoing request."""
        html = _load_text("youtube_channel_korean.html")
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, text=html)

        client = _client_returning(handler)

        channel = resolve_handle("%ED%99%8D%EA%B8%B8%EB%8F%99", client=client)

        assert channel.channel_id == "UCabcDEFghijKLMNOPqrstuv"
        assert channel.display_name == "홍길동"
        assert channel.handle == "홍길동"
        # The outgoing request must carry the handle re-encoded, not double-encoded or mangled.
        assert "%25" not in str(seen[0].url)

    def test_literal_unicode_handle_normalises_the_same_as_percent_encoded(self) -> None:
        html = _load_text("youtube_channel_korean.html")
        client = _client_html(200, html)

        channel = resolve_handle("홍길동", client=client)

        assert channel.handle == "홍길동"
        assert channel.channel_id == "UCabcDEFghijKLMNOPqrstuv"

    def test_user_agent_is_honest_not_a_spoofed_browser(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, text=_load_text("youtube_channel_creator_a.html"))

        client = _client_returning(handler)
        resolve_handle("creator-a", client=client)

        ua = seen[0].headers.get("user-agent", "")
        assert ua == "investing-dashboard/0.1"
        for spoofed in ("Mozilla", "Chrome", "Safari", "WebKit"):
            assert spoofed not in ua

    def test_404_raises_source_not_found(self) -> None:
        client = _client_html(404, "not found")
        with pytest.raises(SourceNotFound):
            resolve_handle("nobody-has-this-handle", client=client)

    def test_500_raises_source_unavailable(self) -> None:
        client = _client_html(500, "server error")
        with pytest.raises(SourceUnavailable):
            resolve_handle("creator-a", client=client)

    def test_timeout_raises_source_unavailable(self) -> None:
        client = _client_raising(httpx.TimeoutException("timed out"))
        with pytest.raises(SourceUnavailable):
            resolve_handle("creator-a", client=client)

    def test_transport_error_raises_source_unavailable(self) -> None:
        client = _client_raising(httpx.ConnectError("connection refused"))
        with pytest.raises(SourceUnavailable):
            resolve_handle("creator-a", client=client)

    def test_page_without_external_id_raises_source_not_found(self) -> None:
        client = _client_html(200, "<html><body>nothing useful here</body></html>")
        with pytest.raises(SourceNotFound):
            resolve_handle("creator-a", client=client)

    def test_missing_og_title_falls_back_to_normalised_handle(self) -> None:
        body = '<html><script>"externalId":"UCaaaaaaaaaaaaaaaaaaaaaa"</script></html>'
        client = _client_html(200, body)

        channel = resolve_handle("creator-a", client=client)

        assert channel.channel_id == "UCaaaaaaaaaaaaaaaaaaaaaa"
        assert channel.display_name == "creator-a"

    def test_empty_handle_raises_source_not_found(self) -> None:
        with pytest.raises(SourceNotFound):
            resolve_handle("@", client=_client_raising(AssertionError("should not be called")))


# ---------------------------------------------------------------------------
# list_videos
# ---------------------------------------------------------------------------


class _FakeYoutubeDL:
    """Stands in for `yt_dlp.YoutubeDL` as a context manager. `calls` records every
    `(url, opts)` pair `extract_info` was invoked with, so tests can assert the right channel
    URL was built without a real network call."""

    def __init__(
        self,
        *,
        result: dict[str, Any] | None,
        error: Exception | None = None,
        calls: list[tuple[str, dict[str, Any]]] | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self._calls = calls

    def __call__(self, opts: dict[str, Any]) -> _FakeYoutubeDL:
        self._opts = opts
        return self

    def __enter__(self) -> _FakeYoutubeDL:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def extract_info(self, url: str, download: bool = False) -> dict[str, Any] | None:
        if self._calls is not None:
            self._calls.append((url, self._opts))
        if self._error is not None:
            raise self._error
        return self._result


class TestListVideos:
    def test_handle_builds_the_at_handle_videos_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []
        fake = _FakeYoutubeDL(result=_load_json("flat_listing_creator_a.json"), calls=calls)
        monkeypatch.setattr("app.personas.sources.youtube.yt_dlp.YoutubeDL", fake)

        list_videos("@creator-a", limit=3)

        assert calls[0][0] == "https://www.youtube.com/@creator-a/videos"

    def test_channel_id_builds_the_channel_videos_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []
        fake = _FakeYoutubeDL(result=_load_json("flat_listing_creator_a.json"), calls=calls)
        monkeypatch.setattr("app.personas.sources.youtube.yt_dlp.YoutubeDL", fake)

        list_videos("UCaaaaaaaaaaaaaaaaaaaaaa", limit=3)

        assert calls[0][0] == "https://www.youtube.com/channel/UCaaaaaaaaaaaaaaaaaaaaaa/videos"

    def test_opts_match_the_verified_flat_extraction_shape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []
        fake = _FakeYoutubeDL(result=_load_json("flat_listing_creator_a.json"), calls=calls)
        monkeypatch.setattr("app.personas.sources.youtube.yt_dlp.YoutubeDL", fake)

        list_videos("@creator-a", limit=5)

        opts = calls[0][1]
        assert opts["extract_flat"] is True
        assert opts["skip_download"] is True
        assert opts["playlistend"] == 5

    def test_entries_parse_with_published_always_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The verified fact this module exists to encode: a flat listing carries no upload date
        at all, so `published` must be `None` on every returned `VideoRef` -- never a stand-in."""
        payload = _load_json("flat_listing_creator_a.json")
        fake = _FakeYoutubeDL(result=payload)
        monkeypatch.setattr("app.personas.sources.youtube.yt_dlp.YoutubeDL", fake)

        refs = list_videos("@creator-a", limit=10)

        assert len(refs) == 3
        assert all(ref.published is None for ref in refs)
        first = refs[0]
        raw_first = payload["entries"][0]
        assert first.video_id == raw_first["id"]
        assert first.title == raw_first["title"]
        assert first.url == raw_first["url"]
        assert first.duration_s == int(raw_first["duration"])

    def test_limit_truncates_entries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeYoutubeDL(result=_load_json("flat_listing_creator_a.json"))
        monkeypatch.setattr("app.personas.sources.youtube.yt_dlp.YoutubeDL", fake)

        refs = list_videos("@creator-a", limit=2)

        assert len(refs) == 2

    def test_entries_missing_id_are_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = {"entries": [{"id": None, "title": "no id"}, {"id": "ok1", "title": "fine"}]}
        fake = _FakeYoutubeDL(result=payload)
        monkeypatch.setattr("app.personas.sources.youtube.yt_dlp.YoutubeDL", fake)

        refs = list_videos("@creator-a", limit=10)

        assert len(refs) == 1
        assert refs[0].video_id == "ok1"

    def test_none_info_returns_empty_tuple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeYoutubeDL(result=None)
        monkeypatch.setattr("app.personas.sources.youtube.yt_dlp.YoutubeDL", fake)

        assert list_videos("@creator-a", limit=10) == ()

    def test_download_error_mentioning_404_raises_source_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _FakeYoutubeDL(result=None, error=DownloadError("HTTP Error 404: Not Found"))
        monkeypatch.setattr("app.personas.sources.youtube.yt_dlp.YoutubeDL", fake)

        with pytest.raises(SourceNotFound):
            list_videos("@no-such-handle-at-all", limit=10)

    def test_download_error_otherwise_raises_source_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _FakeYoutubeDL(result=None, error=DownloadError("Sign in to confirm you're not a bot"))
        monkeypatch.setattr("app.personas.sources.youtube.yt_dlp.YoutubeDL", fake)

        with pytest.raises(SourceUnavailable):
            list_videos("@creator-a", limit=10)


# ---------------------------------------------------------------------------
# fetch_video_meta
# ---------------------------------------------------------------------------


class TestFetchVideoMeta:
    def test_timestamp_is_preferred_and_parsed_as_utc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = _load_json("video_meta_vidaaaaaa01.json")
        fake = _FakeYoutubeDL(result=payload)
        monkeypatch.setattr("app.personas.sources.youtube.yt_dlp.YoutubeDL", fake)

        ref = fetch_video_meta("vidAAAAAA01")

        assert ref.video_id == "vidAAAAAA01"
        assert ref.title == payload["title"]
        assert ref.duration_s == 612
        assert ref.published is not None
        assert ref.published.tzinfo is not None
        assert ref.published.year == 2026 and ref.published.month == 9 and ref.published.day == 1

    def test_upload_date_string_used_when_timestamp_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = dict(_load_json("video_meta_vidaaaaaa01.json"))
        del payload["timestamp"]
        fake = _FakeYoutubeDL(result=payload)
        monkeypatch.setattr("app.personas.sources.youtube.yt_dlp.YoutubeDL", fake)

        ref = fetch_video_meta("vidAAAAAA01")

        assert ref.published is not None
        assert (ref.published.year, ref.published.month, ref.published.day) == (2026, 9, 1)

    def test_missing_both_date_fields_leaves_published_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = dict(_load_json("video_meta_vidaaaaaa01.json"))
        del payload["timestamp"]
        del payload["upload_date"]
        fake = _FakeYoutubeDL(result=payload)
        monkeypatch.setattr("app.personas.sources.youtube.yt_dlp.YoutubeDL", fake)

        ref = fetch_video_meta("vidAAAAAA01")

        assert ref.published is None

    def test_none_info_raises_source_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeYoutubeDL(result=None)
        monkeypatch.setattr("app.personas.sources.youtube.yt_dlp.YoutubeDL", fake)

        with pytest.raises(SourceNotFound):
            fetch_video_meta("does-not-exist")

    def test_download_error_mentioning_unavailable_raises_source_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _FakeYoutubeDL(result=None, error=DownloadError("Video unavailable"))
        monkeypatch.setattr("app.personas.sources.youtube.yt_dlp.YoutubeDL", fake)

        with pytest.raises(SourceNotFound):
            fetch_video_meta("gone")


# ---------------------------------------------------------------------------
# fetch_transcript
# ---------------------------------------------------------------------------


class _FakeSnippet:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeFetchedTranscript:
    def __init__(self, language_code: str, is_generated: bool, texts: list[str]) -> None:
        self.language_code = language_code
        self.is_generated = is_generated
        self._snippets = [_FakeSnippet(t) for t in texts]

    def __iter__(self) -> Any:
        return iter(self._snippets)


class _FakeTranscript:
    def __init__(self, language_code: str, is_generated: bool, texts: list[str]) -> None:
        self.language_code = language_code
        self.is_generated = is_generated
        self._texts = texts

    def fetch(self, preserve_formatting: bool = False) -> _FakeFetchedTranscript:
        return _FakeFetchedTranscript(self.language_code, self.is_generated, self._texts)


class _FakeTranscriptList:
    def __init__(self, video_id: str, tracks: list[_FakeTranscript]) -> None:
        self.video_id = video_id
        self._tracks = tracks

    def __iter__(self) -> Any:
        return iter(self._tracks)


class TestFetchTranscript:
    def test_languages_none_prefers_manual_over_generated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tracks = [
            _FakeTranscript("en", True, ["auto", "generated", "text"]),
            _FakeTranscript("ko", False, ["수동", "자막"]),
        ]
        monkeypatch.setattr(
            YouTubeTranscriptApi, "list", lambda self, video_id: _FakeTranscriptList(video_id, tracks)
        )

        result = fetch_transcript("vid1")

        assert result.video_id == "vid1"
        assert result.lang == "ko"
        assert result.generated is False
        assert result.text == "수동 자막"

    def test_languages_none_falls_back_to_generated_when_no_manual_track(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tracks = [_FakeTranscript("ko", True, ["오토", "캡션"])]
        monkeypatch.setattr(
            YouTubeTranscriptApi, "list", lambda self, video_id: _FakeTranscriptList(video_id, tracks)
        )

        result = fetch_transcript("vid2")

        assert result.lang == "ko"
        assert result.generated is True
        assert result.text == "오토 캡션"

    def test_empty_track_list_raises_transcript_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            YouTubeTranscriptApi, "list", lambda self, video_id: _FakeTranscriptList(video_id, [])
        )

        with pytest.raises(TranscriptUnavailable):
            fetch_transcript("no-captions")

    def test_explicit_languages_calls_fetch_directly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}

        def fake_fetch(self: YouTubeTranscriptApi, video_id: str, languages: list[str]) -> Any:
            seen["video_id"] = video_id
            seen["languages"] = languages
            return _FakeFetchedTranscript("en", True, ["hello", "world"])

        monkeypatch.setattr(YouTubeTranscriptApi, "fetch", fake_fetch)

        result = fetch_transcript("vid3", languages=["en", "ko"])

        assert seen["video_id"] == "vid3"
        assert seen["languages"] == ["en", "ko"]
        assert result.text == "hello world"
        assert result.lang == "en"
        assert result.generated is True

    @pytest.mark.parametrize(
        "exc",
        [TranscriptsDisabled("vid"), NoTranscriptFound("vid", ["en"], _FakeTranscriptList("vid", []))],
    )
    def test_no_transcript_style_errors_map_to_transcript_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, exc: Exception
    ) -> None:
        def raiser(self: YouTubeTranscriptApi, video_id: str) -> Any:
            raise exc

        monkeypatch.setattr(YouTubeTranscriptApi, "list", raiser)

        with pytest.raises(TranscriptUnavailable):
            fetch_transcript("vid")

    @pytest.mark.parametrize("exc", [VideoUnavailable("vid"), InvalidVideoId("vid")])
    def test_video_does_not_exist_errors_map_to_source_not_found(
        self, monkeypatch: pytest.MonkeyPatch, exc: Exception
    ) -> None:
        def raiser(self: YouTubeTranscriptApi, video_id: str) -> Any:
            raise exc

        monkeypatch.setattr(YouTubeTranscriptApi, "list", raiser)

        with pytest.raises(SourceNotFound):
            fetch_transcript("vid")

    @pytest.mark.parametrize("exc", [IpBlocked("vid"), AgeRestricted("vid")])
    def test_blocked_or_restricted_errors_map_to_source_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, exc: Exception
    ) -> None:
        def raiser(self: YouTubeTranscriptApi, video_id: str) -> Any:
            raise exc

        monkeypatch.setattr(YouTubeTranscriptApi, "list", raiser)

        with pytest.raises(SourceUnavailable):
            fetch_transcript("vid")

    def test_raw_requests_exception_does_not_escape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A `requests`-level network failure the library did not wrap must still not leak past
        this module as a raw library exception -- the contract's explicit rule."""

        def raiser(self: YouTubeTranscriptApi, video_id: str) -> Any:
            raise RequestsConnectionError("connection refused")

        monkeypatch.setattr(YouTubeTranscriptApi, "list", raiser)

        with pytest.raises(SourceUnavailable):
            fetch_transcript("vid")

    def test_text_joins_snippets_with_a_space(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tracks = [_FakeTranscript("en", True, ["one", "two", "three"])]
        monkeypatch.setattr(
            YouTubeTranscriptApi, "list", lambda self, video_id: _FakeTranscriptList(video_id, tracks)
        )

        result = fetch_transcript("vid")

        assert result.text == "one two three"
