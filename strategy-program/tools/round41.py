"""Round 41: is an RSI-divergence confirmation gate worth anything on top of a mean-reversion entry?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round41.py --write

`strategy-program/ROUND-41-PLAN.md` is the pre-registration this executes. Read it first. **The round
has not been run**; this tool only authors its field, which `strategy-program/tools/run_round.sh`
then runs and `score.py` scores, exactly like every other card round.

**Numbering note, recorded here because it is the kind of thing that becomes a mystery.** This round
was briefed as round 38 and authored as round 38. A concurrent session was briefed with the same
number and authored a macro real-yield allocation round under `strategy-program/tools/round38.py` and
`data/rounds/r38-2026-09/cards/`, freezing seven `AllocationCard`s there. That work is untouched. This
round moved to the next free number instead (37, 39 and 40 were already claimed by other concurrent
work), so nothing here collides with it -- including the `agent_id` prefix, which would otherwise have
produced two different `r38-control` cards in the same scorecard namespace. The number is the only
thing that changed; every design decision below was fixed before the collision was discovered.

**The question, and where it comes from.** Two of the programme's ingested personas make the same
structural claim, independently. `creator-e` ("Creator E", note `3pLtQ_82nSM`) teaches RSI
divergence as *confirmation* of a support/resistance structure and never as a standalone trigger --
its own theme line calls the failure "relying on single signals without confirmation", and its quote
is "Divergence. Showing up does not mean a trend reversal is guaranteed." `creator-c` (note
`U-I4NfBUJzo`) stacks moving-average alignment, structure and pattern before entering, and says in as
many words that the MA has to be read together with the rest. This programme has tested single-form
entries to exhaustion -- rounds 17, 18 and 34 ran eight forms, eight exits and a regime filter, and
every marginal landed inside the 21.2pp noise floor -- but it has **never** tested an
indicator-*combination* gate: the claim that requiring two independent conditions to agree changes a
result. That is the one testable half of the personas' claim, and this round is it.

**One factor varies: the confirmation gate.** The base entry, exit, brackets, sizing, universe and
cutoff are `backend/app/paper/library/candidates/c18-meanrev.json`'s, character for character --
asserted against the live library JSON at build time by `check_base_matches_c18`, which refuses
`--write` on any drift. Each arm ANDs one gate clause onto that entry and changes nothing else.

**The divergence primitive, and the identifier that selects it.** `app.indicators.swing` publishes a
confirmed swing pivot `lookback` bars *after* it forms -- the lag is the whole causality argument, and
`app.backtest.guards` verifies it. `swing_low(n)` is `IndicatorRef(name="swing", output="low")` and
`rsi_at_swing_low(p, n)` is `IndicatorRef(name="rsi_at_swing", output="low")`, both resolved by
`app.rules.grammar._resolve_indicator_ident` peeling the `_low` suffix off the last underscore. So a
bullish divergence -- price prints a lower low than the last confirmed swing low while RSI reads
higher than it did at that swing -- is `low < swing_low(n) and rsi(14) > rsi_at_swing_low(14, n)`.
Every expression in this field is rehearsed through `guards.check` against **real stored bars** for a
real universe symbol before `--write` is allowed (`guard_rehearsal`), not against a synthetic series:
a divergence expression the causality guard rejects is not usable, and this round had to find that out
before freezing rather than in the middle of a run.

**The structural finding that shapes this round, measured before it was frozen.** `signal_density`
counts how many bars each arm's entry is true on, per window, on the real bars, bounded by the design
cutoff. The divergence conjunction fires on roughly **1% of the bars the control fires on** and is
**exactly zero in most of the eight windows**. That is arithmetic about the rules, not a return, and it
is disclosed in `ROUND-41-PLAN.md` §5 as this round's most likely outcome: a gate that never fires is
not a null result, it is an unmeasured one, and a zero-trade window scores `adjusted_excess = 0.00`
rather than "no data" (`tools/score.py`'s `adjusted_excess` falls back to a zero exposure), so a sparse
arm can beat a losing control **by not trading**. The decision rule in the plan requires a minimum
trade count for exactly that reason. Nothing here was chosen by looking at a return, and no arm was
added or dropped after seeing one.

**Why three divergence lookbacks and not one.** 5 (the registry default), 10 (the headline arm, fixed
before any measurement) and 20. `PROTOCOL.md` §3 rule 4 forbids grid search and requires sensitivity
that demonstrates *insensitivity*; three levels of one parameter, all reported, all pre-registered, is
that. It also forecloses the only interesting objection to a sparse result -- "you picked a bad
lookback" -- since the sparsity holds at all three.

**Why no slot-cap factor.** Round 36 crossed its arms with two slot caps. Here the cap is c18's own 6
of 10 and it is left alone: the gate arms cut simultaneous qualifiers to about one percent of the
control's, so `max_positions` cannot bind in them, and a second cap arm would spend runtime on a
factor measured in advance as inert in half the field. The cost is stated rather than hidden -- this
round therefore says nothing about how the gate interacts with a harder-binding cap.

**The library is read, never written.** This tool touches the library JSON read-only (for the base
identity check and the disjointness recomputation) and this round's own cards directory. Nothing here
reads `data/accounts.toml`, `data/sectors.toml`, `data/store/ledger.sqlite` or anything under
`app.tax`; the cards it writes read only the Parquet/DuckDB bar store, like every other card here.

**Not investment advice.**
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
from collections.abc import Sequence
from decimal import Decimal

from app.backtest import guards
from app.backtest.models import GuardStatus
from app.config import get_settings
from app.market.models import Interval
from app.rules import grammar
from app.tournament.allocation import AllocationCard
from app.tournament.ladder import LadderCard
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from app.tournament.purposes import (
    DisjointnessViolation,
    Purpose,
    find_disjointness_violations,
)
from app.tournament.results import load_library

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r41-2026-09" / "cards"

#: The frozen card this round's control reproduces and whose rule every arm is built on.
C18_PATH = REPO / "backend" / "app" / "paper" / "library" / "candidates" / "c18-meanrev.json"

#: **c18-meanrev's own universe, in c18's own write order.** Ten defensive large caps -- staples,
#: branded pharma, integrated energy, one industrial, one big-box retailer -- every one of them with
#: a first stored daily bar before 1990, so all eight main windows are eligible for all six cells
#: (verified with `strategy-program/tools/windows.py --cards <this round's cards>` before the field
#: was frozen, not assumed).
#:
#: **The order is load-bearing and is c18's, not this round's.** `rank_by` is unset on every card
#: here, as it is on c18, so the write order is the slot tie-break; re-ordering it would make the
#: control a different card from the one it is supposed to reproduce, and `PROTOCOL.md` §7 prices
#: that accident at sigma = 21.2 points.
#:
#: Disjoint from the Roth book by construction (the Roth union is currently `AAPL ADBE AMAT BND CRM
#: CSCO IGV INTU ITA KLAC LRCX SSO VIG VNQ VUG XBI XHB XME XOP XRT XSD`), and recomputed from the
#: live library at build time rather than trusted from that list -- see `roth_symbols`.
UNIVERSE: tuple[str, ...] = (
    "JNJ", "MRK", "PG", "KO", "PEP", "CL", "XOM", "CVX", "MMM", "WMT",
)

#: c18-meanrev's entry, exit and brackets, hardcoded here so the field is readable at a glance and
#: then **asserted against the library JSON** by `check_base_matches_c18`. Hardcoding alone would let
#: the two drift silently; reading alone would hide what the round actually runs behind a file read.
BASE_ENTRY = "rsi(2) < 10 and close > sma(200)"
EXIT = "close > sma(5)"
STOP_LOSS_PCT = Decimal("0.08")
TAKE_PROFIT_PCT = None
MAX_HOLD_DAYS = 10
MAX_POSITIONS = 6
POSITION_PCT = Decimal("0.15")

#: The RSI period every gate that reads an oscillator uses. 14 is the textbook default and the one
#: `RSI_AT_SWING_SPEC`'s own `ParamSpec` carries; it is deliberately **not** c18's `rsi(2)`, because
#: a 2-period RSI at a swing pivot is a different statistic from the one the personas describe, and
#: reusing c18's number here would be a coincidence of spelling rather than a choice.
GATE_RSI_PERIOD = 14

#: The headline divergence lookback, fixed before any measurement. 5 and 20 flank it as the
#: sensitivity ladder; no level is preferred and all three are reported.
HEADLINE_LOOKBACK = 10


def divergence(lookback: int) -> str:
    """The bullish-divergence proxy at `lookback`: a lower low than the last confirmed swing low,
    while RSI reads higher than it did at that swing.

    Built from `lookback` in code rather than typed three times, so the three sensitivity arms are
    provably the same expression at three settings and cannot drift into being three rules.
    """
    return (
        f"low < swing_low({lookback}) and "
        f"rsi({GATE_RSI_PERIOD}) > rsi_at_swing_low({GATE_RSI_PERIOD}, {lookback})"
    )


def structure_half(lookback: int) -> str:
    """The price half of `divergence` on its own -- "price made a lower low", no oscillator."""
    return f"low < swing_low({lookback})"


def momentum_half(lookback: int) -> str:
    """The oscillator half of `divergence` on its own -- "RSI is above where it was at that swing"."""
    return f"rsi({GATE_RSI_PERIOD}) > rsi_at_swing_low({GATE_RSI_PERIOD}, {lookback})"


#: `(slug, gate expression or None, label)`, in the order the field is authored.
#:
#: The two halves are the *literal* conjuncts of `divergence(10)`, derived from the same helpers, so
#: "does the divergence beat both of its halves" is a decomposition rather than a comparison against
#: two rules that merely resemble it. That is the contrast the personas' claim actually turns on: they
#: say the conjunction is worth something the parts are not.
ARMS: tuple[tuple[str, str | None, str], ...] = (
    ("control", None, "c18-meanrev's entry, unchanged"),
    (
        "struct-lb10",
        structure_half(HEADLINE_LOOKBACK),
        "structure half only: a lower low than the last swing low",
    ),
    (
        "mom-lb10",
        momentum_half(HEADLINE_LOOKBACK),
        "oscillator half only: RSI above its value at the last swing low",
    ),
    ("div-lb5", divergence(5), "bullish divergence, swing lookback 5"),
    (
        "div-lb10",
        divergence(HEADLINE_LOOKBACK),
        "bullish divergence, swing lookback 10 (the headline arm)",
    ),
    ("div-lb20", divergence(20), "bullish divergence, swing lookback 20"),
)

#: The free numbers every card carries, itemised so a reader can check the count rather than trust
#: it. `PROTOCOL.md` §3 rule 3 budgets **ten per card** across entry, exit, the two brackets, the
#: hold cap, slot count and position size. Counted as *choices*: every one of these is c18's, frozen
#: in that card before this round was conceived, and none was chosen by looking at an outcome here.
BASE_FREE_NUMBERS: tuple[str, ...] = (
    "rsi period 2 (entry)",
    "rsi threshold 10 (entry)",
    "sma period 200 (entry)",
    "sma period 5 (exit)",
    "stop_loss_pct 0.08",
    "max_hold_days 10",
    "max_positions 6",
    "position_pct 0.15",
)


def gate_free_numbers(gate: str | None) -> tuple[str, ...]:
    """The free numbers a gate clause adds on top of `BASE_FREE_NUMBERS`.

    A swing lookback is one decision even when it appears in both conjuncts of a divergence (the two
    halves must reference the *same* pivot or the expression does not mean what it appears to mean --
    see `app.indicators.swing`'s module docstring), and `GATE_RSI_PERIOD` is one decision however many
    times it is spelled.
    """
    if gate is None:
        return ()
    numbers: list[str] = []
    lookbacks = {int(m) for m in re.findall(r"swing(?:_low)?\((?:\d+,\s*)?(\d+)\)", gate)}
    for lookback in sorted(lookbacks):
        numbers.append(f"swing lookback {lookback} (gate)")
    if f"rsi({GATE_RSI_PERIOD})" in gate:
        numbers.append(f"rsi period {GATE_RSI_PERIOD} (gate)")
    return tuple(numbers)


def free_number_count(gate: str | None) -> int:
    """How many free numbers a card carrying `gate` spends. Printed by `main`, asserted by the tests."""
    return len(BASE_FREE_NUMBERS) + len(gate_free_numbers(gate))


def entry_for(gate: str | None) -> str:
    """c18's entry with `gate` ANDed onto it. The one factor this round varies."""
    return BASE_ENTRY if gate is None else f"{BASE_ENTRY} and {gate}"


def _thesis(label: str, gate: str | None) -> str:
    if gate is None:
        gate_prose = (
            "This is the control cell: c18-meanrev's entry with nothing added, so its trade log must "
            "reproduce c18-meanrev's to the digit in any window both are run in. That is the round's "
            "instrument check, and if it fails, every contrast measured here is suspect."
        )
    else:
        gate_prose = (
            f"The confirmation gate ANDed onto that entry is `{gate}`, and it is the only thing "
            "that differs from the control."
        )
    return (
        f"Round 41 confirmation-stacking cell: {label}. {gate_prose} The round asks one question: "
        "does requiring a second, independent condition to agree with a mean-reversion entry change "
        "the result at all? Two ingested personas make that claim structurally -- creator-e "
        "teaches RSI divergence strictly as confirmation of a support/resistance structure and never "
        "as a standalone trigger, and creator-c stacks moving-average alignment with structure "
        "and pattern before entering. This programme has tested single-form entries exhaustively "
        "(rounds 17, 18 and 34: eight forms, eight exits, a regime filter, every marginal inside the "
        "21.2 percentage point noise floor) and has never tested an indicator-combination gate. The "
        "base is c18-meanrev's rule character for character -- entry rsi(2) < 10 and close > "
        "sma(200), exit close > sma(5), 8% stop, 10-day cap, six slots at 15%, its own ten defensive "
        "large caps in its own write order -- asserted against the library JSON at build time rather "
        "than retyped from memory. Nothing here is tuned: every base number is c18's, frozen before "
        "this round was conceived, and the gate spends one swing lookback and one RSI period. The "
        "divergence conjunction is known in advance to be extremely sparse on this base -- it fires "
        "on roughly one percent of the bars the control fires on, and on zero bars in most windows -- "
        "so a sparse arm's flat median is an unmeasured result, not a null one, and this round's "
        "decision rule requires a minimum trade count before any arm is read as evidence of "
        "anything. This is a measurement study on the taxable trading book; PROTOCOL.md section 9's "
        "r21 amendment means no card in it can be promoted, and none will be. See "
        "strategy-program/ROUND-41-PLAN.md for the pre-registration, the six predictions, the "
        "decision rule and the Benjamini-Hochberg correction taken across all six cells."
    )


#: Pre-registered failure regime, per `PROTOCOL.md` §3 rule 5. Shared across the field because every
#: cell is the same mean-reversion mechanism wearing a different gate, and inventing six different
#: sentences for one mechanism would be decoration rather than six predictions. The arm-specific half
#: is appended per cell below.
FALSIFICATION_BASE = (
    "Regime: this cell buys a 2-period RSI extreme inside an intact 200-day uptrend, so it is "
    "supposed to be worst in a grinding, sustained decline where 'oversold' keeps getting more "
    "oversold and the 200-day average has not yet rolled over -- `bear-2022` first, `gfc` second. "
    "The cell is falsified as a mean-reversion rule if its worst adjusted excess is in neither of "
    "those two windows, because then whatever it earned or lost was not the mechanism its own thesis "
    "claims exposure to. "
)

FALSIFICATION_CONTROL = (
    "As the control it carries a second, harder falsification that runs first: its trade log must "
    "equal c18-meanrev's to the digit in every window both are run in. Any difference means the "
    "instrument moved and no contrast in this round is interpretable."
)

FALSIFICATION_GATED = (
    "Round-level: the gate 'carries information' only if gate minus control exceeds 21.2pp on median "
    "adjusted excess, with the same sign in at least five of eight windows, surviving "
    "Benjamini-Hochberg over all six cells run, AND exceeding both of the divergence's own halves. "
    "Anything less is the null, and this cell is falsified as evidence for confirmation stacking. A "
    "structural falsification runs before any of that: an arm taking fewer than 20 trades across the "
    "eight windows is reported as UNMEASURED, never as a null, because a zero-trade window scores "
    "adjusted excess 0.00 and a gate that never fires can out-score a losing control by not trading."
)


def build() -> list[StrategyCard]:
    """The round's six frozen cards.

    Deterministic: same inputs, same list, same order, byte-identical model dumps. `ARMS` is a fixed
    tuple and nothing here reads a clock, a random source, the bar store or the filesystem.
    """
    cards: list[StrategyCard] = []
    for slug, gate, label in ARMS:
        cards.append(
            StrategyCard(
                agent_id=f"r41-{slug}",
                display_name=f"R41 {label}",
                discipline=Discipline.MEAN_REVERSION,
                purpose=Purpose.TRADING,
                thesis=_thesis(label, gate),
                falsification=FALSIFICATION_BASE
                + (FALSIFICATION_CONTROL if gate is None else FALSIFICATION_GATED),
                universe=UNIVERSE,
                entry=entry_for(gate),
                exit=EXIT,
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


# ---------------------------------------------------------------------------
# The base must be c18's, and be provably c18's
# ---------------------------------------------------------------------------


def c18() -> StrategyCard:
    """`c18-meanrev` as it sits in the live library. Read, never written."""
    return StrategyCard.model_validate_json(C18_PATH.read_text(encoding="utf-8"))


def check_base_matches_c18() -> list[str]:
    """Every field where this round's base differs from `c18-meanrev`'s. Empty is the passing state.

    The control cell exists to reproduce c18 to the digit, and the whole round is a set of contrasts
    against that control. If the base drifts from c18 -- a retyped threshold, a re-ordered universe,
    a bracket copied from the wrong card -- the reproduction check silently stops being one and every
    margin here is measured against a card nobody has a committed record for. So the identity is
    asserted against the library JSON rather than trusted, and `--write` refuses on any difference.

    `agent_id`, `display_name`, `discipline`, `thesis` and `falsification` are deliberately **not**
    compared: those are what a round card is allowed to differ in. `purpose` **is** compared and is
    `Purpose.TRADING` on both -- explicit here, defaulted on c18, which serialises identically.
    """
    base = c18()
    diffs: list[str] = []
    for field, mine, theirs in (
        ("entry", BASE_ENTRY, base.entry),
        ("exit", EXIT, base.exit),
        ("stop_loss_pct", STOP_LOSS_PCT, base.stop_loss_pct),
        ("take_profit_pct", TAKE_PROFIT_PCT, base.take_profit_pct),
        ("max_hold_days", MAX_HOLD_DAYS, base.max_hold_days),
        ("max_positions", MAX_POSITIONS, base.max_positions),
        ("position_pct", POSITION_PCT, base.position_pct),
        ("universe", UNIVERSE, base.universe),
        ("rank_by", None, base.rank_by),
        ("purpose", Purpose.TRADING, base.purpose),
    ):
        if mine != theirs:
            diffs.append(f"{field}: this round has {mine!r}, c18-meanrev has {theirs!r}")
    return diffs


# ---------------------------------------------------------------------------
# The binding constraint: no ticker a Roth card holds
# ---------------------------------------------------------------------------


def library_cards() -> list[StrategyCard | AllocationCard | LadderCard]:
    """Every purposed card in the live library, including the two tiers `load_library` does not walk.

    `app.tournament.results.load_library` covers `base`/`variants`/`candidates`/`retired`, the four
    `StrategyCard` tiers. `library/allocation/` and `library/ladder/` hold `AllocationCard`s and
    `LadderCard`s and are read separately -- the same gap rounds 34 and 36 record, and the same fix.
    Here the direction of the check is reversed from those rounds (this round's cards are *taxable*
    and must avoid the **Roth** union rather than the other way round), but the roster that has to be
    complete is the same one.
    """
    cards: list[StrategyCard | AllocationCard | LadderCard] = [
        card for tier_cards in load_library().values() for card in tier_cards
    ]
    library_root = get_settings().library_dir
    for tier, model in (("allocation", AllocationCard), ("ladder", LadderCard)):
        tier_dir = library_root / tier
        if not tier_dir.is_dir():
            continue
        for path in sorted(tier_dir.glob("*.json")):
            cards.append(model.model_validate_json(path.read_text(encoding="utf-8")))
    return cards


def roth_symbols(
    library: Sequence[StrategyCard | AllocationCard | LadderCard],
) -> frozenset[str]:
    """Every symbol any `roth`-purpose card in `library` can own a position in.

    Recomputed from the library on every call rather than pinned as a literal: the library is edited
    concurrently by other work in this programme, and a hardcoded roster would pass this check against
    a list that no longer describes the Roth book. Rev. Rul. 2008-5 is why the check exists at all --
    a loss realised in the taxable book and replaced inside an IRA within 30 days is disallowed
    outright, with no basis adjustment anywhere, which is strictly worse than an ordinary wash sale.
    """
    return frozenset(
        symbol
        for card in library
        if card.purpose is Purpose.ROTH
        for symbol in card.universe
    )


def check_disjointness(
    cards: Sequence[StrategyCard],
    library: Sequence[StrategyCard | AllocationCard | LadderCard],
) -> tuple[tuple[DisjointnessViolation, ...], tuple[DisjointnessViolation, ...]]:
    """`(mine, pre_existing)` -- violations this round's cards cause, and everyone else's.

    Both come from one `find_disjointness_violations` call over the library and this round's cards
    together, which is the only way to see a collision between a new card and an old one. This
    round's cards are the *non-Roth* side of any violation they cause, so the split is on
    `other_agent_id`, not on `roth_agent_id` the way rounds 34 and 36 split it. A violation between
    two cards already on disk is a real finding to surface, but it is not a reason to refuse to author
    a field that does not participate in it.
    """
    mine_ids = {card.agent_id for card in cards}
    violations = find_disjointness_violations([*library, *cards])
    return (
        tuple(v for v in violations if v.other_agent_id in mine_ids),
        tuple(v for v in violations if v.other_agent_id not in mine_ids),
    )


# ---------------------------------------------------------------------------
# Guard rehearsal -- against real stored bars, not a synthetic series
# ---------------------------------------------------------------------------

#: The symbol the guard rehearsal runs against. `JNJ` is the first name in `UNIVERSE` and has stored
#: daily bars back to 1970, so a 200-day warmup plus the 40 post-warmup bars `app.backtest.guards`
#: needs to demonstrate causality are available many times over.
REHEARSAL_SYMBOL = UNIVERSE[0]


def _bars(symbol: str, *, end: dt.date | None = None):
    """Stored daily bars for `symbol`. Imported lazily so the module can be loaded without a store."""
    from app.market import store

    return store.read_frame(symbol, Interval.DAY, end=end)


def guard_rehearsal() -> list[tuple[str, str, str]]:
    """`(what, expression, status)` for every expression this field uses, on **real** bars.

    Round 36 rehearsed against a synthetic series and left the real check to the runner. That is not
    good enough here: `swing` and `rsi_at_swing` publish a pivot `lookback` bars after it forms, which
    is the entire reason they are causal, and a smooth synthetic oscillation is exactly the series
    least likely to expose a problem with pivot detection. A divergence expression the causality guard
    rejects is not usable, and `--write` refuses rather than freezing a field that cannot run.

    The runner re-checks every expression against **each** universe symbol's own bars before the card
    trades (`app.tournament.runner._guard_card`); this catches, early, an expression that could never
    pass anywhere.
    """
    bars = _bars(REHEARSAL_SYMBOL)
    checks: list[tuple[str, str]] = [("exit", EXIT)]
    for slug, gate, _label in ARMS:
        if gate is not None:
            checks.append((f"gate ({slug})", gate))
        checks.append((f"entry ({slug})", entry_for(gate)))

    out: list[tuple[str, str, str]] = []
    for what, expression in checks:
        report = guards.check(expression, bars, interval=Interval.DAY)
        out.append((what, expression, report.status.value))
    return out


def parse_rehearsal() -> list[str]:
    """Parse every expression through the real grammar. Raises `RuleSyntaxError` on anything that is
    not a condition -- which is what proves `rsi_at_swing_low(14, 10)` really is the identifier that
    selects the `low` output, rather than an identifier this round assumed existed."""
    notes = [f"exit parses: {EXIT}"]
    grammar.parse(EXIT)
    for slug, gate, _label in ARMS:
        entry = entry_for(gate)
        grammar.parse(entry)
        notes.append(f"{slug}: entry parses: {entry}")
    return notes


# ---------------------------------------------------------------------------
# Structural pre-check: how often does each arm's entry even fire?
# ---------------------------------------------------------------------------


def signal_density(
    end: dt.date = DESIGN_THROUGH,
) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    """`(per_window, full_history)` -- entry-true bar counts per arm, summed over `UNIVERSE`.

    **This is arithmetic about the rules, not a return**, and it is the reason the plan can
    pre-register "this gate will not fire" with a number instead of a worry. A signal bar is not a
    trade -- the slot cap, an already-open lot and the hold cap all sit between them -- but zero
    signal bars in a window is exactly zero trades in that window, which is the direction that
    matters here.

    `end` bounds **every** count at the design cutoff, so nothing in the printed summary is computed
    from data an analyst is not allowed to have looked at. One main window extends past that cutoff --
    `recent` runs to 2026-08-18 against a cutoff of 2026-02-13 -- so its column is a count over the
    part of the window this round is allowed to see, not over the whole window. `main` labels it as
    such; understating a count in the direction of "we saw less" is the only safe direction to be
    wrong in here.
    """
    import sys

    from app.rules.evaluate import evaluate

    # `strategy-program` is not an importable package name (the hyphen), so the sibling
    # `windows.py` is reached by putting this file's own directory on the path -- which running
    # this file as a script already does, and loading it by path in a test does not.
    tools_dir = str(pathlib.Path(__file__).resolve().parent)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from windows import MAIN_WINDOWS  # type: ignore[import-not-found]

    per_window: dict[str, dict[str, int]] = {slug: {} for slug, _g, _l in ARMS}
    full: dict[str, int] = {slug: 0 for slug, _g, _l in ARMS}

    for symbol in UNIVERSE:
        bars = _bars(symbol, end=end)
        dates = bars["ts"].dt.date
        for slug, gate, _label in ARMS:
            fired = evaluate(
                grammar.parse(entry_for(gate)), bars, interval=Interval.DAY
            ).fillna(False)
            full[slug] += int(fired.sum())
            for tag, (start, stop, _desc) in MAIN_WINDOWS.items():
                mask = ((dates >= start) & (dates <= stop)).to_numpy()
                per_window[slug][tag] = per_window[slug].get(tag, 0) + int(fired[mask].sum())
    return per_window, full


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="write the cards to the round directory"
    )
    parser.add_argument(
        "--skip-density",
        action="store_true",
        help="skip the signal-density table (it reads every universe symbol's full history)",
    )
    args = parser.parse_args(argv)

    cards = build()

    print(f"built {len(cards)} cards: {len(ARMS)} confirmation-gate arms, one factor varying")
    print(f"  universe ({len(UNIVERSE)}, c18's own order): {' '.join(UNIVERSE)}")
    print(f"  base entry: {BASE_ENTRY}")
    print(f"  exit:       {EXIT}")
    print(
        f"  brackets:   stop {STOP_LOSS_PCT}, take-profit {TAKE_PROFIT_PCT}, "
        f"hold cap {MAX_HOLD_DAYS}d, {MAX_POSITIONS} slots at {POSITION_PCT}"
    )
    print()

    print("field:")
    gates = {slug: gate for slug, gate, _label in ARMS}
    for card in cards:
        gate = gates[card.agent_id.removeprefix("r41-")]
        print(f"  {card.agent_id:<16} [{free_number_count(gate)} free numbers]  {card.entry}")
    print()

    print("base identity against the live c18-meanrev.json:")
    base_diffs = check_base_matches_c18()
    if base_diffs:
        for diff in base_diffs:
            print(f"  DRIFT {diff}")
    else:
        print(
            "  entry, exit, brackets, hold cap, slots, sizing, universe order, rank_by, purpose"
            " -- all identical"
        )
    print()

    print("parse rehearsal:")
    for note in parse_rehearsal():
        print(f"  {note}")
    print()

    print(f"guard rehearsal (REAL stored daily bars for {REHEARSAL_SYMBOL}):")
    failed_guards: list[str] = []
    for what, expression, status in guard_rehearsal():
        print(f"  {status:<8} {what:<20} ->  {expression}")
        if status != GuardStatus.PASSED.value:
            failed_guards.append(what)
    print()

    library = library_cards()
    roth = roth_symbols(library)
    overlap = sorted(set(UNIVERSE) & roth)
    mine, pre_existing = check_disjointness(cards, library)
    print("Roth disjointness (recomputed from the live library, all six tiers):")
    print(f"  {len(library)} purposed cards; {len(roth)} tickers held by roth cards")
    print(f"  this round's universe intersected with them: {overlap or 'none'}")
    print(f"  find_disjointness_violations naming a card of this round: {len(mine)}")
    for violation in pre_existing:
        print(f"  PRE-EXISTING (not this round): {violation.message}")
    print(
        "  NOTE: ticker disjointness is necessary, not sufficient. IRC 1091 turns on securities "
        "being substantially identical, not on symbols matching."
    )
    print()

    if not args.skip_density:
        print(
            "structural pre-check -- entry-true bars per arm (real bars, all 10 symbols, "
            f"bounded at the design cutoff {DESIGN_THROUGH}):"
        )
        per_window, full = signal_density()
        tags = list(next(iter(per_window.values())).keys())
        print("  " + f"{'arm':<13}" + "".join(f"{tag:>11}" for tag in tags) + f"{'FULL':>9}")
        for slug, _gate, _label in ARMS:
            row = "".join(f"{per_window[slug][tag]:>11}" for tag in tags)
            print(f"  {slug:<13}{row}{full[slug]:>9}")
        print(
            f"  `recent` runs to 2026-08-18 and is counted only to the design cutoff "
            f"{DESIGN_THROUGH}; every other column is the whole window."
        )
        print(
            "  A zero here is exactly zero trades in that window, and a zero-trade window scores "
            "adjusted excess 0.00 rather than 'no data' -- see ROUND-41-PLAN.md sections 5 and 6."
        )
        print()

    blocked = bool(base_diffs) or bool(failed_guards) or bool(mine) or bool(overlap)
    if blocked:
        print("REFUSING TO WRITE:")
        if base_diffs:
            print("  the base has drifted from c18-meanrev; the control would reproduce nothing")
        if failed_guards:
            print(f"  guard rehearsal failed for: {', '.join(failed_guards)}")
        for violation in mine:
            print(f"  {violation.message}")
        for symbol in overlap:
            print(f"  {symbol} is in this round's universe and in a roth card's")
        if mine or overlap:
            print(
                "  Rev. Rul. 2008-5: a replacement purchase inside an IRA destroys the taxable loss "
                "outright. Fix the universe, do not waive this."
            )
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
