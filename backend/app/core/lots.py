"""Lot replay: the merged ledger becomes open lots and closed disposals.

Everything in the tax engine is computed from the output of this module, so an error here is an
error on a tax form. Three properties matter more than anything else:

* **Transfers are not trades.** ``TRANSFER_IN`` / ``TRANSFER_OUT`` (Robinhood ``ACATI`` / ``ACATO``)
  and ``INTERNAL_TRANSFER`` (``ITRF``) move a position between accounts without disposing of it.
  The receiving lot keeps the *original* ``acquired_date`` and the *original* basis. Treating one as
  a sale invents a taxable event and restarts the holding period; many rows in a real dataset do this.
* **Replay is deterministic, and in the order the trades actually happened.** Ordering is
  ``(trade_date, executed_at_utc, account_id, replay_order, source_row, txn_id)`` — the same total
  order :func:`app.db.sqlite.fetch_transactions` returns. Two runs over the same ledger must produce
  byte-identical lots, because derived data is rebuilt rather than mutated. ``replay_order``, not
  ``source_row``, is the term that carries chronology: all three brokers export newest-first, so the
  file's own row order runs backwards (see :class:`app.ingest.adapters.base.ExportOrder`). While this
  ordered on ``source_row``, a day of round-trip trading replayed as sell-then-buy and left a phantom
  open lot behind every closed position — large phantom holdings that were never held.
* **Missing basis is visible, never invented.** Webull's Orders Records carry no transfers,
  dividends or splits, and Robinhood ``ACATI`` rows arrive from brokers outside this dataset. When a
  disposal cannot be matched to an acquisition, the engine records a :class:`LotWarning` and books
  zero basis — which overstates the gain — rather than guessing a number that would look right.

Lots are **derived state**: rebuilt from the ledger on demand, never hand-edited and never persisted
across a rebuild.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.core.ids import stable_id
from app.core.models import (
    Account,
    Broker,
    Instrument,
    Lot,
    LotStatus,
    Money,
    Quantity,
    Transaction,
    TxnAction,
)
from app.core.regfees import regulatory_sell_fee

__all__ = [
    "Disposal",
    "LotLedger",
    "LotMethod",
    "LotWarning",
    "OpeningPosition",
    "TransferBasis",
    "WarningKind",
    "build_lots",
]


@dataclass(frozen=True, slots=True)
class OpeningPosition:
    """Shares an account already held when its export begins.

    **A broker export is a window, not a life.** Every Robinhood account in this dataset starts
    mid-history -- `app.core.cash` independently detects the same thing and withholds a balance for
    it -- so a position opened before the first exported row is invisible to the replay. Everything
    downstream then reasons from a share count that is too low, and the failures are not subtle:

    * A sale of shares the export never saw bought becomes :data:`WarningKind.OVERSOLD`, a
      zero-basis disposal, and a realised gain equal to the entire proceeds.
    * A *transfer* of those shares to another account cannot be attributed at all. Neither side can
      be shown to hold them, so :func:`_split_transfer_legs` has to nominate a direction, and on
      real data it nominated wrongly -- leaving shares sitting in an account the
      broker statement says holds none.

    Declaring the opening position replaces both guesses with arithmetic. It is stated by the user
    in the account manifest, because it is exactly the kind of fact no parsing recovers: the shares
    are real, they are simply older than the file.

    ``cost_basis`` is optional and its absence is **not** treated as zero-cost. A lot opened without
    one is marked uncertain, exactly as an unmatched ACAT is, so any gain computed against it is
    reported as the bound it is rather than as a figure. Supplying it is what turns that bound into
    a number, and it is the single most valuable thing a user can add here.
    """

    account_id: str
    symbol: str
    quantity: Decimal
    as_of: dt.date
    """The date the position is stated as of -- normally the day the export begins. Used as the
    lot's acquisition date when :attr:`acquired_date` is unknown, which makes the holding period
    *shorter* than the truth and therefore never understates tax."""
    cost_basis: Decimal | None = None
    acquired_date: dt.date | None = None
    """The real acquisition date, if the user knows it. Decides long- versus short-term."""
    note: str = ""


@dataclass(frozen=True, slots=True)
class TransferBasis:
    """Cost basis for a specific inbound ``TRANSFER_IN`` whose outbound leg this dataset cannot supply.

    An ACAT carries basis with the shares, but the replay can only preserve it when the *sending* leg
    is in the ledger (:func:`build_lots` queues the outbound lot's basis for the inbound leg to draw).
    Two real cases leave an inbound leg with nothing to draw on, and both open a zero-basis lot plus
    :data:`WarningKind.UNMATCHED_TRANSFER_IN`:

    * The sending account is a broker/account **not in this dataset** (e.g. a Webull account whose
      export was never imported). There is no outbound leg at all.
    * The sending account *is* in the dataset, but the two legs do not pair -- a cross-broker ACAT
      where the outbound leg carries no ``transfer_group`` (SoFi) while the inbound leg was tagged
      with the receiving broker's control number, so they never key to the same queue. The basis is
      knowable (it is the sending account's own purchase cost) but the engine cannot route it.

    This declaration supplies that basis by hand. It is matched to a single inbound leg by
    ``(account_id, symbol, as_of)`` -- ``as_of`` is the **transfer date** as it appears on the
    receiving side -- and seeds exactly the queue that leg reads, so the ordinary basis-preserving
    path then runs unchanged. Unlike :class:`OpeningPosition`, ``cost_basis`` is required: an
    unbased transfer already gets the zero-basis lot and the warning without any declaration, so a
    :class:`TransferBasis` with no basis would say nothing.
    """

    account_id: str
    symbol: str
    quantity: Decimal
    as_of: dt.date
    """The transfer date on the receiving side -- the ``TRANSFER_IN`` row's trade date. Matches the
    declaration to one inbound leg."""
    cost_basis: Decimal
    acquired_date: dt.date | None = None
    """The original acquisition date the basis carries from. Decides long- versus short-term; falls
    back to :attr:`as_of` (shorter holding period, never understating tax) when unknown."""
    note: str = ""


class LotMethod(StrEnum):
    """Which open lot a sale consumes first.

    FIFO is the IRS default when the taxpayer does not identify shares at the time of sale, and it is
    what all three brokers apply absent instruction. ``SPECIFIC_ID`` exists for the case where the
    user identified shares to the broker; it requires an explicit lot selection per disposal.
    """

    FIFO = "fifo"
    SPECIFIC_ID = "specific_id"


class WarningKind(StrEnum):
    """Why a replayed transaction could not be handled cleanly.

    Every one of these represents a figure the user must not trust silently, so they surface in the
    API response and on the Tax page rather than only in a log.
    """

    UNMATCHED_TRANSFER_IN = "unmatched_transfer_in"
    """A position arrived by ACAT from an account outside this dataset. Basis and acquisition date
    are unknown; the lot is opened with zero basis and the original date is not recoverable."""

    OVERSOLD = "oversold"
    """A sale consumed more shares than the account held. Expected for Webull, whose Orders Records
    omit transfers in — the shares are real, their acquisition is simply not in the export."""

    MISSING_BASIS = "missing_basis"
    """A disposal matched a lot whose own basis was never established."""

    FEES_UNKNOWN = "fees_unknown"
    """A sale's fees are ``0`` because the source export carries no fee column at all, not because no
    fee was charged. Distinct from :data:`MISSING_BASIS`: the basis on these disposals can be
    perfectly known, and only the sale-side regulatory (SEC/TAF) fee is missing, so the resulting
    gain is only slightly, not grossly, overstated. Raised once per ``SELL`` transaction regardless
    of how many lots it draws on, mirroring :data:`OVERSOLD`. On a real ledger a Webull sale no
    longer reaches this state -- its fee is reconstructed instead, see :data:`FEES_ESTIMATED` -- so
    this remains for a future broker whose export drops the fee column but whose fee schedule is not
    encoded in :mod:`app.core.regfees`."""

    FEES_ESTIMATED = "fees_estimated"
    """A sale's fee was missing from the source export (a Webull *Orders Records* sale carries no fee
    column) and has been **reconstructed** from the published regulatory rate schedule -- the SEC
    Section 31 fee plus the FINRA Trading Activity Fee, both fixed pass-throughs (see
    :mod:`app.core.regfees`). Unlike :data:`FEES_UNKNOWN` this is not a gap: the fee is now netted
    from the gain. The warning exists only to keep that substitution visible, since the reconstructed
    cent is a documented estimate rather than a figure the broker reported. Raised once per ``SELL``
    transaction, mirroring :data:`OVERSOLD`."""

    UNSUPPORTED_ACTION = "unsupported_action"
    """A position-affecting action the replay does not implement, e.g. a spinoff with no ratio."""

    SPLIT_WITHOUT_RATIO = "split_without_ratio"
    """A split row carrying no ratio. Share counts after this date are wrong until it is supplied."""

    AMBIGUOUS_TRANSFER_DIRECTION = "ambiguous_transfer_direction"
    """Both legs of an internal transfer were in accounts the ledger cannot show holding the shares,
    so which one sent them was nominated rather than determined -- see
    :func:`_split_transfer_legs`. The *quantity* is right either way (a transfer conserves it); what
    is uncertain is which account the shares left, and therefore which account's basis and holding
    period travelled with them. Expected whenever an export begins after the account was funded,
    which is the case for every Robinhood account in this dataset."""


class LotWarning(BaseModel):
    """One thing the replay could not do correctly, with enough detail to act on it."""

    model_config = ConfigDict(extra="forbid")

    kind: WarningKind
    txn_id: str
    account_id: str
    instrument_id: str | None = None
    symbol: str | None = None
    trade_date: dt.date
    quantity: Quantity | None = None
    detail: str
    """Human-readable, specific. "sold 44 XXXX against 19 held" beats "oversold"."""


class Disposal(BaseModel):
    """Shares leaving one lot through one sale.

    A single sale that spans three lots produces three disposals. This is the granularity Form 8949
    reports at and the granularity the wash-sale rule operates on.

    Mutable, like :class:`~app.core.models.Lot`: :mod:`app.tax.washsale` writes the disallowed loss
    and the tolling decision back onto the disposal during a rebuild.
    """

    model_config = ConfigDict(extra="forbid")

    disposal_id: str
    lot_id: str
    instrument_id: str
    account_id: str
    symbol: str

    sell_txn_id: str
    lot_method: LotMethod | None = None
    """Which rule chose this lot, or ``None`` when no lot was chosen.

    Recorded on the disposal rather than left implicit because lot selection changes the tax
    outcome, and until it was written down the only way to learn it was arithmetic: a UAT persona
    holding two XLE lots ($58.72, then $57.73) sold 18 shares, saw a basis of $1,056.96, divided,
    and inferred FIFO. Correct, and not something a user should have to derive to know which shares
    they just sold.

    ``None`` on an oversold shortfall, where the replay found no lot to consume and invented neither
    one nor a method for picking it. Defaulting that row to ``FIFO`` would claim a selection was
    made over lots that do not exist.
    """
    acquired_date: dt.date
    """Original acquisition of the consumed lot, preserved across any ACAT transfer."""
    holding_start: dt.date
    """The date the holding period runs from. Equals ``acquired_date`` unless a wash sale tolled it.
    Copied from :attr:`~app.core.models.Lot.effective_holding_start` at disposal time and re-read by
    the wash-sale pass, which may move it earlier."""
    disposed_date: dt.date

    quantity: Quantity
    proceeds: Money
    """Gross proceeds for :attr:`quantity` shares, before fees."""
    cost_basis: Money
    """Basis allocated to these shares, including any wash-sale adjustment already on the lot."""
    fees: Money = Decimal(0)
    """Selling costs allocated to these shares. Reduce the gain; never rounded here."""

    # --- written by app.tax.washsale, not by the replay -----------------------------------------

    disallowed_loss: Money = Decimal(0)
    """**Total** loss disallowed under §1091, deferred and permanent portions together. Positive
    number. Zero when no wash sale applies."""
    permanently_disallowed_loss: Money = Decimal(0)
    """The part of :attr:`disallowed_loss` destroyed rather than deferred, because the replacement
    was bought inside an IRA (Rev. Rul. 2008-5): no basis is added anywhere and the loss is simply
    gone.

    A single sale can be replaced **partly** in an IRA and partly in a taxable account, and the two
    halves have incompatible outcomes. Real data produces this -- disposals split across
    Webull Margin and Webull Roth -- so a lone boolean cannot carry it. The deferred portion is
    :attr:`deferred_disallowed_loss`; the two must never be summed into one figure in the UI.
    """

    @property
    def permanently_disallowed(self) -> bool:
        """True when any part of the disallowance is permanent."""
        return self.permanently_disallowed_loss > 0

    @property
    def deferred_disallowed_loss(self) -> Decimal:
        """The ordinary portion: added to a replacement lot's basis, recoverable later."""
        return self.disallowed_loss - self.permanently_disallowed_loss

    @property
    def gain_loss(self) -> Decimal:
        """Realised gain or loss before any wash-sale disallowance. Negative is a loss."""
        return self.proceeds - self.fees - self.cost_basis

    @property
    def is_loss(self) -> bool:
        return self.gain_loss < 0

    @property
    def allowed_loss(self) -> Decimal:
        """The loss actually deductible after disallowance. Zero or negative."""
        if not self.is_loss:
            return Decimal(0)
        return self.gain_loss + self.disallowed_loss

    @property
    def reportable_gain_loss(self) -> Decimal:
        """Gain, or loss net of disallowance. What lands in the Form 8949 gain column."""
        return self.gain_loss if not self.is_loss else self.allowed_loss


class LotLedger(BaseModel):
    """The full result of a replay: what is held, what was disposed of, and what went wrong.

    ``warnings`` being non-empty does not invalidate the ledger — it localises the doubt. A user with
    an incomplete Webull export still gets correct Robinhood figures, and the Webull gaps are named.
    """

    model_config = ConfigDict(extra="forbid")

    lots: list[Lot] = []
    disposals: list[Disposal] = []
    warnings: list[LotWarning] = []
    symbols: dict[str, str] = {}
    """``instrument_id`` → display symbol, for reporting without a second lookup."""

    def open_lots(self) -> list[Lot]:
        """Lots with shares remaining, in replay order."""
        return [lot for lot in self.lots if lot.remaining > 0]

    def lots_by_id(self) -> dict[str, Lot]:
        return {lot.lot_id: lot for lot in self.lots}


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _instrument_key(txn: Transaction) -> str:
    """The key lots are matched on. Falls back to the raw symbol when ``instrument_id`` was never
    resolved upstream, so a gap in identity resolution degrades a lookup rather than crashing the
    replay."""
    return txn.instrument_id or txn.symbol or ""


def _gross_amount(txn: Transaction) -> Decimal:
    """Total dollar value of a trade: ``quantity * price`` when both are present, else the signed
    cash ``amount``. Every trade in the real exports carries both, but the model does not require
    ``price``, so this is the fallback for a row that only ever supplies the net cash effect."""
    if txn.price is not None and txn.quantity is not None:
        return txn.quantity * txn.price
    if txn.amount is not None:
        return abs(txn.amount)
    return Decimal(0)


#: Best-effort split-ratio extraction. :class:`~app.core.models.Transaction` carries no dedicated
#: ``ratio`` field for SPLIT rows -- none of the three adapters emit one, because no split appears in
#: any of the real exports this system was built against -- so this looks for a ratio spelled out in
#: ``description`` ("4:1", "4-for-1", "4 for 1", "3-to-1"). When nothing parses,
#: :data:`WarningKind.SPLIT_WITHOUT_RATIO` fires and lots are left untouched rather than guessed at.
_SPLIT_RATIO_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-for-|-to-|for|to|:|-)\s*(\d+(?:\.\d+)?)", re.IGNORECASE
)


def _extract_split_ratio(txn: Transaction) -> Decimal | None:
    if not txn.description:
        return None
    match = _SPLIT_RATIO_RE.search(txn.description)
    if not match:
        return None
    new_shares, old_shares = Decimal(match.group(1)), Decimal(match.group(2))
    if old_shares == 0:
        return None
    return new_shares / old_shares


@dataclass
class _TransferChunk:
    """One acquisition-dated slice of basis in flight between an outbound and an inbound transfer
    leg. A single outbound transaction can hand off pieces of several original lots; each becomes
    its own chunk so the receiving side can preserve every original ``acquired_date`` individually
    rather than collapsing them into one blended lot."""

    acquired_date: dt.date
    cost_basis: Decimal
    quantity: Decimal
    uncertain: bool = False
    """True when the outbound lot itself was opened at zero/invented basis (e.g. an earlier
    unmatched transfer). Propagated forward so a chain of transfers doesn't quietly launder an
    uncertain basis into a confident-looking one."""


# ---------------------------------------------------------------------------
# FIFO consumption
# ---------------------------------------------------------------------------


def _consume_fifo(
    candidates: Sequence[Lot], creation_rank: Mapping[str, int], quantity: Decimal
) -> tuple[list[tuple[Lot, Decimal]], Decimal]:
    """Select lots to satisfy ``quantity``, oldest ``acquired_date`` first, ties broken by the order
    lots were created during this replay (mirrors the order same-day acquisitions were recorded in).

    Returns the ``(lot, quantity_taken)`` pairs and the total actually consumed, which is less than
    ``quantity`` exactly when the account does not hold enough -- overselling, which callers must
    handle rather than this function raising.
    """
    ordered = sorted(
        (lot for lot in candidates if lot.remaining > 0),
        key=lambda lot: (lot.acquired_date, creation_rank[lot.lot_id]),
    )
    consumed: list[tuple[Lot, Decimal]] = []
    left = quantity
    for lot in ordered:
        if left <= 0:
            break
        take = min(lot.remaining, left)
        consumed.append((lot, take))
        left -= take
    return consumed, quantity - left


def _apply_consumption(lot: Lot, take: Decimal, as_of: dt.date) -> None:
    lot.remaining -= take
    if lot.remaining <= 0:
        lot.remaining = Decimal(0)
        lot.status = LotStatus.CLOSED
        lot.closed_date = as_of
    else:
        lot.status = LotStatus.PARTIAL


# ---------------------------------------------------------------------------
# INTERNAL_TRANSFER direction classification
# ---------------------------------------------------------------------------


def _resolve_opening_keys(
    opening: Sequence[OpeningPosition],
    transactions: Sequence[Transaction],
) -> list[tuple[tuple[str, str], OpeningPosition]]:
    """Pair each declared opening position with the instrument key its account's rows actually use.

    An opening position is declared by **symbol**, because that is what a user reads off a broker
    screen. The replay keys on ``_instrument_key`` -- the ``instrument_id`` where one was resolved,
    the raw symbol otherwise -- so a declaration keyed on the wrong one silently opens a lot that
    nothing ever consumes, which looks exactly like the phantom holding this feature exists to
    remove. The mapping is therefore taken from the account's own transactions rather than assumed.

    Falls back to the upper-cased symbol when the account has no transaction in that security at
    all. That is the right reading of a position held but never traded inside the export window --
    it is precisely the case being described -- and it stays consistent with ``_instrument_key``'s
    own fallback.

    Returned in declaration order so the lots open deterministically.
    """
    by_symbol: dict[tuple[str, str], str] = {}
    for txn in transactions:
        key = _instrument_key(txn)
        if txn.symbol and key:
            by_symbol.setdefault((txn.account_id, txn.symbol.upper()), key)

    resolved: list[tuple[tuple[str, str], OpeningPosition]] = []
    for position in opening:
        symbol = position.symbol.upper()
        key = by_symbol.get((position.account_id, symbol), symbol)
        resolved.append(((position.account_id, key), position))
    return resolved


def _classify_internal_transfers(
    transactions: Sequence[Transaction],
    opening: Mapping[tuple[str, str], Decimal] | None = None,
) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """Work out which side of each ``INTERNAL_TRANSFER`` (Robinhood ``ITRF``) is sending and which
    is receiving.

    Unlike ACAT, the ``ITRF`` code carries no direction of its own, and in the real export it carries
    no ``transfer_group`` either -- both legs of one transfer share an identical code with nothing
    that links them (the Robinhood adapter only extracts ``control_num`` for ``ACATI``/``ACATO``).
    The only signal left is quantity: whichever account already holds enough shares of the instrument
    as of that date is the one that must be sending them.

    This runs as a self-contained pre-pass in trade-date order, tracking running per-(account,
    instrument) quantity from BUY/SELL/ACAT/SPLIT and from every ``ITRF`` already resolved on an
    earlier date. It does not depend on which of two same-day legs happens to sort first in the
    ledger's ``(trade_date, executed_at, sequence, txn_id)`` order -- real data shows that order is
    not reliable across two different account exports on the same activity date.

    Returns:
        ``(role, partner, unresolved)``. ``role[txn_id]`` is ``"out"`` or ``"in"``.
        ``partner[txn_id]`` is the matched leg's ``txn_id`` where quantity uniquely identified one;
        absent for a one-sided transfer, which is the common case -- most ``ITRF`` rows in the real
        data have no in-dataset counterpart because the other side of the move is at an account this
        dataset doesn't export. ``unresolved`` holds the ``txn_id`` of every leg whose sending role
        was *nominated* rather than determined (see :func:`_split_transfer_legs`), so the replay can
        warn on it.
    """
    itrf_rows = [
        t
        for t in transactions
        if t.action is TxnAction.INTERNAL_TRANSFER and t.symbol and t.quantity
    ]
    if not itrf_rows:
        return {}, {}, set()

    # Seeded with whatever each account already held when its export began. This is the whole
    # point of `OpeningPosition` for this function: the test below is "can this account be shown to
    # hold the shares", and without a seed the answer is no for every position older than the file.
    running: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    running.update(opening or {})
    role: dict[str, str] = {}
    partner: dict[str, str] = {}
    unresolved: set[str] = set()

    # Lifetime acquisitions per (account, instrument), over the whole dataset rather than up to a
    # date. `running` is a point-in-time balance and reads zero for a position opened before the
    # export begins; this reads non-zero for any account that ever bought the security, which is the
    # tie-break `_split_transfer_legs` needs when no balance can be established. ITRF rows are
    # excluded deliberately -- counting a transfer leg as an acquisition would let the very row
    # being classified vote on its own direction.
    acquired_ever: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    acquired_ever.update(opening or {})
    for t in transactions:
        if t.action in (TxnAction.BUY, TxnAction.TRANSFER_IN) and t.quantity is not None:
            acquired_key = _instrument_key(t)
            if acquired_key:
                acquired_ever[(t.account_id, acquired_key)] += t.quantity

    by_date_other: dict[dt.date, list[Transaction]] = defaultdict(list)
    by_date_itrf: dict[dt.date, list[Transaction]] = defaultdict(list)
    for t in transactions:
        if t.action in (
            TxnAction.BUY,
            TxnAction.SELL,
            TxnAction.TRANSFER_IN,
            TxnAction.TRANSFER_OUT,
        ):
            if t.quantity is not None and _instrument_key(t):
                by_date_other[t.trade_date].append(t)
        elif t.action is TxnAction.SPLIT and _instrument_key(t):
            by_date_other[t.trade_date].append(t)
    for t in itrf_rows:
        by_date_itrf[t.trade_date].append(t)

    for trade_date in sorted(set(by_date_other) | set(by_date_itrf)):
        for t in by_date_other.get(trade_date, ()):
            key = (t.account_id, _instrument_key(t))
            if t.action is TxnAction.BUY:
                running[key] += t.quantity  # type: ignore[operator]
            elif t.action is TxnAction.SELL:
                running[key] -= t.quantity  # type: ignore[operator]
            elif t.action is TxnAction.TRANSFER_IN:
                running[key] += t.quantity  # type: ignore[operator]
            elif t.action is TxnAction.TRANSFER_OUT:
                running[key] -= t.quantity  # type: ignore[operator]
            elif t.action is TxnAction.SPLIT:
                ratio = _extract_split_ratio(t)
                if ratio is not None:
                    instrument = _instrument_key(t)
                    for (acct, inst), qty in list(running.items()):
                        if inst == instrument:
                            running[(acct, inst)] = qty * ratio

        day_rows = by_date_itrf.get(trade_date, ())
        if not day_rows:
            continue

        groups: dict[tuple[str, Decimal], list[Transaction]] = defaultdict(list)
        for t in day_rows:
            assert t.quantity is not None  # guaranteed by the itrf_rows filter above
            groups[(_instrument_key(t), t.quantity)].append(t)

        for (instrument, qty), rows in groups.items():
            senders, receivers, nominated = _split_transfer_legs(
                rows, instrument, qty, running, acquired_ever
            )
            unresolved.update(nominated)

            paired = min(len(senders), len(receivers))
            for sender, receiver in zip(senders[:paired], receivers[:paired], strict=True):
                role[sender.txn_id] = "out"
                role[receiver.txn_id] = "in"
                partner[sender.txn_id] = receiver.txn_id
                partner[receiver.txn_id] = sender.txn_id
            for sender in senders[paired:]:
                role[sender.txn_id] = "out"
            for receiver in receivers[paired:]:
                role[receiver.txn_id] = "in"

            for t in rows:
                key = (t.account_id, instrument)
                running[key] += -qty if role[t.txn_id] == "out" else qty

    return role, partner, unresolved


def _split_transfer_legs(
    rows: Sequence[Transaction],
    instrument: str,
    qty: Decimal,
    running: Mapping[tuple[str, str], Decimal],
    acquired_ever: Mapping[tuple[str, str], Decimal],
) -> tuple[list[Transaction], list[Transaction], set[str]]:
    """Decide which legs of one same-day, same-quantity ``ITRF`` group are sending.

    The primary test is the honest one: an account that already holds the shares can send them, and
    one that does not cannot. It is applied first and, when it separates the group, decides alone.

    **When it separates nothing, the group still has to be split.** It used to fall through to
    "nobody holds enough, therefore everybody is receiving", which credits every leg and creates
    shares out of nothing -- an internal transfer conserves quantity by definition, so two legs
    crediting ``qty`` each is not a conservative reading of ambiguous data, it is a fabrication.
    Measured on a real ledger against the broker statement, that alone accounted for the
    last few wrong positions after the export-ordering fix: phantom shares in several large-cap
    symbols, every one of them a same-day leg pair between two Robinhood accounts.

    The reason neither side ever "held enough" is worth stating, because it is not a rare edge: these
    exports **begin after the account was funded** (``app.core.cash`` independently detects the same
    thing and withholds a balance for it on every affected account). A position acquired before the
    export window is invisible to the running tally, so the tally under-counts, and it under-counts
    precisely for the long-standing positions most likely to be moved between accounts.

    The fallback ranks the legs by, in order: the running balance (least wrong under an
    under-counting tally), then **whether that account ever acquired the instrument at all** anywhere
    in the dataset, then ``account_id`` for determinism. The second term is what actually settles the
    real cases: the receiving account had no ``BUY`` or ``TRANSFER_IN`` of the instrument
    in its entire export -- it took delivery and ACAT'd them out days later -- while the
    sending account had bought and sold them all year. An account that never acquired a security is a
    poor candidate for having sent it.

    The nominated senders' ``txn_id``\\ s are returned so the caller can raise
    :data:`WarningKind.AMBIGUOUS_TRANSFER_DIRECTION`. **The direction is a guess and is labelled as
    one; the conservation is not.** Where even the second term ties -- neither account ever acquired
    the instrument outside the transfer itself, which happens when both accounts' exports start after
    the position was opened -- the choice is arbitrary, the warning says so, and the honest fix is an
    opening-balance concept this ledger does not yet have.
    """
    holders = [t for t in rows if running[(t.account_id, instrument)] >= qty]
    if holders:
        holder_ids = {t.txn_id for t in holders}
        return holders, [t for t in rows if t.txn_id not in holder_ids], set()

    if len(rows) < 2:
        # A one-sided leg: the counterpart account is simply not in this dataset. Receiving is the
        # right reading -- `receive_chunks` opens a zero-basis lot and warns -- and nothing is
        # fabricated, because there is no second leg to double-count against.
        return [], list(rows), set()

    # Half the legs send, half receive: whatever the direction, the group conserves quantity.
    ranked = sorted(
        rows,
        key=lambda t: (
            -running[(t.account_id, instrument)],
            -acquired_ever[(t.account_id, instrument)],
            t.account_id,
            t.txn_id,
        ),
    )
    split = len(rows) // 2
    senders = ranked[:split]
    return senders, ranked[split:], {t.txn_id for t in senders}


def _seed_transfer_basis(
    transfer_basis: Sequence[TransferBasis],
    transactions: Sequence[Transaction],
) -> dict[tuple[str, str], list[_TransferChunk]]:
    """Turn declared :class:`TransferBasis` rows into queue chunks the matching inbound leg will read.

    Each declaration is matched to a single ``TRANSFER_IN`` leg by ``(account_id, symbol, as_of)``,
    and the chunk is keyed on exactly ``(transfer_group or "", instrument_key)`` -- the same key that
    leg's :data:`TxnAction.TRANSFER_IN` branch looks up -- read off the matched transaction itself so
    the key can never drift from what the leg computes. A declaration matching no inbound leg (a wrong
    date or symbol) is dropped: the lot then stays unbased and keeps its warning, which surfaces the
    mistake, rather than seeding a queue nothing reads.
    """
    if not transfer_basis:
        return {}
    inbound = [
        t
        for t in transactions
        if t.action is TxnAction.TRANSFER_IN and t.symbol and t.quantity and _instrument_key(t)
    ]
    seeds: dict[tuple[str, str], list[_TransferChunk]] = defaultdict(list)
    for declaration in transfer_basis:
        symbol = declaration.symbol.upper()
        match = next(
            (
                t
                for t in inbound
                if t.account_id == declaration.account_id
                and (t.symbol or "").upper() == symbol
                and t.trade_date == declaration.as_of
            ),
            None,
        )
        if match is None:
            continue
        key = (match.transfer_group or "", _instrument_key(match))
        seeds[key].append(
            _TransferChunk(
                acquired_date=declaration.acquired_date or declaration.as_of,
                cost_basis=declaration.cost_basis,
                quantity=declaration.quantity,
                uncertain=False,
            )
        )
    return seeds


# ---------------------------------------------------------------------------
# Processing order
# ---------------------------------------------------------------------------


def _resolve_processing_order(
    transactions: Sequence[Transaction],
    itrf_role: Mapping[str, str],
    itrf_partner: Mapping[str, str],
) -> list[Transaction]:
    """Reorder so every transfer's outbound leg replays before its inbound leg.

    The upstream sort (``trade_date, executed_at, sequence, txn_id``) does not guarantee this: ACAT
    and ``ITRF`` pairs commonly share a trade date across two different account exports, and none of
    the tie-break fields correlate with which side actually moved first -- ``sequence`` is a row
    position within one file, and ``txn_id`` is a hash. Replaying an inbound leg before its outbound
    counterpart has run makes it look unmatched when it is not, and the outbound leg's shares are
    then pushed to a queue nobody ever reads, which is worse: they vanish from the ledger instead of
    merely losing their basis.

    Reordering only ever pushes an inbound leg to just after its resolved outbound counterpart;
    everything else -- including the relative order of unrelated rows -- keeps its given position.
    """
    position = {t.txn_id: i for i, t in enumerate(transactions)}

    acat_out_max: dict[tuple[str, str], int] = {}
    for i, t in enumerate(transactions):
        if t.action is TxnAction.TRANSFER_OUT and t.transfer_group and _instrument_key(t):
            key = (t.transfer_group, _instrument_key(t))
            acat_out_max[key] = max(acat_out_max.get(key, -1), i)

    ranked: list[tuple[int, int, Transaction]] = []
    for i, t in enumerate(transactions):
        effective = i
        if t.action is TxnAction.TRANSFER_IN and t.transfer_group and _instrument_key(t):
            out_index = acat_out_max.get((t.transfer_group, _instrument_key(t)))
            if out_index is not None:
                effective = max(effective, out_index + 1)
        elif t.action is TxnAction.INTERNAL_TRANSFER and itrf_role.get(t.txn_id) == "in":
            partner_id = itrf_partner.get(t.txn_id)
            if partner_id is not None:
                effective = max(effective, position[partner_id] + 1)
        ranked.append((effective, i, t))

    ranked.sort(key=lambda item: (item[0], item[1]))
    return [t for _, _, t in ranked]


# ---------------------------------------------------------------------------
# The replay
# ---------------------------------------------------------------------------


def build_lots(
    transactions: Sequence[Transaction],
    *,
    accounts: Mapping[str, Account],
    instruments: Mapping[str, Instrument] | None = None,
    method: LotMethod = LotMethod.FIFO,
    opening: Sequence[OpeningPosition] = (),
    transfer_basis: Sequence[TransferBasis] = (),
) -> LotLedger:
    """Replay the merged ledger chronologically into lots and disposals.

    Args:
        transactions: The whole ledger, every account together. Cross-account replay is required:
            ACAT transfers move positions between accounts and the wash-sale pass that follows needs
            all eight accounts in one structure.
        accounts: ``account_id`` → :class:`~app.core.models.Account`. Not consulted by the replay
            itself -- tax treatment is applied downstream by ``app.tax.gains``, which needs every
            account's lots (including IRAs) for wash-sale scanning before it excludes them from
            gain totals. Kept in the signature for that symmetry with
            :func:`app.tax.engine.build_tax_report`.
        instruments: ``instrument_id`` → :class:`~app.core.models.Instrument`, for display symbols.
        method: Lot selection. Only :attr:`LotMethod.FIFO` is implemented: no adapter or UI lets the
            user identify shares at sale time, so ``SPECIFIC_ID`` has no data source yet. Requesting
            it falls back to FIFO rather than raising.
        opening: Positions already held when each export begins -- see :class:`OpeningPosition`.
            Replayed as lots *before* any transaction, so FIFO consumes them first, which is what
            makes them behave like the older shares they are. An opening position for a symbol the
            account never trades is inert rather than an error: the user may simply be recording
            what they hold.
        transfer_basis: Basis for inbound ``TRANSFER_IN`` legs whose outbound leg this dataset cannot
            supply -- see :class:`TransferBasis`. Each seeds the queue its matched inbound leg reads,
            so the ordinary basis-preserving path carries it; a declaration that matches no inbound
            leg is inert (the lot stays unbased and keeps its warning) rather than an error.

    Returns:
        A :class:`LotLedger`. Never raises on incomplete data — gaps become
        :class:`LotWarning` entries, because a raise here would take down the whole Tax page over one
        unmatched Webull sale.
    """
    _ = method  # SPECIFIC_ID is not yet reachable from any adapter or UI; FIFO always applies.
    instrument_index = instruments or {}

    # Resolved before anything else: `_classify_internal_transfers` needs the quantities, and the
    # lots themselves cannot be opened until `new_lot` exists further down.
    opening_keys = _resolve_opening_keys(opening, transactions)
    opening_quantities = {key: pos.quantity for key, pos in opening_keys}

    itrf_role, itrf_partner, itrf_unresolved = _classify_internal_transfers(
        transactions, opening_quantities
    )
    order = _resolve_processing_order(transactions, itrf_role, itrf_partner)

    lots: list[Lot] = []
    creation_rank: dict[str, int] = {}
    open_lots: dict[tuple[str, str], list[Lot]] = defaultdict(list)
    disposals: list[Disposal] = []
    warnings: list[LotWarning] = []
    symbols: dict[str, str] = {}
    uncertain_lot_ids: set[str] = set()

    acat_queue: dict[tuple[str, str], list[_TransferChunk]] = defaultdict(list)
    itrf_queue: dict[str, list[_TransferChunk]] = defaultdict(list)

    # Seed the ACAT queue with any hand-declared transfer basis before the replay reads it, so an
    # inbound leg whose outbound counterpart is not in this dataset still draws real basis instead of
    # opening at zero. Keyed exactly as that leg will look it up; see `_seed_transfer_basis`.
    for _seed_key, _seed_chunks in _seed_transfer_basis(transfer_basis, order).items():
        acat_queue[_seed_key].extend(_seed_chunks)

    def remember_symbol(instrument_id: str | None, symbol: str | None) -> None:
        if not instrument_id or instrument_id in symbols:
            return
        inst = instrument_index.get(instrument_id)
        if inst is not None:
            symbols[instrument_id] = inst.primary_symbol
        elif symbol:
            symbols[instrument_id] = symbol

    def new_lot(
        *,
        txn: Transaction,
        chunk_index: int,
        instrument_key: str,
        acquired_date: dt.date,
        cost_basis: Decimal,
        quantity: Decimal,
    ) -> Lot:
        lot = Lot(
            lot_id=stable_id("lot", txn.txn_id, chunk_index),
            instrument_id=instrument_key,
            account_id=txn.account_id,
            acquired_date=acquired_date,
            acquired_txn_id=txn.txn_id,
            quantity=quantity,
            remaining=quantity,
            cost_basis=cost_basis,
        )
        creation_rank[lot.lot_id] = len(lots)
        lots.append(lot)
        open_lots[(txn.account_id, instrument_key)].append(lot)
        return lot

    def receive_chunks(
        *,
        txn: Transaction,
        instrument_key: str,
        needed: Decimal,
        queue: list[_TransferChunk],
        source: str,
    ) -> None:
        """Open lots from a transfer's inbound leg: one lot per basis-preserving chunk pulled off
        ``queue``, then a zero-basis lot plus :data:`WarningKind.UNMATCHED_TRANSFER_IN` for whatever
        quantity the queue could not cover."""
        chunk_index = 0
        while queue and needed > 0:
            chunk = queue.pop(0)
            take = min(chunk.quantity, needed)
            share = (take / chunk.quantity) if chunk.quantity else Decimal(0)
            lot = new_lot(
                txn=txn,
                chunk_index=chunk_index,
                instrument_key=instrument_key,
                acquired_date=chunk.acquired_date,
                cost_basis=chunk.cost_basis * share,
                quantity=take,
            )
            if chunk.uncertain:
                uncertain_lot_ids.add(lot.lot_id)
            chunk_index += 1
            if take < chunk.quantity:
                queue.insert(
                    0,
                    _TransferChunk(
                        acquired_date=chunk.acquired_date,
                        cost_basis=chunk.cost_basis * (1 - share),
                        quantity=chunk.quantity - take,
                        uncertain=chunk.uncertain,
                    ),
                )
            needed -= take

        if needed > 0:
            lot = new_lot(
                txn=txn,
                chunk_index=chunk_index,
                instrument_key=instrument_key,
                acquired_date=txn.trade_date,
                cost_basis=Decimal(0),
                quantity=needed,
            )
            uncertain_lot_ids.add(lot.lot_id)
            warnings.append(
                LotWarning(
                    kind=WarningKind.UNMATCHED_TRANSFER_IN,
                    txn_id=txn.txn_id,
                    account_id=txn.account_id,
                    instrument_id=instrument_key,
                    symbol=txn.symbol,
                    trade_date=txn.trade_date,
                    quantity=needed,
                    detail=(
                        f"{needed} {txn.symbol or instrument_key} arrived by {source} with no "
                        "matching outbound leg in this dataset; opened at zero basis"
                    ),
                )
            )

    # Opened before the first transaction so FIFO reaches them first -- they are the oldest shares
    # in the account by definition. A lot with no declared basis is marked uncertain rather than
    # treated as free, exactly as an unmatched ACAT is.
    for (account_id, instrument_key), position in opening_keys:
        # Upper-cased: these lots are registered before any transaction, and `remember_symbol` keeps
        # the first spelling it sees. A manifest entry written `googl` would otherwise become the
        # display symbol for that instrument everywhere, including for rows the broker wrote GOOGL.
        remember_symbol(instrument_key, position.symbol.upper())
        lot = Lot(
            lot_id=stable_id("opening-lot", account_id, instrument_key, str(position.as_of)),
            instrument_id=instrument_key,
            account_id=account_id,
            acquired_date=position.acquired_date or position.as_of,
            acquired_txn_id=stable_id("opening", account_id, instrument_key, str(position.as_of)),
            quantity=position.quantity,
            remaining=position.quantity,
            cost_basis=position.cost_basis if position.cost_basis is not None else Decimal(0),
        )
        creation_rank[lot.lot_id] = len(lots)
        lots.append(lot)
        open_lots[(account_id, instrument_key)].append(lot)
        if position.cost_basis is None:
            uncertain_lot_ids.add(lot.lot_id)
            warnings.append(
                LotWarning(
                    kind=WarningKind.MISSING_BASIS,
                    txn_id=lot.acquired_txn_id,
                    account_id=account_id,
                    instrument_id=instrument_key,
                    symbol=position.symbol,
                    trade_date=position.as_of,
                    quantity=position.quantity,
                    detail=(
                        f"{position.quantity} {position.symbol} declared as an opening position in "
                        f"{account_id} as of {position.as_of} with no cost basis. The shares are "
                        "real and the count is now right, but any gain realised against them is a "
                        "bound, not a figure -- supply `cost_basis` in the manifest to fix that"
                        + (f". {position.note}" if position.note else "")
                    ),
                )
            )

    for txn in order:
        remember_symbol(txn.instrument_id, txn.symbol)
        action = txn.action
        instrument_key = _instrument_key(txn)

        if action is TxnAction.BUY:
            qty = txn.quantity if txn.quantity is not None else Decimal(0)
            basis = _gross_amount(txn) + txn.fees
            new_lot(
                txn=txn,
                chunk_index=0,
                instrument_key=instrument_key,
                acquired_date=txn.trade_date,
                cost_basis=basis,
                quantity=qty,
            )

        elif action is TxnAction.SELL:
            qty = txn.quantity if txn.quantity is not None else Decimal(0)
            candidates = open_lots.get((txn.account_id, instrument_key), [])
            consumed, total_consumed = _consume_fifo(candidates, creation_rank, qty)

            gross = _gross_amount(txn)
            per_share_proceeds = gross / qty if qty else Decimal(0)
            # Webull's export has no fee column, so `txn.fees` is 0 structurally on every Webull sale
            # -- the datum is absent, not zero. The two fees a sale really incurs (SEC Section 31 +
            # FINRA TAF) are fixed pass-throughs recoverable from the trade date, share count and
            # proceeds, so reconstruct them (app.core.regfees) and net the gain of the fee that was
            # actually charged instead of overstating it. Only a Webull sale with `fees == 0` is
            # substituted: a real fee on the row, or any other broker's genuine zero-fee trade, is
            # left untouched.
            fee_is_estimated = txn.broker is Broker.WEBULL and txn.fees == 0 and bool(qty)
            effective_fees = (
                regulatory_sell_fee(proceeds=gross, shares=qty, trade_date=txn.trade_date)
                if fee_is_estimated
                else txn.fees
            )
            per_share_fees = effective_fees / qty if qty else Decimal(0)
            symbol = txn.symbol or symbols.get(instrument_key, instrument_key)

            for lot, take in consumed:
                _apply_consumption(lot, take, txn.trade_date)
                disposals.append(
                    Disposal(
                        disposal_id=stable_id("disposal", txn.txn_id, lot.lot_id),
                        lot_id=lot.lot_id,
                        instrument_id=instrument_key,
                        account_id=txn.account_id,
                        symbol=symbol,
                        sell_txn_id=txn.txn_id,
                        lot_method=method,
                        acquired_date=lot.acquired_date,
                        holding_start=lot.effective_holding_start,
                        disposed_date=txn.trade_date,
                        quantity=take,
                        proceeds=per_share_proceeds * take,
                        cost_basis=lot.basis_per_share * take,
                        fees=per_share_fees * take,
                    )
                )
                if lot.lot_id in uncertain_lot_ids:
                    warnings.append(
                        LotWarning(
                            kind=WarningKind.MISSING_BASIS,
                            txn_id=txn.txn_id,
                            account_id=txn.account_id,
                            instrument_id=instrument_key,
                            symbol=symbol,
                            trade_date=txn.trade_date,
                            quantity=take,
                            detail=(
                                f"disposal of {take} {symbol} drew on a lot whose basis was never "
                                "established (an unmatched transfer or an earlier oversold "
                                "shortfall); the resulting gain is overstated"
                            ),
                        )
                    )

            shortfall = qty - total_consumed
            if shortfall > 0:
                disposals.append(
                    Disposal(
                        disposal_id=stable_id("disposal", txn.txn_id, "oversold"),
                        lot_id=stable_id("oversold-lot", txn.txn_id),
                        instrument_id=instrument_key,
                        account_id=txn.account_id,
                        symbol=symbol,
                        sell_txn_id=txn.txn_id,
                        # No acquisition is known for the excess, so the holding period defaults to
                        # zero days -- short-term -- rather than inventing a date. That is the
                        # conservative direction: it cannot understate tax owed.
                        acquired_date=txn.trade_date,
                        holding_start=txn.trade_date,
                        disposed_date=txn.trade_date,
                        quantity=shortfall,
                        proceeds=per_share_proceeds * shortfall,
                        cost_basis=Decimal(0),
                        fees=per_share_fees * shortfall,
                    )
                )
                warnings.append(
                    LotWarning(
                        kind=WarningKind.OVERSOLD,
                        txn_id=txn.txn_id,
                        account_id=txn.account_id,
                        instrument_id=instrument_key,
                        symbol=symbol,
                        trade_date=txn.trade_date,
                        quantity=shortfall,
                        detail=(
                            f"sold {qty} {symbol} against {total_consumed} held in {txn.account_id}"
                        ),
                    )
                )

            # Webull's Orders Records export has no fee column at all -- every transaction it
            # produces carries `fees = 0` structurally (see the adapter's module docstring), which is
            # the absence of data, not a measurement that no fee was charged. The two regulatory
            # pass-throughs on a sale (SEC Section 31 + FINRA TAF) were reconstructed above from the
            # published rate schedule and netted from the gain; surface that so the substitution is
            # never silent. The reconstructed cent is a documented estimate, not a broker-reported
            # figure -- hence a warning rather than a value passed through unremarked.
            if fee_is_estimated:
                warnings.append(
                    LotWarning(
                        kind=WarningKind.FEES_ESTIMATED,
                        txn_id=txn.txn_id,
                        account_id=txn.account_id,
                        instrument_id=instrument_key,
                        symbol=symbol,
                        trade_date=txn.trade_date,
                        quantity=qty,
                        detail=(
                            f"sale of {qty} {symbol} in {txn.account_id}: Webull's export has no fee "
                            "column, so the SEC Section 31 + FINRA TAF regulatory fee was "
                            f"reconstructed from the published rate schedule as ${effective_fees} and "
                            "netted from the gain"
                        ),
                    )
                )

        elif action is TxnAction.TRANSFER_OUT:
            if instrument_key and txn.quantity:
                candidates = open_lots.get((txn.account_id, instrument_key), [])
                consumed, _total = _consume_fifo(candidates, creation_rank, txn.quantity)
                for lot, take in consumed:
                    _apply_consumption(lot, take, txn.trade_date)
                    if txn.transfer_group:
                        acat_queue[(txn.transfer_group, instrument_key)].append(
                            _TransferChunk(
                                acquired_date=lot.acquired_date,
                                cost_basis=lot.basis_per_share * take,
                                quantity=take,
                                uncertain=lot.lot_id in uncertain_lot_ids,
                            )
                        )
            # A cash-only ACAT row (no instrument) or a transfer with no group to key a queue on
            # carries no position to move and is otherwise a no-op: never a Disposal.

        elif action is TxnAction.TRANSFER_IN:
            if instrument_key and txn.quantity:
                queue = acat_queue.get((txn.transfer_group or "", instrument_key), [])
                receive_chunks(
                    txn=txn,
                    instrument_key=instrument_key,
                    needed=txn.quantity,
                    queue=queue,
                    source="ACAT transfer",
                )

        elif action is TxnAction.INTERNAL_TRANSFER:
            if txn.symbol and txn.quantity and instrument_key:
                if txn.txn_id in itrf_unresolved:
                    warnings.append(
                        LotWarning(
                            kind=WarningKind.AMBIGUOUS_TRANSFER_DIRECTION,
                            txn_id=txn.txn_id,
                            account_id=txn.account_id,
                            instrument_id=instrument_key,
                            symbol=txn.symbol,
                            trade_date=txn.trade_date,
                            quantity=txn.quantity,
                            detail=(
                                f"{txn.quantity} {txn.symbol} moved between accounts on "
                                f"{txn.trade_date}, and no account in this dataset can be shown to "
                                f"have held them beforehand -- typically because the export begins "
                                f"after the account was funded. {txn.account_id} was taken as the "
                                "sending side so the transfer conserves quantity; the shares are "
                                "real and the count is right, but which account's cost basis and "
                                "holding period travelled with them is a guess"
                            ),
                        )
                    )
                if itrf_role.get(txn.txn_id) == "out":
                    candidates = open_lots.get((txn.account_id, instrument_key), [])
                    consumed, _total = _consume_fifo(candidates, creation_rank, txn.quantity)
                    for lot, take in consumed:
                        _apply_consumption(lot, take, txn.trade_date)
                        itrf_queue[txn.txn_id].append(
                            _TransferChunk(
                                acquired_date=lot.acquired_date,
                                cost_basis=lot.basis_per_share * take,
                                quantity=take,
                                uncertain=lot.lot_id in uncertain_lot_ids,
                            )
                        )
                else:
                    partner_id = itrf_partner.get(txn.txn_id)
                    queue = itrf_queue.get(partner_id, []) if partner_id else []
                    receive_chunks(
                        txn=txn,
                        instrument_key=instrument_key,
                        needed=txn.quantity,
                        queue=queue,
                        source="internal transfer",
                    )
            # A cash-only ITRF row moves no position; models.TxnAction.affects_position also omits
            # INTERNAL_TRANSFER entirely (only TRANSFER_IN/OUT are listed), which looks like an
            # oversight against the 65 ITRF rows this dataset carries -- handled explicitly here
            # regardless of that property. See the phase report for the recommended contract fix.

        elif action is TxnAction.SPLIT:
            ratio = _extract_split_ratio(txn)
            if ratio is None:
                warnings.append(
                    LotWarning(
                        kind=WarningKind.SPLIT_WITHOUT_RATIO,
                        txn_id=txn.txn_id,
                        account_id=txn.account_id,
                        instrument_id=txn.instrument_id,
                        symbol=txn.symbol,
                        trade_date=txn.trade_date,
                        quantity=txn.quantity,
                        detail=(
                            f"split of {txn.symbol or instrument_key} carries no parseable ratio; "
                            "share counts and per-share basis from this date forward are wrong "
                            "until one is supplied"
                        ),
                    )
                )
            else:
                for lots_for_key in open_lots.values():
                    for lot in lots_for_key:
                        if lot.instrument_id == instrument_key and lot.remaining > 0:
                            lot.quantity = lot.quantity * ratio
                            lot.remaining = lot.remaining * ratio

        elif action is TxnAction.SPINOFF:
            warnings.append(
                LotWarning(
                    kind=WarningKind.UNSUPPORTED_ACTION,
                    txn_id=txn.txn_id,
                    account_id=txn.account_id,
                    instrument_id=txn.instrument_id,
                    symbol=txn.symbol,
                    trade_date=txn.trade_date,
                    quantity=txn.quantity,
                    detail=(
                        f"spinoff on {txn.symbol or txn.instrument_id or 'an unresolved instrument'} "
                        "is not implemented; existing lots are left untouched and no new lot was "
                        "opened for shares of the spun-off company"
                    ),
                )
            )

        # Everything else -- dividends, interest, stock-lending income, fees, subscription fees,
        # cash in/out, IRA_MATCH, adjustments, misc -- does not affect a position. Skipped silently,
        # per contract: no warning is expected for these.

    return LotLedger(lots=lots, disposals=disposals, warnings=warnings, symbols=symbols)
