"""One-shot migration from the old single-stage seat queue to the new two-stage one.

    ./.venv/Scripts/python.exe tools/migrate_seat_pipeline.py --dry-run
    ./.venv/Scripts/python.exe tools/migrate_seat_pipeline.py --apply

**Why this exists.** `app.evolution.models.SeatStatus` used to have one terminal "yes" --
`"approved"` -- which meant both "this card is worth keeping" and "this card is on the paper desk" at
once. On 2026-08-26 that collapsed decision let **22 cards get seated with no person having reviewed
them**: `POST .../approve` filed the request *and* wrote `roster_overlay.json` in the same call. The
pipeline is now two stages (`pending` -> `shelved` -> `seated`, see `app.evolution.models.PendingSeat`
for the full state diagram), and the owner decided the 22 auto-approved cards should land on the
**review shelf**, not stay seated without ever having been looked at.

This script is the migration that gets the two files on disk (`data/loop/pending_seats.json`,
`data/loop/roster_overlay.json`) from the old shape to the new one, exactly once:

1. Every `pending_seats.json` row with the now-retired `status == "approved"` becomes `"shelved"`,
   its `decided_note` prefixed with a fixed, dated explanation (existing notes are preserved, not
   discarded).
2. Every genome id that came from one of those rows is removed from `roster_overlay.json` -- and
   **only** those ids. An id sitting in the overlay that does not trace back to an `approved` seat
   request was put there by some other path (a hand-authored seat, a defect, a manual edit) and is
   not this migration's business to touch; it is left alone and reported as such.

**Why this reads the raw JSON rather than going through `app.evolution.promotion.read_pending_seats`.**
`SeatStatus` no longer has an `"approved"` value -- `app.evolution.models.PendingSeat` is a
`pydantic` model with `Literal["pending", "shelved", "seated", "rejected", "retired"]`, and the very
rows this migration exists to fix fail that model's own validation. Reading through the typed loader
would silently drop every row this script needs to find, logged as "a malformed row" and nothing
more. So this script parses the two JSON files as plain dicts, the same tolerant, best-effort shape
`app.evolution.promotion.read_pending_seats`/`read_overlay` already apply to a file that might not
match today's schema, and writes back plain dicts too -- every row this migration does not touch
(the three still-`"pending"` requests in the frozen snapshot, for instance) is round-tripped
byte-for-byte unless this script explicitly changed it.

**Idempotent by construction, not by a separate check.** After one successful run, no row is left
with `status == "approved"` -- the literal value this script looks for to decide what to migrate --
so a second run finds nothing to do and writes nothing, backups included. Nothing here reopens a
decision `app.evolution.promotion._transition`'s legality table would otherwise refuse: this script
never calls that module at all, since the rows it edits predate the state machine the legality table
enforces.

**Backups.** `--apply` copies both files to `<name>.pre-migration-<UTC timestamp>.json` beside the
originals *before* writing anything, and only when there is something to change -- a no-op run (the
common case on a second invocation) takes no backup and touches neither file. `--dry-run` never
writes anything, backups included; it only reports what `--apply` would do.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.evolution.models import pending_seats_path, roster_overlay_path

__all__ = [
    "MigrationReport",
    "main",
    "parse_args",
    "plan_migration",
    "print_report",
    "run_migration",
]

#: Prefixed onto every migrated row's `decided_note`, verbatim, per the migration contract this
#: script implements. Any note the row already carried is kept, appended after this prefix, rather
#: than overwritten -- a reviewer's original reason for approving the card (if one was ever written)
#: is still part of the record, just no longer the whole of it.
MIGRATION_NOTE_PREFIX = (
    "un-seated 2026-08-26 by owner (seated without review); see docs/research/loop/"
)


@dataclass
class MigrationReport:
    """Everything `plan_migration` decided to do, and everything it deliberately left alone -- the
    object both `--dry-run` and `--apply` print, so the two modes can never describe a different plan
    from the one that (in `--apply`'s case) was actually written.
    """

    shelved: list[tuple[str, str]] = field(default_factory=list)
    """`(genome_id, agent_id)` for each `"approved"` row moved to `"shelved"`."""

    overlay_removed: list[tuple[str, str]] = field(default_factory=list)
    """`(purpose, agent_id)` for each id removed from the roster overlay because it traced back to a
    migrated row."""

    overlay_left_alone: list[tuple[str, str]] = field(default_factory=list)
    """`(purpose, agent_id)` for each overlay id that does **not** correspond to an `approved` seat
    request -- kept, and named here so a reader can see this migration considered it and chose not to
    touch it, not that it was merely missed."""

    already_migrated: bool = False
    """`True` when no `"approved"` row was found at all -- either nothing was ever auto-seated under
    the old scheme, or a previous run of this script already converted every one of them. The report
    is otherwise empty in this case, and `--apply` writes nothing."""

    pending_path: Path | None = None
    overlay_path: Path | None = None

    @property
    def changed(self) -> bool:
        return bool(self.shelved or self.overlay_removed)


def _load_json(path: Path) -> dict[str, Any] | None:
    """Best-effort JSON object read, tolerant exactly like `app.evolution.promotion`'s own readers:
    a missing file is normal (nothing has ever been written there) and returns `None`; anything that
    is not a readable JSON object is also treated as absent rather than raising, since a migration
    script overwriting a file it cannot make sense of is worse than refusing to touch it."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def plan_migration(*, settings: Settings) -> tuple[MigrationReport, dict[str, Any] | None, dict[str, Any] | None]:
    """Read both files and decide what a migration would do, without writing anything.

    Returns `(report, new_pending_payload, new_overlay_payload)`. The two payloads are `None` when
    there is nothing to change (`report.already_migrated`) or when the corresponding file does not
    exist / is not readable -- in which case there is nothing for `run_migration` to write either.
    """
    pending_path = pending_seats_path(settings)
    overlay_path = roster_overlay_path(settings)
    report = MigrationReport(pending_path=pending_path, overlay_path=overlay_path)

    pending_payload = _load_json(pending_path)
    requests = pending_payload.get("requests") if pending_payload is not None else None
    if not isinstance(requests, list):
        requests = []

    approved_rows = [
        row for row in requests if isinstance(row, dict) and row.get("status") == "approved"
    ]
    if not approved_rows:
        report.already_migrated = True
        return report, None, None

    # -- pending_seats.json: approved -> shelved, note prefixed, everything else untouched --------
    to_remove: dict[str, set[str]] = {}  # purpose -> {agent_id, ...}
    new_requests: list[Any] = []
    for row in requests:
        if isinstance(row, dict) and row.get("status") == "approved":
            genome_id = str(row.get("genome_id", ""))
            agent_id = str(row.get("agent_id", genome_id))
            purpose = str(row.get("purpose", ""))
            existing_note = str(row.get("decided_note", "") or "")
            new_note = (
                MIGRATION_NOTE_PREFIX
                if not existing_note
                else f"{MIGRATION_NOTE_PREFIX} {existing_note}"
            )
            updated = copy.deepcopy(row)
            updated["status"] = "shelved"
            updated["decided_note"] = new_note
            new_requests.append(updated)
            report.shelved.append((genome_id, agent_id))
            to_remove.setdefault(purpose, set()).add(agent_id)
        else:
            new_requests.append(row)

    new_pending_payload: dict[str, Any] = (
        dict(pending_payload) if pending_payload is not None else {"version": 1}
    )
    new_pending_payload["requests"] = new_requests

    # -- roster_overlay.json: drop only ids that trace back to a migrated row --------------------
    overlay_payload = _load_json(overlay_path)
    seats = overlay_payload.get("seats") if overlay_payload is not None else None
    new_overlay_payload: dict[str, Any] | None = None
    if isinstance(seats, dict):
        new_seats: dict[str, Any] = {}
        for purpose, ids in seats.items():
            if not isinstance(ids, list):
                new_seats[purpose] = ids
                continue
            removable = to_remove.get(purpose, set())
            kept: list[Any] = []
            for agent_id in ids:
                if isinstance(agent_id, str) and agent_id in removable:
                    report.overlay_removed.append((purpose, agent_id))
                else:
                    kept.append(agent_id)
                    if isinstance(agent_id, str):
                        report.overlay_left_alone.append((purpose, agent_id))
            new_seats[purpose] = kept
        new_overlay_payload = dict(overlay_payload) if overlay_payload is not None else {"version": 1}
        new_overlay_payload["seats"] = new_seats
    # An overlay that is missing, unreadable, or has no `"seats"` object has nothing this migration
    # can safely touch -- there is no removal to make, so the "shelved" half still stands on its own.

    return report, new_pending_payload, new_overlay_payload


def _backup(path: Path, *, stamp: str) -> Path | None:
    """Copy `path` to `<name>.pre-migration-<stamp>.json` beside it, and return where it landed --
    `None` if `path` does not exist (nothing to back up, e.g. the overlay was already empty)."""
    if not path.is_file():
        return None
    backup_path = path.with_name(f"{path.stem}.pre-migration-{stamp}{path.suffix}")
    backup_path.write_bytes(path.read_bytes())
    return backup_path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-migrate")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_migration(*, settings: Settings, apply: bool) -> MigrationReport:
    """Plan the migration and, if `apply`, write it.

    `apply=False` (`--dry-run`) never touches disk, backups included -- `plan_migration` only reads.
    `apply=True` backs up both files first (only the ones a change actually touches, and only when
    `report.changed`), then writes the new `pending_seats.json` and, if it changed, the new
    `roster_overlay.json`. Idempotent: a second call with nothing left to migrate
    (`report.already_migrated`) writes nothing at all.
    """
    report, new_pending, new_overlay = plan_migration(settings=settings)
    if not apply or not report.changed:
        return report

    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    assert report.pending_path is not None and report.overlay_path is not None
    _backup(report.pending_path, stamp=stamp)
    if new_overlay is not None:
        _backup(report.overlay_path, stamp=stamp)

    if new_pending is not None:
        _write_json(report.pending_path, new_pending)
    if new_overlay is not None:
        _write_json(report.overlay_path, new_overlay)

    return report


def print_report(report: MigrationReport, *, apply: bool, log: Any = print) -> None:
    mode = "APPLIED" if apply else "DRY RUN"
    log(f"migrate_seat_pipeline ({mode})")
    log(f"  pending_seats.json: {report.pending_path}")
    log(f"  roster_overlay.json: {report.overlay_path}")
    log("")

    if report.already_migrated:
        log("Nothing to do: no 'approved' row found in pending_seats.json.")
        log("Either nothing was ever auto-seated under the old scheme, or this script already ran.")
        return

    log(f"Shelved {len(report.shelved)} row(s) (status 'approved' -> 'shelved'):")
    for genome_id, agent_id in report.shelved:
        suffix = "" if genome_id == agent_id else f" (agent_id {agent_id})"
        log(f"  - {genome_id}{suffix}")
    log("")

    log(f"Removed {len(report.overlay_removed)} id(s) from roster_overlay.json:")
    for purpose, agent_id in report.overlay_removed:
        log(f"  - {purpose}: {agent_id}")
    log("")

    if report.overlay_left_alone:
        log(
            f"Left {len(report.overlay_left_alone)} id(s) in roster_overlay.json untouched "
            "(no matching 'approved' seat request -- not this migration's to touch):"
        )
        for purpose, agent_id in report.overlay_left_alone:
            log(f"  - {purpose}: {agent_id}")
    else:
        log("Left 0 ids in roster_overlay.json untouched -- every overlay id traced back to an "
            "'approved' seat request.")
    log("")

    if apply:
        log("Backups written next to both files as <name>.pre-migration-<UTC timestamp>.<ext>.")
    else:
        log("Dry run: nothing was written. Re-run with --apply to write these changes.")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true", help="report what would change; write nothing"
    )
    mode.add_argument(
        "--apply", action="store_true", help="write the migration (backs up both files first)"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    report = run_migration(settings=settings, apply=args.apply)
    print_report(report, apply=args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
