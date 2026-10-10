"""An in-memory stand-in for the separate data service (``investing-dashboard-db``).

It speaks the same wire contract the real service does -- ``/v1/ledger``, ``/v1/ledger/snapshot``,
``/v1/ledger/changesets`` and ``/v1/documents/{key}`` behind a bearer token -- so
``app.datasource.remote`` can be tested end to end without importing that package. The ledger lives
in a real SQLite file created by :func:`app.db.sqlite.migrate`, so column names and types match the
dashboard's schema exactly. The revision counter is plain Python state, which tests can bump to
simulate another writer.
"""

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.db import sqlite as ledger_db

#: Ledger tables in foreign-key order, with their primary keys (the service's wire contract).
TABLES: dict[str, tuple[str, ...]] = {
    "account": ("account_id",),
    "instrument": ("instrument_id",),
    "symbol_alias": ("symbol", "broker"),
    "raw_import": ("import_id",),
    "raw_row": ("import_id", "row_index"),
    "txn": ("txn_id",),
}
#: Reference tables a changeset may rewrite in place; every other table is append-only.
UPSERT_TABLES = frozenset({"account", "instrument", "symbol_alias"})
DOCUMENT_KEYS = frozenset({"accounts-manifest", "sectors", "planner-board"})


class _Rows(BaseModel):
    columns: list[str]
    rows: list[list[Any]]


class _Changeset(BaseModel):
    base_revision: int = Field(ge=0)
    tables: dict[str, _Rows] = Field(default_factory=dict)


class _DocumentWrite(BaseModel):
    content: str


class LedgerServiceFake:
    """State plus the FastAPI ``app`` serving it. ``requests`` logs ``"METHOD path"`` per call."""

    def __init__(self, db_path: Path, *, token: str = "test-token", schema_version: int | None = None) -> None:
        self.db_path = db_path
        self.token = token
        self.schema_version = ledger_db.SCHEMA_VERSION if schema_version is None else schema_version
        self.revision = 0
        self.documents: dict[str, dict[str, Any]] = {}
        self.requests: list[str] = []
        with ledger_db.connect(db_path) as conn:
            ledger_db.migrate(conn)
        self.app = self._build_app()

    # -- direct access for tests ---------------------------------------------------------------

    def count(self, table: str) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        finally:
            conn.close()

    def table_rows(self, table: str) -> tuple[list[str], list[list[Any]]]:
        conn = sqlite3.connect(self.db_path)
        try:
            cols = [str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")]
            order = ", ".join(TABLES[table])
            rows = [list(r) for r in conn.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {order}")]
            return cols, rows
        finally:
            conn.close()

    def seed_from(self, ledger_file: Path) -> None:
        """Copy every ledger row from ``ledger_file`` in as one accepted change (revision +1)."""
        src = sqlite3.connect(f"file:{ledger_file.as_posix()}?mode=ro", uri=True)
        try:
            tables = {}
            for table in TABLES:
                cols = [str(r[1]) for r in src.execute(f"PRAGMA table_info({table})")]
                rows = [list(r) for r in src.execute(f"SELECT {', '.join(cols)} FROM {table}")]
                tables[table] = _Rows(columns=cols, rows=rows)
        finally:
            src.close()
        self._apply(_Changeset(base_revision=self.revision, tables=tables))

    def bump_revision(self) -> None:
        """Simulate another writer landing a change without touching the rows."""
        self.revision += 1

    # -- protocol ------------------------------------------------------------------------------

    def _info(self, conn: sqlite3.Connection) -> dict[str, int]:
        count = int(conn.execute("SELECT COUNT(*) FROM txn").fetchone()[0])
        return {"revision": self.revision, "schema_version": self.schema_version, "txn_count": count}

    def _apply(self, change: _Changeset) -> dict[str, Any]:
        if change.base_revision != self.revision:
            raise HTTPException(status_code=412, detail={"current_revision": self.revision})
        unknown = set(change.tables) - set(TABLES)
        if unknown:
            raise HTTPException(status_code=422, detail=f"unknown table(s): {sorted(unknown)}")
        inserted: dict[str, int] = {}
        updated: dict[str, int] = {}
        unchanged: dict[str, int] = {}
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE")
            try:
                for table, pk in TABLES.items():
                    payload = change.tables.get(table)
                    if payload is None or not payload.rows:
                        continue
                    cols = payload.columns
                    pk_idx = [cols.index(k) for k in pk]
                    where = " AND ".join(f"{k} = ?" for k in pk)
                    ins = upd = same = 0
                    for row in payload.rows:
                        key = [row[i] for i in pk_idx]
                        existing = conn.execute(
                            f"SELECT {', '.join(cols)} FROM {table} WHERE {where}", key
                        ).fetchone()
                        if existing is None:
                            conn.execute(
                                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                row,
                            )
                            ins += 1
                        elif list(existing) == list(row):
                            same += 1
                        elif table in UPSERT_TABLES:
                            non_pk = [c for c in cols if c not in pk]
                            sets = ", ".join(f"{c} = ?" for c in non_pk)
                            conn.execute(
                                f"UPDATE {table} SET {sets} WHERE {where}",
                                [row[cols.index(c)] for c in non_pk] + key,
                            )
                            upd += 1
                        else:
                            raise HTTPException(status_code=409, detail=f"{table} row {key} is append-only")
                    inserted[table], updated[table], unchanged[table] = ins, upd, same
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            if any(inserted.values()) or any(updated.values()):
                self.revision += 1
            count = int(conn.execute("SELECT COUNT(*) FROM txn").fetchone()[0])
        finally:
            conn.close()
        return {
            "revision": self.revision,
            "txn_count": count,
            "inserted": inserted,
            "updated": updated,
            "unchanged": unchanged,
        }

    def _build_app(self) -> FastAPI:
        app = FastAPI()
        bearer = HTTPBearer(auto_error=False)
        service = self

        def require_token(creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> None:
            if creds is None or creds.credentials != service.token:
                raise HTTPException(status_code=401, detail="invalid or missing bearer token")

        auth = [Depends(require_token)]

        @app.get("/v1/ledger", dependencies=auth)
        def ledger_info() -> dict[str, int]:
            service.requests.append("GET /v1/ledger")
            conn = sqlite3.connect(service.db_path)
            try:
                return service._info(conn)
            finally:
                conn.close()

        @app.get("/v1/ledger/snapshot", dependencies=auth)
        def snapshot() -> dict[str, Any]:
            service.requests.append("GET /v1/ledger/snapshot")
            conn = sqlite3.connect(service.db_path)
            try:
                info = service._info(conn)
            finally:
                conn.close()
            tables = {}
            for table in TABLES:
                cols, rows = service.table_rows(table)
                tables[table] = {"columns": cols, "rows": rows}
            return {**info, "tables": tables}

        @app.post("/v1/ledger/changesets", dependencies=auth)
        def post_changeset(change: _Changeset) -> dict[str, Any]:
            service.requests.append("POST /v1/ledger/changesets")
            return service._apply(change)

        @app.get("/v1/documents/{key}", dependencies=auth)
        def get_document(key: str) -> dict[str, Any]:
            service.requests.append(f"GET /v1/documents/{key}")
            if key not in DOCUMENT_KEYS:
                raise HTTPException(status_code=404, detail=f"unknown document key {key!r}")
            doc = service.documents.get(key)
            if doc is None:
                raise HTTPException(status_code=404, detail=f"document {key!r} has not been written yet")
            return doc

        @app.put("/v1/documents/{key}", dependencies=auth)
        def put_document(key: str, body: _DocumentWrite) -> dict[str, Any]:
            service.requests.append(f"PUT /v1/documents/{key}")
            if key not in DOCUMENT_KEYS:
                raise HTTPException(status_code=404, detail=f"unknown document key {key!r}")
            previous = service.documents.get(key)
            doc = {
                "key": key,
                "content": body.content,
                "content_type": "application/json" if key == "planner-board" else "application/toml",
                "version": (previous["version"] + 1) if previous else 1,
                "updated_at": dt.datetime(2026, 9, 1, tzinfo=dt.UTC).isoformat(),
            }
            service.documents[key] = doc
            return doc

        return app
