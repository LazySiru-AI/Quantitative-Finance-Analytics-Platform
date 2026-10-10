/**
 * One influencer's consolidated profile -- who they are, what they believe, how they trade -- plus
 * their per-symbol theses and the button to (re)consolidate. Sits alongside `PersonaCard.tsx` under
 * the same persona on `/personas`; `PersonaCard.tsx` is the rolling digest (what changed recently),
 * this component is the standing profile (what the influencer's whole body of notes says about them).
 *
 * **Presentational only -- this component fetches nothing.** `Personas.tsx` owns fetching
 * `GET /{slug}/profile` and `GET /{slug}/theses` and firing `POST /{slug}/consolidate`, the same
 * split `PersonaCard.tsx`'s own docstring establishes. `state` is the discriminated union below
 * rather than a bare `PersonaProfile | null`, so "still loading", "never consolidated" (`404`) and "the
 * fetch actually failed" cannot be confused with each other -- see `docs/INFLUENCER-CONTRACT.md`,
 * "Phase 2", and `@/api/personas`'s docstring on the same section.
 *
 * This file exists to enforce the Phase 2 product guardrails, not merely style them:
 *
 * 1. **Every belief/playbook claim's citations are always visible**, rendered as a chip per
 *    `note_id` right next to the claim text -- never behind a hover, never omitted. Per the contract,
 *    a claim with empty `citations` is invalid and the backend never persists one; showing the
 *    citations is what lets a reader tell "the influencer actually said this" from "the model
 *    invented this."
 * 2. **Everything reads as the influencer's own view** -- "What they believe" / "How they trade",
 *    never "signal" or a recommendation, matching `PersonaCard.tsx`'s own copy discipline.
 * 3. **`profile.degraded` is always visible when true**, worded as a fact-check failure the profile
 *    was released despite, never hidden -- same rule as `PersonaCard.tsx`'s `grounding.degraded`.
 * 4. **Never consolidated is a valid empty state** (`state.phase === "not_found"`, the `404` case):
 *    a short line plus the Consolidate button, not an error and not a spinner.
 * 5. **No notes means the Consolidate button is disabled**, with the reason stated inline -- a
 *    persona with zero notes has nothing for the model to fold into a profile.
 * 6. **Consolidation is synchronous and slow.** The button shows a pending label and disables itself
 *    while `consolidatePending` is true; a rejection's `detail` renders verbatim via
 *    `describePersonaActionError` (`Personas.tsx` builds `consolidateError` with it), never a generic
 *    failure message.
 * 7. **Per-symbol theses link to `/symbol/{symbol}`**, matching `PersonaCard.tsx`'s own ticker chips.
 *
 * **Internationalised** through `misc.personas.profile.*` (and the shared `stanceLabel`), like the
 * rest of `/personas`. Model-written text -- `profile.summary`, each `claim.text` -- and backend
 * error `detail` stay verbatim (they are the influencer's/model's own words or a raw server
 * message), and citation `note_id`s are identifiers; everything else routes through `t()`.
 */
import { Link } from "react-router-dom";

import {
  formatRelativeAge,
  stanceLabel,
  type PersonaProfile as Profile,
  type ProfileClaim,
  type RegimeView,
  type RiskPosture,
  type TickerThesis,
} from "@/api/personas";
import { CitationList } from "@/components/CitationList";
import { ScrollPanel } from "@/components/ScrollPanel";
import { type MessageKey, useT } from "@/i18n";

import "./PersonaProfileExtras.css";

/** The one place `RiskPosture` wording lives for this file -- same idiom as `@/api/personas`'s own
 * `STANCE_LABEL_KEYS`/`OUTCOME_LABEL_KEYS`. Kept local rather than added to that module since the
 * task fence here does not include `@/api/personas`. */
const RISK_POSTURE_KEYS: Record<RiskPosture, MessageKey> = {
  on: "personaProfile.regime.risk.on",
  off: "personaProfile.regime.risk.off",
  mixed: "personaProfile.regime.risk.mixed",
  unclear: "personaProfile.regime.risk.unclear",
};

/** Distinguishes "still loading" / "never consolidated" (`404`) / "the fetch actually failed" from
 * a loaded profile -- see this file's own docstring. `Personas.tsx` is the only producer. */
export type ProfileFetchState =
  | { phase: "loading" }
  | { phase: "not_found" }
  | { phase: "error"; message: string }
  | { phase: "loaded"; profile: Profile };

export interface PersonaProfileProps {
  displayName: string;
  /** The persona's *current* note count (`DigestCard.note_count`), used only to gate the Consolidate
   * button -- distinct from `Profile.note_count`, which is how many notes the loaded profile *version*
   * was actually built from and may already be stale by the time a reader sees it. */
  currentNoteCount: number;
  state: ProfileFetchState;
  theses: TickerThesis[];
  consolidatePending: boolean;
  consolidateError: string | null;
  onConsolidate: () => void;
}

export default function PersonaProfile({
  displayName,
  currentNoteCount,
  state,
  theses,
  consolidatePending,
  consolidateError,
  onConsolidate,
}: PersonaProfileProps) {
  const { t } = useT();
  const hasNotes = currentNoteCount > 0;
  const consolidateDisabled = consolidatePending || !hasNotes;
  const consolidateLabel = consolidatePending
    ? t("misc.personas.profile.consolidating")
    : state.phase === "loaded"
      ? t("misc.personas.profile.reconsolidate")
      : t("misc.personas.profile.consolidate");

  return (
    <ScrollPanel
      panelClassName="persona-profile"
      title={<h3 className="persona-card-subhead">{t("misc.personas.profile.heading")}</h3>}
      label={t("misc.personas.profile.heading")}
      size="lg"
      expandable
    >
      <div className="persona-profile-scroll-body">
        {state.phase === "loading" && (
          <div className="placeholder persona-profile-loading">{t("misc.personas.profile.loading")}</div>
        )}

        {state.phase === "error" && (
          <div className="callout callout-danger persona-profile-error" role="alert">
            {state.message}
          </div>
        )}

        {state.phase === "not_found" && (
          <div className="placeholder persona-profile-empty">
            {t("misc.personas.profile.notConsolidated", { name: displayName })}
          </div>
        )}

        {state.phase === "loaded" && <ProfileBody profile={state.profile} theses={theses} />}

        {!hasNotes && (
          <p className="muted persona-profile-no-notes-reason">
            {t("misc.personas.profile.noNotesReason", { name: displayName })}
          </p>
        )}

        {consolidateError && (
          <div className="callout callout-danger persona-profile-consolidate-error" role="alert">
            {consolidateError}
          </div>
        )}

        <button type="button" onClick={onConsolidate} disabled={consolidateDisabled}>
          {consolidateLabel}
        </button>
      </div>
    </ScrollPanel>
  );
}

function ProfileBody({ profile, theses }: { profile: Profile; theses: TickerThesis[] }) {
  const { t } = useT();
  return (
    <div className="persona-profile-body">
      <div className="persona-profile-meta">
        <span className="badge">{t("misc.personas.profile.version", { version: profile.version })}</span>
        <span className="badge">
          {t(
            profile.note_count === 1
              ? "misc.personas.profile.builtFrom_one"
              : "misc.personas.profile.builtFrom_other",
            { count: profile.note_count },
          )}
        </span>
        <span className="muted persona-profile-age">
          {t("misc.personas.profile.consolidatedAge", {
            age: formatRelativeAge(profile.consolidated_at),
          })}
        </span>
      </div>

      {profile.degraded && (
        <div className="callout callout-warn persona-profile-degraded" role="alert">
          <strong>{t("misc.personas.profile.degradedTitle")}</strong>{" "}
          {t("misc.personas.profile.degradedBody")}
        </div>
      )}

      <p className="persona-profile-summary">{profile.summary}</p>

      {profile.beliefs.length > 0 && (
        <ClaimSection
          title={t("misc.personas.profile.beliefs")}
          claims={profile.beliefs}
          className="persona-profile-beliefs"
        />
      )}

      {profile.playbook.length > 0 && (
        <ClaimSection
          title={t("misc.personas.profile.playbook")}
          claims={profile.playbook}
          className="persona-profile-playbook"
        />
      )}

      {profile.methodology.length > 0 && (
        <ClaimSection
          title={t("personaProfile.methodology.heading")}
          claims={profile.methodology}
          className="persona-profile-methodology"
        />
      )}

      {profile.regime !== null && profile.regime.has_signal && <RegimeSection regime={profile.regime} />}

      {profile.vocabulary.length > 0 && (
        <div className="persona-card-section persona-profile-vocabulary">
          <h4 className="persona-card-subhead">{t("misc.personas.profile.vocabulary")}</h4>
          <ul className="persona-vocab-list">
            {profile.vocabulary.map((term, i) => (
              <li key={`${term}-${i}`} className="persona-vocab-chip">
                {term}
              </li>
            ))}
          </ul>
        </div>
      )}

      {theses.length > 0 && (
        <div className="persona-card-section persona-profile-theses">
          <h4 className="persona-card-subhead">{t("misc.personas.profile.theses")}</h4>
          <ul className="persona-thesis-list">
            {theses.map((thesis, i) => (
              <ThesisItem key={`${thesis.symbol}-${i}`} thesis={thesis} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ClaimSection({
  title,
  claims,
  className,
}: {
  title: string;
  claims: ProfileClaim[];
  className: string;
}) {
  return (
    <div className={`persona-card-section ${className}`}>
      <h4 className="persona-card-subhead">{title}</h4>
      <ul className="persona-claim-list">
        {claims.map((claim, i) => (
          <ClaimItem key={i} claim={claim} />
        ))}
      </ul>
    </div>
  );
}

/** Renders one claim's text plus a citation chip per `note_id` -- rule 1 in this file's docstring:
 * citations are never hidden or omitted, regardless of how many there are. */
function ClaimItem({ claim }: { claim: ProfileClaim }) {
  const { t } = useT();
  return (
    <li className="persona-claim">
      <span className="persona-claim-text">{claim.text}</span>
      <span className="persona-claim-citations" aria-label={t("misc.personas.profile.citationsLabel")}>
        {claim.citations.map((noteId, i) => (
          <span
            key={`${noteId}-${i}`}
            className="persona-citation-chip"
            title={t("misc.personas.profile.citationTitle", { noteId })}
          >
            {noteId}
          </span>
        ))}
      </span>
    </li>
  );
}

/** The persona's macro/regime posture -- rendered only when `has_signal` is true (the caller in
 * `ProfileBody` gates on that plus `regime !== null`). Descriptive, never a trading signal; the
 * `summary` is the model's own words and renders verbatim, matching `profile.summary` above. */
function RegimeSection({ regime }: { regime: RegimeView }) {
  const { t } = useT();
  return (
    <div className="persona-card-section persona-profile-regime">
      <h4 className="persona-card-subhead">{t("personaProfile.regime.heading")}</h4>
      <div className="persona-profile-regime-meta">
        <span className="badge">
          {t("personaProfile.regime.riskPosture", { risk: t(RISK_POSTURE_KEYS[regime.risk]) })}
        </span>
        <span className="muted persona-profile-regime-rates">
          {t("personaProfile.regime.rates", { rates: regime.rates })}
        </span>
      </div>
      <p className="persona-profile-summary persona-profile-regime-summary">{regime.summary}</p>
      {regime.sectors_favoured.length > 0 && (
        <div className="persona-profile-regime-sectors">
          <span className="muted persona-profile-regime-sectors-label">
            {t("personaProfile.regime.sectorsFavoured")}
          </span>
          <ul className="persona-vocab-list">
            {regime.sectors_favoured.map((sector, i) => (
              <li key={`${sector}-${i}`} className="persona-vocab-chip">
                {sector}
              </li>
            ))}
          </ul>
        </div>
      )}
      {regime.sectors_avoided.length > 0 && (
        <div className="persona-profile-regime-sectors">
          <span className="muted persona-profile-regime-sectors-label">
            {t("personaProfile.regime.sectorsAvoided")}
          </span>
          <ul className="persona-vocab-list">
            {regime.sectors_avoided.map((sector, i) => (
              <li key={`${sector}-${i}`} className="persona-vocab-chip">
                {sector}
              </li>
            ))}
          </ul>
        </div>
      )}
      <CitationList citations={regime.citations} className="persona-profile-regime-citations" />
    </div>
  );
}

function ThesisItem({ thesis }: { thesis: TickerThesis }) {
  return (
    <li className="persona-thesis-item">
      <Link className="persona-ticker-chip" to={`/symbol/${encodeURIComponent(thesis.symbol)}`}>
        <span className="position-symbol">{thesis.symbol}</span>
        <span className={`persona-ticker-stance persona-ticker-stance-${thesis.stance}`}>
          {stanceLabel(thesis.stance)}
        </span>
      </Link>
      {thesis.claims.length > 0 && (
        <ul className="persona-claim-list persona-thesis-claim-list">
          {thesis.claims.map((claim, i) => (
            <ClaimItem key={i} claim={claim} />
          ))}
        </ul>
      )}
    </li>
  );
}
