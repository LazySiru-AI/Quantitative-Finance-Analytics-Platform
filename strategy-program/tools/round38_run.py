"""Run and score round 38 (the savings real-yield tilt), the bespoke harness `ROUND-38-PLAN.md` §8
specifies because `strategy-program/tools/score.py` is hard-typed to `app.tournament.models.AgentResult`
and cannot score an `AllocationCard`.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round38_run.py

What it does, and why each choice is the one the plan pre-registered:

* **Sets `INVDASH_MACRO_PIN` to round 21's frozen seven-series FRED pin** before any card runs. A
  macro condition in a `TiltRule` fails closed with `MissingPinError` otherwise (a live fetch is
  refused by design); rounds 23/25/30 all read this same pin, so the real-yield cards see the vintage
  those rounds saw rather than a re-fetched one. No engine change; only the environment.
* **Runs every card through `app.tournament.allocation.run_allocation` with
  `app.paperdesk.desk._mandate(Purpose.SAVINGS)`** -- the live savings book's own mandate, not a
  reconstruction, so the numbers are the desk's execution path (the same discipline
  `strategy-program/tools/savings_gap.py` uses for its arm D).
* **Judges on the 5y/10y rungs, reports the 3y rungs and the six bear supplements.** A 10-20 year
  mandate is a long-horizon question; the 1y/6m rungs are too short to say anything about a book whose
  benchmark is 30/70 and are omitted. `MIN_ELIGIBLE_R5_PER_HORIZON = 2` (`windows.py`) is the gate: a
  card whose macro condition fires in fewer than two windows of a horizon has not been measured on
  that horizon and is reported UNMEASURED there, never as a null (`ROUND-38-PLAN.md` §6; the
  RY>2.0 card was pre-declared structurally degenerate for exactly this reason).
* **The benchmark is the 30/70 SPY/AGG blend, not SPY.** `AllocationResult.benchmark_return` is
  hard-coded to SPY in `app.tournament.allocation`; reporting that as "the savings benchmark" would
  compare a defensive book against 100% equity. The blend is recomputed per window via
  `app.paperdesk.benchmarks.price_blend(REGISTRY["30-70-spy-agg"], ...)` -- `PurposeSpec(SAVINGS).benchmark`.
* **Ranks on drawdown and MAR margin vs the control, CAGR reported not ranked.** The savings mandate
  is lowest-drawdown, least-return-accepted; ranking on return would invert the mandate. The reported
  quantity is treatment-minus-control, and a margin is only a finding where the treatment's condition
  actually fired (a window where it never fires is identical to control by construction, contributes a
  mechanical zero, and is excluded from the margin -- reported separately as "fired in k windows").
* **The 21.2pp noise floor is applied as inherited conservatism and is explicitly not load-bearing
  here.** It was measured on a `StrategyCard`'s universe-ordering tiebreak, a mechanism an
  `AllocationCard` does not have (every sleeve is always held, no slot contention). The plan forbids
  claiming a sub-floor margin is real; this tool reports the margin and lets the plan's rule bind.

Writes `data/rounds/r38-2026-09/analysis.json` and prints the tables. **Not investment advice.**
Price-only bars; AGG/GLD/BIL distributions are unmodelled, so every CAGR is understated and the
drawdown column is the trustworthy half (the same caveat `ALLOCATION-FAMILY.md` carries).

Run as a plain script, not ``-m`` -- ``strategy-program`` is not a legal package name.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import statistics
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Round 21's frozen pin, set before any app import that might read it. Rounds 23/25/30 read the same.
_PIN = REPO / "data" / "rounds" / "r21-2026-08" / "macro-pin.json"
os.environ.setdefault("INVDASH_MACRO_PIN", str(_PIN))

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import windows as W  # noqa: E402  (path-based import, same precedent as disjoint_field.py)

from app.config import get_settings  # noqa: E402
from app.paperdesk.benchmarks import REGISTRY, price_blend  # noqa: E402
from app.paperdesk.desk import _mandate as desk_mandate  # noqa: E402
from app.tournament.allocation import AllocationCard, run_allocation  # noqa: E402
from app.tournament.purposes import Purpose  # noqa: E402

CARDS_DIR = REPO / "data" / "rounds" / "r38-2026-09" / "cards"
CONTROL_ID = "r38-control"
TRADING_DAYS = 252
BENCHMARK_BLEND = "30-70-spy-agg"

#: The judged set (5y + 10y), the reported-but-not-ranked set (3y), and the bear supplements.
RANK_TAGS = ("h10y-1", "h10y-2", "h5y-1", "h5y-2", "h5y-3")
REPORT_TAGS = ("h3y-1", "h3y-2", "h3y-3", "h3y-4")
BEAR_TAGS = ("b6m-1", "b6m-2", "b6m-3", "b1y-1", "b1y-2", "b1y-3")
ALL_TAGS = RANK_TAGS + REPORT_TAGS + BEAR_TAGS


def window_bounds(tag: str) -> tuple[dt.date, dt.date]:
    start, end, _desc = W.WINDOWS[tag]
    return start, end


def cagr_of(result: object, capital: float) -> float | None:
    sessions = getattr(result, "sessions", 0)
    ending = getattr(result, "ending_equity", None)
    if not sessions or ending is None:
        return None
    return (float(ending) / capital) ** (TRADING_DAYS / sessions) - 1


def run_card_windows(card: AllocationCard, settings, mandate, capital: float) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for tag in ALL_TAGS:
        start, end = window_bounds(tag)
        try:
            res = run_allocation(card, settings=settings, mandate=mandate, start=start, end=end)
        except Exception as exc:  # a leg without history, or a window too short to price
            out[tag] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
            continue
        trades = len(getattr(res, "trades", ()) or ())
        out[tag] = {
            "ok": True,
            "sessions": res.sessions,
            "cagr": cagr_of(res, capital),
            "max_drawdown": float(res.max_drawdown),
            "total_return": float(res.total_return),
            "volatility": float(res.volatility) if res.volatility is not None else None,
            "trades": trades,
        }
    return out


def mar(cagr: float | None, dd: float) -> float | None:
    if cagr is None or not dd:
        return None
    return cagr / abs(dd)


def median_or_none(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def main() -> int:
    settings = get_settings()
    mandate = desk_mandate(Purpose.SAVINGS)
    capital = float(mandate.starting_cash)

    cards = {}
    for path in sorted(CARDS_DIR.glob("*.json")):
        card = AllocationCard.model_validate_json(path.read_text(encoding="utf-8"))
        cards[card.agent_id] = card
    if CONTROL_ID not in cards:
        print(f"FATAL: no {CONTROL_ID} in {CARDS_DIR}")
        return 1

    # Print the pin path relative to the repo, never absolute -- an absolute path carries the
    # Windows username and trips the check-no-pii pre-commit gate when this output is committed.
    pin_shown = os.environ["INVDASH_MACRO_PIN"]
    try:
        pin_shown = str(pathlib.Path(pin_shown).resolve().relative_to(REPO).as_posix())
    except ValueError:
        pin_shown = pathlib.Path(pin_shown).name
    print(f"macro pin : {pin_shown}")
    print(f"mandate   : SAVINGS, starting_cash ${capital:,.0f}")
    print(f"benchmark : {BENCHMARK_BLEND} (30/70 SPY/AGG, recomputed per window)")
    print(f"windows   : rank {RANK_TAGS} | report {REPORT_TAGS} | bear {BEAR_TAGS}\n")

    # Benchmark blend per window (total return), the honest yardstick for a defensive book.
    bench: dict[str, float | None] = {}
    for tag in ALL_TAGS:
        start, end = window_bounds(tag)
        try:
            b = price_blend(REGISTRY[BENCHMARK_BLEND], start=start, end=end, settings=settings)
            bench[tag] = float(b) if b is not None else None
        except Exception as exc:
            bench[tag] = None
            print(f"  benchmark unpriceable in {tag}: {type(exc).__name__}")

    results = {aid: run_card_windows(c, settings, mandate, capital) for aid, c in cards.items()}
    control = results[CONTROL_ID]

    # Per-card table over the judged rungs.
    print(f"{'card':22} {'horizon':8} " + " ".join(f"{t:>9}" for t in RANK_TAGS))
    for aid in sorted(results):
        row_dd, row_mar = [], []
        for t in RANK_TAGS:
            r = results[aid][t]
            if r.get("ok"):
                row_dd.append(f"{r['max_drawdown']*100:>8.1f}%")
                row_mar.append(mar(r["cagr"], r["max_drawdown"]))
            else:
                row_dd.append(f"{'n/a':>9}")
                row_mar.append(None)
        print(f"{aid:22} {'maxDD':8} " + " ".join(row_dd))

    # Treatment minus control, on the rungs where the treatment's condition actually fired.
    analysis: dict[str, object] = {
        "round": 38, "capital": capital, "benchmark_blend": BENCHMARK_BLEND,
        "rank_tags": list(RANK_TAGS), "bench_return": bench, "cards": results, "vs_control": {},
    }
    print("\n== treatment minus control (drawdown & MAR), judged rungs ==")
    print(f"{'card':22} {'fired':>6} {'dd_margin':>10} {'mar_margin':>11} {'cagr_margin':>12} verdict")
    for aid in sorted(results):
        if aid == CONTROL_ID:
            continue
        fired = 0
        dd_margins, mar_margins, cagr_margins = [], [], []
        for t in RANK_TAGS:
            r, c = results[aid][t], control[t]
            if not (r.get("ok") and c.get("ok")):
                continue
            differs = r["trades"] != c["trades"] or abs(r["total_return"] - c["total_return"]) > 1e-9
            if not differs:
                continue  # condition never fired here: identical to control by construction
            fired += 1
            dd_margins.append((r["max_drawdown"] - c["max_drawdown"]) * 100)  # +ve = shallower DD
            rm, cm = mar(r["cagr"], r["max_drawdown"]), mar(c["cagr"], c["max_drawdown"])
            if rm is not None and cm is not None:
                mar_margins.append(rm - cm)
            if r["cagr"] is not None and c["cagr"] is not None:
                cagr_margins.append((r["cagr"] - c["cagr"]) * 100)
        dd_m = median_or_none(dd_margins)
        mar_m = median_or_none(mar_margins)
        cagr_m = median_or_none(cagr_margins)
        verdict = "UNMEASURED (fired <2 rungs)" if fired < W.MIN_ELIGIBLE_R5_PER_HORIZON else "measured"
        analysis["vs_control"][aid] = {  # type: ignore[index]
            "fired_rungs": fired, "dd_margin_pp": dd_m, "mar_margin": mar_m,
            "cagr_margin_pp": cagr_m, "verdict": verdict,
        }
        s_dd = "n/a" if dd_m is None else f"{dd_m:>+9.2f}"
        s_mar = "n/a" if mar_m is None else f"{mar_m:>+11.3f}"
        s_cagr = "n/a" if cagr_m is None else f"{cagr_m:>+11.2f}"
        print(f"{aid:22} {fired:>6} {s_dd:>10} {s_mar:>11} {s_cagr:>12} {verdict}")

    # Bear-window coverage: the plan pre-declared macro cards can say little in a crisis.
    print("\n== bear-window firing (each macro card's condition, treatment vs control) ==")
    for aid in sorted(results):
        if aid == CONTROL_ID:
            continue
        fired = sum(
            1 for t in BEAR_TAGS
            if results[aid][t].get("ok") and control[t].get("ok")
            and (results[aid][t]["trades"] != control[t]["trades"]
                 or abs(results[aid][t]["total_return"] - control[t]["total_return"]) > 1e-9)
        )
        print(f"  {aid:22} fired in {fired}/{len(BEAR_TAGS)} bear windows")

    dest = REPO / "data" / "rounds" / "r38-2026-09" / "analysis.json"
    dest.write_text(json.dumps(analysis, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nwrote {dest.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
