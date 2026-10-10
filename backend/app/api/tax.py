"""Tax endpoints: the report, the Form 8949 export, and the 1099-B reconciliation.

Every response is derived state. Nothing here is cached or stored: the ledger is replayed, wash
sales are applied and gains are classified on each request, because derived data in this project is
rebuilt rather than mutated. The alternative -- a cache that can silently go stale against a
re-import -- is how a tax page ends up showing figures that no longer match the ledger underneath
it.

**Measured, 2026-08-14:** the full replay of a real ledger of roughly a thousand transactions takes **~290ms**, of
which wash-sale matching is ~234ms and lot construction ~26ms. This paragraph claimed
"milliseconds" until it was timed; that was an estimate that had never been checked, and the
correction is recorded rather than quietly applied because the number is the whole basis for
choosing recomputation over a cache. It does not change the choice at this size. It does mean the
cost is dominated by the one stage that grows with the square of disposals in an instrument, so a
ledger several times this size is worth re-timing before assuming the decision still holds.

**These endpoints return a calculation, not tax advice.** The figures must be reconciled against the
user's 1099-B forms before they inform a filing.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse

from app.config import get_settings
from app.datasource import ledger_db_path
from app.db import sqlite
from app.ingest.manifest import load_declarations
from app.tax import engine
from app.tax.export import disposals_to_csv, wash_sales_to_csv
from app.tax.form8949 import to_csv
from app.tax.models import ReconcileReport, TaxReport, WashSaleExposureReport
from app.tax.reconcile import Form1099BParseError, parse_1099b_csv, reconcile
from app.tax.washsale_summary import build_wash_sale_exposure_report, build_wash_sale_summary

router = APIRouter(prefix="/api/tax", tags=["tax"])

#: Bounds on the requested year. Wide enough for any real holding period, narrow enough that a
#: malformed query cannot ask the engine to build 10,000 empty reports.
YearParam = Annotated[int, Query(ge=1990, le=2100)]

#: Bounds on an optional page size. 1 to 1000: wide enough for any page a UI would reasonably choose
#: (the Tax page's own default is 100 -- see `frontend/src/pages/Tax.tsx`), narrow enough that a
#: malformed request cannot ask either endpoint below to serialise its entire list by accident when
#: the caller's whole point was to avoid that. `None` -- the default on both endpoints that take it
#: -- means "every row", matching their behaviour before paging existed.
LimitParam = Annotated[int, Query(ge=1, le=1000)]
OffsetParam = Annotated[int, Query(ge=0)]


def _paginate_report(result: TaxReport, *, limit: int | None, offset: int) -> TaxReport:
    """Slice `gains.rows` and `wash_sales` to one page each, at the same `offset`, leaving every
    other field on `result` -- every aggregate, `form8949`, `warnings`, `wash_sale_summary`, all of
    them computed over the whole year -- untouched.

    One `offset` governs both lists rather than one per list: the Tax page never needs a page of
    Disposals and a different page of Wash sales in the same request, since only one of those two
    tabs is ever the active one. `limit=None`, the default, returns each list in full -- identical to
    this endpoint's behaviour before paging existed -- while still populating the `*_total` metadata,
    so a client can read the true count off *any* response without special-casing "did I ask to
    paginate this."

    An `offset` past the end of a list is not an error, matching `app.api.transactions`: it returns
    an empty slice with the corresponding `*_has_more` false, the same shape a client sees paging
    cleanly off the end of a shorter list.
    """
    disposals_total = len(result.gains.rows)
    wash_events_total = len(result.wash_sales)

    if limit is None:
        rows = result.gains.rows[offset:]
        wash_sales = result.wash_sales[offset:]
    else:
        rows = result.gains.rows[offset : offset + limit]
        wash_sales = result.wash_sales[offset : offset + limit]

    gains = result.gains.model_copy(update={"rows": rows})
    return result.model_copy(
        update={
            "gains": gains,
            "wash_sales": wash_sales,
            "disposals_total": disposals_total,
            "wash_events_total": wash_events_total,
            "limit": limit,
            "offset": offset,
            "disposals_has_more": offset + len(rows) < disposals_total,
            "wash_events_has_more": offset + len(wash_sales) < wash_events_total,
        }
    )


def _build(year: int) -> TaxReport:
    """Replay the ledger and build the report, or 404 when there is no ledger yet.

    A missing ledger file is a genuinely different condition from a year with no disposals, and the
    Tax page renders them differently -- "import something" versus "nothing was sold in 2025".
    """
    settings = get_settings()
    ledger_file = ledger_db_path(settings)
    if not ledger_file.exists():
        raise HTTPException(status_code=404, detail="no ledger yet; import broker exports first")

    # `opening` is not optional garnish: without it a sale of shares older than the export is
    # booked at zero basis, and this page would report a different realised gain from the one the
    # Portfolio page derives off the same ledger. See `load_declarations`.
    manifest = load_declarations(settings)
    with sqlite.connect(ledger_file, read_only=True) as conn:
        return engine.report_from_ledger(
            conn,
            tax_year=year,
            opening=manifest.opening_positions if manifest else (),
            transfer_basis=manifest.transfer_bases if manifest else (),
        )


@router.get("/report")
def report(
    year: YearParam | None = None,
    limit: LimitParam | None = None,
    offset: OffsetParam = 0,
) -> TaxReport:
    """The whole tax picture for one year: gains, wash sales, Form 8949, unsettled pairs, warnings.

    `limit`/`offset` page exactly two fields on the response -- `gains.rows` (the Disposals table)
    and `wash_sales` (the per-event Wash sales table) -- since those are the two whose length scales
    with disposal count and the reason this response could otherwise carry several thousand rows for
    a busy year. See `_paginate_report` for exactly what does and does not get sliced.
    """
    result = _build(year if year is not None else engine.default_tax_year())
    return _paginate_report(result, limit=limit, offset=offset)


@router.get("/form8949.csv", response_class=PlainTextResponse)
def form8949_csv(year: YearParam | None = None) -> PlainTextResponse:
    """Form 8949 rows as CSV, for pasting into tax software."""
    resolved = year if year is not None else engine.default_tax_year()
    csv_text = to_csv(_build(resolved).form8949)
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="form8949-{resolved}.csv"'},
    )


#: Media type for every CSV this module hands to a browser. The charset is stated explicitly
#: because the reconciliation exports below are encoded with a BOM (see `_csv_download`) and a
#: response that carries a BOM while declaring nothing is a file Excel and a text editor disagree
#: about.
_CSV_MEDIA_TYPE = "text/csv; charset=utf-8"


def _csv_download(csv_text: str, filename: str) -> Response:
    """One CSV download response: UTF-8 **with a BOM**, named, and marked as an attachment.

    The BOM (``utf-8-sig``) is here for Excel and nothing else. Excel on Windows still opens a
    BOM-less CSV in the system ANSI codepage, which mangles every non-ASCII character in an account
    label the moment one exists -- and this pack is built to be opened in Excel by a CPA, not
    parsed by a program. `PlainTextResponse` cannot express this (it encodes plain UTF-8), so the
    body is encoded here and handed to `Response` as bytes.

    Note the older `/form8949.csv` route deliberately keeps its BOM-less `PlainTextResponse`: its
    output is documented as something a user *pastes* into tax software, where a leading BOM would
    ride along into the first cell. Same project, two different destinations, two encodings.
    """
    return Response(
        content=csv_text.encode("utf-8-sig"),
        media_type=_CSV_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/disposals.csv", response_class=Response)
def export_disposals_csv(year: YearParam | None = None) -> Response:
    """The Disposals table for one year, as CSV -- the per-lot detail behind each Form 8949 line.

    Built from the same `GainsReport` `/report` serialises, and **not paginated**: `limit`/`offset`
    exist so a *page* does not carry several thousand rows to a browser that renders a hundred of
    them. A reconciliation export whose whole purpose is to be totalled against a 1099-B must carry
    the year, so it does.
    """
    resolved = year if year is not None else engine.default_tax_year()
    return _csv_download(disposals_to_csv(_build(resolved).gains), f"disposals-{resolved}.csv")


@router.get("/export/washsales.csv", response_class=Response)
def export_wash_sales_csv(year: YearParam | None = None) -> Response:
    """Triggered wash-sale events for one year, as CSV.

    Year-scoped by sale date, matching `TaxReport.wash_sales` and the Tax page's Wash sales table
    -- **not** the whole-ledger `/wash-sales` tracker, which deliberately takes no year at all (see
    that route's docstring). The two answer different questions and this one is the reconciliation
    half: what §1091 did to *this year's* reported gain. Also unpaginated, for the reason above.
    """
    resolved = year if year is not None else engine.default_tax_year()
    return _csv_download(
        wash_sales_to_csv(_build(resolved).wash_sales), f"washsales-{resolved}.csv"
    )


@router.post("/reconcile")
def reconcile_1099b(
    csv_text: Annotated[str, Body(media_type="text/plain", max_length=2_000_000)],
    year: YearParam | None = None,
) -> ReconcileReport:
    """Diff the computed gains against a 1099-B transcribed to CSV.

    The body is the CSV itself. A parse failure is a 400 with the offending row named rather than a
    500 -- the user is hand-transcribing a broker form, and "row 12: unrecognised term 'LT '" is
    actionable in a way that a stack trace is not.

    Capped at 2MB -- thousands of 1099-B rows' worth of hand-transcribed CSV, and enough headroom
    over any real form this application's users file against, while still bounding what an
    unauthenticated or malicious caller can make this endpoint parse in one request.
    """
    resolved = year if year is not None else engine.default_tax_year()
    try:
        form_lines = parse_1099b_csv(csv_text)
    except Form1099BParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return reconcile(_build(resolved).gains, form_lines)


@router.get("/wash-sales")
def wash_sales(
    limit: LimitParam | None = None,
    offset: OffsetParam = 0,
) -> WashSaleExposureReport:
    """Whole-ledger wash-sale exposure, per symbol, with drill-down to the individual loss sales.

    `limit`/`offset` page `symbols`, the one list on this response whose length scales with how many
    tickers have ever carried a loss sale. `symbol_count` stays the full, unsliced count regardless
    of paging -- see its own docstring in `app.tax.models.WashSaleExposureReport` -- so an existing
    caller reading it for a total (the "N symbols tracked" tile, the Overview page's badge) is
    unaffected by this endpoint gaining the ability to page; neither passes `limit` today.

    Deliberately takes **no year parameter**. `_build`'s `TaxReport.wash_sale_summary` is already
    whole-ledger scoped regardless of which `year` is passed to it -- see the scope comment above
    `wash_sale_summary = build_wash_sale_summary(...)` in `app.tax.engine.build_tax_report` -- because
    "what is deferred right now, and when can I buy this back" does not reset at a calendar boundary
    the way gains and Form 8949 do. Accepting a `year` here would invite a caller to believe it scopes
    something that never was scoped by year in the first place.

    `_build` runs the full lot replay, wash-sale pass, gains classification and Form 8949 build for
    one arbitrarily-chosen year (`engine.default_tax_year()`) purely to reach the whole-ledger
    `wash_sale_summary` sitting on its result -- work well beyond what this endpoint needs, accepted
    here rather than replaying the lot ledger and wash-sale pass a second way in this module. See
    `app.tax.engine`'s own docstring for the ~290ms this replay costs on a real ledger; that cost is
    paid once per request either way, by `/report` or by this endpoint, never twice for the same
    request.
    """
    report = _build(engine.default_tax_year())
    summary = report.wash_sale_summary
    if summary is None:
        # Not reachable through `_build` -- `build_tax_report` always sets this field -- but the type
        # is `Optional` because `TaxReport` is also constructed directly in tests without it (see its
        # docstring). Falling back to an empty, correctly-shaped summary keeps this endpoint total
        # rather than asserting against a case the type system, not the engine, leaves open.
        summary = build_wash_sale_summary((), as_of=dt.date.today())
    exposure = build_wash_sale_exposure_report(summary, generated_at=dt.datetime.now(dt.UTC))

    # `symbol_count` is computed above from the *full* `exposure.symbols` and must stay that way --
    # slicing happens only here, after it, so pagination never touches the total a caller relies on.
    symbol_count = exposure.symbol_count
    if limit is None:
        symbols = exposure.symbols[offset:]
    else:
        symbols = exposure.symbols[offset : offset + limit]
    return exposure.model_copy(
        update={
            "symbols": symbols,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(symbols) < symbol_count,
        }
    )
