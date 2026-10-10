/**
 * Typed client for the Influencer Personas feature.
 *
 * Mirrors `docs/INFLUENCER-CONTRACT.md` field for field -- that document is pinned and authoritative
 * over this file, not the other way around. If a shape here ever looks wrong, the contract wins;
 * fix this file, do not invent a replacement shape.
 *
 * **`GroundingIssue`/`GroundingVerdict` are a local copy, not an import.** The contract says these
 * are reused verbatim from `app.agentdesk.models` on the *backend*; on the frontend this codebase's
 * own convention is "one copy per module" -- `@/api/tradingagents`, `@/api/vibedesk` and
 * `@/api/workflow` each already carry their own identical copy of these two interfaces rather than
 * sharing one, precisely so a change to one module's grounding handling can never silently change
 * another's. This module follows the same rule.
 *
 * **Money is a decimal string, never a JSON number.** `IngestJob.spent_usd` is a `DecimalString`
 * (`@/api/client`) -- `formatMoney` below is a local copy of the same string/BigInt digit-shifting
 * rule `@/api/tradingagents`'s and `@/api/tax`'s own `formatMoney` already establish, built on
 * `@/api/client`'s `parseDecimalString`. Never `Number`/`parseFloat` on `spent_usd`.
 *
 * **`POST /api/personas` and `DELETE /api/personas/{slug}` currently answer `501`** while the
 * backend for them lands in Phase 1 -- see the contract. The body is a plain FastAPI
 * `{"detail": "..."}` explaining that. `describePersonaActionError` below unwraps that `detail` the
 * same way `@/api/tradingagents`'s `describeStartRunError` unwraps a `422`/`409`/`503` body, so the
 * UI can show the backend's own explanation rather than a generic "something went wrong" -- and
 * needs no change at all once the backend actually lands, since the response shape does not change,
 * only the status code.
 *
 * **`POST /api/personas/{slug}/ingest` is real, not a `501` stub.** It enforces the contract's own
 * rules server-side: a `drop` without `text` is a `422` ("pasting the text is required"), a
 * `video_urls` entry the server cannot read a video id out of is a `422` naming the offending value,
 * and a second ingest while one is already running for the persona is a `409`. `IngestPanel` (in
 * `PersonaCard.tsx`) mirrors these as client-side guardrails -- never submitting an empty
 * `video_urls` list or a `drop` missing `text` -- but the server remains the authority; every
 * rejection's `detail` still surfaces verbatim through `describePersonaActionError`, never swallowed.
 *
 * **Copy discipline.** Every stance below is *the influencer's own view*, never this application's
 * measurement or a recommendation -- `Stance.unclear` renders as "no clear stance", not folded into
 * "neutral". `STANCE_LABELS` is the one place that wording lives; `PersonaCard.tsx` reads it from
 * here rather than restating it.
 *
 * **Phase 2 -- persona consolidation.** `PersonaProfile`/`TickerThesis`/`ProfileClaim` and the four
 * `consolidate`/`getProfile`/`theses`/`thesis` calls below mirror `docs/INFLUENCER-CONTRACT.md`'s
 * "Phase 2 -- persona consolidation" section field for field, same as everything above. Two rules
 * from that section that the consuming UI (`PersonaProfile.tsx`) exists to enforce, not merely
 * style:
 *  - **`ProfileClaim.citations` must always render.** The contract states a claim with empty
 *    `citations` is invalid and never persisted -- the whole point of a profile is that a reader can
 *    see a belief/playbook line traces back to actual notes rather than being invented, so hiding the
 *    citation list (e.g. behind a hover) would defeat that.
 *  - **`GET /profile` answering `404` means "never consolidated", not an error.** Every consolidated
 *    persona was consolidated once; a fresh one has no `profile.md` yet, which is a valid, common
 *    empty state -- `PersonaProfile.tsx` renders that as an invitation to consolidate, not a fetch
 *    failure. `POST /consolidate` itself is synchronous (tens of seconds, one model call over notes
 *    already on disk) rather than a job-registry endpoint like `startIngest` above -- there is
 *    nothing to poll.
 *
 * **Phase 3a -- call scoring.** `CallOutcome`/`CallScore`/`PersonaScorecard` and `scorecard` below
 * mirror `docs/INFLUENCER-CONTRACT.md`'s "Phase 3a -- call scoring" section field for field. This
 * measurement is descriptive and backward-looking only -- "if you had acted on what they said, on
 * the day they said it, what would the market have done since" -- never a claim the influencer beat
 * the market and never advice; `PersonaScorecard.tsx` states that caption up front, not this module.
 * Two rules worth flagging because they read differently from Phase 2's endpoints just above:
 *  - **`GET /scorecard` answering `404` means "unknown persona slug"**, unlike `getProfile`'s `404`
 *    ("never consolidated yet") -- there is no "not yet scored" empty state at the HTTP-status level
 *    for this endpoint; a persona with no dated calls still answers `200` with `scored_calls: []` and
 *    `hit_rate: null`. `PersonaScorecard.tsx` therefore has no `not_found` phase the way
 *    `ProfileFetchState` does -- a `404` here renders as a genuine error.
 *  - **`hit_rate: null` and `median_return_pct: null` are not zero.** `null` means "not enough scored
 *    calls yet" (an empty or all-`pending`/`no_data`/`not_directional` denominator); `0` is a real,
 *    distinct measurement ("scored plenty of calls, none played out" / "median return is exactly
 *    0%"). Never render one as the other.
 */

import { ApiRequestError, type DecimalString } from "@/api/client";
import { formatMoney } from "@/format/money";
import { t, type MessageKey } from "@/i18n";

// --- shared wire types (docs/INFLUENCER-CONTRACT.md "Wire types") ---------------------------------

export type Platform = "youtube" | "manual"; // "telegram" | "x" added in Phase 5
export type IngestState = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type Stance = "bullish" | "bearish" | "neutral" | "unclear";
export type TranscriptSource = "manual" | "auto" | null;
export type NoteKind = "video_transcript" | "post" | "manual";

/** What kind of instrument a symbol is, set at mention time. Legacy mentions (written before this
 * field existed) load as "equity" -- the backend's own default, not a frontend fallback. */
export type InstrumentKind = "equity" | "etf" | "index" | "future" | "crypto" | "fx" | "unknown";

/** The holding horizon the speaker implied for a call -- a day-trader's "bullish" is intraday, not
 * a position. "unclear" is the honest default, and what every legacy mention loads as. */
export type Horizon = "intraday" | "swing" | "position" | "long_term" | "unclear";

/** Risk posture a macro/regime commentator implied -- the counterpart to a technical trader's
 * methodology, for personas with no mechanical toolkit. */
export type RiskPosture = "on" | "off" | "mixed" | "unclear";

/** Local copy -- see this module's own docstring for why it is not imported from another module. */
export interface GroundingIssue {
  kind: "ungrounded_number" | "no_evidence" | "empty_output";
  detail: string;
}

/** Whether a card's summary was checked against the evidence (the transcript/post) it was built
 * from. `degraded: true` means the check failed and the summary is shown anyway, marked as such --
 * see `DigestCard.grounding` and `PersonaCard.tsx`'s rendering of it. Never hidden. */
export interface GroundingVerdict {
  ok: boolean;
  issues: GroundingIssue[];
  attempts: number;
  degraded: boolean;
  checked_tokens: number;
}

export interface FollowedSource {
  source_id: string; // "yt:<channelId>" | "manual:<uuid>"
  platform: Platform;
  handle: string; // "@creator-a" as typed
  channel_id: string | null; // UC… for youtube, null for manual
  url: string;
  enabled: boolean;
  added_at: string;
}

/** THE INFLUENCER'S stance, not ours -- see this module's docstring on copy discipline. */
export interface TickerMention {
  symbol: string; // validated against the instrument table; uppercase
  stance: Stance;
  reasoning: string; // paraphrase; may embed a short verbatim quote
  instrument: InstrumentKind; // defaults to "equity" server-side for legacy mentions
  horizon: Horizon; // defaults to "unclear" server-side for legacy mentions
}

export interface EpisodicNote {
  note_id: string; // stable: platform-native id (youtube video id) or uuid
  persona: string; // persona slug
  source_id: string;
  published: string | null; // ISO-8601 upload date; null when the upstream cannot tell us
  ingested_at: string;
  url: string;
  title: string | null;
  kind: NoteKind;
  transcript_source: TranscriptSource;
  lang: string; // source language of the transcript, e.g. "ko"
  summary: string;
  themes: string[]; // 2-5 short bullets: what this item was about
  quotes: string[]; // verbatim, source language
  mentions: TickerMention[];
  path: string; // vault-relative path to the note .md
  degraded: boolean; // this note's own summary was released despite failing the grounding gate
}

/** One upstream that could not be reached / priced on the last refresh -- named `DigestWarning` in
 * `backend/app/personas/models.py`; reused verbatim here rather than left as the anonymous inline
 * shape this module used before every consumer of a `warnings` array had the same fields. */
export interface DigestWarning {
  source: string;
  reason: string;
}

export interface Persona {
  slug: string; // "creator-a"
  display_name: string; // "Creator A"
  sources: FollowedSource[];
  note_count: number;
  tickers: string[]; // validated symbols seen across notes, most-recent first
  profile_version: number; // 0 = never consolidated
  consolidated_at: string | null;
  created_at: string;
}

/** One card per followed influencer -- the /personas page's whole reason to exist. `as_of === null`
 * and `headline === ""` both mean "no notes ingested yet", a valid, renderable state -- see
 * `PersonaCard.tsx`'s empty-state handling, not an error and not a loading spinner. */
export interface DigestCard {
  persona: Persona;
  as_of: string | null; // newest note's ingested_at; null = no notes yet
  window_start: string | null;
  note_count: number;
  headline: string; // one sentence; "" when no notes
  themes: string[]; // 2-5 bullets: what they are trading / focused on
  mentions: TickerMention[]; // aggregated, deduped by symbol, newest stance wins
  latest_note: EpisodicNote | null;
  /** AGGREGATE over the window's notes, not one model call's record -- amended into the contract
   * after this module's first draft. Only `ok` and `degraded` are meaningful here; `issues`,
   * `attempts` and `checked_tokens` stay at their zero/empty defaults and must never be rendered
   * from this field (an "attempts: 1" or "checked_tokens: 0" on a card would present a default as a
   * measurement). Per-note truth lives on `EpisodicNote.degraded` instead -- read that for a
   * drill-down into which specific note failed its check. */
  grounding: GroundingVerdict;
  warnings: DigestWarning[];
}

export interface IngestJob {
  job_id: string;
  persona: string;
  state: IngestState;
  items_total: number;
  items_done: number;
  items_failed: number;
  started_at: string | null;
  finished_at: string | null;
  spent_usd: DecimalString;
  error: string | null; // null unless state === "failed"
}

/** A statistic reported WITH its denominator and uncertainty, never bare -- every rate or mean this
 * feature shows a reader is over a small, single-window sample. `point`/`low`/`high` are all `null`
 * when `n === 0`: an estimate over nothing is undefined, not zero, the same discipline `hit_rate`
 * already applies. `low`/`high` bound a confidence interval at `confidence` (0.90 default). */
export interface StatEstimate {
  n: number;
  point: number | null;
  low: number | null;
  high: number | null;
  confidence: number;
  method: "bootstrap" | "wilson" | "none";
}

/** A macro/regime commentator's structured market posture -- the counterpart to a technical
 * trader's methodology, for personas that describe no mechanical toolkit. `has_signal` is `false`
 * for a persona that offers no macro view (a pure technical trader) -- the same honest-empty
 * discipline `methodology` uses. Descriptive, never a trading signal. */
export interface RegimeView {
  risk: RiskPosture;
  rates: string;
  summary: string;
  sectors_favoured: string[];
  sectors_avoided: string[];
  citations: string[];
  has_signal: boolean;
}

// --- Phase 2: persona consolidation (docs/INFLUENCER-CONTRACT.md "Phase 2 -- persona consolidation") --

/** One belief/playbook statement in a `PersonaProfile`, or one line of a `TickerThesis`. `citations`
 * are `EpisodicNote.note_id`s -- per the contract, a claim with empty `citations` is invalid and the
 * backend never persists one; `PersonaProfile.tsx` renders every citation, never hides them. */
export interface ProfileClaim {
  text: string; // one belief / playbook statement, in the summary language
  citations: string[]; // note_ids backing it; MUST be non-empty
}

/** The consolidated view of an influencer, folded from their episodic notes -- who they are, what
 * they believe, how they trade. Unlike an `EpisodicNote` this IS rewritten on every consolidation
 * (`version` increments, `profile.history/<timestamp>.md` keeps the prior copy server-side), so its
 * `beliefs`/`playbook` claims cite the notes they were built from rather than being trusted on their
 * own -- see this module's docstring, "Phase 2". */
export interface PersonaProfile {
  persona: string; // slug
  version: number; // 1 on first consolidation, +1 each rewrite
  consolidated_at: string; // ISO-8601
  note_count: number; // how many notes this version was built from
  summary: string; // who they are and what they trade, 2-4 sentences
  beliefs: ProfileClaim[]; // what they think the market is doing
  playbook: ProfileClaim[]; // how they actually trade: setups, entries, risk habits
  /** HOW they trade, not what -- the mechanical toolkit: named indicators, chart timeframes,
   * entry/exit triggers, stop/position-sizing and risk rules. Distinct from `playbook` (strategic
   * what-they-do): this is the technique. Empty for a persona whose notes never discuss technique
   * (a pure macro commentator) -- itself an honest signal. */
  methodology: ProfileClaim[];
  /** The persona's structured macro/regime posture -- the counterpart to `methodology` for a
   * commentator with no mechanical toolkit. `null` on a profile consolidated before this field
   * existed, and `has_signal: false` for a purely technical persona. */
  regime: RegimeView | null;
  vocabulary: string[]; // recurring terms/names they use
  degraded: boolean; // released despite failing the grounding gate
  path: string; // vault-relative path to profile.md
}

/** The influencer's running view on one symbol, folded across every note that mentioned it. */
export interface TickerThesis {
  persona: string;
  symbol: string;
  stance: Stance; // their latest stance on it
  updated_at: string;
  claims: ProfileClaim[];
  path: string;
}

// --- Phase 3a: call scoring (docs/INFLUENCER-CONTRACT.md "Phase 3a -- call scoring") -----------

/** How one dated call played out against the market -- see `CallScore.outcome` and this module's
 * docstring, "Phase 3a". `pending` and `no_data` both leave `CallScore.return_pct` `null`, but for
 * different reasons (too recent to have a later bar vs. no usable price series at all) -- both are
 * distinct from `not_directional` (a real return exists, the stance just was not directional). */
export type CallOutcome =
  | "played_out"
  | "went_against"
  | "flat"
  | "not_directional"
  | "pending"
  | "no_data";

/** A call's return a fixed number of TRADING days after entry. `complete` is `false` (and
 * `return_pct` `null`) when fewer than `days` bars exist after the entry bar yet -- the horizon has
 * not elapsed, so no return is extrapolated. Makes calls comparable across time: a July call and an
 * August call are both judged over the same 5/20/60-bar window. */
export interface HorizonReturn {
  days: number;
  return_pct: number | null;
  complete: boolean;
}

/** One scored call -- one note's `TickerMention`, dated by that note's `published`, priced against
 * the symbol's daily bars. `entry_price`/`entry_date`/`latest_price`/`latest_date`/`return_pct`/
 * `basis` are all `null` together for `pending`/`no_data` outcomes; never partially populated. */
export interface CallScore {
  symbol: string;
  stance: Stance;
  note_id: string;
  said_on: string; // the note's published date (ISO)
  entry_date: string | null; // actual first trading close used; null for pending/no_data
  entry_price: number | null;
  latest_date: string | null;
  latest_price: number | null;
  return_pct: number | null; // null for pending/no_data
  basis: "adjusted" | "close" | null; // which price basis was used
  outcome: CallOutcome;
  /** Fixed-horizon returns (5/20/60 trading days after entry), empty for `pending`/`no_data` calls.
   * The return-to-today fields above are "so far"; these are the window-independent measure. */
  horizons: HorizonReturn[];
}

/** Aggregate at one fixed horizon over the directional calls whose horizon has fully elapsed.
 * `hit_rate`/`median_return_pct` are `null` when `directional_count === 0` -- undefined, not zero. */
export interface HorizonStat {
  days: number;
  directional_count: number;
  played_out: number;
  hit_rate: number | null;
  median_return_pct: number | null;
  mean_return_pct: number | null;
  /** Wilson interval for `hit_rate` at this horizon. `null` when `directional_count === 0`. */
  hit_rate_ci: StatEstimate | null;
  /** Bootstrap interval for the MEAN horizon return. `null` when no call has an elapsed return here. */
  return_ci: StatEstimate | null;
}

/** One persona's dated-call track record -- see this module's docstring, "Phase 3a", for the two
 * rules (the `404` semantics and the `null`-vs-`0` distinction on `hit_rate`/`median_return_pct`)
 * `PersonaScorecard.tsx` exists to enforce.
 *
 * The top-level `hit_rate`/`median_return_pct` are return-to-today ("so far"); `horizon_stats`
 * carries the window-independent aggregates at each fixed horizon. */
export interface PersonaScorecard {
  persona: string;
  as_of: string;
  scored_calls: CallScore[]; // newest said_on first
  directional_count: number; // calls in the hit-rate denominator
  played_out: number;
  hit_rate: number | null; // played_out / directional_count, null when denominator is 0
  median_return_pct: number | null; // median signed return over directional priced calls
  /** Wilson interval for the return-to-today `hit_rate`. `null` when no directional call had price
   * data. The single most important honesty signal on the card -- a hit rate of 0.16 over n=192 and
   * one over n=6 must not read the same. */
  hit_rate_ci: StatEstimate | null;
  horizon_stats: HorizonStat[];
  warnings: DigestWarning[]; // symbols/dates that could not be scored
}

// --- Phase 6/7: timeline, ask, books, regime, watchlist, strategy cards, critique, backtest --------

/** One dated stance the influencer took on a symbol -- a single point on its evolution. */
export interface StancePoint {
  note_id: string;
  said_on: string;
  stance: Stance;
  reasoning: string;
}

/** How one symbol's stance evolved. `points` OLDEST first so it reads as a story forward in time
 * (bullish in July, cautious in August, ...). */
export interface StanceTimeline {
  symbol: string;
  points: StancePoint[];
}

/** One note placed on the persona's chronological timeline. */
export interface TimelineEntry {
  note_id: string;
  published: string | null;
  title: string | null;
  summary: string;
  themes: string[];
  symbols: string[];
  url: string;
}

/** The persona's notes as a dated timeline plus per-symbol stance evolution -- a pure read over
 * stored notes, no model call, no market fetch. `entries` newest first; `stance_timelines` lists
 * symbols whose stance actually changed first, then by mention count. */
export interface PersonaTimeline {
  persona: string;
  entries: TimelineEntry[];
  stance_timelines: StanceTimeline[];
}

/** A model's impression of what the influencer would say, grounded in their own profile and notes.
 * Explicitly not the person and not advice. `citations` are the note_ids the answer drew on; empty
 * only when the persona has no notes yet, in which case `answer` says so rather than inventing a
 * view. `stance` is filled only when a `symbol` was asked about and the record supports one. */
export interface PersonaAnswer {
  persona: string;
  question: string;
  symbol: string | null;
  answer: string;
  citations: string[];
  stance: Stance | null;
  grounding: GroundingVerdict;
  degraded: boolean;
  cost_usd: DecimalString;
}

// --- Phase 9: persona chat (multi-turn) -----------------------------------------------------------

/** The UI language a chat turn was asked in -- distinct from `Stance`/`Language` (in `@/i18n`), a
 * local copy per this module's "one copy per module" convention (see this module's own docstring). */
export type ChatLang = "en" | "ko";

/** One question/answer exchange in a chat thread -- the multi-turn successor to a single `ask()`
 * call. `retrieved` is an audit trail (every note_id handed to the model this turn), distinct from
 * `citations` (the note_ids the answer actually drew on) -- the same "cited vs considered"
 * distinction other panels in this module already draw. */
export interface ChatTurn {
  turn_id: string;
  asked_at: string; // ISO-8601
  question: string;
  symbol: string | null;
  lang: ChatLang;
  answer: string;
  citations: string[];
  retrieved: string[]; // note_ids handed to the model this turn (audit)
  stance: Stance | null;
  grounding: GroundingVerdict;
  degraded: boolean;
  cost_usd: DecimalString;
}

/** One chat conversation with a persona. `turns` is `[]` on the list endpoint (`GET /chats`) and
 * populated on a single-thread fetch or right after a turn -- callers must not assume it is always
 * present, matching `ProfileFetchState`'s own discipline about what an endpoint actually returns. */
export interface ChatThread {
  thread_id: string;
  persona: string;
  title: string;
  created_at: string;
  updated_at: string;
  turn_count: number;
  spent_usd: DecimalString;
  turns: ChatTurn[]; // [] on the list endpoint; populated on GET one / after a turn
}

/** Whether the persona's consolidated profile is stale relative to its own notes -- informational,
 * never blocking: the chat still answers while stale, per `PersonaChat.tsx`'s own stale-profile note. */
export interface ChatContext {
  profile_version: number;
  profile_note_count: number;
  note_count: number;
  stale: boolean;
}

/** Body for `POST /{slug}/chats/{thread_id}/turns`. `symbol`/`lang` are omitted entirely, not sent
 * as `null`/`undefined`, when absent -- same `exactOptionalPropertyTypes` discipline as `AskRequest`
 * above. */
export interface ChatTurnRequest {
  question: string;
  symbol?: string;
  lang?: ChatLang;
}

/** One OPEN position in a persona's cash-constrained paper book: a paper buy of a symbol the
 * persona was bullish on at `entry_date`, sized at `notional_per_position` cash allowing, marked to
 * the latest close. Money/quantity fields are decimal strings, never numbers -- never
 * `Number()`/`parseFloat()` them. `return_pct` is a 0-1 FRACTION on the wire (`"0.0642"` = 6.42%),
 * never a whole percent -- render it through `formatSignedFractionPctString`, never a raw `%`
 * suffix, or a real +6.42% return renders as the historical "+6427%" bug this shape replaces.
 * `last_bullish_on` is the most recent note date on which the persona was still bullish on this
 * symbol -- distinct from `entry_date` (when the paper position was opened), since a persona can
 * keep restating the same bullish call across many notes without the book re-entering. Not advice,
 * not a real position. */
export interface PersonaHolding {
  symbol: string;
  stance: Stance;
  note_id: string;
  entry_date: string;
  entry_price: DecimalString;
  quantity: DecimalString;
  cost_basis: DecimalString;
  last_price: DecimalString;
  last_price_date: string;
  market_value: DecimalString;
  unrealised_pnl: DecimalString;
  return_pct: DecimalString; // fraction, e.g. "0.0642" = 6.42%
  bars_held: number;
  weight: number;
  last_bullish_on: string;
}

/** One CLOSED position: a former `PersonaHolding` the book sold, either because the persona's own
 * stance flipped away from bullish (`reason: "flip_bearish" | "flip_neutral"`) or because the cash
 * it tied up was needed to fund a fresher call once the book was fully invested
 * (`reason: "replaced"`). `return_pct` is a 0-1 fraction, same rule as `PersonaHolding.return_pct`. */
export interface PersonaTrade {
  symbol: string;
  note_id: string;
  entry_date: string;
  entry_price: DecimalString;
  exit_date: string;
  exit_price: DecimalString;
  quantity: DecimalString;
  realised_pnl: DecimalString;
  return_pct: DecimalString; // fraction
  reason: "flip_bearish" | "flip_neutral" | "replaced";
}

/** One bullish call the book saw but never opened a paper position for -- named so the gap is
 * visible rather than silently dropped: `"no_cash"` (the book was fully invested and this call was
 * not fresh enough to bump anything out), `"no_market_data"` (the symbol could not be priced), or
 * `"no_bar_since"` (no trading bar exists on/after the call date yet to enter at). */
export interface PersonaSkippedCall {
  symbol: string;
  said_on: string;
  reason: "no_cash" | "no_market_data" | "no_bar_since";
}

/** A persona's cash-constrained paper book: a single paper account starting at `starting_cash`,
 * spending up to `notional_per_position` cash on each fresh bullish call (since `inception`) as cash
 * allows, selling on a bearish/neutral flip or to fund a fresher call when fully invested. Descriptive,
 * not advice. `as_of` is the latest mark date, `null` when the book has never priced anything.
 * `equity` is `cash + market_value_total`; `return_pct` is `equity / starting_cash - 1`, a 0-1
 * FRACTION on the wire -- see `PersonaHolding`'s docstring on the historical percent-vs-fraction bug.
 * `warnings` names symbols that could not be priced -- excluded from the book, never counted as
 * zero. */
export interface PersonaBook {
  persona: string;
  display_name: string;
  inception: string;
  as_of: string | null;
  starting_cash: DecimalString;
  notional_per_position: DecimalString;
  cash: DecimalString;
  equity: DecimalString;
  holdings: PersonaHolding[];
  cost_basis_total: DecimalString;
  market_value_total: DecimalString;
  unrealised_pnl_total: DecimalString;
  realised_pnl_total: DecimalString;
  return_pct: DecimalString; // fraction: equity/starting_cash - 1
  trade_count: number;
  open_count: number;
  trades: PersonaTrade[];
  skipped: PersonaSkippedCall[];
  warnings: DigestWarning[];
}

/** One persona's regime view for the `/regime` endpoint. `has_view` mirrors `view.has_signal` at the
 * top level so a caller can filter without unpacking. */
export interface PersonaRegime {
  persona: string;
  display_name: string;
  view: RegimeView;
  has_view: boolean;
  as_of: string | null;
}

/** The cross-persona macro picture: each persona's regime view, plus a tally of how many lean
 * risk-on vs risk-off. A reference input, never a signal -- `caveat` (always rendered) says so. */
export interface RegimeConsensus {
  as_of: string;
  personas: PersonaRegime[];
  risk_on: number;
  risk_off: number;
  mixed: number;
  caveat: string;
}

/** One symbol on the cross-persona influencer watchlist: how many followed personas are CURRENTLY
 * bullish (vs bearish) on it, who, and one backing reason from the most recent bullish note. A
 * reference for the strategy layer or the owner -- descriptive, never a buy list. */
export interface WatchlistEntry {
  symbol: string;
  bullish_count: number;
  bearish_count: number;
  personas: string[];
  latest_reasoning: string;
  as_of: string | null;
  instrument: InstrumentKind;
}

/** The current-bullish tickers aggregated across every persona, ranked by how many influencers back
 * each. `caveat` (always rendered) states this is a reference, not a recommendation. */
export interface InfluencerWatchlist {
  as_of: string;
  entries: WatchlistEntry[];
  caveat: string;
}

/** A rule-card the persona's METHODOLOGY was mapped onto -- an exploration lens, never advice or a
 * promise of edge. `mapped` is `false` -- with `reason` -- for a persona that describes no
 * mechanical methodology or whose mapping the card validators rejected; in that case `card`/
 * `rule_shape` are `null` and nothing is invented. `caveat` (always shown) states the inspired-by,
 * no-edge-expected framing. */
export interface StrategyCardDraft {
  persona: string;
  mapped: boolean;
  reason: string;
  rule_shape: string | null;
  card: Record<string, unknown> | null;
  rationale: string;
  citations: string[];
  caveat: string;
  degraded: boolean;
  cost_usd: DecimalString;
  /** Monotonic version of this persisted draft (0 = unsaved). */
  version: number;
  /** `techniques_represented / techniques_total` -- how much of the persona's methodology the fixed
   * rule-shape DSL could actually express. `null` when unmapped. Low fidelity is the honest signal
   * that the card is a loose caricature of a rich method, not a faithful port. */
  fidelity: number | null;
  techniques_total: number;
  techniques_represented: number;
  /** Methodology techniques the DSL cannot express, named so the gap is visible rather than
   * silently dropped. */
  unrepresentable: string[];
}

/** A `StrategyCardDraft` plus its save metadata, as persisted under `strategy/<version>.json` and
 * listed by the drafts endpoint. */
export interface SavedStrategyDraft {
  draft: StrategyCardDraft;
  saved_at: string;
  filename: string;
}

/** The library card a promoted persona draft becomes (`app.tournament.models.StrategyCard`). Only
 * the fields the UI reads back are typed; the card carries more, but the caller only needs to confirm
 * what landed and name it. */
export interface PromotedPersonaCard {
  agent_id: string;
  display_name: string;
  source_persona: string;
}

/** One difference between two profile versions: a claim added, removed, or kept but re-cited to
 * different notes. `section` says which part of the profile it belongs to. */
export interface ClaimChange {
  kind: "added" | "removed" | "recited";
  section: "belief" | "playbook" | "methodology";
  text: string;
  citations: string[];
}

/** What changed in a persona's memory between two consolidations -- is this persona's profile
 * improving or just churning? Counts are convenience aggregates over `changes`. */
export interface ProfileDiff {
  persona: string;
  from_version: number;
  to_version: number;
  changes: ClaimChange[];
  added: number;
  removed: number;
  recited: number;
}

/** A persona's in-voice assessment of a strategy card, grounded in their own methodology and
 * beliefs -- the reverse of the persona->card mapping. A reading lens, not advice: `verdict` says
 * how well the card fits how THEY trade, `cannot_say` when the record does not support a judgement.
 * `caveat` (always rendered) states it is an impression of their view, not the person and not
 * advice. */
export interface CardCritique {
  persona: string;
  verdict: "aligned" | "mixed" | "misaligned" | "cannot_say";
  assessment: string;
  citations: string[];
  caveat: string;
  degraded: boolean;
  cost_usd: DecimalString;
}

/** One fixed horizon's aggregate for the persona-backtest lens: the persona's mean signed call
 * return vs the benchmark over the SAME entry->exit windows. All fields `null` when no directional
 * call had both a complete horizon and a benchmark window at this horizon -- undefined, not zero. */
export interface BenchmarkedHorizon {
  days: number;
  n: number;
  mean_return_pct: number | null;
  mean_benchmark_pct: number | null;
  excess_pct: number | null;
  win_rate_vs_benchmark: number | null;
  /** Bootstrap interval for `excess_pct` (per-call excess over the benchmark). `null` when `n === 0`.
   * Over these sample sizes the interval almost always straddles zero -- which is the honest finding. */
  excess_ci: StatEstimate | null;
}

/** A DESCRIPTIVE lens, not a strategy or an alpha claim: how following the persona's dated calls
 * would have compared to holding the benchmark, over the same windows. `caveat` is a fixed string
 * the UI must render -- small samples over a single window are not evidence of skill. */
export interface PersonaBacktest {
  persona: string;
  as_of: string;
  benchmark: string;
  call_count: number;
  horizons: BenchmarkedHorizon[];
  caveat: string;
  warnings: DigestWarning[];
}

// --- Phase 10: persona paper trader (model-driven) -------------------------------------------------

/**
 * One OPEN position in a persona's MODEL-DRIVEN paper trader book (`TraderBook`) -- distinct from
 * `PersonaHolding` (Phase 6's deterministic call-replay book, `PersonaBook`). This book's buys/sells
 * come from asking the persona's model, as the persona, what to do at each weekly decision using its
 * consolidated method and a point-in-time market snapshot -- not from mechanically replaying dated
 * bullish calls. See `docs/INFLUENCER-CONTRACT.md`'s "Phase 10 -- persona paper trader" section,
 * mirrored field for field. Money/quantity fields are decimal strings, never numbers.
 */
export interface TraderPosition {
  symbol: string;
  quantity: DecimalString;
  last_price: DecimalString;
  market_value: DecimalString;
  weight: number;
}

/** One filled order from one weekly decision. Orders fill at the NEXT session's open (no
 * look-ahead), through `app.paper.paperbroker.PaperBroker` + `default_mandate`. */
export interface TraderTradeRec {
  decided_on: string;
  fill_date: string;
  symbol: string;
  side: "buy" | "sell";
  quantity: DecimalString;
  price: DecimalString;
  thesis: string;
}

/** One order the model wanted to place but the mandate (cash discipline, position caps, no
 * look-ahead) rejected -- named so the gap is visible rather than silently dropped. */
export interface TraderRejectionRec {
  decided_on: string;
  symbol: string;
  side: string;
  reason: string;
}

/** One weekly decision: the model's commentary plus whatever it actually traded and whatever was
 * rejected. `degraded: true` means the grounding check on `commentary` failed and it is shown
 * anyway, marked as such -- same rule as `GroundingVerdict.degraded` elsewhere in this module. */
export interface TraderDecisionRec {
  decided_on: string;
  fill_date: string;
  commentary: string;
  degraded: boolean;
  cost_usd: DecimalString;
  trades: TraderTradeRec[];
  rejections: TraderRejectionRec[];
}

export interface TraderEquityPoint {
  date: string;
  equity: DecimalString;
}

/**
 * A persona's MODEL-DRIVEN paper trader book -- the Phase 10 counterpart to `PersonaBook` (Phase 6's
 * deterministic replay). Unlike `PersonaBook`, this asks the model, as the persona, what to buy/sell
 * at each weekly decision using its consolidated method and a point-in-time market snapshot.
 *
 * **Two caveats every UI rendering this MUST show, always visible, never behind a disclosure** (see
 * the contract's own pinned wording): (1) market data is point-in-time (no look-ahead on price), but
 * the persona's *method* is distilled from its whole corpus, so this is "how their stated approach
 * would have traded," not a real-time record; (2) the repo's own research found no measured edge --
 * this is descriptive/experimental, never promoted or treated as skill, never advice.
 *
 * `return_pct` is a 0-1 FRACTION on the wire, same rule as `PersonaBook.return_pct` (see that
 * interface's docstring on the historical percent-vs-fraction bug -- never `Number()` it directly,
 * always through `formatSignedFractionPctString`). `decisions` is newest first. `as_of` is `null`
 * for a book that has never decided anything yet -- a valid, renderable empty state, not an error.
 */
export interface TraderBook {
  persona: string;
  display_name: string;
  inception: string;
  as_of: string | null;
  starting_cash: DecimalString;
  cash: DecimalString;
  equity: DecimalString;
  return_pct: DecimalString; // fraction
  benchmark: string; // "SPY"
  benchmark_return_pct: DecimalString | null; // SPY buy-and-hold over the same window; null if unpriceable
  excess_pct: DecimalString | null; // return_pct - benchmark_return_pct; null when no benchmark
  positions: TraderPosition[];
  equity_curve: TraderEquityPoint[];
  decisions: TraderDecisionRec[]; // newest first
  spent_usd: DecimalString;
  warnings: string[];
}

export type TraderJobState = "queued" | "running" | "succeeded" | "failed";

/** A backfill job's progress -- the poll target for `POST /{slug}/trader/backfill`, mirroring
 * `IngestJob`'s own job-registry shape (`isTraderJobActive` below is `isIngestActive`'s counterpart
 * for this job type). */
export interface TraderJob {
  job_id: string;
  persona: string;
  state: TraderJobState;
  decided_count: number;
  started_at: string | null;
  finished_at: string | null;
  spent_usd: DecimalString;
  error: string | null;
}

/** Body for `POST /{slug}/trader/backfill`. `inception` ("YYYY-MM-DD") is omitted entirely (not
 * sent as `undefined`) when the caller wants the server default (`app.personas.trader.
 * DEFAULT_INCEPTION`, 2026-01-01) -- same `exactOptionalPropertyTypes` discipline as `AskRequest`. */
export interface TraderBackfillRequest {
  inception?: string;
}

// --- requests --------------------------------------------------------------------------------

export interface CreatePersonaRequest {
  handle: string;
  platform?: Platform;
}

export interface IngestDrop {
  url?: string;
  text?: string;
  title?: string;
}

/** Body for `POST /{slug}/ingest`. With neither `video_urls` nor `drop`, the backend backfills the
 * persona's youtube sources up to `limit` (default 20 server-side). */
export interface IngestRequest {
  limit?: number;
  video_urls?: string[];
  drop?: IngestDrop;
}

/** The three mutually-exclusive shapes `PersonaCard.tsx`'s ingest panel can submit -- "recent"
 * sends `{limit}`, "specific" sends `{video_urls}`, "drop" sends `{drop}`. Never a mix: the
 * contract's `drop` requires `text` (a bare `url` alone is a 422, "pasting the text is required"),
 * and an empty `video_urls` is never worth sending since the server would have nothing to do with
 * it. */
export type IngestMode = "recent" | "specific" | "drop";

/** Splits a "one URL/id per line" textarea value into trimmed, non-blank lines for
 * `IngestRequest.video_urls`. Blank lines are ignored, matching the server's own tolerance for
 * pasted lists; an all-blank input yields `[]`, which the caller must never actually submit -- see
 * this module's docstring and `PersonaCard.tsx`'s submit-disabled guard. Content validation (full
 * URL vs. `youtu.be` link vs. bare 11-character id) is the server's job, not this function's --
 * a value this cannot resolve to an id comes back as a named 422, which the UI surfaces verbatim. */
export function parseVideoUrlLines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/** Builds an `IngestDrop` from the Paste Text mode's three fields, omitting `title`/`url` entirely
 * when blank rather than sending them as empty strings (the wire type has them optional, and
 * `exactOptionalPropertyTypes` means the key must be left off, not set to `undefined`). Returns
 * `null` when `text` is blank -- the contract requires `text` on any drop (a `url`-only drop is a
 * 422, "pasting the text is required"), so a blank draft is never worth sending; `PersonaCard.tsx`
 * uses the `null` to disable its own submit button rather than let the server say so. */
export function buildDropRequest(text: string, title: string, url: string): IngestDrop | null {
  const trimmedText = text.trim();
  if (!trimmedText) return null;
  const trimmedTitle = title.trim();
  const trimmedUrl = url.trim();
  return {
    text: trimmedText,
    ...(trimmedTitle ? { title: trimmedTitle } : {}),
    ...(trimmedUrl ? { url: trimmedUrl } : {}),
  };
}

/** Body for `POST /{slug}/ask`. `symbol` is omitted entirely, not sent as `null`, when the question
 * is not about a specific ticker -- the backend's `AskRequest.symbol` is `str | None = None`, and
 * `exactOptionalPropertyTypes` means the key must be left off rather than set to `undefined`. */
export interface AskRequest {
  question: string;
  symbol?: string;
}

/** Body for `POST /{slug}/critique`. `card` is a `StrategyCard` as plain JSON -- this module has no
 * typed shape for a strategy card, so it stays a loose object, matching the backend's own
 * `dict[str, object]`. */
export interface CritiqueRequest {
  card: Record<string, unknown>;
}

/** Optional query params for `GET /{slug}/book`. Both are omitted from the URL when absent -- never
 * sent as `"undefined"` or an empty string; see `buildQuery` below. */
export interface BookOptions {
  as_of?: string;
  exclude_intraday?: boolean;
}

/** Optional query params for `GET /watchlist`. */
export interface WatchlistOptions {
  as_of?: string;
}

/** Required query params for `GET /{slug}/profile/diff` -- the backend's own query alias names are
 * literally `from`/`to` (`Query(alias="from")` / `Query(alias="to")`), not `from_version`/
 * `to_version` (those are the Python parameter names the alias maps onto). */
export interface ProfileDiffOptions {
  from: number;
  to: number;
}

// --- display: stance -----------------------------------------------------------------------------

/** The one place stance wording lives. `unclear` reads as "no clear stance" -- deliberately not
 * folded into "neutral", which is a real, distinct stance an influencer can actually hold (see this
 * module's docstring, "Copy discipline"). A function rather than a plain object so it reads the
 * active language at call time -- `PersonaCard.tsx` calls it from within its own render, which
 * re-runs whenever that component's own `useT()` says the language changed. */
const STANCE_LABEL_KEYS: Record<Stance, MessageKey> = {
  bullish: "misc.personas.stance.bullish",
  bearish: "misc.personas.stance.bearish",
  neutral: "misc.personas.stance.neutral",
  unclear: "misc.personas.stance.unclear",
};

export function stanceLabel(stance: Stance): string {
  return t(STANCE_LABEL_KEYS[stance]);
}

// --- requests ---------------------------------------------------------------------------------

/** Same five-line contract as every other API module's `requestJson` -- see `@/api/tradingagents`'s
 * own docstring for why it is duplicated rather than imported. */
async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiRequestError(response.status, body || response.statusText);
  }
  return (await response.json()) as T;
}

/** For the one endpoint here with no response body (`DELETE /{slug}` -> `204`) -- `requestJson`
 * would fail trying to parse an empty body as JSON. */
async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiRequestError(response.status, body || response.statusText);
  }
}

/** Builds a `"?a=1&b=2"` (or `""`) query string, omitting any param whose value is `undefined`
 * entirely -- never `as_of=undefined` or an empty value. Booleans serialize as `"true"`/`"false"`.
 * Local copy of the same `URLSearchParams`-based rule `@/api/market`'s and `@/api/timeframes`'s own
 * `query()` helpers already establish, per this codebase's "one copy per module" convention. */
function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

const BASE = "/api/personas";
const JSON_HEADERS = { "Content-Type": "application/json" };

export const personasApi = {
  /** Every followed persona, in the backend's own order (not re-sorted here). */
  list: (signal?: AbortSignal) => requestJson<Persona[]>(BASE, { signal: signal ?? null }),

  /** Adds a persona from a handle -- the backend resolves the channel id and display name. `501`
   * today (Phase 1 backend not yet landed); see this module's docstring. */
  create: (body: CreatePersonaRequest, signal?: AbortSignal) =>
    requestJson<Persona>(BASE, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
      signal: signal ?? null,
    }),

  /** Removes a persona. `501` today; see this module's docstring. */
  remove: (slug: string, signal?: AbortSignal) =>
    requestVoid(`${BASE}/${encodeURIComponent(slug)}`, {
      method: "DELETE",
      signal: signal ?? null,
    }),

  /** Every persona's digest card in one request -- the /personas page's primary fetch. Always `200`,
   * even with zero personas or a persona with no notes yet: there is no "not set up" error state to
   * handle here, only "the API could not be reached at all". */
  cards: (signal?: AbortSignal) => requestJson<DigestCard[]>(`${BASE}/cards`, { signal: signal ?? null }),

  /** One persona's episodic notes, newest first (the backend's own order). */
  notes: (slug: string, signal?: AbortSignal) =>
    requestJson<EpisodicNote[]>(`${BASE}/${encodeURIComponent(slug)}/notes`, { signal: signal ?? null }),

  /** Starts an ingest job. Returns the job immediately, in `state: "queued"` (or already
   * `"running"`) -- poll `getIngestJob` for progress. `409` means one is already active for this
   * persona. `501` today; see this module's docstring. */
  startIngest: (slug: string, body: IngestRequest, signal?: AbortSignal) =>
    requestJson<IngestJob>(`${BASE}/${encodeURIComponent(slug)}/ingest`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
      signal: signal ?? null,
    }),

  /** One ingest job's current state -- the poll target while it is `queued`/`running`. */
  getIngestJob: (slug: string, jobId: string, signal?: AbortSignal) =>
    requestJson<IngestJob>(
      `${BASE}/${encodeURIComponent(slug)}/ingest/${encodeURIComponent(jobId)}`,
      { signal: signal ?? null },
    ),

  /** Runs consolidation -- **synchronous**, tens of seconds, one model call over the persona's notes
   * already on disk (see this module's docstring, "Phase 2"). Returns the freshly rewritten
   * `PersonaProfile` on success; a rejection's `detail` (capped-budget `422`/`503`, or today's `501`
   * before this route lands) surfaces through `describePersonaActionError` exactly like the other
   * mutating routes.
   *
   * Accepts either a bare `AbortSignal` (the original two-argument call every existing caller uses)
   * or `{ incremental, signal }` -- `incremental: true` folds only notes newer than the last profile
   * into the standing one instead of rebuilding from every note, so cost stops scaling with vault
   * size. Omitting it entirely sends no query param, matching the backend's own `incremental = False`
   * default. */
  consolidate: (
    slug: string,
    options?: AbortSignal | { incremental?: boolean; signal?: AbortSignal },
  ) => {
    const opts = options instanceof AbortSignal ? { signal: options } : (options ?? {});
    const qs = buildQuery({ incremental: opts.incremental });
    return requestJson<PersonaProfile>(`${BASE}/${encodeURIComponent(slug)}/consolidate${qs}`, {
      method: "POST",
      signal: opts.signal ?? null,
    });
  },

  /** The current consolidated profile. `404` means "never consolidated yet" -- an ordinary empty
   * state callers must render as an invitation to consolidate, never as an error (see this module's
   * docstring, "Phase 2"). */
  getProfile: (slug: string, signal?: AbortSignal) =>
    requestJson<PersonaProfile>(`${BASE}/${encodeURIComponent(slug)}/profile`, {
      signal: signal ?? null,
    }),

  /** Every per-symbol thesis for this persona. Always `200`, `[]` when none exist yet. */
  theses: (slug: string, signal?: AbortSignal) =>
    requestJson<TickerThesis[]>(`${BASE}/${encodeURIComponent(slug)}/theses`, {
      signal: signal ?? null,
    }),

  /** One symbol's thesis. `404` when the persona has no thesis for it. */
  thesis: (slug: string, symbol: string, signal?: AbortSignal) =>
    requestJson<TickerThesis>(
      `${BASE}/${encodeURIComponent(slug)}/theses/${encodeURIComponent(symbol)}`,
      { signal: signal ?? null },
    ),

  /** One persona's dated-call scorecard (Phase 3a). Always `200` with `scored_calls: []` for a
   * persona with no dated mentions yet -- that is the ordinary empty state, not an error. `404`
   * means "unknown persona slug", unlike `getProfile`'s `404` -- see this module's docstring. */
  scorecard: (slug: string, signal?: AbortSignal) =>
    requestJson<PersonaScorecard>(`${BASE}/${encodeURIComponent(slug)}/scorecard`, {
      signal: signal ?? null,
    }),

  /** The persona's notes as a dated timeline plus per-symbol stance evolution. Pure read over stored
   * notes -- no model call, no market fetch. `404` means "unknown persona slug"; a known persona
   * with no notes yields empty `entries`, not an error. */
  timeline: (slug: string, signal?: AbortSignal) =>
    requestJson<PersonaTimeline>(`${BASE}/${encodeURIComponent(slug)}/timeline`, {
      signal: signal ?? null,
    }),

  /** A model's impression of what the persona would say, grounded in their own notes. Synchronous
   * (one grounded call). `404` unknown persona; `409` no notes / budget cap; `503` model unavailable
   * -- surfaces through `describePersonaActionError` like the other mutating routes. */
  ask: (slug: string, body: AskRequest, signal?: AbortSignal) =>
    requestJson<PersonaAnswer>(`${BASE}/${encodeURIComponent(slug)}/ask`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
      signal: signal ?? null,
    }),

  // --- Phase 9: persona chat (multi-turn) --------------------------------------------------------

  /** Every chat thread for this persona, newest `updated_at` first, with `turns: []` -- the thread
   * list, not any one thread's transcript. */
  chats: (slug: string, signal?: AbortSignal) =>
    requestJson<ChatThread[]>(`${BASE}/${encodeURIComponent(slug)}/chats`, { signal: signal ?? null }),

  /** Starts a new, empty chat thread (`201`, `title: ""`, `turns: []`). */
  createChat: (slug: string, signal?: AbortSignal) =>
    requestJson<ChatThread>(`${BASE}/${encodeURIComponent(slug)}/chats`, {
      method: "POST",
      signal: signal ?? null,
    }),

  /** One chat thread with its full transcript. `404` unknown persona or thread. */
  chat: (slug: string, threadId: string, signal?: AbortSignal) =>
    requestJson<ChatThread>(
      `${BASE}/${encodeURIComponent(slug)}/chats/${encodeURIComponent(threadId)}`,
      { signal: signal ?? null },
    ),

  /** Deletes a chat thread (`204`). */
  deleteChat: (slug: string, threadId: string, signal?: AbortSignal) =>
    requestVoid(`${BASE}/${encodeURIComponent(slug)}/chats/${encodeURIComponent(threadId)}`, {
      method: "DELETE",
      signal: signal ?? null,
    }),

  /** Asks one turn within an existing thread. `404` unknown persona/thread; `409` no notes / the
   * 40-turn cap / the thread's own budget cap; `429` daily spend cap; `503` model unavailable --
   * surfaces through `describePersonaActionError` like every other mutating route here. */
  sendTurn: (slug: string, threadId: string, body: ChatTurnRequest, signal?: AbortSignal) =>
    requestJson<ChatTurn>(
      `${BASE}/${encodeURIComponent(slug)}/chats/${encodeURIComponent(threadId)}/turns`,
      {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
        signal: signal ?? null,
      },
    ),

  /** Whether this persona's consolidated profile is stale relative to its notes -- informational for
   * `PersonaChat.tsx`'s stale-profile note, never blocking. */
  chatContext: (slug: string, signal?: AbortSignal) =>
    requestJson<ChatContext>(`${BASE}/${encodeURIComponent(slug)}/chat-context`, {
      signal: signal ?? null,
    }),

  /** Every persona's current-holdings paper book in one request, for the Paper Desk. Defined before
   * `/{slug}` server-side so `"books"` is never captured as a persona slug -- takes no query params. */
  books: (signal?: AbortSignal) => requestJson<PersonaBook[]>(`${BASE}/books`, { signal: signal ?? null }),

  /** One persona's current-holdings paper book. `404` only for an unknown persona. `as_of` prices it
   * point-in-time (no look-ahead); `exclude_intraday` drops calls that are not really holdings. Both
   * are omitted from the URL when absent. */
  book: (slug: string, options?: BookOptions, signal?: AbortSignal) => {
    const qs = buildQuery({
      as_of: options?.as_of,
      exclude_intraday: options?.exclude_intraday,
    });
    return requestJson<PersonaBook>(`${BASE}/${encodeURIComponent(slug)}/book${qs}`, {
      signal: signal ?? null,
    });
  },

  /** The cross-persona consensus watchlist -- what the followed influencers are currently bullish
   * on. `as_of` gives the point-in-time consensus (no look-ahead) and is omitted from the URL when
   * absent (the backend defaults to now). Descriptive, never a buy list. */
  watchlist: (options?: WatchlistOptions, signal?: AbortSignal) => {
    const qs = buildQuery({ as_of: options?.as_of });
    return requestJson<InfluencerWatchlist>(`${BASE}/watchlist${qs}`, { signal: signal ?? null });
  },

  /** The cross-persona macro picture from the commentator personas -- a reference the strategy layer
   * may cite, never a signal. Takes no query params. */
  regime: (signal?: AbortSignal) => requestJson<RegimeConsensus>(`${BASE}/regime`, { signal: signal ?? null }),

  /** Descriptive lens: did following the persona's dated calls beat holding the benchmark over the
   * same windows? `404` only for an unknown persona. */
  backtest: (slug: string, signal?: AbortSignal) =>
    requestJson<PersonaBacktest>(`${BASE}/${encodeURIComponent(slug)}/backtest`, {
      signal: signal ?? null,
    }),

  /** Maps the persona's METHODOLOGY onto the repo's fixed rule-shape DSL (Phase 7c, exploration
   * lens). A mapped draft is persisted server-side so it can be re-opened via `strategyCards`. `404`
   * unknown persona; `409` no methodology / no current-bullish tickers / budget; `503` model
   * unavailable. */
  strategyCard: (slug: string, signal?: AbortSignal) =>
    requestJson<StrategyCardDraft>(`${BASE}/${encodeURIComponent(slug)}/strategy-card`, {
      method: "POST",
      signal: signal ?? null,
    }),

  /** Every persisted strategy-card draft for a persona, newest first. `404` unknown persona. */
  strategyCards: (slug: string, signal?: AbortSignal) =>
    requestJson<SavedStrategyDraft[]>(`${BASE}/${encodeURIComponent(slug)}/strategy-cards`, {
      signal: signal ?? null,
    }),

  /**
   * Promote a saved strategy-card draft onto the competition library shelf as a scorable candidate.
   * The card is read from the persona's own saved draft, never sent here. `404` unknown persona or no
   * draft at that version; `422` a draft that mapped no card; `409` (`ApiRequestError.status`) already
   * on the shelf -- an idempotent no-op to surface, not an error to retry.
   */
  promoteStrategyCard: (slug: string, version: number, signal?: AbortSignal) =>
    requestJson<PromotedPersonaCard>(
      `${BASE}/${encodeURIComponent(slug)}/strategy-cards/${version}/promote`,
      { method: "POST", signal: signal ?? null },
    ),

  /** The reverse of the persona->card mapping: the persona assesses a card in-voice, grounded in
   * their own methodology. `404` unknown persona; `409` budget; `503` model unavailable. A persona
   * with no profile returns a `cannot_say` critique, not an error. */
  critique: (slug: string, body: CritiqueRequest, signal?: AbortSignal) =>
    requestJson<CardCritique>(`${BASE}/${encodeURIComponent(slug)}/critique`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
      signal: signal ?? null,
    }),

  /** What changed in a persona's memory between two consolidations. Query param names are literally
   * `from`/`to` (the backend's own `Query(alias="from"/"to")`), not `from_version`/`to_version`.
   * `404` unknown persona/version. */
  profileDiff: (slug: string, options: ProfileDiffOptions, signal?: AbortSignal) => {
    const qs = buildQuery({ from: options.from, to: options.to });
    return requestJson<ProfileDiff>(`${BASE}/${encodeURIComponent(slug)}/profile/diff${qs}`, {
      signal: signal ?? null,
    });
  },

  // --- Phase 10: persona paper trader (model-driven) ----------------------------------------------

  /** Every persona's model-driven trader book in one request, for the Paper Desk. Takes no query
   * params, always `200`. */
  traderBooks: (signal?: AbortSignal) =>
    requestJson<TraderBook[]>(`${BASE}/trader/books`, { signal: signal ?? null }),

  /** One persona's trader book. `404` only for an unknown persona; a persona that has never traded
   * yet still answers `200` with an empty book (`as_of: null`, no positions, no decisions). */
  traderBook: (slug: string, signal?: AbortSignal) =>
    requestJson<TraderBook>(`${BASE}/${encodeURIComponent(slug)}/trader`, { signal: signal ?? null }),

  /** Resets the trader book (`204`) -- clears the broker state, equity curve and decision log back
   * to empty. */
  resetTrader: (slug: string, signal?: AbortSignal) =>
    requestVoid(`${BASE}/${encodeURIComponent(slug)}/trader`, {
      method: "DELETE",
      signal: signal ?? null,
    }),

  /** Runs ONE decision at the latest session, now -- synchronous, one grounded model call. Returns
   * the freshly updated `TraderBook`. `404` unknown persona; `409` daily/decision budget; `503`
   * model unavailable -- surfaces through `describePersonaActionError` like every other mutating
   * route here. */
  traderDecide: (slug: string, signal?: AbortSignal) =>
    requestJson<TraderBook>(`${BASE}/${encodeURIComponent(slug)}/trader/decide`, {
      method: "POST",
      signal: signal ?? null,
    }),

  /** Starts an async weekly backfill from `body.inception` (server default when omitted). Returns
   * the job immediately (`202`, `state: "queued"`) -- poll `traderBackfillJob` for progress. `409`
   * means one is already active for this persona. */
  traderBackfill: (slug: string, body: TraderBackfillRequest, signal?: AbortSignal) =>
    requestJson<TraderJob>(`${BASE}/${encodeURIComponent(slug)}/trader/backfill`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
      signal: signal ?? null,
    }),

  /** One backfill job's current state -- the poll target while it is `queued`/`running`. */
  traderBackfillJob: (slug: string, jobId: string, signal?: AbortSignal) =>
    requestJson<TraderJob>(
      `${BASE}/${encodeURIComponent(slug)}/trader/backfill/${encodeURIComponent(jobId)}`,
      { signal: signal ?? null },
    ),
};

// --- display helpers ---------------------------------------------------------------------------

/** Whether a poll loop over `getIngestJob` should keep going -- `"queued"`/`"running"` keep the
 * `setInterval` alive, every other state is a settled end state. Mirrors `isRunActive`
 * (`@/api/tradingagents`)'s own shape for this codebase's job-registry poll pattern. */
export function isIngestActive(state: IngestState): boolean {
  return state === "queued" || state === "running";
}

/** Whether a poll loop over `traderBackfillJob` (Phase 10) should keep going -- same shape as
 * `isIngestActive` above, for the trader backfill job type. */
export function isTraderJobActive(state: TraderJobState): boolean {
  return state === "queued" || state === "running";
}

// `formatMoney` moved to `@/format/money` (was a local copy identical to `@/api/tax` and
// `@/api/tradingagents`'s own); re-exported here so every existing `import { formatMoney } from
// "@/api/personas"` across the app keeps working unchanged.
export { formatMoney };

/** Coarse relative age for `DigestCard.as_of` ("3h ago"), the same shape as `@/api/news`'s
 * `formatRelativeAge` -- kept as a local copy rather than imported, per this codebase's "one copy
 * per module" convention (see this module's own docstring). `now` is a parameter, defaulting to the
 * real clock, purely so tests can pin it. An unparseable timestamp renders as an em dash rather than
 * `"NaNh ago"` or throwing. */
export function formatRelativeAge(published: string, now: Date = new Date()): string {
  const publishedDate = new Date(published);
  if (Number.isNaN(publishedDate.getTime())) return "—";
  const diffMs = now.getTime() - publishedDate.getTime();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return t("misc.personas.age.justNow");
  if (minutes < 60) return t("misc.personas.age.minutes", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("misc.personas.age.hours", { count: hours });
  const days = Math.floor(hours / 24);
  return t("misc.personas.age.days", { count: days });
}

/**
 * `error.message` for a failed mutating call is the raw response body -- `{"detail": "..."}`, the
 * plain FastAPI shape every one of the three mutating routes uses for both today's `501`
 * ("Phase 1 lands this later") and tomorrow's real rejections (`409` already-active job, `422`
 * unresolvable handle, etc.). Unwraps `detail` when the body parses as JSON; falls back to the
 * caller-supplied `fallback` otherwise. Local copy of the same unwrapping rule
 * `@/api/tradingagents`'s `describeStartRunError`/`parseErrorDetail` already establish, generalised
 * across all three mutating routes here (they all share one plain-`detail` shape, unlike Trading
 * Agents' per-status-code messages) rather than one function per endpoint.
 */
export function describePersonaActionError(error: unknown, fallback: string): string {
  if (!(error instanceof ApiRequestError)) {
    return error instanceof Error && error.message ? error.message : fallback;
  }
  return parseErrorDetail(error.message) ?? (error.message || fallback);
}

// --- display: call scoring (Phase 3a) ------------------------------------------------------------

/** Signed percent for `CallScore.return_pct`, e.g. `"+4.32%"` / `"-1.05%"`. Same shape as
 * `@/api/market`'s `formatPercent` (a local copy per this module's "one copy per module"
 * convention, since `return_pct` here is a plain `number | null`, not a `DecimalString`). `null`
 * (pending/no_data) renders as an em dash -- the caller still shows the outcome badge separately so
 * the reason for the missing number is never lost. */
export function formatReturnPct(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

/** The one place `CallOutcome` wording lives -- plain, distinct phrasing per outcome so a reader
 * never has to infer "played out" from a raw enum value. **No i18n key here**: like
 * `PersonaProfile.tsx`, this shard's task brief fences off `frontend/src/i18n/` (another session
 * owns it concurrently), so this stays a hardcoded-English literal map rather than a new
 * `MessageKey`, unlike `stanceLabel` above which predates that freeze. See this shard's own report
 * for the follow-up once the i18n freeze lifts. */
const OUTCOME_LABEL_KEYS: Record<CallOutcome, MessageKey> = {
  played_out: "misc.personas.outcome.playedOut",
  went_against: "misc.personas.outcome.wentAgainst",
  flat: "misc.personas.outcome.flat",
  not_directional: "misc.personas.outcome.notDirectional",
  pending: "misc.personas.outcome.pending",
  no_data: "misc.personas.outcome.noData",
};

export function outcomeLabel(outcome: CallOutcome): string {
  return t(OUTCOME_LABEL_KEYS[outcome]);
}

/** A short, subtle note on which price basis a call's `return_pct` used -- adjusted close and raw
 * close are not directly comparable, so the contract requires this stay visible (a footnote/title),
 * never silently hidden, even though it should not dominate the row. `null` (pending/no_data, no
 * return computed at all) has nothing to note. */
export function callBasisNote(basis: CallScore["basis"]): string | null {
  if (basis === "adjusted") return t("misc.personas.basis.adjusted");
  if (basis === "close") return t("misc.personas.basis.close");
  return null;
}

function parseErrorDetail(body: string): string | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object" || !("detail" in parsed)) return null;
  const detail = (parsed as { detail: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : null))
      .filter((m): m is string => m !== null);
    return messages.length > 0 ? messages.join("; ") : null;
  }
  return null;
}
