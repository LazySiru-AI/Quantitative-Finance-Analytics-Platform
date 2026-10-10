/**
 * The public surface. Import from `@/i18n`, not from its internals.
 *
 * Almost every caller wants exactly two things: `useT` in a component, and `t` in a helper that has
 * no component to hang a hook on.
 */
export { default as Trans } from "@/i18n/Trans";
export { default as TranslatedProse } from "@/i18n/TranslatedProse";
export type { MessageKey } from "@/i18n/catalog";
export { CATALOG, SHARDS } from "@/i18n/catalog";
export {
  DEFAULT_LANGUAGE,
  LANGUAGE_STORAGE_KEY,
  getLanguage,
  refreshLanguageFromStorage,
  setLanguage,
  subscribeLanguage,
} from "@/i18n/store";
export { format, t, template, translate } from "@/i18n/t";
export type { Language, MessageParams, MessagePair, MessageShard } from "@/i18n/types";
export { LANGUAGES, isLanguage } from "@/i18n/types";
export type { I18n, Translator } from "@/i18n/useT";
export { localeTag, useLanguage, useT } from "@/i18n/useT";
export type { ProseTranslation, ProseTranslationState } from "@/i18n/useProseTranslation";
export { useProseTranslation } from "@/i18n/useProseTranslation";
