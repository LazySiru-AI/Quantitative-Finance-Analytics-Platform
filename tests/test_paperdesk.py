"""Tests for the live paper desk (`app.paperdesk.desk`, `app.api.paperdesk`).

Split per the repo's own convention (see `tests/test_macro_api.py`'s module docstring): the
arithmetic-and-shape tests below monkeypatch `app.paperdesk.desk.run_card` (and the card/mandate/
window lookups around it) with a synthetic `AgentResult`, so they are fast, deterministic, and let
awkward cases -- a deliberately-wrong `total_return`, a zero-trade desk, a card with no stop -- be
constructed directly rather than coaxed out of real market data. `TestIntegrationRealWindow` at the
bottom is the exception: it runs the real two cards through the real store, unmonkeypatched, and
takes a couple of seconds for twelve-ish sessions across both desks.

Deliberately self-contained rather than importing from `tests/test_tournament_runner.py`: this
file's `_card`/`_mandate`/`_trade`/`_write_bars` builders are small, duplicated copies of that
file's own helpers, the same "duplicated fakes rather than a cross-file import" choice
`tests/test_macro_api.py` documents and makes for its own fakes.

Every test clears `app.paperdesk.desk`'s in-process run cache (keyed on `(agent_id, inception,
as_of, latest_bar)`, not on the settings/store path) and `app.paper.marketdata`'s frame cache
before and after it runs -- neither cache key includes the temp store path a given test's `settings`
fixture points at, so a result cached by one test could otherwise be served, wrongly, to the next.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import paperdesk as paperdesk_api
from app.config import Settings, get_settings
from app.db import duck
from app.market import store as market_store
from app.market.models import BAR_COLUMNS, Interval
from app.paper.marketdata import clear_frame_cache
from app.paper.paperbroker import Mandate
from app.paperdesk import autopilot as autopilot_mod
from app.paperdesk import desk
from app.paperdesk.models import Benchmark
from app.tournament.models import (
    DESIGN_THROUGH,
    AgentResult,
    Discipline,
    RealisedTrade,
    StrategyCard,
)
from app.tournament.purposes import (
    PURPOSE_SPECS,
    FundingShape,
    Purpose,
    find_disjointness_violations,
)
from tests.conftest import requires_real_store

# ---------------------------------------------------------------------------
# Builders -- small, local, overridable via kwargs
# ---------------------------------------------------------------------------


def _mandate(**overrides: object) -> Mandate:
    fields: dict[str, object] = {
        "persona_id": "test-persona",
        "display_name": "Test Persona",
        "account_id": "acct-1",
        "account_label": "Test Account",
        "starting_cash": Decimal("100000.00"),
        "allow_fractional_shares": False,
        "max_positions": 6,
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


def _seat(index: int) -> str:
    """The agent id at a roster position, or a synthetic stand-in past the end of the roster.

    Most tests below need "a desk" and "a second desk" and do not care which cards those are -- they
    check equity arithmetic, stop prices, cache behaviour. Referring to seats positionally keeps them
    alive across a re-selection.

    The fallback exists because the roster is not a fixed length. Round 9's rule seated **two** cards
    where rounds 6 to 8 had four or five, and a bare `AGENT_IDS[2]` then raised `IndexError` at import
    time -- taking the whole module down during collection, so every test in the file failed for a
    reason that had nothing to do with any of them. A stand-in id is harmless: `_install` below routes
    unknown ids to a generic synthetic card, so a test naming the third seat still exercises "some
    desk" even when the desk has only two.
    """
    ids = desk.AGENT_IDS
    return ids[index] if index < len(ids) else f"_unrostered-seat-{index}"


_FIRST = _seat(0)
_SECOND = _seat(1)
_THIRD = _seat(2)

def _card(agent_id: str = _FIRST, **overrides: object) -> StrategyCard:
    fields: dict[str, object] = {
        "agent_id": agent_id,
        "display_name": f"Desk {agent_id}",
        "discipline": Discipline.MOMENTUM,
        "thesis": "a test thesis, written before the trading window ran",
        "universe": ("AAA", "BBB"),
        "entry": "close > 0",
        "exit": "close < 0",
        "stop_loss_pct": Decimal("0.12"),
        "take_profit_pct": None,
        "max_hold_days": 180,
        "max_positions": 6,
        "position_pct": Decimal("0.15"),
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return StrategyCard(**fields)  # type: ignore[arg-type]


def _trade(**overrides: object) -> RealisedTrade:
    fields: dict[str, object] = {
        "symbol": "AAA",
        "entry_date": dt.date(2026, 8, 5),
        "entry_price": Decimal("100.00"),
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
        "sessions": 12,
        "starting_equity": Decimal("100000.00"),
        "ending_equity": Decimal("100000.00"),
        # Deliberately wrong -- see TestTotalReturnComputedFromEquity. A correct implementation
        # must never read this field back out.
        "total_return": Decimal("999"),
        "max_drawdown": Decimal("0.05"),
        "trades": tuple(trades),
        "rejections": (),
        "benchmark_return": Decimal("0.02"),
    }
    fields.update(overrides)
    return AgentResult(**fields)  # type: ignore[arg-type]


#: A synthetic window for the monkeypatched tests. Its session dates are invented -- these tests
#: never touch the real calendar -- but `inception` is taken from `desk.INCEPTION` rather than
#: restated, because the response echoes that field back and a test asserting the echo must not be
#: comparing one hardcoded date against another. The desk has already been backdated once
#: (2026-08-01 -> 2026-06-01); pinning it here made that a test failure about nothing.
_WINDOW = desk._Window(
    inception=desk.INCEPTION,
    first_session=desk.INCEPTION,
    as_of=dt.date(2026, 8, 18),
    decided_on=dt.date(2026, 8, 17),
    sessions=12,
    latest_bar=dt.date(2026, 8, 18),
)


def _write_bars(settings: Settings, symbol: str, prices: dict[dt.date, tuple[float, float]]) -> None:
    """Write one daily bar per `(open, close)` in `prices` into `settings`'s temp store."""
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


def _spy_bars(start: dt.date, end: dt.date) -> dict[dt.date, tuple[float, float]]:
    """One synthetic `(open, close)` bar per calendar day from `start` through `end` inclusive --
    written as SPY, the benchmark `desk._benchmark_dates`/`desk._trading_window`/
    `desk._validate_inception` all read. Every calendar day, weekends included, the same convention
    every other bar-writing helper in this file already uses: the temp store has no notion of a real
    trading calendar, only whichever dates a test chooses to give it a bar for, so this is enough to
    exercise inception bounds and session counting without needing a real holiday-aware calendar."""
    days = (end - start).days + 1
    return {start + dt.timedelta(days=i): (400.0 + i * 0.1, 400.0 + i * 0.1) for i in range(days)}


def _make_window(session_dates: tuple[dt.date, ...]) -> desk._Window:
    """A `desk._Window` built directly from a chosen list of session dates, for tests that care about
    `in_sample_sessions` counting specifically and would rather name the exact session dates than
    reconstruct them from a real `SessionCalendar` over synthetic bars."""
    return desk._Window(
        inception=session_dates[0],
        first_session=session_dates[0],
        as_of=session_dates[-1],
        decided_on=session_dates[-1] - dt.timedelta(days=1),
        sessions=len(session_dates),
        session_dates=session_dates,
        latest_bar=session_dates[-1],
        earliest_bar=session_dates[0],
    )


def _books(body: dict) -> dict[str, dict]:
    """The response's books keyed by purpose. Three of them, always -- a purpose with no cards is an
    empty book, not an absent one."""
    return {b["purpose"]: b for b in body["books"]}


def _desks(body: dict) -> list[dict]:
    """The trading book's **card** desks -- what `_desks(body)` meant before the desk had three
    books, and before it had a seat that is not a card.

    Every monkeypatched test in this file installs a synthetic `StrategyCard`, and a strategy card is
    a trading-purpose card, so this is the book they were always asserting about.

    **The autopilot seat is filtered out here, once, rather than at each assertion.** It rides on the
    trading roster (see `app.paperdesk.desk.rosters`) but it is not a card: it has no
    `StrategyCard` for `_install` to install, no `AgentResult` for `run_card` to return, and it is
    absent from `desk.AGENT_IDS` by design. Every assertion in this file is about card assembly --
    "one desk per `AGENT_IDS`, in roster order, each at the book's starting equity" -- and a seat
    built from a different mechanism entirely would falsify each of them while telling us nothing
    about the property under test. It gets its own file (`tests/test_paperdesk_autopilot.py`).

    Use :func:`_all_desks` for the handful of cases that genuinely care about everything the book
    renders, the autopilot seat included.
    """
    return [d for d in _all_desks(body) if d["kind"] != "autopilot"]


def _all_desks(body: dict) -> list[dict]:
    """Every desk the trading book renders, cards and the autopilot seat alike -- the unfiltered
    counterpart to :func:`_desks`."""
    return _books(body)["trading"]["desks"]


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cards: dict[str, StrategyCard],
    results: dict[str, AgentResult],
    window: desk._Window = _WINDOW,
) -> dict[str, int]:
    """Monkeypatch `desk`'s card/mandate/window/run_card lookups with fixed fakes, so `desk.state`/
    `desk.refresh` exercise only the reshaping logic under test. Returns a mutable call counter for
    `run_card`, for tests that need to prove the cache did or did not fire (see
    `TestRefreshBustsCache`)."""
    monkeypatch.setattr(desk, "_trading_window", lambda settings: window)
    monkeypatch.setattr(desk, "_mandate", lambda purpose: _mandate())
    # See this helper's docstring: the other two books are emptied so each test exercises the
    # book its synthetic strategy card actually belongs to.
    monkeypatch.setattr(desk, "SAVINGS_AGENT_IDS", ())
    monkeypatch.setattr(desk, "ROTH_AGENT_IDS", ())
    # Same fallback reasoning as `fake_run_card` below: a test that builds one bespoke card
    # (a no-stop card, a no-hold-cap card) should not also have to supply the rest of the
    # roster just to keep `desk.state` from raising while it iterates.
    monkeypatch.setattr(
        desk,
        "_load_card",
        lambda settings, agent_id: cards.get(agent_id) or _default_cards()[agent_id],
    )

    calls = {"count": 0}

    def fake_run_card(card: StrategyCard, *, settings: Settings, mandate: Mandate, start: dt.date, end: dt.date) -> AgentResult:
        calls["count"] += 1
        # Fall back to a plain result for any rostered agent the caller did not name. Nearly every
        # test below is about one desk's arithmetic and supplies a result only for that desk; before
        # this fallback they each had to enumerate the whole roster, so adding a third strategy
        # failed ten tests with `KeyError` rather than with anything about the behaviour they check.
        # A test that cares what the other desks return still overrides them explicitly.
        return results.get(card.agent_id) or _result(card)

    monkeypatch.setattr(desk, "run_card", fake_run_card)
    return calls


#: The roster's first three seats, by position rather than by name. Most tests below need "a desk"
#: and "a second desk" and do not care which cards those are -- they check equity arithmetic, stop
#: prices, cache behaviour. Referring to them positionally means a round that re-selects the desk
#: (round 6 replaced `C-trend` with `A-rotation` and `c07-chop`) changes one tuple in `desk.py` and
#: nothing here, instead of turning a product decision into a dozen unrelated test failures.
#: Per-agent sizing for the synthetic cards, mirroring each real card's own shape closely enough
#: that a sizing-dependent assertion means something. Keyed by position for the same reason as
#: above; an agent added to the roster without an entry here still gets a card, from
#: `_GENERIC_SPEC`, so the roster and this table cannot silently disagree about who exists.
_CARD_SPECS: dict[str, dict[str, object]] = {
    _FIRST: dict(universe=("AAA", "BBB"), max_positions=6, position_pct=Decimal("0.15")),
    _SECOND: dict(
        universe=("AAA", "CCC"),
        max_positions=5,
        position_pct=Decimal("0.18"),
        stop_loss_pct=Decimal("0.12"),
        max_hold_days=120,
    ),
    _THIRD: dict(
        universe=("AAA", "DDD"),
        max_positions=4,
        position_pct=Decimal("0.20"),
        stop_loss_pct=Decimal("0.08"),
        max_hold_days=120,
    ),
}

_GENERIC_SPEC: dict[str, object] = dict(
    universe=("AAA", "BBB"), max_positions=4, position_pct=Decimal("0.20")
)


def _default_cards() -> dict[str, StrategyCard]:
    """One synthetic card per rostered agent, built from `desk.AGENT_IDS`.

    Driven by the roster rather than listing two agents by name: the desk gained a third strategy
    and was backdated, and a fixture that hardcodes its membership turns a product change into a
    test failure that says nothing about correctness.
    """
    return {
        agent_id: _card(agent_id, **_CARD_SPECS.get(agent_id, _GENERIC_SPEC))  # type: ignore[arg-type]
        # The roster, plus any id `_CARD_SPECS` names that is not currently on it. The union matters
        # for the roster tests, which deliberately configure a desk the default does not contain and
        # would otherwise KeyError here before reaching what they actually assert.
        for agent_id in dict.fromkeys((*desk.AGENT_IDS, *_CARD_SPECS))
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    desk.clear_cache()
    clear_frame_cache()
    yield
    desk.clear_cache()
    clear_frame_cache()


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(paperdesk_api.router)
    return fastapi_app


@pytest.fixture
def client(settings: Settings, app: FastAPI) -> TestClient:
    """`settings` (from `tests/conftest.py`) redirects `get_settings()` to a temp store via env
    vars, which is what lets `desk.state()` -- called with no arguments by the router -- resolve to
    the same temp settings this test controls, exactly the mechanism that fixture's own docstring
    describes."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Two desks, correct starting figures
# ---------------------------------------------------------------------------


class TestStateEndpointShape:
    def test_every_rostered_desk_appears_with_correct_starting_figures(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One desk per `desk.AGENT_IDS`, in roster order, each from `desk.INCEPTION` at $100,000.

        The earlier version pinned `len(desks) == 2`, the literal pair of agent ids, and
        `"2026-08-01"`. Adding a third strategy and backdating the desk broke it -- but the test was
        never about which strategies trade or when they started; it was about the shape of the
        response. Deriving both from the module keeps the assertion on the property and lets the
        roster stay a product decision.
        """
        cards = _default_cards()
        results = {agent_id: _result(card) for agent_id, card in cards.items()}
        _install(monkeypatch, cards=cards, results=results)

        response = client.get("/api/paperdesk/state")

        assert response.status_code == 200
        body = response.json()
        assert body["inception"] == desk.INCEPTION.isoformat()
        assert _books(body)["trading"]["starting_cash"] == "100000.00"
        assert len(_desks(body)) == len(desk.AGENT_IDS)
        assert [d["agent_id"] for d in _desks(body)] == list(desk.AGENT_IDS)
        for d in _desks(body):
            assert d["starting_equity"] == "100000.00"


# ---------------------------------------------------------------------------
# 2. equity == cash + positions_value, to the cent
# ---------------------------------------------------------------------------


class TestEquityIdentity:
    def test_equity_equals_cash_plus_positions_value(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        _write_bars(
            settings,
            "AAA",
            {dt.date(2026, 8, 1) + dt.timedelta(days=i): (150.0 + i, 150.0 + i) for i in range(20)},
        )
        cards = _default_cards()
        open_trade = _trade(
            symbol="AAA",
            entry_date=dt.date(2026, 8, 5),
            entry_price=Decimal("150.00"),
            quantity=Decimal("100"),
            bars_held=10,
        )
        results = {
            _FIRST: _result(
                cards[_FIRST], trades=(open_trade,), ending_equity=Decimal("101000.00")
            ),
            _SECOND: _result(cards[_SECOND], ending_equity=Decimal("100000.00")),
        }
        _install(monkeypatch, cards=cards, results=results)

        body = client.get("/api/paperdesk/state").json()

        for d in _desks(body):
            cash = Decimal(d["cash"])
            positions_value = Decimal(d["positions_value"])
            equity = Decimal(d["equity"])
            assert cash + positions_value == equity, d["agent_id"]

        b = next(d for d in _desks(body) if d["agent_id"] == _FIRST)
        assert len(b["holdings"]) == 1
        assert Decimal(b["positions_value"]) > 0


# ---------------------------------------------------------------------------
# A held symbol's signal must quote the same price as its holding -- both are marked to `as_of`.
# This is the invariant a signal evaluated one session too early (at `decided_on` instead of
# `as_of`) would violate: two different prices for the same symbol on one page, with nothing
# saying they came from different dates.
# ---------------------------------------------------------------------------


class TestSignalLastCloseMatchesHoldingLastPrice:
    def test_held_symbols_last_close_equals_its_holdings_last_price(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        _write_bars(
            settings,
            "AAA",
            {dt.date(2026, 8, 1) + dt.timedelta(days=i): (150.0 + i, 150.0 + i) for i in range(20)},
        )
        cards = {_FIRST: _card(_FIRST, universe=("AAA", "BBB")), _SECOND: _card(_SECOND, universe=("AAA",))}
        open_trade = _trade(
            symbol="AAA",
            entry_date=dt.date(2026, 8, 5),
            entry_price=Decimal("150.00"),
            quantity=Decimal("100"),
            bars_held=10,
        )
        results = {
            _FIRST: _result(cards[_FIRST], trades=(open_trade,)),
            _SECOND: _result(cards[_SECOND]),
        }
        _install(monkeypatch, cards=cards, results=results)

        body = client.get("/api/paperdesk/state").json()
        b = next(d for d in _desks(body) if d["agent_id"] == _FIRST)

        assert len(b["holdings"]) == 1
        holding = b["holdings"][0]
        assert holding["symbol"] == "AAA"

        signal = next(s for s in b["signals"] if s["symbol"] == "AAA")
        assert signal["held"] is True
        assert signal["last_close"] is not None
        assert Decimal(signal["last_close"]) == Decimal(holding["last_price"])
        # Both are marked to the same `as_of` date this desk reports.
        assert holding["last_price_date"] == body["as_of"]


# ---------------------------------------------------------------------------
# 3. realised_pnl / unrealised_pnl are separated correctly
# ---------------------------------------------------------------------------


class TestRealisedVsUnrealisedSeparation:
    def test_open_at_end_trade_lands_in_unrealised_and_holdings_never_in_trades(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        _write_bars(
            settings,
            "AAA",
            {dt.date(2026, 8, 1) + dt.timedelta(days=i): (200.0, 200.0 + i) for i in range(20)},
        )
        cards = _default_cards()
        closed = _trade(
            symbol="BBB",
            entry_date=dt.date(2026, 8, 3),
            entry_price=Decimal("50.00"),
            exit_date=dt.date(2026, 8, 10),
            exit_price=Decimal("45.00"),
            quantity=Decimal("20"),
            exit_reason="stop",
            pnl=Decimal("-100.00"),
            return_pct=Decimal("-0.10"),
            bars_held=5,
        )
        open_trade = _trade(
            symbol="AAA",
            entry_date=dt.date(2026, 8, 4),
            entry_price=Decimal("200.00"),
            quantity=Decimal("10"),
            exit_reason="open_at_end",
            bars_held=12,
        )
        results = {
            _FIRST: _result(cards[_FIRST], trades=(closed, open_trade)),
            _SECOND: _result(cards[_SECOND]),
        }
        _install(monkeypatch, cards=cards, results=results)

        body = client.get("/api/paperdesk/state").json()
        b = next(d for d in _desks(body) if d["agent_id"] == _FIRST)

        assert [t["symbol"] for t in b["trades"]] == ["BBB"]
        assert b["trades"][0]["exit_reason"] == "stop"
        assert [h["symbol"] for h in b["holdings"]] == ["AAA"]

        assert b["realised_pnl"] == "-100.00"
        assert Decimal(b["unrealised_pnl"]) != Decimal("0")
        # The unrealised figure must come from the holding's own fresh mark, not from the closed
        # trade's pnl leaking into the wrong bucket.
        assert Decimal(b["unrealised_pnl"]) == Decimal(b["holdings"][0]["unrealised_pnl"])


# ---------------------------------------------------------------------------
# 4. total_return is computed from equity, not read off AgentResult.total_return
# ---------------------------------------------------------------------------


class TestTotalReturnComputedFromEquity:
    def test_total_return_ignores_the_planted_wrong_field(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cards = _default_cards()
        results = {
            _FIRST: _result(
                cards[_FIRST],
                ending_equity=Decimal("101000.00"),
                total_return=Decimal("999"),  # deliberately wrong
            ),
            _SECOND: _result(cards[_SECOND]),
        }
        _install(monkeypatch, cards=cards, results=results)

        body = client.get("/api/paperdesk/state").json()
        b = next(d for d in _desks(body) if d["agent_id"] == _FIRST)

        assert Decimal(b["total_return"]) == Decimal("0.01")
        assert b["total_return"] != "999"


# ---------------------------------------------------------------------------
# 5. stop_price
# ---------------------------------------------------------------------------


class TestStopPrice:
    def test_stop_price_is_entry_times_one_minus_stop_and_null_without_a_stop(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cards = {
            _FIRST: _card(
                _FIRST, universe=("AAA",), stop_loss_pct=Decimal("0.12"), max_hold_days=180
            ),
            _SECOND: _card(
                _SECOND, universe=("AAA",), stop_loss_pct=None, max_hold_days=120
            ),
        }
        trade = _trade(entry_price=Decimal("100.00"), quantity=Decimal("10"), bars_held=1)
        results = {
            _FIRST: _result(cards[_FIRST], trades=(trade,)),
            _SECOND: _result(cards[_SECOND], trades=(trade,)),
        }
        _install(monkeypatch, cards=cards, results=results)

        body = client.get("/api/paperdesk/state").json()
        b = next(d for d in _desks(body) if d["agent_id"] == _FIRST)
        c = next(d for d in _desks(body) if d["agent_id"] == _SECOND)

        assert b["holdings"][0]["stop_price"] == "88.00"
        assert c["holdings"][0]["stop_price"] is None


# ---------------------------------------------------------------------------
# 6. sessions_to_time_stop
# ---------------------------------------------------------------------------


class TestSessionsToTimeStop:
    def test_counts_down_correctly_and_null_without_a_hold_cap(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cards = {
            _FIRST: _card(_FIRST, universe=("AAA",), max_hold_days=180),
            _SECOND: _card(_SECOND, universe=("AAA",), max_hold_days=None, stop_loss_pct=Decimal("0.12")),
        }
        b_trade = _trade(bars_held=10)
        c_trade = _trade(bars_held=3)
        results = {
            _FIRST: _result(cards[_FIRST], trades=(b_trade,)),
            _SECOND: _result(cards[_SECOND], trades=(c_trade,)),
        }
        _install(monkeypatch, cards=cards, results=results)

        body = client.get("/api/paperdesk/state").json()
        b = next(d for d in _desks(body) if d["agent_id"] == _FIRST)
        c = next(d for d in _desks(body) if d["agent_id"] == _SECOND)

        assert b["holdings"][0]["sessions_to_time_stop"] == 170  # 180 - 10
        assert c["holdings"][0]["sessions_to_time_stop"] is None


# ---------------------------------------------------------------------------
# 7. A zero-trade desk renders cleanly
# ---------------------------------------------------------------------------


class TestZeroTradeDesk:
    def test_zero_trades_no_division_by_zero_no_null_where_a_figure_is_required(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cards = _default_cards()
        results = {
            _FIRST: _result(cards[_FIRST], trades=()),
            _SECOND: _result(cards[_SECOND], trades=()),
        }
        _install(monkeypatch, cards=cards, results=results)

        body = client.get("/api/paperdesk/state").json()
        b = next(d for d in _desks(body) if d["agent_id"] == _FIRST)

        assert b["holdings"] == []
        assert b["trades"] == []
        assert b["equity"] == b["starting_equity"] == "100000.00"
        assert Decimal(b["total_return"]) == Decimal("0")
        assert b["cash"] == "100000.00"
        assert b["positions_value"] == "0.00"
        assert b["realised_pnl"] == "0.00"
        assert b["unrealised_pnl"] == "0.00"
        assert b["open_positions"] == 0
        assert b["slots_free"] == b["max_positions"]


# ---------------------------------------------------------------------------
# 8. POST /refresh busts the cache
# ---------------------------------------------------------------------------


class TestRefreshBustsCache:
    def test_refresh_recomputes_state_returns_recomputes(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cards = _default_cards()
        results = {
            _FIRST: _result(cards[_FIRST]),
            _SECOND: _result(cards[_SECOND]),
        }
        calls = _install(monkeypatch, cards=cards, results=results)

        first = client.get("/api/paperdesk/state")
        assert first.status_code == 200
        assert calls["count"] == len(desk.AGENT_IDS)  # one run_card call per desk

        second = client.get("/api/paperdesk/state")
        assert second.status_code == 200
        assert calls["count"] == len(desk.AGENT_IDS)  # served from cache, no new run_card calls

        refreshed = client.post("/api/paperdesk/refresh")
        assert refreshed.status_code == 200
        assert calls["count"] == 2 * len(desk.AGENT_IDS)  # cache busted, every desk recomputed

        assert set(refreshed.json()) == set(first.json())
        assert [d["agent_id"] for d in _desks(refreshed.json())] == list(desk.AGENT_IDS)


# ---------------------------------------------------------------------------
# 10. signals cover every universe symbol exactly once
# ---------------------------------------------------------------------------


class TestSignalsCoverage:
    def test_every_universe_symbol_appears_once_and_a_held_symbol_is_flagged(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cards = {
            _FIRST: _card(_FIRST, universe=("AAA", "BBB", "CCC")),
            _SECOND: _card(_SECOND, universe=("AAA", "DDD")),
        }
        held_trade = _trade(symbol="AAA")
        results = {
            _FIRST: _result(cards[_FIRST], trades=(held_trade,)),
            _SECOND: _result(cards[_SECOND]),
        }
        _install(monkeypatch, cards=cards, results=results)

        body = client.get("/api/paperdesk/state").json()
        b = next(d for d in _desks(body) if d["agent_id"] == _FIRST)

        symbols = [s["symbol"] for s in b["signals"]]
        assert sorted(symbols) == ["AAA", "BBB", "CCC"]
        assert len(symbols) == len(set(symbols))

        held_signal = next(s for s in b["signals"] if s["symbol"] == "AAA")
        assert held_signal["held"] is True
        for s in b["signals"]:
            if s["symbol"] != "AAA":
                assert s["held"] is False


# ---------------------------------------------------------------------------
# 10b. `rank_by` reaches the signal panel -- the order, the key, and the queue position
# ---------------------------------------------------------------------------


class TestRankedSignals:
    """The panel says which qualifying name gets a scarce slot, instead of leaving the reader to
    guess from array order.

    `app.tournament.runner` already decides this for the engine (`_ordered_entry_candidates`), and
    `run_card` -- which this desk calls -- has honoured it since `rank_by` existed. What did not
    honour it was the forward-looking panel: `_signals` walked `card.universe` in the order it was
    typed, so a desk with three names firing into two free slots showed them in one order and would
    have bought them in another. These tests pin the two halves to the same order.
    """

    @staticmethod
    def _flat(settings: Settings, symbol: str, close: float) -> None:
        """20 daily bars at one price, so `close` is both the mark and a usable ranking key."""
        _write_bars(
            settings,
            symbol,
            {dt.date(2026, 8, 1) + dt.timedelta(days=i): (close, close) for i in range(20)},
        )

    def test_signals_come_back_in_the_engines_ranked_order_with_the_key_and_a_queue_position(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        self._flat(settings, "AAA", 100.0)
        self._flat(settings, "BBB", 300.0)
        self._flat(settings, "CCC", 200.0)

        cards = {
            _FIRST: _card(
                _FIRST,
                universe=("AAA", "BBB", "CCC"),
                entry="close > 150",
                rank_by="close",
            )
        }
        _install(monkeypatch, cards=cards, results={_FIRST: _result(cards[_FIRST])})

        body = client.get("/api/paperdesk/state").json()
        b = next(d for d in _desks(body) if d["agent_id"] == _FIRST)

        # Highest key first -- *not* the ("AAA", "BBB", "CCC") order the universe was written in,
        # which is the whole point: that order is worth a measured 53.9-point spread (PROTOCOL.md
        # section 7) and the panel used to present it as if it were the answer.
        assert [s["symbol"] for s in b["signals"]] == ["BBB", "CCC", "AAA"]
        assert [s["rank_value"] for s in b["signals"]] == [300.0, 200.0, 100.0]

        # AAA is quiet under `close > 150`, so it is not in the queue at all even though it is
        # ranked -- `entry_rank` counts contenders, not rows.
        by_symbol = {s["symbol"]: s for s in b["signals"]}
        assert by_symbol["BBB"]["entry_rank"] == 1
        assert by_symbol["CCC"]["entry_rank"] == 2
        assert by_symbol["AAA"]["entry_rank"] is None
        assert by_symbol["AAA"]["entry_fires"] is False

        # The expression itself rides along, since a column of bare numbers cannot say what was
        # measured.
        assert b["rank_by"] == "close"

    def test_a_held_name_is_ranked_but_not_queued(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        """Holding a name does not remove it from the ranking -- it removes it from the contest.

        The engine skips a symbol already in the book (no pyramiding) before it ever considers the
        slot, so a held name must not consume a queue position and push the actual next buy from
        `entry_rank == 1` to `2`.
        """
        self._flat(settings, "AAA", 300.0)
        self._flat(settings, "BBB", 200.0)

        cards = {_FIRST: _card(_FIRST, universe=("AAA", "BBB"), entry="close > 0", rank_by="close")}
        held = _trade(symbol="AAA", entry_price=Decimal("300.00"), quantity=Decimal("10"))
        _install(
            monkeypatch, cards=cards, results={_FIRST: _result(cards[_FIRST], trades=(held,))}
        )

        body = client.get("/api/paperdesk/state").json()
        b = next(d for d in _desks(body) if d["agent_id"] == _FIRST)
        by_symbol = {s["symbol"]: s for s in b["signals"]}

        assert by_symbol["AAA"]["held"] is True
        assert by_symbol["AAA"]["rank_value"] == 300.0
        assert by_symbol["AAA"]["entry_rank"] is None
        # BBB is the next buy, and says so as 1 rather than as 2.
        assert by_symbol["BBB"]["entry_rank"] == 1

    def test_a_symbol_with_no_key_sorts_behind_every_ranked_one(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        """An unknown key is not "ranks lowest", it is "this desk cannot say" -- and either way it
        must not land wherever a sort happens to drop a `NaN`. `ZZZ` has no stored bar at all."""
        self._flat(settings, "AAA", 100.0)
        self._flat(settings, "BBB", 300.0)

        cards = {
            _FIRST: _card(_FIRST, universe=("ZZZ", "AAA", "BBB"), entry="close > 0", rank_by="close")
        }
        _install(monkeypatch, cards=cards, results={_FIRST: _result(cards[_FIRST])})

        body = client.get("/api/paperdesk/state").json()
        b = next(d for d in _desks(body) if d["agent_id"] == _FIRST)

        assert [s["symbol"] for s in b["signals"]] == ["BBB", "AAA", "ZZZ"]
        unpriced = next(s for s in b["signals"] if s["symbol"] == "ZZZ")
        assert unpriced["rank_value"] is None
        assert unpriced["blocked"] == "no price"

    def test_an_unranked_card_is_untouched_by_any_of_this(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        """Every card in the library predates `rank_by` and leaves it unset. Their panels must read
        exactly as they did: universe order, and no rank fields claiming a precision the card does
        not have -- numbering an arbitrary order would dress the accident up as a ranking."""
        self._flat(settings, "AAA", 100.0)
        self._flat(settings, "BBB", 300.0)

        cards = {_FIRST: _card(_FIRST, universe=("AAA", "BBB"), entry="close > 0")}
        _install(monkeypatch, cards=cards, results={_FIRST: _result(cards[_FIRST])})

        body = client.get("/api/paperdesk/state").json()
        b = next(d for d in _desks(body) if d["agent_id"] == _FIRST)

        assert b["rank_by"] is None
        assert [s["symbol"] for s in b["signals"]] == ["AAA", "BBB"]
        assert all(s["rank_value"] is None for s in b["signals"])
        assert all(s["entry_rank"] is None for s in b["signals"])


# ---------------------------------------------------------------------------
# 11. The roster is a configuration value, not a source-code constant -- and correct for any size
# ---------------------------------------------------------------------------


class TestConfigurableRoster:
    """`app.config.Settings.paperdesk_agent_ids` is the mechanism: unset (the default), the desk
    falls back to `desk.AGENT_IDS`, the same three cards it has always traded; set to a JSON array
    of agent ids, `desk.roster` returns that instead. These tests exercise both sides of that
    fallback, plus the actual case round 6 will hit: a four-card roster producing four desks, in the
    configured order, without any part of this module assuming exactly three."""

    def test_default_roster_is_round_elevens_selection_plus_the_override(
        self, settings: Settings
    ) -> None:
        """No env var set: `desk.roster` returns `desk.AGENT_IDS` -- round 11's three ranked seats,
        plus one the owner added against the distinctness rule, plus the ladder.

        Round 11 implemented "fix 4": the live out-of-sample record, cut into six contiguous
        sub-periods, became the ranking criterion, and the backtest gates became floors (Gate A,
        Gate L) or a tie-break (Gate S'). It seated `B3-concentrated`, `A-rotation` and `C-trend`.

        **`B-momentum` is here by owner override** (`data/rounds/r11-2026-08/SELECTION.md` section
        8), and it is a different kind of override from rounds 8 and 10. Those disputed *which card
        is better*. This one does not -- `B3-concentrated` still outranks `B-momentum` on the live
        record and still holds the ranked momentum seat. What is overridden is **distinctness**: the
        rule that at most one card per base family may be seated.

        The two are not redundant in the way that rule assumes. `B3-concentrated`'s holdings are a
        strict subset of `B-momentum`'s -- the same four names plus two more -- because they share
        every entry and exit rule and differ only in slot count and position size. Seating both shows
        one idea at two breadths, which is legible; it also means two of five panels agree almost
        entirely, which overstates how much independent evidence the page carries.

        The tuple is repeated here as a literal rather than compared only against `desk.AGENT_IDS`,
        so that re-rostering the desk is a deliberate two-file edit and cannot happen as a side
        effect of some other change. When a later round re-selects, this list moves with it and the
        diff names the round that did it.

        **This tuple briefly held the `-cap126` variants on 2026-08-30 (`a81fcb6`) and was reverted
        the same day.** Round 24 found both momentum cards in breach of their own account:
        `PurposeSpec.horizon_months_max` bounded the trading book at six months, `max_hold_days`
        counts **sessions**, and 180 sessions is ~8.6 calendar months. At `as_of` 2026-08-28 both
        held MRVL entered 2026-03-11 -- 118 sessions, eight short of the line, with 62 still to run.

        Six-month variants were built and measured (`strategy-program/ROUND-24-PLAN.md`, cards frozen
        at `9dcd283`): capping cost `B3-concentrated` -5.07pp of median adjusted excess and
        `B-momentum` -0.19pp on the r2 regime matrix, both inside the 21.2pp ordering floor and both
        confined to `chop-2015`. **The owner resolved the conflict by moving the bound instead** --
        `horizon_months_max` 6 -> 9, the smallest whole month count admitting a 180-session hold --
        so the cards are unchanged and this tuple is back to round 11's selection plus the override.

        The two `-cap126` cards remain in `library/variants/`, unseated. They are pre-registered
        one-decision variants with a measured result behind them; keeping them costs nothing and
        deleting them would erase round 24's second arm.

        **`ladder-qld-schd` was unseated the same day, and for the same mandate, on a measurement.**
        It had held a fifth seat since round 6 as a reference signal outside the competition. A
        `LadderCard` carries no `max_hold_days` -- it re-weights sleeves and never goes to cash -- so
        no horizon check had anything to read on it. `strategy-program/tools/ladder_horizon.py`
        measured it off the real engine's trade log instead: twelve armed cycles, nine inside nine
        months, but **2022-07-22 -> 2024-04-17 is 20.9 months and 2008-03-25 -> 2013-06-11 is 62.5**.
        Neither long-horizon book can take it -- `ROTH` by disjointness (`SCHD` is a sleeve of the
        taxable savings card) and `SAVINGS` by the mandate that dropped `qld-schd-sgov` for holding
        `QLD` -- so it is unseated rather than moved, and stays in the library unretired.

        `ladder-sso-vig-bnd` posts an identical 62.6-month longest stretch and **stays seated on
        `ROTH`**, whose `horizon_months_max` is `None`. That pairing is the control: same state
        machine, same horizon, legal on a long book and not on a short one.

        **`I-13f-duquesne-2026q2` was seated on 2026-08-30 by owner decision, and it is the first
        card here that no gate has ranked.** It is the first `desk_only` card
        (`app.tournament.models.StrategyCard.desk_only`): its `designed_through` is 2026-08-14, the
        date the 13F its universe came from became public, which is after the tournament's design
        cutoff and one day before `desk.INCEPTION`. It cannot enter a round at all --
        `app.tournament.jobs._resolve_cards` refuses it -- so it has no gate result and never will.
        It is seated because the property it has is one no backtested card can have: a 13F basket
        trading a window that opens after the filing it was derived from.

        **Being in this tuple does not mean it renders.** `_book` skips a `desk_only` card whose
        `designed_through` is not before the desk's *effective* inception, which an operator can move
        below the default through `data/paperdesk/inception.json`. See
        `test_default_roster_is_round_elevens_selection_plus_the_override` for the assertion that
        tracks what is actually rendered, which is deliberately a different question from this one.
        """
        # `r40-rsi-confirm-slots6` joined the trading book on 2026-09-09 by owner decision, on no
        # gate -- round 40's sole positive cell, inside the noise floor, from a measurement round.
        # Recorded on `AGENT_IDS` itself and in PROTOCOL.md section 9; the literal moves with it so
        # re-rostering the trading book stays a deliberate two-file edit.
        assert desk.AGENT_IDS == (
            "B3-concentrated",
            "A-rotation",
            "C-trend",
            "B-momentum",
            "I-13f-duquesne-2026q2",
            "r40-rsi-confirm-slots6",
        )
        assert "ladder-qld-schd" not in desk.AGENT_IDS
        # `r34-ma-crossover-on` joined the Roth book on 2026-09-09 by owner decision, on no gate --
        # round 34's best cell, inside the noise floor, from a measurement round that pre-registered
        # "nothing promoted". Recorded on `ROTH_AGENT_IDS` itself and in PROTOCOL.md section 9; this
        # literal moves with it so re-rostering the Roth book stays a deliberate two-file edit too.
        assert desk.ROTH_AGENT_IDS == ("ladder-sso-vig-bnd", "r34-ma-crossover-on")
        assert desk.roster(settings) == desk.AGENT_IDS

    def test_four_agent_roster_produces_four_desks_in_configured_order(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The case this change exists for: round 6 will point `INVDASH_PAPERDESK_AGENT_IDS` at
        four selected cards. Nothing about the response shape (a `list[Desk]`, never a fixed-arity
        model) or the assembly loop in `desk._compute` is sized to three, so four must work exactly
        the same way three does today."""
        four = ("B-momentum", "C-trend", "c14-riskmanaged-wide", "D-fourth")
        monkeypatch.setenv("INVDASH_PAPERDESK_AGENT_IDS", json.dumps(four))
        get_settings.cache_clear()

        cards = {
            agent_id: _card(agent_id, **_CARD_SPECS.get(agent_id, _GENERIC_SPEC))
            for agent_id in four
        }
        results = {agent_id: _result(card) for agent_id, card in cards.items()}
        _install(monkeypatch, cards=cards, results=results)

        body = client.get("/api/paperdesk/state").json()

        assert len(_desks(body)) == 4
        assert [d["agent_id"] for d in _desks(body)] == list(four)
        for d in _desks(body):
            assert d["starting_equity"] == "100000.00"

    def test_roster_order_is_the_response_order_even_when_it_differs_from_agent_ids(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The response's `desks` order is the *configured* roster's order, not `AGENT_IDS`'s own
        order and not the order cards happen to be looked up in -- a caller reordering the roster
        must see that reflected without any other code change."""
        # The roster's own first three, reversed -- what is under test is that the configured
        # order is honoured, not which cards are in it, so naming them positionally keeps this
        # test alive across a re-selection.
        reordered = tuple(reversed(desk.AGENT_IDS[:3]))
        monkeypatch.setenv("INVDASH_PAPERDESK_AGENT_IDS", json.dumps(reordered))
        get_settings.cache_clear()

        cards = _default_cards()
        results = {agent_id: _result(card) for agent_id, card in cards.items()}
        _install(monkeypatch, cards=cards, results=results)

        body = client.get("/api/paperdesk/state").json()
        assert [d["agent_id"] for d in _desks(body)] == list(reordered)


class TestUnknownAgentId:
    """A roster naming a card the library does not contain must fail loudly -- naming the missing
    agent id and where the library was searched -- rather than silently rendering a desk short one
    member. A silently-missing member would look identical to a card that simply holds cash, which
    is a real state this desk can be in, so the failure has to be impossible to miss instead."""

    def test_unknown_agent_id_fails_naming_the_agent_and_the_library_directory(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(desk, "_trading_window", lambda cfg: _WINDOW)
        monkeypatch.setattr(desk, "_mandate", lambda purpose: _mandate())
        # The other two books are emptied so the lookup this test exercises is the bogus trading
        # id it names -- otherwise the savings roster's own real cards are loaded first and this
        # test would pass or fail on a lookup it never mentions.
        monkeypatch.setattr(desk, "SAVINGS_AGENT_IDS", ())
        monkeypatch.setattr(desk, "ROTH_AGENT_IDS", ())
        monkeypatch.setenv("INVDASH_PAPERDESK_AGENT_IDS", json.dumps(["not-a-real-card"]))
        get_settings.cache_clear()
        cfg = get_settings()

        # `_load_card`/`_find_card` are deliberately left unpatched here, unlike every other test in
        # this file: the point is to exercise the real library lookup against a real (nonexistent)
        # library directory, not a fake.
        with pytest.raises(FileNotFoundError) as excinfo:
            desk.state(cfg)

        message = str(excinfo.value)
        assert "not-a-real-card" in message
        assert str(cfg.library_dir) in message

    def test_empty_roster_is_rejected_by_settings_before_it_ever_reaches_the_desk(self) -> None:
        """`Settings.paperdesk_agent_ids`'s own validator rejects an explicitly empty list -- a
        roster of zero cards would render an empty page with nothing saying why, and this is the
        earliest point that can be caught."""
        with pytest.raises(ValueError, match="empty"):
            Settings(paperdesk_agent_ids=())

    def test_duplicate_agent_id_in_roster_is_rejected(self, settings: Settings) -> None:
        monkeypatch_ids = ("B-momentum", "B-momentum", "C-trend")
        with pytest.raises(ValueError, match="B-momentum"):
            desk.roster(settings.model_copy(update={"paperdesk_agent_ids": monkeypatch_ids}))


# ---------------------------------------------------------------------------
# 9. Integration -- the real cards, the real store, unmonkeypatched
# ---------------------------------------------------------------------------


@requires_real_store
class TestIntegrationRealWindow:
    """No `settings` fixture here on purpose: this exercises `desk.state()` against the real
    application store and the two real strategy cards, the same invocation the router itself
    makes with no arguments.

    The window's literal dates are **not** asserted, because the store's most recent bar moves
    forward every time `/api/market/sync` runs and this suite may execute long after the window
    this package was built against was verified. The *relationship* is asserted instead: `as_of`
    equals `latest_bar` (the newest stored session is itself tradeable -- decided on the prior
    session's close, filled at its own open, both already stored; see `desk`'s module docstring for
    why this is not one session behind), independently recomputed here straight from
    `app.market.store.read_frame`, exactly the same read `desk._trading_window` itself makes.
    `first_session` and `sessions` are re-derived from that same calendar. Both were once pinned as
    literals, on the reasoning that the desk's inception is fixed -- and then the desk was backdated
    from 2026-08-01 to 2026-06-01 and the roster grew to three, breaking a test that was never about
    either fact.
    """

    def test_real_run_matches_the_stores_own_window(self) -> None:
        get_settings.cache_clear()
        cfg = get_settings()

        frame = market_store.read_frame("SPY", Interval.DAY, settings=cfg)
        dates = sorted({ts.date() for ts in frame["ts"]})
        expected_latest_bar = dates[-1]

        fastapi_app = FastAPI()
        fastapi_app.include_router(paperdesk_api.router)
        client = TestClient(fastapi_app)

        response = client.get("/api/paperdesk/state")

        assert response.status_code == 200
        body = response.json()
        assert body["latest_bar"] == expected_latest_bar.isoformat()
        # The core relationship this fix restores: the newest stored session is itself tradeable.
        assert body["as_of"] == body["latest_bar"] == expected_latest_bar.isoformat()
        # Re-derived from the store's own SPY calendar rather than pinned: the inception is a
        # product decision that has already moved once (2026-08-01 -> 2026-06-01), and the window
        # grows with every `/api/market/sync`. What must hold is that the desk trades exactly the
        # stored sessions from inception through the newest bar.
        # `effective_inception`, not `desk.INCEPTION`: the constant is now the *default*, and an
        # override under `data/paperdesk/inception.json` legitimately moves the window. Reading the
        # effective value keeps this assertion about what it has always been about -- that the desk
        # trades exactly the stored sessions from wherever it starts through the newest bar -- rather
        # than about which of the two sources supplied the date.
        inception = desk.effective_inception(cfg)
        expected_sessions = [d for d in dates if inception <= d <= expected_latest_bar]
        assert body["first_session"] == expected_sessions[0].isoformat()
        assert body["sessions"] == len(expected_sessions)

        # The roster is `AGENT_IDS` *followed by* whatever `data/loop/roster_overlay.json` seats, not
        # `AGENT_IDS` alone. `app.evolution.promotion` writes that overlay when a machine-proposed
        # card clears the gate twice on differing window sets, so on a machine where the loop has ever
        # promoted anything this list is legitimately longer -- and it is additive by contract, with
        # the hand-authored ids always first and never removed.
        #
        # Pinning equality here is the same mistake this test's own docstring records being made
        # twice already with `first_session` and `sessions`: asserting a fact that is free to change
        # in a test that is not about it. What must hold is the invariant the overlay actually
        # promises.
        #
        # One further subtraction, added 2026-08-30: a `desk_only` card is skipped by `_book` when
        # the desk's *effective* inception is not after its `designed_through` -- it is a card
        # waiting for a window, not a card that failed. So the invariant is that the hand-authored
        # ids appear first **in order, among those eligible to trade this window**, which is what
        # `expected_seated` below computes rather than assumes. Asserting the raw tuple here would
        # make this test fail whenever an operator moves inception backwards, which is a legitimate
        # operator action this test is not about.
        eligible: list[str] = []
        for agent_id in desk.AGENT_IDS:
            card = desk._load_card(cfg, agent_id)
            skipped = (
                getattr(card, "desk_only", False)
                and card.designed_through >= desk.effective_inception(cfg)
            )
            if not skipped:
                eligible.append(agent_id)

        seated = [d["agent_id"] for d in _desks(body)]
        assert seated[: len(eligible)] == eligible
        overlay_seats = desk._overlay_agent_ids(cfg, Purpose.TRADING, already=desk.AGENT_IDS)
        # `eligible`, not `desk.AGENT_IDS` -- same reason as above: a `desk_only` card awaiting a
        # later inception is absent from the render by design, and this line is about the overlay
        # being appended after the hand-authored ids, not about which of those ids can trade today.
        assert seated == eligible + list(overlay_seats)
        # Asserted against `PURPOSE_SPECS` rather than a literal, for the same reason `_mandate`
        # reads it rather than restating it: this desk's seed *is* the trading purpose's seed, and
        # that figure has already been changed more than once. A literal
        # here would turn the next such change into a failure that reads like a regression rather
        # than the intended edit. (The synthetic `_result` fixture above keeps its own $100,000 --
        # that number is fixture-internal and tests roster arity, not capital.)
        expected_seed = str(PURPOSE_SPECS[Purpose.TRADING].seed.quantize(Decimal("0.01")))
        for d in _desks(body):
            assert d["starting_equity"] == expected_seed


# ---------------------------------------------------------------------------
# 12. the disk cache tier: it must be fast, and it must never serve a stale book
# ---------------------------------------------------------------------------


class TestDiskCache:
    """`_cached_run` persists results between processes, so the desk's cold cost is paid once.

    The speed is the easy half. The half worth testing is invalidation: a disk cache keyed on too
    little would serve yesterday's book under today's card name, indefinitely and silently, and the
    page has no way to notice. So the key carries a digest of the card itself, and the test below
    edits a card and asserts the desk recomputes.
    """

    def _run_once(self, settings: Settings, card: StrategyCard, calls: dict[str, int]) -> AgentResult:
        def fake_run_card(
            card: StrategyCard, *, settings: Settings, mandate: Mandate, start: dt.date, end: dt.date
        ) -> AgentResult:
            calls["count"] += 1
            return _result(card)

        original = desk.run_card
        desk.run_card = fake_run_card  # type: ignore[assignment]
        try:
            return desk._cached_run(card, settings=settings, mandate=_mandate(), window=_WINDOW)
        finally:
            desk.run_card = original  # type: ignore[assignment]

    def test_a_second_process_reads_the_result_instead_of_recomputing(self, settings: Settings) -> None:
        card = _card("B-momentum")
        calls = {"count": 0}

        self._run_once(settings, card, calls)
        assert calls["count"] == 1

        desk.clear_cache()  # simulate a restart: memory gone, disk intact
        self._run_once(settings, card, calls)
        assert calls["count"] == 1, "the disk tier should have served this without a recompute"

    def test_editing_the_card_invalidates_the_entry(self, settings: Settings) -> None:
        """The failure this tier could otherwise cause, and the reason the key carries a digest."""
        calls = {"count": 0}
        self._run_once(settings, _card("B-momentum", stop_loss_pct=Decimal("0.12")), calls)
        assert calls["count"] == 1

        desk.clear_cache()
        # Same agent id, same window, different risk control.
        self._run_once(settings, _card("B-momentum", stop_loss_pct=Decimal("0.05")), calls)
        assert calls["count"] == 2, "a changed card must not be served from the old card's entry"

    def test_a_corrupt_entry_recomputes_rather_than_failing(self, settings: Settings) -> None:
        card = _card("B-momentum")
        calls = {"count": 0}
        self._run_once(settings, card, calls)

        written = list((settings.cache_dir / "paperdesk").glob("*.json"))
        assert written, "nothing was persisted"
        written[0].write_text("{ this is not a result", encoding="utf-8")

        desk.clear_cache()
        result = self._run_once(settings, card, calls)
        assert calls["count"] == 2
        assert result.card.agent_id == "B-momentum"

    def test_clear_disk_cache_removes_what_it_wrote(self, settings: Settings) -> None:
        self._run_once(settings, _card("B-momentum"), {"count": 0})
        assert desk.clear_disk_cache(settings) == 1
        assert desk.clear_disk_cache(settings) == 0

    def test_an_agent_id_cannot_escape_the_cache_directory(self, settings: Settings) -> None:
        """Card ids are analyst-supplied and reach the filesystem, so they are reduced, not trusted."""
        key = ("../../etc/passwd", _WINDOW.inception, _WINDOW.as_of, _WINDOW.latest_bar, "deadbeef")
        path = desk._disk_cache_path(settings, key)
        assert desk._disk_cache_dir(settings) == path.parent

    def test_switching_the_roster_reuses_survivors_and_never_mixes_up_a_new_member(
        self, settings: Settings
    ) -> None:
        """The cache key is per-card (`agent_id`, window, card digest) -- it was never per-roster,
        and it must stay that way once the roster is configurable. A roster switch that drops one
        card and adds another must not recompute the card that stayed (its own result does not
        depend on who else is on the desk) and must not serve the new card anything computed for a
        different agent id under a shared "roster" or "slot index" key -- the two failure modes a
        cache keyed on the roster as a whole, or on position within it, would each produce."""
        calls = {"count": 0}
        survivor = _card("X-card")
        outgoing = _card("Y-card")
        incoming = _card("Z-card")

        # Roster A: {X, Y}.
        self._run_once(settings, survivor, calls)
        self._run_once(settings, outgoing, calls)
        assert calls["count"] == 2

        desk.clear_cache()  # simulate a restart between the two roster configurations

        # Roster B: {X, Z} -- Y dropped, Z added, X kept.
        result_x = self._run_once(settings, survivor, calls)
        result_z = self._run_once(settings, incoming, calls)

        assert calls["count"] == 3, (
            "X survived the roster switch and should have been served from its own disk entry, "
            "not recomputed just because the roster around it changed"
        )
        assert result_x.card.agent_id == "X-card"
        assert result_z.card.agent_id == "Z-card"


# ---------------------------------------------------------------------------
# 13. three books: one per purpose, each funded and benchmarked on its own terms
# ---------------------------------------------------------------------------


class TestThreeBooks:
    """`strategy-program/THREE-PURPOSES-PLAN.md` section 2: one leaderboard cannot rank three
    purposes, because a book funded monthly and a book funded once are not being asked the same
    question. These assert the response actually keeps them apart rather than merely nesting the old
    flat list one level deeper."""

    def test_every_purpose_gets_a_book_even_with_no_cards_seated(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty book renders; it is not omitted.

        A hidden book reads as a purpose that does not exist, which is exactly wrong for a purpose
        that is defined and funded but has no card designed for it yet."""
        cards = {_FIRST: _card(_FIRST)}
        _install(monkeypatch, cards=cards, results={_FIRST: _result(cards[_FIRST])})
        monkeypatch.setattr(desk, "SAVINGS_AGENT_IDS", ())
        monkeypatch.setattr(desk, "ROTH_AGENT_IDS", ())

        books = _books(client.get("/api/paperdesk/state").json())

        assert [b["purpose"] for b in books.values()] == ["savings", "trading", "roth"]
        assert books["savings"]["desks"] == []
        assert books["roth"]["desks"] == []
        assert books["trading"]["desks"] != []

    def test_each_book_reports_its_own_purposes_funding(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Funding is echoed from `PURPOSE_SPECS`, so the page and the scorer cannot disagree about
        what a purpose is funded with."""
        cards = {_FIRST: _card(_FIRST)}
        _install(monkeypatch, cards=cards, results={_FIRST: _result(cards[_FIRST])})

        books = _books(client.get("/api/paperdesk/state").json())

        for purpose, book in books.items():
            spec = PURPOSE_SPECS[Purpose(purpose)]
            assert book["funding"]["shape"] == spec.funding_shape.value
            assert book["funding"]["seed"] == str(spec.seed)
            assert book["funding"]["tax_treatment"] == spec.tax_treatment.value

        # `trading`'s `horizon_years_max` is `None`, and since 2026-08-29 that no longer means
        # "unbounded". The owner bounded trading in months -- six on 2026-08-29, nine on 2026-08-30,
        # when round 24 found two seated cards could not honour six. A month bound cannot be stated
        # in whole years without misleading either way, so it lives in
        # `horizon_months_max` and the years field stayed `None`. A renderer that reads only the
        # years field will now say "unbounded" about the most tightly bounded book in the system --
        # asserted together here so that trap is visible at the point it would be introduced.
        assert books["trading"]["funding"]["horizon_years_max"] is None
        assert PURPOSE_SPECS[Purpose.TRADING].horizon_months_max == 9
        assert books["savings"]["funding"]["horizon_years_max"] == 20

    def test_roth_opens_with_its_seed(self) -> None:
        """`ROTH` carries a seed -- an existing IRA balance the account already has at
        inception. See `PurposeSpec.seed`'s own docstring for the history of this figure (it was
        `Decimal("0")` before 2026-08-24).

        Renamed 2026-08-29: this test was called `test_a_contribution_funded_book_opens_with_its_seed`
        while `ROTH` was funded annually on top of the seed. Every ongoing
        contribution was removed from all three purposes on that date, so there is no contribution-funded book
        left for the old name to describe -- the assertions below are unchanged and still correct."""
        assert PURPOSE_SPECS[Purpose.ROTH].seed == Decimal("30000")
        assert desk.opening_capital(PURPOSE_SPECS[Purpose.ROTH]) == Decimal("30000.00")
        # A lump-sum purpose is unaffected: its seed is its opening capital, full stop.
        assert desk.opening_capital(PURPOSE_SPECS[Purpose.TRADING]) == Decimal("60000.00")
        assert desk.opening_capital(PURPOSE_SPECS[Purpose.SAVINGS]) == Decimal("100000.00")

    def test_opening_capital_falls_back_to_contribution_when_seed_is_zero(self) -> None:
        """No purpose in `PURPOSE_SPECS` has a zero seed as of 2026-08-24 -- `ROTH`'s own seed was
        the last one to be zero, until this date -- so `desk.opening_capital`'s fallback-to-
        `contribution` branch is no longer exercised by any real purpose. It is exercised here
        directly, against a synthetic `PurposeSpec`, so the guard `opening_capital`'s own docstring
        says is "currently unreached, not dead" stays proven rather than merely asserted."""
        # Both fields are overridden as of 2026-08-29. `ROTH`'s own contribution is now `0` too --
        # the owner removed every ongoing contribution -- so copying the real spec and zeroing only
        # the seed would produce a spec with nothing to fall back *to*, and the assertion would pass
        # against `0 == 0` while exercising none of the branch it exists to prove.
        spec = PURPOSE_SPECS[Purpose.ROTH].model_copy(
            update={"seed": Decimal("0"), "contribution": Decimal("7500")}
        )
        assert desk.opening_capital(spec) == Decimal("7500.00")

    def test_no_book_discloses_unmodelled_contributions_now_that_none_has_any(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The desk trades a static book, and the note exists to disclose the gap when a purpose is
        actually funded by a stream of deposits the desk does not model.

        **All three purposes became lump sums on 2026-08-29, so the gap this note discloses no longer
        exists for any book and the note correctly stops firing everywhere.** That is the whole
        assertion. Before that date this test was called
        `test_a_contribution_funded_book_says_contributions_are_not_modelled` and asserted the note
        on `savings` and `roth` and its absence on `trading`.

        `_funding_note`'s non-`LUMP_SUM` branch is now unreached by any real purpose. It is retained
        rather than deleted, for the reason `opening_capital`'s own docstring gives about its
        equivalent guard -- contribution funding has been used once and may return, and
        re-deriving the disclosure later costs more than keeping it.
        `test_the_contribution_note_still_fires_for_a_contribution_funded_spec` below covers the
        branch directly against a synthetic spec, so "unreached in production" does not silently
        become "untested"."""
        cards = {_FIRST: _card(_FIRST)}
        _install(monkeypatch, cards=cards, results={_FIRST: _result(cards[_FIRST])})

        books = _books(client.get("/api/paperdesk/state").json())

        for purpose in ("savings", "roth", "trading"):
            assert not any("does not model them" in n for n in books[purpose]["notes"]), (
                f"{purpose} is a lump sum and has no unmodelled contribution stream to disclose"
            )

    def test_the_live_rosters_are_actually_disjoint(self) -> None:
        """`find_disjointness_violations` is the *preventive* half of the wash-sale problem -- it
        exists so a Roth card and a taxable card never name the same ticker, because a replacement
        bought inside an IRA **destroys** the loss outright (Rev. Rul. 2008-5) rather than deferring
        it. Until 2026-08-29 every test of it built synthetic cards, so the invariant had never once
        been pointed at **the cards actually being traded**. This does that.

        Loading the real rosters also means this fails if a future roster edit -- by hand or by the
        evolution loop's overlay -- seats a Roth card sharing a ticker with a taxable one. That is
        the failure mode the invariant exists for, and nothing was watching for it on live data.

        **A caveat this test cannot check, recorded where someone will read it.** Passing here means
        only that no *ticker* is shared. IRC §1091 turns on securities being *substantially
        identical*, and the current rosters are close to the adversarial case for that distinction:
        the Roth holds **BND** while savings holds **AGG** (both broad US investment-grade aggregate
        bond index funds), and **VIG** against savings' and the trading ladder's **SCHD** (both US
        dividend funds). The Roth ladder was made disjoint by substituting near-equivalents, which is
        exactly the construction ticker-equality cannot see. See
        `strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md` §7b; the resolution is a tax professional's, not
        a stricter check's.

        **The autopilot seat is checked too, by a different route, because it has no card.** It sits
        on the trading (taxable) roster and `_load_card` cannot resolve it -- it is a ledger, not a
        `StrategyCard` -- so it cannot go through `find_disjointness_violations` with the rest. Simply
        skipping it would be the wrong fix and a silent hole: this is the one seat whose tickers are
        *chosen at runtime* by a screen rather than declared up front, so it is the single most likely
        way a Roth ticker ever lands in a taxable book. Its actual traded symbols are asserted against
        the Roth cards' universes directly, below.
        """
        settings = get_settings()
        # `rosters`, not `seats`: this walks ids into `_load_card`, and `rosters` is precisely the
        # "which cards" half of that split (see `desk.seats`' own docstring). The autopilot seat is
        # covered separately below, by the only route that can check it.
        cards = [
            desk._load_card(settings, agent_id)
            for ids in desk.rosters(settings).values()
            for agent_id in ids
        ]
        assert cards, "no cards loaded -- this test would pass vacuously"
        roth = [c for c in cards if str(getattr(c, "purpose", "")) == "roth"]
        assert roth, "no roth-purpose card is seated, so disjointness proves nothing here"

        assert find_disjointness_violations(cards) == ()

        # The autopilot seat's own half of the same invariant. Empty is the ordinary state before its
        # first order and makes this assertion vacuous rather than wrong -- which is why it is stated
        # as a set intersection rather than a count: it stays correct on the day the book fills, and
        # that is the day it starts mattering.
        roth_tickers = {ticker for card in roth for ticker in getattr(card, "universe", ())}
        autopilot_tickers = set(autopilot_mod.universe_symbols(settings))
        assert autopilot_tickers & roth_tickers == set(), (
            "the autopilot seat has traded a ticker the Roth book also holds. It trades a taxable "
            "book, so a replacement bought inside the IRA destroys the loss outright rather than "
            "deferring it (Rev. Rul. 2008-5). Its universe is chosen at runtime by the screened "
            "selector, so this cannot be fixed by editing a card -- exclude the ticker from the "
            f"selector's candidate pool: {sorted(autopilot_tickers & roth_tickers)}"
        )

    def test_the_contribution_note_still_fires_for_a_contribution_funded_spec(self) -> None:
        """The retained branch, proven rather than assumed.

        No real purpose has selected `MONTHLY_CONTRIBUTION` or `ANNUAL_CONTRIBUTION` since
        2026-08-29, so without this test `_funding_note`'s disclosure branch would be retained code
        that nothing exercises -- and the day the owner restores a contribution, its first exercise
        would be in production. Asserted against a synthetic spec, the same way
        `test_opening_capital_falls_back_to_contribution_when_seed_is_zero` keeps
        `opening_capital`'s equivalent guard proven."""
        monthly = PURPOSE_SPECS[Purpose.SAVINGS].model_copy(
            update={
                "funding_shape": FundingShape.MONTHLY_CONTRIBUTION,
                "contribution": Decimal("1000"),
            }
        )
        note = desk._funding_note(monthly)
        assert note, "a contribution-funded spec must disclose that the desk does not model it"
        assert "does not model them" in note[0]
        assert "every month" in note[0]

        annual = PURPOSE_SPECS[Purpose.ROTH].model_copy(
            update={
                "funding_shape": FundingShape.ANNUAL_CONTRIBUTION,
                "contribution": Decimal("7500"),
            }
        )
        assert "every year" in desk._funding_note(annual)[0]

        # And the branch under every live purpose today: nothing to disclose.
        assert desk._funding_note(PURPOSE_SPECS[Purpose.SAVINGS]) == []

    def test_a_card_rostered_into_the_wrong_book_is_refused(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A mis-rostered card would be funded with the wrong book's capital and scored against the
        wrong book's benchmark while its own declaration said otherwise."""
        cards = {agent_id: _card(agent_id) for agent_id in desk.AGENT_IDS}
        cards["mis-rostered"] = _card("mis-rostered")
        results = {agent_id: _result(card) for agent_id, card in cards.items()}
        _install(monkeypatch, cards=cards, results=results)
        # A plain `StrategyCard` defaults to `trading`; rostering it in the Roth book is the error.
        monkeypatch.setattr(desk, "ROTH_AGENT_IDS", ("mis-rostered",))

        with pytest.raises(ValueError) as excinfo:
            desk.state(settings)

        message = str(excinfo.value)
        assert "mis-rostered" in message
        assert "trading" in message and "roth" in message


class TestExcessMatchesTheDisplayedBenchmark:
    """`total_return - benchmark` must equal the reported `excess_return`, on every desk of every
    book.

    This did not hold before the books existed, and the discrepancy was invisible rather than loud:
    each builder set `excess_return` from the *engine's* SPY figure, measured over the sessions the
    card actually traded, while the benchmark rendered beside it was priced over the window's stored
    bars. Two clocks, one subtraction, no way for a reader checking it by hand to see why it did not
    come out. With three books it would also have been the wrong *index* for two of them."""

    def test_every_desk_reconciles_against_its_own_books_benchmark(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cards = {agent_id: _card(agent_id) for agent_id in desk.AGENT_IDS}
        results = {agent_id: _result(card) for agent_id, card in cards.items()}
        _install(monkeypatch, cards=cards, results=results)
        # The temp store holds AAA/BBB and no index, so the real benchmark prices to `None` -- which
        # this test would then vacuously pass (the `checked > 0` guard below is what caught that).
        # A fixed, non-null figure is supplied so the subtraction is actually exercised.
        monkeypatch.setattr(
            desk,
            "_book_benchmarks",
            lambda cfg, spec, window: [
                Benchmark(symbol=spec.benchmark, return_pct=Decimal("0.0123"), label="stub")
            ],
        )

        books = _books(client.get("/api/paperdesk/state").json())

        checked = 0
        for book in books.values():
            benchmark = book["benchmark"]["return_pct"]
            for d in book["desks"]:
                if benchmark is None:
                    assert d["excess_return"] is None
                    continue
                expected = Decimal(d["total_return"]) - Decimal(benchmark)
                assert Decimal(d["excess_return"]) == expected, d["agent_id"]
                checked += 1
        assert checked > 0, "no desk was actually checked -- the assertion above proved nothing"


# ---------------------------------------------------------------------------
# 14. Inception override -- settable at runtime, persisted to disk
# ---------------------------------------------------------------------------
#
# Every test below uses the `settings` fixture's temp `INVDASH_DATA_DIR`, never the real `data/` --
# `desk.inception_override_path` is a `settings.data_dir` join, so pointing `settings` at `tmp_path`
# (which the fixture already does) is what keeps `set_inception`/`clear_inception` off the real
# override file. Tests that need a real trading window write synthetic SPY bars via `_spy_bars` into
# the same temp store every other real-window test in this file already writes into; tests that only
# care about the response shape reuse `_install`'s window mock like every other test above them.


class TestInceptionDefault:
    """No override file is the ordinary state -- most servers never call `set_inception`."""

    def test_no_override_file_is_the_default(self, settings: Settings) -> None:
        assert not desk.inception_override_path(settings).is_file()
        assert desk.effective_inception(settings) == desk.INCEPTION

    def test_state_reports_inception_is_custom_false(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cards = _default_cards()
        results = {agent_id: _result(card) for agent_id, card in cards.items()}
        _install(monkeypatch, cards=cards, results=results)

        body = client.get("/api/paperdesk/state").json()

        assert body["inception_is_custom"] is False
        assert body["inception_default"] == desk.INCEPTION.isoformat()
        assert body["design_cutoff"] == DESIGN_THROUGH.isoformat()


class TestInceptionOverrideChangesTheWindow:
    """The whole point of the feature: a changed inception must actually move the trading window,
    not just echo back on the response."""

    def test_setting_an_earlier_inception_moves_first_session_and_grows_sessions(
        self, settings: Settings
    ) -> None:
        _write_bars(settings, "SPY", _spy_bars(dt.date(2026, 1, 1), dt.date(2026, 8, 21)))

        default_window = desk._trading_window(settings)
        assert default_window.inception == desk.INCEPTION

        desk.set_inception(dt.date(2026, 3, 2), settings=settings)
        custom_window = desk._trading_window(settings)

        assert custom_window.inception == dt.date(2026, 3, 2)
        assert custom_window.first_session != default_window.first_session
        assert custom_window.sessions > default_window.sessions
        # Only the start moved -- both windows still end on the same newest stored bar.
        assert custom_window.latest_bar == default_window.latest_bar == dt.date(2026, 8, 21)


class TestMalformedOverrideFallsBack:
    """A present-but-unusable override file must log and fall back to `INCEPTION`, never raise --
    this module has a recorded incident (`_overlay_agent_ids`'s own docstring) where trusting a
    small persisted override enough to raise on it took a page and every book on it down over one
    bad value, and inception is a worse place for that than a roster."""

    def _write_override(self, settings: Settings, content: str) -> Path:
        path = desk.inception_override_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_invalid_json_falls_back_without_raising(
        self, settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._write_override(settings, "{ this is not valid json")

        with caplog.at_level(logging.WARNING, logger="app.paperdesk.desk"):
            result = desk.effective_inception(settings)

        assert result == desk.INCEPTION
        assert any("unreadable" in r.message for r in caplog.records)

    def test_missing_inception_key_falls_back_without_raising(self, settings: Settings) -> None:
        self._write_override(settings, json.dumps({"not_inception": "2026-03-02"}))
        assert desk.effective_inception(settings) == desk.INCEPTION

    def test_non_string_inception_value_falls_back_without_raising(self, settings: Settings) -> None:
        self._write_override(settings, json.dumps({"inception": 20260302}))
        assert desk.effective_inception(settings) == desk.INCEPTION

    def test_unparseable_date_string_falls_back_without_raising(self, settings: Settings) -> None:
        self._write_override(settings, json.dumps({"inception": "not-a-date"}))
        assert desk.effective_inception(settings) == desk.INCEPTION

    def test_a_malformed_override_reports_inception_is_custom_false(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        self._write_override(settings, "{ not valid json")
        cards = _default_cards()
        results = {agent_id: _result(card) for agent_id, card in cards.items()}
        _install(monkeypatch, cards=cards, results=results)

        body = client.get("/api/paperdesk/state").json()

        assert body["inception_is_custom"] is False


class TestInceptionValidation:
    """`set_inception` refuses a date it cannot actually trade from, rather than clamping it -- see
    `desk._validate_inception`'s own docstring for the three distinct refusals."""

    def test_date_after_the_latest_stored_bar_is_rejected(self, settings: Settings) -> None:
        _write_bars(settings, "SPY", _spy_bars(dt.date(2026, 1, 1), dt.date(2026, 8, 21)))

        with pytest.raises(desk.InceptionRejected, match="after the latest stored"):
            desk.set_inception(dt.date(2026, 9, 1), settings=settings)

    def test_date_before_the_earliest_stored_bar_is_rejected(self, settings: Settings) -> None:
        _write_bars(settings, "SPY", _spy_bars(dt.date(2026, 1, 1), dt.date(2026, 8, 21)))

        with pytest.raises(desk.InceptionRejected, match="before the earliest stored"):
            desk.set_inception(dt.date(2025, 12, 1), settings=settings)

    def test_the_very_first_stored_bar_yields_zero_sessions_and_is_rejected(
        self, settings: Settings
    ) -> None:
        """Inside the stored range and yet untradeable: the first stored bar has no prior session to
        decide on, which `SessionCalendar` itself refuses -- a third, distinct refusal from "after
        the latest bar" and "before the earliest bar"."""
        _write_bars(settings, "SPY", _spy_bars(dt.date(2026, 1, 1), dt.date(2026, 8, 21)))

        with pytest.raises(desk.InceptionRejected, match="zero trading sessions"):
            desk.set_inception(dt.date(2026, 1, 1), settings=settings)

    def test_a_rejected_date_never_persists_an_override(self, settings: Settings) -> None:
        _write_bars(settings, "SPY", _spy_bars(dt.date(2026, 1, 1), dt.date(2026, 8, 21)))

        with pytest.raises(desk.InceptionRejected):
            desk.set_inception(dt.date(2026, 9, 1), settings=settings)

        assert not desk.inception_override_path(settings).is_file()

    def test_api_maps_a_rejected_date_to_422_naming_the_reason(
        self, client: TestClient, settings: Settings
    ) -> None:
        _write_bars(settings, "SPY", _spy_bars(dt.date(2026, 1, 1), dt.date(2026, 8, 21)))

        response = client.put("/api/paperdesk/inception", json={"inception": "2026-09-01"})

        assert response.status_code == 422
        assert "after the latest stored" in response.json()["detail"]

    def test_api_accepts_a_valid_date_and_returns_the_recomputed_state(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        _write_bars(settings, "SPY", _spy_bars(dt.date(2026, 1, 1), dt.date(2026, 8, 21)))
        cards = _default_cards()
        results = {agent_id: _result(card) for agent_id, card in cards.items()}
        _install(monkeypatch, cards=cards, results=results)

        response = client.put("/api/paperdesk/inception", json={"inception": "2026-03-02"})

        assert response.status_code == 200
        assert response.json()["inception_is_custom"] is True
        assert desk.effective_inception(settings) == dt.date(2026, 3, 2)


class TestInceptionDelete:
    def test_clear_inception_restores_the_default(self, settings: Settings) -> None:
        _write_bars(settings, "SPY", _spy_bars(dt.date(2026, 1, 1), dt.date(2026, 8, 21)))
        desk.set_inception(dt.date(2026, 3, 2), settings=settings)
        assert desk.effective_inception(settings) == dt.date(2026, 3, 2)

        desk.clear_inception(settings=settings)

        assert desk.effective_inception(settings) == desk.INCEPTION
        assert not desk.inception_override_path(settings).is_file()

    def test_clearing_a_never_set_override_is_a_no_op(self, settings: Settings) -> None:
        desk.clear_inception(settings=settings)  # must not raise
        assert desk.effective_inception(settings) == desk.INCEPTION

    def test_delete_route_restores_default_and_returns_the_recomputed_state(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        cards = _default_cards()
        results = {agent_id: _result(card) for agent_id, card in cards.items()}
        _install(monkeypatch, cards=cards, results=results)
        # Seed an override file directly -- validation is not what this test is about.
        path = desk.inception_override_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"inception": "2026-03-02"}), encoding="utf-8")

        response = client.delete("/api/paperdesk/inception")

        assert response.status_code == 200
        assert not path.is_file()
        assert response.json()["inception_is_custom"] is False


class TestInSampleSessions:
    """`in_sample_sessions` is an honesty flag: how many of this window's sessions fall at or before
    `DESIGN_THROUGH`, and therefore measure a fitted period rather than a forward one. Never a
    refusal -- an operator may legitimately want to look at an in-sample window -- only a disclosure,
    on `PaperDeskState.notes`, when it is nonzero."""

    def test_sessions_before_the_cutoff_are_counted_and_a_note_is_added(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        before = [DESIGN_THROUGH - dt.timedelta(days=d) for d in (8, 6, 4, 2, 0)]
        after = [DESIGN_THROUGH + dt.timedelta(days=d) for d in (2, 4, 6)]
        window = _make_window(tuple(sorted(before + after)))

        cards = _default_cards()
        results = {agent_id: _result(card) for agent_id, card in cards.items()}
        _install(monkeypatch, cards=cards, results=results, window=window)

        body = client.get("/api/paperdesk/state").json()

        assert body["in_sample_sessions"] == 5
        assert body["sessions"] == 8
        assert any("fitted, not forward" in n for n in body["notes"])

    def test_a_window_entirely_after_the_cutoff_counts_zero_and_adds_no_note(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_dates = tuple(DESIGN_THROUGH + dt.timedelta(days=d) for d in (30, 32, 34))
        window = _make_window(session_dates)

        cards = _default_cards()
        results = {agent_id: _result(card) for agent_id, card in cards.items()}
        _install(monkeypatch, cards=cards, results=results, window=window)

        body = client.get("/api/paperdesk/state").json()

        assert body["in_sample_sessions"] == 0
        assert not any("fitted, not forward" in n for n in body["notes"])


class TestInceptionOverrideWriteIsAtomic:
    def test_a_failed_write_never_corrupts_the_existing_override(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A reader landing mid-write must never observe a half-written file. Simulated here by
        making the final `Path.replace` step fail after the temp file has already been written in
        full -- the same failure mode `set_inception`'s own docstring names -- and checking the
        destination file still holds its previous, complete value rather than something torn."""
        _write_bars(settings, "SPY", _spy_bars(dt.date(2026, 1, 1), dt.date(2026, 8, 21)))
        desk.set_inception(dt.date(2026, 3, 2), settings=settings)
        path = desk.inception_override_path(settings)
        original = path.read_text(encoding="utf-8")

        def _boom(self: Path, target: object) -> None:
            raise OSError("simulated failure between the temp write and the rename")

        monkeypatch.setattr(Path, "replace", _boom)
        with pytest.raises(OSError):
            desk.set_inception(dt.date(2026, 4, 1), settings=settings)

        # The destination was never written to directly -- only the temp file was, and the failed
        # rename left it untouched, still holding the last value that fully committed.
        assert path.read_text(encoding="utf-8") == original
        assert desk.effective_inception(settings) == dt.date(2026, 3, 2)


class TestSeatProvenanceOnTheWire:
    """`_book`'s post-loop provenance remap, end to end through `GET /api/paperdesk/state`."""

    def test_hand_authored_seats_report_owner_provenance(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every seat on the synthetic roster is hand-authored and there is no `promotions.jsonl` in
        the temp loop dir, so each desk comes back `provenance == {"source": "owner", ...}` with no
        generation -- proving the remap runs and survives serialisation, not just the unit helper."""
        cards = _default_cards()
        results = {agent_id: _result(card) for agent_id, card in cards.items()}
        _install(monkeypatch, cards=cards, results=results)

        response = client.get("/api/paperdesk/state")

        assert response.status_code == 200
        desks = _desks(response.json())
        assert desks  # the roster is non-empty
        for d in desks:
            assert d["provenance"] == {"source": "owner", "generation": None}
