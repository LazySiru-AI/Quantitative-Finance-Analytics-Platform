"""Round 33 Phase B — the repeatable status/decision report.

Reads the screen-mode candidate log, the screen books, and every stored screen-mode workflow run,
applies the §4 floor and §6 decision rule from `docs/WORKFLOW-UNIVERSE-STUDY-PLAN.md` (see
`app.workflow.phase_b_report`'s module docstring for both, quoted verbatim), and writes a JSON +
markdown report -- the Phase B sibling of `strategy-program/tools/round33_bakeoff.py`'s Phase A report.
Pure read: no network call, no model call, no write to any book or run.

Run from the repo root with the repo venv:
    .venv/Scripts/python.exe strategy-program/tools/phase_b_report.py [--today YYYY-MM-DD] [--out-dir DIR]

Not investment advice.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from app.config import Settings
from app.workflow.phase_b_report import build_phase_b_report, render_markdown

_DEFAULT_OUT_DIR = Path("data/rounds/r33-2026-08")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--today", type=str, default=None, help="YYYY-MM-DD; default: real today")
    parser.add_argument("--out-dir", type=str, default=str(_DEFAULT_OUT_DIR), help="output directory")
    args = parser.parse_args()

    today = dt.date.fromisoformat(args.today) if args.today else None
    settings = Settings()

    report = build_phase_b_report(settings, today=today)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(report)
    (out_dir / "PHASE-B-REPORT.md").write_text(markdown, encoding="utf-8")
    (out_dir / "phase-b-report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8"
    )

    print(f"Phase B report {report.generated_on}", flush=True)
    print(f"  verdict: {report.verdict}", flush=True)
    print(f"  {report.verdict_detail}", flush=True)
    print(
        f"  floor: sessions {report.sessions_observed}/{report.floor_sessions_required}  "
        f"gated candidates {report.gated_candidates_per_gate.get('full_workflow', 0)}/"
        f"{report.floor_gated_required}  met={report.floor_met}",
        flush=True,
    )
    print(f"  wrote {out_dir / 'PHASE-B-REPORT.md'} and {out_dir / 'phase-b-report.json'}", flush=True)


if __name__ == "__main__":
    main()
