/**
 * Typed client for the tax endpoints.
 *
 * Mirrors `backend/app/tax/models.py` field for field. As with the rest of the API, every money
 * figure crosses the wire as a decimal *string* (pydantic serialises `Decimal` that way to preserve
 * precision past what an IEEE double can hold), so nothing here parses one into a `number` for
 * arithmetic. `formatMoney` renders a decimal string for display; `addMoney` combines two of them
 * exactly, using integer cents rather than floating point, for the one figure the backend does not
 * hand over pre-summed (`net_gain` is a Python `@property`, not a serialised field).
 */

import {
  ApiRequestError,
  centsToDecimalString,
  decimalStringToCents,
  type DecimalString,
} from "@/api/client";
import { formatMoney } from "@/format/money";
import { t, type MessageKey } from "@/i18n";

export type HoldingTerm = "short" | "long";

export type Form8949Box = "A" | "B" | "C" | "D" | "E" | "F";

export interface GainRow {
  disposal_id: string;
  instrument_id: string;
  symbol: string;
  account_id: string;
  account_label: string;
  quantity: DecimalString;
  /** The lot these shares came out of. With `lot_method`, the answer to "which shares did I sell". */
  lot_id: string;
  /**
   * `"fifo"` when a rule selected the lot; `null` on an oversold shortfall, where the replay found
   * no lot to consume. Lot selection changes the tax outcome, so it is stated rather than left to
   * be inferred by dividing basis by quantity — which is what a user actually had to do before.
   */
  lot_method: string | null;
  acquired_date: string;
  holding_start: string;
  disposed_date: string;
  term: HoldingTerm;
  proceeds: DecimalString;
  cost_basis: DecimalString;
  fees: DecimalString;
  gain_loss: DecimalString;
  /** Total disallowed under §1091 — deferred and permanent portions together. */
  disallowed_loss: DecimalString;
  /**
   * The destroyed portion (Rev. Rul. 2008-5). A sale replaced partly in an IRA and partly in a
   * taxable account carries both, so this is an amount rather than a share of the whole. The
   * deferred portion is `disallowed_loss` minus this.
   */
  permanently_disallowed_loss: DecimalString;
  /** True when any part is permanent. Use the amounts, not this flag, for arithmetic. */
  permanently_disallowed: boolean;
  reportable_gain_loss: DecimalString;
  is_wash_sale: boolean;
  basis_uncertain: boolean;
  /**
   * `fees = 0` on this disposal's sale because the source export has no fee column at all
   * (currently: every Webull sale), not because no fee was charged. Independent of
   * `basis_uncertain` -- proceeds are only slightly overstated here, not the basis itself.
   */
  fees_unknown: boolean;
}

export interface GainsReport {
  start: string;
  end: string;
  rows: GainRow[];

  short_term_proceeds: DecimalString;
  short_term_basis: DecimalString;
  short_term_gain: DecimalString;
  long_term_proceeds: DecimalString;
  long_term_basis: DecimalString;
  long_term_gain: DecimalString;

  /** Ordinary wash sales: deferred, added to a replacement lot's basis. */
  disallowed_loss_total: DecimalString;
  /** Rev. Rul. 2008-5 IRA replacements: gone. Never sum this with `disallowed_loss_total`. */
  permanently_disallowed_total: DecimalString;

  excluded_account_ids: string[];
  rows_with_uncertain_basis: number;
  /**
   * Reportable gain contributed by the rows counted in `rows_with_uncertain_basis`.
   *
   * A count is not a size, and the two can tell opposite stories: on a real ledger a small
   * fraction of rows can carry an unestablished basis, but those rows are disproportionately
   * the large ones (an ACAT transfer of an existing position, not five shares of a small buy), so
   * they can carry a majority of the year's reported gain. Exists so a caveat can state the size
   * of the doubt, not just its existence. Mirrors `GainsReport.gain_on_uncertain_basis` in
   * `backend/app/tax/models.py`.
   */
  gain_on_uncertain_basis: DecimalString;
  /** Gross proceeds on those same rows. With `basis_on_uncertain_basis`, says how much of the
   *  sale value has a known cost behind it and how much does not. */
  proceeds_on_uncertain_basis: DecimalString;
  /** Basis actually established on those rows — partial, not zero, for a row whose lot was only
   *  partly uncertain. */
  basis_on_uncertain_basis: DecimalString;
  /** Rows carrying `fees_unknown`. Counted separately from `rows_with_uncertain_basis`. */
  rows_with_unknown_fees: number;
}

export interface Form8949Row {
  box: Form8949Box;
  description: string;
  date_acquired: string;
  date_sold: string;
  proceeds: DecimalString;
  cost_basis: DecimalString;
  adjustment_code: string | null;
  adjustment_amount: DecimalString;
  gain_loss: DecimalString;
  disposal_id: string;
}

export interface Form8949Report {
  rows: Form8949Row[];
  short_term_total_proceeds: DecimalString;
  short_term_total_basis: DecimalString;
  short_term_total_adjustment: DecimalString;
  short_term_total_gain: DecimalString;
  long_term_total_proceeds: DecimalString;
  long_term_total_basis: DecimalString;
  long_term_total_adjustment: DecimalString;
  long_term_total_gain: DecimalString;
}

export interface WashSaleEvent {
  event_id: string;
  disposal_id: string;
  instrument_id: string;
  symbol: string;

  sale_date: string;
  sale_account_id: string;
  quantity_sold: DecimalString;
  loss_amount: DecimalString;

  quantity_replaced: DecimalString;
  disallowed_loss: DecimalString;

  replacement_txn_ids: string[];
  replacement_lot_ids: string[];
  replacement_account_ids: string[];

  /** Rev. Rul. 2008-5: replacement bought in an IRA. The loss is gone, not deferred. */
  permanently_disallowed: boolean;
  basis_added_to_lot_id: string | null;
  holding_period_tolled_to: string | null;
  is_chained: boolean;
}

export interface UnsettledPair {
  sale_disposal_id: string;
  sold_symbol: string;
  replacement_symbol: string;
  sale_date: string;
  loss_amount: DecimalString;
  /** Disallowed amount were the pair treated as substantially identical. Positive. */
  impact_if_identical: DecimalString;
  /** Disallowed amount otherwise -- normally zero. */
  impact_if_distinct: DecimalString;
  rationale: string;
}

/**
 * One thing the replay or the wash-sale pass could not resolve cleanly, structured for display.
 * `kind` is a stable machine token (`"oversold"`, `"missing_basis"`, `"unmatched_transfer_in"`,
 * `"fees_unknown"`, `"backward_basis_attachment"`, ...) so the page can group without parsing
 * prose.
 */
export interface TaxWarning {
  kind: string;
  account_id: string | null;
  broker: string | null;
  symbol: string | null;
  trade_date: string | null;
  detail: string;
}

/** Warnings of one `(kind, account_id)` pair, collapsed to a count for the headline view. */
export interface WarningGroup {
  kind: string;
  account_id: string | null;
  broker: string | null;
  count: number;
  sample_detail: string;
}

/**
 * One symbol's wash-sale exposure for the year, pre-aggregated server-side from its
 * `WashSaleEvent`s. Backs the per-symbol panel on the Tax page, which sits above the raw
 * `WashSaleTable` -- that table is one row per event; this is one row per symbol.
 *
 * `deferred_disallowed` and `permanently_disallowed` are never summed: see the module docstring
 * on `WashSaleSummary` below for why, and `TaxReport.wash_sale_summary` for the field this lives
 * under.
 */
export interface WashSaleSymbolSummary {
  symbol: string;
  /**
   * Added to a replacement lot's cost basis, not lost. It comes back when *that* lot is sold --
   * and only if the repurchase that relieves it does not itself land inside 30 days of that
   * sale, which would defer it again rather than release it. Waiting past `repurchase_safe_on`
   * does not return this money; only selling the replacement lot does.
   */
  deferred_disallowed: DecimalString;
  /**
   * Rev. Rul. 2008-5: the replacement was bought inside an IRA, so no basis was added anywhere.
   * Gone outright -- no sale, no waiting, and no lot recovers it. Never sum with
   * `deferred_disallowed`; the two answer different questions ("when does this come back" has an
   * answer for one and not the other).
   */
  permanently_disallowed: DecimalString;
  event_count: number;
  loss_sale_count: number;
  first_sale_date: string;
  last_sale_date: string;
  /**
   * `last_sale_date` + 31 days -- the first day a repurchase of this symbol no longer falls
   * inside that sale's §1091 window (30 days before or after). Governs only the *next*
   * disallowance risk on a fresh purchase; it has no bearing on when `deferred_disallowed`
   * money reappears, which is on the sale of the replacement lot, not on a calendar date.
   */
  repurchase_safe_on: string;
  /** Days remaining until `repurchase_safe_on`. Never negative -- clamped to `0` once safe. */
  days_until_safe: number;
  window_is_open: boolean;
  accounts: string[];
}

/**
 * Per-symbol wash-sale exposure for the year, aggregated from `TaxReport.wash_sales` server-side.
 *
 * The two money totals here answer different questions and must never be added together for a
 * combined "wash-sale impact" figure: `total_deferred` is money still in the system, riding on a
 * replacement lot's basis until that lot sells; `total_permanently_disallowed` is money the IRS
 * rule destroyed outright (Rev. Rul. 2008-5, an IRA replacement) with no lot anywhere carrying it.
 * A single combined number would tell the reader an amount is "at stake" when part of it is not at
 * stake at all -- it is simply gone -- and part of it is not owed back on any date, only on a future
 * sale. See `frontend/src/pages/Tax.tsx`'s `WashSaleSymbolPanel` for how this renders.
 */
export interface WashSaleSummary {
  as_of: string;
  /** Sorted by the backend, deferred descending. */
  symbols: WashSaleSymbolSummary[];
  total_deferred: DecimalString;
  total_permanently_disallowed: DecimalString;
  open_window_count: number;
}

export interface TaxReport {
  tax_year: number;
  generated_at: string;
  gains: GainsReport;
  form8949: Form8949Report;
  /** Paged by `limit`/`offset` -- see `disposals_total`/`wash_events_total` below for the true
   *  counts once this array is a page rather than the whole year. */
  wash_sales: WashSaleEvent[];
  unsettled: UnsettledPair[];
  /**
   * Every basis/fee gap the replay or wash-sale pass could not resolve, one entry per occurrence
   * -- the full, ungrouped detail, for an expandable view. See `warning_groups` for the
   * `(kind, account)` counts the page leads with. Never paginated -- only `gains.rows` and
   * `wash_sales` scale with disposal count; this list does not.
   */
  warnings: TaxWarning[];
  /** `warnings` collapsed to one row per `(kind, account_id)`, sorted by count descending. */
  warning_groups: WarningGroup[];
  /** `null` when the backend has not computed it (or there is nothing to summarize) -- render
   *  nothing in that case, not an empty table. See `WashSaleSummary`'s docstring. */
  wash_sale_summary: WashSaleSummary | null;

  // --- paging metadata for `gains.rows` and `wash_sales` -- see `taxApi.report`'s `TaxReportPage`
  // and `app.api.tax._paginate_report` on the backend. Optional, not required: a response from a
  // backend that predates paging (or a hand-built test fixture elsewhere in this codebase, e.g.
  // `Overview.test.tsx`'s own `TaxReport` stand-in) simply omits these, and every reader below falls
  // back to `.length` -- the exact value these fields equal whenever a caller does not paginate --
  // rather than requiring every existing caller of this type to learn about paging it may not use.
  // Mirrors the `wash_sale_summary` field above, whose own "older API" test in `Tax.test.tsx` pins
  // the same contract: an old/absent value must read as "not paginated", never throw. ---

  /** `len(gains.rows)` for the *whole* year, ignoring `limit`/`offset` -- read this for a count
   *  (e.g. the Disposals tab's badge), never `gains.rows.length`, which shrinks to the page size
   *  once a page has been requested. Falls back to `gains.rows.length` when absent. */
  disposals_total?: number;
  /** The `wash_sales` analogue of `disposals_total`. Falls back to `wash_sales.length`. */
  wash_events_total?: number;
  /** The `limit` this response was built with. `null`/absent means neither list above was sliced. */
  limit?: number | null;
  /** The `offset` this response was built with -- applies to *both* `gains.rows` and `wash_sales`
   *  identically, since the Tax page only ever needs one of its two paged tabs at a time. */
  offset?: number;
  /** Whether `gains.rows` has more rows beyond this page. Falls back to `false`. */
  disposals_has_more?: boolean;
  /** Whether `wash_sales` has more events beyond this page. Falls back to `false`. */
  wash_events_has_more?: boolean;
}

// --- 1099-B reconciliation ------------------------------------------------------------------

/**
 * Why a line does not agree. Mirrors `app.tax.models.ReconcileStatus`.
 *
 * The two "missing" cases are opposites and must never be shown as one "mismatch" count. Missing
 * from the engine means the broker reported a disposal we did not compute — usually a transaction
 * absent from the imported export, so the *ledger* is incomplete. Missing from the 1099-B means we
 * computed one the broker did not report, which is a different investigation entirely.
 */
export type ReconcileStatus =
  | "matched"
  | "amount_differs"
  | "missing_from_engine"
  | "missing_from_1099b";

export interface ReconcileLine {
  symbol: string;
  account_id: string;
  term: HoldingTerm;
  status: ReconcileStatus;

  engine_proceeds: DecimalString;
  engine_basis: DecimalString;
  engine_gain: DecimalString;
  form_proceeds: DecimalString;
  form_basis: DecimalString;
  form_gain: DecimalString;

  /**
   * Engine minus form, computed server-side in `Decimal`. Present on the wire rather than derived
   * here because money is a string by design and this is the column the whole comparison exists
   * for — subtracting two decimal strings in the browser is exactly what that design forbids.
   */
  proceeds_delta: DecimalString;
  basis_delta: DecimalString;
  gain_delta: DecimalString;

  /** The disposals behind the engine's side, so a mismatch can be walked back to specific lots. */
  disposal_ids: string[];
  /** The likely cause, where one is identifiable. English, and the fallback when `note_code` is
   *  absent or unrecognised. */
  note: string | null;
  /** A language-neutral id for `note`'s sentence (`missing_from_1099b`, `amount_differs_wash_higher`,
   *  …), so a localised client renders its own translation. `null` when there is no note. Unknown
   *  codes fall back to `note` — see `ReconcilePanel`. */
  note_code?: string | null;
  /** The values interpolated into `note_code`'s sentence (`symbol`, the wash-sale `amount`). */
  note_params?: Record<string, string> | null;
}

export interface ReconcileReport {
  lines: ReconcileLine[];
  matched_count: number;
  differing_count: number;
  total_gain_delta: DecimalString;
}

/** The header row this endpoint accepts, offered as a starting point for transcription. */
export const RECONCILE_CSV_TEMPLATE =
  "Symbol,Account,Term,Proceeds,Cost Basis,Wash Sale Disallowed\n";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiRequestError(response.status, detailOf(body) || response.statusText);
  }
  return (await response.json()) as T;
}

/**
 * Unwrap FastAPI's `{"detail": ...}`.
 *
 * The reconcile endpoint writes errors meant to be read — "row 12: unrecognised term 'LT '" — for a
 * user hand-transcribing a broker form. Showing them the JSON envelope around that sentence would
 * waste the one thing that makes the error actionable.
 */
function detailOf(body: string): string {
  if (!body) return "";
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const detail = (parsed as { detail: unknown }).detail;
      return typeof detail === "string" ? detail : JSON.stringify(detail);
    }
  } catch {
    // Not JSON; the raw body is still the best thing to show.
  }
  return body;
}

// `year` is typed `number` and every caller sources it from a backend response, so there is no
// injector here today and these two lines were never a defect. They are encoded anyway because
// every other URL in this API layer encodes (`market.ts`, `macro.ts`, `report.ts`, `backtest.ts`),
// and being the only two that do not is the kind of inconsistency that reads as "this one was
// checked and found safe" to one reader and "this one was missed" to the next. Encoding costs
// nothing on a numeric year and keeps the rule uniform: interpolated path and query values are
// encoded, without exception, so the exception never has to be re-derived.
/** Optional paging for `taxApi.report` -- see `TaxReport.limit`/`offset` for what these govern. */
export interface TaxReportPage {
  limit?: number;
  offset?: number;
}

export const taxApi = {
  report: (year: number, page?: TaxReportPage) => {
    const params = new URLSearchParams({ year: String(year) });
    if (page?.limit !== undefined) params.set("limit", String(page.limit));
    if (page?.offset !== undefined) params.set("offset", String(page.offset));
    return requestJson<TaxReport>(`/api/tax/report?${params.toString()}`);
  },
  /** Not fetched -- handed to an <a href> so the browser drives the download natively. */
  form8949CsvUrl: (year: number) =>
    `/api/tax/form8949.csv?year=${encodeURIComponent(String(year))}`,
  /**
   * The other two halves of the reconciliation pack: the Disposals table and the year's triggered
   * wash-sale events, as CSV. Same "hand it to an <a href>" contract as `form8949CsvUrl` above --
   * neither is fetched, so neither needs an error path in the page.
   *
   * Both are **UTF-8 with a BOM** and both are unpaginated: they mirror the whole year's table, not
   * the page of it currently on screen. See `backend/app/tax/export.py` for the column order, which
   * mirrors the on-screen tables left to right.
   *
   * `washSalesCsvUrl` is year-scoped by sale date, matching the Tax page's Wash sales tab. It is
   * NOT the Wash Sales page's whole-ledger tracker (`@/api/washsales`), which has no year at all --
   * the two answer different questions and their totals are expected to differ.
   */
  disposalsCsvUrl: (year: number) =>
    `/api/tax/export/disposals.csv?year=${encodeURIComponent(String(year))}`,
  washSalesCsvUrl: (year: number) =>
    `/api/tax/export/washsales.csv?year=${encodeURIComponent(String(year))}`,
  /**
   * Diff the computed gains against a 1099-B the user transcribed to CSV.
   *
   * The body is the CSV itself as `text/plain`, matching the endpoint's `Body(media_type=...)`.
   * A 400 carries a parse error naming the offending row -- "row 12: unrecognised term 'LT '" --
   * which is the whole reason that error type exists, so it is surfaced verbatim rather than
   * replaced with a generic failure message.
   */
  reconcile: (year: number, csvText: string, signal?: AbortSignal) =>
    requestJson<ReconcileReport>(
      `/api/tax/reconcile?year=${encodeURIComponent(String(year))}`,
      {
        method: "POST",
        headers: { "Content-Type": "text/plain" },
        body: csvText,
        signal: signal ?? null,
      },
    ),
};

// --- money formatting (display only -- never do arithmetic on a DecimalString via these) ---------
// Moved to `@/format/money` (was a local copy identical to `@/api/personas` and
// `@/api/tradingagents`'s own); re-exported here so every existing `import { formatMoney } from
// "@/api/tax"` across the app keeps working unchanged.

export { formatMoney };

/**
 * Exact addition of two decimal strings via integer cents. Used only for `net_gain`, which the
 * backend exposes as a Python property rather than a serialised field.
 *
 * Rounds each operand half-up to cents via `decimalStringToCents` (`@/api/client`), matching
 * `api/portfolio.ts`'s `sumMoney`/`multiplyMoneyByQuantity`/`subtractMoney`/`compareMoneyDesc` rather
 * than the truncating `toCents` this function used to carry its own copy of -- see that module's
 * `sumMoney` docstring for the concrete $0.02 mismatch bug the truncating version of this pattern
 * once caused.
 */
export function addMoney(a: DecimalString, b: DecimalString): DecimalString {
  return centsToDecimalString(decimalStringToCents(a) + decimalStringToCents(b));
}

/**
 * Rounded percentage `part` is of `whole`, e.g. `moneyPercentOf(gain_on_uncertain_basis,
 * short_term_gain)` for "82% of the reported gain". Computed via integer cents, never
 * `parseFloat`, exactly like `addMoney` above — but the *result* is a small bounded integer
 * (typically 0-100), and converting only that final number to `Number` costs no precision. The
 * distinction matters: money must never round-trip through a float, a two- or three-digit display
 * percentage rounding through one is invisible.
 *
 * Returns `null` when `whole` is zero rather than throwing or producing `NaN`/`Infinity` — a
 * caller with a genuinely empty denominator (a year with no reportable gain at all) should drop
 * the percentage clause, not render a broken one.
 */
export function moneyPercentOf(part: DecimalString, whole: DecimalString): number | null {
  const toCents = (v: string): bigint => {
    const trimmed = v.trim();
    const negative = trimmed.startsWith("-");
    const digits = trimmed.replace(/^[+-]/, "");
    const [wholeRaw, fracRaw = ""] = digits.split(".");
    const frac = (fracRaw + "00").slice(0, 2);
    const cents = BigInt(wholeRaw || "0") * 100n + BigInt(frac || "0");
    return negative ? -cents : cents;
  };
  const partCents = toCents(part);
  const wholeCents = toCents(whole);
  if (wholeCents === 0n) return null;
  const numerator = partCents * 100n;
  const negative = (numerator < 0n) !== (wholeCents < 0n);
  const absNumerator = numerator < 0n ? -numerator : numerator;
  const absDenominator = wholeCents < 0n ? -wholeCents : wholeCents;
  // Half-up on the absolute value, ties away from zero -- same rounding rule as `sumMoney`.
  const pct = (absNumerator + absDenominator / 2n) / absDenominator;
  return Number(negative ? -pct : pct);
}

// --- warning vocabulary --------------------------------------------------------------------------

/**
 * Human label for a warning's machine `kind`.
 *
 * Lives here, beside `TaxWarning`, because these tokens are produced by
 * `app.core.lots.WarningKind` on the backend — one source of truth there should mean one here.
 * It was briefly duplicated in `api/portfolio.ts` on the reasoning that the two pages might want
 * to diverge; that trades a real hazard for a hypothetical benefit. Add a kind server-side and the
 * page that was not updated silently renders a raw token like `unsupported_action` next to prose
 * labels, which reads as a bug in the data rather than a gap in a lookup table.
 *
 * Falls back to the raw token for a kind this map does not know, rather than dropping it — an
 * unrecognised warning is exactly the thing that must not silently vanish from a page whose job is
 * to say what could not be resolved.
 *
 * Translated via the module-level `t()` rather than `useT()` -- this is a plain function, not a
 * component, so it has no hook to hang a subscription on. Every caller (`Tax.tsx`, `Portfolio.tsx`)
 * renders this function's return value from inside a component that itself calls `useT()`, so the
 * caller re-renders (and this re-evaluates in the newly active language) on a language toggle; see
 * `useT.ts`'s own docstring on why the caller, not this helper, is what has to subscribe.
 */
const WARNING_KIND_LABEL_KEY: Record<string, MessageKey> = {
  oversold: "tax.warningKind.oversold",
  missing_basis: "tax.warningKind.missingBasis",
  unmatched_transfer_in: "tax.warningKind.unmatchedTransferIn",
  fees_unknown: "tax.warningKind.feesUnknown",
  fees_estimated: "tax.warningKind.feesEstimated",
  unsupported_action: "tax.warningKind.unsupportedAction",
  split_without_ratio: "tax.warningKind.splitWithoutRatio",
  // The share count is right either way -- a transfer conserves quantity -- so this must not read
  // like the position is in doubt. What is in doubt is which account the shares left, and therefore
  // whose cost basis and holding period travelled with them.
  ambiguous_transfer_direction: "tax.warningKind.ambiguousTransferDirection",
  backward_basis_attachment: "tax.warningKind.backwardBasisAttachment",
};

export function warningKindLabel(kind: string): string {
  const key = WARNING_KIND_LABEL_KEY[kind];
  return key ? t(key) : kind;
}
