"""Tests for the tax-aware strategy-switch gate.

Fixtures are constructed directly -- no network, no real bar store, matching the rest of this
module's own "pure function of its arguments" style. Rates are pinned via an explicit `Settings`
instance so a test run is never at the mercy of environment-configured tax rates.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.config import Settings
from app.workflow.taxcheck import (
    MIN_DAYS_BETWEEN_SWITCHES,
    PositionLot,
    RecentSale,
    TargetCardSpec,
    evaluate_switch,
)

TODAY = dt.date(2026, 8, 30)
ADOPTED_LONG_AGO = TODAY - dt.timedelta(days=90)


@pytest.fixture
def settings() -> Settings:
    """Pinned statutory rates, so the gate's tax-cost arithmetic never depends on the environment
    this test happens to run in."""
    return Settings(ordinary_income_tax_rate=0.37, long_term_capital_gains_tax_rate=0.20)


def _lot(
    symbol: str,
    *,
    quantity: Decimal | int = 100,
    cost_basis: Decimal | int,
    acquired_date: dt.date,
    current_price: Decimal | int,
    is_tax_advantaged: bool = False,
) -> PositionLot:
    return PositionLot(
        symbol=symbol,
        quantity=Decimal(quantity),
        cost_basis=Decimal(cost_basis),
        acquired_date=acquired_date,
        current_price=Decimal(current_price),
        is_tax_advantaged=is_tax_advantaged,
    )


# ---------------------------------------------------------------------------
# 1. Clean switch, no positions
# ---------------------------------------------------------------------------


def test_clean_switch_with_no_positions_is_allowed(settings: Settings) -> None:
    verdict = evaluate_switch(
        positions=(),
        target_card=TargetCardSpec(card_id="card-b", universe=frozenset({"MSFT"})),
        incumbent_card_id="card-a",
        today=TODAY,
        card_adopted_date=ADOPTED_LONG_AGO,
        settings=settings,
    )
    assert verdict.allowed is True
    assert verdict.outcome == "allowed"
    assert verdict.projected_wash_disallowance == 0
    assert verdict.st_premium_cost == 0
    assert verdict.days_to_long_term == ()
    assert "card-a" in verdict.reason and "card-b" in verdict.reason


# ---------------------------------------------------------------------------
# 2. Wash sale: loss position repurchased inside the 30-day window
# ---------------------------------------------------------------------------


def test_loss_position_repurchased_inside_wash_window_is_blocked(settings: Settings) -> None:
    # Two lots of the same symbol: one bought 45 days ago and now sitting on a loss, one bought 10
    # days ago (inside the +/-30 day window measured from today's projected sale). Both are being
    # liquidated because MU is not in the target card's universe, so both generate a SELL -- but the
    # second lot's own BUY is still a valid replacement purchase for the first lot's loss regardless
    # of it also being sold today.
    loss_lot = _lot(
        "MU",
        quantity=100,
        cost_basis=10_000,
        acquired_date=TODAY - dt.timedelta(days=45),
        current_price=80,  # 100 * 80 = 8,000 proceeds vs 10,000 basis -> a $2,000 loss
    )
    recent_buy_lot = _lot(
        "MU",
        quantity=20,
        cost_basis=1_800,
        acquired_date=TODAY - dt.timedelta(days=10),
        current_price=80,
    )
    verdict = evaluate_switch(
        positions=(loss_lot, recent_buy_lot),
        target_card=TargetCardSpec(card_id="card-b", universe=frozenset({"MSFT"})),
        incumbent_card_id="card-a",
        today=TODAY,
        card_adopted_date=ADOPTED_LONG_AGO,
        settings=settings,
    )
    assert verdict.allowed is False
    assert verdict.outcome == "blocked_wash_sale"
    assert verdict.projected_wash_disallowance > 0
    # 20 of the 100 loss shares are replaced -> 20% of the $2,000 loss is disallowed.
    assert verdict.projected_wash_disallowance == Decimal("400.00")
    assert "MU" in verdict.reason
    assert "1091" in verdict.reason


def test_wash_sale_via_recent_sale_repurchased_by_target_universe_is_blocked(
    settings: Settings,
) -> None:
    """The forward direction of the rule: a symbol not currently held, sold at a loss recently, that
    the target card's universe would newly buy back inside the window."""
    recent_sale = RecentSale(
        symbol="TSLA",
        sale_date=TODAY - dt.timedelta(days=10),
        quantity=Decimal(10),
        loss_amount=Decimal(500),
    )
    verdict = evaluate_switch(
        positions=(),
        target_card=TargetCardSpec(card_id="card-b", universe=frozenset({"TSLA"})),
        incumbent_card_id="card-a",
        today=TODAY,
        card_adopted_date=ADOPTED_LONG_AGO,
        settings=settings,
        recent_sales=(recent_sale,),
    )
    assert verdict.allowed is False
    assert verdict.outcome == "blocked_wash_sale"
    assert verdict.projected_wash_disallowance == Decimal("500.00")
    assert "TSLA" in verdict.reason


def test_recent_sale_outside_window_does_not_block(settings: Settings) -> None:
    """The same forward case, but the recent sale is old enough that its window has closed -- no
    disallowance, no block."""
    recent_sale = RecentSale(
        symbol="TSLA",
        sale_date=TODAY - dt.timedelta(days=45),
        quantity=Decimal(10),
        loss_amount=Decimal(500),
    )
    verdict = evaluate_switch(
        positions=(),
        target_card=TargetCardSpec(card_id="card-b", universe=frozenset({"TSLA"})),
        incumbent_card_id="card-a",
        today=TODAY,
        card_adopted_date=ADOPTED_LONG_AGO,
        settings=settings,
        recent_sales=(recent_sale,),
    )
    assert verdict.allowed is True
    assert verdict.outcome == "allowed"


# ---------------------------------------------------------------------------
# 3 & 4. Near-long-term block, and the cap that gates it
# ---------------------------------------------------------------------------


def _near_long_term_lot(unrealized_gain: Decimal) -> PositionLot:
    """A lot acquired so its one-year anniversary falls exactly 20 days after `TODAY` -- inside the
    45-day horizon -- with a cost basis chosen to produce the requested unrealized gain at a $600
    current price."""
    acquired_date = TODAY - dt.timedelta(days=345)
    assert (acquired_date.replace(year=acquired_date.year + 1) - TODAY).days == 20
    quantity = Decimal(10)
    current_price = Decimal(600)
    market_value = quantity * current_price
    cost_basis = market_value - unrealized_gain
    return PositionLot(
        symbol="NVDA",
        quantity=quantity,
        cost_basis=cost_basis,
        acquired_date=acquired_date,
        current_price=current_price,
    )


def test_near_long_term_gain_above_cost_cap_is_blocked(settings: Settings) -> None:
    # $5,000 unrealized gain, 20 days short of long-term. Short-vs-long premium = 5,000 * (0.37-0.20)
    # = $850, versus a 1% cap on the $6,000 position value ($60) -- comfortably over the cap.
    lot = _near_long_term_lot(unrealized_gain=Decimal(5_000))
    verdict = evaluate_switch(
        positions=(lot,),
        target_card=TargetCardSpec(card_id="card-b", universe=frozenset()),  # NVDA not kept
        incumbent_card_id="card-a",
        today=TODAY,
        card_adopted_date=ADOPTED_LONG_AGO,
        settings=settings,
    )
    assert verdict.allowed is False
    assert verdict.outcome == "blocked_near_long_term"
    assert verdict.st_premium_cost > 0
    assert verdict.st_premium_cost == Decimal("850.00")
    assert len(verdict.days_to_long_term) == 1
    horizon_lot = verdict.days_to_long_term[0]
    assert horizon_lot.symbol == "NVDA"
    assert horizon_lot.days_remaining == 20
    assert horizon_lot.unrealized_gain == Decimal(5_000)
    assert "NVDA" in verdict.reason
    assert "20 day" in verdict.reason


def test_near_long_term_gain_below_cost_cap_is_allowed(settings: Settings) -> None:
    # Same 20-days-to-anniversary lot, but a $50 gain: premium = 50 * 0.17 = $8.50, versus the same
    # $60 cap -- under the cap, so the horizon alone must not block the switch.
    lot = _near_long_term_lot(unrealized_gain=Decimal(50))
    verdict = evaluate_switch(
        positions=(lot,),
        target_card=TargetCardSpec(card_id="card-b", universe=frozenset()),
        incumbent_card_id="card-a",
        today=TODAY,
        card_adopted_date=ADOPTED_LONG_AGO,
        settings=settings,
    )
    assert verdict.allowed is True
    assert verdict.outcome == "allowed"
    assert verdict.st_premium_cost == 0
    assert verdict.days_to_long_term == ()


def test_near_long_term_gain_already_past_horizon_is_not_priced(settings: Settings) -> None:
    """A gain lot far from its anniversary (well outside LONG_TERM_HORIZON_DAYS) is not even
    examined for the cap, however large the gain."""
    acquired_date = TODAY - dt.timedelta(days=30)  # ~335 days to the anniversary
    lot = PositionLot(
        symbol="NVDA",
        quantity=Decimal(10),
        cost_basis=Decimal(1_000),
        acquired_date=acquired_date,
        current_price=Decimal(600),  # large unrealized gain, but nowhere near long-term
    )
    verdict = evaluate_switch(
        positions=(lot,),
        target_card=TargetCardSpec(card_id="card-b", universe=frozenset()),
        incumbent_card_id="card-a",
        today=TODAY,
        card_adopted_date=ADOPTED_LONG_AGO,
        settings=settings,
    )
    assert verdict.allowed is True
    assert verdict.days_to_long_term == ()


# ---------------------------------------------------------------------------
# 5. Churn limiter
# ---------------------------------------------------------------------------


def test_switch_two_days_after_adoption_with_unchanged_regime_is_blocked_by_churn(
    settings: Settings,
) -> None:
    verdict = evaluate_switch(
        positions=(),
        target_card=TargetCardSpec(card_id="card-b", universe=frozenset()),
        incumbent_card_id="card-a",
        today=TODAY,
        card_adopted_date=TODAY - dt.timedelta(days=2),
        settings=settings,
        regime_changed=False,
    )
    assert verdict.allowed is False
    assert verdict.outcome == "blocked_churn"
    assert "card-a" in verdict.reason
    assert str(MIN_DAYS_BETWEEN_SWITCHES) in verdict.reason


def test_same_switch_two_days_after_adoption_with_changed_regime_is_allowed(
    settings: Settings,
) -> None:
    verdict = evaluate_switch(
        positions=(),
        target_card=TargetCardSpec(card_id="card-b", universe=frozenset()),
        incumbent_card_id="card-a",
        today=TODAY,
        card_adopted_date=TODAY - dt.timedelta(days=2),
        settings=settings,
        regime_changed=True,
    )
    assert verdict.allowed is True
    assert verdict.outcome == "allowed"


def test_switch_exactly_at_min_days_boundary_with_unchanged_regime_is_allowed(
    settings: Settings,
) -> None:
    """MIN_DAYS_BETWEEN_SWITCHES itself is the boundary: exactly that many days is enough, one day
    short is not (covered by the two-days-after-adoption test above)."""
    verdict = evaluate_switch(
        positions=(),
        target_card=TargetCardSpec(card_id="card-b", universe=frozenset()),
        incumbent_card_id="card-a",
        today=TODAY,
        card_adopted_date=TODAY - dt.timedelta(days=MIN_DAYS_BETWEEN_SWITCHES),
        settings=settings,
        regime_changed=False,
    )
    assert verdict.allowed is True
    assert verdict.outcome == "allowed"


# ---------------------------------------------------------------------------
# 6. Overlap: a symbol the target card's universe also holds is not a liquidation
# ---------------------------------------------------------------------------


def test_symbol_kept_by_target_universe_is_not_counted_as_liquidation_cost(
    settings: Settings,
) -> None:
    """The same near-long-term, above-cap lot from the blocking test above -- but NVDA is now in the
    target card's universe, so it is kept rather than liquidated and must not trigger any block."""
    lot = _near_long_term_lot(unrealized_gain=Decimal(5_000))
    verdict = evaluate_switch(
        positions=(lot,),
        target_card=TargetCardSpec(card_id="card-b", universe=frozenset({"NVDA"})),
        incumbent_card_id="card-a",
        today=TODAY,
        card_adopted_date=ADOPTED_LONG_AGO,
        settings=settings,
    )
    assert verdict.allowed is True
    assert verdict.outcome == "allowed"
    assert verdict.st_premium_cost == 0
    assert verdict.days_to_long_term == ()


def test_overlap_symbol_also_excluded_from_wash_sale_projection(settings: Settings) -> None:
    """A symbol kept by the target card is never sold, so it cannot itself be the loss side of a
    projected wash sale, even if a second lot of the same symbol was bought inside the window."""
    loss_lot = _lot(
        "MU",
        quantity=100,
        cost_basis=10_000,
        acquired_date=TODAY - dt.timedelta(days=45),
        current_price=80,
    )
    recent_buy_lot = _lot(
        "MU",
        quantity=20,
        cost_basis=1_800,
        acquired_date=TODAY - dt.timedelta(days=10),
        current_price=80,
    )
    verdict = evaluate_switch(
        positions=(loss_lot, recent_buy_lot),
        target_card=TargetCardSpec(card_id="card-b", universe=frozenset({"MU"})),
        incumbent_card_id="card-a",
        today=TODAY,
        card_adopted_date=ADOPTED_LONG_AGO,
        settings=settings,
    )
    assert verdict.allowed is True
    assert verdict.outcome == "allowed"
    assert verdict.projected_wash_disallowance == 0
