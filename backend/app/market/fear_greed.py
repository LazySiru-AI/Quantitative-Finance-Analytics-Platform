"""The local fallback Fear & Greed composite.

:class:`app.market.providers.cnn.CnnFearGreedProvider` fetches CNN's own index while it is reachable.
It is unofficial and undocumented and will break without notice; when it does, something still has to
render the Fear & Greed tile. That something is :func:`composite_fear_greed`.

**What it is scored from.** CNN's endpoint publishes each of the seven components' raw underlying
measurement -- the S&P's index level, the VIX level, the raw put/call ratio -- but never the
normalisation that turns a raw value into a 0-100 score, nor the weights that combine seven scores
into one. :func:`composite_fear_greed` therefore does not, and cannot, reproduce CNN's number. It
derives its *own* scoring from the same raw inputs and is transparent about doing so:
:attr:`~app.market.macro_models.FearGreedComponent.score` is populated on every component this
function returns, which is precisely the field CNN-sourced components leave ``None``.

**The method.** This function's signature receives one current :class:`FearGreedComponent` reading
per key -- not a time series -- so it cannot literally recompute a live rolling z-score the way "z-score
over a trailing window" usually implies; there is no window in the call. What it does instead is
z-score each raw value against **fixed calibration constants** (mean, population standard deviation)
baked into :data:`_CALIBRATION`. Those constants were computed once from a representative ~40-trading
-day sample of CNN's own historical component series (``tests/fixtures/macro/cnn_fear_greed.json`` --
see the docstring on :mod:`app.market.providers.cnn` for where that fixture came from). The "lookback"
for this composite is therefore that ~40-day sample, frozen at the time these constants were written,
not a window recomputed on every call.

The z-score is mapped onto 0-100 through a bounded ``tanh`` curve (``50 + 50 * tanh(z / 2)``) so that
a component sitting at its calibration mean scores 50 (neutral) and increasingly extreme readings
approach 0 or 100 without ever reaching or exceeding them -- a component in an unprecedented state
still produces a number the rest of the pipeline can render, rather than an unbounded z-score.

**Orientation -- the most likely place to introduce a serious bug.** Every component is oriented so
that *higher score = greedier*, but "higher raw value" means the opposite thing for different
components:

* ``market_momentum_sp500`` (S&P 500 level), ``stock_price_strength`` (breadth of stocks at 52-week
  highs vs lows), ``stock_price_breadth`` (volume in advancing vs declining stocks) and
  ``safe_haven_demand`` (20-day stock return minus 20-day Treasury return) all move *with* greed: a
  higher raw value is a greedier market. These are scored directly.
* ``put_call_options`` (the put/call ratio) and ``market_volatility_vix`` (the VIX level) move
  *against* greed: more hedging and a higher VIX are both fear, not greed. ``junk_bond_demand`` (the
  yield spread between junk and investment-grade bonds) also moves against greed: investors demanding
  a wider risk premium is fear, a narrowing spread is greed. These three are scored with the z-score
  sign flipped before the ``tanh`` mapping -- see :data:`_CALIBRATION`'s ``inverted`` flag. Getting
  this backwards for the VIX is the headline failure mode this module is built to avoid: a VIX spike
  must lower the composite, not raise it, and every component has a dedicated orientation test for
  exactly this reason.

**Known divergence from CNN, beyond the obvious "different formula".** ``market_momentum_sp500``'s
calibration mean is an *absolute S&P 500 index level* captured at one point in time. Unlike a ratio,
a spread, or a percentage, an index level is not stationary -- it trends upward over years -- so this
calibration constant will drift stale as the market moves away from the level it was captured at, and
the momentum component will read as steadily more "extreme" in whichever direction the index has
drifted, independent of actual sentiment. This is a known, accepted limitation of scoring from a
single snapshot rather than a real trailing window; recalibrating :data:`_CALIBRATION` periodically is
the mitigation, not a code fix.

**Missing or unusable components.** A component with no entry in the input, or with
``raw_value is None``, is treated as *absent*, not as an extreme reading -- silently substituting 0
for a missing component would read as extreme fear, which is a fabricated signal, not a conservative
default. The final score instead averages only the components that produced a score, which is
mathematically the same as giving each present component equal weight and renormalising the missing
components' weight across the rest. Each absence is recorded as a :class:`~app.market.models.
MarketWarning` naming the missing component so the caller can say why the number should be trusted
less, rather than silently serving a 4-of-7 composite as if it were a 7-of-7 one. If *no* component
produces a usable score, the composite falls all the way back to a neutral 50 with a warning, since
"unknown" and "extreme fear" are different claims and only one of them is true here.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from typing import Final, NamedTuple

from app.market.macro_models import FearGreed, FearGreedComponent, FearGreedSource, rating_for
from app.market.models import MarketWarning

__all__ = ["composite_fear_greed"]


class _Calibration(NamedTuple):
    label: str
    mean: float
    stdev: float
    inverted: bool
    """``True`` when a *higher* raw value means *more fear* -- the z-score's sign is flipped before
    scoring so that, for every component, a higher final score always means greedier."""


#: Mean and population standard deviation of each component's raw value, computed once from the ~40
#: trading days of history in ``tests/fixtures/macro/cnn_fear_greed.json``. See the module docstring
#: for why these are fixed constants rather than a live trailing window, and for the specific
#: staleness risk on ``market_momentum_sp500``.
_CALIBRATION: Final[dict[str, _Calibration]] = {
    "market_momentum_sp500": _Calibration("Market Momentum", 7507.93, 115.67, inverted=False),
    "stock_price_strength": _Calibration("Stock Price Strength", 1.663, 0.364, inverted=False),
    "stock_price_breadth": _Calibration("Stock Price Breadth", 903.71, 42.98, inverted=False),
    "put_call_options": _Calibration("Put and Call Options", 0.7716, 0.0472, inverted=True),
    "market_volatility_vix": _Calibration("Market Volatility", 17.067, 1.3583, inverted=True),
    "junk_bond_demand": _Calibration("Junk Bond Demand", 1.3123, 0.0466, inverted=True),
    "safe_haven_demand": _Calibration("Safe Haven Demand", 0.8364, 2.1563, inverted=False),
}

#: Canonical iteration order -- matches the order components appear on CNN's own dashboard, and gives
#: every output a stable, predictable component ordering regardless of input order.
_KEYS: Final[tuple[str, ...]] = tuple(_CALIBRATION)

#: Every component carries equal weight. CNN does not publish its real weights, and equal weight is
#: the least presumptuous default in their absence -- it also renormalises trivially: dropping one
#: component from an equal-weight average is just an average over what remains, with no separate
#: bookkeeping needed to redistribute its share.
_EQUAL_WEIGHT: Final[float] = 1.0 / len(_KEYS)


def _component_score(raw_value: float, calibration: _Calibration) -> float:
    """Map one raw value onto a bounded, oriented 0-100 score. See the module docstring's
    "The method" and "Orientation" sections for the reasoning."""
    z = (raw_value - calibration.mean) / calibration.stdev if calibration.stdev > 0 else 0.0
    if calibration.inverted:
        z = -z
    score = 50.0 + 50.0 * math.tanh(z / 2.0)
    return min(100.0, max(0.0, score))


def composite_fear_greed(
    components: Sequence[FearGreedComponent], *, as_of: dt.date
) -> FearGreed:
    """Score a set of raw component readings into a local Fear & Greed index.

    ``components`` need not cover all seven keys, and a covered key need not have a usable
    ``raw_value`` -- both are treated as "component unavailable" and degrade gracefully rather than
    failing the whole composite. See the module docstring for the scoring method, the per-component
    orientation, and how missing components are handled.
    """
    # Later entries win on a repeated key, so a caller may pass a fresher reading for the same
    # component later in the sequence without needing to pre-filter its input.
    by_key: dict[str, FearGreedComponent] = {}
    for component in components:
        if component.key in _CALIBRATION:
            by_key[component.key] = component

    warnings: list[MarketWarning] = []
    out_components: list[FearGreedComponent] = []
    score_total = 0.0
    weight_total = 0.0

    for key in _KEYS:
        calibration = _CALIBRATION[key]
        # Named `reading` rather than reusing `component` from the loop above: that one is bound as
        # a plain `FearGreedComponent`, so rebinding it to an optional here reads as a type error.
        reading = by_key.get(key)
        raw_value = reading.raw_value if reading is not None else None

        # Written as a direct `is None` / `isfinite` test rather than via a `usable` boolean so the
        # `float | None` actually narrows for the `_component_score` call below -- a type checker
        # cannot see that a separate bool implies the value is not None.
        if raw_value is None or not math.isfinite(raw_value):
            warnings.append(
                MarketWarning(
                    kind="missing_component",
                    message=f"composite fear & greed: no usable data for {key!r} "
                    f"({calibration.label}); its weight was redistributed across the remaining "
                    "components",
                )
            )
            unit, description = FearGreedComponent.units_for(key)
            out_components.append(
                FearGreedComponent(
                    key=key,
                    label=calibration.label,
                    raw_value=None,
                    score=None,
                    rating=None,
                    as_of=reading.as_of if reading is not None else None,
                    raw_unit=unit,
                    raw_description=description,
                )
            )
            continue

        score = _component_score(raw_value, calibration)
        unit, description = FearGreedComponent.units_for(key)
        out_components.append(
            FearGreedComponent(
                key=key,
                label=calibration.label,
                raw_value=raw_value,
                score=score,
                rating=rating_for(score),
                as_of=reading.as_of if reading is not None else None,
                raw_unit=unit,
                raw_description=description,
            )
        )
        score_total += score * _EQUAL_WEIGHT
        weight_total += _EQUAL_WEIGHT

    if weight_total > 0.0:
        final_score = score_total / weight_total
    else:
        # Every component was unavailable. Defaulting to 0 would read as extreme fear -- a fabricated
        # signal -- so this falls back to neutral instead, with a warning loud enough to explain why
        # the number is not to be trusted as a real reading.
        final_score = 50.0
        warnings.append(
            MarketWarning(
                kind="missing_component",
                message="composite fear & greed: no components had usable data; the score defaults "
                "to neutral (50) and should not be treated as a real reading",
            )
        )

    final_score = min(100.0, max(0.0, final_score))

    return FearGreed(
        score=final_score,
        rating=rating_for(final_score),
        source=FearGreedSource.COMPOSITE,
        as_of=as_of,
        components=out_components,
        warnings=warnings,
    )
