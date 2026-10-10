"""Tests for the desk's *live session*: `app.paperdesk.desk._live_session`, and its wiring into
`app.paperdesk.desk._build_desk` behind `Settings.paperdesk_live_fills`.

**What this closes.** `app.paper.paperbroker.PaperBroker.submit` already knows how to fill an order
against a live quote (`tests/test_paper_live_fill.py`), and `_build_desk`'s own cache-safety branch
already knows not to freeze a live-priced `AgentResult` (same file) -- but nothing between those two
facts ever actually calls `submit()` with a `live_quote_source`. `run_card` structurally cannot: its
own `SessionCalendar` only ever produces a session for a date the benchmark has a *stored* bar for
(see `app.paperdesk.desk`'s module docstring), so the session dated after `window.as_of` -- decided
on the newest stored close, meant to fill today -- simply never exists there, and `run_card` is out
of this shard's scope regardless. `_live_session` is the piece that actually submits it, on top of
`_build_desk`'s already-replayed result.

**Never hits the real network.** `_StubLiveQuoteSource` below is a plain in-memory fake implementing
`app.market.live.LiveQuoteSource`'s two-method protocol (`snapshot`, `close`) -- copied in spirit from
`tests/test_paper_live_fill.py`'s own fake, this repo's established convention for this exact stub
(see that file's module docstring). Every test that wants the live path monkeypatches
`desk._live_quote_source` to hand back one directly, so the process-wide singleton and its background
poll thread are never built at all.

Builders (`_mandate`, `_card`, `_write_bars`, `_make_window`) are small, local, duplicated copies of
the same-named helpers in `tests/test_paperdesk.py`/`tests/test_paperdesk_rejections.py`/
`tests/test_paper_live_fill.py` -- this repo's own documented convention for these fakes (see
`tests/test_paperdesk.py`'s module docstring) rather than a cross-file import.
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
from app.paper.marketdata import clear_frame_cache
from app.paper.paperbroker import Mandate
from app.paperdesk import desk
from app.tournament.models import (
    DESIGN_THROUGH,
    AgentResult,
    Discipline,
    RealisedTrade,
    StrategyCard,
)

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _mandate(**overrides: object) -> Mandate:
    fields: dict[str, object] = {
        "persona_id": "test-persona",
        "display_name": "Test Persona",
        "account_id": "acct-1",
        "account_label": "Test Account",
        # Deliberately not consulted by the live path -- `_live_session` seeds the broker's cash
        # straight from the desk's own replayed `cash`, never `mandate.starting_cash` (see that
        # function's docstring). Kept here only because `Mandate` requires the field.
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


def _card(**overrides: object) -> StrategyCard:
    fields: dict[str, object] = {
        "agent_id": "live-session-test",
        "display_name": "Live session test desk",
        "discipline": Discipline.MOMENTUM,
        "thesis": "a test thesis, written before the trading window ran",
        "universe": ("LIVEA",),
        "entry": "close > 0",
        "exit": "close < 0",
        "stop_loss_pct": None,
        "take_profit_pct": None,
        "max_hold_days": None,
        "max_positions": 6,
        "position_pct": Decimal("0.10"),
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return StrategyCard(**fields)  # type: ignore[arg-type]


def _trade(**overrides: object) -> RealisedTrade:
    fields: dict[str, object] = {
        "symbol": "LIVEA",
        "entry_date": dt.date(2026, 8, 20),
        "entry_price": Decimal("90.00"),
        "exit_date": None,
        "exit_price": None,
        "quantity": Decimal("10"),
        "exit_reason": "open_at_end",
        "pnl": Decimal("0.00"),
        "return_pct": Decimal("0.00"),
        "bars_held": 5,
    }
    fields.update(overrides)
    return RealisedTrade(**fields)  # type: ignore[arg-type]


def _result(card: StrategyCard, trades: tuple[RealisedTrade, ...] = (), **overrides: object) -> AgentResult:
    fields: dict[str, object] = {
        "card": card,
        "sessions": 3,
        "starting_equity": Decimal("100000.00"),
        "ending_equity": Decimal("100000.00"),
        "total_return": Decimal("0"),
        "max_drawdown": Decimal("0"),
        "trades": tuple(trades),
        "rejections": (),
        "rejection_details": (),
        "benchmark_return": None,
    }
    fields.update(overrides)
    return AgentResult(**fields)  # type: ignore[arg-type]


_AS_OF = dt.date(2026, 8, 28)
_DECIDED_ON = dt.date(2026, 8, 27)
_TODAY = dt.date(2026, 8, 29)  # after `_AS_OF`, and no bar is ever written for it


def _window(**overrides: object) -> desk._Window:
    fields: dict[str, object] = {
        "inception": dt.date(2026, 8, 17),
        "first_session": dt.date(2026, 8, 17),
        "as_of": _AS_OF,
        "decided_on": _DECIDED_ON,
        "sessions": 3,
        "latest_bar": _AS_OF,
    }
    fields.update(overrides)
    return desk._Window(**fields)  # type: ignore[arg-type]


def _write_bar(settings: Settings, symbol: str, day: dt.date, *, open_: float, close: float) -> None:
    """One daily bar. Copied in spirit from `tests/test_paper_live_fill.py`'s own helper."""
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
    so a test can prove the live path was (or was not) consulted, copied in spirit from
    `tests/test_paper_live_fill.py`'s own stub of the same name (this repo's established convention
    for this exact fake)."""

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


class _RaisingLiveQuoteSourceAccessor:
    """Installed via `monkeypatch.setattr(desk, "_live_quote_source", ...)` on a flag-off test, so
    the test fails loudly if the live path is ever reached instead of silently passing because
    nothing happened to fire."""

    def __call__(self, settings: Settings) -> None:  # pragma: no cover -- must never run
        raise AssertionError(
            "desk._live_quote_source was called with Settings.paperdesk_live_fills off -- the live "
            "session must be a strict no-op while the flag is off"
        )


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    desk.clear_cache()
    clear_frame_cache()
    yield
    desk.clear_cache()
    clear_frame_cache()


# ---------------------------------------------------------------------------
# 1. Flag off is a no-op on every field, and never even reaches the live-quote seam
# ---------------------------------------------------------------------------


class TestFlagOffIsANoOp:
    def test_every_live_field_is_empty_and_the_quote_source_is_never_touched(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert settings.paperdesk_live_fills is False
        monkeypatch.setattr(desk, "_live_quote_source", _RaisingLiveQuoteSourceAccessor())
        _write_bar(settings, "LIVEA", _AS_OF, open_=99.00, close=100.00)

        card = _card()
        result = _result(card)
        built = desk._build_desk(
            card, result, settings=settings, window=_window(), mandate=_mandate(), today=_TODAY
        )

        assert built.live_fills == []
        assert built.live_rejections == []
        assert built.live_as_of is None

    def test_flag_off_historical_record_matches_flag_on_byte_for_byte(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The design constraint stated twice in the brief: a live fill must never be mixed into --
        or change so much as one digit of -- `trades`/`holdings`/`equity`/`cash`/`rejections`. Two
        desks built from the identical card/result/window/mandate, one with the flag off and one on
        (with a real firing entry live-filled), must agree on every field except the three `live_*`
        ones. `LIVEA` is held (a real `open_at_end` holding, quiet in both runs -- its exit rule
        never fires) and `LIVEB` is not: only `LIVEB`'s entry fires, live-only, in the flag-on run,
        so `holdings` is non-trivially populated on both sides while the entry activity differs."""
        _write_bar(settings, "LIVEA", _AS_OF, open_=99.00, close=100.00)
        _write_bar(settings, "LIVEB", _AS_OF, open_=99.00, close=100.00)
        card = _card(universe=("LIVEA", "LIVEB"))
        result = _result(card, trades=(_trade(),))  # LIVEA open_at_end -- held in both runs
        window = _window()
        mandate = _mandate()

        built_off = desk._build_desk(
            card, result, settings=settings, window=window, mandate=mandate, today=_TODAY
        )

        live_settings = settings.model_copy(update={"paperdesk_live_fills": True})
        stub = _StubLiveQuoteSource({"LIVEB": Decimal("100.00")})
        monkeypatch.setattr(desk, "_live_quote_source", lambda settings: stub)
        built_on = desk._build_desk(
            card, result, settings=live_settings, window=window, mandate=mandate, today=_TODAY
        )

        # Prove the live path actually did something this run, so this test is not vacuous.
        assert stub.calls, "the live source was never consulted -- this test proves nothing"

        excluded = {"live_fills", "live_rejections", "live_as_of"}
        assert built_off.model_dump(exclude=excluded) == built_on.model_dump(exclude=excluded)


# ---------------------------------------------------------------------------
# 2. Flag on, a firing entry -- a real LiveFill with slippage applied
# ---------------------------------------------------------------------------


class TestFlagOnFiringEntryFillsWithSlippage:
    def test_produces_a_live_fill_with_price_and_quote_price_distinct(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        live_settings = settings.model_copy(update={"paperdesk_live_fills": True})
        # A stored close at the *decision* date (`window.as_of`) is what `_signals` reads to decide
        # the entry rule fires, and what sizing reads to compute the order quantity -- no bar is ever
        # written for `_TODAY` itself, which is exactly what forces `PaperBroker.submit` past
        # `market.open_on` and onto the live-quote branch (see `PaperBroker.submit`'s own docstring).
        _write_bar(settings, "LIVEA", _AS_OF, open_=99.00, close=100.00)
        stub = _StubLiveQuoteSource({"LIVEA": Decimal("100.00")})
        monkeypatch.setattr(desk, "_live_quote_source", lambda settings: stub)

        card = _card()
        result = _result(card)  # no trades -- LIVEA is not held, so its entry rule is free to fire

        built = desk._build_desk(
            card, result, settings=live_settings, window=_window(), mandate=_mandate(), today=_TODAY
        )

        assert stub.calls, "the live source was never consulted"
        assert len(built.live_fills) == 1
        fill = built.live_fills[0]
        assert fill.symbol == "LIVEA"
        assert fill.side == "buy"
        assert Decimal(fill.quantity) > 0
        # slippage_bps=50 (0.5%) applied to a $100.00 live quote, buy side: 100.00 * 1.005 = 100.50
        assert fill.quote_price == "100.00"
        assert fill.price == "100.50"
        assert fill.price != fill.quote_price
        assert Decimal(fill.notional) == Decimal(fill.quantity) * Decimal(fill.price)
        # ISO-8601, parses cleanly, and is UTC.
        parsed = dt.datetime.fromisoformat(fill.quote_ts)
        assert parsed.tzinfo is not None
        assert built.live_as_of is not None
        dt.datetime.fromisoformat(built.live_as_of)

        # And the historical fields this entry must never touch stay exactly what a zero-trade,
        # zero-rejection result always produces.
        assert built.trades == []
        assert built.holdings == []
        assert built.cash == Decimal("100000.00")
        assert built.rejections == []
        assert built.rejection_count == 0

    def test_a_symbol_the_live_source_has_no_price_for_produces_no_fill_and_no_crash(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        live_settings = settings.model_copy(update={"paperdesk_live_fills": True})
        _write_bar(settings, "LIVEA", _AS_OF, open_=99.00, close=100.00)
        stub = _StubLiveQuoteSource({})  # no price for LIVEA at all
        monkeypatch.setattr(desk, "_live_quote_source", lambda settings: stub)

        card = _card()
        result = _result(card)

        built = desk._build_desk(
            card, result, settings=live_settings, window=_window(), mandate=_mandate(), today=_TODAY
        )

        assert built.live_fills == []
        assert len(built.live_rejections) == 1
        assert built.live_rejections[0].rule == "unpriceable"


# ---------------------------------------------------------------------------
# 3. A live rejection lands in `live_rejections`, never in the historical `rejections`
# ---------------------------------------------------------------------------


class TestLiveRejectionStaysSeparateFromHistoricalRejections:
    def test_insufficient_cash_on_the_live_leg_never_touches_historical_rejections(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        live_settings = settings.model_copy(update={"paperdesk_live_fills": True})
        _write_bar(settings, "LIVEA", _AS_OF, open_=99.00, close=100.00)
        stub = _StubLiveQuoteSource({"LIVEA": Decimal("100.00")})
        monkeypatch.setattr(desk, "_live_quote_source", lambda settings: stub)

        # A large position_pct against a tiny replayed ending equity: the desk's own historical
        # `AgentResult` is untouched (zero trades, zero rejections, exactly as `_result`'s defaults
        # say) -- only the *live* leg's cash (`equity - positions_value`, here `$10.00 - $0.00`) is
        # too small for the ~$50,000 order this card's own sizing asks for.
        card = _card(position_pct=Decimal("0.50"), max_positions=1)
        result = _result(card, starting_equity=Decimal("100000.00"), ending_equity=Decimal("10.00"))

        built = desk._build_desk(
            card, result, settings=live_settings, window=_window(), mandate=_mandate(), today=_TODAY
        )

        assert stub.calls, "the live source was never consulted -- this test proves nothing"
        assert len(built.live_rejections) == 1
        assert built.live_rejections[0].rule == "insufficient_cash"
        assert built.live_rejections[0].count == 1

        # The separation this test exists to prove: the historical record -- built from `result`,
        # which never recorded any rejection at all -- must stay exactly that: empty.
        assert built.rejections == []
        assert built.rejection_count == 0
        assert built.live_fills == []


# ---------------------------------------------------------------------------
# 4. Ladder and allocation desks always carry the three fields, well-formed, never attempting a
#    live session even with the flag on.
# ---------------------------------------------------------------------------


class TestLadderAndAllocationDesksNeverAttemptALiveSession:
    def test_ladder_desk_carries_empty_defaults_with_the_flag_on(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.tournament.ladder import LadderCard, LadderResult, Rung

        live_settings = settings.model_copy(update={"paperdesk_live_fills": True})
        monkeypatch.setattr(desk, "_live_quote_source", _RaisingLiveQuoteSourceAccessor())

        card = LadderCard(
            agent_id="ladder-live-test",
            display_name="Ladder live test desk",
            thesis="a test thesis, written before the trading window ran",
            signal_symbol="SPY",
            defensive_symbol="SYMA",
            bond_symbol="SYMB",
            leveraged_symbol="SYMC",
            base_defensive_weight=Decimal("0.60"),
            base_bond_weight=Decimal("0.40"),
            rungs=(Rung(drawdown=Decimal("-0.10"), leveraged_weight=Decimal("0.20")),),
            confirm_ma=5,
            ath_haircut=Decimal("0.5"),
            recovery_gain=Decimal("0.10"),
            recovery_sessions=60,
            designed_through=DESIGN_THROUGH,
        )
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

        built = desk._build_ladder_desk(card, result, settings=live_settings, window=_window())

        assert built.live_fills == []
        assert built.live_rejections == []
        assert built.live_as_of is None
