"""Tests for `app.workflow.universe.resolve_universe` -- the dynamic ticker selection this shard
plumbs into the Agent Workflow pipeline. Mirrors `tests/test_workflow_candidates.py`'s one-file-per-
module convention.

No test here drives the pipeline itself (`tests/test_workflow_pipeline.py` owns that); these exercise
`resolve_universe` directly, against a real strategy card loaded from the library and real bars written
into the temp store -- the same pattern `tests/test_discovery_tools.py`'s clustering tests use.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from app.config import Settings
from app.db import duck
from app.db.duck import BAR_COLUMNS, Interval
from app.paper.marketdata import clear_frame_cache
from app.workflow.pipeline import _load_card
from app.workflow.universe import CANDIDATE_POOLS, resolve_universe

TRADE_DATE = dt.date(2026, 8, 28)


def _card(settings: Settings):
    card = _load_card("B-momentum", settings=settings)
    assert card is not None
    return card


def _weekdays(anchor: dt.date, count: int) -> list[dt.date]:
    dates: list[dt.date] = []
    day = anchor
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day += dt.timedelta(days=1)
    return dates


def _write(settings: Settings, symbol: str, dates: list[dt.date], closes: list[float]) -> None:
    frame = pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(d, dt.time.min, tzinfo=dt.UTC) for d in dates],
                dtype="datetime64[us, UTC]",
            ),
            "open": closes,
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "adj_close": closes,
            "volume": [1_000_000] * len(dates),
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)
    clear_frame_cache()


# ---------------------------------------------------------------------------
# card mode
# ---------------------------------------------------------------------------


def test_card_mode_returns_card_universe_unchanged(settings: Settings) -> None:
    card = _card(settings)
    result = resolve_universe(
        universe_mode="card", selector_id=None, candidate_pool=None, rank_key=None, screen_top_n=None,
        regime_label="risk_on_trend", card=card, settings=settings, as_of=TRADE_DATE,
    )
    assert result == tuple(card.universe)


def test_none_universe_mode_also_returns_card_universe(settings: Settings) -> None:
    """`universe_mode=None` (an unset request field) must behave exactly like `"card"` -- and so must
    any value this module does not recognise, per its own "never raise on a bad string" convention."""
    card = _card(settings)
    for mode in (None, "not_a_real_mode"):
        result = resolve_universe(
            universe_mode=mode, selector_id=None, candidate_pool=None, rank_key=None,
            screen_top_n=None, regime_label="risk_on_trend", card=card, settings=settings,
            as_of=TRADE_DATE,
        )
        assert result == tuple(card.universe)


# ---------------------------------------------------------------------------
# screen mode: selector_id primary path
# ---------------------------------------------------------------------------


def test_screen_mode_with_selector_id_routes_to_select_for_workflow(settings: Settings, monkeypatch) -> None:
    card = _card(settings)
    captured: dict[str, object] = {}

    def fake_select_for_workflow(
        selector_id, *, as_of, regime_label, settings, prior_picks, card_universe, top_n_override=None
    ):
        captured.update(
            selector_id=selector_id, as_of=as_of, regime_label=regime_label,
            prior_picks=prior_picks, card_universe=card_universe, top_n_override=top_n_override,
        )
        return ("XLK", "XLU")

    import app.workflow.universe as universe_mod

    monkeypatch.setattr(universe_mod, "select_for_workflow", fake_select_for_workflow)

    result = resolve_universe(
        universe_mode="screen", selector_id="mom12_1_hysteresis", candidate_pool=None, rank_key=None,
        screen_top_n=None, regime_label="risk_off", card=card, settings=settings, as_of=TRADE_DATE,
    )

    assert result == ("XLK", "XLU")
    assert captured["selector_id"] == "mom12_1_hysteresis"
    assert captured["as_of"] == TRADE_DATE
    assert captured["regime_label"] == "risk_off"
    assert captured["card_universe"] == tuple(card.universe)
    assert captured["prior_picks"] == ()


def test_selector_id_takes_precedence_over_candidate_pool_and_rank_key(settings: Settings, monkeypatch) -> None:
    card = _card(settings)
    import app.workflow.universe as universe_mod

    monkeypatch.setattr(universe_mod, "select_for_workflow", lambda *a, **k: ("ONLY_FROM_SELECTOR",))

    result = resolve_universe(
        universe_mode="screen", selector_id="control_card_universe", candidate_pool="sector-etf",
        rank_key="mom12_1", screen_top_n=1, regime_label="risk_on_trend", card=card, settings=settings,
        as_of=TRADE_DATE,
    )
    assert result == ("ONLY_FROM_SELECTOR",)


# ---------------------------------------------------------------------------
# screen mode: raw candidate_pool/rank_key fallback
# ---------------------------------------------------------------------------


def test_screen_mode_with_rank_key_routes_to_raw_select(settings: Settings) -> None:
    from app.discovery.selector import select

    card = _card(settings)
    dates = _weekdays(dt.date(2020, 1, 1), 260)
    _write(settings, "XLK", dates, [100.0 + i * 0.08 for i in range(260)])
    _write(settings, "XLU", dates, [100.0 + i * 0.03 for i in range(260)])
    as_of = dates[-1]

    result = resolve_universe(
        universe_mode="screen", selector_id=None, candidate_pool="sector-etf", rank_key="mom12_1",
        screen_top_n=1, regime_label="risk_on_trend", card=card, settings=settings, as_of=as_of,
    )

    from app.discovery.candidates import sector_candidates

    expected = select(
        as_of, candidates=sector_candidates(settings), settings=settings, rank_key="mom12_1",
        top_n=1, collapse=True,
    ).picks
    assert result == expected
    assert result == ("XLK",)  # sanity: the steeper grower should win top-1


def test_screen_top_n_defaults_when_omitted(settings: Settings) -> None:
    """`screen_top_n=None` must behave exactly like passing the module's own default (3) explicitly --
    proven by equivalence rather than a fixed result count, since `collapse=True` may legitimately
    reduce a correlated pool to fewer names than `top_n` asked for."""
    card = _card(settings)
    dates = _weekdays(dt.date(2020, 1, 1), 260)
    _write(settings, "XLK", dates, [100.0 + i * 0.08 for i in range(260)])
    _write(settings, "XLU", dates, [100.0 + i * 0.03 for i in range(260)])
    as_of = dates[-1]

    omitted = resolve_universe(
        universe_mode="screen", selector_id=None, candidate_pool="sector-etf", rank_key="mom6",
        screen_top_n=None, regime_label="risk_on_trend", card=card, settings=settings, as_of=as_of,
    )
    explicit = resolve_universe(
        universe_mode="screen", selector_id=None, candidate_pool="sector-etf", rank_key="mom6",
        screen_top_n=3, regime_label="risk_on_trend", card=card, settings=settings, as_of=as_of,
    )
    assert omitted == explicit
    assert len(omitted) > 0


def test_unknown_candidate_pool_degrades_to_empty_tuple(settings: Settings) -> None:
    card = _card(settings)
    result = resolve_universe(
        universe_mode="screen", selector_id=None, candidate_pool="not_a_real_pool", rank_key="mom12_1",
        screen_top_n=3, regime_label="risk_on_trend", card=card, settings=settings, as_of=TRADE_DATE,
    )
    assert result == ()


def test_bad_rank_key_degrades_to_empty_tuple_rather_than_raising(settings: Settings) -> None:
    card = _card(settings)
    result = resolve_universe(
        universe_mode="screen", selector_id=None, candidate_pool="sector-etf", rank_key="not_a_real_key",
        screen_top_n=3, regime_label="risk_on_trend", card=card, settings=settings, as_of=TRADE_DATE,
    )
    assert result == ()


def test_screen_mode_with_neither_selector_nor_pool_degrades_to_empty_tuple(settings: Settings) -> None:
    """`app.workflow.service` is expected to reject this combination as a 422 before a run is ever
    created; this module's own floor still must not raise if it is somehow reached anyway."""
    card = _card(settings)
    result = resolve_universe(
        universe_mode="screen", selector_id=None, candidate_pool=None, rank_key=None, screen_top_n=None,
        regime_label="risk_on_trend", card=card, settings=settings, as_of=TRADE_DATE,
    )
    assert result == ()


# ---------------------------------------------------------------------------
# determinism and point-in-time behaviour
# ---------------------------------------------------------------------------


def test_resolve_universe_is_deterministic(settings: Settings) -> None:
    card = _card(settings)
    dates = _weekdays(dt.date(2020, 1, 1), 260)
    _write(settings, "XLK", dates, [100.0 + i * 0.08 for i in range(260)])
    _write(settings, "XLU", dates, [100.0 + i * 0.03 for i in range(260)])
    as_of = dates[-1]

    kwargs = dict(
        universe_mode="screen", selector_id=None, candidate_pool="sector-etf", rank_key="mom12_1",
        screen_top_n=2, regime_label="risk_on_trend", card=card, settings=settings, as_of=as_of,
    )
    first = resolve_universe(**kwargs)
    second = resolve_universe(**kwargs)
    assert first == second


def test_resolve_universe_never_reads_past_as_of(settings: Settings) -> None:
    """XLE is flat until day 270, then climbs; XLK grows steadily throughout. At an `as_of` shortly
    after the climb starts, XLE's momentum has not caught up to XLK's -- a shortlist computed at that
    `as_of` must reflect only bars up to it, even though the store already holds XLE's later climb.
    A version of `resolve_universe` that peeked past `as_of` would already rank XLE first here."""
    card = _card(settings)
    dates = _weekdays(dt.date(2020, 1, 1), 300)
    xlk_closes = [100.0 + i * 0.05 for i in range(300)]
    xle_closes = [100.0 if i < 270 else 100.0 + (i - 270) * 0.3 for i in range(300)]
    _write(settings, "XLK", dates, xlk_closes)
    _write(settings, "XLE", dates, xle_closes)

    early = resolve_universe(
        universe_mode="screen", selector_id=None, candidate_pool="sector-etf", rank_key="mom6",
        screen_top_n=1, regime_label="risk_on_trend", card=card, settings=settings, as_of=dates[275],
    )
    late = resolve_universe(
        universe_mode="screen", selector_id=None, candidate_pool="sector-etf", rank_key="mom6",
        screen_top_n=1, regime_label="risk_on_trend", card=card, settings=settings, as_of=dates[299],
    )

    assert early == ("XLK",)
    assert late == ("XLE",)


def test_candidate_pools_match_the_real_pool_labels(settings: Settings) -> None:
    from app.discovery.candidates import sector_candidates, theme_candidates

    assert set(CANDIDATE_POOLS) == {"sector-etf", "theme-etf"}
    assert CANDIDATE_POOLS["sector-etf"](settings).name == sector_candidates(settings).name
    assert CANDIDATE_POOLS["theme-etf"](settings).name == theme_candidates(settings).name


# -- prior-shortlist store (live hysteresis) --------------------------------


def test_prior_shortlist_roundtrips(settings: Settings) -> None:
    from app.workflow.universe import load_prior_shortlist, save_prior_shortlist

    save_prior_shortlist(
        settings, selector_id="mom12_1_hysteresis", as_of=TRADE_DATE, picks=("NVDA", "AMD")
    )
    assert load_prior_shortlist(settings, selector_id="mom12_1_hysteresis") == ("NVDA", "AMD")


def test_prior_shortlist_missing_returns_empty(settings: Settings) -> None:
    from app.workflow.universe import load_prior_shortlist

    assert load_prior_shortlist(settings, selector_id="never_written") == ()


def test_prior_shortlist_is_keyed_per_selector_and_source(settings: Settings) -> None:
    from app.workflow.universe import load_prior_shortlist, save_prior_shortlist

    save_prior_shortlist(settings, selector_id="trend_sticky", as_of=TRADE_DATE, picks=("XLK",))
    # A different selector shares no state with it.
    assert load_prior_shortlist(settings, selector_id="mom12_1_hysteresis") == ()
    # A different universe_source is a different file too.
    assert load_prior_shortlist(settings, selector_id="trend_sticky", universe_source="card") == ()
    assert load_prior_shortlist(settings, selector_id="trend_sticky") == ("XLK",)


def test_prior_shortlist_latest_write_wins(settings: Settings) -> None:
    from app.workflow.universe import load_prior_shortlist, save_prior_shortlist

    save_prior_shortlist(settings, selector_id="meanrev_rsi", as_of=TRADE_DATE, picks=("A",))
    save_prior_shortlist(
        settings, selector_id="meanrev_rsi", as_of=TRADE_DATE + dt.timedelta(days=1), picks=("B", "C")
    )
    assert load_prior_shortlist(settings, selector_id="meanrev_rsi") == ("B", "C")


def test_prior_shortlist_malformed_file_degrades_to_empty(settings: Settings) -> None:
    from app.workflow.universe import _prior_shortlist_path, load_prior_shortlist

    path = _prior_shortlist_path(settings, selector_id="breakout_atr", universe_source="screen")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    assert load_prior_shortlist(settings, selector_id="breakout_atr") == ()


# -- screen-mode entry-rule override (less-restrictive entry for study accrual) --------------------


def test_scan_signals_entry_rule_override_replaces_card_entry(settings: Settings) -> None:
    from app.workflow.pipeline import _scan_signals

    card = _card(settings)
    dates = _weekdays(dt.date(2022, 1, 1), 260)
    _write(settings, "XLK", dates, [100.0 + i * 0.5 for i in range(260)])  # steady uptrend
    as_of = dates[-1]

    # A trending-state override fires on the uptrend...
    fired = _scan_signals(
        card, settings=settings, as_of=as_of, universe=["XLK"],
        entry_rule="close > sma(200) and ema(20) > ema(50)",
    )
    assert fired == ["XLK"]

    # ...a deliberately-false override fires nothing, proving the override -- not card.entry -- is used.
    none = _scan_signals(
        card, settings=settings, as_of=as_of, universe=["XLK"], entry_rule="close < sma(200)",
    )
    assert none == []
