"""Round 47: buy weakness x sell strength on three of round 44's held baskets -- does an "accumulate on
pullbacks, then hold" entry, a "trim on extension" exit, or the two combined, beat holding the basket
passively?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round47.py           # dry run
    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round47.py --write   # author

`ROUND-47-PLAN.md` is the pre-registration this module executes. Read it first; this file authors the
field and nothing else. The cards are then gated by `strategy-program/tools/disjoint_field.py`, run by
`run_round.sh` and scored by `score.py`, exactly like every other card round.

**This is one third of `MIX-AND-MATCH-PLAN.md` section 3's rounds 45-47.** Round 44 (`round44.py`)
established, for five baskets including three of this round's four -- `control`, `power`, `defense` --
that a passive control expression (`close > 0` / `close < 0`) and a profit-trim expression
(`close < sma(200) * 1.15` / `close > sma(200) * 1.15`) are both reachable and both null against a
passive-baseline decision rule. This round reuses those two arms **character for character** (drift
against the on-disk r44 cards is asserted, not re-typed) and adds two new arms built from the *entry*
side of Creator C's and Creator A's stated method -- "accumulate on pullbacks inside an uptrend,
then hold" -- crossed with the same trim exit: `dip` (new entry, r44's null exit) and `dip-trim` (new
entry, r44's exit). Twelve cells, one basket axis reused wholesale and one arm axis extended by two.

**Not investment advice. No influencer is endorsed.** Every basket here is round 44's own construction
(see `ROUND-44-PLAN.md` section 2 for the sourcing and disclosed substitutions); this file does not
re-derive or re-justify the baskets, only reuses them, and asserts the reuse is exact.
"""

from __future__ import annotations

import argparse
import pathlib
import re
from decimal import Decimal

from app.config import get_settings
from app.db.duck import Interval
from app.evolution.promotion import _library_cards
from app.evolution.ruleforms import classify
from app.market.store import read_frame
from app.rules import evaluate, grammar
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from app.tournament.purposes import Purpose, find_disjointness_violations

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r47-2026-09" / "cards"

#: Where round 44 wrote the two arms this round reuses verbatim -- the drift check reads these.
_R44_CARDS = REPO / "data" / "rounds" / "r44-2026-09" / "cards"

# ---------------------------------------------------------------------------
# The universe: three of round 44's five baskets, verbatim -- no re-derivation, no re-justification.
# See `ROUND-44-PLAN.md` section 2 for what each basket is and why. This file only asserts the reuse
# is exact (`check_r44_drift`), never re-types a ticker.
# ---------------------------------------------------------------------------

#: Creator A / Creator D's electricity-infrastructure-as-AI-bottleneck thesis (`round44.POWER`).
POWER: tuple[str, ...] = ("NEE", "DUK", "SO", "CCJ")

#: Creator A's defense-spending pillar (`round44.DEFENSE`).
DEFENSE: tuple[str, ...] = ("LMT", "NOC", "GD", "RTX")

#: The broad, style-neutral passive control (`round44.CONTROL`).
CONTROL: tuple[str, ...] = ("VTV", "SPYG", "RSP", "MDY")

#: name -> tickers, in the pinned display order. `power` and `defense` first (the two themed baskets
#: this round's arms are being tested on), `control` last (the reference basket for the field's BH
#: correction) -- the same relative order these three carried inside round 44's own five-basket dict.
BASKETS: dict[str, tuple[str, ...]] = {
    "power": POWER,
    "defense": DEFENSE,
    "control": CONTROL,
}

#: Every traded ticker, basket order preserved, for the reachability probe and the disjointness check.
#: Twelve names -- the twenty of round 44 minus `semicap` (AMAT KLAC LRCX ASML) and `realassets`
#: (XOP XME EWY VWO), which this round does not touch.
TRADED: tuple[str, ...] = tuple(sym for names in BASKETS.values() for sym in names)

# ---------------------------------------------------------------------------
# The four arms
# ---------------------------------------------------------------------------

#: Round 44's control expressions, reused verbatim (drift-checked against the on-disk r44 cards in
#: `check_r44_drift`, not re-typed on trust).
PASSIVE_ENTRY = "close > 0"
PASSIVE_EXIT = "close < 0"

#: Round 44's profit-trim expressions, reused verbatim (drift-checked). `1.15` -- 15% above the
#: 200-day mean -- was round 44's own reachability-tested threshold; this round does not re-tune it.
TRIM_THRESHOLD = Decimal("1.15")
_REGIME_MA = 200
TRIM_ENTRY = f"close < sma({_REGIME_MA}) * {TRIM_THRESHOLD}"
TRIM_EXIT = f"close > sma({_REGIME_MA}) * {TRIM_THRESHOLD}"

#: The new entry: Creator C's and Creator A's "accumulate on a pullback inside an uptrend"
#: (`MIX-AND-MATCH-PLAN.md` section 3, round 47's own row; `PERSONA-HYPOTHESES.md`'s "accumulate on
#: dips inside an uptrend" row, "never as a held-basket entry"). Below the 50-day mean (a pullback),
#: above the 200-day mean (still in the uptrend that makes it a dip rather than a trend break).
_DIP_MA_FAST = 50
DIP_ENTRY = f"close < sma({_DIP_MA_FAST}) and close > sma({_REGIME_MA})"

#: `dip`'s exit is round 44's `PASSIVE_EXIT` -- structurally never true (`close < 0` never fires on a
#: real bar) -- which is the mechanism, not a placeholder: "accumulate ... then hold" means once a
#: pullback is bought, the position is never sold by this rule. A slot that fills stays filled.
DIP_EXIT = PASSIVE_EXIT

#: `dip-trim`: the same pullback entry, but exit on the trim condition instead of never -- "buy
#: weakness, sell strength", Creator B's and Creator C's disciplines combined in one card.
DIP_TRIM_ENTRY = DIP_ENTRY
DIP_TRIM_EXIT = TRIM_EXIT

#: `ruleforms.classify` reads the entry first and only falls back to the exit when the entry names
#: nothing (see that function's own docstring). `passive`'s and `trim`'s classifications are r44's
#: findings, reused: `classify(PASSIVE_ENTRY, PASSIVE_EXIT) is None` (forced to `TREND`, the same
#: least-wrong label round 39's and round 44's passive controls carry) and
#: `classify(TRIM_ENTRY, TRIM_EXIT) is None` (a genuine, not-forced fit to `RISK_MANAGED`: a
#: profit-taking / exposure-reduction discipline on a held position, not a directional entry signal --
#: `Discipline.RISK_MANAGED`'s own docstring). **New for this round:** `DIP_ENTRY` -- a moving-average
#: filter conjunction -- classifies as `TREND` for real, through `classify()`, not by force; and
#: because `dip-trim` shares that same entry and `classify()` never reaches the exit when the entry
#: already names something, `dip-trim` classifies as `TREND` too, for the identical reason. Both are
#: asserted, not asserted-around, at import time below.
PASSIVE_DISCIPLINE = Discipline.TREND
TRIM_DISCIPLINE = Discipline.RISK_MANAGED
DIP_DISCIPLINE = Discipline.TREND
DIP_TRIM_DISCIPLINE = Discipline.TREND

assert classify(PASSIVE_ENTRY, PASSIVE_EXIT) is None, "passive drifted from r44's None classification"
assert classify(TRIM_ENTRY, TRIM_EXIT) is None, "trim drifted from r44's None classification"
assert classify(DIP_ENTRY, DIP_EXIT) == Discipline.TREND, "dip no longer classifies as trend"
assert classify(DIP_TRIM_ENTRY, DIP_TRIM_EXIT) == Discipline.TREND, "dip-trim no longer classifies as trend"

#: One row per arm: display fragment, entry, exit, discipline. Iteration order fixes the on-disk card
#: order and is not a claim about anything.
ARMS: dict[str, dict[str, object]] = {
    "passive": {"entry": PASSIVE_ENTRY, "exit": PASSIVE_EXIT, "discipline": PASSIVE_DISCIPLINE},
    "dip": {"entry": DIP_ENTRY, "exit": DIP_EXIT, "discipline": DIP_DISCIPLINE},
    "trim": {"entry": TRIM_ENTRY, "exit": TRIM_EXIT, "discipline": TRIM_DISCIPLINE},
    "dip-trim": {"entry": DIP_TRIM_ENTRY, "exit": DIP_TRIM_EXIT, "discipline": DIP_TRIM_DISCIPLINE},
}
ARM_ORDER: tuple[str, ...] = ("passive", "dip", "trim", "dip-trim")
assert set(ARMS) == set(ARM_ORDER)

#: Every card holds a slot for every name in its basket: no slot contention, no `rank_by`, 100% of
#: capital deployed when fully invested -- identical to every arm in round 44.
MAX_POSITIONS = 4
POSITION_PCT = Decimal("0.25")

#: Matches every numeric literal in a rule expression, for the `PROTOCOL.md` section 3 budget. Same
#: pattern round35/round39/round40/round44 use.
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def free_numbers(card: StrategyCard) -> int:
    """`PROTOCOL.md` section 3's parameter count: distinct numeric *values* across `entry`, `exit`,
    `rank_by`, plus one per present bracket, plus two for `max_positions`/`position_pct`. Identical
    derivation to `round44.py` (and round35/round39/round40 before it), so budgets are directly
    comparable across rounds.
    """
    text = " ".join(part for part in (card.entry, card.exit, card.rank_by or "") if part)
    values = {match.group(0) for match in _NUMBER.finditer(text)}
    brackets = sum(
        1
        for field in (card.stop_loss_pct, card.take_profit_pct, card.max_hold_days)
        if field is not None
    )
    return len(values) + brackets + 2  # + max_positions + position_pct


def claimed_symbols() -> tuple[frozenset[str], list[object]]:
    """`(tickers claimed by the taxable book, the non-roth cards that claim them)`, from the **live**
    library on disk -- identical derivation to `round44.py::claimed_symbols`, through
    `app.evolution.promotion._library_cards` (all six tiers, including `allocation/` and `ladder/`,
    which `app.tournament.results.load_library` does not walk).

    Recomputed rather than hardcoded: this repository is edited by concurrent sessions (two other
    agents are authoring rounds 45/46 alongside this one) and a ticker list pasted into a constant is
    correct exactly until the next commit.
    """
    others = [
        card
        for card in _library_cards(get_settings())
        if card.purpose in (Purpose.SAVINGS, Purpose.TRADING)
    ]
    symbols = frozenset(symbol for card in others for symbol in card.universe)
    return symbols, others


# ---------------------------------------------------------------------------
# Drift check -- the passive and trim arms must match round 44's on-disk cards for `power`, `defense`
# and `control` exactly. Refuses to write on any difference rather than silently re-deriving a rule
# this round did not re-decide.
# ---------------------------------------------------------------------------

_DRIFT_FIELDS = ("entry", "exit", "max_positions", "position_pct", "universe")


def check_r44_drift() -> list[str]:
    """Compare this round's `passive` and `trim` cards for `power`, `defense`, `control` against the
    r44 cards on disk (`data/rounds/r44-2026-09/cards/r44-<basket>-<arm>.json`). Returns a list of
    problems; empty means no drift. Missing r44 files are themselves reported as problems -- this
    round cannot claim "verbatim from round 44" without something on disk to check it against.
    """
    problems: list[str] = []
    for basket in BASKETS:
        for arm in ("passive", "trim"):
            r44_path = _R44_CARDS / f"r44-{basket}-{arm}.json"
            if not r44_path.is_file():
                problems.append(f"{r44_path} does not exist -- cannot verify {arm}/{basket} reuse")
                continue
            r44_card = StrategyCard.model_validate_json(r44_path.read_text(encoding="utf-8"))
            ours = _build_one(basket, arm)
            for field in _DRIFT_FIELDS:
                a, b = getattr(r44_card, field), getattr(ours, field)
                if a != b:
                    problems.append(
                        f"r47-{basket}-{arm} drifted from r44-{basket}-{arm} on {field}: "
                        f"r44={a!r} vs r47={b!r}"
                    )
    return problems


# ---------------------------------------------------------------------------
# Reachability / support probe -- read_frame + grammar.parse + evaluate.evaluate, bounded to
# DESIGN_THROUGH. Same method `round40.py`'s and `round44.py`'s reachability gates use, extended to
# two conditions: the new dip entry, and the reused trim exit.
# ---------------------------------------------------------------------------


def support_table(settings) -> dict[str, dict[str, object]]:
    """Per-symbol: first bar, session count, and fires/support for both `DIP_ENTRY`
    (`close < sma(50) and close > sma(200)`) and `TRIM_EXIT` (`close > sma(200) * 1.15`), over
    `[first bar, DESIGN_THROUGH]`.

    An in-memory read (`read_frame`, no file lock -- safe alongside other readers) and the real
    evaluator. `ROUND-47-PLAN.md` section 3a is this table, computed once here and reproduced there.
    """
    dip_tree = grammar.parse(DIP_ENTRY)
    trim_tree = grammar.parse(TRIM_EXIT)
    table: dict[str, dict[str, object]] = {}
    for symbol in TRADED:
        frame = read_frame(symbol, Interval.DAY, end=DESIGN_THROUGH, settings=settings)
        if frame.empty:
            table[symbol] = {
                "first_bar": None, "sessions": 0,
                "dip_fires": 0, "dip_support": None,
                "trim_fires": 0, "trim_support": None,
            }
            continue
        first_bar = frame["ts"].iloc[0].date()
        sessions = len(frame)
        dip_series = evaluate.evaluate(dip_tree, frame, interval=Interval.DAY)
        trim_series = evaluate.evaluate(trim_tree, frame, interval=Interval.DAY)
        dip_fires = int(dip_series.fillna(False).astype(bool).sum())
        trim_fires = int(trim_series.fillna(False).astype(bool).sum())
        table[symbol] = {
            "first_bar": first_bar,
            "sessions": sessions,
            "dip_fires": dip_fires,
            "dip_support": (dip_fires / sessions) if sessions else None,
            "trim_fires": trim_fires,
            "trim_support": (trim_fires / sessions) if sessions else None,
        }
    return table


def _thesis(basket: str, arm: str, names: tuple[str, ...]) -> str:
    what = {
        "power": (
            "Creator A's and Creator D's electricity-infrastructure-as-AI-bottleneck thesis: two "
            "regulated utilities (NEE, DUK), one merchant/renewable utility (SO), one uranium miner "
            "(CCJ) -- round 44's basket, reused verbatim (ROUND-44-PLAN.md section 2)."
        ),
        "defense": (
            "Creator A's defense-spending pillar: the four largest US pure-play defense primes "
            "(LMT, NOC, GD, RTX) -- round 44's basket, reused verbatim."
        ),
        "control": (
            "The broad, style-neutral passive control: round 39's and round 44's value+growth pool "
            "(VTV, SPYG, RSP, MDY), reused verbatim as this round's reference basket for the BH "
            "correction."
        ),
    }[basket]
    arm_desc = {
        "passive": (
            "Arm: passive (round 44's control expressions, verbatim: entry 'close > 0', exit "
            "'close < 0' -- always in, never out)."
        ),
        "dip": (
            "Arm: dip -- Creator C's and Creator A's 'accumulate on a pullback inside an uptrend' "
            "entry (close < sma(50) and close > sma(200)) paired with round 44's never-true exit "
            "(close < 0): a filled slot is never sold by this rule. 'Then hold', not a round-trip."
        ),
        "trim": (
            "Arm: trim -- round 44's profit-trim, verbatim: entry/exit both close vs sma(200)*1.15, "
            "stepping a name to cash when it is 15% above its own 200-day mean and back in when it "
            "is not."
        ),
        "dip-trim": (
            "Arm: dip-trim -- the dip entry (close < sma(50) and close > sma(200)) paired with the "
            "trim exit (close > sma(200) * 1.15): buy weakness, sell strength, Creator B's "
            "and Creator C's/Creator A's disciplines combined in one card."
        ),
    }[arm]
    common = (
        f"Round 47 {arm} cell. Basket ({basket}): {what} Universe: {' '.join(names)}. {arm_desc} "
        "Purpose ROTH: no ticker this round trades is claimed by any savings- or trading-purpose "
        "card in the live library (app.evolution.promotion._library_cards, all six tiers), because "
        "Rev. Rul. 2008-5 destroys rather than defers a wash-sale loss whose replacement is bought "
        "inside an IRA. Ticker disjointness from the taxable book is NECESSARY, not sufficient, "
        "under IRC section 1091; nothing here is a section 1091-safety claim. The Roth benchmark is "
        "SPY, price-only, no dividends -- power and defense are not US large-cap-growth books, so a "
        "raw adjusted_excess-vs-SPY reading is not this round's decision quantity; the decision "
        "quantity is arm-minus-passive within basket. Every note in the persona corpus that produced "
        "the underlying hypotheses has published=null (PERSONA-HYPOTHESES.md), so bull-2024 and "
        "recent are IN-SAMPLE to the hypothesis and any positive result confined to them is "
        "hindsight, not a finding -- the fair test is the six windows ending by 2022-10 (gfc, "
        "chop-2011, chop-2015, q4-2018, covid, bear-2022), reported separately. Pre-registered "
        "2026-09-09, before any card ran. Not investment advice; no influencer is endorsed. See "
        "strategy-program/ROUND-47-PLAN.md."
    )
    return common


def _falsification(basket: str, arm: str) -> str:
    floor = (
        "Pre-registered decision rule (PROTOCOL.md section 7 floor, 21.2pp): an edge requires "
        f"median(r47-{basket}-{arm}) minus median(r47-{basket}-passive) > 21.2pp AND BH q<0.10 over "
        "all 12 cells this round runs (denominator against `r47-control-passive`). A margin inside "
        "the floor is a null whichever side it lands on, and the pre-registered prediction is null on "
        "every arm. Nothing is promoted from this round regardless of outcome -- it is a "
        "pre-registered measurement study."
    )
    if arm == "passive":
        return floor + " This is the basket's reference cell -- every other arm in this basket is measured against it."
    if arm == "dip":
        return floor + (
            " Predicted to sit out the start of every window until the first qualifying pullback, so "
            "its session exposure is below the passive arm's and its adjusted-excess gap from passive "
            "is mostly attributable to that entry delay, not to the pullback condition itself -- "
            "reported per window in ROUND-47-PLAN.md's days-to-first-entry table."
        )
    if arm == "trim":
        return floor + (
            " Predicted to underperform its own passive control in bull-2024 (round 44's own finding "
            "for this basket); recent is pre-registered separately and not predicted in either "
            "direction, because round 44 found trim beat passive in recent for this basket."
        )
    return floor + (
        " Predicted not to beat the better of its own two component arms (dip, trim) on median "
        "adjusted excess -- combining a filter and an exit is not expected to out-earn the better of "
        "the two alone."
    )


def _build_one(basket: str, arm: str) -> StrategyCard:
    names = BASKETS[basket]
    spec = ARMS[arm]
    return StrategyCard(
        agent_id=f"r47-{basket}-{arm}",
        display_name=f"R47 basket / {basket} / {arm}",
        discipline=spec["discipline"],  # type: ignore[arg-type]
        purpose=Purpose.ROTH,
        thesis=_thesis(basket, arm, names),
        falsification=_falsification(basket, arm),
        universe=names,
        entry=spec["entry"],  # type: ignore[arg-type]
        exit=spec["exit"],  # type: ignore[arg-type]
        stop_loss_pct=None,
        take_profit_pct=None,
        max_hold_days=None,
        max_positions=MAX_POSITIONS,
        position_pct=POSITION_PCT,
        rank_by=None,
        designed_through=DESIGN_THROUGH,
    )


def build() -> list[StrategyCard]:
    """Round 47's field, in a fixed order: for each of the three baskets, four arms
    (passive, dip, trim, dip-trim) -- twelve cards.

    Deterministic: no clock, no filesystem read, no randomness, so calling this twice returns two
    field-identical lists (`tests/test_round47_field.py::TestDeterminism`).
    """
    cards: list[StrategyCard] = []
    for basket in BASKETS:
        for arm in ARM_ORDER:
            cards.append(_build_one(basket, arm))
    return cards


def _print_support(table: dict[str, dict[str, object]]) -> None:
    print(
        f"support (fraction of sessions), bounded to {DESIGN_THROUGH.isoformat()}:"
    )
    print(
        f"  {'symbol':<8}{'first_bar':<14}{'sessions':>10}"
        f"{'dip_fires':>11}{'dip_supp':>10}{'trim_fires':>12}{'trim_supp':>11}"
    )
    for basket, names in BASKETS.items():
        print(f"  -- {basket} --")
        for symbol in names:
            row = table[symbol]
            dip_supp = row["dip_support"]
            trim_supp = row["trim_support"]
            dip_txt = "n/a" if dip_supp is None else f"{dip_supp:.1%}"
            trim_txt = "n/a" if trim_supp is None else f"{trim_supp:.1%}"
            print(
                f"  {symbol:<8}{row['first_bar']!s:<14}{row['sessions']:>10}"
                f"{row['dip_fires']:>11}{dip_txt:>10}{row['trim_fires']:>12}{trim_txt:>11}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the cards to the round directory")
    args = parser.parse_args(argv)

    settings = get_settings()
    cards = build()
    print(f"built {len(cards)} cards on {len(TRADED)} traded names across {len(BASKETS)} baskets: "
          + " ".join(TRADED))
    print()
    print(
        f"{'agent_id':<20}  {'discipline':<14}  {'slots':>5}  {'pct':>6}  {'free#':>5}  universe"
    )
    print("-" * 100)
    for card in cards:
        print(
            f"{card.agent_id:<20}  {card.discipline!s:<14}  {card.max_positions:>5}  "
            f"{card.position_pct:>6}  {free_numbers(card):>5}  {' '.join(card.universe)}"
        )

    over_budget = [c.agent_id for c in cards if free_numbers(c) > 10]
    print()
    print(
        f"parameter budget: max {max(free_numbers(c) for c in cards)} free numbers per card "
        "(PROTOCOL section 3 allows 10)"
        + (f" -- OVER BUDGET: {over_budget}" if over_budget else "")
    )

    # Every expression the runner will guard, parsed here so a syntax error is a build failure rather
    # than a mid-round card failure the runner walks past (PROTOCOL.md section 8).
    for card in cards:
        grammar.parse(card.entry)
        grammar.parse(card.exit)
    print("grammar: every entry and exit parses")

    # Drift check: passive/trim must match round 44's on-disk cards for power/defense/control exactly.
    print()
    drift = check_r44_drift()
    if drift:
        print("R44 DRIFT CHECK FAILED:")
        for d in drift:
            print(f"  {d}")
    else:
        print(
            "R44 drift check: passive and trim entry/exit/slots/size/universe match "
            "data/rounds/r44-2026-09/cards/ for power, defense, control -- exact reuse confirmed."
        )

    # Reachability / support probe -- printed on both the dry run and the write, and the reason the
    # tool can refuse before anything is written.
    print()
    table = support_table(settings)
    _print_support(table)
    zero_dip = [s for s, row in table.items() if row["dip_fires"] == 0]
    zero_trim = [s for s, row in table.items() if row["trim_fires"] == 0]
    min_dip_sym = min(
        (s for s in table if table[s]["dip_support"] is not None), key=lambda s: table[s]["dip_support"]
    )
    min_trim_sym = min(
        (s for s in table if table[s]["trim_support"] is not None), key=lambda s: table[s]["trim_support"]
    )
    print()
    print(
        f"minimum dip-entry support: {min_dip_sym} at {table[min_dip_sym]['dip_support']:.1%} "
        f"({table[min_dip_sym]['dip_fires']} fires)"
    )
    print(
        f"minimum trim-exit support: {min_trim_sym} at {table[min_trim_sym]['trim_support']:.1%} "
        f"({table[min_trim_sym]['trim_fires']} fires)"
    )

    refusals: list[str] = list(drift)
    if zero_dip:
        refusals.append(
            f"dip entry fires 0 times for: {', '.join(zero_dip)} -- structurally unreachable"
        )
    if zero_trim:
        refusals.append(
            f"trim exit fires 0 times for: {', '.join(zero_trim)} -- structurally unreachable"
        )
    if over_budget:
        refusals.append(f"parameter budget: over 10 free numbers: {over_budget}")

    taxable, other_cards = claimed_symbols()
    print(
        f"library: {len(taxable)} tickers claimed by {len(other_cards)} savings/trading cards "
        "(recomputed live through app.evolution.promotion._library_cards -- all six tiers)"
    )
    overlap = sorted(set(TRADED) & taxable)
    violations = find_disjointness_violations([*cards, *other_cards])
    ours = {card.agent_id for card in cards}
    violations = [v for v in violations if v.roth_agent_id in ours]
    if overlap:
        refusals.append(f"taxable overlap: {overlap}")
    for violation in violations:
        refusals.append(
            f"find_disjointness_violations: {violation.symbol}: {violation.roth_agent_id} (roth) vs "
            f"{violation.other_agent_id} ({violation.other_purpose})"
        )

    if refusals:
        print()
        print("REFUSING TO AUTHOR THIS FIELD.")
        for r in refusals:
            print(f"  {r}")
        return 1
    print(
        "disjointness: no ticker traded by this round is claimed by any savings- or trading-purpose "
        "card, and find_disjointness_violations reports nothing naming one of this round's cards"
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
