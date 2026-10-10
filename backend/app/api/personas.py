"""Persona endpoints: the influencer-persona feature's HTTP surface.

Thin by contract (`docs/INFLUENCER-CONTRACT.md`): this router wires routes and maps domain exceptions
to status codes. All logic -- resolving a handle to a channel, fetching and summarising videos,
reading and writing the vault -- lives in `app.personas`. Provider failures degrade to warnings on a
card rather than 5xx, the same rule `app.api.news` documents.

**Phase 0 skeleton.** The read routes are live against the vault (an empty vault answers with empty
lists, never an error). The mutating routes (`POST`/`DELETE` personas and sources, `POST /ingest`)
are wired to `app.personas.service`, whose implementations Phase 1 fills in; until then they raise a
501 that names what is missing rather than a 500. The route *shapes* are pinned here now so the
Phase 1 backend and frontend workers build against a fixed surface.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.personas import service, trader_service
from app.personas.models import (
    CardCritique,
    ChatContext,
    ChatThread,
    ChatTurn,
    DigestCard,
    EpisodicNote,
    InfluencerWatchlist,
    IngestJob,
    Persona,
    PersonaAnswer,
    PersonaBacktest,
    PersonaBook,
    PersonaProfile,
    PersonaScorecard,
    PersonaTimeline,
    ProfileDiff,
    RegimeConsensus,
    SavedStrategyDraft,
    StrategyCardDraft,
    TickerThesis,
)
from app.personas.trader import TraderBook
from app.personas.trader_service import TraderJob
from app.tournament.models import StrategyCard as LibraryCard

router = APIRouter(prefix="/api/personas", tags=["personas"])

VersionPath = Annotated[int, Path(ge=1)]

SlugPath = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")]
SourceIdPath = Annotated[str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:_-]+$")]
NoteIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
SymbolPath = Annotated[str, Path(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.\-]+$")]
ThreadIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
JobIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class AddPersonaRequest(BaseModel):
    model_config = {"extra": "forbid"}
    handle: str = Field(min_length=1, max_length=200)
    platform: str = "youtube"


class AskRequest(BaseModel):
    model_config = {"extra": "forbid"}
    question: str = Field(min_length=1, max_length=2000)
    symbol: str | None = Field(default=None, max_length=16)


class ChatTurnRequest(BaseModel):
    model_config = {"extra": "forbid"}
    question: str = Field(min_length=1, max_length=2000)
    symbol: str | None = Field(default=None, max_length=16)
    lang: str | None = Field(default=None)
    """`"en"`/`"ko"`; `None` falls back to `settings.persona_summary_lang` (see the route below), the
    same default `AskRequest` leaves implicit for the one-shot `/ask` endpoint."""


class DropSpec(BaseModel):
    model_config = {"extra": "forbid"}
    url: str | None = None
    """When given, must be `http://` or `https://` -- see `app.personas.models._require_http_url`
    for why: this value flows into `service.start_ingest` -> `EpisodicNote.url` (that model's own
    field validator enforces the same rule), and rejecting it here, at the boundary, gives a 422
    naming the bad value instead of a validation error surfacing from deep inside the ingest job."""
    text: str | None = None
    title: str | None = None

    @field_validator("url")
    @classmethod
    def _url_is_http(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        # Empty (after stripping) is left alone rather than rejected: `_plan_items` in
        # `app.personas.service` treats a falsy `url` on a drop as "no url, text only" -- a
        # supported request shape (a drop needs *either* text or a url) -- so an empty string here
        # must reach that check unchanged, not be turned into a 422 by this boundary.
        if stripped and not stripped.lower().startswith(("http://", "https://")):
            raise ValueError(f"url must be empty or start with http:// or https://, got {value!r}")
        return stripped


class IngestRequest(BaseModel):
    model_config = {"extra": "forbid"}
    limit: int | None = Field(default=None, ge=1, le=500)
    video_urls: list[str] | None = None
    drop: DropSpec | None = None


class CritiqueRequest(BaseModel):
    model_config = {"extra": "forbid"}
    card: dict[str, object] = Field(description="A StrategyCard as JSON for the persona to assess.")


class BackfillRequest(BaseModel):
    model_config = {"extra": "forbid"}
    inception: dt.date | None = Field(
        default=None, description="Defaults to app.personas.trader.DEFAULT_INCEPTION (2026-01-01)."
    )


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=what)


# --- personas -------------------------------------------------------------


@router.get("", response_model=list[Persona])
def list_personas() -> list[Persona]:
    return list(service.list_personas(get_settings()))


@router.post("", response_model=Persona, status_code=status.HTTP_201_CREATED)
def add_persona(body: AddPersonaRequest) -> Persona:
    try:
        return service.add_persona(get_settings(), handle=body.handle, platform=body.platform)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/cards", response_model=list[DigestCard])
def list_cards() -> list[DigestCard]:
    return list(service.list_cards(get_settings()))


@router.get("/books", response_model=list[PersonaBook])
def list_books() -> list[PersonaBook]:
    # Defined before `/{slug}` so "books" is not captured as a persona slug (same ordering `/cards`
    # relies on). One current-holdings paper book per persona, for the Paper Desk.
    return list(service.persona_books(get_settings()))


@router.get("/watchlist", response_model=InfluencerWatchlist)
def get_watchlist(
    as_of: Annotated[dt.date | None, Query(description="Point-in-time cutoff; omit for now.")] = None,
) -> InfluencerWatchlist:
    # Before `/{slug}` (collection route). The cross-persona consensus watchlist -- what the followed
    # influencers are currently bullish on, for the strategy layer to seed focus_symbols or the owner
    # to read. `as_of` gives the point-in-time consensus (no look-ahead). Descriptive, not a buy list.
    return service.watchlist(get_settings(), as_of=as_of)


@router.get("/regime", response_model=RegimeConsensus)
def get_regime() -> RegimeConsensus:
    # Before `/{slug}` (collection route). The cross-persona macro picture from the commentator
    # personas -- a reference the strategy layer may cite, never a signal.
    return service.regime(get_settings())


@router.get("/trader/books", response_model=list[TraderBook])
def list_trader_books() -> list[TraderBook]:
    # Before `/{slug}` so "trader" is not captured as a persona slug (same ordering `/books`/`/cards`/
    # `/watchlist`/`/regime` rely on). One trader book per persona, for the Paper Desk; always 200.
    return list(trader_service.list_trader_books(get_settings()))


@router.get("/{slug}", response_model=Persona)
def get_persona(slug: SlugPath) -> Persona:
    persona = service.get_persona(get_settings(), slug)
    if persona is None:
        raise _not_found(f"no persona {slug!r}")
    return persona


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
def delete_persona(slug: SlugPath) -> None:
    # `service.delete_persona` refuses (409) while an ingest is still writing into this persona's
    # directory, so this route needs the same exception translation the mutating routes have -- a
    # `PersonaError` escaping here would surface a deliberate refusal as an internal error.
    try:
        deleted = service.delete_persona(get_settings(), slug)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if not deleted:
        raise _not_found(f"no persona {slug!r}")


@router.post("/{slug}/sources", response_model=Persona)
def add_source(slug: SlugPath, body: AddPersonaRequest) -> Persona:
    try:
        return service.add_source(
            get_settings(), slug, handle=body.handle, platform=body.platform
        )
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.delete("/{slug}/sources/{source_id}", response_model=Persona)
def remove_source(slug: SlugPath, source_id: SourceIdPath) -> Persona:
    try:
        return service.remove_source(get_settings(), slug, source_id)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


# --- notes ----------------------------------------------------------------


@router.get("/{slug}/notes", response_model=list[EpisodicNote])
def list_notes(slug: SlugPath) -> list[EpisodicNote]:
    if service.get_persona(get_settings(), slug) is None:
        raise _not_found(f"no persona {slug!r}")
    return list(service.list_notes(get_settings(), slug))


@router.get("/{slug}/notes/{note_id}", response_model=EpisodicNote)
def get_note(slug: SlugPath, note_id: NoteIdPath) -> EpisodicNote:
    note = service.get_note(get_settings(), slug, note_id)
    if note is None:
        raise _not_found(f"no note {note_id!r} for persona {slug!r}")
    return note


# --- ingest ---------------------------------------------------------------


@router.post("/{slug}/ingest", response_model=IngestJob, status_code=status.HTTP_202_ACCEPTED)
def start_ingest(slug: SlugPath, body: IngestRequest) -> IngestJob:
    try:
        return service.start_ingest(
            get_settings(),
            slug,
            limit=body.limit,
            video_urls=body.video_urls,
            drop=body.drop.model_dump() if body.drop else None,
        )
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{slug}/ingest/{job_id}", response_model=IngestJob)
def get_ingest(slug: SlugPath, job_id: NoteIdPath) -> IngestJob:
    job = service.get_ingest(get_settings(), slug, job_id)
    if job is None:
        raise _not_found(f"no ingest job {job_id!r} for persona {slug!r}")
    return job


# --- consolidation (Phase 2) ----------------------------------------------


@router.post("/{slug}/consolidate", response_model=PersonaProfile)
def consolidate(
    slug: SlugPath,
    incremental: Annotated[bool, Query(description="Fold only notes newer than the last profile.")] = False,
) -> PersonaProfile:
    # Synchronous: one model call over notes already on disk. `PersonaError` carries the status --
    # 404 unknown persona, 409 no notes / budget cap, 503 model unavailable. `incremental` merges only
    # new notes into the standing profile so cost stops scaling with vault size.
    try:
        return service.consolidate(get_settings(), slug, incremental=incremental)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{slug}/profile", response_model=PersonaProfile)
def get_profile(slug: SlugPath) -> PersonaProfile:
    profile = service.get_profile(get_settings(), slug)
    if profile is None:
        raise _not_found(f"persona {slug!r} has no consolidated profile yet")
    return profile


@router.get("/{slug}/profile/diff", response_model=ProfileDiff)
def get_profile_diff(
    slug: SlugPath,
    from_version: Annotated[int, Query(alias="from", ge=1)],
    to_version: Annotated[int, Query(alias="to", ge=1)],
) -> ProfileDiff:
    # What changed in a persona's memory between two consolidations. 404 unknown persona/version.
    try:
        return service.profile_diff(
            get_settings(), slug, from_version=from_version, to_version=to_version
        )
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{slug}/theses", response_model=list[TickerThesis])
def list_theses(slug: SlugPath) -> list[TickerThesis]:
    if service.get_persona(get_settings(), slug) is None:
        raise _not_found(f"no persona {slug!r}")
    return list(service.list_theses(get_settings(), slug))


@router.get("/{slug}/theses/{symbol}", response_model=TickerThesis)
def get_thesis(slug: SlugPath, symbol: SymbolPath) -> TickerThesis:
    thesis = service.get_thesis(get_settings(), slug, symbol)
    if thesis is None:
        raise _not_found(f"persona {slug!r} has no thesis for {symbol!r}")
    return thesis


@router.get("/{slug}/scorecard", response_model=PersonaScorecard)
def get_scorecard(slug: SlugPath) -> PersonaScorecard:
    # Descriptive scoring of dated calls against market history. May fetch bars (so it can be slow on
    # a cold store) but never model-calls; degrades to stored data. 404 only for an unknown persona.
    try:
        return service.scorecard(get_settings(), slug)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{slug}/backtest", response_model=PersonaBacktest)
def get_backtest(slug: SlugPath) -> PersonaBacktest:
    # Descriptive lens: did following the persona's dated calls beat holding SPY over the same
    # windows? Reuses scoring + one SPY fetch; 404 only for an unknown persona.
    try:
        return service.backtest(get_settings(), slug)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{slug}/book", response_model=PersonaBook)
def get_book(
    slug: SlugPath,
    as_of: Annotated[dt.date | None, Query(description="Point-in-time date; omit for latest.")] = None,
    exclude_intraday: Annotated[bool, Query(description="Drop scalp-horizon calls.")] = False,
) -> PersonaBook:
    # A persona's current-holdings paper book. 404 only for an unknown persona. `as_of` prices it
    # point-in-time (no look-ahead); `exclude_intraday` drops calls that are not really holdings.
    try:
        return service.persona_book(
            get_settings(), slug, as_of=as_of, exclude_intraday=exclude_intraday
        )
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{slug}/strategy-card", response_model=StrategyCardDraft)
def strategy_card(slug: SlugPath) -> StrategyCardDraft:
    # Persona -> rule card (Phase 7c, exploration lens). A mapped draft is persisted (versioned) so the
    # owner can re-open it. 404 unknown persona; 409 no methodology / no current-bullish tickers /
    # budget; 503 model unavailable.
    try:
        return service.strategy_card(get_settings(), slug)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{slug}/strategy-cards", response_model=list[SavedStrategyDraft])
def list_strategy_cards(slug: SlugPath) -> list[SavedStrategyDraft]:
    # Every persisted strategy-card draft for a persona, newest first. 404 unknown persona.
    try:
        return list(service.saved_strategy_cards(get_settings(), slug))
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{slug}/strategy-cards/{version}/promote", response_model=LibraryCard, status_code=201)
def promote_strategy_card(slug: SlugPath, version: VersionPath) -> LibraryCard:
    # Promote a saved persona strategy-card draft onto the competition library shelf as a scorable
    # candidate. The card is read from the persona's own saved draft, never the request. 404 unknown
    # persona / no draft at that version; 422 a draft that mapped no card; 409 already on the shelf.
    try:
        return service.promote_strategy_card(get_settings(), slug, version)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{slug}/critique", response_model=CardCritique)
def critique(slug: SlugPath, body: CritiqueRequest) -> CardCritique:
    # The reverse of the persona->card mapping: the persona assesses a card in-voice, grounded in their
    # own methodology. 404 unknown persona; 409 budget; 503 model unavailable. A persona with no profile
    # returns a cannot_say critique, not an error.
    try:
        return service.critique(get_settings(), slug, card=body.card)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{slug}/timeline", response_model=PersonaTimeline)
def get_timeline(slug: SlugPath) -> PersonaTimeline:
    # Pure read over stored notes: chronological entries + per-symbol stance evolution. 404 only for
    # an unknown persona; a known persona with no notes yields empty entries, not an error.
    try:
        return service.timeline(get_settings(), slug)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{slug}/ask", response_model=PersonaAnswer)
def ask_persona(slug: SlugPath, body: AskRequest) -> PersonaAnswer:
    # A model's impression of the persona, grounded in its own notes. 404 unknown persona; 409 no
    # notes / budget cap; 503 model unavailable. Synchronous (one grounded call).
    try:
        return service.ask(get_settings(), slug, question=body.question, symbol=body.symbol)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


# --- Phase 9: persona chat --------------------------------------------------


@router.get("/{slug}/chats", response_model=list[ChatThread])
def list_chats(slug: SlugPath) -> list[ChatThread]:
    # Every persisted chat thread for the persona, turns omitted, newest updated_at first.
    try:
        return list(service.list_chats(get_settings(), slug))
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{slug}/chats", response_model=ChatThread, status_code=status.HTTP_201_CREATED)
def create_chat(slug: SlugPath) -> ChatThread:
    # A fresh, empty chat thread. 404 unknown persona.
    try:
        return service.create_chat(get_settings(), slug)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{slug}/chats/{thread_id}", response_model=ChatThread)
def get_chat(slug: SlugPath, thread_id: ThreadIdPath) -> ChatThread:
    # One chat thread, full turns included. 404 unknown persona/thread.
    try:
        return service.get_chat(get_settings(), slug, thread_id)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.delete("/{slug}/chats/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(slug: SlugPath, thread_id: ThreadIdPath) -> None:
    # 404 unknown persona/thread.
    try:
        service.delete_chat(get_settings(), slug, thread_id)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{slug}/chats/{thread_id}/turns", response_model=ChatTurn)
def add_chat_turn(slug: SlugPath, thread_id: ThreadIdPath, body: ChatTurnRequest) -> ChatTurn:
    # One grounded turn in a persisted thread, folding the thread's own recent history into the
    # prompt. 404 unknown persona/thread; 409 no notes / thread turn cap / thread budget cap; 429
    # daily spend cap (app.agents.spend_http, uncaught); 503 model unavailable. Synchronous.
    settings = get_settings()
    lang = body.lang or settings.persona_summary_lang
    try:
        return service.chat_turn(
            settings, slug, thread_id=thread_id, question=body.question, symbol=body.symbol, lang=lang,
        )
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{slug}/chat-context", response_model=ChatContext)
def get_chat_context(slug: SlugPath) -> ChatContext:
    # Whether the persona's consolidated profile is stale relative to the notes on disk. 404 unknown
    # persona.
    try:
        return service.chat_context(get_settings(), slug)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


# --- Phase 10: persona paper trader ------------------------------------------


@router.get("/{slug}/trader", response_model=TraderBook)
def get_trader(slug: SlugPath) -> TraderBook:
    # A persona's model-driven trader book. 404 unknown persona; a known persona that has never traded
    # gets the empty book, not an error.
    try:
        return trader_service.get_trader_book(get_settings(), slug)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.delete("/{slug}/trader", status_code=status.HTTP_204_NO_CONTENT)
def delete_trader(slug: SlugPath) -> None:
    # Reset the persona's trader book. 404 unknown persona.
    try:
        trader_service.delete_trader_book(get_settings(), slug)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{slug}/trader/decide", response_model=TraderBook)
def decide_trader(slug: SlugPath) -> TraderBook:
    # Run ONE decision at the latest session now. Synchronous, one grounded call. 404 unknown persona;
    # 409 per-decision budget cap; 503 model unavailable; 429 daily spend cap (app.agents.spend_http,
    # uncaught).
    try:
        return trader_service.decide_now(get_settings(), slug)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post(
    "/{slug}/trader/backfill", response_model=TraderJob, status_code=status.HTTP_202_ACCEPTED
)
def start_trader_backfill(slug: SlugPath, body: BackfillRequest) -> TraderJob:
    # Async weekly backfill from `inception` (default app.personas.trader.DEFAULT_INCEPTION), via a
    # background thread + in-memory job registry. 404 unknown persona; 409 a backfill is already
    # active for this persona.
    try:
        return trader_service.start_backfill(get_settings(), slug, inception=body.inception)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{slug}/trader/backfill/{job_id}", response_model=TraderJob)
def get_trader_backfill(slug: SlugPath, job_id: JobIdPath) -> TraderJob:
    # Poll a trader backfill job. 404 unknown persona/job.
    try:
        return trader_service.get_backfill_job(get_settings(), slug, job_id)
    except service.PersonaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
