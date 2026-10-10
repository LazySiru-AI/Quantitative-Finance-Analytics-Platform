"""The one door to personal data: the ledger and the small personal documents.

Every module that needs the transaction ledger, the account manifest, the sector labels or the
Planner board asks this package for it instead of opening a file under ``data/`` itself. That is what
lets the same code run in three modes (``Settings.data_source``):

``local``
    Files on this machine, read and written in place. What the test suite and offline development use.
``demo``
    ``local`` plus an invented demo portfolio seeded into an empty data directory
    (:mod:`app.datasource.demo`), so a fresh public clone renders every page with no real data.
``remote``
    The separate data service (``investing-dashboard-db``) is the system of record and nothing
    personal is persisted here. Reads pull the ledger on demand into a disposable replica that is
    refreshed whenever the service's revision moves; writes compute a changeset against that replica
    and push it back under an optimistic-concurrency precondition. See :mod:`app.datasource.remote`.

The contract callers rely on:

- :func:`ledger_db_path` returns a SQLite path to open **read-only**. It may not exist (an empty
  ledger); callers already handle that.
- :func:`ledger_writer` yields a writable SQLite path. Whatever was written is committed to the
  system of record when the block exits cleanly, and discarded if it raises.
- :func:`read_document` / :func:`write_document` move whole documents. ``None`` means "never written".
- :class:`DataServiceError` means the data service could not be reached or refused the request. The
  API layer maps it to ``503``.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from app.config import Settings, get_settings

DocumentKey = Literal["accounts-manifest", "sectors", "planner-board"]

#: Where each document lives in ``local``/``demo`` mode, relative to ``Settings.data_dir``.
LOCAL_DOCUMENT_PATHS: dict[str, str] = {
    "accounts-manifest": "accounts.toml",
    "sectors": "sectors.toml",
    "planner-board": "designer/board.json",
}


class DataServiceError(RuntimeError):
    """The data service is unreachable, misconfigured, or refused the request."""


def ledger_db_path(settings: Settings | None = None) -> Path:
    """Path of the ledger to open read-only, refreshed from the data service in remote mode."""
    cfg = settings or get_settings()
    if cfg.data_source == "remote":
        from app.datasource import remote

        return remote.fresh_replica(cfg)
    if cfg.data_source == "demo":
        from app.datasource import demo

        demo.ensure_seeded(cfg)
    return cfg.store_dir / "ledger.sqlite"


@contextmanager
def ledger_writer(settings: Settings | None = None) -> Iterator[Path]:
    """A writable ledger path; changes are committed to the system of record on clean exit."""
    cfg = settings or get_settings()
    if cfg.data_source == "remote":
        from app.datasource import remote

        with remote.write_session(cfg) as path:
            yield path
        return
    if cfg.data_source == "demo":
        from app.datasource import demo

        demo.ensure_seeded(cfg)
    yield cfg.store_dir / "ledger.sqlite"


def local_document_path(key: DocumentKey, settings: Settings | None = None) -> Path:
    cfg = settings or get_settings()
    return cfg.data_dir / LOCAL_DOCUMENT_PATHS[key]


def read_document(key: DocumentKey, settings: Settings | None = None) -> str | None:
    cfg = settings or get_settings()
    if cfg.data_source == "remote":
        from app.datasource import remote

        return remote.read_document(cfg, key)
    if cfg.data_source == "demo":
        from app.datasource import demo

        demo.ensure_seeded(cfg)
    path = local_document_path(key, cfg)
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def write_document(key: DocumentKey, content: str, settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    if cfg.data_source == "remote":
        from app.datasource import remote

        remote.write_document(cfg, key, content)
        return
    _atomic_write(local_document_path(key, cfg), content)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def validate_settings(settings: Settings) -> None:
    """Fail at startup on a remote configuration that could never work."""
    if settings.data_source != "remote":
        return
    token = settings.db_service_token.get_secret_value() if settings.db_service_token else ""
    if not token:
        raise DataServiceError(
            "INVDASH_DATA_SOURCE=remote requires INVDASH_DB_SERVICE_TOKEN (the data service's LEDGER_TOKEN)."
        )
    if not settings.db_service_url.startswith(("http://", "https://")):
        raise DataServiceError(f"INVDASH_DB_SERVICE_URL must be an http(s) URL, got {settings.db_service_url!r}")
