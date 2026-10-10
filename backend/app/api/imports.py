"""Import: the one write endpoint, and the only way data enters the system from the UI.

Every other route in this application reads. This one loads broker exports through
:mod:`app.ingest.service`, which is the wiring that was missing for nine phases -- the adapters, the
provenance layer and the idempotent writer all existed and nothing in the running application could
invoke them, while the UI's own empty states told the user to drop files into ``data/`` and rebuild.

**It does not accept uploads, deliberately.** Files are read from ``settings.data_dir`` where they
already sit; the endpoint imports what is on disk rather than receiving bytes. That is not a
limitation worked around, it is the shape of the tool: this is a local single-user application
reading the user's own exports out of a directory they control, and the empty states have always
said so. Accepting multipart uploads would add a write surface, a filename-sanitisation problem and
a size-limit policy in exchange for saving a file copy the user has already done. If this ever
serves more than one person, that trade changes and so does this comment.

Two routes, because previewing and doing are different questions:

* ``GET`` answers *"what would happen"* -- which files are present, which adapter matched each, and
  which account each is declared to belong to. It writes nothing and works fine with no manifest at
  all, which is exactly when it is most useful.
* ``POST`` performs the import and reports per file.

The file-to-account attribution shown by ``GET`` is worth reading before running ``POST``: it is the
one input in this pipeline that no amount of validation can check, because a Robinhood taxable
export and a Robinhood Roth export are structurally identical and only the user knows which is
which.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Final

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import REPO_ROOT, Settings, get_settings
from app.core.models import Account, AccountType, TaxTreatment
from app.datasource import ledger_db_path, read_document
from app.db import sqlite
from app.ingest import service
from app.ingest.manifest import (
    ManifestError,
    append_entry_document,
    load_manifest_document,
    load_manifest_text,
)

router = APIRouter(prefix="/api/import", tags=["import"])

#: Ceiling on how many files one POST may name. The real directory holds eight; a request naming
#: hundreds is a client bug, and each file is a full parse plus a write transaction.
_MAX_FILES: Final = 64


class ManifestStatus(BaseModel):
    """Whether the account manifest can be read, and what it says."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    present: bool
    entries: int = 0
    error: str | None = None
    """Why it cannot be used. Present whenever ``entries`` is 0 and the file exists -- a malformed
    manifest and an absent one are different problems with different fixes."""


class AccountMatchModel(BaseModel):
    """How much of an incoming file an existing account already holds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: str
    account_label: str
    tax_treatment: str
    overlapping: int
    """Transactions this account already has, matched by id. Exact, not inferred."""
    incoming_total: int
    account_total: int
    new_rows: int
    account_coverage: float
    """Share of *this account* the file contains -- the ratio that discriminates. A file holding an
    account whole is a re-export of it; sharing a few of a larger account's same-price trades is
    coincidence between two accounts at one broker."""
    overlap_fraction: float
    """Share of the *file* already stored. Reads low precisely when a match is certain, because a
    fresh export covers months the account does not yet have."""
    shared_symbols: int
    """Context only, never evidence: two accounts holding the same ETFs share every symbol."""
    incoming_symbols: int


class PlannedFileModel(BaseModel):
    """One discovered file and where it would go."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str
    """Relative to the data directory. The absolute path is deliberately not returned: it is a
    server filesystem path and the UI has no use for it."""
    status: str
    adapter: str | None = None
    broker: str | None = None
    account_id: str | None = None
    account_label: str | None = None
    tax_treatment: str | None = None
    row_count: int | None = None
    usable_row_count: int | None = None
    already_imported: bool = False
    detail: str | None = None

    matches: list[AccountMatchModel] = Field(default_factory=list)
    """Same-broker accounts, best first. Populated even when the file is undeclared -- that is when
    the user most needs it, since "is this an account I already have" is the question they are being
    asked to answer."""
    suggested_account_id: str | None = None
    """The one account this file shares transactions with, when one stands out. A suggestion the UI
    preselects and the user confirms; never applied on its own."""
    match_is_ambiguous: bool = False
    """Rows are shared with several accounts and none stands out. The UI must not preselect."""


class ImportPlan(BaseModel):
    """What a POST would do, decided without writing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    data_dir: str
    manifest: ManifestStatus
    files: list[PlannedFileModel]
    importable: int
    """Files that would import. The rest need a manifest entry or an adapter."""


class FileImportModel(BaseModel):
    """What happened to one file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str
    status: str
    adapter: str | None = None
    broker: str | None = None
    account_id: str | None = None
    import_id: str | None = None
    row_count: int = 0
    usable_row_count: int = 0
    """Rows that became transactions. The gap from ``row_count`` is cancellations, footers and
    non-events -- see ``skipped`` for the breakdown."""
    inserted: int = 0
    duplicates: int = 0
    conflicts: list[str] = Field(default_factory=list)
    """Stored rows that disagreed with the incoming ones. **Nothing was overwritten.** A restated
    figure may already have been reported on a tax form, so it is surfaced rather than replaced."""
    skipped: dict[str, int] = Field(default_factory=dict)
    instruments: int = 0
    detail: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ImportRunResult(BaseModel):
    """One import run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    files: list[FileImportModel]
    inserted: int
    ok: bool
    """True only when every file landed and nothing conflicted."""
    ledger_fingerprint: str
    txn_count: int
    started_at: dt.datetime


class NewAccount(BaseModel):
    """Declare an account that does not exist yet.

    ``tax_treatment`` is required and has no default, here as everywhere else: it decides whether an
    account's gains are reported at all and whether a repurchase inside it destroys a loss
    permanently under Rev. Rul. 2008-5. A UI that let this be skipped would be guessing the highest
    -leverage tax input in the system on the user's behalf.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    """Lower-case slug. Constrained because it is written into a TOML file and used as a key."""
    label: str = Field(min_length=1, max_length=120)
    tax_treatment: TaxTreatment
    account_type: AccountType = AccountType.CASH


class FileDecision(BaseModel):
    """What to do with one file: attach it to an account, or open a new one.

    Exactly one of ``account_id`` and ``new_account``. Both, or neither, is a client bug and is
    rejected rather than resolved -- the two mean opposite things, and picking one would be choosing
    between "add to the book I already have" and "start a second one" without being asked.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str
    account_id: str | None = None
    """Attach to this existing account. Its declared tax treatment applies; nothing is re-declared,
    because an account's treatment is a property of the account and not of a file."""
    new_account: NewAccount | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> FileDecision:
        if (self.account_id is None) == (self.new_account is None):
            raise ValueError(
                f"{self.filename!r}: give exactly one of account_id (attach to an existing account) "
                "or new_account (create one)"
            )
        return self


class ImportRequest(BaseModel):
    """Which files to import, and where each one goes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    filenames: list[str] | None = None
    """Names relative to the data directory, as returned by ``GET``. ``null`` imports everything
    found there. Names are matched against the discovered set rather than joined onto a path, so a
    request cannot reach a file outside the data directory."""

    decisions: list[FileDecision] = Field(default_factory=list)
    """Account assignments for files the manifest does not yet declare.

    **Each one is written into ``data/accounts.toml`` before the import runs.** The manifest stays
    the single record of file-to-account attribution, so a choice made in the browser is the same
    choice the CLI sees next time -- otherwise the two entry points would disagree about what the
    user has already answered.
    """


@router.get("", response_model=ImportPlan)
def preview_import() -> ImportPlan:
    """Which exports are present, and which account each would be imported into.

    Writes nothing, and works with no manifest -- that is the state in which a user most needs to
    see what was found.
    """
    settings = get_settings()
    manifest_file = service.manifest_path(settings)

    manifest_text = read_document("accounts-manifest", settings)
    status = ManifestStatus(path=manifest_file.name, present=manifest_text is not None)
    if manifest_text is not None:
        try:
            book = load_manifest_text(manifest_text, manifest_file)
            status = ManifestStatus(
                path=manifest_file.name, present=True, entries=len(book.entries)
            )
        except ManifestError as exc:
            status = ManifestStatus(path=manifest_file.name, present=True, error=str(exc))

    planned = service.plan_import(settings=settings)
    return ImportPlan(
        data_dir=_display_dir(settings.data_dir),
        manifest=status,
        files=[_planned_model(item, settings.data_dir) for item in planned],
        importable=sum(1 for item in planned if item.status is service.FileStatus.IMPORTED),
    )


@router.post("", response_model=ImportRunResult)
def run_import(request: ImportRequest | None = None) -> ImportRunResult:
    """Import broker exports from the data directory into the ledger.

    Idempotent: re-importing an overlapping export inserts nothing and leaves the ledger
    fingerprint unmoved. A row whose stored content disagrees with the incoming one is reported as
    a conflict and **not** overwritten.

    **This writes to the ledger.** Everything derived from it -- lots, positions, wash-sale
    adjustments, gains -- is rebuilt from the ledger on read, so no separate rebuild step follows.
    """
    settings = get_settings()
    body = request or ImportRequest()
    available = service.discover_exports(settings)

    # Decisions are written into the manifest *before* it is loaded, so the import that follows sees
    # them the same way it sees an entry typed by hand. Doing it in this order also means a decision
    # that cannot be recorded stops the run instead of importing under an attribution that was never
    # persisted -- the next CLI run would then ask again and get a different answer.
    if body.decisions:
        _apply_decisions(body.decisions, available=available, settings=settings)

    try:
        book = load_manifest_document(settings)
    except ManifestError as exc:
        # 422 rather than 500: the request is well-formed and the server is healthy; what is missing
        # is a declaration only the user can supply. The message carries the fix.
        raise HTTPException(status_code=422, detail=str(exc)) from None

    targets: tuple[Path, ...]
    if body.filenames is None:
        targets = available
    else:
        if len(body.filenames) > _MAX_FILES:
            raise HTTPException(
                status_code=422,
                detail=f"at most {_MAX_FILES} files per request; {len(body.filenames)} were named",
            )
        by_name = {_relative(path, settings.data_dir): path for path in available}
        unknown = [name for name in body.filenames if name not in by_name]
        if unknown:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"not found in the data directory: {unknown}. Names must match those returned "
                    "by GET /api/import."
                ),
            )
        targets = tuple(by_name[name] for name in body.filenames)

    if not targets:
        raise HTTPException(
            status_code=422,
            detail=(
                f"no broker exports found in {_display_dir(settings.data_dir)}. Copy the CSV exports "
                "there and "
                "try again."
            ),
        )

    run = service.import_paths(targets, manifest=book, settings=settings)
    return ImportRunResult(
        files=[_file_model(item, settings.data_dir) for item in run.files],
        inserted=run.inserted,
        ok=run.ok,
        ledger_fingerprint=run.ledger_fingerprint,
        txn_count=run.txn_count,
        started_at=run.started_at,
    )


def _apply_decisions(
    decisions: list[FileDecision],
    *,
    available: tuple[Path, ...],
    settings: Settings,
) -> None:
    """Record each file-to-account choice in the manifest.

    Attaching to an existing account and opening a new one write the same shape of entry -- the only
    difference is where the account's attributes come from. For an existing account they are read
    back from the ledger, never re-declared by the client: an account's tax treatment is a property
    of the account, and letting a request restate it would allow one file's import to silently
    reclassify a Roth as taxable.
    """
    by_name = {_relative(path, settings.data_dir): path for path in available}

    stored: dict[str, Account] = {}
    ledger_file = ledger_db_path(settings)
    if ledger_file.exists():
        with sqlite.connect(ledger_file, read_only=True) as conn:
            stored = {a.account_id: a for a in sqlite.fetch_accounts(conn)}

    for decision in decisions:
        if decision.filename not in by_name:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"{decision.filename!r} is not in the data directory. Names must match those "
                    "returned by GET /api/import."
                ),
            )

        if decision.new_account is not None:
            new = decision.new_account
            if new.account_id in stored:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"account {new.account_id!r} already exists. Attach the file to it with "
                        "account_id instead of creating it -- which also keeps its declared tax "
                        "treatment rather than restating it."
                    ),
                )
            account_id, label = new.account_id, new.label
            treatment, account_type = new.tax_treatment, new.account_type
            note = "added from the Import panel: new account"
        else:
            existing = stored.get(decision.account_id or "")
            if existing is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"no account {decision.account_id!r} in the ledger. Create it with "
                        "new_account, or attach to one of the accounts GET /api/import lists."
                    ),
                )
            account_id, label = existing.account_id, existing.label
            treatment, account_type = existing.tax_treatment, existing.account_type
            note = "added from the Import panel: attached to an existing account"

        try:
            append_entry_document(
                settings,
                file=decision.filename,
                account_id=account_id,
                label=label,
                tax_treatment=treatment,
                account_type=account_type,
                note=note,
            )
        except ManifestError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None


def _display_dir(data_dir: Path) -> str:
    """The data directory as shown to the client: repo-relative, never absolute.

    An absolute path embeds the OS account name of the machine running the server
    (PII audit 2026-09-10, PII-02). Inside the repo the relative form is what the
    owner already knows; outside it, the directory name alone is enough to find it.
    """
    try:
        return data_dir.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return data_dir.name or str(data_dir)


def _relative(path: Path, data_dir: Path) -> str:
    try:
        return path.resolve().relative_to(data_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def _planned_model(item: service.PlannedFile, data_dir: Path) -> PlannedFileModel:
    return PlannedFileModel(
        filename=_relative(item.path, data_dir),
        status=item.status.value,
        adapter=item.adapter,
        broker=item.broker.value if item.broker else None,
        account_id=item.account_id,
        account_label=item.account_label,
        tax_treatment=item.tax_treatment,
        row_count=item.row_count,
        usable_row_count=item.usable_row_count,
        already_imported=item.already_imported,
        detail=item.detail,
        matches=[
            AccountMatchModel(
                account_id=m.account_id,
                account_label=m.account_label,
                tax_treatment=m.tax_treatment,
                overlapping=m.overlapping,
                incoming_total=m.incoming_total,
                account_total=m.account_total,
                new_rows=m.new_rows,
                account_coverage=m.account_coverage,
                overlap_fraction=m.overlap_fraction,
                shared_symbols=m.shared_symbols,
                incoming_symbols=m.incoming_symbols,
            )
            for m in item.matches
        ],
        suggested_account_id=item.suggested_account_id,
        match_is_ambiguous=item.match_is_ambiguous,
    )


def _file_model(item: service.FileImport, data_dir: Path) -> FileImportModel:
    return FileImportModel(
        filename=_relative(item.path, data_dir),
        status=item.status.value,
        adapter=item.adapter,
        broker=item.broker.value if item.broker else None,
        account_id=item.account_id,
        import_id=item.import_id,
        row_count=item.row_count,
        usable_row_count=item.usable_row_count,
        inserted=item.inserted,
        duplicates=item.duplicates,
        conflicts=list(item.conflicts),
        skipped=dict(item.skipped),
        instruments=item.instruments,
        detail=item.detail,
        warnings=list(item.warnings),
    )


__all__ = ["router"]
