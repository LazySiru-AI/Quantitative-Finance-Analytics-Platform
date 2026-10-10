"""Guard 2: the global trial ledger, and the FDR denominator that survives a restart.

A human running two hundred rule combinations knows they ran two hundred. A loop that discards weak
theses mid-iteration and never mentions them leaves no denominator behind -- and a q-value computed
over "the theses that made it to the end of this session" is a q-value over a set chosen by its own
results, which is not a correction at all.

So every thesis ever registered for a ticker persists here: survived, rejected, inconclusive, and
**abandoned**. Benjamini-Hochberg runs over that whole family. The q-value of thesis #40 reflects the
39 before it, including the ones nobody bothered to finish and the ones from a session three weeks
ago that crashed.

**Its own database file.** The ledger lives in ``store/thesis.sqlite``, not in the brokerage ledger.
Those are the user's real transactions; this is research bookkeeping, and a research feature must not
be able to write anywhere near them. Separate file, separate connection, no foreign keys across.

**Writes are idempotent on the content hash.** Registering the same thesis twice is one row, not two
-- otherwise re-running an identical thesis would inflate its own denominator and make the correction
harsher every time someone pressed the button, which teaches people not to press it.

**Reads never fabricate.** A ticker with no history returns a
:class:`~app.thesis.models.LedgerStats` of zero, not ``None``, because "no trials yet" is a fact
about the denominator and a caller that has to handle ``None`` will eventually treat it as one.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.backtest.scan import benjamini_hochberg
from app.config import Settings, get_settings
from app.thesis.models import LedgerStats, Thesis, ThesisRecord, ThesisStatus, Verdict
from app.thesis.preregister import PreregistrationError, content_hash, verify_unmodified

__all__ = [
    "correct_over_ledger",
    "ledger_path",
    "record",
    "records_for",
    "stats_for",
    "update_outcome",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS thesis_trial (
    thesis_hash   TEXT PRIMARY KEY,
    symbol        TEXT NOT NULL,
    interval      TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    status        TEXT NOT NULL,
    verdict       TEXT,
    hypothesis    TEXT NOT NULL,
    entry_rule    TEXT NOT NULL,
    exit_rule     TEXT,
    horizon       INTEGER NOT NULL,
    direction     TEXT NOT NULL,
    falsifies_if  TEXT NOT NULL,
    p_value       REAL,
    run_id        TEXT,
    payload       TEXT NOT NULL
);
-- Every query here is "everything for this ticker", which is the FDR family.
CREATE INDEX IF NOT EXISTS thesis_trial_symbol ON thesis_trial (symbol, registered_at);
"""


def ledger_path(settings: Settings | None = None) -> Path:
    """``store/thesis.sqlite``. Deliberately not the brokerage ledger -- see the module docstring."""
    cfg = settings or get_settings()
    return cfg.store_dir / "thesis.sqlite"


@contextmanager
def _connect(settings: Settings | None = None) -> Iterator[sqlite3.Connection]:
    """Open the ledger, creating it if absent.

    Mirrors `app.db.sqlite.connect`'s pragmas rather than importing it: that helper opens the
    *brokerage* ledger and takes its schema path from module state, and coupling a research feature
    to it would make this module's storage move whenever that one's did.
    """
    path = ledger_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{path.as_posix()}", uri=True, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(_SCHEMA)
        yield conn
    finally:
        conn.close()


def record(entry: ThesisRecord, *, settings: Settings | None = None) -> None:
    """Persist a registered thesis. Idempotent on the content hash.

    Called at *registration*, before any backtest -- that is what makes an abandoned thesis still
    count. :func:`~app.thesis.preregister.verify_unmodified` runs first so a record whose thesis has
    drifted from its hash can never enter the ledger under the old identity.
    """
    verify_unmodified(entry)
    payload = entry.model_dump_json()
    with _connect(settings) as conn:
        conn.execute(
            """
            INSERT INTO thesis_trial (
                thesis_hash, symbol, interval, registered_at, status, verdict,
                hypothesis, entry_rule, exit_rule, horizon, direction, falsifies_if,
                p_value, run_id, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thesis_hash) DO NOTHING
            """,
            (
                entry.thesis_hash,
                entry.thesis.symbol.upper(),
                entry.thesis.interval.value,
                entry.registered_at.isoformat(),
                entry.status.value,
                entry.verdict.value if entry.verdict else None,
                entry.thesis.hypothesis,
                entry.thesis.entry,
                entry.thesis.exit,
                entry.thesis.horizon,
                entry.thesis.direction.value,
                entry.thesis.falsifies_if,
                entry.in_sample.p_value if entry.in_sample else None,
                entry.run_id,
                payload,
            ),
        )


def update_outcome(
    thesis_hash: str,
    *,
    status: ThesisStatus,
    verdict: Verdict | None = None,
    p_value: float | None = None,
    run_id: str | None = None,
    payload: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Attach an outcome to an already-registered thesis.

    Deliberately keyed by hash and unable to change the thesis itself -- the columns holding the
    claim are absent from this statement. Updating an outcome must never be a path by which the
    hypothesis, the rules or the falsification criterion move.

    ``payload`` is validated against ``thesis_hash`` before it is written. The SQL columns cannot
    drift, but the JSON blob could: passing a serialised record for thesis B under thesis A's hash
    produced a split-brain row whose flat columns described A while its payload described -- and
    endorsed -- B. Guard 1's invariant is that a result joins only to the wording that was
    registered, and this is the boundary where results are attached, so the check belongs here
    rather than only at registration.
    """
    if payload is not None:
        try:
            decoded = ThesisRecord.model_validate_json(payload)
        except Exception as exc:
            raise PreregistrationError(
                f"refusing to store an unreadable payload against {thesis_hash[:12]}: {exc}"
            ) from exc
        if decoded.thesis_hash != thesis_hash:
            raise PreregistrationError(
                f"payload describes thesis {decoded.thesis_hash[:12]} but is being attached to "
                f"{thesis_hash[:12]}; a result may only join the thesis that was registered"
            )
        verify_unmodified(decoded)

    with _connect(settings) as conn:
        conn.execute(
            """
            UPDATE thesis_trial
               SET status = ?,
                   verdict = COALESCE(?, verdict),
                   p_value = COALESCE(?, p_value),
                   run_id = COALESCE(?, run_id),
                   payload = COALESCE(?, payload)
             WHERE thesis_hash = ?
            """,
            (
                status.value,
                verdict.value if verdict else None,
                p_value,
                run_id,
                payload,
                thesis_hash,
            ),
        )


def records_for(symbol: str, *, settings: Settings | None = None) -> list[ThesisRecord]:
    """Every thesis ever registered for this ticker, oldest first. The FDR family."""
    with _connect(settings) as conn:
        rows = conn.execute(
            "SELECT payload FROM thesis_trial WHERE symbol = ? ORDER BY registered_at",
            (symbol.upper(),),
        ).fetchall()
    out: list[ThesisRecord] = []
    for row in rows:
        try:
            out.append(ThesisRecord.model_validate_json(row["payload"]))
        except Exception:
            # A payload this version cannot parse still *happened*, and dropping it would shrink the
            # denominator -- the exact manipulation this module exists to prevent. It is skipped for
            # display but `stats_for` counts rows, not parsed records, so the trial count stands.
            continue
    return out


def stats_for(symbol: str, *, settings: Settings | None = None) -> LedgerStats:
    """The trial family for one ticker. Zeros, never ``None``, for a ticker with no history.

    Counts **rows**, not successfully parsed records: a trial whose payload a later version cannot
    read still consumed a slot, and letting a deserialisation failure shrink the denominator would be
    a silent way to make every q-value more generous.
    """
    upper = symbol.upper()
    with _connect(settings) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(verdict = 'survived')     AS survived,
                   SUM(verdict = 'rejected')     AS rejected,
                   SUM(verdict = 'inconclusive') AS inconclusive,
                   SUM(status  = 'abandoned')    AS abandoned,
                   MIN(registered_at)            AS first_at,
                   MAX(registered_at)            AS last_at
              FROM thesis_trial
             WHERE symbol = ?
            """,
            (upper,),
        ).fetchone()

    def _int(value: object) -> int:
        # SQLite's SUM over a boolean expression returns an int, but the driver types it as
        # `object`; narrowing explicitly rather than casting keeps a NULL (no matching rows) at 0
        # instead of raising, which is the correct answer for a ticker with no trials.
        return int(value) if isinstance(value, int | float | str) else 0

    def _ts(value: object) -> dt.datetime | None:
        return dt.datetime.fromisoformat(str(value)) if value else None

    return LedgerStats(
        symbol=upper,
        total_trials=_int(row["total"]),
        survived=_int(row["survived"]),
        rejected=_int(row["rejected"]),
        inconclusive=_int(row["inconclusive"]),
        abandoned=_int(row["abandoned"]),
        first_registered=_ts(row["first_at"]),
        last_registered=_ts(row["last_at"]),
    )


def correct_over_ledger(
    symbol: str,
    candidate_p: float | None,
    *,
    thesis_hash: str | None = None,
    settings: Settings | None = None,
) -> tuple[float | None, int]:
    """Benjamini-Hochberg one candidate p-value against the ticker's **whole** ledger.

    Returns ``(q_value, family_size)``. The family is every trial ever registered for this ticker,
    including those with no p-value -- an untestable or abandoned thesis still consumed a slot, and
    excluding it would shrink the denominator every other q-value depends on, which is precisely the
    manipulation this package exists to prevent. Entries without a p-value pass through BH as ``None``
    and still count toward ``m``, matching :func:`app.backtest.scan.benjamini_hochberg`.

    ``thesis_hash`` identifies the candidate's own row so its p-value fills that slot rather than
    appending a second one -- the candidate is *already* in the family, because registration precedes
    testing. An earlier version of this function guessed the slot instead, taking the most recent row
    with a NULL p-value, which silently double-counted any thesis whose outcome had already been
    written and inflated ``m`` by one on every such run. Requiring the identity removes the guess:
    a caller that omits it, or passes a hash from another ticker, gets the candidate appended, which
    is the correct answer for a p-value that genuinely has no row yet.
    """
    with _connect(settings) as conn:
        rows = conn.execute(
            "SELECT thesis_hash, p_value FROM thesis_trial WHERE symbol = ? ORDER BY registered_at",
            (symbol.upper(),),
        ).fetchall()

    p_values: list[float | None] = [row["p_value"] for row in rows]
    if candidate_p is None:
        return None, len(p_values)

    hashes = [str(row["thesis_hash"]) for row in rows]
    if thesis_hash is not None and thesis_hash in hashes:
        index = hashes.index(thesis_hash)
        p_values[index] = candidate_p
    else:
        p_values.append(candidate_p)
        index = len(p_values) - 1

    return benjamini_hochberg(p_values)[index], len(p_values)


def register_and_count(
    thesis: Thesis, *, settings: Settings | None = None
) -> tuple[ThesisRecord, LedgerStats]:
    """Convenience for the loop: freeze, persist, and report the resulting family size.

    The order matters and is the point -- the thesis is in the ledger before anything is run against
    it, so an abandoned run leaves its trial behind.
    """
    from app.thesis.preregister import register

    entry = register(thesis)
    record(entry, settings=settings)
    return entry, stats_for(thesis.symbol, settings=settings)


def _unused_content_hash(thesis: Thesis) -> str:  # pragma: no cover - re-export guard
    return content_hash(thesis)
