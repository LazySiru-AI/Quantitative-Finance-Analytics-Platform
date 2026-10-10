"""Tests for `strategy-program/tools/contributions.py`'s cadence-aware contribution harness.

`strategy-program` is not a legal Python package name (the hyphen), so `contributions.py` is loaded
by file path here -- the identical precedent `strategy-program/tools/roth_voltarget.py` and
`strategy-program/tools/savings_family.py` already set for the same reason.

Each test pins one claim the round-15 brief makes about the monthly-contribution extension:

* `TestContributionDatesAnnual` / `TestContributionDatesMonthly` -- `contribution_dates` fires on the
  first session of each period (year or month), plus the first session overall, for both cadences,
  including a partial opening period.
* `TestMonthlyVsAnnualDiffer` -- the same total contributed over the same window, split monthly
  instead of annually, produces a different ending balance and a different IRR. If these ever come out
  equal, the cashflow dating is wrong (see `contributions.py::simulate`'s own docstring).
* `TestContributionDirectedRebalancing` -- a deposit is spent disproportionately on the sleeve that
  drifted underweight, closing the gap, exactly as `simulate`'s own docstring claims.
* `TestAnnualRegressionByteIdentical` -- an existing annual call (the shape all six family scripts
  still use) produces numbers identical to a snapshot captured from this module *before* the monthly
  extension was added, over a fixed synthetic window.
* `TestZeroContributionLumpSum` -- `contribution=0.0` funds once, at `seed`, and never again --
  the exact shape `strategy-program/tools/r15_control.py` and `TRADING`'s `FundingShape.LUMP_SUM`
  both rely on.
* `TestCadenceMixupIsRefused` -- pins that the two ways of naming a recurring contribution
  (`annual_contribution=` and `contribution=`/`cadence=`) cannot be combined or half-used; each
  invalid combination raises `ValueError` rather than silently picking one.

Round 16 adds `cash_constrained` (default `False`) and its own claims:

* `TestCashConstrainedDefaultIsByteIdentical` -- an explicit `cash_constrained=False` reproduces the
  implicit default field-by-field, including the round-15 snapshot constants.
* `TestCashNeverGoesNegative` -- under `cash_constrained=True`, `result.cash` never dips below zero at
  any session across a whole, deliberately turnover-heavy run -- not just at one point -- and the
  constraint actually binds somewhere in that run (`underfunded_buys > 0`), so the invariant is
  non-vacuous.
* `TestSellsBeforeBuys` -- a forced full-rotation swap (100% of one sleeve into another) where dict
  insertion order names the *bought* symbol before the *sold* one. Every number is predicted in
  closed form from `seed` and `slippage_bps` alone (this two-symbol, flat-price, single-rebalance
  shape has an exact algebraic solution) and checked against the actual run: the unconstrained path
  ends each rebalance with cash pushed negative by exactly `2 * equity * slippage_rate` (it spent
  proceeds it didn't have yet), while the constrained path -- which sells first regardless of dict
  order -- ends at exactly zero cash and reports the same amount as `underfunded_shortfall`, proving
  the sell-before-buy ordering is what closes the gap, not luck.
* `TestConstraintNeverBinds` -- `TestContributionDirectedRebalancing`'s own scenario (`band_pct=0.99`,
  so no price-driven rebalance ever fires) run again with `cash_constrained=True`: identical to the
  unconstrained result in every field, because the constrained code path is never even entered.
* `TestNoPhantomCashflows` -- under the constraint, `result.flows` still contains only genuine
  contribution/seed deposits (never a synthetic entry for a rebalance or a rejected buy), so `irr` and
  `time_weighted_cagr` keep reading real cashflows even when buys are being capped or partially
  filled.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import math
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "contributions",
    str(Path(__file__).resolve().parents[1] / "strategy-program" / "tools" / "contributions.py"),
)
contributions = importlib.util.module_from_spec(_spec)
sys.modules["contributions"] = contributions
_spec.loader.exec_module(contributions)


def _business_days(start: dt.date, end: dt.date) -> list[dt.date]:
    """Every Mon-Fri date in `[start, end]`, inclusive -- no holiday calendar, matching the level of
    fidelity this test file needs (a deterministic, weekday-only date grid), not a real trading
    calendar."""
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def _sine_closes(n: int, *, base: float = 100.0, amplitude: float = 0.15, drift: float = 0.0003) -> list[float]:
    """A single deterministic, oscillating-with-drift price path -- enough sequence variation that
    contribution timing actually matters, with no randomness so every run is identical."""
    return [base * (1 + amplitude * math.sin(i / 40.0) + drift * i) for i in range(n)]


def _static_weight_fn(weights: dict[str, float]):
    return lambda i, closes: dict(weights)


# ---------------------------------------------------------------------------
# contribution_dates
# ---------------------------------------------------------------------------


class TestContributionDatesAnnual:
    def test_one_index_per_year_plus_first_session(self) -> None:
        dates = _business_days(dt.date(2020, 1, 1), dt.date(2022, 12, 31))
        idx = contributions.contribution_dates(dates)  # default cadence, unchanged signature
        years_seen = [dates[i].year for i in idx]
        assert years_seen == [2020, 2021, 2022]
        # Every index is the first session of its year.
        for i in idx:
            assert dates[i] == min(d for d in dates if d.year == dates[i].year)

    def test_default_cadence_matches_explicit_annual(self) -> None:
        dates = _business_days(dt.date(2020, 1, 1), dt.date(2021, 12, 31))
        assert contributions.contribution_dates(dates) == contributions.contribution_dates(
            dates, cadence="annual"
        )

    def test_partial_first_year_still_funds_once(self) -> None:
        # Window opens mid-year (August), so the opening period is a partial calendar year.
        dates = _business_days(dt.date(2020, 8, 3), dt.date(2021, 6, 30))
        idx = contributions.contribution_dates(dates)
        assert idx[0] == 0
        # Only two fundings: the partial 2020 open, and 2021's own first session -- never a second
        # 2020 event just because the year was partial.
        assert idx == [0, dates.index(min(d for d in dates if d.year == 2021))]


class TestContributionDatesMonthly:
    def test_twelve_indices_per_full_calendar_year(self) -> None:
        dates = _business_days(dt.date(2021, 1, 1), dt.date(2022, 12, 31))
        idx = contributions.contribution_dates(dates, cadence="monthly")
        months_2021 = [(dates[i].year, dates[i].month) for i in idx if dates[i].year == 2021]
        months_2022 = [(dates[i].year, dates[i].month) for i in idx if dates[i].year == 2022]
        assert months_2021 == [(2021, m) for m in range(1, 13)]
        assert months_2022 == [(2022, m) for m in range(1, 13)]
        # Each index is that month's own first session.
        for i in idx:
            y, m = dates[i].year, dates[i].month
            assert dates[i] == min(d for d in dates if (d.year, d.month) == (y, m))

    def test_partial_first_month_still_funds_once(self) -> None:
        # Window opens mid-month (the 15th), so January is a partial month.
        dates = _business_days(dt.date(2024, 1, 15), dt.date(2024, 3, 31))
        idx = contributions.contribution_dates(dates, cadence="monthly")
        assert idx[0] == 0
        months = [(dates[i].year, dates[i].month) for i in idx]
        # January appears exactly once (the partial open), not once per remaining January session.
        assert months == [(2024, 1), (2024, 2), (2024, 3)]

    def test_unknown_cadence_rejected(self) -> None:
        dates = _business_days(dt.date(2024, 1, 1), dt.date(2024, 1, 31))
        with pytest.raises(ValueError, match="cadence"):
            contributions.contribution_dates(dates, cadence="weekly")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# monthly vs. annual: same total, different sequencing, different answer
# ---------------------------------------------------------------------------


class TestMonthlyVsAnnualDiffer:
    def test_same_total_contribution_gives_different_balance_and_irr(self) -> None:
        dates = _business_days(dt.date(2020, 1, 1), dt.date(2021, 12, 31))
        closes = {"A": _sine_closes(len(dates))}
        weight_fn = _static_weight_fn({"A": 1.0})

        # Same $24,000 total over the two-year window either way: $12,000/year vs. $1,000/month.
        annual = contributions.simulate(
            dates, closes, weight_fn,
            contribution=12_000.0, cadence="annual", slippage_bps=0.0,
        )
        monthly = contributions.simulate(
            dates, closes, weight_fn,
            contribution=1_000.0, cadence="monthly", slippage_bps=0.0,
        )

        assert annual.total_contributed == monthly.total_contributed == 24_000.0
        assert annual.final_balance != pytest.approx(monthly.final_balance)
        assert annual.irr is not None and monthly.irr is not None
        assert annual.irr != pytest.approx(monthly.irr)

    def test_monthly_flow_count_is_twelve_times_annual_over_full_years(self) -> None:
        dates = _business_days(dt.date(2020, 1, 1), dt.date(2022, 12, 31))
        closes = {"A": _sine_closes(len(dates))}
        weight_fn = _static_weight_fn({"A": 1.0})

        annual = contributions.simulate(dates, closes, weight_fn, contribution=7_500.0, cadence="annual")
        monthly = contributions.simulate(dates, closes, weight_fn, contribution=625.0, cadence="monthly")

        assert len(annual.flows) == 3  # 2020, 2021, 2022
        assert len(monthly.flows) == 36  # 12 * 3 full years


# ---------------------------------------------------------------------------
# contribution-directed rebalancing, monthly cadence
# ---------------------------------------------------------------------------


class TestContributionDirectedRebalancing:
    """Two sleeves, X flat and Y declining through January, both targeted 50/50 and a wide
    `band_pct` (0.99) so no *price-driven* rebalance ever fires -- the only thing that can move a
    dollar between sleeves here is the contribution-directed buy this class exists to pin. By the time
    February's deposit lands, Y has drifted underweight (its price fell while X's held flat) and X has
    drifted overweight; the new cash must close that gap, spending more of itself on Y than on X."""

    DATES = [
        dt.date(2024, 1, 2), dt.date(2024, 1, 3), dt.date(2024, 1, 4),
        dt.date(2024, 1, 5), dt.date(2024, 1, 8),
        dt.date(2024, 2, 1), dt.date(2024, 2, 2), dt.date(2024, 2, 5),
    ]
    X = [100.0] * 8
    # -5%/session through January, flat into February.
    Y = [100.0, 95.0, 90.25, 85.7375, 81.450625, 81.450625, 81.450625, 81.450625]

    def _run(self):
        closes = {"X": self.X, "Y": self.Y}
        weight_fn = _static_weight_fn({"X": 0.5, "Y": 0.5})
        return contributions.simulate(
            self.DATES, closes, weight_fn,
            contribution=100.0, cadence="monthly", seed=0.0,
            band_pct=0.99, slippage_bps=0.0, use_contributions_to_rebalance=True,
        )

    def test_deposit_closes_the_underweight_gap(self) -> None:
        result = self._run()
        feb_idx = 5  # 2024-02-01, the second contribution date

        # Going into February's contribution, Y (the decliner) is underweight and X is overweight.
        pre = result.weights[feb_idx - 1]
        assert pre["Y"] < 0.5 < pre["X"]

        holdings_before = {s: pre[s] * result.equity[feb_idx - 1] for s in ("X", "Y")}
        post = result.weights[feb_idx]
        holdings_after = {s: post[s] * result.equity[feb_idx] for s in ("X", "Y")}
        take = {s: holdings_after[s] - holdings_before[s] for s in ("X", "Y")}

        # The whole $100 deposit lands as new holdings, split across both sleeves...
        assert take["X"] + take["Y"] == pytest.approx(100.0)
        # ...but the more-underweight sleeve (Y) gets the larger share of it.
        assert take["Y"] > take["X"]
        # And the deposit was exactly enough to close the gap: both land back at the 50/50 target.
        assert post["X"] == pytest.approx(0.5)
        assert post["Y"] == pytest.approx(0.5)

    def test_no_price_driven_rebalance_fires_on_its_own(self) -> None:
        # rebalances only counts *breach* rebalances; with band_pct=0.99 none should ever fire, so
        # every dollar that moved between sleeves moved via contribution_buys, not this counter.
        result = self._run()
        assert result.rebalances == 0
        assert result.contribution_buys == 2  # one per contribution date


# ---------------------------------------------------------------------------
# regression: an existing annual call is untouched
# ---------------------------------------------------------------------------


class TestAnnualRegressionByteIdentical:
    """A snapshot captured by running this exact scenario against `contributions.simulate` *before*
    the monthly-cadence parameters (`contribution`, `cadence`, `seed`) were added -- see this task's
    own report for how it was captured. Every number below must still match to the last bit: an
    existing caller (all six family scripts) never names `contribution`, `cadence` or `seed`, and this
    pins that leaving them unnamed reproduces the original behaviour exactly, not approximately.
    """

    def _run(self):
        dates = _business_days(dt.date(2020, 1, 1), dt.date(2022, 12, 31))
        closes = {
            "A": [100.0 * (1 + 0.15 * math.sin(i / 40.0) + 0.0003 * i) for i in range(len(dates))],
            "B": [50.0 * (1 + 0.10 * math.cos(i / 55.0) + 0.0002 * i) for i in range(len(dates))],
        }
        weight_fn = _static_weight_fn({"A": 0.6, "B": 0.4})
        # Deliberately the pre-existing call shape: only positional args plus the module's own
        # long-standing defaults, exactly as every family script still calls it.
        return contributions.simulate(dates, closes, weight_fn)

    def test_matches_pre_monthly_snapshot(self) -> None:
        result = self._run()

        assert result.final_balance == 26248.8589146808
        assert result.total_contributed == 22500.0
        assert len(result.flows) == 3
        assert [f.amount for f in result.flows] == [7500.0, 7500.0, 7500.0]
        assert result.irr == 0.07936355361766034
        assert result.time_weighted_cagr == 0.06736075969220368
        assert result.max_drawdown == -0.17854512712709558
        assert result.rebalances == 2
        assert result.contribution_buys == 3
        assert result.turnover == 25755.34056538861
        assert result.cost_paid == 12.877670282694305
        assert result.equity[-5:] == [
            26138.135828962324, 26166.855850133892, 26194.895357554546,
            26222.23576197482, 26248.8589146808,
        ]
        assert result.contributed[-5:] == [22500.0] * 5


# ---------------------------------------------------------------------------
# seed + zero contribution == lump sum, funded once
# ---------------------------------------------------------------------------


class TestZeroContributionLumpSum:
    """The `TRADING` funding shape (`backend/app/tournament/purposes.py`): a `seed`, `contribution=0`,
    no recurring deposit ever again -- and the exact path `strategy-program/tools/r15_control.py`
    relies on for its own "single lump sum, not a savings plan" control."""

    def test_funds_once_at_seed_and_never_again(self) -> None:
        dates = _business_days(dt.date(2020, 1, 1), dt.date(2023, 12, 31))
        closes = {"A": _sine_closes(len(dates))}
        weight_fn = _static_weight_fn({"A": 1.0})

        result = contributions.simulate(
            dates, closes, weight_fn,
            contribution=0.0, cadence="annual", seed=100_000.0,
        )

        assert len(result.flows) == 1
        assert result.flows[0].date == dates[0]
        assert result.flows[0].amount == 100_000.0
        assert result.total_contributed == 100_000.0
        # `contributed` never rises after session 0, across every later year boundary.
        assert all(c == 100_000.0 for c in result.contributed)

    def test_funds_once_regardless_of_cadence(self) -> None:
        # Monthly cadence, contribution=0: still exactly one flow, at the seed.
        dates = _business_days(dt.date(2020, 1, 1), dt.date(2021, 12, 31))
        closes = {"A": _sine_closes(len(dates))}
        weight_fn = _static_weight_fn({"A": 1.0})

        result = contributions.simulate(
            dates, closes, weight_fn,
            contribution=0.0, cadence="monthly", seed=50_000.0,
        )

        assert len(result.flows) == 1
        assert result.flows[0].amount == 50_000.0


# ---------------------------------------------------------------------------
# the two ways of naming a recurring contribution cannot mix
# ---------------------------------------------------------------------------


class TestCadenceMixupIsRefused:
    def _scenario(self):
        dates = _business_days(dt.date(2020, 1, 1), dt.date(2020, 12, 31))
        closes = {"A": _sine_closes(len(dates))}
        weight_fn = _static_weight_fn({"A": 1.0})
        return dates, closes, weight_fn

    def test_contribution_with_non_default_annual_contribution_raises(self) -> None:
        dates, closes, weight_fn = self._scenario()
        with pytest.raises(ValueError, match="not both"):
            contributions.simulate(
                dates, closes, weight_fn,
                annual_contribution=5_000.0,  # non-default -- ambiguous against contribution=
                contribution=1_000.0, cadence="monthly",
            )

    def test_monthly_cadence_without_contribution_raises(self) -> None:
        dates, closes, weight_fn = self._scenario()
        with pytest.raises(ValueError, match="requires an explicit contribution"):
            contributions.simulate(dates, closes, weight_fn, cadence="monthly")

    def test_contribution_alone_with_default_annual_contribution_is_fine(self) -> None:
        # annual_contribution left at its default is not "non-default", so this is not a conflict.
        dates, closes, weight_fn = self._scenario()
        result = contributions.simulate(dates, closes, weight_fn, contribution=500.0, cadence="annual")
        assert result.flows[0].amount == 500.0


# ---------------------------------------------------------------------------
# round 16: cash_constrained
# ---------------------------------------------------------------------------


class TestCashConstrainedDefaultIsByteIdentical:
    """`cash_constrained` defaults to `False`, and every round-15 number must survive it. This reruns
    `TestAnnualRegressionByteIdentical`'s exact scenario and checks that naming `cash_constrained=False`
    explicitly reproduces the implicit default field by field -- not approximately, to the pinned
    snapshot constants -- including the three fields this task adds (`underfunded_buys`,
    `underfunded_shortfall`, `cash`), which must sit at their inert zero/empty-of-drama state when the
    constraint is off."""

    def _run(self, **kwargs):
        dates = _business_days(dt.date(2020, 1, 1), dt.date(2022, 12, 31))
        closes = {
            "A": [100.0 * (1 + 0.15 * math.sin(i / 40.0) + 0.0003 * i) for i in range(len(dates))],
            "B": [50.0 * (1 + 0.10 * math.cos(i / 55.0) + 0.0002 * i) for i in range(len(dates))],
        }
        weight_fn = _static_weight_fn({"A": 0.6, "B": 0.4})
        return contributions.simulate(dates, closes, weight_fn, **kwargs)

    def test_explicit_false_matches_implicit_default_and_the_pinned_snapshot(self) -> None:
        implicit = self._run()
        explicit = self._run(cash_constrained=False)

        # The pinned constants from TestAnnualRegressionByteIdentical, restated here so this class
        # stands on its own as proof rather than only a diff against a sibling test.
        assert implicit.final_balance == explicit.final_balance == 26248.8589146808
        assert implicit.irr == explicit.irr == 0.07936355361766034
        assert implicit.time_weighted_cagr == explicit.time_weighted_cagr == 0.06736075969220368
        assert implicit.max_drawdown == explicit.max_drawdown == -0.17854512712709558
        assert implicit.rebalances == explicit.rebalances == 2
        assert implicit.contribution_buys == explicit.contribution_buys == 3
        assert implicit.turnover == explicit.turnover == 25755.34056538861
        assert implicit.cost_paid == explicit.cost_paid == 12.877670282694305

        # Every session, not just the headline numbers.
        assert implicit.equity == explicit.equity
        assert implicit.contributed == explicit.contributed
        assert implicit.weights == explicit.weights
        assert implicit.cash == explicit.cash
        assert [(f.date, f.amount) for f in implicit.flows] == [
            (f.date, f.amount) for f in explicit.flows
        ]

        # The new fields exist and are inert when the constraint is off.
        assert implicit.underfunded_buys == explicit.underfunded_buys == 0
        assert implicit.underfunded_shortfall == explicit.underfunded_shortfall == 0.0


class TestCashNeverGoesNegative:
    """`cash_constrained=True`'s entire job is to guarantee `cash >= 0` at every session, not just on
    average. This run is deliberately hostile to that guarantee: three sleeves, a target that rotates
    to a different 100%-concentrated symbol every five sessions (forcing a full sell-and-buy rotation
    repeatedly), a tight `band_pct` so every rotation breaches, and non-zero slippage so every rotation
    pays a cost on both sides -- exactly the shape that pushes cash negative under the unconstrained
    path (see `TestSellsBeforeBuys`). The constraint must hold across the whole run, and -- so this
    isn't a vacuous invariant over a run that never binds -- the run must actually record underfunded
    buys."""

    def _run(self) -> contributions.ContributionResult:
        dates = _business_days(dt.date(2020, 1, 1), dt.date(2020, 6, 30))
        n = len(dates)

        def sleeve(amplitude_phase: float, drift: float) -> list[float]:
            return [100.0 * (1 + 0.2 * math.sin(i / 7.0 + amplitude_phase) + drift * i) for i in range(n)]

        closes = {"A": sleeve(0.0, 0.0005), "B": sleeve(2.1, 0.0004), "C": sleeve(4.2, 0.0003)}
        symbols = ["A", "B", "C"]

        def weight_fn(i: int, closes):
            return {symbols[(i // 5) % 3]: 1.0}

        return contributions.simulate(
            dates, closes, weight_fn,
            contribution=0.0, seed=10_000.0,
            band_pct=0.01, slippage_bps=50.0, use_contributions_to_rebalance=False,
            cash_constrained=True,
        )

    def test_cash_stays_non_negative_across_the_whole_run(self) -> None:
        result = self._run()
        assert len(result.cash) == len(result.dates) > 0
        # Allow only float noise, never a real negative balance.
        assert min(result.cash) >= -1e-6

    def test_the_invariant_is_not_vacuous(self) -> None:
        # If this run never actually underfunded a buy, the test above would be proving nothing.
        result = self._run()
        assert result.underfunded_buys > 0
        assert result.underfunded_shortfall > 0.0
        assert result.rebalances > 0


class TestSellsBeforeBuys:
    """A minimal, exactly-solvable forced case: one sleeve (`Y`) holds the whole account, prices are
    flat (so no price drift complicates the arithmetic), and the target then flips to the other sleeve
    (`X`) -- a 100% sell of Y funding a 100% buy of X. `closes` is built as `{"X": ..., "Y": ...}`, so
    `list(closes)` -- dict/insertion order, the order the unconstrained path always walks in -- names
    the *bought* symbol `X` before the *sold* symbol `Y`.

    With flat prices the only friction is `slippage_bps`, so both outcomes have a closed form in terms
    of the equity `E` going into the rotation and the slippage rate `r`:

    * Unconstrained (any order, since the moves are just additions and addition is associative): sells
      *and* buys both execute in full regardless of cash, so the account ends the rotation having paid
      cost on both legs without ever having covered it -- final cash is exactly `-2 * E * r`, provably
      negative for any `r > 0`. This is round 16's whole premise, made concrete.
    * Constrained: `Y` sells first regardless of insertion order, crediting `cash` before `X`'s buy is
      attempted, so `X`'s buy is capped at what that sale actually raised net of its own cost -- final
      cash lands at exactly `0.0`, and the unfilled amount (`E - fill`) equals the same `2 * E * r`
      that went negative in the unconstrained path -- so `underfunded_shortfall` reports precisely the
      dollar amount the unconstrained path spent without having it, not some unrelated figure.

    Because `X` is opened *before* `Y` in `closes`, a naive implementation that simply capped
    dict-order buys without segregating sells first would have attempted `X`'s buy against ~$0 of cash
    (all of it still sitting in `Y`) and filled almost none of it -- an underfunded_shortfall close to
    the full `E`, not the tiny `2*E*r` this scenario actually produces. The small shortfall is itself
    the proof that sells ran first.
    """

    SEED = 10_000.0
    SLIPPAGE_BPS = 100.0
    SWITCH_IDX = 10
    # Wide enough that the ~1%-of-equity overweight the unconstrained path's own negative cash creates
    # after session 0 (target = equity, and equity is *reduced* by the negative cash it is carrying,
    # so `desired_Y` sits a hair below the actual, never-checked `holdings_Y`) never itself breaches
    # and triggers an extra corrective rebalance between session 0 and the swap -- which would still be
    # a real, correctly-modelled consequence of the unconstrained bug, just one that would make the
    # closed-form prediction below track a second rebalance instead of the swap alone.
    BAND_PCT = 0.05

    def _dates(self) -> list[dt.date]:
        return _business_days(dt.date(2024, 1, 2), dt.date(2024, 2, 20))

    def _closes(self, n: int) -> dict[str, list[float]]:
        # Insertion order: X (the eventual buy target) named before Y (the eventual sell target).
        return {"X": [100.0] * n, "Y": [100.0] * n}

    def _weight_fn(self, i: int, closes):
        return {"Y": 1.0} if i < self.SWITCH_IDX else {"X": 1.0}

    def _run(self, *, cash_constrained: bool):
        dates = self._dates()
        closes = self._closes(len(dates))
        return contributions.simulate(
            dates, closes, self._weight_fn,
            contribution=0.0, seed=self.SEED,
            band_pct=self.BAND_PCT, slippage_bps=self.SLIPPAGE_BPS, use_contributions_to_rebalance=False,
            cash_constrained=cash_constrained,
        )

    def test_unconstrained_cash_goes_negative_on_the_swap(self) -> None:
        r = self.SLIPPAGE_BPS / 10_000
        result = self._run(cash_constrained=False)
        assert result.rebalances == 2  # session 0's opening buy, and the swap -- nothing in between

        # Session 0's own opening buy (all-cash into Y) already goes negative by seed*r, because the
        # unconstrained path never checks cash before spending it.
        assert result.cash[0] == pytest.approx(-self.SEED * r)

        # At the swap, `holdings_Y` is still the *full* `seed` (the unconstrained path never trimmed
        # it, having never checked cash), so the sell raises `seed*(1-r)`, while the buy -- sized off
        # `equity = seed*(1-r)`, not off `holdings_Y` -- costs `equity*(1+r)`. Net, starting from
        # session 0's own `-seed*r`: cash_final = -seed*r*(2 - r), algebraically simplified below.
        expected_swap_cash = -self.SEED * r * (2 - r)
        assert result.cash[self.SWITCH_IDX] == pytest.approx(expected_swap_cash)
        assert result.cash[self.SWITCH_IDX] < 0
        # Unconstrained never tracks a shortfall at all -- it always executes the full move.
        assert result.underfunded_buys == 0
        assert result.underfunded_shortfall == 0.0

    def test_constrained_cash_never_negative_and_shortfall_matches_the_gap(self) -> None:
        r = self.SLIPPAGE_BPS / 10_000
        result = self._run(cash_constrained=True)

        assert min(result.cash) >= -1e-9
        # Every partial fill that uses up all available cash lands at exactly zero, both at session 0
        # (the opening all-cash buy is itself underfunded by slippage) and at the swap.
        assert result.cash[0] == pytest.approx(0.0, abs=1e-9)
        assert result.cash[self.SWITCH_IDX] == pytest.approx(0.0, abs=1e-9)

        fill0 = self.SEED / (1 + r)  # session 0's actual fill, capped by cash/(1+r)
        equity_before_swap = fill0  # flat prices: Y's value carries forward unchanged
        swap_shortfall = equity_before_swap * 2 * r / (1 + r)
        day0_shortfall = self.SEED - fill0

        assert result.underfunded_buys == 2  # session 0's open, and the swap -- both slippage-starved
        assert result.underfunded_shortfall == pytest.approx(day0_shortfall + swap_shortfall)

    def test_outcome_differs_from_unconstrained_in_the_expected_direction(self) -> None:
        # Same scenario, only the flag differs. The constrained path must hold *less* of the newly
        # bought sleeve than the unconstrained path (it can't buy what it can't afford), and the
        # unconstrained path's negative cash is the mirror image of the constrained shortfall.
        constrained = self._run(cash_constrained=True)
        unconstrained = self._run(cash_constrained=False)

        constrained_x_value = constrained.weights[self.SWITCH_IDX]["X"] * constrained.equity[
            self.SWITCH_IDX - 1
        ]
        unconstrained_x_value = unconstrained.weights[self.SWITCH_IDX]["X"] * unconstrained.equity[
            self.SWITCH_IDX - 1
        ]
        assert constrained_x_value < unconstrained_x_value

        assert unconstrained.cash[self.SWITCH_IDX] < 0.0
        assert constrained.cash[self.SWITCH_IDX] == pytest.approx(0.0, abs=1e-9)
        assert constrained.underfunded_shortfall > 0.0


class TestConstraintNeverBinds:
    """`TestContributionDirectedRebalancing`'s own scenario, unmodified: `band_pct=0.99` means no
    price-driven rebalance ever fires (pinned there by `test_no_price_driven_rebalance_fires_on_its_own`
    -- `rebalances == 0`), so the `cash_constrained` branch is never even entered. A constraint that
    only ever matters inside a code path this run never reaches must produce byte-identical output
    whether it is on or off."""

    DATES = [
        dt.date(2024, 1, 2), dt.date(2024, 1, 3), dt.date(2024, 1, 4),
        dt.date(2024, 1, 5), dt.date(2024, 1, 8),
        dt.date(2024, 2, 1), dt.date(2024, 2, 2), dt.date(2024, 2, 5),
    ]
    X = [100.0] * 8
    Y = [100.0, 95.0, 90.25, 85.7375, 81.450625, 81.450625, 81.450625, 81.450625]

    def _run(self, *, cash_constrained: bool):
        closes = {"X": self.X, "Y": self.Y}
        weight_fn = _static_weight_fn({"X": 0.5, "Y": 0.5})
        return contributions.simulate(
            self.DATES, closes, weight_fn,
            contribution=100.0, cadence="monthly", seed=0.0,
            band_pct=0.99, slippage_bps=0.0, use_contributions_to_rebalance=True,
            cash_constrained=cash_constrained,
        )

    def test_identical_either_way_when_the_constraint_never_binds(self) -> None:
        off = self._run(cash_constrained=False)
        on = self._run(cash_constrained=True)

        assert off.rebalances == on.rebalances == 0
        assert on.underfunded_buys == 0
        assert off.equity == on.equity
        assert off.cash == on.cash
        assert off.weights == on.weights
        assert off.turnover == on.turnover
        assert off.cost_paid == on.cost_paid


class TestNoPhantomCashflows:
    """`result.flows` drives `irr` (money-weighted return); it must contain exactly the genuine
    deposits -- never a synthetic entry manufactured by a rebalance, a rejected buy, or a shortfall --
    regardless of `cash_constrained`. Reuses `TestSellsBeforeBuys`'s forced-shortfall scenario
    specifically because it *does* generate underfunded buys: if capping a buy were ever going to leak
    a phantom flow, this is the scenario that would surface it."""

    def _run(self, *, cash_constrained: bool):
        dates = _business_days(dt.date(2024, 1, 2), dt.date(2024, 2, 20))
        closes = {"X": [100.0] * len(dates), "Y": [100.0] * len(dates)}

        def weight_fn(i: int, closes):
            return {"Y": 1.0} if i < 10 else {"X": 1.0}

        return contributions.simulate(
            dates, closes, weight_fn,
            contribution=0.0, seed=10_000.0,
            band_pct=0.01, slippage_bps=100.0, use_contributions_to_rebalance=False,
            cash_constrained=cash_constrained,
        )

    def test_flows_unchanged_by_the_constraint(self) -> None:
        off = self._run(cash_constrained=False)
        on = self._run(cash_constrained=True)

        # Exactly one flow either way: the seed, at session 0. Nothing added for the rejected buys.
        assert len(off.flows) == len(on.flows) == 1
        assert on.flows[0].date == off.flows[0].date == self._run(cash_constrained=True).dates[0]
        assert on.flows[0].amount == off.flows[0].amount == 10_000.0

        # Underfunding definitely happened here (see TestSellsBeforeBuys), so this is not a vacuous
        # check of a run where there was never anything to leak.
        assert on.underfunded_buys > 0

    def test_irr_and_time_weighted_cagr_stay_finite_and_computed_from_real_flows(self) -> None:
        on = self._run(cash_constrained=True)

        assert on.irr is not None
        assert math.isfinite(on.irr)
        assert math.isfinite(on.time_weighted_cagr)
        # One contribution in, growth-free flat prices net of slippage drag only: IRR must be a modest
        # loss (all the cost is slippage paid on capped rebalances), not some wild number a phantom
        # flow would produce.
        assert -0.5 < on.irr < 0.0


class TestSettlementDaysDefaultIsInert:
    """`settlement_days` defaults to `0`, and a `0` must be a true no-op.

    Round 19 adds settlement because round 16 measured its own `cash_constrained` as worth nothing
    across 31 cells and its follow-up established why: that constraint executes every sell before any
    buy and lets the proceeds fund them in the same session, so it is settlement-free by construction.
    Every round-15 and round-16 number has to survive the addition untouched, or the new parameter has
    silently restated the record it was built to extend.
    """

    def _run(self, **kwargs):
        dates = _business_days(dt.date(2020, 1, 1), dt.date(2022, 12, 31))
        closes = {
            "A": [100.0 * (1 + 0.15 * math.sin(i / 40.0) + 0.0003 * i) for i in range(len(dates))],
            "B": [50.0 * (1 + 0.10 * math.cos(i / 55.0) + 0.0002 * i) for i in range(len(dates))],
        }
        return contributions.simulate(dates, closes, _static_weight_fn({"A": 0.6, "B": 0.4}), **kwargs)

    def test_zero_reproduces_the_implicit_default_field_by_field(self) -> None:
        implicit = self._run()
        explicit = self._run(settlement_days=0)
        for field in ("final_balance", "total_contributed", "turnover", "cost_paid",
                      "rebalances", "contribution_buys", "underfunded_buys", "underfunded_shortfall"):
            assert getattr(explicit, field) == getattr(implicit, field), field

    def test_zero_is_inert_under_the_cash_constraint_too(self) -> None:
        """The two parameters are independent, so `settlement_days=0` must change nothing about a
        `cash_constrained=True` run either -- round 16's 31 cells depend on it."""
        without = self._run(cash_constrained=True)
        with_zero = self._run(cash_constrained=True, settlement_days=0)
        assert with_zero.final_balance == without.final_balance
        assert with_zero.underfunded_buys == without.underfunded_buys


class TestSettlementActuallyBinds:
    """A rebalance that sells one sleeve to fund another is exactly the trade settlement blocks.

    Constructed so the band genuinely breaches: one sleeve triples while the other is flat, which
    drives drift well past `band_pct` and forces a sell-to-buy rebalance rather than a
    contribution-funded one. Without that, settlement has nothing to bind on -- a synthetic series
    whose sleeves drift gently is funded entirely out of deposits and reports zero underfunded buys at
    any settlement lag, which looks like a passing test and proves nothing.
    """

    def _run(self, **kwargs):
        dates = _business_days(dt.date(2021, 1, 1), dt.date(2021, 12, 31))
        n = len(dates)
        closes = {
            "A": [100.0 * (1 + 2.0 * i / n) for i in range(n)],   # triples
            "B": [100.0 for _ in range(n)],                        # flat
        }
        return contributions.simulate(
            dates, closes, _static_weight_fn({"A": 0.5, "B": 0.5}),
            contribution=0.0, cadence="annual", seed=100_000.0, band_pct=0.05, slippage_bps=0.0,
            **kwargs,
        )

    def test_settlement_blocks_buys_the_same_session_cap_allows(self) -> None:
        same_session = self._run(cash_constrained=True)
        settled = self._run(cash_constrained=True, settlement_days=1)
        assert same_session.underfunded_buys == 0, (
            "the same-session cash cap should never bind -- that is round 16's finding, and if it "
            "binds here the scenario is not testing what this class claims"
        )
        assert settled.underfunded_buys > 0, "T+1 settlement must block at least one rebuy"

    def test_a_longer_lag_binds_at_least_as_hard(self) -> None:
        t1 = self._run(cash_constrained=True, settlement_days=1)
        t2 = self._run(cash_constrained=True, settlement_days=2)
        assert t2.underfunded_buys >= t1.underfunded_buys

    def test_a_deposit_is_spendable_immediately_even_with_proceeds_outstanding(self) -> None:
        """Only sale proceeds wait. A contribution is settled cash on arrival, and a settlement model
        that made deposits wait would understate every contribution-funded strategy for a reason no
        broker applies."""
        dates = _business_days(dt.date(2021, 1, 1), dt.date(2021, 12, 31))
        n = len(dates)
        closes = {"A": [100.0 * (1 + 2.0 * i / n) for i in range(n)], "B": [100.0 for _ in range(n)]}
        funded = contributions.simulate(
            dates, closes, _static_weight_fn({"A": 0.5, "B": 0.5}),
            contribution=1_000.0, cadence="monthly", seed=100_000.0,
            band_pct=0.05, slippage_bps=0.0, cash_constrained=True, settlement_days=1,
        )
        assert funded.contribution_buys > 0, "deposits must still be spent on the underweight sleeve"
