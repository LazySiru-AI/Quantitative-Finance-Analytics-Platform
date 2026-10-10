"""A zero-model-cost historical validation of `app.workflow.regime`'s deterministic classifier and
its static regime -> strategy-card map (`app.workflow.regime.load_regime_map`, `regime_map.json`).

**What this module is not.** `app.workflow.regime`'s own module docstring is explicit that a live
`RegimeCall` is "one label, steering one day's decision", not "a denominator in a statistic" -- and
warns that choosing a regime-cut threshold *after* seeing which choice makes a rule look better is
curve-fitting wearing a methodology's clothes. Nothing here moves, refits, or re-derives any of
`app.workflow.regime`'s thresholds. This module only asks a narrower, already-answerable question:
*given* the classifier and the map exactly as they are pinned today, does re-running them over real
history support the map's own premise -- that each regime's assigned card actually performs
differently in-regime than out-of-regime? A "no" here is a real, expected finding (this programme's
base rate is that edges do not survive; see `docs/reports/regime-backtest.md`), not a defect in this
module, and neither a "yes" nor a "no" here edits `regime_map.json` or `app.workflow.regime`'s
thresholds -- see `docs/WORKFLOW-STUDY-PLAN.md`'s pre-registration and this module's own report for
why that stays a human, out-of-band decision.

**Two pieces, matching the two questions asked of the pinned classifier and the pinned map.**

1. :func:`regime_history` replays `app.workflow.regime.classify` once per historical trading session,
   never touching a network provider (see "What is, and is not, backtestable" below), and returns the
   resulting day-by-day label sequence plus its frequency table and transition matrix.
2. :func:`score_regime_map` takes that history and, for each of the four regime labels' *primary*
   mapped card (index 0 of `regime_map.json`'s ordered list -- the card the live orchestrator is
   documented to try first), runs it once over the same window via the canonical engine,
   `app.tournament.runner.run_card`, and splits the result into an in-regime and an out-of-regime
   comparison. Only the primary card is run per label, and each is run exactly once (never re-run,
   never run in parallel with another): this repo's own backtests are memory-heavy on a 16GB host, and
   this module's own budget is four sequential `run_card` calls over a moderate window, not a sweep
   over the map's fallback candidates too.

**What is, and is not, backtestable, and why that split is honest rather than a shortcut.**
`classify`'s four signals do not all have a history this module can safely replay:

* *SPY trend* and *realized-vol percentile* are genuinely historical: both are computed from
  `app.market.store`'s stored daily bars, sliced to each session's own as-of date exactly as the live
  classifier's own default (`app.workflow.regime._load_spy_bars`) would slice them, so the trend/vol
  signal `regime_history` reports for a given day is the same signal `classify` would have produced
  live on that day, not an approximation of it.
* *The 2s10s spread* has a genuine daily history too (FRED's `T10Y2Y`), but `classify` -- by its own
  module docstring -- never fetches it itself; the live caller supplies it. `regime_history` keeps that
  same contract: it accepts an optional `macro_2s10s_by_date` mapping from the caller (see
  `regime_backtest_report.py`, which fetches `T10Y2Y`'s full published history via
  `app.market.providers.fred.FredProvider` -- a one-time, cacheable, zero-model-cost fetch -- and hands
  the resulting `{date: spread_pct}` mapping in) rather than reaching into `app.market.macro` itself.
  Nothing below makes a network call; a caller that passes nothing simply gets this signal unavailable
  for the whole window, exactly as `classify` already handles a caller who never supplies it.
* *Composite Fear & Greed* has **no** historical backtest path at all, and this module does not
  pretend otherwise. `app.market.macro`'s own module docstring states CNN's endpoint "returns one
  point-in-time reading -- there is no query parameter that asks CNN what did you say on a past date",
  and warns that serving today's live score back for an earlier date "would be exactly the lookahead
  this feature exists to close". `regime_history` therefore always calls `classify` with
  `fear_greed_components=()` -- the same "no data supplied" input `composite_fear_greed` already
  treats as a legitimate case (a neutral 50, an abstention), never a fabricated historical reading.
  Every `RegimeCall` this module produces is missing one of its four signals for exactly this reason;
  `classify`'s own confidence arithmetic already accounts for an unavailable signal by dropping it from
  the denominator, so this degrades every historical call's `confidence` honestly rather than silently.

**How a "daily return series" is built from `run_card`'s output, and the one approximation this
requires.** `app.tournament.runner.run_card` returns an `AgentResult` -- whole-window totals and a
flat list of `RealisedTrade`s -- with no exposed day-by-day equity curve; unlike
`app.workflow.study`, which reconstructs one from a *book*'s daily-marked equity-curve points, there is
nothing here to reconstruct from except the trade list itself. `_split_by_regime` distributes each
trade's own realised `return_pct` **evenly, geometrically, across the trading sessions it was actually
held** (`RealisedTrade.bars_held`, which is genuinely a session count, not a calendar-day count -- see
`app.tournament.runner`'s own `bars_held = fill.session - lot.entry_session_index`): a trade held for
`n` sessions contributes `(1 + return_pct) ** (1/n) - 1` to each of those `n` sessions, weighted by
`StrategyCard.position_pct` -- the same "fraction of *starting* equity per position, summed across
whatever is concurrently open" model `run_card`'s own module docstring describes for how its real
equity curve evolves. This is an approximation of the true path (a trade's real intra-holding P&L is
rarely perfectly smooth), but it is an **unbiased** one for this module's actual purpose: the same
even-distribution rule is applied identically regardless of which regime a session falls in, so it
introduces no systematic tilt toward "in-regime" or "out-of-regime" performance -- the in/out split
this module reports is a comparison of *which sessions* a trade's return lands on, not of the shape
each trade's P&L path took getting there. `docs/reports/regime-backtest.md` states this approximation
plainly next to every number it produces from it.

**Trades are not themselves split by regime.** A single trade can span both in-regime and
out-of-regime sessions, so `app.backtest.metrics.compute`'s `trades` argument -- and therefore its
`win_rate`/`trades` output -- is not meaningful per subset and is passed `()` for both splits;
`RegimeSplitMetrics.in_regime_trade_entries`/`out_of_regime_trade_entries` report the one trade-level
figure that *is* well-defined regardless (how many trades were *opened* on a session carrying that
label), alongside the honestly-empty `trades=0` inside each subset's `StrategyMetrics`.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Final, get_args

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from app.backtest import metrics as metrics_mod
from app.backtest.models import BARS_PER_YEAR, StrategyMetrics
from app.config import Settings
from app.market import store as market_store
from app.market.models import Interval
from app.paper.mandate import default_mandate
from app.paper.marketdata import SessionCalendar
from app.paper.paperbroker import Mandate
from app.tournament.models import AgentResult, RealisedTrade, StrategyCard
from app.tournament.runner import run_card
from app.workflow.regime import RegimeLabel, RegimeMarketData, classify, load_regime_map

__all__ = [
    "RegimeDayCall",
    "RegimeHistoryResult",
    "RegimeMapScoreEntry",
    "RegimeMapScoreResult",
    "RegimeSplitMetrics",
    "regime_history",
    "score_regime_map",
]

#: Every label `RegimeLabel` can take, in the classifier's own canonical order -- read off the type
#: itself (`typing.get_args`) rather than copied as a second literal tuple, so this module cannot drift
#: from `app.workflow.regime._REGIME_LABELS` if that module ever adds a fifth regime.
_ALL_REGIME_LABELS: Final[tuple[RegimeLabel, ...]] = get_args(RegimeLabel)

#: How far back `_nearest_macro_value` will walk from a session date looking for a published 2s10s
#: observation, in calendar days. FRED's `T10Y2Y` is a business-day series with the occasional
#: multi-day gap around a federal holiday cluster; ten days is generous slack for that without risking
#: attributing a session to a spread reading from materially earlier.
_MACRO_LOOKBACK_DAYS: Final[int] = 10

_DAILY_BARS_PER_YEAR: Final[float] = BARS_PER_YEAR[Interval.DAY]


class _Frozen(BaseModel):
    """House style, matching `app.workflow.regime._Frozen` / `app.workflow.study._Frozen`."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# regime_history
# ---------------------------------------------------------------------------


class RegimeDayCall(_Frozen):
    """One historical session's `classify()` result, reduced to what a report needs."""

    date: dt.date
    label: RegimeLabel
    confidence: Decimal
    """`RegimeCall.confidence` for this day -- see `app.workflow.regime.classify`'s docstring. Carried
    through so a reader can tell a firm call from one produced by mostly-unavailable signals."""


class RegimeHistoryResult(_Frozen):
    """Every trading session's regime label over `[start, end]`, plus two summaries of the sequence."""

    start: dt.date
    end: dt.date
    days: tuple[RegimeDayCall, ...]
    """Ascending by date, one entry per trading session -- the same session set
    `app.paper.marketdata.SessionCalendar` would hand `app.tournament.runner.run_card` for an
    identical `(start, end, settings)`, which is what lets `score_regime_map` align a card's trades
    against these labels by date without a second, possibly-divergent calendar."""
    frequencies: dict[RegimeLabel, int]
    """Count of sessions per label, every label present (`0` for one that never fired)."""
    transitions: dict[RegimeLabel, dict[RegimeLabel, int]]
    """`transitions[a][b]` = how many times session `t`'s label was `a` and session `t+1`'s was `b`,
    counted over consecutive *entries in `days`* (i.e. consecutive trading sessions, not consecutive
    calendar dates) -- every `(a, b)` pair present, `0` where it never occurred."""


def _spy_full_frame(*, settings: Settings) -> pd.DataFrame:
    """SPY's whole stored daily history, read once -- every session's `classify()` call below slices
    this same in-memory frame rather than re-reading the store per day, which is what keeps a
    several-hundred-session replay fast without needing `app.paper.marketdata`'s own process-wide
    frame cache (that cache exists for `AsOfMarket`'s use pattern; this module has a simpler one: read
    once, slice many times, inside a single function call)."""
    return market_store.read_frame("SPY", Interval.DAY, settings=settings)


def _slice_through(frame: pd.DataFrame, as_of: dt.date) -> pd.DataFrame:
    """`frame` restricted to `ts <= as_of`, ascending -- the same "everything up to and including
    this date" contract `app.workflow.regime._load_spy_bars` gets from `read_frame(..., end=as_of)`,
    built here as a slice of an already-read frame instead of a fresh store read."""
    bound = pd.Timestamp(as_of, tz="UTC")
    return frame[frame["ts"] <= bound].reset_index(drop=True)


def _nearest_macro_value(by_date: Mapping[dt.date, float], on: dt.date) -> float | None:
    """The most recent `by_date` observation at or before `on`, within `_MACRO_LOOKBACK_DAYS` --
    mirrors the "step back to the nearest *valued* observation" rule `app.market.macro` documents for
    its own horizon changes, over a caller-supplied historical mapping rather than a live-fetched one.
    """
    for offset in range(_MACRO_LOOKBACK_DAYS + 1):
        candidate = on - dt.timedelta(days=offset)
        value = by_date.get(candidate)
        if value is not None:
            return value
    return None


def regime_history(
    start: dt.date,
    end: dt.date,
    *,
    settings: Settings,
    macro_2s10s_by_date: Mapping[dt.date, float] | None = None,
) -> RegimeHistoryResult:
    """Replay `app.workflow.regime.classify` over every trading session in `[start, end]`.

    Deterministic: two calls with the same arguments visit the same sessions (from the same
    `SessionCalendar`), slice the same stored SPY frame the same way, and look up the same
    `macro_2s10s_by_date` entries, so `classify` -- itself pinned deterministic by its own module
    docstring -- returns bit-for-bit identical `RegimeCall`s both times. `fear_greed_components` is
    always `()` here; see the module docstring's "What is, and is not, backtestable" section for why
    that is a documented limitation, not an oversight.

    `macro_2s10s_by_date` defaults to `None`, meaning the macro signal is unavailable for every
    session (a `classify` warning, dropped from the confidence denominator) -- this function never
    fetches it itself, the same "the caller supplies it" contract `classify` already has for this
    exact signal. Raises whatever `SessionCalendar` raises (`UnpricedSymbol`/`ValueError`) if the
    store has no SPY sessions in `[start, end]` at all; a card-scoring caller could not run over that
    window either.
    """
    calendar = SessionCalendar(start=start, end=end, settings=settings)
    spy_full = _spy_full_frame(settings=settings)

    days: list[RegimeDayCall] = []
    label_sequence: list[RegimeLabel] = []
    for session in calendar:
        as_of = session.date
        spy_slice = _slice_through(spy_full, as_of)
        market = RegimeMarketData(
            spy_bars=spy_slice if not spy_slice.empty else None,
            fear_greed_components=(),
            macro_2s10s_pct=(
                _nearest_macro_value(macro_2s10s_by_date, as_of)
                if macro_2s10s_by_date is not None
                else None
            ),
        )
        call = classify(settings=settings, as_of=as_of, market=market)
        days.append(RegimeDayCall(date=as_of, label=call.label, confidence=call.confidence))
        label_sequence.append(call.label)

    frequencies: dict[RegimeLabel, int] = {label: 0 for label in _ALL_REGIME_LABELS}
    frequencies.update(Counter(label_sequence))

    transitions: dict[RegimeLabel, dict[RegimeLabel, int]] = {
        a: {b: 0 for b in _ALL_REGIME_LABELS} for a in _ALL_REGIME_LABELS
    }
    for prev_label, next_label in pairwise(label_sequence):
        transitions[prev_label][next_label] += 1

    return RegimeHistoryResult(
        start=start, end=end, days=tuple(days), frequencies=frequencies, transitions=transitions
    )


# ---------------------------------------------------------------------------
# score_regime_map
# ---------------------------------------------------------------------------


class RegimeSplitMetrics(_Frozen):
    """One card's in-regime vs out-of-regime comparison -- the actual test of the map's premise."""

    label: RegimeLabel
    in_regime_sessions: int
    out_of_regime_sessions: int
    in_regime: StrategyMetrics
    """`app.backtest.metrics.compute` over just the sessions classified `label`, compounded in their
    original order with every other session skipped -- see the module docstring's "daily return
    series" section for how each session's return is derived from `run_card`'s trades. `.trades` is
    always `0` here; see `in_regime_trade_entries` for the meaningful trade-level count."""
    out_of_regime: StrategyMetrics
    """As `in_regime`, over every session classified with a *different* label."""
    in_regime_trade_entries: int
    """Count of this run's `RealisedTrade`s whose `entry_date` fell on a session classified `label`."""
    out_of_regime_trade_entries: int
    """As `in_regime_trade_entries`, for a session classified with a different label."""


class RegimeMapScoreEntry(_Frozen):
    """One regime label's primary mapped card, run once and split -- or the error that stopped it."""

    label: RegimeLabel
    agent_id: str
    """The primary (index-0) `agent_id` from `regime_map.json[label]` -- the only card this module
    runs for `label`; see the module docstring for why the fallback candidates are not also scored."""
    mapped_agent_ids: tuple[str, ...]
    """The full ordered list `regime_map.json` carries for `label`, for context in the report."""
    whole_window_total_return: Decimal | None
    whole_window_sharpe: float | None
    whole_window_trades: int | None
    """These three are `AgentResult`'s own whole-window figures, unmodified -- reported so a reader
    can see the map's card behaved like a normal `run_card` result before looking at the split.
    `None` only alongside a populated `error` (the card could not be run at all)."""
    split: RegimeSplitMetrics | None
    """`None` only alongside a populated `error`."""
    error: str | None
    """`f"{type(exc).__name__}: {exc}"` when loading the card or running it raised -- a guard failure,
    an unpriceable benchmark, a missing library file. Never swallowed silently: a `None` `split` next
    to a populated `error` is how a caller tells "this card was tested and found unremarkable" apart
    from "this card could not be tested"."""


class RegimeMapScoreResult(_Frozen):
    start: dt.date
    end: dt.date
    entries: tuple[RegimeMapScoreEntry, ...]
    """One per `RegimeLabel`, in `app.workflow.regime`'s canonical label order."""


def _find_card_path(agent_id: str, *, settings: Settings) -> Path | None:
    """The on-disk path for `agent_id`, or `None` if no `StrategyCard`-shaped JSON under
    `settings.library_dir` carries it.

    A deliberate, smaller copy of `app.workflow.regime._index_library_by_agent_id`'s search --
    walking every JSON under `library_dir`, skipping whatever does not parse as a `StrategyCard` --
    rather than an import of that private helper: this module was told not to reach through another
    module's underscore-prefixed privacy for a second time (`app.workflow.study`'s own docstring gives
    the identical reasoning for its own copy of `app.workflow.replay._OpenLot`). This one stops at the
    first match rather than indexing the whole library, since every caller here already has a single
    known `agent_id` (from `load_regime_map`, which has already validated it resolves) rather than a
    whole map to look up repeatedly.
    """
    root = settings.library_dir
    if not root.is_dir():
        return None
    for path in sorted(root.rglob("*.json")):
        try:
            card = StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if card.agent_id == agent_id:
            return path
    return None


def _as_date(value: dt.date) -> dt.date:
    """`dt.date` for either a `RealisedTrade.entry_date`/`.exit_date` (`date | datetime`) -- every
    card this module runs trades at `Interval.DAY`, so this is always already a plain `date` in
    practice, but the field's own type allows a `datetime`, and `isinstance` against the narrower
    `date` would wrongly accept a `datetime` too (`datetime` subclasses `date`), so `datetime` is
    checked first."""
    if isinstance(value, dt.datetime):
        return value.date()
    return value


def _distribute_daily_returns(
    result: AgentResult, *, session_dates: Sequence[dt.date]
) -> tuple[list[float], list[bool]]:
    """One (return, is-position-open) pair per entry in `session_dates` -- see the module docstring's
    "daily return series" section for the even-geometric-distribution rule this applies per trade.

    **A still-open position at the window's end has no `exit_date` at all.**
    `app.tournament.runner._open_at_end_trade` sets `RealisedTrade.exit_date=None` for exactly this
    case (it is the paired `MetricsTrade` -- never exposed here -- that carries the mark date instead,
    for `app.backtest.metrics.compute`'s own use inside `run_card`). Treating a `None` `exit_date` as
    "cannot be attributed, skip it" would silently drop every position a card was still holding when
    the window closed -- routinely the *majority* of a card's trades for a short backtest window -- so
    this instead reads `RealisedTrade.bars_held` (which `run_card` already computed as
    `last_session.index - entry_session_index` for exactly this case) and holds the trade through
    `session_dates`' own last entry, the same last-session mark `run_card` used to produce
    `return_pct` in the first place.

    A trade whose `entry_date` does not appear in `session_dates` at all, or whose *closed* `exit_date`
    does not, is skipped rather than raising: `score_regime_map` always builds `session_dates` from the
    identical `(start, end, settings)` triple it runs the card over, so every trade's dates are
    expected to resolve -- this is defence against a future caller breaking that invariant, not a case
    this module's own callers can hit today.
    """
    n = len(session_dates)
    date_to_index = {date: index for index, date in enumerate(session_dates)}
    daily_returns = [0.0] * n
    position_open = [False] * n

    for trade in result.trades:
        entry_index = date_to_index.get(_as_date(trade.entry_date))
        if entry_index is None:
            continue
        if trade.exit_date is not None:
            exit_index = date_to_index.get(_as_date(trade.exit_date))
            if exit_index is None:
                continue
        else:
            exit_index = n - 1  # open_at_end -- see this function's docstring

        held_sessions = exit_index - entry_index
        if held_sessions <= 0:
            # A same-session round trip: attribute the whole return to the one session it happened on.
            held_sessions = 1
            exit_index = min(entry_index + 1, n - 1) if entry_index + 1 < n else entry_index

        per_session_return = (1.0 + float(trade.return_pct)) ** (1.0 / held_sessions) - 1.0
        weight = float(result.card.position_pct)

        for index in range(entry_index, min(exit_index, n - 1) + 1):
            position_open[index] = True
        for index in range(entry_index + 1, min(exit_index, n - 1) + 1):
            daily_returns[index] += weight * per_session_return

    return daily_returns, position_open


def _subset_equity(
    daily_returns: Sequence[float], position_open: Sequence[bool], mask: Sequence[bool]
) -> tuple[np.ndarray, np.ndarray]:
    """`(equity, in_position)` arrays over just the sessions where `mask` is `True`, compounded in
    their original relative order with every other session skipped entirely -- the "what would this
    card's path have looked like across only these sessions" curve `RegimeSplitMetrics.in_regime`/
    `.out_of_regime` are built from. `equity[0] = 1.0` always, matching `app.backtest.metrics.compute`'s
    own contract."""
    sub_returns = [r for r, keep in zip(daily_returns, mask, strict=True) if keep]
    sub_open = [o for o, keep in zip(position_open, mask, strict=True) if keep]

    equity = np.empty(len(sub_returns) + 1, dtype=np.float64)
    equity[0] = 1.0
    for index, r in enumerate(sub_returns):
        equity[index + 1] = equity[index] * (1.0 + r)
    in_position = np.array([False, *sub_open], dtype=np.bool_)
    return equity, in_position


def _split_by_regime(
    result: AgentResult,
    *,
    label: RegimeLabel,
    session_dates: Sequence[dt.date],
    label_by_date: Mapping[dt.date, RegimeLabel],
) -> RegimeSplitMetrics:
    daily_returns, position_open = _distribute_daily_returns(result, session_dates=session_dates)

    in_mask = [label_by_date.get(date) == label for date in session_dates]
    out_mask = [
        label_by_date.get(date) is not None and label_by_date.get(date) != label
        for date in session_dates
    ]

    in_equity, in_position = _subset_equity(daily_returns, position_open, in_mask)
    out_equity, out_position = _subset_equity(daily_returns, position_open, out_mask)

    annualisable = not Interval.DAY.is_intraday
    in_metrics = metrics_mod.compute(
        in_equity,
        in_position=in_position,
        trades=(),
        bars_per_year=_DAILY_BARS_PER_YEAR,
        annualisable=annualisable,
    )
    out_metrics = metrics_mod.compute(
        out_equity,
        in_position=out_position,
        trades=(),
        bars_per_year=_DAILY_BARS_PER_YEAR,
        annualisable=annualisable,
    )

    def _entry_label(trade: RealisedTrade) -> RegimeLabel | None:
        return label_by_date.get(_as_date(trade.entry_date))

    in_entries = sum(1 for trade in result.trades if _entry_label(trade) == label)
    out_entries = sum(
        1 for trade in result.trades if _entry_label(trade) not in (None, label)
    )

    return RegimeSplitMetrics(
        label=label,
        in_regime_sessions=sum(in_mask),
        out_of_regime_sessions=sum(out_mask),
        in_regime=in_metrics,
        out_of_regime=out_metrics,
        in_regime_trade_entries=in_entries,
        out_of_regime_trade_entries=out_entries,
    )


def score_regime_map(
    history: RegimeHistoryResult, *, settings: Settings, mandate: Mandate | None = None
) -> RegimeMapScoreResult:
    """For each `RegimeLabel`'s primary mapped card, run it once over `[history.start, history.end]`
    and split its daily return series by `history`'s day-by-day labels.

    `mandate` defaults to `app.paper.mandate.default_mandate()` -- the same standing mandate
    `app.tournament.jobs` runs every tournament card under. Never runs two cards concurrently (a
    plain `for` loop over `_ALL_REGIME_LABELS`, one `run_card` call at a time) -- see the module
    docstring's host-constraint note. A card that fails to load or to run (a guard failure, a symbol
    with no stored bars over this window) is recorded as an `error` on its own `RegimeMapScoreEntry`
    rather than aborting the other three labels' scoring.
    """
    resolved_mandate = mandate if mandate is not None else default_mandate()
    regime_map = load_regime_map(settings=settings)
    label_by_date: dict[dt.date, RegimeLabel] = {day.date: day.label for day in history.days}
    session_dates = [day.date for day in history.days]

    entries: list[RegimeMapScoreEntry] = []
    for label in _ALL_REGIME_LABELS:
        mapped_ids = regime_map[label]
        primary_id = mapped_ids[0]

        card_path = _find_card_path(primary_id, settings=settings)
        if card_path is None:
            entries.append(
                RegimeMapScoreEntry(
                    label=label,
                    agent_id=primary_id,
                    mapped_agent_ids=mapped_ids,
                    whole_window_total_return=None,
                    whole_window_sharpe=None,
                    whole_window_trades=None,
                    split=None,
                    error=(
                        f"agent_id {primary_id!r} not found under {settings.library_dir} -- "
                        "unexpected, since load_regime_map() already validated this id resolves"
                    ),
                )
            )
            continue

        try:
            card = StrategyCard.model_validate_json(card_path.read_text(encoding="utf-8"))
            result = run_card(
                card,
                settings=settings,
                mandate=resolved_mandate,
                start=history.start,
                end=history.end,
            )
        except Exception as exc:
            # Reported on the entry, never swallowed -- see RegimeMapScoreEntry.error's docstring for
            # why a broad catch is the right shape here.
            entries.append(
                RegimeMapScoreEntry(
                    label=label,
                    agent_id=primary_id,
                    mapped_agent_ids=mapped_ids,
                    whole_window_total_return=None,
                    whole_window_sharpe=None,
                    whole_window_trades=None,
                    split=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        split = _split_by_regime(
            result, label=label, session_dates=session_dates, label_by_date=label_by_date
        )
        entries.append(
            RegimeMapScoreEntry(
                label=label,
                agent_id=primary_id,
                mapped_agent_ids=mapped_ids,
                whole_window_total_return=result.total_return,
                whole_window_sharpe=result.sharpe,
                whole_window_trades=len(result.trades),
                split=split,
                error=None,
            )
        )

    return RegimeMapScoreResult(start=history.start, end=history.end, entries=tuple(entries))
