"""Build Gemini task packets from transcript FILES, with no YouTube call -- the IP-block escape hatch.

**Why this exists.** `tools/backfill_task_bundler.py` fetches each transcript from YouTube, and that
fetch is exactly what gets an IP caption-blocked (both youtube-transcript-api and yt-dlp's subtitle
download return HTTP 429 once the ban trips; only listing/metadata, a different endpoint, still works).
This tool takes transcripts the owner already has -- copied from YouTube's own "Show transcript" panel,
a downloaded caption file, or anywhere else -- and renders the identical committed packet format from
them, so the backfill keeps moving while the block is in force. It never touches the network.

**Input.** A folder of transcript files, one per video, named `<persona_slug>__<video_id>.<ext>` (the
same shape the packets and replies use), or `<video_id>.<ext>` with `--persona <slug>` applied to all.
`<ext>` may be `.txt` (plain text, including YouTube's timestamp-prefixed copy), `.vtt`, `.srt`, or
`.json3`/`.json` (yt-dlp's caption JSON) -- each is cleaned down to plain transcript text. The persona
must already exist in the vault (create it with `app.personas.service.add_persona` first), and a video
that already has a note is skipped. Output packets land in `Settings.backfill_tasks_dir` (or `--out`),
ready to paste into Gemini and ingest with `tools/ingest_backfill_results.py`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

from app.config import Settings  # noqa: E402
from app.personas import backfill  # noqa: E402

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_SUFFIXES = (".txt", ".vtt", ".srt", ".json3", ".json")

#: A leading timestamp token on a transcript line, as YouTube's "Show transcript" copy produces
#: (`0:00`, `1:23`, `1:02:03`) -- stripped so the packet carries words, not clock ticks.
_LEADING_TS_RE = re.compile(r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d+)?\s+")
#: An inline VTT timing/markup tag (`<00:00:01.000>`, `<c>`, `</c>`).
_VTT_TAG_RE = re.compile(r"<[^>]+>")


def _clean_transcript(raw: str, suffix: str) -> str:
    """Reduce a caption file of any supported shape to plain transcript text."""
    if suffix in (".json3", ".json"):
        return _clean_json3(raw)
    if suffix == ".vtt":
        return _clean_cue_format(raw, drop_header="WEBVTT")
    if suffix == ".srt":
        return _clean_cue_format(raw, drop_header=None)
    return _clean_plain(raw)


def _clean_json3(raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _clean_plain(raw)
    if isinstance(data, dict) and "events" in data:
        segs = [
            seg.get("utf8", "")
            for event in data.get("events", [])
            for seg in event.get("segs", [])
        ]
        return _collapse("".join(segs))
    if isinstance(data, dict) and isinstance(data.get("text"), str):
        return _collapse(data["text"])
    return _clean_plain(raw)


def _clean_cue_format(raw: str, *, drop_header: str | None) -> str:
    """VTT/SRT: drop the header, cue-index lines, `-->` timing lines and inline tags; keep the text,
    de-duplicating the consecutive repeats auto-captions emit."""
    out: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if drop_header and stripped.startswith(drop_header):
            continue
        if "-->" in stripped:
            continue
        if stripped.isdigit():  # SRT cue index
            continue
        text = _VTT_TAG_RE.sub("", stripped).strip()
        if text and (not out or out[-1] != text):
            out.append(text)
    return _collapse(" ".join(out))


def _clean_plain(raw: str) -> str:
    lines = [_LEADING_TS_RE.sub("", line).strip() for line in raw.splitlines()]
    return _collapse(" ".join(line for line in lines if line))


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_name(stem: str, default_slug: str | None) -> tuple[str, str] | None:
    """`(persona_slug, video_id)` from a filename stem, or None when it names no usable video id."""
    if "__" in stem:
        slug, _, vid = stem.partition("__")
        vid = vid.strip()
        if slug and _VIDEO_ID_RE.match(vid):
            return slug, vid
        return None
    if default_slug and _VIDEO_ID_RE.match(stem):
        return default_slug, stem
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build Gemini task packets from transcript files (no YouTube call). Files are named "
            "<persona_slug>__<video_id>.<ext> (or <video_id>.<ext> with --persona)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("transcripts_dir", type=Path, help="folder of transcript files (.txt/.vtt/.srt/.json3)")
    parser.add_argument("--persona", default=None, help="persona slug for files named <video_id>.<ext>")
    parser.add_argument("--lang", default="", help="transcript language hint recorded on the packet")
    parser.add_argument("--out", type=Path, default=None, help="output folder (default: Settings.backfill_tasks_dir)")
    args = parser.parse_args(argv)

    if not args.transcripts_dir.is_dir():
        print(f"no such folder: {args.transcripts_dir}", file=sys.stderr)
        return 1

    from app.personas.store import VaultStore

    settings = Settings()
    store = VaultStore(settings)
    personas = {p.slug: p for p in store.list_personas()}

    files = sorted(
        p for p in args.transcripts_dir.iterdir() if p.is_file() and p.suffix.lower() in _SUFFIXES
    )
    if not files:
        print(f"No transcript files ({', '.join(_SUFFIXES)}) in {args.transcripts_dir}")
        return 0

    tasks = []
    skipped = 0
    for path in files:
        parsed = _parse_name(path.stem, args.persona)
        if parsed is None:
            print(f"{path.name}: skipped -- name is not <persona_slug>__<video_id> (and no --persona)")
            skipped += 1
            continue
        slug, video_id = parsed
        persona = personas.get(slug)
        if persona is None:
            print(f"{path.name}: skipped -- no persona {slug!r} in the vault (add it first)")
            skipped += 1
            continue
        if store.has_note(slug, video_id):
            print(f"{path.name}: skipped -- {slug}/{video_id} already has a note")
            skipped += 1
            continue
        transcript = _clean_transcript(path.read_text(encoding="utf-8", errors="replace"), path.suffix.lower())
        if not transcript:
            print(f"{path.name}: skipped -- no transcript text after cleaning")
            skipped += 1
            continue
        tasks.append(
            backfill.task_from_transcript(
                persona, video_id=video_id, transcript=transcript, lang=args.lang,
            )
        )
        print(f"{path.name}: packet for {slug}/{video_id} ({len(transcript)} chars)")

    if not tasks:
        print(f"\nNo packets built ({skipped} file(s) skipped).")
        return 1 if skipped else 0

    out_dir = args.out if args.out is not None else settings.backfill_tasks_dir
    written = backfill.write_task_files(tasks, out_dir, summary_lang=settings.persona_summary_lang)
    print(f"\nWrote {len(written)} packet(s) to {out_dir} ({skipped} skipped).")
    print("Paste each into Gemini; ingest the replies with tools/ingest_backfill_results.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
