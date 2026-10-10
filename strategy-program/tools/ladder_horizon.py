"""How long does a drawdown ladder actually stay levered, in calendar months?

The question `PurposeSpec.horizon_months_max` asks of every other card shape, asked of the one shape
that has no field to answer it with. A `LadderCard` carries no `max_hold_days` -- it never goes to
cash, it re-weights sleeves -- so nothing in the type system or the engine bounds how long a book
running one stays committed to its leveraged sleeve. This measures it instead of arguing about it::

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe \
        strategy-program/tools/ladder_horizon.py

**Method.** Run the card through the real engine (`app.tournament.ladder.run_ladder_card`, the same
call the paper desk makes) over the longest window the bar store supports, and read the round trips
in the leveraged sleeve off the trade log. One round trip is one armed cycle: the ladder bought
leverage on a confirmed drawdown rung and sold it when the recovery clause closed the cycle. The
gap between entry and exit is how long that book was committed.

Nothing is reimplemented here. The state machine is not replicated, the arming rule is not restated,
and no number is derived from anything but `RealisedTrade.entry_date` / `.exit_date` -- which is the
whole point, because a hand-rolled copy of the arming logic would measure the copy.

**Why the window starts 2006-07.** `QLD`'s first bar is 2006-06-20, so the dot-com crash is
unreachable for this card under any substitution and the deepest drawdown in range is the GFC.
The figure this prints is therefore a floor on the card's true horizon, not a bound.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, "backend")

from app.config import Settings
from app.paperdesk.desk import _mandate
from app.tournament.ladder import LadderCard, run_ladder_card
from app.tournament.purposes import PURPOSE_SPECS, Purpose

LIBRARY = Path("backend/app/paper/library/ladder")
DEFAULT_START = dt.date(2006, 7, 1)
DAYS_PER_MONTH = 30.44


def measure(card_file: str, *, purpose: Purpose, start: dt.date, end: dt.date) -> dict[str, object]:
    """Every armed cycle of one ladder card, with the longest in calendar months."""
    card = LadderCard.model_validate_json((LIBRARY / card_file).read_text(encoding="utf-8"))
    result = run_ladder_card(
        card, settings=Settings(), mandate=_mandate(purpose), start=start, end=end
    )
    cycles = []
    for trade in result.trades:
        if trade.symbol != card.leveraged_symbol:
            continue
        exit_date = getattr(trade, "exit_date", None)
        closed = exit_date is not None
        days = ((exit_date or end) - trade.entry_date).days
        cycles.append(
            {
                "entered": trade.entry_date.isoformat(),
                "exited": exit_date.isoformat() if closed else None,
                "open_at_end": not closed,
                "calendar_days": days,
                "months": round(days / DAYS_PER_MONTH, 1),
            }
        )
    longest = max((c["calendar_days"] for c in cycles), default=0)
    return {
        "agent_id": card.agent_id,
        "leveraged_symbol": card.leveraged_symbol,
        "purpose": purpose.value,
        "window": [start.isoformat(), end.isoformat()],
        "cycles": cycles,
        "longest_days": longest,
        "longest_months": round(longest / DAYS_PER_MONTH, 1),
        "horizon_months_max": PURPOSE_SPECS[purpose].horizon_months_max,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end", type=dt.date.fromisoformat, default=dt.date(2026, 8, 28))
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    reports = [
        measure("qld-schd-ief.json", purpose=Purpose.TRADING, start=DEFAULT_START, end=args.end),
        measure("sso-vig-bnd.json", purpose=Purpose.ROTH, start=DEFAULT_START, end=args.end),
    ]

    for r in reports:
        cap = r["horizon_months_max"]
        print(f"== {r['agent_id']}  ({r['purpose']} book, leveraged sleeve {r['leveraged_symbol']})")
        print(f"   window {r['window'][0]} .. {r['window'][1]}, {len(r['cycles'])} armed cycles\n")
        print(f"   {'entered':<12} {'exited':<12} {'cal days':>10} {'months':>8}")
        for c in r["cycles"]:
            exited = c["exited"] or "OPEN"
            tail = "  (still open)" if c["open_at_end"] else ""
            print(
                f"   {c['entered']:<12} {exited:<12} "
                f"{c['calendar_days']:>10} {c['months']:>8.1f}{tail}"
            )
        verdict = (
            "no bound on this purpose"
            if cap is None
            else ("INSIDE" if r["longest_months"] <= cap else "OUTSIDE")
        )
        print(
            f"\n   longest armed stretch: {r['longest_months']} months"
            f"  vs horizon_months_max={cap}  -> {verdict}\n"
        )

    if args.json:
        args.json.write_text(json.dumps(reports, indent=1), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
