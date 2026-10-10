"""Persistence for the Phase 2 consolidated persona: `profile.md`, its `profile.history/` archive,
and per-symbol `theses/<SYMBOL>.md` (see `docs/INFLUENCER-CONTRACT.md`'s "Phase 2 — persona
consolidation" section, which pins the vault layout additions and the frontmatter shape this module
writes and parses).

**Why this is a separate store from `app.personas.store.VaultStore`, not a method added to it.**
Phase 1's store owns immutable, append-only artifacts (`persona.json`, one file per note, `log.md`);
every write there either creates a new file or fully replaces one in place. `profile.md` is the one
artifact in this feature that is *deliberately* rewritten and, unlike `save_persona`, the previous
content must survive the rewrite under `profile.history/` rather than simply being replaced. That is
a different write contract, not a bigger version of the same one, so it gets its own module and its
own atomic-write helper rather than an awkward parameter on `VaultStore.save_persona`.

**Why the write is still temp-file-then-`os.replace`.** Same reasoning as `VaultStore`'s module
docstring: a reader here is the same kind of reader (an HTTP handler serving
``GET /api/personas/{slug}/profile`` or ``.../theses``), and `os.replace` is atomic on both POSIX and
Windows only for files on the same volume, which a same-directory staging file always is. Every write
below goes through `_write_atomic` for that reason, including archiving -- the archive copy of the
previous `profile.md` is itself staged-then-replaced, so a crash mid-archive can never leave a
half-written file under `profile.history/` either.

**Why `save_profile` archives *before* it overwrites, using the outgoing file's own
`consolidated_at`.** The contract says beliefs and playbook drift is meant to stay inspectable across
versions; the previous `profile.md` is read back off disk (not kept from some earlier in-memory
object -- there may not be one, this store is stateless) and copied verbatim to
``profile.history/<that version's consolidated_at, filesystem-safe>.md`` before the new content is
written to `profile.md`. If the outgoing file's own `consolidated_at` cannot be read back (a
corrupted prior write, or one from before this field existed), archiving falls back to the file's
mtime rather than skipping the archive step entirely -- "append-only, never delete an archived
version" is a stronger guarantee than "name it perfectly."

**Why frontmatter is hand-parsed instead of using PyYAML**, and why a corrupt file is skipped (not
raised) from a listing while a direct lookup answers "not found": both reasons are identical to
`VaultStore`'s module docstring and are not repeated here. What Phase 2 needs on top of that: a flow
*list* (`vocabulary: [...]`) actually has to round-trip its contents this time -- `VaultStore` gets to
leave `tickers`/`stances` write-only because the body carries the same information losslessly, but a
profile's body has no equivalent for `vocabulary`, so `_parse_flow_list`/`_render_flow_list` below are
new, not copied.

**Why an uncited claim line is dropped, not raised, while a malformed one still fails the file.**
`ProfileClaim.citations` is validated non-empty at construction (see its docstring in
`app.personas.models`), so a `"- <text>"` line with no ``[[note_id]]`` markers can never become a
`ProfileClaim` at all -- constructing one is not an option. Treating that single line as the whole
file's problem (raising, and losing every other claim in the section) would overreact to exactly the
kind of external hand-edit `VaultStore.list_notes` already tolerates for other structural damage; a
line that does not even start with ``"- "``, on the other hand, is not a recognisable claim in any
form and *does* fail the file, the same way `VaultStore`'s `## Tickers` parser treats an unparseable
ticker line as corrupting the whole note.

**UTF-8, explicitly, everywhere.** Same reasoning as `VaultStore`: the persona feature is
Korean-heavy, and Windows' locale-default encoding is not UTF-8. Every read and write below passes
``encoding="utf-8"``.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import uuid
from pathlib import Path
from typing import cast

from app.config import Settings
from app.personas.models import (
    PersonaProfile,
    ProfileClaim,
    RegimeView,
    RiskPosture,
    Stance,
    TickerThesis,
    persona_dir,
)

__all__ = ["ProfileStore"]

logger = logging.getLogger(__name__)

_PROFILE_FILE = "profile.md"
_HISTORY_DIRNAME = "profile.history"
_THESES_DIRNAME = "theses"

#: `[[note_id]]` citation tokens, matched anywhere in a claim line body (by convention they trail the
#: text, but this does not require that -- it strips every occurrence and treats what is left as the
#: claim text).
_CITATION_RE = re.compile(r"\[\[([^\]]+)\]\]")

# The same hand-rolled YAML-flow-scalar subset `app.personas.store` uses, duplicated here rather than
# imported: the writer and parser in each module are developed and tested together as one symmetric
# pair (see that module's docstring), and reaching into another module's private helpers would couple
# two things that only coincidentally look alike today.
_LEADING_INDICATOR_CHARS = "-?:,[]{}#&*!|>'\"%@`"
_RESERVED_SCALARS = {"true", "false", "null", "~"}
_NUMERIC_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)$")


class ProfileStore:
    """Reads and writes `profile.md`, its `profile.history/` archive, and `theses/<SYMBOL>.md`.

    Stateless beyond `settings`, like `VaultStore` -- every method resolves its own path from
    `persona_dir` on every call.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # --- profile --------------------------------------------------------------

    def load_profile(self, slug: str) -> PersonaProfile | None:
        """The current consolidated profile for `slug`, or `None` when it does not exist or cannot
        be parsed -- a direct lookup is allowed to say "not found" for a corrupt file, the same
        choice `VaultStore.load_persona` makes."""
        path = persona_dir(self._settings, slug) / _PROFILE_FILE
        if not path.is_file():
            return None
        try:
            return _parse_profile_file(path, slug=slug)
        except (OSError, ValueError) as exc:
            logger.warning("profile store: could not read profile %r: %s", slug, exc)
            return None

    def save_profile(self, profile: PersonaProfile) -> Path:
        """Archive the current `profile.md` (if one exists) under `profile.history/`, then write
        `profile` as the new `profile.md`, atomically.

        The target location is derived here from `profile.persona`, not from `profile.path` on the
        incoming object -- this store, not the caller, owns the vault's directory convention, the
        same rule `VaultStore.write_note` follows. `load_profile` sets `path` to what this method
        actually wrote when it reconstructs a profile later.
        """
        directory = persona_dir(self._settings, profile.persona)
        target = directory / _PROFILE_FILE
        if target.is_file():
            _archive_profile(target, history_dir=directory / _HISTORY_DIRNAME)
        _write_atomic(target, _render_profile(profile))
        return target

    def profile_history(self, slug: str) -> tuple[str, ...]:
        """Archived version filenames under `profile.history/`, newest first.

        Filenames are always written as a filesystem-safe rendering of that version's own
        `consolidated_at` (see `_filesystem_safe_iso`), which is a fixed-width, zero-padded ISO
        timestamp -- so a plain reverse string sort orders them newest-first without opening and
        parsing every archived file just to answer this question.
        """
        history_dir = persona_dir(self._settings, slug) / _HISTORY_DIRNAME
        if not history_dir.is_dir():
            return ()
        return tuple(sorted((p.name for p in history_dir.glob("*.md")), reverse=True))

    def list_versions(self, slug: str) -> tuple[int, ...]:
        """Every consolidated version number for `slug`, ascending -- the current `profile.md`'s
        `version` plus every archived file's under `profile.history/`.

        Reuses `_parse_profile_file`'s frontmatter parsing (the version is the same `version:` field
        `load_profile` already reads) rather than re-deriving it from a filename; a file that cannot
        be parsed is skipped, not raised, the same tolerance `profile_history`/`load_profile` give a
        corrupt or hand-edited file elsewhere in this store.
        """
        return tuple(sorted(version for _path, version, _profile in self._all_versions(slug)))

    def load_version(self, slug: str, version: int) -> PersonaProfile | None:
        """The consolidated profile at exactly `version` -- whether that is the current `profile.md`
        or an archived file under `profile.history/` -- or `None` when no readable file records that
        version number.

        `path` on the returned profile reflects where it actually lives (the live `profile.md`, or
        the specific archived file under `profile.history/`), not always the live location, so a
        caller comparing two versions can tell which one is current.
        """
        for path, found_version, profile in self._all_versions(slug):
            if found_version == version:
                return profile.model_copy(update={"path": path})
        return None

    def _all_versions(self, slug: str) -> list[tuple[str, int, PersonaProfile]]:
        """`(vault-relative path, version, parsed profile)` for the current `profile.md` (if any) and
        every readable archived file under `profile.history/`. Shared by `list_versions` and
        `load_version` so both walk the same files the same way."""
        directory = persona_dir(self._settings, slug)
        found: list[tuple[str, int, PersonaProfile]] = []

        current = directory / _PROFILE_FILE
        if current.is_file():
            try:
                profile = _parse_profile_file(current, slug=slug)
            except (OSError, ValueError) as exc:
                logger.warning("profile store: could not read profile %r: %s", slug, exc)
            else:
                found.append((f"influencers/{slug}/{_PROFILE_FILE}", profile.version, profile))

        history_dir = directory / _HISTORY_DIRNAME
        if history_dir.is_dir():
            for path in history_dir.glob("*.md"):
                try:
                    profile = _parse_profile_file(path, slug=slug)
                except (OSError, ValueError) as exc:
                    logger.warning(
                        "profile store: skipping unreadable archived profile %s: %s", path, exc
                    )
                    continue
                archived_path = f"influencers/{slug}/{_HISTORY_DIRNAME}/{path.name}"
                found.append((archived_path, profile.version, profile))

        return found

    # --- theses -----------------------------------------------------------------

    def load_thesis(self, slug: str, symbol: str) -> TickerThesis | None:
        """One persona's running view on `symbol`, or `None` when it does not exist or cannot be
        parsed."""
        path = _thesis_path(self._settings, slug, symbol)
        if not path.is_file():
            return None
        try:
            return _parse_thesis_file(path, slug=slug)
        except (OSError, ValueError) as exc:
            logger.warning("profile store: could not read thesis %r/%r: %s", slug, symbol, exc)
            return None

    def save_thesis(self, thesis: TickerThesis) -> Path:
        """Write `thesis` to `theses/<SYMBOL>.md`, atomically, fully replacing whatever was there.

        Unlike `profile.md`, a thesis has no history requirement in the contract -- it is "one
        running per-ticker view", not a versioned document -- so this is a plain atomic overwrite,
        with the target derived from `thesis.persona`/`thesis.symbol` rather than `thesis.path`, the
        same "store owns the path" rule `save_profile` follows.
        """
        path = _thesis_path(self._settings, thesis.persona, thesis.symbol)
        _write_atomic(path, _render_thesis(thesis))
        return path

    def list_theses(self, slug: str) -> tuple[TickerThesis, ...]:
        """Every readable thesis for `slug`, sorted by symbol.

        A thesis file that cannot be parsed is logged and skipped, not raised -- the same choice
        `VaultStore.list_notes` makes for a bad note file (see the module docstring).
        """
        theses_dir = persona_dir(self._settings, slug) / _THESES_DIRNAME
        if not theses_dir.is_dir():
            return ()

        theses: list[TickerThesis] = []
        for path in sorted(theses_dir.glob("*.md")):
            try:
                theses.append(_parse_thesis_file(path, slug=slug))
            except (OSError, ValueError) as exc:
                logger.warning("profile store: skipping unreadable thesis %s: %s", path, exc)
                continue

        theses.sort(key=lambda thesis: thesis.symbol)
        return tuple(theses)


# --- paths ------------------------------------------------------------------------


def _thesis_path(settings: Settings, slug: str, symbol: str) -> Path:
    return persona_dir(settings, slug) / _THESES_DIRNAME / f"{symbol.strip().upper()}.md"


# --- atomic write -------------------------------------------------------------------


def _write_atomic(path: Path, content: str) -> None:
    """Write `content` to `path` atomically: a uuid-suffixed staging file in `path`'s own directory,
    then a single `os.replace` onto the real name. Identical technique to
    `app.personas.store._write_atomic` and `app.agentdesk.store.RunStore.save`, for the same reason:
    `os.replace` is atomic on both POSIX and Windows only for files on the same volume, which a
    same-directory staging file always is, and a uuid suffix means two writers racing a staging name
    can never collide on the final replace.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f"{path.name}.{uuid.uuid4().hex}.tmp"
    staging.write_text(content, encoding="utf-8")
    os.replace(staging, path)


# --- profile history archiving -------------------------------------------------------


def _filesystem_safe_iso(value: dt.datetime) -> str:
    """A rendering of `value` that is both a valid Windows/POSIX filename component and
    lexicographically sortable in the same order as the timestamps themselves.

    `datetime.isoformat` uses `:` between hours/minutes/seconds, which Windows forbids in filenames;
    replacing it with `-` is the only substitution needed since every other character ISO-8601 uses
    (digits, `T`, `-`, `+`, `.`) is already filename-safe on both platforms. `timespec="microseconds"`
    is pinned rather than left to the datetime's own precision so every rendering has the same fixed
    width -- without that, one timestamp with a zero microsecond field (which `isoformat()` renders
    with no fractional part at all) would sort inconsistently against one that has microseconds,
    breaking the plain string sort `profile_history` relies on.
    """
    return value.isoformat(timespec="microseconds").replace(":", "-")


def _extract_consolidated_at(raw: str) -> dt.datetime | None:
    """Best-effort read of just the `consolidated_at` frontmatter value from a raw `profile.md`
    file's contents, without validating the rest of the document -- used only to name the archive
    copy of an *outgoing* profile, which may itself be corrupt (see the module docstring on why
    archiving still proceeds in that case)."""
    try:
        frontmatter_text, _ = _split_frontmatter(raw)
    except ValueError:
        return None
    raw_value = _split_frontmatter_lines(frontmatter_text).get("consolidated_at")
    if raw_value is None:
        return None
    parsed = _parse_scalar(raw_value)
    if parsed is None:
        return None
    try:
        return dt.datetime.fromisoformat(parsed)
    except ValueError:
        return None


def _archive_profile(target: Path, *, history_dir: Path) -> None:
    """Copy the current contents of `target` (an existing `profile.md`) verbatim into `history_dir`,
    named after that version's own `consolidated_at`. Called by `save_profile` before it overwrites
    `target` with the new version -- see the module docstring for why this order, and why archiving
    still happens even when the outgoing file's `consolidated_at` cannot be read back.
    """
    raw = target.read_text(encoding="utf-8")
    consolidated_at = _extract_consolidated_at(raw)
    if consolidated_at is None:
        consolidated_at = dt.datetime.fromtimestamp(target.stat().st_mtime, tz=dt.UTC)

    stamp = _filesystem_safe_iso(consolidated_at)
    archive_path = history_dir / f"{stamp}.md"
    if archive_path.exists():
        # Two consolidations landing at the same microsecond (plausible with a mocked clock in a
        # test) would otherwise silently overwrite one archived version with another -- history is
        # append-only, so a short uuid suffix disambiguates instead.
        archive_path = history_dir / f"{stamp}-{uuid.uuid4().hex[:8]}.md"
    _write_atomic(archive_path, raw)


# --- frontmatter: writing -----------------------------------------------------------


def _needs_quoting(value: str) -> bool:
    """Whether `value` would parse differently, or fail to parse, if written as a bare YAML plain
    scalar. Identical rule to `app.personas.store._needs_quoting` -- see that module's docstring."""
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


def _scalar(value: str) -> str:
    """Render `value` as a YAML flow scalar: quoted (with `\\` and `"` escaped) when `_needs_quoting`
    requires it, bare otherwise."""
    if _needs_quoting(value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _render_flow_list(items: tuple[str, ...]) -> str:
    return "[" + ", ".join(_scalar(item) for item in items) + "]"


def _render_claim_line(claim: ProfileClaim) -> str:
    citations = " ".join(f"[[{citation}]]" for citation in claim.citations)
    return f"- {claim.text} {citations}".rstrip()


def _render_claims_body(claims: tuple[ProfileClaim, ...]) -> str:
    if not claims:
        return ""
    return "\n" + "\n".join(_render_claim_line(claim) for claim in claims)


def _render_profile(profile: PersonaProfile) -> str:
    frontmatter = "\n".join(
        [
            "---",
            f"persona: {_scalar(profile.persona)}",
            f"version: {profile.version}",
            f"consolidated_at: {profile.consolidated_at.isoformat()}",
            f"note_count: {profile.note_count}",
            f"degraded: {'true' if profile.degraded else 'false'}",
            f"vocabulary: {_render_flow_list(profile.vocabulary)}",
            "---",
        ]
    )

    parts = [
        f"## Summary\n{profile.summary.strip()}",
        "## Beliefs" + _render_claims_body(profile.beliefs),
        "## Playbook" + _render_claims_body(profile.playbook),
    ]
    # Unlike `## Beliefs`/`## Playbook` above, which always render their heading even with no
    # claims, `## Methodology` is omitted entirely when empty -- same choice `app.personas.store`
    # makes for a note's `## Themes`: a persona whose videos never discuss technique (a pure macro
    # commentator) must read back as `()`, and the simplest way to make that unambiguous is to have
    # no section at all rather than an empty heading. It also means a profile.md written before this
    # field existed is byte-for-byte indistinguishable from one for a technique-free persona, so the
    # legacy-file case in `_parse_profile_file` needs no special casing beyond `_extract_section`
    # already returning `""` for a missing heading.
    if profile.methodology:
        parts.append("## Methodology" + _render_claims_body(profile.methodology))
    # `## Regime` follows the same honest-empty rule as `## Methodology` just above, with one more
    # condition: it is omitted both when there is no `RegimeView` at all (a profile consolidated
    # before this field existed) *and* when there is one but `has_signal` is False (a purely
    # technical persona who offers no macro view) -- `RegimeView()`'s own defaults are exactly that
    # second case, so "has a RegimeView with nothing to say" and "has no RegimeView" render
    # byte-for-byte identically, and both load back as `regime=None` (see `_parse_regime_section`).
    if profile.regime is not None and profile.regime.has_signal:
        parts.append(_render_regime_section(profile.regime))
    body = "\n\n".join(parts)
    return f"{frontmatter}\n\n{body}\n"


def _render_regime_section(regime: RegimeView) -> str:
    """Render a populated `RegimeView` as a `## Regime` section: one `key: value` line per field,
    using the same hand-rolled YAML flow-scalar/flow-list rendering (`_scalar`/`_render_flow_list`)
    the frontmatter block already uses -- a `RegimeView` is one structured record, not a list of
    cited claims, so it does not fit the `## Beliefs`/`## Playbook`/`## Methodology` claim-line shape
    above. `has_signal` itself is not written: the section's mere presence already means it was
    `True` (see the omission rule in `_render_profile`), and `_parse_regime_section` relies on that.
    """
    lines = [
        "## Regime",
        f"risk: {_scalar(regime.risk)}",
        f"rates: {_scalar(regime.rates)}",
        f"summary: {_scalar(regime.summary)}",
        f"sectors_favoured: {_render_flow_list(regime.sectors_favoured)}",
        f"sectors_avoided: {_render_flow_list(regime.sectors_avoided)}",
        f"citations: {_render_flow_list(regime.citations)}",
    ]
    return "\n".join(lines)


def _render_thesis(thesis: TickerThesis) -> str:
    frontmatter = "\n".join(
        [
            "---",
            f"persona: {_scalar(thesis.persona)}",
            f"symbol: {_scalar(thesis.symbol)}",
            f"stance: {_scalar(thesis.stance)}",
            f"updated_at: {thesis.updated_at.isoformat()}",
            "---",
        ]
    )
    body = "## Claims" + _render_claims_body(thesis.claims)
    return f"{frontmatter}\n\n{body}\n"


# --- frontmatter: parsing -----------------------------------------------------------


def _split_frontmatter(raw: str) -> tuple[str, str]:
    if not raw.startswith("---\n"):
        raise ValueError("file does not start with a '---' frontmatter delimiter")
    end = raw.find("\n---", 4)
    if end == -1:
        raise ValueError("file has no closing '---' frontmatter delimiter")
    frontmatter_text = raw[4:end]
    body = raw[end + len("\n---") :]
    return frontmatter_text, body.lstrip("\n")


def _parse_scalar(value: str) -> str | None:
    """The inverse of `_scalar`: unquote and unescape a quoted value, map the YAML null spellings to
    `None`, or pass a plain value through unchanged."""
    if value.lower() == "null" or value == "~":
        return None
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        inner = value[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    return value


def _split_frontmatter_lines(text: str) -> dict[str, str]:
    """`key -> raw (still-quoted, unparsed) value string` for every top-level frontmatter line,
    including flow-collection lines (`vocabulary: [...]`) -- unlike
    `app.personas.store._parse_frontmatter`, which deliberately skips those because that module never
    needs to read them back. Here `vocabulary` does need to round-trip, so it is not filtered out;
    callers decode a raw value with `_parse_scalar` (a plain scalar) or `_parse_flow_list` (a flow
    list) as appropriate for that key.
    """
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        key, _, rest = line.partition(":")
        result[key.strip()] = rest.strip()
    return result


def _require_scalar(raw: dict[str, str], key: str) -> str:
    if key not in raw:
        raise ValueError(f"frontmatter is missing required key {key!r}")
    value = _parse_scalar(raw[key])
    if value is None:
        raise ValueError(f"frontmatter key {key!r} must not be null")
    return value


def _parse_flow_list(raw: str) -> list[str]:
    """The inverse of `_render_flow_list`: split a `[item, item, ...]` flow list on top-level commas
    (i.e. commas outside a quoted item), then unquote each item with `_parse_scalar`.

    A naive `.split(",")` is not sufficient -- an item quoted because it itself needs escaping could
    (in principle) contain a comma inside its quotes, and splitting blindly would cut it in two. This
    walks the string once, tracking whether it is inside a `"`-delimited item, and only treats a comma
    as a separator when it is not.
    """
    text = raw.strip()
    if not (text.startswith("[") and text.endswith("]")):
        raise ValueError(f"expected a YAML flow list, got {raw!r}")
    inner = text[1:-1].strip()
    if not inner:
        return []

    tokens: list[str] = []
    buf: list[str] = []
    in_quotes = False
    for ch in inner:
        if ch == '"':
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == "," and not in_quotes:
            tokens.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tokens.append("".join(buf).strip())

    items: list[str] = []
    for token in tokens:
        parsed = _parse_scalar(token)
        items.append(parsed if parsed is not None else "")
    return items


def _extract_section(body: str, heading: str) -> str:
    """The text of a `## {heading}` body section, up to the next `## ` heading or end of file,
    stripped of the leading/trailing blank lines that separate sections. Identical to
    `app.personas.store._extract_section`."""
    marker = f"## {heading}"
    start = body.find(marker)
    if start == -1:
        return ""
    rest = body[start + len(marker) :]
    next_heading = rest.find("\n## ")
    section = rest[:next_heading] if next_heading != -1 else rest
    return section.strip("\n").strip()


def _parse_claims_section(section: str, *, path: Path, heading: str) -> list[ProfileClaim]:
    """The inverse of `_render_claims_body`.

    A line with no `[[note_id]]` citation is logged and skipped -- it can never become a `ProfileClaim`
    (its `citations` validator rejects an empty tuple), and dropping just that one claim rather than
    failing the whole file is the deliberate choice the module docstring explains. A line that does not
    even start with `"- "` is not a recognisable claim in any form and raises, which the caller (a
    `load_*`/`list_*` method) treats as the whole file being corrupt -- the same severity split
    `app.personas.store._parse_tickers_section` draws for its own body section.
    """
    claims: list[ProfileClaim] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("- "):
            raise ValueError(f"unparseable line in '## {heading}' section: {stripped!r}")
        line_body = stripped[2:]
        citations = tuple(_CITATION_RE.findall(line_body))
        text = _CITATION_RE.sub("", line_body).strip()
        if not citations:
            logger.warning(
                "profile store: skipping uncited claim line in '## %s' of %s: %r",
                heading,
                path,
                stripped,
            )
            continue
        claims.append(ProfileClaim(text=text, citations=citations))
    return claims


def _parse_regime_section(body: str) -> RegimeView | None:
    """The inverse of `_render_regime_section`. `None` both for a profile.md written before `regime`
    existed and for one whose `## Regime` section was omitted because `has_signal` was False --
    `_extract_section` returns `""` for a missing heading exactly like it does for `## Methodology`,
    so the two legacy/empty cases are indistinguishable here, which is the point: neither one has a
    macro view to report. Any section that IS present was, by construction, written with
    `has_signal=True` (see `_render_profile`), so that field is not read back from the file at all --
    it is set unconditionally on the returned view.
    """
    section = _extract_section(body, "Regime")
    if not section:
        return None
    raw = _split_frontmatter_lines(section)
    risk = _parse_scalar(raw.get("risk", "unclear")) or "unclear"
    rates = _parse_scalar(raw.get("rates", "")) or ""
    summary = _parse_scalar(raw.get("summary", "")) or ""
    return RegimeView(
        risk=cast("RiskPosture", risk),
        rates=rates,
        summary=summary,
        sectors_favoured=tuple(_parse_flow_list(raw.get("sectors_favoured", "[]"))),
        sectors_avoided=tuple(_parse_flow_list(raw.get("sectors_avoided", "[]"))),
        citations=tuple(_parse_flow_list(raw.get("citations", "[]"))),
        has_signal=True,
    )


def _parse_profile_file(path: Path, *, slug: str) -> PersonaProfile:
    """Parse one `profile.md` file back into a `PersonaProfile`.

    `path` is used both to read the file and to compute the returned `path` field -- there is no
    `path` key in the frontmatter, so the file's location on disk is the ground truth for it, the same
    rule `app.personas.store._parse_note_file` follows.
    """
    raw = path.read_text(encoding="utf-8")
    frontmatter_text, body = _split_frontmatter(raw)
    raw_fields = _split_frontmatter_lines(frontmatter_text)

    degraded_raw = raw_fields.get("degraded")
    degraded = degraded_raw is not None and _parse_scalar(degraded_raw) == "true"

    vocabulary = _parse_flow_list(raw_fields.get("vocabulary", "[]"))

    return PersonaProfile(
        persona=_require_scalar(raw_fields, "persona"),
        version=int(_require_scalar(raw_fields, "version")),
        consolidated_at=dt.datetime.fromisoformat(_require_scalar(raw_fields, "consolidated_at")),
        note_count=int(_require_scalar(raw_fields, "note_count")),
        summary=_extract_section(body, "Summary"),
        beliefs=tuple(_parse_claims_section(_extract_section(body, "Beliefs"), path=path, heading="Beliefs")),
        playbook=tuple(
            _parse_claims_section(_extract_section(body, "Playbook"), path=path, heading="Playbook")
        ),
        # `_extract_section` returns `""` both for an empty `## Methodology` section and for a
        # profile.md written before this field existed (no heading at all) -- `_parse_claims_section`
        # on `""` returns `[]` either way, so a legacy file loads with `methodology=()` with no
        # special-casing needed here.
        methodology=tuple(
            _parse_claims_section(_extract_section(body, "Methodology"), path=path, heading="Methodology")
        ),
        regime=_parse_regime_section(body),
        vocabulary=tuple(vocabulary),
        degraded=degraded,
        path=f"influencers/{slug}/{_PROFILE_FILE}",
    )


def _parse_thesis_file(path: Path, *, slug: str) -> TickerThesis:
    """Parse one `theses/<SYMBOL>.md` file back into a `TickerThesis`. Same "path is ground truth,
    not the frontmatter" rule as `_parse_profile_file`."""
    raw = path.read_text(encoding="utf-8")
    frontmatter_text, body = _split_frontmatter(raw)
    raw_fields = _split_frontmatter_lines(frontmatter_text)

    claims = _parse_claims_section(_extract_section(body, "Claims"), path=path, heading="Claims")

    return TickerThesis(
        persona=_require_scalar(raw_fields, "persona"),
        symbol=_require_scalar(raw_fields, "symbol"),
        stance=cast("Stance", _require_scalar(raw_fields, "stance")),
        updated_at=dt.datetime.fromisoformat(_require_scalar(raw_fields, "updated_at")),
        claims=tuple(claims),
        path=f"influencers/{slug}/{_THESES_DIRNAME}/{path.name}",
    )
