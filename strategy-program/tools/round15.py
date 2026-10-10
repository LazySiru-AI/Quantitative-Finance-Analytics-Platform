"""Round 15: runs the three purpose arms and writes their records.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round15.py [--arm trading|savings|roth|all]

`ROUND-15-PLAN.md` is the pre-registration this executes. Read it first; nothing here overrides it.

TWO ARMS, TWO ENGINES, AND WHY THEY DO NOT SHARE A RESULTS TREE
---------------------------------------------------------------
The trading arm is a lump sum, so it runs through `app.tournament.allocation.run_allocation` and
writes an `AllocationResult` per (card, window) into

    data/rounds/r15-2026-08/results/<window>/runs/<agent_id>.json

which is the published interface `/api/competition` already reads, and which
`results.parse_scored_run` now understands.

The savings and Roth arms are contribution-funded, and there is no engine in this repository that
runs a *card* against a deposit stream. They go through `contributions.simulate` via the
`card_weight_fn` bridge, and their output is a `ContributionResult` -- IRR and time-weighted CAGR,
not `adjusted_excess`. That is a different measurement, not a variant of the same one, so it is
written to a **separate** tree:

    data/rounds/r15-2026-08/contributions/<arm>/<window>/<agent_id>.json

Putting an IRR into the results tree would let it be read as though it were rankable against a
lump-sum `adjusted_excess`. `ROTH-CANDIDATES.md` is blunt that this is a category error rather than
a rounding one, and the cheapest way to never make it is to keep the two on separate shelves.

THE CASH-CONSTRAINT ASYMMETRY -- read before believing any contribution-funded number
------------------------------------------------------------------------------------
`r15_weight_gate.py` proves the bridge computes the engine's target weights exactly: 0 mismatches
across 753 comparisons, worst gap 0. So the two paths agree about *what to hold*.

They do not agree about what happens when you cannot afford it. `run_allocation` drives a real
`PaperBroker` cash account and will reject a buy it cannot fund -- 58 `insufficient_cash`
rejections in `r15_control.py`'s own window, as QLD fell and SCHD ran out of room to fund top-ups.
`contributions.simulate` has no cash constraint at all and always rebalances to target.

So every savings and Roth figure this script produces is **systematically optimistic** relative to
what the same card would do in a real account, and most optimistic exactly where it matters: a
deep drawdown in a leveraged sleeve, which is when rebalancing to target is both most valuable and
least affordable. This is a property of the harness, not a bug, and it is not corrected here. It is
recorded on every contribution-funded record as `cash_constraint_modelled: false` so the caveat
travels with the number instead of living only in this docstring.

WHAT WILL NOT RUN, AND WHY THAT IS REPORTED RATHER THAN WORKED AROUND
---------------------------------------------------------------------
`card_weight_fn` raises `UnsupportedConditionError` for any tilt needing a bar field the harness
does not carry. `contributions.simulate` passes closes only, so `atr(14)` -- which needs high and
low -- cannot be evaluated. `spy-schd-agg-gld-bil-atr-tilt` is a savings card whose only two rules
are ATR-gated, so it cannot run in the savings arm.

It is skipped and recorded as skipped. The alternative -- letting the tilts silently never fire --
would score it as its own static twin and quietly answer the round's central question ("do the
tilts earn their complexity?") with a number that contains no tilts at all.

**Not investment advice.**
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import pathlib
import sys
import traceback
from decimal import Decimal
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import contributions as C
import windows as W

from app.config import get_settings
from app.market.models import Interval
from app.market.store import read_frame
from app.paper.mandate import default_mandate
from app.tournament.allocation import AllocationCard, run_allocation
from app.tournament.ladder import LadderCard, run_ladder_card
from app.tournament.purposes import PURPOSE_SPECS, FundingShape, Purpose
from app.tournament.weightfn import UnsupportedConditionError, card_weight_fn

REPO = pathlib.Path(__file__).resolve().parents[2]
ROUND = REPO / "data" / "rounds" / "r15-2026-08"
CARDS_DIR = ROUND / "cards"
LIBRARY = REPO / "backend" / "app" / "paper" / "library"

#: Contribution-funded arms need a window long enough for a deposit stream to matter -- a monthly
#: drip over 90 sessions is a lump sum with extra steps. Pre-registered in ROUND-15-PLAN.md §5 as
#: "at least three years", which selects exactly these five from the matrix.
LONG_WINDOWS = ("h10y-1", "h10y-2", "h5y-1", "h5y-2", "h5y-3")

#: `FundingShape` -> `contributions.Cadence`. Explicit rather than `.value.split("_")[0]` so that a
#: fourth funding shape added later fails loudly here instead of quietly defaulting to annual and
#: reporting a monthly account's numbers under a yearly deposit schedule.
_CADENCE: dict[FundingShape, str] = {
    FundingShape.MONTHLY_CONTRIBUTION: "monthly",
    FundingShape.ANNUAL_CONTRIBUTION: "annual",
}


def _load_cards() -> list[AllocationCard | LadderCard]:
    """Round 15's field: the five new cards, plus the four already-frozen ones entering as-is."""
    out: list[AllocationCard | LadderCard] = []
    for p in sorted(CARDS_DIR.glob("*.json")):
        out.append(AllocationCard.model_validate_json(p.read_text(encoding="utf-8")))
    for p in sorted((LIBRARY / "allocation").glob("*.json")):
        out.append(AllocationCard.model_validate_json(p.read_text(encoding="utf-8")))
    for p in sorted((LIBRARY / "ladder").glob("*.json")):
        out.append(LadderCard.model_validate_json(p.read_text(encoding="utf-8")))
    return out


def _closes(symbols: tuple[str, ...], settings: Any, through: dt.date) -> tuple[list[dt.date], dict[str, list[float]]]:
    """Common-support close series across `symbols`, oldest first, up to and including `through`.

    Full history, never just the window: an `sma(150)` read from a window's own first session is a
    cold indicator, and `r15_weight_gate.py`'s docstring records how convincingly that fails.
    """
    per: dict[str, dict[dt.date, float]] = {}
    for sym in symbols:
        frame = read_frame(sym, Interval.DAY, settings=settings)
        per[sym] = {d.date(): float(c) for d, c in zip(frame["ts"], frame["close"], strict=True)}
    axis = sorted(set.intersection(*(set(m) for m in per.values())))
    axis = [d for d in axis if d <= through]
    return axis, {sym: [per[sym][d] for d in axis] for sym in symbols}


def _fresh_wf(card: AllocationCard | LadderCard, lo: int, closes: dict[str, list[float]]) -> Any:
    """A new `WeightFn` bound to the full-history series, offset into the window by `lo`.

    Built per cell rather than per card: see the call site for the state-leak this prevents.
    """
    inner = card_weight_fn(card)
    return lambda i, _c: inner(i + lo, closes)


def _write(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, default=str)
    path.write_text(text, encoding="utf-8")


def run_trading(cards: list[AllocationCard | LadderCard], settings: Any) -> list[str]:
    """Lump sum through the real engine, over the main regime windows."""
    log: list[str] = []
    seed = PURPOSE_SPECS[Purpose.TRADING].seed
    mandate = dataclasses.replace(
        default_mandate(starting_cash=Decimal(seed)), max_single_name_weight=Decimal(1)
    )
    field = [c for c in cards if c.purpose is Purpose.TRADING]
    for card in field:
        for tag, (start, end, _desc) in W.MAIN_WINDOWS.items():
            out = ROUND / "results" / tag / "runs" / f"{card.agent_id}.json"
            if out.exists():
                log.append(f"SKIP  {card.agent_id:32} {tag:14} already run")
                continue
            try:
                if isinstance(card, LadderCard):
                    res = run_ladder_card(card, settings=settings, mandate=mandate, start=start, end=end)
                else:
                    res = run_allocation(card, settings=settings, mandate=mandate, start=start, end=end)
                _write(out, res.model_dump_json(indent=2))
                log.append(
                    f"OK    {card.agent_id:32} {tag:14} "
                    f"return={float(res.total_return) * 100:7.2f}%  dd={float(res.max_drawdown) * 100:7.2f}%"
                )
            except Exception as exc:
                log.append(f"FAIL  {card.agent_id:32} {tag:14} {type(exc).__name__}: {exc}")
                traceback.print_exc(limit=2)
    return log


def run_contribution_arm(
    cards: list[AllocationCard | LadderCard], settings: Any, purpose: Purpose, arm: str
) -> list[str]:
    """Deposit stream through the bridge, over the long windows only."""
    log: list[str] = []
    spec = PURPOSE_SPECS[purpose]
    variants: list[Decimal] = [spec.contribution, *spec.contribution_variants]
    field = [c for c in cards if c.purpose is purpose]

    for card in field:
        try:
            card_weight_fn(card)  # probe only; a fresh closure is built per cell below
        except UnsupportedConditionError as exc:
            log.append(f"SKIP  {card.agent_id:32} {'(all windows)':14} unsupported condition: {exc}")
            _write(
                ROUND / "contributions" / arm / f"{card.agent_id}.skipped.json",
                {
                    "agent_id": card.agent_id,
                    "purpose": purpose.value,
                    "skipped": True,
                    "reason": f"{type(exc).__name__}: {exc}",
                    "note": (
                        "Not a failure of the strategy. The contribution harness passes closes "
                        "only, so a tilt gated on a bar field it does not carry cannot be "
                        "evaluated. Running it anyway would silently never fire the tilt and "
                        "score this card as its own static twin."
                    ),
                },
            )
            continue

        for tag in LONG_WINDOWS:
            start, end, _desc = W.ALL_WINDOWS[tag]
            for contribution in variants:
                label = f"{tag}-c{int(contribution)}"
                out = ROUND / "contributions" / arm / label / f"{card.agent_id}.json"
                if out.exists():
                    log.append(f"SKIP  {card.agent_id:32} {label:16} already run")
                    continue
                try:
                    # A ladder's `universe` deliberately omits `signal_symbol` -- SPY is read for
                    # the drawdown state machine and never traded, so it is not a sleeve. The
                    # bridge still needs its closes to compute that signal, so fetch it alongside
                    # the traded sleeves; `card_weight_fn` never returns a weight for it.
                    needed = card.universe
                    if isinstance(card, LadderCard) and card.signal_symbol not in needed:
                        needed = (*needed, card.signal_symbol)
                    axis, closes = _closes(needed, settings, through=end)
                    # A card whose youngest sleeve postdates the window has no overlap at all. That
                    # is an eligibility fact about the card, not a run failure -- SGOV's bars begin
                    # 2020-06-01, so `qld-schd-sgov` simply does not exist during h5y-1 (2013-2018).
                    # Recording it as FAIL would file a data-coverage limit as a broken strategy.
                    lo = next((i for i, d in enumerate(axis) if d >= start), None)
                    hi = max((i for i, d in enumerate(axis) if d <= end), default=None)
                    if lo is None or hi is None or hi <= lo:
                        log.append(f"SKIP  {card.agent_id:32} {label:16} no bars inside this window")
                        continue
                    if hi - lo < C.TRADING_DAYS * 3:
                        log.append(
                            f"SKIP  {card.agent_id:32} {label:16} "
                            f"only {hi - lo} sessions of common support, under the 3-year minimum"
                        )
                        continue
                    res = C.simulate(
                        axis[lo : hi + 1],
                        {s: v[lo : hi + 1] for s, v in closes.items()},
                        # Deliberately ignores `cl` -- the windowed slice `simulate` hands back --
                        # and reads the FULL history instead, offsetting the index by `_lo`. An
                        # `sma(150)` evaluated from a window's own first session is a cold
                        # indicator that never fires; `r15_weight_gate.py`'s docstring records how
                        # convincingly that failure reads as a broken bridge when it is not.
                        #
                        # Every capture is bound as a default argument, `_cl` included: `closes` is
                        # rebound on the next loop iteration, so capturing it by reference would
                        # have every window silently price against the last window's series.
                        # A FRESH closure per cell, never one reused across windows. A LadderCard's
                        # WeightFn is a state machine carrying armed depth and the cycle-starting
                        # high; one closure shared across windows makes each window inherit the
                        # previous one's state. That defect contaminated this round's original
                        # `ladder-sso-vig-bnd` figures -- see r16's SELECTION.md and the dated
                        # correction in this round's own record. AllocationCard closures are
                        # stateless, which is why every allocation cell reproduced exactly.
                        _fresh_wf(card, lo, closes),
                        contribution=float(contribution),
                        cadence=_CADENCE[spec.funding_shape],
                        band_pct=float(card.band_pct) if isinstance(card, AllocationCard) else 0.05,
                        seed=float(spec.seed),
                        slippage_bps=0.0,
                    )
                    _write(
                        out,
                        {
                            "agent_id": card.agent_id,
                            "purpose": purpose.value,
                            "window": tag,
                            "start": axis[lo],
                            "end": axis[hi],
                            "sessions": hi - lo + 1,
                            "seed": str(spec.seed),
                            "contribution": str(contribution),
                            "funding_shape": spec.funding_shape.value,
                            "irr": res.irr,
                            "time_weighted_cagr": res.time_weighted_cagr,
                            "max_drawdown": res.max_drawdown,
                            "volatility": res.volatility,
                            "mar": res.mar,
                            "multiple": res.multiple,
                            "profit": res.profit,
                            # Travels with the number, deliberately -- see this module's docstring.
                            "cash_constraint_modelled": False,
                        },
                    )
                    irr = "n/a" if res.irr is None else f"{res.irr * 100:6.2f}%"
                    log.append(
                        f"OK    {card.agent_id:32} {label:16} irr={irr}  cagr={res.time_weighted_cagr * 100:6.2f}%"
                    )
                except Exception as exc:
                    log.append(f"FAIL  {card.agent_id:32} {label:16} {type(exc).__name__}: {exc}")
                    traceback.print_exc(limit=2)
    return log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="all", choices=["trading", "savings", "roth", "all"])
    args = ap.parse_args()

    settings = get_settings()
    cards = _load_cards()
    print(f"field: {len(cards)} cards")
    for c in cards:
        print(f"  {c.agent_id:34} {c.purpose.value:8} {c.universe}")
    print()

    log: list[str] = []
    if args.arm in ("trading", "all"):
        print("== trading arm (lump sum, main windows) ==")
        log += run_trading(cards, settings)
    if args.arm in ("savings", "all"):
        print("== savings arm (monthly drip, long windows) ==")
        log += run_contribution_arm(cards, settings, Purpose.SAVINGS, "savings")
    if args.arm in ("roth", "all"):
        print("== roth arm (annual drip, long windows) ==")
        log += run_contribution_arm(cards, settings, Purpose.ROTH, "roth")

    print()
    for line in log:
        print(line)
    _write(ROUND / "run.txt", "\n".join(log) + "\n")

    failures = [line for line in log if line.startswith("FAIL")]
    print(f"\n{len(log)} cells, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
