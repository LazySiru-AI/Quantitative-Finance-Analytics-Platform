"""Proves the fix for the rejection-detail loss: `PaperBroker` builds a rich, per-order rejection
reason (`app.paper.paperbroker.Rejection.reason`), but until now it was discarded before reaching
the API -- `AgentResult.rejections` kept only the bare rule slug, and `Desk.rejections: list[str]`
echoed that slug once per refused order, so 8 orders refused for insufficient cash across 3 symbols
rendered as the same unlabelled `"insufficient_cash"` string 8 times over, with no dollar figures and
no symbols.

Three layers are exercised, each a real defect surface if the wiring had a gap:

1. `PaperBroker.submit` against a real, tiny-cash mandate -- genuine `Rejection` objects, not
   hand-typed fakes, so the dollar-figure sentences asserted on below are the broker's own, not a
   copy of its f-string that could drift from it unnoticed.
2. `app.tournament.models.RejectionRecord` / `AgentResult.rejection_details` -- the same
   `rule`/`symbol`/`reason` transform `app.tournament.runner.run_card` applies to `broker.rejections`
   (see that function's own `rejection_details=` line), reproduced here rather than imported, so this
   test does not silently stop testing anything if the runner's line is ever refactored out from under
   it.
3. `app.paperdesk.desk._build_desk` -- the actual call site that turns (2) into
   `app.paperdesk.models.Desk.rejections`/`rejection_count`, the exact shape the API ships.

No bars are written to the temp store for the desk-level tests: `_build_desk`'s `_signals` call
degrades a symbol with no stored price to `blocked="no price"` rather than raising (see
`app.paperdesk.desk._signals`), the same tolerance `tests/test_paperdesk.py::TestZeroTradeDesk`
already relies on with an empty store -- so this file only ever writes bars where a real priced
`PaperBroker.submit()` call needs one (layer 1's `fill_date` open).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from app.config import Settings
from app.db import duck
from app.market.models import BAR_COLUMNS, Interval
from app.paper.marketdata import AsOfMarket, clear_frame_cache
from app.paper.paperbroker import REJECTION_LABELS, Mandate, Order, PaperBroker, rejection_label
from app.paperdesk import desk
from app.tournament.allocation import AllocationCard, AllocationResult, Sleeve
from app.tournament.ladder import LadderCard, LadderResult, Rung
from app.tournament.models import (
    DESIGN_THROUGH,
    AgentResult,
    Discipline,
    RejectionRecord,
    StrategyCard,
)

# ---------------------------------------------------------------------------
# Builders -- small, local, mirroring `tests/test_paperdesk.py`'s own (duplicated rather than
# imported -- see that file's module docstring for why this repo prefers that for its test fakes).
# ---------------------------------------------------------------------------


def _mandate(**overrides: object) -> Mandate:
    fields: dict[str, object] = {
        "persona_id": "test-persona",
        "display_name": "Test Persona",
        "account_id": "acct-1",
        "account_label": "Test Account",
        "starting_cash": Decimal("50.00"),
        "allow_fractional_shares": False,
        "max_positions": 10,
        "max_single_name_weight": Decimal("1.00"),
        "min_clip_notional": Decimal("1.00"),
        "min_cash": Decimal("0.00"),
        "settlement_days": 1,
        "slippage_bps": Decimal("0"),
        "commission_per_trade": Decimal("0"),
        "sec_fee_rate": Decimal("0"),
        "taf_per_share": Decimal("0"),
        "taf_cap": Decimal("0"),
    }
    fields.update(overrides)
    return Mandate(**fields)  # type: ignore[arg-type]


def _write_bars(settings: Settings, symbol: str, prices: dict[dt.date, tuple[float, float]]) -> None:
    """Write one daily bar per `(open, close)` in `prices` into `settings`'s temp store. Copied
    verbatim from `tests/test_paperdesk.py`'s own helper of the same name."""
    dates = sorted(prices)
    opens = [prices[d][0] for d in dates]
    closes = [prices[d][1] for d in dates]
    frame = pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC) for d in dates],
                dtype="datetime64[us, UTC]",
            ),
            "open": opens,
            "high": [max(o, c) + 5.0 for o, c in zip(opens, closes, strict=True)],
            "low": [min(o, c) - 5.0 for o, c in zip(opens, closes, strict=True)],
            "close": closes,
            "adj_close": closes,
            "volume": [1_000_000] * len(dates),
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)


def _order(*, order_id: str, symbol: str, quantity: Decimal, decided_on: dt.date) -> Order:
    return Order(
        order_id=order_id,
        session=1,
        decided_on=decided_on,
        symbol=symbol,
        side="buy",
        quantity=quantity,
        thesis="a test thesis, written before the trading window ran",
        invalidation="a test invalidation",
    )


def _ladder_card(**overrides: object) -> LadderCard:
    """A minimal, valid `LadderCard` whose three sleeves are exactly `SYMA`/`SYMB`/`SYMC` -- the same
    three symbols `_run_broker_refusing_eight_orders_for_insufficient_cash` refuses orders against,
    so a ladder desk built from this card and a broker run against it exercises the identical
    real-broker rejection data the rules-card tests above do."""
    fields: dict[str, object] = {
        "agent_id": "ladder-rej-test",
        "display_name": "Ladder rejection test desk",
        "thesis": "a test thesis, written before the trading window ran",
        "signal_symbol": "SPY",
        "defensive_symbol": "SYMA",
        "bond_symbol": "SYMB",
        "leveraged_symbol": "SYMC",
        "base_defensive_weight": Decimal("0.60"),
        "base_bond_weight": Decimal("0.40"),
        "rungs": (Rung(drawdown=Decimal("-0.10"), leveraged_weight=Decimal("0.20")),),
        "confirm_ma": 5,
        "ath_haircut": Decimal("0.5"),
        "recovery_gain": Decimal("0.10"),
        "recovery_sessions": 60,
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return LadderCard(**fields)  # type: ignore[arg-type]


def _allocation_card(**overrides: object) -> AllocationCard:
    """A minimal, valid `AllocationCard` whose sleeves are exactly `SYMA`/`SYMB`/`SYMC` -- the same
    three symbols `_run_broker_refusing_eight_orders_for_insufficient_cash` refuses orders against, so
    an allocation desk built from this card and a broker run against it exercises the identical
    real-broker rejection data the rules-card and ladder-card tests above do."""
    fields: dict[str, object] = {
        "agent_id": "alloc-rej-test",
        "display_name": "Allocation rejection test desk",
        "thesis": "a test thesis, written before the trading window ran",
        "sleeves": (
            Sleeve(symbol="SYMA", target_weight=Decimal("0.34")),
            Sleeve(symbol="SYMB", target_weight=Decimal("0.33")),
            Sleeve(symbol="SYMC", target_weight=Decimal("0.33")),
        ),
        "band_pct": Decimal("0.05"),
        "rules": (),
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return AllocationCard(**fields)  # type: ignore[arg-type]


def _card(**overrides: object) -> StrategyCard:
    fields: dict[str, object] = {
        "agent_id": "rej-test",
        "display_name": "Rejection test desk",
        "discipline": Discipline.MOMENTUM,
        "thesis": "a test thesis, written before the trading window ran",
        "universe": ("SYMA", "SYMB", "SYMC"),
        "entry": "close > 0",
        "exit": "close < 0",
        "stop_loss_pct": None,
        "take_profit_pct": None,
        "max_hold_days": None,
        "max_positions": 6,
        "position_pct": Decimal("0.15"),
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return StrategyCard(**fields)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    desk.clear_cache()
    clear_frame_cache()
    yield
    desk.clear_cache()
    clear_frame_cache()


# ---------------------------------------------------------------------------
# Layer 1+2: a real broker run producing 8 refusals across 3 symbols, transformed the same way
# `app.tournament.runner.run_card` transforms `broker.rejections` into `AgentResult.rejection_details`.
# ---------------------------------------------------------------------------

_DECIDED_ON = dt.date(2026, 3, 2)
_FILL_DATE = dt.date(2026, 3, 3)

#: 8 orders across exactly 3 symbols -- SYMA x3, SYMB x3, SYMC x2 -- with a distinct quantity per
#: order (1..8 shares) so each rejection's dollar figures differ and "newest first" is a real,
#: content-checkable claim rather than 8 copies of the same string.
_SYMBOLS_FOR_EIGHT_ORDERS = ("SYMA", "SYMB", "SYMC", "SYMA", "SYMB", "SYMC", "SYMA", "SYMB")


def _run_broker_refusing_eight_orders_for_insufficient_cash(settings: Settings) -> PaperBroker:
    """A broker with $50 starting cash, asked to buy 8 orders at ~$1,000+ notional each -- every one
    refused under `insufficient_cash` (cash never changes, since nothing ever fills), across the 3
    symbols in `_SYMBOLS_FOR_EIGHT_ORDERS`."""
    for symbol in {"SYMA", "SYMB", "SYMC"}:
        _write_bars(settings, symbol, {_FILL_DATE: (1000.0, 1000.0)})

    broker = PaperBroker(_mandate())
    market = AsOfMarket(as_of=_DECIDED_ON, settings=settings)
    for i, symbol in enumerate(_SYMBOLS_FOR_EIGHT_ORDERS):
        order = _order(
            order_id=f"o{i}", symbol=symbol, quantity=Decimal(i + 1), decided_on=_DECIDED_ON
        )
        outcome = broker.submit(order, market=market, fill_date=_FILL_DATE)
        assert outcome.rule == "insufficient_cash", (  # type: ignore[union-attr]
            f"order {i} ({symbol}) was not refused for insufficient cash: {outcome!r} -- this "
            "test's mandate/price setup no longer produces the scenario it claims to"
        )
    assert len(broker.rejections) == 8
    return broker


def _rejection_details_from(broker: PaperBroker) -> tuple[RejectionRecord, ...]:
    """The exact transform `app.tournament.runner.run_card` applies at its own
    `rejection_details=` line -- reproduced rather than imported so a change to that line that broke
    the contract would still be caught here."""
    return tuple(
        RejectionRecord(rule=r.rule, symbol=r.symbol, reason=r.reason) for r in broker.rejections
    )


class TestRejectionLabelMap:
    def test_every_rule_paperbroker_can_reject_with_has_a_label(self) -> None:
        """The 10 rule slugs `PaperBroker._reject` is actually called with, read off
        `backend/app/paper/paperbroker.py` -- every one must have a human label, not a slug that
        happens to fall through to the humanised fallback."""
        known_rules = {
            "non_positive_quantity",
            "fractional_shares",
            "missing_thesis",
            "missing_invalidation",
            "min_clip",
            "max_positions",
            "insufficient_cash",
            "max_single_name_weight",
            "unpriceable",
            "no_short",
        }
        assert known_rules <= REJECTION_LABELS.keys()
        for rule in known_rules:
            assert rejection_label(rule) == REJECTION_LABELS[rule]

    def test_an_unrecognised_slug_degrades_to_a_readable_label_instead_of_raising(self) -> None:
        """No `assert_never`, no raise: a rule this map has not caught up with yet must still render
        as something readable -- see `rejection_label`'s own docstring."""
        assert rejection_label("some_future_rule") == "Some future rule"
        assert rejection_label("") == ""


class TestGroupRejectionsCollapsesPerOrderRefusalsIntoOneGroupPerRule:
    def test_eight_orders_three_symbols_one_rule_groups_to_one_entry_with_real_dollar_detail(
        self, settings: Settings
    ) -> None:
        """The scenario the fix exists for: 8 buy orders refused for insufficient cash across 3
        symbols must become ONE `DeskRejection` with `count == 8`, 3 distinct `symbols`, and 8 real
        dollar-figure `detail` sentences -- not 8 repeats of the bare slug."""
        broker = _run_broker_refusing_eight_orders_for_insufficient_cash(settings)
        rejection_details = _rejection_details_from(broker)

        groups, total = desk._group_rejections(rejection_details)

        assert total == 8
        assert len(groups) == 1
        group = groups[0]
        assert group.rule == "insufficient_cash"
        assert group.label == "Insufficient settled cash"
        assert group.count == 8
        assert group.symbols == ["SYMA", "SYMB", "SYMC"]
        assert len(group.detail) == 8

        # Every detail sentence is the broker's own reason, not the bare slug -- dollar figures and
        # the "settled cash" phrase from `PaperBroker._check_buy`'s own f-string.
        for sentence in group.detail:
            assert "$" in sentence
            assert "settled cash" in sentence
            assert sentence != "insufficient_cash"

        # Newest first: order 7 (SYMB, 8 shares, $8000.00 gross) was appended last and must lead;
        # order 0 (SYMA, 1 share, $1000.00 gross) was appended first and must trail.
        assert "$8000.00" in group.detail[0]
        assert "$1000.00" in group.detail[-1]

    def test_bare_rule_only_input_still_groups_with_a_label_but_empty_symbols(self) -> None:
        """`LadderResult`/`AllocationResult` (out of this change's scope -- see
        `app.tournament.ladder`/`app.tournament.allocation`) only ever recorded the bare rule slug,
        never the symbol or reason. `_group_rejections`'s `bare_rules` path must still group and
        label correctly, degrading `symbols` to empty and `detail` to the label rather than
        fabricating data that was never recorded."""
        groups, total = desk._group_rejections(
            None, bare_rules=["max_positions", "max_positions", "no_short"]
        )

        assert total == 3
        assert [g.rule for g in groups] == ["max_positions", "no_short"]
        max_positions_group = groups[0]
        assert max_positions_group.count == 2
        assert max_positions_group.symbols == []
        assert max_positions_group.label == "Max positions reached"
        assert max_positions_group.detail == ["Max positions reached", "Max positions reached"]

    def test_groups_sort_by_count_descending_then_rule_ascending(self) -> None:
        records = (
            *(RejectionRecord(rule="no_short", symbol="AAA", reason="r") for _ in range(2)),
            *(RejectionRecord(rule="max_positions", symbol="BBB", reason="r") for _ in range(5)),
            *(RejectionRecord(rule="min_clip", symbol="CCC", reason="r") for _ in range(2)),
        )
        groups, total = desk._group_rejections(records)
        assert total == 9
        assert [g.rule for g in groups] == ["max_positions", "min_clip", "no_short"]
        assert [g.count for g in groups] == [5, 2, 2]

    def test_detail_is_capped_at_twenty_newest_first(self) -> None:
        records = tuple(
            RejectionRecord(rule="insufficient_cash", symbol="AAA", reason=f"reason {i}")
            for i in range(25)
        )
        groups, total = desk._group_rejections(records)
        assert total == 25
        assert groups[0].count == 25
        assert len(groups[0].detail) == 20
        # Newest first, capped -- the 20 most recently appended (indices 24 down to 5).
        assert groups[0].detail[0] == "reason 24"
        assert groups[0].detail[-1] == "reason 5"

    def test_no_rejections_is_an_empty_list_and_zero_count(self) -> None:
        groups, total = desk._group_rejections(())
        assert groups == []
        assert total == 0


class TestDeskRejectionsReachesTheDeskModel:
    def test_build_desk_groups_the_real_broker_run_into_desk_rejections(
        self, settings: Settings
    ) -> None:
        """End-to-end through the actual call site: `desk._build_desk` -- the same function
        `app.paperdesk.desk.state()` calls for every rules-card desk -- must turn
        `AgentResult.rejection_details` into `Desk.rejections`/`Desk.rejection_count` with the exact
        contract `app.paperdesk.models.DeskRejection` declares."""
        broker = _run_broker_refusing_eight_orders_for_insufficient_cash(settings)
        rejection_details = _rejection_details_from(broker)
        card = _card()
        result = AgentResult(
            card=card,
            sessions=1,
            starting_equity=Decimal("50.00"),
            ending_equity=Decimal("50.00"),
            total_return=Decimal("0"),
            max_drawdown=Decimal("0"),
            trades=(),
            rejections=tuple(r.rule for r in broker.rejections),
            rejection_details=rejection_details,
            benchmark_return=None,
        )
        window = desk._Window(
            inception=_FILL_DATE,
            first_session=_FILL_DATE,
            as_of=_FILL_DATE,
            decided_on=_DECIDED_ON,
            sessions=1,
            latest_bar=_FILL_DATE,
        )

        built = desk._build_desk(card, result, settings=settings, window=window)

        assert built.rejection_count == 8
        assert len(built.rejections) == 1
        group = built.rejections[0]
        assert group.rule == "insufficient_cash"
        assert group.label == "Insufficient settled cash"
        assert group.count == 8
        assert group.symbols == ["SYMA", "SYMB", "SYMC"]
        assert len(group.detail) == 8
        assert all("$" in sentence for sentence in group.detail)

        # Round-trips through pydantic's own JSON encoding the same way the API response does.
        payload = built.model_dump(mode="json")
        assert payload["rejection_count"] == 8
        assert payload["rejections"] == [
            {
                "rule": "insufficient_cash",
                "label": "Insufficient settled cash",
                "count": 8,
                "symbols": ["SYMA", "SYMB", "SYMC"],
                "detail": group.detail,
            }
        ]

    def test_zero_rejections_is_an_empty_list_and_zero_count(self, settings: Settings) -> None:
        card = _card()
        result = AgentResult(
            card=card,
            sessions=1,
            starting_equity=Decimal("50.00"),
            ending_equity=Decimal("50.00"),
            total_return=Decimal("0"),
            max_drawdown=Decimal("0"),
            trades=(),
            rejections=(),
            rejection_details=(),
            benchmark_return=None,
        )
        window = desk._Window(
            inception=_FILL_DATE,
            first_session=_FILL_DATE,
            as_of=_FILL_DATE,
            decided_on=_DECIDED_ON,
            sessions=1,
            latest_bar=_FILL_DATE,
        )

        built = desk._build_desk(card, result, settings=settings, window=window)

        assert built.rejections == []
        assert built.rejection_count == 0


class TestLadderDeskRejectionsCarryRealDetail:
    """The ladder counterpart to `TestDeskRejectionsReachesTheDeskModel` above. Before this change,
    `_build_ladder_desk` called `_group_rejections(None, bare_rules=result.rejections)` -- the
    degraded fallback -- so a ladder desk's `Desk.rejections` always showed an empty `symbols` list
    and a `detail` of the bare rule label repeated once per refused order, no matter how rich
    `LadderResult.rejection_details` actually was. This proves the real call site now reads
    `result.rejection_details` and reaches `Desk.rejections` with genuine per-order symbols and
    dollar-figure detail sentences, the same as the rules path."""

    def test_build_ladder_desk_groups_the_real_broker_run_into_desk_rejections(
        self, settings: Settings
    ) -> None:
        broker = _run_broker_refusing_eight_orders_for_insufficient_cash(settings)
        rejection_details = _rejection_details_from(broker)
        card = _ladder_card()
        result = LadderResult(
            card=card,
            sessions=1,
            starting_equity=Decimal("50.00"),
            ending_equity=Decimal("50.00"),
            total_return=Decimal("0"),
            max_drawdown=Decimal("0"),
            trades=(),
            rejections=tuple(r.rule for r in broker.rejections),
            rejection_details=rejection_details,
            benchmark_return=None,
        )
        window = desk._Window(
            inception=_FILL_DATE,
            first_session=_FILL_DATE,
            as_of=_FILL_DATE,
            decided_on=_DECIDED_ON,
            sessions=1,
            latest_bar=_FILL_DATE,
        )

        built = desk._build_ladder_desk(card, result, settings=settings, window=window)

        assert built.kind == "ladder"
        assert built.rejection_count == 8
        assert len(built.rejections) == 1
        group = built.rejections[0]
        assert group.rule == "insufficient_cash"
        assert group.label == "Insufficient settled cash"
        assert group.count == 8
        # The defect: this used to be `[]` (the `bare_rules` fallback never records a symbol).
        assert group.symbols == ["SYMA", "SYMB", "SYMC"]
        assert len(group.detail) == 8
        # The defect: this used to be 8 copies of the bare label ("Insufficient settled cash"), with
        # no dollar figures. Now it is the broker's own per-order reason sentence.
        for sentence in group.detail:
            assert "$" in sentence
            assert "settled cash" in sentence
            assert sentence != "Insufficient settled cash"

        payload = built.model_dump(mode="json")
        assert payload["rejection_count"] == 8
        assert payload["rejections"] == [
            {
                "rule": "insufficient_cash",
                "label": "Insufficient settled cash",
                "count": 8,
                "symbols": ["SYMA", "SYMB", "SYMC"],
                "detail": group.detail,
            }
        ]

    def test_zero_ladder_rejections_is_an_empty_list_and_zero_count(
        self, settings: Settings
    ) -> None:
        card = _ladder_card()
        result = LadderResult(
            card=card,
            sessions=1,
            starting_equity=Decimal("50.00"),
            ending_equity=Decimal("50.00"),
            total_return=Decimal("0"),
            max_drawdown=Decimal("0"),
            trades=(),
            rejections=(),
            rejection_details=(),
            benchmark_return=None,
        )
        window = desk._Window(
            inception=_FILL_DATE,
            first_session=_FILL_DATE,
            as_of=_FILL_DATE,
            decided_on=_DECIDED_ON,
            sessions=1,
            latest_bar=_FILL_DATE,
        )

        built = desk._build_ladder_desk(card, result, settings=settings, window=window)

        assert built.rejections == []
        assert built.rejection_count == 0


class TestAllocationDeskRejectionsCarryRealDetail:
    """The allocation counterpart to `TestDeskRejectionsReachesTheDeskModel` and
    `TestLadderDeskRejectionsCarryRealDetail` above. Before this change, `_build_allocation_desk`
    called `_group_rejections(None, bare_rules=result.rejections)` -- the degraded fallback -- so an
    allocation desk's `Desk.rejections` always showed an empty `symbols` list and a `detail` of the
    bare rule label repeated once per refused order, no matter how rich a real broker run's rejections
    actually were. This proves the real call site now reads `result.rejection_details` and reaches
    `Desk.rejections` with genuine per-order symbols and dollar-figure detail sentences, the same as
    the rules and ladder paths."""

    def test_build_allocation_desk_groups_the_real_broker_run_into_desk_rejections(
        self, settings: Settings
    ) -> None:
        broker = _run_broker_refusing_eight_orders_for_insufficient_cash(settings)
        rejection_details = _rejection_details_from(broker)
        card = _allocation_card()
        result = AllocationResult(
            card=card,
            sessions=1,
            starting_equity=Decimal("50.00"),
            ending_equity=Decimal("50.00"),
            total_return=Decimal("0"),
            max_drawdown=Decimal("0"),
            trades=(),
            rejections=tuple(r.rule for r in broker.rejections),
            rejection_details=rejection_details,
            benchmark_return=None,
        )
        window = desk._Window(
            inception=_FILL_DATE,
            first_session=_FILL_DATE,
            as_of=_FILL_DATE,
            decided_on=_DECIDED_ON,
            sessions=1,
            latest_bar=_FILL_DATE,
        )

        built = desk._build_allocation_desk(card, result, settings=settings, window=window)

        assert built.kind == "allocation"
        assert built.rejection_count == 8
        assert len(built.rejections) == 1
        group = built.rejections[0]
        assert group.rule == "insufficient_cash"
        assert group.label == "Insufficient settled cash"
        assert group.count == 8
        # The defect: this used to be `[]` (the `bare_rules` fallback never records a symbol).
        assert group.symbols == ["SYMA", "SYMB", "SYMC"]
        assert len(group.detail) == 8
        # The defect: this used to be 8 copies of the bare label ("Insufficient settled cash"), with
        # no dollar figures. Now it is the broker's own per-order reason sentence.
        for sentence in group.detail:
            assert "$" in sentence
            assert "settled cash" in sentence
            assert sentence != "Insufficient settled cash"

        payload = built.model_dump(mode="json")
        assert payload["rejection_count"] == 8
        assert payload["rejections"] == [
            {
                "rule": "insufficient_cash",
                "label": "Insufficient settled cash",
                "count": 8,
                "symbols": ["SYMA", "SYMB", "SYMC"],
                "detail": group.detail,
            }
        ]

    def test_zero_allocation_rejections_is_an_empty_list_and_zero_count(
        self, settings: Settings
    ) -> None:
        card = _allocation_card()
        result = AllocationResult(
            card=card,
            sessions=1,
            starting_equity=Decimal("50.00"),
            ending_equity=Decimal("50.00"),
            total_return=Decimal("0"),
            max_drawdown=Decimal("0"),
            trades=(),
            rejections=(),
            rejection_details=(),
            benchmark_return=None,
        )
        window = desk._Window(
            inception=_FILL_DATE,
            first_session=_FILL_DATE,
            as_of=_FILL_DATE,
            decided_on=_DECIDED_ON,
            sessions=1,
            latest_bar=_FILL_DATE,
        )

        built = desk._build_allocation_desk(card, result, settings=settings, window=window)

        assert built.rejections == []
        assert built.rejection_count == 0
