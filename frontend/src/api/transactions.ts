/**
 * Typed client for the transaction-history endpoint.
 *
 * Mirrors `backend/app/api/transactions.py` field for field. Money and quantities are decimal
 * *strings* throughout, as everywhere else in this API — nothing here parses one into a `number` to
 * do arithmetic with.
 *
 * The one thing worth knowing before using these types: **the aggregate fields describe the whole
 * filtered set, not the page.** `total_bought`, `total_sold` and `net_cash_flow` are computed
 * server-side across every matching row, so they stay correct when only a page of rows came back.
 * Recomputing them from `transactions` would silently answer a different question.
 */

import { ApiRequestError, type DecimalString } from "@/api/client";
import { t } from "@/i18n";

export interface TransactionRow {
  txn_id: string;
  account_id: string;
  broker: string;
  /** Canonical action: `buy`, `sell`, `dividend`, `fee`, `cash_in`, … */
  action: string;

  trade_date: string;
  settle_date: string | null;
  executed_at: string | null;
  /** Position in the source file. The tie-break that makes a same-day lot replay reproducible. */
  sequence: number;

  symbol: string | null;
  instrument_id: string | null;
  cusip: string | null;

  quantity: DecimalString | null;
  price: DecimalString | null;
  fees: DecimalString;
  /** Signed net cash effect; `null` for rows that move no cash (an ACAT position leg, a split). */
  amount: DecimalString | null;

  description: string | null;
  raw_code: string | null;

  /** With `source_row`, the coordinate of the exact CSV line behind this row. */
  import_id: string;
  source_row: number;
}

export interface TransactionPage {
  transactions: TransactionRow[];
  /** Rows matching the filters, ignoring paging. */
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  as_of: string | null;
  earliest: string | null;
  /** Across the filtered SET, not this page. Gross and unsigned — turnover, not cash flow. */
  total_bought: DecimalString;
  total_sold: DecimalString;
  /** Across the filtered SET. Includes fees and income, so it will NOT equal sold − bought. */
  net_cash_flow: DecimalString;
}

export interface TransactionQuery {
  account_id?: string;
  symbol?: string;
  action?: string;
  start?: string;
  end?: string;
  trades_only?: boolean;
  newest_first?: boolean;
  limit?: number;
  offset?: number;
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

export const transactionsApi = {
  list: (query: TransactionQuery = {}, signal?: AbortSignal) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") {
        params.set(key, String(value));
      }
    }
    const qs = params.toString();
    return requestJson<TransactionPage>(`/api/portfolio/transactions${qs ? `?${qs}` : ""}`, {
      signal: signal ?? null,
    });
  },
};

/**
 * Human label for a canonical action. Falls back to de-snake-casing an unrecognised code rather
 * than rendering it raw: the ledger's action vocabulary can grow (a new broker code maps to a new
 * `TxnAction`) and an unmapped value should still read as words, not as `stock_lending_income`.
 */
export function actionLabel(action: string): string {
  const LABELS: Record<string, string> = {
    buy: t("common.buy"),
    sell: t("common.sell"),
    dividend: t("activity.action.dividend"),
    interest: t("activity.action.interest"),
    stock_lending_income: t("activity.action.lendingIncome"),
    fee: t("activity.action.fee"),
    subscription_fee: t("activity.action.subscription"),
    transfer_in: t("activity.action.transferIn"),
    transfer_out: t("activity.action.transferOut"),
    cash_in: t("activity.action.deposit"),
    cash_out: t("activity.action.withdrawal"),
    internal_transfer: t("activity.action.internalTransfer"),
    ira_match: t("activity.action.iraMatch"),
    split: t("activity.action.split"),
    spinoff: t("activity.action.spinoff"),
    adjustment: t("activity.action.adjustment"),
    misc: t("activity.action.misc"),
  };
  return LABELS[action] ?? action.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/** Tone for an action, so buys and sells are distinguishable at a glance without relying on hue
 *  alone — the label is always present too. */
export function actionTone(action: string): "pos" | "neg" | "" {
  if (action === "sell" || action === "cash_in" || action === "dividend") return "pos";
  if (action === "buy" || action === "cash_out" || action === "fee") return "neg";
  return "";
}
