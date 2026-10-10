"""User-administration endpoints for the Data / operator section (UX 2.3).

Thin HTTP wrapper over ``app.auth.store`` -- the store already holds every invariant (normalized
usernames, unique-username enforcement, session revocation on disable). This router adds nothing
past request/response shaping and status-code mapping.

**Owner-only.** ``/api/users`` is one of the prefixes ``AuthGateMiddleware`` reserves for the
``owner`` role (see ``app.auth.gate.OWNER_ONLY_PREFIXES``), so a signed-in ``member`` gets a ``403``
before any route here runs. Until the 2026-09-07 security audit any session could reach these
routes, which meant one leaked cookie could mint a permanent account or disable every other user.
The one invariant the store holds -- at least one enabled owner always exists -- surfaces here as a
``409`` with ``{"detail": "last_owner"}`` on a disable or demotion that would break it.

``password_hash`` never leaves this module -- every response is built through :func:`_to_out` or a
literal dict, neither of which touches that field.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import passwords, store
from app.config import get_settings

router = APIRouter(prefix="/api/users", tags=["users"])

Role = Literal["owner", "member"]


class UserOut(BaseModel):
    username: str
    disabled: bool
    created_at: str
    role: Role


class UsersListOut(BaseModel):
    users: list[UserOut]


class CreateUserBody(BaseModel):
    username: str
    password: str
    role: Role = "member"


class SetPasswordBody(BaseModel):
    password: str


class SetRoleBody(BaseModel):
    role: Role


class UsernameOut(BaseModel):
    username: str


class RevokeSessionsOut(BaseModel):
    revoked: int


def _to_out(user: store.User) -> UserOut:
    return UserOut(
        username=user.username,
        disabled=user.disabled,
        created_at=user.created_at,
        role="owner" if user.is_owner else "member",
    )


def _get_user_or_404(settings, username: str) -> store.User:  # type: ignore[no-untyped-def]
    norm = store.normalize_username(username)
    user = store.get_user(settings, norm)
    if user is None:
        raise HTTPException(status_code=404, detail=f"user {norm!r} not found")
    return user


@router.get("", response_model=UsersListOut)
def list_users() -> UsersListOut:
    settings = get_settings()
    return UsersListOut(users=[_to_out(u) for u in store.list_users(settings)])


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: CreateUserBody) -> UserOut:
    settings = get_settings()
    norm = store.normalize_username(body.username)
    if not norm:
        raise HTTPException(status_code=422, detail="username must not be empty")

    try:
        passwords.validate_length(body.password)
    except passwords.WeakPasswordError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    password_hash = passwords.hash_password(body.password)
    try:
        user = store.create_user(settings, norm, password_hash, role=body.role)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"user {norm!r} already exists") from exc
    return _to_out(user)


@router.post("/{username}/role", response_model=UserOut)
def set_role(username: str, body: SetRoleBody) -> UserOut:
    """Promote or demote a user. ``409 last_owner`` rather than demoting the only enabled owner."""
    settings = get_settings()
    user = _get_user_or_404(settings, username)
    try:
        store.set_role(settings, user.username, body.role)
    except store.LastOwnerError as exc:
        raise HTTPException(status_code=409, detail="last_owner") from exc
    return _to_out(_get_user_or_404(settings, user.username))


@router.post("/{username}/password", response_model=UsernameOut)
def set_password(username: str, body: SetPasswordBody) -> UsernameOut:
    """Reset another user's password, and revoke every session that user holds.

    The revocation is the point of the route as much as the new hash is: an owner resetting a
    password is almost always responding to a lost or shared credential, and leaving the old
    sessions alive would mean whoever held that credential keeps their access until the cookie
    ages out. No ``except_token_hash`` here, unlike the self-service
    ``POST /api/auth/password`` -- that route spares the caller's own session because the caller is
    the account holder; here the caller is an administrator and the account holder is someone else,
    so there is no session of theirs worth sparing.
    """
    settings = get_settings()
    user = _get_user_or_404(settings, username)

    try:
        passwords.validate_length(body.password)
    except passwords.WeakPasswordError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    password_hash = passwords.hash_password(body.password)
    store.set_password_hash(settings, user.username, password_hash)
    store.delete_sessions_for_user(settings, user.id)
    return UsernameOut(username=user.username)


@router.post("/{username}/disable", response_model=UserOut)
def disable_user(username: str) -> UserOut:
    settings = get_settings()
    user = _get_user_or_404(settings, username)
    try:
        store.set_disabled(settings, user.username, True)
    except store.LastOwnerError as exc:
        raise HTTPException(status_code=409, detail="last_owner") from exc
    return _to_out(_get_user_or_404(settings, user.username))


@router.post("/{username}/enable", response_model=UserOut)
def enable_user(username: str) -> UserOut:
    settings = get_settings()
    user = _get_user_or_404(settings, username)
    store.set_disabled(settings, user.username, False)
    return _to_out(_get_user_or_404(settings, user.username))


@router.post("/{username}/revoke-sessions", response_model=RevokeSessionsOut)
def revoke_sessions(username: str) -> RevokeSessionsOut:
    settings = get_settings()
    user = _get_user_or_404(settings, username)
    revoked = store.delete_sessions_for_user(settings, user.id)
    return RevokeSessionsOut(revoked=revoked)
