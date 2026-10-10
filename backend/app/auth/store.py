"""The users-and-sessions database.

A SQLite file **separate from the ledger** (``Settings.auth_db_path``, default
``data_dir/auth.sqlite``). Keeping it out of ``store_dir/ledger.sqlite`` is deliberate: the ledger
carries a ``schema_version`` and a chain of ``_migrate_*`` steps (see ``app.db.sqlite``), and an
auth change has no business bumping that version or risking that migration path. This database has
no migration framework because it does not need one yet -- ``CREATE TABLE IF NOT EXISTS`` is the
whole schema story, and any future column change would add its own guarded step here the same way
the ledger does.

The two tables:

- ``user``    -- one row per named person. ``username`` is unique and stored lower-cased (see
  :func:`normalize_username`); ``disabled`` is a soft lock the CLI toggles; ``role`` is ``owner``
  or ``member`` (see :data:`ROLES`).

**Roles.** Login is the door to the building; the role is the one wall inside it. An ``owner`` sees
everything. A ``member`` sees the research surfaces (strategy lab, competition, agent desks,
personas, market, macro) but not the owner's personal ledger: ``app.auth.gate`` answers ``403`` for
a member on the tax, portfolio, import, user-admin and store-status routes. There is exactly one
invariant, held here rather than in the API: **at least one enabled owner always exists.** The first
user ever created is the owner regardless of the role asked for, a database that predates the
column promotes its earliest user, and :func:`set_role` / :func:`set_disabled` refuse (with
:class:`LastOwnerError`) any change that would leave no enabled owner -- because a locked instance is
recoverable only from a shell on the host.
- ``session`` -- one row per live login. Only the *sha256 of* the session token is stored, never
  the token itself, so a read of this table cannot be replayed as a cookie.

Every function here takes a ``Settings`` and opens its own short-lived connection. SQLite with WAL
and a busy timeout handles the handful of concurrent logins this app will ever see without a pool.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_BUSY_TIMEOUT_MS = 15_000

#: The two roles. ``owner`` is the operator whose ledger this instance serves; ``member`` is
#: everyone else. Stored as text; validated on every write by :func:`_check_role`.
ROLE_OWNER = "owner"
ROLE_MEMBER = "member"
ROLES = frozenset({ROLE_OWNER, ROLE_MEMBER})


class LastOwnerError(ValueError):
    """Raised by a write that would leave the instance with no enabled owner."""


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"role must be one of {sorted(ROLES)}, got {role!r}")
    return role


def normalize_username(username: str) -> str:
    """The canonical form a username is stored and looked up under: trimmed and lower-cased.

    Login is case- and whitespace-insensitive on the username so ``Alice`` and ``alice `` reach the
    same account; the password is neither. Applied at every write and every read, so the uniqueness
    constraint is on the normalized value and two rows cannot differ only in case.
    """
    return username.strip().lower()


@dataclass(frozen=True)
class User:
    """A row of the ``user`` table."""

    id: int
    username: str
    password_hash: str
    disabled: bool
    created_at: str
    role: str = ROLE_MEMBER

    @property
    def is_owner(self) -> bool:
        return self.role == ROLE_OWNER


@contextmanager
def _connect(settings) -> Iterator[sqlite3.Connection]:  # type: ignore[no-untyped-def]
    path: Path = settings.auth_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        yield conn
    finally:
        conn.close()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS user (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    disabled      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'member'
);
CREATE TABLE IF NOT EXISTS session (
    token_hash   TEXT    PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    created_at   TEXT    NOT NULL,
    expires_at   TEXT    NOT NULL,
    last_seen_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS session_user_idx ON session(user_id);
"""


def init_db(settings) -> None:  # type: ignore[no-untyped-def]
    """Create the tables if they do not exist, and bring an older database up to date. Safe to call
    on every startup.

    The one guarded migration: a ``user`` table created before roles existed gains the ``role``
    column, and -- since nobody in such a database is an owner yet -- its earliest-created enabled
    user is promoted. That user is whoever ran ``add-user`` first after the deploy, which is the
    operator by construction; the alternative (nobody is owner, so nobody can reach the tax page or
    the user-admin routes until a shell on the host runs ``set-role``) is exactly the lock-out the
    role invariant exists to prevent.
    """
    with _connect(settings) as conn:
        conn.executescript(_SCHEMA)
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(user)")}
        if "role" not in columns:
            conn.execute("ALTER TABLE user ADD COLUMN role TEXT NOT NULL DEFAULT 'member'")
        _ensure_an_owner(conn)


def _ensure_an_owner(conn: sqlite3.Connection) -> None:
    """Promote the earliest-created enabled user if no enabled owner exists. No-op otherwise, and a
    no-op on an empty table -- the first ``create_user`` handles that case itself."""
    owners = conn.execute(
        "SELECT COUNT(*) AS n FROM user WHERE role = ? AND disabled = 0", (ROLE_OWNER,)
    ).fetchone()["n"]
    if int(owners) > 0:
        return
    conn.execute(
        "UPDATE user SET role = ? WHERE id = "
        "(SELECT id FROM user WHERE disabled = 0 ORDER BY id LIMIT 1)",
        (ROLE_OWNER,),
    )


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


# --- users ------------------------------------------------------------------


def create_user(  # type: ignore[no-untyped-def]
    settings, username: str, password_hash: str, *, role: str = ROLE_MEMBER
) -> User:
    """Insert a new user. Raises :class:`ValueError` if the (normalized) username already exists or
    ``role`` is unknown.

    **The first user is always the owner**, whatever ``role`` says: an instance whose only account
    is a member could reach neither its own ledger nor the user-admin routes, and the CLI on the host
    would be the only way out. Every later user gets the role asked for (default ``member``).
    """
    norm = normalize_username(username)
    if not norm:
        raise ValueError("username must not be empty")
    _check_role(role)
    created = _now()
    with _connect(settings) as conn:
        existing = int(conn.execute("SELECT COUNT(*) AS n FROM user").fetchone()["n"])
        effective_role = ROLE_OWNER if existing == 0 else role
        try:
            cur = conn.execute(
                "INSERT INTO user (username, password_hash, disabled, created_at, role) "
                "VALUES (?, ?, 0, ?, ?)",
                (norm, password_hash, created, effective_role),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"user {norm!r} already exists") from exc
        user_id = int(cur.lastrowid or 0)
    return User(id=user_id, username=norm, password_hash=password_hash, disabled=False,
                created_at=created, role=effective_role)


def get_user(settings, username: str) -> User | None:  # type: ignore[no-untyped-def]
    """Look up a user by username, or ``None``. Lookup is on the normalized username."""
    norm = normalize_username(username)
    with _connect(settings) as conn:
        row = conn.execute("SELECT * FROM user WHERE username = ?", (norm,)).fetchone()
    return _row_to_user(row)


def get_user_by_id(settings, user_id: int) -> User | None:  # type: ignore[no-untyped-def]
    with _connect(settings) as conn:
        row = conn.execute("SELECT * FROM user WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(row)


def list_users(settings) -> list[User]:  # type: ignore[no-untyped-def]
    with _connect(settings) as conn:
        rows = conn.execute("SELECT * FROM user ORDER BY username").fetchall()
    return [u for u in (_row_to_user(r) for r in rows) if u is not None]


def set_password_hash(settings, username: str, password_hash: str) -> bool:  # type: ignore[no-untyped-def]
    """Replace a user's password hash. Returns ``False`` if no such user."""
    norm = normalize_username(username)
    with _connect(settings) as conn:
        cur = conn.execute(
            "UPDATE user SET password_hash = ? WHERE username = ?", (password_hash, norm)
        )
        return cur.rowcount > 0


def _would_orphan(conn: sqlite3.Connection, norm: str) -> bool:
    """Whether ``norm`` is currently the *only* enabled owner -- i.e. whether disabling or demoting
    them would leave no enabled owner."""
    row = conn.execute("SELECT role, disabled FROM user WHERE username = ?", (norm,)).fetchone()
    if row is None or str(row["role"]) != ROLE_OWNER or bool(row["disabled"]):
        return False
    others = conn.execute(
        "SELECT COUNT(*) AS n FROM user WHERE role = ? AND disabled = 0 AND username != ?",
        (ROLE_OWNER, norm),
    ).fetchone()["n"]
    return int(others) == 0


def set_disabled(settings, username: str, disabled: bool) -> bool:  # type: ignore[no-untyped-def]
    """Enable or disable a user. Disabling also revokes their live sessions. Returns ``False`` if
    no such user. Raises :class:`LastOwnerError` rather than disabling the only enabled owner."""
    norm = normalize_username(username)
    with _connect(settings) as conn:
        if disabled and _would_orphan(conn, norm):
            raise LastOwnerError(f"{norm!r} is the only enabled owner and cannot be disabled")
        cur = conn.execute(
            "UPDATE user SET disabled = ? WHERE username = ?", (1 if disabled else 0, norm)
        )
        changed = cur.rowcount > 0
        if changed and disabled:
            conn.execute(
                "DELETE FROM session WHERE user_id = (SELECT id FROM user WHERE username = ?)",
                (norm,),
            )
    return changed


def set_role(settings, username: str, role: str) -> bool:  # type: ignore[no-untyped-def]
    """Change a user's role. Returns ``False`` if no such user. Raises :class:`ValueError` for an
    unknown role and :class:`LastOwnerError` rather than demoting the only enabled owner. A role
    change does not revoke sessions: the gate reads the role from the ``user`` row on every request,
    so it takes effect on the member's next request without signing anyone out."""
    norm = normalize_username(username)
    _check_role(role)
    with _connect(settings) as conn:
        if role != ROLE_OWNER and _would_orphan(conn, norm):
            raise LastOwnerError(f"{norm!r} is the only enabled owner and cannot be demoted")
        cur = conn.execute("UPDATE user SET role = ? WHERE username = ?", (role, norm))
        return cur.rowcount > 0


def count_enabled_owners(settings) -> int:  # type: ignore[no-untyped-def]
    with _connect(settings) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM user WHERE role = ? AND disabled = 0", (ROLE_OWNER,)
        ).fetchone()
    return int(row["n"])


def _row_to_user(row: sqlite3.Row | None) -> User | None:
    if row is None:
        return None
    return User(
        id=int(row["id"]),
        username=str(row["username"]),
        password_hash=str(row["password_hash"]),
        disabled=bool(row["disabled"]),
        created_at=str(row["created_at"]),
        # `sqlite3.Row` has no `__contains__` over keys, so `in row` would test the *values*;
        # `.keys()` is the correct membership test here, hence the suppressed SIM118.
        role=str(row["role"]) if "role" in row.keys() else ROLE_MEMBER,  # noqa: SIM118
    )


# --- sessions ---------------------------------------------------------------


def create_session(  # type: ignore[no-untyped-def]
    settings, user_id: int, token_hash: str, *, expires_at: str
) -> None:
    now = _now()
    with _connect(settings) as conn:
        conn.execute(
            "INSERT INTO session (token_hash, user_id, created_at, expires_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (token_hash, user_id, now, expires_at, now),
        )


@dataclass(frozen=True)
class SessionRow:
    token_hash: str
    user_id: int
    created_at: str
    expires_at: str
    last_seen_at: str


def get_session(settings, token_hash: str) -> SessionRow | None:  # type: ignore[no-untyped-def]
    with _connect(settings) as conn:
        row = conn.execute(
            "SELECT * FROM session WHERE token_hash = ?", (token_hash,)
        ).fetchone()
    if row is None:
        return None
    return SessionRow(
        token_hash=str(row["token_hash"]),
        user_id=int(row["user_id"]),
        created_at=str(row["created_at"]),
        expires_at=str(row["expires_at"]),
        last_seen_at=str(row["last_seen_at"]),
    )


def touch_session(settings, token_hash: str, *, last_seen_at: str, expires_at: str) -> None:  # type: ignore[no-untyped-def]
    """Advance a session's idle clock on use."""
    with _connect(settings) as conn:
        conn.execute(
            "UPDATE session SET last_seen_at = ?, expires_at = ? WHERE token_hash = ?",
            (last_seen_at, expires_at, token_hash),
        )


def delete_session(settings, token_hash: str) -> None:  # type: ignore[no-untyped-def]
    with _connect(settings) as conn:
        conn.execute("DELETE FROM session WHERE token_hash = ?", (token_hash,))


def delete_sessions_for_user(settings, user_id: int, *, except_token_hash: str | None = None) -> int:  # type: ignore[no-untyped-def]
    """Revoke a user's sessions, optionally sparing one (the caller's current session). Returns the
    number deleted."""
    with _connect(settings) as conn:
        if except_token_hash is None:
            cur = conn.execute("DELETE FROM session WHERE user_id = ?", (user_id,))
        else:
            cur = conn.execute(
                "DELETE FROM session WHERE user_id = ? AND token_hash != ?",
                (user_id, except_token_hash),
            )
        return cur.rowcount


def delete_expired_sessions(settings, *, now: str | None = None) -> int:  # type: ignore[no-untyped-def]
    """Delete sessions whose absolute or idle expiry has passed. Returns the number deleted."""
    cutoff = now or _now()
    with _connect(settings) as conn:
        cur = conn.execute("DELETE FROM session WHERE expires_at <= ?", (cutoff,))
        return cur.rowcount
