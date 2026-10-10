"""The append-only event log and its `since` cursor.

**Append-only JSONL, one event per line, never rewritten.** `data/notify/events.jsonl` is the whole
store. There is no database because there is no query here worth one: the only read this feature has
is "everything after cursor X, newest last", which a forward scan answers exactly, and the file grows
by a handful of lines a day. Append-only also means a poller can never be shown an event that later
changes underneath it -- an id, once emitted, denotes one immutable line forever, which is the
property a `since` cursor needs to be trustworthy.

**`since` accepts an event id *or* an ISO timestamp**, because the two callers want different things
and neither should have to translate. A poller that has seen events hands back the last id it saw
and gets strictly what came after it -- exact, gap-free, and immune to two events sharing a
timestamp. A human (or a fresh client with no cursor) hands back a time and gets everything since
then. An id that is no longer in the file (pruned, or from another machine) degrades to "everything",
not to an error: a poller that has fallen too far behind should re-sync, not wedge.

**The seen set is a separate file from the log**, and that is deliberate rather than incidental. The
log is the record and must never be read to decide whether to write -- a dedupe check that scanned
`events.jsonl` would make every emit O(file), and would tie dedupe's retention to the log's. Instead
`seen.json` is a small id -> timestamp map, pruned to :data:`_SEEN_MAX` newest entries, so an id ages
out of *dedupe* long before the event ages out of the *log*. The practical consequence: a
`dedupe_id` that has not been emitted in a very long time may fire again. For the derived daily ids
that is the intent; for explicit ids (a `ChangeItem.id`, a `brief_id`) the horizon is thousands of
events, far past any window in which a re-announcement would be noise.

Writes are `"a"`-mode appends and a whole-file replace for the small JSON sidecars, guarded by a
process-local lock. This is a single-process server writing a few lines a day; cross-process
atomicity is not a problem this feature has, and pretending otherwise would buy nothing.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings

__all__ = ["NotifyEvent", "Severity", "emit", "last_dispatch", "list_since", "status"]

_log = logging.getLogger(__name__)

#: Same three-way ranking the manager desk's `ChangeItem.severity` uses (`app.manager.models`),
#: restated here rather than imported so that `app.notify` takes no dependency on the manager -- the
#: producers this serves next (fills, live decisions, promotions) have nothing to do with that
#: package, and a notification core that imports one of its producers is backwards.
Severity = Literal["attention", "notable", "fyi"]

#: Newest ids kept in the dedupe set. Roughly a year of a busy day's traffic; see the module
#: docstring for what ageing out of this set does and does not mean.
_SEEN_MAX = 5000

#: Serialises this process's appends. Not a cross-process lock -- see the module docstring.
_LOCK = threading.Lock()

#: The `sent` outcome of the most recent :func:`emit` in this process, as `(event_id, sent)`.
#: Exactly one entry, overwritten every emit. `POST /api/notify/test` is the only reader: it has to
#: answer "did that actually go out?", which the returned `NotifyEvent` cannot say (an event is
#: logged whether or not it is sent, which is the entire point of the log/send split).
_LAST_DISPATCH: tuple[str, bool] = ("", False)


class NotifyEvent(BaseModel):
    """One thing worth telling the owner about.

    Frozen and `extra="forbid"`: this shape is the wire contract for `GET /api/notify/events` and the
    on-disk line format at once, and every producer in the next shard codes against it, so a field
    added by accident in one caller must be a loud error rather than a silently persisted extra.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    ts: str
    """ISO-8601, UTC, timezone-suffixed. The sort key and the timestamp form of the `since` cursor."""

    kind: str
    """Dotted producer path -- `manager.change`, `manager.brief`, `paper.fill`, `signal.live`,
    `research.promotion`, `persona.note`, `data.stale`. The prefix before the first dot is the
    subsystem, which is what `notify_kinds`'s prefix matching filters on."""

    severity: Severity
    headline: str = Field(max_length=160)
    detail: str = Field(default="", max_length=320)
    refs: tuple[str, ...] = ()
    """Opaque pointers back at whatever produced this -- a run id, a note id, a symbol. Strings, not
    a typed model, because the consumers are a phone notification and a JSON poller, neither of
    which can follow a typed reference anywhere."""

    source: str = ""
    """Human-readable origin, e.g. `manager:account:cash_drift`. Diagnostic, not parsed."""


def _notify_dir(settings: Settings) -> Path:
    """`data/notify/`, created on demand.

    Derived from `settings.data_dir` locally rather than added as a `Settings` field, the same way
    `auth_db_path` derives from it: there is nothing an operator would want to relocate independently
    of the data root, and a subsystem that needs one directory should not widen the config surface to
    get it.
    """
    path = settings.data_dir / "notify"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _log_path(settings: Settings) -> Path:
    return _notify_dir(settings) / "events.jsonl"


def _seen_path(settings: Settings) -> Path:
    return _notify_dir(settings) / "seen.json"


def _read_seen(settings: Settings) -> dict[str, str]:
    path = _seen_path(settings)
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _log.warning("notify: unreadable seen set at %s; treating every id as new", path.name)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_seen(settings: Settings, seen: dict[str, str]) -> None:
    if len(seen) > _SEEN_MAX:
        newest = sorted(seen.items(), key=lambda kv: kv[1])[-_SEEN_MAX:]
        seen = dict(newest)
    _seen_path(settings).write_text(json.dumps(seen), encoding="utf-8")


def _derived_id(kind: str, headline: str, now: dt.datetime) -> str:
    """`sha256(kind|headline|UTC-date)[:16]` -- see the module docstring for why the date is in it."""
    material = f"{kind}|{headline}|{now.date().isoformat()}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def emit(
    settings: Settings,
    *,
    kind: str,
    severity: Severity,
    headline: str,
    detail: str = "",
    refs: tuple[str, ...] = (),
    source: str = "",
    dedupe_id: str | None = None,
) -> NotifyEvent | None:
    """Log one event and offer it to the sender. Returns the event, or `None` if it was a duplicate.

    `None` is the *normal* answer for a producer on a loop and means "already announced", not
    "failed". Nothing here raises for a delivery problem: `sender.dispatch` runs inside a `try` and
    its failures are logged, because a phone that cannot be reached must never break the snapshot,
    brief or fill that was being reported.
    """
    global _LAST_DISPATCH

    now = dt.datetime.now(dt.UTC)
    event_id = dedupe_id or _derived_id(kind, headline, now)

    with _LOCK:
        seen = _read_seen(settings)
        if event_id in seen:
            return None

        event = NotifyEvent(
            id=event_id,
            ts=now.isoformat(),
            kind=kind,
            severity=severity,
            headline=headline[:160],
            detail=detail[:320],
            refs=tuple(refs),
            source=source,
        )
        with _log_path(settings).open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
        seen[event_id] = event.ts
        _write_seen(settings, seen)

    sent = False
    try:
        from app.notify import sender

        sent = sender.dispatch(settings, event)
    except Exception:
        _log.exception("notify: sender raised on event %s (%s); event is logged", event.id, kind)
    _LAST_DISPATCH = (event.id, sent)
    return event


def last_dispatch(event_id: str) -> bool:
    """Whether `event_id` was this process's most recent :func:`emit` *and* its sender sent it."""
    seen_id, sent = _LAST_DISPATCH
    return sent and seen_id == event_id


def _read_all(settings: Settings) -> list[NotifyEvent]:
    """Every logged event, oldest first. A malformed line is skipped, not fatal -- one bad append
    must not make the whole feed unreadable."""
    path = _log_path(settings)
    if not path.exists():
        return []
    events: list[NotifyEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(NotifyEvent.model_validate_json(line))
        except Exception:
            _log.warning("notify: skipping unparseable line in events.jsonl")
    return events


def list_since(
    settings: Settings, *, since: str | None = None, limit: int = 200
) -> list[NotifyEvent]:
    """Events after `since`, oldest first (newest last), at most `limit` of them.

    `since` is either an event id or an ISO-8601 timestamp; an id that is not in the log is treated
    as "no cursor" rather than as an error (see the module docstring). With no cursor at all the
    *newest* `limit` events come back -- a fresh client wants the recent tail, not the ancient head.
    """
    events = _read_all(settings)
    if not since:
        return events[-limit:] if limit > 0 else []

    for index, event in enumerate(events):
        if event.id == since:
            return events[index + 1 :][:limit]

    # Not an id we know: read it as a timestamp. Compared as strings, which is correct for
    # timezone-suffixed ISO-8601 in a single zone -- every `ts` written here is UTC.
    tail = [event for event in events if event.ts > since]
    return tail[:limit]


def status(settings: Settings) -> dict[str, Any]:
    """The feature's one-glance state: what is configured, how much has been logged, and how much
    the policy actually let through today. Reads the sender's counters rather than keeping its own,
    so "logged" and "sent" can never drift apart in the report."""
    from app.notify import sender

    events = _read_all(settings)
    counters = sender.today_counters(settings)
    return {
        "enabled": settings.notify_enabled,
        "channel": settings.notify_channel,
        "total": len(events),
        "last_event_ts": events[-1].ts if events else None,
        "last_sent_ts": sender.last_sent_ts(settings),
        "sent_today": counters["sent"],
        "suppressed_today": counters["suppressed"],
    }
