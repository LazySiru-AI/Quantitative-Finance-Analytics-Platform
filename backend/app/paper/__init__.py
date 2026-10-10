"""As-of market data and a paper broker: application code, not a UAT harness.

This package used to be `uat.harness.marketdata` and `uat.harness.paperbroker`, living outside
`backend/` under the repository's UAT tooling. It moved here because `app.tournament` and
`app.paperdesk` -- both served by the FastAPI app -- came to depend on it, and served application
code cannot import a test harness: `uvicorn --app-dir backend` (and the Docker image, which copies
only `backend/app`) puts nothing but `backend/` on `sys.path`, so `import uat.harness.marketdata`
from inside `app.tournament.runner` failed with `ModuleNotFoundError` the moment that reachability
happened, even though the test suite -- which always has both the repository root and `backend` on
`pythonpath` -- never saw it fail.

`uat.harness.marketdata` and `uat.harness.paperbroker` still exist, as thin re-export shims over
this package, so every UAT caller (`uat.harness.run`, `uat.harness.ingest`, and their tests) keeps
its import path unchanged. See those shim modules' docstrings for why a re-export and not a copy.
"""

from __future__ import annotations
