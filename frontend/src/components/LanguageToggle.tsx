/**
 * The EN / 한국어 switch, in the sidebar directly under the brand line.
 *
 * **Two buttons, not a `<select>` and not one button that cycles.** With exactly two options a
 * segmented control shows the choice *and* the alternative at once, so the state is readable
 * without opening anything -- and `aria-pressed` gives a screen reader the same on/off reading the
 * favourite stars already use, which is a pattern this app has committed to elsewhere. A cycling
 * button would show only the current value and leave "what happens if I click" to be guessed.
 *
 * **A sibling of `.nav`, deliberately.** `App.test.tsx` counts the links inside `.nav` against the
 * active section's item count and asserts specific pages are absent from it. Anything else rendered
 * inside that container breaks both invariants, which is the same reason the favourites rail sits
 * outside it.
 *
 * `type="button"` is not decoration: a bare `<button>` defaults to `type="submit"`, and this
 * component is generic enough to end up inside a form eventually.
 */
import { setLanguage } from "@/i18n/store";
import type { Language } from "@/i18n/types";
import { useT } from "@/i18n/useT";

import "./LanguageToggle.css";

const OPTIONS: readonly { value: Language; label: "shell.language.en" | "shell.language.ko"; hint: "shell.language.selectEn" | "shell.language.selectKo" }[] = [
  { value: "en", label: "shell.language.en", hint: "shell.language.selectEn" },
  { value: "ko", label: "shell.language.ko", hint: "shell.language.selectKo" },
];

export default function LanguageToggle() {
  const { t, lang } = useT();

  return (
    <div className="language-toggle" role="group" aria-label={t("shell.language.group")}>
      {OPTIONS.map((option) => {
        const active = option.value === lang;
        return (
          <button
            key={option.value}
            type="button"
            className={active ? "language-option is-active" : "language-option"}
            aria-pressed={active}
            // The accessible name is the full sentence, not "EN". A two-letter label read aloud on
            // its own tells a screen reader user nothing about what the control does.
            aria-label={t(option.hint)}
            title={t(option.hint)}
            lang={option.value}
            onClick={() => setLanguage(option.value)}
          >
            {t(option.label)}
          </button>
        );
      })}
    </div>
  );
}
