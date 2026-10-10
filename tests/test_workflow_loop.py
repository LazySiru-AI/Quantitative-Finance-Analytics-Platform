"""Tests for the Agent Workflow desk's daily-cadence autopilot (`backend/app/workflow/loop.py`).

**Never hits the real network.** `run_once` reads only the stored bar store (via
`app.workflow.candidates.resolve_pending` and `app.workflow.book.execute_pending`, both already
network-free by their own contracts) and is called throughout this file with `live_quote_source=None`
implicitly (that is `run_once`'s own hard-coded choice -- see its module docstring's "Live quote
source" section). One daily bar is written directly into a temp-rooted DuckDB/Parquet store via
`_write_bar`, copied in spirit from `tests/test_workflow_book.py`'s own helper of the same name -- that
file's docstring documents this as the established local-builder convention for this layer (no shared
fixture in `tests/conftest.py`), and this file follows it rather than inventing a second one.

**Never waits on a real overnight sleep.** Every daemon-shaped test below either calls `run_once` or
`_run_once_safely` directly (the unit-testable, clock-free core), or drives `start`/`stop` against a
daemon whose own first wake is many hours away -- `stop()`'s interruptible sleep-slice loop
(`_sleep_checking_stop`, sliced at one second) means a stop request during that wait still returns
within a second or two, never after the wait itself elapses.
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from app.config import Settings
from app.db import duck
from app.market.models import BAR_COLUMNS, Interval
from app.paper.marketdata import clear_frame_cache
from app.tournament.models import Discipline, StrategyCard
from app.workflow import book as book_mod
from app.workflow import candidates as candidates_mod
from app.workflow import loop
from app.workflow.book_models import OrderPlan, WorkflowFillRecord, WorkflowOrderRecord
from app.workflow.pipeline import ALL_ARMS, STARTING_CASH

# ---------------------------------------------------------------------------
# Builders -- local to this file, mirroring tests/test_workflow_book.py's own convention.
# ---------------------------------------------------------------------------


def _write_bar(settings: Settings, symbol: str, day: dt.date, *, open_: float, close: float) -> None:
    """One daily bar. Copied in spirit from tests/test_workflow_book.py's `_write_bar`."""
    frame = pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(day, dt.time.min, tzinfo=dt.UTC)],
                dtype="datetime64[us, UTC]",
            ),
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


def _plan(
    *,
    symbol: str,
    notional: str = "1000.00",
    side: str = "buy",
    thesis: str = "a test thesis",
    invalidation: str = "a test invalidation",
    agent_card_id: str = "card-1",
) -> OrderPlan:
    return OrderPlan(
        agent_card_id=agent_card_id,
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        notional=Decimal(notional),
        thesis=thesis,
        invalidation=invalidation,
    )


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    clear_frame_cache()
    yield
    clear_frame_cache()


@pytest.fixture(autouse=True)
def _stop_any_daemon():
    """However a test leaves the module-level singleton, make sure the next test starts clean.

    `app.workflow.loop` exposes no `reset()` testing hook (the scope fence for this change limits this
    module to exactly what the brief asks for) -- this fixture reaches the module's own `_thread`/
    `_stop_event` globals directly instead, the same way this test file is testing an implementation
    module's internals elsewhere (`test_start_twice_...` reads `loop._thread` directly too).
    """
    yield
    loop.stop(timeout=5.0)
    loop._thread = None
    loop._stop_event = None


# ---------------------------------------------------------------------------
# 1. run_once fills a pending order due today
# ---------------------------------------------------------------------------


class TestRunOnceFillsDueOrders:
    def test_run_once_fills_a_pending_order_due_today_and_reports_it(
        self, settings: Settings
    ) -> None:
        decision_date = dt.date(2026, 3, 2)
        fill_date = dt.date(2026, 3, 3)
        _write_bar(settings, "SPY", fill_date, open_=500.00, close=501.00)
        _write_bar(settings, "AAA", decision_date, open_=99.00, close=100.00)
        _write_bar(settings, "AAA", fill_date, open_=100.00, close=101.00)

        book = book_mod.load_book(
            settings, "raw_signal", starting_cash=STARTING_CASH, card_id="card-1"
        )
        book = book_mod.stage_orders(
            book,
            [_plan(symbol="AAA")],
            decision_date=decision_date,
            fill_date=fill_date,
            run_id="run-1",
        )
        book_mod.save_book(settings, book)

        summary = loop.run_once(settings, today=fill_date)

        assert summary.today == fill_date
        assert summary.filled == 1
        assert summary.rejected == 0
        assert summary.still_pending == 0
        assert summary.stored_open_fills == 1
        assert summary.live_quote_fills == 0
        assert summary.per_arm["raw_signal"].filled == 1

        # Every other arm has no staged orders at all -- a no-op, not a failure.
        for arm in ("ta_gated", "vibe_gated", "full_workflow"):
            assert summary.per_arm[arm].filled == 0
            assert summary.per_arm[arm].rejected == 0

        # And it is durable: reloading the book off disk shows the same filled order.
        reloaded = book_mod.load_book(
            settings, "raw_signal", starting_cash=STARTING_CASH, card_id="card-1"
        )
        assert reloaded.orders[0].status == "filled"
        assert reloaded.orders[0].fill is not None
        assert reloaded.orders[0].fill.price_source == "stored_open"
        assert any(p.date == fill_date for p in reloaded.equity_curve), (
            "the fill must also be marked into the equity curve, not left at ()"
        )


# ---------------------------------------------------------------------------
# 1b. run_once marks an equity point for `today` on every arm's book, not just the one that filled
# ---------------------------------------------------------------------------


class TestRunOnceMarksEquity:
    def test_run_once_leaves_each_card_book_with_an_equity_point_for_today(
        self, settings: Settings
    ) -> None:
        today = dt.date(2026, 3, 10)
        _write_bar(settings, "SPY", today, open_=500.00, close=501.00)

        # Pre-seed all four arm books with an adopted date on or before `today`, so a book that
        # never trades still gets a real (flat) point marked rather than one held back by
        # `load_book`'s own `card_adopted_date=today()` default for a brand-new, never-saved book.
        for arm in ALL_ARMS:
            book = book_mod.load_book(
                settings, arm, starting_cash=STARTING_CASH, card_id="card-1",
                card_adopted_date=today,
            )
            book_mod.save_book(settings, book)

        loop.run_once(settings, today=today)

        for arm in ALL_ARMS:
            reloaded = book_mod.load_book(
                settings, arm, starting_cash=STARTING_CASH, card_id="card-1"
            )
            assert any(p.date == today for p in reloaded.equity_curve), (
                f"{arm} book has no equity point for {today}"
            )


# ---------------------------------------------------------------------------
# 2. run_once resolves matured candidate observations
# ---------------------------------------------------------------------------


class TestRunOnceResolvesCandidates:
    def test_run_once_calls_resolve_pending_with_the_given_today(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[Settings, dt.date | None]] = []

        def fake_resolve_pending(*, settings: Settings, today: dt.date | None = None) -> int:
            calls.append((settings, today))
            return 3

        # `loop.candidates` is the very module object imported as `candidates_mod` below -- patching
        # either name patches the same attribute the other reads.
        monkeypatch.setattr(candidates_mod, "resolve_pending", fake_resolve_pending)

        today = dt.date(2026, 4, 1)
        summary = loop.run_once(settings, today=today)

        assert calls == [(settings, today)]
        assert summary.observations_resolved == 3


# ---------------------------------------------------------------------------
# 3. start() is a no-op when the autopilot flag is off
# ---------------------------------------------------------------------------


class TestStartNoOpWhenDisabled:
    def test_start_does_not_launch_a_thread_when_workflow_autopilot_is_false(
        self, settings: Settings
    ) -> None:
        assert settings.workflow_autopilot is False

        loop.start(settings)

        assert loop._thread is None
        assert loop._stop_event is None


# ---------------------------------------------------------------------------
# 4. A failing run_once does not propagate out of the daemon's per-day wrapper
# ---------------------------------------------------------------------------


class TestRunOnceSafelySwallowsFailures:
    def test_a_raising_run_once_is_caught_logged_and_turned_into_none(
        self, settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        def boom(settings: Settings, *, today: dt.date | None = None) -> loop.ExecuteSummary:
            raise RuntimeError("simulated failure")

        with caplog.at_level(logging.ERROR, logger="app.workflow.loop"):
            result = loop._run_once_safely(
                settings, today=dt.date(2026, 5, 1), run_once_fn=boom
            )

        assert result is None
        assert any("run_once failed" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# 5. Single instance: start() twice never starts a second thread
# ---------------------------------------------------------------------------


class TestSingleInstance:
    def test_calling_start_twice_starts_only_one_thread(self, settings: Settings) -> None:
        autopilot_settings = settings.model_copy(update={"workflow_autopilot": True})

        loop.start(autopilot_settings)
        first_thread = loop._thread
        assert first_thread is not None
        assert first_thread.is_alive()

        loop.start(autopilot_settings)
        second_thread = loop._thread

        assert second_thread is first_thread, "a second start() call must not replace the running thread"
        assert first_thread.is_alive()


# ---------------------------------------------------------------------------
# 6. run_once stages mechanical exits (app.workflow.exits wiring)
# ---------------------------------------------------------------------------


def _write_card(settings: Settings, card: StrategyCard) -> None:
    settings.library_dir.mkdir(parents=True, exist_ok=True)
    (settings.library_dir / f"{card.agent_id}.json").write_text(
        card.model_dump_json(indent=2), encoding="utf-8"
    )


class TestRunOnceStagesExits:
    def test_run_once_stages_a_tripped_stop_and_reports_it_in_exits_staged(
        self, settings: Settings, tmp_path: Path
    ) -> None:
        """`run_once` must not just fill entries -- a card's own stop is the seat's whole `exits`
        callout (`app.paperdesk.models.AutopilotDescription.exits`), and until `app.workflow.exits`
        was wired into the daily step a book that only ever bought held every position forever, and
        `ExecuteSummary.exits_staged` never left zero. Breaking this wiring looks like: a position
        sits underwater past its stop night after night and the daemon never notices.

        `library_dir` is redirected into this test's own `tmp_path` -- the shared `settings` fixture
        leaves it at the real, shipped `backend/app/paper/library/`, which a throwaway test card must
        never be written into."""
        card_settings = settings.model_copy(update={"library_dir": tmp_path / "library"})
        agent_id = "exit-wiring-card"
        card = StrategyCard(
            agent_id=agent_id,
            display_name="Exit Wiring Card",
            discipline=Discipline.MOMENTUM,
            thesis="a test thesis",
            falsification="a test falsification",
            universe=("AAA",),
            entry="close > 0",
            exit="",
            stop_loss_pct=Decimal("0.10"),
            take_profit_pct=Decimal("0.20"),
            max_hold_days=30,
            max_positions=5,
            position_pct=Decimal("0.15"),
            designed_through=dt.date(2026, 2, 13),
        )
        _write_card(card_settings, card)

        acquired = dt.date(2026, 3, 2)
        today = dt.date(2026, 3, 9)
        day = acquired - dt.timedelta(days=12)
        while day <= today:
            _write_bar(card_settings, "SPY", day, open_=500.00, close=501.00)
            day += dt.timedelta(days=1)
        _write_bar(card_settings, "AAA", today, open_=90.00, close=89.00)  # <= 90.00 stop threshold

        buy = WorkflowOrderRecord(
            order_id="seed-0",
            arm="raw_signal",
            agent_card_id=agent_id,
            symbol="AAA",
            side="buy",
            notional=Decimal("1000.00"),
            decision_date=acquired - dt.timedelta(days=1),
            fill_date=acquired,
            status="filled",
            thesis="t",
            invalidation="i",
            stop_level=None,
            regime="",
            conviction=None,
            evidence=(),
            created_by_run_id="seed-run",
            fill=WorkflowFillRecord(
                price=Decimal("100.00"),
                price_source="stored_open",
                qty=Decimal("10"),
                slippage=Decimal("0"),
                fees=Decimal("0"),
                reference_open=Decimal("100.00"),
                filled_at=dt.datetime.combine(acquired, dt.time(13, 30), tzinfo=dt.UTC),
            ),
            reject_reason="",
        )
        book = book_mod.load_book(
            card_settings,
            "raw_signal",
            starting_cash=STARTING_CASH,
            card_id=agent_id,
            card_adopted_date=acquired,
        )
        book = book.model_copy(update={"orders": (buy,), "current_card_id": agent_id})
        book_mod.save_book(card_settings, book)

        summary = loop.run_once(card_settings, today=today)

        assert summary.exits_staged >= 1

        reloaded = book_mod.load_book(
            card_settings, "raw_signal", starting_cash=STARTING_CASH, card_id=agent_id
        )
        pending_sells = [
            order for order in reloaded.orders if order.side == "sell" and order.status == "pending"
        ]
        assert len(pending_sells) == 1
        assert pending_sells[0].symbol == "AAA"


# ---------------------------------------------------------------------------
# 7. run_once processes screen-mode books, folded into the totals but not per_arm
# ---------------------------------------------------------------------------


class TestRunOnceProcessesScreenBooks:
    def test_run_once_fills_a_screen_book_and_folds_it_into_the_summed_totals_not_per_arm(
        self, settings: Settings
    ) -> None:
        """A screen-mode book (`universe_source="screen"`) is a second, independent ledger at the
        same arm name -- `run_once` must fill its due orders too, but `per_arm` stays keyed by the
        four card-mode arms only (see that field's own docstring: widening it to a `(arm, source)`
        map would break every existing reader). Breaking this looks like either a screen book that
        silently never fills, or a screen fill double-counted under its card-mode arm's own entry."""
        decision_date = dt.date(2026, 3, 2)
        fill_date = dt.date(2026, 3, 3)
        _write_bar(settings, "SPY", fill_date, open_=500.00, close=501.00)
        _write_bar(settings, "AAA", decision_date, open_=99.00, close=100.00)
        _write_bar(settings, "AAA", fill_date, open_=100.00, close=101.00)

        screen_book = book_mod.load_book(
            settings,
            "raw_signal",
            starting_cash=STARTING_CASH,
            card_id="card-1",
            universe_source="screen",
        )
        screen_book = book_mod.stage_orders(
            screen_book,
            [_plan(symbol="AAA")],
            decision_date=decision_date,
            fill_date=fill_date,
            run_id="screen-run-1",
        )
        book_mod.save_book(settings, screen_book)

        summary = loop.run_once(settings, today=fill_date)

        assert summary.filled == 1
        assert summary.rejected == 0
        for arm in ("raw_signal", "ta_gated", "vibe_gated", "full_workflow"):
            assert summary.per_arm[arm].filled == 0

        reloaded = book_mod.load_book(
            settings,
            "raw_signal",
            starting_cash=STARTING_CASH,
            card_id="card-1",
            universe_source="screen",
        )
        assert reloaded.orders[0].status == "filled"

    def test_a_deployment_with_no_screen_books_still_reports_all_four_card_arms(
        self, settings: Settings
    ) -> None:
        """The no-screen-books path -- the only path any pre-existing deployment has ever exercised --
        must keep behaving exactly as it did before `run_once` learned to look for screen books:
        `per_arm` keyed by all four card arms, nothing extra, nothing missing."""
        today = dt.date(2026, 3, 9)
        _write_bar(settings, "SPY", today, open_=500.00, close=501.00)

        summary = loop.run_once(settings, today=today)

        assert set(summary.per_arm.keys()) == {"raw_signal", "ta_gated", "vibe_gated", "full_workflow"}
