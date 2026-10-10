"""Round 45: persona method cards x cross-persona enhancements, on the taxable trading book.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round45.py           # dry run
    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round45.py --write   # author the field

`ROUND-45-PLAN.md` is the pre-registration this executes. Read it first (and
`strategy-program/MIX-AND-MATCH-PLAN.md` section 3, which pins this round's field).

This authors the round's field and nothing else -- the cards are then run by
`strategy-program/tools/run_round.sh` and scored by `score.py`, exactly like every other card round.
This file does NOT run a backtest.

**The question.** Three bases, each ANOTHER persona's method rendered as a rule (`kim` = Straight
Creator E's confirmation-conjunct card, already measured and seated as `r40-rsi-confirm-slots6`; `bee` =
Creator C's vault-drafted `ma-crossover`; `creator-b` = Creator B's vault-drafted
`band-reversion`), crossed with four single-decision enhancements each borrowed from a THIRD
persona's stated method (`trend100` from Creator C, `rr5` and `trim115` from Creator B,
`risk1pct` from Creator E). Fourteen cells: five arms on `kim` and `creator-b`, four on `bee` (which
already carries the `trend100` filter in its base entry, so that arm is skipped for it).

**Why every arm's entry/exit/bracket is composed by string or Decimal arithmetic, never retyped.**
`BASES` names each base's entry, exit and brackets exactly once; `build()` derives every arm from it
by the ONE substitution the arm's row in `ROUND-45-PLAN.md` names (`+ " and close > sma(100)"` for
`trend100`, `5 * stop_loss_pct` for `rr5`'s take-profit, `Decimal("0.01") / stop_loss_pct` for
`risk1pct`'s position size, `+ " or close > sma(200) * 1.15"` for `trim115`'s exit). There is no
second, hand-typed copy of any base expression anywhere in this file.
`tests/test_round45_field.py` asserts every arm's construction against its base rather than trusting
it.

**Drift asserts.** `kim`'s base is pinned to equal, field for field, the seated library card
`backend/app/paper/library/candidates/r40-rsi-confirm-slots6.json`. `bee`'s and `creator-b`'s bases are
pinned to equal their vault strategy drafts
(`data/vault/influencers/{creator-c,creator-b}/strategy/1.json`) on entry/exit/brackets/slots (`bee`)
or entry/exit/stop/slots (`creator-b` -- its hold cap is deliberately capped from the draft's 252 to 150,
see below). `check_drift()` reads both sources from disk and REFUSES to write if any of them has
moved since this round was pinned.

**The reachability gate**, inherited from round 40's motivating defect (a 4-sigma Bollinger threshold
that could structurally never fire, `sqrt(n-1)` bounds the achievable z-score at n=4, and passed
every other pre-flight check because none of them asks whether a rule can ever be *true*). `--write`
measures every DISTINCT entry and exit against the actual bar store (bounded to `DESIGN_THROUGH`)
with `app.market.store.read_frame` (in-memory, no file lock) and the real evaluator
(`app.rules.grammar.parse` + `app.rules.evaluate.evaluate`). It REFUSES to write if any expression
fires 0 times, if a `trend100` entry retains less than 2% or more than 98% of its own base's firings,
or if any entry fires on more than 300 of every 1000 symbol-sessions.

**Not investment advice. The round has NOT been run.** This file only authors and range-checks the
field; every number it prints is a firing count over price-only bars, not a return.
"""

from __future__ import annotations

import argparse
import json
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

OUT = REPO / "data" / "rounds" / "r45-2026-09" / "cards"

#: The 12-name taxable growth pool, verbatim from `app.evolution.universe._TAXABLE_GROWTH` -- the
#: SAME universe rounds 40 and 42 used, and NOT any of the three vault drafts' own universes. The
#: drafts' universes are today's bullish tickers (several 2022-25 listings that fail window
#: eligibility, per `MIX-AND-MATCH-PLAN.md` section 2); this round runs every rule on the programme's
#: mechanically-defined pool instead, disclosed as a substitution, exactly as that section states.
UNIVERSE: tuple[str, ...] = _TAXABLE_GROWTH

#: Persona attribution, matching the slugs the vault and prior rounds use.
PERSONA_KIM = "Creator E (creator-e)"
PERSONA_BEE = "Creator C (creator-c)"
PERSONA_WSAJ = "Creator B (wsaj)"

#: base -> its pinned field. Every entry/exit/bracket/slot value here is asserted against its
#: drift source by `check_drift()` before any card is written. `creator-b`'s `max_hold_days` is the ONE
#: deliberate deviation from its drift source (252 in the draft) -- capped to 150, well under the
#: `trading` purpose's 9-month horizon ceiling (`app.tournament.purposes.PurposeSpec.horizon_months_max`),
#: and disclosed here and in `ROUND-45-PLAN.md` rather than silently rounded.
BASES: dict[str, dict[str, object]] = {
    "kim": {
        "persona": PERSONA_KIM,
        "discipline": Discipline.MOMENTUM,
        "entry": "close crosses_above bb_mid(20, 2) and rsi(14) > rsi_at_swing_high(14, 10)",
        "exit": "close crosses_below bb_mid(20, 2)",
        "stop_loss_pct": Decimal("0.12"),
        "take_profit_pct": None,
        "max_hold_days": 150,
        "max_positions": 6,
        "position_pct": Decimal("0.125"),
        "has_trend100": True,
        "drift_source": "backend/app/paper/library/candidates/r40-rsi-confirm-slots6.json",
        "drift_kind": "library_card",
        "rationale_quote": (
            "round 40's sole positive persona cell (arm-minus-control +4.82pp at 6 slots), still "
            "inside the 21.2pp floor, seated by direction"
        ),
    },
    "bee": {
        "persona": PERSONA_BEE,
        "discipline": Discipline.TREND,
        "entry": "close > sma(100) and ema(12) crosses_above ema(50)",
        "exit": "ema(12) crosses_below ema(50)",
        "stop_loss_pct": Decimal("0.08"),
        "take_profit_pct": Decimal("0.16"),
        "max_hold_days": 30,
        "max_positions": 5,
        "position_pct": Decimal("0.15"),
        "has_trend100": False,  # the base entry already carries a 100-day trend filter.
        "drift_source": "data/vault/influencers/creator-c/strategy/1.json",
        "drift_kind": "vault_draft",
        # <=15 words, verbatim from the draft's `rationale` field.
        "rationale_quote": (
            "A 12/50 EMA crossover inside a 100-day regime filter directly represents this approach."
        ),
        "fidelity": 0.38,
    },
    "wsaj": {
        "persona": PERSONA_WSAJ,
        "discipline": Discipline.MEAN_REVERSION,
        "entry": "close > sma(200) and close < bb_lower(26, 2)",
        "exit": "close crosses_above bb_mid(26, 2)",
        "stop_loss_pct": Decimal("0.12"),
        "take_profit_pct": None,
        # Draft says 252 (roughly a year of sessions); capped to 150 -- well under the `trading`
        # purpose's 9-month horizon ceiling (`PurposeSpec.horizon_months_max = 9`). Disclosed, not
        # asserted equal to the draft by `check_drift()`.
        "max_hold_days": 150,
        "max_positions": 4,
        "position_pct": Decimal("0.20"),
        "has_trend100": True,
        "drift_source": "data/vault/influencers/wsaj/strategy/1.json",
        "drift_kind": "vault_draft",
        # <=15 words, verbatim from the draft's `rationale` field.
        "rationale_quote": (
            "Band-reversion is chosen as the structural proxy: buying names undervalued by P/E"
        ),
        "fidelity": 0.0,
    },
}

#: Which base carries `trend100` (every base except `bee`, whose base entry already has the filter).
#: 14 cells total: 5 (kim) + 4 (bee) + 5 (creator-b).
ARM_ORDER: tuple[str, ...] = ("base", "trend100", "rr5", "risk1pct", "trim115")

#: enhancement -> whose persona's component it borrows (MIX-AND-MATCH-PLAN.md section 3's arm table).
ENHANCEMENT_PERSONA: dict[str, str] = {
    "trend100": PERSONA_BEE,
    "rr5": PERSONA_WSAJ,
    "risk1pct": PERSONA_KIM,
    "trim115": PERSONA_WSAJ,
}

#: The programme's measured noise floor, `PROTOCOL.md` section 7, and this round's decision rule
#: threshold (`MIX-AND-MATCH-PLAN.md` section 3, round 45): an enhancement earns something only if
#: its marginal exceeds this AND its arm cells survive BH q<0.10 over m=14.
NOISE_FLOOR_PP = 21.2

#: The reachability bound on an ENTRY: more than 300 fires per 1000 symbol-sessions is near-always-on.
MAX_FIRES_PER_1000 = 300

#: A `trend100` entry's retention of its own base's firings must sit inside this band, or the added
#: filter is a no-op (>98%) or a near-off-switch (<2%) and has not been tested.
TREND100_RETENTION_MIN = 0.02
TREND100_RETENTION_MAX = 0.98

#: Matches every numeric literal in a rule expression, for the PROTOCOL section 3 parameter budget.
#: Same pattern rounds 35/36/40/42 use.
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def free_numbers(card: StrategyCard) -> int:
    """PROTOCOL section 3's parameter count for one card: ten free numbers, "counted across `entry`,
    `exit`, the two brackets, the hold cap, slot count and position size".

    Distinct numeric *values* across the expressions (a value reused in entry and exit is one choice,
    not two), plus one per present bracket field, plus two for `max_positions` and `position_pct`.
    Identical convention to `round35.py` / `round36.py` / `round40.py` / `round42.py`.
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
    2008-5). Recomputed via `app.evolution.promotion._library_cards`, which walks all six library
    tiers, rather than hardcoded, because concurrent sessions edit the library and a pasted constant
    is correct only until the next commit -- identical to `round40.py`/`round42.py`'s own helper.
    """
    return frozenset(
        sym
        for card in _library_cards(settings)
        if getattr(card, "purpose", None) is Purpose.ROTH
        for sym in card.universe
    )


def entry_for(base_key: str, arm: str) -> str:
    """The entry string for one (base, arm) pair, by construction from `BASES[base_key]["entry"]`.

    Only `trend100` changes the entry (appends the trend filter). Every other arm's entry equals the
    base's, unchanged -- `rr5` changes the take-profit, `risk1pct` changes the position size, and
    `trim115` changes the exit, each isolating exactly one decision per `PROTOCOL.md` section 7.
    """
    base_entry = BASES[base_key]["entry"]
    if arm == "trend100":
        return f"{base_entry} and close > sma(100)"
    return base_entry


def exit_for(base_key: str, arm: str) -> str:
    """The exit string for one (base, arm) pair, by construction. Only `trim115` changes it."""
    base_exit = BASES[base_key]["exit"]
    if arm == "trim115":
        return f"{base_exit} or close > sma(200) * 1.15"
    return base_exit


def take_profit_for(base_key: str, arm: str) -> Decimal | None:
    """The take-profit for one (base, arm) pair. Only `rr5` changes it: `5 * stop_loss_pct`."""
    spec = BASES[base_key]
    if arm == "rr5":
        return Decimal("5") * spec["stop_loss_pct"]
    return spec["take_profit_pct"]


def position_pct_for(base_key: str, arm: str) -> Decimal:
    """The position size for one (base, arm) pair. Only `risk1pct` changes it:
    `Decimal("0.01") / stop_loss_pct`, quantised to 3 decimal places -- slots (`max_positions`) are
    left unchanged, per `ROUND-45-PLAN.md`'s pinning."""
    spec = BASES[base_key]
    if arm == "risk1pct":
        return (Decimal("0.01") / spec["stop_loss_pct"]).quantize(Decimal("0.001"))
    return spec["position_pct"]


def arms_for(base_key: str) -> tuple[str, ...]:
    """Every arm built for one base: all five, except `trend100` is skipped for `bee` (whose base
    entry already carries a 100-day trend filter -- `MIX-AND-MATCH-PLAN.md` section 3)."""
    if BASES[base_key]["has_trend100"]:
        return ARM_ORDER
    return tuple(a for a in ARM_ORDER if a != "trend100")


def _hindsight_note(base_key: str) -> str:
    spec = BASES[base_key]
    if spec["drift_kind"] == "library_card":
        return (
            "This base is a MEASURED card (`r40-rsi-confirm-slots6`), not a vault draft, and carries "
            "no `published`/fidelity caveat of its own -- round 40 already found it inside the "
            "21.2pp floor."
        )
    return (
        f"This base is a VAULT DRAFT (`{spec['drift_source']}`), machine-mapped from the persona's "
        f"described methodology onto this programme's fixed rule vocabulary -- fidelity "
        f"{spec['fidelity']}. The draft's rationale: \"{spec['rationale_quote']}\" Every note behind "
        "it has `published = null` (`PERSONA-HYPOTHESES.md` section 7), so hindsight against this "
        "round's eight windows is unbounded; the draft is inspired by, not a faithful reproduction "
        "of, what the persona actually trades."
    )


def _thesis(base_key: str, arm: str) -> str:
    spec = BASES[base_key]
    persona = spec["persona"]
    base_txt = (
        f"Round 45 cell on the taxable trading book: base `{base_key}` (persona: {persona}), entry "
        f"'{entry_for(base_key, 'base')}', exit '{exit_for(base_key, 'base')}', stop "
        f"{spec['stop_loss_pct']}, take-profit {spec['take_profit_pct']}, hold cap "
        f"{spec['max_hold_days']}, {spec['max_positions']} slots at {spec['position_pct']} each. "
        + _hindsight_note(base_key)
        + " "
    )
    if arm == "base":
        arm_txt = (
            "This is the BASE cell: the persona's method with no cross-persona enhancement. Every "
            "other arm on this base changes exactly ONE thing against this cell, per PROTOCOL.md "
            "section 7's one-decision rule."
        )
    elif arm == "trend100":
        arm_txt = (
            f"Arm `trend100`, borrowed from {PERSONA_BEE}'s stated 20-week/100-day trend filter: "
            f"entry becomes '{entry_for(base_key, arm)}' -- the base entry plus 'and close > sma(100)', "
            "nothing else changed. Predicted to cut trades relative to the base."
        )
    elif arm == "rr5":
        arm_txt = (
            f"Arm `rr5`, borrowed from {PERSONA_WSAJ}'s risk-first 5:1 max-loss discipline: "
            f"take-profit becomes {take_profit_for(base_key, arm)} (5 x this base's stop), nothing "
            "else changed. Predicted to be near-identical to the base -- the 5:1 bracket rarely binds "
            "(rounds 17/18 measured 0.14pp) -- and the report tool counts how many of this arm's "
            "closed trades actually exited on the target."
        )
    elif arm == "risk1pct":
        arm_txt = (
            f"Arm `risk1pct`, borrowed from {PERSONA_KIM}'s 1%-risk-per-trade sizing: position size "
            f"becomes {position_pct_for(base_key, arm)} (0.01 / this base's stop, quantised to 3dp), "
            "slot count unchanged, nothing else changed. Predicted to lower mean exposure and raise "
            "adjusted excess per unit of capital deployed without changing the sign pattern across "
            "windows."
        )
    else:  # trim115
        arm_txt = (
            f"Arm `trim115`, borrowed from {PERSONA_WSAJ}'s trim-after-exceptional-gains discipline: "
            f"exit becomes '{exit_for(base_key, arm)}' -- the base exit plus 'or close > sma(200) * "
            "1.15', nothing else changed. Predicted to lower exposure and lose to the base in "
            "bull-2024 and recent (r44's trim arm: +0.4 to +2.4pp, null)."
        )
    tail = (
        " Pre-registered 2026-09-09, before any measurement (see strategy-program/ROUND-45-PLAN.md "
        "and strategy-program/MIX-AND-MATCH-PLAN.md section 3). Nothing here is promotable -- the "
        "`trading` purpose is exempt from PROTOCOL.md section 6 promotion (r21 amendment); this is a "
        "measurement study, report only. Not investment advice."
    )
    return base_txt + arm_txt + tail


def _falsification(base_key: str, arm: str) -> str:
    common = (
        f"Honest prior: the null (rounds 17/18/34/38/39/40/42 put form, exit, rotation, style tilts "
        f"and confirmation conjuncts all inside the {NOISE_FLOOR_PP}pp floor). Decision rule: an "
        "enhancement earns something only if its marginal -- the mean over its bases of (arm median "
        "adjusted excess minus base median) -- exceeds the floor AND its arm cells survive BH "
        "q<0.10 over m=14 (each arm cell contrasted with its own base; base cells carry p=None but "
        "count in m). Pre-registered predictions: (1) null for all four enhancements. (2) `trend100` "
        "cuts trades vs base on both bases it applies to (kim, wsaj). (3) `rr5` cells are nearly "
        "identical to their base -- fewer than 10% of exits are expected to be the take-profit "
        "target, counted from the run files' trade logs. (4) `risk1pct` lowers mean exposure and "
        "raises adjusted excess per unit exposure without changing sign patterns across windows. (5) "
        "`trim115` lowers exposure and loses to base in bull-2024 and recent. Nothing here is "
        "promotable regardless of outcome (`trading` purpose, PROTOCOL.md r21 amendment). Sign flips "
        "by regime are expected; only the eight-window median is safe to read."
    )
    if arm == "base":
        return "Baseline against which this base's four enhancement arms are contrasted. " + common
    return common


def build() -> list[StrategyCard]:
    """The 14-card field: 5 arms on `kim` and `creator-b`, 4 on `bee` (skips `trend100`). Deterministic."""
    cards: list[StrategyCard] = []
    for base_key, spec in BASES.items():
        for arm in arms_for(base_key):
            agent_id = f"r45-{base_key}-{arm}"
            cards.append(
                StrategyCard(
                    agent_id=agent_id,
                    display_name=f"{base_key} {arm}",
                    discipline=spec["discipline"],
                    purpose=Purpose.TRADING,
                    thesis=_thesis(base_key, arm),
                    falsification=_falsification(base_key, arm),
                    universe=UNIVERSE,
                    entry=entry_for(base_key, arm),
                    exit=exit_for(base_key, arm),
                    stop_loss_pct=spec["stop_loss_pct"],
                    take_profit_pct=take_profit_for(base_key, arm),
                    max_hold_days=spec["max_hold_days"],
                    max_positions=spec["max_positions"],
                    position_pct=position_pct_for(base_key, arm),
                    rank_by=None,
                    designed_through=DESIGN_THROUGH,
                )
            )
    return cards


# ---------------------------------------------------------------------------
# Drift asserts -- the pinned BASES dict must equal its library-card / vault-draft source, field for
# field (except creator-b's disclosed hold-cap cap). Run before every write.
# ---------------------------------------------------------------------------

def check_drift() -> list[str]:
    """Compare every base's pinned entry/exit/brackets/slots against its on-disk drift source.

    `kim` is asserted equal to the seated library card in full. `bee` is asserted equal to its vault
    draft's entry/exit/brackets/slots. `creator-b` is asserted equal to its vault draft's
    entry/exit/stop/slots -- `max_hold_days` is EXCLUDED from this check because it is deliberately
    capped from the draft's 252 to 150 (the `trading` purpose's 9-month horizon ceiling), and that
    deviation is disclosed, not silently matched. Returns a list of human-readable mismatches; empty
    means clean.
    """
    problems: list[str] = []

    kim_path = REPO / BASES["kim"]["drift_source"]
    if not kim_path.is_file():
        return [f"kim drift source missing: {kim_path}"]
    kim_card = json.loads(kim_path.read_text(encoding="utf-8"))
    kim_spec = BASES["kim"]
    kim_checks = {
        "entry": (kim_card["entry"], kim_spec["entry"]),
        "exit": (kim_card["exit"], kim_spec["exit"]),
        "stop_loss_pct": (Decimal(kim_card["stop_loss_pct"]), kim_spec["stop_loss_pct"]),
        "take_profit_pct": (
            None if kim_card["take_profit_pct"] is None else Decimal(kim_card["take_profit_pct"]),
            kim_spec["take_profit_pct"],
        ),
        "max_hold_days": (kim_card["max_hold_days"], kim_spec["max_hold_days"]),
        "max_positions": (kim_card["max_positions"], kim_spec["max_positions"]),
        "position_pct": (Decimal(kim_card["position_pct"]), kim_spec["position_pct"]),
    }
    for field, (actual, expected) in kim_checks.items():
        if actual != expected:
            problems.append(f"kim.{field}: library card has {actual!r}, round 45 pinned {expected!r}")

    for base_key, fields in (("bee", ("entry", "exit", "stop_loss_pct", "take_profit_pct",
                                       "max_hold_days", "max_positions", "position_pct")),
                              ("wsaj", ("entry", "exit", "stop_loss_pct", "max_positions",
                                        "position_pct"))):
        draft_path = REPO / BASES[base_key]["drift_source"]
        if not draft_path.is_file():
            problems.append(f"{base_key} drift source missing: {draft_path}")
            continue
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        draft_card = draft["draft"]["card"]
        spec = BASES[base_key]
        for field in fields:
            expected = spec[field]
            raw = draft_card[field]
            if field in ("stop_loss_pct", "take_profit_pct", "position_pct"):
                actual = None if raw is None else Decimal(raw)
            else:
                actual = raw
            if actual != expected:
                problems.append(
                    f"{base_key}.{field}: vault draft has {actual!r}, round 45 pinned {expected!r}"
                )

    return problems


# ---------------------------------------------------------------------------
# Reachability gate.
# ---------------------------------------------------------------------------

def _distinct_expressions() -> dict[str, dict[str, str]]:
    """Every DISTINCT entry and exit expression across the round, keyed by a readable label.

    Per base: one base entry, one base exit, one `trim115` exit (base exit + the trim clause), and --
    for `kim`/`creator-b` only -- one `trend100` entry (base entry + the trend clause). `rr5` and
    `risk1pct` never change entry or exit, so they add nothing new here. 11 expressions total (4 for
    kim, 3 for bee, 4 for creator-b).
    """
    out: dict[str, dict[str, str]] = {}
    for base_key, spec in BASES.items():
        out[f"{base_key}-base (entry)"] = {"expr": entry_for(base_key, "base"), "kind": "entry"}
        if spec["has_trend100"]:
            out[f"{base_key}-trend100 (entry)"] = {
                "expr": entry_for(base_key, "trend100"), "kind": "entry", "base_of": f"{base_key}-base (entry)"
            }
        out[f"{base_key}-base (exit)"] = {"expr": exit_for(base_key, "base"), "kind": "exit"}
        out[f"{base_key}-trim115 (exit)"] = {"expr": exit_for(base_key, "trim115"), "kind": "exit"}
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
    every 1000 symbol-sessions; a `trend100` entry retaining outside
    [`TREND100_RETENTION_MIN`, `TREND100_RETENTION_MAX`] of its own base's firings. Exits are measured
    and printed but exempt from the per-1000 ceiling.
    """
    sessions = 0
    for symbol in UNIVERSE:
        sessions += len(read_frame(symbol, Interval.DAY, end=DESIGN_THROUGH, settings=settings))

    table: dict[str, dict[str, object]] = {}
    refusals: list[str] = []
    for label, info in _distinct_expressions().items():
        expr = info["expr"]
        fires = _fires(expr, settings)
        per_1000 = (1000 * fires / sessions) if sessions else float("inf")
        table[label] = {"expr": expr, "fires": fires, "per_1000": per_1000, "kind": info["kind"]}
        if fires == 0:
            refusals.append(f"{label}: '{expr}' fires 0 times -- structurally unreachable")
        elif info["kind"] == "entry" and per_1000 > MAX_FIRES_PER_1000:
            refusals.append(
                f"{label}: {per_1000:.1f}/1000 sessions > {MAX_FIRES_PER_1000}/1000 -- near-always-on entry"
            )

    for label, info in _distinct_expressions().items():
        base_of = info.get("base_of")
        if base_of is None:
            continue
        base_fires = table[base_of]["fires"]
        trend_fires = table[label]["fires"]
        retention = (trend_fires / base_fires) if base_fires else float("inf")
        table[label]["retention_of_base"] = retention
        if retention < TREND100_RETENTION_MIN or retention > TREND100_RETENTION_MAX:
            refusals.append(
                f"{label}: retention {retention:.2%} of '{base_of}' outside "
                f"[{TREND100_RETENTION_MIN:.0%}, {TREND100_RETENTION_MAX:.0%}]"
            )

    return table, sessions, refusals


def _print_reachability(table: dict[str, dict[str, object]], sessions: int) -> None:
    print(f"reachability over {len(UNIVERSE)} names, {sessions} symbol-sessions, bounded to "
          f"{DESIGN_THROUGH.isoformat()}")
    print(f"  {'expression':32s}  {'text':60s}  {'fires':>7s}  {'per 1000':>9s}  {'retention':>10s}")
    print("  " + "-" * 122)
    for label, row in table.items():
        ret = row.get("retention_of_base")
        ret_txt = "--" if ret is None else f"{ret:.2%}"
        print(f"  {label:32s}  {row['expr']!s:60s}  {int(row['fires']):>7d}  {row['per_1000']:>8.2f}  {ret_txt:>10s}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the cards to the round directory")
    args = parser.parse_args(argv)

    settings = get_settings()
    cards = build()

    print(f"built {len(cards)} cards: {len(BASES)} bases ({', '.join(BASES)})")
    for card in cards:
        print(f"  {card.agent_id:22s}  free_numbers={free_numbers(card)}")

    # Reachability probe -- printed on BOTH the dry run and the write.
    table, sessions, refusals = reachability(settings)
    print()
    _print_reachability(table, sessions)

    # Parameter budget.
    over_budget = [c.agent_id for c in cards if free_numbers(c) > 10]
    if over_budget:
        refusals.append(f"parameter budget: over 10 free numbers: {', '.join(over_budget)}")

    # Drift asserts.
    drift_problems = check_drift()
    print()
    if drift_problems:
        print("drift check: MISMATCH")
        for p in drift_problems:
            print(f"  - {p}")
        refusals.extend(f"drift: {p}" for p in drift_problems)
    else:
        print("drift check: clean -- kim/bee/wsaj bases equal their library card / vault drafts")

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
