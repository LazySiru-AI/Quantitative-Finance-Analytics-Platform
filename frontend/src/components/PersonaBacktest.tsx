/**
 * The SPY-benchmarked backtest lens (Phase 3a extension): did following this persona's dated calls,
 * over the SAME entry->exit windows, do any better than just holding the benchmark? Sits alongside
 * `PersonaScorecard.tsx` under the same persona on `/personas` -- where the scorecard measures the
 * calls in isolation, this measures them AGAINST a passive alternative.
 *
 * **Presentational only -- this component fetches nothing.** Whichever page wires this in owns
 * fetching `GET /{slug}/backtest`, the same split `PersonaScorecard.tsx`'s own docstring
 * establishes for `GET /{slug}/scorecard`. `state` is the discriminated union below rather than a
 * bare `PersonaBacktest | null`, so "still loading" / "the fetch actually failed" cannot be confused
 * with a loaded backtest.
 *
 * This file exists to enforce a small set of product guardrails, mirroring `PersonaScorecard.tsx`:
 *
 * 1. **A DESCRIPTIVE lens, never an alpha claim and never advice.** The caption at the top of every
 *    rendered state says so explicitly, naming the benchmark. Nothing here is phrased as "beat the
 *    market" or as a recommendation.
 * 2. **The backend's `caveat` string ALWAYS renders, never behind a disclosure.** Per
 *    `@/api/personas`'s docstring on `PersonaBacktest`, small samples over a single window are not
 *    evidence of skill -- that is the caveat's own point, and hiding it would defeat it.
 * 3. **Every `BenchmarkedHorizon` field that can be `null` is rendered distinctly from `0`.** All of
 *    `mean_return_pct`/`mean_benchmark_pct`/`excess_pct`/`win_rate_vs_benchmark` are `null` together
 *    when `n === 0` (no directional call had both a complete horizon and a benchmark window) -- an
 *    undefined comparison, not a zero one. `excess_ci` routes through the shared `StatValue`
 *    (`@/components/StatValue`), which already carries this discipline; the plain fields get the
 *    same explicit `null` check `PersonaScorecard.tsx` uses for `median_return_pct`.
 * 4. **`call_count: 0` / `horizons: []` is a valid, common empty state**, not an error -- a fresh
 *    persona with no scored calls yet still answers `200`. Rendered as an empty note, matching
 *    `PersonaScorecard.tsx`'s own `scored_calls: []` handling.
 * 5. **Non-empty `warnings` always render**, the same `.warning-list` treatment
 *    `PersonaScorecard.tsx` and `PersonaCard.tsx` give theirs -- never swallowed.
 * 6. **Excess/mean returns are colored by their own sign**, never by whether the persona "won" --
 *    same rule `PersonaScorecard.tsx` applies to `CallScore.return_pct`.
 *
 * **Internationalised** through `personaScorecard.backtest.*` (this feature's own shard). Numbers
 * stay in en-US formatting; each warning's backend `source`/`reason` renders verbatim; the backend
 * `caveat` string renders verbatim (it is server-authored copy, not a `MessageKey`); everything else
 * routes through `t()`.
 */
import {
  formatReturnPct,
  type BenchmarkedHorizon,
  type PersonaBacktest as Backtest,
} from "@/api/personas";
import { ScrollRegion } from "@/components/ScrollPanel";
import { StatValue } from "@/components/StatValue";
import { useT } from "@/i18n";

import "./PersonaBacktest.css";

/** Distinguishes "still loading" / "the fetch actually failed" from a loaded backtest -- see this
 * file's own docstring, matching `ScorecardFetchState`'s shape in `PersonaScorecard.tsx`. */
export type BacktestFetchState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "loaded"; backtest: Backtest };

export interface PersonaBacktestProps {
  displayName: string;
  state: BacktestFetchState;
}

export default function PersonaBacktest({ displayName, state }: PersonaBacktestProps) {
  const { t } = useT();
  const benchmark = state.phase === "loaded" ? state.backtest.benchmark : "SPY";

  return (
    <div className="panel persona-backtest">
      <h3 className="persona-card-subhead">{t("personaScorecard.backtest.heading")}</h3>
      <p className="muted persona-scorecard-caption">
        {t("personaScorecard.backtest.caption", { name: displayName, benchmark })}
      </p>

      <ScrollRegion size="md" label={t("personaScorecard.backtest.heading")}>
        {state.phase === "loading" && (
          <div className="placeholder persona-backtest-loading">
            {t("personaScorecard.backtest.loading")}
          </div>
        )}

        {state.phase === "error" && (
          <div className="callout callout-danger persona-backtest-error" role="alert">
            {state.message}
          </div>
        )}

        {state.phase === "loaded" && <BacktestBody backtest={state.backtest} />}
      </ScrollRegion>
    </div>
  );
}

function returnSignClass(value: number | null): string {
  if (value === null) return "persona-scorecard-return";
  return `persona-scorecard-return persona-scorecard-return-${value >= 0 ? "pos" : "neg"}`;
}

function BacktestBody({ backtest }: { backtest: Backtest }) {
  const { t } = useT();
  const { call_count, benchmark, horizons, caveat, warnings } = backtest;

  return (
    <div className="persona-scorecard-body">
      <p className="persona-scorecard-stat-value" data-testid="backtest-call-count">
        {t("personaScorecard.backtest.callCount", { count: call_count })}
      </p>

      {/* Rule 2: the caveat is ALWAYS visible, never behind a disclosure. */}
      <div className="callout callout-warn persona-backtest-caveat" data-testid="backtest-caveat">
        <strong>{t("personaScorecard.backtest.caveatLabel")}</strong> {caveat}
      </div>

      {warnings.length > 0 && (
        <ul className="warning-list persona-backtest-warnings">
          {warnings.map((w, i) => (
            <li key={i}>{`${w.source}: ${w.reason}`}</li>
          ))}
        </ul>
      )}

      {call_count === 0 || horizons.length === 0 ? (
        <p className="muted persona-scorecard-empty" data-testid="backtest-empty">
          {t("personaScorecard.backtest.empty", { benchmark })}
        </p>
      ) : (
        <ul className="persona-scorecard-list">
          {horizons.map((h) => (
            <BacktestHorizonRow key={h.days} horizon={h} benchmark={benchmark} />
          ))}
        </ul>
      )}
    </div>
  );
}

/** One fixed horizon's persona-vs-benchmark comparison. `excess_ci` (bootstrap interval on the
 * per-call excess over the benchmark) routes through `StatValue`; the plain mean/benchmark/win-rate
 * fields get their own explicit `null` guard rather than a fabricated `0%` -- rule 3 above. */
function BacktestHorizonRow({ horizon, benchmark }: { horizon: BenchmarkedHorizon; benchmark: string }) {
  const { t } = useT();
  // `excess_pct` (the plain point value) is intentionally not rendered on its own -- `excess_ci`
  // below carries the same point plus its bootstrap interval and `n`, which is strictly more
  // honest than a bare number for a per-call excess over the benchmark (see this file's rule 3).
  const { days, n, mean_return_pct, mean_benchmark_pct, win_rate_vs_benchmark, excess_ci } = horizon;

  return (
    <li className="persona-scorecard-row" data-testid={`backtest-row-${days}`}>
      <span className="persona-scorecard-stat-value">{t("personaScorecard.horizon.label", { days })}</span>
      <span className="persona-scorecard-said-on">{t("personaScorecard.backtest.sampleSize", { n })}</span>

      <div className="persona-scorecard-stat">
        <span className="persona-scorecard-stat-label">{t("personaScorecard.backtest.meanReturn")}</span>
        <span className={mean_return_pct === null ? "muted" : returnSignClass(mean_return_pct)}>
          {mean_return_pct === null ? t("personaScorecard.backtest.noData") : formatReturnPct(mean_return_pct)}
        </span>
      </div>

      <div className="persona-scorecard-stat">
        <span className="persona-scorecard-stat-label">
          {t("personaScorecard.backtest.meanBenchmark", { benchmark })}
        </span>
        <span className={mean_benchmark_pct === null ? "muted" : returnSignClass(mean_benchmark_pct)}>
          {mean_benchmark_pct === null
            ? t("personaScorecard.backtest.noData")
            : formatReturnPct(mean_benchmark_pct)}
        </span>
      </div>

      <div className="persona-scorecard-stat">
        <span className="persona-scorecard-stat-label">
          {t("personaScorecard.backtest.excessReturn", { benchmark })}
        </span>
        <StatValue estimate={excess_ci} format="percent" data-testid={`backtest-excess-ci-${days}`} />
      </div>

      <div className="persona-scorecard-stat">
        <span className="persona-scorecard-stat-label">
          {t("personaScorecard.backtest.winRate", { benchmark })}
        </span>
        <span className="persona-scorecard-stat-value">
          {win_rate_vs_benchmark === null
            ? t("personaScorecard.backtest.noData")
            : `${Math.round(win_rate_vs_benchmark * 100)}%`}
        </span>
      </div>
    </li>
  );
}
