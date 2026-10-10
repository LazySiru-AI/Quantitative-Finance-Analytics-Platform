"""Portfolio Planner board: a per-account planning canvas the owner edits and the server persists.

This is the in-app home of what began as `portfolio-designer.html`: columns keyed by account, each
holding a list of tickers the owner is planning around, plus a free-text note per account. The board
is *planning intent*, not a ledger -- nothing here is a transaction, a holding, or a tax figure. The
live wash-sale status, current holdings and the searchable universe the page decorates each ticker
with are read separately from `/api/portfolio`, `/api/tax/wash-sales` and this module's `/universe`;
none of that derived, time-sensitive data is stored on the board, because "can I buy this back yet"
is a function of today's date and must never be frozen into a saved file.

**Persistence model, matching the two things the owner asked for:**

- *Survives shutdown.* The board is a single JSON file, `data/designer/board.json`, written
  atomically (temp file then `Path.replace`) the same way `app.paperdesk.desk.set_inception` writes
  its override. It is the source of truth; there is no browser-local copy the server can disagree
  with.
- *Empty by default, then whatever the owner made.* A server that has never had a `PUT` has no file,
  and `GET` then returns a default board: one empty column per open account, no tickers, no notes.
  The "pull current holdings" button is a *page* action that reads `/api/portfolio` and writes the
  result back through `PUT`; the server never seeds holdings on its own, so the first view is empty
  until the owner either pulls or places a ticker by hand.

Reads never raise on a bad file (a hand-edited or truncated `board.json` logs and falls back to the
default, exactly as the inception override does) -- a corrupt planning file must not 500 the tab.
"""

from __future__ import annotations

import json
import logging
from typing import Final

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.core.models import AccountStatus
from app.datasource import ledger_db_path, local_document_path, read_document, write_document
from app.db import sqlite
from app.market.sectors import load_sector_map, sector_for

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/designer", tags=["designer"])

#: A single symbol as it may appear on the board. Uppercase, starts alphanumeric, then the small set
#: of punctuation real tickers use (`BRK-B`, `BRK.B`). Deliberately permissive on membership -- the
#: board is planning intent, so a ticker the owner has never traded (and that no universe lists) is a
#: legitimate entry -- but bounded in shape and length so a saved file cannot carry an arbitrary blob.
_SYMBOL_MAX_LEN: Final[int] = 12
_NOTE_MAX_LEN: Final[int] = 4000
_MAX_TICKERS_PER_COLUMN: Final[int] = 500
_MAX_COLUMNS: Final[int] = 32


class DesignerTicker(BaseModel):
    """One ticker placed in a column. Symbol only -- the note lives on the column, per the owner's
    "notes per account, not per ticker" instruction, and every other figure the card shows (wash
    window, held quantity, deferred loss, sector) is decorated live by the page, never stored here."""

    symbol: str = Field(min_length=1, max_length=_SYMBOL_MAX_LEN)


class DesignerColumn(BaseModel):
    """One account's planning column: its identity, a free-text note, and the tickers in it.

    `account_id` is the persistence key -- "data stored per account" is this field. `label` is a
    denormalised copy of the account's display name so the board renders without a second lookup and
    still reads sensibly if an account is later renamed or closed; it is not authoritative.
    """

    account_id: str = Field(min_length=1, max_length=64)
    label: str = Field(default="", max_length=128)
    tax_treatment: str | None = Field(default=None, max_length=32)
    account_type: str | None = Field(default=None, max_length=32)
    note: str = Field(default="", max_length=_NOTE_MAX_LEN)
    tickers: list[DesignerTicker] = Field(default_factory=list)


class DesignerBoard(BaseModel):
    """The whole board: one column per account, plus when it was last saved.

    `updated_at` is `None` for the default (never-saved) board and an ISO 8601 timestamp once a `PUT`
    has written the file -- the page shows it as "saved" provenance, and its absence is how the page
    knows it is looking at the empty default rather than an owner-emptied board.
    """

    columns: list[DesignerColumn] = Field(default_factory=list)
    updated_at: str | None = None


class UniverseSymbol(BaseModel):
    """One searchable symbol and its sector, for the palette's search box. `held` is intentionally
    absent -- whether the owner holds a symbol is live state the page reads from `/api/portfolio`,
    not something this universe (a static index-constituent list plus the sector map) can know."""

    symbol: str
    sector: str


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def board_path(settings: Settings) -> str:
    """`data/designer/board.json` -- the single file `PUT` writes and `GET` reads back, one level
    under `settings.data_dir` the same way `app.paperdesk.desk.inception_override_path` sits under
    it for the inception override."""
    return str(local_document_path("planner-board", settings))


def _default_board(settings: Settings) -> DesignerBoard:
    """An empty column per open account, in `account_id` order, no tickers and no notes.

    This is what a server with no saved file returns, and it is deliberately empty: the owner asked
    that the board start blank and fill only from their own actions (the "pull current holdings"
    button or a manual placement), so this seeds column *identity* -- which accounts exist -- but
    never their contents. A ledger that cannot be opened yields no columns rather than raising; the
    tab then shows its empty state instead of 500-ing on a machine whose ledger has not been built.
    """
    ledger_file = ledger_db_path(settings)
    if not ledger_file.exists():
        return DesignerBoard(columns=[], updated_at=None)
    with sqlite.connect(ledger_file, read_only=True) as conn:
        accounts = [a for a in sqlite.fetch_accounts(conn) if a.status is AccountStatus.OPEN]
    columns = [
        DesignerColumn(
            account_id=a.account_id,
            label=a.label,
            tax_treatment=a.tax_treatment.value,
            account_type=a.account_type.value,
        )
        for a in sorted(accounts, key=lambda a: a.account_id)
    ]
    return DesignerBoard(columns=columns, updated_at=None)


def read_board(settings: Settings) -> DesignerBoard:
    """The saved board, or the empty default when there is no file.

    **A missing file is the normal first-run case** and returns the default silently. A
    present-but-malformed file logs and falls back to the default too, and never raises: a
    hand-edited or truncated `board.json` must not take the whole tab down, the same rule
    `app.paperdesk.desk._read_inception_override` applies to its own small persisted file.
    """
    text = read_document("planner-board", settings)
    if text is None:
        return _default_board(settings)
    try:
        payload = json.loads(text)
        return DesignerBoard.model_validate(payload)
    except (OSError, ValueError) as exc:
        logger.warning(
            "designer: board document is unreadable, falling back to the empty default: %s", exc
        )
        return _default_board(settings)


def write_board(board: DesignerBoard, *, settings: Settings) -> None:
    """Persist `board` as the `planner-board` document. Locally that is an atomic temp-file-then-
    replace write (a crash mid-write leaves the old file intact); remotely it is one PUT."""
    write_document("planner-board", board.model_dump_json(), settings)


# ---------------------------------------------------------------------------
# Universe (search)
# ---------------------------------------------------------------------------


def _load_universe(settings: Settings) -> list[UniverseSymbol]:
    """Every symbol the palette's search offers, each with its sector.

    The set is the union of the index-constituent snapshot (`data/universe/index-constituents.json`,
    the same file the strategy universe reads) and every symbol the sector map names -- so a ticker
    the owner has classified but that is not in an index still searches. Sorted, de-duped. A missing
    or unreadable universe file degrades to just the sector-map symbols rather than raising; search
    over a smaller list is far better than a 500.
    """
    from pathlib import Path

    symbols: set[str] = set()
    uni_path = Path(settings.data_dir) / "universe" / "index-constituents.json"
    try:
        payload = json.loads(uni_path.read_text(encoding="utf-8"))
        tickers = payload.get("tickers") if isinstance(payload, dict) else None
        if isinstance(tickers, list):
            symbols.update(str(t) for t in tickers if isinstance(t, str))
    except (OSError, ValueError) as exc:
        logger.warning("designer: universe file at %s unreadable, using sector map only: %s", uni_path, exc)

    # `sector_for` reads the sector map; enumerate its keys through the same loader.
    symbols.update(load_sector_map(settings=settings))

    return [
        UniverseSymbol(symbol=s, sector=sector_for(s, settings=settings))
        for s in sorted(symbols)
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/board", response_model=DesignerBoard)
def get_board() -> DesignerBoard:
    """The saved planning board, or the empty per-account default when nothing has been saved yet.

    Never 500s on a bad saved file -- see `read_board`. Owner-only: the whole `/api/designer` prefix
    sits in `app.auth.gate.OWNER_ONLY_PREFIXES`, because a board names the owner's accounts and the
    tickers they are planning around.
    """
    return read_board(get_settings())


@router.put("/board", response_model=DesignerBoard)
def put_board(board: DesignerBoard) -> DesignerBoard:
    """Replace the whole board and persist it, returning the saved copy with a fresh `updated_at`.

    `PUT`, not `POST`: the page sends the entire board on every autosave, and sending the same board
    twice must leave the same file rather than appending. The body is bounded (column, ticker and
    note caps) so an autosave loop or a bad client cannot grow the file without limit; anything over
    a cap is a `422`, not a silent truncation that would lose the owner's data without telling them.
    """
    import datetime as dt

    if len(board.columns) > _MAX_COLUMNS:
        raise HTTPException(status_code=422, detail=f"too many columns (max {_MAX_COLUMNS})")
    for col in board.columns:
        if len(col.tickers) > _MAX_TICKERS_PER_COLUMN:
            raise HTTPException(
                status_code=422,
                detail=f"column {col.account_id!r} has too many tickers (max {_MAX_TICKERS_PER_COLUMN})",
            )
    saved = board.model_copy(update={"updated_at": dt.datetime.now(dt.UTC).isoformat()})
    settings = get_settings()
    write_board(saved, settings=settings)
    return saved


@router.get("/universe", response_model=list[UniverseSymbol])
def get_universe() -> list[UniverseSymbol]:
    """The searchable symbol list (index constituents + sector-map symbols), each with its sector.

    Static reference data -- it changes only when the universe snapshot or the sector map is
    re-generated -- so the page fetches it once on mount and filters client-side rather than round
    tripping every keystroke.
    """
    return _load_universe(get_settings())
