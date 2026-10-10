"""Tests for :mod:`app.tournament.selection`.

Styled like :mod:`tests.test_tournament_scoring`: fixtures are built by hand, with every number
behind an assertion visible in the test itself, and `AgentResult`/`StrategyCard`/`RealisedTrade` are
constructed directly rather than through `app.tournament.runner`.

Three kinds of test live here, in order:

1. **Pure-function tests** against the module's private helpers (`_gate_l_outcomes`,
   `_gate_c_outcomes`, `_novelty`, `_seat`) -- no filesystem, no bar store, so they run anywhere and
   pin the arithmetic and the honesty requirements (unassessable, not defaulted to pass or fail)
   independently of any one round's committed data.
2. **Filesystem-fixture tests** (`TestLiveCellsDifferencing`, `TestHeldBySession`) that write a small
   `data/rounds/.../results/live-*` tree to `tmp_path` and read it back through the real loader --
   these exercise the one piece of arithmetic (`_live_cells`'s differencing) the task brief calls out
   as silently producing a plausible, biased table if it is wrong.
3. **One end-to-end test** (`TestSelectAgainstRound11`) that calls `select("r11-2026-08")` against
   the repository's own committed round-11 data, with no fixtures at all, and checks it against the
   roster `strategy-program/ROUND-12-PLAN.md` section 5 pre-registered. Round 11 is frozen data
   (`PROTOCOL.md` section 6(a): re-running a frozen round recomputes the same numbers rather than
   sampling anything new), so this is a stable regression check, not a moving target -- if it starts
   failing, either this module or the committed data changed, and either is worth knowing about.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.tournament.models import AgentResult, Discipline, RealisedTrade, StrategyCard
from app.tournament.selection import (
    FIELD,
    GATE_L_FAIL,
    LIVE_TAGS,
    MAX_SEATS,
    MIN_LIVE_HITS,
    NOVELTY_THRESHOLD,
    RULE_VERSION,
    _adjusted_excess,
    _gate_c_outcomes,
    _gate_l_outcomes,
    _held_by_session,
    _live_cells,
    _novelty,
    _seat,
    select,
)
from tests.conftest import requires_real_store

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _card(agent_id: str) -> StrategyCard:
    return StrategyCard(
        agent_id=agent_id,
        display_name=agent_id,
        discipline=Discipline.MOMENTUM,
        thesis="Fixture card -- not a real strategy.",
        universe=("AAPL",),
        entry="close > sma(20)",
        exit="close < sma(20)",
        stop_loss_pct=Decimal("0.08"),
        take_profit_pct=Decimal("0.24"),
        max_hold_days=None,
        max_positions=4,
        position_pct=Decimal("0.25"),
        designed_through=dt.date(2026, 2, 10),
    )


def _agent_result(
    agent_id: str,
    *,
    sessions: int,
    starting_equity: Decimal,
    ending_equity: Decimal,
    benchmark_return: Decimal | None,
    capital_exposure: Decimal | None,
    trades: tuple[RealisedTrade, ...] = (),
) -> AgentResult:
    return AgentResult(
        card=_card(agent_id),
        sessions=sessions,
        starting_equity=starting_equity,
        ending_equity=ending_equity,
        total_return=Decimal("0"),  # deliberately not the real figure -- DEFECTS.md D1, never read
        max_drawdown=Decimal("0"),
        exposure=None,
        capital_exposure=float(capital_exposure) if capital_exposure is not None else None,
        trades=trades,
        benchmark_return=benchmark_return,
    )


def _trade(
    *,
    symbol: str,
    entry_date: dt.date,
    exit_date: dt.date | None,
    quantity: Decimal = Decimal("10"),
    entry_price: Decimal = Decimal("100"),
) -> RealisedTrade:
    exit_price = entry_price if exit_date is not None else None
    return RealisedTrade(
        symbol=symbol,
        entry_date=entry_date,
        entry_price=entry_price,
        exit_date=exit_date,
        exit_price=exit_price,
        quantity=quantity,
        exit_reason="rule" if exit_date is not None else "open_at_end",
        pnl=Decimal("0"),
        return_pct=Decimal("0"),
        bars_held=max((exit_date - entry_date).days if exit_date else 30, 1),
    )


def _write_run(results_root, tag: str, agent_id: str, result: AgentResult) -> None:
    runs_dir = results_root / tag / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"r1-{agent_id}.json").write_text(result.model_dump_json(), encoding="utf-8")


# ---------------------------------------------------------------------------
# Gate L -- carried-forward data, no filesystem involved
# ---------------------------------------------------------------------------


class TestGateL:
    def test_the_two_carried_forward_failures_are_flagged(self) -> None:
        outcomes = {o.agent_id: o for o in _gate_l_outcomes()}
        assert set(GATE_L_FAIL) == {"c07-chop", "c14-riskmanaged-wide"}
        for agent_id, why in GATE_L_FAIL.items():
            assert outcomes[agent_id].passed is False
            assert why in outcomes[agent_id].reason

    def test_every_other_field_card_passes(self) -> None:
        outcomes = {o.agent_id: o for o in _gate_l_outcomes()}
        assert set(outcomes) == set(FIELD)
        for agent_id in FIELD:
            if agent_id not in GATE_L_FAIL:
                assert outcomes[agent_id].passed is True


# ---------------------------------------------------------------------------
# Gate C -- eliminates on hit rate, and reports an unassessable card honestly
# ---------------------------------------------------------------------------


class TestGateC:
    def test_three_of_six_passes_two_of_six_fails(self) -> None:
        cells = {
            "passer": {t: Decimal("0.01") for t in LIVE_TAGS[:3]} | {t: Decimal("-0.01") for t in LIVE_TAGS[3:]},
            "failer": {t: Decimal("0.01") for t in LIVE_TAGS[:2]} | {t: Decimal("-0.01") for t in LIVE_TAGS[2:]},
        }
        outcomes, survivors, summary = _gate_c_outcomes(["passer", "failer"], cells)
        by_id = {o.agent_id: o for o in outcomes}
        assert by_id["passer"].passed is True
        assert summary["passer"]["hits"] == 3
        assert by_id["failer"].passed is False
        assert summary["failer"]["hits"] == 2
        assert survivors == ["passer"]
        assert MIN_LIVE_HITS == 3  # the gate's own threshold, pinned so the fixture above stays honest

    def test_a_card_with_no_live_record_is_unassessable_not_a_default_pass_or_fail(self) -> None:
        """The honesty requirement, checked directly: a candidate absent from `cells` entirely must
        not silently become `passed=True` (defaulting to pass) or read like an ordinary consistency
        failure (defaulting to fail) -- it must say, in its own reason, that it could not be
        assessed."""
        outcomes, survivors, summary = _gate_c_outcomes(["ghost"], {})
        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.agent_id == "ghost"
        assert outcome.passed is False
        assert "cannot be assessed" in outcome.reason or "unassessable" in outcome.reason
        assert "ghost" not in survivors
        assert summary["ghost"] == {"median": None, "hits": 0, "n": 0}


# ---------------------------------------------------------------------------
# Live-matrix differencing -- the arithmetic the task brief singles out as silently biasable
# ---------------------------------------------------------------------------


class TestLiveCellsDifferencing:
    """Builds a six-window cumulative run tree by hand for one field card (`B-momentum`, chosen only
    because it is a real `FIELD` key -- `_live_cells` filters to `FIELD` membership) and checks the
    differencing against numbers computed by hand outside the implementation.

    All six live tags carry the same `starting_equity` (`Decimal(100000)`), matching what makes the
    cumulative-run design correct in the first place: one continuous book, resampled at six end
    dates, never restarted.
    """

    def _build(self, tmp_path):
        starting_equity = Decimal("100000")
        results_root = tmp_path / "results"

        # live-1: 20 sessions, flat (0% return), so `prev_equity` for live-2 stays a round number.
        r1 = _agent_result(
            "B-momentum",
            sessions=20,
            starting_equity=starting_equity,
            ending_equity=Decimal("100000"),
            benchmark_return=Decimal("0.02"),
            capital_exposure=Decimal("1"),
        )
        # live-2: cumulative through 40 sessions. The period-2-alone return is +5% on top of
        # live-1's flat 100000, i.e. ending_equity 105000. `capital_exposure=0.75` is chosen so the
        # *sub-period* exposure recovered by differencing is exactly 0.5 (see the module docstring's
        # formula) -- worked by hand: notional_2 = 0.75*40*100000 = 3,000,000, notional_1 =
        # 1*20*100000 = 2,000,000, so the sub-period notional is 1,000,000 over 20 sessions at
        # prev_equity=100000 -> exposure_step = 1,000,000/(20*100000) = 0.5.
        r2 = _agent_result(
            "B-momentum",
            sessions=40,
            starting_equity=starting_equity,
            ending_equity=Decimal("105000"),
            # cumulative benchmark chosen so the chain-linked *step* is exactly 3%:
            # (1.02 * 1.03) - 1 = 0.0506.
            benchmark_return=Decimal("0.0506"),
            capital_exposure=Decimal("0.75"),
        )
        # live-3..live-6: carried flat from live-2 (zero incremental sessions/return) is invalid
        # (`d_sessions <= 0` would break the loop before live-2 is even reached is not a risk here
        # since live-2 already differenced -- but each later tag must still add sessions). Kept
        # trivial since only live-1 and live-2 are asserted on below.
        later = {}
        prev_cap_notional = Decimal("3000000")
        for i, tag in enumerate(LIVE_TAGS[2:], start=3):
            sessions = 40 + 10 * (i - 2)
            equity = Decimal("105000") + Decimal("1000") * (i - 2)
            bench = Decimal("0.0506") + Decimal("0.001") * (i - 2)
            notional = prev_cap_notional + Decimal("500000")
            cap = notional / (Decimal(sessions) * starting_equity)
            later[tag] = _agent_result(
                "B-momentum",
                sessions=sessions,
                starting_equity=starting_equity,
                ending_equity=equity,
                benchmark_return=bench,
                capital_exposure=cap,
            )
            prev_cap_notional = notional

        for tag, result in {"live-1": r1, "live-2": r2, **later}.items():
            _write_run(results_root, tag, "B-momentum", result)
        return results_root, r1, r2

    def test_first_subperiod_reduces_to_plain_adjusted_excess(self, tmp_path) -> None:
        results_root, r1, _r2 = self._build(tmp_path)
        cells = _live_cells(results_root)
        got = cells["B-momentum"]["live-1"]
        want = _adjusted_excess(r1)
        assert want is not None and got is not None
        assert abs(got - want) < Decimal("1e-12")
        # And the hand-computed value: 0% return, 100% exposure, 2% benchmark -> -2%.
        assert abs(got - Decimal("-0.02")) < Decimal("1e-12")

    def test_second_subperiod_matches_hand_computed_differencing(self, tmp_path) -> None:
        results_root, _r1, _r2 = self._build(tmp_path)
        cells = _live_cells(results_root)
        got = cells["B-momentum"]["live-2"]
        # ret_step = 105000/100000 - 1 = 0.05; bench_step = 1.0506/1.02 - 1 = 0.03 exactly;
        # exposure_step = 0.5 exactly (see the fixture's own docstring). cell = 0.05 - 0.5*0.03.
        want = Decimal("0.05") - Decimal("0.5") * Decimal("0.03")
        assert got is not None
        assert abs(got - want) < Decimal("1e-12")


# ---------------------------------------------------------------------------
# Held-by-session -- half-open interval semantics, and the open-trade convention D5/holdings_overlap
# rely on
# ---------------------------------------------------------------------------


class TestHeldBySession:
    def test_a_closed_trade_is_held_on_entry_and_not_on_exit(self, tmp_path) -> None:
        results_root = tmp_path / "results"
        result = _agent_result(
            "B-momentum",
            sessions=5,
            starting_equity=Decimal("100000"),
            ending_equity=Decimal("100000"),
            benchmark_return=Decimal("0"),
            capital_exposure=Decimal("0"),
            trades=(
                _trade(
                    symbol="AAPL",
                    entry_date=dt.date(2026, 3, 2),
                    exit_date=dt.date(2026, 3, 4),
                ),
            ),
        )
        _write_run(results_root, "live-6", "B-momentum", result)

        days = [dt.date(2026, 3, d) for d in (1, 2, 3, 4, 5)]
        held = _held_by_session(results_root, "B-momentum", days)
        assert held is not None
        assert held[0] == frozenset()  # 3/1 -- before entry
        assert held[1] == frozenset({"AAPL"})  # 3/2 -- entry day, held
        assert held[2] == frozenset({"AAPL"})  # 3/3 -- still held
        assert held[3] == frozenset()  # 3/4 -- exit day, excluded (half-open)
        assert held[4] == frozenset()  # 3/5 -- after exit

    def test_an_open_trade_is_held_through_the_last_session(self, tmp_path) -> None:
        results_root = tmp_path / "results"
        result = _agent_result(
            "B-momentum",
            sessions=5,
            starting_equity=Decimal("100000"),
            ending_equity=Decimal("100000"),
            benchmark_return=Decimal("0"),
            capital_exposure=Decimal("0"),
            trades=(_trade(symbol="MSFT", entry_date=dt.date(2026, 3, 3), exit_date=None),),
        )
        _write_run(results_root, "live-6", "B-momentum", result)

        days = [dt.date(2026, 3, d) for d in (1, 2, 3, 4, 5)]
        held = _held_by_session(results_root, "B-momentum", days)
        assert held is not None
        assert held[2] == frozenset({"MSFT"})
        assert held[3] == frozenset({"MSFT"})
        assert held[4] == frozenset({"MSFT"})  # still held at the window's last session

    def test_a_card_with_no_live_6_run_on_disk_is_none_not_empty(self, tmp_path) -> None:
        results_root = tmp_path / "results"
        results_root.mkdir(parents=True)
        assert _held_by_session(results_root, "nobody-traded", [dt.date(2026, 3, 1)]) is None


# ---------------------------------------------------------------------------
# Novelty -- deliberately asymmetric
# ---------------------------------------------------------------------------


class TestNovelty:
    def test_the_wider_card_shows_novelty_the_narrower_one_does_not(self) -> None:
        """A card holding {AAPL, MSFT} against a seated card holding only {AAPL} is half new; the
        same pair in the other order shows nothing new at all -- the exact asymmetry
        `holdings_overlap.py`'s module docstring builds the whole rule around."""
        wide = [frozenset({"AAPL", "MSFT"})]
        narrow = [frozenset({"AAPL"})]

        count_wide_given_narrow, frac_wide_given_narrow, n = _novelty(wide, [narrow])
        assert count_wide_given_narrow == 1.0
        assert frac_wide_given_narrow == 0.5
        assert n == 1

        count_narrow_given_wide, frac_narrow_given_wide, _n = _novelty(narrow, [wide])
        assert count_narrow_given_wide == 0.0
        assert frac_narrow_given_wide == 0.0

    def test_measured_against_the_union_not_pairwise(self) -> None:
        """Two seated cards that between them cover everything the candidate holds leave it with
        zero novelty, even though neither one alone would have."""
        candidate = [frozenset({"AAPL", "MSFT"})]
        seated_a = [frozenset({"AAPL"})]
        seated_b = [frozenset({"MSFT"})]
        count, _frac, _n = _novelty(candidate, [seated_a, seated_b])
        assert count == 0.0

    def test_sessions_holding_nothing_are_skipped_not_scored(self) -> None:
        candidate = [frozenset(), frozenset({"AAPL"})]
        seated = [frozenset(), frozenset()]
        count, frac, n = _novelty(candidate, [seated])
        assert n == 1  # only the invested session counts
        assert count == 1.0
        assert frac == 1.0

    def test_a_candidate_that_never_held_anything_is_undefined_not_zero(self) -> None:
        candidate = [frozenset(), frozenset()]
        count, frac, n = _novelty(candidate, [[frozenset(), frozenset()]])
        assert count is None
        assert frac is None
        assert n == 0


# ---------------------------------------------------------------------------
# The seating walk -- cap, threshold, and the unassessable-card honesty requirement
# ---------------------------------------------------------------------------


class TestSeat:
    def test_first_ranked_card_is_always_seated(self) -> None:
        held = {"only": [frozenset()]}
        status = _seat(["only"], held)
        _novel, seated, _note = status["only"]
        assert seated is True

    def test_a_card_with_no_live_record_is_unassessable_not_seated_by_default(self) -> None:
        """Distinctness's own version of the honesty requirement: `held[agent_id] is None` (no
        `live-6` trade log) must produce `seated=False` with a note that says the seat could not be
        assessed -- not a silent seat and not a silent, indistinguishable-from-ordinary rejection."""
        held = {"first": [frozenset({"AAPL"})], "no-record": None}
        status = _seat(["first", "no-record"], held)
        novel, seated, note = status["no-record"]
        assert seated is False
        assert novel is None
        assert "cannot be assessed" in note

    def test_seat_count_is_capped_with_no_floor(self) -> None:
        """Five candidates, each holding a name none of the others do -- every one clears the
        novelty threshold against the union so far, but the cap still stops the walk at
        `MAX_SEATS`."""
        days = 1
        held = {
            f"c{i}": [frozenset({f"SYM{i}"})] * days for i in range(MAX_SEATS + 1)
        }
        ranked = list(held)
        status = _seat(ranked, held)
        seated_ids = [agent_id for agent_id, (_n, seated, _note) in status.items() if seated]
        assert len(seated_ids) == MAX_SEATS
        last = f"c{MAX_SEATS}"
        _novel, seated, note = status[last]
        assert seated is False
        assert "cap" in note

    def test_below_threshold_candidate_is_skipped(self) -> None:
        held = {
            "first": [frozenset({"AAPL", "MSFT", "GOOG"})],
            "redundant": [frozenset({"AAPL"})],  # entirely covered by "first" -- 0.0 novel names
        }
        status = _seat(["first", "redundant"], held)
        novel, seated, note = status["redundant"]
        assert novel == "0.00"
        assert seated is False
        assert "below" in note
        assert NOVELTY_THRESHOLD == 1.0  # pin the threshold the fixture's numbers assume


# ---------------------------------------------------------------------------
# End-to-end against the repository's own committed round-11 data
# ---------------------------------------------------------------------------


@requires_real_store
class TestSelectAgainstRound11:
    """No fixtures -- exercises `select()` against `data/rounds/r11-2026-08` exactly as committed,
    and checks the result against `strategy-program/ROUND-12-PLAN.md` section 5's pre-registered
    table. Round 11 is frozen (`PROTOCOL.md` 6(a)), so this is a stable regression check."""

    def test_seats_the_expected_four_and_excludes_the_expected_two(self) -> None:
        result = select("r11-2026-08")
        assert result.rule_version == RULE_VERSION

        rule_seats = [s for s in result.seats if s.seated_by == "rule"]
        assert [s.agent_id for s in rule_seats] == [
            "B3-concentrated",
            "B-momentum",
            "A-rotation",
            "C-trend",
        ]

        by_id = {s.agent_id: s for s in result.ranking}
        assert by_id["B4-tight-stop"].seated is False
        assert by_id["B4-tight-stop"].novel_names == "0.00"
        assert by_id["B2-hold-90"].seated is False
        assert by_id["B2-hold-90"].novel_names == "0.08"

    def test_outside_competition_seat_is_present_and_unranked(self) -> None:
        result = select("r11-2026-08")
        outside = [s for s in result.seats if s.seated_by == "outside-competition"]
        assert len(outside) == 1
        assert outside[0].agent_id == "ladder-qld-schd"
        assert outside[0].rank is None
        assert outside[0].agent_id not in {s.agent_id for s in result.ranking}

    def test_mandatory_notes_are_present_verbatim(self) -> None:
        result = select("r11-2026-08")
        assert "The live matrix is one market environment cut into six pieces, not six regime draws." in result.notes
        assert "The live window is 127 sessions against the ~250 the programme set as its own bar." in result.notes
        assert "The distinctness rule cannot assess a card with no live record." in result.notes

    def test_gates_report_the_known_eliminations(self) -> None:
        result = select("r11-2026-08")
        a_fail = {o.agent_id for o in result.gates["A"] if not o.passed}
        assert "c14-riskmanaged-wide" in a_fail  # fails Gate A outright
        l_fail = {o.agent_id for o in result.gates["L"] if not o.passed}
        assert l_fail == {"c07-chop", "c14-riskmanaged-wide"}
        c_fail = {o.agent_id for o in result.gates["C"] if not o.passed}
        assert "H-trend-diversified" in c_fail
