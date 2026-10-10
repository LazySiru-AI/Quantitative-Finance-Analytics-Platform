"""Tests for the FOMC calendar source (`app.market.fomc`).

Fixture-driven wherever possible -- `tests/fixtures/market/fomc_calendars.html` is a trimmed, real
capture of the live Fed page (see that file's own header comment), so the parsing tests here exercise
the actual DOM shapes the live page produces rather than a synthetic approximation of them. The one
exception is the December/January year-rollover case: the Fed has never published one inside the
window this fixture covers, so that case is driven from a small hand-built HTML string that mimics
the real markup shape instead.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx

from app.market.calendar_models import (
    CalendarEvent,
    EventConfidence,
    EventKind,
    EventSource,
    SessionTiming,
)
from app.market.fomc import (
    ScheduleRefresh,
    _load_bundled_schedule,
    _load_bundled_schedule_from,
    _main,
    _parse_meetings,
    fomc_events,
    refresh_bundled_schedule,
)
from app.market.models import MarketWarning

FIXTURE = Path(__file__).parent / "fixtures" / "market" / "fomc_calendars.html"

#: The exact 2026 schedule the live Fed page carried as of 2026-08-25 (also the brief's own probe
#: output) -- `(date, end_date, has_projections)`.
EXPECTED_2026 = [
    (dt.date(2026, 1, 27), dt.date(2026, 1, 28), False),
    (dt.date(2026, 3, 17), dt.date(2026, 3, 18), True),
    (dt.date(2026, 4, 28), dt.date(2026, 4, 29), False),
    (dt.date(2026, 6, 16), dt.date(2026, 6, 17), True),
    (dt.date(2026, 7, 28), dt.date(2026, 7, 29), False),
    (dt.date(2026, 9, 15), dt.date(2026, 9, 16), True),
    (dt.date(2026, 10, 27), dt.date(2026, 10, 28), False),
    (dt.date(2026, 12, 8), dt.date(2026, 12, 9), True),
]


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _client_serving_fixture() -> httpx.Client:
    html = FIXTURE.read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    return _mock_client(handler)


def _client_raising(exc: Exception) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return _mock_client(handler)


# ---------------------------------------------------------------------------
# 1. Parsing the fixture yields the exact 2026 meeting list.
# ---------------------------------------------------------------------------


def test_parses_exact_2026_meeting_dates_from_fixture() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    meetings = _parse_meetings(html)

    meetings_2026 = [m for m in meetings if m.date.year == 2026]
    actual = [(m.date, m.end_date, m.projections) for m in meetings_2026]

    assert actual == EXPECTED_2026


def test_fomc_events_returns_exact_2026_meetings_via_live_fetch() -> None:
    client = _client_serving_fixture()
    events, warnings = fomc_events(start=dt.date(2026, 1, 1), end=dt.date(2026, 12, 31), client=client)

    assert warnings == ()
    actual = [(e.date, e.end_date, e.detail == "press conference and projections") for e in events]
    assert actual == EXPECTED_2026
    assert all(e.source == EventSource.FEDERAL_RESERVE for e in events)
    assert all(e.kind == EventKind.FOMC for e in events)
    assert all(e.confidence == EventConfidence.CONFIRMED for e in events)
    assert all(e.timing == SessionTiming.DURING_SESSION for e in events)
    assert all(e.symbol is None for e in events)


# ---------------------------------------------------------------------------
# 2. A cross-month meeting ("Apr/May" + "30-1") spans the month boundary correctly.
# ---------------------------------------------------------------------------


def test_cross_month_meeting_spans_the_month_boundary() -> None:
    """The real 2024 "Apr/May" / "30-1" markup, from the fixture's 2024 section."""
    html = FIXTURE.read_text(encoding="utf-8")
    meetings = _parse_meetings(html)

    april_may = next(m for m in meetings if m.date == dt.date(2024, 4, 30))
    assert april_may.end_date == dt.date(2024, 5, 1)
    assert april_may.projections is False


def test_december_january_meeting_rolls_the_year() -> None:
    """No real Dec/Jan meeting exists in the fixture's window, so this drives a small synthetic
    block matching the real markup shape (see this file's module docstring)."""
    html = """
    <div class="panel-heading"><h4><a id="year-2028">2028 FOMC Meetings</a></h4></div>
    <div class="row fomc-meeting" ">
        <div class="fomc-meeting__month col-xs-5 col-sm-3 col-md-2"><strong>Dec/Jan</strong></div>
        <div class="fomc-meeting__date col-xs-4 col-sm-9 col-md-10 col-lg-1">31-1*</div>
    </div>
    """
    meetings = _parse_meetings(html)

    assert len(meetings) == 1
    meeting = meetings[0]
    assert meeting.date == dt.date(2028, 12, 31)
    assert meeting.end_date == dt.date(2029, 1, 1)
    assert meeting.projections is True


# ---------------------------------------------------------------------------
# 3. The "*" marker maps to the projections detail string; its absence maps to None.
# ---------------------------------------------------------------------------


def test_star_marker_maps_to_projections_detail() -> None:
    client = _client_serving_fixture()
    events, _ = fomc_events(start=dt.date(2026, 1, 1), end=dt.date(2026, 12, 31), client=client)

    by_date = {e.date: e for e in events}
    assert by_date[dt.date(2026, 3, 17)].detail == "press conference and projections"
    assert by_date[dt.date(2026, 1, 27)].detail is None


# ---------------------------------------------------------------------------
# 4. A network failure falls back to the bundled snapshot and warns, without raising.
# ---------------------------------------------------------------------------


def test_network_failure_falls_back_to_bundled_snapshot() -> None:
    client = _client_raising(httpx.ConnectError("connection refused"))

    events, warnings = fomc_events(start=dt.date(2026, 1, 1), end=dt.date(2026, 12, 31), client=client)

    assert events, "the bundled snapshot should still cover 2026"
    assert all(e.source == EventSource.BUNDLED_SCHEDULE for e in events)
    fallback_warnings = [w for w in warnings if w.kind == "provider_fallback"]
    assert len(fallback_warnings) == 1
    assert "federalreserve.gov" in fallback_warnings[0].message or "FOMC" in fallback_warnings[0].message


def test_network_failure_never_raises_for_various_transport_errors() -> None:
    for exc in (
        httpx.ConnectError("refused"),
        httpx.ConnectTimeout("timed out"),
        httpx.ReadTimeout("timed out"),
    ):
        client = _client_raising(exc)
        events, warnings = fomc_events(start=dt.date(2026, 1, 1), end=dt.date(2026, 12, 31), client=client)
        assert isinstance(events, tuple)
        assert isinstance(warnings, tuple)
        assert any(w.kind == "provider_fallback" for w in warnings)


def test_non_200_status_falls_back_to_bundled_snapshot() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    client = _mock_client(handler)
    events, warnings = fomc_events(start=dt.date(2026, 1, 1), end=dt.date(2026, 12, 31), client=client)

    assert all(e.source == EventSource.BUNDLED_SCHEDULE for e in events)
    assert any(w.kind == "provider_fallback" for w in warnings)


def test_unparseable_page_falls_back_to_bundled_snapshot() -> None:
    """A page with no 'YYYY FOMC Meetings' section at all -- e.g. the Fed restructured the page --
    must degrade the same way a network failure does, not report an empty calendar."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>nothing recognisable here</body></html>")

    client = _mock_client(handler)
    events, warnings = fomc_events(start=dt.date(2026, 1, 1), end=dt.date(2026, 12, 31), client=client)

    assert all(e.source == EventSource.BUNDLED_SCHEDULE for e in events)
    assert any(w.kind == "provider_fallback" for w in warnings)


# ---------------------------------------------------------------------------
# 5. A start date past the end of the bundled schedule yields zero events + a stale warning.
# ---------------------------------------------------------------------------


def test_start_past_bundled_schedule_end_yields_stale_warning() -> None:
    client = _client_raising(httpx.ConnectError("connection refused"))

    far_future_start = dt.date(2030, 1, 1)
    events, warnings = fomc_events(start=far_future_start, end=dt.date(2030, 12, 31), client=client)

    assert events == ()
    stale_warnings = [w for w in warnings if w.kind == "stale"]
    assert len(stale_warnings) == 1
    # Last known meeting in the bundled snapshot is 2027-12-08 (see data/calendar/fomc_schedule.json).
    last_known = _load_bundled_schedule()
    expected_last = max(m.last_day for m in last_known)
    assert expected_last.isoformat() in stale_warnings[0].message


def test_bundled_schedule_file_has_entries_at_or_after_today() -> None:
    """Sanity check on the committed snapshot itself: it must not already be exhausted, or every
    other test relying on it (and the real feature) silently degrades to an empty calendar."""
    meetings = _load_bundled_schedule()
    assert meetings, "data/calendar/fomc_schedule.json must not be empty"
    assert max(m.last_day for m in meetings) >= dt.date(2026, 8, 25)


# ---------------------------------------------------------------------------
# 6. Window filtering is inclusive at both ends.
# ---------------------------------------------------------------------------


def test_window_filtering_is_inclusive_at_the_start_date() -> None:
    client = _client_serving_fixture()
    events, _ = fomc_events(start=dt.date(2026, 1, 27), end=dt.date(2026, 12, 31), client=client)
    assert events[0].date == dt.date(2026, 1, 27)


def test_window_filtering_is_inclusive_at_the_end_date() -> None:
    """The window's end date lands on a meeting's *end_date*, not its start -- still included."""
    client = _client_serving_fixture()
    events, _ = fomc_events(start=dt.date(2026, 1, 1), end=dt.date(2026, 1, 28), client=client)
    assert len(events) == 1
    assert events[0].date == dt.date(2026, 1, 27)
    assert events[0].end_date == dt.date(2026, 1, 28)


def test_window_excludes_a_meeting_one_day_outside_either_end() -> None:
    client = _client_serving_fixture()
    events, _ = fomc_events(start=dt.date(2026, 1, 29), end=dt.date(2026, 3, 16), client=client)
    assert events == ()


def test_window_spanning_years_returns_meetings_from_both() -> None:
    client = _client_serving_fixture()
    events, _ = fomc_events(start=dt.date(2026, 12, 1), end=dt.date(2027, 2, 1), client=client)
    assert [e.date for e in events] == [dt.date(2026, 12, 8), dt.date(2027, 1, 26)]


# ---------------------------------------------------------------------------
# Misc: return shapes, sorting, and the events themselves are well-formed CalendarEvents.
# ---------------------------------------------------------------------------


def test_events_are_sorted_ascending_by_date() -> None:
    client = _client_serving_fixture()
    events, _ = fomc_events(start=dt.date(2026, 1, 1), end=dt.date(2027, 12, 31), client=client)
    dates = [e.date for e in events]
    assert dates == sorted(dates)


def test_returned_events_are_calendar_event_instances() -> None:
    client = _client_serving_fixture()
    events, warnings = fomc_events(start=dt.date(2026, 1, 1), end=dt.date(2026, 12, 31), client=client)
    assert all(isinstance(e, CalendarEvent) for e in events)
    assert all(isinstance(w, MarketWarning) for w in warnings)


def test_bundled_schedule_json_is_well_formed() -> None:
    path = Path(__file__).parent.parent / "data" / "calendar" / "fomc_schedule.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["source_url"]
    assert payload["meetings"]
    for entry in payload["meetings"]:
        d = dt.date.fromisoformat(entry["date"])
        if entry.get("end_date"):
            e = dt.date.fromisoformat(entry["end_date"])
            assert e > d
        assert isinstance(entry["projections"], bool)


# ---------------------------------------------------------------------------
# 8. Regenerating the bundled snapshot (`refresh_bundled_schedule` / `python -m app.market.fomc`).
#
# The live page is the primary source, so these tests are about the *fallback* not rotting and,
# more importantly, about it never being destroyed by a refresh that ran against a page whose
# layout changed. A refresh that silently emptied the snapshot would remove the safety net at
# precisely the moment the live source is the thing that broke.
# ---------------------------------------------------------------------------

_TODAY = dt.date(2026, 8, 26)


def _write_schedule(path: Path, meetings: list[tuple[str, str | None, bool]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                "retrieved_at": "2026-01-01",
                "note": "test fixture",
                "meetings": [
                    {"date": d, "end_date": e, "projections": p} for d, e, p in meetings
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _client_serving_html(html: str) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    return _mock_client(handler)


def test_refresh_adds_a_newly_published_year(tmp_path: Path) -> None:
    target = tmp_path / "fomc_schedule.json"
    _write_schedule(target, [("2026-01-27", "2026-01-28", False)])

    result = refresh_bundled_schedule(
        client=_client_serving_fixture(), path=target, today=_TODAY
    )

    assert result.written is True
    assert result.refused_reason is None
    assert 2027 in result.new_years
    assert result.meetings_after > result.meetings_before

    reloaded = _load_bundled_schedule_from(target)
    assert {m.date.year for m in reloaded} == {2026, 2027}


def test_refresh_is_idempotent_and_leaves_the_file_byte_identical(tmp_path: Path) -> None:
    target = tmp_path / "fomc_schedule.json"
    _write_schedule(target, [("2026-01-27", "2026-01-28", False)])

    refresh_bundled_schedule(client=_client_serving_fixture(), path=target, today=_TODAY)
    first = target.read_bytes()

    second_result = refresh_bundled_schedule(
        client=_client_serving_fixture(), path=target, today=_TODAY
    )

    # Nothing changed upstream, so a scheduled re-run must not produce a diff -- only
    # `retrieved_at` would have moved, and a date stamp is not worth a commit.
    assert second_result.written is False
    assert second_result.refused_reason is None
    assert target.read_bytes() == first


def test_refresh_refuses_to_shrink_coverage_and_leaves_the_file_alone(tmp_path: Path) -> None:
    target = tmp_path / "fomc_schedule.json"
    # One meeting further out than anything the page carries, so the scrape is strictly smaller.
    _write_schedule(
        target,
        [
            ("2026-01-27", "2026-01-28", False),
            ("2027-12-07", "2027-12-08", True),
            ("2029-06-12", "2029-06-13", False),
            ("2029-09-18", "2029-09-19", True),
            ("2029-11-06", "2029-11-07", False),
            ("2029-12-11", "2029-12-12", True),
            ("2030-01-29", "2030-01-30", False),
            ("2030-03-19", "2030-03-20", True),
            ("2030-05-07", "2030-05-08", False),
            ("2030-06-18", "2030-06-19", True),
            ("2030-07-30", "2030-07-31", False),
            ("2030-09-17", "2030-09-18", True),
            ("2030-11-05", "2030-11-06", False),
            ("2030-12-10", "2030-12-11", True),
            ("2031-01-28", "2031-01-29", False),
            ("2031-03-18", "2031-03-19", True),
            ("2031-04-29", "2031-04-30", False),
        ],
    )
    before = target.read_bytes()

    result = refresh_bundled_schedule(
        client=_client_serving_fixture(), path=target, today=_TODAY
    )

    assert result.written is False
    assert result.refused_reason is not None
    assert "shrink" in result.refused_reason
    assert target.read_bytes() == before


def test_refresh_refuses_an_unparseable_page(tmp_path: Path) -> None:
    target = tmp_path / "fomc_schedule.json"
    _write_schedule(target, [("2026-01-27", "2026-01-28", False)])
    before = target.read_bytes()

    result = refresh_bundled_schedule(
        client=_client_serving_html("<html><body>no calendar here</body></html>"),
        path=target,
        today=_TODAY,
    )

    assert result.written is False
    assert result.refused_reason is not None
    assert "could not read the live FOMC calendar" in result.refused_reason
    assert "FOMC Meetings" in result.refused_reason  # names what it failed to find
    assert target.read_bytes() == before


def test_refresh_refuses_a_network_failure_without_raising(tmp_path: Path) -> None:
    """A scheduled run on a flaky box must report, not traceback -- and must never treat an
    unreachable page as "the Fed published nothing" and blank the snapshot."""
    target = tmp_path / "fomc_schedule.json"
    _write_schedule(target, [("2026-01-27", "2026-01-28", False)])
    before = target.read_bytes()

    result = refresh_bundled_schedule(
        client=_client_raising(httpx.ConnectError("connection refused")),
        path=target,
        today=_TODAY,
    )

    assert result.written is False
    assert result.refused_reason is not None
    assert "could not read the live FOMC calendar" in result.refused_reason
    assert target.read_bytes() == before


def test_dry_run_reports_the_new_year_without_writing(tmp_path: Path) -> None:
    target = tmp_path / "fomc_schedule.json"
    _write_schedule(target, [("2026-01-27", "2026-01-28", False)])
    before = target.read_bytes()

    result = refresh_bundled_schedule(
        client=_client_serving_fixture(), path=target, today=_TODAY, dry_run=True
    )

    assert result.written is False
    assert result.refused_reason is None
    assert 2027 in result.new_years
    assert target.read_bytes() == before


def test_refresh_drops_years_already_in_the_past(tmp_path: Path) -> None:
    target = tmp_path / "fomc_schedule.json"
    _write_schedule(target, [("2027-01-26", "2027-01-27", False)])

    result = refresh_bundled_schedule(
        client=_client_serving_fixture(), path=target, today=dt.date(2027, 6, 1)
    )

    assert result.refused_reason is None
    reloaded = _load_bundled_schedule_from(target)
    assert reloaded, "expected the 2027 meetings to survive the cutoff"
    assert {m.date.year for m in reloaded} == {2027}


def test_refresh_creates_a_missing_snapshot_rather_than_failing(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "fomc_schedule.json"

    result = refresh_bundled_schedule(
        client=_client_serving_fixture(), path=target, today=_TODAY
    )

    assert result.written is True
    assert target.exists()
    assert _load_bundled_schedule_from(target)


def test_main_exits_non_zero_on_a_refusal(monkeypatch, capsys) -> None:
    # A scheduled run must not swallow a refusal: the file was left alone precisely because
    # something upstream looks wrong, and a silent exit 0 would hide that until the fallback is
    # needed. Patched rather than networked so this asserts the exit contract, not the parser.
    def _refused(**_kwargs) -> ScheduleRefresh:
        return ScheduleRefresh(
            path=Path("fomc_schedule.json"),
            written=False,
            years_before=(2026,),
            years_after=(),
            meetings_before=8,
            meetings_after=0,
            last_before=dt.date(2026, 12, 8),
            last_after=None,
            refused_reason="the live page yielded no meetings",
        )

    monkeypatch.setattr("app.market.fomc.refresh_bundled_schedule", _refused)

    assert _main(["--check"]) == 1
    assert "REFUSED" in capsys.readouterr().out


def test_main_exits_zero_and_reports_when_up_to_date(monkeypatch, capsys) -> None:
    def _unchanged(**_kwargs) -> ScheduleRefresh:
        return ScheduleRefresh(
            path=Path("fomc_schedule.json"),
            written=False,
            years_before=(2026, 2027),
            years_after=(2026, 2027),
            meetings_before=16,
            meetings_after=16,
            last_before=dt.date(2027, 12, 8),
            last_after=dt.date(2027, 12, 8),
        )

    monkeypatch.setattr("app.market.fomc.refresh_bundled_schedule", _unchanged)

    assert _main([]) == 0
    assert "up to date" in capsys.readouterr().out
