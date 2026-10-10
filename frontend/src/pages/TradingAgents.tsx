/**
 * Trading Agents: a full analyst-to-portfolio-manager pipeline run on one ticker.
 *
 * Two parts, per the owner's brief (see `docs/AGENT-DESK-CONTRACT.md`, "Page layout"):
 *
 * 1. **A static explainer** (`EXPLAINER_STEPS` below), rendered from a constant, never fetched --
 *    the "brief summary of how it is working" the feature was asked for.
 * 2. **The working surface**: a run form, a live progress board keyed on the contract's fixed
 *    `stage_id` values and grouped by `layer`, per-stage expandable output, the final report, cost
 *    so far, and a recent-runs list.
 * 3. **Decision memory**, below both of the above: the desk's own track record, via
 *    `tradingAgentsApi.memory()` -- previously exported but unused by this page. `alpha_return_pct`
 *    (return over `benchmark`, "SPY") is the headline figure and `raw_return_pct` is secondary, per
 *    the task brief: a decision that made money in a market that made more did not work. Re-fetched
 *    scoped to a run's own symbol when that run reaches a terminal state (see `runSymbol` below) --
 *    not on every keystroke in the still-being-edited symbol box, which is not yet a decision this
 *    desk has made.
 *
 * Every fetch here owns its own `FetchPhase` (`"loading" | "loaded" | "error"`), the same pattern
 * `PaperDesk.tsx`/`Competition.tsx` use -- one bad request must never blank the rest of the page --
 * and each top-level panel is wrapped in its own `PanelBoundary` for the same reason one level down:
 * a bad value inside one panel must not take the others with it.
 *
 * **Polling**: while the selected run's `state` is `"queued"` or `"running"`, `getRun` is polled
 * every 2000ms -- the same job-registry poll shape `Competition.tsx`'s job/loop effects establish.
 * The effect's own dependency array (`run_id`, `state`) is what clears the interval once the run
 * settles into a terminal state, so nothing keeps polling a run that has already finished.
 *
 * **`degraded`, `blocked` and `failed` are three different stage states, not one "error" state.**
 * `degraded` means the stage produced output but its own numbers failed the grounding check three
 * times in a row (`GroundingVerdict.degraded`) -- shown marked "ungrounded" rather than hidden.
 * `blocked` means the stage never ran at all because a dependency failed or was blocked upstream.
 * `failed` means the stage itself threw. Collapsing any two of these into the same badge would tell
 * a reader the wrong thing about where the pipeline actually stopped -- see `TradingAgents.css`'s own
 * comment on the same point.
 *
 * No markdown library is a dependency of this project (checked `frontend/package.json` before
 * assuming one) -- `output_md`/`final_md` render as `<pre className="ta-stage-output">` with
 * `white-space: pre-wrap`, not through a parser this app does not have.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { decimalStringToCents, describeError, parseDecimalString, type DecimalString } from "@/api/client";
import {
  describeStartRunError,
  formatMoney,
  isRunActive,
  tradingAgentsApi,
  type DeskRun,
  type DeskRunSummary,
  type GroundingVerdict,
  type MemoryEntry,
  type RunState,
  type StageRecord,
  type StageState,
  type TradingAgentsConfig,
} from "@/api/tradingagents";
import InfoNote from "@/components/InfoNote";
import PanelBoundary from "@/components/PanelBoundary";
import { ScrollRegion } from "@/components/ScrollPanel";
import StatusPill, { type PillTone } from "@/components/StatusPill";
import { formatFetchError as errorMessage, useFetch, type FetchPhase } from "@/hooks/useFetch";
import { useT, type I18n, type MessageKey } from "@/i18n";
import LiveDecisionsPanel from "@/pages/agentdesk/LiveDecisionsPanel";

import "./TradingAgents.css";

/** Matches the contract's "poll roughly every 2000ms" -- not tied to anything server-side. */
const POLL_INTERVAL_MS = 2000;

/**
 * The pipeline, as a fixed, numbered sequence -- rendered from this constant, never fetched. Mirrors
 * the contract's "Fixed stage ids and labels" table one layer at a time, in plain language: what each
 * stage does and what it hands to the next one. The grounding sentence at the end is stated once,
 * here, rather than re-explained per stage, since it applies to every stage in the pipeline equally.
 */
const EXPLAINER_STEPS: { titleKey: MessageKey; bodyKey: MessageKey }[] = [
  {
    titleKey: "agentDesk.trading.explainer.analysts.title",
    bodyKey: "agentDesk.trading.explainer.analysts.body",
  },
  {
    titleKey: "agentDesk.trading.explainer.debate.title",
    bodyKey: "agentDesk.trading.explainer.debate.body",
  },
  {
    titleKey: "agentDesk.trading.explainer.researchManager.title",
    bodyKey: "agentDesk.trading.explainer.researchManager.body",
  },
  {
    titleKey: "agentDesk.trading.explainer.trader.title",
    bodyKey: "agentDesk.trading.explainer.trader.body",
  },
  {
    titleKey: "agentDesk.trading.explainer.risk.title",
    bodyKey: "agentDesk.trading.explainer.risk.body",
  },
  {
    titleKey: "agentDesk.trading.explainer.pm.title",
    bodyKey: "agentDesk.trading.explainer.pm.body",
  },
];

/** Which layer each stage_id belongs to, in words -- keys are the contract's own `layer` numbers, not
 * re-derived from stage ids (`bull_2`/`risk_neutral_1` etc. do not parse cleanly into a layer on their
 * own). An unrecognised layer number still renders, generically, rather than being dropped -- the
 * conservative reading for a board driven by live server data. */
const LAYER_LABEL_KEYS: Record<number, MessageKey> = {
  0: "agentDesk.trading.layer.analysts",
  1: "agentDesk.trading.layer.debate",
  2: "agentDesk.trading.layer.researchManager",
  3: "agentDesk.trading.layer.trader",
  4: "agentDesk.trading.layer.risk",
  5: "agentDesk.trading.layer.pm",
};

function layerLabel(t: I18n["t"], layer: number): string {
  const key = LAYER_LABEL_KEYS[layer];
  return key ? t(key) : t("agentDesk.trading.layer.fallback", { layer });
}

/** `pending`/`succeeded`/`failed` reuse `common.status.*` -- identical text to what those keys
 * already carry. `running`/`degraded`/`blocked`/`skipped` get their own `agentDesk.trading.*`
 * entries because their wording here differs from (or has no equivalent in) `common.status.*`
 * (`"Running…"` with an ellipsis, `"Degraded (ungrounded)"`, and two states `common.status`
 * does not define at all). */
function stageStateLabel(t: I18n["t"], state: StageState): string {
  switch (state) {
    case "pending":
      return t("status.pending");
    case "running":
      return t("agentDesk.trading.stageState.running");
    case "succeeded":
      return t("status.succeeded");
    case "degraded":
      return t("agentDesk.trading.stageState.degraded");
    case "failed":
      return t("status.failed");
    case "blocked":
      return t("agentDesk.trading.stageState.blocked");
    case "skipped":
      return t("agentDesk.trading.stageState.skipped");
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

/** A day. `DeskRunSummary` (see `@/api/tradingagents`) carries no separate "last updated"
 *  timestamp, so `created_at` is what a still-`running` row is timed against. */
const STALE_RUNNING_MS = 24 * 60 * 60 * 1000;

/**
 * Client-derived display state for one recent-run row (UX-15). The server's raw `state` is never
 * reinterpreted for anything but this one case: a row still reporting `"running"` a day or more
 * after it started is almost certainly stuck, not actually in progress, so it displays as
 * `agentDesk.status.stale` instead. The raw wire value is never thrown away -- when it is no
 * longer the visible label, it is folded into `detail` instead, which `StatusPill` renders as a
 * native `title` (plus `aria-description`), so it stays one hover/read away.
 *
 * Exactly one pill is ever shown per row: `degraded` used to render as a second `StatusPill`
 * next to the state one; it is folded into this same pill's `detail` text instead.
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
  // Raw wire state, kept reachable once it is no longer what the label itself says.
  if (isStale) detailParts.push(r.state);
  if (r.degraded) detailParts.push(t("agentDesk.trading.recentRuns.degradedBadge"));
  return {
    label: isStale ? t("agentDesk.status.stale") : r.state,
    tone: isStale ? "neutral" : runTone(r.state),
    detail: detailParts.length > 0 ? detailParts.join(" · ") : undefined,
  };
}

/**
 * `raw_return_pct`/`alpha_return_pct` (`docs/AGENT-DESK-CONTRACT.md`'s `MemoryEntry`) are not
 * documented as fraction-or-percent in the contract itself, but every other `_pct`-suffixed
 * `DecimalString` already in this codebase (`return_pct` in `@/api/competition` and
 * `@/api/paperdesk`, `stop_loss_pct`, `drawdown_pct`, ...) is a 0-1 fraction, not a pre-multiplied
 * percent -- confirmed against the backend, which computes every one of those as a plain
 * `pnl / basis` ratio. These two fields are named and produced the same way (a realised/benchmark
 * return over a holding window), so they are treated the same: shift the decimal point two places
 * right. Local copy of `formatPctFraction`'s (`@/api/competition`) digit-shifting rule, built on
 * `parseDecimalString` (`@/api/client`) rather than that module's own hand-rolled split, per this
 * task's "never parseFloat a money or return string" instruction -- this module owns no dependency
 * on `@/api/competition`, matching the "one copy per module" convention `@/api/tradingagents`'s own
 * docstring documents for `formatMoney`.
 */
function formatReturnPct(value: DecimalString | null): string {
  if (value === null) return "—";
  const { negative, wholeRaw, fracRaw } = parseDecimalString(value);
  if (/^0*$/.test(wholeRaw) && /^0*$/.test(fracRaw)) return "0.00%";
  const fracPadded = (fracRaw + "0000").slice(0, 4);
  const wholeDigits = ((wholeRaw || "0") + fracPadded.slice(0, 2)).replace(/^0+(?=\d)/, "") || "0";
  const fracPct = fracPadded.slice(2, 4);
  if (wholeDigits === "0" && fracPct === "00") return negative ? ">-0.01%" : "<0.01%";
  return `${negative ? "-" : ""}${wholeDigits}.${fracPct}%`;
}

/** Same as `formatReturnPct`, with an explicit `+` on a positive, non-zero result -- colour is never
 * the only signal for direction, matching `formatSignedPctFraction` (`@/api/competition`). */
function formatSignedReturnPct(value: DecimalString | null): string {
  if (value === null) return "—";
  const rendered = formatReturnPct(value);
  const alreadySigned = rendered.startsWith("-") || rendered.startsWith(">") || rendered.startsWith("<");
  return alreadySigned || rendered === "0.00%" ? rendered : `+${rendered}`;
}

/** `"pos" | "neg" | ""` colour class for a signed return -- `""` for exactly zero or `null`, so a
 * pending or flat entry never picks up gain/loss colouring it did not earn. Mirrors `fractionTone`
 * (`@/api/competition`). */
function returnTone(value: DecimalString | null): "pos" | "neg" | "" {
  if (value === null) return "";
  const { negative, wholeRaw, fracRaw } = parseDecimalString(value);
  if (/^0*$/.test(wholeRaw) && /^0*$/.test(fracRaw)) return "";
  return negative ? "neg" : "pos";
}

/** Reads the symbol a run was started for out of its own echoed-back `config` -- `DeskRun.config` is
 * an untyped `Record<string, unknown>` (shared with Vibe Trading, which may not carry a `symbol` key
 * at all), so this is read defensively rather than assumed. Used to scope the memory re-fetch below
 * to the run that just settled, without keeping a second copy of the symbol in component state. */
function runSymbol(run: DeskRun | null): string | undefined {
  const raw = run?.config?.["symbol"];
  return typeof raw === "string" && raw.trim() ? raw.trim() : undefined;
}

/** Groups a run's stages by `layer`, preserving each layer's own stage order and sorting layers
 * ascending -- the board's structure follows the contract's fixed layer numbers, not an assumption
 * about how many stages exist (debate/risk rounds vary the count within layers 1 and 4). */
function groupByLayer(stages: StageRecord[]): { layer: number; stages: StageRecord[] }[] {
  const byLayer = new Map<number, StageRecord[]>();
  for (const stage of stages) {
    const bucket = byLayer.get(stage.layer);
    if (bucket) bucket.push(stage);
    else byLayer.set(stage.layer, [stage]);
  }
  return [...byLayer.entries()]
    .sort(([a], [b]) => a - b)
    .map(([layer, layerStages]) => ({ layer, stages: layerStages }));
}

/** The run form's own draft state -- kept separate from `StartRunRequest` because a couple of its
 * fields are raw text a reader may be mid-editing (the symbol box, the budget box), the same reason
 * `@/api/evolution`'s `LoopFormDraft` is kept distinct from `Partial<LoopConfig>`. */
interface RunFormDraft {
  symbol: string;
  tradeDate: string;
  analysts: Set<string>;
  debateRounds: number;
  riskRounds: number;
  budgetUsd: string;
  model: string;
  live: boolean;
}

export interface TradingAgentsProps {
  /**
   * True when this page is mounted as a TAB BODY (e.g. `ResearchDesk.tsx`) rather than as its own
   * route. Only one thing changes: the page heading drops from `<h1>` to `<h2>`, so a host page
   * that already renders the document's own `<h1>` does not end up with two top-level headings in
   * a screen reader's heading list (A11Y-02). Optional and defaulted, so `/trading-agents` and
   * every existing test keep the `<h1>` they had. Mirrors `Rules.tsx`/`Timeframes.tsx`/
   * `Backtest.tsx`'s own `embedded` prop.
   *
   * NOTE (handoff): `ResearchDesk.tsx` does not pass this prop yet -- it is outside this change's
   * scope fence. Passing `embedded` from there closes the same two-`<h1>` gap this prop fixes here.
   */
  embedded?: boolean | undefined;
}

export default function TradingAgents({ embedded = false }: TradingAgentsProps = {}) {
  const { t, lang } = useT();

  // --- config ------------------------------------------------------------------------------------
  const configResult = useFetch<TradingAgentsConfig>(
    (signal) => tradingAgentsApi.config(signal),
    [],
    { formatError: (err) => errorMessage(err, t("agentDesk.trading.error.configLoad")) },
  );
  const config = configResult.data;
  const configPhase = configResult.phase;
  const configMessage = configResult.error;

  // --- run form draft, seeded from config's own defaults once it loads -----------------------------
  const [draft, setDraft] = useState<RunFormDraft>({
    symbol: "",
    tradeDate: "",
    analysts: new Set(),
    debateRounds: 1,
    riskRounds: 1,
    budgetUsd: "",
    model: "",
    live: false,
  });
  const [draftSeeded, setDraftSeeded] = useState(false);

  useEffect(() => {
    if (!config || draftSeeded) return;
    setDraft((prev) => ({
      ...prev,
      analysts: new Set(config.analysts.map((a) => a.key)),
      debateRounds: config.default_debate_rounds,
      riskRounds: config.default_risk_rounds,
      budgetUsd: config.default_budget_usd,
      model: config.default_model,
    }));
    setDraftSeeded(true);
  }, [config, draftSeeded]);

  const toggleAnalyst = useCallback((key: string) => {
    setDraft((prev) => {
      const next = new Set(prev.analysts);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return { ...prev, analysts: next };
    });
  }, []);

  const clampRounds = useCallback(
    (value: number) => {
      const max = config?.max_rounds ?? 3;
      if (Number.isNaN(value)) return 1;
      return Math.min(Math.max(1, Math.trunc(value)), max);
    },
    [config?.max_rounds],
  );

  // --- recent runs ---------------------------------------------------------------------------------
  // `lang` (not `t`) drives the re-fetch, matching the original `loadRuns` `useCallback`'s own `[t]`
  // dependency array -- `t`'s own identity already changes with `lang`, and `useFetch` reads
  // `formatError` via a ref rather than as a dependency, so `lang` is named directly here.
  const runsResult = useFetch(
    () => tradingAgentsApi.listRuns().then((res) => res.runs),
    [lang],
    { formatError: (err) => errorMessage(err, t("agentDesk.trading.error.runsLoad")) },
  );
  const runs = runsResult.data ?? [];
  const runsPhase = runsResult.phase;
  const runsMessage = runsResult.error;
  const loadRuns = runsResult.reload;

  // --- decision memory -------------------------------------------------------------------------
  // Own `FetchPhase`, independent of every other panel's -- a failed memory fetch must not blank
  // the run form or the progress board (same rule the module docstring states for every panel here).
  // Declared here, ahead of the run-polling effect below, since that effect calls `loadMemory` once
  // a run settles.
  const [memoryEntries, setMemoryEntries] = useState<MemoryEntry[]>([]);
  const [memoryPhase, setMemoryPhase] = useState<FetchPhase>("loading");
  const [memoryMessage, setMemoryMessage] = useState<string | null>(null);
  const [expandedDecisions, setExpandedDecisions] = useState<Set<string>>(new Set());

  const loadMemory = useCallback((symbol?: string) => {
    setMemoryPhase("loading");
    tradingAgentsApi
      .memory(symbol)
      .then((res) => {
        setMemoryEntries(res.entries);
        setMemoryPhase("loaded");
      })
      .catch((err: unknown) => {
        setMemoryMessage(errorMessage(err, t("agentDesk.trading.error.memoryLoad")));
        setMemoryPhase("error");
      });
  }, [t]);

  // Unscoped on mount -- every entry the desk has recorded, not just the symbol sitting in the run
  // form's draft (which may be empty, or mid-edit, at the moment this page opens).
  useEffect(() => {
    loadMemory();
  }, [loadMemory]);

  const toggleDecision = useCallback((entryId: string) => {
    setExpandedDecisions((prev) => {
      const next = new Set(prev);
      if (next.has(entryId)) next.delete(entryId);
      else next.add(entryId);
      return next;
    });
  }, []);

  // Newest first by `trade_date` -- an ISO date string, so a plain lexicographic comparison already
  // sorts chronologically without needing to parse it into a `Date`.
  const sortedMemory = useMemo(
    () =>
      [...memoryEntries].sort((a, b) =>
        a.trade_date < b.trade_date ? 1 : a.trade_date > b.trade_date ? -1 : 0,
      ),
    [memoryEntries],
  );

  // --- selected/active run --------------------------------------------------------------------------
  const [selectedRun, setSelectedRun] = useState<DeskRun | null>(null);
  const [runPhase, setRunPhase] = useState<FetchPhase | null>(null);
  const [runMessage, setRunMessage] = useState<string | null>(null);
  const [expandedStages, setExpandedStages] = useState<Set<string>>(new Set());

  const openRun = useCallback((runId: string) => {
    setRunPhase("loading");
    setRunMessage(null);
    tradingAgentsApi
      .getRun(runId)
      .then((run) => {
        setSelectedRun(run);
        setRunPhase("loaded");
      })
      .catch((err: unknown) => {
        setRunMessage(errorMessage(err, t("agentDesk.trading.error.runLoad")));
        setRunPhase("error");
      });
  }, [t]);

  // Polls `getRun` every 2s while the selected run is queued/running -- cleared on unmount and the
  // moment the run reaches a terminal state, via the dependency array below (mirrors
  // `Competition.tsx`'s job/loop poll effects).
  useEffect(() => {
    if (!selectedRun || !isRunActive(selectedRun.state)) return;
    const runId = selectedRun.run_id;
    const id = setInterval(() => {
      tradingAgentsApi
        .getRun(runId)
        .then((updated) => {
          setSelectedRun(updated);
          if (!isRunActive(updated.state)) {
            // The run just settled -- refresh the recent-runs list once so its summary (cost,
            // final_rating, stages_done) stops reading stale, without polling that list on its own
            // timer. Decision memory is re-fetched here too, scoped to this run's own symbol: run
            // completion (not a symbol-box keystroke) is the moment a new memory entry can actually
            // exist for it, so this is the one point re-fetching scoped to a symbol earns its cost.
            loadRuns();
            loadMemory(runSymbol(updated));
          }
        })
        .catch(() => {
          // A transient poll failure is not fatal -- the board keeps its last known state and the
          // next tick tries again, rather than the whole page erroring out mid-run.
        });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [selectedRun?.run_id, selectedRun?.state, loadRuns, loadMemory]);

  const toggleStage = useCallback((stageId: string) => {
    setExpandedStages((prev) => {
      const next = new Set(prev);
      if (next.has(stageId)) next.delete(stageId);
      else next.add(stageId);
      return next;
    });
  }, []);

  // --- starting a run --------------------------------------------------------------------------------
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const handleStart = useCallback(() => {
    const symbol = draft.symbol.trim().toUpperCase();
    if (!symbol) {
      setStartError(t("agentDesk.trading.startError.symbolRequired"));
      return;
    }
    setStartError(null);
    setStarting(true);
    tradingAgentsApi
      .startRun({
        symbol,
        ...(draft.live ? {} : draft.tradeDate ? { trade_date: draft.tradeDate } : {}),
        analysts: [...draft.analysts],
        debate_rounds: draft.debateRounds,
        risk_rounds: draft.riskRounds,
        ...(draft.budgetUsd.trim() ? { budget_usd: draft.budgetUsd.trim() } : {}),
        ...(draft.model ? { model: draft.model } : {}),
        ...(draft.live ? { live: true } : {}),
      })
      .then((run) => {
        setSelectedRun(run);
        setRunPhase("loaded");
        setRunMessage(null);
        setExpandedStages(new Set());
        loadRuns();
      })
      .catch((err: unknown) => {
        setStartError(describeStartRunError(err));
      })
      .finally(() => {
        setStarting(false);
      });
  }, [draft, loadRuns, t]);

  const handleCancel = useCallback(() => {
    if (!selectedRun) return;
    tradingAgentsApi
      .cancelRun(selectedRun.run_id)
      .then((updated) => {
        setSelectedRun(updated);
        loadRuns();
        loadMemory(runSymbol(updated));
      })
      .catch((err: unknown) => {
        setRunMessage(describeError(err, t("agentDesk.trading.error.cancelRun")));
      });
  }, [selectedRun, loadRuns, loadMemory, t]);

  const startDisabled = starting || (config !== null && !config.agent_available) || configPhase === "loading";

  const layers = useMemo(() => (selectedRun ? groupByLayer(selectedRun.stages) : []), [selectedRun]);

  const Heading = embedded ? "h2" : "h1";

  return (
    <>
      <Heading>{t("agentDesk.trading.title")}</Heading>
      <p className="subtitle">{t("agentDesk.trading.subtitle")}</p>

      <PanelBoundary label={t("agentDesk.trading.panel.howItWorks")}>
        <section className="panel">
          <h2>{t("agentDesk.trading.explainerPanel.title")}</h2>
          <InfoNote summary={t("agentDesk.trading.explainerPanel.summary")}>
            <ol className="ta-explainer-list">
              {EXPLAINER_STEPS.map((step, i) => (
                <li className="ta-explainer-step" key={step.titleKey}>
                  <span className="ta-explainer-index" aria-hidden="true">
                    {i + 1}
                  </span>
                  <div className="ta-explainer-body">
                    <h3>{t(step.titleKey)}</h3>
                    <p>{t(step.bodyKey)}</p>
                  </div>
                </li>
              ))}
            </ol>
            <p className="muted">{t("agentDesk.trading.explainerPanel.footer")}</p>
          </InfoNote>
        </section>
      </PanelBoundary>

      <PanelBoundary label={t("agentDesk.trading.panel.runForm")}>
        <section className="panel">
          <h2>{t("agentDesk.trading.runForm.title")}</h2>
          {configPhase === "loading" && (
            <div className="placeholder">{t("agentDesk.trading.runForm.loadingConfig")}</div>
          )}
          {configPhase === "error" && <div className="placeholder">{configMessage}</div>}
          {configPhase === "loaded" && config && !config.agent_available && (
            <div className="callout callout-warn ta-unavailable-note" role="alert">
              <strong>{t("agentDesk.trading.agentUnavailable")}</strong> {config.agent_reason}
            </div>
          )}
          {configPhase === "loaded" && config && (
            <form
              className="ta-run-form"
              onSubmit={(e) => {
                e.preventDefault();
                handleStart();
              }}
            >
              <div className="filter-bar">
                <label>
                  <span>{t("common.symbol")}</span>
                  <input
                    className="symbol-input"
                    value={draft.symbol}
                    onChange={(e) => setDraft((prev) => ({ ...prev, symbol: e.target.value }))}
                    placeholder="NVDA"
                    required
                  />
                </label>
                <label>
                  <span>{t("agentDesk.trading.runForm.tradeDate")}</span>
                  <input
                    type="date"
                    value={draft.tradeDate}
                    disabled={draft.live}
                    onChange={(e) => setDraft((prev) => ({ ...prev, tradeDate: e.target.value }))}
                  />
                </label>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={draft.live}
                    onChange={(e) => {
                      const live = e.target.checked;
                      setDraft((prev) => ({ ...prev, live, tradeDate: live ? "" : prev.tradeDate }));
                    }}
                  />
                  {t("agentDesk.trading.runForm.live")}
                </label>
                <label>
                  <span>{t("agentDesk.trading.runForm.debateRounds", { max: config.max_rounds })}</span>
                  <input
                    type="number"
                    min={1}
                    max={config.max_rounds}
                    value={draft.debateRounds}
                    onChange={(e) =>
                      setDraft((prev) => ({ ...prev, debateRounds: clampRounds(Number(e.target.value)) }))
                    }
                  />
                </label>
                <label>
                  <span>{t("agentDesk.trading.runForm.riskRounds", { max: config.max_rounds })}</span>
                  <input
                    type="number"
                    min={1}
                    max={config.max_rounds}
                    value={draft.riskRounds}
                    onChange={(e) =>
                      setDraft((prev) => ({ ...prev, riskRounds: clampRounds(Number(e.target.value)) }))
                    }
                  />
                </label>
                <label>
                  <span>{t("common.budgetCapUsd")}</span>
                  <input
                    value={draft.budgetUsd}
                    onChange={(e) => setDraft((prev) => ({ ...prev, budgetUsd: e.target.value }))}
                    placeholder={config.default_budget_usd}
                  />
                </label>
                <label>
                  <span>{t("agentDesk.trading.runForm.model")}</span>
                  <select
                    value={draft.model}
                    onChange={(e) => setDraft((prev) => ({ ...prev, model: e.target.value }))}
                  >
                    {config.available_models.map((m) => (
                      <option value={m.id} key={m.id}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {draft.live && <p className="muted">{t("agentDesk.trading.runForm.liveHint")}</p>}

              <div>
                <h3>{t("agentDesk.trading.layer.analysts")}</h3>
                <div className="ta-analyst-grid">
                  {config.analysts.map((a) => (
                    <label className="ta-analyst-option" key={a.key}>
                      <input
                        type="checkbox"
                        checked={draft.analysts.has(a.key)}
                        onChange={() => toggleAnalyst(a.key)}
                      />
                      <span>
                        {a.label}
                        <span className="ta-analyst-blurb">{a.blurb}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="ta-start-row">
                <button
                  type="submit"
                  className="ta-start-button"
                  disabled={startDisabled}
                  title={
                    config.agent_available
                      ? undefined
                      : config.agent_reason || t("agentDesk.trading.agentUnavailable")
                  }
                >
                  {starting ? t("agentDesk.trading.runForm.starting") : t("agentDesk.trading.runForm.start")}
                </button>
                {startError && (
                  <span className="callout callout-danger" role="alert" style={{ padding: "0.35rem 0.6rem" }}>
                    {startError}
                  </span>
                )}
              </div>
            </form>
          )}
        </section>
      </PanelBoundary>

      <PanelBoundary label={t("common.recentRuns")}>
        <section className="panel">
          <h2>{t("common.recentRuns")}</h2>
          {runsPhase === "loading" && (
            <div className="placeholder">{t("agentDesk.trading.recentRuns.loading")}</div>
          )}
          {runsPhase === "error" && <div className="placeholder">{runsMessage}</div>}
          {runsPhase === "loaded" && runs.length === 0 && (
            <div className="placeholder">{t("agentDesk.trading.recentRuns.empty")}</div>
          )}
          {runsPhase === "loaded" && runs.length > 0 && (
            <ScrollRegion size="md" label={t("common.recentRuns")}>
              <div className="ta-runs-list">
                {runs.map((r) => (
                  <button
                    type="button"
                    key={r.run_id}
                    className={`ta-run-row${selectedRun?.run_id === r.run_id ? " active" : ""}`}
                    onClick={() => openRun(r.run_id)}
                  >
                    <span className="ta-run-row-label">{r.label}</span>
                    <span className="ta-run-row-meta">
                      {/* Exactly one state pill per row (UX-15) -- `runDisplayState` derives the
                          display label/tone (demoting a long-stuck `running` row to "stale") and
                          folds `degraded` into this pill's own `detail` rather than a second pill.
                          The raw wire `state` still reaches assistive tech / hover via `title`. */}
                      {(() => {
                        const display = runDisplayState(t, r);
                        return (
                          <StatusPill tone={display.tone} label={display.label} detail={display.detail} />
                        );
                      })()}
                      <span>{r.final_rating || "—"}</span>
                      <span>{formatMoney(r.cost_usd)}</span>
                      <span>
                        {t("agentDesk.trading.recentRuns.stagesCount", {
                          done: r.stages_done,
                          total: r.stages_total,
                        })}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            </ScrollRegion>
          )}
        </section>
      </PanelBoundary>

      {runPhase === "loading" && (
        <section className="panel">
          <div className="placeholder">{t("agentDesk.trading.run.loading")}</div>
        </section>
      )}
      {runPhase === "error" && (
        <section className="panel">
          <div className="placeholder">{runMessage}</div>
        </section>
      )}

      {runPhase === "loaded" && selectedRun && (
        <>
          <PanelBoundary label={t("agentDesk.trading.panel.progressBoard")}>
            <section className="panel">
              <div className="ta-final-head">
                {/* `selectedRun.state` is the raw wire value -- passed through the `{state}` slot
                    verbatim, not translated, so the heading still says "running"/"succeeded" etc.
                    exactly as the backend sent it. */}
                <h2>
                  {t("agentDesk.trading.progressBoard.heading", { state: selectedRun.state })}
                </h2>
                {isRunActive(selectedRun.state) && (
                  <button type="button" className="ta-start-button" onClick={handleCancel}>
                    {t("agentDesk.trading.progressBoard.cancelRun")}
                  </button>
                )}
              </div>
              <BudgetBar budget={selectedRun.budget} t={t} />
              {selectedRun.error && (
                <div className="callout callout-danger ta-stage-error" role="alert">
                  {selectedRun.error}
                </div>
              )}
              {layers.map(({ layer, stages }) => (
                <div className="ta-layer" key={layer}>
                  <h3 className="ta-layer-title">{layerLabel(t, layer)}</h3>
                  <div className="ta-stage-grid">
                    {stages.map((stage) => (
                      <StageRow
                        key={stage.stage_id}
                        stage={stage}
                        expanded={expandedStages.has(stage.stage_id)}
                        onToggle={() => toggleStage(stage.stage_id)}
                        t={t}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </section>
          </PanelBoundary>

          <PanelBoundary label={t("common.finalReport")}>
            <section className="panel">
              <div className="ta-final-head">
                <h2>{t("common.finalReport")}</h2>
                {selectedRun.final_rating && (
                  <span className="badge ta-rating">{selectedRun.final_rating}</span>
                )}
              </div>
              {runSymbol(selectedRun) && (
                <Link to={`/symbol/${runSymbol(selectedRun)}?tab=report`} className="ta-open-report">
                  {t("agentDesk.trading.openReport", { symbol: runSymbol(selectedRun) ?? "" })}
                </Link>
              )}
              {selectedRun.final_md ? (
                <>
                  <span className="badge" title={t("common.sourceEnglishTitle")}>
                    {t("common.sourceEnglish")}
                  </span>
                  <ScrollRegion size="md" label={t("common.finalReport")}>
                    <pre className="ta-stage-output">{selectedRun.final_md}</pre>
                  </ScrollRegion>
                </>
              ) : (
                <div className="placeholder">{t("agentDesk.trading.finalReport.empty")}</div>
              )}
            </section>
          </PanelBoundary>
        </>
      )}

      <PanelBoundary label={t("agentDesk.trading.panel.decisionMemory")}>
        <section className="panel">
          <h2>{t("agentDesk.trading.memory.title")}</h2>
          <p className="muted">{t("agentDesk.trading.memory.description")}</p>
          {memoryPhase === "loading" && (
            <div className="placeholder">{t("agentDesk.trading.memory.loading")}</div>
          )}
          {memoryPhase === "error" && <div className="placeholder">{memoryMessage}</div>}
          {memoryPhase === "loaded" && sortedMemory.length === 0 && (
            <div className="placeholder">{t("agentDesk.trading.memory.empty")}</div>
          )}
          {memoryPhase === "loaded" && sortedMemory.length > 0 && (
            <ScrollRegion size="md" label={t("agentDesk.trading.memory.title")}>
              <div className="ta-memory-list">
                {sortedMemory.map((entry) => (
                  <MemoryRow
                    key={entry.entry_id}
                    entry={entry}
                    expanded={expandedDecisions.has(entry.entry_id)}
                    onToggle={() => toggleDecision(entry.entry_id)}
                    t={t}
                  />
                ))}
              </div>
            </ScrollRegion>
          )}
        </section>
      </PanelBoundary>

      <PanelBoundary label={t("agentDesk.live.heading")}>
        <LiveDecisionsPanel />
      </PanelBoundary>
    </>
  );
}

function BudgetBar({ budget, t }: { budget: DeskRun["budget"]; t: I18n["t"] }) {
  const capCents = decimalStringToCents(budget.cap_usd);
  const spentCents = decimalStringToCents(budget.spent_usd);
  const pct = capCents > 0n ? Number((spentCents * 100n) / capCents) : 0;
  const clamped = Math.min(100, Math.max(0, pct));
  const over = spentCents > capCents;
  return (
    <div className="ta-budget-row">
      <span>
        {t("agentDesk.trading.budget.summary", {
          spent: formatMoney(budget.spent_usd),
          cap: formatMoney(budget.cap_usd),
          calls: budget.calls,
        })}
      </span>
      <span className="ta-budget-bar" role="progressbar" aria-valuenow={clamped} aria-valuemin={0} aria-valuemax={100}>
        <span
          className={`ta-budget-bar-fill${over ? " ta-budget-over" : ""}`}
          style={{ width: `${clamped}%` }}
        />
      </span>
    </div>
  );
}

function StageRow({
  stage,
  expanded,
  onToggle,
  t,
}: {
  stage: StageRecord;
  expanded: boolean;
  onToggle: () => void;
  t: I18n["t"];
}) {
  return (
    <div className={`ta-stage ta-stage-${stage.state}`}>
      <button
        type="button"
        className="ta-stage-head"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <span className="ta-stage-name">
          <span className="ta-stage-caret" aria-hidden="true">
            {expanded ? "▾" : "▸"}
          </span>
          {stage.label}
        </span>
        <StatusPill tone={stageTone(stage.state)} label={stageStateLabel(t, stage.state)} />
      </button>
      {expanded && (
        <div className="ta-stage-body">
          {/* `stage.summary` is model-written prose, left untranslated -- see the badge on
              `stage.output_md` just below for the same boundary. */}
          {stage.summary && <p className="muted">{stage.summary}</p>}
          {stage.error && (
            <div className="callout callout-danger ta-stage-error" role="alert">
              {stage.error}
            </div>
          )}
          {stage.output_md ? (
            <>
              <span className="badge" title={t("common.sourceEnglishTitle")}>
                {t("common.sourceEnglish")}
              </span>
              <ScrollRegion size="md" label={t("agentDesk.trading.panel.progressBoard")}>
                <pre className="ta-stage-output">{stage.output_md}</pre>
              </ScrollRegion>
            </>
          ) : (
            <div className="placeholder">{t("agentDesk.trading.stage.noOutput")}</div>
          )}
          {stage.grounding?.degraded && <GroundingPanel grounding={stage.grounding} t={t} />}
          <p className="muted">
            {t("agentDesk.trading.stage.costSoFar", { cost: formatMoney(stage.cost_usd) })}
          </p>
        </div>
      )}
    </div>
  );
}

/**
 * One past decision. `alpha_return_pct` is rendered as the headline figure, labelled "vs {benchmark}"
 * -- per this task's brief, a decision that made money in a market that made more did not work, so
 * the raw return is shown secondary rather than first. A `pending` entry has `null` for every outcome
 * field; `formatSignedReturnPct`/`formatReturnPct` render `null` as an em dash, never `"0.00%"` --
 * conflating "no outcome yet" with "broke even" is exactly the distinction this app polices elsewhere
 * (see `@/api/competition`'s `median_excess`/`worst_excess` docstring). `decision_md` is long, so it
 * sits behind the same expand/collapse pattern `StageRow` above already establishes for `output_md`.
 */
function MemoryRow({
  entry,
  expanded,
  onToggle,
  t,
}: {
  entry: MemoryEntry;
  expanded: boolean;
  onToggle: () => void;
  t: I18n["t"];
}) {
  return (
    <div className={`ta-memory-entry ta-memory-${entry.state}`}>
      <div className="ta-memory-head">
        <span className="ta-memory-symbol">{entry.symbol}</span>
        <span className="ta-memory-date">{entry.trade_date}</span>
        {entry.rating && <span className="badge ta-rating">{entry.rating}</span>}
        <span className={`badge ta-memory-state-${entry.state}`}>
          {entry.state === "pending" ? t("status.pending") : t("agentDesk.trading.memory.resolved")}
        </span>
      </div>

      <div className="ta-memory-metrics">
        <div className="ta-memory-metric ta-memory-metric-alpha">
          <span className="ta-memory-metric-label">
            {t("agentDesk.trading.memory.alphaVs", { benchmark: entry.benchmark || "SPY" })}
          </span>
          <span className={`ta-memory-metric-value ${returnTone(entry.alpha_return_pct)}`}>
            {formatSignedReturnPct(entry.alpha_return_pct)}
          </span>
        </div>
        <div className="ta-memory-metric">
          <span className="ta-memory-metric-label">{t("agentDesk.trading.memory.rawReturn")}</span>
          <span className={`ta-memory-metric-value-secondary ${returnTone(entry.raw_return_pct)}`}>
            {formatSignedReturnPct(entry.raw_return_pct)}
          </span>
        </div>
        <div className="ta-memory-metric">
          <span className="ta-memory-metric-label">{t("agentDesk.trading.memory.holding")}</span>
          <span className="ta-memory-metric-value-secondary">
            {entry.holding_days === null
              ? "—"
              : t("agentDesk.trading.memory.holdingDays", { days: entry.holding_days })}
          </span>
        </div>
      </div>

      {/* `entry.reflection` is model-written prose, left untranslated -- see the badge on
          `entry.decision_md` below for the same boundary. */}
      {entry.state === "resolved" && entry.reflection && (
        <p className="ta-memory-reflection muted">{entry.reflection}</p>
      )}

      <button
        type="button"
        className="ta-memory-toggle"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <span className="ta-stage-caret" aria-hidden="true">
          {expanded ? "▾" : "▸"}
        </span>
        {expanded
          ? t("agentDesk.trading.memory.hideDecision")
          : t("agentDesk.trading.memory.showDecision")}
      </button>
      {expanded &&
        (entry.decision_md ? (
          <>
            <span className="badge" title={t("common.sourceEnglishTitle")}>
              {t("common.sourceEnglish")}
            </span>
            <ScrollRegion size="md" label={t("agentDesk.trading.memory.title")}>
              <pre className="ta-stage-output">{entry.decision_md}</pre>
            </ScrollRegion>
          </>
        ) : (
          <div className="placeholder">{t("agentDesk.trading.memory.noDecisionText")}</div>
        ))}
    </div>
  );
}

function GroundingPanel({ grounding, t }: { grounding: GroundingVerdict; t: I18n["t"] }) {
  const detailKey: MessageKey =
    grounding.attempts === 1
      ? "agentDesk.trading.grounding.detail_one"
      : "agentDesk.trading.grounding.detail_other";
  return (
    <div className="callout callout-warn ta-stage-grounding" role="alert">
      <strong>{t("agentDesk.trading.grounding.label")}</strong>{" "}
      {t(detailKey, { attempts: grounding.attempts })}
      {/* `issue.detail` is the grounding checker's own diagnostic text, left untranslated. */}
      {grounding.issues.length > 0 && (
        <ul className="ta-stage-grounding-issues">
          {grounding.issues.map((issue, i) => (
            <li key={i}>{issue.detail}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
