"""Layer B storage: one `ManagerSnapshot` per day per scope.

Mirrors `app.agentdesk.store.RunStore` on purpose -- same atomic-write idiom (a uuid-suffixed staging
file written in the snapshots directory, then a single `os.replace` onto the final name) and the same
tolerant `load` (a missing or corrupt file returns `None` and logs a warning rather than raising). That
is what lets an HTTP handler serving `/api/manager` read `latest()` while a collector is mid-write
without ever observing a torn file, and lets one bad day's snapshot degrade exactly that day instead of
taking down `list_dates`/`latest` for every other day.

One file per `(as_of, scope)` at `snapshot_path(settings, as_of, scope)` --
`data/agentdesk/manager/snapshots/<YYYY-MM-DD>.<scope>.json` -- so `list_dates` can recover the whole
history by listing the directory and parsing filenames; no separate index to keep in sync.

**Signatures below are pinned exactly as specified for this shard** (`save`, `load`, `latest`,
`list_dates`) -- another worker is coding the collector/API layer against them concurrently, so this
module must not change them, even if a concurrently-edited copy of this file is seen with a different
shape (e.g. `latest` returning a `(date, snapshot)` pair, or an extra `window_bounds` helper). That is
scope drift from elsewhere in the tree, not this shard's contract.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from pathlib import Path

from app.config import Settings
from app.manager.models import ManagerSnapshot, snapshot_path, snapshots_dir

__all__ = ["latest", "list_dates", "load", "save"]

logger = logging.getLogger(__name__)


def save(settings: Settings, snapshot: ManagerSnapshot) -> Path:
    """Write `snapshot` atomically and return the path it was written to.

    The staging file carries a uuid suffix rather than a fixed `.tmp` name -- matching
    `RunStore.save` -- so two concurrent writers (there should only ever be one collector per
    `(as_of, scope)`, but nothing here depends on that) can never collide on the same staging name
    before either reaches its own `os.replace`.
    """
    as_of = dt.date.fromisoformat(snapshot.as_of)
    directory = snapshots_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    path = snapshot_path(settings, as_of, snapshot.scope)
    staging = directory / f"{path.name}.{uuid.uuid4().hex}.tmp"
    staging.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
    os.replace(staging, path)
    return path


def load(settings: Settings, as_of: dt.date, scope: str) -> ManagerSnapshot | None:
    """The snapshot for `(as_of, scope)`, or `None` if it does not exist or cannot be parsed.

    Never raises -- a direct lookup by date is the caller's only answer for the day it asked about,
    so a corrupt file is reported as "no snapshot for that day" rather than crashing the caller, the
    same tolerance `RunStore.load` gives a corrupt `run.json`.
    """
    path = snapshot_path(settings, as_of, scope)
    if not path.is_file():
        return None
    try:
        return ManagerSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("manager snapshots: could not read %s: %s", path, exc)
        return None


def list_dates(settings: Settings, scope: str) -> tuple[dt.date, ...]:
    """Every date with a snapshot file for `scope`, newest first.

    Parses filenames rather than file contents -- cheap, and it means a corrupt snapshot still shows
    up in the list (its date is real even if `load` of it later returns `None`). A filename that does
    not match `<date>.<scope>.json` (a staging leftover, a junk file, a typo) is skipped and logged
    rather than raising.
    """
    directory = snapshots_dir(settings)
    if not directory.is_dir():
        return ()

    suffix = f".{scope}.json"
    dates: list[dt.date] = []
    for entry in directory.iterdir():
        if not entry.is_file() or not entry.name.endswith(suffix):
            continue
        date_part = entry.name[: -len(suffix)]
        try:
            dates.append(dt.date.fromisoformat(date_part))
        except ValueError:
            logger.warning("manager snapshots: skipping unparseable filename %s", entry.name)
            continue

    dates.sort(reverse=True)
    return tuple(dates)


def latest(settings: Settings, scope: str, *, before: dt.date | None = None) -> ManagerSnapshot | None:
    """The newest readable snapshot for `scope`, or the newest strictly before `before` when given.

    This is what powers "yesterday" and "last week" in the tab: `before` is the day being described,
    not literally T-1 or T-7, because a snapshot is not guaranteed to exist for every calendar day
    (a missed collect, a weekend, the desk being off) -- the nearest prior snapshot is the honest
    comparison point, not a date arithmetic guess. A snapshot file that exists but fails to parse is
    skipped in favour of the next-newest one, same tolerance as `load`.
    """
    dates = list_dates(settings, scope)
    if before is not None:
        dates = tuple(d for d in dates if d < before)
    for candidate in dates:  # already newest-first
        snap = load(settings, candidate, scope)
        if snap is not None:
            return snap
    return None
