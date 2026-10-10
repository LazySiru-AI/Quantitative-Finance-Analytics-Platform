"""In-process job registry for a full multi-timeframe rule-accuracy sweep.

Mirrors `app.tournament.jobs`' submit/poll/cancel shape (see that module's docstring for the full
rationale: an in-process daemon-thread worker rather than a detached subprocess, so cancellation is
real and a crash cannot orphan a process the caller only *thinks* it killed) -- but this module is
**not** a tournament round and deliberately does not import or touch `app.tournament.jobs` at all.

**Why an independent lock.** `app.tournament.jobs`' process-wide lock exists to keep two backtests
from reading the DuckDB bar store at once (`strategy-program/DEFECTS.md` D3). It is held by real
tournament rounds, which can run for hours. A research sweep contending with that lock would mean a
person cannot explore this study while a round happens to be running, for no reason connected to
this package's own correctness -- so `_SweepRegistry` below is its own class, with its own
`threading.Lock`, holding its own `_current` slot. The two registries share no state, no lock object
and no import edge; independence here is structural, not a runtime check.

**The unit of work is one `(symbol, interval)` pair.** All rules and horizons for a pair compute off
one shared indicator cache (see `docs/research/timeframes/06-interface-contract.md` section 3), so the
worker below calls `compute_cells` once per pair rather than once per rule. A pair that raises
(a fetch failure, a bad provider response) is recorded as a `SweepPairFailure` and walked past --
losing 1 of 140 pairs to a transient fetch error must not lose the other 139, the same reasoning
`app.tournament.jobs._worker` applies per card.

**Cancellation** sets a `threading.Event` checked between pairs, never inside `compute_cells` itself
-- there is no safe interruption point inside a pair's computation, the same reasoning
`app.tournament.jobs.request_cancel` gives for cancelling between cards rather than mid-`run_card`.

**`compute_cells`/`aggregate` are imported lazily**, inside the worker function, not at module load.
`app.timeframes.service` is being written concurrently against the frozen contract in
`app.timeframes.models` and may not exist, or may not yet import cleanly, at any given moment while
this module is developed alongside it -- importing it eagerly here would make this module's own
importability (and every test that merely imports `app.timeframes.jobs`) hostage to that module's
completeness. `_service()` below is the same indirection `app.api.rules._grammar`/`_evaluator` use for
`app.rules.grammar`/`app.rules.evaluate`, and tests monkeypatch it exactly the same way.
"""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from collections import deque
from types import ModuleType
from typing import Literal

from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.db.duck import Interval
from app.timeframes.models import (
    DEFAULT_COST_BPS,
    RESEARCH_UNIVERSE,
    RuleAccuracyCell,
    Scope,
    symbols_in,
)

__all__ = [
    "JobAlreadyFinished",
    "JobNotFound",
    "SweepAccepted",
    "SweepAlreadyRunning",
    "SweepCreateRequest",
    "SweepCurrent",
    "SweepList",
    "SweepPairFailure",
    "SweepStatus",
    "UnknownSector",
    "UnknownSymbol",
    "get_sweep",
    "list_sweeps",
    "request_cancel",
    "reset_registry",
    "start_sweep",
]

#: Every symbol in the frozen research universe, in universe order -- the default when a request
#: names neither `symbols` nor `sectors`.
_ALL_SYMBOLS: tuple[str, ...] = tuple(symbol for symbol, _ in RESEARCH_UNIVERSE)
_ALL_SYMBOLS_SET: frozenset[str] = frozenset(_ALL_SYMBOLS)
_ALL_SECTORS: frozenset[str] = frozenset(sector for _, sector in RESEARCH_UNIVERSE)

#: All seven intervals, in the contract's finest-to-coarsest order -- the default when a request
#: names no `intervals`.
_ALL_INTERVALS: tuple[Interval, ...] = tuple(Interval)

_LOG_MAXLEN = 200
_HISTORY_MAXLEN = 50


# ---------------------------------------------------------------------------
# Errors -- raised by `start_sweep`/`request_cancel`, translated to HTTP status by
# `app.api.timeframes`. Kept as plain exceptions here (not HTTPException) so this module has no
# FastAPI dependency, matching `app.tournament.jobs`'s own choice.
# ---------------------------------------------------------------------------


class UnknownSymbol(ValueError):
    """A requested symbol is not in `RESEARCH_UNIVERSE` -- maps to 422, naming what is available."""

    def __init__(self, symbol: str, available: list[str]) -> None:
        super().__init__(
            f"unknown symbol {symbol!r}; the research universe is: {', '.join(available)}"
        )
        self.symbol = symbol
        self.available = available


class UnknownSector(ValueError):
    """A requested sector is not one of the universe's own sector labels -- maps to 422."""

    def __init__(self, sector: str, available: list[str]) -> None:
        super().__init__(f"unknown sector {sector!r}; available: {', '.join(available)}")
        self.sector = sector
        self.available = available


class SweepAlreadyRunning(RuntimeError):
    """A sweep is already `queued`/`running` -- maps to 409, naming the live `job_id`."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"a sweep is already running: job {job_id}")
        self.job_id = job_id


class JobNotFound(KeyError):
    """No job with this id in the registry -- maps to 404."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"no job {job_id!r}")
        self.job_id = job_id


class JobAlreadyFinished(RuntimeError):
    """Cancellation requested on a job whose status is already terminal -- maps to 409."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job {job_id} already finished")
        self.job_id = job_id


# ---------------------------------------------------------------------------
# Wire models
# ---------------------------------------------------------------------------


class SweepCreateRequest(BaseModel):
    """`POST /api/timeframes/matrix/jobs` request body."""

    symbols: list[str] = Field(default_factory=list)
    """Symbols to sweep. Empty (with `sectors` also empty) means the whole research universe."""
    sectors: list[str] = Field(default_factory=list)
    """Sector labels (from `RESEARCH_UNIVERSE`) to expand into symbols, unioned with `symbols`."""
    intervals: list[Interval] = Field(default_factory=list)
    """Intervals to sweep. Empty means all seven."""
    rule_ids: list[str] | None = None
    """`None` means the whole rule catalog -- passed straight through to `compute_cells`."""
    horizon_minutes: int | None = None
    """When given, only cells at this cross-interval horizon are kept."""
    scope: Scope = "sector"
    cost_bps: float = DEFAULT_COST_BPS


class SweepPairFailure(BaseModel):
    """One `(symbol, interval)` pair that raised during the sweep, recorded and walked past."""

    symbol: str
    interval: Interval
    error: str


class SweepCurrent(BaseModel):
    """The `(symbol, interval)` pair the worker is computing right now, if any."""

    symbol: str
    interval: Interval


class SweepAccepted(BaseModel):
    """Response to `POST /api/timeframes/matrix/jobs`."""

    job_id: str
    status: Literal["queued", "running"]
    total_pairs: int
    created_at: dt.datetime


class SweepStatus(BaseModel):
    """Full job state, returned by `GET /api/timeframes/matrix/jobs/{job_id}`."""

    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    symbols: list[str]
    intervals: list[Interval]
    scope: Scope
    total_pairs: int
    completed_pairs: int
    failed_pairs: int
    current: SweepCurrent | None = None
    created_at: dt.datetime
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    elapsed_seconds: float
    log: list[str]
    """Last `_LOG_MAXLEN` lines -- a bounded deque, not the whole sweep's history."""
    cells: list[RuleAccuracyCell]
    failures: list[SweepPairFailure]
    error: str | None = None
    """Set only when something killed the job itself, never for an individual pair's failure (that
    goes in `failures` instead) -- matching `app.tournament.jobs.JobStatus.error`'s own contract."""


class SweepList(BaseModel):
    """Every tracked sweep, newest first."""

    jobs: list[SweepStatus]


# ---------------------------------------------------------------------------
# Lazy service accessor -- see the module docstring for why this is not a top-level import.
# ---------------------------------------------------------------------------


def _service() -> ModuleType:
    from app.timeframes import service

    return service


# ---------------------------------------------------------------------------
# Symbol/interval resolution -- shared by the sync `/matrix` endpoint and this module's own
# `start_sweep`, so both apply the exact same validation and defaulting rules.
# ---------------------------------------------------------------------------


def resolve_symbols(symbols: list[str], sectors: list[str]) -> tuple[str, ...]:
    """Validate and resolve a symbol/sector selection against the frozen research universe.

    `symbols` and `sectors` are unioned (in that order, symbols first), each de-duplicated on first
    occurrence. Both empty resolves to the entire universe, in universe order. An unknown symbol or
    sector is a `ValueError` naming the offender and what is actually available, never a silent drop.
    """
    upper_symbols = [s.upper() for s in symbols]
    unknown_symbols = [s for s in upper_symbols if s not in _ALL_SYMBOLS_SET]
    if unknown_symbols:
        raise UnknownSymbol(unknown_symbols[0], sorted(_ALL_SYMBOLS_SET))

    unknown_sectors = [s for s in sectors if s not in _ALL_SECTORS]
    if unknown_sectors:
        raise UnknownSector(unknown_sectors[0], sorted(_ALL_SECTORS))

    resolved: list[str] = []
    seen: set[str] = set()
    for symbol in upper_symbols:
        if symbol not in seen:
            seen.add(symbol)
            resolved.append(symbol)
    for sector in sectors:
        for symbol in symbols_in(sector):
            if symbol not in seen:
                seen.add(symbol)
                resolved.append(symbol)

    if not resolved:
        return _ALL_SYMBOLS
    return tuple(resolved)


def resolve_intervals(intervals: list[Interval]) -> tuple[Interval, ...]:
    """De-duplicate `intervals`, defaulting to all seven when empty."""
    if not intervals:
        return _ALL_INTERVALS
    resolved: list[Interval] = []
    seen: set[Interval] = set()
    for interval in intervals:
        if interval not in seen:
            seen.add(interval)
            resolved.append(interval)
    return tuple(resolved)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


class _SweepJob:
    """Mutable state for one sweep, guarded by its own lock -- independent of
    `app.tournament.jobs._Job`'s lock. See the module docstring."""

    def __init__(
        self,
        *,
        symbols: tuple[str, ...],
        intervals: tuple[Interval, ...],
        scope: Scope,
        rule_ids: list[str] | None,
        horizon_minutes: int | None,
        cost_bps: float,
    ) -> None:
        self.job_id = uuid.uuid4().hex
        self.symbols = symbols
        self.intervals = intervals
        self.scope = scope
        self.rule_ids = rule_ids
        self.horizon_minutes = horizon_minutes
        self.cost_bps = cost_bps
        self.total_pairs = len(symbols) * len(intervals)
        self.completed_pairs = 0
        self.failed_pairs = 0
        self.current: tuple[str, Interval] | None = None
        self.status: Literal["queued", "running", "succeeded", "failed", "cancelled"] = "running"
        self.created_at = dt.datetime.now(dt.UTC)
        self.started_at: dt.datetime | None = None
        self.finished_at: dt.datetime | None = None
        self.log: deque[str] = deque(maxlen=_LOG_MAXLEN)
        self.cells: list[RuleAccuracyCell] = []
        self.failures: list[SweepPairFailure] = []
        self.error: str | None = None
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()

    def append_log(self, line: str) -> None:
        with self.lock:
            self.log.append(line)

    def snapshot(self) -> SweepStatus:
        with self.lock:
            end = self.finished_at or dt.datetime.now(dt.UTC)
            current = (
                SweepCurrent(symbol=self.current[0], interval=self.current[1])
                if self.current
                else None
            )
            return SweepStatus(
                job_id=self.job_id,
                status=self.status,
                symbols=list(self.symbols),
                intervals=list(self.intervals),
                scope=self.scope,
                total_pairs=self.total_pairs,
                completed_pairs=self.completed_pairs,
                failed_pairs=self.failed_pairs,
                current=current,
                created_at=self.created_at,
                started_at=self.started_at,
                finished_at=self.finished_at,
                elapsed_seconds=(end - self.created_at).total_seconds(),
                log=list(self.log),
                cells=list(self.cells),
                failures=list(self.failures),
                error=self.error,
            )


class _SweepRegistry:
    """Process-wide sweep bookkeeping: the one-sweep-at-a-time lock, and a bounded history.

    A distinct class and a distinct module-level instance from `app.tournament.jobs._Registry` --
    see the module docstring for why sharing either would be a mistake, not a simplification.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: _SweepJob | None = None
        self._jobs: deque[_SweepJob] = deque(maxlen=_HISTORY_MAXLEN)
        self._by_id: dict[str, _SweepJob] = {}

    def register(self, job: _SweepJob) -> None:
        """Atomically check-and-set the running slot. Raises `SweepAlreadyRunning` if occupied."""
        with self._lock:
            if self._current is not None:
                raise SweepAlreadyRunning(self._current.job_id)
            self._current = job
            if self._jobs.maxlen is not None and len(self._jobs) >= self._jobs.maxlen:
                evicted = self._jobs.pop()
                self._by_id.pop(evicted.job_id, None)
            self._jobs.appendleft(job)
            self._by_id[job.job_id] = job

    def running_job_id(self) -> str | None:
        with self._lock:
            return self._current.job_id if self._current is not None else None

    def finish(self, job: _SweepJob) -> None:
        with self._lock:
            if self._current is job:
                self._current = None

    def get(self, job_id: str) -> _SweepJob:
        with self._lock:
            job = self._by_id.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        return job

    def list_jobs(self) -> list[_SweepJob]:
        with self._lock:
            return list(self._jobs)


_registry = _SweepRegistry()


def reset_registry() -> None:
    """Testing hook: drop every tracked sweep, exactly the way `app.tournament.jobs.reset_registry`
    does for its own (separate) registry. Without this, the "one sweep at a time" lock and the job
    history would leak across tests in the same process; the worker thread is a daemon so it cannot
    keep the test process alive but does not, on its own, clear the registry's slot early.
    """
    global _registry
    _registry = _SweepRegistry()


def start_sweep(request: SweepCreateRequest, *, settings: Settings | None = None) -> SweepAccepted:
    """Validate `request`, launch its worker thread, and return immediately.

    Validation order matches `app.tournament.jobs.start_job`: is a sweep already running (409,
    cheapest check, fails fast before resolving anything); are the requested symbols/sectors and
    intervals valid (422 each). A `SweepAlreadyRunning` from a race against another concurrent call
    can still surface from `_SweepRegistry.register` itself after this function's own pre-check
    passed -- that atomic check is what actually enforces the invariant, exactly as in
    `app.tournament.jobs`.
    """
    running = _registry.running_job_id()
    if running is not None:
        raise SweepAlreadyRunning(running)

    symbols = resolve_symbols(request.symbols, request.sectors)
    intervals = resolve_intervals(request.intervals)

    job = _SweepJob(
        symbols=symbols,
        intervals=intervals,
        scope=request.scope,
        rule_ids=request.rule_ids,
        horizon_minutes=request.horizon_minutes,
        cost_bps=request.cost_bps,
    )
    _registry.register(job)

    # Read before the worker starts -- the same race `app.tournament.jobs.start_job` documents at
    # its own identical line: `job.status` is mutated by the worker thread, so reading it after
    # `thread.start()` could already observe a terminal status for a very fast (or immediately
    # failing) sweep, which would make an honestly-accepted job report a 500 instead of a 202.
    assert job.status == "running", f"a job is {job.status!r} before its worker has started"
    accepted = SweepAccepted(
        job_id=job.job_id,
        status="running",
        total_pairs=job.total_pairs,
        created_at=job.created_at,
    )

    resolved_settings = settings if settings is not None else get_settings()
    thread = threading.Thread(
        target=_worker,
        args=(job,),
        kwargs={"settings": resolved_settings},
        daemon=True,
        name=f"timeframes-sweep-{job.job_id}",
    )
    thread.start()

    return accepted


def get_sweep(job_id: str) -> SweepStatus:
    return _registry.get(job_id).snapshot()


def list_sweeps() -> SweepList:
    return SweepList(jobs=[job.snapshot() for job in _registry.list_jobs()])


def request_cancel(job_id: str) -> SweepStatus:
    """Set the job's cancellation event. The worker notices between pairs, never mid-`compute_cells`
    -- see the module docstring for why interrupting a pair in flight is not attempted."""
    job = _registry.get(job_id)
    with job.lock:
        if job.status not in ("queued", "running"):
            raise JobAlreadyFinished(job_id)
        job.cancel_event.set()
    job.append_log("cancellation requested")
    return job.snapshot()


def _worker(job: _SweepJob, *, settings: Settings) -> None:
    """Walk every `(symbol, interval)` pair in `job`, calling `compute_cells` once per pair and
    recording a failure (rather than aborting) for any pair that raises. See the module docstring for
    the reasoning behind every choice below; this function is deliberately the only place it is
    executed."""
    with job.lock:
        job.started_at = dt.datetime.now(dt.UTC)
    job.append_log(
        f"sweep {job.job_id}: {len(job.symbols)} symbols x {len(job.intervals)} intervals "
        f"= {job.total_pairs} pairs"
    )

    service = _service()

    for symbol in job.symbols:
        if job.cancel_event.is_set():
            break

        for interval in job.intervals:
            if job.cancel_event.is_set():
                job.append_log(f"cancelled before {symbol} {interval.value}")
                break

            with job.lock:
                job.current = (symbol, interval)

            try:
                cells = service.compute_cells(
                    symbols=[symbol],
                    intervals=[interval],
                    rule_ids=job.rule_ids,
                    cost_bps=job.cost_bps,
                    settings=settings,
                )
                if job.horizon_minutes is not None:
                    cells = [c for c in cells if c.horizon_minutes == job.horizon_minutes]
            except Exception as exc:  # recorded and walked past -- see module docstring
                error_text = f"{type(exc).__name__}: {exc}"
                with job.lock:
                    job.failed_pairs += 1
                    job.failures.append(
                        SweepPairFailure(symbol=symbol, interval=interval, error=error_text)
                    )
                job.append_log(f"{symbol} {interval.value}: FAILED {error_text}")
                continue

            with job.lock:
                job.completed_pairs += 1
                job.cells.extend(cells)
            job.append_log(f"{symbol} {interval.value}: ok {len(cells)} cell(s)")

        with job.lock:
            job.current = None

        if job.cancel_event.is_set():
            break

    # Pool to the requested scope once, over the whole accumulated grid -- never per pair, since
    # pooling per pair would silently reduce to per-symbol scope (see 06-interface-contract.md
    # section 3: "aggregate must pool the underlying counts... FDR is computed once over the entire
    # returned grid"). A failure here is logged and walked past rather than failing the job: the
    # per-symbol cells already collected are still the honest, correct result at `scope="symbol"`,
    # and a caller that asked for pooling is better served by an un-pooled grid than by no grid.
    with job.lock:
        cells_to_pool = list(job.cells)
        scope = job.scope
    if scope != "symbol" and cells_to_pool:
        try:
            pooled = service.aggregate(cells_to_pool, to=scope)
        except Exception as exc:
            job.append_log(f"aggregate to {scope!r} FAILED, returning per-symbol cells: {exc}")
        else:
            with job.lock:
                job.cells = pooled

    with job.lock:
        job.current = None
        job.finished_at = dt.datetime.now(dt.UTC)
        job.status = "cancelled" if job.cancel_event.is_set() else "succeeded"

    _registry.finish(job)
