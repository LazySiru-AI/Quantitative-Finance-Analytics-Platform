/**
 * The React entry point: subscribe a component to the language store and get a bound `t`.
 *
 * A component that renders *any* translated text must call this, including one whose strings come
 * from a helper in `api/` rather than from its own JSX. `t()` reads the store synchronously and
 * would happily return the right string -- but nothing would tell React to call the component again
 * when the language changes, so the old text would sit on screen until some unrelated state moved.
 * Subscribing is what makes the toggle repaint the page.
 */
import { useCallback, useSyncExternalStore } from "react";

import type { MessageKey } from "@/i18n/catalog";
import { getLanguage, subscribeLanguage } from "@/i18n/store";
import { translate } from "@/i18n/t";
import type { Language, MessageParams } from "@/i18n/types";

export type Translator = (key: MessageKey, params?: MessageParams) => string;

export type I18n = {
  /** Translate a key in the active language. */
  t: Translator;
  /** The active language, for the handful of callers that must branch on it (date formatting). */
  lang: Language;
};

export function useT(): I18n {
  const lang = useSyncExternalStore(subscribeLanguage, getLanguage, getLanguage);
  // Bound to `lang` rather than calling the module-level `t`, so the identity changes when the
  // language does and any `useMemo` downstream that lists `t` as a dependency actually recomputes.
  const bound = useCallback<Translator>((key, params) => translate(lang, key, params), [lang]);
  return { t: bound, lang };
}

/** Just the active language, for callers that need the locale but no strings. */
export function useLanguage(): Language {
  return useSyncExternalStore(subscribeLanguage, getLanguage, getLanguage);
}

/**
 * The BCP 47 tag to hand `Intl` and `toLocaleDateString`.
 *
 * Dates go through this; **money and plain numbers deliberately do not.** The account is in USD and
 * `ko-KR` currency formatting prints `US$1,234.56` and drops the alignment that
 * `font-variant-numeric: tabular-nums` exists to preserve. Korean uses the same digit grouping as
 * English, so there is nothing to gain and a column of prices to lose.
 */
export function localeTag(lang: Language): string {
  return lang === "ko" ? "ko-KR" : "en-US";
}
