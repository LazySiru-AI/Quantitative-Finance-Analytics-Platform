import { useEffect, useMemo, useState } from "react";

import { describeError } from "@/api/client";
import {
  formatMoneyOrDash,
  formatSignedMoney,
  moneyTone,
  type PaperDeskState,
  type Purpose,
} from "@/api/paperdesk";
import {
  subscribe,
  type PaperLiveQuote,
  type PaperLiveQuotes,
} from "@/api/paperlive";
import { ScrollRegion } from "@/components/ScrollPanel";
import { useT, type MessageKey } from "@/i18n";
import {
  BOOK_ORDER,
  TAG_ORDER,
  deriveLiveTapeSymbols,
  filterLiveTapeSymbols,
  type LiveTapeSymbol,
  type LiveTapeTag,
} from "./liveTapeModel";

import "./LiveTape.css";

/** Maps each tag to its catalog key. Kept here rather than in `liveTapeModel.ts` -- that module
 *  still exports the plain-English `TAG_LABEL` unchanged (its own test only asserts it is a
 *  string, and other code may still reference it by name), but nothing in this file renders from
 *  it: every render of a tag badge below goes through `useT()`'s bound `t`, so a language switch
 *  repaints it. */
const TAG_MESSAGE_KEY: Record<LiveTapeTag, MessageKey> = {
  HELD: "desk.tape.tagHeld",
  SIGNAL: "desk.tape.tagSignal",
  TRADED: "desk.tape.tagTraded",
};

/**
 * The Live Tape: a prominent, always-at-the-top panel showing only symbols currently in play --
 * held, signalling, or traded last session -- with prices streaming in over `subscribe` (SSE,
 * degrading to polling; see `@/api/paperlive`'s module docstring). Everything about *which* symbols
 * qualify is derived client-side from the `PaperDeskState` the page already loaded
 * (`deriveLiveTapeSymbols`, in `./liveTapeModel`); this component fetches nothing from
 * `/api/paperdesk/*` itself and only ever talks to `/api/paperlive/*` for prices.
 *
 * Deliberately silent about the rest of the page's book/desk-visibility filtering -- the tape is a
 * cross-desk, cross-book view of everything currently in play, not scoped to whichever book tab is
 * selected below it. A symbol a hidden desk holds is still genuinely held right now, and hiding it
 * here because its desk panel happens to be collapsed would defeat the point of a tape meant to
 * answer "what's actually in play" at a glance.
 *
 * The account and status checkbox filters below are a *separate* thing from that book-visibility
 * filtering: they are the tape's own, reader-driven view controls, live only in this component's
 * state, and narrow which rows/badges/actions render -- they never change which desks the rest of
 * the page shows.
 *
 * **Defaults (owner decision, 2026-09-09): account = Trading only, status = Held + Signal.** The
 * trading book is the one whose tape a reader actually watches intraday -- savings and Roth are
 * long-horizon books that rebalance on a band or a monthly signal, and their rows were crowding out
 * the trading names -- and "Traded" is a same-session historical fact, not something in play, so it
 * is off until asked for. `DEFAULT_TAGS` and `defaultPurposes` below are the single place both live;
 * every checkbox is still one click from any other view. If the trading book is absent from the
 * state (a deployment with no trading roster), the account default falls back to every book present,
 * because a filter that starts by hiding everything is a bug, not a default.
 */

/** Status tags checked at first render -- see the component docstring for why `TRADED` is not. */
export const DEFAULT_TAGS: readonly LiveTapeTag[] = ["HELD", "SIGNAL"];

/** Account purposes checked at first render: the trading book alone when it is present, otherwise
 *  every book in `books` (never an empty selection). */
export function defaultPurposes(books: readonly { purpose: Purpose }[]): Set<Purpose> {
  const purposes = books.map((b) => b.purpose);
  return new Set(purposes.includes("trading") ? ["trading" as Purpose] : purposes);
}

export default function LiveTape({ state }: { state: PaperDeskState }) {
  const { t } = useT();
  const rows = useMemo(() => deriveLiveTapeSymbols(state), [state]);

  // Books actually present, in the house display order -- a book with no desks yet still funds a
  // purpose (see `Book`'s docstring in `@/api/paperdesk`) and its symbols, if any reach the tape via
  // another book, should still be filterable, so this is driven by `state.books`, not by which
  // purposes happen to appear in `rows`.
  const availableBooks = useMemo(
    () =>
      BOOK_ORDER.filter((purpose) => state.books.some((b) => b.purpose === purpose)).map(
        (purpose) => state.books.find((b) => b.purpose === purpose)!,
      ),
    [state.books],
  );
  const availableBooksKey = availableBooks.map((b) => b.purpose).join(",");

  const [selectedPurposes, setSelectedPurposes] = useState<Set<Purpose>>(() =>
    defaultPurposes(availableBooks),
  );
  const [selectedTags, setSelectedTags] = useState<Set<LiveTapeTag>>(() => new Set(DEFAULT_TAGS));

  // Reset to the default selection whenever the set of available books changes -- a book appearing
  // or disappearing (funding added, server restarted with a different roster) must never leave a
  // stale selection that silently hides every row on a purpose the reader never chose to hide.
  useEffect(() => {
    setSelectedPurposes(defaultPurposes(availableBooks));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availableBooksKey]);

  const togglePurpose = (purpose: Purpose) => {
    setSelectedPurposes((prev) => {
      const next = new Set(prev);
      if (next.has(purpose)) next.delete(purpose);
      else next.add(purpose);
      return next;
    });
  };

  const toggleTag = (tag: LiveTapeTag) => {
    setSelectedTags((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      return next;
    });
  };

  const filteredRows = useMemo(
    () => filterLiveTapeSymbols(rows, selectedTags, selectedPurposes),
    [rows, selectedTags, selectedPurposes],
  );

  // Subscribe to live quotes for the *filtered* symbol set, not the full one -- a row nobody can see
  // behind the current account/status filters has no business holding open a streaming subscription.
  const symbols = useMemo(() => filteredRows.map((r) => r.symbol), [filteredRows]);
  const symbolsKey = symbols.join(",");

  const [snapshot, setSnapshot] = useState<PaperLiveQuotes | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);

  useEffect(() => {
    setSnapshot(null);
    setStreamError(null);
    if (symbols.length === 0) return;
    const unsubscribe = subscribe(
      symbols,
      (data) => {
        setSnapshot(data);
        setStreamError(null);
      },
      (err: unknown) => {
        setStreamError(describeError(err, t("desk.tape.pricesUnavailable")));
      },
    );
    return unsubscribe;
    // `symbols` is recomputed every render from `symbolsKey`'s own inputs; re-subscribing on the
    // key (a stable string) rather than the array (a new reference every render) is what keeps this
    // from tearing down and reopening the stream on every unrelated re-render of the page above it.
    // `t` is intentionally omitted too: it is stable only within a render, and re-subscribing on a
    // language change is unnecessary -- the fallback string is read fresh from the store the next
    // time an error actually occurs, not baked into the closure at subscribe time in any way that
    // matters here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbolsKey]);

  const quoteBySymbol = useMemo(() => {
    const map = new Map<string, PaperLiveQuote>();
    for (const q of snapshot?.quotes ?? []) map.set(q.symbol, q);
    return map;
  }, [snapshot]);

  const errorBySymbol = useMemo(() => {
    const map = new Map<string, string>();
    for (const e of snapshot?.errors ?? []) map.set(e.symbol, e.message);
    return map;
  }, [snapshot]);

  return (
    <section className="panel live-tape-panel" aria-label={t("desk.tape.sectionAriaLabel")}>
      <div className="live-tape-head">
        <h2 className="live-tape-title">{t("desk.tape.title")}</h2>
        {snapshot && (
          <div className="live-tape-status">
            <span className="badge live-tape-state-badge">{snapshot.market_state}</span>
            <span className="muted live-tape-transport">{t("desk.tape.viaTransport", { transport: snapshot.transport })}</span>
            <span className="muted live-tape-asof">{t("desk.tape.asOfLower", { date: snapshot.as_of })}</span>
          </div>
        )}
      </div>

      <p className="muted live-tape-note">{t("desk.tape.subtitle")}</p>

      <div className="live-tape-filters">
        <fieldset className="live-tape-filter-group">
          <legend>{t("desk.tape.accountsLegend")}</legend>
          {availableBooks.map((book) => (
            <label key={book.purpose} className="live-tape-filter-item">
              <input
                type="checkbox"
                checked={selectedPurposes.has(book.purpose)}
                onChange={() => togglePurpose(book.purpose)}
              />
              {book.label}
            </label>
          ))}
        </fieldset>
        <fieldset className="live-tape-filter-group">
          <legend>{t("common.status")}</legend>
          {TAG_ORDER.map((tag) => (
            <label key={tag} className="live-tape-filter-item">
              <input
                type="checkbox"
                checked={selectedTags.has(tag)}
                onChange={() => toggleTag(tag)}
              />
              {t(TAG_MESSAGE_KEY[tag])}
            </label>
          ))}
        </fieldset>
      </div>

      {snapshot && !snapshot.healthy && (
        <div className="callout callout-warn live-tape-unhealthy" role="alert">
          {t("desk.tape.unhealthy")}
        </div>
      )}

      {streamError && (
        <div className="callout callout-warn live-tape-stream-error" role="alert">
          {streamError}
        </div>
      )}

      {rows.length === 0 ? (
        <div className="placeholder">{t("desk.tape.emptyAll")}</div>
      ) : filteredRows.length === 0 ? (
        <div className="placeholder live-tape-filtered-empty">{t("desk.tape.emptyFiltered")}</div>
      ) : (
        <ScrollRegion size="md" label={t("desk.tape.title")}>
          <div className="live-tape-grid">
            {filteredRows.map((row) => (
              <LiveTapeRow
                key={row.symbol}
                row={row}
                selectedTags={selectedTags}
                selectedPurposes={selectedPurposes}
                quote={quoteBySymbol.get(row.symbol)}
                error={errorBySymbol.get(row.symbol)}
              />
            ))}
          </div>
        </ScrollRegion>
      )}
    </section>
  );
}

function LiveTapeRow({
  row,
  selectedTags,
  selectedPurposes,
  quote,
  error,
}: {
  row: LiveTapeSymbol;
  selectedTags: ReadonlySet<LiveTapeTag>;
  selectedPurposes: ReadonlySet<Purpose>;
  quote: PaperLiveQuote | undefined;
  error: string | undefined;
}) {
  const { t } = useT();
  const tone = quote ? moneyTone(quote.change) : "";

  // Only placements surviving the current filter -- a row admitted because one of its placements
  // passed (tag selected AND purpose selected) should not still display badges for placements the
  // reader just switched off via the other axis.
  const visiblePlacements = row.placements.filter(
    (p) => selectedTags.has(p.tag) && selectedPurposes.has(p.purpose),
  );
  const visibleActions = row.actions.filter((a) => selectedPurposes.has(a.purpose));

  return (
    <div className="live-tape-row">
      <div className="live-tape-row-head">
        <span className="position-symbol live-tape-symbol">{row.symbol}</span>
        <span className="live-tape-tags">
          {visiblePlacements.map((p) => (
            <span
              key={`${p.tag}-${p.purpose}`}
              className={`badge live-tape-tag live-tape-tag-${p.tag.toLowerCase()}`}
              title={p.deskNames.join(", ")}
            >
              {t(TAG_MESSAGE_KEY[p.tag])}
              <span className="live-tape-tag-book"> · {p.bookLabel}</span>
            </span>
          ))}
        </span>
      </div>
      <div className="muted live-tape-desks" title={row.deskNames.join(", ")}>
        {row.deskNames.join(", ")}
      </div>
      {visibleActions.length > 0 && (
        <div className="live-tape-actions">
          {visibleActions.map((a) => {
            const priceText = formatMoneyOrDash(a.price);
            const hasQty = a.quantity != null;
            const actionKey: MessageKey =
              a.side === "sell"
                ? hasQty
                  ? "desk.tape.sellWithQty"
                  : "desk.tape.sellNoQty"
                : hasQty
                  ? "desk.tape.buyWithQty"
                  : "desk.tape.buyNoQty";
            const title =
              a.source === "signal"
                ? t("desk.tape.actionTitleSignal", { deskName: a.deskName, bookLabel: a.bookLabel })
                : t("desk.tape.actionTitle", { deskName: a.deskName, bookLabel: a.bookLabel });
            return (
              <span
                key={`${a.source}-${a.side}-${a.purpose}-${a.deskName}`}
                className={`live-tape-action live-tape-action-${a.side}`}
                title={title}
              >
                {t(actionKey, { price: priceText, qty: a.quantity ?? "" })}
              </span>
            );
          })}
        </div>
      )}
      {quote ? (
        <div className="live-tape-price-block">
          <span className="live-tape-price">{quote.price}</span>
          <span className={`live-tape-change ${tone}`}>
            {formatSignedMoney(quote.change)} ({quote.change_pct}%)
          </span>
          {quote.stale && (
            <span className="badge live-tape-stale-badge" title={t("desk.tape.staleTitle", { ts: quote.ts })}>
              {t("desk.tape.staleBadge")}
            </span>
          )}
          <span className="muted live-tape-source">{quote.source}</span>
        </div>
      ) : error ? (
        <div className="live-tape-price-block">
          <span className="muted live-tape-quote-error">{error}</span>
        </div>
      ) : (
        <div className="live-tape-price-block">
          <span className="muted live-tape-quote-pending">{t("desk.tape.noQuoteYet")}</span>
        </div>
      )}
    </div>
  );
}
