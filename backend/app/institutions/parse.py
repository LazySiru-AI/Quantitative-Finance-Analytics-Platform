"""Turn a raw SEC filing document into a :class:`~app.institutions.models.Snapshot`.

Pure functions only: no network, no HTTP, no filesystem. Everything here operates on an XML
document already in memory (as handed back by ``app.institutions.edgar``) and the small amount of
context the document itself does not carry (which fund it belongs to, and -- for a 13F -- what
period it is *as of*).

Parsed with the standard library's :mod:`xml.etree.ElementTree`. ``lxml`` is not a dependency of
this project and this module must not become the reason it becomes one.

Two document families, two very different shapes, and each hides a trap that this module exists to
avoid. They are enumerated below because each one was reproduced against a real captured filing
before being handled, and the fix is meaningless without the failure it prevents.

**13F information table** (``parse_13f``)

1. *Aggregation is mandatory.* A manager files one ``<infoTable>`` row per subsidiary manager
   holding the same security -- Berkshire's June 2026 filing has 46 rows covering 9 distinct
   CUSIPs, because Ally Financial alone appears three times. Emitting one :class:`Holding` per row
   would triple-count Ally Financial and silently overstate the book by tens of billions of
   dollars. Rows are grouped and summed by CUSIP (see point 4 for the one exception).

2. *Issuer name drift.* CUSIP ``060505104`` is disclosed as ``BANK AMERICA CORP`` in Berkshire's
   quarter ending 2026-03-31 and as ``BANK OF AMER CORP`` in the quarter ending 2026-06-30 -- same
   position, same filer, different text. ``Snapshot.period`` scopes each parse to one filing, so
   cross-period drift is naturally none of this module's business: each call sees only the name(s)
   used in *its own* document. Within a single filing, if two rows for the same CUSIP disagree on
   the name (not observed in a real fixture, but not excludable either -- a manager could correct a
   typo in a later subsidiary-manager row), the first name encountered in document order wins,
   deterministically, rather than raising or silently taking the last.

3. *Value units changed at the 2023-Q1 reporting change.* Before that change, SEC's 13F XML
   technical specification expressed ``<value>`` in **thousands** of dollars; from the quarter
   ending 2023-03-31 onward it is whole dollars. ``Holding.value`` is documented as whole dollars,
   so a pre-change filing read literally understates every position by a factor of 1,000. The
   normalisation is keyed on the **period** (the quarter the holdings are as of), not the filing
   date, because a late or amended filing for an old quarter would otherwise use the wrong scale.
   Both real fixtures captured for this module postdate the change, so this path is exercised with
   a small filing constructed inline in the test suite rather than a captured document.

4. *``sshPrnamtType`` distinguishes shares from principal amount.* ``SH`` means the ``<sshPrnamt>``
   figure is a share count; ``PRN`` means it is the principal amount of a debt instrument -- a
   completely different unit. ``Holding`` has one ``shares`` field for both (by contract, "share
   count, or principal amount for a debt instrument"), so there is no field to record which one a
   given row is. Summing a ``PRN`` row into a ``SH`` group for the same CUSIP would silently add a
   bond's face value to a stock's share count and produce a number that is not a count of anything.
   Instead, a row whose type is not ``SH`` (or that carries a ``<putCall>`` element -- see point 5)
   is grouped and emitted under a CUSIP string suffixed with the type, e.g. ``"12345678-PRN"``,
   never merged with the plain-equity group for that CUSIP. The suffix is visible in the output
   specifically so a caller keying downstream logic on a bare 9-character CUSIP does not
   accidentally match it.

5. *Options carry a ``<putCall>`` element.* A long put or call on an underlying is a different
   instrument from the underlying itself and must not have its contract count merged into the
   underlying's share count -- doing so would, for example, add a bearish put position's contract
   count directly onto a bullish equity position's share count and misstate both. Rows carrying
   ``<putCall>PUT</putCall>`` or ``<putCall>CALL</putCall>`` are kept (not dropped) but grouped
   under a CUSIP suffixed with the option side, by the same mechanism as point 4.

**NPORT-P** (``parse_nport``)

6. *``repPdEnd`` is not the as-of date.* ``repPdEnd`` is the fund's *fiscal* period end;
   ``repPdDate`` is the date the holdings in this specific filing are as of. In the real
   ``sec_nport_ivv_2025-09-30.xml`` fixture, ``repPdEnd`` reads ``2026-03-31`` while ``repPdDate``
   reads ``2025-09-30`` -- an NPORT-P filed for a fiscal year that has not yet ended, reporting a
   quarter from the *previous* fiscal year. ``Snapshot.period`` is built from ``repPdDate``.
   Building it from ``repPdEnd`` would make two genuinely different snapshots (filed months apart,
   covering different quarters) both claim period ``2026-03-31``, which silently collapses them
   into "the same period" for every downstream diff.

7. *``pctVal`` is not used for ``Holding.weight``, and it does not mean what the initial brief for
   this module claimed.* The claim was that ``pctVal`` is already a fraction of one in this
   document. Checked directly against the real ``sec_nport_ivv_2026-03-31.xml`` fixture, that is
   not what the numbers show: Oracle Corp's row there has ``valUSD=3208351264.89`` against the
   filing's own ``netAssets=720543356320.99`` -- a true fraction of ``0.0044527...`` -- while its
   ``pctVal`` reads ``0.445268315465``, exactly 100x larger, for every row checked. So ``pctVal`` in
   this document is a percentage (``0.445268315465`` meaning ``0.445268...%``), not a fraction of
   one, and using it as one directly would overstate every weight by 100x.

   That is not why it is unused here, though -- even correctly rescaled, ``pctVal`` (and computing
   a weight as ``valUSD / netAssets``) expresses a holding's share of the *whole fund's* net assets,
   a quantity that has no field on :class:`~app.institutions.models.Snapshot` and that this parser
   never sees in full: both NPORT fixtures are trimmed to 12 of a genuine S&P 500 ETF's several
   hundred holdings. ``Snapshot.total_value`` is contractually "sum of the holdings' values, as
   disclosed" -- i.e. the sum of what is actually in ``Snapshot.holdings`` -- and ``Holding.weight``
   is "this position's share of the snapshot's total value." For a trimmed document those two
   totals (whole-fund net assets vs. this snapshot's own holdings) are wildly different, so
   ``Holding.weight`` is always computed as ``value / total_value`` from the holdings actually
   parsed, never from ``pctVal``. This is also why the "weights sum to approximately one" test holds
   for a 12-row trimmed fixture: it is true by construction, not because the trimmed subset happens
   to be the whole fund.

8. *Not every row has a usable CUSIP, and the ones that do not say so with a sentinel.*
   ``sec_nport_ivv_2026-03-31.xml`` includes Eaton Corp plc (an Irish-domiciled issuer) with
   ``<cusip>N/A</cusip>``. Dropping such rows would understate ``Snapshot.total_value`` and make
   every other holding's weight overstate its true share. Instead the row is kept and identified by,
   in order: the disclosed CUSIP if it looks real; else the ISIN from
   ``<identifiers><isin value="...">``; else the ``<ticker>`` from the same block; else the LEI;
   else the issuer name; else the row's ordinal. Each fallback carries a prefix (``ISIN:``,
   ``TICKER:``, ``LEI:``, ``NAME:``, ``ROW:``) so it can never coincidentally collide with a genuine
   9-character CUSIP.

   **``"N/A"`` has to be rejected at every step, not only at the CUSIP.** A UAT run found the
   version that guarded only the CUSIP: QQQ and IVV each hold a CME E-Mini NASDAQ 100 future whose
   ``<name>``, ``<lei>`` and ``<cusip>`` are *all* the literal string ``"N/A"``, so it keyed on
   ``LEI:N/A`` and rendered as an issuer named "N/A" holding -$12,012,436.80, badged ``NEW`` and
   styled exactly like an equity purchase. ARK's OpenAI position hit the same branch at $177m.

   The collision matters more than the display. ``LEI:N/A`` is a key two different rows can share,
   and two unidentifiable rows in one filing would be grouped together and their values summed into
   a single position that does not exist. ``ROW:<ordinal>`` is the terminal fallback precisely
   because it cannot collide.

   These rows are not anonymous in the filing, only in the fields first consulted: that future
   carries ``<title>CME E-Mini NASDAQ 100 Index Future</title>`` and
   ``<identifiers><ticker value="NQM6"/></identifiers>``. ``_resolve_nport_issuer`` reads the title
   when ``<name>`` is a sentinel, so the row names itself rather than naming nothing.
"""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from app.institutions.models import FundRef, Holding, Snapshot

__all__ = ["FilingParseError", "parse_13f", "parse_nport"]


class FilingParseError(ValueError):
    """A filing document could not be turned into a :class:`Snapshot`.

    Always names the accession number the malformed document came from -- with two filings often
    parsed back to back in a delta computation, an error that only says "missing <cusip>" leaves no
    way to tell which of the two filings is broken.
    """


_THIRTEENF_NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"
_NPORT_NS = "http://www.sec.gov/edgar/nport"

_THIRTEENF_ROOT_TAG = f"{{{_THIRTEENF_NS}}}informationTable"
_NPORT_ROOT_TAG = f"{{{_NPORT_NS}}}edgarSubmission"

# The 13F value-column unit change took effect for reports with a period of report on or after
# 2023-01-01 (quarter ending 2023-03-31 was the first whole-dollar quarter). See point 3 above.
_THOUSANDS_CUTOVER = dt.date(2023, 1, 1)


def _parse_xml(xml: str | bytes, *, accession: str, kind: str) -> ET.Element:
    """Parse ``xml`` into an :class:`~xml.etree.ElementTree.Element`, never a partial one.

    A ``str`` is encoded to UTF-8 bytes before parsing rather than handed to
    :func:`xml.etree.ElementTree.fromstring` as-is. Both real fixtures for this module begin with
    ``<?xml version="1.0" encoding="UTF-8"?>``, and ``ElementTree.fromstring`` raises
    ``ValueError: Unicode strings with encoding declaration are not supported`` when given a
    ``str`` containing that declaration -- a caller that read a filing as text (the natural thing
    to do, and exactly what ``tests/test_institutions_parse.py`` does via ``Path.read_text``) would
    otherwise hit an unrelated-looking crash on every real document.
    """
    data = xml.encode("utf-8") if isinstance(xml, str) else xml
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise FilingParseError(f"{kind} filing {accession}: could not parse XML ({exc})") from exc


def _required_text(
    elem: ET.Element, local_tag: str, *, ns: str, accession: str, context: str
) -> str:
    """Read a required child element's text, narrowing ``Element | None`` and ``str | None``.

    ``Element.find`` returns ``Element | None`` and ``Element.text`` returns ``str | None`` --
    mypy ``--strict`` rejects using either without a check. Rather than repeat that check (and the
    "empty tag with no text at all" case, which ``.text is None`` alone misses for
    ``<value></value>``) at every call site, it lives here once, and every failure names both the
    accession and the element it went looking for so a malformed filing points straight at the row
    that broke it.
    """
    found = elem.find(f"{{{ns}}}{local_tag}")
    if found is None or found.text is None or not found.text.strip():
        raise FilingParseError(f"{accession}: missing <{local_tag}> in {context}")
    return found.text.strip()


@dataclass
class _Group:
    """Accumulator for rows aggregated into one eventual :class:`Holding`.

    Not part of the public contract -- an internal scratch structure so the aggregation loops in
    ``parse_13f`` and ``parse_nport`` can sum ``value``/``shares`` across rows before constructing
    the (frozen, validated) ``Holding`` exactly once per group.
    """

    key: str
    issuer: str
    value: Decimal
    shares: Decimal


def _finish_snapshot(
    groups: dict[str, _Group],
    order: list[str],
    *,
    fund: FundRef,
    period: dt.date,
    filed: dt.date,
    accession: str,
    value_units_rescaled: bool = False,
) -> Snapshot:
    """Turn accumulated groups into a sorted, weighted :class:`Snapshot`.

    Shared by both parsers so the zero-denominator guard and the sort order are defined in exactly
    one place. ``total_value`` can legitimately be zero -- a filer that reports no section 13(f)
    securities this quarter is a real, if unusual, filing, not a parse failure -- and computing
    ``value / total_value`` unconditionally would raise ``DivisionByZero`` on exactly that filing.
    """
    total_value = sum((groups[key].value for key in order), start=Decimal(0))

    def _weight(value: Decimal) -> Decimal:
        return value / total_value if total_value != 0 else Decimal(0)

    holdings = tuple(
        sorted(
            (
                Holding(
                    cusip=groups[key].key,
                    issuer=groups[key].issuer,
                    value=groups[key].value,
                    shares=groups[key].shares,
                    weight=_weight(groups[key].value),
                    ticker=None,
                )
                for key in order
            ),
            # Value descending, then CUSIP ascending: a snapshot's holding order is reproducible
            # from the same input every time, and the largest positions -- the ones a reader looks
            # at first -- sort to the top without the UI needing its own sort.
            key=lambda h: (-h.value, h.cusip),
        )
    )
    return Snapshot(
        fund=fund,
        period=period,
        filed=filed,
        accession=accession,
        total_value=total_value,
        holdings=holdings,
        value_units_rescaled=value_units_rescaled,
    )


#: A median implied price below this, across a whole 13F book, is taken as evidence that the filing
#: reports thousands rather than whole dollars. See :func:`_looks_like_thousands`.
_IMPLIED_PRICE_FLOOR = Decimal("1.00")

#: Below this many priced rows the median is not a sample worth reasoning from.
_MIN_ROWS_FOR_SCALE_CHECK = 3


def _looks_like_thousands(groups: dict[str, _Group], order: list[str]) -> bool:
    """Whether this filing's values are a thousand times too small to be whole dollars.

    The 2023-Q1 reporting change made whole dollars mandatory, and :func:`parse_13f` scales filings
    that predate it on that rule alone. **Some filers did not follow the change**, so the rule is a
    prior rather than the whole answer, and a filing that still looks wrong afterwards is caught
    here.

    The test is the implied price per share, ``value / shares``, which for a correctly scaled filing
    is simply the quarter-end price of each holding. Taking the median across the book makes it
    robust to a few odd rows. Duquesne Family Office's quarter ending 2026-06-30 reports 72,900 AMD
    shares at a value of ``42348``: read as whole dollars that is $0.58 a share on a day AMD closed
    at $517.82, and read as thousands it is $580.90. Its whole book reads $5.2 million instead of
    the $5.21 billion it is.

    The floor is $1.00 because the gap between the two readings is three orders of magnitude, not a
    near thing: a mis-scaled book implies prices in cents, while a real 13F book -- which covers
    exchange-listed section 13(f) securities only -- has a median share price in the tens or
    hundreds of dollars. A book whose *median* holding trades under a dollar is not something this
    filing type produces.

    Deliberately conservative in three ways, because rescaling someone else's disclosed figure by a
    thousand is not a small thing to do on a guess:

    * only rows with a positive share count contribute, since ``value / 0`` says nothing;
    * option and principal-amount rows are excluded by their suffixed keys -- a bond's "price" per
      unit of principal is not a share price and would drag the median toward zero;
    * fewer than :data:`_MIN_ROWS_FOR_SCALE_CHECK` priced rows returns ``False``, because a median
      over one or two positions is not evidence.
    """
    prices: list[Decimal] = []
    for key in order:
        # A suffixed key marks a PRN or option row (see points 4 and 5 of the module docstring),
        # whose "price" is not a share price.
        if "-" in groups[key].key:
            continue
        shares = groups[key].shares
        if shares > 0:
            prices.append(groups[key].value / shares)

    if len(prices) < _MIN_ROWS_FOR_SCALE_CHECK:
        return False

    prices.sort()
    middle = len(prices) // 2
    median = prices[middle] if len(prices) % 2 == 1 else (prices[middle - 1] + prices[middle]) / 2
    return median < _IMPLIED_PRICE_FLOOR


def parse_13f(
    xml: str | bytes,
    *,
    fund: FundRef,
    period: dt.date,
    filed: dt.date,
    accession: str,
) -> Snapshot:
    """Parse a Form 13F-HR information table into a :class:`Snapshot`.

    ``period`` is a required keyword argument, not derived from ``xml``. A 13F information table
    (``<informationTable>``, the document this function receives) has no period-of-report element
    at all -- that date lives on the filing's separate cover page / primary document XML, which is
    a different file this function never sees. Both real fixtures captured for this module
    (``sec_13f_brk_2026q1.xml``, ``sec_13f_brk_2026q2.xml``) confirm this: their root element is
    ``<informationTable>`` and nothing in the document states what quarter it is for. The caller
    (the EDGAR client, which already knows the period from the filing index it fetched this
    document through) must supply it -- and must supply it correctly, since ``period`` also decides
    the thousands-vs-whole-dollars normalisation in point 3 of the module docstring.

    Raises :class:`FilingParseError` -- naming ``accession`` -- on malformed XML, a document whose
    root is not a ``13F`` ``<informationTable>``, or a row missing any of ``nameOfIssuer``,
    ``cusip``, ``value``, ``sshPrnamt``, or ``sshPrnamtType``. Never returns a ``Snapshot`` built
    from a partially-read document.
    """
    root = _parse_xml(xml, accession=accession, kind="13F")
    if root.tag != _THIRTEENF_ROOT_TAG:
        raise FilingParseError(
            f"13F filing {accession}: root element {root.tag!r} is not "
            f"<informationTable xmlns={_THIRTEENF_NS!r}> -- wrong document or namespace"
        )

    groups: dict[str, _Group] = {}
    order: list[str] = []

    for i, info_table in enumerate(root.findall(f"{{{_THIRTEENF_NS}}}infoTable")):
        row = f"infoTable[{i}]"
        issuer = _required_text(
            info_table, "nameOfIssuer", ns=_THIRTEENF_NS, accession=accession, context=row
        )
        row = f"infoTable[{i}] ({issuer})"

        cusip = _required_text(
            info_table, "cusip", ns=_THIRTEENF_NS, accession=accession, context=row
        ).upper()
        if len(cusip) != 9:
            raise FilingParseError(
                f"13F filing {accession}: {row} cusip {cusip!r} is not 9 characters"
            )

        value_text = _required_text(
            info_table, "value", ns=_THIRTEENF_NS, accession=accession, context=row
        )

        shrs_elem = info_table.find(f"{{{_THIRTEENF_NS}}}shrsOrPrnAmt")
        if shrs_elem is None:
            raise FilingParseError(f"13F filing {accession}: missing <shrsOrPrnAmt> in {row}")
        shares_text = _required_text(
            shrs_elem,
            "sshPrnamt",
            ns=_THIRTEENF_NS,
            accession=accession,
            context=f"{row} shrsOrPrnAmt",
        )
        ssh_type = _required_text(
            shrs_elem,
            "sshPrnamtType",
            ns=_THIRTEENF_NS,
            accession=accession,
            context=f"{row} shrsOrPrnAmt",
        ).upper()

        put_call_elem = info_table.find(f"{{{_THIRTEENF_NS}}}putCall")
        put_call = None
        if put_call_elem is not None and put_call_elem.text and put_call_elem.text.strip():
            put_call = put_call_elem.text.strip().upper()

        value = Decimal(value_text)
        if period < _THOUSANDS_CUTOVER:
            value *= Decimal(1000)
        shares = Decimal(shares_text)

        # Points 4 and 5 of the module docstring: a non-SH row and/or an option leg must never be
        # summed into the plain-equity group for this CUSIP, so it gets a suffixed key instead.
        suffix_parts = [part for part in (ssh_type if ssh_type != "SH" else None, put_call) if part]
        key = cusip if not suffix_parts else f"{cusip}-{'-'.join(suffix_parts)}"

        if key not in groups:
            groups[key] = _Group(key=key, issuer=issuer, value=Decimal(0), shares=Decimal(0))
            order.append(key)
        group = groups[key]
        group.value += value
        group.shares += shares

    # The period rule above is a prior, not a verdict -- see `_looks_like_thousands` for the
    # real 2026 filing that still reports thousands and would otherwise be shown at a
    # thousandth of its size.
    rescaled = _looks_like_thousands(groups, order)
    if rescaled:
        for key in order:
            groups[key].value *= Decimal(1000)

    return _finish_snapshot(
        groups,
        order,
        fund=fund,
        period=period,
        filed=filed,
        accession=accession,
        value_units_rescaled=rescaled,
    )


#: Values that appear where an identifier should be but identify nothing. ``N/A`` is what NPORT-P
#: actually writes for a position that has no CUSIP, no LEI and no issuer name -- an exchange-traded
#: future, most often -- and it appears in *every* such field on the row at once.
_NPORT_NULL_TOKENS: Final[frozenset[str]] = frozenset({"N/A", "NA", "NONE", "-", ""})


def _usable(value: str | None) -> str | None:
    """The value, stripped and uppercased, or ``None`` if it identifies nothing."""
    if value is None:
        return None
    candidate = value.strip().upper()
    if candidate in _NPORT_NULL_TOKENS or set(candidate) <= {"0"}:
        return None
    return candidate


def _resolve_nport_key(sec: ET.Element, *, name: str, ordinal: int) -> str:
    """Pick the join key for one ``<invstOrSec>`` row. See point 8 of the module docstring.

    Falls through CUSIP, ISIN, ticker, LEI, then issuer name -- and never raises, because a row
    this parser cannot cleanly identify is still a real position with real value; refusing to parse
    the whole filing over one such row (or silently dropping just that row) is worse than keying it
    on the least-bad identifier available and saying so via the prefix.

    **Every step tests the ``N/A`` sentinel, not just emptiness.** Guarding only the CUSIP shipped a
    real defect: QQQ and IVV each hold a CME E-Mini NASDAQ 100 future whose ``<name>``, ``<lei>``
    *and* ``<cusip>`` are all the literal string ``"N/A"``, so the row keyed on ``LEI:N/A`` and
    rendered as an issuer called "N/A" holding -$12,012,436.80 -- badged ``NEW``, styled exactly
    like an equity purchase. ARK's OpenAI stake hit the same branch at $177m.

    Worse than the display: ``LEI:N/A`` is a *shared* key. Two unidentifiable rows in one filing
    would land in the same group and have their values summed into a single fabricated position.
    Hence ``ordinal`` -- the row's index within the document, used only when nothing else
    identifies it, which cannot collide with another row by construction.

    The filing is not actually silent about these positions; it just answers in different fields.
    That future carries ``<title>CME E-Mini NASDAQ 100 Index Future</title>`` and
    ``<identifiers><ticker value="NQM6"/></identifiers>``. Reading those is why the row now names
    itself instead of naming nothing.
    """
    cusip = _usable(sec.findtext(f"{{{_NPORT_NS}}}cusip"))
    if cusip is not None and len(cusip) == 9:
        return cusip

    identifiers = sec.find(f"{{{_NPORT_NS}}}identifiers")
    if identifiers is not None:
        isin_elem = identifiers.find(f"{{{_NPORT_NS}}}isin")
        if isin_elem is not None:
            isin = _usable(isin_elem.get("value"))
            if isin is not None:
                return f"ISIN:{isin}"

        # Ahead of the LEI: a ticker names the instrument, while an LEI names the *counterparty*
        # or issuing entity, which is not the same thing for a derivative.
        ticker_elem = identifiers.find(f"{{{_NPORT_NS}}}ticker")
        if ticker_elem is not None:
            ticker = _usable(ticker_elem.get("value"))
            if ticker is not None:
                return f"TICKER:{ticker}"

    lei = _usable(sec.findtext(f"{{{_NPORT_NS}}}lei"))
    if lei is not None:
        return f"LEI:{lei}"

    resolved_name = _usable(name)
    if resolved_name is not None:
        return f"NAME:{resolved_name}"

    return f"ROW:{ordinal}"


def _resolve_nport_issuer(sec: ET.Element, *, fallback: str) -> str:
    """The human-readable name for one row.

    ``<name>`` is the issuer and is normally what a reader wants. When it is the ``N/A`` sentinel,
    ``<title>`` carries the instrument's own description -- "CME E-Mini NASDAQ 100 Index Future"
    rather than a column reading "N/A" beside a twelve-million-dollar figure. Falling back to the
    resolved key last means the row always names *something* a person can look up.
    """
    name = _usable(sec.findtext(f"{{{_NPORT_NS}}}name"))
    if name is not None:
        return (sec.findtext(f"{{{_NPORT_NS}}}name") or "").strip()

    title = sec.findtext(f"{{{_NPORT_NS}}}title")
    if _usable(title) is not None:
        return (title or "").strip()

    return fallback


def parse_nport(
    xml: str | bytes,
    *,
    fund: FundRef,
    filed: dt.date,
    accession: str,
) -> Snapshot:
    """Parse a Form NPORT-P filing into a :class:`Snapshot`.

    ``period`` is not a parameter here, unlike ``parse_13f`` -- unlike a 13F information table, an
    NPORT-P document states its own as-of date in ``<repPdDate>``, and per point 6 of the module
    docstring that is the field to trust, not the fiscal-year ``<repPdEnd>`` that sits next to it.

    Raises :class:`FilingParseError` -- naming ``accession`` -- on malformed XML, a document whose
    root is not an NPORT ``<edgarSubmission>``, a missing ``<genInfo>``/``<repPdDate>``, or an
    ``<invstOrSec>`` row missing ``name``, ``valUSD``, or ``balance``. Never returns a ``Snapshot``
    built from a partially-read document.
    """
    root = _parse_xml(xml, accession=accession, kind="NPORT")
    if root.tag != _NPORT_ROOT_TAG:
        raise FilingParseError(
            f"NPORT filing {accession}: root element {root.tag!r} is not "
            f"<edgarSubmission xmlns={_NPORT_NS!r}> -- wrong document or namespace"
        )

    gen_info = root.find(f".//{{{_NPORT_NS}}}genInfo")
    if gen_info is None:
        raise FilingParseError(f"NPORT filing {accession}: missing <genInfo>")
    rep_pd_date_text = _required_text(
        gen_info, "repPdDate", ns=_NPORT_NS, accession=accession, context="genInfo"
    )
    period = dt.date.fromisoformat(rep_pd_date_text)

    groups: dict[str, _Group] = {}
    order: list[str] = []

    invst_or_secs = root.find(f".//{{{_NPORT_NS}}}invstOrSecs")
    rows = [] if invst_or_secs is None else invst_or_secs.findall(f"{{{_NPORT_NS}}}invstOrSec")

    for i, sec in enumerate(rows):
        context = f"invstOrSec[{i}]"
        name = _required_text(sec, "name", ns=_NPORT_NS, accession=accession, context=context)
        context = f"invstOrSec[{i}] ({name})"
        value_text = _required_text(
            sec, "valUSD", ns=_NPORT_NS, accession=accession, context=context
        )
        balance_text = _required_text(
            sec, "balance", ns=_NPORT_NS, accession=accession, context=context
        )

        key = _resolve_nport_key(sec, name=name, ordinal=i)
        issuer = _resolve_nport_issuer(sec, fallback=key)
        value = Decimal(value_text)
        shares = Decimal(balance_text)

        # NPORT does not exhibit 13F's subsidiary-manager duplication (each security is one lot
        # line, not one line per co-manager), but grouping defensively costs nothing and protects
        # against the same security appearing under two rows for some other reason (e.g. two lots).
        if key not in groups:
            groups[key] = _Group(key=key, issuer=issuer, value=Decimal(0), shares=Decimal(0))
            order.append(key)
        group = groups[key]
        group.value += value
        group.shares += shares

    return _finish_snapshot(
        groups, order, fund=fund, period=period, filed=filed, accession=accession
    )
