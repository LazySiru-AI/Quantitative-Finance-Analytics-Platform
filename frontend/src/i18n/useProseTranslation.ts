/**
 * The hook behind `TranslatedProse`: given a piece of model-written English prose, returns what to
 * show for the active language, fetching a Korean machine translation on demand.
 *
 * **English mode never fetches.** `text` is returned unchanged and `state` is always `"original"` --
 * there is nothing to translate into English, so no network call happens and no cache entry is
 * created.
 *
 * **A module-level cache, keyed by the raw English text, shared across every hook instance.** Two
 * `NarrativeSection`s (or any other future caller) rendering the identical sentence -- which happens
 * whenever the same report section is shown twice, or a page re-mounts the same card -- must share
 * one translation, not fire one request each. The cache also de-duplicates *in-flight* requests: a
 * second component mounting for the same text while the first request is still pending finds the
 * pending entry and awaits its promise instead of calling `translateProse` again. A `null` result
 * (server flag off, the call failed, or the backend's own grounding check rejected it) is cached
 * too, as a "done, no translation" entry -- so a reader is not slowed down retrying it on every
 * remount, and `useProseTranslation` reports it the same way as never having translated at all: the
 * original English, `state: "original"`.
 *
 * **The fetch itself lives in an effect, never in render.** Render only reads the cache and returns
 * whatever is there *right now* (the original text while a fetch is pending or has not started);
 * the effect is what starts a fetch when one is needed and, on resolution, nudges every mounted
 * hook instance watching that text to re-render by bumping local state. That split is what keeps
 * this loop-free -- no "set state during render" warning, and no re-fetch on every render.
 */
import { useEffect, useState } from "react";

import { translateProse } from "@/api/i18n";
import { useLanguage } from "@/i18n/useT";

export type ProseTranslationState = "original" | "translated";

export interface ProseTranslation {
  text: string;
  state: ProseTranslationState;
}

type CacheEntry =
  | { readonly status: "pending"; readonly promise: Promise<string | null> }
  | { readonly status: "done"; readonly value: string | null };

/** Keyed by the raw English source text. Module-level, so it outlives any single component. */
const cache = new Map<string, CacheEntry>();

/**
 * Test-only escape hatch: each hook instance and each cache entry would otherwise leak across test
 * cases, since the cache is intentionally shared for the lifetime of the module. Not exported from
 * `@/i18n` -- only `proseTranslation.test.tsx` should ever call this.
 */
export function __resetProseTranslationCacheForTests(): void {
  cache.clear();
}

/** Returns the cache entry for `text`, starting a fetch (and caching the in-flight promise) if
 * there is not one already -- so a second call for the same text, from a different component,
 * always finds and reuses this same entry instead of starting a second request. */
function getOrStartFetch(text: string): CacheEntry {
  const existing = cache.get(text);
  if (existing) return existing;

  const promise = translateProse([text], "ko").then((results) => results[0] ?? null);
  const entry: CacheEntry = { status: "pending", promise };
  cache.set(text, entry);

  // Replace the pending entry with a settled one once the request resolves. `translateProse`
  // itself never rejects (see its own docstring), so there is no `.catch` to add here.
  void promise.then((value) => {
    // Guards against a cache cleared mid-flight (a test calling the reset above) re-inserting a
    // stale result under a key nothing should own any more.
    if (cache.get(text) === entry) cache.set(text, { status: "done", value });
  });

  return entry;
}

export function useProseTranslation(text: string | null | undefined): ProseTranslation {
  const lang = useLanguage();
  const raw = text ?? "";
  const active = lang === "ko" && raw !== "";
  // Bumped after a pending fetch this instance is watching resolves, purely to trigger a
  // re-render that re-reads the now-settled cache entry below. The number itself is never read.
  const [, forceRerender] = useState(0);

  useEffect(() => {
    if (!active) return;
    const entry = getOrStartFetch(raw);
    if (entry.status === "done") return; // already settled -- nothing to await
    let cancelled = false;
    void entry.promise.then(() => {
      if (!cancelled) forceRerender((n) => n + 1);
    });
    return () => {
      cancelled = true;
    };
  }, [active, raw]);

  if (!active) return { text: raw, state: "original" };

  const entry = cache.get(raw);
  if (entry && entry.status === "done" && entry.value !== null) {
    return { text: entry.value, state: "translated" };
  }
  // Pending, not yet started (first render before the effect runs), or settled with `null`.
  return { text: raw, state: "original" };
}
