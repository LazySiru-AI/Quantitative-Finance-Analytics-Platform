# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Backend image: FastAPI app (app.main:app) served by uvicorn.
#
# Build context is the repo root (see docker-compose.yml: `context: .`,
# `dockerfile: backend/Dockerfile`) so this file can be selective about what
# it pulls in -- notably NOT the repo-root `data/` directory and NOT `.env`.
#
# The user's real financial data (raw broker exports, and the derived
# ledger.sqlite / analytics.duckdb / parquet bars under data/store,
# data/cache) is NEVER copied into this image. It stays on the host and is
# bind-mounted at container start -- see the `data` volume in
# docker-compose.yml. Do NOT add `COPY data ...` or `COPY . .` to this file;
# either would bake real brokerage data into an image layer, which is exactly
# what this project must not do. `.dockerignore` also excludes data/ and .env
# as a second line of defense, so even a stray `COPY . .` would not pick them
# up -- but the explicit, narrow COPYs below are the primary guarantee.
# ---------------------------------------------------------------------------

# Pinned by digest, not just tag: a tag (even a specific patch tag like `3.12.6-slim-bookworm`) can
# be re-pushed to point at different bytes; a digest cannot. Digest resolved via
# `curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/python:pull"`
# then a HEAD-equivalent GET for the `docker-content-digest` response header on
# `https://registry-1.docker.io/v2/library/python/manifests/3.12.6-slim-bookworm` (multi-arch index
# digest -- the same one `docker pull python:3.12.6-slim-bookworm` would resolve to). Re-resolve with
# `docker buildx imagetools inspect python:3.12.6-slim-bookworm` if this ever needs to move.
FROM python:3.12.6-slim-bookworm@sha256:ad48727987b259854d52241fac3bc633574364867b8e20aec305e6e7f4028b26 AS builder

WORKDIR /build

# Build tooling for any dependency without a prebuilt wheel for this
# platform/interpreter. Lives only in this stage -- the runtime stage below
# never sees it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Only the backend's own manifest + source are needed to build the package.
COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir .

# ---------------------------------------------------------------------------
# Same image, same digest, same reasoning as the builder stage above.
FROM python:3.12.6-slim-bookworm@sha256:ad48727987b259854d52241fac3bc633574364867b8e20aec305e6e7f4028b26 AS runtime

# Run as an unprivileged user rather than the image default of root.
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --create-home --shell /usr/sbin/nologin appuser

COPY --from=builder /opt/venv /opt/venv

# Preserve the `backend/app/...` layout inside the image (rather than
# flattening to `/app/...`) purely so the path in the CMD below matches the
# documented local invocation, `uvicorn app.main:app --app-dir backend`, one
# for one.
COPY backend/app /app/backend/app

# Two trees outside `backend/` that the *served application* now reads at
# runtime. Naming the problem here beats letting the image fail to boot:
#
# That single COPY is now the whole application. Three trees used to be copied
# beside it, and tracking why each one left is the useful part of this comment:
#
#   uat/harness/       `app.tournament.runner` imported `marketdata` and
#                      `paperbroker` from it -- served application code reaching
#                      into a test harness, and the reason the server could not
#                      start with only `backend/` on the path. Both modules now
#                      live in `app.paper`, with `uat.harness.*` left behind as
#                      re-export shims for callers under `uat/` and `tests/`.
#   uat/personas/      the trading mandate -- cash, settlement, slippage, fees --
#                      came from `pro-investor-01.setup.json`, so the served app
#                      took its production constraints from a test fixture. Those
#                      numbers are code now, in `app.paper.mandate`.
#   strategy-program/  held both the strategy library and the round records. The
#                      library moved to `app/paper/library/` and so arrives with
#                      the COPY above -- `Settings.library_dir` resolves it
#                      relative to the package, precisely so it travels with an
#                      install. The rounds moved to `data/rounds/`, which is the
#                      bind mount below rather than image content, because they
#                      are written at runtime and grow without bound.
#
# So the image now contains the application and nothing else, and everything it
# reads at runtime arrives through `/data`. `tests/test_deployment_paths.py`
# holds both halves of that: `app.main` must import with only `backend/` on the
# path, and every directory the app still resolves against `REPO_ROOT` must
# appear in a COPY here or be a declared mount.

# backend/app/config.py resolves every store path from these env vars if set,
# falling back to paths under the repo root otherwise. Inside this image
# there is no repo root -- just /app -- so the paths are pointed explicitly
# at /data, which docker-compose.yml bind-mounts from the host's `data/`
# directory. This is the "volume layout is a config choice, not a code
# change" the settings module was written for.
# One entry, and it is load-bearing. `/app/backend` must win over the copy of
# `app` that `pip install .` put in site-packages, because `app.config.REPO_ROOT`
# is `Path(app/config.py).parents[2]`: import the installed copy and `REPO_ROOT`
# resolves somewhere inside the virtualenv, so every `REPO_ROOT`-relative read
# misses `/app/strategy-program`. PYTHONPATH precedes site-packages, which is
# what makes the COPYed tree the one that runs.
#
# `/app` used to be here as well, so `uat` could be imported. Nothing imports it
# any more and it is no longer copied into the image, so the entry went with it.
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/backend" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    INVDASH_DATA_DIR=/data \
    INVDASH_STORE_DIR=/data/store \
    INVDASH_CACHE_DIR=/data/cache \
    INVDASH_ROUNDS_DIR=/data/rounds

WORKDIR /app

# /data is the mount point for the host's data/ directory. It's created here
# (and owned by the app user) so the app can create data/store and
# data/cache under it on first run even before a volume is attached; when
# docker-compose.yml mounts the real ./data over it, the host directory's
# own ownership applies instead.
RUN mkdir -p /data \
    && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8000

# HEALTHCHECK: this image has no curl and no wget -- verified with `docker compose exec
# backend which curl` / `which wget`, both exit 1 on this slim base -- so the probe cannot
# be a plain `curl -f`. Python is guaranteed present (it's the runtime this CMD launches),
# so the probe is a bare urllib.request.urlopen against /api/health. urlopen() raises on
# any non-2xx status, connection refusal, or timeout, and an unhandled exception exits the
# interpreter non-zero -- exactly the signal HEALTHCHECK needs, with no extra plumbing.
#
# Parameters below come from a measured boot time, not a guess: with the image already
# built and `data/` already mounted, `docker compose stop backend && docker compose start
# backend` followed by polling /api/health from the host measured healthy at 3.12s.
#
#   start-period=30s  ~10x the measured 3.12s boot. Failures during start-period don't
#                      count toward `retries` and don't flip the container unhealthy, so
#                      this costs nothing once boot is fast -- but it matters a lot if it's
#                      ever NOT fast: a slower disk, a CPU-starved host, or a `data/` mount
#                      far larger than this dev machine's could all push real boot time up.
#                      A start-period too close to the measured value turns any of those
#                      into a restart loop on first deploy, which is strictly worse than the
#                      few seconds of 502s this HEALTHCHECK exists to fix -- so the margin is
#                      deliberately generous rather than tight.
#   interval=5s        Cadence once start-period has elapsed. Fast enough that
#                      `depends_on: condition: service_healthy` in docker-compose.yml
#                      doesn't add a long extra wait on top of the ~3s boot the frontend is
#                      already blocked on, without polling a trivial endpoint pointlessly
#                      often.
#   timeout=3s         /api/health does no I/O beyond returning a static payload, over
#                      loopback, inside the same container -- normally sub-10ms. 3s is
#                      generous headroom for a loaded host while still catching a process
#                      that's genuinely wedged rather than just briefly slow.
#   retries=3          Three consecutive failures (15s of sustained failure at this
#                      interval) before the container flips to unhealthy, so a single
#                      transient blip doesn't trigger it -- only a real, sustained outage
#                      does.
HEALTHCHECK --interval=5s --timeout=3s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
