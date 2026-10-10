/**
 * "By instrument": the default positions view, holdings rolled up across every account. See
 * `Portfolio.tsx`'s module docstring for why this stays the default and what the other two views
 * (`ByAccountView`, `ByTaxTreatmentView`) add on top of it rather than replace.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  compareMoneyDesc,
  formatMoney,
  formatSignedFractionPct,
  formatSignedMoney,
  formatWeightPct,
  moneyTone,
  warningKindLabel,
  type AccountPosition,
  type PortfolioReport,
  type Position,
} from "@/api/portfolio";
import { FilterBar, SortHeader, sortRows, TableCaption, useTableSort } from "@/components/tableSort";
import { useT } from "@/i18n";
import SectorBadgeEditor from "@/components/SectorBadgeEditor";
import { ScrollRegion } from "@/components/ScrollPanel";

import { compareNullableMoneyAsc, compareNullableNumber } from "./aggregates";

const POSITION_COLUMN_COUNT = 12;

type PositionSortKey =
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
  | "weight";

const POSITION_DEFAULT_DIRS: Record<PositionSortKey, "asc" | "desc"> = {
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
  weight: "desc",
};

const POSITION_SORT_COMPARE: Record<PositionSortKey, (a: Position, b: Position) => number> = {
  symbol: (a, b) => a.symbol.localeCompare(b.symbol),
  sector: (a, b) => a.sector.localeCompare(b.sector) || a.symbol.localeCompare(b.symbol),
  quantity: (a, b) => Number(a.quantity) - Number(b.quantity),
  costBasis: (a, b) => compareMoneyDesc(b.cost_basis, a.cost_basis),
  price: (a, b) => compareNullableMoneyAsc(a.price, b.price),
  marketValue: (a, b) => compareNullableMoneyAsc(a.market_value, b.market_value),
  unrealized: (a, b) => compareNullableMoneyAsc(a.unrealized, b.unrealized),
  unrealizedPct: (a, b) => compareNullableNumber(a.unrealized_pct, b.unrealized_pct),
  dayChange: (a, b) => compareNullableMoneyAsc(a.day_change, b.day_change),
  dayChangePct: (a, b) => compareNullableNumber(a.day_change_pct, b.day_change_pct),
  weight: (a, b) => compareNullableNumber(a.weight_pct, b.weight_pct),
};

export function ByInstrumentView({
  report,
  vocabulary,
  onSectorChanged,
}: {
  report: PortfolioReport;
  vocabulary: string[];
  onSectorChanged: () => void;
}) {
  const { t } = useT();
  const [query, setQuery] = useState("");
  const [sectorChoice, setSectorChoice] = useState("");
  const { sort, toggle } = useTableSort<PositionSortKey>("marketValue", POSITION_DEFAULT_DIRS);

  const sectorChoices = useMemo(() => {
    const set = new Set(report.positions.map((p) => p.sector));
    return Array.from(set)
      .sort((a, b) => a.localeCompare(b))
      .map((s) => ({ value: s, label: s }));
  }, [report.positions]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return report.positions.filter((p) => {
      if (q && !p.symbol.toLowerCase().includes(q)) return false;
      if (sectorChoice && p.sector !== sectorChoice) return false;
      return true;
    });
  }, [report.positions, query, sectorChoice]);

  const priced = useMemo(
    () => sortRows(filtered.filter((p) => p.market_value !== null), sort, POSITION_SORT_COMPARE),
    [filtered, sort],
  );
  const unpriced = useMemo(
    () => filtered.filter((p) => p.market_value === null).slice().sort((a, b) => a.symbol.localeCompare(b.symbol)),
    [filtered],
  );

  if (report.positions.length === 0) {
    return (
      <div className="panel">
        <h2>{t("portfolio.positions.title")}</h2>
        <div className="placeholder">{t("portfolio.positions.none")}</div>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>{t("portfolio.positions.title")}</h2>
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
        total={report.positions.length}
      />
      <ScrollRegion
        size="md"
        label={t("portfolio.filter.note", { shown: filtered.length, total: report.positions.length })}
      >
        <div className="table-wrap">
        <table className="data-table position-table">
          <TableCaption
            caption={t("portfolio.table.caption.byInstrument", { count: filtered.length })}
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
                label={t("portfolio.header.quantityStLt")}
                sortKey="quantity"
                sort={sort}
                onSort={toggle}
                numeric
                title={t("portfolio.sort.ariaLabel", { column: t("portfolio.header.quantityStLt") })}
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
                label={t("portfolio.positions.header.weight")}
                sortKey="weight"
                sort={sort}
                onSort={toggle}
                numeric
                title={t("portfolio.positions.header.weightNote")}
              />
              <th scope="col">
                <span className="visually-hidden">{t("portfolio.header.accountBreakdown")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {priced.map((p) => (
              <PositionRow
                key={p.instrument_id}
                position={p}
                vocabulary={vocabulary}
                onSectorChanged={onSectorChanged}
              />
            ))}
            {unpriced.length > 0 && (
              <tr className="position-group-separator">
                <td colSpan={POSITION_COLUMN_COUNT}>{t("portfolio.positions.unpricedSeparator")}</td>
              </tr>
            )}
            {unpriced.map((p) => (
              <PositionRow
                key={p.instrument_id}
                position={p}
                vocabulary={vocabulary}
                onSectorChanged={onSectorChanged}
              />
            ))}
          </tbody>
        </table>
        </div>
      </ScrollRegion>
    </div>
  );
}

function PositionRow({
  position: p,
  vocabulary,
  onSectorChanged,
}: {
  position: Position;
  vocabulary: string[];
  onSectorChanged: () => void;
}) {
  const { t } = useT();
  const [expanded, setExpanded] = useState(false);
  const detailId = `position-accounts-${p.instrument_id}`;
  const tone = p.unrealized === null ? "" : moneyTone(p.unrealized);
  const dayTone = p.day_change === null ? "" : moneyTone(p.day_change);

  return (
    <>
      <tr>
        <td className="position-symbol-cell">
          <Link className="position-symbol" to={`/symbol/${encodeURIComponent(p.symbol)}`}>
            {p.symbol}
          </Link>
          {p.basis_uncertain && (
            <>
              <span
                className="badge basis-uncertain"
                title={warningKindLabel("missing_basis")}
              >
                {t("portfolio.badge.uncertainBasis")}
              </span>
              {/* Same badge class as the flag above -- same warn colour, no new CSS -- but this one
                  is a real `Link` to the Tax page's Disposals tab, where the basis gap this flag is
                  warning about actually shows up as a dollar figure. */}
              <Link
                className="badge basis-uncertain"
                to="/tax?tab=disposals"
                title={t("portfolio.badge.uncertainBasisLinkTitle")}
              >
                {t("portfolio.badge.uncertainBasisLink")}
              </Link>
            </>
          )}
          {p.fees_unknown && (
            <span className="badge fees-unknown" title={warningKindLabel("fees_unknown")}>
              {t("portfolio.badge.feesUnknown")}
            </span>
          )}
        </td>
        <td>
          <SectorBadgeEditor
            symbol={p.symbol}
            sector={p.sector}
            vocabulary={vocabulary}
            onChanged={onSectorChanged}
          />
        </td>
        <td className="num">
          <div>{p.quantity}</div>
          <div className="position-term-split">
            {p.short_term_quantity} ST / {p.long_term_quantity} LT
          </div>
        </td>
        <td className="num">{formatMoney(p.cost_basis)}</td>
        <td className="num">
          {p.price === null ? (
            "—"
          ) : (
            <>
              <div>{formatMoney(p.price)}</div>
              {p.price_as_of && (
                <div className="position-price-asof">
                  {t("portfolio.positions.asOf", { date: p.price_as_of })}
                </div>
              )}
            </>
          )}
        </td>
        <td className="num">{p.market_value === null ? "—" : formatMoney(p.market_value)}</td>
        <td className="num">
          {p.unrealized === null ? (
            "—"
          ) : (
            <>
              <div className={`position-unrealized-value ${tone}`}>{formatSignedMoney(p.unrealized)}</div>
              {p.basis_uncertain && (
                <div className="entry-tag" title={t("portfolio.badge.boundNotExactTitle")}>
                  {t("portfolio.badge.boundNotExact")}
                </div>
              )}
            </>
          )}
        </td>
        <td className="num">{formatSignedFractionPct(p.unrealized_pct)}</td>
        <td className="num">
          {p.day_change === null ? (
            "—"
          ) : (
            <span className={`position-unrealized-value ${dayTone}`}>{formatSignedMoney(p.day_change)}</span>
          )}
        </td>
        <td className="num">{formatSignedFractionPct(p.day_change_pct)}</td>
        <td className="num">{formatWeightPct(p.weight_pct)}</td>
        <td>
          <button
            type="button"
            className="position-expand-btn"
            aria-expanded={expanded}
            aria-controls={detailId}
            aria-label={t(
              expanded ? "portfolio.positions.hideBreakdown" : "portfolio.positions.showBreakdown",
              { symbol: p.symbol },
            )}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded
              ? t("portfolio.positions.hideLabel")
              : t(
                  p.accounts.length === 1
                    ? "portfolio.positions.acctCount_one"
                    : "portfolio.positions.acctCount_other",
                  { count: p.accounts.length },
                )}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="position-detail-row">
          <td colSpan={POSITION_COLUMN_COUNT}>
            <AccountsBreakdown id={detailId} symbol={p.symbol} accounts={p.accounts} />
          </td>
        </tr>
      )}
    </>
  );
}

function AccountsBreakdown({
  id,
  symbol,
  accounts,
}: {
  id: string;
  symbol: string;
  accounts: AccountPosition[];
}) {
  const { t } = useT();
  return (
    <table className="position-detail-table" id={id}>
      <caption className="visually-hidden">
        {t("portfolio.accountsBreakdown.caption", { symbol })}
      </caption>
      <thead>
        <tr>
          <th scope="col">{t("portfolio.header.account")}</th>
          <th scope="col">{t("portfolio.header.broker")}</th>
          <th scope="col" className="num">
            {t("common.quantity")}
          </th>
          <th scope="col" className="num">
            {t("portfolio.tile.costBasis")}
          </th>
          <th scope="col" className="num">
            {t("portfolio.header.lots")}
          </th>
          <th scope="col">{t("portfolio.header.flags")}</th>
        </tr>
      </thead>
      <tbody>
        {accounts.map((a) => (
          <tr key={a.account_id}>
            <td>{a.account_label}</td>
            <td>{a.broker}</td>
            <td className="num">{a.quantity}</td>
            <td className="num">{formatMoney(a.cost_basis)}</td>
            <td className="num">{a.lot_count}</td>
            <td>
              {a.basis_uncertain && (
                <span className="badge basis-uncertain">{t("portfolio.badge.uncertainBasis")}</span>
              )}
              {a.fees_unknown && (
                <span className="badge fees-unknown">{t("portfolio.badge.feesUnknown")}</span>
              )}
              {!a.basis_uncertain && !a.fees_unknown && "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default ByInstrumentView;
