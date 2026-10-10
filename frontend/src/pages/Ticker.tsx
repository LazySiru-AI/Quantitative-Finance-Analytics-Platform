import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import InstitutionalHolders from "@/components/InstitutionalHolders";

import {
  formatPercent,
  formatPrice,
  formatVolume,
  INTERVALS,
  marketApi,
  type Coverage,
  type Fundamentals,
  type Interval,
  type MarketWarning,
  type Profile,
  type Quote,
  type TickerSummary,
} from "@/api/market";
import Chart from "@/components/Chart";
import Collapsible from "@/components/Collapsible";
import DecisionTable from "@/components/DecisionTable";
import IndicatorPicker from "@/components/IndicatorPicker";
import NewsPanel from "@/components/NewsPanel";
import PanelBoundary from "@/components/PanelBoundary";
import RuleEditor from "@/components/RuleEditor";
import { ScrollPanel } from "@/components/ScrollPanel";
import StatusPill, { type PillTone } from "@/components/StatusPill";
import TimeframeGrid from "@/components/TimeframeGrid";
import type { Overlay } from "@/components/overlays";
import { describeError, useChartSeries, type Phase } from "@/hooks/useChartSeries";
import { useTickerNews } from "@/hooks/useTickerNews";
import { type Translator, useT } from "@/i18n";

// Exported so `Symbol.tsx` (the merged Ticker+Report page) can reuse the same example-symbol row
// in its own empty state rather than hand-copying this list.
export const EXAMPLE_SYMBOLS = ["QQQ", "SOXL", "NVDA", "SPY"];
const NO_OVERLAYS: Overlay[] = [];

/** One chart at a chosen timeframe, or all four side by side. */
type ChartView = "single" | "grid";

/** Per-holding research report: profile, fundamentals, 4-timeframe candles, decision table. */
export default function Ticker() {
  const { symbol: rawSymbol } = useParams<{ symbol: string }>();
  const symbol = rawSymbol ? rawSymbol.toUpperCase() : null;
  const navigate = useNavigate();

  const [symbolInput, setSymbolInput] = useState(symbol ?? "");
  useEffect(() => {
    setSymbolInput(symbol ?? "");
  }, [symbol]);

  const submitSymbol = useCallback(
    (value: string) => {
      const next = value.trim().toUpperCase();
      if (next.length === 0) return;
      navigate(`/symbol/${encodeURIComponent(next)}`);
    },
    [navigate],
  );

  if (!symbol) {
    return <TickerPrompt value={symbolInput} onChange={setSymbolInput} onSubmit={submitSymbol} />;
  }

  // Remounting on symbol change resets every piece of per-symbol state (bars, interval,
  // indicators) instead of trying to reconcile it -- a stale QQQ chart flashing while NVDA data
  // loads in is worse than a brief remount.
  return (
    <TickerDetail
      key={symbol}
      symbol={symbol}
      symbolInput={symbolInput}
      onSymbolInputChange={setSymbolInput}
      onSubmitSymbol={submitSymbol}
    />
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function TickerPrompt({
  value,
  onChange,
  onSubmit,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
}) {
  const { t } = useT();
  return (
    <>
      <h1>{t("ticker.title")}</h1>
      <p className="subtitle">{t("ticker.subtitle")}</p>

      <div className="panel ticker-empty">
        <div className="prompt-line">lookup --symbol=_</div>
        <form
          className="symbol-form"
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit(value);
          }}
        >
          <input
            className="symbol-input"
            value={value}
            onChange={(e) => onChange(e.target.value.toUpperCase())}
            placeholder={t("ticker.symbolForm.placeholder")}
            aria-label={t("ticker.symbolForm.ariaLabel")}
            autoFocus
            spellCheck={false}
          />
          <button type="submit" className="symbol-submit">
            {t("ticker.symbolForm.submit")}
          </button>
        </form>
        <div className="placeholder">{t("ticker.empty.tryThese")}</div>
        <div className="symbol-examples">
          {EXAMPLE_SYMBOLS.map((s) => (
            <button key={s} type="button" className="symbol-example" onClick={() => onSubmit(s)}>
              {s}
            </button>
          ))}
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Loaded ticker
// ---------------------------------------------------------------------------

function TickerDetail({
  symbol,
  symbolInput,
  onSymbolInputChange,
  onSubmitSymbol,
}: {
  symbol: string;
  symbolInput: string;
  onSymbolInputChange: (value: string) => void;
  onSubmitSymbol: (value: string) => void;
}) {
  const { t } = useT();

  return (
    <>
      <h1>{symbol}</h1>
      <p className="subtitle">{t("ticker.subtitle")}</p>

      <div className="panel">
        <form
          className="symbol-form"
          onSubmit={(e) => {
            e.preventDefault();
            onSubmitSymbol(symbolInput);
          }}
        >
          <input
            className="symbol-input"
            value={symbolInput}
            onChange={(e) => onSymbolInputChange(e.target.value.toUpperCase())}
            aria-label={t("ticker.symbolForm.ariaLabel")}
            spellCheck={false}
          />
          <button type="submit" className="symbol-submit">
            {t("ticker.symbolForm.submit")}
          </button>
        </form>
      </div>

      <TickerView symbol={symbol} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Reusable views -- extracted so `Symbol.tsx` (the merged Ticker+Report page, UX refactor 2.1) can
// mount any one of these behind its own tab rail without duplicating the fetching or rendering
// logic here. `TickerView` composes all four for this page's own use above; `Symbol.tsx` mounts
// the sub-views individually instead, one per tab, so switching tabs there costs exactly the one
// fetch the newly-active tab needs rather than the four this page's `TickerDetail` always paid at
// once.
//
// Only `TickerChartView` reads the ticker summary (profile/quote/coverage/fundamentals) -- the
// other three (`DecisionTable`, `NewsPanel` via `useTickerNews`, `InstitutionalHolders`) were
// already independently self-fetching components before this split, so pulling them out changes
// nothing about how or when they fetch, only that they can now be mounted alone.
//
// `TickerDecisionView` used to share its `interval` state with `TickerChartView`'s own timeframe
// picker (both were one component, `TickerDetail`, before this refactor). Splitting them apart
// means each is a self-contained `{symbol}`-only component, which is what lets `Symbol.tsx` mount
// either one alone -- so `TickerDecisionView` now carries its own timeframe picker rather than
// reaching into a sibling tab's state that, once they are two different tabs, may not even be
// mounted.
// ---------------------------------------------------------------------------

/** The full research body: header, warnings, chart, rule editor, coverage, fundamentals, the
 *  decision table, news and institutional holders -- everything `TickerDetail` used to inline. */
export function TickerView({ symbol }: { symbol: string }) {
  return (
    <>
      <TickerChartView symbol={symbol} />
      <TickerDecisionView symbol={symbol} />
      <TickerNewsView symbol={symbol} />
      <TickerHoldersView symbol={symbol} />
    </>
  );
}

/** Header, warnings, the chart (layout/timeframe/indicator controls included), the rule-expression
 *  tester, and the coverage/fundamentals tables -- everything that shares the one
 *  `marketApi.ticker` summary fetch and the one chart-bars fetch. */
export function TickerChartView({ symbol }: { symbol: string }) {
  const { t } = useT();
  const [summary, setSummary] = useState<TickerSummary | null>(null);
  const [summaryPhase, setSummaryPhase] = useState<Phase>("loading");
  const [summaryMessage, setSummaryMessage] = useState<string | null>(null);

  const [interval, setIntervalValue] = useState<Interval>("1d");
  const [view, setView] = useState<ChartView>("single");
  const [overlays, setOverlays] = useState<Overlay[]>(NO_OVERLAYS);

  const handleOverlayChange = useCallback((next: Overlay[]) => setOverlays(next), []);

  // In grid mode every timeframe fetches its own series, so this single-view fetch would be a
  // fifth, redundant request. Passing an empty overlay list keeps it to the bars call the coverage
  // panel needs and no indicator work at all.
  const single = useChartSeries(symbol, interval, view === "single" ? overlays : NO_OVERLAYS);

  useEffect(() => {
    let cancelled = false;
    setSummaryPhase("loading");
    setSummaryMessage(null);
    marketApi
      .ticker(symbol)
      .then((s) => {
        if (cancelled) return;
        setSummary(s);
        setSummaryPhase("loaded");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const d = describeError(e, t("ticker.notFound", { symbol }));
        setSummaryPhase(d.phase);
        setSummaryMessage(d.message);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  const mergedWarnings = useMemo<MarketWarning[]>(
    () => [...(summary?.warnings ?? []), ...single.warnings],
    [summary, single.warnings],
  );

  return (
    <>
      {summaryPhase === "loading" && (
        <div className="panel">
          <div className="placeholder">{t("ticker.loadingSymbol", { symbol })}</div>
        </div>
      )}
      {(summaryPhase === "notfound" || summaryPhase === "error") && (
        <div className="panel">
          <div className="placeholder">{summaryMessage}</div>
        </div>
      )}

      {summaryPhase === "loaded" && summary && (
        <PanelBoundary label={t("ticker.panel.header")}>
          <TickerHeader symbol={symbol} summary={summary} />
        </PanelBoundary>
      )}

      <PanelBoundary label={t("ticker.panel.warnings")}>
        <WarningsStrip warnings={mergedWarnings} />
      </PanelBoundary>

      <div className="panel chart-panel">
        <div className="chart-panel-head">
          <h2>{t("ticker.chart.heading")}</h2>
          <div className="chart-controls">
            <div className="view-tabs" role="tablist" aria-label={t("ticker.chart.layoutAriaLabel")}>
              <button
                type="button"
                role="tab"
                aria-selected={view === "single"}
                className={`timeframe-tab${view === "single" ? " active" : ""}`}
                onClick={() => setView("single")}
              >
                {t("ticker.chart.view.single")}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={view === "grid"}
                className={`timeframe-tab${view === "grid" ? " active" : ""}`}
                onClick={() => setView("grid")}
              >
                {t("ticker.chart.view.grid")}
              </button>
            </div>
            {view === "single" && (
              <div className="timeframe-tabs" role="tablist" aria-label={t("ticker.chart.timeframeAriaLabel")}>
                {INTERVALS.map((iv) => (
                  <button
                    key={iv}
                    type="button"
                    role="tab"
                    aria-selected={iv === interval}
                    className={`timeframe-tab${iv === interval ? " active" : ""}`}
                    onClick={() => setIntervalValue(iv)}
                  >
                    {iv}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {view === "single" && single.source && (
          <div className="ticker-meta chart-source">
            {t("ticker.chart.source", { source: single.source })}
          </div>
        )}

        {/* In grid mode nothing is disabled by interval -- each panel drops what it cannot
            compute and says so, rather than the picker hiding a control that three of the four
            timeframes could have used.

            Collapsed by default: the picker's own catalog grid renders one card per indicator
            (a dozen-plus today), and rendering that open by default pushed the chart itself --
            the thing a reader actually came here for -- most of a screen down. `defaultOpen`
            stays `false` even when overlays are already active, matching the disclosure-by-default
            convention `Collapsible`'s own docstring documents for this codebase; the active
            overlays remain visible on the chart itself either way. */}
        <Collapsible title={<h3 className="section-heading">{t("ticker.indicator.pickerHeading")}</h3>} defaultOpen={false}>
          <IndicatorPicker
            interval={view === "single" ? interval : null}
            onChange={handleOverlayChange}
          />
        </Collapsible>

        <PanelBoundary label={t("ticker.panel.chart")}>
          {view === "grid" ? (
            <TimeframeGrid symbol={symbol} overlays={overlays} />
          ) : (
            <>
              {single.barsPhase === "loading" && (
                <div className="placeholder">{t("ticker.chart.loadingBars", { interval })}</div>
              )}
              {(single.barsPhase === "notfound" || single.barsPhase === "error") && (
                <div className="placeholder">{single.barsMessage}</div>
              )}
              {single.barsPhase === "loaded" && single.bars.length === 0 && (
                <div className="placeholder">{t("ticker.chart.noBars", { interval, symbol })}</div>
              )}
              {single.barsPhase === "loaded" && single.bars.length > 0 && single.barsInterval && (
                // `single.barsInterval`, never the `interval` state above: on an interval change this
                // component re-renders with the new interval one render before the bars for it have
                // been fetched, and `Chart` reads intraday and daily timestamps differently -- 4h bars
                // labelled `1d` collapse to duplicate dates and crash the chart into its error
                // boundary. Pairing the bars with the interval they were fetched with makes that
                // mismatch unrepresentable rather than merely unlikely.
                //
                // `series`/`ts` are gated on `single.tsInterval === single.barsInterval` for the same
                // reason, one level over: the indicators request and the bars request race
                // independently, and the indicators effect has no `barsPhase` guard of its own. A user
                // switching 1d -> 4h with overlays active can have the indicators request resolve
                // first, handing this component fresh 4h `ts`/`series` while `barsInterval` is still
                // `"1d"` for one or more renders -- exactly the mismatch the bars pairing above exists
                // to prevent, just on the other half of the pair. Withholding `series`/`ts` until the
                // two intervals agree means the chart draws candles-only for that one render instead of
                // crashing on `buildLinePoints` slicing intraday timestamps to duplicate business days.
                <Chart
                  bars={single.bars}
                  series={single.tsInterval === single.barsInterval ? single.series : []}
                  ts={single.tsInterval === single.barsInterval ? single.ts : []}
                  colors={single.colors}
                  interval={single.barsInterval}
                />
              )}
              {single.indicatorsPhase === "loading" && (
                <div className="placeholder">{t("ticker.chart.loadingIndicators")}</div>
              )}
              {(single.indicatorsPhase === "notfound" || single.indicatorsPhase === "error") && (
                <div className="placeholder">{single.indicatorsMessage}</div>
              )}
            </>
          )}
        </PanelBoundary>
      </div>

      <div className="panel">
        <h2>{t("ticker.ruleEditor.heading")}</h2>
        <PanelBoundary label={t("ticker.panel.ruleEditor")}>
          <RuleEditor />
        </PanelBoundary>
      </div>

      {summaryPhase === "loaded" && summary && (
        <>
          <PanelBoundary label={t("ticker.panel.coverage")}>
            <CoveragePanel coverage={summary.coverage} />
          </PanelBoundary>
          <PanelBoundary label={t("ticker.panel.fundamentals")}>
            <FundamentalsPanel fundamentals={summary.fundamentals} />
          </PanelBoundary>
        </>
      )}
    </>
  );
}

/** The decision table, with its own timeframe picker -- see the section docstring above for why
 *  this no longer shares `TickerChartView`'s interval state. */
export function TickerDecisionView({ symbol }: { symbol: string }) {
  const { t } = useT();
  const [interval, setIntervalValue] = useState<Interval>("1d");

  return (
    <>
      <div className="panel">
        <div className="timeframe-tabs" role="tablist" aria-label={t("ticker.chart.timeframeAriaLabel")}>
          {INTERVALS.map((iv) => (
            <button
              key={iv}
              type="button"
              role="tab"
              aria-selected={iv === interval}
              className={`timeframe-tab${iv === interval ? " active" : ""}`}
              onClick={() => setIntervalValue(iv)}
            >
              {iv}
            </button>
          ))}
        </div>
      </div>

      <PanelBoundary label={t("ticker.panel.decisionTable")}>
        <DecisionTable symbol={symbol} interval={interval} />
      </PanelBoundary>
    </>
  );
}

/** News & sentiment. `NewsPanel` renders its own `.panel` card and is out of this refactor's scope
 *  to edit, so it is bounded from the outside rather than given a second, duplicate heading here. */
export function TickerNewsView({ symbol }: { symbol: string }) {
  const { t } = useT();
  const news = useTickerNews(symbol);
  return (
    <PanelBoundary label={t("ticker.panel.news")}>
      <ScrollPanel label={t("ticker.panel.news")} expandable size="md">
        <NewsPanel data={news.data} phase={news.phase} message={news.message} />
      </ScrollPanel>
    </PanelBoundary>
  );
}

/** The reverse of the Institutions page: that one starts from a filer, this asks which filers hold
 *  the symbol already on screen. It fetches nothing until the reader presses its own button. */
export function TickerHoldersView({ symbol }: { symbol: string }) {
  const { t } = useT();
  return (
    <PanelBoundary label={t("ticker.panel.institutionalHolders")}>
      <ScrollPanel label={t("ticker.panel.institutionalHolders")} expandable size="md">
        <InstitutionalHolders symbol={symbol} />
      </ScrollPanel>
    </PanelBoundary>
  );
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function TickerHeader({ symbol, summary }: { symbol: string; summary: TickerSummary }) {
  const { t } = useT();
  const profile: Profile | null = summary.profile;
  const quote: Quote | null = summary.quote;
  const currency = profile?.currency ?? "USD";
  const changePositive = (quote?.change ?? 0) >= 0;

  return (
    <div className="panel">
      <div className="ticker-header">
        <div className="ticker-symbol-block">
          <span className="ticker-symbol">{symbol}</span>
          <span className="ticker-name">{profile?.name ?? t("ticker.header.nameUnavailable")}</span>
          <span className="ticker-meta">
            {profile?.exchange ?? "—"} · {profile?.instrument_type ?? "—"} · {currency}
          </span>
        </div>
        <div className="ticker-price-block">
          <span className="ticker-price">{formatPrice(quote?.price ?? null, currency)}</span>
          {quote && quote.change !== null && (
            <span className={`ticker-change ${changePositive ? "pos" : "neg"}`}>
              {formatPrice(quote.change, currency)} ({formatPercent(quote.change_pct)})
            </span>
          )}
          <MarketStateBadge state={quote?.market_state ?? null} />
          <span className="ticker-range">
            {t("ticker.header.range", {
              low: formatPrice(quote?.fifty_two_week_low ?? null, currency),
              high: formatPrice(quote?.fifty_two_week_high ?? null, currency),
            })}
          </span>
          {quote && quote.volume !== null && (
            <span className="ticker-meta">
              {t("ticker.header.volume", { volume: formatVolume(quote.volume) })}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function MarketStateBadge({ state }: { state: string | null }) {
  if (!state) return null;
  const normalized = state.toUpperCase();
  const cls = normalized === "REGULAR" ? "ok" : normalized === "CLOSED" ? "none" : "stale";
  return <span className={`badge ${cls}`}>{state}</span>;
}

// ---------------------------------------------------------------------------
// Warnings -- the honest part of the product. A stale/provider_fallback/clamped warning must be
// visible, never swallowed.
// ---------------------------------------------------------------------------

/**
 * `MarketWarning.kind` is a stable wire token (`stale`, `provider_fallback`, `clamped`,
 * `short_history`, `partial_bar`, `gap`, ...), not UI copy -- rendering it bare put literal
 * snake_case on screen. Maps the known tokens to a tone + translated label for `StatusPill`; an
 * unrecognised future token still gets a readable pill rather than the raw string. Duplicated from
 * `Macro.tsx`'s own copy rather than shared, matching this codebase's existing convention for a
 * wire enum's display label (see `market.institutions.action.*` vs `market.consensus.action.*`).
 */
function warningPillMeta(kind: string, t: Translator): { tone: PillTone; label: string } {
  switch (kind) {
    case "stale":
      return { tone: "warn", label: t("ui.pill.stale") };
    case "provider_fallback":
      return { tone: "warn", label: t("ticker.warningKind.providerFallback") };
    case "clamped":
      return { tone: "info", label: t("ticker.warningKind.clamped") };
    case "short_history":
      return { tone: "warn", label: t("ticker.warningKind.shortHistory") };
    case "partial_bar":
      return { tone: "info", label: t("ticker.warningKind.partialBar") };
    case "gap":
      return { tone: "warn", label: t("ticker.warningKind.gap") };
    default:
      return { tone: "neutral", label: t("ticker.warningKind.other") };
  }
}

function WarningsStrip({ warnings }: { warnings: MarketWarning[] }) {
  const { t } = useT();
  if (warnings.length === 0) return null;
  return (
    <div className="panel">
      <h2>{t("ticker.warnings.heading")}</h2>
      <div className="warnings-strip">
        {warnings.map((w, i) => {
          const meta = warningPillMeta(w.kind, t);
          return (
            <div className="warning-chip" key={`${w.kind}-${i}`}>
              <StatusPill tone={meta.tone} label={meta.label} />
              <span className="message">{w.message}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Coverage
// ---------------------------------------------------------------------------

function CoveragePanel({ coverage }: { coverage: Coverage[] }) {
  const { t } = useT();
  const heading = t("ticker.coverage.heading");
  if (coverage.length === 0) {
    return (
      <div className="panel">
        <h2>{heading}</h2>
        <div className="placeholder">{t("ticker.coverage.empty")}</div>
      </div>
    );
  }
  return (
    <ScrollPanel title={<h2>{heading}</h2>} label={heading} expandable size="md">
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">{t("ticker.coverage.col.interval")}</th>
              <th scope="col">{t("ticker.coverage.col.rows")}</th>
              <th scope="col">{t("ticker.coverage.col.first")}</th>
              <th scope="col">{t("ticker.coverage.col.last")}</th>
              <th scope="col">{t("ticker.coverage.col.fetched")}</th>
            </tr>
          </thead>
          <tbody>
            {coverage.map((c, i) => (
              <tr key={`${c.interval}-${i}`}>
                <td>{c.interval}</td>
                <td>{c.rows.toLocaleString()}</td>
                <td>{c.first_ts ?? "—"}</td>
                <td>{c.last_ts ?? "—"}</td>
                <td>{c.fetched_at ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ScrollPanel>
  );
}

// ---------------------------------------------------------------------------
// Fundamentals -- null or `unavailable_reason` for most of this portfolio, since ETFs file
// nothing with the SEC. That must render as an explained absence, not an error or an empty box.
// ---------------------------------------------------------------------------

function FundamentalsPanel({ fundamentals }: { fundamentals: Fundamentals | null }) {
  const { t } = useT();
  const heading = t("ticker.fundamentals.heading");
  const emptyMessage =
    fundamentals === null
      ? t("ticker.fundamentals.notAttempted")
      : fundamentals.unavailable_reason
        ? fundamentals.unavailable_reason
        : fundamentals.facts.length === 0
          ? t("ticker.fundamentals.noFacts")
          : null;
  if (emptyMessage !== null) {
    return (
      <div className="panel">
        <h2>{heading}</h2>
        <div className="placeholder">{emptyMessage}</div>
      </div>
    );
  }
  // `emptyMessage === null` above rules out every non-table case, but TypeScript can't see that
  // through the ternary -- narrow explicitly rather than asserting.
  const facts = fundamentals?.facts ?? [];
  return (
    <ScrollPanel title={<h2>{heading}</h2>} label={heading} expandable size="md">
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">{t("ticker.fundamentals.col.label")}</th>
              <th scope="col">{t("common.value")}</th>
              <th scope="col">{t("ticker.fundamentals.col.unit")}</th>
              <th scope="col">{t("ticker.fundamentals.col.periodEnd")}</th>
              <th scope="col">{t("ticker.fundamentals.col.fiscalPeriod")}</th>
              <th scope="col">{t("ticker.fundamentals.col.form")}</th>
            </tr>
          </thead>
          <tbody>
            {facts.map((f) => (
              <tr key={`${f.concept}-${f.accession}`}>
                <td>{f.label}</td>
                <td>{f.value.toLocaleString()}</td>
                <td>{f.unit}</td>
                <td>{f.period_end}</td>
                <td>{f.fiscal_period}</td>
                <td>{f.form}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ScrollPanel>
  );
}
