/**
 * Typed client for the wash-sale tracker endpoint.
 *
 * Mirrors `GET /api/tax/wash-sales`. Unlike `taxApi.report`, this endpoint takes no `year` — it is
 * whole-ledger and year-independent, because a wash sale's replacement lot can sit years away from
 * the sale that deferred a loss into it, and a per-year view would silently cut that link. As with
 * the rest of this API, every money figure crosses the wire as a decimal *string* (`DecimalString`,
 * from `@/api/client`), never a JSON `number` — nothing here parses one for arithmetic.
 *
 * **`deferred_disallowed` and `permanently_disallowed` must never be summed.** They answer
 * different questions about money that is not equally "at stake":
 *
 * - `deferred_disallowed` is added to a replacement lot's cost basis, not lost. It returns when
 *   *that* lot is sold, and only if the sale relieving it does not itself land inside 30 days
 *   (which would defer it again rather than release it). Waiting past `repurchase_safe_on` does
 *   **not** return this money; only selling the replacement lot does.
 * - `permanently_disallowed` is Rev. Rul. 2008-5: the replacement was bought inside an IRA, so no
 *   basis was added anywhere. Gone outright — no sale and no date recovers it.
 *
 * A single combined "wash-sale impact" number would tell the reader an amount is at stake when
 * part of it is not at stake at all. `WashSaleSummary` in `@/api/tax` carries the same warning for
 * the per-year figure this tracker generalises; match that standard wherever these render.
 *
 * **The two date fields answer different questions and are easy to confuse:**
 *
 * - `WashSaleTrackerSymbol.repurchase_safe_on` is the symbol's **latest** sale date + 31 days —
 *   "when may I buy this back without creating a fresh wash sale". It says nothing about when
 *   `deferred_disallowed` money comes back; that happens on a lot sale, not a calendar date.
 * - `WashSaleTrackerSale.window_closes_on` is **that individual sale's** date + 31 days — which
 *   specific sale is holding the symbol's window open. A symbol with several sales has one
 *   `repurchase_safe_on` (driven by the latest of them) and one `window_closes_on` per sale.
 */

import { ApiRequestError, type DecimalString } from "@/api/client";

/**
 * One sale that fed a wash sale for its symbol. One row per `WashSaleEvent`-like disposal, nested
 * under the symbol it belongs to — contrast `WashSaleTrackerSymbol`, which is the pre-aggregated
 * per-symbol rollup.
 */
export interface WashSaleTrackerSale {
  disposal_id: string;
  sale_date: string;
  account_id: string;
  quantity_sold: DecimalString;
  quantity_replaced: DecimalString;
  /** The loss realised on this sale, before any disallowance. */
  loss_amount: DecimalString;
  /** Total disallowed on this sale under §1091 — deferred and permanent portions together. */
  disallowed_loss: DecimalString;
  /** True when (all or part of) this sale's disallowed loss is the permanent, IRA-replacement kind. */
  permanently_disallowed: boolean;
  replacement_account_ids: string[];
  /**
   * `sale_date` + 31 days — the first day a repurchase of this symbol no longer falls inside
   * *this sale's* §1091 window. Not the same date as the symbol-level `repurchase_safe_on`; see
   * the module docstring.
   */
  window_closes_on: string;
}

/**
 * One symbol's whole-ledger wash-sale exposure, pre-aggregated server-side from its sales.
 *
 * `deferred_disallowed` and `permanently_disallowed` must never be summed — see the module
 * docstring for why the two are not commensurable.
 */
export interface WashSaleTrackerSymbol {
  symbol: string;
  /**
   * Added to a replacement lot's cost basis, not lost. Comes back when *that* lot is sold, and
   * only if the repurchase relieving it does not itself land inside 30 days of that sale. Waiting
   * past `repurchase_safe_on` does not return this money; only selling the replacement lot does.
   */
  deferred_disallowed: DecimalString;
  /**
   * Rev. Rul. 2008-5: the replacement was bought inside an IRA, so no basis was added anywhere.
   * Gone outright — no sale, no waiting, and no lot recovers it. Never sum with
   * `deferred_disallowed`.
   */
  permanently_disallowed: DecimalString;
  event_count: number;
  loss_sale_count: number;
  first_sale_date: string;
  last_sale_date: string;
  /**
   * `last_sale_date` + 31 days — the first day a repurchase of this symbol no longer falls inside
   * that sale's §1091 window. Governs only the *next* disallowance risk on a fresh purchase; it
   * has no bearing on when `deferred_disallowed` money reappears, which happens on the sale of the
   * replacement lot, not on a calendar date. See `WashSaleTrackerSale.window_closes_on` for the
   * per-sale version of this date.
   */
  repurchase_safe_on: string;
  /** Days remaining until `repurchase_safe_on`. Never negative — clamped to `0` once safe. */
  days_until_safe: number;
  window_is_open: boolean;
  accounts: string[];
  /** The individual sales behind this symbol's totals. Empty when the symbol has an aggregate
   *  entry but the backend did not (yet) expand its sale-level detail — render nothing rather
   *  than inferring a sale from the rollup figures. */
  sales: WashSaleTrackerSale[];
}

/**
 * Whole-ledger wash-sale exposure, as of `as_of`. Year-independent by design — see the module
 * docstring for why a `year` parameter would be wrong for this endpoint.
 *
 * `total_deferred` and `total_permanently_disallowed` must never be summed into one "impact"
 * figure, for the same reason their per-symbol counterparts must not: they answer different
 * questions about money that is not equally at stake.
 */
export interface WashSaleTracker {
  /** The ledger date this snapshot reflects. */
  as_of: string;
  /** When the backend computed this response, as an ISO 8601 timestamp. */
  generated_at: string;
  total_deferred: DecimalString;
  total_permanently_disallowed: DecimalString;
  open_window_count: number;
  symbol_count: number;
  symbols: WashSaleTrackerSymbol[];
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

export const washSalesApi = {
  /** No parameters — the endpoint is whole-ledger and year-independent. */
  tracker: (signal?: AbortSignal) =>
    requestJson<WashSaleTracker>("/api/tax/wash-sales", { signal: signal ?? null }),
};

// --- client-side year scoping ------------------------------------------------------------------
//
// `GET /api/tax/wash-sales` takes no `year` and is documented as never growing one: a replacement
// lot can sit years away from the sale that deferred a loss into it, and a per-year endpoint would
// silently cut that link. But "which of my wash sales happened in 2025" is still a real question a
// filer asks with a 1099-B in front of them, so the Wash Sales page answers it *in the browser*,
// over the sale dates the response already carries, and says on screen that it did.
//
// These helpers deliberately narrow **lists only**. Nothing here re-derives a money total: the
// symbol-level `deferred_disallowed` / `permanently_disallowed` figures are whole-ledger sums the
// backend computed, and the only year-scoped version derivable here would be a sum over `sales` --
// a list this API is explicitly allowed to leave empty (see `WashSaleTrackerSymbol.sales`). That
// sum would be silently short on exactly the symbols whose detail was not expanded — an
// understated tax figure wearing a precise-looking label. The page keeps the whole-ledger tiles
// and labels them for what they are instead.

/** The calendar year of an ISO `YYYY-MM-DD` date, or `null` if it is not one. */
export function yearOf(isoDate: string): number | null {
  const match = /^(\d{4})-\d{2}-\d{2}$/.exec(isoDate.trim());
  if (match?.[1] === undefined) return null;
  return Number(match[1]);
}

/**
 * Every year this tracker has a loss sale in, newest first — the options the page's scope switch
 * offers.
 *
 * Read off `sales[].sale_date` where sale detail exists, and off the symbol's own
 * `first_sale_date`/`last_sale_date` where it does not, so a symbol the backend did not expand
 * still contributes its years rather than vanishing from the switch. A symbol whose first and last
 * loss sales straddle a year with no sale in it contributes that middle year too; the page renders
 * that as an empty-for-this-year state, which is a truthful "nothing here", not a wrong option.
 */
export function washSaleYears(tracker: WashSaleTracker): number[] {
  const years = new Set<number>();
  for (const symbol of tracker.symbols) {
    if (symbol.sales.length > 0) {
      for (const sale of symbol.sales) {
        const year = yearOf(sale.sale_date);
        if (year !== null) years.add(year);
      }
      continue;
    }
    const first = yearOf(symbol.first_sale_date);
    const last = yearOf(symbol.last_sale_date);
    if (first === null || last === null) continue;
    for (let y = Math.min(first, last); y <= Math.max(first, last); y++) years.add(y);
  }
  return [...years].sort((a, b) => b - a);
}

/**
 * The symbols with a loss sale in `year`, each narrowed to that year's sales.
 *
 * Returns a plain array rather than a `WashSaleTracker` on purpose: a tracker object carries four
 * whole-ledger totals, and handing back one whose `symbols` had been filtered while its totals had
 * not would be an object that contradicts itself the moment anything reads both halves.
 *
 * A symbol with no expanded `sales` is kept whenever `year` falls inside its own first/last loss
 * sale span, with its (empty) `sales` untouched — the alternative is dropping a symbol that may
 * well have sold in that year, and a wash-sale page that silently omits an exposure is the one
 * failure this page's rules exist to prevent.
 */
export function symbolsInYear(
  tracker: WashSaleTracker,
  year: number,
): WashSaleTrackerSymbol[] {
  const out: WashSaleTrackerSymbol[] = [];
  for (const symbol of tracker.symbols) {
    if (symbol.sales.length === 0) {
      const first = yearOf(symbol.first_sale_date);
      const last = yearOf(symbol.last_sale_date);
      if (first === null || last === null) continue;
      if (year >= Math.min(first, last) && year <= Math.max(first, last)) out.push(symbol);
      continue;
    }
    const sales = symbol.sales.filter((sale) => yearOf(sale.sale_date) === year);
    if (sales.length > 0) out.push({ ...symbol, sales });
  }
  return out;
}
