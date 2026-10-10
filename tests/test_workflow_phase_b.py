"""Tests for `app.workflow.phase_b` -- the Round 33 Phase B daily step.

The fill/resolve half is exercised for real (a due screen order fills, card books are never touched);
the launch half is stubbed, since spawning real agent runs is `app.workflow.service`'s own tested
concern and this module only orchestrates and polls it.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd

from app.agentdesk.models import DeskRun
from app.agents.models import AgentBudget
from app.config import Settings
from app.db import duck
from app.db.duck import BAR_COLUMNS, Interval
from app.paper.marketdata import clear_frame_cache
from app.workflow import book as book_mod
from app.workflow.book_models import OrderPlan
from app.workflow.phase_b import PHASE_B_SCREEN_TOP_N, phase_b_request, run_phase_b_step
from app.workflow.pipeline import STARTING_CASH

_D = dt.date(2024, 3, 1)


def _write_bar(settings: Settings, symbol: str, day: dt.date, *, open_: float, close: float) -> None:
    frame = pd.DataFrame(
        {
            "ts": pd.Series([dt.datetime.combine(day, dt.time.min, tzinfo=dt.UTC)], dtype="datetime64[us, UTC]"),
            "open": [open_],
            "high": [max(open_, close) + 5.0],
            "low": [min(open_, close) - 5.0],
            "close": [close],
            "adj_close": [close],
            "volume": [1_000_000],
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)
    clear_frame_cache()


def _stage_screen_order(settings: Settings, arm: str, symbol: str, *, fill_date: dt.date) -> None:
    book = book_mod.load_book(settings, arm, starting_cash=STARTING_CASH, card_id="c", universe_source="screen")  # type: ignore[arg-type]
    plan = OrderPlan(
        agent_card_id="c", symbol=symbol, side="buy", notional=Decimal("1000.00"),
        thesis="t", invalidation="i",
    )
    book = book_mod.stage_orders(book, [plan], decision_date=fill_date, fill_date=fill_date, run_id="seed")
    book_mod.save_book(settings, book)


def test_phase_b_request_is_the_frozen_live_config() -> None:
    req = phase_b_request()
    assert req.universe_mode == "screen"
    assert req.selector_id == "mom12_1_hysteresis"
    assert req.screen_top_n == PHASE_B_SCREEN_TOP_N == 10
    assert req.arms_enabled == ["raw_signal", "full_workflow"]
    # A less-restrictive trending-state entry, so the study accrues candidates fast enough to measure.
    assert req.screen_entry_rule == "close > sma(200) and ema(20) > ema(50)"


def test_no_launch_with_no_screen_books_is_a_clean_no_op(settings: Settings) -> None:
    summary = run_phase_b_step(settings, today=_D, launch=False)
    assert summary.launched_run_id is None
    assert (summary.filled, summary.rejected, summary.still_pending) == (0, 0, 0)
    assert summary.staged == {"raw_signal": 0, "full_workflow": 0}


def test_fill_fills_a_due_screen_order_and_never_touches_card_books(settings: Settings) -> None:
    _write_bar(settings, "SPY", _D, open_=500.0, close=501.0)
    _write_bar(settings, "XLK", _D, open_=100.0, close=101.0)
    _stage_screen_order(settings, "raw_signal", "XLK", fill_date=_D)

    summary = run_phase_b_step(settings, today=_D, launch=False)

    assert summary.filled == 1
    assert summary.staged["raw_signal"] == 0  # no longer pending -- it filled
    # The screen book was processed; the card book of the same arm was never created.
    assert book_mod.book_path(settings, "raw_signal", universe_source="screen").is_file()
    assert not book_mod.book_path(settings, "raw_signal", universe_source="card").is_file()

    # And the fill was also marked into the equity curve for `_D`, not left at `()`.
    book = book_mod.load_book(
        settings, "raw_signal", starting_cash=STARTING_CASH, card_id="", universe_source="screen"
    )
    assert any(p.date == _D for p in book.equity_curve)


def test_fill_skips_a_screen_book_that_does_not_exist(settings: Settings) -> None:
    _write_bar(settings, "XLK", _D, open_=100.0, close=101.0)
    _stage_screen_order(settings, "raw_signal", "XLK", fill_date=_D)
    # full_workflow screen book was never staged -> must be skipped, not seeded.
    run_phase_b_step(settings, today=_D, launch=False)
    assert not book_mod.book_path(settings, "full_workflow", universe_source="screen").is_file()


def test_launch_issues_the_frozen_request_and_polls_to_terminal(settings: Settings, monkeypatch) -> None:
    from app.agentdesk.store import RunStore
    from app.workflow import service as service_mod

    captured: dict[str, object] = {}
    canned = DeskRun(
        run_id="pb-1", kind="workflow", state="succeeded",
        created_at=dt.datetime(2024, 3, 1, 12, 0, tzinfo=dt.UTC),
        config={}, stages=(), budget=AgentBudget(cap_usd=Decimal("16")),
    )

    def fake_start(req, *, settings):
        captured["req"] = req
        return canned

    monkeypatch.setattr(service_mod, "start_workflow_run", fake_start)
    monkeypatch.setattr(RunStore, "load", lambda self, run_id: canned)

    summary = run_phase_b_step(settings, today=_D, launch=True, sleep_fn=lambda _s: None)

    assert summary.launched_run_id == "pb-1"
    assert summary.launched_state == "succeeded"
    req = captured["req"]
    assert req.selector_id == "mom12_1_hysteresis"  # type: ignore[attr-defined]
    assert req.screen_top_n == 10  # type: ignore[attr-defined]
