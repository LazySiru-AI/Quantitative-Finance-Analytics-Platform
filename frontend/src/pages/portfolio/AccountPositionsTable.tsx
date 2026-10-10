/**
 * The positions table shared by the by-account panel (`ByAccountView.tsx`) and the by-tax-treatment
 * groups (`ByTaxTreatmentView.tsx`) -- same eleven columns, same priced/unpriced separator
 * convention, same filter bar and sortable headers as `ByInstrumentView`'s table, since a reader
 * should not have to learn two different table controls on one page.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import type { DecimalString } from "@/api/client";
import {
  compareMoneyDesc,
  formatMoney,
  formatSignedFractionPct,
  formatSignedMoney,
  moneyTone,
  warningKindLabel,
} from "@/api/portfolio";
import { ScrollRegion } from "@/components/ScrollPanel";
import SectorBadgeEditor from "@/components/SectorBadgeEditor";
import { FilterBar, SortHeader, sortRows, TableCaption, useTableSort } from "@/components/tableSort";
import { useT } from "@/i18n";
import type { WashSaleTrackerSymbol } from "@/api/washsales";

import { compareNullableMoneyAsc, compareNullableNumber, type AccountPositionRow } from "./aggregates";

export const ACCOUNT_POSITION_COLUMN_COUNT = 11;

type AccountRowSortKey =
  | "symbol"
  | "sector"
  | "quantity"
  | "costBasis"
  | "price"
  | "marketValue"
  | "unrealized"
  | "unrealizedPct"
  | "dayChange"
  | "dayChangePct"
  | "lots"
  | "deferredLoss";

const ACCOUNT_ROW_DEFAULT_DIRS: Record<AccountRowSortKey, "asc" | "desc"> = {
  symbol: "asc",
  sector: "asc",
  quantity: "desc",
  costBasis: "desc",
  price: "desc",
  marketValue: "desc",
  unrealized: "desc",
  unrealizedPct: "desc",
  dayChange: "desc",
  dayChangePct: "desc",
  lots: "desc",
  deferredLoss: "desc",
};

/**
 * One `AccountPositionRow` plus its (optional) wash-sale deferred-loss figure -- the By-tax-treatment
 * view's taxable group looks these up from `washSalesApi.tracker()` by symbol; every other caller of
 * `AccountPositionsTable` (the by-account panel, the retirement group) never supplies a
 * `washBySymbol` map, so these three fields are simply `null`/`false` there and the Deferred loss
 * column never renders.
 */
interface AccountRowWithWash extends AccountPositionRow {
  deferredLoss: DecimalString | null;
  washWindowOpen: boolean;
  washSafeOn: string | null;
}

const ACCOUNT_ROW_SORT_COMPARE: Record<AccountRowSortKey, (a: AccountRowWithWash, b: AccountRowWithWash) => number> = {
  symbol: (a, b) => a.symbol.localeCompare(b.symbol),
  sector: (a, b) => a.sector.localeCompare(b.sector) || a.symbol.localeCompare(b.symbol),
  quantity: (a, b) => Number(a.quantity) - Number(b.quantity),
  costBasis: (a, b) => compareMoneyDesc(b.costBasis, a.costBasis),
  price: (a, b) => compareNullableMoneyAsc(a.price, b.price),
  marketValue: (a, b) => compareNullableMoneyAsc(a.marketValue, b.marketValue),
  unrealized: (a, b) => compareNullableMoneyAsc(a.unrealized, b.unrealized),
  unrealizedPct: (a, b) => compareNullableNumber(a.unrealizedPct, b.unrealizedPct),
  dayChange: (a, b) => compareNullableMoneyAsc(a.dayChange, b.dayChange),
  dayChangePct: (a, b) => compareNullableNumber(a.dayChangePct, b.dayChangePct),
  lots: (a, b) => a.lotCount - b.lotCount,
  deferredLoss: (a, b) => compareNullableMoneyAsc(a.deferredLoss, b.deferredLoss),
};

export function AccountPositionsTable({
  rows,
  unpricedCaveat,
  label,
  vocabulary,
  onSectorChanged,
  washBySymbol,
}: {
  rows: AccountPositionRow[];
  unpricedCaveat: string;
  label: string;
  vocabulary: string[];
  onSectorChanged: () => void;
  /** Present only for the By-tax-treatment view's taxable group -- see `ByTaxTreatmentView.tsx`. Its
   *  presence, not its contents, is what decides whether the Deferred loss column renders at all;
   *  an empty map (nothing wash-flagged, or the tracker fetch failed) still renders the column, with
   *  every row reading "—". */
  washBySymbol?: Map<string, WashSaleTrackerSymbol> | undefined;
}) {
  const { t } = useT();
  const [query, setQuery] = useState("");
  const [sectorChoice, setSectorChoice] = useState("");
  const { sort, toggle } = useTableSort<AccountRowSortKey>("marketValue", ACCOUNT_ROW_DEFAULT_DIRS);
  const showDeferredLoss = washBySymbol !== undefined;
  const columnCount = ACCOUNT_POSITION_COLUMN_COUNT + (showDeferredLoss ? 1 : 0);

  const rowsWithWash: AccountRowWithWash[] = useMemo(
    () =>
      rows.map((r) => {
        const w = washBySymbol?.get(r.symbol);
        return {
          ...r,
          deferredLoss: w ? w.deferred_disallowed : null,
          washWindowOpen: w?.window_is_open ?? false,
          washSafeOn: w?.repurchase_safe_on ?? null,
        };
      }),
    [rows, washBySymbol],
  );

  const sectorChoices = useMemo(() => {
    const set = new Set(rowsWithWash.map((r) => r.sector));
    return Array.from(set)
      .sort((a, b) => a.localeCompare(b))
      .map((s) => ({ value: s, label: s }));
  }, [rowsWithWash]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rowsWithWash.filter((r) => {
      if (q && !r.symbol.toLowerCase().includes(q)) return false;
      if (sectorChoice && r.sector !== sectorChoice) return false;
      return true;
    });
  }, [rowsWithWash, query, sectorChoice]);

  const priced = useMemo(
    () => sortRows(filtered.filter((r) => r.marketValue !== null), sort, ACCOUNT_ROW_SORT_COMPARE),
    [filtered, sort],
  );
  const unpriced = useMemo(
    () => filtered.filter((r) => r.marketValue === null).slice().sort((a, b) => a.symbol.localeCompare(b.symbol)),
    [filtered],
  );

  return (
    <>
      <FilterBar
        query={query}
        onQueryChange={setQuery}
        queryPlaceholder={t("portfolio.filter.symbolPlaceholder")}
        choices={sectorChoices}
        choice={sectorChoice}
        onChoiceChange={setSectorChoice}
        choiceAllLabel={t("portfolio.filter.sectorAll")}
        choiceLabel={t("portfolio.filter.sectorLabel")}
        shown={filtered.length}
        total={rows.length}
      />
      <ScrollRegion size="md" label={label}>
        <div className="table-wrap">
        <table className="data-table account-position-table">
          <TableCaption
            caption={t("portfolio.table.caption.scoped", { label, count: filtered.length })}
          />
          <thead>
            <tr>
              <SortHeader
                label={t("common.symbol")}
                sortKey="symbol"
                sort={sort}
                onSort={toggle}
                title={t("portfolio.sort.ariaLabel", { column: t("common.symbol") })}
              />
              <SortHeader
                label={t("portfolio.header.sector")}
                sortKey="sector"
                sort={sort}
                onSort={toggle}
                title={t("portfolio.sort.ariaLabel", { column: t("portfolio.header.sector") })}
              />
              <SortHeader
                label={t("common.quantity")}
                sortKey="quantity"
                sort={sort}
                onSort={toggle}
                numeric
                title={t("portfolio.sort.ariaLabel", { column: t("common.quantity") })}
              />
              <SortHeader
                label={t("portfolio.tile.costBasis")}
                sortKey="costBasis"
                sort={sort}
                onSort={toggle}
                numeric
                title={t("portfolio.sort.ariaLabel", { column: t("portfolio.tile.costBasis") })}
              />
              <SortHeader
                label={t("common.price")}
                sortKey="price"
                sort={sort}
                onSort={toggle}
                numeric
                title={t("portfolio.sort.ariaLabel", { column: t("common.price") })}
              />
              <SortHeader
                label={t("portfolio.tile.marketValue")}
                sortKey="marketValue"
                sort={sort}
                onSort={toggle}
                numeric
                title={t("portfolio.sort.ariaLabel", { column: t("portfolio.tile.marketValue") })}
              />
              <SortHeader
                label={t("portfolio.tile.unrealized")}
                sortKey="unrealized"
                sort={sort}
                onSort={toggle}
                numeric
                title={t("portfolio.sort.ariaLabel", { column: t("portfolio.tile.unrealized") })}
              />
              <SortHeader
                label={t("portfolio.header.unrealizedPct")}
                sortKey="unrealizedPct"
                sort={sort}
                onSort={toggle}
                numeric
                title={t("portfolio.sort.ariaLabel", { column: t("portfolio.header.unrealizedPct") })}
              />
              <SortHeader
                label={t("portfolio.header.dayChange")}
                sortKey="dayChange"
                sort={sort}
                onSort={toggle}
                numeric
                title={t("portfolio.sort.ariaLabel", { column: t("portfolio.header.dayChange") })}
              />
              <SortHeader
                label={t("portfolio.header.dayChangePct")}
                sortKey="dayChangePct"
                sort={sort}
                onSort={toggle}
                numeric
                title={t("portfolio.sort.ariaLabel", { column: t("portfolio.header.dayChangePct") })}
              />
              <SortHeader
                label={t("portfolio.header.lots")}
                sortKey="lots"
                sort={sort}
                onSort={toggle}
                numeric
                title={t("portfolio.sort.ariaLabel", { column: t("portfolio.header.lots") })}
              />
              {showDeferredLoss && (
                <SortHeader
                  label={t("portfolio.header.deferredLoss")}
                  sortKey="deferredLoss"
                  sort={sort}
                  onSort={toggle}
                  numeric
                  title={t("portfolio.sort.ariaLabel", { column: t("portfolio.header.deferredLoss") })}
                />
              )}
            </tr>
          </thead>
          <tbody>
            {priced.map((row) => (
              <AccountPositionRowView
                key={row.instrumentId}
                row={row}
                vocabulary={vocabulary}
                onSectorChanged={onSectorChanged}
                showDeferredLoss={showDeferredLoss}
              />
            ))}
            {unpriced.length > 0 && (
              <tr className="position-group-separator">
                <td colSpan={columnCount}>{unpricedCaveat}</td>
              </tr>
            )}
            {unpriced.map((row) => (
              <AccountPositionRowView
                key={row.instrumentId}
                row={row}
                vocabulary={vocabulary}
                onSectorChanged={onSectorChanged}
                showDeferredLoss={showDeferredLoss}
              />
            ))}
          </tbody>
        </table>
        </div>
      </ScrollRegion>
    </>
  );
}

function AccountPositionRowView({
  row,
  vocabulary,
  onSectorChanged,
  showDeferredLoss,
}: {
  row: AccountRowWithWash;
  vocabulary: string[];
  onSectorChanged: () => void;
  showDeferredLoss: boolean;
}) {
  const { t } = useT();
  const tone = row.unrealized === null ? "" : moneyTone(row.unrealized);
  const dayTone = row.dayChange === null ? "" : moneyTone(row.dayChange);
  return (
    <tr>
      <td className="position-symbol-cell">
        <Link className="position-symbol" to={`/symbol/${encodeURIComponent(row.symbol)}`}>
          {row.symbol}
        </Link>
        {row.basisUncertain && (
          <>
            <span className="badge basis-uncertain" title={warningKindLabel("missing_basis")}>
              {t("portfolio.badge.uncertainBasis")}
            </span>
            {/* Same treatment as `ByInstrumentView`'s own basis-uncertain badge -- a real `Link` to
                the Tax page's Disposals tab, reusing the badge's own warn styling. */}
            <Link
              className="badge basis-uncertain"
              to="/tax?tab=disposals"
              title={t("portfolio.badge.uncertainBasisLinkTitle")}
            >
              {t("portfolio.badge.uncertainBasisLink")}
            </Link>
          </>
        )}
        {row.feesUnknown && (
          <span className="badge fees-unknown" title={warningKindLabel("fees_unknown")}>
            {t("portfolio.badge.feesUnknown")}
          </span>
        )}
      </td>
      <td>
        <SectorBadgeEditor
          symbol={row.symbol}
          sector={row.sector}
          vocabulary={vocabulary}
          onChanged={onSectorChanged}
        />
      </td>
      <td className="num">{row.quantity}</td>
      <td className="num">{formatMoney(row.costBasis)}</td>
      <td className="num">
        {row.price === null ? (
          "—"
        ) : (
          <>
            <div>{formatMoney(row.price)}</div>
            {row.priceAsOf && (
              <div className="position-price-asof">
                {t("portfolio.positions.asOf", { date: row.priceAsOf })}
              </div>
            )}
          </>
        )}
      </td>
      <td className="num">{row.marketValue === null ? "—" : formatMoney(row.marketValue)}</td>
      <td className="num">
        {row.unrealized === null ? (
          "—"
        ) : (
          <span className={`position-unrealized-value ${tone}`}>
            {formatSignedMoney(row.unrealized)}
          </span>
        )}
      </td>
      <td className="num">{formatSignedFractionPct(row.unrealizedPct)}</td>
      <td className="num">
        {row.dayChange === null ? (
          "—"
        ) : (
          <span className={`position-unrealized-value ${dayTone}`}>{formatSignedMoney(row.dayChange)}</span>
        )}
      </td>
      <td className="num">{formatSignedFractionPct(row.dayChangePct)}</td>
      <td className="num">{row.lotCount}</td>
      {showDeferredLoss && (
        <td className="num">
          {row.deferredLoss === null ? (
            "—"
          ) : (
            <span
              title={
                row.washWindowOpen && row.washSafeOn
                  ? t("portfolio.washColumn.windowOpenTitle", { date: row.washSafeOn })
                  : undefined
              }
            >
              {formatMoney(row.deferredLoss)}
            </span>
          )}
        </td>
      )}
    </tr>
  );
}

export default AccountPositionsTable;
