"""regime-risk stream: the DSL-expressible half of the risk/regime claims (note pp. 2, 7, 10, 11).

Run from docs/research/strategy-lab/:
    ../../../.venv/Scripts/python.exe scripts/regime_risk_dsl.py

**Why this family is deliberately small (4 ideas, not 9).** Most of this stream's assignment --
ATR position sizing, ATR stop calibration, seasonality, VIX/Fear&Greed conditioning -- is explicitly
*not* expressible in the rule DSL (no date operator, no join against a second symbol's frame, and
position sizing is out of scope of the backtest engine entirely; see strategy.py's docstring). What
*is* left for the DSL is the regime-filter claim itself (note p.2, "price > 200MA = positive
long-term trend") and its interaction with a risk-managed (stopped) entry.

**Coordination with trend-ma.** The trend-ma stream already declared and ran
`regime_filter_standalone` (`close > sma(200)` / exit `close < sma(200)`, horizon 20, direction up)
on this exact primary universe, in their own 9-idea/45-test family
(`data/trend_ma_primary.json`). Re-running the identical expression here would inflate this stream's
own family for a test that already exists with its own correctly-corrected q-value -- the note's
BRIEF explicitly asks this stream to "approach it from the regime side... rather than duplicating
their crossover tests." Their result is cited directly in `reports/regime-risk.md` and in
`scripts/regime_risk_regime_value.py`; it is not re-tested here.

What *is* new here, not covered by trend-ma:

1. `below_200ma_regime` -- the mirror image of their test: is forward-return behaviour actually worse
   (not just "not better") while price sits below the 200-day SMA? This is the direct converse of the
   note's claim, and trend-ma's family does not test it.
2. Three pullback ideas (`regime_filtered_pullback` / `unfiltered_pullback` /
   `unfavorable_regime_pullback`) that hold a risk-managed, stopped mean-reversion entry
   (`rsi(14) < 30` -> `rsi(14) > 50`, 15-bar cap, 10% stop) fixed and vary only the regime gate in
   front of it: no gate, gated to price > 200MA, gated to price < 200MA. This directly tests note p.2's
   "trade only when broader market context is favorable" as a *marginal* contribution to a
   risk-managed trade, which is the risk-framework question this stream owns -- not a MA-crossover
   question, which is trend-ma's.

Declared family: 4 ideas x 5 primary symbols = 20 primary tests, one BH ledger.
"""

import sys

sys.path.insert(0, "lib")

from quantlab import Idea, run_family, write  # noqa: E402

PRIMARY = ["SPY", "QQQ", "IWM", "XLK", "XLV"]
REPLICATION = [
    "DIA", "SOXX", "IGV", "XLF", "XLE", "XLP", "XLU", "XLY", "XLI", "XLB", "XLC", "TLT", "GLD",
]

WINDOWS = [
    ("dotcom_2000_2002", "2000-01-01", "2002-12-31"),
    ("bull_2003_2007", "2003-01-01", "2007-10-31"),
    ("qe_bull_2009_2019", "2009-04-01", "2019-12-31"),
    ("covid_2020_2021", "2020-01-01", "2021-12-31"),
    ("bear_2022", "2022-01-01", "2022-12-31"),
    ("recent_2023_now", "2023-01-01", None),
]

# ---------------------------------------------------------------------------
# The declared family. 4 ideas x 5 primary symbols = 20 primary tests, one BH ledger.
# Not a trading recommendation: every idea below is a statistical test of forward-return behaviour
# conditional on a state, using the engine's long-only mechanics as a measurement tool, per BRIEF.md
# section 7 ("nothing may frame an instrument as one to buy or sell").
# ---------------------------------------------------------------------------

IDEAS = [
    Idea(
        key="below_200ma_regime",
        entry="close < sma(200)",
        exit="close > sma(200)",
        horizon=20,
        direction="down",
        rationale=(
            "note p.2: 'price > 200MA = positive long term trend' implies the converse should be "
            "inferior. This is the direct mirror of trend-ma's regime_filter_standalone "
            "(close > sma(200)), not re-tested here -- see module docstring. direction='down' means "
            "the hypothesis under test is that the 20-bar forward hit rate is *below* the same-bars "
            "baseline while price sits under the 200-day SMA; an edge that runs positive is a "
            "rejection of that claim, not merely inconclusive."
        ),
        falsifies_if="20-bar forward hit rate below the 200-day SMA does not fall below the "
        "same-bars baseline",
        source="note p.2 'price > 200MA = positive long term trend' (converse)",
    ),
    Idea(
        key="regime_filtered_pullback",
        entry="close > sma(200) and rsi(14) < 30",
        exit="rsi(14) > 50",
        horizon=10,
        direction="up",
        max_holding_bars=15,
        stop_loss_pct=0.10,
        rationale=(
            "note p.2: 'trade only when broader market context is favorable', applied as a gate on a "
            "risk-managed entry (10% stop, 15-bar cap) rather than on a bare MA-alignment signal -- "
            "this is the risk-framework reading of the claim, not a crossover test. Paired with "
            "unfiltered_pullback (no gate) and unfavorable_regime_pullback (gate inverted) with every "
            "other parameter held fixed, so the marginal contribution of the regime gate on this class "
            "of trade can be read directly off the three edges."
        ),
        falsifies_if="10-bar forward hit rate does not exceed the same-bars baseline, or does not "
        "exceed unfiltered_pullback's edge",
        source="note p.2 'trade only when broader market context is favorable'",
    ),
    Idea(
        key="unfiltered_pullback",
        entry="rsi(14) < 30",
        exit="rsi(14) > 50",
        horizon=10,
        direction="up",
        max_holding_bars=15,
        stop_loss_pct=0.10,
        rationale=(
            "Identical to regime_filtered_pullback with the 'close > sma(200)' gate removed -- "
            "entry structure, exit, horizon, holding cap and stop all held fixed. The counterfactual "
            "that isolates whether the regime gate itself is doing work, not just whether "
            "rsi(14) < 30 mean-reversion works in general."
        ),
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="regime-gate marginal-contribution probe, paired with regime_filtered_pullback",
    ),
    Idea(
        key="unfavorable_regime_pullback",
        entry="close < sma(200) and rsi(14) < 30",
        exit="rsi(14) > 50",
        horizon=10,
        direction="up",
        max_holding_bars=15,
        stop_loss_pct=0.10,
        rationale=(
            "The trade the note's risk framework discourages: buying an oversold bounce while price "
            "is already below the 200-day trend filter -- 'catching a falling knife' in a context the "
            "note itself calls unfavorable. direction is still declared 'up' (this idea asks whether "
            "the trade is a positive-edge trade on its own terms, not whether it under- or "
            "out-performs); the comparison against regime_filtered_pullback's edge and mechanics "
            "(win rate, max drawdown, worst trade) is what actually answers 'does the regime filter "
            "prevent catastrophic loss', in the report."
        ),
        falsifies_if="10-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.2 risk framework: the trade explicitly discouraged by 'favorable context only'",
    ),
]

assert len(IDEAS) == 4, f"expected 4 declared ideas, got {len(IDEAS)}"

if __name__ == "__main__":
    print(f"=== regime-risk DSL primary family: {len(IDEAS)} ideas x {len(PRIMARY)} symbols "
          f"= {len(IDEAS) * len(PRIMARY)} primary tests ===")
    primary = run_family(IDEAS, PRIMARY, family="regime-risk-dsl", windows=WINDOWS)
    write(primary, "regime_risk_dsl_primary")

    survivors = sorted({c["idea"] for c in primary["cells"] if c["verdict"] == "survived"})
    print(f"\nPrimary survivors (idea keys): {survivors or 'NONE'}")

    if survivors:
        surv_ideas = [i for i in IDEAS if i.key in survivors]
        print(f"\n=== regime-risk replication: {len(surv_ideas)} surviving idea(s) x "
              f"{len(REPLICATION)} replication symbols "
              f"= {len(surv_ideas) * len(REPLICATION)} replication tests ===")
        repl = run_family(surv_ideas, REPLICATION, family="regime-risk-dsl-replication", windows=WINDOWS)
        write(repl, "regime_risk_dsl_replication")
    else:
        print("\nNo primary survivors -- replication universe not run (brief: replication runs "
              "only for ideas that survived the primary family).")

    print("\n=== regime_risk_dsl.py complete ===")
