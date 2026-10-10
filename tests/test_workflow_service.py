"""Validation for the dynamic-universe fields on `WorkflowRunRequest` -- `app.workflow.service`'s
`_resolve_universe`/`_validate_arms`.

The reject-path tests go through `start_workflow_run` itself, matching the existing convention in
`tests/test_workflow_pipeline.py::test_service_rejects_unknown_arm_and_bad_budget`: raising
`InvalidRequest` happens before `registry().start` is ever reached, so no background thread is
launched. The resolve-path (non-error) assertions call `_resolve_universe`/`_validate_arms` directly
instead of going through `start_workflow_run`'s full success path -- a validated request that reaches
`registry().start` launches a real background pipeline thread (`app.agentdesk.jobs.DeskRegistry.start`),
exactly the kind of side effect a fast, deterministic unit test for a validation boundary should not
have to wait on or clean up after.
"""

from __future__ import annotations

import pytest

from app.discovery.selector import RANK_KEYS
from app.discovery.workflow_selectors import SELECTOR_IDS
from app.workflow import service as workflow_service
from app.workflow.pipeline import ALL_ARMS, SCREENED_ARMS
from app.workflow.schemas import WorkflowRunRequest
from app.workflow.universe import CANDIDATE_POOLS

# ---------------------------------------------------------------------------
# _resolve_universe
# ---------------------------------------------------------------------------


def test_card_mode_resolves_to_all_none() -> None:
    resolved = workflow_service._resolve_universe(WorkflowRunRequest())
    assert resolved == ("card", None, None, None, None)


def test_explicit_card_mode_resolves_the_same_as_omitted() -> None:
    omitted = workflow_service._resolve_universe(WorkflowRunRequest())
    explicit = workflow_service._resolve_universe(WorkflowRunRequest(universe_mode="card"))
    assert omitted == explicit


def test_screen_mode_with_selector_id_resolves_it_and_ignores_pool_and_rank_key() -> None:
    req = WorkflowRunRequest(
        universe_mode="screen", selector_id="mom12_1_hysteresis",
        candidate_pool="theme-etf", rank_key="mom6",
    )
    mode, selector_id, pool, rank_key, top_n = workflow_service._resolve_universe(req)
    assert mode == "screen"
    assert selector_id == "mom12_1_hysteresis"
    assert pool is None
    assert rank_key is None
    assert top_n == workflow_service.DEFAULT_SCREEN_TOP_N


def test_screen_mode_with_pool_and_rank_key_resolves_the_raw_fallback() -> None:
    req = WorkflowRunRequest(
        universe_mode="screen", candidate_pool="theme-etf", rank_key="mom6", screen_top_n=5,
    )
    resolved = workflow_service._resolve_universe(req)
    assert resolved == ("screen", None, "theme-etf", "mom6", 5)


def test_screen_mode_defaults_pool_and_rank_key_and_top_n_when_omitted() -> None:
    req = WorkflowRunRequest(universe_mode="screen", candidate_pool="sector-etf")
    mode, selector_id, pool, rank_key, top_n = workflow_service._resolve_universe(req)
    assert mode == "screen"
    assert selector_id is None
    assert pool == "sector-etf"
    assert rank_key == workflow_service.DEFAULT_RANK_KEY
    assert top_n == workflow_service.DEFAULT_SCREEN_TOP_N


def test_screen_mode_with_neither_selector_nor_pool_is_rejected() -> None:
    with pytest.raises(workflow_service.InvalidRequest, match="selector_id"):
        workflow_service._resolve_universe(WorkflowRunRequest(universe_mode="screen"))


def test_screen_mode_rejects_unknown_selector_id() -> None:
    req = WorkflowRunRequest(universe_mode="screen", selector_id="not_a_real_selector")
    with pytest.raises(workflow_service.InvalidRequest, match="selector_id"):
        workflow_service._resolve_universe(req)


def test_screen_mode_rejects_unknown_candidate_pool() -> None:
    req = WorkflowRunRequest(universe_mode="screen", candidate_pool="not_a_pool", rank_key="mom6")
    with pytest.raises(workflow_service.InvalidRequest, match="candidate_pool"):
        workflow_service._resolve_universe(req)


def test_screen_mode_rejects_unknown_rank_key() -> None:
    req = WorkflowRunRequest(universe_mode="screen", candidate_pool="sector-etf", rank_key="not_a_key")
    with pytest.raises(workflow_service.InvalidRequest, match="rank_key"):
        workflow_service._resolve_universe(req)


def test_every_selector_id_and_candidate_pool_is_known_to_service() -> None:
    """Cross-check the two modules stay in sync: every id the request-level validation accepts is a
    real, dispatchable id/pool one layer down."""
    for selector_id in SELECTOR_IDS:
        req = WorkflowRunRequest(universe_mode="screen", selector_id=selector_id)
        mode, resolved_id, *_ = workflow_service._resolve_universe(req)
        assert (mode, resolved_id) == ("screen", selector_id)
    for pool in CANDIDATE_POOLS:
        req = WorkflowRunRequest(universe_mode="screen", candidate_pool=pool, rank_key="mom12_1")
        mode, _, resolved_pool, resolved_rank_key, _ = workflow_service._resolve_universe(req)
        assert (mode, resolved_pool, resolved_rank_key) == ("screen", pool, "mom12_1")


# ---------------------------------------------------------------------------
# _validate_arms
# ---------------------------------------------------------------------------


def test_card_mode_arms_default_to_all_arms() -> None:
    assert workflow_service._validate_arms(None, mode="card") == ALL_ARMS


def test_screen_mode_arms_default_to_screened_arms_not_all_arms() -> None:
    assert workflow_service._validate_arms(None, mode="screen") == SCREENED_ARMS
    assert workflow_service._validate_arms(None, mode="screen") != ALL_ARMS


def test_screen_mode_accepts_raw_signal_and_full_workflow() -> None:
    assert workflow_service._validate_arms(["raw_signal"], mode="screen") == ("raw_signal",)
    assert workflow_service._validate_arms(["full_workflow", "raw_signal"], mode="screen") == (
        "raw_signal", "full_workflow",
    )


def test_screen_mode_rejects_ta_gated() -> None:
    with pytest.raises(workflow_service.InvalidRequest):
        workflow_service._validate_arms(["ta_gated"], mode="screen")


def test_screen_mode_rejects_vibe_gated() -> None:
    with pytest.raises(workflow_service.InvalidRequest):
        workflow_service._validate_arms(["vibe_gated"], mode="screen")


def test_card_mode_still_accepts_ta_gated_and_vibe_gated() -> None:
    assert workflow_service._validate_arms(["ta_gated", "vibe_gated"], mode="card") == (
        "ta_gated", "vibe_gated",
    )


# ---------------------------------------------------------------------------
# end-to-end 422 surface via start_workflow_run
# ---------------------------------------------------------------------------


def test_screen_mode_with_ta_gated_arm_is_rejected_at_submission(settings, monkeypatch) -> None:
    monkeypatch.setattr(workflow_service.agents_client, "is_available", lambda: (True, ""))
    with pytest.raises(workflow_service.InvalidRequest):
        workflow_service.start_workflow_run(
            WorkflowRunRequest(universe_mode="screen", arms_enabled=["ta_gated"]), settings=settings
        )


def test_screen_mode_with_no_selector_or_pool_is_rejected_at_submission(settings, monkeypatch) -> None:
    monkeypatch.setattr(workflow_service.agents_client, "is_available", lambda: (True, ""))
    with pytest.raises(workflow_service.InvalidRequest):
        workflow_service.start_workflow_run(
            WorkflowRunRequest(universe_mode="screen"), settings=settings
        )


def test_screen_mode_with_unknown_selector_id_is_rejected_at_submission(settings, monkeypatch) -> None:
    monkeypatch.setattr(workflow_service.agents_client, "is_available", lambda: (True, ""))
    with pytest.raises(workflow_service.InvalidRequest):
        workflow_service.start_workflow_run(
            WorkflowRunRequest(universe_mode="screen", selector_id="not_a_real_selector"),
            settings=settings,
        )


# ---------------------------------------------------------------------------
# config_payload
# ---------------------------------------------------------------------------


def test_config_payload_surfaces_universe_fields(settings) -> None:
    payload = workflow_service.config_payload(settings)
    assert payload["universe_modes"] == ["card", "screen"]
    assert set(payload["candidate_pools"]) == set(CANDIDATE_POOLS)
    assert set(payload["rank_keys"]) == set(RANK_KEYS)
    assert set(payload["selector_ids"]) == set(SELECTOR_IDS)
    assert payload["default_universe_mode"] == "card"
    assert payload["default_candidate_pool"] == workflow_service.DEFAULT_CANDIDATE_POOL
    assert payload["default_rank_key"] == workflow_service.DEFAULT_RANK_KEY
    assert payload["default_screen_top_n"] == workflow_service.DEFAULT_SCREEN_TOP_N


def test_validate_screen_entry_rule_accepts_none_and_a_good_expression() -> None:
    assert workflow_service._validate_screen_entry_rule(None) is None
    rule = "close > sma(200) and ema(20) > ema(50)"
    assert workflow_service._validate_screen_entry_rule(rule) == rule


def test_validate_screen_entry_rule_rejects_a_bad_expression() -> None:
    import pytest

    with pytest.raises(workflow_service.InvalidRequest, match="not a valid entry expression"):
        workflow_service._validate_screen_entry_rule("close >>> not a rule")
