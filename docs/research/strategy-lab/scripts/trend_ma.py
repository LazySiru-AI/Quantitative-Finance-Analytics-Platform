"""trend-ma stream: encode and test the note's MA/EMA systematic framework (note pp. 2-4, 9).

Run from docs/research/strategy-lab/:
    ../../../.venv/Scripts/python.exe scripts/trend_ma.py

Declares the full 9-idea family up front (see IDEAS below), runs it once across the primary
5-symbol universe (45 primary tests, one BH ledger), then a separate exploratory horizon sweep,
then -- only for whatever survives the primary family -- a replication run on the 13-symbol
replication universe with its own separate BH ledger. Nothing is re-run after inspecting results;
if the family needed to grow, this file would say so and the family size would change.
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
        key="ideal_entry_verbatim",
        entry="ema(20) > sma(50) and sma(50) > ema(10) and ema(10) > sma(200)",
        exit="ema(5) crosses_below ema(20)",
        horizon=20,
        direction="up",
        rationale=(
            "note p.4 'Ideal Entry setup', encoded EXACTLY as written: "
            "'20EMA > 50SMA > 10EMA > 200MA'. This ordering is internally odd (10EMA sits below "
            "50SMA while the setup is described as a 'strong intermediate trend'); tested verbatim "
            "on purpose, see stacked_alignment_conventional for the alternative reading. Exit uses "
            "the note's own timing signal, '5EMA crossing 20EMA', in its bearish direction."
        ),
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.4 'Ideal Entry setup' (verbatim ordering)",
    ),
    Idea(
        key="stacked_alignment_conventional",
        entry="ema(10) > ema(20) and ema(20) > sma(50) and sma(50) > sma(200)",
        exit="ema(5) crosses_below ema(20)",
        horizon=20,
        direction="up",
        rationale=(
            "The conventional 'stacked moving averages' reading of the same note passage: fastest "
            "on top, slowest on bottom (ema(10) > ema(20) > sma(50) > sma(200)), i.e. what most "
            "technical-analysis literature means by 'aligned uptrend'. Tested as a separate idea "
            "from ideal_entry_verbatim so the data can say which reading it prefers."
        ),
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.4 'Ideal Entry setup' (conventional stacked-alignment reading)",
    ),
    Idea(
        key="stacked_alignment_no_gate",
        entry="ema(10) > ema(20) and ema(20) > sma(50)",
        exit="ema(5) crosses_below ema(20)",
        horizon=20,
        direction="up",
        rationale=(
            "Identical to stacked_alignment_conventional with the 'sma(50) > sma(200)' regime gate "
            "removed -- everything else (entry structure, exit, horizon, direction) held fixed. "
            "Pairs with stacked_alignment_conventional to isolate the marginal contribution of the "
            "200-day regime gate: same idea, gate on vs gate off."
        ),
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="regime-gate marginal-contribution probe, paired with stacked_alignment_conventional",
    ),
    Idea(
        key="golden_cross_sma",
        entry="sma(50) crosses_above sma(200)",
        exit="sma(50) crosses_below sma(200)",
        horizon=60,
        direction="up",
        rationale=(
            "note p.4 crossover table: '50SMA x 200SMA -- golden/dead cross, long-term'. Horizon "
            "60 is chosen to match the prior study's trend_following idea (ema(50) x ema(200), also "
            "h=60) for direct comparability -- the prior study used EMAs; the note specifies SMAs. "
            "That difference is itself reported."
        ),
        falsifies_if="60-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.4 crossover table, '50SMA x 200SMA golden/dead cross'",
    ),
    Idea(
        key="intermediate_cross_ema20_sma50",
        entry="ema(20) crosses_above sma(50)",
        exit="ema(20) crosses_below sma(50)",
        horizon=20,
        direction="up",
        rationale=(
            "note p.4 crossover table: '20EMA x 50SMA -- intermediate trend'. Also the MA-crossing-"
            "MA half of the timing-vs-trend-confirmation probe (paired with price_cross_sma50 below, "
            "same underlying level (50 SMA), same horizon)."
        ),
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.4 crossover table, '20EMA x 50SMA intermediate trend'",
    ),
    Idea(
        key="price_cross_sma50",
        entry="close crosses_above sma(50)",
        exit="close crosses_below sma(50)",
        horizon=20,
        direction="up",
        rationale=(
            "note p.3: 'price crossing an MA' is described as a timing signal, distinct from 'MA "
            "crossing MA' as a trend-confirmation signal. This is the price-crossing-the-level half "
            "of that distinction, using the same level (50 SMA) and horizon as "
            "intermediate_cross_ema20_sma50 so the two are directly comparable."
        ),
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.3, 'price crossing MA' vs 'MA crossing MA' distinction",
    ),
    Idea(
        key="short_term_cross_10ema_20sma",
        entry="ema(10) crosses_above sma(20)",
        exit="ema(10) crosses_below sma(20)",
        horizon=10,
        direction="up",
        rationale=(
            "note p.4 crossover table: '10EMA x 20MA -- short-term trend strengthening'. Shorter "
            "horizon (10) than the intermediate/long crossovers, matching the note's own "
            "'short-term' framing."
        ),
        falsifies_if="10-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.4 crossover table, '10EMA x 20MA short-term trend strengthening'",
    ),
    Idea(
        key="ma_strategy_page",
        entry="close > sma(200) and close > sma(120) and sma(5) crosses_above sma(20)",
        exit="close >= bb_upper(20,2) or sma(5) crosses_below sma(20)",
        horizon=20,
        direction="up",
        rationale=(
            "note p.9 'MA Strategy' page: entry = long-term MA120/200 direction aligned with price "
            "location (encoded as price above both the 120 and 200 SMA, since MA slope is not "
            "expressible in this DSL) plus a MA5-MA20 crossover in the long-term direction; exit = "
            "BB(20,2) band touch OR a MA5-MA8/20 crossover (encoded as MA5 x MA20, since two "
            "independent fast MAs (8 and 20) both mapping to 'the fast leg' is ambiguous -- 20 was "
            "chosen to match the entry leg)."
        ),
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.9 'MA Strategy' page",
    ),
    Idea(
        key="regime_filter_standalone",
        entry="close > sma(200)",
        exit="close < sma(200)",
        horizon=20,
        direction="up",
        rationale=(
            "note p.2: 'Trade in a rising market' as a standalone regime gate, with no other "
            "condition attached. Same expression as the prior study's momentum_persistence, but run "
            "here on a different symbol universe (SPY/QQQ/IWM/XLK/XLV vs the prior study's "
            "QQQ/SOXX/IGV/DRAM) and reported as this stream's own regime-gate baseline, not a repeat "
            "of the prior study's finding."
        ),
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.2 'Trade in a rising market'",
    ),
]

assert len(IDEAS) == 9, f"expected 9 declared ideas, got {len(IDEAS)}"

if __name__ == "__main__":
    print(f"=== trend-ma primary family: {len(IDEAS)} ideas x {len(PRIMARY)} symbols "
          f"= {len(IDEAS) * len(PRIMARY)} primary tests ===")
    primary = run_family(IDEAS, PRIMARY, family="trend-ma", windows=WINDOWS)
    write(primary, "trend_ma_primary")

    survivors = sorted({c["idea"] for c in primary["cells"] if c["verdict"] == "survived"})
    print(f"\nPrimary survivors (idea keys): {survivors or 'NONE'}")

    print("\n=== trend-ma exploratory horizon sweep (separate BH ledger, descriptive only) ===")
    entry_exprs = sorted({idea.entry for idea in IDEAS})
    sweep = horizon_sweep(entry_exprs, PRIMARY, family="trend-ma-sweep")
    write(sweep, "trend_ma_horizon_sweep")

    if survivors:
        surv_ideas = [i for i in IDEAS if i.key in survivors]
        print(f"\n=== trend-ma replication: {len(surv_ideas)} surviving idea(s) x "
              f"{len(REPLICATION)} replication symbols "
              f"= {len(surv_ideas) * len(REPLICATION)} replication tests ===")
        repl = run_family(surv_ideas, REPLICATION, family="trend-ma-replication", windows=WINDOWS)
        write(repl, "trend_ma_replication")
    else:
        print("\nNo primary survivors -- replication universe not run (brief: replication runs "
              "only for ideas that survived the primary family).")

    print("\n=== trend-ma script complete ===")
