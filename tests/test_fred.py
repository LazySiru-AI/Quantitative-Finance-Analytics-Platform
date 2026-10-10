"""Tests for the FRED macro series provider.

Every test drives an ``httpx.MockTransport`` from the captured fixtures in
``tests/fixtures/macro/`` -- no test in this file makes a network call.

Three of the fixtures (``fred_json_unknown_series.json``, ``fred_json_bad_key.json``,
``fred_unknown_series.txt``) are exactly what was captured off the live endpoints: a first line
``HTTP <status>`` followed by the real response body. :func:`_load_http_fixture` splits the two back
apart so the test can hand the real status code and the real body to ``httpx.Response`` separately.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.market.macro_models import MacroSeries, MacroSource, MacroUnit
from app.market.models import MarketWarning
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
    SymbolNotFound,
)
from app.market.providers.fred import FredProvider

FIXTURES = Path(__file__).parent / "fixtures" / "macro"


def _load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _load_json(name: str) -> dict[str, Any]:
    return json.loads(_load_text(name))


def _load_http_fixture(name: str) -> tuple[int, str]:
    """Split a captured ``HTTP <status>\\n<body>`` fixture into ``(status, body)``."""
    raw = _load_text(name)
    first_line, _, body = raw.partition("\n")
    assert first_line.startswith("HTTP "), f"{name} does not start with an 'HTTP <status>' line"
    return int(first_line.removeprefix("HTTP ").strip()), body


def _client_returning(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _client_text(status_code: int, text: str) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=text)

    return _client_returning(handler)


def _client_json(status_code: int, payload: dict[str, Any]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return _client_returning(handler)


def _capturing_client(
    status_code: int, text: str
) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status_code, text=text)

    return _client_returning(handler), seen


# ---------------------------------------------------------------------------
# Gap conventions -- the single most important behaviour in this module
# ---------------------------------------------------------------------------


class TestGapConventions:
    def test_json_dot_marker_becomes_none(self) -> None:
        """The JSON API spells the 1993-01-18 (MLK Day) gap as the string '.'."""
        payload = _load_json("fred_json_dgs10.json")
        provider = FredProvider(_client_json(200, payload), api_key="dummy-key")

        series = provider.fetch_series("DGS10")

        gap_points = [p for p in series.points if p.date == dt.date(1993, 1, 18)]
        assert len(gap_points) == 1
        assert gap_points[0].value is None
        # Neighbouring rows are real numbers, not swept up by the same code path.
        assert [p.value for p in series.points if p.date == dt.date(1993, 1, 15)] == [6.60]
        assert [p.value for p in series.points if p.date == dt.date(1993, 1, 19)] == [6.59]

    def test_csv_empty_field_becomes_none(self) -> None:
        """The CSV endpoint spells the *same* 1993-01-18 gap as an empty field, not '.'."""
        text = _load_text("fred_missing_rows.csv")
        provider = FredProvider(_client_text(200, text))  # no api_key -> CSV path

        series = provider.fetch_series("DGS10")

        gap_points = [p for p in series.points if p.date == dt.date(1993, 1, 18)]
        assert len(gap_points) == 1
        assert gap_points[0].value is None
        assert len(series.points) == 16

    def test_gap_never_coerced_to_zero(self) -> None:
        """Regression guard for the exact failure mode called out in the design: a holiday
        collapsing the 10-year yield to 0.0 instead of leaving it unobserved."""
        text = _load_text("fred_missing_rows.csv")
        provider = FredProvider(_client_text(200, text))

        series = provider.fetch_series("DGS10")

        for point in series.points:
            if point.date == dt.date(1993, 1, 18):
                assert point.value is None
                assert point.value != 0.0

    def test_latest_skips_trailing_gap_rows(self) -> None:
        """MacroSeries.latest is written elsewhere, but this provider must feed it real gaps for the
        property to have anything to skip. FRED publishes the calendar forward of the data, so a
        series routinely ends on one or more unobserved rows."""
        text = (
            "observation_date,DGS10\n"
            "2024-01-02,3.91\n"
            "2024-01-03,3.97\n"
            "2024-01-04,\n"
            "2024-01-05,\n"
        )
        provider = FredProvider(_client_text(200, text))

        series = provider.fetch_series("DGS10")

        assert series.points[-1].value is None
        latest = series.latest
        assert latest is not None
        assert latest.date == dt.date(2024, 1, 3)
        assert latest.value == 3.97


# ---------------------------------------------------------------------------
# Both endpoints, real fixtures
# ---------------------------------------------------------------------------


class TestRealFixtures:
    def test_csv_dgs10_parses_full_fixture(self) -> None:
        text = _load_text("fred_dgs10.csv")
        provider = FredProvider(_client_text(200, text))

        series = provider.fetch_series("DGS10", unit=MacroUnit.PERCENT)

        assert len(series.points) == 400
        dates = [p.date for p in series.points]
        assert dates == sorted(dates)
        assert series.unit == MacroUnit.PERCENT
        assert series.source == MacroSource.FRED
        assert series.series_id == "DGS10"

    def test_csv_t10y2y_parses_and_allows_negative_values(self) -> None:
        text = _load_text("fred_t10y2y.csv")
        provider = FredProvider(_client_text(200, text))

        series = provider.fetch_series("T10Y2Y", unit=MacroUnit.PERCENT_SPREAD)

        assert len(series.points) == 400
        assert series.unit == MacroUnit.PERCENT_SPREAD

    def test_csv_dcoilwtico_parses(self) -> None:
        text = _load_text("fred_dcoilwtico.csv")
        provider = FredProvider(_client_text(200, text))

        series = provider.fetch_series("DCOILWTICO", unit=MacroUnit.USD)

        assert len(series.points) == 400
        assert series.unit == MacroUnit.USD

    @pytest.mark.parametrize(
        ("series_id", "unit"),
        [
            ("PCEPI", MacroUnit.INDEX),
            ("PCEPILFE", MacroUnit.INDEX),
            ("CPILFESL", MacroUnit.INDEX),
            ("T10YIE", MacroUnit.PERCENT),
        ],
    )
    def test_csv_round21_candidate_series_parse(self, series_id: str, unit: MacroUnit) -> None:
        """The four `MacroField` candidates that had no committed fixture until 2026-08-29.

        `strategy-program/ROUND-21-PLAN.md` §2a makes capturing these the round's first task, and
        gives the reason: all seven candidate series were fetched live and answered, but **a live
        check is evidence the endpoint replied today; a fixture is evidence the parser handles that
        shape and keeps handling it.** `DGS10`, `T10Y2Y` and `DCOILWTICO` had fixtures above and
        these did not, so half the round's candidate set rested on a changelog line.

        The three price indices are `INDEX`, not `PERCENT`: `PCEPI` and friends are index *levels*
        (2026-07 prints 131.659), not rates. That distinction is exactly why §3 of the plan
        disqualifies them from a bare-threshold macro gate -- a level that roughly triples across the
        window matrix is not a regime signal without a YoY transform the engine cannot express."""
        text = _load_text(f"fred_{series_id.lower()}.csv")
        provider = FredProvider(_client_text(200, text))

        series = provider.fetch_series(series_id, unit=unit)

        assert len(series.points) == 400
        assert series.series_id == series_id
        assert series.unit == unit
        assert series.source == MacroSource.FRED
        dates = [p.date for p in series.points]
        assert dates == sorted(dates), "points must be chronological for an as-of join to be valid"
        assert series.latest is not None
        assert series.latest.value is not None

    def test_csv_dcoilbrenteu_parses(self) -> None:
        text = _load_text("fred_dcoilbrenteu.csv")
        provider = FredProvider(_client_text(200, text))

        series = provider.fetch_series("DCOILBRENTEU", unit=MacroUnit.USD)

        assert len(series.points) == 400

    def test_json_dgs10_fixture_parses(self) -> None:
        payload = _load_json("fred_json_dgs10.json")
        provider = FredProvider(_client_json(200, payload), api_key="dummy-key")

        series = provider.fetch_series("DGS10")

        assert len(series.points) == len(payload["observations"])
        assert series.fetched_at is not None
        assert series.fetched_at.tzinfo is not None

    def test_precision_varies_across_rows_and_still_parses(self) -> None:
        """The same response can carry '4.47' and '4.6500000000'. Both are just floats."""
        payload = {
            "observations": [
                {"date": "2024-01-02", "value": "4.47"},
                {"date": "2024-01-03", "value": "4.6500000000"},
            ]
        }
        provider = FredProvider(_client_json(200, payload), api_key="dummy-key")

        series = provider.fetch_series("DGS10")

        assert series.points[0].value == pytest.approx(4.47)
        assert series.points[1].value == pytest.approx(4.65)


# ---------------------------------------------------------------------------
# Endpoint selection and request shape
# ---------------------------------------------------------------------------


class TestEndpointSelection:
    def test_uses_json_endpoint_when_api_key_configured(self) -> None:
        payload = {"observations": [{"date": "2024-01-02", "value": "4.5"}]}
        client, seen = _capturing_client(200, json.dumps(payload))
        provider = FredProvider(client, api_key="secret-key")

        provider.fetch_series("DGS10")

        assert len(seen) == 1
        request = seen[0]
        assert request.url.host == "api.stlouisfed.org"
        assert request.url.params["series_id"] == "DGS10"
        assert request.url.params["api_key"] == "secret-key"
        assert request.url.params["file_type"] == "json"

    def test_uses_csv_endpoint_when_no_api_key(self) -> None:
        client, seen = _capturing_client(200, "observation_date,DGS10\n2024-01-02,4.5\n")
        provider = FredProvider(client)

        provider.fetch_series("DGS10")

        assert len(seen) == 1
        request = seen[0]
        assert request.url.host == "fred.stlouisfed.org"
        assert request.url.params["id"] == "DGS10"
        assert "api_key" not in request.url.params

    def test_user_agent_is_honest_not_a_spoofed_browser(self) -> None:
        """FRED tarpits browser-shaped User-Agents -- see the module docstring. This must never be
        changed to look like Chrome/Firefox/Safari."""
        client, seen = _capturing_client(200, "observation_date,DGS10\n2024-01-02,4.5\n")
        provider = FredProvider(client)

        provider.fetch_series("DGS10")

        ua = seen[0].headers.get("user-agent", "")
        assert ua == "investing-dashboard/0.1"
        for spoofed in ("Mozilla", "Chrome", "Safari", "WebKit"):
            assert spoofed not in ua

    def test_observation_start_sent_on_json_request(self) -> None:
        payload = {"observations": [{"date": "2024-06-01", "value": "4.5"}]}
        client, seen = _capturing_client(200, json.dumps(payload))
        provider = FredProvider(client, api_key="secret-key")

        provider.fetch_series("DGS10", start=dt.date(2024, 6, 1))

        assert seen[0].url.params["observation_start"] == "2024-06-01"


# ---------------------------------------------------------------------------
# observation_start filtering (client-side, works regardless of server behaviour)
# ---------------------------------------------------------------------------


class TestStartFiltering:
    def test_json_points_before_start_are_dropped(self) -> None:
        payload = {
            "observations": [
                {"date": "2024-01-01", "value": "1.0"},
                {"date": "2024-01-02", "value": "2.0"},
                {"date": "2024-01-03", "value": "3.0"},
            ]
        }
        provider = FredProvider(_client_json(200, payload), api_key="dummy-key")

        series = provider.fetch_series("DGS10", start=dt.date(2024, 1, 2))

        assert [p.date for p in series.points] == [dt.date(2024, 1, 2), dt.date(2024, 1, 3)]

    def test_csv_points_before_start_are_dropped(self) -> None:
        text = "observation_date,DGS10\n2024-01-01,1.0\n2024-01-02,2.0\n2024-01-03,3.0\n"
        provider = FredProvider(_client_text(200, text))

        series = provider.fetch_series("DGS10", start=dt.date(2024, 1, 2))

        assert [p.date for p in series.points] == [dt.date(2024, 1, 2), dt.date(2024, 1, 3)]

    def test_start_after_every_observation_yields_empty_series_with_warning(self) -> None:
        text = "observation_date,DGS10\n2024-01-01,1.0\n2024-01-02,2.0\n"
        provider = FredProvider(_client_text(200, text))

        series = provider.fetch_series("DGS10", start=dt.date(2025, 1, 1))

        assert series.points == []
        assert any(w.kind == "short_history" for w in series.warnings)


# ---------------------------------------------------------------------------
# Empty / one-row series
# ---------------------------------------------------------------------------


class TestSmallSeries:
    def test_empty_json_observations_yields_empty_series_with_warning(self) -> None:
        payload = {"observations": []}
        provider = FredProvider(_client_json(200, payload), api_key="dummy-key")

        series = provider.fetch_series("DGS10")

        assert series.points == []
        assert series.latest is None
        assert len(series.warnings) == 1
        assert series.warnings[0].kind == "short_history"
        assert isinstance(series.warnings[0], MarketWarning)

    def test_empty_csv_body_yields_empty_series_with_warning(self) -> None:
        text = "observation_date,DGS10\n"
        provider = FredProvider(_client_text(200, text))

        series = provider.fetch_series("DGS10")

        assert series.points == []
        assert any(w.kind == "short_history" for w in series.warnings)

    def test_one_row_series_with_a_value(self) -> None:
        text = "observation_date,DGS10\n2024-01-02,4.5\n"
        provider = FredProvider(_client_text(200, text))

        series = provider.fetch_series("DGS10")

        assert len(series.points) == 1
        assert series.latest is not None
        assert series.latest.value == 4.5
        assert series.warnings == []

    def test_one_row_series_that_is_a_gap(self) -> None:
        text = "observation_date,DGS10\n2024-01-02,\n"
        provider = FredProvider(_client_text(200, text))

        series = provider.fetch_series("DGS10")

        assert len(series.points) == 1
        assert series.points[0].value is None
        assert series.latest is None


# ---------------------------------------------------------------------------
# Unknown series -- terminal on both endpoints
# ---------------------------------------------------------------------------


class TestUnknownSeries:
    def test_json_unknown_series_raises_symbol_not_found(self) -> None:
        status, body = _load_http_fixture("fred_json_unknown_series.json")
        provider = FredProvider(_client_text(status, body), api_key="dummy-key")

        with pytest.raises(SymbolNotFound):
            provider.fetch_series("NOTASERIES")

    def test_csv_unknown_series_raises_symbol_not_found(self) -> None:
        status, body = _load_http_fixture("fred_unknown_series.txt")
        assert status == 404
        provider = FredProvider(_client_text(status, body))

        with pytest.raises(SymbolNotFound):
            provider.fetch_series("NOTASERIES")


# ---------------------------------------------------------------------------
# Bad API key -- must NOT be confused with an unknown series
# ---------------------------------------------------------------------------


class TestBadApiKey:
    def test_bad_api_key_raises_provider_response_error_not_symbol_not_found(self) -> None:
        status, body = _load_http_fixture("fred_json_bad_key.json")
        assert status == 400
        provider = FredProvider(_client_text(status, body), api_key="wrong-key")

        with pytest.raises(ProviderResponseError) as excinfo:
            provider.fetch_series("DGS10")

        assert not isinstance(excinfo.value, SymbolNotFound)

    def test_bad_key_and_unknown_series_are_distinguishable(self) -> None:
        """The two real 400 bodies FRED returns must map to different exception types -- see the
        module docstring on why conflating them is dangerous (a bad key would look permanently
        wrong, or a genuinely missing series would look transient)."""
        key_status, key_body = _load_http_fixture("fred_json_bad_key.json")
        series_status, series_body = _load_http_fixture("fred_json_unknown_series.json")
        assert key_status == series_status == 400

        bad_key_provider = FredProvider(_client_text(key_status, key_body), api_key="wrong-key")
        unknown_series_provider = FredProvider(
            _client_text(series_status, series_body), api_key="dummy-key"
        )

        with pytest.raises(ProviderResponseError) as bad_key_exc:
            bad_key_provider.fetch_series("DGS10")
        with pytest.raises(SymbolNotFound):
            unknown_series_provider.fetch_series("NOTASERIES")

        assert not isinstance(bad_key_exc.value, SymbolNotFound)


# ---------------------------------------------------------------------------
# Transport-level failures
# ---------------------------------------------------------------------------


class TestTransportFailures:
    def test_json_429_raises_rate_limited_with_retry_after(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited", headers={"Retry-After": "30"})

        provider = FredProvider(_client_returning(handler), api_key="dummy-key")

        with pytest.raises(RateLimited) as excinfo:
            provider.fetch_series("DGS10")
        assert excinfo.value.retry_after == 30.0

    def test_csv_429_raises_rate_limited(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        provider = FredProvider(_client_returning(handler))

        with pytest.raises(RateLimited):
            provider.fetch_series("DGS10")

    def test_json_5xx_raises_provider_unavailable(self) -> None:
        provider = FredProvider(_client_text(503, "server error"), api_key="dummy-key")

        with pytest.raises(ProviderUnavailable):
            provider.fetch_series("DGS10")

    def test_csv_5xx_raises_provider_unavailable(self) -> None:
        provider = FredProvider(_client_text(500, "server error"))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_series("DGS10")

    def test_timeout_raises_provider_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        provider = FredProvider(_client_returning(handler))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_series("DGS10")

    def test_connect_error_raises_provider_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        provider = FredProvider(_client_returning(handler))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_series("DGS10")


# ---------------------------------------------------------------------------
# Malformed responses -- must raise, never silently corrupt or drop data
# ---------------------------------------------------------------------------


class TestMalformedCsv:
    def test_missing_header_raises(self) -> None:
        text = "2024-01-02,4.5\n2024-01-03,4.6\n"
        provider = FredProvider(_client_text(200, text))

        with pytest.raises(ProviderResponseError):
            provider.fetch_series("DGS10")

    def test_wrong_header_column_count_raises(self) -> None:
        text = "observation_date,DGS10,EXTRA\n2024-01-02,4.5,x\n"
        provider = FredProvider(_client_text(200, text))

        with pytest.raises(ProviderResponseError):
            provider.fetch_series("DGS10")

    def test_wrong_row_column_count_raises(self) -> None:
        text = "observation_date,DGS10\n2024-01-02,4.5,unexpected\n"
        provider = FredProvider(_client_text(200, text))

        with pytest.raises(ProviderResponseError):
            provider.fetch_series("DGS10")

    def test_non_numeric_non_gap_value_raises(self) -> None:
        """A value that is neither a float nor the CSV gap marker (empty field) must fail loudly,
        not be silently treated as a gap or coerced to 0."""
        text = "observation_date,DGS10\n2024-01-02,N/A\n"
        provider = FredProvider(_client_text(200, text))

        with pytest.raises(ProviderResponseError):
            provider.fetch_series("DGS10")

    def test_unparseable_date_raises(self) -> None:
        text = "observation_date,DGS10\nnot-a-date,4.5\n"
        provider = FredProvider(_client_text(200, text))

        with pytest.raises(ProviderResponseError):
            provider.fetch_series("DGS10")

    def test_empty_body_raises(self) -> None:
        provider = FredProvider(_client_text(200, ""))

        with pytest.raises(ProviderResponseError):
            provider.fetch_series("DGS10")


class TestMalformedJson:
    def test_non_numeric_non_gap_value_raises(self) -> None:
        payload = {"observations": [{"date": "2024-01-02", "value": "N/A"}]}
        provider = FredProvider(_client_json(200, payload), api_key="dummy-key")

        with pytest.raises(ProviderResponseError):
            provider.fetch_series("DGS10")

    def test_missing_observations_key_raises(self) -> None:
        payload = {"count": 0}
        provider = FredProvider(_client_json(200, payload), api_key="dummy-key")

        with pytest.raises(ProviderResponseError):
            provider.fetch_series("DGS10")

    def test_body_not_json_raises(self) -> None:
        provider = FredProvider(_client_text(200, "not json{"), api_key="dummy-key")

        with pytest.raises(ProviderResponseError):
            provider.fetch_series("DGS10")

    def test_observation_missing_date_raises(self) -> None:
        payload = {"observations": [{"value": "4.5"}]}
        provider = FredProvider(_client_json(200, payload), api_key="dummy-key")

        with pytest.raises(ProviderResponseError):
            provider.fetch_series("DGS10")

    def test_unparseable_date_raises(self) -> None:
        payload = {"observations": [{"date": "not-a-date", "value": "4.5"}]}
        provider = FredProvider(_client_json(200, payload), api_key="dummy-key")

        with pytest.raises(ProviderResponseError):
            provider.fetch_series("DGS10")


# ---------------------------------------------------------------------------
# Return shape
# ---------------------------------------------------------------------------


class TestReturnShape:
    def test_returns_macro_series_with_expected_provenance(self) -> None:
        text = "observation_date,DGS10\n2024-01-02,4.5\n"
        provider = FredProvider(_client_text(200, text))

        series = provider.fetch_series("DGS10", unit=MacroUnit.PERCENT)

        assert isinstance(series, MacroSeries)
        assert series.series_id == "DGS10"
        assert series.title == "DGS10"
        assert series.source == MacroSource.FRED
        assert series.unit == MacroUnit.PERCENT
        assert FredProvider.name == "fred"
