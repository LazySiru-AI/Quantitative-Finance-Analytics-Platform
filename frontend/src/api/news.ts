/**
 * Typed client for the ticker News & Sentiment panel.
 *
 * Mirrors `GET /api/news/ticker/{symbol}` field for field. Three things here are easy to get wrong
 * and are worth reading before using this module.
 *
 * **`SocialSnapshot` has no `total`/`labelled` field on the wire.** The backend computes those as
 * Python `@property` on the model, so they never serialise. `snapshotTotal` / `snapshotLabelled`
 * below recompute them client-side (`bullish + bearish + neutral` and `bullish + bearish`) — do not
 * add `total`/`labelled` to the interface itself, since a payload will never actually carry them and
 * a reader trusting the type would get `undefined` at runtime.
 *
 * **`social: null` and a zero-count `SocialSnapshot` mean different things, and both differ from
 * `bull_ratio: null`.** `social === null` means no social provider could be reached at all — a
 * provenance failure. A reachable snapshot with `bullish + bearish + neutral === 0` means the
 * provider answered but nobody posted in the sampled window — a genuine "nothing happened".
 * `bull_ratio === null` on a *non-empty* snapshot means messages exist but none carried a
 * directional label (an all-neutral window) — different again from an empty window, because the
 * denominator for "how many messages" is still meaningful there. `NewsPanel.tsx` renders each of
 * these three as a distinct sentence; nothing here should collapse them back into one "no data" case.
 *
 * **`bull_ratio` and `labelled_share` are ratios in `[0, 1]`, not percentages.** `formatBullRatio`
 * multiplies by 100 for display; do not do that at the call site too.
 */

import { ApiRequestError } from "@/api/client";
import { t } from "@/i18n";

// --- news ---------------------------------------------------------------

/** One headline. `summary` is `null` when the provider did not supply one — never coerce to `""`,
 * since an empty string would be indistinguishable from a provider that returned a blank summary. */
export interface NewsItem {
  title: string;
  url: string;
  /** ISO 8601 timestamp. Feed this to `formatRelativeAge`, not a raw `Date` format call. */
  published: string;
  /** Which provider surfaced this specific item (e.g. `"yahoo_news"`). */
  source: string;
  publisher: string;
  summary: string | null;
}

// --- social ---------------------------------------------------------------

/**
 * The raw counts a social provider (e.g. StockTwits) reported for its sampled window. `total` and
 * `labelled` are deliberately absent — see the module docstring — use `snapshotTotal` /
 * `snapshotLabelled` below instead of reaching for fields that do not exist on the wire.
 */
export interface SocialSnapshot {
  symbol: string;
  source: string;
  as_of: string;
  window_start: string;
  bullish: number;
  bearish: number;
  neutral: number;
}

/** Total messages the snapshot's window covers, however they were labelled (or not). */
export function snapshotTotal(snapshot: SocialSnapshot): number {
  return snapshot.bullish + snapshot.bearish + snapshot.neutral;
}

/** Messages that carried a directional label at all — the denominator `bull_ratio` is computed over. */
export function snapshotLabelled(snapshot: SocialSnapshot): number {
  return snapshot.bullish + snapshot.bearish;
}

export interface SocialSummary {
  snapshot: SocialSnapshot;
  /** Share of *labelled* messages that were bullish. `null` when `snapshotLabelled` is `0` — an
   * all-neutral (or empty) window has no directional messages to take a share of. Never render this
   * as `0%`: `null` is "not measured", `0` would be "measured at zero", and those are different
   * claims. Use `formatBullRatio`. */
  bull_ratio: number | null;
  /** `snapshotLabelled(snapshot) / snapshotTotal(snapshot)`. `null` specifically when the window was
   * empty (`snapshotTotal` is `0`) — there is no denominator to divide by, as opposed to a non-empty
   * window that happens to be entirely unlabelled (which is `0`, not `null`). */
  labelled_share: number | null;
}

// --- warnings ---------------------------------------------------------------

export interface NewsWarning {
  kind: string;
  message: string;
}

// --- the panel ---------------------------------------------------------------

export interface TickerNewsPanel {
  symbol: string;
  generated_at: string;
  as_of: string | null;
  /** Most-recent-first, however many the caller asked for (`limit`, default 20 server-side). */
  news: NewsItem[];
  /** Which provider answered the headline request. `null` when none could — distinct from `news`
   * simply being empty because a provider answered with nothing to report. */
  news_source: string | null;
  /** `null` when no social provider could be reached at all. See the module docstring for how this
   * differs from a reachable-but-empty snapshot. */
  social: SocialSummary | null;
  warnings: NewsWarning[];
}

// --- requests ---------------------------------------------------------------

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

// --- macro (events + global headlines) ---------------------------------------------------------

/**
 * One Polymarket event's current pricing. Mirrors `app.market.news_models.EventMarket` field for
 * field. `probability` is the market's own mid price passed straight through -- a reported
 * observation "in exactly the way a closing price is" (see the backend docstring), not a ratio this
 * codebase derived, so unlike `bull_ratio` it is never `null` and never needs a denominator alongside
 * it. `volume` and `resolution_date` are the two fields that *are* genuinely absent sometimes (a
 * market the upstream has not committed a close date for, or does not report volume on) and render as
 * an em dash via `formatPrice`/`formatObservationDate` rather than a fabricated `$0` or a blank date.
 */
export interface EventMarket {
  question: string;
  slug: string;
  source: string;
  as_of: string;
  /** `[0, 1]`. Use `formatProbability` -- do not multiply by 100 at the call site too. */
  probability: number;
  volume: number | null;
  /** `YYYY-MM-DD`, or `null` when the upstream has not committed to one. Format with
   * `formatObservationDate` from `@/api/macro` -- same date-only caution as every other macro date
   * in this app: do not round-trip it through a local-zone `Date`. */
  resolution_date: string | null;
}

/**
 * Everything the Macro page's news panel needs, in one request -- headlines plus event-market
 * pricing, both filtered by the same `query`, so neither section can disagree about what was
 * actually searched. Mirrors `app.market.news_models.MacroNewsPanel` field for field.
 *
 * **There is no `events_source` field**, unlike `news_source` for headlines. A dead Polymarket chain
 * therefore does not zero out a dedicated provenance field -- it leaves `events` empty and appends a
 * `MarketWarning` whose `message` contains `"prediction markets unavailable"` (see
 * `app.market.news.build_macro_panel`'s `_fold_provider_error`). `MacroNewsPanel.tsx`'s events
 * section is the one place in this codebase that tells "provider dead" from "provider answered with
 * nothing" by matching that warning text rather than reading a dedicated null field -- read that
 * component's docstring before changing the wording either side of this string depends on.
 */
export interface MacroNewsPanel {
  generated_at: string;
  as_of: string | null;
  /** The query actually searched -- always populated, even when the caller passed none: an empty
   * request falls back server-side to `DEFAULT_MACRO_QUERY`, and this field carries whichever string
   * that resolved to, so a reader can see what was searched without guessing at the fallback. */
  query: string;
  news: NewsItem[];
  /** Which provider answered the headline request. `null` when none could -- distinct from `news`
   * simply being empty because a provider answered with nothing to report. Exactly the ticker panel's
   * `news_source` semantics. */
  news_source: string | null;
  events: EventMarket[];
  warnings: NewsWarning[];
}

/** Requested cap for both sections of the Macro news panel -- passed straight through as `limit` on
 * `GET /api/news/macro`. Exported so `MacroNewsPanel.tsx` can render "N of up to MACRO_NEWS_LIMIT
 * requested" without duplicating the number the fetch itself used, and so the denominator on screen
 * can never drift out of sync with what was actually asked for. */
export const MACRO_NEWS_LIMIT = 20;

export const newsApi = {
  ticker: (symbol: string, signal?: AbortSignal) =>
    requestJson<TickerNewsPanel>(`/api/news/ticker/${encodeURIComponent(symbol)}`, {
      signal: signal ?? null,
    }),
  macro: (signal?: AbortSignal) =>
    requestJson<MacroNewsPanel>(`/api/news/macro?limit=${MACRO_NEWS_LIMIT}`, {
      signal: signal ?? null,
    }),
};

// --- display helpers --------------------------------------------------------

/**
 * `bull_ratio` (a `[0, 1]` share) as a whole-percent string, or an em dash for `null`.
 *
 * The em dash is load-bearing: `null` means "not measured" (nothing was labelled), and formatting it
 * as `0%` would silently restate that as "measured, and the answer was zero" — a real and different
 * claim on data where 8 of 12 messages routinely carry no label at all. Always pair this with a
 * labelled-count denominator at the call site; this function only formats the number, it does not
 * decide whether showing it alone would be misleading.
 */
export function formatBullRatio(ratio: number | null): string {
  if (ratio === null || !Number.isFinite(ratio)) return "—";
  return `${Math.round(ratio * 100)}%`;
}

/**
 * `EventMarket.probability` (a `[0, 1]` mid price) as a whole-percent string.
 *
 * Unlike `formatBullRatio`, this never returns an em dash for `null` because the field it formats is
 * not optional -- `EventMarket.probability` is a required upstream price, not a derived ratio that
 * can come back unmeasured. A non-finite value (which should not occur, but a malformed upstream
 * payload is not this function's problem to diagnose) still renders as an em dash rather than
 * `"NaN%"`.
 */
export function formatProbability(probability: number): string {
  if (!Number.isFinite(probability)) return "—";
  return `${Math.round(probability * 100)}%`;
}

/**
 * Coarse relative age for a headline's `published` timestamp ("3h ago"), the way a reader scans a
 * news list rather than cross-references clock times. `now` is a parameter (defaulting to the real
 * clock) purely so tests can pin it — this module does no polling or auto-refresh of its own.
 *
 * An unparseable timestamp renders as an em dash rather than `"NaNh ago"` or throwing.
 */
export function formatRelativeAge(published: string, now: Date = new Date()): string {
  const publishedDate = new Date(published);
  if (Number.isNaN(publishedDate.getTime())) return "—";
  const diffMs = now.getTime() - publishedDate.getTime();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return t("macro.news.age.justNow");
  if (minutes < 60) return t("macro.news.age.minutes", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("macro.news.age.hours", { count: hours });
  const days = Math.floor(hours / 24);
  return t("macro.news.age.days", { count: days });
}
