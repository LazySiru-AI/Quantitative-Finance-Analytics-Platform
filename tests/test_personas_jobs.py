"""Unit tests for `app.personas.jobs.IngestRegistry` -- the one-active-ingest-per-persona bookkeeping.

Every test constructs its **own** `IngestRegistry()` instead of touching the process-wide
`app.personas.jobs.registry()` singleton, so a target left running by one test can never leak into
another. Coordination with a background thread is always done with `threading.Event` plus
`registry.join(job_id, timeout=...)` -- never `time.sleep` on a guess -- and every event a target
blocks on is released in a `finally`, so a failing assertion above it can never hang the suite.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest

from app.personas.jobs import IngestAlreadyActive, IngestRegistry, JobHandle

#: Every join/wait in this file uses the same small timeout. Long enough that a healthy daemon
#: thread never trips it under load, short enough that a genuine deadlock fails the test fast
#: instead of hanging the run.
_TIMEOUT = 5.0


def _noop(cancel_event: threading.Event, handle: JobHandle) -> None:
    """The simplest possible target: does nothing and returns, so the registry's own fallback
    (`finish(state="succeeded", only_if_unfinished=True)`) is what declares the outcome."""


def _blocking(release: threading.Event) -> Callable[[threading.Event, JobHandle], None]:
    """A target that will not return until the test calls `release.set()`.

    Used to hold a slug's slot "active" for as long as a test needs to observe that state --
    the second-`start`-raises and different-slug-doesn't-race tests both depend on the first job
    still being in flight when they act.
    """

    def _target(cancel_event: threading.Event, handle: JobHandle) -> None:
        release.wait(timeout=_TIMEOUT)

    return _target


def test_start_returns_a_running_job_with_the_given_total() -> None:
    """The route answers `202 Accepted` with exactly this record while work proceeds in the
    background, so its `state` and `items_total` must already be correct the instant `start`
    returns -- a poller must never see a job that claims to be running with the wrong total."""
    registry = IngestRegistry()
    job = registry.start("solo", items_total=7, target=_noop)
    assert job.state == "running"
    assert job.items_total == 7
    assert job.persona == "solo"
    registry.join(job.job_id, timeout=_TIMEOUT)


def test_second_start_for_the_same_slug_raises_ingest_already_active() -> None:
    """Two ingests of the same persona would race on the same note filenames and the same
    `persona.json` -- this is the exact race the one-active-slot-per-slug rule exists to prevent."""
    registry = IngestRegistry()
    release = threading.Event()
    first = registry.start("acme", items_total=3, target=_blocking(release))
    try:
        with pytest.raises(IngestAlreadyActive) as excinfo:
            registry.start("acme", items_total=1, target=_blocking(release))
        assert excinfo.value.slug == "acme"
        assert excinfo.value.job_id == first.job_id
    finally:
        release.set()
        registry.join(first.job_id, timeout=_TIMEOUT)


def test_a_different_slug_is_not_blocked_by_an_active_one() -> None:
    """Two personas ingesting at once contend only for the model budget and YouTube's patience,
    never for a single mutable resource -- each writes into its own vault subtree, so the registry
    must not serialise them."""
    registry = IngestRegistry()
    release_a = threading.Event()
    release_b = threading.Event()
    job_a = registry.start("persona-a", items_total=1, target=_blocking(release_a))
    try:
        job_b = registry.start("persona-b", items_total=1, target=_blocking(release_b))
        assert job_b.job_id != job_a.job_id
        assert job_b.state == "running"
    finally:
        release_a.set()
        release_b.set()
        registry.join(job_a.job_id, timeout=_TIMEOUT)
        registry.join(job_b.job_id, timeout=_TIMEOUT)


def test_a_target_that_returns_normally_ends_succeeded() -> None:
    """A worker that finishes without declaring an outcome is treated as succeeded -- the
    registry's fallback path, exercised here because `_noop` never calls `handle.finish` itself."""
    registry = IngestRegistry()
    job = registry.start("succeed", items_total=1, target=_noop)
    registry.join(job.job_id, timeout=_TIMEOUT)
    final = registry.get(job.job_id)
    assert final is not None
    assert final.state == "succeeded"


def test_a_target_that_raises_ends_failed_with_the_exception_text() -> None:
    """A crashed worker must surface as a failed job, never as one that claims to be running
    forever -- this registry is the only thing that can record how an in-memory job ended."""
    registry = IngestRegistry()

    def _boom(cancel_event: threading.Event, handle: JobHandle) -> None:
        raise ValueError("boom-message")

    job = registry.start("crashes", items_total=1, target=_boom)
    registry.join(job.job_id, timeout=_TIMEOUT)
    final = registry.get(job.job_id)
    assert final is not None
    assert final.state == "failed"
    assert final.error is not None
    assert "boom-message" in final.error


def test_an_explicit_cancelled_finish_is_not_overwritten_to_succeeded() -> None:
    """`only_if_unfinished=True` on the registry's own fallback call exists precisely so a worker
    that already declared itself cancelled (or failed) is never silently relabelled succeeded just
    because it then returned normally."""
    registry = IngestRegistry()

    def _self_cancels(cancel_event: threading.Event, handle: JobHandle) -> None:
        handle.finish(state="cancelled")

    job = registry.start("cancels-itself", items_total=1, target=_self_cancels)
    registry.join(job.job_id, timeout=_TIMEOUT)
    final = registry.get(job.job_id)
    assert final is not None
    assert final.state == "cancelled"


def test_cancel_sets_the_event_the_target_polls() -> None:
    """`cancel` must not block or reach into the thread -- it only flips the `threading.Event` the
    target is expected to poll between items, which is why the target here observes the flip via
    `cancel_event.wait` rather than any registry call."""
    registry = IngestRegistry()

    def _watches_for_cancel(cancel_event: threading.Event, handle: JobHandle) -> None:
        triggered = cancel_event.wait(timeout=_TIMEOUT)
        if triggered:
            handle.finish(state="cancelled")
        else:
            handle.finish(state="failed", error="cancel_event was never set")

    job = registry.start("cancellable", items_total=1, target=_watches_for_cancel)
    assert registry.cancel(job.job_id) is True
    registry.join(job.job_id, timeout=_TIMEOUT)
    final = registry.get(job.job_id)
    assert final is not None
    assert final.state == "cancelled"


def test_cancel_on_an_unknown_job_id_returns_false() -> None:
    """A caller cancelling a job the process never saw (or has since evicted from history) gets a
    clean `False`, not an exception."""
    registry = IngestRegistry()
    assert registry.cancel("no-such-job-id") is False


def test_progress_updates_only_the_counters_it_was_given() -> None:
    """`JobHandle.progress` must be a partial update: reporting `done` alone must leave
    `items_failed` and `items_total` exactly as they were, or a poller would see counters flicker
    to 0 on every progress tick."""
    registry = IngestRegistry()
    progress_applied = threading.Event()
    release = threading.Event()

    def _reports_progress_then_waits(cancel_event: threading.Event, handle: JobHandle) -> None:
        handle.progress(done=3)
        progress_applied.set()
        release.wait(timeout=_TIMEOUT)

    job = registry.start("progressing", items_total=10, target=_reports_progress_then_waits)
    try:
        assert progress_applied.wait(timeout=_TIMEOUT), "target never reported progress in time"
        mid_flight = registry.get(job.job_id)
        assert mid_flight is not None
        assert mid_flight.items_done == 3
        assert mid_flight.items_failed == 0
        assert mid_flight.items_total == 10
        assert mid_flight.state == "running"
    finally:
        release.set()
        registry.join(job.job_id, timeout=_TIMEOUT)


def test_get_on_an_unknown_job_id_returns_none() -> None:
    """A poller asking about a `job_id` this process never issued (wrong process, or a restart --
    see the module docstring) must get `None`, never a KeyError."""
    registry = IngestRegistry()
    assert registry.get("no-such-job-id") is None


def test_the_active_slot_is_released_once_the_target_finishes() -> None:
    """A finished ingest must free its slug's slot -- otherwise a persona could only ever be
    ingested once per process lifetime."""
    registry = IngestRegistry()
    first = registry.start("reusable", items_total=1, target=_noop)
    registry.join(first.job_id, timeout=_TIMEOUT)
    assert registry.active("reusable") is None

    second = registry.start("reusable", items_total=2, target=_noop)  # must not raise
    assert second.job_id != first.job_id
    registry.join(second.job_id, timeout=_TIMEOUT)
