"""Stooq daily-bar provider.

**This provider is currently expected to fail in production**, and it has failed in two different
shapes -- both handled here, because the block is evidently maintained and there is no reason to
expect today's shape to be the last one:

* *2026-08-14:* the CSV download (``https://stooq.com/q/d/l/``) answered with an HTML anti-bot
  challenge page -- a proof-of-work script posting back to ``/__verify`` -- carrying HTTP 200, not
  a 4xx or 5xx. See ``tests/fixtures/market/stooq_challenge.html`` for the exact captured body.
* *2026-08-24:* re-probed, the same URL returns a canned HTTP 404 "page you requested does not
  exist" for live symbols (``aapl``, ``spy``, ``qqq``) -- and so does ``https://stooq.com/``
  itself. A 404 on the site's own homepage is the tell that this is an address-level block rather
  than anything to do with the symbol requested, and it is the evidence behind the 404 branch in
  :meth:`StooqProvider.fetch_bars` refusing to raise ``SymbolNotFound``.

There is no header-only fix for either: both are served regardless of ``User-Agent`` or ``Accept``
and across stooq.com, stooq.pl and plain HTTP, and clearing the challenge requires executing the
embedded JavaScript, which is out of scope for a data provider.

It stays in the provider chain anyway, for one reason: the failure is *correctly typed*. A CSV
parser that saw an HTML document and returned an empty frame would report "no history" for a ticker
that has thirty years of it, and the registry -- which only sees a shape, not a reason -- would take
that as a successful, if disappointing, fetch and stop there rather than falling through to Yahoo.
Raising :class:`~app.market.providers.base.ProviderResponseError` instead makes the failure visible
and retryable-elsewhere, which is the one thing this provider is still able to guarantee.

Only daily bars exist here (``i=d``); Stooq has no intraday endpoint worth integrating, so any other
interval is :class:`~app.market.providers.base.UnsupportedInterval`. The CSV itself is unadjusted, so
``adj_close`` is always ``NaN`` -- never a copy of ``close``, per the same rule Yahoo's intraday bars
follow.
"""

from __future__ import annotations

import datetime as dt
import io
from typing import Final

import httpx
import pandas as pd

from app.market.models import BAR_COLUMNS, Interval
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
    UnsupportedInterval,
    provider_symbol,
)

__all__ = ["StooqProvider"]

_DOWNLOAD_URL: Final[str] = "https://stooq.com/q/d/l/"
_EXPECTED_HEADER: Final[str] = "date,open,high,low,close,volume"


class StooqProvider:
    """Daily OHLCV from Stooq's CSV download. See the module docstring before wiring this up."""

    name = "stooq"
    supported_intervals = frozenset({Interval.DAY})

    def __init__(self, client: httpx.Client | None = None, *, timeout: float = 15.0) -> None:
        self._client = client or httpx.Client(timeout=timeout)

    def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> pd.DataFrame:
        if interval not in self.supported_intervals:
            raise UnsupportedInterval(
                f"stooq serves daily bars only, not {interval.value}", provider=self.name
            )

        try:
            response = self._client.get(
                _DOWNLOAD_URL, params={"s": f"{provider_symbol(symbol).lower()}.us", "i": "d"}
            )
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(f"stooq timed out fetching {symbol}", provider=self.name) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"stooq transport error fetching {symbol}: {exc}", provider=self.name
            ) from exc

        if response.status_code == 404:
            # Deliberately *not* SymbolNotFound. That exception means "the upstream is healthy and
            # says this ticker does not exist", and the registry treats it as terminal: it re-raises
            # at once and the user is told their symbol is wrong. Stooq cannot support that claim.
            # It is currently serving an anti-bot challenge, and a 404 from it is indistinguishable
            # from being blocked -- QQQ, which plainly exists, 404s here today.
            #
            # Since Stooq is only ever reached after the primary has already failed, letting it
            # assert non-existence would let a degraded fallback overrule a healthy primary and turn
            # "Yahoo is down" into "no such ticker": the wrong diagnosis, pointing the user at their
            # own typing instead of at the outage.
            raise ProviderResponseError(
                f"stooq returned 404 for {symbol}; it is behind an anti-bot challenge and its 404s "
                "do not establish that a symbol is missing",
                provider=self.name,
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimited(
                f"stooq rate-limited the request for {symbol}",
                provider=self.name,
                retry_after=float(retry_after) if retry_after else None,
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"stooq returned {response.status_code} for {symbol}", provider=self.name
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"stooq returned unexpected status {response.status_code} for {symbol}",
                provider=self.name,
            )

        return self._parse_csv(response.text, symbol, start=start, end=end)

    def _parse_csv(
        self, text: str, symbol: str, *, start: dt.date | None, end: dt.date | None
    ) -> pd.DataFrame:
        header_line = text.split("\n", 1)[0].strip().lower()
        if header_line != _EXPECTED_HEADER:
            # Whatever this body is -- the anti-bot challenge today, a rate-limit page tomorrow --
            # it is not the CSV this parser understands. Checking the header rather than sniffing
            # content-type or looking for "<html" catches every shape of "not CSV" in one test,
            # including ones that haven't been seen yet.
            raise ProviderResponseError(
                f"stooq did not return CSV for {symbol}: expected header {_EXPECTED_HEADER!r}, "
                f"got {header_line!r}. This is the anti-bot challenge page as of this writing "
                "(HTTP 200, HTML body) -- see tests/fixtures/market/stooq_challenge.html.",
                provider=self.name,
            )

        try:
            raw = pd.read_csv(io.StringIO(text))
        except (pd.errors.ParserError, ValueError) as exc:
            raise ProviderResponseError(
                f"stooq CSV for {symbol} could not be parsed: {exc}", provider=self.name
            ) from exc

        required = {"Date", "Open", "High", "Low", "Close", "Volume"}
        missing = required - set(raw.columns)
        if missing:
            raise ProviderResponseError(
                f"stooq CSV for {symbol} is missing columns {sorted(missing)}", provider=self.name
            )

        raw = raw.dropna(subset=["Open", "High", "Low", "Close"])
        ts = pd.to_datetime(raw["Date"], utc=True)

        frame = pd.DataFrame(
            {
                "ts": ts,
                "open": raw["Open"].astype("float64"),
                "high": raw["High"].astype("float64"),
                "low": raw["Low"].astype("float64"),
                "close": raw["Close"].astype("float64"),
                "adj_close": pd.array([float("nan")] * len(raw), dtype="float64"),
                "volume": raw["Volume"].astype("Int64"),
            },
            columns=list(BAR_COLUMNS),
        )
        frame = frame.sort_values("ts", kind="stable").reset_index(drop=True)

        if start is not None:
            frame = frame[frame["ts"] >= pd.Timestamp(start, tz="UTC")]
        if end is not None:
            frame = frame[frame["ts"] <= pd.Timestamp(end, tz="UTC")]
        return frame.reset_index(drop=True)
