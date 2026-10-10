"""Tests for `app.agents.review_models` and `app.agents.reviewer`.

**Everything here runs fully offline**, mirroring `tests/test_agents_designer.py`'s own two-boundary
approach:

* `TestReviewGenerationCredentialAndBudget` calls `app.agents.reviewer.review_generation` without
  monkeypatching `call_structured` at all, relying on the real `app.agents.client.call_structured` to
  fail before it would ever touch the network -- no credential is configured (see
  `_hermetic_anthropic_env` below) and the budget-exhausted case raises before `import anthropic` is
  even reached, so neither test needs a fake SDK module.
* Every other test monkeypatches `app.agents.reviewer.call_structured` directly, since everything this
  module needs to prove (the no-measurement check, per-candidate coverage, the amendment-value
  exemption, shape inference, the failed-generation path) sits above the client boundary.

**`TestReviewerRoleLiteralGap` records a contract gap that is now closed, and stays as the regression
test for it.** `app.agents.models.AgentCall.role` and `app.agents.client.call_structured`'s own `role`
parameter were both typed `Literal["designer", "scout"]`. This module's contract requires
`call_structured(role="reviewer", ...)`, and `AgentCall.role` is a `pydantic` field -- so
`AgentCall(role="reviewer", ...)` raised `pydantic.ValidationError` *inside* `call_structured`, after a
successful model response and before it could return. Every unit test here monkeypatches
`call_structured`, so the whole suite passed green while the real end-to-end path could not execute
once: that is precisely the failure mode this test exists to catch, and it is why it drives the real
client rather than a fake.

Both `Literal`s now carry `"reviewer"`. The test is therefore an ordinary passing test, not an
`xfail` -- narrowing either `Literal` again fails it immediately. The `role` field is deliberately a
closed `Literal` rather than a free string (an archived call is grouped and audited by role), which
means adding an agent is an edit in three places, and this test is what makes the third one
unforgettable.

Note that several tests here still build their fake `AgentCall` with `.model_construct(...)`, which
skips `pydantic` validation. That is a test-only affordance for constructing a stub cheaply --
`app.agents.reviewer` itself always goes through the real constructor -- and it is exactly why it
could not have caught this gap on its own.
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.agents import cli_transport
from app.agents import reviewer as reviewer_module
from app.agents.client import call_structured
from app.agents.models import (
    DEFAULT_MODEL,
    AgentBudget,
    AgentCall,
    AgentUnavailable,
    BudgetExhausted,
    agent_calls_dir,
)
from app.agents.prompts import REVIEWER_SYSTEM_PROMPT
from app.agents.review_models import CandidateNote, ProposedAmendment, ReviewDirection
from app.agents.reviewer import review_generation
from app.config import Settings
from app.evolution.models import GenerationOutcome, Genome, LoopConfig, Standing
from app.evolution.universe import pool_for
from app.tournament.purposes import Purpose

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """A `Settings` rooted entirely under `tmp_path` -- never the real `data/`."""
    return Settings(
        repo_root=tmp_path,
        data_dir=tmp_path / "data",
        store_dir=tmp_path / "store",
        cache_dir=tmp_path / "cache",
    )


@pytest.fixture(autouse=True)
def _hermetic_anthropic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every test starts with no Anthropic credential of any kind, regardless of what is actually
    set on the machine running the suite -- a developer's own `ANTHROPIC_API_KEY` or `ant auth login`
    profile must never leak into these tests and change their outcome.

    **"Of any kind" now has to include the Claude Code CLI, and leaving it out made one test
    order-dependent.** When this fixture was written the three environment variables below were the
    only ways to reach a model, so deleting them produced a credential-less machine. Then
    `app.agents.cli_transport` added a fourth transport that is found by a filesystem and `PATH`
    lookup rather than by an environment variable -- so on a machine with Claude Code installed (this
    one), blanking the three variables left `client.is_available()` returning `True` via the CLI, and
    `test_missing_credential_surfaces_as_agent_unavailable` stopped raising.

    It did not fail consistently, which is the part worth recording: the test passed when this file
    was run alongside its four sibling agent suites and failed in the full run, so a targeted re-run
    of the "obviously related" files reported green while the whole suite was red. Patching
    `resolve_cli_binary` here rather than inside the one failing test keeps the fixture's promise
    literally true for every test in the file, which is what stops the next transport from
    reintroducing the same latent order dependence.

    A test that deliberately wants a working transport (`TestReviewerRoleLiteralGap`) sets its own
    `ANTHROPIC_API_KEY` and injects a fake `anthropic` module, and the SDK path outranks the CLI, so
    it is unaffected by the patch below.
    """
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "anthropic-config-unused"))
    monkeypatch.setattr(cli_transport, "resolve_cli_binary", lambda: None)


class _DummyOutput(BaseModel):
    """A trivial `output_format` for the client-level xfail test, which never inspects the parsed
    content -- only whether `AgentCall` construction accepts `role="reviewer"`."""

    value: str = "x"


# ---------------------------------------------------------------------------
# Test-data builders
# ---------------------------------------------------------------------------


def _make_config(**overrides: Any) -> LoopConfig:
    defaults: dict[str, Any] = {"population": 3, "goal": "find something that beats the benchmark"}
    defaults.update(overrides)
    return LoopConfig(**defaults)


def _make_standing(**overrides: Any) -> Standing:
    defaults: dict[str, Any] = {
        "genome_id": "g001-aaa",
        "agent_id": "g001-aaa",
        "display_name": "Trend A",
        "rank": 1,
        "eligible": True,
        "windows_run": 6,
        "median_excess": Decimal("0.05"),
        "worst_excess": Decimal("0.01"),
        "hit_rate": 0.6,
        "total_trades": 12,
        "holdout_median_excess": Decimal("0.02"),
        "q_value": 0.2,
    }
    defaults.update(overrides)
    return Standing(**defaults)


def _make_genome(**overrides: Any) -> Genome:
    pool = pool_for(Purpose.TRADING)
    defaults: dict[str, Any] = {
        "genome_id": "g001-aaa",
        "generation": 1,
        "parents": (),
        "origin": "mutation",
        "shape": "rules",
        "purpose": Purpose.TRADING,
        "universe": tuple(pool.growth[:3]),
        "traits": {
            "fast": 10,
            "slow": 20,
            "regime_ma": 100,
            "stop_loss_pct": 0.08,
            "take_profit_pct": 0.25,
            "max_hold_days": 90,
            "max_positions": 4,
            "position_pct": 0.2,
            "rank_key": "rsi(14)",
            "discipline": "trend",
        },
        "seed": 1,
        "notes": "trend continuation",
    }
    defaults.update(overrides)
    return Genome(**defaults)


def _make_outcome(**overrides: Any) -> GenerationOutcome:
    now = dt.datetime.now(dt.UTC)
    defaults: dict[str, Any] = {
        "generation": 1,
        "round_id": "r1-auto-test",
        "purpose": Purpose.TRADING,
        "job_id": None,
        "status": "succeeded",
        "started_at": now,
        "finished_at": now,
        "windows": ("chop-2015", "gfc"),
        "holdout_windows": ("covid",),
        "genome_ids": (),
        "standings": (),
        "findings": (),
        "promoted": (),
        "error": None,
    }
    defaults.update(overrides)
    return GenerationOutcome(**defaults)


def _make_call(**overrides: Any) -> AgentCall:
    """A fake `AgentCall` carrying `role="reviewer"`, built via `.model_construct` rather than the
    real constructor -- see this module's own docstring for why `AgentCall(role="reviewer", ...)`
    cannot be called directly yet, and why that gap belongs to `app/agents/models.py`, not here."""
    defaults: dict[str, Any] = {
        "call_id": "call-test-0001",
        "role": "reviewer",
        "model": DEFAULT_MODEL,
        "created_at": dt.datetime.now(dt.UTC),
        "system": REVIEWER_SYSTEM_PROMPT,
        "user": "usr",
        "raw_response": "{}",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cost_usd": Decimal("0.05"),
        "request_id": None,
        "stop_reason": "end_turn",
    }
    defaults.update(overrides)
    return AgentCall.model_construct(**defaults)


# ---------------------------------------------------------------------------
# app.agents.prompts.REVIEWER_SYSTEM_PROMPT -- never invites a stated measurement
# ---------------------------------------------------------------------------


class TestReviewerSystemPrompt:
    def test_forbids_stating_a_measurement(self) -> None:
        assert "NEVER EMIT A NUMBER" in REVIEWER_SYSTEM_PROMPT
        assert "q-value" in REVIEWER_SYSTEM_PROMPT

    def test_requires_a_note_for_every_candidate(self) -> None:
        lowered = REVIEWER_SYSTEM_PROMPT.lower()
        assert "every single one of them" in lowered or "no exceptions" in lowered

    def test_states_the_noise_floor_counter_argument(self) -> None:
        assert "21.2" in REVIEWER_SYSTEM_PROMPT
        assert "53.9" in REVIEWER_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# app.agents.reviewer.review_generation -- valid path
# ---------------------------------------------------------------------------


class TestReviewGeneration:
    def test_well_formed_review_round_trips_with_a_note_for_every_standing(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        standing_a = _make_standing(genome_id="g001-aaa", agent_id="g001-aaa", rank=1)
        standing_b = _make_standing(
            genome_id="g001-bbb",
            agent_id="g001-bbb",
            rank=2,
            eligible=False,
            median_excess=None,
            worst_excess=None,
            hit_rate=None,
            holdout_median_excess=None,
            q_value=None,
            total_trades=0,
        )
        outcome = _make_outcome(standings=(standing_a, standing_b), genome_ids=("g001-aaa", "g001-bbb"))
        pool = pool_for(Purpose.TRADING)
        genome_a = _make_genome(genome_id="g001-aaa")
        genome_b = _make_genome(genome_id="g001-bbb", universe=tuple(pool.growth[3:6]))

        output = reviewer_module._ReviewerOutput(
            verdict="promising",
            post_mortem=(
                "The trend design held up while the mean-reversion design took no trades at all."
            ),
            per_candidate=[
                CandidateNote(
                    genome_id="g001-aaa",
                    note="Led the field and stayed positive out of sample; worth carrying forward.",
                    keep=True,
                ),
                CandidateNote(
                    genome_id="g001-bbb",
                    note="Never qualified and took no trades; there is nothing here to build on.",
                    keep=False,
                ),
            ],
            direction=ReviewDirection(headline="Trend continuation is worth another generation."),
            amendments=[],
        )
        call = _make_call()
        new_budget = AgentBudget(cap_usd=Decimal("10.00"), spent_usd=Decimal("0.05"), calls=1)

        def fake_call_structured(**kwargs: Any) -> tuple[Any, AgentCall, AgentBudget]:
            assert kwargs["role"] == "reviewer"
            assert kwargs["system"] == REVIEWER_SYSTEM_PROMPT
            assert "g001-aaa" in kwargs["user"]
            assert "g001-bbb" in kwargs["user"]
            return output, call, new_budget

        monkeypatch.setattr(reviewer_module, "call_structured", fake_call_structured)

        review, returned_budget = review_generation(
            outcome=outcome,
            config=_make_config(),
            settings=settings,
            budget=AgentBudget(cap_usd=Decimal("10.00")),
            genomes=(genome_a, genome_b),
        )

        assert returned_budget == new_budget
        assert review.verdict == "promising"
        assert {note.genome_id for note in review.per_candidate} == {"g001-aaa", "g001-bbb"}
        assert review.shape == "rules"
        assert review.purpose is Purpose.TRADING
        assert review.generation == outcome.generation
        assert review.call is call

    def test_shape_is_none_when_no_genomes_supplied(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        standing = _make_standing()
        outcome = _make_outcome(standings=(standing,))
        output = reviewer_module._ReviewerOutput(
            verdict="inconclusive",
            post_mortem="Only one candidate ran and it did not clear the gate.",
            per_candidate=[CandidateNote(genome_id=standing.genome_id, note="Did not clear the gate.", keep=False)],
            direction=ReviewDirection(headline="Not enough here yet."),
        )
        monkeypatch.setattr(
            reviewer_module,
            "call_structured",
            lambda **kw: (output, _make_call(), AgentBudget(cap_usd=Decimal("10.00"))),
        )

        review, _budget = review_generation(
            outcome=outcome, config=_make_config(), settings=settings, budget=AgentBudget(cap_usd=Decimal("10.00"))
        )
        assert review.shape is None

    # -- the mechanical no-measurement check ------------------------------------------------------

    def test_prose_with_ascii_digit_is_rejected(self, monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
        standing = _make_standing()
        outcome = _make_outcome(standings=(standing,))
        output = reviewer_module._ReviewerOutput(
            verdict="inconclusive",
            post_mortem="This looked steady after 2 generations of testing.",
            per_candidate=[CandidateNote(genome_id=standing.genome_id, note="steady", keep=True)],
            direction=ReviewDirection(headline="steady"),
        )
        monkeypatch.setattr(
            reviewer_module,
            "call_structured",
            lambda **kw: (output, _make_call(), AgentBudget(cap_usd=Decimal("10.00"))),
        )

        with pytest.raises(AgentUnavailable, match="reads as a number"):
            review_generation(
                outcome=outcome, config=_make_config(), settings=settings, budget=AgentBudget(cap_usd=Decimal("10.00"))
            )

    @pytest.mark.parametrize(
        "char",
        [chr(0x0664), chr(0x216B)],
        ids=["arabic-indic-four", "roman-numeral-twelve"],
    )
    def test_prose_with_non_ascii_numeral_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings, char: str
    ) -> None:
        """An ASCII-only digit check would wave both of these through -- U+0664 (Arabic-Indic four,
        category Nd) is a digit `int()` can parse, and U+216B (Roman numeral twelve, category Nl) is
        not even in `Nd` but still reads as a number to anyone looking at the screen. This is the
        exact bug `app.report.narrative._is_digit`'s own docstring names, reproduced here to prove
        `app.agents.reviewer` reuses that detector rather than a narrower one."""
        standing = _make_standing()
        outcome = _make_outcome(standings=(standing,))
        output = reviewer_module._ReviewerOutput(
            verdict="inconclusive",
            post_mortem=f"This looked steady across several generations{char}",
            per_candidate=[CandidateNote(genome_id=standing.genome_id, note="steady", keep=True)],
            direction=ReviewDirection(headline="steady"),
        )
        monkeypatch.setattr(
            reviewer_module,
            "call_structured",
            lambda **kw: (output, _make_call(), AgentBudget(cap_usd=Decimal("10.00"))),
        )

        with pytest.raises(AgentUnavailable, match="reads as a number"):
            review_generation(
                outcome=outcome, config=_make_config(), settings=settings, budget=AgentBudget(cap_usd=Decimal("10.00"))
            )

    def test_amendment_value_may_be_a_number(self, monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
        """The one field exempt from the no-measurement rule: `ProposedAmendment.value` is a control
        setting the agent is choosing for the next generation, not a claim about this one."""
        standing = _make_standing()
        outcome = _make_outcome(standings=(standing,))
        output = reviewer_module._ReviewerOutput(
            verdict="promising",
            post_mortem="The field cleared the gate cleanly this time.",
            per_candidate=[CandidateNote(genome_id=standing.genome_id, note="Cleared the gate cleanly.", keep=True)],
            direction=ReviewDirection(headline="Raise the bar."),
            amendments=[
                ProposedAmendment(
                    field="promotion_margin_pp",
                    value=25,
                    reason=(
                        "The field cleared the current margin without much room to spare, and the "
                        "measured noise floor argument still applies -- raising it keeps the gate at "
                        "least as strict as the ordering-noise measurement, not looser."
                    ),
                )
            ],
        )
        monkeypatch.setattr(
            reviewer_module,
            "call_structured",
            lambda **kw: (output, _make_call(), AgentBudget(cap_usd=Decimal("10.00"))),
        )

        review, _budget = review_generation(
            outcome=outcome, config=_make_config(), settings=settings, budget=AgentBudget(cap_usd=Decimal("10.00"))
        )
        assert review.amendments[0].value == 25
        assert review.amendments[0].field == "promotion_margin_pp"

    # -- whole-field coverage -----------------------------------------------------------------------

    def test_per_candidate_naming_unknown_genome_id_raises(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        standing = _make_standing()
        outcome = _make_outcome(standings=(standing,))
        output = reviewer_module._ReviewerOutput(
            verdict="inconclusive",
            post_mortem="fine",
            per_candidate=[CandidateNote(genome_id="not-a-real-genome", note="fine", keep=True)],
            direction=ReviewDirection(headline="steady"),
        )
        monkeypatch.setattr(
            reviewer_module,
            "call_structured",
            lambda **kw: (output, _make_call(), AgentBudget(cap_usd=Decimal("10.00"))),
        )

        with pytest.raises(AgentUnavailable, match="not among this"):
            review_generation(
                outcome=outcome, config=_make_config(), settings=settings, budget=AgentBudget(cap_usd=Decimal("10.00"))
            )

    def test_per_candidate_omitting_a_standing_raises(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        standing_a = _make_standing(genome_id="g001-aaa", agent_id="g001-aaa", rank=1)
        standing_b = _make_standing(genome_id="g001-bbb", agent_id="g001-bbb", rank=2)
        outcome = _make_outcome(standings=(standing_a, standing_b))
        output = reviewer_module._ReviewerOutput(
            verdict="inconclusive",
            post_mortem="fine",
            per_candidate=[CandidateNote(genome_id="g001-aaa", note="fine", keep=True)],
            direction=ReviewDirection(headline="steady"),
        )
        monkeypatch.setattr(
            reviewer_module,
            "call_structured",
            lambda **kw: (output, _make_call(), AgentBudget(cap_usd=Decimal("10.00"))),
        )

        with pytest.raises(AgentUnavailable, match="omits"):
            review_generation(
                outcome=outcome, config=_make_config(), settings=settings, budget=AgentBudget(cap_usd=Decimal("10.00"))
            )

    # -- the failed-generation path -------------------------------------------------------------------

    def test_failed_outcome_still_produces_a_review(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        outcome = _make_outcome(
            status="failed", error="OSError: [Errno 30] Read-only file system", standings=(), genome_ids=()
        )
        output = reviewer_module._ReviewerOutput(
            verdict="broken",
            post_mortem="The generation could not write its results and never produced a standing.",
            per_candidate=[],
            direction=ReviewDirection(headline="Fix the write path before retrying."),
        )
        captured: dict[str, Any] = {}

        def fake_call_structured(**kwargs: Any) -> tuple[Any, AgentCall, AgentBudget]:
            captured["user"] = kwargs["user"]
            return output, _make_call(), AgentBudget(cap_usd=Decimal("10.00"), spent_usd=Decimal("0.05"), calls=1)

        monkeypatch.setattr(reviewer_module, "call_structured", fake_call_structured)

        review, _budget = review_generation(
            outcome=outcome, config=_make_config(), settings=settings, budget=AgentBudget(cap_usd=Decimal("10.00"))
        )
        assert review.verdict == "broken"
        assert review.per_candidate == ()
        assert "FAILED" in captured["user"]
        assert "Read-only file system" in captured["user"]


# ---------------------------------------------------------------------------
# Credential / budget failures -- through the real call_structured, unmonkeypatched
# ---------------------------------------------------------------------------


class TestReviewGenerationCredentialAndBudget:
    def test_missing_credential_surfaces_as_agent_unavailable(self, settings: Settings) -> None:
        """No `ANTHROPIC_API_KEY`, no `ANTHROPIC_AUTH_TOKEN`, no on-disk profile (see
        `_hermetic_anthropic_env`) -- `review_generation` calls the real `call_structured`, which
        raises `AgentUnavailable` before ever making a network call, regardless of whether the
        `anthropic` package itself happens to be installed in this environment."""
        outcome = _make_outcome()
        with pytest.raises(AgentUnavailable):
            review_generation(
                outcome=outcome, config=_make_config(), settings=settings, budget=AgentBudget(cap_usd=Decimal("10.00"))
            )

    def test_exhausted_budget_raises_without_calling_the_model(self, settings: Settings) -> None:
        outcome = _make_outcome()
        budget = AgentBudget(cap_usd=Decimal("1.00"), spent_usd=Decimal("1.00"))

        with pytest.raises(BudgetExhausted) as exc_info:
            review_generation(outcome=outcome, config=_make_config(), settings=settings, budget=budget)

        assert exc_info.value.spent_usd == Decimal("1.00")
        assert exc_info.value.cap_usd == Decimal("1.00")
        # Nothing archived -- the budget check happens before the model is ever reached, so there is
        # no AgentCall for app.agents.client._archive_call to have written.
        directory = agent_calls_dir(settings)
        assert not directory.exists() or not list(directory.glob("*.json"))


# ---------------------------------------------------------------------------
# The role="reviewer" contract gap in app/agents/models.py and app/agents/client.py
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(
        self,
        *,
        input_tokens: int = 100,
        output_tokens: int = 50,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens


class _FakeResponse:
    def __init__(
        self,
        *,
        parsed_output: Any,
        usage: _FakeUsage | None = None,
        stop_reason: str = "end_turn",
        request_id: str = "req_fake_0001",
    ) -> None:
        self.parsed_output = parsed_output
        self.usage = usage or _FakeUsage()
        self.stop_reason = stop_reason
        self._request_id = request_id
        self.content = ()
        self.stop_details = SimpleNamespace(category=None)


class _FakeMessages:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def parse(self, **kwargs: Any) -> _FakeResponse:
        return self._response


def _make_fake_anthropic_module(response: _FakeResponse) -> Any:
    """A minimal `SimpleNamespace` standing in for the `anthropic` module -- duplicated here rather
    than imported from `tests/test_agents_designer.py`, matching this file's own docstring on why
    that file's fake-client approach is mirrored rather than reused across test modules."""

    class _FakeAnthropicClient:
        def __init__(self, *, timeout: float | None = None) -> None:
            self.messages = _FakeMessages(response)

    return SimpleNamespace(
        Anthropic=_FakeAnthropicClient,
        AuthenticationError=type("AuthenticationError", (Exception,), {}),
        PermissionDeniedError=type("PermissionDeniedError", (Exception,), {}),
        RateLimitError=type("RateLimitError", (Exception,), {}),
        BadRequestError=type("BadRequestError", (Exception,), {}),
        APITimeoutError=type("APITimeoutError", (Exception,), {}),
        APIConnectionError=type("APIConnectionError", (Exception,), {}),
        APIStatusError=type("APIStatusError", (Exception,), {"status_code": 500}),
    )


class TestReviewerRoleLiteralGap:
    """See this module's own docstring, "One contract gap blocks the real end-to-end path". Kept as
    its own test rather than folded into `TestReviewGeneration` because it deliberately drives the
    real `app.agents.client.call_structured` (not a monkeypatched one) to prove the gap is in that
    module, not in anything owned by this task.
    """

    def test_real_call_structured_accepts_reviewer_role(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        response = _FakeResponse(parsed_output=_DummyOutput())
        module = _make_fake_anthropic_module(response)
        monkeypatch.setitem(sys.modules, "anthropic", module)

        budget = AgentBudget(cap_usd=Decimal("10.00"))
        _parsed, call, _new_budget = call_structured(
            role="reviewer",
            system="s",
            user="u",
            output_format=_DummyOutput,
            settings=settings,
            budget=budget,
        )
        assert call.role == "reviewer"
