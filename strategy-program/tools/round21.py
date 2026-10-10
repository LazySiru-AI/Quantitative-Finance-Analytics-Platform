"""Round 21: does a macro series knowable at decision time change a card's result?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round21.py --write

`ROUND-21-PLAN.md` is the pre-registration this executes. Read it first.

Four structurally-chosen forms x macro gate on/off = **8 ranked cells**. The forms are one per entry
mechanism the vocabulary contains -- a crossing trend rule, a mean-reversion oscillator, a
price-structure breakout, a volatility-regime entry -- selected from the taxonomy without reference
to round 17's *performance* ordering of the eight. `momentum-state` is excluded because round 18
proved its exit byte-identical to `ma-crossover`'s, so it is not an independent level; the two
Bollinger variants and `macd-cross` are excluded as counterparts of forms already present.

**The gate is `macro(T10Y2Y) > 0`** -- the curve is not inverted. Chosen because it is the one
candidate series that is a *spread* rather than a trending level (`PCEPI`, `PCEPILFE` and `CPILFESL`
roughly triple in nominal terms across this window matrix, so a bare threshold on one is a date test
wearing a regime test's clothes), and because it applies identically to every symbol on a given date
regardless of that symbol's own history -- which is what makes it a market-regime overlay rather than
a per-symbol indicator. `> 0` is set by the concept, not fitted: zero is the only value on this scale
that is not a parameter choice.

**One cell is a deliberate duplicate.** `r21-ma-crossover-off` is byte-identical in construction to
round 17's `r17-ma-crossover-on-none`. If it does not reproduce that cell's committed figures to the
digit, the instrument moved between the rounds and every comparison here is suspect --
`verify_reproduction` performs that check once results exist, the same check round 18 ran against
round 17.

**This round requires a macro pin.** `INVDASH_MACRO_PIN` must point at
`data/rounds/r21-2026-08/macro-pin.json` for every run; the guard fails closed without it, so a
forgotten export produces refusals rather than silently-live-fetched results.

**Not investment advice.**
"""

from __future__ import annotations

import argparse
import json
import pathlib
from decimal import Decimal

from app.evolution import ruleforms
from app.rules import grammar
from app.tournament.models import DESIGN_THROUGH, StrategyCard

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r21-2026-08" / "cards"
PIN = REPO / "data" / "rounds" / "r21-2026-08" / "macro-pin.json"

#: Round 17's Amendment 1 already applied: the two ETFs younger than the matrix are excluded from the
#: start, because a zero-bar symbol fails the whole card at the lookahead guard.
UNIVERSE: tuple[str, ...] = ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB")

FAST, SLOW, REGIME = 10, 30, 200

#: One per entry mechanism, chosen from the taxonomy before any round-21 data existed. See the module
#: docstring for what is excluded and why.
FORMS: tuple[str, ...] = ("ma-crossover", "rsi-pullback", "channel-breakout", "vol-compression")

#: The gate, appended to the entry. Nothing else about a cell changes between `on` and `off`.
MACRO_GATE = "macro(T10Y2Y) > 0"

#: The cell that must reproduce round 17 exactly -> the round 17 agent_id it duplicates.
REPRODUCTION_PAIRS = {"r21-ma-crossover-off": "r17-ma-crossover-on-none"}


def build() -> list[StrategyCard]:
    cards: list[StrategyCard] = []
    for form in FORMS:
        entry, exit_rule = ruleforms.render(form, fast=FAST, slow=SLOW, regime_ma=REGIME)
        grammar.parse(entry)
        grammar.parse(exit_rule)

        # Classified from the ungated pair. The gate is a market-regime conjunct, not a change of
        # discipline -- a trend card that additionally requires an un-inverted curve is still a trend
        # card, and letting the classifier see the conjunct would either fail to recognise it or
        # invent a discipline the card does not have.
        discipline = ruleforms.classify(entry, exit_rule)
        if discipline is None:
            raise SystemExit(f"classifier does not recognise the {form!r} entry/exit pair")

        for gate in ("off", "on"):
            gated_entry = f"{entry} and {MACRO_GATE}" if gate == "on" else entry
            grammar.parse(gated_entry)
            agent_id = f"r21-{form}-{gate}"
            note = ""
            if agent_id in REPRODUCTION_PAIRS:
                note = (
                    " This cell is the round's regression check: it is identical in construction to "
                    f"round 17's {REPRODUCTION_PAIRS[agent_id]} and must reproduce its figures to "
                    "the digit."
                )
            cards.append(
                StrategyCard(
                    agent_id=agent_id,
                    display_name=f"{form} / macro gate {gate}",
                    discipline=discipline,
                    thesis=(
                        "Round 21 cell. Everything except the macro conjunct is held identical "
                        f"across the gate-on and gate-off pair, so any difference is attributable "
                        f"to the gate alone. Gate: {MACRO_GATE if gate == 'on' else 'none'}. This is "
                        "the first round in this programme whose cards can read a non-price field at "
                        "all -- FRED series were collected and displayed but unreachable by any card "
                        "until 2026-08-30. The honest prior, stated before the data: this finds "
                        "nothing, on a base rate of ~50 concepts and near-zero survivors. It is worth "
                        "running because the class was unreachable, not because it is likely to win. "
                        "Nothing in this round is promotable. See "
                        "strategy-program/ROUND-21-PLAN.md for the pre-registration, the "
                        "circular-shift null and the five falsifiable predictions." + note
                    ),
                    universe=UNIVERSE,
                    entry=gated_entry,
                    exit=exit_rule,
                    max_positions=6,
                    position_pct=Decimal("0.15"),
                    designed_through=DESIGN_THROUGH,
                    stop_loss_pct=None,
                    take_profit_pct=None,
                    max_hold_days=None,
                )
            )
    return cards


def verify_reproduction() -> int:
    """Check the duplicate cell against round 17's committed scorecard.

    Run after scoring. A mismatch means the instrument moved between the two rounds -- a changed
    indicator, a changed bar store, a changed engine -- and every between-round comparison in the
    report is then suspect.
    """

    def load(path: pathlib.Path) -> dict[str, object]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = next(
            v
            for v in payload.values()
            if isinstance(v, list) and v and isinstance(v[0], dict) and "agent_id" in v[0]
        )
        return {r["agent_id"]: r for r in rows}

    r17 = load(REPO / "data/rounds/r17-2026-08/scorecard.json")
    r21 = load(REPO / "data/rounds/r21-2026-08/scorecard.json")

    failures = 0
    for new_id, old_id in REPRODUCTION_PAIRS.items():
        a, b = r21.get(new_id), r17.get(old_id)
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
    parser.add_argument("--verify", action="store_true", help="check the reproduction cell")
    args = parser.parse_args(argv)

    if args.verify:
        print("reproduction check against round 17:")
        return 1 if verify_reproduction() else 0

    if not PIN.is_file():
        raise SystemExit(
            f"macro pin missing at {PIN.relative_to(REPO).as_posix()}; this round cannot run "
            f"unpinned -- see ROUND-21-PLAN.md section 2c"
        )

    cards = build()
    print(f"built {len(cards)} cards ({len(FORMS)} forms x 2 gate states)")
    for c in cards:
        flag = "  <- regression cell" if c.agent_id in REPRODUCTION_PAIRS else ""
        print(f"  {c.agent_id:28s} {c.entry}{flag}")
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
