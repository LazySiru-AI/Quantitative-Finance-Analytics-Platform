/**
 * One narrative section of the report.
 *
 * `api/report.ts`'s module docstring is explicit about what this component's job is *not*: the
 * prose arrives already rendered and already verified, because a `RenderedNarrative` only exists
 * when its `GroundingReport` passed on the backend. Re-checking it here would be redundant at best
 * and would risk implying a stronger guarantee than the one that was actually made. The job is to
 * *show that it was checked* -- surface `grounding.cited` as a footnote list resolving to the
 * `Fact` each citation leaned on, and surface `grounding.caveat`, which states the limit of the
 * guarantee (grounded prose is not the same as true prose).
 *
 * When `narrative` is `null` the draft failed verification. There is no fallback sentence: rendering
 * one here would quietly reintroduce the thing the grounding check exists to prevent. Only the
 * section's `warnings` render.
 */
import { useMemo } from "react";

import { formatFact, type Fact, type ReportSection } from "@/api/report";
import type { MarketWarning } from "@/api/report";
import { useT } from "@/i18n";
import TranslatedProse from "@/i18n/TranslatedProse";

interface NarrativeSectionProps {
  section: ReportSection;
}

export default function NarrativeSection({ section }: NarrativeSectionProps) {
  return (
    <div className="panel report-narrative-section">
      <h2 className="section-heading">{section.title}</h2>

      {section.narrative ? (
        <NarrativeBody
          text={section.narrative.text}
          grounding={section.narrative.grounding}
          citedFacts={section.narrative.cited_facts}
        />
      ) : (
        // The draft failed verification. No fallback sentence of our own -- rendering one here
        // would quietly reintroduce the thing grounding exists to prevent. Only the section's own
        // warnings render; if there are none either, that absence is itself the finding.
        <SectionWarnings warnings={section.warnings} />
      )}

      {section.narrative && <SectionWarnings warnings={section.warnings} />}
    </div>
  );
}

function NarrativeBody({
  text,
  grounding,
  citedFacts,
}: {
  text: string;
  grounding: { cited: string[]; caveat: string };
  citedFacts: Fact[];
}) {
  const { t } = useT();
  const factsById = useMemo(() => {
    const map = new Map<string, Fact>();
    for (const fact of citedFacts) map.set(fact.id, fact);
    return map;
  }, [citedFacts]);

  return (
    <div className="report-narrative">
      {/* `text` is model-written prose, verified on the backend before this ever renders (see this
          file's own module docstring). `TranslatedProse` (Phase 4 of the i18n rollout) shows a
          Korean machine translation when the backend supplied one for the active language, and
          falls back to the English original -- badged, exactly as before -- when it did not. */}
      <TranslatedProse text={text} className="report-narrative-text" />

      {grounding.cited.length > 0 && (
        <div className="report-narrative-citations">
          <span className="report-narrative-citations-label">{t("desk.narrative.citationsLabel")}</span>
          <ol>
            {grounding.cited.map((id, i) => {
              const fact = factsById.get(id);
              return (
                <li key={`${id}-${i}`}>
                  {fact ? (
                    <>
                      <strong>{fact.label}</strong>: {formatFact(fact)}
                      <span className="report-citation-source"> — {fact.source}</span>
                    </>
                  ) : (
                    <span className="report-citation-missing">{t("desk.narrative.factNotResolved", { id })}</span>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      )}

      {/* Unobtrusive but present -- this states the limit of the grounding guarantee (every
          numeral resolves to a fact) and must not be hidden, or the narrow check reads as a
          broad one. Also model-written English, per the same rule as `text` above -- not run
          through the catalog. */}
      <p className="report-narrative-caveat">{grounding.caveat}</p>
    </div>
  );
}

function SectionWarnings({ warnings }: { warnings: MarketWarning[] }) {
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
