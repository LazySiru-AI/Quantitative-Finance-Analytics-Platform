"""Tests for `strategy-program/tools/portfolio.py` -- the combined-book scorer.

`strategy-program/tools/portfolio.py` lives under a hyphenated directory, which is not a legal
Python package name, so it cannot be imported as ``strategy_program.tools.portfolio``. It is loaded
by file path via `importlib.util.spec_from_file_location` below -- the same mechanism
`portfolio.py`'s own module docstring names as the alternative to the duplication it chose for its
sibling `score.py` import. Here, loading the module under test by path is the right tool; there is no
sibling to duplicate from.

Two kinds of assertion live in this file, deliberately kept apart (mirrors
`tests/test_competition_api.py`'s split):

* **Arithmetic assertions** (equal-weight combining, cash for an absent member, correlation over
  shared windows only, adjusted excess vs. raw excess) run against synthetic `AgentResult` objects
  built in memory -- no files on disk, no dependency on which real cards happen to be committed.
* **The reproduction assertion** runs against the real, committed `data/rounds/r3-2026-08/results`
  tree, because the numbers under test (`strategy-program/ROUND-4-PLAN.md` Sec 1's hand-computed
  table) are properties of that specific data, not something a synthetic fixture could stand in for.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from decimal import Decimal
from types import ModuleType

import pytest

from app.config import REPO_ROOT
from app.tournament.models import AgentResult, Discipline, StrategyCard

# ---------------------------------------------------------------------------
# Load strategy-program/tools/portfolio.py by path (see the module docstring)
# ---------------------------------------------------------------------------

_PORTFOLIO_PATH = REPO_ROOT / "strategy-program" / "tools" / "portfolio.py"
_spec = importlib.util.spec_from_file_location("strategy_program_tools_portfolio", _PORTFOLIO_PATH)
assert _spec is not None and _spec.loader is not None
portfolio: ModuleType = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = portfolio
_spec.loader.exec_module(portfolio)


# ---------------------------------------------------------------------------
# Synthetic AgentResult builder
# ---------------------------------------------------------------------------

_CARD_DEFAULTS = dict(
    discipline=Discipline.MOMENTUM,
    thesis="A synthetic card used only to exercise portfolio-combining arithmetic, not a real "
    "strategy.",
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


def _make_result(
    agent_id: str,
    *,
    starting_equity: Decimal = Decimal("10000"),
    ending_equity: Decimal,
    benchmark_return: Decimal | None,
    capital_exposure: float | None = None,
    exposure: float | None = None,
    sessions: int = 10,
) -> AgentResult:
    """A minimal, valid `AgentResult` for one (card, window). `total_return` is deliberately set to
    something implausible (`Decimal("999")`) so a test that accidentally reads it instead of
    `portfolio.corrected_return` fails loudly rather than by coincidence."""
    card = StrategyCard(agent_id=agent_id, display_name=agent_id, **_CARD_DEFAULTS)
    return AgentResult(
        card=card,
        sessions=sessions,
        starting_equity=starting_equity,
        ending_equity=ending_equity,
        total_return=Decimal("999"),
        max_drawdown=Decimal("-0.01"),
        exposure=exposure,
        capital_exposure=capital_exposure,
        benchmark_return=benchmark_return,
    )


def _equity_for_return(pct: str, starting: Decimal = Decimal("10000")) -> Decimal:
    """`starting * (1 + pct)` as an `ending_equity` that reproduces `pct` exactly through
    `corrected_return`."""
    return starting * (Decimal(1) + Decimal(pct))


# ---------------------------------------------------------------------------
# 1. Equal-weight arithmetic
# ---------------------------------------------------------------------------


class TestEqualWeightArithmetic:
    def test_combined_return_is_the_mean_of_three_known_returns(self) -> None:
        """Three members, hand-chosen returns of +10%, +5%, -2% -> combined must be their mean,
        exactly, since the metric never touches floats."""
        by_window = {
            "w1": {
                "A": _make_result("A", ending_equity=_equity_for_return("0.10"), benchmark_return=Decimal("0")),
                "B": _make_result("B", ending_equity=_equity_for_return("0.05"), benchmark_return=Decimal("0")),
                "C": _make_result("C", ending_equity=_equity_for_return("-0.02"), benchmark_return=Decimal("0")),
            }
        }
        window = portfolio.combine_window("w1", ["A", "B", "C"], by_window)

        expected = (Decimal("0.10") + Decimal("0.05") + Decimal("-0.02")) / Decimal(3)
        assert window.combined_return == expected
        # Hand-check: (0.10 + 0.05 - 0.02) / 3 = 0.13 / 3 = 0.043333...
        assert window.combined_return == Decimal("0.13") / Decimal(3)

        score = portfolio.score_portfolio(by_window, ["A", "B", "C"], ["w1"])
        assert score.n_windows == 1
        # Benchmark is 0 here, so excess == combined_return exactly.
        assert score.windows[0].excess == expected


# ---------------------------------------------------------------------------
# 2. An absent member holds cash, not NaN
# ---------------------------------------------------------------------------


class TestAbsentMemberHoldsCash:
    def test_two_present_one_absent_divides_by_three_not_two(self) -> None:
        """A, B present with +10% and -4%; C has no run file for this window at all. The combined
        return must be `(a + b + 0) / 3`, not `(a + b) / 2` -- the case that would silently flatten
        an ineligible member out of the book and report an easier one than was actually held."""
        by_window = {
            "w1": {
                "A": _make_result("A", ending_equity=_equity_for_return("0.10"), benchmark_return=Decimal("0")),
                "B": _make_result("B", ending_equity=_equity_for_return("-0.04"), benchmark_return=Decimal("0")),
                # "C" has no entry at all for "w1".
            }
        }
        window = portfolio.combine_window("w1", ["A", "B", "C"], by_window)

        wrong_two_member_mean = (Decimal("0.10") + Decimal("-0.04")) / Decimal(2)
        correct_three_member_mean = (Decimal("0.10") + Decimal("-0.04") + Decimal(0)) / Decimal(3)

        assert window.combined_return == correct_three_member_mean
        assert window.combined_return != wrong_two_member_mean

        member_c = next(m for m in window.members if m.agent_id == "C")
        assert member_c.present is False
        assert member_c.corrected_return is None
        assert member_c.capital_exposure is None

    def test_absent_member_contributes_zero_capital_exposure(self) -> None:
        """The combined `capital_exposure` also treats an absent member as 0 capital deployed, mean
        of `[0.30, 0.0]` over 2 members (not `[0.30]` over 1)."""
        by_window = {
            "w1": {
                "A": _make_result(
                    "A",
                    ending_equity=_equity_for_return("0.05"),
                    benchmark_return=Decimal("0"),
                    capital_exposure=0.30,
                ),
            }
        }
        window = portfolio.combine_window("w1", ["A", "B"], by_window)
        assert window.combined_capital_exposure == Decimal("0.30") / Decimal(2)


# ---------------------------------------------------------------------------
# 3. Correlation uses only shared windows
# ---------------------------------------------------------------------------


class TestCorrelationSharedWindowsOnly:
    def test_pair_count_is_the_overlap_not_the_union(self) -> None:
        """A runs in w1-w4, B runs in w2-w5: the overlap is exactly {w2, w3, w4}, three windows, out
        of five total. `n` must report 3, and no imputed value for w1 or w5 may enter the
        correlation."""
        window_tags = ["w1", "w2", "w3", "w4", "w5"]
        # Chosen so A and B are perfectly correlated on the 3 shared windows only, and would NOT be
        # if w1/w5 were (wrongly) imputed as e.g. 0 and included.
        a_returns = {"w1": "0.20", "w2": "0.10", "w3": "0.05", "w4": "-0.05"}
        b_returns = {"w2": "0.20", "w3": "0.10", "w4": "-0.10", "w5": "-0.30"}

        by_window: dict[str, dict[str, AgentResult]] = {}
        for tag in window_tags:
            agents = {}
            if tag in a_returns:
                agents["A"] = _make_result(
                    "A", ending_equity=_equity_for_return(a_returns[tag]), benchmark_return=Decimal("0")
                )
            if tag in b_returns:
                agents["B"] = _make_result(
                    "B", ending_equity=_equity_for_return(b_returns[tag]), benchmark_return=Decimal("0")
                )
            by_window[tag] = agents

        pairs = portfolio.correlation_matrix(by_window, ["A", "B"], window_tags)
        assert len(pairs) == 1
        assert pairs[0].n == 3

        # Independently confirm the 3 shared windows are exactly {w2, w3, w4} by checking the
        # correlation is computed from a perfectly linear pair on those three points (b = 2a),
        # which would not hold if w1 (a=0.20) or w5 (b=-0.30) leaked in.
        assert pairs[0].rho is not None
        assert pairs[0].rho == pytest.approx(1.0, abs=1e-9)

    def test_fewer_than_two_shared_windows_gives_none_not_a_number(self) -> None:
        by_window = {
            "w1": {"A": _make_result("A", ending_equity=_equity_for_return("0.10"), benchmark_return=Decimal("0"))},
            "w2": {"B": _make_result("B", ending_equity=_equity_for_return("0.10"), benchmark_return=Decimal("0"))},
        }
        pairs = portfolio.correlation_matrix(by_window, ["A", "B"], ["w1", "w2"])
        assert pairs[0].n == 0
        assert pairs[0].rho is None


# ---------------------------------------------------------------------------
# 4. Adjusted excess uses combined capital exposure
# ---------------------------------------------------------------------------


class TestAdjustedExcessUsesCombinedExposure:
    def test_mostly_cash_book_against_falling_benchmark(self) -> None:
        """Two of three members absent (cash); the one present member is barely invested
        (`capital_exposure=0.10`). Against a benchmark of -50%, raw `excess` credits the *entire*
        benchmark decline as if the whole book had avoided it; `adjusted_excess` only credits the
        fraction of capital that was actually not exposed. The two must differ, and `adjusted_excess`
        must be the smaller (less flattering) of the two -- exactly the D2 artifact `portfolio.py`'s
        module docstring says this exists to avoid."""
        by_window = {
            "w1": {
                "A": _make_result(
                    "A",
                    ending_equity=_equity_for_return("0.01"),
                    benchmark_return=Decimal("-0.50"),
                    capital_exposure=0.10,
                ),
                # B and C absent -> cash, 0 capital exposure each.
            }
        }
        window = portfolio.combine_window("w1", ["A", "B", "C"], by_window)

        combined_return = Decimal("0.01") / Decimal(3)
        combined_exposure = Decimal("0.10") / Decimal(3)
        benchmark = Decimal("-0.50")

        assert window.combined_capital_exposure == combined_exposure
        assert window.excess == combined_return - benchmark
        assert window.adjusted_excess == combined_return - (combined_exposure * benchmark)

        assert window.excess != window.adjusted_excess
        # Raw excess over-credits: the whole -50% is added back even though only ~3.3% of the book
        # was actually not exposed to it.
        assert window.adjusted_excess < window.excess


# ---------------------------------------------------------------------------
# 5. Reproduce the hand-computed result against real r3 data
# ---------------------------------------------------------------------------

_R3_RESULTS = REPO_ROOT / "data" / "rounds" / "r3-2026-08" / "results"

requires_r3_results = pytest.mark.skipif(
    not _R3_RESULTS.is_dir(), reason="data/rounds/r3-2026-08/results not present"
)

_TRIO = ["B-momentum", "C-trend", "c14-riskmanaged-wide"]


@pytest.fixture(scope="module")
def score_and_pairs():
    window_tags = portfolio._discover_window_tags(_R3_RESULTS)
    round_tag = portfolio._discover_round_tag(_R3_RESULTS, window_tags)
    assert round_tag is not None
    by_window = portfolio.load_results(_R3_RESULTS, round_tag, window_tags)
    score = portfolio.score_portfolio(by_window, _TRIO, window_tags)
    pairs = portfolio.correlation_matrix(by_window, _TRIO, window_tags)
    return score, pairs


@requires_r3_results
class TestReproducesHandComputedResult:
    """`strategy-program/ROUND-4-PLAN.md` Sec 1's trio -- `B-momentum`, `C-trend`,
    `c14-riskmanaged-wide` -- was scored by hand: median excess +15.4%, worst -11.1%, hit rate 75%,
    over all 8 windows, and rho(C-trend, c14) ~= +0.04.

    Tolerance: 0.1 percentage point (`Decimal("0.001")`) on the three excess figures -- tight enough
    to catch a real formula error, loose enough to survive the hand computation's own rounding to one
    decimal place. 0.02 absolute on rho, for the same reason (the plan states it to two significant
    figures). Hit rate is asserted exactly, since 75% of 8 is an unambiguous 6/8.
    """

    def test_runs_all_eight_main_windows(self, score_and_pairs) -> None:
        score, _pairs = score_and_pairs
        assert score.n_windows == 8

    def test_median_excess(self, score_and_pairs) -> None:
        score, _pairs = score_and_pairs
        assert score.median_excess is not None
        assert score.median_excess == pytest.approx(Decimal("0.154"), abs=Decimal("0.001"))

    def test_worst_excess(self, score_and_pairs) -> None:
        score, _pairs = score_and_pairs
        assert score.worst_excess is not None
        assert score.worst_excess == pytest.approx(Decimal("-0.111"), abs=Decimal("0.001"))

    def test_hit_rate(self, score_and_pairs) -> None:
        score, _pairs = score_and_pairs
        assert score.hit_rate_excess == pytest.approx(0.75)

    def test_correlation_c_trend_vs_c14(self, score_and_pairs) -> None:
        _score, pairs = score_and_pairs
        pair = next(
            p
            for p in pairs
            if {p.a, p.b} == {"C-trend", "c14-riskmanaged-wide"}
        )
        assert pair.rho is not None
        assert pair.rho == pytest.approx(0.04, abs=0.02)


# ---------------------------------------------------------------------------
# Annualized metrics and mixed-length correlation (round 5's horizon ladder)
# ---------------------------------------------------------------------------


class TestAnnualizedMetrics:
    """Round 5 runs windows from 125 to 2517 sessions. Every metric in this module was written when
    the widest spread in a matrix was 45 to 284 sessions, where the distinction below barely bites.
    """

    def test_window_years_comes_from_the_session_count(self) -> None:
        """An `AgentResult` carries no window dates -- they live only on the sibling per-window
        `tournament.json`, which this module never loads -- so the length is derived from
        `sessions` at 252 trading days to the year. Checked here against two of round 5's real
        session counts."""
        decade = _make_result("A", ending_equity=Decimal("10000"), benchmark_return=None, sessions=2517)
        half_year = _make_result("A", ending_equity=Decimal("10000"), benchmark_return=None, sessions=125)

        assert float(portfolio.window_years(decade)) == pytest.approx(9.988, abs=0.01)
        assert float(portfolio.window_years(half_year)) == pytest.approx(0.496, abs=0.01)

    def test_window_years_is_none_for_a_zero_session_window(self) -> None:
        degenerate = _make_result("A", ending_equity=Decimal("10000"), benchmark_return=None, sessions=0)
        assert portfolio.window_years(degenerate) is None

    def test_annualized_return_hand_checked(self) -> None:
        """+100% over ten years is `2 ** 0.1 - 1`; +6% over half a year is `1.06 ** 2 - 1`. Asserted
        against the hand-computed values, not against whatever the implementation happens to
        return."""
        decade = _make_result(
            "A", ending_equity=_equity_for_return("1.00"), benchmark_return=None, sessions=2520
        )
        half_year = _make_result(
            "A", ending_equity=_equity_for_return("0.06"), benchmark_return=None, sessions=126
        )

        assert float(portfolio.annualized_return(decade)) == pytest.approx(2 ** 0.1 - 1, abs=1e-6)
        assert float(portfolio.annualized_return(half_year)) == pytest.approx(1.06 ** 2 - 1, abs=1e-6)

    def test_a_total_loss_cannot_be_annualized_and_is_not_clamped(self) -> None:
        """A return at or below -100% puts the root's base at zero or negative. `None` is the only
        honest answer -- a clamped figure would render as an ordinary number in a table and be read
        as one."""
        wiped_out = _make_result(
            "A", ending_equity=Decimal("0"), benchmark_return=Decimal("0"), sessions=252
        )
        assert portfolio.annualized_return(wiped_out) is None
        assert portfolio.annualized_adjusted_excess(wiped_out) is None


class TestMixedLengthCorrelation:
    """The defect that made `annualized=` necessary, pinned directly.

    Four (card, window) pairs: two decades and two half-years. Within the decades the two cards move
    together; within the half-years they move *opposite*. On raw window returns the between-group
    scale gap -- 60-100% against 1-3% -- swamps both effects and reports a strong positive
    correlation. On compound annual rates, which is the only reading under which the four points are
    the same kind of quantity, the sign reverses.
    """

    #: Two decades then two half-years, matching `_RETURNS` below position for position.
    _SESSIONS = (2520, 2520, 126, 126)
    _A = ("1.00", "0.60", "0.010", "0.030")
    _B = ("0.60", "1.00", "0.030", "0.010")

    def _by_window(self) -> dict[str, dict[str, AgentResult]]:
        out: dict[str, dict[str, AgentResult]] = {}
        for i, (n, ra, rb) in enumerate(zip(self._SESSIONS, self._A, self._B, strict=True)):
            tag = f"w{i}"
            out[tag] = {
                "A": _make_result("A", ending_equity=_equity_for_return(ra),
                                  benchmark_return=Decimal("0"), sessions=n),
                "B": _make_result("B", ending_equity=_equity_for_return(rb),
                                  benchmark_return=Decimal("0"), sessions=n),
            }
        return out

    def test_raw_and_annualized_disagree_on_the_sign(self) -> None:
        by_window = self._by_window()
        tags = list(by_window)

        raw = portfolio.correlation_matrix(by_window, ["A", "B"], tags)[0]
        annualized = portfolio.correlation_matrix(by_window, ["A", "B"], tags, annualized=True)[0]

        assert raw.n == annualized.n == 4
        # Hand-computed with statistics.correlation over the two series.
        assert raw.rho == pytest.approx(+0.7671, abs=1e-3)
        assert annualized.rho == pytest.approx(-0.4924, abs=1e-3)
        assert raw.rho > 0 > annualized.rho

    def test_raw_is_still_the_default(self) -> None:
        """Rounds 1-4's published correlation figures -- including `ROUND-4-PLAN.md` section 1's --
        are raw, and annualizing is not a monotone transform across windows of differing length, so
        the default must not move. `TestRoundFourPlanReproduction` guards the real tree; this guards
        the flag itself."""
        by_window = self._by_window()
        tags = list(by_window)

        default = portfolio.correlation_matrix(by_window, ["A", "B"], tags)[0]
        explicit_raw = portfolio.correlation_matrix(by_window, ["A", "B"], tags, annualized=False)[0]

        assert default.rho == explicit_raw.rho
