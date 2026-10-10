"""Delivery: the policy that decides whether an event goes out, and the channel that takes it there.

**All of the judgement in this feature lives here, and all of it comes from settings.** A producer
says what happened; this module says whether that is worth a buzz right now. Keeping the two apart is
what lets the next shard add five more producers without any of them re-deciding what a quiet hour
is, and what lets the owner retune every producer at once by editing one `.env` line.

The policy is five gates, in this order, and the order is the design:

1. **`notify_enabled`** -- off by default. Everything is still logged; nothing is sent. This is the
   state the feature ships in, so a fresh deployment cannot page anyone by surprise.
2. **`notify_min_severity`** -- `"notable"` by default, which sends `attention` and `notable` and
   drops `fyi`. The `fyi` tier exists so producers can be generous in the *log* without that
   generosity reaching a phone.
3. **`notify_kinds`** -- empty means all. Otherwise a comma list matched by prefix, so `paper.`
   subscribes to every fill without enumerating them and `manager.brief` subscribes to exactly one
   thing. Prefix matching is why `kind` is dotted.
4. **`notify_quiet_hours`** -- `22:00-07:00` America/New_York by default, wrapping midnight.
   **`attention` overrides it**: the whole point of a top severity is that it is the one thing worth
   waking someone for, and a quiet-hours rule with no override would either have to be off or would
   silently swallow the only events that justify the feature.
5. **`notify_rate_cap_per_hour`** -- 20 in a rolling hour, counted from a state file. This is the
   backstop against the failure mode that actually destroys a notification channel: a producer bug
   that emits in a loop. The cap suppresses rather than queues, deliberately -- a hundred deferred
   notifications arriving at once is the same disaster one hour later.

Both channels are total functions that return a bool and never raise. `"log"`, the default, writes
the event at `INFO` and reports success, which makes the whole policy testable and observable with
delivery hardware entirely absent. `"ntfy"` POSTs to a public topic URL; a topic name is the only
secret involved, which is why the runbook is emphatic about choosing an unguessable one.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings
from app.notify.events import NotifyEvent

__all__ = ["dispatch", "last_sent_ts", "today_counters"]

_log = logging.getLogger(__name__)

#: The zone every wall-clock decision here is made in -- quiet hours, and the day boundary
#: `sent_today`/`suppressed_today` are counted against. Market hours are this zone and so is the
#: owner, so "today" and "night" mean the same thing to the policy as to the person reading it.
_ZONE = ZoneInfo("America/New_York")

#: Severity ordering. Higher sends more readily; `notify_min_severity` names the floor.
_RANK: dict[str, int] = {"attention": 3, "notable": 2, "fyi": 1}

#: ntfy's priority scale, per severity. 5 is its "high" (bypasses some do-not-disturb settings), 3
#: its default, 2 its "low" (no sound).
_PRIORITY: dict[str, str] = {"attention": "5", "notable": "3", "fyi": "2"}

#: HTTP timeout for a channel POST. Short on purpose: a producer is waiting on this call, and a
#: notification that is five seconds late is worthless anyway.
_TIMEOUT_S = 5.0


def _now() -> dt.datetime:
    """The wall clock, as one seam.

    Every time-dependent decision here -- quiet hours, the rolling-hour window, the day a counter is
    filed under -- goes through this function, so a test can freeze the clock by patching one name
    instead of the `datetime` module (patching that globally would reach every other module in the
    process, including the ones writing the timestamps being asserted).
    """
    return dt.datetime.now(dt.UTC)


def _state_path(settings: Settings) -> Path:
    path = settings.data_dir / "notify"
    path.mkdir(parents=True, exist_ok=True)
    return path / "sender_state.json"


def _read_state(settings: Settings) -> dict[str, Any]:
    path = _state_path(settings)
    if not path.exists():
        return {"sends": [], "last_sent_ts": None, "days": {}}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _log.warning("notify: unreadable sender state at %s; starting a fresh one", path.name)
        return {"sends": [], "last_sent_ts": None, "days": {}}
    if not isinstance(loaded, dict):
        return {"sends": [], "last_sent_ts": None, "days": {}}
    loaded.setdefault("sends", [])
    loaded.setdefault("last_sent_ts", None)
    loaded.setdefault("days", {})
    return loaded


def _write_state(settings: Settings, state: dict[str, Any], *, now: dt.datetime) -> None:
    """Persist, pruning both growing collections. `sends` keeps two hours (the rolling-hour window
    plus slack); `days` keeps a week, which is all `status()` ever shows."""
    send_cutoff = (now - dt.timedelta(hours=2)).isoformat()
    state["sends"] = [ts for ts in state.get("sends", []) if ts >= send_cutoff]
    day_cutoff = (now.astimezone(_ZONE).date() - dt.timedelta(days=7)).isoformat()
    state["days"] = {d: v for d, v in state.get("days", {}).items() if d >= day_cutoff}
    _state_path(settings).write_text(json.dumps(state), encoding="utf-8")


def _bump(settings: Settings, *, field: str, now: dt.datetime, sent_ts: str | None = None) -> None:
    state = _read_state(settings)
    day = now.astimezone(_ZONE).date().isoformat()
    counters = state["days"].setdefault(day, {"sent": 0, "suppressed": 0})
    counters[field] = int(counters.get(field, 0)) + 1
    if sent_ts is not None:
        state["last_sent_ts"] = sent_ts
        state["sends"].append(sent_ts)
    _write_state(settings, state, now=now)


def today_counters(settings: Settings) -> dict[str, int]:
    """Today's (America/New_York) `sent` and `suppressed` totals, both `0` before anything happens."""
    state = _read_state(settings)
    day = _now().astimezone(_ZONE).date().isoformat()
    counters = state.get("days", {}).get(day, {})
    return {
        "sent": int(counters.get("sent", 0)),
        "suppressed": int(counters.get("suppressed", 0)),
    }


def last_sent_ts(settings: Settings) -> str | None:
    """When this deployment last actually delivered something, or `None`."""
    value = _read_state(settings).get("last_sent_ts")
    return value if isinstance(value, str) else None


def _parse_quiet_hours(raw: str) -> tuple[dt.time, dt.time] | None:
    """`"22:00-07:00"` -> `(22:00, 07:00)`. Empty or malformed -> `None` (no quiet hours).

    Malformed is treated as absent rather than as an error because the failure mode matters: a typo
    in this setting must not silently *suppress* notifications, and it must not crash a producer. It
    means "no quiet window", which is the loud, visible outcome.
    """
    text = raw.strip()
    if not text or "-" not in text:
        return None
    start_raw, _, end_raw = text.partition("-")
    try:
        return dt.time.fromisoformat(start_raw.strip()), dt.time.fromisoformat(end_raw.strip())
    except ValueError:
        _log.warning("notify: could not parse notify_quiet_hours=%r; treating as none", raw)
        return None


def _in_quiet_hours(window: tuple[dt.time, dt.time], now_local: dt.time) -> bool:
    start, end = window
    if start == end:
        return False
    if start < end:  # a same-day window, e.g. 01:00-05:00
        return start <= now_local < end
    return now_local >= start or now_local < end  # wraps midnight, the default 22:00-07:00


def _kind_allowed(raw: str, kind: str) -> bool:
    wanted = [entry.strip() for entry in raw.split(",") if entry.strip()]
    if not wanted:
        return True
    return any(kind == entry or kind.startswith(entry) for entry in wanted)


def _suppress(settings: Settings, event: NotifyEvent, reason: str, now: dt.datetime) -> bool:
    _log.info("notify: suppressed %s (%s): %s", event.id, reason, event.headline)
    _bump(settings, field="suppressed", now=now)
    return False


def dispatch(settings: Settings, event: NotifyEvent) -> bool:
    """Apply the policy, then the channel. `True` only if the event actually went out.

    Never raises: every caller is a producer mid-transaction (a snapshot, a brief, a fill) for which
    a notification is a side effect, so every failure path here ends in a logged `False`.
    """
    now = _now()

    if not settings.notify_enabled:
        return _suppress(settings, event, "notify_enabled is off", now)

    floor = _RANK.get(settings.notify_min_severity.strip().lower(), _RANK["notable"])
    if _RANK.get(event.severity, 0) < floor:
        return _suppress(settings, event, f"below min severity {settings.notify_min_severity}", now)

    if not _kind_allowed(settings.notify_kinds, event.kind):
        return _suppress(settings, event, f"kind {event.kind} not subscribed", now)

    window = _parse_quiet_hours(settings.notify_quiet_hours)
    if (
        window is not None
        and event.severity != "attention"
        and _in_quiet_hours(window, now.astimezone(_ZONE).time())
    ):
        return _suppress(settings, event, "quiet hours", now)

    cap = settings.notify_rate_cap_per_hour
    if cap > 0:
        hour_ago = (now - dt.timedelta(hours=1)).isoformat()
        recent = [ts for ts in _read_state(settings).get("sends", []) if ts >= hour_ago]
        if len(recent) >= cap:
            return _suppress(settings, event, f"rate cap {cap}/hour reached", now)

    channel = settings.notify_channel.strip().lower()
    if channel == "ntfy":
        delivered = _send_ntfy(settings, event)
    elif channel == "log":
        delivered = _send_log(event)
    else:
        _log.warning("notify: unknown notify_channel=%r; nothing sent", settings.notify_channel)
        delivered = False

    if not delivered:
        _bump(settings, field="suppressed", now=now)
        return False
    _bump(settings, field="sent", now=now, sent_ts=now.isoformat())
    return True


def _send_log(event: NotifyEvent) -> bool:
    """The default channel: write the event to the application log. Always succeeds.

    Not a stub. It is how the policy is exercised in tests and in a deployment that has not chosen a
    channel yet, and it is a genuinely useful destination when the server's log is already being
    watched.
    """
    _log.info(
        "notify[%s] %s: %s%s",
        event.severity,
        event.kind,
        event.headline,
        f" -- {event.detail}" if event.detail else "",
    )
    return True


def _ascii(text: str) -> str:
    """HTTP header values are latin-1 at best and ntfy reads `Title` as ASCII. The corpus behind
    several producers here is Korean, so a headline that cannot be encoded is transliterated to `?`
    rather than allowed to raise -- a degraded title still delivers; an exception delivers nothing.
    """
    return text.encode("ascii", "replace").decode("ascii")


def _send_ntfy(settings: Settings, event: NotifyEvent) -> bool:
    """POST the event to `{notify_ntfy_url}/{notify_ntfy_topic}`.

    The topic name is the only access control ntfy's public server has, so an unset topic is a
    configuration error rather than a default worth guessing at -- it returns `False` loudly instead
    of publishing to some shared name.
    """
    topic = settings.notify_ntfy_topic.strip()
    if not topic:
        _log.warning("notify: notify_channel=ntfy but notify_ntfy_topic is empty; nothing sent")
        return False

    url = f"{settings.notify_ntfy_url.rstrip('/')}/{topic}"
    body = (event.detail or event.headline).encode("utf-8")
    headers = {
        "Title": _ascii(event.headline),
        "Priority": _PRIORITY.get(event.severity, "3"),
        "Tags": _ascii(event.kind),
    }
    try:
        response = httpx.post(url, content=body, headers=headers, timeout=_TIMEOUT_S)
        if response.status_code >= 400:
            _log.warning("notify: ntfy returned %s for event %s", response.status_code, event.id)
            return False
    except Exception as exc:
        _log.warning("notify: ntfy POST failed for event %s: %s", event.id, exc)
        return False
    return True
