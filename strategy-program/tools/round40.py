"""Round 40: does an added confirmation conjunct pay for itself?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round40.py           # dry run
    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round40.py --write   # author the field

`ROUND-40-PLAN.md` is the pre-registration this executes. Read it first.

This authors the round's field and nothing else -- the cards are then run by
`strategy-program/tools/run_round.sh` and scored by `score.py`, exactly like every other card round.

**The question.** Hold one base entry fixed and vary only the confirmation term conjoined to it, on
the taxable `trading` book. Does the extra conjunct earn back the trades and exposure it costs? The
hypothesis under test is the influencer persona *creator-e*'s claim that "a signal is only
valid with a confirmation term" (the persona corpus is partly Korean-language and machine-summarised
-- a provenance caveat, and this is a fair test of the claim, not an endorsement of it).

**Why the entry is composed by string construction, not retyped.** Every arm's entry is
`BASE_ENTRY + " and " + <conjunct>`. The base is written down exactly once, in `BASE_ENTRY`, and each
treatment arm is that string plus its conjunct. Hand-retyping the full expression per arm would create
a second, drifting copy of the base and re-open the exact class of defect this round is built around
(see below). `tests/test_round40_field.py` asserts the construction rather than trusting it.

**The defect this round is designed AROUND: a reachability gate.** A parallel round tried
`close crosses_above bb_upper(4, 4)` -- a 4-period Bollinger band at 4 sigma. With the population
standard deviation this codebase uses (`backend/app/indicators/volatility.py`, ``ddof=0``), the
largest z-score any close can reach inside its own n-bar window is ``sqrt(n-1)``; at n=4 that is
``sqrt(3)`` = 1.7321, so a 4-sigma threshold can never be crossed. That expression fires 0 times over
the whole store, yet every pre-flight gate -- `windows.py` eligibility, pytest, ruff, a parameter-range
check -- passed it, because eligibility asks whether an indicator can *warm up*, never whether a rule
can ever be *true*. So `--write` here measures every distinct entry and exit expression against the
actual bar store (bounded to `DESIGN_THROUGH`) and REFUSES to write if any expression fires 0 times, or
if a confirmation arm retains >95% or <2% of its base entry's firing sessions -- a conjunct that changes
almost nothing (a no-op) or almost everything (a near-off-switch) has not been tested. The measurement
uses `app.market.store.read_frame`, which opens an in-memory DuckDB connection (no file lock, safe
alongside other readers), and `app.rules.grammar.parse` + `app.rules.evaluate.evaluate` -- the same DSL
semantics the backtest evaluates -- so a "fire" is a session on which the entry expression is True.

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

OUT = REPO / "data" / "rounds" / "r40-2026-09" / "cards"

#: The 12-name taxable growth pool, verbatim from `app.evolution.universe._TAXABLE_GROWTH`. Mechanically
#: defined by the pool, NOT chosen for this round -- large-cap tech/semiconductors, and therefore NOT
#: survivorship-free (the same honesty note round 34 carried about its ETF universe, by contrast
#: mechanically defined). See `ROUND-40-PLAN.md` section on the universe for the known limitation.
UNIVERSE: tuple[str, ...] = _TAXABLE_GROWTH

#: The base entry, written down exactly ONCE. The high-firing base (`bb_mid`, not `bb_upper`), chosen so
#: the confirmation arms have room to filter. Every treatment arm is this string + " and " + a conjunct.
BASE_ENTRY = "close crosses_above bb_mid(20, 2)"

#: The exit, fixed across every arm, so the only thing that varies within the field is the entry
#: conjunct (and the slot cap). A `bb_mid` crossback -- symmetric with the base.
EXIT = "close crosses_below bb_mid(20, 2)"

#: The kinds an arm can be. A `treatment` is subject to the reachability retention bound; a
#: `negative-control` is measured and printed but exempt from that bound, because the round *predicts*
#: it barely filters (it is the brief's "divergence proxy") and is carried precisely to show a near-no-op
#: is indistinguishable from `none`; the `control` is the base with no conjunct at all.
CONTROL, TREATMENT, NEGATIVE_CONTROL = "control", "treatment", "negative-control"

#: name -> (conjunct or None, kind). The conjunct is the ONLY text that differs between an arm's entry
#: and the base. `none` is the control (no conjunct). Order is the display order.
ARMS: dict[str, tuple[str | None, str]] = {
    "none": (None, CONTROL),
    "swing-structure": ("close > swing_high(10)", TREATMENT),
    "rsi-confirm": ("rsi(14) > rsi_at_swing_high(14, 10)", TREATMENT),
    "divergence-proxy-negative-control": ("rsi_at_swing_low(14, 10) < rsi(14)", NEGATIVE_CONTROL),
}

#: slot cap -> position_pct. Both commit ~0.75 of capital (3 x 0.25, 6 x 0.125), so exposure is
#: comparable across the two caps and the cap varies breadth-of-book, not gross exposure.
SLOT_CAPS: dict[int, Decimal] = {3: Decimal("0.25"), 6: Decimal("0.125")}

#: Fixed brackets, held identical across every cell. Stop 0.12, no take-profit. `max_hold_days` 150 is
#: a backstop well under the `trading` mandate's nine-month / ~189-session ceiling
#: (`app.tournament.purposes`, `horizon_months_max = 9`): the `bb_mid` crossback exit reaches almost
#: every hold first, so 150 caps the tail rather than defining the trade horizon.
STOP_LOSS_PCT = Decimal("0.12")
TAKE_PROFIT_PCT: Decimal | None = None
MAX_HOLD_DAYS = 150

#: The reachability retention bound for a treatment arm. Outside [2%, 95%] the conjunct is a
#: near-off-switch or a no-op and has not been tested -- `--write` refuses.
RETENTION_MIN = 0.02
RETENTION_MAX = 0.95

#: The programme's measured noise floor, `PROTOCOL.md` section 7. A conjunct "pays for itself" only if
#: its arm-minus-control median adjusted excess exceeds this AND survives BH q<0.10; stated here so the
#: plan and the tool cannot drift on the number.
NOISE_FLOOR_PP = 21.2

#: Matches every numeric literal in a rule expression, for the PROTOCOL section 3 parameter budget.
#: Same pattern round35/round36 use.
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def entry_for(conjunct: str | None) -> str:
    """The entry string for an arm, by construction from the single `BASE_ENTRY`.

    `None` -> the bare base (the control). Otherwise `BASE_ENTRY + " and " + conjunct`. This is the ONE
    place an arm's entry is formed; the test asserts every card's entry equals exactly this.
    """
    if conjunct is None:
        return BASE_ENTRY
    return f"{BASE_ENTRY} and {conjunct}"


def free_numbers(card: StrategyCard) -> int:
    """PROTOCOL section 3's parameter count for one card: ten free numbers, "counted across `entry`,
    `exit`, the two brackets, the hold cap, slot count and position size".

    Distinct numeric *values* across the expressions (a value reused in entry and exit is one choice,
    not two), plus one per present bracket field, plus two for `max_positions` and `position_pct`. This
    is the identical convention `strategy-program/tools/round35.py::free_numbers` uses.
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
    only until the next commit.
    """
    return frozenset(
        sym
        for card in _library_cards(settings)
        if getattr(card, "purpose", None) is Purpose.ROTH
        for sym in card.universe
    )


def _thesis(arm: str, kind: str, slot_cap: int) -> str:
    base = (
        "Round 40 cell on the taxable trading book. The base entry "
        f"'{BASE_ENTRY}' and the exit '{EXIT}' are held IDENTICAL across every cell in this round; the "
        "only thing that varies within a slot cap is the confirmation conjunct added to the entry. "
    )
    if kind == CONTROL:
        arm_txt = (
            "This is the CONTROL: the bare base entry, no confirmation term. Every other arm is "
            "reported as arm-minus-this-control on median exposure-adjusted excess, never against SPY."
        )
    elif kind == NEGATIVE_CONTROL:
        arm_txt = (
            "This is a NEGATIVE CONTROL, not a treatment: the conjunct is a divergence proxy that the "
            "reachability study shows barely filters (it retains ~93% of the base's firing sessions). "
            "The round PRE-REGISTERS that it will be indistinguishable from the 'none' control (arm minus "
            "control inside 21.2pp), which is what a near-no-op should look like."
        )
    else:
        arm_txt = (
            "This is a TREATMENT: the base entry with one confirmation conjunct added. A conjunct can "
            "only REDUCE firings, so this arm takes fewer trades and carries lower exposure than the "
            "control -- which is exactly why the metric is exposure-adjusted excess and not raw return."
        )
    tail = (
        f" Slot cap {slot_cap} (position size chosen so gross commitment is ~0.75 either way, so the "
        "cap varies breadth of book, not exposure). The hypothesis under test is the influencer persona "
        "creator-e's claim that a signal is only valid with a confirmation term; that persona's "
        "corpus is partly Korean-language and machine-summarised, so this is a fair test of the claim, "
        "not an endorsement. Pre-registered 2026-09-09 before any measurement. Not investment advice. "
        "See strategy-program/ROUND-40-PLAN.md."
    )
    return base + arm_txt + tail


def _falsification(kind: str) -> str:
    common = (
        f"Honest prior: the null (rounds 17/18/34 put form, exit and rotation all inside the {NOISE_FLOOR_PP}pp "
        "floor). Pre-registered predictions with named failure regimes: "
        "(1) No treatment arm beats the control by more than 21.2pp on median adjusted excess AND survives "
        "BH q<0.10 with the denominator = every cell run; if one does, a confirmation conjunct pays for itself. "
        "(2) The divergence-proxy negative control is INDISTINGUISHABLE from the 'none' control (|arm-control| < 21.2pp), "
        "because it retains ~93% of the base's firings. If it separates, the metric or the store moved. "
        "(3) Both treatments take materially fewer trades and lower exposure than the control (they retain "
        "~11-14% of firings); if a treatment's trade count is NOT below the control's, the conjunct did not bind. "
        "(4) Sign flips by regime: in a strong trend (recent, bull-2024) the confirmation delays entry and gives "
        "back early upside, while in chop it avoids false starts -- so any single-window arm-minus-control read is "
        "unsafe and only the median across the eight main windows is interpreted. "
        "(5) Degenerate-outcome guard: a heavily filtered treatment at slot cap 6 may take so few trades that it "
        "fails the 5-of-8 regime gate in some windows and is UNRANKED -- that is 'switched off', NOT 'the conjunct "
        "did not help', and the two must not be conflated."
    )
    if kind == CONTROL:
        return "Baseline against which every treatment is measured. " + common
    if kind == NEGATIVE_CONTROL:
        return "Predicted to be a no-op relative to the control. " + common
    return common


def build() -> list[StrategyCard]:
    """The 8-cell field: 1 base entry x 4 confirmation arms x 2 slot caps. Deterministic."""
    cards: list[StrategyCard] = []
    for arm, (conjunct, kind) in ARMS.items():
        entry = entry_for(conjunct)
        for slot_cap, position_pct in SLOT_CAPS.items():
            agent_id = f"r40-{arm}-slots{slot_cap}"
            cards.append(
                StrategyCard(
                    agent_id=agent_id,
                    display_name=f"conjunct {arm} / {slot_cap} slots",
                    discipline=Discipline.MOMENTUM,
                    purpose=Purpose.TRADING,
                    thesis=_thesis(arm, kind, slot_cap),
                    falsification=_falsification(kind),
                    universe=UNIVERSE,
                    entry=entry,
                    exit=EXIT,
                    stop_loss_pct=STOP_LOSS_PCT,
                    take_profit_pct=TAKE_PROFIT_PCT,
                    max_hold_days=MAX_HOLD_DAYS,
                    max_positions=slot_cap,
                    position_pct=position_pct,
                    rank_by=None,
                    designed_through=DESIGN_THROUGH,
                )
            )
    return cards


def _fires_per_symbol(tree, settings) -> int:
    """Number of sessions on which `tree` is True across the whole universe, bounded to DESIGN_THROUGH.

    An in-memory read (`read_frame`, no file lock) and the real evaluator, so a "fire" is exactly a
    session the DSL would have signalled an entry on. NA (warmup) is treated as False.
    """
    total = 0
    for symbol in UNIVERSE:
        frame = read_frame(symbol, Interval.DAY, end=DESIGN_THROUGH, settings=settings)
        if frame.empty:
            continue
        series = evaluate.evaluate(tree, frame, interval=Interval.DAY)
        total += int(series.fillna(False).astype(bool).sum())
    return total


def reachability(settings) -> tuple[dict[str, dict[str, object]], list[str]]:
    """Measure every distinct entry and the exit against the bar store; return (table, refusals).

    `table[arm]` carries `fires`, `retention` (vs the base entry, `None` for the control), `kind` and the
    entry text. `refusals` is empty when the field is clean. Refuses on: any expression firing 0 times;
    a TREATMENT arm retaining outside [2%, 95%]. The exit is measured too (a 0-firing exit would trap
    every position until the stop or the hold cap).
    """
    base_tree = grammar.parse(BASE_ENTRY)
    base_fires = _fires_per_symbol(base_tree, settings)

    table: dict[str, dict[str, object]] = {}
    refusals: list[str] = []

    for arm, (conjunct, kind) in ARMS.items():
        entry = entry_for(conjunct)
        fires = _fires_per_symbol(grammar.parse(entry), settings)
        retention = None if conjunct is None else (fires / base_fires if base_fires else float("inf"))
        table[arm] = {"kind": kind, "entry": entry, "fires": fires, "retention": retention}
        if fires == 0:
            refusals.append(f"{arm}: entry '{entry}' fires 0 times -- structurally unreachable")
        if kind == TREATMENT and retention is not None:
            if retention > RETENTION_MAX:
                refusals.append(
                    f"{arm}: retention {retention:.2%} > {RETENTION_MAX:.0%} -- conjunct is a no-op"
                )
            elif retention < RETENTION_MIN:
                refusals.append(
                    f"{arm}: retention {retention:.2%} < {RETENTION_MIN:.0%} -- conjunct is a near-off-switch"
                )

    exit_fires = _fires_per_symbol(grammar.parse(EXIT), settings)
    table["_exit"] = {"kind": "exit", "entry": EXIT, "fires": exit_fires, "retention": None}
    if exit_fires == 0:
        refusals.append(f"exit '{EXIT}' fires 0 times -- positions would never close on the rule")

    return table, refusals


def _print_reachability(table: dict[str, dict[str, object]], base_fires: int, sessions: int) -> None:
    print(f"reachability over {len(UNIVERSE)} names, {sessions} symbol-sessions, bounded to "
          f"{DESIGN_THROUGH.isoformat()}")
    print(f"  base entry: {BASE_ENTRY!r} -> {base_fires} fires "
          f"({1000 * base_fires / sessions:.1f} per 1000 sessions)")
    print(f"  {'arm':36s}  {'kind':16s}  {'fires':>7s}  {'retention':>9s}")
    print("  " + "-" * 74)
    for arm, row in table.items():
        ret = row["retention"]
        ret_txt = "--" if ret is None else f"{ret:.2%}"
        label = "exit" if arm == "_exit" else arm
        print(f"  {label:36s}  {row['kind']!s:16s}  {int(row['fires']):>7d}  {ret_txt:>9s}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the cards to the round directory")
    args = parser.parse_args(argv)

    settings = get_settings()
    cards = build()

    print(f"built {len(cards)} cards: {len(ARMS)} arms x {len(SLOT_CAPS)} slot caps")
    for card in cards:
        print(f"  {card.agent_id:34s}  free_numbers={free_numbers(card)}")

    # Reachability probe -- printed on BOTH the dry run and the write.
    sessions = 0
    for symbol in UNIVERSE:
        sessions += len(read_frame(symbol, Interval.DAY, end=DESIGN_THROUGH, settings=settings))
    base_fires = _fires_per_symbol(grammar.parse(BASE_ENTRY), settings)
    table, refusals = reachability(settings)
    print()
    _print_reachability(table, base_fires, sessions)

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
