"""A persona's paper book -- Phase 6 of `docs/INFLUENCER-CONTRACT.md`.

**The question this module answers:** if you had started with $100,000 in cash and traded every dated
call an influencer made since inception -- buying $10,000 of a symbol the moment they turned bullish on
it, selling it the moment they turned bearish or neutral, and, when cash ran short, closing the
longest-held name to fund a fresh buy -- what would that paper book hold, have realised, and be worth
today? It is a cash-constrained trading REPLAY over the persona's whole dated history, not a snapshot of
"everything currently bullish": a symbol can be bought and later sold within the same book, and a book
can run out of cash and skip a call outright. It is descriptive, never predictive, and explicitly not
advice or a real position. See `docs/INFLUENCER-CONTRACT.md`, "Phase 6 -- persona paper book on the
Paper Desk (pinned)", for the exact wire contract this module implements -- the semantics below restate
it, they do not vary it.

**Every dated mention is an event, processed in chronological order.** Unlike the module's previous
"latest stance wins" snapshot, this replay walks every mention across every note, oldest `said_on`
first, and reacts to each one as if it happened live: a fresh bullish name is bought (cash permitting), a
name already held is simply re-affirmed (its `last_bullish_on` is bumped, no new trade), and a flip to
bearish or neutral closes the position and realises its P&L. `intraday`-horizon calls and `unclear`
stances are no-ops throughout -- a scalp is not a holding to carry forward, and an unclear stance is not
a signal to act on either direction.

**No-look-ahead entry AND exit, identical in spirit to `app.personas.scoring`.** A call is dated by
`said_on = note.published or note.ingested_at`. Every fill -- buy or sell -- happens at the first daily
close on or after that date, never an earlier one: reaching backward would silently look ahead of what
the influencer actually reacted to.

**Cash discipline and a hard position cap, not a fabricated unlimited book.** The replay starts with
`STARTING_CASH_USD` and never goes negative, and holds at most `MAX_OPEN_POSITIONS` names at once. A
fresh buy needs `DEFAULT_NOTIONAL_USD` in cash AND a free slot; when the book is full or cash is
short, it closes its longest-held position(s) first ("replace the stalest") to make room, and only
skips the call outright (`PersonaSkippedCall(reason="no_cash")`) once every open position has been
closed and cash still falls short. Because a full book must sell to buy, gains can never carry it past
the cap -- it is bounded by count, not only by cash.

**Exclude-and-warn, never a fabricated zero.** A symbol whose series cannot be fetched at all
(`ProviderError`, with nothing stored to fall back on -- `ensure_series` only raises when the store is
otherwise empty), or whose fetch comes back with zero bars, is unpriceable: any call on it is recorded as
a `PersonaSkippedCall(reason="no_market_data")` and the symbol is named once in `warnings` with
`reason="no market data"` -- never counted as a zero-value holding or a phantom fill. A call with bars
available but none on or after its date is `PersonaSkippedCall(reason="no_bar_since")` instead -- no
session has settled since the call was made yet.

**Money math is `Decimal` throughout**, matching the wire types (`Money`/`Quantity` from
`app.core.models`) and the ledger-wide "no binary floats in money" rule (`app.core.money`'s module
docstring). Bar prices arrive as market-space `float` (`app.market.models.Bar`); they are converted via
`Decimal(str(...))` at the boundary, never via `Decimal(float)`, which would carry the binary float's
own rounding error into the position's basis.

**`return_pct` is a fraction, not a percent.** Every `return_pct` this module emits -- on a holding, a
trade, or the book total -- is a 0-1 fraction (`Decimal("0.1523")` for a 15.23% gain), quantised to four
places. The frontend multiplies by 100 for display; emitting a pre-multiplied percent here duplicated
that scaling and produced numbers like "+6427%" for an ordinary gain.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Final, Literal

from app.config import Settings
from app.core.money import quantize_money
from app.db.duck import Interval
from app.market.models import Bar
from app.market.providers.base import ProviderError
from app.market.store import ensure_series  # patched as `paperbook.ensure_series` in tests
from app.personas.models import (
    DigestWarning,
    EpisodicNote,
    Persona,
    PersonaBook,
    PersonaHolding,
    PersonaSkippedCall,
    PersonaTrade,
    Stance,
)

__all__ = [
    "DEFAULT_INCEPTION",
    "DEFAULT_NOTIONAL_USD",
    "MAX_OPEN_POSITIONS",
    "STARTING_CASH_USD",
    "build_persona_book",
]

_log = logging.getLogger(__name__)

#: Calls dated before this are ignored entirely -- pinned by the contract, not a per-persona choice.
DEFAULT_INCEPTION: Final[dt.date] = dt.date(2026, 1, 1)

#: The dollar size of every fresh buy in the replay. Pinned by the contract; kept under its original
#: name even though the book is no longer "equal notional forever" (a position can now be closed and
#: replaced) because every fresh entry is still sized to exactly this.
DEFAULT_NOTIONAL_USD: Final[Decimal] = Decimal("10000")

#: The replay's starting cash. Referenced as a module global (never captured in a default-argument
#: value) so a test can monkeypatch `paperbook.STARTING_CASH_USD` to exercise cash-exhaustion paths
#: (a "no cash, no holdings" skip, `replace_stalest`) without simulating ten real buys first.
STARTING_CASH_USD: Final[Decimal] = Decimal("100000")

#: Hard ceiling on how many positions the book may hold open at once ($100,000 / $10,000). The book is
#: capped by COUNT, not only by cash: a fresh bullish call when the book is already full closes the
#: stalest position(s) to make room ("replace the stalest"), the same mechanism a cash shortfall
#: triggers, so a profitable book can never drift past ten names on paper gains alone. A module global
#: (like `STARTING_CASH_USD`) so a test can monkeypatch a smaller cap without simulating ten real buys.
MAX_OPEN_POSITIONS: Final[int] = 10

#: Quantity precision. Fractional shares are pervasive in this codebase's money handling
#: (`app.core.models.Quantity`'s own docstring), and a paper entry price is rarely a round number, so
#: six places keeps `quantity * entry_price` close enough to `notional_per_position` to be reported as
#: the same cost basis after rounding, without pretending to a precision no real broker offers either.
_QTY_QUANT: Final[Decimal] = Decimal("0.000001")

#: `return_pct` reporting precision -- four places, a 0-1 FRACTION (see the module docstring's note on
#: the percent-vs-fraction bug this rewrite fixes).
_RETURN_QUANT: Final[Decimal] = Decimal("0.0001")

#: Why a `PersonaTrade` was closed -- mirrors `PersonaTrade.reason`'s own `Literal`, kept as a module
#: type alias so `_realise` and its callers can be typed without a `# type: ignore` at the boundary.
_TradeReason = Literal["flip_bearish", "flip_neutral", "replaced"]


def _warn(warnings: list[DigestWarning], seen: set[tuple[str, str]], *, source: str, reason: str) -> None:
    """Append a `DigestWarning`, deduplicated on `(source, reason)` -- identical to the helper
    `app.personas.scoring` and `app.personas.backtest` each carry. Without dedup, a persona whose
    provider call fails would print the same complaint once per call that ever named the symbol rather
    than once per distinct cause."""
    key = (source, reason)
    if key in seen:
        return
    seen.add(key)
    warnings.append(DigestWarning(source=source, reason=reason))


def _said_on(note: EpisodicNote) -> dt.datetime:
    """`note.published` when the upstream could date it, else `note.ingested_at` -- the contract's own
    fallback for this module (`said_on = note.published or note.ingested_at`). `ingested_at` is never
    `None`, so every note can be placed on a timeline even when `published` could not be recovered."""
    return note.published or note.ingested_at


@dataclass(frozen=True)
class _Event:
    """One dated mention, ready to be replayed in order. `note_idx` is the note's position in the
    `notes` sequence as given -- the deterministic tiebreak (alongside `symbol`) for two mentions that
    land on the exact same `said_on`, per the contract."""

    said_on: dt.datetime
    note_idx: int
    symbol: str
    stance: Stance
    horizon: str
    note_id: str


def _ordered_events(notes: Sequence[EpisodicNote]) -> list[_Event]:
    """Every mention across every note, sorted ascending by `(said_on, note_idx, symbol)` -- the total
    order the replay walks. Built before any inception/horizon/stance filtering so the ordering itself
    never depends on which events end up skipped."""
    events = [
        _Event(
            said_on=_said_on(note),
            note_idx=note_idx,
            symbol=mention.symbol,
            stance=mention.stance,
            horizon=mention.horizon,
            note_id=note.note_id,
        )
        for note_idx, note in enumerate(notes)
        for mention in note.mentions
    ]
    events.sort(key=lambda e: (e.said_on, e.note_idx, e.symbol))
    return events


def _fetch_bars(
    symbol: str,
    inception: dt.date,
    settings: Settings,
    warnings: list[DigestWarning],
    seen: set[tuple[str, str]],
) -> list[Bar]:
    """The symbol's daily series from `inception` through today, fetched once, sorted ascending by
    `ts`. Returns an empty list -- never raises -- when the symbol cannot be priced at all: a
    `ProviderError` with nothing stored to fall back on (`ensure_series` only raises when the store is
    otherwise empty), or a healthy fetch that comes back with zero bars. Both leave every call on this
    symbol recorded as a skip, named once in `warnings` with `reason="no market data"` (the exact
    wording other Phase 6 workers key off of -- exception detail goes to the log, never the wire)."""
    try:
        series = ensure_series(symbol, Interval.DAY, start=inception, settings=settings)
    except ProviderError as exc:
        _log.info("build_persona_book: %s has no usable bars (provider error: %s)", symbol, exc)
        _warn(warnings, seen, source=symbol, reason="no market data")
        return []

    if not series.bars:
        _warn(warnings, seen, source=symbol, reason="no market data")
        return []

    return sorted(series.bars, key=lambda b: b.ts)


def _bar_on_or_after(bars: Sequence[Bar], on_or_after: dt.date) -> tuple[int, Bar] | None:
    """The first bar with `bar.ts.date() >= on_or_after` -- never an earlier one, for either a buy or a
    sell. Reaching backward to a close that predates the event would silently look ahead of what the
    influencer actually reacted to. Returns the bar's index alongside the bar itself so the caller can
    compute `bars_held` without a second scan. `None` when every stored bar predates the date."""
    for idx, bar in enumerate(bars):
        if bar.ts.date() >= on_or_after:
            return idx, bar
    return None


def _basis_prices(entry: Bar, latest: Bar) -> tuple[Decimal, Decimal]:
    """Entry and latest prices on one shared basis -- adjusted close when *both* bars have one, raw
    close otherwise. Never mixes a raw close at one end with an adjusted close at the other. Converts
    via `Decimal(str(...))` rather than `Decimal(float)`: the latter would carry the binary float's own
    representation error (e.g. `Decimal(110.1)` is `Decimal('110.09999999999999431565811391...')`)
    straight into a reported basis. Used only for the FINAL mark of a still-open holding -- every fill
    (buy or sell) during the replay itself prices off the plain close, per the contract."""
    if entry.adj_close is not None and latest.adj_close is not None:
        return Decimal(str(entry.adj_close)), Decimal(str(latest.adj_close))
    return Decimal(str(entry.close)), Decimal(str(latest.close))


@dataclass
class _Position:
    """One open paper position, tracked mutably while the replay walks events. `entry_bar`/`entry_idx`
    are kept (not just `entry_price`) so a still-open position's final mark can re-pair entry and latest
    bars through `_basis_prices` -- the adjusted-close nuance only matters for that end-of-replay mark,
    never for the fill price itself."""

    symbol: str
    note_id: str
    entry_date: dt.date
    entry_bar: Bar
    entry_idx: int
    entry_price: Decimal
    quantity: Decimal
    cost_basis: Decimal
    last_bullish_on: dt.date


def _realise(
    pos: _Position, exit_bar: Bar, *, reason: _TradeReason
) -> tuple[PersonaTrade, Decimal]:
    """Close `pos` at `exit_bar`'s plain close -> a `PersonaTrade` plus the cash proceeds to credit."""
    exit_price = Decimal(str(exit_bar.close))
    proceeds = quantize_money(pos.quantity * exit_price)
    realised_pnl = quantize_money(pos.quantity * (exit_price - pos.entry_price))
    return_pct = ((exit_price / pos.entry_price) - 1).quantize(_RETURN_QUANT, rounding=ROUND_HALF_UP)
    trade = PersonaTrade(
        symbol=pos.symbol,
        note_id=pos.note_id,
        entry_date=pos.entry_date,
        entry_price=quantize_money(pos.entry_price),
        exit_date=exit_bar.ts.date(),
        exit_price=quantize_money(exit_price),
        quantity=pos.quantity,
        realised_pnl=realised_pnl,
        return_pct=return_pct,
        reason=reason,
    )
    return trade, proceeds


def build_persona_book(
    *,
    persona: Persona,
    notes: Sequence[EpisodicNote],
    settings: Settings,
    inception: dt.date = DEFAULT_INCEPTION,
    notional_per_position: Decimal = DEFAULT_NOTIONAL_USD,
    as_of: dt.date | None = None,
    exclude_intraday: bool = False,
    now: dt.datetime | None = None,
) -> PersonaBook:
    """Replay `persona`'s dated calls into a $100,000 cash-constrained paper book.

    Every mention across `notes` is walked in ascending `said_on` order (ties broken by note-encounter
    order then symbol). `intraday`-horizon calls and `unclear` stances are always no-ops -- a scalp is
    not a holding to carry forward, and `exclude_intraday` (kept only for signature compatibility with
    callers built against the previous snapshot semantics) has nothing left to add on top of that.
    Calls dated before `inception` are ignored entirely.

    - A **bullish** call on a symbol not currently held attempts a `notional_per_position` buy at the
      first close on/after the call date, provided a slot is free (fewer than `MAX_OPEN_POSITIONS`
      open) and held cash covers it. When the book is full or cash is short, it closes its
      longest-held ("stalest") position(s) first to make room (`PersonaTrade(reason="replaced")`), and
      only skips the call (`PersonaSkippedCall(reason="no_cash")`) once that still is not enough. A
      symbol already held is just re-affirmed -- no new trade.
    - A **bearish or neutral** call on a symbol currently held closes it at the first close on/after the
      call date, realising its P&L (`PersonaTrade(reason="flip_bearish"` or `"flip_neutral"`). Not held
      -> no-op.
    - A symbol that cannot be priced at all is skipped with `PersonaSkippedCall(reason="no_market_data")`
      and named once in `warnings`; priceable but with no bar since the call date yet is
      `PersonaSkippedCall(reason="no_bar_since")`.

    Every still-open position is marked, at the end, to its latest available close (adjusted-close basis
    when both entry and latest bars have one, else raw close -- see `_basis_prices`). Cash never goes
    negative: a buy only ever executes once the cash for it is actually in hand.

    `as_of`, when given, replays only calls with `said_on.date() <= as_of` and marks still-open
    positions to the latest bar with `ts.date() <= as_of` (excluded and warned if no such bar exists) --
    the point-in-time counterpart to the default "as of today" replay. `now` is accepted for signature
    symmetry with `app.personas.scoring.score_calls` and has no effect (this module's `as_of` is
    bar-derived, not wall-clock).
    """
    del now

    warnings: list[DigestWarning] = []
    seen_warnings: set[tuple[str, str]] = set()
    bars_cache: dict[str, list[Bar]] = {}

    def symbol_bars(symbol: str) -> list[Bar]:
        if symbol not in bars_cache:
            bars_cache[symbol] = _fetch_bars(symbol, inception, settings, warnings, seen_warnings)
        return bars_cache[symbol]

    cash = quantize_money(STARTING_CASH_USD)
    positions: dict[str, _Position] = {}
    trades: list[PersonaTrade] = []
    skipped: list[PersonaSkippedCall] = []

    def open_position(
        symbol: str, note_id: str, idx: int, bar: Bar, entry_price: Decimal, said_on_date: dt.date
    ) -> None:
        nonlocal cash
        quantity = (notional_per_position / entry_price).quantize(_QTY_QUANT, rounding=ROUND_HALF_UP)
        cost_basis = quantize_money(notional_per_position)
        cash = quantize_money(cash - notional_per_position)
        positions[symbol] = _Position(
            symbol=symbol,
            note_id=note_id,
            entry_date=bar.ts.date(),
            entry_bar=bar,
            entry_idx=idx,
            entry_price=entry_price,
            quantity=quantity,
            cost_basis=cost_basis,
            last_bullish_on=said_on_date,
        )

    def close_position(symbol: str, said_on_date: dt.date, reason: _TradeReason) -> None:
        nonlocal cash
        pos = positions.pop(symbol)
        bars = symbol_bars(symbol)
        located = _bar_on_or_after(bars, said_on_date)
        if located is not None:
            _, exit_bar = located
        else:
            # Shouldn't happen -- the symbol was priceable enough to buy -- but never fabricate a
            # fill: fall back to the latest available close and say so.
            exit_bar = bars[-1]
            _warn(
                warnings,
                seen_warnings,
                source=symbol,
                reason=f"sold at last available close, no bar on/after {said_on_date.isoformat()}",
            )
        trade, proceeds = _realise(pos, exit_bar, reason=reason)
        trades.append(trade)
        cash = quantize_money(cash + proceeds)

    for event in _ordered_events(notes):
        said_on_date = event.said_on.astimezone(dt.UTC).date()
        if said_on_date < inception:
            continue
        if as_of is not None and said_on_date > as_of:
            continue
        if event.horizon == "intraday" or event.stance == "unclear":
            continue

        if event.stance == "bullish":
            if event.symbol in positions:
                positions[event.symbol].last_bullish_on = said_on_date
                continue

            bars = symbol_bars(event.symbol)
            if not bars:
                skipped.append(
                    PersonaSkippedCall(symbol=event.symbol, said_on=said_on_date, reason="no_market_data")
                )
                continue
            located = _bar_on_or_after(bars, said_on_date)
            if located is None:
                skipped.append(
                    PersonaSkippedCall(symbol=event.symbol, said_on=said_on_date, reason="no_bar_since")
                )
                continue
            idx, bar = located
            entry_price = Decimal(str(bar.close))
            if entry_price == 0:
                _warn(warnings, seen_warnings, source=event.symbol, reason="no market data")
                skipped.append(
                    PersonaSkippedCall(symbol=event.symbol, said_on=said_on_date, reason="no_market_data")
                )
                continue

            # Make room for the fresh name: close the stalest position(s) while the book is either
            # full (at the count cap) or short of the entry notional. A profitable book stays capped
            # at MAX_OPEN_POSITIONS names -- it cannot drift to an eleventh on paper gains -- and the
            # "sell something to buy something" discipline holds on both the count and the cash edge.
            while positions and (
                len(positions) >= MAX_OPEN_POSITIONS or cash < notional_per_position
            ):
                stalest_symbol = min(
                    positions, key=lambda s: (positions[s].last_bullish_on, s)
                )
                close_position(stalest_symbol, said_on_date, "replaced")

            if cash >= notional_per_position and len(positions) < MAX_OPEN_POSITIONS:
                open_position(event.symbol, event.note_id, idx, bar, entry_price, said_on_date)
            else:
                skipped.append(
                    PersonaSkippedCall(symbol=event.symbol, said_on=said_on_date, reason="no_cash")
                )
        else:  # bearish or neutral
            if event.symbol in positions:
                flip_reason: _TradeReason = (
                    "flip_bearish" if event.stance == "bearish" else "flip_neutral"
                )
                close_position(event.symbol, said_on_date, flip_reason)
            # else: not held -> no-op.

    holdings: list[PersonaHolding] = []
    for pos in positions.values():
        bars = symbol_bars(pos.symbol)
        if as_of is not None:
            bars = [b for b in bars if b.ts.date() <= as_of]
        if not bars:
            _warn(
                warnings,
                seen_warnings,
                source=pos.symbol,
                reason=f"no bar on or before {as_of.isoformat()}" if as_of else "no market data",
            )
            continue
        latest_idx = len(bars) - 1
        latest_bar = bars[latest_idx]
        entry_price_disp, last_price_disp = _basis_prices(pos.entry_bar, latest_bar)
        if entry_price_disp == 0:
            _warn(warnings, seen_warnings, source=pos.symbol, reason="no market data")
            continue

        market_value = quantize_money(pos.quantity * last_price_disp)
        unrealised_pnl = quantize_money(market_value - pos.cost_basis)
        return_pct = ((last_price_disp / entry_price_disp) - 1).quantize(
            _RETURN_QUANT, rounding=ROUND_HALF_UP
        )
        holdings.append(
            PersonaHolding(
                symbol=pos.symbol,
                stance="bullish",
                note_id=pos.note_id,
                entry_date=pos.entry_date,
                entry_price=quantize_money(entry_price_disp),
                quantity=pos.quantity,
                cost_basis=pos.cost_basis,
                last_price=quantize_money(last_price_disp),
                last_price_date=latest_bar.ts.date(),
                market_value=market_value,
                unrealised_pnl=unrealised_pnl,
                return_pct=return_pct,
                bars_held=latest_idx - pos.entry_idx,
                weight=0.0,
                last_bullish_on=pos.last_bullish_on,
            )
        )

    cost_basis_total = quantize_money(sum((h.cost_basis for h in holdings), Decimal(0)))
    market_value_total = quantize_money(sum((h.market_value for h in holdings), Decimal(0)))
    unrealised_pnl_total = quantize_money(market_value_total - cost_basis_total)
    realised_pnl_total = quantize_money(sum((t.realised_pnl for t in trades), Decimal(0)))
    equity = quantize_money(cash + market_value_total)
    return_pct_total = ((equity / STARTING_CASH_USD) - 1).quantize(_RETURN_QUANT, rounding=ROUND_HALF_UP)

    if market_value_total != 0:
        holdings = [
            h.model_copy(update={"weight": float(h.market_value / market_value_total)})
            for h in holdings
        ]
    # else: every holding keeps the `weight=0.0` set above -- a zero denominator must never propagate
    # as a NaN/inf weight.

    holdings.sort(key=lambda h: (-h.weight, h.symbol))

    if holdings:
        as_of_result: dt.date | None = max(h.last_price_date for h in holdings)
    elif trades:
        as_of_result = max(t.exit_date for t in trades)
    else:
        as_of_result = None

    return PersonaBook(
        persona=persona.slug,
        display_name=persona.display_name,
        inception=inception,
        as_of=as_of_result,
        notional_per_position=quantize_money(notional_per_position),
        starting_cash=quantize_money(STARTING_CASH_USD),
        cash=cash,
        equity=equity,
        holdings=tuple(holdings),
        cost_basis_total=cost_basis_total,
        market_value_total=market_value_total,
        unrealised_pnl_total=unrealised_pnl_total,
        realised_pnl_total=realised_pnl_total,
        return_pct=return_pct_total,
        trade_count=len(trades),
        open_count=len(holdings),
        trades=tuple(trades),
        skipped=tuple(skipped),
        warnings=tuple(warnings),
    )
