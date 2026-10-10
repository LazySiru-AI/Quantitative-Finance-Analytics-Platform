/**
 * The favourites store: sanitisation, persistence and the snapshot-stability contract.
 *
 * `favorites.ts` keeps its state at module scope, initialised once from `localStorage` at import
 * time, so it survives across every test in this file unless something resets it. `beforeEach`
 * below seeds `localStorage` directly and then calls `refreshFavoritesFromStorage()` -- the same
 * escape hatch the module offers for a cross-tab `storage` event -- rather than re-importing the
 * module, because Vitest caches modules per file and a stale snapshot from a previous test would
 * otherwise leak into the next one.
 *
 * These tests are about the store's own invariants, not the UI built on it: unknown paths must be
 * pruned rather than kept as dead links, order must be `NAV` order rather than click order, a
 * corrupt or wrongly-shaped stored value must be tolerated rather than thrown, and `readFavorites`
 * must hand back the *same* array reference when nothing changed -- `useSyncExternalStore` compares
 * snapshots by identity and loops forever ("getSnapshot should be cached") the moment that stops
 * being true.
 */
import { beforeEach, describe, expect, it } from "vitest";

import {
  FAVORITES_STORAGE_KEY,
  readFavorites,
  refreshFavoritesFromStorage,
  toggleFavorite,
  writeFavorites,
} from "@/favorites";
import { NAV_ITEMS } from "@/nav";

// Every path this file hardcodes must be a real destination. If a route is ever renamed, this
// fails loudly here instead of letting the rest of the suite quietly assert on a path nobody can
// reach anymore.
const HARDCODED_PATHS = ["/portfolio", "/macro", "/tax", "/not-a-page"];
const KNOWN = new Set(NAV_ITEMS.map((item) => item.to));
describe("paths used in this file are real nav destinations (or deliberately not)", () => {
  it.each(HARDCODED_PATHS)("%s", (path) => {
    if (path === "/not-a-page") {
      expect(KNOWN.has(path)).toBe(false);
    } else {
      expect(KNOWN.has(path)).toBe(true);
    }
  });
});

function seed(value: string | null): void {
  if (value === null) {
    window.localStorage.removeItem(FAVORITES_STORAGE_KEY);
  } else {
    window.localStorage.setItem(FAVORITES_STORAGE_KEY, value);
  }
  refreshFavoritesFromStorage();
}

beforeEach(() => {
  // Clear first: a previous test's `writeFavorites` call persisted to the same jsdom
  // `localStorage`, and `refreshFavoritesFromStorage` only re-reads -- it does not clear.
  window.localStorage.clear();
  refreshFavoritesFromStorage();
});

describe("readFavorites", () => {
  it("is empty when storage has never been written", () => {
    expect(readFavorites()).toEqual([]);
  });
});

describe("toggleFavorite", () => {
  it("adds an absent path and removes it again on a second toggle", () => {
    toggleFavorite("/macro");
    expect(readFavorites()).toEqual(["/macro"]);

    toggleFavorite("/macro");
    expect(readFavorites()).toEqual([]);
  });

  it("persists the toggle to localStorage under the versioned key", () => {
    toggleFavorite("/macro");

    const raw = window.localStorage.getItem(FAVORITES_STORAGE_KEY);
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw as string)).toEqual(["/macro"]);
  });

  it("orders by NAV position, not by the order things were clicked", () => {
    // Macro is the last item in NAV; Portfolio is the first. Toggling Macro first must not pin it
    // ahead of Portfolio once Portfolio joins the list.
    toggleFavorite("/macro");
    toggleFavorite("/portfolio");

    expect(readFavorites()).toEqual(["/portfolio", "/macro"]);
  });

  it("is a no-op for a path outside NAV_ITEMS", () => {
    toggleFavorite("/not-a-page");

    expect(readFavorites()).toEqual([]);
    expect(window.localStorage.getItem(FAVORITES_STORAGE_KEY)).toBeNull();
  });
});

describe("sanitisation on read", () => {
  it("prunes a path that no longer exists in NAV_ITEMS", () => {
    seed(JSON.stringify(["/portfolio", "/not-a-page"]));

    expect(readFavorites()).toEqual(["/portfolio"]);
  });

  it("collapses duplicate entries", () => {
    seed(JSON.stringify(["/tax", "/tax"]));

    expect(readFavorites()).toEqual(["/tax"]);
  });

  it("tolerates unparseable JSON without throwing", () => {
    expect(() => seed("{not json")).not.toThrow();
    expect(readFavorites()).toEqual([]);
  });

  it("tolerates valid JSON in the wrong shape without throwing", () => {
    expect(() => seed('{"a":1}')).not.toThrow();
    expect(readFavorites()).toEqual([]);
  });
});

describe("snapshot reference stability", () => {
  // The property `useSyncExternalStore` depends on: repeated reads with no intervening change, and
  // a write that turns out to be a no-op, must both hand back the identical array reference rather
  // than a freshly-sanitised equal one.
  it("returns the same reference across repeated reads with no change", () => {
    toggleFavorite("/macro");

    const first = readFavorites();
    const second = readFavorites();

    expect(first).toBe(second);
  });

  it("keeps the same reference after writing the list it already holds", () => {
    toggleFavorite("/macro");
    const before = readFavorites();

    writeFavorites(before);

    expect(readFavorites()).toBe(before);
  });
});

describe("refreshFavoritesFromStorage", () => {
  it("picks up a write made by another tab", () => {
    toggleFavorite("/portfolio");
    expect(readFavorites()).toEqual(["/portfolio"]);

    // Simulate another tab writing directly, bypassing this module's `commit`.
    window.localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify(["/macro"]));
    refreshFavoritesFromStorage();

    expect(readFavorites()).toEqual(["/macro"]);
  });

  it("does not write back to storage on its own", () => {
    // Seed a value sanitisation would rewrite (duplicates, out of NAV order) and confirm the raw
    // stored string is untouched by the refresh -- only the in-memory snapshot is sanitised.
    const rawSeed = JSON.stringify(["/macro", "/portfolio", "/portfolio"]);
    window.localStorage.setItem(FAVORITES_STORAGE_KEY, rawSeed);

    refreshFavoritesFromStorage();

    expect(readFavorites()).toEqual(["/portfolio", "/macro"]);
    expect(window.localStorage.getItem(FAVORITES_STORAGE_KEY)).toBe(rawSeed);
  });
});
