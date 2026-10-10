/**
 * The endless competition/feedback loop's live panel: propose a generation, run it, score it, promote
 * the winners, cool down, repeat -- until stopped. Mirrors `NextRoundPanel`/`SummarySection`'s house
 * style: every piece of data arrives as a prop, `phase`/`message` describe the load, and nothing here
 * calls `evolutionApi` itself -- the parent (`Competition.tsx`) owns the fetch and the poll.
 *
 * **A `null` `status` on a `"loaded"` `phase` is the loop's ordinary idle state, not an error.** The
 * page maps a `GET /loop` `404` to exactly this -- see `api/evolution.ts`'s `isLoopNotStarted` -- so
 * this component renders an inviting "start it" state for `null`, never the generic error placeholder.
 *
 * **The toggle button's label is derived from `status`, not tracked separately.** Idle/stopped/no
 * status -> "Start the loop"; running -> "Stop the loop"; stopping -> "Stopping…" and disabled, so a
 * second click can never be sent while the first stop request is still in flight.
 *
 * **The start form's draft state lives in the parent, not here.** `draft`/`onDraftChange` are a
 * controlled pair, exactly like `rankBy`/`onRankByChange` elsewhere on this page -- deliberately, so
 * `Competition.tsx`'s header "Start the loop" toggle (rendered outside this component, and this
 * component unmounts whenever the reader is on a different tab) still starts the loop with whatever the
 * form currently holds rather than resetting to the form's own defaults every time the Loop tab is
 * revisited. This component's own toggle button assembles the draft into a `Partial<LoopConfig>`
 * (`buildLoopConfigFromDraft`) and hands it to `onStart` -- the parent forwards it to
 * `evolutionApi.startLoop` verbatim.
 *
 * **The form is not the thing that steers the search.** The goal field's helper text says this
 * explicitly and the code backs it up: `goal` free text is threaded straight into the config and never
 * parsed or matched against anything here. Only `focus_symbols`/`avoid_symbols` (the ticker fields) and
 * the ranking metric actually constrain what gets proposed -- see `api/evolution.ts`'s `LoopConfig`
 * docstring. Do not add any code here that reads `goal`'s contents to influence anything; that would
 * make the helper text a lie.
 *
 * **The one thing that does read `goal`, and why it is not that.** `GoalDirectiveWarnings` below runs
 * `detectGoalDirectives` (`./goalDirectives`) over the goal text and, when it finds something shaped
 * like a config directive -- `purposes=[...]`, `focus=NVDA,AMD`, "ranked by hit rate" -- says so next
 * to the field. That output goes to the *reader*, never to the loop: it does not touch `draft`, it is
 * not reachable from `buildLoopConfigFromDraft`, and it does not gate `handleToggle`. The rule above
 * is unchanged -- goal prose still influences nothing about what gets proposed. The warning exists
 * because the previous state of this form let a person type `purposes=['trading', 'roth', 'saving']`
 * into the goal box and watch two generations run the default lanes with no indication anywhere that
 * the request had been dropped, or that `saving` was never a legal purpose to begin with
 * (`data/loop/gen1873/PLAN.md`, `gen1877/PLAN.md`). **It must stay a warning, never a gate**: this
 * field's freedom to hold any sentence at all is the point of having it.
 *
 * **While the loop is running, the config it was started with is a fact, not an input.** The form is
 * replaced by `LoopRunningConfig`, reading `status.config` -- never the (possibly since-edited) draft --
 * so a reader cannot mistake "what I'm about to start" for "what is actually running".
 *
 * **The holdout median is not a second selection median.** `Standing.holdout_median_excess` is scored
 * over windows the selection step never saw -- the honesty check on whether a winner's edge
 * generalises past what it was picked on. It renders beside the selection median, in its own column,
 * labelled inline as never used for selection -- see `api/evolution.ts`'s `Standing` docstring. Folding
 * it into the same figure, or leaving off the label, states a stronger claim than the evidence
 * supports.
 *
 * **`BestStanding`/`LatestFindings` above only ever show the current run's leader and its latest
 * generation.** `GenerationsPanel`, mounted at the bottom of this component, is the whole-field,
 * whole-history complement: every generation the loop has ever run (not just this run's recent
 * history), the entire field on each one (not just the leader), and the model review/plan for any of
 * them. It reads its own data independently of `status` -- generation history persists whether or not
 * the loop happens to be running right now, so it renders unconditionally rather than nested inside
 * the `status &&` branch below.
 *
 * **Promotions/findings/the log are individually `Collapsible`, each with its own bounded
 * `ScrollRegion` inside.** This panel used to stack the toggle, the status line, the best standing,
 * every promotion, every finding from the latest generation, the log tail, `GenerationsPanel`, and
 * `JournalPanel` as one unbounded, non-collapsible block -- a long-running loop with dozens of
 * promotions or a chatty generation made the whole tab a long scroll before a reader ever reached
 * `GenerationsPanel`'s own field-wide table. `Promotions`/`LatestFindings`/`LogTail` below each render
 * inside `Collapsible` (open by default, so nothing a reader used to see is now hidden without a
 * click) with their list/grid/pre body inside `ScrollRegion` (bounded height, scrolls internally
 * instead of pushing the rest of the page down). `LoopStatusLine`/`BestStanding` stay bare -- both are
 * already a fixed, small stat grid, not a list that grows with the run.
 *
 * **The human review queue is no longer mounted here.** `PendingSeatsPanel` used to sit at the bottom
 * of this panel, under the loop form and `GenerationsPanel`, which meant the one place a person makes
 * a real decision -- seat, shelve, reject, retire a promoted card -- was buried behind loop machinery
 * a reviewer has no reason to read first. It now has its own top-level "Review" tab in
 * `Competition.tsx`'s tab rail, rendered independently of this component (see docs/STRATEGY-AGENT-UX-
 * ANALYSIS.md §A2). `PendingSeatsPanel` was already fully self-contained -- it fetches its own queue
 * data and takes no props -- so the move only changed where it is mounted, not how it works.
 */
import {
  buildLoopConfigFromDraft,
  findingKindLabel,
  loopPhaseLabel,
  loopStateLabel,
  purposeLabel,
  PURPOSE_ORDER,
  type GenerationOutcome,
  type LoopConfig,
  type LoopFormDraft,
  type LoopPhase,
  type LoopState,
  type LoopStatus,
  type PromotionRecord,
  type Purpose,
  type Standing,
} from "@/api/evolution";
import { formatIntOrDash, formatSignedPctFraction, fractionTone } from "@/api/competition";
import Collapsible from "@/components/Collapsible";
import { ScrollRegion } from "@/components/ScrollPanel";
import StatusPill, { type PillTone } from "@/components/StatusPill";
import type { FetchPhase } from "@/hooks/useFetch";
import { useT } from "@/i18n";

import GenerationsPanel from "./GenerationsPanel";
import JournalPanel from "./JournalPanel";
import { detectGoalDirectives, type GoalDirectiveWarning } from "./goalDirectives";

/** `<select>` options for the two sizing fields, per the task's own list -- `population` defaults to
 * 10 (was 6), `maxWorkers` to 4. */
const POPULATION_OPTIONS = [4, 6, 8, 10, 12, 16, 20, 24];
const MAX_WORKERS_OPTIONS = [1, 2, 4, 6, 8];

/** Tone mapping for `LoopState`, per docs/COPY-STYLE.md: running -> info (active), stopping -> warn
 * (winding down), stopped/idle -> neutral, failed -> bad. Mirrors `stageTone`/`runTone` in
 * `TradingAgents.tsx`/`VibeTrading.tsx` -- same vocabulary, this page's own union.
 *
 * Exported so `Competition.tsx`'s header can pill the same state in the same tone beside its own
 * loop toggle. That toggle is visible on every tab, while this panel unmounts the moment the reader
 * leaves the Loop tab -- two mappings for one union is how the header ends up calling a failed loop
 * "idle" while the panel calls it "failed". */
export function loopStateTone(state: LoopState): PillTone {
  switch (state) {
    case "running":
      return "info";
    case "stopping":
      return "warn";
    case "idle":
    case "stopped":
      return "neutral";
    case "failed":
      return "bad";
    default: {
      const _exhaustive: never = state;
      void _exhaustive;
      return "neutral";
    }
  }
}

/** Tone mapping for `LoopPhase`: every actively-working phase (proposing/running/scoring/promoting)
 * reads as `info`, `cooldown` as `warn` (winding down between generations), and the idle phase as
 * `neutral` -- mirrors `loopStateTone` above. */
function loopPhaseTone(phase: LoopPhase): PillTone {
  switch (phase) {
    case "idle":
      return "neutral";
    case "proposing":
    case "running":
    case "scoring":
    case "promoting":
      return "info";
    case "cooldown":
      return "warn";
    default: {
      const _exhaustive: never = phase;
      void _exhaustive;
      return "neutral";
    }
  }
}

export interface LoopPanelProps {
  status: LoopStatus | null;
  phase: FetchPhase;
  message: string | null;
  /** True while a start/stop request is in flight -- disables the toggle so a second click cannot be
   * sent on top of the first. */
  busy: boolean;
  /** Called with the draft assembled into a `Partial<LoopConfig>` when the toggle starts the loop --
   * see this module's docstring on why the draft itself is a controlled prop rather than local state. */
  onStart: (config: Partial<LoopConfig>) => void;
  onStop: () => void;
  /** The start form's current values. Controlled by the parent so it survives this component
   * unmounting when the reader leaves the Loop tab. */
  draft: LoopFormDraft;
  onDraftChange: (patch: Partial<LoopFormDraft>) => void;
}

export default function LoopPanel({
  status,
  phase,
  message,
  busy,
  onStart,
  onStop,
  draft,
  onDraftChange,
}: LoopPanelProps) {
  const { t } = useT();
  if (phase === "loading") {
    return (
      <div className="panel comp-loop-panel">
        <div className="placeholder">{t("competition.loop.loadingPanel")}</div>
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div className="panel comp-loop-panel">
        <div className="placeholder">{message ?? t("competition.errors.loop")}</div>
      </div>
    );
  }

  const state = status?.state ?? "idle";
  const running = state === "running" || state === "stopping";
  const stopping = state === "stopping";
  const toggleLabel = stopping
    ? t("competition.loop.stopping")
    : running
      ? t("competition.loop.stop")
      : t("competition.loop.start");
  const toggleClass = running ? "comp-loop-stop" : "comp-run-cta";

  const handleToggle = () => {
    if (running) {
      onStop();
      return;
    }
    onStart(buildLoopConfigFromDraft(draft));
  };

  return (
    <div className="panel comp-loop-panel">
      <div className="comp-loop-head">
        <h2 className="section-heading comp-loop-heading">{t("competition.loop.heading")}</h2>
        <button
          type="button"
          className={toggleClass}
          onClick={handleToggle}
          disabled={busy || stopping}
          aria-describedby="comp-loop-panel-toggle-hint"
        >
          {toggleLabel}
        </button>
      </div>
      <p id="comp-loop-panel-toggle-hint" className="visually-hidden">
        {t("competition.loop.toggleHint")}
      </p>

      {message && <div className="callout callout-danger comp-loop-error">{message}</div>}

      {running && status ? (
        <LoopRunningConfig config={status.config} />
      ) : (
        <LoopStartForm draft={draft} onDraftChange={onDraftChange} />
      )}

      {!status ? (
        <div className="placeholder comp-loop-empty">{t("competition.loop.neverStarted")}</div>
      ) : (
        <>
          <LoopStatusLine status={status} />
          <BestStanding best={status.best} />
          <Promotions promotions={status.promotions} />
          <LatestFindings history={status.history} goal={status.config.goal} />
          <LogTail log={status.log} />
          {status.error && <div className="callout callout-danger comp-loop-error">{status.error}</div>}
        </>
      )}

      <GenerationsPanel />
      <JournalPanel />
    </div>
  );
}

/**
 * The compact start form, shown whenever the loop is not running. Every field is controlled by the
 * parent (`draft`/`onDraftChange`) -- see this module's docstring on why the draft is not local state.
 */
function LoopStartForm({
  draft,
  onDraftChange,
}: {
  draft: LoopFormDraft;
  onDraftChange: (patch: Partial<LoopFormDraft>) => void;
}) {
  const { t } = useT();
  // Recomputed on every keystroke rather than on submit: the whole point is that the reader finds out
  // while they are still looking at the sentence they typed. Cheap -- a handful of regexes over a few
  // hundred characters -- so it is not memoised, matching the rest of this file's plain-render style.
  const goalWarnings = detectGoalDirectives(draft.goal, draft);
  return (
    <div className="comp-loop-form-wrap">
      <h3 className="comp-loop-subheading">{t("competition.loop.form.setupHeading")}</h3>
      <PurposesControl
        selected={draft.purposes}
        onChange={(purposes) => onDraftChange({ purposes })}
      />
      <div className="comp-loop-form-row filter-bar">
        <label className="bt-control-label" htmlFor="comp-loop-population">
          {t("competition.loop.form.populationLabel")}
          <select
            id="comp-loop-population"
            className="bt-entry-select"
            value={draft.population}
            onChange={(e) => onDraftChange({ population: Number(e.target.value) })}
          >
            {POPULATION_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label className="bt-control-label" htmlFor="comp-loop-max-workers">
          {t("competition.loop.form.maxWorkersLabel")}
          <select
            id="comp-loop-max-workers"
            className="bt-entry-select"
            value={draft.maxWorkers}
            onChange={(e) => onDraftChange({ maxWorkers: Number(e.target.value) })}
          >
            {MAX_WORKERS_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="comp-loop-form-hint">{t("competition.loop.form.sizingHint")}</p>

      <label className="bt-control-label comp-loop-goal-label" htmlFor="comp-loop-goal">
        {t("competition.loop.form.goalLabel")}
        <textarea
          id="comp-loop-goal"
          className="bt-scan-input comp-loop-goal-input"
          rows={3}
          placeholder={t("competition.loop.form.goalPlaceholder")}
          value={draft.goal}
          onChange={(e) => onDraftChange({ goal: e.target.value })}
          aria-describedby={
            goalWarnings.length > 0 ? "comp-loop-goal-hint comp-loop-goal-warnings" : "comp-loop-goal-hint"
          }
        />
      </label>
      <GoalDirectiveWarnings warnings={goalWarnings} />
      <p id="comp-loop-goal-hint" className="comp-loop-form-hint">
        {t("competition.loop.form.goalHint")}
      </p>

      <div className="comp-loop-form-row filter-bar">
        <label className="bt-control-label" htmlFor="comp-loop-focus-symbols">
          {t("competition.loop.form.focusLabel")}
          <input
            id="comp-loop-focus-symbols"
            className="symbol-input comp-loop-symbols-input"
            type="text"
            value={draft.focusSymbolsInput}
            onChange={(e) => onDraftChange({ focusSymbolsInput: e.target.value })}
            placeholder={t("competition.loop.form.focusPlaceholder")}
          />
        </label>
        <label className="bt-control-label" htmlFor="comp-loop-avoid-symbols">
          {t("competition.loop.form.avoidLabel")}
          <input
            id="comp-loop-avoid-symbols"
            className="symbol-input comp-loop-symbols-input"
            type="text"
            value={draft.avoidSymbolsInput}
            onChange={(e) => onDraftChange({ avoidSymbolsInput: e.target.value })}
            placeholder={t("competition.loop.form.avoidPlaceholder")}
          />
        </label>
      </div>
      <p className="comp-loop-form-hint">{t("competition.loop.form.tickersHint")}</p>
    </div>
  );
}

/**
 * Which books this run breeds for -- the field whose absence the goal box was being used to work
 * around.
 *
 * **Why this exists at all.** `buildLoopConfigFromDraft` did not carry `purposes`, so every run ever
 * started from this page took `LoopConfig`'s own default (trading and Roth) regardless of what the
 * person wanted, and `savings` was unreachable from the UI entirely -- which is what
 * `docs/research/loop/01-what-the-search-found.md` point 6 measured as zero savings coverage across
 * 231 generations, and what `data/loop/gen1873/PLAN.md`'s `purposes=['trading', 'roth', 'saving']`
 * typed into the *goal* field was trying to ask for.
 *
 * **The last box cannot be unticked.** `LoopConfig.purposes` is `min_length=1` on the backend for a
 * concrete reason -- an empty tuple builds zero lanes and the supervisor dies on a modulo by zero --
 * and a disabled checkbox says so before the request is made. Disabled rather than
 * unticked-then-rejected: the alternative is a 422 for something the form could see coming, and this
 * panel's house rule is that the reader finds out while they are still looking at the control.
 */
function PurposesControl({
  selected,
  onChange,
}: {
  selected: Purpose[];
  onChange: (purposes: Purpose[]) => void;
}) {
  const { t } = useT();
  const isLast = (p: Purpose) => selected.length === 1 && selected[0] === p;
  return (
    <fieldset className="comp-loop-purposes">
      <legend className="bt-control-label comp-loop-purposes-legend">
        {t("competition.loop.form.booksToBreedLegend")}
      </legend>
      <div className="comp-loop-purposes-boxes">
        {PURPOSE_ORDER.map((purpose) => {
          const checked = selected.includes(purpose);
          return (
            <label key={purpose} className="comp-loop-purpose-box" htmlFor={`comp-loop-purpose-${purpose}`}>
              <input
                id={`comp-loop-purpose-${purpose}`}
                type="checkbox"
                checked={checked}
                disabled={isLast(purpose)}
                onChange={() => {
                  // Guarded here as well as by `disabled`: a synthetic click still reaches this
                  // handler under jsdom, and "the last book cannot be unticked" is an invariant of
                  // the control, not a property of how the browser routes events to a disabled input.
                  if (isLast(purpose)) return;
                  onChange(
                    checked
                      ? selected.filter((p) => p !== purpose)
                      : PURPOSE_ORDER.filter((p) => p === purpose || selected.includes(p)),
                  );
                }}
              />
              <span>{purposeLabel(purpose)}</span>
            </label>
          );
        })}
      </div>
      <p className="comp-loop-form-hint">{t("competition.loop.form.booksHint")}</p>
    </fieldset>
  );
}

/**
 * The pre-flight notice for goal text that is shaped like a config directive but is not one.
 *
 * **A warning, not a gate.** Nothing here disables the toggle or changes the draft -- see this
 * module's docstring. It renders nothing at all for the ordinary case (a goal that reads like a
 * question), so a reader who is using the field as intended never sees it.
 *
 * `.callout-warn` rather than `.callout-danger`: the run this describes is about to do something
 * perfectly valid, just not the thing the sentence asks for. `role="status"` (polite, not
 * `"alert"`) for the same reason -- it appears mid-typing, and an assertive live region would
 * interrupt a screen-reader user in the middle of writing the sentence it is about.
 */
function GoalDirectiveWarnings({ warnings }: { warnings: GoalDirectiveWarning[] }) {
  const { t } = useT();
  if (warnings.length === 0) return null;
  return (
    <div
      id="comp-loop-goal-warnings"
      className="callout callout-warn comp-loop-goal-warnings"
      role="status"
    >
      <span className="comp-loop-goal-warnings-label">
        {t(
          warnings.length === 1
            ? "competition.loop.goalWarnings.label_one"
            : "competition.loop.goalWarnings.label_other",
          { count: warnings.length },
        )}
      </span>
      <ul className="comp-loop-goal-warnings-list">
        {warnings.map((w) => (
          <li key={`${w.field}-${w.values.join(",")}`} className="comp-loop-goal-warning">
            <code className="comp-loop-goal-warning-quote">{w.quoted}</code>{" "}
            <span className="comp-loop-goal-warning-message">{w.message}</span>
            {w.legalityMessage && (
              <span className="comp-loop-goal-warning-legality"> {w.legalityMessage}</span>
            )}
          </li>
        ))}
      </ul>
      <p className="comp-loop-goal-warnings-foot">{t("competition.loop.goalWarnings.footer")}</p>
    </div>
  );
}

/** The config a running (or stopping) loop was actually started with -- read from `status.config`,
 * never the draft, which may since have been edited by a reader who has no way to change what is
 * already running. A fact, not an input; see this module's docstring. */
function LoopRunningConfig({ config }: { config: LoopConfig }) {
  const { t } = useT();
  return (
    <div className="comp-loop-running-config">
      <h3 className="comp-loop-subheading">{t("competition.loop.runningConfigHeading")}</h3>
      <div className="status-grid comp-loop-stats">
        <div className="stat">
          <span className="label">{t("competition.loop.form.populationLabel")}</span>
          <span className="value">{config.population}</span>
        </div>
        <div className="stat">
          <span className="label">{t("competition.loop.form.maxWorkersLabel")}</span>
          <span className="value">{config.max_workers}</span>
        </div>
        <div className="stat">
          <span className="label">{t("competition.loop.config.mustInclude")}</span>
          <span className="value">
            {config.focus_symbols.length > 0 ? config.focus_symbols.join(", ") : "—"}
          </span>
        </div>
        <div className="stat">
          <span className="label">{t("competition.loop.config.mustAvoid")}</span>
          <span className="value">
            {config.avoid_symbols.length > 0 ? config.avoid_symbols.join(", ") : "—"}
          </span>
        </div>
      </div>
    </div>
  );
}

function LoopStatusLine({ status }: { status: LoopStatus }) {
  const { t } = useT();
  return (
    <div className="comp-loop-status">
      <div>
        <StatusPill tone={loopStateTone(status.state)} label={loopStateLabel(status.state)} />
        <StatusPill
          tone={loopPhaseTone(status.phase)}
          label={loopPhaseLabel(status.phase)}
          className="comp-loop-phase"
        />
      </div>
      <div className="status-grid comp-loop-stats">
        <div className="stat">
          <span className="label">{t("competition.loop.status.generation")}</span>
          <span className="value">{status.generation}</span>
        </div>
        <div className="stat">
          <span className="label">{t("competition.loop.status.completedGenerations")}</span>
          <span className="value">{status.completed_generations}</span>
        </div>
        <div className="stat">
          <span className="label">{t("competition.loop.status.candidatesTested")}</span>
          <span className="value">{formatIntOrDash(status.candidates_tested)}</span>
        </div>
        <div className="stat">
          <span className="label">{t("competition.loop.status.currentPurpose")}</span>
          <span className="value">
            {status.current_purpose ? purposeLabel(status.current_purpose) : "—"}
          </span>
        </div>
        <div className="stat">
          <span className="label">{t("competition.loop.status.currentRound")}</span>
          <span className="value">{status.current_round_id ?? "—"}</span>
        </div>
      </div>
    </div>
  );
}

function BestStanding({ best }: { best: Standing | null }) {
  const { t } = useT();
  return (
    <div className="comp-loop-best">
      <h3 className="comp-loop-subheading">{t("competition.loop.best.heading")}</h3>
      {!best ? (
        <div className="placeholder">{t("competition.loop.best.empty")}</div>
      ) : (
        <div className="comp-loop-best-body">
          <div className="comp-loop-best-name">
            <span className="comp-card-name">{best.display_name}</span>
            <span className="tile-hint">
              {t("competition.loop.best.idAndRank", { agentId: best.agent_id, rank: best.rank })}
            </span>
            {!best.eligible && <span className="badge comp-ineligible-chip">{t("competition.ineligibleBadge")}</span>}
          </div>
          <div className="status-grid comp-loop-best-stats">
            <div className="stat">
              <span className="label">{t("competition.loop.best.selectionMedian")}</span>
              <span className={`value comp-num ${fractionTone(best.median_excess)}`}>
                {formatSignedPctFraction(best.median_excess)}
              </span>
            </div>
            <div className="stat comp-loop-holdout-stat">
              <span className="label">
                {t("competition.loop.best.holdoutMedian")}
                <span className="comp-loop-holdout-note">{t("competition.loop.holdoutNeverUsedNote")}</span>
              </span>
              <span className={`value comp-num ${fractionTone(best.holdout_median_excess)}`}>
                {formatSignedPctFraction(best.holdout_median_excess)}
              </span>
            </div>
            <div className="stat">
              <span className="label">{t("competition.loop.best.worstExcess")}</span>
              <span className={`value comp-num ${fractionTone(best.worst_excess)}`}>
                {formatSignedPctFraction(best.worst_excess)}
              </span>
            </div>
            <div className="stat">
              <span className="label">{t("competition.loop.best.hitRate")}</span>
              <span className="value">
                {best.hit_rate !== null ? `${(best.hit_rate * 100).toFixed(1)}%` : "—"}
              </span>
            </div>
            <div className="stat">
              <span className="label">{t("competition.loop.best.windowsRun")}</span>
              <span className="value">{best.windows_run}</span>
            </div>
            <div className="stat">
              <span className="label">{t("competition.loop.best.totalTrades")}</span>
              <span className="value">{formatIntOrDash(best.total_trades)}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Promotions({ promotions }: { promotions: PromotionRecord[] }) {
  const { t } = useT();
  const heading = t("competition.loop.promotions.heading");
  return (
    <Collapsible
      title={<h3 className="comp-loop-subheading">{heading}</h3>}
      className="comp-loop-promotions"
    >
      {promotions.length === 0 ? (
        <div className="placeholder">{t("competition.loop.promotions.empty")}</div>
      ) : (
        // Bounded rather than left to grow with every promotion a long-running loop has ever recorded --
        // see `LoopPanel.tsx`'s module docstring on why this whole block used to stack unbounded.
        <ScrollRegion size="md" label={heading}>
          <div className="tile-grid comp-loop-promotion-grid">
            {promotions.map((p) => (
              <div key={p.genome_id} className="tile comp-loop-promotion-tile">
                <div className="comp-card-head">
                  <span className="comp-card-name">{p.agent_id}</span>
                  <span className="badge">{purposeLabel(p.purpose)}</span>
                </div>
                <div className="tile-hint">
                  {t("competition.loop.promotions.idAndDate", { genomeId: p.genome_id, date: p.promoted_at })}
                </div>
                <StatusPill
                  tone={p.seated ? "ok" : "neutral"}
                  label={
                    p.seated
                      ? t("competition.loop.promotions.seated")
                      : t("competition.loop.promotions.notSeated")
                  }
                />
                <p className="comp-loop-promotion-reason">{p.reason}</p>
                <div className="comp-loop-promotion-stats">
                  <span className="comp-num">
                    {t("competition.loop.promotions.median", { value: formatSignedPctFraction(p.median_excess) })}
                  </span>
                  <span className="comp-num">
                    {t("competition.loop.promotions.holdout", {
                      value: formatSignedPctFraction(p.holdout_median_excess),
                    })}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </ScrollRegion>
      )}
    </Collapsible>
  );
}

/** The generation with the highest `generation` number in `history` -- not `history[0]`/`history.at(-1)`,
 * since neither this component nor `LoopStatus`'s own docstring commits to the array's order. */
function latestGeneration(history: GenerationOutcome[]): GenerationOutcome | null {
  const [first, ...rest] = history;
  if (!first) return null;
  return rest.reduce((latest, g) => (g.generation > latest.generation ? g : latest), first);
}

/** `goal` is the run's own stated intent (`status.config.goal`), rendered here -- beside the findings
 * for the generation it was declared for -- explicitly labelled as the intent, never as a finding or a
 * conclusion. It is prose a person wrote before the run started, not something the loop measured. */
function LatestFindings({ history, goal }: { history: GenerationOutcome[]; goal: string }) {
  const { t } = useT();
  const generation = latestGeneration(history);
  const findings = generation?.findings ?? [];
  const heading = generation
    ? t("competition.loop.findings.headingWithGeneration", { generation: generation.generation })
    : t("competition.loop.findings.heading");
  return (
    <Collapsible title={<h3 className="comp-loop-subheading">{heading}</h3>} className="comp-loop-findings">
      {goal && (
        <div className="comp-loop-goal-display">
          <span className="comp-loop-goal-display-label">
            {t("competition.loop.findings.statedGoalLabel")}{" "}
            <span className="comp-loop-goal-display-note">{t("competition.loop.findings.statedGoalNote")}</span>
          </span>
          <p className="comp-loop-goal-text">{goal}</p>
        </div>
      )}
      {findings.length === 0 ? (
        <div className="placeholder">{t("competition.loop.findings.empty")}</div>
      ) : (
        // Bounded rather than left to grow with every finding one generation recorded -- see
        // `LoopPanel.tsx`'s module docstring on why this whole block used to stack unbounded.
        <ScrollRegion size="sm" label={heading}>
          <ul className="comp-loop-findings-list">
            {findings.map((f, i) => (
              <li key={i} className="comp-loop-finding-item">
                <span className="badge comp-loop-finding-badge">{findingKindLabel(f.kind)}</span>
                <span className="comp-loop-finding-summary">{f.summary}</span>
              </li>
            ))}
          </ul>
        </ScrollRegion>
      )}
    </Collapsible>
  );
}

function LogTail({ log }: { log: string[] }) {
  const { t } = useT();
  const heading = t("competition.loop.log.heading");
  return (
    <Collapsible title={<h3 className="comp-loop-subheading">{heading}</h3>} className="comp-loop-log-wrap">
      {log.length === 0 ? (
        <div className="placeholder">{t("competition.loop.log.empty")}</div>
      ) : (
        <ScrollRegion size="sm" label={heading}>
          <pre className="comp-job-log comp-loop-log">{log.slice(-8).join("\n")}</pre>
        </ScrollRegion>
      )}
    </Collapsible>
  );
}
