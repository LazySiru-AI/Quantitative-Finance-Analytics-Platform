"""mean-reversion stream: Bollinger Bands, z-score, and volatility regime (note pp. 2, 5, 9).

Run from docs/research/strategy-lab/:
    ../../../.venv/Scripts/python.exe scripts/mean_reversion.py

Declares the full 8-idea family up front (see IDEAS below), runs it once across the primary
5-symbol universe (40 primary tests, one BH ledger), then a separate exploratory horizon sweep,
then -- only for whatever survives the primary family -- a replication run on the 13-symbol
replication universe with its own separate BH ledger. Nothing is re-run after inspecting results.

Two derived expressions (brief section 4) are used throughout, both on the SAME text each time they
appear, so the entries below are copy-pasteable and re-parseable identically:

  Z_EXPR    z-score(20):    (close - bb_mid(20,2)) / ((bb_upper(20,2) - bb_mid(20,2)) / 2)
  BW20_EXPR BB bandwidth(20): (bb_upper(20,2) - bb_lower(20,2)) / bb_mid(20,2)

The DSL has no abs() and comparisons do not chain, so a symmetric "|z| in band" condition has to be
written as two "and"-ed one-sided comparisons. The note's z-score band and stop-out are themselves
two-sided (mean reversion on the way up from an oversold dip AND mean reversion on the way down from
an overbought spike); this family tests only the oversold / long-entry construction of each, matching
this study's long-only convention (every idea across every stream in this study uses direction="up").
The overbought/short mirror is not run -- see the report's "what this cannot express" section.
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

Z_EXPR = "(close - bb_mid(20,2)) / ((bb_upper(20,2) - bb_mid(20,2)) / 2)"
BW20_EXPR = "(bb_upper(20,2) - bb_lower(20,2)) / bb_mid(20,2)"

# ---------------------------------------------------------------------------
# The declared family. 8 ideas x 5 primary symbols = 40 primary tests, one BH ledger.
# ---------------------------------------------------------------------------

IDEAS = [
    # --- Q1 decomposition: the single most informative thing in this assignment -----------
    Idea(
        key="bb_lower_only",
        entry="close < bb_lower(20,2)",
        exit="close > bb_mid(20,2)",
        horizon=20,
        direction="up",
        max_holding_bars=40,
        rationale=(
            "Decomposition component 1/3 of the note's p.2 headline rule: the band-touch condition "
            "alone, with the 200MA regime gate removed. Exit is the mid-band (SMA20) touch, i.e. "
            "'reversion to the mean achieved' -- this doubles as the band-touch-as-exit test from "
            "note p.9, using the middle band as the (partial) reversion target."
        ),
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.2 headline rule, decomposed: band-touch component alone",
    ),
    Idea(
        key="sma200_only",
        entry="close > sma(200)",
        exit="close < sma(200)",
        horizon=20,
        direction="up",
        rationale=(
            "Decomposition component 2/3 of the note's p.2 headline rule: the 200MA regime gate "
            "alone, with the band-touch condition removed. Same expression as the trend-ma stream's "
            "regime_filter_standalone and the prior study's momentum_persistence, run here as this "
            "stream's own decomposition baseline, not claimed as a fresh replication."
        ),
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.2 headline rule, decomposed: 200MA gate alone",
    ),
    Idea(
        key="headline_conjunction",
        entry="close > sma(200) and close < bb_lower(20,2)",
        exit="close > bb_upper(20,2)",
        horizon=20,
        direction="up",
        max_holding_bars=40,
        rationale=(
            "Decomposition component 3/3, and the note's headline rule verbatim (p.2): "
            "'IF price > 200 MA AND price < lower BB THEN Buy'. This is the exact expression behind "
            "the smoke-test numbers this stream exists to reproduce and extend (SPY edge +0.134, "
            "n_indep=87, p=0.0075; QQQ edge +0.099, n_indep=63, p=0.153 -- both from a 2-test family, "
            "re-corrected here across the full 8x5 family). Exit uses the opposite (upper) band as "
            "the full mean-reversion target, the note p.9 band-touch-exit concept applied to the "
            "headline rule itself."
        ),
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.2, headline entry logic, verbatim",
    ),
    # --- z-score banded entry and the |z|>3 stop-out claim (note p.5) ----------------------
    Idea(
        key="zscore_oversold_band",
        entry=f"{Z_EXPR} < -0.5 and {Z_EXPR} > -2",
        exit="close > bb_mid(20,2)",
        horizon=20,
        direction="up",
        max_holding_bars=20,
        rationale=(
            "note p.5 z-score entry band, |0.5| < z < |2|, oversold/long construction: price is "
            "moderately below its 20-day mean (more than half a band-half-width, less than a full "
            "band-half-width) -- the note's 'stretched rubber band, likely to snap back' zone. Exit "
            "at the mid-band, i.e. the z=0 line."
        ),
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.5, z-score banded entry |0.5| < z < |2|",
    ),
    Idea(
        key="zscore_extreme_stopout",
        entry=f"{Z_EXPR} < -3",
        exit="close > bb_mid(20,2)",
        horizon=20,
        direction="up",
        max_holding_bars=20,
        rationale=(
            "note p.5's hard-stop reasoning, tested as an empirical claim rather than wired in as a "
            "position-management stop (the DSL's stop_loss_pct is a price-percentage field, not a "
            "z-score-conditioned one, so the literal 'exit the position if z exceeds 3' mechanism is "
            "not directly expressible -- see 'what this cannot express'). Same direction, exit, "
            "horizon and holding cap as zscore_oversold_band, differing only in how far below the "
            "mean the entry requires: if the note's reasoning holds (extreme deviation is trend, not "
            "a stretched rubber band), this entry's edge should be weaker than, not stronger than, "
            "the moderate band's."
        ),
        falsifies_if=(
            "extreme-deviation (z<-3) entries do not show a weaker 20-bar edge than the moderate "
            "band (zscore_oversold_band) -- if the edges are equal or the extreme entry is stronger, "
            "the note's stop-out reasoning is not supported"
        ),
        source="note p.5, hard stop at |z| > 3 ('large deviation means a strong trend, not a stretched rubber band')",
    ),
    # --- BB bandwidth as a regime detector (note p.5) --------------------------------------
    Idea(
        key="bb_bandwidth_compression",
        entry=f"{BW20_EXPR} < 0.05",
        horizon=20,
        direction="up",
        max_holding_bars=20,
        rationale=(
            "note p.5: bandwidth < 5% => compression / consolidating regime, i.e. a breakout is "
            "coming. Uses the note's own 5% threshold on (upper-lower)/mid -- NOT the prior study's "
            "volatility_contraction template, which used (upper-lower) < close*0.04, a 4% threshold "
            "on a DIFFERENT denominator (close, not the mid band). That discrepancy is reported, not "
            "silently reconciled. The note's claim is direction-agnostic (a breakout can go either "
            "way); the harness's hit-rate statistic is not, so this idea tests only the directional "
            "half of the claim and the report reads median forward return alongside hit rate to keep "
            "that limitation visible rather than overclaiming a directional finding."
        ),
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.5, BB bandwidth < 5% => compression/consolidating",
    ),
    Idea(
        key="bb_bandwidth_expansion",
        entry=f"{BW20_EXPR} > 0.15",
        horizon=20,
        direction="up",
        max_holding_bars=20,
        rationale=(
            "note p.5: bandwidth > 15% => high-volatility trending regime. Same directional-statistic "
            "caveat as bb_bandwidth_compression: 'trending' does not itself specify up or down, so "
            "this tests whether wide-band conditions on this long-biased universe skew up, alongside "
            "the strategy mechanics' own volatility metric."
        ),
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.5, BB bandwidth > 15% => high-volatility trending regime",
    ),
    # --- BOLL(50,2), named alongside BOLL(20,2) on note p.5 --------------------------------
    Idea(
        key="boll50_band_touch",
        entry="close < bb_lower(50,2)",
        exit="close > bb_mid(50,2)",
        horizon=20,
        direction="up",
        max_holding_bars=40,
        rationale=(
            "note p.5 names both BOLL(20,2) and BOLL(50,2). 50-period analogue of bb_lower_only "
            "(same exit/horizon/direction/holding-cap shape) so the two are directly comparable: does "
            "the band-touch effect, such as it is, depend on lookback length?"
        ),
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.5, 'BOLL(20,2)' and 'BOLL(50,2)' both named",
    ),
]

assert len(IDEAS) == 8, f"expected 8 declared ideas, got {len(IDEAS)}"

if __name__ == "__main__":
    print(f"=== mean-reversion primary family: {len(IDEAS)} ideas x {len(PRIMARY)} symbols "
          f"= {len(IDEAS) * len(PRIMARY)} primary tests ===")
    primary = run_family(IDEAS, PRIMARY, family="mean-reversion", windows=WINDOWS)
    write(primary, "mean_reversion_primary")

    survivors = sorted({c["idea"] for c in primary["cells"] if c["verdict"] == "survived"})
    print(f"\nPrimary survivors (idea keys): {survivors or 'NONE'}")

    print("\n=== mean-reversion exploratory horizon sweep (separate BH ledger, descriptive only) ===")
    entry_exprs = sorted({idea.entry for idea in IDEAS})
    sweep = horizon_sweep(entry_exprs, PRIMARY, family="mean-reversion-sweep")
    write(sweep, "mean_reversion_horizon_sweep")

    if survivors:
        surv_ideas = [i for i in IDEAS if i.key in survivors]
        print(f"\n=== mean-reversion replication: {len(surv_ideas)} surviving idea(s) x "
              f"{len(REPLICATION)} replication symbols "
              f"= {len(surv_ideas) * len(REPLICATION)} replication tests ===")
        repl = run_family(surv_ideas, REPLICATION, family="mean-reversion-replication", windows=WINDOWS)
        write(repl, "mean_reversion_replication")
    else:
        print("\nNo primary survivors -- replication universe not run (brief: replication runs "
              "only for ideas that survived the primary family).")

    print("\n=== mean-reversion script complete ===")
