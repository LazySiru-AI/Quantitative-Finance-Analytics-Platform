"""Round 38: does the *real* discount rate decide how defensive a long-horizon savings book is?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round38.py
    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round38.py --write
    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round38.py --smoke

`ROUND-38-PLAN.md` is the pre-registration this executes. Read it first; this file only authors the
field and refuses to author an illegal one.

**What is new here, stated precisely, because it is the round's whole justification.** Every macro
round this programme has run -- 21, 22, 23, 25, 30, 31, 32 -- conditioned a `trading`-purpose
`StrategyCard`. No macro series has ever been attached to a `savings`- or `roth`-purpose book. And of
the seven `MacroField` series in the DSL (`app.rules.nodes`), `T10YIE` has never been *combined* with
`DGS10`: round 30 measured each alone, as a level and as a rate-of-change forward-return signal, and
found both null. Nominal minus breakeven is the **real yield** -- the discount rate a 10-20 year
savings book is actually exposed to -- and it is a different quantity from either leg. This round is
therefore a new quantity on a new book, not a re-run of a closed line.

**The prior is a null and this round predicts one.** Round 30 measured all seven series null; round
31 closed the macro line on a null; round 32's single inflation near-miss dissolved out of sample.
Nothing about attaching a macro term to a different `purpose` gives it information it did not have.
The round earns its place by testing something the programme has not tested, not by expecting a
different answer -- see `ROUND-38-PLAN.md` section 1.

**The card shape, and the two things about it a reader will guess wrong.** `AllocationCard`'s
`TiltRule.condition` is evaluated against `on_symbol`'s *own bars only* -- there is no cross-symbol
operator -- and `on_symbol` is validated to be some sleeve on the same card. Every rule here uses
`on_symbol="SPY"`, and **SPY supplies only the session axis, not a price signal**: the condition is a
pure `macro(...)` term on every treatment card except the deliberate price placebo. The macro series
is joined onto those bars by `app.rules.macro_binding.bind_macro` at its *release* date, not its
reference date, and `_guard_allocation_card` -> `guards.check` verifies that per scored session.

**A macro condition needs a pin, and that is a runtime requirement, not a design one.** `guards.check`
fails closed with `MissingPinError` unless `INVDASH_MACRO_PIN` points at a pin written by
`app.rules.macro_pin.write_pin`. This module points it at round 21's frozen seven-series pin
(:data:`MACRO_PIN`), the same one rounds 23/25/30 used, so this round cannot silently measure a
differently-revised FRED vintage than they did. Probed 2026-09-09: with the pin set, every condition
in this field returns `GuardStatus.PASSED` including the two-term subtraction.

**Release lag: DGS10 and T10YIE are daily market-observed series and carry one trading day.** Rounds
21/31/32 argue at length about the 45-day placeholder lag on the monthly CPI/PCE indices and the
unclosed *revision* channel behind it. Neither argument applies here. `RELEASE_LAG` gives both of
these series one trading day, which is the engine's own existing convention (a yield stamped with a
session's date is known after that session closes), and a market-observed yield is not revised. This
round therefore inherits none of the inflation rounds' lag caveats and must not be read as if it did.

**Nothing here is searched.** Every threshold is a round number fixed by a concept, not by an outcome
(section 4 of the plan justifies each one individually), the shift is a round ten points of the book,
the sleeve weights are round tenths with the equity share pinned to the savings benchmark's own 30%,
and `sma(200)` on the placebo is the textbook constant already frozen in `app.evolution.ruleforms`.
No return series was read while choosing any of them. What *was* read, and is disclosed rather than
hidden, is the **support of the regressor itself** -- how often each condition fires in each window,
a statement about `DGS10` and `T10YIE` alone that touches no price and no outcome. That screen found
a structural fact this round has to be honest about up front: at a 2.0% threshold the primary
treatment is degenerate (fires in 0 of 6 bear windows and in only one window per horizon, below the
programme's own `MIN_ELIGIBLE_R5_PER_HORIZON = 2`). See `ROUND-38-PLAN.md` sections 4 and 6.

**Not investment advice.** Nothing in this field is promotable; a measurement round promotes nothing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
from decimal import Decimal

from app.rules import grammar
from app.rules.nodes import (
    Arith,
    BoolOp,
    Comparison,
    Cross,
    IndicatorRef,
    Literal,
    MacroRef,
    Not,
    PriceRef,
)
from app.tournament.allocation import AllocationCard, Sleeve, TiltRule
from app.tournament.models import DESIGN_THROUGH
from app.tournament.purposes import Purpose

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r38-2026-09" / "cards"

#: Round 21's frozen seven-series FRED pin, reused rather than re-fetched. Rounds 23, 25 and 30 all
#: measured against this exact file; re-fetching would serve today's revised values against the same
#: reference dates and make this round non-comparable with them for no gain.
MACRO_PIN = REPO / "data" / "rounds" / "r21-2026-08" / "macro-pin.json"

#: The base allocation, identical on every card in the field including the control.
#:
#: `SPY` is 30% because that is the savings benchmark's own equity share (`30-70-spy-agg`,
#: `app.paperdesk.benchmarks`) -- pinning it there means no card in this field is making an unstated
#: equity-beta bet against the thing it is scored against, which is how round 29's "survivor"
#: dissolved. The benchmark's remaining 70% is split across three defensive sleeves in round tenths
#: rather than held entirely in `AGG`, because the tilt this round tests needs somewhere to move
#: weight *to* that is not itself long duration: a high real yield is precisely the state in which
#: `AGG` is hurt, so `BIL` (T-bills) is the honest defensive destination and `GLD` is the non-bond
#: diversifier. No weight here was chosen by looking at a return.
#:
#: **Every sleeve's history clears every window this round uses.** First bars, read live from the
#: store 2026-09-09: SPY 1993-01-29, AGG 2003-09-29, GLD 2004-11-18, BIL 2007-05-30. The earliest
#: window in the set is `h10y-1` (2013-09-03), so the binding constraint is not a sleeve at all --
#: it is `T10YIE`, which starts 2003-01-02. `SCHD` (2011-10-20) and `SGOV` (2020-06-01) are
#: deliberately absent: `SGOV` alone would truncate the field to post-2020 and destroy the 10-year
#: rungs the savings mandate is judged on.
SLEEVES: tuple[tuple[str, str], ...] = (
    ("SPY", "0.30"),
    ("AGG", "0.50"),
    ("GLD", "0.10"),
    ("BIL", "0.10"),
)

#: The same 5-point band both live allocation cards carry (`qld-schd-sgov`,
#: `spy-schd-agg-gld-bil-atr-tilt`), reused rather than re-chosen so this round varies the macro
#: condition and nothing else against the shipped family.
BAND = Decimal("0.05")

#: Ten points of the whole book -- `TiltRule.shift_pct` is a fraction of the *portfolio*, not of
#: `from_symbol`'s own weight. $10,000 of the savings book's $100,000, and it moves the equity sleeve
#: from 30% to 20%: a third of the equity exposure, materially different but not a regime switch.
#:
#: **It is deliberately larger than `BAND`.** A shift smaller than the drift band could be absorbed
#: entirely by the band and never produce a trade -- a tilt that is present, plausible and unread,
#: which is the exact shape of defect this programme keeps finding. At 0.10 against a 0.05 band a
#: firing rule always breaches, so the condition is guaranteed to be *expressed* whenever it is true.
SHIFT = Decimal("0.10")

#: Every rule reads its condition off SPY's bars. SPY carries the longest history of the four sleeves
#: and is the benchmark's own equity leg, so the session axis is the densest available. On every card
#: but `r38-price-placebo` the condition contains no price term at all -- see the module docstring.
ON_SYMBOL = "SPY"

#: The real yield: nominal 10-year constant maturity minus the 10-year breakeven inflation rate. The
#: quantity this round exists to test, and the one combination of `MacroField` members the programme
#: has never formed.
REAL_YIELD = "macro(DGS10) - macro(T10YIE)"


class RothCollision(RuntimeError):
    """A sleeve in this taxable field is claimed by a live `roth`-purpose card."""


def roth_union() -> frozenset[str]:
    """Every ticker claimed by a live `roth`-purpose card, recomputed from the library.

    Walked live from `app.evolution.promotion._library_cards` (which covers all six tiers) rather
    than pasted from a memo, because a hard-coded list of forbidden tickers is a second copy of a
    fact that already exists and it drifts silently -- and the failure it would hide is a taxable
    card quietly claiming a ticker the Roth book already holds, which is a wash-sale exposure, not a
    naming collision.
    """
    from app.config import get_settings
    from app.evolution.promotion import _library_cards

    settings = get_settings()
    claimed: set[str] = set()
    for card in _library_cards(settings):
        if getattr(card, "purpose", None) is Purpose.ROTH:
            claimed |= set(card.universe)
    return frozenset(claimed)


def _literals(node: object) -> int:
    """Count the free numbers in one parsed expression tree.

    Both bare literals (`> 1.0`) and an indicator's numeric arguments (`sma(200)`) count, because
    both are numbers an analyst chose and either could have been tuned. String indicator arguments
    (`vwap(session)`) are not numbers and do not.
    """
    match node:
        case Literal():
            return 1
        case PriceRef() | MacroRef():
            return 0
        case IndicatorRef(args=args):
            return sum(1 for arg in args if isinstance(arg, int | float))
        case Arith(left=left, right=right):
            return _literals(left) + _literals(right)
        case Comparison(left=left, right=right):
            return _literals(left) + _literals(right)
        case Cross(left=left, right=right):
            return _literals(left) + _literals(right)
        case BoolOp(operands=operands):
            return sum(_literals(operand) for operand in operands)
        case Not(operand=operand):
            return _literals(operand)
        case _:  # pragma: no cover -- every node type in the DSL is handled above
            raise TypeError(f"unhandled node {type(node).__name__}")


def free_numbers(card: AllocationCard) -> int:
    """This card's free-number count against PROTOCOL.md section 3 rule 3's budget of ten.

    Counted the way that rule intends -- every number the analyst was free to choose -- which for an
    allocation card is each sleeve's target weight, the band, and per rule the literals in its
    condition plus its own shift. The weights are counted in full rather than as `n - 1`
    "independent" numbers: the partition constraint is the model's, not the analyst's, and counting
    generously is the direction that cannot flatter a card.
    """
    total = len(card.sleeves) + 1  # weights + band_pct
    for rule in card.rules:
        total += _literals(grammar.parse(rule.condition))
        total += 1  # shift_pct (or shift_expr, which none of this field uses)
    return total


#: `(agent_id, display_name, condition, from_symbol, to_symbol, role)`. A `condition` of `None` is
#: the control -- no rule at all, not a rule that never fires. The order is the order the plan states
#: them in; nothing downstream depends on it.
FIELD: tuple[tuple[str, str, str | None, str, str, str], ...] = (
    (
        "r38-control",
        "Real-yield control (no tilt)",
        None,
        "",
        "",
        "control",
    ),
    (
        "r38-realyield-hi-1",
        "Real yield above 1% -> defensive",
        f"{REAL_YIELD} > 1.0",
        "SPY",
        "BIL",
        "primary treatment",
    ),
    (
        "r38-realyield-hi-2",
        "Real yield above 2% -> defensive",
        f"{REAL_YIELD} > 2.0",
        "SPY",
        "BIL",
        "threshold sensitivity (pre-registered degenerate)",
    ),
    (
        "r38-realyield-lo-1",
        "Real yield below 1% -> risk-on",
        f"{REAL_YIELD} < 1.0",
        "BIL",
        "SPY",
        "opposite-direction half",
    ),
    (
        "r38-nominal-hi-4",
        "Nominal 10y above 4% -> defensive",
        "macro(DGS10) > 4.0",
        "SPY",
        "BIL",
        "separability leg A (nominal alone)",
    ),
    (
        "r38-breakeven-lo-2",
        "Breakeven inflation below 2% -> defensive",
        "macro(T10YIE) < 2.0",
        "SPY",
        "BIL",
        "separability leg B (breakeven alone)",
    ),
    (
        "r38-price-placebo",
        "SPY below its 200-day mean -> defensive",
        "close < sma(200)",
        "SPY",
        "BIL",
        "price-only placebo (no macro term)",
    ),
)

_COMMON = (
    "Round 38 pre-registered cell, on the taxable savings book ($100,000 lump sum, 10-20 year "
    "horizon, benchmark 30/70 SPY/AGG, mandate: lowest drawdown of the three books, least return "
    "accepted). Base allocation on every card in this field, including the control: 30% SPY (the "
    "benchmark's own equity share, so no card here makes an unstated beta bet), 50% AGG, 10% GLD, "
    "10% BIL. Cards differ in exactly one thing -- the tilt condition -- and this round reports "
    "treatment MINUS CONTROL, never treatment against the benchmark alone. The programme's prior is "
    "a null: rounds 30 and 31 measured every FRED series in the DSL null, and round 32's single "
    "inflation near-miss dissolved out of sample. This round predicts a null too (see "
    "strategy-program/ROUND-38-PLAN.md section 5); it earns its place by testing a quantity the "
    "programme has never formed -- nominal minus breakeven, the real yield -- on a book no macro "
    "series has ever been attached to, not by expecting a different answer. It is not a proposal to "
    "trade anything, and nothing in a measurement round is promotable. Not investment advice."
)

_FALSIFICATION = (
    "This round's hypothesis is wrong, not merely unlucky, if the treatment-minus-control margin in "
    "max drawdown and MAR is indistinguishable from zero across the eligible 5y and 10y rungs -- "
    "which is the outcome pre-registered as most likely. It is also wrong in the more interesting "
    "direction if the price-only placebo card (r38-price-placebo) moves the same metrics by as much "
    "as any macro card does, because that would show the measured effect is 'a tilt fired sometimes' "
    "rather than 'the real discount rate carried information'. The named failure regime is a "
    "sustained low-real-yield decade with rising equities: from 2013 to 2021 the real yield sat below "
    "1% almost continuously, so a card that de-risks on high real yields spends that entire stretch "
    "identical to its own control and can only differ after 2022 -- which means any margin this round "
    "reports on the 10-year rungs is dominated by one regime transition, not by nine years of "
    "evidence. See ROUND-38-PLAN.md section 6 for the pre-registered per-window firing matrix."
)


def _thesis(agent_id: str, condition: str | None, from_symbol: str, to_symbol: str, role: str) -> str:
    if condition is None:
        return (
            f"{_COMMON} This is the MANDATORY CONTROL: the same four sleeves and the same 5-point "
            "band with every tilt removed, so it carries no rule at all. It is not a treatment that "
            "never fires -- it is the static, periodically-rebalanced book every other card in the "
            "field is measured as a difference from. Its whole purpose is that a savings card that "
            "looks good against the 30/70 benchmark may simply be a better static allocation, which "
            "says nothing whatever about the macro condition this round is testing."
        )
    return (
        f"{_COMMON} This cell's role: {role}. When `{condition}` is true of the session -- read off "
        f"SPY's bars, which supply the session axis only"
        + (
            ", the condition containing no price term at all; the macro series is joined at its "
            "RELEASE date, not its reference date, and DGS10/T10YIE are daily market-observed "
            "series carrying a one-trading-day lag, so this round inherits none of the monthly "
            "CPI/PCE rounds' 45-day placeholder-lag or revision caveats"
            if "macro(" in condition
            else " and, on this one card, the signal itself: this is the deliberate price-only "
            "placebo, carrying no macro term, so that 'a tilt fired sometimes' can be separated "
            "from 'the real discount rate carried information'"
        )
        + f" -- ten points of the whole book move from {from_symbol} into {to_symbol}. Ten points is "
        "deliberately larger than the 5-point band: a shift smaller than the band could be absorbed "
        "by it and never trade, leaving a tilt that is present, plausible and unread. The threshold "
        "is a round number fixed by a concept before any measurement existed, not a searched one "
        "(ROUND-38-PLAN.md section 4 justifies each individually), and no return series was read "
        "while choosing it."
    )


def build() -> list[AllocationCard]:
    """The round's seven cards, deterministically. No I/O, no randomness, no store access."""
    sleeves = tuple(
        Sleeve(symbol=symbol, target_weight=Decimal(weight)) for symbol, weight in SLEEVES
    )
    cards: list[AllocationCard] = []
    for agent_id, display_name, condition, from_symbol, to_symbol, role in FIELD:
        rules: tuple[TiltRule, ...] = ()
        if condition is not None:
            rules = (
                TiltRule(
                    condition=condition,
                    on_symbol=ON_SYMBOL,
                    from_symbol=from_symbol,
                    to_symbol=to_symbol,
                    shift_pct=SHIFT,
                ),
            )
        cards.append(
            AllocationCard(
                agent_id=agent_id,
                display_name=display_name,
                purpose=Purpose.SAVINGS,
                thesis=_thesis(agent_id, condition, from_symbol, to_symbol, role),
                falsification=_FALSIFICATION,
                sleeves=sleeves,
                band_pct=BAND,
                rules=rules,
                designed_through=DESIGN_THROUGH,
            )
        )
    return cards


def check_taxable_disjointness(cards: list[AllocationCard]) -> list[str]:
    """Every sleeve ticker in this taxable field that a live `roth` card already claims."""
    claimed = roth_union()
    used = {sleeve.symbol for card in cards for sleeve in card.sleeves}
    return sorted(used & claimed)


def smoke(card_id: str, start: dt.date, end: dt.date) -> int:
    """Run ONE card through `run_allocation` over a short window, to prove the card is runnable.

    Not a measurement and not part of the round: one window, no control comparison, and the numbers
    it prints are reported nowhere. It exists because a field that validates as JSON and cannot
    actually be executed is the failure this programme has shipped before -- a green suite is not a
    running engine. The store is single-writer; if another process holds it this prints the error and
    returns non-zero rather than retrying.
    """
    os.environ.setdefault("INVDASH_MACRO_PIN", str(MACRO_PIN))
    from app.config import get_settings
    from app.paperdesk.desk import _mandate as desk_mandate
    from app.tournament.allocation import run_allocation

    card = next(c for c in build() if c.agent_id == card_id)
    settings = get_settings()
    mandate = desk_mandate(Purpose.SAVINGS)
    print(f"smoke   {card.agent_id}  {start} .. {end}  (mandate ${mandate.starting_cash:,.0f})")
    if card.rules:
        print(f"        condition: {card.rules[0].condition}")
    result = run_allocation(card, settings=settings, mandate=mandate, start=start, end=end)
    print(
        f"        sessions {result.sessions}  total_return {float(result.total_return):+.4%}  "
        f"max_drawdown {float(result.max_drawdown):.4%}  "
        f"benchmark(SPY) {float(result.benchmark_return or 0):+.4%}"
    )
    print(f"        trades {len(result.trades)}  rejections {len(result.rejections)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Author round 38's field.")
    parser.add_argument("--write", action="store_true", help="write the cards to the round directory")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="run one card through run_allocation over a short window and exit",
    )
    parser.add_argument("--smoke-card", default="r38-realyield-hi-1")
    parser.add_argument("--smoke-start", default="2022-02-16")
    parser.add_argument("--smoke-end", default="2023-02-15")
    args = parser.parse_args(argv)

    if args.smoke:
        return smoke(
            args.smoke_card,
            dt.date.fromisoformat(args.smoke_start),
            dt.date.fromisoformat(args.smoke_end),
        )

    cards = build()
    weights = ", ".join(f"{s} {w}" for s, w in SLEEVES)
    print(f"built {len(cards)} cards  |  sleeves: {weights}  |  band {BAND}  shift {SHIFT}")
    print(f"{'agent_id':22} {'purpose':8} {'free#':>5}  condition")
    for card in cards:
        condition = card.rules[0].condition if card.rules else "(control -- no rule)"
        count = free_numbers(card)
        flag = "" if count <= 10 else "  OVER BUDGET"
        print(f"{card.agent_id:22} {card.purpose.value:8} {count:>5}  {condition}{flag}")

    over = [c.agent_id for c in cards if free_numbers(c) > 10]
    if over:
        print(f"\nREFUSING: {over} exceed PROTOCOL.md section 3 rule 3's ten free numbers")
        return 1

    collisions = check_taxable_disjointness(cards)
    claimed = roth_union()
    print(f"\nroth union (live, {len(claimed)} tickers): {' '.join(sorted(claimed))}")
    if collisions:
        print(f"REFUSING: taxable sleeves {collisions} are claimed by a live roth card")
        raise RothCollision(f"taxable/roth ticker collision: {collisions}")
    print("taxable/roth disjointness: OK -- no sleeve here is claimed by a roth card")

    if not args.write:
        print("\n(dry run -- pass --write to author the field)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    for card in cards:
        path = OUT / f"{card.agent_id}.json"
        path.write_text(card.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {len(cards)} cards to {OUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
