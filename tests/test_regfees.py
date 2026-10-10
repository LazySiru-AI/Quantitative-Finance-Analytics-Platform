"""Tests for :mod:`app.core.regfees` -- the SEC Section 31 + FINRA TAF fee reconstruction.

The rates are the published FY2026 / calendar-2026 schedules (see the module docstring for the
primary sources). These tests pin both the arithmetic and the effective-date boundaries, since a
sale one day either side of an effective date incurs a materially different fee.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.core.regfees import finra_taf_fee, regulatory_sell_fee, sec_section31_fee


class TestSecSection31Fee:
    def test_zero_before_the_fy2026_effective_date(self) -> None:
        # The FY2026 order sets $0.00 per $1e6 for covered sales through 2026-04-03.
        assert sec_section31_fee(Decimal("100000"), dt.date(2026, 4, 3)) == Decimal("0.00")
        assert sec_section31_fee(Decimal("100000"), dt.date(2026, 1, 20)) == Decimal("0.00")

    def test_rate_applies_on_and_after_2026_04_04(self) -> None:
        # $20.60 per $1,000,000 = 0.0000206 x proceeds. $1,000,000 x 0.0000206 = $20.60 exactly.
        assert sec_section31_fee(Decimal("1000000"), dt.date(2026, 4, 4)) == Decimal("20.60")

    def test_rounds_up_to_the_cent(self) -> None:
        # 10,000 x 0.0000206 = 0.206 -> rounds up to 0.21 (broker/SIFMA convention on the SEC fee).
        assert sec_section31_fee(Decimal("10000"), dt.date(2026, 5, 1)) == Decimal("0.21")
        # A tiny but positive fee still rounds up to a cent, never down to zero.
        assert sec_section31_fee(Decimal("1"), dt.date(2026, 5, 1)) == Decimal("0.01")

    def test_non_positive_proceeds_is_zero(self) -> None:
        assert sec_section31_fee(Decimal("0"), dt.date(2026, 5, 1)) == Decimal("0.00")
        assert sec_section31_fee(Decimal("-100"), dt.date(2026, 5, 1)) == Decimal("0.00")


class TestFinraTafFee:
    def test_rate_on_and_after_2026_01_01(self) -> None:
        # 0.000195 per share. 1000 shares -> 0.195 -> 0.20 (nearest cent).
        assert finra_taf_fee(Decimal("1000"), dt.date(2026, 1, 1)) == Decimal("0.20")

    def test_prior_rate_before_2026(self) -> None:
        # The immediately-prior published rate, 0.000166 per share. 1000 -> 0.166 -> 0.17.
        assert finra_taf_fee(Decimal("1000"), dt.date(2025, 12, 31)) == Decimal("0.17")

    def test_one_cent_floor(self) -> None:
        # A handful of shares computes to a fraction of a cent and is floored at $0.01.
        assert finra_taf_fee(Decimal("10"), dt.date(2026, 6, 1)) == Decimal("0.01")
        assert finra_taf_fee(Decimal("1"), dt.date(2026, 6, 1)) == Decimal("0.01")

    def test_cap_binds_only_on_a_very_large_block(self) -> None:
        # 0.000195 x 1,000,000 shares = $195, clamped to the $9.79 per-trade cap.
        assert finra_taf_fee(Decimal("1000000"), dt.date(2026, 6, 1)) == Decimal("9.79")

    def test_non_positive_shares_is_zero(self) -> None:
        assert finra_taf_fee(Decimal("0"), dt.date(2026, 6, 1)) == Decimal("0.00")


class TestRegulatorySellFee:
    def test_sums_both_components_after_the_sec_date(self) -> None:
        # 500 shares sold for $10,000 on 2026-05-01:
        #   SEC = ceil(10000 x 0.0000206) = ceil(0.206) = 0.21
        #   TAF = round(500 x 0.000195) = round(0.0975) = 0.10
        fee = regulatory_sell_fee(
            proceeds=Decimal("10000"), shares=Decimal("500"), trade_date=dt.date(2026, 5, 1)
        )
        assert fee == Decimal("0.31")

    def test_before_the_sec_date_only_taf_applies(self) -> None:
        # Same sale on 2026-02-01: SEC is $0.00, so only the TAF floor remains.
        fee = regulatory_sell_fee(
            proceeds=Decimal("600"), shares=Decimal("25"), trade_date=dt.date(2026, 2, 1)
        )
        assert fee == Decimal("0.01")
