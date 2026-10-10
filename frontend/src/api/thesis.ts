/**
 * Typed client for the thesis loop.
 *
 * Mirrors `backend/app/thesis/models.py` and `backend/app/api/thesis.py` field for field. The
 * rendering rules in `api/backtest.ts` and `api/report.ts` hold verbatim and are not restated —
 * in particular "never show a hit rate without its baseline" and "a guard that did not run is a
 * failure" both apply to `Evidence`, which is scored by the same engines.
 *
 * `backend/app/thesis/__init__.py` names the hazard this whole surface exists to contain: a loop
 * that proposes theses and tests them until one looks good is a p-hacking machine by default, and
 * three properties make it worse than ordinary multiple testing — the trial count is invisible
 * unless shown, the generator can see the data, and iteration is unbounded unless capped. Several
 * things below are specific to *rendering* that containment rather than computing it.
 *
 * **`inconclusive` is a normal result, not a failure.** It is the expected outcome for most theses
 * on most tickers — underpowered, not wrong. Do not style a `Verdict` of `"inconclusive"` the way an
 * error or an empty state would be styled; it belongs next to `"survived"` and `"rejected"` as a
 * third, equally legitimate answer. See `verdictLabel`.
 *
 * **The trial count travels with every verdict.** `Evidence.trials_at_evaluation` is the size of
 * the ledger family `q_value` was corrected over at the moment it was computed, and a q-value shown
 * without it is a number with no way to judge how much correction it already absorbed. Never render
 * `q_value` in a component that does not also render `trials_at_evaluation` next to it.
 *
 * **A burned holdout must be visually loud.** `HoldoutStatus.burned` means the one out-of-sample
 * guarantee this ticker will ever get is gone — a second look happened, and every number the holdout
 * reports from here on is in-sample wearing a different name. This is not a neutral state change
 * like `"spent"`; render it as a problem. See `holdoutSeverity`.
 *
 * **`budget_exhausted` and `catalogue_exhausted` are reportable outcomes, not error states.** "No
 * thesis survived twelve attempts" is real information about the ticker — the loop worked correctly
 * and found nothing. "The catalogue ran out before the budget did" is real information too, but
 * about the author's catalogue rather than the ticker, and the two must read as different sentences
 * — see `outcomeLabel`. Neither gets a spinner-then-failure treatment; both render the way
 * `"inconclusive"` is rendered, as a normal answer.
 */

import { ApiRequestError } from "@/api/client";
import type { Distribution, MarketWarning } from "@/api/backtest";
import type { Interval } from "@/api/market";
import type { FactBundle, StrategyResult } from "@/api/report";
import { t } from "@/i18n";

export type { Distribution, FactBundle, Interval, MarketWarning, StrategyResult };

/** The iteration budget a run may spend before it stops, whatever it has found, when the caller
 * does not override it. Matches `DEFAULT_ITERATION_BUDGET` in the backend contract. */
export const DEFAULT_ITERATION_BUDGET = 12;

/** `POST /run`'s hard ceiling on `budget`. Twice the default, and still a number someone chose. */
export const MAX_ITERATION_BUDGET = 24;

// --- thesis -------------------------------------------------------------

/** The predicted direction of the effect, declared before testing. An effect that comes out
 * significant in the *opposite* direction refutes the thesis rather than confirming it. */
export type Direction = "up" | "down";

/** Where a registered thesis sits in its lifecycle. `"abandoned"` still counts as a trial — a run
 * that discards a weak thesis mid-iteration does not get to forget it happened. */
export type ThesisStatus =
  | "registered"
  | "in_sample_tested"
  | "holdout_tested"
  | "abandoned";

/** What the evidence supports. Three values, and the third is not a failure — see the module
 * docstring and `verdictLabel`. */
export type Verdict = "survived" | "rejected" | "inconclusive";

export interface Thesis {
  symbol: string;
  interval: Interval;
  /** Plain-language claim. Rewording it registers a new thesis — see the backend contract. */
  hypothesis: string;
  /** Rule DSL expression. */
  entry: string;
  exit: string | null;
  max_holding_bars: number | null;
  stop_loss_pct: number | null;
  /** Forward-return horizon the prediction is about, in bars. */
  horizon: number;
  direction: Direction;
  /** What would refute this, written before any test ran. Always non-empty. */
  falsifies_if: string;
  /** Why this was proposed — structure, mechanics, priors. Never "because the chart looked like
   * this", which would make the thesis a description of the sample. */
  rationale: string;
}

/** One statistical read on a thesis. Computes nothing on its own — every figure here came from the
 * same forward-return and binomial-test engines the backtest workbench uses. */
export interface Evidence {
  horizon: number;
  hit_rate: number | null;
  baseline_hit_rate: number | null;
  median_return: number | null;
  baseline_median_return: number | null;
  distribution: Distribution;
  sample_size: number;
  independent_sample_size: number;
  /** Two-sided exact binomial of the independent trigger count against the baseline hit rate. */
  p_value: number | null;
  /** Benjamini–Hochberg against the ticker's *whole* ledger, not this run. Meaningless without
   * `trials_at_evaluation` — see the module docstring. */
  q_value: number | null;
  /** Size of the ledger family `q_value` was corrected over. Required reading alongside it. */
  trials_at_evaluation: number;
}

export interface ThesisRecord {
  thesis_hash: string;
  thesis: Thesis;
  registered_at: string;
  status: ThesisStatus;
  verdict: Verdict | null;
  in_sample: Evidence | null;
  holdout: Evidence | null;
  run_id: string | null;
  notes: string;
}

// --- ledger ---------------------------------------------------------------

/** The trial family a q-value was corrected over. Zeros for a ticker with no history — never
 * absent, because "no trials yet" is itself a fact about the denominator. */
export interface LedgerStats {
  symbol: string;
  total_trials: number;
  survived: number;
  rejected: number;
  inconclusive: number;
  abandoned: number;
  first_registered: string | null;
  last_registered: string | null;
}

// --- holdout ----------------------------------------------------------------

/** Whether a ticker's holdout is still usable. `"burned"` means a second evaluation was attempted
 * and the out-of-sample guarantee is gone for this ticker — see `holdoutSeverity`. */
export type HoldoutStatus = "unused" | "spent" | "burned";

export interface HoldoutState {
  symbol: string;
  /** Last in-sample session, `YYYY-MM-DD`. Everything after it is holdout. */
  split_date: string;
  status: HoldoutStatus;
  evaluated_at: string | null;
  evaluated_thesis_hash: string | null;
  /** Every evaluation attempt, including refused ones — the count is the evidence a holdout was
   * reused, even before reading `status`. */
  attempts: number;
}

// --- strategy card ------------------------------------------------------------

export interface RegimeSlice {
  /** `"high_volatility"`, `"low_volatility"`, `"uptrend"`, `"downtrend"`. */
  label: string;
  bars: number;
  evidence: Evidence | null;
}

/** Which rate source produced `TaxImpact.after_tax_return`. `"user_configured"` means both rates
 * came from the user's own settings; `"statutory_upper_bound"` means at least one fell back to the
 * top federal bracket, so the figure is a ceiling most filers fall under, not a personal number.
 * Mirrors `backend/app/thesis/models.py`'s `TaxRateBasis`. */
export type TaxRateBasis = "user_configured" | "statutory_upper_bound";

/** What the strategy would have cost in tax. `unavailable_reason` explains an absence rather than
 * leaving the caller to guess why every field is `null`. */
export interface TaxImpact {
  gross_return: number | null;
  after_tax_return: number | null;
  short_term_gains: number | null;
  long_term_gains: number | null;
  wash_sales_triggered: number;
  disallowed_loss: number | null;
  /** Which of the two rate sources produced `after_tax_return` — `null` exactly when
   * `unavailable_reason` is set. Required reading alongside `after_tax_return`: the same figure
   * means "your actual after-tax cost" under `"user_configured"` and "a ceiling most filers fall
   * under" under `"statutory_upper_bound"`. */
  rate_basis: TaxRateBasis | null;
  /** The rate actually multiplied against short-term gains to produce `after_tax_return`. */
  short_term_rate_applied: number | null;
  /** Same as `short_term_rate_applied`, for the long-term side. */
  long_term_rate_applied: number | null;
  /** Whether the ticker is also held in an IRA — a loss taken taxable and replaced in the IRA is
   * *permanently* disallowed, not deferred. Tri-state: this card is built from a synthetic,
   * single-account replay with no visibility into the user's real accounts, so `null` (not
   * checked) is the only honest default. Never render `null` as "no". */
  ira_exposure: boolean | null;
  unavailable_reason: string | null;
}

/**
 * The deliverable. Every figure computed, none of it advice — `disclaimer` is not boilerplate to
 * collapse away. Produced for a rejected or inconclusive thesis too, carrying the numbers that
 * killed it: a component that only renders cards for survivors is filtering on the outcome.
 */
export interface StrategyCard {
  symbol: string;
  interval: Interval;
  generated_at: string;
  thesis: Thesis;
  thesis_hash: string;
  verdict: Verdict;

  entry_rule: string;
  exit_rule: string | null;
  /** A rule that fires twice a decade is untradeable however good its statistics look. */
  triggers_per_year: number | null;
  holding_period_median: number | null;
  holding_period_iqr: [number, number] | null;

  /** A distribution, never a point estimate. */
  expected_return: Distribution;
  /** The instrument's unconditional outcome over the same horizon. Required beside
   * `expected_return` for the same reason every other baseline in this project is required. */
  baseline_return: Distribution;
  worst_trade: number | null;
  max_drawdown_in_position: number | null;

  in_sample: Evidence | null;
  holdout: Evidence | null;
  holdout_state: HoldoutState | null;
  ledger: LedgerStats | null;
  regimes: RegimeSlice[];
  tax: TaxImpact | null;

  /** The same thesis on the unlevered equivalent, present only when the subject is a daily-reset
   * leveraged or inverse product. Without it a card can measure leverage decay and call it
   * strategy — never render a leveraged card's numbers without checking for this. */
  unlevered_comparison: StrategyCard | null;
  /** A labelled hourly exit refinement, present only when one ran and cleared the independent-event
   * floor. The daily result is always the headline; this is a footnote, not a replacement. */
  hourly_substudy: Evidence | null;

  strategy_result: StrategyResult | null;
  /** Facts for the grounded narrative, under the same citation contract `api/report.ts` documents. */
  bundle: FactBundle | null;
  warnings: MarketWarning[];
  disclaimer: string;
}

// --- loop result --------------------------------------------------------------

/** How a run ended. Five reportable outcomes, not three results plus an error — see the module
 * docstring on `budget_exhausted` in particular.
 *
 * `"catalogue_exhausted"` is distinct from `"budget_exhausted"` because the two say different
 * things and only one is about the ticker: "no thesis survived twelve attempts" is information
 * about the instrument, while "the author had five ideas and none worked" is information about the
 * author. With the backend's default catalogue (five or six templates) against the default budget
 * of twelve, `"catalogue_exhausted"` is the *usual* outcome, not an edge case — see
 * `backend/app/thesis/models.py`'s `LoopOutcome.CATALOGUE_EXHAUSTED`. */
export type LoopOutcome =
  | "survivor_found"
  | "budget_exhausted"
  | "catalogue_exhausted"
  | "no_data"
  | "holdout_unavailable";

/**
 * One complete run: what was tried, what survived, and what it cost in trials. `records` and
 * `ledger` are always present — the backend never filters this down to survivors, and neither
 * should a component built on top of it. See the module docstring.
 */
export interface LoopResult {
  symbol: string;
  interval: Interval;
  started_at: string;
  finished_at: string;
  outcome: LoopOutcome;
  budget: number;
  /** Every iteration, including those that produced nothing. Equals `records.length`. */
  iterations_used: number;
  records: ThesisRecord[];
  /** Cards for everything that got far enough to have one — not only survivors. */
  cards: StrategyCard[];
  ledger: LedgerStats | null;
  holdout: HoldoutState | null;
  warnings: MarketWarning[];
}

// --- router-specific envelopes ------------------------------------------------

/** `GET /ledger`'s body: the denominator and the trials that make it up, together. Always both —
 * see `LoopResult`'s docstring for why splitting them would hide the trial count. */
export interface LedgerResponse {
  stats: LedgerStats;
  records: ThesisRecord[];
}

/** `GET /holdout`'s body. `state` is `null` for a ticker that has never had a holdout established —
 * not an error, a ticker that has not yet been screened far enough to need one. */
export interface HoldoutResponse {
  state: HoldoutState | null;
  description: string;
}

/** One standard hypothesis from the author's catalogue, as written before any ticker was chosen. */
export interface CatalogueEntry {
  key: string;
  hypothesis: string;
  entry: string;
  exit: string | null;
  horizon: number;
  direction: Direction;
  falsifies_if: string;
  rationale: string;
  max_holding_bars: number | null;
  stop_loss_pct: number | null;
  /** Proposed only for daily-reset leveraged or inverse products. */
  leveraged_only: boolean;
}

// --- requests -----------------------------------------------------------------

export interface RunRequest {
  symbol: string;
  interval?: Interval;
  /** Bounded 1..`MAX_ITERATION_BUDGET` on the backend; an out-of-range value is a 422, not a
   * silently clamped one. */
  budget?: number;
}

/** Identifies which survivor to promote onto the library shelf. Deliberately carries no rule text:
 * the backend rebuilds the card from its own ledger, so a caller points at a survivor but never
 * describes one — see `backend/app/thesis/promotion.py`. `position_pct`/`purpose` are optional risk
 * policy; omitting them takes the backend's defaults. */
export interface PromoteRequest {
  symbol: string;
  thesis_hash: string;
  position_pct?: number;
  purpose?: "savings" | "trading" | "roth";
}

/** The library card `POST /promote` returns (`app.tournament.models.StrategyCard`). Only the fields
 * the UI reads back are typed here; the card itself carries far more, but this endpoint's caller only
 * needs to confirm what landed and name it. */
export interface PromotedCard {
  agent_id: string;
  display_name: string;
  reference_only: boolean;
}

// --- fetchers -------------------------------------------------------------

const BASE = "/api/thesis";

/** Same shape as every other API module's `requestJson` — duplicated rather than shared for the
 * reason `api/backtest.ts` gives: it is a five-line contract, and importing it would tie this
 * module's loadability to another API module it otherwise has nothing to do with. */
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

export const thesisApi = {
  /**
   * Run the loop for one ticker. A `409` means a second holdout evaluation was attempted and the
   * out-of-sample guarantee for this ticker is now gone — the response body explains the burn and
   * the UI must surface it, not retry. A `422` with `outcome`-shaped detail means this ticker's
   * history cannot support a holdout evaluation yet. Neither is a bug: both are `ApiRequestError`s
   * carrying the guard's own explanation as `message`.
   */
  run: (request: RunRequest, signal?: AbortSignal) =>
    requestJson<LoopResult>(`${BASE}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: signal ?? null,
    }),

  /** The trial ledger for one ticker. A ticker with no history returns zeros and an empty record
   * list with a `200`, never a `404` — see `LedgerStats`. */
  ledger: (symbol: string, signal?: AbortSignal) =>
    requestJson<LedgerResponse>(`${BASE}/ledger?symbol=${encodeURIComponent(symbol)}`, {
      signal: signal ?? null,
    }),

  /** One ticker's holdout state and a human sentence describing it. Read-only — never establishes
   * a holdout as a side effect of being viewed. */
  holdout: (symbol: string, signal?: AbortSignal) =>
    requestJson<HoldoutResponse>(`${BASE}/holdout?symbol=${encodeURIComponent(symbol)}`, {
      signal: signal ?? null,
    }),

  /** Every standard hypothesis the default author can propose, so a user can see what will be
   * tried before a single trial is spent on it. */
  catalogue: (signal?: AbortSignal) =>
    requestJson<CatalogueEntry[]>(`${BASE}/catalogue`, { signal: signal ?? null }),

  /**
   * Promote a **survivor** onto the strategy-competition library shelf as a reference card. Only a
   * `card.verdict === "survived"` may be promoted; the backend re-checks the verdict from its ledger
   * and refuses anything else with a `422`. A `409` (`ApiRequestError.status`) means it was already
   * promoted — a survivor's rules are hash-pinned, so that is an idempotent no-op to surface, not an
   * error to retry. A `404` means the survivor is not in the ledger for that symbol.
   */
  promote: (request: PromoteRequest, signal?: AbortSignal) =>
    requestJson<PromotedCard>(`${BASE}/promote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: signal ?? null,
    }),
};

// --- display helpers --------------------------------------------------------

/**
 * Compile-time exhaustiveness for the `switch (x) { ...; default: { const _exhaustive: never = x;
 * ... } }` pattern below. This project's `tsconfig.json` sets `strict: true` but not
 * `noImplicitReturns`, so a switch over a union with a case missing and no `default` compiles cleanly
 * and falls through to `undefined` at runtime rather than failing the build — that gap is exactly how
 * `outcomeLabel` rendered a blank headline for `"catalogue_exhausted"` for as long as `LoopOutcome`
 * did not list it: the union was incomplete *and* nothing would have caught a complete union going
 * unhandled either. A `default` branch that assigns to a local `const _exhaustive: never` closes the
 * compile-time hole exactly as before: `tsc` fails the next time one of this file's unions drifts
 * from the backend's.
 *
 * **This module used to throw here instead of degrading.** `assertNever` used to `throw`, which
 * closed the compile-time hole but reopened a worse one at runtime: `Verdict`/`LoopOutcome`/
 * `HoldoutStatus` all describe data these functions receive from the *server*, not values this code
 * constructs itself, so a throwing default takes the whole page down the moment the backend sends a
 * value this build has not been updated for -- the exact failure `exitReasonLabel` in
 * `@/api/paperdesk` documents happening for real on Paper Desk. Every `switch` below now degrades
 * instead: a label function renders the raw wire value, and `holdoutSeverity` degrades to `"none"`,
 * its own least-alarming reading (see that function's docstring).
 */

/**
 * `"inconclusive"` reads as a normal result, not a failure — see the module docstring. Callers that
 * want a colour or icon should key off this string directly rather than treating any non-`"survived"`
 * verdict as an error.
 */
/** Display word for a raw `Direction` wire value -- the enum itself stays an identifier. */
export function directionLabel(direction: Direction): string {
  switch (direction) {
    case "up":
      return t("strategy.direction.up");
    case "down":
      return t("strategy.direction.down");
    default: {
      const _exhaustive: never = direction;
      void _exhaustive;
      return String(direction);
    }
  }
}

export function verdictLabel(verdict: Verdict): string {
  switch (verdict) {
    case "survived":
      return t("strategy.thesis.verdict.survived");
    case "rejected":
      return t("strategy.thesis.verdict.rejected");
    case "inconclusive":
      return t("strategy.thesis.verdict.inconclusive");
    default: {
      const _exhaustive: never = verdict;
      void _exhaustive;
      return String(verdict);
    }
  }
}

/**
 * `"budget_exhausted"`, `"catalogue_exhausted"` and `"no_data"` are answers, not error states — see
 * the module docstring. Only `"holdout_unavailable"` corresponds to a request the backend actually
 * rejects (`POST /run` turns it into a 409 or 422 before a `LoopResult` with this outcome would ever
 * reach the client); it is included here for completeness and for rendering a `LoopResult` obtained
 * by other means.
 *
 * `"budget_exhausted"` and `"catalogue_exhausted"` read differently on purpose: the first says the
 * ticker outlasted every attempt the run was allowed to spend, the second says the run ran out of
 * distinct hypotheses to try before it ran out of budget — real information about the author's
 * catalogue, not about the ticker. Collapsing them into one label would overstate how hard the loop
 * looked in the second case.
 */
export function outcomeLabel(outcome: LoopOutcome): string {
  switch (outcome) {
    case "survivor_found":
      return t("strategy.thesis.outcome.survivorFound");
    case "budget_exhausted":
      return t("strategy.thesis.outcome.budgetExhausted");
    case "catalogue_exhausted":
      return t("strategy.thesis.outcome.catalogueExhausted");
    case "no_data":
      return t("strategy.thesis.outcome.noData");
    case "holdout_unavailable":
      return t("strategy.thesis.outcome.holdoutUnavailable");
    default: {
      const _exhaustive: never = outcome;
      void _exhaustive;
      return String(outcome);
    }
  }
}

/**
 * How loud a holdout badge should be. `"burned"` must never render at the same visual weight as
 * `"ok"` or `"spent"` — it means the ticker's one out-of-sample guarantee is gone. `"none"` is a
 * ticker that has not been screened far enough to need a holdout yet, and is informational, not a
 * warning.
 */
export type HoldoutSeverity = "none" | "ok" | "spent" | "burned";

export function holdoutSeverity(state: HoldoutState | null): HoldoutSeverity {
  if (state === null) return "none";
  switch (state.status) {
    case "unused":
      return "ok";
    case "spent":
      return "spent";
    case "burned":
      return "burned";
    default: {
      // Degrades to `"none"` rather than throwing -- `HoldoutSeverity` has no literal "neutral"
      // member, and `"none"` is its actual least-alarming reading (see the type's own docstring:
      // "informational, not a warning"). Neither `"ok"` (falsely reassuring) nor `"burned"` (falsely
      // alarming) is a safe guess about a status this build does not recognise.
      const _exhaustive: never = state.status;
      void _exhaustive;
      return "none";
    }
  }
}

/**
 * Format a q-value. Below 0.001 it renders as `<0.001` rather than `0.000`, which would read as
 * certainty about a quantity that is an expected rate over a set. Same convention as
 * `api/backtest.ts`'s `formatQ`, duplicated for the reason `requestJson` is duplicated above.
 */
export function formatQ(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  if (value < 0.001) return "<0.001";
  return value.toFixed(3);
}
