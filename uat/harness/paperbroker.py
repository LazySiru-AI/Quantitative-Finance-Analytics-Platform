"""Moved to `app.paper.paperbroker`. Kept as a re-export so UAT callers are unchanged.

This module used to be the real implementation of the paper broker the UAT harness plays against --
notional cash, real prices, hard mandate limits -- and it lived entirely under `uat/`, outside the
served application, because nothing but `uat.harness.run` ever called it. That changed once
`app.tournament.runner` (driving backtest cards) and, through it, `app.paperdesk.desk` and
`app.tournament.jobs` (both reachable from the FastAPI app via `/api/paperdesk` and
`/api/competition/jobs`) started importing it too. At that point this was no longer a harness
internal; it was application code that happened to live in the wrong tree.

The practical failure: a UAT harness lives outside `backend/`, so any launcher that puts only
`backend/` on `sys.path` -- `uvicorn app.main:app --app-dir backend`, or the Docker image, which
`COPY`s `backend/app` and nothing else -- cannot resolve `import uat.harness.paperbroker` at all.
`import app.main` died with `ModuleNotFoundError: No module named 'uat'` under that invocation, and
the test suite never noticed because `pytest.ini` always puts both the repository root and
`backend` on `pythonpath`, giving every test an importable `uat` regardless of what the served
application actually needs at runtime.

The fix is to move the real implementation into `app.paper`, inside the package the server ships,
and leave this file behind as a thin re-export so nothing under `uat/` -- `uat.harness.run`,
`uat.harness.ingest`, and their tests -- has to change an import line. They keep asking for
`uat.harness.paperbroker` and keep getting back the same classes, now sourced from
`app.paper.paperbroker`.

The re-export is by name, not `import *`, so this file's surface is exactly `__all__` and `ruff`
(which has `F401`/`F403` in scope here) has something concrete to check. Each name must be the
*same object* `app.paper.paperbroker` defines, not a redefinition: `PaperBroker` in particular is
constructed against an `app.paper.marketdata.AsOfMarket`, and a caller importing `PaperBroker` from
here must get the identical class a caller importing it from `app.paper.paperbroker` would, or code
doing `isinstance` checks (or tests asserting shim identity) across the two import paths would see
two unrelated classes instead of one.
"""

from __future__ import annotations

from app.paper.paperbroker import (
    Fill,
    Mandate,
    Order,
    PaperBroker,
    Rejection,
    SessionResult,
    load_mandate,
    summarize,  # noqa: F401
)

__all__ = ["Fill", "Mandate", "Order", "PaperBroker", "Rejection", "SessionResult", "load_mandate"]

#: `summarize` is deliberately outside `__all__`, matching `app.paper.paperbroker` itself -- it is a
#: plain module-level function (no leading underscore) that `tests/test_uat_harness.py` imports by
#: name directly, but it was never part of the curated `__all__` surface either before or after this
#: module moved. Importing it explicitly here, rather than via `import *`, keeps that caller working
#: without widening what `import *` from this module would pull in.
