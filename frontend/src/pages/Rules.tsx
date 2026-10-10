/**
 * Rules: the rule catalog, and a scratchpad for testing an expression.
 *
 * This page exists because the feature was unfindable, not because it was missing. `RuleEditor` and
 * `DecisionTable` were already mounted on `/symbol/:symbol`, reachable only after choosing a symbol,
 * with nothing in the navigation naming them. A UAT persona went looking for `/rules`, was silently
 * redirected to the portfolio by the catch-all route, and reported the rule engine as absent — an
 * entire phase of backend work, written off because the URL it guessed lied to it.
 *
 * The split between here and the ticker page is deliberate and worth stating, since the same two
 * components appear in both places:
 *
 * - **Rule *definitions* are symbol-independent.** `close > sma(20)` means the same thing whatever
 *   it is pointed at, so the catalog and the expression tester belong somewhere that does not make
 *   you pick a symbol first.
 * - **Rule *evaluation* is not.** A decision table is a rule applied to one symbol's bars, so it
 *   stays on the ticker page where the symbol already is. This page links there rather than
 *   duplicating it.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiRequestError } from "@/api/client";
import { rulesApi, type Rule } from "@/api/rules";
import RuleEditor from "@/components/RuleEditor";
import Term from "@/components/Term";
import { Trans, useT } from "@/i18n";

import "./Rules.css";

type Phase = "loading" | "loaded" | "empty" | "error";

export interface RulesProps {
  /**
   * True when this page is mounted as a TAB BODY (`Evidence.tsx`) rather than as its own route.
   * Only one thing changes: the page heading drops from `<h1>` to `<h2>`. Evidence already renders
   * the document's `<h1>`, and a second `<h1>` inside it makes the heading outline claim two
   * top-level documents on one page -- which is what a screen reader's heading list then offers.
   * Optional and defaulted, so `/rules` and every existing test keep the `<h1>` they had.
   */
  embedded?: boolean | undefined;
}

export default function Rules({ embedded = false }: RulesProps = {}) {
  const { t } = useT();
  const [rules, setRules] = useState<Rule[]>([]);
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    rulesApi
      .catalog()
      .then((result) => {
        if (cancelled) return;
        setRules(result);
        setPhase(result.length === 0 ? "empty" : "loaded");
      })
      .catch((error: unknown) => {
        if (cancelled || controller.signal.aborted) return;
        setMessage(
          error instanceof ApiRequestError
            ? t("strategy.error.apiStatus", { status: error.status, message: error.message })
            : t("strategy.rules.catalogLoadError"),
        );
        setPhase("error");
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const Heading = embedded ? "h2" : "h1";

  return (
    <>
      <Heading>{t("strategy.rules.title")}</Heading>
      <p className="subtitle">
        <Trans
          k="strategy.rules.subtitle"
          values={{ evaluated: <em>{t("strategy.rules.subtitleEvaluatedWord")}</em> }}
        />
      </p>

      <section className="panel">
        <h2>{t("strategy.rules.testHeading")}</h2>
        <p className="subtitle">
          <Trans
            k="strategy.rules.dslFieldsNote"
            values={{
              open: <code>open</code>,
              high: <code>high</code>,
              low: <code>low</code>,
              close: <code>close</code>,
              volume: <code>volume</code>,
              sma: <code>sma(20)</code>,
              // First use of RSI anywhere in the lab's own copy -- the field list is where a reader
              // meets the indicator, so the definition sits on the slot rather than in the sentence
              // (which lives in `strategy.rules.dslFieldsNote` and cannot carry markup).
              rsi: (
                <Term k="rsi">
                  <code>rsi(14)</code>
                </Term>
              ),
              bbLower: <code>bb_lower(20, 2)</code>,
            }}
          />
        </p>
        <RuleEditor />
      </section>

      {phase === "loading" && (
        <div className="panel">
          <div className="placeholder">{t("strategy.rules.loadingCatalog")}</div>
        </div>
      )}

      {phase === "error" && (
        <div className="panel">
          <div className="placeholder">{message}</div>
        </div>
      )}

      {phase === "empty" && (
        <div className="panel">
          <div className="placeholder">{t("strategy.rules.catalogEmpty")}</div>
        </div>
      )}

      {phase === "loaded" && (
        <section className="panel">
          <h2>{t("strategy.rules.catalogHeading")}</h2>
          {/* `.rules-catalog-table` (see Rules.css) is what makes DESCRIPTION readable at 1440px.
              `.data-table` sets `white-space: nowrap` on every cell, which is right for the columns
              that hold a figure or an identifier and wrong for the one column holding a sentence:
              each description stretched into a single unbroken line, pushing the table past the
              viewport so the column saying what a rule MEANS was the one a reader had to scroll to
              reach. Intervals are a short bounded set, so they become fixed-width badges instead of
              a comma-joined string competing for the same horizontal room. */}
          <div
            className="table-wrap"
            tabIndex={0}
            role="region"
            aria-label={t("strategy.rules.catalogHeading")}
          >
            <table className="data-table rules-catalog-table">
              <thead>
                <tr>
                  <th scope="col">{t("strategy.rules.header.rule")}</th>
                  {/* Every cell in this column is an expression in the rule DSL, and the catalog is
                      where a reader first meets one. The header keeps its own word; the definition
                      of the language it is written in hangs off it. */}
                  <th scope="col">
                    <Term k="ruleDsl">{t("strategy.rules.header.expression")}</Term>
                  </th>
                  <th scope="col">{t("strategy.rules.header.intervals")}</th>
                  <th scope="col">{t("strategy.rules.header.description")}</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.rule_id}>
                    <th scope="row">{rule.name}</th>
                    <td>
                      <code>{rule.expression}</code>
                    </td>
                    <td className="rules-intervals">
                      {rule.intervals.length === 0 ? (
                        <span className="rules-interval-badge rules-interval-any">
                          {t("strategy.rules.anyInterval")}
                        </span>
                      ) : (
                        rule.intervals.map((interval) => (
                          <span key={interval} className="rules-interval-badge">
                            {interval}
                          </span>
                        ))
                      )}
                    </td>
                    <td className="rules-description">{rule.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            <Trans
              k={rules.length === 1 ? "strategy.rules.catalogCount_one" : "strategy.rules.catalogCount_other"}
              values={{ count: rules.length, link: <Link to="/symbol/SPY">SPY</Link> }}
            />
          </p>
        </section>
      )}
    </>
  );
}
