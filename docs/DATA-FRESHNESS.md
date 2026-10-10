# Data freshness: what is fetched, when, and by whom

Status: built 2026-09-08. This document is the design record for the refetch refactor: which
sources the app reads, which freshness class each belongs to, what the Data page's **Fetch data**
button covers, and how the live path feeds AI agents.

## Why three classes, not one refresh policy

With one owner and at most ten users, nothing justifies polling every source all the time. But a
daemon that trades on agents needs quotes that are minutes old, not a day old. So every source is
assigned to exactly one of three classes, and the refresh machinery is chosen per class:

| Class | Tolerance | Mechanism | Who triggers it |
|---|---|---|---|
| `day_frame` | one trading day stale is fine | one-shot sweep, on-disk caches with TTLs | server start (`refresh_on_startup`) or the **Fetch data** button |
| `intraday` | minutes | in-process quote feed, 5m bars on demand | the Paper Desk tape, a `live` desk run, the live-decision daemon |
| `local` | never fetched | pure ledger replay | `python -m app.ingest` |

Nothing is fetched by the request path "just in case": a page load reads what is stored, and the
header says how old it is.

## The catalog (`GET /api/data/freshness`)

Source of truth: `app.market.freshness`. The endpoint does **no network I/O**; it reads store and
cache metadata only. Four rows report `unknown` honestly because `app.market.cache.CachingTransport`
keys entries by URL hash without recording the URL, so a shared cache tree cannot be attributed to
one source.

| key | class | policy | provider | age measured from |
|---|---|---|---|---|
| `bars_daily` | day_frame | startup sweep / on demand | Yahoo chart API | Parquet coverage for the sweep's tracked head (macro proxies + held symbols, capped at 40) |
| `bars_intraday` | intraday | on demand | Yahoo chart API | newest 5m/1h bar across sampled symbols |
| `macro_snapshot` | day_frame | startup sweep / on demand | FRED + CNN Fear & Greed | this process's last sweep record; `unknown` before a sweep |
| `calendar_events` | day_frame | startup sweep / on demand | Fed FOMC + Nasdaq earnings + FRED releases | `unknown` (shared HTTP cache) |
| `fundamentals_edgar` | day_frame | on demand | SEC EDGAR company facts | `unknown` (shared HTTP cache) |
| `institutions_filings` | day_frame | on demand | SEC EDGAR 13F | newest file under `cache_dir/edgar` and `cache_dir/institutions_consensus` |
| `news` | day_frame | on demand | Yahoo news + GDELT + Polymarket | `unknown` (shared HTTP cache) |
| `social_snapshots` | day_frame | scheduled / manual | StockTwits + Reddit | `social_history.sqlite` mtime |
| `live_quotes` | intraday | streaming | Yahoo quotes (poll or websocket) | `app.market.livefeed.status()` |
| `ledger` | local | computed | broker CSV ingest | `ledger.sqlite` mtime |
| `persona_corpus` | day_frame | scheduled / manual | YouTube transcripts | newest note in the vault |

## The Fetch data button (`POST /api/market/refresh`)

Lives on **Data › Health**. It starts the same sweep `lifespan` runs at server start
(`app.market.refresh.refresh_market_data`) on a daemon thread, returns `202` immediately, and the
page polls `GET /api/market/refresh/status` every 2 s until `running` is false. A second press
while a sweep is running answers `202 {started: false, reason: "already_running"}`, not a 409.

The button covers `bars_daily`, `macro_snapshot`, `social_snapshots`, and `calendar_events`. The
calendar is not part of the sweep itself; the endpoint calls `app.market.calendar.warm` alongside it,
mirroring the pairing `lifespan` makes. Everything else is either fetched per request through its
own cache (fundamentals, 13F, news) or belongs to another feature's daemon (persona corpus).

## The live path

### Feed: `app.market.livefeed`

One process-wide `LiveQuoteSource` (poll by default, `paperlive_transport=stream` for the Yahoo
websocket with automatic fallback). The Paper Desk tape and every agent read through this one
instance, so a symbol is polled once no matter how many consumers ask.

The keep-warm daemon is opt-in (`INVDASH_LIVEFEED_ENABLED=1`). It re-subscribes held symbols, macro
movers and `INVDASH_LIVEFEED_WATCHLIST` every `livefeed_keepalive_seconds` so the poller never
evicts them, capped at 120 symbols. With the daemon off, a quote is still fetched on demand the
first time something asks for it.

### Evidence: `live_quote` and `intraday` sections

Two new sections in `app.agentdesk.evidence.SECTION_KEYS`. Both are look-ahead safe: for any
`as_of` before today they return an empty section with a warning, so a historical replay can never
see a live quote. Timestamps and clock times are scrubbed by the grounding gate
(`_ISO_DATETIME_RE`, `_TIME_RE`), which fixed a real leak: an ISO datetime glued to a `T` previously
left `14`, `32`, `05` as ungrounded tokens.

### Desk runs: `live: true`

`POST /api/tradingagents/runs` and `POST /api/vibedesk/runs` accept `live`. A live run must be as of
today, watches the symbol on the feed, and adds the two live sections to the analysts' packs. A run
without `live` is byte-identical to before; the research stays reproducible unless you opt out.

### Daemon: `app.agentdesk.live_loop`

Opt-in (`INVDASH_LIVE_DECISIONS_ENABLED=1`). Every `live_decisions_interval_minutes` during the
`REGULAR` session it runs one grounded model decision per watchlist symbol under a per-tick spend
cap and appends the record to `data/agentdesk/live_decisions/<date>.jsonl`. It never places, stages
or fills a trade; the records are research signals, surfaced on the Trading Agents page and over
`GET /api/agentdesk/live/decisions`. `POST /api/agentdesk/live/decide` runs one decision by hand.

## Operating notes

- Turn things on in `.env`, restart the backend: `INVDASH_LIVEFEED_ENABLED=1`, then
  `INVDASH_LIVE_DECISIONS_ENABLED=1` once the feed reports `healthy` on Data › Health.
- Yahoo has no published rate limit for the chart endpoint; the poller runs 5 s cadence in regular
  hours and 60 s otherwise. Keep the watchlist small.
- The websocket transport decodes Yahoo's protobuf by hand and has not been verified against live
  bytes; it falls back to polling permanently on the first mismatch. Prefer `poll` until verified.
