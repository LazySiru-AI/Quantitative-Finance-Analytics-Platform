/**
 * Expression editor for the rule DSL.
 *
 * Calls `rulesApi.validate` on every keystroke, debounced -- the parser is cheap but not free, and
 * firing it synchronously on each character would flood the API mid-token. A malformed expression is
 * a normal `200 { valid: false, error }` response, not a failed request: the two are rendered
 * completely differently here. A genuine request failure (network down, 5xx) gets its own message
 * and never overwrites the parse result currently on screen.
 *
 * Guards against a stale response the same way `useChartSeries` guards against a stale symbol/
 * interval response: a request counter, bumped on every keystroke, so a slow validate call that
 * resolves after a newer one cannot clobber it.
 */
import { useEffect, useRef, useState } from "react";

import { ApiRequestError } from "@/api/client";
import { rulesApi, type RuleValidation } from "@/api/rules";
import { useT } from "@/i18n";

const DEBOUNCE_MS = 300;

/**
 * The example the field offers, and it must parse.
 *
 * It read `rsi:14 < 30 and close > sma:200` until 2026-08-14 — colon syntax the DSL has never
 * accepted. A user who typed the application's own suggestion got `unexpected character ':'`, and
 * got it from the raw tokenizer rather than from the helpful hints this page otherwise gives for a
 * mistyped indicator. A UAT persona hit it and said it cost them trust in everything else on the
 * page, which is the same argument the grammar's own hint tests are built on: a suggestion that
 * does not itself parse converts a user's correct suspicion that they mistyped into a belief that
 * the engine is broken.
 *
 * Exported so `RuleEditor.test.tsx` can assert it, and pinned server-side by
 * `tests/test_frontend_contract.py`, which feeds this literal through the real parser.
 */
export const PLACEHOLDER_EXPRESSION = "rsi(14) < 30 and close > sma(200)";

type RequestPhase = "idle" | "checking" | "checked" | "error";

interface RuleEditorProps {
  /** Seeds the input; the field remains freely editable afterward. */
  initialExpression?: string;
}

export default function RuleEditor({ initialExpression = "" }: RuleEditorProps) {
  const { t } = useT();
  const [expression, setExpression] = useState(initialExpression);
  const [result, setResult] = useState<RuleValidation | null>(null);
  const [phase, setPhase] = useState<RequestPhase>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const requestId = useRef(0);

  useEffect(() => {
    const trimmed = expression.trim();
    if (trimmed.length === 0) {
      requestId.current += 1;
      setPhase("idle");
      setResult(null);
      setErrorMessage(null);
      return;
    }

    const id = ++requestId.current;
    setPhase("checking");
    setErrorMessage(null);

    const timer = window.setTimeout(() => {
      rulesApi
        .validate(trimmed)
        .then((validation) => {
          if (requestId.current !== id) return;
          setResult(validation);
          setPhase("checked");
        })
        .catch((e: unknown) => {
          if (requestId.current !== id) return;
          setErrorMessage(
            e instanceof ApiRequestError
              ? t("strategy.error.apiStatus", { status: e.status, message: e.message })
              : t("strategy.error.unreachable"),
          );
          setPhase("error");
        });
    }, DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expression]);

  return (
    <div className="rule-editor">
      <label className="rule-editor-label" htmlFor="rule-editor-input">
        {t("strategy.ruleEditor.expressionLabel")}
      </label>
      <input
        id="rule-editor-input"
        className="rule-editor-input"
        value={expression}
        onChange={(e) => setExpression(e.target.value)}
        placeholder={t("strategy.ruleEditor.placeholderExample", { expression: PLACEHOLDER_EXPRESSION })}
        spellCheck={false}
        autoComplete="off"
        aria-describedby="rule-editor-status"
      />

      <div id="rule-editor-status" className="rule-editor-status" aria-live="polite">
        {phase === "idle" && (
          <span className="placeholder">{t("strategy.ruleEditor.idleHint")}</span>
        )}
        {phase === "checking" && (
          <span className="rule-editor-checking">{t("strategy.ruleEditor.checking")}</span>
        )}
        {phase === "error" && <span className="rule-editor-error">{errorMessage}</span>}
        {phase === "checked" && result && <RuleValidationResult result={result} />}
      </div>
    </div>
  );
}

function RuleValidationResult({ result }: { result: RuleValidation }) {
  const { t } = useT();
  if (!result.valid) {
    return (
      <div className="rule-editor-result invalid">
        <span className="rule-editor-verdict invalid">{t("strategy.ruleEditor.notValid")}</span>
        <span className="rule-editor-parse-error">
          {result.error ?? t("strategy.ruleEditor.parserRejected")}
        </span>
      </div>
    );
  }
  return (
    <div className="rule-editor-result valid">
      <span className="rule-editor-verdict valid">{t("strategy.ruleEditor.valid")}</span>
      {result.normalized !== null && (
        <div className="rule-editor-normalized">
          <span className="rule-editor-field-label">{t("strategy.ruleEditor.understoodAs")}</span>
          <code>{result.normalized}</code>
        </div>
      )}
      {result.indicators.length > 0 && (
        <div className="rule-editor-indicators">
          <span className="rule-editor-field-label">{t("strategy.ruleEditor.indicatorsNeeded")}</span>
          <div className="rule-editor-chips">
            {result.indicators.map((ind) => (
              <span className="rule-editor-chip" key={ind}>
                {ind}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
