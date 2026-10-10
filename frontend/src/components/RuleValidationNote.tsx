/**
 * The inline "this expression does not parse" note, for the three forms that take a DSL expression
 * but are not the rule editor.
 *
 * Deliberately renders the same `.rule-editor-result.invalid` markup `RuleEditor` uses on `/rules`,
 * so a parse error looks identical wherever a reader meets one. It shows **nothing** for a valid
 * expression: `/rules` exists to explain an expression, and reports `Valid`, the normalised tree and
 * the indicators needed. These three forms exist to run something, and a "Valid" badge beside every
 * field there is noise that trains the reader to stop reading the badge -- which is exactly what you
 * do not want on the one occasion it says `Not valid`.
 *
 * `aria-live="polite"` rather than `assertive`: the message appears while the reader is still typing
 * the expression it is about, and an assertive region interrupts a screen reader mid-word.
 */
import type { RuleValidation } from "@/api/rules";
import { useT } from "@/i18n";

export default function RuleValidationNote({
  result,
  id,
}: {
  result: RuleValidation | null;
  id?: string;
}) {
  const { t } = useT();
  if (!result || result.valid) return null;
  return (
    <div className="rule-editor-result invalid" id={id} aria-live="polite">
      <span className="rule-editor-verdict invalid">{t("strategy.ruleEditor.notValid")}</span>
      <span className="rule-editor-parse-error">
        {result.error ?? t("strategy.ruleEditor.parserRejected")}
      </span>
    </div>
  );
}
