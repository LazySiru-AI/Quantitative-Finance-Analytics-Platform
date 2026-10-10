"""Session tokens, their cookie, and the login/validate/revoke lifecycle.

A session is an opaque random token handed to the browser in an ``HttpOnly`` cookie. The server
stores only ``sha256(token)`` (see :mod:`app.auth.store`), so the token behaves like a bearer
credential the database never actually holds -- a leak of the ``session`` table cannot be replayed.

Two expiries, both enforced here:

- **idle**: a session dies ``auth_session_idle_days`` after it was last used. Every validated
  request advances it, so an active user is never logged out mid-session.
- **absolute**: a session dies ``auth_session_max_days`` after it was created, no matter how active.
  The stored ``expires_at`` is always ``min(now + idle, created + absolute)``, so the absolute cap
  wins as the idle window approaches it, and a stolen token is useless after at most the absolute
  window regardless of use.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets

from app.auth import store

#: Name of the session cookie. ``invdash_`` prefix so it is recognizable beside the app's other
#: browser storage, and distinct from the ``VITE_``/``INVDASH_`` env conventions.
COOKIE_NAME = "invdash_session"

#: Raw token length in bytes before hex-encoding. 32 bytes = 256 bits of entropy, far past guessable.
_TOKEN_BYTES = 32


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def hash_token(raw_token: str) -> str:
    """The sha256 hex of a raw token -- the form stored and looked up in the database."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _mint_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def _expiry(settings, created: dt.datetime, *, seen: dt.datetime) -> str:  # type: ignore[no-untyped-def]
    idle_deadline = seen + dt.timedelta(days=settings.auth_session_idle_days)
    absolute_deadline = created + dt.timedelta(days=settings.auth_session_max_days)
    return min(idle_deadline, absolute_deadline).isoformat()


def start_session(settings, user: store.User) -> str:  # type: ignore[no-untyped-def]
    """Create a session for a user and return the *raw* token to set as a cookie.

    The raw token is returned exactly once, here; it is never stored and cannot be recovered from
    the database afterwards.
    """
    raw = _mint_token()
    now = _now()
    store.create_session(
        settings, user.id, hash_token(raw), expires_at=_expiry(settings, now, seen=now)
    )
    return raw


def validate(settings, raw_token: str) -> store.User | None:  # type: ignore[no-untyped-def]
    """Resolve a raw cookie token to a live, enabled user, or ``None``.

    Expired sessions and sessions whose user has since been disabled or deleted are removed as they
    are encountered, so a rejected request also cleans up the row that rejected it. A valid session
    has its idle clock advanced (bounded by the absolute cap) as a side effect.
    """
    if not raw_token:
        return None
    token_hash = hash_token(raw_token)
    row = store.get_session(settings, token_hash)
    if row is None:
        return None

    now = _now()
    try:
        expires_at = dt.datetime.fromisoformat(row.expires_at)
    except ValueError:
        store.delete_session(settings, token_hash)
        return None
    if expires_at <= now:
        store.delete_session(settings, token_hash)
        return None

    user = store.get_user_by_id(settings, row.user_id)
    if user is None or user.disabled:
        store.delete_session(settings, token_hash)
        return None

    try:
        created = dt.datetime.fromisoformat(row.created_at)
    except ValueError:
        created = now
    store.touch_session(
        settings, token_hash, last_seen_at=now.isoformat(),
        expires_at=_expiry(settings, created, seen=now),
    )
    return user


def end_session(settings, raw_token: str) -> None:  # type: ignore[no-untyped-def]
    """Revoke a single session by its raw token. A no-op for an unknown or empty token."""
    if raw_token:
        store.delete_session(settings, hash_token(raw_token))
