/**
 * A term of art, defined where it is used.
 *
 * The measured defect (UX-19 / LANG-10 / LANG-11): this application renders `q` as a bare column
 * head, `INSUFFICIENT` as a pill, "holdout" as a heading on six tables, and BH correction, CAGR,
 * RSI, regime and drawdown in prose -- and defines none of them anywhere a reader can reach. The
 * vocabulary is the product's own; a reader who does not already have it cannot acquire it here.
 *
 * So the definition rides the word. `<Term k="qValue">{t("...col.q")}</Term>` leaves the visible
 * text exactly as it was, adds a dotted underline, and opens the definition from
 * `i18n/messages/glossary.ts` on hover **and** on keyboard focus.
 *
 * **Why not `title=`.** The app already has ~110 native `title` tooltips and they are the reason
 * this component exists: `title` is invisible on touch (no hover on a phone), unreachable from the
 * keyboard, and unsearchable by find-in-page. `InfoNote.tsx` makes the same argument at length for
 * the disclosure case. This is the inline case: too small for a disclosure, too important to leave
 * to a hover-only attribute.
 *
 * **Why the tip is always in the DOM.** `aria-describedby` resolves against the accessibility tree,
 * so a tip removed while closed (or hidden with `display: none`) describes nothing -- the trigger
 * would announce a word with no definition, which is the state this component exists to fix. The
 * tip therefore stays mounted and is revealed visually by `data-open`, never unmounted. That also
 * keeps the definition findable with Ctrl+F, the same property `InfoNote` keeps by using
 * `<details>`.
 *
 * **Why `data-open` and not `:hover`/`:focus-within`.** Escape has to be able to dismiss a tip while
 * the pointer is still over the word, and a CSS-driven tip cannot be dismissed -- the moment state
 * and CSS disagree, the CSS wins and the key does nothing. One source of truth: React state, mirrored
 * onto `data-open` for the stylesheet.
 *
 * **What must never go in here.** Anything a reader is worse off for not seeing -- "not tax advice",
 * the 13F lag, the in-sample warning -- keeps its visible short form plus a pill, per
 * docs/COPY-STYLE.md rule 6. A tooltip explains a word. It is not a place to put a disclaimer.
 */
import { useId, useState, type KeyboardEvent, type ReactNode } from "react";

import type { MessageKey } from "@/i18n/catalog";
import type { GlossarySlug } from "@/i18n/messages/glossary";
import { useT } from "@/i18n/useT";

import "./Term.css";

export type GlossaryKey = GlossarySlug;

export interface TermProps {
  /** Which glossary entry to define. A slug this shard does not define is a compile error. */
  k: GlossaryKey;
  /**
   * The words actually on screen. Omit to render the term's own display name -- but prefer passing
   * the existing label, so applying this component changes nothing a reader can see except the
   * underline.
   */
  children?: ReactNode | undefined;
  className?: string | undefined;
  "data-testid"?: string | undefined;
}

export default function Term({ k, children, className, "data-testid": dataTestId }: TermProps) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const tipId = `term-tip-${useId()}`;

  const termKey = `glossary.${k}.term` as MessageKey;
  const defKey = `glossary.${k}.def` as MessageKey;

  function handleKeyDown(event: KeyboardEvent<HTMLSpanElement>) {
    // Escape dismisses without moving focus -- the reader keeps their place in the tab order and
    // simply stops being covered by the tip. Re-focusing (or re-entering with the pointer) brings
    // it back, so dismissal is per-visit and never sticky.
    if (event.key === "Escape" && open) {
      event.stopPropagation();
      setOpen(false);
    }
  }

  const classes = ["term"];
  if (className) classes.push(className);

  return (
    <span
      className={classes.join(" ")}
      data-open={open}
      data-testid={dataTestId}
      tabIndex={0}
      aria-describedby={tipId}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onKeyDown={handleKeyDown}
    >
      <span className="term-word">{children ?? t(termKey)}</span>
      <span className="term-tip" role="tooltip" id={tipId}>
        {t(defKey)}
      </span>
    </span>
  );
}

export { Term };
