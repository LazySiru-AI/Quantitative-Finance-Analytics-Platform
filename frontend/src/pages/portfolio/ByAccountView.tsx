/**
 * "By account": which account is this instrument actually sitting in, and can I trust that
 * account's own numbers. See `Portfolio.tsx`'s module docstring for why this is an additional lens
 * on the by-instrument roll-up, never a replacement for it.
 *
 * **The account rail.** A `FolderTabs` row -- `All open`, then every OPEN account in
 * `report.accounts` order, then a trailing `Closed (n)` tab when at least one account is closed --
 * replaces the old `<select>` picker so switching accounts, and seeing every account's position
 * count and market value at a glance, no longer costs a dropdown click. Selection lives in the URL
 * (`account`, owned by `Portfolio.tsx`'s `useUrlState` call and threaded down as `account`/
 * `onAccountChange` props) so Back and a deep link both land on the right panel. Past
 * `FOLDER_TAB_MAX` open accounts the rail stops being scannable (see that constant's own docstring)
 * and this falls back to the original `<select>`, still driven by the same URL state.
 *
 * **The Closed tab** does not reuse `AccountPanel` -- a closed account's holdings are stripped from
 * `report.positions` server-side (`excluded_closed_symbols`), so there are no position rows to show.
 * It instead lists the closed accounts themselves with their all-time realized result, the browsing
 * view `ClosedAccountsNote`'s one-line caveat (now folded into `CaveatStrip.tsx`) never offered.
 */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  formatMoney,
  formatSignedFractionPct,
  hasBalance,
  taxTreatmentLabel,
  type AccountSummary,
  type PortfolioReport,
} from "@/api/portfolio";
import AllocationPie, { type AllocationMode } from "@/components/AllocationPie";
import { FOLDER_TAB_MAX, FolderTabs, type FolderTabItem } from "@/components/FolderTabs";
import { TableCaption } from "@/components/tableSort";
import { useT } from "@/i18n";

import {
  accountTabBadge,
  buildAccountPanelData,
  buildAllocationSlices,
  buildOpenAccountsPanel,
  type SelectedPanelData,
} from "./aggregates";
import { AccountPositionsTable } from "./AccountPositionsTable";
import { MoneyTile, PanelCashTile } from "./tiles";

const ALL_OPEN_ID = "all-open";
const CLOSED_TAB_ID = "closed";

export function ByAccountView({
  report,
  vocabulary,
  onSectorChanged,
  account,
  onAccountChange,
}: {
  report: PortfolioReport;
  vocabulary: string[];
  onSectorChanged: () => void;
  /** The currently-selected account id, `"all-open"`, or `"closed"` -- owned by `Portfolio.tsx`'s
   *  `useUrlState("account", ...)` call. */
  account: string;
  onAccountChange: (id: string) => void;
}) {
  const { t } = useT();
  const navigate = useNavigate();
  const [allocMode, setAllocMode] = useState<AllocationMode>("ticker");

  // Listed in `report.accounts` order (label-sorted -- see that field's own docstring), filtered to
  // status -- never re-sorted here, so the rail reads left-to-right in the same order the report
  // itself gives.
  const openAccounts = useMemo(() => report.accounts.filter((a) => a.status === "open"), [report.accounts]);
  const openIds = useMemo(() => new Set(openAccounts.map((a) => a.account_id)), [openAccounts]);
  const closedAccounts = useMemo(() => report.accounts.filter((a) => a.status === "closed"), [report.accounts]);

  const tabItems = useMemo<FolderTabItem[]>(() => {
    const items: FolderTabItem[] = [{ id: ALL_OPEN_ID, label: t("portfolio.accountPicker.allOption") }];
    for (const a of openAccounts) {
      items.push({ id: a.account_id, label: a.label, badge: accountTabBadge(report, a) });
    }
    if (closedAccounts.length > 0) {
      items.push({
        id: CLOSED_TAB_ID,
        label: t("portfolio.accountPicker.closedTab", { count: closedAccounts.length }),
      });
    }
    return items;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report, openAccounts, closedAccounts]);

  if (report.accounts.length === 0) {
    return (
      <div className="panel">
        <div className="placeholder">{t("portfolio.positions.none")}</div>
      </div>
    );
  }

  const useTabs = openAccounts.length <= FOLDER_TAB_MAX;
  const showClosedPanel = account === CLOSED_TAB_ID && closedAccounts.length > 0;
  // `openAccounts.find`, not `report.accounts.find`: a selection can only ever be `"all-open"`,
  // `"closed"`, or an open account's id -- scoping the lookup to `openAccounts` is what actually
  // enforces that a stale id naming a closed account falls through to the combined panel rather
  // than rendering a closed account's now-impossible positions.
  const selectedSummary = !showClosedPanel ? openAccounts.find((a) => a.account_id === account) ?? null : null;
  const panel: SelectedPanelData = selectedSummary
    ? buildAccountPanelData(report, selectedSummary)
    : buildOpenAccountsPanel(report, openIds);

  return (
    <>
      <div className="panel account-picker-panel">
        {useTabs ? (
          <FolderTabs
            size="sm"
            label={t("portfolio.accountPicker.label")}
            active={account}
            onChange={(id) => onAccountChange(id)}
            items={tabItems}
          />
        ) : (
          <>
            <label className="account-picker-label" htmlFor="account-picker-select">
              {t("portfolio.accountPicker.label")}
            </label>
            <select
              id="account-picker-select"
              className="account-picker-select"
              value={selectedSummary ? selectedSummary.account_id : ALL_OPEN_ID}
              onChange={(e) => onAccountChange(e.target.value)}
            >
              <option value={ALL_OPEN_ID}>{t("portfolio.accountPicker.allOption")}</option>
              {openAccounts.map((a) => (
                <option key={a.account_id} value={a.account_id}>
                  {a.label}
                </option>
              ))}
            </select>
          </>
        )}
      </div>
      {showClosedPanel ? (
        <ClosedAccountsPanel closedAccounts={closedAccounts} />
      ) : (
        <AccountPanel
          panel={panel}
          allocMode={allocMode}
          onAllocModeChange={setAllocMode}
          onSelectTicker={(ticker) => navigate(`/symbol/${encodeURIComponent(ticker)}`)}
          vocabulary={vocabulary}
          onSectorChanged={onSectorChanged}
        />
      )}
    </>
  );
}

/** The selected account's (or combined "all open accounts'") figures, allocation pie and positions
 *  table -- ONE full-width panel. `.account-card` is kept as the outer class name even though the
 *  rail above it replaced the old checkbox grid this predates: every existing
 *  `.closest(".account-card")` scoped query in this page's tests keeps working unchanged. */
function AccountPanel({
  panel,
  allocMode,
  onAllocModeChange,
  onSelectTicker,
  vocabulary,
  onSectorChanged,
}: {
  panel: SelectedPanelData;
  allocMode: AllocationMode;
  onAllocModeChange: (mode: AllocationMode) => void;
  onSelectTicker: (ticker: string) => void;
  vocabulary: string[];
  onSectorChanged: () => void;
}) {
  const { t } = useT();
  const positionCount = panel.rows.length;
  const unpricedCount = panel.rows.filter((r) => r.marketValue === null).length;

  const cashTotalForAlloc =
    panel.cash.kind === "single"
      ? panel.cash.cash && hasBalance(panel.cash.cash.verdict)
        ? panel.cash.cash.balance
        : null
      : panel.cash.total;

  const slices = useMemo(
    () => buildAllocationSlices(panel.rows, cashTotalForAlloc, allocMode),
    [panel.rows, cashTotalForAlloc, allocMode],
  );

  return (
    <section className="panel account-card">
      <div className="account-card-head">
        <h2 className="account-card-title">{panel.label}</h2>
        <div className="muted account-card-meta">
          {panel.broker}
          {panel.taxTreatment !== null && (
            <span className={`badge account-tax-badge tax-${panel.taxTreatment}`}>
              {taxTreatmentLabel(panel.taxTreatment)}
            </span>
          )}
          {panel.isClosed && <span className="badge status-closed">{t("portfolio.status.closed")}</span>}
          {panel.warningCount > 0 && (
            <span className="badge basis-uncertain account-warning-count">
              {t(panel.warningCount === 1 ? "portfolio.warningCount_one" : "portfolio.warningCount_other", {
                count: panel.warningCount,
              })}
            </span>
          )}
        </div>
      </div>

      <div className="tile-grid account-card-figures">
        <MoneyTile
          label={t("portfolio.tile.costBasis")}
          value={panel.costBasisTotal}
          hint={t(
            positionCount === 1 ? "portfolio.count.position_one" : "portfolio.count.position_other",
            { count: positionCount },
          )}
        />
        <MoneyTile
          label={t(panel.partial ? "portfolio.tile.marketValuePartial" : "portfolio.tile.marketValue")}
          value={panel.marketValueTotal}
          variant={panel.partial ? "danger" : undefined}
          hint={
            panel.partial
              ? t("portfolio.tile.pricedOfHint", { priced: positionCount - unpricedCount, total: positionCount })
              : panel.marketValueTotal === null
                ? undefined
                : t("portfolio.tile.pricedHint", { count: positionCount - unpricedCount })
          }
        />
        <MoneyTile
          label={t(panel.partial ? "portfolio.tile.unrealizedPartial" : "portfolio.tile.unrealized")}
          value={panel.unrealizedTotal}
          variant={panel.partial ? "danger" : undefined}
          signed={panel.unrealizedTotal !== null}
        />
        <MoneyTile
          label={t("portfolio.tile.dayChange")}
          value={panel.dayChangeTotal}
          hint={panel.dayChangePct === null ? undefined : formatSignedFractionPct(panel.dayChangePct)}
          signed={panel.dayChangeTotal !== null}
        />
        <MoneyTile
          label={t("portfolio.tile.realized")}
          value={panel.realizedGain}
          hint={t("portfolio.tile.realized.hint")}
          signed
        />
        <MoneyTile
          label={t("portfolio.tile.accumulated")}
          value={panel.accumulated}
          hint={t("portfolio.tile.accumulated.hint")}
          emphasize
          signed={panel.accumulated !== null}
        />
        <PanelCashTile info={panel.cash} />
      </div>

      <div
        className="alloc-section"
        aria-label={t(allocMode === "ticker" ? "portfolio.alloc.byTicker" : "portfolio.alloc.bySector")}
      >
        <AllocationPie
          slices={slices}
          mode={allocMode}
          onModeChange={onAllocModeChange}
          title={t("portfolio.alloc.title")}
          onSelectTicker={onSelectTicker}
          {...(unpricedCount > 0
            ? {
                footnote: t(
                  unpricedCount === 1 ? "portfolio.alloc.unpricedNote_one" : "portfolio.alloc.unpricedNote_other",
                  { count: unpricedCount },
                ),
              }
            : {})}
        />
      </div>

      {positionCount === 0 ? (
        <div className="placeholder account-card-empty">{t("portfolio.accountCard.empty")}</div>
      ) : (
        <AccountPositionsTable
          rows={panel.rows}
          unpricedCaveat={t("portfolio.positions.unpricedSeparatorAccount")}
          label={`${panel.label} — ${t("portfolio.positions.title")}`}
          vocabulary={vocabulary}
          onSectorChanged={onSectorChanged}
        />
      )}
    </section>
  );
}

/** The Closed tab's content: no positions to show (they are excluded from `report.positions`
 *  server-side, see `excluded_closed_symbols`), so this lists the closed accounts themselves with
 *  their all-time realized result -- the one figure a closed account still genuinely has. */
function ClosedAccountsPanel({ closedAccounts }: { closedAccounts: AccountSummary[] }) {
  const { t } = useT();
  return (
    <section className="panel account-card">
      <div className="account-card-head">
        {/* Reuses the existing `PanelBoundary` label key -- same fact ("Closed accounts"), same
            translation, one key instead of two saying the same thing. */}
        <h2 className="account-card-title">{t("portfolio.panel.closedAccounts")}</h2>
      </div>
      {/* Not inside a `ScrollRegion` -- this list is bounded by the number of closed accounts, never
          the thousand-row kind `ScrollRegion` exists to cap -- so the scrollable-region role and
          keyboard tab stop (A11Y-03) are supplied directly rather than through that component. */}
      <div
        className="table-wrap"
        tabIndex={0}
        role="region"
        aria-label={t("portfolio.panel.closedAccounts")}
      >
        <table className="data-table">
          <TableCaption
            caption={t("portfolio.table.caption.closedAccounts", { count: closedAccounts.length })}
          />
          <thead>
            <tr>
              <th scope="col">{t("portfolio.header.account")}</th>
              <th scope="col">{t("portfolio.header.broker")}</th>
              <th scope="col" className="num">
                {t("portfolio.tile.realized")}
              </th>
            </tr>
          </thead>
          <tbody>
            {closedAccounts.map((a) => (
              <tr key={a.account_id}>
                <th scope="row">{a.label}</th>
                <td>{a.broker}</td>
                <td className="num">{formatMoney(a.realized_gain)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted account-card-empty">{t("portfolio.closed.note.more")}</p>
    </section>
  );
}

export default ByAccountView;
