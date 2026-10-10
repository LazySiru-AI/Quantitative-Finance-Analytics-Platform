"""The lookahead guard.

A guard is only worth its runtime if it fails on something. Most of these tests therefore construct
a violation and demand it be caught -- ``TestCatchesANonCausalIndicator`` is the one that proves the
module works at all, and without it the rest only establish that legitimate rules are not molested.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.backtest import guards
from app.backtest.models import GuardStatus
from app.db.duck import Interval
from app.indicators import registry as indicator_registry
from app.indicators.base import IndicatorSpec, Pane, ParamKind, ParamSpec
from app.market.macro_models import MacroPoint, MacroSeries, MacroSource, MacroUnit
from app.rules import catalog as rule_catalog
from app.rules import grammar as rule_grammar
from app.rules import macro_pin, nodes
from app.rules.macro_binding import RELEASE_LAG


def _bars(n: int = 400, *, seed: int = 11) -> pd.DataFrame:
    """A random walk with a strictly positive price, enough bars to clear every catalog warmup."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, 1.0, size=n).cumsum()
    close = 100.0 + steps
    close = np.maximum(close, 1.0)
    return pd.DataFrame(
        {
            "ts": pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"),
            "open": close - 0.25,
            "high": close + 0.75,
            "low": close - 0.75,
            "close": close,
            "adj_close": close,
            "volume": rng.uniform(1e6, 5e6, size=n),
        }
    )


class TestCatalogRulesPass:
    """Every shipped rule must clear the guard. A catalog entry that cannot is a defect in the
    catalog, not a reason to loosen the guard."""

    @pytest.mark.parametrize("rule", rule_catalog.catalog(), ids=lambda r: r.rule_id)
    def test_every_catalogued_rule_is_causal(self, rule) -> None:  # type: ignore[no-untyped-def]
        if rule.intervals and Interval.DAY not in rule.intervals:
            pytest.skip(f"{rule.rule_id} is not defined on daily bars")
        report = guards.check(rule.expression, _bars(), interval=Interval.DAY)
        assert report.status is GuardStatus.PASSED, [
            f.detail for f in report.findings if not f.passed
        ]

    def test_the_catalog_is_not_empty(self) -> None:
        """Guards against the parametrisation above silently covering nothing."""
        assert len(rule_catalog.catalog()) >= 10


class TestCatchesANonCausalIndicator:
    """The test the module exists for.

    Each of these registers an indicator that genuinely reads bars it should not, and demands the
    guard notice. A guard that only ever passes is indistinguishable from no guard at all.
    """

    @staticmethod
    def _register(monkeypatch: pytest.MonkeyPatch, name: str, fn) -> None:  # type: ignore[no-untyped-def]
        """Register a deliberately non-causal indicator on both registry bindings.

        Two patches, not one. `app.rules.grammar` does `from app.indicators.registry import get as
        _get_indicator_spec` at module scope, so it holds its own reference and patching only
        `indicator_registry.get` leaves the parser rejecting the name before the guard ever sees the
        tree -- which is what happened the first time this was written, and it made the guard look
        like it had caught something when it had not.
        """
        spec = IndicatorSpec(
            name=name,
            title=name,
            fn=fn,
            params=(ParamSpec(name="period", kind=ParamKind.INT, default=10, minimum=1),),
            pane=Pane.OSCILLATOR,
            warmup=lambda p: int(p["period"]),
        )
        real_get = indicator_registry.get

        def patched(n: str) -> IndicatorSpec | None:
            return spec if n == name else real_get(n)

        monkeypatch.setattr(indicator_registry, "get", patched)
        monkeypatch.setattr(rule_grammar, "_get_indicator_spec", patched)

    def test_a_centered_rolling_window_is_caught(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`center=True` averages bars on both sides of `t`. It is the classic accidental lookahead
        and it is invisible in a chart -- the line simply looks impressively well-timed."""

        def peeking(bars: pd.DataFrame, /, **params: object) -> pd.DataFrame:
            period = int(params["period"])  # type: ignore[call-overload]
            return pd.DataFrame(
                {f"peek_{period}": bars["close"].rolling(period, center=True).mean()},
                index=bars.index,
            )

        self._register(monkeypatch, "peek", peeking)
        report = guards.check("peek(10) > 0", _bars(), interval=Interval.DAY)

        assert report.status is GuardStatus.FAILED
        causality = [f for f in report.findings if f.check == "causality" and not f.passed]
        assert causality, report.findings
        assert "changed when bars after" in causality[0].detail

    def test_a_whole_series_normalisation_is_caught(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dividing by the maximum of the *whole* series makes every early bar depend on a high that
        had not happened yet. Nothing about the resulting series looks wrong."""

        def normalised(bars: pd.DataFrame, /, **params: object) -> pd.DataFrame:
            period = int(params["period"])  # type: ignore[call-overload]
            return pd.DataFrame(
                {f"norm_{period}": bars["close"] / bars["close"].max()}, index=bars.index
            )

        self._register(monkeypatch, "norm", normalised)
        report = guards.check("norm(10) > 0.5", _bars(), interval=Interval.DAY)

        assert report.status is GuardStatus.FAILED
        assert any(f.check == "causality" and not f.passed for f in report.findings)

    def test_a_backfill_is_caught(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`bfill` pulls a later value backwards by definition."""

        def backfilled(bars: pd.DataFrame, /, **params: object) -> pd.DataFrame:
            period = int(params["period"])  # type: ignore[call-overload]
            shifted = bars["close"].shift(-1)
            return pd.DataFrame({f"bf_{period}": shifted.bfill()}, index=bars.index)

        self._register(monkeypatch, "bf", backfilled)
        report = guards.check("bf(10) > 0", _bars(), interval=Interval.DAY)

        assert report.status is GuardStatus.FAILED
        assert any(f.check == "causality" and not f.passed for f in report.findings)

    def test_the_finding_names_the_bar_and_both_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A finding that says only "failed" cannot be acted on. It must locate the disagreement."""

        def peeking(bars: pd.DataFrame, /, **params: object) -> pd.DataFrame:
            period = int(params["period"])  # type: ignore[call-overload]
            return pd.DataFrame(
                {f"peek_{period}": bars["close"].shift(-3)}, index=bars.index
            )

        self._register(monkeypatch, "peek", peeking)
        report = guards.check("peek(10) > 0", _bars(), interval=Interval.DAY)
        detail = next(f.detail for f in report.findings if f.check == "causality" and not f.passed)

        assert "value at bar " in detail
        assert " vs " in detail
        assert "bars[:" in detail


class TestRecursiveIndicatorsAreNotFalselyAccused:
    """Wilder-smoothed and exponentially-weighted indicators are causal but *not* invariant under
    head truncation -- their seed moves. The guard truncates the tail precisely so these pass
    exactly, with no tolerance to hide behind."""

    @pytest.mark.parametrize("expression", [
        "rsi(14) < 30",
        "ema(50) > ema(200)",
        "macd_hist(12,26,9) > 0",
        "atr(14) > 1",
        "close < bb_lower(20,2)",
        "sma(20) > sma(50)",
    ])
    def test_recursive_and_windowed_indicators_pass_exactly(self, expression: str) -> None:
        report = guards.check(expression, _bars(600), interval=Interval.DAY)
        if report.status is not GuardStatus.PASSED:
            failures = [f.detail for f in report.findings if not f.passed]
            pytest.fail(f"{expression} rejected: {failures}")

    def test_the_check_actually_ran(self) -> None:
        """A pass is only meaningful if the causality check produced a positive finding -- otherwise
        an expression with no indicators at all would 'pass' the same way."""
        report = guards.check("rsi(14) < 30", _bars(600), interval=Interval.DAY)
        causality = [f for f in report.findings if f.check == "causality"]
        assert causality and all(f.passed for f in causality)
        assert "leading slices" in causality[0].detail


class TestFailsClosed:
    """Anything unrecognised is rejected. These pin the mechanism, not just the outcome."""

    def test_an_unknown_node_type_is_rejected_by_name(self) -> None:
        @dataclasses.dataclass(frozen=True)
        class Lead:
            """A hypothetical future-referencing node nobody told the guard about."""

            operand: object
            bars: int

        findings: list = []
        guards._walk(Lead(operand=None, bars=3), findings)

        assert findings and not findings[0].passed
        assert "Lead" in findings[0].detail
        assert findings[0].check == "ast_whitelist"

    def test_the_allowlist_covers_every_node_the_ast_exports(self) -> None:
        """The mechanism that makes fail-closed survive a refactor.

        If someone adds a node type to `app.rules.nodes` without teaching this guard about it, this
        test fails *here*, in the guard's own suite, rather than the guard silently permitting a
        construct it has never reasoned about.
        """
        assert guards._unlisted_node_types() == set()

    def test_adj_close_is_not_a_referenceable_field(self) -> None:
        """Pinned in two directions: the AST must not offer it, and the guard's own allowlist is
        derived from `PriceField` so re-adding it there would surface here."""
        assert "adj_close" not in {f.value for f in nodes.PriceField}
        assert frozenset(nodes.PriceField) == guards._ALLOWED_PRICE_FIELDS

    def test_the_macro_allowlist_mirrors_the_enum(self) -> None:
        """Same mechanism as `_ALLOWED_PRICE_FIELDS` above: a series added to `MacroField` without
        the guard being told surfaces here rather than being silently permitted."""
        assert frozenset(nodes.MacroField) == guards._ALLOWED_MACRO_FIELDS

    def test_every_permitted_macro_field_has_a_release_lag(self) -> None:
        """**The second, separate check, and the one with a silent failure mode.**

        Passing `_ALLOWED_MACRO_FIELDS` means the guard knows the series exists. It does *not* mean
        the guard knows when a value in it became public -- that is `RELEASE_LAG`. A series added to
        the enum and the allowlist but forgotten in the lag table would bind by *reference* date,
        reading a figure on the day it describes rather than the day it was published.

        That failure produces a **better** backtest and no error, which is why it gets its own test
        rather than riding on the allowlist's. `strategy-program/ROUND-21-PLAN.md` §2d is explicit
        that the two are separate conditions."""
        missing = {f.value for f in nodes.MacroField} - {f.value for f in RELEASE_LAG}
        assert missing == set(), (
            f"macro fields {sorted(missing)} have no RELEASE_LAG entry; they would bind by "
            f"reference date, which is the lookahead the release-date binding exists to prevent"
        )

    def test_a_macro_gated_rule_without_a_pin_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unverifiable guard must fail, not pass quietly.

        Written first as `test_a_macro_gated_rule_passes_the_guard`, asserting the rule cleared the
        guard with no pin configured -- which it did, until the release-binding check existed. That
        assertion was wrong in the direction that matters: it would have let a card whose causality
        nothing had checked report a clean guard."""
        monkeypatch.delenv(macro_pin.MACRO_PIN_ENV, raising=False)
        macro_pin.clear_pin_cache()

        report = guards.check("close > sma(20) and macro(T10Y2Y) > 0", _bars(), interval=Interval.DAY)

        assert report.status is GuardStatus.FAILED
        finding = next(f for f in report.findings if f.check == "macro_release_binding")
        assert not finding.passed
        assert "failing closed" in finding.detail

    def test_a_macro_gated_rule_passes_against_a_pin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The positive case, against a pin whose observations span the bars.

        The pin is built here rather than pointing at the round's own committed one, so this test
        does not start failing the day that file is re-pinned -- and so the dates below are visible
        beside the assertion instead of four megabytes away."""
        bars = _bars()
        first = bars["ts"].iloc[0].date() - dt.timedelta(days=30)
        series = MacroSeries(
            series_id="T10Y2Y",
            title="T10Y2Y",
            unit=MacroUnit.PERCENT_SPREAD,
            source=MacroSource.FRED,
            points=[MacroPoint(date=first + dt.timedelta(days=i), value=0.5) for i in range(500)],
        )
        pin = tmp_path / "macro-pin.json"
        macro_pin.write_pin(
            pin, {nodes.MacroField.T10Y2Y: series}, created_at=dt.datetime(2026, 8, 30)
        )
        monkeypatch.setenv(macro_pin.MACRO_PIN_ENV, str(pin))
        macro_pin.clear_pin_cache()

        report = guards.check("close > sma(20) and macro(T10Y2Y) > 0", bars, interval=Interval.DAY)

        assert report.status is not GuardStatus.FAILED, [
            f.detail for f in report.findings if not f.passed
        ]
        finding = next(f for f in report.findings if f.check == "macro_release_binding")
        assert finding.passed
        # The scope note matters as much as the pass: this check proves the configured lag was
        # respected, not that the lag is right and not that the data is point-in-time.
        assert "does not see revisions" in finding.detail

    def test_a_price_only_rule_reports_no_macro_finding_at_all(self) -> None:
        """A price-only rule's report is unchanged -- no new row, passing or failing. A guard that
        added a green 'no macro used' line to every rule in the library would train readers to skim
        the section the one macro card actually needs them to read."""
        report = guards.check("close > sma(20)", _bars(), interval=Interval.DAY)
        assert not any(f.check == "macro_release_binding" for f in report.findings)

    def test_a_macro_field_without_a_lag_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The fail-closed branch, exercised rather than assumed.

        `RELEASE_LAG` is complete today -- the test above asserts exactly that -- so the only way to
        reach this branch is to take an entry away, which is precisely the mistake being guarded
        against. Without this, the branch would be unreachable code that has never run, and the day
        someone adds a series and forgets the table would be its first execution."""
        thinned = {k: v for k, v in RELEASE_LAG.items() if k is not nodes.MacroField.T10Y2Y}
        monkeypatch.setattr(guards, "RELEASE_LAG", thinned)

        report = guards.check("macro(T10Y2Y) > 0", _bars(), interval=Interval.DAY)

        assert report.status is GuardStatus.FAILED
        finding = next(f for f in report.findings if not f.passed)
        assert finding.check == "macro_release_lag"
        assert "T10Y2Y" in finding.detail

    def test_an_unknown_indicator_fails_rather_than_raising(self) -> None:
        """The parser resolves names against the registry, so an unknown indicator is rejected one
        layer earlier than `_resolve` -- as a `parse` finding naming it. `_resolve`'s own
        `unknown_indicator` branch stays as defence in depth for the direct-tree path, but this is
        the behaviour a caller of `check()` actually sees, and the test asserts that rather than the
        branch I expected to be reached."""
        report = guards.check("nosuchthing(14) > 5", _bars(), interval=Interval.DAY)
        assert report.status is GuardStatus.FAILED
        finding = next(f for f in report.findings if not f.passed)
        assert "nosuchthing" in finding.detail

    def test_a_malformed_expression_fails_rather_than_raising(self) -> None:
        report = guards.check("rsi(14) <", _bars(), interval=Interval.DAY)
        assert report.status is GuardStatus.FAILED
        assert any(f.check == "parse" for f in report.findings)

    def test_an_empty_expression_fails_rather_than_raising(self) -> None:
        assert guards.check("", _bars(), interval=Interval.DAY).status is GuardStatus.FAILED

    def test_too_few_bars_to_demonstrate_causality_is_a_failure(self) -> None:
        """Not a pass. The check could not run, and `UNVERIFIED`-shaped outcomes are failures."""
        report = guards.check("rsi(14) < 30", _bars(20), interval=Interval.DAY)
        assert report.status is GuardStatus.FAILED
        detail = next(f.detail for f in report.findings if f.check == "causality")
        assert "could not be demonstrated" in detail

    def test_an_indicator_not_defined_on_this_interval_fails(self) -> None:
        """Anchored VWAP is intraday-only; asking for it on daily bars must be refused here rather
        than producing a line that looks authoritative and says nothing."""
        report = guards.check("close > vwap(session)", _bars(), interval=Interval.DAY)
        assert report.status is GuardStatus.FAILED


class TestReportShape:
    def test_the_verdict_is_deterministic(self) -> None:
        """A guard whose answer moves between runs teaches the reader to ignore it."""
        bars = _bars(500)
        first = guards.check("rsi(14) < 30", bars, interval=Interval.DAY)
        second = guards.check("rsi(14) < 30", bars, interval=Interval.DAY)
        assert first.model_dump() == second.model_dump()

    def test_the_expression_is_echoed_back(self) -> None:
        report = guards.check("rsi(14) < 30", _bars(), interval=Interval.DAY)
        assert report.expression == "rsi(14) < 30"

    def test_a_passing_report_still_states_what_was_not_proven(self) -> None:
        """The point-in-time scope note must survive, or a passed guard reads as a stronger
        guarantee than it is."""
        report = guards.check("rsi(14) < 30", _bars(600), interval=Interval.DAY)
        assert report.status is GuardStatus.PASSED
        note = next(f for f in report.findings if f.check == "point_in_time")
        assert "does not prove those bars are point-in-time" in note.detail

    def test_ok_tracks_status(self) -> None:
        passed = guards.check("rsi(14) < 30", _bars(600), interval=Interval.DAY)
        failed = guards.check("rsi(14) <", _bars(600), interval=Interval.DAY)
        assert passed.ok is True
        assert failed.ok is False


class TestRankingKind:
    """`kind="ranking"` -- the same guard, applied to a `StrategyCard.rank_by` key.

    The point of these is that nothing *except* the parse differs. A ranking key decides which name
    takes a scarce slot, so a non-causal one is lookahead that leaves the entry rule beside it clean
    and passing; if the causality check did not reach through this parameter, that would be silent.
    """

    def test_a_causal_numeric_key_passes(self) -> None:
        report = guards.check("close / sma(200)", _bars(), interval=Interval.DAY, kind="ranking")
        assert report.status is GuardStatus.PASSED

    def test_a_condition_fails_the_parse_check(self) -> None:
        report = guards.check("close > sma(50)", _bars(), interval=Interval.DAY, kind="ranking")
        assert report.status is GuardStatus.FAILED
        assert any(f.check == "parse" and not f.passed for f in report.findings)

    def test_a_rule_is_still_what_the_default_expects(self) -> None:
        # The default is unchanged, so no existing caller acquires ranking semantics by omission.
        assert guards.check("close > sma(50)", _bars(), interval=Interval.DAY).status is (
            GuardStatus.PASSED
        )
        assert (
            guards.check("close / sma(200)", _bars(), interval=Interval.DAY).status
            is GuardStatus.FAILED
        )

    def test_a_non_causal_key_is_caught(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The test this class exists for. Same centered-window indicator `TestCatchesANonCausalIndicator`
        # uses, referenced from a ranking key instead of from a rule.
        def peeking(bars: pd.DataFrame, /, **params: object) -> pd.DataFrame:
            period = int(params["period"])  # type: ignore[call-overload]
            return pd.DataFrame(
                {f"rankpeek_{period}": bars["close"].rolling(period, center=True).mean()},
                index=bars.index,
            )

        TestCatchesANonCausalIndicator._register(monkeypatch, "rankpeek", peeking)
        report = guards.check("rankpeek(10)", _bars(), interval=Interval.DAY, kind="ranking")

        assert report.status is GuardStatus.FAILED
        causality = [f for f in report.findings if f.check == "causality" and not f.passed]
        assert causality, report.findings
        assert "changed when bars after" in causality[0].detail

    def test_an_unknown_indicator_in_a_key_is_caught(self) -> None:
        report = guards.check("wibble(3)", _bars(), interval=Interval.DAY, kind="ranking")
        assert report.status is GuardStatus.FAILED
