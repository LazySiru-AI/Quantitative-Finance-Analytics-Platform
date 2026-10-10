"""The notification core: an append-only event log, a policy-filtered sender, and nothing else.

**One `emit()` for the whole application.** Every producer that wants to tell the owner something --
the manager desk's change feed and daily brief today; paper fills, live decisions, research
promotions, persona notes and data-freshness alarms in the next shard -- calls
:func:`app.notify.emit` and stops there. It never decides whether a phone should buzz, what a quiet
hour is, or which channel is configured; that is :mod:`app.notify.sender`'s job alone, driven
entirely by settings. A producer's only responsibility is to describe what happened.

**Logging and sending are deliberately separate.** `emit()` appends to `data/notify/events.jsonl`
*unconditionally* -- even with `notify_enabled` off, which is the default -- and only then asks the
sender whether that event also goes out over a channel. That split is what makes the feature safe to
land with delivery switched off: the log fills up, `GET /api/notify/events` and the polling cursor
can be exercised end to end, and turning delivery on later is one `.env` line rather than a leap of
faith. It is also why a delivery failure can never be a producer's problem -- `dispatch` is called
inside a `try` and its exceptions are logged, never re-raised.

**Dedupe is by event id, and the id is derived, not random.** An event with no explicit `dedupe_id`
is keyed on `kind|headline|today` (UTC), so a producer that runs on a loop -- a snapshot taken three
times in an afternoon, a freshness sweep every hour -- announces a given thing once a day rather
than once a tick. A producer that already has a stable identity for the thing (a `ChangeItem.id`, a
`brief_id`, a fill id) passes it as `dedupe_id` and gets exact-once semantics for free.

The public surface is `emit`, `list_since` and `status`, re-exported here so callers write
`from app.notify import emit`. See `docs/NOTIFY-RUNBOOK.md` for the operator's side.
"""

from __future__ import annotations

from app.notify.events import NotifyEvent, Severity, emit, list_since, status

__all__ = ["NotifyEvent", "Severity", "emit", "list_since", "status"]
