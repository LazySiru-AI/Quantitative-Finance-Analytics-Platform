"""Portfolio Planner board persistence and its endpoints.

These call the `app.api.designer` functions directly under the `settings` fixture (whose
`INVDASH_DATA_DIR` points at a temp dir, so nothing here touches the real `data/designer/board.json`)
rather than through a `TestClient`, because the contract worth pinning is the storage behaviour --
empty by default, round-trips a saved board, never raises on a bad file, bounded on write -- not the
HTTP plumbing. The one gate check confirms the prefix is owner-scoped.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api import designer
from app.auth.gate import is_owner_only
from app.config import Settings


def _board(**kw: object) -> designer.DesignerBoard:
    col = designer.DesignerColumn(
        account_id="rh-taxable",
        label="Robinhood Individual",
        tax_treatment="taxable",
        account_type="cash",
        note="watch MU into earnings",
        tickers=[designer.DesignerTicker(symbol="NVDA"), designer.DesignerTicker(symbol="MU")],
    )
    return designer.DesignerBoard(columns=[col], **kw)  # type: ignore[arg-type]


def test_default_board_is_empty_without_a_ledger(settings: Settings) -> None:
    """A server with no saved file and no ledger returns an empty board rather than raising -- the
    tab then shows its empty state instead of 500-ing on a fresh machine."""
    board = designer.get_board()
    assert board.columns == []
    assert board.updated_at is None
    assert not Path(designer.board_path(settings)).exists()


def test_put_then_get_round_trips_columns_notes_and_tickers(settings: Settings) -> None:
    saved = designer.put_board(_board())
    assert saved.updated_at is not None  # PUT stamps the save time

    reloaded = designer.get_board()
    assert [c.account_id for c in reloaded.columns] == ["rh-taxable"]
    col = reloaded.columns[0]
    assert col.note == "watch MU into earnings"
    assert [t.symbol for t in col.tickers] == ["NVDA", "MU"]
    assert reloaded.updated_at == saved.updated_at


def test_malformed_board_file_falls_back_to_default(settings: Settings) -> None:
    """A hand-edited or truncated file must log and fall back, never raise -- the same rule the
    inception override follows, applied here so a bad planning file cannot take the tab down."""
    path = Path(designer.board_path(settings))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    board = designer.read_board(settings)  # must not raise
    assert board.columns == []
    assert board.updated_at is None


def test_put_rejects_too_many_columns(settings: Settings) -> None:
    board = designer.DesignerBoard(
        columns=[
            designer.DesignerColumn(account_id=f"acct-{i}") for i in range(designer._MAX_COLUMNS + 1)
        ]
    )
    with pytest.raises(HTTPException) as exc:
        designer.put_board(board)
    assert exc.value.status_code == 422


def test_universe_returns_symbols_with_sectors(settings: Settings) -> None:
    """`get_universe` never raises even when the temp data dir has no universe/sector files -- it
    degrades to whatever it can read. Shape is what is pinned here."""
    universe = designer.get_universe()
    assert isinstance(universe, list)
    for entry in universe:
        assert entry.symbol
        assert entry.sector


def test_designer_prefix_is_owner_only() -> None:
    assert is_owner_only("/api/designer/board")
    assert is_owner_only("/api/designer/universe")


def test_saved_file_is_valid_json_matching_the_model(settings: Settings) -> None:
    designer.put_board(_board())
    payload = json.loads(Path(designer.board_path(settings)).read_text(encoding="utf-8"))
    # Re-validating the written bytes guards against a serialiser change that writes something the
    # reader would then reject and silently fall back from.
    designer.DesignerBoard.model_validate(payload)
