"""Ticker spelling at the provider boundary.

The ledger stores what the broker wrote. Robinhood writes ``BRK.B``; Yahoo and Stooq both spell the
same security ``BRK-B``. Sent through unchanged, the request comes back "no chart data", the position
lands in ``unpriced_symbols``, and it is excluded from market value with only a caveat line to say
so -- which is how a whole Berkshire position went missing from a portfolio
total while every other position priced normally.

That failure is silent by construction: the pricing path is *designed* to degrade a symbol it cannot
price rather than fail the request, so a misspelled ticker and a genuinely unpriceable holding look
identical from the outside. These tests exist because nothing else distinguishes them.
"""

from __future__ import annotations

import contextlib

import httpx
import pytest

from app.market.providers.base import provider_symbol


class TestProviderSymbol:
    @pytest.mark.parametrize(
        ("ledger", "provider"),
        [
            ("BRK.B", "BRK-B"),
            ("BRK.A", "BRK-A"),
            ("BF.B", "BF-B"),
            ("LEN.B", "LEN-B"),
            ("HEI.A", "HEI-A"),
        ],
    )
    def test_class_shares_take_a_hyphen(self, ledger: str, provider: str) -> None:
        assert provider_symbol(ledger) == provider

    @pytest.mark.parametrize("symbol", ["AAPL", "NVDA", "SOXL", "SGOV", "BRK-B"])
    def test_everything_else_is_left_alone(self, symbol: str) -> None:
        """Including a symbol already spelled the provider's way -- the mapping is idempotent, so a
        caller that normalises twice does not corrupt the ticker."""
        assert provider_symbol(symbol) == symbol
        assert provider_symbol(provider_symbol(symbol)) == provider_symbol(symbol)

    def test_case_is_normalised(self) -> None:
        assert provider_symbol("brk.b") == "BRK-B"

    @pytest.mark.parametrize(
        "symbol",
        [
            "DX-Y.NYB",  # ICE US Dollar Index -- `.NYB` is an exchange suffix, not a share class.
            "dx-y.nyb",  # Case-insensitively: still an exchange suffix, not a share class.
        ],
    )
    def test_exchange_suffix_on_a_hyphenated_base_is_left_alone(self, symbol: str) -> None:
        """``DX-Y.NYB`` is already Yahoo's own correct spelling. The blanket dot-to-hyphen rewrite
        this replaced would turn it into ``DX-Y-NYB``, which 404s -- this is the bug being fixed.

        The base already containing a hyphen (``DX-Y``) is the signal: no real US share-class ticker
        has one, so a hyphen already present means the dot is not a share-class marker."""
        assert provider_symbol(symbol) == "DX-Y.NYB"

    @pytest.mark.parametrize(
        "symbol",
        [
            "SYMBOL.TO",  # Toronto -- multi-letter suffix, not a share class either way.
            "SYMBOL.AX",  # ASX -- same.
        ],
    )
    def test_multiletter_exchange_suffix_is_left_alone(self, symbol: str) -> None:
        """A suffix longer than one letter can never be a share-class marker (BRK.A/B, BF.A/B,
        HEI.A, LEN.B are all single-letter), so these are left in their given -- already
        provider-correct -- dot form regardless of the base."""
        assert provider_symbol(symbol) == symbol

    def test_single_letter_exchange_suffix_on_a_plain_base_is_the_known_blind_spot(self) -> None:
        """``VOD.L`` (Vodafone, London) has a single-letter suffix and a plain, hyphen-free base --
        indistinguishable, by this rule, from a share class. It is misread as one and wrongly
        rewritten to ``VOD-L``.

        This is a known, documented limitation (see the `provider_symbol` docstring), not an
        oversight: nothing in this codebase's symbol universe currently requests a single-letter
        foreign exchange suffix, so the narrow rule that fixes the actual bug (`DX-Y.NYB`) is
        preferred over a broader one guessing at exchange codes never seen in practice."""
        assert provider_symbol("VOD.L") == "VOD-L"


class TestYahooRequestsTheProviderSpelling:
    """The mapping has to be applied where the URL is built, not merely available."""

    def test_chart_url_uses_the_hyphen_form(self) -> None:
        from app.market.providers.yahoo import YahooProvider

        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(
                200,
                json={"chart": {"result": [{"meta": {"symbol": "BRK-B"}}], "error": None}},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = YahooProvider(client=client)
        provider._get("BRK.B", {})

        assert seen, "no request was made"
        assert "BRK-B" in seen[0]
        assert "BRK.B" not in seen[0]


class TestStooqRequestsTheProviderSpelling:
    def test_download_param_uses_the_hyphen_form(self) -> None:
        from app.db.duck import Interval
        from app.market.providers.stooq import StooqProvider

        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, text="Date,Open,High,Low,Close,Volume\n")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = StooqProvider(client=client)
        # The header-only CSV may legitimately raise; the request URL is what is under test.
        with contextlib.suppress(Exception):
            provider.fetch_bars("BRK.B", Interval.DAY, start=None, end=None)

        assert seen, "no request was made"
        assert "brk-b.us" in seen[0]
