/**
 * Vibe Trading: preset desks of role agents, run as a DAG over real market data.
 *
 * **Top -- a static explainer, rendered from `EXPLAINER_STEPS` below, never fetched.** It exists so a
 * reader opens this page understanding the model before touching the run form: a preset desk is a
 * committee of role agents defined as data; its tasks form a dependency graph; everything in one
 * layer runs in parallel; a downstream agent sees only its upstream's short summary, never the full
 * text; real market data is pre-fetched and injected into every prompt as ground truth *before* any
 * agent runs; and a task whose upstream failed is marked `blocked`, deliberately, rather than quietly
 * completing on nothing.
 *
 * **Below -- the working surface**, in the order the owner's brief lays out:
 *  1. a preset picker (`vibeDeskApi.presets()`), which loads `preset(name)` on selection for the
 *     committee/task/variable detail the run form needs;
 *  2. a run form -- the preset's own declared `variables`, symbol/question (sent whichever a reader
 *     fills in -- see `StartSwarmRequest`'s own docstring in `api/vibedesk.ts` on why this page cannot
 *     know in advance which of the two a given preset actually reads), and a budget cap;
 *  3. a DAG progress board, stages grouped by `layer` so dependencies read top-to-bottom;
 *  4. the selected stage's own report (`output_md`), with `GroundingVerdict` issues surfaced when
 *     `grounding.degraded`;
 *  5. the run's final report (`final_md`) and its cost (`budget`);
 *  6. recent runs (`listRuns()`).
 *
 * **`degraded`/`blocked`/`failed` are three different claims and get three different treatments**
 * (`.vibe-stage-degraded`/`.vibe-stage-blocked`/`.vibe-stage-failed` in `VibeTrading.css`): `degraded`
 * ran and produced output that failed a grounding check; `blocked` never ran at all, because
 * something upstream failed and letting a dependent proceed on missing input would be worse than
 * marking it stopped; `failed` ran and errored. Collapsing any two of these into one visual state
 * would misreport what actually happened in the run.
 *
 * **`GET /config`** serves only the worker-model catalogue (the default model plus the models a run
 * may pick from) -- the same catalogue `GET /api/tradingagents/config` exposes, so the two desks'
 * pickers cannot drift apart (`app.vibedesk.service.build_config` reuses
 * `app.tradingagents.service.AVAILABLE_MODELS` verbatim). Whether the agent layer can run at all is a
 * separate question, still answered by `GET /api/agents/health` (`vibeDeskApi.agentHealth()`) -- see
 * that function's own docstring in `api/vibedesk.ts`.
 *
 * **Polling**: `GET /runs/{run_id}` every 2000ms while `state` is `"queued"` or `"running"` --
 * `isRunActive` from `api/vibedesk.ts`. No SSE, matching `Competition.tsx`'s job-poll and loop-poll
 * effects, which this page's own polling effect mirrors line for line.
 *
 * **No markdown renderer in this codebase's dependencies** (`frontend/package.json` carries none) --
 * `output_md`/`final_md` render inside `<pre className="vibe-output-md">` with `white-space: pre-wrap`
 * rather than pulling in a new dependency for this one page.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { formatMoney } from "@/api/tax";
import {
  isRunActive,
  vibeDeskApi,
  type AgentHealth,
  type DeskRun,
  type DeskRunSummary,
  type PresetDetail,
  type RunState,
  type StageRecord,
  type StageState,
  type StartSwarmRequest,
  type VibeConfig,
} from "@/api/vibedesk";
import InfoNote from "@/components/InfoNote";
import PanelBoundary from "@/components/PanelBoundary";
import { ScrollRegion } from "@/components/ScrollPanel";
import StatusPill, { type PillTone } from "@/components/StatusPill";
import { formatFetchError as errorMessage, useFetch } from "@/hooks/useFetch";
import { useT, type I18n, type MessageKey } from "@/i18n";

import "./VibeTrading.css";

/** Matches `Competition.tsx`'s own job/loop poll interval -- not tied to anything server-side. */
const POLL_INTERVAL_MS = 2000;

/** Sentinel `<option>` value: not a model id, it toggles the free-text version field. */
const CUSTOM_MODEL_CHOICE = "__custom__";

/**
 * The page's static explainer, in the order a reader needs it: what a preset *is*, how its tasks are
 * scheduled, what a downstream agent actually sees, where the ground-truth data comes from, and why a
 * blocked stage is not a bug. Rendered as an ordered list from this constant -- never fetched, per the
 * owner's brief.
 */
const EXPLAINER_STEPS: readonly MessageKey[] = [
  "agentDesk.vibe.explainer.step1",
  "agentDesk.vibe.explainer.step2",
  "agentDesk.vibe.explainer.step3",
  "agentDesk.vibe.explainer.step4",
  "agentDesk.vibe.explainer.step5",
];


/** `pending`/`running`/`succeeded`/`failed` reuse `common.status.*` -- identical text to what those
 * keys already carry. `degraded`/`blocked`/`skipped` get their own `agentDesk.vibe.*` entries
 * because `common.status` does not define them. */
function stageStateLabel(t: I18n["t"], state: StageState): string {
  switch (state) {
    case "pending":
      return t("status.pending");
    case "running":
      return t("status.running");
    case "succeeded":
      return t("status.succeeded");
    case "degraded":
      return t("agentDesk.vibe.stageState.degraded");
    case "failed":
      return t("status.failed");
    case "blocked":
      return t("agentDesk.vibe.stageState.blocked");
    case "skipped":
      return t("agentDesk.vibe.stageState.skipped");
    default: {
      const _exhaustive: never = state;
      void _exhaustive;
      return String(state);
    }
  }
}

/** Tone mapping for a `StageState`, per docs/COPY-STYLE.md: pending -> neutral, running -> info,
 * succeeded -> ok, degraded -> warn, failed -> bad, blocked -> special, skipped -> neutral. */
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

/** Tone mapping for the raw `RunState` wire value (the recent-runs list's own state chip), per
 * docs/COPY-STYLE.md: queued -> neutral, running -> info, succeeded -> ok, failed -> bad,
 * cancelled -> neutral. */
function runTone(state: RunState): PillTone {
  switch (state) {
    case "queued":
      return "neutral";
    case "running":
      return "info";
    case "succeeded":
      return "ok";
    case "failed":
      return "bad";
    case "cancelled":
      return "neutral";
    default: {
      const _exhaustive: never = state;
      void _exhaustive;
      return "neutral";
    }
  }
}

/** A day. `DeskRunSummary` (see `@/api/vibedesk`) carries no separate "last updated" timestamp,
 *  so `created_at` is what a still-`running` row is timed against. */
const STALE_RUNNING_MS = 24 * 60 * 60 * 1000;

/**
 * Client-derived display state for one recent-run row (UX-15) -- mirrors `TradingAgents.tsx`'s
 * own `runDisplayState`. The server's raw `state` is never reinterpreted for anything but this
 * one case: a row still reporting `"running"` a day or more after it started is almost certainly
 * stuck, not actually in progress, so it displays as `agentDesk.status.stale` instead. When the
 * raw wire value is no longer the visible label, it is folded into `detail` instead, which
 * `StatusPill` renders as a native `title` (plus `aria-description`).
 *
 * Exactly one pill is ever shown per row: `degraded` folds into this same pill's `detail` text
 * rather than a second pill.
 *
 * `r.state` is a plain string off the wire (`RunState`) -- deliberately never switched over with
 * a throwing exhaustiveness check here; `runTone` above already covers every known value and
 * falls back to `"neutral"` for anything it does not recognise.
 */
function runDisplayState(
  t: I18n["t"],
  r: DeskRunSummary,
): { label: string; tone: PillTone; detail: string | undefined } {
  const isStale = r.state === "running" && Date.now() - Date.parse(r.created_at) > STALE_RUNNING_MS;
  const detailParts: string[] = [];
  if (isStale) detailParts.push(r.state);
  if (r.degraded) detailParts.push(t("agentDesk.vibe.recentRuns.degradedBadge"));
  return {
    label: isStale ? t("agentDesk.status.stale") : r.state,
    tone: isStale ? "neutral" : runTone(r.state),
    detail: detailParts.length > 0 ? detailParts.join(" · ") : undefined,
  };
}

/** Groups a run's stages by `layer`, ascending, so the DAG board reads top-to-bottom in dependency
 *  order -- a layer never depends on a later one. */
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

/** Reads the symbol a run was started for out of its own echoed-back `config` -- `DeskRun.config` is
 * an untyped `Record<string, unknown>` shared with Trading Agents, and a Vibe run may be
 * question-based with no symbol at all (see `agentDesk.vibe.runConfig.question`), so this is read
 * defensively rather than assumed. Used to gate the Final Report's "open the research report" link. */
function vibeRunSymbol(run: DeskRun | null): string | undefined {
  const raw = run?.config?.["symbol"];
  return typeof raw === "string" && raw.trim() ? raw.trim() : undefined;
}

export interface VibeTradingProps {
  /**
   * True when this page is mounted as a TAB BODY (e.g. `ResearchDesk.tsx`) rather than as its own
   * route. Only one thing changes: the page heading drops from `<h1>` to `<h2>`, so a host page
   * that already renders the document's own `<h1>` does not end up with two top-level headings in
   * a screen reader's heading list (A11Y-02). Optional and defaulted, so `/vibe-trading` and every
   * existing test keep the `<h1>` they had. Mirrors `TradingAgents.tsx`'s own `embedded` prop.
   *
   * NOTE (handoff): `ResearchDesk.tsx` does not pass this prop yet -- it is outside this change's
   * scope fence. Passing `embedded` from there closes the same two-`<h1>` gap this prop fixes here.
   */
  embedded?: boolean | undefined;
}

export default function VibeTrading({ embedded = false }: VibeTradingProps = {}) {
  const { t, lang } = useT();

  // --- presets -------------------------------------------------------------------------------------
  const [selectedPresetName, setSelectedPresetName] = useState<string | null>(null);

  // `lang` (not `t`) drives the re-fetch, matching the original effect's `[t]` dependency array --
  // `t`'s own identity already changes with `lang`, and `useFetch` reads `formatError` via a ref
  // rather than as a dependency, so `lang` is named directly to reproduce "toggling the language
  // re-fetches this list".
  const presetsResult = useFetch(
    () => vibeDeskApi.presets().then((res) => res.presets),
    [lang],
    { formatError: (err) => errorMessage(err, t("agentDesk.vibe.error.presetsLoad")) },
  );
  const presets = presetsResult.data ?? [];
  const presetsPhase = presetsResult.phase;
  const presetsMessage = presetsResult.error;

  useEffect(() => {
    if (presetsResult.data) {
      setSelectedPresetName((prev) => prev ?? presetsResult.data![0]?.name ?? null);
    }
  }, [presetsResult.data]);

  // --- preset detail (agents, tasks, variables) -----------------------------------------------------
  const [variablesInput, setVariablesInput] = useState<Record<string, string>>({});

  const presetDetailResult = useFetch<PresetDetail>(
    () => vibeDeskApi.preset(selectedPresetName as string),
    [selectedPresetName, lang],
    {
      skip: !selectedPresetName,
      formatError: (err) => errorMessage(err, t("agentDesk.vibe.error.presetLoad")),
    },
  );
  // The original effect nulled its own `presetDetail` state the instant a new preset was picked,
  // before the request even went out -- this page's render below checks `presetDetail &&` directly,
  // not gated on `phase === "loaded"`, so a stale detail object must not survive into the next
  // preset's "loading"/"error" phase the way `useFetch` otherwise leaves `data` alone across a
  // re-fetch (see that hook's own docstring on why it never clears `data` by default).
  const presetDetailPhase = presetDetailResult.phase;
  const presetDetail = presetDetailPhase === "loaded" ? presetDetailResult.data : null;
  const presetDetailMessage = presetDetailResult.error;

  useEffect(() => {
    if (!presetDetail) return;
    const defaults: Record<string, string> = {};
    for (const variable of presetDetail.variables) defaults[variable.name] = variable.default;
    setVariablesInput(defaults);
  }, [presetDetail]);

  // --- agent availability ----------------------------------------------------------------------------
  const [agentHealth, setAgentHealth] = useState<AgentHealth | null>(null);

  useEffect(() => {
    let cancelled = false;
    vibeDeskApi
      .agentHealth()
      .then((res) => {
        if (cancelled) return;
        setAgentHealth(res);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // A network failure checking health is itself a reason Start should stay disabled -- fold it
        // into the same shape rather than leaving `agentHealth` null forever (null reads as "still
        // checking", not "checked and it's fine").
        setAgentHealth({
          available: false,
          credential_source: "none",
          reason: errorMessage(err, t("agentDesk.vibe.error.agentAvailability")),
          model: "",
          sdk_installed: false,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  // --- recent runs -------------------------------------------------------------------------------
  // `lang` (not `t`) drives the re-fetch, matching the original `loadRecentRuns` `useCallback`'s own
  // `[t]` dependency array -- see the presets fetch above for why.
  const recentRunsResult = useFetch(
    () => vibeDeskApi.listRuns().then((res) => res.runs),
    [lang],
    { formatError: (err) => errorMessage(err, t("agentDesk.vibe.error.recentRunsLoad")) },
  );
  const recentRuns = recentRunsResult.data ?? [];
  const recentRunsPhase = recentRunsResult.phase;
  const recentRunsMessage = recentRunsResult.error;

  // --- worker model config (the same catalogue Trading Agents' own /config exposes) ------------------
  const configResult = useFetch<VibeConfig>((signal) => vibeDeskApi.config(signal), []);
  const config = configResult.data;
  const configPhase = configResult.phase;

  // --- run form ------------------------------------------------------------------------------------
  const [symbol, setSymbol] = useState("");
  const [question, setQuestion] = useState("");
  const [budgetUsd, setBudgetUsd] = useState("5.00");
  const [live, setLive] = useState(false);
  const [modelChoice, setModelChoice] = useState<string>(CUSTOM_MODEL_CHOICE);
  const [modelChoiceSeeded, setModelChoiceSeeded] = useState(false);
  const [customModel, setCustomModel] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  // Seeds `modelChoice` to the backend's own default the first time config loads -- mirrors
  // `TradingAgents.tsx`'s own `draftSeeded` pattern for the identical reason: run once, and never
  // clobber a choice the reader has since made in the picker.
  useEffect(() => {
    if (!config || modelChoiceSeeded) return;
    setModelChoice(config.default_model);
    setModelChoiceSeeded(true);
  }, [config, modelChoiceSeeded]);

  // The model id actually sent: the picked option, or the free-text field when "Custom version…" is
  // selected. Empty (a blank custom field) omits `model` from the request, letting the backend apply
  // its own `DESK_DEFAULT_MODEL`.
  const selectedModel =
    modelChoice === CUSTOM_MODEL_CHOICE ? customModel.trim() : modelChoice;

  // --- the active run + its DAG board --------------------------------------------------------------
  const [run, setRun] = useState<DeskRun | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [selectedStageId, setSelectedStageId] = useState<string | null>(null);

  // Polls `getRun` every 2000ms while the run is queued/running -- mirrors `Competition.tsx`'s own
  // job-poll effect. The dependency array (`run_id`, `state`) is what clears the interval the moment
  // `state` settles, so nothing keeps polling a run that has already finished.
  useEffect(() => {
    if (!run || !isRunActive(run.state)) return;
    const runId = run.run_id;
    const id = setInterval(() => {
      vibeDeskApi
        .getRun(runId)
        .then((updated) => setRun(updated))
        .catch(() => {
          // A transient poll failure is not fatal -- the board keeps its last known state and the
          // next tick tries again.
        });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [run?.run_id, run?.state]);

  // Once a run settles, the recent-runs list is stale (this run's own row still shows its prior
  // state) -- refresh it exactly once per terminal transition.
  useEffect(() => {
    if (run && !isRunActive(run.state)) {
      recentRunsResult.reload();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `reload` is stable across renders.
  }, [run?.run_id, run?.state]);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedPresetName) return;
    setStartError(null);
    setStarting(true);
    try {
      const trimmedSymbol = symbol.trim();
      const trimmedQuestion = question.trim();
      const body: StartSwarmRequest = {
        preset: selectedPresetName,
        budget_usd: budgetUsd,
        ...(trimmedSymbol ? { symbol: trimmedSymbol.toUpperCase() } : {}),
        ...(trimmedQuestion ? { question: trimmedQuestion } : {}),
        ...(Object.keys(variablesInput).length > 0 ? { variables: variablesInput } : {}),
        ...(selectedModel ? { model: selectedModel } : {}),
        ...(live ? { live: true } : {}),
      };
      const started = await vibeDeskApi.startRun(body);
      setRun(started);
      setSelectedStageId(null);
    } catch (err) {
      setStartError(errorMessage(err, t("agentDesk.vibe.error.startRun")));
    } finally {
      setStarting(false);
    }
  };

  const openRun = (runId: string) => {
    setRunError(null);
    vibeDeskApi
      .getRun(runId)
      .then((res) => {
        setRun(res);
        setSelectedStageId(null);
      })
      .catch((err: unknown) => {
        setRunError(errorMessage(err, t("agentDesk.vibe.error.runLoad")));
      });
  };

  const agentUnavailable = agentHealth !== null && !agentHealth.available;
  const selectedStage = run?.stages.find((s) => s.stage_id === selectedStageId) ?? null;

  const Heading = embedded ? "h2" : "h1";

  return (
    <>
      <Heading>{t("agentDesk.vibe.title")}</Heading>
      <p className="subtitle">{t("agentDesk.vibe.subtitle")}</p>

      <section className="panel vibe-explainer">
        <h2>{t("agentDesk.vibe.explainerPanel.title")}</h2>
        <InfoNote summary={t("agentDesk.vibe.explainerPanel.summary")}>
          <ol>
            {EXPLAINER_STEPS.map((stepKey) => (
              <li key={stepKey}>{t(stepKey)}</li>
            ))}
          </ol>
        </InfoNote>
      </section>

      <PanelBoundary label={t("agentDesk.vibe.panel.presetPicker")}>
        <section className="panel">
          <h2>{t("agentDesk.vibe.presetPicker.title")}</h2>
          {presetsPhase === "loading" && (
            <p className="muted">{t("agentDesk.vibe.presetPicker.loading")}</p>
          )}
          {presetsPhase === "error" && (
            <p className="callout callout-danger">{presetsMessage}</p>
          )}
          {presetsPhase === "loaded" && presets.length === 0 && (
            <p className="muted">{t("agentDesk.vibe.presetPicker.empty")}</p>
          )}
          {presetsPhase === "loaded" && presets.length > 0 && (
            <div className="vibe-preset-list">
              {presets.map((preset) => (
                <button
                  type="button"
                  key={preset.name}
                  className={`vibe-preset-card${preset.name === selectedPresetName ? " selected" : ""}`}
                  aria-pressed={preset.name === selectedPresetName}
                  onClick={() => setSelectedPresetName(preset.name)}
                >
                  <strong>{preset.label}</strong>
                  <span className="muted">{preset.blurb}</span>
                  <span className="vibe-preset-meta">
                    {t("agentDesk.vibe.presetPicker.meta", {
                      agents: preset.agent_count,
                      layers: preset.layer_count,
                    })}
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>
      </PanelBoundary>

      <PanelBoundary label={t("agentDesk.vibe.panel.runConfig")}>
        <section className="panel">
          <h2>{t("agentDesk.vibe.runConfig.title")}</h2>
          {presetDetailPhase === "loading" && (
            <p className="muted">{t("agentDesk.vibe.runConfig.loadingDetail")}</p>
          )}
          {presetDetailPhase === "error" && (
            <p className="callout callout-danger">{presetDetailMessage}</p>
          )}
          {presetDetail && (
            <form className="vibe-run-form" onSubmit={(e) => void handleSubmit(e)}>
              <p className="muted">
                {t("agentDesk.vibe.runConfig.agentsSummary", {
                  agents: presetDetail.agents.length,
                  layers: presetDetail.layer_count,
                })}
              </p>

              <label className="vibe-field">
                <span>{t("common.symbol")}</span>
                <input
                  type="text"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                  placeholder={t("agentDesk.vibe.runConfig.symbolPlaceholder")}
                />
              </label>

              <label className="vibe-field">
                <span>{t("agentDesk.vibe.runConfig.question")}</span>
                <textarea
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder={t("agentDesk.vibe.runConfig.questionPlaceholder")}
                />
              </label>

              {/* `symbol` and `question` have dedicated fields above. A preset still declares
                  `symbol` as a variable so the backend can express "this preset requires one"
                  (see app/vibedesk/service.py `_validate_variables`), but rendering it here too
                  would put a second Symbol box on the form. Skip both here; the dedicated fields
                  are the source of truth and what the request actually sends. */}
              {presetDetail.variables
                .filter((variable) => variable.name !== "symbol" && variable.name !== "question")
                .map((variable) => (
                <label className="vibe-field" key={variable.name}>
                  <span>
                    {variable.label}
                    {variable.required ? " *" : ""}
                  </span>
                  <input
                    type="text"
                    required={variable.required}
                    value={variablesInput[variable.name] ?? ""}
                    onChange={(e) =>
                      setVariablesInput((prev) => ({ ...prev, [variable.name]: e.target.value }))
                    }
                  />
                </label>
              ))}

              <label className="vibe-field">
                <span>{t("common.budgetCapUsd")}</span>
                <input
                  type="text"
                  value={budgetUsd}
                  onChange={(e) => setBudgetUsd(e.target.value)}
                />
              </label>

              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={live}
                  onChange={(e) => setLive(e.target.checked)}
                />
                {t("agentDesk.vibe.runConfig.live")}
              </label>
              {live && <p className="muted">{t("agentDesk.vibe.runConfig.liveHint")}</p>}

              <label className="vibe-field">
                <span>{t("agentDesk.vibe.runConfig.workerModel")}</span>
                <select
                  value={modelChoice}
                  onChange={(e) => setModelChoice(e.target.value)}
                >
                  {config?.available_models.map((m) => (
                    <option value={m.id} key={m.id}>
                      {m.label}
                    </option>
                  ))}
                  <option value={CUSTOM_MODEL_CHOICE}>{t("agentDesk.vibe.model.custom")}</option>
                </select>
                {configPhase === "error" && (
                  <span className="muted">{t("agentDesk.vibe.model.configError")}</span>
                )}
              </label>

              {modelChoice === CUSTOM_MODEL_CHOICE && (
                <label className="vibe-field">
                  <span>{t("agentDesk.vibe.runConfig.customModelId")}</span>
                  <input
                    type="text"
                    value={customModel}
                    onChange={(e) => setCustomModel(e.target.value)}
                    placeholder={t("agentDesk.vibe.runConfig.customModelPlaceholder")}
                  />
                </label>
              )}

              {agentUnavailable && agentHealth && (
                <p className="callout callout-warn vibe-agent-unavailable">
                  {t("agentDesk.vibe.runConfig.agentUnavailable", { reason: agentHealth.reason })}
                </p>
              )}
              {startError && <p className="callout callout-danger">{startError}</p>}

              <button
                type="submit"
                className="comp-run-cta"
                disabled={starting || !selectedPresetName || agentUnavailable}
              >
                {starting
                  ? t("agentDesk.vibe.runConfig.starting")
                  : t("agentDesk.vibe.runConfig.startRun")}
              </button>
            </form>
          )}
        </section>
      </PanelBoundary>

      {run && (
        <PanelBoundary label={t("agentDesk.vibe.panel.runProgress")}>
          <section className="panel">
            <h2>{t("agentDesk.vibe.runProgress.title")}</h2>
            <p className="muted">
              {t("agentDesk.vibe.runProgress.summary", {
                state: run.state,
                spent: formatMoney(run.budget.spent_usd),
                cap: formatMoney(run.budget.cap_usd),
                calls: run.budget.calls,
              })}
            </p>
            {runError && <p className="callout callout-danger">{runError}</p>}
            {run.error && <p className="callout callout-danger">{run.error}</p>}

            <div className="vibe-dag">
              {groupByLayer(run.stages).map(([layer, stages]) => (
                <div className="vibe-dag-layer" key={layer}>
                  <div className="vibe-dag-layer-label">{t("agentDesk.vibe.dag.layer", { layer })}</div>
                  <div className="vibe-dag-layer-stages">
                    {stages.map((stage) => (
                      <button
                        type="button"
                        key={stage.stage_id}
                        data-state={stage.state}
                        className={`vibe-stage vibe-stage-${stage.state}${
                          stage.stage_id === selectedStageId ? " selected" : ""
                        }`}
                        onClick={() => setSelectedStageId(stage.stage_id)}
                      >
                        <span className="vibe-stage-seat">{stage.seat || stage.role}</span>
                        <span className="vibe-stage-label">{stage.label}</span>
                        <StatusPill tone={stageTone(stage.state)} label={stageStateLabel(t, stage.state)} />
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {selectedStage && (
              <div className="panel vibe-stage-detail">
                <h3>{selectedStage.label}</h3>
                <p className="muted">
                  {t("agentDesk.vibe.stageDetail.meta", {
                    seat: selectedStage.seat || "—",
                    state: stageStateLabel(t, selectedStage.state),
                    cost: formatMoney(selectedStage.cost_usd),
                  })}
                </p>
                {selectedStage.error && (
                  <p className="callout callout-danger">{selectedStage.error}</p>
                )}
                {selectedStage.grounding?.degraded && (
                  <div className="callout callout-warn vibe-grounding-issues">
                    <strong>{t("agentDesk.vibe.stageDetail.groundingDegraded")}</strong>
                    {/* `issue.kind` is the grounding checker's own raw enum value and `issue.detail`
                        is its diagnostic text -- both left untranslated. */}
                    <ul>
                      {selectedStage.grounding.issues.map((issue, i) => (
                        <li key={`${issue.kind}-${i}`}>
                          {issue.kind}: {issue.detail}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <span className="badge" title={t("common.sourceEnglishTitle")}>
                  {t("common.sourceEnglish")}
                </span>
                <ScrollRegion size="md" label={t("agentDesk.vibe.runProgress.title")}>
                  <pre className="vibe-output-md">
                    {selectedStage.output_md || t("agentDesk.vibe.stageDetail.noOutputYet")}
                  </pre>
                </ScrollRegion>
              </div>
            )}

            {run.final_md && (
              <div className="panel vibe-final-report">
                <h3>{t("common.finalReport")}</h3>
                {vibeRunSymbol(run) && (
                  <Link to={`/symbol/${vibeRunSymbol(run)}?tab=report`} className="vibe-open-report">
                    {t("agentDesk.vibe.openReport", { symbol: vibeRunSymbol(run) ?? "" })}
                  </Link>
                )}
                <span className="badge" title={t("common.sourceEnglishTitle")}>
                  {t("common.sourceEnglish")}
                </span>
                <ScrollRegion size="md" label={t("common.finalReport")}>
                  <pre className="vibe-output-md">{run.final_md}</pre>
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
            <p className="muted">{t("agentDesk.vibe.recentRuns.loading")}</p>
          )}
          {recentRunsPhase === "error" && (
            <p className="callout callout-danger">{recentRunsMessage}</p>
          )}
          {recentRunsPhase === "loaded" && recentRuns.length === 0 && (
            <p className="muted">{t("agentDesk.vibe.recentRuns.empty")}</p>
          )}
          {recentRunsPhase === "loaded" && recentRuns.length > 0 && (
            <ScrollRegion size="md" label={t("common.recentRuns")}>
              <ul className="vibe-recent-runs">
                {recentRuns.map((summary) => (
                  <li key={summary.run_id}>
                    <button type="button" onClick={() => openRun(summary.run_id)}>
                      <span>{summary.label}</span>
                      {/* Exactly one state pill per row (UX-15) -- `runDisplayState` derives the
                          display label/tone (demoting a long-stuck `running` row to "stale") and
                          folds `degraded` into this pill's own `detail` rather than a second pill. */}
                      {(() => {
                        const display = runDisplayState(t, summary);
                        return (
                          <StatusPill tone={display.tone} label={display.label} detail={display.detail} />
                        );
                      })()}
                      <span className="muted">
                        {t("agentDesk.vibe.recentRuns.stagesCount", {
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
  );
}
