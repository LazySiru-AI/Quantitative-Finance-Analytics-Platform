/**
 * Overview — the landing page.
 *
 * One screen answering "what should I look at today" without clicking through the other thirteen
 * pages: the portfolio headline, the market strip, what each paper-desk reference agent is holding,
 * upcoming FOMC/earnings dates, and anything that actually needs attention. Every figure here is a
 * *summary* of a fuller page — `/portfolio`, `/macro`, `/paper-desk`, `/tax?tab=wash` — and every such
 * section links through to it, because a rounded or partial number that has nowhere to go becomes
 * the source of truth by accident. (The calendar card is the one exception: there is no `/calendar`
 * page to link through to, so `EventCalendarCard` omits the link rather than pointing at a page
 * that does not exist.)
 *
 * Five independent fetches back this page (`portfolioApi.report`, `macroApi.snapshot`,
 * `paperdeskApi.state`, `washSalesApi.tracker`, `calendarApi.upcoming`), and each owns its own
 * loading/loaded/error state. One failing must never blank the others — see `PortfolioSection`,
 * `MarketSection`, `ReferenceDeskSection`, `EventCalendarCard` below, each gated on its own phase
 * rather than a single page-wide flag.
 *
 * Three more independent fetches back the tiles added to make this the real front door
 * (`taxApi.report`, `transactionsApi.list`, `consensusApi.get`) — see `TaxSection`, `ActivitySection`,
 * `ConsensusSection` below. `consensusApi.get` is the slow one (a cold-cache run walks every tracked
 * filer's latest filing), so `useLazyConsensus` fires it a tick after every other fetch on this page
 * has already gone out, and its panel renders a `Skeleton` rather than a bare loading line while it
 * is in flight, and degrades to a dash rather than an error banner on failure — a reader coming to
 * this page for the portfolio or tax tiles should never be made to wait on, or be alarmed by, the
 * one panel doing the most work.
 *
 * Four honesty rules this page exists to keep, all inherited from the pages/endpoints it summarises
 * rather than invented here:
 *
 * - `total_market_value`/`total_unrealized` on `PortfolioReport` are sums over PRICED positions
 *   only (see `api/portfolio.ts`'s module docstring). A non-empty `unpriced_symbols` means the
 *   headline figure is partial, and the tile says so rather than printing a silently-short total.
 * - `total_equity` is only meaningful when `equity_is_complete` is true. When it is not, the tile
 *   is flagged rather than rendering a number that looks whole but is not.
 * - Every price-derived figure says what it is marked to. The portfolio tiles used to print a bare
 *   `Total equity` dollar figure with no date anywhere on it, while `ReferenceDeskSection` fifteen
 *   lines below stated its own staleness plainly — so during a period when the bar store was
 *   silently running sessions behind, this page showed an honest warning on one card and an
 *   apparently-current number on the card above it, with nothing to tell the reader the second was
 *   any less current than the first. See `PortfolioMarkNote`.
 * - The paper desk is three independent reference books, not a portfolio — `savings`, `trading`,
 *   and `roth` never get summed into one figure, and neither do the desks within a book (each
 *   desk is its own agent with its own book). See `ReferenceDeskSection`/`BookCard`.
 * - The calendar card never lets an `estimated` earnings date read as one the company promised, never
 *   shows an earnings-coverage numerator without its `holdings_total` denominator, and never
 *   swallows a degraded sweep's `warnings[]`. See `EventCalendarCard`/`components/EventCalendar`.
 *
 * **Layout.** The three multi-card rows (Tax|Activity, Fear&Greed|Calendar|Attention, and the three
 * reference books) are `CardGrid`s, so every card in a row is exactly as tall as its neighbours and
 * scrolls inside that height. This reverses an earlier, deliberate choice to let each card keep its
 * own natural height: a row of `align-items: start` panels gives every row a ragged bottom edge and
 * a different amount of dead space, and the reader has to re-find the baseline in every column. See
 * `components/Card.tsx` for why the height lives on the grid rather than on each card.
 *
 * Two of those cards compose a component that already brings its own `.panel`, heading and (for the
 * calendar) scroll region — `FearGreedGauge` and `EventCalendar`. Neither is re-implemented here and
 * neither gets a second heading in the card head: two elements with the same accessible name is a
 * worse outcome than a card whose title happens to live one element lower. `Overview.css` flattens
 * the nested panel so the pair still reads as one card.
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "@/auth";
import { ApiRequestError, type DecimalString } from "@/api/client";
import {
  formatMoneyOrDash,
  formatSignedFractionPct,
  formatSignedMoney,
  moneyTone,
  priceAsOfRange,
  type PortfolioReport,
} from "@/api/portfolio";
import { daysUntil, type EventCalendar as EventCalendarData } from "@/api/calendar";
import type { MacroSnapshot } from "@/api/macro";
import {
  fractionStringTone,
  formatSignedFractionPctString,
  paperdeskApi,
  type Book,
  type PaperDeskState,
} from "@/api/paperdesk";
import { washSalesApi, type WashSaleTracker } from "@/api/washsales";
import { evolutionApi, isLoopNotStarted, type LoopState } from "@/api/evolution";
import { tradingAgentsApi, type TradingAgentsConfig } from "@/api/tradingagents";
import { competitionApi, type RoundSummary } from "@/api/competition";
import { taxApi, addMoney, formatMoney as formatTaxMoney, type TaxReport } from "@/api/tax";
import { transactionsApi, actionLabel, type TransactionPage } from "@/api/transactions";
import { consensusApi, type ConsensusResponse } from "@/api/consensus";

import { Trans, t, useT, type MessageKey } from "@/i18n";
import type { Translator } from "@/i18n/useT";

import MacroKeyIndicators from "@/components/MacroKeyIndicators";
import FearGreedGauge from "@/components/FearGreedGauge";
import EventCalendar from "@/components/EventCalendar";
import { Card, CardGrid } from "@/components/Card";
import StatusPill from "@/components/StatusPill";
import Skeleton from "@/components/Skeleton";
import CountdownBar from "@/components/CountdownBar";

import { usePortfolio, type Phase as PortfolioPhase } from "@/hooks/usePortfolio";
import { useMacroSnapshot } from "@/hooks/useMacroSnapshot";
import { useEventCalendar, type CalendarPhase } from "@/hooks/useEventCalendar";
import { useFetch, type FetchPhase } from "@/hooks/useFetch";

import "./Overview.css";

/** Mirrors `STALE_DAYS_WARN_THRESHOLD` in `pages/PaperDesk.tsx` — the same number of days behind
 *  the latest session before the mark is called out, so this page and the full desk page never
 *  disagree about what counts as stale. Not imported from there: that file is out of this page's
 *  scope, and the constant is not exported. */
const STALE_DAYS_WARN_THRESHOLD = 5;

function describeFetchFailure(e: unknown): string {
  if (e instanceof ApiRequestError) return t("misc.fetch.apiError", { status: e.status, message: e.message });
  return t("misc.fetch.unreachable");
}

// --- local fetch hooks -------------------------------------------------------------------------
//
// `usePortfolio`/`useMacroSnapshot` already exist for their own pages; there is no equivalent for
// the paper desk or wash-sale tracker, so this page fetches those two directly, one small
// `useState`/`useEffect` pair each, mirroring the AbortController-per-effect-run guard the existing
// hooks use so a fast unmount never lets a stale response land after the fact.

interface DeskFetchState {
  desk: PaperDeskState | null;
  phase: FetchPhase;
  message: string | null;
  refresh: () => void;
}

function useDeskState(): DeskFetchState {
  const result = useFetch<PaperDeskState>((signal) => paperdeskApi.state(signal), [], {
    formatError: describeFetchFailure,
  });
  // `desk` (unlike most `useFetch` data) reads `null` on a failed fetch, not whatever the last good
  // response was -- the original hook nulled it explicitly in its own `catch`, and `AttentionSection`
  // below reads `desk` directly, ungated by `phase`, relying on exactly that.
  const desk = result.phase === "error" ? null : result.data;
  return { desk, phase: result.phase, message: result.error, refresh: result.reload };
}

interface WashTrackerFetchState {
  tracker: WashSaleTracker | null;
  phase: FetchPhase;
  message: string | null;
  refresh: () => void;
}

/**
 * `enabled` (default handled by the one caller in `Overview()`, which always passes it explicitly)
 * gates the fetch itself -- `/api/tax/wash-sales` is one of the owner-only prefixes, and `Overview()`
 * passes `isOwner` here so a member's session never sends the request. Like `usePortfolio`, this
 * does not invent a phase for "disabled"; `Overview()` never reads this hook's own `phase` for a
 * member, substituting a resolved literal at the call site instead (see its own comment there).
 */
function useWashTracker(enabled: boolean): WashTrackerFetchState {
  const result = useFetch<WashSaleTracker>((signal) => washSalesApi.tracker(signal), [], {
    formatError: describeFetchFailure,
    skip: !enabled,
  });
  // See `useDeskState`'s own note: `AttentionSection` reads `tracker` directly, ungated by `phase`.
  const tracker = result.phase === "error" ? null : result.data;
  return { tracker, phase: result.phase, message: result.error, refresh: result.reload };
}

/**
 * The evolution/competition loop's current lifecycle state, collapsed to just the one field
 * `ProgrammeSection` renders. A `GET /loop` `404` is the loop's ordinary "never started" state, not
 * a page error -- `isLoopNotStarted` is the one place that check should live (see `api/evolution.ts`'s
 * own docstring), so it is folded into `"idle"` here rather than surfacing as a failure the reader has
 * no way to act on differently from a genuinely idle loop.
 */
interface LoopFetchState {
  loopState: LoopState | null;
  phase: FetchPhase;
}

function useLoopState(): LoopFetchState {
  const result = useFetch<LoopState>(async (signal) => {
    try {
      const data = await evolutionApi.loop(signal);
      return data.state;
    } catch (e) {
      if (isLoopNotStarted(e)) return "idle";
      throw e;
    }
  }, []);
  const loopState = result.phase === "error" ? null : result.data;
  return { loopState, phase: result.phase };
}

/** Whether the agent/model layer backing the Trading Agents desk can start a run right now. */
interface AgentFetchState {
  config: TradingAgentsConfig | null;
  phase: FetchPhase;
}

function useAgentAvailability(): AgentFetchState {
  const result = useFetch<TradingAgentsConfig>((signal) => tradingAgentsApi.config(signal), []);
  const config = result.phase === "error" ? null : result.data;
  return { config, phase: result.phase };
}

/**
 * The newest competition round that actually has a leaderboard -- the highest `sequence` among
 * rounds with `has_results: true`. A round directory that exists but never ran (`has_results: false`)
 * has no leaderboard and no selection (see `RoundSummary.has_results`'s own docstring in
 * `api/competition.ts`), so it is never eligible to be "the newest round" this strip reports.
 */
interface NewestRoundFetchState {
  round: RoundSummary | null;
  phase: FetchPhase;
}

function useNewestScoredRound(): NewestRoundFetchState {
  const result = useFetch<RoundSummary | null>(
    (signal) =>
      competitionApi
        .rounds(signal)
        .then((data) =>
          data.rounds
            .filter((r) => r.has_results)
            .reduce<RoundSummary | null>(
              (best, r) => (best === null || r.sequence > best.sequence ? r : best),
              null,
            ),
        ),
    [],
  );
  const round = result.phase === "error" ? null : result.data;
  return { round, phase: result.phase };
}

/**
 * Year-to-date realised gain plus the wash-sale figures the Tax tile shows. `taxApi.report` has no
 * `signal` parameter (unlike every other client in this file), so this guards against a late
 * response with a plain `cancelled` flag rather than an `AbortController` -- the same pattern
 * `resolveDefaultYear` uses in `pages/Tax.tsx` for the same client.
 *
 * The year is simply the calendar year, not `Tax.tsx`'s own `resolveDefaultYear` (which anchors on
 * the ledger's latest transaction to avoid defaulting to a year with nothing in it). That care is for
 * a page whose whole job is showing one year's figures and must not silently land on the wrong one;
 * this tile is explicitly labelled "YTD", so a real `$0.00` in January is the correct answer, not a
 * bug to route around.
 */
interface TaxYtdFetchState {
  report: TaxReport | null;
  phase: FetchPhase;
  message: string | null;
  refresh: () => void;
}

/** `enabled`: see `useWashTracker`'s own docstring above -- same reasoning, `/api/tax` is the
 *  owner-only prefix here, and `Overview()` never reads this hook's own `phase` for a member. */
function useTaxYtdReport(year: number, enabled: boolean): TaxYtdFetchState {
  // `taxApi.report` has no `signal` parameter (see this hook's own module docstring above), so the
  // fetcher below simply ignores the one `useFetch` supplies -- the stale-response guard that matters
  // here is `useFetch`'s own cancelled/generation check, not request cancellation.
  const result = useFetch<TaxReport>(() => taxApi.report(year), [year], {
    formatError: describeFetchFailure,
    skip: !enabled,
  });
  const report = result.phase === "error" ? null : result.data;
  return { report, phase: result.phase, message: result.error, refresh: result.reload };
}

/**
 * The single most recent transaction, plus the filtered-set total `transactionsApi.list` always
 * returns -- see that module's own docstring for why `total` describes the whole matching set and
 * not just the one row asked for here. `limit: 1` keeps this the same cheap round trip
 * `Tax.tsx`'s `resolveDefaultYear` already makes for the same reason: the newest row is all the
 * Activity tile needs, not a page of history.
 */
interface ActivityFetchState {
  page: TransactionPage | null;
  phase: FetchPhase;
  message: string | null;
  refresh: () => void;
}

/** `enabled`: see `useWashTracker`'s own docstring above -- same reasoning, `/api/portfolio/transactions`
 *  (under the owner-only `/api/portfolio` prefix) is the endpoint here. */
function useLatestActivity(enabled: boolean): ActivityFetchState {
  const result = useFetch<TransactionPage>(
    (signal) => transactionsApi.list({ newest_first: true, limit: 1 }, signal),
    [],
    { formatError: describeFetchFailure, skip: !enabled },
  );
  const page = result.phase === "error" ? null : result.data;
  return { page, phase: result.phase, message: result.error, refresh: result.reload };
}

/**
 * Cross-institution filer consensus -- the slowest panel on this page on a cold cache (the backend
 * walks every tracked filer's latest filing). Fired from a `setTimeout(0)` rather than straight from
 * the effect, so it goes out only after every other fetch on this page has already been dispatched in
 * this same mount rather than contending with them for the first round trip. Never exposed to the
 * page-level "Fetch data" button (see `fetchAll` in `Overview()`) for the same reason -- forcing this
 * one cold every time that button is pressed would make the one deliberate, cheap refresh action on
 * this page expensive.
 *
 * No `message` state: a failure here degrades the tile to a dash (see `ConsensusSection`), not to an
 * error banner with a status code -- the brief for this tile is quiet degradation, not a fourth
 * failure surface on the landing page.
 */
interface ConsensusFetchState {
  data: ConsensusResponse | null;
  phase: FetchPhase;
}

function useLazyConsensus(): ConsensusFetchState {
  const [data, setData] = useState<ConsensusResponse | null>(null);
  const [phase, setPhase] = useState<FetchPhase>("loading");

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      consensusApi
        .get({ limit: 1 }, controller.signal)
        .then((result) => {
          setData(result);
          setPhase("loaded");
        })
        .catch((e: unknown) => {
          if (e instanceof DOMException && e.name === "AbortError") return;
          setData(null);
          setPhase("error");
        });
    }, 0);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, []);

  return { data, phase };
}

// --- page ----------------------------------------------------------------------------------------

export default function Overview() {
  const { t } = useT();
  const { isOwner } = useAuth();

  // Four of this page's fetches hit an owner-only API prefix -- `/api/portfolio` (report and, via
  // `useLatestActivity`, transactions), `/api/tax` (the YTD report), and `/api/tax/wash-sales`. Each
  // hook below takes `enabled: isOwner` (or a plain `isOwner` argument) so a member's session never
  // sends any of those four requests -- not "sends it and discards the 403", genuinely never fires.
  //
  // What a member sees instead is NOT that hook's own `phase`: disabling a fetch leaves `phase` stuck
  // at its initial `"loading"` forever (see `usePortfolio`'s and `useWashTracker`'s own docstrings on
  // why neither hook tries to invent a "disabled" phase itself), and a permanent, unresolving
  // "Loading…" is worse than the truth. So for a member, every one of `report`/`portfolioPhase`/
  // `tracker`/`washPhase`/`taxReport`/`taxPhase`/`activityPage`/`activityPhase` below is a literal,
  // already-resolved value instead of whatever the underlying (never-fetched) hook is sitting at --
  // `PortfolioSection`/`TaxSection`/`ActivitySection` render their own compact owner-only line off
  // `isOwner` directly, and `AttentionSection` (which folds portfolio/wash-sale data together with
  // the non-owner-only desk data into one merged list) reads `report`/`tracker` as absent and
  // `portfolioPhase`/`washPhase` as resolved, so it settles on "nothing to report from those two
  // sources" rather than sitting on "still checking" for the rest of the session.
  const rawPortfolio = usePortfolio({ enabled: isOwner });
  const report = isOwner ? rawPortfolio.report : null;
  const portfolioPhase: PortfolioPhase = isOwner ? rawPortfolio.phase : "empty";
  const portfolioMessage = isOwner ? rawPortfolio.message : null;
  const refreshPortfolio = rawPortfolio.refresh;

  const { snapshot, phase: macroPhase, message: macroMessage, refresh: refreshMacro } =
    useMacroSnapshot();
  const { desk, phase: deskPhase, message: deskMessage, refresh: refreshDesk } = useDeskState();

  const rawWash = useWashTracker(isOwner);
  const tracker = isOwner ? rawWash.tracker : null;
  const washPhase: FetchPhase = isOwner ? rawWash.phase : "loaded";
  const washMessage = isOwner ? rawWash.message : null;
  const refreshWash = rawWash.refresh;

  // Lifted out of `EventCalendarCard` (which used to own it) so the page-level "Fetch data" button
  // can re-pull the calendar alongside the other four cards. The section still owns its own
  // expand/collapse state; only the fetch lifecycle moved up here.
  const calendar = useEventCalendar();
  const taxYear = new Date().getFullYear();

  const rawTax = useTaxYtdReport(taxYear, isOwner);
  const taxReport = isOwner ? rawTax.report : null;
  const taxPhase: FetchPhase = isOwner ? rawTax.phase : "loaded";
  const taxMessage = isOwner ? rawTax.message : null;
  const refreshTax = rawTax.refresh;

  const rawActivity = useLatestActivity(isOwner);
  const activityPage = isOwner ? rawActivity.page : null;
  const activityPhase: FetchPhase = isOwner ? rawActivity.phase : "loaded";
  const activityMessage = isOwner ? rawActivity.message : null;
  const refreshActivity = rawActivity.refresh;

  // Deliberately not wired into `fetchAll`/`anyLoading` below -- see `useLazyConsensus`'s own
  // docstring for why this one panel stays off the page-level refresh button.
  const { data: consensusData, phase: consensusPhase } = useLazyConsensus();

  // The "Fetch data" button: one deliberate, user-initiated pull that refreshes every card. The
  // macro card pins its endpoint's cache TTL to zero for this request, forcing fresh FRED/CNN/Yahoo
  // round trips -- that is the volatile, intraday-moving data (prices, Fear & Greed, rates) worth the
  // cost. The portfolio, desk, wash, tax and activity cards cache nothing server-side and simply
  // re-run against the current ledger. The calendar re-fetches its day-scale cache rather than being
  // forced cold: a `?refresh=true` there re-pulls every earnings day as a separate Nasdaq round trip
  // (~60-90s, and a rate-limiter risk) to refresh dates that do not move intraday -- see
  // `useEventCalendar`. An ordinary page load reads the cache the startup warm primed, so the page
  // stays fast to open and only macro pays the network here, and only when the reader asks.
  const anyLoading =
    portfolioPhase === "loading" ||
    macroPhase === "loading" ||
    deskPhase === "loading" ||
    washPhase === "loading" ||
    calendar.phase === "loading" ||
    taxPhase === "loading" ||
    activityPhase === "loading";
  const fetchAll = useCallback(() => {
    refreshPortfolio();
    refreshMacro();
    refreshDesk();
    refreshWash();
    calendar.refresh();
    refreshTax();
    refreshActivity();
  }, [refreshPortfolio, refreshMacro, refreshDesk, refreshWash, calendar, refreshTax, refreshActivity]);

  return (
    <div className="overview-page">
      {/* The page's one `<h1>`. Every section below is an `<h2>`, so without this the landing page
          started its heading outline at level 2 and a screen-reader user jumping by heading had no
          "you are here" to land on. The label is `nav.page./overview.label` rather than a second
          "Overview"/"개요" pair of its own -- the rail and the page must never drift apart on what
          this page is called, and one key cannot. */}
      <div className="overview-toolbar">
        <h1 className="overview-title">{t("nav.page./overview.label")}</h1>
        <button
          type="button"
          className="symbol-submit"
          onClick={fetchAll}
          disabled={anyLoading}
          aria-label={t("misc.overview.fetchData.ariaLabel")}
        >
          {anyLoading ? t("misc.overview.fetchData.loading") : t("misc.overview.fetchData.label")}
        </button>
      </div>

      <PortfolioSection report={report} phase={portfolioPhase} message={portfolioMessage} isOwner={isOwner} />
      <MarketSection snapshot={snapshot} phase={macroPhase} message={macroMessage} />
      <ProgrammeSection />

      {/* Tax and Activity side by side: two more of this page's summaries, each one field's worth of
          "should I look at this today" pulled from a page this reader would otherwise have to open
          directly to learn at all. `sm` because both are a countdown and a handful of tiles -- a card
          that never needs more than that should not be handed the calendar's height. */}
      <CardGrid height="sm" min="320px">
        <TaxSection
          taxReport={taxReport}
          taxPhase={taxPhase}
          taxMessage={taxMessage}
          taxYear={taxYear}
          tracker={tracker}
          washPhase={washPhase}
          isOwner={isOwner}
        />
        <ActivitySection page={activityPage} phase={activityPhase} message={activityMessage} isOwner={isOwner} />
      </CardGrid>

      {/* Fear & Greed, the calendar and the attention list as one equal-height row. Each card owns its
          own fetch/phase state, so one failing never blanks the others; the grid track owns their
          height, so a quiet attention list no longer leaves a column of dead space beside a full
          earnings calendar. */}
      <CardGrid height="md" min="320px">
        <MarketFearGreedCard snapshot={snapshot} phase={macroPhase} />
        <EventCalendarCard
          calendar={calendar.calendar}
          phase={calendar.phase}
          message={calendar.message}
          slow={calendar.slow}
          refresh={calendar.refresh}
        />
        <AttentionSection
          report={report}
          portfolioPhase={portfolioPhase}
          desk={desk}
          deskPhase={deskPhase}
          tracker={tracker}
          washPhase={washPhase}
          washMessage={washMessage}
          isOwner={isOwner}
        />
      </CardGrid>

      {/* Reference desk on its own full-width row (the attention panel that used to sit beside it now
          lives up in the Fear-&-Greed row). */}
      <ReferenceDeskSection desk={desk} phase={deskPhase} message={deskMessage} />

      {/* The slowest panel on the page goes last -- see `useLazyConsensus`'s own docstring for why it
          is fetched after everything above it, and degrades to a dash rather than an error banner. */}
      <ConsensusSection data={consensusData} phase={consensusPhase} />
    </div>
  );
}

// --- section: portfolio headline -------------------------------------------------------------

function PortfolioSection({
  report,
  phase,
  message,
  isOwner,
}: {
  report: PortfolioReport | null;
  phase: "loading" | "loaded" | "empty" | "error";
  message: string | null;
  /** `/api/portfolio` is owner-only (see `Overview()`'s own comment on its owner-only fetches). A
   *  member never fetches it, and this renders one compact line in place of the tile rather than
   *  the loading/error/empty/loaded states below, none of which apply to a request never made. */
  isOwner: boolean;
}) {
  const { t } = useT();
  return (
    <section className="overview-section" aria-labelledby="overview-portfolio-heading">
      <SectionHead
        id="overview-portfolio-heading"
        title={t("misc.overview.section.portfolio")}
        to="/portfolio"
        linkLabel={t("misc.overview.link.portfolio")}
      />
      {!isOwner && <p className="muted overview-owner-only-note">{t("auth.ownerOnly.notice")}</p>}
      {isOwner && phase === "loading" && (
        <div className="panel">
          <Skeleton variant="tiles" rows={4} what={t("misc.overview.portfolio.skeletonWhat")} />
        </div>
      )}
      {isOwner && phase === "error" && (
        <div className="panel callout callout-danger">
          {message
            ? t("misc.overview.portfolio.failedWithMessage", { message })
            : t("misc.overview.portfolio.failed")}
        </div>
      )}
      {isOwner && phase === "empty" && (
        <div className="panel placeholder">{t("misc.overview.portfolio.empty")}</div>
      )}
      {isOwner && phase === "loaded" && report && <PortfolioTiles report={report} />}
    </section>
  );
}

/**
 * Calendar days between a `YYYY-MM-DD` date and today, positive when the date is in the past.
 * `null` for a missing or unreadable date.
 *
 * **`null`, never `0`, on an unreadable date.** `daysUntil` answers `0` for anything it cannot
 * parse, and `0` here renders as "current" — so passing a malformed date straight through would
 * state the exact reassurance the caller has least right to give. The shape is checked before the
 * arithmetic so "I don't know how stale this is" stays distinguishable from "it isn't stale".
 *
 * Built on `daysUntil` from `@/api/calendar` rather than a fourth local copy of the UTC-safe day
 * diff: `new Date("2026-08-25")` read back in a local zone west of Greenwich is the 24th, and that
 * module already documents and solves it. Its sign convention is "days until", so a past date comes
 * back negative and is negated here.
 */
function calendarDaysBehind(date: string | null): number | null {
  if (date === null || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  return -daysUntil(date);
}

/**
 * What the tiles below are marked to, and how far behind the calendar that mark is.
 *
 * Two different dates, deliberately both stated rather than collapsed into one: `report.as_of` is
 * when the *ledger* was read, and `price_as_of` is the close each position is *priced* at. They are
 * not the same claim, and a page that prints only the first invites a reader to assume the prices
 * are that fresh too.
 *
 * Escalates past `STALE_DAYS_WARN_THRESHOLD` to the same `.callout-warn` treatment
 * `ReferenceDeskSection` already uses on this page, so the portfolio headline and the desk card
 * agree about what counts as stale instead of one warning while the other stays quiet.
 *
 * The day count is derived client-side rather than read from a server field, matching
 * `priceAsOfRange`'s own reasoning: it is a pure function of dates already on the wire, and a
 * second server-side figure would be one more thing that can disagree with the rows it summarises.
 */
function PortfolioMarkNote({ report }: { report: PortfolioReport }) {
  const { t } = useT();
  const pricing = priceAsOfRange(report);

  if (pricing === null) {
    return (
      <div className="muted overview-mark-note">
        {t("misc.overview.mark.nothingPriced", { asOf: report.as_of })}
      </div>
    );
  }

  const behind = calendarDaysBehind(pricing.latest);
  const stale = behind !== null && behind > STALE_DAYS_WARN_THRESHOLD;
  const priced =
    pricing.earliest === pricing.latest ? (
      <Trans k="misc.overview.mark.pricedSingle" values={{ date: <strong>{pricing.latest}</strong> }} />
    ) : (
      <Trans
        k="misc.overview.mark.pricedRange"
        values={{
          range: (
            <strong>
              {pricing.earliest} → {pricing.latest}
            </strong>
          ),
          distinct: pricing.distinct,
        }}
      />
    );

  if (stale && behind !== null) {
    return (
      <div className="callout callout-warn overview-mark-callout" role="alert">
        <strong>{t("misc.overview.mark.staleHeadline", { behind, date: pricing.latest })}</strong>{" "}
        {t("misc.overview.mark.staleFooter", { asOf: report.as_of })}
      </div>
    );
  }

  const markKey: MessageKey =
    behind === null
      ? "misc.overview.mark.noBehind"
      : behind <= 0
        ? "misc.overview.mark.today"
        : behind === 1
          ? "misc.overview.mark.behind_one"
          : "misc.overview.mark.behind_other";

  return (
    <div className="muted overview-mark-note">
      <Trans k={markKey} values={{ asOf: report.as_of, priced, days: behind ?? 0 }} />
    </div>
  );
}

function PortfolioTiles({ report }: { report: PortfolioReport }) {
  const { t } = useT();
  const marketPartial = report.unpriced_symbols.length > 0;
  const cashPartial = report.accounts_without_cash.length > 0;
  const pctHint =
    report.total_unrealized_pct === null ? undefined : formatSignedFractionPct(report.total_unrealized_pct);
  const pricedOfHint = marketPartial
    ? pctHint
      ? t("misc.overview.tile.pricedOfHintWithPct", {
          priced: report.priced_position_count,
          total: report.positions.length,
          pct: pctHint,
        })
      : t("misc.overview.tile.pricedOfHint", {
          priced: report.priced_position_count,
          total: report.positions.length,
        })
    : pctHint;

  return (
    <div className="panel">
      <PortfolioMarkNote report={report} />
      <div className="tile-grid">
        <OverviewTile
          label={t("misc.overview.tile.totalEquity")}
          value={formatMoneyOrDash(report.total_equity)}
          variant={report.equity_is_complete ? undefined : "danger"}
          hint={
            report.equity_is_complete
              ? t("misc.overview.tile.totalEquityHintComplete")
              : t("misc.overview.tile.totalEquityHintIncomplete")
          }
          emphasize
        />
        <OverviewTile
          label={cashPartial ? t("misc.overview.tile.cashPartial") : t("misc.overview.tile.cash")}
          value={formatMoneyOrDash(report.cash_balance)}
          variant={cashPartial ? "danger" : undefined}
          hint={
            cashPartial
              ? t(
                  report.accounts_without_cash.length === 1
                    ? "misc.overview.cash.accountsExcluded_one"
                    : "misc.overview.cash.accountsExcluded_other",
                  { count: report.accounts_without_cash.length },
                )
              : undefined
          }
        />
        <OverviewTile
          label={
            marketPartial ? t("misc.overview.tile.unrealizedPnlPartial") : t("misc.overview.tile.unrealizedPnl")
          }
          value={
            report.total_unrealized === null
              ? "—"
              : formatSignedMoney(report.total_unrealized)
          }
          tone={report.total_unrealized === null ? "" : moneyTone(report.total_unrealized)}
          variant={marketPartial ? "danger" : undefined}
          hint={pricedOfHint}
        />
        <OverviewTile
          label={t("misc.overview.tile.positions")}
          value={String(report.positions.length)}
          hint={
            marketPartial
              ? t("misc.overview.tile.unpricedHint", { count: report.unpriced_symbols.length })
              : undefined
          }
        />
      </div>
    </div>
  );
}

function OverviewTile({
  label,
  value,
  hint,
  variant,
  emphasize,
  tone,
}: {
  label: string;
  value: string;
  hint?: string | undefined;
  variant?: "danger" | undefined;
  emphasize?: boolean;
  tone?: "pos" | "neg" | "";
}) {
  return (
    <div className={`stat tile${variant ? ` tile-${variant}` : ""}`}>
      <span className="label">{label}</span>
      <span className={`value${emphasize ? " value-emphasize" : ""}${tone ? ` ${tone}` : ""}`}>
        {value}
      </span>
      {hint && <span className="tile-hint">{hint}</span>}
    </div>
  );
}

// --- section: market context --------------------------------------------------------------------

function MarketSection({
  snapshot,
  phase,
  message,
}: {
  snapshot: MacroSnapshot | null;
  phase: "loading" | "loaded" | "error";
  message: string | null;
}) {
  const { t } = useT();
  return (
    <section className="overview-section" aria-labelledby="overview-market-heading">
      <SectionHead
        id="overview-market-heading"
        title={t("misc.overview.section.market")}
        to="/macro"
        linkLabel={t("misc.overview.link.market")}
      />
      {phase === "loading" && (
        <div className="panel">
          <Skeleton variant="tiles" rows={4} what={t("misc.overview.market.skeletonWhat")} />
        </div>
      )}
      {phase === "error" && (
        <div className="panel callout callout-danger">
          {message
            ? t("misc.overview.market.failedWithMessage", { message })
            : t("misc.overview.market.failed")}
        </div>
      )}
      {/* `colorAllChanges`: on this glance-first page the up/down direction is coloured on every tile,
          including the 10-Year yield and WTI that the Macro page deliberately leaves grey. See the
          prop's own docstring for why the two pages differ on purpose. */}
      {phase === "loaded" && snapshot && <MacroKeyIndicators snapshot={snapshot} colorAllChanges />}
      {/* A second destination out of Market context, alongside the macro summary above: looking up
          one symbol's own chart and thesis, which nothing in the macro snapshot answers. Rendered
          regardless of `phase` -- it names a different page than the one this section's own fetch
          feeds, so a failed macro fetch has no bearing on whether this link is still useful. */}
      <div className="overview-more-link">
        {/* `/symbol`, not the legacy `/ticker`: Ticker and Report were merged into Symbol and both old
            paths are now `RedirectToSymbol` shims (see `App.tsx`). Linking at the shim costs every
            reader a redirect and keeps a dead name alive in the one place the app still writes it. */}
        <Link className="overview-section-link" to="/symbol">
          {t("misc.overview.link.ticker")}
        </Link>
      </div>
    </section>
  );
}

/**
 * The Fear & Greed card, one cell of the Fear-&-Greed/calendar/attention row. It reads the same macro
 * snapshot `MarketSection` above does (Fear & Greed lives on `snapshot.fear_greed`), so it repeats
 * that fetch's phase rather than owning a second one. On failure it stays terse: `MarketSection`
 * right above already prints the full "Market context failed to load" error, so a second copy of the
 * same message here would only be noise — the reader has already been told, one card up.
 *
 * **No `title` on the card.** `FearGreedGauge` renders its own `<h2>Fear &amp; Greed</h2>` (with the
 * CNN/composite provenance badge beside it, which is part of the same claim and cannot be split off).
 * A card title here would put a second element with that same accessible name on the page, so the
 * card head carries only the expand control and the gauge keeps its heading. The gauge is long — a
 * score block, a meter, a history chart, the previous-close grid, a component table and any warnings
 * — which is exactly what `expandable` is for: `md` while it sits in the row, full height on request.
 */
function MarketFearGreedCard({
  snapshot,
  phase,
}: {
  snapshot: MacroSnapshot | null;
  phase: "loading" | "loaded" | "error";
}) {
  const { t } = useT();
  return (
    <Card
      id="fear-greed"
      height="md"
      label={t("misc.fearGreed.title")}
      panelClassName="overview-fg-card"
      expandable
    >
      {phase === "loaded" && snapshot && <FearGreedGauge data={snapshot.fear_greed} />}
      {/* Terse on purpose: `MarketSection` right above prints the full "Market context failed to load"
          error (with its status code and message), and the two cards share the one macro fetch — a
          second copy of the same detail here, status code and all, would just be noise one card down. */}
      {phase === "error" && <div className="placeholder">{t("misc.overview.fearGreed.unavailable")}</div>}
      {phase === "loading" && (
        <Skeleton variant="tiles" rows={1} what={t("misc.overview.fearGreed.skeletonWhat")} />
      )}
    </Card>
  );
}

// --- section: programme status -------------------------------------------------------------------

/**
 * Three facts the landing page otherwise hides entirely: whether the evolution/competition loop is
 * running, whether the agent/model layer behind Trading Agents can start a run, and the newest
 * competition round that actually has a leaderboard. Flagged as gap G1 in
 * `docs/STRATEGY-AGENT-UX-ANALYSIS.md` -- a reader had no way to learn any of these three without
 * opening `/competition` or `/trading-agents` directly and checking for themselves.
 *
 * Three independent fetches, exactly like every other section on this page: one failing renders a
 * muted "unavailable" line on that one stat rather than throwing or blanking the other two.
 */
function ProgrammeSection() {
  const { t } = useT();
  const { loopState, phase: loopPhase } = useLoopState();
  const { config: agentConfig, phase: agentPhase } = useAgentAvailability();
  const { round: newestRound, phase: roundPhase } = useNewestScoredRound();

  return (
    <section className="overview-section" aria-labelledby="overview-programme-heading">
      <SectionHead
        id="overview-programme-heading"
        title={t("misc.overview.programme.heading")}
        to="/competition"
        linkLabel={t("misc.overview.link.programme")}
      />
      <div className="panel tile-grid">
        <ProgrammeStat
          label={t("misc.overview.programme.loopLabel")}
          to="/competition"
          phase={loopPhase}
          pill={loopState ? loopPill(loopState, t) : null}
        />
        <ProgrammeStat
          label={t("misc.overview.programme.agentLabel")}
          to="/agents"
          phase={agentPhase}
          pill={agentConfig ? agentPill(agentConfig, t) : null}
        />
        <ProgrammeStat
          label={t("misc.overview.programme.newestRoundLabel")}
          to="/competition"
          phase={roundPhase}
          pill={roundPhase === "loaded" ? roundPill(newestRound, t) : null}
        />
      </div>
      {/* This strip's own three fetches (loop/agent/round) all summarise the competition-and-agents
          programme; the Strategy Lab -- rule cards, backtests, timeframes -- is a sibling system this
          page otherwise never reaches, so it gets a plain link rather than a fourth tile with nothing
          of its own to fetch. */}
      <div className="overview-more-link">
        <Link className="overview-section-link" to="/strategy">
          {t("misc.overview.link.strategy")}
        </Link>
      </div>
    </section>
  );
}

/** `LoopState` -> the pill `ProgrammeSection` shows for the strategy loop. `"running"`/`"stopping"`
 *  are the two states in which the loop is doing something right now; every other state (including
 *  the "never started" 404 folded into `"idle"` by `useLoopState`) reads as the same quiet "Idle". */
function loopPill(state: LoopState, t: Translator): ReactNode {
  switch (state) {
    case "running":
      return <StatusPill tone="info" label={t("misc.overview.programme.loopRunning")} />;
    case "stopping":
      return <StatusPill tone="warn" label={t("misc.overview.programme.loopStopping")} />;
    case "idle":
    case "stopped":
    case "failed":
      return <StatusPill tone="neutral" label={t("misc.overview.programme.loopIdle")} />;
    default: {
      const _exhaustive: never = state;
      void _exhaustive;
      return <StatusPill tone="neutral" label={t("misc.overview.programme.loopIdle")} />;
    }
  }
}

/** `agent_reason` only ever rides along as the pill's `detail` when the layer is unavailable -- when
 *  it is available there is nothing to explain, and an empty `title`/`aria-description` is worse than
 *  none at all. */
function agentPill(config: TradingAgentsConfig, t: Translator): ReactNode {
  if (config.agent_available) {
    return <StatusPill tone="ok" label={t("misc.overview.programme.agentReady")} />;
  }
  return (
    <StatusPill
      tone="warn"
      label={t("misc.overview.programme.agentUnavailable")}
      detail={config.agent_reason || undefined}
    />
  );
}

/** `null` here has already been narrowed by the caller to mean "the fetch succeeded and no round
 *  has results yet" -- see `useNewestScoredRound`'s own docstring for why a round with
 *  `has_results: false` never reaches this function at all. */
function roundPill(round: RoundSummary | null, t: Translator): ReactNode {
  if (round === null) {
    return <StatusPill tone="neutral" label={t("misc.overview.programme.roundNone")} />;
  }
  return <StatusPill tone="info" label={round.label} detail={round.round_id} />;
}

/**
 * One stat in the programme strip: a label, the pill (or a muted loading/unavailable line while
 * `pill` is `null`), and a link through to the page that stat summarises. The whole tile is the link
 * -- `a { color: inherit; text-decoration: none; }` in `styles.css` already makes an anchor read as
 * plain as the `div`-based tiles elsewhere on this page, so no extra styling is needed to keep it
 * from looking like ordinary link text.
 */
function ProgrammeStat({
  label,
  to,
  phase,
  pill,
}: {
  label: string;
  to: string;
  phase: FetchPhase;
  pill: ReactNode;
}) {
  const { t } = useT();
  return (
    <Link to={to} className="stat tile overview-programme-tile">
      <span className="label">{label}</span>
      <span className="value overview-programme-value">
        {phase === "error" ? (
          <span className="muted">{t("misc.overview.programme.unavailable")}</span>
        ) : pill ? (
          pill
        ) : (
          <span className="muted">{t("common.loading")}</span>
        )}
      </span>
    </Link>
  );
}

// --- section: reference desk --------------------------------------------------------------------

function ReferenceDeskSection({
  desk,
  phase,
  message,
}: {
  desk: PaperDeskState | null;
  phase: FetchPhase;
  message: string | null;
}) {
  const { t } = useT();
  return (
    <section className="overview-section" aria-labelledby="overview-desk-heading">
      {/* The pill and the caveat below are not decoration. This panel prints a RETURN % column for
          every seated agent, and it sits directly under the real-money equity tiles at the top of the
          same page with nothing between them -- so a reader glancing down the column has no marker
          telling them the second set of percentages is play money. Per docs/COPY-STYLE.md rule 6,
          simulated money keeps a *visible* short form: a pill in the header and one line above the
          cards, never folded behind a disclosure. */}
      <SectionHead
        id="overview-desk-heading"
        title={t("misc.overview.section.desk")}
        to="/paper-desk"
        linkLabel={t("misc.overview.link.desk")}
        pill={<StatusPill tone="warn" label={t("ui.pill.simulated")} />}
      />
      <p className="muted overview-desk-caveat">{t("misc.overview.referenceDesk.caveat")}</p>
      {phase === "loading" && (
        <div className="panel">
          <Skeleton variant="rows" rows={5} what={t("misc.overview.desk.skeletonWhat")} />
        </div>
      )}
      {phase === "error" && (
        <div className="panel callout callout-danger">
          {message
            ? t("misc.overview.desk.failedWithMessage", { message })
            : t("misc.overview.desk.failed")}
        </div>
      )}
      {phase === "loaded" && desk && (
        <>
          {desk.stale_days > STALE_DAYS_WARN_THRESHOLD && (
            <div className="panel callout callout-warn">
              {t("misc.overview.desk.staleCallout", { days: desk.stale_days, bar: desk.latest_bar })}
            </div>
          )}
          {/* Three books, one equal-height row. The old layout placed them by `data-purpose` into
              named grid areas (Trading spanning a tall left column, Savings over Roth on the right)
              with `align-items: start`; that existed only to absorb the fact that a card with six
              desks was taller than a card with one. The grid track now sets the height and each
              card's own body scrolls, so the special-casing has nothing left to do -- and source
              order (the order the books arrive in) is a better rule than a hardcoded arrangement
              that silently drops any fourth book the wire ever carries. */}
          <CardGrid height="md" min="300px">
            {desk.books.map((book) => (
              <BookCard key={book.purpose} book={book} />
            ))}
          </CardGrid>
        </>
      )}
    </section>
  );
}

/**
 * One book, one card. Each desk within it keeps its own return — never summed across desks in the
 * same book, and never summed across books. See the module docstring's third honesty rule: this
 * page reports what each reference agent is holding, per book, not a combined "my performance"
 * figure that does not exist on the wire and should not be invented here.
 */
function BookCard({ book }: { book: Book }) {
  const { t } = useT();
  const deskCount = book.desks.length;
  return (
    <Card
      id={`book-${book.purpose}`}
      height="md"
      label={t("misc.overview.desk.cardLabel", { name: book.label })}
      panelClassName="overview-book-card"
      title={<h3>{book.label}</h3>}
      status={
        <span className="badge">
          {t(deskCount === 1 ? "misc.overview.desk.seated_one" : "misc.overview.desk.seated_other", {
            count: deskCount,
          })}
        </span>
      }
      // The book's benchmark is what every return in the body is read against, so it is pinned below
      // the table rather than scrolling away with it. It stays one book's own `benchmark.return_pct`
      // straight off the wire -- never a figure combined with the desk returns above it.
      footer={
        <p className="muted overview-book-benchmark">
          {t("misc.overview.desk.benchmarkLabel", { name: book.benchmark.label ?? book.benchmark.symbol })}{" "}
          <span className={fractionStringTone(book.benchmark.return_pct)}>
            {formatSignedFractionPctString(book.benchmark.return_pct)}
          </span>
        </p>
      }
    >
      {deskCount === 0 ? (
        <div className="placeholder">{t("misc.overview.desk.noCardsSeated")}</div>
      ) : (
        // No `.table-wrap` around this table: the card body IS the scroll container, and a second
        // scrolling box inside it is what stops `.scroll-region table thead th`'s sticky header from
        // sticking -- the header would scroll away with the rows it labels.
        <table className="data-table overview-desk-table">
          <thead>
            <tr>
              <th scope="col">{t("misc.overview.desk.header.agent")}</th>
              <th scope="col">{t("misc.overview.desk.header.return")}</th>
              <th scope="col">{t("misc.overview.desk.header.openPositions")}</th>
            </tr>
          </thead>
          <tbody>
            {book.desks.map((d) => (
              <tr key={d.agent_id}>
                <td>{d.display_name}</td>
                <td className={fractionStringTone(d.total_return)}>
                  {formatSignedFractionPctString(d.total_return)}
                </td>
                <td>{d.open_positions}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

// --- section: tax --------------------------------------------------------------------------------

/**
 * `formatSignedMoney`/`moneyTone` from `@/api/portfolio`, adapted to the tax module's own
 * `formatMoney` -- same regex-only sign check (never `parseFloat`), duplicated rather than imported
 * because each API client in this codebase keeps its own copy of these primitives (see
 * `@/api/tax`'s own module docstring on why its `formatMoney`/`addMoney` are not shared).
 */
function formatSignedTaxMoney(value: DecimalString): string {
  const trimmed = value.trim();
  const isZeroValue = /^[+-]?0*(\.0*)?$/.test(trimmed);
  if (isZeroValue || trimmed.startsWith("-")) return formatTaxMoney(value);
  return `+${formatTaxMoney(value)}`;
}

function taxMoneyTone(value: DecimalString): "pos" | "neg" | "" {
  const trimmed = value.trim();
  if (/^[+-]?0*(\.0*)?$/.test(trimmed)) return "";
  return trimmed.startsWith("-") ? "neg" : "pos";
}

/** The earliest `repurchase_safe_on` among symbols whose window is still open -- the next date any
 *  open wash-sale exposure on the ledger clears, or `null` when nothing is open. Plain string
 *  comparison is safe here: every date on the wire is `YYYY-MM-DD`, which sorts lexicographically in
 *  calendar order. */
function soonestWindowClose(tracker: WashSaleTracker): string | null {
  let soonest: string | null = null;
  for (const symbol of tracker.symbols) {
    if (!symbol.window_is_open) continue;
    if (soonest === null || symbol.repurchase_safe_on < soonest) soonest = symbol.repurchase_safe_on;
  }
  return soonest;
}

/**
 * Year-to-date realised gain, plus the wash-sale exposure this page's `AttentionSection` already
 * flags when it is non-zero. `tracker` is the same `WashSaleTracker` `useWashTracker` fetches for
 * that section -- reused here rather than fetched again, so this tile and the Attention list can
 * never disagree about how many windows are open.
 */
function TaxSection({
  taxReport,
  taxPhase,
  taxMessage,
  taxYear,
  tracker,
  washPhase,
  isOwner,
}: {
  taxReport: TaxReport | null;
  taxPhase: FetchPhase;
  taxMessage: string | null;
  taxYear: number;
  tracker: WashSaleTracker | null;
  washPhase: FetchPhase;
  /** `/api/tax` and `/api/tax/wash-sales` are both owner-only. A member never fetches either, and
   *  the whole tile -- including the countdown, which is otherwise pure client-side arithmetic --
   *  is replaced by one compact line, since this tile is presented as a summary of `/tax`, a page a
   *  member cannot open either. */
  isOwner: boolean;
}) {
  const { t } = useT();
  const ytdGain = taxReport ? addMoney(taxReport.gains.short_term_gain, taxReport.gains.long_term_gain) : null;
  const soonest = tracker ? soonestWindowClose(tracker) : null;

  // One card, not the two stacked `.panel`s this used to be (a countdown box above a tile box). Two
  // boxes for one summary read as two summaries, and in an equal-height row they also made this
  // column taller than anything in it justified.
  return (
    <Card
      id="tax"
      height="sm"
      label={t("misc.overview.section.tax")}
      panelClassName="overview-tax-card"
      aria-labelledby="overview-tax-heading"
      title={<h2 id="overview-tax-heading">{t("misc.overview.section.tax")}</h2>}
      actions={
        <Link className="overview-section-link" to="/tax">
          {t("misc.overview.link.tax")}
        </Link>
      }
    >
      {!isOwner && <p className="muted overview-owner-only-note">{t("auth.ownerOnly.notice")}</p>}
      {/* Days to Dec 31 of the year `taxReport` is for. A pure calendar computation -- it needs no
          fetch of its own and is the first thing in the body, outside every `taxPhase` branch below,
          so a failed tax-report fetch never hides the one piece of this card that never depended on
          it. (Not the head's `status` slot: the bar is a full-width progress track, and `.card-head`
          is a single baseline-aligned row.) */}
      {isOwner && (
        <CountdownBar label={t("misc.overview.tax.yearEndLabel")} deadlineDate={`${taxYear}-12-31`} />
      )}
      {isOwner && taxPhase === "loading" && (
        <Skeleton variant="tiles" rows={3} what={t("misc.overview.tax.skeletonWhat")} />
      )}
      {isOwner && taxPhase === "error" && (
        <div className="callout callout-danger">
          {taxMessage
            ? t("misc.overview.tax.failedWithMessage", { message: taxMessage })
            : t("misc.overview.tax.failed")}
        </div>
      )}
      {isOwner && taxPhase === "loaded" && ytdGain !== null && (
        <div className="tile-grid">
          <OverviewTile
            label={t("misc.overview.tax.tile.ytdGain")}
            value={formatSignedTaxMoney(ytdGain)}
            tone={taxMoneyTone(ytdGain)}
            emphasize
            hint={t("misc.overview.tax.tile.ytdGainHint", { year: taxYear })}
          />
          <OverviewTile
            label={t("misc.overview.tax.tile.deferredWash")}
            value={tracker ? formatTaxMoney(tracker.total_deferred) : "—"}
            hint={washPhase === "error" ? t("misc.overview.tax.tile.washUnavailable") : undefined}
          />
          <OverviewTile
            label={t("misc.overview.tax.tile.openWindows")}
            value={tracker ? String(tracker.open_window_count) : "—"}
            hint={
              tracker && tracker.open_window_count > 0 && soonest
                ? t("misc.overview.tax.tile.soonestClose", { date: soonest })
                : washPhase === "error"
                  ? t("misc.overview.tax.tile.washUnavailable")
                  : undefined
            }
          />
        </div>
      )}
    </Card>
  );
}

// --- section: activity ---------------------------------------------------------------------------

/**
 * The newest transaction on the ledger, plus the filtered-set total `transactionsApi.list` returns
 * alongside it. `page.as_of` is when the ledger itself was last read -- not necessarily the same date
 * as `page.transactions[0].trade_date`, which is why both render rather than only one standing in
 * for the other.
 */
function ActivitySection({
  page,
  phase,
  message,
  isOwner,
}: {
  page: TransactionPage | null;
  phase: FetchPhase;
  message: string | null;
  /** `/api/portfolio/transactions` sits under the owner-only `/api/portfolio` prefix. A member never
   *  fetches it, and this tile becomes one compact line rather than the loading/error/loaded states
   *  below, in place of a summary of `/activity`, a page a member cannot open either. */
  isOwner: boolean;
}) {
  const { t } = useT();
  const lastTxn = page?.transactions[0] ?? null;

  return (
    <Card
      id="activity"
      height="sm"
      label={t("misc.overview.section.activity")}
      panelClassName="overview-activity-card"
      aria-labelledby="overview-activity-heading"
      title={<h2 id="overview-activity-heading">{t("misc.overview.section.activity")}</h2>}
      actions={
        <Link className="overview-section-link" to="/activity">
          {t("misc.overview.link.activity")}
        </Link>
      }
    >
      {!isOwner && <p className="muted overview-owner-only-note">{t("auth.ownerOnly.notice")}</p>}
      {isOwner && phase === "loading" && (
        <Skeleton variant="tiles" rows={2} what={t("misc.overview.activity.skeletonWhat")} />
      )}
      {isOwner && phase === "error" && (
        <div className="callout callout-danger">
          {message
            ? t("misc.overview.activity.failedWithMessage", { message })
            : t("misc.overview.activity.failed")}
        </div>
      )}
      {isOwner && phase === "loaded" && page && (
        <div className="tile-grid">
          <OverviewTile
            label={t("misc.overview.activity.tile.lastTransaction")}
            value={lastTxn ? lastTxn.trade_date : "—"}
            hint={
              lastTxn
                ? t("misc.overview.activity.tile.lastTransactionHint", {
                    action: actionLabel(lastTxn.action),
                    symbol: lastTxn.symbol ?? "",
                  })
                : t("misc.overview.activity.tile.none")
            }
          />
          <OverviewTile
            label={t("misc.overview.activity.tile.total")}
            value={String(page.total)}
            hint={page.as_of ? t("misc.overview.activity.tile.asOf", { date: page.as_of }) : undefined}
          />
        </div>
      )}
    </Card>
  );
}

// --- section: filer consensus ---------------------------------------------------------------------

/**
 * The top consensus buy and sell across every tracked filer -- see `useLazyConsensus`'s own
 * docstring for why this fetch is deferred and never wired into the page's "Fetch data" button.
 *
 * `checked.length` renders alongside every count on purpose: `@/api/consensus`'s own module
 * docstring is explicit that `buyer_count`/`seller_count` are counted out of the filers actually
 * checked this run, never the full tracked universe, and any UI built on this data must say so
 * rather than dropping it once the happy path renders.
 */
function ConsensusSection({
  data,
  phase,
}: {
  data: ConsensusResponse | null;
  phase: FetchPhase;
}) {
  const { t } = useT();
  const topBuy = data?.buys[0] ?? null;
  const topSell = data?.sells[0] ?? null;
  const checkedCount = data?.checked.length ?? 0;

  return (
    <section className="overview-section" aria-labelledby="overview-consensus-heading">
      <SectionHead
        id="overview-consensus-heading"
        title={t("misc.overview.section.consensus")}
        // `/filers?tab=consensus`, not the legacy `/consensus`: Institutions and Consensus were merged
        // into Filers and `/consensus` is now a `RedirectToFilers` shim (see `App.tsx`). Same argument
        // as the `/symbol` link in `MarketSection` -- link at the page, not at the redirect to it.
        to="/filers?tab=consensus"
        linkLabel={t("misc.overview.link.consensus")}
      />
      <div className="panel">
        {phase === "loading" && (
          <Skeleton variant="tiles" rows={2} what={t("misc.overview.consensus.skeletonWhat")} />
        )}
        {phase === "error" && (
          <div className="tile-grid">
            <OverviewTile label={t("misc.overview.consensus.tile.topBuy")} value="—" />
            <OverviewTile label={t("misc.overview.consensus.tile.topSell")} value="—" />
          </div>
        )}
        {phase === "loaded" && data && (
          <div className="tile-grid">
            <OverviewTile
              label={t("misc.overview.consensus.tile.topBuy")}
              value={topBuy ? (topBuy.ticker ?? topBuy.issuer) : "—"}
              hint={
                topBuy
                  ? t("misc.overview.consensus.tile.buyerHint", {
                      count: topBuy.buyer_count,
                      checked: checkedCount,
                    })
                  : t("misc.overview.consensus.tile.none")
              }
            />
            <OverviewTile
              label={t("misc.overview.consensus.tile.topSell")}
              value={topSell ? (topSell.ticker ?? topSell.issuer) : "—"}
              hint={
                topSell
                  ? t("misc.overview.consensus.tile.sellerHint", {
                      count: topSell.seller_count,
                      checked: checkedCount,
                    })
                  : t("misc.overview.consensus.tile.none")
              }
            />
          </div>
        )}
      </div>
    </section>
  );
}

// --- section: calendar -------------------------------------------------------------------------

/**
 * Upcoming FOMC meetings and earnings dates for the user's holdings.
 *
 * The `useEventCalendar` fetch used to live here, but it was lifted up into `Overview()` so the
 * page-level "Fetch data" button can force this card to refresh from source alongside the other
 * four; the state now arrives as props, the same way `PortfolioSection`/`ReferenceDeskSection`
 * receive theirs. This section still owns its own `expanded` state — nothing outside this row needs
 * to know whether the list is unfurled.
 *
 * There is no `/calendar` route, so there is no link out of this card — linking to a page that does
 * not exist would be worse than no link at all.
 *
 * Phase gating mirrors `ReferenceDeskSection` exactly, plus the `empty` phase `usePortfolio`-style
 * hooks also carry: a quiet stretch with no upcoming events is a legitimate resolved state, not a
 * failure, and is worded accordingly rather than reusing the error treatment.
 *
 * **`height="auto"`, and a `Card` with no head of its own.** `EventCalendar` already is a card: it
 * brings a `.panel`, a pinned head (its "Calendar" heading plus the expand control) and a
 * `ScrollRegion` body. Giving the wrapper an `md` body would put a second scroll region inside the
 * first and a second "Calendar" heading beside the first; `height="auto"` makes the wrapper
 * contribute only what the component cannot give itself — the grid track that lines this card up
 * with Fear & Greed and Attention, and the full-row span when it expands. `Overview.css` makes
 * `EventCalendar`'s own region fill that track, so there is still exactly one scrollbar and the
 * heading still never scrolls. The component's existing toggle drives the card's *controlled*
 * `expanded`, so one control moves both.
 */
function EventCalendarCard({
  calendar,
  phase,
  message,
  slow,
  refresh,
}: {
  calendar: EventCalendarData | null;
  phase: CalendarPhase;
  message: string | null;
  slow: boolean;
  refresh: () => void;
}) {
  const { t } = useT();
  // Collapsed by default: the card sits capped-and-scrolling beside Fear & Greed until the reader
  // asks for the whole list.
  const [expanded, setExpanded] = useState(false);

  // The "Calendar" heading lives inside the loaded `EventCalendar` panel (next to its expand/collapse
  // control) rather than in the card head. The transient loading/error/empty bodies below carry the
  // word "Calendar" in their copy instead, so the card is still identifiable before its data lands —
  // without a second "Calendar" heading that would collide with the panel's.
  return (
    <Card
      id="calendar"
      height="auto"
      panelClassName="overview-calendar-card"
      expanded={expanded}
      onExpandedChange={setExpanded}
    >
      {phase === "loading" && (
        // `Skeleton` owns the "still loading" announcement (`role="status"`), so the panel itself is
        // no longer a live region -- two nested polite regions would announce the same fetch twice.
        // `aria-live` stays on the slow note, which appears seconds later: a screen-reader user who
        // has already moved on still hears the explanation rather than sitting in the same silence a
        // sighted reader was left in.
        <div aria-live="off">
          <Skeleton variant="rows" rows={4} what={t("misc.overview.calendar.skeletonWhat")} />
          {slow && (
            <span className="overview-calendar-slow" aria-live="polite">
              {t("misc.overview.calendar.slowNote")}
            </span>
          )}
        </div>
      )}
      {phase === "error" && (
        <div className="callout callout-danger">
          {message
            ? t("misc.overview.calendar.failedWithMessage", { message })
            : t("misc.overview.calendar.failed")}{" "}
          <button type="button" className="decision-expand-btn" onClick={refresh}>
            {t("misc.overview.calendar.tryAgain")}
          </button>
        </div>
      )}
      {phase === "empty" && <div className="placeholder">{t("misc.eventCalendar.noEvents")}</div>}
      {phase === "loaded" && calendar && (
        <EventCalendar
          calendar={calendar}
          expanded={expanded}
          onToggleExpand={() => setExpanded((v) => !v)}
        />
      )}
    </Card>
  );
}

// --- section: attention -----------------------------------------------------------------------

interface AttentionEntry {
  key: string;
  message: string;
  /** Where this entry is actionable. `null` for the "could not be checked" notes, which name a fetch
   *  that failed rather than a finding a reader can go and act on. */
  to: string | null;
  /** The one extra fact that turns a count into something the reader can act on -- currently only
   *  the wash-sale line's soonest safe repurchase date. Rendered outside the `<Link>` so the link
   *  text stays the claim, not the claim plus its footnote. */
  note?: string;
}

function AttentionSection({
  report,
  portfolioPhase,
  desk,
  deskPhase,
  tracker,
  washPhase,
  washMessage,
  isOwner,
}: {
  report: PortfolioReport | null;
  // `usePortfolio`'s own phase, not the local `FetchPhase`: it carries a fourth state, "empty",
  // which is *resolved* (the ledger has no positions) rather than pending. Widening `FetchPhase` to
  // absorb it would have blurred that distinction and made an empty portfolio look like a loading
  // one, permanently suppressing the all-clear for anyone whose ledger is genuinely empty.
  portfolioPhase: PortfolioPhase;
  desk: PaperDeskState | null;
  deskPhase: FetchPhase;
  tracker: WashSaleTracker | null;
  washPhase: FetchPhase;
  washMessage: string | null;
  /** Gates the `/manager` cross-link only. Everything else in this card is fed by `report`/`tracker`,
   *  which `Overview()` has already resolved to literal absent values for a member (see its own
   *  comment on the owner-only fetches), so the list itself needs no second gate here. */
  isOwner: boolean;
}) {
  const { t } = useT();
  const items: AttentionEntry[] = [];
  const unavailable: AttentionEntry[] = [];

  if (tracker) {
    if (tracker.open_window_count > 0) {
      const windowsKey = tracker.open_window_count === 1 ? "1" : "n";
      const symbolsKey = tracker.symbol_count === 1 ? "1" : "n";
      const washKey = `misc.overview.attention.washOpen_${windowsKey}_${symbolsKey}` as MessageKey;
      // The count alone said what is true and nothing about what to do with it. `repurchase_safe_on`
      // is already on every tracker symbol (`soonestWindowClose` above reads the same field for the
      // Tax tile), so the earliest one rides along here -- the date the *next repurchase* stops
      // creating a fresh wash sale. It is emphatically not when deferred money comes back; that
      // happens on a lot sale, never on a calendar date (see `@/api/washsales`).
      const soonestSafe = soonestWindowClose(tracker);
      items.push({
        key: "wash-open",
        message: t(washKey, { windows: tracker.open_window_count, symbols: tracker.symbol_count }),
        to: "/tax?tab=wash",
        ...(soonestSafe ? { note: t("misc.overview.attention.soonest", { date: soonestSafe }) } : {}),
      });
    }
  } else if (washPhase === "error") {
    unavailable.push({
      key: "wash-unavailable",
      message: washMessage
        ? t("misc.overview.attention.washUnavailableWithMessage", { message: washMessage })
        : t("misc.overview.attention.washUnavailable"),
      to: null,
    });
  }

  if (report) {
    if (report.warnings.length > 0) {
      items.push({
        key: "portfolio-warnings",
        message: t(
          report.warnings.length === 1
            ? "misc.overview.attention.portfolioWarning_one"
            : "misc.overview.attention.portfolioWarning_other",
          { count: report.warnings.length },
        ),
        to: "/portfolio",
      });
    }
  }
  // Note: `report === null` here can mean "still loading," "genuinely empty," or "the fetch
  // failed" — `PortfolioSection` above already renders the failure explicitly, and duplicating
  // that as an "unavailable" line here would just be noise for the loading/empty cases, which are
  // not failures. Only the wash-sale and desk fetches (checked against their own `phase` below and
  // above) get an explicit unavailable note, since they have no other section-level state to fall
  // back on for that signal.

  if (desk) {
    if (desk.stale_days > STALE_DAYS_WARN_THRESHOLD) {
      items.push({
        key: "desk-stale",
        message: t("misc.overview.attention.deskStale", { days: desk.stale_days, bar: desk.latest_bar }),
        to: "/paper-desk",
      });
    }
  } else if (deskPhase === "error") {
    unavailable.push({
      key: "desk-unavailable",
      message: t("misc.overview.attention.deskUnavailable"),
      to: null,
    });
  }

  // "Nothing needs your attention" is a claim about three fetches, so it may only be made once all
  // three have come back. Checking `items.length === 0` alone was true during the very first paint
  // -- every source still null, nothing collected yet -- so the panel rendered a confident all-clear
  // and then replaced it with "42 open wash-sale windows" a moment later. On a page whose whole job
  // is telling someone whether they need to act, a premature all-clear is worse than a spinner: a
  // reader who glances once and looks away has been told the opposite of the truth.
  const pending =
    portfolioPhase === "loading" || deskPhase === "loading" || washPhase === "loading";
  const clear = !pending && items.length === 0 && unavailable.length === 0;

  // Findings first, then the "could not be checked" notes, in ONE list inside ONE scroll region --
  // the card body. Two `sm` regions stacked in one panel gave this card two scrollbars and two tab
  // stops for a list that is usually three items long, and split a single question ("is there
  // anything I should look at?") across two boxes with the same accessible name. The two kinds are
  // still told apart: a finding is a link to where it is actionable, a note is muted plain text.
  const entries = [...items, ...unavailable];

  return (
    <Card
      id="attention"
      height="md"
      label={t("misc.overview.attention.heading")}
      panelClassName="overview-attention-card"
      aria-labelledby="overview-attention-heading"
      title={<h2 id="overview-attention-heading">{t("misc.overview.attention.heading")}</h2>}
      // The bridge to the Manager desk, which answers the neighbouring question this card cannot:
      // this list is standing state ("42 windows are open right now"), Manager's feed is the diff
      // against yesterday's snapshot ("MU's window closes in 2 days -- it didn't yesterday"). Owner
      // only, matching the route: `/manager` reads `/api/manager`, an owner-only prefix, so a member
      // offered this link would be offered a 403.
      actions={
        <>
          {/* Rendered in every state, including the all-clear and the still-checking one. The card
              names wash-sale exposure whether or not any is open, and a reader who wants to see the
              windows for themselves should not have to find the Tax page's Wash sales tab to do it. */}
          <Link className="overview-section-link" to="/tax?tab=wash">
            {t("misc.overview.attention.openWashSales")}
          </Link>
          {isOwner && (
            <Link className="overview-section-link" to="/manager">
              {t("misc.overview.attention.managerLink")}
            </Link>
          )}
        </>
      }
    >
      {pending && <p className="placeholder">{t("misc.overview.attention.checking")}</p>}
      {clear && <p className="placeholder">{t("misc.overview.attention.allClear")}</p>}
      {!clear &&
        (entries.length > 0 ? (
          <ul className="warning-list overview-attention-list">
            {entries.map((entry) => (
              <li
                key={entry.key}
                className={entry.to === null ? "overview-attention-unavailable muted" : undefined}
              >
                {entry.to === null ? entry.message : <Link to={entry.to}>{entry.message}</Link>}
                {entry.note && <span className="overview-attention-note">{entry.note}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">{t("misc.overview.attention.noIssuesFound")}</p>
        ))}
    </Card>
  );
}

// --- shared -----------------------------------------------------------------------------------

function SectionHead({
  id,
  title,
  to,
  linkLabel,
  pill,
}: {
  id: string;
  title: string;
  // Optional: `EventCalendarCard` has no full page to link through to (there is no `/calendar`
  // route), so it omits both rather than linking to a page that does not exist.
  to?: string;
  linkLabel?: string;
  /** A qualifier on everything under this heading, sat beside it -- currently only the reference
   *  desk's `SIMULATED`. Beside the heading rather than inside the panel, so it is read before the
   *  numbers it qualifies rather than after them. */
  pill?: ReactNode;
}) {
  return (
    <div className="overview-section-head">
      <div className="overview-section-head-title">
        <h2 id={id}>{title}</h2>
        {pill}
      </div>
      {to && linkLabel && (
        <Link className="overview-section-link" to={to}>
          {linkLabel}
        </Link>
      )}
    </div>
  );
}
