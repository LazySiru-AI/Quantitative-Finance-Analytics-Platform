/**
 * The Competition tab: a dashboard over the strategy-competition framework.
 *
 * Five sections, switched with the `.view-tabs` pattern `Ticker.tsx` established and `Portfolio.tsx`
 * reuses for its own view toggle. They are ordered coarse-to-fine on purpose: the tab used to open
 * straight onto the Leaderboard's twenty-column table with nothing to orient against, which is the
 * complaint this ordering answers.
 *
 *  0. **Rounds** (default, `View`'s `"summary"`) — this round's own question and window set first
 *     (what is even being looked at), then programme scale across all rounds, then this round's
 *     numbers, then a per-window strip (`competition/SummarySection`) -- flowing directly into the
 *     full ranked Leaderboard table (`competition/LeaderboardSection`) rendered right below it, one
 *     round picker driving both. Summary and Leaderboard used to be two separate tabs over the same
 *     round's data (docs/STRATEGY-AGENT-UX-ANALYSIS.md §A2); they are now one view, and
 *     `LeaderboardSection` no longer carries a round picker of its own, so `SummarySection`'s
 *     grouped picker is the only one on screen. `SummarySection`'s picker groups scored rounds
 *     separately from record-only ones (a written `SELECTION.md`/`run.txt` with no run files), and
 *     picking a record-only round renders a designed panel saying so rather than a 404-shaped blank --
 *     the same distinction `defaultRoundId` below exists to protect the picker's *default* against.
 *     The table itself pins SPY's own result as a row so "excess" always has something to be excess
 *     *of* right there in the table, not only inside a drill-down. Clicking a row opens the **Agent**
 *     drill-down -- per-window return vs. SPY and the trades that produced it, sorted by
 *     `abs(contribution)` -- inline underneath the table itself (`comp-agent-drawer`), not on a
 *     separate tab: an "Agent"/"Card" tab used to sit here in the rail and showed nothing but a
 *     "select a card" placeholder until a row was clicked elsewhere, which is a dead tab a reader
 *     could open and find empty. The drawer closes with its own button rather than a tab switch.
 *  1. **Findings** — what the round wrote down, with the items it left *open* pinned at the top.
 *     This is the agenda for the next round (`competition/FindingsSection`). Not gated on
 *     `has_results`: rounds 6-10 and 12 have a `SELECTION.md` and no run files at all, and those are
 *     among the most useful records to read when planning what to run next.
 *  2. **Library & Run** — the four tiers of the strategy library, and the form that launches a new
 *     round with live progress. Reachable from the tab rail *and* from the "Run a round" button in
 *     the page header, since launching a round is the one action here that changes anything.
 *  3. **Selection** — the gate tables (A, L, C) and the resulting desk roster for the round currently
 *     picked in the Rounds view's own round selector (this view adds no second picker). The roster
 *     comes first since it is the answer; the gates and full ranking are the working behind it. A
 *     seat's `seated_by` is never allowed to read as "won on the rule" when it was not — `"outside-
 *     competition"`/`"owner-override"` seats get their own visible marking, not the same badge a
 *     rule-won seat gets. `notes` is rendered verbatim and prominently: it carries the evidence's own
 *     limitations, and the page misrepresents the decision without it.
 *
 * **The round picker must never default to a round with no results.** Seven of the thirteen round
 * directories hold only a `SELECTION.md` or a `run.txt`, so `GET .../leaderboard` answers 404 for
 * them by design. This page used to seed its picker with `rounds[0]` — and because the endpoint
 * sorted round ids as *strings*, where `"r9" > "r13"`, `rounds[0]` was `r9-2026-08`, one of the
 * empty ones. The tab opened onto a 404 and rendered nothing at all. `orderRounds`/`defaultRoundId`
 * below are the fix on this side; `has_results` and `sequence` on `RoundSummary` are the fix on the
 * server's. Both are kept, deliberately: either one alone would have prevented the blank page, and
 * the failure was bad enough to be worth belt and braces.
 *
 * Every fetch here owns its own `FetchPhase` (`"loading" | "loaded" | "error"`), the same pattern
 * `Macro.tsx`/`Thesis.tsx` use — one bad request never blanks the rest of the page.
 *
 * **`null` is not zero anywhere in this contract.** `median_excess`, `worst_excess`,
 * `adjusted_excess` all come back `null` for a card that could not be measured, and `api/competition
 * .ts`'s `formatPctFraction`/`formatSignedPctFraction` render that as an em dash — never a bare
 * template string that would print `"0.00%"` for a figure that was never computed.
 *
 * **A trade's `unrealised: true` is a mark, not money taken.** `TradesTable` below labels it
 * inline rather than folding it into an ordinary P&L column — see the module docstring in
 * `api/competition.ts`.
 */
import { useEffect, useState } from "react";

import { ApiRequestError } from "@/api/client";
import { formatFetchError as errorMessage, useFetch, type FetchPhase } from "@/hooks/useFetch";
import { useTabParam } from "@/hooks/useTabParam";
import { useT, type MessageKey } from "@/i18n";
import {
  competitionApi,
  isTerminalJobStatus,
  type AgentDetailResponse,
  type CreateJobRequest,
  type FindingsResponse,
  type JobStatus,
  type LeaderboardResponse,
  type LibraryResponse,
  type NextRoundBriefing,
  type Purpose,
  type RankBy,
  type RoundNarrative,
  type RoundSummary,
  type SelectionResponse,
  type WindowCatalogueEntry,
} from "@/api/competition";
import {
  buildLoopConfigFromDraft,
  describeStartLoopError,
  DEFAULT_LOOP_FORM_DRAFT,
  evolutionApi,
  isLoopActive,
  isLoopNotStarted,
  loopStateLabel,
  type LoopConfig,
  type LoopFormDraft,
  type LoopStatus,
} from "@/api/evolution";
import StatusPill from "@/components/StatusPill";

import AgentSection from "./competition/AgentSection";
import FindingsSection from "./competition/FindingsSection";
import LeaderboardSection from "./competition/LeaderboardSection";
import LibrarySection from "./competition/LibrarySection";
import LoopPanel, { loopStateTone } from "./competition/LoopPanel";
import NextRoundPanel from "./competition/NextRoundPanel";
import PendingSeatsPanel from "./competition/PendingSeatsPanel";
import RoundNarrativeCard from "./competition/RoundNarrativeCard";
import SelectionSection from "./competition/SelectionSection";
import SummarySection from "./competition/SummarySection";

import "./Competition.css";

/**
 * Which section is on screen. Ordered here coarse-to-fine, the same order the tab rail renders in:
 * `"summary"` (labelled "Rounds" in the rail) is the merged orientation-plus-ranking view -- programme
 * scale -> this round -> per-window strip -> the full leaderboard table, one round picker driving all
 * of it -- `"findings"` is what the round left open for the next one, `"selection"` is who got a seat,
 * and `"library"` is the card shelf plus the run form.
 *
 * **`"summary"` and `"leaderboard"` used to be two tabs over the same round's data** (docs/STRATEGY-
 * AGENT-UX-ANALYSIS.md §A2: the Summary window strip and the Leaderboard are the same round's numbers,
 * so they should not require two tabs and two independent round pickers to see). They are now rendered
 * together under the single `"summary"` view -- `SummarySection` first, then `LeaderboardSection`
 * immediately below it. `LeaderboardSection` lost its own round `<select>` and its own copies of the
 * `/rounds` loading/error/empty placeholders in the merge, because `SummarySection` already renders
 * all four directly above on the same page; what it still reports is its own leaderboard fetch. So
 * one picker drives the page -- and `"leaderboard"` has no entry in `VIEW_TABS` any more. The
 * `View` union keeps the `"leaderboard"` member (nothing downstream needs it removed, and `view` simply
 * never becomes it), the same reasoning `"agent"` below already established.
 *
 * `"agent"` (one card's trades) is a member of this union with no matching tab in `VIEW_TABS`: it
 * used to be its own tab that showed nothing until a leaderboard row was clicked elsewhere, a dead
 * tab a reader could open and find empty. `selectedAgentId` now drives an inline drawer rendered
 * under the merged `"summary"` view's leaderboard table instead (see that view's own render block
 * below), so `view` itself never actually becomes `"agent"` any more -- the member stays in the union
 * only because nothing downstream (the `AgentSection` fetch effect, `agentPhase`/`agentDetail` state)
 * needs it removed, and removing it would be a larger, unrelated cleanup.
 *
 * `"summary"` is the default rather than opening straight onto the 20-column table with no
 * orientation, which is the concrete complaint this restructure answers.
 *
 * `"loop"` is the seventh view, added alongside the six above: the endless competition/feedback loop
 * that proposes, runs, scores, and promotes generations unattended until stopped
 * (`competition/LoopPanel`). Its tab picks up a live indicator while the loop is running/stopping --
 * see `isLoopActive` from `api/evolution.ts` and the tab rail below.
 *
 * `"review"` is the eighth view, sat directly after `"loop"` in the rail: the human review queue
 * (`competition/PendingSeatsPanel`) where a person decides whether a loop-promoted card gets shelved,
 * rejected, seated on the paper desk, or retired. It used to be mounted at the bottom of `LoopPanel`,
 * under the loop's own form and `GenerationsPanel` -- which buried the one place a human decision
 * happens behind loop machinery a reviewer has no reason to read first (docs/STRATEGY-AGENT-UX-
 * ANALYSIS.md §A2). `PendingSeatsPanel` is fully self-contained (fetches its own queue data, takes no
 * props), so this tab renders it directly with nothing wired down from here.
 */
type View =
  | "summary"
  | "leaderboard"
  | "agent"
  | "findings"
  | "selection"
  | "library"
  | "loop"
  | "review";

/** Matches the brief's "poll roughly every 2000ms" -- not tied to anything server-side. */
const POLL_INTERVAL_MS = 2000;

/** The tab rail, coarse-to-fine, in render order. A table rather than six copy-pasted `<button>`s:
 * the old rail repeated the same nine lines per tab, and adding two more sections to it by hand is
 * how one of them ends up with the wrong `aria-selected`.
 *
 * `"leaderboard"` has no entry here on purpose. It used to be its own tab, over the exact same
 * round's data `"summary"` (labelled "Rounds") already shows -- docs/STRATEGY-AGENT-UX-ANALYSIS.md
 * §A2 called this out directly. `LeaderboardSection` now renders directly under `SummarySection` in
 * the `view === "summary"` block below, sharing that block's single round picker, so there is nothing
 * left for a second tab button to switch to.
 *
 * `"agent"` has no entry here either, for the same underlying reason one level down: it used to be
 * its own tab (`competition.tabs.agent`, "Card") that showed nothing but a "select a card" placeholder
 * until a leaderboard row was clicked -- a dead tab a reader could open and find empty. `AgentSection`
 * now renders inline under the leaderboard table in the merged `"summary"` view instead (see that
 * view's own render block below), so there is nothing left for a tab button to open either. The
 * `View` union members and `selectedAgentId` state stay -- both are still exactly what drives which
 * agent's detail is fetched and shown, only *where* it renders changed. */
const VIEW_TABS: { id: View; labelKey: MessageKey }[] = [
  { id: "summary", labelKey: "competition.tabs.summary" },
  { id: "findings", labelKey: "competition.tabs.findings" },
  { id: "selection", labelKey: "competition.tabs.selection" },
  { id: "library", labelKey: "competition.tabs.library" },
  { id: "loop", labelKey: "competition.tabs.loop" },
  { id: "review", labelKey: "competition.tabs.review" },
];

/** The `?tab=` values this page answers to: exactly the ids that have a button in `VIEW_TABS`.
 *
 * A deep link such as the Paper Desk's "Promoted · gen N" pill (`/competition?tab=loop`) opens
 * straight on the Loop view, while an unknown value, or a `View` member with no tab button
 * (`?tab=agent`, `?tab=leaderboard` -- see `View`'s own docstring on why those two survive in the
 * union with no rail entry), falls back to `"summary"` instead of selecting a view the rail cannot
 * show as active.
 *
 * This list used to feed a `TAB_IDS` set read ONCE, in a `useState` initialiser -- the query string
 * seeded the opening view and was then ignored, so every subsequent tab click left the URL saying
 * `?tab=loop` while the reader was three tabs away, and Back walked out of the page rather than
 * back through the tabs. `useTabParam` below makes the URL the state rather than its seed. */
const COMPETITION_TABS: readonly View[] = VIEW_TABS.map((tab) => tab.id);

/**
 * Rounds newest-first by `sequence`, **never** by `round_id` string.
 *
 * Sorting the ids lexicographically puts `"r9-2026-08"` above `"r13-2026-08"`, because `"9" > "1"`
 * character-wise. That is not a hypothetical: it is what the endpoint did, and it is half of why
 * this page rendered an empty Leaderboard. The backend now sorts numerically too; this re-sort is
 * kept anyway so the page does not silently inherit a regression in the response's order.
 *
 * `sequence` falls back to `-1` for a directory name that does not parse, which sorts such a round
 * last rather than dropping it -- an unrecognised round is still a round a reader may want to open.
 */
function orderRounds(rounds: RoundSummary[]): RoundSummary[] {
  return [...rounds].sort((a, b) => {
    if (a.sequence !== b.sequence) return b.sequence - a.sequence;
    return b.round_id.localeCompare(a.round_id);
  });
}

/**
 * Which round the page opens on: **the newest round that actually has scored results.**
 *
 * The old rule was `rounds[0]` — the newest round, full stop. Seven of the thirteen round
 * directories hold only a `SELECTION.md` or a `run.txt` and no run files at all, so
 * `GET .../leaderboard` answers 404 for them by design. Combined with the string-ordering bug above,
 * `rounds[0]` was `r9-2026-08`, one of the empty ones, and the tab opened onto a 404 and rendered
 * nothing at all. Both halves are fixed, but this function is the one that has to stay correct even
 * if a future round is created as an empty directory before it is run — which is exactly how those
 * seven came to exist.
 *
 * Falls back to the newest round of any kind when none has results, so a fresh install with nothing
 * scored yet still selects something and shows a designed empty state rather than a null-round page.
 */
function defaultRoundId(ordered: RoundSummary[]): string | null {
  return ordered.find((r) => r.has_results)?.round_id ?? ordered[0]?.round_id ?? null;
}

export default function Competition() {
  const { t } = useT();
  // Which section is on screen lives in `?tab=`, not a `useState` seeded from it: a tab click now
  // rewrites the URL (so the view is linkable and survives a reload) and pushes a history entry (so
  // Back returns to the previous section instead of leaving the page). Any `round` param already on
  // the URL rides through untouched -- `useTabParam` merges into the query string rather than
  // replacing it.
  const [view, setView] = useTabParam<View>("tab", COMPETITION_TABS, "summary");

  // --- rounds ------------------------------------------------------------------------------------
  const [selectedRoundId, setSelectedRoundId] = useState<string | null>(null);

  const roundsResult = useFetch<RoundSummary[]>(
    (signal) => competitionApi.rounds(signal).then((res) => orderRounds(res.rounds)),
    [],
    { formatError: (err) => errorMessage(err, t("competition.errors.rounds")) },
  );
  const rounds = roundsResult.data ?? [];
  const roundsPhase = roundsResult.phase;
  const roundsMessage = roundsResult.error;

  useEffect(() => {
    if (roundsResult.data) {
      setSelectedRoundId((prev) => prev ?? defaultRoundId(roundsResult.data!));
    }
  }, [roundsResult.data]);

  // --- library -----------------------------------------------------------------------------------
  const libraryResult = useFetch<LibraryResponse>((signal) => competitionApi.library(signal), [], {
    formatError: (err) => errorMessage(err, t("competition.errors.library")),
  });
  const library = libraryResult.data;
  const libraryPhase = libraryResult.phase;
  const libraryMessage = libraryResult.error;

  // --- window catalogue ----------------------------------------------------------------------------
  // The run form's own list of valid windows -- sourced independently of `rounds` so the very first
  // round (before any round exists) still has something to offer, unlike the old `rounds.flatMap(r
  // => r.windows)` derivation this replaces.
  const windowsResult = useFetch<WindowCatalogueEntry[]>(
    (signal) => competitionApi.windows(signal).then((res) => res.windows),
    [],
    { formatError: (err) => errorMessage(err, t("competition.errors.windows")) },
  );
  const windowCatalogue = windowsResult.data ?? [];
  const windowsPhase = windowsResult.phase;
  const windowsMessage = windowsResult.error;

  // --- leaderboard ---------------------------------------------------------------------------------
  const [rankBy, setRankBy] = useState<RankBy>("median");
  const [purpose, setPurpose] = useState<Purpose>("trading");

  const leaderboardResult = useFetch<LeaderboardResponse>(
    (signal) => competitionApi.leaderboard(selectedRoundId as string, rankBy, purpose, signal),
    [selectedRoundId, rankBy, purpose],
    {
      skip: !selectedRoundId,
      formatError: (err) => errorMessage(err, t("competition.errors.leaderboard")),
    },
  );
  const leaderboard = leaderboardResult.data;
  const leaderboardPhase = leaderboardResult.phase;
  const leaderboardMessage = leaderboardResult.error;

  // --- agent drill-down ----------------------------------------------------------------------------
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  const agentResult = useFetch<AgentDetailResponse>(
    (signal) => competitionApi.agentDetail(selectedRoundId as string, selectedAgentId as string, signal),
    [selectedRoundId, selectedAgentId],
    {
      skip: !selectedRoundId || !selectedAgentId,
      formatError: (err) => errorMessage(err, t("competition.errors.agentDetail")),
    },
  );
  const agentDetail = agentResult.data;
  const agentPhase = agentResult.phase;
  const agentMessage = agentResult.error;

  // Selects the agent for the inline drawer rendered under the Leaderboard table in the merged
  // "Rounds" view. `AgentSection` used to be its own tab this called `setView("agent")` to open, then
  // (after Summary/Leaderboard were still two tabs) required switching to Leaderboard first; now
  // Summary and Leaderboard are the same view, so selecting an agent from either one's own row click
  // is the whole job -- there is no other view left to switch to.
  //
  // A *toggle*, not a plain set: the leaderboard's own row control is a real
  // `<button aria-expanded>` now (see `LeaderboardSection`), and a control that says it is expanded
  // has to be able to collapse what it expanded. The drawer's Close button is unchanged and still
  // clears it the same way.
  const openAgent = (agentId: string) => {
    setSelectedAgentId((prev) => (prev === agentId ? null : agentId));
  };

  // --- narrative -------------------------------------------------------------------------------
  // The prose companion to the numbers: what this round asked, how it turned out, and what a person
  // overrode. Authored per round in `NARRATIVE.json` rather than parsed out of `SELECTION.md` --
  // those headings are improvised round to round, so an extractor over them would degrade into
  // plausible-looking prose rather than fail loudly. See `app.tournament.narrative`.
  //
  // 404 is an ordinary state, handled exactly as `selection` below handles its own: a round can have
  // results and findings and still have no authored narrative yet.
  const narrativeResult = useFetch<RoundNarrative | null>(
    async (signal) => {
      try {
        return await competitionApi.narrative(selectedRoundId as string, signal);
      } catch (err) {
        if (err instanceof ApiRequestError && err.status === 404) return null;
        throw err;
      }
    },
    [selectedRoundId],
    {
      skip: !selectedRoundId,
      formatError: (err) => errorMessage(err, t("competition.errors.narrative")),
    },
  );
  const narrative = narrativeResult.data ?? null;
  const narrativePhase = narrativeResult.phase;
  const narrativeMessage = narrativeResult.error;
  const narrativeNotFound = narrativeResult.phase === "loaded" && narrativeResult.data === null;

  // --- the next round --------------------------------------------------------------------------
  // Fetched once on mount, deliberately not keyed on `selectedRoundId`: this answers "what runs
  // next", which does not change with which past round the reader happens to be looking at.
  const briefingResult = useFetch<NextRoundBriefing>((signal) => competitionApi.nextRound(signal), [], {
    formatError: (err) => errorMessage(err, t("competition.errors.nextRound")),
  });
  const briefing = briefingResult.data;
  const briefingPhase = briefingResult.phase;
  const briefingMessage = briefingResult.error;

  // --- selection -------------------------------------------------------------------------------------
  // Shares `selectedRoundId` with the Leaderboard section rather than adding a second round picker.
  // Fetched eagerly on round change (same pattern as the leaderboard effect above), independent of
  // which tab is active, so switching into the Selection tab never shows a spinner for data that could
  // already be in flight.
  //
  // A `404` is not an error to surface as one -- it means this particular round has no selection
  // recorded, which the section renders as its own designed empty state rather than the generic
  // error placeholder every other failure gets.
  const selectionResult = useFetch<SelectionResponse | null>(
    async (signal) => {
      try {
        return await competitionApi.selection(selectedRoundId as string, signal);
      } catch (err) {
        if (err instanceof ApiRequestError && err.status === 404) return null;
        throw err;
      }
    },
    [selectedRoundId],
    {
      skip: !selectedRoundId,
      formatError: (err) => errorMessage(err, t("competition.errors.selection")),
    },
  );
  const selection = selectionResult.data ?? null;
  const selectionPhase = selectionResult.phase;
  const selectionMessage = selectionResult.error;
  const selectionNotFound = selectionResult.phase === "loaded" && selectionResult.data === null;

  // --- findings & follow-ups ---------------------------------------------------------------------
  // Shares `selectedRoundId` with every other section rather than adding a third round picker, and
  // is fetched eagerly on round change exactly like the leaderboard and selection effects above --
  // switching into the Findings tab should never spin for data that could already be in flight.
  //
  // Deliberately NOT gated on `has_results`: a round can have a written record without having any
  // run files. Rounds 6-10 and 12 are exactly that -- a `SELECTION.md` and nothing to score -- and
  // those are among the most useful records to read when planning the next round.
  //
  // Same contract as `selectionNotFound`: a 404 means this round wrote nothing down, which is a
  // designed empty state, not a failure to surface in red.
  const findingsResult = useFetch<FindingsResponse | null>(
    async (signal) => {
      try {
        return await competitionApi.findings(selectedRoundId as string, signal);
      } catch (err) {
        if (err instanceof ApiRequestError && err.status === 404) return null;
        throw err;
      }
    },
    [selectedRoundId],
    {
      skip: !selectedRoundId,
      formatError: (err) => errorMessage(err, t("competition.errors.findings")),
    },
  );
  const findings = findingsResult.data ?? null;
  const findingsPhase = findingsResult.phase;
  const findingsMessage = findingsResult.error;
  const findingsNotFound = findingsResult.phase === "loaded" && findingsResult.data === null;

  // --- run a new round -----------------------------------------------------------------------------
  const [job, setJob] = useState<JobStatus | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [creatingJob, setCreatingJob] = useState(false);

  // Polls `GET /jobs/{job_id}` roughly every 2s while the job is queued/running. The effect's own
  // dependency array (`job_id`, `status`) is what clears the interval on a terminal status: once
  // `status` flips to a terminal value the cleanup below runs and the body returns before creating a
  // new one, so nothing keeps polling a job that is already done.
  useEffect(() => {
    if (!job || isTerminalJobStatus(job.status)) return;
    const jobId = job.job_id;
    const id = setInterval(() => {
      competitionApi
        .job(jobId)
        .then((updated) => setJob(updated))
        .catch(() => {
          // A transient poll failure is not fatal -- the panel keeps its last known state and the
          // next tick tries again, rather than the whole page erroring out mid-run.
        });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [job?.job_id, job?.status]);

  const handleCreateJob = async (request: CreateJobRequest) => {
    setJobError(null);
    setCreatingJob(true);
    try {
      const created = await competitionApi.createJob(request);
      // Seeded from the 202 response, which is only a subset of `JobStatus` -- the first poll tick
      // fills in `completed_runs`, `log`, `results`, etc. `completed_runs`/`failed_runs` start at 0
      // and `current`/timestamps at `null` because nothing has run yet, not because they were
      // withheld.
      setJob({
        job_id: created.job_id,
        status: created.status,
        round_id: created.round_id,
        cards: request.cards,
        windows: request.windows,
        total_runs: created.total_runs,
        completed_runs: 0,
        failed_runs: 0,
        current: null,
        created_at: created.created_at,
        started_at: null,
        finished_at: null,
        elapsed_seconds: null,
        log: [],
        results: [],
        error: null,
      });
    } catch (err) {
      // A 409 names the already-running job in its own message -- rendered plainly, not retried.
      setJobError(errorMessage(err, t("competition.errors.startRound")));
    } finally {
      setCreatingJob(false);
    }
  };

  const handleCancelJob = async () => {
    if (!job) return;
    try {
      const updated = await competitionApi.cancelJob(job.job_id);
      setJob(updated);
    } catch (err) {
      setJobError(errorMessage(err, t("competition.errors.cancelJob")));
    }
  };

  // --- the endless competition/feedback loop --------------------------------------------------------
  // Fetched once on mount, independently of `selectedRoundId` -- the loop is a single running process,
  // not scoped to whichever past round the reader happens to be looking at.
  const [loopStatus, setLoopStatus] = useState<LoopStatus | null>(null);
  const [loopPhase, setLoopPhase] = useState<FetchPhase>("loading");
  const [loopMessage, setLoopMessage] = useState<string | null>(null);
  const [loopBusy, setLoopBusy] = useState(false);
  // The start form's draft values, lifted up here rather than kept as `LoopPanel` local state: the
  // header's own "Start the loop" toggle below (rendered outside `LoopPanel`, which unmounts whenever
  // the reader is on a tab other than "loop") must start the loop with whatever the form currently
  // holds, not silently reset to the form's defaults every time the reader leaves the Loop tab.
  const [loopDraft, setLoopDraft] = useState<LoopFormDraft>(DEFAULT_LOOP_FORM_DRAFT);
  const updateLoopDraft = (patch: Partial<LoopFormDraft>) =>
    setLoopDraft((prev) => ({ ...prev, ...patch }));

  useEffect(() => {
    let cancelled = false;
    setLoopPhase("loading");
    evolutionApi
      .loop()
      .then((res) => {
        if (cancelled) return;
        setLoopStatus(res);
        setLoopPhase("loaded");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // A 404 means the loop has never been started -- an ordinary idle state, not a page error.
        // Rendered by `LoopPanel` as an inviting "start it" state rather than the generic error
        // placeholder every other failure gets, matching `selection`/`findings`/`narrative`'s own
        // documented 404 handling above.
        if (isLoopNotStarted(err)) {
          setLoopStatus(null);
          setLoopPhase("loaded");
          return;
        }
        setLoopMessage(errorMessage(err, t("competition.errors.loop")));
        setLoopPhase("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Polls `GET /loop` roughly every 2s while the loop is running/stopping -- the same shape as the
  // job-poll effect above. The effect's own dependency array (`loop_id`, `state`) is what clears the
  // interval once the loop settles into an end state, so nothing keeps polling a loop that has already
  // stopped or failed.
  useEffect(() => {
    if (!loopStatus || !isLoopActive(loopStatus.state)) return;
    const id = setInterval(() => {
      evolutionApi
        .loop()
        .then((updated) => setLoopStatus(updated))
        .catch(() => {
          // A transient poll failure is not fatal -- the panel keeps its last known state and the
          // next tick tries again, rather than the whole page erroring out mid-run.
        });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [loopStatus?.loop_id, loopStatus?.state]);

  // `config` is optional so the header toggle below can call this with nothing and still get the
  // reader's current form values -- `loopDraft` is the same state `LoopPanel`'s form is controlled by,
  // so "nothing supplied" here means "whatever the form currently holds", never a silent reset to
  // defaults. `LoopPanel`'s own toggle passes its assembled config explicitly instead of relying on
  // this fallback, but the two are always in sync since the draft is controlled from here.
  const handleStartLoop = async (config?: Partial<LoopConfig>) => {
    setLoopMessage(null);
    setLoopBusy(true);
    try {
      const started = await evolutionApi.startLoop(config ?? buildLoopConfigFromDraft(loopDraft));
      setLoopStatus(started);
      setLoopPhase("loaded");
    } catch (err) {
      // A 422 names the specific rejected ticker/list -- see `describeStartLoopError`'s own docstring
      // on why that is not `err.message` rendered verbatim.
      setLoopMessage(describeStartLoopError(err));
    } finally {
      setLoopBusy(false);
    }
  };

  const handleStopLoop = async () => {
    setLoopMessage(null);
    setLoopBusy(true);
    try {
      const stopped = await evolutionApi.stopLoop();
      setLoopStatus(stopped);
    } catch (err) {
      // A 409 means nothing is running -- a real error, unlike `loop()`'s own 404, and rendered
      // plainly rather than retried.
      setLoopMessage(errorMessage(err, t("competition.errors.stopLoop")));
    } finally {
      setLoopBusy(false);
    }
  };

  const loopActive = isLoopActive(loopStatus?.state ?? "idle");
  const loopStopping = loopStatus?.state === "stopping";
  const loopToggleLabel = loopStopping
    ? t("competition.loop.stopping")
    : loopActive
      ? t("competition.loop.stop")
      : t("competition.loop.start");

  // The loop's live state, beside the button that changes it. Without this the header offered a
  // "Start the loop" control whose current state was only readable on the Overview page's programme
  // strip -- a different page entirely -- or by opening the Loop tab.
  //
  // Three states, and the third is the point: `/loop` answering 404 is the loop's ordinary
  // never-started state and is already folded into `loopStatus === null` by the fetch effect above,
  // so it pills as "Idle"; a genuine failure (`loopPhase === "error"`) pills as *unknown* rather
  // than as a confident "Idle" the page has no evidence for. Neither path throws.
  const loopStatePill =
    loopPhase === "loading" ? null : loopPhase === "error" ? (
      <StatusPill tone="neutral" label={t("competition.loop.stateUnknown")} />
    ) : (
      <StatusPill
        tone={loopStateTone(loopStatus?.state ?? "idle")}
        label={loopStateLabel(loopStatus?.state ?? "idle")}
      />
    );

  return (
    <>
      <div className="comp-page-head">
        <div>
          <h1>{t("competition.page.title")}</h1>
          <p className="subtitle">{t("competition.page.subtitle")}</p>
        </div>
        {/* Two actions, side by side: running a round is the one thing on this page that *changes*
            something on its own, and starting the endless loop is the other -- both promoted out of
            their tabs' form furniture rather than sitting three clicks deep.
            They wear the shared quiet `.symbol-submit` treatment (the Macro page's refresh button and
            the Overview toolbar's own), not the accent-filled `.comp-run-cta` they used to: this is a
            page a reader comes to *read*, and two glowing filled controls above the fold read as the
            page's purpose rather than as two side doors off it. The stop state keeps its own colour
            through a modifier, so "stop a running process" is still visibly a different kind of act
            from "start" or "plan". */}
        <div className="comp-header-actions">
          <button
            type="button"
            className="symbol-submit comp-header-action"
            onClick={() => setView("library")}
            aria-describedby="comp-run-cta-hint"
          >
            {t("competition.page.runCta")}
          </button>
          <span className="comp-loop-toggle">
            <button
              type="button"
              className={`symbol-submit comp-header-action${loopActive ? " comp-header-action-stop" : ""}`}
              // No config passed -- `handleStartLoop` falls back to `loopDraft`, the same state
              // `LoopPanel`'s form is controlled by, so this one-click path starts the loop with
              // whatever the form currently holds (or its defaults, if never touched).
              onClick={loopActive ? handleStopLoop : () => handleStartLoop()}
              disabled={loopBusy || loopStopping}
              aria-describedby="comp-loop-cta-hint"
            >
              {loopToggleLabel}
            </button>
            {loopStatePill}
          </span>
        </div>
      </div>
      <p id="comp-run-cta-hint" className="visually-hidden">
        {t("competition.page.runCtaHint")}
      </p>
      <p id="comp-loop-cta-hint" className="visually-hidden">
        {t("competition.loop.toggleHint")}
      </p>

      <div className="view-tabs" role="tablist" aria-label={t("competition.page.tabsAriaLabel")}>
        {VIEW_TABS.map(({ id, labelKey }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={view === id}
            className={`timeframe-tab${view === id ? " active" : ""}`}
            onClick={() => setView(id)}
          >
            {t(labelKey)}
            {/* The tab rail's own version of the pulse `.comp-job-status-running` gives a live job --
                a reader switched away from the Loop tab should still see it is doing something. */}
            {id === "loop" && loopActive && (
              <>
                {" "}
                <span className="comp-tab-live" aria-hidden="true" title={t("competition.page.loopLiveTitle")}>
                  ●
                </span>
                <span className="visually-hidden"> {t("competition.page.loopLiveLabel")}</span>
              </>
            )}
          </button>
        ))}
      </div>

      {view === "summary" && (
        <RoundNarrativeCard
          narrative={narrative}
          phase={narrativePhase}
          message={narrativeMessage}
          notFound={narrativeNotFound}
        />
      )}

      {/* The merged "Rounds" view: `SummarySection`'s orientation (this round's question, programme
          scale, this round's numbers, the per-window strip) flows directly into `LeaderboardSection`'s
          ranked table below it, both driven by the one round picker `SummarySection` renders --
          `LeaderboardSection` no longer renders a round `<select>` of its own, so there is only ever
          one on screen. See `VIEW_TABS`'s and `View`'s own docstrings above on why
          `"leaderboard"` has no separate tab any more (docs/STRATEGY-AGENT-UX-ANALYSIS.md §A2). */}
      {view === "summary" && (
        <SummarySection
          rounds={rounds}
          roundsPhase={roundsPhase}
          roundsMessage={roundsMessage}
          selectedRoundId={selectedRoundId}
          onSelectRound={setSelectedRoundId}
          leaderboard={leaderboard}
          leaderboardPhase={leaderboardPhase}
          leaderboardMessage={leaderboardMessage}
          onSelectAgent={openAgent}
        />
      )}

      {view === "summary" && (
        <LeaderboardSection
          purpose={purpose}
          onSelectPurpose={setPurpose}
          rounds={rounds}
          selectedRoundId={selectedRoundId}
          rankBy={rankBy}
          onRankByChange={setRankBy}
          leaderboard={leaderboard}
          phase={leaderboardPhase}
          message={leaderboardMessage}
          onSelectAgent={openAgent}
          selectedAgentId={selectedAgentId}
        />
      )}

      {/* The drill-down a leaderboard row opens (from either section above -- both now call the same
          `openAgent`), rendered inline under the table it was opened from rather than on its own tab
          -- see `VIEW_TABS`'s own docstring above on why `"agent"` has no tab entry any more. Gated on
          `selectedAgentId` so the bare table is all that shows until a row is actually clicked, and
          cleared by its own close button rather than a tab switch. */}
      {view === "summary" && selectedAgentId && (
        <div className="comp-agent-drawer">
          <AgentSection
            roundId={selectedRoundId}
            agentId={selectedAgentId}
            detail={agentDetail}
            phase={agentPhase}
            message={agentMessage}
            onClose={() => setSelectedAgentId(null)}
          />
        </div>
      )}

      {view === "findings" && (
        <FindingsSection
          rounds={rounds}
          roundsPhase={roundsPhase}
          selectedRoundId={selectedRoundId}
          onSelectRound={setSelectedRoundId}
          findings={findings}
          phase={findingsPhase}
          message={findingsMessage}
          notFound={findingsNotFound}
        />
      )}

      {view === "library" && (
        <NextRoundPanel
          briefing={briefing}
          phase={briefingPhase}
          message={briefingMessage}
        />
      )}

      {view === "library" && (
        <LibrarySection
          library={library}
          libraryPhase={libraryPhase}
          libraryMessage={libraryMessage}
          windowCatalogue={windowCatalogue}
          windowsPhase={windowsPhase}
          windowsMessage={windowsMessage}
          job={job}
          jobError={jobError}
          creatingJob={creatingJob}
          onCreateJob={handleCreateJob}
          onCancelJob={handleCancelJob}
        />
      )}

      {view === "selection" && (
        <SelectionSection
          roundId={selectedRoundId}
          rounds={rounds}
          roundsPhase={roundsPhase}
          onSelectRound={setSelectedRoundId}
          selection={selection}
          phase={selectionPhase}
          message={selectionMessage}
          notFound={selectionNotFound}
        />
      )}

      {view === "loop" && (
        <LoopPanel
          status={loopStatus}
          phase={loopPhase}
          message={loopMessage}
          busy={loopBusy}
          onStart={handleStartLoop}
          onStop={handleStopLoop}
          draft={loopDraft}
          onDraftChange={updateLoopDraft}
        />
      )}

      {/* `PendingSeatsPanel` is fully self-contained -- it fetches its own queue data via
          `evolutionApi.pendingSeats`/`dossier` and takes no props -- so nothing needs wiring down from
          this page's own state. See the `View` docstring above on why this has its own tab rather
          than living inside `LoopPanel`. */}
      {view === "review" && <PendingSeatsPanel />}
    </>
  );
}

