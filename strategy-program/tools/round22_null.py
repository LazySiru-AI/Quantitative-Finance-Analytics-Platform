"""Round 22's pre-registered null: 200 circular shifts of the gate mask, `ma-crossover`, 3 windows.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round22_null.py --shifts 200

`ROUND-22-PLAN.md` §4 is the pre-registration. Read it first.

**What is randomised, and what is not.** A circular shift preserves the mask's on/off proportion and
its run-length distribution exactly and moves only its *phase* relative to price. That is the null
this round tests against: "a regime-shaped filter carrying the real curve's own statistics, but no
informational relationship to this price series." An i.i.d. reshuffle would destroy the run lengths --
the curve stays inverted for months, it does not flip daily -- and produce a null far tighter than the
truth, which would make almost any marginal look significant.

**How a shifted mask reaches a card.** It cannot, directly: the DSL binds `macro(T10Y2Y)` to whatever
the pin holds. Each replicate therefore substitutes a synthetic `T10Y2Y` whose observations are +1 on
the sessions the shifted mask is true and -1 where it is false, so `macro(T10Y2Y) > 0` reproduces the
shifted mask exactly *after* release-date binding. The entire real pipeline -- binding, guard, engine
-- runs unchanged and only the data underneath it moves.

**The substitution is in memory, not on disk.** `app.rules.macro_pin.active_pin` is patched for the
duration of the sweep rather than writing 200 four-megabyte pins. Pinning exists to make *the round*
reproducible; a null replicate is disposable by construction, and its reproducibility comes from the
seeded, deterministic shift schedule below rather than from a file. The release-lag join it is being
measured through is the real one either way.

**Not investment advice.**
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import pathlib
import statistics
from decimal import Decimal

from app.config import get_settings
from app.market.macro_models import MacroPoint, MacroSeries, MacroSource, MacroUnit
from app.paper.paperbroker import load_mandate
from app.rules import macro_pin
from app.rules.macro_binding import RELEASE_LAG
from app.rules.macro_pin import read_pin
from app.rules.nodes import MacroField
from app.tournament.models import StrategyCard
from app.tournament.runner import run_card

REPO = pathlib.Path(__file__).resolve().parents[2]

PIN = REPO / "data" / "rounds" / "r21-2026-08" / "macro-pin.json"
CARDS = REPO / "data" / "rounds" / "r21-2026-08" / "cards"
RESULTS = REPO / "data" / "rounds" / "r22-2026-08" / "results"
OUT = REPO / "data" / "rounds" / "r22-2026-08" / "null.json"

FORM = "ma-crossover"  # §4: one form at full depth, not four shallowly
WINDOWS = (
    ("inv-2000", dt.date(1999, 12, 2), dt.date(2001, 6, 29)),
    ("inv-2006", dt.date(2006, 3, 1), dt.date(2007, 12, 31)),
    ("inv-2022", dt.date(2022, 1, 3), dt.date(2024, 12, 31)),
)


def adjusted_excess(result: object) -> float:
    """`total_return - capital_exposure * benchmark_return`, PROTOCOL §4's ranking quantity."""
    tr = float(result.total_return)  # type: ignore[attr-defined]
    ce = float(result.capital_exposure or 0.0)  # type: ignore[attr-defined]
    br = float(result.benchmark_return)  # type: ignore[attr-defined]
    return tr - ce * br


def observed_mask() -> list[tuple[dt.date, bool]]:
    series = read_pin(PIN)[MacroField.T10Y2Y]
    return [(p.date, p.value > 0) for p in series.points if p.value is not None]


def shifted(mask: list[tuple[dt.date, bool]], offset: int) -> dict[MacroField, MacroSeries]:
    n = len(mask)
    points = [
        MacroPoint(date=date, value=1.0 if mask[(i + offset) % n][1] else -1.0)
        for i, (date, _) in enumerate(mask)
    ]
    return {
        MacroField.T10Y2Y: MacroSeries(
            series_id="T10Y2Y",
            title="T10Y2Y (circular-shift null replicate)",
            unit=MacroUnit.PERCENT_SPREAD,
            source=MacroSource.FRED,
            points=points,
        )
    }


def baseline() -> dict[str, float]:
    """The gate-off cell's adjusted excess per window, read from the round's committed runs.

    Constant across replicates -- the mask does not touch it -- so it is read once rather than
    recomputed 200 times.
    """
    out: dict[str, float] = {}
    for tag, _, _ in WINDOWS:
        d = json.loads((RESULTS / tag / "runs" / f"r1-r21-{FORM}-off.json").read_text())
        out[tag] = float(d["total_return"]) - float(d["capital_exposure"]) * float(d["benchmark_return"])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shifts", type=int, default=200)
    args = ap.parse_args(argv)

    settings = get_settings()
    mandate = dataclasses.replace(
        load_mandate(REPO / "uat" / "personas" / "pro-investor-01.setup.json"),
        max_single_name_weight=Decimal(1),
    )
    card = StrategyCard.model_validate_json((CARDS / f"r21-{FORM}-on.json").read_text())
    mask = observed_mask()
    base = baseline()

    # Deterministic, evenly-spaced offsets over the whole mask -- reproducible without a RNG, and
    # spread rather than clustered so consecutive replicates are not near-duplicates of each other.
    step = max(1, len(mask) // args.shifts)
    offsets = [((i * step) + 1) % len(mask) for i in range(args.shifts)]

    dist: dict[str, list[float]] = {tag: [] for tag, _, _ in WINDOWS}
    blocked: dict[str, list[float]] = {tag: [] for tag, _, _ in WINDOWS}
    lag = RELEASE_LAG[MacroField.T10Y2Y]
    n_mask = len(mask)
    for i, off in enumerate(offsets, 1):
        series = shifted(mask, off)
        macro_pin.clear_pin_cache()
        original = macro_pin.active_pin
        macro_pin.active_pin = lambda path=None, _s=series: _s  # type: ignore[assignment]
        try:
            for tag, start, end in WINDOWS:
                r = run_card(card, settings=settings, mandate=mandate, start=start, end=end)
                dist[tag].append(adjusted_excess(r) - base[tag])
                # How much this replicate's mask actually gates in this window. Recorded because
                # a shifted mask frequently lands on an all-positive stretch and gates nothing at
                # all -- the curve is un-inverted most of history -- so the raw null mixes 'a
                # gate' with 'no gate'. See the conditional null in the report.
                idx = [i for i, (d, _) in enumerate(mask) if start <= d + lag <= end]
                blocked[tag].append(
                    sum(1 for i in idx if not mask[(i + off) % n_mask][1]) / len(idx)
                )
        finally:
            macro_pin.active_pin = original  # type: ignore[assignment]
        if i % 10 == 0 or i == len(offsets):
            print(f"  {i}/{len(offsets)} shifts", flush=True)

    payload: dict[str, object] = {"form": FORM, "shifts": len(offsets), "windows": {}}
    print(f"\n{'window':10s} {'observed':>10s} {'null p2.5':>10s} {'null p97.5':>11s} {'median':>9s}  verdict")
    for tag, _, _ in WINDOWS:
        obs_d = json.loads((RESULTS / tag / "runs" / f"r1-r21-{FORM}-on.json").read_text())
        obs = (float(obs_d["total_return"]) - float(obs_d["capital_exposure"]) * float(obs_d["benchmark_return"])) - base[tag]
        xs = sorted(dist[tag])
        lo, hi = xs[int(0.025 * len(xs))], xs[min(len(xs) - 1, int(0.975 * len(xs)))]
        outside = obs < lo or obs > hi
        payload["windows"][tag] = {  # type: ignore[index]
            "observed_marginal": obs, "null_p2_5": lo, "null_p97_5": hi,
            "null_median": statistics.median(xs), "outside_null": outside, "n": len(xs),
            "raw_marginals": dist[tag], "blocked_fraction": blocked[tag],
        }
        print(f"{tag:10s} {obs*100:>+9.2f}pp {lo*100:>+9.2f}pp {hi*100:>+10.2f}pp "
              f"{statistics.median(xs)*100:>+8.2f}pp  {'OUTSIDE' if outside else 'inside'}")
    OUT.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
