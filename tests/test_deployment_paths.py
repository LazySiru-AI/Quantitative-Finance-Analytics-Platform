"""The server's import roots and the image's contents, against what the application actually reads.

This file exists because of a failure the rest of the suite is structurally incapable of seeing.

Adding `/api/paperdesk` and `/api/competition/*` gave `app.main` an import that reaches
`app.tournament.runner`, which imports `uat.harness.marketdata` and `uat.harness.paperbroker` --
modules living outside `backend/`. The documented invocation at the time was
`uvicorn app.main:app --app-dir backend`, which puts only `backend/` on `sys.path`. The server died
at import with `ModuleNotFoundError: No module named 'uat'`, and the Docker image -- which copies
`backend/app` and nothing else -- could not have started either.

**2262 tests passed throughout.** `pytest.ini` sets `pythonpath = . backend`, so the suite runs with
both roots present and every import resolves. A test suite configured to make imports work cannot
notice that the shipped configuration doesn't. Nothing here re-tests application behaviour; these
tests only assert that the ways the application is *started* agree with what it needs.

**Both halves have since been fixed, and the tests below are what hold the line.**

*The imports.* `marketdata.py` and `paperbroker.py` moved from `uat/harness/` into `app.paper`, where
application code may legitimately import them, and `uat.harness.*` became re-export shims so every UAT
caller kept its import path. `test_app_main_imports_with_only_backend_on_the_path` asserts the server
no longer needs the repository root on `sys.path` at all.

*The data.* The trading mandate -- cash, settlement, slippage, fees -- was read from
`uat/personas/pro-investor-01.setup.json`, so the served application took its production constraints
from a test fixture; it is now code, in `app.paper.mandate`. The strategy library moved from
`strategy-program/library/` into `app/paper/library/`, resolved by `Settings.library_dir` relative to
the *package* rather than to `REPO_ROOT`, so it travels with an install instead of needing to be
deployed alongside one. Nothing under `uat/` is read by the running application any more, and the
image no longer ships it.

*The rounds.* Round records moved from `strategy-program/rounds/` to `data/rounds/`, behind
`Settings.rounds_dir` and `INVDASH_ROUNDS_DIR`. Unlike the library -- a bounded, hand-authored,
read-only set that should travel *inside* an install -- a round is generated output that grows, and
the application writes it, so it belongs in the data directory the app already owns.

**The application now resolves nothing outside itself except `data/` and `.env`**, and the image
contains `backend/app` and nothing else. `test_every_directory_the_app_reads_is_copied_into_the_image`
is what notices if a fourth tree quietly rejoins the list.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import REPO_ROOT

DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
LAUNCH_JSON = REPO_ROOT / ".claude" / "launch.json"
APP_PACKAGE = REPO_ROOT / "backend" / "app"

#: Paths the image deliberately does not COPY, each with the reason it is legitimately absent.
#: Add to this only with a reason; an entry here is an assertion that the container works *without*
#: the path, not a way to quiet the test below.
#:
#:   data   a bind mount supplied by `docker-compose.yml` and pointed at by the `INVDASH_*`
#:          environment variables. Baking a copy into the image would ship a stale duplicate of the
#:          user's real ledger.
#:   .env   optional local configuration read by pydantic-settings, and the one file in this repo
#:          most likely to hold a provider API key. Copying it into an image is how credentials
#:          leak into a registry. Its absence is the correct behaviour: settings fall back to
#:          environment variables, which is how the container is configured.
#:   strategy-program
#:          hand-authored programme documentation, read only by `app.tournament.findings` for
#:          `DEFECTS.md`. The container works without it, which is the assertion this entry makes:
#:          `findings._read_text` returns `None` for a file it cannot find, and the findings
#:          response's `sources` list names only the files actually read -- so a reader can tell
#:          "this round recorded no defects" apart from "the defects file was not available", rather
#:          than silently seeing fewer entries. Copying the tree in would reverse the migration the
#:          comment in `backend/Dockerfile` describes, which removed `strategy-program/` precisely
#:          because the library belonged in the package and the round records belonged in `data/`.
#:          A deployment that does want defect entries mounts a copy and sets
#:          `INVDASH_DEFECTS_FILE` (`app.config.Settings.defects_file`).
#:   .backfill-tasks
#:          a git-ignored, throwaway staging folder for the manual external-agent backfill
#:          (`Settings.backfill_tasks_dir`, its own env var `INVDASH_BACKFILL_TASKS_DIR`). One
#:          Markdown task packet per un-ingested video, written by `app.personas.backfill` and read
#:          back by `app.personas.backfill_ingest`; it is created/read lazily by the `/api/backfill`
#:          endpoints, never at import, so the container starts fine without it and an empty folder
#:          simply means "no packets staged". Baking it into the image would ship stale scratch, and
#:          like `data` a deployment that uses the feature points the env var at a writable mount.
NOT_COPIED_ON_PURPOSE = {"data", ".env", "strategy-program", ".backfill-tasks"}

#: Directories the app reads that must be reachable inside the container *somehow* -- either COPYed
#: or supplied by a mount whose location the image pins with an `INVDASH_*` variable. `data` is the
#: mount; the test below checks the round records in particular, because they moved into `data/` and
#: a mount that resolves to the wrong place fails at request time rather than at startup.
ROUNDS_ENV_VAR = "INVDASH_ROUNDS_DIR"


def _repo_root_reads() -> set[str]:
    """Top-level directories `backend/app/**` resolves against the repository root at runtime.

    Matches both spellings the codebase uses -- the module constant `REPO_ROOT / "x"` and the
    settings field `settings.repo_root / "x"`. A directory reached this way must exist beside the
    application wherever it runs, which on a developer's machine is free and inside a container is
    not.
    """
    pattern = re.compile(r"""(?:REPO_ROOT|repo_root)\s*/\s*["']([^"'/]+)["']""")
    found: set[str] = set()
    for path in APP_PACKAGE.rglob("*.py"):
        found.update(pattern.findall(path.read_text(encoding="utf-8")))
    return found


class TestTheImageShipsWhatTheApplicationReads:
    def test_at_least_one_repo_root_read_is_detected(self) -> None:
        """Guard the guard: a regex that silently matches nothing would pass every test below."""
        reads = _repo_root_reads()
        assert reads, (
            "no `REPO_ROOT / \"...\"` reads found under backend/app -- the pattern in "
            "`_repo_root_reads` has stopped matching how this codebase spells them, and every "
            "assertion in this class is now vacuous"
        )

    def test_every_directory_the_app_reads_is_copied_into_the_image(self) -> None:
        text = DOCKERFILE.read_text(encoding="utf-8")
        copied = set(re.findall(r"^COPY\s+(?:--from=\S+\s+)?(\S+)\s", text, flags=re.MULTILINE))
        copied_tops = {Path(src).parts[0] for src in copied}

        missing = sorted(_repo_root_reads() - copied_tops - NOT_COPIED_ON_PURPOSE)
        assert not missing, (
            f"backend/app reads {missing} relative to REPO_ROOT, but backend/Dockerfile never "
            f"copies {'it' if len(missing) == 1 else 'them'} into the image. The container would "
            f"start and then fail on the first request that touches that path. Either COPY the "
            f"directory (and say in the comment why the application needs it), or stop reading it "
            f"from the served code."
        )

    def test_pythonpath_puts_the_copied_tree_ahead_of_the_installed_one(self) -> None:
        """`/app/backend` must be on the path, and must win over site-packages.

        The builder stage runs `pip install .`, so a second copy of `app` exists inside the
        virtualenv. `app.config.REPO_ROOT` is `Path(app/config.py).parents[2]` -- import the
        installed copy and `REPO_ROOT` resolves somewhere under `/opt/venv`, so every
        `REPO_ROOT`-relative read misses `/app/strategy-program` and the container starts fine
        and then 500s on the first request that needs a round. PYTHONPATH precedes site-packages,
        which is what makes the COPYed tree the one that actually runs. `--app-dir` would do the
        same but only for a single directory, which is why the CMD does not use it.

        This deliberately does *not* require `/app`. It was there so `uat` could be imported;
        nothing imports it now and it is no longer copied into the image.
        """
        text = DOCKERFILE.read_text(encoding="utf-8")
        match = re.search(r'PYTHONPATH="([^"]+)"', text)
        assert match is not None, "backend/Dockerfile no longer sets PYTHONPATH"
        roots = match.group(1).split(":")
        assert "/app/backend" in roots, (
            f"PYTHONPATH is {roots!r}; without /app/backend the site-packages copy of `app` wins "
            "and REPO_ROOT resolves inside the virtualenv"
        )

    def test_the_image_pins_where_the_round_records_live(self) -> None:
        """`data/rounds/` is a mount, so the image must say where it is mounted.

        The rounds left `strategy-program/` for `data/rounds/`, which means the image no longer
        copies them -- they arrive through the `/data` bind mount. `Settings.rounds_dir` defaults to
        `REPO_ROOT / "data" / "rounds"`, and `REPO_ROOT` inside the container is `/app`, so without an
        explicit override the app would look in `/app/data/rounds` while docker-compose mounts the
        host's rounds at `/data`. That mismatch produces an empty round list rather than an error --
        `GET /api/competition/rounds` answers `{"rounds": []}` for a missing directory by design --
        so it would look like a user with no rounds instead of a misconfigured image.

        `INVDASH_STORE_DIR` and `INVDASH_CACHE_DIR` are pinned for exactly the same reason; this
        asserts the third one did not get forgotten.
        """
        text = DOCKERFILE.read_text(encoding="utf-8")
        assert f"{ROUNDS_ENV_VAR}=/data/rounds" in text, (
            f"backend/Dockerfile does not pin {ROUNDS_ENV_VAR}. Without it `Settings.rounds_dir` "
            "resolves to /app/data/rounds, which nothing mounts, and every round silently disappears "
            "from /api/competition/rounds."
        )

    def test_the_cmd_does_not_reintroduce_a_single_app_dir(self) -> None:
        text = DOCKERFILE.read_text(encoding="utf-8")
        cmd = re.search(r"^CMD\s+(.+)$", text, flags=re.MULTILINE)
        assert cmd is not None, "backend/Dockerfile has no CMD"
        assert "--app-dir" not in cmd.group(1), (
            "the CMD passes --app-dir again. It takes one directory, so it can put either `app` or "
            "`uat` on the path but not both; PYTHONPATH is what carries them."
        )


class TestTheDevServerStartsFromTheRepositoryRoot:
    def test_launch_json_points_the_backend_at_the_repository_root(self) -> None:
        if not LAUNCH_JSON.exists():  # pragma: no cover - absent in a partial checkout
            pytest.skip(".claude/launch.json not present")
        config = json.loads(LAUNCH_JSON.read_text(encoding="utf-8"))
        backend = next(
            (c for c in config["configurations"] if c["name"] == "backend"),
            None,
        )
        assert backend is not None, "launch.json has no `backend` configuration"
        args = backend["runtimeArgs"]
        assert "--app-dir" in args, "the backend launch config no longer passes --app-dir"
        app_dir = args[args.index("--app-dir") + 1]
        assert app_dir == ".", (
            f"--app-dir is {app_dir!r}. It must be the repository root: `backend` leaves `uat` off "
            "the path and the server dies at import with ModuleNotFoundError."
        )


class TestTheDocumentedInvocationActuallyImports:
    def test_app_main_imports_with_only_the_repository_root_on_the_path(self) -> None:
        """The real check: a fresh interpreter, one import root, exactly as `--app-dir .` gives it.

        Deliberately *not* inheriting this process's `sys.path` -- that is the whole point. Under
        pytest both roots are present and `import app.main` cannot fail, which is why the broken
        configuration shipped. `app` resolves through its editable install; `uat` resolves through
        the repository root. If a future import in the app package reaches a third tree, this fails
        here rather than in front of a user.
        """
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)
        result = subprocess.run(
            [sys.executable, "-c", "import app.main; print(len(app.main.app.routes))"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env=env,
            timeout=180,
        )
        assert result.returncode == 0, (
            "`import app.main` failed with only the repository root on the path -- which is the "
            "path the documented uvicorn invocation and the Docker image both provide.\n\n"
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        )
        assert int(result.stdout.strip()) > 0

    def test_app_main_imports_with_only_backend_on_the_path(self) -> None:
        """The real fix, not just the workaround: `app.main` no longer needs `uat` at all.

        `app.tournament.runner` and `app.paperdesk.desk` used to import `uat.harness.marketdata`
        and `uat.harness.paperbroker` directly -- a UAT test harness reached from served application
        code. Those two modules have since moved into `app.paper`, inside the package the server
        ships, with `uat.harness.marketdata` / `uat.harness.paperbroker` left behind as re-export
        shims for callers under `uat/` and `tests/` that still ask for them by their old names.

        This test is the one the whole move exists to satisfy: `PYTHONPATH=backend` alone --
        no repository root, so `uat` is not even importable -- must be enough for `import app.main`
        to succeed. If a future change reintroduces an `app` -> `uat` import, this fails here with
        `ModuleNotFoundError: No module named 'uat'` instead of at server startup.
        """
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT / "backend")
        result = subprocess.run(
            [sys.executable, "-c", "import app.main; print(len(app.main.app.routes))"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env=env,
            timeout=180,
        )
        assert result.returncode == 0, (
            "`import app.main` failed with only `backend/` on the path -- application code still "
            "reaches into `uat`, which is exactly the layering inversion this move was meant to "
            "fix.\n\n"
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        )
        assert int(result.stdout.strip()) > 0


class TestTheShimsReExportRatherThanDuplicate:
    """`uat.harness.marketdata` and `uat.harness.paperbroker` must hand back the exact objects
    `app.paper.marketdata` and `app.paper.paperbroker` define, not redefinitions of them.

    The whole point of moving the implementation into `app.paper` and leaving a re-export behind is
    that both import paths name one object apiece. `clear_frame_cache` in particular closes over a
    single process-wide `_FRAME_CACHE` dict; if the shim reimplemented instead of re-exporting, a
    test clearing the cache through `uat.harness.marketdata` would leave the cache
    `app.paper.marketdata`'s readers actually populate untouched -- two caches, silently out of
    sync, and a failure that would look nothing like its cause. Same reasoning for `AsOfMarket`
    (identity matters for `isinstance` checks) and `PaperBroker` (constructed against an
    `AsOfMarket`; two unrelated classes would break any code, or test, comparing across the two
    import paths).
    """

    def test_marketdata_shim_is_the_same_objects(self) -> None:
        import app.paper.marketdata as real
        import uat.harness.marketdata as shim

        assert shim.clear_frame_cache is real.clear_frame_cache
        assert shim.AsOfMarket is real.AsOfMarket
        assert shim.Session is real.Session
        assert shim.SessionCalendar is real.SessionCalendar
        assert shim.UnpricedSymbol is real.UnpricedSymbol

    def test_paperbroker_shim_is_the_same_objects(self) -> None:
        import app.paper.paperbroker as real
        import uat.harness.paperbroker as shim

        assert shim.PaperBroker is real.PaperBroker
        assert shim.Mandate is real.Mandate
        assert shim.Order is real.Order
        assert shim.Fill is real.Fill
        assert shim.Rejection is real.Rejection
        assert shim.SessionResult is real.SessionResult
        assert shim.load_mandate is real.load_mandate


class TestEveryRouterModuleIsActuallyRegistered:
    """Every `APIRouter` under `app.api` must be included on the served application.

    This is the same defect class the rest of this file exists for: the suite is structurally
    incapable of noticing it. `tests/test_api_*.py` build their own `FastAPI()` and mount the router
    under test onto it directly, so a router that `app.main` never calls `include_router` on passes
    its entire test file green while answering `404` on the running server. That is not hypothetical
    -- it is how a whole feature's endpoints reached `main` untested-for-registration, and it is
    cheap to close permanently.

    The check is deliberately structural rather than a hand-maintained list of expected routers: a
    list would have to be edited by the same person who forgot the `include_router` line, which is
    the failure it is meant to catch. Instead it enumerates the package and asserts that every module
    exposing a `router` contributes at least one path to `app.main.app`.

    A module that deliberately ships an unmounted router should be named in `_UNMOUNTED` below with a
    comment saying why -- an explicit exemption a reviewer can see, rather than a silent absence.
    """

    #: Modules under `app.api` that expose a `router` which `app.main` intentionally does not mount.
    #: Empty today. Add a name here only with a reason, never to make this test pass.
    _UNMOUNTED: frozenset[str] = frozenset()

    @staticmethod
    def _included_routers(served: object) -> set[int]:
        """Every `APIRouter` object reachable from the served app, by `id()`.

        FastAPI does not flatten an `include_router` call into plain `Route` objects in every
        version -- the one pinned here keeps a private `_IncludedRouter` wrapper holding an
        `original_router` reference. Comparing paths is therefore version-dependent in a way that
        would make this test quietly stop checking anything after an upgrade. Object identity is
        not: whatever the container looks like, the router that was included is the router the
        module defines. The walk below handles both shapes and recurses through nested includes.
        """
        seen: set[int] = set()

        def walk(routes: object) -> None:
            for route in routes or ():  # type: ignore[union-attr]
                inner = getattr(route, "original_router", None)
                if inner is not None:
                    seen.add(id(inner))
                    walk(getattr(inner, "routes", ()))
                nested = getattr(route, "routes", None)
                if nested is not None and inner is None:
                    walk(nested)

        walk(getattr(served, "routes", ()))
        return seen

    def test_every_api_module_with_a_router_is_included_on_the_served_app(self) -> None:
        import importlib
        import pkgutil

        import app.api
        from app.main import app as served

        included = self._included_routers(served)
        assert included, (
            "walked app.main.app and found no included routers at all -- this test's traversal has "
            "stopped matching FastAPI's route container and is no longer checking anything"
        )

        missing: list[str] = []
        for info in pkgutil.iter_modules(app.api.__path__):
            if info.name.startswith("_") or info.name in self._UNMOUNTED:
                continue
            module = importlib.import_module(f"app.api.{info.name}")
            router = getattr(module, "router", None)
            if router is None:
                continue
            if id(router) not in included:
                missing.append(f"app.api.{info.name}")

        assert not missing, (
            "these api modules define a router that app.main never includes, so their endpoints "
            "answer 404 on the running server while their own tests pass: " + ", ".join(sorted(missing))
        )
