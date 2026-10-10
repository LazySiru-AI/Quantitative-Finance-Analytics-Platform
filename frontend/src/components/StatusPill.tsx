/**
 * One pill, six tones, for every state this app currently spells out in a sentence.
 *
 * The codebase had ~40 page-prefixed badge classes (`desk-dormant-badge`, `comp-job-status-running`,
 * `wf-stage-degraded`, `persona-outcome-badge`, `live-tape-tag-held`, ...) that between them express
 * about six meanings, plus a lot of prose doing a badge's job: "This desk has not opened a position
 * since inception", "The mark is {days} days behind -- treat every figure on this page as that many
 * days stale". A pill reads in a glance; the sentence does not.
 *
 * **Colour is never the only signal.** This is the rule `styles.css` states in its own comments and
 * it is enforced here structurally: `label` is required, so every tone always ships with words. The
 * `neutral` tone additionally carries a dashed border and italic text, because an unknown must never
 * read as a quiet "no" -- the same reasoning `.state-pill.state-unknown` documents.
 *
 * The six tones absorb the `wf-stage-*` / `vibe-stage-*` / `ta-stage-*` vocabulary that three pages
 * already duplicate between them:
 *
 *   pending -> neutral   running -> info      succeeded -> ok
 *   degraded -> warn     failed -> bad        blocked -> special
 */
import { useT } from "@/i18n/useT";
import type { MessageKey } from "@/i18n/catalog";

import "./StatusPill.css";

/**
 * What the pill means, not what colour it is -- callers pick the meaning and the palette follows,
 * so a theme change never has to be chased through call sites.
 *
 * `ok` good / passed / held        -> --up
 * `warn` caution / stale / dormant -> --warn
 * `bad` failed / rejected / loss   -> --down
 * `info` active / running / signal -> --accent
 * `special` blocked / exploratory  -> --accent-2 (dashed, hatched: stopped before it started)
 * `neutral` unknown / none / n-a   -> --muted (dashed + italic: never reads as "false")
 */
export type PillTone = "ok" | "warn" | "bad" | "info" | "special" | "neutral";

export interface StatusPillProps {
  tone: PillTone;
  /** The visible words. Short -- three words at most, per docs/COPY-STYLE.md. */
  label: string;
  /**
   * The *why*, when there is one. Rendered as a native `title` for pointer users and, more
   * importantly, exposed to assistive tech via `aria-description`. For anything a reader genuinely
   * needs, prefer an adjacent `InfoNote` -- `title` is invisible on touch and this is a convenience,
   * not a place to hide a caveat.
   */
  detail?: string | undefined;
  className?: string | undefined;
  "data-testid"?: string | undefined;
}

export function StatusPill({ tone, label, detail, className, "data-testid": dataTestId }: StatusPillProps) {
  const classes = ["status-pill", `status-pill-${tone}`];
  if (className) classes.push(className);
  return (
    <span
      className={classes.join(" ")}
      title={detail}
      aria-description={detail}
      data-testid={dataTestId}
    >
      {label}
    </span>
  );
}

export interface TranslatedStatusPillProps extends Omit<StatusPillProps, "label" | "detail"> {
  labelKey: MessageKey;
  detailKey?: MessageKey | undefined;
  params?: Readonly<Record<string, string | number>> | undefined;
}

/**
 * The same pill, taking catalog keys instead of strings.
 *
 * Most call sites have a key, not a string, and would otherwise each call `useT()` just to unwrap
 * it. Both languages are guaranteed present by `MessagePair`, so there is no fallback path.
 */
export function TranslatedStatusPill({
  labelKey,
  detailKey,
  params,
  ...rest
}: TranslatedStatusPillProps) {
  const { t } = useT();
  return <StatusPill {...rest} label={t(labelKey, params)} detail={detailKey ? t(detailKey, params) : undefined} />;
}

export default StatusPill;
