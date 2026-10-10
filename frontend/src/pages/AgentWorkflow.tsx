/**
 * Agent Workflow: the orchestrator desk. One staged run classifies the market regime, selects a
 * strategy card (tax-aware), scans it for entry candidates, runs child Trading Agents and Vibe
 * Trading runs for research, synthesises an entry plan, and stages next-open orders onto a
 * persistent paper book -- one book per arm, so the same plan can be measured gated and ungated.
 *
 * Three parts, per the owner's brief (`docs/AGENT-DESK-CONTRACT.md`, "Page layout" and the desk's own
 * "Agent Workflow" section):
 *
 * 1. **A static explainer** (`EXPLAINER_STEPS` below), rendered from a constant, never fetched.
 * 2. **The run panel**: a form (strategy card or auto-select, budget, max research symbols, weekly
 *    research budget, which arms are enabled, and a Universe mode toggle -- "card" the strategy
 *    card's own static universe, unchanged default, or "screen" a dynamic discovery-selector
 *    shortlist, which reveals a Selector (a named Round-33 selector, or "raw pool + rank key" to keep
 *    today's `candidate_pool`+`rank_key` behaviour -- the two are mutually exclusive server-side, so
 *    the form sends one or the other, never both), an optional screen-entry-rule override, and an
 *    optional top-N), a live progress board keyed on `stage_id` and grouped by `layer` -- including
 *    the per-symbol `research_{SYM}`/`vibe_{SYM}` stages that only appear once a run reaches candidate
 *    research -- per-stage output, the final entry plan (`final_md`), and recent runs.
 * 3. **The book panel**: `GET /book` returns one `WorkflowBook` per enabled arm; each shows cash,
 *    equity, open positions, and every order (pending and filled) with its fill price and source, and
 *    a `universe_source` badge -- a book is identified by the pair `(arm, universe_source)`, not `arm`
 *    alone, once screen-mode books exist alongside the card-mode ones. "Execute pending (next open)"
 *    calls `POST /book/execute`. A Card/Screened toggle here also drives the study and candidates
 *    panels below (`universeFilter` state) -- its default ("Card") omits `universe_source` from the
 *    book/study/execute requests, so the page's very first fetch of each is byte-for-byte what it
 *    was before this toggle existed. The candidates request is the one exception and always sends
 *    the filter explicitly: an omitted `universe_source` on `GET /candidates` means "unfiltered"
 *    (card and screen rows mixed), not "card".
 * 4. **The study panel**: `GET /study` -- per-arm metrics (each row also carrying its own
 *    `universe_source` badge), paired bootstrap significance against `raw_signal`, vibe verdict
 *    compliance, the directional-study `note`, rendered prominently rather than buried since this is a
 *    directional study, not a backtest with guaranteed fills, and (when the backend serves it) a
 *    per-gate discrimination table -- passed-vs-refused hit rates, mean diff, p/q -- with a plain-text
 *    notice when every gate's `passed_n` is `0`, i.e. not yet measurable.
 * 5. **The candidates panel**: `GET /candidates` -- individual scan observations: why a candidate was
 *    skipped (`skip_reason`/`skip_detail`/`avoided_cost_usd`) and whether each gate's ruling came from
 *    a fresh child-agent call or a cached one (`verdict_source`), plus resolved forward/alpha returns.
 *
 * Every fetch owns its own `FetchPhase` (`"loading" | "loaded" | "error"`), the same pattern
 * `VibeTrading.tsx`/`TradingAgents.tsx` use -- one bad request must never blank the rest of the page
 * -- and each top-level panel is wrapped in its own `PanelBoundary` for the same reason one level
 * down.
 *
 * **Polling**: `GET /runs/{run_id}` every 2000ms while `state` is `"queued"` or `"running"` --
 * `isRunActive` from `api/workflow.ts`, mirroring `VibeTrading.tsx`'s own poll effect line for line.
 * No SSE.
 *
 * **`degraded`/`blocked`/`failed` are three different claims**, same as the sibling desks: `degraded`
 * ran and produced output that failed a grounding check; `blocked` never ran because an upstream
 * dependency failed; `failed` ran and errored. Collapsing any two would misreport what happened.
 *
 * **No markdown renderer in this codebase's dependencies** -- `output_md`/`final_md` render inside
 * `<pre className="wf-output-md">` with `white-space: pre-wrap`, not through a parser this app does
 * not have.
 */
import { useEffect, useState } from "react";

import { formatPctFraction } from "@/api/competition";
import { formatMoney } from "@/api/tax";
import { formatFetchError as errorMessage, useFetch } from "@/hooks/useFetch";
import { Trans, useT, type MessageKey, type Translator } from "@/i18n";
import {
  isRunActive,
  workflowApi,
  type CandidateObservation,
  type DeskRun,
  type ExecuteRequest,
  type GateDecision,
  type GateDiscrimination,
  type StageRecord,
  type StageState,
  type UniverseMode,
  type WorkflowArm,
  type WorkflowCandidates,
  type WorkflowConfig,
  type WorkflowRunRequest,
  type WorkflowStudy,
} from "@/api/workflow";
import InfoNote from "@/components/InfoNote";
import PanelBoundary from "@/components/PanelBoundary";
import { ScrollRegion } from "@/components/ScrollPanel";
import StatusPill, { type PillTone } from "@/components/StatusPill";
import Term from "@/components/Term";

import "./AgentWorkflow.css";

/** Matches the sibling desks' own poll interval -- not tied to anything server-side. */
const POLL_INTERVAL_MS = 2000;

/** Sentinel for "auto-select a card from the regime call" in the card dropdown -- a real
 *  `agent_id` never looks like this, so it can never collide with a configured card. */
const AUTO_CARD = "__auto__";

/**
 * The minimum detectable effect this study was pre-registered against, in percentage points.
 *
 * From `docs/reports/workflow-study-power-analysis.md` §2: at the pre-registered bar of 40 gated
 * candidates, reaching conventional 80% power (alpha 0.05, two-sided) needs a true hit-rate gap of
 * roughly **35pp** between the set a gate passed and the set it refused. It is a static figure and
 * not recomputed here on purpose: the standard deviation of the paired differences never crosses
 * the wire (`WorkflowStudy.paired` carries `mean_daily_diff` and `bootstrap_p` and nothing else),
 * so the usual `MDE ~= 2.8 * sd / sqrt(n)` closed form has no `sd` to work with client-side.
 * Printing a number derived from an invented `sd` would be worse than quoting the simulation that
 * was actually run.
 */
const PRE_REGISTERED_MDE_PP = 35;

/**
 * How many gated candidates the significance figures above are computed over -- the `n` the power
 * analysis is indexed on.
 *
 * Read off the discrimination rows (`passed_n + refused_n`) rather than `paired.length`, which
 * counts *arms*, not observations: three rows in the paired table is three comparisons of the same
 * window, never "n = 3". The maximum across gates, not the sum: each row is the same candidate pool
 * split by a different gate, so summing would multiply one pool by the number of gates.
 *
 * `null` when no discrimination rows exist at all -- an older backend, or a window with no gated
 * candidates. `0` is a real answer (rows exist, nothing gated yet) and stays distinguishable from it.
 */
function gatedCandidateN(study: WorkflowStudy): number | null {
  const rows = study.discrimination;
  if (!rows || rows.length === 0) return null;
  return rows.reduce((best, row) => Math.max(best, row.passed_n + row.refused_n), 0);
}

/**
 * The desk's static explainer, in the order a run actually proceeds: regime, then strategy, then
 * candidates, then research fanned out per symbol, then a synthesised plan, then execution -- and
 * why the four arms exist at all (to measure whether the extra research gates are worth their cost).
 * Rendered from this constant, never fetched.
 */
const EXPLAINER_STEP_KEYS: readonly MessageKey[] = [
  "agentWorkflow.explainer.step1",
  "agentWorkflow.explainer.step2",
  "agentWorkflow.explainer.step3",
  "agentWorkflow.explainer.step4",
  "agentWorkflow.explainer.step5",
  "agentWorkflow.explainer.step6",
];

function stageStateLabel(state: StageState, t: Translator): string {
  switch (state) {
    case "pending":
      return t("status.pending");
    case "running":
      return t("status.running");
    case "succeeded":
      return t("status.succeeded");
    case "degraded":
      return t("agentWorkflow.stageState.degraded");
    case "failed":
      return t("status.failed");
    case "blocked":
      return t("agentWorkflow.stageState.blocked");
    case "skipped":
      return t("agentWorkflow.stageState.skipped");
    default: {
      const _exhaustive: never = state;
      void _exhaustive;
      return String(state);
    }
  }
}

/** Maps a stage's state to the shared `StatusPill` tone vocabulary (docs/COPY-STYLE.md), the same
 *  six-tone mapping the sibling desks use for their own `wf-stage-*`/`vibe-stage-*`/`ta-stage-*`
 *  palettes: `pending`→neutral, `running`→info, `succeeded`→ok, `degraded`→warn, `failed`→bad,
 *  `blocked`→special, `skipped`→neutral. `StageState` is the same fully-enumerated, stable union
 *  `stageStateLabel` above switches on, so a throwing `never` default is safe here too. */
function stageTone(state: StageState): PillTone {
  switch (state) {
    case "pending":
      return "neutral";
    case "running":
      return "info";
    case "succeeded":
      return "ok";
    case "degraded":
      return "warn";
    case "failed":
      return "bad";
    case "blocked":
      return "special";
    case "skipped":
      return "neutral";
    default: {
      const _exhaustive: never = state;
      void _exhaustive;
      return "neutral";
    }
  }
}

/** Renders `universe_source`/`universe_mode` without a throwing exhaustiveness check -- the opposite
 *  of `stageStateLabel` above. `StageState` is a fully enumerated, stable union this build controls
 *  both ends of, so a `never` check there is safe; `UniverseMode` is a brand-new, less-stable field a
 *  running backend may not have started sending yet (`docs/AGENT-DESK-CONTRACT.md`'s "Agent Workflow"
 *  section flags `GET /book` as not yet extended to include it), and a closed union with a throwing
 *  default over server-supplied data is exactly what took the Paper Desk page down once already
 *  (`docs/closed-unions-over-server-data-kill-pages`). An unrecognised or missing value falls back to
 *  a plain label instead of crashing the panel it renders in. */
function universeSourceLabel(source: string | undefined, t: Translator): string {
  switch (source) {
    case "screen":
      return t("agentWorkflow.universe.screened");
    case "card":
      return t("agentWorkflow.universe.card");
    default:
      return source || t("agentWorkflow.universe.card");
  }
}

/** Fallback candidate pools and rank keys, used only when `GET /config` omits `candidate_pools`/
 *  `rank_keys` (an older backend) -- `config_payload` now echoes this catalogue
 *  (`WorkflowConfig.candidate_pools`/`rank_keys`), so these are a safety net, not the primary
 *  source. Matches `app.workflow.service`'s own validation set
 *  (`app.discovery.candidates.sector_candidates`/`theme_candidates`,
 *  `app.discovery.selector.RANK_KEYS`). */
const CANDIDATE_POOLS: readonly string[] = ["sector-etf", "theme-etf"];
const RANK_KEYS: readonly string[] = ["mom12_1", "mom6", "trend"];

/** Sentinel for "raw pool + rank key" in the screen-mode Selector dropdown -- a real `selector_id`
 *  never looks like this. Choosing this option keeps today's `candidate_pool`+`rank_key` behaviour;
 *  choosing any other option sends `selector_id` and omits both. */
const RAW_SELECTOR = "__raw_pool__";

/** The Round-33 promoted selector -- defaulted to when `config.selector_ids` includes it, per the
 *  contract. Falls back to `RAW_SELECTOR` when the backend hasn't rolled it out (or seated it) yet. */
const PROMOTED_SELECTOR = "mom12_1_hysteresis";

/** Groups a run's stages by `layer`, ascending, so the board reads top-to-bottom in dependency
 *  order -- mirrors `VibeTrading.tsx`'s own `groupByLayer`, duplicated per this codebase's
 *  per-module convention rather than shared. */
function groupByLayer(stages: StageRecord[]): [number, StageRecord[]][] {
  const map = new Map<number, StageRecord[]>();
  for (const stage of stages) {
    const bucket = map.get(stage.layer);
    if (bucket) {
      bucket.push(stage);
    } else {
      map.set(stage.layer, [stage]);
    }
  }
  return [...map.entries()].sort((a, b) => a[0] - b[0]);
}

const ALL_ARMS: readonly WorkflowArm[] = ["raw_signal", "ta_gated", "vibe_gated", "full_workflow"];

/** The two views this page splits into (docs/STRATEGY-AGENT-UX-ANALYSIS.md §A5/C4): "Run" is the
 *  operator console (run form + active-run progress + recent runs); "Measure" is the readout
 *  (paper book + effectiveness study + candidates). Defaults to "Run" -- starting a run is the
 *  common case, and the measurement panels are stale/empty until a run has actually settled at
 *  least once. The explainer above both is not part of this switch; it frames either view. */
type WorkflowView = "run" | "measure";

export default function AgentWorkflow() {
  const { t, lang } = useT();
  const [view, setView] = useState<WorkflowView>("run");

  // --- config ----------------------------------------------------------------------------------
  const configResult = useFetch<WorkflowConfig>((signal) => workflowApi.config(signal), [], {
    formatError: (err) => errorMessage(err, t("agentWorkflow.errors.config")),
  });
  const config = configResult.data;
  const configPhase = configResult.phase;
  const configMessage = configResult.error;

  useEffect(() => {
    if (!config) return;
    setCardChoice((prev) => prev ?? AUTO_CARD);
    setBudgetUsd((prev) => prev ?? config.default_budget_usd);
    setMaxResearchSymbols((prev) => prev ?? String(config.default_max_research_symbols));
    setArmsEnabled((prev) => prev ?? new Set(ALL_ARMS));
    // Default to the Round-33 promoted selector when the backend has seated it; otherwise the
    // raw pool+rank-key path, today's only behaviour.
    setSelectorChoice((prev) =>
      prev ?? (config.selector_ids?.includes(PROMOTED_SELECTOR) ? PROMOTED_SELECTOR : RAW_SELECTOR),
    );
  }, [config]);

  // --- recent runs -------------------------------------------------------------------------------
  // `lang` (not `t`) drives the re-fetch, matching the original `loadRecentRuns` `useCallback`'s own
  // `[t]` dependency array -- `t`'s own identity already changes with `lang`, and `useFetch` reads
  // `formatError` via a ref rather than as a dependency, so `lang` is named directly here.
  const recentRunsResult = useFetch(
    (signal) => workflowApi.listRuns(undefined, signal).then((res) => res.runs),
    [lang],
    { formatError: (err) => errorMessage(err, t("agentWorkflow.errors.recentRuns")) },
  );
  const recentRuns = recentRunsResult.data ?? [];
  const recentRunsPhase = recentRunsResult.phase;
  const recentRunsMessage = recentRunsResult.error;
  const loadRecentRuns = recentRunsResult.reload;

  // --- run form ------------------------------------------------------------------------------------
  const [cardChoice, setCardChoice] = useState<string | null>(null);
  const [budgetUsd, setBudgetUsd] = useState<string | null>(null);
  const [maxResearchSymbols, setMaxResearchSymbols] = useState<string | null>(null);
  const [armsEnabled, setArmsEnabled] = useState<Set<WorkflowArm> | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  // Dynamic universe: "card" (default, today's behaviour) or "screen" (a discovery-selector
  // shortlist). The three screen-only fields stay `null` -- and thus off the request body entirely
  // -- until the reader actually picks "screen", so a card-mode submission is byte-for-byte the same
  // request it was before this control existed.
  const [universeMode, setUniverseMode] = useState<UniverseMode>("card");
  const [candidatePool, setCandidatePool] = useState<string | null>(null);
  const [rankKey, setRankKey] = useState<string | null>(null);
  const [screenTopN, setScreenTopN] = useState<string>("");
  // `null` until the config's default resolves it -- see the config-load effect above. `RAW_SELECTOR`
  // keeps today's candidate_pool+rank_key behaviour; anything else is a named selector id.
  const [selectorChoice, setSelectorChoice] = useState<string | null>(null);
  const [screenEntryRule, setScreenEntryRule] = useState<string>("");
  // Both universe modes send this -- unlike the three screen-only fields above, it is not gated on
  // `universeMode === "screen"`.
  const [weeklyBudgetUsd, setWeeklyBudgetUsd] = useState<string>("");

  const toggleArm = (arm: WorkflowArm) => {
    setArmsEnabled((prev) => {
      const next = new Set(prev ?? ALL_ARMS);
      if (next.has(arm)) next.delete(arm);
      else next.add(arm);
      return next;
    });
  };

  // --- the active run + its stage board --------------------------------------------------------------
  const [run, setRun] = useState<DeskRun | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [selectedStageId, setSelectedStageId] = useState<string | null>(null);

  // Polls `getRun` every 2000ms while the run is queued/running -- mirrors `VibeTrading.tsx`'s own
  // poll effect. The dependency array (`run_id`, `state`) clears the interval the moment `state`
  // settles.
  useEffect(() => {
    if (!run || !isRunActive(run.state)) return;
    const runId = run.run_id;
    const id = setInterval(() => {
      workflowApi
        .getRun(runId)
        .then((updated) => setRun(updated))
        .catch(() => {
          // A transient poll failure is not fatal -- the board keeps its last known state and the
          // next tick tries again.
        });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [run?.run_id, run?.state]);

  // Once a run settles, the recent-runs list and the book/study/candidates panels are stale --
  // refresh them exactly once per terminal transition.
  useEffect(() => {
    if (run && !isRunActive(run.state)) {
      loadRecentRuns();
      booksResult.reload();
      studyResult.reload();
      candidatesResult.reload();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.run_id, run?.state, loadRecentRuns]);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!config) return;
    setStartError(null);
    setStarting(true);
    try {
      const parsedMax = maxResearchSymbols !== null ? Number.parseInt(maxResearchSymbols, 10) : NaN;
      const parsedTopN = screenTopN.trim() !== "" ? Number.parseInt(screenTopN, 10) : NaN;
      const effectiveCandidatePools =
        config.candidate_pools && config.candidate_pools.length > 0
          ? config.candidate_pools
          : CANDIDATE_POOLS;
      const effectiveRankKeys =
        config.rank_keys && config.rank_keys.length > 0 ? config.rank_keys : RANK_KEYS;
      const usingNamedSelector =
        universeMode === "screen" && !!selectorChoice && selectorChoice !== RAW_SELECTOR;
      const body: WorkflowRunRequest = {
        agent_card_id: cardChoice && cardChoice !== AUTO_CARD ? cardChoice : null,
        ...(budgetUsd ? { budget_usd: budgetUsd } : {}),
        ...(Number.isFinite(parsedMax) ? { max_research_symbols: parsedMax } : {}),
        arms_enabled: [...(armsEnabled ?? new Set(ALL_ARMS))],
        ...(weeklyBudgetUsd.trim() !== "" ? { weekly_budget_usd: weeklyBudgetUsd.trim() } : {}),
        // Card mode sends none of the screen-only fields -- the request is identical to a build
        // without this control at all, per the contract's "byte-for-byte today's behaviour" note.
        ...(universeMode === "screen"
          ? {
              universe_mode: "screen" as const,
              // A named selector is the PRIMARY path server-side and candidate_pool/rank_key are
              // ignored there -- so the raw pair is omitted entirely rather than sent alongside it.
              ...(usingNamedSelector
                ? { selector_id: selectorChoice as string }
                : {
                    candidate_pool:
                      candidatePool ??
                      config.default_candidate_pool ??
                      effectiveCandidatePools[0] ??
                      "sector-etf",
                    rank_key:
                      rankKey ?? config.default_rank_key ?? effectiveRankKeys[0] ?? "mom12_1",
                  }),
              ...(Number.isFinite(parsedTopN) ? { screen_top_n: parsedTopN } : {}),
              ...(screenEntryRule.trim() !== "" ? { screen_entry_rule: screenEntryRule.trim() } : {}),
            }
          : {}),
      };
      const started = await workflowApi.startRun(body);
      setRun(started);
      setSelectedStageId(null);
    } catch (err) {
      setStartError(errorMessage(err, t("agentWorkflow.errors.startRun")));
    } finally {
      setStarting(false);
    }
  };

  const openRun = (runId: string) => {
    setRunError(null);
    workflowApi
      .getRun(runId)
      .then((res) => {
        setRun(res);
        setSelectedStageId(null);
      })
      .catch((err: unknown) => {
        setRunError(errorMessage(err, t("agentWorkflow.errors.getRun")));
      });
  };

  // --- universe filter, shared by the book / study / candidates panels ---------------------------
  // "card" (the default) omits `universe_source` from every request below, so the initial fetch is
  // byte-for-byte today's behaviour (every card book plus any screen books on disk, undifferentiated
  // except by the badge already on each row). "screen" filters all three panels, and the execute
  // button, to the screen-mode books only.
  const [universeFilter, setUniverseFilter] = useState<UniverseMode>("card");
  const universeParam = universeFilter === "screen" ? "screen" : undefined;

  // --- the paper book, one per arm --------------------------------------------------------------
  const [executing, setExecuting] = useState(false);
  const [executeMessage, setExecuteMessage] = useState<string | null>(null);
  const [executeError, setExecuteError] = useState<string | null>(null);

  // `lang` (not `t`) drives the re-fetch, matching the original `loadBooks` `useCallback`'s own
  // `[universeParam, t]` dependency array -- `t`'s own identity already changes with `lang`, and
  // `useFetch` reads `formatError` via a ref rather than as a dependency, so `lang` is named
  // directly here alongside the `universeParam` this fetch is actually keyed on.
  const booksResult = useFetch(
    (signal) => workflowApi.book(universeParam, signal).then((res) => res.books),
    [universeParam, lang],
    { formatError: (err) => errorMessage(err, t("agentWorkflow.errors.books")) },
  );
  const books = booksResult.data ?? [];
  const booksPhase = booksResult.phase;
  const booksMessage = booksResult.error;

  const handleExecute = async () => {
    setExecuting(true);
    setExecuteError(null);
    setExecuteMessage(null);
    try {
      const requestBody: ExecuteRequest = universeParam ? { universe_source: universeParam } : {};
      const result = await workflowApi.executeBook(requestBody);
      setExecuteMessage(
        t("agentWorkflow.book.executeResult", {
          filled: result.filled,
          rejected: result.rejected,
          stillPending: result.still_pending,
          asOf: result.as_of,
          storedOpen: result.price_source_mix.stored_open,
          liveQuote: result.price_source_mix.live_quote,
          universeLabel: universeSourceLabel(result.universe_source, t),
        }),
      );
      booksResult.reload();
    } catch (err) {
      setExecuteError(errorMessage(err, t("agentWorkflow.errors.execute")));
    } finally {
      setExecuting(false);
    }
  };

  // --- the effectiveness study --------------------------------------------------------------------
  const studyResult = useFetch<WorkflowStudy>(
    (signal) => workflowApi.study(universeParam, signal),
    [universeParam, lang],
    { formatError: (err) => errorMessage(err, t("agentWorkflow.errors.study")) },
  );
  const study = studyResult.data;
  const studyPhase = studyResult.phase;
  const studyMessage = studyResult.error;

  // --- candidate observations: why a candidate was skipped, and whether its gate verdicts came
  // from a fresh call or a cached one --------------------------------------------------------------
  const candidatesResult = useFetch<WorkflowCandidates>(
    (signal) =>
      // Always explicit here, unlike the book/study calls: an omitted `universe_source` on
      // `GET /candidates` is "no filter" (card AND screen rows mixed), not "card".
      workflowApi.candidates({ universeSource: universeFilter, limit: 100 }, signal),
    [universeFilter, lang],
    { formatError: (err) => errorMessage(err, t("agentWorkflow.errors.candidates")) },
  );
  const candidates = candidatesResult.data;
  const candidatesPhase = candidatesResult.phase;
  const candidatesMessage = candidatesResult.error;

  const agentUnavailable = config !== null && !config.agent_available;
  const selectedStage = run?.stages.find((s) => s.stage_id === selectedStageId) ?? null;

  return (
    <>
      <h1>{t("agentWorkflow.title")}</h1>
      <p className="subtitle">{t("agentWorkflow.subtitle")}</p>

      <section className="panel wf-explainer">
        <h2>{t("agentWorkflow.explainer.heading")}</h2>
        <InfoNote summary={t("agentWorkflow.explainer.summary")}>
          <ol>
            {EXPLAINER_STEP_KEYS.map((key) => (
              <li key={key}>{t(key)}</li>
            ))}
          </ol>
        </InfoNote>
      </section>

      <div className="view-tabs" role="tablist" aria-label={t("agentWorkflow.tabs.ariaLabel")}>
        <button
          type="button"
          role="tab"
          aria-selected={view === "run"}
          className={`timeframe-tab${view === "run" ? " active" : ""}`}
          onClick={() => setView("run")}
        >
          {t("agentWorkflow.tabs.run")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === "measure"}
          className={`timeframe-tab${view === "measure" ? " active" : ""}`}
          onClick={() => setView("measure")}
        >
          {t("agentWorkflow.tabs.measure")}
        </button>
      </div>

      {view === "run" && (
        <>
      {/* --- Run panel ------------------------------------------------------------------------- */}
      <PanelBoundary label={t("agentWorkflow.panel.runConfig")}>
        <section className="panel">
          <h2>{t("agentWorkflow.runConfig.heading")}</h2>
          {configPhase === "loading" && (
            <p className="muted">{t("agentWorkflow.runConfig.loading")}</p>
          )}
          {configPhase === "error" && <p className="callout callout-danger">{configMessage}</p>}
          {config && (
            <form className="wf-run-form" onSubmit={(e) => void handleSubmit(e)}>
              <label className="wf-field">
                <span>{t("agentWorkflow.runForm.strategyCard")}</span>
                <select
                  value={cardChoice ?? AUTO_CARD}
                  onChange={(e) => setCardChoice(e.target.value)}
                >
                  <option value={AUTO_CARD}>{t("agentWorkflow.runForm.autoSelect")}</option>
                  {config.cards.map((card) => (
                    <option value={card.agent_id} key={card.agent_id}>
                      {card.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="wf-field">
                <span>{t("common.budgetCapUsd")}</span>
                <input
                  type="text"
                  value={budgetUsd ?? config.default_budget_usd}
                  onChange={(e) => setBudgetUsd(e.target.value)}
                />
              </label>

              <label className="wf-field">
                <span>{t("agentWorkflow.runForm.maxResearchSymbols")}</span>
                <input
                  type="text"
                  inputMode="numeric"
                  value={maxResearchSymbols ?? String(config.default_max_research_symbols)}
                  onChange={(e) => setMaxResearchSymbols(e.target.value)}
                />
              </label>

              <label className="wf-field">
                <span>{t("agentWorkflow.runForm.universe")}</span>
                <select
                  value={universeMode}
                  onChange={(e) => setUniverseMode(e.target.value === "screen" ? "screen" : "card")}
                >
                  <option value="card">{t("agentWorkflow.runForm.universeCardOption")}</option>
                  <option value="screen">{t("agentWorkflow.runForm.universeScreenOption")}</option>
                </select>
              </label>

              <label className="wf-field">
                <span>{t("agentWorkflow.runForm.weeklyBudget")}</span>
                <input
                  type="text"
                  placeholder={t("agentWorkflow.runForm.weeklyBudgetPlaceholder")}
                  value={weeklyBudgetUsd}
                  onChange={(e) => setWeeklyBudgetUsd(e.target.value)}
                />
              </label>

              {universeMode === "screen" && (
                <div className="wf-universe-screen-fields">
                  <label className="wf-field">
                    <span>{t("agentWorkflow.runForm.selector")}</span>
                    <select
                      value={selectorChoice ?? RAW_SELECTOR}
                      onChange={(e) => setSelectorChoice(e.target.value)}
                    >
                      <option value={RAW_SELECTOR}>{t("agentWorkflow.runForm.rawSelectorOption")}</option>
                      {(config.selector_ids ?? []).map((id) => (
                        <option value={id} key={id}>
                          {id}
                        </option>
                      ))}
                    </select>
                  </label>

                  {/* candidate_pool/rank_key are ignored server-side once a named selector is chosen
                      -- hidden rather than shown-but-inert, so the form never implies they still do
                      something. */}
                  {(selectorChoice ?? RAW_SELECTOR) === RAW_SELECTOR && (
                    <>
                      <label className="wf-field">
                        <span>{t("agentWorkflow.runForm.candidatePool")}</span>
                        <select
                          value={
                            candidatePool ??
                            config.default_candidate_pool ??
                            (config.candidate_pools?.[0] ?? CANDIDATE_POOLS[0])
                          }
                          onChange={(e) => setCandidatePool(e.target.value)}
                        >
                          {(config.candidate_pools && config.candidate_pools.length > 0
                            ? config.candidate_pools
                            : CANDIDATE_POOLS
                          ).map((pool) => (
                            <option value={pool} key={pool}>
                              {pool}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="wf-field">
                        <span>{t("agentWorkflow.runForm.rankKey")}</span>
                        <select
                          value={
                            rankKey ?? config.default_rank_key ?? (config.rank_keys?.[0] ?? RANK_KEYS[0])
                          }
                          onChange={(e) => setRankKey(e.target.value)}
                        >
                          {(config.rank_keys && config.rank_keys.length > 0
                            ? config.rank_keys
                            : RANK_KEYS
                          ).map((key) => (
                            <option value={key} key={key}>
                              {key}
                            </option>
                          ))}
                        </select>
                      </label>
                    </>
                  )}

                  <label className="wf-field">
                    <span>{t("agentWorkflow.runForm.screenTopN")}</span>
                    <input
                      type="text"
                      inputMode="numeric"
                      placeholder={
                        config.default_screen_top_n !== undefined
                          ? String(config.default_screen_top_n)
                          : t("agentWorkflow.runForm.screenTopNPlaceholderDefault")
                      }
                      value={screenTopN}
                      onChange={(e) => setScreenTopN(e.target.value)}
                    />
                  </label>

                  <label className="wf-field">
                    <span>{t("agentWorkflow.runForm.screenEntryRule")}</span>
                    <input
                      type="text"
                      placeholder={t("agentWorkflow.runForm.screenEntryRulePlaceholder")}
                      value={screenEntryRule}
                      onChange={(e) => setScreenEntryRule(e.target.value)}
                    />
                  </label>
                </div>
              )}

              <div>
                <h3>{t("agentWorkflow.runForm.armsEnabled")}</h3>
                <div className="wf-arm-grid">
                  {config.arms.map((arm) => (
                    <label className="wf-arm-option" key={arm.key}>
                      <input
                        type="checkbox"
                        checked={(armsEnabled ?? new Set(ALL_ARMS)).has(arm.key)}
                        onChange={() => toggleArm(arm.key)}
                      />
                      <span>
                        {arm.label}
                        <span className="wf-arm-blurb">{arm.blurb}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              {agentUnavailable && (
                <p className="callout callout-warn wf-agent-unavailable">
                  {t("agentWorkflow.runForm.agentUnavailable", { reason: config.agent_reason })}
                </p>
              )}
              {startError && <p className="callout callout-danger">{startError}</p>}

              <button
                type="submit"
                className="comp-run-cta"
                disabled={starting || agentUnavailable}
              >
                {starting ? t("agentWorkflow.runForm.starting") : t("agentWorkflow.runForm.startRun")}
              </button>
            </form>
          )}
        </section>
      </PanelBoundary>

      {run && (
        <PanelBoundary label={t("agentWorkflow.panel.runProgress")}>
          <section className="panel">
            <h2>{t("agentWorkflow.run.heading")}</h2>
            <p className="muted">
              {t("agentWorkflow.run.stateCostLine", {
                state: run.state,
                spent: formatMoney(run.budget.spent_usd),
                cap: formatMoney(run.budget.cap_usd),
                calls: run.budget.calls,
              })}
            </p>
            {runError && <p className="callout callout-danger">{runError}</p>}
            {run.error && <p className="callout callout-danger">{run.error}</p>}

            <div className="wf-dag">
              {groupByLayer(run.stages).map(([layer, stages]) => (
                <div className="wf-dag-layer" key={layer}>
                  <div className="wf-dag-layer-label">
                    {t("agentWorkflow.run.layerLabel", { layer })}
                  </div>
                  <div className="wf-dag-layer-stages">
                    {stages.map((stage) => (
                      <button
                        type="button"
                        key={stage.stage_id}
                        data-state={stage.state}
                        className={`wf-stage wf-stage-${stage.state}${
                          stage.stage_id === selectedStageId ? " selected" : ""
                        }`}
                        onClick={() => setSelectedStageId(stage.stage_id)}
                      >
                        <span className="wf-stage-seat">{stage.seat || stage.role}</span>
                        <span className="wf-stage-label">{stage.label}</span>
                        <StatusPill tone={stageTone(stage.state)} label={stageStateLabel(stage.state, t)} />
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {selectedStage && (
              <div className="panel wf-stage-detail">
                <h3>{selectedStage.label}</h3>
                <p className="muted">
                  {t("agentWorkflow.run.stageDetailLine", {
                    seat: selectedStage.seat || "—",
                    state: stageStateLabel(selectedStage.state, t),
                    cost: formatMoney(selectedStage.cost_usd),
                  })}
                </p>
                {selectedStage.error && (
                  <p className="callout callout-danger">{selectedStage.error}</p>
                )}
                {selectedStage.grounding?.degraded && (
                  <div className="callout callout-warn wf-grounding-issues">
                    {/* "Degraded" is a three-way distinction this page makes and never explains on
                        screen: it ran and produced output that failed a grounding check -- not
                        blocked, not failed. The stage pills carry the same word; this callout is
                        the first place it appears with a reason attached. */}
                    <strong>
                      <Term k="degraded">{t("agentWorkflow.run.groundingDegraded")}</Term>
                    </strong>
                    <ul>
                      {selectedStage.grounding.issues.map((issue, i) => (
                        <li key={`${issue.kind}-${i}`}>
                          {issue.kind}: {issue.detail}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {selectedStage.output_md && (
                  <p className="muted wf-source-badge">
                    <span title={t("common.sourceEnglishTitle")}>{t("common.sourceEnglish")}</span>
                  </p>
                )}
                <ScrollRegion size="md" label={t("agentWorkflow.run.heading")}>
                  <pre className="wf-output-md">
                    {selectedStage.output_md || t("agentWorkflow.run.noOutputYet")}
                  </pre>
                </ScrollRegion>
              </div>
            )}

            {run.final_md && (
              <div className="panel wf-final-report">
                <h3>{t("agentWorkflow.run.entryPlan")}</h3>
                <p className="muted wf-source-badge">
                  <span title={t("common.sourceEnglishTitle")}>{t("common.sourceEnglish")}</span>
                </p>
                <ScrollRegion size="md" label={t("agentWorkflow.run.entryPlan")}>
                  <pre className="wf-output-md">{run.final_md}</pre>
                </ScrollRegion>
              </div>
            )}
          </section>
        </PanelBoundary>
      )}

      <PanelBoundary label={t("common.recentRuns")}>
        <section className="panel">
          <h2>{t("common.recentRuns")}</h2>
          {recentRunsPhase === "loading" && (
            <p className="muted">{t("agentWorkflow.recentRuns.loading")}</p>
          )}
          {recentRunsPhase === "error" && (
            <p className="callout callout-danger">{recentRunsMessage}</p>
          )}
          {recentRunsPhase === "loaded" && recentRuns.length === 0 && (
            <p className="muted">{t("agentWorkflow.recentRuns.empty")}</p>
          )}
          {recentRunsPhase === "loaded" && recentRuns.length > 0 && (
            <ScrollRegion size="md" label={t("common.recentRuns")}>
              <ul className="wf-recent-runs">
                {recentRuns.map((summary) => (
                  <li key={summary.run_id}>
                    <button type="button" onClick={() => openRun(summary.run_id)}>
                      <span>{summary.label}</span>
                      <span className="muted">{summary.state}</span>
                      <span className="muted">
                        {t("agentWorkflow.recentRuns.stagesLine", {
                          done: summary.stages_done,
                          total: summary.stages_total,
                        })}
                      </span>
                      <span className="muted">{formatMoney(summary.cost_usd)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </ScrollRegion>
          )}
        </section>
      </PanelBoundary>
        </>
      )}

      {view === "measure" && (
        <>
      {/* --- Book panel ------------------------------------------------------------------------ */}
      <PanelBoundary label={t("agentWorkflow.panel.paperBook")}>
        <section className="panel">
          <h2>{t("agentWorkflow.book.heading")}</h2>
          <div
            className="wf-universe-toggle"
            role="group"
            aria-label={t("agentWorkflow.book.universeFilterAriaLabel")}
          >
            <button
              type="button"
              aria-pressed={universeFilter === "card"}
              className={universeFilter === "card" ? "active" : ""}
              onClick={() => setUniverseFilter("card")}
            >
              {t("agentWorkflow.universe.card")}
            </button>
            <button
              type="button"
              aria-pressed={universeFilter === "screen"}
              className={universeFilter === "screen" ? "active" : ""}
              onClick={() => setUniverseFilter("screen")}
            >
              {t("agentWorkflow.universe.screened")}
            </button>
          </div>
          <p className="muted">{t("agentWorkflow.book.filterNote")}</p>
          <div className="wf-book-toolbar">
            <button type="button" onClick={() => void handleExecute()} disabled={executing}>
              {executing ? t("agentWorkflow.book.executing") : t("agentWorkflow.book.executeButton")}
            </button>
          </div>
          {executeError && <p className="callout callout-danger">{executeError}</p>}
          {executeMessage && <p className="callout callout-warn">{executeMessage}</p>}

          {booksPhase === "loading" && <p className="muted">{t("agentWorkflow.book.loading")}</p>}
          {booksPhase === "error" && <p className="callout callout-danger">{booksMessage}</p>}
          {booksPhase === "loaded" && books.length === 0 && (
            <p className="muted">{t("agentWorkflow.book.empty")}</p>
          )}

          {booksPhase === "loaded" && books.length > 0 && (
            <div className="wf-book-grid">
              {books.map((book) => (
                <div className="wf-book-card" key={`${book.arm}-${book.universe_source ?? "card"}`}>
                  <h3>
                    {book.arm}
                    <span className="wf-universe-badge" data-universe={book.universe_source ?? "card"}>
                      {universeSourceLabel(book.universe_source, t)}
                    </span>
                  </h3>
                  <p className="muted">
                    {book.as_of
                      ? t("agentWorkflow.book.cardAdoptedLineWithAsOf", {
                          cardId: book.current_card_id,
                          date: book.card_adopted_date,
                          asOf: book.as_of,
                        })
                      : t("agentWorkflow.book.cardAdoptedLine", {
                          cardId: book.current_card_id,
                          date: book.card_adopted_date,
                        })}
                  </p>
                  <p>
                    {t("agentWorkflow.book.cashEquityLine", {
                      cash: formatMoney(book.cash),
                      equity: book.equity !== null ? formatMoney(book.equity) : "—",
                      startingCash: formatMoney(book.starting_cash),
                    })}
                  </p>

                  <h4>{t("agentWorkflow.book.positionsHeading")}</h4>
                  {book.positions.length === 0 ? (
                    <p className="muted">{t("agentWorkflow.book.noPositions")}</p>
                  ) : (
                    <ScrollRegion size="md" label={t("agentWorkflow.book.positionsHeading")}>
                      <table className="wf-table">
                        <thead>
                          <tr>
                            <th>{t("common.symbol")}</th>
                            <th>{t("agentWorkflow.table.qty")}</th>
                            <th>{t("agentWorkflow.table.avgCost")}</th>
                            <th>{t("agentWorkflow.table.marketValue")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {book.positions.map((position) => (
                            <tr key={position.symbol}>
                              <td>{position.symbol}</td>
                              <td>{position.qty}</td>
                              {/* Tolerant of a missing/null value on either money field: a server row
                                  that omits one must render "—", never take the page down (see
                                  `universeSourceLabel`'s note on server-supplied data). */}
                              <td>{position.avg_cost != null ? formatMoney(position.avg_cost) : "—"}</td>
                              <td>
                                {position.market_value != null
                                  ? formatMoney(position.market_value)
                                  : "—"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </ScrollRegion>
                  )}

                  <h4>{t("agentWorkflow.book.ordersHeading")}</h4>
                  {book.orders.length === 0 ? (
                    <p className="muted">{t("agentWorkflow.book.noOrders")}</p>
                  ) : (
                    <ScrollRegion size="md" label={t("agentWorkflow.book.ordersHeading")}>
                      <table className="wf-table">
                        <thead>
                          <tr>
                            <th>{t("common.symbol")}</th>
                            <th>{t("agentWorkflow.table.notional")}</th>
                            <th>{t("common.status")}</th>
                            <th>{t("agentWorkflow.table.fillPrice")}</th>
                            <th>{t("common.source")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {book.orders.map((order) => (
                            <tr key={order.order_id} data-status={order.status}>
                              <td>{order.symbol}</td>
                              <td>{formatMoney(order.notional)}</td>
                              <td>{order.status}</td>
                              <td>{order.fill ? formatMoney(order.fill.price) : "—"}</td>
                              <td>{order.fill ? order.fill.price_source : "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </ScrollRegion>
                  )}

                  {book.tax && (
                    <div className="wf-tax-summary">
                      <h4>{t("agentWorkflow.book.taxHeading")}</h4>
                      <p>
                        {t("agentWorkflow.book.taxLine", {
                          shortTerm: formatMoney(book.tax.short_term_gain),
                          longTerm: formatMoney(book.tax.long_term_gain),
                          net: formatMoney(book.tax.net_realized_gain),
                        })}
                      </p>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </PanelBoundary>

      {/* --- Study panel ----------------------------------------------------------------------- */}
      <PanelBoundary label={t("agentWorkflow.panel.study")}>
        <section className="panel">
          <h2>{t("agentWorkflow.study.heading")}</h2>
          {studyPhase === "loading" && <p className="muted">{t("agentWorkflow.study.loading")}</p>}
          {studyPhase === "error" && <p className="callout callout-danger">{studyMessage}</p>}

          {studyPhase === "loaded" && study && (
            <>
              <p className="callout callout-warn wf-study-note">
                {study.note}{" "}
                <span className="wf-source-badge" title={t("common.sourceEnglishTitle")}>
                  {t("common.sourceEnglish")}
                </span>
              </p>
              <p className="muted">
                {study.window
                  ? t("agentWorkflow.study.benchmarkLineWithWindow", {
                      benchmark: study.benchmark,
                      benchmarkReturn: study.benchmark_return,
                      start: study.window.start,
                      end: study.window.end,
                    })
                  : t("agentWorkflow.study.benchmarkLine", {
                      benchmark: study.benchmark,
                      benchmarkReturn: study.benchmark_return,
                    })}
              </p>

              {study.arms.length === 0 ? (
                <p className="muted">{t("agentWorkflow.study.noArmMetrics")}</p>
              ) : (
                <ScrollRegion size="md" label={t("agentWorkflow.study.heading")}>
                  <table className="wf-table">
                    <thead>
                      <tr>
                        <th>{t("agentWorkflow.table.arm")}</th>
                        <th>{t("agentWorkflow.table.universe")}</th>
                        <th>{t("agentWorkflow.table.totalReturn")}</th>
                        {/* First use on this page of the two columns a reader is most likely to
                            read as something else: a drawdown that is not "the worst it got", and
                            an exposure that is a fraction of bars, not of capital. */}
                        <th>
                          <Term k="drawdown">{t("agentWorkflow.table.maxDrawdown")}</Term>
                        </th>
                        <th>{t("agentWorkflow.table.realizedVol")}</th>
                        <th>
                          <Term k="exposure">{t("agentWorkflow.table.exposure")}</Term>
                        </th>
                        <th>{t("agentWorkflow.table.adjustedExcess")}</th>
                        <th>{t("agentWorkflow.table.trades")}</th>
                        <th>{t("agentWorkflow.table.liveFillFraction")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {study.arms.map((metrics) => (
                        <tr key={`${metrics.arm}-${metrics.universe_source ?? "card"}`}>
                          <td>{metrics.arm}</td>
                          <td>
                            <span
                              className="wf-universe-badge"
                              data-universe={metrics.universe_source ?? "card"}
                            >
                              {universeSourceLabel(metrics.universe_source, t)}
                            </span>
                          </td>
                          {/* Fractions of one on the wire (see `ArmMetrics`); shown as percent. */}
                          <td>{formatPctFraction(metrics.total_return)}</td>
                          <td>{formatPctFraction(metrics.max_drawdown)}</td>
                          <td>{formatPctFraction(metrics.realized_vol)}</td>
                          <td>{formatPctFraction(metrics.exposure)}</td>
                          <td>{formatPctFraction(metrics.adjusted_excess)}</td>
                          <td>{metrics.trades}</td>
                          <td>{formatPctFraction(metrics.live_fill_fraction)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </ScrollRegion>
              )}

              <h3>{t("agentWorkflow.study.pairedHeading")}</h3>
              {/* A p-value with no power line invites the reader to take "not significant" as
                  "no effect". At this study's own n the test cannot see anything smaller than the
                  pre-registered minimum detectable effect, so that number renders next to the
                  heading rather than living only in a report nobody on this page will open. */}
              <InfoNote
                data-testid="wf-study-power"
                summary={(() => {
                  const n = gatedCandidateN(study);
                  return n === null
                    ? t("agentWorkflow.study.powerNoN", { mde: PRE_REGISTERED_MDE_PP })
                    : t("agentWorkflow.study.power", { n, mde: PRE_REGISTERED_MDE_PP });
                })()}
              >
                {t("agentWorkflow.study.power.more", { mde: PRE_REGISTERED_MDE_PP })}
              </InfoNote>
              {study.paired.length === 0 ? (
                <p className="muted">{t("agentWorkflow.study.noPaired")}</p>
              ) : (
                <ScrollRegion size="md" label={t("agentWorkflow.study.pairedHeading")}>
                  <table className="wf-table">
                    <thead>
                      <tr>
                        <th>{t("agentWorkflow.table.arm")}</th>
                        <th>{t("agentWorkflow.table.universe")}</th>
                        <th>{t("agentWorkflow.table.meanDailyDiff")}</th>
                        <th>
                          <Term k="pValue">{t("agentWorkflow.table.bootstrapP")}</Term>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {study.paired.map((row) => (
                        <tr key={`${row.arm}-${row.universe_source ?? "card"}`}>
                          <td>{row.arm}</td>
                          <td>
                            <span className="wf-universe-badge" data-universe={row.universe_source ?? "card"}>
                              {universeSourceLabel(row.universe_source, t)}
                            </span>
                          </td>
                          <td>{formatPctFraction(row.mean_daily_diff)}</td>
                          <td>{row.bootstrap_p}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </ScrollRegion>
              )}

              <p className="muted">
                <Trans
                  k="agentWorkflow.study.vibeVerdictCompliance"
                  values={{
                    value: (
                      <span>
                        {study.vibe_verdict_compliance !== null ? study.vibe_verdict_compliance : "—"}
                      </span>
                    ),
                  }}
                />
              </p>

              {study.discrimination && study.discrimination.length > 0 && (
                <>
                  <h3>{t("agentWorkflow.study.discriminationHeading")}</h3>
                  {study.discrimination.every((row) => row.passed_n === 0) && (
                    <p className="callout callout-warn">{t("agentWorkflow.study.notMeasurable")}</p>
                  )}
                  <ScrollRegion size="md" label={t("agentWorkflow.study.discriminationHeading")}>
                    <table className="wf-table">
                      <thead>
                        <tr>
                          <th>{t("agentWorkflow.table.gate")}</th>
                          <th>{t("agentWorkflow.table.passedN")}</th>
                          <th>{t("agentWorkflow.table.refusedN")}</th>
                          <th>{t("agentWorkflow.table.passedHitRate")}</th>
                          <th>{t("agentWorkflow.table.refusedHitRate")}</th>
                          <th>{t("agentWorkflow.table.meanDiff")}</th>
                          {/* Two one-letter column heads. `p` and `q` are the whole content of
                              these cells and neither is spelled out anywhere on the page -- the
                              definition is the only thing standing between the heading and a
                              guess. */}
                          <th>
                            <Term k="pValue">{t("agentWorkflow.table.pValue")}</Term>
                          </th>
                          <th>
                            <Term k="qValue">{t("agentWorkflow.table.qValue")}</Term>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {study.discrimination.map((row: GateDiscrimination, i) => (
                          <tr key={`${row.gate}-${i}`}>
                            <td>{row.gate}</td>
                            <td>{row.passed_n}</td>
                            <td>{row.refused_n}</td>
                            {/* Hit rates and mean_diff are fractions of one on the wire. */}
                            <td>{formatPctFraction(row.passed_hit_rate ?? null)}</td>
                            <td>{formatPctFraction(row.refused_hit_rate ?? null)}</td>
                            <td>{formatPctFraction(row.mean_diff ?? null)}</td>
                            <td>{row.p_value ?? "—"}</td>
                            <td>{row.q_value ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </ScrollRegion>
                </>
              )}
            </>
          )}
        </section>
      </PanelBoundary>

      {/* --- Candidates panel -------------------------------------------------------------------
          Why a candidate was skipped (`skip_reason`) and whether its gate verdicts came from a
          fresh child-agent call or a cached one (`verdict_source`) -- driven by the same universe
          toggle as the Book/Study panels above. */}
      <PanelBoundary label={t("agentWorkflow.panel.candidates")}>
        <section className="panel">
          <h2>{t("agentWorkflow.candidates.heading")}</h2>
          {candidatesPhase === "loading" && (
            <p className="muted">{t("agentWorkflow.candidates.loading")}</p>
          )}
          {candidatesPhase === "error" && (
            <p className="callout callout-danger">{candidatesMessage}</p>
          )}

          {candidatesPhase === "loaded" && candidates && (
            <>
              {candidates.observations.length === 0 ? (
                <p className="muted">{t("agentWorkflow.candidates.empty")}</p>
              ) : (
                <>
                  <p className="muted">
                    {t("agentWorkflow.candidates.summaryLine", {
                      total: candidates.total,
                      avoidedCost: formatMoney(candidates.avoided_cost_usd),
                      skipReasons:
                        Object.keys(candidates.skip_reasons).length === 0
                          ? t("agentWorkflow.candidates.noneWord")
                          : Object.entries(candidates.skip_reasons)
                              .map(([reason, count]) => `${reason} (${count})`)
                              .join(", "),
                      fresh: candidates.verdict_sources.fresh,
                      cached: candidates.verdict_sources.cached,
                      mixed: candidates.verdict_sources.mixed,
                    })}
                  </p>

                  <ScrollRegion size="sm" label={t("agentWorkflow.candidates.heading")}>
                    <table className="wf-table">
                      <thead>
                        <tr>
                          <th>{t("common.date")}</th>
                          <th>{t("common.symbol")}</th>
                          <th>{t("agentWorkflow.table.card")}</th>
                          <th>
                            <Term k="regime">{t("agentWorkflow.table.regime")}</Term>
                          </th>
                          <th>{t("agentWorkflow.table.rank")}</th>
                          <th>{t("agentWorkflow.table.gatesColumn")}</th>
                          <th>{t("agentWorkflow.table.skipReason")}</th>
                          <th>{t("agentWorkflow.table.state")}</th>
                          <th>{t("agentWorkflow.table.forwardReturn")}</th>
                          <th>{t("agentWorkflow.table.alpha")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {candidates.observations.map((obs: CandidateObservation) => (
                          <tr key={obs.obs_id} data-state={obs.state}>
                            <td>{obs.decision_date}</td>
                            <td>{obs.symbol}</td>
                            <td>{obs.agent_card_id}</td>
                            <td>{obs.regime}</td>
                            <td>{obs.entry_rank}</td>
                            <td>
                              {obs.gates.length === 0 ? (
                                "—"
                              ) : (
                                <ul className="wf-gate-rulings">
                                  {obs.gates.map((gate: GateDecision) => (
                                    <li
                                      key={gate.gate}
                                      className={`wf-gate-ruling ${gate.passed ? "wf-gate-pass" : "wf-gate-fail"}`}
                                      data-verdict-source={gate.verdict_source}
                                      title={gate.detail}
                                    >
                                      {gate.gate}: {gate.passed ? "✓" : "✗"}
                                      {gate.verdict_source !== "fresh"
                                        ? ` (${gate.verdict_source})`
                                        : ""}
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </td>
                            <td title={obs.skip_detail || undefined}>{obs.skip_reason ?? "—"}</td>
                            <td>{obs.state}</td>
                            <td>{formatPctFraction(obs.forward_return_pct)}</td>
                            <td>{formatPctFraction(obs.alpha_return_pct)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </ScrollRegion>
                </>
              )}
            </>
          )}
        </section>
      </PanelBoundary>
        </>
      )}
    </>
  );
}
