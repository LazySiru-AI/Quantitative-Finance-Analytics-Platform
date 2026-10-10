"""Tests for the run-file memoisation `/api/competition/rounds` now reads through.

`list_rounds` counted a round's distinct agents by `json.loads`-ing every run file under every
window, fresh, on every request -- 1051 files across the 14 rounds on disk, ~370ms of parsing per
page load. `results._AGENT_ID_CACHE` memoises each file's `card.agent_id` against that file's own
`(st_mtime_ns, st_size)`, so a repeat call re-reads only what changed.

The point of these tests is the *invalidation*, not the speed. Note that the "read everything fresh,
never cache" rule written down in this codebase -- `results.load_library`'s docstring and
`app.api.competition.library`'s -- is about the *card library*, not the rounds tree, and both still
hold: `load_library` is untouched. Nothing was ever written down for rounds. But the hazard is real
whether or not anyone wrote it down: a round's results tree is written while the API is being read
(`app.tournament.jobs` drops a run file into `results/<window>/runs/` as each card finishes), so a
stale agent count would under-report a round in progress. That is the claim these tests exist to
make checkable -- every test in `TestFreshness` mutates the tree between two `list_rounds` calls and
asserts the second call already reflects the mutation.

Built against a `tmp_path` tree via the `rounds_root` parameter, never `data/rounds`, matching
`test_competition_round_ordering.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.tournament import results


def _write_run(
    root: Path, round_id: str, window: str, agent_id: str, *, filename: str | None = None
) -> Path:
    """One run file, named the way `app.tournament.jobs` names them (`r1-<agent_id>.json`) unless
    `filename` overrides it -- overriding is how the "filename is not the agent id" test below feeds
    a name and a content that disagree."""
    runs_dir = root / round_id / "results" / window / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / (filename if filename is not None else f"r1-{agent_id}.json")
    path.write_text(json.dumps({"card": {"agent_id": agent_id}}), encoding="utf-8")
    return path


def _agents(root: Path, round_id: str) -> int:
    rows = {row.round_id: row for row in results.list_rounds(root)}
    return rows[round_id].agents


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """The cache is module-level process state, so a test that seeded it must not colour the next
    one. `tmp_path` differs per test so a leak could not actually cross over, but clearing keeps
    each test's first call an honest cold call."""
    results._AGENT_ID_CACHE.clear()


class TestFreshness:
    def test_a_run_file_added_between_calls_is_counted_immediately(self, tmp_path: Path) -> None:
        """The mid-round case the cache most has to survive: `jobs` writes card N+1's run file
        while the round list is being polled."""
        _write_run(tmp_path, "r1-2026-08", "gfc", "agent-a")
        assert _agents(tmp_path, "r1-2026-08") == 1

        _write_run(tmp_path, "r1-2026-08", "gfc", "agent-b")
        assert _agents(tmp_path, "r1-2026-08") == 2

    def test_a_run_file_added_in_a_new_window_is_counted_immediately(self, tmp_path: Path) -> None:
        """A window directory that did not exist at the first call -- the cache is keyed per runs
        directory, so a brand-new one must miss rather than inherit anything."""
        _write_run(tmp_path, "r1-2026-08", "gfc", "agent-a")
        assert _agents(tmp_path, "r1-2026-08") == 1

        _write_run(tmp_path, "r1-2026-08", "covid", "agent-b")
        assert _agents(tmp_path, "r1-2026-08") == 2

    def test_a_deleted_run_file_drops_out_of_the_count(self, tmp_path: Path) -> None:
        """Eviction: the memoised entry for a file that is gone must not keep counting its agent."""
        _write_run(tmp_path, "r1-2026-08", "gfc", "agent-a")
        doomed = _write_run(tmp_path, "r1-2026-08", "gfc", "agent-b")
        assert _agents(tmp_path, "r1-2026-08") == 2

        doomed.unlink()
        assert _agents(tmp_path, "r1-2026-08") == 1

    def test_a_rewritten_run_file_is_re_read(self, tmp_path: Path) -> None:
        """Content change under a stable name. `jobs` never does this (it names a run file after the
        agent id inside it), but the count must not depend on that: rewriting the file with a
        different agent id changes its size as well as its mtime, and either alone invalidates."""
        path = _write_run(tmp_path, "r1-2026-08", "gfc", "agent-a")
        assert _agents(tmp_path, "r1-2026-08") == 1

        path.write_text(
            json.dumps({"card": {"agent_id": "agent-renamed-and-much-longer"}}), encoding="utf-8"
        )
        rows = {row.round_id: row for row in results.list_rounds(tmp_path)}
        assert rows["r1-2026-08"].agents == 1
        assert results._AGENT_ID_CACHE[str(path.parent)][path.name][2] == (
            "agent-renamed-and-much-longer"
        )

    def test_the_whole_round_disappearing_leaves_no_row(self, tmp_path: Path) -> None:
        _write_run(tmp_path, "r1-2026-08", "gfc", "agent-a")
        assert _agents(tmp_path, "r1-2026-08") == 1

        for child in sorted((tmp_path / "r1-2026-08").rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()
            else:
                child.unlink()
        (tmp_path / "r1-2026-08").rmdir()
        assert results.list_rounds(tmp_path) == []


class TestCountingRules:
    def test_the_agent_id_comes_from_the_content_not_the_filename(self, tmp_path: Path) -> None:
        """The module docstring's real-data note: every run file on disk is prefixed `r1-` whatever
        round it belongs to, and the id must come from `card.agent_id`. Two files whose names
        disagree with their content, and with each other, are still one agent -- asserted twice so
        the rule is checked on the cache-hit path as well as the cold parse."""
        _write_run(tmp_path, "r1-2026-08", "gfc", "real-id", filename="r1-a-misleading-name.json")
        _write_run(tmp_path, "r1-2026-08", "gfc", "real-id", filename="r9-another-name.json")

        assert _agents(tmp_path, "r1-2026-08") == 1
        assert _agents(tmp_path, "r1-2026-08") == 1

    def test_one_agent_across_two_windows_counts_once(self, tmp_path: Path) -> None:
        _write_run(tmp_path, "r1-2026-08", "gfc", "agent-a")
        _write_run(tmp_path, "r1-2026-08", "covid", "agent-a")
        assert _agents(tmp_path, "r1-2026-08") == 1
        assert _agents(tmp_path, "r1-2026-08") == 1

    def test_a_round_with_no_results_tree_counts_zero(self, tmp_path: Path) -> None:
        (tmp_path / "r1-2026-08").mkdir()
        assert _agents(tmp_path, "r1-2026-08") == 0

    def test_a_malformed_run_file_still_raises(self, tmp_path: Path) -> None:
        """Unchanged from before the cache: a file in `runs/` that is not a run result is a defect
        worth surfacing, not something to silently count as zero agents."""
        runs_dir = tmp_path / "r1-2026-08" / "results" / "gfc" / "runs"
        runs_dir.mkdir(parents=True)
        (runs_dir / "r1-broken.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            results.list_rounds(tmp_path)


class TestCacheActuallyCaches:
    def test_a_second_call_reopens_only_the_run_file_that_changed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point of the change -- without this assertion every test above would also pass
        against the original read-everything implementation. Counts opens of run files only."""
        _write_run(tmp_path, "r1-2026-08", "gfc", "agent-a")
        _write_run(tmp_path, "r1-2026-08", "gfc", "agent-b")
        assert _agents(tmp_path, "r1-2026-08") == 2

        opened: list[str] = []
        real_read_text = Path.read_text

        def counting_read_text(self: Path, *args: object, **kwargs: object) -> str:
            if self.suffix == ".json" and self.parent.name == "runs":
                opened.append(self.name)
            return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_text", counting_read_text)

        assert _agents(tmp_path, "r1-2026-08") == 2
        assert opened == [], "an unchanged results tree should cost no run-file reads at all"

        _write_run(tmp_path, "r1-2026-08", "gfc", "agent-c")
        assert _agents(tmp_path, "r1-2026-08") == 3
        assert opened == ["r1-agent-c.json"], "only the new run file should have been parsed"
