// ---------------------------------------------------------------------------
// 1. Leaderboard
// ---------------------------------------------------------------------------
import {
  formatIntOrDash,
  formatRatio,
  formatSignedPctFraction,
  fractionTone,
  provenanceConstrainedNote,
  purposeLabel,
  PURPOSE_LABELS,
  rankByLabel,
  RANK_BY_OPTIONS,
  type LeaderboardResponse,
  type LeaderboardRow,
  type Purpose,
  type RankBy,
  type RoundSummary,
  type WindowBenchmark,
} from "@/api/competition";
import { ScrollRegion } from "@/components/ScrollPanel";
import Skeleton from "@/components/Skeleton";
import StatusPill from "@/components/StatusPill";
import Term from "@/components/Term";
import { useT, Trans } from "@/i18n";
import { numCell } from "@/pages/competition/cells";

import "./LeaderboardSection.css";

type Phase = "loading" | "loaded" | "error";

export interface LeaderboardSectionProps {
  rounds: RoundSummary[];
  selectedRoundId: string | null;
  rankBy: RankBy;
  onRankByChange: (rankBy: RankBy) => void;
  purpose: Purpose;
  onSelectPurpose: (purpose: Purpose) => void;
  leaderboard: LeaderboardResponse | null;
  phase: Phase;
  message: string | null;
  onSelectAgent: (agentId: string) => void;
  /** The agent whose drill-down is open in the drawer below this table, so each row's own toggle can
   *  report `aria-expanded` honestly. `null` when nothing is open. */
  selectedAgentId: string | null;
}

export default function LeaderboardSection({
  rounds,
  selectedRoundId,
  rankBy,
  onRankByChange,
  purpose,
  onSelectPurpose,
  leaderboard,
  phase,
  message,
  onSelectAgent,
  selectedAgentId,
}: LeaderboardSectionProps) {
  const { t } = useT();
  const selectedRound = rounds.find((r) => r.round_id === selectedRoundId) ?? null;
  // `false` while rounds are still loading, so a slow `/rounds` never makes a real error masquerade
  // as the designed "no results" state -- that would hide a genuine failure behind a reassuring one.
  const selectedRoundHasNoResults = selectedRound !== null && !selectedRound.has_results;
  const selectedRoundLabel = selectedRound?.label ?? t("competition.leaderboard.thisRoundFallback");

  return (
    <>
      <div className="panel filter-bar comp-controls">
        {/* Purpose sits before Round because it changes *which competition* the table is showing,
            not merely how it is sorted. The three purposes are scored on different quantities and a
            row from one is not comparable to a row from another -- see `scoring_basis` below. */}
        <label className="bt-control-label" htmlFor="comp-purpose-select">
          {t("competition.purposeFieldLabel")}
          <select
            id="comp-purpose-select"
            className="bt-entry-select"
            value={purpose}
            onChange={(e) => onSelectPurpose(e.target.value as Purpose)}
          >
            {(Object.keys(PURPOSE_LABELS) as Purpose[]).map((p) => (
              <option key={p} value={p}>
                {purposeLabel(p)}
              </option>
            ))}
          </select>
        </label>
        {/* No round picker here. This section renders underneath `SummarySection` in the merged
            "Rounds" view, and that section's grouped `<select>` is the page's one round picker --
            both are driven by the same `selectedRoundId` from `Competition.tsx`, so a second picker
            down here would only let a reader change the round in two places that coincidentally
            agree. That duplication is what the merge exists to remove. */}
        <label className="bt-control-label" htmlFor="comp-rankby-select">
          {t("competition.leaderboard.rankByLabel")}
          <select
            id="comp-rankby-select"
            className="bt-entry-select"
            value={rankBy}
            onChange={(e) => onRankByChange(e.target.value as RankBy)}
          >
            {RANK_BY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {rankByLabel(o.value)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* The loading / error / no-rounds-yet states of the shared `/rounds` fetch are reported by
          `SummarySection` directly above on the same page, so they are deliberately absent here --
          on one merged page a second copy reads as the app saying the same thing twice. What this
          section still reports below is its own: the state of the *leaderboard* fetch. */}
      {/* A shaped placeholder, not a "Loading…" line: this panel becomes a wide ranked table, and a
          one-line loading state collapses the page and then snaps it open the instant the fetch
          lands. `Skeleton` also carries the polite live region the bare line never had. */}
      {phase === "loading" && (
        <div className="panel">
          <Skeleton variant="rows" rows={6} what={t("competition.leaderboard.skeletonWhat")} />
        </div>
      )}
      {/* A round with no run files makes the leaderboard endpoint answer 404 by design, and the
          page used to render that response body verbatim -- the reader got a raw
          `{"detail":"no such round: ..."}` where a table should be. That is a known, expected state
          with a real explanation, so it gets one, and only a genuinely unexpected failure falls
          through to the error text below. */}
      {phase === "error" && selectedRoundHasNoResults && (
        <div className="panel">
          <div className="placeholder">
            <Trans
              k="competition.leaderboard.noResultsCallout"
              values={{
                bold: (
                  <strong>{t("competition.leaderboard.noResultsBold", { label: selectedRoundLabel })}</strong>
                ),
              }}
            />
          </div>
        </div>
      )}
      {phase === "error" && !selectedRoundHasNoResults && (
        <div className="panel">
          <div className="placeholder">{message ?? t("competition.leaderboard.error")}</div>
        </div>
      )}
      {/* An empty board is not a table with no rows. It has two very different causes -- these cards
          were measured and did badly, or they have never been run at all -- and the server names
          which one in `unscored_reason`. Rendering a bare empty table for the second case would say
          "these strategies have nothing to show for themselves" about strategies nobody has
          measured. */}
      {phase === "loaded" && leaderboard && leaderboard.rows.length === 0 && (
        <div className="panel">
          <div className="placeholder comp-unscored">
            {leaderboard.unscored_reason ??
              t("competition.leaderboard.unscoredFallback", { purpose: purposeLabel(leaderboard.purpose) })}
          </div>
        </div>
      )}

      {phase === "loaded" && leaderboard && leaderboard.rows.length > 0 && (
        <>
          {/* The three purposes are ranked on different quantities, so the basis is stated above the
              table rather than assumed from the column headings. An IRR and an adjusted excess are
              different quantities; ranking them together is a category error, not a rounding one. */}
          <p className="muted comp-scoring-basis">
            <Trans
              k="competition.leaderboard.scoringBasis"
              values={{
                purpose: purposeLabel(leaderboard.purpose),
                basis: <strong>{leaderboard.scoring_basis}</strong>,
              }}
            />
          </p>
          <LeaderboardTable
            leaderboard={leaderboard}
            onSelectAgent={onSelectAgent}
            selectedAgentId={selectedAgentId}
          />
        </>
      )}
    </>
  );
}

function LeaderboardTable({
  leaderboard,
  onSelectAgent,
  selectedAgentId,
}: {
  leaderboard: LeaderboardResponse;
  onSelectAgent: (agentId: string) => void;
  selectedAgentId: string | null;
}) {
  const { t } = useT();
  const windows = leaderboard.windows;
  // Eligibility ("ran N of ...") is judged against the windows that are actually comparable -- a
  // `provenance_constrained` window's universe was only knowable after the fact, so a card is not
  // expected to have run there the way it is expected to have run everywhere else.
  const comparableCount = windows.filter((w) => !w.provenance_constrained).length;
  const constrainedWindows = windows.filter((w) => w.provenance_constrained);
  const rows = [...leaderboard.rows].sort((a, b) => a.rank - b.rank);
  const heading = t("competition.leaderboard.heading", { roundId: leaderboard.round_id });

  return (
    <div className="panel">
      {/* Rank 1 on a board sorted by median excess reads as a winner. It is not: the programme's own
          verdict across every round is that no durable out-of-sample edge was found, and that
          verdict used to live only on `/strategy` -- a page a reader looking at this table may never
          open. The same `landing.strategy.verdictPill` key renders here so the finding travels with
          the table it qualifies, per docs/COPY-STYLE.md rule 6 (a caveat the reader is worse off
          for not seeing keeps a visible short form). No q-value or independent-window column sits
          beside it because neither is on the wire -- `LeaderboardRow` in `@/api/competition` carries
          `median_excess`/`worst_excess`/`hit_rate`/`windows_run` and no multiplicity correction. */}
      <div className="comp-leaderboard-head">
        <h2 className="section-heading">{heading}</h2>
        <StatusPill
          tone="warn"
          label={t("landing.strategy.verdictPill")}
          detail={t("landing.strategy.verdict")}
          data-testid="comp-leaderboard-verdict"
        />
      </div>
      {/* This table's own sticky header + pinned identity columns predate the shared `ScrollRegion`
          primitive (`@/components/ScrollPanel`), which is why the bounding box below is a plain
          `ScrollRegion` rather than a `ScrollPanel`: the pinned-column CSS in `Competition.css`
          (`.comp-leaderboard-table th/td:nth-child(1)/(2)`) still does its own thing, layered on top
          of the primitive's generic `.scroll-region table thead th` sticky-header rule. `.table-wrap`
          stays nested inside the region -- it only ever supplied `overflow-x`, and per the CSS
          Overflow spec that alone used to compute `overflow-y: auto` too with no real bound, which is
          the exact defect `ScrollRegion` exists to fix everywhere on this page. */}
      <ScrollRegion size="lg" label={heading}>
        <div className="table-wrap">
          <table className="data-table comp-leaderboard-table">
            <thead>
              <tr>
                <th>{t("competition.leaderboard.col.rank")}</th>
                <th>{t("competition.leaderboard.col.agent")}</th>
                <th>{t("competition.leaderboard.col.discipline")}</th>
                <th className="num">{t("competition.leaderboard.col.windowsRun")}</th>
                <th className="num">{t("competition.leaderboard.col.medianExcess")}</th>
                <th className="num">{t("competition.leaderboard.col.worstExcess")}</th>
                <th className="num">{t("competition.leaderboard.col.hitRate")}</th>
                {/* The column that decides whether a rank means anything: a card in the market a
                    tenth of the time carries a tenth of the risk, and its excess is not comparable
                    to a fully-invested one's without knowing that. Defined here, at its first and
                    only appearance on this page. */}
                <th className="num">
                  <Term k="exposure">{t("competition.leaderboard.col.meanExposure")}</Term>
                </th>
                {windows.map((w) => (
                  <th key={w.window} className="num comp-window-header">
                    {w.window}
                    {w.provenance_constrained && (
                      <span className="badge comp-provenance-chip" title={provenanceConstrainedNote()}>
                        {t("competition.provenanceConstrained.chip")}
                      </span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr className="comp-spy-row">
                <td>—</td>
                <td>{t("competition.leaderboard.spyBenchmark")}</td>
                <td>—</td>
                <td className="num">—</td>
                <td className="num">—</td>
                <td className="num">—</td>
                <td className="num">—</td>
                <td className="num">—</td>
                {windows.map((w) => (
                  <td key={w.window} className={numCell(fractionTone(w.benchmark_return))}>
                    {formatSignedPctFraction(w.benchmark_return)}
                  </td>
                ))}
              </tr>
              {rows.map((row) => (
                <LeaderboardTableRow
                  key={row.agent_id}
                  row={row}
                  windows={windows}
                  comparableCount={comparableCount}
                  expanded={row.agent_id === selectedAgentId}
                  onSelect={() => onSelectAgent(row.agent_id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      </ScrollRegion>
      {rows.length === 0 && <div className="placeholder">{t("competition.leaderboard.noAgentsRan")}</div>}

      {constrainedWindows.length > 0 && (
        <div className="callout callout-info comp-provenance-note">
          <strong>
            {t(
              constrainedWindows.length === 1
                ? "competition.leaderboard.provenanceNote_one"
                : "competition.leaderboard.provenanceNote_other",
              { windows: constrainedWindows.map((w) => w.window).join(", ") },
            )}
          </strong>{" "}
          {provenanceConstrainedNote()}
        </div>
      )}
    </div>
  );
}

/**
 * One card's row.
 *
 * **The row is a plain `<tr>`.** It used to carry `role="button"` + `tabIndex={0}`, which told
 * assistive technology that ten buttons were sitting where a table's rows should be: the row/column
 * relationship a data table exists to express was gone, and with it any way to hear "rank 4, median
 * excess -2.1%" as one row of a grid. The affordance that role was standing in for -- open this
 * card's drill-down -- is now a real `<button aria-expanded>` in the rank cell, which is announced
 * as a control, is reachable in the tab order on its own, and (unlike the row) can say whether the
 * thing it opens is currently open.
 *
 * The whole row keeps its plain `onClick` as a convenience for a pointer, which costs nothing: it
 * carries no role, no tab stop, and nothing in the accessibility tree, so a screen-reader or
 * keyboard user meets exactly one control per row rather than one control inside one button.
 */
function LeaderboardTableRow({
  row,
  windows,
  comparableCount,
  expanded,
  onSelect,
}: {
  row: LeaderboardRow;
  windows: WindowBenchmark[];
  comparableCount: number;
  /** Whether this row's drill-down is the one currently open in the drawer below the table. */
  expanded: boolean;
  onSelect: () => void;
}) {
  const { t } = useT();
  return (
    <tr
      // `comp-rank-N` for the podium rather than letting the stylesheet target the first three
      // `<tr>`s by position: that only works while this table happens to be sorted by rank
      // ascending, and it silently mis-styles the moment a different `rank_by` reorders the rows.
      className={`comp-agent-row${row.eligible ? "" : " comp-ineligible-row"}${
        row.rank <= 3 ? ` comp-rank-${row.rank}` : ""
      }${expanded ? " comp-agent-row-open" : ""}`}
      onClick={onSelect}
    >
      <td>
        <button
          type="button"
          className="comp-row-toggle"
          aria-expanded={expanded}
          aria-label={t("competition.leaderboard.rowToggleAria", {
            rank: row.rank,
            name: row.display_name,
          })}
          // The row's own pointer handler would otherwise fire straight after this one and toggle
          // the drawer a second time, back to where it started.
          onClick={(e) => {
            e.stopPropagation();
            onSelect();
          }}
        >
          {row.rank}
        </button>
      </td>
      <td>
        {row.display_name}
        {!row.eligible && (
          <span className="badge comp-ineligible-chip">
            {t("competition.leaderboard.ranOfWindows", { run: row.windows_run, total: comparableCount })}
          </span>
        )}
      </td>
      <td>{row.discipline}</td>
      <td className="num comp-num">{formatIntOrDash(row.windows_run)}</td>
      <td className={numCell(fractionTone(row.median_excess))}>
        {formatSignedPctFraction(row.median_excess)}
      </td>
      <td className={numCell(fractionTone(row.worst_excess))}>
        {formatSignedPctFraction(row.worst_excess)}
      </td>
      <td className="num comp-num">{formatRatio(row.hit_rate)}</td>
      <td className="num comp-num">{formatRatio(row.mean_capital_exposure)}</td>
      {windows.map((w) => {
        const cell = row.per_window[w.window];
        return (
          <td key={w.window} className={numCell(cell ? fractionTone(cell.excess) : "")}>
            {cell ? formatSignedPctFraction(cell.excess) : "—"}
          </td>
        );
      })}
    </tr>
  );
}
