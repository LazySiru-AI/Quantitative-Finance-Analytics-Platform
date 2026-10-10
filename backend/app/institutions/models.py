"""The wire contract for institutional and fund holdings.

Every module in this package -- the EDGAR client, the two parsers, the delta engine, the API
router, and the TypeScript client that mirrors these shapes -- codes against the types defined
here. They are the seam, so they are defined once, in one place, and changed deliberately.

Three conventions are load-bearing and are enforced by types rather than by comment:

**Money is :class:`~app.core.models.Money`.** A ``Decimal`` that rejects ``float`` at the boundary
and crosses the wire as a decimal string, exactly as every other monetary field in this
application does. EDGAR reports position values large enough that binary floating point is not a
theoretical concern: Berkshire's June 2026 book is $299,253,556,246, which no ``float`` holds
exactly.

**Weights are fractions of one, never percentages.** ``Decimal("0.0914")`` means 9.14%. This
matches `app.config.Settings.ordinary_income_tax_rate`, which rejects a percentage outright
because the one realistic way that field gets misconfigured is typing ``24`` for "24%". A weight
typed as a percentage here would be off by a hundred in every allocation figure on the page.

**A position is identified by CUSIP, never by issuer name.** This is not fastidiousness. Berkshire
reported the same CUSIP ``060505104`` as ``BANK AMERICA CORP`` in the quarter ending 2026-03-31
and as ``BANK OF AMER CORP`` in the quarter ending 2026-06-30. Keying a quarter-over-quarter diff
on the name turns one continuing position into a simultaneous exit and a new buy -- a $27.5bn
fabricated round trip in a single row.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, computed_field

from app.core.models import Money, Quantity

__all__ = [
    "Action",
    "FundRef",
    "Holding",
    "HoldingChange",
    "PortfolioDelta",
    "Snapshot",
    "Source",
]


class _Frozen(BaseModel):
    """The same immutability contract the rest of the application uses."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class Source(StrEnum):
    """Which disclosure a snapshot came from.

    These are **not** interchangeable, and the distinction is surfaced to the reader rather than
    hidden behind a shared table:

    ``THIRTEEN_F``
        Form 13F-HR. What an institutional investment *manager* held in section 13(f) securities
        on the quarter end. Filed within 45 days of quarter end, so it is the timelier of the two.
        It covers US-listed equities and some options only -- no bonds, no cash, no foreign
        listings -- so a 13F is a *slice* of a manager's book, never the whole of it, and its
        weights are weights within that slice.

    ``NPORT``
        Form NPORT-P. What a registered fund -- an ETF -- actually held, filed quarterly with a
        roughly 60 day lag and covering every asset class the fund owns. This is the real
        portfolio of a real ETF, which is what a question about "what is in QQQ" is actually
        asking.

    The two are frequently conflated. An ETF does not file a 13F; its *sponsor* may file one
    covering every account that sponsor manages in aggregate, which is a different portfolio
    belonging to a different entity.
    """

    THIRTEEN_F = "13F"
    NPORT = "NPORT"


class Action(StrEnum):
    """What the holder did to a position between two periods.

    **Classified from the share count alone, never from the value.** A position's value moves when
    the manager trades it *and* when the market reprices it, and only the first is a decision. In
    the two Berkshire quarters this package is tested against, Chevron's disclosed value fell by
    $3.47bn on a share count that did not move by a single share: a value-based classifier calls
    that a large sale, and it was not a sale at all.
    """

    NEW = "new"
    """Absent in the earlier period, present in the later one."""

    EXIT = "exit"
    """Present in the earlier period, absent in the later one."""

    ADD = "add"
    """Share count rose."""

    TRIM = "trim"
    """Share count fell, but did not reach zero."""

    HOLD = "hold"
    """Share count identical. The value may still have moved a great deal."""


class FundRef(_Frozen):
    """Identity of a tracked filer, and the key a URL uses to name it."""

    key: str
    """Stable, URL-safe identifier. The ticker where one exists (``"QQQ"``), otherwise a slug."""

    name: str
    """As disclosed on the filing, not as typed into a watchlist."""

    source: Source

    cik: str
    """Ten digits, zero-padded, no ``CIK`` prefix -- the form every EDGAR endpoint expects."""

    series_id: str | None = None
    """EDGAR series identifier (``S000004310``), for a fund inside a multi-fund trust.

    ``None`` for a 13F manager, which has no series, and for a single-series trust such as the
    SPDR S&P 500 ETF Trust, whose NPORT filings are addressed by CIK alone. A trust like iShares
    Trust files one NPORT-P per series and carries over a thousand of them, so for those the
    series id is the only thing that picks out the right fund.
    """

    ticker: str | None = None
    """The exchange ticker, when the entity is an ETF that has one."""

    principal: str | None = None
    """The person the filer is publicly identified with, where there is one -- "Cathie Wood" for
    ARK Investment Management, "Warren Buffett" for Berkshire Hathaway.

    **Editorial, not disclosed.** Unlike every other field on this model it comes from the watchlist
    rather than from EDGAR, which is why it is separate from :attr:`name` instead of being folded
    into it: `name` is what the filing says, and that property is worth keeping exact. A reader
    thinks in people, and a filer list that reads "Duquesne Family Office LLC" without saying
    Druckenmiller is a list most people cannot use.

    It names the principal, not the trader. A 13F is filed by a firm, and attributing its positions
    to one person is a simplification the UI should present as a label on the firm rather than as a
    claim about who chose each holding.
    """


class Holding(_Frozen):
    """One position, aggregated to a single row per CUSIP.

    A raw 13F information table is **not** one row per position. Berkshire's June 2026 filing
    reports 46 rows covering 9 distinct securities, because a manager files a separate row per
    subsidiary manager holding the same stock -- Ally Financial appears three times. Summing them
    is mandatory; presenting them unaggregated would multiply-count the book.
    """

    cusip: str
    """Nine characters, uppercased. The join key across periods and sources."""

    issuer: str
    """Issuer name exactly as disclosed in *this* period. Display only -- see the module docstring
    on why it must never be used to match a position across periods."""

    value: Money
    """Market value of the position in whole US dollars.

    Normalised by the parser. 13F filings before the 2023-Q1 reporting change expressed this
    column in *thousands*; a filing that predates the change and is read literally understates the
    position by a factor of a thousand.
    """

    shares: Quantity
    """Share count, or principal amount for a debt instrument."""

    weight: Decimal
    """This position's share of the snapshot's total value, as a fraction of one."""

    ticker: str | None = None
    """Exchange ticker, when it could be resolved from the CUSIP.

    ``None`` is the honest and common answer: neither filing carries a ticker, and no free SEC
    endpoint maps CUSIP to ticker. A resolved ticker is a genuine mapping, never a guess, and the
    UI must render the issuer name rather than invent a symbol when this is ``None``.
    """


class Snapshot(_Frozen):
    """One filer's disclosed portfolio as of one period end."""

    fund: FundRef

    period: dt.date
    """The date the holdings are *as of* -- the quarter end for a 13F, ``repPdDate`` for an NPORT.

    Not the filing date, and the two do not even sort the same way. iShares filed an NPORT-P on
    2026-07-13 reporting the period ending 2025-09-30, months after it filed one reporting the
    period ending 2026-03-31. Ordering snapshots by filing date puts a stale report last and makes
    a delta run backwards.
    """

    filed: dt.date

    accession: str
    """EDGAR accession number, dashed. The provenance of every figure in this snapshot."""

    total_value: Money
    """Sum of the holdings' values, as disclosed. The denominator behind every weight."""

    holdings: tuple[Holding, ...]

    value_units_rescaled: bool = False
    """True when the parser judged this filing's ``<value>`` column to be in thousands and
    multiplied it up to whole dollars.

    SEC's 2023-Q1 reporting change made whole dollars mandatory, and
    :func:`app.institutions.parse.parse_13f` scales pre-change filings on that rule alone. Some
    filers did not follow the change. Duquesne Family Office's quarter ending 2026-06-30 reports
    ``tableValueTotal`` of 5,210,860 against 95 positions -- read literally, Stanley Druckenmiller's
    family office holds $5.2 million, and its 72,900 AMD shares are worth $0.58 each on a day AMD
    closed at $517.82. Read as thousands the book is $5.21 billion, which is the right size.

    So the period rule is a prior, not the whole answer, and a filing that still looks mis-scaled
    afterwards is corrected by inspection. This flag exists because that correction is a
    **judgement about someone else's data**, and a page that silently multiplies a disclosed figure
    by a thousand without saying so is doing something the reader would want to know about.
    """

    @property
    def by_cusip(self) -> dict[str, Holding]:
        """The holdings keyed for diffing. Empty dict for an empty snapshot, never ``None``."""
        return {holding.cusip: holding for holding in self.holdings}


class HoldingChange(_Frozen):
    """What happened to one position between two periods."""

    cusip: str
    issuer: str
    ticker: str | None = None
    action: Action

    shares_before: Quantity
    shares_after: Quantity

    shares_delta: Quantity
    """``shares_after - shares_before``. The decision, isolated from the market."""

    shares_pct_change: Decimal | None = None
    """``shares_delta / shares_before`` as a fraction of one. ``None`` for a NEW position, where
    the denominator is zero -- rendered as "new", never as an infinite or a 100% increase."""

    value_before: Money
    value_after: Money

    value_delta: Money
    """``value_after - value_before``. Trading *and* price movement, inseparably."""

    weight_before: Decimal
    weight_after: Decimal

    weight_delta: Decimal
    """Change in the position's share of the portfolio. Rises when the holder buys and when the
    rest of the book falls, which is why it is reported beside the share change and not instead
    of it."""


class PortfolioDelta(_Frozen):
    """Two snapshots of one filer, and the difference between them."""

    fund: FundRef
    from_period: dt.date
    to_period: dt.date
    from_accession: str
    to_accession: str
    total_value_before: Money
    total_value_after: Money
    changes: tuple[HoldingChange, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def median_shares_pct_change(self) -> Decimal | None:
        """Median share change across the positions the holder actually traded.

        One number that separates a stock picker from a fund that simply changed size, and it is
        here because the ``Action`` labels alone cannot. An index ETF does not choose its holdings:
        when money leaves the fund every position is sold down together, and the diff dutifully
        reports a hundred ``TRIM`` rows for what was not a hundred decisions -- or any decision at
        all.

        Measured on the real filings this package reads, the two cases do not overlap:

        ==================  =========  ==============  ==========================
        Filer               changed    median          spread
        ==================  =========  ==============  ==========================
        QQQ (index ETF)     99         -6.07%          75% inside -5% to -7%
        Berkshire (13F)     13         +3.65%          -58.04% to +658.35%
        ==================  =========  ==============  ==========================

        A tight cluster around a single non-zero figure is the signature of fund flows. It is a
        signature, not a proof -- so this exposes the statistic and lets the page say what it
        suggests, rather than returning a verdict this data cannot support.

        ``None`` when nothing was traded. Computed over ``ADD`` and ``TRIM`` only: ``NEW`` has no
        percentage (zero denominator), ``EXIT`` is always exactly -100% and would drag the median
        toward a value that describes the exits rather than the trading, and ``HOLD`` is exactly
        zero by definition and would pull it to zero on any book that mostly sat still.
        """
        traded = sorted(
            change.shares_pct_change
            for change in self.changes
            if change.action in (Action.ADD, Action.TRIM) and change.shares_pct_change is not None
        )
        if not traded:
            return None
        middle = len(traded) // 2
        if len(traded) % 2 == 1:
            return traded[middle]
        return (traded[middle - 1] + traded[middle]) / 2

    @computed_field  # type: ignore[prop-decorator]
    @property
    def counts(self) -> dict[Action, int]:
        """How many positions fell into each action.

        A ``computed_field`` rather than a plain property so it crosses the wire: the summary
        strip at the top of the page is the first thing a reader looks at, and recomputing it in
        TypeScript from the row array would be a second implementation of the same tally, free to
        disagree with this one.

        Every action appears, zeroes included, so a reader can tell "no exits" from "exits were
        not computed".
        """
        tally = dict.fromkeys(Action, 0)
        for change in self.changes:
            tally[change.action] += 1
        return tally
