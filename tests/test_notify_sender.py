"""Delivery policy and the two channels.

Every test drives `sender.dispatch` directly with a hand-built `NotifyEvent` and a `Settings` whose
notify fields are set through the environment (the same route `.env` uses), so what is asserted here
is the *policy*, not a producer's behaviour.

**No test here reaches the network.** The ntfy tests monkeypatch `httpx.post` at
`app.notify.sender.httpx.post`, which is the name the module actually calls.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings, get_settings
from app.notify import sender
from app.notify.events import NotifyEvent, Severity

_ET = ZoneInfo("America/New_York")


def _event(
    *, severity: Severity = "notable", kind: str = "manager.change", headline: str = "Cash fell 4%"
) -> NotifyEvent:
    return NotifyEvent(
        id="evt-1",
        ts=dt.datetime.now(dt.UTC).isoformat(),
        kind=kind,
        severity=severity,
        headline=headline,
        detail="taxable cash 12,400 -> 11,900",
    )


@pytest.fixture
def notify_settings(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A factory that rebuilds `Settings` with notify overrides applied.

    Built on the conftest `settings` fixture (which roots `data_dir` in `tmp_path`, so the sender's
    state file lands there) and driven through `INVDASH_*` + `get_settings.cache_clear()`, the same
    mechanism a deployment uses -- not by patching attributes onto a Settings object, which would
    prove nothing about how the real configuration path resolves these.

    Delivery is on and the channel is `log` unless a test says otherwise, because a test that had to
    remember to enable delivery would silently pass by never sending anything.
    """

    def _build(**overrides: object) -> Settings:
        base: dict[str, object] = {"NOTIFY_ENABLED": "1", "NOTIFY_CHANNEL": "log"}
        base.update({key.upper(): value for key, value in overrides.items()})
        for key, value in base.items():
            monkeypatch.setenv(f"INVDASH_{key}", str(value))
        get_settings.cache_clear()
        return get_settings()

    return _build


class TestEnabledGate:
    def test_off_by_default_sends_nothing(self, settings: Settings) -> None:
        # The conftest `settings` fixture applies no notify overrides, so this is the shipped default.
        assert settings.notify_enabled is False
        assert sender.dispatch(settings, _event()) is False

    def test_on_sends_over_the_log_channel(self, notify_settings: Any) -> None:
        assert sender.dispatch(notify_settings(notify_quiet_hours=""), _event()) is True

    def test_a_suppression_is_counted_and_a_send_is_counted(self, notify_settings: Any) -> None:
        cfg = notify_settings(notify_min_severity="notable", notify_quiet_hours="")
        sender.dispatch(cfg, _event(severity="fyi"))
        sender.dispatch(cfg, _event(severity="notable"))
        assert sender.today_counters(cfg) == {"sent": 1, "suppressed": 1}
        assert sender.last_sent_ts(cfg) is not None


class TestMinSeverity:
    @pytest.mark.parametrize(
        ("floor", "severity", "expected"),
        [
            ("notable", "attention", True),
            ("notable", "notable", True),
            ("notable", "fyi", False),
            ("attention", "attention", True),
            ("attention", "notable", False),
            ("fyi", "fyi", True),
        ],
    )
    def test_ordering_is_attention_over_notable_over_fyi(
        self, notify_settings: Any, floor: str, severity: Severity, expected: bool
    ) -> None:
        cfg = notify_settings(notify_min_severity=floor, notify_quiet_hours="")
        assert sender.dispatch(cfg, _event(severity=severity)) is expected

    def test_an_unrecognised_floor_falls_back_to_notable_rather_than_sending_everything(
        self, notify_settings: Any
    ) -> None:
        cfg = notify_settings(notify_min_severity="URGENT", notify_quiet_hours="")
        assert sender.dispatch(cfg, _event(severity="fyi")) is False
        assert sender.dispatch(cfg, _event(severity="notable")) is True


class TestKindFilter:
    def test_empty_means_every_kind(self, notify_settings: Any) -> None:
        cfg = notify_settings(notify_kinds="", notify_quiet_hours="")
        assert sender.dispatch(cfg, _event(kind="paper.fill")) is True

    def test_a_prefix_subscribes_to_a_whole_subsystem(self, notify_settings: Any) -> None:
        cfg = notify_settings(notify_kinds="paper.", notify_quiet_hours="")
        assert sender.dispatch(cfg, _event(kind="paper.fill")) is True
        assert sender.dispatch(cfg, _event(kind="paper.close")) is True
        assert sender.dispatch(cfg, _event(kind="manager.change")) is False

    def test_an_exact_kind_subscribes_to_exactly_one_thing(self, notify_settings: Any) -> None:
        cfg = notify_settings(notify_kinds="manager.brief", notify_quiet_hours="")
        assert sender.dispatch(cfg, _event(kind="manager.brief")) is True
        assert sender.dispatch(cfg, _event(kind="manager.change")) is False

    def test_whitespace_around_entries_is_tolerated(self, notify_settings: Any) -> None:
        cfg = notify_settings(notify_kinds=" paper. , manager.brief ", notify_quiet_hours="")
        assert sender.dispatch(cfg, _event(kind="manager.brief")) is True


class TestQuietHours:
    @staticmethod
    def _at(monkeypatch: pytest.MonkeyPatch, hour: int, minute: int = 0) -> None:
        """Freeze the sender's clock at a given America/New_York wall time, so the wrapping
        22:00-07:00 window is exercised on both sides of midnight.

        Patches `sender._now`, the module's single clock seam, rather than `datetime.datetime` --
        patching that would reach every other module in the process.
        """
        frozen = dt.datetime(2026, 9, 10, hour, minute, tzinfo=_ET).astimezone(dt.UTC)
        monkeypatch.setattr(sender, "_now", lambda: frozen)

    def test_notable_is_suppressed_inside_the_window(
        self, notify_settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = notify_settings(notify_quiet_hours="22:00-07:00")
        self._at(monkeypatch, 23)
        assert sender.dispatch(cfg, _event(severity="notable")) is False

    def test_the_window_wraps_past_midnight(
        self, notify_settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = notify_settings(notify_quiet_hours="22:00-07:00")
        self._at(monkeypatch, 3)
        assert sender.dispatch(cfg, _event(severity="notable")) is False

    def test_attention_overrides_quiet_hours(
        self, notify_settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = notify_settings(notify_quiet_hours="22:00-07:00")
        self._at(monkeypatch, 23)
        assert sender.dispatch(cfg, _event(severity="attention")) is True

    def test_outside_the_window_notable_sends(
        self, notify_settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = notify_settings(notify_quiet_hours="22:00-07:00")
        self._at(monkeypatch, 10)
        assert sender.dispatch(cfg, _event(severity="notable")) is True

    def test_empty_means_no_quiet_window(
        self, notify_settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = notify_settings(notify_quiet_hours="")
        self._at(monkeypatch, 23)
        assert sender.dispatch(cfg, _event(severity="notable")) is True

    def test_a_malformed_window_is_treated_as_none_rather_than_suppressing_everything(
        self, notify_settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A typo in this setting must fail loud (deliver) rather than silent (swallow).
        cfg = notify_settings(notify_quiet_hours="10pm to 7am")
        self._at(monkeypatch, 23)
        assert sender.dispatch(cfg, _event(severity="notable")) is True

    def test_a_same_day_window_does_not_wrap(
        self, notify_settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = notify_settings(notify_quiet_hours="01:00-05:00")
        self._at(monkeypatch, 3)
        assert sender.dispatch(cfg, _event(severity="notable")) is False
        self._at(monkeypatch, 23)
        assert sender.dispatch(cfg, _event(severity="notable")) is True


class TestRateCap:
    def test_sends_beyond_the_cap_are_suppressed_within_the_hour(
        self, notify_settings: Any
    ) -> None:
        cfg = notify_settings(notify_rate_cap_per_hour=3, notify_quiet_hours="")
        results = [sender.dispatch(cfg, _event()) for _ in range(5)]
        assert results == [True, True, True, False, False]
        assert sender.today_counters(cfg) == {"sent": 3, "suppressed": 2}

    def test_sends_older_than_an_hour_do_not_count(self, notify_settings: Any) -> None:
        cfg = notify_settings(notify_rate_cap_per_hour=2, notify_quiet_hours="")
        assert sender.dispatch(cfg, _event()) is True
        assert sender.dispatch(cfg, _event()) is True
        assert sender.dispatch(cfg, _event()) is False

        # Age the recorded sends past the rolling window; the cap must then let traffic through.
        state = sender._read_state(cfg)
        old = (dt.datetime.now(dt.UTC) - dt.timedelta(minutes=90)).isoformat()
        state["sends"] = [old, old]
        sender._state_path(cfg).write_text(json.dumps(state), encoding="utf-8")
        assert sender.dispatch(cfg, _event()) is True

    def test_zero_disables_the_cap(self, notify_settings: Any) -> None:
        cfg = notify_settings(notify_rate_cap_per_hour=0, notify_quiet_hours="")
        assert all(sender.dispatch(cfg, _event()) for _ in range(30))


class TestNtfyChannel:
    def test_posts_topic_url_title_priority_and_tags(
        self, notify_settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict[str, Any]] = []

        class _Response:
            status_code = 200

        def _fake_post(url: str, **kwargs: Any) -> _Response:
            calls.append({"url": url, **kwargs})
            return _Response()

        monkeypatch.setattr(sender.httpx, "post", _fake_post)
        cfg = notify_settings(
            notify_channel="ntfy",
            notify_ntfy_url="https://ntfy.example/",
            notify_ntfy_topic="inv-secret-topic",
            notify_quiet_hours="",
        )
        assert sender.dispatch(cfg, _event(severity="attention")) is True

        (call,) = calls
        assert call["url"] == "https://ntfy.example/inv-secret-topic"
        assert call["headers"]["Title"] == "Cash fell 4%"
        assert call["headers"]["Priority"] == "5"  # attention
        assert call["headers"]["Tags"] == "manager.change"
        assert call["content"] == b"taxable cash 12,400 -> 11,900"
        assert call["timeout"] == 5.0

    def test_priority_tracks_severity(
        self, notify_settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[str] = []

        class _Response:
            status_code = 200

        monkeypatch.setattr(
            sender.httpx,
            "post",
            lambda url, **kw: (seen.append(kw["headers"]["Priority"]), _Response())[1],
        )
        cfg = notify_settings(
            notify_channel="ntfy",
            notify_ntfy_topic="t",
            notify_min_severity="fyi",
            notify_quiet_hours="",
        )
        for severity in ("attention", "notable", "fyi"):
            sender.dispatch(cfg, _event(severity=severity))  # type: ignore[arg-type]
        assert seen == ["5", "3", "2"]

    def test_a_raising_transport_returns_false_and_never_propagates(
        self, notify_settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(url: str, **kwargs: Any) -> None:
            raise RuntimeError("connection reset")

        monkeypatch.setattr(sender.httpx, "post", _boom)
        cfg = notify_settings(
            notify_channel="ntfy", notify_ntfy_topic="t", notify_quiet_hours=""
        )
        assert sender.dispatch(cfg, _event()) is False
        assert sender.last_sent_ts(cfg) is None

    def test_an_http_error_status_is_a_failure_not_a_send(
        self, notify_settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Response:
            status_code = 403

        monkeypatch.setattr(sender.httpx, "post", lambda url, **kw: _Response())
        cfg = notify_settings(
            notify_channel="ntfy", notify_ntfy_topic="t", notify_quiet_hours=""
        )
        assert sender.dispatch(cfg, _event()) is False

    def test_an_empty_topic_sends_nothing_rather_than_guessing_a_shared_name(
        self, notify_settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _unreachable(url: str, **kwargs: Any) -> None:
            raise AssertionError("must not POST without a topic")

        monkeypatch.setattr(sender.httpx, "post", _unreachable)
        cfg = notify_settings(
            notify_channel="ntfy", notify_ntfy_topic="", notify_quiet_hours=""
        )
        assert sender.dispatch(cfg, _event()) is False

    def test_a_non_ascii_headline_is_transliterated_rather_than_raising(
        self, notify_settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The persona corpus is Korean; a header that cannot be encoded must degrade, not drop.
        captured: list[str] = []

        class _Response:
            status_code = 200

        monkeypatch.setattr(
            sender.httpx,
            "post",
            lambda url, **kw: (captured.append(kw["headers"]["Title"]), _Response())[1],
        )
        cfg = notify_settings(
            notify_channel="ntfy", notify_ntfy_topic="t", notify_quiet_hours=""
        )
        assert sender.dispatch(cfg, _event(headline="현금 4% 감소")) is True
        assert captured[0].isascii()

    def test_an_unknown_channel_sends_nothing(self, notify_settings: Any) -> None:
        cfg = notify_settings(notify_channel="carrier-pigeon", notify_quiet_hours="")
        assert sender.dispatch(cfg, _event()) is False
