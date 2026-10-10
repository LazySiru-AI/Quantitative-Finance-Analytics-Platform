"""Tests for `app.tournament.results.ScoredRun` -- the normalised reader that lets the round scorer
read allocation and ladder run files, not just stock-picking ones, without ever being able to
compute `adjusted_excess` from an exposure figure that does not mean what that formula assumes.

Three things this file exists to prove, each tied to a specific hazard named in the task brief:

1. **Parsing dispatches on the `"card"` payload's own shape, never the filename.** Every run file
   under every round on disk is prefixed `r1-` regardless of which round produced it (see
   `results.py`'s module docstring) -- a reader that trusted the filename for anything would already
   be wrong today. `TestDispatchIsOnPayloadShapeNotFilename` builds a file whose name says one card
   shape and whose payload says another, and asserts the payload wins.

2. **An `invested-value` run has no path to `adjusted_excess` at all.** Not a `None`, not a
   fallback, not `capital_exposure=1.0` substituted quietly -- `ScoredRun.adjusted_excess()` raises.
   `TestInvestedValueRunHasNoAdjustedExcess` covers both allocation and ladder shapes, and includes
   the specific trap a mid-task correction identified: an allocation run with `capital_exposure=None`
   and `exposure=1.0` (session presence, near 1.0 for a book that is always fully invested) must
   still raise rather than let `exposure` be silently substituted the way `results._adjusted_excess`
   already does, safely, for a `StrategyCard` run that took no trades.

3. **An `entry-notional` run's `adjusted_excess` is pinned to a real file on disk, not a fixture.**
   `TestEntryNotionalPinnedToRealRunFile` reads an actual run file from
   `data/rounds/r14-2026-08/results/`, computes the expected figure two independent ways (a
   hand-derived literal, and `results._adjusted_excess` -- the function this program already ships
   and already runs in production against this exact file), and requires `ScoredRun.adjusted_excess()`
   to agree with both.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.tournament import results
from app.tournament.allocation import AllocationCard, AllocationResult, Sleeve
from app.tournament.ladder import LadderCard, LadderResult, Rung
from app.tournament.models import AgentResult, Discipline, StrategyCard

# ---------------------------------------------------------------------------
# Fixture builders -- one minimal, valid card + result per shape
# ---------------------------------------------------------------------------


def _stock_picking_card(agent_id: str = "picker-1") -> StrategyCard:
    return StrategyCard(
        agent_id=agent_id,
        display_name="Picker One",
        discipline=Discipline.TREND,
        thesis="Momentum persists for several sessions after a volume-confirmed breakout.",
        universe=("AAPL",),
        entry="close > sma(20)",
        exit="close < sma(20)",
        max_positions=4,
        position_pct=Decimal("0.25"),
        designed_through=dt.date(2026, 2, 10),
    )


def _stock_picking_result(
    agent_id: str = "picker-1",
    *,
    capital_exposure: float | None = 0.4,
    exposure: float | None = 0.8,
    benchmark_return: Decimal | None = Decimal("0.05"),
) -> AgentResult:
    return AgentResult(
        card=_stock_picking_card(agent_id),
        sessions=100,
        starting_equity=Decimal("10000.00"),
        ending_equity=Decimal("11000.00"),
        total_return=Decimal("0.10"),
        max_drawdown=Decimal("0.05"),
        capital_exposure=capital_exposure,
        exposure=exposure,
        benchmark_return=benchmark_return,
    )


def _allocation_card(agent_id: str = "alloc-1") -> AllocationCard:
    return AllocationCard(
        agent_id=agent_id,
        display_name="Alloc One",
        thesis="A constant-weight two-sleeve book rebalanced back to target on drift.",
        sleeves=(
            Sleeve(symbol="QLD", target_weight=Decimal("0.60")),
            Sleeve(symbol="SCHD", target_weight=Decimal("0.40")),
        ),
        band_pct=Decimal("0.05"),
        designed_through=dt.date(2026, 2, 10),
    )


def _allocation_result(
    agent_id: str = "alloc-1",
    *,
    capital_exposure: float | None = 0.97,
    exposure: float | None = 1.0,
    benchmark_return: Decimal | None = Decimal("0.08"),
) -> AllocationResult:
    return AllocationResult(
        card=_allocation_card(agent_id),
        sessions=100,
        starting_equity=Decimal("10000.00"),
        ending_equity=Decimal("12000.00"),
        total_return=Decimal("0.20"),
        max_drawdown=Decimal("0.10"),
        capital_exposure=capital_exposure,
        exposure=exposure,
        benchmark_return=benchmark_return,
    )


def _ladder_card(agent_id: str = "ladder-1") -> LadderCard:
    return LadderCard(
        agent_id=agent_id,
        display_name="Ladder One",
        thesis="Rotate into a leveraged sleeve as SPY's drawdown deepens, and back out on recovery.",
        signal_symbol="SPY",
        defensive_symbol="SCHD",
        bond_symbol="IEF",
        leveraged_symbol="QLD",
        base_defensive_weight=Decimal("0.60"),
        base_bond_weight=Decimal("0.40"),
        rungs=(Rung(drawdown=Decimal("-0.10"), leveraged_weight=Decimal("0.20")),),
        confirm_ma=5,
        ath_haircut=Decimal("0.5"),
        recovery_gain=Decimal("0.10"),
        recovery_sessions=60,
        designed_through=dt.date(2026, 2, 10),
    )


def _ladder_result(
    agent_id: str = "ladder-1",
    *,
    capital_exposure: float | None = 0.95,
    exposure: float | None = 1.0,
    benchmark_return: Decimal | None = Decimal("0.06"),
) -> LadderResult:
    return LadderResult(
        card=_ladder_card(agent_id),
        sessions=100,
        starting_equity=Decimal("10000.00"),
        ending_equity=Decimal("10800.00"),
        total_return=Decimal("0.08"),
        max_drawdown=Decimal("0.04"),
        capital_exposure=capital_exposure,
        exposure=exposure,
        benchmark_return=benchmark_return,
    )


# ---------------------------------------------------------------------------
# 1. Each of the three shapes parses with the right exposure_basis
# ---------------------------------------------------------------------------


class TestEachShapeParsesWithTheRightBasis:
    def test_stock_picking_card_is_entry_notional(self) -> None:
        raw = _stock_picking_result().model_dump_json()
        run = results.parse_scored_run(raw, window="gfc")
        assert run.card_shape == "stock-picking"
        assert run.exposure_basis == "entry-notional"
        assert run.agent_id == "picker-1"
        assert run.display_name == "Picker One"

    def test_allocation_card_is_invested_value(self) -> None:
        raw = _allocation_result().model_dump_json()
        run = results.parse_scored_run(raw, window="gfc")
        assert run.card_shape == "allocation"
        assert run.exposure_basis == "invested-value"
        assert run.agent_id == "alloc-1"

    def test_ladder_card_is_invested_value(self) -> None:
        raw = _ladder_result().model_dump_json()
        run = results.parse_scored_run(raw, window="gfc")
        assert run.card_shape == "ladder"
        assert run.exposure_basis == "invested-value"
        assert run.agent_id == "ladder-1"

    def test_an_unrecognised_card_shape_raises_rather_than_guessing(self) -> None:
        raw = json.dumps({"card": {"agent_id": "mystery", "some_other_field": 1}})
        with pytest.raises(results.UnrecognisedCardShapeError):
            results.parse_scored_run(raw, window="gfc")


# ---------------------------------------------------------------------------
# 2. An invested-value run has no adjusted_excess at all
# ---------------------------------------------------------------------------


class TestInvestedValueRunHasNoAdjustedExcess:
    def test_allocation_run_raises_rather_than_returning_a_number(self) -> None:
        raw = _allocation_result().model_dump_json()
        run = results.parse_scored_run(raw, window="gfc")
        with pytest.raises(results.ExposureBasisError) as exc_info:
            run.adjusted_excess()
        assert exc_info.value.agent_id == "alloc-1"
        assert exc_info.value.exposure_basis == "invested-value"

    def test_ladder_run_raises_rather_than_returning_a_number(self) -> None:
        raw = _ladder_result().model_dump_json()
        run = results.parse_scored_run(raw, window="gfc")
        with pytest.raises(results.ExposureBasisError):
            run.adjusted_excess()

    def test_invested_value_run_is_still_scored_on_plain_excess(self) -> None:
        """`excess` carries no claim about capital at risk, so nothing about the exposure-basis
        mismatch corrupts it -- it must still be computed and correct."""
        raw = _allocation_result(benchmark_return=Decimal("0.08")).model_dump_json()
        run = results.parse_scored_run(raw, window="gfc")
        # corrected_return = 12000/10000 - 1 = 0.20; excess = 0.20 - 0.08 = 0.12
        assert run.corrected_return == Decimal("0.20")
        assert run.excess == Decimal("0.12")

    def test_a_none_capital_exposure_does_not_fall_through_to_session_presence_exposure(
        self,
    ) -> None:
        """The trap: `capital_exposure=None` with `exposure=1.0` (session presence -- every sleeve
        of an allocation book is open every session, so this sits near 1.0 regardless of the
        strategy). `results._adjusted_excess` substitutes `exposure` for a `None` `capital_exposure`,
        and that substitution is safe *only* for a `StrategyCard` run that took no trades, where the
        two figures coincide at zero. It is not safe here, and `ScoredRun.adjusted_excess` must not
        take that path at all -- the gate is `exposure_basis`, decided before either field is read,
        not "is capital_exposure present and small enough to trust".
        """
        raw = _allocation_result(capital_exposure=None, exposure=1.0).model_dump_json()
        run = results.parse_scored_run(raw, window="gfc")
        assert run.capital_exposure is None
        with pytest.raises(results.ExposureBasisError):
            run.adjusted_excess()

    def test_a_none_capital_exposure_does_not_fall_through_for_a_ladder_run_either(self) -> None:
        raw = _ladder_result(capital_exposure=None, exposure=1.0).model_dump_json()
        run = results.parse_scored_run(raw, window="gfc")
        assert run.capital_exposure is None
        with pytest.raises(results.ExposureBasisError):
            run.adjusted_excess()


# ---------------------------------------------------------------------------
# 3. An entry-notional run is pinned to a real run file on disk
# ---------------------------------------------------------------------------

_R14_ROOT = Path(__file__).resolve().parents[1] / "data" / "rounds" / "r14-2026-08"
_R14_SAMPLE_RUN = _R14_ROOT / "results" / "bear-2022" / "runs" / "r1-A-rotation.json"


@pytest.mark.skipif(not _R14_SAMPLE_RUN.is_file(), reason="r14 sample run file not present")
class TestEntryNotionalPinnedToRealRunFile:
    """Anchored to `data/rounds/r14-2026-08/results/bear-2022/runs/r1-A-rotation.json` -- a real,
    already-committed round-14 run file, not a fixture that could drift with the code. The expected
    figure is asserted two ways: against a hand-derived Decimal literal (independent of any code
    path), and against `results._adjusted_excess`/`results.compute_window` -- the function this
    program already ships and already runs against this exact file in production, so a divergence
    here would mean `ScoredRun`'s normalisation silently changed what today's leaderboard reports.
    """

    def test_corrected_return_and_excess_match_the_real_file(self) -> None:
        raw = _R14_SAMPLE_RUN.read_text(encoding="utf-8")
        run = results.parse_scored_run(raw, window="bear-2022")
        assert run.card_shape == "stock-picking"
        assert run.exposure_basis == "entry-notional"
        # Hand-derived from the file's own starting_equity/ending_equity: 6672.54/10000.00 - 1.
        assert run.corrected_return == Decimal("-0.332746")
        # Hand-derived: corrected_return - benchmark_return.
        assert run.excess == Decimal("-0.332746") - Decimal(
            "-0.2513961788788578626915809364"
        )

    def test_adjusted_excess_matches_a_hand_derived_literal(self) -> None:
        raw = _R14_SAMPLE_RUN.read_text(encoding="utf-8")
        run = results.parse_scored_run(raw, window="bear-2022")
        # Hand-derived: corrected_return - capital_exposure * benchmark_return, using the file's own
        # capital_exposure (0.2334074642857143) and benchmark_return, computed independently of
        # `results._adjusted_excess` and pasted here as a literal so a shared bug in both code paths
        # could not mask itself.
        expected = Decimal("-0.2740682553567679397816502204")
        assert run.adjusted_excess() == expected

    def test_adjusted_excess_matches_todays_existing_computation_exactly(self) -> None:
        """The direct regression check: `ScoredRun` must produce exactly what
        `results._adjusted_excess`/`compute_window` already compute for this file today, not an
        approximation of it."""
        raw = _R14_SAMPLE_RUN.read_text(encoding="utf-8")
        agent_result = AgentResult.model_validate_json(raw)
        expected = results._adjusted_excess(agent_result)
        expected_via_compute_window = results.compute_window(agent_result, "bear-2022").adjusted_excess

        run = results.parse_scored_run(raw, window="bear-2022")
        assert run.adjusted_excess() == expected
        assert run.adjusted_excess() == expected_via_compute_window


# ---------------------------------------------------------------------------
# 4. Dispatch is on payload shape, never the filename
# ---------------------------------------------------------------------------


class TestDispatchIsOnPayloadShapeNotFilename:
    def test_a_misleadingly_named_file_is_parsed_by_its_payload(self, tmp_path: Path) -> None:
        """A file named as though it were a stock-picking run (`r1-picker-1.json`) but whose payload
        is actually a ladder result. The module docstring's own real-data note establishes that a run
        file's name cannot be trusted to identify anything about its contents (every file under every
        round is prefixed `r1-` regardless of which round produced it); this test extends that same
        distrust to the card *shape*, not just the round it belongs to.
        """
        misleading_path = tmp_path / "r1-picker-1.json"
        misleading_path.write_text(_ladder_result(agent_id="picker-1").model_dump_json(), encoding="utf-8")

        run = results.load_scored_run_file(misleading_path, window="gfc")
        assert run.card_shape == "ladder"
        assert run.exposure_basis == "invested-value"
        assert run.agent_id == "picker-1"

    def test_load_round_scored_runs_reads_mixed_shapes_from_one_round(self, tmp_path: Path) -> None:
        """A round directory holding one stock-picking run, one allocation run and one ladder run,
        all under the same window's `runs/` directory -- the shape it needs to `strategy-program`'s
        `data/rounds/r15-2026-08/` will end up in. `load_round_results` can read none of the last two;
        `load_round_scored_runs` must read all three.
        """
        runs_dir = tmp_path / "r15-2026-08" / "results" / "gfc" / "runs"
        runs_dir.mkdir(parents=True)
        (runs_dir / "r1-picker-1.json").write_text(
            _stock_picking_result(agent_id="picker-1").model_dump_json(), encoding="utf-8"
        )
        (runs_dir / "r1-alloc-1.json").write_text(
            _allocation_result(agent_id="alloc-1").model_dump_json(), encoding="utf-8"
        )
        (runs_dir / "r1-ladder-1.json").write_text(
            _ladder_result(agent_id="ladder-1").model_dump_json(), encoding="utf-8"
        )

        by_window = results.load_round_scored_runs("r15-2026-08", rounds_root=tmp_path)
        agents = by_window["gfc"]
        assert set(agents) == {"picker-1", "alloc-1", "ladder-1"}
        assert agents["picker-1"].exposure_basis == "entry-notional"
        assert agents["alloc-1"].exposure_basis == "invested-value"
        assert agents["ladder-1"].exposure_basis == "invested-value"
        # And the invested-value ones still refuse adjusted_excess when asked.
        with pytest.raises(results.ExposureBasisError):
            agents["alloc-1"].adjusted_excess()
        with pytest.raises(results.ExposureBasisError):
            agents["ladder-1"].adjusted_excess()

    def test_load_round_scored_runs_raises_round_not_found_exactly_like_load_round_results(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(results.RoundNotFoundError):
            results.load_round_scored_runs("no-such-round", rounds_root=tmp_path)


# ---------------------------------------------------------------------------
# 5. build_leaderboard is unchanged for stock-picking cards
# ---------------------------------------------------------------------------


class TestBuildLeaderboardIsUnchangedForStockPickingCards:
    """`build_leaderboard` is not touched by this task -- it still calls `load_round_results`, which
    still validates only `AgentResult`. These are light regression guards on top of the full existing
    suite (`tests/test_competition_api.py` pins the HTTP contract against real round data); the
    determining evidence is that the whole existing suite still passes unchanged.
    """

    def test_a_tmp_round_with_only_stock_picking_cards_still_builds(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "r1-2026-08" / "results" / "gfc" / "runs"
        runs_dir.mkdir(parents=True)
        (runs_dir / "r1-picker-1.json").write_text(
            _stock_picking_result(agent_id="picker-1", benchmark_return=Decimal("0.05")).model_dump_json(),
            encoding="utf-8",
        )

        board = results.build_leaderboard("r1-2026-08", rounds_root=tmp_path)
        assert board.round_id == "r1-2026-08"
        assert board.purpose == "trading"
        assert board.scoring_basis == "adjusted_excess"
        assert [row.agent_id for row in board.rows] == ["picker-1"]

    def test_real_round_leaderboard_still_reports_adjusted_excess_as_the_trading_basis(self) -> None:
        if not (Path("data") / "rounds" / "r2-2026-08" / "results").is_dir():
            pytest.skip("data/rounds/r2-2026-08 not present")
        board = results.build_leaderboard("r2-2026-08")
        assert board.scoring_basis == "adjusted_excess"
        assert board.rows, "r2-2026-08 is expected to have scored rows"


class TestAgentDetailSurvivesNonStockPickingCards:
    """`build_agent_detail` against a round holding allocation and ladder cards.

    Found by a UAT button sweep on 2026-08-29, not by a test: opening any card on round 15's Agent
    tab returned a bare `500`. The cause is stated plainly in `load_round_scored_runs`' own docstring
    -- `load_round_results` "cannot read [allocation and ladder run files] at all" and still backs
    `build_agent_detail` -- so the limitation was known and its user-visible consequence was not. It
    validates *every* run file in the round as an `AgentResult`, so one unreadable file raises out of
    the loader and takes the whole request with it, however many readable ones sit beside it.

    These tests use the committed `r15-2026-08` rather than a fixture, deliberately: the defect is a
    statement about what that round's real files do to this reader, and a hand-built fixture would
    only prove the reader agrees with my idea of the shapes.
    """

    ROUND = "r15-2026-08"

    def test_every_card_in_round_15_reports_its_shape_rather_than_raising(self) -> None:
        board = results.build_leaderboard(self.ROUND)
        agent_ids = [row.agent_id for row in board.rows]
        assert agent_ids, "round 15's leaderboard is empty; this test has nothing to check"

        for agent_id in agent_ids:
            with pytest.raises(results.AgentShapeUnsupportedError) as excinfo:
                results.build_agent_detail(self.ROUND, agent_id)
            # The shape is named, so the message says which reader is missing rather than only that
            # something went wrong.
            assert excinfo.value.shape in ("allocation", "ladder")
            assert excinfo.value.agent_id == agent_id

    def test_an_agent_that_truly_did_not_run_is_still_a_not_found(self) -> None:
        """The two absences must stay distinguishable. Collapsing "ran in a shape I cannot render"
        into "did not run" would deny that round 15 measured these cards at all -- which was the
        entire point of that round."""
        with pytest.raises(results.AgentNotFoundError):
            results.build_agent_detail(self.ROUND, "no-such-agent-anywhere")

    def test_a_stock_picking_round_is_untouched(self) -> None:
        """The regression guard. `r14-2026-08` holds only stock-picking cards and went through the
        old loader; it must still open exactly as before."""
        board = results.build_leaderboard("r14-2026-08")
        first = board.rows[0].agent_id
        detail = results.build_agent_detail("r14-2026-08", first)
        assert detail.agent_id == first
        assert detail.windows, "expected at least one window of metrics"
        assert detail.card.agent_id == first

    def test_the_leaderboard_was_never_affected(self) -> None:
        """Stated as a test because it is what made the defect hard to see: the round ranked fine the
        whole time, so the Agent tab's 500 looked like a per-card data problem rather than a reader
        that could not see any of the round."""
        board = results.build_leaderboard(self.ROUND)
        assert len(board.rows) >= 1
