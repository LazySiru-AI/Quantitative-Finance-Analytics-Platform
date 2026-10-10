"""The three model-spending desks check the rolling daily spend cap before they start a run.

SEC-04 from the 2026-09-10 audit: ``app.agents.spend.LEDGER.check`` gated the manager, persona,
i18n and evolution paths, but nothing in ``app.tradingagents``, ``app.vibedesk`` or
``app.workflow``. Those are precisely the three surfaces that spawn multi-stage model runs -- and
the workflow desk launches child runs of its own -- so the cap could be met and a caller could still
start an unbounded amount of new spending from the UI.

Two things are asserted per desk, and the second is the one that matters:

1. ``SpendCapExceeded`` propagates out of the launcher (``app.main`` maps it to a 429 with
   ``Retry-After``, so no desk needs to translate it itself); and
2. **no run directory is left behind**. The check has to sit before the ``RunStore.save`` that
   creates ``data/agentdesk/<kind>/runs/<run_id>/``, or a capped desk accumulates queued runs no
   worker will ever pick up -- which is how a cap that "works" still costs a cleanup.

`LEDGER` is monkeypatched rather than filled with recorded spend so these tests neither depend on
the real cap value in settings nor leak entries into the process-wide ledger other tests share.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.agentdesk.models import runs_dir
from app.agents.spend import SpendCapExceeded
from app.config import Settings


@pytest.fixture
def capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `LEDGER.check` raise wherever it is called from, however the caller imported it.

    Patched on the `SpendLedger` **instance** rather than on each module's imported name: every
    caller does `from app.agents.spend import LEDGER` and then `LEDGER.check(...)`, so one patch on
    the shared object reaches all of them and cannot be defeated by a module that binds the name
    differently later.
    """

    def _raise(cap_usd: Decimal, **_kwargs: object) -> None:
        raise SpendCapExceeded(Decimal("99"), Decimal("10"), retry_after_seconds=3600)

    from app.agents import spend

    monkeypatch.setattr(spend.LEDGER, "check", _raise)


def _run_dirs(settings: Settings, kind: str) -> list[str]:
    base = runs_dir(settings, kind)  # type: ignore[arg-type]
    if not base.is_dir():
        return []
    return sorted(entry.name for entry in base.iterdir())


class TestTradingAgentsDesk:
    def test_start_run_raises_and_creates_no_run_dir(
        self, settings: Settings, capped: None
    ) -> None:
        from app.api.tradingagents import StartRunRequest
        from app.tradingagents import service

        before = _run_dirs(settings, "tradingagents")
        with pytest.raises(SpendCapExceeded):
            service.start_run(StartRunRequest(symbol="AAPL"), settings=settings)
        assert _run_dirs(settings, "tradingagents") == before


class TestVibedeskDesk:
    def test_start_run_raises_and_creates_no_run_dir(
        self, settings: Settings, capped: None
    ) -> None:
        from app.vibedesk import service
        from app.vibedesk.schemas import StartSwarmRequest

        before = _run_dirs(settings, "vibedesk")
        with pytest.raises(SpendCapExceeded):
            service.start_run(
                StartSwarmRequest(preset="sentiment-intelligence-team", symbol="AAPL"),
                settings=settings,
            )
        assert _run_dirs(settings, "vibedesk") == before


class TestWorkflowDesk:
    def test_start_workflow_run_raises_and_creates_no_run_dir(
        self, settings: Settings, capped: None
    ) -> None:
        from app.workflow import service
        from app.workflow.schemas import WorkflowRunRequest

        before = _run_dirs(settings, "workflow")
        with pytest.raises(SpendCapExceeded):
            service.start_workflow_run(WorkflowRunRequest(), settings=settings)
        assert _run_dirs(settings, "workflow") == before


class TestTheCheckIsFirst:
    """The cap is checked before *any* other validation, so a capped desk answers "over budget"
    rather than a 503 for a missing credential or a 422 for a malformed request -- the caller's
    problem is the cap, and telling them about a different one sends them fixing the wrong thing."""

    def test_tradingagents_reports_the_cap_not_the_missing_agent_layer(
        self, settings: Settings, capped: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.agents import client as agents_client
        from app.api.tradingagents import StartRunRequest
        from app.tradingagents import service

        monkeypatch.setattr(agents_client, "is_available", lambda: (False, "no credential"))
        with pytest.raises(SpendCapExceeded):
            service.start_run(StartRunRequest(symbol="AAPL"), settings=settings)

    def test_vibedesk_reports_the_cap_not_the_unknown_preset(
        self, settings: Settings, capped: None
    ) -> None:
        from app.vibedesk import service
        from app.vibedesk.schemas import StartSwarmRequest

        with pytest.raises(SpendCapExceeded):
            service.start_run(
                StartSwarmRequest(preset="no-such-preset", symbol="AAPL"), settings=settings
            )

    def test_workflow_reports_the_cap_not_the_missing_agent_layer(
        self, settings: Settings, capped: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.agents import client as agents_client
        from app.workflow import service
        from app.workflow.schemas import WorkflowRunRequest

        monkeypatch.setattr(agents_client, "is_available", lambda: (False, "no credential"))
        with pytest.raises(SpendCapExceeded):
            service.start_workflow_run(WorkflowRunRequest(), settings=settings)


class TestAnUncappedDeskIsUnaffected:
    """A zero/negative cap means unlimited (`SpendLedger.check`'s own contract), so the added call
    must be invisible when the cap is off -- otherwise this fix would break every local run."""

    def test_check_is_called_with_the_settings_cap(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.agents import client as agents_client
        from app.agents import spend
        from app.api.tradingagents import StartRunRequest
        from app.tradingagents import service

        seen: list[Decimal] = []
        monkeypatch.setattr(spend.LEDGER, "check", lambda cap: seen.append(cap))
        # Stop the launcher immediately after the cap check, so this test asserts the call and
        # nothing about the run machinery behind it.
        monkeypatch.setattr(agents_client, "is_available", lambda: (False, "no credential"))

        from app.agents.models import AgentUnavailable

        with pytest.raises(AgentUnavailable):
            service.start_run(StartRunRequest(symbol="AAPL"), settings=settings)
        assert seen == [settings.model_spend_daily_cap_usd]
