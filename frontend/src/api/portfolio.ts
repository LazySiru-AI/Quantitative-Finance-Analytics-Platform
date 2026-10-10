/**
 * Typed client for the portfolio endpoint.
 *
 * Mirrors `backend/app/portfolio/models.py` (`PortfolioReport`) field for field. As with `api/tax.ts`,
 * every money and quantity figure crosses the wire as a decimal *string* (pydantic serialises
 * `Decimal` that way to preserve precision past what an IEEE double can hold), so nothing here parses
 * one into a `number` for arithmetic. `formatMoney` is reused from `api/tax.ts` — one rendering rule
 * for money across the app, not two that could drift. `warnings`/`warning_groups` reuse `TaxWarning`
 * and `WarningGroup` from the same module for the same reason: the tax page already established that
 * vocabulary and shape, and this page's warnings are not a different kind of thing.
 *
 * Three things here are easy to get wrong and are worth reading before using the types.
 *
 * **The totals are computed over PRICED positions only.** `total_market_value`, `total_unrealized`
 * and `total_unrealized_pct` are `null` whenever no position has a price, and even when they are
 * non-null they silently exclude every symbol in `unpriced_symbols`. A non-empty `unpriced_symbols`
 * means the headline totals are a partial sum, not the whole portfolio — render that fact, do not
 * just render the number.
 *
 * **`null` is not `0` anywhere in this contract.** A position with no price has `price`,
 * `market_value`, `unrealized` and `unrealized_pct` all `null` — it still holds real shares with a
 * real cost basis, it is simply unpriced. Coercing any of those to zero would understate the
 * portfolio, not just fail to help.
 *
 * **`basis_uncertain` makes `unrealized` a bound, not an estimate.** A position replayed from an
 * import with a basis gap books some or all of its cost basis as zero, which can only overstate the
 * resulting gain (or understate a loss). Same idea as `GainRow.basis_uncertain` in `api/tax.ts`, one
 * level up: per-position instead of per-disposal. `fees_unknown` is independent and weaker — it means
 * the source export had no fee column, not that the basis itself is wrong.
 */

import {
  ApiRequestError,
  centsToDecimalString,
  decimalStringToCents,
  type DecimalString,
} from "@/api/client";
import { type TaxWarning, type WarningGroup } from "@/api/tax";
import { formatMoney, formatMoneyOrDash } from "@/format/money";
import { t } from "@/i18n";

export type { TaxWarning, WarningGroup };

export interface AccountPosition {
  account_id: string;
  account_label: string;
  broker: string;
  quantity: DecimalString;
  cost_basis: DecimalString;
  lot_count: number;
  basis_uncertain: boolean;
  fees_unknown: boolean;
}

export interface Position {
  instrument_id: string;
  symbol: string;
  quantity: DecimalString;
  cost_basis: DecimalString;
  basis_per_share: DecimalString;
  /** `null` when the instrument has no price in the bars store. */
  price: DecimalString | null;
  price_as_of: string | null;
  /** `null` iff `price` is `null` — never a computed `0`. */
  market_value: DecimalString | null;
  unrealized: DecimalString | null;
  unrealized_pct: number | null;
  /** Share of `total_market_value`. `null` whenever `market_value` is `null` (unpriced) or the
   *  portfolio total itself is `null` (nothing priced at all). */
  weight_pct: number | null;
  /** Sector label for the underlying exposure, from `data/sectors.toml`. Never `null` -- an
   *  unmapped symbol reports the literal string `"Unclassified"` rather than leaving the field
   *  absent, so a sector-mode allocation view always has a bucket for every position. */
  sector: string;
  /** The prior session's close, or `null` when the store could not produce two bars (a new
   *  listing, a stale symbol, a gap in the bars store). Backs `day_change`/`day_change_pct` --
   *  see those fields for why all three travel together and go `null` together. */
  previous_close: DecimalString | null;
  /** `quantize_money((price - previous_close) * quantity)`. `null` whenever `price` or
   *  `previous_close` is `null` -- never a computed `0` standing in for "no data", the same rule
   *  `market_value`/`unrealized` above already follow. */
  day_change: DecimalString | null;
  /** `(price - previous_close) / previous_close`, on the same 0–1 fraction scale as
   *  `unrealized_pct` -- format with `formatSignedFractionPct`, not `formatWeightPct`. `null` on
   *  the same conditions as `day_change`. */
  day_change_pct: number | null;
  /** Reflects wash-sale holding-period tolling, not just the raw acquisition date — a replacement
   *  lot's clock can start later than the day it was actually bought. Not decorative. */
  short_term_quantity: DecimalString;
  long_term_quantity: DecimalString;
  earliest_acquired: string;
  latest_acquired: string;
  lot_count: number;
  basis_uncertain: boolean;
  fees_unknown: boolean;
  wash_sale_adjustment: DecimalString;
  /** Same instrument held at more than one broker is common in this dataset; this is the per-account
   *  breakdown backing the position's aggregate figures above. */
  accounts: AccountPosition[];
}

/** Why an account's cash balance is or is not available. Mirrors `app.core.cash.CashVerdict`. */
export type CashVerdict =
  | "derived"
  | "declared"
  | "no_funding_rows"
  | "negative_in_cash_account"
  | "no_transactions";

/** Whether a verdict carries a balance at all. `derived` and `declared` both do and both count
 *  toward the total; they differ in how they go wrong, which is why the verdict itself stays
 *  visible rather than being collapsed to a boolean at the API boundary. */
export function hasBalance(verdict: CashVerdict): boolean {
  return verdict === "derived" || verdict === "declared";
}

/** How gains in an account are taxed. Mirrors `app.core.models.TaxTreatment`. Carried on
 *  `AccountCashBalance`, not on `AccountPosition` -- it is account metadata, not a position figure,
 *  so a per-account view joins the two on `account_id` rather than expecting it on every position
 *  row. A Roth/traditional account's unrealized gain is never (or not yet) taxed; see the Portfolio
 *  page module docstring for why that has to be a headline fact rather than a footnote. */
export type TaxTreatment = "taxable" | "roth_ira" | "traditional_ira";

export interface AccountCashBalance {
  /** The soonest any pending inflow clears, or `null`.
   *
   * `null` carries two distinguishable meanings and the UI must not merge them: nothing is pending
   * (`unsettled` is a real `0`), or the figure is withheld entirely (`unsettled` itself is `null` --
   * a declared balance read off a broker statement has no per-row settle date behind it). */
  unsettled_next_date: string | null;

  /** The date by which *all* pending inflows have cleared, or `null` on the same two conditions.
   *
   * Two dates rather than one because a pending sale and a pending dividend can settle on different
   * days while both feed the same `unsettled` figure -- a single "the settlement date" field would
   * have to silently pick an end, and a reader assuming the other one would be wrong about when
   * their cash is usable. They collapse to one displayed date when they agree, which is the common
   * case. */
  unsettled_full_date: string | null;

  account_id: string;
  account_label: string;
  broker: string;
  tax_treatment: TaxTreatment;
  verdict: CashVerdict;
  /** `null` unless `verdict` is `"derived"` or `"declared"`. The server withholds untrustworthy
   *  balances rather than flagging them, so there is no figure here to render by mistake. */
  balance: DecimalString | null;
  settled: DecimalString | null;
  unsettled: DecimalString | null;
  /** Display-ready explanation. Usually why a balance is *absent* -- but on `"declared"` it
   *  accompanies a figure that is present, saying where it came from and that it does not move. */
  reason: string | null;
  /** Lower bound on opening cash the export omits, when that is why it was withheld. */
  missing_opening_balance: DecimalString | null;
  coverage_start: string | null;
  coverage_end: string | null;

  /** When the user read a `"declared"` balance off their broker.
   *
   *  **A UI showing a declared balance must show this date too.** A derived balance is wrong only if
   *  the ledger is wrong; a declared one is a snapshot that goes stale the moment a trade settles
   *  after it was taken, and nothing in this system can detect that happening. Rendering it without
   *  its date makes a month-old figure indistinguishable from a live one. `null` on every other
   *  verdict. */
  declared_as_of: string | null;
  /** Where the figure came from, in the user's own words. */
  declared_note: string | null;
  /** What the ledger would have said, where a declaration overrode a *trustworthy* derivation. Its
   *  presence means the two disagree. `null` when the derivation was withheld -- an absence is not
   *  agreement. */
  derived_balance: DecimalString | null;
}

/**
 * One account's identity, status and all-time realized result. Mirrors
 * `backend/app/api/portfolio.py`'s `AccountSummary` field for field -- note that unlike
 * `AccountCashBalance`/`AccountPosition` elsewhere in this module, `tax_treatment` and
 * `account_type`/`status` travel together here because this type IS the account, not a
 * per-position or per-cash-balance join onto it.
 *
 * `realized_gain`/`realized_proceeds`/`disposed_cost_basis` are ALL-TIME figures aggregated from
 * `app.tax.engine` over every year the ledger covers, not just `default_tax_year` -- an account
 * closed years ago still reports its full realized history here, which is the point: this is the
 * one place the app answers "how did this account do, ever", independent of the current tax
 * page's year filter.
 */
export interface AccountSummary {
  account_id: string;
  label: string;
  broker: string;
  tax_treatment: TaxTreatment;
  /** `cash | margin | retirement`. Kept as a bare `string` (not a union) because the backend
   *  wire model declares it as `str`, matching `app.core.models.AccountType`'s wire shape rather
   *  than re-deriving a closed union this module would have to keep in sync by hand. */
  account_type: string;
  /** `open | closed`. A closed account is excluded from `PortfolioReport.positions` (see
   *  `excluded_closed_symbols`) but still appears here so its realized history stays visible. */
  status: "open" | "closed";
  realized_gain: DecimalString;
  realized_proceeds: DecimalString;
  disposed_cost_basis: DecimalString;
  /** Open positions the ledger still shows for this account -- `0` for every closed account,
   *  since a closed account's holdings are excluded from `positions` entirely. */
  position_count: number;
}

export interface PortfolioReport {
  /** The soonest any pending inflow clears, or `null`.
   *
   * `null` carries two distinguishable meanings and the UI must not merge them: nothing is pending
   * (`unsettled` is a real `0`), or the figure is withheld entirely (`unsettled` itself is `null` --
   * a declared balance read off a broker statement has no per-row settle date behind it). */
  unsettled_next_date: string | null;

  /** The date by which *all* pending inflows have cleared, or `null` on the same two conditions.
   *
   * Two dates rather than one because a pending sale and a pending dividend can settle on different
   * days while both feed the same `unsettled` figure -- a single "the settlement date" field would
   * have to silently pick an end, and a reader assuming the other one would be wrong about when
   * their cash is usable. They collapse to one displayed date when they agree, which is the common
   * case. */
  unsettled_full_date: string | null;

  as_of: string;
  generated_at: string;
  positions: Position[];
  total_cost_basis: DecimalString;
  /** Over PRICED positions only. See module docstring. */
  total_market_value: DecimalString | null;
  total_unrealized: DecimalString | null;
  total_unrealized_pct: number | null;
  priced_position_count: number;
  /** Non-empty means the totals above are PARTIAL. Never render a total without checking this. */
  unpriced_symbols: string[];

  /** Summed over accounts whose cash could be derived. `null` when none could — and, exactly like
   *  `total_market_value` against `unpriced_symbols`, a PARTIAL sum whenever
   *  `accounts_without_cash` is non-empty. Same rule: render the gap, not just the number. */
  cash_balance: DecimalString | null;
  settled_cash: DecimalString | null;
  /** Proceeds not yet settled as of `as_of` — real money, but not spendable today in a cash
   *  account, which is why it is separate rather than folded into `cash_balance`. */
  unsettled_cash: DecimalString | null;
  /** `cash_balance + total_market_value`, and `null` unless BOTH are complete. Unlike its two
   *  components, there is no honest partial version of this figure: it is read as *the* answer to
   *  "what is this worth", so the server withholds it rather than understate it. */
  total_equity: DecimalString | null;
  equity_is_complete: boolean;
  /** Accounts excluded from `cash_balance`. The cash counterpart of `unpriced_symbols`. */
  accounts_without_cash: string[];
  cash_by_account: AccountCashBalance[];

  positions_with_uncertain_basis: number;
  positions_with_unknown_fees: number;
  warnings: TaxWarning[];
  warning_groups: WarningGroup[];

  /** Every account, open and closed, label-sorted. The by-account view's account picker and its
   *  "Accounts N, N open" status-strip stat both read from this list rather than deriving account
   *  identity from `positions`/`cash_by_account`, which only ever cover a subset (open accounts
   *  with holdings or derivable cash, respectively). */
  accounts: AccountSummary[];
  open_account_count: number;
  /** Sum of `Position.day_change` over priced positions. `null` under the same condition as
   *  `total_unrealized` -- nothing priced at all -- and, like it, silently partial whenever
   *  `unpriced_symbols` is non-empty. */
  total_day_change: DecimalString | null;
  /** `total_day_change / (priced market value - total_day_change)`, i.e. relative to yesterday's
   *  close on the priced book, not today's. `null` on the same condition as `total_day_change`. */
  total_day_change_pct: number | null;
  /** Positions dropped from `positions` because their account is closed -- the count
   *  counterpart to `excluded_closed_symbols`. An instrument held at both an open and a closed
   *  account is not dropped (its surviving open-account slices still report), so this can be
   *  smaller than the closed account's own `position_count` would suggest before closure. */
  excluded_closed_positions: number;
  /** Sorted, deduped symbols behind `excluded_closed_positions` -- what the closed-account note
   *  (section 7's `portfolio.closed.note`) names. */
  excluded_closed_symbols: string[];
}

/**
 * `GET /api/portfolio/sectors` response — the full sector vocabulary the backend will accept, plus
 * the current symbol -> sector map (the same `data/sectors.toml` mapping that already backs
 * `Position.sector`). Fetched once by `Portfolio.tsx` and threaded down to every `SectorBadgeEditor`
 * instance, so the vocabulary is fetched once per page load rather than once per row.
 */
export interface SectorVocabulary {
  vocabulary: string[];
  map: Record<string, string>;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiRequestError(response.status, body || response.statusText);
  }
  return (await response.json()) as T;
}

export const portfolioApi = {
  report: (signal?: AbortSignal) =>
    requestJson<PortfolioReport>("/api/portfolio", { signal: signal ?? null }),

  /** URL of the Markdown statement. A plain href rather than a fetch, so the browser's own download
   *  handles it and the `Content-Disposition` filename from the server is honoured — same approach
   *  as `taxApi.form8949CsvUrl`. */
  statementUrl: () => "/api/portfolio/statement.md",

  /** The sector vocabulary and the current symbol -> sector map, backing `SectorBadgeEditor`'s
   *  `<select>` options. */
  sectors: (signal?: AbortSignal) =>
    requestJson<SectorVocabulary>("/api/portfolio/sectors", { signal: signal ?? null }),

  /** Reassigns one symbol's sector. The server 422s when `sector` is not in the vocabulary --
   *  surfaced to the caller as an `ApiRequestError` via `requestJson`, same as every other endpoint
   *  in this module. */
  setSector: (symbol: string, sector: string) =>
    requestJson<{ symbol: string; sector: string }>(
      `/api/portfolio/sectors/${encodeURIComponent(symbol)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sector }),
      },
    ),
};

// --- display helpers ---------------------------------------------------------------------------
// (money formatting itself now lives in `@/format/money`; re-exported here so callers already
// importing `formatMoney`/`formatMoneyOrDash` from this module keep working unchanged)

export { formatMoney, formatMoneyOrDash };

/**
 * Signed money, for a figure that will also be carried by colour (unrealized gain/loss). Colour
 * alone is not an accessible signal, so every such figure is rendered with an explicit `+`/`-`
 * rather than relying on green/red to say which way it went — the same rule `formatPercent`
 * (`api/market.ts`), `formatChange` (`api/macro.ts`) and `formatSignedRate` (`api/rules.ts`) already
 * follow for their own numeric figures. `formatMoney` itself stays unsigned because most of its call
 * sites (cost basis, proceeds, tiles with no gain/loss framing) are never colour-coded and a bare
 * `+$1,234.56` there would just be noise.
 */
export function formatSignedMoney(value: DecimalString): string {
  const trimmed = value.trim();
  const isZeroValue = /^[+-]?0*(\.0*)?$/.test(trimmed);
  if (isZeroValue || trimmed.startsWith("-")) return formatMoney(value);
  return `+${formatMoney(value)}`;
}

/** `"pos" | "neg" | ""` for the colour class, `""` for exactly zero — mirrors the `edge-value`/
 *  `ticker-change` convention elsewhere in the app (colour plus, never instead of, the explicit sign
 *  from `formatSignedMoney`). */
export function moneyTone(value: DecimalString): "pos" | "neg" | "" {
  const trimmed = value.trim();
  if (/^[+-]?0*(\.0*)?$/.test(trimmed)) return "";
  return trimmed.startsWith("-") ? "neg" : "pos";
}

/**
 * Exact sum of a list of decimal money strings, via integer cents. The list-valued counterpart to
 * `addMoney` (`api/tax.ts`): per-account subtotals need to sum an arbitrary number of per-account
 * cost-basis/market-value strings, not exactly two, and folding `addMoney` pairwise would re-parse
 * the running total on every step for no benefit. Same rule as everywhere else in this module --
 * integer cents, not `parseFloat`. Returns `"0.00"` for an empty list, which is correct: a sum over
 * zero terms is a real, known zero, not an absent figure -- callers with a genuinely absent
 * subtotal (no priced positions to sum at all) must express that as `null` themselves rather than
 * calling this with an empty array and expecting it to say so.
 */
export function sumMoney(values: DecimalString[]): DecimalString {
  // Summed at full precision and rounded ONCE, not rounded per term. The server sends per-account
  // figures unrounded -- a cost basis arrives as `4159.2533333333333` -- and truncating each to
  // cents before adding loses a third of a cent per position. Over a few dozen positions
  // that put the by-tax-treatment subtotals cents below the headline they are supposed to
  // partition: two figures on one screen that did not add up, on a page whose entire claim is that
  // they do. This is the same discipline `app.core.money.quantize_money` enforces on the server --
  // round at the output boundary, never mid-calculation.
  const SCALE = 12n;
  const UNIT = 10n ** SCALE;
  const toScaled = (v: string): bigint => {
    const trimmed = v.trim();
    const negative = trimmed.startsWith("-");
    const digits = trimmed.replace(/^[+-]/, "");
    const [wholeRaw, fracRaw = ""] = digits.split(".");
    const frac = (fracRaw + "0".repeat(Number(SCALE))).slice(0, Number(SCALE));
    const scaled = BigInt(wholeRaw || "0") * UNIT + BigInt(frac || "0");
    return negative ? -scaled : scaled;
  };

  const total = values.reduce((acc, v) => acc + toScaled(v), 0n);
  const negative = total < 0n;
  const abs = negative ? -total : total;
  // Half-up on the absolute value, i.e. ties away from zero -- matching `quantize_money`'s
  // ROUND_HALF_UP rather than JavaScript's round-half-toward-positive-infinity.
  const perCent = UNIT / 100n;
  const cents = (abs + perCent / 2n) / perCent;
  return centsToDecimalString(negative ? -cents : cents);
}

/**
 * Exact subtraction of two decimal money strings, via integer cents -- `unrealized = market value -
 * cost basis` at the per-account granularity the by-account view adds (the server only computes this
 * subtraction at the whole-position and whole-portfolio granularities).
 *
 * Rounds each operand half-up to cents via `decimalStringToCents` (`@/api/client`) before
 * subtracting -- matching `sumMoney`/`multiplyMoneyByQuantity` in this module rather than the
 * truncating `toCents` this function used to carry its own copy of. A subtraction feeding a page
 * whose stated claim is that its figures add up must not disagree with the server by a cent purely
 * because this one call site rounded a different way than every other money helper it sits beside.
 */
export function subtractMoney(a: DecimalString, b: DecimalString): DecimalString {
  return centsToDecimalString(decimalStringToCents(a) - decimalStringToCents(b));
}

function parseDecimalMagnitude(value: string): { negative: boolean; digits: bigint; scale: number } {
  const trimmed = value.trim();
  const negative = trimmed.startsWith("-");
  const unsigned = trimmed.replace(/^[+-]/, "");
  const [wholeRaw, fracRaw = ""] = unsigned.split(".");
  const whole = wholeRaw || "0";
  const digits = BigInt(`${whole}${fracRaw}` || "0");
  return { negative, digits, scale: fracRaw.length };
}

/**
 * `price × quantity`, quantized to cents with ties rounding away from zero -- exactly
 * `quantize_money(price * quantity)` in `backend/app/core/money.py`/`app/api/portfolio.py`'s
 * `_to_position`, which is how the server computes each position's *aggregate* `market_value`. There
 * is no server field for the per-account slice of that figure (the wire contract stops at `quantity`
 * and `cost_basis` per account -- see `AccountPosition`), so the by-account view derives it here from
 * `Position.price` and `AccountPosition.quantity`, and it has to use the same rounding rule the
 * backend uses or the per-account figures would not add back up to the position's own reported
 * total. `price` is always cents-precise; `quantity` can carry more decimal places than that (a
 * fractional share from a DRIP), which is why this cannot reuse `sumMoney`'s same-scale integer-cents
 * approach and instead tracks each operand's own decimal scale before rounding the product down to
 * two places at the end -- rounding anywhere in the middle is exactly the mistake `quantize_money`'s
 * own docstring warns against.
 */
export function multiplyMoneyByQuantity(price: DecimalString, quantity: DecimalString): DecimalString {
  const p = parseDecimalMagnitude(price);
  const q = parseDecimalMagnitude(quantity);
  const productDigits = p.digits * q.digits;
  const productScale = p.scale + q.scale;
  const negative = p.negative !== q.negative && productDigits !== 0n;

  const targetScale = 2;
  let cents: bigint;
  if (productScale <= targetScale) {
    cents = productDigits * 10n ** BigInt(targetScale - productScale);
  } else {
    const divisor = 10n ** BigInt(productScale - targetScale);
    const quotient = productDigits / divisor;
    const remainder = productDigits % divisor;
    // ROUND_HALF_UP, i.e. ties away from zero (Python `decimal` naming, not "toward +infinity") --
    // matches `quantize_money`'s explicit choice, made for the same reason banker's rounding is
    // rejected there: a reporting figure should round the same way regardless of which side of zero
    // it lands on.
    cents = remainder * 2n >= divisor ? quotient + 1n : quotient;
  }

  return centsToDecimalString(negative ? -cents : cents);
}

/**
 * Exact descending comparator for a money field, via `decimalStringToCents` (`@/api/client`) rather
 * than `parseFloat` — sort order is a comparison, not a sum, but there is no reason to introduce float
 * error into it when an exact comparison costs nothing extra. Rounds each side half-up to cents,
 * matching every other money helper in this module rather than the truncating comparison this
 * function used to make on its own.
 */
export function compareMoneyDesc(a: DecimalString, b: DecimalString): number {
  const diff = decimalStringToCents(b) - decimalStringToCents(a);
  return diff < 0n ? -1 : diff > 0n ? 1 : 0;
}

/**
 * Unsigned percent for a **0–1 fraction** (`weight_pct`). A position's weight in the book is a
 * magnitude, not a direction, so this never prepends `+` — `+15.2%` on a weight would read as a
 * gain that does not exist.
 *
 * The `* 100` is the whole point and was missing in the first version of this file. Every
 * fraction-valued field in this API arrives on a 0–1 scale and is scaled at the render boundary --
 * see `formatRate`/`formatSignedRate` in `api/rules.ts`, `api/report.ts`, and the drawdown
 * formatter in `api/backtest.ts`, all of which multiply. Without it a 1.15% position rendered as
 * `0.0%` and the whole book summed to `1.0%`, which looks like an empty portfolio rather than a
 * unit error. Note the deliberate contrast with `formatPercent` in `api/market.ts`, which does
 * *not* multiply because a quote's change percent arrives already on a 0–100 scale — mixing the
 * two up is exactly how this bug happened.
 */
export function formatWeightPct(value: number | null, digits = 1): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

/**
 * The span of price dates behind the market-value total, or `null` when nothing is priced.
 *
 * Derived here rather than added to the API because it is a pure function of `price_as_of` on the
 * positions the report already sends -- a second server-side field would be one more thing that can
 * disagree with the rows it summarises.
 *
 * Lives in this module rather than on a page because two pages now need the same answer and must
 * not give different ones: `pages/Portfolio.tsx` stamps its totals panel with it, and
 * `pages/Overview.tsx` stamps the headline equity tile. It was originally a private function in
 * `Portfolio.tsx`; Overview rendering a total with no mark date at all is the gap that made it
 * shared. A second copy would be a second definition of "what is this priced at".
 */
export function priceAsOfRange(
  report: PortfolioReport,
): { earliest: string; latest: string; distinct: number } | null {
  const dates = report.positions
    .map((position) => position.price_as_of)
    .filter((value): value is string => value !== null)
    .sort();
  if (dates.length === 0) return null;
  return {
    earliest: dates[0]!,
    latest: dates[dates.length - 1]!,
    distinct: new Set(dates).size,
  };
}

/**
 * Signed percent for a 0–1 fraction (`unrealized_pct`, `total_unrealized_pct`). Mirrors
 * `formatSignedRate` in `api/rules.ts`; the explicit sign is the same accessibility contract every
 * coloured figure in this app follows, so gain and loss never rest on hue alone.
 */
export function formatSignedFractionPct(value: number | null, digits = 1): string {
  if (value === null || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(digits)}%`;
}

/**
 * Re-exported so this module stays the single import site for everything the Portfolio page needs.
 * The map itself lives in `@/api/tax`, beside the `TaxWarning` type whose tokens it decodes — see
 * its docstring for why it is shared rather than duplicated per page.
 */
export { warningKindLabel } from "@/api/tax";

/**
 * Display text for `TaxTreatment`, written to state the consequence rather than just name the
 * category -- "Roth IRA" alone reads as a label, not as the fact that matters here, which is that
 * this account's unrealized gain is never taxed. The by-account view treats this as a headline next
 * to the account name, not a footnote, per its module docstring.
 */
export function taxTreatmentLabel(value: TaxTreatment | null | undefined): string {
  switch (value) {
    case "taxable":
      return t("portfolio.taxTreatment.taxable");
    case "roth_ira":
      return t("portfolio.taxTreatment.rothIra");
    case "traditional_ira":
      return t("portfolio.taxTreatment.traditionalIra");
    default:
      return t("portfolio.taxTreatment.unknown");
  }
}
