/**
 * One influencer's cash-constrained paper book: a descriptive paper projection of the persona's
 * live bullish calls, run as a single paper account (starting cash, spend-per-call, sell on a
 * bearish/neutral flip or to fund a fresher call) -- the current-position counterpart to
 * `PersonaScorecard.tsx`'s backward-looking call record. Both sit under the same persona on
 * `/personas`, and this card's holdings table idiom is deliberately the Paper Desk's own
 * (`pages/paperdesk/DeskPanel.tsx`'s `HoldingsTable`/`HoldingRow`) -- same `.table-wrap > table.
 * data-table.position-table` markup, same `position-symbol`/`position-price-asof` cells, same
 * money helpers -- so a reader who already knows how to read a Paper Desk holdings table needs to
 * learn nothing new here.
 *
 * **Presentational only -- this component fetches nothing.** A caller (a personas books list, or
 * the Paper Desk) owns fetching `GET /api/personas/{slug}/book` (or the `/books` collection
 * endpoint) and passing the loaded `PersonaBook` in. That is why the prop is a plain loaded `book`,
 * not a fetch-state union.
 *
 * **Money and quantity fields are decimal strings, never numbers.** Every money/quantity field on
 * `PersonaBook`/`PersonaHolding`/`PersonaTrade` crosses the wire as a `DecimalString` -- see
 * `@/api/personas`'s docstrings. All of them are formatted through `@/api/paperdesk`'s money
 * helpers (`formatMoney`, `formatSignedMoney`, `moneyTone`, `formatSignedFractionPctString`,
 * `formatWeightPct`) rather than re-implemented here.
 *
 * **`return_pct` is a 0-1 FRACTION on the wire, never a whole percent.** `"0.0642"` means 6.42%.
 * This is the fix for the historical "+6427%" bug: that number came from treating an already-a-
 * percent value as a fraction and multiplying by 100 a second time. `formatSignedFractionPctString`
 * is the one place that math happens now; nothing in this file multiplies by 100 itself.
 *
 * **Three lists, three empty rules.** `holdings` (open positions) renders "No open positions" in
 * place of the table when empty, but the section itself always shows -- an influencer can be
 * followed with nothing currently open. `trades` (closed positions) and `skipped` (calls the book
 * saw but never opened) each hide their whole section when empty, since "no closed trades yet" is
 * the overwhelmingly common case for a young book and does not need a permanent empty row.
 *
 * **`warnings` (unpriceable symbols) always render**, independent of every other section -- the
 * same `.warning-list` treatment `PersonaScorecard.tsx` gives `PersonaScorecard.warnings`.
 *
 * **The paper-projection framing (`personaBook.caveat`) is always visible**, never behind a
 * disclosure -- this book is not a real position and not advice. The mechanical detail (replace-
 * the-stalest-position-when-full, no look-ahead pricing) sits one click away in an `InfoNote`.
 */
import { Link } from "react-router-dom";

import {
  formatMoney,
  formatSignedFractionPctString,
  formatSignedMoney,
  formatWeightPct,
  moneyTone,
} from "@/api/paperdesk";
import {
  stanceLabel,
  type PersonaBook,
  type PersonaHolding,
  type PersonaSkippedCall,
  type PersonaTrade,
} from "@/api/personas";
import { InfoNote } from "@/components/InfoNote";
import { ScrollRegion } from "@/components/ScrollPanel";
import { useT } from "@/i18n";
import type { MessageKey } from "@/i18n/catalog";

export interface PersonaBookCardProps {
  book: PersonaBook;
}

const TRADE_REASON_KEYS: Record<PersonaTrade["reason"], MessageKey> = {
  flip_bearish: "personaBook.trade.reason.flipBearish",
  flip_neutral: "personaBook.trade.reason.flipNeutral",
  replaced: "personaBook.trade.reason.replaced",
};

const SKIPPED_REASON_KEYS: Record<PersonaSkippedCall["reason"], MessageKey> = {
  no_cash: "personaBook.skipped.reason.noCash",
  no_market_data: "personaBook.skipped.reason.noMarketData",
  no_bar_since: "personaBook.skipped.reason.noBarSince",
};

export default function PersonaBookCard({ book }: PersonaBookCardProps) {
  const { t } = useT();
  const heading = t("personaBook.heading", { name: book.display_name });
  const unrealisedTone = moneyTone(book.unrealised_pnl_total);
  const realisedTone = moneyTone(book.realised_pnl_total);

  return (
    <div className="panel persona-book-card">
      <h3 className="persona-card-subhead">{heading}</h3>

      <InfoNote
        summary={t("personaBook.caveat", {
          startingCash: formatMoney(book.starting_cash),
          inception: book.inception,
          notional: formatMoney(book.notional_per_position),
        })}
        className="persona-book-caveat"
      >
        {t("personaBook.caveatDetail")}
      </InfoNote>

      <div className="tile-grid persona-book-tiles">
        <div className="stat tile">
          <span className="label" title={t("personaBook.equityInfo")}>
            {t("personaBook.equity")}
          </span>
          <span className="value">{formatMoney(book.equity)}</span>
        </div>
        <div className="stat tile">
          <span className="label" title={t("personaBook.cashInfo")}>
            {t("personaBook.cash")}
          </span>
          <span className="value">{formatMoney(book.cash)}</span>
        </div>
        <div className="stat tile">
          <span className="label" title={t("personaBook.unrealisedPnlInfo")}>
            {t("personaBook.unrealisedPnl")}
          </span>
          <span className={`value${unrealisedTone ? ` ${unrealisedTone}` : ""}`}>
            {formatSignedMoney(book.unrealised_pnl_total)}
          </span>
        </div>
        <div className="stat tile">
          <span className="label" title={t("personaBook.realisedPnlInfo")}>
            {t("personaBook.realisedPnl")}
          </span>
          <span className={`value${realisedTone ? ` ${realisedTone}` : ""}`}>
            {formatSignedMoney(book.realised_pnl_total)}
          </span>
        </div>
        <div className="stat tile">
          <span className="label" title={t("personaBook.returnInfo")}>
            {t("personaBook.returnPct")}
          </span>
          <span className="value">{formatSignedFractionPctString(book.return_pct, 2)}</span>
        </div>
      </div>

      {book.warnings.length > 0 && (
        <ul className="warning-list persona-book-warnings">
          {book.warnings.map((w, i) => (
            <li key={i}>{`${w.source}: ${w.reason}`}</li>
          ))}
        </ul>
      )}

      <details className="persona-book-section persona-book-holdings" open>
        <summary>{t("personaBook.holdingsHeading")}</summary>
        {book.holdings.length === 0 ? (
          <p className="muted persona-book-empty">{t("personaBook.empty")}</p>
        ) : (
          <ScrollRegion size="md" label={t("personaBook.holdingsHeading")}>
            <div className="table-wrap">
              <table className="data-table position-table persona-book-table">
                <thead>
                  <tr>
                    <th scope="col">{t("common.symbol")}</th>
                    <th scope="col" className="num">
                      {t("common.quantity")}
                    </th>
                    <th scope="col">{t("personaBook.entryDate")}</th>
                    <th scope="col" className="num">
                      {t("personaBook.entryPrice")}
                    </th>
                    <th scope="col" className="num">
                      {t("personaBook.lastPrice")}
                    </th>
                    <th scope="col" className="num">
                      {t("personaBook.marketValue")}
                    </th>
                    <th scope="col" className="num">
                      {t("personaBook.unrealisedPnl")}
                    </th>
                    <th scope="col" className="num">
                      {t("personaBook.returnPct")}
                    </th>
                    <th scope="col" className="num">
                      {t("common.weight")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {book.holdings.map((h) => (
                    <HoldingRow key={h.symbol} holding={h} />
                  ))}
                </tbody>
              </table>
            </div>
          </ScrollRegion>
        )}
      </details>

      {book.trades.length > 0 && (
        <details className="persona-book-section persona-book-trades">
          <summary>{t("personaBook.tradesHeading")}</summary>
          <ScrollRegion size="md" label={t("personaBook.tradesHeading")}>
            <div className="table-wrap">
              <table className="data-table position-table persona-book-table persona-book-trades-table">
                <thead>
                  <tr>
                    <th scope="col">{t("common.symbol")}</th>
                    <th scope="col">{t("personaBook.entryDate")}</th>
                    <th scope="col">{t("personaBook.exitDate")}</th>
                    <th scope="col" className="num">
                      {t("common.quantity")}
                    </th>
                    <th scope="col" className="num">
                      {t("personaBook.exitPrice")}
                    </th>
                    <th scope="col" className="num">
                      {t("personaBook.realisedPnl")}
                    </th>
                    <th scope="col" className="num">
                      {t("personaBook.returnPct")}
                    </th>
                    <th scope="col">{t("personaBook.reason")}</th>
                  </tr>
                </thead>
                <tbody>
                  {book.trades.map((trade, i) => (
                    <TradeRow key={`${trade.symbol}-${trade.note_id}-${i}`} trade={trade} />
                  ))}
                </tbody>
              </table>
            </div>
          </ScrollRegion>
        </details>
      )}

      {book.skipped.length > 0 && (
        <details className="persona-book-section persona-book-skipped">
          <summary>{t("personaBook.skippedHeading")}</summary>
          <ScrollRegion size="sm" label={t("personaBook.skippedHeading")}>
            <div className="table-wrap">
              <table className="data-table persona-book-table persona-book-skipped-table">
                <thead>
                  <tr>
                    <th scope="col">{t("common.symbol")}</th>
                    <th scope="col">{t("personaBook.saidOn")}</th>
                    <th scope="col">{t("personaBook.reason")}</th>
                  </tr>
                </thead>
                <tbody>
                  {book.skipped.map((s, i) => (
                    <tr key={`${s.symbol}-${s.said_on}-${i}`}>
                      <td className="position-symbol-cell">
                        <span className="position-symbol">{s.symbol}</span>
                      </td>
                      <td>{s.said_on}</td>
                      <td>{t(SKIPPED_REASON_KEYS[s.reason])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </ScrollRegion>
        </details>
      )}
    </div>
  );
}

function HoldingRow({ holding: h }: { holding: PersonaHolding }) {
  const { t } = useT();
  const tone = moneyTone(h.unrealised_pnl);
  return (
    <tr>
      <td className="position-symbol-cell">
        <Link className="persona-ticker-chip" to={`/symbol/${encodeURIComponent(h.symbol)}`}>
          <span className="position-symbol">{h.symbol}</span>
          <span className={`persona-ticker-stance persona-ticker-stance-${h.stance}`}>
            {stanceLabel(h.stance)}
          </span>
        </Link>
      </td>
      <td className="num">{h.quantity}</td>
      <td>{h.entry_date}</td>
      <td className="num">{formatMoney(h.entry_price)}</td>
      <td className="num">
        <div>{formatMoney(h.last_price)}</div>
        <div className="position-price-asof">{t("personaBook.asOfLower", { date: h.last_price_date })}</div>
      </td>
      <td className="num">{formatMoney(h.market_value)}</td>
      <td className="num">
        <span className={`position-unrealized-value ${tone}`}>{formatSignedMoney(h.unrealised_pnl)}</span>
      </td>
      <td className="num">{formatSignedFractionPctString(h.return_pct, 2)}</td>
      <td className="num">{formatWeightPct(h.weight, 2)}</td>
    </tr>
  );
}

function TradeRow({ trade }: { trade: PersonaTrade }) {
  const { t } = useT();
  const tone = moneyTone(trade.realised_pnl);
  return (
    <tr>
      <td className="position-symbol-cell">
        <Link className="persona-ticker-chip" to={`/symbol/${encodeURIComponent(trade.symbol)}`}>
          <span className="position-symbol">{trade.symbol}</span>
        </Link>
      </td>
      <td>{trade.entry_date}</td>
      <td>{trade.exit_date}</td>
      <td className="num">{trade.quantity}</td>
      <td className="num">{formatMoney(trade.exit_price)}</td>
      <td className="num">
        <span className={`position-unrealized-value ${tone}`}>{formatSignedMoney(trade.realised_pnl)}</span>
      </td>
      <td className="num">{formatSignedFractionPctString(trade.return_pct, 2)}</td>
      <td>{t(TRADE_REASON_KEYS[trade.reason])}</td>
    </tr>
  );
}
