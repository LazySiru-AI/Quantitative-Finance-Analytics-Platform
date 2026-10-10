"""Re-run every frozen card from rounds 1-14 on today's engine, and measure the drift.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/rerun_matrix.py [--limit N] [--report]

WHAT THIS IS, AND WHAT IT IS EMPHATICALLY NOT
----------------------------------------------
This writes to `data/rounds/rerun-2026-08/`. It **never touches r1-r14's results trees**, and its
output is **not** those rounds' results.

`PROTOCOL.md` §6(a) forbids treating a re-run as new evidence, and the reason is structural rather
than fussy: Gate A reads round 5, Gate S' reads rounds 2, 4 and 5, rounds 6-12 are selection rounds
scored over those frozen matrices, and two of them ended in owner overrides argued from specific
figures in them. Re-scoring the matrices underneath would retroactively invalidate seven rounds of
reasoning and both overrides at once.

So this answers a different, narrower question, and the answer is interesting either way:

    **How much of the programme's recorded history is a property of the engine rather than of the
    strategies?**

The engine has moved since those rounds ran -- D1's rebasing correction, D2's `capital_exposure`
split from session-presence `exposure`, D4's full-history lookback, `_undilute_exposure`, and round
14's `rank_by`. A card is frozen; the machine that scores it is not. If re-running produces the same
numbers, the record is robust. If it does not, the size of the gap is the size of the caveat that
belongs on every cross-round comparison the programme has made.

DESIGN NOTES THAT MATTER FOR READING THE OUTPUT
------------------------------------------------
* **Deduplicated by (card, window).** A given card-and-window pair is deterministic, so the same
  pair appearing in three rounds is re-run once and compared against all three stored copies. 954
  distinct pairs across r1-r14, from 1,051 stored run files.

* **Each cell reuses its own original `starting_equity`**, read from the stored result rather than
  from today's `PURPOSE_SPECS`. The trading seed moved from $50,000 to $100,000 today; running an
  old cell at the new seed would fold a capital change into a measurement of engine drift and make
  every number here uninterpretable.

* **Resumable.** An hours-long serial run that cannot be resumed will be interrupted and restarted
  from zero. Every completed cell is skipped on a re-invocation.

* **Serial, deliberately.** The bar store does not take concurrent tournament runs, and a 16GB host
  binds on memory before it binds on anything else.

**Not investment advice.**
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import json
import pathlib
import statistics
import sys
import time
import traceback
from decimal import Decimal
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import windows as W

from app.config import get_settings
from app.paper.mandate import default_mandate
from app.tournament.allocation import AllocationCard, run_allocation
from app.tournament.ladder import LadderCard, run_ladder_card
from app.tournament.models import StrategyCard
from app.tournament.runner import run_card

REPO = pathlib.Path(__file__).resolve().parents[2]
ROUNDS = REPO / "data" / "rounds"
OUT = ROUNDS / "rerun-2026-08"

#: r15 is excluded: it ran on today's engine by construction, so it has no drift to measure.
SOURCE_ROUNDS = tuple(f"r{n}-2026-08" for n in range(1, 15))


@dataclasses.dataclass(frozen=True, slots=True)
class Cell:
    agent_id: str
    window: str
    shape: str
    payload: dict[str, Any]
    starting_equity: str
    stored: tuple[tuple[str, str], ...]  # (source round, stored total_return)


def collect() -> dict[tuple[str, str], Cell]:
    """Every distinct (card, window) in r1-r14, carrying every stored copy's return for comparison."""
    seen: dict[tuple[str, str], Cell] = {}
    extra: dict[tuple[str, str], list[tuple[str, str]]] = collections.defaultdict(list)
    for rd in SOURCE_ROUNDS:
        base = ROUNDS / rd / "results"
        if not base.is_dir():
            continue
        for f in sorted(base.glob("*/runs/*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            card = d.get("card") or {}
            aid = card.get("agent_id")
            window = f.parent.parent.name
            if not aid or window not in W.ALL_WINDOWS:
                continue
            key = (aid, window)
            extra[key].append((rd, str(d.get("total_return"))))
            if key in seen:
                continue
            shape = "ladder" if "signal_symbol" in card else ("alloc" if "sleeves" in card else "strategy")
            seen[key] = Cell(aid, window, shape, card, str(d.get("starting_equity")), ())
    return {k: dataclasses.replace(c, stored=tuple(extra[k])) for k, c in seen.items()}


def run_cell(cell: Cell, settings: Any) -> Any:
    start, end, _desc = W.ALL_WINDOWS[cell.window]
    mandate = dataclasses.replace(
        default_mandate(starting_cash=Decimal(cell.starting_equity)),
        max_single_name_weight=Decimal(1),
    )
    if cell.shape == "ladder":
        return run_ladder_card(LadderCard.model_validate(cell.payload), settings=settings, mandate=mandate, start=start, end=end)
    if cell.shape == "alloc":
        return run_allocation(AllocationCard.model_validate(cell.payload), settings=settings, mandate=mandate, start=start, end=end)
    return run_card(StrategyCard.model_validate(cell.payload), settings=settings, mandate=mandate, start=start, end=end)


def path_for(cell: Cell) -> pathlib.Path:
    return OUT / "results" / cell.window / "runs" / f"{cell.agent_id}.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="run at most N cells this invocation")
    ap.add_argument("--report", action="store_true", help="skip running; compare what already exists")
    args = ap.parse_args()

    settings = get_settings()
    cells = collect()
    todo = [c for c in cells.values() if not path_for(c).exists()]
    print(f"{len(cells)} distinct (card, window) cells across r1-r14; {len(todo)} not yet re-run", flush=True)

    if not args.report:
        budget = args.limit or len(todo)
        t0 = time.time()
        done = failed = 0
        for i, cell in enumerate(todo[:budget], 1):
            try:
                res = run_cell(cell, settings)
                p = path_for(cell)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(res.model_dump_json(indent=2), encoding="utf-8")
                done += 1
            except Exception as exc:
                failed += 1
                (OUT / "failures.log").parent.mkdir(parents=True, exist_ok=True)
                with (OUT / "failures.log").open("a", encoding="utf-8") as fh:
                    fh.write(f"{cell.agent_id}\t{cell.window}\t{type(exc).__name__}: {exc}\n")
                traceback.print_exc(limit=1)
            if i % 10 == 0 or i == budget:
                rate = (time.time() - t0) / i
                print(
                    f"  {i}/{budget}  ok={done} failed={failed}  {rate:.1f}s/cell  "
                    f"eta {(budget - i) * rate / 60:.0f}m",
                    flush=True,
                )

    # ---- comparison -------------------------------------------------------------------------
    drift: list[tuple[float, str, str, str, str]] = []
    missing = 0
    for cell in cells.values():
        p = path_for(cell)
        if not p.exists():
            missing += 1
            continue
        now = json.loads(p.read_text(encoding="utf-8"))
        new = now.get("total_return")
        for src, old in cell.stored:
            if old in (None, "None") or new is None:
                continue
            gap = (float(new) - float(old)) * 100
            drift.append((gap, cell.agent_id, cell.window, src, f"{float(old) * 100:.2f} -> {float(new) * 100:.2f}"))

    print()
    print(f"compared {len(drift)} stored copies; {missing} cells not yet re-run")
    if drift:
        gaps = [abs(g) for g, *_ in drift]
        exact = sum(1 for g in gaps if g < 1e-9)
        print(f"  identical to 1e-9 : {exact}/{len(gaps)} ({exact / len(gaps) * 100:.1f}%)")
        print(f"  median |drift|    : {statistics.median(gaps):.4f} pp")
        print(f"  mean   |drift|    : {statistics.fmean(gaps):.4f} pp")
        print(f"  worst  |drift|    : {max(gaps):.4f} pp")
        print()
        print("  largest movers:")
        for gap, aid, win, src, shown in sorted(drift, key=lambda r: -abs(r[0]))[:15]:
            print(f"    {gap:+8.2f} pp  {aid:26} {win:16} ({src})  {shown}")
        (OUT / "drift.json").write_text(
            json.dumps(
                {
                    "compared": len(drift),
                    "identical": exact,
                    "median_abs_pp": statistics.median(gaps),
                    "worst_abs_pp": max(gaps),
                    "rows": [
                        {"drift_pp": g, "agent_id": a, "window": w, "source_round": s, "old_to_new": t}
                        for g, a, w, s, t in sorted(drift, key=lambda r: -abs(r[0]))
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
