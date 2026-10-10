"""Round 48: does Creator E's 1%-risk sizing do to EVERY seated trading card what round 45 found it
did to his own?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round48.py           # dry run
    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round48.py --write   # author the field

`ROUND-48-PLAN.md` is the pre-registration this executes. Read it first (and
`strategy-program/ROUND-45-PLAN.md`, whose finding this round follows up on, and
`strategy-program/MIX-AND-MATCH-PLAN.md`).

This authors the round's field and nothing else -- the cards are then run by
`strategy-program/tools/run_round.sh` and scored by `score.py`, exactly like every other card round.
This file does NOT run a backtest.

**The question.** Round 45 found that Creator E's `position_pct = 0.01 / stop_loss_pct` sizing was
the one enhancement with a consistent shape on his own card: worst window and IQR both shrink, mean
exposure falls, and the per-window sign pattern is unchanged -- at a cost of 1.35pp of median. This is
the feedback-loop follow-up: apply the identical resizing to EVERY rules card currently seated on
`app.paperdesk.desk.AGENT_IDS`, the live trading roster, and see whether the shape repeats.

**Five bases, read VERBATIM from the library JSON at build time.** Every entry/exit/bracket/hold/slot/
universe/discipline value below comes from `json.loads` on the seated library file, merged with only
the fields a round card must carry that a library card does not (`agent_id`, `display_name`, `thesis`,
`falsification`, `purpose`, `designed_through`) -- never retyped, never a second hand-copied literal to
drift from the source. `_load_base_card` refuses (raises) if a library file is missing.

- `b3` <- `backend/app/paper/library/variants/B3-concentrated.json`
- `arot` <- `backend/app/paper/library/candidates/A-rotation.json`
- `ctrend` <- `backend/app/paper/library/base/C-trend.json`
- `bmom` <- `backend/app/paper/library/base/B-momentum.json`
- `i13f` <- `backend/app/paper/library/candidates/I-13f-duquesne-2026q2.json` -- a 13F-provenance card,
  `desk_only=True` and `designed_through=2026-08-14` in the library (it cannot enter a tournament round
  as-is: `app.tournament.jobs._resolve_cards` refuses any `desk_only` card by name). Round 48 needs it
  IN the round -- unranked on early windows by provenance, not refused outright -- so its `desk_only`
  is overridden to `False` and `designed_through` is pinned to `DESIGN_THROUGH` like every other cell
  here, and its filing-date provenance (2026-08-14, the source card's own `designed_through`) is
  preserved instead through the sidecar mechanism `strategy-program/tools/windows.py` already has for
  exactly this case -- a card whose model carries no `universe_knowable_from` field --
  `write_provenance_sidecar()` below writes `data/rounds/r48-2026-09/cards/provenance.json`. See
  `ROUND-48-PLAN.md` section 3 for why this is the honest treatment rather than a silent drop of the
  provenance constraint.

**Two arms per base.**

- `base`: the card as seated, only `agent_id`/`display_name`/`thesis`/`falsification` changed, plus
  `purpose` set explicitly to TRADING (the library files omit it; the field defaults to TRADING, but
  round 48 states it rather than relying on a default an unrelated future change could move) and
  `designed_through` pinned to `DESIGN_THROUGH`.
- `risk1pct`: `position_pct = (Decimal("0.01") / stop_loss_pct).quantize(Decimal("0.001"))`, everything
  else (including `max_positions`) unchanged from `base`. Built with `base_card.model_copy(update=...)`
  so there is no second, independent computation of the base's own fields to drift from it -- the only
  new number is the position size itself. Every one of this round's five bases carries
  `stop_loss_pct = Decimal("0.12")`, so `risk1pct` lands at the identical `Decimal("0.083")` on every
  base -- a fact this round did not choose, the library did.

**Reachability is inherited, not re-measured.** These five cards have already run in rounds 24 and 26
and trade live on the paper desk today; round 45's bar-store firing-rate probe exists to catch a
*newly written* expression that might be structurally unreachable, which is not this round's risk.
What `--write` does instead: parse every entry/exit with the real grammar (`app.rules.grammar.parse`),
and recompute the roth union from disk (`roth_union()`, identical to `round45.py`'s own helper) and
refuse if the taxable universe here intersects it.

**Not investment advice. The round has NOT been run.** This file only authors and range-checks the
field; every number it prints is a parameter or a set membership, not a return.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from decimal import Decimal
from typing import Any

from app.config import get_settings
from app.evolution.promotion import _library_cards
from app.rules import grammar
from app.tournament.models import DESIGN_THROUGH, StrategyCard
from app.tournament.purposes import Purpose

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r48-2026-09" / "cards"

#: slug -> the seated library file it is read from verbatim, relative to REPO. These are five of the
#: six cards on `app.paperdesk.desk.AGENT_IDS` (the trading roster) -- the sixth, `r40-rsi-confirm-
#: slots6`, is round 45's own `kim` base and is not repeated here.
LIBRARY_PATHS: dict[str, str] = {
    "b3": "backend/app/paper/library/variants/B3-concentrated.json",
    "arot": "backend/app/paper/library/candidates/A-rotation.json",
    "ctrend": "backend/app/paper/library/base/C-trend.json",
    "bmom": "backend/app/paper/library/base/B-momentum.json",
    "i13f": "backend/app/paper/library/candidates/I-13f-duquesne-2026q2.json",
}

#: Which of the five bases carries 13F point-in-time provenance -- see the module docstring and
#: `ROUND-48-PLAN.md` section 3. `2026-08-14` is `I-13f-duquesne-2026q2.json`'s own `designed_through`
#: in the library: the date Duquesne Family Office's 2026-Q2 13F became public, per that card's thesis.
PROVENANCE: dict[str, str] = {"i13f": "2026-08-14"}

ARMS: tuple[str, ...] = ("base", "risk1pct")

#: The programme's measured noise floor (`PROTOCOL.md` section 7) and this round's decision-rule
#: threshold (`ROUND-48-PLAN.md` section 4): the resizing earns something only if its marginal exceeds
#: this AND every risk1pct cell survives BH q<0.10 over m=10.
NOISE_FLOOR_PP = 21.2

#: Matches every numeric literal in a rule expression, for PROTOCOL.md section 3's parameter budget.
#: Identical pattern to rounds 35/36/40/42/45.
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def free_numbers(card: StrategyCard) -> int:
    """PROTOCOL section 3's parameter count for one card. Identical convention to `round45.free_numbers`
    (distinct numeric values across `entry`/`exit`/`rank_by`, plus one per present bracket, plus two
    for `max_positions` and `position_pct`)."""
    text = " ".join(part for part in (card.entry, card.exit, card.rank_by or "") if part)
    values = {match.group(0) for match in _NUMBER.finditer(text)}
    brackets = sum(
        1
        for field in (card.stop_loss_pct, card.take_profit_pct, card.max_hold_days)
        if field is not None
    )
    return len(values) + brackets + 2  # + max_positions + position_pct


def roth_union(settings) -> frozenset[str]:
    """Every ticker held by any live `roth`-purpose library card, recomputed from disk -- identical
    helper to `round45.roth_union` / `round42.py`'s, for the same reason: the library is edited by
    concurrent sessions and a hardcoded set is correct only until the next commit."""
    return frozenset(
        sym
        for card in _library_cards(settings)
        if getattr(card, "purpose", None) is Purpose.ROTH
        for sym in card.universe
    )


def missing_library_files() -> list[str]:
    """Every `LIBRARY_PATHS` entry that does not exist on disk right now. `--write` refuses if this is
    non-empty; see the module docstring."""
    return [path for path in LIBRARY_PATHS.values() if not (REPO / path).is_file()]


def _load_raw(slug: str) -> dict[str, Any]:
    path = REPO / LIBRARY_PATHS[slug]
    if not path.is_file():
        raise FileNotFoundError(
            f"round48 refuses to write: {slug}'s library file is missing: {path}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _thesis(slug: str, arm: str, raw: dict[str, Any]) -> str:
    seated_txt = (
        f"Round 48 cell on the taxable trading book: base `{slug}` (`{raw['agent_id']}`, the card "
        f"seated on `app.paperdesk.desk.AGENT_IDS` today), read verbatim from "
        f"`{LIBRARY_PATHS[slug]}` -- entry '{raw['entry']}', exit '{raw['exit']}', stop "
        f"{raw['stop_loss_pct']}, take-profit {raw.get('take_profit_pct')}, hold cap "
        f"{raw.get('max_hold_days')}, {raw['max_positions']} slots at {raw['position_pct']} each. "
    )
    if slug in PROVENANCE:
        seated_txt += (
            f"This base carries 13F point-in-time provenance: its universe was not knowable before "
            f"{PROVENANCE[slug]} (the filing date), so it is expected UNRANKED on every main window "
            "that starts before that date -- reported, not interpreted, per PROTOCOL.md section 5 and "
            "section 9's r2 amendment. "
        )
    if arm == "base":
        arm_txt = (
            "This is the BASE cell: the seated card unchanged except for its identifying fields. Its "
            "sibling risk1pct cell changes exactly one thing against it, per PROTOCOL.md section 7's "
            "one-decision rule."
        )
    else:
        arm_txt = (
            "Arm `risk1pct`, round 45's follow-up question asked of every seated trading card: "
            "position size becomes Decimal('0.01') / this base's stop_loss_pct, quantised to 3dp "
            "(0.083 here, since every base in this round carries a 0.12 stop) -- slot count and every "
            "other field unchanged. Round 45 measured this exact resizing lower the tail (worst window, "
            "IQR) and mean exposure on Creator E's own card without moving the per-window sign "
            "pattern, at a cost to the median. Predicted here to repeat that shape on the four other "
            "bases, and to be near-inert on the fifth if its own position size barely moves relative to "
            "its stop."
        )
    tail = (
        " Pre-registered 2026-09-09, before any measurement (see strategy-program/ROUND-48-PLAN.md). "
        "Nothing here is promotable -- the `trading` purpose is exempt from PROTOCOL.md section 6 "
        "promotion (r21 amendment); this is a measurement study, report only, and a decision to resize "
        "a seated card for real is the owner's, about risk, not this round's to make. Not investment "
        "advice."
    )
    return seated_txt + arm_txt + tail


def _falsification(slug: str, arm: str) -> str:
    common = (
        f"Decision rule (ROUND-48-PLAN.md section 4): risk1pct earns something only if its marginal -- "
        f"the mean over the five bases of (risk1pct median adjusted excess minus that base's own "
        f"median) -- exceeds the {NOISE_FLOOR_PP}pp floor AND every risk1pct cell survives BH q<0.10 "
        "over m=10 (base cells carry p=None but still occupy a seat in m). Pre-registered predictions: "
        "(1) null on the median marginal (|marginal| < 5pp). (2) worst window shallower on at least 4 "
        "of 5 bases. (3) IQR narrower on at least 4 of 5. (4) mean exposure lower on 5 of 5. (5) "
        "per-window sign pattern identical on at least 7 of 8 windows for every base. (6) adjusted "
        "excess per unit exposure within +/-3pp of the base on every base -- sizing is not alpha. (7) "
        "`i13f` cells unranked by provenance on the main windows, reported not interpreted. (8) "
        "PROTOCOL.md section 4's caveat applies: a smaller book's shallower worst window is a size "
        "effect, and the report prints the worst window in dollars of realised P&L per cell so that "
        "effect is visible in currency, not only in percentage points. Nothing here is promotable "
        "regardless of outcome (`trading` purpose, PROTOCOL.md r21 amendment)."
    )
    if arm == "base":
        return "Baseline against which this base's risk1pct cell is contrasted. " + common
    return common


def _load_base_card(slug: str) -> StrategyCard:
    """The `base` arm: `slug`'s seated library card, read verbatim, with only the round-card
    identifying fields overridden. `purpose` and `desk_only` are stated explicitly rather than left to
    default -- see the module docstring for why `i13f` needs `desk_only=False` here."""
    raw = _load_raw(slug)
    overrides = {
        "agent_id": f"r48-{slug}-base",
        "display_name": f"{slug} base",
        "thesis": _thesis(slug, "base", raw),
        "falsification": _falsification(slug, "base"),
        "purpose": Purpose.TRADING,
        "designed_through": DESIGN_THROUGH,
        "desk_only": False,
    }
    merged = {**raw, **overrides}
    return StrategyCard.model_validate(merged)


def _risk1pct_card(slug: str, base_card: StrategyCard, raw: dict[str, Any]) -> StrategyCard:
    """The `risk1pct` arm, built from `base_card` by `model_copy` -- the ONE substitution this round
    makes, never a second hand-typed copy of the base's own fields."""
    position_pct = (Decimal("0.01") / base_card.stop_loss_pct).quantize(Decimal("0.001"))
    assert position_pct * base_card.max_positions <= Decimal("1"), (
        f"{slug}: risk1pct position_pct {position_pct} x max_positions {base_card.max_positions} "
        "exceeds the whole book"
    )
    return base_card.model_copy(
        update={
            "agent_id": f"r48-{slug}-risk1pct",
            "display_name": f"{slug} risk1pct",
            "thesis": _thesis(slug, "risk1pct", raw),
            "falsification": _falsification(slug, "risk1pct"),
            "position_pct": position_pct,
        }
    )


def build() -> list[StrategyCard]:
    """The 10-card field: `base` and `risk1pct` for each of the five seated bases. Deterministic."""
    cards: list[StrategyCard] = []
    for slug in LIBRARY_PATHS:
        raw = _load_raw(slug)
        base_card = _load_base_card(slug)
        cards.append(base_card)
        cards.append(_risk1pct_card(slug, base_card, raw))
    return cards


def write_provenance_sidecar(out: pathlib.Path) -> None:
    """`out/provenance.json` -- `{agent_id: "YYYY-MM-DD"}` -- the fallback source
    `strategy-program/tools/windows.py::resolve_universe_knowable_from` reads for a card whose
    `StrategyCard` model carries no `universe_knowable_from` field. Both of `i13f`'s round-48 cells
    (base and risk1pct) get the identical 2026-08-14 filing date -- resizing a card's position does not
    change when its basket became knowable."""
    sidecar = {
        f"r48-{slug}-{arm}": date
        for slug, date in PROVENANCE.items()
        for arm in ARMS
    }
    (out / "provenance.json").write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the cards to the round directory")
    args = parser.parse_args(argv)

    settings = get_settings()

    missing = missing_library_files()
    if missing:
        print("REFUSING to write -- library file(s) missing:")
        for m in missing:
            print(f"  - {m}")
        return 1

    cards = build()

    print(f"built {len(cards)} cards: {len(LIBRARY_PATHS)} bases ({', '.join(LIBRARY_PATHS)}) x "
          f"{len(ARMS)} arms ({', '.join(ARMS)})")
    for card in cards:
        print(f"  {card.agent_id:22s}  stop={card.stop_loss_pct}  position_pct={card.position_pct}  "
              f"slots={card.max_positions}  free_numbers={free_numbers(card)}")

    refusals: list[str] = []

    # Parameter budget.
    over_budget = [c.agent_id for c in cards if free_numbers(c) > 10]
    if over_budget:
        refusals.append(f"parameter budget: over 10 free numbers: {', '.join(over_budget)}")

    # Every entry/exit parses under the real grammar.
    parse_problems = []
    for card in cards:
        try:
            grammar.parse(card.entry)
            grammar.parse(card.exit)
        except Exception as exc:  # report every parse failure, not just the first
            parse_problems.append(f"{card.agent_id}: {exc}")
    print()
    if parse_problems:
        print("grammar parse: FAILED")
        for p in parse_problems:
            print(f"  - {p}")
        refusals.extend(f"parse: {p}" for p in parse_problems)
    else:
        print(f"grammar parse: clean -- every entry/exit across {len(cards)} cards parses")

    # Roth disjointness.
    roth = roth_union(settings)
    union_universe: set[str] = set()
    for card in cards:
        union_universe |= set(card.universe)
    violation = sorted(union_universe & roth)
    print()
    print(f"roth union: {len(roth)} tickers; round-48 universes intersect it in: "
          f"{violation if violation else 'nothing'}")
    if violation:
        refusals.append(f"roth disjointness: round-48 universes use roth tickers {violation}")

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
    write_provenance_sidecar(OUT)
    print(f"\nwrote {len(cards)} cards + provenance.json to {OUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
