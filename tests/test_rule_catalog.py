"""Tests for the Phase 6 rule catalog (`app.rules.catalog`).

The parse-everything test in `TestCatalogParses` is the one that matters most: a catalog entry that
400s at render time -- because a typo in the DSL never surfaces until a user actually opens the
decision table -- is exactly the failure mode this file exists to catch before it ships.
`app.rules.grammar` may not exist yet while this phase is still being built in parallel by another
agent; `pytest.importorskip` skips those tests cleanly until it does, but they run for real -- and
must pass -- once it lands in the final suite.
"""

from __future__ import annotations

import pytest

from app.db.duck import Interval
from app.rules import catalog


class TestCatalogCompleteness:
    def test_catalog_has_a_reasonable_number_of_genuinely_different_rules(self) -> None:
        """10-14 per the brief: enough to be useful, few enough that every entry earns its place."""
        rules = catalog.catalog()
        assert 10 <= len(rules) <= 14

    def test_rule_ids_are_unique(self) -> None:
        ids = [r.rule_id for r in catalog.catalog()]
        assert len(ids) == len(set(ids))

    def test_expressions_are_unique(self) -> None:
        """No two catalog entries describing the identical condition under different names."""
        expressions = [r.expression for r in catalog.catalog()]
        assert len(expressions) == len(set(expressions))

    def test_every_rule_has_a_name_expression_and_description(self) -> None:
        for rule in catalog.catalog():
            assert rule.rule_id.strip()
            assert rule.name.strip()
            assert rule.expression.strip()
            assert rule.description.strip()

    def test_catalog_covers_the_required_indicator_families(self) -> None:
        """The brief: RSI, a Bollinger band, an EMA cross, a MACD flip, a long SMA, ATR volatility --
        genuinely different signal families, not fifteen variations on one indicator."""
        text = " ".join(rule.expression for rule in catalog.catalog())
        for token in ("rsi(", "bb_", "ema(", "macd_", "sma(", "atr(", "vwap("):
            assert token in text, f"no catalog rule references {token!r}"

    def test_get_returns_the_matching_rule(self) -> None:
        rule = catalog.get("rsi_oversold")
        assert rule is not None
        assert rule.rule_id == "rsi_oversold"
        assert rule in catalog.catalog()

    def test_get_returns_none_for_an_unknown_id(self) -> None:
        assert catalog.get("not_a_real_rule_id") is None

    def test_catalog_returns_a_fresh_list_each_call(self) -> None:
        """Mutating the caller's list must not corrupt the module's own catalog."""
        rules = catalog.catalog()
        rules.clear()
        assert len(catalog.catalog()) >= 10

    def test_vwap_rule_is_declared_intraday_only(self) -> None:
        """A VWAP-based rule is intraday-only -- declared here, not discovered as a 400 later."""
        vwap_rules = [r for r in catalog.catalog() if "vwap(" in r.expression]
        assert vwap_rules
        for rule in vwap_rules:
            assert rule.intervals
            assert set(rule.intervals) <= {Interval.FIVE_MIN, Interval.HOUR}

    def test_non_vwap_rules_declare_no_interval_restriction(self) -> None:
        """Every other rule is built only from OHLCV and always-available indicators, so `intervals`
        must be empty ("any") -- restricting it would be dishonest, not merely conservative."""
        for rule in catalog.catalog():
            if "vwap(" not in rule.expression:
                assert rule.intervals == ()


class TestCatalogParses:
    """Every catalog expression must parse -- see the module docstring."""

    def test_every_expression_parses(self) -> None:
        grammar = pytest.importorskip("app.rules.grammar")
        failures: list[str] = []
        for rule in catalog.catalog():
            try:
                grammar.parse(rule.expression)
            except Exception as exc:
                failures.append(f"{rule.rule_id} ({rule.expression!r}): {exc}")
        assert not failures, "catalog expressions failed to parse:\n" + "\n".join(failures)

    def test_every_expression_round_trips_through_parse_render_parse(self) -> None:
        """`Rule.expression` must round-trip: re-parsing the rendered form of a parsed tree produces
        an equivalent tree -- see `Rule.expression`'s own docstring for why this is load-bearing."""
        grammar = pytest.importorskip("app.rules.grammar")
        for rule in catalog.catalog():
            node = grammar.parse(rule.expression)
            reparsed = grammar.parse(grammar.render(node))
            assert node == reparsed, f"{rule.rule_id}: {rule.expression!r} did not round-trip"
