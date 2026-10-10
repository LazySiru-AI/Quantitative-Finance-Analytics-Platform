/**
 * The thesis loop page: symbol input, a budget selector, a prominent warning that running consumes
 * trials permanently, the trial ledger, the holdout state, then results.
 *
 * `app/thesis/__init__.py`'s hazard statement calls this package "mostly machinery for saying no",
 * and the ordering of sections on this page is the UI half of that machinery. The ledger and the
 * holdout state render *before* any run -- both are ticker-wide facts that hold regardless of what
 * this session does, and a page that only shows them after a run invites reading a first result in
 * isolation from the trials that came before it. Running is never free: it is one more entry in the
 * ledger below whether or not it produces anything, and it may spend the ticker's one holdout
 * evaluation, so the warning above the run control says both things before the button is pressed,
 * not after.
 *
 * Every section here fails independently, following `Report.tsx`'s pattern: the ledger fetch,
 * the run, and each rendered card all own their own phase, so one bad request cannot blank the rest
 * of the page.
 */
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { INTERVAL_OPTIONS } from "@/api/market";
import type { Interval, MarketWarning } from "@/api/market";
import type { LoopOutcome, LoopResult, StrategyCard as StrategyCardData } from "@/api/thesis";
import Term from "@/components/Term";
import ThesisCard from "@/components/ThesisCard";
import TrialLedger from "@/components/TrialLedger";
import { describeHoldout, useThesisLedger, useThesisRun } from "@/hooks/useThesis";
import { t, useT } from "@/i18n";

const EXAMPLE_SYMBOLS = ["QQQ", "SOXL", "NVDA", "SPY"];

/** Matches `DEFAULT_ITERATION_BUDGET` in `backend/app/thesis/models.py`. Twelve because the budget's
 *  entire job is to make "kept going until something worked" impossible, and any finite number does
 *  that -- it is declared here rather than imported because the wire contract does not expose it as
 *  a constant. */
const DEFAULT_BUDGET = 12;
const BUDGET_OPTIONS = [6, 12, 20, 30] as const;

/**
 * The thesis loop, with no `<h1>` and no route of its own -- everything below the page title.
 *
 * Thesis is no longer a top-level destination: it is the Evidence page's fourth tab (`Evidence.tsx`),
 * which owns the surrounding chrome, and `/thesis/:symbol?` redirects there (`App.tsx`). So the
 * symbol arrives as a prop and a change is reported back through `onSymbolChange` rather than being
 * read from and written to a route param -- the caller decides where the symbol lives (Evidence keeps
 * it in `?symbol=`), which is what lets the same component sit under a tab and under a route without
 * knowing which it is.
 *
 * The run control, its warning, the trial ledger and the holdout panel are untouched: running still
 * spends a trial permanently and may spend the ticker's one holdout evaluation, and the warning above
 * the button still says both before anything is clicked. Folding this into a tab moves where the
 * component is mounted, never what pressing Run costs.
 */
export function ThesisSection({
  symbol,
  onSymbolChange,
}: {
  /** The symbol to show, already trimmed and upper-cased, or `null` for the empty prompt. */
  symbol: string | null;
  /** Called with a new upper-cased symbol when the reader submits one. */
  onSymbolChange: (symbol: string) => void;
}) {
  const [symbolInput, setSymbolInput] = useState(symbol ?? "");

  const submitSymbol = (value: string) => {
    const next = value.trim().toUpperCase();
    if (!next) return;
    onSymbolChange(next);
  };

  if (!symbol) {
    return (
      <ThesisPrompt
        value={symbolInput}
        onChange={setSymbolInput}
        onSubmit={(v) => {
          setSymbolInput(v);
          submitSymbol(v);
        }}
      />
    );
  }

  return (
    <ThesisDetail
      key={symbol}
      symbol={symbol}
      symbolInput={symbolInput}
      onSymbolInputChange={setSymbolInput}
      onSubmitSymbol={submitSymbol}
    />
  );
}

/**
 * The standalone page form: the page title plus the section above, with the symbol read from and
 * written back to `/thesis/:symbol?`.
 *
 * Nothing routes here any more -- `App.tsx` redirects that path to `/evidence?tab=thesis&symbol=…`.
 * Kept for the same reason `WashSales.tsx` keeps its own default export: the page's identity (its
 * `<h1>`) is a separate thing from the surface that moved, and a future standalone mount should get
 * it back rather than re-derive it.
 */
export default function ThesisPage() {
  const { symbol: rawSymbol } = useParams<{ symbol: string }>();
  const symbol = rawSymbol ? rawSymbol.toUpperCase() : null;
  const navigate = useNavigate();
  const { t } = useT();

  return (
    <>
      <h1>{t("strategy.thesis.pageTitle")}</h1>
      <ThesisSection
        symbol={symbol}
        onSymbolChange={(next) => navigate(`/thesis/${encodeURIComponent(next)}`)}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function ThesisPrompt({
  value,
  onChange,
  onSubmit,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
}) {
  const { t } = useT();
  return (
    <>
      {/* No `<h1>` -- see `ThesisSection`'s docstring. The page or tab that mounts this owns the
          heading; a second `<h1>` inside another page's body is a document-outline error. */}
      <p className="subtitle">{t("strategy.thesis.promptSubtitle")}</p>

      <div className="panel">
        <form
          className="symbol-form"
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit(value);
          }}
        >
          <input
            className="symbol-input"
            value={value}
            onChange={(e) => onChange(e.target.value.toUpperCase())}
            placeholder={t("strategy.thesis.symbolPlaceholder")}
            aria-label={t("common.symbol")}
            autoFocus
            spellCheck={false}
          />
          <button type="submit" className="symbol-submit">
            {t("strategy.thesis.goButton")}
          </button>
        </form>
        <div className="placeholder">{t("strategy.thesis.noSymbolYet")}</div>
        <div className="symbol-examples">
          {EXAMPLE_SYMBOLS.map((s) => (
            <button key={s} type="button" className="symbol-example" onClick={() => onSubmit(s)}>
              {s}
            </button>
          ))}
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Loaded page
// ---------------------------------------------------------------------------

function ThesisDetail({
  symbol,
  symbolInput,
  onSymbolInputChange,
  onSubmitSymbol,
}: {
  symbol: string;
  symbolInput: string;
  onSymbolInputChange: (value: string) => void;
  onSubmitSymbol: (value: string) => void;
}) {
  const { t } = useT();
  const [interval, setInterval] = useState<Interval>("1d");
  const [budget, setBudget] = useState<number>(DEFAULT_BUDGET);

  const ledger = useThesisLedger(symbol);
  const { result, phase: runPhase, message: runMessage, run } = useThesisRun();

  // A completed run changes the ledger (a new record lands, at minimum) and possibly the holdout
  // state, so the ledger section must reflect it without a full page reload.
  useEffect(() => {
    if (runPhase === "loaded") ledger.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runPhase]);

  const handleRun = () => {
    run({ symbol, interval, budget });
  };

  return (
    <>
      {/* An `<h2>`, not the `<h1>` this used to be: the symbol names this section, not the page --
          see `ThesisSection`'s docstring. */}
      <h2 className="section-heading">{symbol}</h2>
      <p className="subtitle">{t("strategy.thesis.detailSubtitle", { symbol })}</p>

      <div className="panel">
        <form
          className="symbol-form"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            onSubmitSymbol(symbolInput);
          }}
        >
          <input
            className="symbol-input"
            value={symbolInput}
            onChange={(e) => onSymbolInputChange(e.target.value.toUpperCase())}
            aria-label={t("common.symbol")}
            spellCheck={false}
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
            {t("strategy.thesis.goButton")}
          </button>
        </form>
      </div>

      <RunPanel
        symbol={symbol}
        budget={budget}
        onBudgetChange={setBudget}
        runPhase={runPhase}
        runMessage={runMessage}
        onRun={handleRun}
      />

      <TrialLedger
        symbol={symbol}
        stats={ledger.stats}
        records={ledger.records}
        phase={ledger.phase}
        message={ledger.message}
      />

      <HoldoutPanel symbol={symbol} phase={ledger.phase} holdout={ledger.holdout} />

      {result && <ThesisResults result={result} />}
    </>
  );
}

// ---------------------------------------------------------------------------
// Run control -- the warning sits above the button, not beside it, and states both
// permanent-trial-consumption and the holdout risk before the user can act.
// ---------------------------------------------------------------------------

function RunPanel({
  symbol,
  budget,
  onBudgetChange,
  runPhase,
  runMessage,
  onRun,
}: {
  symbol: string;
  budget: number;
  onBudgetChange: (budget: number) => void;
  runPhase: "idle" | "loading" | "loaded" | "error" | "notfound";
  runMessage: string | null;
  onRun: () => void;
}) {
  const { t } = useT();
  return (
    <div className="panel">
      <h2 className="section-heading">{t("strategy.thesis.runHeading")}</h2>

      <div className="callout callout-warn thesis-run-warning">
        {t("strategy.thesis.runWarning", { symbol })}
      </div>

      <div className="thesis-run-controls">
        <label className="bt-control-label" htmlFor="thesis-budget">
          {t("strategy.thesis.iterationBudgetLabel")}
          <select
            id="thesis-budget"
            className="bt-entry-select"
            value={budget}
            onChange={(e) => onBudgetChange(Number(e.target.value))}
          >
            {BUDGET_OPTIONS.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="symbol-submit"
          disabled={runPhase === "loading"}
          onClick={onRun}
        >
          {runPhase === "loading"
            ? t("strategy.thesis.runningButton")
            : t("strategy.thesis.runLoopButton", { budget })}
        </button>
      </div>

      {(runPhase === "error" || runPhase === "notfound") && (
        <div className="callout callout-danger">{runMessage}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Holdout state -- rendered whether or not a run has happened this session, because a burned or
// spent holdout may be the result of an earlier session entirely.
// ---------------------------------------------------------------------------

function HoldoutPanel({
  symbol,
  phase,
  holdout,
}: {
  symbol: string;
  phase: "idle" | "loading" | "loaded" | "error" | "notfound";
  holdout: import("@/api/thesis").HoldoutState | null;
}) {
  if (phase !== "loaded") return null;

  const status = holdout?.status ?? null;
  const calloutClass =
    status === "burned" ? "callout-danger" : status === "spent" ? "callout-info" : "callout-info";

  return (
    <div className="panel">
      {/* The word this whole panel turns on, at its first visible use on the page: a run can spend
          the ticker's one holdout evaluation, and a reader who reads "holdout" as "another test set"
          has no way to know why spending it matters. */}
      <h2 className="section-heading">
        <Term k="holdout">{t("strategy.thesis.holdoutHeading", { symbol })}</Term>
      </h2>
      <div className={`callout ${calloutClass} thesis-holdout-callout`}>
        {status === "burned" && holdout && (
          <strong>{t("strategy.thesisCard.holdoutBurnedHeadline", { attempts: holdout.attempts })} </strong>
        )}
        {describeHoldout(holdout)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

function ThesisResults({ result }: { result: LoopResult }) {
  const { t } = useT();
  return (
    <>
      <OutcomeBanner result={result} />

      {result.warnings.length > 0 && (
        <div className="panel">
          <h2 className="section-heading">{t("strategy.thesis.warningsHeading")}</h2>
          <div className="warnings-strip">
            {result.warnings.map((w: MarketWarning, i: number) => (
              <div className="warning-chip" key={`${w.kind}-${i}`}>
                <span className="kind">{w.kind}</span>
                <span className="message">{w.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {result.cards.length === 0 ? (
        <div className="panel">
          <div className="placeholder">{t("strategy.thesis.noCards")}</div>
        </div>
      ) : (
        result.cards.map((card: StrategyCardData) => <ThesisCard key={card.thesis_hash} card={card} />)
      )}
    </>
  );
}

/**
 * `budget_exhausted` renders with the same panel and the same `callout-info` treatment as
 * `survivor_found` -- per guard 4, "no thesis survived N attempts" is a finding about the ticker,
 * not a failed run, and styling it as an error would misrepresent what the loop just did. `no_data`
 * and `holdout_unavailable` are operational refusals rather than findings about the ticker, so they
 * get `callout-warn` instead -- a different kind of message, not a lesser one.
 */
function OutcomeBanner({ result }: { result: LoopResult }) {
  const { t } = useT();
  const calloutClass =
    result.outcome === "no_data" || result.outcome === "holdout_unavailable"
      ? "callout-warn"
      : "callout-info";

  return (
    <div className="panel">
      <h2 className="section-heading">{t("strategy.thesis.outcomeHeading")}</h2>
      <div className={`callout ${calloutClass} thesis-outcome`}>
        <div className="thesis-outcome-headline">{outcomeText(result)}</div>
        <div className="thesis-outcome-meta bt-cell-sub">
          {t("strategy.thesis.outcomeMeta", {
            used: result.iterations_used,
            budget: result.budget,
            started: result.started_at,
            finished: result.finished_at,
          })}
        </div>
      </div>
    </div>
  );
}

/**
 * The `default` branch below is a compile-time exhaustiveness check, same `const _exhaustive: never`
 * pattern as `verdictLabel`/`outcomeLabel` in `api/thesis.ts` -- see that module's docstring for why
 * a `default` branch narrowing to `never` is required here rather than relying on `strict` alone
 * (this project's `tsconfig.json` does not set `noImplicitReturns`).
 *
 * **Degrades instead of throwing.** This used to call a local `assertNeverOutcome` that threw --
 * closing the compile-time hole but reopening a worse one at runtime: `LoopOutcome` describes a
 * value this function receives from the *server*, not one this code constructs itself, so a
 * throwing default took the whole Thesis page down the moment the backend sent an outcome this
 * build had not been updated for. Matches `api/thesis.ts`'s `outcomeLabel`, which made the same
 * fix for the same reason.
 */
/** Exported for `Thesis.test.tsx` only -- this is otherwise an internal helper of `OutcomeBanner`
 *  below, not part of this page's public surface. */
export function outcomeText(result: LoopResult): string {
  const outcome: LoopOutcome = result.outcome;
  switch (outcome) {
    case "survivor_found": {
      const n = result.cards.filter((c: StrategyCardData) => c.verdict === "survived").length;
      return t(
        n === 1
          ? "strategy.thesis.outcomeText.survivorFound_one"
          : "strategy.thesis.outcomeText.survivorFound_other",
        { count: n, symbol: result.symbol },
      );
    }
    case "budget_exhausted":
      return t(
        result.iterations_used === 1
          ? "strategy.thesis.outcomeText.budgetExhausted_one"
          : "strategy.thesis.outcomeText.budgetExhausted_other",
        { count: result.iterations_used, symbol: result.symbol },
      );
    case "catalogue_exhausted":
      return t("strategy.thesis.outcomeText.catalogueExhausted", {
        symbol: result.symbol,
        count: result.iterations_used,
      });
    case "no_data":
      return t("strategy.thesis.outcomeText.noData", { symbol: result.symbol });
    case "holdout_unavailable":
      return t("strategy.thesis.outcomeText.holdoutUnavailable", { symbol: result.symbol });
    default: {
      const _exhaustive: never = outcome;
      void _exhaustive;
      return String(outcome);
    }
  }
}
