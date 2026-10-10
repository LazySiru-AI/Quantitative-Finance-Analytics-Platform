"""A tiny persistent translation cache: one JSON file per locale under `data/i18n_cache/`.

Load-on-read, write-through on set, dependency-free (stdlib `json`/`hashlib`/`pathlib` only) --
this is not a database, it is a flat `sha256(text) -> translated string` map sized for the handful of
narrative sentences a page renders, not for bulk translation.

**A cache failure never breaks translation.** Every file operation here is wrapped in try/except and
degrades to "no cache" (a miss on read, a silent no-op on write) rather than raising, because losing
the cache costs one extra model call per sentence while raising out of this module would take down
translation entirely for what is, at worst, a disk hiccup. `app.i18n.narrative` calls `get`/`set` in
its own try/except-free hot path precisely because this module has already absorbed that risk.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

__all__ = ["cache_key", "get_cached", "set_cached"]


def cache_key(text: str) -> str:
    """`sha256` hex digest of `text`, the cache's lookup key. Hashing rather than storing the raw
    English as the key keeps the JSON file's keys a fixed, filesystem- and diff-friendly shape."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cache_path(locale: str, *, data_dir: Path) -> Path:
    return data_dir / "i18n_cache" / f"{locale}.json"


def _load(locale: str, *, data_dir: Path) -> dict[str, str]:
    path = _cache_path(locale, data_dir=data_dir)
    try:
        if not path.is_file():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items()}
    except Exception:
        # Corrupt JSON, a permissions error, a half-written file mid-crash -- any of these degrade
        # to an empty cache rather than taking translation down with them.
        return {}


def get_cached(text: str, *, locale: str, data_dir: Path) -> str | None:
    """The cached translation for `text` under `locale`, or `None` on a miss (including any read
    failure, which is indistinguishable from a miss to a caller)."""
    cache = _load(locale, data_dir=data_dir)
    return cache.get(cache_key(text))


def set_cached(text: str, translated: str, *, locale: str, data_dir: Path) -> None:
    """Write `translated` into the on-disk cache for `(locale, text)`. Read-modify-write, since this
    is a small file meant for occasional narrative sentences, not a high-throughput store -- a lost
    write under concurrent access costs one re-translation, not correctness."""
    path = _cache_path(locale, data_dir=data_dir)
    try:
        cache = _load(locale, data_dir=data_dir)
        cache[cache_key(text)] = translated
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # Never let a cache write failure surface as a translation failure -- the caller already has
        # its translated string; this is purely an optimization for the next call.
        pass
