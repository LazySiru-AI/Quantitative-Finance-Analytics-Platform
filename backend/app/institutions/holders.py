"""Which tracked filers hold one symbol -- the reverse of "what does this filer hold".

Every existing institutions surface answers the question fund-first: pick a filer, see its book,
see what changed. The persona runs kept asking the other question and finding no way to ask it --
*"which of the filers I track hold NVDA?"* -- and
`uat/feedback/BACKLOG.md` names it twice as the largest unbuilt thing those runs surfaced.

**Matching is on CUSIP, and on nothing else.** A 13F carries a CUSIP and
an issuer name; it does not carry a ticker. `app.institutions.catalog.ledger_cusip_tickers` resolves
CUSIPs to tickers from the user's own ledger, and that mapping is the only bridge that exists.

**So this can only answer for symbols the user has actually traded**, and that limitation is
reported rather than hidden: `HoldersResult.symbol_resolved` is `False` when the symbol resolved to
no CUSIP, which makes an empty `holders` list mean "could not look" rather than "nobody holds it".
Asked for AAPL against a ledger that has never held it, this returns nothing while VTI, VOO and IVV
all certainly hold it -- an honest answer, and a sharp one.

Matching on `Holding.ticker` was tried and removed as unreachable: `load_latest` resolves tickers
through `catalog.apply_tickers` using the *same* `ledger_cusip_tickers` mapping, so a holding carries
a ticker exactly when its CUSIP is already in the match set. It could never add a row.

Issuer-name matching is refused outright: the same company is disclosed as "NVIDIA CORP", "NVIDIA
CORPORATION" and "Nvidia Corp" by different filers in one quarter, and
`app.institutions.models.Holding.issuer`'s own docstring warns it must never be used to match a
position. A near-miss would silently attribute someone else's position to a symbol.

**A fund that could not be read is reported, not skipped, and that is the whole point of
`unchecked`.** This walks up to twenty-odd filers, each an EDGAR fetch. If three of them time out
and the answer comes back "no tracked filer holds NVDA", that sentence is false -- it means "none of
the nineteen I could read". A reverse lookup whose failure mode is a *confident empty list* is worse
than one that is simply slow, because the reader cannot tell the two apart. So every fund that fails
is named with its reason, and the caller is told how many of how many were actually checked.

**Cost.** Cold, this is one EDGAR round-trip per tracked filer. `app.institutions.service.build_client`
puts a six-hour HTTP cache in front of that, so the first call after a cache miss is slow -- seconds,
not milliseconds -- and the rest are cheap. That is why this is a synchronous GET on a page the
reader has already chosen to open, and why nothing calls it on a hot path.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from app.config import Settings
from app.institutions import catalog, service
from app.institutions.edgar import EdgarClient
from app.institutions.models import FundRef, Snapshot


@dataclass(frozen=True)
class Holder:
    """One tracked filer's position in the requested symbol."""

    key: str
    name: str
    period: dt.date
    """The period the holdings are as of -- a quarter end, not the filing date."""
    filed: dt.date
    accession: str
    cusip: str
    issuer: str
    """As disclosed by *this* filer. Two filers spell the same company differently; both are shown
    as filed rather than normalised, because normalising would hide that they disagree."""
    shares: Decimal
    value: Decimal
    weight: Decimal
    """The position's share of that filer's disclosed book, as a fraction of one."""
    value_units_rescaled: bool
    """Carried through from the snapshot. A filing whose value column was judged to be in thousands
    and multiplied up is a judgement about someone else's data, and a row derived from one must say
    so -- see `Snapshot.value_units_rescaled`."""


@dataclass(frozen=True)
class Unchecked:
    """A tracked filer whose latest filing could not be read, and why.

    Present so an empty `holders` list cannot be mistaken for "nobody holds it".
    """

    key: str
    name: str
    reason: str


@dataclass(frozen=True)
class HoldersResult:
    symbol: str
    cusips: tuple[str, ...]
    """The CUSIPs the symbol resolved to, from the user's own ledger. Empty means the symbol could
    not be resolved to any CUSIP at all, which is reported rather than treated as "no holders" --
    see `matched_by`."""
    symbol_resolved: bool
    """Whether the symbol resolved to any CUSIP in the user's ledger at all.

    **Load-bearing for reading an empty `holders` list.** ``False`` means the symbol never resolved
    to a CUSIP, so nothing could have matched and the empty list carries no information about who
    holds what. ``True`` with an empty list is the real "none of them hold it"."""
    holders: tuple[Holder, ...]
    unchecked: tuple[Unchecked, ...]
    checked: int
    total: int


def _symbol_cusips(settings: Settings, symbol: str) -> tuple[str, ...]:
    """Every CUSIP the user's own ledger maps to this ticker.

    Plural deliberately: a ticker can change hands between issuers over a long ledger, and the
    mapping is built from what the user actually traded rather than from a reference source.
    """
    wanted = symbol.strip().upper()
    return tuple(
        sorted(
            cusip
            for cusip, ticker in catalog.ledger_cusip_tickers(settings).items()
            if ticker.upper() == wanted
        )
    )


def find_holders(
    symbol: str,
    *,
    settings: Settings,
    client: EdgarClient | None = None,
    as_of: dt.date | None = None,
    funds: tuple[FundRef, ...] | None = None,
) -> HoldersResult:
    """Walk every tracked filer's latest filing and report which ones hold ``symbol``.

    ``as_of`` bounds the search the same way `app.institutions.service.load_latest` does -- on
    **filing date**, so a filing that became public after the bound is not consulted. This exists
    for the UAT harness's no-lookahead guarantee, which is otherwise blind to a live SEC fetch; see
    `uat/README.md`.

    ``funds`` overrides the catalog, for tests. ``client`` likewise -- one client is reused across
    every fund so they share the cache rather than each opening their own.
    """
    wanted = symbol.strip().upper()
    if not wanted:
        raise ValueError("symbol must not be blank")

    cusips = frozenset(_symbol_cusips(settings, wanted))
    tracked = funds if funds is not None else catalog.default_catalog()
    # Not closed afterwards, and not wrapped in `try/finally`: `EdgarClient` exposes no `close`, and
    # the two existing routes in `app.api.institutions` build one per request and let it go the same
    # way. Adding a lifecycle here that the class does not have would be inventing an interface.
    client = client or service.build_client(settings)

    holders: list[Holder] = []
    unchecked: list[Unchecked] = []

    for fund in tracked:
        try:
            snapshot = service.load_latest(fund, client=client, settings=settings, as_of=as_of)
        except Exception as exc:
            # Deliberately broad. Every fund this cannot read must appear in `unchecked`, and the
            # set of exceptions reachable here spans the network layer, the EDGAR listing, the
            # filing parser and "this filer has no filing before the as-of bound". Letting one
            # escape would abort the whole walk and lose the funds already gathered; naming each
            # exception type instead would silently drop whichever one was forgotten.
            unchecked.append(
                Unchecked(key=fund.key, name=fund.name, reason=f"{type(exc).__name__}: {exc}")
            )
            continue
        _collect(snapshot, cusips, holders)

    holders.sort(key=lambda h: h.value, reverse=True)

    return HoldersResult(
        symbol=wanted,
        cusips=tuple(sorted(cusips)),
        symbol_resolved=bool(cusips),
        holders=tuple(holders),
        unchecked=tuple(unchecked),
        checked=len(tracked) - len(unchecked),
        total=len(tracked),
    )


def _collect(snapshot: Snapshot, cusips: frozenset[str], into: list[Holder]) -> None:
    """Append this snapshot's matching positions.

    A filer can disclose the same company under more than one CUSIP (a class A and a class B line,
    for instance), so every match is appended rather than the first one winning.
    """
    for holding in snapshot.holdings:
        if holding.cusip.upper() not in cusips:
            continue
        into.append(
            Holder(
                key=snapshot.fund.key,
                name=snapshot.fund.name,
                period=snapshot.period,
                filed=snapshot.filed,
                accession=snapshot.accession,
                cusip=holding.cusip,
                issuer=holding.issuer,
                shares=Decimal(holding.shares),
                value=Decimal(holding.value),
                weight=Decimal(holding.weight),
                value_units_rescaled=snapshot.value_units_rescaled,
            )
        )
