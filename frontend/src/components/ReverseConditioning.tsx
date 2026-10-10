/**
 * Reverse conditioning: what the indicators were doing before the biggest moves.
 *
 * **This component deliberately does not look like the event study**, and that is the requirement,
 * not a style preference. The moves here were selected by looking at their forward return, so every
 * number is a description of the sample rather than a test of a hypothesis about it. Rendered in the
 * same table shell as a confirmatory result, it would read as one.
 *
 * So: no hit rate, no p-value, no q-value, no edge column — the contract type does not carry those
 * fields, and nothing here computes a substitute from the counts. What it shows instead is a shift:
 * where an indicator sat before the selected moves, against where it usually sits, in units of its
 * own spread.
 *
 * `selected_count` against `independent_selected_count` is given prominence because top-decile moves
 * cluster hard — they are mostly consecutive bars inside a handful of episodes — and the raw count
 * routinely overstates the number of distinct events by several times.
 */

import { useState } from "react";

import type { IndicatorProfile, Interval, ReverseConditioning as Reverse } from "@/api/backtest";
import StatGrid from "@/components/StatGrid";
import { useReverseConditioning } from "@/hooks/useBacktest";
import { Trans, useT } from "@/i18n";

interface ReverseConditioningProps {
  symbol: string;
  interval: Interval;
}

export default function ReverseConditioningPanel({ symbol, interval }: ReverseConditioningProps) {
  const { t } = useT();
  const [horizon, setHorizon] = useState(20);
  const [quantile, setQuantile] = useState(0.9);
  const [lookback, setLookback] = useState(3);
  const { reverse, phase, message, run } = useReverseConditioning();

  return (
    <div className="panel bt-exploratory">
      <div className="bt-exploratory-banner">
        <span className="badge bt-badge-exploratory">{t("strategy.reverse.exploratoryBadge")}</span>
        <span>{t("strategy.reverse.banner")}</span>
      </div>

      <h2 className="section-heading">{t("strategy.reverse.title")}</h2>
      <p className="subtitle">{t("strategy.reverse.subtitle")}</p>

      <div className="bt-scan-controls">
        <label className="bt-control-label" htmlFor="rev-horizon">
          {t("strategy.reverse.moveMeasuredLabel")}
          <select
            id="rev-horizon"
            className="bt-entry-select"
            value={horizon}
            onChange={(e) => setHorizon(Number(e.target.value))}
          >
            {[5, 10, 20, 60].map((h) => (
              <option key={h} value={h}>
                {t("strategy.backtest.underwaterBars", { count: h })}
              </option>
            ))}
          </select>
        </label>
        <label className="bt-control-label" htmlFor="rev-quantile">
          {t("strategy.reverse.selectTopLabel")}
          <select
            id="rev-quantile"
            className="bt-entry-select"
            value={quantile}
            onChange={(e) => setQuantile(Number(e.target.value))}
          >
            <option value={0.95}>5%</option>
            <option value={0.9}>{t("strategy.reverse.decileOption")}</option>
            <option value={0.8}>{t("strategy.reverse.quintileOption")}</option>
          </select>
        </label>
        <label className="bt-control-label" htmlFor="rev-lookback">
          {t("strategy.reverse.profilePriorLabel")}
          <select
            id="rev-lookback"
            className="bt-entry-select"
            value={lookback}
            onChange={(e) => setLookback(Number(e.target.value))}
          >
            {[0, 1, 3, 5, 10].map((l) => (
              <option key={l} value={l}>
                {l === 0
                  ? t("strategy.reverse.signalBarOnly")
                  : t("strategy.backtest.underwaterBars", { count: l })}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="symbol-submit"
          disabled={phase === "loading"}
          onClick={() => run({ symbol, interval, horizon, quantile, lookback })}
        >
          {phase === "loading" ? t("strategy.reverse.profilingButton") : t("strategy.reverse.profileButton")}
        </button>
      </div>

      {phase === "error" && <div className="callout callout-danger">{message}</div>}
      {reverse && <ReverseResult reverse={reverse} />}
    </div>
  );
}

function ReverseResult({ reverse }: { reverse: Reverse }) {
  const { t } = useT();
  const overstatement =
    reverse.independent_selected_count > 0
      ? reverse.selected_count / reverse.independent_selected_count
      : null;

  return (
    <div className="bt-reverse-result">
      <StatGrid
        items={[
          { label: t("strategy.reverse.stat.barsSelected"), value: reverse.selected_count.toLocaleString() },
          {
            label: t("strategy.reverse.stat.distinctEpisodes"),
            value: (
              <span className="bt-independent-emphasis">
                {reverse.independent_selected_count.toLocaleString()}
              </span>
            ),
          },
          {
            label: t("strategy.reverse.stat.moveHorizon"),
            value: t("strategy.backtest.underwaterBars", { count: reverse.horizon }),
          },
          {
            label: t("strategy.reverse.stat.priorWindow"),
            value:
              reverse.lookback === 0
                ? t("strategy.reverse.signalBar")
                : t("strategy.backtest.underwaterBars", { count: reverse.lookback }),
          },
        ]}
      />

      {overstatement !== null && overstatement >= 1.5 && (
        <div className="callout callout-warn">
          {t("strategy.reverse.overstatementWarning", {
            selected: reverse.selected_count.toLocaleString(),
            independent: reverse.independent_selected_count.toLocaleString(),
            factor: overstatement.toFixed(1),
          })}
        </div>
      )}

      {reverse.warnings.length > 0 && (
        <ul className="warning-list">
          {reverse.warnings.map((w, i) => (
            <li key={`${w.kind}-${i}`}>{w.message}</li>
          ))}
        </ul>
      )}

      {reverse.profiles.length === 0 ? (
        <p className="placeholder">{t("strategy.reverse.noProfiles")}</p>
      ) : (
        <div className="table-wrap">
          <table className="data-table bt-reverse-table">
            <thead>
              <tr>
                <th>{t("strategy.reverse.header.indicator")}</th>
                <th className="num">{t("strategy.reverse.header.beforeMove")}</th>
                <th className="num">{t("strategy.reverse.header.usually")}</th>
                <th className="num">{t("strategy.reverse.header.shift")}</th>
              </tr>
            </thead>
            <tbody>
              {reverse.profiles.map((profile) => (
                <ProfileRow key={profile.column} profile={profile} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {reverse.run_id && (
        <p className="bt-run-id">
          <Trans k="strategy.scan.recordedAsRun" values={{ runId: <code>{reverse.run_id.slice(0, 16)}</code> }} />
        </p>
      )}
    </div>
  );
}

function fmt(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return Math.abs(value) >= 100 ? value.toFixed(0) : value.toFixed(2);
}

function ProfileRow({ profile }: { profile: IndicatorProfile }) {
  const { t } = useT();
  const sep = profile.separation;
  return (
    <tr>
      <td>
        <div>{profile.column}</div>
        <div className="bt-cell-sub">{profile.spec}</div>
      </td>
      <td className="num">
        <div>{fmt(profile.selected.median)}</div>
        <div className="bt-cell-sub">
          p25 {fmt(profile.selected.p25)} · p75 {fmt(profile.selected.p75)}
        </div>
      </td>
      <td className="num">
        <div>{fmt(profile.baseline.median)}</div>
        <div className="bt-cell-sub">
          p25 {fmt(profile.baseline.p25)} · p75 {fmt(profile.baseline.p75)}
        </div>
      </td>
      <td className="num">
        {sep === null ? (
          <span className="bt-cell-sub" title={t("strategy.reverse.noSpreadTitle")}>
            {t("strategy.reverse.noSpread")}
          </span>
        ) : (
          <>
            <div className={`edge-value ${sep > 0 ? "pos" : sep < 0 ? "neg" : ""}`}>
              {sep > 0 ? "+" : ""}
              {sep.toFixed(2)}
            </div>
            <div className="bt-cell-sub">
              {sep > 0 ? t("strategy.reverse.iqrsHigher") : t("strategy.reverse.iqrsLower")}
            </div>
          </>
        )}
      </td>
    </tr>
  );
}
