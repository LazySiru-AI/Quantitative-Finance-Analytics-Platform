"""``news_facts`` is the bridge from market observations to the grounding contract.

The properties under test are not "it returns some facts" -- that would pass a version that silently
defaulted a missing ratio to zero. What matters is the discipline `app.report.news_facts`'s module
docstring insists on: `None` over a fabricated default, a present-but-`None` fact rather than an
absent one when a whole section could not be measured, and a `source` string specific enough that a
reader could go find the window it names. `TestGroundingRoundTrip` is the test that proves the ids
this module emits are not just plausible-looking strings -- they are legal `{{fact:id}}` references
that `app.report.narrative.verify` actually accepts.
"""

from __future__ import annotations

import datetime as dt

from app.db.duck import Interval
from app.market.news_models import NewsItem, SocialSnapshot, SocialSummary, TickerNewsPanel
from app.report import narrative
from app.report.models import FactBundle, FactKind, NarrativeDraft
from app.report.news_facts import news_facts


def _news_item(*, hours_ago: float, source: str = "yahoo_news") -> NewsItem:
    published = dt.datetime(2026, 8, 24, 18, 0, tzinfo=dt.UTC) - dt.timedelta(hours=hours_ago)
    return NewsItem(
        title=f"Article {hours_ago}h ago",
        url=f"https://example.test/{hours_ago}",
        published=published,
        source=source,
    )


def _snapshot(
    *, bullish: int = 3, bearish: int = 1, neutral: int = 8, window_start: dt.datetime | None = None
) -> SocialSnapshot:
    return SocialSnapshot(
        symbol="AAPL",
        source="stocktwits",
        as_of=dt.datetime(2026, 8, 24, 18, 2, tzinfo=dt.UTC),
        window_start=window_start,
        bullish=bullish,
        bearish=bearish,
        neutral=neutral,
    )


def _panel(
    *,
    news: tuple[NewsItem, ...] = (),
    news_source: str | None = "yahoo_news",
    social: SocialSummary | None = None,
) -> TickerNewsPanel:
    return TickerNewsPanel(
        symbol="AAPL",
        generated_at=dt.datetime(2026, 8, 24, 18, 5, tzinfo=dt.UTC),
        news=news,
        news_source=news_source,
        social=social,
    )


class TestPopulatedPanel:
    """A panel with both a news feed and a social snapshot yields every id, fully measured."""

    def test_every_id_is_present_with_a_non_none_value(self) -> None:
        panel = _panel(
            news=(_news_item(hours_ago=3), _news_item(hours_ago=30)),
            social=SocialSummary.of(
                _snapshot(
                    bullish=3,
                    bearish=1,
                    neutral=8,
                    window_start=dt.datetime(2026, 8, 24, 16, 55, tzinfo=dt.UTC),
                )
            ),
        )

        facts = news_facts(panel)

        expected_ids = {
            "news.count",
            "news.newest_age_hours",
            "sentiment.messages",
            "sentiment.labelled",
            "sentiment.bullish",
            "sentiment.bearish",
            "sentiment.neutral",
            "sentiment.bull_ratio",
            "sentiment.labelled_share",
        }
        assert set(facts) == expected_ids
        for fact_id in expected_ids:
            assert facts[fact_id].value is not None, fact_id

    def test_news_count_and_newest_age_hours_are_correct(self) -> None:
        panel = _panel(news=(_news_item(hours_ago=3), _news_item(hours_ago=30)))

        facts = news_facts(panel)

        assert facts["news.count"].value == 2
        # `_panel`'s `generated_at` is 18:05, five minutes after `_news_item`'s 18:00 anchor, so the
        # newest article (3h before the anchor) is 3h5m -- 3 + 5/60 hours -- before `generated_at`.
        assert facts["news.newest_age_hours"].value == 3.0 + 5 / 60
        assert facts["news.count"].kind is FactKind.COUNT
        assert facts["news.newest_age_hours"].kind is FactKind.RATIO

    def test_sentiment_counts_and_ratios_match_the_snapshot(self) -> None:
        panel = _panel(social=SocialSummary.of(_snapshot(bullish=3, bearish=1, neutral=8)))

        facts = news_facts(panel)

        assert facts["sentiment.messages"].value == 12
        assert facts["sentiment.labelled"].value == 4
        assert facts["sentiment.bullish"].value == 3
        assert facts["sentiment.bearish"].value == 1
        assert facts["sentiment.neutral"].value == 8
        assert facts["sentiment.bull_ratio"].value == 3 / 4
        assert facts["sentiment.labelled_share"].value == 4 / 12


class TestMissingSocialProvider:
    """``social=None`` is a section that could not be measured, not a section that never existed."""

    def test_every_sentiment_id_is_present_with_value_none(self) -> None:
        panel = _panel(social=None)

        facts = news_facts(panel)

        sentiment_ids = {
            "sentiment.messages",
            "sentiment.labelled",
            "sentiment.bullish",
            "sentiment.bearish",
            "sentiment.neutral",
            "sentiment.bull_ratio",
            "sentiment.labelled_share",
        }
        assert sentiment_ids <= set(facts)
        for fact_id in sentiment_ids:
            assert facts[fact_id].value is None, fact_id

    def test_news_facts_are_unaffected_by_a_missing_social_provider(self) -> None:
        panel = _panel(news=(_news_item(hours_ago=1),), social=None)

        facts = news_facts(panel)

        assert facts["news.count"].value == 1
        assert facts["news.newest_age_hours"].value == 1.0 + 5 / 60


class TestZeroLabelledMessages:
    """The headline discipline: an unmeasurable ratio is ``None``, never a fabricated midpoint."""

    def test_bull_ratio_is_none_not_a_default(self) -> None:
        panel = _panel(social=SocialSummary.of(_snapshot(bullish=0, bearish=0, neutral=12)))

        facts = news_facts(panel)

        assert facts["sentiment.bull_ratio"].value is None
        assert facts["sentiment.bull_ratio"].value != 0.5
        assert facts["sentiment.bull_ratio"].value != 0.0
        assert facts["sentiment.labelled"].value == 0
        assert facts["sentiment.messages"].value == 12

    def test_labelled_share_is_none_when_the_window_is_entirely_empty(self) -> None:
        panel = _panel(social=SocialSummary.of(_snapshot(bullish=0, bearish=0, neutral=0)))

        facts = news_facts(panel)

        assert facts["sentiment.labelled_share"].value is None
        assert facts["sentiment.messages"].value == 0


class TestEmptyNewsList:
    """No articles is a real, reportable state -- zero, not an absence of the fact itself."""

    def test_count_is_zero_and_newest_age_is_none(self) -> None:
        panel = _panel(news=())

        facts = news_facts(panel)

        assert facts["news.count"].value == 0
        assert facts["news.newest_age_hours"].value is None


class TestFactSource:
    """``source`` must name the provider, the symbol, and the actual window -- not just a label."""

    def test_sentiment_source_names_provider_symbol_and_window(self) -> None:
        window_start = dt.datetime(2026, 8, 24, 16, 55, tzinfo=dt.UTC)
        panel = _panel(social=SocialSummary.of(_snapshot(window_start=window_start)))

        source = news_facts(panel)["sentiment.bull_ratio"].source

        assert "stocktwits" in source
        assert "AAPL" in source
        assert window_start.isoformat() in source
        assert "2026-08-24T18:02:00+00:00" in source  # snapshot.as_of

    def test_sentiment_source_says_no_provider_answered_when_social_is_none(self) -> None:
        panel = _panel(social=None)

        source = news_facts(panel)["sentiment.messages"].source

        assert "AAPL" in source
        assert "stocktwits" not in source

    def test_news_source_names_the_answering_provider_and_the_article_span(self) -> None:
        panel = _panel(
            news=(_news_item(hours_ago=3, source="yahoo_news"), _news_item(hours_ago=30)),
            news_source="yahoo_news",
        )

        source = news_facts(panel)["news.count"].source

        assert "yahoo_news" in source
        assert "AAPL" in source
        assert "2" in source  # article count


class TestGroundingRoundTrip:
    """The test that proves the module did its actual job: the ids it emits are legal citations.

    A fact id that is merely a plausible-looking string is worthless to the report -- it only earns
    its place if `app.report.narrative.verify` will actually resolve a `{{fact:...}}` reference built
    from it. This builds a real `FactBundle` from `news_facts`' output, writes a template draft citing
    every single id it produced, and asserts the draft verifies clean: no unknown-fact violations, no
    malformed references, no bare numerals smuggled in around them.
    """

    def test_every_emitted_fact_id_is_a_legal_reference(self) -> None:
        panel = _panel(
            news=(_news_item(hours_ago=3), _news_item(hours_ago=30)),
            social=SocialSummary.of(
                _snapshot(
                    bullish=3,
                    bearish=1,
                    neutral=8,
                    window_start=dt.datetime(2026, 8, 24, 16, 55, tzinfo=dt.UTC),
                )
            ),
        )
        facts = news_facts(panel)
        bundle = FactBundle(
            symbol="AAPL",
            interval=Interval.DAY,
            generated_at=dt.datetime.now(dt.UTC),
            facts=facts,
        )

        references = " ".join(f"{{{{fact:{fact_id}}}}}" for fact_id in facts)
        draft = NarrativeDraft(text=f"Sentiment snapshot: {references}", source="template")

        report = narrative.verify(draft, bundle)

        assert report.grounded is True, report.violations
        assert set(report.cited) == set(facts)

    def test_a_bundle_built_from_an_unmeasurable_panel_still_verifies(self) -> None:
        """``None``-valued facts remain citable -- `verify` checks the id resolves, not the value."""
        panel = _panel(news=(), social=None)
        facts = news_facts(panel)
        bundle = FactBundle(
            symbol="AAPL",
            interval=Interval.DAY,
            generated_at=dt.datetime.now(dt.UTC),
            facts=facts,
        )

        references = " ".join(f"{{{{fact:{fact_id}}}}}" for fact_id in facts)
        draft = NarrativeDraft(text=f"Sentiment snapshot: {references}", source="template")

        report = narrative.verify(draft, bundle)

        assert report.grounded is True, report.violations
