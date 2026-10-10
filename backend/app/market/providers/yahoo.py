"""Yahoo Finance chart provider.

Everything -- bars, quote, profile -- comes off one endpoint: ``/v8/finance/chart/{symbol}``. A
separate ``quoteSummary``/``quote`` endpoint exists and carries richer fields, but it requires a
crumb-and-cookie handshake that Yahoo changes without notice; several public client libraries broke
against it in 2024 and stayed broken for months. The chart endpoint's ``meta`` block repeats the
same last-price fields under a stable, unauthenticated contract, so :meth:`fetch_quote` and
:meth:`fetch_profile` both read it rather than chasing the fragile endpoint for a handful of extra
fields.

Three behaviours here are load-bearing rather than incidental, and each has a fixture in
``tests/fixtures/market/`` built to exercise it:

* **Daily timestamps are re-stamped to the exchange-local session date at midnight UTC.** Yahoo
  hands back a US daily bar at 13:30 UTC (9:30 ET, the open) -- see :func:`app.market.models.
  session_date` for why taking ``.date()`` on that instant is wrong for anyone not reading in UTC.
* **``adj_close`` is genuinely absent, not copied from ``close``, on every intraday interval.** Yahoo
  simply does not return an ``adjclose`` indicator block intraday; filling the column with ``close``
  would make a total-return study silently indistinguishable from a price-return one.
* **The final bar is dropped when its session has not closed.** See :func:`_last_bar_unsettled`.
  Yahoo's chart response typically carries a trailing entry stamped at (or past) the current
  instant that represents the still-forming candle, not a completed one; persisting it would store a
  value that keeps changing after it has supposedly been recorded.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any, Final

import httpx
import pandas as pd

from app.config import get_settings
from app.market.models import (
    BAR_COLUMNS,
    INTERVAL_MAX_LOOKBACK,
    BarSource,
    Interval,
    Profile,
    Quote,
    session_date,
)
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
    SymbolNotFound,
    UnsupportedInterval,
    provider_symbol,
)

__all__ = ["YahooProvider"]

#: Yahoo's own interval tokens. ``1w`` is deliberately absent -- weekly bars are resampled locally
#: from stored daily bars (see app.db.duck's module docstring) and must never be requested here.
_YAHOO_INTERVAL: Final[dict[Interval, str]] = {
    Interval.FIVE_MIN: "5m",
    Interval.FIFTEEN_MIN: "15m",
    Interval.THIRTY_MIN: "30m",
    Interval.HOUR: "1h",
    Interval.FOUR_HOUR: "4h",
    Interval.DAY: "1d",
}

#: Earliest epoch to request when the caller gives no start date. Explicit ``period1``/``period2``
#: rather than ``range=max``, and that is not a stylistic preference.
#:
#: ``range=max`` with ``interval=1d`` **silently returns monthly bars.** Yahoo reports the downgrade
#: only in ``meta.dataGranularity``; the response is otherwise structurally identical, so 330 monthly
#: bars land in the ``interval=1d`` partition and every indicator computed from them is a monthly
#: indicator wearing a daily label -- an SMA(50) that is really a 50-*month* average, plausible on a
#: chart and wrong everywhere. ``period1=0`` returns the same span at true daily granularity (6,897
#: bars for QQQ against 330), so nothing is lost by never asking for ``max``.
_EPOCH_START: Final[int] = 0

#: Wall-clock length of one intraday bar, used only to decide whether the *last* bar's interval has
#: fully elapsed. Not used for daily/weekly, which settle on session close instead.
#:
#: The ``4h`` entry is nominal, not exact. A US regular session is 6.5h, so Yahoo actually emits one
#: true 4h bar (13:30 UTC / 09:30 ET) followed by a 2.5h remainder bar (17:30 UTC / 13:30 ET) to close
#: out the session -- verified by a live probe, not derived from documentation. Using 4h here for the
#: remainder bar means `_last_bar_unsettled` treats it as elapsed only after a full 4h has passed
#: from its open, i.e. up to 1.5h later than the bar actually settles; that is conservative (an extra
#: delay before the bar is trusted), not wrong in the unsafe direction, so it is left as-is rather
#: than special-cased.
_BAR_DURATION: Final[dict[Interval, dt.timedelta]] = {
    Interval.FIVE_MIN: dt.timedelta(minutes=5),
    Interval.FIFTEEN_MIN: dt.timedelta(minutes=15),
    Interval.THIRTY_MIN: dt.timedelta(minutes=30),
    Interval.HOUR: dt.timedelta(hours=1),
    Interval.FOUR_HOUR: dt.timedelta(hours=4),
}

def _user_agent() -> str:
    """Honest, not a spoofed browser string. A Chrome-shaped UA looks like the safer choice for an
    undocumented endpoint -- it is not. `app/market/providers/fred.py` documents the same finding
    against a different upstream: FRED tarpits a browser-shaped User-Agent (the request hangs until
    timeout and never returns) while an honest one gets the same payload in under a second, verified
    3/3 vs 9/9 interleaved against the live endpoint. Yahoo's chart endpoint tolerates the spoofed
    string today, but "tolerates it today" is exactly the state FRED was in before it did not, and
    spoofing is what gets a client blocked in the first place. Do not "fix" this back to a Chrome UA.

    A function, not a module-level `Final` string, and read at request time rather than cached on
    the instance: this used to be a literal carrying a real contact address, and `Settings.
    contact_email` (see `app.config`) is the replacement -- calling `get_settings()` here on every
    request rather than once at import time means a value set in `.env` after this module was first
    imported (as every test's `settings` fixture does, via `get_settings.cache_clear()`) is always
    the one that goes out on the wire.
    """
    return get_settings().contact_email

_CHART_URL: Final[str] = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

#: One day, in seconds. The margin that keeps a request strictly inside an exclusive window.
_ONE_DAY: Final[int] = 86_400


def _market_state(meta: dict[str, Any]) -> str | None:
    """``REGULAR`` / ``PRE`` / ``POST`` / ``CLOSED`` from the chart response.

    The chart endpoint carries no ``marketState`` field -- that one lives on the quote endpoint,
    which needs a crumb-and-cookie handshake this provider deliberately avoids. It does carry
    ``currentTradingPeriod`` and ``regularMarketTime``, which is the same information in unassembled
    form, so the label is derived rather than left permanently null in a UI that has a slot for it.

    Returns ``None`` rather than guessing when the periods are absent: an unlabelled badge is honest,
    a wrong one is not.
    """
    periods = meta.get("currentTradingPeriod")
    now = meta.get("regularMarketTime")
    if not isinstance(periods, dict) or now is None:
        return None
    for name, label in (("pre", "PRE"), ("regular", "REGULAR"), ("post", "POST")):
        window = periods.get(name)
        if isinstance(window, dict) and window.get("start") <= now < window.get("end"):
            return label
    return "CLOSED"


def _window_floor(interval: Interval, period2: int) -> int:
    """The earliest ``period1`` Yahoo will accept for a window ending at ``period2``.

    The retention limit applies to the **span** between the two endpoints, and the bound is
    exclusive: a 1h request spanning exactly 730 days is refused with HTTP 422, 729 days is served.
    Because ``period2`` is the day *after* the end date, a start clamped to "today minus the limit"
    produces a span of exactly the limit -- the one value guaranteed to fail.

    That is how both intraday timeframes came to be entirely broken while daily worked: daily has no
    limit, so it never went near this boundary, and every test that exercised the path used daily
    bars. Half the phase's headline deliverable -- four timeframes -- was dead, and green tests
    said otherwise.
    """
    limit = INTERVAL_MAX_LOOKBACK[interval]
    if limit is None:
        return _EPOCH_START
    return period2 - int(limit.total_seconds()) + _ONE_DAY


def _epoch_utc(date: dt.date) -> int:
    return int(dt.datetime.combine(date, dt.time.min, tzinfo=dt.UTC).timestamp())


def _first_trade_date(first_trade: object) -> dt.date | None:
    """The instrument's first-trade date, or `None` when Yahoo's value cannot be turned into one.

    `datetime.fromtimestamp` raises rather than returning on an out-of-range epoch, and on Windows
    that is an ``OSError: [Errno 22]`` (not the ``OverflowError``/``ValueError`` POSIX raises) for a
    negative or absurdly large seconds value. Yahoo does emit such values -- a pre-1970 listing, or a
    millisecond timestamp mistaken for seconds -- and an unguarded call there turned a perfectly real
    ticker (KO, CAT, JNJ, BA were all observed) into a 500 from `fetch_profile`, which the persona
    ticker validator then read as "unconfirmable" and dropped. A first-trade date is metadata; a bad
    one is worth a `None`, never worth failing the whole profile. Every other field still comes back.
    """
    if not isinstance(first_trade, (int, float)):
        return None
    try:
        return dt.datetime.fromtimestamp(first_trade, tz=dt.UTC).date()
    except (OSError, OverflowError, ValueError):
        return None


def _last_bar_unsettled(
    last_ts: dt.datetime,
    interval: Interval,
    *,
    regular_market_time: dt.datetime,
    regular_end: dt.datetime,
    exchange_tz: str,
) -> bool:
    """Whether the most recent bar belongs to a session that has not finished.

    Split out as a standalone function -- deliberately not a method -- because this is the single
    most consequential decision in the module: get it wrong in one direction and a value that will
    still change gets written to the store as if it were final; get it wrong in the other and every
    fetch during market hours silently loses its newest bar.

    Daily settles on the *session*: the bar is unsettled only if it belongs to the session
    ``currentTradingPeriod`` is currently describing, and that session has not yet reached its close.
    Intraday settles on the *clock*: a bar is unsettled if its own interval, measured from its open,
    has not yet fully elapsed as of ``regular_market_time``. Yahoo's intraday feed often appends a
    trailing bar stamped at exactly the current instant (the still-forming candle); that bar's
    "interval" by construction has not elapsed, so this rule drops it.

    **The daily test is anchored on ``regular_end``'s session, not ``regular_market_time``'s, and
    that distinction is the whole rule.** The two meta fields describe different sessions the moment
    a session ends: after Tuesday's close, ``regularMarketTime`` still reads Tuesday 16:00 ET (the
    last trade that happened) while ``currentTradingPeriod.regular`` has already rolled forward to
    Wednesday 09:30-16:00. An earlier version of this function compared the bar's date against
    ``regular_market_time``'s session and then asked ``regular_market_time < regular_end`` -- which,
    overnight, is Tuesday-16:00 against *Wednesday*-16:00 and therefore always true. Tuesday's fully
    settled bar was dropped as "still forming" by every fetch made between Tuesday's close and
    Wednesday's open, and all weekend for a Friday bar. The store could consequently never hold the
    most recent completed session unless a fetch happened to land inside the following session, and
    the paper desk's mark sat a day behind for exactly that reason (a fetch of forty symbols on a
    Wednesday morning reported forty successes and moved the mark not at all).

    Reading the bar's own session against ``regular_end``'s makes both halves refer to one session:
    a bar dated earlier than the current trading period is finished by definition, whatever the
    clock says, and a bar dated *within* it is unsettled exactly until ``regular_market_time``
    reaches the close.

    ``last_ts`` for daily/weekly must already be the midnight-UTC-normalised session date produced
    by :func:`~app.market.models.session_date` -- it is taken via ``.date()`` here, not re-converted
    through ``session_date`` a second time. Re-running the exchange-timezone conversion on a value
    that is midnight *UTC* rather than a true instant shifts it backward a calendar day for any
    exchange west of UTC (00:00 UTC is still the previous evening in America/New_York), which
    would make an already-settled bar look like it belongs to the day before the current session
    and get spuriously dropped. ``regular_end`` *is* a true instant, so it does go through
    ``session_date``.
    """
    if interval in (Interval.DAY, Interval.WEEK):
        in_current_session = last_ts.date() == session_date(regular_end, exchange_tz)
        return in_current_session and regular_market_time < regular_end
    duration = _BAR_DURATION[interval]
    return regular_market_time < last_ts + duration


class YahooProvider:
    """Bars, quotes and profiles from Yahoo's undocumented-but-stable chart endpoint."""

    name = "yahoo"
    supported_intervals = frozenset(
        {
            Interval.FIVE_MIN,
            Interval.FIFTEEN_MIN,
            Interval.THIRTY_MIN,
            Interval.HOUR,
            Interval.FOUR_HOUR,
            Interval.DAY,
        }
    )

    def __init__(self, client: httpx.Client | None = None, *, timeout: float = 15.0) -> None:
        self._client = client or httpx.Client(timeout=timeout)

    # -- HTTP + error mapping -------------------------------------------------

    def _get(self, symbol: str, params: dict[str, str]) -> dict[str, Any]:
        """Fetch one chart response and return ``chart.result[0]``, mapping transport failures.

        Does not validate that ``timestamp``/``indicators.quote`` are present -- callers that need
        bars use :meth:`_bars_result`, which adds that check; callers that only want ``meta`` (quote,
        profile) do not require a populated series at all.
        """
        requested = provider_symbol(symbol)
        url = _CHART_URL.format(symbol=requested)
        try:
            response = self._client.get(url, params=params, headers={"User-Agent": _user_agent()})
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(f"yahoo timed out fetching {symbol}", provider=self.name) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"yahoo transport error fetching {symbol}: {exc}", provider=self.name
            ) from exc

        if response.status_code == 404:
            # Name the symbol that was actually sent over the wire, not the ledger's pre-transform
            # spelling -- when `provider_symbol` rewrites, those two differ, and a message quoting
            # the wrong one sends whoever reads the warning looking at a symbol that never failed.
            if requested != symbol:
                raise SymbolNotFound(
                    f"yahoo has no chart data for {requested!r} (requested for ledger symbol "
                    f"{symbol!r})",
                    provider=self.name,
                )
            raise SymbolNotFound(f"yahoo has no chart data for {requested!r}", provider=self.name)
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimited(
                f"yahoo rate-limited the request for {symbol}",
                provider=self.name,
                retry_after=float(retry_after) if retry_after else None,
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"yahoo returned {response.status_code} for {symbol}", provider=self.name
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"yahoo returned unexpected status {response.status_code} for {symbol}",
                provider=self.name,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                f"yahoo response for {symbol} was not valid JSON", provider=self.name
            ) from exc

        chart = payload.get("chart", {})
        error = chart.get("error")
        if error is not None:
            # A 200 carrying `chart.error.code == "Not Found"` is how Yahoo answers a delisted or
            # mistyped symbol -- see tests/fixtures/market/yahoo_not_found.json.
            if error.get("code") == "Not Found":
                raise SymbolNotFound(
                    f"yahoo does not recognise the symbol {symbol!r}", provider=self.name
                )
            raise ProviderResponseError(
                f"yahoo returned an error for {symbol}: {error}", provider=self.name
            )

        results = chart.get("result")
        if not results:
            raise ProviderResponseError(
                f"yahoo chart response for {symbol} had no result", provider=self.name
            )
        result: dict[str, Any] = results[0]
        return result

    def _bars_result(self, symbol: str, params: dict[str, str]) -> dict[str, Any]:
        result = self._get(symbol, params)
        if "timestamp" not in result or not result.get("indicators", {}).get("quote"):
            raise ProviderResponseError(
                f"yahoo chart response for {symbol} is missing timestamp/quote data",
                provider=self.name,
            )
        return result

    def _meta(self, symbol: str) -> dict[str, Any]:
        # A minimal request -- five days of daily bars -- solely to read `meta`. Small enough that a
        # holiday-adjacent empty series is still fine, since meta does not depend on the series
        # actually containing rows.
        result = self._get(
            symbol,
            {"range": "5d", "interval": "1d", "includePrePost": "false", "events": "div,split"},
        )
        meta = result.get("meta")
        if not meta:
            raise ProviderResponseError(
                f"yahoo chart response for {symbol} had no meta block", provider=self.name
            )
        meta_dict: dict[str, Any] = meta
        return meta_dict

    # -- BarProvider ------------------------------------------------------

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
                f"yahoo does not fetch {interval.value} bars directly -- weekly bars are resampled "
                "locally from stored daily bars, never fetched",
                provider=self.name,
            )

        period2 = _epoch_utc((end or dt.date.today()) + dt.timedelta(days=1))
        period1 = _epoch_utc(start) if start is not None else _EPOCH_START
        params: dict[str, str] = {
            "interval": _YAHOO_INTERVAL[interval],
            "includePrePost": "false",
            "events": "div,split",
            "period1": str(max(period1, _window_floor(interval, period2))),
            "period2": str(period2),
        }

        result = self._bars_result(symbol, params)
        self._assert_granularity(result, interval, symbol)
        frame = self._to_frame(result, interval)
        # Stashed in `.attrs` rather than added as a column: it is one scalar for the whole frame, not
        # a per-row value, and `BAR_COLUMNS` is a closed contract the store and DuckDB schema both
        # depend on. `app.market.registry.ProviderRegistry.get_bars` reads this back out and threads
        # it into the bar store's intraday staleness gate, which otherwise has no way to know this
        # symbol's own trading hours -- see `app.market.store._plausible_trading_window`.
        frame.attrs["exchange_timezone"] = result["meta"]["exchangeTimezoneName"]
        return frame

    def _assert_granularity(self, result: dict[str, Any], interval: Interval, symbol: str) -> None:
        """Refuse a response whose bars are not the size that was asked for.

        Yahoo answers an over-wide request by quietly *coarsening* the data rather than refusing it,
        and reports the substitution only in ``meta.dataGranularity``. Without this check the
        coarser bars are indistinguishable from the requested ones -- same fields, same shape,
        ascending timestamps -- and they land in the store under the requested interval's partition,
        where nothing downstream can tell they are wrong. Checking one string here is the difference
        between a loud failure and a chart of monthly candles labelled daily.
        """
        served = str(result.get("meta", {}).get("dataGranularity", ""))
        wanted = _YAHOO_INTERVAL[interval]
        if served and served != wanted:
            raise ProviderResponseError(
                f"yahoo served {served} bars for {symbol} when {wanted} was requested; refusing to "
                "store coarser data under the requested interval",
                provider=self.name,
            )

    def _to_frame(self, result: dict[str, Any], interval: Interval) -> pd.DataFrame:
        meta = result["meta"]
        exchange_tz: str = meta["exchangeTimezoneName"]
        timestamps: list[int] = result["timestamp"]
        quote = result["indicators"]["quote"][0]
        adjclose_block = result["indicators"].get("adjclose")
        adjclose: list[float | None] = (
            adjclose_block[0]["adjclose"] if adjclose_block else [None] * len(timestamps)
        )
        opens, highs, lows, closes = quote["open"], quote["high"], quote["low"], quote["close"]
        volumes = quote.get("volume") or [None] * len(timestamps)

        ts_values: list[dt.datetime] = []
        open_values: list[float] = []
        high_values: list[float] = []
        low_values: list[float] = []
        close_values: list[float] = []
        adj_values: list[float] = []
        volume_values: list[int | None] = []

        for i, epoch in enumerate(timestamps):
            o, h, low_v, c = opens[i], highs[i], lows[i], closes[i]
            if o is None or h is None or low_v is None or c is None:
                # Yahoo emits a null OHLC row for a halted session. Dropping rather than
                # forward-filling: an invented bar is worse than a gap in the series.
                continue
            instant = dt.datetime.fromtimestamp(epoch, tz=dt.UTC)
            if interval in (Interval.DAY, Interval.WEEK):
                session = session_date(instant, exchange_tz)
                ts = dt.datetime.combine(session, dt.time.min, tzinfo=dt.UTC)
            else:
                ts = instant
            ts_values.append(ts)
            open_values.append(float(o))
            high_values.append(float(h))
            low_values.append(float(low_v))
            close_values.append(float(c))
            raw_adj = adjclose[i]
            adj_values.append(float(raw_adj) if raw_adj is not None else math.nan)
            volume_values.append(volumes[i])

        frame = pd.DataFrame(
            {
                "ts": pd.to_datetime(ts_values, utc=True),
                "open": pd.array(open_values, dtype="float64"),
                "high": pd.array(high_values, dtype="float64"),
                "low": pd.array(low_values, dtype="float64"),
                "close": pd.array(close_values, dtype="float64"),
                "adj_close": pd.array(adj_values, dtype="float64"),
                "volume": pd.array(volume_values, dtype="Int64"),
            },
            columns=list(BAR_COLUMNS),
        )
        frame = frame.sort_values("ts", kind="stable").reset_index(drop=True)
        return self._drop_unsettled_bar(frame, meta, interval, exchange_tz)

    def _drop_unsettled_bar(
        self, frame: pd.DataFrame, meta: dict[str, Any], interval: Interval, exchange_tz: str
    ) -> pd.DataFrame:
        if frame.empty:
            return frame
        try:
            regular_market_time = dt.datetime.fromtimestamp(
                meta["regularMarketTime"], tz=dt.UTC
            )
            regular_end = dt.datetime.fromtimestamp(
                meta["currentTradingPeriod"]["regular"]["end"], tz=dt.UTC
            )
        except (KeyError, TypeError) as exc:
            raise ProviderResponseError(
                "yahoo chart meta is missing regularMarketTime or "
                "currentTradingPeriod.regular.end -- cannot verify the last bar has settled, so "
                "it cannot safely be kept",
                provider=self.name,
            ) from exc

        last_ts = frame["ts"].iloc[-1].to_pydatetime()
        if _last_bar_unsettled(
            last_ts,
            interval,
            regular_market_time=regular_market_time,
            regular_end=regular_end,
            exchange_tz=exchange_tz,
        ):
            frame = frame.iloc[:-1].reset_index(drop=True)
        return frame

    # -- ProfileProvider ----------------------------------------------------

    def fetch_quote(self, symbol: str) -> Quote:
        meta = self._meta(symbol)
        price = meta.get("regularMarketPrice")
        if price is None:
            raise ProviderResponseError(
                f"yahoo meta for {symbol} has no regularMarketPrice", provider=self.name
            )
        regular_market_time = meta.get("regularMarketTime")
        ts = (
            dt.datetime.fromtimestamp(regular_market_time, tz=dt.UTC)
            if regular_market_time is not None
            else dt.datetime.now(dt.UTC)
        )
        previous_close = meta.get("chartPreviousClose")

        # Only compute the derived pair when both inputs exist, and only divide when the divisor is
        # non-zero -- guessing 0% on an absent previous close would be a fabricated number wearing
        # the shape of a real one.
        change: float | None = None
        change_pct: float | None = None
        if previous_close is not None:
            change = price - previous_close
            if previous_close != 0:
                change_pct = (change / previous_close) * 100

        return Quote(
            symbol=symbol,
            price=float(price),
            ts=ts,
            currency=meta.get("currency", "USD"),
            previous_close=previous_close,
            change=change,
            change_pct=change_pct,
            day_high=meta.get("regularMarketDayHigh"),
            day_low=meta.get("regularMarketDayLow"),
            fifty_two_week_high=meta.get("fiftyTwoWeekHigh"),
            fifty_two_week_low=meta.get("fiftyTwoWeekLow"),
            volume=meta.get("regularMarketVolume"),
            market_state=_market_state(meta),
            source=BarSource.YAHOO,
        )

    def fetch_profile(self, symbol: str) -> Profile:
        meta = self._meta(symbol)
        return Profile(
            symbol=symbol,
            name=meta.get("longName") or meta.get("shortName"),
            exchange=meta.get("fullExchangeName"),
            exchange_timezone=meta.get("exchangeTimezoneName", "America/New_York"),
            # `.get(..., "USD")` is not enough: Yahoo returns the key *present but null* for indices
            # and futures (^GSPC, GC=F), and a default only fills a *missing* key, so a null would
            # reach `Profile(currency=None)` and fail validation -- turning a real symbol into an
            # error. `or "USD"` coalesces the null too. US-denominated is the right fallback here.
            currency=meta.get("currency") or "USD",
            instrument_type=meta.get("instrumentType"),
            first_trade_date=_first_trade_date(meta.get("firstTradeDate")),
            source=BarSource.YAHOO,
        )
