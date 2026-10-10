"""Round 43: does the BOND sleeve's own trend decide how defensive a savings book should be?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round43.py
    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round43.py --write
    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round43.py --smoke

`ROUND-43-PLAN.md` is the pre-registration this executes. Read it first; this file only authors the
field and refuses to author an illegal one.

**What is new here, stated precisely, because it is the round's whole justification.** Every savings
tilt this programme has run -- the allocation family's ATR-tilt, round 38's real-yield and price
placebo cards -- reads its condition off the EQUITY sleeve's own bars (`SPY`) or a macro series, and
moves weight OUT of equity. The bond sleeve (`AGG`) has been held at a static target, rebalanced only
by the drift band, in every card this programme has ever run. `PERSONA-DISCUSSION-2026-09-09.md` §3
supplies a hypothesis this gap has never tested: the corpus's savings-relevant theme is that the BOND
sleeve is the risk (Creator D: rising bond yields; Creator A: precious metals during macro stress).
This round reads AGG's and GLD's own bars instead of SPY's, on the identical book and card shape round
38 already used, and reproduces round 38's placebo VERBATIM as the within-round comparator.

**This round is price-only.** No `macro(...)` term appears anywhere in this field and
`INVDASH_MACRO_PIN` is never set -- unlike round 38, a `TiltRule` here needs nothing from FRED.

**Nothing here is searched.** The base allocation, band and shift are round 38's own figures, reused
unmodified so this round varies exactly one thing -- which sleeve's bars a condition reads, and where
the shifted weight goes (PROTOCOL.md section 7). `sma(200)` is the textbook constant already frozen in
`app.evolution.ruleforms`; `sma(100)` is Creator C's own working timeframe (20 weeks x 5 sessions),
kept as a stated sensitivity pair per section 3 rule 4, not a sweep. See `ROUND-43-PLAN.md` section 4.

**The support of each condition is measured against the live bar store, not assumed.** `support_table`
below reads price only (via `app.market.store.read_frame`, `app.rules.grammar.parse` and
`app.rules.evaluate.evaluate`) -- no return series, no card, no window outcome -- and the plain dry run
prints it every time, so the plan's disclosed support figures cannot silently drift from what the store
actually holds. See `ROUND-43-PLAN.md` section 6.

**Not investment advice.** Nothing in this field is promotable; a measurement round promotes nothing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
from decimal import Decimal

from app.db.duck import Interval
from app.market.store import read_frame
from app.rules import grammar
from app.rules.evaluate import evaluate
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

OUT = REPO / "data" / "rounds" / "r43-2026-09" / "cards"

#: The earliest window in this round's ladder (`h10y-1`, `strategy-program/tools/windows.py`). The
#: support screen below is measured over exactly this span through `DESIGN_THROUGH`, so the disclosed
#: fraction matches what the round's own windows would see.
SUPPORT_FROM = dt.date(2013, 9, 3)

#: The base allocation, identical on every card in the field including the control -- round 38's own
#: figures (`round38.SLEEVES`), reused unmodified rather than re-chosen, because this round varies the
#: tilt's sleeve and destination and nothing else (PROTOCOL.md section 7). SPY is 30% because that is
#: the savings benchmark's own equity share (`30-70-spy-agg`); AGG/GLD/BIL split the remaining 70%.
#:
#: Every sleeve's history clears every window this round uses. First bars, read live from the store:
#: SPY 1993-01-29, AGG 2003-09-29, GLD 2004-11-18, BIL 2007-05-30. The earliest window is `h10y-1`
#: (2013-09-03), so no sleeve binds.
SLEEVES: tuple[tuple[str, str], ...] = (
    ("SPY", "0.30"),
    ("AGG", "0.50"),
    ("GLD", "0.10"),
    ("BIL", "0.10"),
)

#: Round 38's own band, reused unmodified -- see `SLEEVES`'s docstring.
BAND = Decimal("0.05")

#: Round 38's own shift -- ten points of the whole book, deliberately larger than `BAND` so a firing
#: rule always breaches and is guaranteed to be expressed as a trade rather than absorbed by drift.
SHIFT = Decimal("0.10")

#: `(agent_id, display_name, condition, on_symbol, from_symbol, to_symbol, role)`. A `condition` of
#: `None` is the control -- no rule at all, not a rule that never fires. Unlike round 38 (every rule
#: read SPY's bars), `on_symbol` varies per card here -- that variation IS this round's treatment.
FIELD: tuple[tuple[str, str, str | None, str, str, str, str], ...] = (
    (
        "r43-control",
        "Bond-sleeve control (no tilt)",
        None,
        "",
        "",
        "",
        "control",
    ),
    (
        "r43-agg-trend-bil",
        "AGG below its 200-day mean -> defensive (cash)",
        "close < sma(200)",
        "AGG",
        "AGG",
        "BIL",
        "primary treatment",
    ),
    (
        "r43-agg-trend-gld",
        "AGG below its 200-day mean -> defensive (metals)",
        "close < sma(200)",
        "AGG",
        "AGG",
        "GLD",
        "Creator A's metals-in-stress destination",
    ),
    (
        "r43-agg-trend-bil-sma100",
        "AGG below its 100-day mean -> defensive (cash)",
        "close < sma(100)",
        "AGG",
        "AGG",
        "BIL",
        "threshold sensitivity (section 3 rule 4 insensitivity check)",
    ),
    (
        "r43-gld-trend",
        "GLD above its 200-day mean -> rotate bonds into metals",
        "close > sma(200)",
        "GLD",
        "AGG",
        "GLD",
        "trend-confirmed metals tilt",
    ),
    (
        "r43-price-placebo-spy",
        "SPY below its 200-day mean -> defensive (cash)",
        "close < sma(200)",
        "SPY",
        "SPY",
        "BIL",
        "round 38's placebo, reproduced verbatim -- this round's comparator",
    ),
)


class RothCollision(RuntimeError):
    """A sleeve in this taxable field is claimed by a live `roth`-purpose card."""


def roth_union() -> frozenset[str]:
    """Every ticker claimed by a live `roth`-purpose card, recomputed from the library.

    Identical to `round38.roth_union` -- walked live from `app.evolution.promotion._library_cards`
    (all six tiers) rather than pasted from a memo, for the identical reason: a hard-coded forbidden
    list is a second copy of a fact that drifts silently.
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
    """Count the free numbers in one parsed expression tree -- identical to `round38._literals`.

    Both bare literals (`> 1.0`) and an indicator's numeric arguments (`sma(200)`) count, because both
    are numbers an analyst chose and either could have been tuned.
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

    Identical method to `round38.free_numbers`: every sleeve's target weight, the band, and per rule
    the literals in its condition plus its own shift. Weights counted in full, not as `n - 1`
    "independent" numbers -- counting generously is the direction that cannot flatter a card.
    """
    total = len(card.sleeves) + 1  # weights + band_pct
    for rule in card.rules:
        total += _literals(grammar.parse(rule.condition))
        total += 1  # shift_pct (or shift_expr, which none of this field uses)
    return total


_COMMON = (
    "Round 43 pre-registered cell, on the taxable savings book ($100,000 lump sum, 10-20 year "
    "horizon, benchmark 30/70 SPY/AGG, mandate: lowest drawdown of the three books, least return "
    "accepted). Base allocation on every card in this field, including the control: 30% SPY, 50% "
    "AGG, 10% GLD, 10% BIL -- round 38's own figures, reused unmodified. Cards differ in exactly one "
    "thing -- which sleeve's bars the tilt condition reads, and where the shifted weight goes -- and "
    "this round reports treatment MINUS CONTROL, never treatment against the benchmark alone. Every "
    "savings tilt this programme has previously run (the allocation family's ATR-tilt, round 38's "
    "real-yield and price-placebo cards) read the EQUITY sleeve's own bars or a macro series; this "
    "round reads the BOND sleeve's own bars instead, on the hypothesis (from "
    "PERSONA-DISCUSSION-2026-09-09.md section 3: Creator D on rising bond yields, Creator A on "
    "metals during macro stress) that the bond sleeve, not the equity sleeve, is the source of risk "
    "this book should read. The programme's prior is a null: round 38 measured every macro-conditioned "
    "savings tilt inside a fraction of a point of drawdown, beaten by its own price-only placebo. This "
    "round predicts a null too (see strategy-program/ROUND-43-PLAN.md section 5); it earns its place "
    "by testing an unread sleeve, not by expecting a different answer. It is not a proposal to trade "
    "anything, and nothing in a measurement round is promotable. Not investment advice."
)

_FALSIFICATION = (
    "This round's hypothesis is wrong, not merely unlucky, if the treatment-minus-control margin in "
    "max drawdown and MAR for r43-agg-trend-bil is a fraction of a percentage point across the "
    "eligible 5y and 10y rungs -- the pre-registered primary prediction (P1). It is also wrong, in the "
    "more interesting direction the round exists to test, if r43-agg-trend-bil does not beat "
    "r43-price-placebo-spy (round 38's own best cell, +0.94pp drawdown margin, reproduced verbatim in "
    "this field) on the drawdown margin (P2) -- that would show the bond-sleeve read adds nothing over "
    "the equity-sleeve read this programme has already measured. Named failure regimes: a 2013 "
    "taper-tantrum-style whipsaw where a bond-trend break reverts within weeks, and the 2019 bond "
    "rally the tilt sits out. Two of this round's fifteen windows (b6m-2, b1y-1) fall inside the "
    "2021-2022 regime the corpus's bond-stress claim was voiced after publication of the underlying "
    "notes was made with 2022 already known -- a margin appearing only there is hindsight, not a "
    "finding. See ROUND-43-PLAN.md section 5 for the full prediction set and section 6 for the "
    "pre-registered support-of-regressor table."
)


def _thesis(condition: str | None, on_symbol: str, from_symbol: str, to_symbol: str, role: str) -> str:
    if condition is None:
        return (
            f"{_COMMON} This is the MANDATORY CONTROL: the same four sleeves and the same 5-point "
            "band with every tilt removed, so it carries no rule at all. It is not a treatment that "
            "never fires -- it is the static, periodically-rebalanced book every other card in the "
            "field is measured as a difference from."
        )
    return (
        f"{_COMMON} This cell's role: {role}. When `{condition}` is true of {on_symbol}'s own bars -- "
        f"there is no cross-symbol operator in this engine, so the condition is evaluated against "
        f"{on_symbol}'s own price history only -- ten points of the whole book move from {from_symbol} "
        f"into {to_symbol}. Ten points is deliberately larger than the 5-point band: a shift smaller "
        "than the band could be absorbed by it and never trade, leaving a tilt that is present, "
        "plausible and unread. The threshold is a round number fixed by a concept before any "
        "measurement in this round existed (ROUND-43-PLAN.md section 4 justifies each individually), "
        "and no return series was read while choosing it -- what WAS read and is disclosed rather "
        "than hidden is the support of the regressor itself (section 6): how often this condition "
        "fires, which touches no price outcome and no card."
    )


def build() -> list[AllocationCard]:
    """The round's six cards, deterministically. No I/O, no randomness, no store access."""
    sleeves = tuple(
        Sleeve(symbol=symbol, target_weight=Decimal(weight)) for symbol, weight in SLEEVES
    )
    cards: list[AllocationCard] = []
    for agent_id, display_name, condition, on_symbol, from_symbol, to_symbol, role in FIELD:
        rules: tuple[TiltRule, ...] = ()
        if condition is not None:
            rules = (
                TiltRule(
                    condition=condition,
                    on_symbol=on_symbol,
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
                thesis=_thesis(condition, on_symbol, from_symbol, to_symbol, role),
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


#: `(condition, on_symbol)` pairs whose support is worth disclosing -- every distinct condition this
#: field actually uses, deduplicated (the control has none; `r43-agg-trend-bil` and
#: `r43-agg-trend-gld` share one).
_SUPPORT_CONDITIONS: tuple[tuple[str, str], ...] = tuple(
    dict.fromkeys(
        (condition, on_symbol)
        for _aid, _name, condition, on_symbol, _f, _t, _role in FIELD
        if condition is not None
    )
)


def support_table(settings=None) -> dict[tuple[str, str], float | None]:
    """Fraction of sessions each condition is true of its own symbol, `SUPPORT_FROM` .. `DESIGN_THROUGH`.

    Reads price only -- `read_frame` (an in-memory store read, no file lock) -- and evaluates the
    identical parsed tree `run_allocation` would, through `app.rules.grammar.parse` and
    `app.rules.evaluate.evaluate`. Touches no return series, no card, no window outcome: a statement
    about the regressor, not a result. NA (indicator warmup, the first `sma(N)` sessions) is treated
    as false, the identical convention `round40._fires_per_symbol` uses -- the denominator is every
    session in range, not just the post-warmup ones, so a support figure is not silently inflated by
    dropping the sessions on which the condition could not yet evaluate.
    """
    out: dict[tuple[str, str], float | None] = {}
    for condition, on_symbol in _SUPPORT_CONDITIONS:
        frame = read_frame(
            on_symbol, Interval.DAY, start=SUPPORT_FROM, end=DESIGN_THROUGH, settings=settings
        )
        if frame.empty:
            out[(condition, on_symbol)] = None
            continue
        tree = grammar.parse(condition)
        series = evaluate(tree, frame, interval=Interval.DAY)
        out[(condition, on_symbol)] = (
            float(series.fillna(False).astype(bool).mean()) if len(series) else None
        )
    return out


def smoke(card_id: str, start: dt.date, end: dt.date) -> int:
    """Run ONE card through `run_allocation` over a short window, to prove the card is runnable.

    Not a measurement and not part of the round: one window, no control comparison, and the numbers
    it prints are reported nowhere. No macro pin is set -- this field is price-only. The store is
    single-writer; if another process holds it this prints the error and returns non-zero rather than
    retrying.
    """
    from app.config import get_settings
    from app.paperdesk.desk import _mandate as desk_mandate
    from app.tournament.allocation import run_allocation

    card = next(c for c in build() if c.agent_id == card_id)
    settings = get_settings()
    mandate = desk_mandate(Purpose.SAVINGS)
    print(f"smoke   {card.agent_id}  {start} .. {end}  (mandate ${mandate.starting_cash:,.0f})")
    if card.rules:
        rule = card.rules[0]
        print(f"        condition: {rule.condition}  on {rule.on_symbol}  {rule.from_symbol} -> {rule.to_symbol}")
    result = run_allocation(card, settings=settings, mandate=mandate, start=start, end=end)
    print(
        f"        sessions {result.sessions}  total_return {float(result.total_return):+.4%}  "
        f"max_drawdown {float(result.max_drawdown):.4%}  "
        f"benchmark(SPY) {float(result.benchmark_return or 0):+.4%}"
    )
    print(f"        trades {len(result.trades)}  rejections {len(result.rejections)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Author round 43's field.")
    parser.add_argument("--write", action="store_true", help="write the cards to the round directory")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="run one card through run_allocation over a short window and exit",
    )
    parser.add_argument("--smoke-card", default="r43-agg-trend-bil")
    parser.add_argument("--smoke-start", default="2025-02-18")
    parser.add_argument("--smoke-end", default="2026-02-13")
    args = parser.parse_args(argv)

    if args.smoke:
        return smoke(
            args.smoke_card,
            dt.date.fromisoformat(args.smoke_start),
            dt.date.fromisoformat(args.smoke_end),
        )

    from app.config import get_settings

    settings = get_settings()

    cards = build()
    weights = ", ".join(f"{s} {w}" for s, w in SLEEVES)
    print(f"built {len(cards)} cards  |  sleeves: {weights}  |  band {BAND}  shift {SHIFT}")
    print(f"{'agent_id':24} {'purpose':8} {'free#':>5}  on_symbol  condition")
    for card in cards:
        rule = card.rules[0] if card.rules else None
        condition = rule.condition if rule else "(control -- no rule)"
        on_symbol = rule.on_symbol if rule else "-"
        count = free_numbers(card)
        flag = "" if count <= 10 else "  OVER BUDGET"
        print(f"{card.agent_id:24} {card.purpose.value:8} {count:>5}  {on_symbol:9}  {condition}{flag}")

    over = [c.agent_id for c in cards if free_numbers(c) > 10]
    if over:
        print(f"\nREFUSING: {over} exceed PROTOCOL.md section 3 rule 3's ten free numbers")
        return 1

    print(f"\nsupport of each condition, {SUPPORT_FROM} .. {DESIGN_THROUGH} (live store, price only):")
    support = support_table(settings=settings)
    for (condition, on_symbol), frac in support.items():
        shown = "n/a (no bars)" if frac is None else f"{frac:.1%}"
        print(f"  {on_symbol:5} {condition:20} true on {shown} of sessions")

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
