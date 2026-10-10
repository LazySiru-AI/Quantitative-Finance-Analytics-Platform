"""The indicator registry: every spec in one place, and the computation entry point.

This is the module the API layer, the Phase 6 rule DSL, and the Phase 7 backtest workbench all
import instead of the individual indicator modules -- so a name added here is instantly available
to all three, and none of them can define its own competing notion of what ``"rsi"`` means.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

import pandas as pd

from app.indicators.base import IndicatorRequest, IndicatorSpec, parse_spec
from app.indicators.momentum import RSI_SPEC
from app.indicators.swing import MACD_AT_SWING_SPEC, RSI_AT_SWING_SPEC, SWING_SPEC
from app.indicators.trend import EMA_SPEC, MACD_SPEC, SMA_SPEC
from app.indicators.volatility import ATR_SPEC, BB_SPEC
from app.indicators.vwap import VWAP_SPEC
from app.market.models import Interval

__all__ = [
    "REGISTRY",
    "catalog",
    "compute",
    "default_spec",
    "get",
    "request",
]

#: Registration order is display order (:func:`catalog`) -- the frontend's overlay menu lists
#: indicators in this sequence, so it is chosen for a sensible menu rather than alphabetically.
REGISTRY: dict[str, IndicatorSpec] = {
    spec.name: spec
    for spec in (
        SMA_SPEC,
        EMA_SPEC,
        MACD_SPEC,
        RSI_SPEC,
        BB_SPEC,
        ATR_SPEC,
        VWAP_SPEC,
        SWING_SPEC,
        RSI_AT_SWING_SPEC,
        MACD_AT_SWING_SPEC,
    )
}


def get(name: str) -> IndicatorSpec | None:
    """Look up a spec by its lowercase token. ``None`` if nothing is registered under that name."""
    return REGISTRY.get(name.strip().lower())


def catalog() -> list[IndicatorSpec]:
    """Every registered spec, in stable registration order, for the UI's overlay menu."""
    return list(REGISTRY.values())


def request(spec_text: str, *, interval: Interval | None = None) -> IndicatorRequest:
    """Parse a spec string (``"bb:20,2"``) against the registry."""
    return parse_spec(spec_text, get, interval=interval)


def compute(bars: pd.DataFrame, requests: Sequence[IndicatorRequest]) -> pd.DataFrame:
    """Compute every requested indicator against ``bars`` into one frame.

    Does not mutate ``bars``. An empty ``bars`` frame (a symbol with no stored history yet, an
    ordinary state on a fresh install) returns an empty frame carrying the requested columns rather
    than raising -- every indicator function already returns an empty, correctly-shaped result for
    an empty input, so there is nothing special-cased here beyond assembling the columns.
    """
    columns: dict[str, pd.Series] = {}
    for req in requests:
        result = req.compute(bars)
        for col in req.columns:
            columns[col] = result[col]
    return pd.DataFrame(columns, index=bars.index)


def _fmt_default(value: Any) -> str:
    """Render a parameter's default for a spec string: no trailing ``.0`` on whole floats.

    Mirrors :func:`app.indicators.base._fmt` (private to that module, so not imported directly)
    because the round-trip this function exists for -- ``default_spec(spec)`` parsing back through
    :func:`app.indicators.base.parse_spec` to the same params -- depends on producing text that
    ``ParamSpec.coerce`` reads back to the exact default value, which is the same requirement that
    function's formatting serves.
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)


def default_spec(spec: IndicatorSpec) -> str:
    """The spec string for ``spec``'s own defaults -- ``"bb:20,2"``. Round-trips through :func:`request`."""
    if not spec.params:
        return spec.name
    args = ",".join(_fmt_default(p.default) for p in spec.params)
    return f"{spec.name}:{args}"
