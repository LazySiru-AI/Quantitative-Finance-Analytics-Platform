"""Tests for `app.evolution.amend.apply_amendments` -- applying a reviewer's proposed amendments to
the *next* generation's `LoopConfig`, safely and on the record.

**`ProposedAmendment` is faked, not imported.** `app.agents.review_models` (a sibling package, written
concurrently with this one) may not exist in every checkout; `app.evolution.amend` is deliberately
written to duck-type its `amendments` argument (see that module's own docstring), so every test here
builds a small local stand-in -- `_amendment(field, value, reason)` -- with exactly the three
attributes `apply_amendments` actually reads. This mirrors `tests/test_evolution_loop.py`'s own
"fakes instead of real, concurrently-written sibling modules" convention.

Every test points `Settings` at `tmp_path`, so nothing here ever touches the real repository's `data/`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.evolution import amend
from app.evolution.models import (
    GenerationOutcome,
    LoopConfig,
    amendments_path,
    loop_root,
)
from app.tournament.purposes import Purpose

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _amendment:
    """Stands in for `app.agents.review_models.ProposedAmendment` -- see this file's module docstring
    for why a real import is avoided."""

    field: str
    value: Any
    reason: str = "reviewer-stated reason"


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", rounds_dir=tmp_path / "data" / "rounds")


def _config(**overrides: Any) -> LoopConfig:
    base: dict[str, Any] = {
        "windows": ("w1", "w2"),
        "holdout_windows": (),
        "use_news": False,
    }
    base.update(overrides)
    return LoopConfig(**base)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


# ---------------------------------------------------------------------------
# (a) Every amendment field applies
# ---------------------------------------------------------------------------


class TestEveryFieldApplies:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("promotion_margin_pp", Decimal("15.0")),
            ("holdout_windows", ("w9", "w10")),
            ("windows", ("w5", "w6")),
            ("population", 5),
            ("elite_count", 3),
            ("focus_symbols", ("AAPL",)),
            ("avoid_symbols", ("TSLA",)),
            ("use_news", True),
            ("news_fraction", 0.5),
            ("rank_by", "worst"),
            ("promotion_consecutive", 3),
            ("cooldown_seconds", 5.0),
        ],
    )
    def test_field_applies_and_lands_on_the_next_config(
        self, tmp_path: Path, field: str, value: Any
    ) -> None:
        settings = _settings(tmp_path)
        config = _config()

        outcome = amend.apply_amendments(
            config=config,
            amendments=[_amendment(field, value)],
            generation=1,
            purpose=Purpose.TRADING,
            settings=settings,
        )

        assert outcome.refused == ()
        assert len(outcome.applied) == 1
        assert outcome.applied[0].field == field
        assert outcome.applied[0].applied is True
        assert getattr(outcome.config, field) == value

    def test_amendments_apply_cumulatively_within_one_batch(self, tmp_path: Path) -> None:
        """The second amendment in a batch is validated against the config the *first* one produced,
        not the original -- proven by a pair that would conflict against the original but not against
        each other's result: `windows` moves off `w1`/`w2` first, and only then is `holdout_windows`
        set to `("w1", "w2")`, which would have overlapped the *original* `windows`."""
        settings = _settings(tmp_path)
        config = _config(windows=("w1", "w2"), holdout_windows=())

        outcome = amend.apply_amendments(
            config=config,
            amendments=[
                _amendment("windows", ("w5", "w6")),
                _amendment("holdout_windows", ("w1", "w2")),
            ],
            generation=1,
            purpose=Purpose.TRADING,
            settings=settings,
        )

        assert len(outcome.applied) == 2
        assert outcome.refused == ()
        assert outcome.config.windows == ("w5", "w6")
        assert outcome.config.holdout_windows == ("w1", "w2")


# ---------------------------------------------------------------------------
# (b) Out-of-bounds values are refused, readably, without crashing
# ---------------------------------------------------------------------------


class TestOutOfBoundsRefused:
    def test_population_above_the_ceiling_is_refused_with_a_readable_reason(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        config = _config()

        outcome = amend.apply_amendments(
            config=config,
            amendments=[_amendment("population", 999)],
            generation=1,
            purpose=Purpose.TRADING,
            settings=settings,
        )

        assert outcome.applied == ()
        assert len(outcome.refused) == 1
        refusal = outcome.refused[0]
        assert refusal.field == "population"
        assert refusal.value == "999"
        assert refusal.reason  # a real, non-empty pydantic message
        assert "population" in refusal.reason
        # The config the next generation runs with is untouched by the refusal.
        assert outcome.config.population == config.population

    def test_news_fraction_outside_zero_to_one_is_refused(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        config = _config()

        outcome = amend.apply_amendments(
            config=config,
            amendments=[_amendment("news_fraction", 5.0)],
            generation=1,
            purpose=Purpose.TRADING,
            settings=settings,
        )

        assert outcome.applied == ()
        assert len(outcome.refused) == 1
        assert outcome.refused[0].field == "news_fraction"
        assert outcome.config.news_fraction == config.news_fraction


# ---------------------------------------------------------------------------
# (c) An overlapping holdout/selection pair is refused
# ---------------------------------------------------------------------------


class TestHoldoutOverlapRefused:
    def test_holdout_windows_overlapping_windows_is_refused(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        config = _config(windows=("w1", "w2"), holdout_windows=())

        outcome = amend.apply_amendments(
            config=config,
            amendments=[_amendment("holdout_windows", ("w1", "w3"))],
            generation=1,
            purpose=Purpose.TRADING,
            settings=settings,
        )

        assert outcome.applied == ()
        assert len(outcome.refused) == 1
        refusal = outcome.refused[0]
        assert refusal.field == "holdout_windows"
        assert "overlap" in refusal.reason.lower() or "not been held out" in refusal.reason.lower()
        assert outcome.config.holdout_windows == config.holdout_windows

    def test_windows_overlapping_existing_holdout_is_refused(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        config = _config(windows=("w5", "w6"), holdout_windows=("covid", "q4-2018"))

        outcome = amend.apply_amendments(
            config=config,
            amendments=[_amendment("windows", ("w5", "covid"))],
            generation=1,
            purpose=Purpose.TRADING,
            settings=settings,
        )

        assert outcome.applied == ()
        assert len(outcome.refused) == 1
        assert outcome.refused[0].field == "windows"
        assert outcome.config.windows == config.windows

    def test_a_non_overlapping_holdout_change_still_applies(self, tmp_path: Path) -> None:
        """The invariant refuses genuine overlaps only -- the owner's authority to redraw the holdout
        entirely is otherwise honoured, per this module's own docstring."""
        settings = _settings(tmp_path)
        config = _config(windows=("w1", "w2"), holdout_windows=("covid",))

        outcome = amend.apply_amendments(
            config=config,
            amendments=[_amendment("holdout_windows", ("q4-2018", "gfc"))],
            generation=1,
            purpose=Purpose.TRADING,
            settings=settings,
        )

        assert outcome.refused == ()
        assert len(outcome.applied) == 1
        assert outcome.config.holdout_windows == ("q4-2018", "gfc")


# ---------------------------------------------------------------------------
# (d) The jsonl audit trail is appended to for both applied and refused amendments
# ---------------------------------------------------------------------------


class TestAppendOnlyAuditTrail:
    def test_both_applied_and_refused_amendments_are_written_as_valid_json_lines(
        self, tmp_path: Path
    ) -> None:
        settings = _settings(tmp_path)
        config = _config(windows=("w1", "w2"), holdout_windows=())

        amend.apply_amendments(
            config=config,
            amendments=[
                _amendment("population", 6),  # applied
                _amendment("population", -1),  # refused: below the floor
                _amendment("holdout_windows", ("w1",)),  # refused: overlaps windows
            ],
            generation=3,
            purpose=Purpose.ROTH,
            settings=settings,
        )

        path = amendments_path(settings)
        assert path.is_file()
        rows = _read_jsonl(path)
        assert len(rows) == 3

        applied_rows = [row for row in rows if row["applied"] is True]
        refused_rows = [row for row in rows if row["applied"] is False]
        assert len(applied_rows) == 1
        assert len(refused_rows) == 2
        for row in rows:
            assert row["generation"] == 3
            assert row["purpose"] == "roth"
            assert isinstance(row["reason"], str) and row["reason"]
            assert isinstance(row["applied_at"], str)

    def test_a_second_call_appends_rather_than_overwrites(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        config = _config()

        amend.apply_amendments(
            config=config,
            amendments=[_amendment("population", 6)],
            generation=1,
            purpose=Purpose.TRADING,
            settings=settings,
        )
        amend.apply_amendments(
            config=config,
            amendments=[_amendment("elite_count", 4)],
            generation=2,
            purpose=Purpose.TRADING,
            settings=settings,
        )

        rows = _read_jsonl(amendments_path(settings))
        assert len(rows) == 2
        assert [row["generation"] for row in rows] == [1, 2]

    def test_no_amendments_writes_no_file(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        config = _config()

        outcome = amend.apply_amendments(
            config=config, amendments=[], generation=1, purpose=Purpose.TRADING, settings=settings
        )

        assert outcome.applied == ()
        assert outcome.refused == ()
        assert outcome.config == config
        assert not amendments_path(settings).is_file()


# ---------------------------------------------------------------------------
# (e) A completed OUTCOME.json is never modified -- amendments are not retroactive
# ---------------------------------------------------------------------------


class TestNeverRetroactive:
    def test_apply_amendments_never_touches_an_existing_outcome_file(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        config = _config(windows=("w1", "w2"), holdout_windows=())

        # Write a completed generation's outcome to disk, exactly as `app.evolution.loop.
        # _write_outcome_file` does, before any amendment is ever applied.
        import datetime as dt

        outcome_obj = GenerationOutcome(
            generation=1,
            round_id="r1-auto-20260101-000000-g0001",
            purpose=Purpose.TRADING,
            status="succeeded",
            started_at=dt.datetime.now(dt.UTC),
            finished_at=dt.datetime.now(dt.UTC),
            windows=("w1", "w2"),
            genome_ids=("g001-aaaaaaaaaaaa",),
        )
        gen_dir = loop_root(settings) / "gen0001"
        gen_dir.mkdir(parents=True, exist_ok=True)
        outcome_path = gen_dir / "OUTCOME.json"
        outcome_path.write_text(outcome_obj.model_dump_json(indent=2), encoding="utf-8")
        before = outcome_path.read_text(encoding="utf-8")
        before_mtime = outcome_path.stat().st_mtime_ns

        amend.apply_amendments(
            config=config,
            amendments=[
                _amendment("promotion_margin_pp", Decimal("5.0")),
                _amendment("population", 999),  # a refusal too, for good measure
            ],
            generation=1,
            purpose=Purpose.TRADING,
            settings=settings,
        )

        after = outcome_path.read_text(encoding="utf-8")
        after_mtime = outcome_path.stat().st_mtime_ns
        assert after == before, "apply_amendments must never rewrite an existing OUTCOME.json"
        assert after_mtime == before_mtime
