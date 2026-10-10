"""Password hashing and verification.

Uses the standard library's :func:`hashlib.scrypt` -- no third-party dependency. ``scrypt`` is
deliberately memory-hard, which is what makes an offline guess of one of these ten passwords
expensive even if the auth database leaks. bcrypt/argon2 would be defensible too; scrypt wins here
only because it is already in the stdlib and this app's ``backend/Dockerfile`` installs with a bare
``pip install .`` where an optional dependency would silently not be there.

**Encoded form:** ``scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>``. The parameters travel *with* the
hash rather than being read from a constant at verify time, so raising the cost later does not
strand every password stored under the old cost -- an old hash still verifies against the ``n``/``r``
/``p`` baked into its own string, and :func:`needs_rehash` reports which ones a successful login
should quietly upgrade.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

#: scrypt cost parameters for new hashes. n must be a power of two. n=2**14, r=8, p=1 needs about
#: ``128 * r * n`` = 16 MiB of memory per hash -- comfortably fast for an interactive login on the
#: host this runs on, expensive at scale for an attacker. ``maxmem`` is set on the call below with
#: headroom over that figure, because ``hashlib.scrypt`` raises rather than allocating past it.
_N = 2**14
_R = 8
_P = 1
_DKLEN = 32
_SALT_BYTES = 16
#: 64 MiB: four times the ~16 MiB one hash needs, so a future bump to _N up to 2**15 still fits
#: without editing this, while still bounding a maliciously crafted stored hash's memory use.
_MAXMEM = 64 * 1024 * 1024

#: The shortest password this app accepts. Length is the whole policy -- no character-class rules
#: that only push people toward ``Password1!``. Set to 4 at the owner's explicit request for this
#: private LAN instance; it is the single floor the login route and the CLI both enforce (see
#: :func:`validate_length`). Raise it if the instance is ever exposed more widely.
MIN_PASSWORD_LENGTH = 4


class WeakPasswordError(ValueError):
    """Raised when a proposed password is shorter than :data:`MIN_PASSWORD_LENGTH`."""


def validate_length(password: str) -> None:
    """Raise :class:`WeakPasswordError` if ``password`` is too short. The only password rule."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters, got {len(password)}"
        )


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text.encode("ascii"))


def _derive(password: str, *, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=_DKLEN, maxmem=_MAXMEM
    )


def hash_password(password: str) -> str:
    """Validate, salt and hash a password into the encoded form. Raises on a too-short password."""
    validate_length(password)
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = _derive(password, salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(derived)}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check of ``password`` against a stored encoded hash.

    Returns ``False`` -- never raises -- for a malformed or unknown-scheme stored value, so a
    corrupted row in the auth database reads as "wrong password" rather than a 500 that reveals the
    row exists. The digest comparison itself goes through :func:`hmac.compare_digest` so a caller
    cannot learn the correct prefix from response timing.
    """
    try:
        scheme, n_s, r_s, p_s, salt_s, hash_s = encoded.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(hash_s)
        derived = _derive(password, salt=_unb64(salt_s), n=int(n_s), r=int(r_s), p=int(p_s))
    except (ValueError, KeyError):
        return False
    return hmac.compare_digest(derived, expected)


def needs_rehash(encoded: str) -> bool:
    """Whether a stored hash uses parameters weaker than the current baseline.

    A login that both verifies and returns ``True`` here should re-hash the password with
    :func:`hash_password` and store it, so cost quietly rises over time without forcing a reset.
    A value this module cannot parse is reported as needing a rehash -- the safe direction.
    """
    try:
        scheme, n_s, r_s, p_s, _salt, _hash = encoded.split("$")
    except ValueError:
        return True
    if scheme != "scrypt":
        return True
    return (int(n_s), int(r_s), int(p_s)) != (_N, _R, _P)
