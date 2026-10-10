"""Round 21's pre-registered null: circular shifts of the gate mask.

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round21_null.py --shifts 200

`ROUND-21-PLAN.md` section 4 is the pre-registration. Read it first.

**Why not reuse round 17's ~1pp ordering-noise figure.** That came from re-running one card under
shuffled *universe orderings* -- a study about which of several qualifying names takes a scarce slot.
This round's factor is a macro gate, which does not touch universe order at all. Borrowing that number
here is the retroactively-lowered bar `00-EVERYTHING-TESTED.md` recommendation 5 warns against, so this
round measures its own null.

**Why a circular shift and not an i.i.d. reshuffle.** `T10Y2Y > 0` is a boolean series with real
autocorrelation -- the curve does not flip sign day to day, it stays inverted for months. Reshuffling
sessions independently would destroy that run-length structure and produce a null far tighter than the
truth, which would make almost any marginal look significant. A circular shift preserves the mask's
exact on/off proportion **and its exact run-length distribution**, randomising only its phase relative
to price. What it tests is therefore: "a regime-shaped filter with the real curve's own statistics, but
no informational relationship to this price series."

**How a shifted mask is expressed as something a card can read.** It is not, directly -- the DSL binds
`macro(T10Y2Y)` to whatever the pin holds, and a card cannot be told "use this array". So each shift
writes a **synthetic pin** whose `T10Y2Y` observations are +1 on the sessions the shifted mask is true
and -1 where it is false, chosen so that `macro(T10Y2Y) > 0` reproduces the shifted mask exactly after
release-date binding. The entire real pipeline -- binding, guard, engine -- runs unchanged; only the
data underneath it moves. That is the point: a null computed through a *different* code path would be
measuring the difference between two harnesses as well as the effect.

**The shift is applied to eligibility dates, not reference dates**, so every synthetic observation is
already release-lagged by construction and the guard's per-session check passes for the same reason it
passes on the real pin.

**Not investment advice.**
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import subprocess

from app.market.macro_models import MacroPoint, MacroSeries, MacroSource, MacroUnit
from app.rules.macro_pin import read_pin, write_pin
from app.rules.nodes import MacroField

REPO = pathlib.Path(__file__).resolve().parents[2]

ROUND = REPO / "data" / "rounds" / "r21-2026-08"
PIN = ROUND / "macro-pin.json"
CARDS = ROUND / "cards"
NULL_ROOT = ROUND / "null"

#: Only the gate-on cells are re-run. The gate-off half of each pair is unaffected by the mask, so
#: re-running it 200 times would burn four fifths of the compute reproducing a constant.
GATE_ON = ("r21-ma-crossover-on", "r21-rsi-pullback-on", "r21-channel-breakout-on", "r21-vol-compression-on")

#: The eight main windows, matching `run_round.sh`. `13f-legal` is excluded as it is for every
#: non-13F card.
WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("q4-2018", "2018-09-21", "2018-12-24"),
    ("covid", "2020-02-19", "2020-06-30"),
    ("bear-2022", "2022-01-03", "2022-10-12"),
    ("chop-2015", "2015-04-07", "2016-04-15"),
    ("chop-2011", "2011-05-26", "2012-06-06"),
    ("bull-2024", "2024-08-21", "2025-08-20"),
    ("recent", "2025-08-21", "2026-08-18"),
    ("gfc", "2007-10-09", "2009-03-09"),
)


def real_mask() -> list[tuple[dt.date, bool]]:
    """``(reference_date, curve_not_inverted)`` for every observed T10Y2Y point, chronological.

    Unobserved points (FRED's ``.`` for a market holiday) are dropped rather than treated as false:
    a holiday is not an inversion, and counting it as one would change the mask's on/off proportion,
    which the shift is supposed to preserve exactly.
    """
    series = read_pin(PIN)[MacroField.T10Y2Y]
    return [(p.date, p.value > 0) for p in series.points if p.value is not None]


def shifted_series(mask: list[tuple[dt.date, bool]], offset: int) -> MacroSeries:
    """The mask rotated by ``offset`` observations, re-expressed as a T10Y2Y series.

    Dates stay put; only the boolean values rotate. That is what makes this a *phase* randomisation:
    the same number of true sessions, in runs of the same lengths, sitting over different prices.
    """
    n = len(mask)
    values = [mask[(i + offset) % n][1] for i in range(n)]
    points = [
        MacroPoint(date=date, value=1.0 if flag else -1.0)
        for (date, _), flag in zip(mask, values, strict=True)
    ]
    return MacroSeries(
        series_id="T10Y2Y",
        title="T10Y2Y (circular-shift null)",
        unit=MacroUnit.PERCENT_SPREAD,
        source=MacroSource.FRED,
        points=points,
    )


def run_shift(offset: int, workdir: pathlib.Path, *, quiet: bool = True) -> dict[str, float]:
    """Run the four gate-on cells over all eight windows against one shifted mask."""
    pin_path = workdir / "macro-pin.json"
    if pin_path.exists():
        pin_path.unlink()  # a null replicate is disposable; the round's own pin never is
    write_pin(
        pin_path,
        {MacroField.T10Y2Y: shifted_series(real_mask(), offset)},
        created_at=dt.datetime(2026, 8, 30),
        note=f"round 21 circular-shift null, offset {offset}. NOT the round's pin.",
    )

    env = {"INVDASH_MACRO_PIN": str(pin_path)}
    out: dict[str, float] = {}
    for tag, start, end in WINDOWS:
        dest = workdir / "results" / tag
        cmd = [
            ".venv/Scripts/python.exe", "-m", "app.tournament",
            "--cards", str(CARDS), "--out", str(dest),
            "--persona", "uat/personas/pro-investor-01.setup.json",
            "--start", start, "--end", end, "--skip-pdf",
            "--only", "r21-",
        ]
        import os
        merged = {**os.environ, **env, "PYTHONPATH": "backend;."}
        subprocess.run(cmd, cwd=REPO, env=merged, capture_output=quiet, check=False)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shifts", type=int, default=200)
    parser.add_argument("--seed", type=int, default=2121)
    parser.add_argument("--describe", action="store_true", help="print the mask's own statistics only")
    args = parser.parse_args(argv)

    mask = real_mask()
    true_n = sum(1 for _, flag in mask if flag)
    runs: list[int] = []
    current = None
    length = 0
    for _, flag in mask:
        if flag == current:
            length += 1
        else:
            if current is not None:
                runs.append(length)
            current, length = flag, 1
    runs.append(length)

    print(f"T10Y2Y mask: {len(mask)} observed points, {mask[0][0]} .. {mask[-1][0]}")
    print(f"  not inverted: {true_n} ({100 * true_n / len(mask):.1f}%)")
    print(f"  runs: {len(runs)}, longest {max(runs)}, median {sorted(runs)[len(runs) // 2]}")
    print("  -- a circular shift preserves both of those exactly; only the phase moves.")
    if args.describe:
        return 0

    print(f"\n{args.shifts} shifts x {len(GATE_ON)} cells x {len(WINDOWS)} windows = "
          f"{args.shifts * len(GATE_ON) * len(WINDOWS)} runs")
    print("(not started -- see --describe; the runner is invoked by round21_null_run.sh)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
