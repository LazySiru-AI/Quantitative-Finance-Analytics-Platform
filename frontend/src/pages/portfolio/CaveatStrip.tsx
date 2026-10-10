/**
 * The four honesty caveats that used to precede the view controls as four stacked full-width
 * `.panel` blocks (`PartialTotalsCaveat`, `CashCaveat`, `UncertaintySummary`, `ClosedAccountsNote`),
 * collapsed into ONE strip so the view rail sits above the fold on a normal viewport. Nothing here
 * changes what each caveat says or which i18n key it reads -- only the DOM shape around them, from
 * four bordered panels down to one panel holding four short items.
 *
 * **Partial totals stays visible, unconditionally.** Per this page's central rule (see
 * `Portfolio.tsx`'s module docstring), `total_market_value`/`total_unrealized` are sums over PRICED
 * positions only -- silently rendering that partial sum as if it were complete is the one mistake
 * this page must never make. So unlike the other three, its headline is never behind a disclosure;
 * only the other three's already-collapsed long form (`InfoNote`'s `children`) is exactly as far
 * from view as it was before this change.
 *
 * The closed-accounts note additionally has a second, GROWN home now: the account rail's "Closed"
 * tab (`ByAccountView.tsx`) shows the closed accounts themselves, one per row, with their all-time
 * realized result -- this strip keeps the short "why some positions vanished from the roll-up"
 * fact, the tab gives the "which accounts, and how did they do" browsing view neither this strip nor
 * the old `ClosedAccountsNote` ever offered.
 */
import { hasBalance, type AccountCashBalance, type PortfolioReport } from "@/api/portfolio";
import InfoNote from "@/components/InfoNote";
import { ScrollRegion } from "@/components/ScrollPanel";
import { Trans, useT } from "@/i18n";

function PartialTotalsBody({ report }: { report: PortfolioReport }) {
  const { t } = useT();
  const unpriced = report.unpriced_symbols;
  const total = report.positions.length;
  const headlineKey =
    total === 1
      ? "portfolio.partialCaveat.headline_1_1"
      : unpriced.length === 1
        ? "portfolio.partialCaveat.headline_n_1"
        : "portfolio.partialCaveat.headline_n_n";
  return (
    <div className="callout callout-danger caveat-strip-item" role="alert">
      <strong>{t(headlineKey, { unpriced: unpriced.length, total, list: unpriced.join(", ") })}</strong>{" "}
      {t("portfolio.partialCaveat.detail")}
    </div>
  );
}

function CashCaveatBody({ report, excluded }: { report: PortfolioReport; excluded: AccountCashBalance[] }) {
  const { t } = useT();
  const total = report.cash_by_account.filter((a) => a.verdict !== "no_transactions").length;
  const singular = total === 1;
  const balanceNull = report.cash_balance === null;
  const headlineKey = singular
    ? balanceNull
      ? "portfolio.cashCaveat.headline_singularNull"
      : "portfolio.cashCaveat.headline_singularPartial"
    : balanceNull
      ? "portfolio.cashCaveat.headline_pluralNull"
      : "portfolio.cashCaveat.headline_pluralPartial";
  const headline = t(headlineKey, { excluded: excluded.length, total });

  return (
    <div className="callout callout-danger caveat-strip-item" role="alert">
      <strong>{headline}</strong>
      <ScrollRegion size="sm" label={headline}>
        <ul className="cash-reasons">
          {excluded.map((account) => (
            <li key={account.account_id}>
              <InfoNote
                tone="quiet"
                summary={
                  <>
                    <strong>{account.account_label}</strong> ({account.broker}) —{" "}
                    {t("portfolio.cashCaveat.reasonTag")}
                  </>
                }
              >
                <p>{account.reason}</p>
              </InfoNote>
            </li>
          ))}
        </ul>
      </ScrollRegion>
      {t("portfolio.cashCaveat.footer")}
    </div>
  );
}

function UncertaintySummaryBody({ report }: { report: PortfolioReport }) {
  const { t } = useT();
  const { positions_with_uncertain_basis: uncertain, positions_with_unknown_fees: feesUnknown } = report;
  return (
    <div className="callout callout-warn caveat-strip-item">
      {uncertain > 0 && (
        <InfoNote
          summary={
            <Trans k="portfolio.uncertainty.basis.headline" values={{ countBold: <strong>{uncertain}</strong> }} />
          }
        >
          <p>{t("portfolio.uncertainty.basis.detail")}</p>
        </InfoNote>
      )}
      {feesUnknown > 0 && (
        <InfoNote
          summary={
            <Trans
              k="portfolio.uncertainty.feesUnknown.headline"
              values={{ countBold: <strong>{feesUnknown}</strong> }}
            />
          }
        >
          <p>{t("portfolio.uncertainty.feesUnknown.detail")}</p>
        </InfoNote>
      )}
    </div>
  );
}

function ClosedAccountsBody({ report }: { report: PortfolioReport }) {
  const { t } = useT();
  return (
    <div className="caveat-strip-item">
      <InfoNote
        summary={t(
          report.excluded_closed_positions === 1 ? "portfolio.closed.note_one" : "portfolio.closed.note_other",
          {
            count: report.excluded_closed_positions,
            list: report.excluded_closed_symbols.join(", "),
          },
        )}
      >
        <p>{t("portfolio.closed.note.more")}</p>
      </InfoNote>
    </div>
  );
}

/** The merged strip. Renders nothing (same as each of the four originals) when none of the four
 *  conditions apply -- an empty ledger with fully-priced, fully-derivable cash and no closed
 *  accounts shows no caveats at all, same as before. */
export function CaveatStrip({ report }: { report: PortfolioReport }) {
  const hasPartial = report.unpriced_symbols.length > 0;
  const cashExcluded = report.cash_by_account.filter(
    (account) => !hasBalance(account.verdict) && account.verdict !== "no_transactions",
  );
  const hasCash = cashExcluded.length > 0;
  const hasUncertainty = report.positions_with_uncertain_basis > 0 || report.positions_with_unknown_fees > 0;
  const hasClosed = report.excluded_closed_positions > 0;

  if (!hasPartial && !hasCash && !hasUncertainty && !hasClosed) return null;

  return (
    <div className="panel caveat-strip">
      {hasPartial && <PartialTotalsBody report={report} />}
      {hasCash && <CashCaveatBody report={report} excluded={cashExcluded} />}
      {hasUncertainty && <UncertaintySummaryBody report={report} />}
      {hasClosed && <ClosedAccountsBody report={report} />}
    </div>
  );
}

export default CaveatStrip;
