/**
 * Typed client for the endless competition/feedback loop: propose a generation of genomes, run them,
 * score them, promote the winners, cool down, repeat -- unattended, until stopped.
 *
 * Mirrors `api/competition.ts`'s own conventions field for field: a local `requestJson<T>` (duplicated
 * rather than imported -- see that module's docstring on why every API module in this codebase carries
 * its own copy), the same `BASE = "/api/competition"` the loop's four routes hang off of, and `Decimal`
 * fields typed as `DecimalString` -- they arrive as JSON strings, never numbers, and must never be
 * parsed through an IEEE double. Reuse `formatSignedPctFraction`/`formatPctFraction`/`fractionTone`/
 * `formatIntOrDash` from `api/competition.ts` to render any of them; nothing here reimplements that
 * arithmetic. `Purpose` and `PURPOSE_LABELS` are duplicated below rather than imported, matching the
 * same "one copy per module" convention `requestJson` follows.
 *
 * **A `GET /loop` 404 is the loop's normal idle state, not a page error.** The loop has either never
 * been started, or was started once and the record was since cleared -- either way there is nothing to
 * poll and nothing wrong. `isLoopNotStarted` below is the one place that check should live; callers
 * should use it rather than re-deriving `err instanceof ApiRequestError && err.status === 404`
 * themselves, the same way `api/competition.ts`'s callers key off its own documented 404s.
 *
 * **`holdout_median_excess` was never used to pick anything.** It is scored the same way
 * `median_excess` is, but over `holdout_windows` -- windows the selection step never saw. It is the
 * honesty check on whether a winner's edge generalises past the windows it was chosen on, not a second
 * opinion on the same evidence. Render it labelled as unused-for-selection, never under the same
 * heading as the selection median -- see `Standing`'s own docstring below.
 */
import { ApiRequestError, type DecimalString } from "@/api/client";
import { t } from "@/i18n";

// --- loop lifecycle ----------------------------------------------------------------------------------

export type LoopState = "idle" | "running" | "stopping" | "stopped" | "failed";

/** What the supervisor is doing inside one generation. Only meaningful while `LoopState` is
 * `"running"` or `"stopping"` -- see `LoopStatus.phase`. */
export type LoopPhase = "idle" | "proposing" | "running" | "scoring" | "promoting" | "cooldown";

/** Duplicated from `api/competition.ts`'s own `Purpose` rather than imported -- see this module's
 * docstring for why every API module here carries its own copy of shared wire vocabulary. */
export type Purpose = "savings" | "trading" | "roth";

export const PURPOSE_LABELS: Record<Purpose, string> = {
  savings: "Savings",
  trading: "Trading",
  roth: "Roth IRA",
};

/**
 * The translated counterpart to `PURPOSE_LABELS` above -- a function, not a static record, so it reads
 * the catalog fresh on every call rather than freezing whatever language was active at module load.
 * `PURPOSE_LABELS` itself is left untouched (still English-only): `CandidateDossier.tsx`,
 * `PendingSeatsPanel.tsx`, and `candidateName.ts` -- all outside this shard's scope fence -- index it
 * directly (`PURPOSE_LABELS[p]`, `Object.keys(PURPOSE_LABELS)`), and changing its shape would break
 * their compilation. Reuses the same catalog keys as `api/competition.ts`'s own `purposeLabel`: same
 * three words, one Korean translation to keep in sync rather than two. */
export function purposeLabel(purpose: Purpose): string {
  switch (purpose) {
    case "savings":
      return t("competition.purpose.savings");
    case "trading":
      return t("competition.purpose.trading");
    case "roth":
      return t("competition.purpose.rothIra");
    default: {
      const _exhaustive: never = purpose;
      void _exhaustive;
      return String(purpose);
    }
  }
}

export type FindingKind =
  | "winner"
  | "failure"
  | "regime"
  | "universe"
  | "parameter"
  | "gate"
  | "holdout";

const FINDING_KIND_LABELS: Record<FindingKind, string> = {
  winner: "Winner",
  failure: "Failure",
  regime: "Regime",
  universe: "Universe",
  parameter: "Parameter",
  gate: "Gate",
  holdout: "Holdout",
};

/** `FINDING_KIND_LABELS` above is module-private (not exported), so this can translate directly. */
export function findingKindLabel(kind: FindingKind): string {
  switch (kind) {
    case "winner":
      return t("competition.evoFindingKind.winner");
    case "failure":
      return t("competition.evoFindingKind.failure");
    case "regime":
      return t("competition.evoFindingKind.regime");
    case "universe":
      return t("competition.evoFindingKind.universe");
    case "parameter":
      return t("competition.evoFindingKind.parameter");
    case "gate":
      return t("competition.evoFindingKind.gate");
    case "holdout":
      return t("competition.evoFindingKind.holdout");
    default:
      return FINDING_KIND_LABELS[kind];
  }
}

export interface LoopConfig {
  purposes: Purpose[];
  /** How many genomes compete in one generation. Default changed from 6 to **10** when `max_workers`
   * was added -- range 2..24. More agents means a longer generation: each one costs a full pass over
   * every window, `max_workers` notwithstanding. */
  population: number;
  /** How many cards run at once within a generation -- default 4, range 1..16. `1` is fully serial;
   * this is what makes a generation faster, not `population`. */
  max_workers: number;
  elite_count: number;
  windows: string[];
  holdout_windows: string[];
  max_generations: number | null;
  rank_by: string;
  promotion_margin_pp: DecimalString;
  promotion_consecutive: number;
  /** The most windows two of a promotion's evidence sets may share, or `null` for no ceiling (the
   * default). `null` is weaker than it reads: the loop's rotation drops exactly one window per
   * generation, so "two distinct window sets" has always meant two sets sharing four of five. Setting
   * it below what the configured pool can produce is a `400` from `POST /loop`, not a `422`, and the
   * detail names the achievable floor. */
  promotion_max_shared_windows: number | null;
  seat_on_paper_desk: boolean;
  use_news: boolean;
  news_fraction: number;
  seed: number;
  cooldown_seconds: number;
  /** Free text describing what this run is meant to find out. Default `""`. Recorded with every
   * generation and rendered beside the results -- it is never read by the loop itself. `focus_symbols`/
   * `avoid_symbols` and `rank_by` are what actually constrain or steer what gets proposed; a UI that
   * implies this prose is pattern-matched or otherwise steers the search overstates what it does. */
  goal: string;
  /** Tickers every candidate genome must hold. Default `[]`. The backend rejects (`422`) a symbol here
   * that is outside the tradeable pool, or a symbol named in both this list and `avoid_symbols`. */
  focus_symbols: string[];
  /** Tickers no candidate genome may hold. Default `[]`. Same `422` rules as `focus_symbols` above. */
  avoid_symbols: string[];
}

// --- start-loop form draft ---------------------------------------------------------------------------

/**
 * The start form's own working state, kept distinct from `Partial<LoopConfig>` because two of its
 * fields (`focusSymbolsInput`/`avoidSymbolsInput`) are raw, not-yet-parsed text -- a user mid-typing
 * `"NVDA, A"` has not yet produced a valid ticker list, and forcing the field through `LoopConfig`'s
 * `string[]` shape on every keystroke would either reject the partial input or silently drop it.
 * `buildLoopConfigFromDraft` is the one place this draft becomes wire-shaped.
 */
export interface LoopFormDraft {
  /** Which books this run breeds for. At least one -- `LoopConfig.purposes` is `min_length=1` on the
   * backend, because an empty list builds zero lanes and the supervisor then dies on a modulo by zero
   * rather than reporting a bad request. The form enforces the same rule locally so the reader is not
   * told about it by a 422. */
  purposes: Purpose[];
  population: number;
  maxWorkers: number;
  goal: string;
  focusSymbolsInput: string;
  avoidSymbolsInput: string;
}

/** The order the purposes checkboxes render in, and the order `purposes` is sent in -- which is also
 * the order `_lanes_for` cycles lanes through, so it is not cosmetic. Trading first because it is the
 * book with the most cards; savings last because it has the fewest
 * (`strategy-program/SAVINGS-FAMILY.md`). */
export const PURPOSE_ORDER: readonly Purpose[] = ["trading", "roth", "savings"];

/** The form's own defaults -- `population: 10`/`maxWorkers: 4` match `LoopConfig`'s own documented
 * defaults above, so a reader who never touches the form and clicks the one-click header toggle gets
 * exactly what the backend would have defaulted to anyway. */
export const DEFAULT_LOOP_FORM_DRAFT: LoopFormDraft = {
  purposes: ["trading", "roth"],
  population: 10,
  maxWorkers: 4,
  goal: "",
  focusSymbolsInput: "",
  avoidSymbolsInput: "",
};

/** Comma-separated free text -> an uppercased, trimmed ticker list. Empty input (or a string of only
 * commas/whitespace) becomes `[]`, never `[""]` -- `.filter(Boolean)` after the trim is what guarantees
 * that. */
export function parseSymbolListInput(raw: string): string[] {
  return raw
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter((s) => s.length > 0);
}

/** The one place a `LoopFormDraft` becomes the `Partial<LoopConfig>` `startLoop` actually sends. */
export function buildLoopConfigFromDraft(draft: LoopFormDraft): Partial<LoopConfig> {
  return {
    // Sent in `PURPOSE_ORDER`, not in the order the boxes were ticked: `purposes` is the sequence
    // `_lanes_for` cycles through, so two runs that selected the same books would otherwise work
    // their lanes in a different order depending on click order, and a loop's reproducibility claim
    // is scoped to its config.
    purposes: PURPOSE_ORDER.filter((p) => draft.purposes.includes(p)),
    population: draft.population,
    max_workers: draft.maxWorkers,
    goal: draft.goal,
    focus_symbols: parseSymbolListInput(draft.focusSymbolsInput),
    avoid_symbols: parseSymbolListInput(draft.avoidSymbolsInput),
  };
}

/**
 * One genome's standing within a generation. `median_excess`/`worst_excess` follow the same
 * `null`-is-not-zero rule `api/competition.ts`'s `LeaderboardRow` documents for its own fields of the
 * same names -- render with `formatSignedPctFraction`/`formatPctFraction`, never a bare template
 * string that would print `"0.00%"` for a figure that was never computed.
 *
 * **`holdout_median_excess` is not a second `median_excess`.** It is the same quantity computed over
 * `holdout_windows` instead of the windows selection ran on -- windows the promotion decision never
 * looked at. A UI that renders it under the same label as `median_excess`, or without noting it was
 * never used for selection, states a stronger claim for this genome than the evidence supports.
 */
export interface Standing {
  genome_id: string;
  agent_id: string;
  display_name: string;
  rank: number;
  eligible: boolean;
  windows_run: number;
  median_excess: DecimalString | null;
  worst_excess: DecimalString | null;
  hit_rate: number | null;
  total_trades: number;
  holdout_median_excess: DecimalString | null;
  q_value: number | null;
}

export interface Finding {
  kind: FindingKind;
  summary: string;
  evidence: Record<string, unknown>;
}

export interface GenerationOutcome {
  generation: number;
  round_id: string;
  purpose: Purpose;
  job_id: string | null;
  status: "succeeded" | "failed" | "cancelled";
  started_at: string;
  finished_at: string;
  windows: string[];
  holdout_windows: string[];
  genome_ids: string[];
  standings: Standing[];
  findings: Finding[];
  promoted: string[];
  error: string | null;
}

/** One genome the loop actually promoted. `seated: false` means it cleared the promotion gates but
 * never took a seat on the paper desk -- a real, distinct outcome from not being promoted at all;
 * `reason` says why either way. */
export interface PromotionRecord {
  genome_id: string;
  agent_id: string;
  purpose: Purpose;
  promoted_at: string;
  generations: number[];
  window_sets: string[][];
  median_excess: DecimalString;
  holdout_median_excess: DecimalString | null;
  q_value: number | null;
  library_path: string;
  seated: boolean;
  reason: string;
}

export interface LoopStatus {
  loop_id: string;
  state: LoopState;
  phase: LoopPhase;
  config: LoopConfig;
  generation: number;
  completed_generations: number;
  candidates_tested: number;
  started_at: string | null;
  updated_at: string | null;
  stopped_at: string | null;
  current_round_id: string | null;
  current_job_id: string | null;
  current_purpose: Purpose | null;
  best: Standing | null;
  promotions: PromotionRecord[];
  history: GenerationOutcome[];
  log: string[];
  error: string | null;
}

export interface LoopHistoryResponse {
  generations: GenerationOutcome[];
}

// --- generation history & review (GenerationsPanel) ---------------------------------------------------
//
// `LoopStatus.history`/`best` only ever carried the *current run's* recent generations and the single
// current leader. The types below back `GenerationsPanel`, which reads the loop's entire generation
// history independently of whatever is running right now -- the fix for "there is no way to see a
// generation that is not the current one, and no way to see the whole field on any one of them."

/**
 * One field-wide statistic across every candidate scored in a generation -- e.g. the *median* of
 * `median_excess` across the whole population, not the single leader's own number. `n` is the
 * candidate count the stat was computed over and must always be shown alongside it: a median over two
 * candidates and a median over ten are different claims even when the number printed is identical.
 * Every numeric field arrives as a `DecimalString`, exactly like `Standing`'s own fields, for the same
 * precision reason -- see `formatFieldStat` below for the one place this gets rendered.
 */
export interface StatSummary {
  n: number;
  min: DecimalString;
  p25: DecimalString;
  median: DecimalString;
  p75: DecimalString;
  max: DecimalString;
  mean: DecimalString;
}

/**
 * The whole field's spread on each axis for one generation -- the direct fix for "only the leader is
 * tracked." A `null` entry means the generation produced no standings on that axis at all (most often
 * because the generation failed before scoring); it is not the same as a `StatSummary` full of zeros
 * and must render as "no field", never `0` or a blank cell that reads as zero -- see `formatFieldStat`.
 *
 * `holdout_gap_pp` is already in percentage points, unlike every other field here, which are fractions
 * (`0.194` = 19.4%). Render it with `formatPctPoints`, never `formatSignedPctFraction`/
 * `formatPctFraction` -- swapping the two is a silent 100x error that does not look obviously wrong on
 * screen.
 */
export interface GenerationField {
  median_excess: StatSummary | null;
  worst_excess: StatSummary | null;
  hit_rate: StatSummary | null;
  holdout_median: StatSummary | null;
  holdout_gap_pp: StatSummary | null;
  total_trades: StatSummary | null;
  q_value: StatSummary | null;
}

/** `margin_pp` is already in percentage points, exactly like `GenerationField.holdout_gap_pp` above --
 * see `formatPctPoints`. */
export interface GenerationGate {
  cleared: number;
  eligible: number;
  margin_pp: DecimalString | null;
}

/** The single leader's own figures for a generation, kept as a distinct type from `GenerationField`
 * above on purpose -- this is one candidate's result, not the field's distribution. Rendering it under
 * the same heading as `GenerationField.median_excess` would silently swap "the whole field" back for
 * "the best one", which is the exact narrowness this panel exists to fix. */
export interface GenerationLeader {
  genome_id: string;
  display_name: string;
  rank: number;
  median_excess: DecimalString | null;
  holdout_median_excess: DecimalString | null;
}

export interface GenerationSummary {
  generation: number;
  round_id: string;
  purpose: Purpose;
  status: "succeeded" | "failed" | "cancelled";
  started_at: string;
  finished_at: string;
  duration_seconds: number;
  windows: string[];
  holdout_windows: string[];
  candidates: number;
  ranked: number;
  eligible: number;
  error: string | null;
  field: GenerationField;
  gate: GenerationGate;
  promoted: string[];
  leader: GenerationLeader | null;
  findings_by_kind: Record<string, number>;
  has_review: boolean;
}

export interface GenerationsListResponse {
  total: number;
  returned: number;
  offset: number;
  /** Generations the backend could not read back off disk/DB -- not the same thing as a generation
   * that ran and failed (that is `status: "failed"` and reads back fine). Surfaced as its own count,
   * never silently folded into `total` or dropped. */
  unreadable: number;
  /** Newest first, per the endpoint's own contract -- not re-sorted on this side. */
  generations: GenerationSummary[];
}

/** One candidate's write-up inside a model-authored `GenerationReview`. Joined to the matching
 * `Standing` in `GenerationOutcome.standings` by `genome_id` for display -- `note`/`keep` alone name no
 * candidate a reader could act on. */
export interface GenerationReviewPerCandidate {
  genome_id: string;
  note: string;
  keep: boolean;
}

export interface GenerationReviewDirection {
  headline: string;
  hypotheses: string[];
  focus_symbols: string[];
  avoid_symbols: string[];
  emphasise_disciplines: string[];
  retire_disciplines: string[];
}

/** One change the review made to the run's own configuration going forward -- the loop retuning
 * itself. `value` is deliberately `unknown`: the amended field can be any shape `LoopConfig` allows,
 * and coercing it to a narrower display type here risks inventing a value the review never actually
 * stated. Render amendments as a clearly-marked change list, never folded into ordinary prose -- a
 * self-modifying search whose changes are invisible is not auditable. */
export interface GenerationReviewAmendment {
  field: string;
  value: unknown;
  reason: string;
}

export type GenerationReviewVerdict = "promising" | "inconclusive" | "exhausted" | "broken";

/** Written by a model after a generation completes. Every field but `generation`/`purpose`/`verdict`/
 * `post_mortem` may be empty (not populated) on an older or thinner record -- this type only promises
 * the keys exist, not that they carry anything. */
export interface GenerationReview {
  generation: number;
  purpose: Purpose;
  shape: string | null;
  verdict: GenerationReviewVerdict;
  post_mortem: string;
  per_candidate: GenerationReviewPerCandidate[];
  direction: GenerationReviewDirection;
  amendments: GenerationReviewAmendment[];
}

/** `outcome` reuses the existing `GenerationOutcome` type verbatim, per this module's own convention of
 * one definition per wire shape -- every `Standing` in `outcome.standings`, eligible or not, ranked or
 * not, is the direct fix for "only first place is tracked" and all of them must render, not just the
 * ranked ones. `plan_markdown` is the pre-registration written *before* the generation ran;
 * `review` is written *after* it finished -- keep the two visually distinct, never merged into one
 * prose block, since collapsing "what we said we'd do" into "what we concluded happened" is its own
 * way of overstating what either one supports on its own. */
export interface GenerationDetailResponse {
  outcome: GenerationOutcome;
  plan_markdown: string | null;
  review: GenerationReview | null;
}

/** One run of consecutive failed generations sharing one identical error -- the collapse target for
 * `GenerationsPanel`'s single most important display decision. See that component's own docstring on
 * why rendering each generation in a 400-long streak as its own row would make the panel useless. A
 * streak of `count: 1` is an isolated failure with no repeat; it still comes back as its own record so
 * no failure is ever silently swallowed by the collapsing, only ever rendered as at most one row. */
export interface FailureStreak {
  first_generation: number;
  last_generation: number;
  count: number;
  error: string;
  started_at: string;
  finished_at: string;
}

export interface FailureStreaksResponse {
  streaks: FailureStreak[];
}

// --- display helpers: loop state/phase ----------------------------------------------------------------

/**
 * Exhaustive at compile time, forgiving at runtime -- the pattern pinned by `exitReasonLabel` in
 * `@/api/paperdesk` (see that function's docstring for the concrete page-down failure it exists to
 * prevent, and `api/competition.ts`'s own copy of this same note). Every `switch` below still
 * assigns its `default` branch to a local `const _exhaustive: never`, so `tsc` fails the moment a
 * union here gains a member without a case -- but nothing below *throws* over a value that reaches it
 * anyway, since `LoopState`/`LoopPhase` describe data this page polls from the server.
 */

export function loopStateLabel(state: LoopState): string {
  switch (state) {
    case "idle":
      return t("status.idle");
    case "running":
      return t("status.running");
    case "stopping":
      return t("competition.loop.stopping");
    case "stopped":
      return t("status.stopped");
    case "failed":
      return t("status.failed");
    default: {
      const _exhaustive: never = state;
      void _exhaustive;
      return String(state);
    }
  }
}

export function loopPhaseLabel(phase: LoopPhase): string {
  switch (phase) {
    case "idle":
      return t("status.idle");
    case "proposing":
      return t("competition.loopPhase.proposing");
    case "running":
      return t("status.running");
    case "scoring":
      return t("competition.loopPhase.scoring");
    case "promoting":
      return t("competition.loopPhase.promoting");
    case "cooldown":
      return t("competition.loopPhase.cooldown");
    default: {
      const _exhaustive: never = phase;
      void _exhaustive;
      return String(phase);
    }
  }
}

/** Whether a poll loop over `GET /loop` should keep going. `"running"`/`"stopping"` keep the
 * `setInterval` alive (mirrors `isTerminalJobStatus`'s inverse in `api/competition.ts`); every other
 * state is a settled end state -- including `"idle"`, which a `null` status (never started) is treated
 * as by callers that pass `status?.state ?? "idle"` here. An unrecognised state is treated as active --
 * the conservative reading, matching `isTerminalJobStatus`'s own choice to keep polling rather than
 * silently drop a live loop's updates over a value this build has not been taught to end on. */
export function isLoopActive(state: LoopState): boolean {
  switch (state) {
    case "running":
    case "stopping":
      return true;
    case "idle":
    case "stopped":
    case "failed":
      return false;
    default: {
      const _exhaustive: never = state;
      void _exhaustive;
      return true;
    }
  }
}

// --- display helpers: generation field stats ------------------------------------------------------

/** `GenerationField.holdout_gap_pp` and `GenerationGate.margin_pp` are marked in the contract as
 * **already** in percentage points -- unlike `median_excess`/`worst_excess`/`hit_rate`/
 * `holdout_median`, which are fractions (`0.194` = 19.4%) and belong through
 * `formatSignedPctFraction`/`formatPctFraction` (`api/competition.ts`) instead. Getting the two
 * families swapped is a silent 100x error in either direction and does not look obviously wrong on
 * screen, which is exactly why this gets its own function rather than being folded into a shared
 * "format a percentage" helper that a caller could point at the wrong field. String arithmetic only,
 * matching every other formatter in this codebase -- never `parseFloat` followed by `.toFixed`, which
 * rounds through an IEEE double and can invent precision the server never sent.
 *
 * Rendered with a `pp` suffix rather than `%`, deliberately: a bare `%` next to a
 * `formatSignedPctFraction` value on the same row would look like the same unit, and it is not. */
export function formatPctPoints(value: DecimalString | null): string {
  if (value === null) return "—";
  const trimmed = value.trim();
  const negative = trimmed.startsWith("-");
  const digits = trimmed.replace(/^[+-]/, "");
  const [wholeRaw = "0", fracRaw = ""] = digits.split(".");
  const whole = (wholeRaw || "0").replace(/^0+(?=\d)/, "") || "0";
  const frac = (fracRaw + "00").slice(0, 2);
  const isZero = whole === "0" && frac === "00";
  const sign = isZero ? "" : negative ? "-" : "+";
  return `${sign}${whole}.${frac}pp`;
}

/** A `StatSummary`'s `median`, formatted with `n` alongside it -- never the value alone; see
 * `GenerationField`'s own docstring on why "a median over how many" is part of the claim, not a detail.
 * Takes the formatter for the underlying `DecimalString` (`formatSignedPctFraction`, `formatPctFraction`,
 * or `formatPctPoints` -- whichever family the field belongs to) so this stays the one place that
 * enforces "always show n" rather than a template string re-typed per field. `stat === null` renders
 * "no field", never `0` or a blank cell that reads as zero -- see `GenerationField`'s docstring. */
export function formatFieldStat(
  stat: StatSummary | null,
  formatter: (value: DecimalString | null) => string,
): string {
  if (stat === null) return t("competition.field.none");
  return `${formatter(stat.median)} (n=${stat.n})`;
}

// --- requests ------------------------------------------------------------------------------------------

/**
 * The five-stage pipeline a genome moves through, replacing the old two-value
 * `"pending" | "approved" | "rejected"`. `"approved"` no longer exists on the wire -- the 2026-08-26
 * migration rewrites every historical `approved` row to `"shelved"` and pulls its genome id back out
 * of `roster_overlay.json` where it had been auto-seated without review. The old single step
 * conflated "I looked at this and it's worth keeping" with "put it on the desk"; splitting it into
 * `shelved` (kept, named, not trading) and `seated` (on the desk) is the entire point of this rebuild.
 *
 * ```
 * pending --shelve/reject--> shelved --seat/retire--> seated
 *    |                          |
 *    +--> rejected (final)      +--> retired (final)
 * ```
 *
 * `shelve`/`reject` are legal only from `pending`; `seat`/`retire` are legal only from `shelved`. Only
 * `seat` touches `roster_overlay.json`.
 */
export type SeatStatus = "pending" | "shelved" | "seated" | "rejected" | "retired";

export type CautionSeverity = "blocking" | "serious" | "note";

/** One deterministic red flag computed from the frozen ledger plus the card itself -- never model
 * prose (see `SPEC.md`'s "Deterministic, not generated" house rule: fixed rules over fixed inputs, so
 * two runs produce byte-identical cautions and a finding can be trusted as a measurement, not a
 * summary). Render `text` verbatim; never reconstruct the sentence from `code` alone. The backend does
 * not promise an order -- sort by `severity` (`blocking` > `serious` > `note`) before rendering, most
 * severe first. */
export interface Caution {
  /** An open set -- new codes appear over time and render with no special-casing beyond `severity`
   * (see `CandidateDossier.tsx`, which keys its styling and testids off `severity`/`code` generically).
   * `label-does-not-match-rule` and `template-is-not-distinct` (both `serious`) are the newest two,
   * added alongside `PendingSeat.rule_template_id` and `Dossier.discipline_label`/
   * `discipline_label_note` after the 2026-08-26 finding that a self-declared label is not derived
   * from the rule and a mutation can flip it without touching the rule at all -- see
   * `candidateName.ts`'s module docstring for the concrete g1815/g1823 case that surfaced it. */
  code: string;
  severity: CautionSeverity;
  text: string;
}

/** Plain-English composed from the card's own JSON, no jargon left bare -- the direct fix for a queue
 * that showed a hash and four raw numbers with nothing describing what the strategy actually trades.
 * `raw` is the card's source rule fields, kept only so a reader can check the plain sentences against
 * where they came from; it is never the primary explanation. */
export interface WhatItDoes {
  universe: string[];
  universe_note: string;
  entry_plain: string;
  exit_plain: string;
  risk_plain: string;
  sizing_plain: string;
  raw: Record<string, unknown>;
}

export type OriginKind = "random" | "mutation" | "crossover" | "agent";

export interface DossierOrigin {
  generation: number;
  origin_kind: OriginKind;
  parents: string[];
  note: string;
}

/** One generation this genome was actually scored in, oldest first -- `median_excess`/`worst_excess`/
 * `holdout_median_excess` are fractions, formatted with the same `formatSignedPctFraction`/
 * `formatPctFraction` as everywhere else in this module. `total_trades` is a plain count and is never
 * `null` on a row that exists at all. */
export interface EvidenceRow {
  generation: number;
  round_id: string;
  rank: number;
  field_size: number;
  windows: string[];
  median_excess: DecimalString | null;
  worst_excess: DecimalString | null;
  hit_rate: number | null;
  total_trades: number;
  holdout_median_excess: DecimalString | null;
  holdout_windows: string[];
  q_value: number | null;
}

/**
 * What the same numbers look like across the whole field -- the direct fix for a screen that showed
 * "median excess 24.65" with nothing to compare it against. Every field below is explicitly scoped to
 * one of two reference populations, named in its own key -- `_same_purpose` (this card's actual
 * reference population: every candidate ever run for the same purpose, e.g. every `roth` card) or
 * `_all_purposes` (the wider "everything this search has ever run" context). There used to be an
 * unscoped `field_median_excess_all_time`/`field_holdout_median_all_time`/
 * `field_holdout_positive_fraction` here; the backend replaced them with the explicit pairs below
 * because an unlabelled "field median" is exactly what let a card's own figure get compared against
 * the wrong population unnoticed. **Always render which population a figure is scoped to** --
 * `CandidateDossier.tsx` labels every one of these on screen for that reason.
 *
 * `field_holdout_positive_fraction_all_purposes` is the number behind the
 * `holdout-does-not-discriminate` caution: 94.3% of every holdout measurement this search has ever
 * recorded, across every purpose, including purely random candidates, comes back positive -- which is
 * why that figure must be shown to a reader *before* the card's own holdout figure (see
 * `CandidateDossier.tsx`'s own docstring on why that ordering is load-bearing, not cosmetic). It is
 * NOT, on its own, a claim about whether this card beats its own purpose's field --
 * `field_holdout_median_same_purpose` is that comparison, and a card can (and does, e.g.
 * `g1859-fd7c2c196f35`) sit *above* its own purpose's field median while the wider "94.3% positive"
 * caveat still applies. Never render a comparison that asserts a direction the numbers do not support;
 * the deterministic `cautions[].text` already states the correct direction for a given card, so lean on
 * that rather than composing a new directional claim client-side.
 *
 * `holdout_measurements_same_purpose`/`holdout_measurements_all_purposes` are the `n` each positive-
 * fraction figure was computed over -- render alongside it, exactly like `StatSummary.n` above must
 * accompany a median.
 *
 * `noise_floor_pp`/`margin_over_noise_pp` are `DecimalString`s already in percentage points, like
 * `GenerationField.holdout_gap_pp` -- format with `formatPctPoints`, never
 * `formatSignedPctFraction`/`formatPctFraction`, which would silently misread a pp figure as a
 * fraction (a 100x error that does not look obviously wrong on screen).
 */
export interface DossierContext {
  field_median_excess_this_generation: DecimalString | null;
  field_median_excess_same_purpose: DecimalString | null;
  field_median_excess_all_purposes: DecimalString | null;
  field_holdout_median_same_purpose: DecimalString | null;
  field_holdout_median_all_purposes: DecimalString | null;
  field_holdout_positive_fraction_same_purpose: number | null;
  field_holdout_positive_fraction_all_purposes: number | null;
  holdout_measurements_same_purpose: number;
  holdout_measurements_all_purposes: number;
  percentile_all_time: number | null;
  candidates_ever_run: number;
  generations_with_outcomes: number;
  noise_floor_pp: DecimalString | null;
  margin_over_noise_pp: DecimalString | null;
}

export interface OverlapCard {
  genome_id: string;
  headline: string;
  shared_tickers: string[];
  jaccard: number;
}

/** Ticker overlap against every currently shelved/seated card -- the evidence behind the
 * `shelf-crowding` caution. `note` is the backend's own deterministic sentence and renders as-is. */
export interface DossierOverlap {
  with_shelved: OverlapCard[];
  with_seated: OverlapCard[];
  note: string;
}

/** What each of the four decision routes actually does, in the backend's own words -- render next to
 * the relevant button, never tucked into a tooltip a reviewer might not open. */
export interface WhatADecisionDoes {
  shelve: string;
  reject: string;
  seat: string;
  retire: string;
}

/**
 * `GET /api/competition/loop/candidates/{genome_id}/dossier` -- the full case for or against seating
 * one candidate: what it trades, why it exists, how its own numbers compare to the field that produced
 * it, and what could be wrong with it. Named `Dossier`, not `CandidateDossier`, so it does not collide
 * with the React component of that name in `pages/competition/CandidateDossier.tsx`, which fetches and
 * renders this type.
 */
export interface Dossier {
  genome_id: string;
  agent_id: string;
  /** Already composed server-side from the parsed rule (never from `discipline_label`) -- e.g.
   * "EMA 13/21 crossover, 135-day regime filter · CSCO/AMAT/LRCX +3 · Roth". Render this
   * directly; do not recompose it client-side. The backend guarantees this is byte-identical to the
   * same genome's `PendingSeat.headline` on the list endpoint (it has its own test asserting exactly
   * that), which is why `PendingSeatsPanel.tsx`'s `CandidateRow` shows no visible change when a row's
   * dossier finishes loading after its list-row headline was already on screen. */
  headline: string;
  short_id: string;
  purpose: Purpose;
  /** A self-declared label the genome (or whatever proposed it) attached to itself -- NOT derived
   * from the rule, and not safe to treat as a description of what the strategy does. Verified wrong
   * against the frozen ledger: `g1815-d05786e4c611` mutated into `g1823-e2a3d5060b09` with an
   * identical rule (universe, entry, exit, stop, sizing all byte-identical) but this label flipped
   * from `"breakout"` to `"mean-reversion"`. Never feed this into `candidateName.ts`'s `headline()`
   * (see that module's own docstring); render it only alongside `discipline_label_note` below, marked
   * explicitly as a self-declared label, not a description -- see `CandidateDossier.tsx`. */
  discipline_label: string;
  /** The backend's own explanation of why `discipline_label` is not to be trusted as a description --
   * render verbatim next to it (`CandidateDossier.tsx`'s `discipline-label` block) rather than
   * composing a caveat sentence client-side; the backend's wording is the one that stays in sync with
   * whatever evidence it is currently citing. */
  discipline_label_note: string;
  stage: SeatStatus | null;
  requested_at: string | null;
  what_it_does: WhatItDoes;
  thesis: string;
  origin: DossierOrigin;
  evidence: EvidenceRow[];
  context: DossierContext;
  cautions: Caution[];
  overlap: DossierOverlap;
  what_a_decision_does: WhatADecisionDoes;
}

/** One request from the loop for a person to decide about a promoted card.
 *
 * **Why this queue exists.** Promotion used to write the paper desk's roster overlay itself, gated
 * only by `LoopConfig.seat_on_paper_desk` -- a property of the whole *run*, chosen before any
 * candidate existed, so never a judgement about a particular card. Left running, the loop seated 25
 * cards (18 roth, 7 trading) that nobody had looked at. A promotion now files a request and moves
 * through `SeatStatus`'s two human decisions -- worth keeping? then: worth seating? -- rather than
 * one.
 *
 * Every number here was computed by the deterministic scorer and is copied, not re-derived. The one
 * judgement in the model is `status`, and only a person sets it.
 *
 * **`headline`/`short_id` are server-composed, verified against the live `app.main` contract
 * 2026-08-26.** This queue's shape used to carry neither -- no `headline`, no `discipline`, no
 * `universe` -- so a row had nothing readable to show before its dossier had been fetched, only the
 * purpose-only placeholder `candidateName.ts`'s `headline()`/`shortId()` compose. The backend now
 * enriches every row with its own `headline` (composed from the parsed rule, exactly the same way as
 * `Dossier.headline`, and guaranteed byte-identical to it for the same genome) and `short_id`. Prefer
 * a loaded `Dossier`'s own `headline`/`short_id` once a row has been expanded, else these list-row
 * fields, else `candidateName.ts`'s placeholder -- see `PendingSeatsPanel.tsx`'s `CandidateRow`. */
export interface PendingSeat {
  genome_id: string;
  agent_id: string;
  purpose: Purpose;
  requested_at: string;
  generations: number[];
  window_sets: string[][];
  /** A fraction, like every other `median_excess` in this module -- format with the same helper, not
   * as percentage points. */
  median_excess: string;
  holdout_median_excess: string | null;
  /** Benjamini-Hochberg over *every* candidate the loop has ever run, so it worsens as the search
   * continues even for a card that is never re-run. Worth showing beside the median: it is the
   * number that says how much of this showing is explained by how many things were tried. */
  q_value: number | null;
  library_path: string;
  reason: string;
  status: SeatStatus;
  decided_at: string | null;
  decided_note: string;
  /** Server-composed, rule-derived headline for this row -- see the interface docstring and
   * `Dossier.headline`'s own docstring on the byte-identical guarantee between the two. */
  headline: string;
  /** Server-computed `short_id`, identical in shape to `candidateName.ts`'s `shortId(genome_id)`. */
  short_id: string;
  /** The same self-declared tag as `Dossier.discipline_label` -- not derived from the rule, see that
   * field's docstring. Present here mainly so a future caller does not have to fetch a dossier just to
   * read it; this list view does not currently render it (the row's headline already carries the
   * rule-derived description, and the dossier is where the full self-declared-label caveat lives). */
  discipline_label: string;
  /** Identifies which underlying rule template this genome's entry/exit/risk/sizing rules match --
   * the masked-template string the `template-is-not-distinct` caution is computed from (all 25 of the
   * seat-request queue's cards shared exactly one template as of the 2026-08-26 finding, with 25
   * different `discipline_label` values on top of it). Lives on the list row, not on `Dossier`. `null`
   * when the backend has not computed it for this genome. A grouping key, not display text. */
  rule_template_id: string | null;
}

export interface PendingSeatsResponse {
  requests: PendingSeat[];
}

const BASE = "/api/competition";

/** Same five-line contract as every other API module's `requestJson` -- see `api/competition.ts`'s own
 * copy's docstring for why it is duplicated rather than imported. */
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

/** True for the one `ApiRequestError` a caller should render as an ordinary idle state rather than an
 * error -- `GET /loop` answering `404` because the loop has never been started. Every other status
 * (`409` from `DELETE` when nothing is running, `422`, `5xx`, …) is a real failure and should be
 * surfaced as one, exactly like any other endpoint in this app. */
export function isLoopNotStarted(error: unknown): boolean {
  return error instanceof ApiRequestError && error.status === 404;
}

/**
 * Turns a failed `startLoop` call into a message worth showing the person who just clicked "Start the
 * loop" -- in particular a `422`, which is how the backend refuses a `focus_symbols` ticker outside the
 * tradeable pool, or a symbol named in both `focus_symbols` and `avoid_symbols`.
 *
 * `ApiRequestError.message` for a FastAPI `422` is the raw response body -- `{"detail": "..."}` or
 * `{"detail": [{"msg": "...", ...}, ...]}` for a pydantic validation error -- a fragment of the wire
 * protocol, not something to render verbatim (see `InstitutionalHolders.tsx`'s `describeFailure` for the
 * same lesson learned the hard way). This unwraps `detail` when the body parses as JSON: a string
 * `detail` renders as-is (this is the specific, actionable case above -- which ticker, which list), a
 * pydantic array joins its messages, and anything else falls back to a generic rejection rather than a
 * raw JSON fragment.
 */
export function describeStartLoopError(error: unknown): string {
  if (!(error instanceof ApiRequestError)) {
    return error instanceof Error && error.message
      ? error.message
      : t("competition.loop.errors.startFallback");
  }
  if (error.status === 422) {
    const detail = parseErrorDetail(error.message);
    return detail ?? t("competition.loop.errors.configRejected");
  }
  return error.message || t("competition.loop.errors.startFallback");
}

function parseErrorDetail(body: string): string | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object" || !("detail" in parsed)) return null;
  const detail = (parsed as { detail: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : null))
      .filter((m): m is string => m !== null);
    return messages.length > 0 ? messages.join("; ") : null;
  }
  return null;
}

/** One generation's rolling digest -- what that generation taught, as a Markdown string the backend
 *  wrote (`app.evolution.digest`). Rendered as plain pre-wrap text; this app has no Markdown renderer. */
export interface JournalEntry {
  generation: number;
  markdown: string;
}

/** `GET /loop/journal`'s body. `total` counts every generation with a digest on disk, not just the
 *  returned page; `entries` are newest generation first. A loop with no digests answers `total: 0`. */
export interface JournalResponse {
  total: number;
  entries: JournalEntry[];
}

export const evolutionApi = {
  /** Starts the loop. Every field of `LoopConfig` is optional -- an empty body (the default) starts it
   * on its own defaults. Returns the `202` body immediately, before a single generation has run; poll
   * `loop()` for live state. */
  startLoop: (config: Partial<LoopConfig> = {}, signal?: AbortSignal) =>
    requestJson<LoopStatus>(`${BASE}/loop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
      signal: signal ?? null,
    }),

  /** The loop's current status. A `404` means the loop has never been started -- an ordinary idle
   * state, not a page error; check it with `isLoopNotStarted` rather than a bare `err.status === 404`
   * so the one place this rule lives stays this module. */
  loop: (signal?: AbortSignal) => requestJson<LoopStatus>(`${BASE}/loop`, { signal: signal ?? null }),

  /** Asks a running loop to stop. Returns the loop's own status (typically `"stopping"` immediately,
   * settling to `"stopped"` on a later poll) rather than an empty body, so the caller renders it
   * exactly like any other poll result. A `409` means nothing is running -- a real error, unlike
   * `loop()`'s `404`. */
  stopLoop: (signal?: AbortSignal) =>
    requestJson<LoopStatus>(`${BASE}/loop`, { method: "DELETE", signal: signal ?? null }),

  /** Past generations the loop has completed, in the backend's own order -- not re-sorted here.
   * `limit` caps how many come back; omitted, the backend applies its own default. */
  loopHistory: (limit?: number, signal?: AbortSignal) =>
    requestJson<LoopHistoryResponse>(
      `${BASE}/loop/history${limit !== undefined ? `?limit=${encodeURIComponent(String(limit))}` : ""}`,
      { signal: signal ?? null },
    ),

  /** Paginated, newest-first generation summaries -- the field-wide view `GenerationsPanel` reads for
   * its main table and its trend section. `purpose`/`status`/`succeeded_only` are forwarded verbatim
   * only when supplied; an omitted filter lets the backend apply no filter on that axis, matching
   * `leaderboard`'s own optional-param convention in `api/competition.ts`. */
  generations: (
    params: {
      limit?: number;
      offset?: number;
      purpose?: Purpose;
      status?: "succeeded" | "failed" | "cancelled";
      succeeded_only?: boolean;
    } = {},
    signal?: AbortSignal,
  ) => {
    const search = new URLSearchParams();
    if (params.limit !== undefined) search.set("limit", String(params.limit));
    if (params.offset !== undefined) search.set("offset", String(params.offset));
    if (params.purpose !== undefined) search.set("purpose", params.purpose);
    if (params.status !== undefined) search.set("status", params.status);
    if (params.succeeded_only !== undefined) search.set("succeeded_only", String(params.succeeded_only));
    const qs = search.toString();
    return requestJson<GenerationsListResponse>(`${BASE}/loop/generations${qs ? `?${qs}` : ""}`, {
      signal: signal ?? null,
    });
  },

  /** One generation's full detail: every standing it produced (ranked and not, eligible and not), the
   * pre-registration written before it ran, and the model's review written after -- a `null` review
   * means no model has reviewed this generation, not an empty one. */
  generationDetail: (generation: number, signal?: AbortSignal) =>
    requestJson<GenerationDetailResponse>(
      `${BASE}/loop/generations/${encodeURIComponent(String(generation))}`,
      { signal: signal ?? null },
    ),

  /** Every run of consecutive failed generations sharing one identical error, already collapsed by the
   * backend -- see `FailureStreak`'s own docstring. Not paginated: the whole point of this endpoint is
   * that its response stays small even when the raw generation count behind it does not (1644 of 1673
   * generations in the real tree, in runs of hundreds). */
  failureStreaks: (signal?: AbortSignal) =>
    requestJson<FailureStreaksResponse>(`${BASE}/loop/failure-streaks`, { signal: signal ?? null }),

  /** Seat requests the loop has filed, newest first, decided ones included. Never 404s -- an empty
   * queue is an empty list, so this can be polled unconditionally. */
  pendingSeats: (signal?: AbortSignal) =>
    requestJson<PendingSeatsResponse>(`${BASE}/loop/pending-seats`, { signal: signal ?? null }),

  /** Stage-1 yes: keeps the card, names it, and moves it to the review shelf. It does not trade and
   * does not touch `roster_overlay.json` -- see `SeatStatus`'s own docstring on why this step is
   * deliberately not an endorsement to seat. Legal only from `"pending"`; `404` when no request exists
   * for the genome, `409` when the genome is not `"pending"` (the message names its current state and
   * what is legal from it -- render that sentence, then re-read `pendingSeats()` rather than leaving
   * the row asserting a stage the server no longer agrees with). Replaces the old single-step
   * `approveSeat` -- the backend keeps `POST .../approve` only as a deprecated alias for *this* route,
   * not for `seatCandidate`, precisely so an old client cannot seat a card in one step. */
  shelveSeat: (genomeId: string, note = "", signal?: AbortSignal) =>
    requestJson<PendingSeat>(
      `${BASE}/loop/pending-seats/${encodeURIComponent(genomeId)}/shelve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note }),
        signal: signal ?? null,
      },
    ),

  /** Stage-1 no. Legal only from `"pending"`, same 404/409 rules as `shelveSeat`. The desk is
   * untouched, and the loop will not re-ask for this genome however many times it clears the gate
   * again -- `"rejected"` is final. */
  rejectSeat: (genomeId: string, note = "", signal?: AbortSignal) =>
    requestJson<PendingSeat>(
      `${BASE}/loop/pending-seats/${encodeURIComponent(genomeId)}/reject`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note }),
        signal: signal ?? null,
      },
    ),

  /** Stage-2 yes: the *only* decision route that writes `roster_overlay.json`. Legal only from
   * `"shelved"`, same 404/409 rules as `shelveSeat`. This is the second, separate human decision the
   * pipeline exists to require -- clearing the promotion gate and being kept on the shelf are both, on
   * their own, not a reason to trade the card. */
  seatCandidate: (genomeId: string, note = "", signal?: AbortSignal) =>
    requestJson<PendingSeat>(
      `${BASE}/loop/pending-seats/${encodeURIComponent(genomeId)}/seat`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note }),
        signal: signal ?? null,
      },
    ),

  /** Stage-2 no: off the shelf, without ever seating it. Legal only from `"shelved"`, same 404/409
   * rules as `shelveSeat`. `"retired"` is final, exactly like `"rejected"`. */
  retireSeat: (genomeId: string, note = "", signal?: AbortSignal) =>
    requestJson<PendingSeat>(
      `${BASE}/loop/pending-seats/${encodeURIComponent(genomeId)}/retire`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note }),
        signal: signal ?? null,
      },
    ),

  /** The full case for or against seating one candidate -- see `Dossier`'s own docstring. Fetched
   * lazily, only once a reviewer expands a row: eagerly pulling a full dossier (evidence rows, field
   * context, cautions) for every one of the twenty-odd queued cards on page load would be a lot of
   * backend work nobody asked to see yet. `404` when the genome has no card on file. */
  dossier: (genomeId: string, signal?: AbortSignal) =>
    requestJson<Dossier>(
      `${BASE}/loop/candidates/${encodeURIComponent(genomeId)}/dossier`,
      { signal: signal ?? null },
    ),

  /** The rolling per-generation digest journal, newest generation first. Never 404s -- a loop that
   * has written no digest yet answers `{ total: 0, entries: [] }`. `limit`/`offset` paginate; an
   * omitted `limit` lets the backend apply its default (50), matching the optional-param convention
   * `generations`/`history` above already use. */
  journal: (params: { limit?: number; offset?: number } = {}, signal?: AbortSignal) => {
    const search = new URLSearchParams();
    if (params.limit !== undefined) search.set("limit", String(params.limit));
    if (params.offset !== undefined) search.set("offset", String(params.offset));
    const qs = search.toString();
    return requestJson<JournalResponse>(`${BASE}/loop/journal${qs ? `?${qs}` : ""}`, {
      signal: signal ?? null,
    });
  },
};
