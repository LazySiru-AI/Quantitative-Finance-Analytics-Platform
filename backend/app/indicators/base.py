"""The indicator contract: parameter specs, output naming, and the wire format.

An indicator is a pure function from a bar frame to a frame of derived columns, described by an
:class:`IndicatorSpec` that is rich enough for the frontend to build its own controls from -- so the
overlay menu is generated from the same object the maths hangs off, and cannot drift from it.

**Warmup is a first-class output, not an implementation detail.** Every indicator with a lookback
window is undefined for its first *n* bars and must return ``NaN`` there. Seeding those positions
with zeros, or with a partial-window average, is the single most common way a backtest reports an
edge that is really just the warmup artefact. :attr:`IndicatorSpec.warmup` states the count so a
study can drop the region rather than discover it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import pandas as pd

from app.market.models import Interval

__all__ = [
    "IndicatorError",
    "IndicatorFn",
    "IndicatorRequest",
    "IndicatorSpec",
    "Pane",
    "ParamKind",
    "ParamSpec",
    "UnknownIndicator",
    "column_name",
    "parse_spec",
    "wilder_smooth",
]


class IndicatorError(ValueError):
    """A malformed request: unknown name, wrong arity, out-of-range parameter, wrong interval."""


class UnknownIndicator(IndicatorError):
    """No indicator is registered under that name."""


class Pane(StrEnum):
    """Where the frontend draws the result.

    Part of the contract rather than a frontend choice: an RSI plotted on the price axis is
    invisible, and a moving average plotted in its own pane loses the only comparison that matters.
    """

    PRICE = "price"
    """Overlaid on the candles, same axis."""
    OSCILLATOR = "oscillator"
    """Separate pane below, own scale."""


class ParamKind(StrEnum):
    INT = "int"
    FLOAT = "float"
    DATE = "date"
    CHOICE = "choice"
    CHOICE_OR_DATE = "choice_or_date"
    """One of the fixed tokens in :attr:`ParamSpec.choices`, *or* an arbitrary ISO date.

    Exists for the anchored VWAP anchor, which is either ``"session"`` or a date to accumulate
    from. Neither :attr:`CHOICE` nor :attr:`DATE` can express that alone, and the difference is not
    academic: the frontend builds its controls from this kind, so encoding the anchor as a
    ``CHOICE`` over ``("session",)`` would render a dropdown with one option and leave the
    date-anchored form -- the whole point of an *anchored* VWAP for post-drawdown analysis --
    unreachable from the UI.
    """


@dataclass(frozen=True, slots=True)
class ParamSpec:
    """One parameter, with enough metadata for the UI to render an input and validate it."""

    name: str
    kind: ParamKind
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    label: str = ""

    def coerce(self, raw: str) -> Any:
        """Parse one positional argument from a spec string, or raise :class:`IndicatorError`."""
        text = raw.strip()
        try:
            match self.kind:
                case ParamKind.INT:
                    value: Any = int(text)
                case ParamKind.FLOAT:
                    value = float(text)
                case ParamKind.DATE:
                    value = dt.date.fromisoformat(text)
                case ParamKind.CHOICE:
                    if text not in self.choices:
                        raise IndicatorError(
                            f"{self.name}: {text!r} is not one of {', '.join(self.choices)}"
                        )
                    value = text
                case ParamKind.CHOICE_OR_DATE:
                    # Tokens win over dates: the fixed vocabulary is small and closed, so a token
                    # can never be a valid ISO date and the order costs nothing.
                    if text in self.choices:
                        value = text
                    else:
                        try:
                            value = dt.date.fromisoformat(text)
                        except ValueError as exc:
                            options = " or ".join(repr(c) for c in self.choices)
                            raise IndicatorError(
                                f"{self.name}: {text!r} is not {options} or an ISO date (YYYY-MM-DD)"
                            ) from exc
        except IndicatorError:
            raise
        except ValueError as exc:
            raise IndicatorError(f"{self.name}: cannot read {text!r} as {self.kind}") from exc

        if self.kind in (ParamKind.INT, ParamKind.FLOAT):
            if self.minimum is not None and value < self.minimum:
                raise IndicatorError(f"{self.name}: {value} is below the minimum {self.minimum}")
            if self.maximum is not None and value > self.maximum:
                raise IndicatorError(f"{self.name}: {value} is above the maximum {self.maximum}")
        return value


def wilder_smooth(values: pd.Series, period: int) -> pd.Series:
    """Wilder's recursive smoothing, correctly seeded -- shared by RSI's gain/loss averages and ATR.

    This is *not* ``values.ewm(alpha=1/period, adjust=False).mean()``. Pandas seeds that
    recursion from ``values``' first single observation, and with ``alpha = 1/period`` the
    resulting series takes a very long time to converge on Wilder's published numbers -- wrong by
    double-digit RSI points through the first several dozen bars on real data. Wilder's own
    definition seeds the first average as the **simple mean of the first `period` values**, then
    recurses ``avg_t = (avg_{t-1} * (period - 1) + values_t) / period`` from the next position
    onward. This function does exactly that: the seed lands at index ``period - 1`` (0-based) --
    RSI callers, whose gain/loss series already carries one leading NaN from ``close.diff()``,
    drop that leading element before calling this so their own first settled value lands at
    ``period``, matching Wilder's worked examples.

    A ``NaN`` in ``values`` after the seed has settled makes ``ewm`` hold the previous average
    forward rather than emit ``NaN`` at that position (pandas' "skip missing, don't update state"
    semantics) -- callers that care about that (RSI, ATR: see their modules' docstrings) re-mask
    the affected bar back to ``NaN`` themselves, since only they know which of their own inputs
    that bar's ``values`` entry traces back to.
    """
    result = pd.Series(float("nan"), index=values.index, dtype="float64")
    n = len(values)
    if n < period:
        return result

    # The seed is the *simple* mean of the first `period` values -- `skipna=False` so a NaN
    # anywhere in that window makes the seed itself NaN (and everything after it, since ewm can
    # only hold a NaN state forward) rather than silently averaging fewer than `period` values.
    seed = values.iloc[:period].mean(skipna=False)
    seed_index = values.index[period - 1]
    tail = values.iloc[period:]
    # Feeding `seed` in as ewm's own first observation reproduces Wilder's recursion exactly:
    # `adjust=False` computes `y_0 = x_0` and `y_t = alpha*x_t + (1-alpha)*y_{t-1}` for t > 0,
    # which -- once `x_0` is already an *average* rather than a raw observation -- is precisely
    # `avg_t = (avg_{t-1} * (period - 1) + x_t) / period` with `alpha = 1/period`.
    sub = pd.concat([pd.Series([seed], index=[seed_index]), tail])
    smoothed = sub.ewm(alpha=1 / period, adjust=False).mean()
    result.loc[smoothed.index] = smoothed
    return result


class IndicatorFn(Protocol):
    """``fn(bars, **params) -> DataFrame`` sharing the input index.

    ``bars`` carries :data:`~app.market.models.BAR_COLUMNS`. The returned frame's columns are named
    by :func:`column_name` and its index is *identical* to the input's -- same length, same order.
    Returning a shortened frame with the warmup rows trimmed away breaks alignment with the bars,
    and the misalignment shows up as an indicator that leads price by *n* bars, which reads as
    prophecy rather than as a bug.
    """

    def __call__(self, bars: pd.DataFrame, /, **params: Any) -> pd.DataFrame: ...


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    """A registered indicator."""

    name: str
    """Lowercase token used in spec strings and column names: ``sma``, ``bb``, ``macd``."""
    title: str
    fn: IndicatorFn
    params: tuple[ParamSpec, ...] = ()
    outputs: tuple[str, ...] = ()
    """Suffixes for a multi-column indicator -- Bollinger is ``("upper", "mid", "lower")``. Empty
    means one column carrying no suffix."""
    pane: Pane = Pane.PRICE
    intervals: frozenset[Interval] | None = None
    """``None`` means every interval. Anchored VWAP sets ``{5m, 1h}``: a session anchor has no
    meaning on a bar that *is* a session, and drawing it anyway yields a line that looks
    authoritative and says nothing."""
    warmup: Callable[[Mapping[str, Any]], int] = lambda _p: 0
    """Bars that will be ``NaN`` at the head of the output, given the parameters.

    Exact for every indicator whose settling time is a function of its parameters alone -- which is
    all of them except where :attr:`data_dependent_warmup` says otherwise.
    """
    data_dependent_warmup: bool = False
    """``True`` when the leading-``NaN`` count depends on the *data* as well as the parameters, so
    :attr:`warmup` is a guaranteed **lower bound** rather than an exact count.

    Only the swing-pivot family sets this. A pivot indicator cannot publish until price actually
    turns: ``swing(5)`` needs at least ``2 * 5`` bars, but on a monotonically rising series the first
    swing low may not confirm for hundreds of bars, and no function of ``lookback`` can say when.
    Every other indicator here settles on a schedule fixed by its parameters, and
    ``tests/test_indicators.py::TestRegistryWideContract`` holds them to exact equality precisely so
    a miscounted warmup surfaces as a failure -- this flag narrows that assertion to ``>=`` for the
    few specs that genuinely cannot promise more, rather than loosening it for all of them.

    Both consumers of ``warmup`` tolerate a lower bound: :mod:`app.backtest.guards` uses it only to
    choose truncation points past the settling region, and :mod:`app.api.market` reports it to the
    client for display.
    """
    description: str = ""

    def supports(self, interval: Interval) -> bool:
        return self.intervals is None or interval in self.intervals

    def columns(self, params: Mapping[str, Any]) -> tuple[str, ...]:
        base = column_name(self.name, [params[p.name] for p in self.params])
        return (base,) if not self.outputs else tuple(f"{base}_{s}" for s in self.outputs)


def _fmt(value: Any) -> str:
    """Render a parameter for a column name: stable, and no trailing ``.0`` on whole floats."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)


def column_name(name: str, values: list[Any]) -> str:
    """``sma`` + ``[20]`` -> ``sma_20``; ``bb`` + ``[20, 2.0]`` -> ``bb_20_2``.

    Parameters are baked into the name so two configurations of one indicator coexist in a single
    frame. The rule DSL in Phase 6 parses these back, so the format is load-bearing rather than
    cosmetic.
    """
    return "_".join([name, *(_fmt(v) for v in values)]) if values else name


@dataclass(frozen=True, slots=True)
class IndicatorRequest:
    """A resolved request: which indicator, with which arguments."""

    spec: IndicatorSpec
    params: Mapping[str, Any]

    @property
    def columns(self) -> tuple[str, ...]:
        return self.spec.columns(self.params)

    @property
    def key(self) -> str:
        """Round-trips to the spec string that produced it."""
        return column_name(self.spec.name, [self.params[p.name] for p in self.spec.params])

    def compute(self, bars: pd.DataFrame) -> pd.DataFrame:
        return self.spec.fn(bars, **dict(self.params))


def parse_spec(
    text: str, lookup: Callable[[str], IndicatorSpec | None], *, interval: Interval | None = None
) -> IndicatorRequest:
    """Parse ``"bb:20,2"`` into a request, filling omitted trailing arguments from defaults.

    Positional and comma-separated, matching :attr:`IndicatorSpec.params` order. ``"sma"`` alone is
    the default configuration. Extra arguments are an error rather than being ignored -- silently
    dropping the third argument of ``macd:12,26,9`` on an indicator that takes two would compute
    something other than what the user asked for and label it with their parameters.

    A blank positional field is an error, not something to drop: dropping ``arg_text.split(",")``'s
    empty strings wholesale (rather than rejecting them) would shift every argument after the gap
    into the wrong parameter -- ``"macd:,26,9"`` would silently become ``fast=26, slow=9,
    signal=9`` instead of raising. The one tolerated exception is a single *trailing* empty field
    (``"macd:12,26,9,"``, a harmless trailing comma), which is dropped rather than rejected.
    """
    raw_name, _, arg_text = text.strip().partition(":")
    spec = lookup(raw_name.strip().lower())
    if spec is None:
        raise UnknownIndicator(f"unknown indicator {raw_name.strip()!r}")

    if not arg_text.strip():
        args: list[str] = []
    else:
        raw_args = arg_text.split(",")
        if len(raw_args) > 1 and not raw_args[-1].strip():
            raw_args = raw_args[:-1]  # one tolerated trailing empty field
        if any(not a.strip() for a in raw_args):
            raise IndicatorError(
                f"{spec.name}: {arg_text!r} has an empty argument -- omit trailing arguments to "
                "use their defaults instead of leaving a gap"
            )
        args = raw_args
    if len(args) > len(spec.params):
        raise IndicatorError(
            f"{spec.name} takes at most {len(spec.params)} argument(s), got {len(args)}"
        )
    if interval is not None and not spec.supports(interval):
        allowed = ", ".join(sorted(i.value for i in (spec.intervals or ())))
        raise IndicatorError(f"{spec.name} is not defined on {interval.value} bars (only {allowed})")

    params = {
        p.name: p.coerce(args[i]) if i < len(args) else p.default
        for i, p in enumerate(spec.params)
    }
    return IndicatorRequest(spec=spec, params=params)
