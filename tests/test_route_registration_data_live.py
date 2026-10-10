"""Route registration on the *real* app for the two routers added by the 2026-09-08 refetch work.

Both `tests/test_data_freshness.py` and `tests/test_api_live_decisions.py` deliberately build their
own `FastAPI()` around the router under test, which is exactly the shape that once let a missing
`include_router` in `app.main` pass every test (see `tests/test_api_paperlive.py`'s own note). This
file is the one assertion that goes through `app.main.app`. `app.openapi()["paths"]` rather than
`app.routes`: the latter gives a false negative on FastAPI 0.141.
"""

from __future__ import annotations

from app.main import app


def test_data_admin_routes_are_registered_on_the_real_app() -> None:
    paths = app.openapi()["paths"]
    assert "post" in paths["/api/market/refresh"]
    assert "get" in paths["/api/market/refresh/status"]
    assert "get" in paths["/api/data/freshness"]


def test_live_decision_routes_are_registered_on_the_real_app() -> None:
    paths = app.openapi()["paths"]
    assert "get" in paths["/api/agentdesk/live/status"]
    assert "get" in paths["/api/agentdesk/live/decisions"]
    assert "post" in paths["/api/agentdesk/live/decide"]
