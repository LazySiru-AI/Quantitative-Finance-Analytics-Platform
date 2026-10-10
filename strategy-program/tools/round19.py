"""Round 19: how much of the harness/engine gap is settlement?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round19.py

`ROUND-19-PLAN.md` is the pre-registration this executes. Read it first.

Round 16 measured its own cash constraint as worth nothing -- zero underfunded buys across 31 cells --
and its follow-up established why: the constraint it built executes every sell before any buy and lets
the proceeds fund them in the same session, so it is settlement-free by construction and could never
bind. The engine meanwhile rejected 59 orders, all `insufficient_cash`, on the same card with every
friction zeroed. Round 16 wrote down the next step in its own words: *"give `contributions.simulate` a
settlement lag, not just a cash cap, and re-run this comparison."*

`settlement_days` now exists on `simulate`. This is that comparison.

**The design is round 16's `r16_fill_lag.py`, one variable changed.** Same card, same window, same
capital, same zeroed frictions, same engine call -- so the engine number here must reproduce round
16's `86,547.09` exactly, and the harness's settlement-off number must reproduce its `85,942.19`. Both
are asserted rather than eyeballed: if either moves, the instrument changed between the rounds and the
comparison is measuring that instead.

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

WARM_START = dt.date(2022, 1, 3)
START = dt.date(2022, 8, 23)
END = dt.date(2022, 12, 30)
CAPITAL = 100_000.0

#: Round 16's committed figures, asserted as a regression check on the instrument. If either of these
#: fails, something moved between the rounds and every gap reported below is measuring that move.
#: **The engine figure changed on purpose at the D8 fix (2026-08-30) and both values are kept.**
#: Before the fix, `_rebalance_moves` could emit a band-breaching buy with nothing sold to fund it, so
#: the book stopped rebalancing after two episodes and coasted to 86,547.09 on 59 rejections. With the
#: buy funded it rebalances, takes the trade, and ends at 85,746.40 on 3. Replacing the old constant
#: rather than keeping both would erase the only evidence on this path that the instrument moved --
#: and this check exists precisely to make an instrument change impossible to miss.
R16_ENGINE_ENDING_PRE_D8_FIX = 86_547.09
R16_ENGINE_ENDING_POST_D8_FIX = 85_746.40

#: Unchanged, and still asserted: `contributions.simulate` was not touched by the D8 fix, so if the
#: harness figure ever moves, something really is wrong.
R16_HARNESS_ENDING = 85_942.19


def main() -> int:
    settings = get_settings()
    card = AllocationCard.model_validate_json(CARD.read_text(encoding="utf-8"))

    frames = {s: read_frame(s, Interval.DAY, settings=settings) for s in card.universe}
    closes_by_date = {
        s: {d.date(): float(c) for d, c in zip(f["ts"], f["close"], strict=True)} for s, f in frames.items()
    }
    axis = sorted(set.intersection(*(set(m) for m in closes_by_date.values())))
    axis = [d for d in axis if d <= END]
    full_closes = {s: [closes_by_date[s][d] for d in axis] for s in card.universe}
    lo = next(i for i, d in enumerate(axis) if d >= START)
    hi = max(i for i, d in enumerate(axis) if d <= END)

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
    rejections = len(engine.rejections)

    def run(settlement_days: int, cash_constrained: bool) -> C.ContributionResult:
        fn = card_weight_fn(card)
        return C.simulate(
            axis[lo : hi + 1],
            {s: v[lo : hi + 1] for s, v in full_closes.items()},
            lambda session, _c, _f=fn: _f(session + lo, full_closes),
            contribution=0.0,
            cadence="annual",
            seed=CAPITAL,
            band_pct=float(card.band_pct),
            slippage_bps=0.0,
            cash_constrained=cash_constrained,
            settlement_days=settlement_days,
        )

    print(f"card    : {card.agent_id}")
    print(f"window  : {axis[lo]} .. {axis[hi]}  ({hi - lo + 1} sessions)")
    print(f"capital : {CAPITAL:,.2f}   frictions zeroed on both sides")
    print(f"engine  : settlement_days={mandate.settlement_days}  (default_mandate)\n")

    print(f"  {'run_allocation (engine)':44} ending {engine_end:12,.2f}   rejections {rejections}")

    rows: list[tuple[str, float, int, int]] = []
    for label, settle, cc in (
        ("simulate, settlement off (round 16's number)", 0, False),
        ("simulate, cash_constrained only", 0, True),
        ("simulate, cash_constrained + T+1 settlement", 1, True),
        ("simulate, cash_constrained + T+2 settlement", 2, True),
    ):
        r = run(settle, cc)
        rows.append((label, r.final_balance, r.underfunded_buys, r.rebalances))
        print(
            f"  {label:44} ending {r.final_balance:12,.2f}   "
            f"underfunded {r.underfunded_buys:3d}   rebalances {r.rebalances}"
        )

    print("\n  gap to the engine:")
    base_gap = None
    for label, val, _u, _rb in rows:
        gap = val - engine_end
        pct = gap / engine_end * 100
        if base_gap is None:
            base_gap = abs(gap)
            closed = ""
        else:
            closed = f"   ({(1 - abs(gap) / base_gap) * 100:+.1f}% of the original gap closed)"
        print(f"    {label:44} {gap:+10.2f}  ({pct:+.4f}%){closed}")

    # -- the regression check, asserted rather than eyeballed -----------------------------------
    print("\n  regression against round 16's committed figures:")
    harness_ok = abs(rows[0][1] - R16_HARNESS_ENDING) < 0.005
    print(
        f"    {'harness ending, settlement off':36} {rows[0][1]:12,.2f}  "
        f"vs round 16 {R16_HARNESS_ENDING:12,.2f}   {'OK' if harness_ok else 'MISMATCH'}"
    )

    # The engine must match *one* of the two recorded figures, and which one says whether the D8 fix
    # is in. Matching neither means something moved that nobody recorded.
    pre = abs(engine_end - R16_ENGINE_ENDING_PRE_D8_FIX) < 0.005
    post = abs(engine_end - R16_ENGINE_ENDING_POST_D8_FIX) < 0.005
    state = "D8 UNFIXED" if pre else "D8 fixed" if post else "NEITHER -- the instrument moved again"
    print(f"    {'engine ending':36} {engine_end:12,.2f}   -> {state}")

    if not harness_ok:
        print("\n  The harness moved, and the D8 fix does not touch it. Every gap above is suspect.")
        return 1
    if not (pre or post):
        print("\n  The engine matches neither recorded figure. Every gap above is suspect.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
