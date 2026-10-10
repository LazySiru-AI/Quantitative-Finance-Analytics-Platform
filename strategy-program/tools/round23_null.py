"""Round 23's pre-registered null: 200 circular shifts of the *curve's values*, arm C, 3 windows.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round23_null.py --shifts 200

`ROUND-23-PLAN.md` §5. A circular shift preserves the series' level distribution and its
autocorrelation while destroying its alignment to market events, so it separates "this curve, at this
phase" from "a series shaped like this one".

**What differs from round 22's null, and why it has to.** Round 22 tested a binary gate, so its
replicates carry `+1` where a shifted *mask* is true and `-1` where it is false — enough to reproduce
`macro(T10Y2Y) > 0` exactly. This round's arm C reads the series' **magnitude**
(`-0.5 * macro(T10Y2Y)`), so a two-valued replicate would hold the treatment constant and measure
nothing. The replicates here therefore carry the **real values, circularly shifted**: same
distribution, same autocorrelation, same depth of inversion, wrong phase.

**How a shifted series reaches a card.** The same way round 22's mask does — by replacing
`macro_pin.active_pin` for the duration of one replicate, so binding, guard and engine all run
unchanged. Nothing is written to a pin file and the committed pin is never mutated.

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

import round23 as R23

from app.config import get_settings
from app.market.macro_models import MacroPoint, MacroSeries, MacroSource, MacroUnit
from app.paper.mandate import default_mandate
from app.rules import macro_pin
from app.rules.macro_pin import read_pin
from app.rules.nodes import MacroField
from app.tournament.allocation import run_allocation

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r23-2026-08" / "null.json"


def observed_points() -> list[tuple[object, float]]:
    series = read_pin(R23.MACRO_PIN)[MacroField.T10Y2Y]
    return [(p.date, float(p.value)) for p in series.points if p.value is not None]


def shifted(points: list[tuple[object, float]], offset: int) -> dict[MacroField, MacroSeries]:
    """The real values, rotated by `offset` sessions and re-dated to the original calendar."""
    n = len(points)
    pts = [
        MacroPoint(date=date, value=points[(i + offset) % n][1])
        for i, (date, _) in enumerate(points)
    ]
    return {
        MacroField.T10Y2Y: MacroSeries(
            series_id="T10Y2Y",
            title="T10Y2Y (circular-shift null replicate)",
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

    os.environ.setdefault("INVDASH_MACRO_PIN", str(R23.MACRO_PIN))

    cards = R23.build()
    settings = get_settings()
    mandate = dataclasses.replace(
        default_mandate(starting_cash=R23.CAPITAL),
        max_single_name_weight=Decimal(1),
        allow_fractional_shares=True,
    )

    observed = json.loads((REPO / "data/rounds/r23-2026-08/results.json").read_text(encoding="utf-8"))
    # Amendment 3. The committed run's figures, kept so this run can prove it reproduced them rather
    # than replaced them. Offsets are deterministic and the cards and store are frozen, so an
    # identical distribution is the *expected* outcome and any drift means this is a different
    # measurement -- in which case nothing is written.
    prior = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else None
    pts = observed_points()
    n = len(pts)
    step = max(1, n // args.shifts)
    offsets = [((i * step) + 1) % n for i in range(args.shifts)]

    dist: dict[str, list[float]] = {tag: [] for tag, _, _ in R23.WINDOWS}
    print(f"{len(offsets)} shifts over {n} points, arm c-sized against a-control\n", flush=True)

    for i, off in enumerate(offsets, 1):
        series = shifted(pts, off)
        macro_pin.clear_pin_cache()
        original = macro_pin.active_pin
        macro_pin.active_pin = lambda path=None, _s=series: _s  # type: ignore[assignment]
        try:
            for tag, start, end in R23.WINDOWS:
                r = run_allocation(
                    cards["c-sized"], settings=settings, mandate=mandate, start=start, end=end
                )
                # The control is unaffected by the macro series, so it is the committed figure.
                dist[tag].append(float(r.total_return) * 100 - observed[tag]["a-control"]["total_return"])
        finally:
            macro_pin.active_pin = original  # type: ignore[assignment]
        if i % 10 == 0 or i == len(offsets):
            print(f"  {i}/{len(offsets)}", flush=True)

    payload: dict[str, object] = {"shifts": len(offsets), "windows": {}}
    drift: list[str] = []
    print()
    for tag, _, _ in R23.WINDOWS:
        d = sorted(dist[tag])
        obs = observed[tag]["c-sized"]["total_return"] - observed[tag]["a-control"]["total_return"]
        lo, hi = d[int(0.025 * len(d))], d[int(0.975 * len(d))]
        outside = obs < lo or obs > hi
        # Amendment 3: the same interval rebuilt from replicates that actually applied the treatment.
        # A circular shift often lands the window on a non-inverted stretch, the tilt never fires, and
        # the replicate reproduces the control exactly -- an untreated replicate carried as a null draw.
        treated = sorted(v for v in d if v != 0.0)
        t_lo, t_hi = (
            (treated[int(0.025 * len(treated))], treated[int(0.975 * len(treated))])
            if treated
            else (lo, hi)
        )
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
            "treated_outside_null": t_outside,
            "raw_marginals": d,
        }
        verdict = "OUTSIDE the null" if outside else "inside the null"
        t_verdict = "OUTSIDE" if t_outside else "inside"
        print(f"  {tag}: observed {obs:+7.2f}pp   null [{lo:+7.2f}, {hi:+7.2f}]   -> {verdict}")
        print(
            f"    {len(d) - len(treated)}/{len(d)} untreated;  treated-only "
            f"[{t_lo:+7.2f}, {t_hi:+7.2f}] (n={len(treated)})   -> {t_verdict}"
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
