"""Round 35: does the rotation shape carry information when the axis is *country* rather than sector?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round35.py --write

`strategy-program/ROUND-35-PLAN.md` is the pre-registration this file executes. Read it first; this
module authors the field and nothing else. The cards are then run by
`strategy-program/tools/run_round.sh` and scored by `score.py`, exactly like every other card round.

**The question.** `backend/app/paper/library/candidates/c20-rotation.json` is this programme's
"rotation" shape: one *absolute* per-symbol trend filter applied identically across a small set of
economically opposed ETFs, with a binding slot cap doing the actual rotating -- the engine has no
cross-symbol operator, so "rotation" is produced by the universe plus the cap, never by a rule that
compares one symbol to another. That shape has only ever been pointed at **sectors**. This round
points it at **countries**: eight single-country and regional equity ETFs, a dispersion source the
programme has never measured, on tickers the taxable book cannot use.

**The binding constraint, and why this round exists on this universe at all.** Every ticker here must
be absent from every `savings`- or `trading`-purpose card in the live library, because these cards
carry `purpose = Purpose.ROTH` and Rev. Rul. 2008-5 does not merely *defer* a wash-sale loss when the
replacement is bought inside an IRA -- it destroys it outright. `app.tournament.purposes.
find_disjointness_violations` is the invariant; this module checks the field against the live library
at build time and **refuses `--write` on any violation** rather than leaving that to a reviewer. The
claimed-ticker set is recomputed from the library on every run (strategy cards through
`app.tournament.results.load_library`, plus the `allocation/` and `ladder/` tiers that `load_library`
does not walk), never hardcoded, so a card committed by another session between two runs of this tool
moves the answer instead of being missed.

**Ticker disjointness is necessary and not sufficient, and this module does not claim otherwise.**
IRC section 1091 turns on *substantially identical* securities, which is a question about what a fund
holds, not about its ticker. `VWO` (FTSE Emerging Markets) is a different index from the taxable
book's `EEM` (MSCI Emerging Markets) and the two are not the same security -- but their economic
exposure is close, and `ILF` is roughly 60% Brazil while the taxable book holds `EWZ`. The disjoint
roster is what makes an accidental *identical* repurchase impossible; it is not a ruling that the
roster is section 1091-safe, and nothing in this round should be read as one. This is the same
boundary `purposes.py` draws in its own docstring, restated here rather than assumed.

**The universe is not eight independent bets.** `EFA` (MSCI EAFE) contains `EWJ`, `EWG` and `EWU`
among its largest weights, and `VWO` overlaps the emerging-market half of nothing else here only
because `EEM` is excluded. That redundancy is left in and *counted against* the field: Benjamini-
Hochberg correction runs over every cell this round runs, and correlated cells buy no extra evidence
while still spending denominator. The response to that is emphatically **not** to add cells to
compensate -- the field stays at nine.

**Not investment advice.** Every number this round will produce is a backtest on price-only bars with
no dividends, measured against a US benchmark. The honest prior, stated in the plan's section 6, is
that the rotation cells all post negative adjusted excess.
"""

from __future__ import annotations

import argparse
import pathlib
import re
from decimal import Decimal
from typing import Any

from app.rules import grammar
from app.tournament.allocation import AllocationCard
from app.tournament.ladder import LadderCard
from app.tournament.models import DESIGN_THROUGH, StrategyCard
from app.tournament.purposes import Purpose, find_disjointness_violations
from app.tournament.results import load_library

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r35-2026-09" / "cards"

LIBRARY_ROOT = REPO / "backend" / "app" / "paper" / "library"

#: Tiers `app.tournament.results.load_library` does **not** walk. `TIERS` there is
#: `base/variants/candidates/retired` and holds `StrategyCard`s only, so an allocation sleeve or a
#: ladder rung -- both of which buy real lots and therefore both of which can destroy a loss under
#: Rev. Rul. 2008-5 exactly as an entry rule can -- would be invisible to a disjointness check built
#: on `load_library` alone. Five taxable-claimed tickers (`AGG`, `BIL`, `QLD`, `SCHD`, `SGOV`) exist
#: *only* in these two directories.
EXTRA_TIERS: tuple[tuple[str, type[AllocationCard] | type[LadderCard]], ...] = (
    ("allocation", AllocationCard),
    ("ladder", LadderCard),
)

#: Pinned before any measurement and not to be changed: iShares Japan, Germany, UK, Canada and South
#: Korea, iShares Latin America 40, iShares MSCI EAFE and Vanguard FTSE Emerging Markets. First
#: stored daily bars are 1996-03-18 (`EWJ`/`EWG`/`EWU`/`EWC`), 2000-05-12 (`EWY`), 2001-08-27
#: (`EFA`), 2001-10-26 (`ILF`) and 2005-03-10 (`VWO`) -- so `VWO` is the binding symbol and it clears
#: `gfc` (2007-10-09) with a 200-day indicator by more than two years. Verified with
#: `strategy-program/tools/windows.py --cards data/rounds/r35-2026-09/cards`, which is the run this
#: round's definition of done requires rather than an assertion made here.
UNIVERSE: tuple[str, ...] = ("EWJ", "EWG", "EWU", "EWC", "EWY", "ILF", "EFA", "VWO")

#: Excluded and named, so nobody has to rediscover why the obvious members are absent: `EEM`, `EWZ`,
#: `FXI` and `INDA` are all single-country/regional equity ETFs that belong in a country-rotation
#: universe on the merits, and all four are claimed by the taxable book. They are out on the
#: disjointness invariant, not on anything measured.
EXCLUDED_TAXABLE_CLAIMED: tuple[str, ...] = ("EEM", "EWZ", "FXI", "INDA")

# ---------------------------------------------------------------------------
# The two entry forms. Neither was authored here; both are transplanted verbatim.
# ---------------------------------------------------------------------------

#: `c20-rotation`'s absolute per-symbol filter, character for character. Transplanting it rather than
#: restating it is the whole point: the round asks whether *this* shape carries information on a
#: different axis, so a re-tuned version of it would answer a different question. Frozen 2026-02-13.
ABSOLUTE_ENTRY = "close > sma(100) and rsi(14) > 50 and rsi(14) < 75"
ABSOLUTE_EXIT = "close < sma(100) or rsi(14) < 40"

#: The evolution loop's most-evidenced form, at the periods round 17 and round 18 both used. Rendered
#: through `app.evolution.ruleforms` rather than typed here, so this round compares the form **as the
#: loop actually emits it** -- generations 1-1915 ran this one template, and all 28 promotions came
#: from it, which makes it the only form in the vocabulary with a real evidentiary record behind it.
FAST, SLOW, REGIME = 10, 30, 200

#: Ranking key for the `rank` arm: distance above the 200-day trend, highest first. Chosen because it
#: is the one ranking key `StrategyCard.rank_by`'s own docstring names first, it is computable from
#: the bars every card here already reads, and it was not selected by looking at a result. The `order`
#: arm leaves `rank_by` unset, which means fills follow `UNIVERSE`'s written order -- the arbitrary
#: tiebreak PROTOCOL section 7 measures at sigma = 21.2 points.
RANK_KEY = "close / sma(200)"

#: Held identical across all eight rotation cells, and both numbers are `c20-rotation`'s own. Brackets
#: are not part of either form's definition, so holding them fixed is what lets a difference between
#: the two forms be attributed to the form.
STOP_LOSS = Decimal("0.10")
MAX_HOLD_DAYS = 150

#: Slot cap -> position size, chosen so **every card in this field targets the same 88% maximum
#: deployed capital**. That is the design decision that makes the slot-cap factor mean "how
#: concentrated is the same book" rather than "how much money is in the market", and it keeps every
#: cell inside PROTOCOL section 4's 2x exposure-divergence flag. `position_pct * max_positions` is
#: capped at 1.001 by `StrategyCard._position_sizing_is_a_fraction_of_one`; 0.88 leaves the cash
#: buffer that cap exists to preserve.
SLOT_SIZING: dict[int, Decimal] = {2: Decimal("0.44"), 4: Decimal("0.22")}

#: The within-universe passive control. `close > 0` is true on every bar and `close < 0` on none, so
#: this card buys and holds. **Eight slots, not two or four**, because the quantity the scorecard is
#: missing is the *equal-weight buy-and-hold of the same eight names*: a 4-slot passive card would
#: hold whichever four names happen to sit first in `UNIVERSE` (Japan, Germany, the UK and Canada --
#: a developed-markets-only book) and would measure universe ordering rather than the asset class.
#: Its sizing keeps the same 88% budget as every rotation cell, so the comparison is like for like on
#: capital. Both expressions were run through `app.backtest.guards.check` against real `EWJ` bars
#: before this field was authored and both pass; a passive card is a *position, not a strategy*, and
#: this one is in the field to be subtracted, never to be promoted.
CONTROL_ENTRY = "close > 0"
CONTROL_EXIT = "close < 0"
CONTROL_SLOTS = 8
CONTROL_PCT = Decimal("0.11")

#: `app.evolution.ruleforms.classify` returns `None` for the control (no indicator, so nothing to
#: read a discipline off), and `Discipline` has no member meaning "passive". `trend` is the least
#: wrong of seven wrong options and is recorded here as a forced label rather than a claim -- the
#: card's own thesis says so too.
CONTROL_DISCIPLINE = "trend"

#: Matches every numeric literal in a rule expression, for the PROTOCOL section 3 parameter budget.
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def claimed_symbols() -> tuple[frozenset[str], list[Any]]:
    """`(symbols claimed by the taxable book, the non-roth cards that claim them)`, from the **live**
    library on disk.

    Recomputed rather than hardcoded, deliberately: this repository is edited by several concurrent
    sessions, and a ticker list pasted into a constant is correct exactly until the next commit. The
    returned card list is what `find_disjointness_violations` is handed alongside this round's own
    cards -- **only** the non-roth half, so that a pre-existing roth-vs-taxable violation elsewhere in
    the library cannot be reported as though this round caused it.
    """
    others: list[Any] = []
    for cards in load_library(LIBRARY_ROOT).values():
        others.extend(
            card for card in cards if card.purpose in (Purpose.SAVINGS, Purpose.TRADING)
        )
    for tier, model in EXTRA_TIERS:
        tier_dir = LIBRARY_ROOT / tier
        if not tier_dir.is_dir():
            continue
        for path in sorted(tier_dir.glob("*.json")):
            card = model.model_validate_json(path.read_text(encoding="utf-8"))
            if card.purpose in (Purpose.SAVINGS, Purpose.TRADING):
                others.append(card)

    symbols = frozenset(symbol for card in others for symbol in card.universe)
    return symbols, others


def free_numbers(card: StrategyCard) -> int:
    """PROTOCOL section 3's parameter count for one card: ten free numbers, "counted across `entry`,
    `exit`, the two brackets, the hold cap, slot count and position size".

    Distinct numeric *values* across the three expressions, not occurrences: `sma(100)` appearing in
    both the entry and the exit is one number an author chose once, and counting it twice would
    inflate the budget with a fact about text rather than about the hypothesis. `rank_by` is included
    -- it is an expression the author wrote and every number in it is a choice -- even though section
    3's list predates that field existing.
    """
    text = " ".join(part for part in (card.entry, card.exit, card.rank_by or "") if part)
    values = {match.group(0) for match in _NUMBER.finditer(text)}
    brackets = sum(
        1
        for field in (
            card.stop_loss_pct,
            card.take_profit_pct,
            card.max_hold_days,
        )
        if field is not None
    )
    return len(values) + brackets + 2  # + max_positions + position_pct


_SHARED_THESIS_TAIL = (
    "This engine has no cross-symbol operator -- entry and exit are evaluated per instrument "
    "against that instrument's own bars only -- so the rotation here is produced entirely by the "
    "universe, the slot cap and the fill order, exactly as c20-rotation's own thesis says of the "
    "sector version. The universe is eight single-country and regional equity ETFs chosen on one "
    "mechanical criterion and one legal one: enough stored history to clear every window in the "
    "matrix including gfc, and total absence from every savings- or trading-purpose card in the "
    "library, because this card is roth-purpose and Rev. Rul. 2008-5 destroys rather than defers a "
    "wash-sale loss replaced inside an IRA. EEM, EWZ, FXI and INDA belong in this universe on the "
    "merits and are excluded on that second criterion alone. Ticker disjointness is necessary and "
    "not sufficient under IRC section 1091: VWO tracks a different index from the taxable book's "
    "EEM and ILF is not EWZ, but the economic exposures are close, and nothing here claims the "
    "roster is section 1091-safe. EFA contains EWJ, EWG and EWU, so this is not eight independent "
    "bets; that redundancy is left in and counted against the field under Benjamini-Hochberg rather "
    "than papered over with extra cells. The benchmark is SPY, price-only, in USD, which is the "
    "wrong benchmark for a non-US book and is pre-registered as this round's known confound -- the "
    "field carries its own within-universe passive control (r35-passive-8-order) so the rotation "
    "can be read against buy-and-hold of the same eight names rather than only against a decade of "
    "US outperformance. Not a proposal to trade anything. See strategy-program/ROUND-35-PLAN.md."
)


def build() -> list[StrategyCard]:
    """The nine cards of round 35's field, in a fixed order. Deterministic: no clock, no filesystem
    read, no randomness -- calling this twice returns two field-identical lists, which
    `tests/test_round35_field.py` pins.
    """
    from app.evolution import ruleforms  # local: keeps import cost off `--help`

    macross_entry, macross_exit = ruleforms.render(
        "ma-crossover", fast=FAST, slow=SLOW, regime_ma=REGIME
    )
    macross_phrase = ruleforms.describe("ma-crossover", fast=FAST, slow=SLOW, regime_ma=REGIME)

    forms: dict[str, tuple[str, str, str]] = {
        "absolute": (
            ABSOLUTE_ENTRY,
            ABSOLUTE_EXIT,
            "c20-rotation's absolute per-symbol filter verbatim -- price above its own 100-day "
            "average with 14-day RSI between 50 and 75, an established but not extended move, "
            "exited when the trend breaks or RSI falls under 40",
        ),
        "macross": (macross_entry, macross_exit, macross_phrase),
    }

    cards: list[StrategyCard] = []
    for form_name, (entry, exit_rule, phrase) in forms.items():
        discipline = ruleforms.classify(entry, exit_rule)
        if discipline is None:  # pragma: no cover -- both forms classify; see the test
            raise RuntimeError(f"{form_name}: ruleforms.classify does not recognise the rule")
        for slots, position_pct in SLOT_SIZING.items():
            for rank_name, rank_by in (("order", None), ("rank", RANK_KEY)):
                cards.append(
                    StrategyCard(
                        agent_id=f"r35-{form_name}-{slots}-{rank_name}",
                        display_name=(
                            f"R35 country rotation / {form_name} / {slots} slots / {rank_name}"
                        ),
                        discipline=discipline,
                        purpose=Purpose.ROTH,
                        thesis=(
                            f"Round 35 cell. Form: {phrase}. Applied identically across eight "
                            f"country and regional equity ETFs with a binding {slots}-slot cap and "
                            f"{position_pct} of the book per slot, so at most 88% of capital is "
                            "deployed -- the same budget every card in this field carries, which is "
                            "what makes the slot cap a question about concentration rather than "
                            "about how much money is in the market. Slots are filled "
                            + (
                                "by distance above the 200-day trend (highest first), the stated "
                                "chooser rather than the arbitrary one"
                                if rank_by
                                else "in the order the universe is written, which is the arbitrary "
                                "tiebreak PROTOCOL section 7 measures at sigma = 21.2 points"
                            )
                            + ". The hypothesis under test is not that this rule is good -- the "
                            "programme's record across rounds 1-33 is that no durable edge has been "
                            "found, and that record is the prior this card argues against. It is "
                            "that country dispersion is a source this shape has never been pointed "
                            "at, and that a rotation which cannot beat its own universe's "
                            "buy-and-hold on that axis has been shown not to carry information "
                            "there. " + _SHARED_THESIS_TAIL
                        ),
                        falsification=(
                            "Wrong if this cell's median exposure-adjusted excess over the eight "
                            "main windows fails to beat the field's passive control "
                            "(r35-passive-8-order) by more than 21.2 percentage points, the "
                            "programme's measured ordering-noise floor. Beating SPY is not the "
                            "test and failing to beat SPY is not the falsification: a non-US book "
                            "measured against a US price-only benchmark over 2011-2026 inherits an "
                            "asset-class gap no rule can close, which is why the control is in the "
                            "field. A margin inside 21.2pp is a null for this cell whichever side "
                            "of the control it lands on."
                        ),
                        universe=UNIVERSE,
                        entry=entry,
                        exit=exit_rule,
                        stop_loss_pct=STOP_LOSS,
                        take_profit_pct=None,
                        max_hold_days=MAX_HOLD_DAYS,
                        max_positions=slots,
                        position_pct=position_pct,
                        rank_by=rank_by,
                        designed_through=DESIGN_THROUGH,
                    )
                )

    cards.append(
        StrategyCard(
            agent_id=f"r35-passive-{CONTROL_SLOTS}-order",
            display_name="R35 country rotation / passive control / equal-weight, always in",
            discipline=CONTROL_DISCIPLINE,
            purpose=Purpose.ROTH,
            thesis=(
                "Round 35's within-universe passive control, and the reason the rest of the field "
                "can be read at all. Entry 'close > 0' is true on every bar and exit 'close < 0' on "
                "none, with no stop, no target and no time stop, so this card buys all eight names "
                "at the window's open and holds them to its close at 11% each -- the same 88% "
                "capital budget every rotation cell carries. It is a position, not a strategy, and "
                "it is in the field to be subtracted rather than ranked: this harness scores every "
                "card against SPY, price-only and in USD, and a non-US book measured that way over "
                "2011-2026 inherits a decade of US outperformance and dollar strength that no rule "
                "can overcome. The quantity that would actually settle whether the rotation carries "
                "information is its excess over equal-weight buy-and-hold of these same eight "
                "names, and the scorecard cannot compute that -- so this card is that baseline, "
                "run through the identical engine on the identical sessions. Its discipline label "
                "is forced: ruleforms.classify returns None for a rule with no indicator in it, and "
                "the Discipline enum has no member meaning 'passive', so 'trend' is the least wrong "
                "of seven wrong options and is not a claim about what this card does. "
                + _SHARED_THESIS_TAIL
            ),
            falsification=(
                "This card makes no claim that can be falsified -- that is what makes it a control. "
                "What it can do is fail to function: if it does not hold all eight names on "
                "essentially every session of every window (session exposure at or near 1.0, eight "
                "open lots, trade count equal to the universe size), it is not the passive baseline "
                "it is being used as, and every comparison drawn against it in this round is void."
            ),
            universe=UNIVERSE,
            entry=CONTROL_ENTRY,
            exit=CONTROL_EXIT,
            stop_loss_pct=None,
            take_profit_pct=None,
            max_hold_days=None,
            max_positions=CONTROL_SLOTS,
            position_pct=CONTROL_PCT,
            rank_by=None,
            designed_through=DESIGN_THROUGH,
        )
    )
    return cards


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="write the cards to the round directory"
    )
    args = parser.parse_args(argv)

    cards = build()
    print(f"built {len(cards)} cards on {len(UNIVERSE)} names: {' '.join(UNIVERSE)}")
    print()
    print(
        f"{'agent_id':<24}  {'discipline':<14}  {'slots':>5}  {'pct':>5}  {'budget':>6}  "
        f"{'free#':>5}  rank_by"
    )
    print("-" * 104)
    for card in cards:
        budget = card.position_pct * card.max_positions
        print(
            f"{card.agent_id:<24}  {card.discipline!s:<14}  {card.max_positions:>5}  "
            f"{card.position_pct:>5}  {budget:>6}  {free_numbers(card):>5}  "
            f"{card.rank_by or '(universe order)'}"
        )

    over_budget = [c.agent_id for c in cards if free_numbers(c) > 10]
    print()
    print(
        f"parameter budget: max {max(free_numbers(c) for c in cards)} free numbers per card "
        f"(PROTOCOL section 3 allows 10)"
        + (f" -- OVER BUDGET: {over_budget}" if over_budget else "")
    )

    # Every expression the runner will guard, parsed here so a syntax error is a build failure
    # rather than a mid-round card failure the runner walks past (PROTOCOL section 8).
    for card in cards:
        grammar.parse(card.entry)
        grammar.parse(card.exit)
        if card.rank_by is not None:
            grammar.parse_ranking(card.rank_by)
    print("grammar: every entry, exit and ranking key parses")

    taxable, other_cards = claimed_symbols()
    print(
        f"library: {len(taxable)} tickers claimed by {len(other_cards)} savings/trading cards "
        f"(recomputed from {LIBRARY_ROOT.relative_to(REPO).as_posix()})"
    )
    overlap = sorted(set(UNIVERSE) & taxable)
    violations = find_disjointness_violations([*cards, *other_cards])
    if overlap or violations:
        print()
        print("DISJOINTNESS FAILURE -- refusing to author this field.")
        for symbol in overlap:
            print(f"  {symbol} is in this round's universe and in the taxable book")
        for violation in violations:
            print(
                f"  {violation.symbol}: {violation.roth_agent_id} (roth) vs "
                f"{violation.other_agent_id} ({violation.other_purpose})"
            )
        return 1
    print(
        "disjointness: no ticker in this round's universe is claimed by any savings- or "
        "trading-purpose card, and find_disjointness_violations reports nothing"
    )
    print(
        "  excluded on that invariant alone (they belong here on the merits): "
        + " ".join(EXCLUDED_TAXABLE_CLAIMED)
    )
    print(
        "  ticker disjointness is NECESSARY, NOT SUFFICIENT under IRC 1091 -- VWO/EEM and ILF/EWZ "
        "are different securities with close economic exposure; this is not a 1091-safety claim"
    )

    if not args.write:
        print()
        print("(dry run -- pass --write to author the field)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    for card in cards:
        path = OUT / f"{card.agent_id}.json"
        path.write_text(
            card.model_dump_json(indent=2, exclude_none=False) + "\n", encoding="utf-8"
        )
    print()
    print(f"wrote {len(cards)} cards to {OUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
