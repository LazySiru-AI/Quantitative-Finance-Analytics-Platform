/**
 * What changed in a persona's memory between two consolidations -- is the profile improving, or just
 * churning the same claims across re-citations? Sits alongside `PersonaProfile.tsx` (the current
 * standing profile) on `/personas`: this panel looks backward across versions instead of at the
 * latest one.
 *
 * **Presentational only -- this component fetches nothing.** `Personas.tsx` owns the version list
 * (from the persona's `profile_version`) and firing `GET /{slug}/profile/diff?from=&to=`, the same
 * split every other persona panel's own docstring establishes. `state` is the discriminated union
 * below rather than a bare `ProfileDiff | null`, so "never compared" / "comparing now" / "the fetch
 * failed" cannot be confused with a loaded diff.
 *
 * Two rules this file exists to enforce:
 *
 * 1. **Every change's `text` renders verbatim, with its citations, never summarised or truncated** --
 *    the whole point of a diff is to let a reader see exactly what was added, removed, or re-cited,
 *    not a paraphrase of it.
 * 2. **Changes are grouped by `kind` (added/removed/recited), each item tagged with its `section`
 *    (belief/playbook/methodology)** -- a flat, unordered list of a dozen changes reads as noise; the
 *    three-way split up front (what's new, what's gone, what just got re-cited) is the actual
 *    finding. An empty `changes` array renders a plain "no changes" note rather than three empty
 *    section headings.
 *
 * **Internationalised** through `personaProfile.diff.*`. Every `ClaimChange.text` and citation
 * `note_id` stay verbatim; everything else routes through `t()`.
 */
import { useId } from "react";

import { CitationList } from "@/components/CitationList";
import type { ClaimChange, ProfileDiff } from "@/api/personas";
import { type MessageKey, useT } from "@/i18n";

import "./PersonaProfileExtras.css";

/** Distinguishes "never compared" / "comparing now" / "the fetch failed" from a loaded diff --
 * `Personas.tsx` is the only producer. */
export type ProfileDiffState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "loaded"; diff: ProfileDiff };

export interface PersonaProfileDiffProps {
  state: ProfileDiffState;
  /** Versions available to compare (e.g. [1,2,3,4]); page supplies them. */
  versions: number[];
  from: number | null;
  to: number | null;
  onFromChange: (v: number) => void;
  onToChange: (v: number) => void;
  onCompare: () => void;
}

const KINDS: ClaimChange["kind"][] = ["added", "removed", "recited"];

const KIND_LABEL_KEYS: Record<ClaimChange["kind"], MessageKey> = {
  added: "personaProfile.diff.kind.added",
  removed: "personaProfile.diff.kind.removed",
  recited: "personaProfile.diff.kind.recited",
};

const SECTION_LABEL_KEYS: Record<ClaimChange["section"], MessageKey> = {
  belief: "personaProfile.diff.section.belief",
  playbook: "personaProfile.diff.section.playbook",
  methodology: "personaProfile.diff.section.methodology",
};

export default function PersonaProfileDiff({
  state,
  versions,
  from,
  to,
  onFromChange,
  onToChange,
  onCompare,
}: PersonaProfileDiffProps) {
  const { t } = useT();
  const fromId = useId();
  const toId = useId();
  const canCompare = from !== null && to !== null && state.phase !== "loading";

  return (
    <div className="panel persona-profile-diff">
      <h3 className="persona-card-subhead">{t("personaProfile.diff.heading")}</h3>

      <div className="persona-profile-diff-controls">
        <label className="persona-profile-diff-field" htmlFor={fromId}>
          {t("personaProfile.diff.fromLabel")}
          <VersionSelect id={fromId} versions={versions} value={from} onChange={onFromChange} />
        </label>
        <label className="persona-profile-diff-field" htmlFor={toId}>
          {t("personaProfile.diff.toLabel")}
          <VersionSelect id={toId} versions={versions} value={to} onChange={onToChange} />
        </label>
        <button type="button" onClick={onCompare} disabled={!canCompare}>
          {t("personaProfile.diff.compareButton")}
        </button>
      </div>

      {state.phase === "idle" && (
        <p className="muted persona-profile-diff-idle">{t("personaProfile.diff.idleHint")}</p>
      )}

      {state.phase === "loading" && (
        <div className="placeholder persona-profile-diff-loading">{t("personaProfile.diff.loading")}</div>
      )}

      {state.phase === "error" && (
        <div className="callout callout-danger persona-profile-diff-error" role="alert">
          {state.message}
        </div>
      )}

      {state.phase === "loaded" && <DiffBody diff={state.diff} />}
    </div>
  );
}

function VersionSelect({
  id,
  versions,
  value,
  onChange,
}: {
  id: string;
  versions: number[];
  value: number | null;
  onChange: (v: number) => void;
}) {
  const { t } = useT();
  return (
    <select
      id={id}
      className="persona-profile-diff-select"
      value={value === null ? "" : String(value)}
      onChange={(e) => {
        const parsed = Number(e.target.value);
        if (!Number.isNaN(parsed)) onChange(parsed);
      }}
    >
      <option value="" disabled>
        {t("personaProfile.diff.selectPlaceholder")}
      </option>
      {versions.map((v) => (
        <option key={v} value={v}>
          {t("personaProfile.diff.versionOption", { version: v })}
        </option>
      ))}
    </select>
  );
}

function DiffBody({ diff }: { diff: ProfileDiff }) {
  const { t } = useT();
  return (
    <div className="persona-profile-diff-body">
      <div className="persona-profile-diff-summary">
        <span className="badge">
          {t("personaProfile.diff.versionRange", { from: diff.from_version, to: diff.to_version })}
        </span>
        <span className="muted persona-profile-diff-counts">
          {t("personaProfile.diff.counts", {
            added: diff.added,
            removed: diff.removed,
            recited: diff.recited,
          })}
        </span>
      </div>

      {diff.changes.length === 0 ? (
        <p className="muted persona-profile-diff-empty">{t("personaProfile.diff.empty")}</p>
      ) : (
        KINDS.map((kind) => {
          const items = diff.changes.filter((c) => c.kind === kind);
          if (items.length === 0) return null;
          return <ChangeGroup key={kind} kind={kind} changes={items} />;
        })
      )}
    </div>
  );
}

function ChangeGroup({ kind, changes }: { kind: ClaimChange["kind"]; changes: ClaimChange[] }) {
  const { t } = useT();
  return (
    <div className={`persona-card-section persona-profile-diff-group persona-profile-diff-group-${kind}`}>
      <h4 className="persona-card-subhead">{t(KIND_LABEL_KEYS[kind])}</h4>
      <ul className="persona-claim-list">
        {changes.map((change, i) => (
          <ChangeItem key={i} change={change} />
        ))}
      </ul>
    </div>
  );
}

function ChangeItem({ change }: { change: ClaimChange }) {
  const { t } = useT();
  return (
    <li className="persona-claim persona-profile-diff-change">
      <span className="badge persona-profile-diff-change-section">
        {t(SECTION_LABEL_KEYS[change.section])}
      </span>
      <span className="persona-claim-text">{change.text}</span>
      <CitationList citations={change.citations} className="persona-profile-diff-change-citations" />
    </li>
  );
}
