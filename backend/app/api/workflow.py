"""HTTP surface for the Agent Workflow desk -- the orchestrator that chains the other two and then
trades.

Thin, like the other two desk routers: every real decision lives in `app.workflow.service` (run
lifecycle), `app.workflow.book` (the paper ledger) and `app.workflow.study` (the effectiveness
report). This router wires routes and translates those modules' domain exceptions into the status
codes `docs/AGENT-DESK-CONTRACT.md` pins.
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict

from app.agentdesk.jobs import RunAlreadyActive
from app.agentdesk.models import RUN_ID_MAX_LENGTH, RUN_ID_PATTERN, DeskRun
from app.agents.models import AgentUnavailable
from app.config import Settings, get_settings
from app.market import store as market_store
from app.market.models import Interval
from app.paper.mandate import default_mandate
from app.paper.marketdata import AsOfMarket
from app.paper.paperbroker import PaperBroker
from app.workflow import book as book_mod
from app.workflow import candidates as candidates_mod
from app.workflow import service, study, telemetry
from app.workflow.book_models import BookState, WorkflowArm
from app.workflow.pipeline import ALL_ARMS, SCREENED_ARMS, STARTING_CASH
from app.workflow.schemas import DeskRunSummary, WorkflowRunRequest

router = APIRouter(prefix="/api/workflow", tags=["workflow"])

logger = logging.getLogger(__name__)

#: Same shape, and the same shared pattern, as `app.api.vibedesk.RunIdPath` -- see that constant for
#: why an id may not contain a separator or a dot segment.
RunIdPath = Annotated[
    str, Path(min_length=1, max_length=RUN_ID_MAX_LENGTH, pattern=RUN_ID_PATTERN)
]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class RunsListResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    runs: list[DeskRunSummary]


class BookListResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    books: list[dict[str, Any]]


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: dt.date | None = None
    arms: list[str] | None = None
    universe_source: Literal["card", "screen"] = "card"


class CandidatesResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    universe_source: Literal["card", "screen"] | None
    total: int
    observations: list[dict[str, Any]]
    skip_reasons: dict[str, int]
    verdict_sources: dict[str, int]
    avoided_cost_usd: str


@router.get("/config")
def get_config(settings: SettingsDep) -> dict[str, Any]:
    return service.config_payload(settings)


@router.post("/runs", status_code=202, response_model=DeskRun)
def start_run(body: WorkflowRunRequest, settings: SettingsDep) -> DeskRun:
    try:
        return service.start_workflow_run(body, settings=settings)
    except service.InvalidRequest as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AgentUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RunAlreadyActive as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs", response_model=RunsListResponse)
def list_runs(settings: SettingsDep, limit: Annotated[int, Query(ge=1, le=200)] = 25) -> RunsListResponse:
    return RunsListResponse(runs=list(service.list_runs(settings=settings, limit=limit)))


@router.get("/runs/{run_id}", response_model=DeskRun)
def get_run(run_id: RunIdPath, settings: SettingsDep) -> DeskRun:
    run = service.get_run(run_id, settings=settings)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no workflow run {run_id!r}")
    return run


@router.get("/runs/{run_id}/telemetry")
def get_run_telemetry(run_id: RunIdPath, settings: SettingsDep) -> dict[str, Any]:
    """Token and cost telemetry for one workflow run -- its own stages plus every TA/Vibe child it
    launched. Additive: `docs/AGENT-DESK-CONTRACT.md`'s error-status table already pins `404` for an
    unknown run id, and this route follows the same `service.get_run` lookup `get_run` above uses,
    not a second run-existence check invented for this route alone."""
    run = service.get_run(run_id, settings=settings)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no workflow run {run_id!r}")
    return telemetry.build_workflow_telemetry(run, settings=settings).model_dump(mode="json")


@router.delete("/runs/{run_id}", response_model=DeskRun)
def cancel_run(run_id: RunIdPath, settings: SettingsDep) -> DeskRun:
    try:
        return service.cancel_run(run_id, settings=settings)
    except service.RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _validate_arms(
    arms: list[str] | None, *, universe_source: Literal["card", "screen"] = "card"
) -> tuple[WorkflowArm, ...]:
    """`"card"` (default) is exactly today's behaviour, validated against `ALL_ARMS`. `"screen"`
    validates against `SCREENED_ARMS` instead -- the only arms a screen run may enable -- and defaults
    to `SCREENED_ARMS` (not `ALL_ARMS`) when the caller omits `arms` entirely."""
    if universe_source == "screen":
        if arms is None:
            return SCREENED_ARMS
        unknown = sorted(set(arms) - set(SCREENED_ARMS))
        if unknown:
            raise HTTPException(
                status_code=422, detail=f"unknown/ineligible arm(s): {', '.join(unknown)}"
            )
        return tuple(a for a in SCREENED_ARMS if a in arms)

    if arms is None:
        return ALL_ARMS
    unknown = sorted(set(arms) - set(ALL_ARMS))
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown arm(s): {', '.join(unknown)}")
    return tuple(a for a in ALL_ARMS if a in arms)


def _newest_session(settings: Settings) -> dt.date:
    frame = market_store.read_frame("SPY", Interval.DAY, settings=settings)
    if frame is not None and not frame.empty:
        return cast("dt.date", frame["ts"].dt.date.iloc[-1])
    return dt.date.today()


def _positions_view(book: BookState, snapshot_positions: Any) -> list[dict[str, Any]]:
    """The broker snapshot's positions in the contract's `WorkflowBookPosition` shape.

    `PaperBroker.snapshot` emits `{symbol, quantity, mark, market_value, weight_pct_of_1}` -- the
    persona-facing shape -- but `docs/AGENT-DESK-CONTRACT.md` pins `{symbol, qty, avg_cost,
    market_value}` for this page. Passing the snapshot through unmapped left `avg_cost` undefined on
    the wire, which the page's money formatter threw on the first time any workflow book actually
    held a position (the Round 33 screen book). `qty`/`market_value` stay the broker's own numbers;
    `avg_cost` is the whole-lot basis over quantity from `book.held_lots` (FIFO, from the fill
    history), so the page's cost column and the tax check read the same lots.
    """
    basis: dict[str, Decimal] = {}
    held_qty: dict[str, Decimal] = {}
    for lot in book_mod.held_lots(book):
        basis[lot.symbol] = basis.get(lot.symbol, Decimal(0)) + lot.cost_basis
        held_qty[lot.symbol] = held_qty.get(lot.symbol, Decimal(0)) + lot.quantity
    rows: list[dict[str, Any]] = []
    for raw in snapshot_positions or ():
        if not isinstance(raw, dict) or not raw.get("symbol"):
            continue
        symbol = str(raw["symbol"])
        lot_qty = held_qty.get(symbol, Decimal(0))
        avg_cost = basis[symbol] / lot_qty if lot_qty > 0 and symbol in basis else Decimal(0)
        rows.append({
            "symbol": symbol,
            "qty": str(raw.get("quantity") if raw.get("quantity") is not None else format(lot_qty, "f")),
            "avg_cost": format(avg_cost.quantize(Decimal("0.01")), "f"),
            "market_value": raw.get("market_value"),
        })
    return rows


def _book_view(book: BookState, *, settings: Settings, mandate: Any, as_of: dt.date) -> dict[str, Any]:
    """One arm's book in the wire `WorkflowBook` shape.

    Reconstructs the broker from the persisted `broker_state` and asks it for the same snapshot the
    persona is shown -- cash, positions, equity -- rather than re-deriving any of it here, so the
    numbers on this page are the broker's own, not a second computation that could disagree with the
    fills that produced them. `tax_summary` degrades to `None` on its own; a book with no positions
    priceable at `as_of` still renders, with `equity` null.
    """
    broker = PaperBroker.from_state(mandate, book.broker_state)
    market = AsOfMarket(as_of=as_of, settings=settings)
    try:
        snap = broker.snapshot(market)
    except Exception:
        snap = {"cash": format(broker.settled_cash(as_of), "f"), "equity": None, "positions": []}
    tax = book_mod.tax_summary(book, settings=settings)
    return {
        "arm": book.arm,
        "universe_source": book.universe_source,
        "current_card_id": book.current_card_id,
        "card_adopted_date": book.card_adopted_date.isoformat(),
        "starting_cash": format(book.starting_cash, "f"),
        "cash": snap.get("cash"),
        "equity": snap.get("equity"),
        "positions": _positions_view(book, snap.get("positions", [])),
        "orders": [o.model_dump(mode="json") for o in book.orders],
        "equity_curve": [p.model_dump(mode="json") for p in book.equity_curve],
        "tax": tax.model_dump(mode="json") if tax is not None else None,
        "as_of": as_of.isoformat(),
    }


@router.get("/book", response_model=BookListResponse)
def get_book(
    settings: SettingsDep,
    universe_source: Literal["card", "screen"] | None = None,
) -> BookListResponse:
    """Every arm's book, whatever exists on disk. A card-mode book that has never been written back is
    seeded empty so the page can render all four arms side by side from run one; a screen-mode book
    never is (see below).

    `universe_source`, default `None` (omitted), selects which universe's books render:
    - omitted -- today's exact behaviour, unchanged: all four card-mode books (seeded empty if
      absent) plus any screen-mode books that happen to exist on disk.
    - `"card"` -- only the four card-mode books.
    - `"screen"` -- only screen-mode books that exist on disk. Never seeds one just by asking, the
      same rule the omitted/default path already follows for screen-mode books.
    """
    # Code-defined mandate, not read from uat/personas -- served code must not depend on a
    # tree the container does not ship (tests/test_deployment_paths.py). Same default the paper desk
    # uses (app.paper.mandate.default_mandate), so a workflow book's fills obey the same rules.
    mandate = default_mandate(starting_cash=STARTING_CASH)
    as_of = _newest_session(settings)
    books: list[dict[str, Any]] = []
    # The four card-mode books always render (seeded empty from run one) unless the caller asked for
    # screen-only.
    if universe_source in (None, "card"):
        books.extend(
            _book_view(
                book_mod.load_book(settings, arm, starting_cash=STARTING_CASH, card_id=""),
                settings=settings, mandate=mandate, as_of=as_of,
            )
            for arm in ALL_ARMS
        )
    # Screen-mode books (data/agentdesk/workflow/book/screen/<arm>.json) are added only when they
    # exist on disk, so a deployment that has never run a dynamic-universe (screen) study shows
    # exactly today's four books, unchanged -- no empty screen rows are seeded just by opening the page.
    if universe_source in (None, "screen"):
        for arm in ALL_ARMS:
            if book_mod.book_path(settings, arm, universe_source="screen").is_file():
                books.append(
                    _book_view(
                        book_mod.load_book(
                            settings, arm, starting_cash=STARTING_CASH, card_id="",
                            universe_source="screen",
                        ),
                        settings=settings, mandate=mandate, as_of=as_of,
                    )
                )
    return BookListResponse(books=books)


@router.post("/book/execute")
def execute_book(body: ExecuteRequest, settings: SettingsDep) -> dict[str, Any]:
    """Fill every arm's pending orders whose fill date has arrived. A run currently staging orders
    holds the workflow registry slot; refuse to fill mid-write.

    `body.universe_source`, default `"card"`, selects which universe's books this call touches:
    `"card"` is exactly today's behaviour (default arms = `ALL_ARMS`, validated against `ALL_ARMS`).
    `"screen"` defaults `arms` to `SCREENED_ARMS` and validates any explicit list against that same
    tuple -- an arm outside it is a 422, since a screen run may only enable `raw_signal`/
    `full_workflow`. A screen book that does not exist on disk yet is skipped, never seeded and never
    filled, the same "screen books are opt-in, never conjured" rule `get_book` follows.
    """
    from app.agentdesk.jobs import registry

    if registry().active("workflow") is not None:
        raise HTTPException(status_code=409, detail="a workflow run is staging orders; try again once it finishes")

    arms = _validate_arms(body.arms, universe_source=body.universe_source)
    # Code-defined mandate, not read from uat/personas -- served code must not depend on a
    # tree the container does not ship (tests/test_deployment_paths.py). Same default the paper desk
    # uses (app.paper.mandate.default_mandate), so a workflow book's fills obey the same rules.
    mandate = default_mandate(starting_cash=STARTING_CASH)
    as_of = body.as_of or _newest_session(settings)
    filled = rejected = still_pending = 0
    stored_open = live_quote = 0
    for arm in arms:
        if body.universe_source == "screen" and not book_mod.book_path(
            settings, arm, universe_source="screen"
        ).is_file():
            continue  # never seed a screen book just by executing against it
        book = book_mod.load_book(
            settings, arm, starting_cash=STARTING_CASH, card_id="", universe_source=body.universe_source
        )
        book, outcome = book_mod.execute_pending(
            book, settings=settings, mandate=mandate, today=body.as_of
        )
        try:
            book = book_mod.mark_equity_through(
                book, settings=settings, mandate=mandate, through=as_of
            )
        except Exception:
            logger.warning(
                "workflow book %s/%s: equity marking failed after execute; saving fills without it",
                arm, body.universe_source, exc_info=True,
            )
        book_mod.save_book(settings, book)
        filled += outcome.filled
        rejected += outcome.rejected
        still_pending += outcome.still_pending
        stored_open += outcome.stored_open_fills
        live_quote += outcome.live_quote_fills
    return {
        "as_of": as_of.isoformat(),
        "filled": filled,
        "rejected": rejected,
        "still_pending": still_pending,
        "price_source_mix": {"stored_open": stored_open, "live_quote": live_quote},
        "universe_source": body.universe_source,
    }


@router.get("/study")
def get_study(
    settings: SettingsDep,
    universe_source: Literal["card", "screen"] = "card",
) -> dict[str, Any]:
    """`universe_source`, default `"card"`, is byte-for-byte today's call when omitted or `"card"`.
    `"screen"` scores only `SCREENED_ARMS` against the screen-mode books and candidate log -- the
    only arms a screen run may enable."""
    if universe_source == "screen":
        return study.build_study(
            settings=settings, arms=SCREENED_ARMS, universe_source="screen"
        ).model_dump(mode="json")
    return study.build_study(settings=settings).model_dump(mode="json")


@router.get("/candidates", response_model=CandidatesResponse)
def get_candidates(
    settings: SettingsDep,
    universe_source: Literal["card", "screen"] | None = None,
    state: Literal["pending", "resolved"] | None = None,
    symbol: str | None = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> CandidatesResponse:
    """The candidate-observation log (`app.workflow.candidates`), filtered and paged for the page.

    `total`, `skip_reasons`, `verdict_sources` and `avoided_cost_usd` are all computed over *every*
    row matching the filters, before `limit` truncates `observations` -- so a caller paging through a
    long log still sees the true totals on every page, not just the page it asked for.
    """
    rows = candidates_mod.read_observations(
        settings=settings, symbol=symbol, state=state, universe_source=universe_source
    )
    total = len(rows)

    skip_reasons: dict[str, int] = {}
    verdict_sources: dict[str, int] = {"fresh": 0, "cached": 0, "mixed": 0}
    avoided_cost_usd = Decimal("0")
    for row in rows:
        if row.skip_reason is not None:
            skip_reasons[row.skip_reason] = skip_reasons.get(row.skip_reason, 0) + 1
        for decision in row.gates:
            verdict_sources[decision.verdict_source] += 1
        avoided_cost_usd += row.avoided_cost_usd

    # Newest decision_date first, tie-broken by symbol ascending.
    ordered = sorted(rows, key=lambda row: (-row.decision_date.toordinal(), row.symbol))

    return CandidatesResponse(
        universe_source=universe_source,
        total=total,
        observations=[row.model_dump(mode="json") for row in ordered[:limit]],
        skip_reasons=skip_reasons,
        verdict_sources=verdict_sources,
        avoided_cost_usd=format(avoided_cost_usd, "f"),
    )
