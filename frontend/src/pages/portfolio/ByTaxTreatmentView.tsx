/**
 * "By tax treatment": the same positions regrouped into exactly two buckets, taxable and retirement
 * (Roth + traditional IRA collapsed together, nothing finer) -- the one question neither of the
 * other two views answers on its own: how much of the book will never be taxed on the way out. See
 * `Portfolio.tsx`'s module docstring for why nothing finer than two buckets, and `aggregates.ts`'s
 * `buildTaxGroupAggregates` for how the join against `cash_by_account.tax_treatment` works.
 */
import { useEffect, useMemo, useState } from "react";

import type { DecimalString } from "@/api/client";
import { sumMoney, type PortfolioReport } from "@/api/portfolio";
import AllocationPie, { type AllocationMode } from "@/components/AllocationPie";
import { FolderTabs } from "@/components/FolderTabs";
import InfoNote from "@/components/InfoNote";
import { Trans, useT } from "@/i18n";
import { washSalesApi, type WashSaleTrackerSymbol } from "@/api/washsales";

import {
  buildAllocationSlices,
  buildScopedPositionRows,
  buildTaxGroupAggregates,
  taxGroupFor,
  type TaxGroupAggregate,
  type TaxGroupKey,
} from "./aggregates";
import { AccountPositionsTable } from "./AccountPositionsTable";
import { MoneyTile } from "./tiles";

/** The tax-treatment view's scope control: every account, or one `TaxGroupKey`'s worth. Distinct
 *  from `TaxGroupKey` itself only by the addition of `"all"` -- kept as its own type (rather than
 *  `TaxGroupKey | "all"` inlined at every call site) because `Portfolio.tsx`'s `useUrlState` call
 *  needs one importable name for both the type and its valid-values list. */
export type TaxScope = "all" | TaxGroupKey;
export const TAX_SCOPES: readonly TaxScope[] = ["all", "taxable", "retirement"];

/** `"all"` narrows to no particular account -- every other value is a real `account_id` from
 *  `report.accounts`. Kept as page-local `useState` (not URL state): the task this control exists
 *  for is "which slice of the book does the pie show right now", and unlike the primary `scope` tab
 *  a stale or hand-typed account id in a bookmark would need its own validity check against
 *  whichever accounts belong to the CURRENT scope, which is exactly the kind of derived-from-two-
 *  things state `useUrlState`'s `valid` list is not shaped for. */
const ALL_ACCOUNTS_ID = "all";

/** Fetch status for the wash-sale tracker this view loads once and shares across both groups -- own
 *  state, independent of `usePortfolio()`'s report fetch. `bySymbol` stays an empty `Map` (never
 *  `undefined`) through `loading` and `error` alike, so the taxable group's Deferred loss column
 *  always has a map to look up against -- it renders "—" for every row either way, and only the
 *  one-line caveat depends on `status`. */
interface WashFetchState {
  status: "loading" | "loaded" | "error";
  bySymbol: Map<string, WashSaleTrackerSymbol>;
}

export function ByTaxTreatmentView({
  report,
  vocabulary,
  onSectorChanged,
  scope,
  onScopeChange,
}: {
  report: PortfolioReport;
  vocabulary: string[];
  onSectorChanged: () => void;
  /** The scope control's current tab -- owned by `Portfolio.tsx`'s `useUrlState("scope", ...)` call
   *  so a deep link and Back both land on the same slice of the book. */
  scope: TaxScope;
  onScopeChange: (scope: TaxScope) => void;
}) {
  const { t } = useT();
  const { groups, unknownTreatmentAccountIds } = useMemo(
    () => buildTaxGroupAggregates(report),
    [report],
  );
  const unknownSingular = unknownTreatmentAccountIds.length === 1;

  // Narrows the scope pie to one account inside the current `scope` tab -- reset to "all accounts"
  // whenever the tab itself changes, since an account that belonged to the previous tab's group may
  // not belong to the new one (see `ALL_ACCOUNTS_ID`'s own docstring for why this is local state
  // rather than a second URL key).
  const [scopeAccountId, setScopeAccountId] = useState<string>(ALL_ACCOUNTS_ID);
  const [scopeAllocMode, setScopeAllocMode] = useState<AllocationMode>("ticker");

  const scopeAccountOptions = useMemo(
    () =>
      report.accounts.filter(
        (a) => a.status === "open" && (scope === "all" || taxGroupFor(a.tax_treatment) === scope),
      ),
    [report.accounts, scope],
  );

  const { rows: scopeRows, cashTotal: scopeCashTotal } = useMemo(
    () =>
      buildScopedPositionRows(report, {
        ...(scope !== "all" ? { treatment: scope } : {}),
        ...(scopeAccountId !== ALL_ACCOUNTS_ID ? { accountId: scopeAccountId } : {}),
      }),
    [report, scope, scopeAccountId],
  );
  const scopeSlices = useMemo(
    () => buildAllocationSlices(scopeRows, scopeCashTotal, scopeAllocMode),
    [scopeRows, scopeCashTotal, scopeAllocMode],
  );
  const scopeUnpricedCount = scopeRows.filter((r) => r.marketValue === null).length;

  const [wash, setWash] = useState<WashFetchState>({ status: "loading", bySymbol: new Map() });
  useEffect(() => {
    const controller = new AbortController();
    washSalesApi
      .tracker(controller.signal)
      .then((tracker) => {
        setWash({ status: "loaded", bySymbol: new Map(tracker.symbols.map((s) => [s.symbol, s])) });
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setWash({ status: "error", bySymbol: new Map() });
      });
    return () => {
      controller.abort();
    };
  }, []);

  return (
    <div className="account-view">
      <div className="tax-groups-note">
        <InfoNote summary={t("portfolio.taxTreatment.summary")}>
          <p>{t("portfolio.taxTreatment.note")}</p>
        </InfoNote>
      </div>
      {unknownTreatmentAccountIds.length > 0 && (
        <div className="panel callout callout-warn">
          <Trans
            k={
              unknownSingular
                ? "portfolio.taxTreatment.unknownAccounts_one"
                : "portfolio.taxTreatment.unknownAccounts_other"
            }
            values={{
              countLabel: (
                <strong>
                  {t(
                    unknownSingular ? "portfolio.count.account_one" : "portfolio.count.account_other",
                    { count: unknownTreatmentAccountIds.length },
                  )}
                </strong>
              ),
              list: unknownTreatmentAccountIds.join(", "),
            }}
          />
        </div>
      )}

      <section className="panel account-picker-panel">
        <FolderTabs
          size="sm"
          label={t("portfolio.taxTreatment.scope.ariaLabel")}
          active={scope}
          onChange={(id) => {
            onScopeChange(id as TaxScope);
            // The previously-selected account may not belong to the newly-chosen group -- see
            // `ALL_ACCOUNTS_ID`'s own docstring for why this is reset here rather than validated.
            setScopeAccountId(ALL_ACCOUNTS_ID);
          }}
          items={[
            { id: "all", label: t("portfolio.taxTreatment.scope.all") },
            { id: "taxable", label: t("portfolio.taxGroup.taxable") },
            { id: "retirement", label: t("portfolio.taxGroup.retirement") },
          ]}
        />
        {scopeAccountOptions.length > 0 && (
          <>
            <label className="account-picker-label" htmlFor="tax-scope-account-select">
              {t("portfolio.accountPicker.label")}
            </label>
            <select
              id="tax-scope-account-select"
              className="account-picker-select"
              value={scopeAccountId}
              onChange={(e) => setScopeAccountId(e.target.value)}
            >
              <option value={ALL_ACCOUNTS_ID}>{t("portfolio.taxTreatment.scope.allAccounts")}</option>
              {scopeAccountOptions.map((a) => (
                <option key={a.account_id} value={a.account_id}>
                  {a.label}
                </option>
              ))}
            </select>
          </>
        )}
      </section>

      <div
        className="alloc-section"
        aria-label={t(scopeAllocMode === "ticker" ? "portfolio.alloc.byTicker" : "portfolio.alloc.bySector")}
      >
        <AllocationPie
          slices={scopeSlices}
          mode={scopeAllocMode}
          onModeChange={setScopeAllocMode}
          title={t("portfolio.alloc.title")}
          {...(scopeUnpricedCount > 0
            ? {
                footnote: t(
                  scopeUnpricedCount === 1 ? "portfolio.alloc.unpricedNote_one" : "portfolio.alloc.unpricedNote_other",
                  { count: scopeUnpricedCount },
                ),
              }
            : {})}
        />
      </div>

      {groups.map((group) => (
        <TaxGroupSection
          key={group.key}
          group={group}
          vocabulary={vocabulary}
          onSectorChanged={onSectorChanged}
          washBySymbol={group.key === "taxable" ? wash.bySymbol : undefined}
          washUnavailable={wash.status === "error"}
        />
      ))}
    </div>
  );
}

function TaxGroupSection({
  group,
  vocabulary,
  onSectorChanged,
  washBySymbol,
  washUnavailable,
}: {
  group: TaxGroupAggregate;
  vocabulary: string[];
  onSectorChanged: () => void;
  /** Present only for the taxable group -- see `ByTaxTreatmentView`. */
  washBySymbol?: Map<string, WashSaleTrackerSymbol> | undefined;
  washUnavailable: boolean;
}) {
  const { t } = useT();
  const positionCount = group.priced.length + group.unpriced.length;
  const cashPartial = group.cashExcludedCount > 0;
  const groupLabel = t(group.key === "taxable" ? "portfolio.taxGroup.taxable" : "portfolio.taxGroup.retirement");
  const isTaxable = group.key === "taxable";

  // Σ `deferred_disallowed` over this group's OWN symbols -- not every symbol the tracker knows
  // about, since a symbol wash-flagged only in a retirement account (or one this taxable group
  // never held) has no business in a taxable-group total. `null` (never a fabricated zero) whenever
  // the tracker fetch failed; a real, honest zero (`sumMoney([])`) whenever it loaded but none of
  // this group's symbols carry a deferred-loss entry.
  const deferredLossTotal = useMemo(() => {
    if (!isTaxable || !washBySymbol || washUnavailable) return null;
    const amounts = [...group.priced, ...group.unpriced]
      .map((r) => washBySymbol.get(r.symbol)?.deferred_disallowed)
      .filter((v): v is DecimalString => v !== undefined);
    return sumMoney(amounts);
  }, [isTaxable, washBySymbol, washUnavailable, group.priced, group.unpriced]);

  return (
    <section className="panel account-section">
      <div className="account-section-head">
        <div className="account-section-heading">
          <h2 className="account-section-title">{groupLabel}</h2>
          <span className="muted account-broker">
            {t(
              group.accountCount === 1 ? "portfolio.count.account_one" : "portfolio.count.account_other",
              { count: group.accountCount },
            )}
          </span>
        </div>
      </div>

      <div className="tile-grid account-tile-grid">
        <MoneyTile
          label={t("portfolio.tile.costBasis")}
          value={group.costBasisTotal}
          hint={t(
            positionCount === 1 ? "portfolio.count.position_one" : "portfolio.count.position_other",
            { count: positionCount },
          )}
        />
        <MoneyTile
          label={t(group.partial ? "portfolio.tile.marketValuePartial" : "portfolio.tile.marketValue")}
          value={group.marketValueTotal}
          variant={group.partial ? "danger" : undefined}
          hint={
            group.partial
              ? t("portfolio.tile.pricedOfHint", { priced: group.priced.length, total: positionCount })
              : group.marketValueTotal === null
                ? undefined
                : t("portfolio.tile.pricedHint", { count: group.priced.length })
          }
        />
        <MoneyTile
          label={t(group.partial ? "portfolio.tile.unrealizedPartial" : "portfolio.tile.unrealized")}
          value={group.unrealizedTotal}
          variant={group.partial ? "danger" : undefined}
          signed={group.unrealizedTotal !== null}
        />
        <MoneyTile
          label={cashPartial ? t("portfolio.tile.cashPartial") : t("common.cash")}
          value={group.cashTotal}
          variant={cashPartial ? "danger" : undefined}
          hint={
            cashPartial
              ? t("portfolio.tile.accountsOfHint", {
                  n: group.accountCount - group.cashExcludedCount,
                  total: group.accountCount,
                })
              : group.accountCount > 0
                ? t(
                    group.accountCount === 1 ? "portfolio.count.account_one" : "portfolio.count.account_other",
                    { count: group.accountCount },
                  )
                : undefined
          }
        />
        {isTaxable && (
          <MoneyTile
            label={t("portfolio.tile.deferredLoss")}
            value={deferredLossTotal}
            variant={washUnavailable ? "danger" : undefined}
            hint={washUnavailable ? t("portfolio.washCaveat.unavailable") : t("portfolio.tile.deferredLoss.hint")}
          />
        )}
      </div>

      {/* Deferred (`deferred_disallowed`) and permanently-disallowed wash-sale loss must never be
          summed into one figure -- see `@/api/washsales`'s module docstring. This tile and column
          render `deferred_disallowed` alone; the caveat says so on screen rather than only in a code
          comment. */}
      {isTaxable ? (
        <InfoNote tone="quiet" summary={t("portfolio.washCaveat.neverSummedSummary")}>
          <p>{t("portfolio.washCaveat.neverSummed.detail")}</p>
        </InfoNote>
      ) : (
        <InfoNote tone="quiet" summary={t("portfolio.washCaveat.retirementNotDeductible")} />
      )}

      {positionCount === 0 ? (
        <div className="placeholder">{t("portfolio.taxGroup.empty")}</div>
      ) : (
        <AccountPositionsTable
          rows={[...group.priced, ...group.unpriced]}
          unpricedCaveat={t("portfolio.positions.unpricedSeparatorGroup")}
          label={`${groupLabel} — ${t("portfolio.positions.title")}`}
          vocabulary={vocabulary}
          onSectorChanged={onSectorChanged}
          washBySymbol={isTaxable ? washBySymbol : undefined}
        />
      )}
    </section>
  );
}

export default ByTaxTreatmentView;
