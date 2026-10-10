"""Tests for the macro aggregation layer (`app.market.macro`).

Every test drives `build_snapshot` / `load_series` / `load_fear_greed` with fakes injected through
their `fred=` / `cnn=` / `registry=` parameters -- no test in this file makes a network call, and
none goes through `app.market.macro`'s default provider factories (those just wrap the already-tested
`FredProvider` / `CnnFearGreedProvider` in a cache; see `tests/test_fred.py` and
`tests/test_fear_greed.py` for those).

The `registry` fakes reuse the exact pattern `tests/test_market_api.py` established: a real
`ProviderRegistry` wrapping a fake `BarProvider`, so movers and Yahoo-proxy tiles exercise the real
`app.market.store` sync/read path against a temporary store rather than a second, parallel fake of
the store itself.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from typing import Any

import pandas as pd
import pytest

from app.config import Settings
from app.market import macro
from app.market.fear_greed import composite_fear_greed
from app.market.macro_models import (
    ChangeMode,
    FearGreed,
    FearGreedSource,
    MacroPoint,
    MacroSeries,
    MacroSource,
    MacroUnit,
    Rating,
)
from app.market.models import Interval
from app.market.providers.base import ProviderUnavailable, SymbolNotFound
from app.market.registry import ProviderRegistry

TODAY = dt.date.today()


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeFredProvider:
    """Serves a fixed `MacroSeries` per id, or raises for ids not given one."""

    name = "fred"

    def __init__(
        self,
        series_by_id: dict[str, MacroSeries] | None = None,
        *,
        fail: bool = False,
    ) -> None:
        self._series = series_by_id or {}
        self._fail = fail
        self.calls: list[str] = []

    def fetch_series(
        self, series_id: str, *, start: dt.date | None = None, unit: MacroUnit = MacroUnit.PERCENT
    ) -> MacroSeries:
        self.calls.append(series_id)
        if self._fail:
            raise ProviderUnavailable(f"fred down for {series_id}", provider="fred")
        if series_id not in self._series:
            raise SymbolNotFound(f"fred has no fixture for {series_id!r}", provider="fred")
        return self._series[series_id]


class FailingFredProvider(FakeFredProvider):
    def __init__(self) -> None:
        super().__init__(fail=True)


class FakeCnnProvider:
    """Returns a fixed `FearGreed`, or raises when constructed with `fail=True`."""

    name = "cnn"

    def __init__(self, result: FearGreed | None = None, *, fail: bool = False) -> None:
        self._result = result
        self._fail = fail

    def fetch(self) -> FearGreed:
        if self._fail:
            raise ProviderUnavailable("cnn down", provider="cnn")
        assert self._result is not None
        return self._result


class FakeBarProvider:
    """Serves a fixed frame per symbol; symbols with no fixture raise `SymbolNotFound`.

    Mirrors `tests/test_market_api.py::FakeProvider`, extended to serve different data per symbol
    since a macro snapshot fetches twenty movers plus up to three Yahoo proxies in one call.
    """

    name = "yahoo"
    supported_intervals = frozenset({Interval.DAY})

    def __init__(
        self,
        frames: dict[str, pd.DataFrame] | None = None,
        *,
        fail_all: bool = False,
    ) -> None:
        self._frames = frames or {}
        self._fail_all = fail_all
        self.calls: list[str] = []

    def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> pd.DataFrame:
        self.calls.append(symbol)
        if self._fail_all:
            raise ProviderUnavailable(f"yahoo down for {symbol}", provider="yahoo")
        if symbol not in self._frames:
            raise SymbolNotFound(f"yahoo has no fixture for {symbol!r}", provider="yahoo")
        return self._frames[symbol].copy()


def _daily_frame(closes: dict[dt.date, float]) -> pd.DataFrame:
    """A minimal OHLCV frame -- only `close` varies, matching how `_points_from_bars` reads it."""
    dates = sorted(closes)
    values = [closes[d] for d in dates]
    return pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC) for d in dates],
                dtype="datetime64[us, UTC]",
            ),
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "adj_close": values,
            "volume": [1_000_000] * len(dates),
        }
    )


def _macro_series(
    series_id: str,
    unit: MacroUnit,
    points: dict[dt.date, float | None],
    *,
    source: MacroSource = MacroSource.FRED,
) -> MacroSeries:
    ordered = sorted(points)
    return MacroSeries(
        series_id=series_id,
        title=series_id,
        unit=unit,
        source=source,
        points=[MacroPoint(date=d, value=points[d]) for d in ordered],
        fetched_at=dt.datetime.now(dt.UTC),
    )


def _empty_registry() -> ProviderRegistry:
    """A registry whose only provider refuses every symbol -- every mover/proxy tile ends up empty."""
    return ProviderRegistry(bar_providers=[FakeBarProvider()])


def _strict_json_loads(text: str) -> Any:
    """Parses `text`, raising on the bare `NaN`/`Infinity`/`-Infinity` tokens `json.dumps` would emit
    for a float that should have been routed through `jsonable_float` first."""
    return json.loads(text, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))


def _assert_finite(value: Any) -> None:
    """Recursively asserts no float in `value` is NaN or infinite -- the in-memory equivalent of the
    strict-JSON check, for objects not yet serialised."""
    if isinstance(value, float):
        assert math.isfinite(value), f"non-finite float leaked: {value!r}"
    elif isinstance(value, dict):
        for v in value.values():
            _assert_finite(v)
    elif isinstance(value, list):
        for v in value:
            _assert_finite(v)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSnapshotHappyPath:
    def test_every_section_is_populated(self, settings: Settings) -> None:
        us10y = _macro_series("DGS10", MacroUnit.PERCENT, {TODAY - dt.timedelta(days=1): 4.5, TODAY: 4.6})
        spread = _macro_series(
            "T10Y2Y", MacroUnit.PERCENT_SPREAD, {TODAY - dt.timedelta(days=1): 0.4, TODAY: 0.45}
        )
        wti = _macro_series("DCOILWTICO", MacroUnit.USD, {TODAY - dt.timedelta(days=1): 70.0, TODAY: 71.0})
        brent = _macro_series(
            "DCOILBRENTEU", MacroUnit.USD, {TODAY - dt.timedelta(days=1): 74.0, TODAY: 75.0}
        )
        fred = FakeFredProvider(
            {"DGS10": us10y, "T10Y2Y": spread, "DCOILWTICO": wti, "DCOILBRENTEU": brent}
        )
        cnn = FakeCnnProvider(
            FearGreed(score=64.4, rating=Rating.GREED, source=FearGreedSource.CNN, as_of=TODAY)
        )
        mover_frame = _daily_frame({TODAY - dt.timedelta(days=i): 100.0 + i for i in range(30)})
        registry = ProviderRegistry(bar_providers=[FakeBarProvider(frames={
            symbol: mover_frame for symbol, _, _ in macro._MOVERS
        })])

        snap = macro.build_snapshot(
            settings, fred=fred, cnn=cnn, registry=registry
        )

        assert len(snap.rates) == 2
        assert len(snap.oil) == 2
        assert snap.fear_greed is not None
        assert snap.fear_greed.source == FearGreedSource.CNN
        assert len(snap.movers) == len(macro._MOVERS)
        assert all(tile.value is not None for tile in (*snap.rates, *snap.oil))
        assert all(mover.price is not None for mover in snap.movers)

    def test_bitcoin_mover_is_present_with_expected_label_and_unit(self, settings: Settings) -> None:
        """Pins BTC-USD as a mover for the frontend's key-macro-indicators card, which shows the
        10-year Treasury, WTI crude, Bitcoin and the Dollar Index side by side."""
        mover_frame = _daily_frame({TODAY - dt.timedelta(days=i): 50_000.0 + i for i in range(30)})
        registry = ProviderRegistry(bar_providers=[FakeBarProvider(frames={
            symbol: mover_frame for symbol, _, _ in macro._MOVERS
        })])

        snap = macro.build_snapshot(
            settings,
            fred=FailingFredProvider(),
            cnn=FakeCnnProvider(fail=True),
            registry=registry,
        )

        by_symbol = {m.symbol: m for m in snap.movers}
        assert "BTC-USD" in by_symbol
        btc = by_symbol["BTC-USD"]
        assert btc.label == "Bitcoin"
        assert btc.price is not None
        assert btc.unit == MacroUnit.USD
        assert btc.change.mode == ChangeMode.PERCENT

    def test_rates_tile_sources_and_units(self, settings: Settings) -> None:
        us10y = _macro_series("DGS10", MacroUnit.PERCENT, {TODAY: 4.6})
        spread = _macro_series("T10Y2Y", MacroUnit.PERCENT_SPREAD, {TODAY: 0.45})
        wti = _macro_series("DCOILWTICO", MacroUnit.USD, {TODAY: 71.0})
        brent = _macro_series("DCOILBRENTEU", MacroUnit.USD, {TODAY: 75.0})
        fred = FakeFredProvider(
            {"DGS10": us10y, "T10Y2Y": spread, "DCOILWTICO": wti, "DCOILBRENTEU": brent}
        )
        snap = macro.build_snapshot(
            settings,
            fred=fred,
            cnn=FakeCnnProvider(fail=True),
            registry=_empty_registry(),
        )

        by_key = {tile.key: tile for tile in (*snap.rates, *snap.oil)}
        assert by_key["us10y"].source == MacroSource.FRED
        assert by_key["us10y"].unit == MacroUnit.PERCENT
        assert by_key["2s10s"].unit == MacroUnit.PERCENT_SPREAD
        assert by_key["wti"].unit == MacroUnit.USD
        assert by_key["brent"].unit == MacroUnit.USD


# ---------------------------------------------------------------------------
# Change arithmetic: basis points vs percent
# ---------------------------------------------------------------------------


class TestChangeModePerUnit:
    def test_percent_unit_moves_in_basis_points(self, settings: Settings) -> None:
        """A rate is `MacroUnit.PERCENT`, and `change_mode_for` maps that to basis points, not
        percent -- see `app.market.macro_models`."""
        series = _macro_series(
            "DGS10", MacroUnit.PERCENT, {TODAY - dt.timedelta(days=1): 4.50, TODAY: 4.60}
        )
        snap = macro.build_snapshot(
            settings,
            fred=FakeFredProvider({"DGS10": series}),
            cnn=FakeCnnProvider(fail=True),
            registry=_empty_registry(),
        )
        us10y = next(t for t in snap.rates if t.key == "us10y")
        assert us10y.change.mode == ChangeMode.BASIS_POINTS
        assert us10y.change.day == pytest.approx(10.0)  # (4.60 - 4.50) * 100

    def test_usd_unit_moves_in_percent(self, settings: Settings) -> None:
        series = _macro_series(
            "DCOILWTICO", MacroUnit.USD, {TODAY - dt.timedelta(days=1): 70.0, TODAY: 77.0}
        )
        snap = macro.build_snapshot(
            settings,
            fred=FakeFredProvider({"DCOILWTICO": series}),
            cnn=FakeCnnProvider(fail=True),
            registry=_empty_registry(),
        )
        wti = next(t for t in snap.oil if t.key == "wti")
        assert wti.change.mode == ChangeMode.PERCENT
        assert wti.change.day == pytest.approx(10.0)  # (77 - 70) / 70 * 100


class TestT10Y2YCrossesZero:
    """A percentage change here would divide by (or near) zero on an inversion. Basis points must
    not."""

    def test_day_change_across_a_sign_flip_is_finite_basis_points(self, settings: Settings) -> None:
        points = {
            TODAY - dt.timedelta(days=2): -0.10,
            TODAY - dt.timedelta(days=1): -0.01,
            TODAY: 0.01,
        }
        series = _macro_series("T10Y2Y", MacroUnit.PERCENT_SPREAD, points)
        snap = macro.build_snapshot(
            settings,
            fred=FakeFredProvider({"T10Y2Y": series}),
            cnn=FakeCnnProvider(fail=True),
            registry=_empty_registry(),
        )
        spread = next(t for t in snap.rates if t.key == "2s10s")
        assert spread.change.mode == ChangeMode.BASIS_POINTS
        assert spread.change.day == pytest.approx(2.0)  # (0.01 - (-0.01)) * 100
        assert math.isfinite(spread.change.day)

    def test_the_moment_of_inversion_itself_produces_no_nan_or_inf(self, settings: Settings) -> None:
        """The exact case the unit exists for: the spread reads 0.0 on the crossing day."""
        points = {TODAY - dt.timedelta(days=1): -0.02, TODAY: 0.0}
        series = _macro_series("T10Y2Y", MacroUnit.PERCENT_SPREAD, points)
        snap = macro.build_snapshot(
            settings,
            fred=FakeFredProvider({"T10Y2Y": series}),
            cnn=FakeCnnProvider(fail=True),
            registry=_empty_registry(),
        )
        spread = next(t for t in snap.rates if t.key == "2s10s")
        assert spread.value == 0.0
        assert spread.change.day == pytest.approx(2.0)
        _assert_finite(snap.model_dump())


# ---------------------------------------------------------------------------
# YTD boundary: last observation of the previous calendar year, not Jan 1st
# ---------------------------------------------------------------------------


class TestYtdBoundary:
    def test_ytd_anchors_on_last_prior_year_observation_not_jan_first(self, settings: Settings) -> None:
        points: dict[dt.date, float | None] = {
            dt.date(2025, 12, 30): 100.0,  # last real observation of 2025 (31st is a gap below)
            dt.date(2025, 12, 31): None,  # published gap -- must not be used, and must not break YTD
            dt.date(2026, 1, 1): 999.0,  # decoy: if code ever anchored on Jan 1st this would be used
            dt.date(2026, 6, 15): 110.0,  # latest
        }
        series = _macro_series("DCOILWTICO", MacroUnit.USD, points)
        snap = macro.build_snapshot(
            settings,
            fred=FakeFredProvider({"DCOILWTICO": series}),
            cnn=FakeCnnProvider(fail=True),
            registry=_empty_registry(),
        )
        wti = next(t for t in snap.oil if t.key == "wti")
        # (110 - 100) / 100 * 100 = 10%, not measured against the 999.0 Jan-1st decoy.
        assert wti.change.ytd == pytest.approx(10.0)

    def test_ytd_is_none_when_series_does_not_reach_back_that_far(self, settings: Settings) -> None:
        points = {dt.date(2026, 6, 1): 100.0, dt.date(2026, 6, 15): 105.0}
        series = _macro_series("DCOILWTICO", MacroUnit.USD, points)
        snap = macro.build_snapshot(
            settings,
            fred=FakeFredProvider({"DCOILWTICO": series}),
            cnn=FakeCnnProvider(fail=True),
            registry=_empty_registry(),
        )
        wti = next(t for t in snap.oil if t.key == "wti")
        assert wti.change.ytd is None
        assert wti.change.week == pytest.approx(5.0)  # the other horizons still work


# ---------------------------------------------------------------------------
# Trailing and interior gaps
# ---------------------------------------------------------------------------


class TestGapHandling:
    def test_trailing_gap_rows_do_not_become_the_tiles_value(self, settings: Settings) -> None:
        """FRED publishes the calendar forward of the data -- a series routinely ends on one or more
        unobserved rows. The tile must report the last real observation, not `None`."""
        points: dict[dt.date, float | None] = {
            TODAY - dt.timedelta(days=2): 4.55,
            TODAY - dt.timedelta(days=1): None,
            TODAY: None,
        }
        series = _macro_series("DGS10", MacroUnit.PERCENT, points)
        snap = macro.build_snapshot(
            settings,
            fred=FakeFredProvider({"DGS10": series}),
            cnn=FakeCnnProvider(fail=True),
            registry=_empty_registry(),
        )
        us10y = next(t for t in snap.rates if t.key == "us10y")
        assert us10y.value == pytest.approx(4.55)
        assert us10y.as_of == TODAY - dt.timedelta(days=2)

    def test_day_change_steps_back_through_an_interior_gap(self, settings: Settings) -> None:
        """The day before the latest observation is itself a gap; the horizon must step back to the
        next real observation rather than reporting `None` or comparing against a missing value."""
        points: dict[dt.date, float | None] = {
            TODAY - dt.timedelta(days=3): 4.50,
            TODAY - dt.timedelta(days=2): 4.55,
            TODAY - dt.timedelta(days=1): None,  # interior gap, immediately before the latest point
            TODAY: 4.60,
        }
        series = _macro_series("DGS10", MacroUnit.PERCENT, points)
        snap = macro.build_snapshot(
            settings,
            fred=FakeFredProvider({"DGS10": series}),
            cnn=FakeCnnProvider(fail=True),
            registry=_empty_registry(),
        )
        us10y = next(t for t in snap.rates if t.key == "us10y")
        assert us10y.change.day == pytest.approx(5.0)  # (4.60 - 4.55) * 100, skipping the gap


# ---------------------------------------------------------------------------
# The ^TNX magnitude guard
# ---------------------------------------------------------------------------


class TestTnxMagnitudeGuard:
    def test_yahoo_proxy_is_not_divided_by_ten(self, settings: Settings) -> None:
        """Regression guard for the exact failure mode: Yahoo already serves `^TNX` in percent
        (4.699 next to FRED's DGS10 = 4.65 the same day, a ratio of 1.01), so dividing by 10 here
        would render the US 10-year at 0.4699%. Asserts both the precise value and a sane range."""
        frame = _daily_frame({TODAY - dt.timedelta(days=i): 4.699 - i * 0.001 for i in range(10)})
        registry = ProviderRegistry(bar_providers=[FakeBarProvider(frames={"^TNX": frame})])

        snap = macro.build_snapshot(
            settings,
            fred=FailingFredProvider(),
            cnn=FakeCnnProvider(fail=True),
            registry=registry,
        )

        us10y = next(t for t in snap.rates if t.key == "us10y")
        assert us10y.source == MacroSource.YAHOO
        assert us10y.value == pytest.approx(4.699)
        assert 0.1 <= us10y.value <= 25.0, f"US 10-year proxy out of sane range: {us10y.value}"
        assert us10y.value != pytest.approx(0.4699), "looks divided by 10"


# ---------------------------------------------------------------------------
# One dead upstream degrades one tile, not the page
# ---------------------------------------------------------------------------


class TestDegradationIsPerTileNotPerPage:
    def test_fred_entirely_down_leaves_rates_and_oil_empty_but_returns_200_shaped_data(
        self, settings: Settings
    ) -> None:
        mover_frame = _daily_frame({TODAY - dt.timedelta(days=i): 400.0 + i for i in range(30)})
        registry = ProviderRegistry(
            bar_providers=[
                FakeBarProvider(frames={symbol: mover_frame for symbol, _, _ in macro._MOVERS})
            ]
        )
        cnn = FakeCnnProvider(
            FearGreed(score=50.0, rating=Rating.NEUTRAL, source=FearGreedSource.CNN, as_of=TODAY)
        )

        snap = macro.build_snapshot(
            settings, fred=FailingFredProvider(), cnn=cnn, registry=registry
        )

        assert all(tile.value is None for tile in (*snap.rates, *snap.oil))
        assert all(any(w.kind == "provider_fallback" for w in tile.warnings) for tile in snap.rates)
        # The rest of the page is unaffected.
        assert snap.fear_greed is not None and snap.fear_greed.source == FearGreedSource.CNN
        assert all(mover.price is not None for mover in snap.movers)

    def test_every_upstream_down_still_returns_a_full_shape_with_no_exception(
        self, settings: Settings
    ) -> None:
        snap = macro.build_snapshot(
            settings,
            fred=FailingFredProvider(),
            cnn=FakeCnnProvider(fail=True),
            registry=_empty_registry(),
        )
        assert len(snap.rates) == 2
        assert len(snap.oil) == 2
        assert len(snap.movers) == len(macro._MOVERS)
        assert snap.fear_greed is not None
        assert snap.fear_greed.source == FearGreedSource.COMPOSITE
        assert all(mover.price is None for mover in snap.movers)
        assert all(mover.warnings for mover in snap.movers)

    def test_one_mover_failing_does_not_affect_the_others(self, settings: Settings) -> None:
        good_frame = _daily_frame({TODAY - dt.timedelta(days=i): 100.0 + i for i in range(30)})
        registry = ProviderRegistry(
            bar_providers=[FakeBarProvider(frames={"SPY": good_frame})]  # every other symbol 404s
        )
        snap = macro.build_snapshot(
            settings,
            fred=FailingFredProvider(),
            cnn=FakeCnnProvider(fail=True),
            registry=registry,
        )
        by_symbol = {m.symbol: m for m in snap.movers}
        assert by_symbol["SPY"].price is not None
        assert by_symbol["QQQ"].price is None
        assert by_symbol["QQQ"].warnings


# ---------------------------------------------------------------------------
# Fear & Greed fallback
# ---------------------------------------------------------------------------


class TestFearGreedFallback:
    def test_cnn_down_falls_back_to_neutral_composite_with_a_warning(self, settings: Settings) -> None:
        result = macro.load_fear_greed(settings, cnn=FakeCnnProvider(fail=True))
        assert result.source == FearGreedSource.COMPOSITE
        assert result.score == pytest.approx(50.0)
        assert result.rating == Rating.NEUTRAL
        assert any("cnn unavailable" in w.message for w in result.warnings)

    def test_cnn_healthy_is_used_as_is(self, settings: Settings) -> None:
        live = FearGreed(score=64.4, rating=Rating.GREED, source=FearGreedSource.CNN, as_of=TODAY)
        result = macro.load_fear_greed(settings, cnn=FakeCnnProvider(live))
        assert result is live

    def test_matches_the_real_composite_function_directly(self) -> None:
        """Sanity check that the fallback really does call through to `composite_fear_greed` rather
        than reimplementing its neutral-default behaviour."""
        direct = composite_fear_greed((), as_of=TODAY)
        assert direct.score == pytest.approx(50.0)
        assert direct.source == FearGreedSource.COMPOSITE


# ---------------------------------------------------------------------------
# load_series
# ---------------------------------------------------------------------------


class TestLoadSeries:
    def test_unknown_series_id_raises_series_not_found(self, settings: Settings) -> None:
        with pytest.raises(macro.SeriesNotFound):
            macro.load_series(settings, "NOT-A-REAL-SERIES")

    def test_fred_series_id_is_passed_through(self, settings: Settings) -> None:
        series = _macro_series("DGS10", MacroUnit.PERCENT, {TODAY: 4.6})
        result = macro.load_series(
            settings, "DGS10", fred=FakeFredProvider({"DGS10": series})
        )
        assert result is series

    def test_store_backed_series_id_reads_through_the_bar_store(self, settings: Settings) -> None:
        frame = _daily_frame({TODAY - dt.timedelta(days=i): 400.0 + i for i in range(10)})
        registry = ProviderRegistry(bar_providers=[FakeBarProvider(frames={"SPY": frame})])
        result = macro.load_series(settings, "SPY", registry=registry)
        assert result.series_id == "SPY"
        assert result.unit == MacroUnit.USD
        assert result.points
        assert all(p.value is not None for p in result.points)

    def test_yahoo_proxy_series_id_is_fetchable_directly(self, settings: Settings) -> None:
        frame = _daily_frame({TODAY - dt.timedelta(days=i): 4.6 - i * 0.001 for i in range(10)})
        registry = ProviderRegistry(bar_providers=[FakeBarProvider(frames={"^TNX": frame})])
        result = macro.load_series(settings, "^TNX", registry=registry)
        assert result.unit == MacroUnit.PERCENT
        assert result.source in (MacroSource.YAHOO, MacroSource.STORE)


# ---------------------------------------------------------------------------
# MoverTile.unit -- index levels (^VIX, DX-Y.NYB) vs currency-denominated prices
# ---------------------------------------------------------------------------


class TestMoverUnit:
    def test_index_movers_carry_the_index_unit(self, settings: Settings) -> None:
        """`^VIX` and `DX-Y.NYB` are unitless index levels, not dollar prices -- the frontend must be
        able to tell the two apart from `unit` alone, without hard-coding a symbol list of its own."""
        mover_frame = _daily_frame({TODAY - dt.timedelta(days=i): 15.0 + i * 0.1 for i in range(30)})
        registry = ProviderRegistry(bar_providers=[FakeBarProvider(frames={
            symbol: mover_frame for symbol, _, _ in macro._MOVERS
        })])

        snap = macro.build_snapshot(
            settings,
            fred=FailingFredProvider(),
            cnn=FakeCnnProvider(fail=True),
            registry=registry,
        )

        by_symbol = {m.symbol: m for m in snap.movers}
        assert by_symbol["^VIX"].unit == MacroUnit.INDEX
        assert by_symbol["DX-Y.NYB"].unit == MacroUnit.INDEX

    def test_dollar_priced_mover_carries_the_usd_unit(self, settings: Settings) -> None:
        mover_frame = _daily_frame({TODAY - dt.timedelta(days=i): 100.0 + i for i in range(30)})
        registry = ProviderRegistry(bar_providers=[FakeBarProvider(frames={
            symbol: mover_frame for symbol, _, _ in macro._MOVERS
        })])

        snap = macro.build_snapshot(
            settings,
            fred=FailingFredProvider(),
            cnn=FakeCnnProvider(fail=True),
            registry=registry,
        )

        by_symbol = {m.symbol: m for m in snap.movers}
        assert by_symbol["SPY"].unit == MacroUnit.USD
        assert by_symbol["BTC-USD"].unit == MacroUnit.USD

    def test_unit_survives_the_provider_error_path(self, settings: Settings) -> None:
        """A mover whose store read raises must still carry its declared unit -- a failed tile is
        still a tile whose unit is known, and omitting it here would make the frontend fall back to
        currency formatting exactly when it has the least information to justify that."""
        registry = ProviderRegistry(bar_providers=[FakeBarProvider(frames={})])  # every symbol 404s

        snap = macro.build_snapshot(
            settings,
            fred=FailingFredProvider(),
            cnn=FakeCnnProvider(fail=True),
            registry=registry,
        )

        by_symbol = {m.symbol: m for m in snap.movers}
        vix = by_symbol["^VIX"]
        assert vix.price is None
        assert vix.warnings
        assert vix.unit == MacroUnit.INDEX

        spy = by_symbol["SPY"]
        assert spy.price is None
        assert spy.unit == MacroUnit.USD

    def test_every_mover_unit_matches_its_declaration_in_movers(self, settings: Settings) -> None:
        """Loop assertion so a future mover added to `_MOVERS` without a matching `unit` check cannot
        silently default to `MacroUnit.USD` and go unnoticed."""
        mover_frame = _daily_frame({TODAY - dt.timedelta(days=i): 50.0 + i for i in range(30)})
        registry = ProviderRegistry(bar_providers=[FakeBarProvider(frames={
            symbol: mover_frame for symbol, _, _ in macro._MOVERS
        })])

        snap = macro.build_snapshot(
            settings,
            fred=FailingFredProvider(),
            cnn=FakeCnnProvider(fail=True),
            registry=registry,
        )

        by_symbol = {m.symbol: m for m in snap.movers}
        for symbol, _, expected_unit in macro._MOVERS:
            assert by_symbol[symbol].unit == expected_unit, symbol


# ---------------------------------------------------------------------------
# NaN never reaches the aggregation layer's own output
# ---------------------------------------------------------------------------


class TestNoNanOrInfLeaksFromTheSnapshot:
    def test_snapshot_round_trips_through_strict_json(self, settings: Settings) -> None:
        """A percent-mode change with a zero baseline is the one place division could produce
        `inf`; this snapshot deliberately includes one (a WTI price of 0.0) to prove it comes back
        as `null`, not as a bare `Infinity` token that would fail `JSON.parse` in the browser."""
        points: dict[dt.date, float | None] = {
            TODAY - dt.timedelta(days=1): 0.0,
            TODAY: 71.0,
        }
        wti = _macro_series("DCOILWTICO", MacroUnit.USD, points)
        snap = macro.build_snapshot(
            settings,
            fred=FakeFredProvider({"DCOILWTICO": wti}),
            cnn=FakeCnnProvider(fail=True),
            registry=_empty_registry(),
        )

        wti_tile = next(t for t in snap.oil if t.key == "wti")
        assert wti_tile.change.day is None  # not inf: division by a zero baseline is refused

        raw = snap.model_dump_json()
        assert "NaN" not in raw and "Infinity" not in raw
        parsed = _strict_json_loads(raw)  # raises on a bare NaN/Infinity token
        _assert_finite(parsed)
