/**
 * The expandable body behind one candidate row in `PendingSeatsPanel` -- the answer to "why do you
 * want me to decide this," rendered from `GET /api/competition/loop/candidates/{genome_id}/dossier`.
 *
 * **Fetches lazily, once, on mount.** `PendingSeatsPanel` only mounts this component the first time a
 * reviewer expands a row (see that file's own docstring), so simply fetching in a `useEffect` here
 * *is* "fetch on first expand" -- there is no separate lazy-loading logic to write. Fetching every
 * queued card's full dossier eagerly, on page load, for a queue that can hold twenty or thirty
 * candidates, would be a lot of backend work (per-generation evidence rows, field-wide percentiles,
 * ticker-overlap comparisons against every other shelved/seated card) nobody has asked to see yet.
 *
 * **Section order is deliberate and mirrors `SPEC.md`'s own contract order**: what it trades, above
 * every number; why it exists; the evidence, field context first; what could be wrong with it, never
 * collapsed; what each decision does. A reader who never scrolls past the first section still learns
 * what the strategy actually does before hitting a single percentage.
 *
 * **The one non-negotiable ordering: field before card, on the holdout figure specifically.** 94.3% of
 * every holdout measurement this search has ever recorded, across every purpose -- including purely
 * random candidates -- comes back positive. A UI that shows this card's own "+14.88%" first primes a
 * reader to read it as evidence of quality before they have any idea that number is what nearly
 * everything clears. The callout at the top of "The evidence" states that all-purposes baseline before
 * it states this card's own figure, and the `holdout-does-not-discriminate` caution (rendered in
 * "What's wrong with it") restates the same fact in the backend's own deterministic words -- the two
 * are meant to reinforce each other, not stand alone.
 *
 * **Every field-comparison figure is labelled with which population it is scoped to
 * (2026-08-26 correction).** `DossierContext` (`api/evolution.ts`) used to carry a single unscoped
 * `field_median_excess_all_time`/`field_holdout_median_all_time`/`field_holdout_positive_fraction`;
 * the backend replaced them with explicit `_same_purpose`/`_all_purposes` pairs because an unlabelled
 * "field median" is exactly what let a card get compared against the wrong reference population
 * unnoticed. A card's *actual* reference population is `_same_purpose` (every other candidate run for
 * the same purpose, e.g. every `roth` card); `_all_purposes` is the wider "everything this search has
 * ever run" context the 94.3% figure is stated over. Every label below says which one it is showing.
 * This component never asserts a direction ("above"/"below" the field) itself -- that judgement is
 * read straight out of the deterministic `cautions[].text` the backend already computed it into,
 * copied, not recomputed (see `SPEC.md`'s house rule of the same name).
 */

import { useEffect, useRef } from "react";

import { formatIntOrDash, formatRatio, formatSignedPctFraction } from "@/api/competition";
import {
  evolutionApi,
  formatPctPoints,
  purposeLabel,
  type Caution,
  type CautionSeverity,
  type Dossier,
  type OriginKind,
} from "@/api/evolution";
import Fetched from "@/components/Fetched";
import { ScrollRegion } from "@/components/ScrollPanel";
import { useFetch } from "@/hooks/useFetch";
import { useT, type MessageKey } from "@/i18n";

/** `q` is a probability, not a percentage, and small values matter most -- renders with enough places
 * to tell 0.0004 from 0.04 rather than rounding both to "0.0000". Copied from the pre-rebuild
 * `PendingSeatsPanel.tsx` verbatim; this module owns its own copy for the same reason every wire-facing
 * module in this codebase does (see `api/evolution.ts`'s docstring on `requestJson`). */
function formatQ(q: number | null): string {
  if (q === null) return "n/a";
  return q < 0.001 ? q.toExponential(1) : q.toFixed(4);
}

const SEVERITY_ORDER: Record<CautionSeverity, number> = { blocking: 0, serious: 1, note: 2 };

const SEVERITY_LABEL_KEYS: Record<CautionSeverity, MessageKey> = {
  blocking: "competitionRounds.dossier.severity.blocking",
  serious: "competitionRounds.dossier.severity.serious",
  note: "competitionRounds.dossier.severity.note",
};

/** `origin_kind` is a bare backend enum value -- see the module docstring's "field before card"
 * section for the house rule this follows: a display label, never the raw wire value, on screen. */
const ORIGIN_KIND_LABEL_KEYS: Record<OriginKind, MessageKey> = {
  random: "competitionRounds.dossier.origin.random",
  mutation: "competitionRounds.dossier.origin.mutation",
  crossover: "competitionRounds.dossier.origin.crossover",
  agent: "competitionRounds.dossier.origin.agent",
};

export interface CandidateDossierProps {
  genomeId: string;
  /** Called once, the first time the dossier finishes loading -- lets `PendingSeatsPanel` prefer the
   * dossier's own `headline`/`short_id` over the list row's, once both are available (the two are
   * guaranteed byte-identical by the backend, so this is a formality rather than a real upgrade -- see
   * `Dossier.headline`'s own docstring in `api/evolution.ts`). */
  onLoaded?: (dossier: Dossier) => void;
}

export default function CandidateDossier({ genomeId, onLoaded }: CandidateDossierProps) {
  const { t } = useT();
  const result = useFetch<Dossier>(
    (signal) => evolutionApi.dossier(genomeId, signal),
    // Keyed on `genomeId` alone, matching the original effect's own eslint-disabled dependency array:
    // `onLoaded` is a per-render closure, read via the ref below instead, so keying the fetch on it
    // would refetch every render. `PendingSeatsPanel` never remounts this component with a changed
    // `genomeId` in place.
    [genomeId],
    { formatError: (err) => (err instanceof Error ? err.message : String(err)) },
  );

  // Called once per successful load, with whichever `onLoaded` is current at that moment -- a ref
  // rather than a dependency, for the same reason the fetch itself does not key on `onLoaded`.
  const onLoadedRef = useRef(onLoaded);
  onLoadedRef.current = onLoaded;
  useEffect(() => {
    if (result.data) onLoadedRef.current?.(result.data);
  }, [result.data]);

  return (
    <Fetched
      state={result}
      loading={
        <p className="comp-review-dossier-loading" data-testid="dossier-loading">
          {t("competitionRounds.dossier.loading")}
        </p>
      }
      error={(message) => (
        <p className="callout callout-danger comp-review-dossier-error" data-testid="dossier-error">
          {t("competitionRounds.dossier.error", {
            error: message ?? t("competitionRounds.dossier.unknownError"),
          })}
        </p>
      )}
    >
      {(dossier) => <CandidateDossierBody genomeId={genomeId} dossier={dossier} />}
    </Fetched>
  );
}

function CandidateDossierBody({ genomeId, dossier }: { genomeId: string; dossier: Dossier }) {
  const { t } = useT();
  const sortedCautions = [...dossier.cautions].sort(
    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
  );
  const { context } = dossier;
  // The card's own most recent holdout figure, stated plainly at the end of the reality-check callout
  // -- evidence rows arrive oldest first (see EvidenceRow's own docstring), so the last one is the
  // latest scoring. Deliberately placed AFTER both field figures (field before card, the non-negotiable
  // ordering) and deliberately NOT paired with an "above"/"below" adjective of this component's own
  // composing -- that judgement belongs to the deterministic `cautions[].text` below, copied not
  // recomputed, since a hand-written comparison here could assert a direction the numbers do not
  // support (see the module docstring on the 2026-08-26 correction).
  const latestHoldout =
    dossier.evidence.length > 0 ? dossier.evidence[dossier.evidence.length - 1]!.holdout_median_excess : null;

  const originKindLabel = t(ORIGIN_KIND_LABEL_KEYS[dossier.origin.origin_kind]);
  const originLine =
    dossier.origin.parents.length > 0
      ? t("competitionRounds.dossier.originLineWithParents", {
          generation: formatIntOrDash(dossier.origin.generation),
          originKind: originKindLabel,
          parents: dossier.origin.parents.join(", "),
        })
      : t("competitionRounds.dossier.originLine", {
          generation: formatIntOrDash(dossier.origin.generation),
          originKind: originKindLabel,
        });

  return (
    <div className="comp-review-dossier" data-testid="candidate-dossier">
      {/* --- What it does --------------------------------------------------------------------- */}
      <section aria-labelledby={`dossier-does-${genomeId}`} className="comp-review-dossier-section">
        <h5 id={`dossier-does-${genomeId}`}>{t("competitionRounds.dossier.heading.whatItDoes")}</h5>
        <p className="comp-review-universe">
          <strong>{t("competitionRounds.dossier.universeLabel")}</strong> {dossier.what_it_does.universe.join(", ")}
          {". "}
          {dossier.what_it_does.universe_note}
        </p>
        {/* discipline_label is a self-declared label, not derived from the rule -- a mutation can flip
            it (g1815-d05786e4c611 -> g1823-e2a3d5060b09) without changing a single trading parameter,
            so it is never allowed to stand in as a description on its own. The caveat text itself
            (discipline_label_note) is the backend's own -- copied, not recomposed -- and already says
            this; see candidateName.ts's module docstring for the full case. This is the one place this
            label renders at all. */}
        <div className="comp-review-discipline-label" data-testid="discipline-label">
          <p className="comp-review-discipline-label-value">
            {t("competitionRounds.dossier.selfDeclaredLabel")} <strong>{dossier.discipline_label}</strong>
          </p>
          <p className="comp-review-discipline-note">{dossier.discipline_label_note}</p>
        </div>
        <dl className="comp-review-plain-rules">
          <dt>{t("competitionRounds.label.entry")}</dt>
          <dd>{dossier.what_it_does.entry_plain}</dd>
          <dt>{t("competitionRounds.label.exit")}</dt>
          <dd>{dossier.what_it_does.exit_plain}</dd>
          <dt>{t("competitionRounds.label.risk")}</dt>
          <dd>{dossier.what_it_does.risk_plain}</dd>
          <dt>{t("competitionRounds.label.sizing")}</dt>
          <dd>{dossier.what_it_does.sizing_plain}</dd>
        </dl>
      </section>

      {/* --- Why it's here --------------------------------------------------------------------- */}
      <section aria-labelledby={`dossier-why-${genomeId}`} className="comp-review-dossier-section">
        <h5 id={`dossier-why-${genomeId}`}>{t("competitionRounds.dossier.heading.whyHere")}</h5>
        <p className="comp-review-thesis">&ldquo;{dossier.thesis}&rdquo;</p>
        <p className="comp-review-origin">{originLine}</p>
        {dossier.origin.note && <p className="comp-review-origin-note">{dossier.origin.note}</p>}
        {(dossier.overlap.with_shelved.length > 0 || dossier.overlap.with_seated.length > 0) && (
          <p className="comp-review-overlap-note">{dossier.overlap.note}</p>
        )}
      </section>

      {/* --- The evidence ---------------------------------------------------------------------- */}
      <section aria-labelledby={`dossier-evidence-${genomeId}`} className="comp-review-dossier-section">
        <h5 id={`dossier-evidence-${genomeId}`}>{t("competitionRounds.dossier.heading.evidence")}</h5>
        <p className="comp-review-holdout-check callout callout-warn" data-testid="holdout-reality-check">
          {t("competitionRounds.dossier.holdoutCheck.allPurposes", {
            positiveFraction: formatRatio(context.field_holdout_positive_fraction_all_purposes),
            measurements: formatIntOrDash(context.holdout_measurements_all_purposes),
            median: formatSignedPctFraction(context.field_holdout_median_all_purposes),
          })}
          <br />
          {t("competitionRounds.dossier.holdoutCheck.samePurpose", {
            measurements: formatIntOrDash(context.holdout_measurements_same_purpose),
            positiveFraction: formatRatio(context.field_holdout_positive_fraction_same_purpose),
            median: formatSignedPctFraction(context.field_holdout_median_same_purpose),
            cardHoldout: formatSignedPctFraction(latestHoldout),
          })}
        </p>
        {dossier.evidence.length === 0 ? (
          <p className="comp-review-no-evidence">{t("competitionRounds.dossier.noEvidence")}</p>
        ) : (
          <ScrollRegion size="md" label={t("competitionRounds.dossier.heading.evidence")}>
            <div className="table-wrap">
              <table className="data-table comp-review-evidence-table">
                <thead>
                <tr>
                  <th>{t("competitionRounds.dossier.table.generation")}</th>
                  <th>{t("competitionRounds.dossier.table.rankField")}</th>
                  <th>{t("competitionRounds.dossier.table.windows")}</th>
                  <th>{t("competitionRounds.dossier.table.selectionMedian")}</th>
                  <th>{t("competitionRounds.dossier.table.holdoutMedian")}</th>
                  <th>{t("competitionRounds.dossier.table.hitRate")}</th>
                  <th>{t("competitionRounds.dossier.table.trades")}</th>
                  <th>q</th>
                </tr>
              </thead>
              <tbody>
                {dossier.evidence.map((row) => (
                  <tr key={`${row.generation}-${row.round_id}`}>
                    <td>{row.generation}</td>
                    <td>
                      {row.rank} / {row.field_size}
                    </td>
                    <td className="comp-review-windows-cell">{row.windows.join(", ")}</td>
                    <td>
                      <div className="comp-review-field-first">
                        <span className="comp-review-field-value">
                          {t("competitionRounds.dossier.evidenceRow.fieldSamePurpose", {
                            value: formatSignedPctFraction(context.field_median_excess_same_purpose),
                          })}
                        </span>
                        <span className="comp-review-field-value">
                          {t("competitionRounds.dossier.evidenceRow.fieldThisGeneration", {
                            value: formatSignedPctFraction(context.field_median_excess_this_generation),
                          })}
                        </span>
                        <span className="comp-review-card-value">
                          {t("competitionRounds.dossier.evidenceRow.thisCard", {
                            value: formatSignedPctFraction(row.median_excess),
                          })}
                        </span>
                      </div>
                    </td>
                    <td>
                      <div className="comp-review-field-first">
                        <span className="comp-review-field-value">
                          {t("competitionRounds.dossier.evidenceRow.fieldSamePurpose", {
                            value: formatSignedPctFraction(context.field_holdout_median_same_purpose),
                          })}
                        </span>
                        <span className="comp-review-card-value">
                          {t("competitionRounds.dossier.evidenceRow.thisCard", {
                            value: formatSignedPctFraction(row.holdout_median_excess),
                          })}
                        </span>
                      </div>
                    </td>
                    <td>{formatRatio(row.hit_rate)}</td>
                    <td>{formatIntOrDash(row.total_trades)}</td>
                    <td>{formatQ(row.q_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </ScrollRegion>
        )}
        <dl className="status-grid comp-review-context-grid">
          <div>
            <span className="label">{t("competitionRounds.dossier.contextGrid.medianSamePurpose")}</span>
            <span className="value">{formatSignedPctFraction(context.field_median_excess_same_purpose)}</span>
          </div>
          <div>
            <span className="label">{t("competitionRounds.dossier.contextGrid.medianAllPurposes")}</span>
            <span className="value">{formatSignedPctFraction(context.field_median_excess_all_purposes)}</span>
          </div>
          <div>
            <span className="label">{t("competitionRounds.dossier.contextGrid.holdoutMedianSamePurpose")}</span>
            <span className="value">{formatSignedPctFraction(context.field_holdout_median_same_purpose)}</span>
          </div>
          <div>
            <span className="label">{t("competitionRounds.dossier.contextGrid.holdoutMedianAllPurposes")}</span>
            <span className="value">{formatSignedPctFraction(context.field_holdout_median_all_purposes)}</span>
          </div>
          <div>
            <span className="label">{t("competitionRounds.dossier.contextGrid.holdoutPositiveSamePurpose")}</span>
            <span className="value">
              {t("competitionRounds.dossier.contextGrid.ratioWithN", {
                ratio: formatRatio(context.field_holdout_positive_fraction_same_purpose),
                count: formatIntOrDash(context.holdout_measurements_same_purpose),
              })}
            </span>
          </div>
          <div>
            <span className="label">{t("competitionRounds.dossier.contextGrid.holdoutPositiveAllPurposes")}</span>
            <span className="value">
              {t("competitionRounds.dossier.contextGrid.ratioWithN", {
                ratio: formatRatio(context.field_holdout_positive_fraction_all_purposes),
                count: formatIntOrDash(context.holdout_measurements_all_purposes),
              })}
            </span>
          </div>
          <div>
            <span className="label">{t("competitionRounds.dossier.contextGrid.percentile")}</span>
            <span className="value">{formatRatio(context.percentile_all_time)}</span>
          </div>
          <div>
            <span className="label">{t("competitionRounds.dossier.contextGrid.noiseFloor")}</span>
            <span className="value">{formatPctPoints(context.noise_floor_pp)}</span>
          </div>
          <div>
            <span className="label">{t("competitionRounds.dossier.contextGrid.marginOverNoise")}</span>
            <span className="value">{formatPctPoints(context.margin_over_noise_pp)}</span>
          </div>
          <div>
            <span className="label">{t("competitionRounds.dossier.contextGrid.candidatesEverRun")}</span>
            <span className="value">{formatIntOrDash(context.candidates_ever_run)}</span>
          </div>
          <div>
            <span className="label">{t("competitionRounds.dossier.contextGrid.generationsWithOutcomes")}</span>
            <span className="value">{formatIntOrDash(context.generations_with_outcomes)}</span>
          </div>
        </dl>
      </section>

      {/* --- What's wrong with it -- never collapsed, never hidden when non-empty -------------- */}
      <section
        aria-labelledby={`dossier-cautions-${genomeId}`}
        className="comp-review-dossier-section comp-review-cautions-section"
        data-testid="dossier-cautions"
      >
        <h5 id={`dossier-cautions-${genomeId}`}>{t("competitionRounds.dossier.heading.wrong")}</h5>
        {sortedCautions.length === 0 ? (
          <p className="comp-review-no-cautions">{t("competitionRounds.dossier.noCautions")}</p>
        ) : (
          <ScrollRegion size="md" label={t("competitionRounds.dossier.heading.wrong")}>
            <ul className="comp-review-caution-list">
              {sortedCautions.map((caution: Caution) => (
                <li
                  key={caution.code}
                  className={`comp-review-caution comp-review-caution-${caution.severity}`}
                  data-testid={`caution-${caution.code}`}
                >
                  <span className="comp-review-caution-severity">{t(SEVERITY_LABEL_KEYS[caution.severity])}</span>
                  <span className="comp-review-caution-text">{caution.text}</span>
                </li>
              ))}
            </ul>
          </ScrollRegion>
        )}
      </section>

      {/* --- What each button does -------------------------------------------------------------- */}
      <section aria-labelledby={`dossier-decisions-${genomeId}`} className="comp-review-dossier-section">
        <h5 id={`dossier-decisions-${genomeId}`}>{t("competitionRounds.dossier.heading.decisions")}</h5>
        <dl className="comp-review-decision-list">
          <dt>{t("competitionRounds.dossier.decision.shelve")}</dt>
          <dd>{dossier.what_a_decision_does.shelve}</dd>
          <dt>{t("competitionRounds.dossier.decision.reject")}</dt>
          <dd>{dossier.what_a_decision_does.reject}</dd>
          <dt>{t("competitionRounds.action.seatOnPaperDesk")}</dt>
          <dd>{dossier.what_a_decision_does.seat}</dd>
          <dt>{t("competitionRounds.action.retire")}</dt>
          <dd>{dossier.what_a_decision_does.retire}</dd>
        </dl>
        <p className="comp-review-purpose-line">
          {t("competitionRounds.dossier.filedFor", { purpose: purposeLabel(dossier.purpose) })}
        </p>
      </section>
    </div>
  );
}
