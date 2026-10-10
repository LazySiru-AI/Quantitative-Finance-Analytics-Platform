"""Round 36: does relative strength decide the slot, or is `rank_by` inside the ordering-noise floor?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round36.py --write

`strategy-program/ROUND-36-PLAN.md` is the pre-registration this executes. Read it first.

This authors the round's field and nothing else -- the cards are then run by
`strategy-program/tools/run_round.sh` and scored by `score.py`, exactly like every other card round.

**What the round measures.** `StrategyCard.rank_by` is the one place this engine compares symbols to
each other rather than to their own bars (see that field's docstring in full). When more names satisfy
`entry` on a session than `max_positions` leaves room for, somebody chooses; left unset -- the default,
and what every card frozen before the field existed gets -- that chooser is the order the `universe`
array happens to be typed in. `PROTOCOL.md` §7 prices that accident: twelve orderings of one identical
card moved its three-year return across a **53.9-point spread, sigma = 21.2 points**, and the
relative-strength ordering ranked **9th of 10** against random draws. This round asks the question that
measurement leaves open -- whether naming the chooser is worth anything at all -- by varying *only* the
chooser and holding the rule, the universe, the sizing and the cutoff identical.

**Why the field is generated rather than hand-written.** Ten cards differing in two fields is exactly
the shape a hand-copied JSON set gets wrong: the canonical and reversed universes must be provably the
same *set*, and the strongest-first and weakest-first keys must be provably exact negations. Both are
derived here in code (`tuple(reversed(UNIVERSE))`, `f"0 - {STRONGEST}"`) rather than retyped, so the
comparison cannot quietly stop being a comparison. `tests/test_round36_field.py` asserts both.

**The fixed rule is `c20-rotation`'s, and that choice is load-bearing.** `close > sma(100) and rsi(14)
> 50 and rsi(14) < 75` / `close < sma(100) or rsi(14) < 40`, 10% stop, 150-day cap, is an existing
card's absolute filter -- not a rule picked for this round. `c20-rotation`'s own thesis says this
engine "has no cross-symbol operator" and calls its fill order "an arbitrary-but-reasoned tiebreak";
`rank_by` is precisely the feature that changes that claim, so the honest test of it runs *that card's
filter*. Every threshold here was frozen in `backend/app/paper/library/candidates/c20-rotation.json`
before this round was conceived. Nothing was tuned.

**The universe is pinned to the sibling industry round, 34, and must not be changed.** Eight SPDR/
iShares/Vanguard industry ETFs, written once in `UNIVERSE` and reversed in code. The two rounds share
it so their results are comparable; changing it here silently breaks that.

**The Roth invariant is checked against the live library, not against a copy of it.** Every card
carries `purpose = Purpose.ROTH`, and `--write` refuses on any ticker shared with a `savings`- or
`trading`-purpose card, using `app.tournament.purposes.find_disjointness_violations` over the real
library -- including `library/allocation/` and `library/ladder/`, which `load_library` does not walk.
Ticker disjointness is necessary and **not sufficient** under IRC §1091: nothing here claims wash-sale
safety, only that the one mechanical thing that is checkable did not fire. See `purposes.py`'s own
module docstring, which says this at length and is not paraphrased away here.

**Nothing here reads a ledger.** The cards read the Parquet/DuckDB bar store and nothing else --
no `data/accounts.toml`, no `data/sectors.toml`, no `data/store/ledger.sqlite`, no `app.tax`.

**Not investment advice.** The round has not been run.
"""

from __future__ import annotations

import argparse
import math
import pathlib
from decimal import Decimal

import pandas as pd

from app.backtest import guards
from app.backtest.models import GuardStatus
from app.config import get_settings
from app.market.models import Interval
from app.rules import grammar
from app.tournament.allocation import AllocationCard
from app.tournament.ladder import LadderCard
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from app.tournament.purposes import DisjointnessViolation, Purpose, find_disjointness_violations
from app.tournament.results import load_library

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r36-2026-09" / "cards"

#: The pinned industry universe, in **one canonical order**. Identical to the sibling industry round
#: (34) so the two stay comparable, and written exactly once here: the "reversed" arm derives from
#: this tuple in code (`reversed_universe`), so the two orderings are provably the same set and a
#: future edit cannot make them drift into being two different universes.
#:
#: SPDR S&P Metals & Mining, Retail, Homebuilders, Semiconductor, Oil & Gas E&P and Biotech, plus
#: iShares US Aerospace & Defense and Vanguard Real Estate. First stored daily bars: XHB/XSD/XBI
#: 2006-02-06, ITA 2006-05-05, XME/XRT/XOP 2006-06-22, VNQ 2004-09-29 -- every one of them clears
#: `gfc` (2007-10-09) with room for the 200-day key, verified with `tools/windows.py` and with a live
#: `guards.check` against the real bars (see `ROUND-36-PLAN.md` §6).
#:
#: **Substantial identity, stated rather than assumed.** XSD's index is not SOXX's or SMH's, and
#: XOP's is not XLE's, but that is an argument about economics and this tool checks tickers. IRC
#: §1091 turns on securities being *substantially identical*, not on symbols matching; nothing in
#: this file claims these eight names are safe under §1091, only that they are disjoint from every
#: taxable card's universe, which is the one mechanical thing that is cheap to check.
UNIVERSE: tuple[str, ...] = ("XME", "XRT", "XHB", "XSD", "XOP", "XBI", "ITA", "VNQ")

#: `c20-rotation`'s absolute filter, character for character. An existing card's rule, not one chosen
#: for this round -- see the module docstring.
ENTRY = "close > sma(100) and rsi(14) > 50 and rsi(14) < 75"
EXIT = "close < sma(100) or rsi(14) < 40"
STOP_LOSS_PCT = Decimal("0.10")
MAX_HOLD_DAYS = 150

#: Distance above the 200-day trend, the ranking key the `A-rotation` ordering study actually used
#: (`backend/app/paper/library/README.md`: relative-strength order, 9th of 10 against random draws).
STRONGEST = "close / sma(200)"

#: The exact negation of `STRONGEST`, built from it rather than retyped. `rank_by` sorts highest-first
#: and has no direction field, so negation is the only way to express "weakest first" -- see
#: `StrategyCard.rank_by`. The leading `0 -` is that idiom, not a chosen parameter, and is not counted
#: against the parameter budget.
WEAKEST = f"0 - {STRONGEST}"

#: The same "how far above trend" question in volatility units instead of price ratio. A third arm
#: rather than a replacement for `STRONGEST`: if relative strength carries information, it should not
#: matter much which of two reasonable spellings of it is used, and if the two disagree by more than
#: the floor then the *spelling* is doing the work, which is a finding about noise, not about strength.
VOL_UNITS = "(close - sma(50)) / atr(14)"


def reversed_universe() -> tuple[str, ...]:
    """`UNIVERSE` back to front -- the "arbitrary written order, written the other way" arm.

    Derived, never retyped. The whole reversed arm is only a measurement of ordering noise if it is
    the *same set of names* in a different order; a hand-copied tuple with one ticker fat-fingered
    would silently turn this round's cheapest control into a universe comparison.
    """
    return tuple(reversed(UNIVERSE))


#: The five orderings, in the order the field is authored. `(slug, universe, rank_by, label)`.
#: `rank_by=None` is the pre-`rank_by` default -- fills walk `universe` in the order it is written.
ORDERINGS: tuple[tuple[str, tuple[str, ...], str | None, str], ...] = (
    ("canonical", UNIVERSE, None, "written order (rank_by unset)"),
    ("reversed", reversed_universe(), None, "written order, reversed (rank_by unset)"),
    ("strong", UNIVERSE, STRONGEST, "strongest first, close/sma(200)"),
    ("weak", UNIVERSE, WEAKEST, "weakest first, the exact negation of the strongest key"),
    ("volunits", UNIVERSE, VOL_UNITS, "strongest first in volatility units, (close-sma(50))/atr(14)"),
)

#: Slot cap -> position size. **Maximum capital at risk is held equal at 50% across both arms**
#: (2 x 0.25 = 4 x 0.125), so the two arms are commensurable on `adjusted_excess`, which `PROTOCOL.md`
#: §4 measures as scaling with exposure (Pearson r = +0.797 against GFC adjusted excess). The cost is
#: stated rather than hidden: slot count and position size move together, so a *level* difference
#: between the k arms cannot be attributed to the cap alone. That is deliberate, because this round
#: compares ordering *spreads within* a k arm, and every card inside one arm has identical sizing.
SLOTS: tuple[tuple[int, Decimal], ...] = ((2, Decimal("0.25")), (4, Decimal("0.125")))

#: The free numbers in the fixed rule, itemised so a reader can check the count rather than trust it.
#: `PROTOCOL.md` §3 rule 3 budgets **ten free numbers per card** across entry, exit, the two brackets,
#: the hold cap, slot count and position size. Counted as *choices*, not as literal tokens: the
#: `sma(100)` period and the `rsi(14)` period are each one decision reused in both rules.
FIXED_FREE_NUMBERS: tuple[str, ...] = (
    "sma period 100 (entry and exit)",
    "rsi period 14 (entry and exit)",
    "rsi upper 75 (entry)",
    "rsi lower 50 (entry)",
    "rsi exit 40 (exit)",
    "stop_loss_pct 0.10",
    "max_hold_days 150",
    "max_positions (2 or 4)",
    "position_pct (0.25 or 0.125, pinned by max_positions to a 50% ceiling)",
)

#: Free numbers each ranking key adds on top of `FIXED_FREE_NUMBERS`. `rank_by` is not in §3's
#: enumerated list, which predates the field; it is counted here anyway, because a period chosen for a
#: ranking key is exactly as free as one chosen for an entry rule. The `0 -` in `WEAKEST` is the
#: negation idiom, not a parameter. `volunits` re-uses the already-counted 14 for `atr(14)`.
RANK_FREE_NUMBERS: dict[str, tuple[str, ...]] = {
    "canonical": (),
    "reversed": (),
    "strong": ("sma period 200 (rank_by)",),
    "weak": ("sma period 200 (rank_by)",),
    "volunits": ("sma period 50 (rank_by)",),
}


def free_number_count(ordering: str) -> int:
    """How many free numbers a card in `ordering` carries. Reported by `main`, asserted by the tests."""
    return len(FIXED_FREE_NUMBERS) + len(RANK_FREE_NUMBERS[ordering])


def _thesis(ordering: str, label: str, slots: int, rank_by: str | None) -> str:
    chooser = "the order `universe` is written in" if rank_by is None else f"`{rank_by}`"
    return (
        f"Round 36 ordering cell: {label}, {slots} slots on eight industry ETFs. This card is one "
        "cell of a pre-registered ten-cell field whose only variable is which qualifying name takes "
        "a scarce slot. Entry, exit, stop, hold cap, universe membership, design cutoff and maximum "
        "capital at risk are identical across all ten; the chooser here is "
        f"{chooser}. The question the field asks: `StrategyCard.rank_by` is the one place this "
        "engine compares symbols to each other, and PROTOCOL.md section 7 prices the alternative it "
        "replaces -- twelve orderings of one identical card moved its three-year return across a "
        "53.9-point spread, sigma = 21.2 points, with relative-strength order 9th of 10 against "
        "random draws. So the operator is not known to be worth anything, and this round measures "
        "the two contrasts that would settle it: canonical order against its own reverse (pure "
        "ordering noise, with the rule and the names held fixed), and strongest-first against "
        "weakest-first (whether relative strength carries slot-level information at all). If those "
        "two spreads are the same size, the chooser is decorative on this universe. The rule is "
        "c20-rotation's own absolute filter, unchanged, because that card's thesis is what says this "
        "engine has no cross-symbol operator and calls its fill order an arbitrary-but-reasoned "
        "tiebreak -- rank_by is the feature that changes that claim, so it is tested on that card's "
        "filter rather than on a rule invented for the occasion. Nothing here is tuned: every "
        "threshold was frozen in c20-rotation before this round was conceived, and no parameter was "
        "chosen by looking at an outcome. This is a measurement study on a Roth-purpose universe "
        "held disjoint from every taxable card; it is not a proposal to trade anything and nothing "
        "in it will be promoted. See strategy-program/ROUND-36-PLAN.md for the pre-registration, the "
        "predictions, the 21.2pp decision rule and the Benjamini-Hochberg correction taken across "
        "all ten cells."
    )


FALSIFICATION = (
    "Strongest-first minus weakest-first, on median adjusted excess across the eight main windows, "
    "lands inside the 21.2pp ordering-noise floor -- and/or is no larger than the canonical-versus-"
    "reversed spread measured on the identical rule and names. Either outcome says relative strength "
    "carries no slot-level information on this universe and that naming the chooser bought nothing "
    "measurable. A second, structural falsification runs first: if all five orderings inside a slot "
    "arm return identical trade logs, the slot cap never bound, no ordering could have mattered, and "
    "that arm measured nothing at all."
)


def build() -> list[StrategyCard]:
    """The ten frozen cards. Deterministic: same inputs, same list, same order, every call."""
    cards: list[StrategyCard] = []
    for ordering, universe, rank_by, label in ORDERINGS:
        for slots, position_pct in SLOTS:
            cards.append(
                StrategyCard(
                    agent_id=f"r36-{ordering}-k{slots}",
                    display_name=f"R36 {label} / {slots} slots",
                    discipline=Discipline.PAIRS_ROTATION,
                    purpose=Purpose.ROTH,
                    thesis=_thesis(ordering, label, slots, rank_by),
                    falsification=FALSIFICATION,
                    universe=universe,
                    entry=ENTRY,
                    exit=EXIT,
                    rank_by=rank_by,
                    stop_loss_pct=STOP_LOSS_PCT,
                    take_profit_pct=None,
                    max_hold_days=MAX_HOLD_DAYS,
                    max_positions=slots,
                    position_pct=position_pct,
                    designed_through=DESIGN_THROUGH,
                )
            )
    return cards


# ---------------------------------------------------------------------------
# The binding constraint: no intersection with taxable research
# ---------------------------------------------------------------------------


def library_cards() -> list[StrategyCard | AllocationCard | LadderCard]:
    """Every purposed card in the live library, including the two tiers `load_library` does not walk.

    `app.tournament.results.load_library` covers `base`/`variants`/`candidates`/`retired`, which are
    the `StrategyCard` tiers. `library/allocation/` and `library/ladder/` hold `AllocationCard`s and
    `LadderCard`s and are walked separately -- `app.evolution.promotion` records the same gap in as
    many words. Leaving them out would be the whole check quietly missing five taxable tickers
    (AGG, BIL, QLD, SCHD, SGOV are held only by cards in those two directories), which is exactly the
    shape of failure this function exists to prevent.
    """
    cards: list[StrategyCard | AllocationCard | LadderCard] = []
    for tier_cards in load_library().values():
        cards.extend(tier_cards)

    library_root = get_settings().library_dir
    for tier, model in (("allocation", AllocationCard), ("ladder", LadderCard)):
        tier_dir = library_root / tier
        if not tier_dir.is_dir():
            continue
        for path in sorted(tier_dir.glob("*.json")):
            cards.append(model.model_validate_json(path.read_text(encoding="utf-8")))
    return cards


def taxable_symbols(cards: list[StrategyCard | AllocationCard | LadderCard]) -> set[str]:
    """Every ticker held by a `savings`- or `trading`-purpose card. Recomputed, never hardcoded."""
    out: set[str] = set()
    for card in cards:
        if card.purpose in (Purpose.SAVINGS, Purpose.TRADING):
            out |= set(card.universe)
    return out


def disjointness_violations(new_cards: list[StrategyCard]) -> tuple[DisjointnessViolation, ...]:
    """`find_disjointness_violations` over the new field *plus* the whole live library.

    The library is passed in alongside the new cards rather than differenced against a precomputed
    ticker set, so this is the identical check the application's own invariant uses -- one
    implementation, not a second one that could drift from it.
    """
    return find_disjointness_violations([*library_cards(), *new_cards])


# ---------------------------------------------------------------------------
# Guard rehearsal -- store-free, so it runs on every invocation
# ---------------------------------------------------------------------------


def _synthetic_bars(n: int = 600) -> pd.DataFrame:
    """A deterministic, strictly causal daily series -- enough bars for a 200-period warmup plus the
    40 post-warmup bars `app.backtest.guards` needs to demonstrate causality.

    Oscillating with drift so that no indicator degenerates to a constant, and seedless so the frame
    is byte-identical on every machine. This is a rehearsal, not the real check: the runner guards
    every expression against **each universe symbol's own bars** before the card trades
    (`app.tournament.runner._guard_card`, which now checks `rank_by` with `kind="ranking"` exactly as
    it checks `entry` and `exit`). What this catches early is a key that could never pass anywhere.
    """
    ts = pd.date_range("2018-01-01", periods=n, freq="B", tz="UTC")
    close = [100.0 * (1 + 0.15 * math.sin(i / 40.0) + 0.0004 * i) for i in range(n)]
    return pd.DataFrame(
        {
            "ts": ts,
            "open": [c * 0.995 for c in close],
            "high": [c * 1.01 for c in close],
            "low": [c * 0.99 for c in close],
            "close": close,
            "volume": [1_000_000.0] * n,
        }
    )


def guard_rehearsal() -> list[tuple[str, str, str]]:
    """`(what, expression, status)` for every expression this field uses, on a synthetic series."""
    bars = _synthetic_bars()
    checks: list[tuple[str, str, str]] = [("entry", ENTRY, "rule"), ("exit", EXIT, "rule")]
    seen: set[str] = set()
    for slug, _universe, rank_by, _label in ORDERINGS:
        if rank_by is None or rank_by in seen:
            continue
        seen.add(rank_by)
        checks.append((f"rank_by ({slug})", rank_by, "ranking"))

    out: list[tuple[str, str, str]] = []
    for what, expression, kind in checks:
        report = guards.check(expression, bars, interval=Interval.DAY, kind=kind)  # type: ignore[arg-type]
        out.append((what, expression, report.status.value))
    return out


def parse_rehearsal() -> list[str]:
    """Parse every expression through the real grammar. Raises `RuleSyntaxError` if any is not what
    it claims to be -- a condition for `entry`/`exit`, a number for every `rank_by`."""
    notes = [f"entry parses: {ENTRY}", f"exit parses: {EXIT}"]
    grammar.parse(ENTRY)
    grammar.parse(EXIT)
    for slug, _universe, rank_by, _label in ORDERINGS:
        if rank_by is None:
            notes.append(f"{slug}: rank_by unset (fills walk the written universe order)")
            continue
        grammar.parse_ranking(rank_by)
        notes.append(f"{slug}: rank_by parses as a number: {rank_by}")
    return notes


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="write the cards to the round directory"
    )
    args = parser.parse_args(argv)

    cards = build()

    print(f"built {len(cards)} cards: {len(ORDERINGS)} orderings x {len(SLOTS)} slot caps")
    print(f"  canonical universe: {' '.join(UNIVERSE)}")
    print(f"  reversed  universe: {' '.join(reversed_universe())}")
    print(f"  same set: {set(UNIVERSE) == set(reversed_universe())}")
    print()

    print("field:")
    header = f"  {'agent_id':<22} {'slots':>5} {'pct':>7} {'max risk':>9}  rank_by"
    print(header)
    for card in cards:
        ordering = card.agent_id.split("-")[1]
        max_risk = card.position_pct * card.max_positions
        rank = "(universe order)" if card.rank_by is None else card.rank_by
        print(
            f"  {card.agent_id:<22} {card.max_positions:>5} {card.position_pct:>7} "
            f"{max_risk:>9}  {rank}   [{free_number_count(ordering)} free numbers]"
        )
    print()

    print("parse rehearsal:")
    for note in parse_rehearsal():
        print(f"  {note}")
    print()

    print("guard rehearsal (synthetic causal series; the runner re-checks against real bars):")
    failed_guards = []
    for what, expression, status in guard_rehearsal():
        print(f"  {status:<8} {what}  ->  {expression}")
        if status != GuardStatus.PASSED.value:
            failed_guards.append(what)
    print()

    print("negation check:")
    print(f"  strongest: {STRONGEST}")
    print(f"  weakest:   {WEAKEST}")
    print(f"  exact negation: {WEAKEST == '0 - ' + STRONGEST}")
    print()

    library = library_cards()
    taxable = taxable_symbols(library)
    overlap = sorted(set(UNIVERSE) & taxable)
    violations = disjointness_violations(cards)
    print("Roth disjointness (recomputed from the live library, all six tiers):")
    print(f"  {len(library)} purposed cards; {len(taxable)} tickers held by savings/trading cards")
    print(f"  this universe intersected with them: {overlap if overlap else 'none'}")
    print(f"  find_disjointness_violations: {len(violations)} violation(s)")
    for violation in violations:
        print(f"    {violation.message}")
    print(
        "  NOTE: ticker disjointness is necessary, not sufficient. IRC 1091 turns on securities "
        "being substantially identical, not on symbols matching (app.tournament.purposes). Nothing "
        "here claims these eight names are safe under 1091."
    )
    print()

    blocked = bool(violations) or bool(failed_guards)
    if blocked:
        print("REFUSING TO WRITE:")
        if violations:
            print(f"  {len(violations)} Roth/taxable disjointness violation(s)")
        if failed_guards:
            print(f"  guard rehearsal failed for: {', '.join(failed_guards)}")
        return 1

    if not args.write:
        print("(dry run -- pass --write to author the field)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    for card in cards:
        path = OUT / f"{card.agent_id}.json"
        path.write_text(card.model_dump_json(indent=2, exclude_none=False) + "\n", encoding="utf-8")
    print(f"wrote {len(cards)} cards to {OUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
