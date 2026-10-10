"""Round 12's rule, applied: distinctness replaced, everything else held fixed.

Pre-registered in `strategy-program/ROUND-12-PLAN.md`, committed before any round-12 selection ran.
This module is the executable form of it::

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round12.py

**What changed from round 11, and only this.** Gate A and Gate L (backtest floors), Gate C (positive
live `adjusted_excess` in >= 3 of 6 sub-periods) and the ranking on median live adjusted excess -- with
its tie-break chain of live hit rate, then Gate S' backtest rank range, then the 10-year QQQ median --
are reused unmodified from `round10` and `round11`. **Only distinctness changes.** The discipline
clause and the base-family clause are both replaced by one rule stated over holdings: walk the ranking,
seat the first card, and seat each later card if its novel-name count against the union of everything
already seated is >= 1.0 (`ROUND-12-PLAN.md` section 3). `holdings_overlap.novelty` computes the
count; this module only walks the ranking with it. Seat count is still an output, capped at four, with
no floor.

**Round 12 adds no new evidence.** The bar store, every card and every window are the same evidence
round 11 used. This module runs no tournament. It recomputes gates and the live matrix from stored
`AgentResult` JSON exactly as `round11.py` does (frozen results in, deterministic arithmetic out), and
adds one new computation -- novelty over per-session holdings, reconstructed from the `live-6`
cumulative run's own trade log via `holdings_overlap.held_by_session`, which is also unmodified here.

**Do not run anything under `app.tournament` from this module or alongside it.** The bar store is one
DuckDB file; a concurrent writer corrupts results silently (`strategy-program/DEFECTS.md` D3). Every
read this module performs is either a stored-JSON read or a read-only bar-store read.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import holdings_overlap
import round10
import round11
import score

from app.config import get_settings
from app.db import duck

#: Distinctness threshold, in novel names against the union of everyone already seated. One whole
#: position -- the unit `ROUND-12-PLAN.md` section 3 derives, not a fitted percentage. Section 5's
#: feasibility check (`data/rounds/r12-2026-08/holdings-overlap.txt`) shows the roster this produces
#: is unchanged at half this value, which is the evidence that the answer is not balanced on it.
NOVELTY_THRESHOLD = 1.0

#: What the plan's own feasibility check (section 5) recorded the store as, so a divergence is
#: reported rather than silently absorbed. See `main`'s store check.
EXPECTED_SPY_ROWS = 8445
EXPECTED_SPY_LAST = "2026-08-18"

#: The live window's own end date -- every computation in this module (Gate A/L rungs, the live
#: matrix, and the holdings walk) is bounded at or before this date, so bars appended to the store
#: after it cannot change any number below even if the row count has moved.
LIVE_WINDOW_END = "2026-08-18"


def _pct(value: Decimal | float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.2f}%"


def verify_store() -> tuple[int, str]:
    """SPY's row count and last date in the store, read-only. Not assumed -- checked."""
    settings = get_settings()
    with duck.connect(settings.analytics_path) as conn:
        bars = duck.read_bars(conn, settings.bars_dir, "SPY", duck.Interval.DAY)
    return len(bars), str(bars["ts"].max().date())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    # ---- Store check -- this round adds no new evidence, and that claim is checked, not assumed ----
    rows, last_date = verify_store()
    print("== Store check -- round 12 adds no new evidence; this is a different RULE over round 11's ==")
    print("== evidence, not a fresh measurement ==")
    print(f"SPY: {rows} rows, last {last_date}")
    if rows != EXPECTED_SPY_ROWS or last_date != EXPECTED_SPY_LAST:
        print(
            f"  !! store has moved since the plan was written (expected {EXPECTED_SPY_ROWS} rows "
            f"ending {EXPECTED_SPY_LAST}). Every gate and the live matrix below are bounded at or "
            f"before {LIVE_WINDOW_END}, so bars appended after that date cannot change any figure in "
            f"this run -- but the mismatch is reported here rather than silently absorbed. See "
            f"SELECTION.md section 0."
        )

    # ---- Gates A, L -- floors, unchanged from round 10/11 ----
    qqq = round10.rung_excess_vs_qqq()
    a = round10.gate_a(qqq)
    survivors_a = [k for k, v in a.items() if v["pass"]]
    survivors_l = [k for k in survivors_a if k not in round10.GATE_L_FAIL]

    print("\n== Gate A (floor) -- unchanged, recomputed ==")
    print(f"Gate A survivors ({len(survivors_a)}): {', '.join(sorted(survivors_a))}")
    print("\n== Gate L (floor) -- carried forward from round 9 section 2 ==")
    for agent_id, why in round10.GATE_L_FAIL.items():
        print(f"  FAIL {agent_id:24} {why}")
    print(f"Gate L survivors ({len(survivors_l)}): {', '.join(sorted(survivors_l))}")

    # ---- Live matrix -- unchanged from round 11, via its own differencing (D5's fix) ----
    cells = round11.live_cells()

    missing = {a_id: 6 - len(cells.get(a_id, {})) for a_id in round10.FIELD}
    short = {k: v for k, v in missing.items() if v}
    if short:
        print(f"\n!! INCOMPLETE MATRIX -- missing cells: {short}")
        print("   A shortfall is a lost card, not a coverage rule. Re-run before reading anything below.")

    print("\n== The live matrix -- adjusted excess per sub-window, whole field (round11.live_cells) ==")
    header = " ".join(f"{t:>9}" for t in score.R11_LIVE_TAGS)
    print(f"{'card':24} {header} {'median':>9} {'hits':>6}")
    from statistics import median as _median

    live: dict[str, dict[str, object]] = {}
    for agent_id in round10.FIELD:
        row = cells.get(agent_id, {})
        vals = [row[t] for t in score.R11_LIVE_TAGS if t in row]
        med = _median(vals) if vals else None
        hits = sum(1 for v in vals if v > 0)
        live[agent_id] = {"median": med, "hits": hits, "n": len(vals)}
        body = " ".join(f"{_pct(row.get(t)):>9}" for t in score.R11_LIVE_TAGS)
        print(f"{agent_id:24} {body} {_pct(med):>9} {f'{hits}/{len(vals)}':>6}")

    print(f"\n== Gate C -- positive adjusted excess in >= {round11.MIN_LIVE_HITS} of 6 ==")
    survivors_c = []
    for agent_id in survivors_l:
        hits = live[agent_id]["hits"]
        ok = hits >= round11.MIN_LIVE_HITS
        survivors_c.append(agent_id) if ok else None
        print(f"  {'pass' if ok else 'FAIL'} {agent_id:24} {hits}/6")
    print(f"Gate C survivors ({len(survivors_c)}): {', '.join(sorted(survivors_c))}")

    # ---- Ranking -- unchanged tie-break chain from round 11 ----
    rank_table = {spec.name: round10._ranks(round10._medians(spec)) for spec in round10.MATRICES}
    spread: dict[str, int | None] = {}
    for agent_id in round10.FIELD:
        seen = [r for r in (rank_table[m.name].get(agent_id) for m in round10.MATRICES) if r]
        spread[agent_id] = max(seen) - min(seen) if len(seen) >= 2 else None

    print("\n== Ranking -- live median, then live hit rate, then backtest rank range (tie-breaks) ==")

    def key(agent_id: str):
        m = live[agent_id]["median"]
        return (
            -(m if m is not None else Decimal(-99)),
            -live[agent_id]["hits"],
            spread[agent_id] if spread[agent_id] is not None else 99,
            -(a[agent_id]["qqq_10y"] or Decimal(-99)),
        )

    ranked = sorted(survivors_c, key=key)
    print(f"{'card':24} {'live median':>12} {'hits':>6} {'S-range':>8} {'10y QQQ':>9}")
    for agent_id in ranked:
        hits_str = f"{live[agent_id]['hits']}/6"
        print(
            f"{agent_id:24} {_pct(live[agent_id]['median']):>12} "
            f"{hits_str:>6} {spread[agent_id]!s:>8} "
            f"{_pct(a[agent_id]['qqq_10y']):>9}"
        )

    # ---- Distinctness -- round 12's rule, over holdings ----
    print("\n== Distinctness -- novelty over holdings, novel names >= "
          f"{NOVELTY_THRESHOLD:.2f} against the union seated ==")
    days = holdings_overlap.sessions(*holdings_overlap.WINDOW)
    held: dict[str, list[frozenset[str]]] = {}
    for agent_id in ranked:
        try:
            held[agent_id] = holdings_overlap.held_by_session(agent_id, days)
        except FileNotFoundError:
            print(f"  !! no live run on disk for {agent_id} -- cannot be assessed, excluded")

    seats: list[str] = []
    novelty_detail: dict[str, dict[str, object]] = {}
    for agent_id in ranked:
        if agent_id not in held:
            continue
        if len(seats) >= 4:
            print(f"  skip {agent_id:22} -- four seats already filled (cap)")
            continue
        if not seats:
            seats.append(agent_id)
            novelty_detail[agent_id] = {"count": None, "fraction": None, "n": None, "first": True}
            print(f"  SEAT {agent_id:22} (first ranked -- nothing to be redundant with)")
            continue
        count, frac, n = holdings_overlap.novelty(held[agent_id], [held[s] for s in seats])
        novelty_detail[agent_id] = {"count": count, "fraction": frac, "n": n, "first": False}
        if count is None:
            print(f"  skip {agent_id:22} -- never held anything; novelty undefined")
        elif count >= NOVELTY_THRESHOLD:
            seats.append(agent_id)
            print(
                f"  SEAT {agent_id:22} {count:>5.2f} novel names ({frac * 100:>4.1f}% of its book) "
                f"over {n} invested sessions"
            )
        else:
            print(
                f"  skip {agent_id:22} {count:>5.2f} novel names ({frac * 100:>4.1f}%) -- below the line"
            )

    print(f"\n== Round 12 ranked roster: {len(seats)} of a possible 4 ==")
    for i, agent_id in enumerate(seats, 1):
        print(f"  {i}. {agent_id}")
    print("  + ladder-qld-schd (seated outside the competition, unranked)")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "store": {"spy_rows": rows, "spy_last": last_date,
                              "expected_spy_rows": EXPECTED_SPY_ROWS,
                              "expected_spy_last": EXPECTED_SPY_LAST},
                    "live_matrix": {k: {kk: _pct(vv) for kk, vv in v.items()} for k, v in cells.items()},
                    "live_summary": {k: {"median": _pct(v["median"]), "hits": v["hits"], "n": v["n"]}
                                     for k, v in live.items()},
                    "backtest_rank_range": spread,
                    "gate_a_pass": sorted(survivors_a),
                    "gate_l_pass": sorted(survivors_l),
                    "gate_c_pass": sorted(survivors_c),
                    "ranked": ranked,
                    "novelty": {k: {"count": v["count"], "fraction": v["fraction"], "n": v["n"],
                                     "first": v["first"]} for k, v in novelty_detail.items()},
                    "seats": seats,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
