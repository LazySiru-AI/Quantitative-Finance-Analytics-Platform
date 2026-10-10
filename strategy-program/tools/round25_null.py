"""Round 25's pre-registered null: 200 circular shifts of the *derived rate-of-change series*.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round25_null.py --shifts 200

`ROUND-25-PLAN.md` §6. A circular shift preserves the series' level distribution and its
autocorrelation while destroying its alignment to market events, so it separates "this signal, at this
phase" from "a signal shaped like this one".

**What is shifted is the derived series, not the pinned one.** Arm C reads the 20-session change, so
the null has to randomise the phase of *that* series. Shifting the level and then differencing it
would randomise a different treatment than the one the arm reads.

**The primary decision rule is the treated-only interval**, fixed in the plan before this ran rather
than chosen afterwards. Round 23's Amendment 3 established that a large share of replicates in this
construction apply no treatment at all -- a shift lands the window on a stretch where the signal never
fires, the card reproduces the control exactly, and the replicate contributes a zero. That point mass
makes the all-replicate interval too narrow and `outside` too easy to reach, and it is what produced
round 23's one spurious `outside`. Both intervals are reported so this round stays comparable with
rounds 22 and 23 as published; where they disagree, the treated-only interval governs.

**Not investment advice.**
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import statistics
import sys
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import round25 as R25

from app.config import get_settings
from app.market.macro_models import MacroPoint, MacroSeries, MacroSource, MacroUnit
from app.paper.mandate import default_mandate
from app.rules import macro_pin
from app.rules.nodes import MacroField
from app.tournament.allocation import run_allocation

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r25-2026-08" / "null.json"


def derived_points() -> list[tuple[object, float]]:
    """The rate-of-change series arm C actually reads, as (date, value) pairs."""
    series = R25.rate_of_change()[MacroField.T10Y2Y]
    return [(p.date, float(p.value)) for p in series.points]


def shifted(points: list[tuple[object, float]], offset: int) -> dict[MacroField, MacroSeries]:
    """The derived values, rotated by `offset` sessions and re-dated to the original calendar."""
    n = len(points)
    pts = [
        MacroPoint(date=date, value=points[(i + offset) % n][1])
        for i, (date, _) in enumerate(points)
    ]
    return {
        MacroField.T10Y2Y: MacroSeries(
            series_id="T10Y2Y",
            title="T10Y2Y 20-session change (circular-shift null replicate)",
            unit=MacroUnit.PERCENT_SPREAD,
            source=MacroSource.FRED,
            points=pts,
        )
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shifts", type=int, default=200)
    args = ap.parse_args(argv)

    import os

    os.environ.setdefault("INVDASH_MACRO_PIN", str(R25.MACRO_PIN))

    cards = R25.build()
    settings = get_settings()
    mandate = dataclasses.replace(
        default_mandate(starting_cash=R25.CAPITAL),
        max_single_name_weight=Decimal(1),
        allow_fractional_shares=True,
    )

    observed = json.loads((REPO / "data/rounds/r25-2026-08/results.json").read_text(encoding="utf-8"))
    prior = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else None
    pts = derived_points()
    n = len(pts)
    step = max(1, n // args.shifts)
    offsets = [((i * step) + 1) % n for i in range(args.shifts)]

    dist: dict[str, list[float]] = {tag: [] for tag, _, _ in R25.WINDOWS}
    print(f"{len(offsets)} shifts over {n} points, arm c-rate against a-control\n", flush=True)

    for i, off in enumerate(offsets, 1):
        series = shifted(pts, off)
        macro_pin.clear_pin_cache()
        original = macro_pin.active_pin
        macro_pin.active_pin = lambda path=None, _s=series: _s  # type: ignore[assignment]
        try:
            for tag, start, end in R25.WINDOWS:
                r = run_allocation(
                    cards["c-rate"], settings=settings, mandate=mandate, start=start, end=end
                )
                # The control reads no macro series, so its committed figure is the comparator.
                dist[tag].append(
                    float(r.total_return) * 100 - observed[tag]["a-control"]["total_return"]
                )
        finally:
            macro_pin.active_pin = original  # type: ignore[assignment]
            macro_pin.clear_pin_cache()
        if i % 10 == 0 or i == len(offsets):
            print(f"  {i}/{len(offsets)}", flush=True)

    payload: dict[str, object] = {"shifts": len(offsets), "lookback": R25.LOOKBACK, "windows": {}}
    drift: list[str] = []
    print()
    for tag, _, _ in R25.WINDOWS:
        d = sorted(dist[tag])
        obs = observed[tag]["c-rate"]["total_return"] - observed[tag]["a-control"]["total_return"]
        lo, hi = d[int(0.025 * len(d))], d[int(0.975 * len(d))]
        treated = sorted(v for v in d if v != 0.0)
        t_lo, t_hi = (
            (treated[int(0.025 * len(treated))], treated[int(0.975 * len(treated))])
            if treated
            else (lo, hi)
        )
        outside = obs < lo or obs > hi
        t_outside = obs < t_lo or obs > t_hi
        payload["windows"][tag] = {  # type: ignore[index]
            "observed_marginal": obs,
            "null_p2_5": lo,
            "null_p97_5": hi,
            "null_median": statistics.median(d),
            "outside_null": outside,
            "n": len(d),
            "n_untreated": len(d) - len(treated),
            "treated_p2_5": t_lo,
            "treated_p97_5": t_hi,
            # The plan's primary decision rule.
            "treated_outside_null": t_outside,
            "raw_marginals": d,
        }
        print(
            f"  {tag}: observed {obs:+7.2f}pp   all-200 [{lo:+7.2f}, {hi:+7.2f}] "
            f"-> {'OUTSIDE' if outside else 'inside'}"
        )
        print(
            f"    {len(d) - len(treated)}/{len(d)} untreated;  PRIMARY treated-only "
            f"[{t_lo:+7.2f}, {t_hi:+7.2f}] (n={len(treated)}) -> "
            f"{'OUTSIDE' if t_outside else 'inside'}"
        )

        if prior and tag in prior.get("windows", {}) and prior.get("shifts") == len(offsets):
            p = prior["windows"][tag]
            for field, now in (("observed_marginal", obs), ("null_p2_5", lo), ("null_p97_5", hi)):
                if field in p and abs(p[field] - now) > 1e-9:
                    drift.append(f"{tag}.{field}: committed {p[field]!r}, recomputed {now!r}")

    if drift:
        print("\nREFUSING TO WRITE -- this is a different measurement, not the committed one:")
        for line in drift:
            print(f"  {line}")
        return 1

    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
