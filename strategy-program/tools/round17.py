"""Round 17: does strategy *form* matter, holding everything else fixed?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round17.py --write

`ROUND-17-PLAN.md` is the pre-registration this executes. Read it first.

This authors the round's field and nothing else -- the cards are then run by
`strategy-program/tools/run_round.sh` and scored by `score.py`, exactly like every other card round.

**Why the field is generated rather than hand-written.** The eight rule forms are already defined,
in code, in `app.evolution.ruleforms.RENDERERS`, and have been since 2026-08-26. Re-typing them into
48 JSON files by hand would create a second, drifting copy of a vocabulary that already exists, and
the whole point of this round is that the eight forms are compared *as the loop actually emits them*.
So the entry and exit strings come from `ruleforms.render` and the discipline label from
`ruleforms.classify`, which is the same derivation the evolution loop uses.

**The three factors, and why each is a factor rather than a constant.**

* `rule_shape` (8 levels) -- the variable this round exists to isolate. Every previous round varied
  form together with universe and parameters, so no measurement of form alone exists. The evolution
  loop varied parameters *within one form* for generations 1-1915 and has only run ten generations
  under the eight-form vocabulary, none of which has cleared a gate.
* `regime` (2 levels: `on`/`off`) -- six of the eight forms carry a `close > sma(200)` conjunct, and
  no round has ever measured what that filter is worth. Stripping it is the paired half.
* `brackets` (3 levels: `none`/`stop`/`stop-tp`) -- `B-momentum`'s thesis claims a take-profit
  amputates this kind of edge ("capping gains at 8-30% cut mean per-signal return to 2-9%"), which is
  a claim about brackets made from one card's design study and never tested across forms.

8 x 2 x 3 = 48 cells. Every other input is held identical: one mechanically-defined universe, one
position size, one slot count, one set of periods.

**The universe is the eleven sector SPDRs, and that choice is load-bearing.** `PROGRAMME-REPORT.md`'s
own closing section concedes that every long-horizon figure in this programme is an unmeasured upper
bound, because the survivorship gate does not catch a universe picked from an analyst's thesis. The
GICS sector ETFs are mechanically defined, do not die, and were not chosen by looking at returns --
which removes stock selection from the comparison entirely. Two of them are younger than the matrix:
`XLRE` starts 2015-10-07 and `XLC` 2018-06-18, so the `gfc` and `chop-2011` windows see nine names
rather than eleven. That is identical for all 48 cards, so it cannot favour a form.

**Nothing here is tuned.** `fast`/`slow`/`regime_ma` are 10/30/200 and every threshold inside a form
(RSI 40/60, Bollinger 2 sigma, MACD's 9-bar signal, the 2%/5% ATR band) is the textbook setting frozen
in `ruleforms.py` before this round was conceived. `designed_through` is the programme's own
`DESIGN_THROUGH` cutoff. No parameter in this field was chosen by looking at an outcome.

**Not investment advice.**
"""

from __future__ import annotations

import argparse
import pathlib
from decimal import Decimal

from app.evolution import ruleforms
from app.evolution.models import RULE_SHAPES
from app.rules import grammar
from app.tournament.models import DESIGN_THROUGH, StrategyCard

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r17-2026-08" / "cards"

#: Mechanically defined, survivorship-free, and not chosen by looking at returns. See the docstring.
UNIVERSE: tuple[str, ...] = (
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB",
)
#: Amendment 1 (2026-08-30). `XLRE` and `XLC` were in the pre-registered universe and are not here.
#: They launched 2015-10-07 and 2018-06-18, so they hold **zero** bars in `gfc`, `chop-2011` and
#: `chop-2015` -- and a zero-bar symbol does not merely contribute nothing, it fails the whole card:
#: the lookahead guard cannot demonstrate causality against a series with no post-warmup region and
#: refuses rather than passing on no evidence. The first attempt therefore returned 0 of 48 runs in
#: those three windows and 21 of 48 in `q4-2018`. See `ROUND-17-PLAN.md` §8.
EXCLUDED_FOR_HISTORY: tuple[str, ...] = ("XLRE", "XLC")

FAST, SLOW, REGIME = 10, 30, 200

#: The regime conjunct every form that has one carries, in the exact text `render` emits.
REGIME_CLAUSE = f"close > sma({REGIME})"

BRACKETS: dict[str, dict[str, object]] = {
    # No brackets at all: the rule's own exit is the only way out. The control.
    "none": {"stop_loss_pct": None, "take_profit_pct": None, "max_hold_days": None},
    # A stop and a time backstop, no target -- the shape `B-momentum` argues for.
    "stop": {"stop_loss_pct": Decimal("0.12"), "take_profit_pct": None, "max_hold_days": 180},
    # ...and the target it argues against.
    "stop-tp": {
        "stop_loss_pct": Decimal("0.12"),
        "take_profit_pct": Decimal("0.25"),
        "max_hold_days": 180,
    },
}


def strip_regime(entry: str) -> str | None:
    """`entry` with its `close > sma(200)` conjunct removed, or `None` if it has none.

    String surgery on a rendered rule, then re-parsed -- never a hand-written second copy of the
    rule. `render` emits the conjunct in one of two positions depending on the form (leading for
    `ma-crossover`, trailing for `channel-breakout`), so both are handled and the result is validated
    by the real grammar before it is allowed into a card. A form whose regime clause cannot be
    removed cleanly is dropped from the `off` arm and reported, rather than being approximated.
    """
    for candidate in (
        entry.replace(f"{REGIME_CLAUSE} and ", "", 1),
        entry.replace(f" and {REGIME_CLAUSE}", "", 1),
    ):
        if candidate != entry:
            grammar.parse(candidate)  # raises if the surgery produced nonsense
            return candidate
    return None


def build() -> tuple[list[StrategyCard], list[str]]:
    cards: list[StrategyCard] = []
    skipped: list[str] = []

    for shape in RULE_SHAPES:
        entry_on, exit_rule = ruleforms.render(shape, fast=FAST, slow=SLOW, regime_ma=REGIME)
        entry_off = strip_regime(entry_on)
        described = ruleforms.describe(shape, fast=FAST, slow=SLOW, regime_ma=REGIME)

        for regime_state in ("on", "off"):
            entry = entry_on if regime_state == "on" else entry_off
            if entry is None:
                skipped.append(f"{shape}/regime-off: form carries no {REGIME_CLAUSE!r} conjunct")
                continue

            discipline = ruleforms.classify(entry, exit_rule)
            if discipline is None:
                skipped.append(f"{shape}/regime-{regime_state}: classifier does not recognise the rule")
                continue

            for bracket_name, bracket in BRACKETS.items():
                agent_id = f"r17-{shape}-{regime_state}-{bracket_name}"
                cards.append(
                    StrategyCard(
                        agent_id=agent_id,
                        display_name=f"{shape} / regime {regime_state} / {bracket_name}",
                        discipline=discipline,
                        thesis=(
                            f"Round 17 factorial cell. Form: {described}"
                            # `describe` always names the regime filter, because the canonical form
                            # carries one. On the `off` arm that would make the card's own prose
                            # contradict its own entry rule, so the removal is stated explicitly
                            # rather than left to a reader to notice.
                            + (
                                " -- but with the 200-day SMA regime filter REMOVED for this cell, "
                                "which is the paired half of this round's second factor."
                                if regime_state == "off"
                                else "."
                            )
                            + f" Brackets: {bracket_name}. This card is one cell of a "
                            "pre-registered 8x2x3 grid whose only purpose is to measure whether "
                            "strategy form, the regime filter and the bracket policy each change a "
                            "result by more than this programme's own measured noise floor of 21.2 "
                            "percentage points. It is not a proposal to trade anything. Every "
                            "parameter is the textbook constant frozen in app.evolution.ruleforms "
                            "before this round was conceived; nothing here was tuned, and the "
                            "universe is the mechanically defined GICS sector ETF set rather than "
                            "any thesis-picked list, so that stock selection cannot flatter a form. "
                            "See strategy-program/ROUND-17-PLAN.md for the pre-registration, the "
                            "five falsifiable predictions and the correction applied across all "
                            "cells."
                        ),
                        universe=UNIVERSE,
                        entry=entry,
                        exit=exit_rule,
                        max_positions=6,
                        position_pct=Decimal("0.15"),
                        designed_through=DESIGN_THROUGH,
                        **bracket,  # type: ignore[arg-type]
                    )
                )
    return cards, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the cards to the round directory")
    args = parser.parse_args(argv)

    cards, skipped = build()

    print(f"built {len(cards)} cards over {len(RULE_SHAPES)} forms")
    for note in skipped:
        print(f"  skipped: {note}")

    by_discipline: dict[str, int] = {}
    for card in cards:
        by_discipline[str(card.discipline)] = by_discipline.get(str(card.discipline), 0) + 1
    print("  derived disciplines:", by_discipline)

    if not args.write:
        print("\n(dry run -- pass --write to author the field)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    for card in cards:
        path = OUT / f"{card.agent_id}.json"
        path.write_text(card.model_dump_json(indent=2, exclude_none=False) + "\n", encoding="utf-8")
    print(f"\nwrote {len(cards)} cards to {OUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
