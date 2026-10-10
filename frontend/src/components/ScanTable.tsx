/**
 * The guarded scan: many conditions tested at once, with the cost of having tested many in plain
 * sight.
 *
 * Two rendering rules from the contract drive everything here.
 *
 * **The trial count sits next to the results, not in a footnote.** `trials` is the denominator every
 * q-value on this table depends on. Four discoveries out of eighty tests is a different fact from
 * four discoveries, and a reader who has to scroll to learn which one they are looking at has been
 * shown the wrong number.
 *
 * **`discovery` is not "true".** It means `q <= alpha` — an expected-false-discovery-rate statement
 * about the whole set. At the default alpha of 0.10, roughly one in ten flagged rows is expected to
 * be noise, and the badge says so rather than leaving the reader to supply that themselves.
 *
 * Showing p and q side by side is the third thing: the correction is only credible if you can see
 * it working. A row at p = 0.04 and q = 1.00 is the whole argument for the machinery.
 */

import { useMemo, useState } from "react";

import { useRuleValidation } from "@/hooks/useRuleValidation";

import {
  formatQ,
  guardStatusLabel,
  isSmallSample,
  type Interval,
  type ScanEntry,
  type ScanResult,
} from "@/api/backtest";
import { formatRate, formatSignedRate, type RuleValidation } from "@/api/rules";
import StatGrid from "@/components/StatGrid";
import { useScan } from "@/hooks/useBacktest";
import { Trans, useT } from "@/i18n";

const DEFAULT_EXPRESSIONS = [
  "close < bb_lower(20,2)",
  "close > bb_upper(20,2)",
  "rsi(14) < 30",
  "rsi(14) > 70",
  "ema(50) crosses_above ema(200)",
  "close > sma(200)",
].join("\n");

const DEFAULT_HORIZONS = "5, 20, 60";

interface ScanTableProps {
  symbol: string;
  interval: Interval;
}

export default function ScanTable({ symbol, interval }: ScanTableProps) {
  const { t } = useT();
  const [text, setText] = useState(DEFAULT_EXPRESSIONS);
  const [horizonText, setHorizonText] = useState(DEFAULT_HORIZONS);
  const [alpha, setAlpha] = useState(0.1);
  const { scan, phase, message, run } = useScan();

  const expressions = useMemo(
    () =>
      text
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line.length > 0),
    [text],
  );

  const horizons = useMemo(
    () =>
      horizonText
        .split(",")
        .map((part) => Number.parseInt(part.trim(), 10))
        .filter((n) => Number.isFinite(n) && n > 0),
    [horizonText],
  );

  const validation = useRuleValidation(expressions);
  const plannedTrials = expressions.length * horizons.length;

  // Reported by line number against the textarea the reader is looking at, not by expression text:
  // with six expressions in one box, "close >>> sma( is invalid" makes them find it themselves.
  const invalidLines = text
    .split("\n")
    .map((line, index) => ({ line: index + 1, result: validation.resultFor(line) }))
    .filter((entry): entry is { line: number; result: RuleValidation } => entry.result?.valid === false);

  const plannedKey =
    expressions.length === 1
      ? horizons.length === 1
        ? "strategy.scan.planned_1_1"
        : "strategy.scan.planned_1_n"
      : horizons.length === 1
        ? "strategy.scan.planned_n_1"
        : "strategy.scan.planned_n_n";

  return (
    <div className="panel">
      <h2 className="section-heading">{t("strategy.scan.title")}</h2>
      <p className="subtitle">{t("strategy.scan.subtitle")}</p>

      <div className="bt-scan-form">
        <label className="bt-control-label" htmlFor="scan-expressions">
          {t("strategy.scan.expressionsLabel")}
        </label>
        <textarea
          id="scan-expressions"
          className="bt-scan-input"
          rows={6}
          spellCheck={false}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />

        <div className="bt-scan-controls">
          <label className="bt-control-label" htmlFor="scan-horizons">
            {t("strategy.scan.horizonsLabel")}
            <input
              id="scan-horizons"
              className="bt-entry-select"
              value={horizonText}
              onChange={(e) => setHorizonText(e.target.value)}
            />
          </label>
          <label className="bt-control-label" htmlFor="scan-alpha">
            {t("strategy.scan.alphaLabel")}
            <select
              id="scan-alpha"
              className="bt-entry-select"
              value={alpha}
              onChange={(e) => setAlpha(Number(e.target.value))}
            >
              <option value={0.05}>0.05</option>
              <option value={0.1}>0.10</option>
              <option value={0.2}>0.20</option>
            </select>
          </label>
          <button
            type="button"
            className="symbol-submit"
            disabled={
              phase === "loading" ||
              expressions.length === 0 ||
              horizons.length === 0 ||
              // Never gated on `checking`/`unavailable` -- see `useRuleValidation`. A scan is the one
              // operation here that manufactures discoveries out of nothing, so spending its trial
              // budget on an expression that cannot parse is worse than the usual wasted run.
              invalidLines.length > 0
            }
            onClick={() => run({ symbol, interval, expressions, horizons, alpha })}
          >
            {phase === "loading"
              ? t("strategy.scan.scanningButton")
              : t("strategy.scan.runTestsButton", { count: plannedTrials })}
          </button>
        </div>
        {invalidLines.length > 0 && (
          <div className="rule-editor-result invalid" aria-live="polite">
            <span className="rule-editor-verdict invalid">
              {invalidLines.length === 1
                ? t("strategy.scan.invalidLines_one", { line: invalidLines[0]!.line })
                : t("strategy.scan.invalidLines_other", { count: invalidLines.length })}
            </span>
            <ul className="bt-scan-invalid-list">
              {invalidLines.map(({ line, result }) => (
                <li key={line} className="rule-editor-parse-error">
                  <strong>{t("strategy.scan.lineLabel", { line })}</strong>{" "}
                  {result.error ?? t("strategy.ruleEditor.parserRejected")}
                </li>
              ))}
            </ul>
          </div>
        )}
        <p className="bt-scan-planned">
          <Trans
            k={plannedKey}
            values={{
              exprCount: expressions.length,
              horizonCount: horizons.length,
              total: <strong>{plannedTrials}</strong>,
            }}
          />
        </p>
      </div>

      {phase === "error" && <div className="callout callout-danger">{message}</div>}
      {scan && <ScanResultView result={scan} />}
    </div>
  );
}

function ScanResultView({ result }: { result: ScanResult }) {
  const { t } = useT();
  const untestable = result.entries.filter((e) => e.p_value === null).length;
  const rawAt05 = result.entries.filter(
    (e) => e.p_value !== null && e.p_value <= 0.05,
  ).length;

  const sorted = useMemo(
    () =>
      [...result.entries].sort((a, b) => {
        if (a.p_value === null && b.p_value === null) return 0;
        if (a.p_value === null) return 1;
        if (b.p_value === null) return -1;
        return a.p_value - b.p_value;
      }),
    [result.entries],
  );

  return (
    <div className="bt-scan-result">
      <StatGrid
        items={[
          { label: t("strategy.scan.stat.trials"), value: String(result.trials) },
          { label: t("strategy.scan.stat.discoveries"), value: String(result.discoveries) },
          { label: t("strategy.scan.stat.uncorrectedP05"), value: String(rawAt05) },
          { label: t("strategy.scan.stat.untestable"), value: String(untestable) },
          { label: t("strategy.scan.stat.targetFdr"), value: result.alpha.toFixed(2) },
          { label: t("strategy.scan.stat.bars"), value: result.bars.toLocaleString() },
        ]}
      />

      <p className="bt-scan-reading">
        {result.discoveries === 0 ? (
          <>
            {t("strategy.scan.reading.zeroDiscoveries", { trials: result.trials })}
            {rawAt05 > 0 && (
              <>
                {" "}
                {t(rawAt05 === 1 ? "strategy.scan.reading.rawAt05_one" : "strategy.scan.reading.rawAt05_other", {
                  count: rawAt05,
                  trials: result.trials,
                })}
              </>
            )}
          </>
        ) : (
          t("strategy.scan.reading.discoveries", {
            discoveries: result.discoveries,
            trials: result.trials,
            alpha: result.alpha.toFixed(2),
            percent: Math.round(result.alpha * 100),
          })
        )}
      </p>

      <div className="table-wrap">
        <table className="data-table bt-scan-table">
          <thead>
            <tr>
              <th>{t("strategy.scan.header.expression")}</th>
              <th className="num">{t("strategy.scan.header.horizon")}</th>
              <th className="num">{t("strategy.scan.header.edge")}</th>
              <th className="num">{t("strategy.scan.header.indepN")}</th>
              <th className="num">{t("strategy.scan.header.p")}</th>
              <th className="num">{t("strategy.scan.header.q")}</th>
              <th>{t("strategy.scan.header.verdict")}</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((entry, i) => (
              <ScanRow key={`${entry.expression}-${entry.horizon}-${i}`} entry={entry} />
            ))}
          </tbody>
        </table>
      </div>

      {result.run_id && (
        <p className="bt-run-id">
          <Trans k="strategy.scan.recordedAsRun" values={{ runId: <code>{result.run_id.slice(0, 16)}</code> }} />
        </p>
      )}
    </div>
  );
}

function ScanRow({ entry }: { entry: ScanEntry }) {
  const { t } = useT();
  const stats = entry.stats;
  const guardFailed = entry.guard.status !== "passed";
  const edge =
    stats === null || stats.hit_rate === null || stats.baseline_hit_rate === null
      ? null
      : stats.hit_rate - stats.baseline_hit_rate;
  const small = stats !== null && isSmallSample(stats);

  return (
    <tr className={entry.discovery ? "bt-row-discovery" : small ? "bt-row-small-sample" : ""}>
      <td className="bt-arm-expression">{entry.expression}</td>
      <td className="num">{entry.horizon}b</td>
      <td className="num">
        {edge === null ? (
          "—"
        ) : (
          <>
            <div className={`edge-value ${edge > 0 ? "pos" : edge < 0 ? "neg" : ""}`}>
              {formatSignedRate(edge)}
            </div>
            <div className="bt-cell-sub">
              <Trans
                k="strategy.scan.hitRateVsBaseline"
                values={{
                  hit: formatRate(stats?.hit_rate ?? null),
                  baseline: formatRate(stats?.baseline_hit_rate ?? null),
                }}
              />
            </div>
          </>
        )}
      </td>
      <td className="num">
        {stats === null ? "—" : stats.independent_sample_size.toLocaleString()}
        {small && <div className="badge small-sample">{t("strategy.backtest.smallSampleBadge")}</div>}
      </td>
      <td className="num">{entry.p_value === null ? "—" : entry.p_value.toFixed(4)}</td>
      <td className="num">{formatQ(entry.q_value)}</td>
      <td>
        {guardFailed ? (
          <span className="badge bt-badge-guard" title={entry.guard.findings[0]?.detail ?? ""}>
            {t("strategy.scan.guardBadge", { status: guardStatusLabel(entry.guard.status) })}
          </span>
        ) : entry.discovery ? (
          <span className="badge bt-badge-discovery" title={t("strategy.scan.discoveryBadgeTitle")}>
            {t("strategy.scan.survivesCorrection")}
          </span>
        ) : entry.p_value === null ? (
          <span className="badge none">{t("strategy.scan.notTestable")}</span>
        ) : (
          <span className="badge none">{t("strategy.scan.no")}</span>
        )}
      </td>
    </tr>
  );
}
