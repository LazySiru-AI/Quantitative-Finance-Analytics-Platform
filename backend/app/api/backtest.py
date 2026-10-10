"""Backtest workbench endpoints: drawdowns, event studies, reverse conditioning, guarded scans.

Thin over :mod:`app.backtest.service`, in the same shape as :mod:`app.api.rules` is thin over
:mod:`app.rules.service`: a failed guard, an unevaluable condition and a symbol with nothing synced
are all absorbed one layer down and arrive here as ordinary results. The single error condition left
at this boundary is the one every market-facing router already handles -- a confirmed-missing symbol
or every provider down with nothing stored, raised by
:func:`app.market.store.ensure_series` as a :class:`~app.market.providers.base.ProviderError`.

**Input bounds are the one thing this layer owns outright**, and they matter more here than on
``/api/rules/decisions``. That endpoint's cost is fixed by the catalog; these take a caller-supplied
list and multiply it. A scan is ``len(expressions) * len(horizons)`` evaluations, each of which
guards an expression by recomputing its indicators on eight leading slices -- so an unbounded request
is not merely slow, it is a denial of service against a single-user local app, mounted through its
own UI. Every list length, every string length and every numeric range is therefore constrained on
the request model, where FastAPI rejects it with a 422 before a handler runs and before a single bar
is read.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.backtest import service
from app.backtest.models import (
    STUDY_HORIZONS,
    DrawdownBasis,
    DrawdownProfile,
    EventStudy,
    ReverseConditioning,
    RunCard,
    ScanResult,
)
from app.config import get_settings
from app.db.duck import Interval
from app.market.providers.base import ProviderError, ProviderUnavailable, SymbolNotFound
from app.market.registry import ProviderRegistry, default_registry
from app.rules.models import Entry

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

#: Same closed alphabet as `app.api.rules.SymbolParam`, duplicated for the reason that module gives:
#: a symbol reaches the filesystem as a Parquet partition directory name one layer down.
SymbolParam = Annotated[str, Query(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.\-^=]+$")]

_MAX_EXPRESSION_LENGTH = 500
#: Two arms is the A/B comparison the plan describes ("band touch" vs "band touch + RSI < 30"); four
#: leaves room to walk a condition in stages without turning the study into a scan by the back door.
#: Testing many conditions at once is what `/scan` is for, and it is the endpoint that carries the
#: trial counter and the correction -- an event study with twenty arms would be an uncorrected scan
#: wearing a friendlier name.
_MAX_CONDITIONS = 4
#: A scan's real ceiling. At five horizons this is 250 guarded evaluations, which is a long request
#: but a finite one. The number exists so there is *a* number, not because 50 is meaningful.
_MAX_EXPRESSIONS = 50
_MAX_HORIZONS = 8
#: Beyond this a "forward return" spans years and the window falls off the end of most histories.
_MAX_HORIZON_BARS = 500


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class _SymbolBody(BaseModel):
    """Shared symbol/interval fields. The pattern matches `SymbolParam` so a POST body cannot smuggle
    a path separator into a partition name that a query parameter would have been refused."""

    symbol: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.\-^=]+$")
    interval: Interval = Interval.DAY


class EventStudyRequest(_SymbolBody):
    conditions: list[str] = Field(min_length=1, max_length=_MAX_CONDITIONS)
    """Arm 0 is the base every delta is measured against."""
    horizons: list[int] = Field(
        default_factory=lambda: list(STUDY_HORIZONS), min_length=1, max_length=_MAX_HORIZONS
    )
    entry: Entry = Entry.NEXT_OPEN


class ReverseRequest(_SymbolBody):
    horizon: int = Field(default=20, ge=1, le=_MAX_HORIZON_BARS)
    quantile: float = Field(default=0.9, gt=0.0, lt=1.0)
    """Exclusive at both ends. ``1.0`` selects nothing and ``0.0`` selects everything, and both would
    render as a profile of a sample that answers no question."""
    lookback: int = Field(default=0, ge=0, le=60)
    indicators: list[str] = Field(default_factory=list, max_length=20)
    entry: Entry = Entry.NEXT_OPEN


class ScanRequest(_SymbolBody):
    expressions: list[str] = Field(min_length=1, max_length=_MAX_EXPRESSIONS)
    """Every expression here is a trial, whether or not it survives."""
    horizons: list[int] = Field(
        default_factory=lambda: list(STUDY_HORIZONS), min_length=1, max_length=_MAX_HORIZONS
    )
    entry: Entry = Entry.NEXT_OPEN
    alpha: float = Field(default=0.10, gt=0.0, lt=1.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _registry() -> ProviderRegistry:
    """One registry per request -- see `app.api.market._registry`."""
    return default_registry()


def _handle(exc: ProviderError) -> HTTPException:
    """The same status mapping as `app.api.market._handle`, `app.api.macro._handle` and
    `app.api.rules._handle`, duplicated for the reason those give."""
    if isinstance(exc, SymbolNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ProviderUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _check_expressions(values: list[str], *, field: str) -> None:
    """Length-bound each expression. Enforced here rather than by a `Field` constraint on the item
    type so the message names the offending index -- an editor showing "string too long" against a
    list of forty is not actionable."""
    for i, value in enumerate(values):
        if len(value) > _MAX_EXPRESSION_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{field}[{i}] is {len(value)} characters; the limit is "
                    f"{_MAX_EXPRESSION_LENGTH}"
                ),
            )


def _check_horizons(values: list[int]) -> None:
    for i, value in enumerate(values):
        if value < 1 or value > _MAX_HORIZON_BARS:
            raise HTTPException(
                status_code=422,
                detail=f"horizons[{i}] is {value}; must be between 1 and {_MAX_HORIZON_BARS} bars",
            )


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------


@router.get("/drawdowns", response_model=DrawdownProfile)
def drawdowns(
    symbol: SymbolParam,
    interval: Interval = Interval.DAY,
    basis: DrawdownBasis = DrawdownBasis.CLOSE,
    top: int = Query(default=10, ge=1, le=100),
) -> DrawdownProfile:
    """Every material drawdown for one instrument, deepest first.

    ``basis`` comes back on the response as well as going in, because a depth without its basis is
    not a number anyone can read -- see :class:`~app.backtest.models.DrawdownBasis`.
    """
    try:
        return service.build_drawdown_profile(
            get_settings(),
            symbol.upper(),
            interval,
            basis=basis,
            top=top,
            registry=_registry(),
        )
    except ProviderError as exc:
        raise _handle(exc) from exc


# ---------------------------------------------------------------------------
# Event study
# ---------------------------------------------------------------------------


@router.post("/event-study", response_model=EventStudy)
def event_study(request: EventStudyRequest) -> EventStudy:
    """One or more conditions measured forward against a shared baseline.

    A condition whose lookahead guard does not pass comes back as an arm carrying its
    :class:`~app.backtest.models.GuardReport` and **no statistics** -- a 200 with a visible refusal,
    not a 4xx, because "this condition could not be verified" is an answer to the question asked.
    """
    _check_expressions(request.conditions, field="conditions")
    _check_horizons(request.horizons)
    try:
        return service.build_event_study(
            get_settings(),
            request.symbol.upper(),
            request.interval,
            request.conditions,
            horizons=request.horizons,
            entry=request.entry,
            registry=_registry(),
        )
    except ProviderError as exc:
        raise _handle(exc) from exc


# ---------------------------------------------------------------------------
# Reverse conditioning
# ---------------------------------------------------------------------------


@router.post("/reverse", response_model=ReverseConditioning)
def reverse(request: ReverseRequest) -> ReverseConditioning:
    """What the indicators were doing before the biggest moves. **Exploratory output.**

    Carries no hit rate, p-value or q-value, and the response's ``exploratory`` flag is always
    ``True`` -- see :class:`~app.backtest.models.ReverseConditioning` for why a candidate read off
    this table is not a finding until it has been tested as a declared trial.
    """
    _check_expressions(request.indicators, field="indicators")
    try:
        return service.build_reverse_conditioning(
            get_settings(),
            request.symbol.upper(),
            request.interval,
            horizon=request.horizon,
            quantile=request.quantile,
            lookback=request.lookback,
            indicators=request.indicators,
            entry=request.entry,
            registry=_registry(),
        )
    except ProviderError as exc:
        raise _handle(exc) from exc


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


@router.post("/scan", response_model=ScanResult)
def scan(request: ScanRequest) -> ScanResult:
    """Every expression against every horizon, Benjamini-Hochberg corrected across the whole set.

    ``trials`` always equals ``len(entries)``; the model refuses to construct otherwise. Entries that
    could not be evaluated still appear and still consume their trial, because removing them would
    shrink the denominator every surviving q-value depends on.
    """
    _check_expressions(request.expressions, field="expressions")
    _check_horizons(request.horizons)
    try:
        return service.build_scan(
            get_settings(),
            request.symbol.upper(),
            request.interval,
            request.expressions,
            horizons=request.horizons,
            entry=request.entry,
            alpha=request.alpha,
            registry=_registry(),
        )
    except ProviderError as exc:
        raise _handle(exc) from exc


# ---------------------------------------------------------------------------
# Run cards
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}", response_model=RunCard)
def run_card(run_id: Annotated[str, Path(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9]+$")]) -> RunCard:
    """One stored run card. The alphabet is constrained because ``run_id`` becomes a filename."""
    from app.backtest import runcard as runcard_module

    try:
        return runcard_module.read(run_id, settings=get_settings())
    except runcard_module.RunCardNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except runcard_module.RunCardCorrupt as exc:
        # 500, not 404: the file exists and this is the server's own audit trail being unreadable.
        # Reporting it as "not found" would hide a real integrity problem behind a routine status.
        raise HTTPException(status_code=500, detail=str(exc)) from exc
