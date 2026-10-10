/**
 * Activity: the transaction ledger itself.
 *
 * The page that answers "what did I actually do?" — which, before this existed, the application
 * could not. It had positions (what you hold) and a tax report (what you disposed of), and nothing
 * showing the buys in between, despite every one of them sitting in the ledger with full provenance.
 *
 * Two conventions carried from the rest of the app rather than reinvented here:
 *
 * **Aggregates describe the filtered set, not the page.** `total_bought`/`total_sold`/
 * `net_cash_flow` come from the server across every matching row. Summing the visible rows instead
 * would quietly answer a different question whenever a filter matches more than one page.
 *
 * **Provenance is reachable from the row.** Each row carries the import it came from and its
 * zero-based line number in that file, so any figure here can be walked back to the CSV line behind
 * it — the property the whole application is built around, finally visible.
 */

import { useCallback, useEffect, useState } from "react";

import { describeError } from "@/api/client";
import { formatMoney } from "@/api/tax";
import {
  actionLabel,
  actionTone,
  transactionsApi,
  type TransactionPage,
  type TransactionQuery,
} from "@/api/transactions";
import { FilterBar, TableCaption } from "@/components/tableSort";
import ImportPanel from "@/components/ImportPanel";
import { ScrollRegion } from "@/components/ScrollPanel";
import { useT } from "@/i18n";

type Phase = "loading" | "loaded" | "empty" | "error";

const PAGE_SIZE = 100;

export default function Activity() {
  const { t } = useT();
  const [page, setPage] = useState<TransactionPage | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);

  // Live: every keystroke here is the query, no separate "Apply" step -- `FilterBar` is fully
  // controlled and this page owns the one piece of state it reads and writes. The previous
  // two-state (`symbol` draft / `appliedSymbol` committed) split existed only to gate a fetch
  // behind a submit click; `FilterBar`'s own contract is "filters live", so that gate is gone and
  // a keystroke resets `offset` and re-fetches directly, same as `tradesOnly` already did.
  const [symbol, setSymbol] = useState("");
  const [tradesOnly, setTradesOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  // Bumped after an import that inserted rows, to re-run the fetch below. The ledger is the one
  // thing on this page that a user action elsewhere on it can change.
  const [ledgerVersion, setLedgerVersion] = useState(0);

  // The import panel is open by default only when there is nothing to show. On a populated ledger
  // it is a rarely-used control that would otherwise push the history it exists to produce below
  // the fold.
  const [importOpen, setImportOpen] = useState(false);

  const normalizedSymbol = symbol.trim().toUpperCase();

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    setPhase("loading");
    const query: TransactionQuery = {
      limit: PAGE_SIZE,
      offset,
      trades_only: tradesOnly,
      ...(normalizedSymbol ? { symbol: normalizedSymbol } : {}),
    };

    transactionsApi
      .list(query, controller.signal)
      .then((result) => {
        if (cancelled) return;
        setPage(result);
        setPhase(result.total === 0 ? "empty" : "loaded");
      })
      .catch((error: unknown) => {
        if (cancelled || controller.signal.aborted) return;
        setPage(null);
        setMessage(describeError(error, t("activity.error.couldNotLoad")));
        setPhase("error");
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [normalizedSymbol, tradesOnly, offset, ledgerVersion]);

  const handleSymbolChange = useCallback((value: string) => {
    setOffset(0);
    // Matches the pre-existing symbol-input semantics: the field itself always shows uppercase,
    // same as `tradesOnly`'s own instant-apply already worked before this change.
    setSymbol(value.toUpperCase());
  }, []);

  return (
    <>
      <h1>{t("activity.title")}</h1>
      <p className="subtitle">{t("activity.subtitle")}</p>

      {phase === "loaded" && (
        <div className="panel import-toggle-row">
          <button type="button" onClick={() => setImportOpen((open) => !open)}>
            {importOpen ? t("activity.importToggle.hide") : t("activity.importToggle.show")}
          </button>
          <span className="muted">{t("activity.importToggle.hint")}</span>
        </div>
      )}

      {(importOpen || phase === "empty" || phase === "error") && (
        <ImportPanel onImported={() => setLedgerVersion((n) => n + 1)} />
      )}

      <div className="panel activity-filter-row">
        <FilterBar
          query={symbol}
          onQueryChange={handleSymbolChange}
          queryPlaceholder={t("activity.filter.symbolPlaceholder")}
          shown={page?.transactions.length ?? 0}
          total={page?.total ?? 0}
        />
        <label className="checkbox">
          <input
            type="checkbox"
            checked={tradesOnly}
            onChange={(e) => {
              setOffset(0);
              setTradesOnly(e.target.checked);
            }}
          />
          {t("activity.filter.tradesOnly")}
        </label>
      </div>

      {phase === "loading" && (
        <div className="panel">
          <div className="placeholder">{t("activity.loading")}</div>
        </div>
      )}

      {phase === "error" && (
        <div className="panel">
          <div className="placeholder">{message}</div>
        </div>
      )}

      {phase === "empty" && (
        <div className="panel">
          <div className="placeholder">
            {normalizedSymbol || tradesOnly
              ? t("activity.empty.filtered")
              : t("activity.empty.noLedger")}
          </div>
        </div>
      )}

      {phase === "loaded" && page && (
        <>
          <SummaryTiles page={page} />
          <Pager page={page} offset={offset} onOffset={setOffset} />
          <TransactionTable page={page} />
          <Pager page={page} offset={offset} onOffset={setOffset} />
        </>
      )}
    </>
  );
}

function SummaryTiles({ page }: { page: TransactionPage }) {
  const { t } = useT();
  return (
    <div className="panel">
      <div className="tile-grid">
        <Tile
          label={t("activity.tile.transactions")}
          value={page.total.toLocaleString()}
          hint={page.earliest && page.as_of ? `${page.earliest} → ${page.as_of}` : undefined}
        />
        <Tile
          label={t("activity.tile.bought")}
          value={formatMoney(page.total_bought)}
          hint={t("activity.tile.grossHint")}
        />
        <Tile
          label={t("activity.tile.sold")}
          value={formatMoney(page.total_sold)}
          hint={t("activity.tile.grossHint")}
        />
        <Tile
          label={t("activity.tile.netCashFlow")}
          value={formatMoney(page.net_cash_flow)}
          // Spelled out because the arithmetic invites the wrong inference: this includes fees,
          // dividends and deposits, so it is not sold minus bought and will not reconcile against
          // the two tiles beside it.
          hint={t("activity.tile.netCashFlowHint")}
        />
      </div>
    </div>
  );
}

/** Same markup as `Portfolio.tsx`'s `MoneyTile`, minus the money formatting — these values are
 *  already-formatted strings and counts. Kept local rather than shared: the two pages agree on the
 *  CSS contract (`stat tile` / `label` / `value` / `tile-hint`), not on a component. */
function Tile({ label, value, hint }: { label: string; value: string; hint?: string | undefined }) {
  return (
    <div className="stat tile">
      <span className="label">{label}</span>
      <span className="value">{value}</span>
      {hint && <span className="tile-hint">{hint}</span>}
    </div>
  );
}

function TransactionTable({ page }: { page: TransactionPage }) {
  const { t } = useT();
  // Mirrors `Pager`'s own "is there more than one page" check just below -- a table that fits in one
  // page gets no page-count clause in its caption, matching `Pager` rendering nothing for the same
  // shape rather than announcing a "page 1 of 1" that carries no information.
  const paginated = page.total > page.limit;
  const caption = paginated
    ? t("activity.table.caption.paged", {
        shown: page.transactions.length,
        total: page.total,
        page: Math.floor(page.offset / page.limit) + 1,
        totalPages: Math.ceil(page.total / page.limit),
      })
    : t("activity.table.caption.single", { shown: page.transactions.length, total: page.total });
  return (
    <section className="panel">
      <ScrollRegion size="lg" label={t("activity.table.regionLabel")}>
        <div className="table-wrap">
          <table className="data-table">
            <TableCaption caption={caption} />
            <thead>
              <tr>
                <th scope="col">{t("common.date")}</th>
                <th scope="col">{t("common.action")}</th>
                <th scope="col">{t("common.symbol")}</th>
                <th scope="col" className="num">
                  {t("common.quantity")}
                </th>
                <th scope="col" className="num">
                  {t("common.price")}
                </th>
                <th scope="col" className="num">
                  {t("activity.table.amount")}
                </th>
                <th scope="col">{t("activity.table.account")}</th>
                <th scope="col">{t("common.source")}</th>
              </tr>
            </thead>
            <tbody>
              {page.transactions.map((txn) => (
                <tr key={txn.txn_id}>
                  <td>
                    {txn.trade_date}
                    {txn.settle_date && txn.settle_date !== txn.trade_date && (
                      <span className="muted"> → {txn.settle_date}</span>
                    )}
                  </td>
                  <td className={actionTone(txn.action)}>{actionLabel(txn.action)}</td>
                  <td>{txn.symbol ?? "—"}</td>
                  <td className="num">{txn.quantity ?? "—"}</td>
                  <td className="num">{txn.price === null ? "—" : formatMoney(txn.price)}</td>
                  <td className="num">{txn.amount === null ? "—" : formatMoney(txn.amount)}</td>
                  <td>{txn.account_id}</td>
                  <td className="muted">
                    {/* The provenance coordinate, rendered plainly: which import, which line of it.
                        `title` carries the full import id, which is too long for a cell but is what
                        someone actually needs when they go looking in the file. */}
                    <span title={t("activity.table.importTitle", { id: txn.import_id })}>
                      {txn.import_id.slice(0, 8)}:{txn.source_row}
                    </span>
                    {txn.raw_code && <span className="muted"> · {txn.raw_code}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </ScrollRegion>
    </section>
  );
}

function Pager({
  page,
  offset,
  onOffset,
}: {
  page: TransactionPage;
  offset: number;
  onOffset: (next: number) => void;
}) {
  const { t } = useT();
  const first = page.total === 0 ? 0 : offset + 1;
  const last = offset + page.transactions.length;
  if (page.total <= PAGE_SIZE) return null;

  return (
    <div className="panel pager">
      <button type="button" disabled={offset === 0} onClick={() => onOffset(Math.max(0, offset - PAGE_SIZE))}>
        {t("activity.pager.previous")}
      </button>
      <span>
        {t("activity.pager.range", {
          first: first.toLocaleString(),
          last: last.toLocaleString(),
          total: page.total.toLocaleString(),
        })}
      </span>
      <button type="button" disabled={!page.has_more} onClick={() => onOffset(offset + PAGE_SIZE)}>
        {t("activity.pager.next")}
      </button>
    </div>
  );
}

