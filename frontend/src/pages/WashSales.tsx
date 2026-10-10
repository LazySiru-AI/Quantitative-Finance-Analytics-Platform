import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { ApiRequestError } from "@/api/client";
import { formatMoney } from "@/api/tax";
import {
  symbolsInYear,
  washSaleYears,
  washSalesApi,
  yearOf,
  type WashSaleTracker,
  type WashSaleTrackerSale,
  type WashSaleTrackerSymbol,
} from "@/api/washsales";
import { ScrollRegion } from "@/components/ScrollPanel";
import Skeleton from "@/components/Skeleton";
import { StatTile } from "@/components/StatGrid";
import { SortHeader, sortRows, useTableSort } from "@/components/tableSort";
import StatusPill from "@/components/StatusPill";
import { Trans, useT } from "@/i18n";

import "./WashSales.css";

/**
 * The scope the page's lists are showing: the whole connected ledger, or one calendar year of loss
 * sales. `null` is "all years" and is the default -- an open window is a thing you act on today,
 * and defaulting to a year would hide a window opened by a sale in the previous December.
 */
type ScopeYear = number | null;

/**
 * How many days remain until `repurchase_safe_on` before a symbol's countdown is treated as
 * urgent enough to render in the "critical" tier (red, weighted). Chosen well inside a trading
 * week: three days is "act now or miss the window", not "keep an eye on it".
 */
const CRITICAL_DAYS = 3;

/**
 * The next tier out — still worth flagging with a warm colour, but not alarming. Ten days is
 * roughly a third of the 31-day window this tracker's dates are built from (see
 * `@/api/washsales`'s module docstring: `repurchase_safe_on` = last sale date + 31 days), so a
 * symbol in this band has burned through roughly two thirds of its window already.
 */
const SOON_DAYS = 10;

/**
 * The countdown bar's scale. Matches the +31 days `@/api/washsales` documents for
 * `repurchase_safe_on` and `window_closes_on`, so a freshly-opened window starts the bar at 0%
 * rather than understating how much of it is left. A `days_until_safe` above this (possible if a
 * later sale on the same symbol re-opened the window after this snapshot was taken) simply clamps
 * the bar at 0% full -- the exact day count next to it is the number of record either way.
 */
const WINDOW_SCALE_DAYS = 31;

type UrgencyTier = "critical" | "soon" | "open";

function urgencyTier(daysUntilSafe: number): UrgencyTier {
  if (daysUntilSafe <= CRITICAL_DAYS) return "critical";
  if (daysUntilSafe <= SOON_DAYS) return "soon";
  return "open";
}

/** Share of the window already elapsed, as a percentage fill for the countdown bar. */
function countdownFillPct(daysUntilSafe: number): number {
  const clamped = Math.max(0, Math.min(WINDOW_SCALE_DAYS, daysUntilSafe));
  return Math.round(((WINDOW_SCALE_DAYS - clamped) / WINDOW_SCALE_DAYS) * 100);
}

/** Same zero test `Tax.tsx`'s wash-sale panel uses -- kept local rather than imported since it is
 *  not exported from that file and this page does not own it. */
function isZero(value: string): boolean {
  return /^[+-]?0*(\.0*)?$/.test(value.trim());
}

/** Parse a decimal-string amount for ordering only; every printed figure still goes through
 *  `formatMoney` on the original string. A non-finite value sorts as 0 rather than throwing. */
function toAmount(value: string): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

/**
 * The Open windows table's sortable columns. Comparators are written ascending; `sortRows` applies
 * the active direction, so the per-column defaults below (`days`/`safe`/`symbol` ascending, the two
 * money columns descending) are what a fresh click on each header lands on.
 */
type OpenSortKey = "symbol" | "days" | "safe" | "deferred" | "permanent";

const OPEN_DEFAULT_DIRS: Record<OpenSortKey, "asc" | "desc"> = {
  symbol: "asc",
  days: "asc",
  safe: "asc",
  deferred: "desc",
  permanent: "desc",
};

const OPEN_SORT_COMPARE: Record<
  OpenSortKey,
  (a: WashSaleTrackerSymbol, b: WashSaleTrackerSymbol) => number
> = {
  symbol: (a, b) => a.symbol.localeCompare(b.symbol),
  // Tie-break every column by symbol so a re-sort is deterministic on equal keys. ISO
  // `repurchase_safe_on` dates sort correctly under a plain string compare.
  days: (a, b) =>
    a.days_until_safe - b.days_until_safe || a.symbol.localeCompare(b.symbol),
  safe: (a, b) =>
    a.repurchase_safe_on.localeCompare(b.repurchase_safe_on) ||
    a.symbol.localeCompare(b.symbol),
  deferred: (a, b) =>
    toAmount(a.deferred_disallowed) - toAmount(b.deferred_disallowed) ||
    toAmount(a.permanently_disallowed) - toAmount(b.permanently_disallowed) ||
    a.symbol.localeCompare(b.symbol),
  permanent: (a, b) =>
    toAmount(a.permanently_disallowed) - toAmount(b.permanently_disallowed) ||
    a.symbol.localeCompare(b.symbol),
};

/**
 * Whether a symbol carries a loss sale that has not yet been disallowed while its §1091 window is
 * still open -- the case the backend's own contract calls out as the one where the reader's next
 * action still changes the tax outcome: the loss is real, nothing has been added back yet, and a
 * repurchase before the window closes is what creates the wash sale. `sales` carries one row per
 * loss sale, not per triggered event, so `event_count` can be smaller than `sales.length` and a
 * row's own `disallowed_loss` can legitimately be `"0.00"` -- that is not an empty or uninteresting
 * row, it is the live one.
 *
 * When sale-level detail has not been expanded (`sales` is empty -- see `WashSaleTrackerSymbol`'s
 * own docstring in `@/api/washsales`), this falls back to the coarser symbol-level signal: an open
 * window with nothing disallowed at all yet on this symbol, deferred or permanent.
 */
function hasUntriggeredLoss(symbol: WashSaleTrackerSymbol): boolean {
  if (!symbol.window_is_open) return false;
  if (symbol.sales.length > 0)
    return symbol.sales.some((s) => isZero(s.disallowed_loss));
  return (
    isZero(symbol.deferred_disallowed) && isZero(symbol.permanently_disallowed)
  );
}

/**
 * The Disposals tab of the Tax page, filtered to one symbol and one tax year.
 *
 * Tax reads `?tab=` today and ignores `?symbol=`/`?year=` -- the link still lands the reader on the
 * right tab, and the two extra params are the contract for the filter that page is growing. A link
 * that is right about three quarters of its destination is worth more than no link at all, which is
 * what this page had: zero outbound links of any kind.
 */
function disposalsHref(symbol: string, year: number): string {
  const params = new URLSearchParams({
    tab: "disposals",
    year: String(year),
    symbol,
  });
  return `/tax?${params.toString()}`;
}

/**
 * US tax: which §1091 wash-sale windows are still open, and when each closes -- everything the
 * former `/wash-sales` page rendered *except* its own `<h1>`.
 *
 * Split out from the default export below because this surface no longer owns a top-level nav
 * destination: it lives inside the Tax page's Wash sales tab (`Tax.tsx`), which already carries the
 * page's one `<h1>`. A second `<h1>` inside another page's body is both a document-outline error and
 * the thing that makes an embedded surface read as a page that got pasted in. The default export
 * keeps the heading for any remaining standalone use.
 */
export function WashSalesSection() {
  const { t } = useT();
  const [tracker, setTracker] = useState<WashSaleTracker | null>(null);
  const [phase, setPhase] = useState<"loading" | "loaded" | "empty" | "error">(
    "loading",
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    setError(null);
    washSalesApi
      .tracker()
      .then((t) => {
        if (cancelled) return;
        setTracker(t);
        setPhase(t.symbols.length === 0 ? "empty" : "loaded");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        // A 404 means "no ledger yet" ONLY when the API says so. An unknown *route* also 404s
        // -- FastAPI answers `Not Found` -- and treating that as "empty" would render "no wash
        // sales" at a reader whose exposure is simply unmeasured. That is a false all-clear on a
        // tax figure, the same defect class as the wash-sale panel that once reported symbols
        // safe while their windows were open. An unmeasured risk must never look like no risk,
        // so anything else falls through to the error state.
        if (
          e instanceof ApiRequestError &&
          e.status === 404 &&
          /no ledger/i.test(e.message)
        ) {
          setTracker(null);
          setPhase("empty");
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
    // `t` translates in whichever language is active when the catch branch runs -- same accepted
    // limitation as `Tax.tsx`'s own report-fetch effect; see its docstring note.
  }, []);

  return (
    <>
      <p className="subtitle">{t("tax.washSales.subtitle")}</p>

      {/* Byte-for-byte the Tax page's own `Disclaimer` (see `Tax.tsx`): the same pill, the same
          title, the same body key. This page used to carry the title with no pill at all and a
          near-copy of the body that differed in one word ("Detection replays…" for "The engine
          replays…"). "Not tax advice" is one of the things COPY-STYLE.md rule 6 says may be
          shortened but never hidden or varied, and a second wording of the same sentence is how a
          disclaimer starts drifting from the one that was reviewed. */}
      <div className="panel disclaimer" role="note">
        <StatusPill tone="warn" label={t("ui.pill.notAdvice")} />{" "}
        <strong>{t("tax.disclaimer.title")}</strong> {t("tax.disclaimer.body")}
      </div>

      {/* A skeleton, not a one-line "Loading…": this fetch replays the whole connected ledger and
          is slow on a large book, so the panel would otherwise sit collapsed to a
          single line for many seconds and then snap open to four tiles and a symbol list. Four
          `tiles` blocks stand in for the headline grid -- see `Skeleton.tsx` for why the silhouette
          matters more than the word. The accessible live message is the same string that used to be
          the whole state, so nothing a screen reader heard before is lost. */}
      {phase === "loading" && (
        <div className="panel">
          <Skeleton variant="tiles" rows={4} what={t("tax.washSales.title")} />
        </div>
      )}

      {phase === "error" && (
        <div className="panel">
          <div className="placeholder">{error}</div>
        </div>
      )}

      {phase === "empty" && <EmptyState />}

      {/* `!= null`, not `!== null`: `tracker` starts `null` before the fetch resolves and this
          branch is gated on `phase === "loaded"` regardless, but a loose check here matches the
          rest of this codebase's rule for a fetched object that predates a field -- see
          `WashSaleSymbolPanel` in `Tax.tsx` and `formatMoneyOrDash` in `api/portfolio.ts`. A
          strict `!==` would let a backend response missing this object through as `undefined`
          and crash the page instead of falling back to the loading/error states above. */}
      {phase === "loaded" && tracker != null && (
        <WashSalesContent tracker={tracker} />
      )}
    </>
  );
}

/**
 * The standalone page form: the heading plus the section above.
 *
 * `/wash-sales` now redirects to `/tax?tab=wash` (see `App.tsx`), so nothing in the running app
 * routes here any more. Kept as the default export rather than deleted because the section is the
 * part that moved, not the page's identity -- a caller that genuinely wants this surface on its own
 * (a future route, a standalone print view) should get the heading with it rather than have to
 * reinvent which `<h1>` belongs on top.
 */
export default function WashSales() {
  const { t } = useT();
  return (
    <>
      <h1>{t("tax.washSales.title")}</h1>
      <WashSalesSection />
    </>
  );
}

function EmptyState() {
  const { t } = useT();
  return (
    <div className="panel">
      <div className="placeholder">{t("tax.washSales.emptyState")}</div>
    </div>
  );
}

function WashSalesContent({ tracker }: { tracker: WashSaleTracker }) {
  const { t } = useT();
  const [scopeYear, setScopeYear] = useState<ScopeYear>(null);
  const years = useMemo(() => washSaleYears(tracker), [tracker]);

  // The symbols the three sections below draw from. Whole-ledger by default; narrowed to one year
  // of loss sales when the switch says so -- lists only, never the tiles. See `symbolsInYear`'s
  // own docstring in `@/api/washsales` for why no money figure is recomputed here.
  const scopedSymbols = useMemo(
    () => (scopeYear === null ? tracker.symbols : symbolsInYear(tracker, scopeYear)),
    [tracker, scopeYear],
  );

  const openSymbols = useMemo(
    () =>
      scopedSymbols
        .filter((s) => s.window_is_open)
        .slice()
        .sort((a, b) => a.days_until_safe - b.days_until_safe),
    [scopedSymbols],
  );
  const closedSymbols = useMemo(
    () => scopedSymbols.filter((s) => !s.window_is_open),
    [scopedSymbols],
  );
  const closedStillRiding = useMemo(
    () => closedSymbols.filter((s) => !isZero(s.deferred_disallowed)),
    [closedSymbols],
  );
  const closedSettled = closedSymbols.length - closedStillRiding.length;

  return (
    <>
      <ScopeLine tracker={tracker} />
      <HeadlineTiles tracker={tracker} />
      <ScopeSwitch years={years} scopeYear={scopeYear} onChange={setScopeYear} />
      {scopeYear !== null && scopedSymbols.length === 0 ? (
        <div className="panel">
          <div className="placeholder">
            {t("tax.washSales.scope.emptyYear", { year: scopeYear })}
          </div>
        </div>
      ) : (
        <>
          <OpenWindowsSection symbols={openSymbols} scopeYear={scopeYear} />
          <ClosedWindowsSection
            symbols={closedStillRiding}
            settledCount={closedSettled}
            scopeYear={scopeYear}
          />
        </>
      )}

      <p className="muted wsale-footer">{t("tax.washSales.footer")}</p>
    </>
  );
}

/**
 * All years, or one year of loss sales. A segmented control rather than a `<select>`: there are a
 * handful of options at most, and the point of the control is that the *alternative* is visible --
 * a reader looking at a year-filtered list must be able to see, without opening anything, that a
 * wider scope exists and that they are not looking at everything.
 *
 * Rendered as a radio group, not a row of buttons: the state is one-of-N, arrow keys move between
 * the options, and a screen reader announces "2 of 4" rather than four unrelated pressed buttons.
 *
 * Renders nothing when the ledger has no years to offer (an empty or single-symbol tracker with no
 * parseable sale date) -- a control whose only option is the one already active is furniture.
 */
function ScopeSwitch({
  years,
  scopeYear,
  onChange,
}: {
  years: number[];
  scopeYear: ScopeYear;
  onChange: (next: ScopeYear) => void;
}) {
  const { t } = useT();
  if (years.length === 0) return null;

  const options: { key: string; value: ScopeYear; label: string }[] = [
    { key: "all", value: null, label: t("tax.washSales.scope.allYears") },
    ...years.map((year) => ({
      key: String(year),
      value: year as ScopeYear,
      label: t("tax.washSales.scope.year", { year }),
    })),
  ];

  return (
    <div className="panel wsale-scope-panel">
      <div
        className="wsale-scope-switch"
        role="radiogroup"
        aria-label={t("tax.washSales.scope.label")}
      >
        <span className="wsale-scope-switch-label">{t("tax.washSales.scope.label")}</span>
        {options.map((option) => {
          const active = option.value === scopeYear;
          return (
            <button
              key={option.key}
              type="button"
              role="radio"
              aria-checked={active}
              className={`wsale-scope-option${active ? " is-active" : ""}`}
              onClick={() => onChange(option.value)}
            >
              {option.label}
            </button>
          );
        })}
      </div>
      {/* Both notes render only in year scope, and they are two different facts kept in two
          sentences on purpose: where the filter ran (here, not on the server) and what it did NOT
          touch (the tiles above). DEFINITIONS.md standing rule 6 -- one scope per sentence. */}
      {scopeYear !== null && (
        <>
          <p className="muted wsale-scope-note">{t("tax.washSales.scope.clientSide")}</p>
          <p className="muted wsale-scope-note">
            {t("tax.washSales.scope.tilesStayAllYears", { year: scopeYear })}
          </p>
        </>
      )}
    </div>
  );
}

/**
 * States the scope of this whole page in one place: whole-ledger and year-independent, unlike the
 * Tax page's own wash-sale figures, and computed against today's date rather than a fixed report
 * date. Mirrors the scope line `WashSaleSymbolPanel` carries in `Tax.tsx` for the same reason --
 * the two pages' totals are expected to differ, and a reader comparing them needs to know why
 * rather than conclude one of them is wrong.
 */
function ScopeLine({ tracker }: { tracker: WashSaleTracker }) {
  return (
    <div className="panel">
      <p className="subtitle wsale-scope-line">
        <Trans
          k="tax.washSales.scopeLine"
          values={{ asOf: <strong>{tracker.as_of}</strong> }}
        />
      </p>
    </div>
  );
}

function HeadlineTiles({ tracker }: { tracker: WashSaleTracker }) {
  const { t } = useT();
  const hasPermanent = !isZero(tracker.total_permanently_disallowed);
  return (
    <>
      <div className="panel">
        <div className="tile-grid">
          <StatTile
            label={t("tax.wsale.tile.deferred")}
            value={formatMoney(tracker.total_deferred)}
            hint={t("tax.wsale.tile.deferredHint")}
          />
          {/* `tax.wsale.tile.permanentlyDisallowed`, not the Tax page's `tax.tile.*` label: that
              one is one tax year, this is the whole connected ledger. Same figure, different
              window, and the two were sharing a label that named neither. */}
          <StatTile
            label={t("tax.wsale.tile.permanentlyDisallowed")}
            value={formatMoney(tracker.total_permanently_disallowed)}
            hint={t("tax.tile.permanentlyDisallowedHint")}
            variant="danger"
          />
          <StatTile
            label={t("tax.wsale.tile.openWindowSymbols")}
            value={String(tracker.open_window_count)}
          />
          <StatTile
            label={t("tax.wsale.tile.symbolsTracked")}
            value={String(tracker.symbol_count)}
          />
        </div>
      </div>

      {hasPermanent && (
        <div className="panel callout callout-danger">
          <strong>{t("tax.wsale.permanentCallout.lead")}</strong>{" "}
          {t("tax.wsale.permanentCallout.rest", {
            amount: formatMoney(tracker.total_permanently_disallowed),
          })}
        </div>
      )}
    </>
  );
}

/**
 * The headline of the page: every symbol still inside its §1091 window, as a sortable table.
 * Defaults to soonest-closing first (`days` ascending) so a window closing in three days is never
 * buried beneath one closing in a month -- the urgency order is the point of this section, not an
 * incidental sort. The reader can re-sort by any column: symbol, days remaining, safe-from date, or
 * either money figure, which answers the "which open symbol carries the most" question the fixed
 * urgency order cannot. Deferred and permanent stay in separate columns and are never summed.
 *
 * Each row expands in place to the same per-sale drill-down the cards used to hold, so no sale-level
 * detail is lost by moving from cards to a table.
 */
function OpenWindowsSection({
  symbols,
  scopeYear,
}: {
  symbols: WashSaleTrackerSymbol[];
  scopeYear: ScopeYear;
}) {
  const { t } = useT();
  const { sort, toggle: toggleSort } = useTableSort<OpenSortKey>(
    "days",
    OPEN_DEFAULT_DIRS,
  );
  const sorted = useMemo(
    () => sortRows(symbols, sort, OPEN_SORT_COMPARE),
    [symbols, sort],
  );

  // Collapsed by default -- 46 open-window symbols expanded at once would bury the urgency
  // ordering this section exists for under a wall of sale-level detail.
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const toggleRow = useCallback((sym: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(sym)) next.delete(sym);
      else next.add(sym);
      return next;
    });
  }, []);

  const sortTitle = (column: string) =>
    t("ui.table.sortBy", { column });

  return (
    <section className="panel">
      <h2>{t("tax.wsale.openWindows.title")}</h2>
      <p className="subtitle">{t("tax.wsale.openWindows.subtitle")}</p>
      {symbols.length === 0 ? (
        <div className="placeholder">{t("tax.wsale.openWindows.empty")}</div>
      ) : (
        <ScrollRegion size="md" label={t("tax.wsale.openWindows.title")}>
          <div className="table-wrap">
            <table className="data-table wsale-open-table">
              <thead>
                <tr>
                  <SortHeader
                    label={t("common.symbol")}
                    sortKey="symbol"
                    sort={sort}
                    onSort={toggleSort}
                    title={sortTitle(t("common.symbol"))}
                  />
                  <SortHeader
                    label={t("tax.wsale.openTable.daysLeftHeader")}
                    sortKey="days"
                    sort={sort}
                    onSort={toggleSort}
                    title={sortTitle(t("tax.wsale.openTable.daysLeftHeader"))}
                  />
                  <SortHeader
                    label={t("tax.wsale.openTable.safeFromHeader")}
                    sortKey="safe"
                    sort={sort}
                    onSort={toggleSort}
                    title={sortTitle(t("tax.wsale.openTable.safeFromHeader"))}
                  />
                  <SortHeader
                    label={t("tax.header.deferred")}
                    sortKey="deferred"
                    sort={sort}
                    onSort={toggleSort}
                    numeric
                    title={sortTitle(t("tax.header.deferred"))}
                  />
                  <SortHeader
                    label={t("tax.wsale.figureLabel.permanent")}
                    sortKey="permanent"
                    sort={sort}
                    onSort={toggleSort}
                    numeric
                    title={sortTitle(t("tax.wsale.figureLabel.permanent"))}
                  />
                </tr>
              </thead>
              <tbody>
                {sorted.map((s) => (
                  <OpenWindowRow
                    key={s.symbol}
                    symbol={s}
                    tier={urgencyTier(s.days_until_safe)}
                    expanded={expanded.has(s.symbol)}
                    onToggle={toggleRow}
                    scopeYear={scopeYear}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </ScrollRegion>
      )}
    </section>
  );
}

/**
 * One open-window symbol as a table row, plus (when expanded) a second full-width row holding its
 * per-sale drill-down. The urgency tier keeps the card list's left-accent and coloured day badge --
 * "3 days" must not read like "28 days" -- and the countdown-bar markup is carried over unchanged
 * from the former card summary.
 */
function OpenWindowRow({
  symbol,
  tier,
  expanded,
  onToggle,
  scopeYear,
}: {
  symbol: WashSaleTrackerSymbol;
  tier: UrgencyTier;
  expanded: boolean;
  onToggle: (symbol: string) => void;
  scopeYear: ScopeYear;
}) {
  const { t } = useT();
  const fillPct = countdownFillPct(symbol.days_until_safe);
  const hasPermanent = !isZero(symbol.permanently_disallowed);
  const untriggered = hasUntriggeredLoss(symbol);
  const detailId = `wsale-open-detail-${symbol.symbol}`;
  return (
    <>
      <tr
        className={`wsale-open-row wsale-tier-${tier}${untriggered ? " wsale-card-live" : ""}`}
      >
        <td className="wsale-open-symbol-cell">
          <button
            type="button"
            className="wsale-open-toggle"
            aria-expanded={expanded}
            aria-controls={detailId}
            onClick={() => onToggle(symbol.symbol)}
          >
            <span className="wsale-open-caret" aria-hidden="true">
              {expanded ? "▾" : "▸"}
            </span>
            <span className="wsale-symbol-name">{symbol.symbol}</span>
          </button>
          <SeeInDisposals symbol={symbol} scopeYear={scopeYear} />
          <Link
            className="wsale-symbol-page-link"
            to={`/symbol/${encodeURIComponent(symbol.symbol)}`}
            title={t("tax.washSales.openSymbolPage", { symbol: symbol.symbol })}
            aria-label={symbol.symbol}
          >
            ↗
          </Link>
          {untriggered && (
            <span
              className="badge wsale-live-warn"
              title={t("tax.wsale.symbolCard.notYetTriggeredTitle")}
            >
              {t("tax.wsale.symbolCard.notYetTriggered")}
            </span>
          )}
        </td>
        <td className="wsale-open-days-cell">
          <span
            className="wsale-countdown"
            title={t("tax.window.openTitle", { date: symbol.last_sale_date })}
          >
            <span className="wsale-countdown-track">
              <span
                className="wsale-countdown-fill"
                style={{ width: `${fillPct}%` }}
              />
            </span>
            <span className={`badge wsale-days-badge wsale-tier-${tier}`}>
              {t(
                symbol.days_until_safe === 1
                  ? "tax.wsale.daysLeft_one"
                  : "tax.wsale.daysLeft_other",
                { days: symbol.days_until_safe },
              )}
            </span>
          </span>
        </td>
        <td className="muted wsale-open-safe-cell">
          {symbol.repurchase_safe_on}
        </td>
        <td className="num">{formatMoney(symbol.deferred_disallowed)}</td>
        <td className="num wsale-figure-permanent">
          {hasPermanent ? formatMoney(symbol.permanently_disallowed) : "—"}
        </td>
      </tr>
      {expanded && (
        <tr className="wsale-open-detail-row" id={detailId}>
          <td colSpan={5}>
            <SymbolDrilldown symbol={symbol} scopeYear={scopeYear} />
          </td>
        </tr>
      )}
    </>
  );
}

/**
 * The per-row link out to the disposal behind it: this symbol's own Disposals rows on the Tax page.
 *
 * The tax year is the one being viewed when the scope switch names one, and otherwise the year of
 * the symbol's **last** loss sale -- the disposal a reader looking at an open window is asking
 * about. Never today's year: a window can be open in January over a sale made the previous
 * December, and pointing that link at a year with no such disposal is worse than pointing it at the
 * right one.
 */
function SeeInDisposals({
  symbol,
  scopeYear,
}: {
  symbol: WashSaleTrackerSymbol;
  scopeYear: ScopeYear;
}) {
  const { t } = useT();
  const year = scopeYear ?? yearOf(symbol.last_sale_date);
  if (year === null) return null;
  return (
    <Link
      className="wsale-disposals-link"
      to={disposalsHref(symbol.symbol, year)}
      title={t("tax.washSales.seeDisposalsTitle", { symbol: symbol.symbol, year })}
    >
      {t("tax.washSales.seeDisposals")}
    </Link>
  );
}

/**
 * Symbols whose window has already closed, but whose deferred loss is still riding on a
 * replacement lot's basis rather than having come back on a later sale. Folded away by default:
 * these are not actionable today the way an open window is, and 81 symbols is unreadable rendered
 * flat.
 *
 * Symbols whose window is closed *and* carry no outstanding deferred loss (fully recovered, or
 * only ever permanently disallowed) are deliberately excluded from the list rather than silently
 * dropped -- `settledCount` names how many and why, at the point of the total, rather than in a
 * footnote.
 */
function ClosedWindowsSection({
  symbols,
  settledCount,
  scopeYear,
}: {
  symbols: WashSaleTrackerSymbol[];
  settledCount: number;
  scopeYear: ScopeYear;
}) {
  const { t } = useT();
  if (symbols.length === 0 && settledCount === 0) return null;

  // Shared between the visible `<summary>` and the scroll region's accessible name below, so the
  // two never drift apart -- the label a screen-reader user hears for the bounded list is exactly
  // the sentence a sighted user already read to expand it.
  const closedSummaryText = t(
    symbols.length === 1
      ? "tax.wsale.closed.summary_one"
      : "tax.wsale.closed.summary_other",
    { count: symbols.length },
  );

  return (
    <details className="panel wsale-closed-section">
      <summary>{closedSummaryText}</summary>
      <p className="muted wsale-closed-note">
        {t("tax.wsale.closed.note")}
        {settledCount > 0 && (
          <>
            {" "}
            {t(
              settledCount === 1
                ? "tax.wsale.closed.otherSettled_one"
                : "tax.wsale.closed.otherSettled_other",
              { count: settledCount },
            )}
          </>
        )}
      </p>
      {symbols.length > 0 && (
        <ScrollRegion size="md" label={closedSummaryText}>
          <ul className="wsale-closed-list">
            {symbols.map((s) => (
              <li key={s.symbol}>
                <details className="wsale-symbol-card wsale-tier-closed">
                  <summary className="wsale-symbol-summary">
                    <span className="wsale-symbol-name">
                      <Link to={`/symbol/${encodeURIComponent(s.symbol)}`}>{s.symbol}</Link>
                    </span>
                    <SeeInDisposals symbol={s} scopeYear={scopeYear} />
                    <span
                      className="badge wsale-window-safe"
                      title={t("tax.window.closedTitle", {
                        date: s.last_sale_date,
                      })}
                    >
                      {t("tax.wsale.closed.windowClosedBadge", {
                        date: s.repurchase_safe_on,
                      })}
                    </span>
                    <span className="wsale-symbol-figures">
                      <span className="wsale-figure">
                        <span className="wsale-figure-label">
                          {t("tax.header.deferred")}
                        </span>{" "}
                        {formatMoney(s.deferred_disallowed)}
                      </span>
                      {!isZero(s.permanently_disallowed) && (
                        <span className="wsale-figure wsale-figure-permanent">
                          <span className="wsale-figure-label">
                            {t("tax.wsale.figureLabel.permanent")}
                          </span>{" "}
                          {formatMoney(s.permanently_disallowed)}
                        </span>
                      )}
                    </span>
                  </summary>
                  <SymbolDrilldown symbol={s} scopeYear={scopeYear} />
                </details>
              </li>
            ))}
          </ul>
        </ScrollRegion>
      )}
    </details>
  );
}

/**
 * A symbol's individual sales, revealed by expanding its card. Renders nothing but a note when
 * `sales` is empty -- per `@/api/washsales`'s docstring, that means the backend has an aggregate
 * entry but has not (yet) expanded its sale-level detail, and inferring a fabricated row from the
 * rollup figures would misattribute an account and a date neither one actually carries.
 */
function SymbolDrilldown({
  symbol,
  scopeYear,
}: {
  symbol: WashSaleTrackerSymbol;
  scopeYear: ScopeYear;
}) {
  const { t } = useT();
  const lossPlural = symbol.loss_sale_count === 1 ? "1" : "n";
  const eventPlural = symbol.event_count === 1 ? "1" : "n";
  const metaKey =
    lossPlural === "1"
      ? eventPlural === "1"
        ? ("tax.wsale.drilldown.meta_1_1" as const)
        : ("tax.wsale.drilldown.meta_1_n" as const)
      : eventPlural === "1"
        ? ("tax.wsale.drilldown.meta_n_1" as const)
        : ("tax.wsale.drilldown.meta_n_n" as const);
  return (
    <div className="wsale-drilldown">
      <p className="muted wsale-drilldown-meta">
        {t(metaKey, {
          lossCount: symbol.loss_sale_count,
          eventCount: symbol.event_count,
          accounts: symbol.accounts.join(", ") || "—",
          first: symbol.first_sale_date,
          last: symbol.last_sale_date,
        })}
      </p>
      {symbol.sales.length === 0 ? (
        <div className="placeholder">{t("tax.wsale.drilldown.noDetail")}</div>
      ) : (
        // A horizontally scrolling region has to be reachable and named: nine columns overflow at
        // 1440px, and without `tabIndex` a keyboard user cannot scroll it at all.
        <div
          className="table-wrap"
          tabIndex={0}
          role="region"
          aria-label={t("tax.wsale.drilldown.tableAriaLabel", { symbol: symbol.symbol })}
        >
          <table className="data-table wsale-sales-table">
            {/* Visually hidden, and it names the scope as well as the table: a screen reader
                reaching this table has passed through a scroll region inside a <details> inside a
                list, and the one thing the cells themselves cannot say is which window they cover.
                `.visually-hidden` is the app-wide utility from `styles.css`. */}
            <caption className="visually-hidden">
              {scopeYear === null
                ? t("tax.caption.wsaleSales", {
                    symbol: symbol.symbol,
                    count: symbol.sales.length,
                  })
                : t("tax.caption.wsaleSalesYear", {
                    symbol: symbol.symbol,
                    year: scopeYear,
                    count: symbol.sales.length,
                  })}
            </caption>
            <thead>
              <tr>
                <th scope="col">{t("tax.header.sold")}</th>
                <th scope="col">{t("tax.header.account")}</th>
                <th scope="col" className="num">
                  {t("tax.header.qtySold")}
                </th>
                <th scope="col" className="num">
                  {t("tax.header.qtyReplaced")}
                </th>
                <th scope="col" className="num">
                  {t("tax.header.loss")}
                </th>
                <th scope="col" className="num">
                  {t("tax.header.disallowed")}
                </th>
                <th scope="col">{t("tax.header.treatment")}</th>
                <th scope="col">{t("tax.header.replacementAccounts")}</th>
                <th scope="col">{t("tax.header.windowCloses")}</th>
              </tr>
            </thead>
            <tbody>
              {symbol.sales.map((sale) => (
                // Keyed on disposal *and* treatment, not `disposal_id` alone: `sales` is
                // event-grained, so one disposal whose replacement spanned a taxable account and an
                // IRA produces two rows sharing an id -- one deferred, one permanently disallowed.
                // Keying on the id alone makes React treat them as the same row and render only
                // one, and the one that disappears is as likely to be the permanent loss, which is
                // the figure a reader can do nothing about and most needs to see. Occurs in
                // real ledgers.
                <SaleRow
                  key={`${sale.disposal_id}:${sale.permanently_disallowed ? "perm" : "deferred"}`}
                  sale={sale}
                  windowIsOpen={symbol.window_is_open}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/**
 * `sales` is one row per loss sale, not per triggered wash-sale event -- a row can legitimately
 * carry `disallowed_loss: "0.00"` when the loss has not (yet) been re-triggered by a replacement
 * purchase. That is a real zero (rendered as `$0.00`, not `—` -- this is not the withheld-figure
 * case), and while the sale's own window is still open it is the single most actionable row on the
 * page: the loss is realized, nothing is disallowed yet, and a repurchase before `window_closes_on`
 * is what would create the wash sale. It must not read as empty or uninteresting, so it gets its
 * own highlighted row treatment and its own "Treatment" copy rather than falling into the
 * deferred/permanent badges below, both of which would misstate a disallowance that has not
 * happened.
 *
 * Once the row's own window has closed with nothing disallowed, that risk is over -- rendered as a
 * quiet, unhighlighted note rather than a warning that no longer applies.
 */
function SaleRow({
  sale,
  windowIsOpen,
}: {
  sale: WashSaleTrackerSale;
  windowIsOpen: boolean;
}) {
  const { t } = useT();
  const disallowedIsZero = isZero(sale.disallowed_loss);
  const notYetTriggered = disallowedIsZero && windowIsOpen;
  return (
    <tr className={notYetTriggered ? "wsale-sale-row-live" : undefined}>
      <td>{sale.sale_date}</td>
      <td className="muted">{sale.account_id}</td>
      <td className="num">{sale.quantity_sold}</td>
      <td className="num">{sale.quantity_replaced}</td>
      <td className="num">{formatMoney(sale.loss_amount)}</td>
      <td className="num">{formatMoney(sale.disallowed_loss)}</td>
      <td>
        {notYetTriggered ? (
          <span
            className="badge wsale-live-warn"
            title={t("tax.wsale.saleRow.notYetTriggeredTitle")}
          >
            {t("tax.wsale.saleRow.notYetTriggered")}
          </span>
        ) : sale.permanently_disallowed ? (
          <span className="badge permanent">{t("tax.badge.permanent")}</span>
        ) : disallowedIsZero ? (
          <span className="muted">{t("tax.wsale.saleRow.noWashSale")}</span>
        ) : (
          <span className="badge deferred">{t("tax.badge.deferred")}</span>
        )}
      </td>
      <td className="muted">
        {sale.replacement_account_ids.join(", ") || "—"}
      </td>
      <td>{sale.window_closes_on}</td>
    </tr>
  );
}
