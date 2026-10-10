/**
 * Message lookup and placeholder substitution.
 *
 * **Callers never concatenate.** The rule this module exists to enforce is that a sentence is one
 * catalog entry with `{placeholder}` slots, not English fragments glued around a value at the call
 * site. Korean puts the verb last and marks the subject with a particle, so `"Bought " + n +
 * " shares"` has no correct Korean equivalent that a translator can supply -- the whole sentence
 * has to be theirs to reorder. `t("activity.bought", { count: n })` gives them that; string
 * addition does not.
 *
 * **Plurals are two explicit keys, not a rule engine.** English needs one/other and Korean needs
 * neither, which is a two-line problem -- `t(n === 1 ? "x.bar_one" : "x.bar_other", { count: n })`,
 * with both Korean strings identical. A plural-category resolver would be more machinery than the
 * two locales this app ships can justify, and it would move a compile-time key check to runtime.
 */
import { CATALOG, type MessageKey } from "@/i18n/catalog";
import { getLanguage } from "@/i18n/store";
import type { Language, MessageParams } from "@/i18n/types";

/** Matches a `{name}` slot. Names are the identifier characters, so `{` in prose is left alone. */
const PLACEHOLDER = /\{(\w+)\}/g;

/**
 * The raw template for a key in a language, falling back to English.
 *
 * The fallback cannot be reached by a *missing* key -- `MessageShard` makes `en` and `ko` a single
 * entry, so a key without Korean does not compile. It catches the case the type cannot see: an
 * entry whose Korean was left as an empty string, which would otherwise render as a blank cell that
 * looks like missing data rather than missing translation.
 */
export function template(lang: Language, key: MessageKey): string {
  const entry = CATALOG[key];
  if (lang === "ko" && entry.ko) return entry.ko;
  return entry.en;
}

/** Substitute `{name}` slots. An unmatched slot is left verbatim so it is visible, not silent. */
export function format(source: string, params?: MessageParams): string {
  if (!params) return source;
  return source.replace(PLACEHOLDER, (whole, name: string) => {
    const value = params[name];
    return value === undefined ? whole : String(value);
  });
}

/** Translate in an explicit language. Used by tests and by anything rendering both locales. */
export function translate(lang: Language, key: MessageKey, params?: MessageParams): string {
  return format(template(lang, key), params);
}

/**
 * Translate in the active language.
 *
 * Safe to call outside React -- it reads the store's snapshot synchronously. Components that render
 * its output subscribe through `useT()`, so the value is current for the render that asked for it.
 */
export function t(key: MessageKey, params?: MessageParams): string {
  return translate(getLanguage(), key, params);
}

export type { MessageKey };
