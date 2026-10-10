"""The research-verdict cache (`backend/app/workflow/research_cache.py`): TTL, the two free
invalidation triggers, the storage-free re-entry-after-absence check, and the Vibe-only linked
invalidation rule.

Unit-level only -- the mandatory end-to-end proof that a cache hit actually changes pipeline spend
without breaking the trade path lives in `tests/test_workflow_pipeline.py` (see
`test_gate2_cache_hit_avoids_a_second_fresh_research_cycle`), per this project's own standing lesson
that a validator tested only in isolation has missed real caller behaviour before
(`grounding-gate-false-rejections.md`).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.workflow import candidates as candidates_mod
from app.workflow import research_cache as rc
from app.workflow.candidates import CandidateObservation, GateDecision

CARD = "B-momentum"
SYMBOL = "NVDA"
CACHE_DATE = dt.date(2026, 8, 3)


def _write(
    settings,
    *,
    child_kind: rc.ChildKind = "tradingagents",
    decision_date: dt.date = CACHE_DATE,
    regime_label: str = "risk_on_trend",
    price: str = "100",
    atr14: str = "2",
    ta_rating: str = "Buy",
    ta_rating_at_cache: str = "",
    vibe_verdict: str | None = None,
    research_cost_usd: str = "6.50",
) -> rc.ResearchVerdictCacheEntry:
    return rc.write_entry(
        symbol=SYMBOL,
        agent_card_id=CARD,
        child_kind=child_kind,
        decision_date=decision_date,
        regime_label=regime_label,
        price_at_cache=Decimal(price),
        atr14_at_cache=Decimal(atr14),
        ta_rating=ta_rating if child_kind == "tradingagents" else "",
        ta_run_id="ta-1" if child_kind == "tradingagents" else "",
        vibe_verdict=vibe_verdict if child_kind == "vibedesk" else None,  # type: ignore[arg-type]
        vibe_run_id="vibe-1" if child_kind == "vibedesk" else "",
        ta_rating_at_cache=ta_rating_at_cache,
        research_cost_usd=Decimal(research_cost_usd),
        settings=settings,
    )


def _obs(symbol: str, decision_date: dt.date, *, card: str = CARD) -> CandidateObservation:
    return CandidateObservation(
        obs_id=f"obs-{symbol}-{decision_date.isoformat()}",
        run_id="run-x",
        symbol=symbol,
        decision_date=decision_date,
        agent_card_id=card,
        regime="risk_on_trend",
        gates=(GateDecision(gate="ta_gated", passed=True, detail="Buy"),),
    )


# ---------------------------------------------------------------------------
# TTL lock
# ---------------------------------------------------------------------------


def test_ttl_locked_to_candidates_and_tradingagents_memory() -> None:
    """The three-way coupling the spec requires: this module's TTL, `candidates.HOLDING_DAYS`, and
    `tradingagents.memory._HOLDING_DAYS` must never drift apart -- all three horizons must agree or a
    verdict cached under one clock is reused under another."""
    from app.tradingagents.memory import _HOLDING_DAYS

    assert rc.CACHE_TTL_DAYS == candidates_mod.HOLDING_DAYS == _HOLDING_DAYS == 21


# ---------------------------------------------------------------------------
# Storage round trip
# ---------------------------------------------------------------------------


def test_write_then_latest_entry_round_trips(settings) -> None:
    written = _write(settings)
    found = rc.latest_entry(SYMBOL, CARD, "tradingagents", settings=settings)
    assert found == written
    assert found.symbol == SYMBOL
    assert found.research_cost_usd == Decimal("6.50")


def test_latest_entry_is_the_most_recently_appended_row_for_the_key(settings) -> None:
    _write(settings, ta_rating="Hold", decision_date=CACHE_DATE)
    newer = _write(settings, ta_rating="Buy", decision_date=CACHE_DATE + dt.timedelta(days=1))
    found = rc.latest_entry(SYMBOL, CARD, "tradingagents", settings=settings)
    assert found == newer
    assert found.ta_rating == "Buy"


def test_no_entry_at_all_is_not_valid(settings) -> None:
    result = rc.check_verdict_cache(
        SYMBOL, CARD, "tradingagents", settings=settings, today=CACHE_DATE,
        regime_label="risk_on_trend", current_close=Decimal("100"),
    )
    assert result.valid is False
    assert result.reason == rc.NO_ENTRY
    assert result.entry is None


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------


def test_cache_is_valid_inside_the_ttl_window(settings) -> None:
    _write(settings)
    today = CACHE_DATE + dt.timedelta(days=rc.CACHE_TTL_DAYS)  # exactly on the boundary -- still valid
    result = rc.check_verdict_cache(
        SYMBOL, CARD, "tradingagents", settings=settings, today=today,
        regime_label="risk_on_trend", current_close=Decimal("100"),
    )
    assert result.valid is True
    assert result.reason == rc.VALID


def test_ttl_expiry_forces_fresh_research(settings) -> None:
    _write(settings)
    today = CACHE_DATE + dt.timedelta(days=rc.CACHE_TTL_DAYS + 1)  # one day past the boundary
    result = rc.check_verdict_cache(
        SYMBOL, CARD, "tradingagents", settings=settings, today=today,
        regime_label="risk_on_trend", current_close=Decimal("100"),
    )
    assert result.valid is False
    assert result.reason == rc.TTL_EXPIRED


# ---------------------------------------------------------------------------
# Trigger A: regime flip
# ---------------------------------------------------------------------------


def test_regime_flip_invalidates_even_inside_ttl(settings) -> None:
    _write(settings, regime_label="risk_on_trend")
    result = rc.check_verdict_cache(
        SYMBOL, CARD, "tradingagents", settings=settings, today=CACHE_DATE + dt.timedelta(days=2),
        regime_label="risk_off", current_close=Decimal("100"),
    )
    assert result.valid is False
    assert result.reason == rc.REGIME_FLIP


def test_unchanged_regime_does_not_invalidate(settings) -> None:
    _write(settings, regime_label="risk_on_trend")
    result = rc.check_verdict_cache(
        SYMBOL, CARD, "tradingagents", settings=settings, today=CACHE_DATE + dt.timedelta(days=2),
        regime_label="risk_on_trend", current_close=Decimal("100"),
    )
    assert result.valid is True


# ---------------------------------------------------------------------------
# Trigger B: adverse ATR move -- three sub-cases on the same fixture (price=$100, atr14=$2)
# ---------------------------------------------------------------------------


def test_atr_move_exceeding_2x_invalidates(settings) -> None:
    _write(settings, price="100", atr14="2")
    result = rc.check_verdict_cache(
        SYMBOL, CARD, "tradingagents", settings=settings, today=CACHE_DATE + dt.timedelta(days=1),
        regime_label="risk_on_trend", current_close=Decimal("95"),  # move of $5 > 2*$2=$4
    )
    assert result.valid is False
    assert result.reason == rc.ADVERSE_ATR_MOVE


def test_atr_move_exactly_2x_stays_cached_strict_inequality(settings) -> None:
    _write(settings, price="100", atr14="2")
    result = rc.check_verdict_cache(
        SYMBOL, CARD, "tradingagents", settings=settings, today=CACHE_DATE + dt.timedelta(days=1),
        regime_label="risk_on_trend", current_close=Decimal("96"),  # move of $4 == 2*$2, not >
    )
    assert result.valid is True


def test_atr_move_under_2x_stays_cached(settings) -> None:
    _write(settings, price="100", atr14="2")
    result = rc.check_verdict_cache(
        SYMBOL, CARD, "tradingagents", settings=settings, today=CACHE_DATE + dt.timedelta(days=1),
        regime_label="risk_on_trend", current_close=Decimal("97"),  # move of $3 < $4
    )
    assert result.valid is True


def test_unpriceable_current_close_is_treated_as_invalidated(settings) -> None:
    _write(settings)
    result = rc.check_verdict_cache(
        SYMBOL, CARD, "tradingagents", settings=settings, today=CACHE_DATE + dt.timedelta(days=1),
        regime_label="risk_on_trend", current_close=None,
    )
    assert result.valid is False
    assert result.reason == rc.UNPRICEABLE


# ---------------------------------------------------------------------------
# Re-entry after absence -- derived from candidates.jsonl, no separate storage
# ---------------------------------------------------------------------------


def test_reentry_after_absence_invalidates(settings) -> None:
    """Cached at T. The card scanned again at T+3 but NVDA did not appear in that day's candidate
    log (it fell out of the shortlist) -- a genuine absence. Re-firing at T+7, still inside TTL, must
    be treated as invalidated despite clearing TTL/regime/ATR."""
    _write(settings, decision_date=CACHE_DATE)
    gap_date = CACHE_DATE + dt.timedelta(days=3)
    candidates_mod.append_observations([_obs("AMD", gap_date)], settings=settings)  # NVDA absent that day

    today = CACHE_DATE + dt.timedelta(days=7)
    result = rc.check_verdict_cache(
        SYMBOL, CARD, "tradingagents", settings=settings, today=today,
        regime_label="risk_on_trend", current_close=Decimal("100"),
    )
    assert result.valid is False
    assert result.reason == rc.REENTRY_AFTER_ABSENCE


def test_no_gap_in_scan_history_does_not_invalidate(settings) -> None:
    """The companion case: the card scanned again in between and NVDA *was* present every time --
    continuous coverage, no absence, cache stays valid."""
    _write(settings, decision_date=CACHE_DATE)
    gap_date = CACHE_DATE + dt.timedelta(days=3)
    candidates_mod.append_observations([_obs(SYMBOL, gap_date)], settings=settings)

    today = CACHE_DATE + dt.timedelta(days=7)
    result = rc.check_verdict_cache(
        SYMBOL, CARD, "tradingagents", settings=settings, today=today,
        regime_label="risk_on_trend", current_close=Decimal("100"),
    )
    assert result.valid is True


def test_no_intervening_runs_at_all_does_not_invalidate(settings) -> None:
    """No candidates.jsonl rows for this card between cache time and today at all -- there is nothing
    to compare against, so this trigger cannot fire (distinct from a genuine absence)."""
    _write(settings, decision_date=CACHE_DATE)
    today = CACHE_DATE + dt.timedelta(days=7)
    result = rc.check_verdict_cache(
        SYMBOL, CARD, "tradingagents", settings=settings, today=today,
        regime_label="risk_on_trend", current_close=Decimal("100"),
    )
    assert result.valid is True


# ---------------------------------------------------------------------------
# Linked invalidation (Vibe cache only)
# ---------------------------------------------------------------------------


def test_vibe_cache_invalidated_when_effective_ta_rating_differs(settings) -> None:
    _write(
        settings, child_kind="vibedesk", vibe_verdict="SUPPORT", ta_rating_at_cache="Buy",
    )
    result = rc.check_verdict_cache(
        SYMBOL, CARD, "vibedesk", settings=settings, today=CACHE_DATE + dt.timedelta(days=1),
        regime_label="risk_on_trend", current_close=Decimal("100"),
        ta_rating_for_linked_check="Hold",  # TA rating changed this cycle
    )
    assert result.valid is False
    assert result.reason == rc.LINKED_TA_RATING_CHANGED


def test_vibe_cache_not_invalidated_when_effective_ta_rating_is_unchanged(settings) -> None:
    _write(
        settings, child_kind="vibedesk", vibe_verdict="SUPPORT", ta_rating_at_cache="Buy",
    )
    result = rc.check_verdict_cache(
        SYMBOL, CARD, "vibedesk", settings=settings, today=CACHE_DATE + dt.timedelta(days=1),
        regime_label="risk_on_trend", current_close=Decimal("100"),
        ta_rating_for_linked_check="Buy",
    )
    assert result.valid is True
    assert result.entry is not None
    assert result.entry.vibe_verdict == "SUPPORT"


def test_ta_gated_lookups_never_apply_the_linked_check(settings) -> None:
    """The linked-rating rule is Vibe-only -- a TA cache lookup must not even look at
    `ta_rating_for_linked_check`, since it has no such field to compare against."""
    _write(settings, child_kind="tradingagents", ta_rating="Buy")
    result = rc.check_verdict_cache(
        SYMBOL, CARD, "tradingagents", settings=settings, today=CACHE_DATE + dt.timedelta(days=1),
        regime_label="risk_on_trend", current_close=Decimal("100"),
        ta_rating_for_linked_check="totally different, irrelevant here",
    )
    assert result.valid is True
