"""Reported financials, extracted from SEC EDGAR's XBRL company-facts payload.

The model shape here is fixed by an already-written TypeScript client -- field names below are not
negotiable. What *is* this module's job is turning SEC's `companyfacts` JSON, which is a raw XBRL
dump with every historical restatement still in it, into one curated, deduplicated figure per
concept.

Two properties of the SEC data make that non-trivial, and both are handled in :func:`_annual_entries`
and :func:`_dedupe_latest_filed` rather than left for a caller to rediscover:

1. **The same fact is repeated across filings.** A 10-Q reports the prior comparable quarter every
   time it reports the current one, and a later annual report restates prior-year figures again for
   comparison. The same ``(concept, period_end, fiscal_period)`` can therefore appear with several
   different ``accn``/``filed`` values; the latest ``filed`` wins, because a later filing is either
   identical or a correction.

2. **``fp == "FY"`` does not mean "this entry covers a full fiscal year."** Inside a single 10-K's
   XBRL, SEC tags *every* comparative figure the filing shows -- prior quarters, prior years -- with
   the filing's own ``fp``/``form`` (``FY``/``10-K``), because those fields describe the filing, not
   the period the individual fact covers. AAPL's ``Revenues`` concept alone carries eleven such
   entries from one 10-K, of which only three are genuinely annual; the rest are quarterly
   comparatives with a `frame` value like ``CY2017Q1``. The only reliable signal is measuring the
   fact's own ``(end - start)`` and requiring it to span close to a year -- ``frame`` is absent on
   many of the quarterly ones too, so it cannot be used as the filter.

Revenue is reported under two different XBRL tags depending on when a filer adopted ASC 606: legacy
``Revenues`` or ``RevenueFromContractWithCustomerExcludingAssessedTax``. Picking only one silently
drops revenue for roughly half the filers in this universe -- and a filer that *switched* tags mid
history (most did, around 2018) has real annual data under both, at different times. Preferring one
tag categorically is therefore not enough either: AAPL's own company facts carry a stale 2018 figure
under ``Revenues`` and the current 2025 figure under the ASC 606 tag, and a strategy that always
tries ``Revenues`` first would silently report seven-year-old revenue as current. The correct
comparison is across both tags' candidates by ``period_end``, not a fixed preference order -- see
:func:`_most_recent_fact`.

Absence is not an error. Most of this portfolio is ETFs, which file N-CEN/N-PORT rather than the
10-K/10-Q financial statements XBRL covers, so "no fundamentals" is the *expected* answer for most
symbols this module will ever see. :func:`build_fundamentals` therefore never raises for a missing
concept or a missing filer -- it returns a :class:`Fundamentals` with an empty ``facts`` list and a
human-readable ``unavailable_reason``. An absence with a reason is something the UI can render; an
exception is something it has to work around.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

from pydantic import BaseModel, Field

__all__ = ["FundamentalFact", "Fundamentals", "build_fundamentals"]


class FundamentalFact(BaseModel):
    """One reported figure: a concept, its most recent annual value, and where it came from."""

    concept: str
    """The us-gaap XBRL tag, e.g. ``NetIncomeLoss`` -- the tag actually present in the filing, not a
    normalised label. Revenue may hold either of two tags; see the module docstring."""
    label: str
    value: float
    unit: str
    period_end: dt.date
    fiscal_period: str
    form: str
    accession: str


class Fundamentals(BaseModel):
    """A symbol's curated financials, or a stated reason there are none."""

    symbol: str
    cik: str | None = None
    entity_name: str | None = None
    facts: list[FundamentalFact] = Field(default_factory=list)
    unavailable_reason: str | None = None


#: Human labels for each curated concept. Revenue's two alternative tags share one label -- the UI
#: shows "Revenue" regardless of which ASC 606 vintage the filer used.
CONCEPT_LABELS: Final[dict[str, str]] = {
    "Assets": "Total assets",
    "Liabilities": "Total liabilities",
    "StockholdersEquity": "Stockholders' equity",
    "NetIncomeLoss": "Net income",
    "EarningsPerShareDiluted": "Diluted EPS",
    "CommonStockSharesOutstanding": "Shares outstanding",
    "Revenues": "Revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "Revenue",
}

#: Concepts with exactly one XBRL tag each.
_SIMPLE_CONCEPTS: Final[tuple[str, ...]] = (
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "NetIncomeLoss",
    "EarningsPerShareDiluted",
    "CommonStockSharesOutstanding",
)

#: Revenue's two possible tags. Both are searched and the more recent annual figure wins -- never
#: both added together, they are alternative spellings of the same figure, but never a fixed
#: preference order either, since a filer's own history can carry recent data under one tag and
#: only stale data under the other.
_REVENUE_CONCEPTS: Final[tuple[str, ...]] = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
)

#: A duration is treated as "a fiscal year" once it clears 300 days. Real annual periods in this
#: data run 363-371 days (52- or 53-week fiscal calendars); the quarterly comparatives that also
#: carry fp="FY" run under 100 days. 300 sits comfortably in the gap between the two.
_ANNUAL_MIN_DAYS: Final[int] = 300


def _annual_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entries from one concept's unit list that genuinely cover a full fiscal year.

    Restricting to ``form == "10-K"`` and ``fp == "FY"`` is necessary but not sufficient -- see the
    module docstring. Instant facts (balance-sheet figures like ``Assets``) have no ``start`` and are
    kept as-is once the form/fp filter passes; duration facts (income-statement figures) additionally
    need their own span checked.
    """
    annual: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("form") != "10-K" or entry.get("fp") != "FY":
            continue
        start = entry.get("start")
        if start is None:
            annual.append(entry)
            continue
        span = (dt.date.fromisoformat(entry["end"]) - dt.date.fromisoformat(start)).days
        if span >= _ANNUAL_MIN_DAYS:
            annual.append(entry)
    return annual


def _dedupe_latest_filed(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated reports of the same period to the one from the latest filing."""
    latest_by_end: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = entry["end"]
        current = latest_by_end.get(key)
        if current is None or entry.get("filed", "") > current.get("filed", ""):
            latest_by_end[key] = entry
    return list(latest_by_end.values())


def _most_recent_fact(gaap: dict[str, Any], concepts: tuple[str, ...]) -> tuple[str, dict[str, Any]] | None:
    """The most recent annual figure across one or more alternative XBRL tags for the same figure.

    Takes a tuple rather than a single concept so revenue's two tags can compete on ``period_end``
    rather than on which is checked first -- see the module docstring for why a fixed preference
    order silently picks a stale value when a filer switched tags mid-history. Returns the winning
    concept name alongside the entry, since the caller needs to know which tag actually produced it.
    """
    best: tuple[str, dict[str, Any]] | None = None
    for concept in concepts:
        tag = gaap.get(concept)
        if not tag:
            continue
        for unit, entries in tag.get("units", {}).items():
            candidates = _dedupe_latest_filed(_annual_entries(entries))
            if not candidates:
                continue
            candidate = max(candidates, key=lambda e: e["end"])
            if best is None or candidate["end"] > best[1]["end"]:
                best = (concept, {**candidate, "unit": unit})
    return best


def _to_fact(concept: str, entry: dict[str, Any]) -> FundamentalFact:
    return FundamentalFact(
        concept=concept,
        label=CONCEPT_LABELS[concept],
        value=float(entry["val"]),
        unit=entry["unit"],
        period_end=dt.date.fromisoformat(entry["end"]),
        fiscal_period=entry["fp"],
        form=entry["form"],
        accession=entry["accn"],
    )


def build_fundamentals(payload: dict[str, Any], symbol: str) -> Fundamentals:
    """Extract the curated concept set from a raw SEC ``companyfacts`` payload.

    Never raises: a filer with no ``us-gaap`` block (funds, foreign private issuers on IFRS) or one
    that simply lacks all curated concepts gets an empty ``facts`` list and a stated reason, not an
    exception. See the module docstring for why that distinction matters here specifically.
    """
    cik = payload.get("cik")
    cik_str = str(cik) if cik is not None else None
    entity_name = payload.get("entityName")
    gaap: dict[str, Any] = payload.get("facts", {}).get("us-gaap", {})

    if not gaap:
        return Fundamentals(
            symbol=symbol,
            cik=cik_str,
            entity_name=entity_name,
            unavailable_reason=(
                f"SEC has no us-gaap XBRL facts for {symbol}. This is the expected result for "
                "most of this portfolio, which is ETFs: funds file N-CEN/N-PORT, not the 10-K/"
                "10-Q financial statements this endpoint reads."
            ),
        )

    facts: list[FundamentalFact] = []
    for concept in _SIMPLE_CONCEPTS:
        found = _most_recent_fact(gaap, (concept,))
        if found is not None:
            facts.append(_to_fact(*found))

    revenue = _most_recent_fact(gaap, _REVENUE_CONCEPTS)
    if revenue is not None:
        facts.append(_to_fact(*revenue))

    if not facts:
        return Fundamentals(
            symbol=symbol,
            cik=cik_str,
            entity_name=entity_name,
            unavailable_reason=(
                f"SEC has us-gaap facts for {symbol} but none of the curated concepts "
                f"({', '.join(_SIMPLE_CONCEPTS)}, revenue) appear in them."
            ),
        )

    return Fundamentals(symbol=symbol, cik=cik_str, entity_name=entity_name, facts=facts)
