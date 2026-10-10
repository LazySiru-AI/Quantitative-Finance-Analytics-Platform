/**
 * The Live Tape's pure derivation logic -- no React, no fetch, no `@/api/paperlive` -- split out of
 * `LiveTape.tsx` so the tagging/placement/action rules can be unit-tested independent of rendering,
 * and so the row shape they produce can grow past "which tags did this symbol earn" into "which book
 * earned each tag, and what buy/sell is actually happening at what price" without dragging the
 * component's render tree along for the ride.
 *
 * `DecimalString` is imported from `@/api/client` rather than `@/api/paperdesk` -- `paperdesk.ts`
 * itself only ever imports the alias locally and never re-exports it, so importing it from there
 * would not compile. `@/api/client` is the type's actual home; every other `DecimalString` consumer
 * in this codebase (including `paperdesk.ts`) resolves it the same way.
 */
import type { DecimalString } from "@/api/client";
import type { Book, PaperDeskState, Purpose, Signal } from "@/api/paperdesk";

/** Which of the three qualifying conditions a symbol met. A symbol can carry more than one -- it
 *  renders once, with every tag it earned, not once per tag. */
export type LiveTapeTag = "HELD" | "SIGNAL" | "TRADED";

export const TAG_ORDER: readonly LiveTapeTag[] = ["HELD", "SIGNAL", "TRADED"];

export const TAG_LABEL: Record<LiveTapeTag, string> = {
  HELD: "Held",
  SIGNAL: "Signal",
  TRADED: "Traded",
};

/** Display order for the three books a symbol's placements can belong to -- matches the order the
 *  rest of Paper Desk lists purposes in (`Book.purpose`), not whatever order `state.books` happens
 *  to arrive in on a given response. */
export const BOOK_ORDER: readonly Purpose[] = ["savings", "trading", "roth"];

/**
 * One (tag, book) pair a symbol earned, with every desk under that book that earned it.
 *
 * A symbol held in both the Trading and Roth books is one row on the tape, but "held in Trading" and
 * "held in Roth" are different facts about different pools of money -- collapsing them into a single
 * HELD tag the way `LiveTapeSymbol.tags` does (kept for backward compatibility below) would lose
 * which book a reader actually needs to look at. `placements` is the one field that keeps tag and
 * book together; `tags`/`deskNames` stay as flattened summaries across every book for whatever still
 * only wants "does this symbol carry this tag at all".
 */
export interface LiveTapePlacement {
  tag: LiveTapeTag;
  purpose: Purpose;
  /** `Book.label` verbatim, e.g. `"Savings"` / `"Trading"` / `"Roth IRA"` -- render this, never
   *  derive a label from `purpose` a second time. */
  bookLabel: string;
  /** `Desk.display_name` values under THIS book that earned THIS tag, deduped and sorted
   *  `localeCompare`. */
  deskNames: string[];
}

export type LiveTapeActionSide = "buy" | "sell";

/**
 * One buy or sell actually happening for a symbol, at a price, in a specific book/desk -- the
 * concrete "what's happening right now" fact a tag alone does not carry. A SIGNAL tag says a rule
 * fired or was blocked; an action says which direction and at what price, and where a fill exists,
 * exactly what price the desk would really pay after slippage.
 */
export interface LiveTapeAction {
  side: LiveTapeActionSide;
  /** `null` for a signal-sourced action whose `Signal.last_close` is itself `null` -- a symbol with
   *  no price at the decision session. Never coerced to `0`; render `—` instead, same rule as every
   *  other money field in `@/api/paperdesk`. */
  price: DecimalString | null;
  /** `null` for every signal-sourced action -- a signal carries no size, only a fill does. */
  quantity: DecimalString | null;
  purpose: Purpose;
  bookLabel: string;
  deskName: string;
  /** `"fill"` when this action came from `Desk.live_fills` (a real live-priced execution); `"signal"`
   *  when it was inferred from a raised `Signal`'s `entry_fires`/`exit_fires`. A fill is always the
   *  more precise statement of the same event and, per `deriveLiveTapeSymbols`'s dedupe rule below,
   *  suppresses the matching signal-sourced action rather than showing both. */
  source: "fill" | "signal";
}

/** One row of the tape: a deduped symbol, every tag it earned, every desk (by display name) that put
 *  it on the tape, which books it appears in, the full (tag, book) placement detail, and every
 *  buy/sell action currently happening for it. */
export interface LiveTapeSymbol {
  symbol: string;
  /** Deduped, in `TAG_ORDER` -- unchanged from before `placements` existed: a symbol held in two
   *  books still shows one HELD badge here, not two. */
  tags: LiveTapeTag[];
  /** Every desk across all books that touched this symbol, deduped and `localeCompare`-sorted --
   *  unchanged from before `placements` existed. */
  deskNames: string[];
  /** Books this symbol appears in, in `BOOK_ORDER`. */
  purposes: Purpose[];
  /** Sorted by `TAG_ORDER`, then `BOOK_ORDER`. */
  placements: LiveTapePlacement[];
  /** Sorted sells-before-buys, then fill-before-signal, then `deskName.localeCompare`. */
  actions: LiveTapeAction[];
}

/** A signal counts as "raised" for the tape's purposes when its entry or exit rule actually fires,
 *  or when it was blocked from firing -- `Signal.blocked` (`"book full" | "insufficient cash" |
 *  "no price" | string`, see `@/api/paperdesk`) is non-`null` exactly when something about this
 *  session's decision for this symbol is worth a reader's attention, even though `entry_fires`/
 *  `exit_fires` are both `false` in that case. A signal that neither fires nor is blocked is the
 *  ordinary, uninteresting case -- entry quiet, nothing to report -- and does not belong on a tape
 *  meant to show only what is currently in play. */
export function signalIsRaised(signal: Signal): boolean {
  return signal.entry_fires || signal.exit_fires || signal.blocked != null;
}

/** The most recent session any trade in this state actually closed on, or `null` if no book has a
 *  single closed trade. Read from `Trade.exit_date` across every desk in every book -- the state
 *  carries no single "last session" field for trades the way it does for the mark (`as_of`), so this
 *  is derived from the data actually present, per the task's own phrasing ("the most recent session
 *  date present in the state"). */
function mostRecentTradeSession(state: PaperDeskState): string | null {
  let latest: string | null = null;
  for (const book of state.books) {
    for (const desk of book.desks) {
      for (const trade of desk.trades) {
        if (latest === null || trade.exit_date > latest) latest = trade.exit_date;
      }
    }
  }
  return latest;
}

/** Accumulator kept per symbol while walking the state once -- flattened into the public
 *  `LiveTapeSymbol` shape only at the end, once every desk/book has had a chance to contribute. */
interface SymbolAccumulator {
  tags: Set<LiveTapeTag>;
  desks: Set<string>;
  /** Keyed `${tag}:${purpose}` -- the same (symbol, tag, purpose) triple never needs two entries,
   *  even when two different desks in the same book both earn it. */
  placements: Map<string, { tag: LiveTapeTag; purpose: Purpose; bookLabel: string; deskNames: Set<string> }>;
  actions: LiveTapeAction[];
}

function placementKey(tag: LiveTapeTag, purpose: Purpose): string {
  return `${tag}:${purpose}`;
}

/** `${deskName}:${side}` -- the triple the dedupe rule keys on. Symbol is kept as the outer map key
 *  rather than folded into this string so the fill-side lookup during signal processing stays a
 *  simple two-step `Map.get` instead of string-concatenating three fields and hoping none of them
 *  contain the separator. */
function deskSideKey(deskName: string, side: LiveTapeActionSide): string {
  return `${deskName}:${side}`;
}

const SIDE_ORDER: Record<LiveTapeActionSide, number> = { sell: 0, buy: 1 };
const SOURCE_ORDER: Record<LiveTapeAction["source"], number> = { fill: 0, signal: 1 };

/**
 * Derives the live tape's row set from an already-loaded `PaperDeskState` -- no fetch of its own,
 * per the task fence. Walks every desk in every book and tags a symbol the moment any one of the
 * three conditions is met:
 *
 * - held right now (`Holding.symbol`)
 * - a signal fired or was blocked this session (`signalIsRaised` above)
 * - traded in the most recent session any book has a closed trade for (`mostRecentTradeSession`)
 *
 * Each mark also records the owning `Book.purpose`/`Book.label`, producing one `LiveTapePlacement`
 * per distinct (symbol, tag, purpose) -- a symbol held in two books earns two placements, not one
 * placement with two books folded into it, so a reader can see at a glance which pool of money is
 * doing what. `tags`/`deskNames` stay flattened across every book, unchanged from the pre-placement
 * shape, so nothing that only wanted the coarse "does X qualify" question regresses.
 *
 * Then, separately, walks every desk's `live_fills` and raised `signals` again to build `actions`:
 *
 * - a fill's `side` is normalised with `.trim().toLowerCase()`; `"sell"`/`"buy"` become the action's
 *   side, and any other value is *skipped*, never guessed at and never thrown on. `LiveFill.side` is
 *   an open string on the wire (see its docstring in `@/api/paperdesk`, which points at
 *   `exitReasonLabel`'s docstring for the concrete failure a closed union over server-supplied data
 *   already caused on this exact page) -- a switch that throws on an unrecognised side would take
 *   the whole tape, and the page around it, down over one value the server sent that this build
 *   hadn't seen yet.
 * - a raised signal emits a `"sell"` action when `exit_fires`, a `"buy"` action when `entry_fires`
 *   (both may fire), priced from `Signal.last_close` (which may itself be `null`) with `quantity:
 *   null` -- a signal carries no size. A signal that is *only* blocked (raised, but neither fires)
 *   earns its SIGNAL placement and nothing else: inventing a buy/sell line for an order the book
 *   explicitly did not place would misreport what is actually happening.
 * - if a fill action already exists for the same `(symbol, deskName, side)`, the matching
 *   signal-sourced action is dropped -- the fill is the more precise statement of the same event, so
 *   showing both would double-report one execution.
 *
 * Rows are sorted by `symbol.localeCompare`, unchanged from before. Within a row, `placements` sorts
 * by `TAG_ORDER` then `BOOK_ORDER`, and `actions` sorts sells-before-buys, then fill-before-signal,
 * then `deskName.localeCompare`.
 */
export function deriveLiveTapeSymbols(state: PaperDeskState): LiveTapeSymbol[] {
  const bySymbol = new Map<string, SymbolAccumulator>();

  const entryFor = (symbol: string): SymbolAccumulator => {
    let entry = bySymbol.get(symbol);
    if (!entry) {
      entry = { tags: new Set(), desks: new Set(), placements: new Map(), actions: [] };
      bySymbol.set(symbol, entry);
    }
    return entry;
  };

  const mark = (symbol: string, tag: LiveTapeTag, book: Book, deskName: string) => {
    const entry = entryFor(symbol);
    entry.tags.add(tag);
    entry.desks.add(deskName);
    const key = placementKey(tag, book.purpose);
    let placement = entry.placements.get(key);
    if (!placement) {
      placement = { tag, purpose: book.purpose, bookLabel: book.label, deskNames: new Set() };
      entry.placements.set(key, placement);
    }
    placement.deskNames.add(deskName);
  };

  for (const book of state.books) {
    for (const desk of book.desks) {
      for (const holding of desk.holdings) mark(holding.symbol, "HELD", book, desk.display_name);
      for (const signal of desk.signals) {
        if (signalIsRaised(signal)) mark(signal.symbol, "SIGNAL", book, desk.display_name);
      }
    }
  }

  const latestSession = mostRecentTradeSession(state);
  if (latestSession !== null) {
    for (const book of state.books) {
      for (const desk of book.desks) {
        for (const trade of desk.trades) {
          if (trade.exit_date === latestSession) mark(trade.symbol, "TRADED", book, desk.display_name);
        }
      }
    }
  }

  // Fills first: `fillSides` records every (symbol, deskName, side) a fill already covers, so the
  // signal pass below can drop its half of the dedupe without caring about map iteration order.
  const fillSides = new Map<string, Set<string>>();

  for (const book of state.books) {
    for (const desk of book.desks) {
      for (const fill of desk.live_fills) {
        const side = fill.side.trim().toLowerCase();
        if (side !== "buy" && side !== "sell") continue; // unrecognised side -- skip, never guess

        const entry = entryFor(fill.symbol);
        entry.actions.push({
          side,
          price: fill.price,
          quantity: fill.quantity,
          purpose: book.purpose,
          bookLabel: book.label,
          deskName: desk.display_name,
          source: "fill",
        });

        let sides = fillSides.get(fill.symbol);
        if (!sides) {
          sides = new Set();
          fillSides.set(fill.symbol, sides);
        }
        sides.add(deskSideKey(desk.display_name, side));
      }
    }
  }

  for (const book of state.books) {
    for (const desk of book.desks) {
      for (const signal of desk.signals) {
        if (!signalIsRaised(signal)) continue;

        const sides: LiveTapeActionSide[] = [];
        if (signal.exit_fires) sides.push("sell");
        if (signal.entry_fires) sides.push("buy");
        if (sides.length === 0) continue; // blocked-only -- placement already recorded, no action

        const entry = entryFor(signal.symbol);
        const alreadyFilled = fillSides.get(signal.symbol);
        for (const side of sides) {
          if (alreadyFilled?.has(deskSideKey(desk.display_name, side))) continue;
          entry.actions.push({
            side,
            price: signal.last_close,
            quantity: null,
            purpose: book.purpose,
            bookLabel: book.label,
            deskName: desk.display_name,
            source: "signal",
          });
        }
      }
    }
  }

  return Array.from(bySymbol.entries())
    .map(([symbol, entry]) => {
      const placements = Array.from(entry.placements.values())
        .map((p) => ({
          tag: p.tag,
          purpose: p.purpose,
          bookLabel: p.bookLabel,
          deskNames: Array.from(p.deskNames).sort((a, b) => a.localeCompare(b)),
        }))
        .sort((a, b) => {
          const tagDiff = TAG_ORDER.indexOf(a.tag) - TAG_ORDER.indexOf(b.tag);
          if (tagDiff !== 0) return tagDiff;
          return BOOK_ORDER.indexOf(a.purpose) - BOOK_ORDER.indexOf(b.purpose);
        });

      const purposes = BOOK_ORDER.filter((p) => placements.some((placement) => placement.purpose === p));

      const actions = [...entry.actions].sort((a, b) => {
        const sideDiff = SIDE_ORDER[a.side] - SIDE_ORDER[b.side];
        if (sideDiff !== 0) return sideDiff;
        const sourceDiff = SOURCE_ORDER[a.source] - SOURCE_ORDER[b.source];
        if (sourceDiff !== 0) return sourceDiff;
        return a.deskName.localeCompare(b.deskName);
      });

      return {
        symbol,
        tags: TAG_ORDER.filter((tag) => entry.tags.has(tag)),
        deskNames: Array.from(entry.desks).sort((a, b) => a.localeCompare(b)),
        purposes,
        placements,
        actions,
      };
    })
    .sort((a, b) => a.symbol.localeCompare(b.symbol));
}

/**
 * Filters an already-derived row set down to the tags/books a reader has selected, for whatever UI
 * renders account and tag filter controls above the tape.
 *
 * A row survives when it has at least one placement whose tag is in `tags` AND whose purpose is in
 * `purposes` -- both conditions on the *same* placement, not "the row has a matching tag somewhere
 * and a matching purpose somewhere else". A symbol HELD only in Savings and SIGNAL only in Trading,
 * filtered to `{tags: {SIGNAL}, purposes: {savings}}`, has no placement satisfying both at once and
 * correctly disappears -- it is not actually signalling in the Savings book a reader asked about.
 *
 * Either set empty means nothing is selected, which admits no placement and returns `[]` -- not "no
 * filter applied". Rows are returned unmodified (their `placements` array still carries every
 * placement, matching or not) and in input order; this function only decides which rows survive, not
 * what a surviving row's own fields say.
 */
export function filterLiveTapeSymbols(
  rows: LiveTapeSymbol[],
  tags: ReadonlySet<LiveTapeTag>,
  purposes: ReadonlySet<Purpose>,
): LiveTapeSymbol[] {
  return rows.filter((row) => row.placements.some((p) => tags.has(p.tag) && purposes.has(p.purpose)));
}
