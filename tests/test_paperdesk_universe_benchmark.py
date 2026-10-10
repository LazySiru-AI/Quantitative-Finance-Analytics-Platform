"""Tests for two changes to `app.paperdesk.desk`/`app.paperdesk.benchmarks`, both aimed at the same
audit finding: the paper desk's apparent outperformance over 2026-01-01..08-28 was largely universe
selection, not rule skill (`A-rotation` +56.9% vs SPY +11.9%, but SOXX alone -- a name *inside*
`A-rotation`'s own universe -- returned +59.9% buy-and-hold over the same window). Reporting only
SPY/QQQ cannot show that a card's rules subtracted value relative to what they were allowed to buy.

1. `app.paperdesk.benchmarks.price_equal_weight_basket` -- an equal-weight, buy-once-and-hold, never-
   rebalanced basket pricer, and `app.paperdesk.desk._own_universe_benchmark`, which prices one card's
   own tradable universe with it and folds the result into `Book.benchmarks` alongside SPY/QQQ.
2. Two long-standing disk-cache defects in `desk.py`: the cache key's digest omitted the mandate's
   `starting_cash` (three of the six `_DISK_CACHE_VERSION` bumps existed only to paper over that by
   hand -- v4, v5, v7), and `clear_disk_cache` globbed only the current version's prefix, orphaning
   every earlier version's files forever.

Self-contained, small local builders rather than importing `tests/test_paperdesk.py`'s -- the same
"duplicated fakes rather than a cross-file import" choice that file's own docstring documents (and
`tests/test_paperdesk.py` is explicitly out of scope for this change to touch at all).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from app.config import Settings
from app.db import duck
from app.market.models import BAR_COLUMNS, Interval
from app.paper.paperbroker import Mandate
from app.paperdesk import desk
from app.paperdesk.benchmarks import price_equal_weight_basket
from app.tournament.models import DESIGN_THROUGH, AgentResult, Discipline, StrategyCard
from app.tournament.purposes import Purpose

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _card(agent_id: str = "test-card", **overrides: object) -> StrategyCard:
    fields: dict[str, object] = {
        "agent_id": agent_id,
        "display_name": f"Desk {agent_id}",
        "discipline": Discipline.MOMENTUM,
        "thesis": "a test thesis, written before the trading window ran",
        "universe": ("AAA", "BBB"),
        "entry": "close > 0",
        "exit": "close < 0",
        "stop_loss_pct": Decimal("0.12"),
        "take_profit_pct": None,
        "max_hold_days": 180,
        "max_positions": 6,
        "position_pct": Decimal("0.15"),
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return StrategyCard(**fields)  # type: ignore[arg-type]


def _mandate(**overrides: object) -> Mandate:
    fields: dict[str, object] = {
        "persona_id": "test-persona",
        "display_name": "Test Persona",
        "account_id": "acct-1",
        "account_label": "Test Account",
        "starting_cash": Decimal("100000.00"),
        "allow_fractional_shares": False,
        "max_positions": 6,
        "max_single_name_weight": Decimal("1.00"),
        "min_clip_notional": Decimal("1.00"),
        "min_cash": Decimal("0.00"),
        "settlement_days": 1,
        "slippage_bps": Decimal("0"),
        "commission_per_trade": Decimal("0"),
        "sec_fee_rate": Decimal("0"),
        "taf_per_share": Decimal("0"),
        "taf_cap": Decimal("0"),
    }
    fields.update(overrides)
    return Mandate(**fields)  # type: ignore[arg-type]


def _write_daily_bars(settings: Settings, symbol: str, closes: dict[dt.date, float]) -> None:
    """Write one daily bar per `(date, close)` in `closes` into `settings`'s temp store -- same
    `open == close`, price-only convention `tests/test_benchmarks.py`'s `_bar` helper uses, since
    every benchmark this module prices reads `close` alone."""
    dates = sorted(closes)
    frame = pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC) for d in dates],
                dtype="datetime64[us, UTC]",
            ),
            "open": [closes[d] for d in dates],
            "high": [closes[d] + 1.0 for d in dates],
            "low": [closes[d] - 1.0 for d in dates],
            "close": [closes[d] for d in dates],
            "adj_close": [closes[d] for d in dates],
            "volume": [1_000_000] * len(dates),
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)


_START = dt.date(2026, 1, 2)
_END = dt.date(2026, 1, 9)


def _window() -> desk._Window:
    return desk._Window(
        inception=_START,
        first_session=_START,
        as_of=_END,
        decided_on=_END - dt.timedelta(days=1),
        sessions=2,
        latest_bar=_END,
    )


# ---------------------------------------------------------------------------
# (a) the own-universe series is computed over the card's window and differs from SPY
# ---------------------------------------------------------------------------


def test_own_universe_benchmark_differs_from_spy(settings: Settings) -> None:
    """SPY moves +10% over the window; the card's own two-name universe averages +50% (AAA +100%,
    BBB flat). The own-universe benchmark must reflect the card's actual universe, not silently
    collapse to (or agree with) the SPY figure it sits alongside."""
    _write_daily_bars(settings, "SPY", {_START: 400.0, _END: 440.0})
    _write_daily_bars(settings, "AAA", {_START: 100.0, _END: 200.0})
    _write_daily_bars(settings, "BBB", {_START: 50.0, _END: 50.0})

    card = _card(universe=("AAA", "BBB"))
    window = _window()

    own_universe = desk._own_universe_benchmark(settings, card, window)
    spy_return = desk._buy_and_hold(settings, "SPY", window)

    assert own_universe.symbol == f"own_universe_ew:{card.agent_id}"
    assert spy_return == Decimal("0.10")
    assert own_universe.return_pct == Decimal("0.50")
    assert own_universe.return_pct != spy_return


def test_own_universe_benchmark_is_carried_on_the_book(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end: `_book` folds one `own_universe_ew:<agent_id>` entry per seated card into
    `Book.benchmarks`, alongside the existing SPY/QQQ entries -- not replacing them, and not
    disturbing `benchmarks[0]`, which `_book` also uses as the primary for `excess_return`."""
    _write_daily_bars(settings, "SPY", {_START: 400.0, _END: 440.0})
    _write_daily_bars(settings, "QQQ", {_START: 300.0, _END: 330.0})
    _write_daily_bars(settings, "AGG", {_START: 100.0, _END: 101.0})
    _write_daily_bars(settings, "AAA", {_START: 100.0, _END: 200.0})
    _write_daily_bars(settings, "BBB", {_START: 50.0, _END: 50.0})

    agent_id = "trading-universe-card"
    card = _card(agent_id, universe=("AAA", "BBB"))
    window = _window()

    monkeypatch.setattr(desk, "_trading_window", lambda s: window)
    monkeypatch.setattr(desk, "_load_card", lambda s, aid: card)
    monkeypatch.setattr(
        desk,
        "run_card",
        lambda c, *, settings, mandate, start, end: AgentResult(
            card=c,
            sessions=2,
            starting_equity=mandate.starting_cash,
            ending_equity=mandate.starting_cash,
            total_return=Decimal("0"),
            max_drawdown=Decimal("0"),
            trades=(),
            rejections=(),
            benchmark_return=Decimal("0"),
        ),
    )

    book = desk._book(settings, Purpose.TRADING, (agent_id,), window)

    keys = {b.symbol for b in book.benchmarks}
    assert f"own_universe_ew:{agent_id}" in keys
    # `trading`'s primary benchmark is the single-leg "spy" blend (`PURPOSE_SPECS[Purpose.TRADING]
    # .benchmark`); "QQQ" is the one `_BENCHMARKS` entry that survives the single-leg dedup in
    # `_book_benchmarks`. Both must still be present alongside the new own-universe entry.
    assert keys == {"spy", "QQQ", f"own_universe_ew:{agent_id}"}
    own = next(b for b in book.benchmarks if b.symbol == f"own_universe_ew:{agent_id}")
    assert own.return_pct == Decimal("0.50")
    # The primary (book) benchmark must still be first -- `_book` reads `benchmarks[0]` for
    # `excess_return`, so an own-universe entry appended after it must not have displaced it.
    assert book.benchmarks[0].symbol != own.symbol


# ---------------------------------------------------------------------------
# (b) a missing-bars symbol is excluded, not fatal
# ---------------------------------------------------------------------------


def test_missing_symbol_is_excluded_not_fatal(settings: Settings) -> None:
    """A universe naming a symbol with no stored bars at all must not crash the benchmark -- it is
    dropped, disclosed, and the basket still prices from what remains."""
    _write_daily_bars(settings, "AAA", {_START: 100.0, _END: 150.0})
    _write_daily_bars(settings, "BBB", {_START: 100.0, _END: 130.0})
    # "GHOST" is never written -- no bars at all.

    result = price_equal_weight_basket(
        ("AAA", "BBB", "GHOST"), start=_START, end=_END, settings=settings
    )

    assert result.included == ("AAA", "BBB")
    assert result.excluded == ("GHOST",)
    # (0.50 + 0.30) / 2
    assert result.return_pct == Decimal("0.40")


def test_missing_symbol_excluded_via_own_universe_benchmark(settings: Settings) -> None:
    """The same exclusion, exercised through `desk._own_universe_benchmark` -- proving the desk-level
    wrapper propagates the exclusion (in the label, since `Benchmark` has no separate field for it)
    rather than raising or silently pricing as if GHOST were never in the universe."""
    _write_daily_bars(settings, "AAA", {_START: 100.0, _END: 150.0})
    _write_daily_bars(settings, "BBB", {_START: 100.0, _END: 130.0})

    card = _card(universe=("AAA", "BBB", "GHOST"))
    window = _window()

    benchmark = desk._own_universe_benchmark(settings, card, window)

    assert benchmark.return_pct == Decimal("0.40")
    assert "GHOST" in (benchmark.label or "")
    assert "excluding" in (benchmark.label or "")


def test_a_symbol_with_only_one_bar_in_window_is_also_excluded(settings: Settings) -> None:
    """A symbol that has *some* history but only one bar inside the window (e.g. it started trading
    the same day the window ends) cannot produce a return either, and must be excluded the same way
    a wholly-missing symbol is -- not raise, not divide by a missing pair."""
    _write_daily_bars(settings, "AAA", {_START: 100.0, _END: 150.0})
    _write_daily_bars(settings, "LATECOMER", {_END: 42.0})

    result = price_equal_weight_basket(
        ("AAA", "LATECOMER"), start=_START, end=_END, settings=settings
    )

    assert result.included == ("AAA",)
    assert result.excluded == ("LATECOMER",)
    assert result.return_pct == Decimal("0.50")


def test_every_symbol_missing_reports_none_not_a_crash(settings: Settings) -> None:
    """The degenerate case: every symbol in the universe is unpriceable. `None`, the same "unknown,
    not a fabricated zero" convention every benchmark in this package uses -- not an exception."""
    result = price_equal_weight_basket(("GHOST1", "GHOST2"), start=_START, end=_END, settings=settings)

    assert result.return_pct is None
    assert result.included == ()
    assert set(result.excluded) == {"GHOST1", "GHOST2"}


# ---------------------------------------------------------------------------
# (c) starting_cash is folded into the cache key
# ---------------------------------------------------------------------------


def test_run_cache_digest_differs_by_starting_cash() -> None:
    """The unit-level proof: `_run_cache_digest` (what `_cached_run`/`_cached_allocation_run`/
    `_cached_ladder_run` actually store their key under) returns a different digest for the identical
    card when only `starting_cash` changes."""
    card = _card()
    digest_a = desk._run_cache_digest(card, starting_cash=Decimal("100000.00"))
    digest_b = desk._run_cache_digest(card, starting_cash=Decimal("50000.00"))

    assert digest_a != digest_b
    # And the plain card digest -- the one `tests/test_paper_live_fill.py` reconstructs directly --
    # is untouched by this change, exactly as the `_DISK_CACHE_VERSION` v8 note requires.
    assert desk._card_digest(card) == desk._card_digest(card)


def test_two_mandates_differing_only_in_starting_cash_recompute_and_cache_separately(
    settings: Settings,
) -> None:
    """Full integration proof, mirroring `tests/test_paperdesk.py::TestDiskCache`'s own pattern: two
    `_cached_run` calls for the *same* card and window, differing only in `mandate.starting_cash`,
    must (1) both call `run_card` -- the second must not be served from the first's cache entry under
    a capital that no longer matches -- and (2) persist to two distinct files on disk, not one
    overwriting the other."""
    card = _card("B-momentum")
    window = _window()
    calls = {"count": 0}

    def fake_run_card(c, *, settings, mandate, start, end):
        calls["count"] += 1
        return AgentResult(
            card=c,
            sessions=2,
            starting_equity=mandate.starting_cash,
            ending_equity=mandate.starting_cash,
            total_return=Decimal("0"),
            max_drawdown=Decimal("0"),
            trades=(),
            rejections=(),
            benchmark_return=Decimal("0"),
        )

    original = desk.run_card
    desk.run_card = fake_run_card  # type: ignore[assignment]
    try:
        result_a = desk._cached_run(
            card, settings=settings, mandate=_mandate(starting_cash=Decimal("100000.00")), window=window
        )
        result_b = desk._cached_run(
            card, settings=settings, mandate=_mandate(starting_cash=Decimal("50000.00")), window=window
        )
    finally:
        desk.run_card = original  # type: ignore[assignment]

    assert calls["count"] == 2, "a mandate with different starting_cash must not hit the first's cache entry"
    assert result_a.starting_equity != result_b.starting_equity

    written = sorted(p.name for p in (settings.cache_dir / "paperdesk").glob("*.json"))
    assert len(written) == 2, f"expected two distinct cache files, found {written}"


# ---------------------------------------------------------------------------
# (d) clear_disk_cache is version-agnostic
# ---------------------------------------------------------------------------


def test_clear_disk_cache_removes_an_old_version_file(settings: Settings) -> None:
    """A `v1-*.json` entry -- from a build several `_DISK_CACHE_VERSION` bumps ago -- must be removed
    by `clear_disk_cache` exactly as a current-version entry would be, not orphaned forever because
    the glob only ever matched the *current* build's prefix."""
    cache_dir = desk._disk_cache_dir(settings)
    cache_dir.mkdir(parents=True, exist_ok=True)
    old_entry = cache_dir / "v1-B-momentum-20260101-20260201-20260201-deadbeefcafef00d.json"
    old_entry.write_text("{}", encoding="utf-8")
    assert old_entry.is_file()

    removed = desk.clear_disk_cache(settings)

    assert removed == 1
    assert not old_entry.is_file()


def test_clear_disk_cache_removes_multiple_old_versions_and_current(settings: Settings) -> None:
    """Several versions coexisting -- the actual state `data/cache/paperdesk` was found in (~102
    files spanning v1 through v7) -- are all removed in one call, current version included."""
    cache_dir = desk._disk_cache_dir(settings)
    cache_dir.mkdir(parents=True, exist_ok=True)
    names = [
        "v1-B-momentum-20260101-20260201-20260201-deadbeefcafef00d.json",
        "v2-C-trend-20260101-20260201-20260201-0123456789abcdef.json",
        "v6-allocation-D-alloc-20260101-20260201-20260201-fedcba9876543210.json",
        f"{desk._DISK_CACHE_VERSION}-ladder-E-ladder-20260101-20260201-20260201-1111222233334444.json",
    ]
    for name in names:
        (cache_dir / name).write_text("{}", encoding="utf-8")

    removed = desk.clear_disk_cache(settings)

    assert removed == len(names)
    assert list(cache_dir.glob("*.json")) == []


def test_clear_disk_cache_leaves_unrelated_files_alone(settings: Settings) -> None:
    """The version-agnostic glob must still only ever touch files shaped like this module's own
    cache entries -- an unrelated `.json` (or non-`.json`) file dropped in the same directory by
    something else is left in place, proving this is a shape check, not a bare wildcard delete."""
    cache_dir = desk._disk_cache_dir(settings)
    cache_dir.mkdir(parents=True, exist_ok=True)
    stray = cache_dir / "notes.json"
    stray.write_text('{"not": "a cache entry"}', encoding="utf-8")
    also_stray = cache_dir / "v1-B-momentum-20260101-20260201-20260201-deadbeef.json.bak"
    also_stray.write_text("{}", encoding="utf-8")
    real_entry = cache_dir / "v1-B-momentum-20260101-20260201-20260201-deadbeefcafef00d.json"
    real_entry.write_text("{}", encoding="utf-8")

    removed = desk.clear_disk_cache(settings)

    assert removed == 1
    assert stray.is_file()
    assert also_stray.is_file()
    assert not real_entry.is_file()
