"""Tests for the round-ordering defect fix in `app.tournament.results`.

Two faults, both fixed in `results.py`:

* **Fault 1** -- `list_round_ids` sorted directory names lexicographically, so `"r9-2026-08" >
  "r13-2026-08"` as strings and round 9 was presented as the newest round while rounds 10-13 were
  buried in the middle of the list. Fixed by sorting on `round_sequence(name)` (the parsed integer
  ordinal), descending.
* **Fault 2** -- a round with no `results/` directory at all (or one with no windows in it) is
  indistinguishable, in the `/rounds` list, from a round with real results. `load_round_results`
  raises `RoundNotFoundError` for such a round, so `/rounds/{id}/leaderboard` 404s -- `has_results`
  exists so a caller can avoid defaulting a picker onto a round that cannot render.

Built entirely against a `tmp_path` fixture with fabricated round directories, passed via the
`rounds_root` parameter `list_round_ids`/`list_rounds` already accept -- never against the real
`data/rounds` tree, per the task brief.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.tournament import results

# ---------------------------------------------------------------------------
# round_sequence
# ---------------------------------------------------------------------------


class TestRoundSequence:
    def test_parses_the_leading_ordinal(self) -> None:
        assert results.round_sequence("r11-2026-08") == 11
        assert results.round_sequence("r9-2026-08") == 9
        assert results.round_sequence("r1-2026-08") == 1

    def test_non_matching_name_returns_the_sentinel_rather_than_raising(self) -> None:
        assert results.round_sequence("junk") == -1
        assert results.round_sequence("") == -1
        assert results.round_sequence("not-a-round-at-all") == -1


# ---------------------------------------------------------------------------
# Helpers to build a fabricated rounds tree
# ---------------------------------------------------------------------------


def _make_round_with_results(root: Path, round_id: str, window: str = "gfc") -> None:
    """A round directory with a `results/<window>/runs/` tree holding one run file -- enough for
    `_discover_windows` to find the window and for `has_results` to come back `True`."""
    runs_dir = root / round_id / "results" / window / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "r1-agent-a.json").write_text(
        '{"card": {"agent_id": "agent-a"}}', encoding="utf-8"
    )


def _make_round_without_results(root: Path, round_id: str) -> None:
    """A round directory that exists but never got a `results/` tree at all -- the seven real rounds
    (`r6`-`r10`, `r12`, `r13`) that hold only a `SELECTION.md`/`run.txt`."""
    round_dir = root / round_id
    round_dir.mkdir(parents=True)
    (round_dir / "SELECTION.md").write_text("no results yet", encoding="utf-8")


def _make_round_with_empty_results_dir(root: Path, round_id: str) -> None:
    """A `results/` directory that exists but is empty -- still nothing to rank."""
    (root / round_id / "results").mkdir(parents=True)


# ---------------------------------------------------------------------------
# list_round_ids / list_rounds ordering
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_r13_sorts_above_r9(self, tmp_path: Path) -> None:
        """The exact defect: as strings, `"r9-..." > "r13-..."`, so a lexicographic sort put round 9
        ahead of round 13. Numeric ordering must put 13 first."""
        _make_round_with_results(tmp_path, "r9-2026-08")
        _make_round_with_results(tmp_path, "r13-2026-08")

        ids = results.list_round_ids(tmp_path)
        assert ids.index("r13-2026-08") < ids.index("r9-2026-08")

    def test_full_thirteen_round_set_sorts_newest_number_first(self, tmp_path: Path) -> None:
        """Reproduces the live defect's exact round set (r1-r13) and asserts the fixed order is
        strictly descending by round number, not by directory-name string."""
        for n in range(1, 14):
            _make_round_with_results(tmp_path, f"r{n}-2026-08")

        ids = results.list_round_ids(tmp_path)
        assert ids == [f"r{n}-2026-08" for n in range(13, 0, -1)]

    def test_non_matching_directory_name_does_not_raise_and_sorts_last(
        self, tmp_path: Path
    ) -> None:
        """A stray directory under the rounds root that does not look like `r<N>-...` must not 500
        the endpoint -- it sorts after every well-formed round id."""
        _make_round_with_results(tmp_path, "r2-2026-08")
        _make_round_with_results(tmp_path, "r1-2026-08")
        _make_round_with_results(tmp_path, "not-a-round")

        ids = results.list_round_ids(tmp_path)
        assert ids[-1] == "not-a-round"
        assert ids == ["r2-2026-08", "r1-2026-08", "not-a-round"]

    def test_list_rounds_carries_the_same_order_and_sequence_field(
        self, tmp_path: Path
    ) -> None:
        _make_round_with_results(tmp_path, "r9-2026-08")
        _make_round_with_results(tmp_path, "r13-2026-08")

        rounds = results.list_rounds(tmp_path)
        by_id = {r.round_id: r for r in rounds}
        assert [r.round_id for r in rounds] == ["r13-2026-08", "r9-2026-08"]
        assert by_id["r13-2026-08"].sequence == 13
        assert by_id["r9-2026-08"].sequence == 9


# ---------------------------------------------------------------------------
# has_results / has_selection
# ---------------------------------------------------------------------------


class TestHasResults:
    def test_false_for_a_round_with_no_results_directory_at_all(self, tmp_path: Path) -> None:
        _make_round_without_results(tmp_path, "r6-2026-08")

        rounds = results.list_rounds(tmp_path)
        assert len(rounds) == 1
        assert rounds[0].has_results is False

    def test_false_for_a_results_directory_that_exists_but_is_empty(
        self, tmp_path: Path
    ) -> None:
        """A `results/` dir that exists but has no window subdirectories still has nothing to rank
        -- `has_results` must not be `True` merely because the directory is present."""
        _make_round_with_empty_results_dir(tmp_path, "r7-2026-08")

        rounds = results.list_rounds(tmp_path)
        assert rounds[0].has_results is False

    def test_true_for_a_round_with_at_least_one_window_of_results(
        self, tmp_path: Path
    ) -> None:
        _make_round_with_results(tmp_path, "r5-2026-08")

        rounds = results.list_rounds(tmp_path)
        assert rounds[0].has_results is True

    def test_has_selection_false_without_live1_true_with_it(self, tmp_path: Path) -> None:
        _make_round_with_results(tmp_path, "r11-2026-08", window="gfc")
        (tmp_path / "r11-2026-08" / "results" / "live-1" / "runs").mkdir(parents=True)

        _make_round_with_results(tmp_path, "r5-2026-08", window="gfc")

        rounds = results.list_rounds(tmp_path)
        by_id = {r.round_id: r for r in rounds}
        assert by_id["r11-2026-08"].has_selection is True
        assert by_id["r5-2026-08"].has_selection is False

    def test_mixed_set_matches_the_live_defect_shape(self, tmp_path: Path) -> None:
        """Mirrors the real `data/rounds` tree that motivated this fix: r1-r5 and r11 have results,
        r6-r10/r12/r13 do not."""
        has_results_ids = {1, 2, 3, 4, 5, 11}
        for n in range(1, 14):
            round_id = f"r{n}-2026-08"
            if n in has_results_ids:
                _make_round_with_results(tmp_path, round_id)
            else:
                _make_round_without_results(tmp_path, round_id)

        rounds = results.list_rounds(tmp_path)
        by_id = {r.round_id: r for r in rounds}
        for n in range(1, 14):
            round_id = f"r{n}-2026-08"
            expected = n in has_results_ids
            assert by_id[round_id].has_results is expected, round_id

        # And the ordering fault is fixed at the same time: r13 first, r1 last.
        assert [r.round_id for r in rounds] == [f"r{n}-2026-08" for n in range(13, 0, -1)]


# ---------------------------------------------------------------------------
# _round_label / narrative-title preference
# ---------------------------------------------------------------------------


def _write_narrative(root: Path, round_id: str, *, title: str) -> None:
    """A minimal but schema-valid `NARRATIVE.json` under `root / round_id` -- every field
    `RoundNarrative` requires (it is `extra="forbid"`), filled with throwaway values except `title`,
    which is what these tests care about."""
    round_dir = root / round_id
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / "NARRATIVE.json").write_text(
        json.dumps(
            {
                "round_id": round_id,
                "title": title,
                "focus": "A test focus.",
                "headline": "A test headline.",
                "outcome": "A test outcome.",
                "seated": [],
                "owner_override": None,
                "carries_forward": [],
                "sources": [],
            }
        ),
        encoding="utf-8",
    )


class TestRoundLabel:
    def test_round_with_a_narrative_gets_the_title_based_label(self, tmp_path: Path) -> None:
        """A round with an authored `NARRATIVE.json` should show its narrative title, not the
        opaque `"r14 — Aug 2026"` date-derived label."""
        _make_round_with_results(tmp_path, "r14-2026-08")
        _write_narrative(tmp_path, "r14-2026-08", title="Round 14 - naming the chooser")

        rounds = results.list_rounds(tmp_path)
        assert rounds[0].label == "Round 14 - naming the chooser"

    def test_round_without_a_narrative_keeps_the_old_date_based_label(
        self, tmp_path: Path
    ) -> None:
        """No `NARRATIVE.json` at all (the normal state for most rounds) must fall back to the
        pre-existing `"<tag> — <Mon> <year>"` label rather than breaking or going blank."""
        _make_round_with_results(tmp_path, "r15-2026-08")
        assert not (tmp_path / "r15-2026-08" / "NARRATIVE.json").exists()

        rounds = results.list_rounds(tmp_path)
        assert rounds[0].label == "r15 — Aug 2026"

    def test_a_malformed_narrative_falls_back_cleanly_instead_of_500ing_the_list(
        self, tmp_path: Path
    ) -> None:
        """A `NARRATIVE.json` that exists but fails schema validation (here: missing every required
        field but `round_id`) must not raise out of `list_rounds` -- it degrades to the date-based
        label for that one round while the rest of the list still renders."""
        _make_round_with_results(tmp_path, "r16-2026-08")
        round_dir = tmp_path / "r16-2026-08"
        (round_dir / "NARRATIVE.json").write_text(
            json.dumps({"round_id": "r16-2026-08"}), encoding="utf-8"
        )

        rounds = results.list_rounds(tmp_path)
        assert rounds[0].label == "r16 — Aug 2026"
