/**
 * Privacy mode: one switch that blurs every money figure on screen.
 *
 * This is `i18n/store.ts`'s store with a boolean payload, and deliberately so -- the app already has
 * one answer to "a user preference several unrelated components must render from, survives a reload,
 * and must not disagree with itself for even one frame", and a second answer would be a second thing
 * to reason about. `useSyncExternalStore` over a module-level snapshot is what lets the sidebar
 * toggle repaint a table cell in another subtree without a route change or a reload.
 *
 * **The blur is CSS, not React.** The store's only job in the DOM is to set `data-redact="on"` on
 * `<html>`; `styles.css` decides what that hides. That is what makes the feature reach Overview,
 * Account, Tax, Wash Sales and Paper Desk without any of those pages importing anything -- a figure
 * is covered because of the class it already had, not because someone remembered to wrap it. The
 * corollary is that a number rendered with no class at all cannot be covered from here; those are
 * listed in the CSS rule's own comment rather than left to be discovered on a screen share.
 *
 * **It is a screen-privacy control, not a security boundary.** The values are still in the DOM, and
 * anyone with the machine can turn the blur off in one click -- which is the point: this exists for
 * the shoulder behind you and the screen you are sharing, not for an attacker who already has the
 * session.
 */
import { useCallback, useSyncExternalStore } from "react";

/** Versioned, so a future change to the stored shape can be recognised rather than guessed at. */
export const PRIVACY_STORAGE_KEY = "investing-dashboard.privacy.v1";

/** The attribute value `styles.css` keys the blur off. Exported so a test asserts the contract
 *  rather than a string literal that could drift from the stylesheet. */
export const REDACT_ON = "on";

/**
 * Read and validate the stored preference.
 *
 * Every failure path returns `false` rather than throwing: `localStorage` is absent in some embedded
 * webviews, throws outright in Safari private mode, and holds whatever a previous version of this
 * app -- or the user's own devtools -- last put there. Defaulting *off* is the deliberate direction:
 * an app that will not render because a privacy key is malformed is a far worse bug than one that
 * opens showing the figures the owner asked to see.
 */
function readStored(): boolean {
  try {
    return window.localStorage.getItem(PRIVACY_STORAGE_KEY) === REDACT_ON;
  } catch {
    return false;
  }
}

let snapshot: boolean = readStored();
const listeners = new Set<() => void>();

/**
 * Mirror the preference onto the document element.
 *
 * `<html data-redact="on">` is the whole public surface of this module as far as the stylesheet is
 * concerned. Cleared to `""` rather than removed: `dataset` deletion and assignment behave the same
 * for the `[data-redact="on"]` selector, and an always-present attribute is easier to see in
 * devtools when someone is asking why a figure is or is not blurred.
 */
function syncDocumentRedact(on: boolean): void {
  try {
    document.documentElement.dataset["redact"] = on ? REDACT_ON : "";
  } catch {
    // No DOM (a non-jsdom test environment). The store still works; only the attribute is lost.
  }
}

syncDocumentRedact(snapshot);

function commit(next: boolean, persist: boolean): void {
  // `useSyncExternalStore` compares snapshots by identity and will warn and re-render forever if a
  // no-op write still notifies, so an unchanged value must return before touching the listeners.
  if (next === snapshot) return;
  snapshot = next;
  syncDocumentRedact(next);
  if (persist) {
    try {
      window.localStorage.setItem(PRIVACY_STORAGE_KEY, next ? REDACT_ON : "");
    } catch {
      // Full quota or a storage-denied context. The in-memory snapshot still updated, so the
      // session behaves correctly and only the persistence is lost.
    }
  }
  for (const listener of listeners) listener();
}

/** Whether money is currently hidden. Stable by identity until it changes. */
export function isRedacted(): boolean {
  return snapshot;
}

/** Hide or show money, and remember the choice. */
export function setRedacted(next: boolean): void {
  commit(next, true);
}

/**
 * Re-read `localStorage` into the snapshot without writing back.
 *
 * Used by the cross-tab `storage` listener, and by tests that seed `localStorage` directly -- the
 * snapshot is initialised once at module load, so a test that sets the key afterwards needs a way to
 * tell the store to look again.
 */
export function refreshPrivacyFromStorage(): void {
  commit(readStored(), false);
}

function onStorage(event: StorageEvent): void {
  // `key === null` is a `localStorage.clear()` from another tab, which affects us too.
  if (event.key === null || event.key === PRIVACY_STORAGE_KEY) refreshPrivacyFromStorage();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (listeners.size === 1) window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.removeEventListener("storage", onStorage);
  };
}

export type PrivacyApi = {
  /** `true` when money is hidden. */
  redacted: boolean;
  /** Flip the switch. */
  toggle: () => void;
};

/** Subscribe a component to the privacy store. */
export function usePrivacy(): PrivacyApi {
  const redacted = useSyncExternalStore(subscribe, isRedacted, isRedacted);
  const toggle = useCallback(() => setRedacted(!isRedacted()), []);
  return { redacted, toggle };
}
