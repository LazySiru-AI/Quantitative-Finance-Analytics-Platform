"""Report endpoints: the assembled per-holding report, its fact bundle, a strategy backtest, export.

Thin over :mod:`app.report.service`, in the shape :mod:`app.api.backtest` and :mod:`app.api.rules`
already use. Two things are specific to this router.

**Prose that failed verification never crosses this boundary.** The service drops it and attaches a
warning, so there is no path by which an ungrounded sentence reaches a client -- not even as a field
a careless caller might render. That is enforced one layer down, in
:func:`app.report.narrative.compose`, and this router adds nothing to it; it is noted here so nobody
adds a "raw draft" field for debugging convenience.

**Export is Markdown, not JSON.** A report someone wants to keep is a document, and the point of
exporting one is to read it somewhere else. Every figure in the exported prose has already been
substituted from the bundle, and the fact table travels with it so a reader offline can still check
where a number came from.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.backtest.models import Costs, DrawdownBasis, StrategyResult, StrategySpec
from app.config import get_settings
from app.db.duck import Interval
from app.market.providers.base import ProviderError, ProviderUnavailable, SymbolNotFound
from app.market.registry import ProviderRegistry, default_registry
from app.report import service
from app.report.models import FactBundle, Report
from app.report.narrative import format_fact

router = APIRouter(prefix="/api/report", tags=["report"])

SymbolParam = Annotated[str, Query(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.\-^=]+$")]

_MAX_EXPRESSION_LENGTH = 500


class StrategyRequest(BaseModel):
    """One entry/exit backtest.

    Bounds live here for the reason :mod:`app.api.backtest` gives: this endpoint's cost is set by
    caller-supplied rules, and the request model is where a refusal is cheapest.
    """

    symbol: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.\-^=]+$")
    interval: Interval = Interval.DAY
    entry: str = Field(min_length=1, max_length=_MAX_EXPRESSION_LENGTH)
    exit: str | None = Field(default=None, max_length=_MAX_EXPRESSION_LENGTH)
    max_holding_bars: int | None = Field(default=None, ge=1, le=2000)
    stop_loss_pct: float | None = Field(default=None, gt=0.0, lt=1.0)
    """Exclusive at both ends: a 0% stop closes on entry and a 100% stop can only fire if the
    instrument goes to zero, and neither is a stop anybody meant to set."""
    slippage_bps: float = Field(default=5.0, ge=0.0, le=500.0)
    commission_per_trade: float = Field(default=0.0, ge=0.0, le=1000.0)
    notional: float = Field(default=10_000.0, gt=0.0, le=1e9)
    """Only used to express a flat commission as a fraction of the equity curve -- see
    :attr:`app.backtest.models.Costs.notional`. ``gt=0`` because a zero notional makes the
    conversion a division by zero rather than a free trade.

    Deliberately duplicated on :class:`~app.backtest.models.Costs` itself, which carries the same
    ``gt=0`` constraint so the invariant holds for every caller of that model, not only this HTTP
    request. Kept here too rather than deleted as redundant: a request-schema violation surfaces as
    a 422 with a field-level message, which is a better failure for an HTTP caller than the generic
    validation error a model-level rejection alone would produce."""
    risk_free_rate: float = Field(default=0.0, ge=-0.5, le=0.5)


def _registry() -> ProviderRegistry:
    return default_registry()


def _handle(exc: ProviderError) -> HTTPException:
    if isinstance(exc, SymbolNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ProviderUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.get("", response_model=Report)
def report(
    symbol: SymbolParam,
    interval: Interval = Interval.DAY,
    basis: DrawdownBasis = DrawdownBasis.CLOSE,
    top: int = Query(default=10, ge=1, le=100),
) -> Report:
    """The whole report for one holding.

    An engine that fails contributes no facts and leaves a warning rather than failing the request:
    a report of three sections and a stated reason for the fourth is a useful document.
    """
    try:
        return service.build_report(
            get_settings(),
            symbol.upper(),
            interval,
            basis=basis,
            top_drawdowns=top,
            registry=_registry(),
        )
    except ProviderError as exc:
        raise _handle(exc) from exc


@router.get("/facts", response_model=FactBundle)
def facts(symbol: SymbolParam, interval: Interval = Interval.DAY) -> FactBundle:
    """Just the fact bundle -- every figure this report is allowed to state, with its provenance.

    Exposed on its own because it is the answer to "where did that number come from", and because a
    caller writing their own narrative needs to know the vocabulary before writing against it.
    """
    try:
        return service.build_report(
            get_settings(), symbol.upper(), interval, registry=_registry()
        ).bundle
    except ProviderError as exc:
        raise _handle(exc) from exc


@router.post("/strategy", response_model=StrategyResult)
def strategy(request: StrategyRequest) -> StrategyResult:
    """One entry/exit equity-curve backtest, guarded and recorded.

    A spec with neither an exit rule nor a holding cap is a 422: a position opened once would never
    close, which is buy-and-hold with extra steps rather than the strategy the caller described.
    """
    spec = StrategySpec(
        entry=request.entry,
        exit=request.exit,
        max_holding_bars=request.max_holding_bars,
        stop_loss_pct=request.stop_loss_pct,
    )
    if spec.exit is None and spec.max_holding_bars is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "a strategy needs an exit rule or a maximum holding period; with neither, a "
                "position opened once is never closed"
            ),
        )
    try:
        return service.build_strategy_result(
            get_settings(),
            request.symbol.upper(),
            request.interval,
            spec,
            costs=Costs(
                slippage_bps=request.slippage_bps,
                commission_per_trade=request.commission_per_trade,
                notional=request.notional,
            ),
            risk_free_rate=request.risk_free_rate,
            registry=_registry(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderError as exc:
        raise _handle(exc) from exc


@router.get("/export", response_class=PlainTextResponse)
def export(
    symbol: SymbolParam,
    interval: Interval = Interval.DAY,
    basis: DrawdownBasis = DrawdownBasis.CLOSE,
) -> PlainTextResponse:
    """The report as Markdown, with its fact table attached.

    The fact table is not an appendix nobody reads -- it is what makes the exported document
    checkable once it is away from this app. A number in the prose can be traced to a source string
    naming the engine and the window it came from, offline, months later.
    """
    try:
        built = service.build_report(
            get_settings(), symbol.upper(), interval, basis=basis, registry=_registry()
        )
    except ProviderError as exc:
        raise _handle(exc) from exc

    lines: list[str] = [
        f"# {built.symbol} — research report",
        "",
        f"*Generated {built.generated_at:%Y-%m-%d %H:%M UTC} · {built.interval.value} bars*",
        "",
        f"> {built.disclaimer}",
        "",
    ]

    for section in built.sections:
        lines += [f"## {section.title}", ""]
        if section.narrative is not None:
            lines += [section.narrative.text, ""]
        for warning in section.warnings:
            lines += [f"*{warning.message}*", ""]

    if built.warnings:
        lines += ["## Caveats", ""]
        lines += [f"- {w.message}" for w in built.warnings]
        lines += [""]

    lines += [
        "## Figures",
        "",
        "Every number above comes from this table. Each row names the engine and the window that",
        "produced it.",
        "",
        "| Figure | Value | Source |",
        "| --- | --- | --- |",
    ]
    for fact in sorted(built.bundle.facts.values(), key=lambda f: f.id):
        value = format_fact(fact).replace("|", "\\|")
        lines.append(f"| {fact.label} | {value} | `{fact.source}` |")
    lines.append("")

    filename = f"{built.symbol}-{built.interval.value}-report.md"
    return PlainTextResponse(
        "\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
