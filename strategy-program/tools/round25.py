"""Round 25: the curve's *rate of change*, against its level.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round25.py --write --run

`ROUND-25-PLAN.md` is the pre-registration this executes. Read it first.

Rounds 22 and 23 answered the curve as an entry gate and as a sizing term; both null in 3 of 3. This
round takes the last untouched shape.

    A  control   no tilt
    B  level     macro(T10Y2Y) < 0, shift_expr "-0.5 * macro(T10Y2Y)"     -- round 23's c-sized
    C  rate      macro(T10Y2Y) < 0, shift_expr "-1.748 * macro(T10Y2Y)"   -- reading the 20-session change

**A rate of change is not expressible in the DSL** (plan section 2): `macro()` takes a bare series
name, `MacroRef` has no lag, and the indicator registry operates on the OHLCV frame. Arm C therefore
reads a series that has been *substituted* with its own 20-session change, via the same in-process
`macro_pin.active_pin` swap `round22_null.py` and `round23_null.py` use -- so binding, guard and
engine run unchanged, and **nothing is written to a pin file**. A file on disk named `T10Y2Y` holding
deltas would be a trap for every later reader.

**Causality holds by construction.** `ROC(d) = value(d) - value(d - 20)`; both terms are on or before
`d`, and the later of them *is* `T10Y2Y(d)`, so whatever release lag makes the level knowable makes
the change knowable. The derived series carries the original reference dates, so `macro_binding`'s
join applies to it unchanged.

**Arm B is round 23's `c-sized`, unchanged**, which makes plan prediction 1 an instrument check: it
must reproduce that round's committed figures or this round is void. `--run` asserts it.

**Not investment advice.**
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import pathlib
import sys
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import round23 as R23

from app.config import get_settings
from app.market.macro_models import MacroPoint, MacroSeries, MacroSource, MacroUnit
from app.paper.mandate import default_mandate
from app.rules import macro_pin
from app.rules.macro_pin import read_pin
from app.rules.nodes import MacroField
from app.tournament.allocation import AllocationCard, run_allocation

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r25-2026-08"

#: Plan section 3a. One month of sessions, fixed as a convention before any return was looked at. No
#: other lookback was evaluated against an outcome.
LOOKBACK = 20

#: Plan section 3b. Both coefficients are properties of the pinned series, computed before any card
#: ran. B moves 0.0974 of weight per session over the window set; C at k=1 moves 0.0557; so k = 1.748
#: makes the two arms move the same *total* weight and differ only in when they move it.
LEVEL_EXPR = "-0.5 * macro(T10Y2Y)"
RATE_EXPR = "-1.748 * macro(T10Y2Y)"

#: Reused from round 23 rather than copied, so "same sleeves, same windows, same capital" is
#: structurally true instead of asserted. Round 23's amendment 2 explains why the seated
#: `qld-schd-sgov` card cannot be used here.
SLEEVES = R23.SLEEVES
WINDOWS = R23.WINDOWS
CAPITAL = R23.CAPITAL
MACRO_PIN = R23.MACRO_PIN
TILT_FROM, TILT_TO = R23.TILT_FROM, R23.TILT_TO

ARMS: dict[str, str | None] = {
    "a-control": None,
    "b-level": LEVEL_EXPR,
    "c-rate": RATE_EXPR,
}

#: The arm whose macro series is replaced by its own rate of change. The others read the pin as
#: committed.
SUBSTITUTED = "c-rate"


def rate_of_change(lookback: int = LOOKBACK) -> dict[MacroField, MacroSeries]:
    """The pinned T10Y2Y, replaced by its `lookback`-session change, on the original dates.

    Points before the first computable change are dropped rather than zero-filled: a zero would be a
    fabricated "no change" reading that the condition `< 0` would silently treat as not firing.
    """
    series = read_pin(MACRO_PIN)[MacroField.T10Y2Y]
    pts = [p for p in series.points if p.value is not None]
    derived = [
        MacroPoint(date=pts[i].date, value=pts[i].value - pts[i - lookback].value)
        for i in range(lookback, len(pts))
    ]
    return {
        MacroField.T10Y2Y: MacroSeries(
            series_id="T10Y2Y",
            title=f"T10Y2Y {lookback}-session change (round 25 derived series, NOT the level)",
            unit=MacroUnit.PERCENT_SPREAD,
            source=MacroSource.FRED,
            points=derived,
        )
    }


def build() -> dict[str, AllocationCard]:
    base = json.loads(R23.BASE.read_text(encoding="utf-8"))
    cards: dict[str, AllocationCard] = {}
    for arm, expr in ARMS.items():
        payload = dict(base)
        payload["sleeves"] = [{"symbol": s, "target_weight": w} for s, w in SLEEVES]
        payload["agent_id"] = f"r25-{arm}"
        payload["display_name"] = f"Round 25 {arm}"
        payload["rules"] = []
        if expr is not None:
            payload["rules"] = [
                {
                    "condition": "macro(T10Y2Y) < 0",
                    "on_symbol": TILT_FROM,
                    "from_symbol": TILT_FROM,
                    "to_symbol": TILT_TO,
                    "shift_expr": expr,
                }
            ]
        reads = "its 20-session change" if arm == SUBSTITUTED else "its level"
        payload["thesis"] = (
            "Round 25 arm. A static 35/40/25 XLK/XLP/XLU allocation, rotating out of technology into "
            f"consumer staples when the US yield curve signal is negative, reading {reads}. Arm A "
            "applies no tilt; arm B sizes the shift by how inverted the curve is; arm C sizes it by "
            "how fast the curve is falling. The two tilted arms are calibrated to move the same total "
            "weight over the window set, computed from the pinned series before any card ran, so they "
            "differ only in which signal drives them. Arm C reads a derived series and is NOT "
            "expressible as a card on this engine; it measures a hypothesis, not a shippable "
            "capability. A purpose-built three-sector allocation; it bears on no seated card's record. "
            "Nothing in this round is promotable. See strategy-program/ROUND-25-PLAN.md."
        )
        cards[arm] = AllocationCard.model_validate(payload)
    return cards


def _run_arm(arm: str, card: AllocationCard, settings: object, mandate: object,
             start: dt.date, end: dt.date) -> object:
    """Run one arm, substituting the derived series for the duration if this is the rate arm."""
    if arm != SUBSTITUTED:
        return run_allocation(card, settings=settings, mandate=mandate, start=start, end=end)
    series = rate_of_change()
    macro_pin.clear_pin_cache()
    original = macro_pin.active_pin
    macro_pin.active_pin = lambda path=None, _s=series: _s  # type: ignore[assignment]
    try:
        return run_allocation(card, settings=settings, mandate=mandate, start=start, end=end)
    finally:
        macro_pin.active_pin = original  # type: ignore[assignment]
        macro_pin.clear_pin_cache()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="author the arms")
    parser.add_argument("--run", action="store_true", help="run them over the three windows")
    args = parser.parse_args(argv)

    cards = build()
    print(f"built {len(cards)} arms from {R23.BASE.name}")
    for arm, c in cards.items():
        rule = c.rules[0] if c.rules else None
        src = " [DERIVED: 20-session change]" if arm == SUBSTITUTED else ""
        print(f"  {arm:10s} {'no tilt' if rule is None else str(rule.shift_expr)}{src}")

    if args.write:
        (OUT / "cards").mkdir(parents=True, exist_ok=True)
        for _arm, c in cards.items():
            (OUT / "cards" / f"{c.agent_id}.json").write_text(
                c.model_dump_json(indent=2, exclude_none=False) + "\n", encoding="utf-8"
            )
        print(f"\nwrote {len(cards)} cards to {(OUT / 'cards').relative_to(REPO).as_posix()}")

    if not args.run:
        print("\n(pass --run to execute)")
        return 0

    import os

    os.environ.setdefault("INVDASH_MACRO_PIN", str(MACRO_PIN))
    print(f"macro pin: {MACRO_PIN.relative_to(REPO).as_posix()}")

    mandate = dataclasses.replace(
        default_mandate(starting_cash=CAPITAL),
        max_single_name_weight=Decimal(1),
        allow_fractional_shares=True,
    )
    settings = get_settings()
    results: dict[str, dict[str, dict[str, float]]] = {}

    print()
    for tag, start, end in WINDOWS:
        print(f"--- {tag}  {start} -> {end} ---")
        results[tag] = {}
        for arm, card in cards.items():
            r = _run_arm(arm, card, settings, mandate, start, end)
            results[tag][arm] = {
                "ending_equity": float(r.ending_equity),
                "total_return": float(r.total_return) * 100,
                "max_drawdown": float(r.max_drawdown) * 100,
                "capital_exposure": float(r.capital_exposure or 0) * 100,
                "trades": len(r.trades),
                "rejections": len(r.rejections),
            }
            m = results[tag][arm]
            print(
                f"  {arm:10s} return {m['total_return']:+8.2f}%   maxDD {m['max_drawdown']:+7.2f}%   "
                f"exposure {m['capital_exposure']:5.1f}%   trades {m['trades']:3d}   rej {m['rejections']}"
            )
        a, b, c = (results[tag][k]["total_return"] for k in ARMS)
        print(f"    |A-B| {abs(a - b):6.2f}pp   |A-C| {abs(a - c):6.2f}pp   |B-C| {abs(b - c):6.2f}pp")

    # Plan prediction 1: an instrument check, not a hypothesis. Arm B is round 23's `c-sized` card on
    # the same windows under the same pin, so it must reproduce that round's committed figures. If it
    # does not, this round is measuring something other than it claims and nothing is written.
    prior = json.loads((REPO / "data/rounds/r23-2026-08/results.json").read_text(encoding="utf-8"))
    drift = [
        f"{tag}.{field}: round 23 {prior[tag]['c-sized'][field]!r}, here {results[tag]['b-level'][field]!r}"
        for tag, _s, _e in WINDOWS
        for field in ("ending_equity", "total_return", "max_drawdown", "trades")
        if abs(prior[tag]["c-sized"][field] - results[tag]["b-level"][field]) > 1e-9
    ]
    if drift:
        print("\nREFUSING TO WRITE -- arm B does not reproduce round 23's c-sized:")
        for line in drift:
            print(f"  {line}")
        return 1
    print("\ninstrument check: arm B reproduces round 23's c-sized in all three windows")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {(OUT / 'results.json').relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
