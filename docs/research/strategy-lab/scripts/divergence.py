"""divergence stream: swing-pivot RSI/MACD divergence (note p.6, contents item 1b).

This is the one hypothesis the 2026-08-11 strategy study recorded as **untestable**
(`reports/momentum.md` section 8, `REPORT.md` claim #7): "price makes a lower low while
MACD/RSI makes a higher low" needs a lookback-extremum primitive the rule DSL did not have.
`app.indicators.swing` (tests: `tests/test_swing.py`, 37 tests) now provides it --
`swing_low(lookback)`/`swing_high(lookback)` (price at the last *confirmed* pivot, published
`lookback` bars after it forms, held forward) and `rsi_at_swing_low/high`, `macd_at_swing_low/high`
(the oscillator sampled at that same price-pivot bar). Textbook bullish divergence is now
`low < swing_low(5) and rsi(14) > rsi_at_swing_low(14,5)`.

**The whole point of this script is the control arms, not the divergence rules themselves.**
Divergence is a two-part conjunction (a price condition AND an oscillator condition). The prior
study's central lesson (REPORT.md claim #11, `confluence`) is that conjunctions must be decomposed:
a stacked rule can look good purely because its *components* are good, with the stacking itself
adding nothing. `new_low_alone` and `rsi_above_swing_alone` (and, symmetrically,
`macd_above_swing_alone`) are declared in the SAME family, at the SAME horizon, so their edges are
directly comparable to the conjunctions built from them.

**Power is anticipated, not discovered.** The earlier diagnostic (`momentum_divergence_diagnostic.py`,
naive pandas swing detection, no guard, no correction) found under one bullish event per symbol per
year -- ~25 events over ~25-34 years, fewer still once overlapping windows are discarded. That is
below `SMALL_SAMPLE_THRESHOLD = 30`. Three responses, all pre-declared here, before any primary result
is inspected:
  1. Horizon is 5 (not the earlier diagnostic's 10) for every idea in the primary family, to shrink
     window overlap and keep more triggers independent. One horizon per idea, declared up front --
     see the brief's discipline rule 2. A separate, clearly non-primary, descriptive comparison at
     horizon=10 is run afterward specifically to check the earlier diagnostic against the guarded
     operator (see `naive_vs_guarded_comparison` below) -- its numbers never feed a verdict.
  2. `pooled_replication_analysis` (declared here, run unconditionally, BEFORE primary results are
     read) pools the four core divergence ideas' independent trigger counts across the 13-symbol
     replication universe into one binomial test per idea, in its own separate BH ledger (m=4). This
     is not the brief's usual "replicate primary survivors" step -- it runs regardless of what the
     primary family shows, because it exists to buy power, not to confirm a screened result.
     Pooling across correlated ETPs is not free; see the report for what it does and does not buy.
  3. If neither buys enough power, that is reported plainly as "unresolvable at this sample size,"
     with the event count that would be needed, rather than argued past.

Run from docs/research/strategy-lab/:
    ../../../.venv/Scripts/python.exe scripts/divergence.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "lib")

from quantlab import Idea, run_family, horizon_sweep, write, bars_frame, guard, LAB  # noqa: E402

from app.backtest import events as events_mod  # noqa: E402
from app.backtest import scan as scan_mod  # noqa: E402
from app.backtest.models import SMALL_SAMPLE_THRESHOLD, STUDY_HORIZONS, Entry  # noqa: E402
from app.db.duck import Interval  # noqa: E402

SCREEN_ALPHA = 0.10  # matches quantlab.SCREEN_ALPHA / app.thesis.loop's own screen

PRIMARY = ["SPY", "QQQ", "IWM", "XLK", "XLV"]
REPLICATION = [
    "DIA", "SOXX", "IGV", "XLF", "XLE", "XLP", "XLU", "XLY", "XLI", "XLB", "XLC", "TLT", "GLD",
]

WINDOWS = [
    ("dotcom_2000_2002", "2000-01-01", "2002-12-31"),
    ("bull_2003_2007", "2003-01-01", "2007-10-31"),
    ("gfc_2007_2009", "2007-11-01", "2009-03-31"),
    ("qe_bull_2009_2019", "2009-04-01", "2019-12-31"),
    ("covid_2020_2021", "2020-01-01", "2021-12-31"),
    ("bear_2022", "2022-01-01", "2022-12-31"),
    ("recent_2023_now", "2023-01-01", None),
]

DIVERGENCE_HORIZON = 5   # the ONE horizon every primary idea below is judged at -- declared up front
NAIVE_COMPARE_HORIZON = 10  # matches the earlier diagnostic's horizon, used ONLY in the separate
                             # comparison block below, never in the primary family or its BH ledger

LB = 5
LB2 = 10

SWING_LOW = f"swing_low({LB})"
SWING_HIGH = f"swing_high({LB})"
SWING_LOW_LB2 = f"swing_low({LB2})"
RSI_AT_LOW = f"rsi_at_swing_low(14,{LB})"
RSI_AT_HIGH = f"rsi_at_swing_high(14,{LB})"
RSI_AT_LOW_LB2 = f"rsi_at_swing_low(14,{LB2})"
MACD_AT_LOW = f"macd_at_swing_low(12,26,9,{LB})"
MACD_AT_HIGH = f"macd_at_swing_high(12,26,9,{LB})"

# ---------------------------------------------------------------------------
# The declared family. 9 ideas x 5 primary symbols = 45 primary tests, one BH ledger.
# Mechanics (cap=10, stop=15%) match this study's convention for event-triggered (not persistent
# regime) entries -- the same shape momentum.py used for rsi_oversold_reversion. Bearish (direction=
# "down") ideas declare no exit/cap: this is a long-only engine, so a bearish signal cannot be traded
# through it, and this study will not report a "buy the bearish signal" backtest as if it meant
# something -- see the report for how these are read instead (as forward-return hypotheses only).
# ---------------------------------------------------------------------------

IDEAS = [
    # --- the two headline divergence claims (note p.6, contents item 1b) -------------------
    Idea(
        key="bullish_rsi_divergence",
        entry=f"low < {SWING_LOW} and rsi(14) > {RSI_AT_LOW}",
        exit=None,
        horizon=DIVERGENCE_HORIZON,
        direction="up",
        max_holding_bars=10,
        stop_loss_pct=0.15,
        rationale=(
            "note p.6 / contents item 1b, textbook bullish RSI divergence: price undercuts the last "
            "confirmed swing low (lookback=5) while RSI sits above where it read at that swing low. "
            "The exact hypothesis the 2026-08-11 study recorded as untestable (REPORT.md claim #7)."
        ),
        falsifies_if=(
            "the 5-bar forward hit rate does not exceed the same-bars baseline, OR does not exceed "
            "the new_low_alone / rsi_above_swing_alone control arms' edges"
        ),
        source="note p.6, contents item 1b, bullish RSI divergence",
    ),
    Idea(
        key="bullish_macd_divergence",
        entry=f"low < {SWING_LOW} and macd_macd(12,26,9) > {MACD_AT_LOW}",
        exit=None,
        horizon=DIVERGENCE_HORIZON,
        direction="up",
        max_holding_bars=10,
        stop_loss_pct=0.15,
        rationale=(
            "note p.6 verbatim: 'Divergences btw price & MACD => signal of possible trend change' -- "
            "the note's own claim names MACD specifically. Price undercuts the last confirmed swing "
            "low while the MACD line sits above where it read at that swing low."
        ),
        falsifies_if=(
            "the 5-bar forward hit rate does not exceed the same-bars baseline, OR does not exceed "
            "the new_low_alone / macd_above_swing_alone control arms' edges"
        ),
        source="note p.6, verbatim MACD divergence claim",
    ),
    # --- bearish mirrors, tested as direction=down forward-return hypotheses ---------------
    Idea(
        key="bearish_rsi_divergence",
        entry=f"high > {SWING_HIGH} and rsi(14) < {RSI_AT_HIGH}",
        exit=None,
        horizon=DIVERGENCE_HORIZON,
        direction="down",
        max_holding_bars=None,
        stop_loss_pct=None,
        rationale=(
            "Bearish mirror of bullish_rsi_divergence: price exceeds the last confirmed swing high "
            "while RSI sits below where it read at that swing high. Tested as a direction=down "
            "hypothesis on forward returns -- this long-only engine cannot short it, so no strategy "
            "backtest is run for this idea; see the report."
        ),
        falsifies_if=(
            "forward returns following the signal are not lower than the same-bars baseline "
            "(a positive or zero edge rejects the hypothesis as written)"
        ),
        source="note p.6, bearish mirror of the RSI divergence claim",
    ),
    Idea(
        key="bearish_macd_divergence",
        entry=f"high > {SWING_HIGH} and macd_macd(12,26,9) < {MACD_AT_HIGH}",
        exit=None,
        horizon=DIVERGENCE_HORIZON,
        direction="down",
        max_holding_bars=None,
        stop_loss_pct=None,
        rationale=(
            "Bearish mirror of bullish_macd_divergence. Tested as a direction=down hypothesis on "
            "forward returns only -- not tradeable through this long-only engine."
        ),
        falsifies_if=(
            "forward returns following the signal are not lower than the same-bars baseline"
        ),
        source="note p.6, bearish mirror of the MACD divergence claim",
    ),
    # --- control arms: the most important cells in this family -----------------------------
    Idea(
        key="new_low_alone",
        entry=f"low < {SWING_LOW}",
        exit=None,
        horizon=DIVERGENCE_HORIZON,
        direction="up",
        max_holding_bars=10,
        stop_loss_pct=0.15,
        rationale=(
            "Control 1/3: the price half of both bullish conjunctions, with the oscillator condition "
            "removed entirely. Price simply undercuts its last confirmed swing low. If this performs "
            "as well as bullish_rsi_divergence / bullish_macd_divergence, divergence adds nothing -- "
            "the whole concept is a story told about a new low."
        ),
        falsifies_if=(
            "bullish_rsi_divergence's and bullish_macd_divergence's edges do not exceed this "
            "control's edge, on the same symbol"
        ),
        source="decomposition control (brief-mandated), price condition alone",
    ),
    Idea(
        key="rsi_above_swing_alone",
        entry=f"rsi(14) > {RSI_AT_LOW}",
        exit=None,
        horizon=DIVERGENCE_HORIZON,
        direction="up",
        max_holding_bars=10,
        stop_loss_pct=0.15,
        rationale=(
            "Control 2/3: the RSI half of bullish_rsi_divergence, with the price condition (price "
            "must be making a new low) removed entirely."
        ),
        falsifies_if="bullish_rsi_divergence's edge does not exceed this control's edge, on the same symbol",
        source="decomposition control (brief-mandated), RSI condition alone",
    ),
    Idea(
        key="macd_above_swing_alone",
        entry=f"macd_macd(12,26,9) > {MACD_AT_LOW}",
        exit=None,
        horizon=DIVERGENCE_HORIZON,
        direction="up",
        max_holding_bars=10,
        stop_loss_pct=0.15,
        rationale=(
            "Control 3/3, symmetric to rsi_above_swing_alone: the MACD half of "
            "bullish_macd_divergence, with the price condition removed entirely."
        ),
        falsifies_if="bullish_macd_divergence's edge does not exceed this control's edge, on the same symbol",
        source="decomposition control, MACD condition alone",
    ),
    # --- lookback-sensitivity pair -----------------------------------------------------------
    Idea(
        key="bullish_rsi_divergence_lb10",
        entry=f"low < {SWING_LOW_LB2} and rsi(14) > {RSI_AT_LOW_LB2}",
        exit=None,
        horizon=DIVERGENCE_HORIZON,
        direction="up",
        max_holding_bars=10,
        stop_loss_pct=0.15,
        rationale=(
            "Lookback-sensitivity pair (brief-mandated): identical rule to bullish_rsi_divergence, "
            "lookback=10 instead of 5 -- fewer, more strongly confirmed pivots, published 5 bars "
            "later. Same horizon, same mechanics, so any change in verdict is attributable to the "
            "lookback parameter alone."
        ),
        falsifies_if=(
            "edge sign or verdict at lookback=10 does not match bullish_rsi_divergence's at "
            "lookback=5 -- a flip on an arbitrary parameter choice is itself the finding"
        ),
        source="brief-mandated lookback-sensitivity pair",
    ),
    # --- optional confluence arm --------------------------------------------------------------
    Idea(
        key="bullish_rsi_divergence_trend_gated",
        entry=f"low < {SWING_LOW} and rsi(14) > {RSI_AT_LOW} and close > sma(200)",
        exit=None,
        horizon=DIVERGENCE_HORIZON,
        direction="up",
        max_holding_bars=10,
        stop_loss_pct=0.15,
        rationale=(
            "Optional confluence arm: bullish RSI divergence gated by the 200-day trend filter used "
            "throughout this study (note pp. 2, 4, 6, 8, 9). Given the prior study's confluence "
            "finding (REPORT.md #11 -- stacking reliably shrinks sample, its hit-rate effect does "
            "not), this arm is expected to cost sample size predictably and help unpredictably."
        ),
        falsifies_if="edge does not exceed bullish_rsi_divergence's ungated edge on the same symbol",
        source="optional confluence arm, per assignment budget",
    ),
]

assert len(IDEAS) == 9, f"expected 9 declared ideas, got {len(IDEAS)}"

CORE_DIVERGENCE_KEYS = [
    "bullish_rsi_divergence",
    "bullish_macd_divergence",
    "bearish_rsi_divergence",
    "bearish_macd_divergence",
]


# ---------------------------------------------------------------------------
# Pre-declared pooled analysis across the replication universe (13 symbols).
# Declared and coded BEFORE the primary family below is run or inspected. Pools the four core
# divergence ideas' independent triggers across all 13 replication symbols into ONE binomial test
# per idea -- a separate BH ledger, m=4, never folded into the 45-cell primary family. This buys
# events, not independence: the 13 symbols are not 13 independent markets (see the report), so this
# result is reported with that caveat attached everywhere it is used, never as "n=13x the power."
# ---------------------------------------------------------------------------


def _local_verdict(edge, q, n_indep, direction):
    """Mirrors quantlab._verdict exactly (that function is private to quantlab, not imported) --
    direction checked before significance, small-sample floor before the BH screen."""
    if edge is None or q is None:
        return "untestable"
    wrong_way = (direction == "up" and edge < 0) or (direction == "down" and edge > 0)
    if wrong_way:
        return "rejected"
    if n_indep < SMALL_SAMPLE_THRESHOLD:
        return "underpowered"
    return "survived" if q <= SCREEN_ALPHA else "inconclusive"


def pooled_replication_analysis(ideas, symbols, *, horizon):
    """Pool independent-trigger counts for each idea across `symbols` into one binomial cell.

    Per symbol: pull `HorizonStats` at `horizon` via `events_mod.event_study` directly (not through
    `run_family`, which is per-symbol by design). `successes = round(hit_rate * n_indep)` per symbol
    (the same app.thesis.loop convention `quantlab._p_value` uses), summed across symbols; pooled
    baseline is the n_indep-weighted average of each symbol's own baseline hit rate. One binomial
    test per idea against that pooled baseline, then one BH ledger across the `len(ideas)` idea cells.
    """
    cells = []
    per_idea_detail = {}
    for idea in ideas:
        symbol_rows = []
        pooled_successes = 0
        pooled_trials = 0
        baseline_weighted = 0.0
        all_guards_passed = True
        for sym in symbols:
            try:
                bars = bars_frame(sym)
            except Exception as exc:
                symbol_rows.append({"symbol": sym, "error": f"{type(exc).__name__}: {exc}"})
                continue
            g = guard(idea.entry, bars)
            if not g["passed"]:
                all_guards_passed = False
            arms, _ = events_mod.event_study(
                bars, [idea.entry], interval=Interval.DAY, horizons=(horizon,), entry=Entry.NEXT_OPEN
            )
            st = arms[0].stats[0]
            n_indep = st.independent_sample_size
            hit = st.hit_rate
            base = st.baseline_hit_rate
            row = {
                "symbol": sym,
                "guard_status": g["status"],
                "triggers": arms[0].triggers,
                "n_raw": st.sample_size,
                "n_independent": n_indep,
                "hit_rate": hit,
                "baseline_hit_rate": base,
                "median_forward": st.distribution.median if st.distribution else None,
            }
            symbol_rows.append(row)
            if n_indep > 0 and hit is not None and base is not None:
                succ = int(round(hit * n_indep))
                succ = max(0, min(succ, n_indep))
                pooled_successes += succ
                pooled_trials += n_indep
                baseline_weighted += base * n_indep

        pooled_baseline = (baseline_weighted / pooled_trials) if pooled_trials > 0 else None
        pooled_hit = (pooled_successes / pooled_trials) if pooled_trials > 0 else None
        edge = (
            None if pooled_hit is None or pooled_baseline is None else pooled_hit - pooled_baseline
        )
        p = (
            scan_mod.binomial_p_value(pooled_successes, pooled_trials, pooled_baseline)
            if pooled_trials > 0 and pooled_baseline is not None
            else None
        )
        cell = {
            "idea": idea.key,
            "horizon": horizon,
            "direction": idea.direction,
            "n_symbols": len(symbols),
            "pooled_successes": pooled_successes,
            "pooled_n_independent": pooled_trials,
            "pooled_hit_rate": pooled_hit,
            "pooled_baseline_hit_rate": pooled_baseline,
            "edge": edge,
            "p_value": p,
            "all_guards_passed": all_guards_passed,
        }
        cells.append(cell)
        per_idea_detail[idea.key] = symbol_rows

    q_values = scan_mod.benjamini_hochberg([c["p_value"] for c in cells])
    for cell, q in zip(cells, q_values, strict=True):
        cell["q_value"] = q
        idea = next(i for i in ideas if i.key == cell["idea"])
        cell["verdict"] = _local_verdict(cell["edge"], q, cell["pooled_n_independent"], idea.direction)

    return {
        "family": "divergence-pooled-replication",
        "pre_declared": True,
        "note": (
            "Pools independent triggers across the 13-symbol replication universe into one binomial "
            "cell per idea, separate BH ledger (m=4). Buys event count, not independence: the 13 "
            "symbols overlap heavily in calendar time and several are correlated sector/factor "
            "exposures, so this is closer to a handful of independent looks than to 13. See the "
            "report for what this pooling does and does not establish."
        ),
        "symbols_declared": list(symbols),
        "ideas_declared": [i.key for i in ideas],
        "screen_alpha": SCREEN_ALPHA,
        "small_sample_threshold": SMALL_SAMPLE_THRESHOLD,
        "cells": cells,
        "per_idea_detail": per_idea_detail,
    }


# ---------------------------------------------------------------------------
# Descriptive comparison: the guarded operator vs. the earlier naive diagnostic
# (momentum_divergence_diagnostic.py), both at horizon=10, both on PRIMARY. No p-value, no
# correction, not part of any BH ledger -- exists only to check whether the earlier diagnostic's
# naive pandas swing-detection numbers hold up under the real, guarded, publication-lagged operator.
# ---------------------------------------------------------------------------

NAIVE_COMPARE_IDEAS = {
    "bullish_rsi_divergence": f"low < {SWING_LOW} and rsi(14) > {RSI_AT_LOW}",
    "bullish_macd_divergence": f"low < {SWING_LOW} and macd_macd(12,26,9) > {MACD_AT_LOW}",
    "bearish_rsi_divergence": f"high > {SWING_HIGH} and rsi(14) < {RSI_AT_HIGH}",
    "bearish_macd_divergence": f"high > {SWING_HIGH} and macd_macd(12,26,9) < {MACD_AT_HIGH}",
}


def naive_vs_guarded_comparison(symbols, *, horizon):
    result = {}
    for key, expr in NAIVE_COMPARE_IDEAS.items():
        by_symbol = {}
        for sym in symbols:
            bars = bars_frame(sym)
            arms, _ = events_mod.event_study(
                bars, [expr], interval=Interval.DAY, horizons=(horizon,), entry=Entry.NEXT_OPEN
            )
            st = arms[0].stats[0]
            years = len(bars) / 252.0
            by_symbol[sym] = {
                "expression": expr,
                "triggers": arms[0].triggers,
                "triggers_per_year": arms[0].triggers / years if years > 0 else None,
                "n_independent": st.independent_sample_size,
                "hit_rate": st.hit_rate,
                "baseline_hit_rate": st.baseline_hit_rate,
                "mean_forward_return": st.distribution.mean if st.distribution else None,
                "median_forward_return": st.distribution.median if st.distribution else None,
                "baseline_mean_forward_return": (
                    st.baseline_distribution.mean if st.baseline_distribution else None
                ),
            }
        result[key] = by_symbol
    return {
        "descriptive_only": True,
        "guarded_rule_engine": True,
        "p_value": None,
        "horizon": horizon,
        "note": (
            f"Same guarded swing operator as the primary family, run at horizon={horizon} to match "
            "momentum_divergence_diagnostic.py's naive-pandas comparison point exactly. This uses "
            "app.backtest.events.event_study (the same guarded engine as the primary family) so "
            "every number here passed the lookahead guard -- it differs from the primary family only "
            "in horizon (10 here vs 5 there) and in NOT being part of any BH ledger: it exists solely "
            "to check the earlier diagnostic's naive numbers against the real operator, not to screen "
            "a new hypothesis."
        ),
        "by_idea": result,
    }


# ---------------------------------------------------------------------------
# Event frequency and spacing, per symbol -- how often the core divergence rules actually fire and
# whether firings cluster in particular regimes.
# ---------------------------------------------------------------------------


def event_spacing(symbols, ideas_exprs, *, horizon):
    out = {}
    for key, expr in ideas_exprs.items():
        by_symbol = {}
        for sym in symbols:
            bars = bars_frame(sym)
            arms, _ = events_mod.event_study(
                bars, [expr], interval=Interval.DAY, horizons=(horizon,), entry=Entry.NEXT_OPEN
            )
            arm = arms[0]
            dates = arm.trigger_dates
            years_count: dict[str, int] = {}
            for d in dates:
                y = str(d.year)
                years_count[y] = years_count.get(y, 0) + 1
            gaps = [
                (dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)
            ] if len(dates) > 1 else []
            total_years = len(bars) / 252.0
            by_symbol[sym] = {
                "raw_triggers": arm.triggers,
                "triggers_per_year": arm.triggers / total_years if total_years > 0 else None,
                "first_trigger": str(dates[0]) if dates else None,
                "last_trigger": str(dates[-1]) if dates else None,
                "mean_gap_calendar_days": (sum(gaps) / len(gaps)) if gaps else None,
                "min_gap_calendar_days": min(gaps) if gaps else None,
                "max_gap_calendar_days": max(gaps) if gaps else None,
                "triggers_by_calendar_year": years_count,
            }
        out[key] = by_symbol
    return {
        "descriptive_only": True,
        "note": "Raw (overlapping-window) trigger counts and calendar spacing, not the independent "
                "subset used for significance -- this block answers 'how often does this actually "
                "fire and does it cluster', not 'how much independent evidence is there'.",
        "horizon": horizon,
        "by_idea": out,
    }


if __name__ == "__main__":
    print(f"=== divergence primary family: {len(IDEAS)} ideas x {len(PRIMARY)} symbols "
          f"= {len(IDEAS) * len(PRIMARY)} primary tests ===")
    primary = run_family(IDEAS, PRIMARY, family="divergence", windows=WINDOWS)
    write(primary, "divergence_primary")

    survivors = sorted({c["idea"] for c in primary["cells"] if c["verdict"] == "survived"})
    print(f"\nPrimary survivors (idea keys): {survivors or 'NONE'}")

    print("\n=== divergence exploratory horizon sweep (separate BH ledger, descriptive only) ===")
    entry_exprs = sorted({idea.entry for idea in IDEAS})
    sweep = horizon_sweep(entry_exprs, PRIMARY, family="divergence-sweep", horizons=STUDY_HORIZONS)
    write(sweep, "divergence_horizon_sweep")

    print("\n=== divergence pre-declared pooled replication analysis (4 core ideas x 13 symbols, "
          "own BH ledger) ===")
    core_ideas = [i for i in IDEAS if i.key in CORE_DIVERGENCE_KEYS]
    pooled = pooled_replication_analysis(core_ideas, REPLICATION, horizon=DIVERGENCE_HORIZON)
    write(pooled, "divergence_pooled_replication")
    for c in pooled["cells"]:
        edge_str = f"{c['edge']:+.4f}" if c["edge"] is not None else "n/a"
        q_str = f"{c['q_value']:.4f}" if c["q_value"] is not None else "n/a"
        print(f"  {c['idea']:<26} pooled_n_indep={c['pooled_n_independent']:<5} "
              f"edge={edge_str} q={q_str} verdict={c['verdict']}")

    print(f"\n=== naive (momentum stream) vs guarded operator, horizon={NAIVE_COMPARE_HORIZON}, "
          "descriptive only ===")
    naive_compare = naive_vs_guarded_comparison(PRIMARY, horizon=NAIVE_COMPARE_HORIZON)
    write(naive_compare, "divergence_vs_naive_diagnostic")

    print("\n=== event frequency and spacing, primary universe ===")
    spacing = event_spacing(PRIMARY, NAIVE_COMPARE_IDEAS, horizon=DIVERGENCE_HORIZON)
    write(spacing, "divergence_event_spacing")

    if survivors:
        surv_ideas = [i for i in IDEAS if i.key in survivors]
        print(f"\n=== divergence replication (primary survivors only): {len(surv_ideas)} idea(s) x "
              f"{len(REPLICATION)} replication symbols "
              f"= {len(surv_ideas) * len(REPLICATION)} replication tests ===")
        repl = run_family(surv_ideas, REPLICATION, family="divergence-replication", windows=WINDOWS)
        write(repl, "divergence_replication")
    else:
        print("\nNo primary survivors -- standard survivor-replication step not run (brief: "
              "replication runs only for ideas that survived the primary family). The pre-declared "
              "pooled analysis above is separate from this step and was run regardless.")

    print("\n=== divergence script complete ===")
