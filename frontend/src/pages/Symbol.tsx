/**
 * The merged Ticker + Report page (UX refactor 2.1): one symbol bar and five views -- Chart and
 * Decision from `Ticker.tsx`, Report from `Report.tsx`, and Holders/News, also from `Ticker.tsx` --
 * behind one `FolderTabs` rail, replacing the old two-route `/ticker` and `/report` split for a
 * reader who used to have to leave one page to reach the other's content for the same symbol.
 *
 * Every tab mounts exactly one of the exported `Ticker*View` / `ReportView` components (see
 * `Ticker.tsx` and `Report.tsx`) and nothing else -- each of those is already self-contained from
 * the refactor that created them, owning its own fetch and its own loading/error states off of just
 * a `symbol` prop. This page does no data fetching of its own beyond the symbol-bar text input.
 *
 * Only the active tab's subtree is ever mounted, the same rule `Tax.tsx` already established for
 * its own `FolderTabs` rail: switching tabs here costs exactly the one fetch the newly-active view
 * needs, not the four-or-five simultaneous ones the old, still-separate `/ticker` page pays by
 * mounting every one of its sections (via `TickerView`) at once.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { FolderTabs } from "@/components/FolderTabs";
import StatusPill from "@/components/StatusPill";
import { useTabParam } from "@/hooks/useTabParam";
import { useT } from "@/i18n";
import { ReportView } from "@/pages/Report";
import {
  EXAMPLE_SYMBOLS,
  TickerChartView,
  TickerDecisionView,
  TickerHoldersView,
  TickerNewsView,
} from "@/pages/Ticker";

import "./Symbol.css";

const SYMBOL_TABS = ["chart", "decision", "report", "holders", "news"] as const;
type SymbolTab = (typeof SYMBOL_TABS)[number];

export default function Symbol() {
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
    return <SymbolPrompt value={symbolInput} onChange={setSymbolInput} onSubmit={submitSymbol} />;
  }

  // Remounting on symbol change resets every mounted view's own per-symbol state, matching
  // `Ticker.tsx`'s own `key={symbol}` convention on `TickerDetail`.
  return (
    <SymbolDetail
      key={symbol}
      symbol={symbol}
      symbolInput={symbolInput}
      onSymbolInputChange={setSymbolInput}
      onSubmitSymbol={submitSymbol}
    />
  );
}

// ---------------------------------------------------------------------------
// Empty state -- the same shape as `Ticker.tsx`'s own prompt (prompt-line, symbol form, example
// buttons, `EXAMPLE_SYMBOLS` reused rather than re-declared), under this page's own title since this
// route stands in for both `/ticker` and `/report`, not just the one.
// ---------------------------------------------------------------------------

function SymbolPrompt({
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
      <h1>{t("symbol.title")}</h1>
      <p className="subtitle">{t("symbol.subtitle")}</p>

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
// Loaded symbol -- the bar (heading + input form only, no price data: that already lives inside
// the Chart tab's `TickerChartView` header and the Report tab's own `ReportHeader`, and fetching
// the summary a third time here just to repeat it would be a wasted request), the tab rail, and
// exactly one mounted view.
// ---------------------------------------------------------------------------

function SymbolDetail({
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
  // Lives in the URL, not a plain `useState` -- a reload on `/symbol/AAPL?tab=report` opens
  // directly on the Report tab and Back restores the previous one. See `useTabParam`'s own module
  // docstring, and `Tax.tsx`'s identical use of it for its own tab rail.
  const [tab, setTab] = useTabParam<SymbolTab>("tab", SYMBOL_TABS, "chart");

  return (
    <>
      <h1>{symbol}</h1>
      <p className="subtitle">{t("symbol.subtitle")}</p>

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
        {/* Cross-links (UX refactor 3.3): none of the three destinations below take a symbol
            parameter today -- Research Desk and Paper Desk have no per-symbol view, and Filers has
            no symbol filter to deep-link into (see `Filers.tsx`/`Institutions.tsx`) -- so these are
            plain navigation links, not `/research-desk/{symbol}`-shaped ones. Reuses `.download-link`
            (already global, already used by the Form 8949 CSV link on the Tax page) rather than
            inventing new chrome for three link-shaped buttons. */}
        <div className="symbol-quick-links">
          <Link className="download-link" to="/research-desk">
            {t("symbol.quickLinks.researchDesk")}
          </Link>
          <Link className="download-link" to="/paper-desk">
            {t("symbol.quickLinks.paperDesk")}
          </Link>
          <Link className="download-link" to="/filers">
            {t("symbol.quickLinks.filers")}
          </Link>
        </div>
      </div>

      <div className="symbol-tabs">
        <FolderTabs
          label={t("symbol.tabs.label")}
          active={tab}
          // `FolderTabs` is generic over plain `string` ids; the cast is safe because every `id`
          // below is drawn from `SYMBOL_TABS`, the same union `useTabParam`'s `allowed` list enforces.
          onChange={(id) => setTab(id as SymbolTab)}
          items={[
            { id: "chart", label: t("symbol.tabs.chart") },
            { id: "decision", label: t("symbol.tabs.decision") },
            { id: "report", label: t("symbol.tabs.report") },
            { id: "holders", label: t("symbol.tabs.holders") },
            { id: "news", label: t("symbol.tabs.news") },
          ]}
        />
      </div>

      {/* Only the active tab's subtree mounts -- see the module docstring. */}
      {tab === "chart" && <TickerChartView symbol={symbol} />}
      {/* The Decision tab prints an edge percentage and a significance grade per rule, and until
          now printed them with no caveat anywhere above the fold -- a table of percentages headed by
          a ticker reads as a recommendation whatever the footnotes say. Two pills, both `warn`
          (same tone, so no `PillLegend` is owed per COPY-STYLE.md), and one line naming the actual
          limitation:

          IN-SAMPLE is unconditional here, not derived from the response, because it is true by
          construction rather than by configuration -- `DecisionTable` grades every rule on the same
          bars it reports as its sample (`ticker.decision.sampleRange`), so there is no held-out
          period for it to be out-of-sample against. A conditional pill would imply the other case
          exists on this tab. */}
      {tab === "decision" && (
        <div className="panel disclaimer symbol-decision-caveat" role="note">
          <StatusPill tone="warn" label={t("ui.pill.notAdvice")} />{" "}
          <StatusPill tone="warn" label={t("ui.pill.inSample")} />{" "}
          {t("ticker.decision.caveat")}
        </div>
      )}
      {tab === "decision" && <TickerDecisionView symbol={symbol} />}
      {tab === "report" && <ReportView symbol={symbol} />}
      {tab === "holders" && <TickerHoldersView symbol={symbol} />}
      {tab === "news" && <TickerNewsView symbol={symbol} />}
    </>
  );
}
