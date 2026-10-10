"""Application service for personas: the one module the router calls into.

This is the integration layer. It owns the sequencing -- resolve a handle, list a channel, skip what
is already ingested, fetch a transcript, summarise it, validate the symbols, write the note, update
the persona -- while each step's actual work lives in a sibling module (`sources.youtube`, `store`,
`summarize`, `tickers`, `jobs`). The router above it stays a thin translation of exceptions to status
codes.

**Why the ingest dependencies are imported inside functions, not at module scope.** `app.agents.
client` established this rule for `anthropic`: a package that is only needed on one code path must not
be able to break every other path by failing to import. `yt-dlp` and `youtube-transcript-api` are
exactly that -- they are only reachable through an ingest, and an environment missing one (a container
built without them, a partial install) should lose ingesting, not lose the whole API including the
routes that read notes already on disk. A missing import surfaces as a `PersonaError` on the ingest
route naming the package, rather than as an application that will not start.

**Why a card is assembled from stored notes and makes no model call.** Rendering `/personas` must be
free and instant, and it must work with the network down. Everything a card shows was already computed
once, at ingest time, and written into the note. Synthesising a fresh cross-note narrative is a real
feature but it is Phase 2's consolidation step, which runs deliberately and writes its result to
`profile.md` -- not something a page load should trigger.

**Why a fully-failed ingest is reported as failed.** Per-item resilience (one dead video does not stop
the other nineteen) is correct, but on its own it hides total failure: a loop that fails every single
item still finishes "succeeded" with a zero count, which reads as "that channel had nothing new"
rather than "nothing worked". So the worker below tracks both counters and finishes `failed` when it
completed zero items and failed at least one, quoting the last error.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import threading
import uuid
from collections.abc import Callable, Sequence
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from app.config import Settings
from app.personas import jobs as jobs_module
from app.personas.models import (
    CardCritique,
    ChatContext,
    ChatThread,
    ChatTurn,
    DigestCard,
    DigestWarning,
    EpisodicNote,
    FollowedSource,
    InfluencerWatchlist,
    IngestJob,
    Persona,
    PersonaAnswer,
    PersonaBacktest,
    PersonaBook,
    PersonaProfile,
    PersonaRegime,
    PersonaScorecard,
    PersonaTimeline,
    ProfileDiff,
    RegimeConsensus,
    RegimeView,
    SavedStrategyDraft,
    StrategyCardDraft,
    TickerMention,
    TickerThesis,
    slugify,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Imported for annotations only, never at runtime: these are the ingest-path modules this file
    # deliberately imports inside functions (see the module docstring), and a module-scope import
    # here would reintroduce exactly the hard dependency that indirection exists to avoid.
    from pathlib import Path

    from app.agents.models import AgentBudget
    from app.personas.chat import ChatStore
    from app.personas.profile_store import ProfileStore
    from app.personas.store import VaultStore
    from app.personas.summarize import SummaryResult
    from app.tournament.models import StrategyCard

__all__ = [
    "PersonaError",
    "add_persona",
    "add_source",
    "delete_persona",
    "get_ingest",
    "get_note",
    "get_persona",
    "list_cards",
    "list_notes",
    "list_personas",
    "remove_source",
    "start_ingest",
]

logger = logging.getLogger(__name__)

#: How many of a persona's newest notes a `DigestCard` summarises. Ten is roughly a month of a
#: daily-posting channel and a season of a weekly one, which is the window a reader glancing at the
#: page before trading actually cares about. Older notes stay in the vault and are still served by
#: `GET /{slug}/notes`; they simply do not shape the card.
_CARD_NOTES = 10

#: Cap on the bullets and chips a single card renders, so one unusually verbose ingest cannot produce
#: a card thirty items long that buries the other personas.
_CARD_THEMES = 5
_CARD_MENTIONS = 12

#: The owner's current per-channel backfill request. Clamped by `Settings.persona_backfill_max`.
_DEFAULT_INGEST_LIMIT = 20

# Sentence terminators, ASCII plus three CJK ones written as escapes: U+3002 ideographic full stop,
# U+FF1F fullwidth question mark, U+FF01 fullwidth exclamation mark. Escapes rather than literals
# because the fullwidth pair is visually indistinguishable from its ASCII counterpart in a diff, and
# this repo's linter rejects the ambiguity outright. They belong here at all because a summary
# written in Korean -- what `INVDASH_PERSONA_SUMMARY_LANG=ko` produces, and four of the five seed
# channels are Korean -- ends its sentences on these, so an ASCII-only rule would hand the card an
# entire paragraph as its one-sentence headline.
_SENTENCE_END = re.compile("(?<=[.!?\u3002\uff1f\uff01])\\s+")


class PersonaError(RuntimeError):
    """A domain error the router maps to an HTTP status. `status_code` carries the mapping so the
    router stays a one-liner (`raise HTTPException(exc.status_code, str(exc))`)."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _store(settings: Settings) -> VaultStore:
    from app.personas.store import VaultStore as _VaultStore

    return _VaultStore(settings)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


# --- reads -----------------------------------------------------------------


def list_personas(settings: Settings) -> Sequence[Persona]:
    return _store(settings).list_personas()


def get_persona(settings: Settings, slug: str) -> Persona | None:
    return _store(settings).load_persona(slug)


def list_notes(settings: Settings, slug: str) -> Sequence[EpisodicNote]:
    return _store(settings).list_notes(slug)


def get_note(settings: Settings, slug: str, note_id: str) -> EpisodicNote | None:
    return _store(settings).load_note(slug, note_id)


def get_ingest(settings: Settings, slug: str, job_id: str) -> IngestJob | None:
    job = jobs_module.registry().get(job_id)
    if job is None or job.persona != slug:
        return None
    return job


def list_cards(settings: Settings) -> Sequence[DigestCard]:
    """One card per persona, assembled entirely from stored notes. Always answers -- a persona whose
    notes cannot be read contributes a card carrying a warning, never an exception, so one damaged
    vault directory cannot blank the page for every other persona."""
    store = _store(settings)
    cards: list[DigestCard] = []
    for persona in store.list_personas():
        try:
            notes = tuple(store.list_notes(persona.slug))
            warnings: tuple[DigestWarning, ...] = ()
        except Exception as exc:
            logger.warning("personas: could not read notes for %s", persona.slug, exc_info=True)
            notes = ()
            warnings = (DigestWarning(source="vault", reason=f"could not read notes: {exc}"),)
        cards.append(_build_card(persona, notes, warnings))
    return tuple(cards)


def _build_card(
    persona: Persona,
    notes: Sequence[EpisodicNote],
    warnings: tuple[DigestWarning, ...],
) -> DigestCard:
    """Fold a persona's newest notes into the card the page renders.

    An empty note list is a valid, non-error state and produces an empty card -- a persona that has
    been added but not yet ingested is exactly that, and rendering it as an error would tell the owner
    something is broken when nothing is.
    """
    from app.agentdesk.models import GroundingVerdict

    window = tuple(notes[:_CARD_NOTES])
    if not window:
        return DigestCard(
            persona=persona,
            as_of=None,
            window_start=None,
            note_count=0,
            headline="",
            themes=(),
            mentions=(),
            latest_note=None,
            grounding=GroundingVerdict(ok=True),
            warnings=warnings,
        )

    newest = window[0]
    dates = [n.published or n.ingested_at for n in window]

    # Themes and mentions are folded newest-first so the most recent statement wins a tie: if they
    # were bullish on a name last month and bearish yesterday, the card must show bearish.
    themes: list[str] = []
    for note in window:
        for theme in note.themes:
            if theme not in themes:
                themes.append(theme)
            if len(themes) >= _CARD_THEMES:
                break
        if len(themes) >= _CARD_THEMES:
            break

    mentions: list[TickerMention] = []
    seen: set[str] = set()
    for note in window:
        for mention in note.mentions:
            if mention.symbol in seen:
                continue
            seen.add(mention.symbol)
            mentions.append(mention)
            if len(mentions) >= _CARD_MENTIONS:
                break
        if len(mentions) >= _CARD_MENTIONS:
            break

    degraded = any(n.degraded for n in window)
    return DigestCard(
        persona=persona,
        as_of=newest.ingested_at,
        window_start=min(dates),
        note_count=len(notes),
        headline=_first_sentence(newest.summary),
        themes=tuple(themes),
        mentions=tuple(mentions),
        latest_note=newest,
        # An aggregate, not a call record -- see `DigestCard.grounding`'s own docstring for why only
        # `ok` and `degraded` are set here.
        grounding=GroundingVerdict(ok=not degraded, degraded=degraded),
        warnings=warnings,
    )


def _first_sentence(text: str) -> str:
    """The headline: the summary's first sentence, or the whole thing when it has only one.

    Splits on CJK sentence punctuation as well as ASCII, because a summary can be written in Korean
    when the owner sets `INVDASH_PERSONA_SUMMARY_LANG=ko` and a period-only rule would return the
    entire paragraph for it.
    """
    stripped = text.strip()
    if not stripped:
        return ""
    parts = _SENTENCE_END.split(stripped, maxsplit=1)
    return parts[0].strip()


# --- persona and source mutations -----------------------------------------


def add_persona(settings: Settings, *, handle: str, platform: str) -> Persona:
    """Create a persona from a handle, resolving it upstream first so the vault directory is named
    from a real channel rather than from whatever the owner typed."""
    if platform not in {"youtube", "manual"}:
        raise PersonaError(f"unsupported platform {platform!r}", status_code=422)

    store = _store(settings)
    source, display_name, slug = _resolve_source(settings, handle=handle, platform=platform)

    if store.load_persona(slug) is not None:
        raise PersonaError(f"persona {slug!r} already exists", status_code=409)

    persona = Persona(
        slug=slug,
        display_name=display_name,
        sources=(source,),
        created_at=_now(),
    )
    store.save_persona(persona)
    return persona


def _resolve_source(
    settings: Settings, *, handle: str, platform: str
) -> tuple[FollowedSource, str, str]:
    """Turn a typed handle into a `FollowedSource`, a display name and a slug.

    **The slug falls back to the channel id, and that fallback is load-bearing.** Four of the five
    seed channels are Korean, and one of them is reachable only as a percent-encoded Korean handle --
    `slugify` collapses non-latin text to the empty string, so naming the vault directory from the
    handle alone would produce a directory called `""` for it. The channel id is always latin,
    always unique, and always available once resolution has succeeded.
    """
    now = _now()
    if platform == "manual":
        slug = slugify(handle)
        if not slug:
            raise PersonaError(
                "a manual persona needs a handle that yields a usable name; "
                f"{handle!r} contains no latin characters",
                status_code=422,
            )
        return (
            FollowedSource(
                source_id=f"manual:{uuid.uuid4().hex[:12]}",
                platform="manual",
                handle=handle,
                channel_id=None,
                url="",
                added_at=now,
            ),
            handle.strip(),
            slug,
        )

    try:
        from app.personas.sources import youtube
        from app.personas.sources.base import SourceError, SourceNotFound
    except ImportError as exc:
        raise PersonaError(
            f"YouTube ingest is unavailable in this environment: {exc}", status_code=503
        ) from exc

    try:
        resolved = youtube.resolve_handle(handle)
    except SourceNotFound as exc:
        raise PersonaError(f"no such YouTube channel: {handle!r}", status_code=404) from exc
    except SourceError as exc:
        raise PersonaError(f"could not reach YouTube to resolve {handle!r}: {exc}", status_code=502) from exc

    slug = slugify(resolved.handle) or slugify(resolved.display_name) or resolved.channel_id.lower()
    return (
        FollowedSource(
            source_id=f"yt:{resolved.channel_id}",
            platform="youtube",
            handle=resolved.handle,
            channel_id=resolved.channel_id,
            url=resolved.url,
            added_at=now,
        ),
        resolved.display_name,
        slug,
    )


def delete_persona(settings: Settings, slug: str) -> bool:
    """Remove a persona and everything under it. Refuses while an ingest is running, rather than
    deleting the directory out from under a thread that is still writing notes into it."""
    active = jobs_module.registry().active(slug)
    if active is not None:
        raise PersonaError(
            f"an ingest is still running for {slug!r} ({active}); cancel or wait for it first",
            status_code=409,
        )
    return _store(settings).delete_persona(slug)


def add_source(settings: Settings, slug: str, *, handle: str, platform: str) -> Persona:
    store = _store(settings)
    persona = store.load_persona(slug)
    if persona is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)

    source, _display, _slug = _resolve_source(settings, handle=handle, platform=platform)
    if any(existing.source_id == source.source_id for existing in persona.sources):
        raise PersonaError(
            f"{slug!r} already follows {source.source_id}", status_code=409
        )
    updated = persona.model_copy(update={"sources": (*persona.sources, source)})
    store.save_persona(updated)
    return updated


def remove_source(settings: Settings, slug: str, source_id: str) -> Persona:
    store = _store(settings)
    persona = store.load_persona(slug)
    if persona is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    remaining = tuple(s for s in persona.sources if s.source_id != source_id)
    if len(remaining) == len(persona.sources):
        raise PersonaError(f"{slug!r} does not follow {source_id!r}", status_code=404)
    updated = persona.model_copy(update={"sources": remaining})
    store.save_persona(updated)
    return updated


# --- ingest ----------------------------------------------------------------


def start_ingest(
    settings: Settings,
    slug: str,
    *,
    limit: int | None,
    video_urls: list[str] | None,
    drop: dict[str, object] | None,
) -> IngestJob:
    """Plan the work, then hand it to a daemon thread.

    Planning happens on the request thread on purpose: listing a channel and skipping already-ingested
    videos is fast, and doing it here means the 202 response already carries a truthful `items_total`
    rather than a zero that fills in later.

    Also checks `app.agents.spend.LEDGER` against `settings.model_spend_daily_cap_usd` before the
    daemon thread is started -- checking inside `_run_ingest` itself would be too late to answer the
    request with anything but a 202 that then fails silently in the background. See
    `app.personas.service.ask`'s docstring for why `SpendCapExceeded` propagates uncaught here rather
    than becoming a `PersonaError`.
    """
    from app.agents.spend import LEDGER

    store = _store(settings)
    persona = store.load_persona(slug)
    if persona is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)

    registry = jobs_module.registry()
    active = registry.active(slug)
    if active is not None:
        raise PersonaError(
            f"an ingest is already running for {slug!r}: {active}", status_code=409
        )

    effective_limit = min(limit or _DEFAULT_INGEST_LIMIT, settings.persona_backfill_max)
    plan = _plan_items(settings, store, persona, limit=effective_limit,
                       video_urls=video_urls, drop=drop)
    if not plan:
        raise PersonaError(
            f"nothing to ingest for {slug!r}: every item found is already in the vault",
            status_code=409,
        )

    LEDGER.check(settings.model_spend_daily_cap_usd)

    def target(cancel: threading.Event, handle: jobs_module.JobHandle) -> None:
        _run_ingest(settings, persona, plan, cancel=cancel, handle=handle)

    try:
        return registry.start(slug, items_total=len(plan), target=target)
    except jobs_module.IngestAlreadyActive as exc:
        # The `registry.active(slug)` check above is not the same lock `start` takes, so two requests
        # for one persona can both pass it and race into `start`, where the loser raises. That is a
        # plain `RuntimeError`, which the router does not translate -- so without this it surfaces as
        # a 500 rather than as the 409 the contract documents for exactly this situation.
        raise PersonaError(
            f"an ingest is already running for {slug!r}: {exc.job_id}", status_code=409
        ) from exc


class _PlannedItem:
    """One unit of ingest work: either a video to fetch, or a piece of text the owner pasted.

    `source_id` travels with the item so the note it produces is attributed to the source it actually
    came from. It has to be carried here rather than read off `persona.sources[0]` at write time: a
    persona can follow several channels, and once every source's videos are flattened into one plan
    there is no way to recover which channel a given video came from after the fact -- so it is
    recorded at the point the plan is built, where that is still known.
    """

    __slots__ = ("note_id", "source_id", "text", "title", "url")

    def __init__(
        self, *, note_id: str, url: str, title: str | None, text: str | None, source_id: str
    ) -> None:
        self.note_id = note_id
        self.url = url
        self.title = title
        self.text = text
        self.source_id = source_id


def _plan_items(
    settings: Settings,
    store: VaultStore,
    persona: Persona,
    *,
    limit: int,
    video_urls: list[str] | None,
    drop: dict[str, object] | None,
) -> tuple[_PlannedItem, ...]:
    if drop is not None:
        text = drop.get("text")
        url = str(drop.get("url") or "")
        title = drop.get("title")
        if not text and not url:
            raise PersonaError("a drop needs either text or a url", status_code=422)
        if not text:
            raise PersonaError(
                "dropping a bare url is not supported yet; paste the text of the post instead",
                status_code=422,
            )
        return (
            _PlannedItem(
                note_id=f"drop-{uuid.uuid4().hex[:10]}",
                url=url,
                title=str(title) if title else None,
                text=str(text),
                source_id=_manual_source_id(persona),
            ),
        )

    try:
        from app.personas.sources import youtube
        from app.personas.sources.base import SourceError
    except ImportError as exc:
        raise PersonaError(
            f"YouTube ingest is unavailable in this environment: {exc}", status_code=503
        ) from exc

    # (video_id, watch url, title-if-known, source_id). The title is None for an explicitly requested
    # video -- the listing that would have carried it was never fetched -- and the summariser is given
    # None rather than a guessed title. The source_id is carried per ref, not read off sources[0]
    # later, so a persona following two channels attributes each note to the channel it came from.
    refs: list[tuple[str, str, str | None, str]] = []
    if video_urls:
        # An explicitly-requested URL is not tied to any one followed channel, so it is attributed to
        # the persona's first YouTube source when there is one, or to a synthetic ad-hoc id otherwise.
        adhoc_source = _youtube_source_id(persona)
        for raw in video_urls:
            video_id = _video_id_from_url(raw)
            if video_id is None:
                raise PersonaError(f"could not read a video id out of {raw!r}", status_code=422)
            refs.append(
                (video_id, f"https://www.youtube.com/watch?v={video_id}", None, adhoc_source)
            )
    else:
        listing_failures: list[str] = []
        listed_any = False
        for source in persona.sources:
            if source.platform != "youtube" or not source.enabled:
                continue
            listed_any = True
            key = source.channel_id or source.handle
            try:
                for ref in youtube.list_videos(key, limit=limit):
                    refs.append((ref.video_id, ref.url, ref.title, source.source_id))
            except SourceError as exc:
                # One unreachable channel must not sink the whole ingest -- that is the same
                # "provider failures degrade to a warning, they do not 5xx" rule `app.api.news`
                # documents and the contract restates. The failure is logged and the other sources
                # still contribute; only if *nothing* could be listed does it become an error.
                listing_failures.append(f"{source.handle!r}: {exc}")
                logger.warning(
                    "personas: could not list videos for %s (%s); skipping that source",
                    source.handle,
                    exc,
                )

        if not refs and listing_failures:
            raise PersonaError(
                "could not list videos from any followed source: " + "; ".join(listing_failures),
                status_code=502,
            )
        if not refs and not listed_any:
            raise PersonaError(
                f"{persona.slug!r} has no enabled YouTube source to back-fill from",
                status_code=422,
            )

    planned = [
        _PlannedItem(note_id=vid, url=url, title=title, text=None, source_id=source_id)
        for vid, url, title, source_id in refs
        if not store.has_note(persona.slug, vid)
    ]
    return tuple(planned[:limit])


def _youtube_source_id(persona: Persona) -> str:
    """The persona's first enabled YouTube source id, or a synthetic ad-hoc id when it has none.
    Used to attribute an explicitly-requested video URL, which is not tied to any followed channel."""
    for source in persona.sources:
        if source.platform == "youtube" and source.enabled:
            return source.source_id
    return "manual:adhoc"


def _manual_source_id(persona: Persona) -> str:
    """The persona's first manual source id, or a synthetic id when it has none -- a pasted drop is
    not required to correspond to a followed source."""
    for source in persona.sources:
        if source.platform == "manual":
            return source.source_id
    return "manual:drop"


_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")


def _video_id_from_url(raw: str) -> str | None:
    candidate = raw.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        return candidate
    match = _VIDEO_ID_RE.search(candidate)
    return match.group(1) if match else None


def _run_ingest(
    settings: Settings,
    persona: Persona,
    plan: Sequence[_PlannedItem],
    *,
    cancel: threading.Event,
    handle: jobs_module.JobHandle,
) -> None:
    """The worker body. Runs on a daemon thread; never raises out (the registry would catch it, but
    finishing with an accurate state here is better than being caught)."""
    from app.agents.models import AgentBudget, BudgetExhausted
    from app.personas.store import VaultStore
    from app.personas.summarize import summarize_item
    from app.personas.tickers import build_symbol_validator

    store = VaultStore(settings)
    validator = build_symbol_validator(settings)
    try:
        cap = Decimal(settings.persona_ingest_cap_usd)
    except (InvalidOperation, ValueError):
        cap = Decimal("2")
        logger.warning(
            "personas: persona_ingest_cap_usd=%r is not a decimal; falling back to %s",
            settings.persona_ingest_cap_usd,
            cap,
        )
    budget = AgentBudget(cap_usd=cap)

    done = 0
    failed = 0
    last_error: str | None = None
    current = persona

    for item in plan:
        if cancel.is_set():
            handle.finish(state="cancelled")
            return
        try:
            note, budget = _ingest_one(
                settings,
                current,
                item,
                store=store,
                budget=budget,
                summarize=summarize_item,
                validator=validator,
            )
        except BudgetExhausted as exc:
            # The cap is reached. `BudgetExhausted` carries the true accumulated spend -- including
            # the spend of a grounding retry whose SummaryResult we never received -- so reconcile the
            # running total to it rather than reporting the pre-item figure, which would under-count
            # and make the cap look un-exceeded. Then stop: every remaining item would raise this
            # immediately, and fetching their transcripts first would just waste requests.
            budget = budget.model_copy(update={"spent_usd": exc.spent_usd})
            handle.progress(done=done, failed=failed, spent_usd=str(budget.spent_usd))
            store.append_log(
                current.slug,
                f"stopped at budget cap: spent {exc.spent_usd} of {exc.cap_usd}; "
                f"{len(plan) - done - failed} item(s) not attempted",
            )
            state = "succeeded" if done > 0 else "failed"
            error = None if done > 0 else f"budget cap reached before any item completed: {exc}"
            handle.finish(state=state, error=error)
            return
        except Exception as exc:
            failed += 1
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "personas: item %s for %s failed", item.note_id, current.slug, exc_info=True
            )
            store.append_log(current.slug, f"FAILED {item.note_id}: {last_error}")
        else:
            done += 1
            current = _record_note(store, current, note)
            store.append_log(
                current.slug,
                f"ingested {note.note_id} ({len(note.mentions)} tickers, spent {budget.spent_usd})",
            )
        handle.progress(done=done, failed=failed, spent_usd=str(budget.spent_usd))

    # Per-item resilience must not disguise a total failure -- see the module docstring.
    if done == 0 and failed > 0:
        handle.finish(
            state="failed",
            error=f"every one of the {failed} item(s) failed; last error: {last_error}",
        )


def _ingest_one(
    settings: Settings,
    persona: Persona,
    item: _PlannedItem,
    *,
    store: VaultStore,
    budget: AgentBudget,
    summarize: Callable[..., SummaryResult],
    validator: Callable[[str], bool],
) -> tuple[EpisodicNote, AgentBudget]:
    """Fetch, summarise and persist one item. Returns the written note and the updated budget.

    `summarize` is injected rather than imported here so a test can exercise the whole ingest path --
    planning, fetching, note writing, persona bookkeeping -- without a model call. It is typed
    `Callable[..., SummaryResult]` rather than with an exact signature because it is always
    `app.personas.summarize.summarize_item`, whose keyword-only parameters would otherwise have to be
    restated here and kept in sync for no benefit.
    """
    from app.personas.sources import youtube

    # The source is carried on the item (set when the plan was built), not read off
    # `persona.sources[0]` here -- that would attribute every note in a multi-source persona to the
    # first source regardless of which channel actually produced it.
    source_id = item.source_id
    published: dt.datetime | None = None
    lang = ""
    transcript_source = None
    kind = "manual"
    text = item.text
    title = item.title

    if text is None:
        fetched = youtube.fetch_transcript(item.note_id)
        text = fetched.text
        lang = fetched.lang
        transcript_source = "auto" if fetched.generated else "manual"
        kind = "video_transcript"
        # A separate, slower call: the flat listing carries no upload date at all, and `published`
        # stays None rather than borrowing `ingested_at` when even this cannot answer.
        try:
            meta = youtube.fetch_video_meta(item.note_id)
            published = meta.published
            title = title or meta.title
        except Exception:
            logger.info(
                "personas: no upload date for %s; leaving published unset", item.note_id,
                exc_info=True,
            )

    result = summarize(
        text=text,
        title=title,
        url=item.url,
        settings=settings,
        budget=budget,
        lang=lang,
        symbol_validator=validator,
    )

    note = EpisodicNote(
        note_id=item.note_id,
        persona=persona.slug,
        source_id=source_id,
        published=published,
        ingested_at=_now(),
        url=item.url,
        title=title,
        kind=kind,  # type: ignore[arg-type]
        transcript_source=transcript_source,  # type: ignore[arg-type]
        lang=lang,
        summary=result.draft.summary,
        themes=tuple(result.draft.themes),
        quotes=tuple(result.draft.quotes),
        mentions=tuple(result.draft.mentions),
        path="",  # filled in below from the path the store actually wrote
        degraded=bool(result.verdict.degraded),
    )
    written = store.write_note(note, transcript_text=text)
    vault_relative = _vault_relative(settings, written)
    return note.model_copy(update={"path": vault_relative}), result.budget


def _vault_relative(settings: Settings, path: Path) -> str:
    """The note's path as the API reports it: relative to the vault root, posix-separated.

    Falls back to the absolute path only when the file somehow sits outside the vault, which should
    be impossible -- but returning an absolute Windows path is still better than raising here and
    failing an ingest that has already written its note successfully.
    """
    try:
        return path.relative_to(settings.vault_dir).as_posix()
    except ValueError:
        return path.as_posix()


def _record_note(store: VaultStore, persona: Persona, note: EpisodicNote) -> Persona:
    """Fold one new note into the persona record: bump the count, and put its symbols at the front of
    `tickers` so the most recently discussed names lead.

    **Reloads the persona from disk first, and this is load-bearing.** The ingest worker holds an
    in-memory `persona` from the moment the job started, but the owner can `add_source` or
    `remove_source` while the ingest runs -- those write `persona.json` directly. If this folded the
    note into the stale in-memory copy and saved that, it would silently revert the owner's source
    change (a lost update). Reloading means the count/tickers delta lands on top of whatever the
    current on-disk record is, including any source edit made mid-ingest.

    The reload is safe against exactly one writer besides this one: the API's source mutations. Two
    ingests of the same persona cannot race here because the job registry allows only one active
    ingest per slug. If the persona was deleted mid-ingest, `load_persona` returns `None` and we fall
    back to the in-memory copy, which `save_persona` will recreate -- a deleted-then-resurrected
    persona is odd but not corrupt, and the alternative (crashing the worker) is worse.
    """
    fresh = store.load_persona(persona.slug) or persona
    symbols = [m.symbol for m in note.mentions]
    merged = list(dict.fromkeys([*symbols, *fresh.tickers]))
    updated = fresh.model_copy(
        update={"note_count": fresh.note_count + 1, "tickers": tuple(merged)}
    )
    store.save_persona(updated)
    return updated


# --- Phase 2: consolidation ------------------------------------------------


def _profile_store(settings: Settings) -> ProfileStore:
    from app.personas.profile_store import ProfileStore as _ProfileStore

    return _ProfileStore(settings)


def consolidate(settings: Settings, slug: str, *, incremental: bool = False) -> PersonaProfile:
    """Fold a persona's notes into a fresh `PersonaProfile`, archiving the previous version.

    Synchronous, unlike ingest: one model call over notes already on disk. Empty-notes is a 409, not
    a silent empty profile -- there is nothing to consolidate. `AgentUnavailable`/`BudgetExhausted`
    become honest HTTP statuses rather than a 500. The version increments off whatever the store
    currently holds (reloaded here, not carried), so two callers cannot both write version N.

    `incremental` (P1.1): when true AND a prior profile exists, consolidate only the notes newer than
    `prior.consolidated_at` and fold them into the standing profile, so cost stops scaling with vault
    size. Falls back to a full consolidation when there is no prior profile, or when nothing is new
    (re-running incremental with no new notes would otherwise 409 on an empty set). `note_count`
    reflects the whole vault either way -- the profile still describes all the persona's notes.

    Also checks `app.agents.spend.LEDGER` against `settings.model_spend_daily_cap_usd` before the model
    call -- see `app.personas.service.ask`'s docstring for why `SpendCapExceeded` propagates uncaught
    here rather than becoming a `PersonaError`.
    """
    from decimal import Decimal, InvalidOperation

    from app.agents.models import AgentBudget, AgentUnavailable, BudgetExhausted
    from app.agents.spend import LEDGER
    from app.personas.consolidate import consolidate_notes

    store = _store(settings)
    persona = store.load_persona(slug)
    if persona is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)

    all_notes = tuple(store.list_notes(slug))
    if not all_notes:
        raise PersonaError(
            f"{slug!r} has no notes to consolidate yet -- ingest some first", status_code=409
        )

    profiles = _profile_store(settings)
    prev = profiles.load_profile(slug)

    # Incremental: only notes INGESTED since the standing profile, folded into it. Keyed on
    # `ingested_at`, never `published`: a deep backfill adds OLD videos (old publication dates) to the
    # vault now, and keying on publication date would wrongly treat every backfilled note as already
    # covered and skip it. If nothing is new, fall back to a full pass rather than 409 on an empty set
    # (a re-run is idempotent, not an error).
    prior_profile = None
    notes = all_notes
    if incremental and prev is not None:
        cutoff = prev.consolidated_at
        newer = tuple(n for n in all_notes if n.ingested_at > cutoff)
        if newer:
            prior_profile = prev
            notes = newer

    try:
        cap = Decimal(settings.persona_ingest_cap_usd)
    except (InvalidOperation, ValueError):
        cap = Decimal("5")

    LEDGER.check(settings.model_spend_daily_cap_usd)

    try:
        result = consolidate_notes(
            persona_slug=slug, notes=notes, settings=settings,
            budget=AgentBudget(cap_usd=cap), prior_profile=prior_profile,
        )
    except BudgetExhausted as exc:
        raise PersonaError(
            f"consolidation reached the ${exc.cap_usd} budget cap before completing", status_code=409
        ) from exc
    except AgentUnavailable as exc:
        raise PersonaError(f"model unavailable for consolidation: {exc}", status_code=503) from exc

    now = _now()
    profile = PersonaProfile(
        persona=slug,
        version=(prev.version + 1) if prev is not None else 1,
        consolidated_at=now,
        note_count=len(all_notes),
        summary=result.draft.summary,
        beliefs=result.draft.beliefs,
        playbook=result.draft.playbook,
        methodology=result.draft.methodology,
        regime=result.draft.regime if result.draft.regime.has_signal else None,
        vocabulary=result.draft.vocabulary,
        degraded=bool(result.verdict.degraded),
        path="",  # the store derives and owns the real path
    )
    saved = profiles.save_profile(profile)
    profile = profile.model_copy(update={"path": _vault_relative(settings, saved)})

    # Per-symbol theses are a plain overwrite (one running view per ticker; the contract keeps history
    # for the profile, not for theses). Their `updated_at` comes from the notes, set in consolidate.
    for thesis in result.theses:
        profiles.save_thesis(thesis)

    store.save_persona(
        persona.model_copy(update={"profile_version": profile.version, "consolidated_at": now})
    )
    return profile


def get_profile(settings: Settings, slug: str) -> PersonaProfile | None:
    return _profile_store(settings).load_profile(slug)


def list_theses(settings: Settings, slug: str) -> Sequence[TickerThesis]:
    return _profile_store(settings).list_theses(slug)


def get_thesis(settings: Settings, slug: str, symbol: str) -> TickerThesis | None:
    return _profile_store(settings).load_thesis(slug, symbol)


# --- Phase 3a: call scoring ------------------------------------------------


def scorecard(settings: Settings, slug: str) -> PersonaScorecard:
    """Score a persona's dated ticker calls against what the market did since -- descriptive, never
    predictive. Unknown persona is a 404; everything else answers 200, degrading to stored bar data
    (and per-symbol `no_data` warnings) rather than 5xx-ing when a price series cannot be fetched."""
    from app.personas.scoring import score_calls

    store = _store(settings)
    persona = store.load_persona(slug)
    if persona is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    notes = tuple(store.list_notes(slug))
    return score_calls(persona_slug=slug, notes=notes, settings=settings)


def backtest(settings: Settings, slug: str) -> PersonaBacktest:
    """The descriptive backtest lens: did following the persona's dated calls beat holding SPY? 404
    for an unknown persona; a known persona with no directional calls yields empty horizons, not an
    error. Reuses `score_calls` and adds one SPY fetch; degrades (warnings) rather than 5xx."""
    from app.personas.backtest import run_backtest

    store = _store(settings)
    persona = store.load_persona(slug)
    if persona is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    notes = tuple(store.list_notes(slug))
    return run_backtest(persona_slug=slug, notes=notes, settings=settings)


# --- Phase 6: persona paper book (Paper Desk) ------------------------------


def _current_bullish_tickers(notes: Sequence[EpisodicNote]) -> tuple[str, ...]:
    """Symbols whose most recent mention across the persona's notes is bullish (latest-stance-wins),
    the same current-holdings rule the paper book and watchlist use, restated inline to avoid coupling
    to their private helpers."""
    latest: dict[str, tuple[dt.datetime, str]] = {}
    for note in notes:
        said = note.published or note.ingested_at
        for m in note.mentions:
            prev = latest.get(m.symbol)
            if prev is None or said >= prev[0]:
                latest[m.symbol] = (said, m.stance)
    return tuple(sorted(sym for sym, (_said, stance) in latest.items() if stance == "bullish"))


def strategy_card(settings: Settings, slug: str) -> StrategyCardDraft:
    """Map a persona's methodology onto the rule vocabulary and realise a validated StrategyCard draft
    (Phase 7c). Exploration lens, not advice. 404 unknown persona; 409 when the persona has no
    consolidated methodology to map or no current-bullish tickers; 503/409 model/budget.

    Also checks `app.agents.spend.LEDGER` against `settings.model_spend_daily_cap_usd` before the model
    call -- see `app.personas.service.ask`'s docstring for why `SpendCapExceeded` propagates uncaught
    here rather than becoming a `PersonaError`.
    """
    from decimal import Decimal, InvalidOperation

    from app.agents.models import AgentBudget, AgentUnavailable, BudgetExhausted
    from app.agents.spend import LEDGER
    from app.personas.strategy import draft_strategy_card, save_draft

    store = _store(settings)
    persona = store.load_persona(slug)
    if persona is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    profile = _profile_store(settings).load_profile(slug)
    if profile is None or not profile.methodology:
        raise PersonaError(
            f"{slug!r} has no consolidated methodology to map into a strategy -- consolidate first, "
            "or it is a pure commentator with no described technique",
            status_code=409,
        )
    notes = tuple(store.list_notes(slug))
    bullish = _current_bullish_tickers(notes)
    if not bullish:
        raise PersonaError(f"{slug!r} has no current-bullish tickers to trade", status_code=409)

    try:
        cap = Decimal(settings.persona_ingest_cap_usd)
    except (InvalidOperation, ValueError):
        cap = Decimal("5")
    LEDGER.check(settings.model_spend_daily_cap_usd)
    try:
        result = draft_strategy_card(
            persona_slug=slug, profile=profile, bullish_tickers=bullish,
            settings=settings, budget=AgentBudget(cap_usd=cap),
        )
    except BudgetExhausted as exc:
        raise PersonaError(f"card drafting reached the ${exc.cap_usd} budget cap", status_code=409) from exc
    except AgentUnavailable as exc:
        raise PersonaError(f"model unavailable: {exc}", status_code=503) from exc
    # Persist a MAPPED draft so the owner can re-open the exact card they saw (drafting is
    # non-deterministic). An unmapped result is not saved -- there is no card to keep. `save_draft`
    # stamps the version and returns the draft as stored.
    if result.draft.mapped:
        return save_draft(slug, result.draft, settings).draft
    return result.draft


def saved_strategy_cards(settings: Settings, slug: str) -> Sequence[SavedStrategyDraft]:
    """Every persisted strategy-card draft for a persona, newest first. 404 unknown persona; an empty
    tuple when none have been drafted yet."""
    from app.personas.strategy import list_saved_drafts

    store = _store(settings)
    if store.load_persona(slug) is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    return list_saved_drafts(slug, settings)


def promote_strategy_card(settings: Settings, slug: str, version: int) -> StrategyCard:
    """Promote a persona's saved strategy-card draft onto the competition library shelf as a scorable
    candidate (`app.personas.promotion`). Returns the written `app.tournament.models.StrategyCard`.

    404 unknown persona, or no saved draft at that version; 422 a draft that mapped no card (nothing
    to promote); 409 the card is already on the shelf (a hash-stable re-promote of the same version).
    """
    from app.personas import promotion
    from app.personas.strategy import list_saved_drafts

    store = _store(settings)
    if store.load_persona(slug) is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)

    saved = next((s for s in list_saved_drafts(slug, settings) if s.draft.version == version), None)
    if saved is None:
        raise PersonaError(
            f"persona {slug!r} has no saved strategy-card draft at version {version}", status_code=404
        )

    try:
        result = promotion.promote_draft(saved, settings=settings)
    except promotion.NotPromotable as exc:
        raise PersonaError(str(exc), status_code=422) from exc

    if not result.created:
        raise PersonaError(
            f"{result.card.agent_id} is already on the library shelf; promoting this draft again "
            "changes nothing",
            status_code=409,
        )
    return result.card


def critique(settings: Settings, slug: str, *, card: dict[str, object]) -> CardCritique:
    """A persona's in-voice, grounded assessment of a strategy card (P3). 404 unknown persona; a
    persona with no consolidated profile returns a `cannot_say` critique, not an error. 503/409
    model/budget.

    Also checks `app.agents.spend.LEDGER` against `settings.model_spend_daily_cap_usd` before the model
    call -- see `app.personas.service.ask`'s docstring for why `SpendCapExceeded` propagates uncaught
    here rather than becoming a `PersonaError`.
    """
    from decimal import Decimal, InvalidOperation

    from app.agents.models import AgentBudget, AgentUnavailable, BudgetExhausted
    from app.agents.spend import LEDGER
    from app.personas.critique import critique_card

    store = _store(settings)
    if store.load_persona(slug) is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    profile = _profile_store(settings).load_profile(slug)
    try:
        cap = Decimal(settings.persona_ingest_cap_usd)
    except (InvalidOperation, ValueError):
        cap = Decimal("5")
    LEDGER.check(settings.model_spend_daily_cap_usd)
    try:
        result = critique_card(
            persona_slug=slug, profile=profile, card=card,
            settings=settings, budget=AgentBudget(cap_usd=cap),
        )
    except BudgetExhausted as exc:
        raise PersonaError(f"critique reached the ${exc.cap_usd} budget cap", status_code=409) from exc
    except AgentUnavailable as exc:
        raise PersonaError(f"model unavailable: {exc}", status_code=503) from exc
    return result.critique


def profile_diff(settings: Settings, slug: str, *, from_version: int, to_version: int) -> ProfileDiff:
    """What changed in a persona's memory between two consolidations (P2.3). 404 unknown persona or
    unknown version."""
    from app.personas.drift import diff_profiles

    store = _store(settings)
    if store.load_persona(slug) is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    profiles = _profile_store(settings)
    a = profiles.load_version(slug, from_version)
    b = profiles.load_version(slug, to_version)
    if a is None:
        raise PersonaError(f"{slug!r} has no profile version {from_version}", status_code=404)
    if b is None:
        raise PersonaError(f"{slug!r} has no profile version {to_version}", status_code=404)
    return diff_profiles(a, b)


def regime(settings: Settings) -> RegimeConsensus:
    """The cross-persona macro picture (P2.1): each persona's structured regime view, plus a risk-on/
    off tally. A reference the strategy layer MAY cite, never a signal. Always answers."""
    store = _store(settings)
    profiles = _profile_store(settings)
    rows: list[PersonaRegime] = []
    risk_on = risk_off = mixed = 0
    for persona in store.list_personas():
        profile = profiles.load_profile(persona.slug)
        view = profile.regime if (profile and profile.regime) else RegimeView()
        has = bool(profile and profile.regime and profile.regime.has_signal)
        if has:
            if view.risk == "on":
                risk_on += 1
            elif view.risk == "off":
                risk_off += 1
            elif view.risk == "mixed":
                mixed += 1
        rows.append(
            PersonaRegime(
                persona=persona.slug, display_name=persona.display_name, view=view,
                has_view=has, as_of=profile.consolidated_at if profile else None,
            )
        )
    return RegimeConsensus(
        as_of=_now(), personas=tuple(rows), risk_on=risk_on, risk_off=risk_off, mixed=mixed,
        caveat=(
            "What the followed commentators' recent videos imply about the macro backdrop -- a "
            "reference the strategy layer may cite, never a trading signal or advice."
        ),
    )


def watchlist(settings: Settings, *, as_of: dt.date | None = None) -> InfluencerWatchlist:
    """The cross-persona consensus watchlist: tickers the followed influencers are currently bullish
    on, aggregated. A descriptive reference for the strategy layer or the owner, never a buy list.
    `as_of` (P0.1) returns the consensus as it was known on that date -- a point-in-time universe with
    no look-ahead, the honest counterpart to the biased "as of now" default."""
    from app.personas.stances import consensus_as_of
    from app.personas.watchlist import build_watchlist, with_instruments

    store = _store(settings)
    personas = [(p, tuple(store.list_notes(p.slug))) for p in store.list_personas()]
    if as_of is None:
        return build_watchlist(personas=personas)
    return with_instruments(consensus_as_of(personas, as_of=as_of))


def persona_books(settings: Settings) -> list[PersonaBook]:
    """One current-holdings paper book per persona, for the Paper Desk. Always answers; a persona
    whose notes cannot be read still yields an (empty) book rather than failing the whole page."""
    from app.personas.paperbook import build_persona_book

    store = _store(settings)
    out: list[PersonaBook] = []
    for persona in store.list_personas():
        try:
            notes = tuple(store.list_notes(persona.slug))
        except Exception:
            logger.warning("personas: could not read notes for %s book", persona.slug, exc_info=True)
            notes = ()
        out.append(build_persona_book(persona=persona, notes=notes, settings=settings))
    return out


def persona_book(
    settings: Settings, slug: str, *, as_of: dt.date | None = None, exclude_intraday: bool = False
) -> PersonaBook:
    """One persona's current-holdings paper book. 404 for an unknown persona. `as_of` (P0.1) prices the
    book point-in-time (universe and marks as known on that date, no look-ahead); `exclude_intraday`
    drops scalp-horizon calls that are not really holdings. Both default to the current behaviour."""
    from app.personas.paperbook import build_persona_book

    store = _store(settings)
    persona = store.load_persona(slug)
    if persona is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    notes = tuple(store.list_notes(slug))
    return build_persona_book(
        persona=persona, notes=notes, settings=settings,
        as_of=as_of, exclude_intraday=exclude_intraday,
    )


def timeline(settings: Settings, slug: str) -> PersonaTimeline:
    """The persona's notes as a dated timeline plus per-symbol stance evolution -- a pure read over
    stored notes, no model call, no market fetch. 404 for an unknown persona; empty entries when a
    known persona has no notes yet."""
    from app.personas.timeline import build_timeline

    store = _store(settings)
    persona = store.load_persona(slug)
    if persona is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    notes = tuple(store.list_notes(slug))
    return build_timeline(persona_slug=slug, notes=notes)


def ask(settings: Settings, slug: str, *, question: str, symbol: str | None) -> PersonaAnswer:
    """Answer a question in the persona's voice, grounded in its own profile + notes. 404 unknown
    persona; 409 when it has no notes to answer from; 503/409 for model-unavailable/budget. One
    grounded model call, capped by `persona_ingest_cap_usd`.

    Also checks `app.agents.spend.LEDGER` against `settings.model_spend_daily_cap_usd` before the model
    call -- `app.agents.spend.SpendCapExceeded` propagates uncaught (unlike `BudgetExhausted`/
    `AgentUnavailable` above, it is not translated to a `PersonaError` here, since `app.api.personas`
    cannot be edited to catch a new exception type; a process-wide `app.agents.spend_http` handler maps
    it to `429` instead). See that setting's own docstring for why this is a separate, aggregate cap.
    """
    from decimal import Decimal, InvalidOperation

    from app.agents.models import AgentBudget, AgentUnavailable, BudgetExhausted
    from app.agents.spend import LEDGER
    from app.personas.ask import ask_persona

    store = _store(settings)
    persona = store.load_persona(slug)
    if persona is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    notes = tuple(store.list_notes(slug))
    if not notes:
        raise PersonaError(
            f"{slug!r} has no notes to answer from yet -- ingest some first", status_code=409
        )
    profile = _profile_store(settings).load_profile(slug)

    try:
        cap = Decimal(settings.persona_ingest_cap_usd)
    except (InvalidOperation, ValueError):
        cap = Decimal("5")

    LEDGER.check(settings.model_spend_daily_cap_usd)

    try:
        result = ask_persona(
            persona_slug=slug,
            question=question,
            symbol=(symbol.strip().upper() or None) if symbol else None,
            profile=profile,
            notes=notes,
            settings=settings,
            budget=AgentBudget(cap_usd=cap),
        )
    except BudgetExhausted as exc:
        raise PersonaError(
            f"answering reached the ${exc.cap_usd} budget cap", status_code=409
        ) from exc
    except AgentUnavailable as exc:
        raise PersonaError(f"model unavailable: {exc}", status_code=503) from exc
    return result.answer


# --- Phase 9: persona chat ---------------------------------------------------


def _chat_store(settings: Settings) -> ChatStore:
    from app.personas.chat import ChatStore as _ChatStore

    return _ChatStore(settings)


def list_chats(settings: Settings, slug: str) -> tuple[ChatThread, ...]:
    """Every persisted chat thread for `slug`, `turns=()`, newest `updated_at` first. 404 unknown
    persona -- an empty result is the honest answer for a known persona with no threads yet."""
    if _store(settings).load_persona(slug) is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    return _chat_store(settings).list_threads(slug)


def create_chat(settings: Settings, slug: str) -> ChatThread:
    """A fresh, empty chat thread for `slug`. 404 unknown persona. `title` starts empty (see
    `ChatThread`'s own docstring) and is filled in from the first turn's question by `chat_turn`
    below."""
    if _store(settings).load_persona(slug) is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    now = _now()
    thread = ChatThread(
        thread_id=uuid.uuid4().hex, persona=slug, title="", created_at=now, updated_at=now,
    )
    _chat_store(settings).save_thread(thread)
    return thread


def get_chat(settings: Settings, slug: str, thread_id: str) -> ChatThread:
    """One chat thread, full turns included, oldest first. 404 unknown persona or unknown thread."""
    if _store(settings).load_persona(slug) is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    thread = _chat_store(settings).load_thread(slug, thread_id)
    if thread is None:
        raise PersonaError(f"no chat thread {thread_id!r} for persona {slug!r}", status_code=404)
    return thread


def delete_chat(settings: Settings, slug: str, thread_id: str) -> None:
    """Delete one chat thread. 404 unknown persona or unknown thread -- unlike
    `VaultStore.delete_persona`'s idempotent-`bool` shape, a thread the caller cannot even name (an
    unknown persona) or that never existed is a genuine 404 here, matching the contract's own error
    table for this route."""
    if _store(settings).load_persona(slug) is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    if not _chat_store(settings).delete_thread(slug, thread_id):
        raise PersonaError(f"no chat thread {thread_id!r} for persona {slug!r}", status_code=404)


def chat_context(settings: Settings, slug: str) -> ChatContext:
    """Whether the persona's consolidated profile is stale relative to the notes actually on disk --
    never consolidated, or consolidated over fewer notes than now exist. 404 unknown persona."""
    store = _store(settings)
    if store.load_persona(slug) is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)
    note_count = len(store.list_notes(slug))
    profile = _profile_store(settings).load_profile(slug)
    profile_version = profile.version if profile is not None else 0
    profile_note_count = profile.note_count if profile is not None else 0
    stale = profile is None or note_count > profile_note_count
    return ChatContext(
        profile_version=profile_version, profile_note_count=profile_note_count,
        note_count=note_count, stale=stale,
    )


def chat_turn(
    settings: Settings, slug: str, *, thread_id: str, question: str, symbol: str | None, lang: str,
) -> ChatTurn:
    """Answer one turn in a persisted chat thread, grounded in the persona's own profile + notes plus
    the thread's own recent, non-degraded history (`app.personas.chat.chat_turn`). 404 unknown
    persona/thread; 409 no notes to answer from / thread turn cap
    (`app.personas.chat.MAX_TURNS`) / thread budget cap (`persona_chat_cap_usd`); 503 model
    unavailable. Synchronous -- one grounded call, capped per the contract's pinned "Budget" rule.

    Also checks `app.agents.spend.LEDGER` against `settings.model_spend_daily_cap_usd` before the
    model call -- `app.agents.spend.SpendCapExceeded` propagates uncaught, same as `ask` above and for
    the same reason (see that function's own docstring): a process-wide `app.agents.spend_http`
    handler maps it to `429` instead of a `PersonaError` this router could catch.
    """
    from app.agents.models import AgentBudget, AgentUnavailable, BudgetExhausted
    from app.agents.spend import LEDGER
    from app.personas.chat import MAX_TURNS
    from app.personas.chat import chat_turn as _run_chat_turn

    store = _store(settings)
    persona = store.load_persona(slug)
    if persona is None:
        raise PersonaError(f"no persona {slug!r}", status_code=404)

    chat_store = _chat_store(settings)
    thread = chat_store.load_thread(slug, thread_id)
    if thread is None:
        raise PersonaError(f"no chat thread {thread_id!r} for persona {slug!r}", status_code=404)

    notes = tuple(store.list_notes(slug))
    if not notes:
        raise PersonaError(
            f"{slug!r} has no notes to answer from yet -- ingest some first", status_code=409
        )

    if len(thread.turns) >= MAX_TURNS:
        raise PersonaError("thread turn cap reached; start a new thread", status_code=409)

    try:
        cap = Decimal(settings.persona_chat_cap_usd)
    except (InvalidOperation, ValueError):
        cap = Decimal("2")

    spent = Decimal(thread.spent_usd)
    if spent >= cap:
        raise PersonaError("thread budget cap reached", status_code=409)

    profile = _profile_store(settings).load_profile(slug)

    LEDGER.check(settings.model_spend_daily_cap_usd)

    try:
        result = _run_chat_turn(
            persona_slug=slug,
            thread=thread,
            question=question,
            symbol=symbol,
            lang=lang,
            profile=profile,
            notes=notes,
            settings=settings,
            budget=AgentBudget(cap_usd=cap),
            model=settings.persona_chat_model,
        )
    except BudgetExhausted as exc:
        raise PersonaError(
            f"answering reached the ${exc.cap_usd} budget cap", status_code=409
        ) from exc
    except AgentUnavailable as exc:
        raise PersonaError(f"model unavailable: {exc}", status_code=503) from exc

    turn = result.turn
    turns = (*thread.turns, turn)
    updated = thread.model_copy(
        update={
            "turns": turns,
            "turn_count": len(turns),
            "title": thread.title or turn.question[:80],
            "spent_usd": str(spent + Decimal(turn.cost_usd)),
            "updated_at": _now(),
        }
    )
    chat_store.save_thread(updated)
    return turn
