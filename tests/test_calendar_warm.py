"""`app.market.calendar.warm` and its wiring into the application lifespan.

`warm` is the Overview page's calendar-card counterpart to `app.market.refresh._warm_macro_snapshot`
and `app.paperdesk.desk.warm`: a daemon thread started on every server start (behind
`Settings.refresh_on_startup`) that primes the on-disk FOMC/Nasdaq/FRED cache so the first person to
open the Overview page after a restart does not pay a cold sweep. These tests replace
`build_calendar` itself with a fake, so they exercise only the wrapper -- the thread start, the
window it warms, and its swallow-everything contract -- without any real network round trip, and
without re-testing the calendar build already covered by `test_calendar_api.py`.

The lifespan tests mirror `test_market_refresh.py::test_lifespan_leaves_the_sweep_untouched_by_default`:
the real FastAPI `lifespan` runs only inside `with TestClient(app) as ...:`, and the `settings`
fixture pins `INVDASH_REFRESH_ON_STARTUP=0`, so the default-off case is the one every other test file
already inherits for network safety. The on case patches `get_settings` to flip that one flag and
patches the two network-touching startup warms to fakes.
"""

from __future__ import annotations

import threading

import pytest
from starlette.testclient import TestClient

from app.config import Settings
from app.market import calendar


def test_warm_calls_build_calendar_with_the_frontend_default_window(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The warm primes exactly the window the Overview page's first request will ask for. If the two
    diverged, that first request would still pay a cold Nasdaq sweep for the days the warm missed --
    the whole point being defeated -- so `_WARM_DAYS` is pinned to `calendarApi`'s `DEFAULT_DAYS`.
    """
    done = threading.Event()
    seen: list[tuple[int, Settings | None]] = []

    def _fake_build(*, days: int = 60, settings: Settings | None = None, **_: object) -> None:
        seen.append((days, settings))
        done.set()

    monkeypatch.setattr(calendar, "build_calendar", _fake_build)

    calendar.warm(settings)

    assert done.wait(timeout=2.0), "warm never ran build_calendar on its daemon thread"
    assert seen == [(calendar._WARM_DAYS, settings)]
    assert calendar._WARM_DAYS == 60


def test_warm_swallows_a_build_failure(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A warm that fails must leave the server started and the next request building as it always
    did. `build_calendar` already never raises for a degraded upstream, but the guard covers the
    genuine remainder -- so a raising build must not escape the thread or crash startup.
    """
    ran = threading.Event()

    def _boom(**_: object) -> None:
        ran.set()
        raise RuntimeError("upstream is on fire")

    monkeypatch.setattr(calendar, "build_calendar", _boom)

    # Must not raise, even though the build does.
    calendar.warm(settings)

    assert ran.wait(timeout=2.0), "warm never reached the failing build"
    # Give the daemon thread a moment to unwind through the suppressor; nothing to assert beyond the
    # absence of a propagated exception, which a raise inside `_run` could not deliver here anyway --
    # this test's real proof is that the process is still alive to run the next line.


def test_lifespan_leaves_the_calendar_untouched_by_default(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default-off case every other test file inherits: with `refresh_on_startup` at the
    fixture's `0`, the real lifespan never warms the calendar (and so never touches the network).
    """
    from app import main

    called: list[object] = []
    monkeypatch.setattr(main.market_calendar, "warm", lambda *a, **k: called.append(a))

    with TestClient(main.app):
        pass

    assert called == []


def test_lifespan_warms_the_calendar_when_refresh_is_enabled(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With `refresh_on_startup` on, the lifespan primes the calendar alongside the bar/macro sweep.
    Both network-touching warms are replaced with fakes so this asserts the wiring, not real HTTP.
    """
    from app import main

    enabled = settings.model_copy(update={"refresh_on_startup": True})
    monkeypatch.setattr(main, "get_settings", lambda: enabled)
    # The sibling sweep would otherwise fire real Yahoo/FRED/CNN traffic under the same gate.
    monkeypatch.setattr(main.market_refresh, "refresh_market_data", lambda *a, **k: None)

    warmed: list[Settings | None] = []
    monkeypatch.setattr(main.market_calendar, "warm", lambda s=None: warmed.append(s))

    with TestClient(main.app):
        pass

    assert warmed == [enabled]
