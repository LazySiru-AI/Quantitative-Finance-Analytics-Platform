"""Tests for the sector classification read + write path: `app.market.sectors.set_sector` and the
`GET`/`PUT` `/api/portfolio/sectors` endpoints in `app.api.portfolio`.

Every test points at a synthetic `data/sectors.toml` under `tmp_path` via the `settings` fixture
from `tests/conftest.py` (which also disables the auth gate for the whole suite -- see that
fixture's own docstring), so nothing here touches the real repo file.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.market import sectors

_HEADER_SNIPPET = "THIS IS NOT A DATA FEED"

_REAL_SHAPED_FILE = f"""# Hand-maintained sector labels, keyed by ticker symbol.
#
# {_HEADER_SNIPPET}. There is no sector data anywhere else in this application.
#
# Frozen vocabulary (exactly these labels): MEMORY, CRYPTO, SEMI, BIG TECH, SPACE, AI & ROBOTICS,
# ENERGY, FINANCIALS, SOFTWARE, AUTO/EV, HARDWARE, COMMODITIES, HEALTHCARE, CONSUMER, INDUSTRIALS,
# REAL ESTATE, BROAD MARKET, BONDS & CASH, INTERNATIONAL, Unclassified.

[sectors]
AAPL = "BIG TECH"
"BRK.B" = "FINANCIALS"
MSTR = "CRYPTO"
"""


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# app.market.sectors.set_sector
# ---------------------------------------------------------------------------


class TestSetSectorUnit:
    def test_rejects_a_label_outside_the_frozen_vocabulary(self, settings: Settings) -> None:
        path = settings.data_dir / sectors.SECTORS_FILENAME
        _write(path, _REAL_SHAPED_FILE)
        before = path.read_text(encoding="utf-8")

        with pytest.raises(ValueError):
            sectors.set_sector("AAPL", "NOT A REAL SECTOR", settings=settings)

        # File unchanged on rejection.
        assert path.read_text(encoding="utf-8") == before

    def test_upserts_a_new_symbol_and_invalidates_the_cache(self, settings: Settings) -> None:
        path = settings.data_dir / sectors.SECTORS_FILENAME
        _write(path, _REAL_SHAPED_FILE)
        # Warm the cache before writing, to prove the write actually invalidates it.
        assert sectors.sector_for("NVDA", settings=settings) == sectors.UNCLASSIFIED

        stored = sectors.set_sector("nvda", "SEMI", settings=settings)

        assert stored == "SEMI"
        assert sectors.sector_for("NVDA", settings=settings) == "SEMI"
        assert sectors.sector_for("nvda", settings=settings) == "SEMI"

    def test_updates_an_existing_symbol(self, settings: Settings) -> None:
        path = settings.data_dir / sectors.SECTORS_FILENAME
        _write(path, _REAL_SHAPED_FILE)

        sectors.set_sector("MSTR", "BIG TECH", settings=settings)

        assert sectors.sector_for("MSTR", settings=settings) == "BIG TECH"

    def test_setting_unclassified_removes_the_entry(self, settings: Settings) -> None:
        path = settings.data_dir / sectors.SECTORS_FILENAME
        _write(path, _REAL_SHAPED_FILE)

        sectors.set_sector("MSTR", sectors.UNCLASSIFIED, settings=settings)

        assert sectors.sector_for("MSTR", settings=settings) == sectors.UNCLASSIFIED
        raw = path.read_text(encoding="utf-8")
        assert "MSTR" not in raw

    def test_header_comment_survives_a_rewrite(self, settings: Settings) -> None:
        path = settings.data_dir / sectors.SECTORS_FILENAME
        _write(path, _REAL_SHAPED_FILE)

        sectors.set_sector("NVDA", "SEMI", settings=settings)

        raw = path.read_text(encoding="utf-8")
        assert _HEADER_SNIPPET in raw
        assert "Frozen vocabulary" in raw

    def test_table_is_rewritten_sorted_by_symbol(self, settings: Settings) -> None:
        path = settings.data_dir / sectors.SECTORS_FILENAME
        _write(path, _REAL_SHAPED_FILE)

        sectors.set_sector("NVDA", "SEMI", settings=settings)

        raw = path.read_text(encoding="utf-8")
        table_text = raw.split("[sectors]", 1)[1]
        keys = [
            line.split(" = ")[0].strip('"') for line in table_text.strip().splitlines()
        ]
        assert keys == sorted(keys)

    def test_missing_file_still_writes_a_usable_table_with_some_header(
        self, settings: Settings
    ) -> None:
        path = settings.data_dir / sectors.SECTORS_FILENAME
        assert not path.exists()

        sectors.set_sector("NVDA", "SEMI", settings=settings)

        assert path.exists()
        assert sectors.sector_for("NVDA", settings=settings) == "SEMI"
        raw = path.read_text(encoding="utf-8")
        assert "[sectors]" in raw
        assert raw.strip().startswith("#")  # some header, even if minimal

    def test_a_symbol_with_a_dot_round_trips_through_a_quoted_key(self, settings: Settings) -> None:
        path = settings.data_dir / sectors.SECTORS_FILENAME
        _write(path, _REAL_SHAPED_FILE)

        sectors.set_sector("brk.b", "SOFTWARE", settings=settings)

        assert sectors.sector_for("BRK.B", settings=settings) == "SOFTWARE"


# ---------------------------------------------------------------------------
# GET /api/portfolio/sectors
# ---------------------------------------------------------------------------


class TestGetSectorsEndpoint:
    def test_returns_the_frozen_vocabulary_and_current_map(
        self, client: TestClient, settings: Settings
    ) -> None:
        path = settings.data_dir / sectors.SECTORS_FILENAME
        _write(path, _REAL_SHAPED_FILE)

        body = client.get("/api/portfolio/sectors").json()

        assert body["vocabulary"] == list(sectors.SECTOR_VOCABULARY)
        assert len(body["vocabulary"]) == 20
        assert body["map"]["AAPL"] == "BIG TECH"
        assert body["map"]["MSTR"] == "CRYPTO"
        assert body["map"]["BRK.B"] == "FINANCIALS"

    def test_missing_file_returns_an_empty_map_not_an_error(
        self, client: TestClient, settings: Settings
    ) -> None:
        body = client.get("/api/portfolio/sectors").json()

        assert body["map"] == {}
        assert len(body["vocabulary"]) == 20


# ---------------------------------------------------------------------------
# PUT /api/portfolio/sectors/{symbol}
# ---------------------------------------------------------------------------


class TestPutSectorEndpoint:
    def test_valid_label_upserts_and_a_subsequent_get_reflects_it(
        self, client: TestClient, settings: Settings
    ) -> None:
        path = settings.data_dir / sectors.SECTORS_FILENAME
        _write(path, _REAL_SHAPED_FILE)
        # Warm the in-process cache first, so the round trip below proves cache invalidation, not
        # just that a fresh read would have picked it up anyway.
        assert client.get("/api/portfolio/sectors").json()["map"].get("NVDA") is None

        put_body = client.put("/api/portfolio/sectors/NVDA", json={"sector": "SEMI"}).json()
        assert put_body == {"symbol": "NVDA", "sector": "SEMI"}

        get_body = client.get("/api/portfolio/sectors").json()
        assert get_body["map"]["NVDA"] == "SEMI"

    def test_lowercase_symbol_is_upper_cased_in_the_response_and_the_map(
        self, client: TestClient, settings: Settings
    ) -> None:
        _write(settings.data_dir / sectors.SECTORS_FILENAME, _REAL_SHAPED_FILE)

        put_body = client.put("/api/portfolio/sectors/nvda", json={"sector": "SEMI"}).json()

        assert put_body["symbol"] == "NVDA"
        get_body = client.get("/api/portfolio/sectors").json()
        assert get_body["map"]["NVDA"] == "SEMI"

    def test_invalid_label_returns_422_and_leaves_the_file_unchanged(
        self, client: TestClient, settings: Settings
    ) -> None:
        path = settings.data_dir / sectors.SECTORS_FILENAME
        _write(path, _REAL_SHAPED_FILE)
        before = path.read_text(encoding="utf-8")

        response = client.put("/api/portfolio/sectors/AAPL", json={"sector": "NOT A SECTOR"})

        assert response.status_code == 422
        assert path.read_text(encoding="utf-8") == before

    def test_setting_unclassified_removes_the_entry(
        self, client: TestClient, settings: Settings
    ) -> None:
        path = settings.data_dir / sectors.SECTORS_FILENAME
        _write(path, _REAL_SHAPED_FILE)

        put_body = client.put(
            "/api/portfolio/sectors/MSTR", json={"sector": sectors.UNCLASSIFIED}
        ).json()

        assert put_body == {"symbol": "MSTR", "sector": sectors.UNCLASSIFIED}
        get_body = client.get("/api/portfolio/sectors").json()
        assert "MSTR" not in get_body["map"]

    def test_header_comment_survives_through_the_endpoint(
        self, client: TestClient, settings: Settings
    ) -> None:
        path = settings.data_dir / sectors.SECTORS_FILENAME
        _write(path, _REAL_SHAPED_FILE)

        client.put("/api/portfolio/sectors/NVDA", json={"sector": "SEMI"})

        raw = path.read_text(encoding="utf-8")
        assert _HEADER_SNIPPET in raw

    def test_a_symbol_carrying_an_encoded_newline_is_rejected_with_422(
        self, client: TestClient, settings: Settings
    ) -> None:
        """`symbol` is now constrained to the same alphabet `app.api.market.SymbolPath` uses -- a
        `%0A` (a raw newline once decoded) never names a real symbol and must never reach
        `set_sector`'s TOML writer at all, regardless of how well `_quote` now escapes it."""
        path = settings.data_dir / sectors.SECTORS_FILENAME
        _write(path, _REAL_SHAPED_FILE)
        before = path.read_text(encoding="utf-8")

        response = client.put("/api/portfolio/sectors/AAPL%0A", json={"sector": "SEMI"})

        assert response.status_code == 422
        assert path.read_text(encoding="utf-8") == before

    def test_a_symbol_over_sixteen_characters_is_rejected_with_422(
        self, client: TestClient
    ) -> None:
        response = client.put(
            "/api/portfolio/sectors/" + "A" * 17, json={"sector": "SEMI"}
        )
        assert response.status_code == 422
