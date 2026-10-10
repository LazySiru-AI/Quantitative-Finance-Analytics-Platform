"""Run one Round 33 Phase B session: fill matured screen orders, then launch that session's
screened decision. This is the unit a daily scheduler (Windows Task Scheduler, cron) invokes, and
what to run by hand to advance the study one session.

    .venv/Scripts/python.exe -u strategy-program/tools/phase_b_step.py [--no-launch]

`--no-launch` runs the deterministic fill/resolve half only (no agent spend) -- useful to fill
yesterday's staged orders without launching a new decision.
"""

from __future__ import annotations

import argparse

from app.config import Settings
from app.workflow.phase_b import run_phase_b_step


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-launch", action="store_true", help="fill/resolve only, no new run")
    args = parser.parse_args()

    summary = run_phase_b_step(Settings(), launch=not args.no_launch)

    print(f"Phase B step {summary.today}", flush=True)
    print(f"  observations resolved: {summary.observations_resolved}", flush=True)
    print(f"  fills: {summary.filled}  rejected: {summary.rejected}  still pending: {summary.still_pending}", flush=True)
    if summary.launched_run_id is not None:
        print(f"  launched run: {summary.launched_run_id} -> {summary.launched_state}", flush=True)
        if summary.launched_error:
            print(f"  launch error: {summary.launched_error}", flush=True)
    else:
        print("  launch: skipped (--no-launch)", flush=True)
    print(f"  pending after step: {summary.staged}", flush=True)


if __name__ == "__main__":
    main()
