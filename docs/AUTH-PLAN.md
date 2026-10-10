# Login plan: one shared instance, about ten named users

Status: DESIGN ONLY (2026-09-05). Nothing here is built. Execute only when the owner says so.

## Decision

One instance, one login screen, one set of named users (owner + colleagues + UAT testers).
No separate UAT server. Login gates *access*; it does not partition data -- every signed-in user
sees the same ledger, tax forms and paper desks. (The owner accepted this in choosing not to
split the UAT server; it is stated here so nobody later assumes per-user isolation exists.)

Deliberately out of scope: roles/admin UI, self-registration, e-mail password reset, TOTP,
OAuth, per-user data. The owner manages users from a CLI.

## Backend

New package `backend/app/auth/`, no new dependencies (stdlib `hashlib.scrypt`, `secrets`, `hmac`).

| Module | Responsibility |
|---|---|
| `store.py` | SQLite file at `Settings.auth_db_path` (default `data_dir/auth.sqlite`, separate from the ledger so `SCHEMA_VERSION` is untouched). Tables `user(id, username UNIQUE, password_hash, disabled, created_at)` and `session(token_hash, user_id, created_at, expires_at, last_seen_at)`. |
| `passwords.py` | `scrypt` (n=2^14, r=8, p=1, 16-byte salt) encoded `scrypt$n$r$p$salt$hash`; `verify` via `hmac.compare_digest`. Min length 4 (lowered from 10 at owner request), no other rules. |
| `sessions.py` | Opaque 32-byte token, stored as sha256; cookie `invdash_session`, HttpOnly, SameSite=Lax, Path=/, `Secure` only if `auth_cookie_secure`. Idle expiry 14 d, absolute 30 d. |
| `gate.py` | **Raw ASGI middleware** (not `BaseHTTPMiddleware`, which breaks the paperlive SSE stream). When `auth_enabled`, every path except the allowlist needs a valid session, else `401 {"detail":"not_authenticated"}`. Allowlist: `/api/health` (exact; Docker healthcheck), `/api/auth/login`, `/api/auth/logout`, `/api/auth/me`. `/docs` and `/openapi.json` are gated. |
| `throttle.py` | In-memory failed-login counter per username and per client IP: 5 failures in 15 min locks that key for 15 min. |
| `cli.py` | `python -m app.auth.cli add-user NAME` (password via getpass or `--password-stdin`), `set-password`, `disable`, `enable`, `list`, `revoke-sessions NAME`. Run from repo root with the venv, same as uvicorn. |

`app/api/auth.py` router, prefix `/api/auth` -- the contract both sides build against:

| Route | Body | 200 | Errors |
|---|---|---|---|
| `POST /login` | `{"username": str, "password": str}` | `{"username": str}` + Set-Cookie | 401 `{"detail":"invalid_credentials"}` (same for unknown user), 429 `{"detail":"locked","retry_after_seconds":int}` |
| `POST /logout` | none | `{"ok": true}` + cookie cleared | never fails |
| `GET /me` | none | `{"auth_enabled": bool, "authenticated": bool, "username": str or null}` | never 401 (it is how the UI decides what to show) |
| `POST /password` | `{"current": str, "new": str}` | `{"ok": true}`; revokes the user's *other* sessions | 401 wrong current, 422 too short |

Login and `/me` responses carry `Cache-Control: no-store`. Successes and failures are logged with
username and client IP, never the password.

`Settings` additions (all `INVDASH_` prefixed): `auth_enabled: bool = True`,
`auth_db_path: Path = data_dir/auth.sqlite`, `auth_cookie_secure: bool = False`,
`auth_session_idle_days: int = 14`, `auth_session_max_days: int = 30`.

CSRF: SameSite=Lax cookie (not sent on cross-site POST), JSON-only bodies, CORS keeps
`allow_credentials=False`. Adequate for ten known users on a LAN.

Untouched by design: `app.mcp.server` and the UAT harness call the engines in-process, not over
HTTP, so the gate does not affect them.

## Frontend

| File | Change |
|---|---|
| `src/api/auth.ts` | `login`, `logout`, `me`, `changePassword` over the existing `request()` helper; types mirror the table above. |
| `src/api/client.ts` | `request()` fires a `window` event `invdash:unauthenticated` on any 401 before throwing, so one expired session flips the UI without a reload. |
| `src/auth.tsx` | `AuthProvider` + `useAuth()`: calls `/me` on mount; states loading / anonymous / signed-in; `auth_enabled=false` counts as signed-in. Listens for the 401 event. |
| `src/pages/Login.tsx` | Full-screen form (username, password, submit), generic error text, lockout message with countdown, `LanguageToggle` present. |
| `src/pages/Account.tsx` | Route `/account` (not in `NAV`): change password, sign out. |
| `src/App.tsx` | Wrap in `AuthProvider`; anonymous renders `<Login/>` and nothing else; signed-in renders the current tree unchanged. Sidebar gets a footer: username, links to `/account`, sign out. |
| `src/i18n/messages/auth.ts` | New shard, en + ko, registered in the catalog (tsc enforces completeness). |
| Tests | `Login.test.tsx`, `auth.test.tsx` (401 event flips to login); `App.test.tsx` gets a signed-in auth stub so the nav tests stay green. |

Nginx and the Vite proxy already forward cookies; no infra change. `EventSource` (paperlive)
sends same-origin cookies automatically.

## Tests and gates

- `tests/conftest.py`: the session-scoped autouse fixture also sets `INVDASH_AUTH_ENABLED=0`, so
  the ~35 files that build `TestClient(app)` from `app.main` keep passing unchanged.
- New: `tests/test_auth_store.py`, `tests/test_auth_api.py` (login ok/bad/locked, gate 401 vs 200
  on `/api/portfolio`, allowlist, logout revokes, password change revokes other sessions, disabled
  user, cookie flags), `tests/test_auth_gate_streaming.py` (SSE still streams through the gate).
- Gates before commit: pytest via the repo venv, ruff, mypy from `backend/`, `tsc`, vitest.
- Browser verification on the real app: login, open Overview and Paper Desk, sign out, confirm a
  direct `/api/portfolio` fetch returns 401.

## Ops

- `.env.example`: document the five settings. `docs/AUTH.md`: add-user walkthrough, note that
  anything beyond the LAN needs HTTPS in front (Caddy or Tailscale) with
  `INVDASH_AUTH_COOKIE_SECURE=1`, and that `INVDASH_AUTH_ENABLED=0` is the local-dev escape hatch.
- Docker backend: `auth.sqlite` lives on the `/data` volume, so users persist across rebuilds.
- First run after deploy: `add-user` for the owner before anyone can sign in (auth on + zero
  users = locked, by design).

## Execution order (four phases, each committed with its gates green)

1. `app/auth/` package + `Settings` fields + CLI + store/password tests.
2. `api/auth.py` + gate middleware + `main.py` wiring + conftest switch + API and SSE tests.
3. Frontend (api, provider, Login, Account, sidebar footer, i18n shard, tests). Can run in
   parallel with phase 2 because the contract table above is pinned.
4. Docs, `.env.example`, create the owner's user, browser verification.
