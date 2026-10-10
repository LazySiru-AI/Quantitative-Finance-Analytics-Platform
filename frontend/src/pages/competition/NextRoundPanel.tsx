/**
 * What the next round is set up to run, before any job for it exists -- the pre-flight briefing that
 * sits in front of the existing run form. Mirrors `SummarySection`/`FindingsSection`'s house style:
 * every piece of data arrives as a prop, phase/message describe the load, and nothing here calls
 * `competitionApi` itself.
 *
 * `pre_registered: false` is not a warning to style away -- this programme's protocol requires a
 * round's plan to be committed before any run exists, so an un-pre-registered next round is a real
 * blocker, surfaced with the same `.callout-warn` treatment `RoundNarrativeCard` gives an owner
 * override. See `api/competition.ts`'s `NextRoundBriefing` docstring.
 *
 * **Two carries-forward lists, and merging them is a bug** -- see `NextRoundBriefing`'s own docstring
 * for the full reasoning. `authored_carries_forward` is prose a human committed to the previous
 * round's `NARRATIVE.json`; it is rendered first, primary, attributed to `previous_round_id`.
 * `carries_forward: RoundFinding[]` is the findings parser's heuristic keyword read over the same
 * round's prose -- rendered second, visually secondary, under a label that says plainly it is a guess,
 * not a curated list. An empty `authored_carries_forward` says so explicitly rather than promoting the
 * heuristic list into the primary slot to fill the space.
 *
 * `blockers` are surfaced, never hidden or used to disable anything -- this panel informs, it does not
 * gate. The `onRun` callback is only a notification hook for the parent (e.g. "scroll to / open the
 * run form"); this component never runs a round itself.
 */
import type { NextRoundBriefing } from "@/api/competition";
import { useT } from "@/i18n";

import "./NextRoundPanel.css";

type Phase = "loading" | "loaded" | "error";

export interface NextRoundPanelProps {
  briefing: NextRoundBriefing | null;
  phase: Phase;
  message: string | null;
  /** Notifies the parent that the reader wants to act on this briefing (e.g. jump to the run form).
   * This component never runs anything itself -- the manager wires the actual run form separately. */
  onRun?: () => void;
}

export default function NextRoundPanel({ briefing, phase, message, onRun }: NextRoundPanelProps) {
  const { t } = useT();
  if (phase === "loading") {
    return (
      <div className="panel comp-next-panel">
        <div className="placeholder">{t("competitionRounds.nextRound.loading")}</div>
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div className="panel comp-next-panel">
        <div className="placeholder">{message ?? t("competitionRounds.nextRound.loadError")}</div>
      </div>
    );
  }

  if (!briefing) {
    return (
      <div className="panel comp-next-panel">
        <div className="placeholder comp-next-empty">{t("competitionRounds.nextRound.empty")}</div>
      </div>
    );
  }

  const {
    next_round_id,
    previous_round_id,
    plan_path,
    pre_registered,
    focus,
    authored_carries_forward,
    carries_forward,
    blockers,
  } = briefing;

  return (
    <div className="panel comp-next-panel">
      <h2 className="section-heading comp-next-heading">
        {t("competitionRounds.nextRound.heading", { roundId: next_round_id })}
      </h2>

      {pre_registered ? (
        <div className="callout callout-info comp-next-preregistration comp-next-preregistration-ok">
          <strong>{t("competitionRounds.nextRound.planCommitted")}</strong>
          <p className="comp-next-plan-path">{plan_path}</p>
        </div>
      ) : (
        <div
          className="callout callout-warn comp-next-preregistration comp-next-preregistration-warning"
          role="alert"
        >
          <strong>{t("competitionRounds.nextRound.noCommittedPlanTitle")}</strong>
          <p>{t("competitionRounds.nextRound.noCommittedPlanBody")}</p>
        </div>
      )}

      <div className="comp-next-focus">
        <span className="comp-next-label">{t("competitionRounds.nextRound.focusLabel")}</span>
        {focus !== null ? (
          <p className="comp-next-focus-body">{focus}</p>
        ) : (
          <p className="comp-next-focus-unset">
            {pre_registered
              ? t("competitionRounds.nextRound.focusUnsetRegistered")
              : t("competitionRounds.nextRound.focusUnsetUnregistered")}
          </p>
        )}
      </div>

      <div className="comp-next-carries">
        <span className="comp-next-label">{t("competitionRounds.nextRound.carriesLabel")}</span>
        {authored_carries_forward.length === 0 && carries_forward.length === 0 ? (
          <p className="comp-next-carries-empty">{t("competitionRounds.nextRound.nothingCarried")}</p>
        ) : (
          <>
            {authored_carries_forward.length === 0 ? (
              <p className="comp-next-authored-empty">
                {t("competitionRounds.nextRound.authoredEmpty", {
                  previousRoundId: previous_round_id ?? t("competitionRounds.nextRound.thePreviousRound"),
                })}
              </p>
            ) : (
              <ul className="comp-next-authored-list" data-testid="comp-next-authored">
                {authored_carries_forward.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            )}
            {previous_round_id && authored_carries_forward.length > 0 && (
              <div className="comp-next-authored-source">
                {t("competitionRounds.nextRound.fromRound", { previousRoundId: previous_round_id })}
              </div>
            )}

            {carries_forward.length > 0 && (
              <div className="comp-next-heuristic">
                <span className="comp-next-label comp-next-heuristic-label">
                  {t("competitionRounds.nextRound.heuristicLabel")}
                </span>
                <div className="comp-next-heuristic-list">
                  {carries_forward.map((f) => (
                    <div key={f.id} className="comp-next-carry-item comp-next-heuristic-item">
                      <div className="comp-next-carry-title">{f.title}</div>
                      <p className="comp-next-carry-body">{f.body}</p>
                      <div className="comp-next-carry-source">
                        {t("competitionRounds.sourceLine", { source: f.source })}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {blockers.length > 0 && (
        <div className="comp-next-blockers">
          <span className="comp-next-label">{t("competitionRounds.nextRound.blockersLabel")}</span>
          <ul className="comp-next-blockers-list">
            {blockers.map((b, i) => (
              <li key={i} className="comp-next-blocker-item">
                {b}
              </li>
            ))}
          </ul>
        </div>
      )}

      {onRun && (
        <button type="button" className="symbol-submit comp-next-run-button" onClick={onRun}>
          {t("competitionRounds.nextRound.goToRunForm")}
        </button>
      )}
    </div>
  );
}
