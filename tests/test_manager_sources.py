"""Tests for `app.manager.sources.collect` -- the layer-A dispatcher.

The fourteen area builders themselves (`app.manager.sources_owner`, `app.manager.sources_research`)
have their own exhaustive per-area test suites (`tests/test_manager_sources_owner.py`,
`tests/test_manager_sources_research.py`), each hitting a *specific* upstream service directly. This
file does not repeat that: it tests `collect()`'s own contract -- dispatch order, uniqueness, the
member-scope owner-only skip, the fail-soft backstop around a builder call, the unpinned-figure-key
strip, and item-id stability -- by monkeypatching the fourteen section-builder functions on
`sources_owner`/`sources_research` directly (the same seam `app.manager.sources._builders()` reads).

One full-stack test (`test_weight_pct_is_a_fraction_not_a_percent`) goes all the way down to
`app.api.portfolio._build_report`, the way the sibling suites do, to prove the "never `'3.1'`, always
`'0.031'`" rule holds through the real `account_section` builder and not just through a canned
`SnapshotSection` this file hands-rolls.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest

from app.config import Settings
from app.manager import sources, sources_owner, sources_research
from app.manager.models import AREAS, FIGURE_KEYS, ManagerSnapshot, SnapshotSection, SourceRef

AS_OF = dt.date(2026, 6, 15)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _section(key: str, *, ok: bool = True, n_items: int = 0, extra_figure: bool = False) -> SnapshotSection:
    """A minimal, deterministic `SnapshotSection` for `key` -- same shape on every call given the
    same arguments, which is what the id-stability test relies on."""
    figures: dict[str, str] = {}
    allowed = FIGURE_KEYS.get(key, ())
    if allowed:
        figures[allowed[0]] = "1"
    if extra_figure:
        figures["not_a_pinned_key"] = "999"
    return SnapshotSection(
        key=key,  # type: ignore[arg-type]
        ok=ok,
        as_of=AS_OF.isoformat(),
        text=f"canned {key}",
        figures=figures,
        items=_canned_items(key, n_items),
        warnings=() if ok else (f"{key} failed",),
    )


def _canned_items(key: str, n: int) -> tuple[Any, ...]:
    from app.manager.models import SectionItem

    return tuple(
        SectionItem(
            id=f"{key}-{i}",
            label=f"{key} {i}",
            refs=(SourceRef(kind="symbol", id=f"{key}-{i}", label=f"{key} {i}"),),
            text=f"{key} item {i}",
        )
        for i in range(n)
    )


def _patch_all_builders(
    monkeypatch: pytest.MonkeyPatch,
    *,
    override: dict[str, Any] | None = None,
) -> dict[str, list[int]]:
    """Monkeypatch every one of the fourteen section-builder functions to a canned, call-counted
    stand-in, optionally replacing specific areas' builders with `override[area]`. Returns a
    `{area: [call_count]}` dict a test can inspect after calling `collect()` -- the "never calls the
    owner-only source for scope='member'" spy.
    """
    calls: dict[str, list[int]] = {area: [0] for area in AREAS}
    override = override or {}

    owner_areas = {
        "account": "account_section",
        "tax": "tax_section",
        "paperdesk": "paperdesk_section",
        "persona_books": "persona_books_section",
        "persona_traders": "persona_traders_section",
        "activity": "activity_section",
    }
    research_areas = {
        "research": "research_section",
        "desks": "desks_section",
        "live": "live_section",
        "personas": "personas_section",
        "market": "market_section",
        "events": "events_section",
        "news": "news_section",
        "data": "data_section",
    }

    def _make(area: str) -> Any:
        if area in override:
            fn = override[area]

            def _counted(ctx: Any, _area: str = area, _fn: Any = fn) -> SnapshotSection:
                calls[_area][0] += 1
                return _fn(ctx)

            return _counted

        def _default(ctx: Any, _area: str = area) -> SnapshotSection:
            calls[_area][0] += 1
            return _section(_area, n_items=2)

        return _default

    for area, attr in owner_areas.items():
        monkeypatch.setattr(sources_owner, attr, _make(area))
    for area, attr in research_areas.items():
        monkeypatch.setattr(sources_research, attr, _make(area))

    return calls


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def test_collect_returns_all_areas_in_order_with_unique_keys(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_all_builders(monkeypatch)

    snapshot = sources.collect(settings, scope="owner", as_of=AS_OF)

    assert isinstance(snapshot, ManagerSnapshot)
    assert snapshot.scope == "owner"
    assert snapshot.as_of == AS_OF.isoformat()
    assert [section.key for section in snapshot.sections] == list(AREAS)
    keys = [section.key for section in snapshot.sections]
    assert len(keys) == len(set(keys))
    assert all(section.ok for section in snapshot.sections)


def test_every_figure_key_is_pinned(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every section's `figures` and every item's `figures` are a subset of `FIGURE_KEYS[area]` --
    including the one area a builder is rigged to emit a stray key for, proving `collect()`'s own
    strip-unpinned-figures backstop, not just that well-behaved builders stay in bounds."""

    def _rogue(ctx: Any) -> SnapshotSection:
        return _section("account", n_items=1, extra_figure=True)

    _patch_all_builders(monkeypatch, override={"account": _rogue})

    snapshot = sources.collect(settings, scope="owner", as_of=AS_OF)

    for section in snapshot.sections:
        allowed = set(FIGURE_KEYS[section.key])
        assert set(section.figures).issubset(allowed), section.key
        for item in section.items:
            assert set(item.figures).issubset(allowed), (section.key, item.id)

    account = snapshot.section("account")
    assert account is not None
    assert "not_a_pinned_key" not in account.figures


def test_a_raising_builder_degrades_only_its_own_area(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(ctx: Any) -> SnapshotSection:
        raise RuntimeError("upstream is down")

    calls = _patch_all_builders(monkeypatch, override={"market": _boom})

    snapshot = sources.collect(settings, scope="owner", as_of=AS_OF)

    market = snapshot.section("market")
    assert market is not None
    assert market.ok is False
    assert market.items == ()
    assert market.figures == {}
    assert any("upstream is down" in w for w in market.warnings)
    assert any("market" in w for w in snapshot.warnings)

    other_sections = [s for s in snapshot.sections if s.key != "market"]
    assert len(other_sections) == 13
    assert all(section.ok for section in other_sections)
    # every other builder was still called exactly once -- one failure does not short-circuit collect
    assert all(count == [1] for area, count in calls.items() if area != "market")


def test_a_builder_that_returns_ok_false_is_carried_through_unchanged(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A builder is allowed to report its own `ok=False` (its *documented* fail-soft path, not an
    exception) -- `collect()` must not paper over that or treat it differently from a raise."""

    def _degraded(ctx: Any) -> SnapshotSection:
        return SnapshotSection(key="news", ok=False, warnings=("provider unavailable",))

    _patch_all_builders(monkeypatch, override={"news": _degraded})

    snapshot = sources.collect(settings, scope="owner", as_of=AS_OF)

    news = snapshot.section("news")
    assert news is not None
    assert news.ok is False
    assert news.warnings == ("provider unavailable",)
    assert "news: provider unavailable" in snapshot.warnings


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def test_member_scope_never_calls_owner_only_sources(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner-only areas are a deliberate design omission for `scope="member"`, not a collection
    failure: their builder is never called, their section is absent from `sections` entirely (never
    present with `ok=False`), and they are never named in `snapshot.warnings` either -- see
    `app.manager.models.AREAS`'s own docstring on "missing" vs. "failed"."""
    calls = _patch_all_builders(monkeypatch)

    snapshot = sources.collect(settings, scope="member", as_of=AS_OF)

    for area in sources.OWNER_ONLY_AREAS:
        assert calls[area] == [0], f"{area} builder was called for scope=member"
        assert snapshot.section(area) is None
        assert not any(area in w for w in snapshot.warnings), f"{area} reported, not just absent"

    present_keys = [section.key for section in snapshot.sections]
    assert present_keys == [a for a in AREAS if a not in sources.OWNER_ONLY_AREAS]

    for area in AREAS:
        if area in sources.OWNER_ONLY_AREAS:
            continue
        assert calls[area] == [1], f"{area} builder should have been called exactly once"
        section = snapshot.section(area)
        assert section is not None
        assert section.ok is True

    assert snapshot.scope == "member"


def test_owner_scope_calls_every_source_exactly_once(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_all_builders(monkeypatch)

    sources.collect(settings, scope="owner", as_of=AS_OF)

    assert all(count == [1] for count in calls.values())


# ---------------------------------------------------------------------------
# Tax: deferred vs permanently disallowed must never be summed
# ---------------------------------------------------------------------------


def test_tax_deferred_and_permanent_are_separate_figures(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _tax(ctx: Any) -> SnapshotSection:
        return SnapshotSection(
            key="tax",
            ok=True,
            figures={
                "ytd_short_gain": "100.00",
                "ytd_long_gain": "0.00",
                "ytd_net_gain": "100.00",
                "deferred_disallowed": "250.00",
                "permanently_disallowed": "75.00",
                "open_window_count": "1",
            },
        )

    _patch_all_builders(monkeypatch, override={"tax": _tax})

    snapshot = sources.collect(settings, scope="owner", as_of=AS_OF)

    tax = snapshot.section("tax")
    assert tax is not None
    assert tax.figures["deferred_disallowed"] == "250.00"
    assert tax.figures["permanently_disallowed"] == "75.00"
    # never summed into one another or into a third figure under either name
    assert "deferred_disallowed" in FIGURE_KEYS["tax"]
    assert "permanently_disallowed" in FIGURE_KEYS["tax"]
    assert Decimal(tax.figures["deferred_disallowed"]) != Decimal(
        tax.figures["deferred_disallowed"]
    ) + Decimal(tax.figures["permanently_disallowed"])


# ---------------------------------------------------------------------------
# Item id stability
# ---------------------------------------------------------------------------


def test_item_ids_are_stable_across_two_calls(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_all_builders(monkeypatch)

    first = sources.collect(settings, scope="owner", as_of=AS_OF)
    second = sources.collect(settings, scope="owner", as_of=AS_OF)

    for area in AREAS:
        first_ids = [item.id for item in first.section(area).items]  # type: ignore[union-attr]
        second_ids = [item.id for item in second.section(area).items]  # type: ignore[union-attr]
        assert first_ids == second_ids, area


# ---------------------------------------------------------------------------
# Full-stack: rates are fractions, never a pre-multiplied percent
# ---------------------------------------------------------------------------


def test_weight_pct_is_a_fraction_not_a_percent(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A position at 3.1% weight must render `weight_pct == "0.031"` through the real
    `account_section` builder -- never `"3.1"` -- proving the fraction convention holds end to end
    through `collect()`, not only in a hand-rolled canned section."""
    from app.api.portfolio import PortfolioReport, Position

    position = Position(
        instrument_id="inst-aapl",
        symbol="AAPL",
        quantity=Decimal(10),
        cost_basis=Decimal("1000.00"),
        basis_per_share=Decimal("100.00"),
        price=Decimal("150.00"),
        price_as_of=AS_OF,
        market_value=Decimal("1500.00"),
        unrealized=Decimal("500.00"),
        unrealized_pct=0.5,
        weight_pct=0.031,
        sector="Technology",
        previous_close=Decimal("148.00"),
        day_change=Decimal("20.00"),
        day_change_pct=0.0135,
        short_term_quantity=Decimal(10),
        long_term_quantity=Decimal(0),
        earliest_acquired=dt.date(2026, 1, 1),
        latest_acquired=dt.date(2026, 1, 1),
        lot_count=1,
        basis_uncertain=False,
        fees_unknown=False,
        wash_sale_adjustment=Decimal(0),
        accounts=[],
    )
    report = PortfolioReport(
        as_of=AS_OF,
        generated_at=dt.datetime(2026, 6, 15, 18, 0, tzinfo=dt.UTC),
        positions=[position],
        total_cost_basis=Decimal("1000.00"),
        total_market_value=Decimal("1500.00"),
        total_unrealized=Decimal("500.00"),
        total_unrealized_pct=0.5,
        priced_position_count=1,
        unpriced_symbols=[],
        cash_balance=Decimal("2500.00"),
        equity_is_complete=True,
        accounts_without_cash=[],
        positions_with_uncertain_basis=0,
        positions_with_unknown_fees=0,
        warnings=[],
        warning_groups=[],
        total_day_change=Decimal("20.00"),
        total_day_change_pct=0.0135,
    )
    monkeypatch.setattr("app.api.portfolio._build_report", lambda: report)

    # Every other builder is patched to a cheap canned stand-in so this test exercises exactly one
    # real upstream call (`_build_report`), through the real `account_section`, and stays fast/
    # offline for the other thirteen areas like the rest of this file.
    real_account_section = sources_owner.account_section
    _patch_all_builders(monkeypatch, override={"account": real_account_section})

    snapshot = sources.collect(settings, scope="owner", as_of=AS_OF)

    account = snapshot.section("account")
    assert account is not None
    assert account.ok is True
    assert len(account.items) == 1
    weight_pct = account.items[0].figures["weight_pct"]
    assert weight_pct == "0.031"
    assert weight_pct != "3.1"
    Decimal(weight_pct)  # parses cleanly as a decimal string
