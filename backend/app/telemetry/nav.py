"""Navigation-hit log: one JSON line per SPA route change, so the owner can see which pages and tabs
are actually used.

**Local and privacy-light by construction.** Nothing here makes a network call, and a hit carries
only ``path``, ``tab``, ``role`` and a timestamp -- never a username, an IP, or a user id. ``role``
is one of ``"owner"``, ``"member"`` or ``"anon"`` (see ``app.api.telemetry_nav``'s role resolution),
which is enough to tell "the owner's own usage" from "a member's" without identifying which member.

**Append-only JSONL, not a table.** The write path is one ``open(..., "a")`` per batch, and the read
path (`summary`) is a full scan of the file. That is the right trade for what this log is used for:
a handful of route changes per page view, read back at most once per Data > Health page load, never
queried by anything else. A SQLite table would need a migration and an index for a workload this
small; a text file that `tail` can read is easier to reason about and just as fast at this size.

Every function here takes ``settings`` explicitly rather than calling ``get_settings()`` itself, so a
caller (the router, a test) controls exactly which tree is touched -- the same convention every other
module under ``app.telemetry``'s sibling data-writing modules follows.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.config import Settings

#: Hard caps on what a single hit may carry -- generous for any real route/query-param combination
#: in this app, tight enough that a malformed or hostile client can't turn one request into an
#: unbounded write.
_MAX_PATH_LEN = 200
_MAX_TAB_LEN = 60
#: How many events a single `record()` call will ever write, regardless of how many are passed in --
#: the batch the frontend sends is a handful of route changes accumulated over a 10s window, so
#: anything past this is either a bug upstream or an attempt to flood the log.
_MAX_EVENTS_PER_CALL = 100


class NavHit(BaseModel):
    """One route-change event, ready to append. ``ts`` is an ISO-8601 string (the frontend's
    `new Date().toISOString()`), not a `datetime`, so a malformed timestamp fails validation in
    `summary()`'s parse rather than at construction -- the log should still gain the line."""

    ts: str
    path: str
    tab: str | None = None
    role: str


def _nav_path(settings: Settings) -> Path:
    return settings.data_dir / "telemetry" / "nav.jsonl"


def _valid(hit: NavHit) -> bool:
    if not hit.path.startswith("/") or len(hit.path) > _MAX_PATH_LEN:
        return False
    return not (hit.tab is not None and len(hit.tab) > _MAX_TAB_LEN)


def record(settings: Settings, events: Iterable[NavHit]) -> int:
    """Append one JSON line per valid event in ``events``, capped at ``_MAX_EVENTS_PER_CALL``.

    Returns the number of lines actually written -- fewer than ``len(events)`` when some were
    invalid (or the batch was capped), zero when none were. Never raises on a bad individual event;
    it is simply dropped, matching this log's job of being useful, not authoritative.
    """
    batch = list(events)[:_MAX_EVENTS_PER_CALL]
    lines = [
        json.dumps({"ts": hit.ts, "path": hit.path, "tab": hit.tab, "role": hit.role})
        for hit in batch
        if _valid(hit)
    ]
    if not lines:
        return 0

    path = _nav_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")
    return len(lines)


def _parse_ts(raw: Any) -> dt.datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def summary(settings: Settings, *, days: int = 30) -> dict[str, Any]:
    """Roll the last ``days`` days of the log up into per-``(path, tab)`` hit counts.

    A malformed line (bad JSON, a missing or unparsable ``ts``) is skipped rather than raising --
    the log is written by this same module so that should not happen, but a summary must never 500
    the Data > Health page over one bad line an out-of-band edit introduced.
    """
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    path = _nav_path(settings)

    routes: dict[tuple[str, str | None], dict[str, Any]] = {}
    total = 0

    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    obj = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue

                ts = _parse_ts(obj.get("ts"))
                if ts is None or ts < since:
                    continue
                route_path = obj.get("path")
                if not isinstance(route_path, str):
                    continue
                tab = obj.get("tab")
                if tab is not None and not isinstance(tab, str):
                    tab = None

                key = (route_path, tab)
                entry = routes.get(key)
                if entry is None:
                    entry = {"path": route_path, "tab": tab, "hits": 0, "last_ts": obj.get("ts")}
                    routes[key] = entry
                entry["hits"] += 1
                if isinstance(obj.get("ts"), str) and obj["ts"] > entry["last_ts"]:
                    entry["last_ts"] = obj["ts"]
                total += 1

    ordered = sorted(routes.values(), key=lambda r: r["hits"], reverse=True)
    return {
        "days": days,
        "since": since.isoformat(),
        "total": total,
        "routes": ordered,
    }
