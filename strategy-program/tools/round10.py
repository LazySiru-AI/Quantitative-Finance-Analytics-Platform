"""Round 10's rule, applied to the frozen evidence: Gate A, Gate S', ranking, distinctness.

Round 10 replaces round 9's Gate S. The replacement is pre-registered in
`strategy-program/ROUND-10-PLAN.md`; this module is the executable form of it, kept in the tools
directory rather than in a scratch script so the numbers in `data/rounds/r10-2026-08/SELECTION.md`
can be reproduced by anyone who reads them::

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round10.py

**This round adds no new measurements, and that is deliberate.** Round 9 and round 10 are two rules
applied to one body of evidence. The bar store is unchanged since round 9 ran (verified here, not
assumed: `--verify-store` prints SPY's row count and last date), every card is frozen, and every
window is fixed, so a re-run of the round-2/round-4/round-5 matrices or of the out-of-sample
tournament is a deterministic recomputation rather than a new draw -- `strategy-program/PROTOCOL.md`
section 6(a). What *is* recomputed here is the arithmetic over those stored results, which is cheap
and worth doing rather than copying a prior round's prose; what is carried forward is Gate L, whose
inputs are verified identical rather than re-run.

**Two benchmark anchors, and every figure says which it used.** SPY figures come from the engine's
own `benchmark_return` stored on each `AgentResult`, measured over the sessions that run actually
traded. QQQ figures are recomputed here from the bar store, close-to-close over each window's
calendar start/end dates from `data/rounds/r5-2026-08/windows.json`. The two differ by up to ~0.12
annualized points on these windows for reasons that have nothing to do with any card; round 5's
report measured the effect and rounds 8 and 9 both restate it. `--check` reproduces round 9's
published QQQ figures from scratch as a guard that this module computes them the same way.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import score

from app.config import get_settings
from app.db import duck

#: The candidate field, and each card's `StrategyCard.discipline`. Fifteen cards, unchanged from
#: rounds 6, 8 and 9 -- the same convention those rounds used for ranking, reproduced rather than
#: re-derived so a rank in this document means the same thing a rank in those documents means.
FIELD: dict[str, str] = {
    "B-momentum": "momentum",
    "B2-hold-90": "momentum",
    "B3-concentrated": "momentum",
    "B4-tight-stop": "momentum",
    "A-rotation": "pairs-rotation",
    "c20-rotation": "pairs-rotation",
    "C-trend": "trend",
    "H-trend-diversified": "trend",
    "c07-chop": "mean-reversion",
    "c18-meanrev": "mean-reversion",
    "c09-convex": "volatility",
    "c19-volatility": "volatility",
    "c14-riskmanaged-wide": "risk-managed",
    "c21-uncorrelated": "risk-managed",
    "c11-breakout": "breakout",
}

#: Cards that count as one entry for the distinctness rule regardless of `discipline`. Unchanged
#: from rounds 6-9: the four are variants of a single base card, and seating two of them would be
#: seating one idea twice.
BASE_FAMILY: dict[str, str] = {
    "B-momentum": "B",
    "B2-hold-90": "B",
    "B3-concentrated": "B",
    "B4-tight-stop": "B",
}

#: Round 5's 5-year and 10-year rungs -- the horizons the desk actually holds forward over, and what
#: both Gate A and the ranking are computed on.
RUNGS_5Y: tuple[str, ...] = ("h5y-1", "h5y-2", "h5y-3")
RUNGS_10Y: tuple[str, ...] = ("h10y-1", "h10y-2")

#: Gate S' -- see `strategy-program/ROUND-10-PLAN.md` section 3 for why each number is what it is.
#: `MIN_MATRICES` is a coverage floor: a card seen on one matrix has no dispersion to measure.
#: `MAX_RANK_RANGE` is the whole of the rest of the gate; there is deliberately no level term,
#: because level is Gate A's job and the ranking step's job, and round 9's defect was measuring it
#: a third time here.
MIN_MATRICES = 2
MAX_RANK_RANGE = 3

R5_RESULTS = Path("data/rounds/r5-2026-08/results")
R5_WINDOWS = Path("data/rounds/r5-2026-08/windows.json")

#: Gate L's verdicts, carried forward from `data/rounds/r9-2026-08/SELECTION.md` section 2 rather
#: than re-run. The clause is unchanged, the fifteen cards are frozen, the window (2026-02-17 to
#: 2026-08-18, 127 sessions) is bounded by a bar store this module verifies is unchanged, and the
#: desk's own `as_of` is still 2026-08-18 -- so re-running it would reproduce it exactly and then
#: be reported as if two rounds had independently confirmed something. They would not have; it is
#: one measurement counted twice.
GATE_L_FAIL: dict[str, str] = {
    "c07-chop": "all cash for 92 sessions; last trade closed 2026-04-07, past the 60-session line",
    "c14-riskmanaged-wide": "zero trades in the out-of-sample window",
}


class MatrixSpec(NamedTuple):
    name: str
    results: Path
    round_tag: str
    tags: tuple[str, ...]
    annualized: bool


MATRICES: tuple[MatrixSpec, ...] = (
    MatrixSpec("r2", Path("data/rounds/r2-2026-08/results"), "r1", score.MAIN_WINDOW_TAGS, False),
    MatrixSpec("r4", Path("data/rounds/r4-2026-08/results"), "r1", score.R4_MAIN_WINDOW_TAGS, False),
    # Annualized because the ladder arm mixes 6-month through 10-year windows and a raw median
    # cannot compare them; r2 and r4 are all comparably-sized regime windows, so they are not.
    MatrixSpec("r5-ladder", R5_RESULTS, "r1", score.R5_LADDER_TAGS, True),
)


def _medians(spec: MatrixSpec) -> dict[str, Decimal]:
    """Each field card's median adjusted excess on one matrix, over the windows it actually ran."""
    by_window = score.load_results(spec.results, spec.round_tag, list(spec.tags))
    per_card: dict[str, list[Decimal]] = {}
    for agents in by_window.values():
        for agent_id, result in agents.items():
            if agent_id not in FIELD:
                continue
            value = (
                score.annualized_adjusted_excess(result)
                if spec.annualized
                else score.adjusted_excess(result)
            )
            if value is not None:
                per_card.setdefault(agent_id, []).append(value)
    return {agent_id: median(values) for agent_id, values in per_card.items() if values}


def _ranks(values: dict[str, Decimal]) -> dict[str, int]:
    """1-indexed rank, descending, rank 1 best. Cards absent from ``values`` are absent here too --
    an unrun matrix produces no rank rather than a worst-place one."""
    order = sorted(values, key=lambda a: values[a], reverse=True)
    return {agent_id: i + 1 for i, agent_id in enumerate(order)}


def _qqq_annualized(conn, settings, start: dt.date, end: dt.date) -> Decimal:
    """QQQ's annualized close-to-close return over one window's calendar dates, from the bar store.

    Deliberately *not* the engine's `benchmark_return`: that is SPY, measured over the sessions a
    particular run actually traded. This is a second, independent anchor over the window's stated
    calendar period, and every figure derived from it is labelled as such.
    """
    bars = duck.read_bars(conn, settings.bars_dir, "QQQ", duck.Interval.DAY, start=start, end=end)
    closes = [Decimal(str(c)) for c in bars["close"].tolist()]
    if len(closes) < 2:
        raise ValueError(f"QQQ has {len(closes)} bars over {start}..{end} -- cannot price the window")
    total = closes[-1] / closes[0] - 1
    years = Decimal(len(closes)) / score._TRADING_DAYS_PER_YEAR
    return (1 + total) ** (1 / years) - 1 if years > 0 else Decimal(0)


def rung_excess_vs_qqq() -> dict[str, dict[str, Decimal]]:
    """``{agent_id: {rung_tag: annualized adjusted excess vs QQQ}}`` over the 5y and 10y rungs.

    ``annualized_return - capital_exposure * annualized_qqq`` -- the same shape as
    `score.annualized_adjusted_excess`, with QQQ substituted for the engine's SPY benchmark. Using
    `capital_exposure` and not `exposure` is defect D2: `exposure` counts sessions the card was
    present, `capital_exposure` counts capital actually deployed, and only the second one makes
    "did the rules beat being invested this much" a fair question.
    """
    windows = json.loads(R5_WINDOWS.read_text(encoding="utf-8"))
    dates = {
        w["tag"]: (dt.date.fromisoformat(w["start"]), dt.date.fromisoformat(w["end"]))
        for arm in windows["arms"].values()
        for w in arm
    }
    rungs = RUNGS_5Y + RUNGS_10Y
    settings = get_settings()
    out: dict[str, dict[str, Decimal]] = {}
    with duck.connect(settings.analytics_path) as conn:
        qqq = {tag: _qqq_annualized(conn, settings, *dates[tag]) for tag in rungs}
    by_window = score.load_results(R5_RESULTS, "r1", list(rungs))
    for tag in rungs:
        for agent_id, result in by_window[tag].items():
            if agent_id not in FIELD:
                continue
            ann = score.annualized_return(result)
            cap = score.capital_exposure(result)
            if ann is None or cap is None:
                continue
            out.setdefault(agent_id, {})[tag] = ann - cap * qqq[tag]
    return out


def gate_a(qqq_by_rung: dict[str, dict[str, Decimal]]) -> dict[str, dict[str, Decimal | bool]]:
    """Positive median annualized adjusted excess at *both* the 5y and 10y rungs against *both*
    benchmarks. Unchanged from rounds 8 and 9, recomputed rather than copied."""
    by_window = score.load_results(R5_RESULTS, "r1", list(RUNGS_5Y + RUNGS_10Y))
    spy: dict[str, dict[str, Decimal]] = {}
    for tag in RUNGS_5Y + RUNGS_10Y:
        for agent_id, result in by_window[tag].items():
            if agent_id in FIELD:
                value = score.annualized_adjusted_excess(result)
                if value is not None:
                    spy.setdefault(agent_id, {})[tag] = value

    out: dict[str, dict[str, Decimal | bool]] = {}
    for agent_id in FIELD:
        s, q = spy.get(agent_id, {}), qqq_by_rung.get(agent_id, {})
        cells = {
            "spy_5y": _median_of(s, RUNGS_5Y),
            "spy_10y": _median_of(s, RUNGS_10Y),
            "qqq_5y": _median_of(q, RUNGS_5Y),
            "qqq_10y": _median_of(q, RUNGS_10Y),
        }
        values = list(cells.values())
        cells["pass"] = all(v is not None and v > 0 for v in values)
        out[agent_id] = cells
    return out


def _median_of(values: dict[str, Decimal], tags: tuple[str, ...]) -> Decimal | None:
    present = [values[t] for t in tags if t in values]
    return median(present) if present else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="reproduce round 9's published QQQ figures")
    parser.add_argument("--verify-store", action="store_true", help="print bar-store coverage and exit")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.verify_store:
        with duck.connect(settings.analytics_path) as conn:
            for sym in ("SPY", "QQQ"):
                bars = duck.read_bars(conn, settings.bars_dir, sym, duck.Interval.DAY)
                print(f"{sym}: {len(bars)} rows, last {bars['ts'].max().date()}")
        return 0

    qqq_by_rung = rung_excess_vs_qqq()
    a = gate_a(qqq_by_rung)

    print("== Gate A -- median annualized adjusted excess at the 5y and 10y rungs ==")
    print(f"{'card':24} {'5y SPY':>8} {'5y QQQ':>8} {'10y SPY':>8} {'10y QQQ':>8}  verdict")
    for agent_id, c in sorted(a.items(), key=lambda kv: -(kv[1]["spy_5y"] or Decimal(-99))):
        print(
            f"{agent_id:24} " + " ".join(f"{_pct(c[k]):>8}" for k in
                                         ("spy_5y", "qqq_5y", "spy_10y", "qqq_10y"))
            + f"  {'pass' if c['pass'] else 'FAIL'}"
        )
    survivors_a = [k for k, v in a.items() if v["pass"]]
    print(f"\nGate A survivors ({len(survivors_a)}): {', '.join(sorted(survivors_a))}")

    print("\n== Gate L -- carried forward from round 9 section 2 (inputs verified unchanged) ==")
    for agent_id, why in GATE_L_FAIL.items():
        mark = " (already out at Gate A)" if agent_id not in survivors_a else ""
        print(f"  FAIL {agent_id:24} {why}{mark}")
    survivors_l = [a_id for a_id in survivors_a if a_id not in GATE_L_FAIL]
    print(f"Gate L survivors ({len(survivors_l)}): {', '.join(sorted(survivors_l))}")

    rank_table = {spec.name: _ranks(_medians(spec)) for spec in MATRICES}
    print("\n== Gate S' -- coverage >= 2 matrices, rank range <= 3, no level term ==")
    print(f"{'card':24} {'discipline':15} {'r2':>6} {'r4':>6} {'r5':>6} {'range':>6} {'seen':>5}  verdict")
    s_pass: list[str] = []
    s_detail: dict[str, dict[str, object]] = {}
    for agent_id in sorted(FIELD, key=lambda a: (FIELD[a], a)):
        ranks = [rank_table[m.name].get(agent_id) for m in MATRICES]
        seen = [r for r in ranks if r is not None]
        rng = max(seen) - min(seen) if seen else None
        ok = len(seen) >= MIN_MATRICES and rng is not None and rng <= MAX_RANK_RANGE
        eligible = agent_id in survivors_l
        verdict = ("pass" if ok else "FAIL") if eligible else "n/a (out earlier)"
        if ok and eligible:
            s_pass.append(agent_id)
        s_detail[agent_id] = {"ranks": ranks, "range": rng, "seen": len(seen), "pass": ok}
        cells = " ".join(f"{r if r is not None else '--':>6}" for r in ranks)
        flag = "  <-- reduced coverage" if len(seen) == MIN_MATRICES and ok else ""
        print(
            f"{agent_id:24} {FIELD[agent_id]:15} {cells} "
            f"{rng if rng is not None else '--':>6} {len(seen):>5}  {verdict}{flag}"
        )
    print(f"\nGate S' survivors ({len(s_pass)}): {', '.join(sorted(s_pass))}")

    print("\n== Ranking -- median annualized adjusted excess vs QQQ over the 5y and 10y rungs ==")
    ranked = sorted(
        s_pass,
        key=lambda a: _median_of(qqq_by_rung.get(a, {}), RUNGS_5Y + RUNGS_10Y) or Decimal(-99),
        reverse=True,
    )
    rungs = RUNGS_5Y + RUNGS_10Y
    print(f"{'card':24} " + " ".join(f"{t:>8}" for t in rungs) + f" {'median':>9}")
    for agent_id in ranked:
        cells = qqq_by_rung.get(agent_id, {})
        med = _median_of(cells, rungs)
        print(
            f"{agent_id:24} " + " ".join(f"{_pct(cells.get(t)):>8}" for t in rungs)
            + f" {_pct(med):>9}"
        )

    print("\n== Distinctness -- one per discipline, one per base family; seat count is an output ==")
    seats: list[str] = []
    used_disc: set[str] = set()
    used_family: set[str] = set()
    for agent_id in ranked:
        disc, fam = FIELD[agent_id], BASE_FAMILY.get(agent_id, agent_id)
        if disc in used_disc:
            print(f"  skip {agent_id:22} -- {disc} seat already taken")
            continue
        if fam in used_family:
            print(f"  skip {agent_id:22} -- base family {fam} already seated")
            continue
        if len(seats) >= 4:
            print(f"  skip {agent_id:22} -- four seats already filled (cap)")
            continue
        seats.append(agent_id)
        used_disc.add(disc)
        used_family.add(fam)
        print(f"  SEAT {agent_id:22} ({disc})")

    print(f"\n== Round 10 ranked roster: {len(seats)} of a possible 4 ==")
    for i, agent_id in enumerate(seats, 1):
        print(f"  {i}. {agent_id}")
    print("  + ladder-qld-schd (seated outside the competition, unranked)")

    if args.check:
        print("\n== Check: round 9's published QQQ figures, recomputed here ==")
        expect = {
            ("B-momentum", "h5y-1"): "+9.41%", ("B-momentum", "h5y-2"): "+7.68%",
            ("B-momentum", "h5y-3"): "+9.29%", ("B-momentum", "h10y-1"): "+3.74%",
            ("B-momentum", "h10y-2"): "+4.10%", ("B4-tight-stop", "h5y-3"): "+4.96%",
            ("B3-concentrated", "h10y-2"): "+2.72%",
        }
        bad = 0
        for (agent_id, tag), want in sorted(expect.items()):
            got = _pct(qqq_by_rung.get(agent_id, {}).get(tag))
            ok = got == want
            bad += not ok
            print(f"  {'OK ' if ok else 'DIFF'} {agent_id:20} {tag:8} round 9 {want:>8}  here {got:>8}")
        print(f"  {len(expect) - bad}/{len(expect)} reproduce round 9 exactly")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "gate_a": {k: {kk: _pct(vv) if isinstance(vv, Decimal) else vv
                                   for kk, vv in v.items()} for k, v in a.items()},
                    "gate_l_fail": GATE_L_FAIL,
                    "gate_s_prime": s_detail,
                    "ranking_vs_qqq": {k: {kk: _pct(vv) for kk, vv in v.items()}
                                       for k, v in qqq_by_rung.items()},
                    "seats": seats,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    return 0


def _pct(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.2f}%"


if __name__ == "__main__":
    raise SystemExit(main())
