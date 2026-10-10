"""Tests for `app.discovery.workflow_selectors` and `app.discovery.selector_bakeoff`.

Mirrors `tests/test_discovery.py`'s own conventions (`_weekdays`/`_write_bars`/`settings` fixture)
rather than inventing new ones. The load-bearing tests here are the point-in-time ones
(`test_*_ignores_future_bars`) -- the same property `test_discovery.py`'s
`test_selection_ignores_everything_after_as_of` exists to pin, extended to the new gate/hysteresis
logic this module adds on top of `app.discovery.selector.select` -- and
`test_hysteresis_holds_a_bounced_symbol_a_stateless_regate_would_drop`, which is the one test that
actually exercises the difference `select_for_workflow`'s carried `prior_picks` state makes over a
fresh, stateless re-gate every session.

Real `SECTOR_ETF_ROSTER` ticker symbols (`XLK`, `XLE`, `XLU`, `XLF`, `XLY`) are used throughout rather
than synthetic names, because `sector_candidates`/`theme_candidates` only ever look at the fixed
roster constants -- `StoredETFCandidates.symbols_as_of` silently excludes any ticker without stored
bars, so writing bars under five real roster names is what makes exactly those five show up as
candidates and nothing else in the roster does.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from app.config import Settings
from app.db import duck
from app.db.duck import BAR_COLUMNS, Interval
from app.discovery.candidates import sector_candidates
from app.discovery.costs import turnover
from app.discovery.selector_bakeoff import (
    BakeoffResult,
    SelectorGrade,
    _benjamini_hochberg,
    run_selector_bakeoff,
)
from app.discovery.workflow_selectors import SELECTOR_IDS, select_for_workflow
from app.paper.marketdata import clear_frame_cache

# ---------------------------------------------------------------------------
# Fixtures and small helpers -- see `tests/test_discovery.py` for the pattern this mirrors.
# ---------------------------------------------------------------------------


def _weekdays(anchor: dt.date, count: int) -> list[dt.date]:
    dates: list[dt.date] = []
    day = anchor
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day += dt.timedelta(days=1)
    return dates


def _ramp(start: float, step: float, count: int) -> list[float]:
    return [start + step * i for i in range(count)]


def _write_bars(
    settings: Settings,
    symbol: str,
    dates: list[dt.date],
    closes: list[float],
    *,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> None:
    """One daily bar per date. `adj_close == close`, matching `test_discovery.py`'s convention."""
    frame = pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC) for d in dates],
                dtype="datetime64[us, UTC]",
            ),
            "open": closes,
            "high": highs if highs is not None else [c + 1.0 for c in closes],
            "low": lows if lows is not None else [c - 1.0 for c in closes],
            "close": closes,
            "adj_close": closes,
            "volume": [1_000_000] * len(dates),
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)
    clear_frame_cache()


@pytest.fixture
def sector_bars(settings: Settings) -> tuple[Settings, list[dt.date]]:
    """Five real `SECTOR_ETF_ROSTER` tickers, 700 weekdays, with deliberately distinct price paths:

    - `XLK`: steady riser -- top `mom12_1`/`mom6`/`trend` rank throughout.
    - `XLE`: steady decliner -- bottom rank throughout.
    - `XLU`: flat -- a mid-pack filler with no rank-key signal and no gate signal.
    - `XLF`: steady riser, with its high/low range widened over the trailing 15 sessions --
      satisfies `breakout_atr`'s near-252-day-high-plus-ATR-expansion gate (verified numerically
      while building this fixture: expansion ratio ~2.3, gate threshold 0.25).
    - `XLY`: flat, then a single-session crash on the very last bar -- satisfies `meanrev_rsi`'s and
      `signal_density`'s oversold gates (RSI drops to 0; close falls below the 20-bar Bollinger lower
      band, since a lone outlier bar widens the band far more than it moves the 20-bar mean).
    """
    dates = _weekdays(dt.date(2020, 1, 1), 700)
    n = len(dates)

    _write_bars(settings, "XLK", dates, _ramp(100.0, 0.30, n))
    _write_bars(settings, "XLE", dates, _ramp(300.0, -0.20, n))
    _write_bars(settings, "XLU", dates, [150.0] * n)

    closes_f = _ramp(80.0, 0.15, n)
    highs_f = [c + 5.0 for c in closes_f]
    lows_f = [c - 5.0 for c in closes_f]
    for i in range(n - 15, n):
        highs_f[i] = closes_f[i] + 40.0
        lows_f[i] = closes_f[i] - 40.0
    _write_bars(settings, "XLF", dates, closes_f, highs=highs_f, lows=lows_f)

    closes_y = [200.0] * (n - 1) + [150.0]
    _write_bars(settings, "XLY", dates, closes_y)

    return settings, dates


@pytest.fixture
def bouncing_symbol(settings: Settings) -> tuple[Settings, dt.date, dt.date]:
    """`XLY` alone: a single-session crash (RSI -> 0) followed by a 20-session partial recovery.

    Verified numerically while building this fixture: RSI is 0.0 the day of the crash and ~48.8
    twenty sessions later -- above `meanrev_rsi`'s RSI<35 entry gate, but at or below its RSI<=50
    hysteresis-hold threshold. That gap between "would a fresh gate admit this" and "does the
    hysteresis rule still hold it" is exactly what
    `test_hysteresis_holds_a_bounced_symbol_a_stateless_regate_would_drop` measures.
    """
    closes = [200.0] * 399 + [150.0] + [150.0 + 1.0 * i for i in range(1, 21)]
    dates = _weekdays(dt.date(2020, 1, 1), len(closes))
    _write_bars(settings, "XLY", dates, closes)
    return settings, dates[399], dates[419]


# ---------------------------------------------------------------------------
# The pinned registry
# ---------------------------------------------------------------------------


def test_selector_ids_are_the_frozen_eight_in_the_planned_order() -> None:
    assert SELECTOR_IDS == (
        "mom12_1_hysteresis",
        "breakout_atr",
        "meanrev_rsi",
        "trend_sticky",
        "signal_density",
        "divers_mom6",
        "control_card_universe",
        "control_week_rotation",
    )


def test_unknown_selector_id_raises(sector_bars) -> None:
    settings, dates = sector_bars
    with pytest.raises(ValueError, match="unknown selector_id"):
        select_for_workflow("nope", as_of=dates[-1], regime_label="choppy_neutral", settings=settings)


def test_unknown_regime_label_raises(sector_bars) -> None:
    settings, dates = sector_bars
    with pytest.raises(ValueError, match="unknown regime_label"):
        select_for_workflow(
            "mom12_1_hysteresis", as_of=dates[-1], regime_label="euphoric", settings=settings
        )


# ---------------------------------------------------------------------------
# Each entrant: a plausible shortlist in at least one regime
# ---------------------------------------------------------------------------


def test_mom12_1_hysteresis_first_day_fills_from_rank_one(sector_bars) -> None:
    settings, dates = sector_bars
    picks = select_for_workflow(
        "mom12_1_hysteresis", as_of=dates[-1], regime_label="choppy_neutral", settings=settings
    )
    # top_n=2 in choppy_neutral; XLK (steepest riser) ranks first. The second slot is not asserted
    # exactly: XLK and XLF are both smooth ramps correlated >= 0.95 over a trailing year, so
    # `collapse=True` legitimately drops XLF from the order and a flat filler can take its place --
    # that is `select()`'s own collapse behaviour working as designed, not this module's.
    assert picks[0] == "XLK"
    assert len(picks) == 2
    assert set(picks) <= {"XLE", "XLF", "XLK", "XLU", "XLY"}


def test_breakout_atr_high_vol_stress_includes_the_gated_symbol(sector_bars) -> None:
    settings, dates = sector_bars
    picks = select_for_workflow(
        "breakout_atr", as_of=dates[-1], regime_label="high_vol_stress", settings=settings
    )
    assert "XLF" in picks
    assert set(picks) <= {"XLE", "XLF", "XLK", "XLU", "XLY"}


def test_meanrev_rsi_is_switched_off_in_risk_on_trend(sector_bars) -> None:
    settings, dates = sector_bars
    picks = select_for_workflow(
        "meanrev_rsi",
        as_of=dates[-1],
        regime_label="risk_on_trend",
        settings=settings,
        prior_picks=("XLY",),
    )
    assert picks == ()  # unconditional -- even a held incumbent is dropped.


def test_meanrev_rsi_risk_off_includes_the_oversold_symbol(sector_bars) -> None:
    settings, dates = sector_bars
    picks = select_for_workflow(
        "meanrev_rsi", as_of=dates[-1], regime_label="risk_off", settings=settings
    )
    # XLE (a pure monotonic decline, by construction) also pins RSI at 0 and legitimately clears the
    # same gate -- not asserted away, since a genuine downtrend is exactly what this entrant should
    # catch too. XLY is the one this test exists to pin.
    assert "XLY" in picks
    assert len(picks) <= 2  # top_n=2 in risk_off
    assert set(picks) <= {"XLE", "XLF", "XLK", "XLU", "XLY"}


def test_trend_sticky_enters_only_at_rank_one_on_the_first_day(sector_bars) -> None:
    settings, dates = sector_bars
    picks = select_for_workflow(
        "trend_sticky", as_of=dates[-1], regime_label="choppy_neutral", settings=settings
    )
    assert picks == ("XLK",)  # no incumbents yet; only the rank-1 name may newly enter.


def test_signal_density_choppy_neutral_includes_the_crash_symbol(settings: Settings) -> None:
    """Isolated from `sector_bars`'s other tickers on purpose: `XLK`/`XLF`'s own smooth ramps
    legitimately accumulate real rule density too (`price_above_sma200`, `bb_squeeze`), which can
    outrank the crash symbol for a scarce top-2 slot -- a real ranking outcome, not a bug, but not
    what this test exists to pin. A single-candidate pool isolates the gate-and-rank arithmetic this
    test is actually checking from that competition.
    """
    dates = _weekdays(dt.date(2020, 1, 1), 400)
    closes = [200.0] * (len(dates) - 1) + [150.0]
    _write_bars(settings, "XLY", dates, closes)

    picks = select_for_workflow(
        "signal_density", as_of=dates[-1], regime_label="choppy_neutral", settings=settings
    )
    assert picks == ("XLY",)


def test_divers_mom6_uses_the_theme_roster_in_every_regime(sector_bars) -> None:
    settings, dates = sector_bars
    for regime_label in ("risk_on_trend", "risk_off", "choppy_neutral", "high_vol_stress"):
        picks = select_for_workflow(
            "divers_mom6", as_of=dates[-1], regime_label=regime_label, settings=settings
        )
        assert picks == ("XLK",) or "XLK" in picks
        assert len(picks) <= 3


def test_control_card_universe_is_verbatim_and_reads_no_price_history(settings: Settings) -> None:
    # A date with no stored bars at all -- proves nothing here ever opens `AsOfMarket`.
    picks = select_for_workflow(
        "control_card_universe",
        as_of=dt.date(1990, 1, 1),
        regime_label="high_vol_stress",
        settings=settings,
        card_universe=("ZZZ", "AAA", "AAA"),
    )
    assert picks == ("ZZZ", "AAA", "AAA")  # verbatim, not deduplicated or reordered.


def test_control_week_rotation_matches_the_frozen_formula(sector_bars) -> None:
    settings, dates = sector_bars
    pool = sector_candidates(settings)
    checked_a_wrap = False
    checked_no_wrap = False
    for as_of in (dates[-1], dates[-30], dates[-90], dates[-200], dates[-400]):
        symbols = pool.symbols_as_of(as_of)
        if not symbols:
            continue
        n = len(symbols)
        offset = as_of.isocalendar()[1] % n
        end = offset + 3
        if end <= n:
            expected = symbols[offset:end]
            checked_no_wrap = True
        else:
            expected = symbols[offset:] + symbols[: end - n]
            checked_a_wrap = True
        picks = select_for_workflow(
            "control_week_rotation", as_of=as_of, regime_label="risk_off", settings=settings
        )
        assert picks == expected
    assert checked_no_wrap  # the fixture dates must exercise both branches of the formula.
    assert checked_a_wrap


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "selector_id,regime_label",
    [
        ("mom12_1_hysteresis", "risk_on_trend"),
        ("breakout_atr", "high_vol_stress"),
        ("meanrev_rsi", "risk_off"),
        ("trend_sticky", "choppy_neutral"),
        ("signal_density", "choppy_neutral"),
        ("divers_mom6", "risk_off"),
        ("control_week_rotation", "risk_off"),
    ],
)
def test_same_inputs_produce_the_same_output(sector_bars, selector_id: str, regime_label: str) -> None:
    settings, dates = sector_bars
    kwargs = dict(as_of=dates[-1], regime_label=regime_label, settings=settings)
    first = select_for_workflow(selector_id, **kwargs)
    second = select_for_workflow(selector_id, **kwargs)
    assert first == second


# ---------------------------------------------------------------------------
# Point-in-time: a decision must not move when bars after `as_of` change.
# ---------------------------------------------------------------------------


def test_mom12_1_hysteresis_ignores_bars_written_after_as_of(sector_bars) -> None:
    settings, dates = sector_bars
    as_of = dates[-1]
    before = select_for_workflow(
        "mom12_1_hysteresis", as_of=as_of, regime_label="risk_on_trend", settings=settings
    )

    future = _weekdays(as_of + dt.timedelta(days=1), 260)
    # A reversal, the version that actually bites: the current loser rockets and the current
    # winner collapses, entirely after the decision date.
    _write_bars(settings, "XLE", future, _ramp(50.0, 5.0, 260))
    _write_bars(settings, "XLK", future, _ramp(400.0, -2.0, 260))

    after = select_for_workflow(
        "mom12_1_hysteresis", as_of=as_of, regime_label="risk_on_trend", settings=settings
    )
    assert after == before


def test_breakout_atr_ignores_bars_written_after_as_of(sector_bars) -> None:
    settings, dates = sector_bars
    as_of = dates[-1]
    before = select_for_workflow(
        "breakout_atr", as_of=as_of, regime_label="high_vol_stress", settings=settings
    )

    future = _weekdays(as_of + dt.timedelta(days=1), 260)
    # XLU (flat, no gate signal through `as_of`) suddenly gets a huge post-decision range expansion.
    highs = [500.0 + 200.0 * i for i in range(260)]
    lows = [400.0 + 200.0 * i for i in range(260)]
    closes = [450.0 + 200.0 * i for i in range(260)]
    _write_bars(settings, "XLU", future, closes, highs=highs, lows=lows)

    after = select_for_workflow(
        "breakout_atr", as_of=as_of, regime_label="high_vol_stress", settings=settings
    )
    assert after == before


# ---------------------------------------------------------------------------
# Hysteresis actually reduces churn versus a stateless re-gate.
# ---------------------------------------------------------------------------


def test_hysteresis_holds_a_bounced_symbol_a_stateless_regate_would_drop(bouncing_symbol) -> None:
    settings, day1, day2 = bouncing_symbol

    day1_picks = select_for_workflow(
        "meanrev_rsi", as_of=day1, regime_label="risk_off", settings=settings
    )
    assert day1_picks == ("XLY",)  # RSI 0.0 clears the RSI<35 entry gate.

    # With hysteresis: `prior_picks` carries yesterday's hold forward.
    day2_with_hysteresis = select_for_workflow(
        "meanrev_rsi",
        as_of=day2,
        regime_label="risk_off",
        settings=settings,
        prior_picks=day1_picks,
    )
    # Without it: the identical call, but as if nothing had been held -- a fresh gate check.
    day2_gate_only = select_for_workflow(
        "meanrev_rsi", as_of=day2, regime_label="risk_off", settings=settings, prior_picks=()
    )

    assert "XLY" in day2_with_hysteresis  # RSI ~48.8 <= 50: still held.
    assert "XLY" not in day2_gate_only  # RSI ~48.8 is not < 35: a fresh gate would refuse it.

    hysteresis_churn = turnover(day1_picks, day2_with_hysteresis)
    stateless_churn = turnover(day1_picks, day2_gate_only)
    assert hysteresis_churn < stateless_churn


# ---------------------------------------------------------------------------
# Benjamini-Hochberg, in isolation
# ---------------------------------------------------------------------------


def test_benjamini_hochberg_matches_hand_computed_q_values() -> None:
    p_values = {
        "a": 0.01,
        "b": 0.04,
        "c": 0.03,
        "d": 0.50,
        "e": None,
        "f": None,
        "g": None,
        "h": None,
    }
    q = _benjamini_hochberg(p_values, m=8)

    # Sorted ascending: a(rank1, p=.01), c(rank2, p=.03), b(rank3, p=.04), d(rank4, p=.50).
    # Raw q = p * 8 / rank: a=.08, c=.12, b=.10667, d=1.0.
    # Enforced monotone from the largest rank down: q[c] = min(.12, .10667) = .10667; q[a] unchanged.
    assert q["a"] == pytest.approx(0.08)
    assert q["b"] == pytest.approx(0.10667, rel=1e-3)
    assert q["c"] == pytest.approx(0.10667, rel=1e-3)
    assert q["d"] == pytest.approx(1.0)
    assert q["e"] is None
    assert q["f"] is None


def test_benjamini_hochberg_of_no_p_values_is_all_none() -> None:
    p_values = dict.fromkeys(SELECTOR_IDS, None)
    q = _benjamini_hochberg(p_values, m=len(SELECTOR_IDS))
    assert all(value is None for value in q.values())


# ---------------------------------------------------------------------------
# The bake-off driver: structural, end-to-end, on the tiny fixture above.
# ---------------------------------------------------------------------------


def test_bakeoff_driver_grades_all_eight_entrants_on_a_tiny_fixture(sector_bars) -> None:
    settings, dates = sector_bars
    in_sample = (dates[-40], dates[-21])
    holdout = (dates[-20], dates[-1])

    result = run_selector_bakeoff(settings=settings, in_sample=in_sample, holdout=holdout)

    assert isinstance(result, BakeoffResult)
    assert {g.selector_id for g in result.in_sample} == set(SELECTOR_IDS)
    assert {g.selector_id for g in result.holdout} == set(SELECTOR_IDS)

    for grade in (*result.in_sample, *result.holdout):
        assert isinstance(grade, SelectorGrade)
        assert grade.n_dates > 0
        assert grade.n_scored >= 0
        if grade.bootstrap_p is not None:
            assert 0.0 <= grade.bootstrap_p <= 1.0
        if grade.bh_q is not None:
            assert 0.0 <= grade.bh_q <= 1.0
        if grade.hit_rate is not None:
            assert 0.0 <= grade.hit_rate <= 1.0
        if grade.binomial_p is not None:
            assert 0.0 <= grade.binomial_p <= 1.0
        if grade.mean_churn is not None:
            assert grade.mean_churn >= 0
        if grade.implied_dollars_per_day is not None:
            assert grade.implied_dollars_per_day >= 0.0

    grade = result.grade("mom12_1_hysteresis")
    assert grade is not None and grade.selector_id == "mom12_1_hysteresis"
    assert result.grade("mom12_1_hysteresis", slice_name="holdout") is not None
    assert result.grade("does-not-exist") is None


def test_bakeoff_driver_is_deterministic(sector_bars) -> None:
    settings, dates = sector_bars
    window = (dates[-30], dates[-15])
    first = run_selector_bakeoff(settings=settings, in_sample=window, holdout=window)
    second = run_selector_bakeoff(settings=settings, in_sample=window, holdout=window)
    assert first == second


def test_bakeoff_driver_on_an_empty_window_does_not_crash(sector_bars) -> None:
    settings, dates = sector_bars
    as_of = dates[-1]
    result = run_selector_bakeoff(settings=settings, in_sample=(as_of, as_of), holdout=(as_of, as_of))
    for grade in (*result.in_sample, *result.holdout):
        assert grade.n_dates == 1


# -- mom12_1_hysteresis live top_n widening (screen_top_n -> top_n_override) -----------------------

_D = dt.date(2020, 6, 1)
_RANKED = [f"S{i:02d}" for i in range(20)]  # S00..S19, ranks 1..20 by momentum


def _patch_ranking(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.discovery import workflow_selectors as ws

    monkeypatch.setattr(ws, "_pool_for", lambda *a, **k: object())
    # Match the real helper's tuple return type -- `full[:top_n]` preserves it.
    monkeypatch.setattr(ws, "_full_rank_order", lambda *a, **k: tuple(_RANKED))


def test_top_n_override_widens_active_regime(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.discovery import workflow_selectors as ws

    _patch_ranking(monkeypatch)
    # risk_on_trend frozen top_n is 3; override widens the first draw (no prior) to 10.
    out = ws._select_mom12_1_hysteresis(_D, "risk_on_trend", settings, (), top_n_override=10)
    assert out == tuple(_RANKED[:10])


def test_top_n_override_none_reproduces_frozen_three(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.discovery import workflow_selectors as ws

    _patch_ranking(monkeypatch)
    out = ws._select_mom12_1_hysteresis(_D, "risk_on_trend", settings, ())
    assert out == tuple(_RANKED[:3])  # frozen top_n, byte-for-byte


def test_top_n_override_respects_regime_gating(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.discovery import workflow_selectors as ws

    _patch_ranking(monkeypatch)
    # high_vol_stress frozen top_n is 0 (the selector sits it out); an override must NOT start trading it.
    out = ws._select_mom12_1_hysteresis(_D, "high_vol_stress", settings, (), top_n_override=10)
    assert out == ()


def test_top_n_override_scales_the_hysteresis_exit_band(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.discovery import workflow_selectors as ws

    _patch_ranking(monkeypatch)
    # S10 is rank 11. Frozen (top_n=3) exit band is 5 -> dropped. Widened (top_n=10) exit band is 12 -> kept.
    frozen = ws._select_mom12_1_hysteresis(_D, "risk_on_trend", settings, ("S10",))
    assert "S10" not in frozen
    widened = ws._select_mom12_1_hysteresis(_D, "risk_on_trend", settings, ("S10",), top_n_override=10)
    assert "S10" in widened


def test_select_for_workflow_threads_top_n_override(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.discovery import workflow_selectors as ws

    seen: dict[str, int | None] = {}

    def spy(as_of, regime_label, settings, prior_picks, *, top_n_override=None):
        seen["override"] = top_n_override
        return ()

    monkeypatch.setattr(ws, "_select_mom12_1_hysteresis", spy)
    ws.select_for_workflow(
        "mom12_1_hysteresis", as_of=_D, regime_label="risk_on_trend", settings=settings, top_n_override=10
    )
    assert seen["override"] == 10
