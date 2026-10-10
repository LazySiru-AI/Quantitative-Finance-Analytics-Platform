/**
 * A short line that is always read, with the long explanation one click away.
 *
 * The problem this solves, measured: 349 of 2,537 catalog keys (14%) are prose of 80+ characters or
 * multiple sentences -- about 62,000 English characters of on-screen explanation, and the same again
 * in Korean. The longest single strings run 568, 564, 501, 463 and 458 characters, rendered as
 * always-on `<p className="muted">` blocks above the data they describe. The important sentence is
 * in there; it is just not findable.
 *
 * So: `summary` is the sentence that survives, always visible, budgeted (see docs/COPY-STYLE.md).
 * `children` is everything that used to be in the paragraph -- the caveats, the worked reasoning,
 * the "why" -- kept, not deleted, one disclosure away.
 *
 * **Why `<details>` and not a tooltip.** The app's only existing tooltip is the native `title`
 * attribute, used at ~110 sites: invisible on touch, unreachable by keyboard, and unsearchable by
 * find-in-page. `<details>` is the disclosure primitive this codebase already standardised on
 * (`Collapsible.tsx` argues the case at length) -- the browser owns the state, the keyboard, and the
 * screen-reader semantics, the content stays in the DOM for find-in-page, and it works on a phone.
 *
 * **What must not go behind the disclosure.** Anything a reader is worse off for not seeing: the tax
 * page's "calculation, not advice", the 13F reporting lag, in-sample warnings. Those keep a visible
 * short form (usually `summary` plus a `StatusPill`) and put only the elaboration inside.
 */
import { useT } from "@/i18n/useT";

import "./InfoNote.css";

export interface InfoNoteProps {
  /** The line that is always visible. One clause; see the budget in docs/COPY-STYLE.md. */
  summary: React.ReactNode;
  /** The long form. When omitted, this renders as a plain note with no disclosure affordance. */
  children?: React.ReactNode | undefined;
  /** Tighten the type for a note sitting under a stat or inside a table cell. */
  tone?: "default" | "quiet" | undefined;
  /** Open on first render. Defaults to `false` -- the point is that it starts collapsed. */
  defaultOpen?: boolean | undefined;
  className?: string | undefined;
  "data-testid"?: string | undefined;
}

export function InfoNote({
  summary,
  children,
  tone = "default",
  defaultOpen = false,
  className,
  "data-testid": dataTestId,
}: InfoNoteProps) {
  const { t } = useT();

  const classes = ["info-note", `info-note-${tone}`];
  if (className) classes.push(className);

  // No long form: there is nothing to disclose, so do not render a control that expands to nothing.
  if (!children) {
    return (
      <p className={classes.join(" ")} data-testid={dataTestId}>
        {summary}
      </p>
    );
  }

  return (
    <details className={classes.join(" ")} data-testid={dataTestId} open={defaultOpen || undefined}>
      <summary className="info-note-summary" aria-label={t("ui.info.more")}>
        <span className="info-note-mark" aria-hidden="true">
          ⓘ
        </span>
        <span className="info-note-line">{summary}</span>
      </summary>
      <div className="info-note-body">{children}</div>
    </details>
  );
}

export default InfoNote;
