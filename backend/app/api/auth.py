"""Authentication endpoints: login, logout, who-am-I, and change-password.

The contract these four routes present is what ``frontend/src/api/auth.ts`` is written against; the
two sides were built in parallel from the table in ``docs/AUTH-PLAN.md``, so the field names and
status codes here are load-bearing, not incidental.

**Why login and unknown-user both answer 401 ``invalid_credentials``.** A distinct "no such user"
response would let anyone enumerate which of the ~ten usernames exist. The *body* was always
identical; until the 2026-09-07 security audit the *timing* was not, because the check
short-circuited before ``verify_password`` for an unknown or disabled account and so answered in
under a millisecond where a real account cost a full scrypt derivation. :data:`_DECOY_HASH` closes
that: an unknown or disabled username still pays for one verification, against a hash of a password
nobody holds, so the two paths cost the same and the throttle is not the only thing standing between
an attacker and a user list.

CSRF is handled by the cookie's ``SameSite=Lax`` (a cross-site POST does not carry it) together with
JSON-only request bodies and ``allow_credentials=False`` on CORS; adequate for ten known users on a
LAN, and ``docs/AUTH.md`` records the HTTPS-in-front requirement for anything wider.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.auth import passwords, sessions, store
from app.auth.throttle import THROTTLE
from app.config import get_settings

logger = logging.getLogger("app.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: A real, correctly-formed scrypt hash of a password no account has, derived once at import with the
#: same parameters :func:`passwords.hash_password` uses for a live account. Its only job is to give
#: :func:`login` something to verify against when there is no user to verify against, so an unknown
#: or disabled username costs the same wall-clock time as a real one. Never compared to anything a
#: caller could match: ``verify_password`` against it returns ``True`` only for the literal string
#: below, and that string is never accepted as a credential because the branch that uses it always
#: returns 401 regardless of the result.
_DECOY_HASH = passwords.hash_password("decoy-not-a-real-password")  # pragma: allowlist secret


class LoginBody(BaseModel):
    username: str
    password: str


class LoginResult(BaseModel):
    username: str


class MeResult(BaseModel):
    auth_enabled: bool
    authenticated: bool
    username: str | None
    #: ``"owner"`` or ``"member"`` for a signed-in caller; ``None`` when anonymous. Reported as
    #: ``"owner"`` when auth is off, because the gate then lets every request through and the UI
    #: should render every section. See ``app.auth.store`` for what the two roles may reach.
    role: str | None


class PasswordBody(BaseModel):
    current: str
    new: str = Field(min_length=1)


class OkResult(BaseModel):
    ok: bool


def _client_ip(request: Request) -> str:
    """Best-effort client IP for throttle keying.

    Reads ``X-Forwarded-For``'s **last** hop, and only when ``Settings.auth_trust_forwarded_for``
    says this deployment's front door is the app's own nginx (see ``frontend/Dockerfile``) -- the one
    supported topology where this process sits directly behind it. Off by default: the header is
    client-supplied unless something in front of this process appends to it, and trusting it
    unconditionally would let a caller spoof the throttle bucket a login attempt is keyed against --
    either to dodge their own lockout, or to lock out an innocent address by forging it.

    **The last hop, not the first.** ``frontend/Dockerfile``'s proxy config sets
    ``X-Forwarded-For: $proxy_add_x_forwarded_for``, which *appends* nginx's own view of the caller
    to whatever the client already sent -- it does not overwrite the header. A caller can still send
    an ``X-Forwarded-For`` of its own; nginx's append means that value survives as every hop *except*
    the last one. Trusting exactly one hop (this deployment's own nginx, the only thing that reaches
    this process) means trusting the one entry that hop itself is responsible for, which is the
    rightmost -- reading the leftmost instead would take the attacker-supplied value straight back
    out of the header nginx was supposed to have corrected.

    Falls back to the socket peer either way. Used only to bucket failed logins, never for
    authorization, so a spoofed value can at worst lock out the spoofer (when trusted) or do nothing
    (when not)."""
    if get_settings().auth_trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _set_session_cookie(response: Response, raw_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=sessions.COOKIE_NAME,
        value=raw_token,
        httponly=True,
        samesite="lax",
        secure=settings.auth_cookie_secure,
        path="/",
        # The browser keeps the cookie for the absolute session lifetime; the server still enforces
        # the real (idle-and-absolute) expiry on every request, so this is an upper bound, not the
        # authority. A shorter value would just make the browser drop a cookie the server still
        # considers valid.
        max_age=settings.auth_session_max_days * 86_400,
    )


@router.post("/login", response_model=LoginResult)
def login(body: LoginBody, request: Request, response: Response) -> LoginResult | Response:
    _no_store(response)
    settings = get_settings()
    norm = store.normalize_username(body.username)
    ip = _client_ip(request)
    keys = [f"user:{norm}", f"ip:{ip}"]

    retry_after = THROTTLE.retry_after(keys)
    if retry_after > 0:
        logger.warning("login locked for user=%s ip=%s retry_after=%ss", norm, ip, retry_after)
        response.status_code = 429
        return _json(response, {"detail": "locked", "retry_after_seconds": retry_after})

    user = store.get_user(settings, norm)
    # One scrypt derivation happens on every path through this branch -- against the real account's
    # hash when there is one, against `_DECOY_HASH` when the username is unknown or the account is
    # disabled. Writing it as `user is not None and ... and verify_password(...)` short-circuits, and
    # a short-circuit here is exactly the timing oracle this route must not have.
    if user is None or user.disabled:
        passwords.verify_password(body.password, _DECOY_HASH)
        ok = False
    else:
        ok = passwords.verify_password(body.password, user.password_hash)
    if not ok or user is None:
        THROTTLE.record_failure(keys)
        logger.warning("failed login for user=%s ip=%s", norm, ip)
        response.status_code = 401
        return _json(response, {"detail": "invalid_credentials"})

    # Success: clear the username's failure counter (leave the IP's to age out on its own, so it
    # still reflects other accounts probed from the same address), quietly upgrade an old hash, and
    # mint the session.
    THROTTLE.clear([f"user:{norm}"])
    if passwords.needs_rehash(user.password_hash):
        store.set_password_hash(settings, user.username, passwords.hash_password(body.password))
    raw_token = sessions.start_session(settings, user)
    _set_session_cookie(response, raw_token)
    logger.info("login for user=%s ip=%s", user.username, ip)
    return LoginResult(username=user.username)


@router.post("/logout", response_model=OkResult)
def logout(request: Request, response: Response) -> OkResult:
    _no_store(response)
    settings = get_settings()
    raw_token = request.cookies.get(sessions.COOKIE_NAME, "")
    sessions.end_session(settings, raw_token)
    response.delete_cookie(key=sessions.COOKIE_NAME, path="/")
    return OkResult(ok=True)


@router.get("/me", response_model=MeResult)
def me(request: Request, response: Response) -> MeResult:
    """Who the caller is, and whether auth is even on. Never 401 -- this is how the UI decides what
    to render, so it must answer for an anonymous caller too."""
    _no_store(response)
    settings = get_settings()
    if not settings.auth_enabled:
        return MeResult(
            auth_enabled=False, authenticated=False, username=None, role=store.ROLE_OWNER
        )
    raw_token = request.cookies.get(sessions.COOKIE_NAME, "")
    user = sessions.validate(settings, raw_token)
    if user is None:
        return MeResult(auth_enabled=True, authenticated=False, username=None, role=None)
    return MeResult(
        auth_enabled=True, authenticated=True, username=user.username, role=user.role
    )


@router.post("/password", response_model=OkResult)
def change_password(body: PasswordBody, request: Request, response: Response) -> OkResult | Response:
    """Change the signed-in user's own password. Gated -- reachable only with a valid session, since
    it is not on the middleware allowlist. Revokes the user's *other* sessions on success so a change
    prompted by a suspected leak actually evicts the other holder."""
    _no_store(response)
    settings = get_settings()
    raw_token = request.cookies.get(sessions.COOKIE_NAME, "")
    user = sessions.validate(settings, raw_token)
    if user is None:
        response.status_code = 401
        return _json(response, {"detail": "not_authenticated"})

    if not passwords.verify_password(body.current, user.password_hash):
        response.status_code = 401
        return _json(response, {"detail": "invalid_credentials"})

    try:
        passwords.validate_length(body.new)
    except passwords.WeakPasswordError as exc:
        response.status_code = 422
        return _json(response, {"detail": str(exc)})

    store.set_password_hash(settings, user.username, passwords.hash_password(body.new))
    store.delete_sessions_for_user(settings, user.id, except_token_hash=sessions.hash_token(raw_token))
    logger.info("password changed for user=%s", user.username)
    return OkResult(ok=True)


def _json(response: Response, payload: dict[str, object]) -> Response:
    """Return a JSON body while preserving the status code and cookies already set on ``response``.

    FastAPI serialises a returned ``Response`` as-is, so building a fresh ``JSONResponse`` would drop
    the ``Set-Cookie`` and ``Cache-Control`` headers set above. Copying them across keeps one code
    path for both the success and error returns."""
    from fastapi.responses import JSONResponse

    out = JSONResponse(payload, status_code=response.status_code)
    for key, value in response.headers.items():
        if key.lower() in {"cache-control", "set-cookie"}:
            out.headers[key] = value
    return out
