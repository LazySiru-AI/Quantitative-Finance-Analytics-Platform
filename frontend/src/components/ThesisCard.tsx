/**
 * One `StrategyCard` from the thesis loop: what was proposed, what would refute it, and every
 * number the loop's four guards demand sit next to what it qualifies.
 *
 * `backend/app/thesis/models.py`'s `StrategyCard` docstring is explicit that a card is produced for
 * a rejected and an inconclusive thesis too, carrying the numbers that killed it -- "a system that
 * only renders winners is a system whose output is selected on the outcome." This component makes
 * no distinction in structure between verdicts; the same sections render for `survived`, `rejected`
 * and `inconclusive` alike, and `VerdictBadge` (shared with `TrialLedger`) gives all three equal
 * visual weight.
 *
 * Four things here are direct consequences of the guards, not decoration:
 *
 * **`falsifies_if` is labelled as written in advance.** That is the entire point of pre-registration
 * (guard 1) -- a criterion supplied after the numbers arrive is a criterion tuned to pass, so the
 * label says "declared before any test ran" rather than just "falsifies if".
 *
 * **A burned holdout is loud, per-card as well as ticker-wide.** `card.holdout_state` is the state
 * as of when this specific card was evaluated; `"burned"` gets `callout-danger` with the attempt
 * count and the backend's `describe` sentence (via `describeHoldout`, mirrored in `useThesis.ts`)
 * verbatim. `"spent"` is neutral-informational. `"unused"` renders nothing here.
 *
 * **Every q-value shows the family it was corrected over.** `Evidence.trials_at_evaluation` sits
 * directly under every `q_value` in `EvidenceColumn` -- a q-value is meaningless without knowing how
 * large the corrected family was, and that family grows with the ledger.
 *
 * **A leveraged instrument's card is meaningless without its unlevered twin.** `unlevered_comparison`
 * renders as a nested `ThesisCard` (via `nested`, which drops the outer chrome and disclaimer so
 * nesting doesn't repeat either) beneath an explanation that a daily-reset product decays in choppy
 * markets regardless of direction, so its card alone cannot separate strategy edge from that decay.
 */
import { useState } from "react";

import { formatQ, SMALL_SAMPLE_THRESHOLD, type Distribution } from "@/api/backtest";
import { ApiRequestError } from "@/api/client";
import type { MarketWarning } from "@/api/market";
import { formatRate, formatSignedRate } from "@/api/rules";
import {
  directionLabel,
  thesisApi,
  type Evidence,
  type HoldoutState,
  type RegimeSlice,
  type StrategyCard as StrategyCardData,
  type TaxImpact,
  type Thesis,
} from "@/api/thesis";
import StatGrid from "@/components/StatGrid";
import { StatusPill } from "@/components/StatusPill";
import { VerdictBadge } from "@/components/TrialLedger";
import { describeHoldout } from "@/hooks/useThesis";
import { Trans, useT } from "@/i18n";

interface ThesisCardProps {
  card: StrategyCardData;
  /** True when rendered inside another card's `unlevered_comparison` slot -- drops the outer
   *  `.panel` chrome and the disclaimer so a nested card doesn't repeat either. */
  nested?: boolean;
}

export default function ThesisCard({ card, nested = false }: ThesisCardProps) {
  return (
    <div className={nested ? "thesis-nested-card" : "panel"}>
      <ThesisCardHeader card={card} nested={nested} />
      <HoldoutCallout state={card.holdout_state} />
      <FalsifiesBlock thesis={card.thesis} />
      <RuleBlock card={card} />
      <ReturnDistributions card={card} />
      <TradeStats card={card} />
      <EvidenceComparison card={card} />
      {card.regimes.length > 0 && <RegimeTable card={card} />}
      {card.tax && <TaxBlock tax={card.tax} />}
      {card.hourly_substudy && <HourlySubstudy evidence={card.hourly_substudy} />}
      {card.unlevered_comparison && <UnleveredComparison card={card.unlevered_comparison} />}
      <CardWarnings warnings={card.warnings} />
      {!nested && <p className="report-disclaimer">{card.disclaimer}</p>}
    </div>
  );
}

function ThesisCardHeader({ card, nested }: { card: StrategyCardData; nested: boolean }) {
  const { t } = useT();
  return (
    <div className="thesis-card-header">
      <div className="thesis-card-title">
        <h2 className="section-heading">
          {nested
            ? t("strategy.thesisCard.unleveredHeading")
            : t("strategy.thesisCard.headerTitle", { symbol: card.symbol })}
        </h2>
        <VerdictBadge verdict={card.verdict} />
        <PromoteButton card={card} nested={nested} />
      </div>
      <div className="thesis-card-meta">
        {t("strategy.thesisCard.meta", { interval: card.interval, date: card.generated_at })}
        {card.ledger && (
          <>
            {t("strategy.thesisCard.ledgerAtEvaluation", {
              count: card.ledger.total_trials.toLocaleString(),
            })}
          </>
        )}
      </div>
    </div>
  );
}

/**
 * "Promote to library" -- copies a **survivor** onto the strategy-competition shelf as a reference
 * card (`POST /api/thesis/promote`). Renders nothing for any other verdict, and nothing on a nested
 * unlevered card: only a top-level survivor is promotable, and self-gating here keeps
 * `ThesisCardHeader` from having to know the rule.
 *
 * The outcome is shown with `StatusPill`, not a sentence, matching the app's status vocabulary: `ok`
 * once written (with the card's `agent_id`), `info` for a `409` (already promoted -- a hash-pinned
 * survivor, so re-promoting is a no-op worth stating plainly, not an error), and `bad` for a real
 * failure carrying the backend's own message. The button disables itself while in flight and once
 * done so a second click cannot fire a redundant request.
 */
export function PromoteButton({ card, nested }: { card: StrategyCardData; nested: boolean }) {
  const { t } = useT();
  const [phase, setPhase] = useState<"idle" | "promoting" | "done" | "exists" | "error">("idle");
  const [detail, setDetail] = useState<string | null>(null);

  if (nested || card.verdict !== "survived") return null;

  const promote = () => {
    setPhase("promoting");
    setDetail(null);
    thesisApi
      .promote({ symbol: card.symbol, thesis_hash: card.thesis_hash })
      .then((created) => {
        setPhase("done");
        setDetail(created.agent_id);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiRequestError && err.status === 409) {
          setPhase("exists");
          return;
        }
        setPhase("error");
        setDetail(
          err instanceof ApiRequestError ? err.message : t("strategy.thesisCard.promote.errorGeneric"),
        );
      });
  };

  return (
    <span className="thesis-promote-wrap">
      <button
        type="button"
        className="thesis-promote"
        onClick={promote}
        disabled={phase === "promoting" || phase === "done"}
      >
        {phase === "promoting"
          ? t("strategy.thesisCard.promote.promoting")
          : t("strategy.thesisCard.promote.button")}
      </button>
      {phase === "done" && (
        <StatusPill
          tone="ok"
          label={t("strategy.thesisCard.promote.done")}
          detail={detail ?? undefined}
        />
      )}
      {phase === "exists" && (
        <StatusPill tone="info" label={t("strategy.thesisCard.promote.exists")} />
      )}
      {phase === "error" && (
        <StatusPill
          tone="bad"
          label={t("strategy.thesisCard.promote.errorLabel")}
          detail={detail ?? undefined}
        />
      )}
    </span>
  );
}

/** `"unused"` renders nothing -- a ticker's first look at its holdout is not itself news. */
function HoldoutCallout({ state }: { state: HoldoutState | null }) {
  const { t } = useT();
  if (state === null || state.status === "unused") return null;
  if (state.status === "burned") {
    return (
      <div className="callout callout-danger thesis-holdout-callout">
        <strong>{t("strategy.thesisCard.holdoutBurnedHeadline", { attempts: state.attempts })}</strong>{" "}
        {describeHoldout(state)}
      </div>
    );
  }
  return <div className="callout callout-info thesis-holdout-callout">{describeHoldout(state)}</div>;
}

/** `hypothesis`/`rationale`/`falsifies_if` are the author's pre-registered prose -- written before
 *  any test ran, and per this project's model-prose convention it stays in English regardless of
 *  `lang`, with the `common.sourceEnglish` badge marking the boundary rather than leaving a Korean
 *  reader to wonder why this one block did not switch. Only the surrounding chrome is translated. */
function FalsifiesBlock({ thesis }: { thesis: Thesis }) {
  const { t } = useT();
  return (
    <div className="thesis-hypothesis-block">
      <p className="thesis-hypothesis">{thesis.hypothesis}</p>
      {thesis.rationale && <p className="thesis-rationale">{thesis.rationale}</p>}
      <div className="thesis-falsifies">
        <span className="thesis-falsifies-label">{t("strategy.thesisCard.falsifiesLabel")}</span>
        <p className="thesis-falsifies-text">{thesis.falsifies_if}</p>
      </div>
      <span className="badge" title={t("common.sourceEnglishTitle")}>
        {t("common.sourceEnglish")}
      </span>
      <div className="thesis-direction-horizon bt-cell-sub">
        <Trans
          k="strategy.thesisCard.directionHorizon"
          values={{
            direction: <strong>{directionLabel(thesis.direction)}</strong>,
            horizon: thesis.horizon,
          }}
        />
      </div>
    </div>
  );
}

function RuleBlock({ card }: { card: StrategyCardData }) {
  const { t } = useT();
  return (
    <StatGrid
      items={[
        {
          label: t("strategy.thesisCard.field.entry"),
          value: <code className="bt-arm-expression">{card.entry_rule}</code>,
        },
        {
          label: t("strategy.thesisCard.field.exit"),
          value: card.exit_rule ? <code className="bt-arm-expression">{card.exit_rule}</code> : "—",
        },
        {
          label: t("strategy.thesisCard.field.triggersPerYear"),
          value: card.triggers_per_year !== null ? card.triggers_per_year.toFixed(1) : "—",
        },
        {
          label: t("strategy.thesisCard.field.holdingPeriodMedian"),
          value:
            card.holding_period_median !== null
              ? t("strategy.backtest.underwaterBars", { count: card.holding_period_median.toFixed(1) })
              : "—",
        },
        {
          label: t("strategy.thesisCard.field.holdingPeriodIqr"),
          value: card.holding_period_iqr
            ? t("strategy.thesisCard.holdingIqrValue", {
                lo: card.holding_period_iqr[0].toFixed(1),
                hi: card.holding_period_iqr[1].toFixed(1),
              })
            : "—",
        },
      ]}
    />
  );
}

function ReturnDistributions({ card }: { card: StrategyCardData }) {
  const { t } = useT();
  return (
    <div className="thesis-distribution-pair">
      <h3>{t("strategy.thesisCard.returnDistHeading")}</h3>
      <div className="table-wrap">
        <table className="data-table thesis-distribution-table">
          <thead>
            <tr>
              <th scope="col"> </th>
              <th scope="col" className="num">
                {t("strategy.thesisCard.distHeader.median")}
              </th>
              <th scope="col" className="num">
                {t("strategy.thesisCard.distHeader.p05p95")}
              </th>
              <th scope="col" className="num">
                {t("strategy.thesisCard.distHeader.mean")}
              </th>
              <th scope="col" className="num">
                {t("strategy.thesisCard.distHeader.n")}
              </th>
            </tr>
          </thead>
          <tbody>
            <DistributionRow label={t("strategy.thesisCard.expectedRuleLabel")} dist={card.expected_return} />
            <DistributionRow
              label={t("strategy.thesisCard.baselineUnconditionalLabel")}
              dist={card.baseline_return}
            />
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DistributionRow({ label, dist }: { label: string; dist: Distribution }) {
  return (
    <tr>
      <td>{label}</td>
      <td className="num">{formatSignedRate(dist.median)}</td>
      <td className="num bt-cell-sub">
        {formatSignedRate(dist.p05)} – {formatSignedRate(dist.p95)}
      </td>
      <td className="num">{formatSignedRate(dist.mean)}</td>
      <td className="num">{dist.count.toLocaleString()}</td>
    </tr>
  );
}

function TradeStats({ card }: { card: StrategyCardData }) {
  const { t } = useT();
  const worstCls = card.worst_trade !== null && card.worst_trade < 0 ? "neg" : "";
  return (
    <StatGrid
      items={[
        {
          label: t("strategy.thesisCard.field.worstTrade"),
          value: <span className={`edge-value ${worstCls}`}>{formatSignedRate(card.worst_trade)}</span>,
        },
        {
          label: t("strategy.thesisCard.field.maxDrawdownInPosition"),
          value: formatSignedRate(card.max_drawdown_in_position),
        },
      ]}
    />
  );
}

function EvidenceComparison({ card }: { card: StrategyCardData }) {
  const { t } = useT();
  return (
    <div className="thesis-evidence-columns">
      <EvidenceColumn label={t("strategy.thesisCard.inSampleLabel")} evidence={card.in_sample} />
      <EvidenceColumn label={t("strategy.thesisCard.holdoutLabel")} evidence={card.holdout} />
    </div>
  );
}

function EvidenceColumn({ label, evidence }: { label: string; evidence: Evidence | null }) {
  const { t } = useT();
  return (
    <div className="thesis-evidence-col">
      <h3>{label}</h3>
      {evidence === null ? (
        <div className="placeholder">{t("strategy.thesisCard.notEvaluated")}</div>
      ) : (
        <StatGrid
          items={[
            {
              label: t("strategy.thesisCard.evidence.hitRateVsBaseline"),
              value: t("strategy.thesisCard.vsPattern", {
                a: formatRate(evidence.hit_rate),
                b: formatRate(evidence.baseline_hit_rate),
              }),
            },
            {
              label: t("strategy.thesisCard.evidence.medianReturnVsBaseline"),
              value: t("strategy.thesisCard.vsPattern", {
                a: formatSignedRate(evidence.median_return),
                b: formatSignedRate(evidence.baseline_median_return),
              }),
            },
            {
              label: t("strategy.thesisCard.evidence.pValue"),
              value: evidence.p_value !== null ? evidence.p_value.toFixed(4) : "—",
            },
            {
              label: t("strategy.thesisCard.evidence.qValueTrialFamily"),
              value: (
                <>
                  {formatQ(evidence.q_value)}
                  <div className="bt-cell-sub">
                    {t("strategy.trialLedger.ofTrials", { count: evidence.trials_at_evaluation })}
                  </div>
                </>
              ),
            },
            {
              label: t("strategy.thesisCard.evidence.independentSample"),
              value: (
                <>
                  {evidence.independent_sample_size.toLocaleString()}
                  {evidence.independent_sample_size < SMALL_SAMPLE_THRESHOLD && (
                    <div className="badge small-sample">{t("strategy.backtest.smallSampleBadge")}</div>
                  )}
                </>
              ),
            },
          ]}
        />
      )}
    </div>
  );
}

function edgeOf(evidence: Evidence | null | undefined): number | null {
  if (!evidence || evidence.hit_rate === null || evidence.baseline_hit_rate === null) return null;
  return evidence.hit_rate - evidence.baseline_hit_rate;
}

/** A regime is labelled `conditional` when its edge either flips sign against the overall in-sample
 *  edge or diverges from it by more than 5 points -- a coarse but honest signal that this thesis's
 *  edge, if any, depends on which regime the market is in rather than holding generally. */
function isRegimeConditional(slice: RegimeSlice, overallEdge: number | null): boolean {
  const regimeEdge = edgeOf(slice.evidence);
  if (regimeEdge === null || overallEdge === null) return false;
  return Math.sign(regimeEdge) !== Math.sign(overallEdge) || Math.abs(regimeEdge - overallEdge) > 0.05;
}

function RegimeTable({ card }: { card: StrategyCardData }) {
  const { t } = useT();
  const overallEdge = edgeOf(card.in_sample);
  return (
    <div className="thesis-regimes">
      <h3>{t("strategy.thesisCard.regimeHeading")}</h3>
      <p className="bt-cell-sub thesis-regime-note">
        <Trans
          k="strategy.thesisCard.regimeNote"
          values={{
            conditional: (
              <span className="badge thesis-regime-conditional">
                {t("strategy.thesisCard.conditionalBadge")}
              </span>
            ),
          }}
        />
      </p>
      <div className="table-wrap">
        <table className="data-table thesis-regime-table">
          <thead>
            <tr>
              <th scope="col">{t("strategy.thesisCard.regimeHeader.regime")}</th>
              <th scope="col" className="num">
                {t("strategy.thesisCard.regimeHeader.bars")}
              </th>
              <th scope="col" className="num">
                {t("strategy.thesisCard.regimeHeader.edgeVsBaseline")}
              </th>
              <th scope="col"> </th>
            </tr>
          </thead>
          <tbody>
            {card.regimes.map((slice: RegimeSlice) => {
              const edge = edgeOf(slice.evidence);
              const cls = edge === null ? "" : edge > 0 ? "pos" : edge < 0 ? "neg" : "";
              const conditional = isRegimeConditional(slice, overallEdge);
              return (
                <tr key={slice.label}>
                  <td>{slice.label}</td>
                  <td className="num">{slice.bars.toLocaleString()}</td>
                  <td className="num">
                    <span className={`edge-value ${cls}`}>{formatSignedRate(edge)}</span>
                  </td>
                  <td>
                    {conditional && (
                      <span className="badge thesis-regime-conditional">
                        {t("strategy.thesisCard.conditionalBadge")}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TaxBlock({ tax }: { tax: TaxImpact }) {
  const { t } = useT();
  if (tax.unavailable_reason) {
    return (
      <div className="thesis-tax-block">
        <h3>{t("strategy.thesisCard.taxHeading")}</h3>
        <div className="placeholder">{tax.unavailable_reason}</div>
      </div>
    );
  }
  // `rate_basis` is what makes the after-tax figure self-describing: the same float means "your
  // actual modelled cost" under user_configured and "a ceiling most filers fall under" under
  // statutory_upper_bound, and those two readings must never look the same on screen. See
  // `backend/app/thesis/models.py`'s `TaxRateBasis` docstring.
  const isUpperBound = tax.rate_basis === "statutory_upper_bound";
  return (
    <div className="thesis-tax-block">
      <h3>{t("strategy.thesisCard.taxHeading")}</h3>
      {/* Wash sales the strategy triggers against itself are the headline: the thing a standalone
          backtester structurally cannot tell you, and a rule that looks good gross and mediocre
          after tax is a common, normally invisible outcome. */}
      {tax.wash_sales_triggered > 0 && (
        <div className="callout callout-warn thesis-tax-headline">
          {t(
            tax.wash_sales_triggered === 1
              ? "strategy.thesisCard.washSaleHeadline_one"
              : "strategy.thesisCard.washSaleHeadline_other",
            { count: tax.wash_sales_triggered },
          )}
          {tax.disallowed_loss !== null && (
            <>{t("strategy.thesisCard.washSaleDisallowed", { loss: formatSignedRate(tax.disallowed_loss) })}</>
          )}
          .
          {tax.ira_exposure && (
            <>
              {" "}
              <Trans
                k="strategy.thesisCard.washSaleIraClause"
                values={{ permanently: <strong>{t("strategy.thesisCard.permanentlyWord")}</strong> }}
              />
            </>
          )}
        </div>
      )}
      <div className="callout callout-info thesis-tax-headline">
        {isUpperBound ? (
          <Trans
            k="strategy.thesisCard.taxUpperBoundNote"
            values={{
              upperBound: <strong>{t("strategy.thesisCard.upperBoundWord")}</strong>,
              shortTerm: formatRate(tax.short_term_rate_applied),
              longTerm: formatRate(tax.long_term_rate_applied),
            }}
          />
        ) : (
          t("strategy.thesisCard.taxConfiguredNote", {
            shortTerm: formatRate(tax.short_term_rate_applied),
            longTerm: formatRate(tax.long_term_rate_applied),
          })
        )}
      </div>
      <StatGrid
        items={[
          { label: t("strategy.thesisCard.tax.grossReturn"), value: formatSignedRate(tax.gross_return) },
          {
            label: isUpperBound
              ? t("strategy.thesisCard.tax.afterTaxReturnUpperBound")
              : t("strategy.thesisCard.tax.afterTaxReturn"),
            value: (
              <>
                {formatSignedRate(tax.after_tax_return)}
                {isUpperBound && (
                  <div className="bt-cell-sub">{t("strategy.thesisCard.tax.statutoryRateNote")}</div>
                )}
              </>
            ),
          },
          { label: t("strategy.thesisCard.tax.shortTermGains"), value: formatSignedRate(tax.short_term_gains) },
          { label: t("strategy.thesisCard.tax.longTermGains"), value: formatSignedRate(tax.long_term_gains) },
          {
            label: t("strategy.thesisCard.tax.washSalesTriggered"),
            value: tax.wash_sales_triggered.toLocaleString(),
          },
          {
            label: t("strategy.thesisCard.tax.disallowedLoss"),
            value: formatSignedRate(tax.disallowed_loss),
          },
          {
            label: t("strategy.thesisCard.tax.iraExposure"),
            value:
              tax.ira_exposure === null ? (
                <span className="badge none">{t("strategy.thesisCard.tax.notChecked")}</span>
              ) : tax.ira_exposure ? (
                t("strategy.thesisCard.tax.yes")
              ) : (
                t("strategy.thesisCard.tax.no")
              ),
          },
        ]}
      />
    </div>
  );
}

function HourlySubstudy({ evidence }: { evidence: Evidence }) {
  const { t } = useT();
  return (
    <div className="thesis-hourly-substudy">
      <h3>{t("strategy.thesisCard.hourlyHeading")}</h3>
      <p className="bt-cell-sub">{t("strategy.thesisCard.hourlyNote")}</p>
      <EvidenceColumn label={t("strategy.thesisCard.hourlyLabel")} evidence={evidence} />
    </div>
  );
}

function UnleveredComparison({ card }: { card: StrategyCardData }) {
  const { t } = useT();
  return (
    <div className="thesis-unlevered-section">
      <h3>{t("strategy.thesisCard.unleveredHeading")}</h3>
      <p className="callout callout-info thesis-unlevered-note">
        {t("strategy.thesisCard.unleveredNote", { symbol: card.symbol })}
      </p>
      <ThesisCard card={card} nested />
    </div>
  );
}

function CardWarnings({ warnings }: { warnings: MarketWarning[] }) {
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
