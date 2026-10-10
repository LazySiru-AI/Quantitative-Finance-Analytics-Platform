"""Cross-institution consensus: across every tracked filer, which positions were bought and sold
the most in their latest disclosed change.

Every other surface in this package answers a fund-first question -- pick a filer, see its book.
This one flips it: walk all twenty-two tracked filers' latest deltas (see
:func:`app.institutions.service.load_delta`) and rank positions by how many of them moved the same
way. Four things make that harder than "loop and sum", and each is handled explicitly rather than
left as a silent assumption:

**1. Double counting a sponsor that files two ways.** ``ARKINVEST`` (a 13F, Cathie Wood's aggregate
book across every account ARK Investment Management LLC advises) and ``ARKK`` (an NPORT-P, one of
those very accounts) can disclose the same underlying trade twice -- once from the manager's side,
once from the fund's own. Counting both as independent "buyers" of the same CUSIP inflates
``buyer_count``/``seller_count`` for a name ARK holds, for no reason but that ARK discloses it
through two SEC forms. The rule here (:data:`_SUBORDINATE_TO_AUTHORITATIVE`): when both halves of a
known-overlapping pair are present in this run's ``checked`` set *and* both moved the **same CUSIP
on the same side** (both buying, or both selling), the subordinate filer's (``ARKK``) move on that
one CUSIP is dropped from the vote and only the authoritative filer's (``ARKINVEST``) counts.
Every other CUSIP either fund moved alone still counts for that fund alone -- this is a per-position
collapse, not "drop ARKK from the catalog", because ARKINVEST's aggregate book holds names ARKK does
not and ARKK's NPORT can in principle disclose something the aggregate does not yet reflect. Opposite
-side moves on the same CUSIP (one buying, one selling) are left alone rather than suppressed: that
divergence is either real information about how the accounts differ, or noise this module has no
basis to silently resolve in either direction, and it would be wrong to hide it either way. See
:func:`_suppress_sponsor_overlap`. The mapping is extensible -- a future sponsor with the same
13F/NPORT overlap is a new entry, not a new code path.

**2. Filers report different quarters.** Twenty-two filers do not all file on the same day, so "this
quarter's consensus" spanning one manager's Q2 delta and another's Q3 delta is not one consensus --
it is two overlaid and presented as one if the spread is hidden. This module never normalises
periods together. Every :class:`FundMove` carries its own ``period`` -- the *to* period of the
delta it came from -- verbatim, so a reader (or the UI) can see at a glance that a row's movers span
more than one quarter rather than being told a single implied "as of" date that would be false for
some of them.

**3. A $2bn book and a $300bn book are not comparable on dollars.** Ranking primarily on summed
weight or value would let Berkshire's $299bn book outvote ten smaller managers single-handedly on
sheer size, which is not "consensus" in any useful sense -- it is "what did the biggest filer do".
Both ``buys`` and ``sells`` are therefore ranked **primarily on how many distinct funds moved a
position the same way** (:attr:`ConsensusRow.buyer_count` / :attr:`ConsensusRow.seller_count`) --
a vote count, one filer one vote -- with ``total_weight_delta`` (the sum of ``weight_delta`` over
only the funds on that ranking's side) used purely as the tie-break when two positions have the same
vote count. See :func:`_sorted_rows`.

**4. A filer this module could not read is not a filer that held still.** Every fund in
:func:`app.institutions.catalog.default_catalog` is walked, and one that raises -- a network
failure, a filing that will not parse, too little history for a delta -- is recorded in
``unchecked`` with its reason rather than silently skipped, the same contract
:mod:`app.institutions.holders` established first. ``buyer_count``/``seller_count`` are counts over
``checked`` only, and ``checked``/``unchecked``/``total`` all travel with the response so a reader
can see the denominator behind every vote count, not just the numerator.

**Caching.** Walking twenty-two filers is twenty-two EDGAR round trips even when each one is
individually warm behind :func:`app.institutions.service.build_client`'s six-hour HTTP cache --
unacceptable cost for a page load. :func:`build_consensus` therefore materialises the *computed*
response to a JSON file under ``settings.cache_dir / "institutions_consensus"``, keyed by ``as_of``
and ``limit``, and serves that file back rather than recomputing, unless ``refresh=True`` or the
cached ``generated_at`` is older than :data:`_CACHE_TTL_SECONDS`. That TTL is set to exactly the
same six hours as the EDGAR HTTP cache in :mod:`app.institutions.service`
(``service._CACHE_TTL_SECONDS``) on purpose: refreshing this derived response more often than the
underlying per-fund fetch can actually change would only re-derive the same numbers from the same
still-cached upstream responses at the cost of twenty-two round trips for nothing, and letting it
sit stale for longer risks quietly serving a consensus EDGAR has since moved past. A 13F/NPORT filer
does not file more than quarterly, so six hours of staleness on this page is a non-event next to
that cadence.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.core.models import Quantity
from app.institutions import catalog, service
from app.institutions.edgar import EdgarClient
from app.institutions.models import Action, FundRef, HoldingChange, PortfolioDelta, Source

__all__ = [
    "ConsensusResponse",
    "ConsensusRow",
    "FundMove",
    "UncheckedFund",
    "build_consensus",
]

_BUY_ACTIONS: frozenset[Action] = frozenset({Action.NEW, Action.ADD})
_SELL_ACTIONS: frozenset[Action] = frozenset({Action.EXIT, Action.TRIM})

#: Sponsor pairs where the same underlying position can be disclosed through two different tracked
#: filer keys -- see the module docstring's point 1. ``{subordinate_key: authoritative_key}``: when
#: both keys are present in this run's ``checked`` set and both moved the same CUSIP on the same
#: side, the subordinate's move on that one CUSIP is dropped and only the authoritative filer's
#: counts. Add a pair here when a new sponsor's overlap is confirmed; the suppression logic itself
#: (:func:`_suppress_sponsor_overlap`) never names ARK specifically.
_SUBORDINATE_TO_AUTHORITATIVE: dict[str, str] = {
    "ARKK": "ARKINVEST",
}

#: Matches `app.institutions.service._CACHE_TTL_SECONDS` -- see the module docstring's "Caching"
#: paragraph for why this derived cache should not outlive, or refresh faster than, the upstream one.
_CACHE_TTL_SECONDS = 6 * 3600.0

#: Bumped whenever `ConsensusResponse`'s shape changes in a way an old cached file would not survive
#: `model_validate_json` against, or would validate into silently wrong data.
_CACHE_VERSION = "v1"


class UncheckedFund(BaseModel):
    """A tracked filer whose latest delta could not be computed, and why.

    Same shape as `app.api.institutions.UncheckedFund` by design -- not imported from it, because
    `app.institutions` is a lower layer than `app.api` and importing "up" would invert that. See the
    module docstring's point 4 on why this must never be collapsed into a silently smaller
    `checked` count.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    name: str
    reason: str


class FundMove(BaseModel):
    """One fund's contribution to a `ConsensusRow` -- one CUSIP, one filer, one delta."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    name: str
    principal: str | None
    action: Action
    weight_delta: Decimal
    shares_delta: Quantity
    period: dt.date
    """The filing period *this fund's* move came from -- the `to_period` of its delta. Not
    normalised against any other fund's period; see the module docstring's point 2."""
    source: Source


class ConsensusRow(BaseModel):
    """One position, ranked by how many tracked filers moved it the same way.

    `buyer_count` and `seller_count` are both counts across every checked fund regardless of which
    list (`ConsensusResponse.buys` or `.sells`) this row appears in -- a row ranked among the buys
    still shows how many funds were selling the same name in the same window. `movers` likewise
    lists every checked fund that moved this CUSIP, buyers and sellers together, sorted by fund key
    for a deterministic order independent of ranking. `total_weight_delta` is the one field that is
    *not* symmetric: it sums `weight_delta` only over the funds on the side this particular row is
    ranked on -- the buying funds when the row sits in `buys`, the selling funds when it sits in
    `sells` -- see the module docstring's point 3 on why it is a tie-break, not the primary rank.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cusip: str
    issuer: str
    ticker: str | None
    buyer_count: int
    seller_count: int
    net_funds: int
    total_weight_delta: Decimal
    movers: list[FundMove]


class ConsensusResponse(BaseModel):
    """Cross-institution consensus across every tracked filer's latest delta."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    generated_at: dt.datetime
    as_of: dt.date | None
    checked: list[str]
    unchecked: list[UncheckedFund]
    buys: list[ConsensusRow]
    sells: list[ConsensusRow]


# ---------------------------------------------------------------------------
# Walking the catalog
# ---------------------------------------------------------------------------


def _load_deltas(
    funds: tuple[FundRef, ...],
    *,
    client: EdgarClient,
    settings: Settings,
    as_of: dt.date | None,
) -> tuple[list[str], list[UncheckedFund], dict[str, PortfolioDelta]]:
    """Walk every fund, computing its delta. Never lets one fund's failure abort the walk.

    Deliberately broad `except Exception`, matching `app.institutions.holders.find_holders`: the
    set of exceptions reachable through `service.load_delta` spans the network layer, the EDGAR
    listing, the filing parser and "too little history to diff", and naming each type here would be
    one more place a future exception type is silently forgotten and escapes the walk instead of
    landing in `unchecked`.
    """
    checked: list[str] = []
    unchecked: list[UncheckedFund] = []
    deltas: dict[str, PortfolioDelta] = {}

    for fund in funds:
        try:
            deltas[fund.key] = service.load_delta(fund, client=client, settings=settings, as_of=as_of)
        except Exception as exc:
            unchecked.append(
                UncheckedFund(key=fund.key, name=fund.name, reason=f"{type(exc).__name__}: {exc}")
            )
            continue
        checked.append(fund.key)

    return checked, unchecked, deltas


# ---------------------------------------------------------------------------
# Moves: one (fund, change, period) triple per qualifying position change
# ---------------------------------------------------------------------------


def _all_moves(
    deltas: dict[str, PortfolioDelta],
) -> list[tuple[FundRef, HoldingChange, dt.date]]:
    """Every `ADD`/`TRIM`/`NEW`/`EXIT` change across every checked fund's delta.

    `HOLD` is filtered out here, at the source, so nothing downstream of this function ever has to
    remember to exclude it -- see the module docstring and models.py's `Action.HOLD` docstring: a
    `HOLD` is exactly no decision, and must never appear on either side of the response.
    """
    moves: list[tuple[FundRef, HoldingChange, dt.date]] = []
    for delta in deltas.values():
        for change in delta.changes:
            if change.action in _BUY_ACTIONS or change.action in _SELL_ACTIONS:
                moves.append((delta.fund, change, delta.to_period))
    return moves


def _suppress_sponsor_overlap(
    moves: list[tuple[FundRef, HoldingChange, dt.date]],
) -> list[tuple[FundRef, HoldingChange, dt.date]]:
    """Drop a subordinate sponsor's move on a CUSIP its authoritative pair also moved, same side.

    See the module docstring's point 1 and :data:`_SUBORDINATE_TO_AUTHORITATIVE`. Symmetric-safe by
    construction: only ever removes the subordinate's entry, never the authoritative one, so a
    sponsor pair present in `checked` but not overlapping on a given CUSIP is entirely unaffected.
    """
    side_by_fund_cusip: dict[tuple[str, str], bool] = {}
    for fund, change, _period in moves:
        side_by_fund_cusip[(fund.key, change.cusip)] = change.action in _BUY_ACTIONS

    def is_suppressed(fund_key: str, cusip: str) -> bool:
        authoritative = _SUBORDINATE_TO_AUTHORITATIVE.get(fund_key)
        if authoritative is None:
            return False
        auth_is_buy = side_by_fund_cusip.get((authoritative, cusip))
        if auth_is_buy is None:
            return False
        sub_is_buy = side_by_fund_cusip[(fund_key, cusip)]
        return auth_is_buy == sub_is_buy

    return [
        (fund, change, period)
        for fund, change, period in moves
        if not is_suppressed(fund.key, change.cusip)
    ]


# ---------------------------------------------------------------------------
# Grouping into rows and ranking
# ---------------------------------------------------------------------------


def _fund_move(fund: FundRef, change: HoldingChange, period: dt.date) -> FundMove:
    return FundMove(
        key=fund.key,
        name=fund.name,
        principal=fund.principal,
        action=change.action,
        weight_delta=change.weight_delta,
        shares_delta=change.shares_delta,
        period=period,
        source=fund.source,
    )


def _build_row(
    cusip: str, entries: list[tuple[FundRef, HoldingChange, dt.date]], *, side_is_buy: bool
) -> ConsensusRow:
    """One `ConsensusRow` for `cusip`, with `total_weight_delta` scoped to `side_is_buy`'s side.

    `entries` is sorted by fund key before anything is read from it, so `issuer`/`ticker` selection
    and `movers` order are both deterministic and independent of whatever order the caller's walk
    produced -- see `ConsensusRow`'s docstring and the "ranking is deterministic when counts tie"
    test.
    """
    ordered = sorted(entries, key=lambda e: e[0].key)
    buyers = [e for e in ordered if e[1].action in _BUY_ACTIONS]
    sellers = [e for e in ordered if e[1].action in _SELL_ACTIONS]
    side_entries = buyers if side_is_buy else sellers

    issuer = ordered[0][1].issuer
    ticker = next((change.ticker for _fund, change, _period in ordered if change.ticker), None)
    total_weight_delta = sum(
        (change.weight_delta for _fund, change, _period in side_entries), Decimal(0)
    )

    return ConsensusRow(
        cusip=cusip,
        issuer=issuer,
        ticker=ticker,
        buyer_count=len(buyers),
        seller_count=len(sellers),
        net_funds=len(buyers) - len(sellers),
        total_weight_delta=total_weight_delta,
        movers=[_fund_move(fund, change, period) for fund, change, period in ordered],
    )


def _sorted_rows(
    grouped: dict[str, list[tuple[FundRef, HoldingChange, dt.date]]],
    *,
    side_is_buy: bool,
    limit: int,
) -> list[ConsensusRow]:
    """Every CUSIP with at least one mover on `side_is_buy`'s side, ranked and truncated to `limit`.

    Buys rank by `buyer_count` descending, then `total_weight_delta` descending, then `cusip`
    ascending as a deterministic tie-break (module docstring point 3). Sells mirror it exactly on
    `seller_count` in place of `buyer_count` -- the same three-key tuple, same directions -- rather
    than inverting `total_weight_delta`'s sort direction: `total_weight_delta` is a tie-break only,
    reached exclusively when two rows already share the same vote count, so its own sign convention
    for a book of sells (summed negative deltas) never changes which field decides the ranking.
    """
    rows = []
    for cusip, entries in grouped.items():
        count = sum(1 for _f, c, _p in entries if (c.action in _BUY_ACTIONS) == side_is_buy)
        if count == 0:
            continue
        rows.append(_build_row(cusip, entries, side_is_buy=side_is_buy))

    key_fn = (lambda r: (-r.buyer_count, -r.total_weight_delta, r.cusip)) if side_is_buy else (
        lambda r: (-r.seller_count, -r.total_weight_delta, r.cusip)
    )
    rows.sort(key=key_fn)
    return rows[:limit]


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------


def _cache_dir(settings: Settings) -> Path:
    return settings.cache_dir / "institutions_consensus"


def _cache_path(settings: Settings, *, as_of: dt.date | None, limit: int) -> Path:
    as_of_tag = as_of.isoformat() if as_of is not None else "latest"
    return _cache_dir(settings) / f"{_CACHE_VERSION}-{as_of_tag}-{limit}.json"


def _read_cache(path: Path) -> ConsensusResponse | None:
    """The cached response at `path`, or `None` if absent, unreadable, or older than the TTL.

    A truncated or stale-shaped file must never take this endpoint down -- caught narrowly enough
    (`OSError`, `ValueError`) to still let a real bug in `ConsensusResponse` surface as an error
    rather than a silently ignored cache miss.
    """
    if not path.is_file():
        return None
    try:
        cached = ConsensusResponse.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    age = (dt.datetime.now(dt.UTC) - cached.generated_at).total_seconds()
    if age < 0 or age > _CACHE_TTL_SECONDS:
        return None
    return cached


def _write_cache(path: Path, response: ConsensusResponse) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response.model_dump_json(), encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_consensus(
    *,
    settings: Settings,
    as_of: dt.date | None = None,
    limit: int = 20,
    refresh: bool = False,
    client: EdgarClient | None = None,
    funds: tuple[FundRef, ...] | None = None,
    now: dt.datetime | None = None,
) -> ConsensusResponse:
    """Compute -- or serve cached -- cross-institution consensus for the tracked catalog.

    ``as_of`` is passed straight through to `service.load_delta` for every fund, bounding each
    fund's delta to filings public on or before that date -- the same filing-date-not-period bound
    every other endpoint in this package uses. ``limit`` truncates `buys` and `sells` independently
    to at most that many rows each.

    ``refresh=True`` forces a fresh walk of every fund and overwrites the cache, the same escape
    hatch `app.api.macro`'s `/snapshot?refresh=true` offers. Left `False` (the default), a fresh
    enough cached file (see the module docstring's TTL) is served without touching the network at
    all.

    ``client``/``funds``/``now`` exist for tests: `funds` overrides the catalog, `client` lets one
    `EdgarClient` (and therefore one cache) be shared or mocked, and `now` pins `generated_at`
    instead of reading the real clock.
    """
    cache_path = _cache_path(settings, as_of=as_of, limit=limit)
    if not refresh:
        cached = _read_cache(cache_path)
        if cached is not None:
            return cached

    tracked = funds if funds is not None else catalog.default_catalog()
    edgar_client = client or service.build_client(settings)

    checked, unchecked, deltas = _load_deltas(tracked, client=edgar_client, settings=settings, as_of=as_of)

    moves = _all_moves(deltas)
    moves = _suppress_sponsor_overlap(moves)

    grouped: dict[str, list[tuple[FundRef, HoldingChange, dt.date]]] = {}
    for fund, change, period in moves:
        grouped.setdefault(change.cusip, []).append((fund, change, period))

    buys = _sorted_rows(grouped, side_is_buy=True, limit=limit)
    sells = _sorted_rows(grouped, side_is_buy=False, limit=limit)

    response = ConsensusResponse(
        generated_at=now or dt.datetime.now(dt.UTC),
        as_of=as_of,
        checked=checked,
        unchecked=unchecked,
        buys=buys,
        sells=sells,
    )
    _write_cache(cache_path, response)
    return response
