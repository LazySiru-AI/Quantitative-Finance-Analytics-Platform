"""Remote mode: the data service is the system of record; this process keeps only a disposable replica.

**Reads.** :func:`fresh_replica` asks the service for its ledger revision (at most once per
``Settings.db_service_poll_s``). When the revision moved, it pulls ``/v1/ledger/snapshot`` and writes
a new replica file named for that revision, built through the app's own :func:`app.db.sqlite.migrate`
so every reader sees exactly the schema it was written against. Each revision gets its *own* file
rather than replacing one in place: on Windows a file another request still has open cannot be
replaced, and a reader mid-query must never see a half-written ledger. Older replicas are deleted
best-effort once a newer one exists.

**Writes.** :func:`write_session` hands the caller a private copy of the current replica. The existing
ingest pipeline writes into it exactly as it writes a local ledger. On a clean exit the copy is
diffed against the replica it started from, table by table on primary key, and the difference is
posted as one changeset naming the replica's revision as its base. The service applies it atomically
or refuses it (``412``) if another writer got there first; nothing is half-applied either way.

**Failure.** A service that cannot be reached is not an empty ledger. If a replica exists it keeps
being served (stale, with a warning in the log); if none exists, :class:`DataServiceError` propagates
and the API answers ``503``.
"""

from __future__ import annotations

import contextlib
import logging
import re
import shutil
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.datasource import DataServiceError, DocumentKey
from app.db import sqlite as ledger_db

logger = logging.getLogger(__name__)

#: Ledger tables in foreign-key order, with their primary keys. Must match the data service's
#: ``ledger_service.db.PRIMARY_KEYS``.
LEDGER_TABLES: dict[str, tuple[str, ...]] = {
    "account": ("account_id",),
    "instrument": ("instrument_id",),
    "symbol_alias": ("symbol", "broker"),
    "raw_import": ("import_id",),
    "raw_row": ("import_id", "row_index"),
    "txn": ("txn_id",),
}

_REPLICA_RE = re.compile(r"^r(\d+)\.sqlite$")
_lock = threading.RLock()
_last_check: dict[str, float] = {}


# -- paths ------------------------------------------------------------------------------------------


def replica_dir(settings: Settings) -> Path:
    return settings.cache_dir / "ledger-replica"


def _replicas(settings: Settings) -> list[tuple[int, Path]]:
    folder = replica_dir(settings)
    if not folder.is_dir():
        return []
    found = []
    for path in folder.iterdir():
        match = _REPLICA_RE.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    return sorted(found)


def current_replica_path(settings: Settings) -> Path:
    """Newest replica on disk, or a path that does not exist when there is none yet."""
    replicas = _replicas(settings)
    return replicas[-1][1] if replicas else replica_dir(settings) / "r-none.sqlite"


def _replica_revision(path: Path) -> int | None:
    match = _REPLICA_RE.match(path.name)
    return int(match.group(1)) if match else None


# -- HTTP -------------------------------------------------------------------------------------------


def _client(settings: Settings) -> httpx.Client:
    token = settings.db_service_token.get_secret_value() if settings.db_service_token else ""
    if not token:
        raise DataServiceError("INVDASH_DB_SERVICE_TOKEN is not set")
    return httpx.Client(
        base_url=settings.db_service_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}", "Accept-Encoding": "gzip"},
        timeout=settings.db_service_timeout_s,
    )


def _request(settings: Settings, method: str, path: str, **kwargs: Any) -> httpx.Response:
    try:
        with _client(settings) as client:
            response = client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        raise DataServiceError(f"data service unreachable at {settings.db_service_url}: {exc}") from exc
    if response.status_code == 401:
        raise DataServiceError("data service rejected the token (check INVDASH_DB_SERVICE_TOKEN)")
    return response


def _expect_ok(response: httpx.Response, what: str) -> Any:
    if response.status_code >= 400:
        raise DataServiceError(f"{what} failed: HTTP {response.status_code} {response.text[:300]}")
    return response.json()


# -- reads ------------------------------------------------------------------------------------------


def fresh_replica(settings: Settings, *, force: bool = False) -> Path:
    """The replica, refreshed if the service has a newer revision. Serves a stale one if unreachable."""
    with _lock:
        current = current_replica_path(settings)
        key = str(replica_dir(settings))
        now = time.monotonic()
        if not force and current.exists() and now - _last_check.get(key, 0.0) < settings.db_service_poll_s:
            return current
        try:
            info = _expect_ok(_request(settings, "GET", "/v1/ledger"), "ledger revision check")
        except DataServiceError:
            if current.exists():
                logger.warning("data service unreachable; serving replica %s", current.name, exc_info=True)
                return current
            raise
        _last_check[key] = now
        revision = int(info["revision"])
        if current.exists() and _replica_revision(current) == revision:
            return current
        return _pull_snapshot(settings)


def _pull_snapshot(settings: Settings) -> Path:
    response = _request(settings, "GET", "/v1/ledger/snapshot")
    snapshot = _expect_ok(response, "ledger snapshot")
    if int(snapshot["schema_version"]) != ledger_db.SCHEMA_VERSION:
        raise DataServiceError(
            f"data service ledger is schema version {snapshot['schema_version']}; this app expects "
            f"{ledger_db.SCHEMA_VERSION}. Upgrade whichever side is behind."
        )
    revision = int(snapshot["revision"])
    folder = replica_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"r{revision}.sqlite"
    if not target.exists():
        staging = folder / f".staging-{uuid.uuid4().hex}.sqlite"
        try:
            _materialise(staging, snapshot["tables"])
            staging.replace(target)
        finally:
            staging.unlink(missing_ok=True)
        logger.info("ledger replica refreshed to revision %s (%s transactions)", revision, snapshot["txn_count"])
    _prune(settings, keep=target)
    return target


def _materialise(path: Path, tables: dict[str, Any]) -> None:
    with ledger_db.connect(path) as conn:
        ledger_db.migrate(conn)
        conn.execute("BEGIN")
        for table in LEDGER_TABLES:
            payload = tables.get(table)
            if payload is None:
                raise DataServiceError(f"snapshot is missing table {table!r}")
            cols: list[str] = payload["columns"]
            local = set(_columns(conn, table))
            unknown = [c for c in cols if c not in local]
            if unknown:
                raise DataServiceError(f"snapshot table {table!r} has columns this app does not know: {unknown}")
            if payload["rows"]:
                conn.executemany(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    payload["rows"],
                )
        conn.execute("COMMIT")
        conn.execute("PRAGMA journal_mode = DELETE")


def _prune(settings: Settings, *, keep: Path) -> None:
    for _, path in _replicas(settings):
        if path != keep:
            # Still open by a reader on Windows; the next refresh retries.
            with contextlib.suppress(OSError):
                path.unlink()


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")]


# -- writes -----------------------------------------------------------------------------------------


@contextmanager
def write_session(settings: Settings) -> Iterator[Path]:
    """A private writable copy of the replica; its changes are pushed as one changeset on clean exit."""
    with _lock:
        base = fresh_replica(settings, force=True)
        base_revision = _replica_revision(base)
        folder = replica_dir(settings)
        folder.mkdir(parents=True, exist_ok=True)
        work = folder / f".write-{uuid.uuid4().hex}.sqlite"
        if base.exists():
            shutil.copyfile(base, work)
        try:
            yield work
            if base_revision is None:
                base_revision = 0
            tables = diff_ledgers(base if base.exists() else None, work)
            if tables:
                response = _request(
                    settings,
                    "POST",
                    "/v1/ledger/changesets",
                    json={"base_revision": base_revision, "tables": tables},
                )
                if response.status_code == 412:
                    raise DataServiceError(
                        "the ledger changed on the data service while this import ran; nothing was "
                        "written -- run the import again"
                    )
                result = _expect_ok(response, "ledger changeset")
                logger.info("changeset accepted: revision %s, inserted %s", result["revision"], result["inserted"])
                fresh_replica(settings, force=True)
        finally:
            for suffix in ("", "-wal", "-shm", "-journal"):
                Path(f"{work}{suffix}").unlink(missing_ok=True)


def diff_ledgers(base: Path | None, work: Path) -> dict[str, dict[str, Any]]:
    """Rows in ``work`` that are absent from ``base`` or differ from it, per table, columnar."""
    out: dict[str, dict[str, Any]] = {}
    with ledger_db.connect(work, read_only=True) as wconn:
        base_conn = sqlite3.connect(f"file:{base.as_posix()}?mode=ro", uri=True) if base else None
        try:
            for table, pk in LEDGER_TABLES.items():
                cols = _columns(wconn, table)
                select = f"SELECT {', '.join(cols)} FROM {table}"
                pk_idx = [cols.index(k) for k in pk]
                known: dict[tuple[Any, ...], tuple[Any, ...]] = {}
                if base_conn is not None:
                    for row in base_conn.execute(select):
                        known[tuple(row[i] for i in pk_idx)] = tuple(row)
                changed = [
                    list(row)
                    for row in wconn.execute(select)
                    if known.get(tuple(row[i] for i in pk_idx)) != tuple(row)
                ]
                if changed:
                    out[table] = {"columns": cols, "rows": changed}
        finally:
            if base_conn is not None:
                base_conn.close()
    return out


# -- documents --------------------------------------------------------------------------------------


def read_document(settings: Settings, key: DocumentKey) -> str | None:
    response = _request(settings, "GET", f"/v1/documents/{key}")
    if response.status_code == 404:
        return None
    return str(_expect_ok(response, f"read document {key}")["content"])


def write_document(settings: Settings, key: DocumentKey, content: str) -> None:
    response = _request(settings, "PUT", f"/v1/documents/{key}", json={"content": content})
    _expect_ok(response, f"write document {key}")
