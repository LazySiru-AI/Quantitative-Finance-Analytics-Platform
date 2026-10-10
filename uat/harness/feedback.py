"""Validate and append persona findings.

Validation is strict on purpose. The enhancement loop's whole premise is that a finding recorded on
Tuesday is actionable by an engineer on Friday who was not there, and the fields that make that true
-- ``observed``, ``expected``, ``why_it_matters``, a stable ``finding_id`` -- are exactly the ones a
model in a hurry will leave out. Rejecting the write is the only feedback mechanism that reliably
gets them filled in.

``jsonschema`` is not a dependency of this project, so the checks here are hand-written against
``uat/schema/feedback.schema.json``. That file remains the specification; this module must be kept
consistent with it, and :func:`validate` deliberately rejects unknown keys so the two drifting apart
surfaces as an error rather than as silently dropped data.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

__all__ = ["FindingError", "append_findings", "load_findings", "validate"]

_ID_RE: Final = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

_REQUIRED: Final = (
    "finding_id",
    "run_id",
    "persona_id",
    "session",
    "observed_at",
    "surface",
    "kind",
    "severity",
    "title",
    "observed",
    "expected",
    "why_it_matters",
)

_OPTIONAL: Final = (
    "session_date",
    "locator",
    "repro",
    "evidence",
    "blocked_decision",
    "suggested_fix",
    "verification",
)

_SURFACES: Final = frozenset({"ui", "api", "data", "docs", "workflow"})
_KINDS: Final = frozenset({"defect", "friction", "gap"})
_SEVERITIES: Final = frozenset({"blocker", "major", "minor", "polish"})

#: Below this, a prose field is not a description of anything. Chosen from the shortest genuinely
#: useful `observed` value seen while developing the harness ("total showed --- with no explanation",
#: 42 characters) rounded down, so it filters placeholders without filtering terse-but-real answers.
_MIN_PROSE: Final = 25


class FindingError(ValueError):
    """A finding was rejected. The message names every problem at once, not just the first."""

    def __init__(self, index: int, problems: list[str]) -> None:
        detail = "\n".join(f"  - {problem}" for problem in problems)
        super().__init__(f"finding[{index}] rejected:\n{detail}")
        self.index = index
        self.problems = problems


def validate(finding: dict[str, Any], *, index: int = 0) -> dict[str, Any]:
    """Check one finding and return it normalised. Raises :class:`FindingError` on any problem."""
    problems: list[str] = []

    unknown = set(finding) - set(_REQUIRED) - set(_OPTIONAL)
    if unknown:
        problems.append(
            f"unknown field(s) {sorted(unknown)}; the schema forbids extras so a typo cannot "
            "silently discard content"
        )

    for key in _REQUIRED:
        if key not in finding or finding[key] in (None, "", []):
            problems.append(f"{key} is required")

    finding_id = finding.get("finding_id")
    if isinstance(finding_id, str) and not _ID_RE.match(finding_id):
        problems.append(f"finding_id {finding_id!r} must be kebab-case: [a-z0-9] separated by '-'")
    if isinstance(finding_id, str) and re.search(r"\b(day|session)-?\d", finding_id):
        problems.append(
            f"finding_id {finding_id!r} names a session rather than a problem; ids are the dedupe "
            "key across runs and a session-scoped id can never match a later recurrence"
        )

    session = finding.get("session")
    if not isinstance(session, int) or isinstance(session, bool) or session < 1:
        problems.append("session must be an integer >= 1")

    for key, allowed in (("surface", _SURFACES), ("kind", _KINDS), ("severity", _SEVERITIES)):
        value = finding.get(key)
        if value is not None and value not in allowed:
            problems.append(f"{key} {value!r} is not one of {sorted(allowed)}")

    for key in ("observed", "expected", "why_it_matters"):
        value = finding.get(key)
        if isinstance(value, str) and len(value.strip()) < _MIN_PROSE:
            problems.append(
                f"{key} is {len(value.strip())} characters; under {_MIN_PROSE} is a placeholder, "
                "not a description someone can act on"
            )

    title = finding.get("title")
    if isinstance(title, str) and len(title) > 120:
        problems.append(f"title is {len(title)} characters; the schema caps it at 120")

    observed_at = finding.get("observed_at")
    if isinstance(observed_at, str):
        try:
            dt.datetime.fromisoformat(observed_at)
        except ValueError:
            problems.append(f"observed_at {observed_at!r} is not an ISO-8601 timestamp")

    session_date = finding.get("session_date")
    if isinstance(session_date, str):
        try:
            dt.date.fromisoformat(session_date)
        except ValueError:
            problems.append(f"session_date {session_date!r} is not an ISO-8601 date")

    for key in ("repro", "evidence"):
        value = finding.get(key)
        if value is not None and not (
            isinstance(value, list) and all(isinstance(item, str) for item in value)
        ):
            problems.append(f"{key} must be a list of strings")

    if finding.get("severity") == "blocker" and not finding.get("repro"):
        problems.append("a blocker must carry repro steps; nobody can fix what they cannot reproduce")

    if problems:
        raise FindingError(index, problems)

    normalised = dict(finding)
    normalised.setdefault("blocked_decision", False)
    return normalised


def append_findings(path: Path, findings: Iterable[dict[str, Any]]) -> int:
    """Validate every finding, then append them all. Returns the count written.

    All-or-nothing: one invalid finding aborts the whole batch before anything is written, so a
    partially-appended file never has to be reasoned about.
    """
    validated = [validate(finding, index=i) for i, finding in enumerate(findings)]

    existing = {f["finding_id"] for f in load_findings(path)}
    duplicates = [f["finding_id"] for f in validated if f["finding_id"] in existing]
    if duplicates:
        raise ValueError(
            f"finding_id(s) already recorded in this run: {duplicates}. "
            "Reuse across runs is how recurrence is detected; reuse within one run is a mistake."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for finding in validated:
            handle.write(json.dumps(finding, ensure_ascii=False, sort_keys=True) + "\n")
    return len(validated)


def load_findings(path: Path) -> list[dict[str, Any]]:
    """Read a findings file, tolerating absence but not corruption."""
    if not path.exists():
        return []
    findings: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            findings.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number} is not valid JSON: {exc}") from exc
    return findings
