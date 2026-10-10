"""Adapter contract.

Every broker adapter implements :class:`BrokerAdapter`. Adapters are the only code in the system that
knows what a Robinhood or Webull row looks like; everything downstream sees :class:`Transaction`.

The contract has one unusual requirement: **a row that does not become a transaction must be recorded
as a :class:`SkippedRow` with a reason.** Silently dropping rows is the failure mode that matters most
here -- a discarded dividend is invisible in the UI and wrong in the tax output. Recording the reason
also gives each adapter a row-count signature that regression tests can pin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from app.core.models import Account, Broker, Instrument, Transaction
from app.ingest.provenance import RawFile

__all__ = [
    "AdapterResult",
    "BrokerAdapter",
    "ExportOrder",
    "SkipReason",
    "SkippedRow",
    "UnknownTransactionCode",
]


class ExportOrder(StrEnum):
    """Which way round a broker writes its rows.

    Only the adapter can know this, and until it was asked the system assumed every export ran
    oldest-first. All three of these brokers write **newest-first**, and for the two that publish no
    time of day that assumption replayed every trading day backwards.

    What it cost, measured against a real broker statement: a day of same-symbol round trips at
    Robinhood replayed as *sell 50, then buy 50* instead of *buy 50, then sell 50*. The sale found no
    lot to consume (one ``oversold`` warning, a disposal booked at zero basis, so the whole proceeds
    counted as gain) and the purchase opened a lot nothing ever closed. Repeated across a year,
    equal buy and sell totals in heavily-traded symbols netted to large phantom positions that were
    never held. Many symbols in one account were affected, and the accounts whose
    broker *does* publish a timestamp reconciled to the share.

    ``NEWEST_FIRST`` is not a display preference; it decides which shares a sale consumes, and
    therefore the cost basis and realised gain on a tax form.
    """

    OLDEST_FIRST = "oldest_first"
    """Row 0 is the earliest event. ``replay_order`` is the row index unchanged."""

    NEWEST_FIRST = "newest_first"
    """Row 0 is the most recent event -- the export reads like a statement, top-down. Chronological
    order is the file read backwards, which is what :meth:`replay_order_for` returns."""

    def replay_order_for(self, row_index: int, total_rows: int) -> int:
        """The row's chronological rank in the file, ascending = earlier.

        Gaps are fine and expected: skipped rows (cancellations, footers) leave holes, and only the
        relative order matters. What must hold is that a row that executed earlier gets a smaller
        number than one that executed later **in the same file**, which is the only comparison
        :func:`app.db.sqlite.fetch_transactions` makes with it.
        """
        if self is ExportOrder.OLDEST_FIRST:
            return row_index
        return total_rows - 1 - row_index


class SkipReason(StrEnum):
    """Why a source row produced no transaction.

    Every one of these is a legitimate, expected reason. Anything else must raise instead.
    """

    CANCELLED = "cancelled"
    """Order cancelled before execution. Webull ``Status='Cancelled'``; SoFi rows whose
    description ends ``(Canceled)`` -- note these carry a populated ``Amount`` and look
    exactly like executions."""

    FAILED = "failed"
    """Order failed. Webull ``Status='Failed'`` (4 rows)."""

    FOOTER = "footer"
    """Trailing blank row. Robinhood emits two per file."""

    ZERO_FILL = "zero_fill"
    """Accepted but unfilled: ``Filled`` is zero while the order was not formally cancelled."""

    NON_EVENT = "non_event"
    """A row that carries no ledger effect, such as an informational marker."""


@dataclass(frozen=True, slots=True)
class SkippedRow:
    """A source row that produced no transaction, with the reason and enough context to audit it."""

    row_index: int
    reason: SkipReason
    detail: str = ""


class UnknownTransactionCode(ValueError):
    """An adapter met a broker code it has no mapping for.

    Fatal by design. An unmapped code means the broker changed its export or the adapter's
    understanding was incomplete, and guessing produces a wrong tax figure that nobody notices.
    """

    def __init__(self, broker: Broker, code: str, row_index: int) -> None:
        super().__init__(
            f"{broker.value} adapter has no mapping for transaction code {code!r} "
            f"at row {row_index}; add it to the mapping table rather than skipping the row"
        )
        self.broker = broker
        self.code = code
        self.row_index = row_index


@dataclass(slots=True)
class AdapterResult:
    """Everything one file yielded."""

    transactions: list[Transaction] = field(default_factory=list)
    skipped: list[SkippedRow] = field(default_factory=list)
    instruments: dict[str, Instrument] = field(default_factory=dict)
    """Instruments discovered while parsing, keyed by ``instrument_id``. Robinhood contributes CUSIPs
    here, which is what later lets Webull's bare tickers resolve to the same instrument."""

    @property
    def usable_row_count(self) -> int:
        return len(self.transactions)

    def skip_counts(self) -> dict[str, int]:
        """Skips grouped by reason -- the regression signature for an adapter."""
        counts: dict[str, int] = {}
        for row in self.skipped:
            counts[row.reason.value] = counts.get(row.reason.value, 0) + 1
        return counts


@runtime_checkable
class BrokerAdapter(Protocol):
    """One broker's export format.

    Implementations are stateless and registered in :mod:`app.ingest.registry`.
    """

    name: str
    version: str
    """Bumped whenever parsing behaviour changes. Stored on the import record so a ledger row can be
    traced to the exact adapter logic that produced it."""
    broker: Broker
    export_order: ExportOrder
    """Which way round this broker writes its rows -- see :class:`ExportOrder`. Required, with no
    default, for the same reason ``tax_treatment`` is: the wrong answer is silent, produces a
    confident and completely wrong position, and no downstream check can catch it."""

    def matches(self, raw: RawFile) -> bool:
        """Whether this adapter handles the file, judged by header signature.

        Detection is by header rather than filename: the user renames exports freely, and
        ``Account A.csv`` says nothing a parser can rely on.
        """
        ...

    def parse(self, raw: RawFile, *, account: Account, import_id: str) -> AdapterResult:
        """Convert rows into transactions.

        Raises:
            UnknownTransactionCode: A broker code has no mapping.
            MoneyParseError: A numeric field could not be interpreted.
        """
        ...
