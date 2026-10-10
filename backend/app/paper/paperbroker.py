"""A paper broker for UAT personas: notional cash, real prices, hard mandate limits.

This exists because the dashboard has no order-execution path -- it is an analytics layer over
broker CSV exports. To get a week of realistic trade data through it, something has to play the
broker. This module does, and then :mod:`uat.harness.ingest` renders its fills as a broker export so
the data enters the application through the *real* adapter, ledger, lot and wash-sale code rather
than through a side door. A UAT run that bypassed ingest would prove nothing about ingest.

Three decisions worth stating, because each rules out a class of quietly-wrong result:

**Fills are at the next session's open, never at the close the persona just read.** Filling at the
decision-session close makes every decision look prescient by exactly the amount of the overnight
gap, and the effect is largest on the volatile names a persona is most drawn to. See
:mod:`uat.harness.marketdata` for how the read side enforces the matching boundary.

**Decimal throughout, floats rejected at the boundary.** The ledger these fills eventually land in
refuses binary floats in monetary fields (``app.core.models._reject_float``) precisely because the
error compounds through lot matching into a wrong tax figure. A broker that produced floats would
push that error one layer upstream where the ledger's guard cannot see it.

**Mandate limits reject, they do not warn.** A persona that can talk its way past its own position
cap produces trade data that no longer tests what the mandate says it tests. Every violation comes
back as a :class:`Rejection` with a reason string the persona is shown, which is also a small piece
of UAT signal in itself: the reasons a model trips over are the constraints a real user would find
unintuitive.

Nothing here is investment advice, and none of these trades are real.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Final, Literal

from app.market.live import LiveQuoteSource
from app.paper.marketdata import AsOfMarket, UnpricedSymbol

__all__ = [
    "Fill",
    "Mandate",
    "Order",
    "PaperBroker",
    "Rejection",
    "SessionResult",
    "load_mandate",
]

CENTS: Final = Decimal("0.01")
Side = Literal["buy", "sell"]


def _money(value: Decimal) -> Decimal:
    """Round to cents, half-up. Applied at every point a figure becomes a cash movement."""
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def _live_quote_price(symbol: str, source: LiveQuoteSource) -> Decimal | None:
    """One symbol's current live price from `source`, or `None` if there is nothing usable.

    `LiveQuoteSource.snapshot` (`app.market.live`) can come back with an error entry instead of a
    quote -- a brand-new symbol nobody has watched yet, a provider that failed this cycle -- and a
    `LiveQuote` it does return can carry a zero price when a provider genuinely has nothing to say
    (see `app.market.live._to_live_quote`'s own `Decimal("0")` fallback). Both degrade to `None`
    here, never raise: a caller reaching :meth:`PaperBroker.submit`'s live-quote branch has already
    decided what to do when no price is available (reject the order), and an unhandled exception
    from a live network call reaching all the way into a broker submission would be a worse failure
    than the rejection it should have produced instead.
    """
    try:
        snapshot = source.snapshot([symbol])
    except Exception:
        return None
    upper = symbol.upper()
    for quote in snapshot.quotes:
        if quote.symbol.upper() == upper and quote.price > 0:
            return quote.price
    return None


# ---------------------------------------------------------------------------
# Mandate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Mandate:
    """The persona's hard constraints, loaded from ``uat/personas/<id>.setup.json``."""

    persona_id: str
    display_name: str
    account_id: str
    account_label: str
    starting_cash: Decimal

    allow_fractional_shares: bool
    max_positions: int
    max_single_name_weight: Decimal
    min_clip_notional: Decimal
    min_cash: Decimal
    settlement_days: int

    slippage_bps: Decimal
    commission_per_trade: Decimal
    sec_fee_rate: Decimal
    taf_per_share: Decimal
    taf_cap: Decimal


def load_mandate(path: Path) -> Mandate:
    """Read a persona setup file into a :class:`Mandate`.

    Every numeric field is read from a JSON *string* and passed to ``Decimal`` directly. JSON has
    only binary floats, so a bare ``10000.00`` in the file would arrive as a float and reintroduce
    exactly the imprecision the rest of this module is arranged to avoid.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    account = raw["account"]
    constraints = raw["constraints"]
    execution = raw["execution"]

    return Mandate(
        persona_id=raw["persona_id"],
        display_name=raw["display_name"],
        account_id=account["account_id"],
        account_label=account["label"],
        starting_cash=Decimal(raw["capital"]["starting_cash"]),
        allow_fractional_shares=bool(constraints["allow_fractional_shares"]),
        max_positions=int(constraints["max_positions"]),
        max_single_name_weight=Decimal(constraints["max_single_name_weight"]),
        min_clip_notional=Decimal(constraints["min_clip_notional"]),
        min_cash=Decimal(constraints["min_cash"]),
        settlement_days=int(constraints["settlement_days"]),
        slippage_bps=Decimal(execution["slippage_bps"]),
        commission_per_trade=Decimal(execution["commission_per_trade"]),
        sec_fee_rate=Decimal(execution["sec_fee_rate"]),
        taf_per_share=Decimal(execution["taf_per_share"]),
        taf_cap=Decimal(execution["taf_cap"]),
    )


# ---------------------------------------------------------------------------
# Orders, fills, rejections
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Order:
    """An order as the persona submitted it. Validated in :meth:`PaperBroker.submit`."""

    order_id: str
    session: int
    decided_on: dt.date
    symbol: str
    side: Side
    quantity: Decimal
    thesis: str
    invalidation: str
    stop_level: Decimal | None = None
    regime: str | None = None
    conviction: int | None = None
    evidence: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "session": self.session,
            "decided_on": self.decided_on.isoformat(),
            "symbol": self.symbol,
            "side": self.side,
            "quantity": format(self.quantity, "f"),
            "order_type": "market_on_open",
            "thesis": self.thesis,
            "invalidation": self.invalidation,
            "stop_level": format(self.stop_level, "f") if self.stop_level is not None else None,
            "regime": self.regime,
            "conviction": self.conviction,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class Fill:
    """An executed order. The unit :mod:`uat.harness.ingest` turns into ledger rows."""

    order_id: str
    session: int
    trade_date: dt.date
    """The session filled on -- one session after the order's ``decided_on``."""
    symbol: str
    side: Side
    quantity: Decimal
    price: Decimal
    """Open price plus (buy) or minus (sell) slippage, rounded to cents."""
    reference_open: Decimal
    """The unslipped open, kept so the slippage assumption can be audited or re-run."""
    gross: Decimal
    """``quantity * price``, rounded to cents. Unsigned."""
    fees: Decimal
    """Regulatory fees. Sells only -- SEC Section 31 and FINRA TAF are charged on disposals."""
    cash_delta: Decimal
    """Signed effect on cash: negative for a buy, positive for a sell net of fees."""
    price_source: Literal["stored_open", "live_quote"] = "stored_open"
    """Where :attr:`reference_open` came from. ``"stored_open"`` is every fill this broker has ever
    produced until the live-quote seam existed in :meth:`PaperBroker.submit` -- the historical path is
    unchanged and this is its default, so every pre-existing construction site (including
    :func:`_fill_from_json` reading an old persisted run) keeps working without naming this field.
    ``"live_quote"`` marks a fill priced off :mod:`app.market.live` because ``fill_date`` had not
    happened yet and no stored open could exist for it -- see :meth:`PaperBroker.submit`'s docstring.
    Provenance, not a second price: :attr:`price` and :attr:`reference_open` already carry the number;
    this says which kind of number it is, for a caller (:mod:`uat.harness.ingest` among them, per this
    module's own docstring) that needs to tell a reproducible historical fill from one that priced off
    a moment in time nobody can replay.
    """

    def to_json(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "session": self.session,
            "trade_date": self.trade_date.isoformat(),
            "symbol": self.symbol,
            "side": self.side,
            "quantity": format(self.quantity, "f"),
            "price": format(self.price, "f"),
            "reference_open": format(self.reference_open, "f"),
            "gross": format(self.gross, "f"),
            "fees": format(self.fees, "f"),
            "cash_delta": format(self.cash_delta, "f"),
            "price_source": self.price_source,
        }


@dataclass(frozen=True, slots=True)
class Rejection:
    """A refused order and why. Shown to the persona; kept in the run record."""

    order_id: str
    session: int
    symbol: str
    side: Side
    quantity: Decimal
    reason: str
    rule: str
    """Which mandate rule fired, as a stable slug -- ``max_positions``, ``insufficient_cash``, ..."""

    def to_json(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "session": self.session,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": format(self.quantity, "f"),
            "reason": self.reason,
            "rule": self.rule,
        }


REJECTION_LABELS: dict[str, str] = {
    "non_positive_quantity": "Non-positive quantity",
    "fractional_shares": "Fractional shares not allowed",
    "missing_thesis": "Missing thesis",
    "missing_invalidation": "Missing invalidation",
    "min_clip": "Below minimum clip size",
    "max_positions": "Max positions reached",
    "insufficient_cash": "Insufficient settled cash",
    "max_single_name_weight": "Single-name weight cap exceeded",
    "unpriceable": "Unpriceable",
    "no_short": "Shorting not allowed",
}
"""Human titles for :attr:`Rejection.rule`, one entry per slug :meth:`PaperBroker._reject` can be
called with today. See :func:`rejection_label` for what a slug missing from this map degrades to --
never an exception."""


def rejection_label(rule: str) -> str:
    """A human-readable title for a rejection rule slug.

    Falls back to a humanised form of the slug itself for anything not in
    :data:`REJECTION_LABELS`, deliberately -- this never raises. A slug this map has not caught up
    with yet (a new rule, or a stale caller) must still render as something readable rather than
    take a page down; this codebase has already been bitten once by a throwing exhaustiveness check
    over a server-supplied string (see `DeskRejection`'s callers)."""
    label = REJECTION_LABELS.get(rule)
    if label is not None:
        return label
    humanised = rule.replace("_", " ").replace("-", " ").strip()
    return humanised[:1].upper() + humanised[1:] if humanised else rule


@dataclass
class SessionResult:
    """Everything one session's order batch produced."""

    session: int
    trade_date: dt.date
    fills: list[Fill] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    cash_open: Decimal = Decimal(0)
    cash_close: Decimal = Decimal(0)
    equity_close: Decimal = Decimal(0)
    """Cash plus positions marked at the session's own close."""
    marks: dict[str, Decimal] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# The broker
# ---------------------------------------------------------------------------


class PaperBroker:
    """Notional cash and positions for one persona over one run.

    Not thread-safe and not meant to be: one broker, one run, sessions applied in order.
    """

    def __init__(self, mandate: Mandate) -> None:
        self.mandate = mandate
        self.cash: Decimal = mandate.starting_cash
        self.positions: dict[str, Decimal] = {}
        """Symbol -> whole shares held. Cost basis is deliberately *not* tracked here: the ledger
        derives it from the same fills via ``app.core.lots``, and a second basis calculation in the
        harness would be a second thing to keep correct and a way to disagree with the application
        under test."""

        self._unsettled: list[tuple[dt.date, Decimal]] = []
        """``(available_on, amount)`` for sale proceeds not yet settled. A cash account cannot
        rebuy with unsettled proceeds without triggering a good-faith violation, and modelling that
        is what stops the persona from manufacturing free turnover."""

        self.fills: list[Fill] = []
        self.rejections: list[Rejection] = []

    # -- cash --------------------------------------------------------------

    def settled_cash(self, on: dt.date) -> Decimal:
        """Cash available to spend on ``on``: total cash less proceeds that have not settled yet."""
        pending = sum(
            (amount for available_on, amount in self._unsettled if available_on > on),
            Decimal(0),
        )
        return self.cash - pending

    # -- marking -----------------------------------------------------------

    def mark(self, market: AsOfMarket) -> tuple[Decimal, dict[str, Decimal]]:
        """Portfolio market value at ``market``'s as-of close, plus the per-symbol marks.

        An unpriceable holding contributes nothing and is simply absent from the returned marks.
        That mirrors ``app.api.portfolio``: one bad symbol degrades the total rather than failing
        it. The caller is expected to notice the missing key, exactly as the application expects a
        caller to notice ``unpriced_symbols``.
        """
        marks: dict[str, Decimal] = {}
        total = Decimal(0)
        for symbol, quantity in self.positions.items():
            if quantity == 0:
                continue
            try:
                price = market.close(symbol)
            except (UnpricedSymbol, FileNotFoundError):
                continue
            marks[symbol] = price
            total += _money(price * quantity)
        return total, marks

    def equity(self, market: AsOfMarket) -> Decimal:
        value, _ = self.mark(market)
        return self.cash + value

    # -- execution ---------------------------------------------------------

    def submit(
        self,
        order: Order,
        *,
        market: AsOfMarket,
        fill_date: dt.date,
        live_quote_source: LiveQuoteSource | None = None,
        today: dt.date | None = None,
    ) -> Fill | Rejection:
        """Attempt one order. Returns the fill or the reason it was refused.

        ``market`` is as of the *decision* session; ``fill_date`` is the session after it. The
        mandate's weight cap is therefore checked against the decision-session close -- the last
        information the persona actually had -- rather than against the fill price, which nobody
        could have known at submission.

        **The historical path is unchanged.** When ``market.open_on`` finds a stored bar for
        ``fill_date``, that price is used exactly as it always has been, ``live_quote_source`` and
        ``today`` are never consulted, and :attr:`Fill.price_source` is ``"stored_open"``.

        ``live_quote_source`` (see :mod:`app.market.live`) is the seam that lets a persona's *current*
        session -- decided on the newest stored close, meant to fill at the following session's open,
        which does not exist yet because tomorrow has not happened -- actually execute instead of
        silently waiting a day for a bar to arrive. It is consulted **only** when ``open_on`` raises
        *and* ``fill_date`` is today or later (compared against ``today``, or :func:`datetime.date.today`
        when ``today`` is not given -- injectable so a test never depends on the real wall clock). A
        missing bar for a ``fill_date`` already in the past is a genuine data gap, not a not-yet-synced
        one, and rejects exactly as before regardless of whether a live source was passed in --
        collapsing that distinction would silently turn a real hole in the store into a live fill,
        which is precisely the failure mode this branch exists to avoid. When the live path is taken
        and produces a usable quote, slippage (:meth:`_slipped`) still applies to it the same as any
        other reference price, and the resulting :class:`Fill` carries ``price_source="live_quote"`` so
        a caller can tell a reproducible historical fill from one that priced off a moment in time
        nobody can replay.
        """
        reject = self._precheck(order)
        if reject is not None:
            # `_precheck` refuses through `_reject`, which is the sole place that appends to
            # `self.rejections` (see its docstring). Appending here too was the defect: every
            # precheck rejection landed twice, which `summarize()` then over-counted -- selectively,
            # since rejections from the price-dependent paths below call `_reject` directly and were
            # only ever recorded once. It went unnoticed for four full runs because runs 1 through 4
            # produced zero rejections between them; run 5 (order `s2-8`, a fractional-share
            # refusal) is the first order this harness ever rejected, and it came back doubled in
            # both `rejections_this_session` and the next session's `prior_rejections`. Its
            # `metrics.json` is left as recorded and reads 7 rejections with `fractional_shares: 2`;
            # the true figures are 6 and 1.
            return reject

        price_source: Literal["stored_open", "live_quote"] = "stored_open"
        try:
            reference_open = market.open_on(order.symbol, fill_date)
        except (UnpricedSymbol, FileNotFoundError):
            as_of_today = today if today is not None else dt.date.today()
            if live_quote_source is None or fill_date < as_of_today:
                # Either no live source was ever wired in (the historical/default path -- every
                # caller before this seam existed, and every caller today with the feature flag off),
                # or `fill_date` is in the past: a stored-bar gap for a date that has already happened
                # is a real hole in the store, not a bar that simply has not arrived yet, and must
                # still reject exactly as it always has -- see this method's own docstring.
                return self._reject(
                    order,
                    rule="unpriceable",
                    reason=(
                        f"no stored open for {order.symbol} on {fill_date.isoformat()}; "
                        "the order cannot be filled at a price that was ever real"
                    ),
                )
            live_price = _live_quote_price(order.symbol, live_quote_source)
            if live_price is None:
                return self._reject(
                    order,
                    rule="unpriceable",
                    reason=(
                        f"no stored open for {order.symbol} on {fill_date.isoformat()} and no live "
                        "quote is available for it either"
                    ),
                )
            reference_open = live_price
            price_source = "live_quote"

        price = self._slipped(reference_open, order.side)
        gross = _money(price * order.quantity)

        if order.side == "buy":
            outcome = self._check_buy(order, market=market, gross=gross, fill_date=fill_date)
        else:
            outcome = self._check_sell(order)
        if outcome is not None:
            return outcome

        fees = self._fees(order, gross=gross)
        cash_delta = -(gross + fees) if order.side == "buy" else (gross - fees)

        fill = Fill(
            order_id=order.order_id,
            session=order.session,
            trade_date=fill_date,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            reference_open=reference_open,
            gross=gross,
            fees=fees,
            cash_delta=_money(cash_delta),
            price_source=price_source,
        )
        self._apply(fill)
        self.fills.append(fill)
        return fill

    # -- validation --------------------------------------------------------

    def _precheck(self, order: Order) -> Rejection | None:
        """Constraints that need no price."""
        if order.quantity <= 0:
            return self._reject(
                order, rule="non_positive_quantity", reason="quantity must be greater than zero"
            )
        if not self.mandate.allow_fractional_shares and order.quantity != order.quantity.to_integral_value():
            return self._reject(
                order,
                rule="fractional_shares",
                reason=f"mandate is whole shares only; {order.quantity} is fractional",
            )
        if not order.thesis.strip():
            return self._reject(
                order, rule="missing_thesis", reason="an order without a thesis is not recorded"
            )
        if not order.invalidation.strip():
            return self._reject(
                order,
                rule="missing_invalidation",
                reason="an order without a written invalidation is not recorded",
            )
        return None

    def _check_buy(
        self,
        order: Order,
        *,
        market: AsOfMarket,
        gross: Decimal,
        fill_date: dt.date,
    ) -> Rejection | None:
        mandate = self.mandate
        available = self.settled_cash(fill_date)

        if gross < mandate.min_clip_notional and order.symbol not in self.positions:
            return self._reject(
                order,
                rule="min_clip",
                reason=(
                    f"${gross} is below the ${mandate.min_clip_notional} minimum clip for a new "
                    "position"
                ),
            )

        if order.symbol not in self.positions and len(self._open_symbols()) >= mandate.max_positions:
            return self._reject(
                order,
                rule="max_positions",
                reason=(
                    f"already holding {len(self._open_symbols())} of a maximum "
                    f"{mandate.max_positions} positions; exit one before initiating {order.symbol}"
                ),
            )

        if gross > available - mandate.min_cash:
            return self._reject(
                order,
                rule="insufficient_cash",
                reason=(
                    f"${gross} exceeds ${available} of settled cash "
                    f"(total cash ${self.cash}; unsettled proceeds are not spendable in a cash "
                    "account)"
                ),
            )

        # Weight cap against the decision-session close, on the book as it would stand after the
        # fill. Priced at the close rather than the fill price because that is the number the
        # persona could see when it sized the order.
        try:
            decision_price = market.close(order.symbol)
        except (UnpricedSymbol, FileNotFoundError):
            return self._reject(
                order,
                rule="unpriceable",
                reason=f"{order.symbol} has no close on {market.as_of.isoformat()} to size against",
            )

        held_value, _ = self.mark(market)
        added = _money(decision_price * order.quantity)
        post_position = _money(
            decision_price * (self.positions.get(order.symbol, Decimal(0)) + order.quantity)
        )
        post_equity = self.cash - gross + held_value + added
        if post_equity > 0:
            weight = post_position / post_equity
            if weight > mandate.max_single_name_weight:
                return self._reject(
                    order,
                    rule="max_single_name_weight",
                    reason=(
                        f"{order.symbol} would be {weight:.1%} of the book against a "
                        f"{mandate.max_single_name_weight:.0%} cap"
                    ),
                )
        return None

    def _check_sell(self, order: Order) -> Rejection | None:
        held = self.positions.get(order.symbol, Decimal(0))
        if order.quantity > held:
            return self._reject(
                order,
                rule="no_short",
                reason=(
                    f"cannot sell {order.quantity} {order.symbol}; {held} held and the mandate "
                    "forbids shorting"
                ),
            )
        return None

    def _reject(self, order: Order, *, rule: str, reason: str) -> Rejection:
        """Build a :class:`Rejection` and record it. The *only* place that appends to
        ``self.rejections`` -- every refusal, precheck or otherwise, must be constructed here so
        there is exactly one call site to audit for double-recording. A caller that receives the
        returned :class:`Rejection` (directly, or indirectly through :meth:`_precheck`) must treat
        it as already recorded and never append it itself; see the comment at the precheck call site
        in :meth:`submit` for the bug that shape of mistake produced.
        """
        rejection = Rejection(
            order_id=order.order_id,
            session=order.session,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            reason=reason,
            rule=rule,
        )
        self.rejections.append(rejection)
        return rejection

    # -- mechanics ---------------------------------------------------------

    def _slipped(self, reference: Decimal, side: Side) -> Decimal:
        """Move the open against the persona by the configured spread.

        Slippage is always adverse. A symmetric random model would be more realistic per-trade and
        less useful here: it makes two runs of the same decisions disagree, and a UAT dataset that
        cannot be reproduced is a dataset that cannot be used to confirm a fix.
        """
        factor = self.mandate.slippage_bps / Decimal(10_000)
        adjusted = reference * (Decimal(1) + factor) if side == "buy" else reference * (Decimal(1) - factor)
        return _money(adjusted)

    def _fees(self, order: Order, *, gross: Decimal) -> Decimal:
        """Regulatory fees. Charged on disposals only, which is how both fees actually work.

        These are pennies at this notional -- an SEC fee on a $2,000 sale is under six cents -- and
        they are modelled anyway because the point of the run is to exercise the ledger, and the
        ledger has a ``FEE`` code path that would otherwise never be touched by this data.
        """
        if order.side == "buy":
            return self.mandate.commission_per_trade
        sec = gross * self.mandate.sec_fee_rate
        taf = min(order.quantity * self.mandate.taf_per_share, self.mandate.taf_cap)
        return _money(sec + taf + self.mandate.commission_per_trade)

    def _apply(self, fill: Fill) -> None:
        self.cash = _money(self.cash + fill.cash_delta)
        held = self.positions.get(fill.symbol, Decimal(0))
        if fill.side == "buy":
            self.positions[fill.symbol] = held + fill.quantity
        else:
            remaining = held - fill.quantity
            if remaining == 0:
                self.positions.pop(fill.symbol, None)
            else:
                self.positions[fill.symbol] = remaining
            settles_on = _add_business_days(fill.trade_date, self.mandate.settlement_days)
            self._unsettled.append((settles_on, _money(fill.gross - fill.fees)))

    def _open_symbols(self) -> list[str]:
        return [symbol for symbol, quantity in self.positions.items() if quantity > 0]

    # -- persistence -------------------------------------------------------
    #
    # Sessions run as separate processes -- the persona is a subagent invoked between them -- so the
    # book has to survive process exit. Every number round-trips as a string for the same reason the
    # rest of this module avoids floats: JSON numbers are IEEE doubles, and a book that serialises
    # `10000.00` and deserialises `9999.999999999998` would drift a little further every session.

    def to_state(self) -> dict[str, Any]:
        return {
            "cash": format(self.cash, "f"),
            "positions": {s: format(q, "f") for s, q in sorted(self.positions.items())},
            "unsettled": [
                [day.isoformat(), format(amount, "f")] for day, amount in self._unsettled
            ],
            "fills": [f.to_json() for f in self.fills],
            "rejections": [r.to_json() for r in self.rejections],
        }

    @classmethod
    def from_state(cls, mandate: Mandate, state: Mapping[str, Any]) -> PaperBroker:
        broker = cls(mandate)
        broker.cash = Decimal(state["cash"])
        broker.positions = {s: Decimal(q) for s, q in state["positions"].items()}
        broker._unsettled = [
            (dt.date.fromisoformat(day), Decimal(amount)) for day, amount in state["unsettled"]
        ]
        broker.fills = [_fill_from_json(row) for row in state["fills"]]
        broker.rejections = [_rejection_from_json(row) for row in state["rejections"]]
        return broker

    # -- reporting ---------------------------------------------------------

    def snapshot(self, market: AsOfMarket) -> dict[str, Any]:
        """Book state as of ``market``, in the shape the persona is shown at session start."""
        value, marks = self.mark(market)
        equity = self.cash + value
        unpriced = sorted(set(self._open_symbols()) - set(marks))
        return {
            "as_of": market.as_of.isoformat(),
            "cash": format(self.cash, "f"),
            "settled_cash": format(self.settled_cash(market.as_of), "f"),
            "positions_market_value": format(value, "f"),
            "equity": format(equity, "f"),
            "return_since_inception_pct_of_1": (
                format((equity - self.mandate.starting_cash) / self.mandate.starting_cash, ".6f")
            ),
            "positions": [
                {
                    "symbol": symbol,
                    "quantity": format(quantity, "f"),
                    "mark": format(marks[symbol], "f") if symbol in marks else None,
                    "market_value": (
                        format(_money(marks[symbol] * quantity), "f") if symbol in marks else None
                    ),
                    "weight_pct_of_1": (
                        format(_money(marks[symbol] * quantity) / equity, ".6f")
                        if symbol in marks and equity > 0
                        else None
                    ),
                }
                for symbol, quantity in sorted(self.positions.items())
                if quantity > 0
            ],
            "unpriced_symbols": unpriced,
            "open_position_count": len(self._open_symbols()),
            "max_positions": self.mandate.max_positions,
        }


def _fill_from_json(row: Mapping[str, Any]) -> Fill:
    return Fill(
        order_id=row["order_id"],
        session=int(row["session"]),
        trade_date=dt.date.fromisoformat(row["trade_date"]),
        symbol=row["symbol"],
        side=row["side"],
        quantity=Decimal(row["quantity"]),
        price=Decimal(row["price"]),
        reference_open=Decimal(row["reference_open"]),
        gross=Decimal(row["gross"]),
        fees=Decimal(row["fees"]),
        cash_delta=Decimal(row["cash_delta"]),
        # `.get(..., "stored_open")` rather than `row["price_source"]`: a run persisted before this
        # field existed has no such key, and that absence means exactly "stored_open" (the only kind
        # of fill that could have been recorded then) -- not a missing-key error. See `Fill.
        # price_source`'s own docstring.
        price_source=row.get("price_source", "stored_open"),
    )


def _rejection_from_json(row: Mapping[str, Any]) -> Rejection:
    return Rejection(
        order_id=row["order_id"],
        session=int(row["session"]),
        symbol=row["symbol"],
        side=row["side"],
        quantity=Decimal(row["quantity"]),
        reason=row["reason"],
        rule=row["rule"],
    )


def _add_business_days(start: dt.date, days: int) -> dt.date:
    """Advance by ``days`` weekdays.

    Weekday arithmetic, not an exchange calendar: settlement here only has to stop the persona
    reusing proceeds within the same session, and a holiday that slips settlement by one day does
    not change any decision this harness records. Using the session calendar would be more precise
    and would couple the broker to a run-wide object it otherwise does not need.
    """
    current = start
    remaining = days
    while remaining > 0:
        current += dt.timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def summarize(
    fills: Iterable[Fill],
    rejections: Iterable[Rejection],
) -> Mapping[str, Any]:
    """Counts for the run metrics file."""
    fills = list(fills)
    rejections = list(rejections)
    buys = [f for f in fills if f.side == "buy"]
    sells = [f for f in fills if f.side == "sell"]
    return {
        "fills": len(fills),
        "buys": len(buys),
        "sells": len(sells),
        "gross_traded": format(sum((f.gross for f in fills), Decimal(0)), "f"),
        "total_fees": format(sum((f.fees for f in fills), Decimal(0)), "f"),
        "rejections": len(rejections),
        "rejections_by_rule": {
            rule: sum(1 for r in rejections if r.rule == rule)
            for rule in sorted({r.rule for r in rejections})
        },
    }
