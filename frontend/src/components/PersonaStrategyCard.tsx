/**
 * One influencer's drafted strategy card -- their METHODOLOGY mapped onto the repo's fixed
 * rule-shape DSL (Phase 7c). Sits alongside `PersonaProfile.tsx` (the standing profile) and
 * `PersonaScorecard.tsx` (the backward-looking call record) under the same persona on `/personas`:
 * this panel is the forward-looking exploration lens -- "if we tried to mechanise how they trade,
 * what would that look like, and how much of their actual method survives the translation."
 *
 * **Presentational only -- this component fetches nothing.** `Personas.tsx` owns firing
 * `POST /{slug}/strategy-card` and fetching `GET /{slug}/strategy-cards`, the same split every other
 * persona panel's own docstring establishes. `state` is the discriminated union below rather than a
 * bare `StrategyCardDraft | null`, so "never drafted" / "drafting now" / "the call failed" cannot be
 * confused with a drafted card.
 *
 * This file exists to enforce a handful of product guardrails, not merely style them:
 *
 * 1. **`mapped: false` is a valid, plain answer -- never rendered as an error.** A persona whose
 *    notes describe no mechanical methodology, or one with no current-bullish ticker to attach a
 *    card to, is an expected outcome the contract names explicitly (`reason` says which). It renders
 *    in the same quiet, informational tone as `PersonaProfile.tsx`'s "never consolidated" empty
 *    state -- no `role="alert"`, no red border -- while an actual `state.phase === "error"` (the
 *    network/`409`/`503` call itself failing) keeps the loud `callout-danger` treatment every other
 *    persona panel uses for that.
 * 2. **The fidelity meter is the honesty signal, always shown alongside a mapped card.** "expresses
 *    `{represented}` of `{total}` techniques" plus the named `unrepresentable` list says outright how
 *    much of a rich, discursive methodology a fixed DSL can actually hold -- a low fidelity score is
 *    the finding, not a bug to hide.
 * 3. **`caveat` is always visible whenever a draft exists** (mapped or not), and this is
 *    unconditionally framed as an exploration lens, never a recommendation -- matching the same
 *    no-advice discipline `PersonaBook.tsx`/`InfluencerWatchlist` render for their own `caveat`s.
 * 4. **`degraded` is always visible when true**, the same fact-check-failed wording every other
 *    persona panel's `degraded` flag uses (see `PersonaProfile.tsx`'s rule 3).
 * 5. **The produced `card` is opaque JSON to this component** (`Record<string, unknown>`, the
 *    backend's own `dict[str, object]`) -- it renders every key/value pair it is handed via
 *    `StatGrid` rather than assuming any particular rule-shape's field names, so a new rule shape
 *    needs no change here.
 * 6. **`history` is a plain list, oldest concern first: what was drafted, and when** -- filename plus
 *    `formatRelativeAge(saved_at)`, matching `PersonaCard.tsx`'s own relative-age convention.
 *
 * **Internationalised** through `personaProfile.strategyCard.*`. `reason`/`rationale`/`caveat`,
 * every `card` key/value, and every `unrepresentable` entry are the model's/backend's own words and
 * render verbatim; everything else routes through `t()`.
 */
import { CitationList } from "@/components/CitationList";
import StatGrid from "@/components/StatGrid";
import { StatusPill } from "@/components/StatusPill";
import { formatRelativeAge, type SavedStrategyDraft, type StrategyCardDraft } from "@/api/personas";
import { useT } from "@/i18n";

import "./PersonaProfileExtras.css";

/** Distinguishes "never drafted" / "drafting now" / "the call itself failed" from a drafted card --
 * see this file's own docstring, rule 1, for why `mapped: false` inside `"drafted"` is NOT its own
 * phase here: it is a valid shape of a successful draft, not a distinct fetch state. `Personas.tsx`
 * is the only producer. */
export type StrategyCardState =
  | { phase: "idle" }
  | { phase: "pending" }
  | { phase: "error"; message: string }
  | { phase: "drafted"; draft: StrategyCardDraft };

/** The parent-owned state of the "Promote to library" action, kept presentational here exactly like
 * `StrategyCardState`: `PersonaDetail` fires `POST .../strategy-cards/{version}/promote` and threads
 * the result in. `"exists"` is a `409` -- the card is already on the shelf, an idempotent no-op worth
 * stating plainly, not an error. */
export type PromoteState =
  | { phase: "idle" }
  | { phase: "pending" }
  | { phase: "done"; agentId: string }
  | { phase: "exists" }
  | { phase: "error"; message: string };

export interface PersonaStrategyCardProps {
  displayName: string;
  state: StrategyCardState;
  /** Prior persisted drafts, newest first. May be empty. */
  history: SavedStrategyDraft[];
  onDraft: () => void;
  /** Promote the drafted (mapped) card onto the competition library shelf, by its saved version. A
   * caller that omits this gets no promote button; `promoteState` reflects the last attempt. */
  onPromote?: (version: number) => void;
  promoteState?: PromoteState;
}

export default function PersonaStrategyCard({
  displayName,
  state,
  history,
  onDraft,
  onPromote,
  promoteState,
}: PersonaStrategyCardProps) {
  const { t } = useT();
  const pending = state.phase === "pending";

  return (
    <div className="panel persona-strategy-card">
      <h3 className="persona-card-subhead">{t("personaProfile.strategyCard.heading")}</h3>
      <p className="muted persona-strategy-card-hint">
        {t("personaProfile.strategyCard.idleHint", { name: displayName })}
      </p>

      <button type="button" onClick={onDraft} disabled={pending}>
        {pending ? t("personaProfile.strategyCard.drafting") : t("personaProfile.strategyCard.draftButton")}
      </button>

      {state.phase === "error" && (
        <div className="callout callout-danger persona-strategy-card-error" role="alert">
          {state.message}
        </div>
      )}

      {state.phase === "drafted" && (
        <DraftBody
          draft={state.draft}
          {...(onPromote ? { onPromote } : {})}
          {...(promoteState ? { promoteState } : {})}
        />
      )}

      <StrategyCardHistory history={history} />
    </div>
  );
}

/** One drafted card. `draft.mapped === false` renders `draft.reason` as a plain, valid answer (rule
 * 1 above); `draft.mapped === true` renders the opaque `card`, `rationale`, citations and the
 * fidelity honesty meter. `caveat` and `degraded` (when true) render in both branches. */
function DraftBody({
  draft,
  onPromote,
  promoteState,
}: {
  draft: StrategyCardDraft;
  onPromote?: (version: number) => void;
  promoteState?: PromoteState;
}) {
  const { t } = useT();
  return (
    <div className="persona-strategy-card-body">
      <span className="badge persona-strategy-card-version">
        {t("personaProfile.strategyCard.versionBadge", { version: draft.version })}
      </span>

      {draft.degraded && (
        <div className="callout callout-warn persona-strategy-card-degraded" role="alert">
          <strong>{t("personaProfile.strategyCard.degradedTitle")}</strong>{" "}
          {t("personaProfile.strategyCard.degradedBody")}
        </div>
      )}

      {!draft.mapped ? (
        <div className="persona-strategy-card-unmapped">
          <span className="muted persona-strategy-card-reason-label">
            {t("personaProfile.strategyCard.reasonLabel")}
          </span>
          <p className="persona-strategy-card-reason">{draft.reason}</p>
        </div>
      ) : (
        <div className="persona-strategy-card-mapped">
          {draft.rule_shape !== null && (
            <p className="persona-strategy-card-rule-shape">
              <span className="muted">{t("personaProfile.strategyCard.ruleShapeLabel")}</span>{" "}
              <code>{draft.rule_shape}</code>
            </p>
          )}

          {draft.card !== null && (
            <div className="persona-strategy-card-card">
              <h4 className="persona-card-subhead">{t("personaProfile.strategyCard.cardHeading")}</h4>
              <CardFields card={draft.card} />
              {onPromote && (
                <PromoteControl
                  version={draft.version}
                  onPromote={onPromote}
                  state={promoteState ?? { phase: "idle" }}
                />
              )}
            </div>
          )}

          <p className="persona-strategy-card-rationale">
            <span className="muted">{t("personaProfile.strategyCard.rationaleLabel")}</span>{" "}
            {draft.rationale}
          </p>

          <CitationList citations={draft.citations} className="persona-strategy-card-citations" />

          <FidelityMeter draft={draft} />
        </div>
      )}

      <p className="muted persona-strategy-card-caveat">
        <span className="persona-strategy-card-caveat-label">{t("personaProfile.strategyCard.caveatLabel")}</span>{" "}
        {draft.caveat}
      </p>
    </div>
  );
}

/** "Promote to library" for the drafted (mapped) card. Presentational, per this file's rule 0: the
 * click calls `onPromote(version)` and `PersonaDetail` owns the request, threading the outcome back
 * as `state`. The result is a `StatusPill` in the app's status vocabulary -- `ok` once written (with
 * the shelf `agent_id`), `info` for a `409` already-on-shelf (an idempotent no-op, not an error), and
 * `bad` for a real failure carrying the backend's own message. The button disables in flight and once
 * done so a second click cannot re-fire. */
function PromoteControl({
  version,
  onPromote,
  state,
}: {
  version: number;
  onPromote: (version: number) => void;
  state: PromoteState;
}) {
  const { t } = useT();
  const pending = state.phase === "pending";
  return (
    <div className="persona-strategy-card-promote">
      <button
        type="button"
        onClick={() => onPromote(version)}
        disabled={pending || state.phase === "done"}
      >
        {pending
          ? t("personaProfile.strategyCard.promote.promoting")
          : t("personaProfile.strategyCard.promote.button")}
      </button>
      {state.phase === "done" && (
        <StatusPill
          tone="ok"
          label={t("personaProfile.strategyCard.promote.done")}
          detail={state.agentId}
        />
      )}
      {state.phase === "exists" && (
        <StatusPill tone="info" label={t("personaProfile.strategyCard.promote.exists")} />
      )}
      {state.phase === "error" && (
        <StatusPill
          tone="bad"
          label={t("personaProfile.strategyCard.promote.errorLabel")}
          detail={state.message}
        />
      )}
    </div>
  );
}

/** The produced `card` is opaque `Record<string, unknown>` to this component (rule 5 in the file
 * docstring) -- every key renders via `StatGrid`, objects/arrays as compact JSON, so a new rule
 * shape's fields show up here with no code change. */
function CardFields({ card }: { card: Record<string, unknown> }) {
  const entries = Object.entries(card);
  if (entries.length === 0) return null;
  return (
    <StatGrid
      items={entries.map(([key, value]) => ({
        label: key,
        value: formatCardValue(value),
      }))}
    />
  );
}

function formatCardValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

/** The honesty signal on a mapped card: how much of the persona's actual methodology the fixed DSL
 * could express, plus the named techniques it could not -- see the file docstring, rule 2. */
function FidelityMeter({ draft }: { draft: StrategyCardDraft }) {
  const { t } = useT();
  if (draft.fidelity === null) return null;
  return (
    <div className="persona-strategy-card-fidelity">
      <span className="persona-strategy-card-fidelity-summary">
        {t("personaProfile.strategyCard.fidelitySummary", {
          represented: draft.techniques_represented,
          total: draft.techniques_total,
        })}
      </span>
      {draft.unrepresentable.length > 0 && (
        <div className="persona-strategy-card-unrepresentable">
          <span className="muted">{t("personaProfile.strategyCard.unrepresentableLabel")}</span>
          <ul className="persona-vocab-list">
            {draft.unrepresentable.map((technique, i) => (
              <li key={`${technique}-${i}`} className="persona-vocab-chip">
                {technique}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function StrategyCardHistory({ history }: { history: SavedStrategyDraft[] }) {
  const { t } = useT();
  return (
    <div className="persona-strategy-card-history">
      <h4 className="persona-card-subhead">{t("personaProfile.strategyCard.historyHeading")}</h4>
      {history.length === 0 ? (
        <p className="muted persona-strategy-card-history-empty">
          {t("personaProfile.strategyCard.historyEmpty")}
        </p>
      ) : (
        <ul className="persona-strategy-card-history-list">
          {history.map((saved) => (
            <li key={saved.filename} className="persona-strategy-card-history-item">
              <span className="persona-strategy-card-history-filename">{saved.filename}</span>
              <span className="muted persona-strategy-card-history-age">
                {formatRelativeAge(saved.saved_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
