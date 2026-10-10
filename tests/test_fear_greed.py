"""Tests for the CNN Fear & Greed provider and the local fallback composite.

Every provider test drives an ``httpx.MockTransport`` from ``tests/fixtures/macro/
cnn_fear_greed.json`` -- no test in this file makes a network call. The fixture payload is
deep-copied before mutation so tests cannot bleed state into one another through a shared dict.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.market.fear_greed import composite_fear_greed
from app.market.macro_models import FearGreedComponent, FearGreedSource, Rating, rating_for
from app.market.providers.base import ProviderResponseError, ProviderUnavailable, RateLimited
from app.market.providers.cnn import CnnFearGreedProvider

FIXTURES = Path(__file__).parent / "fixtures" / "macro"


def _load_fixture() -> dict[str, Any]:
    return json.loads((FIXTURES / "cnn_fear_greed.json").read_text())


def _client_returning(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _client_json(status_code: int, payload: Any, headers: dict[str, str] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload, headers=headers or {})

    return _client_returning(handler)


def _client_raising(exc: Exception) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return _client_returning(handler)


def _provider(payload: Any, status_code: int = 200) -> CnnFearGreedProvider:
    return CnnFearGreedProvider(client=_client_json(status_code, payload))


# ---------------------------------------------------------------------------
# CNN provider: happy path
# ---------------------------------------------------------------------------


class TestCnnHappyPath:
    def test_parses_index_score_rating_and_provenance(self) -> None:
        payload = _load_fixture()
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        assert result.score == pytest.approx(64.4)
        assert result.rating == Rating.GREED
        assert result.source == FearGreedSource.CNN

    def test_parses_previous_period_fields(self) -> None:
        payload = _load_fixture()
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        assert result.previous_close == pytest.approx(63.6857142857143)
        assert result.previous_week == pytest.approx(50.7428571428571)
        assert result.previous_month == pytest.approx(46.82857142857143)
        assert result.previous_year == pytest.approx(58.37142857142857)

    def test_parses_all_seven_components_with_raw_value_and_no_score(self) -> None:
        payload = _load_fixture()
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        keys = {c.key for c in result.components}
        assert keys == {
            "market_momentum_sp500",
            "stock_price_strength",
            "stock_price_breadth",
            "put_call_options",
            "market_volatility_vix",
            "junk_bond_demand",
            "safe_haven_demand",
        }
        for component in result.components:
            assert component.raw_value is not None
            assert component.score is None  # CNN never publishes the normalisation -- never invented

    def test_component_raw_values_are_the_underlying_measurement_not_a_score(self) -> None:
        """market_momentum_sp500's raw_value is the S&P level (~7753), not a 0-100 figure."""
        payload = _load_fixture()
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        momentum = next(c for c in result.components if c.key == "market_momentum_sp500")
        assert momentum.raw_value == pytest.approx(7753.11)

        vix = next(c for c in result.components if c.key == "market_volatility_vix")
        assert vix.raw_value == pytest.approx(15.46)

        put_call = next(c for c in result.components if c.key == "put_call_options")
        assert put_call.raw_value == pytest.approx(0.686367809139791)

    def test_every_component_carries_its_unit(self) -> None:
        """The test above is exactly why this one exists.

        `market_momentum_sp500` is ~7753 and `put_call_options` is ~0.69 — an index level and a
        ratio, correctly parsed, and rendered until now as two bare decimals in adjacent rows under
        a column headed "Raw". The model's own docstring said they were "not comparable across
        components" while the UI presented them as though they were.
        """
        payload = _load_fixture()
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        assert len(result.components) == 7
        for component in result.components:
            assert component.raw_unit, f"{component.key} has no unit"
            assert component.raw_description, f"{component.key} has no description"

        by_key = {c.key: c for c in result.components}
        assert by_key["market_momentum_sp500"].raw_unit == "index"
        assert by_key["put_call_options"].raw_unit == "ratio"
        assert by_key["junk_bond_demand"].raw_unit == "pp"

    def test_a_component_with_no_data_still_carries_its_unit(self) -> None:
        """The unit describes the measurement, not the reading, so an absent value keeps it.

        Dropping it on the missing path would make the one row a reader most needs explained — the
        one showing an em dash — the only row with nothing explaining what it would have held.
        """
        payload = _load_fixture()
        del payload["market_volatility_vix"]
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        vix = next(c for c in result.components if c.key == "market_volatility_vix")
        assert vix.raw_value is None
        assert vix.raw_unit == "index"
        assert vix.raw_description

    def test_an_unknown_component_key_gets_no_invented_unit(self) -> None:
        """`units_for` returns nothing for a key it does not know.

        Inferring a unit from the magnitude of the number is how a ratio gets labelled an index.
        """
        assert FearGreedComponent.units_for("something_cnn_added_later") == (None, None)

    def test_history_is_parsed_and_ascending_by_date(self) -> None:
        payload = _load_fixture()
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        assert len(result.history) == 40
        dates = [p.date for p in result.history]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# CNN provider: epoch-millisecond conversion
# ---------------------------------------------------------------------------


class TestCnnEpochConversion:
    def test_history_point_lands_on_the_real_date_not_1970(self) -> None:
        payload = _load_fixture()
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        last_point = result.history[-1]
        # Fixture's last historical `x` is 1786406393000.0 ms -> 2026-08-10 UTC. Getting the /1000
        # wrong lands this thousands of years away from 2026, not anywhere near it.
        assert last_point.date == dt.date(2026, 8, 10)
        assert last_point.date.year > 2000

    def test_component_as_of_lands_on_the_real_date_not_1970(self) -> None:
        payload = _load_fixture()
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        momentum = next(c for c in result.components if c.key == "market_momentum_sp500")
        assert momentum.as_of == dt.date(2026, 8, 10)

    def test_top_level_as_of_matches_the_iso_timestamp(self) -> None:
        payload = _load_fixture()
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        assert result.as_of == dt.date(2026, 8, 10)


# ---------------------------------------------------------------------------
# CNN provider: malformed payloads
# ---------------------------------------------------------------------------


class TestCnnMalformedPayload:
    def test_missing_top_level_key_raises_provider_response_error(self) -> None:
        payload = _load_fixture()
        del payload["fear_and_greed"]
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        with pytest.raises(ProviderResponseError):
            provider.fetch()

    def test_renamed_top_level_key_raises_provider_response_error(self) -> None:
        payload = _load_fixture()
        payload["fear_and_greed_renamed"] = payload.pop("fear_and_greed")
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        with pytest.raises(ProviderResponseError):
            provider.fetch()

    def test_component_block_absent_entirely_degrades_gracefully(self) -> None:
        payload = _load_fixture()
        del payload["market_volatility_vix"]
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        vix = next(c for c in result.components if c.key == "market_volatility_vix")
        assert vix.raw_value is None
        assert vix.rating is None
        assert any("market_volatility_vix" in w.message for w in result.warnings)
        # The rest of the index is still usable -- one missing component does not fail the whole
        # fetch.
        assert result.score == pytest.approx(64.4)

    def test_component_with_empty_data_array_degrades_gracefully(self) -> None:
        payload = _load_fixture()
        payload["put_call_options"]["data"] = []
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        put_call = next(c for c in result.components if c.key == "put_call_options")
        assert put_call.raw_value is None
        assert any("put_call_options" in w.message for w in result.warnings)

    def test_historical_block_with_empty_data_array_yields_empty_history(self) -> None:
        payload = _load_fixture()
        payload["fear_and_greed_historical"]["data"] = []
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        assert result.history == []
        assert any("historical" in w.message for w in result.warnings)

    def test_non_numeric_y_in_history_becomes_a_published_gap(self) -> None:
        payload = _load_fixture()
        payload["fear_and_greed_historical"]["data"][-1]["y"] = "N/A"
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        assert result.history[-1].value is None
        # The date is still usable even though the value is not.
        assert result.history[-1].date == dt.date(2026, 8, 10)

    def test_non_numeric_y_in_component_falls_back_to_the_last_numeric_point(self) -> None:
        """The fallback must carry the *fallback point's own date*, not the latest row's.

        The fixture's last two VIX points both fall on 2026-08-10 (epochs 1786320000000 and
        1786392901000), so corrupting only the final row cannot distinguish "kept the right date"
        from "kept the last date" -- an earlier version of this test corrupted one row and asserted
        2026-08-07, a date neither epoch decodes to. Corrupting both forces the scan back across a
        real day boundary, where reporting a stale value under today's date would be a live claim
        that a three-day-old reading is current.
        """
        payload = _load_fixture()
        payload["market_volatility_vix"]["data"][-1]["y"] = "bad"
        payload["market_volatility_vix"]["data"][-2]["y"] = None
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        vix = next(c for c in result.components if c.key == "market_volatility_vix")
        # Third-from-last point in the fixture: y=14.9 at x=1786060800000.0 -> 2026-08-07 UTC.
        assert vix.raw_value == pytest.approx(14.9)
        assert vix.as_of == dt.date(2026, 8, 7)

    def test_component_where_every_point_is_non_numeric_reports_missing(self) -> None:
        payload = _load_fixture()
        for row in payload["junk_bond_demand"]["data"]:
            row["y"] = None
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        junk = next(c for c in result.components if c.key == "junk_bond_demand")
        assert junk.raw_value is None
        assert any("junk_bond_demand" in w.message for w in result.warnings)

    def test_the_rating_disagreement_case_trusts_the_top_level_rating(self) -> None:
        """Fixture: stock_price_strength is 'fear' at the top level but 'extreme fear' on its last
        historical point. The parser must trust the top-level rating."""
        payload = _load_fixture()
        block = payload["stock_price_strength"]
        assert block["rating"] == "fear"
        assert block["data"][-1]["rating"] == "extreme fear"
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        result = provider.fetch()

        strength = next(c for c in result.components if c.key == "stock_price_strength")
        assert strength.rating == Rating.FEAR

    def test_unrecognised_index_rating_raises_provider_response_error(self) -> None:
        payload = _load_fixture()
        payload["fear_and_greed"]["rating"] = "wildly greedy"
        provider = CnnFearGreedProvider(client=_client_json(200, payload))

        with pytest.raises(ProviderResponseError):
            provider.fetch()


# ---------------------------------------------------------------------------
# CNN provider: HTTP error mapping
# ---------------------------------------------------------------------------


class TestCnnHttpErrors:
    def test_404_is_provider_unavailable_not_terminal(self) -> None:
        provider = CnnFearGreedProvider(client=_client_json(404, {}))

        with pytest.raises(ProviderUnavailable):
            provider.fetch()

    def test_500_is_provider_unavailable(self) -> None:
        provider = CnnFearGreedProvider(client=_client_json(500, {}))

        with pytest.raises(ProviderUnavailable):
            provider.fetch()

    def test_timeout_is_provider_unavailable(self) -> None:
        provider = CnnFearGreedProvider(client=_client_raising(httpx.ConnectTimeout("boom")))

        with pytest.raises(ProviderUnavailable):
            provider.fetch()

    def test_429_is_rate_limited(self) -> None:
        provider = CnnFearGreedProvider(
            client=_client_json(429, {}, headers={"Retry-After": "30"})
        )

        with pytest.raises(RateLimited) as excinfo:
            provider.fetch()
        assert excinfo.value.retry_after == pytest.approx(30.0)

    def test_transport_error_is_provider_unavailable(self) -> None:
        provider = CnnFearGreedProvider(
            client=_client_raising(httpx.ConnectError("dns failure"))
        )

        with pytest.raises(ProviderUnavailable):
            provider.fetch()

    def test_invalid_json_is_provider_response_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json{{{")

        provider = CnnFearGreedProvider(client=_client_returning(handler))

        with pytest.raises(ProviderResponseError):
            provider.fetch()


# ---------------------------------------------------------------------------
# rating_for boundaries
# ---------------------------------------------------------------------------


class TestRatingForBoundaries:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (0.0, Rating.EXTREME_FEAR),
            (24.99, Rating.EXTREME_FEAR),
            (25.0, Rating.FEAR),
            (44.99, Rating.FEAR),
            (45.0, Rating.NEUTRAL),
            (54.99, Rating.NEUTRAL),
            (55.0, Rating.GREED),
            (74.99, Rating.GREED),
            (75.0, Rating.EXTREME_GREED),
            (100.0, Rating.EXTREME_GREED),
        ],
    )
    def test_boundary_values(self, score: float, expected: Rating) -> None:
        assert rating_for(score) == expected


# ---------------------------------------------------------------------------
# Composite: helpers
# ---------------------------------------------------------------------------

_AS_OF = dt.date(2026, 8, 10)

#: Calibration means, duplicated here (not imported from app.market.fear_greed) so a test that
#: accidentally breaks the module-private table still fails loudly rather than trivially passing
#: against whatever the implementation currently says its own mean is.
_MEANS: dict[str, float] = {
    "market_momentum_sp500": 7507.93,
    "stock_price_strength": 1.663,
    "stock_price_breadth": 903.71,
    "put_call_options": 0.7716,
    "market_volatility_vix": 17.067,
    "junk_bond_demand": 1.3123,
    "safe_haven_demand": 0.8364,
}

#: Calibration standard deviations, duplicated for the same reason as :data:`_MEANS`.
#:
#: These are what make "an extreme reading" expressible. A raw value is only extreme *relative to its
#: own dispersion*, and these components are on wildly different scales: 1e-6 is 65 standard
#: deviations below ``market_momentum_sp500``'s mean but a mere 0.39 below ``safe_haven_demand``'s,
#: which sits at 0.8364 with a standard deviation of 2.1563. A clamping test that pushes every
#: component to a literal 1e-6 is therefore not testing clamping at all for half of them.
_STDEVS: dict[str, float] = {
    "market_momentum_sp500": 115.67,
    "stock_price_strength": 0.364,
    "stock_price_breadth": 42.98,
    "put_call_options": 0.0472,
    "market_volatility_vix": 1.3583,
    "junk_bond_demand": 0.0466,
    "safe_haven_demand": 2.1563,
}

#: Components whose raw value moves *against* greed -- a higher reading is more fear.
_INVERTED = ("put_call_options", "market_volatility_vix", "junk_bond_demand")

_ALL_KEYS = tuple(_MEANS)


def _saturated(key: str, *, toward: str) -> float:
    """A raw value far enough from ``key``'s calibration mean to saturate its ``tanh`` mapping.

    Expressed in standard deviations rather than as a magic constant, so it saturates every
    component regardless of the scale it happens to be measured on. ``toward`` is the *sentiment*
    wanted, not the direction of the raw value -- the two differ for the inverted components, which
    is the whole point of naming it this way.
    """
    sign = 1.0 if (toward == "greed") != (key in _INVERTED) else -1.0
    return _MEANS[key] + sign * 50.0 * _STDEVS[key]


def _component(key: str, raw_value: float | None, as_of: dt.date = _AS_OF) -> FearGreedComponent:
    return FearGreedComponent(key=key, label=key, raw_value=raw_value, as_of=as_of)


def _full_neutral_set() -> list[FearGreedComponent]:
    """One component per key, each sitting exactly at its calibration mean -- a neutral baseline a
    test can nudge one key away from to isolate that key's effect on the composite."""
    return [_component(key, _MEANS[key]) for key in _ALL_KEYS]


def _with_override(key: str, raw_value: float) -> list[FearGreedComponent]:
    # Each component already carries its own key, so this reads it off the component rather than
    # zipping the list against `_ALL_KEYS` and relying on the two staying aligned.
    return [
        _component(c.key, raw_value) if c.key == key else c for c in _full_neutral_set()
    ]


# ---------------------------------------------------------------------------
# Composite: basic shape
# ---------------------------------------------------------------------------


class TestCompositeBasics:
    def test_full_set_at_calibration_means_scores_neutral(self) -> None:
        result = composite_fear_greed(_full_neutral_set(), as_of=_AS_OF)

        assert result.score == pytest.approx(50.0, abs=0.01)
        assert result.rating == Rating.NEUTRAL
        assert result.source == FearGreedSource.COMPOSITE
        assert result.as_of == _AS_OF
        assert result.warnings == []

    def test_components_carry_a_score_and_rating_unlike_cnn_sourced_ones(self) -> None:
        result = composite_fear_greed(_full_neutral_set(), as_of=_AS_OF)

        for component in result.components:
            assert component.score is not None
            assert component.rating is not None

    def test_rating_uses_the_shared_rating_for_bands(self) -> None:
        result = composite_fear_greed(_full_neutral_set(), as_of=_AS_OF)

        assert result.rating == rating_for(result.score)


# ---------------------------------------------------------------------------
# Composite: orientation, one component at a time
# ---------------------------------------------------------------------------


class TestCompositeOrientation:
    """Each of the seven components gets an explicit direction test. A VIX spike pushing the
    composite UP instead of DOWN is exactly the class of bug this module is built to catch."""

    def test_vix_spike_pushes_the_composite_down(self) -> None:
        baseline = composite_fear_greed(_full_neutral_set(), as_of=_AS_OF).score
        spiked = composite_fear_greed(
            _with_override("market_volatility_vix", _MEANS["market_volatility_vix"] * 3),
            as_of=_AS_OF,
        ).score

        assert spiked < baseline

    def test_vix_drop_pushes_the_composite_up(self) -> None:
        baseline = composite_fear_greed(_full_neutral_set(), as_of=_AS_OF).score
        dropped = composite_fear_greed(
            _with_override("market_volatility_vix", _MEANS["market_volatility_vix"] * 0.3),
            as_of=_AS_OF,
        ).score

        assert dropped > baseline

    def test_put_call_ratio_spike_pushes_the_composite_down(self) -> None:
        baseline = composite_fear_greed(_full_neutral_set(), as_of=_AS_OF).score
        spiked = composite_fear_greed(
            _with_override("put_call_options", _MEANS["put_call_options"] * 3),
            as_of=_AS_OF,
        ).score

        assert spiked < baseline

    def test_junk_bond_spread_widening_pushes_the_composite_down(self) -> None:
        baseline = composite_fear_greed(_full_neutral_set(), as_of=_AS_OF).score
        widened = composite_fear_greed(
            _with_override("junk_bond_demand", _MEANS["junk_bond_demand"] * 3),
            as_of=_AS_OF,
        ).score

        assert widened < baseline

    def test_sp500_momentum_rise_pushes_the_composite_up(self) -> None:
        baseline = composite_fear_greed(_full_neutral_set(), as_of=_AS_OF).score
        risen = composite_fear_greed(
            _with_override("market_momentum_sp500", _MEANS["market_momentum_sp500"] * 1.1),
            as_of=_AS_OF,
        ).score

        assert risen > baseline

    def test_stock_price_strength_rise_pushes_the_composite_up(self) -> None:
        baseline = composite_fear_greed(_full_neutral_set(), as_of=_AS_OF).score
        risen = composite_fear_greed(
            _with_override("stock_price_strength", _MEANS["stock_price_strength"] * 3),
            as_of=_AS_OF,
        ).score

        assert risen > baseline

    def test_stock_price_breadth_rise_pushes_the_composite_up(self) -> None:
        baseline = composite_fear_greed(_full_neutral_set(), as_of=_AS_OF).score
        risen = composite_fear_greed(
            _with_override("stock_price_breadth", _MEANS["stock_price_breadth"] * 1.5),
            as_of=_AS_OF,
        ).score

        assert risen > baseline

    def test_safe_haven_demand_rise_pushes_the_composite_up(self) -> None:
        """Higher safe_haven_demand raw value means stocks outperforming bonds -- risk-on -- so it
        is scored directly, not inverted."""
        baseline = composite_fear_greed(_full_neutral_set(), as_of=_AS_OF).score
        risen = composite_fear_greed(
            _with_override("safe_haven_demand", _MEANS["safe_haven_demand"] + 10.0),
            as_of=_AS_OF,
        ).score

        assert risen > baseline


# ---------------------------------------------------------------------------
# Composite: missing components
# ---------------------------------------------------------------------------


class TestCompositeMissingComponents:
    def test_one_missing_component_renormalises_and_warns(self) -> None:
        components = [c for c in _full_neutral_set() if c.key != "market_volatility_vix"]

        result = composite_fear_greed(components, as_of=_AS_OF)

        # The remaining six are all at their calibration mean, so the renormalised average is still
        # neutral -- proving the missing weight was redistributed rather than treated as zero (which
        # would drag the score toward extreme fear).
        assert result.score == pytest.approx(50.0, abs=0.01)
        assert len(result.warnings) == 1
        assert "market_volatility_vix" in result.warnings[0].message
        missing = next(c for c in result.components if c.key == "market_volatility_vix")
        assert missing.raw_value is None
        assert missing.score is None

    def test_three_missing_components_renormalise_and_warn_for_each(self) -> None:
        dropped = {"market_volatility_vix", "put_call_options", "junk_bond_demand"}
        components = [c for c in _full_neutral_set() if c.key not in dropped]

        result = composite_fear_greed(components, as_of=_AS_OF)

        assert result.score == pytest.approx(50.0, abs=0.01)
        assert len(result.warnings) == 3
        warned_keys = {key for key in dropped if any(key in w.message for w in result.warnings)}
        assert warned_keys == dropped
        for key in dropped:
            missing = next(c for c in result.components if c.key == key)
            assert missing.raw_value is None

    def test_a_missing_component_does_not_read_as_extreme_fear(self) -> None:
        """A component missing entirely must not silently act like a raw_value of 0 -- that would
        drag a genuinely neutral reading toward extreme fear."""
        components = [c for c in _full_neutral_set() if c.key != "safe_haven_demand"]

        result = composite_fear_greed(components, as_of=_AS_OF)

        assert result.rating != Rating.EXTREME_FEAR
        assert result.score == pytest.approx(50.0, abs=0.01)

    def test_component_present_but_raw_value_none_is_treated_as_missing(self) -> None:
        components = _full_neutral_set()
        components = [
            _component("market_volatility_vix", None) if c.key == "market_volatility_vix" else c
            for c in components
        ]

        result = composite_fear_greed(components, as_of=_AS_OF)

        assert len(result.warnings) == 1
        assert result.score == pytest.approx(50.0, abs=0.01)

    def test_every_component_missing_falls_back_to_neutral_with_a_warning(self) -> None:
        result = composite_fear_greed([], as_of=_AS_OF)

        assert result.score == pytest.approx(50.0)
        assert result.rating == Rating.NEUTRAL
        assert len(result.warnings) == 7 + 1  # one per missing component, plus the fallback warning


# ---------------------------------------------------------------------------
# Composite: clamping
# ---------------------------------------------------------------------------


class TestCompositeClamping:
    def test_extreme_greed_inputs_clamp_at_100(self) -> None:
        components = [_component(key, _saturated(key, toward="greed")) for key in _ALL_KEYS]

        result = composite_fear_greed(components, as_of=_AS_OF)

        assert result.score <= 100.0
        assert result.score == pytest.approx(100.0, abs=0.5)

    def test_extreme_fear_inputs_clamp_at_0(self) -> None:
        components = [_component(key, _saturated(key, toward="fear")) for key in _ALL_KEYS]

        result = composite_fear_greed(components, as_of=_AS_OF)

        assert result.score >= 0.0
        assert result.score == pytest.approx(0.0, abs=0.5)

    def test_every_component_individually_saturates_in_both_directions(self) -> None:
        """The clamping tests above are only meaningful if each component really does saturate.

        An earlier version of this file expressed "extreme" as a literal ``1e-6`` for every
        component, which is 65 standard deviations below ``market_momentum_sp500``'s mean but only
        0.39 below ``safe_haven_demand``'s -- so that component scored 40, not 0, and the aggregate
        clamping assertion failed for a reason that had nothing to do with clamping. This pins the
        per-component precondition directly, so the next such mistake names the component it broke.
        """
        for key in _ALL_KEYS:
            greedy = composite_fear_greed(
                [_component(key, _saturated(key, toward="greed"))], as_of=_AS_OF
            ).components
            fearful = composite_fear_greed(
                [_component(key, _saturated(key, toward="fear"))], as_of=_AS_OF
            ).components

            high = next(c for c in greedy if c.key == key).score
            low = next(c for c in fearful if c.key == key).score
            assert high is not None and low is not None
            assert high == pytest.approx(100.0, abs=0.5), f"{key} did not saturate toward greed"
            assert low == pytest.approx(0.0, abs=0.5), f"{key} did not saturate toward fear"

    def test_single_component_score_never_exceeds_the_0_100_bound(self) -> None:
        result = composite_fear_greed(
            [_component("market_volatility_vix", 100_000.0)], as_of=_AS_OF
        )

        vix = next(c for c in result.components if c.key == "market_volatility_vix")
        assert vix.score is not None
        assert 0.0 <= vix.score <= 100.0
        assert result.score >= 0.0
