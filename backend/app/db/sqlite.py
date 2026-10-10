"""SQLite ledger: connection management, schema migration, and idempotent writes.

The ledger is the system of record. Everything else in the application -- lots, positions, wash-sale
adjustments, realised gains -- is derived from it and can be thrown away and rebuilt.

Idempotency lives in :func:`insert_transactions`. Transaction ids are deterministic hashes of the
identifying fields, so a re-imported overlapping export collides on the primary key and is skipped.
Crucially the insert does *not* silently overwrite: a row whose id already exists but whose content
differs is reported as a conflict, because that means either the broker restated the data or the
adapter changed, and both deserve a human look.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from app.core.ids import stable_id
from app.core.models import (
    Account,
    AccountStatus,
    AccountType,
    Broker,
    ImportRecord,
    Instrument,
    InstrumentKind,
    TaxTreatment,
    Transaction,
    TxnAction,
)

logger = logging.getLogger(__name__)

#: Every value `Broker`/`TxnAction` recognise in *this* build, precomputed once rather than re-walking
#: the enum on every row -- see `_known_txn_enums` and `fetch_accounts` for why a row naming anything
#: else is degraded rather than left to raise `ValueError` out of `Broker(...)`/`TxnAction(...)`.
_KNOWN_BROKER_VALUES = frozenset(b.value for b in Broker)
_KNOWN_TXN_ACTION_VALUES = frozenset(a.value for a in TxnAction)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 5
"""2 added `executed_at_utc` (see `_migrate_executed_at_utc`); 3 drops `derived_build` (see
`_migrate_drop_derived_build`); 4 adds `replay_order`, which corrects a replay that ran every
trading day backwards for the two brokers that publish no execution time (see
`_migrate_replay_order`); 5 adds `account.status` (open | closed), defaulted to 'open' for every
existing row (see `_migrate_account_status`). `migrate` upgrades an existing database in place;
see MIGRATION.md."""

__all__ = [
    "InsertReport",
    "connect",
    "fetch_accounts",
    "fetch_instruments",
    "fetch_symbol_aliases",
    "fetch_transactions",
    "insert_transactions",
    "ledger_fingerprint",
    "migrate",
    "transaction_from_row",
    "upsert_account",
    "upsert_instrument",
    "upsert_symbol_alias",
]


def _adapt_decimal(value: Decimal) -> str:
    return format(value, "f")


sqlite3.register_adapter(Decimal, _adapt_decimal)


_BUSY_TIMEOUT_MS = 15_000
"""How long a writer waits for another writer's lock before giving up, in milliseconds.

WAL lets any number of readers coexist with one writer, but it still serialises writer against
writer -- a second ``BEGIN IMMEDIATE`` (or plain ``INSERT``/``UPDATE``) while another connection
holds the write lock has to wait its turn. Left unset, ``sqlite3.connect`` uses the stdlib default
of a 5 second lock wait, and SQLite's own busy handler is not installed at all -- so a second
writer that cannot get the lock within that window does not wait longer, it raises
``sqlite3.OperationalError: database is locked`` straight into the caller. That is not a slow
query; it is a *transient* condition -- the write would have gone through if it had waited another
moment -- surfaced as a hard failure (a 500 to a user, e.g.
``thesis-holdout-ledger-race-database-locked-500``) for an operation that had every chance of
succeeding.

This is a local, single-user application: the only thing a write can ever be contending with is
another request the same person just made (a second tab, a double-click, an import racing a
holdout write), not an unrelated tenant. 15 seconds is comfortably longer than any write this
module does -- none of them hold the lock for more than a handful of statements -- while still
being short enough that a genuinely stuck connection (e.g. a deadlock) fails within a request
timeout instead of hanging the caller indefinitely. Anything under ~10s risks the same spurious
500 under ordinary contention; anything past ~30s starts trading a rare, real hang for a much
longer wait on the common, transient case.

``sqlite3.connect(..., timeout=...)`` and ``PRAGMA busy_timeout`` are **the same knob**, not two
that have to agree. CPython implements the ``timeout`` argument by calling ``sqlite3_busy_timeout``
on the new connection, so the pragma below re-states in SQL what the constructor already set.
Checked rather than assumed: a ``mode=ro`` connection, which never executes that pragma, still
reports ``PRAGMA busy_timeout`` as 15000.

Both are kept anyway, and the reason is documentation rather than mechanism -- ``timeout`` is an
easy argument to read as a *connect* timeout, which it is not, and the pragma beside it names the
behaviour in SQLite's own vocabulary. Driving both from one constant means they cannot drift into
disagreeing about a value that is really only stored once.
"""


@contextmanager
def connect(path: Path, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
    """Open the ledger with the pragmas this schema depends on.

    ``foreign_keys`` is off by default in SQLite and must be enabled per connection, otherwise the
    referential integrity declared in ``schema.sql`` is decorative.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    uri = f"file:{path.as_posix()}{'?mode=ro' if read_only else ''}"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        if not read_only:
            conn.execute("PRAGMA journal_mode = WAL")
            # Guarded with ``journal_mode`` because a ``mode=ro`` connection takes no write lock
            # and this restates a value it already has. Note it *does* already have it: the
            # ``timeout`` argument on the constructor above sets the same busy handler on every
            # connection, read-only included, so this line changes nothing at runtime and exists
            # to name the behaviour where a reader will look for it.
            conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        yield conn
    finally:
        conn.close()


def migrate(conn: sqlite3.Connection) -> int:
    """Apply the schema if absent, then run any in-place upgrades. Returns the resulting schema version.

    The schema is written with ``IF NOT EXISTS`` throughout, so ``executescript`` is safe to run on
    every startup and does nothing to a database that already has every table. Column-level changes
    to an existing table are not expressible that way -- ``CREATE TABLE IF NOT EXISTS`` does not add
    columns to a table that already exists -- so those live in dedicated ``_migrate_*`` steps that do
    their own existence checks and are individually safe to run twice. There is exactly one such step
    today: :func:`_migrate_executed_at_utc`.
    """
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate_executed_at_utc(conn)
    _migrate_replay_order(conn)
    _migrate_symbol_alias_backfill(conn)
    _migrate_drop_derived_build(conn)
    _migrate_account_status(conn)

    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = int(row["v"]) if row is not None and row["v"] is not None else 0
    if current < SCHEMA_VERSION:
        # A fresh database (current == 0) and an upgraded one (current == 1, pre-executed_at_utc)
        # both land here exactly once: the second `migrate` call always sees current == SCHEMA_VERSION
        # and takes the early return below instead, so no duplicate row is ever inserted.
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, dt.datetime.now(dt.UTC).isoformat()),
        )
        return SCHEMA_VERSION
    return current


def _migrate_executed_at_utc(conn: sqlite3.Connection) -> None:
    """Add and backfill ``txn.executed_at_utc`` on every database, fresh or pre-existing.

    ``schema.sql`` deliberately does *not* declare this column -- ``CREATE TABLE IF NOT EXISTS`` runs
    only against a table that does not yet exist, so it cannot be the vehicle for adding a column to
    one that already does, and a brand-new database and a five-year-old one need to end up with the
    same shape. Routing both through one ``ALTER TABLE`` step here means there is only one code path
    to trust rather than "schema.sql for new databases, this function for old ones" silently drifting
    apart.

    This is the fix for a real ordering bug, not a cosmetic addition. ``fetch_transactions`` used to
    order by the ``executed_at`` text column directly, and Webull timestamps carry a fixed UTC offset
    that legitimately changes across the November DST changeover (``-04:00`` before, ``-05:00``
    after -- see ``app/ingest/adapters/webull.py:_pin_offset``). ISO strings with different offsets do
    not sort chronologically as text, so a same-day sale in the repeated hour could be replayed
    against the wrong lot, silently producing the wrong cost basis. ``executed_at_utc`` is a
    fixed-width UTC rendering of the same instant, which *does* sort correctly as text, and
    ``fetch_transactions`` now orders on it instead.

    Safe to run twice, and safe to run against a database with real user data:

    * The column add is guarded by a ``PRAGMA table_info`` check rather than ``ADD COLUMN IF NOT
      EXISTS`` -- SQLite's ``ALTER TABLE ADD COLUMN`` does not accept ``IF NOT EXISTS`` (unlike
      ``CREATE TABLE``/``CREATE INDEX``), so the equivalent has to be spelled out by hand.
    * The backfill ``UPDATE`` only touches rows where ``executed_at_utc IS NULL`` while ``executed_at``
      is not, so a second run has nothing left to do -- it is not merely idempotent by producing the
      same result twice, it does zero work the second time.
    * Nothing here rewrites ``executed_at`` or any other existing column, so a user is never asked to
      re-import to get this fix.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(txn)")}
    if "executed_at_utc" not in columns:
        conn.execute("ALTER TABLE txn ADD COLUMN executed_at_utc TEXT")

    rows = conn.execute(
        "SELECT txn_id, executed_at FROM txn WHERE executed_at IS NOT NULL AND executed_at_utc IS NULL"
    ).fetchall()
    if not rows:
        return
    updates = [
        (_executed_at_utc(dt.datetime.fromisoformat(row["executed_at"])), row["txn_id"])
        for row in rows
    ]
    conn.executemany("UPDATE txn SET executed_at_utc = ? WHERE txn_id = ?", updates)


def _migrate_replay_order(conn: sqlite3.Connection) -> None:
    """Add and backfill ``txn.replay_order``: the chronological rank of a row within its file.

    **This corrects a wrong position, not a wrong presentation.** ``fetch_transactions`` used to
    break same-date ties on ``source_row``, on the stated assumption that "the export's own row order
    is the only evidence of what happened first". All three brokers write their exports
    *newest-first*, so that replayed every trading day backwards. Where the broker publishes an
    execution timestamp (Webull) the timestamp dominated and nothing was wrong. Where it does not
    (Robinhood, SoFi), a day's round trip replayed as sell-then-buy: the sale found no lot, booked a
    zero-basis disposal and raised ``oversold``, and the purchase opened a lot nothing ever closed.

    Measured on a real ledger against the broker statement: equal buy and sell totals in
    heavily-traded leveraged ETFs left large phantom positions in symbols that were no longer held.
    Many symbols in one Robinhood account were affected and more carried inflated quantities; the
    Webull accounts reconciled exactly. The overstatement of that account's market value was large.

    The backfill has to reconstruct what the adapter would now emit, from what is stored:

    * ``replay_order = (max source_row in that import) - source_row`` for a newest-first adapter,
      matching :meth:`ExportOrder.replay_order_for` exactly -- the maximum stored ``source_row`` is
      the file's last usable row, and since only relative order matters, using it in place of the
      file's true row count shifts every row in the import by the same constant.
    * Grouped **per import**, never globally: each file has its own row numbering, and two imports
      into one account would otherwise interleave.
    * Adapters are read from ``raw_import.adapter``, so an oldest-first adapter added later is left
      alone rather than reversed.

    Safe to run twice: the column add is guarded by ``PRAGMA table_info`` (SQLite's ``ADD COLUMN``
    takes no ``IF NOT EXISTS``), and the backfill runs only when the column has just been added.
    Doing it on the existing rows rather than requiring a re-import matters because ``replay_order``
    is not part of ``txn_id`` -- no stored identity changes, so there is nothing for a user to redo.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(txn)")}
    if "replay_order" in columns:
        return
    conn.execute("ALTER TABLE txn ADD COLUMN replay_order INTEGER NOT NULL DEFAULT 0")

    newest_first = {
        row["import_id"]
        for row in conn.execute("SELECT import_id, adapter FROM raw_import")
        if row["adapter"] in _NEWEST_FIRST_ADAPTERS
    }
    if not newest_first:
        return
    placeholders = ", ".join("?" for _ in newest_first)
    conn.execute(
        "UPDATE txn SET replay_order = ("
        "  SELECT MAX(peer.source_row) FROM txn AS peer WHERE peer.import_id = txn.import_id"
        ") - source_row "
        f"WHERE import_id IN ({placeholders})",
        tuple(newest_first),
    )


def _migrate_account_status(conn: sqlite3.Connection) -> None:
    """Add ``account.status``, defaulted to ``'open'`` for every row that predates the column.

    ``schema.sql`` declares ``status TEXT NOT NULL DEFAULT 'open'`` for brand-new databases, but
    ``CREATE TABLE IF NOT EXISTS`` does not touch a table that already exists, so an existing ledger
    needs the same ``ALTER TABLE`` treatment as ``executed_at_utc`` and ``replay_order`` above.
    Unlike those two this needs no data backfill beyond the column default itself: SQLite applies a
    constant ``DEFAULT`` to every existing row when the column is added, not only to rows inserted
    afterward, so every account that predates this migration is correctly `open` -- the real status
    of a closed account arrives the next time `python -m app.ingest` upserts it from the manifest,
    the same as any other manifest-declared field.

    Safe to run twice: guarded by the same ``PRAGMA table_info`` check as the other migrations here,
    since SQLite's ``ALTER TABLE ADD COLUMN`` has no ``IF NOT EXISTS`` form.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(account)")}
    if "status" not in columns:
        conn.execute("ALTER TABLE account ADD COLUMN status TEXT NOT NULL DEFAULT 'open'")


#: Adapters known to write newest-first, for :func:`_migrate_replay_order`'s backfill only. New code
#: must read ``BrokerAdapter.export_order`` instead -- this list exists because a migration reads a
#: stored adapter *name* from `raw_import` and cannot import an adapter that may since have been
#: renamed or removed. Deliberately not derived from the registry for that reason.
_NEWEST_FIRST_ADAPTERS = frozenset({"robinhood", "webull", "sofi"})


def _migrate_drop_derived_build(conn: sqlite3.Connection) -> None:
    """Remove ``derived_build``, which recorded rebuilds of derived tables that do not exist.

    It was designed in Phase 1 for an architecture where lots, positions, wash-sale adjustments and
    gains would be *materialised* in SQLite and rebuilt on each import -- see ``schema.sql``'s
    header, which still described that plan. That is not what got built. Every derived figure in
    this application is recomputed from the ledger on each request, deliberately:
    :mod:`app.api.tax`'s module docstring makes the argument, that a cache which can silently go
    stale against a re-import is how a tax page ends up showing figures that no longer match the
    ledger underneath it.

    So the table was never written by production code, ``/api/health/stores`` reported
    ``never_built`` forever, and the Portfolio page carried a "Derived state: not built" badge
    sitting beside figures that were correct and current. A UAT persona flagged it as unexplained
    and said it made them second-guess a page that did not deserve it. A status that is permanently
    true and permanently irrelevant is worse than no status: it spends the reader's attention and
    teaches them to discount the row it sits in.

    **Only dropped when empty.** Nothing ever wrote it, so it is empty everywhere -- but this file's
    standing rule is that source data is never deleted, and a table with rows in it would be
    evidence that something did write it after all, which is a thing to look at rather than to
    discard. Measured, not assumed.

    If ledger growth ever forces a materialised derivation, that is a design change which brings its
    own bookkeeping, and this table is one ``git revert`` away. For the record, at roughly a thousand
    transactions the full replay measures ~290ms, of which wash-sale matching is ~234ms.
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'derived_build'"
    ).fetchone()
    if exists is None:
        return

    rows = conn.execute("SELECT COUNT(*) AS n FROM derived_build").fetchone()["n"]
    if rows:  # pragma: no cover - nothing has ever written this table
        return
    conn.execute("DROP TABLE derived_build")


def _migrate_symbol_alias_backfill(conn: sqlite3.Connection) -> None:
    """Populate ``symbol_alias`` from ``txn`` rows written before this table had a writer.

    ``symbol_alias`` (``symbol``, ``broker``, ``instrument_id``) was part of the schema from the
    start -- see ``schema.sql``'s comment naming it as source-tier, alongside ``txn`` and
    ``instrument`` -- but nothing ever wrote to it until :func:`insert_transactions` started doing so
    below. A ledger populated before that change has every fact this table needs sitting on ``txn``
    already: ``symbol``, ``broker`` and ``instrument_id`` are columns on every row. Backfilling from
    them is the same move as :func:`_migrate_executed_at_utc` -- deriving a new table from data the
    ledger already has, not re-parsing anything -- so it is safe against ``data/store/ledger.sqlite``
    without touching a CSV or hand-editing a row.

    ``INSERT OR IGNORE`` keyed on the table's own ``(symbol, broker)`` primary key makes this
    idempotent: a second run, or a run against a database this has already populated, inserts
    nothing.

    Note this backfill can only see whatever ``instrument_id`` a row was stored with at import time.
    It does not itself resolve the cross-broker split this migration exists alongside --
    :func:`app.core.canonical.canonicalize_ledger` does that, at derive time, from the ledger's
    current contents, and does not depend on this table being populated.
    """
    conn.execute(
        """
        INSERT OR IGNORE INTO symbol_alias (symbol, broker, instrument_id)
        SELECT DISTINCT symbol, broker, instrument_id
        FROM txn
        WHERE symbol IS NOT NULL AND instrument_id IS NOT NULL
        """
    )


# ---------------------------------------------------------------------------
# Reference entities
# ---------------------------------------------------------------------------


def upsert_account(conn: sqlite3.Connection, account: Account) -> None:
    conn.execute(
        """
        INSERT INTO account (account_id, broker, label, tax_treatment, account_type, status)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (account_id) DO UPDATE SET
            broker = excluded.broker,
            label = excluded.label,
            tax_treatment = excluded.tax_treatment,
            account_type = excluded.account_type,
            status = excluded.status
        """,
        (
            account.account_id,
            account.broker.value,
            account.label,
            account.tax_treatment.value,
            account.account_type.value,
            account.status.value,
        ),
    )


def upsert_instrument(conn: sqlite3.Connection, instrument: Instrument) -> None:
    conn.execute(
        """
        INSERT INTO instrument (instrument_id, primary_symbol, cusip, name, kind, is_priceable)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (instrument_id) DO UPDATE SET
            primary_symbol = excluded.primary_symbol,
            cusip = COALESCE(excluded.cusip, instrument.cusip),
            name = COALESCE(excluded.name, instrument.name),
            kind = excluded.kind,
            is_priceable = excluded.is_priceable
        """,
        (
            instrument.instrument_id,
            instrument.primary_symbol,
            instrument.cusip,
            instrument.name,
            instrument.kind.value,
            int(instrument.is_priceable),
        ),
    )


def upsert_symbol_alias(
    conn: sqlite3.Connection, *, symbol: str, broker: str, instrument_id: str
) -> None:
    """Record that this broker, spelling a symbol exactly this way, resolved it to this instrument.

    One row per ``(symbol, broker)`` -- the literal spelling a broker's own export uses, e.g.
    ``BRK.B``/``robinhood`` and ``BRK-B``/``webull`` as two separate rows, both eventually pointing at
    the same instrument once :func:`app.core.canonical.canonicalize_ledger` has resolved it. The
    ``instrument_id`` stored here is whatever the adapter assigned *at parse time*, which may be
    symbol-keyed rather than the eventual CUSIP-keyed canonical id -- this table is a provenance
    record of what each broker said, not itself the resolved cross-broker identity. ``ON CONFLICT ...
    DO UPDATE`` makes a re-import update the row to the latest-known assignment rather than erroring,
    matching every other idempotent write in this module.
    """
    conn.execute(
        """
        INSERT INTO symbol_alias (symbol, broker, instrument_id)
        VALUES (?, ?, ?)
        ON CONFLICT (symbol, broker) DO UPDATE SET
            instrument_id = excluded.instrument_id
        """,
        (symbol, broker, instrument_id),
    )


def record_import(conn: sqlite3.Connection, record: ImportRecord) -> None:
    conn.execute(
        """
        INSERT INTO raw_import (
            import_id, source_path, filename, file_sha256, content_hash, broker, account_id,
            adapter, adapter_version, row_count, usable_row_count, imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.import_id,
            record.source_path,
            record.filename,
            record.file_sha256,
            record.content_hash,
            record.broker.value,
            record.account_id,
            record.adapter,
            record.adapter_version,
            record.row_count,
            record.usable_row_count,
            record.imported_at.isoformat(),
        ),
    )


#: Where :class:`csv.DictReader` parks fields that overflow the declared header. The reader uses
#: ``None`` as that key, which is not a JSON object key and — with ``sort_keys=True`` — is not even
#: comparable against the real column names. Renaming it to a visible sentinel keeps the row
#: serialisable and keeps the overflow content, which is the part worth preserving.
_RESTKEY_COLUMN = "__unmapped__"


def record_raw_rows(
    conn: sqlite3.Connection,
    import_id: str,
    rows: Iterable[dict[str, str | None]],
) -> int:
    """Store every source row verbatim as JSON.

    This is what keeps "trace this figure back to the CSV" answerable after the original file has been
    moved, renamed or replaced by a newer export.

    Rows are normalised only in one respect, and it is not a loss of fidelity: a row with more fields
    than the header declares carries them under ``DictReader``'s ``None`` restkey, which is moved to
    ``__unmapped__``. Robinhood's second footer row is exactly this shape -- it holds a tax
    disclaimer past the last declared column -- so every real Robinhood import hits it.
    """
    payload = [
        (import_id, index, json.dumps(_serialisable(row), ensure_ascii=False, sort_keys=True))
        for index, row in enumerate(rows)
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO raw_row (import_id, row_index, content) VALUES (?, ?, ?)",
        payload,
    )
    return len(payload)


def _serialisable(row: dict[str, str | None]) -> dict[str, object]:
    """A source row with JSON-safe keys, content untouched.

    Only the ``None`` key is rewritten. Its value is whatever ``DictReader`` collected -- a list of
    the overflow fields, not a string -- and it is stored as-is rather than joined, so the stored row
    still says how many fields overflowed.
    """
    if None not in row:
        return dict(row)
    converted: dict[str, object] = {}
    for key, value in row.items():
        converted[_RESTKEY_COLUMN if key is None else key] = value
    return converted


def find_import_by_content(
    conn: sqlite3.Connection,
    content_hash: str,
    *,
    account_id: str | None = None,
) -> sqlite3.Row | None:
    """Look for a previous import of byte-equivalent content, to skip redundant work.

    ``account_id`` narrows the search to one account, which is what a re-import check actually
    wants: the same export loaded into a *different* account is a different import, not a repeat of
    this one. Without the filter, a file that had been re-assigned between accounts would match the
    other account's row -- most recent first -- and the caller would conclude it had already
    imported content it had not.
    """
    # sqlite3.Cursor.fetchone() is typed as returning Any, so the result is bound and annotated
    # before returning rather than passed straight through.
    if account_id is None:
        row: sqlite3.Row | None = conn.execute(
            "SELECT * FROM raw_import WHERE content_hash = ? ORDER BY imported_at DESC LIMIT 1",
            (content_hash,),
        ).fetchone()
        return row
    row = conn.execute(
        "SELECT * FROM raw_import WHERE content_hash = ? AND account_id = ? "
        "ORDER BY imported_at DESC LIMIT 1",
        (content_hash, account_id),
    ).fetchone()
    return row


# ---------------------------------------------------------------------------
# Ledger writes
# ---------------------------------------------------------------------------

_TXN_COLUMNS = (
    "txn_id", "import_id", "source_row", "replay_order", "account_id", "broker", "action",
    "trade_date", "settle_date", "executed_at", "executed_at_utc", "sequence",
    "symbol", "cusip", "instrument_id",
    "quantity", "price", "fees", "amount",
    "currency", "description", "transfer_group", "raw_code",
)


def _executed_at_utc(value: dt.datetime | None) -> str | None:
    """Offset-independent sort key for ``executed_at``: the same instant, rendered in UTC.

    Two aware datetimes that denote different instants can still text-sort in the wrong order if
    they carry different UTC offsets -- exactly what happens to Webull's ``executed_at`` across a
    DST changeover, where the adapter deliberately emits ``-04:00`` (EDT) before the fall-back and
    ``-05:00`` (EST) after it, for good reason (see ``_pin_offset`` in
    ``app/ingest/adapters/webull.py``). Normalising to one offset -- UTC -- before formatting removes
    the degree of freedom that broke the sort; comparing the resulting strings is then equivalent to
    comparing the instants.

    ``timespec="microseconds"`` is not decoration: without it, ``isoformat()`` omits the fractional
    part entirely when it is zero, so rows would carry mixed-width strings and the fixed-width
    assumption text sorting depends on would quietly stop holding for a mixed batch.
    """
    if value is None:
        return None
    return value.astimezone(dt.UTC).isoformat(timespec="microseconds")

@dataclass(slots=True)
class InsertReport:
    """Outcome of an idempotent ledger write."""

    inserted: int = 0
    duplicates: int = 0
    """Already present with identical material content. The expected result of re-importing."""
    conflicts: list[tuple[str, str, object, object]] = field(default_factory=list)
    """``(txn_id, field, existing, incoming)`` where a stored row disagrees with the incoming one.
    Surfaced for review rather than overwritten -- a restated figure must not silently replace a
    number that may already have been reported on a tax form."""

    @property
    def total(self) -> int:
        return self.inserted + self.duplicates + len(self.conflicts)

    @property
    def is_clean(self) -> bool:
        return not self.conflicts


def _txn_row(txn: Transaction) -> tuple[object, ...]:
    return (
        txn.txn_id,
        txn.import_id,
        txn.source_row,
        txn.replay_order,
        txn.account_id,
        txn.broker.value,
        txn.action.value,
        txn.trade_date.isoformat(),
        txn.settle_date.isoformat() if txn.settle_date else None,
        txn.executed_at.isoformat() if txn.executed_at else None,
        _executed_at_utc(txn.executed_at),
        txn.sequence,
        txn.symbol,
        txn.cusip,
        txn.instrument_id,
        _dec(txn.quantity),
        _dec(txn.price),
        _dec(txn.fees),
        _dec(txn.amount),
        txn.currency,
        txn.description,
        txn.transfer_group,
        txn.raw_code,
    )


def _dec(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _material_view(txn: Transaction) -> dict[str, object]:
    return {
        "account_id": txn.account_id,
        "broker": txn.broker.value,
        "action": txn.action.value,
        "trade_date": txn.trade_date.isoformat(),
        "settle_date": txn.settle_date.isoformat() if txn.settle_date else None,
        "symbol": txn.symbol,
        "cusip": txn.cusip,
        "quantity": _dec(txn.quantity),
        "price": _dec(txn.price),
        "fees": _dec(txn.fees),
        "amount": _dec(txn.amount),
        "currency": txn.currency,
    }


def insert_transactions(
    conn: sqlite3.Connection,
    transactions: Sequence[Transaction],
) -> InsertReport:
    """Insert transactions idempotently.

    New ids are inserted. Ids already present are compared field by field: identical content counts
    as a duplicate and is skipped; differing content is recorded as a conflict and **not** written.

    Numeric comparison is done on canonical decimal strings, so a broker switching from ``50`` to
    ``50.00`` between exports does not register as a conflict.
    """
    report = InsertReport()
    if not transactions:
        return report

    incoming_ids = [t.txn_id for t in transactions]
    existing: dict[str, sqlite3.Row] = {}
    # Chunked to stay under SQLite's variable limit on large imports.
    for start in range(0, len(incoming_ids), 500):
        chunk = incoming_ids[start : start + 500]
        placeholders = ",".join("?" * len(chunk))
        for row in conn.execute(
            f"SELECT * FROM txn WHERE txn_id IN ({placeholders})",
            chunk,
        ):
            existing[row["txn_id"]] = row

    to_insert: list[tuple[object, ...]] = []
    for txn in transactions:
        prior = existing.get(txn.txn_id)
        if prior is None:
            to_insert.append(_txn_row(txn))
            continue

        differences = [
            (name, prior[name], value)
            for name, value in _material_view(txn).items()
            if _normalise(prior[name]) != _normalise(value)
        ]
        if differences:
            report.conflicts.extend((txn.txn_id, n, old, new) for n, old, new in differences)
        else:
            report.duplicates += 1

    if to_insert:
        placeholders = ",".join("?" * len(_TXN_COLUMNS))
        conn.executemany(
            f"INSERT INTO txn ({','.join(_TXN_COLUMNS)}) VALUES ({placeholders})",
            to_insert,
        )
        report.inserted = len(to_insert)

    # Populate symbol_alias for every transaction this call saw, not just newly-inserted ones -- a
    # re-import of an already-present file must still be able to backfill an alias this table did not
    # have before. Independent of insert/duplicate/conflict: the alias records what the broker wrote
    # and what the adapter resolved it to, which is true regardless of whether the txn row itself was
    # new. See app.core.canonical for why this table is populated but not depended on for the actual
    # cross-broker identity fix -- that runs at derive time over the ledger's current contents.
    for txn in transactions:
        if txn.symbol and txn.instrument_id:
            upsert_symbol_alias(
                conn, symbol=txn.symbol, broker=txn.broker.value, instrument_id=txn.instrument_id
            )

    return report


def _normalise(value: object) -> object:
    """Compare decimal-bearing text by numeric value, everything else by identity of text."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            return format(Decimal(value).normalize(), "f")
        except Exception:
            return value
    return value


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def fetch_transactions(
    conn: sqlite3.Connection,
    *,
    account_id: str | None = None,
    instrument_id: str | None = None,
) -> list[sqlite3.Row]:
    """Read the ledger in deterministic replay order.

    Ordering is ``(trade_date, executed_at_utc, account_id, replay_order, source_row, txn_id)``.

    **``account_id`` is in the key because otherwise a hash decided real money.** Robinhood publishes
    no execution time, so its rows carry a NULL ``executed_at_utc``; every file has a row 0, a row 1
    and so on; and this function is called without an account filter for the full replay. Two rows in
    *different* accounts, on the same date, at the same position therefore tied on the first three
    terms and fell through to ``txn_id`` -- a hash, i.e. an arbitrary order that changes whenever the
    id derivation changes.

    Measured on a real ledger, comparing two databases with byte-identical transaction content and
    only their id scheme different: realised short-term gain, deferred wash-sale losses and the
    permanently disallowed total all moved by hundreds of dollars. The event *count* was the same both times; what moved was which disposal each
    replacement purchase attached to.

    Same-day cross-account attribution is genuinely underdetermined by the data -- nothing in a
    Robinhood export says whether the Roth trade or the taxable one came first -- so no ordering here
    is more *correct* than another. What this key buys is that the answer stops depending on a hash:
    it is stable across re-imports, reproducible from the ledger alone, and inspectable by anyone
    reading a row. The remaining arbitrariness is confined to the choice of alphabetical account
    order, which is at least visible.

    The final ``txn_id`` term still makes the order total, for rows that tie on everything else.

    **The fourth term is ``replay_order``, not ``source_row``, and that distinction is the whole
    point.** For a broker that publishes no time of day the export's own row order is the only
    evidence of what happened first -- but *which way round* it runs is a fact about the file, and
    all three of these brokers write newest-first. Ordering on ``source_row`` therefore replayed
    every trading day backwards. A Robinhood day of ``buy 50, sell 50`` replayed as ``sell 50, buy
    50``: the sale found no lot, booked a zero-basis disposal and raised ``oversold``, and the
    purchase opened a lot nothing closed. Across a year that turned equal buy and sell totals
    into large phantom positions, and many symbols in one account into holdings that were
    not owned -- a large amount of invented market value, while the accounts whose broker
    *does* publish a timestamp reconciled to the share. ``replay_order`` is the adapter's own
    chronological rank (:class:`app.ingest.adapters.base.ExportOrder`); ``source_row`` stays as the
    provenance join to ``raw_row`` and remains in the key only to make the order total within a file.

    ``sequence`` is not in the key at all. It used to hold the row's file position and was used here;
    it now holds an ordinal among a row's *duplicates* (see
    :class:`app.core.ids.TransactionSequencer`, which changed it so that identity survives a longer
    re-export), which is almost always ``0`` and carries no ordering information. Left on
    ``sequence`` the tie-break silently fell through to ``txn_id`` -- a hash, i.e. an arbitrary
    order for same-day trades, because :func:`app.core.lots._consume_fifo` trusts this order to
    choose between lots sharing an ``acquired_date``.

    Sorting is done on ``executed_at_utc``, a UTC-normalised copy of ``executed_at``, and deliberately
    not on ``executed_at`` itself. ``executed_at`` legitimately carries different fixed UTC offsets
    across a DST changeover (Webull's adapter pins ``-04:00``/EDT before the fall-back and
    ``-05:00``/EST after it, on purpose -- see ``_pin_offset`` in ``app/ingest/adapters/webull.py``),
    and ISO datetime strings with different offsets do not compare chronologically as text. Sorting
    on the raw column would silently reverse same-day trades that straddle the repeated hour, and
    :func:`app.core.lots._consume_fifo` trusts this order to break ties when two lots share an
    ``acquired_date`` -- a reversed fetch there means a same-day sale can consume the wrong lot,
    which is a wrong cost basis and a wrong realised gain, not merely a display quirk. NULL
    ``executed_at_utc`` sorts first within a ``trade_date`` (SQLite's default for ``ORDER BY ASC``),
    matching the old ``COALESCE(executed_at, '')`` behaviour, so rows without an execution time fall
    back to ``(trade_date, account_id, source_row, txn_id)``.
    """
    clauses: list[str] = []
    params: list[object] = []
    if account_id:
        clauses.append("account_id = ?")
        params.append(account_id)
    if instrument_id:
        clauses.append("instrument_id = ?")
        params.append(instrument_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM txn {where} "
        "ORDER BY trade_date, executed_at_utc, account_id, replay_order, source_row, txn_id",
        params,
    ).fetchall()
    return [row for row in rows if _known_txn_enums(row)]


def _known_txn_enums(row: sqlite3.Row) -> bool:
    """`True` when `row`'s `broker` and `action` are both values the current build's `Broker`/
    `TxnAction` enums recognise; `False`, after a loud `WARNING`, for anything else.

    **Why this filters here rather than inside `transaction_from_row`.** That function is called
    directly, per row, from four call sites this module cannot reach to edit
    (`app.api.transactions`, `app.api.portfolio`, `app.market.calendar`, `app.tax.engine`), every one
    of them a bare ``[transaction_from_row(row) for row in fetch_transactions(conn)]``. Making
    `transaction_from_row` itself tolerate a bad row would have to return `Transaction | None` to do
    it, which would put a `None` into every one of those callers' `list[Transaction]` -- a defect at
    each call site, and a worse failure than the `ValueError` this exists to prevent, since it would
    surface later and further from its cause. Filtering the row out here, before it ever reaches
    `transaction_from_row`, keeps that function's contract exactly as it was -- it still raises
    immediately on anything it does not recognise, which is correct for its other role validating a
    row an adapter is about to write (see `TxnAction`'s own docstring: "raise on anything
    unrecognised") -- while giving this module's *read* path, the one place that can safely see "the
    ledger already contains a token this build does not know", somewhere to degrade instead of 500ing
    every endpoint that reads the ledger (`/api/portfolio`, `/api/tax`, `/api/transactions`) over one
    bad row.

    **This is not expected to ever fire in normal operation.** Every stored row was validated against
    these same enums by the adapter that wrote it. A row failing this check means the *build reading
    it* is older, or differently configured, than the one that wrote it -- a schema drift, a
    hand-edited database, or a future broker adapter this build has not seen -- which is exactly why
    this logs at `WARNING` (loud enough that it will not go unnoticed) rather than silently thinning
    the transactions a caller gets back.
    """
    broker_value = row["broker"]
    if broker_value not in _KNOWN_BROKER_VALUES:
        logger.warning(
            "sqlite: txn %s (account %s) has unknown broker %r -- excluding it from the fetched "
            "transactions until the ledger or this build is corrected",
            row["txn_id"],
            row["account_id"],
            broker_value,
        )
        return False
    action_value = row["action"]
    if action_value not in _KNOWN_TXN_ACTION_VALUES:
        logger.warning(
            "sqlite: txn %s (account %s) has unknown action %r -- excluding it from the fetched "
            "transactions until the ledger or this build is corrected",
            row["txn_id"],
            row["account_id"],
            action_value,
        )
        return False
    return True


def _opt_decimal(value: object) -> Decimal | None:
    """Read a decimal column back without going through :class:`float`.

    Decimal columns are stored as text for exactly this reason: ``Decimal(str(x))`` round-trips a
    broker figure unchanged, whereas a float hop would reintroduce the representation error the
    models refuse at their boundary.
    """
    return None if value is None else Decimal(str(value))


def transaction_from_row(row: sqlite3.Row) -> Transaction:
    """Rebuild a :class:`~app.core.models.Transaction` from a ``txn`` row.

    The inverse of :func:`_txn_row`. Derived state -- lots, wash-sale adjustments, gains -- is
    rebuilt from these on every request rather than stored, so this is the hot path into the tax
    engine and the only place row shape is translated back into a model.
    """
    return Transaction(
        txn_id=row["txn_id"],
        import_id=row["import_id"],
        source_row=int(row["source_row"]),
        replay_order=int(row["replay_order"]),
        account_id=row["account_id"],
        broker=Broker(row["broker"]),
        action=TxnAction(row["action"]),
        trade_date=dt.date.fromisoformat(row["trade_date"]),
        settle_date=dt.date.fromisoformat(row["settle_date"]) if row["settle_date"] else None,
        executed_at=(
            dt.datetime.fromisoformat(row["executed_at"]) if row["executed_at"] else None
        ),
        sequence=int(row["sequence"]),
        symbol=row["symbol"],
        cusip=row["cusip"],
        instrument_id=row["instrument_id"],
        quantity=_opt_decimal(row["quantity"]),
        price=_opt_decimal(row["price"]),
        fees=Decimal(str(row["fees"])) if row["fees"] is not None else Decimal(0),
        amount=_opt_decimal(row["amount"]),
        currency=row["currency"],
        description=row["description"],
        transfer_group=row["transfer_group"],
        raw_code=row["raw_code"],
    )


def fetch_accounts(conn: sqlite3.Connection) -> list[Account]:
    """Every registered account. The tax engine needs all of them at once.

    A per-account query would be the natural shape and the wrong one: a replacement purchase in any
    account the user controls triggers the wash-sale rule, so the engine must see all of them
    together or it will miss cross-broker and taxable-to-IRA cases entirely.

    An account row naming a `broker` value outside the current build's `Broker` enum is excluded
    rather than left to raise `ValueError` out of this function -- the same "degrade with a loud
    warning, never a silent drop" rule `_known_txn_enums` applies to `txn` rows, applied here to
    `account` for the identical reason: one row this build does not recognise must not 500 every
    endpoint that calls this function (`/api/portfolio`, `/api/tax`, `app.ingest.service`) rather than
    just omitting that one account.
    """
    accounts: list[Account] = []
    for row in conn.execute("SELECT * FROM account ORDER BY account_id"):
        broker_value = row["broker"]
        if broker_value not in _KNOWN_BROKER_VALUES:
            logger.warning(
                "sqlite: account %s has unknown broker %r -- excluding it from the fetched accounts "
                "until the ledger or this build is corrected",
                row["account_id"],
                broker_value,
            )
            continue
        accounts.append(
            Account(
                account_id=row["account_id"],
                broker=Broker(broker_value),
                label=row["label"],
                tax_treatment=TaxTreatment(row["tax_treatment"]),
                account_type=AccountType(row["account_type"]),
                status=AccountStatus(row["status"]),
            )
        )
    return accounts


def fetch_instruments(conn: sqlite3.Connection) -> list[Instrument]:
    """Every known instrument, for resolving display symbols during a rebuild."""
    return [
        Instrument(
            instrument_id=row["instrument_id"],
            primary_symbol=row["primary_symbol"],
            cusip=row["cusip"],
            name=row["name"],
            kind=InstrumentKind(row["kind"]),
            is_priceable=bool(row["is_priceable"]),
        )
        for row in conn.execute("SELECT * FROM instrument ORDER BY instrument_id")
    ]


def fetch_symbol_aliases(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Every ``(symbol, broker, instrument_id)`` row, for audit and for :func:`upsert_symbol_alias`
    round-trip tests. Not consulted by the cross-broker identity fix itself -- see
    ``app.core.canonical``'s module docstring for why that runs against the ledger's current
    contents instead of this table."""
    return [
        (row["symbol"], row["broker"], row["instrument_id"])
        for row in conn.execute("SELECT symbol, broker, instrument_id FROM symbol_alias ORDER BY symbol, broker")
    ]


def ledger_fingerprint(conn: sqlite3.Connection) -> tuple[str, int]:
    """Hash the ledger's transaction ids, for detecting stale derived state.

    Returns ``(fingerprint, txn_count)``. A derived build whose stored fingerprint no longer matches
    was computed against a different ledger and must be rebuilt.
    """
    ids = [r["txn_id"] for r in conn.execute("SELECT txn_id FROM txn ORDER BY txn_id")]
    return stable_id(*ids, length=64), len(ids)
