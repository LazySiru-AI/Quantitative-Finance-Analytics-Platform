/**
 * The page-wide totals panel: the as-of stamp, the download-statement link, and the seven money
 * tiles (cost basis, market value, cash, total equity, unrealized, today, accumulated) plus the
 * three-stat detail row underneath. Unchanged from what `Portfolio.tsx` rendered directly before the
 * `pages/portfolio/` split -- see that file's module docstring for the partial-totals rule every
 * figure here obeys.
 */
import {
  formatMoney,
  formatMoneyOrDash,
  formatSignedFractionPct,
  portfolioApi,
  priceAsOfRange,
  sumMoney,
  type PortfolioReport,
} from "@/api/portfolio";
import { Trans, useT } from "@/i18n";

import { largestPositionSummary, settlementClause } from "./aggregates";
import { MoneyTile, Stat, SummaryDetail } from "./tiles";

export function TotalsPanel({ report }: { report: PortfolioReport }) {
  const { t } = useT();
  const partial = report.unpriced_symbols.length > 0;
  const cashPartial = report.accounts_without_cash.length > 0;
  const pctHint =
    report.total_unrealized_pct === null ? undefined : formatSignedFractionPct(report.total_unrealized_pct);
  const dayChangeHint =
    report.total_day_change_pct === null ? undefined : formatSignedFractionPct(report.total_day_change_pct);

  // Realized is always known (every account's `realized_gain` is a real, non-null figure); unrealized
  // is not (see `total_unrealized`'s own "priced positions only" rule). Rather than silently treating a
  // withheld unrealized figure as zero -- exactly the mistake `total_equity` refuses to make for the
  // same reason -- Accumulated goes `null` too whenever `total_unrealized` is `null`, instead of
  // quietly reporting realized-only under a label that promises both.
  const totalRealized = sumMoney(report.accounts.map((a) => a.realized_gain));
  const accumulated = report.total_unrealized === null ? null : sumMoney([totalRealized, report.total_unrealized]);

  // Unsettled proceeds are real money that cannot be spent today, so they are surfaced as a hint on
  // the cash tile rather than left for the reader to discover in the per-account panel. Both facts
  // are shown when both apply, rather than one winning -- see the git history on this tile for the
  // regression that motivated it.
  const cashParts: string[] = [];
  if (report.unsettled_cash !== null && report.unsettled_cash.trim() !== "0") {
    let unsettledPart = t("portfolio.cash.settledUnsettled", {
      settled: formatMoneyOrDash(report.settled_cash),
      unsettled: formatMoney(report.unsettled_cash),
    });
    const clause = settlementClause(report.unsettled_next_date, report.unsettled_full_date);
    if (clause) unsettledPart += ` (${clause})`;
    cashParts.push(unsettledPart);
  }
  if (cashPartial) {
    cashParts.push(
      t(
        report.accounts_without_cash.length === 1
          ? "portfolio.cash.accountsExcluded_one"
          : "portfolio.cash.accountsExcluded_other",
        { count: report.accounts_without_cash.length },
      ),
    );
  }
  const cashHint = cashParts.length > 0 ? cashParts.join(" · ") : undefined;

  const pricing = priceAsOfRange(report);

  return (
    <div className="panel">
      <div className="totals-asof muted">
        {pricing === null ? (
          t("portfolio.totals.asOfNothingPriced", { asOf: report.as_of })
        ) : pricing.earliest === pricing.latest ? (
          <Trans
            k="portfolio.totals.asOfSingle"
            values={{ asOf: report.as_of, latest: <strong>{pricing.latest}</strong> }}
          />
        ) : (
          <Trans
            k="portfolio.totals.asOfRange"
            values={{
              asOf: report.as_of,
              range: (
                <strong>
                  {pricing.earliest} → {pricing.latest}
                </strong>
              ),
              distinct: pricing.distinct,
            }}
          />
        )}
      </div>
      <div className="totals-actions">
        <a
          className="download-link"
          href={portfolioApi.statementUrl()}
          download={`portfolio-statement-${report.as_of}.md`}
        >
          {t("portfolio.totals.downloadStatement")}
        </a>
      </div>
      <div className="tile-grid">
        <MoneyTile
          label={t("portfolio.tile.costBasis")}
          value={report.total_cost_basis}
          hint={t(
            report.positions.length === 1 ? "portfolio.count.position_one" : "portfolio.count.position_other",
            { count: report.positions.length },
          )}
        />
        <MoneyTile
          label={t(partial ? "portfolio.tile.marketValuePartial" : "portfolio.tile.marketValue")}
          value={report.total_market_value}
          variant={partial ? "danger" : undefined}
          hint={
            partial
              ? t("portfolio.tile.pricedOfHint", {
                  priced: report.priced_position_count,
                  total: report.positions.length,
                })
              : t("portfolio.tile.pricedHint", { count: report.priced_position_count })
          }
        />
        <MoneyTile
          label={cashPartial ? t("portfolio.tile.cashPartial") : t("common.cash")}
          value={report.cash_balance}
          variant={cashPartial ? "danger" : undefined}
          hint={cashHint}
        />
        <MoneyTile
          label={t("portfolio.tile.totalEquity")}
          value={report.total_equity}
          variant={report.equity_is_complete ? undefined : "danger"}
          hint={
            report.equity_is_complete
              ? t("portfolio.tile.totalEquityHintComplete")
              : t("portfolio.tile.totalEquityHintIncomplete")
          }
          emphasize
        />
        <MoneyTile
          label={t(
            partial ? "portfolio.tile.unrealizedGainLossPartial" : "portfolio.tile.unrealizedGainLoss",
          )}
          value={report.total_unrealized}
          variant={partial ? "danger" : undefined}
          hint={pctHint}
          emphasize
          signed
        />
        <MoneyTile
          label={t("portfolio.tile.dayChange")}
          value={report.total_day_change}
          variant={partial ? "danger" : undefined}
          hint={dayChangeHint}
          signed
        />
        <MoneyTile
          label={t("portfolio.tile.accumulated")}
          value={accumulated}
          hint={t("portfolio.tile.accumulated.hint")}
          emphasize
          signed
        />
      </div>
      <div className="status-grid totals-detail-grid">
        <Stat label={t("portfolio.stat.accountsFunded")} value={report.cash_by_account.length} />
        <SummaryDetail
          label={t("portfolio.summary.positionCount")}
          value={
            report.unpriced_symbols.length > 0
              ? t("portfolio.summary.positionCountDetail", {
                  total: report.positions.length,
                  unpriced: report.unpriced_symbols.length,
                })
              : `${report.positions.length}`
          }
        />
        <SummaryDetail
          label={t("portfolio.summary.largestPosition")}
          value={largestPositionSummary(report)}
        />
      </div>
    </div>
  );
}

export default TotalsPanel;
