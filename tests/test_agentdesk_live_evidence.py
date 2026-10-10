"""Tests for the two live evidence sections -- `live_quote` and `intraday` -- and for the grounding
scrubs they needed.

Two properties matter more than the rest and are tested first-class here:

* **Look-ahead safety.** A pack built as of a past date must not contain today's quote or today's
  intraday bars. That is the invariant `AsOfMarket` enforces everywhere else in this application, and
  a live feed is the single easiest way to break it.
* **The gate passes realistic prose, and still fails a fabrication.** This repo has a scar for
  unit-testing the grounding checker on rules in isolation: ISO dates and `RSI(14)` leaked tokens and
  the gate rejected agents for following their own prompts. So the tests below probe `check` with the
  sentences a model actually writes about a live quote -- times, timezone labels, ISO timestamps --
  and then prove that a price nobody measured still fails.

No network: `livefeed.latest_with_snapshot` and `store.ensure_series` are both replaced, and
`httpx.HTTPTransport.handle_request` is blocked as a backstop.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.agentdesk import evidence
from app.agentdesk.grounding import check, grounded_values, numeric_tokens
from app.agentdesk.models import EvidencePack
from app.config import Settings
from app.market import livefeed
from app.market.live import LiveQuote, LiveQuoteError, LiveSnapshot
from app.market.models import Bar, BarSeries, BarSource, Interval, MarketWarning

_TODAY = dt.datetime.now(dt.UTC).date()
_QUOTE_TS = dt.datetime.now(dt.UTC).replace(microsecond=0)


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def _blocked(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"test_agentdesk_live_evidence.py attempted a real HTTP request: {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)


def _live_quote(*, stale: bool = False) -> LiveQuote:
    return LiveQuote(
        symbol="AAPL",
        price=Decimal("231.45"),
        previous_close=Decimal("228.70"),
        change=Decimal("2.75"),
        change_pct=Decimal("1.2024"),
        ts=_QUOTE_TS,
        stale=stale,
        source="yahoo",
    )


def _snapshot(*, quotes: tuple[LiveQuote, ...], errors: tuple[LiveQuoteError, ...] = ()) -> LiveSnapshot:
    return LiveSnapshot(
        as_of=_QUOTE_TS,
        market_state="REGULAR",
        transport="poll",
        healthy=True,
        quotes=quotes,
        errors=errors,
    )


@pytest.fixture
def live_quote_available(monkeypatch: pytest.MonkeyPatch) -> LiveQuote:
    quote = _live_quote()
    monkeypatch.setattr(
        livefeed,
        "latest_with_snapshot",
        lambda symbol: (quote, _snapshot(quotes=(quote,))),
    )
    return quote


def _bars(session: dt.date, count: int = 30) -> list[Bar]:
    """`count` five-minute bars on `session`, starting at 13:30 UTC (a US regular open)."""
    start = dt.datetime.combine(session, dt.time(13, 30), tzinfo=dt.UTC)
    return [
        Bar(
            ts=start + dt.timedelta(minutes=5 * i),
            open=230.00 + i * 0.10,
            high=230.50 + i * 0.10,
            low=229.80 + i * 0.10,
            close=230.20 + i * 0.10,
            volume=100_000 + i,
        )
        for i in range(count)
    ]


@pytest.fixture
def intraday_bars(monkeypatch: pytest.MonkeyPatch) -> list[Bar]:
    bars = _bars(_TODAY)

    def _ensure_series(symbol: str, interval: Interval, **kwargs: object) -> BarSeries:
        assert interval is Interval.FIVE_MIN
        return BarSeries(symbol=symbol, interval=interval, source=BarSource.YAHOO, bars=bars)

    monkeypatch.setattr(evidence.store, "ensure_series", _ensure_series)
    return bars


# ---------------------------------------------------------------------------
# live_quote
# ---------------------------------------------------------------------------


class TestLiveQuoteSection:
    def test_it_carries_the_quote_as_grounded_items(
        self, settings: Settings, live_quote_available: LiveQuote
    ) -> None:
        section, warnings = evidence._live_quote_evidence("AAPL", None, settings=settings)

        assert warnings == ()
        values = {item.key: item.value for item in section.items}
        assert values["price"] == "231.45"
        assert values["previous_close"] == "228.70"
        assert values["change"] == "2.75"
        assert values["change_pct"] == "1.2024"
        assert values["market_state"] == "REGULAR"
        assert "quote_age_seconds" in values
        # The provenance a reader needs is how *this process* got the quote, not the upstream name.
        assert {item.source for item in section.items} == {"poll"}
        # The timestamp lives in the text (and on each item's as_of), not in a numeric item.
        assert _QUOTE_TS.isoformat() in section.text
        assert "current" in section.text

    def test_a_stale_quote_says_so_in_the_text(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        quote = _live_quote(stale=True)
        monkeypatch.setattr(
            livefeed, "latest_with_snapshot", lambda symbol: (quote, _snapshot(quotes=(quote,)))
        )

        section = evidence.live_quote_evidence("AAPL", None, settings=settings)
        assert "STALE" in section.text

    def test_a_past_as_of_produces_an_empty_section_and_a_warning(
        self, settings: Settings, live_quote_available: LiveQuote
    ) -> None:
        section, warnings = evidence._live_quote_evidence(
            "AAPL", _TODAY - dt.timedelta(days=1), settings=settings
        )

        assert section.items == ()
        assert section.text == ""
        assert len(warnings) == 1
        assert "past date" in warnings[0]

    def test_today_is_not_treated_as_historical(
        self, settings: Settings, live_quote_available: LiveQuote
    ) -> None:
        section, warnings = evidence._live_quote_evidence("AAPL", _TODAY, settings=settings)

        assert warnings == ()
        assert section.items

    def test_disabled_paperlive_produces_an_empty_section_and_a_warning(
        self, settings: Settings, live_quote_available: LiveQuote
    ) -> None:
        section, warnings = evidence._live_quote_evidence(
            "AAPL", None, settings=settings.model_copy(update={"paperlive_enabled": False})
        )

        assert section.items == ()
        assert "disabled" in warnings[0]

    def test_no_quote_reports_the_feeds_own_reason(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            livefeed,
            "latest_with_snapshot",
            lambda symbol: (
                None,
                _snapshot(quotes=(), errors=(LiveQuoteError(symbol="AAPL", message="not found"),)),
            ),
        )

        section, warnings = evidence._live_quote_evidence("AAPL", None, settings=settings)

        assert section.items == ()
        assert "not found" in warnings[0]

    def test_a_feed_failure_is_an_empty_section_not_an_exception(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(livefeed, "latest_with_snapshot", lambda symbol: (None, None))

        section, warnings = evidence._live_quote_evidence("AAPL", None, settings=settings)
        assert section.items == ()
        assert warnings


# ---------------------------------------------------------------------------
# The grounding gate against realistic live-quote prose
# ---------------------------------------------------------------------------


def _live_pack(settings: Settings) -> EvidencePack:
    section = evidence.live_quote_evidence("AAPL", None, settings=settings)
    return EvidencePack(symbol="AAPL", as_of=None, sections=(section,))


class TestLiveQuoteGrounding:
    #: The sentence the brief names, and the shape a market analyst actually writes about a live
    #: quote: a price, a clock time with a timezone label, an ISO date, a rounded percentage, a
    #: previous close, and a market-state word.
    SENTENCE = (
        "AAPL is trading at 231.45 as of 14:32 UTC on 2026-09-08, up 1.2% from yesterday's close "
        "of 228.70; the market is REGULAR."
    )

    def test_the_realistic_sentence_passes(
        self, settings: Settings, live_quote_available: LiveQuote
    ) -> None:
        verdict = check(self.SENTENCE, _live_pack(settings))
        assert verdict.ok, verdict.issues

    def test_an_iso_timestamp_as_of_passes(
        self, settings: Settings, live_quote_available: LiveQuote
    ) -> None:
        text = (
            f"The last price is 231.45 (as of {_QUOTE_TS.isoformat()}), against a previous close "
            "of 228.70."
        )
        verdict = check(text, _live_pack(settings))
        assert verdict.ok, verdict.issues

    def test_an_et_clock_time_passes(
        self, settings: Settings, live_quote_available: LiveQuote
    ) -> None:
        text = "As of 09:35 ET the quote is 231.45, up 1.20% on the session."
        verdict = check(text, _live_pack(settings))
        assert verdict.ok, verdict.issues

    def test_a_fabricated_price_still_fails(
        self, settings: Settings, live_quote_available: LiveQuote
    ) -> None:
        text = "AAPL is trading at 999.99 as of 14:32 UTC, having touched 1,250.75 earlier."
        verdict = check(text, _live_pack(settings))

        assert not verdict.ok
        assert verdict.issues[0].kind == "ungrounded_number"
        assert "999.99" in verdict.issues[0].detail
        assert "1250.75" in verdict.issues[0].detail

    def test_a_fabricated_number_hidden_next_to_a_time_still_fails(
        self, settings: Settings, live_quote_available: LiveQuote
    ) -> None:
        """The scrub must remove the time, not everything near it."""
        text = "At 14:32 the price printed 415.60."
        verdict = check(text, _live_pack(settings))
        assert not verdict.ok
        assert "415.6" in verdict.issues[0].detail

    def test_the_quotes_own_items_are_all_admissible(
        self, settings: Settings, live_quote_available: LiveQuote
    ) -> None:
        values = grounded_values(_live_pack(settings))
        assert "231.45" in values
        assert "228.7" in values
        assert "2.75" in values
        assert "1.2" in values  # a one-decimal restatement of 1.2024


class TestTimeScrubs:
    """`numeric_tokens` in isolation -- but only for the constructs the sentences above rely on."""

    @pytest.mark.parametrize(
        "text",
        [
            "as of 14:32 UTC",
            "as of 14:32",
            "at 09:35 ET",
            "at 09:35:07Z",
            "at 2:30 pm",
            "at 14:32:05+00:00",
            "as of 2026-09-08T14:32:05+00:00",
            "as of 2026-09-08T14:32Z",
            "as of 2026-09-08 14:32:05",
            "the window ran 13:30-20:00 UTC",
        ],
    )
    def test_a_clock_time_leaks_no_tokens(self, text: str) -> None:
        assert numeric_tokens(text) == ()

    def test_a_measurement_beside_a_time_is_still_extracted(self) -> None:
        assert numeric_tokens("at 14:32 the close was 231.45") == ("231.45",)

    def test_the_previously_covered_constructs_still_work(self) -> None:
        """Regression guard on the existing scrubs, which the new ones run alongside."""
        assert numeric_tokens("RSI(14) on 2026-08-28 over 200 days") == ()
        assert numeric_tokens("the close was $101.50, up 12.34%") == ("101.5", "12.34")


# ---------------------------------------------------------------------------
# intraday
# ---------------------------------------------------------------------------


class TestIntradaySection:
    def test_it_summarises_the_session(
        self, settings: Settings, intraday_bars: list[Bar]
    ) -> None:
        section, warnings = evidence._intraday_evidence("AAPL", None, settings=settings, bars=24)

        assert warnings == ()
        values = {item.key: item.value for item in section.items}
        window = intraday_bars[-24:]
        assert values["last_close"] == f"{window[-1].close:.2f}"
        assert values["session_high"] == f"{max(b.high for b in window):.2f}"
        assert values["session_low"] == f"{min(b.low for b in window):.2f}"
        assert values["bar_count"] == "24"
        assert values["session_volume"] == str(sum(b.volume or 0 for b in window))
        assert "five-minute bars" in section.text
        # Six table rows plus the one-line header.
        assert len(section.text.splitlines()) == 7

    def test_the_bars_argument_bounds_the_window(
        self, settings: Settings, intraday_bars: list[Bar]
    ) -> None:
        section = evidence.intraday_evidence("AAPL", None, settings=settings, bars=5)
        values = {item.key: item.value for item in section.items}
        assert values["bar_count"] == "5"

    def test_a_past_as_of_produces_an_empty_section_and_a_warning(
        self, settings: Settings, intraday_bars: list[Bar]
    ) -> None:
        section, warnings = evidence._intraday_evidence(
            "AAPL", _TODAY - dt.timedelta(days=1), settings=settings
        )

        assert section.items == ()
        assert section.text == ""
        assert "past date" in warnings[0]

    def test_no_bars_is_an_empty_section_and_a_warning(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            evidence.store,
            "ensure_series",
            lambda symbol, interval, **kwargs: BarSeries(
                symbol=symbol, interval=interval, source=BarSource.YAHOO, bars=[]
            ),
        )

        section, warnings = evidence._intraday_evidence("AAPL", None, settings=settings)
        assert section.items == ()
        assert "no 5-minute bars" in warnings[0]

    def test_a_stale_session_is_reported_rather_than_passed_off_as_today(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stale_session = _TODAY - dt.timedelta(days=3)
        monkeypatch.setattr(
            evidence.store,
            "ensure_series",
            lambda symbol, interval, **kwargs: BarSeries(
                symbol=symbol, interval=interval, source=BarSource.YAHOO, bars=_bars(stale_session)
            ),
        )

        section, warnings = evidence._intraday_evidence("AAPL", None, settings=settings)

        assert section.items, "stale bars are still useful; they just have to be labelled"
        assert any(stale_session.isoformat() in w for w in warnings)

    def test_store_warnings_are_folded_in(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            evidence.store,
            "ensure_series",
            lambda symbol, interval, **kwargs: BarSeries(
                symbol=symbol,
                interval=interval,
                source=BarSource.YAHOO,
                bars=_bars(_TODAY),
                warnings=[MarketWarning(kind="stale", message="provider unavailable")],
            ),
        )

        _section, warnings = evidence._intraday_evidence("AAPL", None, settings=settings)
        assert any("provider unavailable" in w for w in warnings)

    def test_a_provider_failure_is_an_empty_section_not_an_exception(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.market.providers.base import ProviderUnavailable

        def _boom(symbol: str, interval: Interval, **kwargs: object) -> BarSeries:
            raise ProviderUnavailable("yahoo is down", provider="yahoo")

        monkeypatch.setattr(evidence.store, "ensure_series", _boom)

        section, warnings = evidence._intraday_evidence("AAPL", None, settings=settings)
        assert section.items == ()
        assert "yahoo is down" in warnings[0]

    def test_a_missing_volume_omits_the_total_rather_than_undercounting(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bars = _bars(_TODAY, count=6)
        bars[2] = bars[2].model_copy(update={"volume": None})
        monkeypatch.setattr(
            evidence.store,
            "ensure_series",
            lambda symbol, interval, **kwargs: BarSeries(
                symbol=symbol, interval=interval, source=BarSource.YAHOO, bars=bars
            ),
        )

        section, warnings = evidence._intraday_evidence("AAPL", None, settings=settings)

        assert "session_volume" not in {item.key for item in section.items}
        assert any("no volume" in w for w in warnings)


# ---------------------------------------------------------------------------
# build_pack
# ---------------------------------------------------------------------------


class TestBuildPack:
    def test_the_two_new_keys_are_accepted(
        self, settings: Settings, live_quote_available: LiveQuote, intraday_bars: list[Bar]
    ) -> None:
        pack = evidence.build_pack(
            "AAPL", None, settings=settings, sections=["live_quote", "intraday"]
        )

        assert [section.title for section in pack.sections] == ["Live quote", "Intraday"]
        assert not pack.is_empty

    def test_an_unknown_key_still_raises(self, settings: Settings) -> None:
        with pytest.raises(ValueError, match="unknown evidence section"):
            evidence.build_pack("AAPL", None, settings=settings, sections=["live_quote", "nope"])

    def test_a_historical_pack_sees_neither_live_section(
        self, settings: Settings, live_quote_available: LiveQuote, intraday_bars: list[Bar]
    ) -> None:
        pack = evidence.build_pack(
            "AAPL",
            _TODAY - dt.timedelta(days=30),
            settings=settings,
            sections=["live_quote", "intraday"],
        )

        assert pack.is_empty, "a replay must not see the current market"
        assert len(pack.warnings) == 2
        assert grounded_values(pack) == frozenset()

    def test_the_new_keys_are_appended_so_existing_presets_are_untouched(self) -> None:
        assert evidence.SECTION_KEYS[:7] == (
            "price",
            "indicators",
            "news",
            "social",
            "fundamentals",
            "macro",
            "events",
        )
        assert evidence.SECTION_KEYS[7:] == ("live_quote", "intraday")
