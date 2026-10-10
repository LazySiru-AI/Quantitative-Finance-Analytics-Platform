"""Provenance: recording where every ledger row came from.

An import proceeds in three steps, in this order:

1. :func:`read_rows` reads the file verbatim, tolerating the encodings brokers actually emit.
2. :func:`build_import_record` hashes it and describes the import.
3. The adapter turns rows into transactions, which are written alongside the raw rows.

The raw rows are stored even though the file is still on disk, because the file will be replaced by a
newer export and the old one will be gone. Without the stored copy, "why does this lot say $4,851.90"
becomes unanswerable a month later.
"""

from __future__ import annotations

import csv
import datetime as dt
from collections.abc import Sequence
from pathlib import Path

from app.config import Settings, get_settings
from app.core.ids import content_hash, file_sha256, stable_id
from app.core.models import Broker, ImportRecord

__all__ = [
    "RawFile",
    "RowLimitExceeded",
    "build_import_record",
    "read_rows",
]

#: Encodings tried in order.
#:
#: All three brokers currently emit valid UTF-8 -- verified at byte level, including the bullet in
#: SoFi's "To SoFi Checking * 0000", which is E2 80 A2 (U+2022) and not the cp1252 byte it looks like
#: in a mis-configured console. The cp1252 fallback is kept because a broker can change encoding
#: between exports without warning, not because anything needs it today.
#:
#: Never fall back to errors="ignore": that silently corrupts a description rather than failing
#: somewhere visible, and a mangled description can be hiding a CUSIP.
_ENCODINGS = ("utf-8-sig", "cp1252")


class RawFile:
    """A broker export read verbatim, before any interpretation."""

    __slots__ = ("encoding", "header", "path", "rows")

    def __init__(
        self,
        path: Path,
        encoding: str,
        header: Sequence[str],
        rows: list[dict[str, str | None]],
    ) -> None:
        self.path = path
        self.encoding = encoding
        self.header = tuple(header)
        self.rows = rows

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def header_signature(self) -> str:
        """Normalised header, used to select an adapter.

        Detection is by header rather than filename because the user renames exports freely --
        ``Account A.csv`` tells the parser nothing.
        """
        return "|".join(h.strip().lower() for h in self.header)

    def content_hash(self) -> str:
        """Hash of the parsed content, stable across encoding and line-ending differences."""
        return content_hash(
            [tuple((row.get(col) or "") for col in self.header) for row in self.rows]
        )


class RowLimitExceeded(ValueError):
    """A broker CSV had more data rows than :attr:`~app.config.Settings.ingest_max_rows` permits.

    Raised while the file is still being iterated, not after it has been fully loaded -- the whole
    point of the ceiling is to fail fast with an actionable message instead of finishing the load
    (exhausting memory in the process) and only then discovering the file was too big.
    """

    def __init__(self, path: Path, max_rows: int) -> None:
        super().__init__(
            f"{path.name!r} has more than {max_rows:,} data rows; refusing to load the rest into "
            "memory. Raise Settings.ingest_max_rows (env var INVDASH_INGEST_MAX_ROWS) if this file "
            "is genuinely legitimate, or check whether it is corrupted or the wrong file."
        )
        self.path = path
        self.max_rows = max_rows


def read_rows(path: Path, *, settings: Settings | None = None) -> RawFile:
    """Read a broker CSV without interpreting it.

    Uses :mod:`csv` rather than line splitting, which is not optional here: 380 of Robinhood's 491
    rows contain a newline inside the quoted ``Description`` field, and any line-based reader shreds
    the file into nonsense.

    Raises:
        UnicodeDecodeError: The file matched none of the supported encodings. Deliberately fatal --
            a mangled description could be hiding a CUSIP.
        RowLimitExceeded: The file has more data rows than ``settings.ingest_max_rows`` (see that
            field's docstring for why the default is what it is). Checked row by row while reading
            rather than after the fact, so a pathological file is rejected before it is fully sitting
            in memory, which is the failure this ceiling exists to prevent in the first place.
    """
    cfg = settings or get_settings()
    max_rows = cfg.ingest_max_rows
    last_error: UnicodeDecodeError | None = None
    for encoding in _ENCODINGS:
        try:
            with path.open("r", newline="", encoding=encoding) as handle:
                reader = csv.DictReader(handle)
                header = reader.fieldnames or []
                rows: list[dict[str, str | None]] = []
                for row in reader:
                    if len(rows) >= max_rows:
                        raise RowLimitExceeded(path, max_rows)
                    rows.append(dict(row))
            return RawFile(path=path, encoding=encoding, header=header, rows=rows)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    assert last_error is not None
    raise last_error


def build_import_record(
    raw: RawFile,
    *,
    broker: Broker,
    account_id: str,
    adapter: str,
    adapter_version: str,
    usable_row_count: int,
    imported_at: dt.datetime | None = None,
) -> ImportRecord:
    """Describe an import, hashing the file both ways.

    Both hashes are kept because they answer different questions. ``file_sha256`` says "is this the
    same bytes"; ``content_hash`` says "is this the same data", and survives a broker switching line
    endings. Re-import detection uses the latter.

    ``usable_row_count`` is the number of rows that became transactions. The gap from ``row_count``
    is the regression signal for adapters: Webull should discard its cancelled or
    failed rows, SoFi its cancellations.
    """
    when = imported_at or dt.datetime.now(dt.UTC)
    digest = raw.content_hash()
    return ImportRecord(
        import_id=stable_id("import", digest, account_id, when.isoformat()),
        source_path=str(raw.path),
        filename=raw.path.name,
        file_sha256=file_sha256(raw.path),
        content_hash=digest,
        broker=broker,
        account_id=account_id,
        adapter=adapter,
        adapter_version=adapter_version,
        row_count=raw.row_count,
        usable_row_count=usable_row_count,
        imported_at=when,
    )
