"""Round 16: what the cash constraint is worth.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round16.py

`ROUND-16-PLAN.md` is the pre-registration this executes. Read it first.

Every round-15 contribution cell is run twice -- `cash_constrained=False` and `True` -- over the
same windows, cards and drip sizes. One variable, paired.

The unconstrained side is also the regression check, and a stronger one than any unit test: it must
reproduce round 15's *committed* figures on real data, to the last digit. If it does not, the cash
constraint leaked into the default path and every comparison below is measuring the leak.

The P1 re-test re-runs round 15's headline -- the monthly drip against an equivalent lump sum -- with
the constraint on, because that is the finding most at risk. The drip's only win was in `h5y-3`, the
bear-market window, which is exactly where a real account most often cannot fund the rebalance it is
being credited for.

**Not investment advice.**
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import contributions as C
import windows as W

from app.config import get_settings
from app.market.models import Interval
from app.market.store import read_frame
from app.tournament.allocation import AllocationCard
from app.tournament.ladder import LadderCard
from app.tournament.purposes import PURPOSE_SPECS, FundingShape, Purpose
from app.tournament.weightfn import UnsupportedConditionError, card_weight_fn

REPO = pathlib.Path(__file__).resolve().parents[2]
R15 = REPO / "data" / "rounds" / "r15-2026-08"
OUT = REPO / "data" / "rounds" / "r16-2026-08"
LIBRARY = REPO / "backend" / "app" / "paper" / "library"

_CADENCE = {
    FundingShape.MONTHLY_CONTRIBUTION: "monthly",
    FundingShape.ANNUAL_CONTRIBUTION: "annual",
}


def load_cards() -> dict[str, AllocationCard | LadderCard]:
    out: dict[str, AllocationCard | LadderCard] = {}
    for p in sorted((R15 / "cards").glob("*.json")):
        c = AllocationCard.model_validate_json(p.read_text(encoding="utf-8"))
        out[c.agent_id] = c
    for p in sorted((LIBRARY / "allocation").glob("*.json")):
        c = AllocationCard.model_validate_json(p.read_text(encoding="utf-8"))
        out[c.agent_id] = c
    for p in sorted((LIBRARY / "ladder").glob("*.json")):
        lc = LadderCard.model_validate_json(p.read_text(encoding="utf-8"))
        out[lc.agent_id] = lc
    return out


def closes_for(card: Any, settings: Any, through: dt.date) -> tuple[list[dt.date], dict[str, list[float]]]:
    """Full common-support history. A ladder's untraded `signal_symbol` is fetched but never weighted."""
    needed = card.universe
    if isinstance(card, LadderCard) and card.signal_symbol not in needed:
        needed = (*needed, card.signal_symbol)
    per: dict[str, dict[dt.date, float]] = {}
    for sym in needed:
        f = read_frame(sym, Interval.DAY, settings=settings)
        per[sym] = {d.date(): float(c) for d, c in zip(f["ts"], f["close"], strict=True)}
    axis = sorted(set.intersection(*(set(m) for m in per.values())))
    axis = [d for d in axis if d <= through]
    return axis, {s: [per[s][d] for d in axis] for s in needed}


def main() -> int:
    settings = get_settings()
    cards = load_cards()
    rows: list[dict[str, Any]] = []
    regressions: list[str] = []

    # Skips two things: `.skipped.json` markers (cards the bridge refused, which have no figures),
    # and any `*-CONTAMINATED-INVALID` tree. The latter holds round 15's original
    # `ladder-sso-vig-bnd` records, kept as evidence of the stateful-closure leak this round found --
    # the same convention round 11 used for its own retired instrument. Globbing them back in would
    # compare the corrected run against the very numbers it corrected.
    stored = sorted(
        p
        for p in (R15 / "contributions").rglob("*.json")
        if not p.name.endswith(".skipped.json")
        and not any("CONTAMINATED" in part for part in p.parts)
    )
    print(f"{len(stored)} round-15 contribution cells to re-run, both ways\n", flush=True)

    for p in stored:
        rec = json.loads(p.read_text(encoding="utf-8"))
        aid, tag = rec["agent_id"], rec["window"]
        card = cards[aid]
        purpose = Purpose(rec["purpose"])
        spec = PURPOSE_SPECS[purpose]
        contribution = float(rec["contribution"])
        start, end, _ = W.ALL_WINDOWS[tag]

        try:
            card_weight_fn(card)  # probe: raises here rather than mid-run for an unsupported tilt
        except UnsupportedConditionError:
            continue

        axis, closes = closes_for(card, settings, end)
        lo = next(i for i, d in enumerate(axis) if d >= start)
        hi = max(i for i, d in enumerate(axis) if d <= end)
        dates = axis[lo : hi + 1]
        sub = {s: v[lo : hi + 1] for s, v in closes.items()}

        # A FRESH closure per simulate call. `card_weight_fn` for a LadderCard returns a *stateful*
        # closure -- it carries armed depth and the cycle-starting high across sessions, because the
        # ladder is a state machine. Reusing one across two runs makes the second inherit the first's
        # state; measured, that moved this card's h5y-2 CAGR from 11.63% to 26.52%. An AllocationCard
        # closure is stateless and unaffected, which is why only the ladder ever showed it.
        def make_wf(_card: Any = card, _lo: int = lo, _cl: Any = closes) -> Any:
            inner = card_weight_fn(_card)
            return lambda session, _c, _inner=inner, _o=_lo, _s=_cl: _inner(session + _o, _s)

        common = dict(
            contribution=contribution,
            cadence=_CADENCE[spec.funding_shape],
            seed=float(spec.seed),
            band_pct=float(card.band_pct) if isinstance(card, AllocationCard) else 0.05,
            slippage_bps=0.0,
        )
        free = C.simulate(dates, sub, make_wf(), cash_constrained=False, **common)
        held = C.simulate(dates, sub, make_wf(), cash_constrained=True, **common)

        # The unconstrained path must reproduce round 15's committed figure exactly.
        old = rec["irr"]
        if old is not None and free.irr is not None and abs(free.irr - old) > 1e-12:
            regressions.append(f"{aid} {tag} c{int(contribution)}: r15 {old:.10f} -> now {free.irr:.10f}")

        rows.append(
            {
                "agent_id": aid,
                "purpose": rec["purpose"],
                "window": tag,
                "contribution": contribution,
                "irr_unconstrained": free.irr,
                "irr_constrained": held.irr,
                "irr_drag_pp": None if (free.irr is None or held.irr is None) else (held.irr - free.irr) * 100,
                "cagr_unconstrained": free.time_weighted_cagr,
                "cagr_constrained": held.time_weighted_cagr,
                "cagr_drag_pp": (held.time_weighted_cagr - free.time_weighted_cagr) * 100,
                "underfunded_buys": held.underfunded_buys,
                "underfunded_shortfall": held.underfunded_shortfall,
                "rebalances_unconstrained": free.rebalances,
                "rebalances_constrained": held.rebalances,
                "cash_constraint_modelled": True,
            }
        )
        d = rows[-1]["cagr_drag_pp"]
        print(
            f"  {aid:30} {tag:8} c{int(contribution):<5} "
            f"cagr {free.time_weighted_cagr * 100:6.2f}% -> {held.time_weighted_cagr * 100:6.2f}%  "
            f"drag {d:+6.2f}pp  underfunded {held.underfunded_buys:4d} (${held.underfunded_shortfall:,.0f})",
            flush=True,
        )

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "paired.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    print()
    if regressions:
        print(f"!! {len(regressions)} REGRESSIONS -- the unconstrained path no longer reproduces round 15:")
        for r in regressions:
            print("   ", r)
    else:
        print(f"regression check: all {len(rows)} unconstrained cells reproduce round 15 exactly")

    drags = [r["cagr_drag_pp"] for r in rows]
    worse = sum(1 for d in drags if d < -1e-9)
    better = sum(1 for d in drags if d > 1e-9)
    print()
    print(f"P1(bias is one-directional): {worse} worse, {better} better, {len(drags) - worse - better} unchanged")
    print(f"  mean drag   : {sum(drags) / len(drags):+.3f} pp")
    print(f"  worst drag  : {min(drags):+.3f} pp")
    by_card: dict[str, float] = {}
    for r in rows:
        by_card[r["agent_id"]] = min(by_card.get(r["agent_id"], 0.0), r["cagr_drag_pp"])
    print("  worst drag per card:")
    for aid, d in sorted(by_card.items(), key=lambda x: x[1]):
        print(f"    {aid:32} {d:+7.3f} pp")
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
