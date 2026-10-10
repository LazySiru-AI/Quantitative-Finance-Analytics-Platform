"""Tests for `app.rules.macro_binding` -- the release-date join that keeps a macro rule causal.

The important tests here are not the shape ones. They are the ones that demonstrate the binding
**excludes something a naive join would have included**, because a join that merely produces
plausible numbers is exactly what the reference-date version already does.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from app.market.macro_models import MacroPoint, MacroSeries, MacroSource, MacroUnit
from app.rules.grammar import parse, parse_ranking
from app.rules.macro_binding import (
    RELEASE_LAG,
    UnlistedMacroFieldError,
    bind_for_bars,
    bind_macro,
    eligibility_dates,
    required_macro_fields,
    verify_release_binding,
)
from app.rules.macro_pin import MACRO_PIN_ENV, MissingPinError, clear_pin_cache
from app.rules.nodes import MacroField


def _series(series_id: str, points: list[tuple[dt.date, float | None]]) -> MacroSeries:
    return MacroSeries(
        series_id=series_id,
        title=series_id,
        unit=MacroUnit.INDEX,
        source=MacroSource.FRED,
        points=[MacroPoint(date=d, value=v) for d, v in points],
    )


def _index(*dates: dt.date) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([dt.datetime(d.year, d.month, d.day) for d in dates])


class TestReleaseDateBinding:
    def test_a_daily_value_is_not_visible_on_its_own_reference_date(self) -> None:
        """`DGS10` stamped 2026-06-10 is known after that session closes, not during it.

        This is the same rule the backtest engine already applies to prices -- decisions use data
        strictly before the decision session -- and applying it to a macro value is what stops
        `macro(DGS10)` being the one leaf in a rule that can see its own bar."""
        series = _series("DGS10", [(dt.date(2026, 6, 10), 4.5)])
        idx = _index(dt.date(2026, 6, 10), dt.date(2026, 6, 11))

        bound = bind_macro([MacroField.DGS10], {MacroField.DGS10: series}, idx)

        assert pd.isna(bound["DGS10"].iloc[0]), "visible on its own reference date"
        assert bound["DGS10"].iloc[1] == 4.5

    def test_a_monthly_index_is_withheld_for_the_full_release_lag(self) -> None:
        """Core CPI for July carries the date 2026-07-01 and is not published on 2026-07-01.

        45 days is the configured lag, so the value appears on 2026-08-15 and not before. The bar on
        2026-08-14 -- six weeks after the reference date, and still before the configured release --
        must see nothing."""
        series = _series("CPILFESL", [(dt.date(2026, 7, 1), 336.789)])
        idx = _index(dt.date(2026, 7, 1), dt.date(2026, 8, 14), dt.date(2026, 8, 15))

        bound = bind_macro([MacroField.CPILFESL], {MacroField.CPILFESL: series}, idx)

        assert pd.isna(bound["CPILFESL"].iloc[0])
        assert pd.isna(bound["CPILFESL"].iloc[1])
        assert bound["CPILFESL"].iloc[2] == pytest.approx(336.789)

    def test_the_binding_withholds_what_a_reference_date_join_would_have_shown(self) -> None:
        """**The point of the module, stated as a differential rather than an absolute.**

        A test that only asserts "the value appears on 2026-08-15" would pass against a join that
        happened to be off in some other way. This one computes what the *naive* join -- the one
        `app.market.macro._nearest_on_or_before` performs, selecting on ``point.date <= target`` --
        would have produced on the same bars, and asserts the two genuinely disagree.

        The disagreement is the lookahead. On 2026-07-15 a reference-date join hands a rule July's
        core CPI a month before it was published; this binding hands it ``NaN``. If these two ever
        agree on every bar, the release lag has stopped doing anything.
        """
        series = _series("CPILFESL", [(dt.date(2026, 7, 1), 336.789)])
        bars = [dt.date(2026, 7, 15), dt.date(2026, 8, 1), dt.date(2026, 8, 20)]
        idx = _index(*bars)

        bound = bind_macro([MacroField.CPILFESL], {MacroField.CPILFESL: series}, idx)

        # The naive join, written out rather than imported, so this test states the thing it is
        # guarding against instead of depending on the module that implements it.
        naive = [
            next(
                (p.value for p in reversed(series.points) if p.date <= bar and p.value is not None),
                None,
            )
            for bar in bars
        ]

        assert naive == [336.789, 336.789, 336.789], "the naive join sees July's print immediately"
        assert pd.isna(bound["CPILFESL"].iloc[0]), "release-date binding must withhold it on 07-15"
        assert pd.isna(bound["CPILFESL"].iloc[1]), "still withheld on 08-01, inside the 45-day lag"
        assert bound["CPILFESL"].iloc[2] == pytest.approx(336.789), "published by 08-20"

        disagreements = sum(
            1
            for naive_value, bound_value in zip(naive, bound["CPILFESL"], strict=True)
            if pd.isna(bound_value) != (naive_value is None)
        )
        assert disagreements == 2, "the two joins must differ on exactly the pre-release bars"

    def test_a_value_carries_forward_until_the_next_release(self) -> None:
        """A monthly series genuinely holds its last published figure between releases -- that is
        what a decision-maker knew on each of those days, not an interpolation choice."""
        series = _series(
            "CPILFESL", [(dt.date(2026, 6, 1), 100.0), (dt.date(2026, 7, 1), 200.0)]
        )
        idx = _index(dt.date(2026, 7, 20), dt.date(2026, 8, 10), dt.date(2026, 8, 20))

        bound = bind_macro([MacroField.CPILFESL], {MacroField.CPILFESL: series}, idx)

        # June's print is eligible from 07-16; July's from 08-15.
        assert bound["CPILFESL"].tolist() == [100.0, 100.0, 200.0]

    def test_a_holiday_gap_does_not_erase_the_last_real_print(self) -> None:
        """FRED writes ``.`` for a market holiday, which parses to ``value=None``. A non-publication
        is not a publication of nothing: the previous figure stands, which is what a reader that day
        would have seen."""
        series = _series(
            "DGS10", [(dt.date(2026, 6, 10), 4.5), (dt.date(2026, 6, 11), None)]
        )
        idx = _index(dt.date(2026, 6, 12), dt.date(2026, 6, 13))

        bound = bind_macro([MacroField.DGS10], {MacroField.DGS10: series}, idx)

        assert bound["DGS10"].tolist() == [4.5, 4.5]

    def test_bars_before_any_release_are_nan_not_zero(self) -> None:
        """``NaN`` propagates to ``NA`` through the evaluator's Kleene layer, so a gated card is
        *undefined* there rather than *excluded*. Zero would silently satisfy ``> -1``."""
        series = _series("DGS10", [(dt.date(2026, 6, 10), 4.5)])
        idx = _index(dt.date(2026, 1, 2), dt.date(2026, 1, 3))

        bound = bind_macro([MacroField.DGS10], {MacroField.DGS10: series}, idx)

        assert bound["DGS10"].isna().all()

    def test_a_tz_aware_index_binds_on_the_same_calendar_days(self) -> None:
        """Bar indices may be tz-aware; a FRED date is a bare calendar day. Comparing them without
        normalising is either a TypeError or an off-by-one across midnight."""
        series = _series("DGS10", [(dt.date(2026, 6, 10), 4.5)])
        naive = _index(dt.date(2026, 6, 10), dt.date(2026, 6, 11))
        aware = naive.tz_localize("UTC")

        bound_naive = bind_macro([MacroField.DGS10], {MacroField.DGS10: series}, naive)
        bound_aware = bind_macro([MacroField.DGS10], {MacroField.DGS10: series}, aware)

        # `equal_nan` because the first bar is legitimately NaN under both bindings and `nan != nan`
        # would fail on a correct result. Compared as arrays rather than Series: the two carry
        # different index dtypes by construction, which is the whole point of the test.
        assert np.array_equal(
            bound_naive["DGS10"].to_numpy(), bound_aware["DGS10"].to_numpy(), equal_nan=True
        )


class TestFailsClosed:
    def test_every_macro_field_has_a_release_lag(self) -> None:
        assert set(RELEASE_LAG) == set(MacroField)

    def test_a_field_with_no_lag_raises_rather_than_defaulting_to_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A zero default would bind by reference date, which is the whole failure being prevented --
        and it would do so while producing a *better* backtest and no error.

        The table is complete (asserted directly above), so the only way to reach this branch is to
        remove an entry -- which is exactly the mistake it guards against. Without this the branch
        would never have executed, and the day someone adds a series and forgets the table would be
        its first run."""
        thinned = {k: v for k, v in RELEASE_LAG.items() if k is not MacroField.DGS10}
        monkeypatch.setattr("app.rules.macro_binding.RELEASE_LAG", thinned)

        with pytest.raises(UnlistedMacroFieldError) as excinfo:
            eligibility_dates(MacroField.DGS10, [])

        assert excinfo.value.field is MacroField.DGS10
        assert "not defaulted to zero" in str(excinfo.value)

    def test_bind_macro_refuses_to_invent_a_missing_series(self) -> None:
        """Defaulting an absent series to ``NaN`` would make a gated card silently never trade,
        which reads as a strategy with no signals rather than as a wiring bug."""
        with pytest.raises(KeyError, match="no MacroSeries supplied"):
            bind_macro([MacroField.DGS10], {}, _index(dt.date(2026, 6, 10)))

    def test_no_fields_is_an_empty_frame_not_an_error(self) -> None:
        idx = _index(dt.date(2026, 6, 10))
        assert bind_macro([], {}, idx).empty


class TestRequiredMacroFields:
    def test_it_finds_fields_nested_under_boolean_structure(self) -> None:
        tree = parse("not (close > 1 and (macro(T10Y2Y) > 0 or macro(DGS10) < 5))")
        assert required_macro_fields(tree) == [MacroField.T10Y2Y, MacroField.DGS10]

    def test_it_finds_a_field_inside_arithmetic_in_a_ranking_key(self) -> None:
        tree = parse_ranking("close / macro(DGS10)")
        assert required_macro_fields(tree) == [MacroField.DGS10]

    def test_it_deduplicates_and_preserves_first_encountered_order(self) -> None:
        tree = parse("macro(DGS10) > 1 and macro(T10Y2Y) > 0 and macro(DGS10) < 9")
        assert required_macro_fields(tree) == [MacroField.DGS10, MacroField.T10Y2Y]

    def test_a_tree_with_no_macro_reference_returns_empty(self) -> None:
        assert required_macro_fields(parse("close > sma(20)")) == []


class TestBindForBars:
    """The one function the run path calls."""

    def test_a_price_only_tree_binds_nothing(self) -> None:
        """The overwhelmingly common case, and the reason nothing else in the engine changed: a rule
        with no `macro(...)` gets `None`, the call to `evaluate` is byte-identical to what it was
        before macro fields existed, and no pin is consulted or required."""
        bars = pd.DataFrame({"ts": pd.to_datetime(["2026-06-10", "2026-06-11"]), "close": [1.0, 2.0]})

        assert bind_for_bars(parse("close > sma(2)"), bars) is None

    def test_dates_come_from_the_ts_column_when_there_is_one(self) -> None:
        """`app.backtest.strategy` and `app.backtest.events` carry timestamps in a `ts` column over a
        *positional* index. Reading dates off that index instead would bind every bar to 1970 and
        raise nothing at all -- every value would simply be NaN, which reads as "the series has no
        history here" rather than as a bug."""
        series = _series("DGS10", [(dt.date(2026, 6, 10), 4.5)])
        bars = pd.DataFrame(
            {"ts": pd.to_datetime(["2026-06-10", "2026-06-11"]), "close": [1.0, 2.0]}
        )
        assert list(bars.index) == [0, 1], "this test is only meaningful on a positional index"

        bound = bind_for_bars(
            parse("macro(DGS10) > 1"), bars, series={MacroField.DGS10: series}
        )

        assert bound is not None
        assert list(bound.index) == [0, 1], "output must stay aligned to the caller's own index"
        assert pd.isna(bound["DGS10"].iloc[0])
        assert bound["DGS10"].iloc[1] == 4.5

    def test_a_macro_rule_without_a_pin_refuses_rather_than_fetching(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**The determinism guarantee, enforced.** A live fetch here would make the run reproducible
        in its dates and not in its values, because FRED serves revised numbers against the same
        reference dates -- the failure that looks like success. `PROTOCOL.md` §8 requires the
        opposite, so an unpinned macro rule stops."""
        monkeypatch.delenv(MACRO_PIN_ENV, raising=False)
        clear_pin_cache()
        bars = pd.DataFrame({"ts": pd.to_datetime(["2026-06-10"]), "close": [1.0]})

        with pytest.raises(MissingPinError, match="no macro pin is configured"):
            bind_for_bars(parse("macro(DGS10) > 1"), bars)

    def test_a_mismatched_date_count_raises_rather_than_misaligning(self) -> None:
        """One date per bar, or the join attributes a macro value to the wrong session -- silently,
        since both sides are just sequences."""
        series = _series("DGS10", [(dt.date(2026, 6, 10), 4.5)])
        idx = _index(dt.date(2026, 6, 10), dt.date(2026, 6, 11))

        with pytest.raises(ValueError, match="must correspond one-to-one"):
            bind_macro(
                [MacroField.DGS10],
                {MacroField.DGS10: series},
                idx,
                dates=[dt.date(2026, 6, 10)],
            )


class TestVerifyReleaseBinding:
    """A verifier that only ever passes is indistinguishable from no verifier.

    The first test here builds the *naive* binding -- the reference-date join this whole module
    exists to replace -- and demands the verifier catch it. If that ever stops failing, the check has
    become decoration.
    """

    def test_it_catches_the_naive_reference_date_binding(self) -> None:
        series = _series("CPILFESL", [(dt.date(2026, 7, 1), 336.789)])
        bars = [dt.date(2026, 7, 15), dt.date(2026, 8, 1), dt.date(2026, 8, 20)]
        idx = _index(*bars)

        # The bug, constructed deliberately: every bar on or after the *reference* date sees the
        # value, with no release lag applied at all.
        naive = pd.DataFrame(
            {
                "CPILFESL": [
                    336.789 if bar >= dt.date(2026, 7, 1) else float("nan") for bar in bars
                ]
            },
            index=idx,
        )

        violations = verify_release_binding(
            naive, [MacroField.CPILFESL], {MacroField.CPILFESL: series}, bars
        )

        assert len(violations) == 2, [v.describe() for v in violations]
        assert {v.bar_date for v in violations} == {dt.date(2026, 7, 15), dt.date(2026, 8, 1)}
        assert violations[0].bound_value == pytest.approx(336.789)
        assert violations[0].expected_value is None
        assert "had been released by then" in violations[0].describe()

    def test_the_real_binding_passes_its_own_verifier(self) -> None:
        """The other direction. Note this is a weaker statement than the test above: two pieces of
        code by the same author agreeing proves consistency, not correctness -- which is why the
        verifier bisects an explicit eligibility list where `bind_macro` carries a forward cursor,
        so a cursor bug cannot reproduce identically in both and cancel out."""
        series = _series(
            "CPILFESL", [(dt.date(2026, 6, 1), 100.0), (dt.date(2026, 7, 1), 200.0)]
        )
        bars = [dt.date(2026, 7, 20), dt.date(2026, 8, 10), dt.date(2026, 8, 20)]
        idx = _index(*bars)
        bound = bind_macro(
            [MacroField.CPILFESL], {MacroField.CPILFESL: series}, idx, dates=bars
        )

        assert (
            verify_release_binding(
                bound, [MacroField.CPILFESL], {MacroField.CPILFESL: series}, bars
            )
            == []
        )

    def test_it_catches_a_value_bound_one_day_early(self) -> None:
        """The subtle version. A binding off by a single day on a daily series is not visible in a
        chart and shifts every signal forward by one session."""
        series = _series("DGS10", [(dt.date(2026, 6, 10), 4.5)])
        bars = [dt.date(2026, 6, 10), dt.date(2026, 6, 11)]
        early = pd.DataFrame({"DGS10": [4.5, 4.5]}, index=_index(*bars))

        violations = verify_release_binding(
            early, [MacroField.DGS10], {MacroField.DGS10: series}, bars
        )

        assert [v.bar_date for v in violations] == [dt.date(2026, 6, 10)]

    def test_a_holiday_none_does_not_advance_the_expectation(self) -> None:
        """The verifier must model FRED's `.` the same way the binding does, or it would report a
        violation on every market holiday and be turned off within a week."""
        series = _series(
            "DGS10", [(dt.date(2026, 6, 10), 4.5), (dt.date(2026, 6, 11), None)]
        )
        bars = [dt.date(2026, 6, 12), dt.date(2026, 6, 13)]
        bound = pd.DataFrame({"DGS10": [4.5, 4.5]}, index=_index(*bars))

        assert (
            verify_release_binding(bound, [MacroField.DGS10], {MacroField.DGS10: series}, bars)
            == []
        )
