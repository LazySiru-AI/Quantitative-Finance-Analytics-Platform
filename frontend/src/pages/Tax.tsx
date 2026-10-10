import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiRequestError, type DecimalString } from "@/api/client";
import { subtractMoney } from "@/api/portfolio";
import {
  addMoney,
  formatMoney,
  moneyPercentOf,
  taxApi,
  warningKindLabel,
  type Form8949Box,
  type Form8949Row,
  type GainsReport,
  type TaxReport,
  type TaxWarning,
  type UnsettledPair,
  type WarningGroup,
  type WashSaleEvent,
  type WashSaleSummary,
  type WashSaleSymbolSummary,
} from "@/api/tax";
import { transactionsApi } from "@/api/transactions";
import { FolderTabs } from "@/components/FolderTabs";
import InfoNote from "@/components/InfoNote";
import PanelBoundary from "@/components/PanelBoundary";
import ReconcilePanel from "@/components/ReconcilePanel";
import { ScrollPanel, ScrollRegion } from "@/components/ScrollPanel";
import { StatTile } from "@/components/StatGrid";
import StatusPill from "@/components/StatusPill";
import { FilterBar, SortHeader, sortRows, useTableSort } from "@/components/tableSort";
import { useTabParam } from "@/hooks/useTabParam";
import { Trans, useT, type MessageKey } from "@/i18n";
import { WashSalesSection } from "@/pages/WashSales";

import "./Tax.css";

/**
 * Share of a tax year's disposals with an unverifiable basis above which the caveat is promoted
 * above the headline figures rather than left to the muted note beneath the tiles. Below this, a
 * handful of gaps in an otherwise-clean year is exactly what the existing tile-level note already
 * conveys proportionately. At or above it, the number of disposals with a real basis is small
 * enough that leading with the total gain first and the caveat second is misleading regardless of
 * how the caveat is phrased -- the reader needs the doubt before the number, not after it. 20% is
 * chosen deliberately below the pathological case this was written against (99%, phase-3.md) so
 * the promotion also fires well short of that extreme.
 */
const UNCERTAIN_BASIS_PROMOTION_THRESHOLD = 0.2;

/**
 * The same promotion, measured in money instead of rows -- and the one that actually fires on real
 * data.
 *
 * Counting rows was the whole test until this was added, and it has a blind spot big enough to drive
 * the year through: an unestablished basis attaches to shares that *arrived* rather than being
 * bought, which means transfers and pre-window holdings, which means the large positions. On a
 * real ledger that can be a small fraction of disposals, comfortably under the row threshold,
 * carrying most of the reported gain. The page led with the headline
 * and mentioned the doubt eleven screens down, on a figure that is four fifths guesswork.
 *
 * Set below the row threshold on purpose. A quarter of the year's gain resting on basis nobody has
 * established is already the dominant fact about that year, well before it becomes a majority.
 */
const UNCERTAIN_GAIN_PROMOTION_THRESHOLD = 0.25;

/**
 * The four sections the Tax page scans in, as a `FolderTabs` rail rather than one long scroll.
 *
 * `summary` carries the two legally-relevant callouts (uncertain-basis, permanently-disallowed)
 * plus the headline tiles and warnings -- everything a filer needs before touching a table. The
 * other three each own exactly one of the page's heavy tables, so only the active tab's rows are
 * ever mounted (see the `tab === "..."` guards in `Tax()` below) instead of thousands of rows this
 * page used to render unconditionally.
 */
type TaxTab = "summary" | "disposals" | "wash" | "f8949";
const TAX_TABS: readonly TaxTab[] = ["summary", "disposals", "wash", "f8949"];

/**
 * Rows per page for the Disposals and Wash sales tables -- see `taxApi.report`'s `limit`/`offset`
 * and `app.api.tax._paginate_report` on the backend. Matches `Activity.tsx`'s own `PAGE_SIZE`: both
 * pages page the same kind of thing (a ledger-scale table) and there is no reason for one to feel
 * denser than the other.
 */
const PAGE_SIZE = 100;

/** What an empty tax report actually means, once the ledger has been consulted. */
interface EmptyContext {
  /** Rows in the whole ledger, any year. */
  ledgerRows: number;
  /** Rows whose trade date falls in the selected tax year. */
  rowsThisYear: number;
}

/**
 * Why this year's report is empty, for the empty-state message only.
 *
 * Two counts, not one. The first version of this asked only for the ledger's total and then wrote
 * *"It holds 7 transactions, none of them in this tax year"* — a sentence that asserts something it
 * never checked. A UAT persona hit it on an account whose transactions were **all** in that year
 * and said so: the Activity page and `/api/portfolio/transactions` both contradicted the Tax page
 * outright. A report with no *disposals* is not a year with no *activity*, and the difference is
 * the whole message.
 *
 * Failure is deliberately silent: this exists to make one sentence more specific, and reporting
 * "could not determine ledger size" over an empty tax year substitutes a problem the user does not
 * have for the one they do. `null` falls back to the import instruction.
 */
async function loadEmptyContext(
  year: number,
  set: (context: EmptyContext) => void,
  cancelled: () => boolean,
): Promise<void> {
  try {
    const [stores, page] = await Promise.all([
      api.stores(),
      // `limit: 1` because only `total` is wanted -- it counts the whole filtered set, not the page.
      transactionsApi.list({ start: `${year}-01-01`, end: `${year}-12-31`, limit: 1 }),
    ]);
    // `transactions` is optional on the wire -- absent when the ledger file does not exist yet,
    // which is the same thing as zero rows for this message's purposes.
    if (!cancelled()) {
      set({ ledgerRows: stores.ledger.transactions ?? 0, rowsThisYear: page.total });
    }
  } catch {
    // Leave it null.
  }
}

/**
 * Which of the three absences this is.
 *
 * The order matters: "nothing imported" is checked first because it is the only one whose answer is
 * "go and import", and the other two must never be phrased that way at a user who already has. The
 * third case — activity in the year but nothing disposed of — is the common one for anyone who
 * bought and held, and saying "no activity" to them is simply false.
 */
function EmptyYearMessage({ year, context }: { year: number; context: EmptyContext | null }) {
  const { t } = useT();

  if (context === null || context.ledgerRows === 0) {
    return (
      <Trans
        k="tax.empty.notImported"
        values={{ dataDir: <code>data/</code>, activityLink: <Link to="/activity">Activity</Link> }}
      />
    );
  }

  if (context.rowsThisYear === 0) {
    return <>{t("tax.empty.noYearActivity", { year, count: context.ledgerRows.toLocaleString() })}</>;
  }

  return (
    <Trans
      k={context.rowsThisYear === 1 ? "tax.empty.nothingDisposed_one" : "tax.empty.nothingDisposed_other"}
      values={{
        year,
        count: context.rowsThisYear.toLocaleString(),
        activityLink: <Link to="/activity">Activity</Link>,
      }}
    />
  );
}

/**
 * The year the page opens on, before the user touches the selector.
 *
 * `currentYear - 1` used to be the unconditional default -- correct only in January, when the
 * current year genuinely has no activity yet and last year's return is what is being filed. Wrong
 * the rest of the year: three concurrent UAT persona runs opened this page against a ledger dated
 * entirely in the current year, landed on last year under the old default, and read "No <year>
 * activity at all -- pick another year above" as a failed import. The 2026 logic underneath was
 * fine the whole time; only the default selection pointed at the wrong year.
 *
 * Anchors on the single most recent transaction across the *whole* ledger rather than probing eight
 * years of report fetches -- one lightweight, unfiltered, newest-first, limit-1 call answers "does
 * this ledger have any activity, and if so, in which year" in one round trip, reusing the same
 * `transactionsApi` this page already calls from `loadEmptyContext`. Falls back to
 * `currentYear - 1` when the ledger has no transactions at all (there is nothing to anchor to) or
 * when the lookup itself fails -- a hiccup here must not block the page; the report fetch below will
 * report its own error if the API is genuinely down.
 */
async function resolveDefaultYear(currentYear: number): Promise<number> {
  try {
    const page = await transactionsApi.list({ newest_first: true, limit: 1 });
    const latestDate = page.transactions[0]?.trade_date;
    if (latestDate) {
      const y = Number(latestDate.slice(0, 4));
      if (Number.isFinite(y)) return y;
    }
  } catch {
    // Network hiccup or an old backend without this filter -- fall through to the January-filing
    // default below rather than leaving the page stuck with no year selected at all.
  }
  return currentYear - 1;
}

/** US tax: wash sales, capital gains, Form 8949. */
export default function Tax() {
  const { t } = useT();
  const currentYear = new Date().getFullYear();
  // `null` until `resolveDefaultYear` (below) answers. Nothing here treats `null` as a real year --
  // the page shows a plain loading panel instead of the year selector while it is `null`, so the
  // reader never sees one year rendered and then silently swapped for another after first paint.
  const [year, setYear] = useState<number | null>(null);
  const [report, setReport] = useState<TaxReport | null>(null);
  const [phase, setPhase] = useState<"loading" | "loaded" | "empty" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  // Only consulted when the year comes back empty, and only to tell three different absences
  // apart: nothing imported at all, nothing in this year, or activity in this year with nothing
  // disposed of. Each needs a different sentence, and two of them are not "go and import".
  const [emptyContext, setEmptyContext] = useState<EmptyContext | null>(null);
  // Which of the four sections is showing. Lives in the URL (not a plain `useState`) so a reload on
  // `/tax?tab=wash` opens directly on Wash sales and Back restores the previous tab -- see
  // `useTabParam`'s own module docstring for why that is the point. A hostile or stale `?tab=` falls
  // back to `summary` via `allowed` rather than ever reaching a component that switches on it.
  // This was already a `useUrlState` call rather than a `useState`; it now goes through the shared
  // tab hook so all six tabbed pages have one implementation instead of six near-copies.
  const [tab, setTab] = useTabParam<TaxTab>("tab", TAX_TABS, "summary");

  // Which page of `gains.rows` / `wash_sales` is showing, one offset per table since the two are
  // paged independently even though a single fetch below carries both (see `taxApi.report`'s single
  // `offset` param -- the Tax page never needs two different pages of two different lists in the
  // same request, only one of these tabs is ever active). Reset alongside `year` in the selector's
  // own `onChange`, not in an effect keyed on `year`, so the reset lands in the same render as the
  // year change instead of racing it -- see that handler below.
  const [disposalsOffset, setDisposalsOffset] = useState(0);
  const [washOffset, setWashOffset] = useState(0);

  // Resolves the default year exactly once per mount, before the report effect below ever runs.
  useEffect(() => {
    let cancelled = false;
    void resolveDefaultYear(currentYear).then((resolved) => {
      if (!cancelled) setYear(resolved);
    });
    return () => {
      cancelled = true;
    };
    // `currentYear` cannot change within a mounted session; this runs once, on mount, by design.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (year === null) return; // still resolving the default -- see the effect above
    let cancelled = false;
    setPhase("loading");
    setError(null);
    // Only the active tab's own list is ever paged over the wire -- `gains.rows` for Disposals,
    // `wash_sales` for Wash sales. Summary and Form 8949 use neither list (Summary reads only the
    // aggregates and warnings; Form 8949 has its own, never-paginated `form8949.rows`), so both ask
    // for the smallest page merely to keep those two lists off the wire on those tabs too -- the
    // whole point of this fetch no longer carrying the whole report by default.
    const page =
      tab === "disposals"
        ? { limit: PAGE_SIZE, offset: disposalsOffset }
        : tab === "wash"
          ? { limit: PAGE_SIZE, offset: washOffset }
          : { limit: PAGE_SIZE, offset: 0 };
    taxApi
      .report(year, page)
      .then((r) => {
        if (cancelled) return;
        setReport(r);
        const empty = isEmptyReport(r);
        setPhase(empty ? "empty" : "loaded");
        if (empty) void loadEmptyContext(year, setEmptyContext, () => cancelled);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiRequestError && e.status === 404) {
          setReport(null);
          setPhase("empty");
          void loadEmptyContext(year, setEmptyContext, () => cancelled);
          return;
        }
        setError(
          e instanceof ApiRequestError
            ? t("tax.error.apiError", { status: e.status, message: e.message })
            : t("tax.error.cannotReachApi"),
        );
        setPhase("error");
      });
    return () => {
      cancelled = true;
    };
    // `t` translates in whichever language is active when the catch branch runs; a later toggle
    // does not retranslate an already-set error message -- same limitation Portfolio.tsx's
    // `statusError` accepts for the same reason (see its own effect docstring).
    //
    // Re-runs on `tab` too, not only `year`/the two offsets: switching to Disposals or Wash sales
    // for the first time needs its own fetch, because the previous tab's fetch asked for that list's
    // smallest page, not this one's requested page. That means the tab rail itself (mounted only
    // once `phase === "loaded"`, below) briefly disappears behind the loading placeholder on every
    // tab switch, the same as it already does on a year change -- an accepted, existing trade-off
    // this page makes for "recompute rather than cache" (see `app/api/tax.py`'s own docstring),
    // extended here to paging.
  }, [year, tab, disposalsOffset, washOffset]);

  // Normally `currentYear` down to `currentYear - 8`. Widened to include the resolved default when
  // it falls outside that window (a ledger whose only activity is older than eight years, or -- in
  // principle -- dated ahead of today) so the selector's value is always one of its own options
  // rather than a year silently missing from the list it was chosen from.
  const yearOptions = useMemo(() => {
    const top = year !== null && year > currentYear ? year : currentYear;
    const bottom = year !== null && year < currentYear - 8 ? year : currentYear - 8;
    const years: number[] = [];
    for (let y = top; y >= bottom; y--) years.push(y);
    return years;
  }, [currentYear, year]);

  return (
    // `.tax-page` is the print stylesheet's hook and nothing else -- `Tax.css`'s `@media print`
    // rules are all scoped under it, so loading that stylesheet (it is bundled app-wide, like every
    // other page's) cannot change how any other page prints. See `Tax.css`'s own header.
    <div className="tax-page">
      <h1>{t("tax.title")}</h1>
      <p className="subtitle">
        {/* No account count here on purpose. This line read "all eight accounts" for months while
            the ledger held seven -- a number that was true when it was written and silently stopped
            being true, which is the whole failure mode this page's honesty rules exist to prevent.
            "Every account" is true at any ledger size and needs no maintenance. */}
        {t("tax.subtitle")}
      </p>

      <Disclaimer />

      {year === null ? (
        <div className="panel">
          <div className="placeholder">{t("tax.loading.initial")}</div>
        </div>
      ) : (
        <>
          <div className="panel">
            <label className="year-select">
              {t("tax.yearSelect.label")}
              <select
                value={year}
                onChange={(e) => {
                  // Both offsets reset in the same handler that changes `year`, landing in the same
                  // render rather than a separate effect keyed on `year` -- an effect would still
                  // fire the fetch below with the *previous* year's stale offset for one extra
                  // request before a second effect run corrected it.
                  setYear(Number(e.target.value));
                  setDisposalsOffset(0);
                  setWashOffset(0);
                }}
              >
                {yearOptions.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {phase === "loading" && (
            <div className="panel">
              <div className="placeholder">{t("tax.loading.year", { year })}</div>
            </div>
          )}

          {phase === "error" && (
            <div className="panel">
              <div className="placeholder">{error}</div>
            </div>
          )}

          {phase === "empty" && (
            <div className="panel">
              <div className="placeholder">
                {/* The closing line belongs to `EmptyYearMessage`, not to this panel. It used to be
                    appended here for all three cases and read "this is an absence of data, not a
                    report of zero gains" — which is true of the two absences and flatly contradicts
                    the third, where the year genuinely has activity and genuinely has zero gains. A
                    UAT persona read the two sentences against each other and filed the contradiction. */}
                <EmptyYearMessage year={year} context={emptyContext} />
              </div>
            </div>
          )}

          {phase === "loaded" && report && (
            <>
              {/* Each top-level panel below gets its own boundary: this page computes tax figures
                  from replayed brokerage history, and a malformed value in one panel's slice of the
                  report (see `ErrorBoundary.tsx`'s own docstring for the concrete incident this
                  guards against -- an undefined money field took the whole Tax page to a white
                  screen) must not also hide every other, unrelated figure on the same page. */}
              {/* Above the tab rail, unconditionally on every tab -- not just when `tab === "summary"`.
                  This is the one legally-relevant callout with a promotion threshold at all (see
                  `shouldPromoteUncertainBasis`'s docstring), and "do not hide behind a tab click" means
                  a reader who lands on `?tab=wash` from a bookmark must see it too, not only a reader
                  who happens to be on the default tab. */}
              <PanelBoundary label={t("tax.panel.uncertainBasisCaveat")}>
                {/* The year's disposal count, the same figure the Disposals badge shows -- never
                    `gains.rows.length`, which is one page. See `UncertainBasisMagnitudeCaveat`. */}
                <UncertainBasisPromotedCaveat
                  gains={report.gains}
                  total={report.disposals_total ?? report.gains.rows.length}
                />
              </PanelBoundary>

              <FolderTabs
                label={t("tax.tabs.label")}
                active={tab}
                // `FolderTabs` is generic over plain `string` ids; the cast is safe because every
                // `id` below is drawn from `TAX_TABS`, the same union `useTabParam`'s `allowed` list
                // enforces -- there is no id this rail can ever hand back that isn't a `TaxTab`.
                onChange={(id) => setTab(id as TaxTab)}
                items={[
                  { id: "summary", label: t("tax.tabs.summary") },
                  {
                    id: "disposals",
                    // The year's true count, not `report.gains.rows.length` -- that array is now
                    // only the active page once `disposalsOffset`/`limit` slice it, and the badge
                    // must not shrink to the page size just because a later page is showing.
                    label: t("tax.tabs.disposals"),
                    badge: String(report.disposals_total ?? report.gains.rows.length),
                  },
                  {
                    id: "wash",
                    label: t("tax.tabs.wash"),
                    badge: String(report.wash_events_total ?? report.wash_sales.length),
                  },
                  {
                    id: "f8949",
                    label: t("tax.tabs.f8949"),
                    badge: String(report.form8949.rows.length),
                  },
                ]}
              />

              {/* Only the active tab's subtree is mounted -- the whole point of this refactor. The
                  Disposals table alone used to run ~1,341 rows unconditionally; now it exists in the
                  DOM only while `tab === "disposals"`. */}
              {tab === "summary" && (
                <>
                  {/* `SummaryTiles` carries the OTHER legally-relevant callout (permanently
                      disallowed) plus the muted, non-promoted uncertain-basis note -- both already
                      the first thing rendered on this, the default tab, i.e. above the fold without
                      any click required. */}
                  <PanelBoundary label={t("tax.panel.summary")}>
                    <SummaryTiles
                      gains={report.gains}
                      total={report.disposals_total ?? report.gains.rows.length}
                      year={year}
                    />
                  </PanelBoundary>
                  <PanelBoundary label={t("tax.panel.warnings")}>
                    <WarningsSection
                      warnings={report.warnings}
                      warningGroups={report.warning_groups}
                      year={report.tax_year}
                    />
                  </PanelBoundary>
                </>
              )}

              {tab === "disposals" && (
                <PanelBoundary label={t("tax.panel.disposals")}>
                  <DisposalsTable
                    gains={report.gains}
                    total={report.disposals_total ?? report.gains.rows.length}
                    year={report.tax_year}
                    offset={disposalsOffset}
                    hasMore={report.disposals_has_more ?? false}
                    onOffsetChange={setDisposalsOffset}
                  />
                </PanelBoundary>
              )}

              {tab === "wash" && (
                <>
                  <PanelBoundary label={t("tax.panel.washSalesBySymbol")}>
                    <WashSaleSymbolPanel
                      summary={report.wash_sale_summary}
                      year={year}
                      report={report}
                    />
                  </PanelBoundary>
                  <PanelBoundary label={t("tax.panel.washSales")}>
                    <WashSaleTable
                      events={report.wash_sales}
                      total={report.wash_events_total ?? report.wash_sales.length}
                      year={report.tax_year}
                      offset={washOffset}
                      hasMore={report.wash_events_has_more ?? false}
                      onOffsetChange={setWashOffset}
                    />
                  </PanelBoundary>
                  <PanelBoundary label={t("tax.panel.unsettledClassifications")}>
                    <UnsettledSection pairs={report.unsettled} year={report.tax_year} />
                  </PanelBoundary>
                  {/* The former `/wash-sales` page, folded in here rather than kept as its own nav
                      destination. It is NOT a duplicate of the two panels above: those are
                      year-scoped and event-grained (which disallowances this tax year's report
                      carries), while this is whole-ledger and present-tense (which §1091 windows are
                      still open *today*, and when each closes). Two readers' questions, one tab --
                      appended below rather than replacing anything, and under its own subheading so
                      the change of scope is stated rather than left to be inferred from two tables
                      that disagree. `/wash-sales` redirects here; see `App.tsx`. */}
                  <PanelBoundary label={t("tax.washSales.openWindowsHeading")}>
                    <>
                      <h2 className="section-heading">{t("tax.washSales.openWindowsHeading")}</h2>
                      <WashSalesSection />
                    </>
                  </PanelBoundary>
                </>
              )}

              {tab === "f8949" && (
                <>
                  <PanelBoundary label={t("tax.panel.form8949")}>
                    <Form8949Section report={report} />
                  </PanelBoundary>
                  {/* The pack sits between the form and the reconcile panel because that is the
                      order the work happens in: read the form, take the files to your CPA, then
                      diff what comes back against the 1099-B. */}
                  <PanelBoundary label={t("tax.export.pack.title")}>
                    <ReconciliationPack year={report.tax_year} />
                  </PanelBoundary>
                  {/* Reconciling is the step that comes *after* you have the numbers, and the
                      disclaimer at the top of this page has always said it is required before
                      filing. It rides along on the Form 8949 tab, the last stop before filing. */}
                  <PanelBoundary label={t("tax.panel.reconcile")}>
                    <ReconcilePanel year={year} />
                  </PanelBoundary>
                </>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

function isEmptyReport(report: TaxReport): boolean {
  // `disposals_total`/`wash_events_total`, not `report.gains.rows.length`/`report.wash_sales.length`
  // -- those two arrays are now only the active page once a `limit` slices them, and a year with
  // real disposals must never read as empty merely because the page fetched for the current tab
  // (Summary asks for the smallest one of each -- see the report-fetch effect above) happened to be
  // small. The `??` fallback covers a response with no paging metadata at all -- see `TaxReport`'s
  // own docstring in `api/tax.ts` -- in which case the array *is* the whole set and `.length` is
  // exactly right. `form8949.rows`/`unsettled`/`warnings` are never paginated, so their own
  // `.length` still means exactly what it always did.
  return (
    (report.disposals_total ?? report.gains.rows.length) === 0 &&
    report.form8949.rows.length === 0 &&
    (report.wash_events_total ?? report.wash_sales.length) === 0 &&
    report.unsettled.length === 0 &&
    report.warnings.length === 0
  );
}

/**
 * The page-level disclaimer, rendered above the tab rail so every tab carries it -- Summary and
 * Form 8949 included, which are the two a filer is on when the numbers leave this app.
 *
 * The scope sentence (`tax.washSales.footer`) is the *same key* the Wash Sales page renders in its
 * own footer, not a second copy of it. This is the page that generates the Form 8949, and the
 * sentence it needs -- options are not covered, and neither is a repurchase in an account this app
 * cannot see, a spouse's included -- was previously said only on the other page. §1091 applies
 * across every account a taxpayer controls, so a filer reading only this page had the one exclusion
 * that can invalidate the form withheld from them. One key, two renders (COPY-STYLE.md rule 2).
 */
function Disclaimer() {
  const { t } = useT();
  return (
    <div className="panel disclaimer" role="note">
      <StatusPill tone="warn" label={t("ui.pill.notAdvice")} />{" "}
      <strong>{t("tax.disclaimer.title")}</strong> {t("tax.disclaimer.body")}
      <p className="muted">{t("tax.washSales.footer")}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Promoted uncertain-basis caveat -- shown above the figures, not 330 lines below them
// ---------------------------------------------------------------------------

/**
 * When most of a tax year's disposals have an unverifiable basis, the headline gain figures are
 * not a number so much as an upper bound, and the reader needs to know that *before* the number,
 * not after scrolling past it and the warnings list. Below `UNCERTAIN_BASIS_PROMOTION_THRESHOLD`
 * this renders nothing -- the existing muted note inside `SummaryTiles` already covers a handful of
 * gaps proportionately.
 */
/**
 * Per-disposal detail, including which lot was relieved and under what rule.
 *
 * `gains.rows` was previously computed, carried through the API and never rendered -- the page
 * showed summary tiles and the Form 8949 boxes, with nothing in between. So a user asking the
 * ordinary question "which shares did I just sell?" had no answer on screen. A UAT persona resorted
 * to dividing cost basis by quantity and matching the result against its own fill prices to work out
 * that FIFO had been applied. It had, and lot selection changes the tax outcome, so it is stated
 * here rather than left to arithmetic.
 *
 * Form 8949 deliberately does not carry these columns: it mirrors the IRS layout, and a lot id is
 * not part of that form.
 */
function DisposalsTable({
  gains,
  total,
  year,
  offset,
  hasMore,
  onOffsetChange,
}: {
  gains: GainsReport;
  /** Disposals for the whole year, ignoring paging -- `TaxReport.disposals_total`. May exceed
   *  `gains.rows.length` once a `limit` has sliced that array to one page. */
  total: number;
  /** The tax year, for the table's caption. Named there rather than left implicit: the caption is
   *  the only thing a screen reader hears before ten columns of dates and money, and the year is
   *  exactly the fact those cells cannot supply. */
  year: number;
  offset: number;
  hasMore: boolean;
  onOffsetChange: (next: number) => void;
}) {
  const { t } = useT();
  // Live symbol substring filter -- `FilterBar` already renders the "showing N of M" count and the
  // Clear button; this component only owns the predicate. It runs over `gains.rows` alone, which is
  // one *page* of the year's disposals now that this table is server-paged -- a symbol that only
  // appears on a different page will not show up here until that page is fetched. `total === 0` (not
  // `gains.rows.length === 0`) is checked AFTER this hook, not before, so the hook order stays
  // stable across renders regardless of which year the caller passes in (Rules of Hooks), and so an
  // out-of-range page for a genuinely non-empty year still renders the panel (and its Pager) rather
  // than disappearing.
  const [query, setQuery] = useState("");
  if (total === 0) return null;

  const q = query.trim().toLowerCase();
  const rows = q ? gains.rows.filter((row) => row.symbol.toLowerCase().includes(q)) : gains.rows;

  return (
    <ScrollPanel
      size="md"
      label={t("tax.panel.disposals")}
      expandable
      panelClassName="disposals-panel"
      title={
        <div>
          <h2>{t("tax.panel.disposals")}</h2>
          <p className="subtitle">{t("tax.disposals.subtitle")}</p>
          {/* One InfoNote near the header replaces the four per-cell `title=` tooltips this table
              used to carry (lot id, "no lot", basis-uncertain "?", holding-tolled note) -- none of
              which a touch or keyboard user could ever reach. */}
          <InfoNote tone="quiet" summary={t("tax.disposals.columnsNote.summary")}>
            <p>{t("tax.disposals.columnsNote.lotId")}</p>
            <p>{t("tax.disposals.columnsNote.noLot")}</p>
            <p>{t("tax.disposals.columnsNote.basisUncertain")}</p>
            <p>{t("tax.disposals.columnsNote.tolled")}</p>
          </InfoNote>
        </div>
      }
      actions={
        <FilterBar
          query={query}
          onQueryChange={setQuery}
          queryPlaceholder={t("tax.disposals.filterPlaceholder")}
          // `shown` is the filter match count on *this page* -- the filter has no server side yet,
          // so it cannot reach rows sitting on a different page. `total` is still the whole year's
          // count, not this page's, so the "N of M" line reads correctly when the filter is empty.
          shown={rows.length}
          total={total}
        />
      }
    >
      <TaxPager total={total} offset={offset} limit={PAGE_SIZE} hasMore={hasMore} onOffsetChange={onOffsetChange} />
      <div className="table-wrap">
        <table className="data-table" data-testid="disposals-table">
          {/* `total`, not `rows.length`: the caption states the year's row count, which is what the
              table is *of*. The filter's own "showing N of M" line beside the header is what says
              how many are on screen right now. */}
          <caption className="visually-hidden">
            {t("tax.caption.disposals", { year, count: total })}
          </caption>
          <thead>
            <tr>
              <th scope="col">{t("tax.header.sold")}</th>
              <th scope="col">{t("common.symbol")}</th>
              <th scope="col" className="num">
                {t("tax.header.qty")}
              </th>
              <th scope="col">{t("tax.header.acquired")}</th>
              <th scope="col">{t("tax.header.lotMethod")}</th>
              <th scope="col">{t("tax.header.term")}</th>
              <th scope="col" className="num">
                {t("tax.header.proceeds")}
              </th>
              <th scope="col" className="num">
                {t("tax.header.costBasis")}
              </th>
              <th scope="col" className="num">
                {t("tax.header.gainLoss")}
              </th>
              <th scope="col">{t("tax.header.account")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={10} className="placeholder">
                  {t("tax.disposals.filteredEmpty")}
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.disposal_id}>
                  <td>{row.disposed_date}</td>
                  <td>
                    <Link to={`/symbol/${encodeURIComponent(row.symbol)}`}>{row.symbol}</Link>
                  </td>
                  <td className="num">{row.quantity}</td>
                  <td>
                    {row.acquired_date}
                    {row.holding_start !== row.acquired_date && (
                      <span className="muted">
                        {" "}
                        {t("tax.disposals.holdingFrom", { date: row.holding_start })}
                      </span>
                    )}
                  </td>
                  <td className="muted">
                    {/* The lot id is a hash and too long for a cell -- the first octet plus the
                        method is enough to tell two lots apart; the InfoNote above the table
                        carries the rest, not a per-cell tooltip. */}
                    {row.lot_id.slice(0, 8)}
                    {" · "}
                    {row.lot_method === null ? t("tax.disposals.noLot") : row.lot_method.toUpperCase()}
                  </td>
                  <td>{row.term === "short" ? t("tax.term.short") : t("tax.term.long")}</td>
                  <td className="num">{formatMoney(row.proceeds)}</td>
                  <td className="num">
                    {formatMoney(row.cost_basis)}
                    {row.basis_uncertain && <span className="muted"> ?</span>}
                  </td>
                  <td className="num">{formatMoney(row.reportable_gain_loss)}</td>
                  <td className="muted">{row.account_label}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <TaxPager total={total} offset={offset} limit={PAGE_SIZE} hasMore={hasMore} onOffsetChange={onOffsetChange} />
      <p className="muted">
        {/* The year's total, not `gains.rows.length` (the current page) -- this sentence is a
            year-wide disclaimer about the gain/loss column, not a description of the page. */}
        {t(total === 1 ? "tax.disposals.footer_one" : "tax.disposals.footer_other", { count: total })}
      </p>
    </ScrollPanel>
  );
}

/**
 * A page/offset control shared by the Disposals and Wash sales tables -- the two lists
 * `GET /api/tax/report`'s `limit`/`offset` actually page. Mirrors `Activity.tsx`'s own `Pager`
 * (same copy, same "hide when everything already fits on one page" rule) rather than importing it:
 * that component is private to `Activity.tsx` and reads a `TransactionPage`, a shape neither table
 * here has -- there is no third caller yet to justify lifting it into a shared component.
 */
function TaxPager({
  total,
  offset,
  limit,
  hasMore,
  onOffsetChange,
}: {
  total: number;
  offset: number;
  limit: number;
  hasMore: boolean;
  onOffsetChange: (next: number) => void;
}) {
  const { t } = useT();
  if (total <= limit) return null;

  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);

  return (
    <div className="panel pager">
      <button
        type="button"
        disabled={offset === 0}
        onClick={() => onOffsetChange(Math.max(0, offset - limit))}
      >
        {t("tax.pager.previous")}
      </button>
      <span>
        {t("tax.pager.range", {
          first: first.toLocaleString(),
          last: last.toLocaleString(),
          total: total.toLocaleString(),
        })}
      </span>
      <button type="button" disabled={!hasMore} onClick={() => onOffsetChange(offset + limit)}>
        {t("tax.pager.next")}
      </button>
    </div>
  );
}

/**
 * Whether the uncertain-basis caveat belongs *above* the figures rather than beneath them.
 *
 * Either test promotes on its own -- they catch different shapes. A year that is mostly guesswork by
 * row count is caught by the first even if it nets to little; a year where a handful of large
 * transferred positions carry most of the gain is caught only by the second, and that is the shape
 * a real ledger can have.
 *
 * Exported to the two callers deliberately: the promoted caveat and the tile-level one say the same
 * thing at different volumes, so exactly one may render. Two boxes repeating "N disposals,
 * $X, Y%" a screen apart does not double the warning, it teaches the reader to skip both.
 *
 * `total` is the year's disposal count (`TaxReport.disposals_total`), passed in rather than read
 * off `gains.rows.length` -- see `UncertainBasisMagnitudeCaveat`'s own note. Taking it from the
 * page would make the promotion threshold itself a function of which page is on screen: 8 uncertain
 * rows against a 100-row page is 8% and silent, but the same 8 against the next page's 47 rows is
 * 17%, and paging forward would fire a legal callout that paging back dismisses.
 */
function shouldPromoteUncertainBasis(gains: GainsReport, total: number): boolean {
  const uncertain = gains.rows_with_uncertain_basis;
  if (total === 0 || uncertain === 0) return false;
  const gainShare = moneyPercentOf(
    gains.gain_on_uncertain_basis,
    addMoney(gains.short_term_gain, gains.long_term_gain),
  );
  return (
    uncertain / total >= UNCERTAIN_BASIS_PROMOTION_THRESHOLD ||
    (gainShare !== null && gainShare >= UNCERTAIN_GAIN_PROMOTION_THRESHOLD * 100)
  );
}

/**
 * The uncertain-basis caveat, promoted above the headline figures.
 *
 * Deliberately the *same component* as the one beneath the tiles rather than a second, tersER copy
 * of the same warning. Two boxes a screen apart both reading "N disposals, $X,
 * Y%" does not double the warning -- it teaches the reader that these boxes repeat themselves and
 * can be skipped. Exactly one renders; this one wins when `shouldPromoteUncertainBasis` says the
 * doubt is large enough that the reader needs it before the number rather than after it.
 */
function UncertainBasisPromotedCaveat({ gains, total }: { gains: GainsReport; total: number }) {
  if (!shouldPromoteUncertainBasis(gains, total)) return null;
  return (
    <UncertainBasisMagnitudeCaveat
      gains={gains}
      total={total}
      netGain={addMoney(gains.short_term_gain, gains.long_term_gain)}
      placement="promoted"
    />
  );
}

// ---------------------------------------------------------------------------
// Summary tiles
// ---------------------------------------------------------------------------

/**
 * The five headline figures, each labelled with the tax year it was computed over.
 *
 * The year is in the label rather than under it because all five come off `GainsReport`, which the
 * backend builds from the disposals inside `[start, end]` only -- and the deferred wash-sale figure
 * beside them has a whole-ledger twin on the Wash Sales page, several times its size, wearing what
 * used to be nearly the same label. A reader landing on the two pages in either order had one
 * unscoped "Wash-sale disallowed (deferred)" and one unscoped "Deferred", differing by a factor
 * neither label accounted for, with the explanation sitting in a hint under one of them.
 * DEFINITIONS.md standing rule 2: where two figures could be confused, the label disambiguates
 * both.
 */
function SummaryTiles({
  gains,
  total,
  year,
}: {
  gains: GainsReport;
  /** Disposals for the whole year -- `TaxReport.disposals_total`, not the fetched page. */
  total: number;
  year: number;
}) {
  const { t } = useT();
  const netGain = addMoney(gains.short_term_gain, gains.long_term_gain);
  const hasPermanent = !isZero(gains.permanently_disallowed_total);

  return (
    <>
      <div className="panel">
        <div className="tile-grid">
          <StatTile
            label={t("tax.tile.shortTermGain", { year })}
            value={formatMoney(gains.short_term_gain)}
          />
          <StatTile
            label={t("tax.tile.longTermGain", { year })}
            value={formatMoney(gains.long_term_gain)}
          />
          <StatTile label={t("tax.tile.netGain", { year })} value={formatMoney(netGain)} emphasize />
          <StatTile
            label={t("tax.tile.washSaleDisallowedDeferred", { year })}
            value={formatMoney(gains.disallowed_loss_total)}
            hint={t("tax.tile.washSaleDisallowedHint")}
          />
          <StatTile
            label={t("tax.tile.permanentlyDisallowedIra", { year })}
            value={formatMoney(gains.permanently_disallowed_total)}
            hint={t("tax.tile.permanentlyDisallowedHint")}
            variant="danger"
          />
        </div>
        {/* The way out to the whole-ledger view of the deferred tile beside it. Rendered under the
            row rather than inside that tile's own `hint`, which `StatGrid` types as a `string` --
            widening it to a node is a change to a component five other pages share, and this link
            does not need it. The two figures are deliberately different windows (this year vs the
            whole ledger); the arrow is the invitation to go and see the other one. */}
        <p className="muted tax-tile-link">
          <Link to="/tax?tab=wash">{t("tax.tile.deferred.seeWashSales")}</Link>
        </p>
      </div>

      {hasPermanent && (
        <div className="panel callout callout-danger">
          <strong>{t("tax.summary.permanentCallout.lead")}</strong>{" "}
          {t("tax.summary.permanentCallout.rest", {
            amount: formatMoney(gains.permanently_disallowed_total),
          })}
        </div>
      )}

      {/* Only when the promoted caveat above the tiles did not already say all of this. */}
      {!shouldPromoteUncertainBasis(gains, total) && (
        <UncertainBasisMagnitudeCaveat gains={gains} total={total} netGain={netGain} />
      )}
    </>
  );
}

/**
 * The vaguer sibling of `UncertainBasisPromotedCaveat` above — shown whenever any row has an
 * uncertain basis, not only once the share crosses that function's promotion threshold. A row
 * count alone understates a concentrated gap: on a real ledger the uncertain rows can be a small share of
 * the count but most of the reported gain, because the missing-basis rows are disproportionately
 * the large ones (an ACAT transfer of an existing position, not five shares of a small buy).
 * Naming only the count told a reader "9.4%, a rounding concern" when the truth was "most of this
 * number is unverified" — the same failure `CashCaveat` and `PartialTotalsCaveat` exist to avoid
 * on the Portfolio page. See `GainsReport.gain_on_uncertain_basis`'s docstring in
 * `backend/app/tax/models.py`.
 *
 * Renders nothing when there are no uncertain rows, or no disposals at all — both guarded before
 * any arithmetic runs, so this never divides by zero.
 */
function UncertainBasisMagnitudeCaveat({
  gains,
  total,
  netGain,
  placement = "beneath",
}: {
  gains: GainsReport;
  /**
   * Disposals in the whole tax year -- `TaxReport.disposals_total`, the same count the Disposals
   * tab's badge shows, falling back to `gains.rows.length` for a response with no paging metadata.
   *
   * Emphatically NOT `gains.rows.length` read here. That array is one *page* (100 rows) once
   * `limit`/`offset` slice it, while `rows_with_uncertain_basis` and `gain_on_uncertain_basis`
   * beside it are whole-year aggregates the backend leaves untouched by paging
   * (`app.api.tax._paginate_report`). Reading the denominator off the page produced "4/100
   * disposals lack cost basis" on a year with over a thousand of them -- a ratio 14x too alarming,
   * inside a `role="alert"` callout above the headline gain, that then *changed as the reader
   * paged*. A numerator and a denominator from two different populations is not a ratio at all;
   * DEFINITIONS.md standing rule 6.
   */
  total: number;
  netGain: DecimalString;
  /** Where on the page this instance sits. Changes the severity and the one word that would
   *  otherwise point the reader in the wrong direction ("reported above" vs "below"). */
  placement?: "promoted" | "beneath";
}) {
  const { t } = useT();
  const uncertain = gains.rows_with_uncertain_basis;
  if (uncertain === 0 || total === 0) return null;

  const remainingCount = total - uncertain;
  // Exact, via integer cents -- what the OTHER (established-basis) rows net to on their own.
  const remainder = subtractMoney(netGain, gains.gain_on_uncertain_basis);
  const remainderIsZero = isZero(remainder);
  const remainderNegative = !remainderIsZero && remainder.trim().startsWith("-");
  const remainderAbs = remainder.trim().startsWith("-") ? remainder.trim().slice(1) : remainder;
  // `null` when `netGain` is zero -- guarded inside `moneyPercentOf`, not here, so this component
  // never has to special-case the denominator itself.
  const pctOfHeadline = moneyPercentOf(gains.gain_on_uncertain_basis, netGain);

  // The headline and remainder sentences vary along an English grammar axis Korean does not have
  // (singular/plural, and here also a below/above or loss/gain word choice) -- per this project's
  // i18n rule against splicing a raw-English fragment onto a template, each shape is its own
  // catalog entry rather than a string assembled from parts. See `messages/tax.ts`.
  const headlineKey =
    pctOfHeadline === null
      ? total === 1
        ? ("tax.uncertainBasis.headline_one" as const)
        : ("tax.uncertainBasis.headline_other" as const)
      : placement === "promoted"
        ? total === 1
          ? ("tax.uncertainBasis.headlineRatio_one_below" as const)
          : ("tax.uncertainBasis.headlineRatio_other_below" as const)
        : total === 1
          ? ("tax.uncertainBasis.headlineRatio_one_above" as const)
          : ("tax.uncertainBasis.headlineRatio_other_above" as const);

  const remainderKey = remainderIsZero
    ? remainingCount === 1
      ? ("tax.uncertainBasis.remainder_one_zero" as const)
      : ("tax.uncertainBasis.remainder_other_zero" as const)
    : remainderNegative
      ? remainingCount === 1
        ? ("tax.uncertainBasis.remainder_one_loss" as const)
        : ("tax.uncertainBasis.remainder_other_loss" as const)
      : remainingCount === 1
        ? ("tax.uncertainBasis.remainder_one_gain" as const)
        : ("tax.uncertainBasis.remainder_other_gain" as const);

  return (
    <div
      className={`panel callout ${placement === "promoted" ? "callout-danger" : "callout-warn"}`}
      role="alert"
    >
      {/* The headline (how much of the gain is a bound, not a figure) is the one line a filer must
          not miss, so it stays visible; the arithmetic that supports it -- what the other rows net
          to, proceeds-vs-basis, and how to fix it -- is "longer than that" and sits behind the
          expandable. Kept as a one-line caveat rather than fully hidden: this is the "your number
          is a bound" alert, and a filing tool should never bury that by default. */}
      <strong>
        {t(headlineKey, {
          uncertain: uncertain.toLocaleString(),
          total: total.toLocaleString(),
          gainOnUncertain: formatMoney(gains.gain_on_uncertain_basis),
          pct: pctOfHeadline ?? 0,
          netGain: formatMoney(netGain),
        })}
      </strong>
      <details className="warning-detail">
        <summary>{t("tax.uncertainBasis.showDetail")}</summary>
        {remainingCount > 0 && (
          <>
            {t(remainderKey, {
              count: remainingCount.toLocaleString(),
              amount: formatMoney(remainderAbs),
            })}{" "}
          </>
        )}
        {t("tax.uncertainBasis.proceedsVsBasis", {
          proceeds: formatMoney(gains.proceeds_on_uncertain_basis),
          basis: formatMoney(gains.basis_on_uncertain_basis),
        })}
        <div>
          <Trans
            k="tax.uncertainBasis.fixIt"
            values={{
              openingPosition: <code>[[opening_position]]</code>,
              costBasisCode: <code>cost_basis</code>,
              accountsToml: <code>data/accounts.toml</code>,
            }}
          />
        </div>
      </details>
    </div>
  );
}

function isZero(value: string): boolean {
  return /^[+-]?0*(\.0*)?$/.test(value.trim());
}

// ---------------------------------------------------------------------------
// Warnings
// ---------------------------------------------------------------------------

// `warningKindLabel` lives in `@/api/tax`, beside the `TaxWarning` type whose tokens it decodes,
// so this page and the Portfolio page cannot drift apart when a new `WarningKind` is added
// server-side. See its docstring there.

function WarningsSection({
  warnings,
  warningGroups,
  year,
}: {
  warnings: TaxWarning[];
  warningGroups: WarningGroup[];
  /** The tax year, for the group table's caption -- these gaps are the selected year's, not the
   *  whole ledger's. */
  year: number;
}) {
  const { t } = useT();
  if (warnings.length === 0) return null;
  return (
    <div className="panel callout callout-danger">
      {/* Only the headline shows by default; the per-kind table and the full per-warning list are
          both "longer than that" and live behind one expandable, so the filer sees the one sentence
          that matters (figures overstated, N gaps) without scrolling a 1,000-row table to reach the
          disposals beneath it. Expand to audit; the counts stay in the headline either way. */}
      <strong>
        {t(warnings.length === 1 ? "tax.warnings.headline_one" : "tax.warnings.headline_other", {
          count: warnings.length,
        })}
      </strong>
      <details className="warning-detail">
        <summary>{t("tax.warnings.showGaps")}</summary>
        <div className="table-wrap">
          <table className="data-table warning-group-table">
            <caption className="visually-hidden">
              {t("tax.caption.warningGroups", { year })}
            </caption>
            <thead>
              <tr>
                <th scope="col">{t("tax.header.kind")}</th>
                <th scope="col">{t("tax.header.account")}</th>
                <th scope="col">{t("common.count")}</th>
                <th scope="col">{t("tax.header.example")}</th>
              </tr>
            </thead>
            <tbody>
              {warningGroups.map((g) => (
                <tr key={`${g.kind}:${g.account_id ?? ""}`}>
                  <td>{warningKindLabel(g.kind)}</td>
                  <td>
                    {g.account_id ?? "—"}
                    {g.broker ? ` (${g.broker})` : ""}
                  </td>
                  <td>{g.count}</td>
                  <td className="warning-sample">{g.sample_detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <details className="warning-detail">
          <summary>{t("tax.warnings.showAll", { count: warnings.length })}</summary>
          <ScrollRegion size="sm" label={t("tax.panel.warnings")}>
            <ul className="warning-list">
              {warnings.map((w, i) => (
                <li key={i}>
                  {warningKindLabel(w.kind)}
                  {w.account_id ? ` (${w.account_id})` : ""}: {w.detail}
                </li>
              ))}
            </ul>
          </ScrollRegion>
        </details>
      </details>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Wash sales
// ---------------------------------------------------------------------------

/**
 * Per-symbol wash-sale exposure, sitting above the per-event `WashSaleTable` below it. That table
 * is one row per event, which is the right grain for auditing a single disallowance back to its
 * replacement lots; this is one row per symbol, which is the right grain for the question a filer
 * actually asks next: "for this ticker, how much is deferred, how much is gone for good, and when
 * can I buy back in without triggering §1091 again."
 *
 * Deliberately scoped to the *entire connected ledger*, not the tax year selected above --
 * "is it safe to buy this back today" is a present-tense question, and filtering to a year would
 * silently hide a wash sale from outside it that still governs a purchase made today. That means
 * `summary.total_deferred` does not equal the "Wash-sale disallowed (deferred)" tile's
 * `gains.disallowed_loss_total` above, which *is* year-scoped -- on real data the two can
 * differ with nothing on the page explaining why. The scope line
 * below exists to close that gap for the reader, not to apologize for it.
 *
 * "Safe to repurchase" in the status column is narrower than it sounds: it clears only the
 * exact-CUSIP test this engine checks. It says nothing about a substantially-identical security
 * (the `UNSETTLED` equivalence table this engine keeps -- e.g. NVDA/NVDL -- is deliberately never
 * auto-applied; see `UnsettledSection` below on this page), options or contracts to acquire (not
 * modelled at all), or a purchase in an account this app has never seen, including a spouse's.
 * The panel footer says so explicitly rather than leaving it to be assumed.
 *
 * Renders nothing when `summary` is `null` -- the contract leaves it nullable for a report the
 * backend has not computed one for, and an absent summary is not the same claim as "zero
 * exposure," so there is no honest empty table to draw here the way `WashSaleTable` draws one for
 * a genuinely empty `events` array.
 */

type WashSortKey = "symbol" | "deferred" | "permanent" | "lossSales" | "lastSale" | "status";

// Module-level so `useTableSort`'s toggle keeps a stable identity across renders (see tableSort.tsx).
const WASH_SORT_DEFAULT_DIRS: Record<WashSortKey, "asc" | "desc"> = {
  symbol: "asc",
  deferred: "desc",
  permanent: "desc",
  lossSales: "desc",
  lastSale: "desc",
  status: "asc",
};

// `status` ascending sorts open windows first -- the actionable ones, where a repurchase now would
// re-defer the loss -- then by how soon each becomes safe; "completed" (closed) windows fall last.
const WASH_SORT_COMPARE: Record<
  WashSortKey,
  (a: WashSaleSymbolSummary, b: WashSaleSymbolSummary) => number
> = {
  symbol: (a, b) => a.symbol.localeCompare(b.symbol),
  deferred: (a, b) => Number(a.deferred_disallowed) - Number(b.deferred_disallowed),
  permanent: (a, b) => Number(a.permanently_disallowed) - Number(b.permanently_disallowed),
  lossSales: (a, b) => a.loss_sale_count - b.loss_sale_count,
  lastSale: (a, b) => a.last_sale_date.localeCompare(b.last_sale_date),
  status: (a, b) =>
    a.window_is_open !== b.window_is_open
      ? a.window_is_open
        ? -1
        : 1
      : a.days_until_safe - b.days_until_safe,
};

// Window-state filter values for the FilterBar's category select. "" is "all".
const WASH_FILTER_OPEN = "open";
const WASH_FILTER_COMPLETED = "completed";

function WashSaleSymbolPanel({
  summary,
  year,
  report,
}: {
  summary: WashSaleSummary | null;
  /** The tax year the rest of the page is scoped to. Named in the scope line rather than left
   *  as "the year selected above", so the reader can check the two totals against each other
   *  without first working out which year they are comparing. */
  year: number;
  /** The whole report, so `tolledOpenLotDatesBySymbol` (see below) runs *inside* this component's
   *  own render rather than in the caller's -- `Tax`'s. A `PanelBoundary` wrapped around this
   *  component only catches a throw that happens during this component's own render; a throw from a
   *  function called while building this component's *props*, in the caller, happens one frame
   *  earlier and would still take the whole page down with it, defeating the boundary's whole
   *  purpose. Taking `report` and computing the derived map here, instead of accepting it
   *  pre-computed, is what makes that failure containable. */
  report: TaxReport;
}) {
  const { t } = useT();
  // Hooks run before the null-guard below so their call order is stable across renders (Rules of
  // Hooks): the guard's early return must never sit between two hooks. Sort defaults to the largest
  // deferred loss first -- the figure a filer is scanning this table to find.
  const { sort, toggle } = useTableSort<WashSortKey>("deferred", WASH_SORT_DEFAULT_DIRS);
  const [query, setQuery] = useState("");
  const [windowFilter, setWindowFilter] = useState("");
  // `== null`, not `=== null`: the field is *absent* rather than null when the API serving this page
  // predates it, and a strict check lets `undefined` through to `summary.symbols` and takes the
  // whole Tax page down to its ErrorBoundary. Seen for real during this feature's own rollout, with
  // the frontend deployed against a backend that had not restarted. Same trap `formatMoneyOrDash`
  // hit earlier in this codebase, and the same fix.
  if (summary == null) return null;

  // See this function's docstring above -- computed here, inside the component `PanelBoundary`
  // actually wraps, not by the caller.
  const tolledOpenLots = tolledOpenLotDatesBySymbol(report);

  // Filter (symbol text + window state) then sort. "completed" is a closed window: the 61-day clock
  // has run out, the loss is settled and it is safe to repurchase -- the opposite of an open window.
  const q = query.trim().toLowerCase();
  const filteredSymbols = summary.symbols.filter((s) => {
    if (q && !s.symbol.toLowerCase().includes(q)) return false;
    if (windowFilter === WASH_FILTER_OPEN && !s.window_is_open) return false;
    if (windowFilter === WASH_FILTER_COMPLETED && s.window_is_open) return false;
    return true;
  });
  const rows = sortRows(filteredSymbols, sort, WASH_SORT_COMPARE);

  return (
    <div className="panel">
      <h2>{t("tax.panel.washSalesBySymbol")}</h2>
      <p className="subtitle wash-scope-line">
        <Trans
          k="tax.washSymbolPanel.scopeLine"
          values={{ year, isEmph: <em>{t("tax.washSymbolPanel.isWord")}</em> }}
        />
      </p>

      {summary.symbols.length === 0 ? (
        <div className="placeholder">{t("tax.washSymbolPanel.empty")}</div>
      ) : (
        <>
          <p className="muted wash-column-note">{t("tax.washSymbolPanel.columnNote")}</p>
          <FilterBar
            query={query}
            onQueryChange={setQuery}
            queryPlaceholder={t("tax.washSymbolPanel.filterPlaceholder")}
            choices={[
              { value: WASH_FILTER_OPEN, label: t("tax.washSymbolPanel.filterOpen") },
              { value: WASH_FILTER_COMPLETED, label: t("tax.washSymbolPanel.filterCompleted") },
            ]}
            choice={windowFilter}
            onChoiceChange={setWindowFilter}
            choiceAllLabel={t("tax.washSymbolPanel.filterAll")}
            shown={rows.length}
            total={summary.symbols.length}
          />
          <ScrollRegion size="md" label={t("tax.panel.washSalesBySymbol")}>
            <div className="table-wrap">
              <table className="data-table wash-summary-table">
              {/* Whole ledger, not the year the rest of the page is on -- the same scope this
                  panel's visible scope line above states, repeated for a reader who reaches the
                  table without it. `summary.symbols.length`, not `rows.length`: the caption
                  describes the table, and the FilterBar states what the filter is showing. */}
              <caption className="visually-hidden">
                {t("tax.caption.washBySymbol", {
                  asOf: summary.as_of,
                  count: summary.symbols.length,
                })}
              </caption>
              <thead>
                <tr>
                  <SortHeader label={t("common.symbol")} sortKey="symbol" sort={sort} onSort={toggle} />
                  <SortHeader
                    label={t("tax.header.deferred")}
                    sortKey="deferred"
                    sort={sort}
                    onSort={toggle}
                    numeric
                  />
                  <SortHeader
                    label={t("tax.header.permanentlyDisallowed")}
                    sortKey="permanent"
                    sort={sort}
                    onSort={toggle}
                    numeric
                  />
                  <SortHeader
                    label={t("tax.header.lossSales")}
                    sortKey="lossSales"
                    sort={sort}
                    onSort={toggle}
                    numeric
                  />
                  <SortHeader
                    label={t("tax.header.lastLossSale")}
                    sortKey="lastSale"
                    sort={sort}
                    onSort={toggle}
                  />
                  <SortHeader
                    label={t("tax.header.repurchaseStatus")}
                    sortKey="status"
                    sort={sort}
                    onSort={toggle}
                  />
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="placeholder">
                      {t("tax.washSymbolPanel.filteredEmpty")}
                    </td>
                  </tr>
                ) : (
                  rows.map((s) => {
                  // The single most important row in this table: a recent loss sale with no
                  // repurchase yet, so `deferred_disallowed` is a real "0.00" -- nothing to defer,
                  // *yet* -- rather than an absent figure. Left alone next to a loud warn badge it
                  // reads as "nothing happening here"; it is the opposite, so the row and the badge
                  // both get marked.
                  const noRepurchaseYet = s.window_is_open && isZero(s.deferred_disallowed);
                  const tolledDates = tolledOpenLots.get(s.symbol) ?? [];
                  return (
                    <tr key={s.symbol} className={noRepurchaseYet ? "wash-row-pending" : undefined}>
                      <td>
                        {s.symbol}
                        {tolledDates.length > 0 && (
                          <span className="muted" title={t("tax.washSymbolPanel.tolledTitle")}>
                            {" "}
                            {t("tax.washSymbolPanel.tolledText", { dates: tolledDates.join(", ") })}
                          </span>
                        )}
                      </td>
                      <td className="num">{formatMoney(s.deferred_disallowed)}</td>
                      <td className="num">{formatMoney(s.permanently_disallowed)}</td>
                      <td className="num">{s.loss_sale_count}</td>
                      <td>{s.last_sale_date}</td>
                      <td>
                        {s.window_is_open ? (
                          <span
                            className="badge wash-window-open"
                            title={t("tax.window.openTitle", { date: s.last_sale_date })}
                          >
                            {t(
                              s.days_until_safe === 1
                                ? "tax.washSymbolPanel.daysLeft_one"
                                : "tax.washSymbolPanel.daysLeft_other",
                              { days: s.days_until_safe, date: s.repurchase_safe_on },
                            )}
                          </span>
                        ) : (
                          <span
                            className="badge wash-window-safe"
                            title={t("tax.window.closedTitle", { date: s.last_sale_date })}
                          >
                            {t("tax.washSymbolPanel.safeToRepurchase", { date: s.repurchase_safe_on })}
                          </span>
                        )}
                        {noRepurchaseYet && (
                          <span className="wash-pending-note">
                            {" "}
                            {t("tax.washSymbolPanel.noRepurchaseYet")}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                  })
                )}
                </tbody>
              </table>
            </div>
          </ScrollRegion>

          <p className="muted wash-repurchase-note">{t("tax.washSymbolPanel.repurchaseNote")}</p>

          <div className="wash-totals">
            <p className="muted wash-total-deferred">
              <strong>
                {t("tax.washSymbolPanel.totalDeferredLead", {
                  amount: formatMoney(summary.total_deferred),
                })}
              </strong>{" "}
              {t("tax.washSymbolPanel.totalDeferredRest")}
            </p>
            <p className="muted wash-total-permanent">
              <strong>
                {t("tax.washSymbolPanel.totalPermanentLead", {
                  amount: formatMoney(summary.total_permanently_disallowed),
                })}
              </strong>{" "}
              {t("tax.washSymbolPanel.totalPermanentRest")}
            </p>
            <p className="muted wash-open-count">
              {t(
                summary.symbols.length === 1
                  ? "tax.washSymbolPanel.openCount_one"
                  : "tax.washSymbolPanel.openCount_other",
                {
                  openCount: summary.open_window_count,
                  total: summary.symbols.length,
                  asOf: summary.as_of,
                },
              )}
            </p>
          </div>
        </>
      )}

      <InfoNote className="wash-panel-footer" tone="quiet" summary={t("tax.washSymbolPanel.footer")}>
        <p>{t("tax.washSymbolPanel.footer.more")}</p>
      </InfoNote>
    </div>
  );
}

/**
 * Symbols carrying a wash-sale-tolled holding period on a replacement lot this report does not
 * already show as disposed.
 *
 * `GainRow.holding_start` already surfaces a tolled holding period for a lot that *was* sold this
 * year -- the `(holding from ...)` note in `DisposalsTable` above. `WashSaleEvent` carries the same
 * fact (`holding_period_tolled_to`) for every replacement lot, sold or not, but until now nothing on
 * the page rendered it for the ones still held -- a replacement lot that absorbed a disallowed loss
 * and was never sold showed its tolled date nowhere, even though the wire already carried it.
 * Cross-referencing against this year's disposed lot ids is what tells the two cases apart without a
 * new fetch or a new backend field: a `basis_added_to_lot_id` that is not among them was not
 * disposed within this report.
 *
 * This is not a claim that the lot is held *today* in some absolute sense -- only that this report's
 * own data does not show it disposed. A lot sold in a year outside the one currently selected would
 * also not appear here; closing that gap needs a positions endpoint this page does not fetch, which
 * is out of scope for this fix. And `TaxReport.wash_sales` is itself year-scoped to the sale date
 * (`build_tax_report` on the backend), so this only catches wash sales *triggered* in the selected
 * year -- not the full ledger history `WashSaleSymbolPanel` otherwise deliberately covers (see its
 * scope line).
 */
function tolledOpenLotDatesBySymbol(report: TaxReport): Map<string, string[]> {
  const disposedLotIds = new Set(report.gains.rows.map((row) => row.lot_id));
  const bySymbol = new Map<string, string[]>();
  for (const event of report.wash_sales) {
    if (event.holding_period_tolled_to == null) continue;
    // Every replacement lot, not just `basis_added_to_lot_id`. That field names the *one* lot that
    // absorbed the most basis, so a loss spread across three replacements points at one of them and
    // says nothing about the other two. Keying on it here would hide a still-held tolled lot
    // whenever the largest replacement happened to be the one sold. The backend had this exact bug
    // in `_sync_disposals` -- it re-synced only `basis_added_to_lot_id` and left the rest of a
    // multi-lot replacement unadjusted -- and it is the same mistake one layer up.
    const replacements = event.replacement_lot_ids.length
      ? event.replacement_lot_ids
      : event.basis_added_to_lot_id != null
        ? [event.basis_added_to_lot_id]
        : [];
    // Nothing to toll: a permanently disallowed loss (IRA replacement) has no lot to carry it.
    if (replacements.length === 0) continue;
    // Shown already in Disposals if every replacement was sold within this report.
    if (replacements.every((id) => disposedLotIds.has(id))) continue;
    const dates = bySymbol.get(event.symbol) ?? [];
    if (!dates.includes(event.holding_period_tolled_to)) dates.push(event.holding_period_tolled_to);
    bySymbol.set(event.symbol, dates);
  }
  return bySymbol;
}

function WashSaleTable({
  events,
  total,
  year,
  offset,
  hasMore,
  onOffsetChange,
}: {
  events: WashSaleEvent[];
  /** The tax year, for the caption. This table is year-scoped by sale date -- unlike the
   *  whole-ledger per-symbol panel above it, which is the confusion the two captions exist to
   *  prevent. */
  year: number;
  /** Triggered events for the whole ledger year, ignoring paging -- `TaxReport.wash_events_total`.
   *  May exceed `events.length` once a `limit` has sliced that array to one page. */
  total: number;
  offset: number;
  hasMore: boolean;
  onOffsetChange: (next: number) => void;
}) {
  const { t } = useT();

  // `total === 0`, not `events.length === 0` -- the latter is also true for an out-of-range page of
  // a genuinely non-empty year, and that must still render the table shell plus a working Pager to
  // page back, not the "no wash sales" empty state.
  if (total === 0) {
    return (
      <div className="panel">
        <h2>{t("tax.panel.washSales")}</h2>
        <div className="placeholder">{t("tax.washSaleTable.empty")}</div>
      </div>
    );
  }

  return (
    <ScrollPanel
      size="md"
      label={t("tax.panel.washSales")}
      expandable
      title={<h2>{t("tax.panel.washSales")}</h2>}
    >
      <TaxPager total={total} offset={offset} limit={PAGE_SIZE} hasMore={hasMore} onOffsetChange={onOffsetChange} />
      <div className="table-wrap">
        <table className="data-table">
          <caption className="visually-hidden">
            {t("tax.caption.washEvents", { year, count: total })}
          </caption>
          <thead>
            <tr>
              <th scope="col">{t("common.date")}</th>
              <th scope="col">{t("common.symbol")}</th>
              <th scope="col">{t("tax.header.accounts")}</th>
              <th scope="col">{t("tax.header.qtyReplacedSold")}</th>
              <th scope="col">{t("tax.header.loss")}</th>
              <th scope="col">{t("tax.header.disallowed")}</th>
              <th scope="col">{t("tax.header.treatment")}</th>
            </tr>
          </thead>
          <tbody>
            {events.map((ev) => {
              const accounts = Array.from(
                new Set([ev.sale_account_id, ...ev.replacement_account_ids]),
              ).join(", ");
              return (
                <tr key={ev.event_id}>
                  <td>{ev.sale_date}</td>
                  <td>
                    <Link to={`/symbol/${encodeURIComponent(ev.symbol)}`}>{ev.symbol}</Link>
                  </td>
                  <td>{accounts}</td>
                  <td>
                    {ev.quantity_replaced} / {ev.quantity_sold}
                  </td>
                  <td>{formatMoney(ev.loss_amount)}</td>
                  <td>{formatMoney(ev.disallowed_loss)}</td>
                  <td>
                    {ev.permanently_disallowed ? (
                      <span className="badge permanent">{t("tax.badge.permanent")}</span>
                    ) : (
                      <span className="badge deferred">{t("tax.badge.deferred")}</span>
                    )}{" "}
                    {/* Cross-link (UX refactor 3.3): this event's sale is one of the year's
                        disposals -- the Disposals tab is where its full per-lot detail (proceeds,
                        cost basis, term) actually lives, not on this table. */}
                    <Link
                      to="/tax?tab=disposals"
                      className="download-link"
                      title={t("tax.washSaleTable.viewDisposalsTitle")}
                    >
                      {t("tax.washSaleTable.viewDisposals")}
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <TaxPager total={total} offset={offset} limit={PAGE_SIZE} hasMore={hasMore} onOffsetChange={onOffsetChange} />
    </ScrollPanel>
  );
}

// ---------------------------------------------------------------------------
// Unsettled classifications
// ---------------------------------------------------------------------------

function UnsettledSection({ pairs, year }: { pairs: UnsettledPair[]; year: number }) {
  const { t } = useT();
  if (pairs.length === 0) return null;
  return (
    <div className="panel">
      <h2>{t("tax.panel.unsettledClassifications")}</h2>
      <p className="placeholder">{t("tax.unsettled.intro")}</p>
      <ScrollRegion size="md" label={t("tax.panel.unsettledClassifications")}>
        <div className="table-wrap">
          <table className="data-table">
            <caption className="visually-hidden">
              {t("tax.caption.unsettled", { year, count: pairs.length })}
            </caption>
            <thead>
              <tr>
                <th scope="col">{t("tax.header.saleDate")}</th>
              <th scope="col">{t("tax.header.sold")}</th>
              <th scope="col">{t("tax.header.replacement")}</th>
              <th scope="col">{t("tax.header.lossAtStake")}</th>
              <th scope="col">{t("tax.header.ifIdentical")}</th>
              <th scope="col">{t("tax.header.ifDistinct")}</th>
              <th scope="col">{t("tax.header.rationale")}</th>
            </tr>
          </thead>
          <tbody>
            {pairs.map((p) => (
              <tr key={p.sale_disposal_id}>
                <td>{p.sale_date}</td>
                <td>{p.sold_symbol}</td>
                <td>{p.replacement_symbol}</td>
                <td>{formatMoney(p.loss_amount)}</td>
                <td>
                  {t("tax.unsettled.disallowedAmount", { amount: formatMoney(p.impact_if_identical) })}
                </td>
                <td>
                  {t("tax.unsettled.disallowedAmount", { amount: formatMoney(p.impact_if_distinct) })}
                </td>
                <td>{p.rationale}</td>
              </tr>
            ))}
            </tbody>
          </table>
        </div>
      </ScrollRegion>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Form 8949
// ---------------------------------------------------------------------------

const BOX_ORDER: Form8949Box[] = ["A", "B", "C", "D", "E", "F"];
const SHORT_TERM_BOXES: Form8949Box[] = ["A", "B", "C"];
const LONG_TERM_BOXES: Form8949Box[] = ["D", "E", "F"];

const BOX_LABEL_KEY = {
  A: "tax.box.a",
  B: "tax.box.b",
  C: "tax.box.c",
  D: "tax.box.d",
  E: "tax.box.e",
  F: "tax.box.f",
} as const satisfies Record<Form8949Box, MessageKey>;

function Form8949Section({ report }: { report: TaxReport }) {
  const { t } = useT();
  const { form8949 } = report;
  const rowsByBox = useMemo(() => {
    const map = new Map<Form8949Box, Form8949Row[]>();
    for (const box of BOX_ORDER) map.set(box, []);
    for (const row of form8949.rows) map.get(row.box)?.push(row);
    return map;
  }, [form8949.rows]);

  // The box the subtotal for each term attaches to -- the *last non-empty* box in that term, not
  // unconditionally box C / box F. `rowsByBox` skips rendering an empty box entirely (see the `if
  // (rows.length === 0) return null` below), so anchoring the subtotal to a fixed box hid it whenever
  // that specific box happened to have no rows -- which is the common case: broker-reported basis
  // lands in A/B (short-term) and D/E (long-term), and C/F cover only trades with no 1099-B at all.
  // `null` when the whole term has no rows, so neither subtotal renders for a term that has nothing
  // to sum -- matching the old behaviour for a term genuinely absent from this year's disposals.
  const lastNonEmptyBox = (boxes: Form8949Box[]): Form8949Box | null => {
    for (let i = boxes.length - 1; i >= 0; i--) {
      const box = boxes[i];
      if (box && (rowsByBox.get(box) ?? []).length > 0) return box;
    }
    return null;
  };
  const lastShortTermBox = lastNonEmptyBox(SHORT_TERM_BOXES);
  const lastLongTermBox = lastNonEmptyBox(LONG_TERM_BOXES);

  return (
    <div className="panel">
      <div className="form8949-header">
        <h2>{t("tax.panel.form8949")}</h2>
        <a
          className="download-link"
          href={taxApi.form8949CsvUrl(report.tax_year)}
          download={`form8949-${report.tax_year}.csv`}
        >
          {t("tax.form8949.downloadCsv")}
        </a>
      </div>

      {form8949.rows.length === 0 ? (
        <div className="placeholder">{t("tax.form8949.empty")}</div>
      ) : (
        BOX_ORDER.map((box) => {
          const rows = rowsByBox.get(box) ?? [];
          if (rows.length === 0) return null;
          const isLast = box === lastShortTermBox || box === lastLongTermBox;
          return (
            <div className="form8949-box" key={box}>
              <h3>{t(BOX_LABEL_KEY[box])}</h3>
              <ScrollRegion size="md" label={t(BOX_LABEL_KEY[box])}>
                <div className="table-wrap">
                  <table className="data-table">
                    {/* Named per box, not "Form 8949": six of these render on a busy year and a
                        caption that did not say which box is the same as no caption at all. */}
                    <caption className="visually-hidden">
                      {t("tax.caption.form8949", {
                        box: t(BOX_LABEL_KEY[box]),
                        year: report.tax_year,
                        count: rows.length,
                      })}
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">{t("tax.header.description")}</th>
                    <th scope="col">{t("tax.header.acquired")}</th>
                    <th scope="col">{t("tax.header.sold")}</th>
                    <th scope="col">{t("tax.header.proceeds")}</th>
                    <th scope="col">{t("tax.header.costBasis")}</th>
                    <th scope="col">{t("tax.header.code")}</th>
                    <th scope="col">{t("tax.header.adjustment")}</th>
                    <th scope="col">{t("tax.header.gainLoss")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.disposal_id}>
                      <td>{row.description}</td>
                      <td>{row.date_acquired}</td>
                      <td>{row.date_sold}</td>
                      <td>{formatMoney(row.proceeds)}</td>
                      <td>{formatMoney(row.cost_basis)}</td>
                      <td>{row.adjustment_code ?? "—"}</td>
                      <td>{formatMoney(row.adjustment_amount)}</td>
                      <td>{formatMoney(row.gain_loss)}</td>
                    </tr>
                  ))}
                  </tbody>
                  </table>
                </div>
              </ScrollRegion>
              {isLast && (
                <Subtotal
                  label={t(SHORT_TERM_BOXES.includes(box) ? "tax.subtotal.shortTerm" : "tax.subtotal.longTerm")}
                  proceeds={
                    SHORT_TERM_BOXES.includes(box)
                      ? form8949.short_term_total_proceeds
                      : form8949.long_term_total_proceeds
                  }
                  basis={
                    SHORT_TERM_BOXES.includes(box)
                      ? form8949.short_term_total_basis
                      : form8949.long_term_total_basis
                  }
                  adjustment={
                    SHORT_TERM_BOXES.includes(box)
                      ? form8949.short_term_total_adjustment
                      : form8949.long_term_total_adjustment
                  }
                  gain={
                    SHORT_TERM_BOXES.includes(box)
                      ? form8949.short_term_total_gain
                      : form8949.long_term_total_gain
                  }
                />
              )}
            </div>
          );
        })
      )}
    </div>
  );
}

/**
 * The three CSVs a filer hands to whoever checks their return, plus a Print button for the same
 * tab as a working paper.
 *
 * One section, not three scattered download links: the point is that these are the *same three
 * tables* already on this page, exported together and scoped to the same year, so a reconciliation
 * can be done against a 1099-B without re-deriving which file covers what. Each link is a plain
 * `<a download>` -- the browser drives the download, so there is no fetch, no spinner and no error
 * path here; a failure surfaces as the browser's own, on a URL the user can see.
 *
 * The hint carries the "not tax advice" line a second time on purpose. It is already at the top of
 * the page, but these files outlive the page, and a CSV opened in a spreadsheet three weeks later
 * has no disclaimer attached to it -- COPY-STYLE.md rule 6, the one caveat that may be shortened
 * but never dropped.
 */
function ReconciliationPack({ year }: { year: number }) {
  const { t } = useT();
  const links: { key: string; href: string; filename: string; label: string }[] = [
    {
      key: "f8949",
      href: taxApi.form8949CsvUrl(year),
      filename: `form8949-${year}.csv`,
      label: t("tax.export.pack.form8949"),
    },
    {
      key: "disposals",
      href: taxApi.disposalsCsvUrl(year),
      filename: `disposals-${year}.csv`,
      label: t("tax.export.pack.disposals"),
    },
    {
      key: "washsales",
      href: taxApi.washSalesCsvUrl(year),
      filename: `washsales-${year}.csv`,
      label: t("tax.export.pack.washSales"),
    },
  ];

  return (
    <div className="panel tax-export-pack">
      <h2>{t("tax.export.pack.title")}</h2>
      <p className="muted tax-export-hint">{t("tax.export.pack.hint", { year })}</p>
      <div className="tax-export-actions">
        {links.map((link) => (
          <a key={link.key} className="download-link" href={link.href} download={link.filename}>
            {link.label}
          </a>
        ))}
        {/* `window.print()` rather than a rendered PDF: the print stylesheet in `Tax.css` already
            makes this tab a working paper, and every browser's own print dialog offers "Save as
            PDF" from there. A second rendering path would be a second thing to keep in agreement
            with the tables. */}
        <button
          type="button"
          className="download-link tax-print-button"
          title={t("tax.export.printTitle")}
          onClick={() => {
            window.print();
          }}
        >
          {t("tax.export.print")}
        </button>
      </div>
    </div>
  );
}

function Subtotal({
  label,
  proceeds,
  basis,
  adjustment,
  gain,
}: {
  label: string;
  proceeds: string;
  basis: string;
  adjustment: string;
  gain: string;
}) {
  const { t } = useT();
  return (
    <div className="form8949-subtotal">
      <strong>{label}:</strong>{" "}
      {t("tax.subtotal.detail", {
        proceeds: formatMoney(proceeds),
        basis: formatMoney(basis),
        adjustment: formatMoney(adjustment),
        gain: formatMoney(gain),
      })}
    </div>
  );
}
