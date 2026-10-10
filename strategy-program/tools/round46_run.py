"""Run and score round 46 (does two independent savings de-risking reads stack additively?), the
bespoke harness `ROUND-46-PLAN.md` section 8 specifies -- adapted from `round43_run.py` (itself
adapted from `round38_run.py`) because `strategy-program/tools/score.py` is hard-typed to
`app.tournament.models.AgentResult` and cannot score an `AllocationCard`.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round46_run.py
    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round46_run.py --smoke

What it does, and why each choice is the one the plan pre-registered:

* **No macro pin.** Every condition in this field is price-only (`close`/`sma` on SPY or AGG) --
  `INVDASH_MACRO_PIN` is never set, and no card here has a `macro(...)` term.
* **Runs every card through `app.tournament.allocation.run_allocation` with
  `app.paperdesk.desk._mandate(Purpose.SAVINGS)`** -- the live savings book's own mandate, identical
  to round 38's and round 43's discipline.
* **Judges on the 5y/10y rungs, reports the 3y rungs and the six bear supplements.** Same ladder round
  38 and round 43 used (`R5_LADDER_WINDOW_TAGS` + `R5_BEAR_WINDOW_TAGS`), so all three rounds' numbers
  sit side by side. `MIN_ELIGIBLE_R5_PER_HORIZON = 2` (`windows.py`) is the gate.
* **The benchmark is the 30/70 SPY/AGG blend, not SPY.** Recomputed per window via
  `app.paperdesk.benchmarks.price_blend`.
* **Ranks on drawdown and MAR margin vs the control, CAGR reported not ranked** -- the savings mandate
  is lowest-drawdown, least-return-accepted.
* **A separate table labels `b6m-2`/`b1y-1` "2022 (in-sample to the hypothesis)"** -- identical to
  round 43's hindsight discussion: the corpus's bond-stress claim was voiced with 2022 already known.
* **Five pairwise lines are this round's whole point.** On the RANK_TAGS rungs where the relevant
  cards both fired, per-rung, then median across rungs: `both - spy`, `both - agg`,
  `both - (spy + agg)` (the additivity test, plan section 5 P1: within +/-0.5pp means the two reads
  are independent), `both-gld - both` and `both-trim - both` (plan section 5 P4: a third rule earning
  its place on the stack, not merely adding cost).
* **The 21.2pp noise floor is inherited conservatism, not load-bearing here** -- identical caveat to
  round 38 and round 43.

Writes `data/rounds/r46-2026-09/analysis.json` and `data/rounds/r46-2026-09/ANALYSIS.md` (the printed
tables, as markdown) and prints the same tables to stdout. **Not investment advice.** Price-only bars;
AGG/GLD/BIL distributions are unmodelled, so every CAGR is understated and the drawdown column is the
trustworthy half.

Run as a plain script, not ``-m`` -- ``strategy-program`` is not a legal package name.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import statistics
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import windows as W  # noqa: E402  (path-based import, same precedent as round38_run.py / round43_run.py)

from app.config import get_settings  # noqa: E402
from app.paperdesk.benchmarks import REGISTRY, price_blend  # noqa: E402
from app.paperdesk.desk import _mandate as desk_mandate  # noqa: E402
from app.tournament.allocation import AllocationCard, run_allocation  # noqa: E402
from app.tournament.purposes import Purpose  # noqa: E402

CARDS_DIR = REPO / "data" / "rounds" / "r46-2026-09" / "cards"
CONTROL_ID = "r46-control"
SPY_ID = "r46-spy-derisk"
AGG_ID = "r46-agg-derisk"
BOTH_ID = "r46-both"
BOTH_GLD_ID = "r46-both-gld"
TRIM_ID = "r46-trim-high"
BOTH_TRIM_ID = "r46-both-trim"
TRADING_DAYS = 252
BENCHMARK_BLEND = "30-70-spy-agg"

#: The judged set (5y + 10y), the reported-but-not-ranked set (3y), and the bear supplements --
#: identical to round 38's and round 43's ladder, so all three rounds' numbers sit side by side.
RANK_TAGS = ("h10y-1", "h10y-2", "h5y-1", "h5y-2", "h5y-3")
REPORT_TAGS = ("h3y-1", "h3y-2", "h3y-3", "h3y-4")
BEAR_TAGS = ("b6m-1", "b6m-2", "b6m-3", "b1y-1", "b1y-2", "b1y-3")
ALL_TAGS = RANK_TAGS + REPORT_TAGS + BEAR_TAGS

#: The two bear windows that sit inside the 2021-2022 regime the corpus's bond-stress claim was voiced
#: after -- round 43's hindsight discussion, unchanged here. A margin appearing ONLY here is hindsight
#: confirming what was already known when the claim was made, not out-of-sample evidence.
HINDSIGHT_TAGS = ("b6m-2", "b1y-1")

#: One window short enough for `--smoke` to run in seconds -- `h1y-6` (2025-02-18 .. 2026-02-13),
#: identical to round 43's smoke tag.
SMOKE_TAG = "h1y-6"

#: How close to zero, in points of drawdown margin, `both - (spy + agg)` must sit for plan section 5's
#: P1 (independence) to hold, and how much a third rule must improve `both`'s own margin by for P4 to
#: hold. Both are the plan's own pre-registered thresholds, not derived from any outcome.
ADDITIVITY_TOLERANCE_PP = 0.5


def window_bounds(tag: str) -> tuple[dt.date, dt.date]:
    start, end, _desc = W.WINDOWS[tag]
    return start, end


def cagr_of(result: object, capital: float) -> float | None:
    sessions = getattr(result, "sessions", 0)
    ending = getattr(result, "ending_equity", None)
    if not sessions or ending is None:
        return None
    return (float(ending) / capital) ** (TRADING_DAYS / sessions) - 1


def run_card_windows(
    card: AllocationCard, settings, mandate, capital: float, tags: tuple[str, ...] = ALL_TAGS
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for tag in tags:
        start, end = window_bounds(tag)
        try:
            res = run_allocation(card, settings=settings, mandate=mandate, start=start, end=end)
        except Exception as exc:  # a leg without history, or a window too short to price
            out[tag] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
            continue
        trades = len(getattr(res, "trades", ()) or ())
        out[tag] = {
            "ok": True,
            "sessions": res.sessions,
            "cagr": cagr_of(res, capital),
            "max_drawdown": float(res.max_drawdown),
            "total_return": float(res.total_return),
            "volatility": float(res.volatility) if res.volatility is not None else None,
            "trades": trades,
        }
    return out


def mar(cagr: float | None, dd: float) -> float | None:
    if cagr is None or not dd:
        return None
    return cagr / abs(dd)


def median_or_none(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def _fired(treatment: dict, control: dict) -> bool:
    if not (treatment.get("ok") and control.get("ok")):
        return False
    return (
        treatment["trades"] != control["trades"]
        or abs(treatment["total_return"] - control["total_return"]) > 1e-9
    )


def _dd_margins_by_tag(
    aid: str, results: dict[str, dict[str, dict]], control: dict[str, dict], tags: tuple[str, ...] = RANK_TAGS
) -> dict[str, float]:
    """`{tag: drawdown_margin_pp}` for every tag in `tags` on which `aid`'s condition fired."""
    out: dict[str, float] = {}
    for tag in tags:
        r, c = results[aid][tag], control[tag]
        if not _fired(r, c):
            continue
        out[tag] = (r["max_drawdown"] - c["max_drawdown"]) * 100
    return out


def _pairwise_median(
    left: dict[str, float], right: dict[str, float], combine
) -> tuple[float | None, int]:
    """`combine(left[tag], right[tag])` over tags common to both, median + count of common tags."""
    common = sorted(set(left) & set(right))
    if not common:
        return None, 0
    values = [combine(left[t], right[t]) for t in common]
    return median_or_none(values), len(common)


def smoke(card_id: str = BOTH_ID) -> int:
    """Run ONE card over `SMOKE_TAG` to prove the frozen field is executable. Not a measurement."""
    settings = get_settings()
    mandate = desk_mandate(Purpose.SAVINGS)
    card = AllocationCard.model_validate_json((CARDS_DIR / f"{card_id}.json").read_text(encoding="utf-8"))
    start, end = window_bounds(SMOKE_TAG)
    print(f"smoke   {card.agent_id}  {SMOKE_TAG} ({start} .. {end})  (mandate ${float(mandate.starting_cash):,.0f})")
    for rule in card.rules:
        print(f"        condition: {rule.condition}  on {rule.on_symbol}  {rule.from_symbol} -> {rule.to_symbol}")
    result = run_allocation(card, settings=settings, mandate=mandate, start=start, end=end)
    print(
        f"        sessions {result.sessions}  total_return {float(result.total_return):+.4%}  "
        f"max_drawdown {float(result.max_drawdown):.4%}"
    )
    print(f"        trades {len(result.trades)}  rejections {len(result.rejections)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run and score round 46.")
    parser.add_argument(
        "--smoke", action="store_true", help="run one card over one short window and exit"
    )
    parser.add_argument("--smoke-card", default=BOTH_ID)
    args = parser.parse_args(argv)

    if args.smoke:
        return smoke(args.smoke_card)

    settings = get_settings()
    mandate = desk_mandate(Purpose.SAVINGS)
    capital = float(mandate.starting_cash)

    cards = {}
    for path in sorted(CARDS_DIR.glob("*.json")):
        card = AllocationCard.model_validate_json(path.read_text(encoding="utf-8"))
        cards[card.agent_id] = card
    if CONTROL_ID not in cards:
        print(f"FATAL: no {CONTROL_ID} in {CARDS_DIR}")
        return 1

    md: list[str] = []
    md.append("# Round 46 -- ANALYSIS")
    md.append("")
    md.append("Generated by `strategy-program/tools/round46_run.py`. **Not investment advice.**")
    md.append("")

    print("macro pin : none -- this field is price-only")
    print(f"mandate   : SAVINGS, starting_cash ${capital:,.0f}")
    print(f"benchmark : {BENCHMARK_BLEND} (30/70 SPY/AGG, recomputed per window)")
    print(f"windows   : rank {RANK_TAGS} | report {REPORT_TAGS} | bear {BEAR_TAGS}\n")
    md.append(f"- mandate: SAVINGS, starting_cash ${capital:,.0f}")
    md.append(f"- benchmark: {BENCHMARK_BLEND} (30/70 SPY/AGG, recomputed per window)")
    md.append(f"- windows: rank {list(RANK_TAGS)} | report {list(REPORT_TAGS)} | bear {list(BEAR_TAGS)}")
    md.append("")

    # Benchmark blend per window (total return), the honest yardstick for a defensive book.
    bench: dict[str, float | None] = {}
    for tag in ALL_TAGS:
        start, end = window_bounds(tag)
        try:
            b = price_blend(REGISTRY[BENCHMARK_BLEND], start=start, end=end, settings=settings)
            bench[tag] = float(b) if b is not None else None
        except Exception as exc:
            bench[tag] = None
            print(f"  benchmark unpriceable in {tag}: {type(exc).__name__}")

    results = {aid: run_card_windows(c, settings, mandate, capital) for aid, c in cards.items()}
    control = results[CONTROL_ID]

    # Per-card table over the judged rungs.
    print(f"{'card':16} {'horizon':8} " + " ".join(f"{t:>9}" for t in RANK_TAGS))
    md.append("## Per-card max drawdown, judged rungs")
    md.append("")
    md.append("| card | " + " | ".join(RANK_TAGS) + " |")
    md.append("|---|" + "---|" * len(RANK_TAGS))
    for aid in sorted(results):
        row_dd = []
        for t in RANK_TAGS:
            r = results[aid][t]
            row_dd.append(f"{r['max_drawdown']*100:>8.1f}%" if r.get("ok") else f"{'n/a':>9}")
        print(f"{aid:16} {'maxDD':8} " + " ".join(row_dd))
        md.append(f"| {aid} | " + " | ".join(s.strip() for s in row_dd) + " |")
    md.append("")

    # Treatment minus control, on the rungs where the treatment's condition actually fired.
    analysis: dict[str, object] = {
        "round": 46, "capital": capital, "benchmark_blend": BENCHMARK_BLEND,
        "rank_tags": list(RANK_TAGS), "bench_return": bench, "cards": results, "vs_control": {},
    }
    print("\n== treatment minus control (drawdown & MAR), judged rungs ==")
    md.append("## Treatment minus control (drawdown & MAR), judged rungs")
    md.append("")
    md.append("| card | fired | dd_margin_pp | mar_margin | cagr_margin_pp | verdict |")
    md.append("|---|---|---|---|---|---|")
    print(f"{'card':16} {'fired':>6} {'dd_margin':>10} {'mar_margin':>11} {'cagr_margin':>12} verdict")
    dd_by_tag: dict[str, dict[str, float]] = {}
    for aid in sorted(results):
        if aid == CONTROL_ID:
            continue
        dd_by_tag[aid] = _dd_margins_by_tag(aid, results, control, RANK_TAGS)
        fired = 0
        dd_margins, mar_margins, cagr_margins = [], [], []
        for t in RANK_TAGS:
            r, c = results[aid][t], control[t]
            if not _fired(r, c):
                continue  # condition never fired here: identical to control by construction
            fired += 1
            dd_margins.append((r["max_drawdown"] - c["max_drawdown"]) * 100)  # +ve = shallower DD
            rm, cm = mar(r["cagr"], r["max_drawdown"]), mar(c["cagr"], c["max_drawdown"])
            if rm is not None and cm is not None:
                mar_margins.append(rm - cm)
            if r["cagr"] is not None and c["cagr"] is not None:
                cagr_margins.append((r["cagr"] - c["cagr"]) * 100)
        dd_m = median_or_none(dd_margins)
        mar_m = median_or_none(mar_margins)
        cagr_m = median_or_none(cagr_margins)
        verdict = "UNMEASURED (fired <2 rungs)" if fired < W.MIN_ELIGIBLE_R5_PER_HORIZON else "measured"
        analysis["vs_control"][aid] = {  # type: ignore[index]
            "fired_rungs": fired, "dd_margin_pp": dd_m, "mar_margin": mar_m,
            "cagr_margin_pp": cagr_m, "verdict": verdict,
        }
        s_dd = "n/a" if dd_m is None else f"{dd_m:>+9.2f}"
        s_mar = "n/a" if mar_m is None else f"{mar_m:>+11.3f}"
        s_cagr = "n/a" if cagr_m is None else f"{cagr_m:>+11.2f}"
        print(f"{aid:16} {fired:>6} {s_dd:>10} {s_mar:>11} {s_cagr:>12} {verdict}")
        md.append(
            f"| {aid} | {fired} | {s_dd.strip()} | {s_mar.strip()} | {s_cagr.strip()} | {verdict} |"
        )
    md.append("")

    # This round's whole point: five pairwise lines, per-rung then median across common rungs.
    print("\n== additivity pairwise lines (drawdown margin, judged rungs) ==")
    md.append("## Additivity pairwise lines (drawdown margin, judged rungs)")
    md.append("")
    md.append("| pair | rungs | median_pp | verdict |")
    md.append("|---|---|---|---|")
    pairwise: dict[str, dict[str, object]] = {}

    def _report_pair(name: str, value: float | None, n: int, verdict: str) -> None:
        s_val = "n/a" if value is None else f"{value:+.2f}"
        print(f"  {name:24} rungs={n:>2}  {s_val:>8}pp   {verdict}")
        md.append(f"| {name} | {n} | {s_val.strip()} | {verdict} |")
        pairwise[name] = {"median_pp": value, "rungs": n, "verdict": verdict}

    both_minus_spy, n1 = _pairwise_median(dd_by_tag[BOTH_ID], dd_by_tag[SPY_ID], lambda b, s: b - s)
    _report_pair(
        "both - spy", both_minus_spy, n1,
        "n/a" if both_minus_spy is None else ("both adds over spy alone" if both_minus_spy > 0 else "both does not improve on spy alone"),
    )

    both_minus_agg, n2 = _pairwise_median(dd_by_tag[BOTH_ID], dd_by_tag[AGG_ID], lambda b, a: b - a)
    _report_pair(
        "both - agg", both_minus_agg, n2,
        "n/a" if both_minus_agg is None else ("both adds over agg alone" if both_minus_agg > 0 else "both does not improve on agg alone"),
    )

    common_sum = sorted(set(dd_by_tag[BOTH_ID]) & set(dd_by_tag[SPY_ID]) & set(dd_by_tag[AGG_ID]))
    if common_sum:
        sum_diffs = [
            dd_by_tag[BOTH_ID][t] - (dd_by_tag[SPY_ID][t] + dd_by_tag[AGG_ID][t]) for t in common_sum
        ]
        both_minus_sum = median_or_none(sum_diffs)
    else:
        both_minus_sum = None
    verdict_p1 = (
        "n/a"
        if both_minus_sum is None
        else (
            f"within +/-{ADDITIVITY_TOLERANCE_PP}pp of the sum (P1 holds -- reads look independent)"
            if abs(both_minus_sum) <= ADDITIVITY_TOLERANCE_PP
            else f"more than {ADDITIVITY_TOLERANCE_PP}pp from the sum (P1 falsified -- reads overlap)"
        )
    )
    _report_pair("both - (spy + agg)", both_minus_sum, len(common_sum), verdict_p1)

    both_gld_minus_both, n4 = _pairwise_median(
        dd_by_tag[BOTH_GLD_ID], dd_by_tag[BOTH_ID], lambda g, b: g - b
    )
    verdict_p4a = (
        "n/a"
        if both_gld_minus_both is None
        else (
            f"improves both by >{ADDITIVITY_TOLERANCE_PP}pp (P4 falsified for GLD -- the add-on helps)"
            if both_gld_minus_both > ADDITIVITY_TOLERANCE_PP
            else "does not improve both by more than the tolerance (P4 holds for GLD)"
        )
    )
    _report_pair("both-gld - both", both_gld_minus_both, n4, verdict_p4a)

    both_trim_minus_both, n5 = _pairwise_median(
        dd_by_tag[BOTH_TRIM_ID], dd_by_tag[BOTH_ID], lambda t, b: t - b
    )
    verdict_p4b = (
        "n/a"
        if both_trim_minus_both is None
        else (
            f"improves both by >{ADDITIVITY_TOLERANCE_PP}pp (P4 falsified for trim -- the add-on helps)"
            if both_trim_minus_both > ADDITIVITY_TOLERANCE_PP
            else "does not improve both by more than the tolerance (P4 holds for trim)"
        )
    )
    _report_pair("both-trim - both", both_trim_minus_both, n5, verdict_p4b)
    md.append("")

    analysis["additivity"] = pairwise

    # Bear-window coverage, split: the 2022 windows are in-sample to the hypothesis (round 43 section 5).
    print("\n== bear-window firing (each treatment's condition, treatment vs control) ==")
    md.append("## Bear-window firing, split by hindsight status")
    md.append("")
    md.append("### 2022 (in-sample to the hypothesis)")
    md.append("")
    md.append("| card | " + " | ".join(HINDSIGHT_TAGS) + " |")
    md.append("|---|" + "---|" * len(HINDSIGHT_TAGS))
    other_bear = tuple(t for t in BEAR_TAGS if t not in HINDSIGHT_TAGS)
    hindsight_rows: dict[str, dict[str, object]] = {}
    for aid in sorted(results):
        if aid == CONTROL_ID:
            continue
        fired_hindsight = [t for t in HINDSIGHT_TAGS if _fired(results[aid][t], control[t])]
        fired_other = [t for t in other_bear if _fired(results[aid][t], control[t])]
        hindsight_rows[aid] = {
            "fired_2022": fired_hindsight, "fired_other_bear": fired_other,
        }
        print(
            f"  {aid:16} 2022 (in-sample to hypothesis): fired {len(fired_hindsight)}/{len(HINDSIGHT_TAGS)}"
            f"   other bear windows: fired {len(fired_other)}/{len(other_bear)}"
        )
        md.append(f"| {aid} | " + " | ".join("fired" if t in fired_hindsight else "-" for t in HINDSIGHT_TAGS) + " |")
    md.append("")
    md.append("### Other bear windows (not in-sample to the hypothesis)")
    md.append("")
    md.append("| card | " + " | ".join(other_bear) + " |")
    md.append("|---|" + "---|" * len(other_bear))
    for aid in sorted(results):
        if aid == CONTROL_ID:
            continue
        fired_other = hindsight_rows[aid]["fired_other_bear"]
        md.append(f"| {aid} | " + " | ".join("fired" if t in fired_other else "-" for t in other_bear) + " |")
    md.append("")
    analysis["bear_hindsight_split"] = {
        "hindsight_tags": list(HINDSIGHT_TAGS), "other_bear_tags": list(other_bear),
        "by_card": hindsight_rows,
    }

    md.append("---")
    md.append("")
    md.append(
        "Not investment advice. Price-only bars; AGG/GLD/BIL distributions are unmodelled, so every "
        "CAGR is understated and the drawdown column is the trustworthy half. A stack that de-risks "
        "both sleeves at once sits twenty points of the book in BIL on any session where both "
        "conditions fire simultaneously (ten from SPY, ten from AGG, on top of BIL's own 10% target) "
        "-- the opportunity cost of that cash is not modelled here beyond BIL's own (near-zero, "
        "unmodelled) yield."
    )

    dest_json = REPO / "data" / "rounds" / "r46-2026-09" / "analysis.json"
    dest_json.write_text(json.dumps(analysis, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nwrote {dest_json.relative_to(REPO).as_posix()}")

    dest_md = REPO / "data" / "rounds" / "r46-2026-09" / "ANALYSIS.md"
    dest_md.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {dest_md.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
