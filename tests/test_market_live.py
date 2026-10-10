"""Tests for `app.market.live`: the protobuf field decoder, `PollingQuoteSource`'s failure/health
accounting, and `YahooStreamQuoteSource`'s fall-back-on-any-doubt behaviour.

No test in this file touches the network. `PollingQuoteSource` and `YahooStreamQuoteSource` are
driven with a hand-written fake registry/connection -- the same shape `tests/test_market_refresh.py`
already uses for `app.market.refresh` -- and every source built here is `.close()`d so no daemon
thread outlives its test.
"""

from __future__ import annotations

import base64
import datetime as dt
import struct
import time

import pytest

from app.market.live import (
    DEFAULT_STALE_AFTER_SECONDS,
    LiveQuoteError,
    PollingQuoteSource,
    YahooStreamQuoteSource,
    build_polling_registry,
    decode_pricing_frame,
    parse_protobuf_fields,
)
from app.market.models import BarSource, Quote

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeRegistry:
    """A `ProviderRegistry`-shaped stand-in: `get_quote` returns a configured `Quote` or raises a
    configured exception, per symbol, and records every call in order."""

    def __init__(
        self,
        quotes: dict[str, Quote] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.quotes = dict(quotes or {})
        self.errors = dict(errors or {})
        self.calls: list[str] = []

    def get_quote(self, symbol: str) -> Quote:
        self.calls.append(symbol)
        if symbol in self.errors:
            raise self.errors[symbol]
        return self.quotes[symbol]


class FakeConnection:
    """A `_StreamConnection`-shaped stand-in. `recv` returns queued messages in order and raises
    `TimeoutError` once the queue is empty -- the same behaviour `websockets.sync.client` gives on a
    real read timeout, which is what lets `YahooStreamQuoteSource`'s bootstrap-timeout logic run
    against this fake exactly as it would against the real thing."""

    def __init__(self, messages: list[str] | None = None) -> None:
        self._messages = list(messages or [])
        self.sent: list[str] = []
        self.closed = False

    def send(self, message: str) -> None:
        self.sent.append(message)

    def recv(self, timeout: float | None = None) -> str:
        if self._messages:
            return self._messages.pop(0)
        raise TimeoutError("no message queued")

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        self.closed = True


def _quote(
    symbol: str,
    price: float,
    *,
    ts: dt.datetime | None = None,
    market_state: str | None = "REGULAR",
    previous_close: float | None = None,
    change: float | None = None,
    change_pct: float | None = None,
) -> Quote:
    return Quote(
        symbol=symbol,
        price=price,
        ts=ts or dt.datetime.now(dt.UTC),
        market_state=market_state,
        previous_close=previous_close,
        change=change,
        change_pct=change_pct,
        source=BarSource.YAHOO,
    )


def _encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _encode_tag(field_no: int, wire_type: int) -> bytes:
    return _encode_varint((field_no << 3) | wire_type)


def _encode_pricing_frame(
    symbol: str,
    price: float,
    *,
    day_volume: int | None = None,
    change_pct: float | None = None,
) -> bytes:
    """Build a minimal `PricingData`-shaped protobuf message for testing the decoder -- the inverse
    of `decode_pricing_frame`. Field numbers match the ones that module asserts (unverified against
    real Yahoo bytes, see its module docstring): 1=id, 2=price, 7=dayVolume, 13=changePercent.
    """
    out = bytearray()
    id_bytes = symbol.encode("utf-8")
    out += _encode_tag(1, 2) + _encode_varint(len(id_bytes)) + id_bytes
    out += _encode_tag(2, 5) + struct.pack("<f", price)
    if day_volume is not None:
        out += _encode_tag(7, 0) + _encode_varint(day_volume)
    if change_pct is not None:
        out += _encode_tag(13, 5) + struct.pack("<f", change_pct)
    return bytes(out)


# ---------------------------------------------------------------------------
# Protobuf decoder
# ---------------------------------------------------------------------------


class TestPricingFrameDecoder:
    def test_decodes_id_price_volume_and_change_pct(self) -> None:
        raw = _encode_pricing_frame("AAPL", 150.25, day_volume=123456, change_pct=1.25)
        decoded = decode_pricing_frame(raw)
        assert decoded is not None
        assert decoded["symbol"] == "AAPL"
        assert decoded["price"] == pytest.approx(150.25, abs=1e-3)
        assert decoded["day_volume"] == 123456
        assert decoded["change_pct"] == pytest.approx(1.25, abs=1e-3)

    def test_missing_optional_fields_are_simply_absent(self) -> None:
        raw = _encode_pricing_frame("MSFT", 300.0)
        decoded = decode_pricing_frame(raw)
        assert decoded is not None
        assert decoded["symbol"] == "MSFT"
        assert "day_volume" not in decoded
        assert "change_pct" not in decoded

    def test_truncated_bytes_decode_to_none_not_an_exception(self) -> None:
        raw = _encode_pricing_frame("AAPL", 150.25)
        assert decode_pricing_frame(raw[:3]) is None
        assert decode_pricing_frame(b"\xff\xff\xff") is None
        assert decode_pricing_frame(b"") is None

    def test_non_positive_or_non_finite_price_is_rejected(self) -> None:
        raw = _encode_pricing_frame("AAPL", 0.0)
        assert decode_pricing_frame(raw) is None

    def test_parse_protobuf_fields_recovers_a_varint_and_a_length_delimited_field(self) -> None:
        raw = _encode_tag(1, 2) + _encode_varint(3) + b"ABC" + _encode_tag(7, 0) + _encode_varint(42)
        fields = parse_protobuf_fields(raw)
        assert fields[1] == b"ABC"
        assert fields[7] == 42


# ---------------------------------------------------------------------------
# PollingQuoteSource
# ---------------------------------------------------------------------------


class TestPollingQuoteSource:
    def test_one_symbol_failing_leaves_the_others_flowing(self) -> None:
        registry = FakeRegistry(
            quotes={"AAPL": _quote("AAPL", 319.70)},
            errors={"BAD": ValueError("no such ticker")},
        )
        source = PollingQuoteSource(
            registry_factory=lambda: registry, fast_interval=5.0, idle_interval=5.0
        )
        try:
            snapshot = source.snapshot(["AAPL", "BAD"])
        finally:
            source.close()

        assert {q.symbol for q in snapshot.quotes} == {"AAPL"}
        assert snapshot.errors == (LiveQuoteError(symbol="BAD", message="no such ticker"),)
        # the good symbol must not be reported unhealthy just because its neighbour failed
        assert snapshot.healthy is True

    def test_sustained_total_failure_flips_healthy_false(self) -> None:
        registry = FakeRegistry(errors={"BAD": ValueError("down")})
        source = PollingQuoteSource(
            registry_factory=lambda: registry,
            fast_interval=0.02,
            idle_interval=0.02,
            unhealthy_after_cycles=2,
        )
        try:
            source.subscribe(["BAD"])
            deadline = time.monotonic() + 3.0
            while source.healthy and time.monotonic() < deadline:
                time.sleep(0.02)
            assert source.healthy is False
        finally:
            source.close()

    def test_a_single_bad_cycle_does_not_flip_healthy(self) -> None:
        """One symbol erroring once is the ordinary, expected shape of `errors` -- not sustained
        total failure. `healthy` must stay `True` for it."""
        registry = FakeRegistry(errors={"BAD": ValueError("transient")})
        source = PollingQuoteSource(
            registry_factory=lambda: registry,
            fast_interval=5.0,
            idle_interval=5.0,
            unhealthy_after_cycles=3,
        )
        try:
            snapshot = source.snapshot(["BAD"])
        finally:
            source.close()
        assert snapshot.healthy is True

    def test_stale_flag_set_past_the_threshold(self) -> None:
        old_ts = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1000)
        registry = FakeRegistry(quotes={"OLD": _quote("OLD", 10.0, ts=old_ts)})
        source = PollingQuoteSource(
            registry_factory=lambda: registry,
            fast_interval=5.0,
            idle_interval=5.0,
            stale_after_seconds=10.0,
        )
        try:
            snapshot = source.snapshot(["OLD"])
        finally:
            source.close()
        assert snapshot.quotes[0].stale is True

    def test_fresh_quote_is_not_stale(self) -> None:
        registry = FakeRegistry(quotes={"NEW": _quote("NEW", 10.0)})
        source = PollingQuoteSource(
            registry_factory=lambda: registry,
            fast_interval=5.0,
            idle_interval=5.0,
            stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS,
        )
        try:
            snapshot = source.snapshot(["NEW"])
        finally:
            source.close()
        assert snapshot.quotes[0].stale is False

    def test_prices_cross_as_decimal_quantized_for_display(self) -> None:
        registry = FakeRegistry(
            quotes={
                "AAPL": _quote(
                    "AAPL", 319.7, previous_close=309.35, change=10.35, change_pct=3.3457
                )
            }
        )
        source = PollingQuoteSource(
            registry_factory=lambda: registry, fast_interval=5.0, idle_interval=5.0
        )
        try:
            snapshot = source.snapshot(["AAPL"])
        finally:
            source.close()
        q = snapshot.quotes[0]
        assert str(q.price) == "319.70"
        assert str(q.previous_close) == "309.35"
        assert str(q.change) == "10.35"
        assert str(q.change_pct) == "3.3457"
        assert q.source == "yahoo"

    def test_float_subtraction_artifacts_never_reach_the_wire(self) -> None:
        """The values below are the real ones this endpoint returned for AAPL against live Yahoo.

        Yahoo computes `change` as a float subtraction upstream, so a clean $10.35 move arrives as
        `10.349999999999966`. Every stubbed test in this file used tidy literals and so could not
        have caught it; rendering it verbatim put a fifteen-decimal price change on the page.
        """
        registry = FakeRegistry(
            quotes={
                "AAPL": _quote(
                    "AAPL",
                    319.7,
                    previous_close=309.35,
                    change=10.349999999999966,
                    change_pct=3.3457249070631856,
                )
            }
        )
        source = PollingQuoteSource(
            registry_factory=lambda: registry, fast_interval=5.0, idle_interval=5.0
        )
        try:
            snapshot = source.snapshot(["AAPL"])
        finally:
            source.close()
        q = snapshot.quotes[0]
        assert str(q.change) == "10.35"
        assert str(q.change_pct) == "3.3457"

    def test_dominant_market_state_prefers_regular(self) -> None:
        registry = FakeRegistry(
            quotes={
                "CLOSED_SYM": _quote("CLOSED_SYM", 1.0, market_state="CLOSED"),
                "OPEN_SYM": _quote("OPEN_SYM", 2.0, market_state="REGULAR"),
            }
        )
        source = PollingQuoteSource(
            registry_factory=lambda: registry, fast_interval=5.0, idle_interval=5.0
        )
        try:
            snapshot = source.snapshot(["CLOSED_SYM", "OPEN_SYM"])
        finally:
            source.close()
        assert snapshot.market_state == "REGULAR"

    def test_unknown_symbol_never_seen_reports_an_error_not_a_crash(self) -> None:
        """A symbol the registry doesn't know about raises `KeyError` from the fake -- exactly the
        shape "provider blew up for a reason this module didn't anticipate" takes in production, and
        it must land in `errors`, not propagate."""
        registry = FakeRegistry(quotes={})
        source = PollingQuoteSource(
            registry_factory=lambda: registry, fast_interval=5.0, idle_interval=5.0
        )
        try:
            snapshot = source.snapshot(["GHOST"])
        finally:
            source.close()
        assert snapshot.quotes == ()
        assert len(snapshot.errors) == 1
        assert snapshot.errors[0].symbol == "GHOST"


def test_build_polling_registry_bypasses_the_shared_http_cache() -> None:
    """`app.market.registry.default_registry()` wraps every request in `CachingTransport` with a
    30-second TTL for quote lookups -- fine for the rest of the app, but it would make a 5-second
    poll cadence mostly replay a cached price. `build_polling_registry` must not use it."""
    import httpx

    from app.market.cache import CachingTransport

    registry = build_polling_registry()
    provider = registry._profile_providers[0]
    transport = provider._client._transport
    assert not isinstance(transport, CachingTransport)
    assert isinstance(transport, httpx.HTTPTransport)


# ---------------------------------------------------------------------------
# YahooStreamQuoteSource
# ---------------------------------------------------------------------------


class TestYahooStreamQuoteSource:
    def test_falls_back_immediately_when_connect_fails(self) -> None:
        def bad_connect() -> FakeConnection:
            raise OSError("connection refused")

        fallback_registry = FakeRegistry(quotes={"AAPL": _quote("AAPL", 100.0)})
        fallback = PollingQuoteSource(
            registry_factory=lambda: fallback_registry, fast_interval=0.05, idle_interval=0.05
        )
        source = YahooStreamQuoteSource(
            fallback=fallback, connect_fn=bad_connect, bootstrap_timeout=0.2, frame_timeout=0.05
        )
        try:
            snapshot = source.snapshot(["AAPL"])
            deadline = time.monotonic() + 2.0
            while source.mode == "bootstrapping" and time.monotonic() < deadline:
                time.sleep(0.02)
                snapshot = source.snapshot(["AAPL"])
            assert source.mode == "fallback"
            assert snapshot.transport == "poll"
            assert snapshot.quotes[0].symbol == "AAPL"
        finally:
            source.close()

    def test_falls_back_after_bootstrap_timeout_with_no_frames(self) -> None:
        conn = FakeConnection(messages=[])  # every recv() times out

        fallback_registry = FakeRegistry(quotes={"AAPL": _quote("AAPL", 100.0)})
        fallback = PollingQuoteSource(
            registry_factory=lambda: fallback_registry, fast_interval=0.05, idle_interval=0.05
        )
        source = YahooStreamQuoteSource(
            fallback=fallback,
            connect_fn=lambda: conn,
            bootstrap_timeout=0.15,
            frame_timeout=0.02,
        )
        try:
            source.snapshot(["AAPL"])  # starts the stream thread and subscribes the symbol
            deadline = time.monotonic() + 2.0
            while source.mode == "bootstrapping" and time.monotonic() < deadline:
                time.sleep(0.02)
            assert source.mode == "fallback"
            assert source.fallback_reason is not None and "bootstrap" in source.fallback_reason
            snapshot = source.snapshot(["AAPL"])
            assert snapshot.transport == "poll"
        finally:
            source.close()

    def test_decoded_price_disagreeing_with_rest_is_never_trusted(self) -> None:
        """The frame decodes cleanly (proving decode isn't the failure mode here) but names a price
        wildly different from the REST quote for the same symbol -- the exact "unverified decoder
        silently emitting garbage" case the brief calls out. It must never be surfaced, and the
        source must still end up on the fallback."""
        frame = _encode_pricing_frame("AAPL", 999.0)
        conn = FakeConnection(messages=[base64.b64encode(frame).decode("ascii")])

        rest_registry = FakeRegistry(quotes={"AAPL": _quote("AAPL", 100.0)})
        fallback_registry = FakeRegistry(quotes={"AAPL": _quote("AAPL", 100.0)})
        fallback = PollingQuoteSource(
            registry_factory=lambda: fallback_registry, fast_interval=0.05, idle_interval=0.05
        )
        source = YahooStreamQuoteSource(
            fallback=fallback,
            registry_factory=lambda: rest_registry,
            connect_fn=lambda: conn,
            bootstrap_timeout=0.2,
            frame_timeout=0.02,
            validation_tolerance=0.05,
        )
        try:
            source.snapshot(["AAPL"])
            deadline = time.monotonic() + 2.0
            while source.mode == "bootstrapping" and time.monotonic() < deadline:
                time.sleep(0.02)
            assert source.mode == "fallback"
            snapshot = source.snapshot(["AAPL"])
            # served from the fallback (whose REST price is 100.0), never the untrusted 999.0
            assert snapshot.transport == "poll"
            assert str(snapshot.quotes[0].price) == "100.00"
        finally:
            source.close()

    def test_validated_frame_is_served_from_the_stream(self) -> None:
        price = 123.45
        frame = _encode_pricing_frame("AAPL", price)
        conn = FakeConnection(messages=[base64.b64encode(frame).decode("ascii")])

        rest_registry = FakeRegistry(quotes={"AAPL": _quote("AAPL", price)})
        # Deliberately different from the stream price, so a test that accidentally reads the
        # fallback instead of the stream fails loudly rather than passing by coincidence.
        fallback_registry = FakeRegistry(quotes={"AAPL": _quote("AAPL", 1.0)})
        fallback = PollingQuoteSource(
            registry_factory=lambda: fallback_registry, fast_interval=0.05, idle_interval=0.05
        )
        source = YahooStreamQuoteSource(
            fallback=fallback,
            registry_factory=lambda: rest_registry,
            connect_fn=lambda: conn,
            bootstrap_timeout=1.0,
            frame_timeout=0.02,
        )
        try:
            deadline = time.monotonic() + 2.0
            snapshot = source.snapshot(["AAPL"])
            while snapshot.transport != "stream" and time.monotonic() < deadline:
                time.sleep(0.02)
                snapshot = source.snapshot(["AAPL"])
            assert snapshot.transport == "stream"
            assert snapshot.quotes[0].symbol == "AAPL"
            assert float(snapshot.quotes[0].price) == pytest.approx(price, abs=1e-2)
        finally:
            source.close()

    def test_frame_for_an_unwatched_symbol_is_ignored(self) -> None:
        """A frame naming a symbol nobody asked for must not be adopted -- it is either the wrong
        field mapping (garbage) or a stale subscription; either way it is not this caller's data."""
        frame = _encode_pricing_frame("MSFT", 50.0)
        conn = FakeConnection(messages=[base64.b64encode(frame).decode("ascii")])
        rest_registry = FakeRegistry(quotes={"MSFT": _quote("MSFT", 50.0)})
        fallback = PollingQuoteSource(
            registry_factory=lambda: FakeRegistry(quotes={"AAPL": _quote("AAPL", 1.0)}),
            fast_interval=0.05,
            idle_interval=0.05,
        )
        source = YahooStreamQuoteSource(
            fallback=fallback,
            registry_factory=lambda: rest_registry,
            connect_fn=lambda: conn,
            bootstrap_timeout=0.15,
            frame_timeout=0.02,
        )
        try:
            source.snapshot(["AAPL"])  # watches AAPL only -- the frame names MSFT
            deadline = time.monotonic() + 2.0
            while source.mode == "bootstrapping" and time.monotonic() < deadline:
                time.sleep(0.02)
            # never validated (the only frame sent was for an unwatched symbol), so this instance
            # gives up once the bootstrap window elapses
            assert source.mode == "fallback"
        finally:
            source.close()
