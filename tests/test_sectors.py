"""Tests for `app.market.sectors`: the hand-maintained symbol -> sector label lookup.

Every test points at a synthetic TOML file under `tmp_path` (via the `settings` fixture
from `tests/conftest.py`) so nothing here depends on -- or mutates -- the repo's real
`data/sectors.toml`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from app.config import Settings
from app.market import sectors

# ---------------------------------------------------------------------------
# `sector_for` / `load_sector_map` behaviour against a synthetic file
# ---------------------------------------------------------------------------


def _write_sectors_toml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


class TestSectorFor:
    def test_a_mapped_symbol_resolves_to_its_label(self, settings: Settings) -> None:
        _write_sectors_toml(
            settings.data_dir / sectors.SECTORS_FILENAME,
            '[sectors]\nMSTR = "CRYPTO"\nNVDA = "SEMI"\n',
        )

        assert sectors.sector_for("MSTR", settings=settings) == "CRYPTO"
        assert sectors.sector_for("NVDA", settings=settings) == "SEMI"

    def test_lookup_is_case_insensitive_on_both_sides(self, settings: Settings) -> None:
        _write_sectors_toml(
            settings.data_dir / sectors.SECTORS_FILENAME,
            '[sectors]\nmstr = "CRYPTO"\n',
        )

        assert sectors.sector_for("MSTR", settings=settings) == "CRYPTO"
        assert sectors.sector_for("mstr", settings=settings) == "CRYPTO"
        assert sectors.sector_for("MsTr", settings=settings) == "CRYPTO"

    def test_an_unknown_symbol_is_unclassified(self, settings: Settings) -> None:
        _write_sectors_toml(settings.data_dir / sectors.SECTORS_FILENAME, '[sectors]\nMSTR = "CRYPTO"\n')

        assert sectors.sector_for("ZZZZ", settings=settings) == sectors.UNCLASSIFIED

    def test_a_missing_file_degrades_to_unclassified_rather_than_raising(
        self, settings: Settings
    ) -> None:
        # Deliberately never written -- `settings.data_dir` exists (the fixture calls
        # `ensure_dirs`) but no `sectors.toml` lives in it.
        assert sectors.sector_for("MSTR", settings=settings) == sectors.UNCLASSIFIED
        assert sectors.load_sector_map(settings.data_dir / sectors.SECTORS_FILENAME) == {}

    def test_malformed_toml_degrades_to_unclassified_rather_than_raising(
        self, settings: Settings
    ) -> None:
        _write_sectors_toml(
            settings.data_dir / sectors.SECTORS_FILENAME, "this is not [ valid toml at all ===\n"
        )

        assert sectors.sector_for("MSTR", settings=settings) == sectors.UNCLASSIFIED

    def test_a_table_missing_the_sectors_key_degrades_to_unclassified(
        self, settings: Settings
    ) -> None:
        _write_sectors_toml(settings.data_dir / sectors.SECTORS_FILENAME, '[not_sectors]\nMSTR = "CRYPTO"\n')

        assert sectors.sector_for("MSTR", settings=settings) == sectors.UNCLASSIFIED

    def test_never_returns_none(self, settings: Settings) -> None:
        _write_sectors_toml(settings.data_dir / sectors.SECTORS_FILENAME, '[sectors]\nMSTR = "CRYPTO"\n')

        for symbol in ("MSTR", "unknown-symbol", ""):
            result = sectors.sector_for(symbol, settings=settings)
            assert result is not None
            assert isinstance(result, str)


# ---------------------------------------------------------------------------
# `_quote`: TOML control-character escaping (security hardening)
# ---------------------------------------------------------------------------


class TestQuoteEscapesControlCharacters:
    """`_quote` used to escape only `\\` and `"`. A label or symbol carrying a raw newline, tab, or
    any other byte below U+0020 would land in the basic TOML string literal unescaped -- invalid
    TOML that `tomllib.loads` cannot parse back, breaking the module's own "never raise" contract on
    the read side by way of a write the same module made."""

    def test_newline_round_trips_through_tomllib(self) -> None:
        quoted = sectors._quote("a\nb")
        parsed = tomllib.loads(f"key = {quoted}\n")
        assert parsed["key"] == "a\nb"

    def test_tab_and_carriage_return_round_trip(self) -> None:
        quoted = sectors._quote("a\tb\rc")
        parsed = tomllib.loads(f"key = {quoted}\n")
        assert parsed["key"] == "a\tb\rc"

    def test_an_unnamed_control_character_is_escaped_as_unicode(self) -> None:
        value = "x" + chr(0x01) + "y"
        quoted = sectors._quote(value)
        parsed = tomllib.loads(f"key = {quoted}\n")
        assert parsed["key"] == value

    def test_backslash_and_quote_still_escape_correctly_alongside_a_control_char(self) -> None:
        value = 'a"b\\c\nd'
        quoted = sectors._quote(value)
        parsed = tomllib.loads(f"key = {quoted}\n")
        assert parsed["key"] == value

    def test_set_sector_with_a_control_character_in_the_label_produces_parseable_toml(
        self, settings: Settings
    ) -> None:
        # `sector` still has to be in the frozen vocabulary for `set_sector` to accept it at all --
        # this proves the *symbol* side (arbitrary user input reaching the TOML key) stays safe when
        # it carries a control character, by round-tripping the whole file through tomllib.
        path = settings.data_dir / sectors.SECTORS_FILENAME
        symbol = "EVIL\nSYMBOL"
        sectors.set_sector(symbol, "SEMI", settings=settings)

        raw = path.read_text(encoding="utf-8")
        # The file as a whole must still parse -- this is the actual defect: an unescaped control
        # character breaking the surrounding TOML structure, not merely being stored oddly.
        reparsed = tomllib.loads(raw)
        assert reparsed["sectors"][symbol.upper()] == "SEMI"
