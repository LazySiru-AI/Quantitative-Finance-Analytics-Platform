"""Run persistence: one `DeskRun` snapshot per stage transition, written where nobody else can see a
half-written file.

`DeskRun` and `StageRecord` are both frozen (see `app.agentdesk.models`), which means a run's
lifecycle is not "mutate this object in place" but "replace it with a new one and save that" --
:func:`with_stage` is the one function in this package that performs that replacement, and
`RunStore.save` is the one function that persists the result. A poll landing mid-run therefore always
reads either the previous stage's complete snapshot or the new one, never a torn mixture of the two.

**Why the write is temp-file-then-`os.replace`, not a direct write.** `app.market.store` and
`app.db.duck` both learned the same lesson the hard way: a reader (an HTTP handler serving `GET
/api/.../runs/{run_id}`) can observe a file mid-write if the writer does not stage first, and on
Windows a bare in-place write is not even atomic with respect to a concurrent read. `os.replace` is
atomic on both POSIX and Windows for files on the same volume, which a same-directory staging file
always is.

**Why a corrupt `run.json` is skipped, not raised, from `list_runs`.** One run's file being truncated
by a crash mid-write (before this module existed, or from a bug elsewhere) must not take down a page
that lists twenty-five other runs that are perfectly fine. `load` for that one `run_id` still returns
`None` -- a direct lookup for a known-bad run is allowed to say "not found" -- but a listing walks
past it and logs a warning, the same choice `app.tournament.jobs` makes for a job's own bookkeeping.
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from typing import Any

from app.agentdesk.models import DeskKind, DeskRun, run_dir, runs_dir
from app.config import Settings

__all__ = ["RunStore", "with_stage"]

logger = logging.getLogger(__name__)

_RUN_FILE = "run.json"


class RunStore:
    """Reads and writes `DeskRun` snapshots for one desk kind, under `data/agentdesk/<kind>/runs/`."""

    def __init__(self, settings: Settings, kind: DeskKind) -> None:
        self._settings = settings
        self._kind = kind

    def save(self, run: DeskRun) -> None:
        """Write `run` atomically: a uuid-suffixed staging file in the run's own directory, then a
        single `os.replace` onto `run.json`. The staging name carries a uuid rather than a fixed
        `.tmp` suffix for the same reason `app.market.store._write_meta` and `app.db.duck.write_bars`
        do -- two writers racing a fixed staging name can still collide on the final replace even
        though a single writer never races itself here (one `DeskRun` per run, one worker thread per
        run), and matching the established convention costs nothing.
        """
        directory = run_dir(self._settings, self._kind, run.run_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / _RUN_FILE
        staging = directory / f"{_RUN_FILE}.{uuid.uuid4().hex}.tmp"
        staging.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        os.replace(staging, path)

    def load(self, run_id: str) -> DeskRun | None:
        """The run's current snapshot, or `None` if it does not exist or its file cannot be parsed.

        A direct lookup by `run_id` is allowed to answer "not found" for a corrupt file -- unlike
        `list_runs`, which has other runs' data to show and therefore logs a warning and walks past
        instead, this is the caller's *only* answer for the id it asked about, so there is nothing to
        walk past to.
        """
        path = run_dir(self._settings, self._kind, run_id) / _RUN_FILE
        if not path.is_file():
            return None
        try:
            return DeskRun.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("agentdesk store: could not read run %r: %s", run_id, exc)
            return None

    def list_runs(self, limit: int = 25) -> tuple[DeskRun, ...]:
        """Every readable run for this kind, newest `created_at` first, capped at `limit`.

        A run whose `run.json` cannot be parsed is logged and skipped -- see the module docstring --
        so one bad file costs the listing exactly one entry, never the whole page.
        """
        base = runs_dir(self._settings, self._kind)
        if not base.is_dir():
            return ()

        runs: list[DeskRun] = []
        for entry in sorted(base.iterdir()):
            path = entry / _RUN_FILE
            if not path.is_file():
                continue
            try:
                runs.append(DeskRun.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                logger.warning("agentdesk store: skipping unreadable run file %s: %s", path, exc)
                continue

        runs.sort(key=lambda run: run.created_at, reverse=True)
        return tuple(runs[:limit])

    def delete(self, run_id: str) -> bool:
        """Remove the run's whole directory (its `run.json` plus any per-stage markdown beside it).

        Returns `False` for a run that was never saved rather than raising -- a caller asking to
        delete something already gone is not an error condition this store needs to distinguish from
        a successful delete of an empty state.
        """
        directory = run_dir(self._settings, self._kind, run_id)
        if not (directory / _RUN_FILE).is_file():
            return False
        shutil.rmtree(directory)
        return True


def with_stage(run: DeskRun, stage_id: str, **changes: Any) -> DeskRun:
    """`run`, with the `StageRecord` named `stage_id` replaced by a copy carrying `changes`.

    The one update primitive both desks share: a pipeline stage finishing, a stage's grounding verdict
    landing, a stage moving to `"blocked"` because its dependency failed -- every transition is
    "replace one stage in the tuple, then replace the run" rather than a mutation, matching `DeskRun`'s
    own frozen contract. Raises `KeyError` for an unknown `stage_id` rather than silently no-op'ing,
    because a caller naming a stage that is not in this run is a programming error worth surfacing
    immediately rather than a run that quietly never updates.
    """
    stages = list(run.stages)
    for index, stage in enumerate(stages):
        if stage.stage_id == stage_id:
            stages[index] = stage.model_copy(update=changes)
            return run.model_copy(update={"stages": tuple(stages)})
    raise KeyError(f"no stage {stage_id!r} in run {run.run_id!r}")
