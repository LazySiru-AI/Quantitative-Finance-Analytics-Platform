import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiRequestError, type StoreStatus } from "@/api/client";
import { portfolioApi } from "@/api/portfolio";
import InfoNote from "@/components/InfoNote";
import PanelBoundary from "@/components/PanelBoundary";
import Skeleton from "@/components/Skeleton";
import { FolderTabs } from "@/components/FolderTabs";
import { usePortfolio } from "@/hooks/usePortfolio";
import { useUrlState } from "@/hooks/useUrlState";
import { Trans, useT } from "@/i18n";

import { CaveatStrip } from "./portfolio/CaveatStrip";
import { CashByAccount } from "./portfolio/CashByAccount";
import { ByAccountView } from "./portfolio/ByAccountView";
import { ByInstrumentView } from "./portfolio/ByInstrumentView";
import { ByTaxTreatmentView, TAX_SCOPES, type TaxScope } from "./portfolio/ByTaxTreatmentView";
import { TotalsPanel } from "./portfolio/TotalsPanel";
import { WarningsSection } from "./portfolio/WarningsSection";
import { Stat } from "./portfolio/tiles";
import "./Portfolio.css";

type PositionsView = "instrument" | "account" | "tax";
const POSITIONS_VIEWS: readonly PositionsView[] = ["instrument", "account", "tax"];

const ALL_OPEN_ID = "all-open";
const CLOSED_TAB_ID = "closed";

/**
 * Portfolio page: holdings reconstructed from brokerage transaction history, plus the store-status
 * tiles that were the whole page before Phase 2 landed. Split into `pages/portfolio/` (this file
 * stays the orchestrator: it owns `usePortfolio()`, the two `useUrlState` view rails below, and the
 * `sectorVocabulary` fetch threaded down to every view) because the single-file version ran past
 * 2,900 lines.
 *
 * The one rule everything below is built around: `total_market_value`/`total_unrealized` are sums
 * over PRICED positions only (see `api/portfolio.ts`'s module docstring), so a non-empty
 * `unpriced_symbols` means those totals are a partial sum, not the whole book. Silently rendering
 * that partial sum as if it were complete is the one mistake this page must never make, so the
 * caveat (`portfolio/CaveatStrip.tsx`) is promoted above the tiles rather than left to a footnote --
 * the same layout choice `Tax.tsx` makes for its own uncertain-basis caveat.
 *
 * **By-instrument is the default, and stays the default.** The positions table (`ByInstrumentView`)
 * rolls every holding up across accounts because the rules that actually govern risk are
 * instrument-shaped, not account-shaped: wash-sale disallowance (IRC §1091) applies to the taxpayer
 * across every broker they hold, not per account -- a purchase inside a Roth can permanently kill a
 * loss realized in a taxable account at a different broker (Rev. Rul. 2008-5) -- and concentration is
 * a share of the whole book, not of one slice of it. "By account" (`ByAccountView`) is an additional
 * lens for questions the roll-up genuinely hides -- which account's numbers can be trusted (a basis
 * or fee gap is a property of the export, not the instrument), how much of an instrument's flag is
 * actually one account's problem, and which dollars sit in a Roth and will never be taxed on the way
 * out -- not a replacement for the instrument view, and nothing in its UI should read as license to
 * reason about wash sales or concentration one account at a time.
 *
 * **The two view rails.** A primary `FolderTabs` rail (By instrument / By account / By tax
 * treatment, `?view=`) sits above a secondary one (`ByAccountView`'s own account rail, `?account=`)
 * that only shows under "By account" -- `size="sm"` there reads as a hierarchy under the primary
 * rail's `size="md"`, not as a second unrelated control. Both live in the URL via `useUrlState` so
 * Back and a deep link both land on the exact view a reader left.
 *
 * "By tax treatment" (`ByTaxTreatmentView`) regroups the same positions into exactly two buckets --
 * taxable and retirement (Roth + traditional IRA collapsed together, nothing finer) -- for the one
 * question neither of the other two views answers on its own: how much of the book will never be
 * taxed on the way out. Same joins, same partial-total rules, same instrument counted once per group
 * it actually sits in -- not a fourth way to reason about wash sales or concentration.
 */
export default function Portfolio() {
  const { t } = useT();
  const [status, setStatus] = useState<StoreStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const { report, phase, message, refresh } = usePortfolio();

  const [view, setView] = useUrlState<PositionsView>("view", "instrument", { valid: POSITIONS_VIEWS });

  // The account rail's valid ids depend on the report (open accounts, plus a "closed" tab only when
  // at least one account is closed), so this is recomputed every render rather than fixed at module
  // scope -- but the hook itself is still called unconditionally on every render, per the rules of
  // hooks, with an empty list before the report has loaded (any `?account=` on a cold load simply
  // falls back to "all-open" until the report resolves).
  const accountValidIds = useMemo(() => {
    if (!report) return [ALL_OPEN_ID];
    const openIds = report.accounts.filter((a) => a.status === "open").map((a) => a.account_id);
    const hasClosed = report.accounts.some((a) => a.status === "closed");
    return [ALL_OPEN_ID, ...openIds, ...(hasClosed ? [CLOSED_TAB_ID] : [])];
  }, [report]);
  const [account, setAccount] = useUrlState<string>("account", ALL_OPEN_ID, { valid: accountValidIds });

  // The By-tax-treatment view's scope control (all / taxable / retirement) for its allocation pie --
  // its own URL key, independent of `view`/`account` above, per `useUrlState`'s "other params
  // survive" contract.
  const [scope, setScope] = useUrlState<TaxScope>("scope", "all", { valid: TAX_SCOPES });

  // The sector vocabulary and the current symbol -> sector map, fetched once here rather than once
  // per `SectorBadgeEditor` -- every row's editor shares this same array. A failed fetch leaves the
  // vocabulary empty: `SectorBadgeEditor` still falls back to offering the position's own current
  // sector as its sole option, so nothing already on screen breaks, only re-assignment narrows.
  const [sectorVocabulary, setSectorVocabulary] = useState<string[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    api
      .stores(controller.signal)
      .then((s) => setStatus(s))
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setStatusError(
          e instanceof ApiRequestError
            ? t("portfolio.apiError", { status: e.status, message: e.message })
            : t("portfolio.cannotReachApi"),
        );
      });
    return () => {
      controller.abort();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    portfolioApi
      .sectors(controller.signal)
      .then((v) => setSectorVocabulary(v.vocabulary))
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        // Silently degrade -- see the `sectorVocabulary` state comment above.
      });
    return () => {
      controller.abort();
    };
  }, []);

  return (
    <>
      <h1>{t("portfolio.title")}</h1>
      <p className="subtitle">{t("portfolio.subtitle")}</p>

      {statusError && (
        <div className="panel">
          <div className="placeholder">{statusError}</div>
        </div>
      )}

      {status && (
        <div className="panel">
          <div className="status-grid">
            <Stat
              label={t("portfolio.stat.accounts")}
              value={status.ledger.account ?? 0}
              hint={report ? t("portfolio.stat.accountsHint", { open: report.open_account_count }) : undefined}
            />
            <Stat label={t("portfolio.stat.instruments")} value={status.ledger.instrument ?? 0} />
            <Stat label={t("portfolio.stat.imports")} value={status.ledger.raw_import ?? 0} />
            <Stat
              label={t("portfolio.stat.transactions")}
              value={status.ledger.transactions ?? 0}
            />
          </div>
        </div>
      )}

      {/* Many seconds on a large book: `usePortfolio` reconstructs every holding from transaction history
          before it can render a single row. A one-line "Loading…" left the whole page collapsed for
          that entire time and then snapped open to a caveat strip, four totals and a positions
          table. `rows` is the right silhouette here -- the table below it is what dominates the
          eventual height, not the tiles. */}
      {phase === "loading" && (
        <div className="panel">
          <Skeleton variant="rows" rows={6} what={t("portfolio.title")} />
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
            {report ? (
              t("portfolio.empty.noOpenPositions", { asOf: report.as_of })
            ) : (
              <Trans
                k="portfolio.empty.noLedger"
                values={{
                  dataDir: <code>data/</code>,
                  activityLink: <Link to="/activity">Activity</Link>,
                }}
              />
            )}
          </div>
        </div>
      )}

      {phase === "loaded" && report && (
        <>
          {/* Each top-level panel gets its own boundary: a malformed value in one part of the report
              (an uncertain-basis position, a warning group with a shape the UI does not expect) must
              not blank every other figure on the page along with it -- see `ErrorBoundary.tsx`'s own
              docstring for the concrete Tax-page incident this pattern exists to contain. */}
          <PanelBoundary label={t("portfolio.panel.caveats")}>
            <CaveatStrip report={report} />
          </PanelBoundary>
          <PanelBoundary label={t("portfolio.panel.totals")}>
            <TotalsPanel report={report} />
          </PanelBoundary>
          <PanelBoundary label={t("portfolio.panel.warnings")}>
            <WarningsSection warnings={report.warnings} warningGroups={report.warning_groups} />
          </PanelBoundary>

          <div className="panel positions-view-toggle">
            <FolderTabs
              size="md"
              label={t("portfolio.positionsView.ariaLabel")}
              active={view}
              onChange={(id) => setView(id as PositionsView)}
              items={[
                { id: "instrument", label: t("portfolio.tabs.byInstrument") },
                { id: "account", label: t("portfolio.tabs.byAccount") },
                { id: "tax", label: t("portfolio.tabs.byTaxTreatment") },
              ]}
            />
            <InfoNote className="positions-view-note" tone="quiet" summary={t("portfolio.positionsView.note")}>
              <p>{t("portfolio.positionsView.note.more")}</p>
            </InfoNote>
          </div>

          <PanelBoundary label={t("portfolio.panel.positions")}>
            {view === "instrument" ? (
              <ByInstrumentView report={report} vocabulary={sectorVocabulary} onSectorChanged={refresh} />
            ) : view === "account" ? (
              <ByAccountView
                report={report}
                vocabulary={sectorVocabulary}
                onSectorChanged={refresh}
                account={account}
                onAccountChange={setAccount}
              />
            ) : (
              <ByTaxTreatmentView
                report={report}
                vocabulary={sectorVocabulary}
                onSectorChanged={refresh}
                scope={scope}
                onScopeChange={setScope}
              />
            )}
          </PanelBoundary>
          <PanelBoundary label={t("portfolio.panel.cashByAccount")}>
            <CashByAccount report={report} />
          </PanelBoundary>
        </>
      )}
    </>
  );
}
