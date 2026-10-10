/**
 * Favourited nav destinations: the pages the sidebar pins into a section of their own.
 *
 * The nav is two levels deep (see `nav.ts`), which fixed the "thirteen unrelated peers in one
 * list" problem but created a smaller one: the pages *you* use every day are rarely in one
 * section. Getting from Wash Sales to Macro is now two clicks through a rail, every time.
 * Favourites are the escape hatch -- a flat, user-chosen list that ignores the section grouping
 * entirely and sits below it.
 *
 * **Paths are the identity, and only known paths are kept.** The stored value is a list of
 * `NavItem["to"]` strings, filtered against `NAV_ITEMS` on every read and every write. A page that
 * is renamed or removed therefore drops out of someone's favourites silently rather than becoming
 * a pinned link to the 404 -- which is the failure mode a stored label or a stored index would
 * both produce, and neither would be visible to the person until they clicked it.
 *
 * **Order is `NAV` order, not click order.** Sanitising through `NAV_ITEMS` re-sorts on the way in.
 * A favourites list that reshuffles itself as you star things is a list you have to re-read every
 * time; one that mirrors the nav is one you learn the shape of once.
 *
 * **One module-level store, not per-component state.** Two separate places render favourite state
 * -- the star beside each page link, and the favourites section itself -- and they must agree the
 * instant either changes. `useSyncExternalStore` over a shared snapshot is what makes clicking a
 * star in the page rail add the row below without a round trip through the route or a reload.
 */
import { useCallback, useMemo, useSyncExternalStore } from "react";

import { NAV_ITEMS, type NavItem } from "@/nav";

/** Versioned, so a future change to the stored shape can be recognised rather than guessed at. */
export const FAVORITES_STORAGE_KEY = "investing-dashboard.favorites.v1";

const KNOWN_PATHS = new Set(NAV_ITEMS.map((item) => item.to));

/** Drop anything that is not a live destination, de-duplicate, and return in `NAV` order. */
function sanitize(paths: readonly unknown[]): readonly string[] {
  const wanted = new Set<string>();
  for (const path of paths) {
    if (typeof path === "string" && KNOWN_PATHS.has(path)) wanted.add(path);
  }
  return NAV_ITEMS.filter((item) => wanted.has(item.to)).map((item) => item.to);
}

/**
 * Read and validate the stored list.
 *
 * Every failure path returns `[]` rather than throwing: `localStorage` is absent in some embedded
 * webviews, throws outright in Safari private mode, and holds whatever a previous version of this
 * app -- or the user's own devtools -- last put there. A nav that refuses to render because a
 * favourites key is malformed would be a far worse bug than a nav that quietly forgets a star.
 */
function readStored(): readonly string[] {
  try {
    const raw = window.localStorage.getItem(FAVORITES_STORAGE_KEY);
    if (raw === null) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? sanitize(parsed) : [];
  } catch {
    return [];
  }
}

let snapshot: readonly string[] = readStored();
const listeners = new Set<() => void>();

function sameList(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((path, i) => path === b[i]);
}

/**
 * Replace the snapshot, optionally persisting it, and notify subscribers.
 *
 * The `sameList` guard is what keeps `getSnapshot` honest. `useSyncExternalStore` compares
 * snapshots by identity and will loop forever ("getSnapshot should be cached") if a fresh array is
 * handed back for an unchanged value -- so a no-op toggle, or a `storage` event for a write this
 * tab made itself, must leave the existing reference in place.
 */
function commit(next: readonly string[], persist: boolean): void {
  const sane = sanitize(next);
  if (sameList(sane, snapshot)) return;
  snapshot = sane;
  if (persist) {
    try {
      window.localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify(sane));
    } catch {
      // Full quota or a storage-denied context. The in-memory snapshot still updated, so the
      // session behaves correctly and only the persistence is lost.
    }
  }
  for (const listener of listeners) listener();
}

/** The current favourites, as paths, in `NAV` order. Stable by identity until they change. */
export function readFavorites(): readonly string[] {
  return snapshot;
}

/** Replace the whole list. Unknown paths are discarded. */
export function writeFavorites(paths: readonly string[]): void {
  commit(paths, true);
}

/** Add `to` if absent, remove it if present. A path outside `NAV_ITEMS` is a no-op. */
export function toggleFavorite(to: string): void {
  commit(snapshot.includes(to) ? snapshot.filter((path) => path !== to) : [...snapshot, to], true);
}

/**
 * Re-read `localStorage` into the snapshot without writing back.
 *
 * Used by the cross-tab `storage` listener, and by tests that seed `localStorage` directly -- the
 * snapshot is initialised once at module load, so a test that sets the key afterwards needs a way
 * to tell the store to look again.
 */
export function refreshFavoritesFromStorage(): void {
  commit(readStored(), false);
}

function onStorage(event: StorageEvent): void {
  // `key === null` is a `localStorage.clear()` from another tab, which affects us too.
  if (event.key === null || event.key === FAVORITES_STORAGE_KEY) refreshFavoritesFromStorage();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (listeners.size === 1) window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.removeEventListener("storage", onStorage);
  };
}

export type FavoritesApi = {
  /** The favourited destinations themselves, in `NAV` order, ready to render. */
  favorites: readonly NavItem[];
  isFavorite: (to: string) => boolean;
  toggleFavorite: (to: string) => void;
};

/** Subscribe a component to the favourites store. */
export function useFavorites(): FavoritesApi {
  const paths = useSyncExternalStore(subscribe, readFavorites, readFavorites);

  const favorites = useMemo(() => NAV_ITEMS.filter((item) => paths.includes(item.to)), [paths]);
  const isFavorite = useCallback((to: string) => paths.includes(to), [paths]);

  return { favorites, isFavorite, toggleFavorite };
}
