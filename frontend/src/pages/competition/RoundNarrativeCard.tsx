/**
 * A round's own written narrative -- the prose companion to `FindingsSection`'s structured entries.
 * Mirrors `SummarySection`/`FindingsSection`'s house style: every piece of data arrives as a prop (the
 * parent owns the fetch), phase/message/notFound describe the load, and nothing here calls
 * `competitionApi` itself.
 *
 * `outcome` is **plain text with `\n\n` paragraph breaks, deliberately not markdown** -- see
 * `api/competition.ts`'s `RoundNarrative` docstring. It is split on the blank line and rendered as one
 * `<p>` per paragraph, never through `dangerouslySetInnerHTML`, matching `FindingsSection`'s own
 * "render body as text" rule for the same reason: this is hand-written prose lifted off disk, and a
 * stray `<` in it must never be read as markup.
 *
 * `outcome` runs to five or six paragraphs on some rounds, so it is wrapped in the shared
 * `Collapsible` (`components/Collapsible.tsx`) and collapsed by default -- the `headline` and `focus`
 * above it already tell the reader what the round concluded, so hiding the detail costs nothing. The
 * `data-testid="comp-narrative-outcome"` stays on the inner div (not the `<details>`), and `Collapsible`
 * always mounts its children, so existing paragraph-count assertions keep working collapsed or not.
 *
 * `owner_override` is a first-class part of what happened, not a footnote. Three of this programme's
 * rounds ended in one, so a non-null value gets its own visually distinct callout (`.callout-warn`,
 * the same amber-toned treatment `styles.css` already uses for "this needs attention" elsewhere on the
 * page) rather than a quiet aside. `null` renders nothing at all -- no empty callout shell for a round
 * that had nothing to override.
 *
 * `seated: []` is a real, distinct fact ("this round seated nothing"), not the same as "no data yet" --
 * it renders an explicit sentence rather than leaving a blank area a reader might mistake for a loading
 * gap or a bug.
 */
import type { RoundNarrative } from "@/api/competition";
import Collapsible from "@/components/Collapsible";
import { useT } from "@/i18n";

import "./RoundNarrativeCard.css";

type Phase = "loading" | "loaded" | "error";

export interface RoundNarrativeCardProps {
  narrative: RoundNarrative | null;
  phase: Phase;
  message: string | null;
  /** True when the round exists but the narrative endpoint answered 404 -- a designed empty state
   * (this round has no authored narrative yet), not an error. */
  notFound: boolean;
}

/** Plain text, `\n\n`-delimited paragraphs -- never markdown, never HTML. A trailing/leading blank
 * paragraph (e.g. `"\n\nfoo"`) is dropped rather than rendered as an empty `<p>`. */
function splitParagraphs(outcome: string): string[] {
  return outcome.split("\n\n").filter((p) => p.trim().length > 0);
}

export default function RoundNarrativeCard({ narrative, phase, message, notFound }: RoundNarrativeCardProps) {
  const { t } = useT();

  if (phase === "loading") {
    return (
      <div className="panel comp-narrative-panel">
        <div className="placeholder">{t("competition.narrative.loading")}</div>
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div className="panel comp-narrative-panel">
        <div className="placeholder">{message ?? t("competition.errors.narrative")}</div>
      </div>
    );
  }

  if (notFound || !narrative) {
    // Not a red error -- rounds legitimately have no authored narrative yet, the same way
    // `FindingsSection` treats its own 404. See that component's docstring for the precedent.
    return (
      <div className="panel comp-narrative-panel">
        <div className="placeholder comp-narrative-empty">
          {t("competition.narrative.emptyNotFound")}
        </div>
      </div>
    );
  }

  const paragraphs = splitParagraphs(narrative.outcome);
  const hasOverride = narrative.owner_override !== null;

  return (
    <div className="panel comp-narrative-panel">
      <h2 className="section-heading comp-narrative-title">{narrative.title}</h2>

      <p className="comp-narrative-headline">{narrative.headline}</p>

      <div className="comp-narrative-focus">
        <span className="comp-narrative-label">{t("competition.narrative.askedLabel")}</span>
        <p className="comp-narrative-focus-body">{narrative.focus}</p>
      </div>

      <Collapsible
        title={<span className="comp-narrative-outcome-label">{t("competition.narrative.happenedLabel")}</span>}
        defaultOpen={false}
        className="comp-narrative-outcome-collapsible"
      >
        <div className="comp-narrative-outcome" data-testid="comp-narrative-outcome">
          {paragraphs.map((p, i) => (
            <p key={i} className="comp-narrative-outcome-p">
              {p}
            </p>
          ))}
        </div>
      </Collapsible>

      {hasOverride && (
        <div
          className="callout callout-warn comp-narrative-override"
          role="note"
          data-testid="comp-narrative-override"
        >
          <strong className="comp-narrative-override-label">{t("competition.narrative.ownerOverride")}</strong>
          <p className="comp-narrative-override-body">{narrative.owner_override}</p>
        </div>
      )}

      <div className="comp-narrative-seated">
        <span className="comp-narrative-label">{t("competition.narrative.seatedLabel")}</span>
        {narrative.seated.length === 0 ? (
          <p className="comp-narrative-seated-empty">{t("competition.narrative.seatedEmpty")}</p>
        ) : (
          <div className="comp-narrative-seated-chips">
            {narrative.seated.map((agentId) => (
              <span key={agentId} className="badge comp-narrative-seated-chip">
                {agentId}
              </span>
            ))}
          </div>
        )}
      </div>

      {narrative.carries_forward.length > 0 && (
        <div className="comp-narrative-carries">
          <span className="comp-narrative-label">{t("competition.narrative.carriesForwardLabel")}</span>
          <ul className="comp-narrative-carries-list">
            {narrative.carries_forward.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {narrative.sources.length > 0 && (
        <ul className="comp-narrative-sources">
          {narrative.sources.map((s) => (
            <li key={s} className="comp-narrative-source">
              {s}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
