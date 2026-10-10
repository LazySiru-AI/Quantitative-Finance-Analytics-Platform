/**
 * The shape every message shard has to satisfy.
 *
 * **English and Korean live side by side, in one entry.** The obvious alternative -- an `en.ts` and
 * a `ko.ts` holding parallel key sets -- makes completeness something a type has to be asked to
 * check, and makes a missing Korean string a *runtime* fallback rather than a compile error. Here a
 * key cannot exist without both languages, because the key *is* the pair. `tsc --noEmit` already
 * runs in CI, so "every string is translated" stops being a review question.
 *
 * It also makes the shards file-disjoint, which is why the catalog is assembled from a folder of
 * them rather than kept in one file: two people (or two agents) extracting strings from different
 * pages never touch the same module.
 */

/** One message, in both languages. */
export type MessagePair = {
  readonly en: string;
  readonly ko: string;
};

/** A per-area group of messages. Keys are dotted ids -- see `catalog.ts` for the convention. */
export type MessageShard = Readonly<Record<string, MessagePair>>;

/** Values substituted into `{placeholder}` slots. */
export type MessageParams = Readonly<Record<string, string | number>>;

/** The two locales this app ships. */
export type Language = "en" | "ko";

export const LANGUAGES: readonly Language[] = ["en", "ko"] as const;

export function isLanguage(value: unknown): value is Language {
  return value === "en" || value === "ko";
}
