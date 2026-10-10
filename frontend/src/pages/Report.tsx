/**
 * The per-holding report: profile and quote, verified narrative sections in order, the drawdown
 * profile and decision-table summary if the backend attached them, the strategy backtest card, the
 * full fact bundle, top-level warnings, and the disclaimer.
 *
 * One fetch (`useReport`) drives the page shell, but every section below the header owns its own
 * presence check -- `drawdown`, `decisions` and `strategy` are each independently nullable on the
 * wire, and a section that is absent for this symbol renders nothing rather than a placeholder that
 * implies a fetch failed. `NarrativeSection` additionally owns its own per-section grounding
 * failure, so one ungrounded paragraph does not take the rest of the report with it, and
 * `StrategyCard` fetches its own on-demand strategy runs through a separate hook, so a bad strategy
 * request cannot blank anything above it.
 */
import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { formatDepth, formatUnderwater, type DrawdownProfile } from "@/api/backtest";
import { CurrentDrawdownCard } from "@/components/DrawdownTable";
import { formatPercent, formatPrice, INTERVAL_OPTIONS } from "@/api/market";
import {
  reportApi,
  type Interval,
  type Profile,
  type Quote,
  type Report as ReportData,
  type ReportSection,
} from "@/api/report";
import { edgeOf, formatRate, formatSignedRate, HORIZONS, stateLabel, type DecisionTable } from "@/api/rules";
import type { MarketWarning } from "@/api/market";
import Collapsible from "@/components/Collapsible";
import FactTable from "@/components/FactTable";
import NarrativeSection from "@/components/NarrativeSection";
import { ScrollRegion } from "@/components/ScrollPanel";
import StatGrid from "@/components/StatGrid";
import StatusPill, { type PillTone } from "@/components/StatusPill";
import StrategyCard from "@/components/StrategyCard";
import { useReport } from "@/hooks/useReport";
import { type Translator, useT } from "@/i18n";

const EXAMPLE_SYMBOLS = ["QQQ", "SOXL", "NVDA", "SPY"];


export default function Report() {
  const { symbol: rawSymbol } = useParams<{ symbol: string }>();
  const symbol = rawSymbol ? rawSymbol.toUpperCase() : null;
  const navigate = useNavigate();

  const [symbolInput, setSymbolInput] = useState(symbol ?? "");

  const submitSymbol = (value: string) => {
    const next = value.trim().toUpperCase();
    if (!next) return;
    navigate(`/symbol/${encodeURIComponent(next)}?tab=report`);
  };

  if (!symbol) {
    return (
      <ReportPrompt
        value={symbolInput}
        onChange={setSymbolInput}
        onSubmit={(v) => {
          setSymbolInput(v);
          submitSymbol(v);
        }}
      />
    );
  }

  return (
    <ReportDetail
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

function ReportPrompt({
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
      <h1>{t("market.report.title")}</h1>
      <p className="subtitle">{t("market.report.subtitle")}</p>

      <div className="panel">
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
            placeholder={t("market.report.symbolPlaceholder")}
            aria-label={t("common.symbol")}
            autoFocus
            spellCheck={false}
          />
          <button type="submit" className="symbol-submit">
            {t("market.report.go")}
          </button>
        </form>
        <div className="placeholder">{t("market.report.noSymbolYet")}</div>
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
// Loaded report
// ---------------------------------------------------------------------------

function ReportDetail({
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
      <p className="subtitle">{t("market.report.subtitle")}</p>

      <div className="panel">
        <form
          className="symbol-form"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            onSubmitSymbol(symbolInput);
          }}
        >
          <input
            className="symbol-input"
            value={symbolInput}
            onChange={(e) => onSymbolInputChange(e.target.value.toUpperCase())}
            aria-label={t("common.symbol")}
            spellCheck={false}
          />
          <button type="submit" className="symbol-submit">
            {t("market.report.go")}
          </button>
        </form>
      </div>

      <ReportView symbol={symbol} />
    </>
  );
}

/**
 * The per-symbol report body: an interval picker (moved here from the top form above so this
 * component is self-contained on just a `symbol` prop -- see `Ticker.tsx`'s own `TickerDecisionView`
 * for the identical reasoning), then the loading/error states and the loaded report itself.
 * Extracted so `Symbol.tsx` (the merged Ticker+Report page, UX refactor 2.1) can mount this as its
 * Report tab without duplicating `useReport` or any of the rendering below it.
 */
export function ReportView({ symbol }: { symbol: string }) {
  const { t } = useT();
  const [interval, setInterval] = useState<Interval>("1d");
  const { report, phase, message } = useReport(symbol, interval);

  return (
    <>
      <div className="panel">
        <div className="symbol-form">
          <select
            className="bt-entry-select"
            value={interval}
            onChange={(e) => setInterval(e.target.value as Interval)}
            aria-label={t("market.report.intervalAriaLabel")}
          >
            {INTERVAL_OPTIONS.map((i) => (
              <option key={i.value} value={i.value}>
                {i.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {phase === "loading" && (
        <div className="panel">
          <div className="placeholder">{t("market.report.loadingFor", { symbol })}</div>
        </div>
      )}
      {(phase === "notfound" || phase === "error") && (
        <div className="panel">
          <div className="placeholder">{message}</div>
        </div>
      )}

      {phase === "loaded" && report && <ReportBody symbol={symbol} interval={interval} report={report} />}
    </>
  );
}

function ReportBody({ symbol, interval, report }: { symbol: string; interval: Interval; report: ReportData }) {
  const { t } = useT();
  return (
    <>
      <ReportHeader symbol={symbol} profile={report.profile} quote={report.quote} />

      <ReportWarnings warnings={report.warnings} />

      <NarrativeSections sections={report.sections} />

      {report.drawdown && <DrawdownPanel drawdown={report.drawdown} />}

      {report.decisions && <DecisionSummaryPanel decisions={report.decisions} />}

      <StrategyCard symbol={symbol} interval={interval} initial={report.strategy} />

      <FactTable bundle={report.bundle} />

      <div className="panel">
        <a className="symbol-submit report-export-link" href={reportApi.exportUrl(symbol, interval)} download>
          {t("market.report.exportMarkdown")}
        </a>
      </div>

      <p className="report-disclaimer">
        {/* `report.disclaimer` is backend-written boilerplate, not UI copy this shard owns -- it
            stays English regardless of `lang`, and the badge says so plainly rather than leaving a
            Korean reader to wonder why this one paragraph did not switch. */}
        {report.disclaimer}{" "}
        <span className="badge" title={t("common.sourceEnglishTitle")}>
          {t("common.sourceEnglish")}
        </span>
      </p>
    </>
  );
}

// ---------------------------------------------------------------------------
// Narrative sections -- the first stays fully open (it is the case's headline, and this page
// already runs 5.8 screens with nothing collapsible before this pass). Every section after it
// collapses behind `Collapsible`, since `NarrativeSection` itself renders a full `.panel` card with
// its own heading and is out of this page's scope to edit -- wrapping it is the only lever
// available, so the section's own title is reused as the disclosure summary rather than inventing
// a second, shorter label that would disagree with the heading revealed underneath it.
// ---------------------------------------------------------------------------

function NarrativeSections({ sections }: { sections: ReportSection[] }) {
  return (
    <>
      {sections.map((section, i) =>
        i === 0 ? (
          <NarrativeSection key={section.section_id} section={section} />
        ) : (
          <Collapsible
            key={section.section_id}
            title={<h2 className="section-heading">{section.title}</h2>}
            defaultOpen={false}
          >
            <NarrativeSection section={section} />
          </Collapsible>
        ),
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function ReportHeader({
  symbol,
  profile,
  quote,
}: {
  symbol: string;
  profile: Profile | null;
  quote: Quote | null;
}) {
  const { t } = useT();
  const currency = profile?.currency ?? "USD";
  const change = quote?.change ?? null;
  const changePct = quote?.change_pct ?? null;
  const changePositive = change !== null && change >= 0;

  return (
    <div className="panel">
      <div className="ticker-header">
        <div className="ticker-symbol-block">
          <span className="ticker-symbol">{symbol}</span>
          <span className="ticker-name">{profile?.name ?? t("market.report.nameUnavailable")}</span>
          <span className="ticker-meta">
            {profile?.exchange ?? "—"} · {profile?.instrument_type ?? "—"} · {currency}
          </span>
        </div>
        <div className="ticker-price-block">
          <span className="ticker-price">{formatPrice(quote?.price ?? null, currency)}</span>
          {change !== null && (
            <span className={`ticker-change ${changePositive ? "pos" : "neg"}`}>
              {formatPrice(change, currency)} ({formatPercent(changePct)})
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * `MarketWarning.kind` is a stable wire token (`stale`, `provider_fallback`, `clamped`,
 * `short_history`, `partial_bar`, `gap`, ...), not UI copy -- rendering it bare put literal
 * snake_case on screen. Maps the known tokens to a tone + translated label for `StatusPill`; an
 * unrecognised future token still gets a readable pill rather than the raw string. Duplicated from
 * `Macro.tsx`/`Ticker.tsx`'s own copies rather than shared, matching this codebase's existing
 * convention for a wire enum's display label (see `market.institutions.action.*` vs
 * `market.consensus.action.*`). Shared by `ReportWarnings` and `DrawdownPanel` below -- both render
 * the same `MarketWarning[]` shape on this one page.
 */
function warningPillMeta(kind: string, t: Translator): { tone: PillTone; label: string } {
  switch (kind) {
    case "stale":
      return { tone: "warn", label: t("ui.pill.stale") };
    case "provider_fallback":
      return { tone: "warn", label: t("market.warningKind.providerFallback") };
    case "clamped":
      return { tone: "info", label: t("market.warningKind.clamped") };
    case "short_history":
      return { tone: "warn", label: t("market.warningKind.shortHistory") };
    case "partial_bar":
      return { tone: "info", label: t("market.warningKind.partialBar") };
    case "gap":
      return { tone: "warn", label: t("market.warningKind.gap") };
    default:
      return { tone: "neutral", label: t("market.warningKind.other") };
  }
}

function ReportWarnings({ warnings }: { warnings: MarketWarning[] }) {
  const { t } = useT();
  if (warnings.length === 0) return null;
  return (
    <div className="panel">
      <h2>{t("market.report.warningsTitle")}</h2>
      <ScrollRegion size="sm" label={t("market.report.warningsTitle")}>
        <div className="warnings-strip">
          {warnings.map((w, i) => {
            const meta = warningPillMeta(w.kind, t);
            return (
              <div className="warning-chip" key={`${w.kind}-${i}`}>
                <StatusPill tone={meta.tone} label={meta.label} />
                {/* `w.message` is backend-written diagnostic prose, not UI copy this shard owns --
                    it stays English regardless of `lang`, and the badge says so plainly. */}
                <span className="message">{w.message}</span>
                <span className="badge" title={t("common.sourceEnglishTitle")}>
                  {t("common.sourceEnglish")}
                </span>
              </div>
            );
          })}
        </div>
      </ScrollRegion>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Drawdown -- renders `DrawdownTable`'s own `CurrentDrawdownCard` and reuses its
// `formatDepth`/`formatUnderwater` and `bt-drawdown-table` presentation, against the profile the
// report endpoint already attached rather than issuing a second fetch against the backtest
// endpoint. This comment used to claim it reused the presentation; it reused the CSS and
// reimplemented the logic, which is how the two pages came to disagree about the same episode.
// ---------------------------------------------------------------------------

function DrawdownPanel({ drawdown }: { drawdown: DrawdownProfile }) {
  const { t } = useT();
  return (
    <div className="panel">
      <h2 className="section-heading">
        {t("market.report.drawdown.title", { basis: drawdown.basis })}
      </h2>
      <StatGrid
        items={[
          {
            label: t("market.report.sampleLabel"),
            value: `${drawdown.first_bar ?? "—"} → ${drawdown.last_bar ?? "—"}`,
          },
          { label: t("market.report.drawdown.bars"), value: drawdown.bars.toLocaleString() },
          {
            label: t("market.report.drawdown.episodesConsidered"),
            value: drawdown.episodes_considered.toLocaleString(),
          },
        ]}
      />

      {drawdown.warnings.length > 0 && (
        <ScrollRegion size="sm" label={t("market.report.warningsTitle")}>
          <div className="warnings-strip">
            {drawdown.warnings.map((w, i) => {
              const meta = warningPillMeta(w.kind, t);
              return (
                <div className="warning-chip" key={`${w.kind}-${i}`}>
                  <StatusPill tone={meta.tone} label={meta.label} />
                  {/* `w.message` is backend-written diagnostic prose, not UI copy this shard owns --
                      it stays English regardless of `lang`, and the badge says so plainly. */}
                  <span className="message">{w.message}</span>
                  <span className="badge" title={t("common.sourceEnglishTitle")}>
                    {t("common.sourceEnglish")}
                  </span>
                </div>
              );
            })}
          </div>
        </ScrollRegion>
      )}

      {/* The shared card, not a local copy. This page used to render its own, and the copy missed
          the `depth_now` fix: `/backtest` showed XLE 1.0% off its peak while this page showed 15.6%
          for the same episode on the same day -- a trader reading here would think a position was
          down double digits when it was down about one. Found by a UAT persona loading both. */}
      <CurrentDrawdownCard episode={drawdown.current} basis={drawdown.basis} />

      {drawdown.episodes.length === 0 ? (
        <div className="placeholder">
          {t("market.report.drawdown.noEpisodes", { symbol: drawdown.symbol })}
        </div>
      ) : (
        <ScrollRegion
          size="md"
          label={t("market.report.drawdown.title", { basis: drawdown.basis })}
        >
          <div className="table-wrap">
            <table className="data-table bt-drawdown-table">
              <thead>
                <tr>
                  <th scope="col">{t("market.report.drawdown.header.peak")}</th>
                  <th scope="col">{t("market.report.drawdown.header.trough")}</th>
                  <th scope="col" className="num">
                    {t("market.report.drawdown.header.depth")}
                  </th>
                  <th scope="col" className="num">
                    {t("market.report.drawdown.header.barsToTrough")}
                  </th>
                  <th scope="col">{t("market.report.drawdown.header.recovery")}</th>
                  <th scope="col">{t("market.report.drawdown.header.underwater")}</th>
                </tr>
              </thead>
              <tbody>
                {drawdown.episodes.map((ep, i) => (
                  <tr key={`${ep.peak_date}-${i}`}>
                    <td>
                      {ep.peak_date}
                      <div className="bt-cell-sub">{ep.peak_value.toLocaleString()}</div>
                    </td>
                    <td>
                      {ep.trough_date}
                      <div className="bt-cell-sub">{ep.trough_value.toLocaleString()}</div>
                    </td>
                    <td className="num">{formatDepth(ep.depth)}</td>
                    <td className="num">{ep.bars_to_trough.toLocaleString()}</td>
                    <td>
                      {ep.recovery_date ?? "—"}
                      <div className="bt-cell-sub">
                        {ep.bars_to_recovery === null
                          ? "—"
                          : t("market.report.drawdown.barsCount", {
                              count: ep.bars_to_recovery.toLocaleString(),
                            })}
                      </div>
                    </td>
                    <td>{formatUnderwater(ep)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ScrollRegion>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Decision table summary -- a condensed view (current state plus the 20-bar edge) of what the full
// workbench decision table on the Ticker page shows in depth. Same "never a hit rate without its
// baseline" and "unknown is not styled like false" rules from `api/rules.ts` apply here too.
// ---------------------------------------------------------------------------

function DecisionSummaryPanel({ decisions }: { decisions: DecisionTable }) {
  const { t } = useT();
  const horizonIndex = HORIZONS.indexOf(20);
  const firingCount = decisions.rows.filter((r) => r.state.state === "true").length;

  return (
    <div className="panel">
      <h2 className="section-heading">{t("market.report.decisions.title")}</h2>
      <p className="subtitle">{t("market.report.decisions.subtitle")}</p>
      <StatGrid
        items={[
          {
            label: t("market.report.sampleLabel"),
            value: `${decisions.first_bar ?? "—"} → ${decisions.last_bar ?? "—"}`,
          },
          {
            label: t("market.report.decisions.barsEvaluated"),
            value: decisions.bars_evaluated.toLocaleString(),
          },
          {
            label: t("market.report.decisions.rulesFiringNow"),
            value: firingCount.toLocaleString(),
          },
        ]}
      />

      {decisions.rows.length === 0 ? (
        <div className="placeholder">{t("market.report.decisions.noRules")}</div>
      ) : (
        <ScrollRegion size="md" label={t("market.report.decisions.title")}>
          <div className="table-wrap">
            <table className="data-table report-decision-summary">
              <thead>
                <tr>
                  <th scope="col">{t("market.report.decisions.header.rule")}</th>
                  <th scope="col">{t("market.report.decisions.header.state")}</th>
                  <th scope="col" className="num">
                    {t("market.report.decisions.header.edge20b")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {decisions.rows.map((row) => {
                  const evidence = horizonIndex >= 0 ? row.evidence[horizonIndex] : undefined;
                  const edge = evidence ? edgeOf(evidence) : null;
                  const cls = edge === null ? "" : edge > 0 ? "pos" : edge < 0 ? "neg" : "";
                  const stateCls =
                    row.state.state === "true" ? "ok" : row.state.state === "unknown" ? "none" : "";
                  return (
                    <tr key={row.rule.rule_id}>
                      <td>
                        {row.rule.name}
                        <div className="bt-cell-sub">{row.rule.expression}</div>
                      </td>
                      <td>
                        <span className={`badge ${stateCls}`}>{stateLabel(row.state.state)}</span>
                      </td>
                      <td className="num">
                        {evidence ? (
                          <>
                            <div className={`edge-value ${cls}`}>{formatSignedRate(edge)}</div>
                            <div className="bt-cell-sub">
                              {t("market.report.decisions.hitRateVsBaseline", {
                                hitRate: formatRate(evidence.hit_rate),
                                baseline: formatRate(evidence.baseline_hit_rate),
                              })}
                            </div>
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </ScrollRegion>
      )}
    </div>
  );
}
