/**
 * The strategy backtest: an entry/exit rule against history, with buy-and-hold sitting next to
 * every number it could otherwise be mistaken for beating.
 *
 * Four rules from `api/report.ts`'s module docstring drive this layout, in the order they matter.
 *
 * **A return without `exposure` in view is not shown.** `total_return` and `cagr` always carry the
 * fraction of bars the strategy actually held a position, right under the number -- a return near
 * buy-and-hold's at 5% exposure is a different fact from the same return at 100%.
 *
 * **Buy-and-hold sits adjacent to every strategy metric, and the difference gets the emphasis.**
 * `excessReturn`/`excessCagr` get their own column, styled with the same `.edge-value` treatment as
 * every other edge on this workbench, so a losing strategy reads as a loss rather than as a big
 * number next to a bigger one.
 *
 * **`cost_drag` is prominent, and `edgeVerdict` drives a loud callout.** Three outcomes, not two: a
 * strategy that *beat* buy-and-hold by less than its own frictions cost has no demonstrated edge,
 * and one that simply lost is a different finding that must not borrow the first's gentler phrasing.
 * Burying either in a details table would be the easiest way to misread this card.
 *
 * **`guardOk(result.guard)` gates everything.** A failed or unverified guard renders only the guard
 * findings; no metric, no trade, no equity curve.
 *
 * `null` never renders as `0` -- every numeric cell goes through `formatRate`/`formatSignedRate` or
 * the local `formatRatio`, all of which render `null` as an em dash.
 */
import { useState, type FormEvent } from "react";

import RuleValidationNote from "@/components/RuleValidationNote";
import { useRuleValidation } from "@/hooks/useRuleValidation";

import { guardOk, guardStatusLabel } from "@/api/backtest";
import {
  edgeVerdict,
  excessCagr,
  excessReturn,
  type EquityPoint,
  type GuardReport,
  type Interval,
  type StrategyRequest,
  type StrategyResult,
  type Trade,
} from "@/api/report";
import { formatRate, formatSignedRate } from "@/api/rules";
import type { MarketWarning } from "@/api/market";
import StatGrid from "@/components/StatGrid";
import { useStrategy } from "@/hooks/useReport";
import { Trans, useT } from "@/i18n";

interface StrategyCardProps {
  symbol: string;
  interval: Interval;
  initial: StrategyResult | null;
}

function formatRatio(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return value.toFixed(2);
}

export default function StrategyCard({ symbol, interval, initial }: StrategyCardProps) {
  const { t } = useT();
  const initialMaxHolding = initial?.spec.max_holding_bars ?? null;
  const initialStopLoss = initial?.spec.stop_loss_pct ?? null;
  const initialSlippage = initial?.costs.slippage_bps ?? null;

  const [entry, setEntry] = useState(initial?.spec.entry ?? "");
  const [exit, setExit] = useState(initial?.spec.exit ?? "");
  const [maxHoldingBars, setMaxHoldingBars] = useState(
    initialMaxHolding !== null ? String(initialMaxHolding) : "",
  );
  const [stopLossPct, setStopLossPct] = useState(
    initialStopLoss !== null ? String(initialStopLoss * 100) : "",
  );
  const [slippageBps, setSlippageBps] = useState(initialSlippage !== null ? String(initialSlippage) : "");

  const { result, phase, message, run } = useStrategy();
  const active = result ?? initial;
  // The exit rule is optional, so an empty one is skipped rather than reported invalid -- that is
  // `useRuleValidation`'s rule, and it is why this can pass both fields without special-casing.
  const validation = useRuleValidation([entry, exit]);
  const canSubmit = entry.trim().length > 0 && validation.invalid.length === 0;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmedEntry = entry.trim();
    if (!trimmedEntry) return;

    const request: StrategyRequest = { symbol, interval, entry: trimmedEntry };

    const trimmedExit = exit.trim();
    if (trimmedExit) request.exit = trimmedExit;

    const bars = Number.parseInt(maxHoldingBars, 10);
    if (maxHoldingBars.trim() !== "" && Number.isFinite(bars) && bars > 0) {
      request.max_holding_bars = bars;
    }

    const stop = Number.parseFloat(stopLossPct);
    if (stopLossPct.trim() !== "" && Number.isFinite(stop) && stop > 0) {
      request.stop_loss_pct = stop / 100;
    }

    const slip = Number.parseFloat(slippageBps);
    if (slippageBps.trim() !== "" && Number.isFinite(slip) && slip >= 0) {
      request.slippage_bps = slip;
    }

    run(request);
  };

  return (
    <div className="panel">
      <h2 className="section-heading">{t("strategy.strategyCard.title")}</h2>
      <p className="subtitle">{t("strategy.strategyCard.subtitle")}</p>

      <form className="report-strategy-form" onSubmit={submit}>
        <label className="rule-editor-label" htmlFor="strategy-entry">
          {t("strategy.strategyCard.entryRuleLabel")}
        </label>
        <input
          id="strategy-entry"
          className="rule-editor-input"
          value={entry}
          onChange={(e) => setEntry(e.target.value)}
          placeholder={t("strategy.ruleEditor.placeholderExample", { expression: "close > sma(200)" })}
          spellCheck={false}
          autoComplete="off"
          aria-describedby="strategy-entry-validity"
        />
        <RuleValidationNote id="strategy-entry-validity" result={validation.resultFor(entry)} />

        <label className="rule-editor-label" htmlFor="strategy-exit">
          {t("strategy.strategyCard.exitRuleLabel")}
        </label>
        <input
          id="strategy-exit"
          className="rule-editor-input"
          value={exit}
          onChange={(e) => setExit(e.target.value)}
          placeholder={t("strategy.ruleEditor.placeholderExample", { expression: "close < sma(200)" })}
          spellCheck={false}
          autoComplete="off"
          aria-describedby="strategy-exit-validity"
        />
        <RuleValidationNote id="strategy-exit-validity" result={validation.resultFor(exit)} />

        <div className="bt-scan-controls">
          <label className="bt-control-label" htmlFor="strategy-max-hold">
            {t("strategy.strategyCard.maxHoldingLabel")}
            <input
              id="strategy-max-hold"
              className="bt-entry-select"
              value={maxHoldingBars}
              onChange={(e) => setMaxHoldingBars(e.target.value)}
              placeholder={t("strategy.strategyCard.nonePlaceholder")}
              inputMode="numeric"
            />
          </label>
          <label className="bt-control-label" htmlFor="strategy-stop">
            {t("strategy.strategyCard.stopLossLabel")}
            <input
              id="strategy-stop"
              className="bt-entry-select"
              value={stopLossPct}
              onChange={(e) => setStopLossPct(e.target.value)}
              placeholder={t("strategy.strategyCard.nonePlaceholder")}
              inputMode="decimal"
            />
          </label>
          <label className="bt-control-label" htmlFor="strategy-slippage">
            {t("strategy.strategyCard.slippageLabel")}
            <input
              id="strategy-slippage"
              className="bt-entry-select"
              value={slippageBps}
              onChange={(e) => setSlippageBps(e.target.value)}
              placeholder={t("strategy.strategyCard.defaultPlaceholder")}
              inputMode="decimal"
            />
          </label>
          <button type="submit" className="symbol-submit" disabled={!canSubmit || phase === "loading"}>
            {phase === "loading"
              ? t("strategy.strategyCard.runningButton")
              : t("strategy.strategyCard.runButton")}
          </button>
        </div>
      </form>

      {phase === "idle" && !active && (
        <div className="placeholder">{t("strategy.strategyCard.idlePlaceholder")}</div>
      )}
      {(phase === "error" || phase === "notfound") && (
        <div className="callout callout-danger">{message}</div>
      )}

      {active && <StrategyResultView result={active} />}
    </div>
  );
}

function StrategyResultView({ result }: { result: StrategyResult }) {
  const { t } = useT();
  if (!guardOk(result.guard)) {
    return <GuardFailure guard={result.guard} />;
  }

  const excess = excessReturn(result);
  const excessAnn = excessCagr(result);
  const verdict = edgeVerdict(result);

  return (
    <div className="report-strategy-result">
      <StrategyWarnings warnings={result.warnings} />

      {/* Three verdicts, not two. "Your edge is inside its costs" is a statement about a marginal
          win, and applying that phrasing to a strategy that trailed buy-and-hold by 130 points
          would describe a rout as a close call. */}
      {verdict === "underperforms" && (
        <div className="callout callout-danger report-cost-callout">
          {t("strategy.strategyCard.verdictUnderperforms", {
            excess: formatSignedRate(excess),
            drag: formatSignedRate(result.cost_drag),
          })}
        </div>
      )}

      {verdict === "inside_costs" && (
        <div className="callout callout-warn report-cost-callout">
          {t("strategy.strategyCard.verdictInsideCosts", {
            excess: formatSignedRate(excess),
            drag: formatSignedRate(result.cost_drag),
          })}
        </div>
      )}

      <StatGrid
        items={[
          {
            label: t("strategy.strategyCard.field.entry"),
            value: <code className="bt-arm-expression">{result.spec.entry}</code>,
          },
          {
            label: t("strategy.strategyCard.field.exit"),
            value: result.spec.exit ? (
              <code className="bt-arm-expression">{result.spec.exit}</code>
            ) : (
              "—"
            ),
          },
          {
            label: t("strategy.strategyCard.field.maxHolding"),
            value:
              result.spec.max_holding_bars !== null
                ? t("strategy.backtest.underwaterBars", { count: result.spec.max_holding_bars })
                : "—",
          },
          {
            label: t("strategy.strategyCard.field.stopLoss"),
            value: result.spec.stop_loss_pct !== null ? formatRate(result.spec.stop_loss_pct) : "—",
          },
          { label: t("strategy.strategyCard.field.slippage"), value: `${result.costs.slippage_bps} bps` },
          {
            label: t("strategy.strategyCard.field.commissionPerTrade"),
            value: result.costs.commission_per_trade.toLocaleString(),
          },
          {
            label: t("strategy.strategyCard.field.costDrag"),
            value: (
              <span className={`edge-value ${result.cost_drag !== null && result.cost_drag < 0 ? "neg" : ""}`}>
                {formatSignedRate(result.cost_drag)}
              </span>
            ),
          },
          {
            label: t("strategy.strategyCard.field.sample"),
            value: `${result.first_bar ?? "—"} → ${result.last_bar ?? "—"}`,
          },
        ]}
      />

      <MetricsTable result={result} excess={excess} excessAnn={excessAnn} />

      {/* "Trades" counts every trade the strategy opened, the one still open at the end included.
          It read "Trades (closed)" directly above "Open at end", so the two invited being added and
          the open trade counted twice -- and it disagreed with the win rate below, which really is
          over closed trades only. "Opened" says which event is being counted; "of which still open"
          says the second figure is a subset rather than an addition. */}
      <StatGrid
        items={[
          { label: t("strategy.strategyCard.field.tradesOpened"), value: result.metrics.trades.toLocaleString() },
          {
            label: t("strategy.strategyCard.field.stillOpen"),
            value: result.open_trades.toLocaleString(),
          },
          {
            label: t("strategy.strategyCard.field.tradesPerYear"),
            value: result.metrics.trades_per_year !== null ? result.metrics.trades_per_year.toFixed(1) : "—",
          },
          {
            label: t("strategy.strategyCard.field.barsPerYear"),
            value: result.metrics.bars_per_year.toLocaleString(),
          },
        ]}
      />

      {result.equity_curve.length > 1 && <EquityCurveChart curve={result.equity_curve} />}

      <TradesTable trades={result.trades} openTrades={result.open_trades} />

      {result.run_id && (
        <p className="bt-run-id">
          <Trans k="strategy.scan.recordedAsRun" values={{ runId: <code>{result.run_id.slice(0, 16)}</code> }} />
        </p>
      )}
    </div>
  );
}

/** `"unverified"` is styled identically to `"failed"` -- a problem, not a pending state -- via the
 *  shared `.callout-danger` treatment, matching `EventStudy`'s `GuardStatusBlock`. */
function GuardFailure({ guard }: { guard: GuardReport }) {
  const { t } = useT();
  return (
    <div className="callout callout-danger bt-guard-callout">
      <div className="bt-guard-status">
        {guard.status === "unverified"
          ? t("strategy.strategyCard.guardUnverified")
          : t("strategy.strategyCard.guardFailed")}
      </div>
      {guard.findings.length > 0 && (
        <ul className="warning-list">
          {guard.findings.map((f, i) => (
            <li key={`${f.check}-${i}`}>
              <strong>{f.check}</strong> — {f.detail} ({guardStatusLabel(f.passed ? "passed" : "failed")})
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StrategyWarnings({ warnings }: { warnings: MarketWarning[] }) {
  if (warnings.length === 0) return null;
  return (
    <div className="warnings-strip">
      {warnings.map((w, i) => (
        <div className="warning-chip" key={`${w.kind}-${i}`}>
          <span className="kind">{w.kind}</span>
          <span className="message">{w.message}</span>
        </div>
      ))}
    </div>
  );
}

function MetricsTable({
  result,
  excess,
  excessAnn,
}: {
  result: StrategyResult;
  excess: number | null;
  excessAnn: number | null;
}) {
  const { t } = useT();
  const excessCls = (v: number | null) => (v === null ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "");

  return (
    <div className="table-wrap">
      <table className="data-table report-strategy-metrics">
        <thead>
          <tr>
            <th scope="col">{t("strategy.strategyCard.header.metric")}</th>
            <th scope="col" className="num">
              {t("strategy.strategyCard.header.strategy")}
            </th>
            <th scope="col" className="num">
              {t("strategy.strategyCard.header.buyHold")}
            </th>
            <th scope="col" className="num">
              {t("strategy.strategyCard.header.excess")}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{t("strategy.strategyCard.metric.totalReturn")}</td>
            <td className="num">
              {formatSignedRate(result.metrics.total_return)}
              <div className="bt-cell-sub">
                {t("strategy.strategyCard.exposureSub", { value: formatRate(result.metrics.exposure) })}
              </div>
            </td>
            <td className="num">
              {formatSignedRate(result.buy_hold.total_return)}
              <div className="bt-cell-sub">
                {t("strategy.strategyCard.exposureSub", { value: formatRate(result.buy_hold.exposure) })}
              </div>
            </td>
            <td className={`num edge-value ${excessCls(excess)}`}>{formatSignedRate(excess)}</td>
          </tr>
          <tr>
            <td>{t("strategy.strategyCard.metric.cagr")}</td>
            <td className="num">{formatSignedRate(result.metrics.cagr)}</td>
            <td className="num">{formatSignedRate(result.buy_hold.cagr)}</td>
            <td className={`num edge-value ${excessCls(excessAnn)}`}>{formatSignedRate(excessAnn)}</td>
          </tr>
          <tr>
            <td>{t("strategy.strategyCard.metric.volatility")}</td>
            <td className="num">{formatRate(result.metrics.volatility)}</td>
            <td className="num">{formatRate(result.buy_hold.volatility)}</td>
            <td className="num">—</td>
          </tr>
          <tr>
            <td>
              {t("strategy.strategyCard.metric.sharpe")}
              <div className="bt-cell-sub">
                {t("strategy.strategyCard.rfSub", { value: formatRate(result.metrics.risk_free_rate) })}
              </div>
            </td>
            <td className="num">{formatRatio(result.metrics.sharpe)}</td>
            <td className="num">{formatRatio(result.buy_hold.sharpe)}</td>
            <td className="num">—</td>
          </tr>
          <tr>
            <td>{t("strategy.strategyCard.metric.sortino")}</td>
            <td className="num">{formatRatio(result.metrics.sortino)}</td>
            <td className="num">{formatRatio(result.buy_hold.sortino)}</td>
            <td className="num">—</td>
          </tr>
          <tr>
            <td>{t("strategy.strategyCard.metric.maxDrawdown")}</td>
            <td className="num">{formatSignedRate(result.metrics.max_drawdown)}</td>
            <td className="num">{formatSignedRate(result.buy_hold.max_drawdown)}</td>
            <td className="num">—</td>
          </tr>
          <tr>
            <td>{t("strategy.strategyCard.metric.exposure")}</td>
            <td className="num">{formatRate(result.metrics.exposure)}</td>
            <td className="num">{formatRate(result.buy_hold.exposure)}</td>
            <td className="num">—</td>
          </tr>
          <tr>
            <td>{t("strategy.strategyCard.metric.winRate")}</td>
            <td className="num">{formatRate(result.metrics.win_rate)}</td>
            <td className="num">{formatRate(result.buy_hold.win_rate)}</td>
            <td className="num">—</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function TradesTable({ trades, openTrades }: { trades: Trade[]; openTrades: number }) {
  const { t } = useT();
  return (
    <>
      <h3>{t("strategy.strategyCard.tradesHeading")}</h3>
      {openTrades > 0 && (
        <p className="bt-cell-sub report-open-trades-note">
          {t(
            openTrades === 1
              ? "strategy.strategyCard.openTradesNote_one"
              : "strategy.strategyCard.openTradesNote_other",
            { count: openTrades },
          )}
        </p>
      )}
      {trades.length === 0 ? (
        <div className="placeholder">{t("strategy.strategyCard.noTrades")}</div>
      ) : (
        <div className="table-wrap">
          <table className="data-table report-trades-table">
            <thead>
              <tr>
                <th scope="col">{t("strategy.strategyCard.tradesHeader.entry")}</th>
                <th scope="col">{t("strategy.strategyCard.tradesHeader.exit")}</th>
                <th scope="col" className="num">
                  {t("strategy.strategyCard.tradesHeader.barsHeld")}
                </th>
                <th scope="col" className="num">
                  {t("strategy.strategyCard.tradesHeader.return")}
                </th>
                <th scope="col">{t("strategy.strategyCard.tradesHeader.exitReason")}</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade, i) => (
                <TradeRow key={`${trade.entry_date}-${i}`} trade={trade} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function TradeRow({ trade }: { trade: Trade }) {
  const { t } = useT();
  const returnCls = trade.return_pct > 0 ? "pos" : trade.return_pct < 0 ? "neg" : "";
  return (
    <tr className={trade.open_at_end ? "report-trade-open" : ""}>
      <td>
        {trade.entry_date}
        <div className="bt-cell-sub">{trade.entry_price.toLocaleString()}</div>
      </td>
      <td>
        {trade.exit_date}
        <div className="bt-cell-sub">{trade.exit_price.toLocaleString()}</div>
      </td>
      <td className="num">{trade.bars_held.toLocaleString()}</td>
      <td className={`num edge-value ${returnCls}`}>{formatSignedRate(trade.return_pct)}</td>
      <td>
        {trade.exit_reason}
        {trade.open_at_end && (
          <span className="badge report-badge-open" title={t("strategy.strategyCard.openBadgeTitle")}>
            {t("strategy.strategyCard.openBadgeText")}
          </span>
        )}
      </td>
    </tr>
  );
}

/** Optional and additive: inline SVG only, no charting dependency. Strategy and buy-and-hold share
 *  one axis so the comparison this card is built around stays visible in the chart too. */
function EquityCurveChart({ curve }: { curve: EquityPoint[] }) {
  const { t } = useT();
  const width = 680;
  const height = 220;
  const padding = 10;

  const values = curve.flatMap((p) => [p.equity, p.buy_hold]).filter((v) => Number.isFinite(v));
  if (values.length === 0) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  const xStep = curve.length > 1 ? (width - padding * 2) / (curve.length - 1) : 0;
  const y = (v: number) => height - padding - ((v - min) / span) * (height - padding * 2);

  const strategyPoints = curve.map((p, i) => `${padding + i * xStep},${y(p.equity)}`).join(" ");
  const buyHoldPoints = curve.map((p, i) => `${padding + i * xStep},${y(p.buy_hold)}`).join(" ");

  return (
    <div className="report-equity-chart">
      <h3>{t("strategy.strategyCard.equityCurveHeading")}</h3>
      <div className="table-wrap">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="report-equity-svg"
          role="img"
          aria-label={t("strategy.strategyCard.equityChartAriaLabel")}
        >
          <polyline points={buyHoldPoints} className="report-equity-line report-equity-line-buyhold" />
          <polyline points={strategyPoints} className="report-equity-line report-equity-line-strategy" />
        </svg>
      </div>
      <div className="report-equity-legend">
        <span className="report-equity-legend-item">
          <span className="report-equity-swatch report-equity-swatch-strategy" />{" "}
          {t("strategy.strategyCard.header.strategy")}
        </span>
        <span className="report-equity-legend-item">
          <span className="report-equity-swatch report-equity-swatch-buyhold" />{" "}
          {t("strategy.strategyCard.header.buyHold")}
        </span>
      </div>
    </div>
  );
}
