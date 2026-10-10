"""Source-layer adapters for the influencer-persona feature.

One adapter per platform (`app.personas.sources.youtube` today; Phase 5 adds telegram/x). Each
adapter is a thin, stateless translator -- upstream HTTP or a scraping library in, the shapes in
`app.personas.sources.base` out -- the same split `app.market.providers` uses and for the same
reason: the vault-building and summarisation code above this layer should never need to know
whether a failure came from `httpx`, `yt_dlp` or `youtube_transcript_api`, only whether it is
worth retrying (`SourceUnavailable`), permanent (`SourceNotFound`), or specific to captions
(`TranscriptUnavailable`).
"""

from __future__ import annotations
