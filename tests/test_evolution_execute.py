"""Tests for `app.evolution.execute` and the two narrow `app.tournament.jobs` edits it depends on.

Three things are exercised here, deliberately kept in one file because they are one feature cut
three ways:

1. `jobs._LIBRARY_TIERS` gaining `"generated"`, and `jobs._load_library_index` tolerating a
   non-`StrategyCard` payload (an `AllocationCard`) in that one tier while staying strict everywhere
   else -- `TestGeneratedTier` below.
2. `jobs.external_round_slot`, the public context manager that lets a runner outside `jobs._worker`
   take the exact same process-wide single-slot lock `start_job` takes -- `TestExternalRoundSlot`.
3. `execute.run_generation` itself, which drives both card shapes through that slot and writes run
   files `app.tournament.results.load_round_scored_runs` can read back -- everything after that.

**No test here runs a real multi-window round.** `execute.run_card`/`execute.run_allocation` are
monkeypatched with fast fakes everywhere except `TestGenuineRunCardCall` and the `max_workers>1` tests
below, which write a handful of synthetic bars into a `tmp_path`-rooted store (the same technique
`tests/test_tournament_runner.py` uses) and trade a short window -- a genuine `run_card` call, proven
rather than assumed, but cheap because the windows are a handful of sessions long, not eight months.
Every test redirects the job registry to `tmp_path` via `jobs.reset_registry(output_root=...)`; none
of them ever touch the real `data/rounds/` or `backend/app/paper/library/`.

**A fourth thing is exercised, at the bottom of this file: `max_workers > 1`.** A monkeypatched
`execute.run_card`/`execute.run_allocation` only takes effect in *this* process -- a worker process
spawned by `ProcessPoolExecutor` gets its own fresh, unpatched import of `app.evolution.execute`, so
every test that actually drives cards through the pool (`TestParallelExecution`,
`TestParallelFailureIsolation`, `TestParallelCancellation`) uses genuine `run_card` calls against real,
synthetic bars, the same way `TestGenuineRunCardCall` does. The one exception is
`TestBrokenProcessPoolFallback`, which reproduces a worker dying underneath the pool -- not practical
to do for real, fast and deterministically, in a unit test -- by calling `execute._run_window_in_pool`
directly with a fake executor whose `submit()` hands back a `Future` pre-loaded with
`BrokenProcessPool`, rather than a real `ProcessPoolExecutor`; see that test's own docstring.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.db import duck
from app.evolution import execute
from app.market.models import BAR_COLUMNS, Interval
from app.tournament import jobs, results
from app.tournament.allocation import AllocationCard, AllocationResult, Sleeve
from app.tournament.models import DESIGN_THROUGH, AgentResult, Discipline, StrategyCard

# ---------------------------------------------------------------------------
# Card / bar / result builders -- kept local to this file rather than imported from
# tests/test_competition_jobs.py or tests/test_tournament_runner.py, both of which own their own
# fixtures and are not this file's to import from.
# ---------------------------------------------------------------------------


def _card(**overrides: object) -> StrategyCard:
    fields: dict[str, object] = {
        "agent_id": "exec-agent",
        "display_name": "Exec Agent",
        "discipline": Discipline.TREND,
        "thesis": "a test thesis, written before the trading window ran",
        "universe": ("TESTX",),
        "entry": "close > 0",
        "exit": "",
        "max_hold_days": 50,
        "max_positions": 1,
        "position_pct": Decimal("1.0"),
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return StrategyCard(**fields)  # type: ignore[arg-type]


def _allocation_card(**overrides: object) -> AllocationCard:
    fields: dict[str, object] = {
        "agent_id": "exec-alloc",
        "display_name": "Exec Allocation",
        "thesis": "a test thesis for an allocation card, written before the trading window ran",
        "sleeves": (
            Sleeve(symbol="QLD", target_weight=Decimal("0.5")),
            Sleeve(symbol="SGOV", target_weight=Decimal("0.5")),
        ),
        "band_pct": Decimal("0.05"),
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return AllocationCard(**fields)  # type: ignore[arg-type]


def _fake_agent_result(card: StrategyCard) -> AgentResult:
    return AgentResult(
        card=card,
        sessions=10,
        starting_equity=Decimal("10000.00"),
        ending_equity=Decimal("10500.00"),
        total_return=Decimal("0.05"),
        max_drawdown=Decimal("-0.02"),
        trades=(),
        benchmark_return=Decimal("0.02"),
        capital_exposure=0.4,
    )


def _fake_allocation_result(card: AllocationCard) -> AllocationResult:
    return AllocationResult(
        card=card,
        sessions=10,
        starting_equity=Decimal("10000.00"),
        ending_equity=Decimal("10300.00"),
        total_return=Decimal("0.03"),
        max_drawdown=Decimal("-0.01"),
        trades=(),
        benchmark_return=Decimal("0.02"),
        capital_exposure=0.6,
    )


def _weekdays(anchor: dt.date, count: int) -> list[dt.date]:
    dates: list[dt.date] = []
    day = anchor
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day += dt.timedelta(days=1)
    return dates


def _flat(dates: list[dt.date], price: float) -> dict[dt.date, tuple[float, float]]:
    return dict.fromkeys(dates, (price, price))


def _write_bars(settings: Settings, symbol: str, prices: dict[dt.date, tuple[float, float]]) -> None:
    """One daily bar per `(open, close)` in `prices` -- copied from
    `tests/test_tournament_runner.py`'s identical helper, which explains the generous high/low
    bracket: every bracket decision the runner makes is based on the close, never the high/low, so
    their exact values are inert here."""
    dates = sorted(prices)
    opens = [prices[d][0] for d in dates]
    closes = [prices[d][1] for d in dates]
    frame = pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC) for d in dates],
                dtype="datetime64[us, UTC]",
            ),
            "open": opens,
            "high": [max(o, c) + 5.0 for o, c in zip(opens, closes, strict=True)],
            "low": [min(o, c) - 5.0 for o, c in zip(opens, closes, strict=True)],
            "close": closes,
            "adj_close": closes,
            "volume": [1_000_000] * len(dates),
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)


@pytest.fixture(autouse=True)
def _reset_registry_after_every_test() -> None:
    """Belt and braces, matching `tests/test_competition_jobs.py`'s identical fixture: whatever a
    test leaves registered must not leak into the next test's `JobAlreadyRunning` check."""
    yield
    jobs.reset_registry()


# ---------------------------------------------------------------------------
# 1. `generated` tier: resolution, and tolerant-but-only-there parsing
# ---------------------------------------------------------------------------


class TestGeneratedTier:
    @pytest.fixture
    def library_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Redirects both of `jobs`' tier roots to an empty `tmp_path` tree rather than the real,
        committed `backend/app/paper/library/` -- so a test can plant exactly the files it wants to
        assert about, including a deliberately malformed one, without touching real library content.

        **Two roots, not one, since the `generated` tier moved out of the library.** Auto-proposed
        cards now live under `data/loop/generated/` (`app.evolution.models.generated_tier_dir`), which
        `jobs` resolves through its own `_generated_tier_dir()` rather than through `_library_root()`.
        Patching only the latter left this fixture planting files somewhere `_load_library_index` no
        longer looks, and the two tests below failed against the *real* `data/loop/generated/`
        instead -- a fixture silently testing production state, which is worse than an outright
        error. Both are patched to the same `tmp_path` tree so the tests read exactly as they did
        before the move.
        """
        root = tmp_path / "library"
        monkeypatch.setattr(jobs, "_library_root", lambda: root)
        monkeypatch.setattr(jobs, "_generated_tier_dir", lambda: root / "generated")
        return root

    def test_generated_tier_resolves_a_card_by_agent_id(self, library_root: Path) -> None:
        generated_dir = library_root / "generated"
        generated_dir.mkdir(parents=True)
        card = _card(agent_id="G-searcher-1")
        (generated_dir / "G-searcher-1.json").write_text(
            card.model_dump_json(indent=2), encoding="utf-8"
        )

        resolved = jobs._resolve_cards(["G-searcher-1"], "base")

        assert len(resolved) == 1
        assert resolved[0].agent_id == "G-searcher-1"

    def test_allocation_card_in_generated_tier_is_skipped_not_raised(
        self, library_root: Path
    ) -> None:
        generated_dir = library_root / "generated"
        generated_dir.mkdir(parents=True)
        alloc = _allocation_card(agent_id="G-alloc-1")
        (generated_dir / "G-alloc-1.json").write_text(
            alloc.model_dump_json(indent=2), encoding="utf-8"
        )
        valid = _card(agent_id="G-valid-1")
        (generated_dir / "G-valid-1.json").write_text(
            valid.model_dump_json(indent=2), encoding="utf-8"
        )

        # Must not raise: the AllocationCard payload fails StrategyCard validation and is skipped.
        index = jobs._load_library_index()

        assert "G-alloc-1" not in index
        assert "G-valid-1" in index
        assert index["G-valid-1"][0] == "generated"

    def test_malformed_card_in_base_tier_still_raises(self, library_root: Path) -> None:
        base_dir = library_root / "base"
        base_dir.mkdir(parents=True)
        (base_dir / "Bad.json").write_text(
            json.dumps({"agent_id": "Bad", "display_name": "Bad Card"}), encoding="utf-8"
        )

        with pytest.raises(ValidationError):
            jobs._load_library_index()

    def test_malformed_card_in_generated_tier_alone_is_not_enough_to_hide_a_base_defect(
        self, library_root: Path
    ) -> None:
        """The tolerance is scoped to `generated/` only -- a base-tier defect still surfaces even
        when a generated-tier AllocationCard sits right beside it."""
        (library_root / "generated").mkdir(parents=True)
        alloc = _allocation_card(agent_id="G-alloc-2")
        (library_root / "generated" / "G-alloc-2.json").write_text(
            alloc.model_dump_json(indent=2), encoding="utf-8"
        )
        (library_root / "base").mkdir(parents=True)
        (library_root / "base" / "Bad.json").write_text(
            json.dumps({"agent_id": "Bad"}), encoding="utf-8"
        )

        with pytest.raises(ValidationError):
            jobs._load_library_index()


# ---------------------------------------------------------------------------
# 2. `external_round_slot`: the single invariant this whole feature must not violate
# ---------------------------------------------------------------------------


class TestExternalRoundSlot:
    def test_raises_job_already_running_on_contention_and_releases_on_normal_exit(
        self, tmp_path: Path
    ) -> None:
        jobs.reset_registry(output_root=tmp_path)

        with jobs.external_round_slot("r-first", total_runs=1) as job1:
            with pytest.raises(jobs.JobAlreadyRunning) as excinfo, jobs.external_round_slot(
                "r-second", total_runs=1
            ):
                pass  # pragma: no cover - register() raises before this body ever runs
            assert job1.job_id in str(excinfo.value)

            with job1.lock:
                job1.status = "succeeded"
                job1.finished_at = dt.datetime.now(dt.UTC)

        # The slot is free again after a normal (non-exception) exit.
        with jobs.external_round_slot("r-third", total_runs=1) as job3:
            assert job3.job_id != job1.job_id
            with job3.lock:
                job3.status = "succeeded"
                job3.finished_at = dt.datetime.now(dt.UTC)

    def test_releases_the_slot_and_marks_the_job_failed_on_an_uncaught_exception(
        self, tmp_path: Path
    ) -> None:
        jobs.reset_registry(output_root=tmp_path)
        captured: dict[str, object] = {}

        with (
            pytest.raises(RuntimeError, match="boom"),
            jobs.external_round_slot("r-boom", total_runs=1) as job,
        ):
            captured["job"] = job
            raise RuntimeError("boom")

        job = captured["job"]
        assert job.status == "failed"  # type: ignore[union-attr]
        assert "boom" in (job.error or "")  # type: ignore[union-attr]

        # The registry does not still think r-boom's job is running.
        with jobs.external_round_slot("r-after-boom", total_runs=1) as job2, job2.lock:
            job2.status = "succeeded"
            job2.finished_at = dt.datetime.now(dt.UTC)


# ---------------------------------------------------------------------------
# 3. `run_generation`: both card shapes, failure handling, cancellation
# ---------------------------------------------------------------------------


class TestRunGenerationBothShapes:
    def test_writes_run_files_both_shapes_readable_by_results(
        self, tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        jobs.reset_registry(output_root=tmp_path)
        strategy_card = _card(agent_id="X-strategy")
        allocation_card = _allocation_card(agent_id="X-allocation")

        monkeypatch.setattr(execute, "run_card", lambda card, **_kw: _fake_agent_result(card))
        monkeypatch.setattr(
            execute, "run_allocation", lambda card, **_kw: _fake_allocation_result(card)
        )

        report = execute.run_generation(
            round_id="r-both-shapes",
            cards=[strategy_card, allocation_card],
            windows=["covid"],
            settings=settings,
            output_root=tmp_path,
        )

        assert report.status == "succeeded"
        assert report.job_id is not None
        assert report.completed_runs == 2
        assert report.failed_runs == 0
        assert report.errors == ()

        # The whole point: results.load_round_scored_runs (the reader the Competition page and the
        # loop's own scoring both use) must parse what run_generation wrote, for both shapes.
        scored = results.load_round_scored_runs("r-both-shapes", rounds_root=tmp_path)
        by_agent = scored["covid"]
        assert set(by_agent) == {"X-strategy", "X-allocation"}
        assert by_agent["X-strategy"].card_shape == "stock-picking"
        assert by_agent["X-allocation"].card_shape == "allocation"

        for card in (strategy_card, allocation_card):
            frozen_path = tmp_path / "r-both-shapes" / "cards" / f"{card.agent_id}.json"
            assert frozen_path.is_file(), f"expected a frozen card at {frozen_path}"

        run_path = (
            tmp_path
            / "r-both-shapes"
            / "results"
            / "covid"
            / "runs"
            / f"{jobs._TAG}-X-strategy.json"
        )
        loaded = AgentResult.model_validate_json(run_path.read_text(encoding="utf-8"))
        assert loaded.card.agent_id == "X-strategy"

    def test_failing_card_is_recorded_and_the_run_continues(
        self, tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        jobs.reset_registry(output_root=tmp_path)
        good = _card(agent_id="X-good")
        bad = _card(agent_id="X-bad")

        def fake_run_card(card: StrategyCard, **_kw: object) -> AgentResult:
            if card.agent_id == "X-bad":
                raise RuntimeError("synthetic failure")
            return _fake_agent_result(card)

        monkeypatch.setattr(execute, "run_card", fake_run_card)

        report = execute.run_generation(
            round_id="r-partial",
            cards=[good, bad],
            windows=["covid"],
            settings=settings,
            output_root=tmp_path,
        )

        assert report.status == "succeeded", "one card's failure must not fail the generation"
        assert report.completed_runs == 1
        assert report.failed_runs == 1
        assert len(report.errors) == 1
        assert "X-bad" in report.errors[0]
        assert "synthetic failure" in report.errors[0]

        good_run = (
            tmp_path / "r-partial" / "results" / "covid" / "runs" / f"{jobs._TAG}-X-good.json"
        )
        bad_run = tmp_path / "r-partial" / "results" / "covid" / "runs" / f"{jobs._TAG}-X-bad.json"
        assert good_run.is_file()
        assert not bad_run.is_file()

    def test_cancel_between_cards_returns_cancelled(
        self, tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        jobs.reset_registry(output_root=tmp_path)
        cancel_event = threading.Event()
        first = _card(agent_id="X-first")
        second = _card(agent_id="X-second")

        def fake_run_card(card: StrategyCard, **_kw: object) -> AgentResult:
            result = _fake_agent_result(card)
            if card.agent_id == "X-first":
                # Cancellation fires *during* the first card's run -- it must still be allowed to
                # finish (there is no way to abort a run in flight); only the next card is skipped.
                cancel_event.set()
            return result

        monkeypatch.setattr(execute, "run_card", fake_run_card)

        report = execute.run_generation(
            round_id="r-cancel",
            cards=[first, second],
            windows=["covid", "bear-2022"],
            settings=settings,
            cancel=cancel_event,
            output_root=tmp_path,
        )

        assert report.status == "cancelled"
        assert report.completed_runs == 1
        assert report.failed_runs == 0
        assert report.windows == ("covid", "bear-2022"), "reports the request, not just the reach"

        first_run = (
            tmp_path / "r-cancel" / "results" / "covid" / "runs" / f"{jobs._TAG}-X-first.json"
        )
        second_run = (
            tmp_path / "r-cancel" / "results" / "covid" / "runs" / f"{jobs._TAG}-X-second.json"
        )
        assert first_run.is_file()
        assert not second_run.is_file()
        assert not (tmp_path / "r-cancel" / "results" / "bear-2022").exists()

    def test_mandate_load_failure_fails_the_whole_generation(
        self, tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        jobs.reset_registry(output_root=tmp_path)

        def broken_mandate() -> object:
            raise RuntimeError("mandate config missing")

        monkeypatch.setattr(jobs, "_load_mandate", broken_mandate)

        report = execute.run_generation(
            round_id="r-mandate-fail",
            cards=[_card(agent_id="X-irrelevant")],
            windows=["covid"],
            settings=settings,
            output_root=tmp_path,
        )

        assert report.status == "failed"
        assert report.completed_runs == 0
        assert report.failed_runs == 0
        assert any("mandate" in e for e in report.errors)

    def test_round_already_populated_is_refused(
        self, tmp_path: Path, settings: Settings
    ) -> None:
        jobs.reset_registry(output_root=tmp_path)
        existing = tmp_path / "r-taken" / "results" / "covid" / "runs"
        existing.mkdir(parents=True)
        (existing / "r1-X-existing.json").write_text("{}", encoding="utf-8")

        with pytest.raises(jobs.RoundAlreadyExists):
            execute.run_generation(
                round_id="r-taken",
                cards=[_card(agent_id="X-new")],
                windows=["covid"],
                settings=settings,
                output_root=tmp_path,
            )


# ---------------------------------------------------------------------------
# 4. output_root is honoured everywhere, and settings.rounds_dir is never touched
# ---------------------------------------------------------------------------


class TestOutputRootIsolation:
    def test_output_root_receives_every_file_and_settings_rounds_dir_stays_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        jobs.reset_registry()
        # A Settings object whose rounds_dir stands in for the real `data/rounds/` -- git-tracked,
        # and the one place this call must never write regardless of what output_root says.
        untouched_rounds_dir = tmp_path / "settings-rounds-dir"
        explicit_root = tmp_path / "explicit-output-root"
        settings = Settings(rounds_dir=untouched_rounds_dir)

        card = _card(agent_id="X-root-check")
        monkeypatch.setattr(execute, "run_card", lambda c, **_kw: _fake_agent_result(c))

        report = execute.run_generation(
            round_id="r-root-check",
            cards=[card],
            windows=["covid"],
            settings=settings,
            output_root=explicit_root,
        )

        assert report.status == "succeeded"

        run_path = (
            explicit_root
            / "r-root-check"
            / "results"
            / "covid"
            / "runs"
            / f"{jobs._TAG}-X-root-check.json"
        )
        assert run_path.is_file(), f"expected a run file under output_root at {run_path}"
        frozen_path = explicit_root / "r-root-check" / "cards" / "X-root-check.json"
        assert frozen_path.is_file(), f"expected a frozen card under output_root at {frozen_path}"

        assert not untouched_rounds_dir.exists(), (
            "run_generation must never fall back to settings.rounds_dir when an explicit "
            "output_root was given"
        )

    def test_default_output_root_is_jobs_default_not_settings_rounds_dir(
        self, tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When `output_root` is omitted, the default is `jobs._default_output_root()` -- which
        `jobs.reset_registry(output_root=...)` redirects -- not `settings.rounds_dir`. This is the
        behaviour the evolution loop's supervisor and every other test in this file both rely on."""
        jobs.reset_registry(output_root=tmp_path)
        card = _card(agent_id="X-default-root")
        monkeypatch.setattr(execute, "run_card", lambda c, **_kw: _fake_agent_result(c))

        report = execute.run_generation(
            round_id="r-default-root",
            cards=[card],
            windows=["covid"],
            settings=settings,
        )

        assert report.status == "succeeded"
        run_path = (
            tmp_path
            / "r-default-root"
            / "results"
            / "covid"
            / "runs"
            / f"{jobs._TAG}-X-default-root.json"
        )
        assert run_path.is_file()


# ---------------------------------------------------------------------------
# 5. A genuine run_card call -- the call convention proven, not assumed
# ---------------------------------------------------------------------------


class TestGenuineRunCardCall:
    def test_run_generation_drives_a_real_run_card_on_a_tiny_window(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        dates = _weekdays(dt.date(2026, 1, 5), 8)
        trade_dates = dates[5:]
        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(settings, "TESTX", _flat(dates, 50.0))

        start, end = trade_dates[0], trade_dates[-1]
        # A tiny custom window, patched into the real jobs.WINDOWS matrix for this test only --
        # execute.run_generation only ever accepts a tag jobs.WINDOWS already knows (matching
        # jobs._worker's own contract), so a genuine, fast run needs a real entry there, not a
        # parallel windows table this module would have to invent for itself.
        monkeypatch.setitem(jobs.WINDOWS, "exec-tiny", (start, end, "tiny test window"))
        jobs.reset_registry(output_root=tmp_path)

        card = _card(agent_id="exec-genuine", universe=("TESTX",))

        report = execute.run_generation(
            round_id="r-genuine",
            cards=[card],
            windows=["exec-tiny"],
            settings=settings,
            output_root=tmp_path,
        )

        assert report.status == "succeeded"
        assert report.completed_runs == 1
        assert report.failed_runs == 0
        assert report.errors == ()

        run_path = (
            tmp_path
            / "r-genuine"
            / "results"
            / "exec-tiny"
            / "runs"
            / f"{jobs._TAG}-exec-genuine.json"
        )
        assert run_path.is_file()

        loaded = AgentResult.model_validate_json(run_path.read_text(encoding="utf-8"))
        assert loaded.card.agent_id == "exec-genuine"
        assert loaded.sessions == len(trade_dates)

        scored = results.load_round_scored_runs("r-genuine", rounds_root=tmp_path)
        assert scored["exec-tiny"]["exec-genuine"].card_shape == "stock-picking"


# ---------------------------------------------------------------------------
# 6. max_workers > 1 -- genuine cards run through a real ProcessPoolExecutor
# ---------------------------------------------------------------------------


class TestParallelExecution:
    def test_output_identical_regardless_of_max_workers(
        self, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point of `max_workers`: a generation run at `max_workers=1` and one run at
        `max_workers=3`, same cards, same window, must write byte-identical run files. Both runs use
        a genuine `run_card` call (no monkeypatch reaches a worker process), so this is a real proof,
        not an artifact of a fake always returning the same canned result."""
        dates = _weekdays(dt.date(2026, 1, 5), 10)
        trade_dates = dates[5:]
        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(settings, "TESTX", _flat(dates, 50.0))
        _write_bars(settings, "TESTY", _flat(dates, 75.0))

        start, end = trade_dates[0], trade_dates[-1]
        monkeypatch.setitem(jobs.WINDOWS, "exec-parallel", (start, end, "tiny parallel test window"))

        cards = [
            _card(agent_id="P-one", universe=("TESTX",)),
            _card(agent_id="P-two", universe=("TESTY",)),
            _card(agent_id="P-three", universe=("TESTX", "TESTY")),
        ]

        jobs.reset_registry(output_root=tmp_path)
        report_serial = execute.run_generation(
            round_id="r-parallel-serial",
            cards=cards,
            windows=["exec-parallel"],
            settings=settings,
            output_root=tmp_path,
            max_workers=1,
        )
        jobs.reset_registry(output_root=tmp_path)
        report_parallel = execute.run_generation(
            round_id="r-parallel-three",
            cards=cards,
            windows=["exec-parallel"],
            settings=settings,
            output_root=tmp_path,
            max_workers=3,
        )

        assert report_serial.status == "succeeded"
        assert report_parallel.status == "succeeded"
        assert report_serial.completed_runs == report_parallel.completed_runs == 3
        assert report_serial.failed_runs == report_parallel.failed_runs == 0
        assert report_serial.errors == report_parallel.errors == ()

        for card in cards:
            serial_path = (
                tmp_path
                / "r-parallel-serial"
                / "results"
                / "exec-parallel"
                / "runs"
                / f"{jobs._TAG}-{card.agent_id}.json"
            )
            parallel_path = (
                tmp_path
                / "r-parallel-three"
                / "results"
                / "exec-parallel"
                / "runs"
                / f"{jobs._TAG}-{card.agent_id}.json"
            )
            assert serial_path.is_file(), f"expected a serial run file at {serial_path}"
            assert parallel_path.is_file(), f"expected a parallel run file at {parallel_path}"
            assert serial_path.read_text(encoding="utf-8") == parallel_path.read_text(
                encoding="utf-8"
            ), f"{card.agent_id}: max_workers=1 and max_workers=3 wrote different run files"

    def test_max_workers_one_takes_the_serial_in_process_path(
        self, tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`max_workers=1` (the default) must never touch `ProcessPoolExecutor` -- proven here by
        monkeypatching `execute.run_card`, which only takes effect in this process. If this call
        silently went through a worker process instead, `calls` would stay empty (the worker's own
        fresh import of `run_card` would be unpatched) and the two run files below would never be
        written by the fake at all."""
        jobs.reset_registry(output_root=tmp_path)
        calls: list[str] = []

        def fake_run_card(card: StrategyCard, **_kw: object) -> AgentResult:
            calls.append(card.agent_id)
            return _fake_agent_result(card)

        monkeypatch.setattr(execute, "run_card", fake_run_card)

        cards = [_card(agent_id="X-serial-a"), _card(agent_id="X-serial-b")]

        report = execute.run_generation(
            round_id="r-serial-explicit",
            cards=cards,
            windows=["covid"],
            settings=settings,
            output_root=tmp_path,
            max_workers=1,
        )

        assert report.status == "succeeded"
        assert report.completed_runs == 2
        assert report.failed_runs == 0
        assert sorted(calls) == ["X-serial-a", "X-serial-b"]

        for agent_id in ("X-serial-a", "X-serial-b"):
            run_path = (
                tmp_path
                / "r-serial-explicit"
                / "results"
                / "covid"
                / "runs"
                / f"{jobs._TAG}-{agent_id}.json"
            )
            assert run_path.is_file()


class TestParallelFailureIsolation:
    def test_failing_card_is_recorded_and_the_rest_run_under_parallelism(
        self, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A genuine failure (`runner.GuardFailed`, from too few bars for a 20-period SMA's causality
        window -- the same technique `tests/test_tournament_runner.py::TestGuardFailure` uses) raised
        inside a worker process must still be recorded and walked past, exactly as the serial path
        does. This is deliberately a real exception from a real card, not a monkeypatched one --
        monkeypatching `execute.run_card` would prove nothing about a worker process's own exception
        handling."""
        dates = _weekdays(dt.date(2026, 1, 5), 6)
        d1 = dates[5]
        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(settings, "TESTX", _flat(dates, 100.0))

        monkeypatch.setitem(jobs.WINDOWS, "exec-guard", (d1, d1, "tiny guard-failure test window"))

        good = _card(agent_id="P-good", universe=("TESTX",), entry="close > 0")
        bad = _card(agent_id="P-bad", universe=("TESTX",), entry="close > sma(20)")

        jobs.reset_registry(output_root=tmp_path)
        report = execute.run_generation(
            round_id="r-parallel-partial",
            cards=[good, bad],
            windows=["exec-guard"],
            settings=settings,
            output_root=tmp_path,
            max_workers=2,
        )

        assert report.status == "succeeded", "one card's failure must not fail the generation"
        assert report.completed_runs == 1
        assert report.failed_runs == 1
        assert len(report.errors) == 1
        assert "P-bad" in report.errors[0]
        assert "GuardFailed" in report.errors[0]

        good_run = (
            tmp_path
            / "r-parallel-partial"
            / "results"
            / "exec-guard"
            / "runs"
            / f"{jobs._TAG}-P-good.json"
        )
        bad_run = (
            tmp_path
            / "r-parallel-partial"
            / "results"
            / "exec-guard"
            / "runs"
            / f"{jobs._TAG}-P-bad.json"
        )
        assert good_run.is_file()
        assert not bad_run.is_file()


class TestParallelCancellation:
    def test_cancel_between_windows_returns_cancelled_under_parallelism(
        self, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cancellation fires (via a `log` callback watching for the first card's completion line --
        the parallel equivalent of the serial suite's monkeypatched-`run_card` trick, since a worker
        process cannot be monkeypatched from here) while window one's three genuine cards are still
        running. Every card already submitted to the pool keeps running to completion -- there is no
        way to abort a card mid-run, under `max_workers>1` any more than under the serial path -- so
        window one finishes in full; only window two, whose cancel check comes before any card is
        submitted, is skipped. `status` must still land on `"cancelled"`, not `"succeeded"`."""
        dates = _weekdays(dt.date(2026, 1, 5), 10)
        trade_dates = dates[5:]
        _write_bars(settings, "SPY", _flat(dates, 100.0))
        _write_bars(settings, "TESTX", _flat(dates, 50.0))

        start, end = trade_dates[0], trade_dates[-1]
        monkeypatch.setitem(jobs.WINDOWS, "exec-cancel-1", (start, end, "tiny cancel window one"))
        monkeypatch.setitem(jobs.WINDOWS, "exec-cancel-2", (start, end, "tiny cancel window two"))

        cards = [_card(agent_id=f"P-cancel-{i}", universe=("TESTX",)) for i in range(3)]

        jobs.reset_registry(output_root=tmp_path)
        cancel_event = threading.Event()

        def watch_log(line: str) -> None:
            if ": ok " in line:  # a card just completed -- cancel before the next window starts
                cancel_event.set()

        report = execute.run_generation(
            round_id="r-parallel-cancel",
            cards=cards,
            windows=["exec-cancel-1", "exec-cancel-2"],
            settings=settings,
            output_root=tmp_path,
            max_workers=2,
            cancel=cancel_event,
            log=watch_log,
        )

        assert report.status == "cancelled"
        assert report.completed_runs == 3, "window one's already-submitted cards must all finish"
        assert report.failed_runs == 0
        assert report.windows == ("exec-cancel-1", "exec-cancel-2"), (
            "reports the request, not just the reach"
        )
        assert not (tmp_path / "r-parallel-cancel" / "results" / "exec-cancel-2").exists()


class TestBrokenProcessPoolFallback:
    def test_a_broken_worker_pool_falls_back_to_serial_for_the_rest_of_the_window(
        self, tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A real worker process dying underneath a real `ProcessPoolExecutor` (an OOM kill, a
        segfault) is not something a fast, deterministic unit test can reproduce on demand -- so this
        calls `execute._run_window_in_pool` directly, the same function `run_generation` calls once
        `max_workers>1`, with a fake executor standing in for the pool. Its `submit()` hands back a
        real `concurrent.futures.Future`, pre-loaded with `BrokenProcessPool` for one poisoned card
        and a genuine (monkeypatched, in-process) `_run_one_card_in_worker` call for the other two --
        reproducing exactly what a real pool does when a worker dies (every pending future raises
        `BrokenProcessPool`, not just the one that triggered it), without needing an actual crash.

        The proof this test exists for: the pool dying must not lose the generation. The poisoned
        card gets a real answer anyway, via the serial fallback -- not a synthetic failure, and not
        silently dropped -- and the fallback is logged, satisfying "record it" rather than "swallow
        it"."""
        good_a = _card(agent_id="B-good-a")
        poison = _card(agent_id="B-poison")
        good_b = _card(agent_id="B-good-b")

        monkeypatch.setattr(execute, "run_card", lambda card, **_kw: _fake_agent_result(card))

        class _FakeBrokenPoolExecutor:
            def submit(self, fn, **kwargs):
                future: Future = Future()
                if kwargs["agent_id"] == "B-poison":
                    future.set_exception(BrokenProcessPool("synthetic worker crash"))
                else:
                    future.set_result(fn(**kwargs))
                return future

        runs_dir = tmp_path / "r-broken-pool" / "results" / "covid" / "runs"
        runs_dir.mkdir(parents=True)

        job = jobs._Job(round_id="r-broken-pool", cards=(), windows=(), output_root=tmp_path)
        mandate = jobs._load_mandate()
        counts = execute._Counts()
        errors: list[str] = []
        log_lines: list[str] = []

        start, end, _regime = jobs.WINDOWS["covid"]
        cancelled, pool_broke = execute._run_window_in_pool(
            executor=_FakeBrokenPoolExecutor(),  # type: ignore[arg-type]
            job=job,
            window="covid",
            cards=[good_a, poison, good_b],
            runs_dir=runs_dir,
            settings=settings,
            mandate=mandate,
            start=start,
            end=end,
            cancel_requested=lambda: False,
            counts=counts,
            errors=errors,
            emit=log_lines.append,
        )

        assert pool_broke is True
        assert cancelled is False
        assert counts.completed == 3, "the poisoned card must still get a real result, via fallback"
        assert counts.failed == 0
        assert any("pool broke" in line for line in log_lines), "the crash must be logged, not silent"

        for agent_id in ("B-good-a", "B-poison", "B-good-b"):
            run_path = runs_dir / f"{jobs._TAG}-{agent_id}.json"
            assert run_path.is_file(), f"expected a run file for {agent_id} at {run_path}"

        assert len(job.results) == 3, "no card may be recorded twice (once from the pool, once retried)"
        assert sorted(r.agent_id for r in job.results) == ["B-good-a", "B-good-b", "B-poison"]

    def test_a_broken_pool_under_a_pending_cancel_still_finishes_already_submitted_cards(
        self, tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The two failure modes above, together: cancellation is requested *while* a window's cards
        are in flight, and then the worker pool dies. This is not hypothetical -- it is what
        `TestParallelCancellation` hit for real during a full-suite run whose stderr carried
        "OpenBLAS error: Memory allocation still failed after 10 retries, giving up": a worker died on
        a memory-constrained host after the first card had already completed and set the cancel event.

        Every card here was submitted to the pool before cancellation was observed, so every one of
        them must finish and be recorded -- exactly as they would have on the success path, whose
        result-collection loop has no cancel check at all. The defect this test pins is not a slow
        cancel but silent loss: the already-submitted cards were dropped without incrementing
        `completed`, incrementing `failed`, or appending to `errors`, so a generation that lost a
        whole window's work was indistinguishable from one cancelled cleanly before it started.

        Cancellation is driven off the first `ok` log line, the same trick `TestParallelCancellation`
        uses -- and, because that line is only ever emitted from `_apply_outcome` inside the
        result-collection loop, the cancel is guaranteed to land *after* every card was submitted and
        *before* the fallback runs, whatever order `as_completed` yields the three already-finished
        futures in."""
        good = _card(agent_id="C-good")
        poison_a = _card(agent_id="C-poison-a")
        poison_b = _card(agent_id="C-poison-b")

        monkeypatch.setattr(execute, "run_card", lambda card, **_kw: _fake_agent_result(card))

        class _FakeBrokenPoolExecutor:
            def submit(self, fn, **kwargs):
                future: Future = Future()
                if kwargs["agent_id"].startswith("C-poison"):
                    future.set_exception(BrokenProcessPool("synthetic worker crash"))
                else:
                    future.set_result(fn(**kwargs))
                return future

        cancel_event = threading.Event()
        log_lines: list[str] = []

        def watch_log(line: str) -> None:
            log_lines.append(line)
            if ": ok " in line:  # a card completed -- cancel, mid-window, exactly as observed
                cancel_event.set()

        runs_dir = tmp_path / "r-broken-pool-cancel" / "results" / "covid" / "runs"
        runs_dir.mkdir(parents=True)

        job = jobs._Job(round_id="r-broken-pool-cancel", cards=(), windows=(), output_root=tmp_path)
        mandate = jobs._load_mandate()
        counts = execute._Counts()
        errors: list[str] = []

        start, end, _regime = jobs.WINDOWS["covid"]
        cancelled, pool_broke = execute._run_window_in_pool(
            executor=_FakeBrokenPoolExecutor(),  # type: ignore[arg-type]
            job=job,
            window="covid",
            cards=[good, poison_a, poison_b],
            runs_dir=runs_dir,
            settings=settings,
            mandate=mandate,
            start=start,
            end=end,
            cancel_requested=cancel_event.is_set,
            counts=counts,
            errors=errors,
            emit=watch_log,
        )

        assert pool_broke is True
        assert cancel_event.is_set(), "the test's own premise: cancellation fired during the window"
        assert counts.completed == 3, (
            "every card was submitted before the cancel -- a dead worker may not turn an "
            "already-submitted card into a never-attempted one"
        )
        assert counts.failed == 0
        assert errors == []
        assert cancelled is False, (
            "nothing was skipped *because of* the cancel -- this window ran in full, and it is "
            "run_generation's between-window check that turns the pending cancel into "
            "status='cancelled'"
        )

        for agent_id in ("C-good", "C-poison-a", "C-poison-b"):
            run_path = runs_dir / f"{jobs._TAG}-{agent_id}.json"
            assert run_path.is_file(), f"expected a run file for {agent_id} at {run_path}"

        assert len(job.results) == 3
        assert sorted(r.agent_id for r in job.results) == ["C-good", "C-poison-a", "C-poison-b"]
        assert not any("cancelled before" in line for line in log_lines), (
            "no already-submitted card may be logged as skipped-for-cancellation"
        )
        assert any("must still finish" in line for line in log_lines), (
            "finishing them under a pending cancel is a decision worth a log line, not a silence"
        )
