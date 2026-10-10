"""Select competition windows by *measured* redundancy, not by regime label.

Round 2 added `chop-2011` and `chop-2015` because they looked like a distinct "sideways" regime --
two windows where SPY moved constantly but returned within 0.05% over 260 sessions each. That cost
520 sessions of compute, the round's most expensive addition. Measured afterwards by how the field of
cards actually *ranked* within them, they turned out to be largely redundant with windows already in
the matrix: `chop-2011` resembles `bear-2022` (Spearman rho 0.73 on `adjusted_excess`) more than it
resembles its own sibling `chop-2015` (rho 0.46). A window's label -- "sideways", "crash", "bull" --
does not predict what it measures. Only the field's behaviour in it does. See
`strategy-program/WINDOWS.md` and `data/rounds/r2-2026-08/REPORT.md` section 3.

This module has two capabilities, and they are epistemically very different.

**(1) Measure redundancy among windows that have already been run** (`--results`). This is the
*expensive, ground-truth* measurement: build the card x window matrix of
`strategy_program.tools.score.adjusted_excess`, then compute the Spearman rank correlation between
every pair of windows over the cards common to both. Two windows that rank the field the same way are
redundant regardless of what their SPY return, volatility, or regime label say about them -- the whole
point of a window is to separate strategies, and a window that reorders the field identically to one
already in the matrix is not doing that job, whatever it is called.

Windows do not share a card set: only 15 of 27 cards in round 2's actual results could run
`chop-2011` (its universe or history disqualified the rest under `strategy_program.tools.windows`'s
eligibility gate) against 23 for `chop-2015`. Every correlation is computed over the *intersection* of
cards that ran both windows, its `n` is always reported alongside it, and a pair is refused --
reported as `n/a`, not silently computed on a handful of cards -- below `MIN_SHARED_CARDS` (see that
constant's docstring for why 5).

Spearman's rho is computed here with `statistics.pstdev`/`statistics.fmean` over rank-transformed
values, not `scipy.stats.spearmanr` -- this program does not want a new dependency for one formula.
**Ties are handled with the standard mid-rank convention**: values tied for a spot share the average
of the ranks that span, e.g. two values tied for best occupy ranks 1 and 2 and are both recorded as
1.5. This matters here specifically because `adjusted_excess` can plausibly tie (two cards with
identical exposure and return in a short window), and the naive "assign ranks in encounter order"
shortcut would silently overstate or understate the correlation depending on which value happened to
sort first. See `_rank`.

`suggest_drop_set` then asks: given a redundancy threshold, what is the smallest set of windows to
remove so that no remaining pair exceeds it? **This is a greedy heuristic, not an exact solution** --
the underlying problem (minimum vertex cover on the "exceeds threshold" graph) is NP-hard in general,
and with only eight main windows an exact search would be cheap, but the greedy repeated-highest-degree
removal used here is the standard 2-approximation and is simple enough to audit by eye against the
printed correlation matrix. It is not guaranteed optimal; see `suggest_drop_set`'s docstring for the
tie-breaking rule.

**(2) Score candidate windows before spending compute on them** (`--candidates`). The honest
limitation, stated once here and not softened anywhere else in this module: **true redundancy can
only be measured after running the field, and running the field is the cost this capability exists to
avoid.** So this is a *proxy*, built from SPY alone (no backtest, no card, no compute beyond a single
read-only DuckDB scan), and it is labelled a proxy everywhere it appears in this module's output.

The proxy signature per window is five SPY-only numbers: total return (first session's open to last
session's close, matching the benchmark convention `strategy-program/WINDOWS.md` documents for every
card), annualised volatility, max drawdown, the fraction of sessions closing above the 200-session
moving average, and the path-efficiency ratio `abs(total_return) / sum(abs(daily_return))` -- a number
near 1 for a window that moves in a straight line and near 0 for a window that moves constantly but
arrives nowhere (`chop-2011` and `chop-2015` both measure near 0.0002 here, which is exactly the
"moves constantly, goes nowhere" property they were hand-picked for). Each dimension is standardised
(z-scored across the comparison set) before any distance is computed, because the five dimensions live
on wildly different scales -- annualised volatility ranges roughly 13-52%, path efficiency ranges
roughly 0.0002-0.31 -- and an unstandardised Euclidean distance would just measure "which dimension has
the largest raw units," not genuine dissimilarity.

**The single most valuable output of this module** is the comparison this capability makes even
without any `--candidates` at all: for each of the eight existing windows, does its nearest neighbour
*by SPY signature* match its nearest neighbour *by measured Spearman correlation* from capability (1)?
If the cheap proxy's answer usually agrees with the expensive ground truth, the proxy is worth trusting
for candidate screening. If it does not, this module says so plainly rather than presenting the proxy
as if it worked -- doing otherwise would repeat exactly the mistake that produced the chop windows:
trusting what a window's shape suggests about it over what the field's behaviour in it actually shows.

Read-only DuckDB access is mandatory (`strategy-program/WINDOWS.md`, "Data access rule"): the store's
default connection takes a write lock, and this module may run alongside other agents' concurrent
research reads or an in-progress round. Every connection this module opens uses
``duck.connect(settings.analytics_path, read_only=True)``. The date column is `ts` (a UTC timestamp),
never `date`.

Usage::

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/window_redundancy.py \\
        --results data/rounds/r2-2026-08/results

    # also score candidate windows against the existing matrix, given a JSON file shaped
    # {"tag": ["YYYY-MM-DD", "YYYY-MM-DD"], ...} (see `load_candidates`):
    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/window_redundancy.py \\
        --results data/rounds/r2-2026-08/results \\
        --candidates .scratch/window-redundancy/candidates.json

Run as a plain script, not ``-m`` -- ``strategy-program`` is not a legal Python package name (the
hyphen), so it can only be invoked by file path, with `backend` and the repo root already on
``PYTHONPATH`` for the `app.*` imports this module makes. This module also imports its siblings
`score.py` and `windows.py` directly (as a script run by path puts this file's own directory first on
``sys.path``) rather than re-deriving `adjusted_excess`, `load_results`, and the window matrix's
dates independently -- correctness here depends on matching `score.py`'s exact metric (including its
`AgentResult.total_return`/`exposure` corrections, `strategy-program/DEFECTS.md` D1/D2) and
`windows.py`'s exact dates, and reimplementing either by hand risks drifting from the source of truth
silently. Only `score.py`'s and `windows.py`'s public, `__all__`-exported names are used; this module
does not reach into either one's private (underscore-prefixed) helpers.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import get_settings
from app.db import duck

# `score.py` and `windows.py` live beside this file under the hyphenated `strategy-program/tools/`
# directory, which is not an importable package path -- see this module's own docstring and
# `score.py`'s docstring for why the two siblings duplicate a few constants rather than importing
# across that boundary. This module instead imports both directly, which only works because it must
# be invoked the same way they are (by file path, not `-m`): the interpreter puts a script's own
# directory first on `sys.path`, so `score` and `windows` resolve as ordinary top-level modules. The
# explicit insert below makes that dependency work regardless of the exact invocation, rather than
# relying on the implicit behaviour alone.
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import score  # noqa: E402
import windows  # noqa: E402

if TYPE_CHECKING:
    import pandas as pd

    from app.config import Settings

__all__ = [
    "DEFAULT_DROP_THRESHOLD",
    "MIN_SHARED_CARDS",
    "TRADING_DAYS_PER_YEAR",
    "WindowPairCorrelation",
    "WindowSignature",
    "adjusted_excess_matrix",
    "euclidean_distance",
    "max_correlation_per_window",
    "nearest_by_correlation",
    "nearest_by_signature",
    "pairwise_correlations",
    "spearman_rho",
    "spy_signature",
    "standardize_signatures",
    "suggest_drop_set",
]

#: Below this many cards common to a pair of windows, this module refuses to report a Spearman
#: correlation for that pair at all (reported as `n/a`, not a number computed on too few points).
#:
#: Chosen to match `strategy_program.tools.windows.MIN_ELIGIBLE_MAIN_WINDOWS` /
#: `strategy_program.tools.score.MIN_RANKED_MAIN_WINDOWS`, both 5 -- the same ~60% proportion the rest
#: of this program already uses as its floor for "enough of a sample to say something comparable."
#: There is a second, independent reason it belongs here specifically: with fewer than 5 points, a
#: single card's tie-break or a single rank swap moves Spearman's rho by 0.2-0.4, which is larger than
#: the gaps this module is trying to distinguish (0.46 vs 0.73 in round 2's own chop-window finding).
#: A correlation computed on 3 or 4 shared cards is not a measurement precise enough to base a drop
#: decision on, and reporting it as if it were would be the same error the chop windows themselves
#: were added to correct -- trusting a number that looks meaningful over one that actually is.
MIN_SHARED_CARDS = 5

#: Default `--threshold` for `suggest_drop_set`. Round 2's own worst offender (`chop-2011` vs
#: `bear-2022`, rho 0.73) clears this; a pair above 0.7 orders a field of ranked cards almost
#: identically, which is the operational definition of "redundant" this module uses -- not that the
#: two windows are literally the same regime, but that keeping both buys almost no additional
#: information about how the field is ordered, for the same per-window compute cost.
DEFAULT_DROP_THRESHOLD = 0.7

#: US-market trading-day convention, matching `strategy_program.tools.windows._TRADING_DAYS_PER_YEAR`.
TRADING_DAYS_PER_YEAR = 252

#: Sessions of trailing history the 200-day moving average needs before a signature's
#: "fraction of sessions above the 200dma" dimension is considered measurable.
_MA_LOOKBACK = 200


# ---------------------------------------------------------------------------
# (1) Measured redundancy from already-run results
# ---------------------------------------------------------------------------


def _discover_window_tags(results_root: Path) -> list[str]:
    """Every subdirectory of ``results_root`` with a ``runs/`` folder, in `windows.MAIN_WINDOWS`'
    canonical order (then any others alphabetically) -- mirrors `score._discover_window_tags`'
    behaviour without reaching into that private helper.
    """
    if not results_root.is_dir():
        return []
    found = {p.name for p in results_root.iterdir() if p.is_dir() and (p / "runs").is_dir()}
    ordered = [tag for tag in windows.MAIN_WINDOWS if tag in found]
    ordered += sorted(found - set(windows.MAIN_WINDOWS))
    return ordered


def _detect_round_tag(results_root: Path, tags: list[str]) -> str:
    """The single round prefix shared by every run filename under ``results_root`` (e.g. ``"r1"`` for
    ``r1-c01-meanrev.json``), mirroring `score._discover_round_tag` without reaching into it. Exits
    with a clear message rather than guessing when zero or more than one prefix is found.
    """
    prefixes: set[str] = set()
    for tag in tags:
        runs_dir = results_root / tag / "runs"
        if runs_dir.is_dir():
            for path in runs_dir.glob("*.json"):
                prefixes.add(path.stem.split("-", 1)[0])
    if len(prefixes) != 1:
        raise SystemExit(
            f"could not auto-detect a single round tag under {results_root} "
            f"(found {sorted(prefixes)}); pass --round explicitly"
        )
    return prefixes.pop()


def adjusted_excess_matrix(
    results_root: Path, *, round_tag: str | None = None
) -> tuple[dict[str, dict[str, float]], list[str], str]:
    """The card x window matrix of `score.adjusted_excess`, as ``{agent_id: {window_tag: value}}``.

    Restricted to `windows.MAIN_WINDOWS` (the eight ranked round-2 regimes; the `13f-legal`
    special-case window is excluded, same as `score.py`'s own `MAIN_WINDOW_TAGS`) intersected with
    whatever window directories actually exist under ``results_root``. A cell is omitted -- not
    zero-filled -- whenever the card was not run in that window, or was run but
    `score.adjusted_excess` returned `None` (unknown exposure or benchmark return); every downstream
    correlation is computed only over cards present in both windows being compared, never over an
    invented value.

    Returns ``(matrix, tags, round_tag)`` -- ``tags`` is the window tags actually used (main windows
    found on disk, in canonical order) and ``round_tag`` is the one detected or passed in, so callers
    printing a report can state exactly what was measured.
    """
    tags = [t for t in _discover_window_tags(results_root) if t in windows.MAIN_WINDOWS]
    if not tags:
        raise SystemExit(f"no main-window runs/ directories found under {results_root}")
    resolved_round_tag = round_tag or _detect_round_tag(results_root, tags)

    by_window = score.load_results(results_root, resolved_round_tag, tags)

    matrix: dict[str, dict[str, float]] = {}
    for tag, agents in by_window.items():
        for agent_id, result in agents.items():
            value = score.adjusted_excess(result)
            if value is None:
                continue
            matrix.setdefault(agent_id, {})[tag] = float(value)
    return matrix, tags, resolved_round_tag


def _rank(values: list[float]) -> list[float]:
    """1-indexed ranks of ``values``, ascending, ties sharing the average rank they span.

    E.g. ``[10, 20, 20, 30]`` ranks as ``[1, 2.5, 2.5, 4]`` -- the two values tied for 2nd/3rd place
    both get 2.5 rather than one arbitrarily beating the other. This is the standard mid-rank
    convention Spearman's rho is defined against; skipping it (assigning ranks in encounter order)
    silently biases rho whenever a tie exists, which `adjusted_excess` can plausibly produce.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    n = len(order)
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + 1 + j + 1) / 2
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def spearman_rho(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rank correlation between ``xs`` and ``ys`` (same length, paired by index).

    Computed as the Pearson correlation of the rank-transformed series (`_rank`, average-rank ties) --
    exactly equivalent to the textbook Spearman formula once ties are present, and simpler to get right
    than the ``1 - 6*sum(d**2)/(n*(n**2-1))`` shortcut, which requires a separate tie-correction term
    that formula does not include. Pure `statistics` -- no new dependency for one correlation.

    `None` when either series has zero variance (every rank identical, e.g. all cards tied), since
    correlation is undefined there, not zero.
    """
    n = len(xs)
    if n == 0 or len(ys) != n:
        raise ValueError(f"xs and ys must be the same nonzero length, got {len(xs)} and {len(ys)}")
    rx = _rank(xs)
    ry = _rank(ys)
    sx = statistics.pstdev(rx)
    sy = statistics.pstdev(ry)
    if sx == 0 or sy == 0:
        return None
    mean_x = statistics.fmean(rx)
    mean_y = statistics.fmean(ry)
    covariance = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry, strict=True)) / n
    return covariance / (sx * sy)


@dataclass(frozen=True, slots=True)
class WindowPairCorrelation:
    """One (window, window) pair's measured redundancy.

    ``rho`` and ``n`` are always both present when ``rho`` is not `None`. ``rho`` is `None` either
    because ``n < MIN_SHARED_CARDS`` (see ``insufficient``) or because one of the two card sets had
    zero rank variance -- ``note`` explains which.
    """

    window_a: str
    window_b: str
    n: int
    rho: float | None
    insufficient: bool
    note: str = ""


def pairwise_correlations(
    matrix: dict[str, dict[str, float]],
    tags: list[str],
    *,
    min_shared_cards: int = MIN_SHARED_CARDS,
) -> list[WindowPairCorrelation]:
    """Every unordered pair of ``tags``, correlated over the cards common to both.

    Cards are drawn from ``matrix`` (`adjusted_excess_matrix`'s output); a pair with fewer than
    ``min_shared_cards`` common cards gets ``rho=None, insufficient=True`` rather than a number -- see
    `MIN_SHARED_CARDS`.
    """
    out: list[WindowPairCorrelation] = []
    for i, a in enumerate(tags):
        for b in tags[i + 1 :]:
            common = sorted(
                card for card, cells in matrix.items() if a in cells and b in cells
            )
            n = len(common)
            if n < min_shared_cards:
                out.append(
                    WindowPairCorrelation(
                        window_a=a,
                        window_b=b,
                        n=n,
                        rho=None,
                        insufficient=True,
                        note=f"only {n} shared card(s), below MIN_SHARED_CARDS={min_shared_cards}",
                    )
                )
                continue
            xs = [matrix[c][a] for c in common]
            ys = [matrix[c][b] for c in common]
            rho = spearman_rho(xs, ys)
            note = "" if rho is not None else "zero rank variance in one window's shared cards"
            out.append(
                WindowPairCorrelation(
                    window_a=a, window_b=b, n=n, rho=rho, insufficient=rho is None, note=note
                )
            )
    return out


def max_correlation_per_window(pairs: list[WindowPairCorrelation]) -> dict[str, tuple[str, float, int]]:
    """For every window that appears in at least one measurable pair, its **maximum** correlation
    against any other window -- the number that answers "is this window nearly a duplicate of
    another one?" Returns ``{tag: (most_similar_tag, rho, n)}``; a window with no measurable pair at
    all (every pairing fell below `MIN_SHARED_CARDS`) is simply absent from the result.
    """
    best: dict[str, tuple[str, float, int]] = {}
    for p in pairs:
        if p.rho is None:
            continue
        for this_tag, other_tag in ((p.window_a, p.window_b), (p.window_b, p.window_a)):
            current = best.get(this_tag)
            if current is None or p.rho > current[1]:
                best[this_tag] = (other_tag, p.rho, p.n)
    return best


def suggest_drop_set(
    pairs: list[WindowPairCorrelation], tags: list[str], threshold: float
) -> list[str]:
    """Greedy heuristic: the windows to drop so that no remaining pair's measured rho exceeds
    ``threshold``.

    **This is a greedy 2-approximation to minimum vertex cover, not an exact solution.** Build a graph
    where an edge joins two windows whose measured rho exceeds ``threshold``; repeatedly remove the
    remaining vertex touching the most remaining edges (ties broken first by the sum of that vertex's
    remaining rho values, descending -- prefer dropping whichever window is most entangled overall, not
    just tied on edge count -- then alphabetically, for a fully deterministic result) until no edges
    remain. Pairs below `MIN_SHARED_CARDS` (``rho is None``) never contribute an edge: an unmeasured
    pair is not evidence of redundancy, and treating it as low correlation would be a guess this module
    explicitly refuses to make.

    Order of removal is not unique in general -- a different tie-break could produce a different
    (same-size, in most cases) valid set. This function returns one defensible answer, not *the*
    optimal one; verify against the printed correlation matrix before acting on it.
    """
    edges: dict[str, dict[str, float]] = {t: {} for t in tags}
    for p in pairs:
        if p.rho is not None and p.rho > threshold:
            edges[p.window_a][p.window_b] = p.rho
            edges[p.window_b][p.window_a] = p.rho

    remaining = set(tags)
    dropped: list[str] = []
    while True:
        active = {t: {o: r for o, r in edges[t].items() if o in remaining} for t in remaining}
        if not any(active.values()):
            break
        worst = max(
            remaining,
            key=lambda t: (len(active[t]), sum(active[t].values()), t),
        )
        dropped.append(worst)
        remaining.discard(worst)
    return dropped


# ---------------------------------------------------------------------------
# (2) The SPY-signature proxy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WindowSignature:
    """A window's shape, from SPY alone -- the cheap proxy this module compares against measured
    redundancy. See the module docstring for why each dimension was chosen and why standardisation
    matters before any distance is computed on these.
    """

    tag: str
    start: dt.date
    end: dt.date
    n_sessions: int
    total_return: float
    ann_vol: float
    max_drawdown: float
    frac_above_200dma: float | None
    path_efficiency: float


def _load_spy(settings: Settings) -> pd.DataFrame:
    """Full SPY daily-bar history, sorted by session date, with a trailing 200-session SMA of
    ``close`` attached (`_MA_LOOKBACK`; `NaN` for the first 199 sessions of the whole series, which is
    what makes `spy_signature`'s `frac_above_200dma` `None` for a window too close to the start of
    stored history to have a full lookback -- see that function).

    **Read-only, as `strategy-program/WINDOWS.md` mandates** -- this module runs alongside other
    concurrent research reads and never needs to write to the store.
    """
    with duck.connect(settings.analytics_path, read_only=True) as conn:
        frame = duck.read_bars(conn, settings.bars_dir, "SPY", duck.Interval.DAY)
    if frame.empty:
        raise SystemExit("no SPY bars found in the analytics store -- has it been synced?")
    frame = frame.sort_values("ts").reset_index(drop=True)
    frame["date"] = frame["ts"].dt.date
    frame["sma200"] = frame["close"].rolling(_MA_LOOKBACK, min_periods=_MA_LOOKBACK).mean()
    return frame


def spy_signature(spy: pd.DataFrame, tag: str, start: dt.date, end: dt.date) -> WindowSignature | None:
    """The five-number SPY-only signature for one ``[start, end]`` window (inclusive).

    ``spy`` must already carry a ``date`` column and a trailing ``sma200`` column (`_load_spy`
    produces both). `None` when the window has no stored sessions at all.

    * ``total_return`` -- first session's ``open`` to last session's ``close``, matching
      `strategy-program/WINDOWS.md`'s benchmark convention exactly (verified against the round-2
      matrix's own published SPY figures for all eight windows, to within rounding).
    * ``ann_vol`` -- population stdev of session-over-session `close` returns, annualised by
      ``sqrt(TRADING_DAYS_PER_YEAR)``.
    * ``max_drawdown`` -- most negative ``close / running_peak - 1`` within the window, peak seeded at
      the window's own first close (a window is scored on its own path, not on how far it sits below a
      pre-window high).
    * ``frac_above_200dma`` -- fraction of the window's sessions whose `close` exceeds the trailing
      200-session SMA. `None` -- not 0.0 -- when the window starts before session 200 of the whole
      stored SPY series, since there is then no valid SMA to compare against for any of it.
    * ``path_efficiency`` -- ``abs(total_return) / sum(abs(daily_return))``, in ``[0, 1]``: near 1 for
      a window that moves in a straight line, near 0 for one that moves constantly but arrives back
      near where it started (`chop-2011` and `chop-2015` both measure approximately 0.0002 here).
    """
    mask = (spy["date"] >= start) & (spy["date"] <= end)
    sub = spy.loc[mask]
    if sub.empty:
        return None

    closes = sub["close"].tolist()
    first_open = float(sub["open"].iloc[0])
    last_close = float(closes[-1])
    total_return = last_close / first_open - 1

    daily_returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    ann_vol = (
        statistics.pstdev(daily_returns) * (TRADING_DAYS_PER_YEAR**0.5) if len(daily_returns) > 1 else 0.0
    )

    peak = closes[0]
    max_dd = 0.0
    for c in closes:
        peak = max(peak, c)
        max_dd = min(max_dd, c / peak - 1)

    sma_values = sub["sma200"]
    valid = sma_values.notna()
    frac_above_200dma = (
        float((sub["close"][valid] > sma_values[valid]).mean()) if valid.any() else None
    )

    path_len = sum(abs(r) for r in daily_returns)
    path_efficiency = abs(total_return) / path_len if path_len else 0.0

    return WindowSignature(
        tag=tag,
        start=start,
        end=end,
        n_sessions=len(sub),
        total_return=total_return,
        ann_vol=ann_vol,
        max_drawdown=max_dd,
        frac_above_200dma=frac_above_200dma,
        path_efficiency=path_efficiency,
    )


_SIGNATURE_DIMS: tuple[str, ...] = (
    "total_return",
    "ann_vol",
    "max_drawdown",
    "frac_above_200dma",
    "path_efficiency",
)


def standardize_signatures(sigs: dict[str, WindowSignature]) -> dict[str, dict[str, float]]:
    """Z-score every dimension of ``sigs`` across the whole set given -- existing windows and
    candidates together, so "far" is measured on the same scale for both.

    **Why standardise at all:** the five raw dimensions live on very different scales (annualised
    volatility roughly 0.13-0.52, path efficiency roughly 0.0002-0.31 in round 2's own matrix); an
    unstandardised Euclidean distance would be dominated by whichever dimension happens to have the
    largest raw numbers, which is an artefact of units, not a genuine measure of dissimilarity.

    A window missing `frac_above_200dma` (too close to the start of stored history for a full 200-day
    lookback) is excluded from that one dimension's mean/stdev and gets no z-score for it; a
    zero-variance dimension (every window identical on it) z-scores to 0.0 for everyone, contributing
    nothing to distance rather than dividing by zero.
    """
    out: dict[str, dict[str, float]] = {tag: {} for tag in sigs}
    for dim in _SIGNATURE_DIMS:
        values = {tag: getattr(sig, dim) for tag, sig in sigs.items() if getattr(sig, dim) is not None}
        if not values:
            continue
        mean = statistics.fmean(values.values())
        std = statistics.pstdev(values.values())
        for tag, value in values.items():
            out[tag][dim] = (value - mean) / std if std else 0.0
    return out


def euclidean_distance(a: dict[str, float], b: dict[str, float]) -> float | None:
    """Euclidean distance between two standardised signatures, over the dimensions both have a
    z-score for. `None` if they share no dimension at all (should not happen in practice: only
    `frac_above_200dma` can be missing, and it is missing for both only for two windows both too close
    to the start of stored history).
    """
    shared = set(a) & set(b)
    if not shared:
        return None
    return sum((a[d] - b[d]) ** 2 for d in shared) ** 0.5


def nearest_by_signature(
    standardized: dict[str, dict[str, float]], tags: list[str]
) -> dict[str, tuple[str, float]]:
    """For each of ``tags``, its nearest neighbour among the others by standardised SPY-signature
    Euclidean distance -- the proxy's answer to "which window does this one most resemble?"
    """
    out: dict[str, tuple[str, float]] = {}
    for tag in tags:
        best: tuple[str, float] | None = None
        for other in tags:
            if other == tag:
                continue
            d = euclidean_distance(standardized[tag], standardized[other])
            if d is None:
                continue
            if best is None or d < best[1]:
                best = (other, d)
        if best is not None:
            out[tag] = best
    return out


def nearest_by_correlation(
    pairs: list[WindowPairCorrelation], tags: list[str]
) -> dict[str, tuple[str, float, int]]:
    """For each of ``tags``, its nearest neighbour by *measured* Spearman rho -- the ground truth
    `nearest_by_signature` is checked against. Same computation as `max_correlation_per_window`,
    narrowed to ``tags``; kept as a separate name here because in this module's context it is playing
    the role of "the answer key," not "the headline number."
    """
    best = max_correlation_per_window(pairs)
    return {tag: best[tag] for tag in tags if tag in best}


# ---------------------------------------------------------------------------
# Candidate windows
# ---------------------------------------------------------------------------


def load_candidates(path: Path) -> dict[str, tuple[dt.date, dt.date]]:
    """Parse ``--candidates``: a JSON object ``{tag: ["YYYY-MM-DD", "YYYY-MM-DD"]}`` of proposed
    ``[start, end]`` date ranges to score against the existing matrix before spending any compute on
    them.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object of {{tag: [start_iso, end_iso]}}")
    out: dict[str, tuple[dt.date, dt.date]] = {}
    for tag, bounds in raw.items():
        if not (isinstance(bounds, list) and len(bounds) == 2):
            raise ValueError(f"{path}: candidate {tag!r} must be a 2-element [start, end] list")
        start = dt.date.fromisoformat(bounds[0])
        end = dt.date.fromisoformat(bounds[1])
        out[tag] = (start, end)
    return out


def furthest_candidates(
    standardized: dict[str, dict[str, float]],
    existing_tags: list[str],
    candidate_tags: list[str],
) -> list[tuple[str, float, str]]:
    """Rank ``candidate_tags`` by how "furthest from every existing window" they are.

    Operationalised as the **maximum-minimum** criterion: for each candidate, its distance to its
    *nearest* existing window (the one it would most resemble if added) -- a candidate close to even
    one existing window is not offering new coverage no matter how far it sits from the rest, so the
    minimum is the honest measure of "how novel is this," and candidates are ranked descending on it.

    Returns ``[(candidate_tag, nearest_existing_distance, nearest_existing_tag), ...]``, furthest
    first. A candidate with no computable distance to any existing window (signature unmeasurable) is
    omitted.
    """
    ranked: list[tuple[str, float, str]] = []
    for cand in candidate_tags:
        if cand not in standardized:
            continue
        best: tuple[str, float] | None = None
        for existing in existing_tags:
            d = euclidean_distance(standardized[cand], standardized[existing])
            if d is None:
                continue
            if best is None or d < best[1]:
                best = (existing, d)
        if best is not None:
            ranked.append((cand, best[1], best[0]))
    ranked.sort(key=lambda row: row[1], reverse=True)
    return ranked


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_rho(p: WindowPairCorrelation) -> str:
    if p.rho is None:
        return "n/a"
    return f"{p.rho:+.3f}"


def render_report(
    *,
    matrix: dict[str, dict[str, float]],
    tags: list[str],
    round_tag: str,
    pairs: list[WindowPairCorrelation],
    min_shared_cards: int,
    threshold: float,
    signatures: dict[str, WindowSignature],
    standardized: dict[str, dict[str, float]],
    sig_nn: dict[str, tuple[str, float]],
    corr_nn: dict[str, tuple[str, float, int]],
    candidate_rank: list[tuple[str, float, str]],
    candidate_signatures: dict[str, WindowSignature],
) -> str:
    lines: list[str] = []
    n_cards = len(matrix)
    lines.append(f"round: {round_tag}    windows scored: {len(tags)}    cards with any result: {n_cards}")
    lines.append(f"MIN_SHARED_CARDS={min_shared_cards}    drop-threshold={threshold}")
    lines.append("")

    # --- (1a) full correlation matrix -------------------------------------------------
    lines.append("## (1) Measured redundancy -- Spearman rho of adjusted_excess, pairwise")
    lines.append("")
    width = max(len(t) for t in tags) + 1
    header = " " * width + " ".join(t.rjust(10) for t in tags)
    lines.append(header)
    pair_lookup = {frozenset((p.window_a, p.window_b)): p for p in pairs}
    for a in tags:
        row_cells = []
        for b in tags:
            if a == b:
                row_cells.append("--".rjust(10))
                continue
            p = pair_lookup[frozenset((a, b))]
            row_cells.append(f"{_fmt_rho(p)}(n{p.n})".rjust(10))
        lines.append(a.ljust(width) + " ".join(row_cells))
    lines.append("")

    # --- (1b) most redundant pairs, ranked --------------------------------------------
    lines.append("## Most redundant pairs (ranked by rho, descending; n/a pairs excluded)")
    lines.append("")
    ranked_pairs = sorted((p for p in pairs if p.rho is not None), key=lambda p: p.rho, reverse=True)
    for p in ranked_pairs:
        lines.append(f"  {p.window_a} vs {p.window_b}: rho={p.rho:+.3f}  n={p.n}")
    insufficient = [p for p in pairs if p.insufficient]
    if insufficient:
        lines.append("")
        lines.append(f"  ({len(insufficient)} pair(s) below MIN_SHARED_CARDS or zero-variance, omitted above)")
    lines.append("")

    # --- (1c) reproduction check against the three quoted figures ---------------------
    lines.append("## Reproduction check against data/rounds/r2-2026-08/REPORT.md section 3")
    lines.append("")
    quoted = {
        frozenset(("chop-2011", "bear-2022")): 0.732,
        frozenset(("chop-2015", "covid")): 0.610,
        frozenset(("chop-2011", "chop-2015")): 0.461,
    }
    for key, expected in quoted.items():
        a, b = sorted(key)
        p = pair_lookup.get(key)
        if p is None or p.rho is None:
            lines.append(f"  {a} vs {b}: expected {expected:+.3f} -- COULD NOT REPRODUCE (n/a here)")
            continue
        diff = p.rho - expected
        verdict = "OK" if abs(diff) < 0.02 else "DISCREPANCY"
        lines.append(
            f"  {a} vs {b}: expected {expected:+.3f}, measured {p.rho:+.3f} (n={p.n}), "
            f"diff={diff:+.3f} [{verdict}]"
        )
    lines.append("")

    # --- (1d) max correlation per window ------------------------------------------------
    lines.append("## Each window's maximum correlation against any other window")
    lines.append("")
    best_per_window = max_correlation_per_window(pairs)
    for tag in tags:
        if tag not in best_per_window:
            lines.append(f"  {tag}: no measurable pair (every pairing below MIN_SHARED_CARDS)")
            continue
        other, rho, n = best_per_window[tag]
        lines.append(f"  {tag}: most similar to {other}  rho={rho:+.3f}  n={n}")
    lines.append("")

    # --- (1e) suggested drop set ---------------------------------------------------------
    lines.append(f"## Suggested drop set (greedy heuristic, threshold={threshold})")
    lines.append("")
    drop_set = suggest_drop_set(pairs, tags, threshold)
    if drop_set:
        lines.append(f"  drop: {', '.join(drop_set)}")
    else:
        lines.append("  drop: (none -- no pair exceeds the threshold)")
    lines.append("")

    # --- (2a) SPY signatures for existing windows -----------------------------------------
    lines.append("## (2) SPY-signature PROXY -- not measured redundancy, see module docstring")
    lines.append("")
    lines.append("Existing-window signatures:")
    hdr = f"  {'tag':<12}{'return':>9}{'ann_vol':>9}{'max_dd':>9}{'abv200dma':>11}{'path_eff':>10}"
    lines.append(hdr)
    for tag in tags:
        sig = signatures.get(tag)
        if sig is None:
            continue
        above = "n/a" if sig.frac_above_200dma is None else f"{sig.frac_above_200dma * 100:.1f}%"
        lines.append(
            f"  {tag:<12}{sig.total_return * 100:>8.2f}%{sig.ann_vol * 100:>8.2f}%"
            f"{sig.max_drawdown * 100:>8.2f}%{above:>11}{sig.path_efficiency:>10.4f}"
        )
    lines.append("")

    # --- (2b) proxy vs measured comparison -- the most valuable output --------------------
    lines.append("## Proxy vs measured: does the SPY signature predict the field's actual redundancy?")
    lines.append("")
    agree = 0
    compared = 0
    for tag in tags:
        if tag not in sig_nn or tag not in corr_nn:
            continue
        compared += 1
        sig_partner, sig_dist = sig_nn[tag]
        corr_partner, corr_rho, corr_n = corr_nn[tag]
        match = sig_partner == corr_partner
        agree += int(match)
        flag = "MATCH" if match else "MISMATCH"
        lines.append(
            f"  {tag}: proxy says nearest={sig_partner} (dist={sig_dist:.3f})  |  "
            f"measured says nearest={corr_partner} (rho={corr_rho:+.3f}, n={corr_n})  [{flag}]"
        )
    lines.append("")
    if compared:
        rate = agree / compared
        lines.append(f"agreement: {agree}/{compared} windows ({rate * 100:.0f}%)")
        if rate < 0.5:
            lines.append(
                "VERDICT: the SPY-signature proxy does NOT reliably predict measured redundancy for "
                "this matrix -- most windows' nearest neighbour by signature is a different window "
                "than their nearest neighbour by measured field ranking. Do not use signature distance "
                "alone to decide a candidate window is non-redundant; it can only be used to rule "
                "candidates IN for consideration, never to certify them as safe from redundancy."
            )
        else:
            lines.append(
                "VERDICT: the SPY-signature proxy agrees with measured redundancy on a majority of "
                "windows here, but still disagreed on at least one -- treat it as a screening filter, "
                "not a replacement for measuring redundancy after the field actually runs."
            )
    else:
        lines.append("no windows had both a signature neighbour and a measured neighbour to compare")
    lines.append("")

    # --- (2c) candidates -------------------------------------------------------------------
    if candidate_signatures:
        lines.append("## Candidate windows -- furthest from every existing window (PROXY only)")
        lines.append("")
        for tag in candidate_signatures:
            sig = candidate_signatures[tag]
            above = "n/a" if sig.frac_above_200dma is None else f"{sig.frac_above_200dma * 100:.1f}%"
            lines.append(
                f"  {tag} [{sig.start} .. {sig.end}, n={sig.n_sessions}]: "
                f"return={sig.total_return * 100:+.2f}% vol={sig.ann_vol * 100:.2f}% "
                f"max_dd={sig.max_drawdown * 100:.2f}% abv200dma={above} path_eff={sig.path_efficiency:.4f}"
            )
        lines.append("")
        if candidate_rank:
            lines.append("ranked (furthest first -- max-min distance to nearest existing window):")
            for cand, dist, nearest in candidate_rank:
                lines.append(f"  {cand}: nearest existing window = {nearest}, distance={dist:.3f}")
        else:
            lines.append("(no candidate had a computable distance to any existing window)")
        lines.append("")
    else:
        lines.append("## Candidate windows: none supplied (--candidates)")
        lines.append("")

    return "\n".join(lines) + "\n"


def build_json_report(
    *,
    tags: list[str],
    round_tag: str,
    pairs: list[WindowPairCorrelation],
    signatures: dict[str, WindowSignature],
    sig_nn: dict[str, tuple[str, float]],
    corr_nn: dict[str, tuple[str, float, int]],
    candidate_rank: list[tuple[str, float, str]],
    candidate_signatures: dict[str, WindowSignature],
) -> dict:
    def sig_json(sig: WindowSignature) -> dict:
        return {
            "tag": sig.tag,
            "start": sig.start.isoformat(),
            "end": sig.end.isoformat(),
            "n_sessions": sig.n_sessions,
            "total_return": sig.total_return,
            "ann_vol": sig.ann_vol,
            "max_drawdown": sig.max_drawdown,
            "frac_above_200dma": sig.frac_above_200dma,
            "path_efficiency": sig.path_efficiency,
        }

    return {
        "round": round_tag,
        "window_tags": tags,
        "pairwise_correlations": [
            {
                "window_a": p.window_a,
                "window_b": p.window_b,
                "n": p.n,
                "rho": p.rho,
                "insufficient": p.insufficient,
                "note": p.note,
            }
            for p in pairs
        ],
        "max_correlation_per_window": {
            tag: {"nearest": other, "rho": rho, "n": n}
            for tag, (other, rho, n) in max_correlation_per_window(pairs).items()
        },
        "signatures": {tag: sig_json(sig) for tag, sig in signatures.items()},
        "proxy_vs_measured": {
            tag: {
                "signature_nearest": sig_nn[tag][0],
                "signature_distance": sig_nn[tag][1],
                "measured_nearest": corr_nn[tag][0] if tag in corr_nn else None,
                "measured_rho": corr_nn[tag][1] if tag in corr_nn else None,
                "measured_n": corr_nn[tag][2] if tag in corr_nn else None,
                "agrees": tag in corr_nn and sig_nn[tag][0] == corr_nn[tag][0],
            }
            for tag in sig_nn
        },
        "candidates": {
            "signatures": {tag: sig_json(sig) for tag, sig in candidate_signatures.items()},
            "furthest_ranked": [
                {"tag": cand, "nearest_existing": nearest, "distance": dist}
                for cand, dist, nearest in candidate_rank
            ],
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        dest="results_root",
        type=Path,
        required=True,
        help="results tree, e.g. data/rounds/r2-2026-08/results "
        "(directory containing <window-tag>/runs/<round>-<agent_id>.json)",
    )
    parser.add_argument(
        "--round",
        dest="round_tag",
        default=None,
        help="round prefix on each run filename; auto-detected from the files on disk when omitted",
    )
    parser.add_argument(
        "--min-shared-cards",
        type=int,
        default=MIN_SHARED_CARDS,
        help=f"minimum cards shared by a window pair before its correlation is reported "
        f"(default {MIN_SHARED_CARDS}; see MIN_SHARED_CARDS's docstring)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_DROP_THRESHOLD,
        help=f"redundancy threshold for the suggested drop set (default {DEFAULT_DROP_THRESHOLD})",
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        default=None,
        help="optional JSON {tag: [start_iso, end_iso]} of candidate windows to score against the "
        "existing matrix via the SPY-signature proxy (capability 2)",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="optional path to also write the full machine-readable report",
    )
    args = parser.parse_args(argv)

    matrix, tags, round_tag = adjusted_excess_matrix(args.results_root, round_tag=args.round_tag)
    pairs = pairwise_correlations(matrix, tags, min_shared_cards=args.min_shared_cards)

    settings = get_settings()
    spy = _load_spy(settings)

    signatures: dict[str, WindowSignature] = {}
    for tag in tags:
        start, end, _regime = windows.MAIN_WINDOWS[tag]
        sig = spy_signature(spy, tag, start, end)
        if sig is not None:
            signatures[tag] = sig

    candidate_bounds = load_candidates(args.candidates) if args.candidates is not None else {}
    candidate_signatures: dict[str, WindowSignature] = {}
    for tag, (start, end) in candidate_bounds.items():
        sig = spy_signature(spy, tag, start, end)
        if sig is not None:
            candidate_signatures[tag] = sig
        else:
            print(f"warning: candidate {tag!r} has no stored SPY sessions in [{start}, {end}]")

    all_signatures = {**signatures, **candidate_signatures}
    standardized = standardize_signatures(all_signatures)

    sig_nn = nearest_by_signature(standardized, tags)
    corr_nn = nearest_by_correlation(pairs, tags)
    candidate_rank = furthest_candidates(standardized, tags, list(candidate_signatures))

    report = render_report(
        matrix=matrix,
        tags=tags,
        round_tag=round_tag,
        pairs=pairs,
        min_shared_cards=args.min_shared_cards,
        threshold=args.threshold,
        signatures=signatures,
        standardized=standardized,
        sig_nn=sig_nn,
        corr_nn=corr_nn,
        candidate_rank=candidate_rank,
        candidate_signatures=candidate_signatures,
    )
    print(report)

    if args.json is not None:
        payload = build_json_report(
            tags=tags,
            round_tag=round_tag,
            pairs=pairs,
            signatures=signatures,
            sig_nn=sig_nn,
            corr_nn=corr_nn,
            candidate_rank=candidate_rank,
            candidate_signatures=candidate_signatures,
        )
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
