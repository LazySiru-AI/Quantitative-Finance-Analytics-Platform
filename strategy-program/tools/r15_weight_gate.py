"""Round 15, gate 1: does the bridge compute the ENGINE'S target weights, exactly?

`r15_control.py` compares ending equity between `run_allocation` and `contributions.simulate`, and
that comparison answers two questions at once -- whether `card_weight_fn` reproduces the engine's
weights, and whether two different account models fill the resulting orders the same way. It passes
at 0.66% relative, with 58 `insufficient_cash` rejections on the engine side, so at least part of
that gap has nothing to do with the bridge being right.

`ROUND-15-PLAN.md` §7 asked for agreement "to within rounding". 0.66% is not rounding. This script
isolates the half of the question that can meet that standard: same card, same sessions, no broker
on either side -- `allocation._target_weights` against the bridge's `WeightFn`, session for session,
symbol for symbol.

Run it before trusting any round-15 number:

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/r15_weight_gate.py

A NOTE ON HOW THIS WAS FIRST GOT WRONG, because the failure was convincing.

The first version indexed the bridge on the window's 251 sessions alone. It reported 276 mismatches
out of 753, every gap exactly 0.08 -- precisely the card's own `shift_pct` -- which reads
unmistakably as "the tilt never fires", the exact defect this gate exists to catch. It was the
gate that was wrong. The engine's `_build_signal_table` reads every stored bar, so its `sma(150)` is
already warm at the window's first session, while the bridge had been handed 13 closes and correctly
declined to fire. Comparing a warm indicator against a cold one is a bug in the comparison.

The fix is the `axis` below: both sides get the full common-support history, and the window's
sessions are looked up by position within it. A gate that truncates one side's history and not the
other's will manufacture a failure that looks exactly like the real one.

**Not investment advice.**
"""


from __future__ import annotations

import datetime as dt
import pathlib
from decimal import Decimal

from app.config import get_settings
from app.market.models import Interval
from app.market.store import read_frame
from app.tournament.allocation import (
    AllocationCard,
    _build_signal_table,
    _guard_allocation_card,
    _target_weights,
)
from app.tournament.runner import SessionCalendar
from app.tournament.weightfn import card_weight_fn

CARD = "backend/app/paper/library/allocation/qld-schd-sgov.json"
START, END = dt.date(2022, 1, 3), dt.date(2022, 12, 30)

settings = get_settings()
card = AllocationCard.model_validate_json(pathlib.Path(CARD).read_text(encoding="utf-8"))

calendar = SessionCalendar(start=START, end=END, settings=settings, benchmark="SPY")
sessions = list(calendar)
trees = _guard_allocation_card(card, settings=settings, first_decided_on=sessions[0].decided_on)
tables = [
    _build_signal_table(t, (r.on_symbol,), settings=settings, through=sessions[-1].decided_on)
    for t, r in zip(trees, card.rules, strict=True)
]

# The bridge reads plain float close series keyed by symbol, indexed by session position.
#
# FULL history, not just the window's sessions. The engine's `_build_signal_table` reads every
# stored bar, so at the window's first session its `sma(150)` is already warm from years of prior
# closes. Handing the bridge only the 251 in-window closes and comparing the two compares a warm
# indicator against a cold one -- which is a bug in the comparison, not in the bridge. (It looked
# exactly like a real failure first time round: 276 mismatches, every gap precisely the card's own
# 0.08 shift_pct, i.e. "the tilt never fired".)
#
# So: index every symbol on the same shared session axis, and align the window's sessions into it.
closes: dict[str, list[float]] = {}
by_date_all: dict[str, dict[dt.date, float]] = {}
for sym in card.universe:
    frame = read_frame(sym, Interval.DAY, settings=settings)
    by_date_all[sym] = {d.date(): float(c) for d, c in zip(frame["ts"], frame["close"], strict=True)}

# The axis is the union of dates where every sleeve priced, up to the window end -- the same
# common-support rule the engine's calendar applies.
axis = sorted(set.intersection(*(set(m) for m in by_date_all.values())))
axis = [d for d in axis if d <= sessions[-1].decided_on]
for sym in card.universe:
    closes[sym] = [by_date_all[sym][d] for d in axis]
pos = {d: i for i, d in enumerate(axis)}

fn = card_weight_fn(card)

worst = Decimal(0)
mismatches = 0
first_bad = None
for session in sessions:
    engine = _target_weights(card, tables, session.decided_on)
    bridge = fn(pos[session.decided_on], closes)
    for sym in card.universe:
        gap = abs(Decimal(str(bridge.get(sym, 0.0))) - engine[sym])
        if gap > worst:
            worst = gap
        if gap > Decimal("1e-9"):
            mismatches += 1
            if first_bad is None:
                first_bad = (session.decided_on, sym, engine[sym], bridge.get(sym))

print(f"card            : {card.agent_id}")
print(f"sessions        : {len(sessions)}  ({sessions[0].decided_on} .. {sessions[-1].decided_on})")
print(f"comparisons     : {len(sessions) * len(card.universe)}")
print(f"weight mismatches (>1e-9): {mismatches}")
print(f"worst absolute weight gap: {worst}")
if first_bad:
    print(f"first mismatch  : {first_bad}")
print()
print("PASS -- bridge weights are the engine's weights" if mismatches == 0 else "FAIL")
