import type { DecimalString } from "@/api/client";
import {
  formatMoney,
  formatSignedFractionPctString,
  fractionStringTone,
  type Book,
  type Desk,
  type FetchSummary,
  type Funding,
  type PaperDeskBenchmark,
  type PaperDeskState,
} from "@/api/paperdesk";
import { CardGrid } from "@/components/Card";
import { ScrollRegion } from "@/components/ScrollPanel";
import { TranslatedStatusPill } from "@/components/StatusPill";
import { Trans, t, useT } from "@/i18n";

import DeskPanel from "./DeskPanel";

const STALE_DAYS_WARN_THRESHOLD = 5;

// ---------------------------------------------------------------------------
// Visibility chooser -- which desks are shown, independent of which exist.
// ---------------------------------------------------------------------------

/**
 * One checkbox per desk the API actually returned, labelled with `display_name` rather than
 * `agent_id` -- the panel titles below (`DeskPanel`'s `<h2>`) already render `display_name`, and a
 * ladder card's `agent_id` (`ladder-qld-schd`) reads nothing like the title a reader is scanning
 * for (`Drawdown Ladder - QLD/SCHD/IEF`); matching the chooser label to the panel title lets a
 * reader correlate the two directly instead of translating between two different names for the
 * same card.
 *
 * Real `<input type="checkbox">`/`<label>` pairs, not clickable `<div>`s, so this works with a
 * keyboard and a screen reader for free. Not `role="tablist"`/`role="tab"`: these checkboxes are
 * independent show/hide filters (any combination, including all or none), not a set of mutually
 * exclusive views where exactly one panel is "the" selected one.
 */
function DeskVisibilityChooser({
  desks,
  visible,
  onToggle,
}: {
  desks: Desk[];
  visible: Set<string>;
  onToggle: (agentId: string) => void;
}) {
  const { t: tt } = useT();
  return (
    <div className="panel desk-visibility-panel">
      <h2 className="desk-visibility-title">{tt("desk.book.desksShownTitle")}</h2>
      <ScrollRegion size="md" label={tt("desk.book.desksShownTitle")}>
        <div className="desk-visibility-list">
          {desks.map((d) => (
            <label key={d.agent_id} className="desk-visibility-item">
              <input
                type="checkbox"
                checked={visible.has(d.agent_id)}
                onChange={() => onToggle(d.agent_id)}
              />
              {d.display_name}
            </label>
          ))}
        </div>
      </ScrollRegion>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

export function DeskHeader({
  data,
  refreshing,
  onRefresh,
  refreshError,
}: {
  data: PaperDeskState;
  refreshing: boolean;
  onRefresh: () => void;
  refreshError: string | null;
}) {
  const stale = data.stale_days > STALE_DAYS_WARN_THRESHOLD;
  const { t: tt } = useT();

  return (
    <div className="panel desk-header-panel">
      <div className="desk-header-top">
        <div className="status-grid desk-header-grid">
          <Stat label={tt("desk.header.inceptionLabel")} value={data.inception} />
          <Stat label={tt("desk.header.asOfLabel")} value={data.as_of} />
          <Stat label={tt("desk.header.sessionsLabel")} value={String(data.sessions)} />
          <Stat label={tt("desk.header.firstSessionLabel")} value={data.first_session} />
        </div>
        {/* Labelled for what it now does. This button used to say "Refresh" while only dropping a
            cache and recomputing off bars the store already had -- which left a reader who pressed
            it staring at the same `as_of` and the same `stale_days` with no way to tell whether
            anything had been asked of the provider at all. It now fetches every symbol the desk
            prices before recomputing (`paperdeskApi.refresh`), so it says so, and `FetchReport`
            below states the result rather than leaving it to be inferred from a date that may
            legitimately not have moved. */}
        <button type="button" className="download-link desk-refresh-btn" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? tt("desk.header.fetching") : tt("desk.header.fetchLatest")}
        </button>
      </div>

      {refreshing && (
        <p className="muted desk-fetch-progress" role="status" aria-live="polite">
          {tt("desk.header.fetchingProgress")}
        </p>
      )}

      {/* `as_of` is the store's most recent session, never "now" -- said plainly, every render, not
          left for the reader to infer from a date that might otherwise pass for "today".

          `stale_days` is `today - latest_bar`, not `latest_bar - as_of`. This line used to render it
          as "N days ahead of the mark above", which describes a gap that does not exist: `as_of` and
          `latest_bar` are equal by construction (see `PaperDeskState.as_of`'s own docstring, which
          says so and warns against conflating the two), so the sentence printed two identical dates
          and then claimed one was a day ahead of the other. */}
      <p className="muted desk-mark-note">
        <Trans k="desk.header.markNoteLead" values={{ asOf: <strong>{data.as_of}</strong> }} />
        {data.latest_bar}
        {data.stale_days > 0
          ? tt(data.stale_days === 1 ? "desk.header.staleSuffix_one" : "desk.header.staleSuffix_other", {
              days: data.stale_days,
            })
          : ""}
        .
      </p>

      {/* At-a-glance amber chip alongside the sentence above -- reading "stale" still requires
          parsing a full clause; this is the same fact as a three-word pill. Fires at any
          `stale_days > 0`, independent of `STALE_DAYS_WARN_THRESHOLD`, which gates the louder
          callout below -- a one-day lag is still worth a glance-able marker even when it is not
          yet worth an alert-role callout. Additive: the callout it sits beside is unchanged. */}
      {data.stale_days > 0 && (
        <TranslatedStatusPill
          tone="warn"
          labelKey="ui.pill.staleDays"
          detailKey="desk.header.staleCalloutBody"
          params={{ days: data.stale_days, asOf: data.as_of }}
          className="desk-stale-pill"
        />
      )}

      {stale && (
        <div className="callout callout-warn desk-stale-callout" role="alert">
          <strong>{tt("desk.header.staleCalloutStrong", { days: data.stale_days })}</strong>{" "}
          {tt("desk.header.staleCalloutBody", { asOf: data.as_of })}
        </div>
      )}

      {refreshError && (
        <div className="callout callout-danger desk-refresh-error" role="alert">
          {refreshError}
        </div>
      )}

      {data.fetch && <FetchReport summary={data.fetch} asOf={data.as_of} />}

      {data.notes.length > 0 && (
        <div className="disclaimer panel desk-notes">
          <ul className="desk-notes-list">
            {data.notes.map((note, i) => (
              <li key={i}>{note}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/**
 * What the last press of the fetch button actually pulled. Rendered only when `data.fetch` is
 * present, which is only ever after a fetch this page performed -- a plain page load leaves it
 * `null` and this renders nothing, rather than showing some earlier session's counters.
 *
 * **The point of this block is that "nothing changed" is a legitimate, common outcome and must not
 * read as a failure.** Forty symbols answering without gaining a session is what a weekend, a
 * holiday, or a second press two minutes after the first all look like. So `advanced` and
 * `unchanged` are stated as separate counts, and the mark is reported by comparing
 * `latest_bar_before` with `latest_bar_after`: a fetch can legitimately merge hundreds of rows
 * without moving the desk's own `as_of` forward, and a reader who sees an unchanged date with no
 * explanation reasonably concludes the button is broken.
 *
 * `rows_merged` is labelled "bars merged", never "new bars". The backend re-requests a short
 * overlap behind each symbol's newest stored bar on every call, so this number is large on a press
 * that stored no new session at all -- an earlier version of this line read "56 new daily bars
 * stored" underneath "the newest stored session is still 2026-08-25", which is a contradiction the
 * reader has to resolve and should never have been asked to.
 *
 * Failures are listed, not summarised away. One rate-limited ticker among forty is not an error
 * state for the page -- the recompute ran, and every other symbol is current -- so this is a
 * `callout-warn` inside an otherwise successful report rather than the `callout-danger` treatment
 * reserved above for a fetch that could not reach the API at all.
 */
// `summary`, not `fetch`: a prop named `fetch` shadows the global `fetch` inside this function,
// which is a needless trap in a file that may one day want to call it.
function FetchReport({ summary, asOf }: { summary: FetchSummary; asOf: string }) {
  const markMoved =
    summary.latest_bar_after !== null && summary.latest_bar_after !== summary.latest_bar_before;
  const { t: tt } = useT();

  const failedClause = summary.failed > 0 ? tt("desk.header.failedClause", { failed: summary.failed }) : "";
  const barsWord = tt(summary.rows_merged === 1 ? "desk.header.barWord_one" : "desk.header.barWord_other");

  return (
    <div className="desk-fetch-report" role="status">
      <p className="muted desk-fetch-summary">
        {tt("desk.header.fetchSummary", {
          requested: summary.requested,
          duration: summary.duration_seconds,
          advanced: summary.advanced,
          unchanged: summary.unchanged,
          failedClause,
          rowsMerged: summary.rows_merged,
          barsWord,
        })}
      </p>
      <p className="muted desk-fetch-mark">
        {markMoved
          ? tt("desk.header.fetchMarkMoved", {
              before: summary.latest_bar_before ?? tt("desk.header.noStoredBars"),
              // `markMoved` already established `latest_bar_after !== null` above; the fallback
              // here is unreachable in practice and exists only to keep this a plain string for
              // `MessageParams`, not to state a real possibility.
              after: summary.latest_bar_after ?? tt("desk.header.unavailable"),
              asOf,
            })
          : tt("desk.header.fetchMarkUnchanged", {
              after: summary.latest_bar_after ?? tt("desk.header.unavailable"),
            })}
      </p>
      {summary.failures.length > 0 && (
        <div className="callout callout-warn desk-fetch-failures">
          <strong>{tt("desk.header.failuresHeading", { failed: summary.failed, requested: summary.requested })}</strong>{" "}
          {tt("desk.header.failuresBody")}
          <ul className="desk-fetch-failure-list">
            {summary.failures.map((failure) => (
              <li key={failure}>{failure}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Human wording for a book's funding, from the server's own `Funding`.
 *
 *  `horizon_years_max === null` renders as "no fixed horizon" rather than a blank or a made-up
 *  bound: for the trading purpose the horizon is deliberately unstated, and a purpose whose horizon
 *  is unstated is not the same as one whose horizon is short. */
function fundingSummary(funding: Funding, startingCash: DecimalString): string {
  const horizon =
    funding.horizon_years_max === null
      ? t("desk.book.horizonNone")
      : t("desk.book.horizonRange", { min: funding.horizon_years_min ?? 0, max: funding.horizon_years_max });
  const cadence =
    funding.shape === "lump_sum"
      ? t("desk.book.cadenceLumpSum")
      : funding.shape === "monthly_contribution"
        ? t("desk.book.cadenceMonthly", { amount: formatMoney(funding.contribution) })
        // `then` on this branch too. Without it the Roth book rendered
        // "$30,000.00 $7,500.00 once a year" -- two money figures butted together with nothing
        // joining them, which reads as one malformed number rather than as a contribution schedule.
        // Caught in a browser pass; the monthly branch above always had the word.
        : t("desk.book.cadenceAnnual", { amount: formatMoney(funding.contribution) });
  // Tax treatment is an open backend string (see `Funding.tax_treatment`'s own docstring), not a
  // closed enum this file knows the whole set of -- shown verbatim, cosmetically de-snaked, never
  // translated, same rule as `market_state`/`transport` elsewhere in this codebase.
  return t("desk.book.fundingSummary", {
    starting: formatMoney(startingCash),
    cadence,
    horizon,
    taxTreatment: funding.tax_treatment.replace("_", " "),
  });
}

/** Every benchmark the server sent, falling back to the legacy singular field.
 *
 *  A server predating `benchmarks` sends only `benchmark`; rendering nothing in that case would
 *  silently drop the comparison the page exists to make. */
function benchmarksOf(book: Book): PaperDeskBenchmark[] {
  return book.benchmarks?.length ? book.benchmarks : [book.benchmark];
}

/** One purpose's book: its funding, its own benchmark, its notes, and its desks.
 *
 *  Rendered even when it seats no cards. A purpose can be defined and funded before a card exists
 *  for it, and hiding the book in that case would read as the purpose not existing at all. */
export function BookSection({
  book,
  asOf,
  visible,
  onToggle,
}: {
  book: Book;
  asOf: string;
  visible: Set<string>;
  onToggle: (agentId: string) => void;
}) {
  const visibleDesks = book.desks.filter((d) => visible.has(d.agent_id));
  const { t: tt } = useT();

  return (
    <section className="desk-book" aria-label={tt("desk.book.sectionAriaLabel", { label: book.label })}>
      <div className="panel desk-book-head">
        <div className="desk-book-title">
          <h2>{book.label}</h2>
          <span className="badge desk-book-purpose">{book.purpose}</span>
        </div>
        <p className="muted desk-book-funding">{fundingSummary(book.funding, book.starting_cash)}</p>
        <div className="status-grid desk-book-grid">
          <Stat label={tt("desk.book.openingCapitalLabel")} value={formatMoney(book.starting_cash)} />
          {benchmarksOf(book).map((b) => (
            <Stat
              key={b.symbol}
              label={b.label ? `${b.symbol} (${b.label})` : tt("desk.book.benchmarkLabel", { symbol: b.symbol })}
              value={formatSignedFractionPctString(b.return_pct)}
              tone={fractionStringTone(b.return_pct)}
            />
          ))}
        </div>
        {/* A book's own notes, not the desk's -- the contribution disclosure in particular is true
            of exactly two of the three books and would be misleading printed under the third. */}
        {book.notes && book.notes.length > 0 && (
          <ul className="desk-book-notes">
            {book.notes.map((note, i) => (
              <li key={i}>{note}</li>
            ))}
          </ul>
        )}
      </div>

      {book.desks.length === 0 ? (
        <div className="panel">
          <div className="placeholder">{tt("desk.book.noCards")}</div>
        </div>
      ) : (
        <>
          <DeskVisibilityChooser desks={book.desks} visible={visible} onToggle={onToggle} />
          {visibleDesks.length === 0 ? (
            <div className="panel">
              <div className="placeholder">{tt("desk.book.noDesksSelected")}</div>
            </div>
          ) : (
            /* `CardGrid`, not a bare `.desk-grid`: the height belongs to the grid's tracks, which
               is the only thing that actually makes a row of desks share a bottom edge (CSS grid
               equalises tracks, not siblings -- see `Card.css`). `desk-grid` rides along so this
               page keeps its own explicit 3-up/2-up/1-up column counts rather than the primitive's
               `auto-fit`, which would squeeze a fourth column of squashed tables onto a wide
               monitor. */
            <CardGrid height="lg" min="320px" className="desk-grid">
              {visibleDesks.map((desk) => (
                <DeskPanel key={desk.agent_id} desk={desk} asOf={asOf} />
              ))}
            </CardGrid>
          )}
        </>
      )}
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "" | "pos" | "neg" }) {
  return (
    <div className="stat tile">
      <span className="label">{label}</span>
      <span className={`value${tone ? ` ${tone}` : ""}`}>{value}</span>
    </div>
  );
}
