"""Generate one Markdown *task packet* per not-yet-ingested influencer video, into a folder.

**Why this exists.** The owner runs small backfill jobs -- "summarise this influencer's new videos into
persona notes" -- on external agents (Gemini, ChatGPT) they already pay a subscription for, rather than
on this project's Claude budget. This script does the deterministic half: it finds what is new across
the followed channels, fetches each transcript, and writes a self-contained packet the owner pastes
into whatever agent they like. The agent's JSON reply comes back through `tools/ingest_backfill_results.py`
(the validated result-ingest), which re-imposes the ticker + numeric-grounding guardrails the in-house
summariser gets for free -- so nothing here needs a model, a credential, or the network beyond YouTube.

It is a thin wrapper over `app.personas.backfill`: discovery and rendering live there so the same code
backs the in-app "Backfill tasks" page; this CLI only parses arguments, writes files, and reports.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

from app.config import Settings  # noqa: E402
from app.personas import backfill  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write one Markdown task packet per new (un-ingested) influencer video into a folder, to "
            "hand to an external agent. Makes no model call and needs no credential."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--persona", action="append", dest="slugs", metavar="SLUG",
        help="restrict to this persona slug (repeatable); default is every followed persona",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="max new videos per persona (clamped by persona_backfill_max); default is that ceiling",
    )
    parser.add_argument("--out", type=Path, default=None, help="output folder (default: .backfill-tasks/)")
    args = parser.parse_args(argv)

    settings = Settings()
    try:
        tasks = backfill.discover_tasks(settings, limit_per_persona=args.limit, slugs=args.slugs)
    except Exception as exc:  # a clean message beats a traceback for an operator running this by hand
        print(f"discovery failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if not tasks:
        print("No new videos to back-fill: every followed video already has a note.")
        return 0

    # `Settings.backfill_tasks_dir`, not a constant local to this script: `tools/ingest_backfill_results.py`
    # and the in-app Backfill page have to look in the *same* folder to find the packet a pasted reply
    # answers (that packet is where the transcript the reply is grounded against still lives), so the
    # location is deployment configuration shared by three callers rather than this CLI's private default.
    out_dir = args.out if args.out is not None else settings.backfill_tasks_dir
    written = backfill.write_task_files(tasks, out_dir, summary_lang=settings.persona_summary_lang)

    by_persona: dict[str, int] = {}
    for task in tasks:
        by_persona[task.persona_name] = by_persona.get(task.persona_name, 0) + 1

    print(f"Wrote {len(written)} task packet(s) + index.md to {out_dir}")
    for name, count in sorted(by_persona.items()):
        print(f"  {name}: {count}")
    print("\nPaste a packet's contents into Gemini/ChatGPT/Claude; feed the JSON replies back with:")
    print("  python tools/ingest_backfill_results.py <folder-of-replies>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
