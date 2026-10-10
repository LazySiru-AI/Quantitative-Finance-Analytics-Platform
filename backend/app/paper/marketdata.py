"""Read-only, as-of-clamped view of the application's own daily bar store.

The persona must never see a price it could not have seen. That is the single property this module
exists to guarantee, and it guarantees it by construction rather than by discipline: every read goes
through :meth:`AsOfMarket.history`, which takes the as-of date from the :class:`AsOfMarket` instance
rather than from the caller, so a session cannot widen its own window by passing a later ``end``.

Why this matters more here than in a backtest. `app.backtest.guards` already defends the backtest
engine against lookahead, but that engine consumes a frame it was handed. Here the *decision-maker
is a language model*, and a model shown next week's close will use it while sincerely reporting that
it did not. There is no post-hoc test that can distinguish a lucky call from a leaked one, so the
leak has to be impossible at the boundary.

The store this reads is the real one under ``data/store/bars``. Bars are market reference data --
public OHLCV, nothing personal -- so reading them is safe. Nothing in this module writes anywhere.

**Process-wide frame cache.** A tournament card walks hundreds of sessions, and every one of them
used to re-read every held symbol's parquet file from scratch -- ~0.043s per symbol-session, which
is nearly the entire cost of a backtest loop over a 9-symbol card and 252 sessions. The fix is
`_full_frame`: it reads a symbol's whole stored history once per process and keeps it in
`_FRAME_CACHE`, keyed on `(symbol, interval, bars_dir)`. Every subsequent read for that key -- from
any `AsOfMarket` instance, at any `as_of` -- is served from the cached frame instead of the parquet
file.

That last sentence is exactly where this cache could quietly reintroduce the lookahead this module
exists to prevent, so the invariant is worth stating precisely: **the cache stores the unbounded
frame; the as-of clamp is applied on every read, after the cache lookup, from the calling
instance's own `self.as_of`.** Nothing about `as_of` is baked into the cache key or the cached
value. An instance built with `as_of=2026-01-05` and one built with `as_of=2026-06-01` share the
same cached frame for a symbol, but each slices it independently at read time -- the January
instance can never see June's rows, because nothing about June's read ever touches the January
instance's slicing step. This is what makes it safe to warm the cache from a *later* `as_of` and
then construct an *earlier* one and still get a clean answer; see
`tests/test_marketdata_cache.py::test_no_lookahead_leak_across_instances`, which exists specifically
to catch a future refactor that keys the cache on `as_of` (or slices before caching) by mistake.

The slice handed back to a caller is always `.copy()`-ed before it leaves `_slice`. A cached
`DataFrame` is a single shared object; returning a view or an unindexed slice of it would let a
caller's in-place mutation (a strategy doing `frame["close"] = ...` for a rolling calculation, say)
corrupt every future read of that symbol for the rest of the process, silently and for every other
persona sharing it.

Staleness: a long-running process (the FastAPI server, in particular) can sync new bars for a
symbol while this module still holds a cached frame for it. Re-reading unconditionally on every
call would defeat the point of caching; never re-reading would mean a freshly synced symbol stays
invisible until restart. `_full_frame` splits the difference with a `Path.stat()` per read --
`st_mtime_ns` and `st_size` of the underlying parquet file -- and only re-reads through `read_frame`
when either has changed since the frame was cached. A `stat()` call is close enough to free next to
an actual parquet read that this buys freshness at no real cost. If the file does not exist at all,
this is treated as an ordinary cache miss and `read_frame` is called exactly as it is today --
`read_frame`'s own "no stored data" behaviour (an empty frame with the right columns) is untouched
and nothing is cached for a symbol that has never been synced.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, SupportsFloat, SupportsIndex

import pandas as pd

from app.config import Settings
from app.db.duck import bar_path
from app.market import store
from app.market.models import Interval

__all__ = ["AsOfMarket", "Session", "SessionCalendar", "UnpricedSymbol", "clear_frame_cache"]


@dataclass(frozen=True, slots=True)
class _CachedFrame:
    """One process-wide cache entry: a symbol's full stored history plus the file fingerprint it
    was read at, so a later read can tell whether the parquet file has since changed underneath it.
    """

    frame: pd.DataFrame
    mtime_ns: int
    size: int


#: `_FRAME_CACHE` is keyed on `(symbol, interval.value, str(settings.bars_dir))` -- the settings
#: path is part of the key, not an afterthought, because `tests/test_marketdata_cache.py` (and any
#: other test using a temp store) must never be served a frame that some earlier test, or the real
#: application, cached for a different `bars_dir`. Keying on the settings object's identity would
#: work by accident for tests that build a fresh `Settings` per case, but would fail the moment two
#: `Settings` instances legitimately pointed at the same directory (e.g. one built directly and one
#: via `get_settings()`) and were treated as different caches for no reason; the directory string is
#: the thing that actually determines which files are being read, so it is what the key is built
#: from.
_FRAME_CACHE: dict[tuple[str, str, str], _CachedFrame] = {}


def clear_frame_cache() -> None:
    """Drop every cached frame.

    Call this after syncing new bars into a store a long-running process might have already cached
    frames from (nothing in this module observes a sync as it happens -- see `_full_frame`'s
    `Path.stat()` check for the mechanism that otherwise catches it lazily), and at the top of any
    test that must not let a previous test's cached frame leak in.
    """
    _FRAME_CACHE.clear()


def _full_frame(
    symbol: str, *, settings: Settings, interval: Interval = Interval.DAY
) -> pd.DataFrame:
    """The symbol's whole stored history at `interval`, read once per process and sliced per as-of
    by every caller thereafter.

    Returns exactly what `store.read_frame(symbol, interval, settings=settings)` returns -- same
    columns, dtypes, index and row order -- whether served from cache or read fresh. Callers must
    never mutate the returned frame in place; see the module docstring's "process-wide frame cache"
    section for why, and `_slice` for where the defensive copy actually happens.

    `interval` defaults to `Interval.DAY`, which is what every pre-existing caller gets and what the
    live paper desk and tournament still run on. The cache key already carried an interval string
    before this parameter existed, so two intervals of the same symbol have never been able to
    collide here.
    """
    key = (symbol, interval.value, str(settings.bars_dir))
    path = bar_path(settings.bars_dir, symbol, interval)
    try:
        stat = path.stat()
        fingerprint: tuple[int, int] | None = (stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        fingerprint = None

    cached = _FRAME_CACHE.get(key)
    if (
        fingerprint is not None
        and cached is not None
        and (cached.mtime_ns, cached.size) == fingerprint
    ):
        return cached.frame

    frame = store.read_frame(symbol, interval, settings=settings)
    if fingerprint is not None:
        _FRAME_CACHE[key] = _CachedFrame(frame=frame, mtime_ns=fingerprint[0], size=fingerprint[1])
    else:
        # No file to fingerprint -- nothing safe to cache. Drop any stale entry rather than leave a
        # cached frame for a file that no longer exists (a test's tmp store torn down and rebuilt at
        # the same path, for instance) sitting around to be served by mistake once the file returns.
        _FRAME_CACHE.pop(key, None)
    return frame


def _utc_bound(moment: dt.date) -> pd.Timestamp:
    """A UTC `pd.Timestamp` for a slice boundary, accepting a date or a datetime.

    `pd.Timestamp(x, tz="UTC")` raises on an already-aware datetime, and intraday decision keys are
    aware where daily session dates are not -- so the two cases are separated here rather than at
    each of `_slice`'s call sites.
    """
    ts = pd.Timestamp(moment)
    return ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")


def _slice(frame: pd.DataFrame, *, start: dt.date, end: dt.date) -> pd.DataFrame:
    """`frame` restricted to `ts` in `[start, end]` inclusive, as a copy the caller owns outright.

    The boundaries are built the same way `store.read_frame`'s own weekly-resample branch builds
    them (`pd.Timestamp(d, tz="UTC")`), and for the same reason: every daily bar's `ts` has already
    been re-expressed in UTC by `store._normalize_utc`, and every DuckDB connection this codebase
    opens is pinned to `TimeZone='UTC'` (see `app.db.duck.connect`), so comparing against a UTC
    midnight boundary here reproduces exactly what the old code got by pushing `start`/`end` down
    into the SQL `WHERE` clause instead.

    Always returns a copy, never a view: `frame` may be the one shared object in `_FRAME_CACHE`, and
    a caller that mutated a bare slice of it would corrupt every future read of that symbol for the
    rest of the process.
    """
    start_ts = _utc_bound(start)
    end_ts = _utc_bound(end)
    sliced = frame[(frame["ts"] >= start_ts) & (frame["ts"] <= end_ts)]
    return sliced.reset_index(drop=True).copy()


class UnpricedSymbol(LookupError):
    """The store has no usable bar for this symbol at or before the as-of date."""

    def __init__(self, symbol: str, as_of: dt.date) -> None:
        super().__init__(f"no stored daily bar for {symbol!r} at or before {as_of.isoformat()}")
        self.symbol = symbol
        self.as_of = as_of


@dataclass(frozen=True, slots=True)
class Session:
    """One trading session, as the harness numbers them."""

    index: int
    """1-based session number within the run."""
    date: dt.date
    """The session being traded: orders decided at ``decided_on`` fill at this session's open."""
    decided_on: dt.date
    """The last session whose close the persona was allowed to see. Always strictly before
    :attr:`date`."""


class SessionCalendar:
    """The run's trading sessions, derived from the store rather than from a holiday table.

    A session exists if and only if the benchmark symbol has a stored bar for it. That is not a
    shortcut: the whole run prices off this store, so a date the store has no bar for is a date the
    harness could not fill an order on anyway, and inventing one from a calendar would produce a
    session whose fills are fabricated.
    """

    def __init__(
        self,
        *,
        start: dt.date,
        end: dt.date,
        settings: Settings,
        benchmark: str = "SPY",
        interval: Interval = Interval.DAY,
    ) -> None:
        self._settings = settings
        self.benchmark = benchmark
        self.interval = interval

        # One extra week of lead-in so `decided_on` for the first session is a real prior session
        # rather than a weekend.
        frame = store.read_frame(
            benchmark,
            interval,
            start=start - dt.timedelta(days=10),
            end=end,
            settings=settings,
        )
        if frame.empty:
            raise UnpricedSymbol(benchmark, end)

        # The unit a session is keyed by depends on the interval, and deliberately so.
        #
        # At `Interval.DAY` a session is a calendar date, exactly as it always was -- `ts.date()`
        # here reproduces the pre-existing behaviour bar for bar, which is what keeps the live desk
        # and every committed tournament round reproducible. At any finer interval a date is the
        # wrong key: 78 five-minute bars share one date, so collapsing them would keep only the last
        # and silently discard 77 decisions. Intraday runs are therefore keyed by the bar's full
        # timestamp.
        #
        # `dt.datetime` is a subclass of `dt.date`, so both flow through the same annotations -- but
        # they must never be *mixed* within one run, because `date < datetime` raises. A single run
        # only ever produces one kind, from this one place.
        if interval is Interval.DAY:
            keys = sorted({ts.date() for ts in frame["ts"]})
        else:
            keys = sorted({ts.to_pydatetime() for ts in frame["ts"]})
        dates = keys
        lo: dt.date = start
        hi: dt.date = end
        if interval is not Interval.DAY:
            # Widen the date bounds to cover the whole of the first and last day, so an intraday
            # run is not truncated at midnight of its own end date.
            lo = _utc_bound(start).to_pydatetime()
            hi = _utc_bound(end + dt.timedelta(days=1)).to_pydatetime()
        in_range = [d for d in dates if lo <= d <= hi]
        if not in_range:
            raise ValueError(
                f"no stored {benchmark} {interval.value} sessions between {start} and {end}; "
                "the run window contains no tradeable bar"
            )

        sessions: list[Session] = []
        for index, day in enumerate(in_range, start=1):
            prior = [d for d in dates if d < day]
            if not prior:
                raise ValueError(
                    f"session {day} has no prior stored session to decide on; "
                    "extend the store's history before running"
                )
            sessions.append(Session(index=index, date=day, decided_on=prior[-1]))

        self.sessions: Final[tuple[Session, ...]] = tuple(sessions)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.sessions)

    def __len__(self) -> int:
        return len(self.sessions)


class AsOfMarket:
    """Bars for one moment in the run. Cannot see past :attr:`as_of`.

    Construct one per session and throw it away. Sharing an instance across sessions would silently
    hand an earlier session a later window.
    """

    def __init__(
        self, *, as_of: dt.date, settings: Settings, interval: Interval = Interval.DAY
    ) -> None:
        self.as_of = as_of
        self._settings = settings
        self.interval = interval

    # -- history -----------------------------------------------------------

    def history(self, symbol: str, *, lookback_days: int | None = 400) -> pd.DataFrame:
        """Daily bars for ``symbol`` ending at :attr:`as_of` inclusive.

        ``end`` is not a parameter. See the module docstring.

        Reads through the process-wide frame cache (`_full_frame`): the symbol's whole stored
        history is fetched once per process and this method slices out `[as_of - lookback_days,
        as_of]` on every call, from `self.as_of` specifically -- never from anything wider. See the
        module docstring's "process-wide frame cache" section for why that ordering is the entire
        safety property of this class.

        **``lookback_days=None`` means every stored bar up to ``as_of``**, and it is what any caller
        computing a *recursive* indicator should pass. `sma` over a 400-day window is exact, because
        a rolling mean forgets everything older than its own period. `ema` and Wilder `rsi` do not
        forget: their value on any date carries a decaying contribution from wherever their series
        began, so a bounded window silently makes the answer a function of the bound. At the former
        400-day default -- about 275 trading bars -- an `ema(50)` differs from the same `ema(50)`
        computed over full history by roughly ``(1 - 2/51) ** 275``, about 1.8e-5, which is small
        right up until two averages are crossing and 1.8e-5 decides which is above the other. See
        `strategy-program/DEFECTS.md` D4 for the case that found this: one flipped signal, one lost
        trade, in a card whose entry is an EMA crossover.

        Passing `None` does not make the answer arbitrary-free by magic; it moves the arbitrary
        choice from a constant nobody picked to the start of the stored data, which is at least a
        fact about the world rather than a default argument. A bounded lookback remains right for
        callers that want a recent slice and nothing more -- `close` asks for 30 days, and the desk's
        last-price read asks for 10.
        """
        frame = _full_frame(symbol.upper(), settings=self._settings, interval=self.interval)
        if lookback_days is None and not frame.empty:
            first = frame["ts"].iloc[0]
            start: dt.date = first.date() if self.interval is Interval.DAY else first.to_pydatetime()
        else:
            # `lookback_days` is calendar days, and stays calendar days at every interval -- a
            # 400-day window is 400 days whether it holds 275 daily bars or ~31,000 five-minute
            # ones. Reinterpreting the number as bars would quietly shrink an intraday lookback to
            # a few sessions and change what every recursive indicator computes; see this method's
            # note on `ema`/`rsi` for why a silently-bounded window is the specific failure mode
            # worth avoiding here.
            start = self.as_of - dt.timedelta(days=lookback_days or 0)
        return _slice(frame, start=start, end=self.as_of)

    def close(self, symbol: str) -> Decimal:
        """The last close at or before :attr:`as_of`.

        Raises :class:`UnpricedSymbol` rather than returning ``None``: a caller that reaches this
        function has already decided it needs a price, and a ``None`` here has historically been
        turned into a zero somewhere downstream.
        """
        frame = self.history(symbol, lookback_days=30)
        if frame.empty:
            raise UnpricedSymbol(symbol, self.as_of)
        return _to_money(frame["close"].iloc[-1])

    def open_on(self, symbol: str, day: dt.date) -> Decimal:
        """The opening price of ``symbol`` on ``day``.

        This is the one function permitted to look at a date after :attr:`as_of`, because it is the
        fill and not the decision: the persona decides on data through :attr:`as_of` and the broker
        fills at the next session's open. Calling it is the broker's privilege, not the persona's --
        the persona is never handed an :class:`AsOfMarket` and a future date together.

        Also reads through `_full_frame`. `day` is not clamped against `self.as_of` here any more
        than it was before this cache existed -- that would break the fill itself -- so this method
        alone is unaffected by the "never wider than `as_of`" guarantee the rest of the class relies
        on; the clamp remains enforced by who is allowed to call it, not by what it returns.
        """
        frame = _full_frame(symbol.upper(), settings=self._settings, interval=self.interval)
        sliced = _slice(frame, start=day, end=day)
        if sliced.empty:
            raise UnpricedSymbol(symbol, day)
        return _to_money(sliced["open"].iloc[0])

    def has(self, symbol: str) -> bool:
        """Whether the symbol is priceable as of now, without raising."""
        try:
            self.close(symbol)
        except (UnpricedSymbol, FileNotFoundError):
            return False
        return True


def _to_money(value: SupportsFloat | SupportsIndex | str) -> Decimal:
    """Cross the float/Decimal boundary through ``str``.

    Bar prices are floats by design (``app.market.models.Bar``). ``Decimal(0.1)`` would import the
    float's binary error into a monetary figure; ``Decimal(str(0.1))`` does not. This is the same
    conversion `app.api.portfolio._price` makes, for the same reason.

    The parameter is annotated as what :func:`float` actually accepts rather than as ``object``.
    It read ``object`` until `app.tournament` became the first application module to import this
    harness, which put ``uat`` on mypy's path for the first time and surfaced the mismatch -- the
    annotation had always been wider than the body, and nothing had been checking.
    """
    return Decimal(str(round(float(value), 4)))
