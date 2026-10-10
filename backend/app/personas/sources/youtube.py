"""YouTube source adapter: handle -> channel, channel -> recent videos, video -> metadata/transcript.

Every upstream fact this module relies on was verified live against the five seed channels on
2026-09-01 (see `docs/INFLUENCER-CONTRACT.md`'s "Verified upstream facts" section); none of it is
re-derived here, only implemented against.

* **Handle resolution is keyless HTML scraping, not an API call.** `GET youtube.com/@<handle>`
  (following redirects) embeds the channel's `externalId` and `og:title` in the page's inline JSON
  and meta tags. No YouTube Data API key is used or required anywhere in this module.
* **The RSS feed (`feeds/videos.xml?channel_id=`) is dead for these channels** -- verified 404/500
  against every seed channel with both an honest and a browser-shaped User-Agent. Do not resurrect
  it as a "simpler" alternative to yt-dlp; it was tried and it does not work.
* **A flat channel listing carries no upload date whatsoever.** `yt_dlp` with `extract_flat=True`
  returns entries whose only non-null keys are `_type, duration, id, ie_key, thumbnails, title, url,
  view_count` -- `timestamp`, `upload_date` and `release_timestamp` are all absent, not merely
  `None`. `list_videos` therefore always returns `published=None`; recovering a real date costs a
  separate, non-flat `fetch_video_meta` call per video, which is why it is a call the caller opts
  into rather than something `list_videos` does automatically for every entry it returns.
* **Every seed channel's captions are auto-generated (ASR) only.** `fetch_transcript` still prefers
  a manually-created track when one exists, but no seed channel currently offers one to test against.

Every network call carries the honest `User-Agent: investing-dashboard/0.1` (never a browser
string -- see `app/market/providers/fred.py`'s module docstring for why that backfires) and an
explicit timeout, the same two rules every provider in `app.market.providers` follows.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from collections.abc import Sequence
from typing import Final
from urllib.parse import unquote, urlsplit

import httpx
import yt_dlp  # type: ignore[import-untyped]
from requests.exceptions import RequestException
from youtube_transcript_api import (
    AgeRestricted,
    CouldNotRetrieveTranscript,
    InvalidVideoId,
    IpBlocked,
    NoTranscriptFound,
    PoTokenRequired,
    RequestBlocked,
    Transcript,
    TranscriptList,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeRequestFailed,
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
)
from yt_dlp.utils import DownloadError  # type: ignore[import-untyped]

from app.personas.sources.base import (
    FetchedTranscript,
    ResolvedChannel,
    SourceError,
    SourceNotFound,
    SourceUnavailable,
    TranscriptUnavailable,
    VideoRef,
)

__all__ = [
    "fetch_transcript",
    "fetch_video_meta",
    "list_videos",
    "resolve_handle",
]

#: Honest, not a spoofed browser string. See `app/market/providers/fred.py`'s module docstring for
#: why a Chrome-shaped User-Agent is the wrong instinct here, not just an unnecessary one.
_USER_AGENT: Final[str] = "investing-dashboard/0.1"

_TIMEOUT: Final[float] = 15.0

#: Captures the channel id embedded in a `youtube.com/@<handle>` page's inline JSON. Verified
#: against all five seed channels 2026-09-01.
_CHANNEL_ID_RE: Final[re.Pattern[str]] = re.compile(r'"externalId":"(UC[\w-]{22})"')

#: The channel's display name, from the page's Open Graph title tag.
_OG_TITLE_RE: Final[re.Pattern[str]] = re.compile(r'<meta property="og:title" content="([^"]*)"')

#: A bare `UC...` channel id is 24 characters total: the fixed `UC` prefix plus 22 base64url-ish
#: characters. Used to tell `list_videos`'s `handle_or_channel_id` argument apart from a handle
#: without a network round trip.
_CHANNEL_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^UC[\w-]{22}$")


def _normalize_handle(raw: str) -> str:
    """Accept `"@creator-a"`, `"creator-a"`, or a full channel URL and return the bare handle.

    Also undoes percent-encoding, so a handle passed pre-encoded (as one seed channel's Korean
    handle, `%EA%B9%80%EB%8B%A8%ED%85%8C`, sometimes arrives) and the same handle passed as literal
    unicode both normalise to one value. Re-encoding for the outgoing request is `httpx`'s job --
    verified 2026-09-01 that `httpx.Client(...).get(f".../@{unicode_handle}")` percent-encodes the
    path segment on its own, so this function does not need to re-encode before handing the string
    off.
    """
    s = raw.strip()
    if s.startswith(("http://", "https://")):
        s = urlsplit(s).path
    s = s.strip("/")
    if s.startswith("@"):
        s = s[1:]
    return unquote(s)


def resolve_handle(handle: str, *, client: httpx.Client | None = None) -> ResolvedChannel:
    """Resolve a handle to its stable `UC...` channel id.

    Keyless: fetches `youtube.com/@<handle>` and regex-searches the response body for the channel's
    `externalId` and `og:title`. `client` is accepted for tests (`httpx.MockTransport`) and for a
    caller that wants to share a connection pool across several resolutions; when omitted, a
    short-lived client is created and closed here.
    """
    normalized = _normalize_handle(handle)
    if not normalized:
        raise SourceNotFound(f"empty handle after normalising {handle!r}", provider="youtube")

    url = f"https://www.youtube.com/@{normalized}"
    owns_client = client is None
    http_client = client if client is not None else httpx.Client(
        timeout=_TIMEOUT, follow_redirects=True
    )
    try:
        try:
            response = http_client.get(url, headers={"User-Agent": _USER_AGENT})
        except httpx.TimeoutException as exc:
            raise SourceUnavailable(
                f"timed out resolving handle {handle!r}", provider="youtube"
            ) from exc
        except httpx.TransportError as exc:
            raise SourceUnavailable(
                f"transport error resolving handle {handle!r}: {exc}", provider="youtube"
            ) from exc

        if response.status_code == 404:
            raise SourceNotFound(f"no channel for handle {handle!r}", provider="youtube")
        if response.status_code >= 400:
            raise SourceUnavailable(
                f"youtube returned {response.status_code} resolving handle {handle!r}",
                provider="youtube",
            )

        match = _CHANNEL_ID_RE.search(response.text)
        if match is None:
            raise SourceNotFound(
                f"no channel id found on the page for handle {handle!r}", provider="youtube"
            )
        channel_id = match.group(1)

        title_match = _OG_TITLE_RE.search(response.text)
        display_name = html.unescape(title_match.group(1)) if title_match else normalized

        return ResolvedChannel(
            channel_id=channel_id, display_name=display_name, handle=normalized, url=url
        )
    finally:
        if owns_client:
            http_client.close()


def _as_int(value: object) -> int | None:
    """`yt_dlp` entries carry numeric fields as `int | float | None`; `bool` is technically an `int`
    subclass but never a meaningful duration, so it is excluded the same way
    `app.market.providers.yahoo_news._parse_published` excludes it from a timestamp field."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _classify_download_error(exc: Exception, identifier: str) -> SourceError:
    """`yt_dlp` raises one exception type (`DownloadError`) for everything from a 404 to a network
    timeout, so this layer has to read the message to tell "does not exist" apart from "try again".
    Deliberately conservative: only messages that clearly say the channel/video is gone map to
    `SourceNotFound`; anything else (blocked, rate-limited, a changed page format) maps to the
    retryable `SourceUnavailable`, since guessing wrong the other way would make an ingest job give
    up permanently on a source that was only ever temporarily unreachable."""
    msg = str(exc).lower()
    not_found_markers = (
        "404",
        "does not exist",
        "this channel does not have",
        "unable to find",
        "video unavailable",
        "this video is unavailable",
        "has been removed",
        "private video",
    )
    if any(marker in msg for marker in not_found_markers):
        return SourceNotFound(f"not found for {identifier!r}: {exc}", provider="youtube")
    return SourceUnavailable(f"yt-dlp failed for {identifier!r}: {exc}", provider="youtube")


def _channel_videos_url(handle_or_channel_id: str) -> str:
    s = handle_or_channel_id.strip()
    if _CHANNEL_ID_PATTERN.match(s):
        return f"https://www.youtube.com/channel/{s}/videos"
    normalized = _normalize_handle(s)
    return f"https://www.youtube.com/@{normalized}/videos"


def list_videos(handle_or_channel_id: str, *, limit: int) -> tuple[VideoRef, ...]:
    """The most recent `limit` videos on a channel, via a *flat* `yt_dlp` playlist extract.

    Accepts either a handle (`"@creator-a"`, `"creator-a"`) or a bare `UC...` channel id, and
    builds the matching `/@<handle>/videos` or `/channel/<id>/videos` URL.

    **Every returned `VideoRef.published` is `None`.** Verified 2026-09-01: a flat extract's entries
    carry no upload-date field of any kind. Callers that need a real date must call
    `fetch_video_meta` per video they keep -- deliberately not done here for every entry, since that
    would turn one fast flat listing into `limit` slow non-flat ones for videos the caller may not
    even end up ingesting.
    """
    url = _channel_videos_url(handle_or_channel_id)
    opts = {
        "quiet": True,
        "extract_flat": True,
        "playlistend": limit,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise _classify_download_error(exc, handle_or_channel_id) from exc

    if not info:
        return ()

    entries = info.get("entries") or []
    refs: list[VideoRef] = []
    for entry in entries:
        if not entry:
            continue
        video_id = entry.get("id")
        if not video_id:
            continue
        refs.append(
            VideoRef(
                video_id=video_id,
                title=entry.get("title") or "",
                url=entry.get("url") or f"https://www.youtube.com/watch?v={video_id}",
                duration_s=_as_int(entry.get("duration")),
                published=None,
            )
        )
        if len(refs) >= limit:
            break
    return tuple(refs)


def _parse_upload_date(upload_date: object, timestamp: object) -> dt.datetime | None:
    """`timestamp` (a unix int) is preferred when present; `upload_date` (a `"YYYYMMDD"` string) is
    the fallback. Either missing or unparseable answers `None` -- never a substitute date."""
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        return dt.datetime.fromtimestamp(timestamp, tz=dt.UTC)
    if isinstance(upload_date, str) and len(upload_date) == 8 and upload_date.isdigit():
        try:
            return dt.datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=dt.UTC)
        except ValueError:
            return None
    return None


def fetch_video_meta(video_id: str) -> VideoRef:
    """A non-flat, single-video `yt_dlp` extract -- slower than `list_videos`, and the only call in
    this module that can recover a real upload date. `published` is populated when YouTube's
    response carries `timestamp` or `upload_date`, and `None` when even this fails; see
    `_parse_upload_date`."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {"quiet": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise _classify_download_error(exc, video_id) from exc

    if not info:
        raise SourceNotFound(f"no metadata returned for video {video_id!r}", provider="youtube")

    return VideoRef(
        video_id=info.get("id") or video_id,
        title=info.get("title") or "",
        url=info.get("webpage_url") or url,
        duration_s=_as_int(info.get("duration")),
        published=_parse_upload_date(info.get("upload_date"), info.get("timestamp")),
    )


def _pick_best_track(track_list: TranscriptList) -> Transcript:
    """Prefer a manually-created track over an auto-generated one; otherwise take whatever exists.

    `TranscriptList.__iter__` already yields manually-created tracks before generated ones, but that
    ordering is an implementation detail of `youtube_transcript_api` this function does not lean
    on -- it filters on `is_generated` explicitly so the preference holds even if that iteration
    order ever changes upstream.
    """
    tracks = list(track_list)
    if not tracks:
        raise TranscriptUnavailable(
            f"no caption tracks available for video {track_list.video_id!r}", provider="youtube"
        )
    manual = [t for t in tracks if not t.is_generated]
    return manual[0] if manual else tracks[0]


def fetch_transcript(
    video_id: str, *, languages: Sequence[str] | None = None
) -> FetchedTranscript:
    """The full transcript text for one video.

    With `languages` given, fetches that track directly (`YouTubeTranscriptApi.fetch`'s own
    priority-ordered language matching). With `languages=None`, lists every available track and
    picks the best one per `_pick_best_track` -- every seed channel currently offers auto-generated
    tracks only, so in practice that means "the first language YouTube generated captions in", but
    the preference for a manual track is honoured the moment one exists.

    Every failure from `youtube_transcript_api` (or the `requests` session it uses underneath) is
    translated to this module's own vocabulary: no caption track at all is `TranscriptUnavailable`;
    a video that does not exist or cannot be identified is `SourceNotFound`; everything else
    (blocked, rate-limited, a malformed response) is the retryable `SourceUnavailable`. No exception
    from either library is allowed to escape this function.
    """
    api = YouTubeTranscriptApi()
    try:
        if languages:
            fetched = api.fetch(video_id, languages=list(languages))
        else:
            fetched = _pick_best_track(api.list(video_id)).fetch()
    except (TranscriptsDisabled, NoTranscriptFound) as exc:
        raise TranscriptUnavailable(
            f"no usable transcript for video {video_id!r}: {exc}", provider="youtube"
        ) from exc
    except (VideoUnavailable, InvalidVideoId) as exc:
        raise SourceNotFound(
            f"video {video_id!r} does not exist: {exc}", provider="youtube"
        ) from exc
    except (
        IpBlocked,
        RequestBlocked,
        YouTubeRequestFailed,
        PoTokenRequired,
        VideoUnplayable,
        AgeRestricted,
        CouldNotRetrieveTranscript,
    ) as exc:
        raise SourceUnavailable(
            f"could not retrieve transcript for video {video_id!r}: {exc}", provider="youtube"
        ) from exc
    except YouTubeTranscriptApiException as exc:
        raise SourceUnavailable(
            f"youtube-transcript-api failure for video {video_id!r}: {exc}", provider="youtube"
        ) from exc
    except RequestException as exc:
        # A lower-level `requests` failure (connection error, timeout) that the library itself did
        # not wrap in one of its own exception types -- still must not escape as a raw library
        # exception.
        raise SourceUnavailable(
            f"network error fetching transcript for video {video_id!r}: {exc}", provider="youtube"
        ) from exc

    text = " ".join(snippet.text for snippet in fetched)
    return FetchedTranscript(
        video_id=video_id,
        text=text,
        lang=fetched.language_code,
        generated=fetched.is_generated,
    )
