/**
 * The Competition tab's orientation levels: four stacked sections, coarse to fine, that sit in front
 * of the dense Leaderboard table (rendered by `LeaderboardSection` directly below this component in
 * the merged "Rounds" view -- see `Competition.tsx`) rather than replacing it. The two used to be
 * separate tabs sharing the same round's data under two different round pickers; they are now one
 * view with one picker (this component's own `RoundPicker`), the table simply continuing where this
 * component's own window strip leaves off.
 *
 *  1. **This round** -- the round picker, grouped into rounds that were actually scored and rounds
 *     that are a written record only (`RoundOrientationPanel`), then -- for whichever round is
 *     selected -- its own `label` sentence (the question the round asked) and the window set it ran.
 *     No figures here at all: this level exists to say *what* is being looked at before any number
 *     is shown, which is the ordering the owner asked for after the tab shipped a bare "median excess
 *     +24.65%" with nothing saying what it was a median *of* or what it was excess *over*.
 *  2. **Programme scale** -- a tile row over every round directory the backend knows about
 *     (`rounds`), regardless of which one is selected: how many rounds exist, how many produced
 *     results, a peak agent-roster figure, the union of windows any scored round has covered, and
 *     the newest round that actually has results.
 *  3. **This round's numbers** -- for `selectedRoundId`: eligibility gate, best/median performer, SPY's
 *     own median return over the round's comparable windows. Every figure here carries its meaning
 *     inline (what it is measured against, and what it does not tell you) rather than sitting as a
 *     bare percentage -- see the noise-floor block below.
 *  4. **Window detail** -- a compact per-window strip for the same round: SPY's return, the best
 *     card's excess, and how many cards ran, one row per window. This flows directly into the full
 *     Leaderboard table rendered right below it in the merged view, not a replacement for it.
 *
 * **Why level 1 comes before level 2, not after.** Level 2 (`ProgrammeScalePanel`) answers "how big is
 * this programme"; level 1 answers "what round am I even looking at, and what did it ask". A reader
 * who has not yet been told which round's numbers they are about to see gets no benefit from a
 * programme-wide scale tile row first -- orientation, then scale, then the numbers those two frame.
 *
 * **The `has_results: false` defect this component exists partly to fix.** Some round directories are
 * a written record only -- a `SELECTION.md` or a `run.txt` and no `results/` tree at all -- so
 * `GET .../leaderboard` 404s for them by design, and the live bug was the page defaulting onto one of
 * them and rendering blank with no explanation. `RoundOrientationPanel` below groups such rounds into
 * their own labelled section in the picker (never mixed in with scored rounds, never marked merely
 * "still loading"), and once one is selected it renders a designed panel that says what it actually
 * is -- a written record, no run files, its narrative is above -- rather than an empty leaderboard
 * shape. `RoundStatsTiles`/`DetailSummaryPanel` below both short-circuit to nothing for such a round
 * *before* waiting on `leaderboardPhase` to turn `"error"` -- we already know from
 * `RoundSummary.has_results` that the fetch cannot succeed, so there is no reason to show a loading
 * spinner for it first, and no reason to repeat the orientation panel's own explanation a second time.
 *
 * **Rounds sort by `sequence`, never by `round_id` as a string.** `r13` collates before `r9`
 * lexicographically; `sequence` is the parsed ordinal the backend provides for exactly this reason.
 *
 * **Every margin against SPY states the noise floor it has to clear to mean anything.**
 * `strategy-program/PROTOCOL.md` section 7 measured what re-running one *identical* card under twelve
 * universe orderings alone does to its result: a 53.9-point spread, sigma 21.2 points, purely from
 * which order the universe array happened to be written in. A margin narrower than that has not been
 * shown to be anything but that noise, and the section says outright to "state the margin against that
 * floor explicitly, every time". `withinNoiseFloor` below is this page's one implementation of that
 * rule, and every tile or cell that shows a card's excess against SPY calls it and renders the caution
 * inline when it fires -- never as a separate legend the reader has to go find.
 *
 * **`median_excess` and the SPY-benchmark aggregates below are `null`-safe.** A card with no
 * measurable median is dropped from the best/median-performer computation rather than sorted as
 * though its excess were zero; if every row lacks one, both tiles render an em dash via literal `"—"`
 * or `formatSignedPctFraction(null)`, never `"0.00%"`. See `api/competition.ts`'s module docstring.
 *
 * **`per_window` is read only with `?.`/explicit presence checks below.** The "best card's excess"
 * column in the detail strip is computed only from rows that actually have an entry for that window;
 * a window nobody ran renders an em dash there, not a manufactured zero.
 *
 * **A `provenance_constrained` window is marked and excluded from cross-window aggregates.** It gets
 * a visible "not comparable" chip in the detail strip and is left out of the SPY-median computation
 * in the round-summary tiles (`comparableWindows` below) -- its per-window row itself still renders
 * (a reader can still see what happened *in* that window), it just never feeds a number that claims
 * to summarise *across* windows.
 *
 * **Never `parseFloat` a `DecimalString`.** `medianDecimalString` below sorts with the exported
 * `compareDecimalStrings` and picks the lower-middle element on a tie (no arithmetic averaging of two
 * decimal strings, which would require the same string-safe treatment `compareDecimalStrings` itself
 * gets) -- consistent with every other figure on this page, which is formatted, never computed on, in
 * this component. `withinNoiseFloor` is the same rule applied to a threshold comparison: it compares
 * against the fixed strings `"0.212"`/`"-0.212"` with `compareDecimalStrings`, never a parsed float.
 */
import { useMemo } from "react";

import {
  compareDecimalStrings,
  formatIntOrDash,
  formatSignedPctFraction,
  fractionTone,
  provenanceConstrainedNote,
  type LeaderboardResponse,
  type LeaderboardRow,
  type PerWindowResult,
  type RoundSummary,
  type WindowBenchmark,
} from "@/api/competition";
import type { DecimalString } from "@/api/client";
import { InfoNote } from "@/components/InfoNote";
import { ScrollRegion } from "@/components/ScrollPanel";
import Skeleton from "@/components/Skeleton";
import StatusPill from "@/components/StatusPill";
import Term from "@/components/Term";
import { useT, Trans } from "@/i18n";

import { roundOptionText } from "./roundOption";

import "./SummarySection.css";

type Phase = "loading" | "loaded" | "error";

export interface SummarySectionProps {
  rounds: RoundSummary[];
  roundsPhase: Phase;
  roundsMessage: string | null;
  selectedRoundId: string | null;
  onSelectRound: (roundId: string) => void;
  leaderboard: LeaderboardResponse | null;
  leaderboardPhase: Phase;
  leaderboardMessage: string | null;
  /** Open one agent's drill-down (the inline drawer rendered below the merged Rounds view). */
  onSelectAgent: (agentId: string) => void;
}

// --- shared helpers ---------------------------------------------------------------------------------

/** Newest-first by the backend's own parsed ordinal -- sorting `round_id` as a string puts `r9`
 * above `r13`, which is precisely the ordering defect this view exists to not repeat. */
function sortRoundsNewestFirst(rounds: RoundSummary[]): RoundSummary[] {
  return [...rounds].sort((a, b) => b.sequence - a.sequence);
}

/** Median of a list of `DecimalString`s without ever parsing one into a float. Sorts with
 * `compareDecimalStrings` and takes the lower-middle element on an even count -- a deliberate
 * simplification (a true even-count median would need to average two decimal strings, which needs
 * its own string-safe arithmetic this page has no call for elsewhere) rather than an approximation
 * that silently drifts through an IEEE double. */
function medianDecimalString(values: DecimalString[]): DecimalString | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort(compareDecimalStrings);
  return sorted[Math.floor((sorted.length - 1) / 2)] ?? null;
}

function hasMedianExcess(row: LeaderboardRow): row is LeaderboardRow & { median_excess: DecimalString } {
  return row.median_excess !== null;
}

/** NOT `cells.ts`'s `numCell`, despite the name it used to share with it: this one emits
 *  `summary-num`, not `comp-num`. Renamed when three identical copies of the other one were
 *  merged, because "same name, different behaviour" is worse than either duplication. */
function summaryNumCell(tone: "pos" | "neg" | "" = ""): string {
  return tone ? `num summary-num ${tone}` : "num summary-num";
}

// --- noise floor -------------------------------------------------------------------------------------
// See the module docstring's "Every margin against SPY..." paragraph for where this comes from.

/** Displayed alongside the caution text below -- kept as one named constant so the number in the
 *  prose and the number in the threshold below can never drift apart from each other. */
const NOISE_FLOOR_PP = 21.2;
const NOISE_FLOOR_UPPER: DecimalString = "0.212";
const NOISE_FLOOR_LOWER: DecimalString = "-0.212";

/** True when a margin's magnitude is smaller than the measured reordering-noise floor above --
 *  string comparison against fixed thresholds only, never a parsed float. `null` (never measured) is
 *  not "small"; it is simply not comparable, so this returns `false` and the caller's own null
 *  handling renders the usual em dash rather than a caution about a number that was never computed. */
function withinNoiseFloor(value: DecimalString | null): boolean {
  if (value === null) return false;
  return compareDecimalStrings(value, NOISE_FLOOR_UPPER) < 0 && compareDecimalStrings(value, NOISE_FLOOR_LOWER) > 0;
}

/** The inline caution this page owes every margin against SPY once it is smaller than the noise
 *  floor -- see the module docstring. Renders nothing when the margin clears the floor or was never
 *  measured (`withinNoiseFloor(null) === false`), so a tile that has nothing to caution about stays
 *  exactly as plain as it would be without this component. A function, not a module-level string
 *  constant, so it reads the catalog fresh on every call -- this component is private to this file
 *  (never indexed elsewhere), so unlike `PURPOSE_LABELS` in `api/competition.ts` there is no
 *  out-of-scope consumer to keep byte-compatible with a static shape.
 *
 *  No `title` tooltip here -- the full PROTOCOL.md §7 explanation (12 reorderings, 53.9pp spread,
 *  sigma 21.2) used to be duplicated as a hover tooltip on this span AND on `WindowDetailRow`'s own
 *  noise chip below, on top of the always-visible caveat paragraph above the window table. It now
 *  lives in exactly one place -- the `InfoNote` in `DetailSummaryPanel` -- so this stays the short,
 *  always-visible caution sentence only. */
function NoiseFloorCaution({ value }: { value: DecimalString | null }) {
  const { t } = useT();
  if (!withinNoiseFloor(value)) return null;
  return (
    <span className="summary-noise-caution">
      {t("competition.summary.noiseFloor.caution", { pp: NOISE_FLOOR_PP })}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Top level: SummarySection
// ---------------------------------------------------------------------------

export default function SummarySection({
  rounds,
  roundsPhase,
  roundsMessage,
  selectedRoundId,
  onSelectRound,
  leaderboard,
  leaderboardPhase,
  leaderboardMessage,
  onSelectAgent,
}: SummarySectionProps) {
  const sortedRounds = useMemo(() => sortRoundsNewestFirst(rounds), [rounds]);
  const selectedRound = useMemo(
    () => sortedRounds.find((r) => r.round_id === selectedRoundId) ?? null,
    [sortedRounds, selectedRoundId],
  );
  const leaderboardMatchesSelection =
    leaderboard !== null && selectedRoundId !== null && leaderboard.round_id === selectedRoundId;

  return (
    <>
      <RoundOrientationPanel
        sortedRounds={sortedRounds}
        roundsPhase={roundsPhase}
        roundsMessage={roundsMessage}
        selectedRoundId={selectedRoundId}
        selectedRound={selectedRound}
        onSelectRound={onSelectRound}
      />

      <ProgrammeScalePanel rounds={rounds} roundsPhase={roundsPhase} roundsMessage={roundsMessage} />

      <RoundStatsPanel
        selectedRoundId={selectedRoundId}
        selectedRound={selectedRound}
        leaderboard={leaderboardMatchesSelection ? leaderboard : null}
        leaderboardPhase={leaderboardPhase}
        leaderboardMessage={leaderboardMessage}
      />

      <DetailSummaryPanel
        selectedRound={selectedRound}
        leaderboard={leaderboardMatchesSelection ? leaderboard : null}
        leaderboardPhase={leaderboardPhase}
        leaderboardMessage={leaderboardMessage}
        onSelectAgent={onSelectAgent}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// 1. This round -- orientation: the picker, the question, the windows. No figures.
// ---------------------------------------------------------------------------

/** The round picker itself: one `<select>` with two `<optgroup>`s -- "Scored" and "Record only" --
 * rather than the two-tablist button wall this replaces. `<optgroup>` is the native equivalent of
 * the old two independent `role="tablist"` groups: a screen reader announces the group label on
 * entry the same way, and scored rounds still come first (the ones a reader usually wants) with
 * record-only rounds in their own group after, never interleaved. A record-only option is not
 * disabled -- choosing one is a decision a reader can still make (its Findings/Selection are worth
 * reading).
 *
 * **Option text is derived, never `label`.** See `roundOption.ts`: the authored labels are four
 * different naming schemes, some of them whole sentences, and a `<select>` full of sentences is a
 * list nobody can scan. The round's own question still renders in full directly below this picker
 * (`RoundOrientationPanel`'s "Question" block for a scored round, the record-only callout for one
 * without results), so nothing is lost by keeping it out of the control itself -- and a second muted
 * copy of the same sentence two lines above that block would be the same fact twice.
 *
 * **"No scored results" is a pill, not option text.** It used to ride along inside the option string
 * as a suffix, which made one option in the list twice the length of its neighbours to carry a fact
 * about the *selected* round. It now sits beside the select as a `neutral` pill (the tone for "not
 * applicable" per docs/COPY-STYLE.md), so it is stated once, about the round actually chosen. */
function RoundPicker({
  sortedRounds,
  roundsPhase,
  roundsMessage,
  selectedRoundId,
  onSelectRound,
}: {
  sortedRounds: RoundSummary[];
  roundsPhase: Phase;
  roundsMessage: string | null;
  selectedRoundId: string | null;
  onSelectRound: (roundId: string) => void;
}) {
  const { t, lang } = useT();
  const selectedRound = sortedRounds.find((r) => r.round_id === selectedRoundId) ?? null;
  if (roundsPhase === "loading") {
    return <Skeleton variant="text" rows={1} what={t("competition.summary.skeletonWhat.rounds")} />;
  }
  if (roundsPhase === "error") {
    return <div className="placeholder">{roundsMessage ?? t("competition.summary.roundsError")}</div>;
  }
  if (sortedRounds.length === 0) {
    // Deliberately distinct copy from `ProgrammeScalePanel`'s empty state just below -- that one
    // answers "has the programme ever produced a scored round" (it has not); this one is about the
    // one round this level needs to orient around, so it is the level that points at the fix. Phrased
    // differently from `Competition.tsx`'s own "No rounds have been run yet. Start one from Library
    // & Run." (Leaderboard tab) too -- same suggestion, not the same sentence repeated a third time.
    return <div className="placeholder">{t("competition.summary.noRoundsHint")}</div>;
  }

  const scored = sortedRounds.filter((r) => r.has_results);
  const recordOnly = sortedRounds.filter((r) => !r.has_results);

  return (
    <div className="summary-round-picker">
      <label className="bt-control-label summary-round-select-label" htmlFor="summary-round-select">
        {t("competition.leaderboard.roundFieldLabel")}
        <select
          id="summary-round-select"
          className="bt-entry-select summary-round-select"
          value={selectedRoundId ?? ""}
          onChange={(e) => onSelectRound(e.target.value)}
        >
          {scored.length > 0 && (
            <optgroup label={t("competition.summary.scoredLabel")}>
              {scored.map((r) => (
                <option key={r.round_id} value={r.round_id}>
                  {roundOptionText(r.round_id, lang)}
                </option>
              ))}
            </optgroup>
          )}
          {recordOnly.length > 0 && (
            <optgroup label={t("competition.summary.recordOnlyLabel")}>
              {recordOnly.map((r) => (
                <option key={r.round_id} value={r.round_id}>
                  {roundOptionText(r.round_id, lang)}
                </option>
              ))}
            </optgroup>
          )}
        </select>
      </label>
      {selectedRound !== null && !selectedRound.has_results && (
        <StatusPill tone="neutral" label={t("competition.summary.noScoredResultsPill")} />
      )}
    </div>
  );
}

function RoundOrientationPanel({
  sortedRounds,
  roundsPhase,
  roundsMessage,
  selectedRoundId,
  selectedRound,
  onSelectRound,
}: {
  sortedRounds: RoundSummary[];
  roundsPhase: Phase;
  roundsMessage: string | null;
  selectedRoundId: string | null;
  selectedRound: RoundSummary | null;
  onSelectRound: (roundId: string) => void;
}) {
  const { t } = useT();
  const knownEmpty = selectedRound !== null && !selectedRound.has_results;

  return (
    <div className="panel">
      <h2 className="section-heading">{t("competition.summary.thisRoundHeading")}</h2>
      <RoundPicker
        sortedRounds={sortedRounds}
        roundsPhase={roundsPhase}
        roundsMessage={roundsMessage}
        selectedRoundId={selectedRoundId}
        onSelectRound={onSelectRound}
      />

      {roundsPhase === "loaded" && sortedRounds.length > 0 && !selectedRoundId && (
        <div className="placeholder summary-panel-body">{t("competition.summary.pickRoundHint")}</div>
      )}

      {/* The designed record-only panel this component exists partly to add: a card with no run files
          used to render as a blank leaderboard shape once a 404 came back. This says outright what the
          round actually is -- a written note, not a scored measurement -- and points at where that
          note lives (the narrative card above this section, and the Findings tab) instead of leaving
          the reader looking at an empty table wondering whether something is broken. */}
      {selectedRoundId && knownEmpty && (
        <div className="callout callout-info summary-empty-round">
          <Trans
            k="competition.summary.recordOnlyExplain"
            values={{
              label: <strong>{selectedRound?.label}</strong>,
              selectionMd: <code>SELECTION.md</code>,
              runTxt: <code>run.txt</code>,
            }}
          />
        </div>
      )}

      {selectedRoundId && !knownEmpty && selectedRound && (
        <div className="summary-orientation-body">
          <span className="summary-orientation-label">{t("competition.summary.questionLabel")}</span>
          <p className="summary-orientation-question">{selectedRound.label}</p>
          <div className="summary-orientation-windows">
            <span className="summary-orientation-label">
              {/* First visible use of "windows" on this page -- each one is a non-overlapping test
                  period, the same independence `glossary.indep` defines, so the term rides the
                  first place a reader meets the word rather than every later repeat of it. */}
              <Term k="indep">{t("competition.summary.windowsRunLabel")}</Term>{" "}
              <span className="tile-hint">({formatIntOrDash(selectedRound.windows.length)})</span>
            </span>
            {selectedRound.windows.length === 0 ? (
              <p className="muted summary-orientation-no-windows">{t("competition.summary.noWindowsRecorded")}</p>
            ) : (
              <ScrollRegion
                size="md"
                label={t("competition.summary.windowsRunLabel")}
                className="summary-orientation-window-chips"
              >
                {selectedRound.windows.map((w) => (
                  <span key={w} className="badge summary-window-chip">
                    {w}
                  </span>
                ))}
              </ScrollRegion>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 2. Programme scale
// ---------------------------------------------------------------------------

interface ProgrammeStats {
  totalRounds: number;
  roundsWithResults: number;
  peakAgents: number;
  windowsCovered: number;
  newestWithResults: RoundSummary | null;
}

/** Computed only from `rounds` -- the only programme-wide data this component receives. `agents` on
 * `RoundSummary` is a per-round count, not a list of ids, so there is no way to de-duplicate agent
 * identities across rounds from this contract; `peakAgents` is the largest single round's roster
 * among scored rounds, labelled "peak roster" in the tile rather than "distinct agents" so the number
 * never claims a de-duplication this data cannot support. */
function computeProgrammeStats(rounds: RoundSummary[]): ProgrammeStats {
  const withResults = rounds.filter((r) => r.has_results);
  const windowSet = new Set<string>();
  for (const r of withResults) {
    for (const w of r.windows) windowSet.add(w);
  }
  const peakAgents = withResults.reduce((max, r) => Math.max(max, r.agents), 0);
  const newestWithResults = sortRoundsNewestFirst(withResults)[0] ?? null;
  return {
    totalRounds: rounds.length,
    roundsWithResults: withResults.length,
    peakAgents,
    windowsCovered: windowSet.size,
    newestWithResults,
  };
}

function ProgrammeScalePanel({
  rounds,
  roundsPhase,
  roundsMessage,
}: {
  rounds: RoundSummary[];
  roundsPhase: Phase;
  roundsMessage: string | null;
}) {
  const { t } = useT();
  const stats = useMemo(() => computeProgrammeStats(rounds), [rounds]);

  return (
    <div className="panel">
      <h2 className="section-heading">{t("competition.summary.programmeScaleHeading")}</h2>
      <p className="subtitle summary-panel-subtitle">{t("competition.summary.programmeScaleSubtitle")}</p>

      {roundsPhase === "loading" && (
        <Skeleton variant="tiles" rows={5} what={t("competition.summary.skeletonWhat.rounds")} />
      )}
      {roundsPhase === "error" && (
        <div className="placeholder">{roundsMessage ?? t("competition.summary.roundsError")}</div>
      )}
      {roundsPhase === "loaded" && rounds.length === 0 && (
        <div className="placeholder">{t("competition.summary.noRoundsRunYet")}</div>
      )}
      {roundsPhase === "loaded" && rounds.length > 0 && (
        <div className="tile-grid summary-tile-grid">
          <div className="tile">
            <span className="label">{t("competition.summary.tile.roundsRun")}</span>
            <span className="value value-emphasize">{formatIntOrDash(stats.totalRounds)}</span>
          </div>
          <div className="tile">
            <span className="label">{t("competition.summary.tile.producedResults")}</span>
            <span className="value value-emphasize">{formatIntOrDash(stats.roundsWithResults)}</span>
            <span className="tile-hint">
              {t("competition.summary.tile.producedResultsHint", { total: stats.totalRounds })}
            </span>
          </div>
          <div className="tile">
            <span className="label">{t("competition.summary.tile.agentsScored")}</span>
            <span className="value value-emphasize">{formatIntOrDash(stats.peakAgents)}</span>
            <span className="tile-hint">{t("competition.summary.tile.agentsScoredHint")}</span>
          </div>
          <div className="tile">
            <span className="label">{t("competition.summary.tile.windowsCovered")}</span>
            <span className="value value-emphasize">{formatIntOrDash(stats.windowsCovered)}</span>
            <span className="tile-hint">{t("competition.summary.tile.windowsCoveredHint")}</span>
          </div>
          <div className="tile">
            <span className="label">{t("competition.summary.tile.newestWithResults")}</span>
            <span className="value">{stats.newestWithResults?.label ?? "—"}</span>
            {!stats.newestWithResults && (
              <span className="tile-hint">{t("competition.summary.tile.newestNone")}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 3. This round's numbers -- every figure carries what it means inline.
// ---------------------------------------------------------------------------

function RoundStatsPanel({
  selectedRoundId,
  selectedRound,
  leaderboard,
  leaderboardPhase,
  leaderboardMessage,
}: {
  selectedRoundId: string | null;
  selectedRound: RoundSummary | null;
  leaderboard: LeaderboardResponse | null;
  leaderboardPhase: Phase;
  leaderboardMessage: string | null;
}) {
  const { t } = useT();
  // The orientation panel above already explains a round with no selection or no scored results --
  // this panel stays quiet rather than repeat the same message a second time (same pattern
  // `DetailSummaryPanel` below already used).
  if (!selectedRoundId) return null;
  if (!selectedRound) return null;
  if (!selectedRound.has_results) return null;

  if (leaderboardPhase === "loading") {
    return (
      <div className="panel">
        <h2 className="section-heading">{t("competition.summary.roundNumbersHeading")}</h2>
        <Skeleton variant="tiles" rows={6} what={t("competition.summary.skeletonWhat.roundNumbers")} />
      </div>
    );
  }
  if (leaderboardPhase === "error") {
    return (
      <div className="panel">
        <h2 className="section-heading">{t("competition.summary.roundNumbersHeading")}</h2>
        <div className="placeholder">{leaderboardMessage ?? t("competition.summary.roundResultsError")}</div>
      </div>
    );
  }
  if (!leaderboard) return null;

  return (
    <div className="panel">
      <h2 className="section-heading">{t("competition.summary.roundNumbersHeading")}</h2>
      <RoundStatsTiles round={selectedRound} leaderboard={leaderboard} />
    </div>
  );
}

function RoundStatsTiles({
  round,
  leaderboard,
}: {
  round: RoundSummary;
  leaderboard: LeaderboardResponse;
}) {
  const { t } = useT();
  const rows = leaderboard.rows;
  const eligibleCount = rows.filter((r) => r.eligible).length;

  const validRows = rows.filter(hasMedianExcess);
  const sortedByMedian = [...validRows].sort((a, b) =>
    compareDecimalStrings(b.median_excess, a.median_excess),
  );
  const best = sortedByMedian[0] ?? null;
  const medianPerformer =
    sortedByMedian.length > 0 ? sortedByMedian[Math.floor((sortedByMedian.length - 1) / 2)] : null;

  // A provenance_constrained window's universe was only knowable after the fact -- it cannot be
  // ranked against the others, so it is left out of this aggregate. See the module docstring.
  const comparableWindows = leaderboard.windows.filter((w) => !w.provenance_constrained);
  const benchmarkMedian = medianDecimalString(comparableWindows.map((w) => w.benchmark_return));

  return (
    <div className="summary-panel-body">
      <div className="tile-grid summary-tile-grid">
        <div className="tile">
          <span className="label">{t("competition.summary.tile.windows")}</span>
          <span className="value value-emphasize">{formatIntOrDash(round.windows.length)}</span>
          <span className="tile-hint">{t("competition.summary.tile.windowsHint")}</span>
        </div>
        <div className="tile">
          <span className="label">{t("competition.summary.tile.agents")}</span>
          <span className="value value-emphasize">{formatIntOrDash(round.agents)}</span>
          <span className="tile-hint">{t("competition.summary.tile.agentsHint")}</span>
        </div>
        <div className="tile">
          <span className="label">{t("competition.summary.tile.clearedGate")}</span>
          <span className="value value-emphasize">
            {formatIntOrDash(eligibleCount)} / {formatIntOrDash(rows.length)}
          </span>
          <span className="tile-hint">{t("competition.summary.tile.clearedGateHint")}</span>
        </div>
        <div className="tile">
          <span className="label">{t("competition.summary.tile.bestPerformer")}</span>
          <span className={`value ${summaryNumCell(fractionTone(best?.median_excess ?? null))}`}>
            {best ? `${best.display_name} ${formatSignedPctFraction(best.median_excess)}` : "—"}
          </span>
          <span className="tile-hint summary-tile-meaning">{t("competition.summary.tile.bestPerformerHint")}</span>
          <NoiseFloorCaution value={best?.median_excess ?? null} />
        </div>
        <div className="tile">
          <span className="label">{t("competition.summary.tile.medianPerformer")}</span>
          <span className={`value ${summaryNumCell(fractionTone(medianPerformer?.median_excess ?? null))}`}>
            {medianPerformer
              ? `${medianPerformer.display_name} ${formatSignedPctFraction(medianPerformer.median_excess)}`
              : "—"}
          </span>
          <span className="tile-hint summary-tile-meaning">{t("competition.summary.tile.medianPerformerHint")}</span>
          <NoiseFloorCaution value={medianPerformer?.median_excess ?? null} />
        </div>
        <div className="tile">
          <span className="label">{t("competition.summary.tile.spyMedianReturn")}</span>
          <span className={`value ${summaryNumCell(fractionTone(benchmarkMedian))}`}>
            {formatSignedPctFraction(benchmarkMedian)}
          </span>
          <span className="tile-hint summary-tile-meaning">{t("competition.summary.tile.spyMedianReturnHint")}</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 4. Window detail
// ---------------------------------------------------------------------------

function DetailSummaryPanel({
  selectedRound,
  leaderboard,
  leaderboardPhase,
  leaderboardMessage,
  onSelectAgent,
}: {
  selectedRound: RoundSummary | null;
  leaderboard: LeaderboardResponse | null;
  leaderboardPhase: Phase;
  leaderboardMessage: string | null;
  onSelectAgent: (agentId: string) => void;
}) {
  const { t } = useT();
  // The orientation panel above already explains a round with no selection or no scored results --
  // this panel stays quiet rather than repeat the same message a second time.
  if (!selectedRound) return null;
  if (!selectedRound.has_results) return null;

  if (leaderboardPhase === "loading") {
    return (
      <div className="panel">
        <h2 className="section-heading">{t("competition.summary.windowDetailHeading")}</h2>
        <Skeleton variant="rows" rows={4} what={t("competition.summary.skeletonWhat.windowDetail")} />
      </div>
    );
  }
  if (leaderboardPhase === "error") {
    return (
      <div className="panel">
        <h2 className="section-heading">{t("competition.summary.windowDetailHeading")}</h2>
        <div className="placeholder">{leaderboardMessage ?? t("competition.summary.windowDetailError")}</div>
      </div>
    );
  }
  if (!leaderboard) return null;

  const windows = leaderboard.windows;

  return (
    <div className="panel">
      <h2 className="section-heading">
        {t("competition.summary.windowDetailForRound", { roundId: leaderboard.round_id })}
      </h2>
      {windows.length === 0 ? (
        <div className="placeholder">{t("competition.summary.noWindowsRecorded")}</div>
      ) : (
        <>
          {/* The one place this page states the noise-floor caveat in full -- see `NoiseFloorCaution`'s
              docstring above. The short sentence stays always visible (what "best card excess" means,
              and the {pp}pp threshold below which it is marked); the full PROTOCOL.md §7 measurement
              behind that threshold sits one click away rather than duplicated as a hover tooltip on
              every badge that references it. */}
          <InfoNote
            className="summary-window-table-note"
            summary={
              <Trans
                k="competition.summary.windowTableNote"
                values={{
                  pp: NOISE_FLOOR_PP,
                  noiseChip: (
                    <span className="summary-noise-chip-inline">{t("competition.summary.noiseChip")}</span>
                  ),
                }}
              />
            }
          >
            {t("competition.summary.noiseFloor.title")}
          </InfoNote>
          <ScrollRegion
            size="md"
            label={t("competition.summary.windowDetailForRound", { roundId: leaderboard.round_id })}
          >
            <div className="table-wrap">
              <table className="data-table summary-window-table">
                <thead>
                  <tr>
                    <th scope="col">{t("competition.summary.col.window")}</th>
                    <th scope="col" className="num">
                      {t("competition.summary.col.spyReturn")}
                    </th>
                    <th scope="col" className="num">
                      {t("competition.summary.col.bestCardExcess")}
                    </th>
                    <th scope="col" className="num">
                      {t("competition.summary.col.cardsRun")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {windows.map((w) => (
                    <WindowDetailRow key={w.window} window={w} rows={leaderboard.rows} onSelectAgent={onSelectAgent} />
                  ))}
                </tbody>
              </table>
            </div>
          </ScrollRegion>
        </>
      )}
    </div>
  );
}

interface BestInWindow {
  row: LeaderboardRow;
  cell: PerWindowResult;
}

function WindowDetailRow({
  window: w,
  rows,
  onSelectAgent,
}: {
  window: WindowBenchmark;
  rows: LeaderboardRow[];
  onSelectAgent: (agentId: string) => void;
}) {
  const { t } = useT();
  // `per_window` is a partial map -- a card that did not run this window has no entry at all, so this
  // only ever looks at rows that actually have one, never a `?? someDefault` that would manufacture a
  // result for a window the card never touched.
  let best: BestInWindow | null = null;
  let ranCount = 0;
  for (const row of rows) {
    const cell = row.per_window[w.window];
    if (!cell) continue;
    ranCount += 1;
    if (!best || compareDecimalStrings(cell.excess, best.cell.excess) > 0) {
      best = { row, cell };
    }
  }

  return (
    <tr className={w.provenance_constrained ? "summary-constrained-row" : ""}>
      <td>
        {w.window}
        {w.provenance_constrained && (
          <span className="badge summary-provenance-chip" title={provenanceConstrainedNote()}>
            {t("competition.provenanceConstrained.chip")}
          </span>
        )}
      </td>
      <td className={summaryNumCell(fractionTone(w.benchmark_return))}>
        {formatSignedPctFraction(w.benchmark_return)}
      </td>
      <td className={summaryNumCell(best ? fractionTone(best.cell.excess) : "")}>
        {best ? (
          <>
            <button
              type="button"
              className="summary-best-card-btn"
              onClick={() => onSelectAgent((best as BestInWindow).row.agent_id)}
            >
              {best.row.display_name} {formatSignedPctFraction(best.cell.excess)}
            </button>
            {withinNoiseFloor(best.cell.excess) && (
              <span className="summary-noise-chip">{t("competition.summary.noiseChip")}</span>
            )}
          </>
        ) : (
          "—"
        )}
      </td>
      <td className={summaryNumCell()}>{formatIntOrDash(ranCount)}</td>
    </tr>
  );
}
