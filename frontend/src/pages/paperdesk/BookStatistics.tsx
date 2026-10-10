import { Link } from "react-router-dom";

import type { DecimalString } from "@/api/client";
import {
  decisionActionLabel,
  exitReasonLabel,
  formatFractionPctString,
  formatInstant,
  formatMoney,
  formatMoneyOrDash,
  formatRankValue,
  formatSignedFractionPctString,
  formatSignedMoney,
  formatWeightPct,
  fractionStringTone,
  moneyTone,
  type AutopilotDescription,
  type Decision,
  type Desk,
  type LadderDescription,
  type Signal,
  type Trade,
} from "@/api/paperdesk";
import { Trans, type Translator, useT } from "@/i18n";

// ---------------------------------------------------------------------------
// Book statistics -- demoted, not deleted. Collapsed by default, and now nested inside
// `DeskPanel`'s own "Statistics & details" disclosure: still there for an "is this strategy
// healthy" check, but no longer the first thing the panel shows and no longer paid for in height.
//
// None of the tables below carries a `ScrollRegion` or a `.table-wrap` any more. Every one of them
// renders inside the desk card's single scrolling body (`Card`'s `card-body`), and a scroller
// nested in a scroller traps the wheel and makes the inner content unreachable on touch -- the rule
// `ScrollPanel.tsx`'s own docstring states as "ONE scroll region per card".
// ---------------------------------------------------------------------------

export default function BookStatistics({ desk }: { desk: Desk }) {
  const { t } = useT();
  return (
    <details className="desk-section desk-book-stats">
      <summary className="desk-book-stats-summary">{t("paperDesk.bookStats.summary")}</summary>
      <div className="desk-book-stats-body">
        <DeskTiles desk={desk} />
        <PnlTiles desk={desk} />
        <SignalsTable signals={desk.signals} rankBy={desk.rank_by} />
        <DecisionsTable decisions={desk.decisions} />
        <TradesTable trades={desk.trades} />
        {desk.kind === "ladder" && desk.ladder ? (
          <DeskLadderDescription desk={desk} ladder={desk.ladder} />
        ) : desk.kind === "autopilot" && desk.autopilot ? (
          <DeskAutopilotDescription desk={desk} autopilot={desk.autopilot} />
        ) : (
          <DeskRules desk={desk} />
        )}
      </div>
    </details>
  );
}

function DeskTiles({ desk }: { desk: Desk }) {
  const { t } = useT();
  return (
    <div className="tile-grid desk-tile-grid">
      <MoneyStat label={t("common.equity")} value={desk.equity} emphasize />
      <MoneyStat label={t("common.cash")} value={desk.cash} />
      <MoneyStat label={t("paperDesk.tiles.positionsValue")} value={desk.positions_value} />
      <FractionStat label={t("paperDesk.tiles.totalReturn")} value={desk.total_return} signed />
      <FractionStat
        label={t("paperDesk.tiles.excessVsBenchmark")}
        hint={t("paperDesk.tiles.excessVsBenchmarkHint")}
        value={desk.excess_return}
        signed
      />
      <FractionStat label={t("paperDesk.tiles.maxDrawdown")} value={desk.max_drawdown} />
      <div className="stat tile">
        <span className="label" title={t("paperDesk.tiles.capitalExposureHint")}>
          {t("paperDesk.tiles.capitalExposure")}
        </span>
        <span className="value">{formatWeightPct(desk.capital_exposure, 2)}</span>
      </div>
      <div className="stat tile">
        <span className="label">{t("paperDesk.tiles.openPositions")}</span>
        <span className="value">
          {/* A ladder card has no per-position slot count (`max_positions` is null for it -- see
              `Desk.max_positions`'s own docstring); its own "slots" are simply how many of its three
              sleeves are currently held at a nonzero weight, out of its whole universe. */}
          {desk.open_positions} / {desk.max_positions ?? desk.universe.length}
        </span>
        <span className="tile-hint">
          {t(
            desk.slots_free === 1 ? "paperDesk.tiles.slotsFree_one" : "paperDesk.tiles.slotsFree_other",
            { count: desk.slots_free },
          )}
        </span>
      </div>
    </div>
  );
}

function MoneyStat({
  label,
  value,
  emphasize,
}: {
  label: string;
  value: DecimalString;
  emphasize?: boolean;
}) {
  return (
    <div className="stat tile">
      <span className="label">{label}</span>
      <span className={`value${emphasize ? " value-emphasize" : ""}`}>{formatMoney(value)}</span>
    </div>
  );
}

function FractionStat({
  label,
  value,
  signed,
  hint,
}: {
  label: string;
  value: DecimalString;
  signed?: boolean;
  hint?: string;
}) {
  const tone = signed ? fractionStringTone(value) : "";
  const text = signed ? formatSignedFractionPctString(value) : formatFractionPctString(value);
  return (
    <div className="stat tile">
      <span className="label" title={hint}>
        {label}
      </span>
      <span className={`value${tone ? ` ${tone}` : ""}`}>{text}</span>
    </div>
  );
}

/**
 * Realised and unrealised P&L, rendered as two separate figures -- never summed. See the page and
 * module docstrings for why: a mark against the last stored close is not money taken, so combining
 * the two into one headline would state a certainty about the unrealised half this desk does not
 * have until the position actually closes.
 */
function PnlTiles({ desk }: { desk: Desk }) {
  const { t } = useT();
  const realisedTone = moneyTone(desk.realised_pnl);
  const unrealisedTone = moneyTone(desk.unrealised_pnl);
  return (
    <div className="tile-grid desk-pnl-grid">
      <div className="stat tile">
        <span className="label">{t("paperDesk.pnl.realised")}</span>
        <span className={`value${realisedTone ? ` ${realisedTone}` : ""}`}>
          {formatSignedMoney(desk.realised_pnl)}
        </span>
        <span className="tile-hint">{t("paperDesk.pnl.realisedHint")}</span>
      </div>
      <div className="stat tile">
        <span className="label">{t("paperDesk.pnl.unrealisedMark")}</span>
        <span className={`value${unrealisedTone ? ` ${unrealisedTone}` : ""}`}>
          {formatSignedMoney(desk.unrealised_pnl)}
        </span>
        <span className="tile-hint">{t("paperDesk.pnl.unrealisedHint")}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Signals
// ---------------------------------------------------------------------------

/**
 * Every universe symbol's current standing.
 *
 * Row order is the backend's, and for a ranked desk that is the engine's own entry order rather
 * than the order `universe` was typed in -- so reading down the table is reading down the priority
 * the desk would actually apply. `rankBy` adds the key column and, more importantly, labels it:
 * `1.0712` means nothing until the header says it is `close / sma(200)`.
 */
function SignalsTable({ signals, rankBy = null }: { signals: Signal[]; rankBy?: string | null }) {
  const { t } = useT();
  return (
    <div className="desk-section">
      <h3>{t("paperDesk.signals.title")}</h3>
      {rankBy !== null && (
        <p className="muted desk-signals-rank-note">
          <Trans
            k="paperDesk.signals.rankNote"
            values={{ rankBy: <code>{rankBy}</code>, dash: <span aria-hidden="true">—</span> }}
          />
        </p>
      )}
      {signals.length === 0 ? (
        <div className="placeholder">{t("paperDesk.signals.empty")}</div>
      ) : (
        <table className="data-table desk-signals-table">
          <thead>
            <tr>
              <th scope="col">{t("common.symbol")}</th>
              <th scope="col">{t("paperDesk.signals.held")}</th>
              <th scope="col">{t("paperDesk.signals.entryFires")}</th>
              <th scope="col">{t("paperDesk.signals.exitFires")}</th>
              <th scope="col" className="num">
                {t("paperDesk.signals.lastClose")}
              </th>
              {rankBy !== null && (
                <th scope="col" className="num" title={rankBy}>
                  {t("paperDesk.signals.rankKey")}
                </th>
              )}
              <th scope="col">{t("paperDesk.signals.blocked")}</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((s) => (
              <tr key={s.symbol}>
                <td className="position-symbol-cell">
                  <span className="position-symbol">{s.symbol}</span>
                </td>
                <td>
                  <StatePill
                    value={s.held}
                    trueLabel={t("paperDesk.signals.held")}
                    falseLabel={t("paperDesk.signals.heldFalse")}
                  />
                </td>
                <td>
                  <StatePill
                    value={s.entry_fires}
                    trueLabel={t("paperDesk.signals.firesTrue")}
                    falseLabel={t("paperDesk.signals.firesFalse")}
                  />
                </td>
                <td>
                  <StatePill
                    value={s.exit_fires}
                    trueLabel={t("paperDesk.signals.firesTrue")}
                    falseLabel={t("paperDesk.signals.firesFalse")}
                  />
                </td>
                <td className="num">{formatMoneyOrDash(s.last_close)}</td>
                {rankBy !== null && (
                  <td className="num desk-signals-rank-cell">
                    {formatRankValue(s.rank_value)}
                    {s.entry_rank !== null && (
                      <span className="badge desk-rank-badge">#{s.entry_rank}</span>
                    )}
                  </td>
                )}
                <td>
                  {s.blocked ? (
                    <span className="badge basis-uncertain desk-blocked-badge">{s.blocked}</span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function StatePill({
  value,
  trueLabel,
  falseLabel,
}: {
  value: boolean;
  trueLabel: string;
  falseLabel: string;
}) {
  return (
    <span className={`state-pill ${value ? "state-true" : "state-false"}`}>
      {value ? trueLabel : falseLabel}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Decisions
// ---------------------------------------------------------------------------

function DecisionsTable({ decisions }: { decisions: Decision[] }) {
  const { t } = useT();
  return (
    <div className="desk-section">
      <h3>{t("paperDesk.decisionsTable.title")}</h3>
      {decisions.length === 0 ? (
        <div className="placeholder">{t("paperDesk.noDecisionsYet")}</div>
      ) : (
        <table className="data-table desk-decisions-table">
          <thead>
            <tr>
              <th scope="col">{t("common.date")}</th>
              <th scope="col">{t("common.symbol")}</th>
              <th scope="col">{t("common.action")}</th>
              <th scope="col">{t("paperDesk.decisionsTable.reason")}</th>
              <th scope="col" className="num">
                {t("common.price")}
              </th>
              <th scope="col" className="num">
                {t("common.quantity")}
              </th>
              <th scope="col" className="num">
                {t("paperDesk.staged.notional")}
              </th>
            </tr>
          </thead>
          <tbody>
            {decisions.map((d, i) => (
              <tr key={`${d.date}-${d.symbol}-${i}`}>
                <td>{d.date}</td>
                <td className="position-symbol-cell">
                  <span className="position-symbol">{d.symbol}</span>
                </td>
                <td>
                  <span className={`badge desk-action-badge desk-action-${d.action}`}>
                    {decisionActionLabel(d.action)}
                  </span>
                </td>
                <td className="muted">{d.reason}</td>
                <td className="num">{formatMoney(d.price)}</td>
                <td className="num">{d.quantity}</td>
                <td className="num">{formatMoney(d.notional)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trades
// ---------------------------------------------------------------------------

function TradesTable({ trades }: { trades: Trade[] }) {
  const { t } = useT();
  return (
    <div className="desk-section">
      <h3>{t("paperDesk.trades.title")}</h3>
      {trades.length === 0 ? (
        <div className="placeholder">{t("paperDesk.trades.empty")}</div>
      ) : (
        <table className="data-table desk-trades-table">
          <thead>
            <tr>
              <th scope="col">{t("common.symbol")}</th>
              <th scope="col">{t("paperDesk.holdings.entryDate")}</th>
              <th scope="col" className="num">
                {t("paperDesk.holdings.entryPrice")}
              </th>
              <th scope="col">{t("paperDesk.trades.exitDate")}</th>
              <th scope="col" className="num">
                {t("paperDesk.trades.exitPrice")}
              </th>
              <th scope="col" className="num">
                {t("common.quantity")}
              </th>
              <th scope="col">{t("paperDesk.trades.exitReason")}</th>
              <th scope="col" className="num">
                {t("paperDesk.trades.pnl")}
              </th>
              <th scope="col" className="num">
                {t("paperDesk.returnHeader")}
              </th>
              <th scope="col" className="num">
                {t("paperDesk.trades.barsHeld")}
              </th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => (
              <TradeRow key={`${t.symbol}-${t.exit_date}-${i}`} trade={t} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function TradeRow({ trade: t }: { trade: Trade }) {
  const tone = moneyTone(t.pnl);
  return (
    <tr>
      <td className="position-symbol-cell">
        <span className="position-symbol">{t.symbol}</span>
      </td>
      <td>{t.entry_date}</td>
      <td className="num">{formatMoney(t.entry_price)}</td>
      <td>{t.exit_date}</td>
      <td className="num">{formatMoney(t.exit_price)}</td>
      <td className="num">{t.quantity}</td>
      <td>{exitReasonLabel(t.exit_reason)}</td>
      <td className="num">
        <span className={`position-unrealized-value ${tone}`}>{formatSignedMoney(t.pnl)}</span>
      </td>
      <td className="num">{formatSignedFractionPctString(t.return_pct)}</td>
      <td className="num">{t.bars_held}</td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// The desk's own rules
// ---------------------------------------------------------------------------

function DeskRules({ desk }: { desk: Desk }) {
  const { t } = useT();
  return (
    <div className="desk-section desk-rules-section">
      <h3>{t("paperDesk.rules.heading")}</h3>
      <pre className="desk-rules-block">
        <div>
          <span className="muted">{t("paperDesk.rules.universe")}</span>
          {desk.universe.join(", ")}
        </div>
        <div>
          <span className="muted">{t("paperDesk.rules.entry")}</span>
          {desk.entry}
        </div>
        <div>
          <span className="muted">{t("paperDesk.rules.exit")}</span>
          {desk.exit}
        </div>
        <div>
          <span className="muted">{t("paperDesk.rules.stopLoss")}</span>
          {/* A bare dash here would read as a formatting bug in a block whose whole job is stating
              the strategy's risk controls -- the card genuinely declines a hard stop, so the
              rules block says so in words. */}
          {desk.stop_loss_pct === null
            ? t("paperDesk.rules.noStopLoss")
            : formatFractionPctString(desk.stop_loss_pct)}
        </div>
        <div>
          <span className="muted">{t("paperDesk.rules.takeProfit")}</span>
          {desk.take_profit_pct === null ? "—" : formatFractionPctString(desk.take_profit_pct)}
        </div>
        <div>
          <span className="muted">{t("paperDesk.rules.maxHold")}</span>
          {desk.max_hold_days === null
            ? t("paperDesk.rules.noHoldCap")
            : t("paperDesk.rules.maxHoldValue", { days: desk.max_hold_days })}
        </div>
        <div>
          <span className="muted">{t("paperDesk.rules.maxPositions")}</span>
          {desk.max_positions}
        </div>
        <div>
          <span className="muted">{t("paperDesk.rules.positionSize")}</span>
          {t("paperDesk.rules.positionSizeValue", {
            pct: formatFractionPctString(desk.position_pct),
          })}
        </div>
      </pre>
      <details className="desk-thesis-detail">
        <summary>{t("paperDesk.rules.thesis")}</summary>
        <p className="muted">{desk.thesis}</p>
      </details>
    </div>
  );
}

/**
 * The `kind === "ladder"` counterpart to `DeskRules`. A drawdown-ladder card has no per-symbol
 * boolean entry/exit rule at all -- its every decision is a portfolio weight driven by one shared
 * signal (SPY's own drawdown from its all-time closing high), not an in-or-out rule per universe
 * symbol -- so rendering `entry`/`exit` prose for it would misrepresent how the card actually
 * executes (see the backend's `app.paperdesk.models.LadderDescription` docstring). This renders the
 * ladder's own mechanism instead: the base state, the confirmation gate, the funding order and the
 * recovery terms, reusing the same `.desk-rules-block` class `DeskRules` already uses. The rung
 * table itself is no longer here -- it is `LadderRungs` above, rendered in the card body as this
 * kind's forward-looking block, because which rung is active is what the card does next rather than
 * a description of how it is configured.
 */
function DeskLadderDescription({ desk, ladder }: { desk: Desk; ladder: LadderDescription }) {
  const { t } = useT();
  return (
    <div className="desk-section desk-rules-section desk-ladder-section">
      <h3>{t("paperDesk.rules.heading")}</h3>
      <pre className="desk-rules-block">
        <div>
          <span className="muted">{t("paperDesk.rules.universe")}</span>
          {desk.universe.join(", ")}
        </div>
        <div>
          <span className="muted">{t("paperDesk.ladder.signal")}</span>
          {t("paperDesk.ladder.signalValue", { symbol: ladder.signal_symbol })}
        </div>
        <div>
          <span className="muted">{t("paperDesk.ladder.baseState")}</span>
          {formatFractionPctString(ladder.base_defensive_weight_pct)} {ladder.defensive_symbol} /{" "}
          {formatFractionPctString(ladder.base_bond_weight_pct)} {ladder.bond_symbol} / 0%{" "}
          {ladder.leveraged_symbol}
        </div>
        <div>
          <span className="muted">{t("paperDesk.ladder.confirmation")}</span>
          {t("paperDesk.ladder.confirmationValue", {
            signalSymbol: ladder.signal_symbol,
            sessions: ladder.confirm_ma_sessions,
          })}
        </div>
        <div>
          <span className="muted">{t("paperDesk.ladder.fundingOrder")}</span>
          {t("paperDesk.ladder.fundingOrderValue", {
            leveragedSymbol: ladder.leveraged_symbol,
            bondSymbol: ladder.bond_symbol,
            defensiveSymbol: ladder.defensive_symbol,
          })}
        </div>
        <div>
          <span className="muted">{t("paperDesk.ladder.recovery")}</span>
          {t("paperDesk.ladder.recoveryValue", {
            leveragedSymbol: ladder.leveraged_symbol,
            gainPct: formatFractionPctString(ladder.recovery_gain_pct),
            sessions: ladder.recovery_sessions,
          })}
        </div>
      </pre>
      <details className="desk-thesis-detail">
        <summary>{t("paperDesk.rules.thesis")}</summary>
        <p className="muted">{desk.thesis}</p>
      </details>
    </div>
  );
}

/**
 * The ladder's rung table, on its own so `DeskPanel` can render it as that card kind's
 * forward-looking block -- the same slot `UpcomingSignals` fills for a rules desk and `StagedOrders`
 * for an autopilot seat.
 *
 * It sits in the card body rather than inside the rules prose it used to follow because it is not
 * prose: a ladder card has no per-symbol entry rule to project forward, and which rung SPY's
 * drawdown currently sits on is the one thing that decides this desk's next weight. Exported (not
 * private to `DeskLadderDescription`) so there is exactly one of it -- rendering a second copy
 * inside the disclosure would state the same weights twice and let them drift apart.
 */
export function LadderRungs({ ladder }: { ladder: LadderDescription }) {
  const { t } = useT();
  return (
    <div className="desk-section desk-ladder-rungs-section">
      <table className="data-table desk-ladder-rungs-table">
        <caption className="muted desk-ladder-rungs-caption">
          {t("paperDesk.ladder.rungsCaption")}
        </caption>
        <thead>
          <tr>
            <th scope="col">{t("paperDesk.ladder.spyDrawdownHeader")}</th>
            <th scope="col" className="num">
              {t("paperDesk.ladder.leveragedTargetHeader", { symbol: ladder.leveraged_symbol })}
            </th>
          </tr>
        </thead>
        <tbody>
          {ladder.rungs.map((r) => (
            <tr key={r.drawdown_pct}>
              <td>{formatFractionPctString(r.drawdown_pct)}</td>
              <td className="num">{formatFractionPctString(r.leveraged_weight_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * `universe_source` in the reader's words, not the raw wire token. Open string, not a closed union --
 * see `exitReasonLabel`'s docstring in `api/paperdesk.ts` for the concrete incident (an unrecognised
 * `exit_reason` throwing out of render and taking down the whole Paper Desk page) this degrade-instead-
 * of-throw pattern exists to avoid. An unrecognised source renders as-is rather than crashing.
 */
function autopilotUniverseSourceLabel(source: string, t: Translator): string {
  if (source === "screen") return t("paperDesk.autopilot.universeSourceScreen");
  if (source === "card") return t("paperDesk.autopilot.universeSourceCard");
  return source;
}

/**
 * The `kind === "autopilot"` counterpart to `DeskRules`/`DeskLadderDescription`. An autopilot seat's
 * `entry`/`exit`/`position_pct`/`rank_by` are all `null` (see `Desk.autopilot`'s own docstring) --
 * `DeskRules` would print a rules block inventing rules this desk does not have, exactly the mistake
 * `DeskLadderDescription` already exists to avoid for a ladder card. This renders the seat's actual
 * provenance instead.
 */
function DeskAutopilotDescription({
  desk,
  autopilot,
}: {
  desk: Desk;
  autopilot: AutopilotDescription;
}) {
  const { t } = useT();
  return (
    <div className="desk-section desk-rules-section desk-autopilot-section">
      {/* Headed "Provenance", not "Rules". This desk has no rules -- no entry expression, no exit,
          no position sizing -- and heading the block "Rules" would be the exact mistake the ladder
          branch above exists to prevent: naming a section after something the card does not have,
          so a reader goes looking for the rule that produced a position and finds an empty line.
          What this desk has instead is a provenance: which arm, which universe, which card, and
          what the last run did. */}
      <h3>{t("paperDesk.autopilot.provenanceHeading")}</h3>
      <pre className="desk-rules-block">
        <div>
          <span className="muted">{t("paperDesk.autopilot.tradedSoFar")}</span>
          {/* Every symbol this book has ever ordered, not a fixed universe -- the screened selector
              picks a fresh shortlist each session, so there is no standing list to print. Empty is
              the ordinary state before the first order, and it is said in words rather than left as
              a blank line after a label, which reads as a rendering bug. */}
          {desk.universe.length > 0
            ? desk.universe.join(", ")
            : t("paperDesk.autopilot.tradedSoFarEmpty")}
        </div>
        <div>
          <span className="muted">{t("paperDesk.autopilot.bookLabel")}</span>
          {t("paperDesk.autopilot.bookValue", {
            arm: autopilot.arm,
            universeSource: autopilotUniverseSourceLabel(autopilot.universe_source, t),
          })}
        </div>
        <div>
          <span className="muted">{t("paperDesk.autopilot.currentCard")}</span>
          {autopilot.current_card_id}
        </div>
        <div>
          <span className="muted">{t("paperDesk.autopilot.cardAdopted")}</span>
          {autopilot.card_adopted_date}
          {/* Explicitly NOT the desk's own inception -- the inception picker above re-runs every
              other kind of card from a new date, but this seat's orders were judgements the regime
              call made on their own day and cannot be re-run from another one. For a book that has
              never switched cards, this date is simply this seat's own inception. The rest of the
              caveat (the picker won't move it; that day's orders can't rerun elsewhere) sits behind
              a hover -- the load-bearing fact stays inline. */}
          <span title={t("paperDesk.autopilot.cardAdoptedDetail")}>
            {t("paperDesk.autopilot.cardAdoptedSuffix")}
          </span>
        </div>
        <div>
          <span className="muted">{t("paperDesk.autopilot.orders")}</span>
          {t("paperDesk.autopilot.ordersValue", {
            total: autopilot.orders_total,
            filled: autopilot.orders_filled,
            pending: autopilot.orders_pending,
            rejected: autopilot.orders_rejected,
          })}
          {/* These four need not sum to orders_total: "cancelled" and "expired" are legal order
              statuses nothing sets today, so a reader must not compute one count from the others.
              That reason is a hover away; the "need not sum" fact itself stays inline. */}
          <span title={t("paperDesk.autopilot.ordersFootnoteDetail")}>
            {t("paperDesk.autopilot.ordersFootnote")}
          </span>
        </div>
        <div>
          <span className="muted">{t("paperDesk.autopilot.lastRun")}</span>
          {autopilot.last_run_id === null ? (
            t("paperDesk.autopilot.lastRunNone")
          ) : (
            <>
              {autopilot.last_run_id},{" "}
              {autopilot.last_run_state ?? t("paperDesk.autopilot.lastRunStateUnknown")},{" "}
              {autopilot.last_run_at !== null
                ? formatInstant(autopilot.last_run_at)
                : t("paperDesk.autopilot.lastRunTimeUnknown")}
              {autopilot.last_run_outcome ? ` -- ${autopilot.last_run_outcome}` : ""}
            </>
          )}
        </div>
        <div>
          <span className="muted">{t("paperDesk.autopilot.exits")}</span>
          {/* Open string, not a closed union -- see `exitReasonLabel`'s docstring in api/paperdesk.ts
              for the incident this degrade-instead-of-throw pattern exists to avoid. No `switch` here:
              an unrecognised value still renders (as itself) rather than throwing.

              "none" is stated in words rather than left as a bare token: this desk only ever buys, so
              nothing is ever sold and the selected card's own stop, target and hold-cap rules never
              touch these fills. Any other value is the backend's own sentence naming the rules
              actually in force -- rendered as-is and introduced as how this desk closes a position,
              never restated or re-derived here: the backend owns that wording, and a second copy of
              it on the client would drift the moment the card's rules changed. */}
          {autopilot.exits === "none"
            ? t("paperDesk.autopilot.exitsNoneValue")
            : t("paperDesk.autopilot.exitsOtherValue", { exits: autopilot.exits })}
        </div>
      </pre>
      <p className="muted desk-autopilot-run-link-line">
        <Link to="/agent-workflow" className="download-link desk-autopilot-run-link">
          {t("paperDesk.autopilot.runLink")}
        </Link>
      </p>
      <details className="desk-thesis-detail">
        <summary>{t("paperDesk.rules.thesis")}</summary>
        <p className="muted">{desk.thesis}</p>
      </details>
    </div>
  );
}
