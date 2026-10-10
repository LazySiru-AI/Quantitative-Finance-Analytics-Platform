/**
 * The cross-persona risk-on/off regime tally -- what the followed macro commentators (personas
 * with no mechanical methodology) are collectively saying about the market's posture. Sits
 * alongside `PersonaWatchlist.tsx` as the two cross-persona consensus panels on `/personas`, both
 * fed by `@/api/personas`'s `watchlist`/`regime` endpoints.
 *
 * **Presentational only -- this component fetches nothing.** The page owns fetching `GET /regime`;
 * `state` is the discriminated union below, matching `PersonaScorecard.tsx`'s `ScorecardFetchState`
 * split so "still loading" / "the fetch actually failed" is never confused with a loaded consensus.
 *
 * This file exists to enforce the product guardrails, not merely style them:
 *
 * 1. **Only personas with `has_view` contribute a rendered `RegimeView`.** A persona without one
 *    (a pure technical trader, or one whose profile predates the field) gets a plain note instead
 *    of a fabricated "no signal" view -- never silently dropped, never rendered as a fake view.
 * 2. **The `risk_on`/`risk_off`/`mixed` tally is the headline**, shown before any per-persona detail.
 * 3. **`summary` renders verbatim** -- the commentator's own framing, not paraphrased further here.
 * 4. **`caveat` always renders, whenever a consensus is loaded** -- "a reference input, never a
 *    signal" -- regardless of how many personas have a view.
 * 5. **Citations render via the shared `CitationList`**, the same non-collapsible treatment every
 *    other persona claim gets.
 *
 * Internationalised through `personaConsensus.regime.*`; `rates`/`summary`/`sectors_favoured`/
 * `sectors_avoided` and citation ids are the backend's own words and are never routed through `t()`.
 */
import type { JSX } from "react";

import type { PersonaRegime as PersonaRegimeEntry, RegimeConsensus, RiskPosture } from "@/api/personas";
import { CitationList } from "@/components/CitationList";
import { ScrollRegion } from "@/components/ScrollPanel";
import { StatusPill, type PillTone } from "@/components/StatusPill";
import { useT } from "@/i18n";

import "./PersonaConsensus.css";

/** Distinguishes "still loading" / "the fetch actually failed" from a loaded consensus. The page is
 * the only producer. */
export type RegimeState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "loaded"; consensus: RegimeConsensus };

export interface PersonaRegimeProps {
  state: RegimeState;
}

/** Risk posture -> `StatusPill` tone. `on`/`off` map to the shared good/bad tones this app already
 * uses for held/rejected; `mixed` is a caution, `unclear` the honest neutral default. */
const RISK_TONE: Readonly<Record<RiskPosture, PillTone>> = {
  on: "ok",
  off: "bad",
  mixed: "warn",
  unclear: "neutral",
};

export default function PersonaRegime({ state }: PersonaRegimeProps): JSX.Element {
  const { t } = useT();

  return (
    <div className="panel persona-regime">
      <h3 className="persona-card-subhead">{t("personaConsensus.regime.heading")}</h3>
      <p className="muted persona-regime-subtitle">{t("personaConsensus.regime.subtitle")}</p>

      {state.phase === "loading" && (
        <div className="placeholder persona-regime-loading">{t("personaConsensus.regime.loading")}</div>
      )}

      {state.phase === "error" && (
        <div className="callout callout-danger persona-regime-error" role="alert">
          {state.message}
        </div>
      )}

      {state.phase === "loaded" && <RegimeBody consensus={state.consensus} />}
    </div>
  );
}

function RegimeBody({ consensus }: { consensus: RegimeConsensus }) {
  const { t } = useT();
  const { personas, risk_on, risk_off, mixed, caveat } = consensus;

  return (
    <div className="persona-regime-body">
      {/* Rule 4: always rendered, whenever a consensus is loaded -- independent of `personas.length`. */}
      <p className="muted persona-regime-caveat">{caveat}</p>

      <div className="persona-regime-tally">
        <div className="persona-regime-tally-stat">
          <span className="persona-regime-tally-label">{t("personaConsensus.regime.riskOn")}</span>
          <span className="persona-regime-tally-value">{risk_on}</span>
        </div>
        <div className="persona-regime-tally-stat">
          <span className="persona-regime-tally-label">{t("personaConsensus.regime.riskOff")}</span>
          <span className="persona-regime-tally-value">{risk_off}</span>
        </div>
        <div className="persona-regime-tally-stat">
          <span className="persona-regime-tally-label">{t("personaConsensus.regime.mixed")}</span>
          <span className="persona-regime-tally-value">{mixed}</span>
        </div>
      </div>

      {personas.length === 0 ? (
        <p className="muted persona-regime-empty">{t("personaConsensus.regime.empty")}</p>
      ) : (
        <ScrollRegion size="md" label={t("personaConsensus.regime.heading")}>
          <ul className="persona-regime-list">
            {personas.map((entry) =>
              entry.has_view ? (
                <RegimeRow key={entry.persona} entry={entry} />
              ) : (
                <NoViewRow key={entry.persona} entry={entry} />
              ),
            )}
          </ul>
        </ScrollRegion>
      )}
    </div>
  );
}

/** Rule 1: a persona without `has_view` gets this plain note, never a fabricated view. */
function NoViewRow({ entry }: { entry: PersonaRegimeEntry }) {
  const { t } = useT();
  return (
    <li className="persona-regime-row persona-regime-row-no-view">
      <span className="persona-regime-name">{entry.display_name}</span>
      <span className="muted persona-regime-no-view-note">{t("personaConsensus.regime.noView")}</span>
    </li>
  );
}

function RegimeRow({ entry }: { entry: PersonaRegimeEntry }) {
  const { t } = useT();
  const { view } = entry;

  const postureLabel = t(
    (
      {
        on: "personaConsensus.regime.postureOn",
        off: "personaConsensus.regime.postureOff",
        mixed: "personaConsensus.regime.postureMixed",
        unclear: "personaConsensus.regime.postureUnclear",
      } as const
    )[view.risk],
  );

  return (
    <li className="persona-regime-row">
      <div className="persona-regime-row-header">
        <span className="persona-regime-name">{entry.display_name}</span>
        <StatusPill tone={RISK_TONE[view.risk]} label={postureLabel} />
      </div>
      {view.rates !== "" && (
        <p className="persona-regime-rates">
          <span className="persona-regime-rates-label">{t("personaConsensus.regime.ratesLabel")}</span>{" "}
          {view.rates}
        </p>
      )}
      <p className="persona-regime-summary">{view.summary}</p>
      {view.sectors_favoured.length > 0 && (
        <p className="persona-regime-sectors persona-regime-sectors-favoured">
          <span className="persona-regime-sectors-label">{t("personaConsensus.regime.favoured")}</span>{" "}
          {view.sectors_favoured.join(", ")}
        </p>
      )}
      {view.sectors_avoided.length > 0 && (
        <p className="persona-regime-sectors persona-regime-sectors-avoided">
          <span className="persona-regime-sectors-label">{t("personaConsensus.regime.avoided")}</span>{" "}
          {view.sectors_avoided.join(", ")}
        </p>
      )}
      <CitationList citations={view.citations} />
    </li>
  );
}
