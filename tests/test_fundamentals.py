"""Tests for :mod:`app.market.fundamentals`: the annual-duration filter, the amended-filing
dedupe, revenue's two competing XBRL tags, and the never-raise absence path.

``tests/fixtures/market/sec_companyfacts_aapl.json`` is real (trimmed) SEC data and is deliberately
messy in exactly the way production data is messy: it carries a stale ``Revenues`` figure from a
2018 filing alongside a current ``RevenueFromContractWithCustomerExcludingAssessedTax`` figure from
2025, and its ``Revenues`` concept alone carries eleven ``fp="FY"``/``form="10-K"`` entries of which
only three actually span a full fiscal year. Both traps are exercised directly against that fixture
rather than only against constructed data, because a fix that special-cases the constructed shape
would still be wrong against the real one.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from app.market.fundamentals import (
    FundamentalFact,
    Fundamentals,
    _annual_entries,
    build_fundamentals,
)

FIXTURES = Path(__file__).parent / "fixtures" / "market"


def _load_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def _payload(concept: str, entries: list[dict[str, Any]], *, unit: str = "USD") -> dict[str, Any]:
    """A minimal companyfacts-shaped payload carrying one concept's entries."""
    return {
        "cik": 1234567,
        "entityName": "Test Co",
        "facts": {"us-gaap": {concept: {"label": concept, "units": {unit: entries}}}},
    }


def _entry(
    *,
    end: str,
    val: float,
    accn: str,
    filed: str,
    start: str | None = "2023-01-01",
    fp: str = "FY",
    form: str = "10-K",
) -> dict[str, Any]:
    entry: dict[str, Any] = {"end": end, "val": val, "accn": accn, "fy": 2023, "fp": fp, "form": form, "filed": filed}
    if start is not None:
        entry["start"] = start
    return entry


# ---------------------------------------------------------------------------
# The models themselves -- field names are fixed by an already-written TS client.
# ---------------------------------------------------------------------------


class TestModelShape:
    def test_fundamental_fact_has_the_exact_contracted_fields(self) -> None:
        fact = FundamentalFact(
            concept="NetIncomeLoss",
            label="Net income",
            value=1.0,
            unit="USD",
            period_end=dt.date(2024, 1, 1),
            fiscal_period="FY",
            form="10-K",
            accession="0001-24-000001",
        )
        assert fact.model_dump().keys() == {
            "concept",
            "label",
            "value",
            "unit",
            "period_end",
            "fiscal_period",
            "form",
            "accession",
        }

    def test_fundamentals_defaults_to_empty_facts_and_no_reason(self) -> None:
        result = Fundamentals(symbol="TEST")
        assert result.facts == []
        assert result.unavailable_reason is None
        assert result.cik is None
        assert result.entity_name is None


# ---------------------------------------------------------------------------
# Real fixture: the annual-duration filter and the two revenue tags.
# ---------------------------------------------------------------------------


class TestRealAaplFixture:
    def test_curated_concepts_take_the_most_recent_annual_value(self) -> None:
        payload = _load_json("sec_companyfacts_aapl.json")

        result = build_fundamentals(payload, "AAPL")

        assert result.unavailable_reason is None
        assert result.cik == "320193"
        assert result.entity_name == "Apple Inc."
        by_concept = {f.concept: f for f in result.facts}
        assert by_concept["Assets"].value == 359241000000
        assert by_concept["Assets"].period_end == dt.date(2025, 9, 27)
        assert by_concept["Liabilities"].value == 285508000000
        assert by_concept["StockholdersEquity"].value == 73733000000
        assert by_concept["NetIncomeLoss"].value == 112010000000
        assert by_concept["EarningsPerShareDiluted"].value == 7.46
        assert by_concept["CommonStockSharesOutstanding"].value == 14773260000

    def test_revenue_picks_the_tag_with_the_more_recent_period_not_the_first_tag_tried(self) -> None:
        """`Revenues` has data in this fixture (a stale 2018 filing) and is tried first, but
        `RevenueFromContractWithCustomerExcludingAssessedTax` carries the current 2025 figure. A
        fixed try-A-then-B preference would silently report seven-year-old revenue as current."""
        payload = _load_json("sec_companyfacts_aapl.json")

        result = build_fundamentals(payload, "AAPL")

        revenue_facts = [f for f in result.facts if f.label == "Revenue"]
        assert len(revenue_facts) == 1
        revenue = revenue_facts[0]
        assert revenue.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
        assert revenue.value == 416161000000
        assert revenue.period_end == dt.date(2025, 9, 27)

    def test_annual_filter_excludes_quarterly_comparatives_embedded_in_one_10_k(self) -> None:
        """`Revenues` alone carries 11 fp="FY"/form="10-K" entries from a single filing; only 3
        span a full fiscal year (~363-371 days) -- the rest are quarterly comparatives the filing
        happens to tag the same way. `frame` cannot be used to tell them apart: several of the
        quarterly ones lack it too."""
        payload = _load_json("sec_companyfacts_aapl.json")
        gaap = payload["facts"]["us-gaap"]

        annual = _annual_entries(gaap["Revenues"]["units"]["USD"])

        assert {e["end"] for e in annual} == {"2016-09-24", "2017-09-30", "2018-09-29"}
        # The excluded quarterly comparative for Q4 2016 must not appear.
        assert 78351000000 not in {e["val"] for e in annual}


# ---------------------------------------------------------------------------
# Constructed payloads: dedup, revenue fallback, and the never-raise absence path.
# ---------------------------------------------------------------------------


class TestDedupeAcrossAmendedFilings:
    def test_the_latest_filed_entry_wins_on_a_repeated_period(self) -> None:
        entries = [
            _entry(end="2023-12-31", val=100.0, accn="original", filed="2024-02-01"),
            _entry(end="2023-12-31", val=105.0, accn="amended", filed="2024-06-01"),
        ]
        payload = _payload("NetIncomeLoss", entries)

        result = build_fundamentals(payload, "TEST")

        fact = next(f for f in result.facts if f.concept == "NetIncomeLoss")
        assert fact.value == 105.0
        assert fact.accession == "amended"

    def test_an_earlier_filed_date_does_not_override_a_later_one_regardless_of_list_order(self) -> None:
        entries = [
            _entry(end="2023-12-31", val=105.0, accn="amended", filed="2024-06-01"),
            _entry(end="2023-12-31", val=100.0, accn="original", filed="2024-02-01"),
        ]
        payload = _payload("NetIncomeLoss", entries)

        result = build_fundamentals(payload, "TEST")

        fact = next(f for f in result.facts if f.concept == "NetIncomeLoss")
        assert fact.value == 105.0


class TestRevenueFallback:
    def test_falls_back_to_the_contract_tag_when_revenues_is_entirely_absent(self) -> None:
        entries = [_entry(start="2023-01-01", end="2023-12-31", val=500.0, accn="a1", filed="2024-01-01")]
        payload = _payload("RevenueFromContractWithCustomerExcludingAssessedTax", entries)

        result = build_fundamentals(payload, "TEST")

        revenue = next(f for f in result.facts if f.label == "Revenue")
        assert revenue.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
        assert revenue.value == 500.0

    def test_uses_revenues_when_it_is_the_only_tag_present(self) -> None:
        entries = [_entry(start="2023-01-01", end="2023-12-31", val=700.0, accn="a1", filed="2024-01-01")]
        payload = _payload("Revenues", entries)

        result = build_fundamentals(payload, "TEST")

        revenue = next(f for f in result.facts if f.label == "Revenue")
        assert revenue.concept == "Revenues"
        assert revenue.value == 700.0


class TestUnavailableIsAReasonNotAnException:
    def test_missing_us_gaap_block_returns_a_reason_instead_of_raising(self) -> None:
        payload = {"cik": 99, "entityName": "Some ETF Trust", "facts": {}}

        result = build_fundamentals(payload, "QQQ")

        assert result.facts == []
        assert result.unavailable_reason is not None
        assert "ETF" in result.unavailable_reason
        assert result.symbol == "QQQ"
        assert result.entity_name == "Some ETF Trust"

    def test_us_gaap_present_but_no_curated_concepts_returns_a_reason(self) -> None:
        payload = {
            "cik": 3,
            "entityName": "Weird Co",
            "facts": {"us-gaap": {"SomeUnrelatedConcept": {"units": {"USD": []}}}},
        }

        result = build_fundamentals(payload, "WEIRD")

        assert result.facts == []
        assert result.unavailable_reason is not None

    def test_never_raises_for_a_missing_facts_key_entirely(self) -> None:
        payload: dict[str, Any] = {"cik": 4, "entityName": "Bare"}

        result = build_fundamentals(payload, "BARE")

        assert result.facts == []
        assert result.unavailable_reason is not None
