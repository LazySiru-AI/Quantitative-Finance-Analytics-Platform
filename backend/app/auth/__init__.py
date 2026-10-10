"""Authentication for the dashboard: named users, password login, server-side sessions.

This package gates *access* to the whole application; it does not partition *data*. Every
signed-in user sees the same ledger, tax forms and paper desks -- there is exactly one book, and
login is the door to the building, not a wall between rooms. That is the deliberate consequence of
running one instance for the roughly ten expected users (the owner, a few colleagues, and the UAT
personas) rather than standing up a separate UAT server; see ``docs/AUTH-PLAN.md``.

The pieces, and why each is its own module:

- ``passwords``  -- hashing and verification (stdlib ``scrypt``), the one place that knows the
  encoded-hash format.
- ``store``      -- the users/sessions SQLite database, in its *own* file separate from the
  ledger so the ledger's schema version is never touched by an auth change.
- ``sessions``   -- opaque token minting, cookie shape, and the create/validate/revoke lifecycle.
- ``throttle``   -- an in-process failed-login limiter, per username and per client IP.
- ``gate``       -- the raw-ASGI middleware that requires a session on every non-allowlisted path.
- ``cli``        -- ``python -m app.auth.cli`` for the owner to add and manage users.

Nothing here is imported by ``app.mcp`` or the UAT harness: those call the engines in-process, not
over HTTP, so the gate never sees them.
"""

from __future__ import annotations
