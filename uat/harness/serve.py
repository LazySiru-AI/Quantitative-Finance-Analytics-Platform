"""Serve the application against a UAT sandbox, on its own port.

A developer machine usually already has the real backend running on 8000 against the real ledger.
Repointing that one at a sandbox would be the obvious thing to do and is the wrong thing to do: the
persona would be one restart away from browsing the user's actual brokerage history, and the user
would be one restart away from finding synthetic trades in their portfolio. So this starts a
*second* instance on its own port, against its own store, and touches nothing the first one uses.

It also, since ``--sandbox`` was added, has to keep three-plus persona runs from seeing each other's
data: runs replaying different calendar windows each get their own ``uat/sandbox/<name>/`` (see
``uat.harness.ingest.sandbox_settings``), and this process must serve exactly one of them per
invocation -- three parallel ``serve`` processes on three ports, each pinned to its own sandbox by
this flag.

The redirection is by environment variable rather than by passing a ``Settings`` object because
``app.config.get_settings`` is an ``lru_cache``d process-wide singleton read from ``INVDASH_*`` --
setting the variables before anything calls it is the only interception point that catches every
caller, including the ones that reach for settings at module scope. Importing
``uat.harness.ingest`` up front to compute the target paths is safe ahead of that: nothing it pulls
in calls ``get_settings()`` at import time (only inside function bodies, with an explicit ``settings``
usually already in hand) -- only ``app.main``, imported by name string inside ``uvicorn.run`` below,
touches it eagerly, and by then the environment is already set.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_HARNESS = Path(__file__).resolve().parent
_UAT = _HARNESS.parent
_REPO = _UAT.parent
for _path in (_REPO / "backend", _REPO):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from uat.harness.ingest import sandbox_settings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="uat.harness.serve")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--sandbox",
        default="sandbox",
        help="name under uat/sandbox/ to serve; must already exist (see `run.py init --sandbox`)",
    )
    parser.add_argument(
        "--auth",
        action="store_true",
        help=(
            "leave authentication ON for this sandbox instance instead of the default off; use "
            "this to deliberately exercise the real login flow"
        ),
    )
    args = parser.parse_args(argv)

    requested = sandbox_settings(_REPO, name=args.sandbox)

    # Set before calling get_settings(). See the module docstring.
    os.environ["INVDASH_REPO_ROOT"] = str(_REPO)
    os.environ["INVDASH_DATA_DIR"] = str(requested.data_dir)
    os.environ["INVDASH_STORE_DIR"] = str(requested.store_dir)
    os.environ["INVDASH_CACHE_DIR"] = str(requested.cache_dir)
    # app.auth.gate.AuthGateMiddleware 401s every path except /api/health and the auth
    # endpoints themselves, and an instance with zero users (which every fresh sandbox is) is
    # therefore fully locked. That gate protects a real ledger from an unauthenticated caller;
    # a sandbox holds only synthetic data seeded by uat.harness.ingest, binds loopback only, and
    # is driven by an automated persona, not a person who can type a password into a login
    # screen. Leaving the gate on here would just stop the persona's browser at that screen and
    # fail the whole run, for no protection anything actually needs -- so auth defaults off for
    # sandbox instances. Pass --auth when the run is deliberately about testing the login flow
    # itself. This only ever touches the sandbox process this script starts; the real backend on
    # port 8000 is untouched and stays gated by its own default.
    os.environ["INVDASH_AUTH_ENABLED"] = "1" if args.auth else "0"

    import uvicorn

    from app.config import get_settings

    settings = get_settings()
    if settings.store_dir != requested.store_dir:  # pragma: no cover - defensive
        raise SystemExit(
            f"refusing to start: settings resolved store_dir to {settings.store_dir}, not the "
            f"requested sandbox {args.sandbox!r} ({requested.store_dir}). A stale .env or an "
            f"already-imported app.config would explain it."
        )

    print(
        f"UAT backend on http://{args.host}:{args.port}  sandbox={args.sandbox}  "
        f"ledger={settings.ledger_path}"
    )
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
