"""Unit tests for the auth password, store and session layers -- no HTTP, no app."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app.auth import passwords, sessions, store
from app.config import Settings


@pytest.fixture
def auth_settings(tmp_path: Path) -> Settings:
    """A Settings whose auth database lives under tmp. `_detach_dotenv` (conftest, session-scoped
    autouse) already cut `.env` out, so this constructs cleanly."""
    settings = Settings(data_dir=tmp_path / "data")
    store.init_db(settings)
    return settings


# --- passwords --------------------------------------------------------------


def test_hash_verify_roundtrip() -> None:
    encoded = passwords.hash_password("correct-horse-staple")
    assert passwords.verify_password("correct-horse-staple", encoded)
    assert not passwords.verify_password("wrong-horse-staple", encoded)


def test_hash_is_salted() -> None:
    a = passwords.hash_password("correct-horse-staple")
    b = passwords.hash_password("correct-horse-staple")
    assert a != b  # different salt each time
    assert passwords.verify_password("correct-horse-staple", a)
    assert passwords.verify_password("correct-horse-staple", b)


def test_short_password_rejected() -> None:
    with pytest.raises(passwords.WeakPasswordError):
        passwords.hash_password("ab")  # under MIN_PASSWORD_LENGTH (4)


def test_verify_never_raises_on_garbage() -> None:
    assert not passwords.verify_password("anything", "not-a-valid-encoded-hash")
    assert not passwords.verify_password("anything", "bcrypt$stuff")
    assert not passwords.verify_password("anything", "")


def test_needs_rehash() -> None:
    encoded = passwords.hash_password("correct-horse-staple")
    assert not passwords.needs_rehash(encoded)
    assert passwords.needs_rehash("scrypt$1024$8$1$c2FsdA==$aGFzaA==")  # weaker n
    assert passwords.needs_rehash("garbage")


# --- user store -------------------------------------------------------------


def test_create_and_get_user(auth_settings: Settings) -> None:
    user = store.create_user(auth_settings, "Alice", passwords.hash_password("correct-horse-staple"))
    assert user.username == "alice"  # normalized
    fetched = store.get_user(auth_settings, "  ALICE ")  # case- and space-insensitive
    assert fetched is not None
    assert fetched.id == user.id


def test_duplicate_username_rejected(auth_settings: Settings) -> None:
    store.create_user(auth_settings, "alice", passwords.hash_password("correct-horse-staple"))
    with pytest.raises(ValueError):
        store.create_user(auth_settings, "ALICE", passwords.hash_password("another-password-x"))


def test_set_password_and_disable(auth_settings: Settings) -> None:
    # `root` is created first and is therefore the owner; `alice` is a member and can be disabled.
    store.create_user(auth_settings, "root", passwords.hash_password("correct-horse-staple"))
    store.create_user(auth_settings, "alice", passwords.hash_password("correct-horse-staple"))
    assert store.set_password_hash(auth_settings, "alice", passwords.hash_password("new-password-xy"))
    user = store.get_user(auth_settings, "alice")
    assert user is not None and passwords.verify_password("new-password-xy", user.password_hash)
    assert store.set_disabled(auth_settings, "alice", True)
    assert (store.get_user(auth_settings, "alice") or user).disabled
    assert not store.set_disabled(auth_settings, "nobody", True)


def test_disable_revokes_sessions(auth_settings: Settings) -> None:
    store.create_user(auth_settings, "root", passwords.hash_password("correct-horse-staple"))
    user = store.create_user(auth_settings, "alice", passwords.hash_password("correct-horse-staple"))
    sessions.start_session(auth_settings, user)
    store.set_disabled(auth_settings, "alice", True)
    # No sessions remain for the disabled user.
    assert store.delete_sessions_for_user(auth_settings, user.id) == 0


# --- roles ------------------------------------------------------------------


def test_first_user_is_owner_regardless_of_requested_role(auth_settings: Settings) -> None:
    first = store.create_user(
        auth_settings, "alice", passwords.hash_password("correct-horse-staple"), role="member"
    )
    assert first.role == store.ROLE_OWNER and first.is_owner
    second = store.create_user(auth_settings, "bob", passwords.hash_password("correct-horse-staple"))
    assert second.role == store.ROLE_MEMBER and not second.is_owner
    # The role survives a round trip through the database, not just the returned dataclass.
    assert (store.get_user(auth_settings, "alice") or first).is_owner
    assert not (store.get_user(auth_settings, "bob") or second).is_owner
    assert store.count_enabled_owners(auth_settings) == 1


def test_create_user_rejects_unknown_role(auth_settings: Settings) -> None:
    with pytest.raises(ValueError):
        store.create_user(auth_settings, "alice", passwords.hash_password("correct-horse-staple"),
                          role="admin")


def test_set_role_promotes_and_demotes(auth_settings: Settings) -> None:
    store.create_user(auth_settings, "alice", passwords.hash_password("correct-horse-staple"))
    store.create_user(auth_settings, "bob", passwords.hash_password("correct-horse-staple"))
    assert store.set_role(auth_settings, "bob", store.ROLE_OWNER)
    assert store.count_enabled_owners(auth_settings) == 2
    # With two owners, alice may step down.
    assert store.set_role(auth_settings, "alice", store.ROLE_MEMBER)
    assert not (store.get_user(auth_settings, "alice") or first_or_fail()).is_owner
    assert not store.set_role(auth_settings, "nobody", store.ROLE_OWNER)
    with pytest.raises(ValueError):
        store.set_role(auth_settings, "bob", "admin")


def first_or_fail() -> store.User:  # pragma: no cover - only reached if get_user returned None
    raise AssertionError("expected the user to exist")


def test_last_owner_cannot_be_demoted_or_disabled(auth_settings: Settings) -> None:
    store.create_user(auth_settings, "alice", passwords.hash_password("correct-horse-staple"))
    store.create_user(auth_settings, "bob", passwords.hash_password("correct-horse-staple"))
    with pytest.raises(store.LastOwnerError):
        store.set_role(auth_settings, "alice", store.ROLE_MEMBER)
    with pytest.raises(store.LastOwnerError):
        store.set_disabled(auth_settings, "alice", True)
    # Nothing changed: alice is still the enabled owner.
    alice = store.get_user(auth_settings, "alice")
    assert alice is not None and alice.is_owner and not alice.disabled
    # A second owner who is *disabled* does not count as cover.
    store.set_role(auth_settings, "bob", store.ROLE_OWNER)
    store.set_disabled(auth_settings, "bob", True)
    with pytest.raises(store.LastOwnerError):
        store.set_role(auth_settings, "alice", store.ROLE_MEMBER)


def test_init_db_migrates_a_pre_role_database(tmp_path: Path) -> None:
    """A `user` table created before the `role` column existed gains it, and its earliest enabled
    user becomes the owner -- so an upgraded instance is never left with nobody able to reach the
    ledger or the user-admin routes."""
    import sqlite3

    settings = Settings(data_dir=tmp_path / "data")
    settings.auth_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.auth_db_path)
    conn.executescript(
        """
        CREATE TABLE user (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        INSERT INTO user (username, password_hash, disabled, created_at)
            VALUES ('gone', 'x', 1, '2026-01-01'), ('owner', 'x', 0, '2026-01-02'),
                   ('later', 'x', 0, '2026-01-03');
        """
    )
    conn.close()

    store.init_db(settings)

    by_name = {u.username: u for u in store.list_users(settings)}
    assert by_name["owner"].is_owner  # earliest *enabled* user, not the disabled one before it
    assert not by_name["gone"].is_owner
    assert not by_name["later"].is_owner
    # Idempotent: a second init neither errors nor adds a second owner.
    store.init_db(settings)
    assert store.count_enabled_owners(settings) == 1


# --- sessions ---------------------------------------------------------------


def test_session_validate_roundtrip(auth_settings: Settings) -> None:
    user = store.create_user(auth_settings, "alice", passwords.hash_password("correct-horse-staple"))
    token = sessions.start_session(auth_settings, user)
    resolved = sessions.validate(auth_settings, token)
    assert resolved is not None and resolved.username == "alice"


def test_session_stores_only_the_hash(auth_settings: Settings) -> None:
    user = store.create_user(auth_settings, "alice", passwords.hash_password("correct-horse-staple"))
    token = sessions.start_session(auth_settings, user)
    row = store.get_session(auth_settings, sessions.hash_token(token))
    assert row is not None
    assert row.token_hash != token  # the raw token is nowhere in the row
    assert row.token_hash == sessions.hash_token(token)


def test_expired_session_rejected_and_cleaned(auth_settings: Settings) -> None:
    user = store.create_user(auth_settings, "alice", passwords.hash_password("correct-horse-staple"))
    token = sessions.start_session(auth_settings, user)
    token_hash = sessions.hash_token(token)
    past = (dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)).isoformat()
    store.touch_session(auth_settings, token_hash, last_seen_at=past, expires_at=past)
    assert sessions.validate(auth_settings, token) is None
    assert store.get_session(auth_settings, token_hash) is None  # cleaned on the way out


def test_end_session(auth_settings: Settings) -> None:
    user = store.create_user(auth_settings, "alice", passwords.hash_password("correct-horse-staple"))
    token = sessions.start_session(auth_settings, user)
    sessions.end_session(auth_settings, token)
    assert sessions.validate(auth_settings, token) is None
    sessions.end_session(auth_settings, "")  # no-op, does not raise


def test_absolute_cap_bounds_idle_extension(auth_settings: Settings) -> None:
    settings = Settings(data_dir=auth_settings.data_dir, auth_session_idle_days=14,
                        auth_session_max_days=30)
    user = store.create_user(settings, "bob", passwords.hash_password("correct-horse-staple"))
    token = sessions.start_session(settings, user)
    row = store.get_session(settings, sessions.hash_token(token))
    assert row is not None
    created = dt.datetime.fromisoformat(row.created_at)
    expires = dt.datetime.fromisoformat(row.expires_at)
    # Fresh session: idle deadline (created+14d) is nearer than absolute (created+30d).
    assert expires == created + dt.timedelta(days=14)
