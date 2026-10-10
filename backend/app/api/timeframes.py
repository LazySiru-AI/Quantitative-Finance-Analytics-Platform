"""Multi-timeframe rule-accuracy study: intervals/universe metadata, the sync matrix slice, the
background sweep job, and the signal-trace drill-down.

`APIRouter(prefix="/api/timeframes")`, registered in `app.main` alongside the existing routers. See
`docs/research/timeframes/06-interface-contract.md` section 4 for the frozen endpoint table this
router implements literally.

Thin on purpose, matching `app.api.rules`: `/intervals` and `/universe` are static reads with no
service dependency at all; `/matrix` and `/signal` are synchronous wrappers over
`app.timeframes.service`; `/matrix/jobs*` are a thin translation of `app.timeframes.jobs`' domain
exceptions into HTTP status, the same relationship `app.api.competition_jobs` has to
`app.tournament.jobs`.

**`app.timeframes.service` is imported lazily**, inside `_service()`, never at module load. It is
being written concurrently against the frozen contract in `app.timeframes.models` and may not exist,
or may not yet import cleanly, while this router is developed alongside it -- see `_service()`'s own
docstring, which mirrors `app.api.rules._grammar`/`_evaluator`'s identical reasoning for
`app.rules.grammar`/`app.rules.evaluate`. Tests monkeypatch `_service` the same way
`tests/test_rules_api.py` monkeypatches `rules_api._grammar`.

**The size guard.** `GET /matrix` computes off however many `(symbol, interval)` pairs the request
resolves to; the unit of work is one such pair (see `app.timeframes.jobs`' module docstring). A
request resolving to more than `MAX_SYNC_PAIRS` pairs is refused with `422`, naming the actual pair
count and pointing at `POST /matrix/jobs` -- never `500`, and never left to run long enough to look
like a hang. This mirrors the fix this phase is explicitly not allowed to skip: passing an unsupported
`interval` string to the *existing* `/api/backtest` endpoints reaches a bare `BARS_PER_YEAR[interval]`
dict lookup and raises an uncaught `KeyError` (a `500`) -- see `app.backtest.models.BARS_PER_YEAR` and
`app.backtest.strategy.run_backtest`. Every `interval` value here is validated at this boundary
instead, explicitly, before anything downstream can raise on it.
"""

from __future__ import annotations

import datetime as dt
from types import ModuleType
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel

from app.agentdesk.models import RUN_ID_MAX_LENGTH, RUN_ID_PATTERN
from app.api.market import SymbolParam
from app.config import get_settings
from app.db.duck import Interval
from app.timeframes import jobs
from app.timeframes.models import (
    DEFAULT_COST_BPS,
    RESEARCH_UNIVERSE,
    RuleAccuracyCell,
    Scope,
    SignalTrace,
)

router = APIRouter(prefix="/api/timeframes", tags=["timeframes"])

#: The unit of compute is one `(symbol, interval)` pair; a full 20-name x 7-interval sweep is ~140
#: pairs and takes 36s-4min warm-cache (see the delivery brief's "Verified facts"). 20 keeps the
#: synchronous endpoint well under a request timeout even cold, while still being enough for a
#: single-symbol, all-intervals-but-one-or-two slice -- the "small on-demand slice" the contract
#: describes `/matrix` as being for.
MAX_SYNC_PAIRS = 20

#: `job_id`s are `uuid.uuid4().hex` -- 32 lowercase hex characters -- but this path parameter accepts
#: a slightly wider shape so a malformed id reads as this router's own 404 rather than a 422 the
#: caller has to interpret differently for the same underlying mistake. Matches
#: `app.api.competition_jobs.JobIdPath` exactly -- including the shared
#: `app.agentdesk.models.RUN_ID_PATTERN`. This registry is in-memory, so an id here never reaches the
#: filesystem, but the one constant across every id-keyed router is what keeps them from drifting
#: apart on what an id may contain; a future on-disk sweep archive inherits the bound for free.
JobIdPath = Annotated[
    str, Path(min_length=1, max_length=RUN_ID_MAX_LENGTH, pattern=RUN_ID_PATTERN)
]


# ---------------------------------------------------------------------------
# Wire shapes that exist only at this boundary
# ---------------------------------------------------------------------------


class IntervalInfo(BaseModel):
    """One row of `GET /intervals` -- static metadata, not a measurement.

    `bars_per_session`/`retention_days` are `None` exactly where the contract's own table (section 0)
    has a dash: `1w` has no session-native bar count (it is derived from daily bars, not fetched), and
    `1d`/`1w` retention is unbounded rather than a finite day count.
    """

    interval: Interval
    bars_per_session: int | None
    retention_days: int | None
    bars_per_year: int
    note: str = ""


class UniverseEntry(BaseModel):
    """One row of `GET /universe`."""

    symbol: str
    sector: str


class MatrixCoverage(BaseModel):
    """How much of the requested grid is actually measurable -- the honest headline for this
    feature, per the contract's own framing: `cells_sufficient` vs `cells_total`."""

    symbols: int
    intervals: int
    rules: int
    cells_total: int
    cells_sufficient: int


class MatrixResponse(BaseModel):
    """`GET /matrix` response -- field names match section 4's example verbatim."""

    cells: list[RuleAccuracyCell]
    generated_at: dt.datetime
    coverage: MatrixCoverage
    warnings: list[str]


#: Static per-interval metadata for `GET /intervals`, transcribed from
#: `docs/research/timeframes/06-interface-contract.md` section 0 (live-verified 2026-08-25) and from
#: `app.timeframes.models.interval_minutes`'s own nominal-minutes table, which this must stay
#: consistent with (`bars_per_year = minutes_per_year / interval_minutes`, minutes-per-session x
#: sessions-per-year).
_INTERVAL_CATALOG: tuple[IntervalInfo, ...] = (
    IntervalInfo(
        interval=Interval.FIVE_MIN, bars_per_session=78, retention_days=60, bars_per_year=19656
    ),
    IntervalInfo(
        interval=Interval.FIFTEEN_MIN, bars_per_session=26, retention_days=60, bars_per_year=6552
    ),
    IntervalInfo(
        interval=Interval.THIRTY_MIN, bars_per_session=13, retention_days=60, bars_per_year=3276
    ),
    IntervalInfo(
        interval=Interval.HOUR,
        bars_per_session=7,
        retention_days=730,
        bars_per_year=1764,
        note="the last bar of each session is a 30-minute stub, not a full hour",
    ),
    IntervalInfo(
        interval=Interval.FOUR_HOUR,
        bars_per_session=2,
        retention_days=730,
        bars_per_year=504,
        note="the second bar of each session is a 2.5h remainder, not a full 4h",
    ),
    IntervalInfo(interval=Interval.DAY, bars_per_session=1, retention_days=None, bars_per_year=252),
    IntervalInfo(
        interval=Interval.WEEK,
        bars_per_session=None,
        retention_days=None,
        bars_per_year=52,
        note="derived locally from daily bars, not fetched as its own interval",
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _service() -> ModuleType:
    """The real `app.timeframes.service` module, imported lazily -- see this module's own docstring
    for why. A separate indirection from `app.timeframes.jobs._service` (which exists for the same
    reason, for the sweep worker's own use) so tests can monkeypatch either boundary independently.

    `ModuleType` rather than a `Protocol` matching the three functions called through here. A
    protocol would type the call sites, but it would be a hand-maintained transcription of
    `service`'s signatures kept in step by inspection -- the same arrangement that has already
    drifted between `strategy-program/tools/` and the engine it mirrors. Attribute access is
    therefore `Any`, and the one call site asserting a return contract pins it explicitly below."""
    from app.timeframes import service

    return service


def _parse_csv(value: str | None) -> list[str]:
    """`"AAPL, msft"` -> `["AAPL", "msft"]`. `None` or blank -> `[]`, meaning "not specified" to
    every caller below, which then apply their own default (the whole universe, or all seven
    intervals) -- never a silent empty result."""
    if value is None:
        return []
    return [token.strip() for token in value.split(",") if token.strip()]


def _parse_intervals_csv(value: str | None) -> list[Interval]:
    """Validate a csv `intervals` query param against `Interval` at this boundary, before it can
    reach any downstream dict lookup -- see this module's docstring for the `KeyError`/500 this is
    explicitly here to avoid. Unknown values are reported together, naming every bad token and the
    full valid alphabet, rather than failing on only the first."""
    tokens = _parse_csv(value)
    valid = {member.value for member in Interval}
    unknown = [token for token in tokens if token not in valid]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"unknown interval(s) {unknown!r}; valid intervals are "
                f"{sorted(valid)}"
            ),
        )
    return [Interval(token) for token in tokens]


def _resolve_symbols_and_intervals(
    *, symbols_csv: str | None, sectors_csv: str | None, intervals_csv: str | None
) -> tuple[tuple[str, ...], tuple[Interval, ...]]:
    """Shared resolution for `GET /matrix`: parse csv params, validate them, and apply the same
    defaulting rules `app.timeframes.jobs.start_sweep` uses -- so a slice and a sweep for the "same"
    request always mean the same set of pairs."""
    symbols = _parse_csv(symbols_csv)
    sectors = _parse_csv(sectors_csv)
    intervals = _parse_intervals_csv(intervals_csv)

    try:
        resolved_symbols = jobs.resolve_symbols(symbols, sectors)
    except (jobs.UnknownSymbol, jobs.UnknownSector) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    resolved_intervals = jobs.resolve_intervals(intervals)
    return resolved_symbols, resolved_intervals


def _coverage(
    cells: list[RuleAccuracyCell], *, requested_symbols: int, requested_intervals: int
) -> MatrixCoverage:
    """`coverage.symbols`/`.intervals` report what was *requested*, not what survives aggregation --
    a sector/universe-scope cell no longer carries a per-symbol row to count, but the caller asked
    about a grid of this shape and that is what "coverage" answers. `.rules`/`.cells_total`/
    `.cells_sufficient` are read off the cells actually returned."""
    rules = {cell.rule_id for cell in cells}
    sufficient = sum(1 for cell in cells if cell.sufficient)
    return MatrixCoverage(
        symbols=requested_symbols,
        intervals=requested_intervals,
        rules=len(rules),
        cells_total=len(cells),
        cells_sufficient=sufficient,
    )


def _warnings(cells: list[RuleAccuracyCell]) -> list[str]:
    warnings: list[str] = []
    seen: set[str] = set()
    for cell in cells:
        for warning in cell.warnings:
            if warning not in seen:
                seen.add(warning)
                warnings.append(warning)
    return warnings


# ---------------------------------------------------------------------------
# Static metadata
# ---------------------------------------------------------------------------


@router.get("/intervals", response_model=list[IntervalInfo])
def intervals() -> list[IntervalInfo]:
    """The seven intervals this study covers, with retention and bars/session. Static and cheap --
    no service call, no bar store access."""
    return list(_INTERVAL_CATALOG)


@router.get("/universe", response_model=list[UniverseEntry])
def universe() -> list[UniverseEntry]:
    """The 20 frozen research-universe symbols with their sectors. Static and cheap."""
    return [UniverseEntry(symbol=symbol, sector=sector) for symbol, sector in RESEARCH_UNIVERSE]


# ---------------------------------------------------------------------------
# Synchronous matrix slice
# ---------------------------------------------------------------------------


@router.get("/matrix", response_model=MatrixResponse)
def matrix(
    symbols: str | None = Query(None, description="csv symbols, e.g. AAPL,MSFT"),
    sectors: str | None = Query(None, description="csv sector labels"),
    intervals: str | None = Query(None, description="csv intervals, default all seven"),
    rule_ids: str | None = Query(None, description="csv rule ids, default the whole catalog"),
    horizon_minutes: int | None = Query(None),
    scope: Scope = Query("sector"),  # noqa: B008 -- FastAPI's own idiom, as in `start_loop`
    cost_bps: float = Query(DEFAULT_COST_BPS),
) -> MatrixResponse:
    """A small, on-demand slice of the rule-accuracy grid, computed synchronously.

    Refuses (`422`) any request resolving to more than `MAX_SYNC_PAIRS` `(symbol, interval)` pairs --
    the unit of work `app.timeframes.service.compute_cells` computes per call -- and points the
    caller at `POST /matrix/jobs` instead. `symbols`/`sectors` default to the whole research universe
    when both are omitted; `intervals` defaults to all seven. An unknown symbol, sector or interval
    is `422`, never a downstream `KeyError`.
    """
    resolved_symbols, resolved_intervals = _resolve_symbols_and_intervals(
        symbols_csv=symbols, sectors_csv=sectors, intervals_csv=intervals
    )

    pair_count = len(resolved_symbols) * len(resolved_intervals)
    if pair_count > MAX_SYNC_PAIRS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"request resolves to {pair_count} (symbol, interval) pairs "
                f"({len(resolved_symbols)} symbols x {len(resolved_intervals)} intervals), "
                f"exceeding MAX_SYNC_PAIRS={MAX_SYNC_PAIRS}; submit this as a sweep via "
                "POST /api/timeframes/matrix/jobs instead"
            ),
        )

    rule_id_list = _parse_csv(rule_ids) or None

    try:
        cells = _service().compute_cells(
            symbols=resolved_symbols,
            intervals=resolved_intervals,
            rule_ids=rule_id_list,
            cost_bps=cost_bps,
            settings=get_settings(),
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if horizon_minutes is not None:
        cells = [cell for cell in cells if cell.horizon_minutes == horizon_minutes]

    if scope != "symbol" and cells:
        try:
            cells = _service().aggregate(cells, to=scope)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    coverage = _coverage(
        cells, requested_symbols=len(resolved_symbols), requested_intervals=len(resolved_intervals)
    )

    return MatrixResponse(
        cells=cells,
        generated_at=dt.datetime.now(dt.UTC),
        coverage=coverage,
        warnings=_warnings(cells),
    )


# ---------------------------------------------------------------------------
# Background sweep job
# ---------------------------------------------------------------------------


@router.post("/matrix/jobs", response_model=jobs.SweepAccepted, status_code=202)
def create_sweep(body: jobs.SweepCreateRequest) -> jobs.SweepAccepted:
    """Launch a full sweep as a background worker thread and return immediately.

    `symbols`/`sectors` empty means the whole research universe; `intervals` empty means all seven.
    Only one sweep may run at a time, process-wide -- a second call while one is already
    `queued`/`running` is `409`, naming the live `job_id`. This lock is **independent of**
    `app.tournament.jobs`' own one-round-at-a-time lock -- see `app.timeframes.jobs`'s module
    docstring for why sharing it would be a mistake; a research sweep here never contends with, and
    is never blocked by, a real tournament round.
    """
    try:
        return jobs.start_sweep(body)
    except jobs.SweepAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (jobs.UnknownSymbol, jobs.UnknownSector) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/matrix/jobs/{job_id}", response_model=jobs.SweepStatus)
def get_sweep(job_id: JobIdPath) -> jobs.SweepStatus:
    """One sweep's full state: progress counters, the current `(symbol, interval)` pair, the last
    200 log lines, every cell computed so far, and every pair that failed. `404` for an unknown
    `job_id`."""
    try:
        return jobs.get_sweep(job_id)
    except jobs.JobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/matrix/jobs/{job_id}", response_model=jobs.SweepStatus)
def cancel_sweep(job_id: JobIdPath) -> jobs.SweepStatus:
    """Ask a running sweep to stop, returning its state at the moment cancellation was requested.

    The worker notices between `(symbol, interval)` pairs rather than mid-pair, so this returns
    promptly while the sweep may still be finishing the pair in flight -- poll the `GET` route to see
    it reach `cancelled`. Cells already computed are kept: a cancelled sweep is a partial result, not
    a discarded one.

    `409` rather than `404` for a job that has already finished -- the caller asked for something
    that cannot happen to a completed sweep, which is a different problem from naming a job that
    never existed, and a UI wants to tell those two apart.
    """
    try:
        return jobs.request_cancel(job_id)
    except jobs.JobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except jobs.JobAlreadyFinished as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Signal trace (drill-down chart)
# ---------------------------------------------------------------------------


@router.get("/signal", response_model=SignalTrace)
def signal(symbol: SymbolParam, interval: Interval, rule_id: str) -> SignalTrace:
    """One `SignalTrace` for the drill-down chart: bars, indicator series and rising-edge fire
    markers for one `(symbol, interval, rule_id)`.

    `interval` is typed `Interval` directly (not a csv string), so FastAPI validates it against the
    enum before this function body ever runs -- an unknown value is a `422` from the framework itself,
    never a downstream lookup error.
    """
    try:
        # Annotated rather than returned straight through: `_service()` is a module, so this
        # call is `Any`, and returning it directly would assert the `-> SignalTrace` contract
        # without anything checking it.
        trace: SignalTrace = _service().signal_trace(
            symbol=symbol.upper(), interval=interval, rule_id=rule_id, settings=get_settings()
        )
        return trace
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
