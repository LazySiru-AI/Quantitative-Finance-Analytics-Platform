"""`app.manager.commissions` -- the manager running its own commissioned research in-process.

No real model call, market data read, or agent-layer probe happens here: every child service's
`start_run`/`start_workflow_run`/`ask` is monkeypatched on `app.manager.commissions` itself (the
module-level references this module imports), and `RunStore` is replaced with a fake whose `load`
returns a pre-baked terminal `DeskRun` -- exactly the shape `app.workflow.pipeline`'s own tests use for
its child-launch helpers. What is exercised for real is `commissions.py`'s own orchestration: the
approve/decline state flips, the autonomy policy, the launch-and-await sequence, and every failure path
degrading to `state="failed"`/`"cancelled"` instead of raising.
"""

from __future__ import annotations

import datetime as dt
import threading
from decimal import Decimal

import pytest

from app.agentdesk.jobs import RunAlreadyActive
from app.agentdesk.models import DeskRun
from app.agents.models import AgentBudget, AgentUnavailable
from app.config import Settings
from app.manager import commissions
from app.manager.models import Commission
from app.personas.models import GroundingVerdict, PersonaAnswer
from app.personas.service import PersonaError

CREATED = dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.UTC)


def _commission(kind: str, *, params: dict | None = None, state: str = "approved", budget_usd: str = "4.00") -> Commission:
    return Commission(
        commission_id="c-1",
        kind=kind,  # type: ignore[arg-type]
        params=params or {},
        rationale="test rationale",
        budget_usd=budget_usd,
        state=state,  # type: ignore[arg-type]
    )


def _terminal_run(kind: str, run_id: str, *, state: str = "succeeded", final_rating: str = "",
                   final_md: str = "", error: str = "", cost: str = "3.00") -> DeskRun:
    return DeskRun(
        run_id=run_id,
        kind=kind,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        created_at=CREATED,
        completed_at=CREATED,
        config={},
        final_md=final_md,
        final_rating=final_rating,
        error=error,
        budget=AgentBudget(cap_usd=Decimal("4.00"), spent_usd=Decimal(cost), calls=1),
    )


class _FakeRunStore:
    """Replaces `app.manager.commissions.RunStore`. `runs` maps run_id -> the terminal `DeskRun` a
    poll should immediately see -- every commission test here bakes the child run terminal from the
    start, so `_await_child`'s loop resolves on its very first iteration and no real sleep happens."""

    runs: dict[str, DeskRun] = {}

    def __init__(self, settings: Settings, kind: str) -> None:
        self.kind = kind

    def load(self, run_id: str) -> DeskRun | None:
        return _FakeRunStore.runs.get(run_id)


@pytest.fixture(autouse=True)
def _patch_run_store(monkeypatch: pytest.MonkeyPatch):
    _FakeRunStore.runs = {}
    monkeypatch.setattr(commissions, "RunStore", _FakeRunStore)
    yield
    _FakeRunStore.runs = {}


class _FakeRegistry:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def cancel(self, run_id: str) -> bool:
        self.cancelled.append(run_id)
        return True


# ---------------------------------------------------------------------------
# may_run_unattended
# ---------------------------------------------------------------------------


def test_may_run_unattended_false_when_autonomy_is_propose(settings: Settings) -> None:
    settings.manager_autonomy = "propose"
    settings.manager_unattended_kinds = "persona_chat,vibedesk"
    for kind in ("tradingagents", "vibedesk", "workflow", "persona_chat"):
        assert commissions.may_run_unattended(_commission(kind), settings) is False


def test_may_run_unattended_respects_kind_list(settings: Settings) -> None:
    settings.manager_autonomy = "auto_bounded"
    settings.manager_unattended_kinds = "persona_chat,vibedesk"
    assert commissions.may_run_unattended(_commission("persona_chat"), settings) is True
    assert commissions.may_run_unattended(_commission("vibedesk"), settings) is True
    assert commissions.may_run_unattended(_commission("tradingagents"), settings) is False
    assert commissions.may_run_unattended(_commission("workflow"), settings) is False


def test_may_run_unattended_honours_custom_kind_list(settings: Settings) -> None:
    settings.manager_autonomy = "auto_bounded"
    settings.manager_unattended_kinds = "tradingagents"
    assert commissions.may_run_unattended(_commission("tradingagents"), settings) is True
    assert commissions.may_run_unattended(_commission("vibedesk"), settings) is False


# ---------------------------------------------------------------------------
# approve / decline
# ---------------------------------------------------------------------------


def test_approve_flips_state_to_approved() -> None:
    commission = _commission("vibedesk", state="proposed")
    approved = commissions.approve(commission)
    assert approved.state == "approved"
    assert commission.state == "proposed"  # frozen input untouched


def test_decline_flips_state_to_declined() -> None:
    commission = _commission("vibedesk", state="proposed")
    declined = commissions.decline(commission)
    assert declined.state == "declined"


# ---------------------------------------------------------------------------
# execute: gating on approval
# ---------------------------------------------------------------------------


def test_execute_does_not_run_an_unapproved_commission(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def _boom(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("start_run must not be called for an unapproved commission")

    monkeypatch.setattr(commissions.tradingagents_service, "start_run", _boom)

    commission = _commission("tradingagents", state="proposed")
    result = commissions.execute(commission, settings=settings)

    assert called is False
    assert result.state == "proposed"
    assert "not run" in result.child_summary


@pytest.mark.parametrize("state", ["succeeded", "failed", "cancelled", "declined"])
def test_execute_does_not_run_a_terminal_commission(settings: Settings, monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    def _boom(*_args, **_kwargs):
        raise AssertionError("must not launch a terminal commission")

    monkeypatch.setattr(commissions.tradingagents_service, "start_run", _boom)
    commission = _commission("tradingagents", state=state)
    result = commissions.execute(commission, settings=settings)
    assert result.state == state


# ---------------------------------------------------------------------------
# execute: each kind's happy path
# ---------------------------------------------------------------------------


def test_execute_tradingagents_succeeds(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    seen_req = {}

    def _fake_start_run(req, *, settings):
        seen_req["symbol"] = req.symbol
        seen_req["budget_usd"] = req.budget_usd
        return _terminal_run("tradingagents", "ta-run-1", state="queued")

    monkeypatch.setattr(commissions.tradingagents_service, "start_run", _fake_start_run)
    _FakeRunStore.runs["ta-run-1"] = _terminal_run(
        "tradingagents", "ta-run-1", state="succeeded", final_rating="Buy", final_md="Strong setup on NVDA."
    )

    commission = _commission("tradingagents", params={"symbol": "NVDA"}, budget_usd="4.50")
    result = commissions.execute(commission, settings=settings)

    assert seen_req["symbol"] == "NVDA"
    assert seen_req["budget_usd"] == "4.50"
    assert result.state == "succeeded"
    assert result.child_run_id == "ta-run-1"
    assert "Buy" in result.child_summary
    assert "NVDA" in result.child_summary or "setup" in result.child_summary


def test_execute_vibedesk_succeeds(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    seen_req = {}

    def _fake_start_run(req, *, settings):
        seen_req["preset"] = req.preset
        seen_req["symbol"] = req.symbol
        return _terminal_run("vibedesk", "vibe-run-1", state="queued")

    monkeypatch.setattr(commissions.vibedesk_service, "start_run", _fake_start_run)
    _FakeRunStore.runs["vibe-run-1"] = _terminal_run(
        "vibedesk", "vibe-run-1", state="succeeded", final_md="VERDICT: SUPPORT for AMD."
    )

    commission = _commission(
        "vibedesk", params={"preset": "followup_review", "symbol": "AMD", "question": "Does the thesis hold?"}
    )
    result = commissions.execute(commission, settings=settings)

    assert seen_req["preset"] == "followup_review"
    assert seen_req["symbol"] == "AMD"
    assert result.state == "succeeded"
    assert result.child_run_id == "vibe-run-1"
    assert "SUPPORT" in result.child_summary


def test_execute_workflow_succeeds(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    seen_req = {}

    def _fake_start_workflow_run(req, *, settings):
        seen_req["agent_card_id"] = req.agent_card_id
        return _terminal_run("workflow", "wf-run-1", state="queued")

    monkeypatch.setattr(commissions.workflow_service, "start_workflow_run", _fake_start_workflow_run)
    _FakeRunStore.runs["wf-run-1"] = _terminal_run(
        "workflow", "wf-run-1", state="succeeded", final_md="Staged 2 orders for B-momentum."
    )

    commission = _commission("workflow", params={"agent_card_id": "B-momentum"})
    result = commissions.execute(commission, settings=settings)

    assert seen_req["agent_card_id"] == "B-momentum"
    assert result.state == "succeeded"
    assert result.child_run_id == "wf-run-1"
    assert "B-momentum" in result.child_summary


def test_execute_persona_chat_succeeds_with_no_child_run(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    answer = PersonaAnswer(
        persona="testpersona",
        question="What do you think of NVDA?",
        symbol="NVDA",
        answer="I'd stay disciplined here and watch the thesis, not the ticker.",
        citations=("note-1",),
        grounding=GroundingVerdict(ok=True),
    )

    def _fake_ask(settings, slug, *, question, symbol):
        assert slug == "testpersona"
        assert question == "What do you think of NVDA?"
        assert symbol == "NVDA"
        return answer

    monkeypatch.setattr(commissions.personas_service, "ask", _fake_ask)

    commission = _commission(
        "persona_chat", params={"slug": "testpersona", "question": "What do you think of NVDA?", "symbol": "NVDA"}
    )
    result = commissions.execute(commission, settings=settings)

    assert result.state == "succeeded"
    assert result.child_run_id is None
    assert "disciplined" in result.child_summary


# ---------------------------------------------------------------------------
# execute: failure paths never raise
# ---------------------------------------------------------------------------


def test_execute_child_failure_degrades_to_failed(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        commissions.tradingagents_service, "start_run",
        lambda req, *, settings: _terminal_run("tradingagents", "ta-fail-1", state="queued"),
    )
    _FakeRunStore.runs["ta-fail-1"] = _terminal_run(
        "tradingagents", "ta-fail-1", state="failed", error="agent budget exhausted mid-run"
    )

    commission = _commission("tradingagents", params={"symbol": "TSLA"})
    result = commissions.execute(commission, settings=settings)

    assert result.state == "failed"
    assert result.child_run_id == "ta-fail-1"
    assert "budget exhausted" in result.child_summary


def test_execute_agent_unavailable_degrades_to_failed(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_unavailable(req, *, settings):
        raise AgentUnavailable("no credential configured")

    monkeypatch.setattr(commissions.tradingagents_service, "start_run", _raise_unavailable)

    commission = _commission("tradingagents", params={"symbol": "TSLA"})
    result = commissions.execute(commission, settings=settings)

    assert result.state == "failed"
    assert "agent layer unavailable" in result.child_summary


def test_execute_run_already_active_degrades_to_failed(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_active(req, *, settings):
        raise RunAlreadyActive("vibedesk", "vibe-other-run")

    monkeypatch.setattr(commissions.vibedesk_service, "start_run", _raise_active)

    commission = _commission("vibedesk", params={"preset": "followup_review", "symbol": "AMD"})
    result = commissions.execute(commission, settings=settings)

    assert result.state == "failed"
    assert "already active" in result.child_summary


def test_execute_persona_chat_error_degrades_to_failed(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_persona_error(settings, slug, *, question, symbol):
        raise PersonaError("no persona 'ghost'", status_code=404)

    monkeypatch.setattr(commissions.personas_service, "ask", _raise_persona_error)

    commission = _commission("persona_chat", params={"slug": "ghost", "question": "hi"})
    result = commissions.execute(commission, settings=settings)

    assert result.state == "failed"
    assert result.child_run_id is None
    assert "ghost" in result.child_summary


# ---------------------------------------------------------------------------
# execute: timeout and cancel paths cancel the child through the registry
# ---------------------------------------------------------------------------


def test_execute_timeout_cancels_child_and_marks_failed(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_registry = _FakeRegistry()
    monkeypatch.setattr(commissions, "registry", lambda: fake_registry)
    monkeypatch.setattr(commissions, "_CHILD_TIMEOUT_S", 0)
    monkeypatch.setattr(commissions.time, "sleep", lambda _s: None)

    monkeypatch.setattr(
        commissions.tradingagents_service, "start_run",
        lambda req, *, settings: _terminal_run("tradingagents", "ta-wedge-1", state="queued"),
    )
    # Never terminal -- the store keeps reporting "running", so the loop can only exit via timeout.
    _FakeRunStore.runs["ta-wedge-1"] = _terminal_run("tradingagents", "ta-wedge-1", state="running")

    commission = _commission("tradingagents", params={"symbol": "MSFT"})
    result = commissions.execute(commission, settings=settings)

    assert result.state == "failed"
    assert result.child_run_id == "ta-wedge-1"
    assert "timed out" in result.child_summary
    assert fake_registry.cancelled == ["ta-wedge-1"]


def test_execute_cancel_event_cancels_child_and_marks_cancelled(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_registry = _FakeRegistry()
    monkeypatch.setattr(commissions, "registry", lambda: fake_registry)

    monkeypatch.setattr(
        commissions.vibedesk_service, "start_run",
        lambda req, *, settings: _terminal_run("vibedesk", "vibe-cancel-1", state="queued"),
    )
    _FakeRunStore.runs["vibe-cancel-1"] = _terminal_run("vibedesk", "vibe-cancel-1", state="running")

    cancel = threading.Event()
    cancel.set()

    commission = _commission("vibedesk", params={"preset": "followup_review", "symbol": "AMD"})
    result = commissions.execute(commission, settings=settings, cancel=cancel)

    assert result.state == "cancelled"
    assert result.child_run_id == "vibe-cancel-1"
    assert fake_registry.cancelled == ["vibe-cancel-1"]
