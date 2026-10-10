"""Symbol -> sector label lookup, backed by the hand-maintained ``data/sectors.toml``.

There is no sector data anywhere in this application, and the market data provider cannot supply
one either: :mod:`app.market.providers.yahoo` gets everything from the single
``/v8/finance/chart/{symbol}`` endpoint, whose metadata carries no sector field. Yahoo's richer
``quoteSummary`` endpoint does carry one, but it needs a crumb this app does not fetch. So the
mapping lives in a flat, hand-edited TOML file instead -- see that file's own header comment for the
frozen vocabulary and the classification rules a human editing it should follow.

**This module must never raise.** A sector label is cosmetic -- worth showing when available, never
worth taking a portfolio page down over. A missing file, a malformed one, or a symbol nobody has
classified yet all resolve the same way: :data:`UNCLASSIFIED`.
"""

from __future__ import annotations

import re
import time
import tomllib
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Final

from app.config import Settings, get_settings
from app.datasource import DataServiceError, read_document, write_document

__all__ = [
    "SECTOR_VOCABULARY",
    "UNCLASSIFIED",
    "load_sector_map",
    "sector_for",
    "set_sector",
]

#: Label for a symbol with no entry in `data/sectors.toml`, or used when the file itself could not
#: be read at all. Also part of the frozen sector vocabulary (see `data/sectors.toml`'s header).
UNCLASSIFIED: Final[str] = "Unclassified"

#: Conventional filename, resolved inside `settings.data_dir` -- same pattern as
#: `app.ingest.manifest.MANIFEST_FILENAME`.
SECTORS_FILENAME: Final[str] = "sectors.toml"

#: The frozen sector vocabulary, spelled exactly as `data/sectors.toml`'s own header comment
#: documents it -- that comment is the source of truth a human maintainer reads; this tuple is its
#: machine-checkable mirror, used to validate `set_sector` and to tell a client what it may offer.
SECTOR_VOCABULARY: Final[tuple[str, ...]] = (
    "MEMORY",
    "CRYPTO",
    "SEMI",
    "BIG TECH",
    "SPACE",
    "AI & ROBOTICS",
    "ENERGY",
    "FINANCIALS",
    "SOFTWARE",
    "AUTO/EV",
    "HARDWARE",
    "COMMODITIES",
    "HEALTHCARE",
    "CONSUMER",
    "INDUSTRIALS",
    "REAL ESTATE",
    "BROAD MARKET",
    "BONDS & CASH",
    "INTERNATIONAL",
    UNCLASSIFIED,
)


def _parse_table(raw_toml: str) -> dict[str, str]:
    """Parse the `[sectors]` table out of raw TOML text into a symbol(upper) -> label mapping.

    Never raises: `tomllib.loads` can fail with `TOMLDecodeError` on invalid TOML, and a `[sectors]`
    table missing or not actually a table both degrade to an empty mapping, exactly like a symbol
    with no entry at all -- see the module docstring for why. Shared by the cached file reader below
    and by `set_sector`'s own pre-write read of whatever is currently on disk.
    """
    try:
        raw = tomllib.loads(raw_toml)
    except Exception:
        return {}

    table = raw.get("sectors")
    if not isinstance(table, dict):
        return {}

    result: dict[str, str] = {}
    for symbol, label in table.items():
        if isinstance(symbol, str) and isinstance(label, str):
            result[symbol.upper()] = label
    return result


@lru_cache(maxsize=8)
def _load_map_cached(path: Path) -> Mapping[str, str]:
    """The real parse, cached per resolved path so a hot per-position lookup never re-reads the
    file from disk. Keyed on `path` rather than nothing, so a test pointing at a `tmp_path` fixture
    never sees another test's (or the real repo's) cached content.

    Never raises: `path.read_text` can fail with `OSError` (missing file, permissions) or
    `UnicodeDecodeError` (bad encoding), and `_parse_table` never raises either. Both degrade to an
    empty mapping. `set_sector` below is what invalidates this cache after a write -- see its
    docstring.
    """
    try:
        raw_toml = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    return _parse_table(raw_toml)


@lru_cache(maxsize=8)
def _parse_cached(raw_toml: str) -> Mapping[str, str]:
    """`_parse_table` memoised on the document *content*. Keyed on the text itself, so a write is
    visible to the very next read, and a test that points `data_dir` at a tmp dir gets its own data
    without any invalidation."""
    return _parse_table(raw_toml)


#: Remote mode only: `(fetched_at, text)` per data-service URL. A per-position `sector_for` would
#: otherwise be one HTTP round trip per symbol. Local/demo reads are a small file read and are not
#: cached here. `set_sector` clears it so a write is visible immediately.
_REMOTE_TTL_S: Final[float] = 30.0
_remote_text: dict[str, tuple[float, str | None]] = {}


def _document_text(cfg: Settings) -> str | None:
    """The sectors document, or `None` if never written / unreadable. Never raises."""
    try:
        if cfg.data_source != "remote":
            return read_document("sectors", cfg)
        hit = _remote_text.get(cfg.db_service_url)
        if hit is not None and time.monotonic() - hit[0] < _REMOTE_TTL_S:
            return hit[1]
        text = read_document("sectors", cfg)
        _remote_text[cfg.db_service_url] = (time.monotonic(), text)
        return text
    except (DataServiceError, OSError, UnicodeDecodeError):
        return None


def load_sector_map(
    path: Path | None = None, *, settings: Settings | None = None
) -> Mapping[str, str]:
    """Symbol (upper) -> sector label. Reads the `sectors` document (`data/sectors.toml`). Cached.

    With no `path`, the document comes from the data source of `settings` (default: the
    process-wide settings), so local, demo and remote mode all read through
    :mod:`app.datasource`. An explicit `path` reads that file directly and is kept for callers
    that want a specific file.
    """
    if path is not None:
        return _load_map_cached(path)
    text = _document_text(settings or get_settings())
    return _parse_cached(text) if text is not None else {}


def sector_for(symbol: str, *, settings: Settings | None = None) -> str:
    """The sector label for `symbol`, or `UNCLASSIFIED`. Never raises, never returns `None`."""
    cfg = settings or get_settings()
    sector_map = load_sector_map(settings=cfg)
    return sector_map.get(symbol.upper(), UNCLASSIFIED)


# ---------------------------------------------------------------------------
# Writing: upsert one symbol's classification, preserving the hand-written header
# ---------------------------------------------------------------------------

#: Used only when `data/sectors.toml` is missing or unparseable enough that no header can be
#: recovered from it at all -- so a rewrite in that situation still leaves *some* explanation
#: behind rather than a bare `[sectors]` table with no context.
_MINIMAL_HEADER = (
    "# Hand-maintained sector labels, keyed by ticker symbol. See app.market.sectors.sector_for "
    "for how a symbol with no entry here resolves, and set_sector for how this file is written.\n"
)

#: TOML bare-key charset (letters, digits, underscore, hyphen). A symbol outside it -- `BRK.B` is
#: a common one -- must be quoted or the dot would parse as a dotted key.
_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _split_header(text: str) -> str:
    """Everything above the `[sectors]` table marker, verbatim -- this is the frozen-vocabulary and
    classification-rules documentation a human maintainer relies on, and a rewrite must never drop
    it. Falls back to `_MINIMAL_HEADER` when the file is empty/missing or has no `[sectors]` marker
    to split on (an unexpected shape, but still handled without losing whatever *is* there when it
    is non-blank).
    """
    marker_idx = text.find("[sectors]")
    if marker_idx == -1:
        return text if text.strip() else _MINIMAL_HEADER
    return text[:marker_idx]


#: TOML basic strings forbid literal control characters (anything below U+0020, other than the
#: named escapes below) -- one of these in a symbol or label would otherwise produce a file
#: `tomllib.loads` cannot parse back, which is exactly the file this module's own read side must
#: tolerate (see the module docstring's "never raise" contract) rather than choke on because the
#: write side put it there. Named escapes for the common three; everything else below 0x20 goes out
#: as a `\uXXXX` escape, per the TOML spec.
_CONTROL_ESCAPES: Final[dict[str, str]] = {
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}


def _quote(value: str) -> str:
    """A basic TOML string literal for `value`: backslashes and double quotes are escaped, and every
    control character (below U+0020) is escaped too -- named escapes for the common ones, `\\uXXXX`
    for the rest -- so a symbol or label that happens to contain one (a stray newline pasted from a
    label field, say) can never produce a file this module's own reader cannot parse back.
    """
    out: list[str] = []
    for ch in value.replace("\\", "\\\\").replace('"', '\\"'):
        if ch == "\\" or ord(ch) >= 0x20:
            out.append(ch)
        elif ch in _CONTROL_ESCAPES:
            out.append(_CONTROL_ESCAPES[ch])
        else:
            out.append(f"\\u{ord(ch):04x}")
    return '"' + "".join(out) + '"'


def _format_key(symbol: str) -> str:
    """`symbol` as a TOML key: bare when it fits the bare-key charset, quoted otherwise."""
    return symbol if _BARE_KEY_RE.match(symbol) else _quote(symbol)


def _render(header: str, table: Mapping[str, str]) -> str:
    """Rebuild the file text: the preserved `header`, then `[sectors]` and one sorted
    `SYMBOL = "LABEL"` line per entry.

    Normalizes the boundary between header and table to exactly one blank line, so the fallback
    `_MINIMAL_HEADER` (a single line, no trailing blank) reads the same as a header recovered from
    a real file (which already ends with one, since that blank line sits between the header's prose
    and the original `[sectors]` line and `_split_header` keeps it as part of the header).
    """
    if not header.endswith("\n"):
        header += "\n"
    if header.strip() and not header.endswith("\n\n"):
        header += "\n"

    lines = [f"{_format_key(symbol)} = {_quote(label)}" for symbol, label in sorted(table.items())]
    body = "\n".join(lines)
    return f"{header}[sectors]\n{body}\n" if body else f"{header}[sectors]\n"


def set_sector(symbol: str, sector: str, *, settings: Settings | None = None) -> str:
    """Upsert `symbol` -> `sector` into `data/sectors.toml` and invalidate the read cache so the
    next `sector_for`/`load_sector_map` call sees it immediately. Returns the stored label.

    Raises `ValueError` if `sector` is not one of `SECTOR_VOCABULARY` -- unlike the read side, this
    function has no "never raise" contract, because writing bad data into the one source of truth
    is exactly the case worth failing loudly on rather than degrading quietly.

    Setting `sector` to `UNCLASSIFIED` removes the symbol's entry entirely rather than writing
    `SYMBOL = "Unclassified"`: "no entry" and "explicitly Unclassified" already mean the same thing
    to every reader (`sector_for`'s default), so there is nothing worth persisting.

    The file's header comment -- the frozen-vocabulary and classification-rules documentation a
    human maintainer relies on -- is preserved verbatim; see `_split_header`. The table itself is
    always rebuilt sorted by symbol, so a diff of this file after an edit shows only the one entry
    that actually changed.
    """
    if sector not in SECTOR_VOCABULARY:
        raise ValueError(
            f"{sector!r} is not part of the frozen sector vocabulary: "
            f"{', '.join(SECTOR_VOCABULARY)}"
        )

    cfg = settings or get_settings()
    symbol = symbol.upper()

    # A fresh read, never the remote TTL cache: this is read-modify-write. A data-service failure
    # propagates (503) rather than silently rewriting the document from an empty table.
    text = read_document("sectors", cfg) or ""

    header = _split_header(text)
    table = _parse_table(text)

    if sector == UNCLASSIFIED:
        table.pop(symbol, None)
    else:
        table[symbol] = sector

    write_document("sectors", _render(header, table), cfg)

    _load_map_cached.cache_clear()
    _remote_text.clear()
    return sector
