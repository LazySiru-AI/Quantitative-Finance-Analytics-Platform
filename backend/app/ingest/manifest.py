"""The account manifest: which account each broker export belongs to.

An adapter is chosen by header signature (see :mod:`app.ingest.registry`), and that works because a
Robinhood file *looks* like a Robinhood file. **Which account it is cannot be recovered the same
way.** Robinhood's three exports are byte-identical in structure; only the user knows that one is
the Roth. The filename is the obvious tempting source and is the wrong one, for the same reason the
registry refuses to detect adapters by filename: the user renames exports freely, and a guess that
lands wrong produces numbers that are silently incorrect rather than absent.

Two of the four declared fields change tax figures:

* ``tax_treatment`` decides whether an account's gains are reported at all, and whether a
  replacement purchase inside it destroys a loss permanently under Rev. Rul. 2008-5 instead of
  deferring it. There is **no safe default**, so it is required and an absent value raises. Reading
  "Roth" out of a filename would be a guess about the single field with the most tax leverage in the
  system.
* ``account_type`` decides whether :mod:`app.core.cash` applies its running-balance check --
  a margin account may legitimately go negative, a cash account may not. This one *does* have a
  conservative default (``cash``, which applies the check), so it is optional; declaring a cash
  account as margin suppresses a real correctness check, which is why the generated template writes
  it out explicitly rather than leaving it implied.

``broker`` is optional and is a **cross-check, not an input**: the adapter that matched the header is
the authority, and a manifest that disagrees with it means the entry is pointing at the wrong file.
That is worth stopping for, since the usual cause is a filename edited in one place and not the
other.

Format is TOML, read with the standard library's :mod:`tomllib` -- no new dependency, and comments
survive round-trips through a text editor, which matters for a file the user maintains by hand::

    [[account]]
    file = "robinhood-taxable.csv"
    account_id = "rh-taxable"
    label = "Taxable"
    tax_treatment = "taxable"
    account_type = "cash"

The manifest lives beside the exports it describes, under ``data/``, and is therefore gitignored
along with them: it names real accounts.
"""

from __future__ import annotations

import datetime as dt
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.config import Settings
from app.core.cash import DeclaredCash
from app.core.lots import OpeningPosition, TransferBasis
from app.core.models import Account, AccountStatus, AccountType, Broker, TaxTreatment

__all__ = [
    "MANIFEST_FILENAME",
    "AccountEntry",
    "Manifest",
    "ManifestError",
    "append_entry",
    "append_entry_document",
    "load_declarations",
    "load_manifest",
    "load_manifest_document",
    "load_manifest_text",
    "render_template",
]

#: Conventional name, resolved inside ``settings.data_dir``.
MANIFEST_FILENAME = "accounts.toml"

_ENTRY_KEYS = frozenset(
    {"file", "account_id", "label", "tax_treatment", "account_type", "status", "broker"}
)
_TOP_LEVEL_KEYS = frozenset({"account", "cash", "opening_position", "transfer_basis"})
_CASH_KEYS = frozenset({"account_id", "balance", "settled", "unsettled", "as_of", "note"})
_OPENING_KEYS = frozenset(
    {"account_id", "symbol", "quantity", "as_of", "cost_basis", "acquired_date", "note"}
)
_TRANSFER_BASIS_KEYS = frozenset(
    {"account_id", "symbol", "quantity", "as_of", "cost_basis", "acquired_date", "note"}
)


class ManifestError(ValueError):
    """The manifest is missing, malformed, or incomplete.

    Always fatal. A partially-understood manifest imports some files into the right accounts and
    others into wrong ones, and the result is a ledger that looks complete and is not.
    """


@dataclass(frozen=True, slots=True)
class AccountEntry:
    """One file, and the account it belongs to."""

    path: Path
    """Absolute path to the export, resolved against the manifest's own directory."""
    account: Account
    declared_broker: Broker | None
    """What the manifest claimed, if anything. Checked against the resolved adapter; never used in
    place of it."""


@dataclass(frozen=True, slots=True)
class Manifest:
    """Every declared file, in declaration order, plus any cash the user declared by hand."""

    path: Path
    entries: tuple[AccountEntry, ...]
    declared_cash: Mapping[str, DeclaredCash] = field(default_factory=dict)
    """Balances stated from the broker, by ``account_id`` -- see :class:`app.core.cash.DeclaredCash`.

    Lives here rather than in a file of its own because it is the same kind of fact as everything
    else in this manifest: something only the user can supply, which no amount of parsing recovers.
    Several real accounts export order history with no cash rows at all."""

    opening_positions: tuple[OpeningPosition, ...] = ()
    """Shares each account already held when its export begins -- see
    :class:`app.core.lots.OpeningPosition`. The same kind of fact again: a broker export is a window,
    not a life, and a position older than the file is invisible without being declared."""

    transfer_bases: tuple[TransferBasis, ...] = ()
    """Cost basis for inbound transfers whose sending leg this dataset cannot supply -- see
    :class:`app.core.lots.TransferBasis`. Again the same kind of fact: an ACAT carries basis with the
    shares, but the engine can only preserve it when it can see the leg the shares left from."""

    def entry_for(self, path: Path) -> AccountEntry | None:
        """The entry describing ``path``, or ``None`` if the file is not declared."""
        target = path.resolve()
        return next((e for e in self.entries if e.path == target), None)

    @property
    def declared_paths(self) -> tuple[Path, ...]:
        return tuple(entry.path for entry in self.entries)


def _missing_manifest_error(path: Path) -> ManifestError:
    return ManifestError(
        f"no account manifest at {path}. Every broker export has to be assigned to an account "
        "before it can be imported -- the file's header identifies the broker but not which of "
        "that broker's accounts it is. Run `python -m app.ingest --init` to write a template "
        "covering the files already present."
    )


def load_manifest(path: Path) -> Manifest:
    """Parse and validate the manifest at ``path``.

    Raises:
        ManifestError: The file is absent, is not valid TOML, or any entry is incomplete,
            duplicated, or contradicts another entry for the same account.
    """
    if not path.exists():
        raise _missing_manifest_error(path)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ManifestError(f"{path} is not valid UTF-8: {exc}") from exc
    return load_manifest_text(text, path)


def load_manifest_document(settings: Settings | None = None) -> Manifest:
    """Parse the ``accounts-manifest`` document from the data source (file, demo seed or remote).

    A never-written document raises the same :class:`ManifestError` a missing file does.
    """
    from app.datasource import local_document_path, read_document

    nominal = local_document_path("accounts-manifest", settings)
    try:
        text = read_document("accounts-manifest", settings)
    except UnicodeDecodeError as exc:
        raise ManifestError(f"{nominal} is not valid UTF-8: {exc}") from exc
    if text is None:
        raise _missing_manifest_error(nominal)
    return load_manifest_text(text, nominal)


def load_manifest_text(text: str, path: Path) -> Manifest:
    """Parse and validate manifest ``text``; ``path`` is its nominal location.

    ``path`` anchors relative ``file`` entries (resolved against its parent) and prefixes errors.
    """
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"{path} is not valid TOML: {exc}") from exc

    unknown_top = sorted(set(raw) - _TOP_LEVEL_KEYS)
    if unknown_top:
        raise ManifestError(
            f"{path} has unknown top-level key(s) {unknown_top}; the tables are [[account]], "
            "[[cash]], [[opening_position]] and [[transfer_basis]]"
        )

    rows = raw.get("account", [])
    if not isinstance(rows, list) or not rows:
        raise ManifestError(
            f"{path} declares no accounts. Each export needs an [[account]] entry naming its file "
            "and tax treatment."
        )

    entries: list[AccountEntry] = []
    seen_files: dict[Path, int] = {}
    by_account: dict[str, tuple[int, Account]] = {}

    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ManifestError(f"{path}: [[account]] entry {index} is not a table")
        entry = _entry_from_row(row, index=index, manifest_path=path)

        first_seen = seen_files.get(entry.path)
        if first_seen is not None:
            raise ManifestError(
                f"{path}: {entry.path.name!r} is declared twice (entries {first_seen} and {index}). "
                "One file belongs to one account."
            )
        seen_files[entry.path] = index

        # The same account legitimately appears more than once -- a 2025 export and a 2026 export of
        # the same Robinhood account are two files, and re-importing overlapping rows is a no-op by
        # design. What must not differ is what those entries *say* about the account, since the last
        # one written would silently win at `upsert_account`. `status` is the deliberate exception:
        # entries are allowed to disagree about it (see the merge below), because the account being
        # closed is a fact about the account, not about any one file.
        previous = by_account.get(entry.account.account_id)
        if previous is not None:
            prior_index, prior_account = previous
            if _identity_fields(prior_account) != _identity_fields(entry.account):
                raise ManifestError(
                    f"{path}: account {entry.account.account_id!r} is described differently in "
                    f"entries {prior_index} and {index}. Two files may share an account, but they "
                    "must agree about its label, tax treatment and account type."
                )
        else:
            by_account[entry.account.account_id] = (index, entry.account)

        entries.append(entry)

    # Merge `status` across every entry sharing an account_id: an account is closed if ANY of its
    # entries declares it closed, even though most entries leave the key absent (open). This runs
    # after the loop above because the identity check there deliberately ignores `status` -- one
    # entry may say nothing (open by default) while a later one for the same account_id says closed,
    # and both are honest statements about the same account at different points in its history.
    closed_ids = {
        entry.account.account_id for entry in entries if entry.account.status is AccountStatus.CLOSED
    }
    entries = [
        entry
        if entry.account.account_id not in closed_ids
        else AccountEntry(
            path=entry.path,
            account=entry.account.model_copy(update={"status": AccountStatus.CLOSED}),
            declared_broker=entry.declared_broker,
        )
        for entry in entries
    ]

    return Manifest(
        path=path.resolve(),
        entries=tuple(entries),
        declared_cash=_declared_cash(raw.get("cash", []), path=path, known=set(by_account)),
        opening_positions=_opening_positions(
            raw.get("opening_position", []), path=path, known=set(by_account)
        ),
        transfer_bases=_transfer_bases(
            raw.get("transfer_basis", []), path=path, known=set(by_account)
        ),
    )


def _identity_fields(account: Account) -> tuple[Broker, str, TaxTreatment, AccountType]:
    """Everything two entries for the same account_id must agree on -- excludes `status`.

    `status` is deliberately left out: entries are allowed to disagree about it (see the merge in
    `load_manifest`), because closing an account is a fact that arrives later than the entry that
    first declared it, not a contradiction to reject.
    """
    return (account.broker, account.label, account.tax_treatment, account.account_type)


def _entry_from_row(row: dict[str, object], *, index: int, manifest_path: Path) -> AccountEntry:
    unknown = sorted(set(row) - _ENTRY_KEYS)
    if unknown:
        raise ManifestError(
            f"{manifest_path}: entry {index} has unknown key(s) {unknown}; "
            f"valid keys are {sorted(_ENTRY_KEYS)}"
        )

    file_value = _required_str(row, "file", index=index, manifest_path=manifest_path)
    relative = Path(file_value)
    root = manifest_path.parent.resolve()
    resolved = (root / relative).resolve()
    # Containment is checked on the *resolved* path rather than by inspecting the text, because the
    # textual checks are not portable: `Path("/etc/passwd").is_absolute()` is False on Windows (no
    # drive letter), yet joining it onto the data directory yields `C:\etc\passwd` -- outside. The
    # drive-anchored and `..` forms are named separately only to give a clearer message.
    if relative.is_absolute() or relative.drive or relative.root or ".." in relative.parts:
        raise ManifestError(
            f"{manifest_path}: entry {index} has file={file_value!r}. Paths are relative to the "
            "manifest's own directory, and may not be absolute, drive- or root-anchored, or "
            "contain '..'."
        )
    if not resolved.is_relative_to(root):
        raise ManifestError(
            f"{manifest_path}: entry {index} has file={file_value!r}, which resolves to "
            f"{resolved} -- outside {root}. A manifest may only name files beside itself."
        )

    account_id = _required_str(row, "account_id", index=index, manifest_path=manifest_path)
    label = _optional_str(row, "label", index=index, manifest_path=manifest_path) or account_id

    treatment_text = _optional_str(row, "tax_treatment", index=index, manifest_path=manifest_path)
    if not treatment_text:
        raise ManifestError(
            f"{manifest_path}: entry {index} ({file_value}) does not declare tax_treatment. "
            f"It is required and has no default -- valid values are "
            f"{[t.value for t in TaxTreatment]}. It decides whether this account's gains are "
            "reported at all, and whether a replacement purchase in it destroys a loss permanently "
            "(Rev. Rul. 2008-5) rather than deferring it, so it is not something to infer from a "
            "filename."
        )
    try:
        tax_treatment = TaxTreatment(treatment_text)
    except ValueError:
        raise ManifestError(
            f"{manifest_path}: entry {index} has tax_treatment={treatment_text!r}; "
            f"valid values are {[t.value for t in TaxTreatment]}"
        ) from None

    type_text = _optional_str(row, "account_type", index=index, manifest_path=manifest_path)
    try:
        account_type = AccountType(type_text) if type_text else AccountType.CASH
    except ValueError:
        raise ManifestError(
            f"{manifest_path}: entry {index} has account_type={type_text!r}; "
            f"valid values are {[t.value for t in AccountType]}"
        ) from None

    status_text = _optional_str(row, "status", index=index, manifest_path=manifest_path)
    try:
        status = AccountStatus(status_text) if status_text else AccountStatus.OPEN
    except ValueError:
        raise ManifestError(
            f"{manifest_path}: entry {index} has status={status_text!r}; "
            f"valid values are {[s.value for s in AccountStatus]}"
        ) from None

    broker_text = _optional_str(row, "broker", index=index, manifest_path=manifest_path)
    try:
        declared_broker = Broker(broker_text) if broker_text else None
    except ValueError:
        raise ManifestError(
            f"{manifest_path}: entry {index} has broker={broker_text!r}; "
            f"valid values are {[b.value for b in Broker]}"
        ) from None

    # `Account` needs a broker at construction. When the manifest does not declare one it is filled
    # in from the adapter that matched the header, in `app.ingest.service` -- which is the authority
    # either way. A placeholder here would be a value nothing checked.
    return AccountEntry(
        path=resolved,
        account=Account(
            account_id=account_id,
            broker=declared_broker or Broker.ROBINHOOD,
            label=label,
            tax_treatment=tax_treatment,
            account_type=account_type,
            status=status,
        ),
        declared_broker=declared_broker,
    )


def _required_str(
    row: dict[str, object], key: str, *, index: int, manifest_path: Path
) -> str:
    value = _optional_str(row, key, index=index, manifest_path=manifest_path)
    if not value:
        raise ManifestError(f"{manifest_path}: entry {index} is missing required key {key!r}")
    return value


def _optional_str(
    row: dict[str, object], key: str, *, index: int, manifest_path: Path
) -> str | None:
    if key not in row:
        return None
    value = row[key]
    if not isinstance(value, str):
        raise ManifestError(
            f"{manifest_path}: entry {index} has {key}={value!r}, which is not a string"
        )
    return value.strip() or None


def append_entry(
    path: Path,
    *,
    file: str,
    account_id: str,
    label: str,
    tax_treatment: TaxTreatment,
    account_type: AccountType,
    status: AccountStatus = AccountStatus.OPEN,
    note: str = "",
) -> None:
    """Add one ``[[account]]`` entry, creating the manifest if it does not exist yet.

    The UI's account decision has to persist, or the next ``python -m app.ingest`` would ask for it
    again and the two entry points would disagree about what the user has already answered. The
    manifest stays the single record of file-to-account attribution; this is how a choice made in a
    browser gets written into it.

    Appends rather than rewrites: the file is hand-edited, carries the user's own comments, and
    re-rendering it from parsed state would quietly discard them.

    Raises:
        ManifestError: ``file`` is already declared. Re-assigning a file is an edit, and an edit to
            an existing entry is not something to do behind the user's back -- the rows already
            imported under the old account do not move, so a silent change would leave the same
            trades under two accounts with nothing on screen saying so.
    """
    if path.exists():
        _reject_if_declared(load_manifest(path), path, file)

    block = _entry_block(
        file=file,
        account_id=account_id,
        label=label,
        tax_treatment=tax_treatment,
        account_type=account_type,
        status=status,
        note=note,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "" if path.exists() else _TEMPLATE_HEADER
    with path.open("a", encoding="utf-8") as handle:
        handle.write(header + block)


def append_entry_document(
    settings: Settings | None = None,
    *,
    file: str,
    account_id: str,
    label: str,
    tax_treatment: TaxTreatment,
    account_type: AccountType,
    status: AccountStatus = AccountStatus.OPEN,
    note: str = "",
) -> None:
    """:func:`append_entry` against the ``accounts-manifest`` document of the data source."""
    from app.datasource import local_document_path, read_document, write_document

    nominal = local_document_path("accounts-manifest", settings)
    current = read_document("accounts-manifest", settings)
    if current is not None:
        _reject_if_declared(load_manifest_text(current, nominal), nominal, file)
    block = _entry_block(
        file=file,
        account_id=account_id,
        label=label,
        tax_treatment=tax_treatment,
        account_type=account_type,
        status=status,
        note=note,
    )
    header = "" if current is not None else _TEMPLATE_HEADER
    write_document("accounts-manifest", (current or "") + header + block, settings)


def _reject_if_declared(existing: Manifest, path: Path, file: str) -> None:
    target = (path.parent / file).resolve()
    if any(entry.path == target for entry in existing.entries):
        raise ManifestError(
            f"{file!r} is already declared in {path.name}. Change the entry by hand if you mean "
            "to move this file to a different account -- rows already imported under the old "
            "one stay where they are, so this is not a change to make silently."
        )


def _entry_block(
    *,
    file: str,
    account_id: str,
    label: str,
    tax_treatment: TaxTreatment,
    account_type: AccountType,
    status: AccountStatus,
    note: str,
) -> str:
    lines = [
        "",
        "[[account]]",
    ]
    if note:
        lines.insert(1, f"# {note}")
    lines += [
        f'file = "{file}"',
        f'account_id = "{account_id}"',
        f'label = "{label}"',
        f'tax_treatment = "{tax_treatment.value}"',
        f'account_type = "{account_type.value}"',
    ]
    if status is not AccountStatus.OPEN:
        # Only written when non-default, so existing manifests -- and the common case of appending
        # an open account -- stay byte-identical to what they were before `status` existed.
        lines.append(f'status = "{status.value}"')
    lines.append("")
    return "\n".join(lines)


_TEMPLATE_HEADER = "\n".join(
    [
        "# Account manifest -- which account each broker export belongs to.",
        "#",
        "# The adapter is chosen by header signature, so the broker is detected for you. Which",
        "# *account* a file represents cannot be detected: two exports from one broker are",
        "# structurally identical. Entries below were written either by `--init` or by the Import",
        "# panel; both leave the file hand-editable.",
        "",
    ]
)


def render_template(detected: Sequence[tuple[Path, str, Broker]], *, data_dir: Path) -> str:
    """Render a starting manifest for files already present.

    ``detected`` is ``(path, adapter_name, broker)`` per file, as resolved by the registry. Every
    field this function can honestly fill in is filled in; ``tax_treatment`` is deliberately left
    empty, because the whole point of the manifest is that this value comes from the user rather
    than from a filename. A template that pre-filled it with a guess would be read as a suggestion
    and accepted unchanged, which is the failure this file exists to prevent.
    """
    lines = [
        "# Account manifest -- which account each broker export belongs to.",
        "#",
        "# The adapter is chosen by header signature, so the broker is detected for you. Which",
        "# *account* a file represents cannot be detected: Robinhood's taxable and Roth exports are",
        "# structurally identical. Fill in tax_treatment for each entry before importing.",
        "#",
        "#   tax_treatment: " + " | ".join(t.value for t in TaxTreatment) + "   (required)",
        "#   account_type:  " + " | ".join(t.value for t in AccountType) + "   (default: cash)",
        "#",
        "# account_type is not cosmetic: a cash account is checked for a negative running balance",
        "# and a margin account is not, so declaring the wrong one either suppresses a real check or",
        "# withholds a cash figure for the wrong reason.",
        "",
    ]
    if not detected:
        lines += [
            f"# No broker exports found in {data_dir}. Drop the CSVs in and re-run --init.",
            "",
        ]
    for path, adapter_name, broker in detected:
        try:
            relative = path.resolve().relative_to(data_dir.resolve()).as_posix()
        except ValueError:
            relative = path.name
        lines += [
            "[[account]]",
            f'file = "{relative}"',
            f'account_id = "{_suggest_account_id(path, broker)}"',
            f'label = "{path.stem}"',
            'tax_treatment = ""  # REQUIRED -- fill this in',
            'account_type = "cash"',
            f'broker = "{broker.value}"  # detected from the header by the {adapter_name} adapter',
            "",
        ]
    return "\n".join(lines)


def _suggest_account_id(path: Path, broker: Broker) -> str:
    """A slug from the filename, offered as a starting point.

    Safe to derive where ``tax_treatment`` is not: an id is a label the user can rewrite freely and
    no calculation reads meaning out of it. It still gets written into a file the user edits before
    anything runs, so a bad suggestion is visible rather than silently applied.
    """
    stem = path.stem.lower()
    keep = [char if char.isalnum() else "-" for char in stem]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    prefix = {Broker.ROBINHOOD: "rh", Broker.WEBULL: "wb", Broker.SOFI: "sofi"}[broker]
    return slug if slug.startswith(prefix) else f"{prefix}-{slug}"


def _declared_cash(
    rows: object, *, path: Path, known: set[str]
) -> dict[str, DeclaredCash]:
    """Parse the optional ``[[cash]]`` tables into :class:`~app.core.cash.DeclaredCash`.

    **Money is required to be a TOML string, and a float is rejected outright.** TOML numbers are
    IEEE 754 doubles, so ``balance = 1234.56`` arrives as ``1234.5599999999999454...`` and would
    put representation error into the one figure the user typed in by hand -- in a file whose whole
    purpose is to record facts the system cannot compute. This is the same rule the rest of the
    application follows at every boundary; it is only worth restating here because TOML makes
    writing the wrong thing look natural.

    ``as_of`` is required for the reason given on :attr:`app.core.cash.AccountCash.declared_as_of`:
    a declared balance is a snapshot and goes stale silently, so it may not be recorded without the
    date it was true.
    """
    if not rows:
        return {}
    if not isinstance(rows, list):
        raise ManifestError(f"{path}: [[cash]] must be a list of tables")

    declared: dict[str, DeclaredCash] = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ManifestError(f"{path}: [[cash]] entry {index} is not a table")
        unknown = sorted(set(row) - _CASH_KEYS)
        if unknown:
            raise ManifestError(
                f"{path}: [[cash]] entry {index} has unknown key(s) {unknown}; "
                f"allowed keys are {sorted(_CASH_KEYS)}"
            )

        account_id = _required_str(row, "account_id", index=index, manifest_path=path)
        if account_id not in known:
            raise ManifestError(
                f"{path}: [[cash]] entry {index} declares a balance for account "
                f"{account_id!r}, which no [[account]] entry describes. Cash is declared *for* an "
                "account, so the account has to exist first."
            )
        if account_id in declared:
            raise ManifestError(
                f"{path}: account {account_id!r} has more than one [[cash]] entry. One balance per "
                "account -- two would silently resolve to whichever was written last."
            )

        as_of = _toml_date(row.get("as_of"))
        if as_of is None:
            raise ManifestError(
                f"{path}: [[cash]] entry {index} ({account_id}) needs an `as_of` date, written "
                "unquoted as TOML understands it, e.g. `as_of = 2026-08-14`. A declared balance "
                "without the date it was true cannot be told apart from a current one."
            )

        balance = _money(row, "balance", index=index, account_id=account_id, path=path)
        if balance is None:
            raise ManifestError(
                f"{path}: [[cash]] entry {index} ({account_id}) is missing `balance`"
            )
        declaration = DeclaredCash(
            account_id=account_id,
            balance=balance,
            as_of=as_of,
            settled=_money(row, "settled", index=index, account_id=account_id, path=path),
            unsettled=_money(row, "unsettled", index=index, account_id=account_id, path=path),
            note=_optional_str(row, "note", index=index, manifest_path=path) or "",
        )
        try:
            declaration.validate()
        except ValueError as exc:
            raise ManifestError(f"{path}: [[cash]] entry {index} -- {exc}") from exc
        declared[account_id] = declaration

    return declared


def _money(
    row: dict[str, object],
    key: str,
    *,
    index: int,
    account_id: str,
    path: Path,
) -> Decimal | None:
    """One money field from a ``[[cash]]`` table. String in, ``Decimal`` out -- see `_declared_cash`."""
    value = row.get(key)
    if value is None:
        return None
    if isinstance(value, float | int) and not isinstance(value, bool):
        raise ManifestError(
            f"{path}: [[cash]] entry {index} ({account_id}) writes `{key}` as a TOML number. Money "
            f'must be quoted -- `{key} = "{value}"` -- because a TOML number is a float and cannot '
            "represent a cent exactly."
        )
    if not isinstance(value, str):
        raise ManifestError(
            f"{path}: [[cash]] entry {index} ({account_id}) has a non-string `{key}`"
        )
    try:
        return Decimal(value.strip())
    except InvalidOperation as exc:
        raise ManifestError(
            f"{path}: [[cash]] entry {index} ({account_id}) has `{key} = {value!r}`, which is not a "
            "number"
        ) from exc


def _opening_positions(
    rows: object, *, path: Path, known: set[str]
) -> tuple[OpeningPosition, ...]:
    """Parse the optional ``[[opening_position]]`` tables.

    Same rules as ``[[cash]]``: quantities and money are quoted strings because TOML numbers are
    IEEE 754 doubles, and ``as_of`` is required because a position stated without the date it was
    true cannot be placed in the replay at all -- it is the lot's acquisition date when no better one
    is known, and FIFO decides real money from it.

    ``cost_basis`` is optional and stays optional. Requiring it would mean refusing the share count,
    which is the half that fixes the position; an absent basis becomes an uncertain lot and a
    :data:`app.core.lots.WarningKind.MISSING_BASIS` warning rather than a silent zero.
    """
    if not rows:
        return ()
    if not isinstance(rows, list):
        raise ManifestError(f"{path}: [[opening_position]] must be a list of tables")

    seen: set[tuple[str, str]] = set()
    positions: list[OpeningPosition] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ManifestError(f"{path}: [[opening_position]] entry {index} is not a table")
        unknown = sorted(set(row) - _OPENING_KEYS)
        if unknown:
            raise ManifestError(
                f"{path}: [[opening_position]] entry {index} has unknown key(s) {unknown}; "
                f"allowed keys are {sorted(_OPENING_KEYS)}"
            )

        account_id = _required_str(row, "account_id", index=index, manifest_path=path)
        if account_id not in known:
            raise ManifestError(
                f"{path}: [[opening_position]] entry {index} is for account {account_id!r}, which "
                "no [[account]] entry describes."
            )
        symbol = _required_str(row, "symbol", index=index, manifest_path=path).upper()
        if (account_id, symbol) in seen:
            raise ManifestError(
                f"{path}: {account_id} declares more than one opening position in {symbol}. One per "
                "account and symbol -- two would silently resolve to whichever was written last."
            )
        seen.add((account_id, symbol))

        as_of = _toml_date(row.get("as_of"))
        if as_of is None:
            raise ManifestError(
                f"{path}: [[opening_position]] entry {index} ({account_id} {symbol}) needs an "
                "`as_of` date, written unquoted, e.g. `as_of = 2026-01-05`. It is normally the day "
                "the export begins, and it becomes the lot's acquisition date when no real one is "
                "known -- which makes the holding period shorter than the truth, never longer."
            )
        quantity = _money(row, "quantity", index=index, account_id=account_id, path=path)
        if quantity is None or quantity <= 0:
            raise ManifestError(
                f"{path}: [[opening_position]] entry {index} ({account_id} {symbol}) needs a "
                'positive quoted `quantity`, e.g. `quantity = "15"`. A zero or negative opening '
                "position is not a thing this can represent -- to say an account held nothing, omit "
                "the entry."
            )

        positions.append(
            OpeningPosition(
                account_id=account_id,
                symbol=symbol,
                quantity=quantity,
                as_of=as_of,
                cost_basis=_money(row, "cost_basis", index=index, account_id=account_id, path=path),
                acquired_date=_toml_date(row.get("acquired_date")),
                note=_optional_str(row, "note", index=index, manifest_path=path) or "",
            )
        )
    return tuple(positions)


def _transfer_bases(
    rows: object, *, path: Path, known: set[str]
) -> tuple[TransferBasis, ...]:
    """Parse the optional ``[[transfer_basis]]`` tables.

    Same shape as ``[[opening_position]]`` but ``cost_basis`` is **required**: an unbased inbound
    transfer already opens a zero-basis lot and warns without any declaration, so a transfer-basis
    row with no basis would carry no information. ``as_of`` is the transfer date on the receiving
    side and, with ``account_id`` and ``symbol``, identifies the one inbound leg the basis attaches
    to; more than one row for the same ``(account, symbol, as_of)`` is refused because they would
    silently resolve to whichever was written last.
    """
    if not rows:
        return ()
    if not isinstance(rows, list):
        raise ManifestError(f"{path}: [[transfer_basis]] must be a list of tables")

    seen: set[tuple[str, str, dt.date]] = set()
    bases: list[TransferBasis] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ManifestError(f"{path}: [[transfer_basis]] entry {index} is not a table")
        unknown = sorted(set(row) - _TRANSFER_BASIS_KEYS)
        if unknown:
            raise ManifestError(
                f"{path}: [[transfer_basis]] entry {index} has unknown key(s) {unknown}; "
                f"allowed keys are {sorted(_TRANSFER_BASIS_KEYS)}"
            )

        account_id = _required_str(row, "account_id", index=index, manifest_path=path)
        if account_id not in known:
            raise ManifestError(
                f"{path}: [[transfer_basis]] entry {index} is for account {account_id!r}, which "
                "no [[account]] entry describes."
            )
        symbol = _required_str(row, "symbol", index=index, manifest_path=path).upper()

        as_of = _toml_date(row.get("as_of"))
        if as_of is None:
            raise ManifestError(
                f"{path}: [[transfer_basis]] entry {index} ({account_id} {symbol}) needs an "
                "`as_of` date, written unquoted, e.g. `as_of = 2026-06-18`. It is the transfer date "
                "on the receiving side and is what matches this basis to one inbound transfer."
            )
        if (account_id, symbol, as_of) in seen:
            raise ManifestError(
                f"{path}: {account_id} declares more than one transfer basis for {symbol} on "
                f"{as_of}. One per account, symbol and date -- two would silently resolve to "
                "whichever was written last."
            )
        seen.add((account_id, symbol, as_of))

        quantity = _money(row, "quantity", index=index, account_id=account_id, path=path)
        if quantity is None or quantity <= 0:
            raise ManifestError(
                f"{path}: [[transfer_basis]] entry {index} ({account_id} {symbol}) needs a "
                'positive quoted `quantity`, e.g. `quantity = "150"`.'
            )
        cost_basis = _money(row, "cost_basis", index=index, account_id=account_id, path=path)
        if cost_basis is None or cost_basis < 0:
            raise ManifestError(
                f"{path}: [[transfer_basis]] entry {index} ({account_id} {symbol}) needs a "
                'non-negative quoted `cost_basis`, e.g. `cost_basis = "3664.40"`. It is the whole '
                "point of the entry -- an unbased transfer needs no declaration."
            )

        bases.append(
            TransferBasis(
                account_id=account_id,
                symbol=symbol,
                quantity=quantity,
                as_of=as_of,
                cost_basis=cost_basis,
                acquired_date=_toml_date(row.get("acquired_date")),
                note=_optional_str(row, "note", index=index, manifest_path=path) or "",
            )
        )
    return tuple(bases)


def _toml_date(value: object) -> dt.date | None:
    """A TOML date, accepting the datetime form ``tomllib`` produces for a date-time literal."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return None


def load_declarations(settings: Settings) -> Manifest | None:
    """The user's manifest for a read endpoint, or ``None`` when it is absent or unreadable.

    **Every read path that replays the ledger must go through this one function.** The manifest now
    carries facts that change what the replay produces -- opening positions and declared cash -- so a
    caller that forgets it does not merely lose a feature, it computes a *different portfolio* from
    the same database. That is exactly what happened: `app.api.portfolio` was wired up and
    `app.api.tax` was not, and the two pages disagreed about the realised gain and about
    whether a position was held. Two screens, one ledger, two answers, no error anywhere.

    **A broken or absent manifest degrades to no declarations, never to an error.** The manifest is
    an ingestion input; these are read endpoints, and a user who has not written one -- or who has a
    typo in one -- should still get their positions rather than a 500 on a page that does not
    otherwise need the file. The import path validates it loudly, which is where a malformed manifest
    actually costs something.
    """
    try:
        return load_manifest_document(settings)
    except ManifestError:
        return None
