"""momentum stream: MACD, RSI, and confluence (note pp.2, 6-9).

Run from docs/research/strategy-lab/:
    ../../../.venv/Scripts/python.exe scripts/momentum.py

Declares the full 9-idea family up front (see IDEAS below), runs it once across the primary
5-symbol universe (45 primary tests, one BH ledger), then a separate exploratory horizon sweep,
then -- only for whatever survives the primary family -- a replication run on the 13-symbol
replication universe with its own separate BH ledger.

Two MACD ideas (macd_signal_cross, macd_zero_cross) encode the note's two distinct MACD entry
concepts (p.6) as separate tests. ma_crossover_matched is the matched comparator for the note's own
claim, verbatim: "MACD crossover is faster but more falsy than MA crossover" (p.6) -- matched on
EMA(10)/EMA(20) rather than SMA(5)/SMA(20) because MACD itself is built from two EMAs (12,26); an
EMA-vs-EMA crossover holds the smoothing family constant. rsi_oversold_reversion and rsi_regime_gate
encode the note's two contradictory readings of the same indicator (p.2, p.7): RSI<30 as a
mean-reversion buy vs. high RSI as a strong-trend regime worth joining. confluence_macd_trend and
confluence_rsi_trend are the two stacked-condition ideas (p.6, p.8, p.9); trend_gate_sma200 and
trend_gate_ema20_sma50 are their trend-gate components tested alone, at the identical horizon, so the
report can show whether stacking helped or just shrank the sample.

Bullish/bearish divergence (note p.6, contents item 1b) is not expressible in the DSL -- no
lookback-extremum operator -- and is NOT part of this declared family. See
scripts/momentum_divergence_diagnostic.py for a separate, explicitly descriptive, non-DSL probe.
"""

import sys

sys.path.insert(0, "lib")

from quantlab import Idea, run_family, horizon_sweep, write  # noqa: E402

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
# The declared family. 9 ideas x 5 primary symbols = 45 primary tests, one BH ledger.
# ---------------------------------------------------------------------------

IDEAS = [
    Idea(
        key="macd_signal_cross",
        entry="macd_macd(12,26,9) crosses_above macd_signal(12,26,9)",
        exit="macd_macd(12,26,9) crosses_below macd_signal(12,26,9)",
        horizon=10,
        direction="up",
        rationale=(
            "note p.6: MACD line crossing above its own signal line (EMA9 of the MACD line) is the "
            "canonical MACD entry trigger. Tested as its own idea, distinct from the zero-line cross "
            "-- the note conflates the two, they are not the same signal."
        ),
        falsifies_if="10-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.6 MACD signal-line crossover",
    ),
    Idea(
        key="macd_zero_cross",
        entry="macd_macd(12,26,9) crosses_above 0",
        exit="macd_macd(12,26,9) crosses_below 0",
        horizon=10,
        direction="up",
        rationale=(
            "note p.6: 'zero line = the momentum midpoint'. MACD crossing zero means EMA12 has just "
            "overtaken EMA26 outright -- a coarser, later trigger than the signal-line cross, tested "
            "separately at the identical horizon."
        ),
        falsifies_if="10-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.6 MACD zero-line cross",
    ),
    Idea(
        key="ma_crossover_matched",
        entry="ema(10) crosses_above ema(20)",
        exit="ema(10) crosses_below ema(20)",
        horizon=10,
        direction="up",
        rationale=(
            "Matched comparator for the note's own claim (p.6, verbatim): 'MACD crossover is faster "
            "but more falsy than MA crossover.' Matched on EMA(10)/EMA(20) rather than SMA(5)/SMA(20) "
            "because MACD is itself built from two EMAs (12,26); holding the smoothing family "
            "constant isolates the actual mechanical difference this claim is about -- crossing two "
            "EMAs directly vs. crossing the EMA12-EMA26 difference against its own EMA9-smoothed "
            "signal line -- rather than also changing SMA-vs-EMA responsiveness at the same time."
        ),
        falsifies_if="10-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.6 'MACD crossover is faster but more falsy than MA crossover'",
    ),
    Idea(
        key="rsi_oversold_reversion",
        entry="rsi(14) < 30",
        exit="rsi(14) > 50",
        horizon=5,
        direction="up",
        max_holding_bars=10,
        stop_loss_pct=0.15,
        rationale=(
            "note p.7: RSI<30 read as the conventional oversold / mean-reversion buy signal. "
            "Mechanics (horizon, exit, cap, stop) are identical to the prior study's oversold_bounce "
            "template, so this stream's five-symbol result is directly comparable to the prior "
            "study's QQQ/SOXX/IGV result, where it was a net loser on SOXX and IGV."
        ),
        falsifies_if="5-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.7 RSI oversold/overbought reading",
    ),
    Idea(
        key="rsi_regime_gate",
        entry="rsi(14) crosses_above 60",
        exit="rsi(14) crosses_below 40",
        horizon=10,
        direction="up",
        rationale=(
            "note p.2: RSI framed as a 'trend strength regime' indicator rather than a reversion "
            "oscillator -- high RSI reads as confirmation of a strong trend worth joining, not "
            "exhaustion. Operationalized as a crossing event (entering a strong-momentum regime at "
            "60) rather than a level, at the same horizon and direction as rsi_oversold_reversion so "
            "the two opposite readings of the same indicator can be compared head to head."
        ),
        falsifies_if="10-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.2 RSI as trend-strength regime",
    ),
    Idea(
        key="trend_gate_sma200",
        entry="close > sma(200)",
        exit="close < sma(200)",
        horizon=10,
        direction="up",
        rationale=(
            "Component-alone test for confluence_macd_trend below: the 200-day trend gate on its "
            "own, same horizon, so any hit-rate change from stacking MACD on top of it is visible "
            "against this baseline rather than assumed."
        ),
        falsifies_if="10-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.2 'trade in a rising market'; decomposition component for confluence_macd_trend",
    ),
    Idea(
        key="confluence_macd_trend",
        entry="macd_macd(12,26,9) crosses_above macd_signal(12,26,9) and close > sma(200)",
        exit="macd_macd(12,26,9) crosses_below macd_signal(12,26,9)",
        horizon=10,
        direction="up",
        rationale=(
            "note p.6, p.8-9: stacked-condition 'confluence' entry -- a MACD signal-line cross fired "
            "only while price sits above its 200-day trend. Paired with macd_signal_cross (trigger "
            "alone) and trend_gate_sma200 (gate alone) at the identical horizon so the report can "
            "show the sample-size collapse from stacking alongside any hit-rate change."
        ),
        falsifies_if="10-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.6/p.8/p.9 'Confluence metric' / 'Golden Alignment'",
    ),
    Idea(
        key="trend_gate_ema20_sma50",
        entry="ema(20) > sma(50)",
        exit="ema(20) crosses_below sma(50)",
        horizon=10,
        direction="up",
        rationale=(
            "Component-alone test for confluence_rsi_trend below: the intermediate EMA20-over-SMA50 "
            "trend gate on its own, same horizon."
        ),
        falsifies_if="10-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.4 intermediate trend structure; decomposition component for confluence_rsi_trend",
    ),
    Idea(
        key="confluence_rsi_trend",
        entry="rsi(14) crosses_above 60 and ema(20) > sma(50)",
        exit="rsi(14) crosses_below 40",
        horizon=10,
        direction="up",
        rationale=(
            "note p.6, p.8-9: second confluence idea -- the RSI regime-gate trigger fired only while "
            "the intermediate trend structure (EMA20 above SMA50) is intact. Paired with "
            "rsi_regime_gate (trigger alone) and trend_gate_ema20_sma50 (gate alone) at the identical "
            "horizon."
        ),
        falsifies_if="10-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.6/p.8/p.9 'Confluence metric' / 'Golden Alignment', second instance",
    ),
]

assert len(IDEAS) == 9, f"expected 9 declared ideas, got {len(IDEAS)}"

if __name__ == "__main__":
    print(f"=== momentum primary family: {len(IDEAS)} ideas x {len(PRIMARY)} symbols "
          f"= {len(IDEAS) * len(PRIMARY)} primary tests ===")
    primary = run_family(IDEAS, PRIMARY, family="momentum", windows=WINDOWS)
    write(primary, "momentum_primary")

    survivors = sorted({c["idea"] for c in primary["cells"] if c["verdict"] == "survived"})
    print(f"\nPrimary survivors (idea keys): {survivors or 'NONE'}")

    print("\n=== momentum exploratory horizon sweep (separate BH ledger, descriptive only) ===")
    entry_exprs = sorted({idea.entry for idea in IDEAS})
    sweep = horizon_sweep(entry_exprs, PRIMARY, family="momentum-sweep")
    write(sweep, "momentum_horizon_sweep")

    if survivors:
        surv_ideas = [i for i in IDEAS if i.key in survivors]
        print(f"\n=== momentum replication: {len(surv_ideas)} surviving idea(s) x "
              f"{len(REPLICATION)} replication symbols "
              f"= {len(surv_ideas) * len(REPLICATION)} replication tests ===")
        repl = run_family(surv_ideas, REPLICATION, family="momentum-replication", windows=WINDOWS)
        write(repl, "momentum_replication")
    else:
        print("\nNo primary survivors -- replication universe not run (brief: replication runs "
              "only for ideas that survived the primary family).")

    print("\n=== momentum script complete ===")
