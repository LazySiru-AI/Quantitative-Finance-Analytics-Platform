/**
 * Pure data-shaping helpers behind the Account page's three positions views (`ByInstrumentView`,
 * `ByAccountView`, `ByTaxTreatmentView`) -- no JSX, no hooks, nothing that reads or writes the URL.
 * Split out of `Portfolio.tsx` (see that file's own docstring for why the page is shaped the way it
 * is) purely to keep the 2,900-line original navigable; every function here is unchanged in
 * behaviour from what it replaced.
 *
 * The one rule every builder below agrees on: a slice's `market_value`/`unrealized` is computed
 * from that slice's OWN quantity/cost-basis against the instrument's shared `price`/`previous_close`
 * -- never borrowed from the instrument-level aggregate `Position` already carries -- because two
 * accounts holding the same instrument at different cost bases must not silently inherit each
 * other's dollar figures.
 */
import { type DecimalString } from "@/api/client";
import {
  compareMoneyDesc,
  formatWeightPct,
  hasBalance,
  moneyTone,
  multiplyMoneyByQuantity,
  subtractMoney,
  sumMoney,
  type AccountCashBalance,
  type AccountPosition,
  type AccountSummary,
  type PortfolioReport,
  type Position,
  type TaxTreatment,
} from "@/api/portfolio";
import type { AllocationMode, AllocationSlice } from "@/components/AllocationPie";
import { t } from "@/i18n";

// ---------------------------------------------------------------------------
// Shared sort/compare helpers -- money and nullable-number comparisons used by both the instrument
// table and the account/tax-group table. Ascending-style comparators throughout (negative means `a`
// sorts first), matching `sortRows`'s contract of multiplying by +1/-1 for asc/desc.
// ---------------------------------------------------------------------------

export function compareNullableMoneyAsc(a: DecimalString | null, b: DecimalString | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return -1;
  if (b === null) return 1;
  return compareMoneyDesc(b, a);
}

export function compareNullableNumber(a: number | null, b: number | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return -1;
  if (b === null) return 1;
  return a - b;
}

/**
 * `numerator / denominator` as a UI-only convenience fraction, never a wire figure. Used for the
 * per-account and per-tax-group `unrealized_pct` this page derives (the server only computes
 * `unrealized_pct` at the whole-position granularity) -- a rendering-only ratio in the same spirit as
 * `AllocationPie.tsx`'s `valueToFraction`, not a figure any total on this page is built from.
 */
export function fractionOrNull(numerator: DecimalString, denominator: DecimalString): number | null {
  const den = Number(denominator);
  if (!Number.isFinite(den) || den === 0) return null;
  const num = Number(numerator);
  if (!Number.isFinite(num)) return null;
  return num / den;
}

/**
 * "clears 2026-04-01" for a single settlement date, or "clears 2026-04-01 → 2026-04-03" when the
 * pending inflows behind an unsettled figure settle on different dates. `undefined` when there is
 * nothing to say -- the caller decides whether that means "omit the clause" or "nothing pending",
 * which is exactly why this takes the raw next/full dates rather than a pre-decided boolean.
 */
export function settlementClause(next: string | null, full: string | null): string | undefined {
  if (next === null || full === null) return undefined;
  return next === full
    ? t("portfolio.cash.clearsOne", { date: next })
    : t("portfolio.cash.clearsRange", { next, full });
}

/**
 * The single largest holding by share of priced market value, or `"—"` when nothing is priced yet.
 * `weight_pct` is already the right denominator for this (see its docstring on `Position`) -- a
 * second "biggest position" computed some other way would risk disagreeing with the weight column
 * the reader can already see in the positions table.
 */
export function largestPositionSummary(report: PortfolioReport): string {
  let best: Position | null = null;
  for (const position of report.positions) {
    if (position.weight_pct === null) continue;
    if (best === null || position.weight_pct > (best.weight_pct as number)) {
      best = position;
    }
  }
  return best === null ? "—" : `${best.symbol} (${formatWeightPct(best.weight_pct)})`;
}

/**
 * A compact "$41.2k" / "$1.2M" rendering for the account-rail tab badges -- the one place on this
 * page a dollar figure is deliberately NOT shown at full precision. `formatMoney`/`formatMoneyOrDash`
 * elsewhere on this page always render the exact cent figure because a total is something a reader
 * checks arithmetic against; a tab badge is a wayfinding hint next to a label the reader already
 * knows the full figure for one click away, so full precision there would just be noise competing
 * with the tab's own label for width.
 */
export function formatCompactMoney(value: DecimalString | null): string {
  if (value === null) return "—";
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const abs = Math.abs(num);
  const sign = num < 0 ? "-" : "";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(0)}`;
}

/**
 * One account's market value, summed over its PRICED slices only -- the same "priced positions only"
 * rule `total_market_value` documents, applied at account granularity. `null` when the account holds
 * nothing priced (never a fabricated `$0`), matching `formatCompactMoney`'s own `null` -> "—" rule.
 * Deliberately cheaper than `buildAccountPanelData`: the account rail needs only this one number per
 * tab, not the full row set a selected panel renders, so this walks `report.positions` once per
 * account rather than building every intermediate row.
 */
export function computeAccountMarketValue(report: PortfolioReport, accountId: string): DecimalString | null {
  const values: DecimalString[] = [];
  for (const position of report.positions) {
    if (position.price === null) continue;
    for (const ap of position.accounts) {
      if (ap.account_id !== accountId) continue;
      values.push(multiplyMoneyByQuantity(position.price, ap.quantity));
    }
  }
  return values.length > 0 ? sumMoney(values) : null;
}

/** The account-rail tab badge text for one open account: `"{position_count} · {compact market value}"`
 *  (e.g. `"12 · $41.2k"`). Compact rather than full precision -- see `formatCompactMoney`'s docstring. */
export function accountTabBadge(report: PortfolioReport, account: AccountSummary): string {
  return `${account.position_count} · ${formatCompactMoney(computeAccountMarketValue(report, account.account_id))}`;
}

// ---------------------------------------------------------------------------
// Per-slice rows shared by the by-account panel and the by-tax-treatment groups.
// ---------------------------------------------------------------------------

/** One instrument's slice of one account (or of a combined group of accounts), with figures computed
 *  for that slice alone -- never borrowed from the instrument's aggregate. Shared by the by-account
 *  panel and the by-tax-treatment groups: the shape a row needs to render is identical either way,
 *  only what it sums over differs. */
export interface AccountPositionRow {
  instrumentId: string;
  symbol: string;
  /** Sector label for the underlying exposure -- see `Position.sector`. Identical for every slice of
   *  the same instrument, since sector is a property of the instrument, not of which account holds it. */
  sector: string;
  quantity: DecimalString;
  costBasis: DecimalString;
  lotCount: number;
  basisUncertain: boolean;
  feesUnknown: boolean;
  price: DecimalString | null;
  priceAsOf: string | null;
  /** `price × quantity` for this slice only, via `multiplyMoneyByQuantity`. `null` iff `price` is
   *  `null` -- the instrument itself is unpriced, not just this slice of it. */
  marketValue: DecimalString | null;
  unrealized: DecimalString | null;
  /** `unrealized / costBasis` for this slice -- a UI-only ratio (see `fractionOrNull`), not a wire
   *  figure, because the server only computes `unrealized_pct` at the whole-position granularity. */
  unrealizedPct: number | null;
  /** `(price - previousClose) × quantity` for this slice, mirroring `Position.day_change` one
   *  granularity down. `null` under the same conditions as `Position.day_change`. */
  dayChange: DecimalString | null;
  /** `(price - previousClose) / previousClose` -- identical for every slice of the same instrument,
   *  since the ratio does not depend on how many shares this slice holds. Passed through from
   *  `Position.day_change_pct` rather than recomputed. */
  dayChangePct: number | null;
}

/** One `Position` × one `AccountPosition` slice, computed once so every builder below (single
 *  account, combined "all open" group, tax-treatment group) agrees on the arithmetic. */
export function buildAccountPositionRow(position: Position, ap: AccountPosition): AccountPositionRow {
  const marketValue = position.price !== null ? multiplyMoneyByQuantity(position.price, ap.quantity) : null;
  const unrealized = marketValue !== null ? subtractMoney(marketValue, ap.cost_basis) : null;
  const unrealizedPct = unrealized !== null ? fractionOrNull(unrealized, ap.cost_basis) : null;
  const dayChange =
    position.price !== null && position.previous_close !== null
      ? multiplyMoneyByQuantity(subtractMoney(position.price, position.previous_close), ap.quantity)
      : null;
  return {
    instrumentId: position.instrument_id,
    symbol: position.symbol,
    sector: position.sector,
    quantity: ap.quantity,
    costBasis: ap.cost_basis,
    lotCount: ap.lot_count,
    basisUncertain: ap.basis_uncertain,
    feesUnknown: ap.fees_unknown,
    price: position.price,
    priceAsOf: position.price_as_of,
    marketValue,
    unrealized,
    unrealizedPct,
    dayChange,
    dayChangePct: position.day_change_pct,
  };
}

/** Splits a row list into priced (sorted by market value descending) and unpriced (sorted
 *  alphabetically), and sums the three headline subtotals over them -- the one place every panel
 *  below computes "cost basis / market value / unrealized, given a set of rows" so the three never
 *  disagree on rounding or on which rows count. */
export function summarizeRows(rows: AccountPositionRow[]): {
  priced: AccountPositionRow[];
  unpriced: AccountPositionRow[];
  costBasisTotal: DecimalString;
  marketValueTotal: DecimalString | null;
  unrealizedTotal: DecimalString | null;
} {
  const priced = rows
    .filter((r) => r.marketValue !== null)
    .sort((a, b) => compareMoneyDesc(a.marketValue as DecimalString, b.marketValue as DecimalString));
  const unpriced = rows.filter((r) => r.marketValue === null).sort((a, b) => a.symbol.localeCompare(b.symbol));
  const costBasisTotal = sumMoney(rows.map((r) => r.costBasis));
  const marketValueTotal = priced.length > 0 ? sumMoney(priced.map((r) => r.marketValue as DecimalString)) : null;
  const unrealizedTotal =
    marketValueTotal !== null ? subtractMoney(marketValueTotal, sumMoney(priced.map((r) => r.costBasis))) : null;
  return { priced, unpriced, costBasisTotal, marketValueTotal, unrealizedTotal };
}

/** How the selected panel's cash tile should render -- a single real account carries one
 *  `AccountCashBalance` with its own verdict/reason/settlement clause (reuse `AccountCashTile`
 *  unchanged); "All open accounts" has no such single record, only a sum of however many of them
 *  could be derived or declared, so it renders through the simpler "N of M accounts" hint pattern
 *  `TaxGroupSection`'s cash tile already established. */
export type PanelCashInfo =
  | { kind: "single"; cash: AccountCashBalance | null }
  | { kind: "combined"; total: DecimalString | null; partial: boolean; includedCount: number; totalCount: number };

/** Everything one account panel (a single real account, or the combined "all open accounts" view)
 *  needs to render: its headline figures, its cash, and the position rows behind both the table and
 *  the allocation pie. */
export interface SelectedPanelData {
  key: string;
  label: string;
  broker: string | null;
  taxTreatment: TaxTreatment | null;
  isClosed: boolean;
  warningCount: number;
  costBasisTotal: DecimalString;
  marketValueTotal: DecimalString | null;
  unrealizedTotal: DecimalString | null;
  partial: boolean;
  cash: PanelCashInfo;
  rows: AccountPositionRow[];
  /** All-time reportable realized gain/loss for this account (or summed across every open account
   *  for the combined panel) -- always known, since `AccountSummary.realized_gain` is a real, never
   *  withheld figure (see its docstring in `api/portfolio.ts`). */
  realizedGain: DecimalString;
  /** `realizedGain + unrealizedTotal`, `null` whenever `unrealizedTotal` is -- mirrors the page-wide
   *  Accumulated tile: a withheld unrealized figure must not silently render a realized-only number
   *  under a label that promises both. */
  accumulated: DecimalString | null;
  /** Sum of `dayChange` over this panel's rows that have one -- `null` when none do (nothing in the
   *  panel could produce a previous-close comparison), never a fabricated `0.00`. */
  dayChangeTotal: DecimalString | null;
  /** `dayChangeTotal / (marketValueTotal - dayChangeTotal)`, the same ratio `total_day_change_pct`'s
   *  docstring defines at the whole-report granularity -- `null` when either side of that division
   *  is unavailable. */
  dayChangePct: number | null;
}

/** The Today tile's dollar total and percent for a set of rows, mirroring `total_day_change`/
 *  `total_day_change_pct`'s definition one granularity down (see `SelectedPanelData`'s own
 *  docstring). Shared by every panel builder below so none of them can disagree on the arithmetic. */
export function computePanelDayChange(
  rows: AccountPositionRow[],
  marketValueTotal: DecimalString | null,
): { dayChangeTotal: DecimalString | null; dayChangePct: number | null } {
  const withDayChange = rows.filter((r): r is AccountPositionRow & { dayChange: DecimalString } => r.dayChange !== null);
  if (withDayChange.length === 0) return { dayChangeTotal: null, dayChangePct: null };
  const dayChangeTotal = sumMoney(withDayChange.map((r) => r.dayChange));
  const dayChangePct =
    marketValueTotal !== null ? fractionOrNull(dayChangeTotal, subtractMoney(marketValueTotal, dayChangeTotal)) : null;
  return { dayChangeTotal, dayChangePct };
}

/** One real account's panel data, built directly from `report.positions`/`cash_by_account` filtered
 *  to this `account_id` -- deliberately NOT derived from a report-wide per-account index, since the
 *  picker only ever needs one account's slice at a time and building an index for every account on
 *  every render would do work the reader never asked for. */
export function buildAccountPanelData(report: PortfolioReport, summary: AccountSummary): SelectedPanelData {
  const rows: AccountPositionRow[] = [];
  for (const position of report.positions) {
    for (const ap of position.accounts) {
      if (ap.account_id !== summary.account_id) continue;
      rows.push(buildAccountPositionRow(position, ap));
    }
  }
  const { priced, unpriced, costBasisTotal, marketValueTotal, unrealizedTotal } = summarizeRows(rows);
  const cash = report.cash_by_account.find((c) => c.account_id === summary.account_id) ?? null;
  const warningCount = report.warnings.filter((w) => w.account_id === summary.account_id).length;
  const allRows = [...priced, ...unpriced];
  const { dayChangeTotal, dayChangePct } = computePanelDayChange(allRows, marketValueTotal);

  return {
    key: summary.account_id,
    label: summary.label,
    broker: summary.broker,
    taxTreatment: summary.tax_treatment,
    isClosed: summary.status === "closed",
    warningCount,
    costBasisTotal,
    marketValueTotal,
    unrealizedTotal,
    partial: unpriced.length > 0,
    cash: { kind: "single", cash },
    rows: allRows,
    realizedGain: summary.realized_gain,
    accumulated: unrealizedTotal === null ? null : sumMoney([summary.realized_gain, unrealizedTotal]),
    dayChangeTotal,
    dayChangePct,
  };
}

/** The combined "All open accounts" panel -- every instrument summed across every OPEN account's
 *  slice of it (never a closed one; those are already excluded from `report.positions` server-side),
 *  and cash summed across whichever open accounts could derive or declare a balance. Mirrors
 *  `buildTaxGroupAggregates`'s per-instrument accumulation, but groups by "open" instead of by tax
 *  treatment. */
export function buildOpenAccountsPanel(report: PortfolioReport, openAccountIds: ReadonlySet<string>): SelectedPanelData {
  interface Accumulator {
    symbol: string;
    sector: string;
    quantity: DecimalString;
    costBasis: DecimalString;
    lotCount: number;
    basisUncertain: boolean;
    feesUnknown: boolean;
    price: DecimalString | null;
    priceAsOf: string | null;
    previousClose: DecimalString | null;
    dayChangePct: number | null;
  }
  const byInstrument = new Map<string, Accumulator>();
  for (const position of report.positions) {
    for (const ap of position.accounts) {
      if (!openAccountIds.has(ap.account_id)) continue;
      const existing = byInstrument.get(position.instrument_id);
      if (existing) {
        existing.quantity = sumMoney([existing.quantity, ap.quantity]);
        existing.costBasis = sumMoney([existing.costBasis, ap.cost_basis]);
        existing.lotCount += ap.lot_count;
        existing.basisUncertain = existing.basisUncertain || ap.basis_uncertain;
        existing.feesUnknown = existing.feesUnknown || ap.fees_unknown;
      } else {
        byInstrument.set(position.instrument_id, {
          symbol: position.symbol,
          sector: position.sector,
          quantity: ap.quantity,
          costBasis: ap.cost_basis,
          lotCount: ap.lot_count,
          basisUncertain: ap.basis_uncertain,
          feesUnknown: ap.fees_unknown,
          price: position.price,
          priceAsOf: position.price_as_of,
          previousClose: position.previous_close,
          dayChangePct: position.day_change_pct,
        });
      }
    }
  }

  const rows: AccountPositionRow[] = Array.from(byInstrument.entries()).map(([instrumentId, r]) => {
    const marketValue = r.price !== null ? multiplyMoneyByQuantity(r.price, r.quantity) : null;
    const unrealized = marketValue !== null ? subtractMoney(marketValue, r.costBasis) : null;
    const unrealizedPct = unrealized !== null ? fractionOrNull(unrealized, r.costBasis) : null;
    const dayChange =
      r.price !== null && r.previousClose !== null
        ? multiplyMoneyByQuantity(subtractMoney(r.price, r.previousClose), r.quantity)
        : null;
    return {
      instrumentId,
      symbol: r.symbol,
      sector: r.sector,
      quantity: r.quantity,
      costBasis: r.costBasis,
      lotCount: r.lotCount,
      basisUncertain: r.basisUncertain,
      feesUnknown: r.feesUnknown,
      price: r.price,
      priceAsOf: r.priceAsOf,
      marketValue,
      unrealized,
      unrealizedPct,
      dayChange,
      dayChangePct: r.dayChangePct,
    };
  });

  const { priced, unpriced, costBasisTotal, marketValueTotal, unrealizedTotal } = summarizeRows(rows);

  const cashBalances: DecimalString[] = [];
  let cashExcluded = 0;
  let cashCount = 0;
  for (const cash of report.cash_by_account) {
    if (!openAccountIds.has(cash.account_id)) continue;
    cashCount += 1;
    if (hasBalance(cash.verdict) && cash.balance !== null) cashBalances.push(cash.balance);
    else cashExcluded += 1;
  }
  const cashTotal = cashBalances.length > 0 ? sumMoney(cashBalances) : null;

  const warningCount = report.warnings.filter(
    (w) => w.account_id !== null && openAccountIds.has(w.account_id),
  ).length;

  const allRows = [...priced, ...unpriced];
  const { dayChangeTotal, dayChangePct } = computePanelDayChange(allRows, marketValueTotal);
  // Every open account's all-time realized gain, summed -- `AccountSummary.realized_gain` is always
  // known (never withheld), so unlike `cashTotal` above there is no partial-sum case to flag here.
  const realizedGain = sumMoney(
    report.accounts.filter((a) => openAccountIds.has(a.account_id)).map((a) => a.realized_gain),
  );

  return {
    key: "all-open",
    label: t("portfolio.accountPicker.allOption"),
    broker: null,
    taxTreatment: null,
    isClosed: false,
    warningCount,
    costBasisTotal,
    marketValueTotal,
    unrealizedTotal,
    partial: unpriced.length > 0,
    cash: {
      kind: "combined",
      total: cashTotal,
      partial: cashExcluded > 0,
      includedCount: cashCount - cashExcluded,
      totalCount: cashCount,
    },
    rows: allRows,
    realizedGain,
    accumulated: unrealizedTotal === null ? null : sumMoney([realizedGain, unrealizedTotal]),
    dayChangeTotal,
    dayChangePct,
  };
}

/** Ticker- or sector-mode slices for `AllocationPie`, built from a panel's priced rows plus an
 *  optional Cash slice -- unpriced rows cannot be valued at all, so they are excluded here and their
 *  count surfaces instead as the pie's footnote (`portfolio.alloc.unpricedNote`). Cash is added only
 *  when it is both known (`cashTotal !== null`) and strictly positive (`moneyTone === "pos"`) -- a
 *  withheld or zero cash figure adds nothing meaningful to a pie of dollar shares. */
export function buildAllocationSlices(
  rows: AccountPositionRow[],
  cashTotal: DecimalString | null,
  mode: AllocationMode,
): AllocationSlice[] {
  const priced = rows.filter(
    (r): r is AccountPositionRow & { marketValue: DecimalString } => r.marketValue !== null,
  );

  let slices: AllocationSlice[];
  if (mode === "ticker") {
    slices = priced.map((r) => ({
      key: r.instrumentId,
      label: r.symbol,
      sector: r.sector,
      value: r.marketValue,
      ticker: r.symbol,
    }));
  } else {
    const bySector = new Map<string, DecimalString[]>();
    for (const r of priced) {
      const existing = bySector.get(r.sector);
      if (existing) existing.push(r.marketValue);
      else bySector.set(r.sector, [r.marketValue]);
    }
    slices = Array.from(bySector.entries()).map(([sector, values]) => ({
      key: sector,
      label: sector,
      sector,
      value: sumMoney(values),
      ticker: null,
    }));
  }

  if (cashTotal !== null && moneyTone(cashTotal) === "pos") {
    slices.push({ key: "__cash__", label: t("portfolio.alloc.cashSlice"), sector: "", value: cashTotal, ticker: null });
  }
  return slices;
}

// ---------------------------------------------------------------------------
// By-tax-treatment aggregation -- see `ByTaxTreatmentView.tsx` for the view that renders this.
// ---------------------------------------------------------------------------

export type TaxGroupKey = "taxable" | "retirement";

/** Both groups' keys, in display order. */
export const TAX_GROUP_KEYS: readonly TaxGroupKey[] = ["taxable", "retirement"];

/** Roth and traditional are two different `TaxTreatment` values but land in the same group here --
 *  the boundary this view draws is "never taxed on the way out" vs. "ordinary taxable gain", not a
 *  finer split of retirement account types. */
export function taxGroupFor(treatment: TaxTreatment): TaxGroupKey {
  return treatment === "taxable" ? "taxable" : "retirement";
}

export interface TaxGroupAggregate {
  key: TaxGroupKey;
  /** Every account in `cash_by_account` with this group's tax treatment, whether or not it holds a
   *  position right now -- cash is account-level data independent of what the account currently
   *  holds, same reasoning `TotalsTiles` uses for the whole-portfolio `cash_balance`. */
  accountCount: number;
  /** One row per instrument actually held by this group -- a sum across every account in the group
   *  holding it, not a per-account row. Reuses `AccountPositionRow` because the shape a row needs to
   *  render is identical either way. */
  priced: AccountPositionRow[];
  unpriced: AccountPositionRow[];
  costBasisTotal: DecimalString;
  marketValueTotal: DecimalString | null;
  unrealizedTotal: DecimalString | null;
  partial: boolean;
  cashTotal: DecimalString | null;
  cashExcludedCount: number;
}

/**
 * Groups the same positions the by-account panel slices by account, but by tax treatment instead --
 * exactly two buckets (`taxGroupFor`). Joins `Position.accounts[]` to `cash_by_account` on
 * `account_id`, so an instrument held in both a taxable and a retirement account contributes only
 * that group's quantity/cost-basis to each side -- never the whole position counted twice.
 *
 * An account slice whose `account_id` has no `cash_by_account` entry carries no known tax treatment --
 * there is nowhere else it could come from -- and guessing it into one side would be worse than
 * admitting it is unknown. Such slices are excluded from both groups and their account ids are
 * returned separately so the caller can say so on screen, rather than silently shrinking both totals.
 */
export function buildTaxGroupAggregates(report: PortfolioReport): {
  groups: TaxGroupAggregate[];
  unknownTreatmentAccountIds: string[];
} {
  const cashByAccount = new Map(report.cash_by_account.map((c) => [c.account_id, c]));

  interface RowAccumulator {
    symbol: string;
    sector: string;
    quantity: DecimalString;
    costBasis: DecimalString;
    lotCount: number;
    basisUncertain: boolean;
    feesUnknown: boolean;
    price: DecimalString | null;
    priceAsOf: string | null;
    previousClose: DecimalString | null;
    dayChangePct: number | null;
  }
  const rowsByGroup: Record<TaxGroupKey, Map<string, RowAccumulator>> = {
    taxable: new Map(),
    retirement: new Map(),
  };
  const unknownTreatmentAccountIds = new Set<string>();

  for (const position of report.positions) {
    for (const ap of position.accounts) {
      const cash = cashByAccount.get(ap.account_id);
      if (!cash) {
        unknownTreatmentAccountIds.add(ap.account_id);
        continue;
      }
      const map = rowsByGroup[taxGroupFor(cash.tax_treatment)];
      const existing = map.get(position.instrument_id);
      if (existing) {
        // Same instrument, another account in the same group -- sum the slices rather than replacing
        // one with the other. `basis_uncertain`/`fees_unknown` propagate the same way the whole-book
        // roll-up does: if any contributing account's slice is flagged, the group row is too.
        existing.quantity = sumMoney([existing.quantity, ap.quantity]);
        existing.costBasis = sumMoney([existing.costBasis, ap.cost_basis]);
        existing.lotCount += ap.lot_count;
        existing.basisUncertain = existing.basisUncertain || ap.basis_uncertain;
        existing.feesUnknown = existing.feesUnknown || ap.fees_unknown;
      } else {
        map.set(position.instrument_id, {
          symbol: position.symbol,
          sector: position.sector,
          quantity: ap.quantity,
          costBasis: ap.cost_basis,
          lotCount: ap.lot_count,
          basisUncertain: ap.basis_uncertain,
          feesUnknown: ap.fees_unknown,
          price: position.price,
          priceAsOf: position.price_as_of,
          previousClose: position.previous_close,
          dayChangePct: position.day_change_pct,
        });
      }
    }
  }

  const cashByGroup: Record<
    TaxGroupKey,
    { balances: DecimalString[]; excluded: number; count: number }
  > = {
    taxable: { balances: [], excluded: 0, count: 0 },
    retirement: { balances: [], excluded: 0, count: 0 },
  };
  for (const cash of report.cash_by_account) {
    const bucket = cashByGroup[taxGroupFor(cash.tax_treatment)];
    bucket.count += 1;
    if (hasBalance(cash.verdict) && cash.balance !== null) {
      bucket.balances.push(cash.balance);
    } else {
      bucket.excluded += 1;
    }
  }

  const groups: TaxGroupAggregate[] = TAX_GROUP_KEYS.map((key) => {
    const priced: AccountPositionRow[] = [];
    const unpriced: AccountPositionRow[] = [];
    for (const [instrumentId, r] of rowsByGroup[key]) {
      const marketValue = r.price !== null ? multiplyMoneyByQuantity(r.price, r.quantity) : null;
      const unrealized = marketValue !== null ? subtractMoney(marketValue, r.costBasis) : null;
      const unrealizedPct = unrealized !== null ? fractionOrNull(unrealized, r.costBasis) : null;
      const dayChange =
        r.price !== null && r.previousClose !== null
          ? multiplyMoneyByQuantity(subtractMoney(r.price, r.previousClose), r.quantity)
          : null;
      const row: AccountPositionRow = {
        instrumentId,
        symbol: r.symbol,
        sector: r.sector,
        quantity: r.quantity,
        costBasis: r.costBasis,
        lotCount: r.lotCount,
        basisUncertain: r.basisUncertain,
        feesUnknown: r.feesUnknown,
        price: r.price,
        priceAsOf: r.priceAsOf,
        marketValue,
        unrealized,
        unrealizedPct,
        dayChange,
        dayChangePct: r.dayChangePct,
      };
      (marketValue !== null ? priced : unpriced).push(row);
    }
    priced.sort((a, b) =>
      compareMoneyDesc(a.marketValue as DecimalString, b.marketValue as DecimalString),
    );
    unpriced.sort((a, b) => a.symbol.localeCompare(b.symbol));

    const costBasisTotal = sumMoney([...priced, ...unpriced].map((r) => r.costBasis));
    const marketValueTotal =
      priced.length > 0 ? sumMoney(priced.map((r) => r.marketValue as DecimalString)) : null;
    const unrealizedTotal =
      marketValueTotal !== null
        ? subtractMoney(marketValueTotal, sumMoney(priced.map((r) => r.costBasis)))
        : null;

    const cashBucket = cashByGroup[key];
    const cashTotal = cashBucket.balances.length > 0 ? sumMoney(cashBucket.balances) : null;

    return {
      key,
      accountCount: cashBucket.count,
      priced,
      unpriced,
      costBasisTotal,
      marketValueTotal,
      unrealizedTotal,
      partial: unpriced.length > 0,
      cashTotal,
      cashExcludedCount: cashBucket.excluded,
    };
  });

  return { groups, unknownTreatmentAccountIds: Array.from(unknownTreatmentAccountIds) };
}

// ---------------------------------------------------------------------------
// Scoped allocation -- the tax-treatment view's scope control (all / taxable / retirement, optionally
// narrowed to one account) reads through this rather than a bespoke third copy of the accumulation
// logic `buildTaxGroupAggregates`/`buildOpenAccountsPanel` each already do.
// ---------------------------------------------------------------------------

/** Which slice of the book a caller wants: every account (`{}`), one `TaxGroupKey`'s worth of
 *  accounts, one account by id, or both narrowed together (an account only counts when it ALSO
 *  matches the requested treatment -- an account carrying the other treatment contributes nothing,
 *  the same way an instrument absent from a group contributes nothing to that group's total). */
export interface AllocationScope {
  treatment?: TaxGroupKey;
  accountId?: string;
}

/**
 * The position rows + cash total for an arbitrary scope -- reuses the exact join against
 * `cash_by_account.tax_treatment` that `buildTaxGroupAggregates` performs (see that function's own
 * docstring) rather than a second, possibly-drifting copy of it. An account slice with no matching
 * `cash_by_account` entry has no known tax treatment and is excluded from a `treatment`-scoped
 * request for the same reason `buildTaxGroupAggregates` excludes it from both of its groups: guessing
 * it into one side would be worse than admitting it is unknown.
 *
 * Every derived per-row figure (`marketValue`/`unrealized`/`unrealizedPct`/`dayChange`) is computed
 * once from the SUMMED quantity/cost-basis across every account slice this scope includes -- never
 * summed from already-derived per-slice rows -- so a symbol split across two accounts inside the same
 * scope reports one honest figure for its combined position, matching
 * `buildTaxGroupAggregates`/`buildOpenAccountsPanel`'s own accumulate-then-derive order.
 */
export function buildScopedPositionRows(
  report: PortfolioReport,
  scope: AllocationScope,
): { rows: AccountPositionRow[]; cashTotal: DecimalString | null } {
  const cashByAccount = new Map(report.cash_by_account.map((c) => [c.account_id, c]));

  const matchesScope = (accountId: string): boolean => {
    if (scope.accountId !== undefined && accountId !== scope.accountId) return false;
    if (scope.treatment !== undefined) {
      const cash = cashByAccount.get(accountId);
      if (!cash || taxGroupFor(cash.tax_treatment) !== scope.treatment) return false;
    }
    return true;
  };

  interface Accumulator {
    symbol: string;
    sector: string;
    quantity: DecimalString;
    costBasis: DecimalString;
    lotCount: number;
    basisUncertain: boolean;
    feesUnknown: boolean;
    price: DecimalString | null;
    priceAsOf: string | null;
    previousClose: DecimalString | null;
    dayChangePct: number | null;
  }
  const byInstrument = new Map<string, Accumulator>();

  for (const position of report.positions) {
    for (const ap of position.accounts) {
      if (!matchesScope(ap.account_id)) continue;
      const existing = byInstrument.get(position.instrument_id);
      if (existing) {
        existing.quantity = sumMoney([existing.quantity, ap.quantity]);
        existing.costBasis = sumMoney([existing.costBasis, ap.cost_basis]);
        existing.lotCount += ap.lot_count;
        existing.basisUncertain = existing.basisUncertain || ap.basis_uncertain;
        existing.feesUnknown = existing.feesUnknown || ap.fees_unknown;
      } else {
        byInstrument.set(position.instrument_id, {
          symbol: position.symbol,
          sector: position.sector,
          quantity: ap.quantity,
          costBasis: ap.cost_basis,
          lotCount: ap.lot_count,
          basisUncertain: ap.basis_uncertain,
          feesUnknown: ap.fees_unknown,
          price: position.price,
          priceAsOf: position.price_as_of,
          previousClose: position.previous_close,
          dayChangePct: position.day_change_pct,
        });
      }
    }
  }

  const rows: AccountPositionRow[] = Array.from(byInstrument.entries()).map(([instrumentId, r]) => {
    const marketValue = r.price !== null ? multiplyMoneyByQuantity(r.price, r.quantity) : null;
    const unrealized = marketValue !== null ? subtractMoney(marketValue, r.costBasis) : null;
    const unrealizedPct = unrealized !== null ? fractionOrNull(unrealized, r.costBasis) : null;
    const dayChange =
      r.price !== null && r.previousClose !== null
        ? multiplyMoneyByQuantity(subtractMoney(r.price, r.previousClose), r.quantity)
        : null;
    return {
      instrumentId,
      symbol: r.symbol,
      sector: r.sector,
      quantity: r.quantity,
      costBasis: r.costBasis,
      lotCount: r.lotCount,
      basisUncertain: r.basisUncertain,
      feesUnknown: r.feesUnknown,
      price: r.price,
      priceAsOf: r.priceAsOf,
      marketValue,
      unrealized,
      unrealizedPct,
      dayChange,
      dayChangePct: r.dayChangePct,
    };
  });

  const cashBalances: DecimalString[] = [];
  for (const cash of report.cash_by_account) {
    if (!matchesScope(cash.account_id)) continue;
    if (hasBalance(cash.verdict) && cash.balance !== null) cashBalances.push(cash.balance);
  }
  const cashTotal = cashBalances.length > 0 ? sumMoney(cashBalances) : null;

  return { rows, cashTotal };
}
