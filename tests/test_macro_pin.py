"""Tests for `app.rules.macro_pin` -- freezing the macro data a round is scored against.

The behaviours worth testing here are the refusals. A pin that round-trips is table stakes; a pin
that can be silently overwritten or hand-edited is not a pin at all, because the guarantee it exists
to provide is that the bytes a published figure was produced from are still the bytes on disk.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from app.market.macro_models import MacroPoint, MacroSeries, MacroSource, MacroUnit
from app.rules.macro_pin import (
    MACRO_UNITS,
    PIN_FORMAT_VERSION,
    PinExistsError,
    PinIntegrityError,
    fetch_series_for_pin,
    pin_digest,
    read_pin,
    write_pin,
)
from app.rules.nodes import MacroField

_CREATED = dt.datetime(2026, 8, 30, 12, 0, 0)


def _series(field: MacroField, points: list[tuple[dt.date, float | None]]) -> MacroSeries:
    return MacroSeries(
        series_id=field.value,
        title=field.value,
        unit=MACRO_UNITS[field],
        source=MacroSource.FRED,
        points=[MacroPoint(date=d, value=v) for d, v in points],
    )


def _sample() -> dict[MacroField, MacroSeries]:
    return {
        MacroField.DGS10: _series(
            MacroField.DGS10, [(dt.date(2026, 6, 10), 4.5), (dt.date(2026, 6, 11), None)]
        ),
        MacroField.T10Y2Y: _series(MacroField.T10Y2Y, [(dt.date(2026, 6, 10), -0.2)]),
    }


class TestUnits:
    def test_every_macro_field_has_a_unit(self) -> None:
        """A missing unit would be defaulted or guessed downstream, and the unit decides how every
        change figure is computed -- `PERCENT_SPREAD` exists precisely because a spread that crosses
        zero must never be given a percentage change."""
        assert set(MACRO_UNITS) == set(MacroField)

    def test_the_price_indices_are_index_not_percent(self) -> None:
        """`CPILFESL` prints 336.789, an index level, not 336% -- mislabelling it `PERCENT` would
        format it as a rate and compute nonsense changes against it."""
        for field in (MacroField.PCEPI, MacroField.PCEPILFE, MacroField.CPILFESL):
            assert MACRO_UNITS[field] is MacroUnit.INDEX


class TestRoundTrip:
    def test_a_pin_round_trips_including_unobserved_points(self, tmp_path: Path) -> None:
        """A ``None`` is FRED's market-holiday gap. It must survive as ``None`` -- a pin that
        silently coerced it to 0.0 would hand the binding a real 0% yield on a day nobody traded."""
        pinned = _sample()
        path = tmp_path / "macro-pin.json"

        digest = write_pin(path, pinned, created_at=_CREATED)
        back = read_pin(path)

        assert pin_digest(back) == digest
        assert [(p.date, p.value) for p in back[MacroField.DGS10].points] == [
            (dt.date(2026, 6, 10), 4.5),
            (dt.date(2026, 6, 11), None),
        ]
        assert back[MacroField.T10Y2Y].unit is MacroUnit.PERCENT_SPREAD

    def test_the_digest_ignores_when_the_data_was_downloaded(self, tmp_path: Path) -> None:
        """Two pins of identical observations taken a minute apart must compare equal. Folding
        `fetched_at` into the hash would make every pin unique and the digest useless as the equality
        test it exists to be."""
        early = _sample()
        late = {
            field: series.model_copy(update={"fetched_at": dt.datetime(2027, 1, 1, 9, 0, 0)})
            for field, series in _sample().items()
        }

        assert pin_digest(early) == pin_digest(late)

    def test_a_changed_observation_changes_the_digest(self) -> None:
        """The other half of the property above: the digest must be sensitive to the thing it is
        supposed to protect. A hash that ignored values would pass every tamper test vacuously."""
        original = _sample()
        revised = _sample()
        revised[MacroField.DGS10] = _series(MacroField.DGS10, [(dt.date(2026, 6, 10), 4.6)])

        assert pin_digest(original) != pin_digest(revised)


class TestRefusals:
    def test_writing_over_an_existing_pin_is_refused(self, tmp_path: Path) -> None:
        """The central guarantee. An overwrite destroys the evidence for every figure already scored
        against the old bytes, so re-pinning must be a deliberate deletion rather than a side effect
        of re-running a script."""
        path = tmp_path / "macro-pin.json"
        write_pin(path, _sample(), created_at=_CREATED)

        with pytest.raises(PinExistsError, match="refusing to overwrite"):
            write_pin(path, _sample(), created_at=_CREATED)

    def test_an_edited_pin_is_refused_rather_than_warned_about(self, tmp_path: Path) -> None:
        """A digest that only warned would let a hand-edited series through under the authority of a
        recorded hash, which is worse than having no hash at all."""
        path = tmp_path / "macro-pin.json"
        write_pin(path, _sample(), created_at=_CREATED)
        path.write_text(path.read_text(encoding="utf-8").replace("4.5", "9.9"), encoding="utf-8")

        with pytest.raises(PinIntegrityError, match="has been modified"):
            read_pin(path)

    def test_a_pin_from_an_older_format_is_refused_not_guessed_at(self, tmp_path: Path) -> None:
        path = tmp_path / "macro-pin.json"
        write_pin(path, _sample(), created_at=_CREATED)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["format_version"] = PIN_FORMAT_VERSION - 1
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(PinIntegrityError, match="format version"):
            read_pin(path)

    def test_a_series_name_that_is_not_a_macro_field_is_refused(self, tmp_path: Path) -> None:
        """A pin naming a series the DSL cannot reference means the pin and the enum disagree about
        what this round reads, and silently dropping it would let a card's field go unpinned."""
        path = tmp_path / "macro-pin.json"
        write_pin(path, _sample(), created_at=_CREATED)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["series"]["NOTASERIES"] = payload["series"]["DGS10"]
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(PinIntegrityError, match="not a MacroField"):
            read_pin(path)


class TestFetch:
    def test_each_field_is_fetched_with_its_declared_unit(self) -> None:
        """The provider does not know what a series *is*; the unit is supplied by the caller, so a
        wrong table here mislabels the data permanently at pin time."""
        seen: list[tuple[str, MacroUnit]] = []

        class _Provider:
            def fetch_series(self, series_id: str, *, unit: MacroUnit) -> MacroSeries:
                seen.append((series_id, unit))
                return MacroSeries(
                    series_id=series_id,
                    title=series_id,
                    unit=unit,
                    source=MacroSource.FRED,
                    points=[],
                )

        fetch_series_for_pin(list(MacroField), provider=_Provider())

        assert seen == [(f.value, MACRO_UNITS[f]) for f in MacroField]

    def test_a_field_is_fetched_once_even_if_requested_twice(self) -> None:
        calls: list[str] = []

        class _Provider:
            def fetch_series(self, series_id: str, *, unit: MacroUnit) -> MacroSeries:
                calls.append(series_id)
                return MacroSeries(
                    series_id=series_id,
                    title=series_id,
                    unit=unit,
                    source=MacroSource.FRED,
                    points=[],
                )

        fetch_series_for_pin(
            [MacroField.DGS10, MacroField.DGS10, MacroField.T10Y2Y], provider=_Provider()
        )

        assert calls == ["DGS10", "T10Y2Y"]
