"""A single-slot, per-desk-kind job registry -- the same in-process, daemon-thread pattern
`app.tournament.jobs` uses for a competition round, narrowed to what a desk run needs.

**Why in-process daemon threads, never a subprocess.** See `app.tournament.jobs`'s own module
docstring for the incident this pattern exists to prevent (`strategy-program/DEFECTS.md` D3): a
detached process launched with no completion signal was killed by PID, which killed the process but
not whatever was driving it, which promptly relaunched a replacement, and the two then fought over
the same store. A thread inside this process has no shell loop above it to survive it, and
`DeskRegistry.cancel` sets a `threading.Event` the worker itself is expected to check -- cancellation
here cancels, rather than orphaning work the caller only *thinks* it stopped.

**Why one active run per desk *kind*, not one run for the whole registry.** `app.tournament.jobs`
enforces a single global slot because every round contends for the same DuckDB bar store and the same
16 GB host. A `tradingagents` run and a `vibedesk` run make model calls and read the same market-data
store too, but they do not write into each other's `data/agentdesk/<kind>/runs/` tree and do not share
a single mutable resource the way two tournament rounds share the bar store -- so gating both desks
behind one lock would block a VibeDesk research run for no reason while a TradingAgents pipeline is
mid-debate. The lock in this module is therefore keyed by `DeskKind`, not global.

**Why a caller passes a plain `Callable[[threading.Event], None]` rather than this module owning the
run's control flow.** `app.tournament.jobs._worker` owns its own loop because there is exactly one
shape of work it runs (a card x window matrix). A desk run's shape differs by `DeskKind` -- a fixed
pipeline for TradingAgents, a preset-defined DAG for VibeDesk -- and neither shape belongs inside a
package that is shared machinery for both. This registry's job is only the slot, the thread, and the
cancellation signal; the caller (each desk's own orchestrator) is the one that knows how to drive its
stages, check the event between them, and call `app.agentdesk.store.RunStore.save` as it goes.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from app.agentdesk.models import DeskKind

__all__ = ["DeskRegistry", "RunAlreadyActive", "registry"]

logger = logging.getLogger(__name__)

#: Bounded so a long-running process's `_by_run_id` map cannot grow without limit -- mirrors
#: `app.tournament.jobs._HISTORY_MAXLEN`. A run evicted from this history is still on disk via
#: `app.agentdesk.store.RunStore`; only this registry's in-memory bookkeeping (cancel/cancelled/join
#: for that particular run_id) stops working for it, which is the same trade-off the tournament
#: registry already makes for its own job history.
_HISTORY_MAXLEN = 200


class RunAlreadyActive(RuntimeError):
    """`kind` already has a run in flight -- see `DeskRegistry.start`."""

    def __init__(self, kind: DeskKind, run_id: str) -> None:
        super().__init__(f"a {kind} run is already active: {run_id}")
        self.kind = kind
        self.run_id = run_id


@dataclass
class _Slot:
    """One run's bookkeeping: which thread is running it and how to ask it to stop.

    `thread` is set by `DeskRegistry.start` immediately after construction, before the thread is
    started -- it exists on this dataclass (rather than being threaded through as a second value)
    so `join` and the worker's own completion callback can reach it by `run_id` alone.
    """

    run_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


class DeskRegistry:
    """Process-wide bookkeeping for in-flight desk runs, one active slot per `DeskKind`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[DeskKind, _Slot] = {}
        self._history: deque[_Slot] = deque(maxlen=_HISTORY_MAXLEN)
        self._by_run_id: dict[str, _Slot] = {}

    def start(self, kind: DeskKind, run_id: str, target: Callable[[threading.Event], None]) -> None:
        """Launch `target` on a new daemon thread, passing it the cancellation event to poll.

        Raises `RunAlreadyActive` if `kind` already has a run in flight -- atomically, under the same
        lock the completion callback below releases under, so a run finishing and a new one starting
        can never race each other into an inconsistent slot.

        **Exceptions inside `target` never escape the thread.** A worker that raises is logged in full
        (`logger.exception`, so the traceback is captured) and its slot is released; it is the
        caller's own responsibility -- via `app.agentdesk.store.with_stage` and `RunStore.save` inside
        `target` itself -- to have already persisted a terminal `DeskRun.state` before that happens.
        This registry has no `DeskRun` of its own to mark failed; unlike `app.tournament.jobs._Job`,
        which owns its job's status directly, the run record here lives entirely in the caller's
        hands and on disk.
        """
        with self._lock:
            existing = self._active.get(kind)
            if existing is not None:
                raise RunAlreadyActive(kind, existing.run_id)

            slot = _Slot(run_id=run_id)

            def _run() -> None:
                try:
                    target(slot.cancel_event)
                except Exception:
                    logger.exception(
                        "agentdesk jobs: %s run %s raised out of its worker thread", kind, run_id
                    )
                finally:
                    with self._lock:
                        if self._active.get(kind) is slot:
                            del self._active[kind]

            thread = threading.Thread(target=_run, daemon=True, name=f"agentdesk-{kind}-{run_id}")
            slot.thread = thread

            self._active[kind] = slot
            if len(self._by_run_id) >= _HISTORY_MAXLEN and self._history:
                evicted = self._history.popleft()
                self._by_run_id.pop(evicted.run_id, None)
            self._history.append(slot)
            self._by_run_id[run_id] = slot

            thread.start()

    def active(self, kind: DeskKind) -> str | None:
        """The `run_id` currently in flight for `kind`, or `None` if that slot is free."""
        with self._lock:
            slot = self._active.get(kind)
            return slot.run_id if slot is not None else None

    def cancel(self, run_id: str) -> bool:
        """Set `run_id`'s cancellation event. `False` if this registry has never heard of `run_id`.

        Sets the event and returns; it does not wait for the worker to notice. `app.tournament.jobs`'s
        own docstring states the reasoning this module shares: a worker is expected to check the event
        *between* stages, never mid-call, so a run in the middle of a model call finishes that call
        before it stops -- interrupting a call in flight is not attempted, here any more than there.
        """
        with self._lock:
            slot = self._by_run_id.get(run_id)
        if slot is None:
            return False
        slot.cancel_event.set()
        return True

    def cancelled(self, run_id: str) -> bool:
        """Whether `cancel(run_id)` has been called. `False` for an unknown `run_id` as well as for a
        known one that was never cancelled -- a caller that needs to tell the two apart already has
        `active`/`join` and the persisted `DeskRun.state` to do it with."""
        with self._lock:
            slot = self._by_run_id.get(run_id)
        return slot is not None and slot.cancel_event.is_set()

    def join(self, run_id: str, timeout: float | None = None) -> None:
        """Block until `run_id`'s worker thread finishes, or `timeout` seconds elapse.

        A no-op for an unknown `run_id` -- there is nothing to join, and a test polling for a run that
        already fell out of `_HISTORY_MAXLEN`'s window has bigger problems than this method raising.
        Existence purely for tests, matching `app.tournament.jobs`'s own `_worker`'s daemon-thread
        design: production callers read a run's state from `app.agentdesk.store.RunStore`, which is
        updated as the thread runs, not by blocking on the thread itself.
        """
        with self._lock:
            slot = self._by_run_id.get(run_id)
        if slot is None or slot.thread is None:
            return
        slot.thread.join(timeout)


_registry = DeskRegistry()


def registry() -> DeskRegistry:
    """The process-wide `DeskRegistry` every desk orchestrator shares.

    A module-level singleton rather than a `functools.lru_cache`d factory -- there is exactly one of
    these per process, it holds no configuration to vary by argument, and a factory would only invite
    a caller to wonder whether two calls could ever return different registries. Tests that need
    isolation construct their own `DeskRegistry()` directly rather than resetting this one, since
    (unlike `app.tournament.jobs`'s registry) nothing else in the process reaches for this singleton
    by import-time side effect yet.
    """
    return _registry
