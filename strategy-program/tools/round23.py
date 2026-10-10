"""Round 23: the curve as a *sizing* input, not a gate.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round23.py --write --run

`ROUND-23-PLAN.md` is the pre-registration this executes, including Amendment 1. Read it first.

Round 22 answered the entry-gate question with a clean null and named the sizing variant as untouched.
`TiltRule.shift_expr` -- which did not exist when the consolidated report ranked continuous sizing the
programme's #2 outstanding change -- makes it expressible, so this round asks it.

Three arms on one derived card (Amendment 1: the seated card's own price tilts are stripped, so the
curve tilt is the only rule and a B-vs-C difference cannot be an interaction with `bb_upper`):

    A  control   no tilt
    B  binary    macro(T10Y2Y) < 0, shift_pct 0.172
    C  sized     macro(T10Y2Y) < 0, shift_expr "-0.5 * macro(T10Y2Y)"

**B's constant is C's pooled mean shift, computed from the pinned series before any card ran** (plan
section 2a). The two arms therefore move the same average weight and differ only in how it is
distributed across sessions -- without which a B/C difference would be a difference in magnitude
wearing the name of a difference in gradation.

**Not investment advice.**
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import pathlib
from decimal import Decimal

from app.config import get_settings
from app.paper.mandate import default_mandate
from app.tournament.allocation import AllocationCard, run_allocation

REPO = pathlib.Path(__file__).resolve().parents[2]

BASE = REPO / "backend" / "app" / "paper" / "library" / "allocation" / "qld-schd-sgov.json"
OUT = REPO / "data" / "rounds" / "r23-2026-08"

#: Amendment 2. The base card's own sleeves (QLD 2006-06, SCHD 2011-10, SGOV 2020-05) do not exist in
#: two of the three windows -- and the engine reported that as `+0.00% on 0 trades` rather than
#: refusing, so it had to be caught by reading first bars rather than by a failure. These three all
#: start 1998-12-21 and cover every window in the set.
SLEEVES = (("XLK", "0.35"), ("XLP", "0.40"), ("XLU", "0.25"))
TILT_FROM, TILT_TO = "XLK", "XLP"

#: The macro pin round 21 froze. Without it `_guard_allocation_card` fails closed, deliberately: FRED
#: serves revised values against the same reference dates, so an unpinned run is reproducible in its
#: dates and not in its answers.
MACRO_PIN = REPO / "data" / "rounds" / "r21-2026-08" / "macro-pin.json"

#: Round 22's, reused unchanged -- selected on the treatment, not the outcome. See plan section 3.
WINDOWS: tuple[tuple[str, dt.date, dt.date], ...] = (
    ("inv-2000", dt.date(1999, 6, 1), dt.date(2001, 6, 29)),
    ("inv-2006", dt.date(2006, 3, 1), dt.date(2007, 12, 31)),
    ("inv-2022", dt.date(2022, 1, 3), dt.date(2024, 12, 31)),
)

CAPITAL = Decimal("100000")

#: Both numbers are properties of the pinned series, computed before any card ran. See plan 2a.
BINARY_SHIFT = "0.172"
SIZED_EXPR = "-0.5 * macro(T10Y2Y)"

ARMS = {
    "a-control": None,
    "b-binary": {"shift_pct": BINARY_SHIFT},
    "c-sized": {"shift_expr": SIZED_EXPR},
}


def build() -> dict[str, AllocationCard]:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    cards: dict[str, AllocationCard] = {}
    for arm, tilt in ARMS.items():
        payload = dict(base)
        payload["sleeves"] = [
            {"symbol": sym, "target_weight": w} for sym, w in SLEEVES
        ]
        payload["agent_id"] = f"r23-{arm}"
        payload["display_name"] = f"Round 23 {arm}"
        # Amendment 1: the seated card's two price tilts are dropped in every arm, so the curve tilt
        # is the only rule and the B-vs-C comparison measures gradation rather than an interaction.
        payload["rules"] = []
        if tilt is not None:
            payload["rules"] = [
                {
                    "condition": "macro(T10Y2Y) < 0",
                    "on_symbol": TILT_FROM,
                    "from_symbol": TILT_FROM,
                    "to_symbol": TILT_TO,
                    **tilt,
                }
            ]
        payload["thesis"] = (
            "Round 23 arm. A static 35/40/25 XLK/XLP/XLU allocation, rotating out of technology into "
            "consumer staples as the US yield curve inverts. Arm A applies no tilt; arm B applies a constant "
            f"{BINARY_SHIFT} shift whenever the curve is inverted; arm C sizes the shift by how "
            f"inverted it is ({SIZED_EXPR}). B's constant is C's pooled mean shift over firing "
            "sessions, computed from the pinned series before any card ran, so the two arms move the "
            "same average weight and differ only in how it is distributed. A purpose-built three-sector "
            "allocation (plan Amendments 1 and 2); it bears on no seated card's record. Not a proposal to trade anything; nothing in this round "
            "is promotable. See strategy-program/ROUND-23-PLAN.md."
        )
        cards[arm] = AllocationCard.model_validate(payload)
    return cards


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="author the arms")
    parser.add_argument("--run", action="store_true", help="run them over the three windows")
    args = parser.parse_args(argv)

    cards = build()
    print(f"built {len(cards)} arms from {BASE.name}")
    for arm, c in cards.items():
        rule = c.rules[0] if c.rules else None
        desc = "no tilt" if rule is None else (
            f"{rule.condition}  {rule.from_symbol}->{rule.to_symbol}  "
            f"{'shift_pct=' + str(rule.shift_pct) if rule.shift_pct is not None else 'shift_expr=' + str(rule.shift_expr)}"
        )
        print(f"  {arm:10s} {desc}")

    if args.write:
        (OUT / "cards").mkdir(parents=True, exist_ok=True)
        for _arm, c in cards.items():
            (OUT / "cards" / f"{c.agent_id}.json").write_text(
                c.model_dump_json(indent=2, exclude_none=False) + "\n", encoding="utf-8"
            )
        print(f"\nwrote {len(cards)} cards to {(OUT / 'cards').relative_to(REPO).as_posix()}")

    if not args.run:
        print("\n(pass --run to execute)")
        return 0

    # Fail-closed guard: set before the first run_allocation call, not in the shell, so the tool
    # cannot be invoked in a state where it silently reads live FRED values.
    import os
    os.environ.setdefault("INVDASH_MACRO_PIN", str(MACRO_PIN))
    print(f"macro pin: {MACRO_PIN.relative_to(REPO).as_posix()}")

    mandate = dataclasses.replace(
        default_mandate(starting_cash=CAPITAL),
        max_single_name_weight=Decimal(1),
        allow_fractional_shares=True,
    )
    settings = get_settings()
    results: dict[str, dict[str, dict[str, float]]] = {}

    print()
    for tag, start, end in WINDOWS:
        print(f"--- {tag}  {start} -> {end} ---")
        results[tag] = {}
        for arm, card in cards.items():
            r = run_allocation(card, settings=settings, mandate=mandate, start=start, end=end)
            results[tag][arm] = {
                "ending_equity": float(r.ending_equity),
                "total_return": float(r.total_return) * 100,
                "max_drawdown": float(r.max_drawdown) * 100,
                "capital_exposure": float(r.capital_exposure or 0) * 100,
                "trades": len(r.trades),
                "rejections": len(r.rejections),
            }
            m = results[tag][arm]
            print(
                f"  {arm:10s} return {m['total_return']:+8.2f}%   maxDD {m['max_drawdown']:+7.2f}%   "
                f"exposure {m['capital_exposure']:5.1f}%   trades {m['trades']:3d}   rej {m['rejections']}"
            )
        a, b, c = (results[tag][k]["total_return"] for k in ("a-control", "b-binary", "c-sized"))
        print(f"    |A-B| {abs(a-b):6.2f}pp   |A-C| {abs(a-c):6.2f}pp   |B-C| {abs(b-c):6.2f}pp")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {(OUT / 'results.json').relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
