"""Tests for the paper desk's fetch button: `app.paperdesk.desk.universe_symbols`,
`app.paperdesk.fetch.fetch_all`, and the `fetch=true` half of `POST /api/paperdesk/refresh`.

Its own file rather than a section of `tests/test_paperdesk.py`, matching that file's own stated
split: everything there monkeypatches `run_card` and exercises reshaping arithmetic, while
everything here is about which symbols get *asked for* and what happens when the provider answers
badly. Nothing in this file touches the network -- `store.sync_bars` is replaced by a fake that
records its calls, which is also what proves the sweep asked for every symbol rather than quietly
skipping some.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import paperdesk as paperdesk_api
from app.config import Settings
from app.market.models import Coverage, Interval, MarketWarning
from app.market.providers.base import RateLimited
from app.market.store import BarSource, SyncOutcome
from app.paperdesk import desk, fetch
from app.paperdesk.models import Benchmark, Book, Funding, PaperDeskState
from app.tournament.allocation import AllocationCard, Sleeve, TiltRule
from app.tournament.ladder import LadderCard, Rung
from app.tournament.purposes import Purpose

#: Both card models validate a minimum thesis length -- an analyst's card has to say why the
#: strategy should work, not just what it does. Nothing in this file is about thesis content, so one
#: filler string serves every card built below.
_THESIS = (
    "Synthetic card used only to exercise which symbols a card contributes to the desk's fetch "
    "list. It makes no market claim and is never run through the engine; the shape is the whole "
    "point of it. This would be falsified by nothing, because it asserts nothing."
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _ts(day: str | None) -> dt.datetime | None:
    return None if day is None else dt.datetime.fromisoformat(day + "T00:00:00+00:00")


def _outcome(symbol: str, rows: int, last_session: str | None) -> SyncOutcome:
    """`sync_bars`' own return, with the post-sync coverage `fetch_all` reads `advanced` from.

    `rows_written` and `last_session` are set independently on purpose: that is exactly the case the
    real provider produces on every second press -- a short overlap comes back (rows > 0) while the
    newest stored session does not move.
    """
    return SyncOutcome(
        symbol=symbol,
        interval=Interval.DAY,
        source=BarSource.YAHOO,
        rows_written=rows,
        coverage=Coverage(
            symbol=symbol, interval=Interval.DAY, rows=rows, last_ts=_ts(last_session)
        ),
        warnings=[MarketWarning(kind="test", message="synthetic")],
    )


@pytest.fixture(autouse=True)
def _no_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 300ms inter-request delay is real behaviour worth keeping in production and pure dead
    wall time in a test that never leaves the process -- forty symbols would otherwise cost twelve
    seconds per test. Patched out here rather than lowered in the module, so the shipped pacing
    stays the pacing a real fetch uses."""
    monkeypatch.setattr(fetch.time, "sleep", lambda _seconds: None)


#: What the fake store holds for a symbol before any sync in a test that does not say otherwise.
_BEFORE = "2026-08-24"


def _install_sync(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rows: dict[str, int] | None = None,
    failures: dict[str, Exception] | None = None,
    before: dict[str, str | None] | None = None,
    after: dict[str, str | None] | None = None,
) -> list[str]:
    """Replace `store.sync_bars` and `store.coverage` with a fake store. Returns the symbols asked
    for, in order.

    `rows` gives a per-symbol merged-row count (default `2` -- the overlap the real provider re-sends
    every time, which is the number that must *not* drive `advanced`). `before`/`after` give the
    symbol's newest stored session either side of the sync, defaulting to `_BEFORE` before and
    `"2026-08-25"` after, i.e. "it advanced". `failures` maps a symbol to the exception its sync
    should raise.

    `store.coverage` is patched here too, not separately, because `fetch_all` now reads it once per
    symbol *before* the sync -- the pre-sync half of the `advanced` comparison.
    """
    asked: list[str] = []
    row_counts = rows or {}
    raises = failures or {}
    before_map = before or {}
    after_map = after or {}

    def fake_coverage(
        symbol: str, interval: Interval, *, settings: Settings | None = None
    ) -> Coverage:
        day = before_map.get(symbol, _BEFORE)
        return Coverage(symbol=symbol, interval=interval, rows=1, last_ts=_ts(day))

    def fake_sync(
        symbol: str,
        interval: Interval,
        *,
        registry: object = None,
        settings: Settings | None = None,
        full: bool = False,
    ) -> SyncOutcome:
        asked.append(symbol)
        assert interval is Interval.DAY, "the desk trades daily bars only"
        assert full is False, "a fetch must be incremental, not a full-history re-download"
        if symbol in raises:
            raise raises[symbol]
        return _outcome(symbol, row_counts.get(symbol, 2), after_map.get(symbol, "2026-08-25"))

    monkeypatch.setattr(fetch.store, "coverage", fake_coverage)
    monkeypatch.setattr(fetch.store, "sync_bars", fake_sync)
    return asked


def _install_mark(monkeypatch: pytest.MonkeyPatch, *, before: str, after: str) -> None:
    """Make the *benchmark's* own coverage differ either side of the sweep, so a test can assert the
    page's "the mark moved" reporting.

    Layered over `_install_sync`'s fake coverage rather than replacing it: `SPY` alone decides the
    desk's mark (`app.paperdesk.desk._trading_window`), and every other symbol keeps answering with
    whatever that fixture said. Call this *after* `_install_sync`.
    """
    benchmark = desk._BENCHMARK
    inner = fetch.store.coverage
    answers = iter([before, after])

    def fake_coverage(
        symbol: str, interval: Interval, *, settings: Settings | None = None
    ) -> Coverage:
        if symbol != benchmark:
            return inner(symbol, interval, settings=settings)
        return Coverage(
            symbol=symbol, interval=interval, rows=1, last_ts=_ts(next(answers, after))
        )

    monkeypatch.setattr(fetch.store, "coverage", fake_coverage)


# ---------------------------------------------------------------------------
# 1. universe_symbols -- what the desk actually needs priced
# ---------------------------------------------------------------------------


class TestUniverseSymbols:
    def test_covers_every_card_shape_and_both_benchmarks(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rules card contributes its `universe`, a ladder its four named symbols (including the
        `signal_symbol` it never holds), and an allocation card its sleeves *and* its tilt rules."""
        ladder = LadderCard(
            agent_id="L",
            display_name="L",
            thesis=_THESIS,
            signal_symbol="SPY",
            defensive_symbol="SCHD",
            bond_symbol="IEF",
            leveraged_symbol="QLD",
            base_defensive_weight=Decimal("0.60"),
            base_bond_weight=Decimal("0.40"),
            rungs=(Rung(drawdown=Decimal("-0.10"), leveraged_weight=Decimal("0.20")),),
            confirm_ma=50,
            ath_haircut=Decimal("0.5"),
            recovery_gain=Decimal("0.10"),
            recovery_sessions=60,
            designed_through=dt.date(2026, 2, 13),
        )
        allocation = AllocationCard(
            agent_id="A",
            display_name="A",
            thesis=_THESIS,
            sleeves=(
                Sleeve(symbol="VIG", target_weight=Decimal("0.60")),
                Sleeve(symbol="BND", target_weight=Decimal("0.40")),
            ),
            band_pct=Decimal("0.05"),
            rules=(
                TiltRule(
                    on_symbol="VIG",
                    from_symbol="BND",
                    to_symbol="VIG",
                    shift_pct=Decimal("0.10"),
                    condition="close > sma(close, 50)",
                ),
            ),
            designed_through=dt.date(2026, 2, 13),
        )
        cards: dict[str, object] = {"L": ladder, "A": allocation}
        monkeypatch.setattr(
            desk,
            "rosters",
            lambda cfg: {
                Purpose.TRADING: ("L", "A"),
                Purpose.SAVINGS: (),
                Purpose.ROTH: (),
            },
        )
        monkeypatch.setattr(desk, "_load_card", lambda cfg, agent_id: cards[agent_id])

        symbols = desk.universe_symbols(settings)

        # The ladder's signal symbol is SPY, which is also a benchmark; both benchmarks are present
        # regardless of whether any card happens to name them.
        assert set(symbols) >= {"SPY", "QQQ", "SCHD", "IEF", "QLD", "VIG", "BND"}
        assert symbols == tuple(sorted(set(symbols))), "sorted and de-duplicated"

    def test_an_unreadable_card_is_skipped_rather_than_raising(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A roster overlay naming a card that no longer exists must not stop the other thirty-nine
        symbols from being fetched -- see `universe_symbols`' own docstring."""
        monkeypatch.setattr(
            desk,
            "rosters",
            lambda cfg: {Purpose.TRADING: ("gone",), Purpose.SAVINGS: (), Purpose.ROTH: ()},
        )

        def explode(cfg: Settings, agent_id: str) -> object:
            raise FileNotFoundError("no card named " + repr(agent_id))

        monkeypatch.setattr(desk, "_load_card", explode)

        assert desk.universe_symbols(settings) == ("QQQ", "SPY")


# ---------------------------------------------------------------------------
# 2. fetch_all -- ask about everything, report honestly
# ---------------------------------------------------------------------------


class TestFetchAll:
    def test_asks_for_every_symbol_and_splits_advanced_from_unchanged(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(desk, "universe_symbols", lambda cfg: ("AAA", "BBB", "CCC"))
        asked = _install_sync(
            monkeypatch,
            rows={"AAA": 3, "BBB": 2, "CCC": 2},
            after={"BBB": _BEFORE},  # answered, but its newest session did not move
        )
        _install_mark(monkeypatch, before="2026-08-24", after="2026-08-25")

        summary = fetch.fetch_all(settings)

        assert asked == ["AAA", "BBB", "CCC"], "every symbol asked for, none skipped as 'fresh'"
        assert (summary.requested, summary.advanced, summary.unchanged, summary.failed) == (
            3,
            2,
            1,
            0,
        )
        assert summary.rows_merged == 7
        assert summary.failures == []
        assert (summary.latest_bar_before, summary.latest_bar_after) == (
            dt.date(2026, 8, 24),
            dt.date(2026, 8, 25),
        )
        assert summary.requested == summary.advanced + summary.unchanged + summary.failed

    def test_a_re_sent_overlap_is_not_counted_as_a_new_session(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The defect this counter was rewritten for. `sync_bars` re-requests a short overlap behind
        each symbol's newest stored bar on every call, so rows always come back -- and the first
        draft of this summary read that as "three symbols updated" on a second press that stored
        nothing. `advanced` must read the store, and `rows_merged` must not be mistaken for it."""
        monkeypatch.setattr(desk, "universe_symbols", lambda cfg: ("AAA", "BBB", "CCC"))
        _install_sync(
            monkeypatch,
            rows={"AAA": 2, "BBB": 2, "CCC": 2},
            after={"AAA": _BEFORE, "BBB": _BEFORE, "CCC": _BEFORE},
        )
        _install_mark(monkeypatch, before=_BEFORE, after=_BEFORE)

        summary = fetch.fetch_all(settings)

        assert summary.advanced == 0
        assert summary.unchanged == 3
        assert summary.rows_merged == 6, "rows still came back -- they are just not new sessions"

    def test_a_symbol_with_no_stored_bars_that_gains_some_counts_as_advanced(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """First-ever sync of a newly rostered card's symbol: nothing stored before, a session
        stored after. `None -> a date` is the clearest possible advance and must not fall through to
        `unchanged` on a `None` check written the lazy way."""
        monkeypatch.setattr(desk, "universe_symbols", lambda cfg: ("NEW",))
        _install_sync(monkeypatch, before={"NEW": None}, after={"NEW": "2026-08-25"})
        _install_mark(monkeypatch, before=_BEFORE, after=_BEFORE)

        summary = fetch.fetch_all(settings)

        assert summary.advanced == 1
        assert summary.unchanged == 0

    def test_a_provider_failure_is_recorded_and_the_sweep_continues(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One rate-limited ticker must not cost the other two their fetch -- the failure mode this
        module's docstring exists to rule out."""
        monkeypatch.setattr(desk, "universe_symbols", lambda cfg: ("AAA", "BBB", "CCC"))
        asked = _install_sync(monkeypatch, failures={"BBB": RateLimited("slow down", provider="test")})
        _install_mark(monkeypatch, before="2026-08-25", after="2026-08-25")

        summary = fetch.fetch_all(settings)

        assert asked == ["AAA", "BBB", "CCC"]
        assert (summary.advanced, summary.failed) == (2, 1)
        assert len(summary.failures) == 1
        assert summary.failures[0].startswith("BBB: ")
        assert "slow down" in summary.failures[0]

    def test_a_non_provider_exception_is_also_contained(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A corrupt parquet file mid-merge raises something that is not a `ProviderError`, and it
        must be contained for the same reason: the caller's recompute is where a broken store
        becomes visible, and losing two good syncs to surface it earlier is a bad trade."""
        monkeypatch.setattr(desk, "universe_symbols", lambda cfg: ("AAA", "BBB", "CCC"))
        _install_sync(monkeypatch, failures={"AAA": ValueError("corrupt parquet")})
        _install_mark(monkeypatch, before="2026-08-25", after="2026-08-25")

        summary = fetch.fetch_all(settings)

        assert summary.failed == 1
        assert summary.failures == ["AAA: ValueError: corrupt parquet"]
        assert summary.advanced == 2

    def test_an_unreadable_store_reports_no_mark_rather_than_failing(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_latest_bar` is diagnostic. A store that cannot answer it must not take down a fetch
        whose syncs all succeeded."""
        monkeypatch.setattr(desk, "universe_symbols", lambda cfg: ("AAA",))
        _install_sync(monkeypatch)

        def explode(
            symbol: str, interval: Interval, *, settings: Settings | None = None
        ) -> Coverage:
            raise OSError("store unreadable")

        monkeypatch.setattr(fetch.store, "coverage", explode)

        summary = fetch.fetch_all(settings)

        # The sync itself succeeded, and its own post-sync coverage still names a session, so the
        # symbol is counted as advanced. Only the diagnostic reads went dark.
        assert summary.advanced == 1
        assert summary.failed == 0
        assert summary.latest_bar_before is None
        assert summary.latest_bar_after is None


# ---------------------------------------------------------------------------
# 3. The route -- opt-in, and never fatal
# ---------------------------------------------------------------------------


def _state() -> PaperDeskState:
    """A minimal, already-computed desk state.

    The route tests below stub `desk.refresh` with this rather than letting it run for real. What
    they are about is the *wiring*: whether `?fetch=true` runs the sweep, whether its absence keeps
    the request off the network, and whether the summary reaches the response body. Whether the
    recompute produces the right equity figures is `tests/test_paperdesk.py`'s subject, and making
    these four tests each seed a temp store with benchmark bars would test that a second time while
    obscuring what they actually check.
    """
    return PaperDeskState(
        inception=dt.date(2026, 8, 15),
        as_of=dt.date(2026, 8, 25),
        latest_bar=dt.date(2026, 8, 25),
        stale_days=1,
        first_session=dt.date(2026, 8, 17),
        sessions=7,
        inception_default=dt.date(2026, 8, 15),
        inception_is_custom=False,
        design_cutoff=dt.date(2026, 2, 13),
        in_sample_sessions=0,
        earliest_inception=dt.date(1993, 1, 29),
        latest_inception=dt.date(2026, 8, 25),
        notes=[],
        books=[
            Book(
                purpose=Purpose.TRADING,
                label="Trading",
                funding=Funding(
                    purpose=Purpose.TRADING,
                    shape="lump_sum",
                    seed=Decimal("100000.00"),
                    contribution=Decimal("0.00"),
                    tax_treatment="taxable",
                ),
                starting_cash=Decimal("100000.00"),
                benchmark=Benchmark(symbol="SPY", return_pct=Decimal("0.01")),
                desks=[],
            )
        ],
    )


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(desk, "refresh", lambda *args, **kwargs: _state())
    monkeypatch.setattr(desk, "state", lambda *args, **kwargs: _state())
    app = FastAPI()
    app.include_router(paperdesk_api.router)
    return TestClient(app)


class TestRefreshRoute:
    def test_refresh_without_fetch_never_reaches_the_provider(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The default is a pure recompute. Any caller that typed the documented cache-busting POST
        -- including every other test in this repository -- must keep getting exactly that."""

        def spy(*args: object, **kwargs: object) -> object:
            raise AssertionError("fetch_all must not run without ?fetch=true")

        monkeypatch.setattr(paperdesk_api.fetch, "fetch_all", spy)

        response = client.post("/api/paperdesk/refresh")

        assert response.status_code == 200
        assert response.json()["fetch"] is None

    def test_state_never_carries_a_fetch_summary(self, client: TestClient) -> None:
        """A state read touches no network, so reporting some earlier press's counters would be a
        lie -- `None` is the honest answer. The field is still present, so the response shape is the
        same one every route on this router serves."""
        payload = client.get("/api/paperdesk/state").json()

        assert "fetch" in payload
        assert payload["fetch"] is None

    def test_fetch_true_runs_the_sweep_and_returns_its_summary(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(desk, "universe_symbols", lambda cfg: ("AAA", "BBB"))
        _install_sync(monkeypatch, rows={"AAA": 4, "BBB": 2}, after={"BBB": _BEFORE})
        _install_mark(monkeypatch, before="2026-08-24", after="2026-08-25")

        response = client.post("/api/paperdesk/refresh?fetch=true")

        assert response.status_code == 200
        body = response.json()
        summary = body["fetch"]
        assert summary["requested"] == 2
        assert summary["advanced"] == 1
        assert summary["unchanged"] == 1
        assert summary["rows_merged"] == 6
        assert summary["latest_bar_before"] == "2026-08-24"
        assert summary["latest_bar_after"] == "2026-08-25"
        # The recompute still ran and the state half of the response is intact.
        assert body["as_of"]

    def test_a_failed_symbol_does_not_fail_the_request(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A desk still holding yesterday's bars is worth serving. Burying that behind a 502 because
        one ticker was rate-limited hides a page that is fine."""
        monkeypatch.setattr(desk, "universe_symbols", lambda cfg: ("AAA", "BBB"))
        _install_sync(monkeypatch, failures={"AAA": RateLimited("429", provider="test")})
        _install_mark(monkeypatch, before="2026-08-25", after="2026-08-25")

        response = client.post("/api/paperdesk/refresh?fetch=true")

        assert response.status_code == 200
        body = response.json()
        assert body["fetch"]["failed"] == 1
        assert body["books"], "the recompute ran regardless"
