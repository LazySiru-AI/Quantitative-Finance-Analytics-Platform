"""Canonical instrument identity across brokers that do not supply a CUSIP.

:func:`app.core.ids.instrument_id` keys on CUSIP when a broker supplies one and falls back to the
normalised symbol otherwise. Robinhood supplies CUSIPs; Webull does not. Parsed file-by-file, that
means one real security can surface as two distinct ``instrument_id`` values -- a CUSIP-keyed one
from Robinhood and a symbol-keyed one from Webull -- and :mod:`app.tax.washsale` matches wash sales
on ``instrument_id`` (deliberately: ticker text is not a safe match key). A split identity makes a
cross-broker wash-sale pair for that security invisible to the engine.

**Why this lives on the derive path, not the ingest path.** Resolving a symbol-keyed id to its
CUSIP-keyed twin requires seeing both ends -- the CUSIP might arrive in a file imported *after* the
symbol-keyed one. An ingest-time fix would only work when the CUSIP-bearing broker happens to be
imported first, which is not a fix, it is a coin flip. The whole ledger is visible only when it is
loaded for derivation (:func:`app.tax.engine.report_from_ledger`, the Portfolio route, and anywhere
else that calls :func:`app.core.lots.build_lots` against stored transactions), so that is where
resolution happens, and it is recomputed from the *current* ledger contents on every call -- nothing
here is persisted, so it survives a rebuild for free and never requires touching a stored row.

**Merge direction is one-way.** Only a symbol-keyed id is ever remapped, and only onto a *specific*
CUSIP-keyed id observed for that same normalised symbol somewhere in the ledger. A CUSIP-keyed id is
never rewritten, and two distinct CUSIPs are never merged into each other -- that would blend two
different securities that happen to share a ticker (a delisted company and whatever reused its
symbol later), which is a far worse defect than the one this module fixes. See
:class:`ConflictingCusipError`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.core.ids import instrument_id as compute_instrument_id
from app.core.ids import normalize_symbol
from app.core.models import Instrument, Transaction

__all__ = [
    "ConflictingCusipError",
    "build_canonical_instrument_map",
    "canonicalize_ledger",
    "remap_instruments",
    "remap_transactions",
]


class ConflictingCusipError(ValueError):
    """One normalised symbol resolves to two distinct CUSIPs somewhere in the ledger.

    This is not the bug the rest of this module fixes -- it is the opposite hazard, and the one that
    matters more: silently merging two different securities because their tickers happen to collide
    (a ticker reused after a delisting, for instance) would fabricate a wash-sale pair, a cost basis,
    or a holding period between two things that are not the same investment. Per the repo's "unknown
    input raises" rule, this is surfaced rather than resolved by picking one CUSIP over the other.
    """

    def __init__(self, normalized_symbol: str, cusips: set[str]) -> None:
        ordered = sorted(cusips)
        super().__init__(
            f"symbol {normalized_symbol!r} maps to {len(ordered)} distinct CUSIPs {ordered} "
            "somewhere in the ledger -- this is not a broker-spelling difference, it is either two "
            "different securities that happen to share a ticker (e.g. reuse after a delisting) or "
            "bad input data. Refusing to merge them; resolve the conflict in the data before "
            "re-running."
        )
        self.normalized_symbol = normalized_symbol
        self.cusips = ordered


def _normalized_cusip(cusip: str | None) -> str | None:
    if not cusip:
        return None
    stripped = cusip.strip().upper()
    return stripped or None


def build_canonical_instrument_map(
    transactions: Sequence[Transaction],
    instruments: Mapping[str, Instrument],
) -> dict[str, str]:
    """Map every symbol-keyed ``instrument_id`` that has a CUSIP-keyed twin onto that twin.

    Scans every :class:`Instrument` and every :class:`Transaction` in the ledger -- both, because an
    instrument discovered mid-parse (e.g. a Robinhood ``SLIP``/``CDIV`` row) may carry a CUSIP that
    never made it onto the ``instrument`` table's ``primary_symbol`` row for a different broker's
    spelling. For each normalised symbol that has exactly one distinct CUSIP anywhere in the ledger,
    the symbol-keyed id :func:`app.core.ids.instrument_id` would have produced for that symbol is
    computed directly (not guessed) and mapped to the CUSIP-keyed id actually observed.

    Order-independent by construction: the result depends only on the *set* of CUSIPs and symbols
    present in the ledger, never on which file mentioned them first.

    A symbol that is *always* accompanied by its CUSIP (every broker that ever mentions it supplies
    one) never actually produces a symbol-keyed id in the first place -- there is nothing to merge,
    and this returns no entry for it, even though a hypothetical symbol-keyed id could be computed.
    Only ids that genuinely appear somewhere in ``instruments`` or ``transactions`` are ever used as
    a map key, so the map's size is exactly the number of instruments this ledger actually split.

    Raises:
        ConflictingCusipError: A normalised symbol maps to more than one distinct CUSIP.
    """
    cusip_by_symbol: dict[str, tuple[str, str]] = {}  # normalized symbol -> (cusip, instrument_id)
    seen_ids: set[str] = set(instruments.keys())

    def observe(symbol: str | None, cusip: str | None, iid: str | None) -> None:
        if iid:
            seen_ids.add(iid)
        normalized_cusip = _normalized_cusip(cusip)
        if not symbol or not normalized_cusip or not iid:
            return
        norm_symbol = normalize_symbol(symbol)
        existing = cusip_by_symbol.get(norm_symbol)
        if existing is not None and existing[0] != normalized_cusip:
            raise ConflictingCusipError(norm_symbol, {existing[0], normalized_cusip})
        cusip_by_symbol[norm_symbol] = (normalized_cusip, iid)

    for instrument in instruments.values():
        observe(instrument.primary_symbol, instrument.cusip, instrument.instrument_id)
    for txn in transactions:
        observe(txn.symbol, txn.cusip, txn.instrument_id)

    canonical: dict[str, str] = {}
    for norm_symbol, (_cusip, canonical_id) in cusip_by_symbol.items():
        symbol_keyed_id = compute_instrument_id(cusip=None, symbol=norm_symbol)
        if symbol_keyed_id != canonical_id and symbol_keyed_id in seen_ids:
            canonical[symbol_keyed_id] = canonical_id
    return canonical


def remap_transactions(
    transactions: Sequence[Transaction], canonical: Mapping[str, str]
) -> list[Transaction]:
    """Rewrite every transaction's ``instrument_id`` through ``canonical``, leaving the rest untouched.

    Only ``instrument_id`` changes -- ``symbol`` and ``cusip`` stay exactly as the broker reported
    them, because they are provenance, not identity, and nothing downstream reads them for grouping.
    """
    if not canonical:
        return list(transactions)
    result: list[Transaction] = []
    for txn in transactions:
        replacement = canonical.get(txn.instrument_id) if txn.instrument_id else None
        result.append(
            txn.model_copy(update={"instrument_id": replacement}) if replacement else txn
        )
    return result


def remap_instruments(
    instruments: Mapping[str, Instrument], canonical: Mapping[str, str]
) -> dict[str, Instrument]:
    """Drop the now-superseded symbol-keyed instrument rows.

    After :func:`remap_transactions`, nothing references a merged-away id any more, so keeping its
    ``Instrument`` entry around would just be a dead alias a future lookup could accidentally hit.
    """
    if not canonical:
        return dict(instruments)
    return {iid: inst for iid, inst in instruments.items() if iid not in canonical}


def canonicalize_ledger(
    transactions: Sequence[Transaction],
    instruments: Mapping[str, Instrument],
) -> tuple[list[Transaction], dict[str, Instrument]]:
    """Resolve cross-broker instrument identity, then remap both transactions and instruments.

    The one function every derive-time call site should use: build the canonical map, apply it to
    the transactions about to be replayed by :func:`app.core.lots.build_lots`, and apply it to the
    instrument lookup those transactions will be displayed against. Call this *before* ``build_lots``
    -- wash-sale matching keys on ``instrument_id``, so anything that runs the replay on unmapped
    transactions reproduces the original bug regardless of what happens afterwards.
    """
    canonical = build_canonical_instrument_map(transactions, instruments)
    return remap_transactions(transactions, canonical), remap_instruments(instruments, canonical)
