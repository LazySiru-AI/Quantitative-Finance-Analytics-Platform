"""The import orchestrator: broker CSV on disk -> rows in the ledger.

Everything this module needs already existed and was individually tested -- header-signature
detection, the three adapters, provenance hashing, deterministic transaction ids, idempotent
insertion. What did not exist was anything that called them in order. ``app.ingest`` had no
production entry point at all: outside the test suite and the UAT harness, nothing in the running
application could load a broker export, while the UI's empty states told the user to drop files into
``data/`` and rebuild. ``tests/test_e2e.py`` recorded the gap in its own docstring -- *"there is no
ingestion endpoint or CLI to populate it ... with no orchestrating function wiring them together"* --
and it stayed open for seven more phases. This module is that function.

**It adds no parsing logic, and must not.** Every decision about what a row means belongs to an
adapter. If something here starts interpreting a broker's data, the seam is in the wrong place.

Three properties this layer owns, none of which any individual piece below it could:

**Per-file atomicity.** Each file's writes -- account, import record, raw rows, instruments,
transactions -- happen inside one explicit transaction. The connection runs in autocommit mode
(``isolation_level=None``, see :func:`app.db.sqlite.connect`), so without an explicit ``BEGIN`` a
file that failed halfway would leave the rows it had already written behind. A half-imported file is
worse than an unimported one: it looks like data.

**One import record per distinct file content.** ``import_id`` is derived from the content hash, the
account *and the timestamp*, so importing the same unchanged file twice would otherwise mint a second
``raw_import`` row and a second verbatim copy of every source row, growing the store on every run
while the transactions themselves correctly deduplicate. Content already imported into the same
account reuses the stored ``import_id``, which makes re-running this a no-op across the whole store
rather than only in ``txn``.

**Failure is per file.** One unreadable export does not abandon the other seven. Every file comes
back with its own status, and the run reports what did not land as prominently as what did.

Re-import remains genuinely idempotent rather than merely tolerated: transactions are re-parsed and
re-offered on every run, so a file whose import was interrupted heals itself, and a row whose stored
content disagrees with the incoming one surfaces as a conflict instead of being overwritten.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from app.config import Settings, get_settings
from app.core.models import Account, AccountType, Broker, ImportRecord, TaxTreatment
from app.datasource import ledger_db_path, ledger_writer, local_document_path
from app.db import sqlite
from app.ingest import registry
from app.ingest.adapters.base import BrokerAdapter
from app.ingest.manifest import AccountEntry, Manifest, load_manifest_document
from app.ingest.matching import AccountMatch, FileMatches, match_accounts
from app.ingest.provenance import RawFile, build_import_record, read_rows

__all__ = [
    "FileImport",
    "FileStatus",
    "ImportRun",
    "PlannedFile",
    "discover_exports",
    "import_paths",
    "manifest_path",
    "plan_import",
    "summarise",
]


class FileStatus(StrEnum):
    """What became of one file.

    The three failure statuses are distinguished rather than collapsed into "error" because they
    call for different actions: a missing manifest entry is something the user writes, an
    unrecognised header is an adapter that needs adding, and a parse failure is a bug or a changed
    export format.
    """

    IMPORTED = "imported"
    """Rows landed. Includes a partial re-import where only some rows were new."""
    UNCHANGED = "unchanged"
    """Every row was already present with identical content -- the expected result of re-running."""
    CONFLICTS = "conflicts"
    """At least one stored row disagreed with the incoming one. Nothing was overwritten."""
    UNDECLARED = "undeclared"
    """Present on disk but not in the manifest, so there is no account to attribute it to."""
    NO_ADAPTER = "no_adapter"
    """No registered adapter recognised the header."""
    AMBIGUOUS = "ambiguous"
    """More than one adapter claimed it -- a bug in an adapter's ``matches``, not user error."""
    FAILED = "failed"
    """The file was recognised and could not be parsed or written."""

    @property
    def is_failure(self) -> bool:
        return self in {
            FileStatus.UNDECLARED,
            FileStatus.NO_ADAPTER,
            FileStatus.AMBIGUOUS,
            FileStatus.FAILED,
        }


@dataclass(frozen=True, slots=True)
class PlannedFile:
    """What one file would do, decided without writing anything.

    Produced by :func:`plan_import` so a caller -- ``--dry-run``, or the UI before the user commits
    -- can see the file-to-account attribution that is about to be applied. Attribution is the one
    thing in this pipeline a user can get wrong in a way no validation can catch, so it is worth
    showing before rather than reporting after.
    """

    path: Path
    status: FileStatus
    """``IMPORTED`` here means "would import"; the failure statuses mean the same as after a run."""
    adapter: str | None = None
    broker: Broker | None = None
    account_id: str | None = None
    account_label: str | None = None
    tax_treatment: str | None = None
    row_count: int | None = None
    usable_row_count: int | None = None
    """Rows that would become transactions -- the denominator the match evidence is measured over."""
    detail: str | None = None
    already_imported: bool = False
    """This exact content is already in the ledger under this account."""

    matches: tuple[AccountMatch, ...] = ()
    """Same-broker accounts scored by how many of this file's transactions they already hold.

    Exact, not heuristic: `txn_id` includes the account, so the ids this file would produce under
    each candidate are recomputed and looked up. Present even for an undeclared file -- in fact
    *especially* then, because that is when the user has to decide whether this is a re-export of an
    account they already have or a new one. See :mod:`app.ingest.matching`.
    """
    match_is_ambiguous: bool = False
    """Two or more accounts share transactions with this file, which should not happen. Surfaced
    rather than resolved by picking one."""

    @property
    def suggested_account_id(self) -> str | None:
        """The one account sharing transactions with this file, if exactly one does.

        A *suggestion*, never applied on its own -- the import path still requires the account to be
        declared. Tax treatment in particular is never inferred from a match: attaching to an
        existing account inherits its declared treatment, which is a different thing from guessing.
        """
        best = FileMatches(self.matches).best
        return best.account_id if best is not None else None


@dataclass(frozen=True, slots=True)
class FileImport:
    """The outcome of importing one file."""

    path: Path
    status: FileStatus
    adapter: str | None = None
    broker: Broker | None = None
    account_id: str | None = None
    import_id: str | None = None
    row_count: int = 0
    """Data rows in the file."""
    usable_row_count: int = 0
    """Rows that became transactions. The gap from ``row_count`` is the adapter's skip signature."""
    inserted: int = 0
    duplicates: int = 0
    conflicts: tuple[str, ...] = ()
    skipped: dict[str, int] = field(default_factory=dict)
    instruments: int = 0
    raw_rows_stored: int = 0
    detail: str | None = None
    """Why it failed, when it did. An actionable sentence, not a traceback."""
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.status.is_failure


@dataclass(frozen=True, slots=True)
class ImportRun:
    """Every file in one invocation, plus the ledger state it produced."""

    files: tuple[FileImport, ...]
    ledger_fingerprint: str
    txn_count: int
    started_at: dt.datetime

    @property
    def inserted(self) -> int:
        return sum(f.inserted for f in self.files)

    @property
    def failures(self) -> tuple[FileImport, ...]:
        return tuple(f for f in self.files if not f.ok)

    @property
    def conflicted(self) -> tuple[FileImport, ...]:
        return tuple(f for f in self.files if f.conflicts)

    @property
    def ok(self) -> bool:
        """True when every file landed and nothing conflicted.

        Conflicts count against this deliberately. A conflict is not a soft warning: it means the
        broker restated a figure or an adapter changed its mind about one, and the stored row --
        possibly already reported on a tax form -- was left alone. That deserves the same attention
        as an outright failure.
        """
        return not self.failures and not self.conflicted


def manifest_path(settings: Settings | None = None) -> Path:
    """Where the account manifest lives: ``accounts.toml`` beside the exports it describes."""
    return local_document_path("accounts-manifest", settings or get_settings())


def discover_exports(settings: Settings | None = None) -> tuple[Path, ...]:
    """Every CSV under ``data_dir`` that could be a broker export, sorted.

    The derived stores live under ``data/store`` and the provider cache under ``data/cache``, both
    inside ``data_dir``; neither holds broker exports and a stray CSV in either would otherwise be
    offered for import. They are excluded by location rather than by name pattern -- a filename
    tells this layer nothing, which is the same reason adapters are chosen by header.
    """
    cfg = settings or get_settings()
    if not cfg.data_dir.exists():
        return ()
    excluded = (cfg.store_dir.resolve(), cfg.cache_dir.resolve())
    found = [
        path
        for path in cfg.data_dir.rglob("*.csv")
        if path.is_file() and not _is_within(path, excluded)
    ]
    return tuple(sorted(found))


def _is_within(path: Path, roots: Sequence[Path]) -> bool:
    resolved = path.resolve()
    return any(resolved.is_relative_to(root) for root in roots)


def plan_import(
    paths: Sequence[Path] | None = None,
    *,
    manifest: Manifest | None = None,
    settings: Settings | None = None,
) -> tuple[PlannedFile, ...]:
    """Resolve files to adapters and accounts without writing anything.

    Reads the ledger only to answer "is this content already imported", and read-only at that.
    """
    cfg = settings or get_settings()
    targets = tuple(paths) if paths is not None else discover_exports(cfg)
    book = manifest if manifest is not None else _load_manifest_or_none(cfg)
    registry.load_builtin_adapters()

    seen: list[tuple[str, str]] = []
    accounts: list[Account] = []
    ledger = ledger_db_path(cfg)
    if ledger.exists():
        with sqlite.connect(ledger, read_only=True) as conn:
            seen = [
                (str(row["content_hash"]), str(row["account_id"]))
                for row in conn.execute("SELECT content_hash, account_id FROM raw_import")
            ]
            accounts = sqlite.fetch_accounts(conn)

    planned: list[PlannedFile] = []
    for path in targets:
        try:
            raw = read_rows(path, settings=cfg)
        except Exception as exc:
            planned.append(
                PlannedFile(path=path, status=FileStatus.FAILED, detail=_reason(exc))
            )
            continue

        try:
            adapter = registry.resolve(raw)
        except registry.AmbiguousAdapter as exc:
            planned.append(
                PlannedFile(
                    path=path,
                    status=FileStatus.AMBIGUOUS,
                    row_count=raw.row_count,
                    detail=_reason(exc),
                )
            )
            continue
        except registry.AdapterNotFound as exc:
            planned.append(
                PlannedFile(
                    path=path,
                    status=FileStatus.NO_ADAPTER,
                    row_count=raw.row_count,
                    detail=_reason(exc),
                )
            )
            continue

        entry = book.entry_for(path) if book is not None else None
        # Scored before the manifest is consulted, because the answer is most needed exactly when
        # there is no entry: "is this a re-export of an account I already have, or a new one" is the
        # question the user has to answer to write that entry in the first place.
        matches, usable = _score_matches(raw, adapter, accounts, cfg)

        if entry is None:
            planned.append(
                PlannedFile(
                    path=path,
                    status=FileStatus.UNDECLARED,
                    adapter=adapter.name,
                    broker=adapter.broker,
                    row_count=raw.row_count,
                    usable_row_count=usable,
                    matches=matches.candidates,
                    match_is_ambiguous=matches.ambiguous,
                    detail=(
                        f"{path.name!r} is not declared in the account manifest, so there is no "
                        "account to attribute its rows to. Add an [[account]] entry for it, or "
                        "move the file out of the data directory if it is not a broker export."
                    ),
                )
            )
            continue

        account = _account_for(entry, adapter)
        planned.append(
            PlannedFile(
                path=path,
                status=FileStatus.IMPORTED,
                adapter=adapter.name,
                broker=adapter.broker,
                account_id=account.account_id,
                account_label=account.label,
                tax_treatment=account.tax_treatment.value,
                row_count=raw.row_count,
                usable_row_count=usable,
                matches=matches.candidates,
                match_is_ambiguous=matches.ambiguous,
                already_imported=(raw.content_hash(), account.account_id) in seen,
            )
        )
    return tuple(planned)


def _score_matches(
    raw: RawFile,
    adapter: BrokerAdapter,
    accounts: Sequence[Account],
    settings: Settings,
) -> tuple[FileMatches, int | None]:
    """``(matches, usable_row_count)`` for one file, or empty evidence if it cannot be parsed.

    Parsed against a placeholder account: :func:`app.ingest.matching.match_accounts` recomputes the
    ids per candidate, so the placeholder never reaches a comparison. A parse failure here is not
    raised -- this is a preview, and a file that will fail to import should say so through its
    status rather than by making the whole listing 500.
    """
    if not accounts:
        return FileMatches(), None
    ledger = ledger_db_path(settings)
    if not ledger.exists():
        return FileMatches(), None

    probe = Account(
        account_id="__match_probe__",
        broker=adapter.broker,
        label="probe",
        tax_treatment=TaxTreatment.TAXABLE,
        account_type=AccountType.CASH,
    )
    try:
        record = build_import_record(
            raw,
            broker=adapter.broker,
            account_id=probe.account_id,
            adapter=adapter.name,
            adapter_version=adapter.version,
            usable_row_count=0,
        )
        parsed = adapter.parse(raw, account=probe, import_id=record.import_id)
    except Exception:
        return FileMatches(), None

    with sqlite.connect(ledger, read_only=True) as conn:
        return (
            match_accounts(parsed.transactions, accounts=accounts, conn=conn),
            parsed.usable_row_count,
        )


def import_paths(
    paths: Sequence[Path] | None = None,
    *,
    manifest: Manifest | None = None,
    settings: Settings | None = None,
    imported_at: dt.datetime | None = None,
) -> ImportRun:
    """Import each path, and report what happened to every one of them.

    ``paths`` defaults to every export discovered under ``data_dir``. ``manifest`` defaults to
    ``data/accounts.toml``; a missing or malformed one raises
    :class:`~app.ingest.manifest.ManifestError` before anything is written, because a run that
    imports the files it understood and skips the rest produces a ledger that is wrong in a way
    nothing downstream can detect.
    """
    cfg = settings or get_settings()
    when = imported_at or dt.datetime.now(dt.UTC)
    targets = tuple(paths) if paths is not None else discover_exports(cfg)
    book = manifest if manifest is not None else load_manifest_document(cfg)
    registry.load_builtin_adapters()

    cfg.ensure_dirs()
    results: list[FileImport] = []
    with ledger_writer(cfg) as ledger_file, sqlite.connect(ledger_file) as conn:
        sqlite.migrate(conn)
        for path in targets:
            results.append(_import_one(conn, path, book=book, settings=cfg, imported_at=when))
        fingerprint, txn_count = sqlite.ledger_fingerprint(conn)

    return ImportRun(
        files=tuple(results),
        ledger_fingerprint=fingerprint,
        txn_count=txn_count,
        started_at=when,
    )


def _import_one(
    conn: sqlite3.Connection,
    path: Path,
    *,
    book: Manifest,
    settings: Settings,
    imported_at: dt.datetime,
) -> FileImport:
    try:
        raw = read_rows(path, settings=settings)
    except Exception as exc:
        return FileImport(path=path, status=FileStatus.FAILED, detail=_reason(exc))

    try:
        adapter = registry.resolve(raw)
    except registry.AmbiguousAdapter as exc:
        return FileImport(
            path=path,
            status=FileStatus.AMBIGUOUS,
            row_count=raw.row_count,
            detail=_reason(exc),
        )
    except registry.AdapterNotFound as exc:
        return FileImport(
            path=path,
            status=FileStatus.NO_ADAPTER,
            row_count=raw.row_count,
            detail=_reason(exc),
        )

    entry = book.entry_for(path)
    if entry is None:
        return FileImport(
            path=path,
            status=FileStatus.UNDECLARED,
            adapter=adapter.name,
            broker=adapter.broker,
            row_count=raw.row_count,
            detail=(
                f"{path.name!r} is not declared in {book.path.name}, so there is no account to "
                "attribute its rows to. Add an [[account]] entry for it."
            ),
        )

    if entry.declared_broker is not None and entry.declared_broker is not adapter.broker:
        # The header is the authority. A manifest that disagrees is pointing at the wrong file --
        # usually a filename edited in one place and not the other -- and importing under the
        # declared account would file one broker's trades against another broker's account.
        return FileImport(
            path=path,
            status=FileStatus.FAILED,
            adapter=adapter.name,
            broker=adapter.broker,
            account_id=entry.account.account_id,
            row_count=raw.row_count,
            detail=(
                f"manifest declares broker={entry.declared_broker.value!r} for {path.name!r}, but "
                f"its header is {adapter.broker.value!r} (matched by the {adapter.name} adapter). "
                "The header is authoritative; fix the manifest entry or point it at the right file."
            ),
        )

    account = _account_for(entry, adapter)
    warnings: list[str] = []

    try:
        conn.execute("BEGIN")
        result = _write_one(
            conn,
            raw=raw,
            adapter=adapter,
            account=account,
            imported_at=imported_at,
            warnings=warnings,
        )
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        return FileImport(
            path=path,
            status=FileStatus.FAILED,
            adapter=adapter.name,
            broker=adapter.broker,
            account_id=account.account_id,
            row_count=raw.row_count,
            detail=_reason(exc),
        )

    record, parsed, report, raw_rows_stored = result
    if report.conflicts:
        status = FileStatus.CONFLICTS
    elif report.inserted:
        status = FileStatus.IMPORTED
    else:
        status = FileStatus.UNCHANGED

    return FileImport(
        path=path,
        status=status,
        adapter=adapter.name,
        broker=adapter.broker,
        account_id=account.account_id,
        import_id=record.import_id,
        row_count=raw.row_count,
        usable_row_count=parsed,
        inserted=report.inserted,
        duplicates=report.duplicates,
        conflicts=tuple(_format_conflict(c) for c in report.conflicts),
        skipped=dict(report.skip_counts),
        instruments=report.instrument_count,
        raw_rows_stored=raw_rows_stored,
        warnings=tuple(warnings),
    )


@dataclass(slots=True)
class _WriteReport:
    """Insert counts plus the per-file extras the caller reports on."""

    inserted: int
    duplicates: int
    conflicts: list[tuple[str, str, object, object]]
    skip_counts: dict[str, int]
    instrument_count: int


def _write_one(
    conn: sqlite3.Connection,
    *,
    raw: RawFile,
    adapter: BrokerAdapter,
    account: Account,
    imported_at: dt.datetime,
    warnings: list[str],
) -> tuple[ImportRecord, int, _WriteReport, int]:
    """Parse and write one file. Called inside an open transaction; raises to roll it back."""
    digest = raw.content_hash()
    prior = sqlite.find_import_by_content(conn, digest, account_id=account.account_id)
    elsewhere = (
        None if prior is not None else sqlite.find_import_by_content(conn, digest)
    )

    if elsewhere is not None:
        # Same bytes, different account. Legitimate -- a file re-assigned after a manifest edit --
        # but the rows already filed under the old account do not move, and nothing downstream will
        # ever point out that the same trades now exist twice under two account ids.
        warnings.append(
            f"this content was previously imported as account {str(elsewhere['account_id'])!r}; "
            f"its rows remain in the ledger under that account alongside the ones being written "
            f"now for {account.account_id!r}"
        )

    if prior is not None:
        import_id = str(prior["import_id"])
    else:
        # `build_import_record` needs `usable_row_count`, which needs the parse, which needs the
        # `import_id` this call produces. Called twice with the same `imported_at` so both calls
        # derive the same id and only the row count differs -- the id formula stays in one place.
        import_id = build_import_record(
            raw,
            broker=adapter.broker,
            account_id=account.account_id,
            adapter=adapter.name,
            adapter_version=adapter.version,
            usable_row_count=0,
            imported_at=imported_at,
        ).import_id

    parsed = adapter.parse(raw, account=account, import_id=import_id)

    record = build_import_record(
        raw,
        broker=adapter.broker,
        account_id=account.account_id,
        adapter=adapter.name,
        adapter_version=adapter.version,
        usable_row_count=parsed.usable_row_count,
        imported_at=imported_at,
    )
    if prior is not None:
        record = record.model_copy(
            update={
                "import_id": import_id,
                "imported_at": dt.datetime.fromisoformat(str(prior["imported_at"])),
            }
        )

    # The account row is a foreign-key target for every transaction, and the import row for both the
    # transactions and the raw rows, so both are written before anything references them.
    sqlite.upsert_account(conn, account)
    raw_rows_stored = 0
    if prior is None:
        sqlite.record_import(conn, record)
        # Storing the source rows verbatim is what keeps "trace this figure back to the CSV"
        # answerable once the export has been replaced by a newer one. `provenance.py` opens by
        # promising exactly this; until this module existed nothing performed it, and `raw_row` sat
        # empty in a real ledger while every transaction in it carried a source_row pointing into
        # a table with nothing in it.
        raw_rows_stored = sqlite.record_raw_rows(conn, record.import_id, raw.rows)

    for instrument in parsed.instruments.values():
        sqlite.upsert_instrument(conn, instrument)
    report = sqlite.insert_transactions(conn, parsed.transactions)

    return (
        record,
        parsed.usable_row_count,
        _WriteReport(
            inserted=report.inserted,
            duplicates=report.duplicates,
            conflicts=report.conflicts,
            skip_counts=parsed.skip_counts(),
            instrument_count=len(parsed.instruments),
        ),
        raw_rows_stored,
    )


def _account_for(entry: AccountEntry, adapter: BrokerAdapter) -> Account:
    """The manifest's account, with the broker the adapter actually detected.

    The manifest may omit ``broker`` entirely, and where it declares one it has already been checked
    against this value. Either way the header wins, so no account is ever written carrying a broker
    the file's own contents contradict.
    """
    if entry.account.broker is adapter.broker:
        return entry.account
    return entry.account.model_copy(update={"broker": adapter.broker})


def _load_manifest_or_none(settings: Settings) -> Manifest | None:
    from app.ingest.manifest import ManifestError

    try:
        return load_manifest_document(settings)
    except ManifestError:
        # Planning is a read-only preview and is most useful precisely when the manifest is missing
        # -- that is when a user needs to see which files were found and what they resolve to.
        # Importing, by contrast, raises: see `import_paths`.
        return None


def _format_conflict(conflict: tuple[str, str, object, object]) -> str:
    txn_id, field_name, existing, incoming = conflict
    return f"{txn_id}: {field_name} stored={existing!r} incoming={incoming!r}"


def _reason(exc: Exception) -> str:
    """One actionable line from an exception, keeping the type when the message alone is opaque."""
    text = str(exc).strip()
    if not text:
        return type(exc).__name__
    first = text.splitlines()[0]
    return text if len(text) <= 400 else f"{first} …"


def summarise(files: Iterable[FileImport]) -> str:
    """One line per file, for a terminal. Failures carry their reason inline."""
    lines: list[str] = []
    for item in files:
        head = f"{item.path.name:<40} {item.status.value:<11}"
        if item.ok:
            lines.append(
                f"{head} {item.inserted:>5} new, {item.duplicates:>5} dup, "
                f"{len(item.conflicts):>3} conflict  ({item.usable_row_count}/{item.row_count} rows"
                f" -> {item.account_id})"
            )
        else:
            lines.append(f"{head} {item.detail or ''}")
        for warning in item.warnings:
            lines.append(f"{'':<40} warning: {warning}")
    return "\n".join(lines)
