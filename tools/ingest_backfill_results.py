"""Ingest a folder of external-agent replies back into the persona vault, one note per reply.

**Why this exists.** `tools/backfill_task_bundler.py` writes one Markdown *task packet* per
un-ingested influencer video; the owner pastes each into whatever agent they already pay for (Gemini,
ChatGPT, another Claude) and saves each JSON reply into a folder. This is the other end: it matches
each reply back to the packet it answers, re-imposes the two guardrails the in-house summariser gets
for free -- ticker validation and a numeric-grounding check against the *packet's own transcript* --
and writes a persona note with honest provenance (`summary_source="external"`). Nothing here calls a
model or spends a cent; the whole point of the loop is that the summarising happened elsewhere.

**The packet folder is not optional.** Grounding needs the exact transcript the agent was shown, and
after the packet has been handed off that text exists in one place only: the packet on disk. A reply
whose packet has been deleted is reported, not guessed at -- validating against a re-fetched
transcript would be checking the answer against a different question. Regenerate with
`tools/backfill_task_bundler.py` and the reply becomes ingestible again unchanged.

Like the bundler, this is a thin wrapper: matching, parsing, validation and persistence all live in
`app.personas.backfill` / `app.personas.backfill_ingest`, so the same code backs the in-app page.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

from app.config import Settings  # noqa: E402
from app.personas import backfill  # noqa: E402
from app.personas.backfill_ingest import (  # noqa: E402
    BackfillResultInvalid,
    BackfillValidationFailed,
    ingest_result,
    parse_result,
    validate_result,
)

#: A YouTube video id: exactly 11 characters of `[A-Za-z0-9_-]`. The one shape that lets a reply be
#: matched back to its task without the owner having to name the file anything in particular.
_VIDEO_ID = r"[A-Za-z0-9_-]{11}"

#: The packet's own "Task id (paste back with the result)" line, however the agent echoed it back --
#: with or without backticks, with or without the parenthetical. Anchored on the words "task id" so a
#: bare 11-character run somewhere in the prose cannot be mistaken for the id.
_TASK_ID_LINE_RE = re.compile(rf"task id[^\n]*?[`\"']?(?P<video_id>{_VIDEO_ID})[`\"']?", re.IGNORECASE)

#: Fallback: the id sitting in the filename, which is what saving a packet's reply next to it
#: naturally produces (`creator-a__vnew.md`, `vnew.json`). Searched with word-ish boundaries so a
#: longer token cannot contribute an 11-character window by accident.
_FILENAME_ID_RE = re.compile(rf"(?:^|[^A-Za-z0-9_-])(?P<video_id>{_VIDEO_ID})(?:[^A-Za-z0-9_-]|$)")

#: A batch reply's per-video section heading: a markdown heading line whose entire text is one video
#: id (`## 8T51-plWXBY`). The owner's requested return format is ONE file with every video under such
#: a heading followed by its ```json block; this is what lets one file be split into per-video units.
#: The id must be the whole heading text (`\s*$`), so an ordinary titled heading ("## Summary") never
#: matches -- its words are not an 11-char id run.
_SECTION_HEADING_RE = re.compile(rf"(?m)^[ \t]*#+[ \t]+(?P<video_id>{_VIDEO_ID})[ \t]*$")

_SUFFIXES = (".md", ".json", ".txt")


def _video_id_from(text: str, stem: str) -> str | None:
    """The task id a reply answers: from a "Task id" line in the reply itself first, then from the
    filename. The reply's own line wins because the owner may have renamed the file, while the packet
    explicitly asks for the id to be pasted back with the result."""
    match = _TASK_ID_LINE_RE.search(text)
    if match is not None:
        return match["video_id"]
    match = _FILENAME_ID_RE.search(stem)
    if match is not None:
        return match["video_id"]
    return None


def _reply_units(text: str, stem: str) -> list[tuple[str | None, str, str]]:
    """Split one reply file into `(video_id, section_text, label)` units.

    The owner's batch format returns ONE markdown file with every video under a `## <video_id>`
    heading; a per-video save returns a file that is a single reply. When the file carries such
    headings, this yields one unit per section (the id comes from the heading, authoritative); when it
    carries none, it yields a single whole-file unit whose id is found the old way (a "Task id" line,
    else the filename). Either shape ingests without the owner having to declare which they used.
    """
    headings = list(_SECTION_HEADING_RE.finditer(text))
    if not headings:
        return [(_video_id_from(text, stem), text, stem)]
    units: list[tuple[str | None, str, str]] = []
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        video_id = match["video_id"]
        units.append((video_id, text[match.end() : end], f"{stem}#{video_id}"))
    return units


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest a folder of external-agent JSON replies as persona notes, validating each "
            "against its task packet's transcript. Makes no model call and needs no credential."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("results_dir", type=Path, help="folder of agent replies (*.md, *.json, *.txt)")
    parser.add_argument(
        "--tasks-dir", type=Path, default=None,
        help="folder the task packets were written to (default: Settings.backfill_tasks_dir)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="validate every reply and report, without writing any note",
    )
    args = parser.parse_args(argv)

    settings = Settings()
    tasks_dir = args.tasks_dir if args.tasks_dir is not None else settings.backfill_tasks_dir

    results_dir: Path = args.results_dir
    if not results_dir.is_dir():
        print(f"no such folder: {results_dir}", file=sys.stderr)
        return 1

    files = sorted(p for p in results_dir.iterdir() if p.is_file() and p.suffix.lower() in _SUFFIXES)
    if not files:
        print(f"No reply files ({', '.join(_SUFFIXES)}) in {results_dir}")
        return 0

    counts = {"ingested": 0, "rejected": 0, "invalid": 0, "unmatched": 0, "duplicate": 0}
    units = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"{path.name}: unmatched -- could not read it ({exc})")
            counts["unmatched"] += 1
            units += 1
            continue
        for video_id, section, label in _reply_units(text, path.stem):
            units += 1
            outcome = _process_unit(
                video_id, section, label=label, tasks_dir=tasks_dir,
                settings=settings, dry_run=args.dry_run,
            )
            counts[outcome] = counts.get(outcome, 0) + 1

    print(
        f"\n{units} reply/section(s): {counts['ingested']} ingested, {counts['rejected']} rejected, "
        f"{counts['invalid']} invalid, {counts['unmatched']} unmatched, {counts['duplicate']} duplicate"
    )
    # Only a reply this run could not act on at all is a hard error. A rejection is the guardrail
    # doing its job on a specific reply, but it still leaves work undone, so it counts too -- a
    # non-zero exit is what tells the owner "something in this folder still needs you".
    hard = counts["rejected"] + counts["invalid"] + counts["unmatched"]
    return 1 if hard else 0


def _process_unit(
    video_id: str | None, text: str, *, label: str, tasks_dir: Path, settings: Settings, dry_run: bool
) -> str:
    """Handle one reply unit (a whole file, or one `## <id>` section of a batch file) end to end,
    printing exactly one line for it. Returns the outcome key."""
    if video_id is None:
        print(f"{label}: unmatched -- no task id in the reply and none in the filename")
        return "unmatched"

    packet = backfill.find_task_packet(tasks_dir, video_id)
    if packet is None:
        print(
            f"{label}: no packet for {video_id} "
            f"(regenerate with tools/backfill_task_bundler.py)"
        )
        return "unmatched"

    try:
        result = parse_result(text)
    except BackfillResultInvalid as exc:
        print(f"{label}: invalid: {exc}")
        return "invalid"

    if dry_run:
        from app.personas.tickers import build_symbol_validator

        report = validate_result(
            result,
            transcript=packet.transcript,
            symbol_validator=build_symbol_validator(settings),
        )
        if report.ok:
            print(
                f"{label}: would ingest {video_id} -> {packet.ref.persona_slug} "
                f"({len(result.mentions)} tickers)"
            )
            return "ingested"
        print(f"{label}: rejected: {'; '.join(report.reasons)}")
        return "rejected"

    from app.personas.service import PersonaError

    try:
        note = ingest_result(
            settings,
            persona_slug=packet.ref.persona_slug,
            video_id=video_id,
            result=result,
            transcript=packet.transcript,
            url=packet.ref.url or None,
            title=packet.ref.title or None,
            published=_published(packet.ref.published),
            lang=packet.lang,
            transcript_source="auto" if packet.generated else "manual",
        )
    except BackfillValidationFailed as exc:
        print(f"{label}: rejected: {'; '.join(exc.reasons)}")
        return "rejected"
    except PersonaError as exc:
        if exc.status_code == 409:
            print(f"{label}: duplicate -- {video_id} already has a note")
            return "duplicate"
        print(f"{label}: unmatched -- {exc}")
        return "unmatched"

    print(
        f"{label}: ingested {video_id} -> {packet.ref.persona_slug} "
        f"({len(note.mentions)} tickers)"
    )
    return "ingested"


def _published(iso_date: str) -> dt.datetime | None:
    """The packet's `**Published:**` date as a UTC datetime, or `None` when the packet says unknown.

    Never substitutes today's date: `EpisodicNote.published` is nullable specifically so "the upstream
    could not tell us" stays distinguishable from a real date, and a wall-clock stand-in would order
    the persona's timeline wrong while looking exactly like a genuine value.
    """
    if not iso_date:
        return None
    try:
        return dt.datetime.fromisoformat(iso_date).replace(tzinfo=dt.UTC)
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
