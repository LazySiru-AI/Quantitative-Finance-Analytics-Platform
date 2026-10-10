"""Moved to `app.paper.marketdata`. Kept as a re-export so UAT callers are unchanged.

This module used to be the real implementation: an as-of-clamped view of the application's own
daily bar store, built for the UAT harness and living entirely under `uat/`, outside the served
application. That stopped being true the day `app.tournament.runner` started importing it -- first
to run backtest cards, and then, once `/api/paperdesk` and `/api/competition/jobs` made
`app.tournament` reachable from the web app, as code the *server* imports at startup.

That reachability is the whole problem. Application code cannot import from a test harness: a UAT
harness lives outside `backend/`, and anything that puts only `backend/` on `sys.path` --
`uvicorn app.main:app --app-dir backend`, or the Docker image, which `COPY`s `backend/app` and
nothing else -- cannot resolve `import uat.harness.marketdata` at all. `import app.main` failed
with `ModuleNotFoundError: No module named 'uat'` under exactly that invocation, and the pytest
suite never caught it because `pytest.ini` puts both the repository root and `backend` on
`pythonpath`, so every test always had `uat` importable regardless of what the server actually
needs.

The fix is to recognize these modules for what they had become -- application code, not test
harness code -- and move them into `app.paper`, inside the package the server actually ships. This
file stays behind as a thin re-export purely so nothing under `uat/` (in particular `uat.harness.run`,
`uat.harness.ingest`, and their own tests) has to change a single import line; they keep asking for
`uat.harness.marketdata` and keep getting the same objects back, now sourced from `app.paper.marketdata`.

The re-export below is by name, not `import *`, so this file's surface is exactly `__all__` and
`ruff` (which has `F401`/`F403` in scope for this repository) has something concrete to check
against. Each name here must be the *same object* `app.paper.marketdata` defines -- `clear_frame_cache`
in particular closes over the one process-wide `_FRAME_CACHE` dict, and a caller clearing the cache
through this module must clear the exact cache that `app.paper.marketdata`'s readers populate.
A plain `from ... import name` gives that by construction; redefining or wrapping any of these names
here would silently split the cache in two and reintroduce the lookahead risk the module exists to
prevent, in a way no test importing only one of the two paths would ever notice.
"""

from __future__ import annotations

from app.paper.marketdata import (
    AsOfMarket,
    Session,
    SessionCalendar,
    UnpricedSymbol,
    clear_frame_cache,
)

__all__ = ["AsOfMarket", "Session", "SessionCalendar", "UnpricedSymbol", "clear_frame_cache"]
