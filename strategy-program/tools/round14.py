"""Round 14's measurement: what naming the chooser is worth.

`strategy-program/ROUND-14-PLAN.md` (committed as `8767fa1`, before any run existed) is the
authority. The quantity it pre-registered is **not** which variant scores highest -- it is the
**spread between variants of one base card**, because that spread is what universe ordering was
silently contributing to every contested session in every round.

`app.tournament.runner._ordered_entry_candidates`: when more names qualify than there are slots, the
order the runner walks the universe in *is* the selection rule. Unranked, that order is the order
symbols were typed into a JSON array -- worth a measured 53.9-point spread over twelve orderings of
one identical card (`PROTOCOL.md` section 7). This round produces a second, independent estimate of
the same effect across five more cards.

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe \\
        strategy-program/tools/round14.py

**The control decides whether anything else may be read.** `c21-uncorrelated` holds six names in six
slots, so no slot can ever be contested and its ranked variant must produce results byte-identical to
its base. A non-zero divergence there means the harness is wrong, not that the key did something --
and every other figure in the round is then meaningless. Checked first, and loudly.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent))

import score

RESULTS = Path("data/rounds/r14-2026-08/results")

CONTENDERS = ["B3-concentrated", "c19-volatility", "B-momentum", "A-rotation", "C-trend"]
CONTROL = "c21-uncorrelated"
KEYS = ["rs", "lowvol", "stretch"]
KEY_LABEL = {
    "": "unranked (universe order)",
    "rs": "relative strength",
    "lowvol": "lowest volatility",
    "stretch": "stretch in ATR units",
}


def medians(tags: list[str]) -> dict[str, Decimal | None]:
    """Each staged card's median adjusted excess over the windows it actually ran.

    Non-annualized: round 2's eight windows are all comparably-sized regime windows, so a raw median
    compares like with like -- unlike round 5's ladder, which mixes 6-month and 10-year rungs.
    """
    by_window = score.load_results(RESULTS, "r1", tags)
    per: dict[str, list[Decimal]] = {}
    for agents in by_window.values():
        for agent_id, result in agents.items():
            value = score.adjusted_excess(result)
            if value is not None:
                per.setdefault(agent_id, []).append(value)
    return {a: (median(v) if v else None) for a, v in per.items()}


def _pct(v: Decimal | float | None) -> str:
    return "n/a" if v is None else f"{float(v) * 100:+.2f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    tags = [t for t in score.MAIN_WINDOW_TAGS]
    med = medians(tags)

    print(f"== round 14: {len(med)} cards scored over {len(tags)} regime windows ==")
    print(f"   windows: {', '.join(tags)}\n")

    # --- the control, first, because it gates everything else ------------------------------------
    base_c = med.get(CONTROL)
    var_c = med.get(f"{CONTROL}-rs")
    print("== CONTROL -- c21-uncorrelated, 6 names in 6 slots, no slot can be contested ==")
    if base_c is None or var_c is None:
        print(f"  !! missing: base={base_c} ranked={var_c} -- cannot verify the harness")
        control_ok = False
        divergence = None
    else:
        divergence = var_c - base_c
        control_ok = divergence == 0
        print(f"  base   {_pct(base_c)}")
        print(f"  ranked {_pct(var_c)}")
        print(f"  divergence {_pct(divergence)}  ->  {'PASS' if control_ok else 'FAIL'}")
    if not control_ok:
        print("\n  Every other figure below is unreadable until this is zero. Stopping the read here")
        print("  is the pre-registered response, not a judgement made after seeing the numbers.\n")

    # --- the spread, which is the point ----------------------------------------------------------
    print("\n== SPREAD per base card: what the choice of chooser is worth ==")
    header = f"{'base card':20}" + "".join(f"{KEY_LABEL[k][:11]:>13}" for k in ["", *KEYS])
    print(header + f"{'spread':>10}{'best':>12}")
    rows = {}
    for base in CONTENDERS:
        vals = {"": med.get(base)}
        for k in KEYS:
            vals[k] = med.get(f"{base}-{k}")
        present = {k: v for k, v in vals.items() if v is not None}
        spread = (max(present.values()) - min(present.values())) if len(present) > 1 else None
        best = max(present, key=lambda k: present[k]) if present else None
        rows[base] = {
            "values": {k: (float(v) if v is not None else None) for k, v in vals.items()},
            "spread_pts": float(spread * 100) if spread is not None else None,
            "best_key": best,
        }
        cells = "".join(f"{_pct(vals[k]):>13}" for k in ["", *KEYS])
        print(
            f"{base:20}{cells}{_pct(spread):>10}"
            f"{(KEY_LABEL[best][:11] if best is not None else 'n/a'):>12}"
        )

    spreads = [r["spread_pts"] for r in rows.values() if r["spread_pts"] is not None]
    wins: dict[str, int] = {}
    for r in rows.values():
        if r["best_key"] is not None:
            wins[r["best_key"]] = wins.get(r["best_key"], 0) + 1

    print("\n== against the pre-committed expectations (ROUND-14-PLAN.md section 6) ==")
    print(
        f"  1. control diverges by exactly 0  ->  "
        f"{'HELD' if control_ok else 'CONTRADICTED'} ({_pct(divergence)} pts)"
    )
    if spreads:
        under = sum(1 for s in spreads if s < 53.9)
        print(
            f"  2. spread under 53.9 pts on most cards  ->  "
            f"{'HELD' if under > len(spreads) / 2 else 'CONTRADICTED'} "
            f"({under} of {len(spreads)}; max {max(spreads):.2f}, median {median(spreads):.2f})"
        )
        small = sum(1 for s in spreads if s < 5)
        print(
            f"  4. at least one base spreads under 5 pts  ->  "
            f"{'HELD' if small else 'CONTRADICTED'} ({small} of {len(spreads)})"
        )
    print(
        f"  3. no single key wins on every base  ->  "
        f"{'HELD' if len(wins) > 1 else 'CONTRADICTED'} "
        f"({ {KEY_LABEL[k]: n for k, n in wins.items()} })"
    )

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "windows": tags,
                    "control": {
                        "agent": CONTROL,
                        "base": float(base_c) if base_c is not None else None,
                        "ranked": float(var_c) if var_c is not None else None,
                        "divergence": float(divergence) if divergence is not None else None,
                        "passed": control_ok,
                    },
                    "bases": rows,
                    "key_wins": wins,
                    "spreads_pts": spreads,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
