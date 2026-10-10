# Running with Docker

> **Status: config validated with the real Docker CLI; images still never built.**
> Updated 2026-08-24 (second pass, same day). Supersedes the WSL diagnosis two paragraphs
> below this one, which was itself written earlier the same day and has since drifted.
>
> What changed since that earlier pass: `wsl.exe` is **no longer the version stub**.
> `wsl --status` now runs and returns real output -- `Default Version: 2` -- instead of
> the `--install` usage-only text it printed before, which means the WSL optional Windows
> feature **is enabled** on this machine today. Re-run verbatim, `wsl --status` currently
> prints:
> ```
> Default Version: 2
>
> The Windows Subsystem for Linux kernel can be manually updated with 'wsl --update', but
> automatic updates cannot occur due to your system settings. ...
> The WSL 2 kernel file is not found. To update or restore the kernel please run 'wsl --update'.
> ```
> and `wsl -l -v` prints:
> ```
> Windows Subsystem for Linux has no installed distributions.
> Distributions can be installed by visiting the Microsoft Store: https://aka.ms/wslstore
> ```
> So the blocker is no longer "WSL isn't installed" -- it is two narrower, still-unmet
> things: **the WSL2 kernel component is missing**, and **no distribution is installed**
> (Docker Desktop's Linux engine needs a distro to run inside). `wsl --update` fixes the
> first on its own; `wsl --install -d <distro>` fixes both in one step, since it pulls the
> kernel component along with the distro if either is missing. See "Enabling WSL2
> (Windows)" below, updated to match.
>
> `docker version` confirms the engine is still unreachable: `failed to connect to the
> docker API at npipe:////./pipe/dockerDesktopLinuxEngine ...  The system cannot find the
> path specified`, and a process check (`Get-Process`, matched against `docker` and
> `com.docker`) found zero Docker-related processes running -- Docker Desktop is installed
> but not started.
>
> **SUPERSEDED 2026-08-24, later the same day: the stack now builds and runs.** The owner
> fixed WSL (`wsl --update --web-download` from an elevated prompt -- plain `wsl --update`
> failed with `Catastrophic failure` because this machine is not opted in to Microsoft-product
> updates, so the Windows Update path it uses is unavailable), then installed a distro and
> started Docker Desktop. `docker version` now reports server **29.7.2**, `wsl -l -v` shows
> `docker-desktop  Running  2`, and the engine is `linux/x86_64`, 8 CPU, 8.26 GB.
>
> **First build in this repository's history, and it passed.** `docker compose build` exited 0.
> Everything the paragraph below said was unconfirmed is now confirmed -- see "Verified against
> a running stack" further down for the actual output. The original text is kept rather than
> deleted, because the reasoning it records was correct at the time and the conclusions it
> reached by static review all held:
>
> > ~~What is still unverified: **the images have never been built and the stack has never
> > been started.** `docker compose config` never contacts the daemon, so nothing below
> > about a *running* container is confirmed -- not the backend boot, not nginx's `/api/`
> > proxy, not the CSP headers `frontend/Dockerfile` sets, not the `/api/health` response.
> > **No image in this repository has ever been built.**~~
>
> **The two steps that would make containers runnable here** -- both the owner's call, not
> something an agent should run unattended, since the first needs elevation and reboots
> the machine:
> 1. From an **Administrator** PowerShell: `wsl --install -d <distro>` (e.g. `wsl --install
>    -d Ubuntu`) -- installs the missing kernel component and a distribution in one step.
>    Reboot when it asks.
> 2. Start Docker Desktop (from the Start menu, or the per-user install at
>    `C:\Users\<user>\AppData\Local\Programs\DockerDesktop`) and wait for it to report
>    "Engine running".
>
> Nothing below this box has been re-verified against that end state, because neither step
> has been taken on this machine as of this update.

## Topology (current default): frontend in Docker, backend on the host

**As of this revision, `docker compose up` starts only the frontend.** The backend
(FastAPI/uvicorn) is expected to run directly on the Windows host, not in a container --
it wants the repo venv, the host's Anthropic credentials (an `ant auth login` profile
under `%APPDATA%\Anthropic`, which a container cannot see), and it runs a long-lived loop
a developer needs to restart quickly. The frontend is a static bundle with no such needs,
so it stays in nginx/Docker.

Run the backend on the host:

```
.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir backend
```

(from the repo root). See "Binding the host backend beyond 127.0.0.1" immediately below
for what `--host 0.0.0.0` actually costs before running that command -- it is not a free
choice.

Run the frontend in Docker:

```
docker compose up --build -d
```

nginx's `/api/` reverse proxy target is **not baked into the image** -- it is resolved at
container *start* from the `API_PROXY_TARGET` environment variable via nginx's own
envsubst-on-templates mechanism (see `frontend/Dockerfile`). `docker-compose.yml` sets it
to `http://host.docker.internal:8000` by default, which is what makes the container reach
the host backend above.

**The old both-in-Docker topology still exists**, gated behind a Compose profile, for
whoever wants the backend containerized instead:

```
API_PROXY_TARGET=http://backend:8000 docker compose --profile backend up --build -d
```

`--profile backend` starts the `backend` service (build, `/data` bind mount, port 8002,
HEALTHCHECK -- all unchanged from before this revision). The `API_PROXY_TARGET` override
on the left is required, not optional: without it, the frontend container still defaults
to proxying at the host, even when the backend container is also running side by side.
Compose has no per-profile conditional value for a single service's `environment:` block,
so this is a documented manual override rather than something Compose switches
automatically -- see the comment on `frontend.environment` in `docker-compose.yml`.

There is no more `depends_on: backend: condition: service_healthy` gating frontend
startup (it depended on the `backend` service, which is now profile-gated and, in the
default topology, doesn't exist as a Compose service at all). **What that costs:** nginx
now starts immediately and returns `502` on `/api/*` until whatever `API_PROXY_TARGET`
names is actually accepting connections, instead of Compose blocking frontend startup on
a health check. Verified below -- a `502` with no backend running is the expected,
correct result, not a defect.

## Binding the host backend beyond 127.0.0.1

This is the one real tension in this design, and it is not hidden: a container reaching
`host.docker.internal` generally needs the host process it's calling to be listening on
an address a container can reach, not `127.0.0.1` only -- which is in tension with this
repo's own security rationale (see `docker-compose.yml`'s header comment). **Every route
now requires a session.** A login gate (`backend/app/auth/gate.py`'s
`AuthGateMiddleware`) returns `401 {"detail": "not_authenticated"}` on anything except
`GET /api/health` (the container healthcheck), `/api/auth/login`, `/api/auth/logout`,
`/api/auth/me`, and `OPTIONS` preflights -- `/docs` and `/openapi.json` are gated too.
See `docs/AUTH.md` for the full design.

That auth is real, but it does not by itself make a wider bind safe. The traffic here is
plain HTTP, `Settings.auth_cookie_secure` defaults to `False`, and the login throttle (5
failed attempts per 15 minutes, per username and per IP) is in-memory and
single-process -- so a wider bind still puts the login form and the session cookie on a
wire that a bigger network can read, and the tax endpoints (`/api/tax/report`,
`/api/tax/form8949.csv`) remain a complete realized-gains history available to anyone
who can present a valid session.

What was actually verified on this machine, 2026-08-25, against Docker Desktop 4.87.0 /
engine 29.7.2 (Windows, WSL2 backend) -- **this corrects an assumption in the original
design brief for this change, so read it before choosing a bind address:**

```
$ Get-NetTCPConnection -LocalPort 8000 -State Listen | Select LocalAddress,LocalPort
LocalAddress LocalPort
------------ ---------
127.0.0.1         8000

$ curl -s http://localhost:8080/api/health      # through the frontend container's proxy
{"status":"ok"}
$ curl -s http://127.0.0.1:8000/api/health       # direct on the host
{"status":"ok"}
```

A backend bound **only** to `127.0.0.1:8000` on the host was reached successfully by the
frontend container via `host.docker.internal`, with no `--host 0.0.0.0` involved. This is
real, verified Docker Desktop behavior, not a Linux-Docker assumption carried over
incorrectly: Docker Desktop's networking layer (Windows and Mac both use the same
vpnkit-style host-forwarding design) implements `host.docker.internal` as a proxy that
runs with the host's own network access, which can reach loopback-only services. It is
**not** equivalent to a real routed connection arriving at the host's network stack from
an external address -- which is exactly what a `127.0.0.1`-bound listener normally
refuses.

**So on this Windows + Docker Desktop setup specifically: you do not need `--host
0.0.0.0`.** Run the backend on `127.0.0.1` (the safer default -- see
`docker-compose.yml`'s header comment on why) and the containerized frontend's proxy
already reaches it, as verified above. Prefer this. Only reach for `--host 0.0.0.0` if
you have a concrete reason Docker Desktop's forwarding doesn't cover (e.g. this repo is
ever run under native Linux Docker instead of Docker Desktop -- there, `extra_hosts`'
`host-gateway` resolves to a real gateway IP on a real interface, not a host-forwarding
proxy, and a `127.0.0.1`-only listener genuinely would not be reachable; `--host 0.0.0.0`
would be required there, not merely convenient).

If you do end up needing `--host 0.0.0.0` for any reason:

- It makes the API reachable from the local network (any other device on the same Wi-Fi
  or LAN segment), not just this machine -- **unless the host firewall blocks it.**
- Windows Defender Firewall prompts on the first bind to a new port and blocks inbound
  connections by default on Public network profiles. That is a **real** mitigation --
  it is not nothing -- but it is **not a guarantee**: it does not fire on Private/Domain
  profiles the same way, and a developer can click "Allow" without thinking. A request
  now needs a valid session to reach `/api/tax/report` or `/api/tax/form8949.csv` (see
  `docs/AUTH.md`), but the login itself and the resulting session cookie both travel as
  plain HTTP, `auth_cookie_secure` is off by default, and the login throttle is
  in-memory/single-process -- so a wider bind still hands a bigger network a shot at the
  login form and at the cookie in transit.
- The firewall prompt is a speed bump. What actually closes this gap is TLS in front of
  the API plus `INVDASH_AUTH_COOKIE_SECURE=1` (so the session cookie gets the `Secure`
  flag for real) -- the login gate on its own is not that, over plain HTTP. See
  `docs/AUTH.md`.

**A safer alternative, if LAN exposure is ever unacceptable for your situation:** don't
put the frontend in Docker at all. Keep the backend on `127.0.0.1:8000` and run
`npm run dev` from `frontend/` instead -- Vite's dev server proxies `/api/*` to
`127.0.0.1:8000` directly (see `frontend/vite.config.ts`), entirely on loopback, no
container networking involved. This sidesteps container networking, not the login gate
itself -- every request still needs a valid session either way, see `docs/AUTH.md` --
but it keeps both the login exchange and the session cookie off any wire wider than
loopback. That is the recommended fallback when the Docker Desktop host-forwarding
behavior above is not available or not trusted for your environment (e.g. native Linux
Docker without administering the firewall yourself).

## Prerequisites

- Docker Engine with the Compose plugin (`docker compose`, not the standalone `docker-compose`).
- **On Windows Home: WSL2.** Docker Desktop's engine runs inside WSL2, and Home has no
  Hyper-V alternative, so without it the daemon never starts and every command below fails
  with `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`.
  See "Enabling WSL2 (Windows)".
- A `.env` file at the repo root (copy `.env.example` and fill in `INVDASH_FRED_API_KEY` --
  optional; see the comments in `.env.example`). Only needed for `--profile backend` --
  `docker compose` reads it via `env_file:` in `docker-compose.yml` and injects it as
  environment variables into the `backend` *container*, which does not exist in the
  default (host-backend) topology. The file is never copied into an image.
- An existing `data/` directory at the repo root (even empty) -- only needed for
  `--profile backend`'s bind mount. In the default topology the host backend reads
  `data/` directly, the same way the non-Docker workflow always has.

## Run it

**Default topology (frontend in Docker, backend on the host):**

```
.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir backend
docker compose up --build -d
```

- Backend (FastAPI/uvicorn, on the host): http://localhost:8000 -- try http://localhost:8000/api/health
- Frontend (static build served by nginx, which proxies `/api/*` to `API_PROXY_TARGET`,
  defaulting to `http://host.docker.internal:8000`): http://localhost:8080, and
  http://localhost:8080/api/health should proxy through to the same response.

See "Binding the host backend beyond 127.0.0.1" above before running the backend command
above with `--host 0.0.0.0` -- on this machine's Docker Desktop it was verified to be
unnecessary (127.0.0.1 alone was reachable via the proxy); it is shown here because it is
the more portable form across Docker backends, not because it's required here.

**Old both-in-Docker topology, via `--profile backend`:**

```
API_PROXY_TARGET=http://backend:8000 docker compose --profile backend up --build -d
```

- Backend (FastAPI/uvicorn, containerized): http://localhost:8002 -- try http://localhost:8002/api/health
- Frontend: http://localhost:8080, proxying to the `backend` container over the Compose
  network rather than the host.

Host ports **8002** and **8080** were chosen because 8000 and 5174 were already in use by
another dev environment on this machine at the time this was written. **Not 8001**: that
port is also used by `.claude/launch.json`'s `uat-backend` configuration
(`uat.harness.serve --port 8001`, run directly on the host, not in a container) --
publishing the backend container there too would collide with it the moment both are
started in the same session. 8002 was checked against every `"port"` value in
`.claude/launch.json` and found free. Change the left-hand side of the `ports:` mappings in
`docker-compose.yml` if 8002/8080 collide with something else on your machine; nothing
else depends on those specific numbers.

Stop with `docker compose down` (add `-v` only if you also want to remove anonymous volumes;
there are none of consequence here since `data/` is a bind mount, not a named volume).
Verified with `docker compose down --dry-run` against a stack that had both `frontend`
(default) and a `backend` container (started earlier via `--profile backend`) running:
plain `down` only targets `frontend` -- the backend container is left running, and the
shared network reports "still in use" rather than being removed. If you started with
`--profile backend`, stop with `docker compose --profile backend down` to also remove the
backend container; `down` filters by profile the same way `up` does, it does not clean up
everything unconditionally.

## Volume layout

The backend container sets `INVDASH_DATA_DIR=/data`, `INVDASH_STORE_DIR=/data/store` and
`INVDASH_CACHE_DIR=/data/cache` (see `backend/app/config.py` for what each governs), and
`docker-compose.yml` bind-mounts the repo's `./data` directory to `/data` in the container.

This is the point of the whole setup: your real brokerage exports and the derived
`ledger.sqlite` / `analytics.duckdb` / parquet bars live only on the host filesystem, at the
same `data/` path the non-Docker workflow already uses. Neither `backend/Dockerfile` nor
`frontend/Dockerfile` ever `COPY`s `data/` or `.env` into an image layer, and `.dockerignore`
excludes both from the build context as a second line of defense. Deleting the containers or
rebuilding the images does not touch anything under `data/`.

The login gate's user database (`Settings.auth_db_path`, i.e. `data_dir/auth.sqlite`,
see `backend/app/config.py`) lives under this same mount -- with `INVDASH_DATA_DIR=/data`
that's `/data/auth.sqlite` inside the `backend` container. **A freshly built or freshly
mounted container is fully locked**, the same as a fresh checkout on the host: with zero
users in that database, the login gate rejects every request, by design. Create one with
`docker compose --profile backend exec backend python -m app.auth.cli add-user <name>`
(or the equivalent host command against the same `data/` directory if you're using the
default host-backend topology) before expecting to reach anything past `/api/health`.
See `docs/AUTH.md` for the CLI's full usage.

## Environment variables that matter

| Variable | Where it's set | Purpose |
|---|---|---|
| `API_PROXY_TARGET` | `ENV` default in `frontend/Dockerfile` (`http://host.docker.internal:8000`), overridable via `docker-compose.yml`'s `frontend.environment` (`${API_PROXY_TARGET:-...}`) | Where nginx's `/api/` reverse proxy sends requests, resolved at container *start* (not build time) via nginx's envsubst-on-templates mechanism. Default targets the host backend; override to `http://backend:8000` when using `--profile backend`. Not secret -- just a URL. |
| `INVDASH_FRED_API_KEY` | Host `.env`, passed through via `env_file:` (only read by the `backend` service, i.e. only relevant under `--profile backend`) | Optional FRED API access; see `.env.example`. Never appears in `docker-compose.yml`, either Dockerfile, or any image layer. For the default (host-backend) topology, set it however the host process normally picks it up (e.g. the host's own `.env` / shell environment). |
| `INVDASH_DATA_DIR`, `INVDASH_STORE_DIR`, `INVDASH_CACHE_DIR` | Hardcoded in `docker-compose.yml`'s `environment:` block for the `backend` service (only relevant under `--profile backend`) | Redirect storage paths to the `/data` mount point described above. Not secret -- just paths. In the default topology the host backend uses its normal on-host paths instead. |

## Architecture notes

- `backend/Dockerfile` is multi-stage: a `builder` stage with build tooling installs the
  package from `backend/pyproject.toml` into a venv; the `runtime` stage copies just that venv
  plus `backend/app` and runs as a non-root user (`appuser`). Only built/run at all under
  `--profile backend` -- the default topology runs the backend on the host instead (see
  "Topology" above).
- `frontend/Dockerfile` is multi-stage: a Node stage runs `npm ci && npm run build` (the
  production build, never `npm run dev`); an nginx stage serves the resulting `dist/` output as
  static files and reverse-proxies `/api/` to whatever `API_PROXY_TARGET` names --
  **resolved at container start, not baked in at build time** (nginx's own
  envsubst-on-templates mechanism, filtered via `NGINX_ENVSUBST_FILTER` so only
  `API_PROXY_TARGET` is substituted and nginx's own `$host`/`$remote_addr`/etc. runtime
  variables survive untouched -- verified by rendering the template, see "Verified:
  frontend-in-Docker, backend-on-host" below). Default target is
  `http://host.docker.internal:8000` (the host backend); `--profile backend` overrides it
  to `http://backend:8000` (the Compose service name/network) for the old topology. Runs
  as the base image's non-root `nginx` user, listening on 8080 (not 80) so it never needs
  root to bind the port.
- The rendered `location /api/` block (see the "Rendered nginx config" excerpt below) sets
  no `proxy_cookie_path` or `proxy_hide_header` -- it passes every response header,
  `Set-Cookie` included, straight through unmodified. That means the login gate's
  `invdash_session` cookie (see `docs/AUTH.md`) needs no proxy-side change to work through
  this frontend container: the browser sees the cookie exactly as the backend set it,
  scoped to whatever `Path=/` and `SameSite=Lax` it was issued with, regardless of whether
  the backend is the host process or the `--profile backend` container.
- Because the browser only ever talks to the nginx origin, and nginx forwards `/api/` calls to
  the backend server-side (host or container, either way), `backend/app/main.py`'s CORS
  allow-list (which only lists the Vite *dev-server* origins) is simply never exercised in
  this setup -- there is no cross-origin browser request to allow in the first place.

## What "verified" would look like

If you have Docker available, the honest verification for this file is:

```
docker compose up --build -d
curl -s http://localhost:8002/api/health
curl -sI http://localhost:8080/
docker compose down
```

The first `curl` should return `{"status": "ok"}`; the second should return a `200` with
`Content-Type: text/html`. **Both have now been executed against a running stack and both
passed** -- see "Verified against a running stack" immediately below.

## Verified against a running stack

> **This section and "Verified after the HEALTHCHECK / depends_on / port fixes" below both
> describe the OLD both-in-Docker topology** (backend and frontend both containerized,
> `depends_on: backend: condition: service_healthy`, proxy hardcoded to
> `http://backend:8000`) -- the topology now reachable via `docker compose --profile
> backend up`, not the default. Kept verbatim as the historical record of what was true
> when it was written; none of it was re-run or changed for this revision. See "Verified:
> frontend-in-Docker, backend-on-host" further below for the current default topology's
> verification.
>
> The record immediately below predates the fixes in "Verified after the HEALTHCHECK /
> depends_on / port fixes" further down: it was captured while the backend still published
> on host port **8001** and before `frontend` waited on `backend`'s health. Kept verbatim as
> the historical record of the first successful build/run in this repo -- see the later
> section for the current state (port 8002, `service_healthy` gating, backend HEALTHCHECK).

Executed 2026-08-24 against a real engine (server 29.7.2), not by static review:

```
docker compose build                     # exit 0 -- both images built, first time ever
docker compose up -d                     # backend + frontend both running

docker images
  investing-dashboard-backend:latest     599MB
  investing-dashboard-frontend:latest    68.5MB

curl localhost:8001/api/health           {"status":"ok"}
curl localhost:8001/openapi.json         60 routes, incl. /api/news/{ticker,macro}
                                         and /api/market/refresh/status
curl -o /dev/null -w '%{http_code}' localhost:8080/             200
curl -o /dev/null -w '%{http_code}' localhost:8080/api/health   200
```

Three claims this settles that static review could only argue for:

* **The store is not baked into the image.** 599MB for the backend against a multi-gigabyte
  `data/store/bars/` tree is the proof `.dockerignore`'s `data/` exclusion actually works.
* **nginx's `/api/` proxy resolves the Compose service name.** `localhost:8080/api/health`
  returning 200 means the frontend container reached `http://backend:8000/api/` over the
  Compose network -- the question the dev-only `127.0.0.1:8000` Vite proxy raised.
* **The narrow `PYTHONPATH=/app/backend` is sufficient.** The app imports and serves with only
  `backend/` on the path, as `tests/test_deployment_paths.py` pins.

The full page renders end to end: `http://localhost:8080/ticker/AAPL` shows the four nav
sections (Overview / Portfolio / Strategy Lab / Market) and the ticker page's own headings
through to "News & sentiment" and "Institutional holders", with no error boundary.

Stop it with `docker compose down`.

## Verified after the HEALTHCHECK / depends_on / port fixes

> **This section also describes the old both-in-Docker topology** -- see the note at the
> top of "Verified against a running stack" above. `depends_on: backend: condition:
> service_healthy`, described and verified below, no longer exists in the default
> topology's `docker-compose.yml`; it only applies when running with `--profile backend`,
> and even there the `frontend` service itself carries no `depends_on` any more (Compose
> does not allow a profile-less service to depend on a profile-gated one -- see the
> comment on `frontend` in `docker-compose.yml`). Kept verbatim as history.

Both findings this file previously recorded as low-severity and deliberately unfixed
("no HEALTHCHECK, `depends_on` only waits for `service_started`" and "host port 8001
collides with `.claude/launch.json`'s `uat-backend`") are now fixed, and re-verified against
a real engine on 2026-08-24 (same day, later pass) rather than argued for statically:

**What changed:**
- `backend/Dockerfile` now declares a `HEALTHCHECK` that probes `/api/health` with
  `python -c "import urllib.request; ..."` (no shell, exec form) -- this image has neither
  `curl` nor `wget` (`docker compose exec backend which curl` / `which wget` both exit 1),
  confirmed before picking the probe. Parameters: `--interval=5s --timeout=3s
  --start-period=30s --retries=3`. `start-period=30s` is ~10x the measured actual
  time-to-healthy (3.12s, see below) specifically so a slower disk, a CPU-starved host, or a
  much bigger `data/` mount doesn't turn a slow-but-healthy boot into a restart loop -- see
  the comment above the `HEALTHCHECK` line in `backend/Dockerfile` for the full reasoning
  behind each of the four numbers.
- `docker-compose.yml`'s `frontend` service now depends on `backend` with
  `condition: service_healthy` instead of the implicit `service_started`, so nginx no longer
  starts before uvicorn is confirmed accepting connections.
- The backend's host-side publish moved from `127.0.0.1:8001:8000` to `127.0.0.1:8002:8000`
  to stop colliding with `.claude/launch.json`'s `uat-backend` (`uat.harness.serve --port
  8001`, run on the host, not in a container). 8002 was checked against every `"port"` value
  in `.claude/launch.json` and against the repo for any other use as a service port; none
  found. All command examples in this file above now say 8002, not 8001.

**Boot time, measured, not estimated** (backend already built, `data/` already mounted,
warm image -- `docker compose stop backend` then `docker compose start backend`, polling
`/api/health` from the host every 0.25s):

```
healthy after 3.12s (attempt 12)
```

**`docker compose config --quiet`** after the edits: exit 0 -- the compose file still parses
(this caught an early mistake: an empty `healthcheck:` block under `backend` in
`docker-compose.yml`, added to note that Compose picks up the image-level HEALTHCHECK
automatically, parsed as `healthcheck: null` and was removed in favor of a plain comment).

**Full rebuild and fresh `up`:**

```
$ docker compose down
$ docker compose build
 ... both images built (frontend build hit an unrelated, transient TS2307 "Cannot find
     module './BookStatistics'" error on the first attempt -- another active session was
     mid-edit on frontend/src/pages/paperdesk/ at that moment; a second `docker compose
     build frontend` immediately after succeeded, confirming it was a build-context race
     against a concurrently-changing source tree, not a defect introduced here)
 Image investing-dashboard-backend Built
 Image investing-dashboard-frontend Built

$ docker compose up -d
 Network investingdashboard_default Created
 Container investingdashboard-backend-1 Created
 Container investingdashboard-frontend-1 Created
 Container investingdashboard-backend-1 Starting
 Container investingdashboard-backend-1 Started
 Container investingdashboard-backend-1 Waiting     <- frontend has not started yet
 Container investingdashboard-backend-1 Healthy     <- only now does frontend start
 Container investingdashboard-frontend-1 Starting
 Container investingdashboard-frontend-1 Started
```

That `Waiting` / `Healthy` sequence with the frontend container not created-and-started
until after it is the `service_healthy` gate working, not `service_started`: previously
Compose would have started `frontend` the instant `backend`'s process began, without
waiting for the HEALTHCHECK at all.

**`docker compose ps`:**

```
NAME                            IMAGE                          COMMAND                  SERVICE    CREATED          STATUS                    PORTS
investingdashboard-backend-1    investing-dashboard-backend    "python -m uvicorn a…"   backend    19 seconds ago   Up 14 seconds (healthy)   127.0.0.1:8002->8000/tcp
investingdashboard-frontend-1   investing-dashboard-frontend   "/docker-entrypoint.…"   frontend   15 seconds ago   Up 7 seconds              127.0.0.1:8080->8080/tcp
```

**`docker inspect` on the healthcheck itself** -- confirms the exact parameters landed in the
image and that the probe genuinely succeeds without curl or wget:

```
$ docker inspect investingdashboard-backend-1 --format '{{json .Config.Healthcheck}}'
{"Test":["CMD","python","-c","import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"],"Interval":5000000000,"Timeout":3000000000,"StartPeriod":30000000000,"Retries":3}

$ docker inspect investingdashboard-backend-1 --format '{{json .State.Health}}'
{"Status":"healthy","FailingStreak":0,"Log":[
  {"Start":"2026-08-25T00:40:09Z","End":"2026-08-25T00:40:10Z","ExitCode":0,"Output":""},
  {"Start":"2026-08-25T00:40:15Z","End":"2026-08-25T00:40:16Z","ExitCode":0,"Output":""},
  {"Start":"2026-08-25T00:40:21Z","End":"2026-08-25T00:40:22Z","ExitCode":0,"Output":""}
]}
```

**Probes, on the new port:**

```
$ curl -s http://127.0.0.1:8002/api/health
{"status":"ok"}

$ curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8001/api/health --max-time 2
000                                          # nothing docker-related on 8001 any more
$ curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/
200
$ curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/health
200
```

All four confirm: the backend is reachable (and only) on 8002, the old port is free for
`uat-backend` to use without collision, and the frontend (and its `/api/` proxy) still work
end to end with the new `depends_on` gate in place.

What was executed *before* the engine existed, and passed:

```
docker compose config --quiet     # exit 0 -- parses, interpolates .env, resolves mounts/ports
```

That is a static check of this file only. It proves nothing about whether the images build or
the containers run.

## Verified: frontend-in-Docker, backend-on-host (current default topology)

Executed 2026-08-25 against Docker Desktop 4.87.0 / engine server 29.7.2 (Windows,
WSL2 backend), not by static review. This is the verification for the topology change in
this revision -- frontend containerized, backend on the host, `API_PROXY_TARGET`
resolved at container start.

**Compose picks the right services by profile:**

```
$ docker compose config --quiet
(exit 0)

$ docker compose config --services
frontend

$ docker compose --profile backend config --services
backend
frontend
```

A bare `docker compose up` only ever considers `frontend` -- confirming `backend`'s
`profiles: ["backend"]` actually gates it, not just documents an intent.

**Build:**

```
$ docker compose build frontend
...
 Image investing-dashboard-frontend Built
```

Clean build, `npm run build` inside the Node stage produced the usual `dist/` bundle, no
errors.

**Up and `ps`:**

```
$ docker compose up -d
 Container investingdashboard-frontend-1 Started

$ docker compose ps
NAME                            IMAGE                          ...  SERVICE    STATUS                  PORTS
investingdashboard-backend-1    ...                            ...  backend    Up 26 hours (healthy)   127.0.0.1:8002->8000/tcp
investingdashboard-frontend-1   investing-dashboard-frontend   ...  frontend   Up 1 second             127.0.0.1:8080->8080/tcp
```

The `backend` row is a container left running from an earlier `--profile backend`
session on this machine (`docker compose ps` lists everything belonging to the project
regardless of the current invocation's profile -- only `up`/`down` filter by profile, as
verified separately below). This `docker compose up -d` invocation itself started only
`frontend`, matching the `config --services` output above.

**Rendered nginx config -- proves `envsubst` resolved `API_PROXY_TARGET` and left
nginx's own variables alone:**

The exact command given in this change's brief,
`docker run --rm --entrypoint sh investing-dashboard-frontend -c "cat
/etc/nginx/conf.d/default.conf"`, does **not** demonstrate this -- `--entrypoint sh`
replaces the base nginx image's `ENTRYPOINT` (`/docker-entrypoint.sh`) entirely, so none
of `/docker-entrypoint.d/*.sh` (including the envsubst-on-templates script) ever runs.
Confirmed by actually running it:

```
$ docker run --rm --entrypoint sh investing-dashboard-frontend -c "cat /etc/nginx/conf.d/default.conf"
server {
    listen       80;
    server_name  localhost;
    ...
    location / {
        root   /usr/share/nginx/html;
        index  index.html index.htm;
    }
    ...
}
```

That is the **stock, unmodified nginx base-image config** (port 80, the default
`html`/PHP-FPM boilerplate) -- proof that this repo's config was never written to
`/etc/nginx/conf.d/` at build time any more (it now only exists as the *template*, at
`/etc/nginx/templates/default.conf.template`), and that bypassing `ENTRYPOINT` bypasses
rendering entirely. The correct way to observe the rendered config is against a
container that actually went through `/docker-entrypoint.sh` -- i.e. one started
normally by `docker compose up` / `docker run` without an entrypoint override -- inspected
with `docker exec`:

```
$ docker exec investingdashboard-frontend-1 cat /etc/nginx/conf.d/default.conf
server {
    listen 8080;
    server_name _;
    ...
    location /api/ {
        proxy_pass http://host.docker.internal:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

`proxy_pass` resolved to the real default (`http://host.docker.internal:8000/api/`), and
`$host`, `$remote_addr`, `$proxy_add_x_forwarded_for`, `$scheme` all survived as literal,
unsubstituted nginx variables -- `NGINX_ENVSUBST_FILTER=^API_PROXY_TARGET$` did exactly
what it was set to do.

**Page and proxy, live:**

```
$ curl -s -o /dev/null -w "frontend root: %{http_code}\n" http://localhost:8080/
frontend root: 200

$ curl -s -o /dev/null -w "api via proxy: %{http_code}\n" http://localhost:8080/api/health
api via proxy: 200
```

A `502` was the expected result here if no backend were reachable at
`host.docker.internal:8000` -- it did not occur because a backend process happened to
already be running on the host at the time (see below), which let this also verify the
*success* path, not just the `502` fallback.

**The bind-address finding -- see "Binding the host backend beyond 127.0.0.1" above for
the full writeup, this is the raw evidence:**

```
$ Get-NetTCPConnection -LocalPort 8000 -State Listen | Select LocalAddress,LocalPort
LocalAddress LocalPort
------------ ---------
127.0.0.1         8000

$ curl -s http://127.0.0.1:8000/api/health
{"status":"ok"}
$ curl -s http://localhost:8080/api/health
{"status":"ok"}
```

The host process on port 8000 was bound to `127.0.0.1` only, confirmed via
`Get-NetTCPConnection`, not `netstat` alone (which can be ambiguous about dual-stack
binds) -- yet the containerized frontend's proxy reached it successfully through
`host.docker.internal`. **This means the 200-through-proxy case was verified with the
backend on loopback only, not with `--host 0.0.0.0`** -- stronger evidence than the brief
for this change anticipated, and the reason "Binding the host backend beyond 127.0.0.1"
above recommends keeping the backend on `127.0.0.1` rather than treating `--host 0.0.0.0`
as required.

**`docker compose down --dry-run` confirms profile filtering applies to `down` too:**

```
$ docker compose down --dry-run
 Container investingdashboard-frontend-1 Stopping
 Container investingdashboard-frontend-1 Stopped
 Container investingdashboard-frontend-1 Removing
 Container investingdashboard-frontend-1 Removed
 Network investingdashboard_default Removing
 Network investingdashboard_default Resource is still in use
```

Plain `down` (no `--profile backend`) only targets `frontend`; the `backend` container
from the earlier `--profile backend` session was left alone (and the network could not be
removed because that container was still using it) -- confirming the "stop with
`--profile backend down`" guidance under "Run it" above.

## Enabling WSL2 (Windows)

Only needed on Windows, and only once. Docker Desktop will not start without it on Windows
Home. This is the owner's step to run, not one an agent should run unattended -- it needs
Administrator elevation and it reboots the machine. From an **Administrator** PowerShell:

```
wsl --install -d <distro>
```

e.g. `wsl --install -d Ubuntu`. As of this update the WSL optional Windows feature is
already enabled on this machine (`wsl --status` runs and reports `Default Version: 2`,
rather than the old `--install`-usage-only stub output), but the WSL2 kernel component is
missing (`wsl --status`: *"The WSL 2 kernel file is not found. To update or restore the
kernel please run 'wsl --update'."*) and no distribution is installed (`wsl -l -v`: *"...has
no installed distributions"*). `wsl --install -d <distro>` pulls both the kernel and the
named distribution in one step; a bare `wsl --update` would fix only the kernel and still
leave no distro for Docker Desktop's Linux engine to run inside. Reboot when it asks. After
the reboot, `wsl --status` should report the kernel version instead of "file is not found",
`wsl -l -v` should list the installed distro, and Docker Desktop's engine should reach
"Engine running" once started (see the two-step box at the top of this file).

Then, from a **new** shell (an existing one will not have picked up the PATH entry Docker
Desktop added at install time):

```
docker compose up --build
```

Notes for this machine specifically:

- The CPU (i7-7700HQ) supports VT-x and `HypervisorPresent` already reports `True`, so no BIOS
  change is expected to be necessary. If `wsl --install` later complains that virtualization is
  disabled, that is a firmware setting and has to be changed in BIOS/UEFI, not from Windows.
- Earlier the same day this file was updated, `wsl.exe` behaved as the 10.0.19041
  version-stub -- usage-text-only output, and the WSL feature read as not enabled. That is
  no longer the current state: `wsl.exe` now runs for real and the feature is confirmed
  enabled directly from its own output (`Default Version: 2`), not inferred. What is
  missing now is narrower -- the kernel component and a distribution, both addressed by
  the `wsl --install -d <distro>` command above.

## A caution about `docker compose config`

`docker compose config` prints the **fully resolved** configuration, which means it interpolates
`env_file:` and echoes `INVDASH_FRED_API_KEY`'s real value to stdout in cleartext. That is
expected behaviour, not a leak in this repo -- `.env` is gitignored (`.gitignore:66`) and
untracked, and neither Dockerfile copies it. But do not paste raw `docker compose config` output
into an issue, a PR, a chat or a log without redacting that line first. Use
`docker compose config --quiet` when you only want the validation exit code, as above.
