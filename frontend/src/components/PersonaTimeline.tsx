/**
 * One influencer's chronological timeline (Phase 6/7) -- a dated feed of what they actually said,
 * plus a per-symbol track of how their stance evolved over time. Sits alongside `PersonaCard.tsx`
 * (the rolling digest), `PersonaProfile.tsx` (the standing profile) and `PersonaScorecard.tsx` (the
 * backward-looking call record) under the same persona on `/personas`.
 *
 * **Presentational only -- this component fetches nothing.** A page-level caller owns fetching
 * `GET /{slug}/timeline` and hands it in as `state`, the same split every other persona component in
 * this codebase already follows. `state` is a discriminated union rather than a bare
 * `PersonaTimeline | null` so "still loading" / "the fetch actually failed" cannot be confused with a
 * loaded (possibly empty) timeline -- see `@/api/personas`'s docstring on `PersonaTimeline`.
 *
 * Two things this file exists to enforce, not merely style:
 *
 * 1. **A missing `published`/never renders a fake date.** `TimelineEntry.published` is nullable
 *    (the upstream sometimes cannot tell us) -- this shows `personaTimeline.dateUnknown` instead of
 *    silently passing `null` through a date formatter, which would print `"Invalid Date"` or worse,
 *    quietly coerce to "now".
 * 2. **A symbol whose stance actually changed is surfaced first, not buried in mention-count order.**
 *    "Changed" means the points do not all share one stance -- computed locally off `points` rather
 *    than trusted from arrival order, so this still reads correctly even if a caller mocks the API
 *    with an unordered fixture. Each track's own points render OLDEST first (per
 *    `@/api/personas`'s `StanceTimeline` docstring) so the arc reads forward in time.
 *
 * Empty `entries`/`stance_timelines` is a valid, common state (a persona with dated notes that have
 * no resolved stance changes, or vice versa) -- rendered as a plain note, never an error and never a
 * spinner.
 *
 * **Copy discipline.** `summary`/`reasoning`/`title` are the influencer's own words (or a model's
 * verbatim paraphrase of them) and render as-is; everything else routes through `t()`. This is a
 * descriptive record of what was said and when, never a signal and never advice -- the caption says
 * so up front, matching `PersonaScorecard.tsx`'s own framing.
 *
 * Each symbol links to `/symbol/{symbol}`, matching `PersonaCard.tsx`'s and `PersonaScorecard.tsx`'s
 * ticker-chip idiom.
 */
import { Link } from "react-router-dom";

import {
  formatRelativeAge,
  stanceLabel,
  type PersonaTimeline as Timeline,
  type StancePoint,
  type StanceTimeline,
  type TimelineEntry,
} from "@/api/personas";
import { CitationList } from "@/components/CitationList";
import { ScrollRegion } from "@/components/ScrollPanel";
import { useT } from "@/i18n";
import { safeHref } from "@/safeHref";

import "./PersonaTimeline.css";

/** Distinguishes "still loading" / "the fetch actually failed" from a loaded (possibly empty)
 * timeline -- see this file's own docstring. A page-level caller is the only producer. */
export type TimelineFetchState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "loaded"; timeline: Timeline };

export interface PersonaTimelineProps {
  displayName: string;
  state: TimelineFetchState;
}

export default function PersonaTimeline({ displayName, state }: PersonaTimelineProps) {
  const { t } = useT();
  return (
    <div className="panel persona-timeline">
      <h3 className="persona-card-subhead">{t("personaTimeline.heading")}</h3>
      <p className="muted persona-timeline-caption">
        {t("personaTimeline.caption", { name: displayName })}
      </p>

      <ScrollRegion size="lg" label={t("personaTimeline.heading")}>
        {state.phase === "loading" && (
          <div className="placeholder persona-timeline-loading">{t("personaTimeline.loading")}</div>
        )}

        {state.phase === "error" && (
          <div className="callout callout-danger persona-timeline-error" role="alert">
            {state.message}
          </div>
        )}

        {state.phase === "loaded" && <TimelineBody timeline={state.timeline} />}
      </ScrollRegion>
    </div>
  );
}

/** `true` when a symbol's stance track shows more than one distinct stance across its points --
 * computed locally rather than trusted from the backend's own ordering, so a track's "changed"
 * status is always consistent with the points actually rendered underneath it. An empty or
 * single-point track never counts as changed: there is nothing to compare. */
function stanceChanged(points: readonly StancePoint[]): boolean {
  if (points.length < 2) return false;
  const first = points[0]!.stance;
  return points.some((point) => point.stance !== first);
}

/** Stable sort: changed tracks first, ties broken by leaving the backend's own relative order in
 * place (which is already "changed first, then by mention count" per `@/api/personas`'s
 * `PersonaTimeline` docstring) -- this is a defensive re-assertion of that rule at render time, not
 * a competing sort. */
function orderStanceTimelines(tracks: readonly StanceTimeline[]): StanceTimeline[] {
  return tracks
    .map((track, index) => ({ track, index, changed: stanceChanged(track.points) }))
    .sort((a, b) => {
      if (a.changed !== b.changed) return a.changed ? -1 : 1;
      return a.index - b.index;
    })
    .map((entry) => entry.track);
}

function TimelineBody({ timeline }: { timeline: Timeline }) {
  const { t } = useT();
  const { entries, stance_timelines } = timeline;
  const isEmpty = entries.length === 0 && stance_timelines.length === 0;

  return (
    <div className="persona-timeline-body">
      {isEmpty && <p className="muted persona-timeline-empty">{t("personaTimeline.empty")}</p>}

      {stance_timelines.length > 0 && (
        <div className="persona-timeline-section">
          <h4 className="persona-card-subhead">{t("personaTimeline.stanceHeading")}</h4>
          <ul className="persona-timeline-stance-list">
            {orderStanceTimelines(stance_timelines).map((track, i) => (
              <StanceTrack key={`${track.symbol}-${i}`} track={track} />
            ))}
          </ul>
        </div>
      )}

      {entries.length > 0 && (
        <div className="persona-timeline-section">
          <h4 className="persona-card-subhead">{t("personaTimeline.feedHeading")}</h4>
          <ul className="persona-timeline-feed">
            {/* Composite key: the backend feed can repeat a note_id (the same video surfacing in
                more than one dated slice), so `note_id` alone is not unique across the feed. */}
            {entries.map((entry, i) => (
              <TimelineEntryRow key={`${entry.note_id}-${i}`} entry={entry} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** One symbol's stance arc -- points render in the order the API gives them (OLDEST first, per
 * `StanceTimeline`'s own docstring), never re-sorted here. */
function StanceTrack({ track }: { track: StanceTimeline }) {
  const { t } = useT();
  const changed = stanceChanged(track.points);

  return (
    <li
      className={`persona-timeline-stance-track${changed ? " persona-timeline-stance-changed" : ""}`}
      data-changed={changed ? "true" : "false"}
    >
      <div className="persona-timeline-stance-track-head">
        <Link className="persona-ticker-chip" to={`/symbol/${encodeURIComponent(track.symbol)}`}>
          <span className="position-symbol">{track.symbol}</span>
        </Link>
        {changed && (
          <span className="badge persona-timeline-changed-badge">
            {t("personaTimeline.stanceChangedBadge")}
          </span>
        )}
      </div>
      <ol className="persona-timeline-stance-points">
        {track.points.map((point, i) => (
          <li key={`${point.note_id}-${i}`} className="persona-timeline-stance-point">
            <span className="muted persona-timeline-stance-date" title={point.said_on}>
              {formatRelativeAge(point.said_on)}
            </span>
            <span className={`persona-ticker-stance persona-ticker-stance-${point.stance}`}>
              {stanceLabel(point.stance)}
            </span>
            <span className="persona-timeline-stance-reasoning">{point.reasoning}</span>
          </li>
        ))}
      </ol>
    </li>
  );
}

/** One note on the dated feed. `entries` arrives newest-first (per `PersonaTimeline`'s own
 * docstring) and is rendered in that order, never re-sorted here. */
function TimelineEntryRow({ entry }: { entry: TimelineEntry }) {
  const { t } = useT();
  const dateLabel =
    entry.published === null ? t("personaTimeline.dateUnknown") : formatRelativeAge(entry.published);
  const href = safeHref(entry.url);
  const titleLabel = entry.title ?? t("personaTimeline.untitled");

  return (
    <li className="persona-timeline-entry">
      <div className="persona-timeline-entry-head">
        <span className="muted persona-timeline-entry-date" title={entry.published ?? undefined}>
          {dateLabel}
        </span>
        {href === null ? (
          <span className="persona-timeline-entry-title">{titleLabel}</span>
        ) : (
          <a
            className="persona-timeline-entry-title"
            href={href}
            target="_blank"
            rel="noopener noreferrer"
          >
            {titleLabel}
          </a>
        )}
      </div>

      <p className="persona-timeline-entry-summary">{entry.summary}</p>

      {entry.themes.length > 0 && (
        <ul className="persona-timeline-entry-themes">
          {entry.themes.map((theme, i) => (
            <li key={i}>{theme}</li>
          ))}
        </ul>
      )}

      {entry.symbols.length > 0 && (
        <ul className="persona-timeline-entry-symbols">
          {entry.symbols.map((symbol, i) => (
            <li key={`${symbol}-${i}`}>
              <Link className="persona-ticker-chip" to={`/symbol/${encodeURIComponent(symbol)}`}>
                <span className="position-symbol">{symbol}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <CitationList citations={[entry.note_id]} />
    </li>
  );
}
