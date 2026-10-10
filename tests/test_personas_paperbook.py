"""Tests for `app.personas.paperbook.build_persona_book` -- see `docs/INFLUENCER-CONTRACT.md`,
"Phase 6 -- persona paper book on the Paper Desk (pinned)", for the semantics under test. Every test
replaces `paperbook.ensure_series` with a fake so the suite never touches the network or a real bar
store, mirroring `tests/test_personas_scoring.py`'s own fixture pattern.

This is a cash-constrained trading REPLAY (rewritten from the previous unbounded equal-notional
snapshot): every dated mention is walked in order, a fresh bullish call buys `notional_per_position`
when cash allows (or closes the stalest open holding to try to raise it), and a bearish/neutral flip on
a held symbol sells it. `return_pct` everywhere is a 0-1 FRACTION, never a pre-multiplied percent.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal

import pytest

from app.config import Settings
from app.db.duck import Interval
from app.market.models import Bar, BarSeries, BarSource
from app.market.providers.base import ProviderUnavailable
from app.personas import paperbook
from app.personas.models import EpisodicNote, Persona, TickerMention

UTC = dt.UTC


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _bar(day: dt.date, close: float, *, adj_close: float | None = None) -> Bar:
    return Bar(
        ts=dt.datetime(day.year, day.month, day.day, tzinfo=UTC),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=adj_close,
    )


def _series(symbol: str, bars: Sequence[Bar]) -> BarSeries:
    return BarSeries(symbol=symbol, interval=Interval.DAY, source=BarSource.STORE, bars=list(bars))


_DEFAULT_INGESTED_AT = dt.datetime(2026, 1, 1, tzinfo=UTC)


def _note(
    *,
    note_id: str = "n1",
    published: dt.datetime | None,
    mentions: Sequence[TickerMention] = (),
    persona: str = "testpersona",
    ingested_at: dt.datetime = _DEFAULT_INGESTED_AT,
) -> EpisodicNote:
    return EpisodicNote(
        note_id=note_id,
        persona=persona,
        source_id="yt:UCXXXXXXXXXXXXXXXXXXXXXX",
        published=published,
        ingested_at=ingested_at,
        url=f"https://www.youtube.com/watch?v={note_id}",
        title="A title",
        kind="video_transcript",
        transcript_source="auto",
        lang="en",
        summary="a summary",
        themes=(),
        quotes=(),
        mentions=tuple(mentions),
        path=f"notes/{note_id}.md",
        degraded=False,
    )


def _mention(
    symbol: str, stance: str, reasoning: str = "because", *, horizon: str = "unclear"
) -> TickerMention:
    return TickerMention(  # type: ignore[arg-type]
        symbol=symbol, stance=stance, reasoning=reasoning, horizon=horizon
    )


def _persona(*, slug: str = "testpersona", display_name: str = "Test Persona") -> Persona:
    return Persona(
        slug=slug,
        display_name=display_name,
        sources=(),
        note_count=0,
        tickers=(),
        profile_version=0,
        consolidated_at=None,
        created_at=dt.datetime(2026, 1, 1, tzinfo=UTC),
    )


class _FakeEnsureSeries:
    """Records every call and answers from a fixed map: `BarSeries` to return, or an `Exception`
    instance to raise. Standing in for `app.market.store.ensure_series` in every test below."""

    def __init__(self, answers: dict[str, BarSeries | Exception]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    def __call__(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
        settings: Settings | None = None,
        **_: object,
    ) -> BarSeries:
        self.calls.append(symbol)
        answer = self.answers[symbol]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _patch(monkeypatch: pytest.MonkeyPatch, answers: dict[str, BarSeries | Exception]) -> _FakeEnsureSeries:
    fake = _FakeEnsureSeries(answers)
    monkeypatch.setattr(paperbook, "ensure_series", fake)
    return fake


INCEPTION = dt.date(2026, 1, 1)


# ---------------------------------------------------------------------------
# A single bullish buy
# ---------------------------------------------------------------------------


class TestBuy:
    def test_bullish_call_buys_notional_and_marks_to_latest_close(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 110.0)]
        _patch(monkeypatch, {"AAA": _series("AAA", bars)})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("AAA", "bullish")])

        book = paperbook.build_persona_book(persona=_persona(), notes=[note], settings=settings)

        assert len(book.holdings) == 1
        h = book.holdings[0]
        assert h.symbol == "AAA"
        assert h.stance == "bullish"
        assert h.note_id == "n1"
        assert h.entry_date == dt.date(2026, 1, 5)
        assert h.entry_price == Decimal("100")
        assert h.last_price == Decimal("110")
        assert h.quantity == (Decimal("10000") / Decimal("100")).quantize(Decimal("0.000001"))
        assert h.cost_basis == Decimal("10000.00")
        assert h.market_value == Decimal("11000.00")
        assert h.unrealised_pnl == Decimal("1000.00")
        # A 10% gain is Decimal("0.1000") -- a FRACTION, never Decimal("10.00").
        assert h.return_pct == Decimal("0.1000")
        assert h.bars_held == 1
        assert h.weight == pytest.approx(1.0)
        assert h.last_bullish_on == dt.date(2026, 1, 5)

        assert book.starting_cash == Decimal("100000.00")
        assert book.cash == Decimal("90000.00")
        assert book.cost_basis_total == Decimal("10000.00")
        assert book.market_value_total == Decimal("11000.00")
        assert book.unrealised_pnl_total == Decimal("1000.00")
        assert book.realised_pnl_total == Decimal("0.00") or book.realised_pnl_total == Decimal(0)
        assert book.equity == book.cash + book.market_value_total == Decimal("101000.00")
        assert book.return_pct == book.equity / book.starting_cash - 1
        assert book.return_pct == Decimal("0.0100")
        assert book.as_of == dt.date(2026, 1, 10)
        assert book.open_count == 1
        assert book.trade_count == 0
        assert book.trades == ()
        assert book.skipped == ()

    def test_second_bullish_call_on_held_symbol_is_a_no_op_but_bumps_last_bullish_on(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [
            _bar(dt.date(2026, 1, 5), 100.0),
            _bar(dt.date(2026, 1, 10), 105.0),
            _bar(dt.date(2026, 1, 20), 110.0),
        ]
        _patch(monkeypatch, {"AAA": _series("AAA", bars)})
        notes = [
            _note(
                note_id="n1", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("AAA", "bullish")],
            ),
            _note(
                note_id="n2", published=dt.datetime(2026, 1, 10, tzinfo=UTC),
                mentions=[_mention("AAA", "bullish")],
            ),
        ]

        book = paperbook.build_persona_book(persona=_persona(), notes=notes, settings=settings)

        assert len(book.holdings) == 1
        h = book.holdings[0]
        # Still entered at the FIRST call's price -- the second bullish mention re-affirms, it does
        # not re-buy.
        assert h.entry_date == dt.date(2026, 1, 5)
        assert h.entry_price == Decimal("100")
        assert h.last_bullish_on == dt.date(2026, 1, 10)
        assert book.cash == Decimal("90000.00")  # only ONE buy happened
        assert book.trade_count == 0


# ---------------------------------------------------------------------------
# Flips: bearish / neutral close a held position
# ---------------------------------------------------------------------------


class TestFlip:
    def test_bearish_flip_sells_a_held_position_and_realises_pnl(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [
            _bar(dt.date(2026, 1, 5), 100.0),
            _bar(dt.date(2026, 1, 15), 120.0),
        ]
        _patch(monkeypatch, {"BBB": _series("BBB", bars)})
        notes = [
            _note(
                note_id="n_buy", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("BBB", "bullish")],
            ),
            _note(
                note_id="n_sell", published=dt.datetime(2026, 1, 15, tzinfo=UTC),
                mentions=[_mention("BBB", "bearish")],
            ),
        ]

        book = paperbook.build_persona_book(persona=_persona(), notes=notes, settings=settings)

        assert book.holdings == ()
        assert len(book.trades) == 1
        t = book.trades[0]
        assert t.symbol == "BBB"
        assert t.note_id == "n_buy"
        assert t.entry_date == dt.date(2026, 1, 5)
        assert t.entry_price == Decimal("100")
        assert t.exit_date == dt.date(2026, 1, 15)
        assert t.exit_price == Decimal("120")
        assert t.reason == "flip_bearish"
        quantity = (Decimal("10000") / Decimal("100")).quantize(Decimal("0.000001"))
        assert t.quantity == quantity
        assert t.realised_pnl == (quantity * Decimal("20")).quantize(Decimal("0.01"))
        assert t.return_pct == Decimal("0.2000")

        # Cash is back: starting - notional + proceeds.
        proceeds = (quantity * Decimal("120")).quantize(Decimal("0.01"))
        assert book.cash == (Decimal("90000.00") + proceeds)
        assert book.realised_pnl_total == t.realised_pnl
        assert book.equity == book.cash  # nothing else open
        assert book.trade_count == 1
        assert book.open_count == 0
        assert book.as_of == dt.date(2026, 1, 15)

    def test_neutral_flip_also_sells_a_held_position(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 15), 90.0)]
        _patch(monkeypatch, {"CCC": _series("CCC", bars)})
        notes = [
            _note(
                note_id="n_buy", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("CCC", "bullish")],
            ),
            _note(
                note_id="n_sell", published=dt.datetime(2026, 1, 15, tzinfo=UTC),
                mentions=[_mention("CCC", "neutral")],
            ),
        ]

        book = paperbook.build_persona_book(persona=_persona(), notes=notes, settings=settings)

        assert book.holdings == ()
        assert len(book.trades) == 1
        assert book.trades[0].reason == "flip_neutral"
        assert book.trades[0].return_pct == Decimal("-0.1000")

    def test_bearish_call_on_a_symbol_never_held_is_a_no_op(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, {})  # ensure_series must never be called
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("DDD", "bearish")])

        book = paperbook.build_persona_book(persona=_persona(), notes=[note], settings=settings)

        assert book.holdings == ()
        assert book.trades == ()
        assert book.cash == book.starting_cash == Decimal("100000.00")


# ---------------------------------------------------------------------------
# Cash constraints: no_cash skip, replace_stalest
# ---------------------------------------------------------------------------


class TestCashConstraints:
    def test_no_holdings_and_insufficient_cash_skips_with_no_cash(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no open holdings to close, a buy that needs more cash than is on hand is skipped
        outright. `STARTING_CASH_USD` is monkeypatched down so this does not require ten real buys
        first to exhaust the real $100,000."""
        monkeypatch.setattr(paperbook, "STARTING_CASH_USD", Decimal("5000"))
        _patch(monkeypatch, {"EEE": _series("EEE", [_bar(dt.date(2026, 1, 5), 100.0)])})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("EEE", "bullish")])

        book = paperbook.build_persona_book(persona=_persona(), notes=[note], settings=settings)

        assert book.holdings == ()
        assert book.cash == Decimal("5000")
        assert len(book.skipped) == 1
        assert book.skipped[0] == paperbook.PersonaSkippedCall(
            symbol="EEE", said_on=dt.date(2026, 1, 5), reason="no_cash"
        )

    def test_replace_stalest_sells_the_oldest_bullish_holding_to_fund_a_new_buy(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cash starts at $15,000 -- enough for exactly one $10,000 position, leaving $5,000. A second
        bullish call needs another $10,000; the only open holding (the stalest, trivially, since it is
        the only one) is closed to raise it."""
        monkeypatch.setattr(paperbook, "STARTING_CASH_USD", Decimal("15000"))
        bars_a = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 100.0)]
        bars_b = [_bar(dt.date(2026, 1, 10), 50.0), _bar(dt.date(2026, 1, 20), 55.0)]
        _patch(monkeypatch, {"FFF": _series("FFF", bars_a), "GGG": _series("GGG", bars_b)})
        notes = [
            _note(
                note_id="n_fff", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("FFF", "bullish")],
            ),
            _note(
                note_id="n_ggg", published=dt.datetime(2026, 1, 10, tzinfo=UTC),
                mentions=[_mention("GGG", "bullish")],
            ),
        ]

        book = paperbook.build_persona_book(persona=_persona(), notes=notes, settings=settings)

        # FFF was bought then closed (reason "replaced") to fund GGG.
        assert [h.symbol for h in book.holdings] == ["GGG"]
        assert len(book.trades) == 1
        t = book.trades[0]
        assert t.symbol == "FFF"
        assert t.reason == "replaced"
        assert t.exit_date == dt.date(2026, 1, 10)
        assert t.exit_price == Decimal("100")  # flat price -- sold for exactly what it cost
        assert t.realised_pnl == Decimal("0.00")

        # $5,000 leftover + $10,000 raised from selling FFF = $15,000, minus the $10,000 GGG buy.
        assert book.cash == Decimal("5000.00")
        assert book.skipped == ()

    def test_no_cash_after_replace_stalest_exhausts_every_holding(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When even closing every open holding cannot raise enough cash, the call is skipped -- the
        sales already made still stand."""
        monkeypatch.setattr(paperbook, "STARTING_CASH_USD", Decimal("10000"))
        # HHH craters to $1 by the time III comes bullish -- selling it raises almost nothing.
        bars_h = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 1.0)]
        bars_i = [_bar(dt.date(2026, 1, 10), 50.0)]
        _patch(monkeypatch, {"HHH": _series("HHH", bars_h), "III": _series("III", bars_i)})
        notes = [
            _note(
                note_id="n_hhh", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("HHH", "bullish")],
            ),
            _note(
                note_id="n_iii", published=dt.datetime(2026, 1, 10, tzinfo=UTC),
                mentions=[_mention("III", "bullish")],
            ),
        ]

        book = paperbook.build_persona_book(persona=_persona(), notes=notes, settings=settings)

        assert book.holdings == ()  # HHH was sold trying to fund III; III itself never bought
        assert len(book.trades) == 1
        assert book.trades[0].symbol == "HHH"
        assert book.trades[0].reason == "replaced"
        assert len(book.skipped) == 1
        assert book.skipped[0].symbol == "III"
        assert book.skipped[0].reason == "no_cash"
        assert book.cash >= Decimal(0)

    def test_full_book_replaces_the_stalest_even_with_cash_to_spare(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The book is capped by COUNT, not only by cash. With the cap at 2 and ample cash, a third
        bullish call still closes the stalest holding to make room -- a profitable book can never
        drift past the cap on paper gains."""
        monkeypatch.setattr(paperbook, "MAX_OPEN_POSITIONS", 2)
        # $1,000,000 cash: never the binding constraint, so any replacement is the count cap at work.
        monkeypatch.setattr(paperbook, "STARTING_CASH_USD", Decimal("1000000"))
        bars_j = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 20), 100.0)]
        bars_k = [_bar(dt.date(2026, 1, 6), 100.0), _bar(dt.date(2026, 1, 20), 100.0)]
        bars_l = [_bar(dt.date(2026, 1, 10), 100.0), _bar(dt.date(2026, 1, 20), 100.0)]
        _patch(
            monkeypatch,
            {"JJJ": _series("JJJ", bars_j), "KKK": _series("KKK", bars_k), "LLL": _series("LLL", bars_l)},
        )
        notes = [
            _note(
                note_id="n_jjj", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("JJJ", "bullish")],
            ),
            _note(
                note_id="n_kkk", published=dt.datetime(2026, 1, 6, tzinfo=UTC),
                mentions=[_mention("KKK", "bullish")],
            ),
            _note(
                note_id="n_lll", published=dt.datetime(2026, 1, 10, tzinfo=UTC),
                mentions=[_mention("LLL", "bullish")],
            ),
        ]

        book = paperbook.build_persona_book(persona=_persona(), notes=notes, settings=settings)

        # Cap honoured: never more than 2 open. JJJ (stalest) was replaced by LLL despite spare cash.
        assert book.open_count == 2
        assert [h.symbol for h in book.holdings] == ["KKK", "LLL"]
        assert len(book.trades) == 1
        assert book.trades[0].symbol == "JJJ"
        assert book.trades[0].reason == "replaced"
        assert book.skipped == ()


# ---------------------------------------------------------------------------
# No-ops: unclear stance, intraday horizon
# ---------------------------------------------------------------------------


class TestNoOps:
    def test_unclear_stance_is_a_no_op(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, {})  # never fetched
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("JJJ", "unclear")])

        book = paperbook.build_persona_book(persona=_persona(), notes=[note], settings=settings)

        assert book.holdings == ()
        assert book.cash == book.starting_cash

    def test_intraday_horizon_is_always_a_no_op_regardless_of_exclude_intraday(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, {})  # never fetched
        note = _note(
            published=dt.datetime(2026, 1, 5, tzinfo=UTC),
            mentions=[_mention("KKK", "bullish", horizon="intraday")],
        )

        book_default = paperbook.build_persona_book(persona=_persona(), notes=[note], settings=settings)
        book_flagged = paperbook.build_persona_book(
            persona=_persona(), notes=[note], settings=settings, exclude_intraday=True
        )

        assert book_default.holdings == () and book_default.cash == book_default.starting_cash
        assert book_flagged.holdings == () and book_flagged.cash == book_flagged.starting_cash


# ---------------------------------------------------------------------------
# No-look-ahead, on both entry and exit
# ---------------------------------------------------------------------------


class TestNoLookAhead:
    def test_entry_is_first_bar_at_or_after_date_not_prior(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        friday = dt.date(2026, 1, 2)
        monday = dt.date(2026, 1, 5)
        tuesday = dt.date(2026, 1, 6)
        bars = [_bar(friday, 100.0), _bar(monday, 200.0), _bar(tuesday, 210.0)]
        _patch(monkeypatch, {"LLL": _series("LLL", bars)})
        saturday = dt.date(2026, 1, 3)
        note = _note(
            published=dt.datetime(saturday.year, saturday.month, saturday.day, tzinfo=UTC),
            mentions=[_mention("LLL", "bullish")],
        )

        book = paperbook.build_persona_book(persona=_persona(), notes=[note], settings=settings)

        h = book.holdings[0]
        assert h.entry_date == monday
        assert h.entry_price == Decimal("200")  # not Friday's 100

    def test_exit_is_first_bar_at_or_after_date_not_prior(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [
            _bar(dt.date(2026, 1, 2), 100.0),
            _bar(dt.date(2026, 1, 5), 150.0),  # Monday
            _bar(dt.date(2026, 1, 6), 160.0),  # Tuesday
        ]
        _patch(monkeypatch, {"MMM": _series("MMM", bars)})
        saturday_sell = dt.date(2026, 1, 3)  # falls between Friday and Monday
        notes = [
            _note(
                note_id="n_buy", published=dt.datetime(2026, 1, 2, tzinfo=UTC),
                mentions=[_mention("MMM", "bullish")],
            ),
            _note(
                note_id="n_sell",
                published=dt.datetime(saturday_sell.year, saturday_sell.month, saturday_sell.day, tzinfo=UTC),
                mentions=[_mention("MMM", "bearish")],
            ),
        ]

        book = paperbook.build_persona_book(persona=_persona(), notes=notes, settings=settings)

        assert book.trades[0].exit_date == dt.date(2026, 1, 5)  # not the Friday 100 print
        assert book.trades[0].exit_price == Decimal("150")

    def test_no_entry_bar_yet_is_skipped_not_a_fabricated_pending_state(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [_bar(dt.date(2026, 1, 2), 100.0), _bar(dt.date(2026, 1, 5), 105.0)]
        _patch(monkeypatch, {"NNN": _series("NNN", bars)})
        note = _note(published=dt.datetime(2026, 1, 20, tzinfo=UTC), mentions=[_mention("NNN", "bullish")])

        book = paperbook.build_persona_book(persona=_persona(), notes=[note], settings=settings)

        assert book.holdings == ()
        assert book.skipped == (
            paperbook.PersonaSkippedCall(symbol="NNN", said_on=dt.date(2026, 1, 20), reason="no_bar_since"),
        )


# ---------------------------------------------------------------------------
# Exclude-and-warn, never a fabricated zero
# ---------------------------------------------------------------------------


class TestExcludeAndWarn:
    def test_symbol_with_no_bars_skipped_and_warned_no_market_data(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, {"OOO": _series("OOO", [])})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("OOO", "bullish")])

        book = paperbook.build_persona_book(persona=_persona(), notes=[note], settings=settings)

        assert book.holdings == ()
        assert len(book.warnings) == 1
        assert book.warnings[0].source == "OOO"
        assert book.warnings[0].reason == "no market data"
        assert book.skipped == (
            paperbook.PersonaSkippedCall(symbol="OOO", said_on=dt.date(2026, 1, 5), reason="no_market_data"),
        )
        assert book.cash == book.starting_cash

    def test_provider_error_skipped_and_warned_never_raises(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, {"PPP": ProviderUnavailable("network down", provider="yahoo")})
        note = _note(published=dt.datetime(2026, 1, 5, tzinfo=UTC), mentions=[_mention("PPP", "bullish")])

        book = paperbook.build_persona_book(persona=_persona(), notes=[note], settings=settings)

        assert book.holdings == ()
        assert any(w.source == "PPP" and w.reason == "no market data" for w in book.warnings)
        assert book.skipped[0].reason == "no_market_data"


# ---------------------------------------------------------------------------
# Cash invariants
# ---------------------------------------------------------------------------


class TestCashInvariants:
    def test_cash_never_negative_across_a_busy_replay(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(paperbook, "STARTING_CASH_USD", Decimal("10000"))
        bars = {
            sym: _series(sym, [_bar(dt.date(2026, 1, d), 100.0) for d in (5, 10, 15, 20, 25)])
            for sym in ("QQQ1", "QQQ2", "QQQ3", "QQQ4")
        }
        _patch(monkeypatch, bars)
        notes = [
            _note(
                note_id=f"n_{sym}", published=dt.datetime(2026, 1, 5 + i * 5, tzinfo=UTC),
                mentions=[_mention(sym, "bullish")],
            )
            for i, sym in enumerate(("QQQ1", "QQQ2", "QQQ3", "QQQ4"))
        ]

        book = paperbook.build_persona_book(persona=_persona(), notes=notes, settings=settings)

        assert book.cash >= Decimal(0)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


class TestEnvelope:
    def test_persona_and_inception_fields(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, {})

        book = paperbook.build_persona_book(
            persona=_persona(slug="creator-a", display_name="Creator A"),
            notes=[],
            settings=settings,
        )

        assert book.persona == "creator-a"
        assert book.display_name == "Creator A"
        assert book.inception == paperbook.DEFAULT_INCEPTION
        assert book.notional_per_position == Decimal("10000.00")
        assert book.starting_cash == Decimal("100000.00")
        assert book.cash == Decimal("100000.00")
        assert book.equity == Decimal("100000.00")
        assert book.return_pct == Decimal("0.0000") or book.return_pct == Decimal(0)
        assert book.holdings == ()
        assert book.trades == ()
        assert book.skipped == ()
        assert book.as_of is None
        assert book.open_count == 0
        assert book.trade_count == 0

    def test_custom_inception_and_notional(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [_bar(dt.date(2026, 3, 1), 50.0), _bar(dt.date(2026, 3, 10), 55.0)]
        _patch(monkeypatch, {"RRR": _series("RRR", bars)})
        note = _note(published=dt.datetime(2026, 3, 1, tzinfo=UTC), mentions=[_mention("RRR", "bullish")])

        book = paperbook.build_persona_book(
            persona=_persona(),
            notes=[note],
            settings=settings,
            inception=dt.date(2026, 3, 1),
            notional_per_position=Decimal("5000"),
        )

        assert book.inception == dt.date(2026, 3, 1)
        assert book.notional_per_position == Decimal("5000.00")
        assert book.holdings[0].cost_basis == Decimal("5000.00")
        assert book.cash == Decimal("95000.00")

    def test_pre_inception_call_is_ignored(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, {})  # never fetched -- ignored before pricing
        note = _note(
            published=dt.datetime(2025, 12, 15, tzinfo=UTC),  # before DEFAULT_INCEPTION
            mentions=[_mention("SSS", "bullish")],
        )

        book = paperbook.build_persona_book(persona=_persona(), notes=[note], settings=settings)

        assert book.holdings == ()
        assert book.cash == book.starting_cash

    def test_undated_note_falls_back_to_ingested_at(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = [_bar(dt.date(2026, 2, 1), 20.0), _bar(dt.date(2026, 2, 10), 22.0)]
        _patch(monkeypatch, {"TTT": _series("TTT", bars)})
        note = _note(
            published=None,
            ingested_at=dt.datetime(2026, 2, 1, tzinfo=UTC),
            mentions=[_mention("TTT", "bullish")],
        )

        book = paperbook.build_persona_book(persona=_persona(), notes=[note], settings=settings)

        assert len(book.holdings) == 1
        assert book.holdings[0].symbol == "TTT"

    def test_weights_sum_to_one_and_sorted_by_weight_desc(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars_a = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 200.0)]  # doubles
        bars_b = [_bar(dt.date(2026, 1, 5), 100.0), _bar(dt.date(2026, 1, 10), 110.0)]  # +10%
        _patch(monkeypatch, {"UUU": _series("UUU", bars_a), "VVV": _series("VVV", bars_b)})
        notes = [
            _note(
                note_id="n_uuu", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("UUU", "bullish")],
            ),
            _note(
                note_id="n_vvv", published=dt.datetime(2026, 1, 5, tzinfo=UTC),
                mentions=[_mention("VVV", "bullish")],
            ),
        ]

        book = paperbook.build_persona_book(persona=_persona(), notes=notes, settings=settings)

        assert len(book.holdings) == 2
        total_weight = sum(h.weight for h in book.holdings)
        assert total_weight == pytest.approx(1.0)
        assert [h.symbol for h in book.holdings] == ["UUU", "VVV"]
        assert book.holdings[0].weight > book.holdings[1].weight
