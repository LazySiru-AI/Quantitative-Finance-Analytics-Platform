"""Shared shapes for the tax engine.

These types are the contract between the wash-sale pass, the gains report, Form 8949 and the
1099-B reconciliation. They are declared in one place so those four modules can be written against
each other without any of them owning the definitions.

**Everything here is a calculation, not tax advice.** The output must be reconciled against the
user's 1099-B forms before it informs a filing.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, computed_field

from app.core.models import Money, Quantity

__all__ = [
    "EquivalenceDecision",
    "EquivalenceRule",
    "Form8949Box",
    "Form8949Report",
    "Form8949Row",
    "GainsReport",
    "HoldingTerm",
    "ReconcileLine",
    "ReconcileReport",
    "ReconcileStatus",
    "TaxReport",
    "TaxWarning",
    "UnsettledPair",
    "WarningGroup",
    "WashSaleEvent",
    "WashSaleExposureReport",
    "WashSaleSaleRow",
    "WashSaleSummary",
    "WashSaleSymbolSummary",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Substantially identical
# ---------------------------------------------------------------------------


class EquivalenceDecision(StrEnum):
    """Whether two instruments are "substantially identical" under §1091.

    The statute does not define the term and the IRS has not ruled on several pairs this portfolio
    actually holds. The engine therefore has three answers, not two, and ``UNSETTLED`` is a real
    output rather than a placeholder: silently choosing either interpretation is the defect.
    """

    IDENTICAL = "identical"
    """Same CUSIP. The only case the engine decides on its own."""

    NOT_IDENTICAL = "not_identical"
    """Settled in the negative — a fund and its inverse (SOXL/SOXS) are never grouped."""

    UNSETTLED = "unsettled"
    """No authority. Surfaced to the user with both interpretations priced; never auto-applied."""


class EquivalenceRule(_Frozen):
    """One entry in the substantially-identical table, keyed on symbols rather than CUSIP.

    Symbols are the right key here despite CUSIP being the identity key elsewhere: these rules
    express a relationship between two *different* securities, and the user reasons about them by
    ticker.
    """

    left: str
    right: str
    decision: EquivalenceDecision
    rationale: str
    """Why. Shown in the UI next to the flag, so the user can judge the reasoning."""

    def matches(self, a: str, b: str) -> bool:
        """Order-independent symbol match."""
        pair = {a.upper(), b.upper()}
        return pair == {self.left.upper(), self.right.upper()}


class UnsettledPair(_Frozen):
    """A potential wash sale the engine refuses to decide, with both outcomes priced.

    The user rules on it and the decision is recorded. Until then neither number is applied.
    """

    sale_disposal_id: str
    sold_symbol: str
    replacement_symbol: str
    sale_date: dt.date
    loss_amount: Money
    """The loss at stake, positive."""
    impact_if_identical: Money
    """Disallowed amount were the pair treated as substantially identical. Positive."""
    impact_if_distinct: Money
    """Disallowed amount otherwise — normally zero. Present so the UI can show both sides."""
    rationale: str


# ---------------------------------------------------------------------------
# Wash sales
# ---------------------------------------------------------------------------


class WashSaleEvent(_Frozen):
    """One triggered wash sale, traceable to the sale and to every replacement that caused it."""

    event_id: str
    disposal_id: str
    instrument_id: str
    symbol: str

    sale_date: dt.date
    sale_account_id: str
    quantity_sold: Quantity
    loss_amount: Money
    """The full realised loss before disallowance. Positive number."""

    quantity_replaced: Quantity
    """Shares matched by replacement purchases in the 61-day window, capped at ``quantity_sold``."""
    disallowed_loss: Money
    """Positive. Proportional to ``quantity_replaced / quantity_sold`` on a partial replacement."""

    replacement_txn_ids: tuple[str, ...] = ()
    replacement_lot_ids: tuple[str, ...] = ()
    replacement_account_ids: tuple[str, ...] = ()

    permanently_disallowed: bool = False
    """Rev. Rul. 2008-5: replacement bought in an IRA. The loss is destroyed, not deferred, and no
    basis is added anywhere — not to the IRA lot, not to anything. Reported as its own line."""

    basis_added_to_lot_id: str | None = None
    """The replacement lot that absorbed the disallowed loss. ``None`` when permanently disallowed,
    which is exactly the distinction that makes the IRA case worse."""

    holding_period_tolled_to: dt.date | None = None
    """The earlier holding-period start the replacement lot inherited. ``None`` if not tolled."""

    is_chained: bool = False
    """True when the sold lot was itself a wash-sale replacement, so this loss was computed against
    an already-adjusted basis."""


class WashSaleSaleRow(_Frozen):
    """One loss sale, for the exposure tracker's drill-down under a symbol.

    **One row per triggered** :class:`WashSaleEvent`, not per disposal -- a disposal split across a
    taxable and an IRA replacement produces one deferred event and one permanent event from the same
    sale, and folding them into a single row would force ``disallowed_loss`` to mix the two kinds of
    money the rest of this module keeps apart (see the module docstring). Two rows sharing a
    ``disposal_id`` is the correctly ungainly result of that split, confirmed on real data -- disposals
    split across Webull Margin and Webull Roth.

    **Plus one row for every loss sale that triggered no event at all** -- a loss not yet matched to
    a replacement purchase. These are the rows :func:`build_wash_sale_summary`'s own docstring calls
    "the one case where acting on this panel still changes the outcome": nothing has been disallowed
    (``disallowed_loss`` and ``quantity_replaced`` are zero, ``permanently_disallowed`` is false,
    ``replacement_account_ids`` is empty), but ``loss_amount`` is the sale's real loss and the window
    is still open. Their presence is why a symbol's ``len(sales)`` can exceed its ``event_count`` --
    the two counts answer different questions and callers must not assume they are equal.
    """

    disposal_id: str
    sale_date: dt.date
    account_id: str
    """Sale-side account -- :attr:`WashSaleEvent.sale_account_id` for a triggered row, the disposal's
    own account for an untriggered one."""
    quantity_sold: Quantity
    quantity_replaced: Quantity
    """Zero for an untriggered row -- nothing has been matched to a replacement yet."""
    loss_amount: Money
    """The full realised loss before disallowance, positive. Real on every row, triggered or not --
    an untriggered loss is exactly as real as a triggered one, it simply has not been disallowed."""
    disallowed_loss: Money
    """Zero for an untriggered row. Never mixes deferred and permanent -- see the class docstring."""
    permanently_disallowed: bool
    replacement_account_ids: tuple[str, ...]
    window_closes_on: dt.date
    """``sale_date + 31`` days -- this sale's *own* window. Differs from the symbol-level
    :attr:`WashSaleSymbolSummary.repurchase_safe_on`, which is measured from the symbol's *latest*
    sale and can be later than this row's own close date."""


class WashSaleSymbolSummary(_Frozen):
    """One symbol's wash-sale exposure, aggregated across every triggered event.

    ``deferred_disallowed`` and ``permanently_disallowed`` are never summed with each other -- see
    the module docstring's distinction and :attr:`WashSaleEvent.permanently_disallowed`. Deferred is
    already sitting in a replacement lot's basis, recovered only when that lot is sold and not
    re-replaced within its own 30 days; permanent (Rev. Rul. 2008-5) is destroyed and recovered by
    nothing.
    """

    symbol: str
    deferred_disallowed: Money
    """Sum of every non-permanent event's ``disallowed_loss``. Already added to a replacement lot's
    basis -- not money released by waiting."""
    permanently_disallowed: Money
    """Sum of every permanent event's ``disallowed_loss`` (Rev. Rul. 2008-5). Destroyed, not
    deferred; must never be added to :attr:`deferred_disallowed`."""
    event_count: int
    loss_sale_count: int
    """Distinct disposals (``WashSaleEvent.disposal_id``) that triggered at least one event -- not
    the same as :attr:`event_count`, since one disposal split across a taxable and an IRA
    replacement produces two events from one sale."""
    first_sale_date: dt.date
    last_sale_date: dt.date
    """The most recent triggering sale. Its own 30-day window is the last to close, so
    :attr:`repurchase_safe_on` is measured from this date, not from :attr:`first_sale_date`."""
    repurchase_safe_on: dt.date
    """``last_sale_date + 31`` days -- the first date IRC §1091's window no longer reaches back to
    that sale (inclusive at +30, exclusive at +31; see ``app.tax.washsale``)."""
    days_until_safe: int
    """``max(0, (repurchase_safe_on - as_of).days)`` -- zero, never negative, once the window has
    already closed."""
    window_is_open: bool
    """``as_of <= last_sale_date + 30``. True through the last day the window still reaches back."""
    accounts: tuple[str, ...]
    """Sale-side account ids (``WashSaleEvent.sale_account_id``) that sold this symbol at a loss
    inside a wash-sale window, sorted."""
    sales: tuple[WashSaleSaleRow, ...] = ()
    """The individual loss sales behind this row's totals -- see :class:`WashSaleSaleRow` for the
    grain and why ``len(sales)`` is not the same number as :attr:`event_count`. Sorted by
    ``sale_date`` descending: the most recent sale's window is the last to close, so it leads.
    Defaults to empty rather than being required, so existing callers that build a
    :class:`WashSaleSymbolSummary` without loss-sale detail (tests constructing one by hand) are not
    forced to supply it."""


class WashSaleSummary(_Frozen):
    """Wash-sale exposure aggregated per symbol, for the Tax page's "what's deferred, and when is it
    safe to repurchase" view.

    ``as_of`` is the one clock-dependent input -- see :func:`app.tax.engine.build_tax_report`. It
    affects only :attr:`WashSaleSymbolSummary.days_until_safe` and
    :attr:`WashSaleSymbolSummary.window_is_open`; every dollar figure here is deterministic given the
    same events.
    """

    as_of: dt.date
    symbols: tuple[WashSaleSymbolSummary, ...]
    """Sorted by :attr:`~WashSaleSymbolSummary.deferred_disallowed` descending, then symbol
    ascending -- the symbols with the most at stake lead."""
    total_deferred: Money
    """Sum of every symbol's ``deferred_disallowed``."""
    total_permanently_disallowed: Money
    """Sum of every symbol's ``permanently_disallowed``. Kept separate from :attr:`total_deferred`
    for the same reason the per-symbol figures are -- see :class:`WashSaleSymbolSummary`."""
    open_window_count: int
    """Count of symbols with :attr:`~WashSaleSymbolSummary.window_is_open` true."""


class WashSaleExposureReport(_Frozen):
    """``GET /api/tax/wash-sales`` -- the whole-ledger wash-sale exposure tracker.

    Not year-scoped, and deliberately has no ``year`` field: see :class:`WashSaleSummary` and
    ``app.tax.washsale_summary``'s module docstring. "What is deferred right now, and when can I buy
    this back" does not reset at a calendar boundary the way gains and Form 8949 do.

    Wraps the same figures as :class:`WashSaleSummary` -- ``total_deferred``,
    ``total_permanently_disallowed``, ``open_window_count``, and per-symbol rows carrying
    :attr:`WashSaleSymbolSummary.sales` -- under a **different symbol order**. The Tax report page
    reads :attr:`WashSaleSummary.symbols` sorted by size alone; this tracker's whole purpose is "what
    is still live", so :attr:`symbols` here leads with open windows before size ever breaks the tie,
    and that ordering is produced server-side rather than left for a client to re-sort.
    """

    as_of: dt.date
    generated_at: dt.datetime
    """Wall-clock time the report was built. Distinct from :attr:`as_of`, the date
    ``days_until_safe``/``window_is_open`` are measured from -- see :class:`WashSaleSummary`."""
    total_deferred: Money
    total_permanently_disallowed: Money
    open_window_count: int
    symbol_count: int
    """The full, **unsliced** count of symbols in this tracker -- set from the complete list before
    ``limit``/``offset`` (see below) ever truncate :attr:`symbols`. Stays a reliable total regardless
    of paging, which is what the ``/wash-sales`` page's "N symbols tracked" tile and the Overview
    page's badge both read; neither passes ``limit``, so neither is affected by this field's
    docstring changing, only by that guarantee being written down."""
    symbols: tuple[WashSaleSymbolSummary, ...]
    """Sorted **open windows first**, then :attr:`~WashSaleSymbolSummary.deferred_disallowed`
    descending, then symbol ascending -- see the class docstring. Contrast
    :attr:`WashSaleSummary.symbols`, which this tracker does not reuse the order of. Sliced to one
    page when the endpoint is called with ``limit`` -- see :attr:`limit` below."""

    limit: int | None = None
    """Mirrors :attr:`TaxReport.limit` -- the page size :attr:`symbols` was built with. ``None`` --
    the default -- means the caller did not paginate and :attr:`symbols` is the whole tracker."""
    offset: int = 0
    """Mirrors :attr:`TaxReport.offset`."""
    has_more: bool = False
    """Whether :attr:`symbols` has more entries beyond this page -- ``offset + len(symbols) <
    symbol_count``. Always ``False`` when :attr:`limit` is ``None``."""


# ---------------------------------------------------------------------------
# Gains
# ---------------------------------------------------------------------------


class HoldingTerm(StrEnum):
    """Capital gains term.

    Long-term requires **more than** one year. The holding period starts the day *after*
    acquisition, so a security bought 2025-01-10 and sold 2026-01-10 is short-term; 2026-01-11 is
    long-term. Exactly one year is short-term.
    """

    SHORT = "short"
    LONG = "long"


class GainRow(_Frozen):
    """One disposal, classified and priced. The unit of both the gains report and Form 8949."""

    disposal_id: str
    instrument_id: str
    symbol: str
    account_id: str
    account_label: str

    quantity: Quantity
    lot_id: str
    """The lot these shares came out of. With ``lot_method``, this is the answer to "which shares
    did I just sell" -- previously derivable only by dividing the basis by the quantity and matching
    the result against the acquisition prices by hand."""
    lot_method: str | None = None
    """``"fifo"`` when a rule selected the lot; ``null`` on an oversold shortfall, where the replay
    found no lot to consume. Lot selection changes the tax outcome, so it is stated rather than
    inferred."""
    acquired_date: dt.date
    holding_start: dt.date
    """Post-tolling. Differs from ``acquired_date`` only when a wash sale moved it earlier."""
    disposed_date: dt.date
    term: HoldingTerm

    proceeds: Money
    cost_basis: Money
    fees: Money
    gain_loss: Money
    """Before disallowance. Negative is a loss."""
    disallowed_loss: Money = Decimal(0)
    """**Total** disallowed under §1091, deferred and permanent together."""
    permanently_disallowed_loss: Money = Decimal(0)
    """The destroyed portion (Rev. Rul. 2008-5). A sale replaced partly in an IRA and partly in a
    taxable account carries both, so this is an amount rather than a share of the whole."""
    permanently_disallowed: bool = False
    """True when any part of the disallowance is permanent. Use the amounts, not this flag, for
    arithmetic -- it cannot express a partial split."""
    reportable_gain_loss: Money = Decimal(0)
    """After disallowance. What the Form 8949 gain column carries."""

    is_wash_sale: bool = False
    basis_uncertain: bool = False
    """The replay could not establish this lot's basis. The gain is overstated and must not be filed
    without correction."""
    fees_unknown: bool = False
    """This disposal's sale carries ``fees = 0`` not because no fee was charged, but because the
    source export has no fee column at all (currently: every Webull sale --
    :class:`~app.core.lots.WarningKind.FEES_UNKNOWN`). Independent of ``basis_uncertain``: basis can
    be fully known while the regulatory (SEC/TAF) fee on the same sale is simply missing. Proceeds
    and the reported gain are therefore very slightly overstated -- a much smaller effect than an
    unverifiable basis, which is why this is its own flag rather than folded into that one."""


class GainsReport(_Frozen):
    """Realised gains over a date range, taxable accounts only.

    Tax-advantaged accounts are **excluded here and scanned anyway** by the wash-sale pass. Both must
    be true at once; implementing one and not the other is the classic bug in this area.
    """

    start: dt.date
    end: dt.date
    rows: tuple[GainRow, ...] = ()

    short_term_proceeds: Money = Decimal(0)
    short_term_basis: Money = Decimal(0)
    short_term_gain: Money = Decimal(0)
    long_term_proceeds: Money = Decimal(0)
    long_term_basis: Money = Decimal(0)
    long_term_gain: Money = Decimal(0)

    disallowed_loss_total: Money = Decimal(0)
    """Ordinary wash sales: deferred, added to replacement basis."""
    permanently_disallowed_total: Money = Decimal(0)
    """Rev. Rul. 2008-5 IRA cases: gone. Deliberately a separate total."""

    excluded_account_ids: tuple[str, ...] = ()
    """Tax-advantaged accounts omitted from the figures above."""
    rows_with_uncertain_basis: int = 0
    gain_on_uncertain_basis: Money = Decimal(0)
    """Reportable gain contributed by the rows counted in :attr:`rows_with_uncertain_basis`.

    **A count is not a size, and here the two tell opposite stories.** On a real ledger a small fraction of
    rows carried an unestablished basis -- which reads as a rounding concern. Those rows
    contributed a large positive gain, while all the others netted to a loss. The headline gain
    was not slightly overstated by them; it was produced by them.

    This is the amount by which the reported gain would move if every one of those rows turned out to
    have cost exactly what it sold for. It is therefore a bound on the correction available, not an
    estimate of the error: the true basis is somewhere between zero and this, and only the user's own
    records can say where. Exposed so a caveat can state the size of the doubt instead of only its
    existence -- the same obligation ``accounts_without_cash`` discharges for a partial cash total.
    """
    proceeds_on_uncertain_basis: Money = Decimal(0)
    """Gross proceeds on those same rows. With :attr:`basis_on_uncertain_basis`, it says how much of
    the sale value has a known cost behind it and how much does not."""
    basis_on_uncertain_basis: Money = Decimal(0)
    """Basis actually established on those rows -- partial, not zero, for a row whose lot was only
    partly uncertain."""
    rows_with_unknown_fees: int = 0
    """Rows carrying :attr:`GainRow.fees_unknown`. Counted separately from
    ``rows_with_uncertain_basis`` -- a row can have a fully known basis and still be in this count,
    or vice versa."""

    @property
    def net_gain(self) -> Decimal:
        return self.short_term_gain + self.long_term_gain


# ---------------------------------------------------------------------------
# Form 8949
# ---------------------------------------------------------------------------


class Form8949Box(StrEnum):
    """Which box the row is reported under.

    Short-term A/B/C and long-term D/E/F. Covered vs noncovered is the broker's basis-reporting
    obligation: equities acquired on or after 2011-01-01 are covered, and every acquisition in this
    dataset postdates that, so A and D are the normal outcome here. B/E and C/F exist for
    transferred-in positions whose basis the receiving broker never received.
    """

    A = "A"
    """Short-term, basis reported to the IRS."""
    B = "B"
    """Short-term, basis NOT reported to the IRS."""
    C = "C"
    """Short-term, not reported on any 1099-B."""
    D = "D"
    """Long-term, basis reported to the IRS."""
    E = "E"
    """Long-term, basis NOT reported to the IRS."""
    F = "F"
    """Long-term, not reported on any 1099-B."""


class Form8949Row(_Frozen):
    """One line of IRS Form 8949, column for column."""

    box: Form8949Box
    description: str
    """Column (a). Quantity and symbol, with no misleading trailing zeros: ``"50 SOXL"``,
    ``"1.4832 NVDA"``. Fractional shares are pervasive here, so the quantity is not an integer."""
    date_acquired: dt.date
    """Column (b). The original acquisition, not a transfer date."""
    date_sold: dt.date
    """Column (c)."""
    proceeds: Money
    """Column (d). Rounded to cents."""
    cost_basis: Money
    """Column (e). Includes any wash-sale adjustment already rolled into the lot."""
    adjustment_code: str | None = None
    """Column (f). ``"W"`` for a wash sale. ``None`` when there is no adjustment."""
    adjustment_amount: Money = Decimal(0)
    """Column (g). Positive for a wash-sale add-back, which reduces the reported loss."""
    gain_loss: Money = Decimal(0)
    """Column (h) = (d) - (e) + (g)."""

    disposal_id: str
    """Not on the form. Kept so every row walks back to a lot and from there to a CSV line."""


class Form8949Report(_Frozen):
    """Form 8949 rows grouped by box, with the subtotals that carry to Schedule D."""

    rows: tuple[Form8949Row, ...] = ()
    short_term_total_proceeds: Money = Decimal(0)
    short_term_total_basis: Money = Decimal(0)
    short_term_total_adjustment: Money = Decimal(0)
    short_term_total_gain: Money = Decimal(0)
    long_term_total_proceeds: Money = Decimal(0)
    long_term_total_basis: Money = Decimal(0)
    long_term_total_adjustment: Money = Decimal(0)
    long_term_total_gain: Money = Decimal(0)

    def rows_for_box(self, box: Form8949Box) -> tuple[Form8949Row, ...]:
        return tuple(row for row in self.rows if row.box is box)


# ---------------------------------------------------------------------------
# 1099-B reconciliation
# ---------------------------------------------------------------------------


class ReconcileStatus(StrEnum):
    MATCHED = "matched"
    AMOUNT_DIFFERS = "amount_differs"
    MISSING_FROM_ENGINE = "missing_from_engine"
    """On the 1099-B, absent from our figures — usually a transaction missing from the export."""
    MISSING_FROM_1099B = "missing_from_1099b"
    """We computed a disposal the broker did not report."""


class ReconcileLine(_Frozen):
    """One security's comparison against a broker 1099-B.

    "Off by $312" is not a finding. This carries the specific security, both sides, and the delta.
    """

    symbol: str
    account_id: str
    term: HoldingTerm
    status: ReconcileStatus

    engine_proceeds: Money = Decimal(0)
    engine_basis: Money = Decimal(0)
    engine_gain: Money = Decimal(0)
    form_proceeds: Money = Decimal(0)
    form_basis: Money = Decimal(0)
    form_gain: Money = Decimal(0)

    disposal_ids: tuple[str, ...] = ()
    note: str | None = None
    """The likely cause where one is identifiable — a missing transfer, an omitted fee.

    English, and the canonical text: it is what logs, tests and any non-localised client read. A
    localised UI prefers :attr:`note_code` and falls back to this."""

    note_code: str | None = None
    """A stable, language-neutral identifier for :attr:`note`'s sentence, so a localised client can
    render its own translation instead of the English ``note``. One of a small closed set
    (``missing_from_engine_webull``, ``missing_from_engine_generic``, ``missing_from_1099b``,
    ``amount_differs_wash_higher``, ``amount_differs_wash_lower``); ``None`` when there is no note.
    The frontend maps it to a catalog key and falls back to ``note`` for an unknown code, so adding a
    code here never has to be matched by a frontend change in the same deploy."""

    note_params: dict[str, str] | None = None
    """The values interpolated into :attr:`note_code`'s sentence (e.g. ``symbol`` and the
    wash-sale ``amount``), so the translation can place them in its own word order rather than
    receiving a pre-composed string."""

    # Serialised, not merely computed. Money crosses this API as a decimal *string* precisely so
    # that no client does arithmetic on it -- which would leave a UI unable to show the one column a
    # reconciliation exists for ("off by how much") without subtracting two strings in IEEE doubles.
    # The subtraction stays here, in Decimal, and the answer travels.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def proceeds_delta(self) -> Decimal:
        return self.engine_proceeds - self.form_proceeds

    @computed_field  # type: ignore[prop-decorator]
    @property
    def basis_delta(self) -> Decimal:
        return self.engine_basis - self.form_basis

    @computed_field  # type: ignore[prop-decorator]
    @property
    def gain_delta(self) -> Decimal:
        return self.engine_gain - self.form_gain


class ReconcileReport(_Frozen):
    """The whole comparison. Clean means every line matched to the cent."""

    lines: tuple[ReconcileLine, ...] = ()
    matched_count: int = 0
    differing_count: int = 0
    total_gain_delta: Money = Decimal(0)

    @property
    def is_clean(self) -> bool:
        return self.differing_count == 0


# ---------------------------------------------------------------------------
# Warnings (display)
# ---------------------------------------------------------------------------


class TaxWarning(_Frozen):
    """One thing the replay or the wash-sale pass could not resolve cleanly, structured for display.

    Mirrors :class:`~app.core.lots.LotWarning` for warnings sourced there, plus the backward
    basis-attachment notes :func:`app.tax.engine._sync_disposals` produces on its own. Kept
    structured -- rather than the single flattened string this used to be -- specifically so the
    Tax page can group occurrences by ``(kind, account_id)`` and show a count instead of one
    ``<li>`` per warning. On a real portfolio that list runs to hundreds of lines for one tax year alone;
    hundreds of individual sentences is not a caveat a reader can absorb, and a plain string list gives the
    frontend no honest way to collapse them short of re-parsing prose.
    """

    kind: str
    """Stable machine token. For a replay-sourced warning this is a
    :class:`~app.core.lots.WarningKind` value (``"oversold"``, ``"missing_basis"``,
    ``"unmatched_transfer_in"``, ``"fees_unknown"``, ...); ``"backward_basis_attachment"`` for the
    wash-sale re-sync notes, which have no ``LotWarning`` of their own."""
    account_id: str | None = None
    broker: str | None = None
    """:class:`~app.core.models.Broker` value, resolved from ``account_id`` where known. Absent when
    the warning has no single account to attribute (none currently do, but the field stays optional
    rather than a lie)."""
    symbol: str | None = None
    trade_date: dt.date | None = None
    detail: str
    """Human-readable, specific -- carries whatever the source warning's own detail said."""


class WarningGroup(_Frozen):
    """Warnings of one ``(kind, account_id)`` pair, collapsed to a count for the headline view.

    The full, ungrouped list still travels on :attr:`TaxReport.warnings` for an expandable detail
    section -- grouping here is about legibility, not about hiding anything.
    """

    kind: str
    account_id: str | None = None
    broker: str | None = None
    count: int
    sample_detail: str
    """One representative message (the first warning in the group), verbatim. Enough to show the
    shape of the problem without repeating it ``count`` times."""


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


class TaxReport(_Frozen):
    """Everything the Tax page needs from one rebuild, for one tax year."""

    tax_year: int
    generated_at: dt.datetime
    gains: GainsReport
    form8949: Form8949Report
    wash_sales: tuple[WashSaleEvent, ...] = ()
    unsettled: tuple[UnsettledPair, ...] = ()
    warnings: tuple[TaxWarning, ...] = ()
    """Every basis/fee gap the replay or wash-sale pass could not resolve, one entry per occurrence
    -- the full, ungrouped detail. See :attr:`warning_groups` for the ``(kind, account)`` counts the
    Tax page leads with."""
    warning_groups: tuple[WarningGroup, ...] = ()
    """:attr:`warnings` collapsed to one row per ``(kind, account_id)``, sorted by count descending.
    What the Tax page renders above the fold; :attr:`warnings` backs the expandable detail."""
    wash_sale_summary: WashSaleSummary | None = None
    """Per-symbol wash-sale aggregation -- see :mod:`app.tax.washsale_summary`. Optional with a
    ``None`` default deliberately: ``TaxReport`` is constructed directly in several tests, and a
    required field would break every one of them."""

    # -----------------------------------------------------------------------
    # Paging metadata for `gains.rows` and `wash_sales` -- see `app.api.tax.report`'s `limit`/
    # `offset` query params. Every field below defaults to "not paginated" (``None``/``0``/``False``)
    # so a `TaxReport` built anywhere that is not that endpoint -- `engine.build_tax_report`, or a
    # test constructing one directly -- is unaffected and reads as a full, unsliced report, exactly
    # as it always has.
    # -----------------------------------------------------------------------

    disposals_total: int = 0
    """Length of the *full* ``gains.rows`` for this year, ignoring ``limit``/``offset`` -- mirrors
    ``app.api.transactions.TransactionPage.total``. Equal to ``len(gains.rows)`` whenever the caller
    did not paginate; only diverges once ``limit`` truncates the list actually returned. A client
    reads this for a count (e.g. the Disposals tab's badge), never ``len(gains.rows)``, so the number
    shown does not shrink to the current page size."""
    wash_events_total: int = 0
    """The ``wash_sales`` analogue of :attr:`disposals_total` -- the count of triggered wash-sale
    events for this year before ``limit``/``offset`` sliced the list actually returned."""
    limit: int | None = None
    """The ``limit`` this response was built with, echoed back so a client holding only the response
    (not the request it made) can tell a page from the whole set. ``None`` -- the default -- means
    neither list below was sliced."""
    offset: int = 0
    """The ``offset`` this response was built with. Applies to *both* :attr:`gains`'s ``rows`` and
    :attr:`wash_sales` identically -- ``GET /api/tax/report`` takes one ``limit``/``offset`` pair,
    not one per list, because the Tax page never needs two different pages of two different lists in
    the same request: only one of its Disposals/Wash sales tabs is ever the active one."""
    disposals_has_more: bool = False
    """Whether ``gains.rows`` has additional rows beyond this page -- ``offset + len(gains.rows) <
    disposals_total``. Always ``False`` when ``limit`` is ``None``, since the whole list came back."""
    wash_events_has_more: bool = False
    """The ``wash_sales`` analogue of :attr:`disposals_has_more`."""

    @property
    def permanent_disallowance_count(self) -> int:
        return sum(1 for event in self.wash_sales if event.permanently_disallowed)
