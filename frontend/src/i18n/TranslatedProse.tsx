/**
 * Renders one piece of model-written English prose, translated to Korean when the active language
 * is Korean and the backend supplied a translation -- falling back to the English original,
 * badged, otherwise.
 *
 * **Three states a Korean reader can see, never silently merged:**
 *  - English mode: just the text. No badge -- there is nothing to disclose.
 *  - Korean mode, translated: the Korean text, with a subtle "machine-translated" badge. This is
 *    still not the same guarantee as the grounded-and-verified English original underneath it, so
 *    the badge stays, just less insistent than the one below.
 *  - Korean mode, not translated (the server flag is off, the call failed, or it is still
 *    pending): the English original, with the existing "Original (English)" badge -- the same
 *    markup `NarrativeSection.tsx` used before this component existed, kept byte-for-byte so the
 *    page does not visibly change for the failure/pending case, only gains a new success case.
 *
 * `useProseTranslation` owns the fetch/cache; this component only decides what to render for the
 * state it reports.
 */
import { useProseTranslation } from "@/i18n/useProseTranslation";
import { useT } from "@/i18n/useT";

interface TranslatedProseProps {
  text: string | null | undefined;
  as?: "p" | "div" | "span";
  className?: string;
}

export default function TranslatedProse({ text, as, className }: TranslatedProseProps) {
  const { t, lang } = useT();
  const { text: displayText, state } = useProseTranslation(text);
  const Tag = as ?? "p";
  const hasText = text !== null && text !== undefined && text !== "";

  return (
    <>
      <Tag className={className}>{displayText}</Tag>
      {hasText && lang === "ko" && state === "original" && (
        <span className="badge report-narrative-source-badge" title={t("common.sourceEnglishTitle")}>
          {t("common.sourceEnglish")}
        </span>
      )}
      {hasText && lang === "ko" && state === "translated" && (
        <span
          className="badge report-narrative-source-badge report-narrative-source-badge--translated"
          title={t("common.sourceMachineTranslatedTitle")}
        >
          {t("common.sourceMachineTranslated")}
        </span>
      )}
    </>
  );
}
