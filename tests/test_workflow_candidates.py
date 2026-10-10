"""The candidate observation log -- the Agent Workflow study's well-powered instrument.

The log exists to record the candidates every gate *refused*, which no order ledger can hold because
those trades were never placed. These tests protect the two properties the study leans on: that a
refused candidate is still written down with its forward return, and that the horizon matches the
Trading Agents decision log so the two are poolable.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import pandas as pd
import pytest

from app.workflow import candidates as candidates_mod
from app.workflow.candidates import (
    HOLDING_DAYS,
    SKIP_REASONS,
    CandidateObservation,
    GateDecision,
    append_observations,
    candidates_log_path,
    read_observations,
    resolve_pending,
)


def test_horizon_matches_the_trading_agents_decision_log() -> None:
    """The coupling `candidates.HOLDING_DAYS` documents but deliberately does not express as an
    import, because the name on the other side is private.

    If these drift, the two logs measure different horizons and pooling them -- or comparing a gate's
    hit rate against the TA desk's own resolved record -- silently compares different things.
    """
    from app.tradingagents.memory import _HOLDING_DAYS

    assert HOLDING_DAYS == _HOLDING_DAYS


def _observation(
    symbol: str = "NVDA",
    *,
    decision_date: dt.date = dt.date(2026, 8, 3),
    passed: bool = True,
    detail: str = "Buy",
    was_explicit: bool = True,
) -> CandidateObservation:
    return CandidateObservation(
        obs_id=f"obs-{symbol}-{decision_date.isoformat()}-{detail}",
        run_id="run-1",
        symbol=symbol,
        decision_date=decision_date,
        agent_card_id="B-momentum",
        regime="risk_on_trend",
        gates=(
            GateDecision(
                gate="ta_gated", passed=passed, detail=detail, was_explicit=was_explicit
            ),
        ),
    )


@pytest.fixture
def priced(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stored daily history for NVDA and SPY spanning the resolution window.

    NVDA rises 10% over the window and SPY 4%, so a resolved observation must show
    `alpha_return_pct` of +6pp -- a value distinct enough from both inputs that a test asserting it
    cannot pass by accident if the subtraction is dropped or reversed.
    """

    def fake_read_frame(symbol: str, interval: object, *, settings: object) -> pd.DataFrame | None:
        closes = {"NVDA": (100.0, 110.0), "SPY": (400.0, 416.0)}.get(symbol)
        if closes is None:
            return None
        return pd.DataFrame(
            {
                "ts": pd.to_datetime([dt.date(2026, 8, 3), dt.date(2026, 8, 24)]),
                "close": list(closes),
            }
        )

    monkeypatch.setattr(candidates_mod.market_store, "read_frame", fake_read_frame)


def test_a_refused_candidate_is_recorded_and_resolved(settings, priced) -> None:
    """The property the whole log exists for.

    A gate that refuses a candidate which then outperforms is worse than no gate, and only this log
    can say so -- the book has no row for a trade that was never placed. So a refusal must survive
    the round trip *and* acquire a forward return, exactly like a pass.
    """
    append_observations(
        [
            _observation(passed=True, detail="Buy"),
            _observation(symbol="NVDA", passed=False, detail="Hold").model_copy(
                update={"obs_id": "obs-refused"}
            ),
        ],
        settings=settings,
    )

    resolved = resolve_pending(settings=settings, today=dt.date(2026, 9, 30))
    assert resolved == 2

    rows = {row.obs_id: row for row in read_observations(settings=settings)}
    refused = rows["obs-refused"]

    assert refused.gates[0].passed is False
    assert refused.state == "resolved"
    assert refused.forward_return_pct == Decimal("0.100000")
    assert refused.benchmark_return_pct == Decimal("0.040000")
    assert refused.alpha_return_pct == Decimal("0.060000")
    assert refused.horizon_days == HOLDING_DAYS


def test_an_observation_is_not_resolved_before_its_horizon(settings, priced) -> None:
    """Resolving early would price a partial window as if it were a full one."""
    append_observations([_observation()], settings=settings)

    assert resolve_pending(settings=settings, today=dt.date(2026, 8, 10)) == 0
    (row,) = read_observations(settings=settings)
    assert row.state == "pending"
    assert row.forward_return_pct is None


def test_an_unpriceable_window_resolves_as_unpriceable_not_as_zero(
    settings, monkeypatch
) -> None:
    """`None` rather than a fabricated zero, and marked so it leaves the pending queue.

    A zero would be averaged into the study as a real observation of no movement. Leaving it pending
    forever would silently shrink the sample instead. Neither is honest; `unpriceable` is.
    """
    monkeypatch.setattr(
        candidates_mod.market_store,
        "read_frame",
        lambda symbol, interval, *, settings: None,
    )
    append_observations([_observation(symbol="DELISTED")], settings=settings)

    assert resolve_pending(settings=settings, today=dt.date(2026, 9, 30)) == 1
    (row,) = read_observations(settings=settings)
    assert row.state == "resolved"
    assert row.unpriceable is True
    assert row.forward_return_pct is None


def test_resolution_is_idempotent(settings, priced) -> None:
    """`resolve_pending` runs on a schedule and may be called twice for the same day."""
    append_observations([_observation()], settings=settings)

    assert resolve_pending(settings=settings, today=dt.date(2026, 9, 30)) == 1
    assert resolve_pending(settings=settings, today=dt.date(2026, 9, 30)) == 0

    (row,) = read_observations(settings=settings)
    assert row.forward_return_pct == Decimal("0.100000")


def test_a_defaulted_gate_ruling_is_distinguishable_from_a_judged_one(settings) -> None:
    """`was_explicit=False` is an abstention, not a decision.

    A Vibe run that failed to emit a parseable verdict defaults to INCONCLUSIVE, which means no
    trade. Counting that as the model having considered the candidate and declined it would let a
    model that simply did not answer look like one that thought carefully and said no.
    """
    append_observations(
        [_observation(passed=False, detail="INCONCLUSIVE", was_explicit=False)],
        settings=settings,
    )
    (row,) = read_observations(settings=settings)
    assert row.gates[0].was_explicit is False
    assert row.gates[0].passed is False


def test_an_unreadable_row_is_skipped_rather_than_killing_the_read(
    settings, priced, caplog
) -> None:
    """One corrupt line must not cost the whole study its data."""
    append_observations([_observation()], settings=settings)
    path = candidates_log_path(settings)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    rows = read_observations(settings=settings)
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# universe_source / skip taxonomy / verdict_source -- additive fields, defaults must not break
# old rows already on disk.
# ---------------------------------------------------------------------------


def test_universe_source_and_skip_fields_default_for_a_freshly_built_observation() -> None:
    """A `CandidateObservation` built without naming any of the new fields gets exactly the values
    every pre-existing caller (and every pre-existing on-disk row) implicitly has."""
    obs = _observation()
    assert obs.universe_source == "card"
    assert obs.skip_reason is None
    assert obs.skip_detail == ""
    assert obs.avoided_cost_usd == Decimal("0")
    assert obs.gates[0].verdict_source == "fresh"


def test_an_old_shape_jsonl_row_without_the_new_keys_still_loads(settings) -> None:
    """A row written before `universe_source`/`skip_reason`/`skip_detail`/`avoided_cost_usd`/
    `verdict_source` existed has none of those keys in its JSON at all -- Pydantic must fill every one
    from its default, not refuse the row. `CandidateObservation`/`GateDecision` are `extra="forbid"`,
    which rejects *unknown* keys present in a payload; it does not require every field to be present,
    so an old row with fewer keys than today's shape is exactly what that guard permits."""
    old_shape_row = {
        "obs_id": "obs-old-1",
        "run_id": "run-old",
        "symbol": "OLD",
        "decision_date": "2026-01-05",
        "agent_card_id": "B-momentum",
        "regime": "risk_on_trend",
        "entry_rank": 0,
        "gates": [
            {"gate": "ta_gated", "passed": True, "detail": "Buy", "was_explicit": True}
        ],
        "state": "pending",
        "horizon_days": None,
        "forward_return_pct": None,
        "benchmark_return_pct": None,
        "alpha_return_pct": None,
        "resolved_at": None,
        "unpriceable": False,
    }
    path = candidates_log_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(old_shape_row) + "\n", encoding="utf-8")

    (row,) = read_observations(settings=settings)
    assert row.obs_id == "obs-old-1"
    assert row.universe_source == "card"
    assert row.skip_reason is None
    assert row.skip_detail == ""
    assert row.avoided_cost_usd == Decimal("0")
    assert row.gates[0].verdict_source == "fresh"


def test_universe_source_filter_on_read_observations(settings) -> None:
    card_obs = _observation(symbol="AAA").model_copy(update={"obs_id": "obs-card"})
    screen_obs = _observation(symbol="BBB").model_copy(
        update={"obs_id": "obs-screen", "universe_source": "screen"}
    )
    append_observations([card_obs, screen_obs], settings=settings)

    card_only = read_observations(settings=settings, universe_source="card")
    screen_only = read_observations(settings=settings, universe_source="screen")
    unfiltered = read_observations(settings=settings)

    assert {row.obs_id for row in card_only} == {"obs-card"}
    assert {row.obs_id for row in screen_only} == {"obs-screen"}
    assert {row.obs_id for row in unfiltered} == {"obs-card", "obs-screen"}


def test_skip_and_avoided_cost_fields_round_trip(settings) -> None:
    obs = _observation(symbol="CCC").model_copy(
        update={
            "obs_id": "obs-skip",
            "skip_reason": "no_book_capacity",
            "skip_detail": "full_workflow book at max_positions",
            "avoided_cost_usd": Decimal("0.42"),
        }
    )
    append_observations([obs], settings=settings)

    (row,) = read_observations(settings=settings)
    assert row.skip_reason == "no_book_capacity"
    assert row.skip_detail == "full_workflow book at max_positions"
    assert row.avoided_cost_usd == Decimal("0.42")


def test_skip_reasons_taxonomy_excludes_cache_hit() -> None:
    """A cache hit is carried by `GateDecision.verdict_source == 'cached'`, never the skip taxonomy --
    pinning this as a test, not just a docstring claim, so a future edit cannot quietly add it back."""
    assert "cache_hit" not in SKIP_REASONS
    assert set(SKIP_REASONS) == {
        "weekly_budget_exhausted",
        "no_book_capacity",
        "tax_wash_sale_blocked",
        "correlation_duplicate",
        "budget_exhausted",
        "over_cap",
    }


def test_verdict_source_round_trips_through_gate_decision(settings) -> None:
    obs = _observation(symbol="DDD").model_copy(
        update={
            "obs_id": "obs-cached",
            "gates": (
                GateDecision(
                    gate="ta_gated", passed=True, detail="Buy", verdict_source="cached"
                ),
            ),
        }
    )
    append_observations([obs], settings=settings)

    (row,) = read_observations(settings=settings)
    assert row.gates[0].verdict_source == "cached"
