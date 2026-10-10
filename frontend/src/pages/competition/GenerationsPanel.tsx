/**
 * The whole-field, whole-history browser for the evolution loop's generations -- the fix for
 * `LoopPanel` only ever having rendered one first-place `Standing` from the *current* run
 * (`BestStanding`). Mounted at the bottom of `LoopPanel`; see that file's own docstring for why.
 *
 * Unlike every other component on this page (`LoopPanel`, `LeaderboardSection`, ...), this one reads
 * its own data rather than taking it as props: the generation history and its failure streaks are
 * independent of whatever `LoopStatus` the loop happens to be in *right now* -- they exist and are
 * worth reading whether the loop is running, stopped, or has never been started this session.
 *
 * **Collapsing failure streaks is this component's single most important display decision.** The real
 * generation history behind this loop runs to 1673 generations, of which 1644 failed with one
 * identical error, in runs of hundreds. A table with one row per generation would render those as
 * hundreds of near-identical rows and bury the handful of generations that actually produced a field
 * worth reading -- the exact "there's nothing useful on screen" failure mode `Competition.tsx`'s
 * `orderRounds`/`defaultRoundId` were written to avoid, one level down. `GET /failure-streaks` answers
 * with the collapsed shape directly: one record per run of consecutive identical failures, including a
 * run of one (an isolated failure with no repeat). `mergeGenerationRows` below is the one place that
 * combines it with the ordinary `/generations` list: every `status === "failed"` summary from that
 * list is dropped in favour of the streak record that already accounts for it -- never rendered a
 * second time as an individual row, and never silently dropped either, since even a lone failure still
 * comes back from `/failure-streaks` as its own one-line record.
 *
 * **Failure streaks are not attributable to one purpose.** `FailureStreak` carries no `purpose` field
 * -- these are runs of an identical error (typically an infrastructure fault, not a losing strategy),
 * and the backend does not scope them to a lane. So streak rows are fetched once, independent of the
 * `purpose` filter below, and always render regardless of which lane the table is currently filtered
 * to -- each one labelled "(all purposes)" so a reader never mistakes a streak for evidence about the
 * lane they happen to be looking at.
 *
 * **The purpose filter is not cosmetic -- it is what makes the trend section correct.** Generations
 * cycle through lanes (purpose x card shape); generation 40 in the "trading" lane and generation 41 in
 * "savings" were never in the same competition, so a sparkline drawn across both would compare field
 * medians that were never measured against each other. One `purpose` selector drives both the ordinary
 * generation query and the trend query, so the two never disagree about which lane is on screen, and
 * `GenerationTrends` states the lane in its own heading rather than leaving it implicit.
 *
 * **Percentages arrive in two incompatible units.** `median_excess`/`worst_excess`/`hit_rate`/
 * `holdout_median` are fractions (`0.194` = 19.4%); `holdout_gap_pp`/`gate.margin_pp` are already in
 * percentage points. `formatPctPoints` (`api/evolution.ts`) exists specifically so this file never runs
 * a pp value through `formatSignedPctFraction`, or vice versa -- swapping the two is a silent 100x
 * error that does not look obviously wrong on screen.
 *
 * **The whole component is wrapped in a top-level `Collapsible`, closed by default.** This is the
 * heaviest thing `LoopPanel` mounts underneath the loop's own status -- a paginated table plus three
 * sparklines, always rendered regardless of whether the loop is running. Closed by default (matching
 * `RoundNarrativeCard`'s own long-form section) so opening the Loop tab does not force a reader to
 * scroll past this before reaching `JournalPanel`; every row/column/fetch below is unchanged, just
 * inside the disclosure. `Collapsible` always mounts its children, so the fetches this component owns
 * still fire on mount whether or not the panel starts open.
 */
import { useEffect, useMemo, useState } from "react";

import type { DecimalString } from "@/api/client";
import {
  formatIntOrDash,
  formatPctFraction,
  formatSignedPctFraction,
  fractionTone,
} from "@/api/competition";
import {
  evolutionApi,
  findingKindLabel,
  formatFieldStat,
  formatPctPoints,
  purposeLabel,
  type FailureStreak,
  type Finding,
  type FindingKind,
  type GenerationDetailResponse,
  type GenerationReview,
  type GenerationReviewVerdict,
  type GenerationSummary,
  type GenerationsListResponse,
  type Purpose,
  type Standing,
  type StatSummary,
} from "@/api/evolution";
import Collapsible from "@/components/Collapsible";
import { ScrollRegion } from "@/components/ScrollPanel";
import StatusPill, { type PillTone } from "@/components/StatusPill";
import { formatFetchError as errorMessage, useFetch, type FetchPhase } from "@/hooks/useFetch";
import { Trans, useT, type MessageKey } from "@/i18n";

const PURPOSE_OPTIONS: Purpose[] = ["trading", "savings", "roth"];
const PAGE_SIZE = 25;
/** How far back the trend section looks -- generously larger than one table page since the sparkline
 * is meant to show a shape over time, not just the page currently on screen. `succeeded_only: true`
 * keeps this query cheap even though the raw generation count behind a purpose can be large: failed
 * generations carry no `field` to plot in the first place (see `GenerationField`'s docstring). */
const TREND_LIMIT = 200;

/** `Standing.q_value` duplicated from `formatQ` (`api/backtest.ts`/`api/thesis.ts`) rather than
 * imported -- those modules are owned by other agents and out of this file's scope fence, and every
 * API-adjacent module in this codebase already carries its own copy of shared formatting rather than
 * import across page boundaries (see `api/evolution.ts`'s own docstring on `requestJson`). */
function formatQValue(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  if (value < 0.001) return "<0.001";
  return value.toFixed(3);
}

/** Label for a `GenerationSummary.status` value, reusing the shared `status.*` catalog keys
 * (`common.ts`) rather than rendering the raw wire string -- the previous `{summary.status}` render
 * showed the untranslated lowercase value verbatim. Module-private, mirrors `verdictLabel` below. */
function generationStatusLabel(status: GenerationSummary["status"], t: (key: MessageKey) => string): string {
  switch (status) {
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

/** Tone mapping for `GenerationSummary.status`, per docs/COPY-STYLE.md. `"failed"` is included for
 * exhaustiveness even though `mergeGenerationRows` drops every `status === "failed"` summary in favour
 * of its collapsed `FailureStreak` row -- see this module's docstring. */
function generationStatusTone(status: GenerationSummary["status"]): PillTone {
  switch (status) {
    case "succeeded":
      return "ok";
    case "failed":
      return "bad";
    case "cancelled":
      return "neutral";
    default: {
      const _exhaustive: never = status;
      void _exhaustive;
      return "neutral";
    }
  }
}

/** Tone mapping for `GenerationReviewVerdict`, per docs/COPY-STYLE.md: promising -> ok, inconclusive ->
 * neutral, exhausted -> warn (the search on this lane is spent), broken -> bad. */
function verdictTone(verdict: GenerationReviewVerdict): PillTone {
  switch (verdict) {
    case "promising":
      return "ok";
    case "inconclusive":
      return "neutral";
    case "exhausted":
      return "warn";
    case "broken":
      return "bad";
    default: {
      const _exhaustive: never = verdict;
      void _exhaustive;
      return "neutral";
    }
  }
}

/** A row this table actually renders: either one ordinary generation, or one collapsed failure streak
 * standing in for every failed generation it covers. A single discriminated union so the table body is
 * one `.map` over one array, ordered newest-first by whichever generation number sorts each kind of
 * row -- `last_generation` for a streak, `generation` for an ordinary row. */
type GenerationRow =
  | { kind: "generation"; sortKey: number; summary: GenerationSummary }
  | { kind: "streak"; sortKey: number; streak: FailureStreak };

/**
 * Combines one page of `/generations` with the full `/failure-streaks` list into the newest-first rows
 * the table renders. Every `status === "failed"` summary is dropped here in favour of the streak that
 * already accounts for it -- see this module's docstring for why, and why that never loses a failure:
 * `/failure-streaks` covers every failed generation, including runs of exactly one.
 */
function mergeGenerationRows(generations: GenerationSummary[], streaks: FailureStreak[]): GenerationRow[] {
  const rows: GenerationRow[] = [];
  for (const g of generations) {
    if (g.status === "failed") continue;
    rows.push({ kind: "generation", sortKey: g.generation, summary: g });
  }
  for (const s of streaks) {
    rows.push({ kind: "streak", sortKey: s.last_generation, streak: s });
  }
  return rows.sort((a, b) => b.sortKey - a.sortKey);
}

export default function GenerationsPanel() {
  const { t } = useT();
  const [purpose, setPurpose] = useState<Purpose>("trading");
  const [offset, setOffset] = useState(0);

  const listResult = useFetch<GenerationsListResponse>(
    (signal) => evolutionApi.generations({ purpose, limit: PAGE_SIZE, offset }, signal),
    [purpose, offset],
    { formatError: (err) => errorMessage(err, t("competition.generations.errors.list")) },
  );
  const listResponse = listResult.data;
  const listPhase = listResult.phase;
  const listMessage = listResult.error;

  // Resets pagination whenever the lane changes -- an offset from one purpose's page count means
  // nothing against another purpose's.
  useEffect(() => {
    setOffset(0);
  }, [purpose]);

  // Fetched once, independent of `purpose` -- see this module's docstring on why a failure streak
  // cannot be attributed to one lane.
  const streaksResult = useFetch(
    (signal) => evolutionApi.failureStreaks(signal).then((res) => res.streaks),
    [],
    { formatError: (err) => errorMessage(err, t("competition.generations.errors.streaks")) },
  );
  const streaks = streaksResult.data ?? [];
  const streaksPhase = streaksResult.phase;
  const streaksMessage = streaksResult.error;

  const rows = useMemo(
    () => (listResponse ? mergeGenerationRows(listResponse.generations, streaks) : []),
    [listResponse, streaks],
  );

  // --- trend data: a separate, wider, purpose-scoped fetch --------------------------------------
  const trendResult = useFetch(
    (signal) =>
      evolutionApi
        .generations({ purpose, limit: TREND_LIMIT, offset: 0, succeeded_only: true }, signal)
        .then((res) => res.generations),
    [purpose],
    { formatError: (err) => errorMessage(err, t("competition.generations.errors.trend")) },
  );
  const trendGenerations = trendResult.data ?? [];
  const trendPhase = trendResult.phase;
  const trendMessage = trendResult.error;

  // --- per-row expansion + detail fetch -----------------------------------------------------------
  const [expandedGeneration, setExpandedGeneration] = useState<number | null>(null);
  const [expandedStreakKey, setExpandedStreakKey] = useState<string | null>(null);
  const [detailCache, setDetailCache] = useState<Record<number, DetailState>>({});

  const toggleGeneration = (generation: number) => {
    setExpandedGeneration((prev) => (prev === generation ? null : generation));
    if (!(generation in detailCache)) {
      setDetailCache((prev) => ({ ...prev, [generation]: { phase: "loading" } }));
      evolutionApi
        .generationDetail(generation)
        .then((data) => {
          setDetailCache((prev) => ({ ...prev, [generation]: { phase: "loaded", data } }));
        })
        .catch((err: unknown) => {
          setDetailCache((prev) => ({
            ...prev,
            [generation]: {
              phase: "error",
              message: errorMessage(err, t("competition.generations.errors.detail")),
            },
          }));
        });
    }
  };

  const toggleStreak = (key: string) => {
    setExpandedStreakKey((prev) => (prev === key ? null : key));
  };

  const total = listResponse?.total ?? 0;
  const returned = listResponse?.returned ?? 0;
  const unreadable = listResponse?.unreadable ?? 0;
  const canGoPrev = offset > 0;
  const canGoNext = offset + returned < total;

  return (
    // The whole-field, whole-history browser is the heaviest thing `LoopPanel` mounts -- a top-level
    // `Collapsible`, closed by default like `RoundNarrativeCard`'s own long-form section, so a reader
    // does not have to scroll past 25 rows of generation history (plus three sparklines) every time
    // they open the Loop tab just to reach `JournalPanel` below it. See `LoopPanel.tsx`'s module
    // docstring for the rest of this page's bounding work.
    <Collapsible
      title={<h3 className="comp-loop-subheading">{t("competition.generations.heading")}</h3>}
      defaultOpen={false}
      className="comp-gens-panel"
    >
      <div className="comp-gens-head">
        <label className="bt-control-label" htmlFor="comp-gens-purpose">
          {t("competition.purposeFieldLabel")}
          <select
            id="comp-gens-purpose"
            className="bt-entry-select"
            value={purpose}
            onChange={(e) => setPurpose(e.target.value as Purpose)}
          >
            {PURPOSE_OPTIONS.map((p) => (
              <option key={p} value={p}>
                {purposeLabel(p)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="comp-loop-form-hint">{t("competition.generations.hint")}</p>

      <GenerationTrends purpose={purpose} phase={trendPhase} message={trendMessage} generations={trendGenerations} />

      {listPhase === "loading" && <div className="placeholder">{t("competition.generations.loading")}</div>}
      {listPhase === "error" && (
        <div className="callout callout-danger">{listMessage ?? t("competition.generations.errors.list")}</div>
      )}
      {streaksPhase === "error" && (
        <div className="callout callout-danger">
          {streaksMessage ?? t("competition.generations.errors.streaks")}
        </div>
      )}

      {listPhase === "loaded" && (
        <>
          {unreadable > 0 && (
            <div className="callout callout-warn comp-gens-unreadable">
              {t(
                unreadable === 1
                  ? "competition.generations.unreadable_one"
                  : "competition.generations.unreadable_other",
                { count: unreadable },
              )}
            </div>
          )}
          {rows.length === 0 ? (
            <div className="placeholder">{t("competition.generations.empty")}</div>
          ) : (
            <ScrollRegion size="lg" label={t("competition.generations.heading")}>
              <div className="table-wrap">
                <table className="data-table comp-gens-table">
                  <thead>
                    <tr>
                      <th>{t("competition.generations.col.generation")}</th>
                      <th>{t("competition.generations.col.status")}</th>
                      <th>{t("competition.generations.col.candidatesRankedEligible")}</th>
                      <th>{t("competition.generations.col.fieldSelectionMedian")}</th>
                      <th>{t("competition.generations.col.fieldHitRate")}</th>
                      <th>{t("competition.generations.col.holdoutGap")}</th>
                      <th>{t("competition.generations.col.gateClearedEligible")}</th>
                      <th>{t("competition.generations.col.promoted")}</th>
                      <th>{t("competition.generations.col.review")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) =>
                      row.kind === "streak" ? (
                        <FailureStreakRow
                          key={`streak-${row.streak.first_generation}-${row.streak.last_generation}`}
                          streak={row.streak}
                          expanded={
                            expandedStreakKey === `${row.streak.first_generation}-${row.streak.last_generation}`
                          }
                          onToggle={() =>
                            toggleStreak(`${row.streak.first_generation}-${row.streak.last_generation}`)
                          }
                        />
                      ) : (
                        <GenerationRowView
                          key={`gen-${row.summary.generation}`}
                          summary={row.summary}
                          expanded={expandedGeneration === row.summary.generation}
                          onToggle={() => toggleGeneration(row.summary.generation)}
                          detail={detailCache[row.summary.generation]}
                        />
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </ScrollRegion>
          )}
          <div className="comp-gens-pagination">
            <button type="button" onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} disabled={!canGoPrev}>
              {t("competition.generations.newer")}
            </button>
            <span className="comp-gens-pagination-summary">
              {total === 0
                ? t("competition.generations.pageRangeEmpty")
                : t("competition.generations.pageRange", { from: offset + 1, to: offset + returned, total })}
            </span>
            <button type="button" onClick={() => setOffset(offset + PAGE_SIZE)} disabled={!canGoNext}>
              {t("competition.generations.older")}
            </button>
          </div>
        </>
      )}
    </Collapsible>
  );
}

type DetailState =
  | { phase: "loading" }
  | { phase: "loaded"; data: GenerationDetailResponse }
  | { phase: "error"; message: string };

/** One collapsed failure streak. Expanding it reveals the fields already present on `FailureStreak`
 * itself (full error text, the generation range, and both timestamps) -- no further fetch is needed,
 * since the backend already returns everything a streak record has to say about itself. */
function FailureStreakRow({
  streak,
  expanded,
  onToggle,
}: {
  streak: FailureStreak;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useT();
  const span =
    streak.first_generation === streak.last_generation
      ? t("competition.generations.streak.singleGeneration", { n: streak.first_generation })
      : t("competition.generations.streak.rangeGenerations", {
          first: streak.first_generation,
          last: streak.last_generation,
        });
  const label =
    streak.count === 1
      ? t("competition.generations.streak.singleFailed", { span })
      : t("competition.generations.streak.multipleFailed", { count: streak.count });
  return (
    <>
      <tr
        className="comp-gens-streak-row"
        onClick={onToggle}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") onToggle();
        }}
      >
        <td colSpan={9}>
          <StatusPill
            tone="bad"
            label={`${t("competition.generations.streak.failedBadge")}${
              streak.count > 1 ? ` ×${streak.count}` : ""
            }`}
            className="comp-gens-streak-badge"
          />
          <span className="comp-gens-streak-label">
            {label} <span className="comp-gens-streak-error">{streak.error}</span>
          </span>
          <span className="tile-hint comp-gens-streak-scope">{t("competition.generations.streak.allPurposes")}</span>
        </td>
      </tr>
      {expanded && (
        <tr className="comp-gens-streak-detail-row">
          <td colSpan={9}>
            <div className="comp-gens-streak-detail">
              <div className="status-grid comp-loop-stats">
                <div className="stat">
                  <span className="label">{span}</span>
                  <span className="value">
                    {t("competition.generations.streak.count", { count: formatIntOrDash(streak.count) })}
                  </span>
                </div>
                <div className="stat">
                  <span className="label">{t("competition.generations.streak.firstFailed")}</span>
                  <span className="value">{streak.started_at}</span>
                </div>
                <div className="stat">
                  <span className="label">{t("competition.generations.streak.lastFailed")}</span>
                  <span className="value">{streak.finished_at}</span>
                </div>
              </div>
              <p className="comp-gens-streak-full-error">{streak.error}</p>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/** One ordinary generation's row. Every non-`null` `StatSummary` cell shows the field median plus `n`
 * via `formatFieldStat`; a `null` one shows "no field" -- never `0`. Selection and holdout figures are
 * kept in separate, separately-labelled columns ("Field selection median" vs. "Holdout gap"), carrying
 * `LoopPanel`'s own reasoning on that point forward: folding a holdout number into the selection
 * column, or leaving off which is which, states a stronger claim than the evidence supports. */
function GenerationRowView({
  summary,
  expanded,
  onToggle,
  detail,
}: {
  summary: GenerationSummary;
  expanded: boolean;
  onToggle: () => void;
  detail: DetailState | undefined;
}) {
  const { t } = useT();
  return (
    <>
      <tr
        className="comp-gens-row comp-agent-row"
        onClick={onToggle}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") onToggle();
        }}
      >
        <td>
          <span className="comp-card-name">
            {t("competition.generations.row.genLabel", { n: summary.generation })}
          </span>
          <span className="tile-hint"> · {purposeLabel(summary.purpose)}</span>
        </td>
        <td>
          <StatusPill tone={generationStatusTone(summary.status)} label={generationStatusLabel(summary.status, t)} />
        </td>
        <td className="comp-num">
          {formatIntOrDash(summary.candidates)} / {formatIntOrDash(summary.ranked)} /{" "}
          {formatIntOrDash(summary.eligible)}
        </td>
        <td className="comp-num">{formatFieldStat(summary.field.median_excess, formatSignedPctFraction)}</td>
        <td className="comp-num">{formatFieldStat(summary.field.hit_rate, formatPctFraction)}</td>
        <td className="comp-num comp-gens-holdout-cell">
          {formatFieldStat(summary.field.holdout_gap_pp, formatPctPoints)}
        </td>
        <td className="comp-num">
          {formatIntOrDash(summary.gate.cleared)} / {formatIntOrDash(summary.gate.eligible)}
        </td>
        <td className="comp-num">{formatIntOrDash(summary.promoted.length)}</td>
        <td>
          {summary.has_review ? (
            <span className="badge">{t("competition.generations.row.reviewed")}</span>
          ) : (
            <span className="badge none">{t("competition.generations.row.noReview")}</span>
          )}
        </td>
      </tr>
      {expanded && (
        <tr className="comp-gens-detail-row">
          <td colSpan={9}>
            <GenerationDetailView generation={summary.generation} detail={detail} />
          </td>
        </tr>
      )}
    </>
  );
}

/** The expanded view of one generation: every `Standing` it produced (the direct fix for "only first
 * place is tracked"), the findings it recorded (grouped by kind), the pre-registration written before
 * it ran, and the model's review written after -- see this module's docstring on why the plan and the
 * review are kept visually distinct. */
function GenerationDetailView({
  generation,
  detail,
}: {
  generation: number;
  detail: DetailState | undefined;
}) {
  const { t } = useT();
  if (!detail || detail.phase === "loading") {
    return <div className="placeholder">{t("competition.generations.detail.loading", { n: generation })}</div>;
  }
  if (detail.phase === "error") {
    return <div className="callout callout-danger">{detail.message}</div>;
  }
  const { outcome, plan_markdown, review } = detail.data;

  const findingsByKind = new Map<FindingKind, Finding[]>();
  for (const f of outcome.findings) {
    const list = findingsByKind.get(f.kind) ?? [];
    list.push(f);
    findingsByKind.set(f.kind, list);
  }

  return (
    <div className="comp-gens-detail">
      <StandingsTable generation={generation} standings={outcome.standings} review={review} />

      <div className="comp-gens-detail-section">
        <h4 className="comp-loop-subheading">{t("competition.generations.detail.findingsByKind")}</h4>
        {findingsByKind.size === 0 ? (
          <div className="placeholder">{t("competition.generations.detail.noFindings")}</div>
        ) : (
          Array.from(findingsByKind.entries()).map(([kind, findings]) => (
            <div key={kind} className="comp-gens-finding-group">
              <span className="badge comp-loop-finding-badge">
                {findingKindLabel(kind)} ({findings.length})
              </span>
              <ScrollRegion size="sm" label={`${findingKindLabel(kind)} (${findings.length})`}>
                <ul className="comp-loop-findings-list">
                  {findings.map((f, i) => (
                    <li key={i} className="comp-loop-finding-item">
                      <span className="comp-loop-finding-summary">{f.summary}</span>
                    </li>
                  ))}
                </ul>
              </ScrollRegion>
            </div>
          ))
        )}
      </div>

      {plan_markdown && (
        <details className="comp-gens-detail-section">
          <summary className="comp-loop-subheading comp-gens-plan-summary">
            {t("competition.generations.detail.planSummary")}
          </summary>
          {/* `comp-gens-plan-text` keeps its own font/background/padding/`white-space: pre-wrap` --
              those stay on the `<pre>` itself rather than moving to `ScrollRegion`'s wrapping `<div>`,
              since `white-space` is a property the `<pre>` element's own UA stylesheet sets explicitly
              (not merely inherits), so a value declared only on an ancestor would lose to it and the
              text would stop wrapping. `ScrollRegion` only supplies the bound + scroll; the box
              styling is unchanged. */}
          <ScrollRegion size="sm" label={t("competition.generations.detail.planSummary")}>
            <pre className="comp-gens-plan-text">{plan_markdown}</pre>
          </ScrollRegion>
        </details>
      )}

      <ReviewView review={review} />
    </div>
  );
}

/** Every `Standing` the generation produced, ranked or not, eligible or not -- ineligible rows stay on
 * screen, visibly de-emphasised via the existing `.comp-ineligible-row`/`.comp-ineligible-chip`
 * treatment `Competition.css` already defines for the leaderboard, never hidden. A per-candidate review
 * note (joined by `genome_id`) renders inline on its row when present, since a note with no candidate
 * to attach to names nothing a reader could act on. */
function StandingsTable({
  generation,
  standings,
  review,
}: {
  generation: number;
  standings: Standing[];
  review: GenerationReview | null;
}) {
  const { t } = useT();
  const notesByGenome = new Map((review?.per_candidate ?? []).map((c) => [c.genome_id, c]));
  if (standings.length === 0) {
    return <div className="placeholder">{t("competition.generations.standings.empty")}</div>;
  }
  return (
    <ScrollRegion size="md" label={t("competition.generations.row.genLabel", { n: generation })}>
      <div className="table-wrap">
        <table className="data-table comp-gens-standings-table">
          <thead>
            <tr>
              <th>{t("competition.generations.standings.col.rank")}</th>
              <th>{t("competition.generations.standings.col.name")}</th>
              <th>{t("competition.generations.standings.col.eligible")}</th>
              <th>{t("competition.generations.standings.col.windowsRun")}</th>
              <th>{t("competition.generations.standings.col.selectionMedian")}</th>
              <th>{t("competition.generations.standings.col.worstWindow")}</th>
              <th>{t("competition.generations.standings.col.hitRate")}</th>
              <th>
                {t("competition.generations.standings.col.holdoutMedian")}
                <span className="comp-loop-holdout-note">{t("competition.loop.holdoutNeverUsedNote")}</span>
              </th>
              <th>{t("competition.generations.standings.col.trades")}</th>
              <th>{t("competition.generations.standings.col.qValue")}</th>
            </tr>
          </thead>
          <tbody>
            {standings.map((s) => {
                const note = notesByGenome.get(s.genome_id);
                return (
                  <tr key={s.genome_id} className={s.eligible ? undefined : "comp-ineligible-row"}>
                    <td>{s.rank}</td>
                    <td>
                      <span className="comp-card-name">{s.display_name}</span>
                      <span className="tile-hint"> {s.agent_id}</span>
                      {!s.eligible && (
                        <span className="badge comp-ineligible-chip">{t("competition.ineligibleBadge")}</span>
                      )}
                      {note && (
                        <div className="comp-gens-review-note">
                          <StatusPill
                            tone={note.keep ? "ok" : "bad"}
                            label={
                              note.keep
                                ? t("competition.generations.standings.keep")
                                : t("competition.generations.standings.drop")
                            }
                          />{" "}
                          {note.note}
                        </div>
                      )}
                    </td>
                    <td>
                      {s.eligible
                        ? t("competition.generations.standings.yes")
                        : t("competition.generations.standings.no")}
                    </td>
                    <td className="comp-num">{s.windows_run}</td>
                    <td className={`comp-num ${fractionTone(s.median_excess)}`}>
                      {formatSignedPctFraction(s.median_excess)}
                    </td>
                    <td className={`comp-num ${fractionTone(s.worst_excess)}`}>
                      {formatSignedPctFraction(s.worst_excess)}
                    </td>
                    <td className="comp-num">
                      {s.hit_rate !== null ? `${(s.hit_rate * 100).toFixed(1)}%` : "—"}
                    </td>
                    <td className={`comp-num comp-gens-holdout-cell ${fractionTone(s.holdout_median_excess)}`}>
                      {formatSignedPctFraction(s.holdout_median_excess)}
                    </td>
                    <td className="comp-num">{formatIntOrDash(s.total_trades)}</td>
                    <td className="comp-num">{formatQValue(s.q_value)}</td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>
    </ScrollRegion>
  );
}


/** Translated per-call rather than a static `Record` -- module-private (never imported elsewhere), so
 * unlike `PURPOSE_LABELS` in `api/competition.ts` there is no out-of-scope consumer indexing it by
 * shape, and a function reads the catalog fresh on every render. */
function verdictLabel(verdict: GenerationReview["verdict"], t: (key: MessageKey) => string): string {
  switch (verdict) {
    case "promising":
      return t("competition.verdict.promising");
    case "inconclusive":
      return t("competition.verdict.inconclusive");
    case "exhausted":
      return t("competition.verdict.exhausted");
    case "broken":
      return t("competition.verdict.broken");
    default: {
      const _exhaustive: never = verdict;
      void _exhaustive;
      return String(verdict);
    }
  }
}

/** The model's review, when one exists. A `null` review renders one plain sentence saying so -- never
 * an empty box, which would read as "there was a review and it had nothing to say" rather than the
 * true state, "no model has looked at this generation yet." Amendments render inside a `.callout-warn`:
 * the loop retuning its own configuration is the kind of change that should catch a reader's eye, not
 * blend into the surrounding prose. */
function ReviewView({ review }: { review: GenerationReview | null }) {
  const { t } = useT();
  if (!review) {
    return (
      <div className="comp-gens-detail-section">
        <h4 className="comp-loop-subheading">{t("competition.generations.review.heading")}</h4>
        <div className="placeholder">{t("competition.generations.review.none")}</div>
      </div>
    );
  }
  const { direction, amendments } = review;
  const hasDirection =
    direction.headline ||
    direction.hypotheses.length > 0 ||
    direction.focus_symbols.length > 0 ||
    direction.avoid_symbols.length > 0 ||
    direction.emphasise_disciplines.length > 0 ||
    direction.retire_disciplines.length > 0;
  return (
    <div className="comp-gens-detail-section">
      <h4 className="comp-loop-subheading">{t("competition.generations.review.heading")}</h4>
      <div className="comp-gens-review-head">
        <StatusPill tone={verdictTone(review.verdict)} label={verdictLabel(review.verdict, t)} />
        {review.shape && <span className="tile-hint">{review.shape}</span>}
      </div>
      {review.post_mortem && <p className="comp-gens-postmortem">{review.post_mortem}</p>}

      {hasDirection && (
        <div className="comp-gens-direction">
          <span className="comp-loop-goal-display-label">{t("competition.generations.review.direction")}</span>
          {direction.headline && <p className="comp-gens-direction-headline">{direction.headline}</p>}
          {direction.hypotheses.length > 0 && (
            <ul className="comp-gens-direction-list">
              {direction.hypotheses.map((h, i) => (
                <li key={i}>{h}</li>
              ))}
            </ul>
          )}
          <div className="comp-gens-direction-tags">
            {direction.focus_symbols.length > 0 && (
              <span>{t("competition.generations.review.focus", { list: direction.focus_symbols.join(", ") })}</span>
            )}
            {direction.avoid_symbols.length > 0 && (
              <span>{t("competition.generations.review.avoid", { list: direction.avoid_symbols.join(", ") })}</span>
            )}
            {direction.emphasise_disciplines.length > 0 && (
              <span>
                {t("competition.generations.review.emphasise", {
                  list: direction.emphasise_disciplines.join(", "),
                })}
              </span>
            )}
            {direction.retire_disciplines.length > 0 && (
              <span>
                {t("competition.generations.review.retire", { list: direction.retire_disciplines.join(", ") })}
              </span>
            )}
          </div>
        </div>
      )}

      {amendments.length > 0 && (
        <div className="callout callout-warn comp-gens-amendments">
          <span className="comp-loop-goal-display-label">
            {t("competition.generations.review.amendmentsHeading")}
          </span>
          <ul className="comp-gens-amendments-list">
            {amendments.map((a, i) => (
              <li key={i}>
                <span className="comp-card-rule-label">{a.field}</span>
                <span className="comp-gens-amendment-value">{JSON.stringify(a.value)}</span>
                <span className="comp-gens-amendment-reason">{a.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// --- trend: compact per-aspect sparklines, one purpose at a time -----------------------------------

/** Turns a `DecimalString` into a plotting coordinate only -- never displayed as text. Every number a
 * reader actually reads on this panel goes through `formatSignedPctFraction`/`formatPctFraction`/
 * `formatPctPoints` on the raw string; this function exists solely because an SVG `points` attribute
 * needs real numbers to place pixels, and pixel placement is not a claim about precision the way a
 * printed digit is. */
function toPlotNumber(value: DecimalString): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

interface TrendPoint {
  generation: number;
  value: number;
}

/** One inline SVG sparkline -- no charting library (none is a dependency of this project; see
 * `package.json`). A flat, muted line rather than an empty chart when there are fewer than two points,
 * since a "trend" of zero or one point is not a trend. */
function Sparkline({ points, zeroLine }: { points: TrendPoint[]; zeroLine?: boolean }) {
  const { t } = useT();
  const width = 240;
  const height = 48;
  if (points.length < 2) {
    return <div className="placeholder comp-gens-sparkline-empty">{t("competition.generations.trend.notEnough")}</div>;
  }
  const values = points.map((p) => p.value);
  const min = Math.min(...values, zeroLine ? 0 : Infinity);
  const max = Math.max(...values, zeroLine ? 0 : -Infinity);
  const span = max - min || 1;
  const xStep = width / (points.length - 1);
  const coords = points.map((p, i) => {
    const x = i * xStep;
    const y = height - ((p.value - min) / span) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const zeroY = height - ((0 - min) / span) * height;
  const firstGeneration = points[0]?.generation ?? 0;
  const lastGeneration = points[points.length - 1]?.generation ?? 0;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="comp-gens-sparkline"
      role="img"
      aria-label={t("competition.generations.trend.ariaLabel", {
        count: points.length,
        first: firstGeneration,
        last: lastGeneration,
      })}
    >
      {zeroLine && (
        <line x1={0} y1={zeroY} x2={width} y2={zeroY} className="comp-gens-sparkline-zero" />
      )}
      <polyline points={coords.join(" ")} className="comp-gens-sparkline-line" fill="none" />
    </svg>
  );
}

/**
 * At-a-glance shape across generations for one purpose at a time: field median excess, holdout gap,
 * and gate clearance. `purpose` is the same selector driving the table above -- see this module's
 * docstring on why a sparkline drawn across mixed purposes would compare generations that were never
 * in the same competition. The lane is restated here in the heading, not left implicit, since this is
 * the one section where mixing it up silently produces a plausible-looking but meaningless line.
 */
function GenerationTrends({
  purpose,
  phase,
  message,
  generations,
}: {
  purpose: Purpose;
  phase: FetchPhase;
  message: string | null;
  generations: GenerationSummary[];
}) {
  const { t } = useT();
  const ascending = useMemo(
    () => [...generations].sort((a, b) => a.generation - b.generation),
    [generations],
  );

  const medianExcessPoints: TrendPoint[] = ascending
    .filter((g) => g.field.median_excess !== null)
    .map((g) => ({ generation: g.generation, value: toPlotNumber((g.field.median_excess as StatSummary).median) }));

  const holdoutGapPoints: TrendPoint[] = ascending
    .filter((g) => g.field.holdout_gap_pp !== null)
    .map((g) => ({ generation: g.generation, value: toPlotNumber((g.field.holdout_gap_pp as StatSummary).median) }));

  const gateClearancePoints: TrendPoint[] = ascending
    .filter((g) => g.gate.eligible > 0)
    .map((g) => ({ generation: g.generation, value: g.gate.cleared / g.gate.eligible }));

  return (
    <div className="comp-gens-trends">
      <h4 className="comp-loop-subheading">
        <Trans
          k="competition.generations.trend.heading"
          values={{
            purpose: purposeLabel(purpose),
            note: (
              <span className="comp-loop-holdout-note">{t("competition.generations.trend.headingNote")}</span>
            ),
          }}
        />
      </h4>
      <p className="comp-loop-form-hint">{t("competition.generations.trend.hint")}</p>
      {phase === "loading" && <div className="placeholder">{t("competition.generations.trend.loading")}</div>}
      {phase === "error" && (
        <div className="callout callout-danger">{message ?? t("competition.generations.errors.trend")}</div>
      )}
      {phase === "loaded" && (
        <div className="comp-gens-trend-grid">
          <div className="comp-gens-trend-tile">
            <span className="label">{t("competition.generations.trend.medianExcess")}</span>
            <Sparkline points={medianExcessPoints} zeroLine />
          </div>
          <div className="comp-gens-trend-tile">
            <span className="label">{t("competition.generations.trend.holdoutGap")}</span>
            <Sparkline points={holdoutGapPoints} zeroLine />
          </div>
          <div className="comp-gens-trend-tile">
            <span className="label">{t("competition.generations.trend.gateClearance")}</span>
            <Sparkline points={gateClearancePoints} />
          </div>
        </div>
      )}
    </div>
  );
}
