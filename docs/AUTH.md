# Authentication

One shared instance, a login screen, and a handful of named users. This is deliberately small: the
expected population is the owner, a few colleagues, and the UAT personas -- roughly ten people. See
[`AUTH-PLAN.md`](AUTH-PLAN.md) for the design and the reasoning behind each choice.

**Login gates access, not data.** Every signed-in user sees the same ledger, tax forms and paper
desks. There is one book, and login is the door to the building rather than a wall between rooms.

## Managing users

Users are created and managed from the command line, run from the repository root with the project
venv (the same way the server is started -- see [`DOCKER.md`](DOCKER.md)):

```bash
.venv/Scripts/python.exe -m app.auth.cli add-user alice            # a member, unless first
.venv/Scripts/python.exe -m app.auth.cli add-user bob --role owner
.venv/Scripts/python.exe -m app.auth.cli list                      # shows each user's role
.venv/Scripts/python.exe -m app.auth.cli set-role alice owner      # never demotes the last owner
.venv/Scripts/python.exe -m app.auth.cli set-password alice        # revokes alice's sessions
.venv/Scripts/python.exe -m app.auth.cli disable alice             # locks out + revokes sessions
.venv/Scripts/python.exe -m app.auth.cli enable alice
.venv/Scripts/python.exe -m app.auth.cli revoke-sessions alice     # sign alice out everywhere
```

The same operations are available to a signed-in **owner** from the Data section of the UI
(`/api/users`); a member cannot reach that surface at all.

Passwords are prompted for interactively and never echoed; there is no way to pass one as an
argument. For scripting, pipe it in with `--password-stdin`. The only password rule is a 4-character
minimum (set low at the owner's request for this private LAN instance -- raise
`MIN_PASSWORD_LENGTH` in `backend/app/auth/passwords.py` if the instance is ever exposed more
widely). Usernames are case- and whitespace-insensitive.

The user database is a SQLite file at `data/auth.sqlite` (tracked by `INVDASH_DATA_DIR`, so it lives
on the Docker `/data` volume and persists across image rebuilds). It is separate from the ledger, so
an auth change never touches the ledger's schema. Only the salted `scrypt` hash of each password and
the SHA-256 of each session token are stored -- never a plaintext password or a usable token.

## Roles: owner and member

Login is the door to the building; the role is the one wall inside it. Every user is either the
**owner** or a **member**:

There are three tiers. A member refused by either owner tier gets the same
`403 {"detail": "owner_only"}`.

| Tier | Surface | Owner | Member |
| --- | --- | --- | --- |
| **Owner-only prefixes** (every method) | Tax (`/api/tax`), Account and transactions (`/api/portfolio`), imports (`/api/import`), user admin (`/api/users`), store status (`/api/health/stores`), manager desk (`/api/manager`) | yes | `403` |
| **Owner write, member read** | Agent desks (`/api/tradingagents`, `/api/vibedesk`, `/api/workflow`, `/api/agentdesk`), personas (`/api/personas`), job launchers (`/api/competition/jobs`, `/api/competition/loop`, `/api/timeframes`), translation (`/api/i18n`), market sweep (`/api/market/refresh`) | yes | `GET`/`HEAD` yes, everything else `403` |
| **Member read and write** | Everything else: market data, macro, news, reports, thesis, rules, backtests, the paper desk, and each user's own `/api/auth/password` | yes | yes |

The middle tier exists because those `POST`s are not reads with a side effect -- each one either
bills a model call to the owner's API key or seizes a process-wide slot for hours (a backtest, the
evolution loop, a timeframe sweep, a full provider refresh). Browsing a finished run stays open to
everyone; starting a new one does not. The daily spend cap
(`Settings.model_spend_daily_cap_usd`) bounds how much can be spent, not who may spend it.

Both owner tiers are matched by path prefix in the gate (`app.auth.gate.OWNER_ONLY_PREFIXES` and
`WRITE_OWNER_ONLY_PREFIXES`), so a route added under one of those prefixes is protected by default.
The frontend hides the owner-only sections for members rather than showing a page that cannot load.

Three rules keep an instance from locking itself out:

- **The first user created is always the owner**, whatever `--role` says.
- **At least one enabled owner always exists.** Disabling or demoting the last one is refused
  (`409 last_owner` over HTTP, an error from the CLI). Promote someone else first.
- **A database from before roles existed is migrated on startup**: the `role` column is added and
  the earliest-created enabled user becomes the owner.

A role change takes effect on the next request; nobody is signed out. When auth is off
(`INVDASH_AUTH_ENABLED=0`) there is no session to carry a role, the gate is a no-op, and `/api/auth/me`
reports `role: "owner"` so the UI renders every section.

## First run after a deploy

Auth is **on by default**, and a fresh instance has no users, so it is **locked**: every route but
the health check and the login endpoints returns `401` until someone exists. Create the first user
before anyone tries to sign in:

```bash
.venv/Scripts/python.exe -m app.auth.cli add-user <owner>
```

## Turning auth off (local development)

For single-user work on your own machine, a login screen is just friction. Set `INVDASH_AUTH_ENABLED=0`
in `.env`; the gate becomes a no-op and the app renders as it did before this feature existed. The
test suite already runs with auth disabled (see `tests/conftest.py`).

## Exposure beyond the LAN

The supported topology is loopback or LAN over plain HTTP (see [`DOCKER.md`](DOCKER.md)). The session
cookie is `HttpOnly` and `SameSite=Lax`, which is adequate for ten known users on a local network.

If the instance is ever reachable from anywhere wider, put a TLS terminator in front (Caddy, a
reverse proxy, or Tailscale Serve) and set `INVDASH_AUTH_COOKIE_SECURE=1` so the cookie is sent only
over HTTPS. Do **not** set that flag without TLS in front: a `Secure` cookie is never sent over plain
HTTP, so every login would silently fail. Login itself is not a substitute for TLS -- without it,
credentials cross the wire in the clear.

### Exposing beyond loopback: the order is not negotiable

The listener today is **loopback-only** (`127.0.0.1`), which is what makes every weaker choice below
survivable. Widening it is the *last* step, never the first:

1. **Put a TLS terminator in front.** Nothing else changes yet; verify HTTPS actually serves the
   app through the proxy while the app itself is still on loopback.
2. **Set `INVDASH_AUTH_COOKIE_SECURE=1`** and restart. Sign in over HTTPS and confirm the session
   sticks. This step is worthless before step 1 (the cookie is never sent) and dangerous after step
   3 (the session cookie crosses the open network in the clear until you do it).
3. **Widen the bind** (`--host 0.0.0.0`, or the Docker port publish) only now.

Any other order leaves a window in which either logins fail silently or session cookies and
credentials cross the wire unencrypted. Two more things to check before step 3:

- **`INVDASH_AUTH_ENABLED=0` opens every route to anyone who can reach the port** -- the ledger,
  the tax forms, the import surface, all of it, with no session at all. The server says so at
  startup with a `logger.warning` (see the `lifespan` function in `backend/app/main.py`); that
  warning is the check. Auth must be **on** before the bind is widened.
- **Security response headers** (`nosniff`, `x-frame-options: DENY`, `no-referrer`, `no-store`) are
  applied to every `/api/` response by `app.auth.headers.SecurityHeadersMiddleware`. Two are
  deliberately *not* there and become the terminator's job: **HSTS**, which goes on the TLS
  terminator at step 1, and **CSP**, which belongs on the nginx serving the frontend
  (`frontend/Dockerfile`).

### Password length: an owner decision

`MIN_PASSWORD_LENGTH` in `backend/app/auth/passwords.py` is **4**, set low at the owner's explicit
request (2026-09-05) for this private, loopback-bound instance. It is recorded here as a decision,
not an oversight. A 4-character minimum is not defensible on an exposed instance: raise it to **12**
as part of the sequence above, before step 3. Existing passwords are not re-validated on a change to
this constant, so raise it and then rotate the accounts with `set-password`.

## What the login protects, and what it does not

- **Protected:** every API route except `GET /api/health` (the container healthcheck) and the login
  routes themselves (`/api/auth/login`, `/api/auth/logout`, `/api/auth/me`). `/docs` and
  `/openapi.json` are gated too.
- **Partitioned by role, not by user:** there is one dataset. The owner sees all of it; members see
  the research surfaces and none of the personal ledger, and cannot start the runs that spend the
  owner's model budget (see *Roles* above). This is still not multi-tenancy -- two owners see the
  same ledger.
- **Not covered:** the MCP server and the UAT harness reach the engines in-process, not over HTTP,
  so they are unaffected by the gate. A brute-force limiter (5 failures per 15 minutes, per username
  and per IP) bounds password guessing; it is in-memory and single-process, matching the one-worker
  deployment.
