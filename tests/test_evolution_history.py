"""Tests for `app.evolution.history`.

Every fixture here builds a synthetic `gen{N:04d}/` tree under `tmp_path` -- never `data/loop/` --
using real `GenerationOutcome.model_dump_json()` output so the on-disk shape these tests parse is
identical to what `app.evolution.loop._write_outcome_file` actually writes, not a hand-approximated
stand-in. `tests/test_api_evolution.py` covers the HTTP layer (status codes, query-param wiring); this
file covers the reader and the statistics underneath it.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from decimal import Decimal
from pathlib import Path

from app.config import Settings
from app.evolution import history
from app.evolution.models import Finding, GenerationOutcome, Standing
from app.tournament.purposes import Purpose

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

_START = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)


def _standing(
    genome_id: str,
    *,
    rank: int = 1,
    eligible: bool = True,
    windows_run: int = 5,
    median_excess: str | None = "0.05",
    worst_excess: str | None = "-0.02",
    hit_rate: float | None = 0.6,
    total_trades: int = 10,
    holdout_median_excess: str | None = "0.03",
    q_value: float | None = 0.01,
) -> Standing:
    return Standing(
        genome_id=genome_id,
        agent_id=genome_id,
        display_name=f"card {genome_id}",
        rank=rank,
        eligible=eligible,
        windows_run=windows_run,
        median_excess=None if median_excess is None else Decimal(median_excess),
        worst_excess=None if worst_excess is None else Decimal(worst_excess),
        hit_rate=hit_rate,
        total_trades=total_trades,
        holdout_median_excess=None if holdout_median_excess is None else Decimal(holdout_median_excess),
        q_value=q_value,
    )


def _gate_finding(cleared: int, eligible: int, margin_pp: str = "21.2") -> Finding:
    return Finding(
        kind="gate",
        summary=f"{cleared} of {eligible} cleared.",
        evidence={"cleared": cleared, "eligible": eligible, "margin_pp": margin_pp, "cleared_genome_ids": ()},
    )


def _outcome(
    generation: int,
    *,
    status: str = "succeeded",
    purpose: Purpose = Purpose.TRADING,
    standings: tuple[Standing, ...] = (),
    findings: tuple[Finding, ...] = (),
    error: str | None = None,
    genome_ids: tuple[str, ...] | None = None,
    promoted: tuple[str, ...] = (),
    minutes_offset: int = 0,
) -> GenerationOutcome:
    started = _START + dt.timedelta(minutes=minutes_offset)
    return GenerationOutcome(
        generation=generation,
        round_id=f"r1-auto-gen{generation:04d}",
        purpose=purpose,
        status=status,
        started_at=started,
        finished_at=started + dt.timedelta(seconds=30),
        windows=("chop-2015", "recent"),
        holdout_windows=("covid",),
        genome_ids=genome_ids if genome_ids is not None else tuple(s.genome_id for s in standings),
        standings=standings,
        findings=findings,
        promoted=promoted,
        error=error,
    )


def _write_generation(
    root: Path,
    generation: int,
    *,
    outcome: GenerationOutcome | None = None,
    raw_outcome: str | None = None,
    plan: str | None = "# plan\n",
    review: dict | None = None,
) -> Path:
    """Writes `gen{N:04d}/` under `root` (== `loop_root(settings)`). Exactly one of `outcome`/
    `raw_outcome` should be given; `raw_outcome` lets a test write a zero-byte or malformed file
    directly, matching the two real failure shapes this reader has to survive."""
    gen_dir = root / f"gen{generation:04d}"
    gen_dir.mkdir(parents=True, exist_ok=True)
    if plan is not None:
        (gen_dir / "PLAN.md").write_text(plan, encoding="utf-8")
    if raw_outcome is not None:
        (gen_dir / "OUTCOME.json").write_text(raw_outcome, encoding="utf-8")
    elif outcome is not None:
        (gen_dir / "OUTCOME.json").write_text(outcome.model_dump_json(indent=2), encoding="utf-8")
    if review is not None:
        (gen_dir / "REVIEW.json").write_text(json.dumps(review), encoding="utf-8")
    return gen_dir


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", rounds_dir=tmp_path / "data" / "rounds")


# ---------------------------------------------------------------------------
# Empty tree -- never 404, never raises
# ---------------------------------------------------------------------------


def test_empty_tree_yields_empty_list_not_an_error(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    page, total, unreadable = history.list_generations(settings)
    assert page == []
    assert total == 0
    assert unreadable == 0
    assert history.get_generation(settings, 1) is None
    assert history.failure_streaks(settings) == ()


# ---------------------------------------------------------------------------
# Pagination and ordering
# ---------------------------------------------------------------------------


def test_generations_are_newest_first_and_paginate(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    for gen in range(1, 6):
        _write_generation(root, gen, outcome=_outcome(gen, minutes_offset=gen))

    page, total, unreadable = history.list_generations(settings, limit=2, offset=0)
    assert total == 5
    assert unreadable == 0
    assert [g.generation for g in page] == [5, 4]

    page2, total2, _ = history.list_generations(settings, limit=2, offset=2)
    assert total2 == 5
    assert [g.generation for g in page2] == [3, 2]

    page3, _, _ = history.list_generations(settings, limit=2, offset=4)
    assert [g.generation for g in page3] == [1]


def test_total_reflects_the_filter_not_the_page(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    for gen in range(1, 4):
        _write_generation(root, gen, outcome=_outcome(gen, status="succeeded", minutes_offset=gen))
    for gen in range(4, 9):
        _write_generation(root, gen, outcome=_outcome(gen, status="failed", error="boom", minutes_offset=gen))

    page, total, unreadable = history.list_generations(settings, limit=1, succeeded_only=True)
    assert total == 3
    assert len(page) == 1
    assert unreadable == 0

    _page_all, total_all, _ = history.list_generations(settings, limit=1)
    assert total_all == 8


def test_purpose_and_status_filters(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    _write_generation(root, 1, outcome=_outcome(1, purpose=Purpose.TRADING, status="succeeded"))
    _write_generation(root, 2, outcome=_outcome(2, purpose=Purpose.ROTH, status="succeeded"))
    _write_generation(root, 3, outcome=_outcome(3, purpose=Purpose.TRADING, status="cancelled"))

    page, total, _ = history.list_generations(settings, purpose="roth")
    assert total == 1
    assert page[0].generation == 2

    page, total, _ = history.list_generations(settings, status="cancelled")
    assert total == 1
    assert page[0].generation == 3


# ---------------------------------------------------------------------------
# A generation with zero standings -> null field stats, not zeros
# ---------------------------------------------------------------------------


def test_generation_with_no_standings_has_null_field_stats(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    outcome = _outcome(1, status="failed", error="OSError: read-only", standings=(), genome_ids=("g1",))
    _write_generation(root, 1, outcome=outcome)

    page, total, unreadable = history.list_generations(settings)
    assert total == 1
    assert unreadable == 0
    summary = page[0]
    assert summary.candidates == 1
    assert summary.ranked == 0
    assert summary.eligible == 0
    assert summary.field.median_excess is None
    assert summary.field.worst_excess is None
    assert summary.field.hit_rate is None
    assert summary.field.holdout_median is None
    assert summary.field.holdout_gap_pp is None
    assert summary.field.total_trades is None
    assert summary.field.q_value is None
    assert summary.leader is None
    assert summary.gate.cleared == 0
    assert summary.gate.eligible == 0


# ---------------------------------------------------------------------------
# Zero-byte / malformed OUTCOME.json -> unreadable, never raises
# ---------------------------------------------------------------------------


def test_zero_byte_outcome_file_counts_as_unreadable(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    # Exactly the real failure mode found in data/loop/gen1673/OUTCOME.json: a process died mid-write,
    # leaving a zero-byte file with no PLAN.md sibling either.
    _write_generation(root, 1673, raw_outcome="", plan=None)

    page, total, unreadable = history.list_generations(settings)
    assert page == []
    assert total == 0
    assert unreadable == 1
    assert history.get_generation(settings, 1673) is None


def test_malformed_json_counts_as_unreadable_not_a_500(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    _write_generation(root, 2, raw_outcome="{not valid json")

    page, total, unreadable = history.list_generations(settings)
    assert page == []
    assert total == 0
    assert unreadable == 1


def test_schema_invalid_json_counts_as_unreadable(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    # Valid JSON, wrong shape entirely -- missing every required GenerationOutcome field.
    _write_generation(root, 3, raw_outcome=json.dumps({"hello": "world"}))

    _page, total, unreadable = history.list_generations(settings)
    assert total == 0
    assert unreadable == 1


def test_in_progress_generation_missing_outcome_counts_as_unreadable_until_written(tmp_path: Path) -> None:
    """A generation mid-run has PLAN.md but no OUTCOME.json yet -- `app.evolution.loop` writes the
    plan first. It must read the same way a corrupt file does (unreadable, not yet listable) and must
    become visible the moment OUTCOME.json is written, proving the cache invalidates correctly."""
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    gen_dir = _write_generation(root, 1, plan="# plan\n")  # no outcome argument -> no OUTCOME.json

    _, total, unreadable = history.list_generations(settings)
    assert total == 0
    assert unreadable == 1

    # The generation "finishes": OUTCOME.json is written into the already-existing directory, exactly
    # the write order app.evolution.loop._write_outcome_file uses.
    (gen_dir / "OUTCOME.json").write_text(_outcome(1).model_dump_json(), encoding="utf-8")

    page, total, unreadable = history.list_generations(settings)
    assert total == 1
    assert unreadable == 0
    assert page[0].generation == 1


# ---------------------------------------------------------------------------
# holdout_gap_pp excludes candidates missing either side
# ---------------------------------------------------------------------------


def test_holdout_gap_pp_excludes_candidates_missing_either_side(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    standings = (
        _standing("g1", median_excess="0.10", holdout_median_excess="0.04"),  # gap = 6pp
        _standing("g2", median_excess="0.20", holdout_median_excess="0.05"),  # gap = 15pp
        _standing("g3", median_excess="0.30", holdout_median_excess=None),  # excluded: no holdout
        _standing("g4", median_excess=None, holdout_median_excess="0.01"),  # excluded: no selection
    )
    outcome = _outcome(1, standings=standings, findings=(_gate_finding(0, 3),))
    _write_generation(root, 1, outcome=outcome)

    page, _, _ = history.list_generations(settings)
    gap = page[0].field.holdout_gap_pp
    assert gap is not None
    assert gap.n == 2
    assert gap.min == Decimal("6.00")
    assert gap.max == Decimal("15.00")


# ---------------------------------------------------------------------------
# StatSummary itself
# ---------------------------------------------------------------------------


def test_stat_summary_single_value(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    standings = (_standing("g1", median_excess="0.05"),)
    _write_generation(root, 1, outcome=_outcome(1, standings=standings, findings=(_gate_finding(0, 1),)))

    page, _, _ = history.list_generations(settings)
    stat = page[0].field.median_excess
    assert stat is not None
    assert stat.n == 1
    assert stat.min == stat.p25 == stat.median == stat.p75 == stat.max == stat.mean == Decimal("0.05")


def test_stat_summary_matches_statistics_median_for_a_small_field(tmp_path: Path) -> None:
    import statistics as stdlib_statistics

    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    values = ["0.01", "0.02", "0.03", "0.04", "0.05"]
    standings = tuple(_standing(f"g{i}", median_excess=v) for i, v in enumerate(values))
    _write_generation(root, 1, outcome=_outcome(1, standings=standings, findings=(_gate_finding(0, 5),)))

    page, _, _ = history.list_generations(settings)
    stat = page[0].field.median_excess
    assert stat is not None
    expected_median = stdlib_statistics.median(Decimal(v) for v in values)
    assert stat.median == expected_median
    assert stat.n == 5


# ---------------------------------------------------------------------------
# Gate stats read the "gate" finding, not the "goal" finding sharing the same kind
# ---------------------------------------------------------------------------


def test_gate_stats_pick_the_gate_finding_over_a_goal_finding_sharing_the_same_kind(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    goal_finding = Finding(
        kind="gate",
        summary="goal progress finding, also kind=gate",
        evidence={"goal": "test", "current_value": "0.1", "rank_by": "median"},
    )
    gate_finding = _gate_finding(2, 5, margin_pp="21.2")
    standings = (_standing("g1"),)
    outcome = _outcome(1, standings=standings, findings=(goal_finding, gate_finding))
    _write_generation(root, 1, outcome=outcome)

    page, _, _ = history.list_generations(settings)
    gate = page[0].gate
    assert gate.cleared == 2
    assert gate.eligible == 5
    assert gate.margin_pp == Decimal("21.2")


# ---------------------------------------------------------------------------
# Failure-streak collapsing
# ---------------------------------------------------------------------------


def test_failure_streaks_merge_consecutive_same_error(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    for gen in range(1, 6):
        _write_generation(
            root, gen, outcome=_outcome(gen, status="failed", error="OSError: read-only", minutes_offset=gen)
        )

    streaks = history.failure_streaks(settings)
    assert len(streaks) == 1
    assert streaks[0].first_generation == 1
    assert streaks[0].last_generation == 5
    assert streaks[0].count == 5
    assert streaks[0].error == "OSError: read-only"
    # Every generation in this streak used `_outcome`'s default purpose (trading), so this is the
    # single-lane case a purpose filter is meant to keep: exactly one element, not zero and not five.
    assert streaks[0].purposes == ("trading",)


def test_failure_streaks_report_every_purpose_the_streak_spans(tmp_path: Path) -> None:
    """`app.evolution.loop` cycles purposes round-robin across generations, so a run of consecutive,
    identically-failing generation *numbers* can span more than one lane. The streak itself must not
    split on that -- same status, same error, consecutive numbers is still the only grouping rule --
    but `purposes` must report every lane the run actually touched, sorted and deduplicated."""
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    _write_generation(
        root, 1, outcome=_outcome(1, status="failed", error="errorA", purpose=Purpose.TRADING, minutes_offset=1)
    )
    _write_generation(
        root, 2, outcome=_outcome(2, status="failed", error="errorA", purpose=Purpose.ROTH, minutes_offset=2)
    )
    _write_generation(
        root, 3, outcome=_outcome(3, status="failed", error="errorA", purpose=Purpose.TRADING, minutes_offset=3)
    )

    streaks = history.failure_streaks(settings)
    assert len(streaks) == 1
    assert streaks[0].count == 3
    assert streaks[0].purposes == ("roth", "trading")


def test_failure_streaks_split_on_a_different_error(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    for gen in range(1, 4):
        _write_generation(root, gen, outcome=_outcome(gen, status="failed", error="errorA", minutes_offset=gen))
    for gen in range(4, 6):
        _write_generation(root, gen, outcome=_outcome(gen, status="failed", error="errorB", minutes_offset=gen))

    streaks = history.failure_streaks(settings)
    assert len(streaks) == 2
    # Newest first.
    assert streaks[0].first_generation == 4
    assert streaks[0].last_generation == 5
    assert streaks[0].error == "errorB"
    assert streaks[1].first_generation == 1
    assert streaks[1].last_generation == 3
    assert streaks[1].error == "errorA"


def test_failure_streaks_split_on_an_intervening_success(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    _write_generation(root, 1, outcome=_outcome(1, status="failed", error="errorA", minutes_offset=1))
    _write_generation(root, 2, outcome=_outcome(2, status="failed", error="errorA", minutes_offset=2))
    _write_generation(
        root,
        3,
        outcome=_outcome(
            3,
            status="succeeded",
            standings=(_standing("g3"),),
            findings=(_gate_finding(0, 1),),
            minutes_offset=3,
        ),
    )
    _write_generation(root, 4, outcome=_outcome(4, status="failed", error="errorA", minutes_offset=4))

    streaks = history.failure_streaks(settings)
    assert len(streaks) == 2
    assert streaks[0].first_generation == 4
    assert streaks[0].last_generation == 4
    assert streaks[1].first_generation == 1
    assert streaks[1].last_generation == 2


def test_failure_streaks_split_on_an_unreadable_generation_in_between(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    _write_generation(root, 1, outcome=_outcome(1, status="failed", error="errorA", minutes_offset=1))
    _write_generation(root, 2, raw_outcome="")  # unreadable -- cannot be assumed to share the error
    _write_generation(root, 3, outcome=_outcome(3, status="failed", error="errorA", minutes_offset=3))

    streaks = history.failure_streaks(settings)
    assert len(streaks) == 2
    assert {(s.first_generation, s.last_generation) for s in streaks} == {(1, 1), (3, 3)}


def test_failure_streaks_split_on_a_generation_number_gap(tmp_path: Path) -> None:
    """Two `failed` generations sharing an error but with a missing directory between them (gen 2
    absent entirely, not merely unreadable) must not be merged into one streak."""
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    _write_generation(root, 1, outcome=_outcome(1, status="failed", error="errorA", minutes_offset=1))
    _write_generation(root, 3, outcome=_outcome(3, status="failed", error="errorA", minutes_offset=3))

    streaks = history.failure_streaks(settings)
    assert len(streaks) == 2


# ---------------------------------------------------------------------------
# Detail endpoint reader: 404 (None) for missing generation, null plan_markdown, review passthrough
# ---------------------------------------------------------------------------


def test_get_generation_returns_none_for_a_missing_generation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert history.get_generation(settings, 999) is None


def test_get_generation_reports_null_plan_when_plan_md_is_absent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    _write_generation(root, 1, outcome=_outcome(1), plan=None)

    detail = history.get_generation(settings, 1)
    assert detail is not None
    assert detail.plan_markdown is None
    assert detail.outcome.generation == 1


def test_get_generation_returns_plan_text_verbatim(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    _write_generation(root, 1, outcome=_outcome(1), plan="# Generation 1 plan\n\nSome text.\n")

    detail = history.get_generation(settings, 1)
    assert detail is not None
    assert detail.plan_markdown == "# Generation 1 plan\n\nSome text.\n"


def test_review_passes_through_unknown_keys_untouched(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    review_payload = {"verdict": "solid", "nested": {"a": 1, "b": [1, 2, 3]}, "score": 4.5}
    _write_generation(root, 1, outcome=_outcome(1), review=review_payload)

    page, _, _ = history.list_generations(settings)
    assert page[0].has_review is True

    detail = history.get_generation(settings, 1)
    assert detail is not None
    assert detail.review == review_payload


def test_no_review_file_means_null_review_and_has_review_false(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    _write_generation(root, 1, outcome=_outcome(1))

    page, _, _ = history.list_generations(settings)
    assert page[0].has_review is False

    detail = history.get_generation(settings, 1)
    assert detail is not None
    assert detail.review is None


# ---------------------------------------------------------------------------
# Cache correctness: a directory rewritten in place is detected, not silently ignored
# ---------------------------------------------------------------------------


def test_cache_reflects_a_newly_added_generation_without_restarting(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    _write_generation(root, 1, outcome=_outcome(1))

    _, total_before, _ = history.list_generations(settings)
    assert total_before == 1

    _write_generation(root, 2, outcome=_outcome(2, minutes_offset=1))
    _, total_after, _ = history.list_generations(settings)
    assert total_after == 2


# ---------------------------------------------------------------------------
# Measured cold-path cost against a synthetic 1,673-directory tree
#
# The real data/loop/ tree in this environment holds only 30 generation directories today (see this
# module's own docstring and this task's final report for that finding), not the 1,673 the brief
# describes -- so this test builds a synthetic tree at that scale, in the same 27-succeeded /
# 1,644-failed / 1-cancelled / 1-unreadable mix, and prints the measured cold and warm costs.
# ---------------------------------------------------------------------------


def test_measured_cost_against_synthetic_1673_tree(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    root = settings.data_dir / "loop"
    root.mkdir(parents=True)

    succeeded_standings = tuple(
        _standing(f"g{i:03d}", median_excess=f"0.{i:02d}", holdout_median_excess=f"0.0{i % 9}")
        for i in range(10)
    )
    for gen in range(1, 28):
        outcome = _outcome(
            gen,
            standings=succeeded_standings,
            findings=(_gate_finding(2, 10),),
            minutes_offset=gen,
        )
        _write_generation(root, gen, outcome=outcome)
    for gen in range(28, 1672):
        outcome = _outcome(
            gen,
            status="failed",
            error="OSError: [Errno 30] Read-only file system",
            genome_ids=tuple(f"g{gen}-{i}" for i in range(10)),
            minutes_offset=gen,
        )
        _write_generation(root, gen, outcome=outcome, plan="# plan\n")
    _write_generation(
        root, 1672, outcome=_outcome(1672, status="cancelled", genome_ids=("g1672-0",), minutes_offset=1672)
    )
    _write_generation(root, 1673, raw_outcome="", plan=None)  # the real zero-byte case, at scale

    started = time.perf_counter()
    _page, total, unreadable = history.list_generations(settings, limit=50)
    cold_seconds = time.perf_counter() - started
    assert total == 1672  # 1673 dirs minus the one unreadable
    assert unreadable == 1

    started_warm = time.perf_counter()
    history.list_generations(settings, limit=50)
    warm_seconds = time.perf_counter() - started_warm

    print(
        f"\n[history cost] cold: {cold_seconds:.3f}s for 1673 dirs "
        f"({1673 / cold_seconds:.0f} dirs/s); warm (nothing changed): {warm_seconds * 1000:.1f}ms"
    )
    # Not a hard performance assertion (CI hardware varies) -- the printed numbers are what the module
    # docstring's measured figures came from. The one thing asserted is the *shape* of the win: a
    # repeat call over an unchanged tree must not cost anywhere near what the cold call did.
    assert warm_seconds < cold_seconds
