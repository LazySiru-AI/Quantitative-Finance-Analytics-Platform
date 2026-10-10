"""Bind a FRED series to a bar index by **release date**, so a rule reads only what was published.

This module exists because the obvious join is wrong, and wrong in the direction that inflates a
backtest.

**The trap.** FRED serves the *currently revised* value against the *reference* date. Core CPI for
July carries the date ``2026-07-01`` and is published in mid-August. A rule that reads
``macro(CPILFESL)`` on ``2026-07-15`` by asking "what is the most recent point dated on or before
today" gets July's number six weeks before anyone had it. That is the same shape of lookahead
``strategy-program/CONSTRAINTS.md`` describes for 13F filings -- where a position held on 30 September
may not be public until 14 November -- and it is worth remembering how that one was caught:

    "Round 1 ranked a 13F-derived card on four windows predating its own filings -- caught by a
    reader, not a tool, because the eligibility check asks whether a card's *symbols* have history and
    nothing asked whether its *basket* was knowable."  (``PROTOCOL.md`` section 9)

**Why this cannot reuse :mod:`app.market.macro`.** That module's ``as_of`` truncation is the closest
existing code and it selects on ``point.date <= target`` -- the reference date. It is *correct there*:
a dashboard reader asking what the ten-year printed through June 1st wants the value labelled June
1st. It is exactly wrong for a rule, for the same reason ``as_of=None`` on a 13F call "silently gives
you tomorrow's newspaper". Nothing in this module calls ``_truncate_to_as_of`` or
``_nearest_on_or_before``, and nothing should.

**The binding.** Every :class:`~app.market.macro_models.MacroPoint` is given an *eligibility date* --
``point.date + RELEASE_LAG[field]`` -- and a bar at date ``t`` sees the most recent point whose
eligibility date is ``<= t``. The join happens once per card per field, here, rather than per node in
the evaluator, so there is exactly one place this rule can be got wrong.

**What this closes and what it does not.** It closes the *lag* leak. It does **not** close the
*revision* leak: if BLS revised July's core CPI in the September release, the value bound to July's
eligibility date is the September-revised number, not what actually printed in mid-August. Closing
that needs FRED's ALFRED vintage archive (``realtime_start``/``vintage_dates``), which
:class:`~app.market.providers.fred.FredProvider` does not speak. ``ROUND-21-PLAN.md`` section 2d states
this as a known, unclosed second channel, and a guard pass here must never be read as proving
point-in-time correctness -- only that the configured lag was respected.
"""

from __future__ import annotations

import bisect
import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import pandas as pd

from app.market.macro_models import MacroSeries
from app.rules.nodes import (
    Arith,
    BoolOp,
    Comparison,
    Cross,
    MacroField,
    MacroRef,
    Not,
)

__all__ = [
    "RELEASE_LAG",
    "ReleaseBindingViolation",
    "UnlistedMacroFieldError",
    "bind_macro",
    "eligibility_dates",
    "required_macro_fields",
    "verify_release_binding",
]


#: How long after its reference date a series is actually published, per field.
#:
#: **The daily rates carry one trading day, matching the engine's own convention.** A yield or spot
#: price stamped with a session's date is known after that session closes, and
#: ``app.backtest.strategy`` already refuses to act on a signal in the bar that produced it: decisions
#: use data strictly before the decision session and fills happen at the next session's open. A daily
#: macro value is treated the same way, so ``macro(DGS10)`` on a decision bar is the previous
#: session's print, never the one being decided on.
#:
#: **The monthly indices carry 45 calendar days, and that number is a deliberately conservative
#: placeholder rather than a claimed release calendar.** Real CPI publishes roughly two weeks after
#: month-end and PCE roughly four. 45 days is chosen for symmetry with the 13F statute's own 45-day
#: figure (``CONSTRAINTS.md``) and because it errs in the only safe direction: it excludes history
#: that was in fact available, and never admits a value that was not. Replacing it with the BLS and
#: BEA release calendars is real work this module does not do, and ``ROUND-21-PLAN.md`` section 6
#: lists it as an open gap rather than a detail.
#:
#: **A field missing from this table is an error, never a zero default.** See
#: :class:`UnlistedMacroFieldError`.
RELEASE_LAG: Mapping[MacroField, dt.timedelta] = MappingProxyType(
    {
        MacroField.DGS10: dt.timedelta(days=1),
        MacroField.T10Y2Y: dt.timedelta(days=1),
        MacroField.T10YIE: dt.timedelta(days=1),
        MacroField.DCOILWTICO: dt.timedelta(days=1),
        MacroField.PCEPI: dt.timedelta(days=45),
        MacroField.PCEPILFE: dt.timedelta(days=45),
        MacroField.CPILFESL: dt.timedelta(days=45),
    }
)


class UnlistedMacroFieldError(LookupError):
    """A :class:`MacroField` was referenced with no :data:`RELEASE_LAG` entry.

    Raised rather than defaulting to a zero lag, and the distinction is the whole point: a zero lag
    binds by reference date, which is precisely the lookahead this module exists to prevent. A new
    series added to :class:`MacroField` and forgotten here would otherwise produce a *better* backtest
    result and no error at all -- the failure mode that is hardest to notice, because nothing looks
    broken.

    This mirrors ``app.backtest.guards._unlisted_node_types``, which fails closed on an AST node type
    the guard has not been told about, for the same reason.
    """

    def __init__(self, field: MacroField) -> None:
        self.field = field
        super().__init__(
            f"macro field {field.value!r} has no RELEASE_LAG entry, so the date it became knowable "
            f"is unknown. Add it to app.rules.macro_binding.RELEASE_LAG -- it is not defaulted to "
            f"zero, because a zero lag reads a value on the day it refers to rather than the day it "
            f"was published, which is the lookahead this module exists to prevent."
        )


def required_macro_fields(node: object) -> list[MacroField]:
    """Every :class:`MacroField` the tree reaches, in first-encountered order, deduplicated.

    Lives here rather than beside ``app.backtest.guards.required_indicator_refs`` because the runner
    needs it to build a frame *before* any guard runs, and routing that through the guard module
    would make every caller that merely wants to evaluate a rule import the thing that checks it.

    Enumerated by walking the tree, not by running it, which is what makes the guard's fail-closed
    lag check possible: a card's reachable series set is known statically, so a field with no
    :data:`RELEASE_LAG` entry is caught before a bar is touched rather than on the first session the
    branch happens to be taken.
    """
    seen: dict[MacroField, None] = {}

    def walk(n: object) -> None:
        match n:
            case MacroRef(field=field):
                seen.setdefault(field, None)
            case Arith(left=left, right=right):
                walk(left)
                walk(right)
            case Comparison(left=left, right=right) | Cross(left=left, right=right):
                walk(left)
                walk(right)
            case Not(operand=operand):
                walk(operand)
            case BoolOp(operands=operands):
                for operand in operands:
                    walk(operand)

    walk(node)
    return list(seen)


def eligibility_dates(
    field: MacroField, points: Sequence[object]
) -> list[tuple[dt.date, float | None]]:
    """``(eligibility_date, value)`` per point, chronological -- the shifted series a bar joins to.

    Split out from :func:`bind_macro` so the guard can re-derive the same dates independently and
    check them against the sessions actually scored, rather than trusting the join that produced
    them. ``app.backtest.guards`` does exactly that: it proves the property after the fact instead of
    assuming the code above got it right, the same posture the existing causality check takes toward
    indicators.
    """
    lag = RELEASE_LAG.get(field)
    if lag is None:
        raise UnlistedMacroFieldError(field)
    out: list[tuple[dt.date, float | None]] = []
    for point in points:
        date = point.date  # type: ignore[attr-defined]
        value = point.value  # type: ignore[attr-defined]
        out.append((date + lag, value))
    out.sort(key=lambda pair: pair[0])
    return out


def bind_macro(
    fields: Sequence[MacroField],
    series: Mapping[MacroField, MacroSeries],
    index: pd.Index,
    *,
    dates: Sequence[dt.date] | None = None,
) -> pd.DataFrame:
    """One ``float64`` column per field, indexed like ``index``, release-date bound.

    ``NaN`` before a field's first eligible observation, which is the honest value there: the series
    existed but nothing had been published yet, and a rule comparing against ``NaN`` yields ``NA``
    through the evaluator's Kleene layer rather than a silent ``False``. That matters at the start of
    a long window -- a monthly index with a 45-day lag has no value at all for the first six weeks,
    and a card gated on it must be *undefined* there, not *excluded*.

    Values are carried forward between observations by construction, not by an interpolation choice:
    a monthly series genuinely holds its last published value until the next release, which is what a
    decision-maker actually knew on each of those days.
    """
    if len(fields) == 0:
        return pd.DataFrame(index=index)

    # `dates` is supplied when the caller's frame carries its timestamps in a `ts` *column* over a
    # positional index -- which `app.backtest.strategy` and `app.backtest.events` both do. Deriving
    # them from a positional index instead would silently bind every bar to 1970 rather than raise,
    # so the caller states them when it has them. See :func:`bind_for_bars`.
    bar_dates = list(dates) if dates is not None else _as_dates(index)
    if len(bar_dates) != len(index):
        raise ValueError(
            f"got {len(bar_dates)} dates for {len(index)} bars; the two must correspond one-to-one "
            f"or the join silently attributes a macro value to the wrong session"
        )
    columns: dict[str, pd.Series] = {}
    for field in dict.fromkeys(fields):
        macro_series = series.get(field)
        if macro_series is None:
            raise KeyError(
                f"no MacroSeries supplied for {field.value!r}; bind_macro cannot invent one, and "
                f"defaulting it to NaN would make a card silently never trade rather than fail"
            )
        pairs = eligibility_dates(field, macro_series.points)
        columns[field.value] = _asof_column(pairs, bar_dates, index)
    return pd.DataFrame(columns, index=index)


def _as_dates(index: pd.Index) -> list[dt.date]:
    """``index`` as plain dates, tz-naive, for comparison against a FRED observation date.

    A bar index is timestamped and may be tz-aware; a FRED date is a bare calendar day. Comparing the
    two directly is either a TypeError or, worse, an off-by-one when a tz-aware midnight converts
    backwards across the date line. Normalising once here keeps that conversion in a single place
    instead of at every comparison.
    """
    converted = pd.DatetimeIndex(index)
    if converted.tz is not None:
        converted = converted.tz_convert("UTC").tz_localize(None)
    return [ts.date() for ts in converted]


def _asof_column(
    pairs: Sequence[tuple[dt.date, float | None]],
    bar_dates: Sequence[dt.date],
    index: pd.Index,
) -> pd.Series:
    """The most recent value whose eligibility date is ``<=`` each bar date.

    A straight linear merge rather than :func:`pandas.merge_asof`, because both sides are already
    sorted and the semantics wanted here ("strictly on or before, carry forward, NaN before the
    first") are one loop and no keyword arguments to misread. ``None`` values -- FRED's ``.`` for a
    market holiday -- do not advance the carried value: a holiday is not a publication, so the last
    real print stands, which is what a reader on that day would have seen.
    """
    values: list[float] = []
    carried = float("nan")
    cursor = 0
    for bar_date in bar_dates:
        while cursor < len(pairs) and pairs[cursor][0] <= bar_date:
            value = pairs[cursor][1]
            if value is not None:
                carried = float(value)
            cursor += 1
        values.append(carried)
    return pd.Series(values, index=index, dtype="float64")


def bind_for_bars(
    node: object,
    bars: pd.DataFrame,
    *,
    series: Mapping[MacroField, MacroSeries] | None = None,
) -> pd.DataFrame | None:
    """The macro frame ``node`` needs for ``bars``, or ``None`` if it references no macro series.

    The one function the run path calls. Returning ``None`` for the overwhelmingly common case -- a
    rule with no ``macro(...)`` in it -- is what lets every existing caller keep its current
    behaviour exactly: :func:`app.rules.evaluate.evaluate` treats ``macro=None`` as "this caller
    supports no macro", and a tree with no :class:`MacroRef` never asks it for one.

    ``series`` defaults to the pin named by ``INVDASH_MACRO_PIN``
    (:func:`app.rules.macro_pin.active_pin`), which raises if none is configured. **A live fetch is
    never attempted**, here or anywhere below this function: an unpinned run reproduces its dates and
    not its values, which is the failure that looks like success.

    **Dates come from the ``ts`` column when there is one, and the index otherwise.** The two bar
    frames in this codebase disagree: :mod:`app.backtest.strategy` and :mod:`app.backtest.events`
    carry ``ts`` as a column over a positional index, while the rules service indexes by timestamp
    directly. Guessing wrong does not raise -- it silently binds every bar to the same date, or to
    1970 -- so the shape is detected rather than assumed.
    """
    fields = required_macro_fields(node)
    if not fields:
        return None
    if series is None:
        from app.rules.macro_pin import active_pin

        series = active_pin()
    dates = _bar_dates(bars)
    return bind_macro(fields, series, bars.index, dates=dates)


def _bar_dates(bars: pd.DataFrame) -> list[dt.date]:
    """Each bar's calendar date, from ``ts`` if present, else from the index."""
    if "ts" in bars.columns:
        column = pd.DatetimeIndex(bars["ts"])
        if column.tz is not None:
            column = column.tz_convert("UTC").tz_localize(None)
        return [ts.date() for ts in column]
    return _as_dates(bars.index)


@dataclass(frozen=True, slots=True)
class ReleaseBindingViolation:
    """One bar where the bound value is not what release-date eligibility permits."""

    field: MacroField
    bar_date: dt.date
    bound_value: float | None
    expected_value: float | None

    def describe(self) -> str:
        bound = "NaN" if self.bound_value is None else f"{self.bound_value}"
        expected = "NaN" if self.expected_value is None else f"{self.expected_value}"
        return (
            f"macro({self.field.value}) on {self.bar_date.isoformat()}: bound {bound}, but only "
            f"{expected} had been released by then"
        )


def verify_release_binding(
    bound: pd.DataFrame,
    fields: Sequence[MacroField],
    series: Mapping[MacroField, MacroSeries],
    dates: Sequence[dt.date],
) -> list[ReleaseBindingViolation]:
    """Re-derive what each bar was entitled to see, and report every bar where it saw something else.

    **This proves the property rather than implementing it, which is why it exists at all.**
    :func:`bind_macro` is the code that is supposed to be causal; a test of `bind_macro` written by
    whoever wrote `bind_macro` mostly proves they were consistent with themselves. This walks the
    *output* and asks, per bar, whether the value present there could have been known on that date --
    the same posture ``app.backtest.guards`` already takes toward indicators, where causality is
    checked by recomputing on truncated data rather than by trusting the indicator's own code.

    It is deliberately built differently from the thing it checks. :func:`_asof_column` carries a
    forward cursor across bars; this bisects an explicit eligibility list per bar, so a cursor bug --
    an off-by-one, a failure to reset, a mis-ordered input -- cannot be reproduced identically here
    and cancel out.

    An empty return is the pass. A non-empty one means at least one bar read a figure before it was
    published, which is lookahead, and no result from that run should be quoted.
    """
    violations: list[ReleaseBindingViolation] = []
    for field in dict.fromkeys(fields):
        macro_series = series.get(field)
        if macro_series is None or field.value not in bound.columns:
            continue
        pairs = eligibility_dates(field, macro_series.points)
        elig = [pair[0] for pair in pairs]
        # `carried[i]` is the newest non-None value among pairs[0..i] -- what a reader would have
        # had once pairs[i] was public, since an unobserved point publishes nothing.
        carried: list[float | None] = []
        latest: float | None = None
        for _, value in pairs:
            if value is not None:
                latest = float(value)
            carried.append(latest)

        column = bound[field.value]
        for position, bar_date in enumerate(dates):
            eligible_count = bisect.bisect_right(elig, bar_date)
            expected = carried[eligible_count - 1] if eligible_count > 0 else None
            raw = column.iloc[position]
            actual = None if pd.isna(raw) else float(raw)
            if actual != expected:
                violations.append(
                    ReleaseBindingViolation(
                        field=field,
                        bar_date=bar_date,
                        bound_value=actual,
                        expected_value=expected,
                    )
                )
    return violations
