"""Peak-to-trough-to-recovery decomposition of a price series.

**What an episode is.** The running peak is a record high: the first bar whose price is the
largest seen so far. An episode begins there and ends on the first later bar whose price is back
at or above that peak -- the *recovery* bar. Everything strictly between is one underwater period.
Episodes tile the series without overlapping: the moment one recovers, the recovery bar either
becomes (or already is) the new running peak, and the next episode -- if any -- can only start
after it. This is why the naive approach of reporting "every local decline" is wrong: two dips on
the way down to the same trough are one episode, not two, and reporting them separately
double-counts a single decline in a top-N table.

**Basis.** :attr:`~app.backtest.models.DrawdownBasis.CLOSE` and ``ADJ_CLOSE`` track a single
column for peak, trough and recovery alike. ``INTRADAY`` tracks ``high`` for the running peak and
the recovery test, but ``low`` for the trough -- the deepest excursion a stop could have been hit
at, even though the bar's close never traded there.

**NaN handling.** A missing print must not be allowed to *silently* participate in either extreme:
a gap must not overwrite the peak with a null-derived value, and it must not be picked as a trough
either -- both would misreport a hole in the data as a market move. Bars whose basis column is
``NaN`` are therefore masked out of both the running-peak update and the recovery test; the
underwater/not-underwater state simply carries through them unchanged. For ``INTRADAY`` the peak
(``high``) and trough (``low``) columns are masked independently, since one can be missing while
the other is not.

**Ties.** A bar that merely *matches* the running peak is not a new record -- the peak is the
first bar to reach that value, because that is the bar the drawdown, if any, would be measured
from.

**Same-bar trough and recovery.** ``INTRADAY`` can have a bar whose ``low`` sets the episode's
deepest trough and whose ``high`` also clears the peak (a V-bottom within one bar). The trough
check on a candidate recovery bar therefore runs *before* the episode is closed, so
``bars_to_trough == bars_to_recovery`` on that bar rather than the trough being missed because the
bar "already recovered".
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from app.backtest.models import DrawdownBasis, DrawdownEpisode

__all__ = ["profile"]


def profile(
    bars: pd.DataFrame, *, basis: DrawdownBasis = DrawdownBasis.CLOSE, top: int = 10
) -> tuple[list[DrawdownEpisode], DrawdownEpisode | None, int]:
    """Decompose ``bars`` into non-overlapping underwater episodes.

    Returns ``(episodes, current, episodes_considered)``:

    * ``episodes`` -- every episode found, deepest first (most negative :attr:`DrawdownEpisode.depth`
      first), truncated to ``top``.
    * ``current`` -- the still-underwater episode ending on the last bar, or ``None`` if the series
      closes at its running high. Returned regardless of whether it made the ``top`` cut.
    * ``episodes_considered`` -- the true count before truncation.

    ``bars`` must carry ``ts`` (tz-aware, ascending) plus ``open``, ``high``, ``low``, ``close``,
    ``adj_close``, ``volume``. An empty frame, a single-bar frame and an all-``NaN`` basis column
    all yield ``([], None, 0)`` rather than raising.
    """
    n = len(bars)
    if n == 0 or top < 0:
        return [], None, 0

    peak_col, trough_col = _basis_columns(basis)
    peak_vals = bars[peak_col].to_numpy(dtype=float)
    trough_vals = bars[trough_col].to_numpy(dtype=float)
    dates = bars["ts"].dt.date.to_numpy()

    episodes: list[DrawdownEpisode] = []

    # (value, index) pairs, kept together so mypy never has to trust that two split Optional
    # variables stay in sync -- they are unpacked into plain, narrowed locals as soon as a branch
    # has confirmed the pair is present.
    running_peak: tuple[float, int] | None = None
    ep_peak: tuple[float, int] = (0.0, 0)
    ep_trough: tuple[float, int] | None = None
    underwater = False
    # The most recent observation on the peak column, for the live episode's `depth_now`. Tracked in
    # the same pass rather than read off the last row afterwards, because the last row's basis can
    # be NaN -- and this module's rule is that a gap never silently participates in a figure. Using
    # the last *valid* print, dated honestly, is the same treatment the running peak already gets.
    last_valid: tuple[float, int] | None = None

    for i in range(n):
        p = peak_vals[i]
        t = trough_vals[i]
        p_valid = not math.isnan(p)
        t_valid = not math.isnan(t)
        if p_valid:
            last_valid = (p, i)

        if running_peak is None:
            # No record yet: the first usable bar establishes it. Nothing can be underwater
            # relative to a peak that does not exist yet.
            if p_valid:
                running_peak = (p, i)
            continue

        running_peak_val = running_peak[0]

        if p_valid and p >= running_peak_val:
            # At or above the record: resolves any active episode and may extend the record.
            if underwater:
                # A V-bottom bar: its trough column can still be the episode's deepest point even
                # though its peak column is also the recovery. Check before closing.
                if t_valid and (ep_trough is None or t < ep_trough[0]):
                    ep_trough = (t, i)
                episodes.append(_episode(dates, ep_peak, ep_trough, i, i))
                underwater = False
            if p > running_peak_val:
                # Strictly greater: a new record. A tie leaves the existing (earlier) peak bar in
                # place -- the peak is the first bar to reach a given value, not the latest.
                running_peak = (p, i)
            continue

        # Not a new record: either p is NaN (unknown -- state carries through unchanged) or p is
        # strictly below the running peak (definitely underwater).
        if p_valid and not underwater:
            underwater = True
            ep_peak = running_peak
            ep_trough = None

        if underwater and t_valid and (ep_trough is None or t < ep_trough[0]):
            ep_trough = (t, i)

    all_episodes = list(episodes)
    current: DrawdownEpisode | None = None
    if underwater:
        # `last_valid` is passed only here. A recovered episode has no "current depth" -- it ended,
        # and the bars after it belong to a later episode or to a new record high, so measuring the
        # latest price against *its* peak would answer a question nobody asked.
        current = _episode(dates, ep_peak, ep_trough, None, n - 1, last_valid=last_valid)
        all_episodes.append(current)

    all_episodes.sort(key=lambda e: e.depth)
    return all_episodes[:top], current, len(all_episodes)


def _basis_columns(basis: DrawdownBasis) -> tuple[str, str]:
    """(peak column, trough column) for ``basis``. Equal for the two close-based bases; ``high``
    and ``low`` for ``INTRADAY``, per :class:`~app.backtest.models.DrawdownBasis`."""
    if basis is DrawdownBasis.INTRADAY:
        return "high", "low"
    if basis is DrawdownBasis.ADJ_CLOSE:
        return "adj_close", "adj_close"
    return "close", "close"


def _episode(
    dates: np.ndarray,
    peak: tuple[float, int],
    trough: tuple[float, int] | None,
    recovery_idx: int | None,
    last_idx: int,
    *,
    last_valid: tuple[float, int] | None = None,
) -> DrawdownEpisode:
    """Build one episode from the (value, index) pairs the scan in :func:`profile` accumulated.

    ``trough`` is ``None`` only in the pathological case of an episode whose trough column is
    ``NaN`` for its entire underwater span while its peak column is not (possible only for
    ``INTRADAY``, where the two columns differ) -- there is no observed low to report, so the peak
    bar itself is used as a zero-depth placeholder rather than fabricating one.

    ``last_valid`` is supplied only for the still-open episode and produces
    :attr:`~app.backtest.models.DrawdownEpisode.depth_now`. It is measured on the **peak column**,
    which for ``INTRADAY`` means ``high`` rather than ``low``: that is the column the recovery test
    uses, so "how far below the record am I now" is asked with the same measure that would end the
    episode. Answering it on the trough column would report the worst intraday excursion of the
    latest bar as the current position, which is a different and more alarming claim.
    """
    peak_val, peak_idx = peak
    trough_val, trough_idx = trough if trough is not None else (peak_val, peak_idx)

    depth = trough_val / peak_val - 1.0
    bars_to_trough = trough_idx - peak_idx

    depth_now: float | None = None
    last_value: float | None = None
    last_value_date: dt.date | None = None
    if last_valid is not None:
        last_value, last_value_idx = last_valid
        depth_now = last_value / peak_val - 1.0
        last_value_date = dates[last_value_idx]

    if recovery_idx is not None:
        bars_to_recovery: int | None = recovery_idx - peak_idx
        bars_underwater = recovery_idx - peak_idx
        still_underwater = False
        recovery_date = dates[recovery_idx]
    else:
        bars_to_recovery = None
        bars_underwater = last_idx - peak_idx
        still_underwater = True
        recovery_date = None

    return DrawdownEpisode(
        peak_date=dates[peak_idx],
        peak_value=peak_val,
        trough_date=dates[trough_idx],
        trough_value=trough_val,
        depth=depth,
        bars_to_trough=bars_to_trough,
        recovery_date=recovery_date,
        bars_to_recovery=bars_to_recovery,
        bars_underwater=bars_underwater,
        still_underwater=still_underwater,
        depth_now=depth_now,
        last_value=last_value,
        last_value_date=last_value_date,
    )
