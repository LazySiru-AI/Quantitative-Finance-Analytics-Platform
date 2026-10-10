/**
 * The "Calendar" card on Overview — upcoming FOMC meetings, scheduled federal economic releases
 * (PCE, CPI, the jobs report, GDP, PPI, retail sales) and earnings dates for the user's holdings,
 * in one chronological list. Presentational: it takes a fully loaded `EventCalendar`
 * (the wire type from `@/api/calendar`) and renders it. `pages/Overview.tsx`'s `EventCalendarSection`
 * owns the loading/error/empty phase gating (matching every other Overview section's template) and
 * only mounts this component once data has actually arrived.
 *
 * **Three honesty rules this card exists to keep, all inherited from the calendar endpoint rather
 * than invented here** (see `Overview.tsx`'s own module docstring for the page-wide version of this
 * discipline):
 *
 * - An `estimated` event is a vendor's projection, not a date the company promised. It is marked
 *   with a visible "est." badge; a `confirmed` event carries no such badge at all, so silence reads
 *   as confirmed and the badge is the only way to read otherwise.
 * - `holdings_covered`/`holdings_total` renders as an explicit denominator. Three earnings dates out
 *   of three holdings and three out of forty tell different stories from the same numerator, so the
 *   numerator never appears without it.
 * - Every entry in `warnings[]` renders visibly via the shared `.callout.callout-warn` treatment — a
 *   degraded earnings sweep is shown, not swallowed.
 *
 * FOMC dates sourced from `bundled_schedule` (a committed snapshot rather than a live Fed page) carry
 * a "snapshot" badge on the row, plus one explanatory line when at least one such row is present, so
 * that provenance is visible without requiring a reader to already know what the source enum means.
 *
 * All three kinds stay in one date-ordered list — grouping them into separate lists would break the
 * ordering the brief asks for — so they are told apart at a glance instead, via a per-row kind badge
 * and a left-border accent (`event-calendar-row-fomc` / `-earnings` / `-economic_release`).
 *
 * An economic release is its own kind rather than being folded in with FOMC under one "macro"
 * label: an FOMC meeting is a decision the Committee is about to make, a release is a measurement
 * already taken that is about to be published, and a reader scanning for "when is the next inflation
 * print" is looking for exactly that distinction. Release rows carry no ticker and no "est." badge —
 * the dates come from the agencies' own published schedules via FRED, so they are confirmed, and
 * silence on the badge is what "confirmed" looks like everywhere else on this card.
 */
import {
  daysUntil,
  formatEventDateRange,
  type CalendarEventItem,
  type EventCalendar as EventCalendarData,
} from "@/api/calendar";
import { ScrollRegion } from "@/components/ScrollPanel";
import StatusPill from "@/components/StatusPill";
import { useT, type Language, type Translator } from "@/i18n";
import {
  hasUntranslatedCalendarProse,
  resolveCalendarProse,
  resolveVocab,
} from "@/i18n/messages/serverVocab";

import "./EventCalendar.css";

/** "today" / "tomorrow" / "in N days" for a non-negative offset; the calendar endpoint only ever
 *  returns *upcoming* events, but a negative offset (today's fetch racing past midnight, a clock
 *  skew) is handled rather than left to print "in -1 days". */
/**
 * The row's date, or a two-day span, in the reader's own language.
 *
 * `formatEventDateRange` in `api/calendar.ts` does the same collapsing (`"Sep 15-16, 2026"`, and the
 * full-date forms when a span crosses a month or a year) but formats against the *browser* locale --
 * `toLocaleDateString(undefined, ...)` -- which is not the app's language toggle. Under 한국어 that
 * printed English month names inside an otherwise Korean card. This wraps it: English is the helper's
 * own output, byte for byte, and Korean is built here with the same UTC-safe `Date.UTC` idiom the
 * helper documents, so `"2026-08-07"` never renders as the 6th west of Greenwich.
 *
 * The wrapper lives here rather than in `api/calendar.ts` because that module is shared and owned
 * elsewhere; when it grows a locale parameter this function should collapse into a call to it.
 */
function eventDateText(date: string, endDate: string | null, lang: Language): string {
  if (lang === "en") return formatEventDateRange(date, endDate);

  const start = utcDate(date);
  if (!start) return formatEventDateRange(date, endDate);
  const end = endDate && endDate !== date ? utcDate(endDate) : null;
  const full = (d: Date) =>
    d.toLocaleDateString("ko-KR", {
      year: "numeric",
      month: "long",
      day: "numeric",
      timeZone: "UTC",
    });
  if (!end) return full(start);
  // Korean reads largest unit first, so a same-month span collapses on the tail (the day), not the
  // head: 2026년 9월 15-16일.
  if (start.getUTCFullYear() === end.getUTCFullYear() && start.getUTCMonth() === end.getUTCMonth()) {
    return `${full(start)}–${end.getUTCDate()}일`;
  }
  return `${full(start)} – ${full(end)}`;
}

function utcDate(date: string): Date | null {
  const [year, month, day] = date.split("-").map(Number);
  if (!year || !month || !day) return null;
  return new Date(Date.UTC(year, month - 1, day));
}

/**
 * When in the session an event lands, or `null` for `"unknown"` so the field is omitted rather than
 * printing the word "unknown" -- the same contract `describeTiming` in `api/calendar.ts` keeps, with
 * the three phrases translated. An unrecognised timing token falls back to the token itself rather
 * than throwing, for the reason `kindLabel` below spells out.
 */
function timingLabel(timing: CalendarEventItem["timing"], t: Translator): string | null {
  if (timing === "unknown") return null;
  return resolveVocab(t, `serverVocab.calendar.timing.${timing}`, timing);
}

function relativeLabel(days: number, t: Translator): string {
  if (days === 0) return t("misc.eventCalendar.relative.today");
  if (days === 1) return t("misc.eventCalendar.relative.tomorrow");
  if (days > 1) return t("misc.eventCalendar.relative.inDays", { days });
  if (days === -1) return t("misc.eventCalendar.relative.yesterday");
  return t("misc.eventCalendar.relative.daysAgo", { days: Math.abs(days) });
}

/**
 * `expanded` controls only the card's *height*, not what it shows. Collapsed (the default) the card
 * is capped to roughly its neighbour's height on the Overview grid and its body scrolls; expanded it
 * drops the cap and lets the whole list stand at full height. Both are driven by CSS off the
 * `expanded` class — the toggle never hides a row, so find-in-page and any assistive reader still
 * reach every event in either state. The height cap itself lives in `EventCalendar.css`, so a card
 * mounted outside the Overview grid (with no `onToggleExpand`) simply renders every row.
 */
export default function EventCalendar({
  calendar,
  expanded = true,
  onToggleExpand,
}: {
  calendar: EventCalendarData;
  expanded?: boolean;
  onToggleExpand?: () => void;
}) {
  const { t, lang } = useT();
  const events = calendar.events;
  // Which of this card's words came from the server and have no key: a release this build has never
  // seen, a hand-written earnings note, and every `warnings[]` message (free diagnostic prose by
  // definition). Korean only -- in English there is nothing to disclose.
  const untranslated =
    (lang === "ko" && calendar.warnings.length > 0) ||
    hasUntranslatedCalendarProse(
      lang,
      events.flatMap((event) => [event.title, event.detail]),
    );

  return (
    <div className={`panel event-calendar-panel${expanded ? " expanded" : ""}`}>
      <div className="event-calendar-head">
        <h2 className="event-calendar-heading">{t("misc.eventCalendar.heading")}</h2>
        {/* The honest half of this card's language story: the dates, kinds and badges are Korean, the
            release prose this build does not recognise is not. Saying so is cheaper for the reader
            than discovering it row by row. */}
        {untranslated && (
          <StatusPill
            tone="neutral"
            label={t("misc.pill.englishOnly")}
            detail={t("misc.pill.englishOnlyDetail")}
            data-testid="event-calendar-english-only"
          />
        )}
        {onToggleExpand && (
          <button
            type="button"
            className="decision-expand-btn"
            aria-expanded={expanded}
            onClick={onToggleExpand}
          >
            {expanded ? t("misc.eventCalendar.collapseButton") : t("misc.eventCalendar.expandButton")}
          </button>
        )}
      </div>

      <ScrollRegion
        size="md"
        label={t("misc.eventCalendar.heading")}
        expanded={expanded}
        className="event-calendar-scroll"
      >
        <p className="muted event-calendar-coverage">
          {t("misc.eventCalendar.coverage", {
            covered: calendar.holdings_covered,
            total: calendar.holdings_total,
          })}
        </p>

        {calendar.warnings.length > 0 && (
          <div className="event-calendar-warnings">
            {calendar.warnings.map((w, i) => (
              <div key={`${w.kind}-${i}`} className="callout callout-warn event-calendar-warning">
                {w.message}
              </div>
            ))}
          </div>
        )}

        {events.length === 0 ? (
          <p className="placeholder">{t("misc.eventCalendar.noEvents")}</p>
        ) : (
          <>
            {events.some((e) => e.source === "bundled_schedule") && (
              <p className="muted event-calendar-provenance">{t("misc.eventCalendar.snapshotProvenance")}</p>
            )}
            <ul className="event-calendar-list">
              {events.map((event, idx) => (
                <EventRow
                  key={`${event.kind}-${event.symbol ?? "none"}-${event.date}-${idx}`}
                  event={event}
                />
              ))}
            </ul>
          </>
        )}
      </ScrollRegion>
    </div>
  );
}

/**
 * The badge text for one row's kind.
 *
 * A lookup with a fallback, deliberately not a `switch` with an `assertNever` default. `kind` is a
 * server-supplied string; a backend that adds a fourth kind would, under a throwing exhaustiveness
 * check, take this whole card — and the Overview page around it — down at render time. A row
 * labelled with the raw kind is a cosmetic defect that still shows the reader the date; a thrown
 * error shows them nothing. The compile-time check that the union is complete lives in
 * `tests/test_frontend_contract.py`'s territory, not in a runtime throw.
 */
function kindLabel(kind: CalendarEventItem["kind"], t: Translator): string {
  const labels: Record<string, string> = {
    fomc: t("misc.eventCalendar.kind.fomc"),
    earnings: t("misc.eventCalendar.kind.earnings"),
    economic_release: t("misc.eventCalendar.kind.economicRelease"),
  };
  return labels[kind] ?? kind;
}

function EventRow({ event }: { event: CalendarEventItem }) {
  const { t, lang } = useT();
  const relative = relativeLabel(daysUntil(event.date), t);
  const timingText = timingLabel(event.timing, t);
  const title = resolveCalendarProse(t, lang, event.title);
  const detail = resolveCalendarProse(t, lang, event.detail);

  return (
    <li className={`event-calendar-row event-calendar-row-${event.kind}`}>
      <div className="event-calendar-row-head">
        <span className="event-calendar-date">
          {eventDateText(event.date, event.end_date, lang)}
        </span>
        <span className="muted event-calendar-relative">{relative}</span>
        <span className={`badge event-calendar-kind-badge event-calendar-kind-${event.kind}`}>
          {kindLabel(event.kind, t)}
        </span>
        <span className="event-calendar-title">{title}</span>
        {event.symbol && <span className="badge">{event.symbol}</span>}
        {event.confidence === "estimated" && (
          <span className="badge event-calendar-badge-estimated">{t("misc.eventCalendar.badge.estimated")}</span>
        )}
        {event.source === "bundled_schedule" && (
          <span className="badge event-calendar-badge-snapshot">{t("misc.eventCalendar.badge.snapshot")}</span>
        )}
      </div>
      {(timingText || detail) && (
        <div className="muted event-calendar-row-detail">
          {timingText}
          {timingText && detail ? " · " : ""}
          {detail}
        </div>
      )}
    </li>
  );
}
