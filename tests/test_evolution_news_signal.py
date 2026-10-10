"""Tests for `app.evolution.news_signal`.

Entirely offline: `app.market.news.build_ticker_panel` is monkeypatched at the point
`news_signal` imported it (`ns.build_ticker_panel`), so nothing in this file makes an HTTP request.
Every `Settings` instance is rooted in `tmp_path`, so nothing writes into the real `data/` tree.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app.config import Settings
from app.evolution import news_signal as ns
from app.market.news_models import NewsItem, SocialSnapshot, SocialSummary, TickerNewsPanel
from app.tournament.purposes import Purpose

NOW = dt.datetime(2026, 8, 24, 13, 2, tzinfo=dt.UTC)


# ---------------------------------------------------------------------------
# Fixtures and small builders
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A `Settings` rooted entirely under `tmp_path` -- never the real `data/` tree."""
    return Settings(data_dir=tmp_path / "data")


def _news_items(n: int, *, source: str) -> tuple[NewsItem, ...]:
    return tuple(
        NewsItem(
            title=f"Headline {i}",
            url=f"https://example.com/{source}/{i}",
            published=NOW - dt.timedelta(hours=i),
            source=source,
        )
        for i in range(n)
    )


def _social(*, bullish: int, bearish: int, neutral: int, source: str = "stocktwits") -> SocialSummary:
    snapshot = SocialSnapshot(
        symbol="X",
        source=source,
        as_of=NOW,
        bullish=bullish,
        bearish=bearish,
        neutral=neutral,
    )
    return SocialSummary.of(snapshot)


def _panel(
    symbol: str,
    *,
    news_count: int = 0,
    news_source: str | None = "yahoo_news",
    social: SocialSummary | None = None,
) -> TickerNewsPanel:
    return TickerNewsPanel(
        symbol=symbol,
        generated_at=NOW,
        as_of=None,
        news=_news_items(news_count, source=news_source) if news_source else (),
        news_source=news_source,
        social=social,
    )


def _panel_lookup(monkeypatch: pytest.MonkeyPatch, panels: dict[str, TickerNewsPanel], *, calls: list[str]) -> None:
    def fake_build_ticker_panel(_settings: Settings, symbol: str, *, as_of=None, **_kw) -> TickerNewsPanel:
        calls.append(symbol)
        return panels[symbol]

    monkeypatch.setattr(ns, "build_ticker_panel", fake_build_ticker_panel)


# ---------------------------------------------------------------------------
# (a) deterministic ordering
# ---------------------------------------------------------------------------


class TestRankAttentionOrdering:
    def test_orders_by_news_then_social_then_symbol(self, settings, monkeypatch):
        panels = {
            # Highest news count wins outright.
            "CCC": _panel("CCC", news_count=10, social=None),
            # Same news count (5): social count breaks the tie, BBB (10) ahead of AAA/DDD (2).
            "BBB": _panel("BBB", news_count=5, social=_social(bullish=5, bearish=5, neutral=0)),
            "AAA": _panel("AAA", news_count=5, social=_social(bullish=1, bearish=1, neutral=0)),
            "DDD": _panel("DDD", news_count=5, social=_social(bullish=1, bearish=1, neutral=0)),
        }
        calls: list[str] = []
        _panel_lookup(monkeypatch, panels, calls=calls)

        ranked = ns.rank_attention(symbols=["AAA", "BBB", "CCC", "DDD"], settings=settings)

        assert [a.symbol for a in ranked] == ["CCC", "BBB", "AAA", "DDD"]

    def test_ordering_is_reproducible_across_calls(self, settings, monkeypatch):
        panels = {
            "AAPL": _panel("AAPL", news_count=3),
            "MSFT": _panel("MSFT", news_count=3),
        }
        _panel_lookup(monkeypatch, panels, calls=[])

        first = ns.rank_attention(symbols=["MSFT", "AAPL"], settings=settings)
        second = ns.rank_attention(symbols=["AAPL", "MSFT"], settings=settings)

        assert [a.symbol for a in first] == [a.symbol for a in second] == ["AAPL", "MSFT"]


# ---------------------------------------------------------------------------
# (b) a raising provider degrades to zero counts, never propagates
# ---------------------------------------------------------------------------


class TestNeverRaises:
    def test_provider_raising_yields_zero_counts(self, settings, monkeypatch):
        def fake_build_ticker_panel(_settings, _symbol, *, as_of=None, **_kw):
            raise RuntimeError("provider chain is offline")

        monkeypatch.setattr(ns, "build_ticker_panel", fake_build_ticker_panel)

        ranked = ns.rank_attention(symbols=["ZZZ"], settings=settings)

        assert len(ranked) == 1
        attention = ranked[0]
        assert attention.symbol == "ZZZ"
        assert attention.news_items == 0
        assert attention.social_messages is None
        assert attention.bull_ratio is None
        assert attention.sources == ()

    def test_one_symbol_raising_does_not_poison_the_others(self, settings, monkeypatch):
        panels = {"OK": _panel("OK", news_count=4)}

        def fake_build_ticker_panel(_settings, symbol, *, as_of=None, **_kw):
            if symbol == "BAD":
                raise RuntimeError("boom")
            return panels[symbol]

        monkeypatch.setattr(ns, "build_ticker_panel", fake_build_ticker_panel)

        ranked = {a.symbol: a for a in ns.rank_attention(symbols=["OK", "BAD"], settings=settings)}

        assert ranked["OK"].news_items == 4
        assert ranked["BAD"].news_items == 0


# ---------------------------------------------------------------------------
# (c) social_messages is None, not 0, when the social provider had nothing
# ---------------------------------------------------------------------------


class TestSocialMessagesNoneVsZero:
    def test_a_real_zero_answer_is_zero_not_none(self, settings, monkeypatch):
        zero_social = _social(bullish=0, bearish=0, neutral=0)
        panels = {"ZERO": _panel("ZERO", news_count=1, social=zero_social)}
        _panel_lookup(monkeypatch, panels, calls=[])

        ranked = ns.rank_attention(symbols=["ZERO"], settings=settings)

        assert ranked[0].social_messages == 0

    def test_no_social_provider_is_none_not_zero(self, settings, monkeypatch):
        panels = {"NONE": _panel("NONE", news_count=1, social=None)}
        _panel_lookup(monkeypatch, panels, calls=[])

        ranked = ns.rank_attention(symbols=["NONE"], settings=settings)

        assert ranked[0].social_messages is None


# ---------------------------------------------------------------------------
# (d) bull_ratio is copied, never derived here
# ---------------------------------------------------------------------------


class TestBullRatioIsCopied:
    def test_bull_ratio_matches_the_upstream_summary_exactly(self, settings, monkeypatch):
        labelled = _social(bullish=3, bearish=1, neutral=6)
        panels = {"L": _panel("L", news_count=1, social=labelled)}
        _panel_lookup(monkeypatch, panels, calls=[])

        ranked = ns.rank_attention(symbols=["L"], settings=settings)

        assert ranked[0].bull_ratio == labelled.bull_ratio
        assert ranked[0].bull_ratio == pytest.approx(0.75)

    def test_bull_ratio_is_none_when_nothing_was_labelled(self, settings, monkeypatch):
        unlabelled = _social(bullish=0, bearish=0, neutral=10)
        panels = {"U": _panel("U", news_count=1, social=unlabelled)}
        _panel_lookup(monkeypatch, panels, calls=[])

        ranked = ns.rank_attention(symbols=["U"], settings=settings)

        assert unlabelled.bull_ratio is None
        assert ranked[0].bull_ratio is None


# ---------------------------------------------------------------------------
# (e) disk cache: written, and a second call within the TTL does not re-probe
# ---------------------------------------------------------------------------


class TestCache:
    def test_cache_file_is_written(self, settings, monkeypatch):
        panels = {"AAA": _panel("AAA", news_count=3)}
        _panel_lookup(monkeypatch, panels, calls=[])

        ns.rank_attention(symbols=["AAA"], settings=settings)

        cache_path = ns._cache_path(settings, day=dt.datetime.now(dt.UTC).date())
        assert cache_path.is_file()

    def test_second_call_within_ttl_does_not_reprobe(self, settings, monkeypatch):
        panels = {"AAA": _panel("AAA", news_count=3)}
        calls: list[str] = []
        _panel_lookup(monkeypatch, panels, calls=calls)

        first = ns.rank_attention(symbols=["AAA"], settings=settings)
        assert calls == ["AAA"]

        second = ns.rank_attention(symbols=["AAA"], settings=settings)

        assert calls == ["AAA"]  # not called a second time
        assert [a.symbol for a in second] == [a.symbol for a in first]
        assert second[0].news_items == first[0].news_items

    def test_a_different_as_of_is_not_served_from_the_other_bounds_cache_entry(self, settings, monkeypatch):
        panels = {"AAA": _panel("AAA", news_count=3)}
        calls: list[str] = []
        _panel_lookup(monkeypatch, panels, calls=calls)

        ns.rank_attention(symbols=["AAA"], settings=settings, as_of=None)
        ns.rank_attention(
            symbols=["AAA"], settings=settings, as_of=dt.datetime(2019, 1, 1, tzinfo=dt.UTC)
        )

        assert calls == ["AAA", "AAA"]


# ---------------------------------------------------------------------------
# (f) trending_symbols
# ---------------------------------------------------------------------------


class TestTrendingSymbols:
    def test_respects_limit_and_orders_by_coverage(self, settings, monkeypatch):
        panels = {
            "A": _panel("A", news_count=1),
            "B": _panel("B", news_count=5),
            "C": _panel("C", news_count=3),
            "D": _panel("D", news_count=0, news_source=None),  # zero coverage, must be excluded
        }
        _panel_lookup(monkeypatch, panels, calls=[])

        result = ns.trending_symbols(
            purpose=Purpose.TRADING, settings=settings, limit=2, candidates=["A", "B", "C", "D"]
        )

        assert result == ("B", "C")
        assert len(result) <= 2

    def test_total_failure_returns_empty_tuple(self, settings, monkeypatch):
        def fake_build_ticker_panel(_settings, _symbol, *, as_of=None, **_kw):
            raise RuntimeError("every provider is down")

        monkeypatch.setattr(ns, "build_ticker_panel", fake_build_ticker_panel)

        result = ns.trending_symbols(purpose=Purpose.ROTH, settings=settings, candidates=["X", "Y", "Z"])

        assert result == ()

    def test_empty_candidates_returns_empty_tuple(self, settings):
        result = ns.trending_symbols(purpose=Purpose.SAVINGS, settings=settings, candidates=[])

        assert result == ()

    def test_zero_coverage_across_the_board_returns_empty_tuple(self, settings, monkeypatch):
        panels = {
            "A": _panel("A", news_count=0, news_source=None),
            "B": _panel("B", news_count=0, news_source=None),
        }
        _panel_lookup(monkeypatch, panels, calls=[])

        result = ns.trending_symbols(purpose=Purpose.TRADING, settings=settings, candidates=["A", "B"])

        assert result == ()


# ---------------------------------------------------------------------------
# (g) provenance: counts only, no derived number
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_contains_counts_and_no_derived_number(self):
        attention = ns.Attention(
            symbol="SMH",
            news_items=14,
            social_messages=212,
            bull_ratio=0.5833333333333334,
            sources=("yahoo_news", "stocktwits"),
            as_of=NOW,
        )

        line = ns.provenance(attention)

        assert line.startswith("SMH:")
        assert "14" in line
        assert "212" in line
        # bull_ratio must never appear -- it is a derived number, not a count.
        assert "0.58" not in line
        assert "58%" not in line
        assert "%" not in line
        assert str(attention.bull_ratio) not in line

    def test_none_social_messages_is_omitted_not_rendered_as_zero(self):
        attention = ns.Attention(
            symbol="QQQ",
            news_items=0,
            social_messages=None,
            bull_ratio=None,
            sources=(),
            as_of=NOW,
        )

        line = ns.provenance(attention)

        assert "social message" not in line
        assert "0 news item" in line
