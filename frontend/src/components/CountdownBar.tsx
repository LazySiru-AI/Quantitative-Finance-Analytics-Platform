/**
 * CountdownBar -- a labelled progress bar toward a deadline, whose urgency intensifies (green -> amber
 * -> red) as the deadline nears.
 *
 * **Colour is never the only signal**, the same rule `StatusPill.tsx` states and enforces for its own
 * tones. The remaining-time caption always renders as visible text next to the bar -- "12 days left",
 * "Due today", "3 days overdue" -- and that same text is folded into the bar's `aria-label`, so a
 * screen reader hears the fact a sighted reader sees rather than a bare "82% progress" that says
 * nothing about how many days that is.
 *
 * Two independent ways to describe how close the deadline is:
 *
 *  - **Date mode** (`deadlineDate`): the caller has a calendar date -- e.g. tax year-end -- and this
 *    component derives both the caption and the bar's fill from it, via `periodDays` (the length of
 *    the countdown window the date ends; default 365 for an annual deadline).
 *  - **Fraction mode** (`fraction` + `remainingCaption`): the caller already has a 0..1 ratio in hand
 *    (e.g. spend used against a cap) and supplies its own caption -- this component has no way to
 *    word "how much is left" for a quantity whose units it does not know.
 *
 * `deadlineDate` wins when both are supplied, so a caller migrating from one mode to the other never
 * has to delete the other prop first.
 */
import { daysUntil } from "@/api/calendar";
import { useT } from "@/i18n";

import "./CountdownBar.css";

export type CountdownTone = "ok" | "warn" | "danger";

export interface CountdownBarProps {
  /** Short heading above the bar, e.g. "Tax year-end". Keep to a few words. */
  label: string;

  // --- date mode ---------------------------------------------------------------------------------
  /** `YYYY-MM-DD` deadline. When present, this component is in date mode and `fraction`/
   *  `remainingCaption` are ignored. */
  deadlineDate?: string | null;
  /** Length in days of the countdown window `deadlineDate` is the end of -- turns "N days left" into
   *  a 0..1 bar fill. Default 365 (an annual deadline). Only used in date mode. */
  periodDays?: number;
  /** Days remaining at or below which the tone escalates from "ok" to "warn". Default 30. Only used
   *  in date mode. */
  warnAtDays?: number;
  /** Days remaining at or below which the tone escalates to "danger". Default 7. Only used in date
   *  mode. */
  dangerAtDays?: number;
  /** Overrides "now" for tests -- forwarded straight to `daysUntil`. Only used in date mode. */
  today?: Date;

  // --- fraction mode -------------------------------------------------------------------------------
  /** A precomputed 0..1 fill for a caller that already knows elapsed/total (e.g. spend used against a
   *  cap) rather than a calendar date. Ignored when `deadlineDate` is given. */
  fraction?: number;
  /** The visible remaining-time text for fraction mode, e.g. "$420 of $500 used". Required with
   *  `fraction` -- this component has no way to word a quantity it does not know the units of. */
  remainingCaption?: string;
  /** Fill at or above which the tone escalates to "warn". Default 0.75. Only used in fraction mode. */
  warnAtFraction?: number;
  /** Fill at or above which the tone escalates to "danger". Default 0.9. Only used in fraction mode. */
  dangerAtFraction?: number;

  className?: string;
}

function clamp01(n: number): number {
  if (Number.isNaN(n)) return 0;
  return Math.min(1, Math.max(0, n));
}

export default function CountdownBar({
  label,
  deadlineDate,
  periodDays = 365,
  warnAtDays = 30,
  dangerAtDays = 7,
  today,
  fraction,
  remainingCaption,
  warnAtFraction = 0.75,
  dangerAtFraction = 0.9,
  className,
}: CountdownBarProps) {
  const { t } = useT();

  let fill: number;
  let tone: CountdownTone;
  let caption: string;

  if (deadlineDate) {
    // `today` is forwarded as-is: when it is `undefined`, `daysUntil`'s own default parameter
    // (`new Date()`) applies -- passing `undefined` through, rather than substituting `new Date()`
    // here too, keeps there being exactly one place that decides what "now" means.
    const remaining = daysUntil(deadlineDate, today);
    fill = clamp01(1 - Math.max(0, remaining) / Math.max(1, periodDays));
    if (remaining < 0) {
      tone = "danger";
      caption = t(
        remaining === -1 ? "misc.countdownBar.overdue_one" : "misc.countdownBar.overdue_other",
        { days: Math.abs(remaining) },
      );
    } else if (remaining === 0) {
      tone = "danger";
      caption = t("misc.countdownBar.dueToday");
    } else {
      tone = remaining <= dangerAtDays ? "danger" : remaining <= warnAtDays ? "warn" : "ok";
      caption = t(
        remaining === 1 ? "misc.countdownBar.daysLeft_one" : "misc.countdownBar.daysLeft_other",
        { days: remaining },
      );
    }
  } else {
    fill = clamp01(fraction ?? 0);
    tone = fill >= dangerAtFraction ? "danger" : fill >= warnAtFraction ? "warn" : "ok";
    caption = remainingCaption ?? "";
  }

  const percent = Math.round(fill * 100);

  return (
    <div className={`countdown-bar${className ? ` ${className}` : ""}`} data-tone={tone}>
      <div className="countdown-bar-head">
        <span className="countdown-bar-label">{label}</span>
        <span className={`countdown-bar-caption countdown-bar-caption-${tone}`}>{caption}</span>
      </div>
      <div
        className="countdown-bar-track"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={t("misc.countdownBar.ariaLabel", { label, caption })}
      >
        <div className={`countdown-bar-fill countdown-bar-fill-${tone}`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
