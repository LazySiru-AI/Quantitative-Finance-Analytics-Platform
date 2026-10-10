// ---------------------------------------------------------------------------
// 3. Library + run
// ---------------------------------------------------------------------------
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import {
  formatIntOrDash,
  formatPctFraction,
  formatSignedPctFraction,
  fractionTone,
  horizonLabel,
  HORIZON_ORDER,
  isTerminalJobStatus,
  jobRunResultStatusLabel,
  jobStatusLabel,
  provenanceConstrainedNote,
  type CardSummary,
  type CreateJobRequest,
  type Horizon,
  type JobStatus,
  type LibraryResponse,
  type LibraryTier,
  type WindowCatalogueEntry,
} from "@/api/competition";
import { ScrollRegion } from "@/components/ScrollPanel";
import { Trans, useT } from "@/i18n";
import { numCell } from "@/pages/competition/cells";

type Phase = "loading" | "loaded" | "error";

export interface LibrarySectionProps {
  library: LibraryResponse | null;
  libraryPhase: Phase;
  libraryMessage: string | null;
  windowCatalogue: WindowCatalogueEntry[];
  windowsPhase: Phase;
  windowsMessage: string | null;
  job: JobStatus | null;
  jobError: string | null;
  creatingJob: boolean;
  onCreateJob: (request: CreateJobRequest) => void;
  onCancelJob: () => void;
}

export default function LibrarySection({
  library,
  libraryPhase,
  libraryMessage,
  windowCatalogue,
  windowsPhase,
  windowsMessage,
  job,
  jobError,
  creatingJob,
  onCreateJob,
  onCancelJob,
}: LibrarySectionProps) {
  const { t } = useT();
  const allCards = useMemo(() => (library ? library.tiers.flatMap((tier) => tier.cards) : []), [library]);

  return (
    <>
      {libraryPhase === "loading" && (
        <div className="panel">
          <div className="placeholder">{t("competitionRounds.library.loading")}</div>
        </div>
      )}
      {libraryPhase === "error" && (
        <div className="panel">
          <div className="placeholder">{libraryMessage ?? t("competitionRounds.library.loadError")}</div>
        </div>
      )}
      {libraryPhase === "loaded" && library && (
        <>
          {library.tiers.map((tier) => (
            <LibraryTierPanel key={tier.tier} tier={tier} />
          ))}

          <RunPanel
            cards={allCards}
            tiers={library.tiers}
            windows={windowCatalogue}
            windowsPhase={windowsPhase}
            windowsMessage={windowsMessage}
            job={job}
            jobError={jobError}
            creatingJob={creatingJob}
            onCreateJob={onCreateJob}
            onCancelJob={onCancelJob}
          />
        </>
      )}
    </>
  );
}

/**
 * One tier's cards as a table -- one ROW per card -- rather than a stack of full-prose tiles. The
 * library used to render every tier as `CardTile` prose cards (name, universe sentence, entry/exit
 * sentences, a sizing row, a thesis paragraph) one under another; with four tiers of cards that ran
 * several screens before a reader reached the run form below it. Universe/entry/exit/params are the
 * columns a reader scans across the whole library; the thesis (and anything else) sits behind each
 * row's own `<details>`, collapsed by default, so opening one card's reasoning never pushes every
 * other row down the page.
 */
function LibraryTierPanel({ tier }: { tier: LibraryTier }) {
  const { t } = useT();
  return (
    <div className="panel">
      <h2 className="section-heading">{tier.label}</h2>
      {tier.cards.length === 0 ? (
        <div className="placeholder">{t("competitionRounds.library.noCardsInTier")}</div>
      ) : (
        <ScrollRegion size="md" label={t("competitionRounds.library.cardsLegend")}>
          <div className="table-wrap">
            <table className="data-table comp-card-table">
              <thead>
                <tr>
                  <th>{t("competitionRounds.table.agent")}</th>
                  <th>{t("competitionRounds.library.universeHeader")}</th>
                  <th>{t("competitionRounds.label.entry")}</th>
                  <th>{t("competitionRounds.label.exit")}</th>
                  <th>{t("competitionRounds.library.paramsHeader")}</th>
                  <th>{t("competitionRounds.library.detail")}</th>
                </tr>
              </thead>
              <tbody>
                {tier.cards.map((card) => (
                  <CardRow key={card.agent_id} card={card} />
                ))}
              </tbody>
            </table>
          </div>
        </ScrollRegion>
      )}
    </div>
  );
}

function CardRow({ card }: { card: CardSummary }) {
  const { t } = useT();
  return (
    <tr className="comp-card-row">
      <td>
        <div className="comp-card-name">{card.display_name}</div>
        <div className="comp-card-agent-id">{card.agent_id}</div>
      </td>
      <td className="comp-card-universe-cell">{card.universe.join(", ") || "—"}</td>
      <td className="comp-card-rule-cell">{card.entry}</td>
      <td className="comp-card-rule-cell">{card.exit}</td>
      <td>
        <div className="comp-card-sizing">
          <span>{t("competitionRounds.library.stopLoss", { value: formatPctFraction(card.stop_loss_pct) })}</span>
          <span>{t("competitionRounds.library.takeProfit", { value: formatPctFraction(card.take_profit_pct) })}</span>
          <span>{t("competitionRounds.library.maxHold", { days: formatIntOrDash(card.max_hold_days) })}</span>
          <span>{t("competitionRounds.library.maxPositions", { count: card.max_positions })}</span>
          <span>{t("competitionRounds.library.positionSize", { value: formatPctFraction(card.position_pct) })}</span>
        </div>
      </td>
      <td>
        {/* Native <details>/<summary> -- collapsed by default, no JS state needed, and jsdom keeps
            the children in the DOM either way so text-based queries against the thesis still work. */}
        <details className="comp-card-detail">
          <summary>{t("competitionRounds.library.detail")}</summary>
          <div className="comp-card-detail-body">
            <span className="badge">{card.discipline}</span>
            <div className="tile-hint">
              {t("competitionRounds.library.designedThrough", {
                agentId: card.agent_id,
                designedThrough: card.designed_through,
              })}
            </div>
            <p className="comp-card-thesis">{card.thesis}</p>
          </div>
        </details>
      </td>
    </tr>
  );
}

/**
 * Splits the window catalogue into the run form's own presentation groups. Every pre-round-5 window
 * (`horizon: null` -- a named regime window has a length but not a *designed* horizon) renders
 * exactly as it always has: one flat, ungrouped grid, so rounds 1-4 stay selectable the way they read
 * today. Round 5's 27 horizon-ladder/bear-supplement windows are bucketed by `horizon` instead, so the
 * form can render one heading per rung ("6 months (9 windows)", …) rather than 27 undifferentiated
 * checkboxes -- unreadable as a flat list, per the round's own brief. `Map` preserves each bucket's
 * within-group order exactly as the backend returned it (main first, then chronological) rather than
 * re-sorting a second time.
 */
function groupWindowsByHorizon(windows: WindowCatalogueEntry[]): {
  legacy: WindowCatalogueEntry[];
  byHorizon: Map<Horizon, WindowCatalogueEntry[]>;
} {
  const legacy: WindowCatalogueEntry[] = [];
  const byHorizon = new Map<Horizon, WindowCatalogueEntry[]>();
  for (const w of windows) {
    if (w.horizon === null) {
      legacy.push(w);
      continue;
    }
    const bucket = byHorizon.get(w.horizon);
    if (bucket) bucket.push(w);
    else byHorizon.set(w.horizon, [w]);
  }
  return { legacy, byHorizon };
}

function WindowCheckboxGroups({
  windows,
  selectedWindows,
  onToggle,
}: {
  windows: WindowCatalogueEntry[];
  selectedWindows: Set<string>;
  onToggle: (window: string) => void;
}) {
  const { t } = useT();
  const { legacy, byHorizon } = useMemo(() => groupWindowsByHorizon(windows), [windows]);

  // ONE bounded region for the whole selector -- legacy windows plus every horizon group -- rather
  // than one scroll box per group. Round 5's 27-window ladder alone used to stack five separate
  // scrolling grids (one per horizon rung) down the page; grouped-but-unbounded is still unbounded
  // once there are enough groups. The grouping/headings stay exactly as before, just inside one box.
  return (
    <ScrollRegion size="md" label={t("competitionRounds.library.windowsLegend")}>
      {legacy.length > 0 && (
        <div className="comp-checkbox-grid">
          {legacy.map((w) => (
            <WindowCheckboxItem
              key={w.window}
              w={w}
              checked={selectedWindows.has(w.window)}
              onToggle={() => onToggle(w.window)}
            />
          ))}
        </div>
      )}

      {/* 6m -> 10y, not the order the backend happens to return windows in -- the task's own
          "readable ladder" requirement is exactly this fixed, shortest-to-longest ordering. */}
      {HORIZON_ORDER.filter((h) => byHorizon.has(h)).map((h) => {
        const list = byHorizon.get(h) as WindowCatalogueEntry[];
        return (
          <div key={h} className="comp-horizon-group">
            <h4 className="comp-horizon-heading">
              {horizonLabel(h)}{" "}
              <span className="comp-horizon-count">
                {t(
                  list.length === 1
                    ? "competitionRounds.library.windowCount_one"
                    : "competitionRounds.library.windowCount_other",
                  { count: list.length },
                )}
              </span>
            </h4>
            <div className="comp-checkbox-grid">
              {list.map((w) => (
                <WindowCheckboxItem
                  key={w.window}
                  w={w}
                  checked={selectedWindows.has(w.window)}
                  onToggle={() => onToggle(w.window)}
                />
              ))}
            </div>
          </div>
        );
      })}
    </ScrollRegion>
  );
}

function WindowCheckboxItem({
  w,
  checked,
  onToggle,
}: {
  w: WindowCatalogueEntry;
  checked: boolean;
  onToggle: () => void;
}) {
  const { t } = useT();
  return (
    <label className={`comp-checkbox-item${w.main ? "" : " comp-checkbox-item-secondary"}`}>
      <input type="checkbox" checked={checked} onChange={onToggle} />
      {/* JSX drops an indentation-only newline between elements entirely rather than collapsing it
          to a space, so without the explicit `{" "}` separators below the label's accessible
          name/textContent would run every part together with no whitespace at all
          ("gfc2007-10-01...") -- a real defect for anyone reading the computed name via a screen
          reader or `getByLabelText`, even though the `.comp-window-label` flex column keeps each
          part visually on its own line regardless. */}
      <span className="comp-window-label">
        <span className="comp-window-key">{w.window}</span>{" "}
        <span className="comp-window-dates">
          {w.start} – {w.end}
        </span>{" "}
        <span className="comp-window-desc">{w.label}</span>
        {/* The ladder was sampled by calendar, without regard to direction; the bear supplement was
            hand-picked for a *falling* benchmark. Mixing the two silently is exactly the selection
            effect this round exists to measure, so the arm gets its own visible badge rather than
            being folded into the same undifferentiated checkbox as its ladder siblings. */}
        {w.matrix === "r5-bear" && (
          <>
            {" "}
            <span
              className="badge comp-bear-chip"
              title={t("competitionRounds.library.bearBadgeTitle")}
            >
              {t("competitionRounds.library.bearBadge")}
            </span>
          </>
        )}
        {!w.main && (
          <>
            {" "}
            <span className="badge comp-provenance-chip" title={provenanceConstrainedNote()}>
              {t("competitionRounds.library.notRegimeWindow")}
            </span>
          </>
        )}
      </span>
    </label>
  );
}

function RunPanel({
  cards,
  tiers,
  windows,
  windowsPhase,
  windowsMessage,
  job,
  jobError,
  creatingJob,
  onCreateJob,
  onCancelJob,
}: {
  cards: CardSummary[];
  tiers: LibraryTier[];
  windows: WindowCatalogueEntry[];
  windowsPhase: Phase;
  windowsMessage: string | null;
  job: JobStatus | null;
  jobError: string | null;
  creatingJob: boolean;
  onCreateJob: (request: CreateJobRequest) => void;
  onCancelJob: () => void;
}) {
  const { t } = useT();
  const [roundId, setRoundId] = useState("");
  const [tier, setTier] = useState("");
  const [selectedCards, setSelectedCards] = useState<Set<string>>(new Set());
  const [selectedWindows, setSelectedWindows] = useState<Set<string>>(new Set());
  const hasSeededWindows = useRef(false);
  const hasNonMainWindow = windows.some((w) => !w.main);

  // The catalogue arrives asynchronously (it is fetched once, independently of the library), so the
  // "main windows checked by default" seed runs the first time it has anything to seed from, not on
  // mount -- a `useState` initializer would run before the fetch resolves and default to nothing.
  useEffect(() => {
    if (hasSeededWindows.current || windows.length === 0) return;
    hasSeededWindows.current = true;
    setSelectedWindows(new Set(windows.filter((w) => w.main).map((w) => w.window)));
  }, [windows]);

  const toggleCard = (agentId: string) => {
    setSelectedCards((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) next.delete(agentId);
      else next.add(agentId);
      return next;
    });
  };
  const toggleWindow = (window: string) => {
    setSelectedWindows((prev) => {
      const next = new Set(prev);
      if (next.has(window)) next.delete(window);
      else next.add(window);
      return next;
    });
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmedRoundId = roundId.trim();
    if (!trimmedRoundId || selectedCards.size === 0 || selectedWindows.size === 0) return;
    onCreateJob({
      round_id: trimmedRoundId,
      cards: Array.from(selectedCards),
      windows: Array.from(selectedWindows),
      ...(tier ? { tier } : {}),
    });
  };

  const running = job !== null && !isTerminalJobStatus(job.status);

  return (
    <div className="panel">
      <h2 className="section-heading">{t("competitionRounds.library.runHeading")}</h2>
      <form className="comp-run-form" onSubmit={handleSubmit}>
        <label className="bt-control-label" htmlFor="comp-round-id">
          {t("competitionRounds.library.roundIdLabel")}
          <input
            id="comp-round-id"
            className="symbol-input"
            value={roundId}
            onChange={(e) => setRoundId(e.target.value)}
            placeholder="r3-2026-08"
          />
        </label>

        {tiers.length > 0 && (
          <label className="bt-control-label" htmlFor="comp-tier-select">
            {t("competitionRounds.library.tierLabel")}
            <select
              id="comp-tier-select"
              className="bt-entry-select"
              value={tier}
              onChange={(e) => setTier(e.target.value)}
            >
              <option value="">{t("competitionRounds.library.anyTier")}</option>
              {tiers.map((tierOption) => (
                <option key={tierOption.tier} value={tierOption.tier}>
                  {tierOption.label}
                </option>
              ))}
            </select>
          </label>
        )}

        <fieldset className="comp-checkbox-fieldset">
          <legend className="bt-control-label">{t("competitionRounds.library.cardsLegend")}</legend>
          {cards.length === 0 ? (
            <div className="placeholder">{t("competitionRounds.library.noCardsInLibrary")}</div>
          ) : (
            <ScrollRegion size="md" label={t("competitionRounds.library.cardsLegend")}>
              <div className="comp-checkbox-grid">
                {cards.map((c) => (
                  <label key={c.agent_id} className="comp-checkbox-item">
                    <input
                      type="checkbox"
                      checked={selectedCards.has(c.agent_id)}
                      onChange={() => toggleCard(c.agent_id)}
                    />
                    {c.display_name}
                  </label>
                ))}
              </div>
            </ScrollRegion>
          )}
        </fieldset>

        <fieldset className="comp-checkbox-fieldset">
          <legend className="bt-control-label">{t("competitionRounds.library.windowsLegend")}</legend>
          {windowsPhase === "loading" && (
            <div className="placeholder">{t("competitionRounds.library.loadingWindows")}</div>
          )}
          {windowsPhase === "error" && (
            <div className="placeholder">
              {windowsMessage ?? t("competitionRounds.library.windowsLoadError")}
            </div>
          )}
          {windowsPhase === "loaded" && windows.length === 0 && (
            <div className="placeholder">{t("competitionRounds.library.noWindowsDefined")}</div>
          )}
          {windowsPhase === "loaded" && windows.length > 0 && (
            <WindowCheckboxGroups
              windows={windows}
              selectedWindows={selectedWindows}
              onToggle={toggleWindow}
            />
          )}
          {windowsPhase === "loaded" && hasNonMainWindow && (
            <p className="comp-window-note">
              <Trans
                k="competitionRounds.library.provenanceNote"
                values={{ term: <strong>13f-legal</strong> }}
              />{" "}
              {provenanceConstrainedNote()}
            </p>
          )}
        </fieldset>

        <button type="submit" className="symbol-submit" disabled={creatingJob || running}>
          {creatingJob ? t("competitionRounds.library.starting") : t("competitionRounds.library.runRound")}
        </button>
      </form>

      {jobError && <div className="callout callout-danger comp-job-error">{jobError}</div>}

      {job && <JobProgressPanel job={job} onCancel={onCancelJob} />}
    </div>
  );
}

function JobProgressPanel({ job, onCancel }: { job: JobStatus; onCancel: () => void }) {
  const { t } = useT();
  const terminal = isTerminalJobStatus(job.status);
  return (
    <div className="comp-job-panel">
      <div className="comp-job-head">
        <span className={`state-pill comp-job-status comp-job-status-${job.status}`}>
          {jobStatusLabel(job.status)}
        </span>
        <span className="comp-job-progress-text">
          {t("competitionRounds.library.runsComplete", {
            completed: job.completed_runs,
            total: job.total_runs,
          })}
          {job.failed_runs > 0 && (
            <span className="comp-job-failed">
              {" "}
              · {t("competitionRounds.library.runsFailed", { count: job.failed_runs })}
            </span>
          )}
        </span>
        {!terminal && (
          <button type="button" className="symbol-submit comp-job-cancel" onClick={onCancel}>
            {t("competitionRounds.library.cancel")}
          </button>
        )}
      </div>
      {/* The proportional bar. CSS cannot compute a percentage from two numbers in the DOM, so the
          ratio is handed to it as a custom property and the bar's width is drawn from that. Guarded
          against `total_runs: 0`, which is what a job looks like between `POST` and its first poll. */}
      <div
        className="comp-job-progress-bar"
        style={
          {
            "--comp-job-pct": `${job.total_runs > 0 ? Math.round((job.completed_runs / job.total_runs) * 100) : 0}%`,
          } as React.CSSProperties
        }
        role="progressbar"
        aria-valuenow={job.completed_runs}
        aria-valuemin={0}
        aria-valuemax={job.total_runs}
        aria-label={t("competitionRounds.library.progressLabel")}
      />
      {job.current && (
        <div className="comp-job-current">
          {t("competitionRounds.library.running", {
            agentId: job.current.agent_id,
            window: job.current.window,
          })}
        </div>
      )}
      {job.error && <div className="callout callout-danger">{job.error}</div>}
      {job.log.length > 0 && (
        // No dedicated "job log" heading exists for a manually-run round -- reusing the evolution
        // loop's own `competition.loop.log.heading` ("Supervisor log"), the closest existing
        // translated "log" label in the catalog, rather than inventing a new key. Worth its own key
        // in a later i18n pass.
        <ScrollRegion size="sm" label={t("competition.loop.log.heading")}>
          <pre className="comp-job-log">{job.log.slice(-8).join("\n")}</pre>
        </ScrollRegion>
      )}
      {job.results.length > 0 && (
        <ScrollRegion
          size="md"
          label={t("competitionRounds.library.runsComplete", {
            completed: job.completed_runs,
            total: job.total_runs,
          })}
        >
          <div className="table-wrap">
            <table className="data-table comp-job-results-table">
              <thead>
              <tr>
                <th>{t("competitionRounds.library.resultsTable.window")}</th>
                <th>{t("competitionRounds.table.agent")}</th>
                <th>{t("common.status")}</th>
                <th className="num">{t("competitionRounds.library.resultsTable.excess")}</th>
                <th className="num">{t("competitionRounds.library.resultsTable.seconds")}</th>
              </tr>
            </thead>
            <tbody>
              {job.results.map((r, i) => (
                <tr key={`${r.window}-${r.agent_id}-${i}`}>
                  <td>{r.window}</td>
                  <td>{r.agent_id}</td>
                  <td>
                    <span className={`state-pill comp-job-result-${r.status}`}>
                      {jobRunResultStatusLabel(r.status)}
                    </span>
                  </td>
                  <td className={numCell(r.excess !== undefined ? fractionTone(r.excess) : "")}>
                    {r.excess !== undefined ? formatSignedPctFraction(r.excess) : "—"}
                  </td>
                  <td className="num comp-num">
                    {r.seconds !== undefined ? r.seconds.toFixed(1) : "—"}
                  </td>
                </tr>
              ))}
              </tbody>
            </table>
          </div>
        </ScrollRegion>
      )}
    </div>
  );
}
