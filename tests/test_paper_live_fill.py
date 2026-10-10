"""Tests for the live-quote fill seam: `PaperBroker.submit`'s `live_quote_source`/`today` parameters
(`backend/app/paper/paperbroker.py`) and the paper desk's cache-safety response to
`Settings.paperdesk_live_fills` (`backend/app/paperdesk/desk.py`).

**Premise, verified before any of this was written (see the shard report for the full account):**
`app.paperdesk.desk._trading_window` bounds every session's own trading window at the newest
*stored* bar (`window.as_of == window.latest_bar`), and `app.tournament.runner.run_card` builds its
own `SessionCalendar` over the identical `(inception, end=window.as_of)` range -- a session can only
exist for a date the benchmark actually has a stored bar for. The session decided on the newest
stored close and meant to fill at the *following* session's open is therefore never constructed at
all today: no `Rejection` is ever produced for it, it simply never runs, and waits for the next
`/api/market/sync` to pull in tomorrow's bar. This file's first two test classes exercise
`PaperBroker.submit` directly, at the layer where the fix actually lives.

**Never hits the real network.** `_StubLiveQuoteSource` below is a plain in-memory fake implementing
`app.market.live.LiveQuoteSource`'s two-method protocol (`snapshot`, `close`) -- no `PollingQuoteSource`,
no `httpx`, no Yahoo. `app.market.live` itself already has 36 tests of its own; this file only proves
`PaperBroker` and `app.paperdesk.desk` consume that module's real dataclasses correctly.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from app.config import Settings
from app.db import duck
from app.market.live import LiveQuote, LiveQuoteError, LiveSnapshot
from app.market.models import BAR_COLUMNS, Interval
from app.paper.marketdata import AsOfMarket, clear_frame_cache
from app.paper.paperbroker import Mandate, Order, PaperBroker
from app.paperdesk import desk
from app.tournament.models import DESIGN_THROUGH, AgentResult, Discipline, StrategyCard

# ---------------------------------------------------------------------------
# Builders -- small, local, mirroring tests/test_paperdesk_rejections.py's own (this repo's
# established convention for these test fakes -- see that file's module docstring).
# ---------------------------------------------------------------------------


def _mandate(**overrides: object) -> Mandate:
    fields: dict[str, object] = {
        "persona_id": "test-persona",
        "display_name": "Test Persona",
        "account_id": "acct-1",
        "account_label": "Test Account",
        "starting_cash": Decimal("100000.00"),
        "allow_fractional_shares": False,
        "max_positions": 10,
        "max_single_name_weight": Decimal("1.00"),
        "min_clip_notional": Decimal("1.00"),
        "min_cash": Decimal("0.00"),
        "settlement_days": 1,
        "slippage_bps": Decimal("50"),  # 0.5% -- large enough that slippage applied is unmissable
        "commission_per_trade": Decimal("0"),
        "sec_fee_rate": Decimal("0"),
        "taf_per_share": Decimal("0"),
        "taf_cap": Decimal("0"),
    }
    fields.update(overrides)
    return Mandate(**fields)  # type: ignore[arg-type]


def _order(*, order_id: str = "o1", symbol: str, decided_on: dt.date) -> Order:
    return Order(
        order_id=order_id,
        session=1,
        decided_on=decided_on,
        symbol=symbol,
        side="buy",
        quantity=Decimal(1),
        thesis="a test thesis",
        invalidation="a test invalidation",
    )


def _write_bar(settings: Settings, symbol: str, day: dt.date, *, open_: float, close: float) -> None:
    """One daily bar. Copied in spirit from tests/test_paperdesk_rejections.py's `_write_bars`."""
    frame = pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(day, dt.time.min, tzinfo=dt.UTC)],
                dtype="datetime64[us, UTC]",
            ),
            "open": [open_],
            "high": [max(open_, close) + 5.0],
            "low": [min(open_, close) - 5.0],
            "close": [close],
            "adj_close": [close],
            "volume": [1_000_000],
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)


class _StubLiveQuoteSource:
    """A fake `app.market.live.LiveQuoteSource` -- no network, ever. Records every `snapshot` call
    so a test can prove the live path was (or, just as importantly, was *not*) consulted."""

    def __init__(self, prices: dict[str, Decimal]) -> None:
        self._prices = prices
        self.calls: list[tuple[str, ...]] = []

    def snapshot(self, symbols: list[str]) -> LiveSnapshot:
        self.calls.append(tuple(symbols))
        now = dt.datetime.now(dt.UTC)
        quotes: list[LiveQuote] = []
        errors: list[LiveQuoteError] = []
        for symbol in symbols:
            price = self._prices.get(symbol.upper())
            if price is None:
                errors.append(LiveQuoteError(symbol=symbol, message="no stub price configured"))
                continue
            quotes.append(
                LiveQuote(
                    symbol=symbol.upper(),
                    price=price,
                    previous_close=None,
                    change=None,
                    change_pct=None,
                    ts=now,
                    stale=False,
                    source="stub",
                )
            )
        return LiveSnapshot(
            as_of=now,
            market_state="REGULAR",
            transport="poll",
            healthy=True,
            quotes=tuple(quotes),
            errors=tuple(errors),
        )

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    desk.clear_cache()
    clear_frame_cache()
    yield
    desk.clear_cache()
    clear_frame_cache()


# ---------------------------------------------------------------------------
# PaperBroker.submit -- the seam itself
# ---------------------------------------------------------------------------

_DECIDED_ON = dt.date(2026, 8, 28)
_TODAY = dt.date(2026, 8, 29)
_FUTURE_FILL_DATE = dt.date(2026, 8, 30)  # >= _TODAY, no stored bar -- the scenario this shard fixes
_PAST_FILL_DATE = dt.date(2020, 1, 2)  # < _TODAY, no stored bar -- a genuine, unrelated data gap


class TestFlagOffReproducesTodaysBehaviourExactly:
    """No `live_quote_source` is ever passed -- which is what every existing caller does today, and
    what happens throughout the application while `Settings.paperdesk_live_fills` is at its default
    `False`, since nothing wires a source in while it is off. This is the byte-identical-behaviour
    claim, proven directly at the one call site the feature touches."""

    def test_missing_bar_for_a_future_fill_date_still_rejects_unpriceable_without_a_live_source(
        self, settings: Settings
    ) -> None:
        broker = PaperBroker(_mandate())
        market = AsOfMarket(as_of=_DECIDED_ON, settings=settings)
        order = _order(symbol="NOSOURCE", decided_on=_DECIDED_ON)

        outcome = broker.submit(order, market=market, fill_date=_FUTURE_FILL_DATE)

        assert outcome.rule == "unpriceable"  # type: ignore[union-attr]
        assert "no stored open for NOSOURCE on 2026-08-30" in outcome.reason  # type: ignore[union-attr]
        assert "the order cannot be filled at a price that was ever real" in outcome.reason  # type: ignore[union-attr]
        assert broker.fills == []

    def test_a_real_historical_fill_still_carries_price_source_stored_open(
        self, settings: Settings
    ) -> None:
        """The ordinary path -- a stored open exists -- untouched by any of this shard's new
        parameters, and the new `Fill.price_source` field defaults exactly as documented."""
        decided_on = dt.date(2026, 3, 2)
        fill_date = dt.date(2026, 3, 3)
        # A close near `decided_on` too, within `market.close`'s 30-day lookback -- otherwise
        # `_check_buy`'s weight-cap sizing (a different, unrelated `unpriceable` path) rejects first.
        _write_bar(settings, "HIST", decided_on, open_=99.00, close=99.50)
        _write_bar(settings, "HIST", fill_date, open_=100.00, close=101.00)
        broker = PaperBroker(_mandate())
        market = AsOfMarket(as_of=decided_on, settings=settings)
        order = _order(symbol="HIST", decided_on=decided_on)

        outcome = broker.submit(order, market=market, fill_date=fill_date)

        assert isinstance(outcome, type(broker.fills[0]))
        assert outcome.price_source == "stored_open"  # type: ignore[union-attr]
        # slippage_bps=50 (0.5%) applied to a $100.00 open, buy side: 100.00 * 1.005 = 100.50
        assert outcome.price == Decimal("100.50")  # type: ignore[union-attr]
        assert outcome.reference_open == Decimal("100.00")  # type: ignore[union-attr]
        payload = outcome.to_json()  # type: ignore[union-attr]
        assert payload["price_source"] == "stored_open"
        # Every pre-existing key is still present -- a key was added, never renamed or removed.
        for key in (
            "order_id", "session", "trade_date", "symbol", "side", "quantity", "price",
            "reference_open", "gross", "fees", "cash_delta",
        ):
            assert key in payload


class TestPastDatedMissingBarStillRejectsEvenWithALiveSourceAvailable:
    """A `fill_date` that has already happened is a genuine hole in the store, not a bar that simply
    has not arrived yet -- collapsing the two would silently turn a real data gap into a live fill.
    The live source must not even be consulted."""

    def test_rejects_unpriceable_and_never_calls_the_live_source(self, settings: Settings) -> None:
        broker = PaperBroker(_mandate())
        market = AsOfMarket(as_of=dt.date(2019, 12, 30), settings=settings)
        order = _order(symbol="STALE", decided_on=dt.date(2019, 12, 30))
        stub = _StubLiveQuoteSource({"STALE": Decimal("42.00")})

        outcome = broker.submit(
            order,
            market=market,
            fill_date=_PAST_FILL_DATE,
            live_quote_source=stub,
            today=_TODAY,
        )

        assert outcome.rule == "unpriceable"  # type: ignore[union-attr]
        assert "no stored open for STALE on 2020-01-02" in outcome.reason  # type: ignore[union-attr]
        assert stub.calls == [], (
            "the live source was consulted for a past-dated gap -- a real data hole must reject "
            "exactly as before, never fall through to a live quote"
        )
        assert broker.fills == []


class TestFutureDatedMissingBarFillsFromALiveQuoteWhenTheFlagPathIsWired:
    """The scenario this shard exists for: the newest session's own decision, meant to fill at a
    session that has not happened yet. `open_on` raises because there genuinely is no bar for
    `_FUTURE_FILL_DATE` -- and with a live source provided and `fill_date >= today`, the order fills
    against it instead of rejecting."""

    def test_fills_from_the_stubbed_live_quote_with_slippage_applied(self, settings: Settings) -> None:
        # A stored close at the *decision* date is what `_check_buy`'s weight-cap sizing reads --
        # realistic, since the persona's decision was made against a real close yesterday. What is
        # genuinely missing is only the fill date's open.
        _write_bar(settings, "NEXT", _DECIDED_ON, open_=99.00, close=100.00)
        broker = PaperBroker(_mandate())
        market = AsOfMarket(as_of=_DECIDED_ON, settings=settings)
        order = _order(symbol="NEXT", decided_on=_DECIDED_ON)
        stub = _StubLiveQuoteSource({"NEXT": Decimal("100.00")})

        outcome = broker.submit(
            order,
            market=market,
            fill_date=_FUTURE_FILL_DATE,
            live_quote_source=stub,
            today=_TODAY,
        )

        assert stub.calls == [("NEXT",)]
        assert not hasattr(outcome, "rule"), f"order was rejected instead of filled: {outcome!r}"
        assert outcome.price_source == "live_quote"  # type: ignore[union-attr]
        assert outcome.reference_open == Decimal("100.00")  # type: ignore[union-attr]
        # slippage_bps=50 (0.5%) applied to the live $100.00 quote, buy side: 100.00 * 1.005 = 100.50
        assert outcome.price == Decimal("100.50")  # type: ignore[union-attr]
        assert outcome.trade_date == _FUTURE_FILL_DATE  # type: ignore[union-attr]
        assert broker.fills == [outcome]
        assert outcome.to_json()["price_source"] == "live_quote"  # type: ignore[union-attr]

    def test_a_symbol_the_live_source_has_no_price_for_still_rejects_unpriceable(
        self, settings: Settings
    ) -> None:
        _write_bar(settings, "NOQUOTE", _DECIDED_ON, open_=50.00, close=50.00)
        broker = PaperBroker(_mandate())
        market = AsOfMarket(as_of=_DECIDED_ON, settings=settings)
        order = _order(symbol="NOQUOTE", decided_on=_DECIDED_ON)
        stub = _StubLiveQuoteSource({})  # no price for NOQUOTE at all

        outcome = broker.submit(
            order,
            market=market,
            fill_date=_FUTURE_FILL_DATE,
            live_quote_source=stub,
            today=_TODAY,
        )

        assert outcome.rule == "unpriceable"  # type: ignore[union-attr]
        assert "no live quote is available" in outcome.reason  # type: ignore[union-attr]
        assert broker.fills == []


# ---------------------------------------------------------------------------
# app.paperdesk.desk -- the cache-safety trap
# ---------------------------------------------------------------------------
#
# `run_card` (out of this shard's scope -- `app.tournament.runner`) does not yet call
# `PaperBroker.submit` with a live quote source at all, so `_cached_run` cannot yet actually produce
# a live-priced `AgentResult` end to end. What is tested here is the policy that must hold the day it
# does: with `Settings.paperdesk_live_fills` on, `_cached_run` must never freeze one call's result and
# serve it back on the next -- proven directly by monkeypatching `desk.run_card` to return a distinct
# object on every call and showing both tiers are bypassed while the flag is on, and untouched (a
# single call, cached and reused) while it is off.


def _card(**overrides: object) -> StrategyCard:
    fields: dict[str, object] = {
        "agent_id": "live-fill-cache-test",
        "display_name": "Live fill cache test desk",
        "discipline": Discipline.MOMENTUM,
        "thesis": "a test thesis",
        "universe": ("SYMA",),
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


def _fake_agent_result(card: StrategyCard) -> AgentResult:
    return AgentResult(
        card=card,
        sessions=1,
        starting_equity=Decimal("100000.00"),
        ending_equity=Decimal("100000.00"),
        total_return=Decimal("0"),
        max_drawdown=Decimal("0"),
        trades=(),
        rejections=(),
        rejection_details=(),
        benchmark_return=None,
    )


class TestDeskCacheDoesNotServeAStaleLivePrice:
    def test_flag_off_caches_and_reuses_the_first_result(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[int] = []

        def fake_run_card(card, *, settings, mandate, start, end):
            calls.append(len(calls))
            return _fake_agent_result(card)

        monkeypatch.setattr(desk, "run_card", fake_run_card)
        assert settings.paperdesk_live_fills is False

        card = _card()
        mandate = _mandate()
        window = desk._Window(
            inception=dt.date(2026, 8, 1),
            first_session=dt.date(2026, 8, 3),
            as_of=dt.date(2026, 8, 21),
            decided_on=dt.date(2026, 8, 20),
            sessions=10,
            latest_bar=dt.date(2026, 8, 21),
        )

        first = desk._cached_run(card, settings=settings, mandate=mandate, window=window)
        second = desk._cached_run(card, settings=settings, mandate=mandate, window=window)

        assert len(calls) == 1, "the second call recomputed instead of being served from cache"
        assert second is first, "a cached run must hand back the identical object, not an equal copy"

    def test_flag_on_bypasses_both_cache_tiers_every_call(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[int] = []

        def fake_run_card(card, *, settings, mandate, start, end):
            calls.append(len(calls))
            return _fake_agent_result(card)

        monkeypatch.setattr(desk, "run_card", fake_run_card)
        live_settings = settings.model_copy(update={"paperdesk_live_fills": True})

        card = _card()
        mandate = _mandate()
        window = desk._Window(
            inception=dt.date(2026, 8, 1),
            first_session=dt.date(2026, 8, 3),
            as_of=dt.date(2026, 8, 21),
            decided_on=dt.date(2026, 8, 20),
            sessions=10,
            latest_bar=dt.date(2026, 8, 21),
        )

        first = desk._cached_run(card, settings=live_settings, mandate=mandate, window=window)
        second = desk._cached_run(card, settings=live_settings, mandate=mandate, window=window)

        assert len(calls) == 2, (
            "a live-fills-enabled run was served from cache on the second call -- this is exactly "
            "the stale-live-price trap: a frozen price from the first call would be shown forever"
        )
        assert second is not first, "each call must be a freshly computed result, never a cached one"
        # And bypassing the cache must not have left anything behind in either tier for a later,
        # flag-off call to accidentally pick up. The key's digest folds in starting_cash (v8), so
        # reconstruct it through the same _run_cache_digest seam the real caller uses.
        key = (
            card.agent_id,
            window.inception,
            window.as_of,
            window.latest_bar,
            desk._run_cache_digest(card, starting_cash=mandate.starting_cash),
        )
        assert key not in desk._RUN_CACHE
        assert not desk._disk_cache_path(live_settings, key).is_file()

    def test_flag_off_behaviour_is_unaffected_by_the_live_fills_branch_existing(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second, more direct byte-identical-behaviour proof at the desk layer: with the flag at
        its default, `_cached_run` writes through to the disk tier exactly as it always has."""
        calls: list[int] = []

        def fake_run_card(card, *, settings, mandate, start, end):
            calls.append(len(calls))
            return _fake_agent_result(card)

        monkeypatch.setattr(desk, "run_card", fake_run_card)

        card = _card()
        mandate = _mandate()
        window = desk._Window(
            inception=dt.date(2026, 8, 1),
            first_session=dt.date(2026, 8, 3),
            as_of=dt.date(2026, 8, 21),
            decided_on=dt.date(2026, 8, 20),
            sessions=10,
            latest_bar=dt.date(2026, 8, 21),
        )
        key = (
            card.agent_id,
            window.inception,
            window.as_of,
            window.latest_bar,
            desk._run_cache_digest(card, starting_cash=mandate.starting_cash),
        )

        desk._cached_run(card, settings=settings, mandate=mandate, window=window)

        assert key in desk._RUN_CACHE
        assert desk._disk_cache_path(settings, key).is_file()
