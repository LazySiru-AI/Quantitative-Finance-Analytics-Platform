/**
 * Typed client for the Portfolio Planner board (`/api/designer`).
 *
 * Three calls, mirroring the backend module's three endpoints:
 *  - `board()` / `saveBoard()` read and write the persisted, per-account planning board. The board
 *    stores *intent only* -- which tickers sit in which account column, and one free-text note per
 *    account. It carries no money, no wash-sale status and no holdings: all of that is decorated
 *    live by the page from `@/api/portfolio` and `@/api/washsales`, because "can I buy this back
 *    yet" depends on today's date and must never be frozen into a saved board.
 *  - `universe()` is the search palette's symbol list (index constituents + the sector map), fetched
 *    once on mount and filtered client-side.
 *
 * The whole prefix is owner-only (see `backend/app/auth/gate.py`), so a member gets a 403 from every
 * call here -- the route is `OwnerGate`d in `App.tsx` for the same reason, so this client is only
 * ever reached by an owner in practice.
 */

import { ApiRequestError } from "@/api/client";

/** One ticker in a column. Symbol only -- the note lives on the column, never the ticker. */
export interface DesignerTicker {
  symbol: string;
}

/**
 * One account's planning column. `account_id` is the persistence key ("data stored per account");
 * `label`/`tax_treatment`/`account_type` are denormalised copies of the account's own fields so the
 * board renders without a second lookup, not an authoritative source.
 */
export interface DesignerColumn {
  account_id: string;
  label: string;
  tax_treatment: string | null;
  account_type: string | null;
  note: string;
  tickers: DesignerTicker[];
}

/**
 * The whole board. `updated_at` is `null` for the never-saved default (one empty column per open
 * account) and an ISO 8601 timestamp once saved -- its absence is how the page distinguishes the
 * empty default from a board the owner deliberately emptied.
 */
export interface DesignerBoard {
  columns: DesignerColumn[];
  updated_at: string | null;
}

/** One searchable symbol and its sector. No `held` flag -- holdings are live state read elsewhere. */
export interface UniverseSymbol {
  symbol: string;
  sector: string;
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

export const designerApi = {
  board: (signal?: AbortSignal) =>
    requestJson<DesignerBoard>("/api/designer/board", { signal: signal ?? null }),

  saveBoard: (board: DesignerBoard) =>
    requestJson<DesignerBoard>("/api/designer/board", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(board),
    }),

  universe: (signal?: AbortSignal) =>
    requestJson<UniverseSymbol[]>("/api/designer/universe", { signal: signal ?? null }),
};
