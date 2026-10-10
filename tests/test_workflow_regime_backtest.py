"""Tests for `app.workflow.regime_backtest`: the zero-model-cost historical replay of
`app.workflow.regime.classify` (:func:`~app.workflow.regime_backtest.regime_history`) and the
in-regime/out-of-regime scoring of `regime_map.json`'s primary cards
(:func:`~app.workflow.regime_backtest.score_regime_map`).

No network calls anywhere in this file, and no dependency on the real (gitignored) `data/store` --
every symbol used below, including `SPY`, is written into the `settings` fixture's temporary
`bars_dir` by `_write_daily_bars`, mirroring `tests/test_tournament_runner.py`'s own convention for
testing `app.tournament.runner.run_card` against synthetic bars. `score_regime_map`'s tests also never
touch the real `regime_map.json` or the real card library: `app.workflow.regime.load_regime_map` and
`app.workflow.regime_backtest._find_card_path` are monkeypatched to a synthetic map and a single
temp-written `StrategyCard`, the same "don't depend on production content drifting" reasoning
`tests/test_workflow_regime.py` gives for monkeypatching `regime_mod._REGIME_MAP_PATH` in its own
malformed-map tests.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from app.config import Settings
from app.db import duck
from app.market.models import BAR_COLUMNS, Interval
from app.paper.paperbroker import Mandate
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from app.tournament.runner import run_card
from app.workflow import regime_backtest as rb

# ---------------------------------------------------------------------------
# Shared fixtures -- adapted from tests/test_tournament_runner.py's own helpers
# ---------------------------------------------------------------------------


def _weekdays(anchor: dt.date, count: int) -> list[dt.date]:
    """`count` weekdays starting at `anchor` (included if itself a weekday)."""
    dates: list[dt.date] = []
    day = anchor
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day += dt.timedelta(days=1)
    return dates


def _write_daily_bars(settings: Settings, symbol: str, dates: list[dt.date], closes: list[float]) -> None:
    """One daily bar per `(date, close)`, `open` equal to `close` and `high`/`low` bracketing it
    generously -- neither `regime_history` nor `run_card`'s bracket checks in these tests depend on
    intrabar values, only on `close`."""
    frame = pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC) for d in dates],
                dtype="datetime64[us, UTC]",
            ),
            "open": closes,
            "high": [c + 5.0 for c in closes],
            "low": [c - 5.0 for c in closes],
            "close": closes,
            "adj_close": closes,
            "volume": [1_000_000] * len(dates),
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)


def _mandate(**overrides: object) -> Mandate:
    """A zero-fee, uncapped-concentration mandate -- fees would make a trade's `return_pct` a function
    of share count and price rather than of the pure price move, which is what these tests need to
    hand-verify the geometric split against. `max_single_name_weight=1.00` (rather than
    `app.paper.mandate.default_mandate`'s real 25% cap) so a single-symbol, `position_pct=1.0` test
    card is not rejected for concentration -- disclosed here explicitly, the same way
    `app.tournament.jobs`/`app.tournament.__main__` disclose their own loosening of that same field."""
    fields: dict[str, object] = {
        "persona_id": "test-agent",
        "display_name": "Test Agent",
        "account_id": "acct-1",
        "account_label": "Test Account",
        "starting_cash": Decimal("10000.00"),
        "allow_fractional_shares": False,
        "max_positions": 1,
        "max_single_name_weight": Decimal("1.00"),
        "min_clip_notional": Decimal("1.00"),
        "min_cash": Decimal("0.00"),
        "settlement_days": 1,
        "slippage_bps": Decimal("0"),
        "commission_per_trade": Decimal("0"),
        "sec_fee_rate": Decimal("0"),
        "taf_per_share": Decimal("0"),
        "taf_cap": Decimal("0"),
    }
    fields.update(overrides)
    return Mandate(**fields)  # type: ignore[arg-type]


def _card(**overrides: object) -> StrategyCard:
    """A single-symbol, always-enters, never-naturally-exits card: `entry="close > 0"` fires on the
    very first session (no indicator warmup to wait out), `max_hold_days` is set far beyond any test
    window so the position never gets a time-stop exit, and with `max_positions=1` on a one-symbol
    universe this produces *exactly one* trade per run -- an `open_at_end` `RealisedTrade` marked at
    the window's last session. That single, predictable trade is what
    `TestScoreRegimeMapSplitting` hand-verifies the regime split against."""
    fields: dict[str, object] = {
        "agent_id": "test-card",
        "display_name": "Test Card",
        "discipline": Discipline.TREND,
        "thesis": "a test thesis, written before the trading window ran",
        "universe": ("TST",),
        "entry": "close > 0",
        "exit": "",
        "max_hold_days": 200,
        "max_positions": 1,
        "position_pct": Decimal("1.0"),
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return StrategyCard(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. regime_history: determinism
# ---------------------------------------------------------------------------


class TestRegimeHistoryDeterminism:
    def test_two_calls_are_identical(self, settings: Settings) -> None:
        """The same `(start, end, settings)` -- and no `macro_2s10s_by_date` -- must replay to a
        bit-for-bit identical `RegimeHistoryResult` both times, matching `classify`'s own documented
        determinism (see `tests/test_workflow_regime.py::test_classify_is_deterministic`)."""
        dates = _weekdays(dt.date(2024, 1, 2), 260)
        closes = [100.0 + 0.1 * i for i in range(len(dates))]
        _write_daily_bars(settings, "SPY", dates, closes)
        start, end = dates[-15], dates[-1]

        first = rb.regime_history(start, end, settings=settings)
        second = rb.regime_history(start, end, settings=settings)

        assert first == second
        assert len(first.days) == 15
        assert sum(first.frequencies.values()) == 15
        # one transition per consecutive pair of the 15 sessions
        assert sum(sum(row.values()) for row in first.transitions.values()) == 14

    def test_deterministic_with_a_supplied_macro_series_too(self, settings: Settings) -> None:
        """The same replay stays deterministic once a `macro_2s10s_by_date` mapping is in play --
        covers the nearest-on-or-before lookup (`_nearest_macro_value`), not just the no-macro path
        the previous test exercises."""
        dates = _weekdays(dt.date(2024, 1, 2), 260)
        closes = [200.0 - 0.1 * i for i in range(len(dates))]  # a clean downtrend
        _write_daily_bars(settings, "SPY", dates, closes)
        start, end = dates[-15], dates[-1]
        macro_by_date = {d: -0.4 + 0.01 * i for i, d in enumerate(dates)}

        first = rb.regime_history(start, end, settings=settings, macro_2s10s_by_date=macro_by_date)
        second = rb.regime_history(start, end, settings=settings, macro_2s10s_by_date=macro_by_date)

        assert first == second
        assert len(first.days) == 15
        # every label present in the frequency table, even ones that never fired
        assert set(first.frequencies) == set(rb._ALL_REGIME_LABELS)


# ---------------------------------------------------------------------------
# 2. score_regime_map: the in-regime / out-of-regime split, against a known regime pattern
# ---------------------------------------------------------------------------


def _compound(trade_return_pct: float, held_sessions: int, weight: float, count: int) -> float:
    """A direct re-derivation of `app.workflow.regime_backtest`'s own documented geometric-
    decomposition rule (module docstring, "How a daily return series is built"): a trade held
    `held_sessions` sessions contributes `(1 + return_pct) ** (1/held_sessions) - 1` to each of them,
    weighted by `position_pct`; compounding `count` of those identical per-session contributions is
    what the module's own equity curve does for a subset of `count` in-regime (or out-of-regime)
    sessions. Written from the docstring's prose, not by calling the module's private
    `_distribute_daily_returns`/`_subset_equity` -- so a test failure here means the module's *output*
    disagrees with what it documents, not merely with its own internals."""
    per_session = (1.0 + trade_return_pct) ** (1.0 / held_sessions) - 1.0
    equity = 1.0
    for _ in range(count):
        equity *= 1.0 + weight * per_session
    return equity - 1.0


class TestScoreRegimeMapSplitting:
    """See `app.workflow.regime_backtest`'s module docstring, "How a daily return series is built",
    for the geometric-decomposition rule under test, and `_compound` above for its direct
    re-derivation -- the formula every assertion below checks the module's own output against.
    """

    def test_split_matches_the_documented_geometric_decomposition(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        n_sessions = 8
        lead_in = 15
        all_dates = _weekdays(dt.date(2024, 3, 4), lead_in + n_sessions)
        window_dates = all_dates[-n_sessions:]
        start, end = window_dates[0], window_dates[-1]

        spy_closes = [100.0 + 0.05 * i for i in range(len(all_dates))]
        _write_daily_bars(settings, "SPY", all_dates, spy_closes)
        tst_closes = [50.0 + 0.5 * i for i in range(len(all_dates))]
        _write_daily_bars(settings, "TST", all_dates, tst_closes)

        # position_pct=0.5 (rather than 1.0) leaves real dollar headroom between the notional a lot
        # is *sized* at (decided off the prior close) and what it might actually cost to *fill* (the
        # next close, which has moved a little) -- at 1.0 those are the same number and the smallest
        # uptick between decision and fill rejects the order for insufficient cash.
        card = _card(position_pct=Decimal("0.5"))
        card_path = tmp_path / "test-card.json"
        card_path.write_text(card.model_dump_json(), encoding="utf-8")

        fake_map = {label: (card.agent_id,) for label in rb._ALL_REGIME_LABELS}
        monkeypatch.setattr(rb, "load_regime_map", lambda *, settings: fake_map)
        monkeypatch.setattr(
            rb,
            "_find_card_path",
            lambda agent_id, *, settings: card_path if agent_id == card.agent_id else None,
        )

        # First 4 window sessions labelled risk_on_trend, last 4 risk_off -- a known, hand-chosen
        # regime pattern that straddles the single trade's holding period (entry on session 0).
        split_index = 4
        days = tuple(
            rb.RegimeDayCall(
                date=d,
                label="risk_on_trend" if i < split_index else "risk_off",
                confidence=Decimal("1.0"),
            )
            for i, d in enumerate(window_dates)
        )
        frequencies = {label: 0 for label in rb._ALL_REGIME_LABELS}
        frequencies["risk_on_trend"] = split_index
        frequencies["risk_off"] = n_sessions - split_index
        transitions = {a: {b: 0 for b in rb._ALL_REGIME_LABELS} for a in rb._ALL_REGIME_LABELS}
        history = rb.RegimeHistoryResult(
            start=start, end=end, days=days, frequencies=frequencies, transitions=transitions
        )

        mandate = _mandate()
        result = rb.score_regime_map(history, settings=settings, mandate=mandate)

        assert result.start == start
        assert result.end == end
        assert len(result.entries) == 4
        assert {e.label for e in result.entries} == set(rb._ALL_REGIME_LABELS)

        # Independently reproduce the one trade run_card actually filled, to hand-check the split
        # against its real return_pct/bars_held rather than an assumed value.
        agent_result = run_card(card, settings=settings, mandate=mandate, start=start, end=end)
        assert len(agent_result.trades) == 1
        trade = agent_result.trades[0]
        assert trade.bars_held == n_sessions - 1  # entry on session 1, marked at the last session

        held_sessions = trade.bars_held
        entry_idx = 0  # entry fires on the window's first session -- see _card's docstring
        held_indices = range(entry_idx + 1, n_sessions)
        count_in = sum(1 for i in held_indices if i < split_index)
        count_out = len(held_indices) - count_in
        weight = float(card.position_pct)
        expected_in_return = _compound(float(trade.return_pct), held_sessions, weight, count_in)
        expected_out_return = _compound(float(trade.return_pct), held_sessions, weight, count_out)

        risk_on_entry = next(e for e in result.entries if e.label == "risk_on_trend")
        assert risk_on_entry.error is None
        assert risk_on_entry.agent_id == card.agent_id
        assert risk_on_entry.whole_window_trades == 1
        assert risk_on_entry.whole_window_total_return == agent_result.total_return
        split = risk_on_entry.split
        assert split is not None
        assert split.in_regime_sessions == split_index
        assert split.out_of_regime_sessions == n_sessions - split_index
        assert split.in_regime.total_return == pytest.approx(expected_in_return, abs=1e-9)
        assert split.out_of_regime.total_return == pytest.approx(expected_out_return, abs=1e-9)
        # `trades` inside each subset's StrategyMetrics is always 0 by construction -- a trade spans
        # both subsets, so it is not attributable to either one at the metrics.compute() level.
        assert split.in_regime.trades == 0
        assert split.out_of_regime.trades == 0
        # ... but trade *entries* are well-defined: the one trade entered on a risk_on_trend session.
        assert split.in_regime_trade_entries == 1
        assert split.out_of_regime_trade_entries == 0

        # The other three labels reuse the identical card and window (same fake_map entry for all
        # four), so they must reproduce the *same* underlying trade -- only which sessions count as
        # "in-regime" differs. risk_off's in-regime split is exactly risk_on_trend's out-of-regime
        # split, since between them the two labels partition every session in the window.
        risk_off_entry = next(e for e in result.entries if e.label == "risk_off")
        assert risk_off_entry.split is not None
        assert risk_off_entry.split.in_regime.total_return == pytest.approx(
            expected_out_return, abs=1e-9
        )
        assert risk_off_entry.split.out_of_regime.total_return == pytest.approx(
            expected_in_return, abs=1e-9
        )
        assert risk_off_entry.split.in_regime_trade_entries == 0
        assert risk_off_entry.split.out_of_regime_trade_entries == 1

        # A label with zero sessions in the window (every session here is risk_on_trend or risk_off)
        # still gets a well-defined, empty split rather than a crash.
        choppy_entry = next(e for e in result.entries if e.label == "choppy_neutral")
        assert choppy_entry.split is not None
        assert choppy_entry.split.in_regime_sessions == 0
        assert choppy_entry.split.in_regime.total_return == pytest.approx(0.0, abs=1e-9)
        assert choppy_entry.split.out_of_regime_sessions == n_sessions

    def test_a_card_that_cannot_be_found_is_reported_as_an_error_not_a_crash(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`score_regime_map` must not raise when one label's mapped `agent_id` cannot be resolved to
        a card on disk -- it records `error` on that label's own entry and still scores the rest."""
        dates = _weekdays(dt.date(2024, 3, 4), 20)
        closes = [100.0 + 0.1 * i for i in range(len(dates))]
        _write_daily_bars(settings, "SPY", dates, closes)
        start, end = dates[-5], dates[-1]

        fake_map = {label: ("missing-card",) for label in rb._ALL_REGIME_LABELS}
        monkeypatch.setattr(rb, "load_regime_map", lambda *, settings: fake_map)
        monkeypatch.setattr(rb, "_find_card_path", lambda agent_id, *, settings: None)

        history = rb.regime_history(start, end, settings=settings)
        result = rb.score_regime_map(history, settings=settings, mandate=_mandate())

        assert len(result.entries) == 4
        for entry in result.entries:
            assert entry.agent_id == "missing-card"
            assert entry.split is None
            assert entry.error is not None
            assert "missing-card" in entry.error
