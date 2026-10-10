/**
 * Typed client for the strategy-competition dashboard.
 *
 * Mirrors the contract two backend routers are being built against concurrently: a library router
 * (strategy cards by tier) and a rounds/jobs router (leaderboards, agent drill-downs, and the async
 * job that runs a new round). Field names below are written to match that contract exactly, field
 * for field, the same way `api/macro.ts` and `api/thesis.ts` mirror their own backend models.
 *
 * A few things here are easy to get wrong and are worth reading before using the types.
 *
 * **`median_excess`, `worst_excess` and `adjusted_excess` are `null`-able, and `null` is not zero.**
 * A card that ran zero comparable windows, or a window whose adjustment could not be computed, comes
 * back `null` — rendering that as `0.00%` states "broke even" about a figure that was never measured.
 * Use `formatSignedPctFraction`/`formatPctFraction` below, never a bare template string.
 *
 * **`per_window` is a partial map, not a fixed-shape record.** A card that did not run in a window
 * has no entry for it at all — absent, not a zeroed-out result. Always read it with `?.`, never
 * `per_window[window] ?? someDefault`, which would manufacture a result for a window the card never
 * touched.
 *
 * **A `provenance_constrained` window cannot be ranked against the others.** Its tradable universe
 * was only knowable from a 13F filing that postdates the window itself, so the "excess" recorded
 * there is not comparable to a window whose universe was known in advance. See
 * `PROVENANCE_CONSTRAINED_NOTE`.
 *
 * **A trade's `unrealised: true` means the position was still open at the window's end.** Its `pnl`
 * and `contribution` are a mark against the last price the window saw, not money actually taken —
 * this is a real distinction the underlying reports make, and flattening it into an ordinary trade
 * row overstates how much of a card's result is "banked".
 *
 * **`JobStatus["status"]` is exactly the union the backend enumerates, no more.** `tests/
 * test_frontend_contract.py` exists because this contract drifted once already: a Python enum
 * gained a member the TypeScript union did not know about, and because this project's `tsconfig.json`
 * sets `strict: true` but not `noImplicitReturns`, a `switch` over the old union with the new member
 * unhandled compiled cleanly and fell through to `undefined` at runtime — rendering a blank headline
 * in front of a user rather than failing the build. `jobStatusLabel` and `isTerminalJobStatus` below
 * both close the compile-time half of that hole with a `default` branch assigned to a local `const
 * _exhaustive: never` (see `exitReasonLabel` in `@/api/paperdesk` for why the runtime half of that
 * branch degrades instead of throwing); any new `switch` added over `JobRunStatus` in the page must
 * do the same.
 */

import { ApiRequestError, type DecimalString } from "@/api/client";
import { t } from "@/i18n";

// --- library ------------------------------------------------------------------------------------

export interface CardSummary {
  agent_id: string;
  display_name: string;
  discipline: string;
  universe: string[];
  entry: string;
  exit: string;
  stop_loss_pct: DecimalString | null;
  take_profit_pct: DecimalString | null;
  max_hold_days: number | null;
  max_positions: number;
  position_pct: DecimalString;
  /** `YYYY-MM-DD` — the last date the card's rules were designed/reviewed against, not a run date. */
  designed_through: string;
  thesis: string;
}

/**
 * One shelf of the library. `tier` is left as a plain `string` rather than a closed union: unlike
 * `JobRunStatus`, nothing on this page switches on it — it is only ever looped over and rendered as
 * a section heading, so a fifth tier arriving from the backend renders as one more section rather
 * than falling through a missing `case`.
 */
export interface LibraryTier {
  tier: string;
  label: string;
  cards: CardSummary[];
}

export interface LibraryResponse {
  tiers: LibraryTier[];
}

// --- rounds -------------------------------------------------------------------------------------

export interface RoundSummary {
  round_id: string;
  label: string;
  windows: string[];
  agents: number;
  has_report: boolean;
  has_brief: boolean;
  /**
   * Whether this round has a `results/` directory with run files in it. **A round with
   * `has_results: false` has no leaderboard and no selection** -- `GET .../leaderboard` answers 404
   * for it, by design (`RoundNotFoundError`), because there is nothing to rank.
   *
   * This field exists because its absence was a live defect. `/rounds` returns every directory under
   * `data/rounds`, including seven that hold only a `SELECTION.md` or a `run.txt` and no run files at
   * all, and the page seeded its selected round from `rounds[0]` -- which, under the old
   * lexicographic ordering, was `r9-2026-08`, one of the empty ones. The Leaderboard tab opened onto
   * a 404 and rendered nothing. Never default a round picker to a round with `has_results: false`,
   * and never present one as though a leaderboard were merely still loading.
   */
  has_results: boolean;
  /** Whether `GET .../selection` will answer for this round rather than 404. Requires a `live-1`
   * sub-window in the results tree, so it is strictly narrower than `has_results`. */
  has_selection: boolean;
  /** The round's ordinal parsed out of its id (`r11-2026-08` -> `11`), so callers sort numerically.
   * Sorting round ids as plain strings puts `r9` above `r13`; that is the ordering bug above. */
  sequence: number;
}

export interface RoundsResponse {
  rounds: RoundSummary[];
}

// --- window catalogue -----------------------------------------------------------------------------

/**
 * Which sampling scheme produced a window. `"r2"`/`"r4"` are the original named market-regime
 * windows (`gfc`, `covid`, `banks-2023`, …); `"special"` is `13f-legal`; round 5 replaces the regime
 * windows with a horizon ladder and adds two matrices for it: `"r5-ladder"` is the calendar-sampled
 * ladder itself (27 windows, 6 months to 10 years, no regard for market direction), and `"r5-bear"`
 * is the 6-window bear supplement -- windows deliberately chosen for a *falling* benchmark, so a
 * reader can tell the two arms apart rather than have them silently mixed. Left as a plain `string`
 * union rather than switched on anywhere with an `assertNever` guard: nothing here branches
 * exhaustively over it, it is only ever compared against `"r5-bear"` to render a badge.
 */
export type WindowMatrix = "r2" | "r4" | "special" | "r5-ladder" | "r5-bear";

/** The five rungs of the round-5 horizon ladder, shortest to longest. A window with `horizon: null`
 * has a length but not a *designed* horizon -- see `WindowCatalogueEntry.horizon`. */
export type Horizon = "6m" | "1y" | "3y" | "5y" | "10y";

/** `horizon`, shortest to longest -- the order the run form's grouped sections render in, not the
 * order the backend happens to return windows in. */
export const HORIZON_ORDER: Horizon[] = ["6m", "1y", "3y", "5y", "10y"];

/** Display label for one horizon group's heading. */
export const HORIZON_LABELS: Record<Horizon, string> = {
  "6m": "6 months",
  "1y": "1 year",
  "3y": "3 years",
  "5y": "5 years",
  "10y": "10 years",
};

/** The translated counterpart to `HORIZON_LABELS` -- a function so it reads the catalog fresh per
 * call rather than freezing the launch-time language, matching `purposeLabel`/`rankByLabel`. The
 * static map stays for any caller that only needs the key set. */
export function horizonLabel(horizon: Horizon): string {
  switch (horizon) {
    case "6m":
      return t("competition.horizon.6m");
    case "1y":
      return t("competition.horizon.1y");
    case "3y":
      return t("competition.horizon.3y");
    case "5y":
      return t("competition.horizon.5y");
    case "10y":
      return t("competition.horizon.10y");
    default: {
      const _exhaustive: never = horizon;
      void _exhaustive;
      return String(horizon);
    }
  }
}

/**
 * One backtest regime window, as the run form's own catalogue of choices — sourced from the same
 * constant the job runner validates `POST /jobs`'s `windows` against, so the form can only ever offer
 * what the backend will actually accept.
 *
 * `main: false` marks `13f-legal`, the one window whose tradable universe was only knowable from a
 * later 13F filing — the same fact `WindowBenchmark.provenance_constrained` flags on the leaderboard.
 * It exists only for cards whose universe came from a 13F filing, sits outside the eligibility gate,
 * and is not comparable with the eight regime windows, so the run form defaults it unchecked rather
 * than defaulting every window on.
 *
 * `horizon` is `null` for every pre-round-5 window (a named regime window has a length but not a
 * *designed* horizon) and one of `Horizon`'s five values for the round-5 ladder/bear-supplement
 * windows. The run form groups by this field when present and leaves a `null`-horizon window in its
 * existing, ungrouped presentation -- see `Competition.tsx`'s `groupWindowsByHorizon`.
 */
export interface WindowCatalogueEntry {
  window: string;
  /** `YYYY-MM-DD`. */
  start: string;
  /** `YYYY-MM-DD`. */
  end: string;
  label: string;
  main: boolean;
  matrix: WindowMatrix;
  horizon: Horizon | null;
}

/** Main windows first, then non-main; chronological by `start` within each group — the order the
 * backend already returns them in, not re-sorted here. */
export interface WindowsResponse {
  windows: WindowCatalogueEntry[];
}

// --- leaderboard ----------------------------------------------------------------------------------

export type RankBy = "median" | "worst" | "hit-rate" | "excess-per-exposure";

export const RANK_BY_OPTIONS: { value: RankBy; label: string }[] = [
  { value: "median", label: "Median excess" },
  { value: "worst", label: "Worst-window excess" },
  { value: "hit-rate", label: "Hit rate" },
  { value: "excess-per-exposure", label: "Excess per exposure" },
];

/** The translated counterpart to `RANK_BY_OPTIONS`'s own `label` field -- see `purposeLabel`'s
 * docstring above for why this is a function rather than a change to the static array (`goalDirectives
 * .ts`, outside this shard's scope fence, reads `RANK_BY_OPTIONS.map((o) => o.value)` directly). */
export function rankByLabel(rankBy: RankBy): string {
  switch (rankBy) {
    case "median":
      return t("competition.rankBy.median");
    case "worst":
      return t("competition.rankBy.worst");
    case "hit-rate":
      return t("competition.rankBy.hitRate");
    case "excess-per-exposure":
      return t("competition.rankBy.excessPerExposure");
    default: {
      const _exhaustive: never = rankBy;
      void _exhaustive;
      return String(rankBy);
    }
  }
}

/** SPY's own result for one window — rendered as a pinned row in the leaderboard itself, not only
 * inside a drill-down, so a reader can see what "excess" is excess *of* without leaving the table. */
export interface WindowBenchmark {
  window: string;
  sessions: number;
  benchmark_return: DecimalString;
  /** True when this window's tradable universe was only knowable from a later 13F filing — its
   * result cannot be ranked against the other windows. See `PROVENANCE_CONSTRAINED_NOTE`. */
  provenance_constrained: boolean;
}

export interface PerWindowResult {
  total_return: DecimalString;
  benchmark_return: DecimalString;
  excess: DecimalString;
  adjusted_excess: DecimalString | null;
  capital_exposure: number;
  capital_exposure_reconstructed: boolean;
  max_drawdown: DecimalString;
  trades: number;
  sessions: number;
}

export interface LeaderboardRow {
  rank: number;
  agent_id: string;
  display_name: string;
  discipline: string;
  windows_run: number;
  eligible: boolean;
  median_excess: DecimalString | null;
  worst_excess: DecimalString | null;
  hit_rate: number;
  mean_capital_exposure: number;
  total_trades: number;
  /** Keyed by window key. A card that did not run in a window is simply absent here — see the
   * module docstring. */
  per_window: Record<string, PerWindowResult>;
}

export type Purpose = "savings" | "trading" | "roth";

export const PURPOSE_LABELS: Record<Purpose, string> = {
  savings: "Savings",
  trading: "Trading",
  roth: "Roth IRA",
};

/**
 * The translated counterpart to `PURPOSE_LABELS` above -- a function, not a static record, so it reads
 * the catalog fresh on every call rather than freezing whatever language was active at module load.
 * `PURPOSE_LABELS` itself is left untouched (still English-only) because several components outside
 * this shard's scope fence index it directly (`Object.keys(PURPOSE_LABELS)`, `PURPOSE_LABELS[p]`) --
 * see this file's module docstring. Prefer this function in any new call site within the Competition
 * page core.
 */
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

/** One purpose, as the competition scores it.
 *
 *  `horizon_years_max === null` means the horizon is deliberately unstated, not missing -- render
 *  "unbounded", never a default. */
export interface PurposeInfo {
  purpose: Purpose;
  funding_shape: "lump_sum" | "monthly_contribution" | "annual_contribution";
  seed: DecimalString;
  contribution: DecimalString;
  horizon_years_min: number | null;
  horizon_years_max: number | null;
  tax_treatment: string;
  symbols_must_be_disjoint: boolean;
  benchmark: string;
  /** The quantity this purpose's board is ranked on. `adjusted_excess` for trading; `irr+cagr` for
   *  the two contribution-funded purposes. */
  scoring_basis: string;
}

export interface PurposesResponse {
  purposes: PurposeInfo[];
}

export interface LeaderboardResponse {
  round_id: string;
  rank_by: RankBy;
  purpose: Purpose;
  /** The quantity `rows` is ranked on. Sent with the rows rather than assumed by the renderer,
   *  because it differs by purpose: an IRR and an `adjusted_excess` are different quantities and
   *  putting one under the other's column heading is a category error, not a rounding one. */
  scoring_basis: string;
  /** Why `rows` is empty, when it is; `null` whenever there are rows.
   *
   *  An empty board has two very different causes -- these cards were measured and did badly, or
   *  they have never been run at all -- and a reader acts differently on each. Render this instead
   *  of an empty table. */
  unscored_reason?: string | null;
  windows: WindowBenchmark[];
  rows: LeaderboardRow[];
}

// --- agent drill-down -------------------------------------------------------------------------------

export interface TradeDetail {
  symbol: string;
  entry_date: string;
  exit_date: string;
  entry_price: DecimalString;
  exit_price: DecimalString;
  quantity: DecimalString;
  bars_held: number;
  exit_reason: string;
  return_pct: DecimalString;
  pnl: DecimalString;
  /** This trade's share of the card's total return for the window — what the trade table is sorted
   * by (descending `abs`). */
  contribution: DecimalString;
  /** See the module docstring: `true` means the position was still open at the window's end, and
   * `pnl`/`contribution` are a mark against the last price, not money actually taken. */
  unrealised: boolean;
}

export interface AgentWindowDetail {
  window: string;
  sessions: number;
  starting_equity: DecimalString;
  ending_equity: DecimalString;
  total_return: DecimalString;
  benchmark_return: DecimalString;
  excess: DecimalString;
  adjusted_excess: DecimalString | null;
  capital_exposure: number;
  max_drawdown: DecimalString;
  win_rate: number;
  profit_factor: DecimalString;
  unrealised_share: DecimalString;
  /** Share of *gross winning* trades' P&L captured by the three largest winners — the concentration
   * read, alongside `return_without_top3_winners`. */
  top3_share_of_gross_wins: number;
  return_without_top3_winners: DecimalString;
  rejections: string[];
  trades: TradeDetail[];
}

export interface AgentDetailResponse {
  round_id: string;
  agent_id: string;
  display_name: string;
  card: CardSummary;
  windows: AgentWindowDetail[];
}

// --- selection ------------------------------------------------------------------------------------

/**
 * One agent's pass/fail result against a single gate. `"A"`, `"L"`, `"C"` (in that key order) are the
 * three gates a card must clear before it can be ranked for a seat; `detail` is a free-form map of
 * whatever figures justify `reason` for this gate (e.g. `{ "windows_run": "6/6" }`) — rendered as
 * columns rather than parsed, since the set of keys can differ gate to gate.
 */
export interface GateOutcome {
  agent_id: string;
  passed: boolean;
  reason: string;
  detail: Record<string, string>;
}

/**
 * One row of the full ranking, and — when `seated` — one seat on the desk. `live_median`,
 * `live_hits`, `novel_names` arrive **preformatted as strings** (e.g. `"+7.41%"`, `"4/6"`, `"1.32"`)
 * — render them verbatim, never reparse or reformat them as numbers; `null` means the figure could
 * not be computed for this card, not zero.
 *
 * `seated_by` matters as much as `seated` itself: `"rule"` is a seat won on the ranking gates below,
 * but `"outside-competition"`/`"owner-override"` are seats granted for a reason the rule did not
 * produce — a card marked either of those must never be presented as if it won on the rule.
 */
export interface SelectionSeat {
  agent_id: string;
  rank: number | null;
  live_median: string | null;
  live_hits: string | null;
  novel_names: string | null;
  seated: boolean;
  seated_by: "rule" | "outside-competition" | "owner-override";
  note: string;
}

export interface SelectionResponse {
  round_id: string;
  rule_version: string;
  /** Keys `"A"`, `"L"`, `"C"`, in that order — see `GateOutcome`. */
  gates: Record<string, GateOutcome[]>;
  ranking: SelectionSeat[];
  seats: SelectionSeat[];
  /** Rendered verbatim and prominently wherever this response is shown — see `Competition.tsx`'s
   * `SelectionSection`. These carry the evidence's own limitations; the page misrepresents the
   * decision without them. */
  notes: string[];
}


// --- findings & follow-ups --------------------------------------------------------------------------

/**
 * What kind of thing one entry is. Deliberately a closed union *without* an `assertNever` switch
 * anywhere: like `LibraryTier.tier`, it is only ever looked up in `FINDING_KIND_LABELS` and rendered
 * as a chip, so a sixth kind arriving server-side renders under its raw key rather than crashing a
 * `switch`. Use `findingKindLabel` rather than indexing the record directly.
 *
 * - `"finding"` -- something the round established about the cards or the field.
 * - `"follow-up"` -- an open item the round left for a later round to settle.
 * - `"defect"` -- a fault found in the measuring instrument itself (`strategy-program/DEFECTS.md`).
 *   These are the entries that can invalidate a result rather than merely qualify it.
 * - `"decision"` -- a seating or scope decision recorded in `SELECTION.md`, including the owner
 *   overrides. A decision is not evidence; it is what was done in spite of, or because of, evidence.
 */
export type FindingKind = "finding" | "follow-up" | "defect" | "decision";

export const FINDING_KIND_LABELS: Record<string, string> = {
  finding: "Finding",
  "follow-up": "Follow-up",
  defect: "Defect",
  decision: "Decision",
};

/** Not indexed elsewhere in this codebase (verified: nothing imports `FINDING_KIND_LABELS` directly),
 * so unlike `PURPOSE_LABELS`/`RANK_BY_OPTIONS`/`PROVENANCE_CONSTRAINED_NOTE` above, this function can
 * translate directly rather than needing a separate additive export. */
export function findingKindLabel(kind: string): string {
  switch (kind) {
    case "finding":
      return t("competition.findingKind.finding");
    case "follow-up":
      return t("competition.findingKind.followUp");
    case "defect":
      return t("competition.findingKind.defect");
    case "decision":
      return t("competition.findingKind.decision");
    default:
      return FINDING_KIND_LABELS[kind] ?? kind;
  }
}

/**
 * One entry lifted out of a round's own written record.
 *
 * `body` is the source markdown's text, already extracted -- render it as **text**, never through
 * `dangerouslySetInnerHTML`. It comes off disk from files a person wrote by hand; treating it as
 * markup would make a stray `<` in a card rule into an injection surface for no reader benefit.
 *
 * `carries_forward: true` is the load-bearing flag: it marks an entry the round left *open* for the
 * next round to settle, which is exactly the set a reader planning the next round needs. It is not a
 * synonym for `kind === "follow-up"` -- an unfixed `"defect"` carries forward too, and a `"finding"`
 * whose prediction was contradicted usually does.
 */
export interface RoundFinding {
  id: string;
  round_id: string;
  kind: FindingKind;
  title: string;
  body: string;
  /** Where it was read from, e.g. `"SELECTION.md § 8"` -- rendered so a reader can go check the
   * claim against the file rather than take the page's word for it. */
  source: string;
  carries_forward: boolean;
}

export interface FindingsResponse {
  round_id: string;
  /** Everything the round established, `carries_forward` or not. */
  findings: RoundFinding[];
  /** The open items only -- every entry here also appears in `findings`. Rendering both lists is
   * intentional duplication: one is the record, the other is the agenda for the next round. */
  follow_ups: RoundFinding[];
  /** The files actually read to build this response. An empty `findings` list with a non-empty
   * `sources` means the round wrote nothing down, which is different from the round not existing. */
  sources: string[];
}

// --- narrative & next-round briefing ---------------------------------------------------------------

/**
 * A round's own written narrative -- the prose companion to `FindingsResponse`'s structured entries.
 *
 * `outcome` is **plain text with `\n\n` paragraph breaks, deliberately not markdown** -- split on the
 * blank line to render paragraphs and never inject it as HTML, matching `RoundFinding.body`'s own
 * "render as text" rule above.
 */
export interface RoundNarrative {
  round_id: string;
  title: string;
  focus: string;
  headline: string;
  outcome: string;
  seated: string[];
  owner_override: string | null;
  carries_forward: string[];
  sources: string[];
}

/**
 * What the next round is set up to run, before any job for it exists.
 *
 * `pre_registered: false` is not a warning to style away: this programme's protocol requires a
 * round's plan to be committed before any run exists, so an un-pre-registered next round is a real
 * blocker the UI must show, not a cosmetic nicety.
 *
 * **Two carries-forward lists, and merging them is a bug.** `authored_carries_forward` is prose a
 * human committed to the previous round's `NARRATIVE.json` as that round's own conclusions.
 * `carries_forward` is what `app.api.competition_findings` *parsed* out of the round's markdown, and
 * that module's docstring is blunt about what it is: "a heuristic keyword match over prose... A
 * caller rendering `carries_forward` as a hard fact rather than a 'the parser's best read' signal is
 * the mistake this docstring exists to prevent." It reads a genuinely open item as settled when the
 * prose avoids its keywords, and the reverse. Render the authored list as the record and the parsed
 * list as clearly secondary; never promote the second into the first's place to fill empty space.
 */
export interface NextRoundBriefing {
  previous_round_id: string | null;
  next_round_id: string;
  plan_path: string | null;
  pre_registered: boolean;
  focus: string | null;
  /** Hand-written in the previous round's `NARRATIVE.json`. Authoritative. */
  authored_carries_forward: string[];
  /** The findings parser's best read over the same round's prose. A guess, not a curated list. */
  carries_forward: RoundFinding[];
  blockers: string[];
}

// --- jobs -----------------------------------------------------------------------------------------

export interface CreateJobRequest {
  round_id: string;
  cards: string[];
  windows: string[];
  tier?: string;
}

/** How one (card, window) run inside a job finished — the backend types this
 * `Literal["ok","failed"]`. Every `switch` over it must end in a `default` branch narrowing to
 * `never` via `assertNever`, exactly like `JobRunStatus`: `tests/test_frontend_contract.py` exists
 * because this exact shape of drift (a third value added server-side, unhandled here) once rendered
 * a blank cell instead of failing the build. */
export type JobRunResultStatus = "ok" | "failed";

export interface JobRunResult {
  window: string;
  agent_id: string;
  status: JobRunResultStatus;
  total_return?: DecimalString;
  benchmark_return?: DecimalString;
  excess?: DecimalString;
  capital_exposure?: number;
  trades?: number;
  seconds?: number;
}

export interface JobCurrent {
  window: string;
  agent_id: string;
}

/**
 * A job's own lifecycle — see the module docstring's note on `tests/test_frontend_contract.py`.
 * Every `switch` over this value in `Competition.tsx` must end in a `default` branch that narrows to
 * `never` via `assertNever`, matching `jobStatusLabel` below.
 */
export type JobRunStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

/** The `202` body `POST /jobs` returns immediately — a subset of `JobStatus`'s fields, before a
 * single run has started. The page seeds its progress state from this and fills in the rest
 * (`completed_runs`, `log`, `results`, …) from the first poll of `GET /jobs/{job_id}`. */
export interface JobCreated {
  job_id: string;
  status: JobRunStatus;
  round_id: string;
  total_runs: number;
  created_at: string;
}

export interface JobStatus {
  job_id: string;
  status: JobRunStatus;
  round_id: string;
  cards: string[];
  windows: string[];
  total_runs: number;
  completed_runs: number;
  failed_runs: number;
  current: JobCurrent | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  elapsed_seconds: number | null;
  log: string[];
  results: JobRunResult[];
  error: string | null;
}

export interface JobsResponse {
  jobs: JobStatus[];
}

// --- requests ---------------------------------------------------------------------------------------

const BASE = "/api/competition";

/** Same five-line contract as every other API module's `requestJson` (see `api/thesis.ts`'s
 * docstring for why it is duplicated rather than imported). */
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

export const competitionApi = {
  library: (signal?: AbortSignal) =>
    requestJson<LibraryResponse>(`${BASE}/library`, { signal: signal ?? null }),

  rounds: (signal?: AbortSignal) =>
    requestJson<RoundsResponse>(`${BASE}/rounds`, { signal: signal ?? null }),

  /** The run form's own catalogue of valid windows — see `WindowCatalogueEntry`'s docstring. */
  windows: (signal?: AbortSignal) =>
    requestJson<WindowsResponse>(`${BASE}/windows`, { signal: signal ?? null }),

  /** One purpose's board. `purpose` defaults to `trading` server-side, which is what every card in
   * every committed round is, so omitting it returns exactly what this call returned before purposes
   * existed. An unknown purpose is a `422`, not a silent fallback. */
  leaderboard: (roundId: string, rankBy: RankBy, purpose: Purpose = "trading", signal?: AbortSignal) =>
    requestJson<LeaderboardResponse>(
      `${BASE}/rounds/${encodeURIComponent(roundId)}/leaderboard` +
        `?rank_by=${encodeURIComponent(rankBy)}&purpose=${encodeURIComponent(purpose)}`,
      { signal: signal ?? null },
    ),

  /** The three purposes, their funding, and the basis each is ranked on -- a catalogue read, so a
   * client renders three books from data rather than from three hardcoded assumptions. */
  purposes: (signal?: AbortSignal) =>
    requestJson<PurposesResponse>(`${BASE}/purposes`, { signal: signal ?? null }),

  agentDetail: (roundId: string, agentId: string, signal?: AbortSignal) =>
    requestJson<AgentDetailResponse>(
      `${BASE}/rounds/${encodeURIComponent(roundId)}/agents/${encodeURIComponent(agentId)}`,
      { signal: signal ?? null },
    ),

  /** A round's own written record -- findings, defects, decisions, and the open items it leaves for
   * the next round. A `404` means the round directory itself is unknown; a round that simply wrote
   * nothing down answers `200` with empty lists, which the page renders as a designed empty state
   * rather than an error. */
  findings: (roundId: string, signal?: AbortSignal) =>
    requestJson<FindingsResponse>(`${BASE}/rounds/${encodeURIComponent(roundId)}/findings`, {
      signal: signal ?? null,
    }),

  /** The gate tables and resulting desk roster for a round — see `SelectionResponse`. A `404` means
   * this round has no selection recorded yet, surfaced by the page as a designed empty state rather
   * than a generic error. */
  selection: (roundId: string, signal?: AbortSignal) =>
    requestJson<SelectionResponse>(`${BASE}/rounds/${encodeURIComponent(roundId)}/selection`, {
      signal: signal ?? null,
    }),

  /** A round's own written narrative — see `RoundNarrative`. `404` means this round has no authored
   * narrative, an ordinary state rather than an error (a round can have results and findings but no
   * narrative prose yet). This is deliberately **not** swallowed here — it propagates as the same
   * `ApiRequestError` `selection`/`findings` raise for their own 404s, so the caller tracks a
   * `narrativeNotFound` boolean exactly the way the page already tracks `selectionNotFound`. */
  narrative: (roundId: string, signal?: AbortSignal) =>
    requestJson<RoundNarrative>(`${BASE}/rounds/${encodeURIComponent(roundId)}/narrative`, {
      signal: signal ?? null,
    }),

  /** What the next round is set up to run, and whether it is actually cleared to -- see
   * `NextRoundBriefing`. Takes no round id: the backend resolves "next" from the round catalogue
   * itself. */
  nextRound: (signal?: AbortSignal) =>
    requestJson<NextRoundBriefing>(`${BASE}/next-round`, { signal: signal ?? null }),

  /** `409` means a round is already running — the response body names the live job id, and the
   * caller must surface that text, not retry. `422` means an unknown card/window/round_id. Both
   * arrive as `ApiRequestError`s carrying the server's own message. */
  createJob: (request: CreateJobRequest, signal?: AbortSignal) =>
    requestJson<JobCreated>(`${BASE}/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: signal ?? null,
    }),

  jobs: (signal?: AbortSignal) => requestJson<JobsResponse>(`${BASE}/jobs`, { signal: signal ?? null }),

  job: (jobId: string, signal?: AbortSignal) =>
    requestJson<JobStatus>(`${BASE}/jobs/${encodeURIComponent(jobId)}`, { signal: signal ?? null }),

  /** Cancels a running job. Returns the job's own status (normally `"cancelled"`) rather than an
   * empty body, so the caller can render it exactly like any other poll result. */
  cancelJob: (jobId: string, signal?: AbortSignal) =>
    requestJson<JobStatus>(`${BASE}/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
      signal: signal ?? null,
    }),
};

// --- display helpers: job status --------------------------------------------------------------------

/**
 * Exhaustive at compile time, forgiving at runtime -- the pattern pinned by `exitReasonLabel` in
 * `@/api/paperdesk` (see that function's docstring for the concrete page-down failure it exists to
 * prevent). Every `switch` below still assigns its `default` branch to a local `const _exhaustive:
 * never`, so `tsc` fails the moment a union here gains a member without a case -- but nothing below
 * *throws* over a value that reaches it anyway, because every one of these unions describes data this
 * page receives from the server rather than constructs itself, and a throwing default escapes render
 * into the route's `ErrorBoundary` exactly the way `rebalance_trim` once did to Paper Desk.
 */

export function jobStatusLabel(status: JobRunStatus): string {
  switch (status) {
    case "queued":
      return t("status.queued");
    case "running":
      return t("status.running");
    case "succeeded":
      return t("status.succeeded");
    case "failed":
      return t("status.failed");
    case "cancelled":
      return t("status.cancelled");
    default: {
      const _exhaustive: never = status;
      void _exhaustive;
      return String(status);
    }
  }
}

/** Whether a job's polling loop should stop. `"queued"`/`"running"` keep the `setInterval` alive;
 * every other value is an end state. An unrecognised status is treated as non-terminal -- the
 * conservative reading, since it keeps the poll alive rather than silently dropping a live job's
 * status updates over a value this build has not been taught to end on. */
export function isTerminalJobStatus(status: JobRunStatus): boolean {
  switch (status) {
    case "succeeded":
    case "failed":
    case "cancelled":
      return true;
    case "queued":
    case "running":
      return false;
    default: {
      const _exhaustive: never = status;
      void _exhaustive;
      return false;
    }
  }
}

export function jobRunResultStatusLabel(status: JobRunResultStatus): string {
  switch (status) {
    case "ok":
      return t("competition.jobRunResult.ok");
    case "failed":
      return t("status.failed");
    default: {
      const _exhaustive: never = status;
      void _exhaustive;
      return String(status);
    }
  }
}

/** `"pos" | "neg" | ""` colour class for one run's own outcome inside a job, matching `fractionTone`'s
 * naming below. `""` (no colour) is the degrade for a status this build does not recognise -- neither
 * "pos" nor "neg" is a safe guess about an outcome this function cannot classify. */
export function jobRunResultTone(status: JobRunResultStatus): "pos" | "neg" | "" {
  switch (status) {
    case "ok":
      return "pos";
    case "failed":
      return "neg";
    default: {
      const _exhaustive: never = status;
      void _exhaustive;
      return "";
    }
  }
}

/** Display label for one seat's `seated_by`. `"rule"` reads as an unqualified win; the other two are
 * deliberately phrased so neither can be mistaken for "won on the rule" at a glance — see
 * `SelectionSeat`'s docstring. */
export function seatedByLabel(seatedBy: SelectionSeat["seated_by"]): string {
  switch (seatedBy) {
    case "rule":
      return t("competition.seatedBy.rule");
    case "outside-competition":
      return t("competition.seatedBy.outsideCompetition");
    case "owner-override":
      return t("competition.seatedBy.ownerOverride");
    default: {
      const _exhaustive: never = seatedBy;
      void _exhaustive;
      return String(seatedBy);
    }
  }
}

/** Why a `provenance_constrained` window is marked and excluded from ranking comparisons — rendered
 * next to the chip, not only implied by it. */
export const PROVENANCE_CONSTRAINED_NOTE =
  "Not comparable — this window's tradable universe was only knowable from a later 13F filing, so its result cannot be ranked against the other windows.";

/** The translated counterpart to `PROVENANCE_CONSTRAINED_NOTE` above -- a function for the same reason
 * `purposeLabel` is: `LibrarySection.tsx`, outside this shard's scope fence, reads the static constant
 * directly, so it is left untouched and this file's own components call this instead. */
export function provenanceConstrainedNote(): string {
  return t("competition.provenanceConstrained.note");
}

// --- decimal-string formatting -----------------------------------------------------------------------
// String arithmetic only, never `parseFloat` — matching `api/institutions.ts`'s `formatWeight`/
// `formatSharesPctChange`, which this pair is adapted from. A long decimal string must never round
// through an IEEE double on its way to the screen.

/**
 * `value` is a fraction of one (`"0.0272"` -> `"2.72%"`), matching every excess/return/exposure
 * figure in this contract. `null` renders as an em dash, never `"0.00%"` — see the module docstring
 * on `median_excess`/`worst_excess`/`adjusted_excess`.
 */
export function formatPctFraction(value: DecimalString | null): string {
  if (value === null) return "—";
  const trimmed = value.trim();
  const negative = trimmed.startsWith("-");
  const digits = trimmed.replace(/^[+-]/, "");
  const [wholeRaw = "", fracRaw = ""] = digits.split(".");
  if (/^0*$/.test(wholeRaw) && /^0*$/.test(fracRaw)) return "0.00%";
  // Fraction -> percent shifts the decimal point two places right, same as `formatWeight`.
  const fracPadded = (fracRaw + "0000").slice(0, 4);
  const wholeDigits = ((wholeRaw || "0") + fracPadded.slice(0, 2)).replace(/^0+(?=\d)/, "");
  const fracPct = fracPadded.slice(2, 4);
  if (wholeDigits === "0" && fracPct === "00") return negative ? ">-0.01%" : "<0.01%";
  return `${negative ? "-" : ""}${wholeDigits}.${fracPct}%`;
}

/** Same as `formatPctFraction`, with an explicit `+` on a positive, non-zero result — colour is
 * never the only signal for direction on this page, matching `formatSignedMoney` (`api/portfolio.ts`)
 * and `formatSharesPctChange` (`api/institutions.ts`). */
export function formatSignedPctFraction(value: DecimalString | null): string {
  if (value === null) return "—";
  const rendered = formatPctFraction(value);
  const alreadySigned = rendered.startsWith("-") || rendered.startsWith(">") || rendered.startsWith("<");
  return alreadySigned || rendered === "0.00%" ? rendered : `+${rendered}`;
}

/** `"pos" | "neg" | ""` colour class for a signed fraction — `""` for exactly zero or `null`, so a
 * withheld or flat figure never picks up gain/loss colouring it did not earn. Mirrors
 * `moneyTone` (`api/portfolio.ts`). */
export function fractionTone(value: DecimalString | null): "pos" | "neg" | "" {
  if (value === null) return "";
  const trimmed = value.trim();
  if (/^[+-]?0*(\.0*)?$/.test(trimmed)) return "";
  return trimmed.startsWith("-") ? "neg" : "pos";
}

/** A plain 0..1 ratio delivered as a JSON `number` (`hit_rate`, `mean_capital_exposure`,
 * `capital_exposure`, `win_rate`, `top3_share_of_gross_wins`) — these are statistics, not ledger
 * figures, so ordinary float formatting is fine. `null`/non-finite renders as an em dash. */
export function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

/** A dollar-denominated `DecimalString` (`entry_price`, `exit_price`, `pnl`, `contribution`,
 * `starting_equity`, `ending_equity`) — string arithmetic only, matching `formatMoney`
 * (`api/tax.ts`), duplicated rather than imported for the reason every other api module in this
 * project gives for its own copy. */
export function formatDecimalMoney(value: DecimalString | null): string {
  if (value === null) return "—";
  const trimmed = value.trim();
  const negative = trimmed.startsWith("-");
  const digits = trimmed.replace(/^[+-]/, "");
  const [wholeRaw, fracRaw = ""] = digits.split(".");
  const whole = (wholeRaw || "0").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const frac = (fracRaw + "00").slice(0, 2);
  return `${negative && whole + frac !== "000" ? "-" : ""}$${whole}.${frac}`;
}

/** Signed dollar figure for a per-trade P&L/contribution column that also carries colour. */
export function formatSignedDecimalMoney(value: DecimalString | null): string {
  if (value === null) return "—";
  const trimmed = value.trim();
  const isZeroValue = /^[+-]?0*(\.0*)?$/.test(trimmed);
  if (isZeroValue || trimmed.startsWith("-")) return formatDecimalMoney(value);
  return `+${formatDecimalMoney(value)}`;
}

/** A share/contract count — keeps a genuine fractional share, drops only wire padding, matching
 * `formatShares` (`api/institutions.ts`). */
export function formatQuantity(value: DecimalString | null): string {
  if (value === null) return "—";
  const trimmed = value.trim();
  const negative = trimmed.startsWith("-");
  const digits = trimmed.replace(/^[+-]/, "");
  const [wholeRaw, fracRaw = ""] = digits.split(".");
  const whole = (wholeRaw || "0").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const significant = fracRaw.replace(/0+$/, "");
  const frac = significant ? `.${significant}` : "";
  return `${negative && whole + significant !== "0" ? "-" : ""}${whole}${frac}`;
}

/** A plain ratio like `profit_factor` (`"1.8"`) — rendered verbatim rather than reparsed, since the
 * server already chose its own precision and reformatting through a float would be arithmetic on a
 * `DecimalString` for no benefit. */
export function formatRatioString(value: DecimalString | null): string {
  if (value === null) return "—";
  return value.trim();
}

export function formatIntOrDash(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString();
}

/**
 * Ordering comparator for two decimal strings that never parses either into a float — copied
 * verbatim from `pages/Institutions.tsx`'s `compareDecimalStrings` (not imported: that file is
 * owned by another agent and out of this page's scope fence). Pads both fractional parts to the
 * same length and compares as `BigInt` rather than converting either side to `Number`. Used to sort
 * the trade table by `abs(contribution)` descending without ever coercing a `DecimalString` through
 * an IEEE double.
 */
export function compareDecimalStrings(a: DecimalString, b: DecimalString): number {
  const parse = (v: DecimalString) => {
    const trimmed = v.trim();
    const negative = trimmed.startsWith("-");
    const digits = trimmed.replace(/^[+-]/, "");
    const [wholeRaw, fracRaw = ""] = digits.split(".");
    return { negative, wholeRaw: wholeRaw || "0", fracRaw };
  };
  const pa = parse(a);
  const pb = parse(b);
  const fracLen = Math.max(pa.fracRaw.length, pb.fracRaw.length);
  const scale = (p: ReturnType<typeof parse>): bigint => {
    const magnitude = BigInt(p.wholeRaw + p.fracRaw.padEnd(fracLen, "0"));
    return p.negative ? -magnitude : magnitude;
  };
  const sa = scale(pa);
  const sb = scale(pb);
  return sa < sb ? -1 : sa > sb ? 1 : 0;
}

/** Absolute value of a `DecimalString`, for sorting by magnitude (the trade table's `abs(contribution)`
 * descending order) without ever parsing to a float. */
export function absDecimalString(value: DecimalString): DecimalString {
  const trimmed = value.trim();
  return trimmed.startsWith("-") ? trimmed.slice(1) : trimmed;
}
