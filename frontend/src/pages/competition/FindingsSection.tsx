/**
 * The Findings tab: a round's own written record, read off `SELECTION.md`, `DEFECTS.md`, and
 * whatever else the round left behind on disk -- answering one question for someone about to run
 * round N+1: *what did the last round leave unfinished?*
 *
 * Three parts, in this order:
 *
 *  1. **Carried forward** -- pinned at the top, everything with `carries_forward: true`. This is the
 *     agenda for the next round, so it is the first and most prominent thing on screen. Filtered on
 *     `carries_forward === true` alone, deliberately not on `kind === "follow-up"`: an unfixed
 *     `"defect"` carries forward too, and so can a `"finding"` whose prediction was contradicted --
 *     see `api/competition.ts`'s docstring on `RoundFinding`.
 *  2. **Full record** -- every entry the round wrote down, grouped by `kind` and filterable by it.
 *     Carried-forward entries reappear here (the API's `follow_ups` is a filtered *view* of the same
 *     `findings` list, not a disjoint one) -- each one carries its own "carries forward" badge here
 *     so it reads as the same item shown in its full context, not a second, unrelated one.
 *  3. **Round picker** -- newest-first by `sequence`, never by sorting `round_id` as a string (that
 *     puts `r9` above `r13`), and never filtered on `has_results`: a round can have a full written
 *     record (a `SELECTION.md`) with no run files at all.
 *
 * `kind` is always rendered through `findingKindLabel`, never by indexing `FINDING_KIND_LABELS`
 * directly and never by a `switch` -- a fifth kind arriving from the backend renders under its own raw
 * key instead of crashing or going blank, matching the module docstring in `api/competition.ts`.
 *
 * `body` is hand-written markdown text lifted off disk. It is rendered as plain text -- `pre-wrap`
 * only, never `dangerouslySetInnerHTML` -- so a stray `<` in a card rule can never be read as markup.
 */
import { useMemo, useState } from "react";

import { findingKindLabel, type FindingsResponse, type RoundFinding, type RoundSummary } from "@/api/competition";
import { ScrollRegion } from "@/components/ScrollPanel";
import { useT } from "@/i18n";

import { roundOptionText } from "./roundOption";

import "./FindingsSection.css";

type Phase = "loading" | "loaded" | "error";

export interface FindingsSectionProps {
  rounds: RoundSummary[];
  roundsPhase: Phase;
  selectedRoundId: string | null;
  onSelectRound: (roundId: string) => void;
  findings: FindingsResponse | null;
  phase: Phase;
  message: string | null;
  /** True when the round exists but the endpoint answered 404 -- a designed empty state, not an
   * error. */
  notFound: boolean;
}

/** The four kinds the contract documents, in the fixed order the record reads best in -- matching
 * `Competition.tsx`'s `GATE_ORDER` pattern. Anything the backend adds later that is not one of these
 * still renders, appended after them in first-seen order rather than dropped -- see `orderedKinds`. */
const KIND_ORDER: string[] = ["finding", "follow-up", "defect", "decision"];

/** Every kind actually present in `findings`, in `KIND_ORDER` first, then any kind this page has
 * never seen before in first-seen order. Never assumes the four documented kinds are the only ones
 * that will ever arrive. */
function orderedKinds(findings: RoundFinding[]): string[] {
  const present = new Set<string>(findings.map((f) => f.kind));
  const known = KIND_ORDER.filter((k) => present.has(k));
  const extra: string[] = [];
  const seenExtra = new Set<string>();
  for (const f of findings) {
    if (!KIND_ORDER.includes(f.kind) && !seenExtra.has(f.kind)) {
      seenExtra.add(f.kind);
      extra.push(f.kind);
    }
  }
  return [...known, ...extra];
}

function groupByKind(findings: RoundFinding[]): Map<string, RoundFinding[]> {
  const map = new Map<string, RoundFinding[]>();
  for (const f of findings) {
    const bucket = map.get(f.kind);
    if (bucket) bucket.push(f);
    else map.set(f.kind, [f]);
  }
  return map;
}

export default function FindingsSection({
  rounds,
  roundsPhase,
  selectedRoundId,
  onSelectRound,
  findings,
  phase,
  message,
  notFound,
}: FindingsSectionProps) {
  const { t } = useT();
  const [kindFilter, setKindFilter] = useState<string>("all");

  const picker = (
    <FindingsRoundPicker
      rounds={rounds}
      roundsPhase={roundsPhase}
      selectedRoundId={selectedRoundId}
      onSelectRound={onSelectRound}
    />
  );

  if (!selectedRoundId) {
    return (
      <>
        {picker}
        <div className="panel">
          <div className="placeholder">{t("competitionRounds.findings.pickRound")}</div>
        </div>
      </>
    );
  }

  if (phase === "loading") {
    return (
      <>
        {picker}
        <div className="panel">
          <div className="placeholder">
            {t("competitionRounds.findings.loadingRound", { roundId: selectedRoundId })}
          </div>
        </div>
      </>
    );
  }

  if (phase === "error") {
    return (
      <>
        {picker}
        <div className="panel">
          <div className="placeholder">{message ?? t("competitionRounds.findings.loadError")}</div>
        </div>
      </>
    );
  }

  if (notFound || !findings) {
    // Not a red error -- rounds legitimately have no written record. `SelectionSection` in
    // `Competition.tsx` treats its own 404 the same way, for the same reason.
    return (
      <>
        {picker}
        <div className="panel">
          <div className="placeholder">
            {t("competitionRounds.findings.notFound", { roundId: selectedRoundId })}
          </div>
        </div>
      </>
    );
  }

  if (findings.findings.length === 0) {
    // Two different facts, deliberately not collapsed into one message: a round with nothing in
    // `sources` never had a findings file to read at all, while a round with files in `sources` but
    // zero parsed entries had something read that turned out not to be parseable -- a reader planning
    // the next round needs to be able to tell those apart. See `FindingsResponse.sources`'s docstring.
    return (
      <>
        {picker}
        <div className="panel">
          {findings.sources.length === 0 ? (
            <div className="placeholder">
              {t("competitionRounds.findings.nothingWritten", { roundId: selectedRoundId })}
            </div>
          ) : (
            <div className="placeholder">
              {t("competitionRounds.findings.filesUnparseable", { roundId: selectedRoundId })}
              <ul className="findings-sources-list">
                {findings.sources.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </>
    );
  }

  const carriedForward = findings.findings.filter((f) => f.carries_forward === true);
  const kinds = orderedKinds(findings.findings);
  const grouped = groupByKind(findings.findings);
  const visibleKinds = kindFilter === "all" ? kinds : kinds.filter((k) => k === kindFilter);

  return (
    <>
      {picker}
      <CarriedForwardSection findings={carriedForward} />
      <FullRecordSection
        kinds={kinds}
        visibleKinds={visibleKinds}
        grouped={grouped}
        kindFilter={kindFilter}
        onKindFilterChange={setKindFilter}
      />
      {findings.sources.length > 0 && (
        <div className="panel">
          <h2 className="section-heading">{t("competitionRounds.findings.sourcesReadHeading")}</h2>
          <ul className="findings-sources-list">
            {findings.sources.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Round picker
// ---------------------------------------------------------------------------

function FindingsRoundPicker({
  rounds,
  roundsPhase,
  selectedRoundId,
  onSelectRound,
}: {
  rounds: RoundSummary[];
  roundsPhase: Phase;
  selectedRoundId: string | null;
  onSelectRound: (roundId: string) => void;
}) {
  // Newest-first by `sequence`, never by sorting `round_id` as a plain string -- that ordering puts
  // `r9` above `r13`. `has_results` is deliberately not filtered on here: a round can have findings
  // (a `SELECTION.md`) with no run files at all, and this picker's whole job is to still reach it.
  const { t, lang } = useT();
  const sortedRounds = useMemo(() => [...rounds].sort((a, b) => b.sequence - a.sequence), [rounds]);
  const selectedRound = sortedRounds.find((r) => r.round_id === selectedRoundId) ?? null;

  return (
    <div className="panel filter-bar findings-controls">
      <label className="bt-control-label" htmlFor="findings-round-select">
        {t("competitionRounds.roundLabel")}
        {roundsPhase === "loaded" && (
          <select
            id="findings-round-select"
            className="bt-entry-select"
            value={selectedRoundId ?? ""}
            onChange={(e) => onSelectRound(e.target.value)}
          >
            {sortedRounds.length === 0 && <option value="">{t("competitionRounds.noRoundsYet")}</option>}
            {/* Derived option text, never the authored `label` -- see `roundOption.ts`. The label
                itself renders under the select instead, where a sentence costs nothing. */}
            {sortedRounds.map((r) => (
              <option key={r.round_id} value={r.round_id}>
                {roundOptionText(r.round_id, lang)}
              </option>
            ))}
          </select>
        )}
        {roundsPhase === "loading" && (
          <span className="placeholder findings-round-note">{t("competitionRounds.findings.loadingRoundsNote")}</span>
        )}
        {roundsPhase === "error" && (
          <span className="placeholder findings-round-note">{t("competitionRounds.findings.roundsLoadErrorNote")}</span>
        )}
      </label>
      {selectedRound && <p className="muted comp-round-title">{selectedRound.label}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 1. Carried forward -- pinned agenda for the next round
// ---------------------------------------------------------------------------

function CarriedForwardSection({ findings }: { findings: RoundFinding[] }) {
  const { t } = useT();
  const heading = t("competitionRounds.findings.carriedForwardHeading");
  return (
    // No `aria-label` here -- the entry list below is itself a named `ScrollRegion` with this same
    // heading text, and a `<section>` with an accessible name is its own ARIA "region" landmark, so
    // giving both the identical name would put two same-named regions one inside the other. The `<h2>`
    // still carries the heading visually and in the page's heading outline.
    <section className="panel findings-carried-panel">
      <h2 className="section-heading findings-carried-heading">{heading}</h2>
      <p className="muted findings-carried-subtitle">
        {t("competitionRounds.findings.carriedForwardSubtitle")}
      </p>
      {findings.length === 0 ? (
        <div className="placeholder">{t("competitionRounds.findings.carriedForwardEmpty")}</div>
      ) : (
        <ScrollRegion size="md" label={heading} className="findings-entry-list">
          {findings.map((f) => (
            <FindingEntry key={`carried-${f.id}`} finding={f} pinned />
          ))}
        </ScrollRegion>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// 2. Full record -- everything the round wrote down, grouped by kind
// ---------------------------------------------------------------------------

function FullRecordSection({
  kinds,
  visibleKinds,
  grouped,
  kindFilter,
  onKindFilterChange,
}: {
  kinds: string[];
  visibleKinds: string[];
  grouped: Map<string, RoundFinding[]>;
  kindFilter: string;
  onKindFilterChange: (kind: string) => void;
}) {
  const { t } = useT();
  return (
    <>
      <div className="panel findings-filter-panel">
        <h2 className="section-heading">{t("competitionRounds.findings.fullRecordHeading")}</h2>
        <p className="muted findings-full-record-subtitle">
          {t("competitionRounds.findings.fullRecordSubtitle")}
        </p>
        <div
          className="timeframe-tabs findings-kind-filter"
          role="group"
          aria-label={t("competitionRounds.findings.filterByKind")}
        >
          <button
            type="button"
            aria-pressed={kindFilter === "all"}
            className={`timeframe-tab${kindFilter === "all" ? " active" : ""}`}
            onClick={() => onKindFilterChange("all")}
          >
            {t("common.all")}
          </button>
          {kinds.map((k) => (
            <button
              key={k}
              type="button"
              aria-pressed={kindFilter === k}
              className={`timeframe-tab${kindFilter === k ? " active" : ""}`}
              onClick={() => onKindFilterChange(k)}
            >
              {findingKindLabel(k)}
            </button>
          ))}
        </div>
      </div>

      {visibleKinds.map((kind) => (
        <FindingsKindGroup key={kind} kind={kind} findings={grouped.get(kind) ?? []} />
      ))}
    </>
  );
}

function FindingsKindGroup({ kind, findings }: { kind: string; findings: RoundFinding[] }) {
  const { t } = useT();
  const kindLabel = findingKindLabel(kind);
  return (
    // No `aria-label` here -- same reasoning as `CarriedForwardSection` above: the entry list is
    // itself a named `ScrollRegion` using this same kind label, so the `<section>` stays an
    // unnamed wrapper rather than a second, identically-named landmark around the first.
    <section className="panel findings-kind-group">
      <h3 className="findings-kind-group-heading">
        {kindLabel}{" "}
        <span className="findings-kind-group-count">
          {t(
            findings.length === 1
              ? "competitionRounds.findings.entryCount_one"
              : "competitionRounds.findings.entryCount_other",
            { count: findings.length },
          )}
        </span>
      </h3>
      {findings.length === 0 ? (
        <div className="placeholder">{t("competitionRounds.findings.noEntriesOfKind")}</div>
      ) : (
        <ScrollRegion size="md" label={kindLabel} className="findings-entry-list">
          {findings.map((f) => (
            <FindingEntry key={f.id} finding={f} pinned={false} />
          ))}
        </ScrollRegion>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// One entry, shared by the Carried-forward and Full-record sections
// ---------------------------------------------------------------------------

/**
 * One entry lifted out of a round's own written record. Rendered as `<details>`/`<summary>` so a long
 * `body` can be collapsed without losing keyboard/screen-reader access -- open by default, since the
 * whole point of this page is to be read, not to hide the record behind a click.
 *
 * `data-kind` on the wrapper and on the kind chip is how `FindingsSection.css` gives `"defect"` its
 * distinct `--warn`/`--down` treatment -- an attribute selector rather than an interpolated class name,
 * so an arbitrary `kind` string can never produce an invalid CSS class.
 */
function FindingEntry({ finding, pinned }: { finding: RoundFinding; pinned: boolean }) {
  const { t } = useT();
  return (
    <details
      className={`findings-entry${pinned ? " findings-entry-pinned" : ""}`}
      data-kind={finding.kind}
      open
    >
      <summary className="findings-entry-summary">
        <span className="findings-kind-chip" data-kind={finding.kind}>
          {findingKindLabel(finding.kind)}
        </span>
        <span className="findings-entry-title">{finding.title}</span>
        {finding.carries_forward && (
          <span
            className="findings-carries-badge"
            title={t("competitionRounds.findings.carriesForwardTitle")}
          >
            {t("competitionRounds.findings.carriesForwardBadge")}
          </span>
        )}
      </summary>
      <div className="findings-entry-body">
        {/* `body` is hand-written markdown text off disk -- rendered as plain text via React's own
            escaping, never `dangerouslySetInnerHTML`. `pre-wrap` (in the CSS) is what lets its
            paragraph breaks survive without treating any of it as markup. */}
        <p className="findings-body">{finding.body}</p>
        <div className="findings-source">{t("competitionRounds.sourceLine", { source: finding.source })}</div>
      </div>
    </details>
  );
}
