"""Tests for `app.workflow.regime`: the deterministic live market-regime classifier and its static
regime -> strategy-card map.

No network calls anywhere in this file. Every `classify()` call is driven entirely by
`app.workflow.regime.RegimeMarketData` fixtures built in-process -- synthetic SPY-shaped OHLC frames,
hand-picked Fear & Greed component readings, and a plain float for the macro signal -- never
`app.market.store`, `app.market.macro`, or a live CNN/FRED provider. `load_regime_map`'s "validates
against the real library" test is the one place this file touches real on-disk data, and that data is
the strategy-card JSON already committed to the repository, not a network resource.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.config import Settings
from app.market.macro_models import FearGreedComponent
from app.workflow import regime as regime_mod
from app.workflow.regime import (
    RegimeCall,
    RegimeMapError,
    RegimeMarketData,
    classify,
    load_regime_map,
)

AS_OF = dt.date(2026, 8, 15)

# ---------------------------------------------------------------------------
# Synthetic SPY bar fixtures
#
# `classify`'s trend signal needs >= 210 bars (SMA(200) plus a 10-bar slope lookback) and its
# volatility signal needs >= 30 settled ATR% observations -- both comfortably covered by the 220-bar
# series built below. Each series' `close` moves along a smooth, hand-designed path (linear drift,
# not a compounding one -- see the note on `_BAND_NOISE`) so that trend direction and realized-vol
# percentile are both predictable and independently controllable, and every path is a plain Python/
# numpy expression with no random seed left implicit, so the same fixture produces the same frame on
# every run and every machine.
# ---------------------------------------------------------------------------

_N_BARS = 220

#: Deterministic (seeded) daily high/low band, as a fraction of that day's close. Real deterministic
#: series (a pure linear drift with a *constant* proportional band) turn out to make ATR%-of-close
#: monotonic across the whole window -- the smoothed-past-range-over-today's-close ratio drifts in one
#: direction for a compounding series with no noise at all, which would pin every fixture's volatility
#: percentile at 0 or 100 regardless of what the fixture is trying to test. A small fixed-seed
#: pseudo-random wobble around a calm baseline avoids that artifact while staying perfectly
#: reproducible (`RandomState(0)`, not `default_rng()` with no seed) -- this is a property of how the
#: *test fixtures* are built, not of `classify` itself, which never draws a random number.
_BAND_NOISE: np.ndarray = 0.004 + 0.0015 * np.random.RandomState(0).rand(_N_BARS)


def _make_spy_bars(closes: list[float], band_pct: np.ndarray | float = _BAND_NOISE) -> pd.DataFrame:
    """A minimal OHLCV frame `classify`'s signals accept: `ts` ascending, `high`/`low` a band around
    `close`, `open` the prior close. `band_pct` is a per-bar fraction of that day's close."""
    n = len(closes)
    dates = pd.date_range("2025-01-02", periods=n, freq="B", tz="UTC")
    close = pd.Series(closes, dtype=float)
    band = close * pd.Series(np.broadcast_to(band_pct, n), dtype=float)
    return pd.DataFrame(
        {
            "ts": dates,
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + band,
            "low": close - band,
            "close": close,
            "volume": 1_000_000,
        }
    )


def _uptrend_bars() -> pd.DataFrame:
    """A clean, calm uptrend: close above SMA(200), SMA(50) rising, volatility unremarkable.
    Verified (see this module's development notes) to vote `spy_trend=risk_on_trend`,
    `realized_vol=<abstain>`."""
    closes = [100.0 + 0.15 * i for i in range(_N_BARS)]
    return _make_spy_bars(closes)


def _downtrend_bars() -> pd.DataFrame:
    """A clean, calm downtrend: close below SMA(200), SMA(50) falling, volatility unremarkable.
    Votes `spy_trend=risk_off`, `realized_vol=<abstain>`."""
    closes = [200.0 - 0.15 * i for i in range(_N_BARS)]
    return _make_spy_bars(closes)


def _choppy_bars() -> pd.DataFrame:
    """170 sessions of the same calm uptrend followed by 50 sessions of an equally calm reversal --
    long enough a decline to turn SMA(50)'s slope negative, not long enough to pull the close below
    SMA(200) (which is still dominated by the longer uptrend segment). Close-vs-SMA(200) and the
    SMA(50) slope therefore disagree, which is exactly the "mixed" case `_spy_trend_signal` abstains
    on. Volatility stays unremarkable throughout. Votes `spy_trend=<abstain>`,
    `realized_vol=<abstain>`."""
    up_days, down_rate = 170, 0.15
    closes = [100.0 + 0.15 * i for i in range(up_days)]
    tail = closes[-1]
    closes += [tail - down_rate * i for i in range(1, _N_BARS - up_days + 1)]
    return _make_spy_bars(closes)


def _stress_bars() -> pd.DataFrame:
    """200 calm sessions (an oscillation with no net drift, banded at the same noise as the other
    fixtures) followed by 20 sessions whose *band* widens to 5% of close -- a genuine, deliberate
    volatility spike, not a drift artifact. Votes `realized_vol=high_vol_stress`; `spy_trend` happens
    to read `risk_on_trend` on this path (the calm segment drifts up very slightly), which is used
    deliberately in `test_high_vol_stress_reachable` to prove the volatility signal overrides the
    trend ballot rather than merely outvoting it."""
    calm_n = _N_BARS - 20
    calm = [150.0 + 0.01 * np.sin(i / 3) for i in range(calm_n)]
    tail = calm[-1]
    stress_tail = [tail + 0.02 * i for i in range(1, 21)]
    closes = calm + stress_tail
    band = np.concatenate([_BAND_NOISE[:calm_n], np.full(20, 0.05)])
    return _make_spy_bars(closes, band)


# ---------------------------------------------------------------------------
# Fear & Greed component fixtures -- see app.market.fear_greed.composite_fear_greed for the scoring.
# These raw values were chosen (and checked against composite_fear_greed directly) to land clearly on
# either side of the classifier's own _FEAR_VOTE_THRESHOLD / _GREED_VOTE_THRESHOLD, not near a
# boundary where a change to composite_fear_greed's calibration could flip the test.
# ---------------------------------------------------------------------------

_EXTREME_FEAR_COMPONENTS = (
    FearGreedComponent(
        key="market_volatility_vix", label="Market Volatility", raw_value=45.0, as_of=AS_OF
    ),
    FearGreedComponent(key="put_call_options", label="Put/Call", raw_value=1.3, as_of=AS_OF),
    FearGreedComponent(
        key="junk_bond_demand", label="Junk Bond Demand", raw_value=2.0, as_of=AS_OF
    ),
)

_EXTREME_GREED_COMPONENTS = (
    FearGreedComponent(
        key="market_volatility_vix", label="Market Volatility", raw_value=10.0, as_of=AS_OF
    ),
    FearGreedComponent(key="put_call_options", label="Put/Call", raw_value=0.5, as_of=AS_OF),
    FearGreedComponent(
        key="safe_haven_demand", label="Safe Haven Demand", raw_value=6.0, as_of=AS_OF
    ),
)


# ---------------------------------------------------------------------------
# 1. Determinism
# ---------------------------------------------------------------------------


def test_classify_is_deterministic(settings: Settings) -> None:
    """The same fixture inputs produce a bit-for-bit identical `RegimeCall` on repeat calls."""
    market = RegimeMarketData(
        spy_bars=_uptrend_bars(),
        fear_greed_components=_EXTREME_GREED_COMPONENTS,
        macro_2s10s_pct=0.6,
    )
    first = classify(settings=settings, as_of=AS_OF, market=market)
    second = classify(settings=settings, as_of=AS_OF, market=market)
    assert first == second
    assert isinstance(first, RegimeCall)


# ---------------------------------------------------------------------------
# 2. Every label is reachable
# ---------------------------------------------------------------------------


def test_risk_on_trend_reachable(settings: Settings) -> None:
    market = RegimeMarketData(
        spy_bars=_uptrend_bars(),
        fear_greed_components=_EXTREME_GREED_COMPONENTS,
        macro_2s10s_pct=0.6,  # steepening -> risk_on_trend vote
    )
    call = classify(settings=settings, as_of=AS_OF, market=market)
    assert call.label == "risk_on_trend"
    assert call.warnings == ()
    # trend, fear_greed and macro all voted risk_on_trend; only realized_vol abstained.
    assert float(call.confidence) == pytest.approx(0.75)


def test_risk_off_reachable(settings: Settings) -> None:
    market = RegimeMarketData(
        spy_bars=_downtrend_bars(),
        fear_greed_components=_EXTREME_FEAR_COMPONENTS,
        macro_2s10s_pct=-0.3,  # inverted -> risk_off vote
    )
    call = classify(settings=settings, as_of=AS_OF, market=market)
    assert call.label == "risk_off"
    assert call.warnings == ()
    assert float(call.confidence) == pytest.approx(0.75)


def test_choppy_neutral_reachable(settings: Settings) -> None:
    market = RegimeMarketData(
        spy_bars=_choppy_bars(),
        fear_greed_components=(),  # empty -> composite_fear_greed reports a neutral 50 -> abstain
        macro_2s10s_pct=0.2,  # flat, between the inversion and steepening cuts -> abstain
    )
    call = classify(settings=settings, as_of=AS_OF, market=market)
    assert call.label == "choppy_neutral"
    assert call.warnings == ()
    # Every signal was available; none of them voted choppy_neutral (it is only ever the fallback
    # when nothing else spoke), so agreement is honestly zero -- a low confidence is the correct
    # description of "nothing had a strong view", not a defect in the arithmetic.
    assert float(call.confidence) == pytest.approx(0.0)


def test_high_vol_stress_reachable_and_overrides_the_ballot(settings: Settings) -> None:
    """The volatility signal wins even when it is outnumbered on the three-way ballot.

    `_stress_bars` makes `spy_trend` vote `risk_on_trend`, and this test additionally feeds an
    extreme-fear reading and an inverted spread -- two more votes for `risk_off` -- so the ballot,
    taken alone, would be 2-1 for `risk_off`. `high_vol_stress` must still win, because the module's
    documented precedence rule is that a firing volatility signal decides the call outright rather
    than joining the ballot.
    """
    market = RegimeMarketData(
        spy_bars=_stress_bars(),
        fear_greed_components=_EXTREME_FEAR_COMPONENTS,  # would vote risk_off
        macro_2s10s_pct=-0.3,  # would vote risk_off
    )
    call = classify(settings=settings, as_of=AS_OF, market=market)
    assert call.label == "high_vol_stress"
    assert call.warnings == ()
    # Only realized_vol agrees with the final label -- trend and macro voted risk_off/risk_on_trend,
    # neither of which is high_vol_stress.
    assert float(call.confidence) == pytest.approx(0.25)
    vol_input = next(i for i in call.inputs if i.name == "realized_vol")
    assert vol_input.contributed is True
    trend_input = next(i for i in call.inputs if i.name == "spy_trend")
    assert trend_input.contributed is False


# ---------------------------------------------------------------------------
# 3. Provider degradation
# ---------------------------------------------------------------------------


def test_fear_greed_failure_degrades_to_a_warning_not_an_exception(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`composite_fear_greed` raising must not stop `classify` from returning a label -- it must
    degrade to a warning naming the failed signal and drop out of the confidence denominator."""

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("cnn raw component feed is malformed")

    monkeypatch.setattr(regime_mod, "composite_fear_greed", _boom)

    market = RegimeMarketData(
        spy_bars=_uptrend_bars(),
        fear_greed_components=_EXTREME_GREED_COMPONENTS,  # irrelevant: composite_fear_greed never runs
        macro_2s10s_pct=0.6,
    )
    call = classify(settings=settings, as_of=AS_OF, market=market)

    assert call.label == "risk_on_trend"  # trend + macro still agree; the call still completes
    assert len(call.warnings) == 1
    assert "fear_greed" in call.warnings[0]
    assert "cnn raw component feed is malformed" in call.warnings[0]

    fear_greed_input = next(i for i in call.inputs if i.name == "fear_greed")
    assert fear_greed_input.contributed is False
    assert "unavailable" in fear_greed_input.value

    # Denominator drops to the three signals that were actually available (spy_trend, realized_vol,
    # macro_2s10s); trend and macro both agree with the winning label, realized_vol abstained.
    assert float(call.confidence) == pytest.approx(2 / 3, abs=1e-4)


def test_missing_spy_bars_degrades_two_signals_independently(settings: Settings) -> None:
    """No `spy_bars` and no live store data behind it: `spy_trend` and `realized_vol` each fail on
    their own and are named separately, while the signals that do not depend on bars still work."""
    market = RegimeMarketData(
        spy_bars=None,  # nothing supplied, and nothing stored in this test's isolated store dir
        fear_greed_components=_EXTREME_FEAR_COMPONENTS,
        macro_2s10s_pct=-0.3,
    )
    call = classify(settings=settings, as_of=AS_OF, market=market)

    assert call.label == "risk_off"  # fear_greed + macro still agree
    warned_names = {w.split(" unavailable", 1)[0] for w in call.warnings}
    assert warned_names == {"spy_trend", "realized_vol"}
    assert float(call.confidence) == pytest.approx(1.0)  # both available signals agree with risk_off


# ---------------------------------------------------------------------------
# 4 & 5. load_regime_map
# ---------------------------------------------------------------------------


def test_load_regime_map_validates_against_the_real_library(settings: Settings) -> None:
    """The map this module ships resolves every agent_id against the real, on-disk card library --
    this is the test that would catch a typo'd agent_id in `regime_map.json`."""
    result = load_regime_map(settings=settings)

    assert set(result.keys()) == {
        "risk_on_trend",
        "risk_off",
        "choppy_neutral",
        "high_vol_stress",
    }
    for label, agent_ids in result.items():
        assert isinstance(agent_ids, tuple)
        assert len(agent_ids) > 0
        assert all(isinstance(a, str) and a for a in agent_ids), label


def test_load_regime_map_raises_on_a_nonexistent_agent_id(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A map referencing an `agent_id` no card carries fails loudly at load time, naming the label
    and the offending id -- not silently the next time a live run tries to trade that regime."""
    bad_map = tmp_path / "regime_map.json"
    bad_map.write_text(
        """
        {
          "_comment": "test fixture",
          "risk_on_trend": ["C-trend", "this-agent-id-does-not-exist"],
          "risk_off": ["c14-riskmanaged-wide"],
          "choppy_neutral": ["c07-chop"],
          "high_vol_stress": ["c19-volatility"]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(regime_mod, "_REGIME_MAP_PATH", bad_map)

    with pytest.raises(RegimeMapError) as excinfo:
        load_regime_map(settings=settings)

    message = str(excinfo.value)
    assert "this-agent-id-does-not-exist" in message
    assert "risk_on_trend" in message


def test_load_regime_map_raises_on_a_missing_label(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every one of the four labels must be covered -- a map that forgets one fails at load, not the
    first time a live run classifies into the label nobody wrote a roster for."""
    incomplete_map = tmp_path / "regime_map.json"
    incomplete_map.write_text(
        """
        {
          "risk_on_trend": ["C-trend"],
          "risk_off": ["c14-riskmanaged-wide"],
          "choppy_neutral": ["c07-chop"]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(regime_mod, "_REGIME_MAP_PATH", incomplete_map)

    with pytest.raises(RegimeMapError) as excinfo:
        load_regime_map(settings=settings)

    assert "high_vol_stress" in str(excinfo.value)
