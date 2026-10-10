"""One-active-ingest-per-persona job registry.

The same in-process daemon-thread pattern `app.agentdesk.jobs.DeskRegistry` uses, with one deliberate
difference: **this registry owns the `IngestJob` record itself**, rather than delegating run state to
a store on disk.

`DeskRegistry` can stay stateless about a run's status because `app.agentdesk.store.RunStore` persists
a `DeskRun` snapshot at every stage transition, so `GET /runs/{run_id}` reads the disk. An ingest has
no such per-stage snapshot to read: its durable output is the set of episodic notes it wrote into the
vault, and those are the point of the feature -- a job record that outlived the process would add a
second, separate thing to keep consistent with them for no gain. So `IngestJob` lives here, in memory,
for as long as the process does. The consequence is stated plainly rather than hidden: **a server
restart forgets in-flight and completed job records, but never loses an ingested note.** A caller
polling a `job_id` across a restart gets a 404, which is honest -- the job genuinely is not running
any more and this process cannot say how it ended.

**One active job per persona slug, not one globally.** Two personas ingesting at once contend only for
the model budget and YouTube's patience, not for a single mutable resource -- each writes into its own
`<vault>/influencers/<slug>/` tree. Gating them behind one global lock would serialise two independent
backfills for no reason. Two ingests of the *same* persona, though, would race on the same note
filenames and the same `persona.json`, so that is the slot this registry enforces.

Cancellation follows the established rule: `cancel` sets a `threading.Event` the worker checks
*between* items, never mid-call, so an ingest stops before the next video rather than abandoning one
in flight.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import uuid
from collections import deque
from collections.abc import Callable

from app.personas.models import IngestJob

__all__ = ["IngestAlreadyActive", "IngestRegistry", "registry"]

logger = logging.getLogger(__name__)

#: Bounded for the same reason `app.agentdesk.jobs._HISTORY_MAXLEN` is: a long-lived process must not
#: accumulate job records without limit. An evicted job's *notes* are still in the vault; only the
#: ability to poll that particular `job_id` goes away.
_HISTORY_MAXLEN = 200


class IngestAlreadyActive(RuntimeError):
    """`slug` already has an ingest in flight -- see `IngestRegistry.start`."""

    def __init__(self, slug: str, job_id: str) -> None:
        super().__init__(f"an ingest is already running for persona {slug!r}: {job_id}")
        self.slug = slug
        self.job_id = job_id


class _Slot:
    """One ingest's bookkeeping: its current record, its thread, and how to ask it to stop.

    `job` is replaced wholesale rather than mutated, because `IngestJob` is frozen -- a poller reading
    it under the registry lock therefore always sees one coherent snapshot, never a half-updated one.
    """

    __slots__ = ("cancel_event", "job", "thread")

    def __init__(self, job: IngestJob) -> None:
        self.job = job
        self.cancel_event = threading.Event()
        self.thread: threading.Thread | None = None


class IngestRegistry:
    """Process-wide bookkeeping for in-flight ingests, one active slot per persona slug."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, _Slot] = {}
        self._history: deque[_Slot] = deque(maxlen=_HISTORY_MAXLEN)
        self._by_job_id: dict[str, _Slot] = {}

    def start(
        self,
        slug: str,
        *,
        items_total: int,
        target: Callable[[threading.Event, JobHandle], None],
    ) -> IngestJob:
        """Queue an ingest for `slug` and launch `target` on a daemon thread.

        Returns the job's initial record immediately -- the route answers `202 Accepted` with it while
        the work proceeds. Raises `IngestAlreadyActive` if `slug` already has one in flight, atomically
        under the same lock the completion callback releases under, so a finishing job and a starting
        one cannot race into an inconsistent slot.

        `target` receives the cancellation event to poll between items and a `JobHandle` to report
        progress through. **An exception escaping `target` is caught here** and recorded on the job as
        `state="failed"` with the exception text, so a crashed worker surfaces as a failed job rather
        than as a job that claims to be running forever. That is a real difference from
        `DeskRegistry.start`, which only logs: there the run's terminal state is already on disk, here
        this registry is the only thing that can record it.
        """
        with self._lock:
            existing = self._active.get(slug)
            if existing is not None:
                raise IngestAlreadyActive(slug, existing.job.job_id)

            job_id = uuid.uuid4().hex[:16]
            slot = _Slot(
                IngestJob(
                    job_id=job_id,
                    persona=slug,
                    state="running",
                    items_total=items_total,
                    started_at=dt.datetime.now(dt.UTC),
                )
            )
            handle = JobHandle(self, job_id)

            def _run() -> None:
                try:
                    target(slot.cancel_event, handle)
                except Exception as exc:  # deliberately broad; see the docstring
                    logger.exception("personas: ingest %s for %s raised out of its thread", job_id, slug)
                    handle.finish(state="failed", error=f"{type(exc).__name__}: {exc}")
                else:
                    # A worker that finished without declaring an outcome is treated as succeeded --
                    # but only if it has not already set one, so an explicit `finish` inside `target`
                    # (including a cancellation) is never overwritten here.
                    handle.finish(state="succeeded", only_if_unfinished=True)
                finally:
                    with self._lock:
                        if self._active.get(slug) is slot:
                            del self._active[slug]

            thread = threading.Thread(target=_run, daemon=True, name=f"personas-ingest-{slug}-{job_id}")
            slot.thread = thread

            self._active[slug] = slot
            if len(self._by_job_id) >= _HISTORY_MAXLEN and self._history:
                evicted = self._history.popleft()
                self._by_job_id.pop(evicted.job.job_id, None)
            self._history.append(slot)
            self._by_job_id[job_id] = slot

            thread.start()
            return slot.job

    def active(self, slug: str) -> str | None:
        """The `job_id` currently in flight for `slug`, or `None` if that slot is free."""
        with self._lock:
            slot = self._active.get(slug)
            return slot.job.job_id if slot is not None else None

    def get(self, job_id: str) -> IngestJob | None:
        """The current record for `job_id`, or `None` if this process never saw it (or evicted it)."""
        with self._lock:
            slot = self._by_job_id.get(job_id)
            return slot.job if slot is not None else None

    def cancel(self, job_id: str) -> bool:
        """Set `job_id`'s cancellation event. `False` for an unknown job. Does not wait: the worker
        checks the event between items, so an ingest stops before the next video rather than
        abandoning one mid-fetch."""
        with self._lock:
            slot = self._by_job_id.get(job_id)
        if slot is None:
            return False
        slot.cancel_event.set()
        return True

    def join(self, job_id: str, timeout: float | None = None) -> None:
        """Block until `job_id`'s thread finishes. A no-op for an unknown job. For tests: production
        callers poll `get`, which the worker updates as it runs."""
        with self._lock:
            slot = self._by_job_id.get(job_id)
        if slot is None or slot.thread is None:
            return
        slot.thread.join(timeout)

    # -- used by JobHandle ---------------------------------------------------

    def update_job(self, job_id: str, **changes: object) -> None:
        """Replace `job_id`'s record with a copy carrying `changes`. Public rather than underscored
        only because `JobHandle` (a separate class in this module) is its sole caller and a private
        name would be a lint violation at that call site; treat it as internal to this module."""
        with self._lock:
            slot = self._by_job_id.get(job_id)
            if slot is None:
                return
            slot.job = slot.job.model_copy(update=changes)


class JobHandle:
    """The narrow surface a worker uses to report progress, so the worker never touches the registry's
    lock or its slots directly.

    Every method is safe to call from the worker thread and is a no-op for a job the registry has
    forgotten, so a very long ingest that outlived its own history entry cannot crash on its last
    progress report.
    """

    def __init__(self, registry_: IngestRegistry, job_id: str) -> None:
        self._registry = registry_
        self._job_id = job_id
        self._finished = False

    @property
    def job_id(self) -> str:
        return self._job_id

    def progress(self, *, done: int | None = None, failed: int | None = None,
                 total: int | None = None, spent_usd: str | None = None) -> None:
        """Update the counters a poller renders. Only the arguments given are changed."""
        changes: dict[str, object] = {}
        if done is not None:
            changes["items_done"] = done
        if failed is not None:
            changes["items_failed"] = failed
        if total is not None:
            changes["items_total"] = total
        if spent_usd is not None:
            changes["spent_usd"] = spent_usd
        if changes:
            self._registry.update_job(self._job_id, **changes)

    def finish(
        self,
        *,
        state: str,
        error: str | None = None,
        only_if_unfinished: bool = False,
    ) -> None:
        """Record a terminal state once. A second call is ignored unless it is an explicit override,
        which is what keeps the registry's own "worker returned, call it succeeded" fallback from
        clobbering a worker that already declared itself cancelled or failed."""
        if self._finished and only_if_unfinished:
            return
        self._finished = True
        self._registry.update_job(
            self._job_id,
            state=state,
            error=error,
            finished_at=dt.datetime.now(dt.UTC),
        )


_registry = IngestRegistry()


def registry() -> IngestRegistry:
    """The process-wide `IngestRegistry`. A module-level singleton for the same reason
    `app.agentdesk.jobs.registry` is one: there is exactly one of it per process, and a cached factory
    would only add a way to accidentally hold two."""
    return _registry
