"""Stamp verification verdicts onto a run's findings.

A persona's finding is a *report*, not a fact. The persona is a user: it can be misled by an error
message, by a page it did not find, or -- as happened in this run -- by its own browser automation
failing to deliver a click that a real mouse would have delivered. Three of the four blockers in the
first run were of that last kind, and shipping them to a backlog unverified would have put an
engineer on a bug that does not exist while the genuine gaps waited behind it.

So every finding gets read against the source before it counts, and the verdict is written back onto
the finding itself rather than kept in a separate document. ``uat/schema/feedback.schema.json``
reserves the ``verification`` object for exactly this, and stamping it in place keeps the JSONL the
single machine-readable record: a later run can diff against it, and a triager can filter to
``confirmed`` without consulting anything else.

Verdicts are supplied by whoever did the verifying -- this module only applies and validates them.
It refuses to invent one, and it refuses to stamp a finding it has no verdict for, so a finding
silently added to a run cannot pass through looking verified.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

__all__ = ["VERDICTS", "apply_verdicts"]

VERDICTS: frozenset[str] = frozenset(
    {"confirmed", "partly-confirmed", "not-reproduced", "works-as-designed", "unverified"}
)


def apply_verdicts(
    path: Path,
    verdicts: Mapping[str, Mapping[str, Any]],
    *,
    require_complete: bool = True,
) -> dict[str, int]:
    """Rewrite ``path`` with a ``verification`` block on each finding.

    Args:
        path: The run's ``feedback.jsonl``.
        verdicts: ``finding_id -> {"status", "checked_against", "note"}``.
        require_complete: Fail if any finding in the file has no verdict. On by default -- a
            partially verified run that looks fully verified is worse than an obviously unverified
            one.

    Returns:
        Counts by status.
    """
    findings = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    known = {f["finding_id"] for f in findings}
    unknown = set(verdicts) - known
    if unknown:
        raise ValueError(f"verdicts given for findings not in {path.name}: {sorted(unknown)}")

    missing = known - set(verdicts)
    if missing and require_complete:
        raise ValueError(f"no verdict for: {sorted(missing)}")

    counts: dict[str, int] = {}
    for finding in findings:
        verdict = verdicts.get(finding["finding_id"])
        if verdict is None:
            continue
        status = verdict["status"]
        if status not in VERDICTS:
            raise ValueError(f"{status!r} is not one of {sorted(VERDICTS)}")
        block: dict[str, Any] = {"status": status}
        if verdict.get("checked_against"):
            block["checked_against"] = list(verdict["checked_against"])
        if verdict.get("note"):
            block["note"] = verdict["note"]
        finding["verification"] = block
        counts[status] = counts.get(status, 0) + 1

    path.write_text(
        "".join(
            json.dumps(f, ensure_ascii=False, sort_keys=True) + "\n" for f in findings
        ),
        encoding="utf-8",
    )
    return counts
