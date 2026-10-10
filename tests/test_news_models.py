"""Tests for `app.market.news_models.NewsItem.url`'s scheme guard.

The provider-level "one bad url drops that item, not the feed" behaviour is covered where it
matters -- `tests/test_provider_yahoo_news.py`, `tests/test_provider_gdelt.py`,
`tests/test_provider_reddit.py`. This file tests the model-level guard directly: what it rejects,
what it accepts, and that it never fires on a legitimate empty/whitespace edge already excluded by
other fields.
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from app.market.news_models import NewsItem

_NOW = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)


def _make(url: str) -> NewsItem:
    return NewsItem(title="t", url=url, published=_NOW, source="test")


class TestNewsItemUrlScheme:
    @pytest.mark.parametrize(
        "bad_url",
        [
            "javascript:alert(1)",
            "JavaScript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "ftp://example.com/x",
            "no-scheme-at-all",
            "",
        ],
    )
    def test_a_non_http_scheme_is_rejected(self, bad_url: str) -> None:
        with pytest.raises(ValidationError):
            _make(bad_url)

    @pytest.mark.parametrize(
        "good_url",
        ["http://example.com/a", "https://example.com/a", "  https://example.com/a  "],
    )
    def test_an_http_or_https_url_is_accepted_and_stripped(self, good_url: str) -> None:
        item = _make(good_url)
        assert item.url == good_url.strip()
