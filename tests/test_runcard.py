"""Run cards: the audit trail that makes a result reproducible after the fact.

The property that matters is not "a file gets written" but "the same question against the same data
produces the same identity, and a different one cannot quietly overwrite it". These tests are mostly
about the second half.
"""

from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from app.backtest import runcard
from app.config import Settings
from app.db.duck import Interval


def _bars(n: int = 100, *, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + rng.normal(0.0, 1.0, size=n).cumsum()
    return pd.DataFrame(
        {
            "ts": pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"),
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "adj_close": close,
            "volume": np.full(n, 1e6),
        }
    )


def _card(bars: pd.DataFrame, **overrides: object) -> runcard.RunCard:
    kwargs: dict[str, object] = {
        "symbol": "QQQ",
        "interval": Interval.DAY,
        "params": {"horizon": 20, "alpha": 0.1},
        "bars": bars,
        "results": {"trials": 3},
    }
    kwargs.update(overrides)
    return runcard.make("scan", **kwargs)  # type: ignore[arg-type]


class TestIdentityIsContent:
    def test_the_same_question_against_the_same_data_gives_the_same_id(self) -> None:
        bars = _bars()
        assert _card(bars).run_id == _card(bars).run_id

    def test_key_order_does_not_change_the_params_hash(self) -> None:
        """`{"a": 1, "b": 2}` and `{"b": 2, "a": 1}` are the same question."""
        bars = _bars()
        first = _card(bars, params={"alpha": 0.1, "horizon": 20, "z": None})
        second = _card(bars, params={"z": None, "horizon": 20, "alpha": 0.1})
        assert first.params_hash == second.params_hash
        assert first.run_id == second.run_id

    def test_a_different_symbol_gives_a_different_id(self) -> None:
        bars = _bars()
        assert _card(bars).run_id != _card(bars, symbol="SPY").run_id

    def test_a_different_question_gives_a_different_id(self) -> None:
        bars = _bars()
        assert _card(bars).run_id != _card(bars, params={"horizon": 5, "alpha": 0.1}).run_id

    def test_floats_dates_enums_and_none_survive_and_hash_stably(self) -> None:
        bars = _bars()
        params: dict[str, object] = {
            "f": 0.30000000000000004,
            "d": dt.date(2026, 1, 15),
            "t": dt.datetime(2026, 1, 15, 12, 30, tzinfo=dt.UTC),
            "e": Interval.WEEK,
            "n": None,
            "list": [1, 2.5, "x"],
        }
        assert _card(bars, params=params).params_hash == _card(bars, params=params).params_hash


class TestDataFingerprint:
    def test_one_changed_close_changes_the_fingerprint_but_not_the_params_hash(self) -> None:
        """The whole point: a moved number under an unchanged question is otherwise
        indistinguishable from a code bug."""
        bars = _bars()
        moved = bars.copy()
        moved.loc[50, "close"] = float(moved.loc[50, "close"]) + 0.01

        original, revised = _card(bars), _card(moved)
        assert original.params_hash == revised.params_hash
        assert original.data_fingerprint != revised.data_fingerprint
        assert original.run_id != revised.run_id

    def test_a_longer_history_changes_the_fingerprint(self) -> None:
        assert _card(_bars(100)).data_fingerprint != _card(_bars(120)).data_fingerprint

    def test_the_same_bars_give_the_same_fingerprint(self) -> None:
        bars = _bars()
        assert runcard.fingerprint(bars, symbol="QQQ", interval=Interval.DAY) == runcard.fingerprint(
            bars, symbol="QQQ", interval=Interval.DAY
        )

    def test_an_empty_frame_is_fingerprinted_rather_than_crashing(self) -> None:
        empty = _bars(0)
        assert runcard.fingerprint(empty, symbol="QQQ", interval=Interval.DAY)


class TestImmutability:
    def test_writing_identical_content_twice_is_a_no_op(self, settings: Settings) -> None:
        """Re-running the same study must not error."""
        card = _card(_bars())
        first = runcard.write(card, settings=settings)
        second = runcard.write(card, settings=settings)
        assert first == second

    def test_a_different_payload_under_an_existing_id_is_refused(self, settings: Settings) -> None:
        """The check that makes this an audit trail rather than a cache. Constructed by hand-editing
        the card, because the content hash makes it otherwise unreachable -- which is the point, and
        also why the guard must exist for the case where it is not."""
        card = _card(_bars())
        runcard.write(card, settings=settings)
        tampered = card.model_copy(update={"results": {"trials": 999}})

        with pytest.raises(runcard.RunCardConflict):
            runcard.write(tampered, settings=settings)

    def test_the_stored_payload_is_unchanged_after_a_refused_write(
        self, settings: Settings
    ) -> None:
        card = _card(_bars())
        runcard.write(card, settings=settings)
        with pytest.raises(runcard.RunCardConflict):
            runcard.write(card.model_copy(update={"results": {"trials": 999}}), settings=settings)

        assert runcard.read(card.run_id, settings=settings).results == {"trials": 3}


class TestRoundTrip:
    def test_every_field_survives(self, settings: Settings) -> None:
        params: dict[str, object] = {
            "d": dt.date(2026, 1, 15),
            "f": 1.5,
            "n": None,
            "nested": {"a": [1, 2, 3]},
        }
        card = _card(_bars(), params=params, results={"trials": 7, "discoveries": 0})
        runcard.write(card, settings=settings)
        back = runcard.read(card.run_id, settings=settings)

        assert back.run_id == card.run_id
        assert back.kind == card.kind
        assert back.symbol == card.symbol
        assert back.interval is card.interval
        assert back.params == params
        assert back.results == {"trials": 7, "discoveries": 0}
        assert back.params_hash == card.params_hash
        assert back.data_fingerprint == card.data_fingerprint
        assert back.created_at == card.created_at

    def test_an_unknown_id_raises_a_specific_error(self, settings: Settings) -> None:
        """Not a bare `FileNotFoundError` leaking the storage layout to the API."""
        with pytest.raises(runcard.RunCardNotFound):
            runcard.read("a" * 64, settings=settings)

    def test_a_truncated_file_names_itself_rather_than_raising_json_errors(
        self, settings: Settings
    ) -> None:
        card = _card(_bars())
        path = runcard.write(card, settings=settings)
        path.write_text('{"run_id": "abc", "kind":', encoding="utf-8")

        with pytest.raises(runcard.RunCardCorrupt) as excinfo:
            runcard.read(card.run_id, settings=settings)
        assert str(path) in str(excinfo.value)

    def test_a_wrong_typed_field_is_caught_without_assertions(self, settings: Settings) -> None:
        """`python -O` strips `assert`, so validation must not depend on it -- a run of the app
        under optimisation would otherwise let a hand-edited card through."""
        card = _card(_bars())
        path = runcard.write(card, settings=settings)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["symbol"] = 12345
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(runcard.RunCardCorrupt):
            runcard.read(card.run_id, settings=settings)


class TestRecent:
    def test_newest_first_and_limit_respected(self, settings: Settings) -> None:
        cards = [_card(_bars(), params={"i": i}) for i in range(5)]
        for i, card in enumerate(cards):
            runcard.write(
                card.model_copy(
                    update={"created_at": dt.datetime(2026, 1, 1 + i, tzinfo=dt.UTC)}
                ),
                settings=settings,
            )

        listed = runcard.recent(limit=3, settings=settings)
        assert len(listed) == 3
        assert [c.created_at for c in listed] == sorted(
            (c.created_at for c in listed), reverse=True
        )

    def test_no_runs_is_an_empty_list_not_an_error(self, settings: Settings) -> None:
        assert runcard.recent(settings=settings) == []


class TestCodeVersion:
    def test_it_is_a_revision_or_the_literal_unknown(self) -> None:
        """Never a fabricated placeholder -- two different builds must not look identical."""
        version = _card(_bars()).code_version
        assert version == "unknown" or (version and all(c in "0123456789abcdef" for c in version))
