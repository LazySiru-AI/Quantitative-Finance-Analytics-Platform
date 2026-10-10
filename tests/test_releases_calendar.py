"""Tests for `app.market.releases` -- the economic-release half of the Overview calendar.

Every test drives the module through a fake `httpx.Client` built over `httpx.MockTransport`, so
nothing here touches FRED. The fixtures are hand-written rather than captured because the endpoint's
response shape is two fields deep (`{"release_dates": [{"release_id": ..., "date": ...}]}`) and a
captured file would mostly be realtime metadata this module never reads.

The contract under test is the one `app.market.calendar` depends on and states in its own module
docstring: **this function never raises.** Every failure -- no key, a dead endpoint, a rejected key,
a response whose shape changed, one unparseable row -- must come back as warnings plus whatever did
parse, because the alternative is that a FRED outage costs a reader the FOMC date and their own
earnings dates too.
"""

from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest

from app.config import Settings
from app.market.calendar_models import EventConfidence, EventKind, EventSource, SessionTiming
from app.market.releases import RELEASES, release_events

START = dt.date(2026, 8, 26)
END = dt.date(2026, 10, 25)

#: Every release id the module asks about, so a handler can answer per release.
_IDS = tuple(release.release_id for release in RELEASES)

#: `app.market.releases.RELEASES` ids, by title, for tests that name a specific release.
_ID_BY_TITLE = {release.title: release.release_id for release in RELEASES}
_PCE_ID = next(rid for title, rid in _ID_BY_TITLE.items() if title.startswith("PCE"))
_CPI_ID = _ID_BY_TITLE["CPI"]


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _dates_response(release_id: int, days: list[str]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "realtime_start": START.isoformat(),
            "realtime_end": END.isoformat(),
            "release_dates": [{"release_id": release_id, "date": day} for day in days],
        },
    )


def _keyed(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """A settings object with a FRED key. The suite's own `settings` fixture has none (see
    `tests/conftest.py`'s `_detach_dotenv`), which is itself one of the cases tested below."""
    monkeypatch.setenv("INVDASH_FRED_API_KEY", "test-key")
    from app.config import get_settings

    get_settings.cache_clear()
    return get_settings()


# ---------------------------------------------------------------------------
# 1. The happy path
# ---------------------------------------------------------------------------


class TestScheduledReleases:
    def test_every_configured_release_is_asked_for_and_becomes_an_event(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = _keyed(settings, monkeypatch)
        asked: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            release_id = int(request.url.params["release_id"])
            asked.append(release_id)
            return _dates_response(release_id, ["2026-09-15"])

        events, warnings = release_events(
            start=START, end=END, settings=cfg, client=_client(handler)
        )

        assert sorted(asked) == sorted(_IDS), "one request per configured release, no more, no less"
        assert len(events) == len(RELEASES)
        assert warnings == ()
        assert {e.kind for e in events} == {EventKind.ECONOMIC_RELEASE}
        assert {e.source for e in events} == {EventSource.FRED}

    def test_a_release_date_is_confirmed_before_the_open_and_carries_no_symbol(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """These come from the agencies' own published schedules, not a vendor's extrapolation, so
        `CONFIRMED` is a claim about the upstream rather than a default. Every release named in
        `RELEASES` is issued at 08:30 ET, which is `BEFORE_OPEN`; the endpoint carries no time of
        day at all, so this is the module's own knowledge, and it has to be right."""
        cfg = _keyed(settings, monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            release_id = int(request.url.params["release_id"])
            days = ["2026-08-26"] if release_id == _PCE_ID else []
            return _dates_response(release_id, days)

        events, _ = release_events(start=START, end=END, settings=cfg, client=_client(handler))

        [pce] = events
        assert pce.date == dt.date(2026, 8, 26)
        assert pce.title.startswith("PCE inflation")
        assert pce.confidence is EventConfidence.CONFIRMED
        assert pce.timing is SessionTiming.BEFORE_OPEN
        assert pce.symbol is None
        assert pce.detail and "BEA" in pce.detail

    def test_forward_dated_rows_are_requested_explicitly(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`include_release_dates_with_no_data=true` is what makes this a calendar rather than a
        history: without it FRED answers only with dates that already carry an observation, which by
        construction excludes every release that has not happened yet. Losing this parameter would
        empty the forward half of the card while every test that only checked shapes stayed green."""
        cfg = _keyed(settings, monkeypatch)
        seen: list[httpx.URL] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url)
            return _dates_response(int(request.url.params["release_id"]), [])

        release_events(start=START, end=END, settings=cfg, client=_client(handler))

        for url in seen:
            assert url.params["include_release_dates_with_no_data"] == "true"
            assert url.params["realtime_start"] == START.isoformat()
            assert url.params["realtime_end"] == END.isoformat()

    def test_dates_outside_the_window_are_dropped(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The endpoint is asked for the window, but the window is also enforced here -- a `realtime`
        range is not quite a publication-date range upstream, and a calendar that quietly showed a
        date outside the span it advertises is the defect the `start`/`end` fields exist to rule
        out."""
        cfg = _keyed(settings, monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            release_id = int(request.url.params["release_id"])
            if release_id != _CPI_ID:
                return _dates_response(release_id, [])
            return _dates_response(release_id, ["2026-08-11", "2026-09-11", "2026-12-10"])

        events, _ = release_events(start=START, end=END, settings=cfg, client=_client(handler))

        assert [e.date for e in events] == [dt.date(2026, 9, 11)]

    def test_events_are_sorted_by_date_then_title(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GDP and PCE genuinely land on the same morning every quarter, so the same-day tiebreak is
        an ordinary case, not a hypothetical."""
        cfg = _keyed(settings, monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            return _dates_response(int(request.url.params["release_id"]), ["2026-09-30"])

        events, _ = release_events(start=START, end=END, settings=cfg, client=_client(handler))

        assert [e.title for e in events] == sorted(e.title for e in events)


# ---------------------------------------------------------------------------
# 2. Degrading -- never raising
# ---------------------------------------------------------------------------


class TestDegradation:
    def test_no_api_key_yields_a_named_warning_and_no_events(self, settings: Settings) -> None:
        """FRED has no keyless equivalent of the release schedule, so the honest answer is "no rows,
        and here is why" -- never a guessed date derived from "the last Friday of the month"."""
        events, warnings = release_events(start=START, end=END, settings=settings)

        assert events == ()
        assert [w.kind for w in warnings] == ["config"]
        assert "INVDASH_FRED_API_KEY" in warnings[0].message

    def test_no_api_key_makes_no_request_at_all(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return _dates_response(0, [])

        release_events(start=START, end=END, settings=settings, client=_client(handler))

        assert calls == []

    def test_one_failing_release_costs_only_its_own_rows(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The rule this module exists to keep: a rejected key or a 500 on one release must not take
        the other five with it, and the warning must name which one went missing."""
        cfg = _keyed(settings, monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            release_id = int(request.url.params["release_id"])
            if release_id == _CPI_ID:
                return httpx.Response(500, text="upstream error")
            return _dates_response(release_id, ["2026-09-15"])

        events, warnings = release_events(
            start=START, end=END, settings=cfg, client=_client(handler)
        )

        assert len(events) == len(RELEASES) - 1
        assert "CPI" not in {e.title for e in events}
        assert [w.kind for w in warnings] == ["provider_fallback"]
        assert "CPI" in warnings[0].message

    def test_a_transport_error_is_contained(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = _keyed(settings, monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host", request=request)

        events, warnings = release_events(
            start=START, end=END, settings=cfg, client=_client(handler)
        )

        assert events == ()
        assert len(warnings) == len(RELEASES)
        assert {w.kind for w in warnings} == {"provider_fallback"}

    def test_a_response_that_is_not_json_is_contained(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FRED answering with an HTML error page, or a proxy interposing one, must not raise a
        `JSONDecodeError` out of a function the calendar calls without a try block."""
        cfg = _keyed(settings, monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>maintenance</html>")

        events, warnings = release_events(
            start=START, end=END, settings=cfg, client=_client(handler)
        )

        assert events == ()
        assert {w.kind for w in warnings} == {"provider_fallback"}

    def test_a_missing_release_dates_array_is_contained(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = _keyed(settings, monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=json.dumps({"count": 0}))

        events, warnings = release_events(
            start=START, end=END, settings=cfg, client=_client(handler)
        )

        assert events == ()
        assert {w.kind for w in warnings} == {"provider_fallback"}

    def test_one_unparseable_row_does_not_discard_its_siblings(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Five good dates are worth more than a warning about the sixth -- the same trade
        `app.paperdesk.fetch` makes per symbol."""
        cfg = _keyed(settings, monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            release_id = int(request.url.params["release_id"])
            if release_id != _CPI_ID:
                return _dates_response(release_id, [])
            return httpx.Response(
                200,
                json={
                    "release_dates": [
                        {"release_id": release_id, "date": "not-a-date"},
                        {"release_id": release_id, "date": "2026-09-11"},
                        {"release_id": release_id},
                    ]
                },
            )

        events, warnings = release_events(
            start=START, end=END, settings=cfg, client=_client(handler)
        )

        assert [e.date for e in events] == [dt.date(2026, 9, 11)]
        assert warnings == ()


# ---------------------------------------------------------------------------
# 3. What is on the list, and what is deliberately not
# ---------------------------------------------------------------------------


class TestReleaseRoster:
    def test_pce_cpi_jobs_and_gdp_are_all_carried(self) -> None:
        titles = " | ".join(release.title for release in RELEASES)
        for expected in ("PCE", "CPI", "Employment Situation", "GDP", "PPI", "Retail sales"):
            assert expected in titles

    def test_weekly_jobless_claims_are_not_carried(self) -> None:
        """Deliberate, and documented in the module docstring: nine rows in a 60-day window would
        make two thirds of the calendar one repeating entry and bury the FOMC meeting and the two
        inflation prints a reader came for. Release 180 is the weekly claims report."""
        assert 180 not in {release.release_id for release in RELEASES}

    def test_every_release_id_is_distinct(self) -> None:
        ids = [release.release_id for release in RELEASES]
        assert len(set(ids)) == len(ids)
