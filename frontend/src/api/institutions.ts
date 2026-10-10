/**
 * Typed client for the institutions/13F+NPORT endpoints.
 *
 * Tracks what large institutions (13F filers) and major ETFs (NPORT-P filers) hold, and -- the
 * reason this exists -- what changed between one filing and the last one. As with the rest of this
 * API, every money and weight figure crosses the wire as a decimal *string* (`DecimalString`);
 * nothing here parses one into a `number` for arithmetic, only for display.
 *
 * **Two filings, not one, and they disagree on what "holdings" even means.** A 13F is what a
 * *manager* (a hedge fund, an asset manager) held in US-listed equities as of quarter end, filed
 * roughly 45 days later -- it is a slice of their book: no bonds, no cash, no foreign-listed shares.
 * Its `weight` figures are weights *within that slice*, not of the manager's whole portfolio. An
 * NPORT-P is what an *ETF* actually held, filed roughly 60 days later, and it covers everything the
 * fund owns -- an ETF does not file a 13F. `SOURCE_NOTE` below is the one-line explanation the page
 * renders next to whichever kind of filing is on screen; never blend the two kinds' weights into one
 * ranked list as though they meant the same thing.
 *
 * **`ticker` is `null` on almost every holding, and that is correct, not missing data.** Neither
 * filing type carries a ticker at all -- both report by CUSIP. The backend fills in `ticker` only
 * where that CUSIP already matches something in the user's own imported ledger, which is exactly
 * the case this page exists to surface: "this institution just moved on something I hold." Do not
 * invent a ticker from the issuer name, and do not render a blank column where a `null` ticker would
 * go -- the `cusip` is always present and is the row's real identity.
 *
 * **A share count and a dollar value are different questions, and blending them lies.** A position's
 * reported value moves for two unrelated reasons: the manager traded it, or the market repriced it.
 * Only the first is a decision. The real case that makes this concrete: Berkshire's Chevron stake
 * went from $17.46bn to $13.99bn across one quarter on a share count that did not move by a single
 * share -- oil moved, they did not. `HoldingChange.action` (and every "what did they do" framing
 * built from it) is derived server-side from the **share** columns only. The value columns are
 * carried alongside as a separate figure and must always be labelled as including price movement --
 * never used to imply a trade that did not happen.
 */

import { ApiRequestError, parseDecimalString, type DecimalString } from "@/api/client";

export type Source = "13F" | "NPORT";

/** What a share-count comparison across two periods concluded happened, computed server-side --
 *  never re-derived here from the value columns, which move on price alone as often as on trading. */
export type Action = "new" | "exit" | "add" | "trim" | "hold";

/**
 * A one-line explanation of what kind of filing backs the data on screen, keyed by `FundRef.source`.
 * Rendered near the data itself (not in a separate "about" page) because the numbers on this page
 * are already months stale by the time they are filed, and a reader must never mistake a 13F's
 * equities-only slice, or an NPORT's fuller-but-still-lagged snapshot, for a live position.
 */
export const SOURCE_NOTE: Record<Source, string> = {
  "13F": "13F: what this manager held in US-listed equities only, as of quarter end, filed ~45 days later. No bonds, no cash, no foreign listings -- weights are of this slice, not the whole book.",
  NPORT: "NPORT-P: what this ETF actually held, as of quarter end, filed ~60 days later, covering everything the fund owns. An ETF does not file a 13F.",
};

export interface FundRef {
  /** URL-safe id: the ticker where one exists (e.g. "QQQ"), otherwise a stable key (e.g. "BRK"). */
  key: string;
  name: string;
  source: Source;
  cik: string;
  series_id: string | null;
  ticker: string | null;
  /**
   * The person the filer is publicly identified with — "Cathie Wood", "Warren Buffett" — or `null`
   * where naming one would be misleading (Renaissance's founder died in 2024; Lone Pine's stopped
   * managing money in 2019).
   *
   * Editorial, from the watchlist, **not from the filing**. It labels the firm, and is never a
   * claim that this person personally chose any holding: a 13F is filed by a firm.
   */
  principal: string | null;
}

/** One position in a fund's filing. `ticker` is `null` for the overwhelming majority of rows -- see
 *  the module docstring -- and that is the expected, correct state, not a data gap. */
export interface Holding {
  cusip: string;
  issuer: string;
  /** Whole US dollars. */
  value: DecimalString;
  shares: DecimalString;
  /** Fraction of one -- `"0.0914"` is 9.14%, formatted for display via `formatWeight`. */
  weight: DecimalString;
  /** Non-null only where this CUSIP matched something in the user's own ledger. */
  ticker: string | null;
}

export interface Snapshot {
  fund: FundRef;
  /** The as-of date the filing reports, `"YYYY-MM-DD"` -- not when it reached the SEC. */
  period: string;
  /** When the filing reached the SEC, `"YYYY-MM-DD"`. Always later than `period`, per the ~45/~60
   *  day lags the module docstring describes -- provenance, not a live timestamp. */
  filed: string;
  /** EDGAR accession number, dashed, for tracing this snapshot back to the actual filing. */
  accession: string;
  total_value: DecimalString;
  holdings: Holding[];
  /**
   * True when the server judged this filing's values to be stated in thousands and multiplied them
   * up to whole dollars.
   *
   * Surfaced rather than hidden because it is a correction applied to somebody else's disclosed
   * figure. Duquesne Family Office's quarter ending 2026-06-30 reads $5.2 million taken literally,
   * and $5.21 billion — the right size — read as thousands.
   */
  value_units_rescaled: boolean;
}

/**
 * One CUSIP's change between two consecutive filings. `action` is computed server-side from the
 * **share** columns (`shares_before`/`shares_after`) -- see the module docstring's Chevron example
 * for why the value columns must never be used to infer it. The value and weight columns are still
 * carried here because they matter, just not for that judgement: they answer "how much bigger/
 * smaller is this position now", which includes price movement the share columns cannot show.
 */
export interface HoldingChange {
  cusip: string;
  issuer: string;
  /** Non-null only where this CUSIP matched something in the user's own ledger -- the row most
   *  worth a second look, since it means this institution just moved on something the user holds. */
  ticker: string | null;
  action: Action;
  shares_before: DecimalString;
  shares_after: DecimalString;
  shares_delta: DecimalString;
  /**
   * `null` specifically for a brand-new position (`shares_before` is zero, so a percent change is
   * undefined, not zero and not infinite). Render `null` as the word "new" -- never `0%`, which
   * would understate a position that did not exist last quarter, and never `∞`/`Infinity`, which is
   * technically correct and useless. See `formatSharesPctChange`.
   */
  shares_pct_change: DecimalString | null;
  value_before: DecimalString;
  value_after: DecimalString;
  /** Dollar change including price movement, not a trading signal by itself -- pair with
   *  `shares_delta`/`action` before drawing any conclusion from this number alone. */
  value_delta: DecimalString;
  weight_before: DecimalString;
  weight_after: DecimalString;
  weight_delta: DecimalString;
}

/**
 * Every holding's change between two consecutive filings for one fund, plus the server's own tally
 * of how many landed in each `Action` bucket.
 *
 * `counts` is authoritative -- render the summary strip from it directly and never recompute the
 * tally from `changes` client-side. The two are produced by different code paths (this object is
 * one aggregate query, `changes` is the row-level join), and a client-side recount that quietly
 * disagreed with the server's own tally would be a second implementation of the same arithmetic
 * with no way for a reader to know which one is right.
 */
export interface PortfolioDelta {
  fund: FundRef;
  from_period: string;
  to_period: string;
  from_accession: string;
  to_accession: string;
  total_value_before: DecimalString;
  total_value_after: DecimalString;
  changes: HoldingChange[];
  /** Every `Action` key present, zeroes included -- safe to index without an existence check. */
  counts: Record<Action, number>;
  /**
   * Median `shares_pct_change` across the ADD and TRIM rows only, as a fraction of one. `null`
   * when nothing was traded.
   *
   * Read it beside the counts, not instead of them. An index fund does not pick its holdings, so
   * when it changes size every position moves together and the diff reports a hundred `trim` rows
   * for what was not a hundred decisions -- QQQ's last filing pair shows 95, at a median of
   * -6.07%. A stock picker's rows scatter instead: Berkshire's thirteen span -58% to +658%.
   */
  median_shares_pct_change: DecimalString | null;
}

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

/** One tracked filer's disclosed position in a symbol, from the reverse lookup. */
export interface HolderRow {
  key: string;
  name: string;
  period: string;
  filed: string;
  accession: string;
  cusip: string;
  issuer: string;
  shares: DecimalString;
  value: DecimalString;
  weight: DecimalString;
  value_units_rescaled: boolean;
}

/** A tracked filer whose latest filing could not be read, and why. */
export interface UncheckedFund {
  key: string;
  name: string;
  reason: string;
}

/**
 * Which tracked filers hold one symbol.
 *
 * **`unchecked`, `checked` and `total` are not diagnostics — they decide what an empty `holders`
 * array means.** The lookup walks every filer over the network; if some fail, "no tracked filer
 * holds NVDA" is false and only these fields separate that from the real answer. Any UI rendering
 * `holders` must render these too.
 *
 * **`symbol_resolved` is the other half of the same problem.** CUSIP is the only bridge from a 13F
 * to a ticker and it comes from the user's own ledger, so a symbol they have never traded resolves
 * to nothing and cannot match however many filers hold it. `false` with an empty `holders` means
 * "could not look", not "nobody holds it".
 */
export interface HoldersResponse {
  symbol: string;
  cusips: string[];
  symbol_resolved: boolean;
  holders: HolderRow[];
  unchecked: UncheckedFund[];
  checked: number;
  total: number;
}

export const institutionsApi = {
  funds: (signal?: AbortSignal) =>
    requestJson<{ funds: FundRef[] }>("/api/institutions/funds", { signal: signal ?? null }),
  /**
   * `key` and `period` both go through `encodeURIComponent`, without exception -- `key` comes back
   * verbatim from `funds()` today, but treating a same-origin, server-sourced string as safe to
   * interpolate unencoded is exactly the assumption that breaks the day one fund's `key` contains a
   * character that is not URL-safe; see `@/api/tax`'s module comment on why this app encodes every
   * interpolated value uniformly rather than special-casing the ones judged safe today.
   */
  holdings: (key: string, period?: string, signal?: AbortSignal) => {
    const qs = period ? `?period=${encodeURIComponent(period)}` : "";
    return requestJson<Snapshot>(`/api/institutions/${encodeURIComponent(key)}/holdings${qs}`, {
      signal: signal ?? null,
    });
  },
  changes: (key: string, signal?: AbortSignal) =>
    requestJson<PortfolioDelta>(`/api/institutions/${encodeURIComponent(key)}/changes`, {
      signal: signal ?? null,
    }),
  /**
   * Which tracked filers hold `symbol`.
   *
   * **Slow when cold** — the server walks every filer in the catalog, one EDGAR fetch each behind a
   * six-hour cache, so first call after a cache miss is measured in tens of seconds and later ones
   * in single digits. Callers must show a pending state that survives that long rather than a
   * spinner sized for a normal request, and must never fire this on hover or on keystroke.
   */
  holders: (symbol: string, signal?: AbortSignal) =>
    requestJson<HoldersResponse>(
      `/api/institutions/holders/${encodeURIComponent(symbol)}`,
      { signal: signal ?? null },
    ),
};

// --- display helpers (never do arithmetic on a DecimalString via these) --------------------------

/**
 * Render a weight fraction as a percentage, e.g. `"0.0914"` -> `"9.14%"`. Shifts the decimal point
 * by string manipulation, the same technique `formatMoney` (`@/api/tax`) uses for cents -- never
 * `parseFloat`, which would round-trip the value through an IEEE double for no reason a display
 * string needs. Truncates rather than rounds past two decimal places, matching `formatMoney`'s own
 * "never round; the server already did" rule.
 *
 * A magnitude smaller than that two-decimal-place display can show renders as an explicit
 * under-threshold marker, not `"0.00%"` -- `"<0.01%"` for a tiny positive, `">-0.01%"` for a tiny
 * negative (chosen so the marker itself is a true inequality: `-0.0032% > -0.01%`). The real case
 * this exists for: QQQ's NQM6 future, -$12,012,436.80 against a ~$372bn fund, weighs -0.0032%,
 * which truncated straight to two places used to print `"-0.00%"` -- indistinguishable from an
 * exact zero except for a minus sign a reader has no way to explain. An exact zero still renders
 * plainly as `"0.00%"`, with no sign and no marker, because a real zero and an unmeasurable
 * quantity must never look alike.
 *
 * Parses via `parseDecimalString` (`@/api/client`), which expands scientific notation first -- a
 * `Decimal` this small (ARK's Moog Inc weight, `6.5385669523052923658747931E-7`) is exactly the
 * shape `Decimal`'s Python serialisation switches to exponential notation for.
 */
export function formatWeight(value: DecimalString): string {
  const { negative, wholeRaw, fracRaw } = parseDecimalString(value);
  // Zero-ness must be checked against every digit the value carries, not just the ones that
  // survive truncation below -- otherwise a tiny non-zero weight and a true zero collapse onto
  // the same check, which is exactly how "-0.00%" happened in the first place.
  if (/^0*$/.test(wholeRaw) && /^0*$/.test(fracRaw)) return "0.00%";
  // Weight -> percent is a shift of the decimal point two places right: the first two fractional
  // digits become the whole part's new low digits, and the next two become the percent's own
  // fractional part.
  const fracPadded = (fracRaw + "0000").slice(0, 4);
  const wholeDigits = (wholeRaw + fracPadded.slice(0, 2)).replace(/^0+(?=\d)/, "");
  const fracPct = fracPadded.slice(2, 4);
  // `wholeDigits` can never be "" -- the `|| "0"` above guarantees at least one digit survives --
  // so a value too small to show at two decimal places truncates to the string "0", not "". Check
  // for that instead of the empty string this used to (wrongly) compare against.
  if (wholeDigits === "0" && fracPct === "00") return negative ? ">-0.01%" : "<0.01%";
  return `${negative ? "-" : ""}${wholeDigits}.${fracPct}%`;
}

/** Shares as a plain, comma-grouped count. Keeps any fractional part exactly as given (e.g. a DRIP
 *  fraction) rather than rounding it away -- unlike money, there is no fixed decimal precision to
 *  truncate to. Parses via `parseDecimalString` (`@/api/client`), so a scientific-notation share
 *  count (e.g. `"1E+3"`) expands to `"1,000"` rather than silently truncating to `"1"`. */
export function formatShares(value: DecimalString): string {
  const { negative, wholeRaw, fracRaw } = parseDecimalString(value);
  const whole = wholeRaw.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  // Trailing zeros are the wire format's padding, not precision anyone asked for. NPORT-P states
  // every balance to eight decimal places, so an un-stripped column reads
  // `102,954,591.00000000` on every row of every ETF -- eight characters of noise per cell,
  // widening the table enough to push the columns that carry the actual signal off the side.
  // Significant fractional digits still survive verbatim: a real fractional share prints as
  // `1,234.5`, and only the padding after it is dropped.
  const significant = fracRaw.replace(/0+$/, "");
  const frac = significant ? `.${significant}` : "";
  return `${negative && whole + significant !== "0" ? "-" : ""}${whole}${frac}`;
}

/** Signed share count, for `shares_delta` -- explicit `+`/`-` rather than colour alone, matching
 *  `formatSignedMoney`'s (`@/api/portfolio`) accessibility rule for every other signed figure in
 *  this app. */
export function formatSignedShares(value: DecimalString): string {
  const { negative, wholeRaw, fracRaw } = parseDecimalString(value);
  const isZeroValue = /^0*$/.test(wholeRaw) && /^0*$/.test(fracRaw);
  if (isZeroValue || negative) return formatShares(value);
  return `+${formatShares(value)}`;
}

/**
 * `shares_pct_change`, formatted -- `null` renders as the word `"new"`, never `"0%"` (which would
 * understate a position that did not exist last period) and never `"∞"`/`"Infinity"` (technically
 * defensible, useless to read).
 *
 * **The wire value is a fraction of one, not a percent**, exactly like the `weight` fields: the
 * server computes `shares_delta / shares_before` and the contract in `app/institutions/models.py`
 * says so. So this shifts the decimal point by two, delegating to `formatWeight` rather than
 * repeating the shift. Reading it as an already-scaled percent is off by a hundred in the one
 * direction that hides the story: Berkshire cut Capital One from 7,150,000 shares to 3,000,000 in
 * a single quarter, and the wire value `-0.5804895104895105` would have rendered as `-0.58%` --
 * a majority liquidation displayed as rounding noise.
 *
 * The only thing added on top of `formatWeight` is an explicit `+` on increases. A change column
 * is read by scanning signs, and a bare `58.04%` beside a `-58.04%` is ambiguous at a glance.
 *
 * `formatWeight` can return four shapes: an exact `"0.00%"`, a plain signed/unsigned percent, or
 * an under-threshold marker (`"<0.01%"` positive, `">-0.01%"` negative). Only the plain positive
 * shape wants a `+` -- prepending one to `"0.00%"` would claim a position grew when it did not
 * move by a measurable amount, and prepending one to a marker would produce `"+<0.01%"`, legible
 * to no one, when the marker's own leading `<`/`>` already carries the direction.
 */
export function formatSharesPctChange(value: DecimalString | null): string {
  if (value === null) return "new";
  const rendered = formatWeight(value);
  const alreadySigned = rendered.startsWith("-") || rendered.startsWith(">") || rendered.startsWith("<");
  return alreadySigned || rendered === "0.00%" ? rendered : `+${rendered}`;
}
