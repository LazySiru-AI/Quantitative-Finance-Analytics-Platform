/**
 * All four timeframes at once: 5m, 1h, 1d, 1w in one view.
 *
 * The point is the comparison. A band touch on the daily means something different depending on
 * whether the weekly is trending or ranging, and flipping between tabs to check makes you hold the
 * other three in your head. Side by side, the relationship is the thing you read rather than
 * something you reconstruct.
 *
 * Each panel fetches independently and fails independently. A 5m series that has aged out of the
 * provider's 59-day window must not blank the weekly chart next to it, so every panel carries its
 * own phase, its own source label and its own placeholder.
 */
import { INTERVALS, type Interval } from "@/api/market";
import Chart from "@/components/Chart";
import { overlaysFor, type Overlay } from "@/components/overlays";
import { useChartSeries } from "@/hooks/useChartSeries";
import { useT } from "@/i18n";

const PANEL_HEIGHT = 260;

interface TimeframeGridProps {
  symbol: string;
  overlays: Overlay[];
}

export default function TimeframeGrid({ symbol, overlays }: TimeframeGridProps) {
  return (
    <div className="timeframe-grid">
      {INTERVALS.map((interval) => (
        <TimeframePanel key={interval} symbol={symbol} interval={interval} overlays={overlays} />
      ))}
    </div>
  );
}

function TimeframePanel({
  symbol,
  interval,
  overlays,
}: {
  symbol: string;
  interval: Interval;
  overlays: Overlay[];
}) {
  const { t } = useT();
  const state = useChartSeries(symbol, interval, overlays);
  const applicable = overlaysFor(overlays, interval);
  const dropped = overlays.length - applicable.length;

  return (
    <section className="timeframe-panel" aria-label={`${symbol} ${interval}`}>
      <header className="timeframe-panel-head">
        <span className="timeframe-panel-interval">{interval}</span>
        <span className="timeframe-panel-meta">
          {state.barsPhase === "loaded"
            ? t("strategy.backtest.underwaterBars", { count: state.bars.length.toLocaleString() })
            : ""}
          {state.source ? ` · ${state.source}` : ""}
        </span>
      </header>

      {/* Off the happy path (loading, an error, or a genuinely empty series) this panel has no
          `Chart` to size it, so it renders only a one-line `.placeholder` -- and without a floor on
          that branch, `.timeframe-grid`'s default `stretch` still equalises the ROW, but a row where
          every OTHER panel is also short (e.g. all four still loading) collapses to that one line
          instead of `PANEL_HEIGHT`, and the layout jumps again the moment a `Chart` lands. Pinning
          `minHeight` to the same `PANEL_HEIGHT` the `Chart` below is given keeps all four panels the
          same size in every phase, not just once data arrives. */}
      {state.barsPhase === "loading" && (
        <div
          className="placeholder timeframe-panel-placeholder"
          style={{ minHeight: PANEL_HEIGHT }}
        >
          {t("strategy.timeframeGrid.loading", { interval })}
        </div>
      )}
      {(state.barsPhase === "error" || state.barsPhase === "notfound") && (
        <div
          className="placeholder timeframe-panel-placeholder"
          style={{ minHeight: PANEL_HEIGHT }}
        >
          {state.barsMessage}
        </div>
      )}
      {state.barsPhase === "loaded" && state.bars.length === 0 && (
        <div
          className="placeholder timeframe-panel-placeholder"
          style={{ minHeight: PANEL_HEIGHT }}
        >
          {t("strategy.timeframeGrid.noBars", { interval })}
        </div>
      )}
      {state.barsPhase === "loaded" && state.bars.length > 0 && (
        <Chart
          bars={state.bars}
          series={state.tsInterval === state.barsInterval ? state.series : []}
          ts={state.tsInterval === state.barsInterval ? state.ts : []}
          colors={state.colors}
          interval={interval}
          height={PANEL_HEIGHT}
          compact
        />
      )}

      {/* Naming what was left out beats a panel that quietly draws one fewer line than its
          neighbour and gives no reason. */}
      {dropped > 0 && (
        <div className="timeframe-panel-note">
          {t(
            dropped === 1
              ? "strategy.timeframeGrid.overlaysNotDefined_one"
              : "strategy.timeframeGrid.overlaysNotDefined_other",
            { count: dropped, interval },
          )}
        </div>
      )}
      {state.warnings.length > 0 && (
        <div className="timeframe-panel-note warn">
          {state.warnings.map((w) => w.kind).join(" · ")}
        </div>
      )}
    </section>
  );
}
