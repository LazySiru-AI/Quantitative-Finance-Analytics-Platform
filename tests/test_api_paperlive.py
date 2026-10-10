"""Tests for `app.api.paperlive`: the wire contract, the symbol cap, the disabled-feature gate, and
the SSE stream's framing and clean termination on disconnect.

Follows `tests/test_market_api.py`'s pattern exactly: drive the *real* `app.main.app` through
`TestClient`, and replace the module's own source accessor (`paperlive_api._source`) with a fake --
the same shape that file uses for `app.api.market._registry`. This is deliberate, not incidental:
this repo has a known failure mode where an API test builds its own `FastAPI()` app and a missing
`include_router` in `main.py` still passes every test (see `app.main`'s own module docstring and
`tests/test_deployment_paths.py`). Importing `app` from `app.main` and asserting through `TestClient`
is what a `include_router` regression would actually break.

`app.market.live` has its own test file (`tests/test_market_live.py`) for `PollingQuoteSource` /
`YahooStreamQuoteSource` themselves; this file only exercises the HTTP boundary on top of them, with
a fake source that has no threads and no network of its own.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import json
from collections.abc import Sequence
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api import paperlive as paperlive_api
from app.config import Settings, get_settings
from app.main import app
from app.market.live import LiveQuote, LiveQuoteError, LiveSnapshot

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeSource:
    """A `LiveQuoteSource` with no thread and no network: `snapshot` returns whatever was configured,
    recording every call's symbol list so a test can assert what the route actually asked for."""

    def __init__(self, snapshot: LiveSnapshot) -> None:
        self._snapshot = snapshot
        self.calls: list[list[str]] = []

    def snapshot(self, symbols: Sequence[str]) -> LiveSnapshot:
        self.calls.append(list(symbols))
        return self._snapshot

    def close(self) -> None:  # pragma: no cover -- nothing to clean up
        pass


_AS_OF = dt.datetime(2026, 8, 28, 20, 0, 1, tzinfo=dt.UTC)


def _contract_snapshot() -> LiveSnapshot:
    """Matches the shard brief's own contract example almost verbatim."""
    return LiveSnapshot(
        as_of=_AS_OF,
        market_state="POST",
        transport="poll",
        healthy=True,
        quotes=(
            LiveQuote(
                symbol="AAPL",
                price=Decimal("319.70"),
                previous_close=Decimal("309.35"),
                change=Decimal("10.35"),
                change_pct=Decimal("3.3457"),
                ts=_AS_OF,
                stale=False,
                source="yahoo",
            ),
        ),
        errors=(LiveQuoteError(symbol="XYZ", message="not found"),),
    )


def _to_response_json() -> str:
    return paperlive_api._to_response(_contract_snapshot()).model_dump_json()


@pytest.fixture
def fake_source() -> FakeSource:
    return FakeSource(_contract_snapshot())


@pytest.fixture
def client(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, fake_source: FakeSource
) -> TestClient:
    monkeypatch.setattr(paperlive_api, "_source", lambda: fake_source)
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/paperlive/quotes
# ---------------------------------------------------------------------------


class TestQuotesRoute:
    def test_matches_the_contract_shape(self, client: TestClient) -> None:
        resp = client.get("/api/paperlive/quotes", params={"symbols": "AAPL,XYZ"})
        assert resp.status_code == 200
        body = resp.json()

        assert body["market_state"] == "POST"
        assert body["transport"] == "poll"
        assert body["healthy"] is True
        assert body["as_of"] == "2026-08-28T20:00:01Z"

        assert len(body["quotes"]) == 1
        q = body["quotes"][0]
        assert q["symbol"] == "AAPL"
        # every money/percent field crosses the wire as a JSON string, never a number
        assert q["price"] == "319.70"
        assert isinstance(q["price"], str)
        assert q["previous_close"] == "309.35"
        assert q["change"] == "10.35"
        assert q["change_pct"] == "3.3457"
        assert q["ts"] == "2026-08-28T20:00:01Z"
        assert q["stale"] is False
        assert q["source"] == "yahoo"

        assert body["errors"] == [{"symbol": "XYZ", "message": "not found"}]

    def test_symbols_are_parsed_upper_cased_and_deduplicated(
        self, client: TestClient, fake_source: FakeSource
    ) -> None:
        resp = client.get("/api/paperlive/quotes", params={"symbols": " aapl ,AAPL, msft"})
        assert resp.status_code == 200
        assert fake_source.calls[-1] == ["AAPL", "MSFT"]

    def test_invalid_symbol_is_422(self, client: TestClient) -> None:
        resp = client.get("/api/paperlive/quotes", params={"symbols": "AAPL,not a symbol"})
        assert resp.status_code == 422

    def test_empty_symbols_is_422(self, client: TestClient) -> None:
        resp = client.get("/api/paperlive/quotes", params={"symbols": " , ,"})
        assert resp.status_code == 422

    def test_too_many_symbols_is_422(self, client: TestClient) -> None:
        many = ",".join(f"SYM{i}" for i in range(51))
        resp = client.get("/api/paperlive/quotes", params={"symbols": many})
        assert resp.status_code == 422
        assert "50" in resp.json()["detail"]

    def test_exactly_the_cap_is_accepted(self, client: TestClient) -> None:
        exactly_fifty = ",".join(f"SYM{i}" for i in range(50))
        resp = client.get("/api/paperlive/quotes", params={"symbols": exactly_fifty})
        assert resp.status_code == 200

    def test_disabled_feature_is_503(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INVDASH_PAPERLIVE_ENABLED", "0")
        get_settings.cache_clear()
        try:
            resp = client.get("/api/paperlive/quotes", params={"symbols": "AAPL"})
            assert resp.status_code == 503
        finally:
            get_settings.cache_clear()


# ---------------------------------------------------------------------------
# GET /api/paperlive/stream
# ---------------------------------------------------------------------------


class TestStreamRoute:
    def test_emits_a_well_formed_quotes_frame(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Drives the *real* `/stream` route (real `StreamingResponse`, real headers, real call into
        `_event_stream` with the args the route builds from the request/settings) through an actual
        HTTP round trip -- but with `_event_stream` itself replaced by a two-frame fake.

        This is not a shortcut around testing the real thing: `httpx.ASGITransport` (what
        `TestClient` is built on) runs the whole ASGI app call to completion before it hands back a
        `Response` at all -- see `ASGITransport.handle_async_request` in `httpx/_transports/asgi.py`,
        which does `await self.app(scope, receive, send)` and only builds a `Response` afterwards.
        It cannot represent an in-progress, still-open stream, so the real `_event_stream` (an
        infinite generator by design -- see its own docstring) can never be driven through
        `TestClient` at all; every attempt hangs until the surrounding test times out. The real
        generator's framing, keepalive schedule and disconnect handling are exercised directly, with
        no HTTP layer in the way at all, by `TestEventStreamGenerator` below and by the recorded
        `captured` call here, which proves the route passed it the right arguments.
        """
        captured: dict[str, object] = {}

        async def fake_event_stream(source: object, symbols: object, **kwargs: object):
            captured["symbols"] = symbols
            captured["kwargs"] = kwargs
            yield "event: quotes\ndata: " + _to_response_json()

        monkeypatch.setattr(paperlive_api, "_event_stream", fake_event_stream)

        resp = client.get("/api/paperlive/stream", params={"symbols": "AAPL"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

        text = resp.text
        assert text.startswith("event: quotes\ndata: ")
        payload = json.loads(text[len("event: quotes\ndata: ") :])
        assert payload["market_state"] == "POST"
        assert payload["quotes"][0]["symbol"] == "AAPL"
        assert payload["quotes"][0]["price"] == "319.70"

        assert captured["symbols"] == ["AAPL"]
        assert captured["kwargs"]["poll_interval"] == pytest.approx(5.0)

    def test_too_many_symbols_is_422(self, client: TestClient) -> None:
        many = ",".join(f"SYM{i}" for i in range(51))
        resp = client.get("/api/paperlive/stream", params={"symbols": many})
        assert resp.status_code == 422

    def test_disabled_feature_is_503(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INVDASH_PAPERLIVE_ENABLED", "0")
        get_settings.cache_clear()
        try:
            resp = client.get("/api/paperlive/stream", params={"symbols": "AAPL"})
            assert resp.status_code == 503
        finally:
            get_settings.cache_clear()


# ---------------------------------------------------------------------------
# The SSE generator itself, driven directly (no HTTP, no thread) -- this is what actually proves
# "terminates cleanly on disconnect" and "keepalive on schedule", which are awkward to force
# deterministically through a real streaming HTTP connection in a fast unit test.
# ---------------------------------------------------------------------------


class TestEventStreamGenerator:
    def test_emits_one_frame_immediately_then_stops_on_disconnect(self) -> None:
        source = FakeSource(_contract_snapshot())
        disconnect_after = 3
        calls = {"n": 0}

        async def is_disconnected() -> bool:
            calls["n"] += 1
            return calls["n"] > disconnect_after

        async def run() -> list[str]:
            events = []
            async for chunk in paperlive_api._event_stream(
                source,
                ["AAPL"],
                poll_interval=1000.0,  # never re-fires within this test
                is_disconnected=is_disconnected,
                sleep=lambda _s: asyncio.sleep(0),
            ):
                events.append(chunk)
            return events

        events = asyncio.run(run())
        assert len(events) == 1
        assert events[0].startswith("event: quotes\ndata: ")
        # the fake source was subscribed exactly once per emitted frame, never once per tick
        assert source.calls == [["AAPL"]]

    def test_sends_keepalive_comments_while_idle(self) -> None:
        source = FakeSource(_contract_snapshot())
        disconnect_after = 4
        events: list[str] = []

        async def is_disconnected() -> bool:
            return len(events) >= disconnect_after

        async def run() -> None:
            async for chunk in paperlive_api._event_stream(
                source,
                ["AAPL"],
                poll_interval=1000.0,  # far longer than the test can run
                is_disconnected=is_disconnected,
                keepalive_interval=0.05,
                tick_seconds=0.02,
            ):
                events.append(chunk)

        asyncio.run(run())
        assert events[0].startswith("event: quotes")
        assert any(e == ": keepalive\n\n" for e in events[1:])

    def test_terminates_immediately_when_already_disconnected(self) -> None:
        source = FakeSource(_contract_snapshot())

        async def already_gone() -> bool:
            return True

        async def run() -> list[str]:
            return [
                chunk
                async for chunk in paperlive_api._event_stream(
                    source,
                    ["AAPL"],
                    poll_interval=5.0,
                    is_disconnected=already_gone,
                    sleep=lambda _s: asyncio.sleep(0),
                )
            ]

        events = asyncio.run(run())
        assert events == []
        assert source.calls == []


# ---------------------------------------------------------------------------
# Symbol parsing helper
# ---------------------------------------------------------------------------


class TestParseSymbols:
    def test_upper_cases_strips_and_dedupes_preserving_order(self) -> None:
        assert paperlive_api._parse_symbols(" msft ,AAPL,msft") == ["MSFT", "AAPL"]

    def test_rejects_an_invalid_symbol(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            paperlive_api._parse_symbols("AAPL,bad symbol!")
        assert exc_info.value.status_code == 422

    def test_rejects_more_than_the_cap(self) -> None:
        from fastapi import HTTPException

        many = ",".join(f"SYM{i}" for i in range(51))
        with pytest.raises(HTTPException) as exc_info:
            paperlive_api._parse_symbols(many)
        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Route registration on the *real* app -- the known failure mode this codebase has seen before is a
# missing `include_router` in `app.main` passing every test because the test built its own app
# instead. `client` above already goes through `app.main.app`; this asserts it explicitly too.
# ---------------------------------------------------------------------------


def test_routes_are_registered_on_the_real_app() -> None:
    paths = set(app.openapi()["paths"])
    assert "/api/paperlive/quotes" in paths
    assert "/api/paperlive/stream" in paths


class TestEventStreamCadenceFollowsMarketState:
    """The emit cadence has two tiers, matching `PollingQuoteSource`'s own upstream cadence.

    The route used to pass only `paperlive_poll_seconds`, so with the market closed every connected
    browser was sent a byte-identical snapshot on the fast interval -- twelve redundant frames per
    actual upstream refresh at the shipped 5s/60s defaults. Caught by watching the real endpoint
    stream, not by any stubbed test: every fixture here reports a single `market_state`, so a
    single-tier loop looks perfectly correct until the two tiers are asked to differ.
    """

    @staticmethod
    def _run(snapshot: LiveSnapshot, *, ticks: int) -> list[str]:
        source = FakeSource(snapshot)
        events: list[str] = []
        seen = {"n": 0}

        async def is_disconnected() -> bool:
            seen["n"] += 1
            return seen["n"] > ticks

        async def run() -> None:
            async for chunk in paperlive_api._event_stream(
                source,
                ["AAPL"],
                poll_interval=0.0,  # fast tier: re-fire on every tick
                idle_interval=1000.0,  # idle tier: never re-fires within this test
                is_disconnected=is_disconnected,
                keepalive_interval=1000.0,  # keep keepalives out of the way
                tick_seconds=0.001,
                sleep=lambda _s: asyncio.sleep(0),
            ):
                events.append(chunk)

        asyncio.run(run())
        return events

    def test_closed_market_falls_back_to_the_idle_interval_after_one_frame(self) -> None:
        events = self._run(_contract_snapshot(), ticks=8)
        # POST, not REGULAR: the immediate frame is sent, then the idle interval suppresses the rest
        assert len(events) == 1

    def test_open_market_keeps_emitting_on_the_fast_interval(self) -> None:
        regular = dataclasses.replace(_contract_snapshot(), market_state="REGULAR")
        events = self._run(regular, ticks=8)
        assert len(events) > 1
        assert all(e.startswith("event: quotes") for e in events)
