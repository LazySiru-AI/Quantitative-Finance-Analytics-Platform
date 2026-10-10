/**
 * The decision table: one row per rule, each rule's current truth state plus historical evidence
 * across the four forward-return horizons.
 *
 * Four horizons times several statistics per horizon is too much to read at a glance, so the default
 * view shows one horizon as a compact row (20 bars -- 1 is dominated by same-bar noise, 60 starves
 * the independent sample through forward-window overlap, 20 is the middle ground), with a per-row
 * expander revealing the full breakdown across all four. Nothing is computed differently for the
 * compact view; every number is one click away, never hidden.
 *
 * Three rules from `api/rules.ts`'s module docstring drive most of the layout choices here: a hit
 * rate is never shown without its baseline (edge gets the visual weight, hit-rate/baseline sit small
 * underneath), `null` renders as an em dash rather than `0.0%`, and `state: "unknown"` is never
 * styled like `state: "false"`.
 */
import { useMemo, useState } from "react";

import type { Interval } from "@/api/market";
import {
  edgeOf,
  formatRate,
  formatSignedRate,
  HORIZONS,
  stateLabel,
  type DecisionRow,
  type Evidence,
  type Horizon,
  type MarketWarning,
  type RuleState,
  type Significance,
  type SignificanceCriteria,
  type TriState,
} from "@/api/rules";
import { useDecisionTable } from "@/hooks/useDecisionTable";
import { Trans, useT, type Translator } from "@/i18n";

const DEFAULT_HORIZON: Horizon = 20;
const COLUMN_COUNT = 8;

interface DecisionTableProps {
  symbol: string;
  interval: Interval;
}

export default function DecisionTable({ symbol, interval }: DecisionTableProps) {
  const { t } = useT();
  const { table, phase, message } = useDecisionTable(symbol, interval);
  const [horizon, setHorizon] = useState<Horizon>(DEFAULT_HORIZON);

  return (
    <div className="panel">
      <h2>{t("ticker.decision.heading")}</h2>

      {phase === "loading" && <div className="placeholder">{t("ticker.decision.loading")}</div>}
      {(phase === "notfound" || phase === "error") && <div className="placeholder">{message}</div>}

      {phase === "loaded" && table && (
        <>
          <div className="decision-meta">
            <span>
              <Trans
                k="ticker.decision.sampleRange"
                values={{
                  first: <strong>{table.first_bar ?? "—"}</strong>,
                  last: <strong>{table.last_bar ?? "—"}</strong>,
                }}
              />
            </span>
            <span>
              <Trans
                k="ticker.decision.barsEvaluated"
                values={{ count: <strong>{table.bars_evaluated.toLocaleString()}</strong> }}
              />
            </span>
          </div>

          <DecisionWarnings warnings={table.warnings} />

          <div
            className="decision-horizon-picker"
            role="tablist"
            aria-label={t("ticker.decision.horizonAriaLabel")}
          >
            <span className="decision-horizon-label">{t("ticker.decision.horizonLabel")}</span>
            {HORIZONS.map((h) => (
              <button
                key={h}
                type="button"
                role="tab"
                aria-selected={h === horizon}
                className={`timeframe-tab${h === horizon ? " active" : ""}`}
                onClick={() => setHorizon(h)}
              >
                {h}b
              </button>
            ))}
          </div>

          {table.rows.length === 0 ? (
            <div className="placeholder">{t("ticker.decision.noRules", { symbol, interval })}</div>
          ) : (
            <div className="table-wrap">
              <table
                className="data-table decision-table"
                aria-label={t("ticker.decision.tableAriaLabel", { symbol, interval, horizon })}
              >
                <thead>
                  <tr>
                    <th scope="col">{t("ticker.decision.col.rule")}</th>
                    <th scope="col">{t("ticker.decision.col.state")}</th>
                    <th scope="col">{t("ticker.decision.col.lastTrigger")}</th>
                    <th scope="col" className="num">
                      {t("ticker.decision.col.edge", { horizon })}
                    </th>
                    <th scope="col" className="num">
                      {t("ticker.decision.col.medianReturn", { horizon })}
                    </th>
                    <th scope="col" className="num">
                      {t("ticker.decision.col.sample")}
                    </th>
                    <th scope="col">{t("ticker.decision.col.significance")}</th>
                    <th scope="col">
                      <span className="visually-hidden">{t("ticker.decision.col.rowDetailsHidden")}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {table.rows.map((row) => (
                    <DecisionTableRow key={row.rule.rule_id} row={row} horizon={horizon} />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <SignificanceLegend criteria={table.criteria} />
        </>
      )}
    </div>
  );
}

function DecisionWarnings({ warnings }: { warnings: MarketWarning[] }) {
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

function DecisionTableRow({ row, horizon }: { row: DecisionRow; horizon: Horizon }) {
  const { t } = useT();
  const [expanded, setExpanded] = useState(false);
  const evidence = useMemo(
    () => row.evidence.find((e) => e.horizon === horizon),
    [row.evidence, horizon],
  );
  const detailId = `decision-detail-${row.rule.rule_id}`;

  return (
    <>
      <tr className={`decision-row${row.warnings.length > 0 ? " degraded" : ""}`}>
        <td className="rule-name-cell">
          <span className="rule-name" title={row.rule.description}>
            {row.rule.name}
          </span>
          <span className="rule-id">{row.rule.rule_id}</span>
          {row.warnings.length > 0 && (
            <span className="rule-row-warning">{row.warnings.map((w) => w.message).join(" · ")}</span>
          )}
        </td>
        <td>
          <StatePill state={row.state.state} />
        </td>
        <td>
          <LastTriggerCell state={row.state} />
        </td>
        <EdgeCell evidence={evidence} />
        <MedianCell evidence={evidence} />
        <SampleCell evidence={evidence} />
        <SignificanceCell evidence={evidence} />
        <td>
          <button
            type="button"
            className="decision-expand-btn"
            aria-expanded={expanded}
            aria-controls={detailId}
            aria-label={
              expanded
                ? t("ticker.decision.hideBreakdown", { rule: row.rule.name })
                : t("ticker.decision.showBreakdown", { rule: row.rule.name })
            }
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? t("ticker.decision.hideButton") : t("ticker.decision.allHorizonsButton")}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="decision-detail-row">
          <td colSpan={COLUMN_COUNT}>
            <DecisionRowDetail id={detailId} row={row} />
          </td>
        </tr>
      )}
    </>
  );
}

/**
 * What the Significance column's three words mean, in the numbers they are decided by.
 *
 * A UAT persona put it directly: the Scan page names its method (Benjamini–Hochberg) while this
 * table grades every rule "insufficient" with nothing stating the test or the threshold, so the
 * grade reads as an opinion rather than as a rule a reader can check a row against — and
 * "insufficient" on every row of a table is precisely the case where a reader most needs to know
 * whether that is a fact about their rules or about the sample.
 *
 * The numbers come from the response, not from this file: they live as constants in
 * `app.rules.evidence`, and a legend hard-coded here would be wrong the first time one moved.
 */
function SignificanceLegend({ criteria }: { criteria: SignificanceCriteria | null }) {
  const { t } = useT();
  if (criteria === null) return null;
  const pct = (edge: number) => t("ticker.decision.legend.points", { n: (edge * 100).toFixed(0) });

  return (
    <details className="significance-legend">
      <summary>{t("ticker.decision.legend.summary")}</summary>
      <p>
        <Trans
          k="ticker.decision.legend.intro"
          values={{
            insufficient: <strong>{t("ticker.decision.significance.insufficient")}</strong>,
            independent: <em>{t("ticker.decision.legend.independentWord")}</em>,
          }}
        />
      </p>
      <ul>
        <li>
          <Trans
            k="ticker.decision.legend.suggestiveItem"
            values={{
              label: <strong>{t("ticker.decision.significance.suggestive")}</strong>,
              n: criteria.suggestive_min_independent,
              and: <em>{t("ticker.decision.legend.and")}</em>,
              edge: pct(criteria.suggestive_min_edge),
            }}
          />
        </li>
        <li>
          <Trans
            k="ticker.decision.legend.weakItem"
            values={{
              label: <strong>{t("ticker.decision.significance.weak")}</strong>,
              n: criteria.weak_min_independent,
              and: <em>{t("ticker.decision.legend.and")}</em>,
              edge: pct(criteria.weak_min_edge),
            }}
          />
        </li>
        <li>
          <Trans
            k="ticker.decision.legend.insufficientItem"
            values={{ label: <strong>{t("ticker.decision.significance.insufficient")}</strong> }}
          />
        </li>
      </ul>
      <p className="muted">
        <Trans
          k="ticker.decision.legend.footer"
          values={{ howOften: <em>{t("ticker.decision.legend.howOften")}</em> }}
        />
      </p>
    </details>
  );
}

function StatePill({ state }: { state: TriState }) {
  return <span className={`state-pill state-${state}`}>{stateLabel(state)}</span>;
}

/** `null` means the rule never fired in stored history -- distinct from "fired long ago", which is
 *  why it renders as text, not the em dash used for unmeasurable statistics. */
function LastTriggerCell({ state }: { state: RuleState }) {
  const { t } = useT();
  if (state.last_trigger === null) {
    return <span className="never-fired">{t("ticker.decision.neverFired")}</span>;
  }
  return (
    <span className="last-trigger">
      <span className="last-trigger-ts">{state.last_trigger.replace("T", " ")}</span>
      {state.bars_since_trigger !== null && (
        <span className="last-trigger-bars">
          {t("ticker.barsAgo", { count: state.bars_since_trigger.toLocaleString() })}
        </span>
      )}
    </span>
  );
}

/** The edge -- hit rate minus baseline -- carries the visual weight. The raw hit rate and its
 *  baseline sit underneath, small and muted: present, but never competing with the number that
 *  actually means something. */
function EdgeCell({ evidence }: { evidence: Evidence | undefined }) {
  const { t } = useT();
  if (!evidence) {
    return <td className="num edge-cell">—</td>;
  }
  const edge = edgeOf(evidence);
  const cls = edge === null ? "" : edge > 0 ? "pos" : edge < 0 ? "neg" : "";
  const provisional = evidence.significance === "insufficient" ? " evidence-provisional" : "";
  return (
    <td className={`num edge-cell${provisional}`}>
      <div className={`edge-value ${cls}`}>{formatSignedRate(edge)}</div>
      <div className="edge-baseline">
        {t("ticker.decision.edge.vsBase", {
          hit: formatRate(evidence.hit_rate),
          base: formatRate(evidence.baseline_hit_rate),
        })}
      </div>
      {evidence.entry === "same_close" && (
        <div className="entry-tag" title={t("ticker.decision.edge.upperBoundTitle")}>
          {t("ticker.decision.edge.upperBoundTag")}
        </div>
      )}
    </td>
  );
}

function MedianCell({ evidence }: { evidence: Evidence | undefined }) {
  const { t } = useT();
  if (!evidence) {
    return <td className="num median-cell">—</td>;
  }
  const provisional = evidence.significance === "insufficient" ? " evidence-provisional" : "";
  return (
    <td className={`num median-cell${provisional}`}>
      <div className="median-value">{formatSignedRate(evidence.median_return)}</div>
      <div className="median-baseline">
        {t("ticker.decision.median.base", { value: formatSignedRate(evidence.baseline_median_return) })}
      </div>
    </td>
  );
}

function SampleCell({ evidence }: { evidence: Evidence | undefined }) {
  const { t } = useT();
  if (!evidence) {
    return <td className="num sample-cell">—</td>;
  }
  return (
    <td className="num sample-cell">
      {t("ticker.decision.sample.indepSuffix", {
        sample: evidence.sample_size.toLocaleString(),
        indep: evidence.independent_sample_size.toLocaleString(),
      })}
    </td>
  );
}

function SignificanceCell({ evidence }: { evidence: Evidence | undefined }) {
  if (!evidence) {
    return <td>—</td>;
  }
  return (
    <td>
      <SignificanceBadge significance={evidence.significance} />
    </td>
  );
}

function significanceLabel(t: Translator, significance: Significance): string {
  if (significance === "suggestive") return t("ticker.decision.significance.suggestive");
  if (significance === "weak") return t("ticker.decision.significance.weak");
  return t("ticker.decision.significance.insufficient");
}

/** `suggestive` means "worth opening the backtest workbench", never "significant" -- the label text
 *  itself says exactly that and nothing stronger. */
function SignificanceBadge({ significance }: { significance: Significance }) {
  const { t } = useT();
  return <span className={`significance-badge ${significance}`}>{significanceLabel(t, significance)}</span>;
}

function DecisionRowDetail({ id, row }: { id: string; row: DecisionRow }) {
  const { t } = useT();
  return (
    <table className="decision-detail-table" id={id}>
      <caption className="visually-hidden">
        {t("ticker.decision.detail.caption", { rule: row.rule.name })}
      </caption>
      <thead>
        <tr>
          <th scope="col">{t("ticker.decision.horizonLabel")}</th>
          <th scope="col">{t("ticker.decision.detail.col.entry")}</th>
          <th scope="col">{t("ticker.decision.detail.col.edge")}</th>
          <th scope="col">{t("ticker.decision.detail.col.hitRateBase")}</th>
          <th scope="col">{t("ticker.decision.detail.col.medianBase")}</th>
          <th scope="col">{t("ticker.decision.detail.col.sampleIndep")}</th>
          <th scope="col">{t("ticker.decision.col.significance")}</th>
        </tr>
      </thead>
      <tbody>
        {HORIZONS.map((h) => {
          const evidence = row.evidence.find((e) => e.horizon === h);
          if (!evidence) {
            return (
              <tr key={h}>
                <td>{h}b</td>
                <td colSpan={6}>{t("ticker.decision.detail.notEvaluated")}</td>
              </tr>
            );
          }
          const edge = edgeOf(evidence);
          return (
            <tr key={h}>
              <td>{h}b</td>
              <td>
                {evidence.entry === "same_close"
                  ? t("ticker.decision.entry.sameClose")
                  : t("ticker.decision.entry.nextOpen")}
              </td>
              <td>{formatSignedRate(edge)}</td>
              <td>
                {formatRate(evidence.hit_rate)} / {formatRate(evidence.baseline_hit_rate)}
              </td>
              <td>
                {formatSignedRate(evidence.median_return)} /{" "}
                {formatSignedRate(evidence.baseline_median_return)}
              </td>
              <td>
                {evidence.sample_size.toLocaleString()} / {evidence.independent_sample_size.toLocaleString()}
              </td>
              <td>
                <SignificanceBadge significance={evidence.significance} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
