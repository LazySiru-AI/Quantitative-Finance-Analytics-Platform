"""Notification HTTP surface: the poller's feed, the operator's status page, and a test button.

Three routes, all thin -- everything they do is in `app.notify.events`. `/api/notify` is owner-only
via `app.auth.gate.OWNER_ONLY_PREFIXES` (the feed carries account and tax headlines), with one
deliberate exception: `GET /events` and `GET /status` are also reachable with the read-only
`notify_service_token` bearer, so a phone shortcut or a cron can poll without holding a browser
session. That exception is implemented in the gate, not here -- a router that re-implemented auth
would be a second place for it to be wrong.

Lives in `app/notify/api.py` rather than `app/api/notify.py`, unlike most routers here, because this
package is self-contained and the sibling shards that will add producers should find the whole
feature in one directory.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.config import get_settings
from app.notify import events

router = APIRouter(prefix="/api/notify", tags=["notify"])


class EventsResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    events: list[events.NotifyEvent]


class TestResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sent: bool
    """Whether the policy and channel actually delivered it -- `False` is the expected answer while
    `notify_enabled` is off, and the event is logged either way."""

    event_id: str


@router.get("/events", response_model=EventsResponse)
def get_events(since: str | None = None, limit: int = 200) -> EventsResponse:
    """The feed. `since` is an event id or an ISO timestamp; newest last. Poll by handing back the
    `id` of the last event you saw."""
    return EventsResponse(
        events=events.list_since(get_settings(), since=since, limit=max(1, min(limit, 1000)))
    )


@router.get("/status")
def get_status() -> dict[str, Any]:
    return events.status(get_settings())


@router.post("/test", response_model=TestResponse)
def post_test() -> TestResponse:
    """Emit one `notify.test` `attention` event, to prove the whole path end to end.

    The `dedupe_id` carries the current second, so pressing this twice sends twice -- a test button
    that silently deduped itself would be indistinguishable from a broken channel, which is exactly
    the question the button exists to answer. `attention` for the same reason: it is the one severity
    that clears quiet hours, so the test is not silently swallowed at 23:00.
    """
    settings = get_settings()
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S")
    event = events.emit(
        settings,
        kind="notify.test",
        severity="attention",
        headline="Notification test",
        detail="Sent from the Data tab. If this reached your phone, delivery works.",
        source="notify:test",
        dedupe_id=f"notify.test:{stamp}",
    )
    if event is None:  # same second, same button -- report the dedupe honestly
        return TestResponse(sent=False, event_id=f"notify.test:{stamp}")
    return TestResponse(sent=events.last_dispatch(event.id), event_id=event.id)
