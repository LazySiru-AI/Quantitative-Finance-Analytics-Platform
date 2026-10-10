"""Tests for `app.evolution.digest` and its HTTP surface, `app.api.evolution_journal`.

Follows `tests/test_evolution_seating.py`'s own fixture style: a `settings` fixture whose `data_dir`
starts empty (so `loop_root` and every file under it start absent -- the state a first-ever digest has
to cope with), and small helpers that write exactly the JSON/Markdown shape the real writers
(`app.evolution.loop._write_outcome_file` / `_write_plan_file`) produce, rather than going through
those functions (this workstream does not own `loop.py`).
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import evolution_journal
from app.config import Settings
from app.evolution import digest
from app.evolution import loop as loop_module
from app.evolution.models import Finding, GenerationOutcome, Standing, loop_root
from app.tournament.purposes import Purpose


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(repo_root=tmp_path, data_dir=tmp_path / "data")


# ---------------------------------------------------------------------------
# Helpers -- write exactly the on-disk shapes `write_digest` reads
# ---------------------------------------------------------------------------


def _standing(
    genome_id: str,
    *,
    rank: int = 1,
    median_excess: str | None = "0.2000",
    holdout_median_excess: str | None = "0.1500",
    eligible: bool = True,
) -> Standing:
    return Standing(
        genome_id=genome_id,
        agent_id=genome_id,
        display_name=f"auto {genome_id}",
        rank=rank,
        eligible=eligible,
        windows_run=5,
        median_excess=None if median_excess is None else Decimal(median_excess),
        worst_excess=Decimal("-0.05"),
        hit_rate=0.6,
        total_trades=40,
        holdout_median_excess=(
            None if holdout_median_excess is None else Decimal(holdout_median_excess)
        ),
    )


def _goal_finding(
    *, previous_generation: int | None, direction: str = "improved over"
) -> Finding:
    evidence: dict[str, object] = {
        "goal": "test goal",
        "focus_symbols": [],
        "rank_by": "median",
        "focus_symbols_in_elite_universes": [],
        "focus_symbols_missing_from_elite_universes": [],
        "current_genome_id": "g0001-a",
        "current_value": "0.20",
    }
    if previous_generation is not None:
        evidence["previous_generation"] = previous_generation
        evidence["previous_genome_id"] = "g0000-a"
        evidence["previous_value"] = "0.10"
        evidence["delta_pp"] = "10.00"
        evidence["direction"] = direction
        summary = f"test goal: 'median' = 0.20 this generation {direction} 0.10 in generation {previous_generation}."
    else:
        summary = "This lane's first measured generation for test goal: 'median' = 0.20, with no prior generation in this lane yet to compare against."
    return Finding(kind="gate", summary=summary, evidence=evidence)


def _outcome(
    generation: int,
    *,
    purpose: Purpose = Purpose.ROTH,
    status: str = "succeeded",
    genome_ids: tuple[str, ...] = ("g0001-a", "g0001-b"),
    standings: tuple[Standing, ...] = (),
    findings: tuple[Finding, ...] = (),
    promoted: tuple[str, ...] = (),
    error: str | None = None,
    windows: tuple[str, ...] = ("gfc", "recent"),
    holdout_windows: tuple[str, ...] = ("covid",),
) -> GenerationOutcome:
    return GenerationOutcome(
        generation=generation,
        round_id=f"r1-auto-test-g{generation:04d}",
        purpose=purpose,
        job_id="job-1",
        status=status,  # type: ignore[arg-type]
        started_at=dt.datetime(2026, 8, 26, 10, 0, tzinfo=dt.UTC),
        finished_at=dt.datetime(2026, 8, 26, 10, 5, tzinfo=dt.UTC),
        windows=windows,
        holdout_windows=holdout_windows,
        genome_ids=genome_ids,
        standings=standings,
        findings=findings,
        promoted=promoted,
        error=error,
    )


def _write_outcome(settings: Settings, outcome: GenerationOutcome) -> Path:
    gen_dir = loop_root(settings) / f"gen{outcome.generation:04d}"
    gen_dir.mkdir(parents=True, exist_ok=True)
    path = gen_dir / "OUTCOME.json"
    path.write_text(outcome.model_dump_json(), encoding="utf-8")
    return path


def _write_plan(
    settings: Settings, generation: int, *, purpose: Purpose = Purpose.ROTH, candidates: tuple[tuple[str, str], ...] = ()
) -> Path:
    """`candidates` is `(genome_id, origin)` pairs, rendered in `_write_plan_file`'s own bullet
    format -- just enough of it for `_origin_counts` to parse."""
    gen_dir = loop_root(settings) / f"gen{generation:04d}"
    gen_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"# Generation {generation} plan", "", f"**Purpose:** {purpose.value}", "", "## Candidates", ""]
    for genome_id, origin in candidates:
        lines.append(f"- `{genome_id}` ({origin}, rules, parents=none) -- test candidate")
        lines.append("  - universe: SPY")
        lines.append('  - traits: {}')
    path = gen_dir / "PLAN.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_ledger(settings: Settings, rows: list[dict[str, object]]) -> Path:
    path = loop_root(settings) / "ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def _mkdir_gen(settings: Settings, generation: int) -> None:
    """A bare generation directory with nothing in it -- enough for gap detection to see it exists."""
    (loop_root(settings) / f"gen{generation:04d}").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# render_digest -- determinism
# ---------------------------------------------------------------------------


class TestRenderDigestDeterminism:
    def test_two_calls_with_identical_arguments_are_byte_identical(self) -> None:
        outcome = _outcome(
            5,
            standings=(_standing("g0005-a"),),
            findings=(Finding(kind="winner", summary="g0005-a won.", evidence={}),),
            promoted=("g0005-a",),
        )
        field_stats = digest._field_snapshot(outcome.standings)
        caveat = digest.CaveatStats(positive=100, total=105, candidates_ever_run=110)

        kwargs = dict(
            previous_outcome=None,
            previous_generation=None,
            previous_gap=None,
            previous_unreadable_reason=None,
            next_generation=None,
            plan_markdown="# plan\n\n## Candidates\n\n- `g0005-a` (random, rules, parents=none) -- x\n",
            field_stats=field_stats,
            caveat=caveat,
        )
        first = digest.render_digest(outcome, **kwargs)
        second = digest.render_digest(outcome, **kwargs)
        assert first == second

    def test_no_adjectives_leak_into_the_text(self) -> None:
        """A blunt guard against the exact failure mode the brief calls out: no unearned adjective
        in the rendered digest."""
        outcome = _outcome(
            5,
            standings=(_standing("g0005-a"),),
            findings=(Finding(kind="winner", summary="g0005-a led.", evidence={}),),
        )
        field_stats = digest._field_snapshot(outcome.standings)
        caveat = digest.CaveatStats(positive=100, total=105, candidates_ever_run=110)
        text = digest.render_digest(
            outcome,
            previous_outcome=None,
            previous_generation=None,
            previous_gap=None,
            previous_unreadable_reason=None,
            next_generation=None,
            plan_markdown=None,
            field_stats=field_stats,
            caveat=caveat,
        )
        for banned in ("promising", "strong", "impressive", "great", "excellent"):
            assert banned not in text.lower()


# ---------------------------------------------------------------------------
# write_digest -- the normal case (a real previous generation, no gap)
# ---------------------------------------------------------------------------


class TestWriteDigestNormalCase:
    def test_normal_generation_differences_against_the_same_lane_previous_generation(
        self, settings: Settings
    ) -> None:
        _write_outcome(
            settings,
            _outcome(
                10,
                genome_ids=("g0010-a",),
                standings=(_standing("g0010-a", median_excess="0.10"),),
                findings=(_goal_finding(previous_generation=None),),
            ),
        )
        # Directories between 10 and 14 exist (a different lane interleaved), so there is no gap.
        _mkdir_gen(settings, 11)
        _mkdir_gen(settings, 12)
        _mkdir_gen(settings, 13)
        _write_outcome(
            settings,
            _outcome(
                14,
                genome_ids=("g0010-a", "g0014-b"),
                standings=(_standing("g0014-c", median_excess="0.30"),),
                findings=(_goal_finding(previous_generation=10),),
            ),
        )
        _write_plan(settings, 14, candidates=(("g0014-b", "random"), ("g0014-c", "mutation")))

        markdown, changed = digest.write_digest(14, settings=settings, dry_run=True)

        assert changed is True
        assert "## Generation 14 · Roth · succeeded ·" in markdown
        assert "What changed since generation 10." in markdown
        assert "10.00% -> 30.00%" in markdown
        assert "1 of the previous generation's 1 candidate(s) carried forward" in markdown
        assert not (loop_root(settings) / "gen0014" / "DIGEST.md").exists(), "dry_run must not write"

    def test_apply_writes_the_file_and_is_idempotent(self, settings: Settings) -> None:
        _write_outcome(settings, _outcome(1, findings=(_goal_finding(previous_generation=None),)))
        markdown, changed = digest.write_digest(1, settings=settings, dry_run=False)
        assert changed is True
        path = digest.digest_path(settings, 1)
        assert path.read_text(encoding="utf-8") == markdown

        _, changed_again = digest.write_digest(1, settings=settings, dry_run=False)
        assert changed_again is False, "identical inputs must not rewrite the file a second time"


# ---------------------------------------------------------------------------
# _humanise_figures -- a presentation transform on the digest's own copy of finding text
# ---------------------------------------------------------------------------


class TestHumaniseFigures:
    def test_long_decimal_becomes_a_signed_percentage(self) -> None:
        before = (
            "holdout median (0.1487857552623824866024516738) is consistent with its selection "
            "median (0.2465181788788578626915809364): drop = 9.77pp against a 21.2pp margin."
        )
        after = digest._humanise_figures(before)
        assert "(+14.88%)" in after
        assert "(+24.65%)" in after
        # Already-formatted percentage-point figures must survive untouched.
        assert "9.77pp" in after
        assert "21.2pp" in after
        # Nothing but the two numerals' presentation changed.
        assert after.replace("+14.88%", "0.1487857552623824866024516738").replace(
            "+24.65%", "0.2465181788788578626915809364"
        ) == before

    def test_negative_long_decimal_becomes_a_signed_percentage(self) -> None:
        before = "worst median excess this generation was in 'bull-2024' (-0.1169003367454490237061650321)."
        after = digest._humanise_figures(before)
        assert "(-11.69%)" in after
        assert "0.1169003367454490237061650321" not in after

    def test_source_finding_text_is_never_modified(self) -> None:
        """The transform is applied to a copy for display; the `Finding` on disk (and in memory) is
        untouched -- `app.evolution.feedback`'s own module docstring is why that has to hold."""
        finding = Finding(
            kind="winner",
            summary="g0001-a led with median excess 0.2465181788788578626915809364.",
            evidence={},
        )
        original = finding.summary
        digest._humanise_figures(finding.summary)
        assert finding.summary == original
        assert finding.summary == "g0001-a led with median excess 0.2465181788788578626915809364."

    def test_short_decimals_are_left_exactly_as_is(self) -> None:
        """A trait mean, a q-value, and a margin -- none of them long enough to be an unambiguous
        measured-excess figure -- must not be touched."""
        text = "Trait 'band_pct': elite mean 0.196 vs field mean 0.0641667; q = 0.0049; margin 21.2."
        assert digest._humanise_figures(text) == text

    def test_rendered_digest_contains_no_bare_long_decimal(self, settings: Settings) -> None:
        _write_outcome(
            settings,
            _outcome(
                1,
                standings=(_standing("g0001-a"),),
                findings=(
                    Finding(
                        kind="winner",
                        summary="g0001-a led with median excess 0.2465181788788578626915809364.",
                        evidence={},
                    ),
                ),
            ),
        )
        markdown, _ = digest.write_digest(1, settings=settings, dry_run=True)
        assert "0.2465181788788578626915809364" not in markdown
        assert "+24.65%" in markdown


# ---------------------------------------------------------------------------
# next_generation -- lane-aware, never `generation + 1`
# ---------------------------------------------------------------------------


class TestNextGenerationIsLaneAware:
    def test_finds_the_real_later_generation_that_names_this_one_as_previous(
        self, settings: Settings
    ) -> None:
        _write_outcome(settings, _outcome(10, findings=(_goal_finding(previous_generation=None),)))
        _mkdir_gen(settings, 11)  # a different lane's generation, on disk between 10 and 14
        _mkdir_gen(settings, 12)
        _mkdir_gen(settings, 13)
        _write_outcome(settings, _outcome(14, findings=(_goal_finding(previous_generation=10),)))

        markdown, _ = digest.write_digest(10, settings=settings, dry_run=True)

        assert "**What generation 14 will try.**" in markdown
        assert "What generation 11 will try" not in markdown

    def test_live_write_with_no_later_generation_yet_does_not_guess(
        self, settings: Settings
    ) -> None:
        """The common live case: `write_digest` is called right after this generation's own
        `OUTCOME.json` is written, before anything later exists on disk."""
        _write_outcome(settings, _outcome(10, findings=(_goal_finding(previous_generation=None),)))

        markdown, _ = digest.write_digest(10, settings=settings, dry_run=True)

        assert "What generation 11 will try" not in markdown
        assert "**What the next generation in this lane will try.**" in markdown

    def test_unreadable_generation_also_gets_a_lane_aware_next_when_one_exists(
        self, settings: Settings
    ) -> None:
        (loop_root(settings) / "gen0005").mkdir(parents=True, exist_ok=True)  # unreadable
        _write_outcome(settings, _outcome(6, findings=(_goal_finding(previous_generation=5),)))

        markdown, _ = digest.write_digest(5, settings=settings, dry_run=True)

        assert "**What generation 6 will try.**" in markdown


# ---------------------------------------------------------------------------
# The gap case
# ---------------------------------------------------------------------------


class TestGapHandling:
    def test_far_apart_previous_generation_is_not_differenced_against(
        self, settings: Settings
    ) -> None:
        """`previous_generation` names a real earlier generation, but nothing exists on disk between
        it and the current one -- must not compute a field-median delta across the gap."""
        _write_outcome(settings, _outcome(10, standings=(_standing("g0010-a"),)))
        _write_outcome(
            settings,
            _outcome(500, findings=(_goal_finding(previous_generation=10),)),
        )

        markdown, _ = digest.write_digest(500, settings=settings, dry_run=True)

        assert "What changed since generation 10." in markdown
        assert "489 generation(s)" in markdown
        assert "no directory on disk at all" in markdown
        assert "->" not in markdown.split("What changed since generation 10.")[1].split("**What it found")[0], (
            "no field-median delta must be rendered across an unverified gap"
        )
        # Not the documented 28->1673 gap, so the specific OSError cause must not be invented here.
        assert "OSError" not in markdown

    def test_the_documented_gap_cites_its_known_cause(self, settings: Settings) -> None:
        """The exact numbers this repository's own gap has: `previous_generation=28`,
        `generation=1673`, 1,644 missing generation numbers between them."""
        _write_outcome(settings, _outcome(28, status="cancelled", standings=(), findings=()))
        _write_outcome(
            settings,
            _outcome(1673, findings=(_goal_finding(previous_generation=28),)),
        )
        markdown, _ = digest.write_digest(1673, settings=settings, dry_run=True)
        assert "1644 generation(s)" in markdown
        assert "OSError" in markdown
        assert "gen0029 through gen1672" in markdown

    def test_unreadable_generation_reports_the_gap_from_the_nearest_directory(
        self, settings: Settings
    ) -> None:
        """The unreadable branch has no `OUTCOME.json` to read a lane-aware previous generation
        from, so it falls back to the nearest existing directory on disk -- exercised here the same
        way the real `gen1673` (an empty `OUTCOME.json`) sits right after `gen0028` on this
        repository's own tree."""
        _write_outcome(settings, _outcome(28))
        gen_dir = loop_root(settings) / "gen1673"
        gen_dir.mkdir(parents=True, exist_ok=True)
        (gen_dir / "OUTCOME.json").write_text("", encoding="utf-8")  # zero bytes, like the real one

        markdown, _ = digest.write_digest(1673, settings=settings, dry_run=True)

        assert "unreadable" in markdown
        assert "present but empty (0 bytes)" in markdown
        assert "gen0028" in markdown
        assert "1644 generation(s)" in markdown
        assert "OSError" in markdown


# ---------------------------------------------------------------------------
# Failed / cancelled / unreadable generations still get a digest
# ---------------------------------------------------------------------------


class TestIncompleteGenerations:
    def test_failed_generation_names_its_error(self, settings: Settings) -> None:
        _write_outcome(
            settings,
            _outcome(3, status="failed", standings=(), findings=(), error="OSError: disk full"),
        )
        markdown, _ = digest.write_digest(3, settings=settings, dry_run=True)
        assert "· failed ·" in markdown
        assert "OSError: disk full" in markdown
        assert "No findings were derived for this generation (this generation failed" in markdown

    def test_cancelled_generation_with_no_error_says_so_plainly(self, settings: Settings) -> None:
        _write_outcome(
            settings, _outcome(3, status="cancelled", standings=(), findings=(), error=None)
        )
        markdown, _ = digest.write_digest(3, settings=settings, dry_run=True)
        assert "· cancelled ·" in markdown
        assert "no error was recorded" in markdown

    def test_missing_outcome_file_is_unreadable_not_an_exception(self, settings: Settings) -> None:
        (loop_root(settings) / "gen0007").mkdir(parents=True, exist_ok=True)
        markdown, changed = digest.write_digest(7, settings=settings, dry_run=True)
        assert changed is True
        assert "does not exist" in markdown
        assert "unreadable" in markdown

    def test_empty_outcome_file_is_unreadable(self, settings: Settings) -> None:
        gen_dir = loop_root(settings) / "gen0008"
        gen_dir.mkdir(parents=True, exist_ok=True)
        (gen_dir / "OUTCOME.json").write_text("", encoding="utf-8")
        markdown, _ = digest.write_digest(8, settings=settings, dry_run=True)
        assert "present but empty (0 bytes)" in markdown

    def test_malformed_json_is_unreadable(self, settings: Settings) -> None:
        gen_dir = loop_root(settings) / "gen0009"
        gen_dir.mkdir(parents=True, exist_ok=True)
        (gen_dir / "OUTCOME.json").write_text("{not json", encoding="utf-8")
        markdown, _ = digest.write_digest(9, settings=settings, dry_run=True)
        assert "is not valid JSON" in markdown

    def test_schema_invalid_json_is_unreadable(self, settings: Settings) -> None:
        gen_dir = loop_root(settings) / "gen0011"
        gen_dir.mkdir(parents=True, exist_ok=True)
        (gen_dir / "OUTCOME.json").write_text(json.dumps({"generation": "not an outcome"}), encoding="utf-8")
        markdown, _ = digest.write_digest(11, settings=settings, dry_run=True)
        assert "does not match the expected schema" in markdown

    def test_unreadable_generation_with_a_plan_reports_the_plan(self, settings: Settings) -> None:
        _write_plan(
            settings, 12, purpose=Purpose.TRADING, candidates=(("g0012-a", "random"), ("g0012-b", "news"))
        )
        markdown, _ = digest.write_digest(12, settings=settings, dry_run=True)
        assert "Trading" in markdown
        assert "2 candidate(s) were planned" in markdown
        assert "1 news, 1 random" in markdown


# ---------------------------------------------------------------------------
# Open questions
# ---------------------------------------------------------------------------


class TestOpenQuestions:
    def test_failure_holdout_contradiction_and_worsened_goal_are_open_questions(self) -> None:
        outcome = _outcome(
            20,
            standings=(_standing("g0020-a"),),
            findings=(
                Finding(kind="failure", summary="g0020-x took zero trades.", evidence={}),
                Finding(
                    kind="holdout",
                    summary="g0020-a's holdout contradicts its selection.",
                    evidence={"contradicts": True},
                ),
                Finding(
                    kind="holdout",
                    summary="g0020-b's holdout is consistent.",
                    evidence={"contradicts": False},
                ),
                _goal_finding(previous_generation=19, direction="worsened from"),
                Finding(kind="winner", summary="g0020-a won.", evidence={}),
            ),
        )
        field_stats = digest._field_snapshot(outcome.standings)
        caveat = digest.CaveatStats(positive=1, total=1, candidates_ever_run=1)
        text = digest.render_digest(
            outcome,
            previous_outcome=None,
            previous_generation=19,
            previous_gap=None,
            previous_unreadable_reason="`OUTCOME.json` does not exist",
            next_generation=21,
            plan_markdown=None,
            field_stats=field_stats,
            caveat=caveat,
        )
        open_section = text.split("What generation 21 will try.")[1]
        assert "g0020-x took zero trades." in open_section
        assert "g0020-a's holdout contradicts its selection." in open_section
        assert "worsened from" in open_section or "worsened" in open_section
        assert "g0020-b's holdout is consistent." not in open_section
        assert "g0020-a won." not in open_section


# ---------------------------------------------------------------------------
# previous_lane_reset -- telling a genuine first generation apart from a restart
# ---------------------------------------------------------------------------


class TestLaneResetNote:
    def test_genuinely_first_generation_gets_no_restart_note(self, settings: Settings) -> None:
        """No earlier generation of any purpose exists on disk at all -- this really is the first
        generation the loop has ever run, and the digest must not claim otherwise."""
        _write_outcome(
            settings, _outcome(1, purpose=Purpose.ROTH, findings=(_goal_finding(previous_generation=None),))
        )
        markdown, _ = digest.write_digest(1, settings=settings, dry_run=True)
        assert "restart" not in markdown.lower()
        assert "This is this lane's first measured generation on record" in markdown

    def test_new_purpose_with_no_earlier_same_purpose_generation_gets_no_restart_note(
        self, settings: Settings
    ) -> None:
        """A purpose that is new to the loop (added to `LoopConfig.purposes` partway through a run)
        legitimately has no earlier same-purpose generation, even though earlier generations of
        *other* purposes exist -- this must not be misread as a restart."""
        _write_outcome(
            settings,
            _outcome(1, purpose=Purpose.TRADING, findings=(_goal_finding(previous_generation=None),)),
        )
        _write_outcome(
            settings,
            _outcome(2, purpose=Purpose.ROTH, findings=(_goal_finding(previous_generation=None),)),
        )
        markdown, _ = digest.write_digest(2, settings=settings, dry_run=True)
        assert "restart" not in markdown.lower()

    def test_earlier_same_purpose_generation_triggers_the_restart_note(
        self, settings: Settings
    ) -> None:
        """This lane genuinely ran before (an earlier same-purpose generation exists on disk), but
        this generation's own goal finding has no recorded predecessor -- the signature of the
        loop's in-process lane history having been reset by a restart, per the owner's own note."""
        _write_outcome(
            settings,
            _outcome(1, purpose=Purpose.ROTH, findings=(_goal_finding(previous_generation=None),)),
        )
        _write_outcome(
            settings,
            _outcome(9, purpose=Purpose.ROTH, findings=(_goal_finding(previous_generation=None),)),
        )
        markdown, _ = digest.write_digest(9, settings=settings, dry_run=True)
        assert "restart" in markdown.lower()
        assert "history_by_lane" in markdown
        assert "without actually being the purpose's first ever run" in markdown


# ---------------------------------------------------------------------------
# The standing caveat -- computed from the ledger, never hardcoded
# ---------------------------------------------------------------------------


class TestCaveatStats:
    def test_computed_fraction_matches_hand_count(self, settings: Settings) -> None:
        rows = [
            {"genome_id": "a", "holdout_median_excess": "0.10"},
            {"genome_id": "b", "holdout_median_excess": "-0.05"},
            {"genome_id": "c", "holdout_median_excess": "0.20"},
            {"genome_id": "d", "holdout_median_excess": None},  # excluded from the denominator
            {"genome_id": "e"},  # missing key entirely -- same as None
        ]
        _write_ledger(settings, rows)
        stats = digest.caveat_stats(settings)
        assert stats.candidates_ever_run == 5
        assert stats.total == 3
        assert stats.positive == 2
        assert stats.positive_fraction == Decimal(2) / Decimal(3)

    def test_missing_ledger_degrades_to_zero_not_an_exception(self, settings: Settings) -> None:
        stats = digest.caveat_stats(settings)
        assert stats == digest.CaveatStats(positive=0, total=0, candidates_ever_run=0)
        assert stats.positive_fraction is None

    def test_one_bad_line_does_not_discard_the_rest(self, settings: Settings) -> None:
        path = loop_root(settings) / "ledger.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"holdout_median_excess": "0.10"}\nnot json at all\n{"holdout_median_excess": "0.20"}\n',
            encoding="utf-8",
        )
        stats = digest.caveat_stats(settings)
        assert stats.candidates_ever_run == 2
        assert stats.positive == 2

    def test_null_is_never_rendered_as_zero_percent(self, settings: Settings) -> None:
        caveat = digest.CaveatStats(positive=0, total=0, candidates_ever_run=0)
        sentence = digest._standing_caveat_sentence(caveat)
        assert "0.0%" not in sentence
        assert "cannot be computed" in sentence


class TestCaveatStatsCache:
    """`caveat_stats` is now called once per generation from inside the loop's own supervisor
    thread (`write_digest`, wired into `app.evolution.loop._run` right after `_write_outcome_file`)
    against a ledger that only grows -- these tests are the coordinator's explicit ask: prove a
    second call over an unchanged file does not re-read it, and that a real change does invalidate."""

    def test_second_call_with_unchanged_file_does_not_reread(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_ledger(settings, [{"holdout_median_excess": "0.10"}, {"holdout_median_excess": "0.20"}])
        first = digest.caveat_stats(settings)

        calls: list[Path] = []
        original = digest._read_ledger_text

        def _tracking_read(path: Path) -> str | None:
            calls.append(path)
            return original(path)

        monkeypatch.setattr(digest, "_read_ledger_text", _tracking_read)

        second = digest.caveat_stats(settings)

        assert second == first
        assert calls == [], "an unchanged ledger.jsonl must not be read a second time"

    def test_touching_the_file_invalidates_the_cache(self, settings: Settings) -> None:
        _write_ledger(settings, [{"holdout_median_excess": "0.10"}])
        first = digest.caveat_stats(settings)
        assert first.candidates_ever_run == 1

        _write_ledger(
            settings, [{"holdout_median_excess": "0.10"}, {"holdout_median_excess": "0.20"}]
        )
        second = digest.caveat_stats(settings)
        assert second.candidates_ever_run == 2
        assert second != first

    def test_a_missing_ledger_result_is_not_poisoned_once_the_file_appears(
        self, settings: Settings
    ) -> None:
        """The specific poisoning risk the coordinator called out: an empty result cached for a
        missing file must not survive the file actually being written."""
        first = digest.caveat_stats(settings)
        assert first == digest.CaveatStats(positive=0, total=0, candidates_ever_run=0)

        _write_ledger(settings, [{"holdout_median_excess": "0.10"}])
        second = digest.caveat_stats(settings)
        assert second.candidates_ever_run == 1
        assert second.positive == 1

    def test_read_failure_on_an_existing_file_is_not_cached(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A transient read failure (the file exists -- `_ledger_signature` sees a real signature --
        but `_read_ledger_text` fails anyway) must not poison the cache under that real signature;
        the very next call, once reads succeed again, must return real data rather than a cached
        zero."""
        _write_ledger(settings, [{"holdout_median_excess": "0.10"}])

        monkeypatch.setattr(digest, "_read_ledger_text", lambda path: None)
        degraded = digest.caveat_stats(settings)
        assert degraded == digest.CaveatStats(positive=0, total=0, candidates_ever_run=0)

        monkeypatch.undo()
        recovered = digest.caveat_stats(settings)
        assert recovered.candidates_ever_run == 1


# ---------------------------------------------------------------------------
# rebuild_journal
# ---------------------------------------------------------------------------


class TestRebuildJournal:
    def test_journal_is_oldest_first_and_states_counts(self, settings: Settings) -> None:
        _write_outcome(settings, _outcome(1))
        _write_outcome(settings, _outcome(2, status="cancelled", standings=(), findings=()))
        digest.write_digest(1, settings=settings, dry_run=False)
        digest.write_digest(2, settings=settings, dry_run=False)

        path = digest.rebuild_journal(settings=settings)
        text = path.read_text(encoding="utf-8")

        assert text.index("Generation 1") < text.index("Generation 2")
        assert "Generation directories on disk: 2" in text
        assert "Readable outcomes: 2" in text

    def test_is_idempotent(self, settings: Settings) -> None:
        _write_outcome(settings, _outcome(1))
        digest.write_digest(1, settings=settings, dry_run=False)
        first = digest.rebuild_journal(settings=settings)
        first_text = first.read_text(encoding="utf-8")
        second = digest.rebuild_journal(settings=settings)
        assert second.read_text(encoding="utf-8") == first_text

    def test_empty_tree_produces_a_header_only_journal(self, settings: Settings) -> None:
        path = digest.rebuild_journal(settings=settings)
        text = path.read_text(encoding="utf-8")
        assert "Generation directories on disk: 0" in text

    def test_reports_a_gap_in_the_header(self, settings: Settings) -> None:
        _write_outcome(settings, _outcome(1))
        _write_outcome(settings, _outcome(9))
        digest.write_digest(1, settings=settings, dry_run=False)
        digest.write_digest(9, settings=settings, dry_run=False)
        text = digest.rebuild_journal(settings=settings).read_text(encoding="utf-8")
        assert "Gap: gen0001 -> gen0009, 7 generation(s)" in text


# ---------------------------------------------------------------------------
# GET /api/competition/loop/journal
# ---------------------------------------------------------------------------


@pytest.fixture
def journal_app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(evolution_journal.router)
    return fastapi_app


@pytest.fixture
def journal_client(
    journal_app: FastAPI, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setattr(loop_module, "get_settings", lambda: settings)
    return TestClient(journal_app)


class TestJournalRoute:
    def test_absent_journal_is_not_a_404(self, journal_client: TestClient) -> None:
        response = journal_client.get("/api/competition/loop/journal")
        assert response.status_code == 200
        assert response.json() == {"total": 0, "entries": []}

    def test_pagination_is_newest_first(
        self, settings: Settings, journal_client: TestClient
    ) -> None:
        for generation in (1, 2, 3, 4, 5):
            _write_outcome(settings, _outcome(generation))
            digest.write_digest(generation, settings=settings, dry_run=False)

        response = journal_client.get("/api/competition/loop/journal", params={"limit": 2, "offset": 1})
        body = response.json()
        assert body["total"] == 5
        assert [entry["generation"] for entry in body["entries"]] == [4, 3]

    def test_entries_carry_the_full_digest_markdown(
        self, settings: Settings, journal_client: TestClient
    ) -> None:
        _write_outcome(settings, _outcome(1))
        digest.write_digest(1, settings=settings, dry_run=False)
        body = journal_client.get("/api/competition/loop/journal").json()
        assert body["total"] == 1
        assert "## Generation 1" in body["entries"][0]["markdown"]

    def test_a_generation_with_no_digest_is_simply_absent(
        self, settings: Settings, journal_client: TestClient
    ) -> None:
        _write_outcome(settings, _outcome(1))  # OUTCOME.json exists, but write_digest never ran
        body = journal_client.get("/api/competition/loop/journal").json()
        assert body == {"total": 0, "entries": []}


# ---------------------------------------------------------------------------
# Backfill idempotency across the whole tree
# ---------------------------------------------------------------------------


class TestBackfillIdempotency:
    def test_writing_every_generation_twice_changes_nothing_the_second_time(
        self, settings: Settings
    ) -> None:
        _write_outcome(settings, _outcome(1, findings=(_goal_finding(previous_generation=None),)))
        _write_outcome(
            settings, _outcome(2, status="cancelled", standings=(), findings=())
        )
        (loop_root(settings) / "gen0003").mkdir(parents=True, exist_ok=True)  # unreadable

        caveat = digest.caveat_stats(settings)
        first_pass = {
            g: digest.write_digest(g, settings=settings, caveat=caveat, dry_run=False)[1]
            for g in (1, 2, 3)
        }
        assert all(first_pass.values()), "every generation should write on the first pass"

        second_pass = {
            g: digest.write_digest(g, settings=settings, caveat=caveat, dry_run=False)[1]
            for g in (1, 2, 3)
        }
        assert not any(second_pass.values()), "a second identical pass must change nothing"

        digest.rebuild_journal(settings=settings)
        before = digest.journal_path(settings).read_text(encoding="utf-8")
        digest.rebuild_journal(settings=settings)
        after = digest.journal_path(settings).read_text(encoding="utf-8")
        assert before == after
