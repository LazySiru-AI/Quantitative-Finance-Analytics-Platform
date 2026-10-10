/**
 * The backtest workbench.
 *
 * Four sections, ordered by how much they can mislead you, cheapest claim first.
 *
 * **Drawdown** is descriptive. No hypothesis, no baseline, nothing to correct for — it can be read
 * at face value, and it is the only section on this page of which that is true.
 *
 * **Event study** is confirmatory, but only if the condition was chosen before looking. Nothing in
 * software can enforce that; what the UI can do is keep the baseline next to every hit rate and
 * give the *edge* the emphasis.
 *
 * **Scan** is where the honesty cost is paid, and it carries its trial count next to the results.
 *
 * **Reverse conditioning** is exploratory by construction and is rendered in its own visual
 * language so it cannot be mistaken for the section above it.
 *
 * Each section owns its own loading, error and empty state and fetches independently, so one failed
 * request degrades a panel rather than blanking the page.
 */

import { useState, type FormEvent } from "react";

import { INTERVAL_OPTIONS } from "@/api/market";
import type { Interval } from "@/api/market";
import DrawdownTable from "@/components/DrawdownTable";
import EventStudy from "@/components/EventStudy";
import ReverseConditioningPanel from "@/components/ReverseConditioning";
import ScanTable from "@/components/ScanTable";
import Term from "@/components/Term";
import { Trans, useT } from "@/i18n";

const EXAMPLES = ["SOXL", "QQQ", "NVDA", "SPY", "TLT"] as const;

export interface BacktestProps {
  /**
   * True when this page is mounted as a TAB BODY (`Evidence.tsx`) rather than as its own route.
   * Only one thing changes: the page heading drops from `<h1>` to `<h2>`. Evidence already renders
   * the document's `<h1>`, and a second `<h1>` inside it makes the heading outline claim two
   * top-level documents on one page -- which is what a screen reader's heading list then offers
   * (A11Y-02). Optional and defaulted, so `/backtest` and every existing test keep the `<h1>` they
   * had. Mirrors `Rules.tsx`/`Timeframes.tsx`'s own `embedded` prop.
   */
  embedded?: boolean | undefined;
}

export default function Backtest({ embedded = false }: BacktestProps = {}) {
  const { t } = useT();
  const [symbol, setSymbol] = useState("");
  const [input, setInput] = useState("");
  const [interval, setInterval] = useState<Interval>("1d");

  function submit(event: FormEvent) {
    event.preventDefault();
    const next = input.trim().toUpperCase();
    if (next) setSymbol(next);
  }

  const Heading = embedded ? "h2" : "h1";

  return (
    <>
      <Heading>{t("strategy.backtest.pageTitle")}</Heading>
      <p className="subtitle">
        <Trans
          k="strategy.backtest.pageSubtitle"
          values={{ nextBarOpen: <strong>{t("strategy.backtest.pageSubtitleNextBarOpenWord")}</strong> }}
        />
      </p>

      <div className="panel">
        <form className="symbol-form" onSubmit={submit}>
          <input
            className="symbol-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t("common.symbol")}
            aria-label={t("common.symbol")}
            spellCheck={false}
            maxLength={16}
          />
          <select
            className="bt-entry-select"
            value={interval}
            onChange={(e) => setInterval(e.target.value as Interval)}
            aria-label={t("strategy.backtest.intervalAriaLabel")}
          >
            {INTERVAL_OPTIONS.map((i) => (
              <option key={i.value} value={i.value}>
                {i.label}
              </option>
            ))}
          </select>
          <button type="submit" className="symbol-submit">
            {t("strategy.backtest.loadButton")}
          </button>
        </form>
        <div className="symbol-examples">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="symbol-example"
              onClick={() => {
                setInput(example);
                setSymbol(example);
              }}
            >
              {example}
            </button>
          ))}
        </div>
      </div>

      {symbol === "" ? (
        <div className="panel">
          <div className="placeholder">
            {t("strategy.backtest.emptyIntro")}
            <br />
            <br />
            {/* The empty state is this page's own first use of every section name it lists, and
                drawdown is the one that is a measurement rather than a label. The heading slot
                keeps its text and its emphasis; only the definition is added. */}
            <Trans
              k="strategy.backtest.emptyDrawdown"
              values={{
                heading: (
                  <Term k="drawdown">
                    <strong>{t("strategy.drawdown.title")}</strong>
                  </Term>
                ),
              }}
            />
            <br />
            <br />
            <Trans
              k="strategy.backtest.emptyEventStudy"
              values={{ heading: <strong>{t("strategy.eventStudy.title")}</strong> }}
            />
            <br />
            <br />
            <Trans
              k="strategy.backtest.emptyScan"
              values={{ heading: <strong>{t("strategy.scan.title")}</strong> }}
            />
            <br />
            <br />
            <Trans
              k="strategy.backtest.emptyReverse"
              values={{ heading: <strong>{t("strategy.backtest.reverseConditioningWord")}</strong> }}
            />
          </div>
        </div>
      ) : (
        <>
          <DrawdownTable symbol={symbol} interval={interval} />
          <EventStudy symbol={symbol} interval={interval} />
          <ScanTable symbol={symbol} interval={interval} />
          <ReverseConditioningPanel symbol={symbol} interval={interval} />
        </>
      )}
    </>
  );
}
