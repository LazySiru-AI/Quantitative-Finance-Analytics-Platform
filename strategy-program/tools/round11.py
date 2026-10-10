"""Round 11's rule, applied: fix 4 -- the live record ranks, the backtests are floors.

Pre-registered in `strategy-program/ROUND-11-PLAN.md` (commit `dda5573`, before any sub-window was
run). This module is the executable form of it::

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round11.py

**What changed from round 10.** Gates A and L are unchanged and stay eliminating, but their job is now
explicitly a floor -- "the long-horizon backtest does not say this card is broken". Gate S' stops
eliminating anything and becomes a tie-break. The ranking moves off the backtests entirely and onto the
live out-of-sample record, cut into the six contiguous sub-windows of `score.R11_MATRIX`. A new **Gate
C** requires positive `adjusted_excess` in at least 3 of the 6, so promoting the live record cannot
collapse into promoting one good month.

**The limitation this cannot fix, restated here because it belongs next to the code.** Six contiguous
sub-windows of one period are not six regime draws. They are one market environment cut into pieces.
A card clearing Gate C is consistent *within that environment* and the matrix says nothing about any
other -- which is exactly what the three backtest matrices, now demoted to floors and a tie-break,
were there to say. Weighting the narrow-but-unfittable evidence above the broad-but-fittable evidence
is the whole content of fix 4, and it is a trade rather than an upgrade.

Shared definitions (the fifteen-card field and its disciplines, the base-family map, Gate A, Gate L's
carried-forward verdicts, the three backtest matrices) are imported from `round10` rather than
restated, so a rank in this document means what a rank in round 10's document meant.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent))

import round10
import score

R11_RESULTS = Path("data/rounds/r11-2026-08/results")

#: Gate C: positive `adjusted_excess` in at least this many of the six live sub-windows. Half the
#: matrix plus one -- a bare majority, chosen so the gate asks "more often right than not" rather
#: than a threshold tuned to a particular field. Deliberately *not* set from the observed hit rates:
#: it is pre-registered in `ROUND-11-PLAN.md` section 3 and was fixed before any sub-window ran.
MIN_LIVE_HITS = 3


def live_cells() -> dict[str, dict[str, Decimal]]:
    """``{agent_id: {live_tag: adjusted_excess}}`` per sub-period, by differencing cumulative runs.

    **Each run under `R11_RESULTS` starts at 2026-02-17 and ends at its tag's boundary** -- they are
    cumulative, not independent (`strategy-program/tools/run_live_matrix.sh`). Six separate
    sub-window runs would each start with a flat book, forcing a card that entered in March and held
    into August to liquidate and re-enter at every boundary, inside a window too short for many entry
    rules to re-fire from a standing start. That version of this matrix put `B-momentum` at 0.0%
    exposure and zero trades in two entire sub-windows while it was in fact fully invested, and it
    biased the whole field toward high-turnover cards. See `strategy-program/DEFECTS.md` D5.

    Differencing recovers each sub-period **exactly**, because every quantity involved is either a
    level or a per-session sum over a `starting_equity` common to all six runs:

    * **return** -- ``ending_equity_k / ending_equity_{k-1} - 1``.
    * **benchmark** -- ``(1 + bench_k) / (1 + bench_{k-1}) - 1``. Chain-linked, not subtracted: two
      cumulative returns do not difference arithmetically.
    * **capital exposure** -- `AgentResult.capital_exposure` is
      ``sum(session_entry_notional) / (sessions * starting_equity)`` (`app.tournament.runner`), so
      multiplying back recovers the notional total and differencing gives the sub-period's. It is
      then divided by ``delta_sessions * ending_equity_{k-1}`` -- the equity the sub-period actually
      began with, which is the same base its return is measured against. Dividing by the original
      `starting_equity` instead would understate exposure for any card that had already grown, and
      would put the numerator and denominator of `adjusted_excess` on different bases.

    Non-annualized, unlike round 5's ladder arm: the six sub-periods are all the same size (21-22
    sessions), so a raw median compares like with like, and annualizing a three-week window would
    multiply every figure by twelve for no gain in comparability.
    """
    by_window = score.load_results(R11_RESULTS, "r1", list(score.R11_LIVE_TAGS))
    out: dict[str, dict[str, Decimal]] = {}
    for agent_id in round10.FIELD:
        runs = [by_window[tag].get(agent_id) for tag in score.R11_LIVE_TAGS]
        if any(r is None for r in runs):
            continue
        prev_equity = runs[0].starting_equity
        prev_bench = Decimal(0)
        prev_notional = Decimal(0)
        prev_sessions = 0
        for tag, r in zip(score.R11_LIVE_TAGS, runs, strict=True):
            d_sessions = r.sessions - prev_sessions
            if d_sessions <= 0 or prev_equity <= 0:
                break
            ret = r.ending_equity / prev_equity - 1
            bench = (1 + r.benchmark_return) / (1 + prev_bench) - 1
            notional = (
                Decimal(str(r.capital_exposure)) * Decimal(r.sessions) * runs[0].starting_equity
            )
            exposure = (notional - prev_notional) / (Decimal(d_sessions) * prev_equity)
            out.setdefault(agent_id, {})[tag] = ret - exposure * bench
            prev_equity, prev_bench = r.ending_equity, r.benchmark_return
            prev_notional, prev_sessions = notional, r.sessions
    return out


def _pct(value: Decimal | float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.2f}%"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    qqq = round10.rung_excess_vs_qqq()
    a = round10.gate_a(qqq)
    survivors_a = [k for k, v in a.items() if v["pass"]]
    survivors_l = [k for k in survivors_a if k not in round10.GATE_L_FAIL]

    print("== Gate A (floor) -- unchanged, recomputed ==")
    print(f"Gate A survivors ({len(survivors_a)}): {', '.join(sorted(survivors_a))}")
    print("\n== Gate L (floor) -- carried forward from round 9 section 2 ==")
    for agent_id, why in round10.GATE_L_FAIL.items():
        print(f"  FAIL {agent_id:24} {why}")
    print(f"Gate L survivors ({len(survivors_l)}): {', '.join(sorted(survivors_l))}")

    cells = live_cells()

    # Self-check: for the first sub-period there is nothing to difference against -- prev equity is
    # the run's own `starting_equity`, prev benchmark is 0 and prev notional is 0 -- so the
    # differenced cell must reduce exactly to `score.adjusted_excess` of that run. If the arithmetic
    # in `live_cells` is wrong anywhere, it is wrong here too, and this is the one cell where an
    # independent implementation already exists to check it against.
    first = score.load_results(R11_RESULTS, 'r1', [score.R11_LIVE_TAGS[0]])[score.R11_LIVE_TAGS[0]]
    for agent_id, result in sorted(first.items()):
        want = score.adjusted_excess(result)
        got = cells.get(agent_id, {}).get(score.R11_LIVE_TAGS[0])
        if want is not None and got is not None and abs(want - got) > Decimal('1e-12'):
            raise AssertionError(
                f'differencing disagrees with score.adjusted_excess on the first sub-period for '
                f'{agent_id}: {want} vs {got}'
            )
    print(
        f"\nself-check: first sub-period reduces to score.adjusted_excess "
        f"for all {len(first)} cards"
    )

    missing = {a_id: 6 - len(cells.get(a_id, {})) for a_id in round10.FIELD}
    short = {k: v for k, v in missing.items() if v}
    if short:
        print(f"\n!! INCOMPLETE MATRIX -- missing cells: {short}")
        print("   A shortfall is a lost card, not a coverage rule. Re-run before reading anything below.")

    print("\n== The live matrix -- adjusted excess per sub-window, whole field ==")
    header = " ".join(f"{t:>9}" for t in score.R11_LIVE_TAGS)
    print(f"{'card':24} {header} {'median':>9} {'hits':>6}")
    live: dict[str, dict[str, object]] = {}
    for agent_id in round10.FIELD:
        row = cells.get(agent_id, {})
        vals = [row[t] for t in score.R11_LIVE_TAGS if t in row]
        med = median(vals) if vals else None
        hits = sum(1 for v in vals if v > 0)
        live[agent_id] = {"median": med, "hits": hits, "n": len(vals)}
        body = " ".join(f"{_pct(row.get(t)):>9}" for t in score.R11_LIVE_TAGS)
        print(f"{agent_id:24} {body} {_pct(med):>9} {f'{hits}/{len(vals)}':>6}")

    print(f"\n== Gate C -- positive adjusted excess in >= {MIN_LIVE_HITS} of 6 ==")
    survivors_c = []
    for agent_id in survivors_l:
        hits = live[agent_id]["hits"]
        ok = hits >= MIN_LIVE_HITS
        survivors_c.append(agent_id) if ok else None
        print(f"  {'pass' if ok else 'FAIL'} {agent_id:24} {hits}/6")
    print(f"Gate C survivors ({len(survivors_c)}): {', '.join(sorted(survivors_c))}")

    # Gate S' no longer eliminates; its dispersion number is computed for every card and used only to
    # break ties the live record cannot separate.
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
        print(
            f"{agent_id:24} {_pct(live[agent_id]['median']):>12} "
            f"{f'{live[agent_id]["hits"]}/6':>6} {spread[agent_id]!s:>8} "
            f"{_pct(a[agent_id]['qqq_10y']):>9}"
        )

    print("\n== Distinctness -- one per discipline, one per base family; seat count is an output ==")
    seats: list[str] = []
    used_disc: set[str] = set()
    used_family: set[str] = set()
    for agent_id in ranked:
        disc = round10.FIELD[agent_id]
        fam = round10.BASE_FAMILY.get(agent_id, agent_id)
        if disc in used_disc:
            print(f"  skip {agent_id:22} -- {disc} seat already taken")
        elif fam in used_family:
            print(f"  skip {agent_id:22} -- base family {fam} already seated")
        elif len(seats) >= 4:
            print(f"  skip {agent_id:22} -- four seats already filled (cap)")
        else:
            seats.append(agent_id)
            used_disc.add(disc)
            used_family.add(fam)
            print(f"  SEAT {agent_id:22} ({disc})")

    print(f"\n== Round 11 ranked roster: {len(seats)} of a possible 4 ==")
    for i, agent_id in enumerate(seats, 1):
        print(f"  {i}. {agent_id}")
    print("  + ladder-qld-schd (seated outside the competition, unranked)")

    print("\n== Pre-committed expectations (ROUND-11-PLAN.md section 6) ==")
    b3, ar = live["B3-concentrated"]["median"], live["A-rotation"]["median"]
    lead = max(live, key=lambda k: live[k]["median"] or Decimal(-99))
    print(f"  1. B3-concentrated expected to lead the live matrix. Leader is {lead!r}.")
    print(f"     B3-concentrated {_pct(b3)} vs A-rotation {_pct(ar)} -> "
          f"{'HELD' if (b3 or Decimal(-99)) > (ar or Decimal(-99)) else 'CONTRADICTED'}")
    mom = [k for k in seats if round10.FIELD[k] == "momentum"]
    print(f"  2. Momentum seat decided by the rule: {mom[0] if mom else 'none seated'}")
    cut_by_c = [k for k in survivors_l if k not in survivors_c]
    print(f"  3. Gate C expected to eliminate at least one card. Eliminated: "
          f"{cut_by_c if cut_by_c else 'NOBODY -- gate is decorative on this field'}")
    print(f"  4. Seat count 2-4 expected. Got {len(seats)} -> "
          f"{'HELD' if 2 <= len(seats) <= 4 else 'CONTRADICTED'}")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "live_matrix": {k: {kk: _pct(vv) for kk, vv in v.items()} for k, v in cells.items()},
                    "live_summary": {k: {"median": _pct(v["median"]), "hits": v["hits"], "n": v["n"]}
                                     for k, v in live.items()},
                    "backtest_rank_range": spread,
                    "gate_a_pass": sorted(survivors_a),
                    "gate_l_pass": sorted(survivors_l),
                    "gate_c_pass": sorted(survivors_c),
                    "ranked": ranked,
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
