# Notifications runbook

The app keeps an append-only log of things worth knowing about — a manager change, a finished brief,
an autopilot fill, a rule desk's position change, a live buy/sell signal, a research promotion, a new
influencer note, and a data source that has just gone stale. Anything in that log can also be pushed
to a phone.

**Delivery is off by default and the log fills up anyway.** `INVDASH_NOTIFY_ENABLED` governs only
whether events leave the machine; `GET /api/notify/events` serves them either way. So the safe order
of operations is: run for a few days with delivery off, look at what the log actually collects, then
turn delivery on for the subset worth interrupting you.

---

## 1. Pick a channel

### `log` (the default)

Events are written to the application log at INFO. Nothing to install. This is the right setting
while you are deciding what deserves a notification at all, and it is a genuine destination if you
already watch the server log.

```
INVDASH_NOTIFY_ENABLED=1
INVDASH_NOTIFY_CHANNEL=log
```

### `ntfy` (phone push)

[ntfy](https://ntfy.sh) delivers a push notification to a phone by HTTP POST, with no account and no
API key.

1. Install the **ntfy** app (iOS App Store / Google Play / F-Droid).
2. **Choose a topic name.** On the public server `ntfy.sh`, *the topic name is the only access
   control there is* — anyone who knows or guesses it can read every notification you send. So do
   not pick `portfolio` or `alerts`. Pick something no one will type by accident, e.g. the output of
   `python -c "import secrets; print('inv-' + secrets.token_urlsafe(16))"`.
3. In the app, **Subscribe to topic** and paste that name.
4. Put the same name in `.env`:

```
INVDASH_NOTIFY_ENABLED=1
INVDASH_NOTIFY_CHANNEL=ntfy
INVDASH_NOTIFY_NTFY_TOPIC=inv-xxxxxxxxxxxxxxxxxxxxxx
```

If the topic is left empty, nothing is sent and a warning is logged — the app will not guess at a
shared name.

To keep event text off a third party entirely, self-host ntfy and point `INVDASH_NOTIFY_NTFY_URL` at
it. Everything else is unchanged.

Restart the server after editing `.env` — settings are read once per process.

---

## 2. Verify

```
POST /api/notify/test
```

Emits one `notify.test` event at `attention` severity and answers `{"sent": true|false, "event_id":
"..."}`. `sent: false` with delivery off is the expected answer, and the event is still logged.
`attention` is used deliberately so the test is not swallowed by quiet hours at 23:00, and the
dedupe key carries the current second so pressing it twice really does send twice.

```
GET /api/notify/status
```

```json
{"enabled": true, "channel": "ntfy", "total": 41, "last_event_ts": "...",
 "last_sent_ts": "...", "sent_today": 6, "suppressed_today": 12}
```

A high `suppressed_today` next to a low `sent_today` is the policy working, not a fault — read
section 4 to see which gate is doing it. The server log names the reason for every suppression.

---

## 3. The feed and its cursor

```
GET /api/notify/events?since=<cursor>&limit=200
```

Events come back oldest-first (newest last). `since` accepts **either an event id or an ISO
timestamp**:

- **Polling**: hand back the `id` of the last event you saw. You get strictly what came after it —
  gap-free, and immune to two events sharing a timestamp.
- **Catching up by time**: hand back an ISO timestamp, e.g. `2026-09-10T00:00:00+00:00`.
- **No cursor**: you get the newest `limit` events.

An id the server no longer recognises degrades to "everything recent" rather than erroring, so a
poller that has fallen behind re-syncs instead of wedging.

### Service token (polling without a login)

The app is behind a login gate, and a shell script cannot hold a session cookie. Set a read-only
bearer:

```
INVDASH_NOTIFY_SERVICE_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

Then:

```
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/notify/events?since=2026-09-10T00:00:00+00:00"
```

The token reaches **four GETs and nothing else**:

| Path | What it gives |
| --- | --- |
| `GET /api/notify/events` | the event feed |
| `GET /api/notify/status` | delivery counters |
| `GET /api/manager/changes` | the manager change feed |
| `GET /api/manager/briefs/latest` | the most recent brief |

Any other path, and any non-`GET` method, ignores the bearer and falls through to the normal cookie
check. An empty token (the default) disables the path entirely. Rotate it by changing the value and
restarting; there is no revocation list because there is only ever one token.

---

## 4. Policy: what actually gets delivered

Five gates, applied in this order. Anything that fails one is logged and counted in
`suppressed_today`, never queued for later.

| Setting | Default | Effect |
| --- | --- | --- |
| `INVDASH_NOTIFY_ENABLED` | `0` | Off → nothing is ever sent. Everything is still logged. |
| `INVDASH_NOTIFY_MIN_SEVERITY` | `notable` | Sends `attention` + `notable`, drops `fyi`. Ordering is `attention` > `notable` > `fyi`. |
| `INVDASH_NOTIFY_KINDS` | *(empty = all)* | Comma list, **prefix-matched** on the dotted kind. `paper.` subscribes to every fill; `manager.brief` to exactly one thing. |
| `INVDASH_NOTIFY_QUIET_HOURS` | `22:00-07:00` | America/New_York, wraps midnight. **`attention` still sends during quiet hours** — that is what the top severity is for. Empty disables. |
| `INVDASH_NOTIFY_RATE_CAP_PER_HOUR` | `20` | Rolling-hour ceiling. Beyond it events are suppressed, not deferred — a hundred delayed notifications arriving at once is the same disaster an hour later. `0` disables. |

Suppression is deliberately lossy at the *delivery* layer only. The log is complete regardless, so
anything a gate dropped is still in `GET /api/notify/events`.

### Event kinds

Every producer is hooked. Each row names its severity and the `dedupe_id` it passes, because those
two together decide what actually reaches a phone: the severity is what
`INVDASH_NOTIFY_MIN_SEVERITY` filters on, and the dedupe id is what decides whether a repeat is one
notification or ten.

| Kind | Emitted by | Severity | Dedupe id |
| --- | --- | --- | --- |
| `manager.change` | manager snapshot, per change item | the item's own | `<ChangeItem.id>` |
| `manager.brief` | manager brief, one per brief | `attention` | `manager.brief:<brief_id>` |
| `notify.test` | `POST /api/notify/test` | `attention` | carries the current second |
| `paper.fill` | `app.workflow.book.execute_pending` — every autopilot fill **and** every rejection | `notable` | `paper.fill:workflow:<order_id>:<filled\|rejected>` |
| `paper.fill` | `app.paperdesk.desk.refresh` — a rule desk's position changed | `notable` | `paper.fill:desk:<purpose>/<agent_id>:<symbol>:<BUY\|SELL>:<as_of>` |
| `signal.live` | `app.agentdesk.live_loop.decide` — `buy`/`sell` only, never degraded | `attention` | `signal.live:<symbol>:<decided_at>` |
| `research.promotion` | `app.evolution.promotion` — one per promoted genome | `notable` | `research.promotion:<genome_id>:<promoted_at>` |
| `persona.note` | `app.personas.store.VaultStore.write_note` | `fyi` | `persona.note:<slug>:<note_id>` |
| `data.stale` | `app.market.freshness.report` — on the `fresh`/`live` → `stale` edge | `notable` | `data.stale:<key>:<UTC date>` |

Four of these are quieter than they look, on purpose:

- **Live decisions only notify on `buy`/`sell`.** `hold` and `no_action` are most of what a watchlist
  tick produces and neither asks anything of you. A `degraded` decision — one whose rationale carried
  a figure the grounding gate could not trace back to the evidence — is also excluded: a lock screen
  is exactly where nobody goes and checks. Both are still in the log and on the Agent Desk page.
- **Rule-desk fills are *observed*, not executed.** The paper desk replays each card from stored bars
  and reports the positions the replay ends holding; there is no fill to read. So
  `app.paperdesk.fill_journal` differences this refresh's holdings against the last one and calls the
  difference a change. It runs on `POST /api/paperdesk/refresh` only, never on a cached page read, and
  a position opened and closed between two refreshes produces nothing at all (the desk's own `trades`
  list has that round trip). **The first run after this feature lands records a baseline and announces
  nothing** — otherwise every position already open would arrive as a fresh buy. Deleting
  `data/paperdesk/holdings_last.json` re-baselines the same way.
- **Freshness alarms are edge-triggered.** `report()` is called on every load of Data > Health, so a
  level check would re-announce the same stale source on every page view. Only a source that *was*
  `fresh` or `live` and is now `stale` fires, and the dedupe id bounds even a flapping source to once
  a UTC day. `unknown` and `disabled` are not healthy previous states: a source that could not be
  measured, or that you turned off, has not gone stale.
- **Persona notes are `fyi`**, which the default `INVDASH_NOTIFY_MIN_SEVERITY=notable` does not
  deliver. That is intended — a backfill writes dozens at once. They are all in
  `GET /api/notify/events`; set `INVDASH_NOTIFY_MIN_SEVERITY=fyi` if you want them pushed.

A notification failure can never break the thing that produced it: every hook is a `try/except` around
a lazy `from app.notify import emit`, and a fill, note, promotion or report is written before its
event is offered.

---

## 5. Where things live

| Path | What |
| --- | --- |
| `data/notify/events.jsonl` | the log. One JSON event per line, append-only, never rewritten. Safe to read, tail, or archive. |
| `data/notify/seen.json` | dedupe set, newest 5000 ids. Deleting it makes recent events emittable again. |
| `data/notify/sender_state.json` | rate-cap window and the daily sent/suppressed counters. Deleting it resets the hour. |
| `data/notify/freshness_last.json` | each source's status at the last `report()`, so `data.stale` can fire on the edge. Deleting it means the next report re-baselines and announces nothing. |
| `data/paperdesk/holdings_last.json` | each rule desk's holdings at the last refresh. Deleting it re-baselines the fill journal. |
| `data/paperdesk/fills.jsonl` | every desk position change ever observed, append-only. Safe to read or archive; it is a record, nothing reads it back. |

Deleting any of these is safe; deleting `events.jsonl` loses history and invalidates every
poller's cursor (which re-syncs on its own).

## 6. Dedupe, when something does not arrive

An event id is either the producer's own stable id (a change item's id, a brief id) or
`sha256(kind|headline|today-in-UTC)`. The second form means **a producer that repeats itself
announces a given headline once per UTC day**. That is intended for anything on a loop — three
snapshots in an afternoon produce one notification per change, not three.

So if an expected notification did not arrive:

1. Check `GET /api/notify/events` — if the event is not in the log at all, the producer did not run.
2. If it is in the log but was not delivered, the server log names the gate that suppressed it.
3. If it is neither in the log nor suppressed, it was deduped against an earlier emit today.

A notification failure can never break the thing that produced it: every `emit()` call site is
wrapped, and the sender never raises.
