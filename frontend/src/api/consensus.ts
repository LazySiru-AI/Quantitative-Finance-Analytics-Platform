/**
 * Typed client for the cross-institution consensus endpoint.
 *
 * Answers a different question than `@/api/institutions`: not "what does fund X hold" but "what are
 * many tracked funds doing right now, in agreement." The backend walks every tracked filer, diffs
 * each one against its own previous filing, and ranks CUSIPs by how many funds moved the same
 * direction. As with the rest of this API, every money and weight figure crosses the wire as a
 * decimal *string* (`DecimalString`); nothing here parses one into a `number` for arithmetic, only
 * for display -- see `formatWeight`/`formatSharesPctChange`/`formatSignedShares` in
 * `@/api/institutions`, which this module reuses rather than re-implementing.
 *
 * Four things this contract makes true that a naive "N funds bought NVDA" headline would hide:
 *
 * **1. `checked` is the real denominator, `unchecked` is why it is smaller than the tracked
 * universe.** A fund that failed to load is not a fund that declined to buy -- it is a fund nobody
 * measured this run. `buyer_count`/`seller_count` on every row are counted out of `checked.length`
 * funds, never out of the full tracked list. Any UI built on this data must render `unchecked`
 * (with its `reason`) next to the count, not drop it once the happy path renders.
 *
 * **2. Different movers file for different periods.** `FundMove.period` is *that fund's own* filing
 * period, not a shared "as of" date for the whole row -- one mover's `period` can be a full quarter
 * behind another's on the very same CUSIP. A "consensus" that silently blended Q2 and Q3 movers into
 * one number would not be one; every mover must show its own `period`.
 *
 * **3. `13F` and `NPORT` are not the same instrument.** A 13F is a manager's US-listed-equities-only
 * slice, filed ~45 days after quarter end; an NPORT-P is an ETF's whole book, filed ~60 days later.
 * Blending the two into one undifferentiated "N funds moved" count would compare different regimes as
 * though they measured the same thing -- `FundMove.source` exists so a reader can tell them apart per
 * mover, matching the rule `@/api/institutions`'s module docstring states for `SOURCE_NOTE`.
 *
 * **4. Every figure here is stale by construction.** `generated_at` is when this response was
 * computed, not when any position changed -- the underlying filings still lag their quarter end by
 * the same ~45/~60 days `@/api/institutions` describes. This is history, not a live tape.
 */

import { ApiRequestError, type DecimalString } from "@/api/client";
import type { Action, Source } from "@/api/institutions";

export type { Action, Source };

/**
 * One tracked fund's move on one CUSIP, contributing to that CUSIP's consensus ranking.
 *
 * `principal` and `action` carry the same meaning and the same provenance rules as their namesakes
 * in `@/api/institutions` (`FundRef.principal`, `HoldingChange.action`): `principal` is editorial
 * labelling from the watchlist, never a claim about who personally decided anything, and `action` is
 * computed server-side from share columns, never re-derivable here from `weight_delta` alone (a
 * weight can move on price with no trade at all -- see that module's Chevron example).
 */
export interface FundMove {
  key: string;
  name: string;
  /** The person the fund is publicly associated with, e.g. "Cathie Wood" -- `null` where naming one
   *  would mislead. Prefer this over `name` when rendering a mover, falling back to `name`. */
  principal: string | null;
  action: Action;
  weight_delta: DecimalString;
  shares_delta: DecimalString;
  /** THIS fund's own filing period, `"YYYY-MM-DD"` -- not a shared date for the row. Two movers on
   *  the same CUSIP can carry different periods; always render this per mover, never assume it
   *  matches a sibling mover or the response's own `as_of`. */
  period: string;
  source: Source;
}

/** One CUSIP's ranking, with every fund that moved it since its own last filing. */
export interface ConsensusRow {
  cusip: string;
  issuer: string;
  /** Non-null only where this CUSIP matched something in the user's own ledger -- same rule as
   *  `Holding.ticker` in `@/api/institutions`. Never synthesised from `issuer`. */
  ticker: string | null;
  /** How many of the `checked` funds moved to increase this position -- out of `checked.length`,
   *  never out of the full tracked universe. */
  buyer_count: number;
  /** How many of the `checked` funds moved to decrease this position -- same denominator caveat. */
  seller_count: number;
  net_funds: number;
  /** Summed `weight_delta` across every mover on this row -- a fraction of one, formatted the same
   *  way as any other weight-shaped decimal via `formatWeight`/`formatSharesPctChange`. */
  total_weight_delta: DecimalString;
  /** Ranked or not, every fund that moved this CUSIP -- the detail behind `buyer_count`/
   *  `seller_count`, never fewer entries than those two counts sum to. */
  movers: FundMove[];
}

/** A tracked fund whose latest filing could not be diffed this run, and why -- the other half of
 *  `checked`. Same shape as `UncheckedFund` in `@/api/institutions`, kept as an independent type
 *  here since the two endpoints are not guaranteed to version together. */
export interface UncheckedFund {
  key: string;
  name: string;
  reason: string;
}

/**
 * The full consensus response.
 *
 * **`checked` and `unchecked` are not diagnostics -- they decide what every count on `buys`/`sells`
 * means.** `buyer_count`/`seller_count` on each `ConsensusRow` are counted out of `checked.length`
 * funds; `unchecked` is why that number can be smaller than the full tracked universe. Any UI
 * rendering `buys` or `sells` must render `checked`/`unchecked` too, not bury them behind a click a
 * reader has no reason to make.
 */
export interface ConsensusResponse {
  /** When this response was computed -- ISO datetime. Not a live timestamp: the filings behind it
   *  are already months old by construction (see this module's docstring). */
  generated_at: string;
  /** The as-of date this run compared filings through, `"YYYY-MM-DD"`, or `null` when the server
   *  used its own default (the latest filings on record for each fund). */
  as_of: string | null;
  /** Fund keys successfully diffed this run -- the real denominator for every count on `buys`/
   *  `sells`. */
  checked: string[];
  unchecked: UncheckedFund[];
  /** Ranked most-bought first -- do not re-sort client-side; the ranking is the server's own
   *  ordering decision, matching this codebase's rule (see `PortfolioDelta.counts` in
   *  `@/api/institutions`) against a second, possibly-disagreeing client-side computation of the
   *  same thing. */
  buys: ConsensusRow[];
  /** Ranked most-sold first -- same rule as `buys`. */
  sells: ConsensusRow[];
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

export interface ConsensusParams {
  /** `"YYYY-MM-DD"`. Omitted to let the server use its own default. */
  asOf?: string;
  /** Force a fresh comparison rather than serving a cached one. */
  refresh?: boolean;
  /** Cap on rows per side (`buys`/`sells`). Omitted to let the server use its own default. */
  limit?: number;
}

export const consensusApi = {
  /**
   * Every value goes through `encodeURIComponent`/`URLSearchParams` rather than manual string
   * concatenation, matching `@/api/institutions`'s stated rule against treating a same-origin,
   * server-adjacent string as safe to interpolate unencoded.
   */
  get: (params: ConsensusParams = {}, signal?: AbortSignal) => {
    const qs = new URLSearchParams();
    if (params.asOf) qs.set("as_of", params.asOf);
    if (params.refresh) qs.set("refresh", "true");
    if (params.limit != null) qs.set("limit", String(params.limit));
    const query = qs.toString();
    return requestJson<ConsensusResponse>(
      `/api/institutions/consensus${query ? `?${query}` : ""}`,
      { signal: signal ?? null },
    );
  },
};
