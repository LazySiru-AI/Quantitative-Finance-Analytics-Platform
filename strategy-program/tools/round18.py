"""Round 18: does the *exit* decide the result?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round18.py --write

`ROUND-18-PLAN.md` is the pre-registration this executes. Read it first.

The mirror of round 17. There, each form's entry and exit moved together and were one factor; here the
entry is pinned and only the exit varies, which is the only way to attribute a difference to the exit.

The entry is the loop's own hardcoded template -- `ma-crossover` with the regime filter on -- not round
17's best cell. Picking the winner of the previous round would be selecting on an outcome; the template
is the most-evidenced entry in this programme by a very large margin, having been the *only* entry the
evolution loop emitted for generations 1-1915.

**One pair is a deliberate duplicate.** The `ma-crossover` exit against this entry reproduces round
17's `ma-crossover-on-none` and `ma-crossover-on-stop` cells exactly. That is the round's built-in
regression check: if those two do not reproduce round 17's committed figures to the digit, the
instrument moved between the rounds and every comparison here is suspect. `verify_reproduction` below
performs that check against round 17's scorecard once results exist.

**Not investment advice.**
"""

from __future__ import annotations

import argparse
import json
import pathlib
from decimal import Decimal

from app.evolution import ruleforms
from app.evolution.models import RULE_SHAPES
from app.rules import grammar
from app.tournament.models import DESIGN_THROUGH, StrategyCard

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r18-2026-08" / "cards"

#: Round 17's Amendment 1 already applied: the two ETFs younger than the matrix are excluded from the
#: start, because a zero-bar symbol fails the whole card at the lookahead guard.
UNIVERSE: tuple[str, ...] = ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB")

FAST, SLOW, REGIME = 10, 30, 200

#: The loop's own template, regime filter on. See the module docstring for why this and not the winner.
FIXED_ENTRY = f"close > sma({REGIME}) and ema({FAST}) crosses_above ema({SLOW})"

#: Two levels, not three: round 17 measured `stop` and `stop-tp` as indistinguishable (both -1.96%).
BRACKETS: dict[str, dict[str, object]] = {
    "none": {"stop_loss_pct": None, "take_profit_pct": None, "max_hold_days": None},
    "stop": {"stop_loss_pct": Decimal("0.12"), "take_profit_pct": None, "max_hold_days": 180},
}

#: The cells that must reproduce round 17 exactly -> the round 17 agent_id they duplicate.
REPRODUCTION_PAIRS = {
    "r18-exit-ma-crossover-none": "r17-ma-crossover-on-none",
    "r18-exit-ma-crossover-stop": "r17-ma-crossover-on-stop",
}


def build() -> list[StrategyCard]:
    grammar.parse(FIXED_ENTRY)  # the entry is fixed; prove it parses once, loudly, before 16 cards use it
    cards: list[StrategyCard] = []

    for shape in RULE_SHAPES:
        _entry_unused, exit_rule = ruleforms.render(shape, fast=FAST, slow=SLOW, regime_ma=REGIME)
        grammar.parse(exit_rule)

        # Classified from the pair actually being traded -- this entry with *this* exit -- not from the
        # form the exit was borrowed from. A `band-reversion` exit on a trend entry is not a
        # mean-reversion card, and labelling it one would put a false discipline in the record.
        discipline = ruleforms.classify(FIXED_ENTRY, exit_rule)
        if discipline is None:
            raise SystemExit(f"classifier does not recognise the fixed entry with the {shape!r} exit")

        for bracket_name, bracket in BRACKETS.items():
            agent_id = f"r18-exit-{shape}-{bracket_name}"
            note = ""
            if agent_id in REPRODUCTION_PAIRS:
                note = (
                    " This cell is the round's regression check: it is identical to round 17's "
                    f"{REPRODUCTION_PAIRS[agent_id]} and must reproduce its figures to the digit."
                )
            cards.append(
                StrategyCard(
                    agent_id=agent_id,
                    display_name=f"fixed entry / exit {shape} / {bracket_name}",
                    discipline=discipline,
                    thesis=(
                        "Round 18 cell. The entry is pinned to the evolution loop's own hardcoded "
                        f"template -- {FIXED_ENTRY} -- and only the exit varies, so that any "
                        "difference is attributable to the exit alone. Round 17 found bracket policy "
                        "moved its whole 48-cell field by 0.14 percentage points, with many cells "
                        "byte-identical across bracket policies, because the rule's own exit fires "
                        f"first almost every time; this round isolates that. Exit borrowed from the "
                        f"{shape} form. Brackets: {bracket_name}. Not a proposal to trade anything; "
                        "nothing in this round is promotable. See "
                        "strategy-program/ROUND-18-PLAN.md for the pre-registration and the five "
                        "falsifiable predictions." + note
                    ),
                    universe=UNIVERSE,
                    entry=FIXED_ENTRY,
                    exit=exit_rule,
                    max_positions=6,
                    position_pct=Decimal("0.15"),
                    designed_through=DESIGN_THROUGH,
                    **bracket,  # type: ignore[arg-type]
                )
            )
    return cards


def verify_reproduction() -> int:
    """Check the two duplicate cells against round 17's committed scorecard.

    Run after scoring. A mismatch means the instrument moved between the two rounds -- a changed
    indicator, a changed bar store, a changed engine -- and every between-round comparison in the
    report is then suspect. Round 16 ran the identical check against round 15 and it is the reason
    that round's cash-constraint comparison can be trusted at all.
    """
    def load(path: pathlib.Path) -> dict[str, object]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = next(
            v for v in payload.values()
            if isinstance(v, list) and v and isinstance(v[0], dict) and "agent_id" in v[0]
        )
        return {r["agent_id"]: r for r in rows}

    r17 = load(REPO / "data/rounds/r17-2026-08/scorecard.json")
    r18 = load(REPO / "data/rounds/r18-2026-08/scorecard.json")

    failures = 0
    for new_id, old_id in REPRODUCTION_PAIRS.items():
        a, b = r18.get(new_id), r17.get(old_id)
        if a is None or b is None:
            print(f"  MISSING {new_id} or {old_id}")
            failures += 1
            continue
        for field in ("median_adjusted_excess", "worst_adjusted_excess", "hit_rate", "trades"):
            if a.get(field) != b.get(field):
                print(f"  MISMATCH {new_id}.{field}: {a.get(field)!r} != {old_id} {b.get(field)!r}")
                failures += 1
        if failures == 0:
            print(f"  OK {new_id} reproduces {old_id}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="author the field")
    parser.add_argument("--verify", action="store_true", help="check the two reproduction cells")
    args = parser.parse_args(argv)

    if args.verify:
        print("reproduction check against round 17:")
        return 1 if verify_reproduction() else 0

    cards = build()
    print(f"built {len(cards)} cards")
    print(f"  fixed entry: {FIXED_ENTRY}")
    for c in cards:
        if c.agent_id in REPRODUCTION_PAIRS:
            print(f"  regression cell: {c.agent_id} <- {REPRODUCTION_PAIRS[c.agent_id]}")
    if not args.write:
        print("\n(dry run -- pass --write to author the field)")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for c in cards:
        (OUT / f"{c.agent_id}.json").write_text(
            c.model_dump_json(indent=2, exclude_none=False) + "\n", encoding="utf-8"
        )
    print(f"\nwrote {len(cards)} cards to {OUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
