/**
 * The active display language: one preference, read from everywhere, agreeing instantly.
 *
 * This is `favorites.ts`'s store with a different payload, and deliberately so -- the app already
 * has one answer to "a user preference that several unrelated components must render from, survives
 * a reload, and must not disagree with itself for even one frame", and a second answer would be a
 * second thing to reason about. `useSyncExternalStore` over a module-level snapshot is what lets the
 * sidebar toggle repaint a table header in another subtree without a route change or a reload.
 *
 * **A module-level store rather than context** for a second reason too: roughly a hundred string
 * literals live in non-React code -- `api/market.ts`'s formatters, `api/paperdesk.ts`'s status
 * labels, `nav.ts`'s destination list. Those cannot read a context. They call `t()`, which reads
 * this snapshot synchronously, and they are always current for the render that asked, because every
 * component that renders their output subscribes through `useT()` and re-renders on change.
 *
 * **English is the default, and `navigator.language` is not consulted.** Sniffing the browser would
 * flip a Korean-configured machine into Korean on first load, which silently changes what ~900
 * existing test assertions and every screenshot in `docs/` are looking at. The toggle is the
 * request; auto-detection is a different feature with a different failure mode.
 */
import { isLanguage, type Language } from "@/i18n/types";

/** Versioned, so a future change to the stored shape can be recognised rather than guessed at. */
export const LANGUAGE_STORAGE_KEY = "investing-dashboard.language.v1";

export const DEFAULT_LANGUAGE: Language = "en";

/**
 * Read and validate the stored language.
 *
 * Every failure path returns the default rather than throwing: `localStorage` is absent in some
 * embedded webviews, throws outright in Safari private mode, and holds whatever a previous version
 * of this app -- or the user's own devtools -- last put there. An application that refuses to render
 * because a language key is malformed would be a far worse bug than one that opens in English.
 */
function readStored(): Language {
  try {
    const raw = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    return isLanguage(raw) ? raw : DEFAULT_LANGUAGE;
  } catch {
    return DEFAULT_LANGUAGE;
  }
}

let snapshot: Language = readStored();
const listeners = new Set<() => void>();

/**
 * Mirror the active language onto the document element.
 *
 * Not decoration. `lang` is what a screen reader keys its pronunciation off, what the browser keys
 * hyphenation and font fallback off, and what `:lang()` selectors in `styles.css` can hook if the
 * Korean stack ever needs different metrics. A page whose text is Korean but whose `lang` says
 * `en` is read aloud as mangled English.
 */
function syncDocumentLanguage(lang: Language): void {
  try {
    document.documentElement.lang = lang;
  } catch {
    // No DOM (a non-jsdom test environment). The store still works; only the attribute is lost.
  }
}

syncDocumentLanguage(snapshot);

function commit(next: Language, persist: boolean): void {
  // `useSyncExternalStore` compares snapshots by identity and will warn and re-render forever if a
  // no-op write still notifies, so an unchanged value must return before touching the listeners.
  if (next === snapshot) return;
  snapshot = next;
  syncDocumentLanguage(next);
  if (persist) {
    try {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, next);
    } catch {
      // Full quota or a storage-denied context. The in-memory snapshot still updated, so the
      // session behaves correctly and only the persistence is lost.
    }
  }
  for (const listener of listeners) listener();
}

/** The active language. Stable by identity until it changes. */
export function getLanguage(): Language {
  return snapshot;
}

/** Switch the display language and remember the choice. */
export function setLanguage(next: Language): void {
  commit(next, true);
}

/**
 * Re-read `localStorage` into the snapshot without writing back.
 *
 * Used by the cross-tab `storage` listener, and by tests that seed `localStorage` directly -- the
 * snapshot is initialised once at module load, so a test that sets the key afterwards needs a way
 * to tell the store to look again.
 */
export function refreshLanguageFromStorage(): void {
  commit(readStored(), false);
}

function onStorage(event: StorageEvent): void {
  // `key === null` is a `localStorage.clear()` from another tab, which affects us too.
  if (event.key === null || event.key === LANGUAGE_STORAGE_KEY) refreshLanguageFromStorage();
}

export function subscribeLanguage(listener: () => void): () => void {
  listeners.add(listener);
  if (listeners.size === 1) window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.removeEventListener("storage", onStorage);
  };
}
