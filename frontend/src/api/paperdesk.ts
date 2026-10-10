/**
 * Typed client for the Paper Desk endpoint.
 *
 * Mirrors the backend's paper-trading contract field for field, in the same style as
 * `api/portfolio.ts` and `api/macro.ts`: money and quantity figures cross the wire as a decimal
 * *string* (see `api/client.ts`'s `DecimalString`), because a Python `Decimal` serialised as a JSON
 * number would silently round-trip through an IEEE double. Nothing here parses one of those strings
 * for arithmetic -- only for display. `formatMoney`, `sumMoney`, `subtractMoney` and
 * `multiplyMoneyByQuantity` are re-exported from `@/api/portfolio` rather than re-implemented, so
 * this page shares the exact same rounding rules as Portfolio/Tax instead of a second copy that
 * could drift.
 *
 * Three things here are easy to get wrong and are worth reading before using the types.
 *
 * **`as_of` is not "now".** It is the most recent session the desk was marked to, and `stale_days`
 * says how far behind the calendar that mark is. A page that renders `as_of` next to a clock icon
 * without saying "marked to the close of" is claiming a live price it does not have.
 *
 * **`null` is not `0`, same rule as every other money contract in this app.** `stop_price`,
 * `take_profit_pct`, `sessions_to_time_stop`, and -- at the card level -- `stop_loss_pct` and
 * `max_hold_days` are all legitimately absent: a desk's card can decline a hard stop entirely or
 * carry no hold cap at all, not merely a wide one, and `Signal.last_close` is `null` for a symbol
 * with no price at the decision session (paired with `blocked: "no price"`). Coercing any of these
 * to zero states something the desk's own rules -- or the market data -- do not.
 *
 * **`realised_pnl` and `unrealised_pnl` are never summed into one "P&L".** Realised is money the
 * desk actually captured by closing a position; unrealised is a mark against the last stored close,
 * which moves (or evaporates) the next time a price updates. Presenting their sum as a single figure
 * states a certainty about the unrealised half that the desk does not have. See the module's
 * `formatFractionPctString`-adjacent helpers below -- there is deliberately no `totalPnl` helper in
 * this file.
 *
 * **`exit_reason` is a closed union, not a free string.** Modelled with an `assertNever` guard in
 * `exitReasonLabel` for the same reason `tests/test_frontend_contract.py`'s docstring gives: a
 * backend enum gaining a member and a TypeScript union silently not following it compiles clean on
 * both sides and renders a blank label in front of a user. If the backend adds a member here, `tsc`
 * must fail until this file's switch is updated.
 */

import { ApiRequestError, type DecimalString } from "@/api/client";
import { t } from "@/i18n";
import {
  formatMoney,
  formatMoneyOrDash,
  formatSignedMoney,
  formatWeightPct,
  moneyTone,
  multiplyMoneyByQuantity,
  subtractMoney,
  sumMoney,
} from "@/api/portfolio";

export {
  formatMoney,
  formatMoneyOrDash,
  formatSignedMoney,
  formatWeightPct,
  moneyTone,
  multiplyMoneyByQuantity,
  subtractMoney,
  sumMoney,
};

// --- benchmark ----------------------------------------------------------------------------------

export interface PaperDeskBenchmark {
  symbol: string;
  return_pct: DecimalString;
  /** What the index is, in the reader's terms ("broad market", "Nasdaq-100"). Absent on the legacy
   *  singular `benchmark` field, which predates the server sending more than one. */
  label?: string | null;
}

// --- holdings -------------------------------------------------------------------------------------

export interface Holding {
  symbol: string;
  quantity: DecimalString;
  entry_date: string;
  entry_price: DecimalString;
  cost_basis: DecimalString;
  last_price: DecimalString;
  last_price_date: string;
  market_value: DecimalString;
  unrealised_pnl: DecimalString;
  return_pct: DecimalString;
  bars_held: number;
  /** 0-1 fraction of the desk's positions value, a plain JSON number (not a `DecimalString`) --
   *  matches the backend's `capital_exposure`, which is also unquoted on the wire. */
  weight: number;
  /** `null` when the desk carries no stop discipline on this holding -- never `0`, which would read
   *  as a stop sitting at the current price. */
  stop_price: DecimalString | null;
  target_price: DecimalString | null;
  /** `null` when the desk has no time-stop clock at all (no `max_hold_days`), or when the position
   *  was never actually entered under one -- distinct from `0`, which would mean "expires today". */
  sessions_to_time_stop: number | null;
}

// --- trades (closed round trips) -----------------------------------------------------------------

/** Mirrors the backend's exit-reason enum. See the module docstring: this union must be extended,
 *  with `exitReasonLabel` below, the moment the backend gains a new member -- never left to drift.
 *
 *  `rebalance_trim` is emitted by allocation and ladder cards when a drift-band rebalance sells part
 *  of a sleeve. It was missing here, and the omission took the whole Paper Desk page down: those
 *  cards only produce it over a window long enough to rebalance, so the default inception (six
 *  sessions) never reached it, and making inception user-settable turned a previously-unreachable
 *  code path into a one-click crash. */
export type ExitReason =
  | "rule"
  | "stop"
  | "target"
  | "time"
  | "open_at_end"
  | "rebalance_trim";

export interface Trade {
  symbol: string;
  entry_date: string;
  entry_price: DecimalString;
  exit_date: string;
  exit_price: DecimalString;
  quantity: DecimalString;
  exit_reason: ExitReason;
  pnl: DecimalString;
  return_pct: DecimalString;
  bars_held: number;
}

/** Display label for `ExitReason`.
 *
 *  **Exhaustive at compile time, forgiving at runtime, and the difference is the whole point.** The
 *  `never` assignment below still makes adding a union member without a case here a compile error --
 *  that guarantee is worth keeping. What changed is what happens when the *server* sends a value this
 *  build has never heard of: it now renders the raw string instead of throwing.
 *
 *  A closed union over server-supplied data is a promise the client cannot keep. `exit_reason` is
 *  typed `str` on the backend (`app.paperdesk.models.Trade`), so any new reason reaches this function
 *  regardless of what TypeScript believes. When `rebalance_trim` did exactly that, the throw
 *  propagated out of render, the route's `ErrorBoundary` caught it, and the entire Paper Desk page --
 *  every book, every figure -- was replaced by an error card over one unrecognised label in one cell
 *  of one table. That is the same failure `ErrorBoundary`'s own docstring was written about: "the
 *  figures further up that page were fine and the user could no longer see any of them."
 *
 *  Worse, the trigger was persisted server-side, so the crash survived every reload and the control
 *  that would have undone it was inside the subtree that no longer rendered. An unknown label is a
 *  cosmetic problem; an unrecoverable page is not. */
export function exitReasonLabel(reason: ExitReason): string {
  switch (reason) {
    case "rule":
      return t("paperDesk.exitReason.rule");
    case "stop":
      return t("paperDesk.exitReason.stop");
    case "target":
      return t("paperDesk.exitReason.target");
    case "time":
      return t("paperDesk.exitReason.time");
    case "open_at_end":
      return t("paperDesk.exitReason.openAtEnd");
    case "rebalance_trim":
      return t("paperDesk.exitReason.rebalanceTrim");
    default: {
      // Compile-time exhaustiveness: if a member is added to `ExitReason` without a case above,
      // this assignment fails to typecheck. It is an assignment rather than a throwing call so the
      // runtime path below stays reachable.
      const _exhaustive: never = reason;
      void _exhaustive;
      return String(reason);
    }
  }
}

// --- decisions ------------------------------------------------------------------------------------

export type DecisionAction = "enter" | "exit";

/**
 * Display label for `DecisionAction`. Exhaustive at compile time, forgiving at runtime -- the same
 * pattern as `exitReasonLabel` above, and for the same reason: the backend types `Decision.action` as
 * a plain `str`, so a value this build has never heard of can reach here regardless of what
 * `DecisionAction` claims. This function used to throw on that case via `assertNeverDecisionAction`,
 * which is exactly the failure mode `exitReasonLabel`'s docstring describes -- a throw here would
 * escape render and take down the whole Paper Desk page over one unrecognised label in one cell.
 */
export function decisionActionLabel(action: DecisionAction): string {
  switch (action) {
    case "enter":
      return t("paperDesk.decisionAction.enter");
    case "exit":
      return t("paperDesk.decisionAction.exit");
    default: {
      // Compile-time exhaustiveness: if a member is added to `DecisionAction` without a case above,
      // this assignment fails to typecheck. It is an assignment rather than a throwing call so the
      // runtime path below stays reachable.
      const _exhaustive: never = action;
      void _exhaustive;
      return String(action);
    }
  }
}

export interface Decision {
  date: string;
  symbol: string;
  action: DecisionAction;
  reason: string;
  price: DecimalString;
  quantity: DecimalString;
  notional: DecimalString;
}

// --- signals ---------------------------------------------------------------------------------------

/** Why a symbol's entry did not fire even though nothing else about it is wrong. `null` means
 *  nothing blocked it -- not that it entered; `entry_fires`/`held` say that part. */
export type BlockedReason = "book full" | "insufficient cash" | "no price";

export interface Signal {
  symbol: string;
  held: boolean;
  entry_fires: boolean;
  exit_fires: boolean;
  /** `null` when the symbol has no price at the decision session -- a young ticker with no bar yet.
   *  That case ships with `blocked: "no price"`. Render `—`, never `0` or `$0.00`. */
  last_close: DecimalString | null;
  blocked: BlockedReason | string | null;
  /** This symbol's value for the desk's `rank_by` key, or `null`.
   *
   *  A raw number in the key expression's own units -- `close / sma(200)` gives `1.07`, `rsi(14)`
   *  gives `62.4` -- not a normalised score, so it is comparable across the rows of one desk and
   *  across nothing else. `null` when the desk set no `rank_by`, and also when the key is unknown
   *  for this symbol (an indicator still in warmup, a ticker with no bar). Render `—`, never `0`. */
  rank_value: number | null;
  /** 1-based place in the queue for this desk's free slots; `null` for a symbol not in it.
   *
   *  `entry_rank === 1` is the name this desk buys next. `null` for every symbol not currently
   *  contending -- already held, or entry quiet -- and for every symbol on a desk with no
   *  `rank_by`, where fill order is the arbitrary order `universe` was typed in and numbering it
   *  would present an accident as a ranking. Read against `slots_free` to see how far down the
   *  queue the money actually reaches. */
  entry_rank: number | null;
}

// --- ladder description (kind === "ladder" only) ---------------------------------------------------

export interface LadderRungDescription {
  /** A negative fraction of one -- `-0.10` reads as "SPY 10% below its own all-time closing high". */
  drawdown_pct: DecimalString;
  /** Fraction of the whole book the leveraged sleeve targets once this rung has fired. */
  leveraged_weight_pct: DecimalString;
}

/**
 * A drawdown-ladder card's own rules, as submitted -- the `kind === "ladder"` counterpart to the
 * `entry`/`exit`/`max_positions`/`position_pct` fields a rules card carries directly on `Desk`. A
 * ladder card has no per-symbol boolean rule at all (see the backend's `app.tournament.ladder`
 * module docstring for why this is a genuinely different decision, not a dialect of the same one),
 * so rendering `entry`/`exit` prose for it would invent a rule the card does not have -- this is
 * what the page renders instead.
 */
export interface LadderDescription {
  /** The index whose drawdown from its own all-time closing high drives every decision -- SPY. */
  signal_symbol: string;
  defensive_symbol: string;
  bond_symbol: string;
  leveraged_symbol: string;
  base_defensive_weight_pct: DecimalString;
  base_bond_weight_pct: DecimalString;
  rungs: LadderRungDescription[];
  /** Session count for the bounce-confirmation moving average -- a rung fires only once the signal
   *  has closed back above this trailing average. */
  confirm_ma_sessions: number;
  /** On a new all-time high, the leveraged sleeve's weight is multiplied by this rather than sold
   *  outright. */
  ath_haircut_pct: DecimalString;
  /** Full exit once the signal closes this fraction above the high the current cycle started
   *  from. */
  recovery_gain_pct: DecimalString;
  /** Full exit this many sessions after a new high, whichever of this or `recovery_gain_pct` comes
   *  first. */
  recovery_sessions: number;
}

// --- rejections --------------------------------------------------------------------------------------

/**
 * One rule's worth of orders the broker refused this session, pre-grouped server-side so a desk that
 * refuses the same rule eight times in a row renders as one line instead of eight identical strings.
 * Groups arrive sorted by `count` descending.
 *
 * `rule` is an open string, not a closed union -- new rejection rules are a backend-only change, and
 * a switch statement here that throws on an unrecognised one would take the whole page down exactly
 * the way `exitReasonLabel`'s docstring describes. Always resolve a group's heading through
 * `deskRejectionLabel`, never `rule` directly, so a blank or missing `label` degrades to the slug
 * instead of rendering nothing.
 */
export interface DeskRejection {
  /** Machine slug, e.g. `"insufficient_cash"`. Open-ended -- do not switch on this. */
  rule: string;
  /** Human title, e.g. `"Insufficient settled cash"`. Always sent by the server, but treated as
   *  untrusted: fall back to `rule` via `deskRejectionLabel` if it arrives empty or missing. */
  label: string;
  /** Orders refused under this rule this session. */
  count: number;
  /** Distinct symbols affected, sorted, may be empty. */
  symbols: string[];
  /** One full reason sentence per refused order, newest first, capped at 20. */
  detail: string[];
}

/** `rejection.label` with a fallback to the machine slug -- the server always populates `label`, but
 *  it is still server data, and a missing or empty string here must degrade to something readable
 *  rather than rendering a blank heading. */
export function deskRejectionLabel(rejection: DeskRejection): string {
  return rejection.label || rejection.rule;
}

// --- live-priced execution -------------------------------------------------------------------------

/**
 * One fill the desk would make right now, priced against a real-time quote rather than the last
 * stored session close -- distinct from `Trade`/`Decision`, which are the desk's audited historical
 * record. Recomputed on every refresh: a fill present in this list this second may not still qualify
 * the next time the page asks, because the live quote itself moved.
 *
 * `side` is an open string (`"buy"` | `"sell"` today), deliberately NOT a closed union. See
 * `exitReasonLabel`'s docstring above for the concrete failure a closed union over server-supplied
 * data has already caused in this exact page -- do not repeat that pattern here.
 */
export interface LiveFill {
  symbol: string;
  side: string;
  quantity: DecimalString;
  /** The price this fill actually executes at, slippage applied. */
  price: DecimalString;
  /** The unslipped live quote this fill was priced from -- compare against `price` to see the
   *  slippage applied. */
  quote_price: DecimalString;
  /** ISO-8601 UTC timestamp of the quote `quote_price` was read from. */
  quote_ts: string;
  notional: DecimalString;
}

// --- after-tax / wash-sale summary (kind === "rules", taxable book only) -----------------------------

/**
 * One triggered wash sale (IRC 1091), in the shape the desk needs to display it -- a thin projection
 * of the backend's own `app.tax.models.WashSaleEvent`. See `Desk.tax`'s own docstring for exactly
 * when a desk carries any of these at all.
 */
export interface WashSaleFlag {
  symbol: string;
  /** The date the disallowed loss was realised. */
  loss_date: string;
  /** Earliest acquisition date among the matched replacement lots -- the date shares were actually
   *  bought back that caused the disallowance. `null` only if a replacement lot the event references
   *  cannot be found in the ledger, which does not happen for a flag reaching this page. */
  repurchase_date: string | null;
  quantity_sold: DecimalString;
  quantity_replaced: DecimalString;
  /** Positive. Deferred into the replacement lot's basis (IRC 1091) -- never the permanent, IRA-only
   *  kind, since a paper account is always a taxable cash account. See `permanently_disallowed`. */
  disallowed_amount: DecimalString;
  /** Always `false` for a paper-desk fill -- kept on the shape for parity with the backend's real
   *  wash-sale event, which can carry `true` for a real IRA import. */
  permanently_disallowed: boolean;
  disposal_id: string;
  event_id: string;
}

/**
 * After-tax realised results for one rules desk's closed trades, over one date range -- computed by
 * the repo's real cost-basis / wash-sale / holding-period tax engine
 * (`app.paper.papertax.summarize_paper_tax`) from fills synthesised out of the desk's own trade log.
 * See `Desk.tax`'s own docstring for exactly when a desk carries this at all, and for the one
 * deliberate gap: the synthesised fills carry zero fees, so `tax_owed`/`after_tax_realized_gain`
 * omit the paper broker's own per-leg regulatory fees (a few cents per sell) -- restated on the
 * book's own `notes` whenever any desk in it carries a `tax` block.
 */
export interface PaperTaxSummary {
  account_id: string;
  start: string;
  end: string;
  short_term_gain: DecimalString;
  long_term_gain: DecimalString;
  /** `short_term_gain + long_term_gain`, before tax. */
  net_realized_gain: DecimalString;
  /** Ordinary (deferred) wash-sale disallowance over the range -- the sum behind `wash_sales` below,
   *  not a second independent figure. */
  disallowed_loss_total: DecimalString;
  /** Always zero for a paper desk -- see `WashSaleFlag.permanently_disallowed`. */
  permanently_disallowed_total: DecimalString;
  /** Every triggered wash sale whose loss date falls in `[start, end]`. */
  wash_sales: WashSaleFlag[];
  short_term_rate: DecimalString;
  long_term_rate: DecimalString;
  /** `"explicit"` when either rate differs from the statutory default; `"statutory_upper_bound"` when
   *  both equal it (the ordinary case -- this app does not ask a user to disclose their real
   *  bracket); `"user_configured"` when both came from a configured setting. Open string, not a
   *  closed union -- render as-is rather than switching on it. */
  rate_basis: string;
  /** `max(short_term_gain, 0) * short_term_rate + max(long_term_gain, 0) * long_term_rate`. A net
   *  loss on either side contributes zero here, never a rebate. */
  tax_owed: DecimalString;
  /** `net_realized_gain - tax_owed` -- the one figure the desk's other panels do not show. */
  after_tax_realized_gain: DecimalString;
}

// --- desk ------------------------------------------------------------------------------------------

/** `"rules"` is every desk this application traded before the drawdown ladder: a per-symbol universe
 *  with a boolean entry/exit rule. `"ladder"` is a portfolio-weight rotation driven by one shared
 *  drawdown signal, with no per-symbol rule at all -- see `Desk.ladder`. */
/** One order the autopilot's book has staged but has not yet filled.
 *
 *  Deliberately not a `Signal`. A `Signal` is a rule re-read against the newest close on every
 *  request and changes when the bars change; a staged order is a decision already written down on
 *  its own `decision_date` and cannot be re-derived. "The strategy would buy this" and "the desk has
 *  already committed to buying this at the next open" are different claims and get different shapes.
 *
 *  `notional` is a dollar amount, never a share count: sizing happens at fill time against the
 *  decision date's close, so a pending order has no quantity and none is invented. */
export interface AutopilotOrder {
  symbol: string;
  /** `"buy"` or `"sell"`. Buys are staged by the workflow's entry plan; sells by the card's own
   *  mechanical exits (see `AutopilotDescription.exits`), so both appear here. */
  side: string;
  notional: DecimalString;
  decision_date: string;
  /** The session this fills at the open of. May already be in the past when the daily step has not
   *  run; an order is never silently expired. */
  fill_date: string;
  /** The regime label the run staged this under, or `""` when it recorded none. */
  regime: string;
}

/** The autopilot seat's provenance — the `kind === "autopilot"` counterpart to `LadderDescription`,
 *  present if and only if `Desk.kind === "autopilot"`.
 *
 *  Its own block rather than reinterpreted rule fields, for the reason the ladder has one: this desk
 *  has no per-symbol entry/exit expression to render. What it has is a provenance — which study arm,
 *  which screened universe, which card the regime call selected, and what the last run did. */
export interface AutopilotDescription {
  /** Which of the four study arms this seat trades. */
  arm: string;
  /** `"screen"` or `"card"`. A book is identified by the pair `(arm, universe_source)`, never by
   *  `arm` alone. */
  universe_source: string;
  current_card_id: string;
  /** When that card was adopted — and, for a book that has never switched, this seat's own
   *  inception, which is not the desk's. */
  card_adopted_date: string;
  orders_total: number;
  orders_filled: number;
  orders_pending: number;
  orders_rejected: number;
  last_run_id: string | null;
  /** `"succeeded"`, `"failed"`, `"cancelled"`, or `null` when no run has been recorded. */
  last_run_state: string | null;
  /** ISO-8601 UTC instant, not a session date. Never compare it to `as_of`. */
  last_run_at: string | null;
  /** One sentence on what the last run actually did ("no entry candidates fired").
   *
   *  **Render this whenever the seat is flat.** A seat showing its full starting cash is either a
   *  strategy that found nothing or a pipeline that is broken, and nothing else on the desk tells
   *  those apart. */
  last_run_outcome: string | null;
  /** How this seat closes a position, in the reader's words — the one fact that decides how to read
   *  its return, so it is always surfaced on the panel. Two shapes: `"none"` means nothing ever sells
   *  (buy and hold forever, the card's stop and target inert); any other value is a sentence naming
   *  the exit rules actually in force ("12% stop, 120-session hold cap, and exit rule …"), which
   *  `app.workflow.exits` applies once a session and fills at the next open. Render it verbatim; never
   *  print a bare `"none"` on its own. */
  exits: string;
}

export type DeskKind = "rules" | "ladder" | "allocation" | "autopilot";

export interface Desk {
  agent_id: string;
  display_name: string;
  discipline: string;
  thesis: string;
  /** Defaults to `"rules"` server-side; always present on the wire. */
  kind: DeskKind;
  universe: string[];
  /** `null` only for `kind === "ladder"` -- see `Desk.ladder` for what that card shape reports
   *  instead. Always a string for `kind === "rules"`. */
  entry: string | null;
  /** Same `null`-only-for-a-ladder-card rule as `entry`. */
  exit: string | null;
  /** `null` when this desk's card declines a hard stop entirely -- distinct from a stop that is
   *  merely wide. Never coerce to `0`, which would state the desk stops out at the current price. */
  stop_loss_pct: DecimalString | null;
  /** `null` when this desk has no take-profit rule at all -- never `0`. */
  take_profit_pct: DecimalString | null;
  /** `null` when this desk's card carries no hold cap at all -- a position may sit open
   *  indefinitely. Distinct from `0`, which would mean "close today." */
  max_hold_days: number | null;
  /** `null` only for `kind === "ladder"`, which has no per-position slot count. */
  max_positions: number | null;
  /** `null` only for `kind === "ladder"`, which sizes every sleeve as a weight of the whole book,
   *  not a fixed fraction per position. */
  position_pct: DecimalString | null;
  /** The card's ranking-key expression verbatim (`"close / sma(200)"`), or `null` if it set none.
   *
   *  Needed to label `Signal.rank_value`: a column of bare numbers cannot say what was measured.
   *  `null` also means `Signal.entry_rank` is `null` throughout and this desk fills in `universe`
   *  order. */
  rank_by: string | null;
  /** Present if and only if `kind === "ladder"`. */
  ladder: LadderDescription | null;
  /** Present if and only if `kind === "autopilot"`. Optional for the same server-version reason as
   *  `Book.benchmarks` — a server predating this seat sends no key at all. Treat `undefined` and
   *  `null` identically. */
  autopilot?: AutopilotDescription | null;
  /** Orders this desk has staged but not yet filled. Only ever non-empty for
   *  `kind === "autopilot"`; every other kind sizes and fills within one replayed session and has
   *  nothing in flight. Optional for the same server-version reason as `autopilot`. */
  staged_orders?: AutopilotOrder[];
  starting_equity: DecimalString;
  cash: DecimalString;
  positions_value: DecimalString;
  equity: DecimalString;
  total_return: DecimalString;
  excess_return: DecimalString;
  max_drawdown: DecimalString;
  /** 0-1 fraction, a plain JSON number -- unlike almost everything else on this desk, this one is
   *  NOT a `DecimalString` on the wire. Formatted with `formatWeightPct`, not the fraction-string
   *  helpers below. */
  capital_exposure: number;
  /** Money the desk actually captured by closing a position. Never summed with `unrealised_pnl` --
   *  see the module docstring. */
  realised_pnl: DecimalString;
  /** A mark against the last stored close, not money taken. Always labelled as a mark in the UI. */
  unrealised_pnl: DecimalString;
  open_positions: number;
  slots_free: number;
  holdings: Holding[];
  trades: Trade[];
  decisions: Decision[];
  signals: Signal[];
  /** Orders the broker refused this session, grouped by rule. Non-empty means the desk did not run
   *  exactly as written this session -- always rendered as a visible summary, never folded away in a
   *  footnote. See `DeskRejection`. */
  rejections: DeskRejection[];
  /** Total refused orders across every group in `rejections` -- the number this desk's own headline
   *  quotes, since `rejections.length` is a group count, not an order count. */
  rejection_count: number;
  /** What this desk would trade RIGHT NOW against a real-time quote -- a live-priced projection,
   *  recomputed on every refresh, and never part of the desk's audited historical record the way
   *  `trades`/`decisions` are. Empty when the feature is off or nothing qualifies this instant. */
  live_fills: LiveFill[];
  /** Orders the broker would refuse against the live quote right now, grouped the same way as
   *  `rejections` -- rendered through the same `RejectionGroup` component. */
  live_rejections: DeskRejection[];
  /** ISO-8601 UTC timestamp the live figures above were computed against. `null` means the live
   *  feature is off for this desk (or this server build) -- render nothing, not an empty panel. */
  live_as_of: string | null;
  /** After-tax / wash-sale summary for this desk's closed trades. Populated if and only if
   *  `kind === "rules"` **and** this desk's book is taxable (`Funding.tax_treatment === "taxable"`) --
   *  `null` for every ladder/allocation desk and for every Roth desk regardless of kind. Also `null`
   *  on a genuine backend computation failure, which is degraded server-side rather than ever failing
   *  the desk (or the page) -- see `app.paperdesk.desk._build_desk`'s own docstring.
   *
   *  Optional for the same server-version reason as `Book.benchmarks`/`Book.notes` above: a server
   *  predating this feature sends no `tax` key at all, and a fixture or a page built against that
   *  older contract must still compile and render. Treat `undefined` and `null` identically -- both
   *  mean "no after-tax panel for this desk". */
  tax?: PaperTaxSummary | null;
  /** Where this seat came from (`SeatProvenance`). Optional/`null` for the same server-version reason
   *  as `tax` above: a server predating this feature sends no `provenance` key, and a fixture built
   *  against the older contract must still render. Treat `undefined`/`null` as "origin unknown, show
   *  nothing". */
  provenance?: SeatProvenance | null;
}

/** Where a desk seat came from -- mirrors `app.paperdesk.models.SeatProvenance`. `"promoted"` carries
 *  the latest evolution `generation` the genome cleared and links to the Loop view; `"owner"` is a
 *  hand-authored / operator-rostered seat, no generation and no link. */
export interface SeatProvenance {
  source: "promoted" | "owner";
  generation: number | null;
}

export type Purpose = "savings" | "trading" | "roth";

/** How one book's money arrives, echoed from the server's own `PurposeSpec`.
 *
 *  `horizon_years_max` is `null` for `trading` and that is a decision, not a missing value: a
 *  purpose whose horizon is unstated is not the same as one whose horizon is short. Render
 *  "unbounded", never a default. */
export interface Funding {
  purpose: Purpose;
  shape: "lump_sum" | "monthly_contribution" | "annual_contribution";
  seed: DecimalString;
  contribution: DecimalString;
  horizon_years_min: number | null;
  horizon_years_max: number | null;
  tax_treatment: string;
}

/** One purpose's book: its funding, its own benchmark, and the desks trading it.
 *
 *  Three books exist because a book funded monthly and a book funded once are not being asked the
 *  same question, and one list cannot answer both. A book with an empty `desks` array is a real,
 *  renderable state -- a purpose can be defined and funded before a card exists for it -- and must
 *  render as "no cards seated yet" rather than be hidden, because a hidden book reads as a purpose
 *  that does not exist. */
export interface Book {
  purpose: Purpose;
  label: string;
  funding: Funding;
  /** The book's opening capital, and the denominator every equity figure on its desks is measured
   *  against. Not always `funding.seed`: a Roth's seed is zero because its money arrives annually,
   *  so it opens with its first contribution instead. */
  starting_cash: DecimalString;
  benchmark: PaperDeskBenchmark;
  /** Every benchmark this book is measured against, its own primary first.
   *
   *  Per book, because a book measured against the wrong index is measured against the wrong thing:
   *  `trading` is scored against SPY while `savings` and `roth` are scored against a 60/40 SPY/AGG
   *  blend. Optional for the same server-version reason as before. */
  benchmarks?: PaperDeskBenchmark[];
  /** Notes true of this book only -- including, for the two contribution-funded purposes, that the
   *  desk trades a static book and does not model their contributions. */
  notes?: string[];
  desks: Desk[];
}

/** What one press of the page's fetch button actually pulled from the market provider.
 *
 *  Only `paperdeskApi.refresh()` ever returns a populated one; `state()`, `setInception()` and
 *  `resetInception()` all leave it `null` because none of them touch the network. `null` is
 *  therefore "this response fetched nothing", never "the fetch reported nothing".
 *
 *  **`advanced` and `unchanged` are separate and must stay separate on screen.** "Forty symbols
 *  answered and none gained a session" is the ordinary weekend result and is not a failure; folding
 *  it in with `advanced` under one "succeeded" count would make it indistinguishable from forty
 *  symbols that genuinely moved, which is the single question a reader presses the button to answer.
 *
 *  **`rows_merged` is not a count of new sessions and must never be rendered as one.** The backend
 *  re-requests a short overlap behind each symbol's newest stored bar on every call, so this is
 *  non-zero on a second press that stored nothing new. `advanced` is the "did anything change"
 *  number; this one only says how much data moved.
 *
 *  Absent (`undefined`) on a server predating this field, for the same reason `Book.benchmarks` is
 *  optional -- callers must treat `undefined` and `null` identically. */
export interface FetchSummary {
  /** Symbols asked for: every card on every book's roster, plus the benchmarks. Always equals
   *  `advanced + unchanged + failed`. */
  requested: number;
  /** Symbols whose newest stored session moved forward as a result of this fetch. */
  advanced: number;
  /** Symbols that answered without gaining a session. Not a failure. */
  unchanged: number;
  /** Symbols whose fetch raised -- an outage, a rate limit, an unknown ticker. */
  failed: number;
  /** Total bars returned and merged across every symbol, re-sent overlap included. */
  rows_merged: number;
  /** `"SYMBOL: reason"` per failure, in fetch order. Detail behind `failed`, not a substitute. */
  failures: string[];
  /** ISO 8601 timestamps, UTC. */
  started_at: string;
  finished_at: string;
  /** Wall time of the whole sweep, seconds -- computed server-side so no caller differences two
   *  timestamps and gets the zone handling wrong. */
  duration_seconds: number;
  /** The benchmark's newest stored session either side of the fetch, `YYYY-MM-DD`, or `null` when
   *  the benchmark has no stored bars.
   *
   *  These are what say whether the fetch moved the page's own *mark*, which is a stricter question
   *  than whether any individual symbol advanced: the mark follows the primary benchmark alone, so
   *  a handful of constituents can gain a session while `as_of` stays put. Both sides of the
   *  comparison travel on the wire rather than being inferred from `as_of` alone. */
  latest_bar_before: string | null;
  latest_bar_after: string | null;
}

export interface PaperDeskState {
  /** The window every book is actually traded over -- `inception_default` unless an override is in
   *  effect (`inception_is_custom`). Changing it (`paperdeskApi.setInception`) re-runs every agent
   *  from that date; it does not fetch new market data and does not change which strategies are
   *  seated. */
  inception: string;
  /** The application's built-in default inception, regardless of whether an override is in effect --
   *  what `paperdeskApi.resetInception` returns the desk to.
   *
   *  Optional for the same server-version reason as `Book.benchmarks` above: a server predating the
   *  inception picker sends none of these six fields, and a page (or a fixture in a test this module
   *  does not own, e.g. `Overview.test.tsx`) built against that older contract must still compile and
   *  render. `PaperDesk.tsx` treats an absent value as "the picker/warning has nothing to show". */
  inception_default: string;
  /** True when `inception` differs from `inception_default` because a reader set an override. Absent
   *  on an older server -- treated as `false`. */
  inception_is_custom: boolean;
  /** The strategy design cutoff date. A session at or before this date is in-sample for the cards
   *  trading it -- see `in_sample_sessions`. */
  design_cutoff: string;
  /** How many sessions in the current `inception` window fall at or before `design_cutoff`. Greater
   *  than zero means the headline return blends fitted (in-sample) and unfitted (forward) periods,
   *  which is the specific hazard `PaperDesk.tsx`'s in-sample warning exists to surface -- see that
   *  page's module docstring. Absent (or `0`) on an older server means the warning does not render. */
  in_sample_sessions: number;
  /** The earliest date the inception picker will accept -- the first stored benchmark bar. */
  earliest_inception: string;
  /** The latest date the inception picker will accept -- the last date still yielding at least one
   *  traded session. */
  latest_inception: string;
  /** The date the figures on this page are marked to. Not "now" -- see the module docstring. */
  as_of: string;
  latest_bar: string;
  /** How many calendar days behind `latest_bar` (or "today") the mark in `as_of` is. */
  stale_days: number;
  first_session: string;
  sessions: number;
  /** Notes about the desk as a whole. A note true of one book only lives on that `Book`. */
  notes: string[];
  /** One per purpose, in `savings`, `trading`, `roth` order.
   *
   *  This replaced flat `starting_cash`/`benchmark`/`benchmarks`/`desks` fields. Those described one
   *  book and there are three; keeping them alongside would have meant either a fourth answer that
   *  is none of the three, or silently privileging one purpose as "the" desk. */
  books: Book[];
  /** What the request that produced this state pulled from the market provider, or `null`/absent
   *  when it pulled nothing. Only `paperdeskApi.refresh()` ever populates it. */
  fetch?: FetchSummary | null;
}

// --- requests ---------------------------------------------------------------------------------------

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiRequestError(response.status, detailOf(body) || response.statusText);
  }
  return (await response.json()) as T;
}

/**
 * FastAPI wraps an `HTTPException` message in `{"detail": ...}` -- unwrapping it here is what lets
 * a rejected inception date's specific reason ("no stored benchmark bar before 2019-03-04") reach
 * the screen instead of a raw JSON blob. The same helper as `@/api/imports`' `detailOf`; kept as its
 * own private copy per this module's stated preference for one clear implementation per contract
 * rather than a shared cross-module utility for a three-line parse.
 */
function detailOf(body: string): string {
  if (!body) return "";
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const detail = (parsed as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      return JSON.stringify(detail);
    }
  } catch {
    // Not JSON. The raw body is still the best thing to show.
  }
  return body;
}

export const paperdeskApi = {
  state: (signal?: AbortSignal) =>
    requestJson<PaperDeskState>("/api/paperdesk/state", { signal: signal ?? null }),

  /** Fetches fresh daily bars for every symbol the desk prices, then recomputes every book and
   *  returns the same shape as `state()` with `fetch` populated.
   *
   *  **`?fetch=true` is sent explicitly and is not the server's default.** Without it the endpoint
   *  only busts its caches and recomputes off bars it already had -- which produces the identical
   *  figures, including the identical `stale_days`, and is exactly what this button used to do.
   *  The server keeps the no-fetch behaviour as its default so that callers who want a pure
   *  recompute (this repository's own backend tests among them) do not silently start reaching for
   *  the network; the page opts in because the page is where a person presses the button.
   *
   *  This is slow on purpose -- roughly forty paced provider round trips -- so every caller must
   *  render a busy state rather than assume it returns promptly. A provider failure on individual
   *  symbols does not reject: it comes back in `fetch.failures` alongside a recompute that ran
   *  anyway. Only an unreachable API or a genuinely broken recompute rejects here. */
  refresh: (signal?: AbortSignal) =>
    requestJson<PaperDeskState>("/api/paperdesk/refresh?fetch=true", {
      method: "POST",
      signal: signal ?? null,
    }),

  /** Sets an inception override and returns the full recomputed state -- one round trip, no
   *  follow-up `state()` call needed. A rejected date (outside `[earliest_inception,
   *  latest_inception]`, or otherwise unusable) comes back as a `422` whose body names the specific
   *  reason; `requestJson`'s `detailOf` unwrapping surfaces it verbatim rather than a generic
   *  failure. */
  setInception: (inception: string, signal?: AbortSignal) =>
    requestJson<PaperDeskState>("/api/paperdesk/inception", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ inception }),
      signal: signal ?? null,
    }),

  /** Clears an inception override, returning the desk to `inception_default`, and returns the full
   *  recomputed state. */
  resetInception: (signal?: AbortSignal) =>
    requestJson<PaperDeskState>("/api/paperdesk/inception", {
      method: "DELETE",
      signal: signal ?? null,
    }),
};

// --- display helpers ----------------------------------------------------------------------------
//
// Every fraction-valued figure in this contract EXCEPT `capital_exposure`/`weight` arrives as a
// `DecimalString`, not a JSON `number` (see `total_return`, `excess_return`, `max_drawdown`,
// `return_pct`, `stop_loss_pct`, `take_profit_pct`, `position_pct`, `benchmark.return_pct`). These
// parse the string with `Number(...)` for DISPLAY ONLY -- rendering a rate to two decimal places
// does not carry the same precision risk `sumMoney`'s docstring warns about for money, since nothing
// here sums or compares two of these values against each other; it only ever prints one. Reaching
// for `formatWeightPct`/`formatSignedFractionPct` from `api/portfolio.ts` at these call sites would
// not compile (they take `number | null`, and these are strings), which is why this module carries
// its own small pair of string-typed equivalents rather than force-casting at every call site.

function parseFraction(value: DecimalString | null | undefined): number | null {
  if (value == null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Unsigned percent for a `DecimalString` 0-1 fraction (`stop_loss_pct`, `take_profit_pct`,
 *  `position_pct`, `max_drawdown`). `—` on `null`, never `0%`. */
export function formatFractionPctString(value: DecimalString | null | undefined, digits = 2): string {
  const parsed = parseFraction(value);
  if (parsed === null) return "—";
  return `${(parsed * 100).toFixed(digits)}%`;
}

/** Signed percent for a `DecimalString` 0-1 fraction (`total_return`, `excess_return`, `return_pct`,
 *  `benchmark.return_pct`) -- the explicit `+`/`-` is the same accessibility contract every coloured
 *  figure in this app follows (see `formatSignedMoney`'s docstring in `api/portfolio.ts`). */
export function formatSignedFractionPctString(
  value: DecimalString | null | undefined,
  digits = 2,
): string {
  const parsed = parseFraction(value);
  if (parsed === null) return "—";
  const sign = parsed > 0 ? "+" : "";
  return `${sign}${(parsed * 100).toFixed(digits)}%`;
}

/**
 * `Signal.rank_value` for display -- the one figure in this contract that arrives as a JSON `number`
 * rather than a `DecimalString`, because it is a ranking key in the expression's own units and not
 * money or a rate (see `Signal.rank_value`).
 *
 * Four decimals because the keys people actually write span orders of magnitude -- `close / sma(200)`
 * lands near `1.0` and separates two names in the third decimal, while `rsi(14)` lands near `60` --
 * and rounding harder would print two adjacent rows as an identical number while the desk ranked one
 * above the other. That is the specific way a ranking display can lie: not by being wrong, but by
 * hiding the difference it is there to show. `—` on `null`, never `0`, which is a real key value.
 */
export function formatRankValue(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toFixed(4);
}

/**
 * An ISO-8601 UTC instant, rendered readably and still unambiguously — `"2026-09-01 07:20 UTC"`.
 *
 * For a real-time *moment* only (`AutopilotDescription.last_run_at`, `Desk.live_as_of`), never for a
 * session date. Those are plain `YYYY-MM-DD` strings and are printed as-is everywhere on this page,
 * because a session date has no clock and putting one on it would invent a precision the figure does
 * not have.
 *
 * **Kept in UTC rather than converted to the reader's zone**, which is the opposite of what
 * `api/calendar.ts` and `api/macro.ts` do for their date-only values, and deliberately so. Those
 * convert *because* a bare date has no zone and `new Date("2026-08-07").toLocaleDateString()` prints
 * the 6th anywhere west of Greenwich. This value is a real instant that already carries its zone, and
 * the thing a reader compares it against — the run's own record on the Agent Workflow desk, the
 * server's logs — is stamped in UTC too. Silently shifting it would make two views of one run appear
 * to disagree by the reader's offset.
 *
 * Trims the microseconds the backend sends: they are audit precision, and six digits of them between
 * a reader and the minute they wanted is the reason this helper exists. Returns `"—"` for a null, and
 * returns the raw string unchanged for anything unparseable — a value we cannot read is still shown,
 * never swallowed.
 */
export function formatInstant(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const iso = parsed.toISOString();
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
}

/** `"pos" | "neg" | ""` for the colour class on a `DecimalString` fraction, mirroring `moneyTone`. */
export function fractionStringTone(value: DecimalString | null | undefined): "pos" | "neg" | "" {
  const parsed = parseFraction(value);
  if (parsed === null || parsed === 0) return "";
  return parsed > 0 ? "pos" : "neg";
}
