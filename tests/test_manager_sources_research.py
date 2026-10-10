"""Tests for `app.manager.sources_research`'s eight section builders.

Every upstream call inside a builder is bound at module level under its own name (see that module's
own docstring), so a test forces the `ok=False` path by monkeypatching that name directly on
`sources_research` -- no real repo data, ledger, or network call is ever touched. Fakes are plain
`SimpleNamespace` objects: the builders only ever read attributes off what their upstream calls
return, so a duck-typed stand-in is enough and avoids re-deriving every real pydantic model's full
set of required fields.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.manager import sources_research
from app.manager.models import FIGURE_KEYS, SnapshotSection
from app.manager.sources_research import SourceContext


def _ctx(settings: Settings) -> SourceContext:
    return SourceContext(
        settings=settings,
        as_of=dt.date(2026, 9, 9),
        scope="owner",
        now=dt.datetime(2026, 9, 9, 15, 0, tzinfo=dt.UTC),
    )


def _assert_valid_figures(section: SnapshotSection) -> None:
    """Every figure key -- section-level and per-item -- is one of `FIGURE_KEYS[section.key]`, and
    every value parses as `Decimal`."""
    allowed = set(FIGURE_KEYS[section.key])
    for key, value in section.figures.items():
        assert key in allowed, f"{section.key}: unexpected section figure key {key!r}"
        Decimal(value)  # raises InvalidOperation if not a decimal string
    for item in section.items:
        for key, value in item.figures.items():
            assert key in allowed, f"{section.key}: unexpected item figure key {key!r} on {item.id!r}"
            Decimal(value)


def _assert_unique_ids(section: SnapshotSection) -> None:
    ids = [item.id for item in section.items]
    assert len(ids) == len(set(ids)), f"{section.key}: duplicate item ids {ids}"


# ---------------------------------------------------------------------------
# research_section
# ---------------------------------------------------------------------------


def _raise(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("boom")


def test_research_section_fails_soft(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources_research, "get_next_round_briefing", _raise)
    section = sources_research.research_section(_ctx(settings))
    assert section.key == "research"
    assert section.ok is False
    assert section.warnings


def test_research_section_happy_path(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    briefing = SimpleNamespace(
        next_round_id="round-14", pre_registered=True,
        blockers=["No plan file committed for the next round yet."],
    )
    generations = [
        SimpleNamespace(
            generation=42,
            purpose="trading",
            status="succeeded",
            finished_at=dt.datetime(2026, 9, 8, 10, 0, tzinfo=dt.UTC),
            candidates=8,
            promoted=("g-1",),
            leader=SimpleNamespace(median_excess=Decimal("0.031")),
            field=SimpleNamespace(q_value=SimpleNamespace(median=Decimal("0.2"))),
        ),
        SimpleNamespace(
            generation=41,
            purpose="roth",
            status="failed",
            finished_at=dt.datetime(2026, 9, 7, 10, 0, tzinfo=dt.UTC),
            candidates=0,
            promoted=(),
            leader=None,
            field=SimpleNamespace(q_value=None),
        ),
    ]
    seats = [
        SimpleNamespace(
            genome_id="g-pending-1",
            agent_id="scout",
            purpose="trading",
            status="pending",
            requested_at=dt.datetime(2026, 9, 8, 11, 0, tzinfo=dt.UTC),
            reason="cleared the gate",
            median_excess=Decimal("0.04"),
            q_value=0.1,
        ),
        SimpleNamespace(
            genome_id="g-seated-1",
            agent_id="scout",
            purpose="trading",
            status="seated",
            requested_at=dt.datetime(2026, 9, 6, 11, 0, tzinfo=dt.UTC),
            reason="already decided",
            median_excess=Decimal("0.05"),
            q_value=0.05,
        ),
    ]
    promotions = [
        SimpleNamespace(
            genome_id="g-9",
            agent_id="scout",
            purpose="trading",
            promoted_at=dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.UTC),  # inside the 7-day lookback
            median_excess=Decimal("0.045"),
        ),
        SimpleNamespace(
            genome_id="g-old",
            agent_id="scout",
            purpose="trading",
            promoted_at=dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.UTC),  # outside the lookback
            median_excess=Decimal("0.02"),
        ),
    ]
    monkeypatch.setattr(sources_research, "get_next_round_briefing", lambda: briefing)
    monkeypatch.setattr(
        sources_research, "list_evolution_generations", lambda settings, limit=10: (generations, 2, 0)
    )
    monkeypatch.setattr(sources_research, "read_pending_seats", lambda settings: seats)
    monkeypatch.setattr(sources_research, "load_promotions", lambda settings: promotions)

    section = sources_research.research_section(_ctx(settings))

    assert section.key == "research"
    assert section.ok is True
    assert section.figures["generation"] == "42"
    assert section.figures["promoted_count"] == "1"
    # Only the "pending" seat should be counted/emitted, not the already-decided one.
    assert section.figures["pending_seats"] == "1"
    ids = {item.id for item in section.items}
    assert "gen:42" in ids
    assert "gen:41" in ids
    assert "g-pending-1" in ids
    assert "g-seated-1" not in ids
    # A blocker from the briefing lands as its own `blocker:` item, keyed by position.
    assert "blocker:0" in ids
    blocker_item = next(item for item in section.items if item.id == "blocker:0")
    assert blocker_item.text == "No plan file committed for the next round yet."
    # Only the promotion inside the 7-day lookback becomes a `promo:` item.
    assert "promo:g-9" in ids
    assert "promo:g-old" not in ids
    promo_item = next(item for item in section.items if item.id == "promo:g-9")
    assert promo_item.observed_at == "2026-09-08T12:00:00+00:00"
    assert promo_item.figures["promoted_count"] == "1"
    _assert_valid_figures(section)
    _assert_unique_ids(section)


def test_research_section_promotions_read_failure_is_a_warning_not_a_failure(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken `promotions.jsonl` must degrade to a warning, per this module's fail-soft convention
    -- the rest of the research section (generations, seats, blockers) must still come through."""
    briefing = SimpleNamespace(next_round_id="round-14", pre_registered=True, blockers=[])
    monkeypatch.setattr(sources_research, "get_next_round_briefing", lambda: briefing)
    monkeypatch.setattr(
        sources_research, "list_evolution_generations", lambda settings, limit=10: ([], 0, 0)
    )
    monkeypatch.setattr(sources_research, "read_pending_seats", lambda settings: [])
    monkeypatch.setattr(sources_research, "load_promotions", _raise)

    section = sources_research.research_section(_ctx(settings))

    assert section.ok is True
    assert section.warnings
    assert not any(item.id.startswith("promo:") for item in section.items)


# ---------------------------------------------------------------------------
# desks_section
# ---------------------------------------------------------------------------


class _FakeStage:
    def __init__(self, state: str) -> None:
        self.state = state


class _FakeRun:
    def __init__(
        self,
        run_id: str,
        *,
        created_at: dt.datetime,
        completed_at: dt.datetime | None,
        state: str = "succeeded",
        final_rating: str = "",
        degraded: bool = False,
        cost_usd: Decimal = Decimal("1.5"),
        stages: list[_FakeStage] | None = None,
    ) -> None:
        self.run_id = run_id
        self.created_at = created_at
        self.completed_at = completed_at
        self.state = state
        self.final_rating = final_rating
        self.degraded = degraded
        self.cost_usd = cost_usd
        self.stages = stages or [_FakeStage("succeeded"), _FakeStage("pending")]


class _FakeRunStore:
    def __init__(self, runs_by_kind: dict[str, list[_FakeRun]]) -> None:
        self._runs_by_kind = runs_by_kind

    def __call__(self, settings: Settings, kind: str) -> _FakeRunStore:
        self._kind = kind
        return self

    def list_runs(self, limit: int = 25) -> list[_FakeRun]:
        return self._runs_by_kind.get(self._kind, [])


def test_desks_section_fails_soft(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(settings: Settings, kind: str) -> None:
        raise RuntimeError("no store")

    monkeypatch.setattr(sources_research, "RunStore", _boom)
    section = sources_research.desks_section(_ctx(settings))
    assert section.key == "desks"
    assert section.ok is False
    assert section.warnings


def test_desks_section_windows_and_observed_at(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = dt.datetime(2026, 9, 9, 15, 0, tzinfo=dt.UTC)
    inside = _FakeRun(
        "run-inside",
        created_at=now - dt.timedelta(days=2),
        completed_at=now - dt.timedelta(days=1),
    )
    outside = _FakeRun(
        "run-outside",
        created_at=now - dt.timedelta(days=30),
        completed_at=now - dt.timedelta(days=29),
    )
    store = _FakeRunStore({"tradingagents": [inside, outside], "vibedesk": [], "workflow": []})
    monkeypatch.setattr(sources_research, "RunStore", store)

    section = sources_research.desks_section(_ctx(settings))

    assert section.key == "desks"
    assert section.ok is True
    ids = {item.id for item in section.items}
    assert ids == {"run-inside"}
    (item,) = section.items
    assert item.observed_at == (now - dt.timedelta(days=1)).isoformat()
    _assert_valid_figures(section)
    _assert_unique_ids(section)


# ---------------------------------------------------------------------------
# live_section
# ---------------------------------------------------------------------------


def test_live_section_fails_soft(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources_research, "list_live_decisions", _raise)
    section = sources_research.live_section(_ctx(settings))
    assert section.key == "live"
    assert section.ok is False
    assert section.warnings


def test_live_section_happy_path(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        SimpleNamespace(
            symbol="AAPL",
            decided_at=dt.datetime(2026, 9, 9, 14, 0, tzinfo=dt.UTC),
            stance="bullish",
            confidence=0.72,
            rationale="RSI turned up on strong volume, well past the usual noise band",
            price="228.10",
            cost_usd="0.03",
        ),
    ]
    monkeypatch.setattr(
        sources_research, "list_live_decisions", lambda settings, limit=100: records
    )
    section = sources_research.live_section(_ctx(settings))
    assert section.key == "live"
    assert section.ok is True
    assert len(section.items) == 1
    item = section.items[0]
    assert item.observed_at == "2026-09-09T14:00:00+00:00"
    assert item.figures["confidence"] == "0.72"
    _assert_valid_figures(section)
    _assert_unique_ids(section)


# ---------------------------------------------------------------------------
# personas_section
# ---------------------------------------------------------------------------


def test_personas_section_fails_soft(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources_research, "list_persona_cards", _raise)
    section = sources_research.personas_section(_ctx(settings))
    assert section.key == "personas"
    assert section.ok is False
    assert section.warnings


def test_personas_section_happy_path(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    cards = [
        SimpleNamespace(
            persona=SimpleNamespace(slug="p-1", display_name="Persona One"),
            note_count=12,
            as_of=dt.datetime(2026, 9, 9, 8, 0, tzinfo=dt.UTC),
            headline="Turned bullish on semis",
        ),
    ]
    wl = SimpleNamespace(
        entries=[
            SimpleNamespace(
                symbol="NVDA",
                bullish_count=3,
                bearish_count=1,
                as_of=dt.datetime(2026, 9, 9, 8, 0, tzinfo=dt.UTC),
                latest_reasoning="strong datacenter demand",
            ),
        ]
    )
    reg = SimpleNamespace(risk_on=4, risk_off=1, mixed=2, as_of=dt.datetime(2026, 9, 9, 9, 0, tzinfo=dt.UTC))
    monkeypatch.setattr(sources_research, "list_persona_cards", lambda settings: cards)
    monkeypatch.setattr(sources_research, "persona_watchlist", lambda settings: wl)
    monkeypatch.setattr(sources_research, "persona_regime", lambda settings: reg)
    monkeypatch.setattr(
        sources_research, "persona_chat_context",
        lambda settings, slug: SimpleNamespace(
            profile_version=1, profile_note_count=12, note_count=12, stale=False,
        ),
    )

    section = sources_research.personas_section(_ctx(settings))
    assert section.key == "personas"
    assert section.ok is True
    assert section.figures["risk_on"] == "4"
    ids = {item.id for item in section.items}
    # The persona's card is within the 7-day lookback, so it also surfaces as a `note:` item; the
    # profile is not stale (per the mock above), so no `persona:` item is emitted.
    assert ids == {"p-1", "note:p-1", "wl:NVDA"}
    _assert_valid_figures(section)
    _assert_unique_ids(section)


def test_personas_section_stale_profile_emits_persona_item(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    cards = [
        SimpleNamespace(
            persona=SimpleNamespace(slug="p-1", display_name="Persona One"),
            note_count=12,
            as_of=dt.datetime(2026, 9, 9, 8, 0, tzinfo=dt.UTC),
            headline="Turned bullish on semis",
        ),
    ]
    wl = SimpleNamespace(entries=[])
    reg = SimpleNamespace(risk_on=0, risk_off=0, mixed=0, as_of=dt.datetime(2026, 9, 9, 9, 0, tzinfo=dt.UTC))
    monkeypatch.setattr(sources_research, "list_persona_cards", lambda settings: cards)
    monkeypatch.setattr(sources_research, "persona_watchlist", lambda settings: wl)
    monkeypatch.setattr(sources_research, "persona_regime", lambda settings: reg)
    monkeypatch.setattr(
        sources_research, "persona_chat_context",
        lambda settings, slug: SimpleNamespace(
            profile_version=1, profile_note_count=3, note_count=12, stale=True,
        ),
    )

    section = sources_research.personas_section(_ctx(settings))
    assert section.ok is True
    ids = {item.id for item in section.items}
    assert "persona:p-1" in ids
    stale_item = next(item for item in section.items if item.id == "persona:p-1")
    assert "stale" in stale_item.text.lower()
    _assert_valid_figures(section)
    _assert_unique_ids(section)


def test_personas_section_chat_context_failure_is_a_warning_not_a_failure(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    cards = [
        SimpleNamespace(
            persona=SimpleNamespace(slug="p-1", display_name="Persona One"),
            note_count=12,
            as_of=dt.datetime(2026, 9, 9, 8, 0, tzinfo=dt.UTC),
            headline="Turned bullish on semis",
        ),
    ]
    wl = SimpleNamespace(entries=[])
    reg = SimpleNamespace(risk_on=0, risk_off=0, mixed=0, as_of=dt.datetime(2026, 9, 9, 9, 0, tzinfo=dt.UTC))
    monkeypatch.setattr(sources_research, "list_persona_cards", lambda settings: cards)
    monkeypatch.setattr(sources_research, "persona_watchlist", lambda settings: wl)
    monkeypatch.setattr(sources_research, "persona_regime", lambda settings: reg)
    monkeypatch.setattr(sources_research, "persona_chat_context", _raise)

    section = sources_research.personas_section(_ctx(settings))
    assert section.ok is True
    assert section.warnings
    assert not any(item.id.startswith("persona:") for item in section.items)


# ---------------------------------------------------------------------------
# market_section
# ---------------------------------------------------------------------------


def test_market_section_fails_soft(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources_research, "build_macro_snapshot", _raise)
    section = sources_research.market_section(_ctx(settings))
    assert section.key == "market"
    assert section.ok is False
    assert section.warnings


def test_market_section_happy_path(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    change = SimpleNamespace(day=0.01, week=-0.02, month=0.05)
    tile = SimpleNamespace(
        key="us10y",
        label="US 10Y",
        value=4.65,
        change=change,
        as_of=dt.date(2026, 9, 8),
    )
    mover = SimpleNamespace(
        symbol="SPY",
        label="S&P 500 ETF",
        price=560.12,
        change=change,
        as_of=dt.date(2026, 9, 8),
    )
    snap = SimpleNamespace(
        rates=[tile],
        oil=[],
        movers=[mover],
        fear_greed=SimpleNamespace(score=55.0),
        generated_at=dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.UTC),
    )
    monkeypatch.setattr(sources_research, "build_macro_snapshot", lambda settings: snap)

    section = sources_research.market_section(_ctx(settings))
    assert section.key == "market"
    assert section.ok is True
    assert section.figures["fear_greed"] == "55.0"
    ids = {item.id for item in section.items}
    assert ids == {"us10y", "SPY"}
    _assert_valid_figures(section)
    _assert_unique_ids(section)


def test_market_section_no_fear_greed_is_not_fabricated(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = SimpleNamespace(
        rates=[],
        oil=[],
        movers=[],
        fear_greed=None,
        generated_at=dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.UTC),
    )
    monkeypatch.setattr(sources_research, "build_macro_snapshot", lambda settings: snap)
    section = sources_research.market_section(_ctx(settings))
    assert "fear_greed" not in section.figures
    assert section.warnings


# ---------------------------------------------------------------------------
# events_section
# ---------------------------------------------------------------------------


def test_events_section_fails_soft(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources_research, "build_calendar", _raise)
    section = sources_research.events_section(_ctx(settings))
    assert section.key == "events"
    assert section.ok is False
    assert section.warnings


def test_events_section_happy_path(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        SimpleNamespace(
            kind="fomc",
            title="FOMC meeting",
            date=dt.date(2026, 9, 16),
            symbol=None,
            detail=None,
            confidence="confirmed",
        ),
        SimpleNamespace(
            kind="earnings",
            title="NVDA earnings",
            date=dt.date(2026, 9, 12),
            symbol="NVDA",
            detail="consensus EPS $2.09",
            confidence="estimated",
        ),
    ]
    cal = SimpleNamespace(events=events, generated_at=dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.UTC))
    monkeypatch.setattr(sources_research, "build_calendar", lambda **kwargs: cal)

    section = sources_research.events_section(_ctx(settings))
    assert section.key == "events"
    assert section.ok is True
    assert len(section.items) == 2
    nvda_item = next(item for item in section.items if "NVDA" in item.id)
    assert nvda_item.figures["days_until"] == "3"
    _assert_valid_figures(section)
    _assert_unique_ids(section)


# ---------------------------------------------------------------------------
# news_section
# ---------------------------------------------------------------------------


def test_news_section_fails_soft(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources_research, "build_macro_panel", _raise)
    section = sources_research.news_section(_ctx(settings))
    assert section.key == "news"
    assert section.ok is False
    assert section.warnings


def test_news_section_happy_path(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    articles = [
        SimpleNamespace(
            url="https://example.com/a",
            title="Fed signals a pause",
            published=dt.datetime(2026, 9, 9, 10, 0, tzinfo=dt.UTC),
            source="Reuters",
        ),
        SimpleNamespace(
            url="https://example.com/b",
            title="Oil slides on demand worries",
            published=dt.datetime(2026, 9, 9, 9, 0, tzinfo=dt.UTC),
            source="AP",
        ),
    ]
    panel = SimpleNamespace(news=articles, generated_at=dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.UTC))
    monkeypatch.setattr(sources_research, "build_macro_panel", lambda settings, **kwargs: panel)

    section = sources_research.news_section(_ctx(settings))
    assert section.key == "news"
    assert section.ok is True
    assert section.figures["count"] == "2"
    ids = {item.id for item in section.items}
    assert ids == {"https://example.com/a", "https://example.com/b"}
    _assert_valid_figures(section)
    _assert_unique_ids(section)


def test_news_section_dedupes_repeated_urls(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    articles = [
        SimpleNamespace(
            url="https://example.com/dup",
            title="Same story, syndicated",
            published=dt.datetime(2026, 9, 9, 10, 0, tzinfo=dt.UTC),
            source="Wire A",
        ),
        SimpleNamespace(
            url="https://example.com/dup",
            title="Same story, syndicated (mirror)",
            published=dt.datetime(2026, 9, 9, 10, 5, tzinfo=dt.UTC),
            source="Wire B",
        ),
    ]
    panel = SimpleNamespace(news=articles, generated_at=dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.UTC))
    monkeypatch.setattr(sources_research, "build_macro_panel", lambda settings, **kwargs: panel)

    section = sources_research.news_section(_ctx(settings))
    _assert_unique_ids(section)
    assert section.items[1].id == "https://example.com/dup#2"


# ---------------------------------------------------------------------------
# data_section
# ---------------------------------------------------------------------------


def test_data_section_fails_soft(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources_research, "freshness_report", _raise)
    section = sources_research.data_section(_ctx(settings))
    assert section.key == "data"
    assert section.ok is False
    assert section.warnings


def test_data_section_does_not_fabricate_freshness_for_unknown(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    rep = {
        "as_of": "2026-09-09T15:00:00+00:00",
        "sources": [
            {
                "key": "macro_snapshot",
                "provider": "FRED",
                "status": "unknown",
                "detail": "shared URL-less HTTP cache; cannot attribute an mtime to this source",
                "last_updated": None,
                "age_seconds": None,
            },
            {
                "key": "bars_daily",
                "provider": "Yahoo chart API",
                "status": "fresh",
                "detail": "last written 2026-09-09T14:55:00+00:00",
                "last_updated": "2026-09-09T14:55:00+00:00",
                "age_seconds": 300,
            },
            {
                "key": "social_snapshots",
                "provider": "StockTwits + Reddit",
                "status": "stale",
                "detail": "last written 3 days ago",
                "last_updated": "2026-09-06T14:55:00+00:00",
                "age_seconds": 259200,
            },
        ],
    }
    monkeypatch.setattr(sources_research, "freshness_report", lambda settings: rep)

    section = sources_research.data_section(_ctx(settings))
    assert section.key == "data"
    assert section.ok is True
    assert section.figures["stale_count"] == "1"
    assert section.figures["unknown_count"] == "1"

    by_id = {item.id: item for item in section.items}
    unknown_item = by_id["macro_snapshot"]
    # The unknown source must never carry an age -- that would be reporting a guess as a measurement.
    assert "age_seconds" not in unknown_item.figures
    assert unknown_item.observed_at is None
    assert "unknown" in unknown_item.text

    fresh_item = by_id["bars_daily"]
    assert fresh_item.figures["age_seconds"] == "300"
    assert fresh_item.observed_at == "2026-09-09T14:55:00+00:00"

    _assert_valid_figures(section)
    _assert_unique_ids(section)


def test_data_section_emits_sweep_item_on_refresh_failure(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    rep = {
        "as_of": "2026-09-09T15:00:00+00:00",
        "sources": [],
        "refresh": {
            "running": False,
            "failed": 3,
            "failed_symbols": ["AAPL:1d", "MSFT:1d"],
            "error": None,
            "started_at": "2026-09-09T14:00:00+00:00",
            "finished_at": "2026-09-09T14:05:00+00:00",
        },
    }
    monkeypatch.setattr(sources_research, "freshness_report", lambda settings: rep)
    monkeypatch.setattr(
        sources_research, "social_daemon_status", lambda: {"healthy": True}
    )

    section = sources_research.data_section(_ctx(settings))
    assert section.ok is True
    ids = {item.id for item in section.items}
    assert "sweep:refresh" in ids
    sweep_item = next(item for item in section.items if item.id == "sweep:refresh")
    assert "failed" in sweep_item.text.lower()
    assert sweep_item.observed_at == "2026-09-09T14:05:00+00:00"
    _assert_valid_figures(section)
    _assert_unique_ids(section)


def test_data_section_no_sweep_item_when_nothing_failed(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    rep = {
        "as_of": "2026-09-09T15:00:00+00:00",
        "sources": [],
        "refresh": {"running": False, "failed": 0, "error": None},
    }
    monkeypatch.setattr(sources_research, "freshness_report", lambda settings: rep)
    monkeypatch.setattr(sources_research, "social_daemon_status", lambda: {"healthy": True})

    section = sources_research.data_section(_ctx(settings))
    assert section.ok is True
    assert not any(item.id.startswith("sweep:") for item in section.items)


def test_data_section_emits_daemon_item_when_social_scheduler_unhealthy(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    rep = {"as_of": "2026-09-09T15:00:00+00:00", "sources": []}
    social = {
        "healthy": False,
        "consecutive_all_failed_ticks": 6,
        "last_error": "connection reset",
        "last_tick_at": "2026-09-09T14:30:00+00:00",
    }
    monkeypatch.setattr(sources_research, "freshness_report", lambda settings: rep)
    monkeypatch.setattr(sources_research, "social_daemon_status", lambda: social)

    section = sources_research.data_section(_ctx(settings))
    assert section.ok is True
    ids = {item.id for item in section.items}
    assert "daemon:social" in ids
    daemon_item = next(item for item in section.items if item.id == "daemon:social")
    assert "unhealthy" in daemon_item.text.lower()
    assert daemon_item.observed_at == "2026-09-09T14:30:00+00:00"
    _assert_valid_figures(section)
    _assert_unique_ids(section)


def test_data_section_social_daemon_status_failure_is_a_warning_not_a_failure(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    rep = {"as_of": "2026-09-09T15:00:00+00:00", "sources": []}
    monkeypatch.setattr(sources_research, "freshness_report", lambda settings: rep)
    monkeypatch.setattr(sources_research, "social_daemon_status", _raise)

    section = sources_research.data_section(_ctx(settings))
    assert section.ok is True
    assert section.warnings
    assert not any(item.id.startswith("daemon:") for item in section.items)


# ---------------------------------------------------------------------------
# Cross-cutting: every builder returns its own key, even when unconfigured/erroring by default
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "area,builder",
    [
        ("research", sources_research.research_section),
        ("desks", sources_research.desks_section),
        ("live", sources_research.live_section),
        ("personas", sources_research.personas_section),
        ("market", sources_research.market_section),
        ("events", sources_research.events_section),
        ("news", sources_research.news_section),
        ("data", sources_research.data_section),
    ],
)
def test_builder_never_raises_against_real_settings(
    area: str, builder: object, settings: Settings
) -> None:
    """Every builder is callable against a real (if empty/tmp-rooted) `Settings` without raising --
    whatever it finds (or does not find) on disk, it must degrade to `ok=False` with a reason rather
    than propagate an exception. This is the same guarantee `app.manager.sources.collect` relies on as
    a backstop; here it is proven per builder, not only through the aggregator."""
    section = builder(_ctx(settings))  # type: ignore[operator]
    assert section.key == area
    assert isinstance(section.ok, bool)
