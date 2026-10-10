"""Tests for `app.paper.papertax`: the paper desk's after-tax reporting built on the real tax engine.

Every case here constructs `app.paper.paperbroker.Fill` objects directly -- the shape a
`PaperBroker` run actually produces -- rather than going through a live `PaperBroker`, so each test
pins exactly the trade sequence and dates it needs without depending on market data or the mandate's
own execution rules. `_fill` below reproduces `PaperBroker`'s own rounding (`_money`, cents, half-up)
so the fixtures are internally consistent with what a real fill would look like.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.config import Settings
from app.paper.paperbroker import Fill
from app.paper.papertax import (
    STATUTORY_LONG_TERM_RATE,
    STATUTORY_SHORT_TERM_RATE,
    fills_to_transactions,
    resolve_configured_rates,
    summarize_paper_tax,
)

CENTS = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def _fill(
    order_id: str,
    session: int,
    trade_date: date,
    symbol: str,
    side: str,
    quantity: str,
    price: str,
    fees: str = "0.00",
) -> Fill:
    """Build one `Fill` the way `PaperBroker.submit` would have, at the given price and quantity.

    Slippage is not modelled here -- `price` is taken as the fill price directly (``reference_open``
    equal to it), since these tests are about the tax engine's own arithmetic, not the broker's
    slippage model, which `tests/test_paper_live_fill.py` and friends already cover.
    """
    qty = Decimal(quantity)
    px = Decimal(price)
    fee = Decimal(fees)
    gross = _money(qty * px)
    cash_delta = _money(-(gross + fee)) if side == "buy" else _money(gross - fee)
    return Fill(
        order_id=order_id,
        session=session,
        trade_date=trade_date,
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        quantity=qty,
        price=px,
        reference_open=px,
        gross=gross,
        fees=fee,
        cash_delta=cash_delta,
    )


# ---------------------------------------------------------------------------
# fills_to_transactions
# ---------------------------------------------------------------------------


def test_fills_to_transactions_is_independent_of_input_order() -> None:
    """The same two fills, given in either order, must produce the identical `Transaction` list --
    see the module docstring: ordering is imposed internally by `(trade_date, session, order_id)`,
    never taken from the caller's list order."""
    buy = _fill("o1", 1, date(2026, 1, 5), "AAPL", "buy", "10", "100.00")
    sell = _fill("o2", 2, date(2026, 3, 5), "AAPL", "sell", "10", "150.00")

    forward = fills_to_transactions([buy, sell])
    backward = fills_to_transactions([sell, buy])

    assert [t.txn_id for t in forward] == [t.txn_id for t in backward]
    assert [t.source_row for t in forward] == [0, 1]
    assert [t.replay_order for t in forward] == [0, 1]


def test_fills_to_transactions_maps_side_to_buy_and_sell_actions() -> None:
    buy = _fill("o1", 1, date(2026, 1, 5), "AAPL", "buy", "10", "100.00")
    sell = _fill("o2", 2, date(2026, 3, 5), "AAPL", "sell", "10", "150.00")

    txns = fills_to_transactions([buy, sell])

    assert txns[0].action.value == "buy"
    assert txns[0].quantity == Decimal("10")
    assert txns[0].price == Decimal("100.00")
    assert txns[1].action.value == "sell"
    assert txns[1].price == Decimal("150.00")


# ---------------------------------------------------------------------------
# Case 1: simple short-term gain
# ---------------------------------------------------------------------------


def test_simple_short_term_gain() -> None:
    fills = [
        _fill("o1", 1, date(2026, 1, 5), "AAPL", "buy", "10", "100.00"),
        _fill("o2", 2, date(2026, 3, 5), "AAPL", "sell", "10", "150.00"),
    ]

    summary = summarize_paper_tax(fills)

    assert summary.short_term_gain == Decimal("500.00")
    assert summary.long_term_gain == Decimal("0")
    assert summary.net_realized_gain == Decimal("500.00")
    assert summary.wash_sales == ()
    assert summary.disallowed_loss_total == Decimal("0")

    # Statutory-default after-tax figure: 500 * 0.37 short-term rate.
    assert summary.short_term_rate == STATUTORY_SHORT_TERM_RATE
    assert summary.rate_basis == "statutory_upper_bound"
    assert summary.tax_owed == Decimal("185.00")
    assert summary.after_tax_realized_gain == Decimal("315.00")


# ---------------------------------------------------------------------------
# Case 2: long-term gain (held > 365 days)
# ---------------------------------------------------------------------------


def test_long_term_gain_held_over_a_year() -> None:
    fills = [
        _fill("o1", 1, date(2024, 1, 10), "MSFT", "buy", "5", "200.00"),
        _fill("o2", 2, date(2025, 6, 15), "MSFT", "sell", "5", "300.00"),
    ]

    summary = summarize_paper_tax(fills)

    assert summary.long_term_gain == Decimal("500.00")
    assert summary.short_term_gain == Decimal("0")
    assert summary.wash_sales == ()

    tax_owed = _money(Decimal("500.00") * STATUTORY_LONG_TERM_RATE)
    assert summary.tax_owed == tax_owed
    assert summary.after_tax_realized_gain == Decimal("500.00") - tax_owed


def test_holding_exactly_one_year_is_still_short_term() -> None:
    """`app.tax.gains.classify_term`: long-term requires *more than* one year -- exactly the
    anniversary date is short-term. Sanity check that the paper-tax wiring does not special-case
    this away from the real engine's rule."""
    fills = [
        _fill("o1", 1, date(2025, 1, 10), "MSFT", "buy", "5", "200.00"),
        _fill("o2", 2, date(2026, 1, 10), "MSFT", "sell", "5", "300.00"),
    ]

    summary = summarize_paper_tax(fills)

    assert summary.short_term_gain == Decimal("500.00")
    assert summary.long_term_gain == Decimal("0")


# ---------------------------------------------------------------------------
# Case 3: loss + repurchase inside 30 days -> wash sale
# ---------------------------------------------------------------------------


def test_loss_with_repurchase_inside_30_days_is_flagged_as_a_wash_sale() -> None:
    fills = [
        _fill("o1", 1, date(2026, 2, 1), "XYZ", "buy", "10", "50.00"),
        _fill("o2", 2, date(2026, 2, 20), "XYZ", "sell", "10", "40.00"),
        # 5 days after the loss sale: inside the 61-day (30 before/30 after) window.
        _fill("o3", 3, date(2026, 2, 25), "XYZ", "buy", "10", "42.00"),
    ]

    summary = summarize_paper_tax(fills)

    assert len(summary.wash_sales) == 1
    flag = summary.wash_sales[0]
    assert flag.symbol == "XYZ"
    assert flag.loss_date == date(2026, 2, 20)
    assert flag.repurchase_date == date(2026, 2, 25)
    assert flag.quantity_sold == Decimal("10")
    assert flag.quantity_replaced == Decimal("10")
    # Full replacement of a $100 loss (10 shares * $10/share) disallows the whole loss.
    assert flag.disallowed_amount == Decimal("100.00")
    assert flag.permanently_disallowed is False

    assert summary.disallowed_loss_total == Decimal("100.00")
    # The loss is fully disallowed, so it contributes nothing to the reportable short-term figure.
    assert summary.short_term_gain == Decimal("0")


def test_loss_with_repurchase_on_day_30_is_still_flagged() -> None:
    """IRC §1091's window is inclusive at +30 days -- boundary check distinct from the "outside the
    window" case below, which uses day 31+."""
    fills = [
        _fill("o1", 1, date(2026, 2, 1), "QRS", "buy", "10", "50.00"),
        _fill("o2", 2, date(2026, 2, 20), "QRS", "sell", "10", "40.00"),
        _fill("o3", 3, date(2026, 3, 22), "QRS", "buy", "10", "42.00"),  # exactly +30 days
    ]

    summary = summarize_paper_tax(fills)

    assert len(summary.wash_sales) == 1
    assert summary.wash_sales[0].repurchase_date == date(2026, 3, 22)


# ---------------------------------------------------------------------------
# Case 4: loss + repurchase outside 30 days -> not flagged
# ---------------------------------------------------------------------------


def test_loss_with_repurchase_outside_30_days_is_not_flagged() -> None:
    fills = [
        _fill("o1", 1, date(2026, 1, 1), "ABC", "buy", "10", "50.00"),
        _fill("o2", 2, date(2026, 1, 15), "ABC", "sell", "10", "40.00"),
        # 45 days after the loss sale: well outside the 30-day window.
        _fill("o3", 3, date(2026, 3, 1), "ABC", "buy", "10", "45.00"),
    ]

    summary = summarize_paper_tax(fills)

    assert summary.wash_sales == ()
    assert summary.disallowed_loss_total == Decimal("0")
    # The full loss is realised and reportable: (40 - 50) * 10 = -100.00.
    assert summary.short_term_gain == Decimal("-100.00")


# ---------------------------------------------------------------------------
# Case 5: end-to-end reproduction of the real A-rotation MU pattern
# ---------------------------------------------------------------------------


def test_mu_pattern_sell_at_loss_then_rebuy_two_days_later_is_flagged() -> None:
    """Reproduces a paper-card defect case: MU sold at a loss on 2026-08-19, rebought
    2026-08-21 -- a loss on 5 shares, replaced two days later, which the paper desk showed
    nowhere. `summarize_paper_tax` must flag it exactly as the real tax engine would for a broker
    import of the same trades."""
    fills = [
        _fill("o1", 10, date(2026, 6, 1), "MU", "buy", "5", "250.00"),
        # (101.80 - 250.00) * 5 = -741.00
        _fill("o2", 40, date(2026, 8, 19), "MU", "sell", "5", "101.80"),
        _fill("o3", 41, date(2026, 8, 21), "MU", "buy", "5", "105.00"),
    ]

    summary = summarize_paper_tax(fills)

    assert len(summary.wash_sales) == 1
    flag = summary.wash_sales[0]
    assert flag.symbol == "MU"
    assert flag.loss_date == date(2026, 8, 19)
    assert flag.repurchase_date == date(2026, 8, 21)
    assert flag.disallowed_amount == Decimal("741.00")
    assert flag.quantity_replaced == Decimal("5")

    assert summary.disallowed_loss_total == Decimal("741.00")
    # Fully disallowed: contributes zero to the reportable short-term figure.
    assert summary.short_term_gain == Decimal("0")


# ---------------------------------------------------------------------------
# Purity / determinism
# ---------------------------------------------------------------------------


def test_summarize_paper_tax_is_pure_and_repeatable() -> None:
    """Same fills, called twice (once with the list order reversed) -> identical summary. Nothing in
    this module may depend on call order, wall-clock time, or hidden state."""
    fills = [
        _fill("o1", 1, date(2026, 2, 1), "XYZ", "buy", "10", "50.00"),
        _fill("o2", 2, date(2026, 2, 20), "XYZ", "sell", "10", "40.00"),
        _fill("o3", 3, date(2026, 2, 25), "XYZ", "buy", "10", "42.00"),
    ]

    first = summarize_paper_tax(fills)
    second = summarize_paper_tax(list(reversed(fills)))

    assert first == second


def test_empty_fills_without_explicit_range_raises() -> None:
    """No fills and no explicit `start`/`end` cannot infer a date range without reading the wall
    clock, which this module deliberately never does -- see `summarize_paper_tax`'s docstring."""
    with pytest.raises(ValueError, match="zero fills"):
        summarize_paper_tax([])


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------


def test_explicit_rates_are_used_and_labelled_explicit() -> None:
    fills = [
        _fill("o1", 1, date(2026, 1, 5), "AAPL", "buy", "10", "100.00"),
        _fill("o2", 2, date(2026, 3, 5), "AAPL", "sell", "10", "150.00"),
    ]

    summary = summarize_paper_tax(
        fills, short_term_rate=Decimal("0.24"), long_term_rate=Decimal("0.15")
    )

    assert summary.short_term_rate == Decimal("0.24")
    assert summary.rate_basis == "explicit"
    assert summary.tax_owed == Decimal("120.00")  # 500.00 * 0.24
    assert summary.after_tax_realized_gain == Decimal("380.00")


def test_resolve_configured_rates_falls_back_to_statutory_when_unset() -> None:
    settings = Settings(ordinary_income_tax_rate=None, long_term_capital_gains_tax_rate=None)

    short_rate, long_rate, basis = resolve_configured_rates(settings)

    assert short_rate == STATUTORY_SHORT_TERM_RATE
    assert long_rate == STATUTORY_LONG_TERM_RATE
    assert basis == "statutory_upper_bound"


def test_resolve_configured_rates_uses_the_users_configured_brackets() -> None:
    settings = Settings(ordinary_income_tax_rate=0.22, long_term_capital_gains_tax_rate=0.15)

    short_rate, long_rate, basis = resolve_configured_rates(settings)

    assert short_rate == Decimal("0.22")
    assert long_rate == Decimal("0.15")
    assert basis == "user_configured"


def test_resolve_configured_rates_output_feeds_directly_into_summarize() -> None:
    fills = [
        _fill("o1", 1, date(2026, 1, 5), "AAPL", "buy", "10", "100.00"),
        _fill("o2", 2, date(2026, 3, 5), "AAPL", "sell", "10", "150.00"),
    ]
    settings = Settings(ordinary_income_tax_rate=0.22, long_term_capital_gains_tax_rate=0.15)
    short_rate, long_rate, _basis = resolve_configured_rates(settings)

    summary = summarize_paper_tax(fills, short_term_rate=short_rate, long_term_rate=long_rate)

    assert summary.short_term_rate == Decimal("0.22")
    assert summary.tax_owed == Decimal("110.00")  # 500.00 * 0.22
