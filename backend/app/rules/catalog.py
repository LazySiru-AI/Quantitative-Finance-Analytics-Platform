"""The curated rule catalog: a fixed set of named conditions the decision table can price.

These are not "the best rules" -- there is no such thing independent of an instrument and a regime.
They are the classics a technically-literate user already has an intuition for (RSI extremes, a
Bollinger touch, a moving-average cross, a MACD flip, a long-term trend filter, a volatility
expansion, a VWAP reclaim), chosen so the decision table's evidence columns have something familiar
to calibrate against. A user who has never heard of ``rsi(14) < 30`` cannot judge whether its 54% hit
rate against a 51% baseline means anything; a user who already believes "oversold bounces" can see
the two numbers side by side and update.

**Every expression here is written against the shared DSL in :mod:`app.rules.nodes` / parsed by
:mod:`app.rules.grammar`.** ``bb_lower(20,2)`` is an :class:`~app.rules.nodes.IndicatorRef` with
``name="bb", output="lower", args=(20, 2)``; a multi-output indicator is always referenced as
``{name}_{output}(args...)``, never by the bare indicator name. See ``nodes.py``'s module docstring
for the grammar this must round-trip through.

**Intervals are declared, not discovered.** :attr:`~app.rules.models.Rule.intervals` is empty
("any") for every rule built only from OHLCV and the always-available indicators (RSI, Bollinger,
EMA, MACD, SMA, ATR -- none of those carry an ``intervals`` restriction in
:mod:`app.indicators.registry`). The one exception is the VWAP reclaim rule: anchored VWAP is
registered with ``intervals={5m, 1h}`` (see ``app.indicators.vwap.VWAP_SPEC``) because a
session-anchored average has no meaning on a bar that *is* a session, and this catalog states that
restriction up front rather than letting a daily request 400 at evaluation time.
"""

from __future__ import annotations

from app.db.duck import Interval
from app.rules.models import Rule

__all__ = ["catalog", "get"]

#: Intraday-only intervals VWAP is defined on -- mirrors `app.indicators.vwap.VWAP_SPEC.intervals`.
_INTRADAY: tuple[Interval, ...] = (Interval.FIVE_MIN, Interval.HOUR)

_CATALOG: tuple[Rule, ...] = (
    Rule(
        rule_id="rsi_oversold",
        name="RSI(14) Oversold",
        expression="rsi(14) < 30",
        description="Wilder RSI over 14 bars has dropped below 30, the classic oversold threshold.",
    ),
    Rule(
        rule_id="rsi_overbought",
        name="RSI(14) Overbought",
        expression="rsi(14) > 70",
        description="Wilder RSI over 14 bars has risen above 70, the classic overbought threshold.",
    ),
    Rule(
        rule_id="bb_lower_touch",
        name="Price Below Lower Bollinger Band",
        expression="close < bb_lower(20,2)",
        description="Close has fallen below the lower 20-bar, 2-stddev Bollinger band -- a "
        "stretched move away from the mean, read either as oversold or as a breakdown.",
    ),
    Rule(
        rule_id="bb_upper_touch",
        name="Price Above Upper Bollinger Band",
        expression="close > bb_upper(20,2)",
        description="Close has risen above the upper 20-bar, 2-stddev Bollinger band -- a "
        "stretched move away from the mean, read either as overbought or as a breakout.",
    ),
    Rule(
        rule_id="bb_squeeze",
        name="Bollinger Band Squeeze",
        expression="bb_upper(20,2) - bb_lower(20,2) < close * 0.04",
        description="The band width has contracted to under 4% of price -- a volatility "
        "contraction that classically precedes an expansion in either direction.",
    ),
    Rule(
        rule_id="ema_golden_cross",
        name="EMA 50/200 Golden Cross",
        expression="ema(50) crosses_above ema(200)",
        description="The 50-bar EMA has just crossed above the 200-bar EMA -- a long-standing "
        "trend-following buy signal.",
    ),
    Rule(
        rule_id="ema_death_cross",
        name="EMA 50/200 Death Cross",
        expression="ema(50) crosses_below ema(200)",
        description="The 50-bar EMA has just crossed below the 200-bar EMA -- the trend-following "
        "mirror of the golden cross.",
    ),
    Rule(
        rule_id="macd_bullish_flip",
        name="MACD Histogram Turns Positive",
        expression="macd_hist(12,26,9) crosses_above 0",
        description="The MACD(12,26,9) histogram has just crossed above zero -- momentum turning "
        "from negative to positive.",
    ),
    Rule(
        rule_id="macd_bearish_flip",
        name="MACD Histogram Turns Negative",
        expression="macd_hist(12,26,9) crosses_below 0",
        description="The MACD(12,26,9) histogram has just crossed below zero -- momentum turning "
        "from positive to negative.",
    ),
    Rule(
        rule_id="price_above_sma200",
        name="Price Above 200-Bar SMA",
        expression="close > sma(200)",
        description="Close sits above the 200-bar simple moving average -- the standard long-term "
        "trend filter: above it, the instrument is in a technical uptrend.",
    ),
    Rule(
        rule_id="atr_range_expansion",
        name="Volatility Expansion (Range > 1.5x ATR)",
        expression="high - low > atr(14) * 1.5",
        description="Today's high-low range exceeds 1.5x the 14-bar Wilder ATR -- a single bar "
        "moving well outside its recent typical range, the signature of a breakout or a shock.",
    ),
    Rule(
        rule_id="vwap_reclaim",
        name="Price Reclaims Session VWAP",
        expression="close crosses_above vwap()",
        description="Close has just crossed back above the session-anchored VWAP -- intraday only, "
        "since a session anchor has no meaning on a bar that is itself a whole session.",
        intervals=_INTRADAY,
    ),
)

_BY_ID: dict[str, Rule] = {rule.rule_id: rule for rule in _CATALOG}


def catalog() -> list[Rule]:
    """Every catalogued rule, in the fixed display order above."""
    return list(_CATALOG)


def get(rule_id: str) -> Rule | None:
    """Look up one catalogued rule by its stable id. ``None`` if nothing is registered under it."""
    return _BY_ID.get(rule_id)
