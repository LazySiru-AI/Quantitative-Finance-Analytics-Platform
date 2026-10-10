"""The Obsidian-compatible markdown vault store: persists and reads back personas, episodic notes,
and raw transcripts under ``<settings.vault_dir>/influencers/<slug>/`` (see
`docs/INFLUENCER-CONTRACT.md`'s "Vault layout" section, which pins the directory shape and the
episodic-note frontmatter schema this module writes and parses).

**Why the write is temp-file-then-`os.replace`, exactly like `app.agentdesk.store.RunStore`.** A
reader here is the same kind of reader that module worries about: an HTTP handler serving
``GET /api/personas/{slug}/notes`` can observe a file mid-write if the writer does not stage first,
and `os.replace` is atomic on both POSIX and Windows *only* for files on the same volume -- which a
same-directory staging file always is. Every write in this module (`persona.json`, one note's
markdown, its transcript, `log.md`) goes through the one `_write_atomic` helper below rather than a
direct `Path.write_text`, for that reason.

**Why a corrupt file is skipped, not raised, from a listing.** `list_personas` and `list_notes` each
have other, perfectly good files to show; one truncated `persona.json` or one note whose frontmatter
got mangled by an external editor must not take down the whole page. This mirrors
`RunStore.list_runs` exactly: the listing logs a warning and walks past the bad entry, while a direct
lookup by id/slug (`load_persona`, `load_note`) is allowed to answer "not found" for that one
corrupt file, because a caller asking about a specific id has nothing else to fall back to.

**Why episodic notes are immutable.** `write_note` raises rather than overwriting when a note for the
same `note_id` already exists. The contract calls episodic notes "never rewritten" -- they are the
persona's raw memory trace; only the Phase 2 profile and per-ticker theses get regenerated from them.
Enforcing that here, in the one place that writes a note file, is what makes it a guarantee rather
than a convention every future caller has to remember.

**Why frontmatter is hand-parsed instead of using PyYAML.** There is no YAML dependency in this repo
(see `backend/pyproject.toml`) and this module must not add one just to read back six scalar fields,
an optional date, a flat list of tickers and a flat symbol-to-stance map. What is implemented below is
a small, self-consistent *subset* of YAML flow scalars -- enough to round-trip exactly what this
module itself writes, quoting a value only when leaving it bare would change how it parses (a
``: `` sequence, a leading indicator character, an empty string, something that reads as a number or
boolean) or when the contract's own literal example always quotes that field (``title``, `source_id`).
It is not a general YAML parser and does not try to be one; the writer and parser are developed and
tested together as one symmetric pair, and `tests/test_personas_store.py` proves the round trip
rather than assuming it.

**Why `published`'s frontmatter key is omitted rather than null.** `EpisodicNote.published` is
`None` specifically to mean "the upstream genuinely could not tell us" (see that field's docstring in
`app.personas.models` -- yt-dlp's flat channel listing carries no upload date at all). Writing
``published: null`` would look identical to a value that was asked for and came back null, when the
truth is closer to "this line does not exist for this note." Omitting the key entirely is the
one-way-to-say-it choice; every *other* nullable field here (`title`, `transcript_source`) has no such
distinction to preserve, so those use the ordinary YAML `null`.

**`degraded` and `themes` (contract amendment, additive).** `degraded` is a frontmatter boolean that
is *always* written (`degraded: true`/`degraded: false`), the mirror image of `published`: a missing
key here does not mean "unknown", it means "written before this field existed," so it parses back as
`False` either way. `themes` is prose, not a scalar, so it lives in the body as a `## Themes` bullet
list between `## Summary` and `## Tickers` -- and unlike `## Tickers`/`## Quotes`, which always render
their heading, `## Themes` is omitted entirely when there are no themes, per the amendment.

**`summary_source` (contract amendment, additive).** A frontmatter scalar written on every note, the
same shape as `degraded`: a missing key means "written before this field existed", which reads back
as `"model"` -- the historical truth, since the external paste-back path
(`app.personas.backfill_ingest`) did not exist when those notes were made. An unrecognised value is
*not* coerced to the default; it fails `EpisodicNote`'s `Literal` check and the note is treated as
corrupt, because this field is a provenance claim and silently downgrading a broken one would assert
something the file does not say.

**Why the tickers/stances frontmatter lines are write-only.** They exist so a human skimming the
vault in Obsidian, or an Obsidian dataview query, can see a note's tickers without opening the body.
The reasoning per ticker -- the thing that actually needs to round-trip losslessly -- lives in the
``## Tickers`` body section instead, one bullet per `TickerMention`. Parsing therefore reconstructs
`EpisodicNote.mentions` from the body, not from the frontmatter's `tickers`/`stances` lines; those two
lines are regenerated from the same `mentions` tuple on every write and never read back.

**UTF-8, explicitly, everywhere.** Four of the five seed channels are Korean (see the contract's
"Verified upstream facts"). Every read and write below passes ``encoding="utf-8"`` -- Windows'
locale-default encoding is not UTF-8, and a default-encoding write here would silently corrupt
Korean summaries and quotes the moment this runs on a Windows checkout, which is exactly the
environment this repo is developed on.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import cast

from app.config import Settings
from app.personas.models import (
    EpisodicNote,
    Horizon,
    InstrumentKind,
    NoteKind,
    Persona,
    Stance,
    SummarySource,
    TickerMention,
    TranscriptSource,
    persona_dir,
    personas_root,
)

__all__ = ["VaultStore"]

logger = logging.getLogger(__name__)

_PERSONA_FILE = "persona.json"
_LOG_FILE = "log.md"
_NOTES_DIRNAME = "notes"

#: Length of the ``YYYY-MM-DD-`` prefix every note filename carries, used by `_notes_matching` to
#: pin a looked-up id to the whole trailing segment of the stem rather than any suffix of it.
_DATE_PREFIX_LENGTH = len("YYYY-MM-DD-")
_TRANSCRIPTS_DIRNAME = "transcripts"

# A plain-YAML-flow-scalar special char set: any of these appearing at the *start* of an unquoted
# value would be read by a real YAML parser as an indicator character (block sequence, anchor, tag,
# alias, comment, flow collection, etc.) rather than as the first character of a plain string.
_LEADING_INDICATOR_CHARS = "-?:,[]{}#&*!|>'\"%@`"
_RESERVED_SCALARS = {"true", "false", "null", "~"}
_NUMERIC_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)$")

#: The bracket group is OPTIONAL so a legacy note (written before `instrument`/`horizon` existed --
#: 216 of them on disk as of this writing) still parses: with no `[...]` at all, both named groups
#: come back `None`, and `_parse_tickers_section` below maps that to the model's own defaults
#: ("equity"/"unclear") rather than treating a missing bracket as a corrupt line.
_TICKER_LINE_RE = re.compile(
    r"^- \*\*(?P<symbol>[^*]+)\*\*"
    r"(?: \[(?P<instrument>[a-z]+), (?P<horizon>[a-z_]+)\])?"
    r" — (?P<stance>\w+)\. (?P<reasoning>.*)$"
)


class VaultStore:
    """Reads and writes the markdown vault for one process's worth of persona data.

    Stateless beyond `settings` -- every method resolves its own path from `personas_root`/
    `persona_dir` on every call, the same way `RunStore` does, so nothing here needs to be kept in
    sync with concurrent writers beyond what the atomic-write and immutable-note guarantees already
    provide.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # --- personas -----------------------------------------------------------

    def list_personas(self) -> tuple[Persona, ...]:
        """Every persona with a readable `persona.json`, sorted by `display_name`.

        An empty or absent vault answers `()`, not an error -- a fresh install has ingested nothing
        yet, and that is a normal state for the `/personas` page to render. A persona directory whose
        `persona.json` is missing or unparseable is logged and skipped, the same choice
        `RunStore.list_runs` makes for a bad `run.json`.
        """
        root = personas_root(self._settings)
        if not root.is_dir():
            return ()

        personas: list[Persona] = []
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            path = entry / _PERSONA_FILE
            if not path.is_file():
                continue
            try:
                personas.append(Persona.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                logger.warning("personas store: skipping unreadable persona file %s: %s", path, exc)
                continue

        personas.sort(key=lambda persona: persona.display_name)
        return tuple(personas)

    def load_persona(self, slug: str) -> Persona | None:
        """One persona by slug, or `None` if it does not exist or its `persona.json` cannot be
        parsed -- a direct lookup is allowed to say "not found" for a corrupt file, unlike
        `list_personas`, which has other personas to show and logs a warning instead."""
        path = persona_dir(self._settings, slug) / _PERSONA_FILE
        if not path.is_file():
            return None
        try:
            return Persona.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("personas store: could not read persona %r: %s", slug, exc)
            return None

    def save_persona(self, persona: Persona) -> None:
        """Write `persona.json` atomically. `persona.json` is the machine source of truth for the
        API (per the contract's vault layout), so it is written with `model_dump_json` rather than
        any hand-built dict -- the wire shape and the on-disk shape are the same shape, by
        construction."""
        path = persona_dir(self._settings, persona.slug) / _PERSONA_FILE
        _write_atomic(path, persona.model_dump_json(indent=2))

    def delete_persona(self, slug: str) -> bool:
        """Remove the persona's whole directory (notes, transcripts, `persona.json`, `log.md`).

        Returns whether it existed, rather than raising, for a slug that was never saved -- the same
        choice `RunStore.delete` makes: a caller asking to delete something already gone is not an
        error condition this store needs to distinguish from a successful delete.
        """
        directory = persona_dir(self._settings, slug)
        if not (directory / _PERSONA_FILE).is_file():
            return False
        shutil.rmtree(directory)
        return True

    # --- episodic notes -------------------------------------------------------

    def write_note(self, note: EpisodicNote, *, transcript_text: str | None = None) -> Path:
        """Write one immutable episodic note (and, if given, its raw transcript) to the vault.

        The note's filename date prefix comes from `note.published` when it is not `None`, else from
        `note.ingested_at` (the contract's rule, restated on `EpisodicNote.published`'s docstring in
        `app.personas.models`). The target location is derived here from `note.persona`,
        `note.note_id` and that date -- `note.path` on the incoming object is not consulted, because
        this store, not the caller, owns the vault's directory convention; `load_note`/`list_notes`
        set `path` to whatever this method actually wrote to when they reconstruct a note later.

        Raises `ValueError` if a note for this `note_id` already exists under this persona --
        episodic notes are never rewritten (see the module docstring). The transcript, if given, is
        written first, so a caller can never observe a note whose body links to a transcript file
        that does not exist yet.
        """
        slug = note.persona
        if self.has_note(slug, note.note_id):
            raise ValueError(
                f"note {note.note_id!r} already exists for persona {slug!r}; episodic notes are "
                f"immutable and cannot be overwritten"
            )

        has_transcript = transcript_text is not None
        if transcript_text is not None:
            transcript_path = persona_dir(self._settings, slug) / _TRANSCRIPTS_DIRNAME / (
                f"{note.note_id}.md"
            )
            _write_atomic(transcript_path, transcript_text)

        date_prefix = (note.published or note.ingested_at).date().isoformat()
        note_path = persona_dir(self._settings, slug) / _NOTES_DIRNAME / (
            f"{date_prefix}-{note.note_id}.md"
        )
        content = _render_note(note, include_transcript_link=has_transcript)
        _write_atomic(note_path, content)
        self._notify_note(note)
        return note_path

    def _notify_note(self, note: EpisodicNote) -> None:
        """Announce one newly written note through `app.notify`.

        `fyi`, the quietest severity: a new influencer note is something to read when convenient, not
        an interruption, and a backfill run writes them by the dozen. Under the default policy
        (`INVDASH_NOTIFY_MIN_SEVERITY=notable`) these are logged and *not* delivered, which is the
        intended shape -- `GET /api/notify/events` still shows every one.

        Called after the atomic write and only on the success path, so an event can never announce a
        note that is not on disk; notes are immutable (`write_note` refuses a duplicate id), so the
        `slug:note_id` dedupe key is exact rather than a heuristic. Wrapped, like every other hook.
        """
        try:
            from app.notify import emit

            title = note.title or note.url
            emit(
                self._settings,
                kind="persona.note",
                severity="fyi",
                headline=f"New note for {note.persona}: {title}",
                detail=note.summary,
                refs=(f"persona:{note.persona}",),
                source="personas.store",
                dedupe_id=f"persona.note:{note.persona}:{note.note_id}",
            )
        except Exception:
            logger.exception(
                "personas store: notify hook failed for note %s; the note itself is written",
                note.note_id,
            )

    def list_notes(self, slug: str) -> tuple[EpisodicNote, ...]:
        """Every readable note for `slug`, newest first (by `published`, falling back to
        `ingested_at` for a note whose upload date is unknown -- the same fallback the filename
        itself uses, so "newest" here tracks the same date that ordered the note into its file).

        A note whose file cannot be parsed is logged and skipped, not raised -- the same choice
        `RunStore.list_runs` makes for a bad `run.json`; see the module docstring.
        """
        notes_dir = persona_dir(self._settings, slug) / _NOTES_DIRNAME
        if not notes_dir.is_dir():
            return ()

        notes: list[EpisodicNote] = []
        for path in sorted(notes_dir.glob("*.md")):
            try:
                notes.append(_parse_note_file(path, slug=slug))
            except (OSError, ValueError) as exc:
                logger.warning("personas store: skipping unreadable note %s: %s", path, exc)
                continue

        notes.sort(key=lambda note: note.published or note.ingested_at, reverse=True)
        return tuple(notes)

    def load_note(self, slug: str, note_id: str) -> EpisodicNote | None:
        """One note by id, or `None` if it does not exist or cannot be parsed.

        The filename carries a date prefix this method does not otherwise know, so it globs for
        ``*-<note_id>.md`` rather than guessing the date -- immutability guarantees at most one match
        (`write_note` refuses a second note with the same id), and `sorted()` makes the choice
        deterministic in the pathological case of a leftover duplicate from outside this store.
        """
        notes_dir = persona_dir(self._settings, slug) / _NOTES_DIRNAME
        if not notes_dir.is_dir():
            return None
        matches = _notes_matching(notes_dir, note_id)
        if not matches:
            return None
        try:
            return _parse_note_file(matches[0], slug=slug)
        except (OSError, ValueError) as exc:
            logger.warning("personas store: could not read note %r/%r: %s", slug, note_id, exc)
            return None

    def has_note(self, slug: str, note_id: str) -> bool:
        """Whether a note for `note_id` already exists, without parsing it.

        Ingest needs this on every candidate video/post *before* spending a model call on a summary,
        so it is a directory glob, not a `load_note(...) is not None` call -- the latter would parse
        and validate the full frontmatter and body just to answer a yes/no question, and would also
        (wrongly) answer "no" for a note that exists but is corrupt, which is not the question being
        asked here.
        """
        notes_dir = persona_dir(self._settings, slug) / _NOTES_DIRNAME
        if not notes_dir.is_dir():
            return False
        return bool(_notes_matching(notes_dir, note_id))

    def read_transcript(self, slug: str, note_id: str) -> str | None:
        """The raw transcript/drop text for one note, or `None` if none was ever written for it --
        a manual text-drop note or a `"post"`-kind note may have no separate transcript file at
        all."""
        path = persona_dir(self._settings, slug) / _TRANSCRIPTS_DIRNAME / f"{note_id}.md"
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("personas store: could not read transcript %r/%r: %s", slug, note_id, exc)
            return None

    def append_log(self, slug: str, line: str) -> None:
        """Append one line to `log.md`, the append-only per-ingest cost log.

        Read-modify-atomic-write rather than an `open(..., "a")` append: the hard requirement here is
        that a concurrent reader never observes a half-written file, and a plain append does not make
        that promise on every platform for every write size. `log.md` is a small, human-scale file (one
        line per ingested item), so re-writing it whole on every append costs nothing that matters in
        exchange for the same atomicity guarantee every other write in this module gets.
        """
        path = persona_dir(self._settings, slug) / _LOG_FILE
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        _write_atomic(path, f"{existing}{line.rstrip(chr(10))}\n")


# --- atomic write --------------------------------------------------------------


def _notes_matching(notes_dir: Path, note_id: str) -> list[Path]:
    """Note files whose id is exactly `note_id`, sorted for determinism.

    **A glob of ``*-<note_id>.md`` is not sufficient, and the difference is a correctness bug.** The
    filename is ``<YYYY-MM-DD>-<note_id>.md``, and a note id may itself contain hyphens -- real
    YouTube video ids are drawn from ``[A-Za-z0-9_-]`` (``8T51-plWXBY`` and ``AUq4h-VPi-k`` are two
    from the seed channels), and a manual drop's id is ``drop-<hex>``. With a bare glob, the ``*``
    happily absorbs the date *and* the first part of a real id, so looking up ``plWXBY`` matches the
    file belonging to ``8T51-plWXBY``: `load_note` then returns a note whose `note_id` is not the one
    that was asked for, and `has_note` reports a video as already ingested when it never was, which
    would silently refuse to ever ingest it.

    Anchoring on the exact stem length pins the id to the whole trailing segment: the prefix is
    always ten date characters plus one separating hyphen, so a genuine match's stem is exactly
    ``11 + len(note_id)`` characters long.
    """
    if not note_id:
        return []
    expected_stem_length = _DATE_PREFIX_LENGTH + len(note_id)
    suffix = f"-{note_id}"
    return sorted(
        path
        for path in notes_dir.glob(f"*-{note_id}.md")
        if len(path.stem) == expected_stem_length and path.stem.endswith(suffix)
    )


def _write_atomic(path: Path, content: str) -> None:
    """Write `content` to `path` atomically: a uuid-suffixed staging file in `path`'s own directory,
    then a single `os.replace` onto the real name. See the module docstring for why -- this is the
    same technique `app.agentdesk.store.RunStore.save` uses, for the same reason: `os.replace` is
    atomic on both POSIX and Windows only for files on the same volume, which a same-directory
    staging file always is, and a uuid suffix (rather than a fixed `.tmp`) means two writers racing a
    staging name can never collide on the final replace.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f"{path.name}.{uuid.uuid4().hex}.tmp"
    staging.write_text(content, encoding="utf-8")
    os.replace(staging, path)


# --- frontmatter: writing --------------------------------------------------------


def _needs_quoting(value: str) -> bool:
    """Whether `value` would parse differently, or fail to parse, if written as a bare YAML plain
    scalar -- see the module docstring's note on why this is a hand-rolled subset of YAML rather
    than a dependency."""
    if value == "":
        return True
    if value != value.strip():
        return True
    if value.lower() in _RESERVED_SCALARS:
        return True
    if _NUMERIC_RE.match(value):
        return True
    if value[0] in _LEADING_INDICATOR_CHARS:
        return True
    if ": " in value or value.endswith(":"):
        return True
    return " #" in value


def _scalar(value: str, *, always_quote: bool = False) -> str:
    """Render `value` as a YAML flow scalar: quoted (with `\\` and `"` escaped) when required by
    `_needs_quoting`, or when `always_quote` is set -- used for `source_id` and `title`, which the
    contract's own literal frontmatter example always quotes regardless of content."""
    if always_quote or _needs_quoting(value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _scalar_or_null(value: str | None, *, always_quote: bool = False) -> str:
    if value is None:
        return "null"
    return _scalar(value, always_quote=always_quote)


def _render_frontmatter(note: EpisodicNote) -> str:
    lines = [
        "---",
        f"note_id: {_scalar(note.note_id)}",
        f"persona: {_scalar(note.persona)}",
        f"source_id: {_scalar(note.source_id, always_quote=True)}",
    ]
    if note.published is not None:
        # Omitted entirely, not written as `null`, when unknown -- see the module docstring.
        lines.append(f"published: {note.published.isoformat()}")
    lines.append(f"ingested_at: {note.ingested_at.isoformat()}")
    lines.append(f"url: {_scalar(note.url)}")
    lines.append(f"title: {_scalar_or_null(note.title, always_quote=True)}")
    lines.append(f"kind: {_scalar(note.kind)}")
    lines.append(f"transcript_source: {_scalar_or_null(note.transcript_source)}")
    lines.append(f"lang: {_scalar(note.lang)}")
    lines.append(f"tickers: [{', '.join(_scalar(m.symbol) for m in note.mentions)}]")
    stances = ", ".join(f"{_scalar(m.symbol)}: {_scalar(m.stance)}" for m in note.mentions)
    lines.append(f"stances: {{{stances}}}")
    # Always written, unlike `published` -- a missing key means "written before this field existed"
    # and must read back as `False`, not "unknown", so there is no state this key needs to omit.
    lines.append(f"degraded: {'true' if note.degraded else 'false'}")
    # Always written, like `degraded` and for the same reason: a missing key means "written before
    # this field existed", which parses back as the model's own default ("model"), so there is no
    # state this key needs to omit to stay honest.
    lines.append(f"summary_source: {_scalar(note.summary_source)}")
    lines.append("---")
    return "\n".join(lines)


def _render_note(note: EpisodicNote, *, include_transcript_link: bool) -> str:
    """The full markdown file for `note`: frontmatter, then the `## Summary` / `## Tickers` /
    `## Quotes` / `## Source` body the contract's example lays out.

    `include_transcript_link` controls whether `## Source` links to a transcript file -- only true
    when `write_note` actually wrote one, so a reader never follows a link to a file that does not
    exist.
    """
    frontmatter = _render_frontmatter(note)

    summary_section = f"## Summary\n{note.summary.strip()}"

    parts = [summary_section]

    # Omitted entirely when there are no themes -- unlike `## Tickers`/`## Quotes` below, which
    # always render their heading even when empty. The manager's amendment calls this out
    # explicitly: a note with no themes must read back as `()`, and the simplest way to make that
    # unambiguous is to have no section at all rather than an empty one.
    if note.themes:
        theme_lines = "\n".join(f"- {theme}" for theme in note.themes)
        parts.append(f"## Themes\n{theme_lines}")

    # `[instrument, horizon]` is emitted on every write, even at the defaults -- a legacy note only
    # ever lacks the bracket because it predates this field, never because this store chose to omit
    # it once the field existed (the module's "one way to say it" discipline, applied here too).
    ticker_lines = "\n".join(
        f"- **{mention.symbol}** [{mention.instrument}, {mention.horizon}] — "
        f"{mention.stance}. {mention.reasoning}"
        for mention in note.mentions
    )
    parts.append("## Tickers" + (f"\n{ticker_lines}" if ticker_lines else ""))

    quote_lines = "\n".join(f"> {quote}" for quote in note.quotes)
    parts.append("## Quotes" + (f"\n{quote_lines}" if quote_lines else ""))

    links = []
    if include_transcript_link:
        links.append(f"[Transcript](../{_TRANSCRIPTS_DIRNAME}/{note.note_id}.md)")
    links.append(f"[Original]({note.url})")
    parts.append(f"## Source\n{' · '.join(links)}")

    body = "\n\n".join(parts)
    return f"{frontmatter}\n\n{body}\n"


# --- frontmatter: parsing --------------------------------------------------------


def _split_frontmatter(raw: str) -> tuple[str, str]:
    if not raw.startswith("---\n"):
        raise ValueError("note file does not start with a '---' frontmatter delimiter")
    end = raw.find("\n---", 4)
    if end == -1:
        raise ValueError("note file has no closing '---' frontmatter delimiter")
    frontmatter_text = raw[4:end]
    body = raw[end + len("\n---") :]
    return frontmatter_text, body.lstrip("\n")


def _parse_scalar(value: str) -> str | None:
    """The inverse of `_scalar`/`_scalar_or_null`: unquote and unescape a quoted value, or map the
    YAML null spellings to `None`, or pass a plain value through unchanged."""
    if value.lower() == "null" or value == "~":
        return None
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        inner = value[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    return value


def _parse_frontmatter(text: str) -> dict[str, str | None]:
    """A flat `key -> scalar` map from the frontmatter block.

    Lines whose value is a flow list (`tickers: [...]`) or flow mapping (`stances: {...}`) are
    intentionally not decoded here -- see the module docstring on why those two lines are
    write-only; `mentions` is reconstructed from the body's `## Tickers` section instead, which is
    the only place the per-ticker reasoning lives.
    """
    result: dict[str, str | None] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        key, _, rest = line.partition(":")
        value = rest.strip()
        if value.startswith("[") or value.startswith("{"):
            continue
        result[key.strip()] = _parse_scalar(value)
    return result


def _require(frontmatter: dict[str, str | None], key: str) -> str:
    value = frontmatter.get(key)
    if value is None:
        raise ValueError(f"frontmatter is missing required key {key!r}")
    return value


def _extract_section(body: str, heading: str) -> str:
    """The text of a `## {heading}` body section, up to the next `## ` heading or end of file,
    stripped of the leading/trailing blank lines that separate sections."""
    marker = f"## {heading}"
    start = body.find(marker)
    if start == -1:
        return ""
    rest = body[start + len(marker) :]
    next_heading = rest.find("\n## ")
    section = rest[:next_heading] if next_heading != -1 else rest
    return section.strip("\n").strip()


def _parse_tickers_section(section: str) -> list[TickerMention]:
    mentions: list[TickerMention] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _TICKER_LINE_RE.match(stripped)
        if match is None:
            raise ValueError(f"unparseable line in '## Tickers' section: {stripped!r}")
        symbol = match["symbol"]
        # `cast`, not a runtime check: pydantic validates `stance` against the `Stance` Literal at
        # construction regardless of what mypy is told here, so a bad word in the file still raises
        # `ValidationError` (a `ValueError` subclass) and gets treated as a corrupt note by the
        # caller -- this only satisfies the static type checker, which (via pydantic's
        # `dataclass_transform`) checks constructor arguments against the model's field types even
        # without the mypy plugin.
        stance = cast("Stance", match["stance"])
        reasoning = match["reasoning"]
        # `instrument`/`horizon` are `None` for a legacy line with no bracket at all, or a captured
        # lowercase word for a line this store itself wrote. Either way, feed it straight to
        # `TickerMention` and let pydantic's own `Literal` check decide whether it is one of the
        # recognised values -- a `None` (missing bracket) or an unrecognised word (a future value
        # this build does not know, or outright corruption) both raise `ValidationError`, and both
        # fall back to the model defaults here rather than making an otherwise-good note unparseable.
        try:
            mention = TickerMention(
                symbol=symbol,
                stance=stance,
                reasoning=reasoning,
                instrument=cast("InstrumentKind", match["instrument"]),
                horizon=cast("Horizon", match["horizon"]),
            )
        except ValueError:
            mention = TickerMention(symbol=symbol, stance=stance, reasoning=reasoning)
        mentions.append(mention)
    return mentions


def _parse_themes_section(section: str) -> list[str]:
    """The inverse of the `## Themes` bullet rendering above. An absent section (`section == ""`,
    which is also what `_extract_section` returns when the heading itself is missing) parses to `[]`
    -- the "omitted means empty" contract the manager's amendment asks for."""
    themes: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("- "):
            raise ValueError(f"unparseable line in '## Themes' section: {stripped!r}")
        themes.append(stripped[2:].strip())
    return themes


def _parse_quotes_section(section: str) -> list[str]:
    quotes: list[str] = []
    for line in section.splitlines():
        if not line.strip():
            continue
        if not line.startswith("> "):
            raise ValueError(f"unparseable line in '## Quotes' section: {line!r}")
        quotes.append(line[2:])
    return quotes


def _parse_note_file(path: Path, *, slug: str) -> EpisodicNote:
    """Parse one note file back into an `EpisodicNote`.

    `path` is used both to read the file and to compute the returned `path` field: the vault-relative
    posix path is derived from `slug` and the file's own name, never from anything inside the file
    itself -- there is no `path` key in the frontmatter (see the module docstring), so the file's
    location on disk *is* the ground truth for it.
    """
    raw = path.read_text(encoding="utf-8")
    frontmatter_text, body = _split_frontmatter(raw)
    frontmatter = _parse_frontmatter(frontmatter_text)

    published_raw = frontmatter.get("published")
    published = dt.datetime.fromisoformat(published_raw) if published_raw is not None else None

    # Missing key -> `False`, the same "written before this field existed" fallback the manager's
    # amendment asks for -- `frontmatter.get(...)` already gives `None` for an absent key, so only an
    # explicit `"true"` (case-insensitively) counts as true.
    degraded_raw = frontmatter.get("degraded")
    degraded = degraded_raw is not None and degraded_raw.lower() == "true"

    # Missing key -> "model": a note written before this field existed came from the in-house
    # summariser by construction (the external paste-back path did not exist yet), so the default is
    # not a guess, it is the historical truth. An unrecognised word would fail `EpisodicNote`'s own
    # `Literal` check and make the whole note unparseable, which is the right way round: this field
    # is a provenance claim, and quietly downgrading a corrupt one to "model" would assert something
    # the file does not say.
    summary_source_raw = frontmatter.get("summary_source")

    themes = _parse_themes_section(_extract_section(body, "Themes"))
    mentions = _parse_tickers_section(_extract_section(body, "Tickers"))
    quotes = _parse_quotes_section(_extract_section(body, "Quotes"))
    summary = _extract_section(body, "Summary")

    return EpisodicNote(
        note_id=_require(frontmatter, "note_id"),
        persona=_require(frontmatter, "persona"),
        source_id=_require(frontmatter, "source_id"),
        published=published,
        ingested_at=dt.datetime.fromisoformat(_require(frontmatter, "ingested_at")),
        url=_require(frontmatter, "url"),
        title=frontmatter.get("title"),
        # Same `cast`-not-a-check reasoning as `_parse_tickers_section` above: pydantic still
        # validates these against `EpisodicNote`'s own `Literal` field types at construction.
        kind=cast("NoteKind", _require(frontmatter, "kind")),
        transcript_source=cast("TranscriptSource | None", frontmatter.get("transcript_source")),
        lang=_require(frontmatter, "lang"),
        summary=summary,
        themes=tuple(themes),
        quotes=tuple(quotes),
        mentions=tuple(mentions),
        path=f"influencers/{slug}/{_NOTES_DIRNAME}/{path.name}",
        degraded=degraded,
        summary_source=cast("SummarySource", summary_source_raw or "model"),
    )
