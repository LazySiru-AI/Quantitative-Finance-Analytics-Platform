"""Round 16 follow-up: is the decide/fill lag what the 0.66% divergence is made of?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/r16_fill_lag.py

WHY THIS EXISTS, AND A CORRECTION TO ROUND 16'S OWN RECORD
----------------------------------------------------------
Round 16 measured that the cash constraint accounts for none of the 0.6567% gap between
`run_allocation` and `contributions.simulate` -- zero underfunded buys across 31 cells. Its
`SELECTION.md` then listed the remaining suspects, in order:

    1. Whole-share fills. `PaperBroker` transacts shares; the harness transacts dollars.
    2. Settlement lag.
    3. The decide/fill lag.

**Suspect 1 is wrong, and was wrong when it was written.** `r15_control.py:168` already passes
`allow_fractional_shares=True`, with its own comment saying why: "no whole-share flooring noise --
simulate() has none either." The control has been eliminating that term from the start. Listing it
first as the leading candidate was an error of not re-reading the control being explained.

That leaves the fill convention, which this script tests directly.

WHAT THE TWO PATHS ACTUALLY DO
-------------------------------
`run_allocation` decides on session `i`'s **close** and fills at session `i+1`'s **open** -- the
same no-lookahead convention `run_card` uses, and the reason a card cannot act on a price it could
not have seen.

`contributions.simulate` has one price series and uses `closes[s][i]` for both. It decides and fills
at the same close.

So the harness systematically transacts at a price the engine could not have got. Over a window with
two rebalances that is a small, one-off difference; over a window with many it compounds.

THE TEST
--------
Run `simulate` twice on the identical card and window, changing only the price series it fills at:

  A. `closes[i]`            -- what it does today
  B. `opens[i+1]`           -- the price the engine would actually have filled at

If the gap to `run_allocation` collapses under B, the fill convention is the term. If it does not,
settlement lag is the remaining suspect and this script has eliminated the second of three.

Note what is deliberately NOT changed: the weights. `r15_weight_gate.py` proved those match the
engine exactly, 753 comparisons at zero. Only the price each target is transacted at moves.

**Not investment advice.**
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import contributions as C

from app.config import get_settings
from app.market.models import Interval
from app.market.store import read_frame
from app.paper.mandate import default_mandate
from app.tournament.allocation import AllocationCard, run_allocation
from app.tournament.weightfn import card_weight_fn

REPO = pathlib.Path(__file__).resolve().parents[2]
CARD = REPO / "backend" / "app" / "paper" / "library" / "allocation" / "qld-schd-sgov.json"

#: Same window as `r15_control.py`: inside one calendar year, so `simulate`'s annual contribution
#: fires exactly once and the comparison is against a single lump sum rather than a drip.
WARM_START = dt.date(2022, 1, 3)
START = dt.date(2022, 8, 23)
END = dt.date(2022, 12, 30)
CAPITAL = 100_000.0


def main() -> int:
    settings = get_settings()
    card = AllocationCard.model_validate_json(CARD.read_text(encoding="utf-8"))

    frames = {s: read_frame(s, Interval.DAY, settings=settings) for s in card.universe}
    closes_by_date = {
        s: {d.date(): float(c) for d, c in zip(f["ts"], f["close"], strict=True)} for s, f in frames.items()
    }
    opens_by_date = {
        s: {d.date(): float(o) for d, o in zip(f["ts"], f["open"], strict=True)} for s, f in frames.items()
    }
    axis = sorted(set.intersection(*(set(m) for m in closes_by_date.values())))
    axis = [d for d in axis if d <= END]

    full_closes = {s: [closes_by_date[s][d] for d in axis] for s in card.universe}
    lo = next(i for i, d in enumerate(axis) if d >= START)
    hi = max(i for i, d in enumerate(axis) if d <= END)

    # --- the engine ------------------------------------------------------------------------
    mandate = default_mandate(starting_cash=Decimal(str(CAPITAL)))
    import dataclasses

    mandate = dataclasses.replace(
        mandate,
        max_single_name_weight=Decimal(1),
        allow_fractional_shares=True,
        slippage_bps=Decimal(0),
        commission_per_trade=Decimal(0),
    )
    engine = run_allocation(card, settings=settings, mandate=mandate, start=START, end=END)
    engine_end = float(engine.ending_equity)

    # --- the harness, two fill conventions --------------------------------------------------
    def run(prices: dict[str, list[float]], label: str) -> float:
        fn = card_weight_fn(card)
        res = C.simulate(
            axis[lo : hi + 1],
            {s: v[lo : hi + 1] for s, v in prices.items()},
            lambda session, _c, _f=fn: _f(session + lo, full_closes),
            contribution=0.0,
            cadence="annual",
            seed=CAPITAL,
            band_pct=float(card.band_pct),
            slippage_bps=0.0,
        )
        print(f"  {label:34} ending {res.final_balance:12,.2f}  rebalances {res.rebalances}")
        return res.final_balance

    # B fills at the NEXT session's open, which is what the engine gets. The last session has no
    # next open, so it reuses its own close -- one session at the very end, and the alternative
    # (dropping it) would shorten the window and change what is being compared.
    next_open = {
        s: [
            opens_by_date[s][axis[i + 1]] if i + 1 < len(axis) else closes_by_date[s][axis[i]]
            for i in range(len(axis))
        ]
        for s in card.universe
    }

    print(f"card   : {card.agent_id}")
    print(f"window : {axis[lo]} .. {axis[hi]}  ({hi - lo + 1} sessions), warmup from {WARM_START}")
    print(f"capital: {CAPITAL:,.2f}  frictions zeroed on both sides\n")
    print(f"  {'run_allocation (engine)':34} ending {engine_end:12,.2f}  rejections {len(engine.rejections)}")
    a = run(full_closes, "simulate @ close[i]   (today)")
    b = run(next_open, "simulate @ open[i+1]  (engine's fill)")

    print()
    for label, val in (("close[i]", a), ("open[i+1]", b)):
        gap = val - engine_end
        print(f"  vs engine, {label:10} : {gap:+10.2f}  ({gap / engine_end * 100:+.4f}%)")

    closed = abs(b - engine_end) < abs(a - engine_end)
    shrink = (1 - abs(b - engine_end) / abs(a - engine_end)) * 100 if a != engine_end else 0.0
    print()
    print(
        f"VERDICT: switching to the engine's fill convention "
        f"{'CLOSES' if closed else 'DOES NOT CLOSE'} the gap "
        f"({shrink:+.1f}% of the divergence removed)."
    )
    if not closed:
        print("         Settlement lag remains the last unexamined suspect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
