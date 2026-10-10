"""Round 42: level reclaim (wick rejection) and breakout quality (0.25-range confirmation).

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round42.py           # dry run
    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round42.py --write   # author the field

`ROUND-42-PLAN.md` is the pre-registration this executes. Read it first.

This authors the round's field and nothing else -- the cards are then run by
`strategy-program/tools/run_round.sh` and scored by `score.py`, exactly like every other card round.

**The question.** Two independent families, each testing one influencer persona's untested claim on
the taxable `trading` book, each contrasted against its OWN control (never against SPY, and never
against the other family's control):

- **Family A, "level reclaim"** (persona `creator-e` / Creator E): a wick rejection at a
  prior confirmed swing low -- the session pierced the level intrabar and closed back above it --
  beats a plain close-to-close reclaim of the same level. He pre-registered that this loses in
  range-bound consolidation.
- **Family B, "breakout quality"** (persona `creator-c` / Creator C): a breakout that first
  advances 0.25 x the prior range's height confirms; the level-only breakout does not distinguish real
  breaks from ones that stall. He pre-registered losses on gaps and in chop. Only the entry-side half
  of his claim is expressible -- see `ROUND-42-PLAN.md` section 6 for what is not.

**Why each arm's entry is a module constant, not retyped per card.** `FAMILIES` names every arm's
entry text exactly once; `build()` reads it to construct cards. There is no second, hand-typed copy of
any expression anywhere in this file. `tests/test_round42_field.py` asserts the pinned literal text by
construction rather than trusting it.

**The reachability gate.** Round 40 found a 4-sigma Bollinger threshold that could structurally never
fire (`sqrt(n-1)` bounds the achievable z-score at n=4) and passed every pre-flight gate anyway,
because eligibility asks whether an indicator can *warm up*, never whether a rule can ever be *true*.
So `--write` here measures every DISTINCT entry and exit against the actual bar store (bounded to
`DESIGN_THROUGH`) with `app.market.store.read_frame` (an in-memory DuckDB connection -- no file lock,
safe alongside other readers) and the real evaluator (`app.rules.grammar.parse` +
`app.rules.evaluate.evaluate`, so a "fire" is a session on which the expression is True under the same
DSL semantics the backtest evaluates). It REFUSES to write if any expression fires 0 times, or if any
ENTRY fires on more than 300 of every 1000 symbol-sessions -- a near-always-on entry that would not be
testing the claim at all, it would be testing "is the market open".

**Not investment advice. The round has NOT been run.** This file only authors and range-checks the
field; every number it prints is a firing count over price-only bars, not a return.
"""

from __future__ import annotations

import argparse
import pathlib
import re
from decimal import Decimal

from app.config import get_settings
from app.db.duck import Interval
from app.evolution.promotion import _library_cards
from app.evolution.universe import _TAXABLE_GROWTH
from app.market.store import read_frame
from app.rules import evaluate, grammar
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from app.tournament.purposes import Purpose

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r42-2026-09" / "cards"

#: The 12-name taxable growth pool, verbatim from `app.evolution.universe._TAXABLE_GROWTH`. Mechanically
#: defined by the pool, NOT chosen for this round -- large-cap tech/semiconductors, and therefore NOT
#: survivorship-free, the same limitation round 40 carried on this identical universe.
UNIVERSE: tuple[str, ...] = _TAXABLE_GROWTH

#: The kinds an arm can be. Every arm in this round is either the family's `control` (no confirmation
#: term) or a `treatment` (one confirmation term added). There is no negative control this round --
#: round 40 already established that pattern; this round's job is the two claims themselves.
CONTROL, TREATMENT = "control", "treatment"

#: Persona attribution, quoted (<=15 words each, see `ROUND-42-PLAN.md` section 1) and named in every
#: card's thesis so a reader does not have to cross-reference the plan to know whose claim a cell tests.
PERSONA_A = "Creator E (creator-e)"
PERSONA_B = "Creator C (creator-c)"

#: name -> {discipline, exit, arms: {arm -> (entry, kind)}, persona}. This is the ONE place every
#: entry and exit expression in the round is written down. `build()` reads it; nothing downstream
#: retypes an expression.
FAMILIES: dict[str, dict[str, object]] = {
    "reclaim": {
        "discipline": Discipline.MEAN_REVERSION,
        "persona": PERSONA_A,
        "exit": "close crosses_below swing_low(20)",
        "arms": {
            "control": ("close crosses_above swing_low(20)", CONTROL),
            "wick": ("low < swing_low(20) and close > swing_low(20)", TREATMENT),
            "wick-body": (
                "low < swing_low(20) and close > swing_low(20) and "
                "(close - open) > 0.5 * (high - low)",
                TREATMENT,
            ),
        },
    },
    "breakout": {
        "discipline": Discipline.BREAKOUT,
        "persona": PERSONA_B,
        "exit": "close crosses_below ema(20)",
        "arms": {
            "control": ("close crosses_above swing_high(20)", CONTROL),
            "q25": (
                "close crosses_above swing_high(20) + 0.25 * (swing_high(20) - swing_low(20))",
                TREATMENT,
            ),
        },
    },
}

#: Brackets, held IDENTICAL across every one of the 5 cards -- both families and every arm within them.
#: The only thing that varies between cards is the entry expression (and, across families, the exit and
#: the discipline label). Fixed per the round's pinning: stop 0.12, no take-profit, 150-day backstop,
#: 3 slots at 0.25 each.
STOP_LOSS_PCT = Decimal("0.12")
TAKE_PROFIT_PCT: Decimal | None = None
MAX_HOLD_DAYS = 150
MAX_POSITIONS = 3
POSITION_PCT = Decimal("0.25")

#: The reachability bound on an ENTRY: more than 300 fires per 1000 symbol-sessions is treated as
#: near-always-on -- a rule so loose it is not testing the persona's claim, it is testing whether the
#: market is open. Exits are exempt from this bound (an exit's job is to close positions promptly; a
#: high-firing exit is a short average hold, not a broken gate) but are still refused if they never fire.
MAX_FIRES_PER_1000 = 300

#: The programme's measured noise floor, `PROTOCOL.md` section 7. An arm "earns" something only if its
#: arm-minus-own-control median adjusted excess exceeds this AND survives BH q<0.10; stated here so the
#: plan and the tool cannot drift on the number.
NOISE_FLOOR_PP = 21.2

#: Matches every numeric literal in a rule expression, for the PROTOCOL section 3 parameter budget.
#: Same pattern round35/round36/round40 use.
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def free_numbers(card: StrategyCard) -> int:
    """PROTOCOL section 3's parameter count for one card: ten free numbers, "counted across `entry`,
    `exit`, the two brackets, the hold cap, slot count and position size".

    Distinct numeric *values* across the expressions (a value reused in entry and exit is one choice,
    not two), plus one per present bracket field, plus two for `max_positions` and `position_pct`. The
    identical convention `round35.py` / `round36.py` / `round40.py::free_numbers` use.
    """
    text = " ".join(part for part in (card.entry, card.exit, card.rank_by or "") if part)
    values = {match.group(0) for match in _NUMBER.finditer(text)}
    brackets = sum(
        1
        for field in (card.stop_loss_pct, card.take_profit_pct, card.max_hold_days)
        if field is not None
    )
    return len(values) + brackets + 2  # + max_positions + position_pct


def roth_union(settings) -> frozenset[str]:
    """Every ticker held by any live `roth`-purpose library card, recomputed from disk.

    A taxable card may not use any of these (`app.tournament.purposes` disjointness rule; Rev. Rul.
    2008-5). Recomputed via `app.evolution.promotion._library_cards`, which walks all six library tiers,
    rather than hardcoded, because concurrent sessions edit the library and a pasted constant is correct
    only until the next commit -- identical to `round40.py::roth_union`.
    """
    return frozenset(
        sym
        for card in _library_cards(settings)
        if getattr(card, "purpose", None) is Purpose.ROTH
        for sym in card.universe
    )


def _thesis(family: str, arm: str, kind: str, exit_expr: str, persona: str) -> str:
    if family == "reclaim":
        claim = (
            "the family's persona (Creator E / creator-e) pre-registered wick rejection at "
            "prior support with full-body candle confirmation as the one daily-bar principle from his "
            "method not yet tested here, and pre-registered that it loses in range-bound consolidation "
            "(PERSONA-DISCUSSION-2026-09-09.md section 3)."
        )
    else:
        claim = (
            "the family's persona (Creator C / creator-c) pre-registered that a genuine range "
            "breakout confirms by advancing 0.25 x the range height before it can be trusted, and that "
            "failed breakouts stall before reaching it; he pre-registered losses on gaps and in chop "
            "(PERSONA-DISCUSSION-2026-09-09.md section 3). His 1.0x-range profit target and 'within 5 "
            "days' clock are NOT expressible in this engine's DSL and are not part of this test -- see "
            "ROUND-42-PLAN.md section 6."
        )
    base = (
        f"Round 42, family '{family}' on the taxable trading book (persona: {persona}). Every arm in "
        f"this family shares the exit '{exit_expr}' and the fixed brackets (stop 0.12, no take-profit, "
        "150-day hold cap, 3 slots at 0.25 each); the ONLY thing that varies within the family is the "
        f"entry expression. {claim} "
    )
    if kind == CONTROL:
        arm_txt = (
            "This is the family's CONTROL: the plain level-crossing entry with no confirmation "
            "structure. Every treatment in this family is reported as arm-minus-THIS-control on median "
            "exposure-adjusted excess, never against SPY and never against the other family's control."
        )
    else:
        arm_txt = (
            "This is a TREATMENT: the control's entry with one confirmation term added (intrabar "
            "structure, a full-body candle, or a distance-past-the-level confirmation). A confirmation "
            "term can only REDUCE firings relative to its own control, so this arm takes fewer trades "
            "and carries lower exposure -- which is exactly why the metric is exposure-adjusted excess "
            "and not raw return."
        )
    tail = (
        " Pre-registered 2026-09-09, before any measurement. Nothing here is promotable -- the "
        "`trading` purpose is exempt from PROTOCOL.md section 6 promotion by the r21 amendment; this is "
        "a measurement study, report only. Not investment advice. See strategy-program/ROUND-42-PLAN.md."
    )
    return base + arm_txt + tail


def _falsification(family: str, kind: str) -> str:
    if family == "reclaim":
        regime = (
            "range-bound consolidation, per the persona's own pre-registered failure regime "
            "(support/resistance blur and wicks read as noise rather than institutional markers)."
        )
        pred = (
            "(1) wick-body takes fewer trades than wick, which takes fewer than the reclaim control "
            "(each added structural term can only filter further). "
        )
    else:
        regime = (
            "gapping markets where the 0.25 confirmation is crossed in a single overnight gap then "
            "reverses, and sideways/choppy markets where 0.25 arrives too late to matter -- both named "
            "by the persona."
        )
        pred = (
            "(1) q25 takes fewer trades and enters later than the breakout control, giving back early "
            "upside in strong trends (bull-2024, recent) while avoiding false starts in chop "
            "(chop-2015, chop-2011). "
        )
    common = (
        f"Honest prior: the null (rounds 17/18/34/38/39/40 put form, exit, rotation and confirmation "
        f"conjuncts all inside the {NOISE_FLOOR_PP}pp floor). Pre-registered predictions: {pred}"
        "(2) the sign of arm-minus-control flips by regime -- named failure regime: "
        f"{regime} -- so any single-window read is unsafe and only the eight-window median is "
        "interpreted. (3) An arm that fails the 5-of-8 regime gate and is unranked has been switched "
        "off, which is not the same finding as 'the confirmation did not help' -- the two must not be "
        "conflated. Decision rule: earns something only if arm-minus-own-control median adjusted excess "
        f"exceeds {NOISE_FLOOR_PP}pp AND survives BH q<0.10 over the field of 5 cells."
    )
    if kind == CONTROL:
        return "Baseline against which this family's treatments are measured. " + common
    return common


def build() -> list[StrategyCard]:
    """The 5-card field: family A (reclaim, 3 arms) + family B (breakout, 2 arms). Deterministic."""
    cards: list[StrategyCard] = []
    for family, spec in FAMILIES.items():
        discipline = spec["discipline"]
        exit_expr = spec["exit"]
        persona = spec["persona"]
        arms: dict[str, tuple[str, str]] = spec["arms"]  # type: ignore[assignment]
        for arm, (entry, kind) in arms.items():
            agent_id = f"r42-{family}-{arm}"
            cards.append(
                StrategyCard(
                    agent_id=agent_id,
                    display_name=f"{family} {arm}",
                    discipline=discipline,
                    purpose=Purpose.TRADING,
                    thesis=_thesis(family, arm, kind, exit_expr, persona),
                    falsification=_falsification(family, kind),
                    universe=UNIVERSE,
                    entry=entry,
                    exit=exit_expr,
                    stop_loss_pct=STOP_LOSS_PCT,
                    take_profit_pct=TAKE_PROFIT_PCT,
                    max_hold_days=MAX_HOLD_DAYS,
                    max_positions=MAX_POSITIONS,
                    position_pct=POSITION_PCT,
                    rank_by=None,
                    designed_through=DESIGN_THROUGH,
                )
            )
    return cards


def _distinct_expressions() -> dict[str, str]:
    """Every DISTINCT entry and exit expression across the round, keyed by a readable label.

    5 entries (one per card) + 2 exits (one per family, `reclaim`'s three arms share it and `breakout`'s
    two arms share it) = 7 expressions measured. Order matches the plan's reachability table.
    """
    out: dict[str, str] = {}
    for family, spec in FAMILIES.items():
        arms: dict[str, tuple[str, str]] = spec["arms"]  # type: ignore[assignment]
        for arm, (entry, _kind) in arms.items():
            out[f"{family}-{arm} (entry)"] = entry
        out[f"{family} (exit)"] = spec["exit"]  # type: ignore[assignment]
    return out


def _fires(expr: str, settings) -> int:
    """Number of sessions on which `expr` is True across the whole universe, bounded to DESIGN_THROUGH.

    An in-memory read (`read_frame`, no file lock) and the real evaluator, so a "fire" is exactly a
    session the DSL would have signalled True on. NA (warmup) is treated as False.
    """
    tree = grammar.parse(expr)
    total = 0
    for symbol in UNIVERSE:
        frame = read_frame(symbol, Interval.DAY, end=DESIGN_THROUGH, settings=settings)
        if frame.empty:
            continue
        series = evaluate.evaluate(tree, frame, interval=Interval.DAY)
        total += int(series.fillna(False).astype(bool).sum())
    return total


def reachability(settings) -> tuple[dict[str, dict[str, object]], int, list[str]]:
    """Measure every distinct entry and exit against the bar store; return (table, sessions, refusals).

    Refuses on: any expression firing 0 times; any ENTRY firing on more than `MAX_FIRES_PER_1000` of
    every 1000 symbol-sessions (a near-always-on entry that would not test the persona's claim at all).
    Exits are measured and printed but exempt from the per-1000 ceiling.
    """
    sessions = 0
    for symbol in UNIVERSE:
        sessions += len(read_frame(symbol, Interval.DAY, end=DESIGN_THROUGH, settings=settings))

    table: dict[str, dict[str, object]] = {}
    refusals: list[str] = []
    for label, expr in _distinct_expressions().items():
        is_exit = label.endswith("(exit)")
        fires = _fires(expr, settings)
        per_1000 = (1000 * fires / sessions) if sessions else float("inf")
        table[label] = {"expr": expr, "fires": fires, "per_1000": per_1000, "is_exit": is_exit}
        if fires == 0:
            refusals.append(f"{label}: '{expr}' fires 0 times -- structurally unreachable")
        elif not is_exit and per_1000 > MAX_FIRES_PER_1000:
            refusals.append(
                f"{label}: {per_1000:.1f}/1000 sessions > {MAX_FIRES_PER_1000}/1000 -- near-always-on entry"
            )
    return table, sessions, refusals


def _print_reachability(table: dict[str, dict[str, object]], sessions: int) -> None:
    print(f"reachability over {len(UNIVERSE)} names, {sessions} symbol-sessions, bounded to "
          f"{DESIGN_THROUGH.isoformat()}")
    print(f"  {'expression':70s}  {'fires':>7s}  {'per 1000':>9s}")
    print("  " + "-" * 92)
    for label, row in table.items():
        print(f"  {label:28s} {row['expr']!s:41s}  {int(row['fires']):>7d}  {row['per_1000']:>8.2f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the cards to the round directory")
    args = parser.parse_args(argv)

    settings = get_settings()
    cards = build()

    print(f"built {len(cards)} cards: {len(FAMILIES)} families ({', '.join(FAMILIES)})")
    for card in cards:
        print(f"  {card.agent_id:28s}  free_numbers={free_numbers(card)}")

    # Reachability probe -- printed on BOTH the dry run and the write.
    table, sessions, refusals = reachability(settings)
    print()
    _print_reachability(table, sessions)

    # Parameter budget.
    over_budget = [c.agent_id for c in cards if free_numbers(c) > 10]
    if over_budget:
        refusals.append(f"parameter budget: over 10 free numbers: {', '.join(over_budget)}")

    # Roth disjointness.
    roth = roth_union(settings)
    violation = sorted(set(UNIVERSE) & roth)
    print()
    print(f"roth union: {len(roth)} tickers; taxable universe intersects it in: "
          f"{violation if violation else 'nothing'}")
    if violation:
        refusals.append(f"roth disjointness: taxable universe uses roth tickers {violation}")

    if refusals:
        print()
        print("REFUSING to write -- the field is not clean:")
        for r in refusals:
            print(f"  - {r}")
        if not args.write:
            print("\n(dry run -- pass --write to author the field)")
        return 1

    if not args.write:
        print("\n(dry run -- field is clean; pass --write to author it)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    for card in cards:
        path = OUT / f"{card.agent_id}.json"
        path.write_text(card.model_dump_json(indent=2, exclude_none=False) + "\n", encoding="utf-8")
    print(f"\nwrote {len(cards)} cards to {OUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
