"""Tests for `strategy-program/tools/storestate.py` -- the DEFECTS.md D6 store pin.

`strategy-program` is not a legal Python package name, so the module under test is loaded by file
path, the same way `tests/test_portfolio_tool.py` loads its own subject.

**What D6 actually asks for, and therefore what these tests check.** The defect is not "the store
changed" -- the store is *supposed* to change, because `data/store/` is gitignored mutable state and
ordinary use of the dashboard syncs fresh bars. The defect is that round 11 asserted the store was
unchanged by comparing against a row count transcribed from round 9's prose, a comparison with an
expiry date nobody stated. So the properties under test are:

1. a round records its evidence base as *data*, at run time;
2. a later round's comparison names which symbols moved and by how much;
3. an absent pin reports as *absent*, never as "unchanged" -- the failure mode that started this;
4. pinning is opt-in, so an already-published scorecard re-scored without it is unchanged.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from app.config import REPO_ROOT, Settings
from app.db import duck
from app.market.models import BAR_COLUMNS, Interval

_PATH = REPO_ROOT / "strategy-program" / "tools" / "storestate.py"
_spec = importlib.util.spec_from_file_location("strategy_program_tools_storestate", _PATH)
assert _spec is not None and _spec.loader is not None
storestate: ModuleType = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = storestate
_spec.loader.exec_module(storestate)


def _write_bars(settings: Settings, symbol: str, days: list[dt.date]) -> None:
    """One flat daily bar per date. Prices are inert here -- only the row count and the last
    timestamp are ever read back."""
    frame = pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC) for d in days],
                dtype="datetime64[us, UTC]",
            ),
            "open": [10.0] * len(days),
            "high": [11.0] * len(days),
            "low": [9.0] * len(days),
            "close": [10.5] * len(days),
            "adj_close": [10.5] * len(days),
            "volume": [1_000] * len(days),
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)


def _days(start: dt.date, n: int) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range(n)]


def _state(symbol: str, rows: int, last: str | None) -> object:
    return storestate.SymbolState(
        symbol=symbol, rows=rows, last_bar=dt.date.fromisoformat(last) if last else None
    )


def _pin(*states: object, at: str = "2026-08-20T00:00:00+00:00") -> object:
    return storestate.StoreState(
        captured_at=dt.datetime.fromisoformat(at), interval="1d", symbols=tuple(states)
    )


# ---------------------------------------------------------------------------
# capture -- against a real Parquet store
# ---------------------------------------------------------------------------


class TestCapture:
    def test_records_row_count_and_last_bar_per_symbol(self, settings: Settings) -> None:
        _write_bars(settings, "SPY", _days(dt.date(2026, 1, 1), 5))
        _write_bars(settings, "QQQ", _days(dt.date(2026, 1, 1), 3))

        pinned = storestate.capture(settings=settings)
        by_symbol = pinned.by_symbol()

        assert set(by_symbol) == {"SPY", "QQQ"}
        assert by_symbol["SPY"].rows == 5
        assert by_symbol["SPY"].last_bar == dt.date(2026, 1, 5)
        assert by_symbol["QQQ"].rows == 3
        assert pinned.total_rows == 8
        assert pinned.captured_at.tzinfo is not None

    def test_a_symbol_containing_an_equals_sign_is_captured(self, settings: Settings) -> None:
        """`BZ=F` (Brent futures) is in the real store, and its partition directory is `symbol=BZ=F`.

        DuckDB's `hive_partitioning = true` cannot split that into one key and one value and fails
        the *whole* scan with `Binder Error: Hive partition mismatch ... key "symbol" not found` --
        so one futures ticker would have cost the pin all 688 symbols, not just itself. `capture`
        groups by filename and parses the directory name instead. This test is the reason that is
        not a stylistic choice.
        """
        _write_bars(settings, "BZ=F", _days(dt.date(2026, 1, 1), 4))
        _write_bars(settings, "SPY", _days(dt.date(2026, 1, 1), 2))

        by_symbol = storestate.capture(settings=settings).by_symbol()

        assert by_symbol["BZ=F"].rows == 4
        assert by_symbol["SPY"].rows == 2

    def test_narrowing_to_named_symbols(self, settings: Settings) -> None:
        _write_bars(settings, "SPY", _days(dt.date(2026, 1, 1), 5))
        _write_bars(settings, "QQQ", _days(dt.date(2026, 1, 1), 3))

        pinned = storestate.capture(symbols=["SPY"], settings=settings)

        assert [s.symbol for s in pinned.symbols] == ["SPY"]

    def test_empty_store_pins_nothing(self, settings: Settings) -> None:
        pinned = storestate.capture(settings=settings)
        assert pinned.symbols == ()
        assert pinned.total_rows == 0


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_roundtrips_through_json(self, settings: Settings) -> None:
        _write_bars(settings, "SPY", _days(dt.date(2026, 1, 1), 5))
        _write_bars(settings, "BZ=F", _days(dt.date(2026, 1, 1), 2))
        pinned = storestate.capture(settings=settings)

        payload = json.loads(json.dumps(storestate.state_to_json(pinned)))
        restored = storestate.state_from_json(payload)

        assert restored.symbols == pinned.symbols
        assert restored.interval == pinned.interval

    def test_symbols_serialise_as_a_mapping_so_a_diff_is_one_line_per_symbol(self) -> None:
        payload = storestate.state_to_json(_pin(_state("SPY", 5, "2026-01-05")))
        assert payload["symbols"] == {"SPY": {"rows": 5, "last_bar": "2026-01-05"}}
        assert payload["symbol_count"] == 1
        assert payload["total_rows"] == 5

    def test_a_malformed_pin_is_refused_rather_than_read_as_empty(self) -> None:
        with pytest.raises(ValueError, match="mapping"):
            storestate.state_from_json({"captured_at": "2026-08-20T00:00:00+00:00", "symbols": []})


# ---------------------------------------------------------------------------
# compare -- the half that makes the pin worth taking
# ---------------------------------------------------------------------------


class TestCompare:
    def test_identical_stores_report_no_drift(self) -> None:
        pin = _pin(_state("SPY", 8445, "2026-08-18"), _state("QQQ", 6900, "2026-08-18"))

        drift = storestate.compare(pin, pin)

        assert drift.changed is False
        assert drift.unchanged == 2
        assert "unchanged" in storestate.describe_drift(drift)

    def test_the_round_11_case_names_the_symbol_and_the_delta(self) -> None:
        """This is the sentence round 11 should have been able to write.

        Its §0 said "the bar store is unchanged since round 9 ran -- verified, not assumed: SPY
        holds 8,445 rows ending 2026-08-18". By the end of that day it held 8,448 ending 08-21.
        """
        before = _pin(_state("SPY", 8445, "2026-08-18"))
        after = _pin(_state("SPY", 8448, "2026-08-21"), at="2026-08-22T00:00:00+00:00")

        drift = storestate.compare(before, after)
        (moved,) = drift.drifted

        assert drift.changed is True
        assert moved.symbol == "SPY"
        assert moved.kind == "appended"
        assert moved.row_delta == 3
        text = storestate.describe_drift(drift)
        assert "DIFFERS" in text
        assert "8445->8448" in text
        assert "2026-08-18 -> 2026-08-21" in text

    def test_a_shrinking_store_is_not_reported_as_an_append(self) -> None:
        drift = storestate.compare(_pin(_state("SPY", 100, "2026-08-18")), _pin(_state("SPY", 90, "2026-08-17")))
        (moved,) = drift.drifted
        assert moved.kind == "shrank"
        assert moved.row_delta == -10

    def test_same_row_count_with_a_different_last_bar_is_rewritten_not_unchanged(self) -> None:
        """The case a row count alone cannot see.

        A partition rebuilt over a shifted window keeps its count while changing what it contains.
        Reporting "0 rows added" would read as "unchanged", which is the exact class of false
        reassurance D6 is about.
        """
        drift = storestate.compare(
            _pin(_state("SPY", 100, "2026-08-18")), _pin(_state("SPY", 100, "2026-08-21"))
        )
        (moved,) = drift.drifted

        assert moved.kind == "rewritten"
        assert moved.row_delta == 0
        assert drift.changed is True
        assert "rewritten" in storestate.describe_drift(drift)

    def test_added_and_removed_symbols_are_distinguished(self) -> None:
        drift = storestate.compare(
            _pin(_state("SPY", 10, "2026-08-18"), _state("OLD", 5, "2026-08-18")),
            _pin(_state("SPY", 10, "2026-08-18"), _state("NEW", 7, "2026-08-18")),
        )

        kinds = {d.symbol: d.kind for d in drift.drifted}
        assert kinds == {"OLD": "removed", "NEW": "added"}
        assert drift.unchanged == 1

    def test_rows_added_sums_only_growth(self) -> None:
        drift = storestate.compare(
            _pin(_state("A", 10, "2026-08-18"), _state("B", 10, "2026-08-18")),
            _pin(_state("A", 14, "2026-08-19"), _state("B", 6, "2026-08-17")),
        )
        assert drift.rows_added == 4

    def test_describe_truncates_a_long_drift_list_and_says_so(self) -> None:
        before = _pin(*[_state(f"S{i}", 10, "2026-08-18") for i in range(20)])
        after = _pin(*[_state(f"S{i}", 11, "2026-08-19") for i in range(20)])

        text = storestate.describe_drift(storestate.compare(before, after), limit=3)

        assert "and 17 more" in text


# ---------------------------------------------------------------------------
# load_pin -- "no pin" must never read as "unchanged"
# ---------------------------------------------------------------------------


class TestLoadPin:
    def test_a_scorecard_without_a_pin_returns_none(self, tmp_path: Path) -> None:
        """Every round scored before this landed. `None` is what forces a caller to say "recorded no
        pin" instead of silently reporting an empty comparison as agreement."""
        path = tmp_path / "scorecard.json"
        path.write_text(json.dumps({"round": "r4", "ranked": []}), encoding="utf-8")

        assert storestate.load_pin(path) is None

    def test_a_scorecard_with_a_pin_round_trips(self, tmp_path: Path) -> None:
        pinned = _pin(_state("SPY", 8450, "2026-08-25"))
        path = tmp_path / "scorecard.json"
        path.write_text(
            json.dumps({"round": "r17", storestate.STORE_STATE_KEY: storestate.state_to_json(pinned)}),
            encoding="utf-8",
        )

        loaded = storestate.load_pin(path)

        assert loaded is not None
        assert loaded.by_symbol()["SPY"].rows == 8450
        assert loaded.by_symbol()["SPY"].last_bar == dt.date(2026, 8, 25)

    def test_a_non_object_pin_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "scorecard.json"
        path.write_text(json.dumps({storestate.STORE_STATE_KEY: "nope"}), encoding="utf-8")

        with pytest.raises(ValueError, match="not an object"):
            storestate.load_pin(path)


# ---------------------------------------------------------------------------
# The scorecard contract -- pinning must stay opt-in
# ---------------------------------------------------------------------------


class TestScorecardStaysReproducible:
    """`score.py`'s `_build_json` promises that rounds 2-4's published JSON gains no new top-level
    keys. D6 needs a new key. Both hold only because the key is omitted unless asked for -- so this
    is the test that stops a later "just always pin it" from silently breaking reproduction of every
    already-published round."""

    @staticmethod
    def _score_module() -> ModuleType:
        path = REPO_ROOT / "strategy-program" / "tools" / "score.py"
        spec = importlib.util.spec_from_file_location("strategy_program_tools_score_d6", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_omitted_by_default(self) -> None:
        score = self._score_module()
        out = score._build_json([], [], [], results_root=Path("x"), round_tag="r4")
        assert storestate.STORE_STATE_KEY not in out

    def test_present_only_when_supplied_and_adds_nothing_else(self) -> None:
        score = self._score_module()
        without = score._build_json([], [], [], results_root=Path("x"), round_tag="r4")
        with_pin = score._build_json(
            [],
            [],
            [],
            results_root=Path("x"),
            round_tag="r4",
            store_state=storestate.state_to_json(_pin(_state("SPY", 8450, "2026-08-25"))),
        )

        assert set(with_pin) - set(without) == {storestate.STORE_STATE_KEY}
        assert {k: v for k, v in with_pin.items() if k != storestate.STORE_STATE_KEY} == without
