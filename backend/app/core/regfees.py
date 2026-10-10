"""Reconstruct the regulatory pass-through fees a broker export omits.

Webull's *Orders Records* export has no fee column at all, so every sale it produces reaches the
ledger with ``fees = 0`` -- the absence of the datum, not a measurement that no fee was charged
(see :class:`app.core.lots.WarningKind.FEES_UNKNOWN`). But the two fees that are actually charged on
a sale of a US equity are not broker-discretionary: they are fixed pass-throughs set by published
rate schedules, so the fee a given sale incurred is recoverable from its *trade date*, *share count*
and *proceeds* even when the export dropped the column. This module is that reconstruction.

Two fees apply, **on sales only** (a purchase incurs neither):

* **SEC Section 31 fee** -- a fraction of the dollar *proceeds*. The rate is reset by the SEC each
  fiscal year and, in a year where prior collections already met the target, sits at ``$0.00`` for
  the first part of the year until a mid-year order raises it.
* **FINRA Trading Activity Fee (TAF)** -- a flat amount *per share*, with a ``$0.01`` minimum and a
  per-trade cap that only a very large block would reach.

Rates encoded here, verified 2026-09-05 against the primary sources:

* SEC Section 31, fiscal year 2026: **$0.00 per $1,000,000** of covered sales with a trade date
  **before 2026-04-04**, and **$20.60 per $1,000,000** (i.e. ``0.0000206`` x proceeds) on or after
  **2026-04-04**. (SEC FY2026 fee-rate order, eff. 2026-04-04, per SEC Fee
  Rate Advisory 2026-2 and FINRA Information Notice 03/17/26; the $0.00 pre-April period is stated
  verbatim in that order.) Rounded **up** to the cent, matching the SIFMA/broker convention for
  passing the SEC fee through on a confirmation -- the aim is to reproduce the fee Webull actually
  charged, not to minimise it.
* FINRA TAF, sales of covered equity: **$0.000195 per share** on or after **2026-01-01** (raised
  from ``0.000166``; FINRA rule filing SR-FINRA-2024-xxx, Federal Register 2024-11-27). ``$0.01``
  minimum, rounded to the nearest cent. Per-trade cap ``$9.79`` (Webull's published schedule); it
  binds only above ~50,000 shares in a single sale and never on this ledger, but is applied for
  completeness.

The module is calibrated to the 2026 fiscal schedule because that is the window every trade in this
ledger falls in. For a trade dated before 2026 the immediately-prior published rate is used (SEC
Section 31 was likewise $0.00 through early 2026, and TAF was ``0.000166``); this keeps an older
paper-trade fixture from getting a nonsense fee rather than pretending to know rates further back.

Everything here is derived, never stored, and is intentionally a documented *estimate*: the exact
cent a broker printed can differ by a rounding step. It is applied in place of ``fees = 0`` so a
Webull sale's gain is netted of the fee that was really charged instead of overstated by it, and the
substitution is surfaced as :class:`app.core.lots.WarningKind.FEES_ESTIMATED` so the provenance is
never silent.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

__all__ = ["finra_taf_fee", "regulatory_sell_fee", "sec_section31_fee"]

_CENT = Decimal("0.01")

#: SEC Section 31 fee, expressed as a rate per dollar of proceeds, effective on/after the given date.
#: The FY2026 order set $0.00 for covered sales through 2026-04-03 and $20.60/$1e6 from 2026-04-04.
_SEC_EFFECTIVE_DATE = dt.date(2026, 4, 4)
_SEC_RATE_ON_OR_AFTER = Decimal("0.0000206")  # $20.60 per $1,000,000
_SEC_RATE_BEFORE = Decimal("0")  # $0.00 per $1,000,000 for FY2026 sales before 2026-04-04

#: FINRA Trading Activity Fee, per share, on sales of covered equity.
_TAF_EFFECTIVE_DATE = dt.date(2026, 1, 1)
_TAF_RATE_ON_OR_AFTER = Decimal("0.000195")
_TAF_RATE_BEFORE = Decimal("0.000166")  # the immediately-prior published rate
_TAF_MIN = Decimal("0.01")
_TAF_MAX = Decimal("9.79")  # Webull's published per-trade cap; never binds on this ledger


def sec_section31_fee(proceeds: Decimal, trade_date: dt.date) -> Decimal:
    """The SEC Section 31 fee on a sale of ``proceeds`` dollars, rounded up to the cent.

    Zero for a non-positive proceeds figure and for any FY2026 sale before 2026-04-04.
    """
    if proceeds <= 0:
        return Decimal("0.00")
    rate = _SEC_RATE_ON_OR_AFTER if trade_date >= _SEC_EFFECTIVE_DATE else _SEC_RATE_BEFORE
    raw = proceeds * rate
    if raw <= 0:
        return Decimal("0.00")
    return raw.quantize(_CENT, rounding=ROUND_CEILING)


def finra_taf_fee(shares: Decimal, trade_date: dt.date) -> Decimal:
    """The FINRA Trading Activity Fee on a sale of ``shares`` shares.

    Rounded to the nearest cent, floored at ``$0.01`` and capped at the per-trade maximum. Zero for a
    non-positive share count.
    """
    if shares <= 0:
        return Decimal("0.00")
    rate = _TAF_RATE_ON_OR_AFTER if trade_date >= _TAF_EFFECTIVE_DATE else _TAF_RATE_BEFORE
    fee = (shares * rate).quantize(_CENT, rounding=ROUND_HALF_UP)
    if fee < _TAF_MIN:
        fee = _TAF_MIN
    if fee > _TAF_MAX:
        fee = _TAF_MAX
    return fee


def regulatory_sell_fee(*, proceeds: Decimal, shares: Decimal, trade_date: dt.date) -> Decimal:
    """Total reconstructed regulatory fee on a sale: SEC Section 31 + FINRA TAF.

    Both components are sales-only pass-throughs; a caller applies this only to a ``SELL``. The
    result is a non-negative, cent-quantized :class:`~decimal.Decimal`.
    """
    return sec_section31_fee(proceeds, trade_date) + finra_taf_fee(shares, trade_date)
