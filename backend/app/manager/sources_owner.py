"""Layer A builders for the owner's own book: account, tax, activity, and the paper-desk / persona
books that sit beside them. See `app.manager.sources` for the fail-soft contract every builder here
follows, and `app.manager.models.FIGURE_KEYS` for the figure names each area may emit.

Every builder: `(ctx: SourceContext) -> SnapshotSection` with `key` equal to its own area. Money and
rates are decimal STRINGS (a rate is a 0-1 fraction, never a pre-multiplied percent). A partial total
keeps its gap list -- if `total_market_value` is null because something is unpriced, the section says
so rather than emitting a confident number.

Every builder calls the same service the matching page's router calls, in-process -- never HTTP,
never a second implementation of the underlying logic. Each is wrapped in a broad `except Exception`
so a broken upstream degrades to exactly one `ok=False` section rather than failing `collect()`
(which also catches, as a backstop -- see `app.manager.sources`).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import HTTPException

from app.manager.models import SectionItem, SnapshotSection, SourceRef
from app.manager.sources import SourceContext

__all__ = [
    "account_section",
    "activity_section",
    "paperdesk_section",
    "persona_books_section",
    "persona_traders_section",
    "tax_section",
]

#: Trim length for a persona trader's latest decision commentary embedded in its item's `text`.
_COMMENTARY_TRIM = 140

#: How many trailing days `activity_section` looks back from `ctx.as_of`.
_ACTIVITY_LOOKBACK_DAYS = 7


def account_section(ctx: SourceContext) -> SnapshotSection:
    """Every open position and the account-wide totals, from `app.api.portfolio._build_report()` --
    the same in-process call `GET /api/portfolio` makes."""
    from app.api import portfolio as portfolio_api

    try:
        report = portfolio_api._build_report()
    except HTTPException as exc:
        return SnapshotSection(key="account", ok=False, warnings=(str(exc.detail),))
    except Exception as exc:
        return SnapshotSection(
            key="account", ok=False, warnings=(f"{type(exc).__name__}: {exc}",)
        )

    items: list[SectionItem] = []
    for position in report.positions:
        figures: dict[str, str] = {"quantity": str(position.quantity)}
        if position.weight_pct is not None:
            figures["weight_pct"] = str(position.weight_pct)
        if position.day_change_pct is not None:
            figures["day_change_pct"] = str(position.day_change_pct)
        if position.market_value is not None:
            figures["market_value"] = str(position.market_value)
        if position.unrealized_pct is not None:
            figures["unrealized_pct"] = str(position.unrealized_pct)

        mv_text = str(position.market_value) if position.market_value is not None else "unpriced"
        items.append(
            SectionItem(
                id=position.symbol,
                label=position.symbol,
                figures=figures,
                observed_at=position.price_as_of.isoformat() if position.price_as_of else None,
                refs=(SourceRef(kind="symbol", id=position.symbol, label=position.symbol),),
                text=f"{position.symbol}: {position.quantity} sh, mv {mv_text}",
            )
        )

    section_figures: dict[str, str] = {"unpriced_count": str(len(report.unpriced_symbols))}
    # Partial totals keep their gap -- only a fully-priced book gets a confident total.
    if not report.unpriced_symbols and report.total_market_value is not None:
        section_figures["total_market_value"] = str(report.total_market_value)
    if report.total_day_change_pct is not None:
        section_figures["total_day_change_pct"] = str(report.total_day_change_pct)
    if report.cash_balance is not None:
        section_figures["cash_balance"] = str(report.cash_balance)

    warnings: list[str] = []
    if report.unpriced_symbols:
        warnings.append(f"unpriced: {', '.join(report.unpriced_symbols)}")
    if report.accounts_without_cash:
        warnings.append(f"cash unavailable for: {', '.join(report.accounts_without_cash)}")
    if not report.equity_is_complete:
        warnings.append("equity_is_complete=false")

    total_text = (
        f"total mv {section_figures['total_market_value']}"
        if "total_market_value" in section_figures
        else "total mv incomplete (unpriced symbols present)"
    )
    cash_text = f", cash {section_figures['cash_balance']}" if "cash_balance" in section_figures else ""
    text = f"{len(report.positions)} positions, {total_text}{cash_text}"

    return SnapshotSection(
        key="account",
        ok=True,
        as_of=report.as_of.isoformat(),
        text=text,
        figures=section_figures,
        items=tuple(items),
        warnings=tuple(warnings),
    )


def tax_section(ctx: SourceContext) -> SnapshotSection:
    """The current tax year's YTD gains plus whole-ledger wash-sale exposure, from
    `app.api.tax._build(year)` and `app.api.tax.wash_sales()` -- the same in-process calls
    `GET /api/tax/report` and `GET /api/tax/wash-sales` make."""
    from app.api import tax as tax_api

    try:
        report = tax_api._build(ctx.as_of.year)
        exposure = tax_api.wash_sales()
    except HTTPException as exc:
        return SnapshotSection(key="tax", ok=False, warnings=(str(exc.detail),))
    except Exception as exc:
        return SnapshotSection(key="tax", ok=False, warnings=(f"{type(exc).__name__}: {exc}",))

    figures = {
        "ytd_short_gain": str(report.gains.short_term_gain),
        "ytd_long_gain": str(report.gains.long_term_gain),
        "ytd_net_gain": str(report.gains.net_gain),
        # `deferred_disallowed` and `permanently_disallowed` are never summed together -- see
        # `WashSaleSymbolSummary`'s own docstring in `app.tax.models`.
        "deferred_disallowed": str(exposure.total_deferred),
        "permanently_disallowed": str(exposure.total_permanently_disallowed),
        "open_window_count": str(exposure.open_window_count),
    }

    items: list[SectionItem] = []
    for symbol in exposure.symbols:
        # Only symbols with a currently-open window, or a permanent (never-reopening) disallowance
        # on record, are worth a row here -- a closed window with nothing permanently lost is no
        # longer live exposure.
        if not symbol.window_is_open and symbol.permanently_disallowed == 0:
            continue
        loss_amount = sum((sale.loss_amount for sale in symbol.sales), Decimal(0))
        items.append(
            SectionItem(
                id=symbol.symbol,
                label=symbol.symbol,
                figures={
                    "days_until_safe": str(symbol.days_until_safe),
                    "loss_amount": str(loss_amount),
                    "deferred_disallowed": str(symbol.deferred_disallowed),
                },
                observed_at=symbol.last_sale_date.isoformat(),
                refs=(SourceRef(kind="symbol", id=symbol.symbol, label=symbol.symbol),),
                text=(
                    f"{symbol.symbol}: window "
                    f"{'open' if symbol.window_is_open else 'closed'}, "
                    f"deferred {symbol.deferred_disallowed}, safe in {symbol.days_until_safe}d"
                ),
            )
        )

    text = (
        f"YTD net gain {figures['ytd_net_gain']} "
        f"(short {figures['ytd_short_gain']}, long {figures['ytd_long_gain']}); "
        f"{exposure.open_window_count} open wash window(s), {exposure.total_deferred} deferred, "
        f"{exposure.total_permanently_disallowed} permanently disallowed"
    )

    return SnapshotSection(
        key="tax",
        ok=True,
        as_of=ctx.as_of.isoformat(),
        text=text,
        figures=figures,
        items=tuple(items),
    )


def activity_section(ctx: SourceContext) -> SnapshotSection:
    """Transactions in the trailing 7 days, from `app.api.transactions.list_transactions()` -- the
    same in-process call `GET /api/portfolio/transactions` makes."""
    from app.api import transactions as transactions_api

    start = ctx.as_of - dt.timedelta(days=_ACTIVITY_LOOKBACK_DAYS)
    try:
        page = transactions_api.list_transactions(start=start, end=ctx.as_of, newest_first=True)
    except HTTPException as exc:
        return SnapshotSection(key="activity", ok=False, warnings=(str(exc.detail),))
    except Exception as exc:
        return SnapshotSection(
            key="activity", ok=False, warnings=(f"{type(exc).__name__}: {exc}",)
        )

    items: list[SectionItem] = []
    for txn in page.transactions:
        figures: dict[str, str] = {}
        if txn.quantity is not None:
            figures["quantity"] = str(txn.quantity)
        if txn.amount is not None:
            figures["amount"] = str(txn.amount)
        label = f"{txn.action} {txn.symbol}".strip() if txn.symbol else txn.action
        items.append(
            SectionItem(
                id=txn.txn_id,
                label=label,
                figures=figures,
                observed_at=txn.trade_date.isoformat(),
                refs=(SourceRef(kind="txn", id=txn.txn_id, label=label),),
                text=(
                    f"{txn.trade_date.isoformat()} {label} "
                    f"qty {figures.get('quantity', '-')} amt {figures.get('amount', '-')}"
                ),
            )
        )

    text = f"{len(items)} transaction(s) in the last {_ACTIVITY_LOOKBACK_DAYS} days"
    return SnapshotSection(
        key="activity",
        ok=True,
        as_of=ctx.as_of.isoformat(),
        text=text,
        items=tuple(items),
    )


def paperdesk_section(ctx: SourceContext) -> SnapshotSection:
    """Every desk seat across every book, from `app.paperdesk.desk.state()` -- the same in-process
    call `GET /api/paperdesk/state` makes."""
    from app.paperdesk import desk as paperdesk_desk

    try:
        state = paperdesk_desk.state(ctx.settings)
    except Exception as exc:
        return SnapshotSection(
            key="paperdesk", ok=False, warnings=(f"{type(exc).__name__}: {exc}",)
        )

    items: list[SectionItem] = []
    book_lines: list[str] = []
    for book in state.books:
        book_equity = sum((seat.equity for seat in book.desks), Decimal(0))
        book_lines.append(f"{book.purpose}: {len(book.desks)} desk(s), equity {book_equity}")
        for seat in book.desks:
            figures: dict[str, str] = {
                "equity": str(seat.equity),
                "total_return": str(seat.total_return),
                "max_drawdown": str(seat.max_drawdown),
                "open_positions": str(seat.open_positions),
                "rejection_count": str(seat.rejection_count),
            }
            if seat.excess_return is not None:
                figures["excess_return"] = str(seat.excess_return)
            items.append(
                SectionItem(
                    id=seat.agent_id,
                    label=seat.display_name,
                    figures=figures,
                    refs=(SourceRef(kind="seat", id=seat.agent_id, label=seat.display_name),),
                    text=(
                        f"{seat.display_name} ({book.purpose}): equity {seat.equity}, "
                        f"return {seat.total_return}, {seat.open_positions} open"
                    ),
                )
            )

    text = f"as of {state.as_of.isoformat()}, {state.stale_days}d stale; " + "; ".join(book_lines)
    return SnapshotSection(
        key="paperdesk",
        ok=True,
        as_of=state.as_of.isoformat(),
        text=text,
        items=tuple(items),
    )


def persona_books_section(ctx: SourceContext) -> SnapshotSection:
    """One current-holdings paper book per persona, from `app.personas.service.persona_books()` --
    the same in-process call the Paper Desk page makes."""
    from app.personas import service as personas_service

    try:
        books = personas_service.persona_books(ctx.settings)
    except Exception as exc:
        return SnapshotSection(
            key="persona_books", ok=False, warnings=(f"{type(exc).__name__}: {exc}",)
        )

    items = [
        SectionItem(
            id=book.persona,
            label=book.display_name,
            figures={
                "equity": str(book.equity),
                "return_pct": str(book.return_pct),
                "open_count": str(book.open_count),
                "trade_count": str(book.trade_count),
            },
            observed_at=book.as_of.isoformat() if book.as_of else None,
            refs=(SourceRef(kind="persona", id=book.persona, label=book.display_name),),
            text=(
                f"{book.display_name}: equity {book.equity}, return {book.return_pct}, "
                f"{book.open_count} open / {book.trade_count} trades"
            ),
        )
        for book in books
    ]

    text = f"{len(items)} persona book(s)"
    return SnapshotSection(key="persona_books", ok=True, text=text, items=tuple(items))


def persona_traders_section(ctx: SourceContext) -> SnapshotSection:
    """One model-driven trader book per persona, from
    `app.personas.trader_service.list_trader_books()` -- the same in-process call the Paper Desk
    page makes."""
    from app.personas import trader_service as personas_trader_service

    try:
        books = personas_trader_service.list_trader_books(ctx.settings)
    except Exception as exc:
        return SnapshotSection(
            key="persona_traders", ok=False, warnings=(f"{type(exc).__name__}: {exc}",)
        )

    items: list[SectionItem] = []
    for book in books:
        # `TraderBook`'s money/rate fields are already decimal strings on the model -- passed
        # through verbatim, never re-parsed through a float.
        figures: dict[str, str] = {
            "equity": book.equity,
            "return_pct": book.return_pct,
            "decision_count": str(len(book.decisions)),
            "positions": str(len(book.positions)),
        }
        if book.benchmark_return_pct is not None:
            figures["benchmark_return_pct"] = book.benchmark_return_pct
        if book.excess_pct is not None:
            figures["excess_pct"] = book.excess_pct

        commentary = ""
        if book.decisions:
            commentary = book.decisions[0].commentary.strip()
            if len(commentary) > _COMMENTARY_TRIM:
                commentary = commentary[: _COMMENTARY_TRIM - 3] + "..."

        summary = f"{book.display_name}: equity {book.equity}, return {book.return_pct}"
        items.append(
            SectionItem(
                id=book.persona,
                label=book.display_name,
                figures=figures,
                observed_at=book.as_of,
                refs=(SourceRef(kind="persona", id=book.persona, label=book.display_name),),
                text=f"{summary}. {commentary}".strip() if commentary else summary,
            )
        )

    text = f"{len(items)} persona trader(s)"
    return SnapshotSection(key="persona_traders", ok=True, text=text, items=tuple(items))
