/**
 * Per-account cash, shown only when at least one account actually has a balance to show.
 *
 * Two kinds of balance land in this table and the last column is what separates them. A *derived*
 * balance is a sum over a window of the export, and the window is the caveat -- nothing in an export
 * proves it reaches account inception. A *declared* balance was read off the broker on one day and
 * does not move afterwards, so its caveat is a date and the fact that it is frozen. Labelling the
 * column "Derived from" and printing a coverage window under a declared figure would assert the one
 * thing that is not true of it.
 */
import { formatMoneyOrDash, hasBalance, type PortfolioReport } from "@/api/portfolio";
import { ScrollRegion } from "@/components/ScrollPanel";
import InfoNote from "@/components/InfoNote";
import { Trans, useT } from "@/i18n";

import { CashSource } from "./tiles";

export function CashByAccount({ report }: { report: PortfolioReport }) {
  const { t } = useT();
  const shown = report.cash_by_account.filter((account) => hasBalance(account.verdict));
  if (shown.length === 0) return null;
  const anyDeclared = shown.some((account) => account.verdict === "declared");

  return (
    <section className="panel">
      <h2>{t("portfolio.cashByAccount.title")}</h2>
      <ScrollRegion size="sm" label={t("portfolio.cashByAccount.title")}>
        <div className="table-wrap">
        <table className="data-table cash-account-table">
        <thead>
          <tr>
            <th scope="col">{t("portfolio.header.account")}</th>
            <th scope="col">{t("portfolio.header.broker")}</th>
            <th scope="col" className="num">
              {t("portfolio.header.settled")}
            </th>
            <th scope="col" className="num">
              {t("portfolio.header.unsettled")}
            </th>
            <th scope="col" className="num">
              {t("portfolio.header.balance")}
            </th>
            <th scope="col">{t("common.source")}</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((account) => (
            <tr key={account.account_id}>
              <th scope="row">{account.account_label}</th>
              <td>{account.broker}</td>
              {/* `shown` is filtered to verdicts that carry a balance, where the server guarantees
                  these are present -- but a filter narrows nothing for the type checker, and
                  coercing a null to `$0.00` here is exactly the failure this page's own contract
                  forbids. So each renders an em dash on null, matching MoneyTile. */}
              <td className="num">{formatMoneyOrDash(account.settled)}</td>
              <td className="num">{formatMoneyOrDash(account.unsettled)}</td>
              <td className="num">{formatMoneyOrDash(account.balance)}</td>
              <td className="muted">
                <CashSource account={account} />
              </td>
            </tr>
          ))}
          </tbody>
        </table>
        </div>
      </ScrollRegion>
      <InfoNote summary={t("portfolio.cashByAccount.notesSummary")}>
        <p>
          <Trans
            k="portfolio.cashByAccount.derivedNote"
            values={{ derived: <strong>{t("portfolio.cashByAccount.derivedWord")}</strong> }}
          />
        </p>
        {anyDeclared && (
          <p>
            <Trans
              k="portfolio.cashByAccount.declaredNote"
              values={{
                declared: <strong>{t("portfolio.cashByAccount.declaredWord")}</strong>,
                code: <code>data/accounts.toml</code>,
              }}
            />
          </p>
        )}
      </InfoNote>
    </section>
  );
}

export default CashByAccount;
