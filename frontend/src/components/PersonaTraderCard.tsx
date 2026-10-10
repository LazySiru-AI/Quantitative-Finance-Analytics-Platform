/**
 * One influencer's MODEL-DRIVEN paper trader book (Phase 10) -- the counterpart to
 * `PersonaBookCard.tsx` (Phase 6's deterministic call-replay book). Instead of mechanically
 * replaying dated bullish calls, this asks the persona's model, as the persona, what to buy/sell at
 * each weekly decision using its consolidated method and a point-in-time market snapshot. See
 * `docs/INFLUENCER-CONTRACT.md`'s "Phase 10" section and `@/api/personas`'s `TraderBook` docstring,
 * mirrored field for field.
 *
 * **Presentational only -- this component fetches nothing.** A caller (the Paper Desk) owns
 * fetching `GET /api/personas/trader/books` (or one persona's `GET /{slug}/trader`), running
 * `decide`/`backfill`/`reset`, and passing the loaded `TraderBook` plus the in-flight state for each
 * action back in. That is why `decideState`/`backfillState` are plain unions the caller drives, not
 * fetch state this component owns.
 *
 * **Two caveats are ALWAYS rendered, never behind a disclosure.** Unlike `PersonaBookCard`'s single
 * paper-projection line (an `InfoNote` with a collapsible detail), Phase 10's contract pins two
 * *distinct* caveats that must both stay visible: (1) point-in-time market data, but a method
 * distilled from the whole corpus -- "how their approach would have traded," not a live record; (2)
 * no measured edge -- descriptive/experimental, never advice. Rendered here as two plain `InfoNote`s
 * with no `children`, which is this codebase's established way to get `InfoNote`'s visual treatment
 * without its disclosure affordance (see `InfoNote.tsx`'s own docstring: no children -> plain
 * paragraph, no `<details>`).
 *
 * **Money/quantity fields are decimal strings, never numbers**, formatted through `@/api/paperdesk`'s
 * helpers exactly like `PersonaBookCard`. `return_pct` is a 0-1 FRACTION -- see `TraderBook`'s own
 * docstring on the historical percent-vs-fraction bug this discipline avoids.
 *
 * **The equity-curve sparkline parses `TraderEquityPoint.equity` with `Number()` for chart
 * *plotting* only** (an SVG y-coordinate), never for arithmetic or a displayed figure -- the actual
 * first/last equity VALUES shown as text still go through `formatMoney` on the original decimal
 * string, matching `api/paperdesk.ts`'s own "parse for display, never for money math" rule.
 *
 * **All three controls confirm first, through the one `ConfirmSheet`.** Decide and Backfill each put
 * a paid model call behind a single click -- one call for Decide, one call *per week since inception*
 * for Backfill -- and Reset destroys the book. That is exactly the line `pages/data/UsersPanel.tsx`
 * draws: confirm what spends or destroys, never what merely recomputes. Each sheet's preview names
 * the provider call and the daily cap, and shows `book.spent_usd` -- the one spend figure this
 * component actually has. It shows no projection: the cost of a run that has not happened is not a
 * number this card is given, and inventing one would be worse than saying nothing.
 */
import { useMemo, useState } from "react";

import {
  formatMoney,
  formatSignedFractionPctString,
  formatWeightPct,
} from "@/api/paperdesk";
import type { DecimalString } from "@/api/client";
import type {
  TraderBook,
  TraderDecisionRec,
  TraderEquityPoint,
  TraderPosition,
  TraderTradeRec,
} from "@/api/personas";
import { ConfirmSheet } from "@/components/ConfirmSheet";
import { InfoNote } from "@/components/InfoNote";
import { ScrollRegion } from "@/components/ScrollPanel";
import { TranslatedStatusPill } from "@/components/StatusPill";
import { useT } from "@/i18n";
import type { MessageKey } from "@/i18n/catalog";

import "./PersonaTraderCard.css";

/** How many decisions render before "show all" -- older ones are collapsed rather than dropped, the
 * same "kept, one click away" rule `docs/COPY-STYLE.md` applies to long copy applied here to a long
 * list instead. */
const VISIBLE_DECISIONS = 5;

export type DecideState = { phase: "idle" } | { phase: "pending" } | { phase: "error"; message: string };
export type BackfillState =
  | { phase: "idle" }
  | { phase: "running"; decided: number }
  | { phase: "error"; message: string };

export interface PersonaTraderCardProps {
  book: TraderBook;
  decideState: DecideState;
  backfillState: BackfillState;
  onDecide: () => void;
  /** `inception` is a "YYYY-MM-DD" string from a date input. */
  onBackfill: (inception: string) => void;
  onReset: () => void;
}

const SIDE_LABEL_KEYS: Record<TraderTradeRec["side"], MessageKey> = {
  buy: "personaTrader.sideBuy",
  sell: "personaTrader.sideSell",
};

/** Which of the three guarded actions has its `ConfirmSheet` open. */
type PendingAction = "decide" | "backfill" | "reset" | null;

export default function PersonaTraderCard({
  book,
  decideState,
  backfillState,
  onDecide,
  onBackfill,
  onReset,
}: PersonaTraderCardProps) {
  const { t } = useT();
  const [backfillDate, setBackfillDate] = useState(book.inception);
  const [showAllDecisions, setShowAllDecisions] = useState(false);
  const [confirming, setConfirming] = useState<PendingAction>(null);

  const heading = t("personaTrader.heading", { name: book.display_name });
  const decidePending = decideState.phase === "pending";
  const backfillRunning = backfillState.phase === "running";
  const visibleDecisions = showAllDecisions ? book.decisions : book.decisions.slice(0, VISIBLE_DECISIONS);
  const hiddenCount = book.decisions.length - visibleDecisions.length;

  return (
    <div className="panel persona-trader-card">
      <div className="persona-trader-head">
        <h3 className="persona-card-subhead">{heading}</h3>
        <TranslatedStatusPill tone="special" labelKey="personaTrader.experimentalPill" />
      </div>

      {/* Both caveats, always visible -- see this module's docstring. Never collapse either behind
          the InfoNote disclosure `children` would otherwise offer. */}
      <InfoNote summary={t("personaTrader.caveatPointInTime")} className="persona-trader-caveat" />
      <InfoNote summary={t("personaTrader.caveatNoEdge")} className="persona-trader-caveat" />

      <div className="tile-grid persona-trader-tiles">
        <div className="stat tile">
          <span className="label">{t("personaTrader.equity")}</span>
          <span className="value">{formatMoney(book.equity)}</span>
        </div>
        <div className="stat tile">
          <span className="label">{t("personaTrader.returnPct")}</span>
          <span className="value">{formatSignedFractionPctString(book.return_pct, 2)}</span>
        </div>
        <div className="stat tile">
          <span className="label">{t("personaTrader.vsBenchmark", { benchmark: book.benchmark })}</span>
          <span className="value">
            {book.excess_pct !== null
              ? formatSignedFractionPctString(book.excess_pct, 2)
              : t("personaTrader.noBenchmark")}
          </span>
          {book.benchmark_return_pct !== null && (
            <span className="muted persona-trader-bench-sub">
              {t("personaTrader.benchmarkReturn", {
                benchmark: book.benchmark,
                pct: formatSignedFractionPctString(book.benchmark_return_pct, 1),
              })}
            </span>
          )}
        </div>
        <div className="stat tile">
          <span className="label">{t("personaTrader.cash")}</span>
          <span className="value">{formatMoney(book.cash)}</span>
        </div>
        <div className="stat tile">
          <span className="label">{t("personaTrader.inception")}</span>
          <span className="value persona-trader-date-value">{book.inception}</span>
        </div>
        <div className="stat tile">
          <span className="label">{t("personaTrader.asOfLabel")}</span>
          <span className="value persona-trader-date-value">
            {book.as_of ?? t("personaTrader.notYetDecided")}
          </span>
        </div>
      </div>

      {book.warnings.length > 0 && (
        <ul className="warning-list persona-trader-warnings">
          {book.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}

      <section className="persona-trader-section">
        <h4>{t("personaTrader.equityCurveHeading")}</h4>
        <EquityCurve curve={book.equity_curve} />
      </section>

      <details className="persona-trader-section" open>
        <summary>{t("personaTrader.holdingsHeading")}</summary>
        {book.positions.length === 0 ? (
          <p className="muted persona-trader-empty">{t("personaTrader.holdingsEmpty")}</p>
        ) : (
          <ScrollRegion size="md" label={t("personaTrader.holdingsHeading")}>
            <div className="table-wrap">
              <table className="data-table position-table persona-trader-table">
                <thead>
                  <tr>
                    <th scope="col">{t("common.symbol")}</th>
                    <th scope="col" className="num">
                      {t("common.quantity")}
                    </th>
                    <th scope="col" className="num">
                      {t("personaTrader.lastPrice")}
                    </th>
                    <th scope="col" className="num">
                      {t("personaTrader.marketValue")}
                    </th>
                    <th scope="col" className="num">
                      {t("common.weight")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {book.positions.map((p) => (
                    <PositionRow key={p.symbol} position={p} />
                  ))}
                </tbody>
              </table>
            </div>
          </ScrollRegion>
        )}
      </details>

      <details className="persona-trader-section" open>
        <summary>{t("personaTrader.decisionsHeading")}</summary>
        {book.decisions.length === 0 ? (
          <p className="muted persona-trader-empty">{t("personaTrader.decisionsEmpty")}</p>
        ) : (
          <>
            <ul className="persona-trader-decision-list">
              {visibleDecisions.map((d, i) => (
                <DecisionRow key={`${d.decided_on}-${i}`} decision={d} />
              ))}
            </ul>
            {hiddenCount > 0 && (
              <button
                type="button"
                className="download-link persona-trader-show-all"
                onClick={() => setShowAllDecisions(true)}
              >
                {t("personaTrader.showAllDecisions", { count: book.decisions.length })}
              </button>
            )}
            {showAllDecisions && book.decisions.length > VISIBLE_DECISIONS && (
              <button
                type="button"
                className="download-link persona-trader-show-all"
                onClick={() => setShowAllDecisions(false)}
              >
                {t("personaTrader.showFewerDecisions")}
              </button>
            )}
          </>
        )}
      </details>

      <div className="persona-trader-controls">
        <div className="persona-trader-control-row">
          <button
            type="button"
            className="download-link"
            onClick={() => setConfirming("decide")}
            disabled={decidePending}
          >
            {decidePending ? t("personaTrader.decidePending") : t("personaTrader.decideButton")}
          </button>
          {decideState.phase === "error" && (
            <div className="callout callout-danger persona-trader-inline-error" role="alert">
              {decideState.message}
            </div>
          )}
        </div>

        <div className="persona-trader-control-row">
          <label className="persona-trader-backfill-field">
            <span className="persona-trader-backfill-label">{t("personaTrader.backfillDateLabel")}</span>
            <input
              type="date"
              value={backfillDate}
              disabled={backfillRunning}
              onChange={(e) => setBackfillDate(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="download-link"
            onClick={() => setConfirming("backfill")}
            disabled={backfillRunning}
          >
            {backfillRunning
              ? t("personaTrader.backfillRunning", { decided: backfillState.decided })
              : t("personaTrader.backfillButton")}
          </button>
          {backfillState.phase === "error" && (
            <div className="callout callout-danger persona-trader-inline-error" role="alert">
              {backfillState.message}
            </div>
          )}
        </div>

        <div className="persona-trader-control-row">
          <button
            type="button"
            className="download-link persona-trader-reset"
            onClick={() => setConfirming("reset")}
          >
            {t("personaTrader.resetButton")}
          </button>
        </div>
      </div>

      <ConfirmSheet
        open={confirming !== null}
        question={
          confirming === "decide"
            ? t("personaTrader.decideConfirm.title")
            : confirming === "backfill"
              ? t("personaTrader.backfillConfirm.title", { date: backfillDate })
              : t("personaTrader.resetConfirm.title")
        }
        preview={
          <>
            <p>
              {confirming === "decide"
                ? t("personaTrader.decideConfirm.body")
                : confirming === "backfill"
                  ? t("personaTrader.backfillConfirm.body")
                  : t("personaTrader.resetConfirm.body")}
            </p>
            <p className="muted">
              {t("personaTrader.confirmSpentSoFar", { spent: formatMoney(book.spent_usd) })}
            </p>
          </>
        }
        confirmLabel={
          confirming === "decide"
            ? t("personaTrader.decideConfirm.confirm")
            : confirming === "backfill"
              ? t("personaTrader.backfillConfirm.confirm")
              : t("personaTrader.resetConfirm.confirm")
        }
        tone={confirming === "reset" ? "bad" : "warn"}
        onConfirm={() => {
          const action = confirming;
          setConfirming(null);
          if (action === "decide") onDecide();
          else if (action === "backfill") onBackfill(backfillDate);
          else if (action === "reset") onReset();
        }}
        onCancel={() => setConfirming(null)}
      />
    </div>
  );
}

function PositionRow({ position: p }: { position: TraderPosition }) {
  return (
    <tr>
      <td className="position-symbol-cell">
        <span className="position-symbol">{p.symbol}</span>
      </td>
      <td className="num">{p.quantity}</td>
      <td className="num">{formatMoney(p.last_price)}</td>
      <td className="num">{formatMoney(p.market_value)}</td>
      <td className="num">{formatWeightPct(p.weight, 2)}</td>
    </tr>
  );
}

function DecisionRow({ decision }: { decision: TraderDecisionRec }) {
  const { t } = useT();
  return (
    <li className="persona-trader-decision">
      <div className="persona-trader-decision-head">
        <span className="persona-trader-decision-dates">
          {t("personaTrader.decidedFilled", { decidedOn: decision.decided_on, fillDate: decision.fill_date })}
        </span>
        {decision.degraded && <TranslatedStatusPill tone="warn" labelKey="personaTrader.degradedPill" />}
      </div>
      {decision.commentary && <p className="persona-trader-decision-commentary">{decision.commentary}</p>}
      {decision.trades.length > 0 && (
        <ul className="persona-trader-decision-trades">
          {decision.trades.map((trade, i) => (
            <li key={i}>
              {t("personaTrader.tradeLine", {
                side: t(SIDE_LABEL_KEYS[trade.side]),
                quantity: trade.quantity,
                symbol: trade.symbol,
                price: formatMoney(trade.price),
              })}
              {trade.thesis ? ` -- ${trade.thesis}` : ""}
            </li>
          ))}
        </ul>
      )}
      {decision.rejections.length > 0 && (
        <div className="persona-trader-decision-rejections muted">
          <span>{t("personaTrader.rejectionsHeading")}</span>
          <ul>
            {decision.rejections.map((r, i) => (
              <li key={i}>{t("personaTrader.rejectionLine", { symbol: r.symbol, reason: r.reason })}</li>
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

/** Chart-only parse of a decimal-string equity value -- for the SVG y-coordinate, never for a
 * displayed figure or arithmetic. See this module's own docstring. */
function equityNumber(value: DecimalString): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

const CURVE_WIDTH = 300;
const CURVE_HEIGHT = 56;

function EquityCurve({ curve }: { curve: TraderEquityPoint[] }) {
  const { t } = useT();

  const points = useMemo(() => {
    if (curve.length === 0) return "";
    const values = curve.map((p) => equityNumber(p.equity));
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const stepX = curve.length > 1 ? CURVE_WIDTH / (curve.length - 1) : 0;
    return values
      .map((v, i) => {
        const x = curve.length > 1 ? i * stepX : CURVE_WIDTH / 2;
        const y = CURVE_HEIGHT - ((v - min) / span) * CURVE_HEIGHT;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }, [curve]);

  if (curve.length === 0) {
    return <p className="muted persona-trader-empty">{t("personaTrader.equityCurveEmpty")}</p>;
  }

  const first = curve[0];
  const last = curve[curve.length - 1];
  const ariaLabel =
    first && last
      ? t("personaTrader.equityCurveAriaLabel", {
          start: formatMoney(first.equity),
          startDate: first.date,
          end: formatMoney(last.equity),
          endDate: last.date,
        })
      : t("personaTrader.equityCurveHeading");

  return (
    <div className="persona-trader-sparkline-wrap">
      <svg
        viewBox={`0 0 ${CURVE_WIDTH} ${CURVE_HEIGHT}`}
        className="persona-trader-sparkline"
        role="img"
        aria-label={ariaLabel}
        preserveAspectRatio="none"
      >
        <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
      <div className="persona-trader-sparkline-labels">
        {first && (
          <span>
            {first.date}: {formatMoney(first.equity)}
          </span>
        )}
        {last && (
          <span>
            {last.date}: {formatMoney(last.equity)}
          </span>
        )}
      </div>
    </div>
  );
}
