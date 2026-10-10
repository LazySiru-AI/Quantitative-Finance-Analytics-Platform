"""Round 46: do two independent de-risking reads stack additively on the savings book?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round46.py
    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round46.py --write
    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round46.py --smoke

`ROUND-46-PLAN.md` is the pre-registration this executes. Read it first; this file only authors the
field and refuses to author an illegal one.

**What is new here, stated precisely.** Round 43 measured two INDEPENDENT single-sleeve reads on the
identical savings book: `r43-price-placebo-spy` (equity sleeve, `SPY close < sma(200) -> SPY->BIL`,
+0.94pp drawdown margin) and `r43-agg-trend-bil` (bond sleeve, `AGG close < sma(200) -> AGG->BIL`,
+1.34pp). Each moved the book's drawdown by about a point on its own. This round asks whether they
stack: does a card that carries BOTH conditions move the drawdown by roughly the SUM of the two
single-sleeve margins (independent signals) or by something closer to ONE of them alone (the same
signal read twice, because SPY's and AGG's 200-day trends are correlated in a broad drawdown)? Two
further cards test whether adding a third rule -- Creator A's metals destination or Creator B's trim-after-gains -- improves the two-sleeve stack any further.

**`r46-spy-derisk` and `r46-agg-derisk` are `r43-price-placebo-spy` and `r43-agg-trend-bil`
reproduced VERBATIM.** `check_r43_drift` below re-reads those two cards from
`data/rounds/r43-2026-09/cards/` and refuses to write (or continue a dry run) if a single field of
either rule has drifted from what this module hard-codes -- the two rounds' numbers are only
comparable if the reused cards are byte-identical, not merely similarly-described.

**This round is price-only.** No `macro(...)` term appears anywhere in this field and
`INVDASH_MACRO_PIN` is never set -- identical to round 43, unlike round 38.

**Nothing here is searched.** The base allocation, band and shift are round 38's and round 43's own
figures, reused unmodified. `sma(200)` is the textbook constant already frozen in
`app.evolution.ruleforms`. The trim threshold, `sma(200) * 1.15`, is Creator B's own figure
(`PERSONA-DISCUSSION-2026-09-09.md` line 135, and round 44's trim arm), reused unmodified rather than
re-derived. See `ROUND-46-PLAN.md` section 3.

**The support of each condition, AND the pairwise overlap of the two single-sleeve conditions, are
measured against the live bar store, not assumed.** `support_table` and `overlap_fraction` below read
price only -- no return series, no card, no window outcome -- and the plain dry run prints both every
time. The overlap figure is this round's pre-registered independence read (`ROUND-46-PLAN.md` section
6): if the SPY-derisk and AGG-derisk conditions were independent, the joint fraction would equal the
product of the two marginal fractions; a joint fraction well above that product means the two reads
fire together far more often than chance, which is the mechanical reason a stacked card's margin would
fall short of the sum of its parts.

**A disclosed deviation from round 43's ten-free-number refusal.** `free_numbers` below is the
IDENTICAL method `round43.free_numbers` and `round38.free_numbers` use (weights + band, counted in
full, plus each rule's condition literals and its own shift). Round 43 and round 38 never carried more
than one rule per card, so their tools refuse to write any card whose count exceeds
PROTOCOL.md section 3 rule 3's budget of ten. This round's whole point is to test whether two (or
three) rules that EACH ALREADY CLEARED that budget on their own -- `r46-spy-derisk` and
`r46-agg-derisk` at 7 apiece, reproduced verbatim from a round that already ran them -- combine when
stacked on one card. Stacking necessarily raises the count (`r46-both` 9, `r46-both-gld` 11,
`r46-both-trim` 12) without introducing a single new searched threshold: every literal in every
stacked rule is inherited from a card this programme has already authored and, for the two AGG/SPY
rules, already run. `main` below PRINTS every count and flags every card over ten; it does NOT refuse
to write on that basis (unlike `round43.main`) -- only a roth/taxable collision or drift against the
r43 cards refuses. `ROUND-46-PLAN.md` section 4 states this deviation in the same place the plan
states every other budget number, so a reader sees it beside the count, not buried in code.

**Not investment advice.** Nothing in this field is promotable; a measurement round promotes nothing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
from decimal import Decimal

import pandas as pd

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

OUT = REPO / "data" / "rounds" / "r46-2026-09" / "cards"

#: The r43 cards this round reproduces verbatim -- read live, never pasted, so drift is caught rather
#: than silently trusted. See `check_r43_drift`.
_R43_CARDS_DIR = REPO / "data" / "rounds" / "r43-2026-09" / "cards"
_R43_SPY_PLACEBO = _R43_CARDS_DIR / "r43-price-placebo-spy.json"
_R43_AGG_PRIMARY = _R43_CARDS_DIR / "r43-agg-trend-bil.json"

#: The earliest window in this round's ladder (`h10y-1`, `strategy-program/tools/windows.py`),
#: identical to round 43's `SUPPORT_FROM` -- the support and overlap screens below are measured over
#: exactly this span through `DESIGN_THROUGH`.
SUPPORT_FROM = dt.date(2013, 9, 3)

#: The base allocation, identical on every card in the field including the control -- round 38's and
#: round 43's own figures, reused unmodified. SPY is 30% because that is the savings benchmark's own
#: equity share (`30-70-spy-agg`); AGG/GLD/BIL split the remaining 70%.
SLEEVES: tuple[tuple[str, str], ...] = (
    ("SPY", "0.30"),
    ("AGG", "0.50"),
    ("GLD", "0.10"),
    ("BIL", "0.10"),
)

#: Round 38's and round 43's own band, reused unmodified.
BAND = Decimal("0.05")

#: Round 38's and round 43's own shift -- ten points of the whole book on every rule in this field,
#: deliberately larger than `BAND` so a firing rule always breaches and is guaranteed to be expressed
#: as a trade rather than absorbed by drift. Every rule below uses this SAME constant, so a stacked
#: card that fires two rules simultaneously moves twenty points, not ten -- see `ROUND-46-PLAN.md`
#: section 7's opportunity-cost discussion.
SHIFT = Decimal("0.10")

#: `(condition, on_symbol, from_symbol, to_symbol)`. The four distinct rules this round's seven cards
#: are built from. `RULE_SPY_DERISK` and `RULE_AGG_DERISK` are `r43-price-placebo-spy`'s and
#: `r43-agg-trend-bil`'s rules, reproduced verbatim -- see `check_r43_drift`.
RULE_SPY_DERISK: tuple[str, str, str, str] = ("close < sma(200)", "SPY", "SPY", "BIL")
RULE_AGG_DERISK: tuple[str, str, str, str] = ("close < sma(200)", "AGG", "AGG", "BIL")
#: Creator A's metals-in-stress destination -- `r43-gld-trend`'s rule, reproduced verbatim: rotate
#: bonds into gold only while gold's OWN trend confirms.
RULE_GLD_DEST: tuple[str, str, str, str] = ("close > sma(200)", "GLD", "AGG", "GLD")
#: Creator B's trim-after-gains on the equity sleeve (`PERSONA-DISCUSSION-2026-09-09.md` line
#: 135: "a price-extension trim is expressible: exit when `close > sma(200) * 1.15`"; the identical
#: threshold round 44's trim arm used). Framed here as a `TiltRule` (SPY -> BIL) rather than round 44's
#: `StrategyCard` entry/exit pair, because this round's card shape is `AllocationCard`.
RULE_TRIM_HIGH: tuple[str, str, str, str] = ("close > sma(200) * 1.15", "SPY", "SPY", "BIL")

#: `(agent_id, display_name, rules, role)`. `rules` is a tuple of `(condition, on_symbol, from_symbol,
#: to_symbol)` tuples, in the order the card carries them (empty for the control).
FIELD: tuple[
    tuple[str, str, tuple[tuple[str, str, str, str], ...], str], ...
] = (
    (
        "r46-control",
        "Two-sleeve de-risk control (no tilt)",
        (),
        "control",
    ),
    (
        "r46-spy-derisk",
        "SPY below its 200-day mean -> defensive (cash)",
        (RULE_SPY_DERISK,),
        "equity-sleeve read alone -- r43's placebo, reproduced verbatim",
    ),
    (
        "r46-agg-derisk",
        "AGG below its 200-day mean -> defensive (cash)",
        (RULE_AGG_DERISK,),
        "bond-sleeve read alone -- r43's primary treatment, reproduced verbatim",
    ),
    (
        "r46-both",
        "Both sleeves de-risk independently",
        (RULE_SPY_DERISK, RULE_AGG_DERISK),
        "additivity test -- the two single-sleeve reads stacked on one card",
    ),
    (
        "r46-both-gld",
        "Both sleeves de-risk + metals rotation when AGG is weak and GLD confirms",
        (RULE_SPY_DERISK, RULE_AGG_DERISK, RULE_GLD_DEST),
        "both + Creator A's metals-in-stress destination",
    ),
    (
        "r46-trim-high",
        "SPY more than 15% above its 200-day mean -> trim to cash",
        (RULE_TRIM_HIGH,),
        "Creator B's trim-after-gains on the equity sleeve, alone",
    ),
    (
        "r46-both-trim",
        "Both sleeves de-risk + trim the equity sleeve after exceptional gains",
        (RULE_SPY_DERISK, RULE_AGG_DERISK, RULE_TRIM_HIGH),
        "both + Creator B's trim",
    ),
)


class RothCollision(RuntimeError):
    """A sleeve in this taxable field is claimed by a live `roth`-purpose card."""


class R43Drift(RuntimeError):
    """`r46-spy-derisk` or `r46-agg-derisk` no longer matches its r43 source card byte for byte."""


def roth_union() -> frozenset[str]:
    """Every ticker claimed by a live `roth`-purpose card, recomputed from the library.

    Identical to `round43.roth_union` / `round38.roth_union` -- walked live from
    `app.evolution.promotion._library_cards` (all six tiers) rather than pasted from a memo.
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
    """Count the free numbers in one parsed expression tree -- identical to `round43._literals`."""
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

    Identical method to `round43.free_numbers` / `round38.free_numbers`: every sleeve's target
    weight, the band, and per rule the literals in its condition plus its own shift. Weights counted
    in full, not as `n - 1` "independent" numbers -- counting generously is the direction that cannot
    flatter a card. Unlike round 43, a card here may carry more than one rule, so the sum runs over
    every rule the card has (see this module's docstring for why a stacked card's count legitimately
    exceeds ten without a new search having occurred).
    """
    total = len(card.sleeves) + 1  # weights + band_pct
    for rule in card.rules:
        total += _literals(grammar.parse(rule.condition))
        total += 1  # shift_pct (or shift_expr, which none of this field uses)
    return total


def check_r43_drift() -> list[str]:
    """Every way `r46-spy-derisk` / `r46-agg-derisk` no longer match their r43 source cards.

    Reads `r43-price-placebo-spy.json` and `r43-agg-trend-bil.json` live from
    `data/rounds/r43-2026-09/cards/` and compares `(condition, on_symbol, from_symbol, to_symbol,
    shift_pct)` against `RULE_SPY_DERISK` / `RULE_AGG_DERISK` and `SHIFT`. An empty list means no
    drift. A missing file is itself reported as drift, not silently skipped.
    """
    problems: list[str] = []
    checks = (
        ("r46-spy-derisk", _R43_SPY_PLACEBO, RULE_SPY_DERISK),
        ("r46-agg-derisk", _R43_AGG_PRIMARY, RULE_AGG_DERISK),
    )
    for agent_id, path, expected in checks:
        if not path.exists():
            problems.append(f"{agent_id}: source card {path} does not exist")
            continue
        source = AllocationCard.model_validate_json(path.read_text(encoding="utf-8"))
        if len(source.rules) != 1:
            problems.append(
                f"{agent_id}: source card {path.name} has {len(source.rules)} rules, expected 1"
            )
            continue
        rule = source.rules[0]
        actual = (rule.condition, rule.on_symbol, rule.from_symbol, rule.to_symbol)
        if actual != expected:
            problems.append(f"{agent_id}: source rule {actual} != pinned {expected}")
        if rule.shift_pct != SHIFT:
            problems.append(f"{agent_id}: source shift_pct {rule.shift_pct} != pinned {SHIFT}")
    return problems


_COMMON = (
    "Round 46 pre-registered cell, on the taxable savings book ($100,000 lump sum, 10-20 year "
    "horizon, benchmark 30/70 SPY/AGG, mandate: lowest drawdown of the three books, least return "
    "accepted). Base allocation on every card in this field, including the control: 30% SPY, 50% "
    "AGG, 10% GLD, 10% BIL -- round 38's and round 43's own figures, reused unmodified. This round "
    "asks whether two independently-measured de-risking reads (round 43: the SPY-sleeve placebo, "
    "+0.94pp drawdown margin; the AGG-sleeve primary, +1.34pp) stack additively when carried on one "
    "card, and whether adding a third rule -- Creator A's metals destination or Creator B's "
    "trim-after-gains -- improves the stack further. Every reported figure is treatment MINUS "
    "CONTROL, never treatment against the benchmark alone. It is not a proposal to trade anything, "
    "and nothing in a measurement round is promotable. Not investment advice."
)

_FALSIFICATION = (
    "This round's additivity hypothesis is wrong, in the informative direction, if r46-both's "
    "drawdown margin is NOT within +/-0.5pp of the sum of r46-spy-derisk's and r46-agg-derisk's own "
    "margins (P1) -- that would show the two reads are not independent, i.e. they fire on "
    "overlapping sessions of the same underlying drawdown rather than capturing two separable risks. "
    "It is also wrong if any card in this field moves the drawdown margin by more than a few points "
    "(P2) -- every prior savings tilt this programme has measured, including both single-sleeve "
    "reads this round stacks, has stayed inside a couple of points. It is wrong about the trim rule "
    "specifically if r46-trim-high does NOT show a CAGR drag with no drawdown benefit (P3) -- SPY "
    "trades more than 15% above its own 200-day mean on a meaningful minority of sessions, mostly "
    "inside sustained rallies, so a rule that steps out there is predicted to give back upside "
    "without shallowing a drawdown it was never positioned to prevent. It is wrong about the two "
    "add-on cards specifically if r46-both-gld or r46-both-trim improves r46-both's own drawdown "
    "margin by more than 0.5pp (P4) -- a third rule stacked on an already-stacked card is predicted "
    "to add cost (more trades, more whipsaw) without a compensating defensive benefit. b6m-2 and "
    "b1y-1 (the 2021-2022 bear windows) are in-sample to the corpus's bond-stress hypothesis, "
    "exactly as round 43 pre-registered, and are reported separately. See ROUND-46-PLAN.md section 5 "
    "for the full prediction set and section 6 for the pre-registered support and overlap tables."
)


def _thesis(rules: tuple[tuple[str, str, str, str], ...], role: str) -> str:
    if not rules:
        return (
            f"{_COMMON} This is the MANDATORY CONTROL: the same four sleeves and the same 5-point "
            "band with every tilt removed, so it carries no rule at all. It is not a treatment that "
            "never fires -- it is the static, periodically-rebalanced book every other card in the "
            "field is measured as a difference from."
        )
    lines = "; ".join(
        f"`{condition}` true of {on_symbol}'s own bars -> {SHIFT * 100:.0f} points move from "
        f"{from_symbol} into {to_symbol}"
        for condition, on_symbol, from_symbol, to_symbol in rules
    )
    return (
        f"{_COMMON} This cell's role: {role}. Rules, evaluated independently against each condition's "
        f"own symbol's bars (there is no cross-symbol operator in this engine): {lines}. When more "
        "than one rule fires on the same session, each moves its own ten points; the book does not "
        "treat a doubly-fired session specially. No return series was read while choosing any "
        "threshold in this field -- every condition and shift is reused, unmodified, from a card this "
        "programme has already authored (round 38, round 43, or round 44's trim arm, translated into "
        "this card shape's TiltRule). What WAS read and is disclosed rather than hidden is the "
        "support of each regressor and the pairwise overlap of the two single-sleeve conditions "
        "(ROUND-46-PLAN.md section 6): how often each condition fires, and how often the SPY and AGG "
        "conditions fire together -- both touch price only, never a return series, a card or a window "
        "outcome."
    )


def build() -> list[AllocationCard]:
    """The round's seven cards, deterministically. No I/O, no randomness, no store access."""
    sleeves = tuple(
        Sleeve(symbol=symbol, target_weight=Decimal(weight)) for symbol, weight in SLEEVES
    )
    cards: list[AllocationCard] = []
    for agent_id, display_name, rules_spec, role in FIELD:
        rules: tuple[TiltRule, ...] = tuple(
            TiltRule(
                condition=condition,
                on_symbol=on_symbol,
                from_symbol=from_symbol,
                to_symbol=to_symbol,
                shift_pct=SHIFT,
            )
            for condition, on_symbol, from_symbol, to_symbol in rules_spec
        )
        cards.append(
            AllocationCard(
                agent_id=agent_id,
                display_name=display_name,
                purpose=Purpose.SAVINGS,
                thesis=_thesis(rules_spec, role),
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
#: field actually uses, deduplicated across every card and every rule slot.
_SUPPORT_CONDITIONS: tuple[tuple[str, str], ...] = tuple(
    dict.fromkeys(
        (condition, on_symbol)
        for _aid, _name, rules_spec, _role in FIELD
        for condition, on_symbol, _f, _t in rules_spec
    )
)


def support_table(settings=None) -> dict[tuple[str, str], float | None]:
    """Fraction of sessions each condition is true of its own symbol, `SUPPORT_FROM` .. `DESIGN_THROUGH`.

    Identical method to `round43.support_table`: reads price only (`read_frame`, no file lock),
    evaluates through the real grammar/evaluate call path, NA-as-false convention. A statement about
    the regressor, not a result.
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


def overlap_fraction(settings=None) -> float | None:
    """Fraction of sessions on which BOTH the SPY-derisk and AGG-derisk conditions are true.

    The pre-registered independence read (`ROUND-46-PLAN.md` section 6). Reads SPY's and AGG's own
    bars separately, evaluates each condition through the real grammar/evaluate path (identical to
    `support_table`), joins the two truth series on their `ts` column (an inner join -- a session
    missing from either symbol's history is dropped from the denominator rather than treated as
    false, so the joint fraction is measured only over sessions both symbols actually priced), and
    reports the joint true fraction. `fillna(False)` before the join -- an indicator's warmup NA
    counts as "condition not true", the identical convention `support_table` and `round40.
    _fires_per_symbol` use. Touches no return series, no card, no window outcome.
    """
    spy_condition, spy_symbol = RULE_SPY_DERISK[0], RULE_SPY_DERISK[1]
    agg_condition, agg_symbol = RULE_AGG_DERISK[0], RULE_AGG_DERISK[1]

    spy_frame = read_frame(
        spy_symbol, Interval.DAY, start=SUPPORT_FROM, end=DESIGN_THROUGH, settings=settings
    )
    agg_frame = read_frame(
        agg_symbol, Interval.DAY, start=SUPPORT_FROM, end=DESIGN_THROUGH, settings=settings
    )
    if spy_frame.empty or agg_frame.empty:
        return None

    spy_series = (
        evaluate(grammar.parse(spy_condition), spy_frame, interval=Interval.DAY)
        .fillna(False)
        .astype(bool)
    )
    agg_series = (
        evaluate(grammar.parse(agg_condition), agg_frame, interval=Interval.DAY)
        .fillna(False)
        .astype(bool)
    )

    spy_df = pd.DataFrame({"ts": spy_frame["ts"].to_numpy(), "spy_true": spy_series.to_numpy()})
    agg_df = pd.DataFrame({"ts": agg_frame["ts"].to_numpy(), "agg_true": agg_series.to_numpy()})
    joined = spy_df.merge(agg_df, on="ts", how="inner")
    if joined.empty:
        return None
    return float((joined["spy_true"] & joined["agg_true"]).mean())


def smoke(card_id: str, start: dt.date, end: dt.date) -> int:
    """Run ONE card through `run_allocation` over a short window, to prove the card is runnable.

    Not a measurement and not part of the round: one window, no control comparison, and the numbers
    it prints are reported nowhere. No macro pin is set -- this field is price-only.
    """
    from app.config import get_settings
    from app.paperdesk.desk import _mandate as desk_mandate
    from app.tournament.allocation import run_allocation

    card = next(c for c in build() if c.agent_id == card_id)
    settings = get_settings()
    mandate = desk_mandate(Purpose.SAVINGS)
    print(f"smoke   {card.agent_id}  {start} .. {end}  (mandate ${mandate.starting_cash:,.0f})")
    for rule in card.rules:
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
    parser = argparse.ArgumentParser(description="Author round 46's field.")
    parser.add_argument("--write", action="store_true", help="write the cards to the round directory")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="run one card through run_allocation over a short window and exit",
    )
    parser.add_argument("--smoke-card", default="r46-both")
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

    drift = check_r43_drift()
    if drift:
        print("REFUSING: r43 source cards have drifted from what round46.py pins:")
        for problem in drift:
            print(f"  - {problem}")
        raise R43Drift(f"r43 drift: {drift}")
    print("r43 reuse check: OK -- r46-spy-derisk and r46-agg-derisk match their r43 source cards byte for byte")

    cards = build()
    weights = ", ".join(f"{s} {w}" for s, w in SLEEVES)
    print(f"\nbuilt {len(cards)} cards  |  sleeves: {weights}  |  band {BAND}  shift {SHIFT}")
    print(f"{'agent_id':16} {'purpose':8} {'free#':>5}  rules")
    for card in cards:
        count = free_numbers(card)
        flag = "" if count <= 10 else "  OVER 10 (stacked rules -- see module docstring, expected)"
        if card.rules:
            rules_desc = "; ".join(
                f"{r.on_symbol}:{r.condition}->{r.to_symbol}" for r in card.rules
            )
        else:
            rules_desc = "(control -- no rule)"
        print(f"{card.agent_id:16} {card.purpose.value:8} {count:>5}  {rules_desc}{flag}")

    print(f"\nsupport of each condition, {SUPPORT_FROM} .. {DESIGN_THROUGH} (live store, price only):")
    support = support_table(settings=settings)
    for (condition, on_symbol), frac in support.items():
        shown = "n/a (no bars)" if frac is None else f"{frac:.1%}"
        print(f"  {on_symbol:5} {condition:24} true on {shown} of sessions")

    print(
        f"\npairwise overlap, {SUPPORT_FROM} .. {DESIGN_THROUGH} (both SPY-derisk AND AGG-derisk true, "
        "joined on date -- the pre-registered independence read, ROUND-46-PLAN.md section 6):"
    )
    joint = overlap_fraction(settings=settings)
    spy_support = support.get((RULE_SPY_DERISK[0], RULE_SPY_DERISK[1]))
    agg_support = support.get((RULE_AGG_DERISK[0], RULE_AGG_DERISK[1]))
    if joint is None or spy_support is None or agg_support is None:
        print("  n/a (missing bars for SPY or AGG over this span)")
    else:
        independent_expectation = spy_support * agg_support
        print(f"  actual joint fraction        : {joint:.1%}")
        print(f"  if independent (spy x agg)   : {independent_expectation:.1%}")
        ratio = joint / independent_expectation if independent_expectation else float("nan")
        print(f"  actual / independent-expected : {ratio:.2f}x")

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
