/**
 * The persona's in-voice critique of a strategy card -- the reverse of `PersonaAsk.tsx`'s
 * "ask them anything": here the caller already has a card in hand and wants the influencer's
 * reading of it, grounded in their own methodology. NEVER the person literally speaking and NEVER
 * advice -- see `personaAsk.critique.caveatLabel`, rendered always-visible next to the trigger.
 *
 * **Presentational only -- this component fetches nothing.** `state` is a discriminated union
 * ("nothing asked yet" / "in flight" / "the request failed" / "done") and `onCritique` is a bare
 * trigger with no arguments -- `Personas.tsx` already knows which card is selected and owns
 * calling `POST /{slug}/critique`, the same fetch-free split `PersonaAsk.tsx`'s own docstring
 * describes.
 *
 * Product guardrails this file enforces:
 *
 * 1. The trigger is disabled, with an explanation, whenever `canCritique` is false ("no card to
 *    critique yet") -- never a silently-inert button.
 * 2. `verdict` renders as one of four visually distinct badges (`aligned` / `mixed` /
 *    `misaligned` / `cannot_say`) via `StatusPill`, never folded into a single generic style.
 * 3. `assessment` renders verbatim (model-written text, not this app's copy); `citations` (via
 *    `CitationList`) and `caveat` are always visible once a critique exists; `degraded` renders
 *    as a fact-check-failure callout, exactly like `PersonaAsk.tsx`'s answer body.
 * 4. `caveat` is the backend's own fixed disclaimer string for this critique and renders verbatim,
 *    separate from -- and in addition to -- this component's own always-visible
 *    `personaAsk.critique.caveatLabel` framing text above the trigger.
 */
import type { CardCritique } from "@/api/personas";
import { CitationList } from "@/components/CitationList";
import { ScrollRegion } from "@/components/ScrollPanel";
import StatusPill, { type PillTone } from "@/components/StatusPill";
import { useT, type MessageKey } from "@/i18n";

import "./PersonaAsk.css";

export type CritiqueState =
  | { phase: "idle" }
  | { phase: "pending" }
  | { phase: "error"; message: string }
  | { phase: "done"; critique: CardCritique };

export interface PersonaCritiqueProps {
  displayName: string;
  state: CritiqueState;
  /** Whether a card is available to critique; disable the trigger + explain when false. */
  canCritique: boolean;
  onCritique: () => void;
}

const VERDICT_TONE: Record<CardCritique["verdict"], PillTone> = {
  aligned: "ok",
  mixed: "warn",
  misaligned: "bad",
  cannot_say: "neutral",
};

const VERDICT_LABEL_KEY: Record<CardCritique["verdict"], MessageKey> = {
  aligned: "personaAsk.critique.verdict.aligned",
  mixed: "personaAsk.critique.verdict.mixed",
  misaligned: "personaAsk.critique.verdict.misaligned",
  cannot_say: "personaAsk.critique.verdict.cannotSay",
};

export default function PersonaCritique({ displayName, state, canCritique, onCritique }: PersonaCritiqueProps) {
  const { t } = useT();
  const pending = state.phase === "pending";

  return (
    <section className="panel persona-critique">
      <h3 className="persona-critique-heading">{t("personaAsk.critique.heading", { name: displayName })}</h3>
      <p className="muted persona-critique-caveat-label">
        {t("personaAsk.critique.caveatLabel", { name: displayName })}
      </p>

      <div className="persona-critique-trigger-row">
        <button type="button" onClick={onCritique} disabled={!canCritique || pending}>
          {pending ? t("personaAsk.critique.pending", { name: displayName }) : t("personaAsk.critique.trigger")}
        </button>
        {!canCritique && (
          <span className="muted persona-critique-disabled-explain">
            {t("personaAsk.critique.disabledExplain")}
          </span>
        )}
      </div>

      <ScrollRegion size="md" label={t("personaAsk.critique.heading", { name: displayName })}>
        {state.phase === "idle" && (
          <p className="placeholder persona-critique-idle">
            {t("personaAsk.critique.idleHint", { name: displayName })}
          </p>
        )}

        {state.phase === "pending" && (
          <div className="placeholder persona-critique-loading">
            {t("personaAsk.critique.pending", { name: displayName })}
          </div>
        )}

        {state.phase === "error" && (
          <div className="callout callout-danger persona-critique-error" role="alert">
            {state.message}
          </div>
        )}

        {state.phase === "done" && <CritiqueBody critique={state.critique} />}
      </ScrollRegion>
    </section>
  );
}

function CritiqueBody({ critique }: { critique: CardCritique }) {
  const { t } = useT();
  return (
    <div className="persona-critique-body">
      {critique.degraded && (
        <div className="callout callout-warn persona-critique-degraded" role="alert">
          <StatusPill tone="warn" label={t("ui.pill.unverified")} />{" "}
          <strong>{t("personaAsk.ask.groundingWarning")}</strong>
        </div>
      )}

      <div className="persona-critique-verdict-row">
        <span className="muted">{t("personaAsk.critique.verdictHeading")}:</span>
        <StatusPill
          tone={VERDICT_TONE[critique.verdict]}
          label={t(VERDICT_LABEL_KEY[critique.verdict])}
          className="persona-critique-verdict"
          data-testid="persona-critique-verdict"
        />
      </div>

      <p className="persona-critique-assessment">{critique.assessment}</p>

      <CitationList citations={critique.citations} />

      {/* `critique.caveat` is the backend's own fixed disclaimer for this critique -- verbatim,
          never routed through t(). See this file's docstring, guardrail 4. */}
      <p className="muted persona-critique-backend-caveat">{critique.caveat}</p>
    </div>
  );
}
