"""Render one analyst's :class:`~app.tournament.models.AgentResult` as a PDF.

**Why a PDF at all, and why this shape.** The tournament produces a number -- a total return -- for
each of ten analysts, and the naive presentation of that is exactly the p-hacking artifact
`app.tournament.models` exists to prevent: a leaderboard with the winner's return in bold. A report
that can be checked has to show the rules that produced the number beside the number, the window the
result was measured over, the broker's rejections, and the correction for having tried ten strategies
-- so that a reader with the PDF and nothing else can tell whether the number means anything. Every
section below exists because omitting it would let the report describe a different, better-looking
strategy than the one that actually ran.

**Why platypus rather than an HTML template.** This checkout has no `jinja2`, `weasyprint`,
`markdown`, or `wkhtmltopdf`/`pandoc` on `PATH` -- an HTML-to-PDF route does not exist here.
`reportlab`'s platypus API (`SimpleDocTemplate` plus a story of flowables) is the only working path,
so that is what this module uses.

**Why verbatim fields go through `Preformatted`, not `Paragraph`.** A `Paragraph` interprets a subset
of HTML, so a rule-DSL expression containing `<` or `&` (e.g. ``close < sma_50``) would either be
silently mangled or crash the parser. `Preformatted` renders its text literally with a fixed-width
font and no markup interpretation, which is also the more honest rendering for something the report
promises is verbatim.

**Why `None` and `0` must never look alike.** Several of `AgentResult`'s fields -- `sharpe`,
`profit_factor`, `realised_reward_risk`, `q_value` -- are `None` when the underlying quantity could
not be computed (too few trades, no losing trades, no tournament supplied), not when it was computed
and happened to be zero. Rendering both as ``0`` would make an unmeasured strategy look identical to
one that was measured and broke even, which is precisely the kind of confusion this repo's other
report-writing code (`app.report.models`) was built to make impossible. Every optional numeric field
here renders as an em dash when `None` and never coerces a missing value to zero.

**Why Decimal never touches float.** `Money` and `Quantity` (see `app.core.models`) are `Decimal`
specifically so that no binary-float rounding error can enter a monetary figure. Formatting a
`Decimal` for display uses `Decimal.__format__`/`Decimal.quantize` directly; nothing in this module
calls `float()` on a `Decimal`-typed value.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, StyleSheet1, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.tournament.models import (
    DESIGN_THROUGH,
    TRADE_END,
    TRADE_START,
    AgentResult,
    RealisedTrade,
    TournamentResult,
)

__all__ = ["render_agent_report"]

_DASH: Final[str] = "—"
"""Rendered for every optional metric that is ``None``. Never used for a real zero -- see the module
docstring."""

_MAX_TRADES_SHOWN: Final[int] = 50
"""A tournament run can close hundreds of trades; the PDF shows a fair sample with the true count
stated, rather than either truncating silently or laying out an unbounded table."""

_MAX_REJECTIONS_SHOWN: Final[int] = 50

_TABLE_STYLE: Final[TableStyle] = TableStyle(
    [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
)

_KV_TABLE_STYLE: Final[TableStyle] = TableStyle(
    [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
)


def _fmt_decimal(value: Decimal | None, *, digits: int = 2, suffix: str = "") -> str:
    """Format a ``Decimal`` without ever routing it through ``float``.

    ``None`` renders as an em dash -- "not computed" -- which is a different claim from "computed
    and zero". Callers must pass ``None`` only for genuinely unmeasured quantities.
    """
    if value is None:
        return _DASH
    quantum = Decimal(1).scaleb(-digits)
    return f"{value.quantize(quantum)}{suffix}"


def _fmt_pct_decimal(value: Decimal | None, *, digits: int = 2) -> str:
    """Format a ``Decimal`` fraction (``Decimal("0.05")``) as a percentage string."""
    if value is None:
        return _DASH
    return _fmt_decimal(value * 100, digits=digits, suffix="%")


def _fmt_float(value: float | None, *, digits: int = 2) -> str:
    """Format a native ``float`` metric (sharpe, sortino, ...). These fields are ``float`` in
    `AgentResult` itself -- not `Money` -- so formatting them with ``float`` formatting does not
    violate the no-float-for-money rule."""
    if value is None:
        return _DASH
    return f"{value:.{digits}f}"


def _fmt_pct_float(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return _DASH
    return f"{value * 100:.{digits}f}%"


def _fmt_money(value: Decimal) -> str:
    """Format a `Money` value for display. ``Decimal.__format__`` supports thousands separators and
    fixed precision directly -- no detour through ``float`` is needed or permitted."""
    return f"${value:,.2f}"


def _fmt_int(value: int | None) -> str:
    return _DASH if value is None else str(value)


def _kv_table(
    rows: list[list[str]], *, col_widths: tuple[float, float] = (2.3 * inch, 3.4 * inch)
) -> Table:
    """A two-column label/value table, used throughout for the strategy card and result blocks."""
    table = Table(rows, colWidths=list(col_widths))
    table.setStyle(_KV_TABLE_STYLE)
    return table


def _styles() -> StyleSheet1:
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "Mono",
            parent=styles["Code"],
            fontName="Courier",
            fontSize=8.5,
            leading=11,
        )
    )
    return styles


def _brackets_rows(result: AgentResult) -> list[list[str]]:
    c = result.card
    return [
        ["Stop loss", _fmt_pct_decimal(c.stop_loss_pct)],
        ["Take profit", _fmt_pct_decimal(c.take_profit_pct)],
        ["Max hold days", _fmt_int(c.max_hold_days)],
        ["Max positions", str(c.max_positions)],
        ["Position size (fraction of equity)", _fmt_pct_decimal(c.position_pct)],
        ["Designed through", c.designed_through.isoformat()],
    ]


def _strategy_section(result: AgentResult, styles: StyleSheet1) -> list[Any]:
    story: list[Any] = []
    c = result.card
    story.append(Paragraph("Strategy as submitted", styles["Heading2"]))
    story.append(
        Paragraph(
            "Everything below is what the analyst submitted before the trading window ran. A "
            "result cannot be checked against a strategy that is not shown alongside it.",
            styles["BodyText"],
        )
    )
    story.append(Paragraph("Discipline", styles["Heading3"]))
    story.append(Paragraph(c.discipline.value, styles["BodyText"]))
    story.append(Paragraph("Thesis", styles["Heading3"]))
    story.append(Preformatted(c.thesis, styles["Mono"]))
    story.append(Paragraph("Universe", styles["Heading3"]))
    story.append(Paragraph(", ".join(c.universe), styles["BodyText"]))
    story.append(Paragraph("Entry rule", styles["Heading3"]))
    story.append(Preformatted(c.entry, styles["Mono"]))
    story.append(Paragraph("Exit rule", styles["Heading3"]))
    story.append(Preformatted(c.exit, styles["Mono"]))
    story.append(Paragraph("Brackets and sizing", styles["Heading3"]))
    story.append(_kv_table(_brackets_rows(result)))
    story.append(Spacer(1, 10))
    return story


def _window_section(
    result: AgentResult, window: tuple[dt.date, dt.date], styles: StyleSheet1
) -> list[Any]:
    trade_start, trade_end = window
    story: list[Any] = []
    story.append(Paragraph("Trading window", styles["Heading2"]))
    story.append(
        Paragraph(
            f"Designed through {DESIGN_THROUGH.isoformat()}. Traded {trade_start.isoformat()} "
            f"through {trade_end.isoformat()}, {result.sessions} sessions.",
            styles["BodyText"],
        )
    )
    # The out-of-sample claim is a property of *this* window, not of the package, so it is decided
    # here rather than asserted unconditionally. Printing both sentences -- "this is out-of-sample"
    # followed by "part of this is in-sample" -- is how the first three-year run's reports read, and
    # a report that contradicts itself within one paragraph teaches the reader to trust neither half.
    if trade_start > DESIGN_THROUGH:
        story.append(
            Paragraph(
                "The design window and the trading window are different windows -- the design "
                "cutoff is before the first traded session -- which is what makes this an "
                "out-of-sample result rather than a fit graded on the data used to build it.",
                styles["BodyText"],
            )
        )
    else:
        story.append(
            Paragraph(
                "This run's trading window starts on or before the design cutoff, so the analyst "
                "designed this strategy with sight of part of the data it just traded. The portion "
                "of the run before "
                f"{DESIGN_THROUGH.isoformat()} is in-sample and does not measure out-of-sample "
                "performance -- only sessions after the design cutoff do.",
                styles["BodyText"],
            )
        )
    story.append(Spacer(1, 10))
    return story


def _results_rows(result: AgentResult) -> list[list[str]]:
    """The headline metrics table, as label/value pairs.

    Pulled out as a pure function -- taking an `AgentResult` and returning plain strings, no
    `reportlab` object in sight -- so a test can assert exactly what each cell says (in particular,
    that a ``None`` metric renders as :data:`_DASH` and not ``"0"``) without parsing a rendered PDF.
    """
    return [
        ["Total return", _fmt_pct_decimal(result.total_return)],
        ["Max drawdown", _fmt_pct_decimal(result.max_drawdown)],
        ["Sharpe", _fmt_float(result.sharpe)],
        ["Sortino", _fmt_float(result.sortino)],
        ["Volatility", _fmt_float(result.volatility)],
        ["Exposure", _fmt_pct_float(result.exposure)],
        ["Win rate", _fmt_pct_float(result.win_rate)],
        ["Profit factor", _fmt_decimal(result.profit_factor)],
        ["Trade count", str(len(result.trades))],
    ]


def _reward_risk_rows(result: AgentResult) -> list[list[str]]:
    return [
        ["Planned reward:risk (card)", _fmt_decimal(result.card.reward_risk)],
        ["Realised reward:risk", _fmt_decimal(result.realised_reward_risk)],
    ]


def _benchmark_rows(result: AgentResult) -> list[list[str]]:
    rows = [
        ["Strategy total return", _fmt_pct_decimal(result.total_return)],
        ["Buy-and-hold benchmark return, same sessions", _fmt_pct_decimal(result.benchmark_return)],
    ]
    if result.benchmark_return is not None:
        rows.append(
            [
                "Excess over benchmark",
                _fmt_pct_decimal(result.total_return - result.benchmark_return),
            ]
        )
    return rows


def _results_section(result: AgentResult, styles: StyleSheet1) -> list[Any]:
    story: list[Any] = []
    story.append(Paragraph("Results", styles["Heading2"]))
    story.append(_kv_table(_results_rows(result)))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Reward:risk, planned versus realised", styles["Heading3"]))
    story.append(
        Paragraph(
            "Planned is the ratio the card declared before trading (take-profit over stop-loss). "
            "Realised is what actually happened -- mean winning return over mean losing return -- "
            "since most trades exit on the rule or the time stop, not on either bracket.",
            styles["BodyText"],
        )
    )
    story.append(_kv_table(_reward_risk_rows(result)))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Benchmark comparison", styles["Heading3"]))
    story.append(_kv_table(_benchmark_rows(result)))
    story.append(Spacer(1, 10))
    return story


def _trade_row(trade: RealisedTrade) -> list[str]:
    return [
        trade.symbol,
        trade.entry_date.isoformat(),
        trade.exit_date.isoformat() if trade.exit_date is not None else _DASH,
        str(trade.quantity),
        _fmt_money(trade.entry_price),
        _fmt_money(trade.exit_price) if trade.exit_price is not None else _DASH,
        _fmt_money(trade.pnl),
        _fmt_pct_decimal(trade.return_pct),
        trade.exit_reason,
    ]


def _trades_section(result: AgentResult, styles: StyleSheet1) -> list[Any]:
    story: list[Any] = []
    story.append(Paragraph("Trades", styles["Heading2"]))
    if not result.trades:
        story.append(
            Paragraph(
                "No trades closed in this window. Zero closed trades is a measured outcome, not a "
                "missing one.",
                styles["BodyText"],
            )
        )
        story.append(Spacer(1, 10))
        return story

    total = len(result.trades)
    shown = result.trades[:_MAX_TRADES_SHOWN]
    if total > _MAX_TRADES_SHOWN:
        story.append(
            Paragraph(
                f"Showing the first {_MAX_TRADES_SHOWN} of {total} trades.",
                styles["BodyText"],
            )
        )
    else:
        story.append(Paragraph(f"{total} trade{'s' if total != 1 else ''}.", styles["BodyText"]))

    header = ["Symbol", "Entry", "Exit", "Qty", "Entry $", "Exit $", "PnL", "Return", "Reason"]
    rows: list[list[str]] = [header] + [_trade_row(t) for t in shown]
    table = Table(rows, repeatRows=1)
    table.setStyle(_TABLE_STYLE)
    story.append(table)
    story.append(Spacer(1, 10))
    return story


def _rejections_section(result: AgentResult, styles: StyleSheet1) -> list[Any]:
    story: list[Any] = []
    story.append(Paragraph("Rejected orders", styles["Heading2"]))
    story.append(
        Paragraph(
            "Orders the mock broker refused. A strategy whose orders were mostly rejected did not "
            "run as written, and omitting this list would describe a different strategy.",
            styles["BodyText"],
        )
    )
    if not result.rejections:
        story.append(
            Paragraph("None. Every order this strategy sent was accepted.", styles["BodyText"])
        )
        story.append(Spacer(1, 10))
        return story

    total = len(result.rejections)
    shown = result.rejections[:_MAX_REJECTIONS_SHOWN]
    if total > _MAX_REJECTIONS_SHOWN:
        story.append(
            Paragraph(
                f"Showing the first {_MAX_REJECTIONS_SHOWN} of {total} rejections.",
                styles["BodyText"],
            )
        )
    else:
        story.append(
            Paragraph(f"{total} rejection{'s' if total != 1 else ''}.", styles["BodyText"])
        )
    story.append(Preformatted("\n".join(shown), styles["Mono"]))
    story.append(Spacer(1, 10))
    return story


def _significance_section(
    result: AgentResult, tournament: TournamentResult | None, styles: StyleSheet1
) -> list[Any]:
    story: list[Any] = []
    story.append(Paragraph("Statistical significance", styles["Heading2"]))
    story.append(
        Paragraph(
            f"p-value (two-sided, binomial on the win/loss record): {_fmt_float(result.p_value)}",
            styles["BodyText"],
        )
    )
    if tournament is not None:
        n_agents = len(tournament.agents)
        story.append(
            Paragraph(
                f"q-value, corrected via Benjamini-Hochberg across the {n_agents} strategies "
                f"tried in this tournament: {_fmt_float(result.q_value)}",
                styles["BodyText"],
            )
        )
    else:
        story.append(
            Paragraph(
                "q-value: not available. This report was generated without the tournament result, "
                "so no correction for the number of strategies tried could be applied -- the "
                "p-value above is uncorrected and should not be read as a q-value.",
                styles["BodyText"],
            )
        )
    story.append(Spacer(1, 10))
    return story


def _limitations_section(result: AgentResult, styles: StyleSheet1) -> list[Any]:
    story: list[Any] = []
    story.append(Paragraph("Limitations", styles["Heading2"]))
    bullets = [
        f"{result.sessions} sessions is one market regime, not a sample of regimes. A strategy "
        "that worked here has not been shown to work in a rising-rate, high-volatility, or "
        "sideways regime -- only in whatever this one was.",
        "The traded universe was chosen because the user already trades these names. That is a "
        "selection effect, not a random or representative sample of the market, and it biases "
        "every result in this report in a direction that cannot be corrected after the fact.",
        "Fills are simulated: orders execute at the next session's open with deterministic "
        "adverse slippage applied by the mock broker. These are not real fills -- a live broker "
        "would fill some orders worse, and might reject orders this simulation accepted.",
        "This is a simulation of a trading strategy, not investment advice, and no figure in "
        "this report should be treated as a recommendation to trade.",
    ]
    for bullet in bullets:
        story.append(Paragraph(f"• {bullet}", styles["BodyText"]))
    return story


def render_agent_report(
    result: AgentResult,
    *,
    out_dir: Path,
    tournament: TournamentResult | None = None,
    window: tuple[dt.date, dt.date] | None = None,
) -> Path:
    """Render ``result`` to a one-analyst PDF report and return the path written.

    The file is named from ``result.card.agent_id`` (a short slug, unique within the tournament --
    see `StrategyCard.agent_id`), so calling this once per agent into the same `out_dir` produces one
    report per analyst with no collisions.

    ``tournament`` is optional because a single agent's result is a valid, useful object on its own
    (during development, or when re-rendering one analyst's report). When it is supplied, the q-value
    section states how many strategies the multiple-comparison correction ran across; when it is not,
    the report says plainly that no correction could be applied rather than rendering a q-value
    figure with no stated denominator, which would look precise while being unverifiable.

    The window printed in the "Trading window" section is resolved in this order: an explicit
    ``window`` argument (the caller knows exactly what dates it ran), else ``tournament``'s own
    `trade_start`/`trade_end` when a `tournament` was supplied (it already carries the real window
    for the run that produced ``result``), else the module's `TRADE_START`/`TRADE_END` constants as a
    last resort. Falling straight to the constants whenever `tournament` is supplied would print the
    old fixed window even when `tournament` proves a different one actually ran.
    """
    if window is not None:
        resolved_window = window
    elif tournament is not None:
        resolved_window = (tournament.trade_start, tournament.trade_end)
    else:
        resolved_window = (TRADE_START, TRADE_END)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{result.card.agent_id}.pdf"

    styles = _styles()
    story: list[Any] = []

    story.append(Paragraph(f"{result.card.display_name} ({result.card.agent_id})", styles["Title"]))
    story.append(Spacer(1, 6))

    story.extend(_strategy_section(result, styles))
    story.extend(_window_section(result, resolved_window, styles))
    story.extend(_results_section(result, styles))
    story.extend(_trades_section(result, styles))
    story.extend(_rejections_section(result, styles))
    story.extend(_significance_section(result, tournament, styles))
    story.extend(_limitations_section(result, styles))

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title=f"{result.card.display_name} tournament report",
    )
    doc.build(story)
    return out_path
