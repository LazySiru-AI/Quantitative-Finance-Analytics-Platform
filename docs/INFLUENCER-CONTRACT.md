# Influencer Personas — pinned contract

The feature builds one **persona agent per influencer**, each with a growing memory stored as an
Obsidian-compatible markdown vault. Backend package `app.personas`, router `/api/personas`, frontend
page `/personas` under the **Agent Desk** nav section.

**Nothing in this file is negotiable by a worker.** If a shape here is wrong or insufficient, say so
in your report and stop — do not invent a replacement. A field renamed on one side and not the other
is the exact failure this document exists to prevent (see `parallel-agents-invent-each-others-contracts`).

Backing Python types: [`backend/app/personas/models.py`](../backend/app/personas/models.py).

## Conventions (same as `docs/AGENT-DESK-CONTRACT.md`)

- **Money is a decimal string, never a JSON number** (`spent_usd`, `cap_usd`). Render with
  `frontend/src/api/client.ts` helpers.
- **Timestamps are ISO-8601 strings**, or `null` when the event has not happened.
- Every response model is a frozen Pydantic model (`_Frozen`: `frozen=True, extra="forbid"`).
- Routers are thin: wire routes, translate domain exceptions to status codes. Logic lives in the
  sibling package. Provider failures degrade to a warning, they do not 5xx (the `app.api.news`
  contract).
- Grounding types (`GroundingIssue`, `GroundingVerdict`) are reused verbatim from
  `app.agentdesk.models`; do not redefine them.

## Verified upstream facts (2026-09-01, do not re-derive)

- Handle → channel id: GET `youtube.com/@<handle>`, regex `"externalId":"(UC[\w-]{22})"`. Keyless.
- **RSS (`feeds/videos.xml`) is dead for these channels (404/500). Do not use it.**
- Video listing: `yt-dlp` flat playlist on `youtube.com/@<handle>/videos`
  (`extract_flat=True, playlistend=N, skip_download=True`) → entries with `id`, `title`, `duration`,
  `url`, `view_count`. **No upload date of any kind** (`timestamp`/`upload_date`/`release_timestamp`
  are all absent) — verified. A per-video non-flat extract recovers `upload_date`; when even that
  fails, `published` is `null`. Never substitute `ingested_at` for it.
- Transcript: `youtube_transcript_api.YouTubeTranscriptApi().fetch(video_id, languages=[...])`;
  `.list(video_id)` enumerates tracks. Auto-generated tracks only for the seed channels.
- 4 of 5 seed channels are Korean. Summariser must accept Korean input. Default output language is
  English with source-language quotes preserved verbatim (`INVDASH_PERSONA_SUMMARY_LANG`, default `en`).

## Wire types (TypeScript mirror of `models.py`)

```ts
type Platform = "youtube" | "manual";        // "telegram" | "x" added in Phase 5
type IngestState = "queued" | "running" | "succeeded" | "failed" | "cancelled";
type Stance = "bullish" | "bearish" | "neutral" | "unclear";
type TranscriptSource = "manual" | "auto" | null;
type NoteKind = "video_transcript" | "post" | "manual";

// reused from Agent Desk, do not redefine
interface GroundingIssue { kind: "ungrounded_number" | "no_evidence" | "empty_output"; detail: string; }
interface GroundingVerdict { ok: boolean; issues: GroundingIssue[]; attempts: number;
  degraded: boolean; checked_tokens: number; }

interface FollowedSource {
  source_id: string;         // "yt:<channelId>" | "manual:<uuid>"
  platform: Platform;
  handle: string;            // "@creator-a" as typed
  channel_id: string | null; // UC… for youtube, null for manual
  url: string;
  enabled: boolean;
  added_at: string;
}

interface TickerMention {
  symbol: string;            // validated against the instrument table; uppercase
  stance: Stance;            // THE INFLUENCER'S stance, not ours
  reasoning: string;         // paraphrase; may embed a short verbatim quote
}

interface EpisodicNote {
  note_id: string;           // stable: platform-native id (youtube video id) or uuid
  persona: string;           // persona slug
  source_id: string;
  published: string | null;  // ISO-8601 upload date; null when the upstream cannot tell us
  ingested_at: string;
  url: string;
  title: string | null;
  kind: NoteKind;
  transcript_source: TranscriptSource;
  lang: string;              // source language of the transcript, e.g. "ko"
  summary: string;
  themes: string[];          // 2-5 short bullets: what this item was about
  quotes: string[];          // verbatim, source language
  mentions: TickerMention[];
  path: string;              // vault-relative path to the note .md
  degraded: boolean;         // summary was released despite failing the grounding gate
}

interface Persona {
  slug: string;              // "creator-a"
  display_name: string;      // "Creator A"
  sources: FollowedSource[];
  note_count: number;
  tickers: string[];         // validated symbols seen across notes, most-recent first
  profile_version: number;   // 0 = never consolidated
  consolidated_at: string | null;
  created_at: string;
}

interface DigestCard {
  persona: Persona;
  as_of: string | null;      // newest note's ingested_at; null = no notes yet
  window_start: string | null;
  note_count: number;
  headline: string;          // one sentence; "" when no notes
  themes: string[];          // 2–5 bullets: what they are trading / focused on
  mentions: TickerMention[]; // aggregated, deduped by symbol, newest stance wins
  latest_note: EpisodicNote | null;
  // AGGREGATE over the window's notes, not one call's record: only `ok` and `degraded` are
  // meaningful; `issues`/`attempts`/`checked_tokens` stay at defaults. Per-note truth is
  // EpisodicNote.degraded.
  grounding: GroundingVerdict;
  warnings: { source: string; reason: string }[];
}

interface IngestJob {
  job_id: string;
  persona: string;
  state: IngestState;
  items_total: number;
  items_done: number;
  items_failed: number;
  started_at: string | null;
  finished_at: string | null;
  spent_usd: string;         // decimal string
  error: string | null;      // null unless state === "failed"
}
```

## Endpoints

```
GET    /api/personas                          -> Persona[]
POST   /api/personas            {handle, platform?}   -> Persona          (resolves channel id + name)
GET    /api/personas/{slug}                   -> Persona                  (404 if unknown)
DELETE /api/personas/{slug}                   -> 204
POST   /api/personas/{slug}/sources  {handle, platform?} -> Persona
DELETE /api/personas/{slug}/sources/{source_id}          -> Persona

GET    /api/personas/cards                    -> DigestCard[]             (always 200)
GET    /api/personas/{slug}/notes             -> EpisodicNote[]           (newest first)
GET    /api/personas/{slug}/notes/{note_id}   -> EpisodicNote             (404 if unknown)

POST   /api/personas/{slug}/ingest  {limit?: number, video_urls?: string[],
                                      drop?: {url?: string, text?: string, title?: string}} -> IngestJob
GET    /api/personas/{slug}/ingest/{job_id}   -> IngestJob                (409 on POST if one active)
```

`POST /ingest` with neither `video_urls` nor `drop` backfills the persona's youtube sources up to
`limit` (default 20, the owner's current choice; hard cap `INVDASH_PERSONA_BACKFILL_MAX`, default 50).
Phases 2–4 add `/consolidate`, `/profile`, `/theses/{symbol}`, `/ask`, `/card`; their shapes are
pinned when those phases start.

## Vault layout (`INVDASH_VAULT_DIR`, default `data/vault/`)

```
<vault>/influencers/<slug>/
  notes/<YYYY-MM-DD>-<note_id>.md      immutable episodic note
  transcripts/<note_id>.md             raw transcript / drop text (linked from the note)
  persona.json                          machine mirror of Persona (source of truth for the API)
  log.md                                append-only ingest log with per-item cost
  profile.md            (Phase 2)       consolidated persona, claims cite [[note]] links
  theses/<SYMBOL>.md    (Phase 2)
```

Episodic note frontmatter (YAML) — this IS part of the contract:

```yaml
---
note_id: VIDEOID004
persona: creator-a
source_id: "yt:UCxxxxxxxxxxxxxxxxxxxxxx"
published: 2026-09-01T00:00:00Z   # omit the key entirely when unknown
ingested_at: 2026-09-01T23:40:00Z
url: https://www.youtube.com/watch?v=VIDEOID004
title: "36 1 September Market Headwinds..."
kind: video_transcript
transcript_source: auto
lang: ko
tickers: [NVDA, TSLA]
stances: {NVDA: bullish, TSLA: neutral}
degraded: false
---
```
Body: `## Summary`, `## Themes` (`- ` bullets), `## Tickers` (one line each with stance + reasoning),
`## Quotes` (verbatim, source language), `## Source` (link to the transcript file). Episodic notes are **never rewritten**.

## Guardrails (enforced in code, checked by QA)

- Card and note copy says "the influencer's stance" / "their view", never "signal" or advice.
- Every `TickerMention.symbol` is validated against the instrument table before it lands in a note or
  card; unvalidated symbols are dropped, not guessed (auto-captions mangle tickers).
- Summaries run through `app.agentdesk.grounding.check` with the transcript/post as the evidence pack;
  a number not present in the source is rejected and re-asked, then the note is marked degraded.
- Transcripts stay in the private vault; no endpoint serves raw transcript text outside the local app
  beyond the owner's own drill-down, and nothing is published.
- Honest `User-Agent` (`investing-dashboard/0.1`); ingest is one pass per source, polite cadence.

---

# Phase 2 — persona consolidation (pinned)

Phase 1 writes one immutable note per ingested item. Phase 2 folds those notes into a **persona
profile**: who this person is, what they believe, how they trade. Same rules as Phase 1 -- frozen
models, thin router, degrade rather than 5xx -- plus one new hard rule:

**Every profile claim must cite the notes it came from.** A `ProfileClaim` with an empty `citations`
tuple is invalid and must never be persisted. The profile is a *derived* document: unlike an episodic
note it IS rewritten, so without citations there is no way to tell a claim the influencer actually
made from one the model invented. `profile.history/<timestamp>.md` keeps every prior version so the
drift is visible.

## Wire types

```ts
interface ProfileClaim {
  text: string;             // one belief / playbook statement, in the summary language
  citations: string[];      // note_ids backing it; MUST be non-empty
}

interface PersonaProfile {
  persona: string;          // slug
  version: number;          // 1 on first consolidation, +1 each rewrite
  consolidated_at: string;  // ISO-8601
  note_count: number;       // how many notes this version was built from
  summary: string;          // who they are and what they trade, 2-4 sentences
  beliefs: ProfileClaim[];  // what they think the market is doing
  playbook: ProfileClaim[]; // how they actually trade: setups, entries, risk habits
  vocabulary: string[];     // recurring terms/names they use
  degraded: boolean;        // released despite failing the grounding gate
  path: string;             // vault-relative path to profile.md
}

interface TickerThesis {
  persona: string;
  symbol: string;
  stance: Stance;           // their latest stance on it
  updated_at: string;
  claims: ProfileClaim[];
  path: string;
}
```

## Endpoints

```
POST /api/personas/{slug}/consolidate  -> PersonaProfile   (200; runs the model, rewrites profile.md)
GET  /api/personas/{slug}/profile      -> PersonaProfile   (404 when never consolidated)
GET  /api/personas/{slug}/theses       -> TickerThesis[]   (always 200, [] when none)
GET  /api/personas/{slug}/theses/{symbol} -> TickerThesis  (404 when unknown)
```

`POST /consolidate` is **synchronous**, unlike ingest. It is one model call over notes already on
disk (tens of seconds), not a per-item loop over the network, so a job registry would add polling
machinery for a single call. It is capped by `persona_ingest_cap_usd` like any other model work.

## Vault layout additions

```
<vault>/influencers/<slug>/
  profile.md                    the current consolidated persona (rewritten each time)
  profile.history/<ISO>.md      every previous version, never deleted
  theses/<SYMBOL>.md            one running per-ticker view
```

`profile.md` frontmatter: `persona`, `version`, `consolidated_at`, `note_count`, `degraded`,
`vocabulary` (flow list). Body: `## Summary`, `## Beliefs`, `## Playbook`, each claim rendered as
`- <text> [[<note_id>]] [[<note_id>]]` so the citations are live Obsidian links.

---

# Phase 3a — call scoring (pinned)

The notes carry a dated stance per ticker. Scoring asks the honest, backward-looking question this
whole dashboard exists for: **if you had acted on what the influencer said, on the day they said it,
what would the market have done since?** It is DESCRIPTIVE, never predictive, and never advice -- the
copy must say so. It measures only the calls they actually made on camera; it is not an audited track
record, and selection/survivorship caveats apply.

## Semantics (exact -- a worker must not vary these)

- **A call = one note's `TickerMention` on a symbol, dated by that note's `published`.** A note whose
  `published` is null cannot be scored (no anchor date) and is reported under warnings, never guessed.
- **Entry = the close of the first daily bar with `bar.ts.date() >= said_on.date()`.** Never earlier
  -- that would be look-ahead. A Sunday upload scores against Monday's close. If no bar exists at or
  after the date yet (a call from today, market not yet closed), outcome is `pending`, not a guess.
- **Latest = the most recent daily bar available.**
- **Return basis = adjusted close when BOTH endpoints have `adj_close`, else raw `close` on both**
  (never mix bases across the two ends). `return_pct = (latest/entry - 1) * 100`.
- **Outcome** (`|return| < 2.0` is the flat band):
  - `not_directional` when stance is neutral/unclear (return still shown for context)
  - `flat` when directional but within the flat band
  - `played_out` when bullish & up, or bearish & down
  - `went_against` when bullish & down, or bearish & up
  - `pending` when the statement date is at/after the last available bar
  - `no_data` when the symbol has no usable bars for the window
- **Fetch each symbol's daily series once** (earliest `said_on` -> today) via
  `app.market.store.ensure_series(symbol, Interval.DAY, start=..., settings=...)`, then index per note.
  `ensure_series` degrades to stored data on a provider failure; a symbol it cannot serve at all is a
  `no_data`/warning, not a 5xx.
- **Hit rate counts only directional calls that have price data** (`played_out`/`went_against`/`flat`);
  `pending`, `no_data`, and `not_directional` are excluded from the denominator. `flat` counts as
  neither played-out nor against but is in the denominator (a call that went nowhere is not a hit).

## Wire types

```ts
type CallOutcome =
  "played_out" | "went_against" | "flat" | "not_directional" | "pending" | "no_data";

interface CallScore {
  symbol: string;
  stance: Stance;
  note_id: string;
  said_on: string;          // the note's published date (ISO)
  entry_date: string | null;  // actual first trading close used; null for pending/no_data
  entry_price: number | null;
  latest_date: string | null;
  latest_price: number | null;
  return_pct: number | null;  // null for pending/no_data
  basis: "adjusted" | "close" | null;  // which price basis was used
  outcome: CallOutcome;
}

interface PersonaScorecard {
  persona: string;
  as_of: string;
  scored_calls: CallScore[];      // newest said_on first
  directional_count: number;      // calls in the hit-rate denominator
  played_out: number;
  hit_rate: number | null;        // played_out / directional_count, null when denominator is 0
  median_return_pct: number | null;   // median signed return over directional priced calls
  warnings: { source: string; reason: string }[];  // symbols/dates that could not be scored
}
```

Signed return, for `median_return_pct`, is `return_pct` for a bullish call and `-return_pct` for a
bearish one -- so a persona who is consistently right trends positive regardless of direction.

## Endpoint

```
GET /api/personas/{slug}/scorecard  -> PersonaScorecard   (404 unknown persona; always 200 otherwise,
                                                            [] scored_calls when no dated mentions)
```

Read-only and cheap-ish (bar reads, no model call), but it may fetch bars, so it can be slow on a
cold store -- that is acceptable for a GET the user triggers, and it degrades to stored data.

---

# Phase 3b — fixed horizons + chronological view (pinned)

Two additions driven by the same insight: a timestamp is only useful if calls are made comparable
across time. Return-to-today (3a) judges an old call over months and a new one over days; fixed
horizons fix that, and the timeline makes the evolution of a view legible.

## Fixed-horizon scoring (extends 3a)

For each call, in addition to return-to-today, compute the return at fixed **trading-day** horizons
after entry: **5, 20, 60**. Entry is unchanged (first close at/after said_on, no look-ahead). The
horizon bar is the close exactly `days` trading bars after the entry bar; if fewer than `days` bars
exist after entry yet, that horizon is **incomplete** (`return_pct: null`, `complete: false`) -- never
extrapolated. Basis and flat-band rules are identical to 3a.

```ts
interface HorizonReturn { days: number; return_pct: number | null; complete: boolean; }
// CallScore gains:  horizons: HorizonReturn[];   // one per configured horizon; [] for pending/no_data

interface HorizonStat {          // aggregate at one horizon over directional calls whose horizon is COMPLETE
  days: number;
  directional_count: number;     // directional calls with a complete horizon return
  played_out: number;
  hit_rate: number | null;       // null when directional_count == 0
  median_return_pct: number | null;   // signed (bullish +, bearish -)
}
// PersonaScorecard gains:  horizon_stats: HorizonStat[];
```
Horizons live in `app.personas.scoring.DEFAULT_HORIZONS = (5, 20, 60)`. Return-to-today fields on
CallScore/PersonaScorecard are unchanged and still served (they are "so far", a useful complement).

## Chronological view (new)

```ts
interface StancePoint { note_id: string; said_on: string; stance: Stance; reasoning: string; }
interface StanceTimeline { symbol: string; points: StancePoint[]; }  // OLDEST first -> reads as evolution
interface TimelineEntry {
  note_id: string; published: string | null; title: string | null;
  summary: string; themes: string[]; symbols: string[]; url: string;
}
interface PersonaTimeline {
  persona: string;
  entries: TimelineEntry[];            // newest first
  stance_timelines: StanceTimeline[];  // symbols that changed stance first, then by mention count
}
```

Endpoint: `GET /api/personas/{slug}/timeline -> PersonaTimeline` (404 unknown persona; empty entries
when no notes). Pure read over stored notes -- no model call, no market fetch.

---

# Phase 4 — ask the persona (pinned)

The point of the whole feature: not just "what did they say", but "what would they say about X now,
in their voice, grounded in their own record." A model's impression of the person, built from the
consolidated profile plus the notes that bear on the question -- explicitly NOT the person, and NOT
advice. Every answer cites the notes it drew on.

## Semantics

- Retrieval: the profile (if consolidated) plus the notes relevant to the question -- when a `symbol`
  is given, the notes that mention it, newest first, then recent notes; otherwise the most recent
  notes. Capped (`app.personas.ask.MAX_CONTEXT_NOTES`). When a `symbol` is given, the current market
  snapshot for it (recent close / simple context) is added to the evidence so the persona can speak
  to "now" without the grounding gate rejecting a real figure.
- The answer runs through `app.agentdesk.grounding.run_grounded`: numbers must be grounded in the
  evidence, and a degraded answer is returned (never raised), flagged. `citations` are note_ids the
  answer used; an answer that cites nothing is allowed only when the persona has no notes yet, in
  which case it says so rather than inventing a view.
- Voice, not advice: the prompt casts the model as an impression of the influencer, forbids inventing
  positions they never expressed and forbids giving the reader financial advice. `stance` is filled
  only when a `symbol` was asked about and the persona's record supports one, else null/"unclear".

## Wire types

```ts
interface PersonaAnswer {
  persona: string;
  question: string;
  symbol: string | null;
  answer: string;            // in the persona's voice, grounded
  citations: string[];       // note_ids the answer drew on
  stance: Stance | null;     // their stance on `symbol`, when asked and supported
  grounding: GroundingVerdict;
  degraded: boolean;         // released despite failing the gate
  cost_usd: string;          // decimal string
}
```

## Endpoint

```
POST /api/personas/{slug}/ask  {question: string, symbol?: string}  -> PersonaAnswer
```
404 unknown persona; 409 when the persona has no notes to answer from; 503 model unavailable; 409 on
budget cap. Synchronous (one grounded call), capped by `persona_ingest_cap_usd`.

---

# Phase 4b — persona backtest lens (pinned)

A **descriptive lens**, explicitly NOT a strategy recommendation or an alpha claim: "if you had
followed this persona's dated calls, would you have beaten just holding the market?" It follows each
directional call (long a bullish call, signed-negative a bearish one) from its entry (the 3a rule:
first close at/after `said_on`, no look-ahead) and, at each fixed horizon, compares the persona's mean
call return to the benchmark's return over the SAME entry->exit windows. Small samples over a single
window are not evidence of skill; the response carries a fixed caveat saying so, and every UI must
render it.

Benchmark: **SPY** (fixed for now; the market proxy this repo already uses everywhere). A call whose
symbol or window has no bars, or whose horizon has not elapsed, is excluded from that horizon's
aggregate and surfaced in `warnings` -- never counted as zero.

```ts
interface BenchmarkedHorizon {
  days: number;
  n: number;                       // directional calls with a complete horizon AND a benchmark window
  mean_return_pct: number | null;  // persona's mean SIGNED call return (bullish +, bearish -)
  mean_benchmark_pct: number | null;   // SPY mean return over the same entry->exit windows
  excess_pct: number | null;       // mean_return_pct - mean_benchmark_pct (the descriptive "edge")
  win_rate_vs_benchmark: number | null;  // fraction of calls whose signed return beat SPY's, or null
}
interface PersonaBacktest {
  persona: string;
  as_of: string;
  benchmark: string;               // "SPY"
  call_count: number;              // directional calls considered (any horizon)
  horizons: BenchmarkedHorizon[];  // 5/20/60 trading days
  caveat: string;                  // fixed: descriptive, window-dependent, not advice, not predictive
  warnings: { source: string; reason: string }[];
}
```

Endpoint: `GET /api/personas/{slug}/backtest -> PersonaBacktest` (404 unknown persona; empty horizons
when no directional calls have priced/benchmarked windows). Reuses `score_calls`; adds one SPY fetch.

---

# Phase 6 — persona paper book on the Paper Desk (pinned)

"What following each influencer's calls would have done with $100,000", shown beside the reference
agents on the Paper Desk. A persona's book is a CASH-CONSTRAINED TRADING REPLAY of its dated calls
since inception -- not a snapshot of "everything currently bullish". It is descriptive, not advice, and
not a real position. Backend lives entirely in `app.personas` (no edits to the contested
`app.paperdesk`); the Paper Desk page renders it via these endpoints (frontend handoff), so
`PersonaHolding` mirrors the paper desk's `Holding` fields structurally for UI reuse.

Rewritten 2026-09 from an earlier unbounded equal-notional snapshot (every symbol ever CURRENTLY
bullish, bought with no cash limit, never sold) to fix two problems: that design could not represent a
name being bought and later sold, and it emitted `return_pct` as a pre-multiplied percent (`"6427"` for
an ordinary gain) that the frontend then multiplied by 100 again. Both are fixed by this replay.

## Semantics
- **Replay, not selection.** Every mention across every note is walked in ascending `said_on` (=
  `published` or `ingested_at`) order, ties broken by note-encounter order then symbol. Calls dated
  before **inception** (`app.personas.paperbook.DEFAULT_INCEPTION = 2026-01-01`) are ignored entirely,
  and so are `intraday`-horizon calls and `unclear` stances, throughout.
- **Starting cash** = `app.personas.paperbook.STARTING_CASH_USD = 100000`. **Notional per position** =
  `DEFAULT_NOTIONAL_USD = 10000` per fresh buy. **Hard position cap** =
  `MAX_OPEN_POSITIONS = 10` ($100,000 / $10,000): the book holds at most ten names at once, capped by
  count and not only by cash, so paper gains can never carry it past ten.
- **Bullish, not held:** buy `notional_per_position` at the first daily close on/after `said_on` (the
  3a no-look-ahead rule), via `ensure_series(symbol, Interval.DAY, start=inception)`. `quantity =
  notional / entry_price`, `cost_basis = notional`, cash debited. When the book is already full
  (`MAX_OPEN_POSITIONS` open) OR cash is short, close the longest-held ("stalest", by
  `last_bullish_on`) open position(s) first to make room (`PersonaTrade.reason = "replaced"`) -- so a
  full book must sell to buy even with cash to spare; still short of a slot and cash after every
  position is tried -> the call is recorded in `skipped` (`reason = "no_cash"`), and the sales already
  made stand.
- **Bullish, already held:** no trade -- `last_bullish_on` is bumped to this call's date (this is the
  field `replace_stalest` reads to pick which open position to close first).
- **Bearish or neutral, held:** sell at the first close on/after `said_on`, realising `PersonaTrade`
  (`reason = "flip_bearish"` or `"flip_neutral"`), cash credited. Not held -> no-op.
- **Unpriceable symbol** (no usable bars at all) -> every call on it lands in `skipped`
  (`reason = "no_market_data"`) and the symbol is named once in `warnings` with
  `reason = "no market data"` (exact wording); priced but with no bar since the call date yet ->
  `skipped` (`reason = "no_bar_since"`). Never a fabricated fill.
- **Final mark.** Every still-open position is marked to its latest available close (adjusted-close
  basis when both entry and latest bars have one, else raw close -- same rule as scoring).
  `unrealised_pnl = market_value - cost_basis`; `weight = market_value / market_value_total`.
- **`return_pct` is a 0-1 FRACTION everywhere** -- on a holding, a trade, and the book total -- never a
  pre-multiplied percent. `0.1523` means a 15.23% gain; the frontend multiplies by 100 to display it.
- **Book totals.** `equity = cash + market_value_total`; `return_pct = equity / starting_cash - 1`;
  `realised_pnl_total` sums every closed trade's P&L. Cash never goes negative. `as_of` = the latest
  open holding's mark date, else the latest closed trade's exit date, else `None` (an untouched book).

## Wire types
```ts
interface PersonaHolding {           // mirrors paperdesk Holding fields for UI reuse -- OPEN positions
  symbol: string; stance: Stance; note_id: string;
  entry_date: string; entry_price: string; quantity: string; cost_basis: string;
  last_price: string; last_price_date: string; market_value: string;
  unrealised_pnl: string; return_pct: string;  // return_pct: 0-1 fraction, e.g. "0.1523"
  bars_held: number; weight: number; last_bullish_on: string;
}
interface PersonaTrade {             // one CLOSED position
  symbol: string; note_id: string; entry_date: string; entry_price: string;
  exit_date: string; exit_price: string; quantity: string; realised_pnl: string;
  return_pct: string;                // 0-1 fraction, like everywhere else in this book
  reason: "flip_bearish" | "flip_neutral" | "replaced";
}
interface PersonaSkippedCall {       // one call the replay did not act on
  symbol: string; said_on: string;
  reason: "no_cash" | "no_market_data" | "no_bar_since";
}
interface PersonaBook {
  persona: string; display_name: string; inception: string; as_of: string | null;
  notional_per_position: string; starting_cash: string; cash: string; equity: string;
  holdings: PersonaHolding[];
  cost_basis_total: string; market_value_total: string; unrealised_pnl_total: string;
  realised_pnl_total: string; return_pct: string;  // return_pct: 0-1 fraction
  trade_count: number; open_count: number;
  trades: PersonaTrade[]; skipped: PersonaSkippedCall[];
  warnings: { source: string; reason: string }[];
}
```

## Endpoints
```
GET /api/personas/books            -> PersonaBook[]   (one per persona; always 200)
GET /api/personas/{slug}/book      -> PersonaBook     (404 unknown persona)
```

---

# Phase 7 — cross-pollination (pinned)

Three pieces so strategy cards and influencer data inform each other. All backend in `app.personas`;
no edits to the contested strategy/paperdesk code (7b/7c consume their PUBLIC seams only).

## 7a — methodology on the profile (extends Phase 2 consolidation)
`PersonaProfile.methodology: ProfileClaim[]` -- HOW they trade (indicators, timeframes, entry/exit
triggers, risk/sizing rules, tools), each cited, produced by the SAME consolidation call that makes
beliefs/playbook. `ProfileDraft` gains `methodology: tuple[ProfileClaim,...]`; the prompt asks for the
mechanical toolkit specifically, distinct from the strategic playbook. `profile.md` gains a
`## Methodology` body section (`- <claim> [[note]]`), round-tripped like `## Beliefs`/`## Playbook`.

## 7b — influencer consensus watchlist (direction a: tickers -> strategy reference)
```
GET /api/personas/watchlist -> InfluencerWatchlist
interface WatchlistEntry { symbol: string; bullish_count: number; bearish_count: number;
  personas: string[];        // slugs currently bullish
  latest_reasoning: string;  // one backing reason, from the most recent bullish note
  as_of: string | null; }    // newest backing call's date
interface InfluencerWatchlist { as_of: string; entries: WatchlistEntry[]; caveat: string; }
```
`entries` are symbols at least one persona is CURRENTLY bullish on (latest-stance-wins, validated
against the instrument table), ranked by `bullish_count` desc then symbol. A reference the strategy
layer can seed `focus_symbols`/`candidates` from (`app.agents.scout`/`designer` already accept those),
or the owner can read. Descriptive, not a buy list -- `caveat` says so.

## 7c — persona -> strategy card (direction b: persona learns the DSL)

`POST /api/personas/{slug}/strategy-card -> StrategyCardDraft`. The model reads the persona's
`methodology` (7a) + its current-bullish tickers and proposes ONE rule card expressed in the repo's
existing vocabulary, which is then rendered and validated so the result is a real, backtestable
`app.tournament.models.StrategyCard` -- never free-form DSL.

Honest by construction: (1) only personas WITH a methodology can be mapped -- a macro commentator
(empty methodology) returns 409 "this persona describes no mechanical methodology to translate",
never an invented card; (2) it is "inspired by", not faithful; (3) per the repo's 33-round record it
is not expected to beat the null -- it is an exploration lens, and the draft carries a fixed caveat
saying so.

Mapping (the model chooses, constrained):
- `rule_shape` from `app.evolution.models.RuleShape` (ma-crossover / momentum-state / rsi-pullback /
  band-reversion / channel-breakout / band-breakout / macd-cross / vol-compression) -- whichever best
  matches the described technique, cited to the methodology claims that justify it.
- trait params (fast<slow<regime_ma within bounds, stop_loss_pct, take_profit_pct, max_hold_days,
  max_positions, position_pct) informed by the methodology (e.g. stated stops/timeframes/R:R).
- `universe` = the persona's current-bullish tickers, capped at 12, uppercased.
The draft is realised through `app.evolution.proposer.card_for` (which renders entry/exit/rank text,
parses it with `app.rules.grammar`, and runs every `StrategyCard` validator); any rejection is
reported, never patched.

```ts
interface StrategyCardDraft {
  persona: string;
  mapped: boolean;              // false when the persona has no methodology to map (with `reason`)
  reason: string;              // why unmapped, or "" when mapped
  rule_shape: string | null;
  card: object | null;          // the validated StrategyCard (JSON) when mapped
  rationale: string;           // how the methodology informed the shape/params, cited
  citations: string[];         // methodology note_ids the mapping drew on
  caveat: string;              // fixed: inspired-by, exploration lens, expect no edge, not advice
  degraded: boolean;
  cost_usd: string;
}
```
404 unknown persona; 409 when the persona has no methodology (consolidate first, or it is a pure
commentator); 503 model unavailable; 409 budget. Synchronous, capped by `persona_ingest_cap_usd`.

---

# Phase 8 — rigor + auditability (improvements plan)

Everything below is DESCRIPTIVE. The point-in-time round proved the feature has no edge; these changes
make the honest signal legible, they do not chase alpha. Plan: `docs/INFLUENCER-IMPROVEMENTS-PLAN.md`.

## 8.0 Shared shapes (pinned in `models.py`)
- `InstrumentKind = equity|etf|index|future|crypto|fx|unknown`; `Horizon = intraday|swing|position|
  long_term|unclear`; `RiskPosture = on|off|mixed|unclear`. `TickerMention` gains `instrument`
  (default equity) + `horizon` (default unclear); both additive, legacy notes load at the defaults.
- `StatEstimate {n, point, low, high, confidence=0.90, method: bootstrap|wilson|none}` — every rate/
  mean carries one. `point/low/high` are null when `n==0`.

## 8.1 Point-in-time (P0.1)
- `app.personas.stances.bullish_as_of(notes, as_of)` and `consensus_as_of(personas, as_of=, now=)`.
- `GET /api/personas/watchlist?as_of=<ISO date>` — the consensus as known on that date; omit for now.
- `GET /api/personas/{slug}/book?as_of=<ISO date>&walk_forward=<bool>` — the paper book priced with a
  point-in-time universe; `walk_forward=true` re-derives the universe monthly from stances known then.

## 8.2 Instrument typing (P0.2)
- `WatchlistEntry.instrument` set from `app.personas.instruments.classify(symbol)`.
- `POST /{slug}/strategy-card` rejects a universe containing a non-equity/ETF (422) and names the
  suggested ETF proxy from `instruments.PROXY_TABLE`; only tradeable names reach `card_for`.

## 8.3 Stats (P0.4)
- `PersonaScorecard.hit_rate_ci`; `HorizonStat.hit_rate_ci`/`return_ci`/`mean_return_pct`;
  `BenchmarkedHorizon.excess_ci` — all `StatEstimate`, computed by `app.personas.stats`
  (Wilson for rates, seeded bootstrap for means). Null-safe over n==0.

## 8.4 Regime view (P2.1)
- Consolidation also extracts `PersonaProfile.regime: RegimeView` (risk/rates/sectors, cited;
  `has_signal=False` for a pure technical trader). `## Regime` section in `profile.md`.
- `GET /api/personas/regime -> RegimeConsensus` (per-persona + risk-on/off tally + caveat);
  `GET /{slug}/profile` already returns `regime`.

## 8.5 Card drafts + fidelity (P2.2)
- `StrategyCardDraft` gains `version`, `fidelity`, `techniques_total/represented`, `unrepresentable`.
- `POST /{slug}/strategy-card` persists each mapped draft under `strategy/<version>.json`;
  `GET /{slug}/strategy-cards -> SavedStrategyDraft[]` lists them, newest first.

## 8.6 Profile drift (P2.3)
- `GET /{slug}/profile/diff?from=<v>&to=<v> -> ProfileDiff` — claims added/removed/re-cited between two
  consolidations (`app.personas.drift`).

## 8.7 Incremental consolidation (P1.1)
- `POST /{slug}/consolidate?incremental=<bool>` — when true, consolidate only notes newer than
  `profile.consolidated_at` and merge into the standing profile, so cost stops scaling with vault size.

## 8.8 Persona critiques a card (P3)
- `POST /{slug}/critique` body `{card: StrategyCard-JSON}` -> `CardCritique` — the persona's in-voice
  assessment of how the card fits their methodology (`app.personas.critique`). Grounded, cited, not
  advice; `cannot_say` when the record does not support a judgement. Capped by `persona_ingest_cap_usd`.

---

# Phase 9 — persona chat (pinned)

Multi-turn conversation with one persona, grounded in its own profile + notes, in its voice. The
one-shot `POST /{slug}/ask` (Phase 4) stays as-is (its own special case); this adds persisted
threads and a retriever that ranks by relevance to the question instead of pure recency. Same rules
as every other phase: frozen models, thin router, degrade rather than 5xx, every answer cited, never
advice, never the person. Plan: `docs/PERSONA-CHAT-PLAN.md`.

## Retrieval (pinned signature — `app.personas.retrieval`)

The chat service calls, verbatim:

```python
def select_notes(
    notes: Sequence[EpisodicNote],
    question: str,
    *,
    symbol: str | None,
    profile: PersonaProfile | None,
    cap: int = 16,
    char_budget: int = 40_000,
) -> tuple[EpisodicNote, ...]:
    """Notes most relevant to `question`, newest-as-tiebreak, capped by count AND assembled char
    budget. Lexical tf-idf over each note's title+themes+summary+quotes+mention reasoning; Latin
    lower-cased with light stemming, Hangul as character bigrams. Symbol-matching notes boosted;
    notes cited by a profile claim whose text overlaps the question boosted. Never raises; returns
    the most-recent `cap` notes when the question has no informative tokens."""
```

`char_budget` is the sum of `len(note.summary)` over the returned notes (a proxy for prompt size);
stop adding once it would exceed the budget, but always return at least one note when any exist.

## Wire types (TypeScript mirror of `models.py`)

```ts
type ChatLang = "en" | "ko";

interface ChatTurn {
  turn_id: string;            // uuid
  asked_at: string;           // ISO-8601
  question: string;
  symbol: string | null;
  lang: ChatLang;
  answer: string;             // persona's voice, grounded
  citations: string[];        // note_ids used, ⊆ retrieved
  retrieved: string[];        // note_ids handed to the model this turn (audit)
  stance: Stance | null;      // only when a symbol was asked and the record supports one
  grounding: GroundingVerdict;
  degraded: boolean;
  cost_usd: string;           // decimal string
}

interface ChatThread {
  thread_id: string;
  persona: string;            // slug
  title: string;              // first question, ≤ 80 chars
  created_at: string;
  updated_at: string;
  turn_count: number;
  spent_usd: string;          // decimal string, sum of turns' cost_usd
  turns: ChatTurn[];          // oldest first; [] on the list endpoint
}

interface ChatContext {
  profile_version: number;    // 0 = never consolidated
  profile_note_count: number; // notes the profile was built from
  note_count: number;         // notes on disk
  stale: boolean;             // never consolidated, OR note_count > profile_note_count
}
```

## Endpoints

```
GET    /api/personas/{slug}/chats                      -> ChatThread[]  (turns: [], newest updated_at first)
POST   /api/personas/{slug}/chats                      -> ChatThread    (201, empty thread)
GET    /api/personas/{slug}/chats/{thread_id}          -> ChatThread    (404 unknown persona/thread)
DELETE /api/personas/{slug}/chats/{thread_id}          -> 204
POST   /api/personas/{slug}/chats/{thread_id}/turns
         {question: string (1-2000), symbol?: string, lang?: ChatLang} -> ChatTurn
GET    /api/personas/{slug}/chat-context               -> ChatContext
```

`POST …/turns` errors: 404 unknown persona/thread; 409 persona has no notes / thread turn cap
(`MAX_TURNS = 40`) / thread budget cap (`persona_chat_cap_usd`); 429 daily spend cap (existing
`app.agents.spend_http` handler, uncaught); 503 model unavailable. Synchronous — one grounded call.

## Semantics (a worker must not vary these)

- **Turn assembly.** System prompt = the Phase-4 ask system prompt + conversational continuity rules
  (may build on earlier turns; still never advice, never off-record). Context order: last
  `MAX_HISTORY_TURNS = 8` (question, answer) pairs → profile (rendered by
  `app.personas.ask._render_profile`) → retrieved notes → market snapshot (when `symbol`) → the new
  question. Older turns are dropped, never summarised (a summary is uncited prose).
- **Evidence pack** = profile + notes + snapshot + one "earlier answers in this thread" section that
  includes **only non-degraded** prior answers — a number that failed the gate once must not launder
  itself into a later turn's grounded set.
- **Grounding** via `app.agentdesk.grounding.run_grounded`, exactly as `ask_persona`. Degraded
  answers are returned flagged, never raised.
- **Citations** filtered to the notes actually handed to this turn (`ask._filter_citations` rule);
  `retrieved` records the full handed set for audit. **Stance** `None` unless a `symbol` was asked.
- **Budget.** `LEDGER.check(settings.model_spend_daily_cap_usd)` before each turn; per-thread
  `AgentBudget(cap_usd=persona_chat_cap_usd)` (default `"2"`); every `AgentCall` archived like ask's.
  `persona_chat_model` (default `app.agents.models.DEFAULT_MODEL`) selects the model.
- **Language** from the request `lang` (default `settings.persona_summary_lang`); quotes stay verbatim
  in source language.

## Vault layout additions

```
<vault>/influencers/<slug>/
  chats/<thread_id>.json        the ChatThread (source of truth for the API); an Obsidian .md mirror is Phase 3
```

## Guardrails (enforced in code, checked by QA)

- Every answer is labelled "a model's impression of <name>, from cited notes" — never the person,
  never advice. Citations and the `degraded` flag are always visible, never behind a disclosure.
- A persona with no notes is 409, not an invented answer. `unclear` stance reads as "no clear stance".
- New settings: `persona_chat_cap_usd: str = "2"`, `persona_chat_model: str = DEFAULT_MODEL`.

---

# Phase 10 — persona paper trader (pinned)

Seats each persona as a **model-driven** paper trader on the Paper Desk. Unlike Phase 6's
`app.personas.paperbook` (a deterministic replay of dated calls), this asks the model, as the persona,
what to buy/sell at each weekly decision using its consolidated method and a point-in-time market
snapshot. Orders fill at the next session's open through `app.paper.paperbroker.PaperBroker` +
`default_mandate` (cash discipline, position caps, no look-ahead enforced centrally). Engine:
`app.personas.trader` (built + proven). Same rules as every phase: frozen models, thin router,
degrade rather than 5xx, grounded, never advice.

**Two caveats every UI MUST render (do not conflate):** (1) market data is point-in-time (no
look-ahead on price), but the persona's *method* is distilled from its whole corpus, so this is "how
their stated approach would have traded," not a real-time record; (2) the repo's own research found no
measured edge — this is descriptive/experimental, never promoted or treated as skill, never advice.

## Wire types (TS mirror of `app.personas.trader`)

```ts
interface TraderPosition { symbol: string; quantity: string; last_price: string; market_value: string; weight: number; }
interface TraderTradeRec { decided_on: string; fill_date: string; symbol: string; side: "buy"|"sell"; quantity: string; price: string; thesis: string; }
interface TraderRejectionRec { decided_on: string; symbol: string; side: string; reason: string; }
interface TraderDecisionRec { decided_on: string; fill_date: string; commentary: string; degraded: boolean; cost_usd: string; trades: TraderTradeRec[]; rejections: TraderRejectionRec[]; }
interface TraderEquityPoint { date: string; equity: string; }
interface TraderBook {
  persona: string; display_name: string; inception: string; as_of: string | null;
  starting_cash: string; cash: string; equity: string; return_pct: string;   // return_pct: 0-1 fraction
  benchmark: string; benchmark_return_pct: string | null; excess_pct: string | null;  // SPY buy-and-hold over the same window; null if unpriceable
  positions: TraderPosition[]; equity_curve: TraderEquityPoint[];
  decisions: TraderDecisionRec[];                                             // newest first
  spent_usd: string; warnings: string[];
}
type TraderJobState = "queued" | "running" | "succeeded" | "failed";
interface TraderJob {
  job_id: string; persona: string; state: TraderJobState;
  decided_count: number; started_at: string | null; finished_at: string | null;
  spent_usd: string; error: string | null;
}
```

## Endpoints

```
GET    /api/personas/trader/books                     -> TraderBook[]   (one per persona; always 200)
GET    /api/personas/{slug}/trader                    -> TraderBook     (404 unknown persona; empty book if never traded)
DELETE /api/personas/{slug}/trader                    -> 204            (reset the book)
POST   /api/personas/{slug}/trader/decide             -> TraderBook     (run ONE decision at the latest session now; sync, one grounded call)
POST   /api/personas/{slug}/trader/backfill {inception?: "YYYY-MM-DD"} -> TraderJob (202; async weekly backfill from inception)
GET    /api/personas/{slug}/trader/backfill/{job_id}  -> TraderJob      (poll; 409 on POST if one active for the persona)
```

`decide` errors: 404 unknown persona; 409 daily/decision budget; 503 model unavailable. `backfill`
runs asynchronously (many model calls) via a background thread + in-memory job registry, mirroring
`app.personas.jobs` ingest jobs; `inception` defaults to `app.personas.trader.DEFAULT_INCEPTION`
(2026-01-01). Both spend paths call `LEDGER.check(model_spend_daily_cap_usd)` before each decision and
are bounded by `persona_trader_decision_cap_usd` (per call) / `persona_trader_backfill_cap_usd`
(per backfill run).

## Vault layout

```
<vault>/influencers/<slug>/trader/book.json    the trader book (broker state + equity curve + decision log + inception + spend)
```

## Settings + daemon

`persona_trader_decision_cap_usd="1"`, `persona_trader_backfill_cap_usd="15"`,
`persona_trader_model=DEFAULT_MODEL`, `persona_trader_enabled=False`. When enabled,
`app.personas.trader_loop.start` (mirroring `app.personas.refresh_loop`) advances each persona's book
forward one weekly decision as new sessions arrive — opt-in because it spends tokens unattended. The
decide/backfill endpoints work regardless of the flag.

## Frontend

Render each `TraderBook` on the Paper Desk beside the reference-agent and Phase-6 replay books: the
equity curve, current holdings, return, and the decision log (each decision's commentary + trades +
rejections + degraded flag). An on-demand "Run this week's decision" button (`decide`), a backfill
trigger with an inception date input (`backfill` + poll), and both caveats always visible. Money
fields are decimal strings; `return_pct` is a 0-1 fraction (×100 to display).
