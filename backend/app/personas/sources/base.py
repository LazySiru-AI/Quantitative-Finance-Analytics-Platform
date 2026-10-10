"""The source-layer contract and its error vocabulary.

Deliberately mirrors `app.market.providers.base`: `SourceError` carries a `provider` name the same
way `ProviderError` does, and the split between "does not exist" (`SourceNotFound`, terminal) and
"try again later" (`SourceUnavailable`, retryable) is the same distinction that split protects
there. This layer adds one case market providers do not need: `TranscriptUnavailable`, for a video
that resolves and plays fine but carries no usable caption track. Collapsing that into
`SourceUnavailable` would make an ingest job retry a video that will never grow a transcript;
collapsing it into `SourceNotFound` would tell the caller the video itself does not exist, when it
does -- the ingest log needs to say "no captions", not "no such video".

The dataclasses below are the source layer's own wire shapes, not `app.personas.models`' frontend
contract types -- `app.personas.service` (Phase 1) is what maps a `VideoRef` + `FetchedTranscript`
into an `EpisodicNote`. Keeping the two separate means a source adapter never needs to know about
the vault, ticker validation, or grounding.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

__all__ = [
    "FetchedTranscript",
    "ResolvedChannel",
    "SourceError",
    "SourceNotFound",
    "SourceUnavailable",
    "TranscriptUnavailable",
    "VideoRef",
]


class SourceError(Exception):
    """Base for every source-layer failure. Carries the provider name for the caller's warning
    text -- same shape as `app.market.providers.base.ProviderError`."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message)
        self.provider = provider


class SourceUnavailable(SourceError):
    """Upstream unreachable, blocked, rate-limited, or answered with something this layer's parser
    does not understand. Retryable: an ingest job should try this source again later rather than
    give up on it."""


class SourceNotFound(SourceError):
    """The upstream is healthy and says this handle or video does not exist. Terminal: retrying
    will not make a mistyped handle or a deleted video reappear."""


class TranscriptUnavailable(SourceError):
    """The video resolves and plays fine but has no usable caption track -- disabled entirely, or
    none in a requested language. See the module docstring for why this is its own case rather
    than folded into `SourceNotFound` or `SourceUnavailable`."""


@dataclass(frozen=True)
class ResolvedChannel:
    """A handle resolved to a stable channel id.

    `handle` is normalised: no leading ``@``, and percent-encoding undone, so a caller that passes
    ``"%EA%B9%80%EB%8B%A8%ED%85%8C"`` and one that passes the literal Korean handle both resolve to
    the same value here.
    """

    channel_id: str
    display_name: str
    handle: str
    url: str


@dataclass(frozen=True)
class VideoRef:
    """One video, as known by whichever call produced it.

    `published` is `None` from every `list_videos` result -- verified 2026-09-01: yt-dlp's *flat*
    channel listing carries no upload-date field at all (`timestamp`, `upload_date` and
    `release_timestamp` are all absent from its entries). Only `fetch_video_meta`, a separate and
    slower non-flat per-video extract, can recover it, and even that returns `None` when YouTube's
    own response omits it -- never a fabricated date standing in for a real one.
    """

    video_id: str
    title: str
    url: str
    duration_s: int | None
    published: dt.datetime | None


@dataclass(frozen=True)
class FetchedTranscript:
    """The full text of one caption track, plus which track it was.

    `text` is every snippet joined with a single space -- good enough as evidence text for the
    grounding check and the summariser; it is not meant to preserve per-snippet timing. `generated`
    is `True` for an auto (ASR) track; every seed channel has auto-generated tracks only, so callers
    should not assume a manual track will ever be offered.
    """

    video_id: str
    text: str
    lang: str
    generated: bool
