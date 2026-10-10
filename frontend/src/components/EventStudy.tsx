/**
 * Forward-return event study: one condition (arm 0, the base), optionally a second arm to compare
 * against it.
 *
 * Three rules drive the layout. First, `api/rules.ts`'s "never show a hit rate without its
 * baseline" — the edge (`edgeOfStats`) gets the visual weight, hit-rate/baseline sit small
 * underneath, same treatment as `DecisionTable`'s `EdgeCell`. Second, `independent_sample_size` gets
 * prominence over the raw `sample_size` — it is the number significance actually rests on, and the
 * distribution spread (p05..p95) sits next to it rather than a mean, since these samples are skewed.
 * Third, and specific to this component: `ArmDelta` renders `hit_rate_delta` and
 * `sample_size_delta`/`independent_sample_size_delta` *together*, and a positive hit-rate delta on a
 * shrinking independent sample gets an explicit caution line — per the contract's own example, a
 * 12-point gain on a sample that fell from 140 to 9 must not read as an improvement.
 *
 * `guardOk(guard)` gates every set of numbers per arm: `"failed"` or `"unverified"` renders the
 * guard findings and nothing else, `"unverified"` styled identically to `"failed"` (a problem, not a
 * pending state) via the shared `.callout-danger` treatment.
 */
import { useState } from "react";

import RuleValidationNote from "@/components/RuleValidationNote";
import { useRuleValidation } from "@/hooks/useRuleValidation";

import {
  edgeOfStats,
  guardOk,
  isSmallSample,
  SMALL_SAMPLE_THRESHOLD,
  STUDY_HORIZONS,
  type ArmDelta,
  type ConditionArm,
  type Entry,
  type EventStudy as EventStudyResult,
  type GuardReport,
  type HorizonStats,
} from "@/api/backtest";
import { PLACEHOLDER_EXPRESSION } from "@/components/RuleEditor";
import { formatRate, formatSignedRate } from "@/api/rules";
import type { Interval, MarketWarning } from "@/api/market";
import { useEventStudy } from "@/hooks/useBacktest";
import { Trans, useT } from "@/i18n";

const MAX_ARMS = 2;

interface EventStudyProps {
  symbol: string;
  interval: Interval;
}

export default function EventStudy({ symbol, interval }: EventStudyProps) {
  const { t } = useT();
  const [arms, setArms] = useState<string[]>([""]);
  const [entry, setEntry] = useState<Entry>("next_open");
  const { study, phase, message, run } = useEventStudy();

  const addArm = () => {
    if (arms.length >= MAX_ARMS) return;
    setArms((prev) => [...prev, ""]);
  };
  const removeArm = (index: number) => {
    setArms((prev) => prev.filter((_, i) => i !== index));
  };
  const updateArm = (index: number, value: string) => {
    setArms((prev) => prev.map((a, i) => (i === index ? value : a)));
  };

  const conditions = arms.map((a) => a.trim()).filter((a) => a.length > 0);
  const validation = useRuleValidation(conditions);
  // Gated on `invalid`, never on `checking` or `unavailable`: a validate call that is merely slow, or
  // an endpoint that is down, must not take the run button away. See `useRuleValidation`'s docstring.
  const canSubmit = conditions.length > 0 && validation.invalid.length === 0;

  const submit = () => {
    if (!canSubmit) return;
    run({
      symbol,
      interval,
      conditions,
      horizons: [...STUDY_HORIZONS],
      entry,
    });
  };

  return (
    <div className="panel">
      <h2>{t("strategy.eventStudy.title")}</h2>

      <form
        className="bt-event-study-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        {arms.map((value, i) => (
          <div className="bt-arm-input-row" key={i}>
            <label className="rule-editor-label" htmlFor={`bt-arm-${i}`}>
              {i === 0
                ? t("strategy.eventStudy.conditionBase")
                : t("strategy.eventStudy.conditionArmB")}
            </label>
            <div className="bt-arm-input-controls">
              <input
                id={`bt-arm-${i}`}
                className="rule-editor-input"
                value={value}
                onChange={(e) => updateArm(i, e.target.value)}
                placeholder={t("strategy.ruleEditor.placeholderExample", {
                  expression: PLACEHOLDER_EXPRESSION,
                })}
                spellCheck={false}
                autoComplete="off"
                aria-describedby={`bt-arm-${i}-validity`}
              />
              {i > 0 && (
                <button type="button" className="bt-arm-remove" onClick={() => removeArm(i)}>
                  {t("strategy.eventStudy.removeArm")}
                </button>
              )}
            </div>
            <RuleValidationNote id={`bt-arm-${i}-validity`} result={validation.resultFor(value)} />
          </div>
        ))}

        <div className="bt-event-study-controls">
          {arms.length < MAX_ARMS && (
            <button type="button" className="decision-expand-btn" onClick={addArm}>
              {t("strategy.eventStudy.addSecondArm")}
            </button>
          )}

          <label className="bt-entry-select">
            <span className="rule-editor-label">{t("strategy.eventStudy.entryLabel")}</span>
            <select value={entry} onChange={(e) => setEntry(e.target.value as Entry)}>
              <option value="next_open">{t("strategy.eventStudy.entryNextOpen")}</option>
              <option value="same_close">{t("strategy.eventStudy.entrySameClose")}</option>
            </select>
          </label>

          <button type="submit" className="symbol-submit" disabled={!canSubmit}>
            {t("strategy.eventStudy.runButton")}
          </button>
        </div>
      </form>

      {phase === "idle" && (
        <div className="placeholder">{t("strategy.eventStudy.idlePlaceholder")}</div>
      )}
      {phase === "loading" && (
        <div className="placeholder">{t("strategy.eventStudy.runningPlaceholder")}</div>
      )}
      {(phase === "notfound" || phase === "error") && <div className="placeholder">{message}</div>}

      {phase === "loaded" && study && <EventStudyResultView study={study} />}
    </div>
  );
}

function EventStudyResultView({ study }: { study: EventStudyResult }) {
  return (
    <div className="bt-event-study-result">
      <div className="bt-event-study-meta">
        <Trans
          k="strategy.eventStudy.sampleMeta"
          values={{
            first: <strong>{study.first_bar ?? "—"}</strong>,
            last: <strong>{study.last_bar ?? "—"}</strong>,
            bars: study.bars.toLocaleString(),
          }}
        />
      </div>

      <EventStudyWarnings warnings={study.warnings} />

      {study.arms.map((arm, i) => (
        <ArmPanel key={`${arm.expression}-${i}`} arm={arm} index={i} />
      ))}

      {study.arms.length > 1 && <DeltaPanel deltas={study.deltas} />}
    </div>
  );
}

function EventStudyWarnings({ warnings }: { warnings: MarketWarning[] }) {
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

function ArmPanel({ arm, index }: { arm: ConditionArm; index: number }) {
  const { t } = useT();
  const ok = guardOk(arm.guard);
  return (
    <div className={`bt-arm-card${index === 0 ? " bt-arm-base" : ""}`}>
      <div className="bt-arm-head">
        <h3>
          {index === 0
            ? t("strategy.eventStudy.baseConditionHeading")
            : t("strategy.eventStudy.armBHeading")}
        </h3>
        <code className="bt-arm-expression">{arm.expression}</code>
      </div>
      <div className="bt-arm-meta">
        <Trans
          k="strategy.eventStudy.armMeta"
          values={{
            triggers: arm.triggers.toLocaleString(),
            evaluable: arm.evaluable_bars.toLocaleString(),
          }}
        />
        {arm.trigger_dates.length !== arm.triggers && (
          <span>
            {" "}
            <Trans
              k="strategy.eventStudy.totalFires"
              values={{ count: arm.trigger_dates.length.toLocaleString() }}
            />
          </span>
        )}
      </div>

      <ArmPanelWarnings warnings={arm.warnings} />
      <GuardStatusBlock guard={arm.guard} />

      {ok && arm.stats.length === 0 && (
        <div className="placeholder">{t("strategy.eventStudy.noHorizonStats")}</div>
      )}

      {ok && arm.stats.length > 0 && (
        <div className="table-wrap">
          <table className="data-table bt-event-study-table">
            <thead>
              <tr>
                <th scope="col">{t("strategy.eventStudy.header.horizon")}</th>
                <th scope="col" className="num">
                  {t("strategy.eventStudy.header.edgeHitBase")}
                </th>
                <th scope="col" className="num">
                  {t("strategy.eventStudy.header.medianDistribution")}
                </th>
                <th scope="col" className="num">
                  {t("strategy.eventStudy.header.sampleIndependent")}
                </th>
              </tr>
            </thead>
            <tbody>
              {arm.stats.map((s) => (
                <HorizonStatsRow key={s.horizon} stats={s} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ArmPanelWarnings({ warnings }: { warnings: MarketWarning[] }) {
  if (warnings.length === 0) return null;
  return (
    <div className="warnings-strip bt-arm-warnings">
      {warnings.map((w, i) => (
        <div className="warning-chip" key={`${w.kind}-${i}`}>
          <span className="kind">{w.kind}</span>
          <span className="message">{w.message}</span>
        </div>
      ))}
    </div>
  );
}

/** `"unverified"` must be styled as a problem, not a pending state -- it shares the same
 *  `.callout-danger` treatment as `"failed"`, differing only in the label text. */
function GuardStatusBlock({ guard }: { guard: GuardReport }) {
  const { t } = useT();
  if (guardOk(guard)) return null;
  return (
    <div className="callout callout-danger bt-guard-callout">
      <div className="bt-guard-status">
        {guard.status === "unverified"
          ? t("strategy.eventStudy.guardUnverified")
          : t("strategy.eventStudy.guardFailed")}
      </div>
      {guard.findings.length > 0 && (
        <ul className="warning-list">
          {guard.findings.map((f, i) => (
            <li key={`${f.check}-${i}`}>
              <strong>{f.check}</strong> — {f.detail} (
              {f.passed ? t("strategy.guardStatus.passed") : t("strategy.guardStatus.failed")})
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function HorizonStatsRow({ stats }: { stats: HorizonStats }) {
  const { t } = useT();
  const edge = edgeOfStats(stats);
  const cls = edge === null ? "" : edge > 0 ? "pos" : edge < 0 ? "neg" : "";
  const small = isSmallSample(stats);
  return (
    <tr className={small ? "bt-row-small-sample" : ""}>
      <td>{stats.horizon}b</td>
      <td className="num edge-cell">
        <div className={`edge-value ${cls}`}>{formatSignedRate(edge)}</div>
        <div className="edge-baseline">
          <Trans
            k="strategy.eventStudy.hitVsBaseline"
            values={{ hit: formatRate(stats.hit_rate), baseline: formatRate(stats.baseline_hit_rate) }}
          />
        </div>
        {stats.entry === "same_close" && (
          <div className="entry-tag" title={t("strategy.eventStudy.sameCloseTitle")}>
            {t("strategy.eventStudy.sameCloseTag")}
          </div>
        )}
      </td>
      <td className="num bt-distribution-cell">
        <div className="median-value">
          {t("strategy.eventStudy.medianLabel", { value: formatSignedRate(stats.distribution.median) })}
        </div>
        <div className="bt-cell-sub">
          p05 {formatSignedRate(stats.distribution.p05)} · p25{" "}
          {formatSignedRate(stats.distribution.p25)} · p75 {formatSignedRate(stats.distribution.p75)}{" "}
          · p95 {formatSignedRate(stats.distribution.p95)}
        </div>
      </td>
      <td className="num">
        <div className="bt-sample-independent">
          {t("strategy.eventStudy.indepLabel", { count: stats.independent_sample_size.toLocaleString() })}
        </div>
        <div className="bt-cell-sub">
          <Trans
            k="strategy.eventStudy.sampleRawBase"
            values={{
              raw: stats.sample_size.toLocaleString(),
              base: stats.baseline_sample_size.toLocaleString(),
            }}
          />
        </div>
        {small && (
          <span
            className="badge small-sample"
            title={t("strategy.eventStudy.smallSampleTitle", { threshold: SMALL_SAMPLE_THRESHOLD })}
          >
            {t("strategy.backtest.smallSampleBadge")}
          </span>
        )}
      </td>
    </tr>
  );
}

function DeltaPanel({ deltas }: { deltas: ArmDelta[] }) {
  const { t } = useT();
  if (deltas.length === 0) return null;
  return (
    <div className="bt-delta-panel">
      <h3>{t("strategy.eventStudy.deltaHeading")}</h3>
      <div className="table-wrap">
        <table className="data-table bt-delta-table">
          <thead>
            <tr>
              <th scope="col">{t("strategy.eventStudy.header.horizon")}</th>
              <th scope="col" className="num">
                {t("strategy.eventStudy.deltaHeader.hitRateDelta")}
              </th>
              <th scope="col" className="num">
                {t("strategy.eventStudy.deltaHeader.medianDelta")}
              </th>
              <th scope="col" className="num">
                {t("strategy.eventStudy.deltaHeader.sampleSizeDelta")}
              </th>
            </tr>
          </thead>
          <tbody>
            {deltas.map((d) => (
              <DeltaRow key={d.horizon} delta={d} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DeltaRow({ delta }: { delta: ArmDelta }) {
  const { t } = useT();
  const hitCls =
    delta.hit_rate_delta === null ? "" : delta.hit_rate_delta > 0 ? "pos" : delta.hit_rate_delta < 0 ? "neg" : "";
  const sampleShrank = delta.independent_sample_size_delta < 0;
  const sampleCls =
    delta.independent_sample_size_delta > 0 ? "pos" : delta.independent_sample_size_delta < 0 ? "neg" : "";
  const caution = sampleShrank && hitCls === "pos";
  return (
    <tr className={caution ? "bt-delta-caution" : ""}>
      <td>{delta.horizon}b</td>
      <td className={`num edge-value ${hitCls}`}>{formatSignedRate(delta.hit_rate_delta)}</td>
      <td className="num">{formatSignedRate(delta.median_delta)}</td>
      <td className={`num ${sampleCls}`}>
        <Trans
          k="strategy.eventStudy.deltaSampleCell"
          values={{
            rawSign: delta.sample_size_delta > 0 ? "+" : "",
            raw: delta.sample_size_delta.toLocaleString(),
            indepSign: delta.independent_sample_size_delta > 0 ? "+" : "",
            indep: delta.independent_sample_size_delta.toLocaleString(),
          }}
        />
        {caution && <div className="bt-delta-warning">{t("strategy.eventStudy.deltaCaution")}</div>}
      </td>
    </tr>
  );
}
