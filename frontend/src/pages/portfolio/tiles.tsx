/**
 * The Account page's small, reused presentational leaves -- a labelled number (`Stat`), a money
 * figure with an optional hint and danger tint (`MoneyTile`), and the cash-specific tiles that read
 * an `AccountCashBalance`/`PanelCashInfo` rather than a bare `DecimalString`.
 *
 * `MoneyTile` is deliberately NOT folded together with `Tax.tsx`/`WashSales.tsx`'s `StatTile` (see
 * `StatGrid.tsx`'s own docstring on that decision) or with `Activity.tsx`'s `Tile`: those pages agree
 * on the shared CSS contract (`stat tile`/`label`/`value`/`tile-hint`), not on a component, and
 * `MoneyTile` additionally owns money-formatting and sign/tone -- `StatTile`'s callers format their
 * own values -- which is exactly the difference that keeps these three call sites from converging.
 */
import type { DecimalString } from "@/api/client";
import {
  formatMoney,
  formatMoneyOrDash,
  formatSignedMoney,
  hasBalance,
  moneyTone,
  type AccountCashBalance,
} from "@/api/portfolio";
import { useT } from "@/i18n";

import { settlementClause, type PanelCashInfo } from "./aggregates";

export function Stat({ label, value, hint }: { label: string; value: number; hint?: string | undefined }) {
  return (
    <div className="stat">
      <span className="label">{label}</span>
      <span className="value">{value.toLocaleString()}</span>
      {hint && <span className="tile-hint">{hint}</span>}
    </div>
  );
}

/** A `Stat`-shaped tile for a summary figure that is not itself a number -- `Stat` calls
 *  `.toLocaleString()` on its value, which is exactly wrong for "SOXL (12.5%)". Same `.stat` markup
 *  either way, so it inherits the same styling without a second CSS class to maintain. */
export function SummaryDetail({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <span className="label">{label}</span>
      <span className="value">{value}</span>
    </div>
  );
}

export function MoneyTile({
  label,
  value,
  hint,
  variant,
  emphasize,
  signed,
}: {
  label: string;
  value: DecimalString | null;
  hint?: string | undefined;
  variant?: "danger" | undefined;
  emphasize?: boolean;
  signed?: boolean;
}) {
  const tone = signed && value !== null ? moneyTone(value) : "";
  const text = value === null ? "—" : signed ? formatSignedMoney(value) : formatMoney(value);
  return (
    <div className={`stat tile${variant ? ` tile-${variant}` : ""}`}>
      <span className="label">{label}</span>
      <span className={`value${emphasize ? " value-emphasize" : ""}${tone ? ` ${tone}` : ""}`}>
        {text}
      </span>
      {hint && <span className="tile-hint">{hint}</span>}
    </div>
  );
}

/** The last column of the "Cash by account" table: where this particular figure came from. */
export function CashSource({ account }: { account: AccountCashBalance }) {
  const { t } = useT();
  if (account.verdict === "declared") {
    return (
      <>
        <div>
          {t("portfolio.cashSource.declared", {
            date: account.declared_as_of ?? t("portfolio.cashSource.noDate"),
          })}
        </div>
        {account.declared_note && <div className="position-price-asof">{account.declared_note}</div>}
        {/* The derivation still ran. It only lands here when it produced a trustworthy figure and
            that figure disagrees, which means either the export is incomplete or the declaration is
            stale -- both worth knowing, neither safe to resolve silently. */}
        {account.derived_balance !== null && (
          <div className="entry-tag" title={t("portfolio.cashSource.disagreeTitle")}>
            {t("portfolio.cashSource.ledgerDerives", { amount: formatMoney(account.derived_balance) })}
          </div>
        )}
      </>
    );
  }
  return (
    <>
      {t("portfolio.cashSource.derivedRange", {
        start: account.coverage_start ?? "",
        end: account.coverage_end ?? "",
      })}
    </>
  );
}

/** The cash tile for one real account. Never coerces a withheld balance to `$0.00`: `MoneyTile`
 *  already renders `null` as an em dash, so the only job here is to make sure a withheld or missing
 *  balance reaches it as `null` rather than as a fabricated number, and that the reason ends up
 *  somewhere on screen instead of silently vanishing along with the figure. */
export function AccountCashTile({ cash }: { cash: AccountCashBalance | null }) {
  const { t } = useT();
  if (cash === null) {
    return (
      <MoneyTile
        label={t("common.cash")}
        value={null}
        variant="danger"
        hint={t("portfolio.accountCash.noData")}
      />
    );
  }
  if (!hasBalance(cash.verdict)) {
    return (
      <MoneyTile label={t("common.cash")} value={null} variant="danger" hint={cash.reason ?? undefined} />
    );
  }
  const hasUnsettled = cash.unsettled !== null && cash.unsettled.trim() !== "0";
  const parts: string[] = [];
  if (hasUnsettled) {
    let unsettledPart = t("portfolio.cash.settledUnsettled", {
      settled: formatMoneyOrDash(cash.settled),
      unsettled: formatMoney(cash.unsettled as DecimalString),
    });
    const clause = settlementClause(cash.unsettled_next_date, cash.unsettled_full_date);
    if (clause) unsettledPart += ` (${clause})`;
    parts.push(unsettledPart);
  }
  // A declared balance never renders without its date. It is a snapshot the user read off their
  // broker, it does not move as transactions are imported, and nothing here can notice it going
  // stale -- so undated it is indistinguishable from a live figure. See `declared_as_of`.
  if (cash.verdict === "declared" && cash.declared_as_of) {
    parts.push(t("portfolio.cash.declaredAsOf", { date: cash.declared_as_of }));
  }
  return (
    <MoneyTile
      label={t("common.cash")}
      value={cash.balance}
      hint={parts.length > 0 ? parts.join(" · ") : undefined}
    />
  );
}

/** The cash tile for the selected panel -- a single real account reuses `AccountCashTile` verbatim
 *  (same verdict/reason/settlement-clause rendering as before); the combined "all open accounts" view
 *  has no single `AccountCashBalance` to hand it, so it renders through the same "N of M accounts"
 *  hint pattern the by-tax-treatment groups use for their own multi-account sum. */
export function PanelCashTile({ info }: { info: PanelCashInfo }) {
  const { t } = useT();
  if (info.kind === "single") {
    return <AccountCashTile cash={info.cash} />;
  }
  const { total, partial, includedCount, totalCount } = info;
  return (
    <MoneyTile
      label={t(partial ? "portfolio.tile.cashPartial" : "common.cash")}
      value={total}
      variant={partial ? "danger" : undefined}
      hint={
        partial
          ? t("portfolio.tile.accountsOfHint", { n: includedCount, total: totalCount })
          : totalCount > 0
            ? t(totalCount === 1 ? "portfolio.count.account_one" : "portfolio.count.account_other", {
                count: totalCount,
              })
            : undefined
      }
    />
  );
}
