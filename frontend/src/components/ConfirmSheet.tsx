/**
 * The one confirmation dialog for every mutation in this app.
 *
 * Rule 19 of the refactor plan (`docs/APP-UX-REFACTOR-ANALYSIS.md` §3.6) is "a mutation previews,
 * confirms, and re-fetches only what it changed" -- this is the middle third. The preview *heading*
 * ("What will change") is this component's; the preview *content* is always the caller's, because
 * only the caller knows what its own mutation touches.
 *
 * **Why a hand-rolled overlay instead of `<dialog>`.** `<dialog showModal()>` would hand focus
 * management, the top-layer stacking and Escape-to-close to the browser for free, which is
 * tempting. It was rejected here because jsdom's support for `showModal`/`close` and the resulting
 * `::backdrop` is inconsistent across the version this repo pins, which would make "does Escape
 * close it" and "is focus trapped" flaky in exactly the tests meant to prove they work. A fixed
 * overlay plus a manual focus trap is more code, but it is code that runs the same way in a browser
 * and under `jsdom`.
 *
 * **Why the cancel button, not the confirm button, gets initial focus.** This dialog exists
 * specifically for actions serious enough to want a confirmation step -- recomputing a book,
 * discarding a draft, deleting a lot. Autofocusing *confirm* would make the easiest possible action
 * (press Enter without reading) also the destructive one. Landing focus on cancel means doing
 * nothing is the path of least resistance, and reaching confirm costs one deliberate Tab or click.
 *
 * **Focus trap.** Tab and Shift+Tab cycle only through the sheet's own focusable elements (its own
 * two buttons, plus anything interactive the caller's `preview` node contains) so a keyboard user
 * can never tab out into the page behind the backdrop while the dialog is open. On close, focus is
 * handed back to whatever element had it before the sheet opened -- otherwise the browser's default
 * is to drop focus to `<body>`, which strands a keyboard user back at the top of the page instead of
 * where they were.
 */
import { useEffect, useId, useRef } from "react";

import { useT } from "@/i18n/useT";

import "./ConfirmSheet.css";

/** Elements a Tab press should be able to land on inside the sheet. */
const FOCUSABLE_SELECTOR =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

export interface ConfirmSheetProps {
  open: boolean;
  /** Short sentence naming the action, e.g. "Recompute every book from 2026-01-02?" */
  question: string;
  /** What will change. Rendered under a "What will change" heading. */
  preview?: React.ReactNode | undefined;
  /** Defaults to `interaction.confirm.confirm`. */
  confirmLabel?: string | undefined;
  /** Set while the mutation is in flight: disables both buttons, shows the working label. */
  busy?: boolean | undefined;
  tone?: "neutral" | "warn" | "bad" | undefined;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmSheet({
  open,
  question,
  preview,
  confirmLabel,
  busy = false,
  tone = "neutral",
  onConfirm,
  onCancel,
}: ConfirmSheetProps) {
  const { t } = useT();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();

  // One effect owns the whole open lifecycle -- grabbing focus, trapping Tab, handling Escape, and
  // giving focus back on the way out -- so there is exactly one place that stores "what had focus
  // before this opened" and exactly one place that restores it. Splitting capture and restore into
  // separate effects invites them to run out of order across a re-render.
  useEffect(() => {
    if (!open) return undefined;

    const previouslyFocused = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();

    function focusableElements(): HTMLElement[] {
      const container = dialogRef.current;
      if (!container) return [];
      return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
        (el) => !el.hasAttribute("disabled"),
      );
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== "Tab") return;

      const elements = focusableElements();
      if (elements.length === 0) return;
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (!first || !last) return;

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus();
    };
  }, [open, onCancel]);

  if (!open) return null;

  const classes = ["confirm-sheet", `confirm-sheet-${tone}`];

  return (
    <div className="confirm-sheet-backdrop" onClick={onCancel}>
      <div
        ref={dialogRef}
        className={classes.join(" ")}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        // Stop the click from bubbling to the backdrop's onCancel -- a click that starts and ends
        // inside the sheet is not "click outside the sheet", even though the backdrop is an
        // ancestor in the DOM.
        onClick={(event) => event.stopPropagation()}
      >
        <p id={titleId} className="confirm-sheet-question">
          {question}
        </p>
        {preview !== undefined && (
          <div className="confirm-sheet-preview">
            <h3 className="confirm-sheet-preview-title">{t("interaction.confirm.previewTitle")}</h3>
            <div className="confirm-sheet-preview-body">{preview}</div>
          </div>
        )}
        <div className="confirm-sheet-actions">
          <button
            ref={cancelRef}
            type="button"
            className="confirm-sheet-cancel"
            onClick={onCancel}
            disabled={busy}
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="confirm-sheet-confirm"
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? t("interaction.confirm.working") : confirmLabel ?? t("interaction.confirm.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}

export default ConfirmSheet;
