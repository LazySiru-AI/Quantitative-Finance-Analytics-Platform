"""Tests for `strategy-program/tools/score.py`'s ranking matrix, which round 4 made a parameter.

The defect this file exists to prevent is specific and was live until round 4 was scored. Every gate
computation in `score.py` intersected the windows a card ran against the module constant
`MAIN_WINDOW_TAGS` -- the eight regimes rounds 2 and 3 used. Round 4's matrix shares **none** of those
eight (`PROTOCOL.md` Sec 6(a): a frozen card on a deterministic engine recomputes, rather than
resamples, a window it has already run, so a confirmation round has to bring new windows). Scoring
round 4 against the round-2 constant therefore gave every card `run_tags == []`, which is not an
error anywhere in the pipeline -- "ran too few main windows" is an ordinary unranked verdict -- so the
scorer would have printed a **complete, well-formed, empty leaderboard**. That is the worst available
failure mode for a scorer, and `test_r2_matrix_ranks_nothing_in_an_r4_tree` pins it directly.

`score.py` lives under a hyphenated directory, which is not a legal Python package name, so it is
loaded by file path (the same mechanism, and the same reason, as `tests/test_portfolio_tool.py`).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from app.config import REPO_ROOT
from app.tournament.models import AgentResult, Discipline, RealisedTrade, StrategyCard

_SCORE_PATH = REPO_ROOT / "strategy-program" / "tools" / "score.py"
_spec = importlib.util.spec_from_file_location("strategy_program_tools_score", _SCORE_PATH)
assert _spec is not None and _spec.loader is not None
score: ModuleType = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = score
_spec.loader.exec_module(score)


_CARD_DEFAULTS = dict(
    discipline=Discipline.MOMENTUM,
    thesis="A synthetic card used only to exercise the ranking gate, not a real strategy.",
    universe=("AAPL",),
    entry="close > sma(50)",
    exit="close < sma(50)",
    stop_loss_pct=Decimal("0.10"),
    take_profit_pct=None,
    max_hold_days=90,
    max_positions=1,
    position_pct=Decimal("0.50"),
    designed_through=dt.date(2026, 2, 13),
)


_TRADE = RealisedTrade(
    symbol="AAPL",
    entry_date=dt.date(2024, 1, 2),
    entry_price=Decimal("100"),
    exit_date=dt.date(2024, 1, 12),
    exit_price=Decimal("105"),
    quantity=Decimal("10"),
    exit_reason="signal",
    pnl=Decimal("50"),
    return_pct=Decimal("0.05"),
    bars_held=8,
)


def _result(
    agent_id: str,
    *,
    ret: str,
    sessions: int = 10,
    benchmark_return: str | None = "0",
    capital_exposure: float | None = 0.5,
) -> AgentResult:
    """One (card, window) result with a known return against a flat benchmark, and one trade -- the
    gate also requires `total_trades > 0`, and a card with no trades is unranked for a different
    reason than the one under test here.

    `sessions`, `benchmark_return` and `capital_exposure` default to the values every pre-existing
    test in this file already relies on (10, "0", 0.5), so every call site written before round 5's
    annualized-metric tests is unaffected; the new tests below pass their own `sessions` and
    `benchmark_return` to exercise `window_years` and the annualized functions, which the flat
    defaults were never chosen to test."""
    card = StrategyCard(agent_id=agent_id, display_name=agent_id, **_CARD_DEFAULTS)
    starting = Decimal("10000")
    return AgentResult(
        card=card,
        sessions=sessions,
        starting_equity=starting,
        ending_equity=starting * (Decimal(1) + Decimal(ret)),
        # Deliberately implausible: `score.corrected_return` recomputes from equity (DEFECTS.md D1),
        # so a reader of this field instead of that function fails loudly rather than by coincidence.
        total_return=Decimal("999"),
        max_drawdown=Decimal("-0.01"),
        exposure=0.5,
        capital_exposure=capital_exposure,
        benchmark_return=None if benchmark_return is None else Decimal(benchmark_return),
        # The gate is `enough windows AND total_trades > 0`; a card with no trades is unranked
        # for a reason that has nothing to do with the matrix, which would make every assertion
        # below pass for the wrong reason.
        trades=(_TRADE,),
    )


def _run_results(agent_id: str, tags: list[str]) -> dict[str, AgentResult]:
    return {tag: _result(agent_id, ret="0.05") for tag in tags}


class TestMatrixDefinitions:
    def test_r4_shares_no_window_with_r2(self) -> None:
        """The whole reason the matrix had to become a parameter. If a future round reuses a window
        this assertion fails, and the reuse needs a PROTOCOL.md Sec 6(a) justification before the
        assertion is relaxed -- not the other way round."""
        assert not set(score.R2_MATRIX.tags) & set(score.R4_MATRIX.tags)

    def test_gates_hold_the_same_proportion(self) -> None:
        """Round 1 was 3-of-5, round 2 5-of-8, round 4 4-of-6 -- all ~60-67%. The gate is meant to
        bind equally hard as the matrix grows, not to drift with it."""
        for matrix in (score.R2_MATRIX, score.R4_MATRIX):
            assert 0.6 <= matrix.min_ranked / len(matrix.tags) <= 0.7

    def test_default_is_still_round_twos_matrix(self) -> None:
        """Rounds 2 and 3 are published against 5-of-8 and have to stay reproducible, so every
        signature that gained a `matrix` argument defaults to the constants those rounds used."""
        assert score.R2_MATRIX.tags == score.MAIN_WINDOW_TAGS
        assert score.R2_MATRIX.min_ranked == score.MIN_RANKED_MAIN_WINDOWS


class TestDetectMatrix:
    def test_detects_each_matrix_from_its_own_tags(self) -> None:
        assert score.detect_matrix(list(score.R4_MATRIX.tags)) is score.R4_MATRIX
        assert score.detect_matrix(list(score.R2_MATRIX.tags)) is score.R2_MATRIX

    def test_detects_from_a_partial_set(self) -> None:
        """A results tree can legitimately hold fewer windows than its matrix names -- a run in
        progress, or a matrix a card is only partly eligible for."""
        assert score.detect_matrix(["banks-2023"]) is score.R4_MATRIX
        assert score.detect_matrix(["gfc", "covid"]) is score.R2_MATRIX

    @pytest.mark.parametrize(
        "tags",
        [
            pytest.param([], id="empty"),
            pytest.param(["13f-legal"], id="only-a-special-window"),
            pytest.param(["gfc", "banks-2023"], id="spans-both"),
        ],
    )
    def test_returns_none_rather_than_guessing(self, tags: list[str]) -> None:
        """`None` is what makes the CLI print an error and exit 1. Guessing here would reintroduce
        exactly the silent-empty-leaderboard failure the parameter exists to prevent."""
        assert score.detect_matrix(tags) is None


class TestGateFollowsTheMatrix:
    def test_r2_matrix_ranks_nothing_in_an_r4_tree(self) -> None:
        """The defect, pinned. Four round-4 windows is a clear pass under round 4's 4-of-6 gate, and
        under the round-2 matrix the same card is silently unranked -- with no error raised anywhere,
        which is why this was worth a parameter rather than a comment."""
        tags = ["oil-2014", "volmageddon-2018", "inflation-2021", "banks-2023"]
        runs = _run_results("card", tags)
        per_window = {tag: score.WindowCell(status="run") for tag in tags}

        wrong = score.aggregate_card("card", None, per_window, runs, None, matrix=score.R2_MATRIX)
        assert wrong.n_windows_run == 0
        assert wrong.ranked is False
        assert wrong.median_adjusted_excess is None

        right = score.aggregate_card("card", None, per_window, runs, None, matrix=score.R4_MATRIX)
        assert right.n_windows_run == 4
        assert right.ranked is True
        assert right.median_adjusted_excess == Decimal("0.05")

    def test_three_r4_windows_is_one_short_of_the_gate(self) -> None:
        """4-of-6 is the gate, so 3 must fail -- the boundary, not just the happy path."""
        tags = ["oil-2014", "inflation-2021", "banks-2023"]
        runs = _run_results("card", tags)
        per_window = {tag: score.WindowCell(status="run") for tag in tags}

        card = score.aggregate_card("card", None, per_window, runs, None, matrix=score.R4_MATRIX)
        assert card.n_windows_run == 3
        assert card.ranked is False

    def test_r2_gate_is_unchanged_at_five_of_eight(self) -> None:
        """The regression guard for rounds 2 and 3: five round-2 windows ranks, four does not."""
        five = ["gfc", "covid", "bear-2022", "q4-2018", "bull-2024"]
        four = five[:-1]
        for tags, expected in ((five, True), (four, False)):
            runs = _run_results("card", tags)
            per_window = {tag: score.WindowCell(status="run") for tag in tags}
            card = score.aggregate_card("card", None, per_window, runs, None)
            assert card.ranked is expected, tags


class TestDiscoveryOrdersByTheGivenMatrix:
    def test_window_directories_come_back_in_matrix_order(self, tmp_path) -> None:
        """`_discover_window_tags` orders main windows canonically then anything else
        alphabetically, so a report's columns read the same way every time. Under the wrong matrix
        every round-4 window falls into the "anything else" bucket and sorts alphabetically -- which
        is not wrong-looking enough to notice by eye, the same reason the empty leaderboard was not."""
        for tag in ("banks-2023", "oil-2014", "recovery-2009", "13f-legal"):
            (tmp_path / tag / "runs").mkdir(parents=True)

        assert score._discover_window_tags(tmp_path, matrix=score.R4_MATRIX) == [
            "recovery-2009",
            "oil-2014",
            "banks-2023",
            "13f-legal",
        ]
        assert score._discover_window_tags(tmp_path, matrix=score.R2_MATRIX) == [
            "13f-legal",
            "banks-2023",
            "oil-2014",
            "recovery-2009",
        ]


#: `Decimal` round-trips through `float` for the annualized functions' fractional root (see
#: `annualized_return`'s docstring) -- the tests below check against hand-computed values to this
#: tolerance rather than asserting exact equality, which is the whole point of documenting that the
#: annualized path is inexact and the non-annualized path is not.
_TOLERANCE = Decimal("0.000001")


class TestWindowYears:
    """`window_years` is `sessions / 252` -- see its docstring for why no calendar-date source is
    available to prefer instead (the per-card run file `score.py` loads has no window dates of its
    own; only the per-window `tournament.json` does, and this module never reads that file)."""

    def test_matches_round_fives_own_session_counts(self) -> None:
        """Sanity-check against `data/rounds/r5-2026-08/windows.json`'s real session counts for each
        horizon: every one of them lands within a few percent of its own horizon label and nowhere
        near a neighbouring one."""
        cases = {
            126: Decimal("0.5"),  # a 6m window, e.g. h6m-1..6 / b6m-1..3
            252: Decimal("1"),  # a 1y window, e.g. h1y-1..6 / b1y-1..3
            756: Decimal("3"),  # a 3y window, e.g. h3y-1/h3y-3
            1260: Decimal("5"),  # a 5y window, e.g. h5y-1
            2520: Decimal("10"),  # a clean 10y window for the hand-checked arithmetic tests below
        }
        for sessions, expected_years in cases.items():
            result = _result("card", ret="0.01", sessions=sessions)
            assert score.window_years(result) == expected_years

    def test_none_for_zero_sessions(self) -> None:
        """Zero sessions is not a zero-year window -- it is an unmeasurable one (see the module
        docstring's rule that a missing quantity is never rendered as zero)."""
        result = _result("card", ret="0.01", sessions=0)
        assert score.window_years(result) is None


class TestAnnualizedArithmeticHandChecked:
    """The arithmetic, checked against hand-computed numbers -- not against whatever the code
    happens to return, which would let a sign error or an inverted exponent pass silently."""

    def test_ten_year_window_hand_checked(self) -> None:
        """A 10-year window (2520 sessions = 252 * 10, an exact `window_years` of 10) with a total
        return of +100% annualizes to `2 ** 0.1 - 1 = 7.177%`."""
        result = _result("card", ret="1.00", sessions=2520, benchmark_return="1.00")
        expected = Decimal(str(2**0.1 - 1))
        assert abs(score.annualized_return(result) - expected) < _TOLERANCE
        # The benchmark side uses the identical mechanism (`annualized_benchmark`), on the same
        # +100%-over-10-years input -- it must agree with the return side to the same tolerance.
        assert abs(score.annualized_benchmark(result) - expected) < _TOLERANCE

    def test_six_month_window_hand_checked(self) -> None:
        """A 6-month window (126 sessions, `window_years` of 0.5) with a total return of +6%
        annualizes to `1.06 ** 2 - 1 = 12.36%`."""
        result = _result("card", ret="0.06", sessions=126, benchmark_return="0.06")
        expected = Decimal(str(1.06**2 - 1))
        assert abs(score.annualized_return(result) - expected) < _TOLERANCE
        assert abs(score.annualized_benchmark(result) - expected) < _TOLERANCE

    def test_annualized_adjusted_excess_hand_checked(self) -> None:
        """`annualized_adjusted_excess = annualized_return - capital_exposure * annualized_benchmark`,
        with a 10-year, +100%-return, +50%-benchmark, 50%-exposure card: annualized_return is
        `2 ** 0.1 - 1`, annualized_benchmark is `1.5 ** 0.1 - 1`, and the exposure-weighted difference
        is computed by hand and compared, not re-derived from the function under test."""
        result = _result(
            "card", ret="1.00", sessions=2520, benchmark_return="0.50", capital_exposure=0.5
        )
        ann_return = Decimal(str(2**0.1 - 1))
        ann_bench = Decimal(str(1.5**0.1 - 1))
        expected = ann_return - Decimal("0.5") * ann_bench
        assert abs(score.annualized_adjusted_excess(result) - expected) < _TOLERANCE


class TestAnnualizedComparability:
    """The defect this shard exists to prevent: without annualizing, a 10-year window's
    `adjusted_excess` and a 6-month window's are not the same unit, so a card measured on one and a
    card measured on the other cannot be compared on the raw figure even when they performed
    identically well per year."""

    def test_identical_annualized_performance_across_horizons(self) -> None:
        # Card A: a 10-year window (2520 sessions) with a +100% total return: annualizes to
        # `2 ** 0.1 - 1`.
        ann_target = 2**0.1 - 1
        card_a = _result("a", ret="1.00", sessions=2520, benchmark_return="0")

        # Card B: a 6-month window (126 sessions) whose *raw* total return is chosen so that it
        # annualizes to the exact same per-year rate as card A: `(1 + ann_target) ** 0.5 - 1`. Its raw
        # total return (~3.52%) is nothing like card A's (+100%) -- that gap is the whole defect.
        ret_b = (1 + ann_target) ** 0.5 - 1
        card_b = _result("b", ret=str(ret_b), sessions=126, benchmark_return="0")

        # Wildly different on the raw metric -- exactly the incomparability the module docstring
        # warns a naive cross-horizon median would produce.
        raw_a = score.adjusted_excess(card_a)
        raw_b = score.adjusted_excess(card_b)
        assert raw_a is not None and raw_b is not None
        assert abs(raw_a - raw_b) > Decimal("0.5")

        # Equal -- to a tight tolerance -- on the annualized metric, because the two cards were
        # constructed to perform identically per year regardless of how long each window was.
        ann_a = score.annualized_adjusted_excess(card_a)
        ann_b = score.annualized_adjusted_excess(card_b)
        assert ann_a is not None and ann_b is not None
        assert abs(ann_a - ann_b) < _TOLERANCE


class TestAnnualizedDegenerateCases:
    """`None`, never raised, never a substituted zero -- matching every other unmeasurable metric in
    this file."""

    def test_zero_sessions(self) -> None:
        result = _result("card", ret="0.05", sessions=0)
        assert score.window_years(result) is None
        assert score.annualized_return(result) is None
        assert score.annualized_benchmark(result) is None
        assert score.annualized_adjusted_excess(result) is None

    def test_total_wipeout_return_has_no_real_root(self) -> None:
        """A total return of exactly -100% or worse leaves `1 + corrected_return <= 0`, which has no
        real-valued fractional root."""
        result = _result("card", ret="-1.00", sessions=252, benchmark_return="0")
        assert score.annualized_return(result) is None
        # The benchmark side is unaffected -- only the card's own return wiped out.
        assert score.annualized_benchmark(result) is not None
        assert score.annualized_adjusted_excess(result) is None

    def test_benchmark_wipeout_has_no_real_root(self) -> None:
        result = _result("card", ret="0.05", sessions=252, benchmark_return="-1.50")
        assert score.annualized_return(result) is not None
        assert score.annualized_benchmark(result) is None
        assert score.annualized_adjusted_excess(result) is None

    def test_missing_benchmark_return(self) -> None:
        """An unknown benchmark is not a zero-return one (see `excess`'s docstring) -- `None`
        propagates rather than being treated as `0`."""
        result = _result("card", ret="0.05", sessions=252, benchmark_return=None)
        assert score.annualized_benchmark(result) is None
        assert score.annualized_adjusted_excess(result) is None


class TestR5MatrixDefinitions:
    def test_r5_matrix_has_27_windows(self) -> None:
        assert len(score.R5_MATRIX.tags) == 27
        assert len(score.R5_LADDER_TAGS) == 21
        assert len(score.R5_BEAR_TAGS) == 6
        assert score.R5_MATRIX.tags == score.R5_LADDER_TAGS + score.R5_BEAR_TAGS

    def test_every_r5_tag_has_a_horizon(self) -> None:
        for tag in score.R5_MATRIX.tags:
            assert tag in score.R5_HORIZON, tag
        assert set(score.R5_HORIZON.values()) == set(score.HORIZON_ORDER)

    def test_r5_shares_no_window_with_r2_or_r4(self) -> None:
        """Same reasoning as `TestMatrixDefinitions.test_r4_shares_no_window_with_r2`: round 5 must
        bring windows a frozen card has not already been scored on (`PROTOCOL.md` Sec 6(a))."""
        assert not set(score.R5_MATRIX.tags) & set(score.R2_MATRIX.tags)
        assert not set(score.R5_MATRIX.tags) & set(score.R4_MATRIX.tags)

    def test_r5_defines_a_per_horizon_gate_the_others_do_not(self) -> None:
        assert score.R5_MATRIX.min_ranked_per_horizon == score.MIN_RANKED_PER_HORIZON
        assert score.R2_MATRIX.min_ranked_per_horizon is None
        assert score.R4_MATRIX.min_ranked_per_horizon is None


class TestDetectMatrixIncludesR5:
    def test_detects_r5_from_its_own_tags(self) -> None:
        assert score.detect_matrix(list(score.R5_MATRIX.tags)) is score.R5_MATRIX

    def test_detects_from_a_partial_r5_set(self) -> None:
        assert score.detect_matrix(["h10y-1", "b6m-2"]) is score.R5_MATRIX

    @pytest.mark.parametrize(
        "tags",
        [
            pytest.param(["gfc", "h10y-1"], id="r2-and-r5"),
            pytest.param(["banks-2023", "h6m-1"], id="r4-and-r5"),
        ],
    )
    def test_returns_none_when_tags_span_r5_and_another_matrix(self, tags: list[str]) -> None:
        assert score.detect_matrix(tags) is None


class TestPerHorizonGate:
    """Round 5's gate is *per horizon*, not just per matrix -- a card needs at least
    `MIN_RANKED_PER_HORIZON` (2) run windows within a horizon before that horizon's median is
    reported, because the 10-year horizon has only two windows in the entire matrix."""

    def test_one_window_in_a_horizon_is_below_the_gate(self) -> None:
        tags = ["h10y-1"]
        runs = {t: _result("card", ret="0.05", sessions=2520) for t in tags}
        per_window = {t: score.WindowCell(status="run") for t in tags}
        card = score.aggregate_card("card", None, per_window, runs, None, matrix=score.R5_MATRIX)

        assert "10y" in card.per_horizon_ladder
        horizon = card.per_horizon_ladder["10y"]
        assert horizon.n_windows == 1
        assert horizon.gate_cleared is False
        assert horizon.median_annualized_adjusted_excess is None
        assert horizon.worst_annualized_adjusted_excess is None
        assert horizon.hit_rate is None

    def test_two_windows_in_a_horizon_clears_the_gate(self) -> None:
        tags = ["h10y-1", "h10y-2"]
        runs = {t: _result("card", ret="0.05", sessions=2520) for t in tags}
        per_window = {t: score.WindowCell(status="run") for t in tags}
        card = score.aggregate_card("card", None, per_window, runs, None, matrix=score.R5_MATRIX)

        horizon = card.per_horizon_ladder["10y"]
        assert horizon.n_windows == 2
        assert horizon.gate_cleared is True
        assert horizon.median_annualized_adjusted_excess is not None

    def test_absent_horizon_is_not_a_zero_entry(self) -> None:
        """A horizon the card never ran a window in does not appear in `per_horizon_ladder` at all --
        it is missing, not present with `n_windows=0` -- matching `WindowCell`'s "never a zero for a
        missing thing" rule."""
        tags = ["h1y-1", "h1y-2"]
        runs = {t: _result("card", ret="0.05", sessions=252) for t in tags}
        per_window = {t: score.WindowCell(status="run") for t in tags}
        card = score.aggregate_card("card", None, per_window, runs, None, matrix=score.R5_MATRIX)

        assert "10y" not in card.per_horizon_ladder
        assert "5y" not in card.per_horizon_ladder
        assert "1y" in card.per_horizon_ladder

    def test_ladder_and_bear_arms_are_scored_separately(self) -> None:
        """A 6-month ladder window and a 6-month bear window must never land in the same
        `HorizonScore` -- see `CardScore.per_horizon_ladder`'s docstring for why mixing them back
        together would reintroduce the exact selection effect round 4 was about."""
        tags = ["h6m-1", "h6m-2", "b6m-1", "b6m-2"]
        runs = {t: _result("card", ret="0.05", sessions=126) for t in tags}
        per_window = {t: score.WindowCell(status="run") for t in tags}
        card = score.aggregate_card("card", None, per_window, runs, None, matrix=score.R5_MATRIX)

        assert card.per_horizon_ladder["6m"].n_windows == 2
        assert card.per_horizon_bear["6m"].n_windows == 2
        assert card.per_horizon_ladder["6m"].arm == "ladder"
        assert card.per_horizon_bear["6m"].arm == "bear"


class TestRoundsTwoAndFourStayByteIdentical:
    """Rounds 2-4 are published and must stay reproducible: scoring against `R2_MATRIX` or
    `R4_MATRIX` must produce no horizon table, no annualized columns, and no new JSON keys -- see the
    module docstring's per-matrix requirement."""

    def test_no_horizon_data_is_attached(self) -> None:
        for matrix, tags in (
            (score.R2_MATRIX, ["gfc", "covid"]),
            (score.R4_MATRIX, ["oil-2014", "inflation-2021"]),
        ):
            runs = _run_results("card", tags)
            per_window = {tag: score.WindowCell(status="run") for tag in tags}
            card = score.aggregate_card("card", None, per_window, runs, None, matrix=matrix)
            assert card.per_horizon_ladder == {}, matrix.name
            assert card.per_horizon_bear == {}, matrix.name

    def test_render_markdown_has_no_horizon_section(self) -> None:
        for matrix, tags in (
            (score.R2_MATRIX, ["gfc", "covid", "bear-2022", "q4-2018", "bull-2024"]),
            (
                score.R4_MATRIX,
                ["oil-2014", "volmageddon-2018", "inflation-2021", "banks-2023"],
            ),
        ):
            runs = _run_results("card", tags)
            per_window = {tag: score.WindowCell(status="run") for tag in tags}
            card = score.aggregate_card("card", None, per_window, runs, None, matrix=matrix)
            markdown = score.render_markdown([card], [], tags, matrix=matrix)
            assert "Horizon breakdown" not in markdown, matrix.name
            assert "annualized" not in markdown.lower(), matrix.name

    def test_json_has_no_horizon_keys(self) -> None:
        for matrix, tags in (
            (score.R2_MATRIX, ["gfc", "covid"]),
            (score.R4_MATRIX, ["oil-2014", "inflation-2021"]),
        ):
            runs = _run_results("card", tags)
            per_window = {tag: score.WindowCell(status="run") for tag in tags}
            card = score.aggregate_card("card", None, per_window, runs, None, matrix=matrix)
            payload = score._build_json(
                [card],
                [],
                tags,
                results_root=Path("."),
                round_tag="r1",
                matrix=matrix,
            )
            assert "min_ranked_per_horizon" not in payload, matrix.name
            assert "horizon_order" not in payload, matrix.name
            assert "per_horizon_ladder" not in payload["ranked"][0], matrix.name
            assert "per_horizon_bear" not in payload["ranked"][0], matrix.name


class TestRoundFiveHorizonReport:
    """The horizon table is the entire point of round 5 -- a reader must be able to see whether a
    card's ranking depends on holding period."""

    def test_render_markdown_shows_horizon_table_for_r5(self) -> None:
        tags = list(score.R5_MATRIX.tags)
        runs = {t: _result("card", ret="0.05", sessions=252) for t in tags}
        per_window = {t: score.WindowCell(status="run") for t in tags}
        card = score.aggregate_card("card", None, per_window, runs, None, matrix=score.R5_MATRIX)
        markdown = score.render_markdown([card], [], tags, matrix=score.R5_MATRIX)

        assert "Horizon breakdown" in markdown
        assert "Ladder arm" in markdown
        assert "Bear arm" in markdown
        for horizon in score.HORIZON_ORDER:
            assert horizon in markdown

    def test_json_includes_horizon_breakdown_for_r5(self) -> None:
        tags = list(score.R5_MATRIX.tags)
        runs = {t: _result("card", ret="0.05", sessions=252) for t in tags}
        per_window = {t: score.WindowCell(status="run") for t in tags}
        card = score.aggregate_card("card", None, per_window, runs, None, matrix=score.R5_MATRIX)
        payload = score._build_json(
            [card],
            [],
            tags,
            results_root=Path("."),
            round_tag="r1",
            matrix=score.R5_MATRIX,
        )
        assert payload["min_ranked_per_horizon"] == score.MIN_RANKED_PER_HORIZON
        assert payload["horizon_order"] == list(score.HORIZON_ORDER)
        assert "per_horizon_ladder" in payload["ranked"][0]
        assert "per_horizon_bear" in payload["ranked"][0]
