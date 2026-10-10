"""Integration tests for the macro HTTP API (`app.api.macro`).

`app.main` does not wire this router yet -- that is the orchestrator's job once every phase-5 module
lands, see the delivery report -- so the `app` fixture below builds its own minimal `FastAPI` app
around `macro.router`, the same way the router can be exercised in isolation before `app.main` grows
an `app.include_router(macro.router)` line. Once that line exists, these tests keep working unchanged:
they only depend on the router object and the `app.market.macro` module it calls into.

Every test patches `app.market.macro`'s default provider factories
(`_default_fred` / `_default_cnn` / `default_registry`) with fakes, the same pattern
`tests/test_market_api.py` uses for `app.api.market._registry`. No test here makes a network call.

Deliberately self-contained rather than importing fakes from `tests/test_macro.py`: this file's
fakes are duplicated in miniature (a few dozen lines) rather than shared, so this module never
depends on `tests` being importable as a package -- a cross-file `from tests.test_macro import ...`
is exactly the kind of import that breaks when pytest is invoked with explicit file paths and its
`pythonpath` ini setting is not picked up (observed locally: `pytest ../tests/test_macro_api.py`
without `-c backend/pyproject.toml` fails collection with `ModuleNotFoundError: No module named
'tests'`, even for the pre-existing `from tests.conftest import make_txn` pattern other test modules
already use). Keeping this file free of that dependency means it collects under either invocation.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import macro as macro_api
from app.config import Settings
from app.market import macro
from app.market.macro_models import (
    FearGreed,
    FearGreedSource,
    MacroPoint,
    MacroSeries,
    MacroUnit,
    Rating,
)
from app.market.models import Interval
from app.market.providers.base import ProviderUnavailable, SymbolNotFound
from app.market.registry import ProviderRegistry

TODAY = dt.date.today()


# ---------------------------------------------------------------------------
# Fakes -- see the module docstring for why these are not imported from tests/test_macro.py
# ---------------------------------------------------------------------------


class FakeFredProvider:
    name = "fred"

    def __init__(
        self, series_by_id: dict[str, MacroSeries] | None = None, *, fail: bool = False
    ) -> None:
        self._series = series_by_id or {}
        self._fail = fail

    def fetch_series(
        self, series_id: str, *, start: dt.date | None = None, unit: MacroUnit = MacroUnit.PERCENT
    ) -> MacroSeries:
        if self._fail:
            raise ProviderUnavailable(f"fred down for {series_id}", provider="fred")
        if series_id not in self._series:
            raise SymbolNotFound(f"fred has no fixture for {series_id!r}", provider="fred")
        return self._series[series_id]


class FakeCnnProvider:
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
    name = "yahoo"
    supported_intervals = frozenset({Interval.DAY})

    def __init__(self, frames: dict[str, pd.DataFrame] | None = None) -> None:
        self._frames = frames or {}

    def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> pd.DataFrame:
        if symbol not in self._frames:
            raise SymbolNotFound(f"yahoo has no fixture for {symbol!r}", provider="yahoo")
        return self._frames[symbol].copy()


def _daily_frame(closes: dict[dt.date, float]) -> pd.DataFrame:
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


def _macro_series(series_id: str, unit: MacroUnit, points: dict[dt.date, float]) -> MacroSeries:
    ordered = sorted(points)
    return MacroSeries(
        series_id=series_id,
        title=series_id,
        unit=unit,
        source=macro.MacroSource.FRED,
        points=[MacroPoint(date=d, value=points[d]) for d in ordered],
        fetched_at=dt.datetime.now(dt.UTC),
    )


def _working_registry(*, extra_symbols: tuple[str, ...] = ()) -> ProviderRegistry:
    """Every mover, plus any extra symbols a test needs (a Yahoo proxy like `^TNX`), all served."""
    frame = _daily_frame({TODAY - dt.timedelta(days=i): 100.0 + i for i in range(30)})
    symbols = [s for s, _, _ in macro._MOVERS] + list(extra_symbols)
    return ProviderRegistry(bar_providers=[FakeBarProvider(frames={s: frame for s in symbols})])


def _working_fred() -> FakeFredProvider:
    return FakeFredProvider(
        {
            "DGS10": _macro_series("DGS10", MacroUnit.PERCENT, {TODAY: 4.6}),
            "T10Y2Y": _macro_series("T10Y2Y", MacroUnit.PERCENT_SPREAD, {TODAY: 0.45}),
            "DCOILWTICO": _macro_series("DCOILWTICO", MacroUnit.USD, {TODAY: 71.0}),
            "DCOILBRENTEU": _macro_series("DCOILBRENTEU", MacroUnit.USD, {TODAY: 75.0}),
        }
    )


def _working_cnn() -> FakeCnnProvider:
    return FakeCnnProvider(
        FearGreed(score=64.4, rating=Rating.GREED, source=FearGreedSource.CNN, as_of=TODAY)
    )


def _fred_with_series(points: dict[dt.date, float]) -> FakeFredProvider:
    """A `FakeFredProvider` serving only `DGS10`, with an arbitrary caller-chosen date/value map.

    Distinct from `_working_fred`, which pins every series to a single `TODAY` observation --
    useless for truncation tests, which need more than one dated point to truncate *between*.
    """
    return FakeFredProvider({"DGS10": _macro_series("DGS10", MacroUnit.PERCENT, points)})


def _parse_dt(raw: str) -> dt.datetime:
    return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _strict_json_loads(text: str) -> Any:
    """Parses `text`, raising on a bare `NaN`/`Infinity`/`-Infinity` token -- the invalid-JSON shape
    `json.dumps` produces for a float that should have been routed through `jsonable_float` first."""
    return json.loads(text, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))


# ---------------------------------------------------------------------------
# App + fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """A bare app around just the macro router -- see the module docstring for why this does not
    import `app.main`."""
    fastapi_app = FastAPI()
    fastapi_app.include_router(macro_api.router)
    return fastapi_app


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch, app: FastAPI) -> TestClient:
    """A client whose FRED, CNN and bar-store providers are all working fakes.

    Individual tests override one of these three via `monkeypatch` again to exercise a degraded
    upstream, matching the layered-fixture style `tests/test_market_api.py` uses for its own client.
    """
    monkeypatch.setattr(macro, "_default_fred", lambda cfg, **_: _working_fred())
    monkeypatch.setattr(macro, "_default_cnn", lambda cfg, **_: _working_cnn())
    monkeypatch.setattr(macro, "default_registry", lambda *a, **kw: _working_registry())
    return TestClient(app)


# ---------------------------------------------------------------------------
# /api/macro/snapshot
# ---------------------------------------------------------------------------


class TestSnapshotEndpoint:
    def test_happy_path_returns_a_fully_populated_page(self, client: TestClient) -> None:
        response = client.get("/api/macro/snapshot")
        assert response.status_code == 200
        body = response.json()
        assert len(body["rates"]) == 2
        assert len(body["oil"]) == 2
        assert len(body["movers"]) == len(macro._MOVERS)
        assert body["fear_greed"]["source"] == "cnn"
        assert all(tile["value"] is not None for tile in (*body["rates"], *body["oil"]))

    def test_refresh_query_param_is_accepted(self, client: TestClient) -> None:
        assert client.get("/api/macro/snapshot?refresh=true").status_code == 200
        assert client.get("/api/macro/snapshot?refresh=false").status_code == 200

    def test_malformed_refresh_param_is_a_4xx_not_a_500(self, client: TestClient) -> None:
        response = client.get("/api/macro/snapshot?refresh=not-a-bool")
        assert 400 <= response.status_code < 500

    def test_one_dead_upstream_still_returns_200_with_the_rest_of_the_page_intact(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(macro, "_default_fred", lambda cfg, **_: FakeFredProvider(fail=True))

        response = client.get("/api/macro/snapshot")

        assert response.status_code == 200
        body = response.json()
        assert all(tile["value"] is None for tile in (*body["rates"], *body["oil"]))
        assert all(tile["warnings"] for tile in body["rates"])
        assert body["fear_greed"]["source"] == "cnn"  # unaffected by the FRED outage
        assert all(mover["price"] is not None for mover in body["movers"])

    def test_cnn_down_falls_back_to_composite_but_still_returns_200(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(macro, "_default_cnn", lambda cfg, **_: FakeCnnProvider(fail=True))

        response = client.get("/api/macro/snapshot")

        assert response.status_code == 200
        body = response.json()
        assert body["fear_greed"]["source"] == "composite"
        assert body["fear_greed"]["score"] == pytest.approx(50.0)

    def test_no_nan_or_infinity_token_reaches_the_wire(self, client: TestClient) -> None:
        """`json.dumps` renders a bare `NaN`/`Infinity` for an unguarded float, which is not valid
        JSON and fails `JSON.parse` in the browser. The real response body is parsed with a parser
        that raises on those tokens instead of silently accepting them."""
        raw = client.get("/api/macro/snapshot").text
        assert "NaN" not in raw and "Infinity" not in raw
        _strict_json_loads(raw)  # raises ValueError on a bare NaN/Infinity/-Infinity token

    def test_response_matches_the_macro_snapshot_shape(self, client: TestClient) -> None:
        """Field-for-field spot check against `frontend/src/api/macro.ts`'s `MacroSnapshot`."""
        body = client.get("/api/macro/snapshot").json()
        assert set(body) == {"generated_at", "rates", "oil", "fear_greed", "movers", "warnings"}
        tile = body["rates"][0]
        assert set(tile) == {
            "key",
            "label",
            "value",
            "unit",
            "as_of",
            "change",
            "spark",
            "source",
            "warnings",
        }
        assert set(tile["change"]) == {"mode", "day", "week", "month", "ytd"}


# ---------------------------------------------------------------------------
# /api/macro/series/{series_id}
# ---------------------------------------------------------------------------


class TestSeriesEndpoint:
    def test_known_fred_id_returns_its_series(self, client: TestClient) -> None:
        response = client.get("/api/macro/series/DGS10")
        assert response.status_code == 200
        body = response.json()
        assert body["series_id"] == "DGS10"
        assert body["source"] == "fred"

    def test_known_store_backed_id_returns_its_series(self, client: TestClient) -> None:
        response = client.get("/api/macro/series/SPY")
        assert response.status_code == 200
        assert response.json()["series_id"] == "SPY"

    def test_unknown_series_id_is_404_not_500(self, client: TestClient) -> None:
        response = client.get("/api/macro/series/NOT-A-REAL-SERIES")
        assert response.status_code == 404

    def test_series_url_round_trips_symbols_needing_escaping(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`^TNX` and `CL=F` carry characters that must be percent-encoded in a URL path; the
        frontend does this with `encodeURIComponent` (see `frontend/src/api/macro.ts`), and FastAPI
        must decode it back to the exact catalog key on the way in."""
        monkeypatch.setattr(
            macro,
            "default_registry",
            lambda *a, **kw: _working_registry(extra_symbols=("^TNX", "CL=F")),
        )

        response = client.get("/api/macro/series/%5ETNX")  # ^TNX
        assert response.status_code == 200
        assert response.json()["series_id"] == "^TNX"

        response = client.get("/api/macro/series/CL%3DF")  # CL=F
        assert response.status_code == 200
        assert response.json()["series_id"] == "CL=F"

    def test_fred_upstream_down_is_a_503_not_a_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(macro, "_default_fred", lambda cfg, **_: FakeFredProvider(fail=True))
        response = client.get("/api/macro/series/DGS10")
        assert response.status_code == 503

    def test_no_nan_or_infinity_token_reaches_the_wire(self, client: TestClient) -> None:
        raw = client.get("/api/macro/series/DGS10").text
        assert "NaN" not in raw and "Infinity" not in raw
        _strict_json_loads(raw)


# ---------------------------------------------------------------------------
# /api/macro/fear-greed
# ---------------------------------------------------------------------------


class TestFearGreedEndpoint:
    def test_happy_path(self, client: TestClient) -> None:
        response = client.get("/api/macro/fear-greed")
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "cnn"
        assert body["score"] == pytest.approx(64.4)

    def test_cnn_down_still_returns_200_via_the_composite(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(macro, "_default_cnn", lambda cfg, **_: FakeCnnProvider(fail=True))
        response = client.get("/api/macro/fear-greed")
        assert response.status_code == 200
        assert response.json()["source"] == "composite"

    def test_response_matches_the_fear_greed_shape(self, client: TestClient) -> None:
        body = client.get("/api/macro/fear-greed").json()
        assert set(body) >= {
            "score",
            "rating",
            "source",
            "as_of",
            "components",
            "previous_close",
            "previous_week",
            "previous_month",
            "previous_year",
            "history",
            "warnings",
        }

    def test_no_nan_or_infinity_token_reaches_the_wire(self, client: TestClient) -> None:
        raw = client.get("/api/macro/fear-greed").text
        assert "NaN" not in raw and "Infinity" not in raw
        _strict_json_loads(raw)


# ---------------------------------------------------------------------------
# `as_of` -- the no-lookahead bound (macro-snapshot-live-fetch-has-no-session-lookahead-boundary)
# ---------------------------------------------------------------------------


class TestAsOfTruncation:
    """`/api/macro/series/{id}` is the most direct place to see truncation: the response is just
    `points`, with no tile arithmetic layered on top to obscure what did or didn't get cut."""

    def test_truncates_between_two_real_observations(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`as_of` lands on a date with no observation of its own (the fixture is spaced every two
        days) -- the last point in the response must be the real observation immediately before it,
        not the nearest one on either side and not the whole series."""
        points = {
            TODAY - dt.timedelta(days=8): 10.0,
            TODAY - dt.timedelta(days=6): 20.0,
            TODAY - dt.timedelta(days=4): 30.0,
            TODAY - dt.timedelta(days=2): 40.0,
            TODAY: 50.0,
        }
        monkeypatch.setattr(macro, "_default_fred", lambda cfg, **_: _fred_with_series(points))
        as_of = TODAY - dt.timedelta(days=5)  # strictly between the day-6 and day-4 observations

        response = client.get(f"/api/macro/series/DGS10?as_of={as_of.isoformat()}")

        assert response.status_code == 200
        body = response.json()
        dates = [p["date"] for p in body["points"]]
        assert dates == [
            (TODAY - dt.timedelta(days=8)).isoformat(),
            (TODAY - dt.timedelta(days=6)).isoformat(),
        ]
        assert body["points"][-1]["value"] == pytest.approx(20.0)

    def test_observation_dated_exactly_as_of_is_included(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The off-by-one this feature could ship with: `as_of` is inclusive ("on or before"), so an
        observation dated exactly `as_of` must survive truncation, and the very next calendar day's
        observation must not."""
        as_of = TODAY - dt.timedelta(days=1)
        points = {as_of: 4.5, as_of + dt.timedelta(days=1): 4.9}
        monkeypatch.setattr(macro, "_default_fred", lambda cfg, **_: _fred_with_series(points))

        response = client.get(f"/api/macro/series/DGS10?as_of={as_of.isoformat()}")

        assert response.status_code == 200
        body = response.json()
        assert [p["date"] for p in body["points"]] == [as_of.isoformat()]
        assert body["points"][0]["value"] == pytest.approx(4.5)

    def test_omitting_as_of_returns_the_full_untruncated_series(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        points = {TODAY - dt.timedelta(days=i): float(i) for i in range(5)}
        monkeypatch.setattr(macro, "_default_fred", lambda cfg, **_: _fred_with_series(points))

        response = client.get("/api/macro/series/DGS10")

        assert response.status_code == 200
        body = response.json()
        assert len(body["points"]) == 5
        # `fetched_at` is a live "now" stamp, not pinned to any observation date -- see
        # TestAsOfGeneratedAt below for the bounded case.
        assert abs((dt.datetime.now(dt.UTC) - _parse_dt(body["fetched_at"])).total_seconds()) < 30

    def test_store_backed_series_is_also_truncated(self, client: TestClient) -> None:
        """`SPY` is served from the bar store, a structurally different code path from `DGS10`'s
        FRED fetch (`store.ensure_series(end=as_of)` plus `_truncate_to_as_of`, not just the
        latter) -- this exercises that path independently rather than trusting the FRED-side tests
        to stand in for it. `_working_registry` gives `SPY` 30 daily closes ending `TODAY`."""
        full = client.get("/api/macro/series/SPY").json()
        as_of = TODAY - dt.timedelta(days=10)

        response = client.get(f"/api/macro/series/SPY?as_of={as_of.isoformat()}")

        assert response.status_code == 200
        body = response.json()
        assert body["points"], "a 10-day-old bound must not empty a 30-day-deep series"
        assert all(dt.date.fromisoformat(p["date"]) <= as_of for p in body["points"])
        assert len(body["points"]) < len(full["points"])

    def test_as_of_before_every_observation_is_an_explicit_empty_series_not_a_zero(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        points = {TODAY - dt.timedelta(days=i): float(i) for i in range(5)}  # earliest = TODAY-4
        monkeypatch.setattr(macro, "_default_fred", lambda cfg, **_: _fred_with_series(points))
        as_of = TODAY - dt.timedelta(days=100)

        response = client.get(f"/api/macro/series/DGS10?as_of={as_of.isoformat()}")

        assert response.status_code == 200
        body = response.json()
        assert body["points"] == []
        assert any(w["kind"] == "short_history" for w in body["warnings"])
        assert any(as_of.isoformat() in w["message"] for w in body["warnings"])

    def test_unparseable_as_of_is_422_not_500(self, client: TestClient) -> None:
        for path in (
            "/api/macro/snapshot?as_of=not-a-date",
            "/api/macro/series/DGS10?as_of=not-a-date",
            "/api/macro/fear-greed?as_of=not-a-date",
        ):
            assert client.get(path).status_code == 422, path


class TestAsOfDerivedFigures:
    """Requirement (3): a change/level figure computed from truncated data must actually be
    recomputed, not carried over from the unbounded fetch relabelled with a new date."""

    def test_mover_price_and_day_change_differ_when_truncated(self, client: TestClient) -> None:
        """`_working_registry` gives every mover, including `SPY`, 30 daily closes with
        `value = 100 + days_before_today` -- deterministic and strictly monotonic, so truncating to
        an earlier `as_of` must change both the reported price and its day-over-day change, not just
        the `as_of` label on an unchanged number."""
        live = client.get("/api/macro/snapshot").json()
        as_of = TODAY - dt.timedelta(days=10)
        bounded = client.get(f"/api/macro/snapshot?as_of={as_of.isoformat()}").json()

        live_spy = next(m for m in live["movers"] if m["symbol"] == "SPY")
        bounded_spy = next(m for m in bounded["movers"] if m["symbol"] == "SPY")

        assert live_spy["price"] == pytest.approx(100.0)
        assert bounded_spy["price"] == pytest.approx(110.0)
        assert bounded_spy["as_of"] == as_of.isoformat()
        assert live_spy["change"]["day"] is not None
        assert bounded_spy["change"]["day"] is not None
        assert live_spy["change"]["day"] != pytest.approx(bounded_spy["change"]["day"])


class TestAsOfGeneratedAt:
    """Requirement (4): `generated_at` must stop being unconditionally "now" once a bound is in
    force, and must never be mistakable for a live timestamp."""

    def test_generated_at_is_now_when_as_of_is_omitted(self, client: TestClient) -> None:
        body = client.get("/api/macro/snapshot").json()
        generated_at = _parse_dt(body["generated_at"])
        assert abs((dt.datetime.now(dt.UTC) - generated_at).total_seconds()) < 30

    def test_generated_at_is_the_bound_when_as_of_is_given(self, client: TestClient) -> None:
        as_of = TODAY - dt.timedelta(days=3)
        body = client.get(f"/api/macro/snapshot?as_of={as_of.isoformat()}").json()
        generated_at = _parse_dt(body["generated_at"])
        assert generated_at == dt.datetime.combine(as_of, dt.time.min, tzinfo=dt.UTC)
        # Not "now": a bounded response's timestamp must be visibly distinguishable from a live one.
        assert abs((dt.datetime.now(dt.UTC) - generated_at).total_seconds()) > 30

    def test_series_fetched_at_is_the_bound_when_as_of_is_given(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        points = {TODAY - dt.timedelta(days=i): float(i) for i in range(5)}
        monkeypatch.setattr(macro, "_default_fred", lambda cfg, **_: _fred_with_series(points))
        as_of = TODAY - dt.timedelta(days=2)

        body = client.get(f"/api/macro/series/DGS10?as_of={as_of.isoformat()}").json()

        assert _parse_dt(body["fetched_at"]) == dt.datetime.combine(
            as_of, dt.time.min, tzinfo=dt.UTC
        )


class TestAsOfFearGreed:
    """Requirement (5): CNN's reading is point-in-time with nothing to truncate, so an `as_of`
    request must not silently hand back today's live score under a historical-looking label."""

    def test_snapshot_withholds_fear_greed_when_as_of_is_given(self, client: TestClient) -> None:
        as_of = TODAY - dt.timedelta(days=1)

        body = client.get(f"/api/macro/snapshot?as_of={as_of.isoformat()}").json()

        assert body["fear_greed"] is None
        assert any(w["kind"] == "as_of_unsupported" for w in body["warnings"])

    def test_snapshot_still_serves_live_fear_greed_when_as_of_is_omitted(
        self, client: TestClient
    ) -> None:
        body = client.get("/api/macro/snapshot").json()
        assert body["fear_greed"]["source"] == "cnn"

    def test_fear_greed_endpoint_rejects_an_as_of_bound(self, client: TestClient) -> None:
        as_of = TODAY - dt.timedelta(days=1)

        response = client.get(f"/api/macro/fear-greed?as_of={as_of.isoformat()}")

        assert response.status_code == 422
        assert "as-of" in response.json()["detail"] or "as_of" in response.json()["detail"]

    def test_fear_greed_endpoint_unaffected_when_as_of_is_omitted(self, client: TestClient) -> None:
        response = client.get("/api/macro/fear-greed")
        assert response.status_code == 200
        assert response.json()["source"] == "cnn"


class TestRefreshBypassesTheProviderCache:
    """Regression guard for the bug where ``?refresh=true`` refreshed only the bar-store (Yahoo) half
    of the snapshot and left the FRED- and CNN-backed tiles served from their fixed 24h HTTP cache.

    The symptom was a *forced* refresh still showing a stale date -- e.g. the 10-Year Treasury tile a
    day behind FRED's own latest observation, with an identical rate value hiding the lag -- because
    ``refresh`` was threaded into the mover/proxy reads but never lowered the FRED/CNN client's TTL.
    ``build_snapshot(refresh=True)`` must build those clients at ``ttl=0`` so a forced refresh is a
    real round trip; ``refresh=False`` must keep the long macro TTL that stops an ordinary page open
    from re-downloading FRED's full CSV history.
    """

    def test_default_clients_are_zero_ttl_only_when_refreshing(self, settings: Settings) -> None:
        fred_cold = macro._default_fred(settings, refresh=True)
        fred_warm = macro._default_fred(settings, refresh=False)
        cnn_cold = macro._default_cnn(settings, refresh=True)
        cnn_warm = macro._default_cnn(settings, refresh=False)
        try:
            assert fred_cold._client._transport._default_ttl == 0.0  # type: ignore[attr-defined]
            assert fred_warm._client._transport._default_ttl == macro._MACRO_CACHE_TTL  # type: ignore[attr-defined]
            assert cnn_cold._client._transport._default_ttl == 0.0  # type: ignore[attr-defined]
            assert cnn_warm._client._transport._default_ttl == macro._MACRO_CACHE_TTL  # type: ignore[attr-defined]
        finally:
            for p in (fred_cold, fred_warm, cnn_cold, cnn_warm):
                p._client.close()  # type: ignore[attr-defined]

    def test_build_snapshot_threads_refresh_into_the_fred_and_cnn_clients(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, bool] = {}

        def fake_fred(cfg: Settings, *, refresh: bool = False) -> FakeFredProvider:
            seen["fred"] = refresh
            return _working_fred()

        def fake_cnn(cfg: Settings, *, refresh: bool = False) -> FakeCnnProvider:
            seen["cnn"] = refresh
            return _working_cnn()

        monkeypatch.setattr(macro, "_default_fred", fake_fred)
        monkeypatch.setattr(macro, "_default_cnn", fake_cnn)
        monkeypatch.setattr(macro, "default_registry", lambda cfg: _working_registry())

        macro.build_snapshot(settings, refresh=True)
        assert seen == {"fred": True, "cnn": True}

        seen.clear()
        macro.build_snapshot(settings, refresh=False)
        assert seen == {"fred": False, "cnn": False}
