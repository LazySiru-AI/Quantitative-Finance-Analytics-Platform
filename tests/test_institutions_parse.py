"""Tests for ``app.institutions.parse``.

Every aggregate figure asserted against ``sec_13f_brk_2026q2.xml`` and ``sec_13f_brk_2026q1.xml``
is a real number from a real captured Berkshire Hathaway 13F-HR, summed by hand across the
subsidiary-manager rows for each CUSIP -- that hand-summed aggregation is the point of these tests,
not an incidental assertion. Shapes with no real fixture (the pre-2023 thousands-unit filing,
within-filing issuer drift, a PRN/SH mix) are built as small synthetic documents inline, matching
the real fixtures' namespace and element shape exactly.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.institutions.models import FundRef, Holding, Snapshot, Source
from app.institutions.parse import FilingParseError, parse_13f, parse_nport

#: The NPORT-P namespace, spelled out here rather than imported from the module under test so a
#: typo in the module cannot make these tests agree with it by construction.
_NPORT_NS_FOR_TEST = "http://www.sec.gov/edgar/nport"

FIXTURES = Path(__file__).parent / "fixtures" / "institutions"

BRK = FundRef(key="brk", name="Berkshire Hathaway Inc", source=Source.THIRTEEN_F, cik="0001067983")
IVV = FundRef(
    key="IVV",
    name="iShares Core S&P 500 ETF",
    source=Source.NPORT,
    cik="0001100663",
    series_id="S000004310",
    ticker="IVV",
)


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 13F: aggregation across subsidiary-manager rows
# ---------------------------------------------------------------------------

# CUSIP -> (value, shares, issuer as disclosed in *this* quarter's filing).
Q2_EXPECTED = {
    "02005N100": (Decimal("1240650000"), Decimal("27000000"), "ALLY FINL INC"),
    "02079K107": (Decimal("9606489032"), Decimal("27188433"), "ALPHABET INC"),
    "02079K305": (Decimal("28157599351"), Decimal("78791167"), "ALPHABET INC"),
    "025816109": (Decimal("51282319275"), Decimal("151610700"), "AMERICAN EXPRESS CO"),
    "037833100": (Decimal("65950296923"), Decimal("227917808"), "APPLE INC"),
    "060505104": (Decimal("27543790975"), Decimal("483394015"), "BANK OF AMER CORP"),
    "14040H105": (Decimal("601860000"), Decimal("3000000"), "CAPITAL ONE FINL CORP"),
    "166764100": (Decimal("13986141890"), Decimal("84375856"), "CHEVRON CORPORATION"),
    "191216100": (Decimal("7946163766"), Decimal("97774871"), "COCA COLA CO"),
}

Q1_EXPECTED = {
    "02005N100": (Decimal("1137670000"), Decimal("29000000"), "ALLY FINL INC"),
    "02079K107": (Decimal("1028454775"), Decimal("3585215"), "ALPHABET INC"),
    "02079K305": (Decimal("15600071913"), Decimal("54249798"), "ALPHABET INC"),
    "025816109": (Decimal("45859204536"), Decimal("151610700"), "AMERICAN EXPRESS CO"),
    "037833100": (Decimal("57843260493"), Decimal("227917808"), "APPLE INC"),
    "060505104": (Decimal("25039178044"), Decimal("513624165"), "BANK AMERICA CORP"),
    "14040H105": (Decimal("1304374500"), Decimal("7150000"), "CAPITAL ONE FINL CORP"),
    "166764100": (Decimal("17457364606"), Decimal("84375856"), "CHEVRON CORPORATION"),
    "191216100": (Decimal("6201091980"), Decimal("81539671"), "COCA COLA CO"),
}


def test_parse_13f_q2_aggregates_46_rows_into_9_cusips() -> None:
    snap = parse_13f(
        _read("sec_13f_brk_2026q2.xml"),
        fund=BRK,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="0001193125-26-352200",
    )
    assert len(snap.holdings) == 9
    by_cusip = snap.by_cusip
    for cusip, (value, shares, issuer) in Q2_EXPECTED.items():
        holding = by_cusip[cusip]
        assert holding.value == value
        assert holding.shares == shares
        assert holding.issuer == issuer
        assert holding.ticker is None
    assert snap.total_value == sum(v for v, _, _ in Q2_EXPECTED.values())
    assert snap.period == dt.date(2026, 6, 30)
    assert snap.filed == dt.date(2026, 8, 14)
    assert snap.accession == "0001193125-26-352200"


def test_parse_13f_q1_aggregates_and_shows_pre_drift_issuer_name() -> None:
    snap = parse_13f(
        _read("sec_13f_brk_2026q1.xml"),
        fund=BRK,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 15),
        accession="0001193125-26-226661",
    )
    assert len(snap.holdings) == 9
    by_cusip = snap.by_cusip
    for cusip, (value, shares, issuer) in Q1_EXPECTED.items():
        holding = by_cusip[cusip]
        assert holding.value == value
        assert holding.shares == shares
        assert holding.issuer == issuer
    assert snap.total_value == sum(v for v, _, _ in Q1_EXPECTED.values())

    # Trap 2: same CUSIP, different issuer text across the two quarters -- because each parse call
    # only ever sees one filing, this is not something parse_13f resolves; it is what makes CUSIP,
    # not issuer name, the only safe join key (see models.py's module docstring).
    assert by_cusip["060505104"].issuer == "BANK AMERICA CORP"
    q2 = parse_13f(
        _read("sec_13f_brk_2026q2.xml"),
        fund=BRK,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="0001193125-26-352200",
    )
    assert q2.by_cusip["060505104"].issuer == "BANK OF AMER CORP"


def test_13f_holdings_sorted_by_value_descending_then_cusip() -> None:
    snap = parse_13f(
        _read("sec_13f_brk_2026q2.xml"),
        fund=BRK,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="0001193125-26-352200",
    )
    values = [h.value for h in snap.holdings]
    assert values == sorted(values, reverse=True)


def test_13f_weights_sum_to_approximately_one() -> None:
    snap = parse_13f(
        _read("sec_13f_brk_2026q2.xml"),
        fund=BRK,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="0001193125-26-352200",
    )
    total_weight = sum((h.weight for h in snap.holdings), start=Decimal(0))
    assert abs(total_weight - Decimal(1)) < Decimal("0.0000001")


# ---------------------------------------------------------------------------
# 13F: synthetic documents for shapes no real fixture exercises
# ---------------------------------------------------------------------------

_13F_NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"


def _info_table_doc(rows: str) -> str:
    return f'<informationTable xmlns="{_13F_NS}">{rows}</informationTable>'


def _info_table_row(
    issuer: str,
    cusip: str,
    value: str,
    shares: str,
    ssh_type: str = "SH",
    put_call: str | None = None,
) -> str:
    put_call_xml = f"<putCall>{put_call}</putCall>" if put_call else ""
    return (
        "<infoTable>"
        f"<nameOfIssuer>{issuer}</nameOfIssuer>"
        "<titleOfClass>COM</titleOfClass>"
        f"<cusip>{cusip}</cusip>"
        f"<value>{value}</value>"
        f"<shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt><sshPrnamtType>{ssh_type}</sshPrnamtType></shrsOrPrnAmt>"
        f"{put_call_xml}"
        "<investmentDiscretion>SOLE</investmentDiscretion>"
        "<votingAuthority><Sole>0</Sole><Shared>0</Shared><None>0</None></votingAuthority>"
        "</infoTable>"
    )


def test_13f_value_normalised_from_thousands_before_2023_q1() -> None:
    """Point 3: a filing for a pre-change quarter states <value> in thousands of dollars."""
    xml = _info_table_doc(_info_table_row("OLDCO INC", "123456789", "577211", "12561737"))
    snap = parse_13f(
        xml,
        fund=BRK,
        period=dt.date(2022, 12, 31),
        filed=dt.date(2023, 2, 10),
        accession="0000000000-22-000001",
    )
    assert snap.holdings[0].value == Decimal("577211000")


def test_13f_value_not_scaled_from_2023_q1_onward() -> None:
    xml = _info_table_doc(_info_table_row("NEWCO INC", "123456789", "577211815", "12561737"))
    snap = parse_13f(
        xml,
        fund=BRK,
        period=dt.date(2023, 3, 31),
        filed=dt.date(2023, 5, 10),
        accession="0000000000-23-000001",
    )
    assert snap.holdings[0].value == Decimal("577211815")


def test_13f_within_filing_issuer_drift_keeps_first_occurrence_and_aggregates() -> None:
    """Point 2: two rows for one CUSIP disagreeing on the issuer name must not crash aggregation."""
    xml = _info_table_doc(
        _info_table_row("OLD NAME CORP", "123456789", "100", "10")
        + _info_table_row("NEW NAME CORP", "123456789", "200", "20")
    )
    snap = parse_13f(
        xml,
        fund=BRK,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="0000000000-26-000001",
    )
    assert len(snap.holdings) == 1
    holding = snap.holdings[0]
    assert holding.value == Decimal("300")
    assert holding.shares == Decimal("30")
    assert holding.issuer == "OLD NAME CORP"


def test_13f_prn_row_not_merged_into_share_count() -> None:
    """Point 4: a PRN (principal amount) row must not be summed into a SH group for the same CUSIP."""
    xml = _info_table_doc(
        _info_table_row("EQUITY LEG", "123456789", "1000", "100", ssh_type="SH")
        + _info_table_row("BOND LEG", "123456789", "2000", "50", ssh_type="PRN")
    )
    snap = parse_13f(
        xml,
        fund=BRK,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="0000000000-26-000002",
    )
    assert len(snap.holdings) == 2
    by_cusip = snap.by_cusip
    assert by_cusip["123456789"].shares == Decimal("100")
    assert by_cusip["123456789-PRN"].shares == Decimal("50")


def test_13f_put_option_row_not_merged_into_underlying() -> None:
    """Point 5: a put on an underlying must not merge into the underlying's plain equity row."""
    xml = _info_table_doc(
        _info_table_row("UNDERLYING", "123456789", "1000", "100")
        + _info_table_row("UNDERLYING", "123456789", "500", "200", put_call="PUT")
    )
    snap = parse_13f(
        xml,
        fund=BRK,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="0000000000-26-000003",
    )
    by_cusip = snap.by_cusip
    assert by_cusip["123456789"].shares == Decimal("100")
    assert by_cusip["123456789-PUT"].shares == Decimal("200")


def test_13f_missing_required_element_raises_naming_accession() -> None:
    xml = _info_table_doc(
        "<infoTable><nameOfIssuer>NO CUSIP CORP</nameOfIssuer>"
        "<value>100</value>"
        "<shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>"
        "</infoTable>"
    )
    with pytest.raises(FilingParseError, match="ACC-MISSING-CUSIP") as excinfo:
        parse_13f(
            xml,
            fund=BRK,
            period=dt.date(2026, 6, 30),
            filed=dt.date(2026, 8, 14),
            accession="ACC-MISSING-CUSIP",
        )
    assert "cusip" in str(excinfo.value)


def test_13f_empty_filing_has_zero_total_and_no_division_by_zero() -> None:
    snap = parse_13f(
        _info_table_doc(""),
        fund=BRK,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="0000000000-26-000004",
    )
    assert snap.holdings == ()
    assert snap.total_value == Decimal(0)


def test_13f_malformed_xml_raises_filing_parse_error() -> None:
    with pytest.raises(FilingParseError, match="ACC-BAD-XML"):
        parse_13f(
            "<informationTable><infoTable>",
            fund=BRK,
            period=dt.date(2026, 6, 30),
            filed=dt.date(2026, 8, 14),
            accession="ACC-BAD-XML",
        )


def test_13f_wrong_root_element_raises() -> None:
    with pytest.raises(FilingParseError, match="ACC-WRONG-ROOT"):
        parse_13f(
            "<somethingElse/>",
            fund=BRK,
            period=dt.date(2026, 6, 30),
            filed=dt.date(2026, 8, 14),
            accession="ACC-WRONG-ROOT",
        )


# ---------------------------------------------------------------------------
# NPORT-P
# ---------------------------------------------------------------------------


def test_parse_nport_uses_rep_pd_date_not_rep_pd_end() -> None:
    """Point 6: repPdEnd (fiscal year end) and repPdDate (as-of date) genuinely differ in this
    fixture -- repPdEnd is 2026-03-31 while repPdDate is 2025-09-30."""
    snap = parse_nport(
        _read("sec_nport_ivv_2025-09-30.xml"),
        fund=IVV,
        filed=dt.date(2026, 7, 13),
        accession="0001100663-26-000001",
    )
    assert snap.period == dt.date(2025, 9, 30)
    assert snap.period != dt.date(2026, 3, 31)


def test_parse_nport_2026_q1_holdings_and_weights() -> None:
    snap = parse_nport(
        _read("sec_nport_ivv_2026-03-31.xml"),
        fund=IVV,
        filed=dt.date(2026, 5, 20),
        accession="0001100663-26-000002",
    )
    assert snap.period == dt.date(2026, 3, 31)
    assert len(snap.holdings) == 12
    by_cusip = snap.by_cusip

    oracle = by_cusip["68389X105"]
    assert oracle.value == Decimal("3208351264.89")
    assert oracle.shares == Decimal("21809199.00000000")
    assert oracle.issuer == "Oracle Corp."
    assert oracle.ticker is None

    # Point 7: Snapshot.total_value is the sum of the 12 holdings actually parsed (this trimmed
    # fixture), not the fund's real net assets -- so weight is computed from that local total, and
    # is therefore not equal to the filing's own (differently-scoped) pctVal figure.
    assert snap.total_value == sum((h.value for h in snap.holdings), start=Decimal(0))
    for holding in snap.holdings:
        assert holding.weight == holding.value / snap.total_value


def test_nport_weights_sum_to_approximately_one() -> None:
    snap = parse_nport(
        _read("sec_nport_ivv_2026-03-31.xml"),
        fund=IVV,
        filed=dt.date(2026, 5, 20),
        accession="0001100663-26-000002",
    )
    total_weight = sum((h.weight for h in snap.holdings), start=Decimal(0))
    assert abs(total_weight - Decimal(1)) < Decimal("0.0000001")


def test_nport_row_with_na_cusip_keyed_by_isin_not_dropped() -> None:
    """Point 8: Eaton Corp plc discloses <cusip>N/A</cusip> in this real fixture (Irish issuer, no
    CUSIP) but does carry an ISIN. It must still appear in holdings and count toward total_value."""
    snap = parse_nport(
        _read("sec_nport_ivv_2026-03-31.xml"),
        fund=IVV,
        filed=dt.date(2026, 5, 20),
        accession="0001100663-26-000002",
    )
    eaton = snap.by_cusip["ISIN:IE00B8KQN827"]
    assert eaton.issuer == "Eaton Corp. plc"
    assert eaton.value == Decimal("1786450056.96")


_NPORT_NS = "http://www.sec.gov/edgar/nport"


def _nport_doc(rep_pd_end: str, rep_pd_date: str, rows: str) -> str:
    return (
        f'<edgarSubmission xmlns="{_NPORT_NS}">'
        "<formData><genInfo>"
        f"<repPdEnd>{rep_pd_end}</repPdEnd><repPdDate>{rep_pd_date}</repPdDate>"
        "</genInfo><invstOrSecs>"
        f"{rows}"
        "</invstOrSecs></formData></edgarSubmission>"
    )


def _nport_row(name: str, cusip: str, val_usd: str, balance: str) -> str:
    return (
        "<invstOrSec>"
        f"<name>{name}</name><title>{name}</title><cusip>{cusip}</cusip>"
        f"<balance>{balance}</balance><units>NS</units>"
        f"<valUSD>{val_usd}</valUSD>"
        "</invstOrSec>"
    )


def test_nport_missing_required_element_raises_naming_accession() -> None:
    xml = _nport_doc(
        "2026-03-31",
        "2026-03-31",
        "<invstOrSec><name>NO VALUE CORP</name><cusip>123456789</cusip>"
        "<balance>10</balance></invstOrSec>",
    )
    with pytest.raises(FilingParseError, match="ACC-NPORT-MISSING") as excinfo:
        parse_nport(xml, fund=IVV, filed=dt.date(2026, 5, 20), accession="ACC-NPORT-MISSING")
    assert "valUSD" in str(excinfo.value)


def test_nport_empty_filing_has_zero_total_and_no_division_by_zero() -> None:
    xml = _nport_doc("2026-03-31", "2026-03-31", "")
    snap = parse_nport(xml, fund=IVV, filed=dt.date(2026, 5, 20), accession="ACC-NPORT-EMPTY")
    assert snap.holdings == ()
    assert snap.total_value == Decimal(0)


def test_nport_malformed_xml_raises_filing_parse_error() -> None:
    with pytest.raises(FilingParseError, match="ACC-NPORT-BAD-XML"):
        parse_nport(
            "<edgarSubmission><formData>",
            fund=IVV,
            filed=dt.date(2026, 5, 20),
            accession="ACC-NPORT-BAD-XML",
        )


def test_nport_wrong_root_element_raises() -> None:
    with pytest.raises(FilingParseError, match="ACC-NPORT-WRONG-ROOT"):
        parse_nport(
            "<somethingElse/>",
            fund=IVV,
            filed=dt.date(2026, 5, 20),
            accession="ACC-NPORT-WRONG-ROOT",
        )


# ---------------------------------------------------------------------------
# Money boundary: float is rejected, Decimal is what actually flows through
# ---------------------------------------------------------------------------


def test_holding_rejects_float_value_and_shares() -> None:
    """The contract (app.core.models.Money / Quantity) rejects float at the boundary -- this is
    why every parse in this module builds Decimal directly from the XML text and never routes a
    figure through float. Constructing a Holding with a float proves the rejection is real."""
    with pytest.raises(ValidationError):
        Holding(
            cusip="123456789",
            issuer="FLOAT CORP",
            value=1234.56,  # type: ignore[arg-type]
            shares=Decimal("10"),
            weight=Decimal("1"),
        )
    with pytest.raises(ValidationError):
        Holding(
            cusip="123456789",
            issuer="FLOAT CORP",
            value=Decimal("1234.56"),
            shares=10.0,  # type: ignore[arg-type]
            weight=Decimal("1"),
        )


def test_parsed_holdings_are_genuinely_decimal() -> None:
    snap = parse_13f(
        _read("sec_13f_brk_2026q2.xml"),
        fund=BRK,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="0001193125-26-352200",
    )
    for holding in snap.holdings:
        assert isinstance(holding.value, Decimal)
        assert isinstance(holding.shares, Decimal)
        assert isinstance(holding.weight, Decimal)
    assert isinstance(snap.total_value, Decimal)


class TestNportSentinelIdentifiers:
    """Rows whose identifying fields are all the literal string ``N/A``.

    Found by UAT run 11 against live filings, and reproduced here from the real document. QQQ and
    IVV each hold a CME E-Mini NASDAQ 100 future whose ``<name>``, ``<lei>`` and ``<cusip>`` are
    every one of them ``"N/A"``. Guarding the sentinel on the CUSIP alone let it fall through to
    ``LEI:N/A`` -- a key that identifies nothing and, worse, that a second such row would share.
    """

    def _doc(self, *rows: str) -> bytes:
        body = "".join(rows)
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="{_NPORT_NS_FOR_TEST}">
  <formData>
    <genInfo><repPdEnd>2026-03-31</repPdEnd><repPdDate>2026-03-31</repPdDate></genInfo>
    <invstOrSecs>{body}</invstOrSecs>
  </formData>
</edgarSubmission>""".encode()

    def _row(
        self,
        *,
        name: str,
        lei: str,
        cusip: str,
        title: str = "",
        ticker: str = "",
        value: str = "1000",
        balance: str = "10",
    ) -> str:
        ident = f'<ticker value="{ticker}"/>' if ticker else ""
        title_el = f"<title>{title}</title>" if title else ""
        return (
            f"<invstOrSec><name>{name}</name><lei>{lei}</lei>{title_el}<cusip>{cusip}</cusip>"
            f"<identifiers>{ident}</identifiers><balance>{balance}</balance>"
            f"<valUSD>{value}</valUSD></invstOrSec>"
        )

    def _parse(self, doc: bytes) -> Snapshot:
        return parse_nport(
            doc,
            fund=FundRef(
                key="QQQ", name="Invesco QQQ Trust", source=Source.NPORT, cik="0001067839"
            ),
            filed=dt.date(2026, 5, 28),
            accession="0001067839-26-000024",
        )

    def test_the_futures_row_names_itself_from_title_and_ticker(self) -> None:
        """The exact QQQ row, verbatim from the live filing."""
        snap = self._parse(
            self._doc(
                self._row(
                    name="N/A",
                    lei="N/A",
                    cusip="N/A",
                    title="CME E-Mini NASDAQ 100 Index Future",
                    ticker="NQM6",
                    value="-12012436.80",
                    balance="700",
                )
            )
        )
        holding = snap.holdings[0]
        assert holding.cusip == "TICKER:NQM6"
        assert holding.issuer == "CME E-Mini NASDAQ 100 Index Future"
        assert holding.value == Decimal("-12012436.80")
        assert "N/A" not in holding.cusip
        assert holding.issuer != "N/A"

    def test_two_unidentifiable_rows_never_merge_into_one_position(self) -> None:
        """The reason this is a defect and not a cosmetic issue.

        Under the old resolver both of these keyed on ``LEI:N/A`` and were summed into a single
        holding worth $3,000 that no filing ever reported.
        """
        snap = self._parse(
            self._doc(
                self._row(name="N/A", lei="N/A", cusip="N/A", value="1000", balance="1"),
                self._row(name="N/A", lei="N/A", cusip="N/A", value="2000", balance="2"),
            )
        )
        assert len(snap.holdings) == 2
        assert len({h.cusip for h in snap.holdings}) == 2
        assert sorted(h.value for h in snap.holdings) == [Decimal("1000"), Decimal("2000")]

    def test_a_named_position_without_identifiers_keys_on_its_name(self) -> None:
        """ARK's OpenAI stake: a real $177m holding with a name but no CUSIP, ISIN, ticker or LEI."""
        snap = self._parse(
            self._doc(
                self._row(
                    name="OPENAI GROUP PBC SERIES C",
                    lei="N/A",
                    cusip="N/A",
                    value="177028452.35",
                    balance="1",
                )
            )
        )
        assert snap.holdings[0].cusip == "NAME:OPENAI GROUP PBC SERIES C"
        assert snap.holdings[0].issuer == "OPENAI GROUP PBC SERIES C"

    def test_a_real_cusip_still_wins_over_every_fallback(self) -> None:
        snap = self._parse(
            self._doc(self._row(name="Aflac Inc", lei="549300N0B7DOGLXWPP39", cusip="001055102"))
        )
        assert snap.holdings[0].cusip == "001055102"


class TestFilingsStillReportedInThousands:
    """A 2026 filing whose values are a thousand times too small.

    The 2023-Q1 reporting change made whole dollars mandatory. Not every filer followed it, so the
    period rule alone is not enough. Every figure below is taken verbatim from Duquesne Family
    Office's real 13F-HR for the quarter ending 2026-06-30 (accession 0001536411-26-000006), whose
    `tableValueTotal` reads 5,210,860 across 95 positions.
    """

    def _doc(self, *rows: tuple[str, str, str, str]) -> bytes:
        body = "".join(
            f"<infoTable><nameOfIssuer>{name}</nameOfIssuer><titleOfClass>COM</titleOfClass>"
            f"<cusip>{cusip}</cusip><value>{value}</value>"
            f"<shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt><sshPrnamtType>SH</sshPrnamtType>"
            f"</shrsOrPrnAmt></infoTable>"
            for name, cusip, value, shares in rows
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">'
            f"{body}</informationTable>"
        ).encode()

    def _parse(self, doc: bytes, period: dt.date = dt.date(2026, 6, 30)) -> Snapshot:
        return parse_13f(
            doc,
            fund=FundRef(
                key="DUQUESNE",
                name="Duquesne Family Office LLC",
                source=Source.THIRTEEN_F,
                cik="0001536411",
            ),
            period=period,
            filed=dt.date(2026, 8, 14),
            accession="0001536411-26-000006",
        )

    #: Real rows from that filing: (issuer, cusip, value-as-filed, shares).
    DUQUESNE_ROWS = (
        ("Advanced Micro Devices Inc", "007903107", "42348", "72900"),
        ("10X Genomics Inc", "88025U109", "15455", "403100"),
        ("Alcoa Corp", "013872106", "9679", "185640"),
        ("Adma Biologics Inc", "000899104", "23303", "2784110"),
    )

    def test_a_2026_filing_in_thousands_is_scaled_up_and_says_so(self) -> None:
        """AMD at $0.58 a share on a day it closed at $517.82 is not a price; it is a unit error."""
        snap = self._parse(self._doc(*self.DUQUESNE_ROWS))

        assert snap.value_units_rescaled is True
        amd = snap.by_cusip["007903107"]
        assert amd.value == Decimal("42348000")
        # The implied price is now a plausible one. Read literally it was $0.58.
        assert amd.value / amd.shares == Decimal("42348000") / Decimal("72900")
        assert Decimal("500") < amd.value / amd.shares < Decimal("700")

    def test_a_correctly_scaled_filing_is_left_exactly_alone(self) -> None:
        """Berkshire's real Q2-2026 figures. Nothing here may move by a cent."""
        snap = self._parse(
            self._doc(
                ("APPLE INC", "037833100", "65950296923", "227917808"),
                ("BANK OF AMER CORP", "060505104", "27543790975", "483394015"),
                ("AMERICAN EXPRESS CO", "025816109", "51282319275", "151610700"),
                ("COCA COLA CO", "191216100", "7946163766", "97774871"),
            )
        )
        assert snap.value_units_rescaled is False
        assert snap.by_cusip["037833100"].value == Decimal("65950296923")
        assert snap.total_value == Decimal("152722570939")

    def test_the_pre_2023_period_rule_and_the_check_do_not_both_fire(self) -> None:
        """A genuinely old filing is scaled once by the period rule, not twice.

        The period rule multiplies by a thousand for anything before 2023-Q1; the median check then
        runs on the *scaled* values and must find them plausible, or an old filing would be
        multiplied by a million.
        """
        snap = self._parse(
            self._doc(
                ("APPLE INC", "037833100", "65950296", "227917808"),
                ("BANK OF AMER CORP", "060505104", "27543790", "483394015"),
                ("AMERICAN EXPRESS CO", "025816109", "51282319", "151610700"),
            ),
            period=dt.date(2022, 12, 31),
        )
        assert snap.value_units_rescaled is False
        assert snap.by_cusip["037833100"].value == Decimal("65950296") * 1000

    def test_too_few_priced_rows_is_not_evidence(self) -> None:
        """Two positions are not a book, and a median over them is not a finding."""
        snap = self._parse(
            self._doc(
                ("SOME PENNY CO", "111111111", "5", "100"),
                ("ANOTHER PENNY CO", "222222222", "7", "200"),
            )
        )
        assert snap.value_units_rescaled is False
        assert snap.by_cusip["111111111"].value == Decimal("5")

    def test_a_zero_share_row_cannot_drag_the_median(self) -> None:
        """`value / 0` says nothing, so those rows are excluded rather than treated as free."""
        snap = self._parse(
            self._doc(
                ("APPLE INC", "037833100", "65950296923", "227917808"),
                ("BANK OF AMER CORP", "060505104", "27543790975", "483394015"),
                ("AMERICAN EXPRESS CO", "025816109", "51282319275", "151610700"),
                ("WRITTEN DOWN CO", "333333333", "0", "0"),
            )
        )
        assert snap.value_units_rescaled is False
