-- Ledger schema (SQLite).
--
-- Two tiers live here:
--
--   SOURCE   raw_import, raw_row, txn, account, instrument, symbol_alias
--            Append-only. Never edited, never deleted. The transaction ledger is the system of
--            record and everything else is reconstructible from it.
--
--   DERIVED  nothing. Lots, positions, wash-sale adjustments and realised gains are computed from
--            the ledger on every request and never stored, so there is no derived tier here to go
--            stale. That is a deliberate choice, argued in app/api/tax.py's module docstring: a
--            cache that can silently disagree with the ledger underneath it is how a tax page ends
--            up showing figures that are no longer true. This header described a materialised
--            derived tier, and a `derived_build` table recording its rebuilds, until 2026-08-14 --
--            neither was ever built, and the table has been dropped (schema version 3).
--
-- Money and share quantities are TEXT, holding the canonical decimal string. SQLite's REAL is an
-- IEEE double, which would reintroduce exactly the float error the Python layer works to avoid.
-- INTEGER is unusable because fractional shares are pervasive in this data.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Migration bookkeeping
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Provenance
-- ---------------------------------------------------------------------------

-- One row per ingested file.
CREATE TABLE IF NOT EXISTS raw_import (
    import_id         TEXT PRIMARY KEY,
    source_path       TEXT NOT NULL,
    filename          TEXT NOT NULL,
    file_sha256       TEXT NOT NULL,
    -- Hash of parsed content: stable when a broker changes line endings or encoding without
    -- changing data. This is the one to compare when deciding whether a file is a true re-import.
    content_hash      TEXT NOT NULL,
    broker            TEXT NOT NULL,
    account_id        TEXT NOT NULL,
    adapter           TEXT NOT NULL,
    adapter_version   TEXT NOT NULL,
    row_count         INTEGER NOT NULL,
    -- Rows that became transactions. The gap is cancellations, footers and non-events; a change in
    -- this number between two exports of the same period is a regression signal.
    usable_row_count  INTEGER NOT NULL,
    imported_at       TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES account (account_id)
);

CREATE INDEX IF NOT EXISTS ix_raw_import_content ON raw_import (content_hash);
CREATE INDEX IF NOT EXISTS ix_raw_import_account ON raw_import (account_id, imported_at);

-- Every source row, verbatim, as a JSON object of the original column names and values.
-- This is what makes "trace this number back to the CSV" answerable after the file has moved.
CREATE TABLE IF NOT EXISTS raw_row (
    import_id   TEXT NOT NULL,
    row_index   INTEGER NOT NULL,
    content     TEXT NOT NULL,
    PRIMARY KEY (import_id, row_index),
    FOREIGN KEY (import_id) REFERENCES raw_import (import_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- Reference entities
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS account (
    account_id     TEXT PRIMARY KEY,
    broker         TEXT NOT NULL,
    label          TEXT NOT NULL,
    tax_treatment  TEXT NOT NULL,   -- taxable | roth_ira | traditional_ira
    account_type   TEXT NOT NULL,   -- cash | margin | retirement
    status         TEXT NOT NULL DEFAULT 'open'  -- open | closed
);

CREATE TABLE IF NOT EXISTS instrument (
    instrument_id   TEXT PRIMARY KEY,
    primary_symbol  TEXT NOT NULL,
    cusip           TEXT,
    name            TEXT,
    kind            TEXT NOT NULL DEFAULT 'unknown',
    is_priceable    INTEGER NOT NULL DEFAULT 1
);

-- CUSIP is the real identity key; a unique index enforces that two instruments cannot claim one.
CREATE UNIQUE INDEX IF NOT EXISTS ux_instrument_cusip
    ON instrument (cusip) WHERE cusip IS NOT NULL;

-- Broker-specific ticker spellings mapping onto one instrument: BRK.B (Robinhood) and BRK-B (Webull).
CREATE TABLE IF NOT EXISTS symbol_alias (
    symbol         TEXT NOT NULL,
    broker         TEXT NOT NULL,
    instrument_id  TEXT NOT NULL,
    PRIMARY KEY (symbol, broker),
    FOREIGN KEY (instrument_id) REFERENCES instrument (instrument_id)
);

-- ---------------------------------------------------------------------------
-- Ledger
-- ---------------------------------------------------------------------------

-- txn_id is a deterministic hash of the transaction's identifying fields, so re-importing an
-- overlapping export collides here and is skipped. That is the whole idempotency mechanism.
CREATE TABLE IF NOT EXISTS txn (
    txn_id          TEXT PRIMARY KEY,
    import_id       TEXT NOT NULL,
    -- Which line of the file this came from. Provenance only: it joins to raw_row, and it says
    -- nothing about what happened first, because a broker may write its export newest-first.
    source_row      INTEGER NOT NULL,
    -- Chronological rank within the file, ascending = earlier. Set by the adapter, which is the
    -- only code that knows the file's direction. This, not source_row, is what replay orders on.
    replay_order    INTEGER NOT NULL DEFAULT 0,

    account_id      TEXT NOT NULL,
    broker          TEXT NOT NULL,
    action          TEXT NOT NULL,

    trade_date      TEXT NOT NULL,          -- ISO date
    settle_date     TEXT,
    executed_at     TEXT,                   -- ISO datetime, tz-aware where the broker supplies it
    sequence        INTEGER NOT NULL DEFAULT 0,

    symbol          TEXT,
    cusip           TEXT,
    instrument_id   TEXT,

    quantity        TEXT,                   -- decimal string
    price           TEXT,                   -- decimal string
    fees            TEXT NOT NULL DEFAULT '0',
    amount          TEXT,                   -- decimal string, signed

    currency        TEXT NOT NULL DEFAULT 'USD',
    description     TEXT,
    transfer_group  TEXT,                   -- ACAT control_num
    raw_code        TEXT,                   -- broker's own code: SLIP, ACATI, ...

    FOREIGN KEY (import_id) REFERENCES raw_import (import_id),
    FOREIGN KEY (account_id) REFERENCES account (account_id),
    FOREIGN KEY (instrument_id) REFERENCES instrument (instrument_id)
);

CREATE INDEX IF NOT EXISTS ix_txn_account_date ON txn (account_id, trade_date);
CREATE INDEX IF NOT EXISTS ix_txn_instrument_date ON txn (instrument_id, trade_date);
CREATE INDEX IF NOT EXISTS ix_txn_import ON txn (import_id, source_row);
-- Wash-sale scanning walks every disposal of an instrument across all accounts within a date
-- window, so it reads by (instrument, date) irrespective of account. Indexed above.
CREATE INDEX IF NOT EXISTS ix_txn_transfer_group
    ON txn (transfer_group) WHERE transfer_group IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Derived-state bookkeeping: none
-- ---------------------------------------------------------------------------
--
-- `derived_build` lived here and recorded each rebuild of the derived tables, so a stale derivation
-- could be detected. Nothing ever wrote it, because the derived tables it tracked were never
-- built -- see the header. `/api/health/stores` reported "never built" forever and the Portfolio
-- page rendered that as a badge next to figures that were current and correct.
--
-- Dropped in schema version 3 by `_migrate_drop_derived_build`, which removes it only when empty.
