import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiRequestError, compareDecimalStrings } from "@/api/client";
import {
  formatShares,
  formatSharesPctChange,
  formatSignedShares,
  formatWeight,
  institutionsApi,
  type Action,
  type FundRef,
  type Holding,
  type HoldingChange,
  type PortfolioDelta,
  type Snapshot,
  type Source,
} from "@/api/institutions";
import { formatMoneyOrDash, formatSignedMoney, moneyTone } from "@/api/portfolio";
import { Card, CardGrid } from "@/components/Card";
import Collapsible from "@/components/Collapsible";
import Fetched from "@/components/Fetched";
import HoldingsPieChart from "@/components/HoldingsPieChart";
import InfoNote from "@/components/InfoNote";
import RecentMoves from "@/components/RecentMoves";
import { ScrollRegion } from "@/components/ScrollPanel";
import StatusPill from "@/components/StatusPill";
import { FilterBar, TableCaption } from "@/components/tableSort";
import { useFetch, type FetchPhase } from "@/hooks/useFetch";
import { Trans, useT, type Translator } from "@/i18n";
import { ACTION_LABEL_KEY, IssuerCell } from "@/pages/filers/shared";

import "./Institutions.css";

/** This page's own phase carries a 4th member, `"empty"`, that `useFetch`'s own `FetchPhase` does not
 *  (see that hook's docstring on why) -- derived from `FetchPhase` plus a length/`null` check on the
 *  loaded data, at each of this page's three fetch call sites below. */
type Phase = FetchPhase | "empty";

// `ACTION_LABEL_KEY` (the five-way new/exit/add/trim/hold vocabulary) and `IssuerCell` now live in
// `@/pages/filers/shared` -- this page and `Consensus.tsx` used to each keep a byte-identical copy
// of both (finding E1 in the Filers merge task). Tone stays local: it is genuinely page-specific
// styling, not duplicated content.
const ACTION_TONE: Record<Action, string> = {
  new: "inst-action-new",
  exit: "inst-action-exit",
  add: "inst-action-add",
  trim: "inst-action-trim",
  hold: "inst-action-hold",
};

/**
 * The translated equivalent of `@/api/institutions`'s exported `SOURCE_NOTE`.
 *
 * `SOURCE_NOTE` itself has to stay English-only: `api/institutions.test.ts` (outside this page's
 * scope) asserts its exact English wording directly (`toMatch(/US-listed equities/)` and the
 * like), so changing what it returns would break a test this change is not allowed to touch. This
 * page never reads `SOURCE_NOTE` for display any more -- it looks up the same two sentences from
 * the catalog instead, keyed by `fund.source`.
 */
function sourceNote(t: Translator, source: Source): string {
  return source === "13F"
    ? t("market.institutions.sourceNote.13F")
    : t("market.institutions.sourceNote.NPORT");
}

/**
 * Ask the page's question in reverse: not "what does this filer hold" but "who holds this symbol".
 *
 * **Navigates rather than rendering the answer here.** The holders panel already exists on the
 * ticker page, where the reader also gets price history and the rule editor for the same symbol.
 * Rendering a second copy inline would mean two components fetching the same slow endpoint and two
 * places to keep the "an empty list may mean I could not look" caveats correct -- and those caveats
 * are the part that must not drift. `uat/feedback/BACKLOG.md` asked for a way to *ask* the question
 * from here; it did not ask for the answer to be duplicated here.
 */
function SymbolLookup() {
  const { t } = useT();
  const navigate = useNavigate();
  const [value, setValue] = useState("");

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const symbol = value.trim().toUpperCase();
    if (symbol) navigate(`/symbol/${encodeURIComponent(symbol)}`);
  };

  return (
    <form className="panel inst-lookup" onSubmit={submit}>
      <label className="inst-lookup-label" htmlFor="inst-symbol-lookup">
        {t("market.institutions.lookup.label")}
      </label>
      <div className="inst-lookup-row">
        <input
          id="inst-symbol-lookup"
          className="inst-lookup-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="NVDA"
          aria-label={t("market.institutions.lookup.ariaLabel")}
        />
        <button type="submit" className="inst-lookup-submit">
          {t("market.institutions.lookup.submit")}
        </button>
      </div>
      <p className="muted inst-lookup-note">{t("market.institutions.lookup.note")}</p>
    </form>
  );
}

/**
 * The Institutions tab body: the symbol lookup, the filing-lag disclaimer, the cross-link to
 * Consensus, and the funds-loading phase machine feeding `InstitutionsContent`. Exported (as of the
 * Filers merge, UX refactor 2.2) so `Filers.tsx` can mount it as the "Institutions" tab's content
 * without a second `<h1>`/subtitle -- `Filers.tsx` supplies the shared banner for the merged page;
 * this component supplies everything below it, unchanged from what `Institutions()` (below) has
 * always rendered in that spot.
 */
export function InstitutionsView() {
  const { t } = useT();
  const fundsResult = useFetch<FundRef[]>(
    async () => {
      try {
        const r = await institutionsApi.funds();
        return r.funds;
      } catch (e) {
        // A 404 with copy naming an empty universe is the only 404 treated as "nothing to show" --
        // see `describeFetchError` and the identical guard on `WashSales.tsx`. Any other 404 (an
        // unknown route also answers 404) falls through to the real error state below rather than
        // rendering "no institutions tracked", which would be a false all-clear on a page whose
        // whole job is to say what a filer did.
        if (e instanceof ApiRequestError && e.status === 404 && /no funds/i.test(e.message)) {
          return [];
        }
        throw e;
      }
    },
    [],
    { formatError: (e) => describeFetchError(t, e, t("market.institutions.noun.noFunds")) },
  );

  return (
    <>
      <SymbolLookup />

      {/* The filing-lag caveat used to be said twice -- once as the pill's hover `title`, once again
          in the paragraph right beside it. Kept once, in the visible paragraph: per `StatusPill`'s
          own docstring, `title` is a convenience for a short label, not the place for a caveat a
          reader genuinely needs (invisible on touch, and this one already has a permanent, visible
          home). */}
      <div className="panel disclaimer" role="note">
        <StatusPill tone="warn" label={t("ui.pill.filingLag")} />{" "}
        <strong>{t("market.institutions.disclaimer.lead")}</strong>{" "}
        {t("market.institutions.disclaimer.body")}
      </div>

      {/* Institutions <-> Consensus cross-link (`nav.ts` already declares the two adjacent).
          Rendered in every phase -- a reader who came here to see one filer, but really wants the
          cross-fund picture, should not have to leave via the nav bar to find it. Points at the
          merged Filers page's consensus tab directly; the legacy `/consensus` route only redirects
          there and is slated for removal once no caller names it. */}
      <p className="muted">
        <Trans
          k="market.institutions.crossLink"
          values={{
            link: (
              <Link to="/filers?tab=consensus">{t("market.institutions.crossLink.linkText")}</Link>
            ),
          }}
        />
      </p>

      <Fetched
        state={fundsResult}
        loading={
          <div className="panel">
            <div className="placeholder">{t("market.institutions.loadingFunds")}</div>
          </div>
        }
        error={(message) => (
          <div className="panel">
            <div className="placeholder">{message}</div>
          </div>
        )}
        isEmpty={(f) => f.length === 0}
        empty={
          <div className="panel">
            <div className="placeholder">{t("market.institutions.emptyFunds")}</div>
          </div>
        }
      >
        {(loadedFunds) => <InstitutionsContent funds={loadedFunds} />}
      </Fetched>
    </>
  );
}

/** Institutions & major ETFs: what they hold, and -- the point of this page -- what changed since
 *  the last filing, so it can be checked against the user's own portfolio.
 *
 *  Standalone page chrome (`<h1>`/subtitle) plus `InstitutionsView` above. Kept as the route's
 *  default export for now -- the orchestrator removes this once `/institutions` redirects to
 *  `/filers`, per the Filers merge task's scope fence. */
export default function Institutions() {
  const { t } = useT();
  return (
    <>
      <h1>{t("market.institutions.title")}</h1>
      <p className="subtitle">{t("market.institutions.subtitle")}</p>
      <InstitutionsView />
    </>
  );
}

/**
 * Turns a caught fetch failure into display copy. Shared by every fetch on this page (funds,
 * holdings, changes) because all three hit a live SEC-derived pipeline and can fail the same three
 * ways: an unreachable upstream (502/503, very plausible in practice -- SEC endpoints are not
 * always up), a genuine API error, or a network failure reaching this app's own backend at all.
 * `emptyNoun` only affects the 500-class message text; the 404-vs-empty decision itself is made by
 * each call site, matching `WashSales.tsx`'s rule that only a 404 whose message matches an expected
 * string counts as "nothing to show".
 */
function describeFetchError(t: Translator, e: unknown, emptyNoun: string): string {
  if (e instanceof ApiRequestError) {
    if (e.status === 502 || e.status === 503) {
      return t("market.institutions.error.upstreamUnreachable", { status: e.status });
    }
    return t("market.institutions.error.apiError", { status: e.status, message: e.message });
  }
  return t("market.institutions.error.cannotReachApi", { emptyNoun });
}

function InstitutionsContent({ funds }: { funds: FundRef[] }) {
  const { t } = useT();
  const [selectedKey, setSelectedKey] = useState<string>(funds[0]?.key ?? "");
  const selected = funds.find((f) => f.key === selectedKey) ?? funds[0];
  if (!selected) return null;

  return (
    <>
      <div className="panel">
        <label className="year-select">
          {t("market.institutions.fundLabel")}
          <select value={selected.key} onChange={(e) => setSelectedKey(e.target.value)}>
            {funds.map((f) => (
              <option key={f.key} value={f.key}>
                {/* The principal leads for a 13F filer. A list reading "Duquesne Family Office LLC"
                    is one most people cannot use; "Stanley Druckenmiller — Duquesne Family Office
                    LLC" is the same list, findable. The firm name is never dropped, because that
                    is what actually filed. */}
                {f.principal ? `${f.principal} — ${f.name}` : f.name} ({f.ticker ?? f.key}) ·{" "}
                {f.source}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* Keyed on the fund's key so switching funds remounts this whole subtree instead of trying
          to reconcile per-fund state -- the same technique `Ticker.tsx` uses on `symbol`. Without
          the key, a stale holdings table for the previous fund would flash on screen while the next
          fund's data loads in. */}
      <FundView key={selected.key} fund={selected} />
    </>
  );
}

function FundView({ fund }: { fund: FundRef }) {
  const { t } = useT();
  // Deliberately `[fund.key]` only, matching `Portfolio.tsx`'s own fetch effects: this refetches when
  // the selected fund changes, and `formatError` translates in whichever language is active when the
  // request actually fails.
  const snapshotResult = useFetch<Snapshot | null>(
    async () => {
      try {
        return await institutionsApi.holdings(fund.key);
      } catch (e) {
        if (
          e instanceof ApiRequestError &&
          e.status === 404 &&
          /no (holdings|filings) on record/i.test(e.message)
        ) {
          return null;
        }
        throw e;
      }
    },
    [fund.key],
    { formatError: (e) => describeFetchError(t, e, t("market.institutions.noun.holdings")) },
  );
  const snapshot = snapshotResult.data;
  const snapshotPhase: Phase =
    snapshotResult.phase === "loaded"
      ? snapshot === null || snapshot.holdings.length === 0
        ? "empty"
        : "loaded"
      : snapshotResult.phase;
  const snapshotError = snapshotResult.error;

  // Only one filing on record for this fund is a real, expected state -- there is nothing to diff a
  // first filing against. The server says so with **409**, not 404: the fund exists and the request
  // was well-formed, so 404 would have been a lie about the resource. Guarded on that status plus the
  // specific message, matching this page's other guards -- any other 409 falls through to the real
  // error state instead of quietly rendering "nothing changed".
  //
  // `tests/test_frontend_contract.py` asserts the server's real `InsufficientHistory` text still
  // satisfies this pattern. It did not, once: the page originally guarded a 404 with a regex written
  // before the endpoint existed, so the one state this branch is *for* rendered as a red error instead.
  const deltaResult = useFetch<PortfolioDelta | null>(
    async () => {
      try {
        return await institutionsApi.changes(fund.key);
      } catch (e) {
        if (e instanceof ApiRequestError && e.status === 409 && /usable filing period/i.test(e.message)) {
          return null;
        }
        throw e;
      }
    },
    [fund.key],
    { formatError: (e) => describeFetchError(t, e, t("market.institutions.noun.changes")) },
  );
  const delta = deltaResult.data;
  const deltaPhase: Phase =
    deltaResult.phase === "loaded"
      ? delta === null || delta.changes.length === 0
        ? "empty"
        : "loaded"
      : deltaResult.phase;
  const deltaError = deltaResult.error;

  return (
    <>
      {/* The shape of the book comes before the deltas against it -- a reader sees what the fund
          *is* before what changed. */}
      <PortfolioShapeSection
        fund={fund}
        snapshot={snapshot}
        snapshotPhase={snapshotPhase}
        snapshotError={snapshotError}
        delta={delta}
        deltaPhase={deltaPhase}
        deltaError={deltaError}
      />
      <ChangesSection fund={fund} phase={deltaPhase} error={deltaError} delta={delta} />
      <HoldingsSection fund={fund} phase={snapshotPhase} error={snapshotError} snapshot={snapshot} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Portfolio shape -- pie + biggest recent moves, side by side above the full table.
// ---------------------------------------------------------------------------

/**
 * A reader's first look at a filer's book: its shape (the pie) beside what just moved in it (the
 * moves panel), before the exhaustive row-by-row tables below. Placed ahead of `ChangesSection` and
 * `HoldingsSection` rather than a third fetch of its own -- both halves are fed from state `FundView`
 * already holds. It leads the page because the shape of the book is what the deltas below are
 * changes *to*: a reader who sees "+40% CVX" first has nothing to size it against yet. The pie reads `snapshot` (the current filing's holdings, i.e. "what the book looks
 * like now") and the moves panel reads `delta` (the diff against the prior filing, i.e. "what just
 * changed") -- two different questions with two different natural sources, not an arbitrary split.
 *
 * Deliberately not wrapped in its own `.panel`: `HoldingsPieChart` and `RecentMoves` each render as a
 * complete `<section className="panel">` with its own `<h2>` (`Portfolio by weight` / `Recent
 * moves`). Boxing them in a second, outer `.panel` here would nest card-in-card-in-card -- a doubled
 * border and padding around an already-boxed pair, not a real grouping. `.section-heading` (already
 * used the same bare way by `Competition.tsx`, e.g. its "Desk roster"/"Full ranking" headings) gives
 * this row a title without a redundant box.
 *
 * `RecentMoves` is simply handed `delta`/`deltaPhase`/`deltaError` -- it already renders every one of
 * its own loading/error/empty/loaded states internally. `HoldingsPieChart` gets no such pass-through:
 * its props carry no phase at all, only `holdings`, and it treats an empty array as "this filer
 * genuinely holds nothing" (see its own docstring). Handed `snapshot?.holdings ?? []` on a loading or
 * failed fetch, it would render that same "no holdings" copy for "have not measured yet" -- so this
 * component is only ever mounted once `snapshotPhase === "loaded"`; the other three phases get their
 * own placeholder here, worded the same as `HoldingsSection`'s so the two surfaces do not disagree.
 */
function PortfolioShapeSection({
  fund,
  snapshot,
  snapshotPhase,
  snapshotError,
  delta,
  deltaPhase,
  deltaError,
}: {
  fund: FundRef;
  snapshot: Snapshot | null;
  snapshotPhase: Phase;
  snapshotError: string | null;
  delta: PortfolioDelta | null;
  deltaPhase: Phase;
  deltaError: string | null;
}) {
  const { t } = useT();
  const navigate = useNavigate();
  // The chart slices and move rows below are not anchors -- a pie slice is an SVG path, a move row
  // is a list item -- so there is nothing for react-router's `Link` to render onto. `useNavigate` is
  // the correct escape hatch here, the same way `SymbolLookup` above already uses it for its form
  // submission. This is *not* a precedent for the ticker badges in `IssuerCell`: those really are
  // simple text links and get a real `Link` so browser-native middle-click / ctrl-click keep working.
  const onSelectTicker = (ticker: string) => navigate(`/symbol/${encodeURIComponent(ticker)}`);

  return (
    <section className="inst-shape-section">
      <h2 className="section-heading">{t("market.institutions.shape.title")}</h2>
      <p className="subtitle inst-source-note">{sourceNote(t, fund.source)}</p>

      <CardGrid height="md" className="inst-shape-grid">
        {/* `height="auto"`: no `label`/`ScrollRegion` needed, and `HoldingsPieChart`'s loaded state
            already carries its own heading (`desk.holdingsPie.title`) -- a `title` here would just
            print that same text a second time. `panelClassName` keeps the pre-existing hook
            (`Institutions.css`'s `.inst-shape-pie > .panel` rule) working, now scoped to the
            nested `.panel` that `HoldingsPieChart`'s own loaded output still renders inside this
            card's body. */}
        <Card height="auto" panelClassName="inst-shape-pie" data-testid="inst-shape-pie-card">
          {snapshotPhase === "loading" && (
            <div className="placeholder">{t("market.institutions.loadingHoldings")}</div>
          )}
          {snapshotPhase === "error" && <div className="placeholder">{snapshotError}</div>}
          {snapshotPhase === "empty" && (
            // Deliberately not verbatim-identical to `HoldingsSection`'s "No holdings on record for
            // this fund yet." below -- the two placeholders describe the same underlying fact but
            // would otherwise render the exact same string twice on screen, which also makes them
            // ambiguous to any test (or screen reader "find in page") that looks up that text once.
            <div className="placeholder">{t("market.institutions.shape.emptyChart")}</div>
          )}
          {snapshotPhase === "loaded" && snapshot && (
            <HoldingsPieChart
              holdings={snapshot.holdings}
              fundName={fund.name}
              source={fund.source}
              onSelectTicker={onSelectTicker}
            />
          )}
        </Card>

        {/* `height="md"`: `RecentMoves` renders every one of its own phases inside its own
            `<h2>`-titled `.panel`, so `label` here (required at this height) only names the
            `ScrollRegion` for assistive tech -- it is not a second visible heading. */}
        <Card
          height="md"
          label={t("desk.recentMoves.title")}
          panelClassName="inst-shape-moves"
          data-testid="inst-shape-moves-card"
        >
          <RecentMoves
            delta={delta}
            phase={deltaPhase}
            error={deltaError}
            onSelectTicker={onSelectTicker}
          />
        </Card>
      </CardGrid>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Sort helpers -- shared by both of this page's sortable tables (the Changes
// section directly below, and Full holdings further down). Kept local to this
// file rather than lifted to a shared module: two call sites don't earn one.
// ---------------------------------------------------------------------------

type SortState<K extends string> = { key: K; dir: "asc" | "desc" };

/** Advances a column's sort state on click: a fresh key starts at that column's own default
 *  direction (see `CHANGE_DEFAULT_DIR` / `HOLDING_DEFAULT_DIR` below); clicking the already-active
 *  column just flips it. */
function nextSortState<K extends string>(
  prev: SortState<K>,
  key: K,
  defaultDir: Record<K, "asc" | "desc">,
): SortState<K> {
  return prev.key === key
    ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
    : { key, dir: defaultDir[key] };
}

// ---------------------------------------------------------------------------
// Changes section -- the point of this page.
// ---------------------------------------------------------------------------

type ChangeSortKey =
  | "issuer"
  | "action"
  | "shares_delta"
  | "shares_pct_change"
  | "value_delta"
  | "weight_after";

/** The direction a freshly-clicked column starts in, before any toggle -- alphabetic columns start
 *  ascending (A first), magnitude columns start descending (biggest first), matching what a reader
 *  scanning a finance table expects from each kind of column. A second click on the same header
 *  still just flips it, per `toggleSort` below. */
const CHANGE_DEFAULT_DIR: Record<ChangeSortKey, "asc" | "desc"> = {
  issuer: "asc",
  action: "asc",
  shares_delta: "desc",
  shares_pct_change: "desc",
  value_delta: "desc",
  weight_after: "desc",
};

function ChangesSection({
  fund,
  phase,
  error,
  delta,
}: {
  fund: FundRef;
  phase: Phase;
  error: string | null;
  delta: PortfolioDelta | null;
}) {
  const { t } = useT();
  const [ownedOnly, setOwnedOnly] = useState(false);
  const [hideHold, setHideHold] = useState(true);
  const [sort, setSort] = useState<SortState<ChangeSortKey>>({
    key: "value_delta",
    dir: "desc",
  });

  const rows = useMemo(() => {
    if (!delta) return [];
    let filtered = delta.changes;
    if (ownedOnly) filtered = filtered.filter((c) => c.ticker != null);
    if (hideHold) filtered = filtered.filter((c) => c.action !== "hold");
    return filtered.slice().sort((a, b) => {
      const dir = sort.dir === "asc" ? 1 : -1;
      switch (sort.key) {
        case "issuer":
          return a.issuer.localeCompare(b.issuer) * dir;
        case "action":
          return a.action.localeCompare(b.action) * dir;
        case "shares_delta":
          return compareDecimalStrings(a.shares_delta, b.shares_delta) * dir;
        case "shares_pct_change": {
          // `null` means a brand-new position, which has no percentage because there was no prior
          // share count to divide by. Sorting it as though it were 0% would file the quarter's
          // most decisive buys in among the positions that did not move at all, so new positions
          // are held together at the end of the order in both directions -- they are not a
          // magnitude and do not belong on the same scale as one.
          const an = a.shares_pct_change;
          const bn = b.shares_pct_change;
          if (an === null || bn === null) {
            if (an === null && bn === null) return 0;
            return an === null ? 1 : -1;
          }
          return compareDecimalStrings(an, bn) * dir;
        }
        case "value_delta":
          return compareDecimalStrings(a.value_delta, b.value_delta) * dir;
        case "weight_after":
          return compareDecimalStrings(a.weight_after, b.weight_after) * dir;
        default:
          return 0;
      }
    });
  }, [delta, ownedOnly, hideHold, sort]);

  const toggleSort = (key: ChangeSortKey) =>
    setSort((prev) => nextSortState(prev, key, CHANGE_DEFAULT_DIR));

  return (
    <section className="panel">
      <Collapsible title={<h2>{t("market.institutions.changes.title")}</h2>} defaultOpen>
        <p className="subtitle inst-source-note">{sourceNote(t, fund.source)}</p>

        {phase === "loaded" && delta && <ProvenanceLine delta={delta} />}

        {phase === "loading" && (
          <div className="placeholder">{t("market.institutions.loadingChanges")}</div>
        )}
        {phase === "error" && <div className="placeholder">{error}</div>}
        {phase === "empty" && (
          <div className="placeholder">{t("market.institutions.changes.empty")}</div>
        )}

        {phase === "loaded" && delta && (
          <>
            <CountsStrip counts={delta.counts} visible={rows} />
            <TradedTogetherNote delta={delta} />

            <div className="filter-bar inst-changes-filters">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={ownedOnly}
                  onChange={(e) => setOwnedOnly(e.target.checked)}
                />
                {t("market.institutions.filter.ownedOnly")}
              </label>
              <OwnershipCaveat />
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={hideHold}
                  onChange={(e) => setHideHold(e.target.checked)}
                />
                {t("market.institutions.changes.hideHold")}
              </label>
            </div>

            {/* The "Weight in filing" header below also carries this as a hover `title`, for a
                mouse reader -- but a hover-only tooltip is invisible on touch and unreachable by
                keyboard, so the fact itself (what the weight is a share *of*) gets a visible home
                here too. Repeated verbatim in `HoldingsSection` below: this project has been bitten
                more than once by a fix landing on one of these two tables and not its twin. */}
            <InfoNote
              tone="quiet"
              className="inst-weight-caption"
              summary={
                fund.source === "13F"
                  ? t("market.institutions.weightTooltip.13F")
                  : t("market.institutions.weightTooltip.NPORT")
              }
            />

            {rows.length === 0 ? (
              <div className="placeholder">{t("market.institutions.changes.noRowsMatch")}</div>
            ) : (
              <ScrollRegion size="md" label={t("market.institutions.changes.title")}>
                <div className="table-wrap">
                <table className="data-table inst-changes-table">
                  <TableCaption
                    caption={t("market.institutions.table.caption.changes", {
                      fund: fund.name,
                      count: rows.length,
                    })}
                  />
                  <thead>
                    <tr>
                      <SortHeader
                        label={t("market.institutions.header.issuer")}
                        sortKey="issuer"
                        sort={sort}
                        onSort={toggleSort}
                      />
                      {/* Not "CUSIP": a foreign listing often has none, and the parser falls
                          back to an ISIN-, LEI- or name-derived key rather than dropping the
                          row. Ferrovial SE appears in QQQ as `ISIN:NL0015001FS8`, which under a
                          column headed CUSIP is simply a wrong label on a right value. */}
                      <th scope="col">{t("market.institutions.header.identifier")}</th>
                      <SortHeader
                        label={t("market.institutions.header.action")}
                        sortKey="action"
                        sort={sort}
                        onSort={toggleSort}
                      />
                      <th scope="col" className="num">
                        {t("market.institutions.header.sharesBefore")}
                      </th>
                      <th scope="col" className="num">
                        {t("market.institutions.header.sharesAfter")}
                      </th>
                      <SortHeader
                        label={t("market.institutions.header.sharesDelta")}
                        sortKey="shares_delta"
                        sort={sort}
                        onSort={toggleSort}
                        numeric
                      />
                      <SortHeader
                        label={t("market.institutions.header.sharesPctChg")}
                        sortKey="shares_pct_change"
                        sort={sort}
                        onSort={toggleSort}
                        numeric
                      />
                      <SortHeader
                        label={t("market.institutions.header.valueDelta")}
                        sortKey="value_delta"
                        sort={sort}
                        onSort={toggleSort}
                        numeric
                      />
                      {/* The denominator is named because "weight" already means something else
                          one page over: /portfolio's weight is a share of the user's own invested
                          value. Two columns with the same header and different denominators invite
                          a comparison that is not valid. */}
                      <SortHeader
                        label={t("market.institutions.header.weightInFiling")}
                        sortKey="weight_after"
                        sort={sort}
                        onSort={toggleSort}
                        numeric
                        title={
                          fund.source === "13F"
                            ? t("market.institutions.weightTooltip.13F")
                            : t("market.institutions.weightTooltip.NPORT")
                        }
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((c) => (
                      <ChangeRow key={c.cusip} change={c} />
                    ))}
                  </tbody>
                </table>
                </div>
              </ScrollRegion>
            )}
          </>
        )}
      </Collapsible>
    </section>
  );
}

/**
 * Why "only holdings I also own" is a floor, not a census.
 *
 * A holding is matched to the user's book by CUSIP, and the CUSIP has to already be in their
 * ledger for the match to happen. Only the Robinhood adapter supplies one: `ingest/adapters/sofi.py`
 * and `ingest/adapters/webull.py` both set `cusip=None` on every row, because neither export has
 * the column. So a position held only at SoFi or Webull can never be flagged here however much of
 * it the user owns.
 *
 * This is not hypothetical and it is not a corner. Apple is the largest position in Berkshire's
 * disclosed book at roughly 22% of it, the user holds AAPL, and it renders unflagged -- because
 * AAPL is one of the ledger instruments carrying no CUSIP. Without this note the filter quietly
 * asserts something false: that the user owns none of what it hid. Two independent UAT runs filed
 * that on the same day.
 *
 * Rendered as an `InfoNote` rather than an always-on paragraph: the one-clause summary ("matched by
 * CUSIP, an unflagged row may still be yours") is what a reader needs at a glance next to the
 * checkbox it qualifies, and the full reasoning above is one click away rather than permanently on
 * screen twice (this component is mounted once per section, Changes and Full holdings alike).
 */
function OwnershipCaveat() {
  const { t } = useT();
  return (
    <InfoNote
      tone="quiet"
      className="inst-owned-caveat"
      summary={t("market.institutions.ownershipCaveat.summary")}
    >
      <p>
        <Trans
          k="market.institutions.ownershipCaveat.detail"
          values={{ noCusipMatch: <em>{t("market.institutions.noCusipMatch")}</em> }}
        />
      </p>
    </InfoNote>
  );
}

/** Rendered straight from the server's own tally -- never recomputed from `changes` here. A second
 *  client-side implementation of the same count is free to disagree with the first, and a reader
 *  has no way to tell which one is wrong; see `PortfolioDelta.counts`'s docstring. */
function CountsStrip({
  counts,
  visible,
}: {
  counts: Record<Action, number>;
  visible: HoldingChange[];
}) {
  const { t } = useT();
  const order: Action[] = ["new", "exit", "add", "trim", "hold"];
  const shown = useMemo(() => {
    const tally: Record<Action, number> = { new: 0, exit: 0, add: 0, trim: 0, hold: 0 };
    for (const change of visible) tally[change.action] += 1;
    return tally;
  }, [visible]);

  // Qualify the tiles only when rows are genuinely missing from the table, not merely because a
  // checkbox is ticked. QQQ's latest diff contains no `hold` rows at all, so the default
  // "hide unchanged" filter removes nothing -- and an earlier version of this still announced
  // "Filters are active: 104 of 104 positions shown", which is noise that trains a reader to stop
  // reading the qualifier in the cases where it matters.
  const total = totalPositions(counts);
  const hidden = total - visible.length;

  return (
    <>
      <div className="tile-grid inst-counts-strip">
        {order.map((action) => (
          <div key={action} className="stat tile">
            <span className="label">{t(ACTION_LABEL_KEY[action])}</span>
            <span className="value">
              {hidden > 0 ? `${shown[action]} of ${counts[action]}` : counts[action]}
            </span>
          </div>
        ))}
      </div>
      {hidden > 0 && (
        <p className="muted inst-filter-note">
          {t("market.institutions.changes.filterNote", { hidden, total, shown: visible.length })}
        </p>
      )}
    </>
  );
}

/** Total positions in the unfiltered diff, from the server's tally rather than a row count. */
function totalPositions(counts: Record<Action, number>): number {
  return counts.new + counts.exit + counts.add + counts.trim + counts.hold;
}

/**
 * The caveat that stops the counts strip above from being read as a list of decisions.
 *
 * A 13F manager chooses each position, so every `add` and `trim` is a decision. A fund does not:
 * when money leaves it, or when its index reconstitutes, every holding is sold down together and
 * the diff reports one `trim` per position for something that was not a per-position judgement at
 * all. QQQ's most recent filing pair reports **95 trims** at a median of -6.07%, with three
 * quarters of them inside a -5% to -7% band. Nothing was decided ninety-five times.
 *
 * This states the median and what a tight cluster means, and stops there. It does not assert
 * "these are flows", because the same signature has more than one cause and the data cannot tell
 * them apart: SCHD's median is -22.64%, which is its index reconstituting, not investors leaving.
 * Naming a cause we cannot evidence would be the same species of error as the label it corrects.
 *
 * Rendered as an `InfoNote`: the median-change fact is the summary a reader needs to see without
 * asking, and the NPORT/13F-specific "here is how to read that" clause is the elaboration, one
 * click away rather than a second permanently-on paragraph under the counts strip.
 */
function TradedTogetherNote({ delta }: { delta: PortfolioDelta }) {
  const { t } = useT();
  const traded = delta.counts.add + delta.counts.trim;
  // Below a handful of traded positions a median describes nothing, and the "moved together"
  // framing would be actively misleading about a book that made three separate decisions.
  if (delta.median_shares_pct_change === null || traded < 10) return null;

  return (
    <InfoNote
      tone="quiet"
      className="inst-traded-note"
      summary={
        <Trans
          k="market.institutions.tradedNote.summary"
          values={{
            traded,
            median: <strong>{formatSharesPctChange(delta.median_shares_pct_change)}</strong>,
          }}
        />
      }
    >
      {delta.fund.source === "NPORT" ? (
        <p>
          <Trans
            k="market.institutions.tradedNote.nport"
            values={{ weight: <strong>{t("common.weight")}</strong> }}
          />
        </p>
      ) : (
        <p>{t("market.institutions.tradedNote.13F")}</p>
      )}
    </InfoNote>
  );
}

function ProvenanceLine({ delta }: { delta: PortfolioDelta }) {
  return (
    <p className="muted inst-provenance">
      <Trans
        k="market.institutions.provenance"
        values={{
          fromPeriod: <strong>{delta.from_period}</strong>,
          fromAccession: delta.from_accession,
          toPeriod: <strong>{delta.to_period}</strong>,
          toAccession: delta.to_accession,
          before: formatMoneyOrDash(delta.total_value_before),
          after: formatMoneyOrDash(delta.total_value_after),
        }}
      />
    </p>
  );
}

function SortHeader<K extends string>({
  label,
  sortKey,
  sort,
  onSort,
  numeric,
  title,
}: {
  label: string;
  sortKey: K;
  sort: SortState<K>;
  onSort: (key: K) => void;
  numeric?: boolean;
  title?: string;
}) {
  const active = sort.key === sortKey;
  const arrow = active ? (sort.dir === "asc" ? "▲" : "▼") : "";
  return (
    <th scope="col" className={numeric ? "num" : undefined} title={title}>
      <button type="button" className="inst-sort-button" onClick={() => onSort(sortKey)}>
        {label} {arrow}
      </button>
    </th>
  );
}

/**
 * One holding's period-over-period change. The action badge and every word of "what this fund did"
 * framing comes from `action` (server-computed off the share columns) and the share columns
 * themselves -- never from `value_delta`, which is shown right beside it but explicitly labelled as
 * including price movement, per the Chevron case in `@/api/institutions`'s module docstring: a
 * $3.5bn drop in reported value with a share count that never moved is a price move, not a sale.
 */
function ChangeRow({ change }: { change: HoldingChange }) {
  const { t } = useT();
  const owned = change.ticker != null;
  const valueTone = moneyTone(change.value_delta);
  return (
    <tr className={owned ? "inst-owned-row" : undefined}>
      <td>
        <IssuerCell issuer={change.issuer} ticker={change.ticker} />
      </td>
      <td className="muted inst-cusip">{change.cusip}</td>
      <td>
        <span className={`badge ${ACTION_TONE[change.action]}`}>
          {t(ACTION_LABEL_KEY[change.action])}
        </span>
      </td>
      <td className="num">{formatShares(change.shares_before)}</td>
      <td className="num">{formatShares(change.shares_after)}</td>
      <td className={`num ${moneyTone(change.shares_delta)}`}>
        {formatSignedShares(change.shares_delta)}
      </td>
      <td className="num">{formatSharesPctChange(change.shares_pct_change)}</td>
      <td className={`num ${valueTone}`}>{formatSignedMoney(change.value_delta)}</td>
      <td className="num">{formatWeight(change.weight_after)}</td>
    </tr>
  );
}

// `IssuerCell` now lives in `@/pages/filers/shared` (imported above) -- see that module's docstring.

// ---------------------------------------------------------------------------
// Holdings section -- the full current snapshot.
// ---------------------------------------------------------------------------

type HoldingSortKey = "issuer" | "value" | "shares" | "weight";

/** Same rationale as `CHANGE_DEFAULT_DIR` above, for the Full holdings table's own columns. */
const HOLDING_DEFAULT_DIR: Record<HoldingSortKey, "asc" | "desc"> = {
  issuer: "asc",
  value: "desc",
  shares: "desc",
  weight: "desc",
};

function HoldingsSection({
  fund,
  phase,
  error,
  snapshot,
}: {
  fund: FundRef;
  phase: Phase;
  error: string | null;
  snapshot: Snapshot | null;
}) {
  const { t } = useT();
  const [ownedOnly, setOwnedOnly] = useState(false);
  // Live issuer-name substring filter, added alongside the pre-existing `ownedOnly` checkbox rather
  // than replacing it -- `FilterBar` (shared with Consensus's own table below, and with
  // `Activity.tsx`'s and `Tax.tsx`'s) owns the text box, the "showing N of M" count and the Clear
  // button; this component only supplies the predicate, same division of labour as
  // `DisposalsTable` in `Tax.tsx`.
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortState<HoldingSortKey>>({
    key: "value",
    dir: "desc",
  });

  const rows = useMemo(() => {
    if (!snapshot) return [];
    const q = query.trim().toLowerCase();
    const filtered = snapshot.holdings.filter((h) => {
      if (ownedOnly && h.ticker == null) return false;
      if (q && !h.issuer.toLowerCase().includes(q)) return false;
      return true;
    });
    return filtered.slice().sort((a, b) => {
      const dir = sort.dir === "asc" ? 1 : -1;
      switch (sort.key) {
        case "issuer":
          return a.issuer.localeCompare(b.issuer) * dir;
        case "value":
          return compareDecimalStrings(a.value, b.value) * dir;
        case "shares":
          return compareDecimalStrings(a.shares, b.shares) * dir;
        case "weight":
          return compareDecimalStrings(a.weight, b.weight) * dir;
        default:
          return 0;
      }
    });
  }, [snapshot, ownedOnly, query, sort]);

  const toggleSort = (key: HoldingSortKey) =>
    setSort((prev) => nextSortState(prev, key, HOLDING_DEFAULT_DIR));

  return (
    <section className="panel">
      {/* Matches `ChangesSection`'s `Collapsible` wrap above -- a long snapshot table earns the same
          collapse-to-glance treatment as the changes table right above it, rather than always
          rendering in full while its sibling section can be closed. */}
      <Collapsible title={<h2>{t("market.institutions.holdings.title")}</h2>} defaultOpen>
        <p className="subtitle inst-source-note">{sourceNote(t, fund.source)}</p>

        {phase === "loaded" && snapshot && (
          <p className="muted inst-provenance">
            <Trans
              k={
                snapshot.holdings.length === 1
                  ? "market.institutions.holdings.provenance_one"
                  : "market.institutions.holdings.provenance_other"
              }
              values={{
                period: <strong>{snapshot.period}</strong>,
                filed: <strong>{snapshot.filed}</strong>,
                accession: snapshot.accession,
                value: formatMoneyOrDash(snapshot.total_value),
                count: snapshot.holdings.length,
              }}
            />
            {snapshot.value_units_rescaled && (
              <>
                {" "}
                <strong>{t("market.institutions.holdings.rescaledLead")}</strong>{" "}
                {t("market.institutions.holdings.rescaledBody")}
              </>
            )}
          </p>
        )}

        {phase === "loading" && (
          <div className="placeholder">{t("market.institutions.loadingHoldings")}</div>
        )}
        {phase === "error" && <div className="placeholder">{error}</div>}
        {phase === "empty" && (
          <div className="placeholder">{t("market.institutions.holdings.empty")}</div>
        )}

        {phase === "loaded" && snapshot && (
          <>
            {/* `FilterBar`'s own text query and this checkbox both narrow the same `rows` above --
                the text box for "find this issuer" (1.10, shared with Consensus's table below), the
                checkbox for the pre-existing "only what I also own" question `OwnershipCaveat`
                qualifies. `total`/`shown` describe the whole snapshot vs. after BOTH filters, so the
                count is honest even when only one of the two is narrowing anything. */}
            <FilterBar
              query={query}
              onQueryChange={setQuery}
              queryPlaceholder={t("tax.disposals.filterPlaceholder")}
              shown={rows.length}
              total={snapshot.holdings.length}
            />
            <div className="filter-bar">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={ownedOnly}
                  onChange={(e) => setOwnedOnly(e.target.checked)}
                />
                {t("market.institutions.filter.ownedOnly")}
              </label>
              <OwnershipCaveat />
            </div>

            {rows.length < snapshot.holdings.length && (
              <p className="muted inst-filter-note">
                {t("market.institutions.holdings.filterNote", {
                  hidden: snapshot.holdings.length - rows.length,
                  total: snapshot.holdings.length,
                  shown: rows.length,
                })}
              </p>
            )}

            {/* Twin of the same caption in `ChangesSection` above -- see the comment there for why
                this is not left as a hover-only `title`. */}
            <InfoNote
              tone="quiet"
              className="inst-weight-caption"
              summary={
                fund.source === "13F"
                  ? t("market.institutions.weightTooltip.13F")
                  : t("market.institutions.weightTooltip.NPORT")
              }
            />

            {rows.length === 0 ? (
              <div className="placeholder">{t("market.institutions.holdings.noMatch")}</div>
            ) : (
              <ScrollRegion size="md" label={t("market.institutions.holdings.title")}>
                <div className="table-wrap">
                <table className="data-table">
                  <TableCaption
                    caption={t("market.institutions.table.caption.holdings", {
                      fund: fund.name,
                      count: rows.length,
                    })}
                  />
                  <thead>
                    <tr>
                      <SortHeader<HoldingSortKey>
                        label={t("market.institutions.header.issuer")}
                        sortKey="issuer"
                        sort={sort}
                        onSort={toggleSort}
                      />
                      {/* Not "CUSIP": a foreign listing often has none, and the parser falls
                          back to an ISIN-, LEI- or name-derived key rather than dropping the
                          row. Ferrovial SE appears in QQQ as `ISIN:NL0015001FS8`, which under a
                          column headed CUSIP is simply a wrong label on a right value. */}
                      <th scope="col">{t("market.institutions.header.identifier")}</th>
                      <SortHeader<HoldingSortKey>
                        label={t("common.shares")}
                        sortKey="shares"
                        sort={sort}
                        onSort={toggleSort}
                        numeric
                      />
                      <SortHeader<HoldingSortKey>
                        label={t("common.value")}
                        sortKey="value"
                        sort={sort}
                        onSort={toggleSort}
                        numeric
                      />
                      {/* The twin of the Changes table's weight header, and it has to say the same
                          thing. UAT run 12 found the first version of this fix had reached only the
                          other table: a reader who opened Full holdings first met the original
                          ambiguity untouched. This project has been bitten by a fix landing on one
                          surface and not its sibling several times now -- see the drawdown card, the
                          rule placeholder, and the rule validator. */}
                      <SortHeader<HoldingSortKey>
                        label={t("market.institutions.header.weightInFiling")}
                        sortKey="weight"
                        sort={sort}
                        onSort={toggleSort}
                        numeric
                        title={
                          fund.source === "13F"
                            ? t("market.institutions.weightTooltip.13F")
                            : t("market.institutions.weightTooltip.NPORT")
                        }
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((h) => (
                      <HoldingRow key={h.cusip} holding={h} />
                    ))}
                  </tbody>
                </table>
                </div>
              </ScrollRegion>
            )}
          </>
        )}
      </Collapsible>
    </section>
  );
}

function HoldingRow({ holding }: { holding: Holding }) {
  const owned = holding.ticker != null;
  return (
    <tr className={owned ? "inst-owned-row" : undefined}>
      <td>
        <IssuerCell issuer={holding.issuer} ticker={holding.ticker} />
      </td>
      <td className="muted inst-cusip">{holding.cusip}</td>
      <td className="num">{formatShares(holding.shares)}</td>
      <td className="num">{formatMoneyOrDash(holding.value)}</td>
      <td className="num">{formatWeight(holding.weight)}</td>
    </tr>
  );
}
