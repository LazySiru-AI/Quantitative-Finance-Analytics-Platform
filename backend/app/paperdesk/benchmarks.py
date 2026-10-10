"""Price a blended benchmark: a fixed-weight basket of symbols (e.g. 60% SPY / 40% AGG) as one
total return over a date window.

**Why this exists.** Two places in this codebase already price a benchmark --
:func:`app.tournament.runner._benchmark_return` and :func:`app.paperdesk.desk._buy_and_hold` -- and
both are single-symbol, both hardcoded to ``SPY``. That is the wrong yardstick for a long-horizon
savings book: SPY alone is far more aggressive than a diversified, partly-bonds portfolio, so scoring
savings against it manufactures a permanent "underperformance" that has nothing to do with the
strategy and everything to do with the benchmark being a different, riskier thing (see
``strategy-program/THREE-PURPOSES-PLAN.md`` section 7, "Benchmarks per purpose"). Nothing in this
codebase composes more than one symbol into one return today, so a blended benchmark is new code, not
a parameter on the existing one. This module is deliberately standalone -- it does not wire into
``desk.py`` or ``runner.py``; that is a separate change once this capability is proven on its own.

**Decision 1 -- weights must sum to exactly 1, checked with exact ``Decimal`` equality, not a
tolerance.** A basket whose stated weights sum to 0.97 or 1.03 is not "close enough" to a 60/40 --
it is a different, undisclosed allocation, and silently renormalising it would hide that from
whoever wrote the weights. Exact equality is safe to require here specifically *because* weights are
``Decimal`` literals (``Decimal("0.60")``, not ``0.6`` as a ``float``): unlike ``float``, `Decimal`
arithmetic on base-10 literals is exact, so ``Decimal("0.60") + Decimal("0.40") == Decimal("1")`` has
no representation error to tolerate. A float-epsilon comparison would be solving a problem `Decimal`
inputs do not have; see the module docstring on money being ``Decimal`` throughout this codebase.
The failure names the actual sum (see :class:`WeightError`) so the caller sees exactly what they
typed, not just "invalid".

**Decision 2 -- the blend rebalances daily (a "constant-mix" benchmark), not buy-once-and-drift.**
A 60/40 basket bought once and left alone is not 60/40 ten years later -- it drifts toward whichever
leg compounded faster, and by the end the "60/40" label on the chart is describing an allocation that
no longer exists. There is no universally correct choice between that and rebalancing (both are used
in practice, under different names -- "buy-and-hold blend" vs "constant-mix index"), but leaving the
choice unstated is worse than either: a reader who assumes daily rebalancing when the code drifted, or
vice versa, misreads every figure this module produces. This module rebalances back to the target
weights at the close of every stored session, computed as the weighted sum of each leg's own daily
return, compounded day over day:

    equity *= 1 + sum(leg.weight * (close_t / close_t-1 - 1) for leg in blend.legs)

Two reasons for daily over some coarser period (monthly/annual): (1) the only calendar this module
has *is* daily bars -- picking a rebalance date coarser than the data invents a schedule the data
does not describe, where daily uses exactly the granularity that is actually stored; (2) it keeps the
comparability property this module exists for -- a basket with one leg at 100% weight must return
*exactly* what the existing single-symbol path returns over the same window (see
:mod:`tests.test_benchmarks`'s comparability test), and daily rebalancing of a single leg is a no-op
by construction (there is nothing else to rebalance against), which telescopes to the same
first-close/last-close ratio :func:`app.paperdesk.desk._buy_and_hold` computes. A less frequent
rebalance schedule would still agree in the single-leg case, but would need its own separate argument
for why that period rather than any other; daily needs none, because it is simply "every day this
module has a price for."

**Decision 3 -- a leg with insufficient history is an explicit, loud failure (:class:`InsufficientHistory`),
never a silently-shortened basket.** SPY's stored history goes back to 1993; AGG's starts in 2003 --
a real, current asymmetry in this store, not a hypothetical. Pricing a 1998-2026 60/40 SPY/AGG blend
by quietly starting the *basket* in 2003 (when AGG first has a bar) would flatter or distort the
figure two ways at once: the reported number would silently stop being "the 60/40 blend since 1998"
while still being labelled that, and the missing years -- which might have been SPY's worst or best --
would vanish from the comparison without a trace. Dropping the short leg and pricing 100% SPY instead
would be just as silent a substitution. Both are silent because both look like a normal, successful
result to a caller who only checks whether a number came back. This module refuses instead: if any
leg's stored history does not reach back to the window's start (or forward to its end),
:func:`price_blend` raises, naming the leg, its actual stored range, and the window it could not
cover, so the caller must consciously pick a window every leg can actually price rather than get a
number that quietly measures a shorter or different basket than the one asked for.

**How bars are read, matching ``desk.py``'s convention exactly.** ``_buy_and_hold`` reads a symbol's
*entire* stored history (not a bounded slice), then filters to the window's dates in pandas, and
prices off ``close`` -- not ``open`` or ``adj_close`` -- at the first and last row inside the window.
This module does the same, for the same two reasons ``_buy_and_hold`` gives implicitly: reading the
full history is what makes it possible to know whether a leg's data reaches back far enough (Decision
3) rather than merely observing an empty bounded slice with no way to tell "no data exists" apart from
"the window's start fell on a weekend", and pricing off ``close`` keeps every benchmark this
application renders side by side computed off the same price field (see ``desk.py``'s own note on
``_buy_and_hold`` vs the tournament engine's open-to-close convention -- mixing price fields inside
one comparison list is the mistake round 5's report caught and fixed). Reads go through
``duck.read_bars`` against an in-memory connection from ``duck.connect()`` (per this task's
constraints), which pins the connection's timezone to UTC -- see ``duck.connect``'s own docstring for
why an un-pinned connection would silently re-label timestamps in the host's local zone and shift
``.dt.date`` by a day for anyone west of UTC. Belt-and-suspenders with an explicit
``tz_convert("UTC")`` after the read, matching ``app.market.store._normalize_utc``'s defensive
posture on the same hazard.

**Money is ``Decimal``.** Every price and every weight is ``Decimal``, converted from the stored
``close`` column the same way ``_buy_and_hold`` does it -- ``Decimal(str(value))``, never
``Decimal(value)`` on a float, which would capture the float's binary representation error rather
than the decimal string actually stored. This module never touches ``float`` at a money boundary.

**Why the ``"qqq"`` entry exists.** SPY alone is not a neutral yardstick for a field that includes
concentrated tech and leveraged-Nasdaq sleeves (e.g. QLD, SSO): round 5 re-derived QQQ across the same
27 windows already used to score SPY and found QQQ compounded at +18.56%/yr over the trailing decade
against SPY's +12.14%/yr (``data/rounds/r5-2026-08/REPORT.md`` section 3) -- roughly half again SPY's
rate. Measured against SPY alone, that gap silently flatters every card whose holdings lean toward the
Nasdaq-100: `A-rotation`'s reported 10-year edge fell from +5.28%/yr to +0.6%/yr the moment QQQ was
used as the denominator instead of SPY -- the same nine semiconductor names, the same decade, a
four-and-a-half-point swing purely from which index the edge was measured against. A round that
compares such a card only to SPY is choosing the denominator that makes it look best, not the one that
best represents what it is actually competing against. Carrying `"qqq"` as a second single-symbol
blend, structurally identical to `"spy"`, lets every future round report a candidate against both and
let the reader see whichever gap the SPY-only comparison was hiding.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import decimal
import itertools
from collections.abc import Iterable
from decimal import Decimal

import duckdb
import pandas as pd

from app.config import Settings, get_settings
from app.db import duck

__all__ = [
    "REGISTRY",
    "Blend",
    "EqualWeightBasket",
    "InsufficientHistory",
    "Leg",
    "WeightError",
    "price_blend",
    "price_equal_weight_basket",
]


@dataclasses.dataclass(frozen=True, slots=True)
class Leg:
    """One symbol's fixed target weight inside a :class:`Blend`, e.g. ``Leg("SPY", Decimal("0.60"))``.

    ``weight`` is the *target* the blend rebalances back to at every session's close (see
    :mod:`app.paperdesk.benchmarks`'s module docstring, Decision 2) -- not merely the weight bought
    on day one, which is the whole distinction a "60/40 blend" is making a claim about.
    """

    symbol: str
    weight: Decimal


class WeightError(ValueError):
    """A :class:`Blend`'s leg weights did not sum to exactly 1.

    Names the blend and the actual sum, e.g. ``blend '60-40-spy-agg': leg weights sum to 1.10, not
    1`` -- deliberately not a generic "invalid weights", because the caller needs to see their own
    number to find the typo.
    """

    def __init__(self, name: str, total: Decimal) -> None:
        super().__init__(f"blend {name!r}: leg weights sum to {total}, not 1")
        self.name = name
        self.total = total


class InsufficientHistory(ValueError):
    """One leg of a :class:`Blend` cannot be priced across the whole requested window.

    Raised rather than pricing a shorter or substitute basket -- see the module docstring's Decision
    3. ``detail`` is a human-readable description of exactly how the leg's stored range falls short
    (e.g. "stored history starts 2003-09-29, after the window's start 1998-01-01"), so the error
    message names the actual dates rather than just "not enough data".
    """

    def __init__(self, blend_name: str, symbol: str, detail: str) -> None:
        super().__init__(
            f"blend {blend_name!r}: leg {symbol!r} cannot be priced over the requested window -- "
            f"{detail}"
        )
        self.blend_name = blend_name
        self.symbol = symbol
        self.detail = detail


@dataclasses.dataclass(frozen=True, slots=True)
class Blend:
    """A named, fixed-weight basket of symbols priced as one blended total return by
    :func:`price_blend`.

    ``__post_init__`` validates on construction, not on first use -- a ``Blend`` whose weights do not
    sum to 1 is not a deferred pricing failure, it is a malformed value that should never have existed
    long enough to be passed anywhere. See :class:`WeightError`.
    """

    name: str
    label: str
    legs: tuple[Leg, ...]

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError(f"blend {self.name!r}: has no legs")
        total = sum((leg.weight for leg in self.legs), Decimal(0))
        if total != Decimal(1):
            raise WeightError(self.name, total)


#: Named blends worth having, so a caller names a blend rather than repeating raw weights, and two
#: callers cannot silently disagree about what "60/40" means -- one spelling it 60/40, another
#: 59/41 by a rounding slip, both calling the result the same thing. Every entry here rebalances
#: daily; see :mod:`app.paperdesk.benchmarks`'s module docstring, Decision 2.
REGISTRY: dict[str, Blend] = {
    # A single-leg blend, so that "this book's benchmark" is one type everywhere rather than
    # "a symbol, or else a blend" with a branch at every use site. SPY at weight 1 priced through
    # `price_blend` is SPY: the daily-rebalance step Decision 2 describes is a no-op on one leg,
    # since a lone leg is already at its target weight every session by construction.
    "spy": Blend(
        name="spy",
        label="SPY",
        legs=(Leg(symbol="SPY", weight=Decimal("1")),),
    ),
    # A second single-symbol yardstick, structurally identical to "spy" above. Exists because SPY
    # alone understates the bar for Nasdaq-heavy and leveraged-Nasdaq candidates -- see the module
    # docstring's "Why the qqq entry exists" for round 5's numbers (QQQ +18.56%/yr vs SPY +12.14%/yr
    # over the trailing decade, which roughly halved `A-rotation`'s reported 10-year edge).
    "qqq": Blend(
        name="qqq",
        label="QQQ",
        legs=(Leg(symbol="QQQ", weight=Decimal("1")),),
    ),
    "60-40-spy-agg": Blend(
        name="60-40-spy-agg",
        label="60/40 SPY/AGG",
        legs=(
            Leg(symbol="SPY", weight=Decimal("0.60")),
            Leg(symbol="AGG", weight=Decimal("0.40")),
        ),
    ),
    # Added 2026-08-29 for `SAVINGS`, which stopped being a growth book on that date. 60/40 above was
    # already the *growth* compromise -- the yardstick for a book that wants equity exposure with the
    # edges taken off. The owner's savings mandate is now the safest of three books, explicitly
    # willing to accept the least return of the three, so measuring it against 60/40 would score a
    # preservation book against a growth alternative and read every point of forgone return as a
    # miss rather than as the trade it was chosen to be.
    #
    # 30/70 is a judgement, not a backtested optimum, and it is stated as one: no run in this repo
    # compared candidate savings benchmarks, and `strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md`
    # section 7c records it as an owner-overridable decision alongside the Roth's.
    "30-70-spy-agg": Blend(
        name="30-70-spy-agg",
        label="30/70 SPY/AGG",
        legs=(
            Leg(symbol="SPY", weight=Decimal("0.30")),
            Leg(symbol="AGG", weight=Decimal("0.70")),
        ),
    ),
}


def _read_full_history(
    conn: duckdb.DuckDBPyConnection, settings: Settings, symbol: str
) -> pd.DataFrame:
    """`symbol`'s entire stored daily history, ``ts`` re-expressed in UTC.

    Unbounded on purpose -- see the module docstring's "How bars are read" section: knowing whether a
    leg's history reaches back to (and through) a requested window requires seeing the leg's actual
    stored range, not just whatever a bounded query happens to return inside it.
    """
    frame = duck.read_bars(conn, settings.bars_dir, symbol, duck.Interval.DAY)
    if frame.empty or "ts" not in frame.columns:
        return frame
    frame = frame.copy()
    frame["ts"] = frame["ts"].dt.tz_convert("UTC")
    return frame


def price_blend(
    blend: Blend,
    *,
    start: dt.date,
    end: dt.date,
    settings: Settings | None = None,
) -> Decimal | None:
    """Total return of `blend` from `start` to `end`, rebalanced daily to its target weights.

    Returns ``None`` when the window itself yields fewer than two aligned trading sessions inside
    ``[start, end]`` -- an honestly unpriceable window, the same "unknown, not a fabricated zero"
    convention :func:`app.paperdesk.desk._buy_and_hold` uses. Raises :class:`InsufficientHistory`
    instead when a leg's *stored history* does not reach the window at all -- a different failure
    mode from "the window is short": that one is a property of the request, this one is a property of
    the data, and conflating them into the same `None` would let a data gap masquerade as an
    ordinary narrow window. Raises :class:`WeightError` only via :class:`Blend`'s own construction --
    `price_blend` never receives a `Blend` with invalid weights, because none can exist.
    """
    cfg = settings or get_settings()

    leg_closes: dict[str, dict[dt.date, Decimal]] = {}
    with duck.connect() as conn:
        for leg in blend.legs:
            frame = _read_full_history(conn, cfg, leg.symbol)
            if frame.empty:
                raise InsufficientHistory(blend.name, leg.symbol, "no stored bars at all")

            earliest = frame["ts"].iloc[0].date()
            latest = frame["ts"].iloc[-1].date()
            if earliest > start:
                raise InsufficientHistory(
                    blend.name,
                    leg.symbol,
                    f"stored history starts {earliest.isoformat()}, after the window's start "
                    f"{start.isoformat()}",
                )
            if latest < end:
                raise InsufficientHistory(
                    blend.name,
                    leg.symbol,
                    f"stored history ends {latest.isoformat()}, before the window's end "
                    f"{end.isoformat()}",
                )

            inside = frame[(frame["ts"].dt.date >= start) & (frame["ts"].dt.date <= end)]
            leg_closes[leg.symbol] = {
                row.ts.date(): Decimal(str(row.close)) for row in inside.itertuples()
            }

    common_dates = sorted(set.intersection(*(set(closes) for closes in leg_closes.values())))
    if len(common_dates) < 2:
        return None

    # `equity` accumulates at raised precision, then is rounded back down to the caller's ambient
    # context (28 significant digits, the `decimal` module default and what every other figure in this
    # codebase is computed under) *before* the final `- 1`, not after. That ordering is deliberate, not
    # cosmetic: this loop performs one division and one multiplication per day, where
    # `_buy_and_hold`'s `last / first - 1` performs one division total, so accumulating the running
    # product at only 28 digits throughout would compound rounding error across every session and
    # drift from `_buy_and_hold`'s figure at low digits -- measured directly during development. Fifty
    # digits keeps that intermediate error far below the 28th digit for any window this store holds.
    # But widening precision alone is not sufficient to match `_buy_and_hold` exactly on a
    # 100%-weight single leg (where `equity` is mathematically `last_close / first_close`): rounding
    # `equity - 1` to 28 digits *after* subtracting is a different operation from `_buy_and_hold`'s
    # `last/first - 1`, which rounds the *quotient* to 28 digits first and only then subtracts 1 --
    # and because the quotient sits near 1.0, that subtraction cancels its leading digit, so rounding
    # before vs after the subtraction lands on a different final digit. Rounding `equity` itself to 28
    # digits first (`+equity` below, evaluated back in the restored ambient context) and subtracting 1
    # only after reproduces `_buy_and_hold`'s own rounding point exactly, which is what the
    # comparability test in `tests/test_benchmarks.py` verifies against real stored bars.
    with decimal.localcontext() as ctx:
        ctx.prec = 50
        equity = Decimal(1)
        for prev_date, curr_date in itertools.pairwise(common_dates):
            day_return = Decimal(0)
            for leg in blend.legs:
                prev_price = leg_closes[leg.symbol][prev_date]
                curr_price = leg_closes[leg.symbol][curr_date]
                if prev_price <= 0:
                    return None
                day_return += leg.weight * (curr_price / prev_price - 1)
            equity *= Decimal(1) + day_return

    return +equity - Decimal(1)


@dataclasses.dataclass(frozen=True, slots=True)
class EqualWeightBasket:
    """The result of :func:`price_equal_weight_basket`: a basket's blended return, plus which of the
    requested symbols actually went into it.

    A second return type rather than reusing :class:`Blend`/:class:`price_blend`'s `Decimal | None`:
    this pricer's whole point is that a symbol lacking bars is *dropped*, not fatal (see
    :func:`price_equal_weight_basket`'s own docstring), and a caller cannot tell "every symbol priced"
    from "three of nine were silently excluded" from a bare number. `included`/`excluded` make that
    distinction inspectable rather than inferred.
    """

    return_pct: Decimal | None
    """`None` when not even one symbol could be priced over the window -- the same "unknown, not a
    fabricated zero" convention every benchmark in this package uses."""
    included: tuple[str, ...]
    """Symbols actually priced into the basket, in the order `symbols` was given (deduplicated)."""
    excluded: tuple[str, ...]
    """Symbols dropped for lacking at least two stored bars inside `[start, end]` -- same order."""


def price_equal_weight_basket(
    symbols: Iterable[str],
    *,
    start: dt.date,
    end: dt.date,
    settings: Settings | None = None,
) -> EqualWeightBasket:
    """Equal-dollar-weight, buy-once-and-hold return of `symbols` from `start` to `end` -- bought at
    each symbol's first stored close inside the window, held to its last, **never rebalanced**.

    **Why this is a second pricer rather than a call to `price_blend`.** `price_blend` rebalances back
    to its target weights at every session's close (see this module's Decision 2) -- the deliberate
    choice for a fixed-allocation benchmark like 60/40 SPY/AGG, where "60/40" is a claim about every
    day, not just day one. A card's own tradable universe is a different kind of yardstick: "what
    would buying this card's own picks, equally, and never touching them again have returned" -- the
    literal buy-and-hold alternative to the card's own rules, which by construction trade in and out.
    Daily-rebalancing that basket back to equal weight would price a *different*, hypothetical
    strategy (a systematic equal-weight rebalancer) instead of the plain "bought it and left it alone"
    question this benchmark exists to answer. So this function keeps each leg's own share count fixed
    from its first priced day onward, exactly as `app.paperdesk.desk._buy_and_hold` prices a single
    symbol -- `price_blend` with one leg already reduces to that identical arithmetic (see
    `tests/test_benchmarks.py`'s comparability test), and with `n` legs at equal weight and no
    rebalancing, the whole basket's return is just the plain average of each leg's own `last/first - 1`
    (every leg starts at the same dollar stake, so summing `n` equal stakes each grown by its own
    return and dividing by the total staked is exactly the mean of the per-leg returns).

    **Why a missing symbol is excluded, not fatal.** Unlike `price_blend`'s legs (a named, fixed
    60/40 blend where a short leg makes the *labelled* allocation false -- see Decision 3), a card's
    universe is a roster of names an analyst chose, any one of which can predate or postdate its own
    stored history without changing what "this card's universe, equal-weight" means for the rest of
    it. Raising on one thinly-covered symbol would take down every card's benchmark on the one card
    whose universe happens to include it; excluding it and saying so (`excluded`) is the same
    "degrade visibly, do not fail invisibly" posture `app.paperdesk.desk._book_benchmarks` already
    takes toward a book whose primary benchmark cannot price.

    **Price convention.** Identical to `price_blend` and `_buy_and_hold`: full stored history read via
    `duck.read_bars` against an in-memory `duck.connect()`, filtered to `[start, end]`, priced off raw
    `close` (never `adj_close`) as `Decimal(str(value))`. See this module's docstring, "How bars are
    read" and "Money is `Decimal`", for why.

    A symbol is excluded when its full history is empty, or its bars inside `[start, end]` number
    fewer than two (nothing to compute a return from), or its first inside-window close is not
    positive. `symbols` is deduplicated, preserving first occurrence, before pricing -- a universe
    that names the same symbol twice must not double its weight in the basket.
    """
    cfg = settings or get_settings()

    included: list[str] = []
    excluded: list[str] = []
    leg_returns: list[Decimal] = []
    with duck.connect() as conn:
        for symbol in dict.fromkeys(symbols):
            frame = _read_full_history(conn, cfg, symbol)
            if frame.empty:
                excluded.append(symbol)
                continue
            inside = frame[(frame["ts"].dt.date >= start) & (frame["ts"].dt.date <= end)]
            if len(inside) < 2:
                excluded.append(symbol)
                continue
            first_close = Decimal(str(inside["close"].iloc[0]))
            last_close = Decimal(str(inside["close"].iloc[-1]))
            if first_close <= 0:
                excluded.append(symbol)
                continue
            leg_returns.append(last_close / first_close - 1)
            included.append(symbol)

    if not leg_returns:
        return EqualWeightBasket(return_pct=None, included=(), excluded=tuple(excluded))

    with decimal.localcontext() as ctx:
        ctx.prec = 50
        average = sum(leg_returns, Decimal(0)) / Decimal(len(leg_returns))

    return EqualWeightBasket(return_pct=+average, included=tuple(included), excluded=tuple(excluded))
