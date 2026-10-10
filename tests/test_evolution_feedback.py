"""Tests for `app.evolution.feedback` and `app.evolution.ledger`.

Round trees are built by hand under `tmp_path`, in the exact shape `app.tournament.jobs` writes on
disk (verified against `data/rounds/r1-2026-08/results/bear-2022/runs/r1-A-rotation.json`, a real
committed run file) -- `results/<window>/runs/<agent_id>.json`, one `StrategyCard`-shaped payload per
file, matched by the embedded `card.agent_id`, never by filename (see
`app.tournament.results`'s own module docstring on why the filename cannot be trusted). Nothing here
writes into `data/`; every fixture is rooted at `tmp_path`.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

from app.config import Settings
from app.evolution import feedback
from app.evolution.feedback import (
    derive_findings,
    field_window_medians,
    ledger_entries_for,
    read_standings,
    select_elites,
)
from app.evolution.ledger import Ledger, LedgerEntry
from app.evolution.models import Genome, LoopConfig, Standing
from app.tournament.purposes import Purpose
from app.tournament.results import build_leaderboard

# ---------------------------------------------------------------------------
# Fixture builders -- construct real run-file JSON, copying the shape of a committed run file.
# ---------------------------------------------------------------------------


def _card_payload(
    agent_id: str, *, purpose: str = "trading", universe: tuple[str, ...] = ("AAA", "BBB")
) -> dict:
    return {
        "agent_id": agent_id,
        "display_name": f"Card {agent_id}",
        "discipline": "trend",
        "purpose": purpose,
        "thesis": "A placeholder thesis, long enough to satisfy no length constraint but present.",
        "universe": list(universe),
        "entry": "close > sma(20)",
        "exit": "close < sma(20)",
        "stop_loss_pct": "0.10",
        "take_profit_pct": "0.20",
        "max_hold_days": 60,
        "max_positions": 2,
        "position_pct": "0.40",
        "designed_through": "2026-01-01",
    }


def _trade_payload(pnl: str, *, exit_reason: str = "rule") -> dict:
    return {
        "symbol": "AAA",
        "entry_date": "2022-01-03",
        "entry_price": "10.00",
        "exit_date": "2022-01-10",
        "exit_price": "11.00" if Decimal(pnl) >= 0 else "9.00",
        "quantity": "10",
        "exit_reason": exit_reason,
        "pnl": pnl,
        "return_pct": "0.05",
        "bars_held": 5,
    }


def _run_payload(
    agent_id: str,
    *,
    purpose: str = "trading",
    benchmark_return: str = "0.00",
    starting_equity: str = "10000.00",
    ending_equity: str,
    trades: list[dict] | None = None,
    sessions: int = 120,
) -> dict:
    trades = trades if trades is not None else [_trade_payload("50.00"), _trade_payload("-20.00")]
    total_return = str((Decimal(ending_equity) / Decimal(starting_equity)) - 1)
    return {
        "card": _card_payload(agent_id, purpose=purpose),
        "sessions": sessions,
        "starting_equity": starting_equity,
        "ending_equity": ending_equity,
        "total_return": total_return,
        "max_drawdown": "-0.05",
        "sharpe": None,
        "sortino": None,
        "volatility": None,
        "exposure": 0.5,
        "capital_exposure": 0.3,
        "win_rate": None,
        "profit_factor": None,
        "realised_reward_risk": None,
        "trades": trades,
        "rejections": [],
        "benchmark_return": benchmark_return,
        "p_value": None,
        "q_value": None,
        "notes": [],
    }


def _write_run_file(rounds_root: Path, round_id: str, window: str, agent_id: str, payload: dict) -> None:
    runs_dir = rounds_root / round_id / "results" / window / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{agent_id}.json").write_text(json.dumps(payload), encoding="utf-8")


#: Six windows, none named "13f-legal", enough to clear `MIN_ELIGIBLE_MAIN_WINDOWS` (5).
SELECTION_WINDOWS = ("bear-2022", "chop-2015", "chop-2011", "bull-2024", "recent", "gfc")
HOLDOUT_WINDOWS = ("covid", "q4-2018")


def _genome(genome_id: str, *, universe: tuple[str, ...] = ("AAA", "BBB"), traits: dict | None = None) -> Genome:
    return Genome(
        genome_id=genome_id,
        generation=0,
        parents=(),
        origin="founder",
        shape="rules",
        purpose=Purpose.TRADING,
        universe=universe,
        traits=traits if traits is not None else {"lookback": 20},
        seed=0,
        notes="",
    )


def _settings(tmp_path: Path, *, rounds_dir: Path | None = None) -> Settings:
    return Settings(
        rounds_dir=rounds_dir if rounds_dir is not None else tmp_path / "rounds",
        data_dir=tmp_path / "data",
    )


def _default_config() -> LoopConfig:
    return LoopConfig(rank_by="median")


# ---------------------------------------------------------------------------
# (a) read_standings copies leaderboard numbers exactly
# ---------------------------------------------------------------------------


def test_read_standings_copies_leaderboard_rows_exactly(tmp_path: Path) -> None:
    round_id = "r-test-a"
    rounds_root = tmp_path / "rounds"

    for window in SELECTION_WINDOWS:
        _write_run_file(rounds_root, round_id, window, "cand-a", _run_payload("cand-a", ending_equity="11000.00"))
        _write_run_file(rounds_root, round_id, window, "cand-b", _run_payload("cand-b", ending_equity="9000.00"))
    # A human-authored card sharing the round -- must be skipped, it has no genome.
    for window in SELECTION_WINDOWS:
        _write_run_file(rounds_root, round_id, window, "human-card", _run_payload("human-card", ending_equity="10500.00"))

    genomes = {"cand-a": _genome("cand-a"), "cand-b": _genome("cand-b")}
    settings = _settings(tmp_path, rounds_dir=rounds_root)
    config = _default_config()

    board = build_leaderboard(round_id, rank_by="median", rounds_root=rounds_root, purpose="trading")
    standings = read_standings(
        round_id=round_id,
        purpose=Purpose.TRADING,
        genomes=genomes,
        config=config,
        settings=settings,
        selection_windows=SELECTION_WINDOWS,
        holdout_windows=(),
    )

    assert {s.agent_id for s in standings} == {"cand-a", "cand-b"}  # human-card skipped

    by_agent = {row.agent_id: row for row in board.rows}
    for standing in standings:
        row = by_agent[standing.agent_id]
        assert standing.rank == row.rank
        assert standing.eligible == row.eligible
        assert standing.windows_run == row.windows_run
        assert standing.median_excess == row.median_excess
        assert standing.worst_excess == row.worst_excess
        assert standing.hit_rate == row.hit_rate
        assert standing.total_trades == row.total_trades
        assert standing.display_name == row.display_name
        assert standing.holdout_median_excess is None  # no holdout windows were requested


def test_read_standings_honours_a_non_default_rounds_root(tmp_path: Path) -> None:
    """The manager's correction: a running loop writes its generations under `loop_root(settings) /
    'rounds'`, not `settings.rounds_dir` -- so `read_standings` must read wherever it is told, not
    wherever `settings` happens to point."""
    round_id = "r-test-root"
    custom_root = tmp_path / "loop_owned" / "rounds"
    unrelated_default = tmp_path / "rounds"  # settings points here; must never be read from

    for window in SELECTION_WINDOWS:
        _write_run_file(custom_root, round_id, window, "cand-a", _run_payload("cand-a", ending_equity="11000.00"))

    genomes = {"cand-a": _genome("cand-a")}
    settings = _settings(tmp_path, rounds_dir=unrelated_default)
    config = _default_config()

    standings = read_standings(
        round_id=round_id,
        purpose=Purpose.TRADING,
        genomes=genomes,
        config=config,
        settings=settings,
        selection_windows=SELECTION_WINDOWS,
        holdout_windows=(),
        rounds_root=custom_root,
    )

    assert len(standings) == 1
    assert standings[0].agent_id == "cand-a"
    assert standings[0].eligible is True
    assert not unrelated_default.exists()  # nothing was ever written there


# ---------------------------------------------------------------------------
# (b) holdout median comes from holdout windows only, and does not flip rank
# ---------------------------------------------------------------------------


def test_holdout_median_is_independent_of_selection_and_does_not_flip_rank(tmp_path: Path) -> None:
    round_id = "r-test-b"
    rounds_root = tmp_path / "rounds"

    # Selection performance: cand-a dominates cand-b by a wide margin, in every selection window.
    for window in SELECTION_WINDOWS:
        _write_run_file(rounds_root, round_id, window, "cand-a", _run_payload("cand-a", ending_equity="15000.00"))
        _write_run_file(rounds_root, round_id, window, "cand-b", _run_payload("cand-b", ending_equity="6000.00"))

    def _write_holdout(cand_a_ending: str, cand_b_ending: str) -> None:
        for window in HOLDOUT_WINDOWS:
            _write_run_file(rounds_root, round_id, window, "cand-a", _run_payload("cand-a", ending_equity=cand_a_ending))
            _write_run_file(rounds_root, round_id, window, "cand-b", _run_payload("cand-b", ending_equity=cand_b_ending))

    genomes = {"cand-a": _genome("cand-a"), "cand-b": _genome("cand-b")}
    settings = _settings(tmp_path, rounds_dir=rounds_root)
    config = _default_config()

    def _read() -> tuple[Standing, ...]:
        return read_standings(
            round_id=round_id,
            purpose=Purpose.TRADING,
            genomes=genomes,
            config=config,
            settings=settings,
            selection_windows=SELECTION_WINDOWS,
            holdout_windows=HOLDOUT_WINDOWS,
        )

    # Variant 1: mild holdout results for both.
    _write_holdout(cand_a_ending="10500.00", cand_b_ending="9500.00")
    first = {s.agent_id: s for s in _read()}

    # Variant 2: holdout results reversed and made extreme -- if this leaked into `read_standings`'s
    # own ranking decision (it must not; `build_leaderboard`'s own rank is copied verbatim and this
    # function never recomputes it), cand-b's collapse-then-holdout-boom story could invite a bug that
    # tried to blend it in. Selection dominance is wide enough that the rank stays put either way.
    _write_holdout(cand_a_ending="1000.00", cand_b_ending="30000.00")
    second = {s.agent_id: s for s in _read()}

    assert first["cand-a"].rank == second["cand-a"].rank == 1
    assert first["cand-b"].rank == second["cand-b"].rank == 2

    # The holdout figure itself did change, and changed to exactly the median of the two holdout
    # windows' own `excess` values -- computed from holdout runs alone, per the excess formula
    # `corrected_return - benchmark_return` with `benchmark_return = 0`.
    expected_first_a = Decimal("10500.00") / Decimal("10000.00") - 1
    expected_second_a = Decimal("1000.00") / Decimal("10000.00") - 1
    assert first["cand-a"].holdout_median_excess == expected_first_a
    assert second["cand-a"].holdout_median_excess == expected_second_a
    assert first["cand-a"].holdout_median_excess != second["cand-a"].holdout_median_excess

    # And the holdout figure is not simply a copy of the selection median -- it is a different
    # computation over different windows.
    assert first["cand-a"].holdout_median_excess != first["cand-a"].median_excess


# ---------------------------------------------------------------------------
# (b2) `holdout_round_id`: the holdout figure is read from a *separate* round directory, never from
# `round_id`'s own tree -- this is the defect fix itself. `app.evolution.loop` now runs selection and
# holdout windows into two round directories precisely because `build_leaderboard` has no window
# filter: a holdout window written into the *same* round as selection would be ranked right along
# with it, putting the holdout inside the very median it exists to check. This test proves the read
# side of that fix: given a selection round with only selection-window run files and a *different*
# round with only holdout-window run files, `read_standings(holdout_round_id=...)` must report the
# selection median from the first and the holdout median from the second -- never blend them, and
# never fall back to the single-round `_holdout_medians` codepath (which would find nothing, since
# `round_id`'s own directory holds no holdout-window run files here at all).
# ---------------------------------------------------------------------------


def test_read_standings_with_explicit_holdout_round_id_reads_holdout_from_the_other_round(
    tmp_path: Path,
) -> None:
    round_id = "r-test-holdout-round-id"
    holdout_round_id = f"{round_id}-holdout"
    rounds_root = tmp_path / "rounds"

    # `round_id`'s own directory holds only selection windows -- exactly what a fixed `loop.py` now
    # writes there.
    for window in SELECTION_WINDOWS:
        _write_run_file(rounds_root, round_id, window, "cand-a", _run_payload("cand-a", ending_equity="15000.00"))

    # The holdout windows live entirely under the sibling round directory instead.
    for window in HOLDOUT_WINDOWS:
        _write_run_file(
            rounds_root, holdout_round_id, window, "cand-a", _run_payload("cand-a", ending_equity="10500.00")
        )

    genomes = {"cand-a": _genome("cand-a")}
    settings = _settings(tmp_path, rounds_dir=rounds_root)
    config = _default_config()

    standings = read_standings(
        round_id=round_id,
        purpose=Purpose.TRADING,
        genomes=genomes,
        config=config,
        settings=settings,
        selection_windows=SELECTION_WINDOWS,
        holdout_windows=HOLDOUT_WINDOWS,
        holdout_round_id=holdout_round_id,
    )

    assert len(standings) == 1
    standing = standings[0]

    selection_board = build_leaderboard(round_id, rank_by="median", rounds_root=rounds_root, purpose="trading")
    holdout_board = build_leaderboard(holdout_round_id, rank_by="median", rounds_root=rounds_root, purpose="trading")

    # The selection number is `round_id`'s own board, exactly as before.
    assert standing.median_excess == selection_board.rows[0].median_excess
    # `windows_run` counts only what `round_id` itself holds -- selection windows, never selection
    # plus holdout, because the holdout run files never landed in this round's directory at all.
    assert standing.windows_run == len(SELECTION_WINDOWS)

    # The holdout number is `holdout_round_id`'s own board -- copied via `build_leaderboard`, never
    # recomputed by hand, and it is the DIFFERENT round's number, not a re-read of round_id's.
    assert standing.holdout_median_excess == holdout_board.rows[0].median_excess
    assert standing.holdout_median_excess is not None
    assert standing.holdout_median_excess != standing.median_excess


def test_read_standings_without_holdout_round_id_keeps_the_original_single_round_behaviour(
    tmp_path: Path,
) -> None:
    """`holdout_round_id=None` (the default) must still work exactly as before -- existing callers
    that run selection and holdout windows into one round are unaffected by this parameter's
    addition."""
    round_id = "r-test-holdout-default"
    rounds_root = tmp_path / "rounds"

    for window in SELECTION_WINDOWS:
        _write_run_file(rounds_root, round_id, window, "cand-a", _run_payload("cand-a", ending_equity="15000.00"))
    for window in HOLDOUT_WINDOWS:
        _write_run_file(rounds_root, round_id, window, "cand-a", _run_payload("cand-a", ending_equity="10500.00"))

    genomes = {"cand-a": _genome("cand-a")}
    settings = _settings(tmp_path, rounds_dir=rounds_root)
    config = _default_config()

    standings = read_standings(
        round_id=round_id,
        purpose=Purpose.TRADING,
        genomes=genomes,
        config=config,
        settings=settings,
        selection_windows=SELECTION_WINDOWS,
        holdout_windows=HOLDOUT_WINDOWS,
        # holdout_round_id omitted -- defaults to None
    )

    assert len(standings) == 1
    assert standings[0].holdout_median_excess is not None
    expected = Decimal("10500.00") / Decimal("10000.00") - 1
    assert standings[0].holdout_median_excess == expected


# ---------------------------------------------------------------------------
# (c) derive_findings is deterministic
# ---------------------------------------------------------------------------


def _standing(
    genome_id: str,
    *,
    rank: int,
    eligible: bool = True,
    median_excess: Decimal | None,
    worst_excess: Decimal | None = None,
    holdout_median_excess: Decimal | None = None,
    windows_run: int = 6,
    hit_rate: float | None = 0.8,
    total_trades: int = 12,
) -> Standing:
    return Standing(
        genome_id=genome_id,
        agent_id=genome_id,
        display_name=genome_id,
        rank=rank,
        eligible=eligible,
        windows_run=windows_run,
        median_excess=median_excess,
        worst_excess=worst_excess if worst_excess is not None else median_excess,
        hit_rate=hit_rate,
        total_trades=total_trades,
        holdout_median_excess=holdout_median_excess,
    )


def test_derive_findings_is_deterministic_across_two_calls(tmp_path: Path) -> None:
    standings = (
        _standing("g1", rank=1, median_excess=Decimal("0.10"), holdout_median_excess=Decimal("0.08")),
        _standing("g2", rank=2, median_excess=Decimal("0.05"), holdout_median_excess=Decimal("0.02")),
        _standing("g3", rank=3, median_excess=Decimal("0.01"), holdout_median_excess=Decimal("-0.01")),
        _standing("g4", rank=4, eligible=False, median_excess=None, windows_run=2, total_trades=0),
    )
    genomes = {
        "g1": _genome("g1", universe=("AAA", "BBB"), traits={"lookback": 20, "threshold": 1.5}),
        "g2": _genome("g2", universe=("BBB", "CCC"), traits={"lookback": 30, "threshold": 1.2}),
        "g3": _genome("g3", universe=("CCC", "DDD"), traits={"lookback": 10, "threshold": 2.0}),
        "g4": _genome("g4", universe=("EEE",), traits={"lookback": 40, "threshold": 0.5}),
    }
    config = LoopConfig(elite_count=2)

    kwargs = dict(
        standings=standings,
        config=config,
        purpose=Purpose.TRADING,
        selection_windows=SELECTION_WINDOWS,
        holdout_windows=HOLDOUT_WINDOWS,
        genomes=genomes,
    )
    first = derive_findings(**kwargs)
    second = derive_findings(**kwargs)

    assert first == second
    assert len(first) > 0
    kinds = {f.kind for f in first}
    assert "winner" in kinds
    assert "holdout" in kinds
    assert "gate" in kinds
    assert "universe" in kinds
    assert "parameter" in kinds
    assert "regime" in kinds
    assert "failure" in kinds  # g4 is ineligible and took zero trades


# ---------------------------------------------------------------------------
# (d) the holdout finding fires on a sign flip
# ---------------------------------------------------------------------------


def test_holdout_finding_fires_on_a_sign_flip() -> None:
    winner = _standing(
        "g1", rank=1, median_excess=Decimal("0.08"), holdout_median_excess=Decimal("-0.03")
    )
    standings = (winner,)
    genomes = {"g1": _genome("g1")}

    findings = derive_findings(
        standings=standings,
        config=LoopConfig(),
        purpose=Purpose.TRADING,
        selection_windows=SELECTION_WINDOWS,
        holdout_windows=HOLDOUT_WINDOWS,
        genomes=genomes,
    )

    holdout_findings = [f for f in findings if f.kind == "holdout"]
    assert len(holdout_findings) == 1
    finding = holdout_findings[0]
    assert finding.evidence["sign_flip"] is True
    assert finding.evidence["contradicts"] is True
    assert "contradicts" in finding.summary


def test_holdout_finding_is_consistent_when_no_flip_and_no_large_drop() -> None:
    winner = _standing(
        "g1", rank=1, median_excess=Decimal("0.08"), holdout_median_excess=Decimal("0.07")
    )
    findings = derive_findings(
        standings=(winner,),
        config=LoopConfig(),
        purpose=Purpose.TRADING,
        selection_windows=SELECTION_WINDOWS,
        holdout_windows=HOLDOUT_WINDOWS,
        genomes={"g1": _genome("g1")},
    )
    finding = next(f for f in findings if f.kind == "holdout")
    assert finding.evidence["sign_flip"] is False
    assert finding.evidence["contradicts"] is False


# ---------------------------------------------------------------------------
# (e) select_elites never returns an ineligible standing, and is deterministic under ties
# ---------------------------------------------------------------------------


def test_select_elites_excludes_ineligible_and_breaks_ties_deterministically() -> None:
    standings = (
        # Ineligible but numerically the best -- must never be selected.
        _standing("z-ineligible", rank=1, eligible=False, median_excess=Decimal("99"), windows_run=1),
        # Three eligible standings tied on median_excess; worst_excess breaks the first two, then
        # genome_id breaks the remaining tie.
        _standing("g-b", rank=2, median_excess=Decimal("0.05"), worst_excess=Decimal("0.01")),
        _standing("g-a", rank=3, median_excess=Decimal("0.05"), worst_excess=Decimal("0.02")),
        _standing("g-c", rank=4, median_excess=Decimal("0.05"), worst_excess=Decimal("0.01")),
        _standing("g-low", rank=5, median_excess=Decimal("0.01"), worst_excess=Decimal("0.01")),
    )
    genomes = {s.genome_id: _genome(s.genome_id) for s in standings}
    config = LoopConfig(elite_count=3)

    elites = select_elites(standings, genomes, config=config)

    assert "z-ineligible" not in {g.genome_id for g in elites}
    assert len(elites) == 3
    # g-a has the best worst_excess (0.02); g-b and g-c tie on worst_excess (0.01), and "g-b" < "g-c".
    assert [g.genome_id for g in elites] == ["g-a", "g-b", "g-c"]

    # Determinism: re-running with the same (but reordered) input gives the same result.
    shuffled = tuple(reversed(standings))
    elites_again = select_elites(shuffled, genomes, config=config)
    assert [g.genome_id for g in elites_again] == [g.genome_id for g in elites]


def test_select_elites_never_pads_when_too_few_are_eligible() -> None:
    standings = (
        _standing("only-eligible", rank=1, median_excess=Decimal("0.02")),
        _standing("ineligible-1", rank=2, eligible=False, median_excess=Decimal("50"), windows_run=1),
        _standing("ineligible-2", rank=3, eligible=False, median_excess=Decimal("50"), windows_run=1),
    )
    genomes = {s.genome_id: _genome(s.genome_id) for s in standings}
    elites = select_elites(standings, genomes, config=LoopConfig(elite_count=3))
    assert [g.genome_id for g in elites] == ["only-eligible"]


# ---------------------------------------------------------------------------
# (f) BH q-values are monotone and computed over the whole ledger
# ---------------------------------------------------------------------------


def _entry(genome_id: str, generation: int, p_value: float | None, median_excess: str = "0.05") -> LedgerEntry:
    return LedgerEntry(
        genome_id=genome_id,
        generation=generation,
        purpose="trading",
        round_id=f"r-gen{generation}",
        windows=SELECTION_WINDOWS,
        median_excess=Decimal(median_excess),
        holdout_median_excess=None,
        closed_trades=20,
        wins=14,
        p_value=p_value,
        recorded_at=dt.datetime(2026, 8, 24, tzinfo=dt.UTC),
    )


def test_ledger_q_values_are_monotone_and_span_the_whole_ledger(tmp_path: Path) -> None:
    """Six genuinely distinct genomes, in `genome_id_for`'s real `g{generation}-{digest}` shape --
    the suffixes deliberately never repeat across generations (unlike `g0-a`/`g1-a`, which used to be
    used here and, by `content_digest` splitting on the *first* `-`, collided to the same digest `a`;
    that was an accidental fixture collision, not a claim that those two are the same hypothesis --
    see `test_ledger_q_values_dedupe_a_rediscovered_genome_to_one_hypothesis` right below for the
    actual same-hypothesis case, which uses one id recorded twice)."""
    ledger = Ledger(tmp_path / "ledger.jsonl")

    generation_0 = [
        _entry("g0-alpha", 0, p_value=0.01),
        _entry("g0-bravo", 0, p_value=0.03),
        _entry("g0-charlie", 0, p_value=None),  # untestable: too few closed trades
        _entry("g0-delta", 0, p_value=0.4),
    ]
    ledger.record(generation_0)

    q_after_gen0 = ledger.q_values()
    assert set(q_after_gen0) == {
        "g0-alpha",
        "g0-bravo",
        "g0-delta",
    }  # g0-charlie has no p_value, so no q_value
    assert ledger.distinct_candidates() == 4

    # Monotonicity: sorted by p_value ascending, q_value must never decrease.
    ordered = sorted(
        (e for e in generation_0 if e.p_value is not None), key=lambda e: e.p_value
    )
    q_in_p_order = [q_after_gen0[e.genome_id] for e in ordered]
    assert q_in_p_order == sorted(q_in_p_order)

    # Adding a second generation grows `m` -- the whole point of a ledger-wide correction is that an
    # old entry's q-value is not settled once its own generation ends.
    generation_1 = [
        _entry("g1-echo", 1, p_value=0.0001),
        _entry("g1-foxtrot", 1, p_value=0.0005),
    ]
    ledger.record(generation_1)
    q_after_gen1 = ledger.q_values()

    assert ledger.distinct_candidates() == 6
    for genome_id in ("g0-alpha", "g0-bravo", "g0-delta"):
        assert q_after_gen1[genome_id] != q_after_gen0[genome_id]


def test_ledger_q_values_dedupe_a_rediscovered_genome_to_one_hypothesis(tmp_path: Path) -> None:
    """`genome_id_for`'s own docstring: content-addressing exists so the ledger's correction
    denominator counts distinct hypotheses, not distinct runs. A genome recorded twice (rediscovered
    in a later generation) must occupy one seat in `m`, not two."""
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.record([_entry("g-repeat", 0, p_value=0.01), _entry("g-other", 0, p_value=0.02)])
    ledger.record([_entry("g-repeat", 5, p_value=0.01)])  # same genome, later generation

    assert ledger.distinct_candidates() == 2
    assert len(ledger.entries()) == 3


def test_ledger_best_returns_the_highest_median_excess(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    assert ledger.best() is None
    ledger.record(
        [
            _entry("low", 0, p_value=0.01, median_excess="0.02"),
            _entry("high", 0, p_value=0.01, median_excess="0.30"),
            _entry("mid", 0, p_value=0.01, median_excess="0.10"),
        ]
    )
    best = ledger.best()
    assert best is not None
    assert best.genome_id == "high"


# ---------------------------------------------------------------------------
# (g) Ledger tolerates a truncated final line
# ---------------------------------------------------------------------------


def test_ledger_tolerates_a_truncated_final_line(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.record([_entry("g-1", 0, p_value=0.01), _entry("g-2", 0, p_value=0.02)])

    # Simulate a crash mid-write: append a syntactically incomplete JSON line with no trailing newline.
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"genome_id": "g-3", "generation": 0, "purpose": "tradi')

    entries = ledger.entries()
    assert {e.genome_id for e in entries} == {"g-1", "g-2"}  # truncated line dropped, not raised

    # The ledger remains writable afterwards -- a restart does not get stuck behind the bad tail, and
    # `record` does not raise just because the file it is appending to ends mid-line.
    ledger.record([_entry("g-4", 1, p_value=0.03)])


def test_ledger_raises_on_a_corrupt_line_that_is_not_the_last(tmp_path: Path) -> None:
    """A malformed line that is *not* the final one is real corruption, not a mid-write crash, and
    must not be silently dropped -- see `Ledger.entries`'s own docstring."""
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        "not valid json at all\n" + json.dumps({"genome_id": "g-1"}) + "\n", encoding="utf-8"
    )
    ledger = Ledger(path)
    try:
        ledger.entries()
    except (json.JSONDecodeError, KeyError, ValueError):
        pass
    else:
        raise AssertionError("expected a real parse failure on a non-final corrupt line")


# ---------------------------------------------------------------------------
# ledger_entries_for -- basic correctness (closed_trades / wins read from real run files)
# ---------------------------------------------------------------------------


def test_ledger_entries_for_reads_real_closed_trade_counts(tmp_path: Path) -> None:
    round_id = "r-test-ledger"
    rounds_root = tmp_path / "rounds"

    # 12 closed trades across the six selection windows (2 per window), 8 winners, 4 losers --
    # enough to clear MIN_CLOSED_TRADES_FOR_P_VALUE (10).
    trades_by_window = {
        "bear-2022": [_trade_payload("10"), _trade_payload("10")],
        "chop-2015": [_trade_payload("10"), _trade_payload("10")],
        "chop-2011": [_trade_payload("10"), _trade_payload("-10")],
        "bull-2024": [_trade_payload("10"), _trade_payload("-10")],
        "recent": [_trade_payload("10"), _trade_payload("-10")],
        "gfc": [_trade_payload("10"), _trade_payload("-10")],
    }
    for window, trades in trades_by_window.items():
        _write_run_file(
            rounds_root, round_id, window, "cand-a",
            _run_payload("cand-a", ending_equity="10500.00", trades=trades),
        )

    genomes = {"cand-a": _genome("cand-a")}
    settings = _settings(tmp_path, rounds_dir=rounds_root)
    config = _default_config()

    standings = read_standings(
        round_id=round_id,
        purpose=Purpose.TRADING,
        genomes=genomes,
        config=config,
        settings=settings,
        selection_windows=SELECTION_WINDOWS,
        holdout_windows=(),
    )

    entries = ledger_entries_for(
        standings,
        round_id=round_id,
        purpose=Purpose.TRADING,
        generation=0,
        selection_windows=SELECTION_WINDOWS,
        settings=settings,
    )

    assert len(entries) == 1
    entry = entries[0]
    assert entry.closed_trades == 12
    assert entry.wins == 8
    assert entry.p_value is not None  # 12 >= MIN_CLOSED_TRADES_FOR_P_VALUE


def test_ledger_entries_for_honours_a_non_default_rounds_root(tmp_path: Path) -> None:
    round_id = "r-test-ledger-root"
    custom_root = tmp_path / "loop_owned" / "rounds"

    for window in SELECTION_WINDOWS:
        _write_run_file(custom_root, round_id, window, "cand-a", _run_payload("cand-a", ending_equity="11000.00"))

    genomes = {"cand-a": _genome("cand-a")}
    settings = _settings(tmp_path, rounds_dir=tmp_path / "unused_default")
    config = _default_config()

    standings = read_standings(
        round_id=round_id,
        purpose=Purpose.TRADING,
        genomes=genomes,
        config=config,
        settings=settings,
        selection_windows=SELECTION_WINDOWS,
        holdout_windows=(),
        rounds_root=custom_root,
    )
    entries = ledger_entries_for(
        standings,
        round_id=round_id,
        purpose=Purpose.TRADING,
        generation=0,
        selection_windows=SELECTION_WINDOWS,
        settings=settings,
        rounds_root=custom_root,
    )
    assert len(entries) == 1
    assert entries[0].closed_trades == 12  # 2 trades x 6 windows, from _run_payload's default trades


# ---------------------------------------------------------------------------
# field_window_medians -- feeds the regime finding
# ---------------------------------------------------------------------------


def test_field_window_medians_and_regime_finding(tmp_path: Path) -> None:
    round_id = "r-test-regime"
    rounds_root = tmp_path / "rounds"

    endings = {
        "bear-2022": "9000.00",  # worst window: excess = -0.10
        "chop-2015": "10500.00",
        "chop-2011": "10500.00",
        "bull-2024": "10500.00",
        "recent": "10500.00",
        "gfc": "10500.00",
    }
    for window, ending in endings.items():
        _write_run_file(rounds_root, round_id, window, "cand-a", _run_payload("cand-a", ending_equity=ending))

    genomes = {"cand-a": _genome("cand-a")}
    settings = _settings(tmp_path, rounds_dir=rounds_root)

    medians = field_window_medians(
        round_id, purpose=Purpose.TRADING, genomes=genomes, windows=SELECTION_WINDOWS, settings=settings
    )
    assert medians["bear-2022"] == Decimal("9000.00") / Decimal("10000.00") - 1

    standing = _standing("cand-a", rank=1, median_excess=Decimal("0.03"), holdout_median_excess=Decimal("0.02"))
    findings = derive_findings(
        standings=(standing,),
        config=LoopConfig(),
        purpose=Purpose.TRADING,
        selection_windows=SELECTION_WINDOWS,
        holdout_windows=HOLDOUT_WINDOWS,
        genomes=genomes,
        window_medians=medians,
    )
    regime = next(f for f in findings if f.kind == "regime")
    assert regime.evidence["worst_window"] == "bear-2022"

    # Without window_medians, the regime finding still fires, just without naming a window.
    findings_without = derive_findings(
        standings=(standing,),
        config=LoopConfig(),
        purpose=Purpose.TRADING,
        selection_windows=SELECTION_WINDOWS,
        holdout_windows=HOLDOUT_WINDOWS,
        genomes=genomes,
    )
    regime_without = next(f for f in findings_without if f.kind == "regime")
    assert "worst_window" not in regime_without.evidence


# ---------------------------------------------------------------------------
# The exposure correction
# ---------------------------------------------------------------------------


class _FakeRun:
    """Only the three fields `_adjusted_value` is allowed to read, plus the one it must not."""

    def __init__(self, corrected, benchmark, capital_exposure, exposure=Decimal("1.0")):
        self.corrected_return = corrected
        self.benchmark_return = benchmark
        self.capital_exposure = capital_exposure
        self.exposure = exposure


class TestAdjustedValue:
    def test_subtracts_exposure_times_benchmark(self) -> None:
        """The measured `gfc` case: a card holding 19% of capital that lost 29.69% against a -56.23%
        benchmark reads as +26.53% on plain excess and -19.01% adjusted. The first says it beat the
        market; the second says it did worse than a passive position of its own size."""
        run = _FakeRun(Decimal("-0.2969"), Decimal("-0.5623"), 0.19)
        value = feedback._adjusted_value(run)
        assert value is not None
        assert value.quantize(Decimal("0.0001")) == Decimal("-0.1901")

    def test_float_exposure_does_not_raise(self) -> None:
        """`capital_exposure` is a `float` on `ScoredRun` while the returns are `Decimal`, and
        `float * Decimal` is a TypeError rather than a coercion -- this shipped broken once."""
        assert feedback._adjusted_value(_FakeRun(Decimal("0.1"), Decimal("0.2"), 0.5)) is not None

    def test_returns_none_when_capital_exposure_is_missing_rather_than_using_exposure(self) -> None:
        """The whole reason `ScoredRun.adjusted_excess` refuses non-`entry-notional` runs is that a
        reader gating on data would fall back to `exposure` -- session presence, which sits near 1.0
        for an allocation book -- and return a confident wrong number. This must refuse instead."""
        run = _FakeRun(Decimal("-0.30"), Decimal("-0.56"), None, exposure=Decimal("0.97"))
        assert feedback._adjusted_value(run) is None

    def test_returns_none_without_a_benchmark(self) -> None:
        assert feedback._adjusted_value(_FakeRun(Decimal("0.1"), None, 0.5)) is None

    def test_a_fully_invested_card_adjusts_to_plain_excess(self) -> None:
        """At `capital_exposure == 1` the correction is the identity -- the two metrics only diverge
        for a card that is not fully deployed, which is the case the correction exists for."""
        run = _FakeRun(Decimal("0.10"), Decimal("-0.20"), 1.0)
        assert feedback._adjusted_value(run) == Decimal("0.10") - Decimal("-0.20")


# ---------------------------------------------------------------------------
# Findings prose states its units -- found on screen, not by a test
# ---------------------------------------------------------------------------


class TestFindingSummariesAreInPoints:
    """A browser pass over the live Generations panel found this rendered verbatim:

        auto g1867 · mean-reversion (roth) (g1867-a97f787ebcc8) led the field with median excess
        0.07894444217223358327652806180.

    Twenty-nine significant digits of an unlabelled *fraction*, where every margin it will be
    compared against -- `promotion_margin_pp`, `NOISE_FLOOR_PP` -- is in percentage points. The
    holdout summary was worse: it already converted `drop_pp` correctly and labelled it `pp`, then
    printed the two medians raw in the same sentence, so one line carried both conventions.

    Same family as the promotion reason that read "median excess 0.2572...pp > 21.2pp margin" --
    a card apparently failing the gate it had just cleared. In all three places the *stored* figure
    was right and only the sentence was wrong, which is exactly why it survived: nothing the loop
    computes ever passes through this prose.
    """

    def test_the_winner_summary_reads_in_points(self) -> None:
        winner = _standing("g1", rank=1, median_excess=Decimal("0.07894444217223358327652806180"))

        finding = feedback._winner_finding(winner)

        assert "+7.89pp" in finding.summary
        assert "0.078944" not in finding.summary
        assert finding.evidence["median_excess"] == "0.07894444217223358327652806180", (
            "evidence keeps full precision -- only the prose is rounded"
        )

    def test_a_negative_excess_keeps_its_sign(self) -> None:
        finding = feedback._winner_finding(
            _standing("g1", rank=1, median_excess=Decimal("-0.01422712556528432598864620418"))
        )
        assert "-1.42pp" in finding.summary

    def test_an_unmeasured_median_says_so_rather_than_printing_none(self) -> None:
        assert feedback._pp(None) == "not measured"

    def test_the_holdout_summary_does_not_mix_conventions(self) -> None:
        """`drop = X pp` beside two raw fractions was the actual rendered sentence."""
        winner = _standing(
            "g1",
            rank=1,
            median_excess=Decimal("0.07894444217223358327652806180"),
            holdout_median_excess=Decimal("0.02345678901234567890123456789"),
        )

        summary = feedback._holdout_finding(winner, config=LoopConfig()).summary

        assert "+7.89pp" in summary
        assert "+2.35pp" in summary
        assert "drop = 5.55pp" in summary
        assert "0.0789" not in summary and "0.0234" not in summary
