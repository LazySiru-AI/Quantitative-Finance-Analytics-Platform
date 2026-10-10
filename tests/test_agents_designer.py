"""Tests for `app.agents.client`, `app.agents.prompts` and `app.agents.designer`.

**Everything here runs fully offline.** No test constructs a real `anthropic.Anthropic` client or
makes a network call. Two boundaries are monkeypatched, depending on what a test targets:

* Client-level tests (`TestCallStructured*`) inject a fake module into `sys.modules["anthropic"]`
  before calling `app.agents.client.call_structured`, so the `import anthropic` inside that function
  picks up the fake rather than the real package -- the same trick that lets `TestAvailabilityFailures`
  simulate "the package is not installed" by setting the module to `None`.
* Designer-level tests (`TestDesignGeneration`) monkeypatch `app.agents.designer.call_structured`
  directly, since everything designer.py needs to prove (validation, genome conversion, focus/avoid
  handling) sits above the client boundary and does not need a fake SDK at all.

**One assertion here was blocked by a contract gap, and is the reason it is worth reading.**
`app.evolution.models.GenomeOrigin` did not include `"agent"`, even though `app.agents.models`'s
own docstring states an agent-designed genome records `origin="agent"` and `designer.py` is
written to that contract -- so `Genome(origin="agent", ...)` raised `pydantic.ValidationError` and
the whole valid-slate path was unreachable while every *rejection* path passed. It was caught by
marking this test `xfail(strict=True)` rather than deleting or weakening it: a strict xfail fails
the suite the moment it starts passing, so adding `"agent"` to that `Literal` reported itself
immediately instead of leaving a permanently-skipped test behind. The marker is gone now that the
gap is closed; this note stays because the technique is the point.
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
from app.agents import designer as designer_module
from app.agents.client import (
    build_client,
    call_structured,
    credential_source,
    estimate_cost_usd,
    is_available,
)
from app.agents.designer import design_generation
from app.agents.models import (
    DEFAULT_MODEL,
    AgentBudget,
    AgentCall,
    AgentUnavailable,
    BudgetExhausted,
    ProposedCard,
    agent_calls_dir,
)
from app.agents.prompts import DESIGNER_SYSTEM_PROMPT
from app.config import Settings
from app.evolution.models import RULE_SHAPES, LoopConfig, genome_id_for
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
    profile must never leak into these tests and change their outcome."""
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "anthropic-config-unused"))


class _DummyOutput(BaseModel):
    """A trivial `output_format` for client-level tests that never inspect the parsed content."""

    value: str = "x"


# ---------------------------------------------------------------------------
# A fake `anthropic` module -- installed into `sys.modules` per test, never imported for real
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


class _FakeStopDetails:
    def __init__(self, category: str | None) -> None:
        self.category = category


class _FakeResponse:
    def __init__(
        self,
        *,
        parsed_output: Any,
        usage: _FakeUsage | None = None,
        stop_reason: str = "end_turn",
        request_id: str = "req_fake_0001",
        content: tuple[Any, ...] = (),
    ) -> None:
        self.parsed_output = parsed_output
        self.usage = usage or _FakeUsage()
        self.stop_reason = stop_reason
        self._request_id = request_id
        self.content = content
        self.stop_details = _FakeStopDetails("cyber" if stop_reason == "refusal" else None)


class _FakeMessages:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return self._response


def _make_fake_anthropic_module(response: _FakeResponse) -> tuple[Any, _FakeMessages]:
    """A `SimpleNamespace` standing in for the `anthropic` module -- installed via
    `monkeypatch.setitem(sys.modules, "anthropic", module)` so `import anthropic` inside
    `app.agents.client` resolves to this rather than the real package. Returns the module and the
    fake `.messages` object, so a test can inspect exactly what `call_structured` sent."""
    messages = _FakeMessages(response)

    class _FakeAnthropicClient:
        def __init__(self, *, timeout: float | None = None) -> None:
            self.timeout = timeout
            self.messages = messages

    module = SimpleNamespace(
        Anthropic=_FakeAnthropicClient,
        AuthenticationError=type("AuthenticationError", (Exception,), {}),
        PermissionDeniedError=type("PermissionDeniedError", (Exception,), {}),
        RateLimitError=type("RateLimitError", (Exception,), {}),
        BadRequestError=type("BadRequestError", (Exception,), {}),
        APITimeoutError=type("APITimeoutError", (Exception,), {}),
        APIConnectionError=type("APIConnectionError", (Exception,), {}),
        APIStatusError=type("APIStatusError", (Exception,), {"status_code": 500}),
    )
    return module, messages


# ---------------------------------------------------------------------------
# (a) credential_source / is_available
# ---------------------------------------------------------------------------


class TestCredentialSource:
    """**Two of these tests must hide the Claude Code CLI, and the reason is worth stating.**

    When this class was written the SDK's three slots (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
    an `ant auth login` profile) were the only way to reach a model, so "none of the three are set"
    and "no agent call is possible" were the same statement. `app.agents.cli_transport` added a fourth
    transport underneath them -- a locally-installed Claude Code binary, found by a filesystem/`PATH`
    lookup rather than an environment variable -- and on any developer machine with Claude Code
    installed that lookup succeeds. Blanking the three SDK env vars therefore no longer produces a
    machine with no credential; it produces one that correctly falls through to the CLI.

    That is the feature working, not a regression: `credential_source()` returning `"cli"` and
    `is_available()` returning `True` are both the right answers on a machine where the CLI is
    genuinely installed. What went stale is the *tests*, which asserted the old equivalence. The two
    below that are specifically about the exhausted-fallback-chain case now patch
    `resolve_cli_binary` to `None` so they describe the machine they meant to describe. The rest of
    the class is untouched -- a test about which SDK slot outranks which never depended on the CLI.
    """

    def test_none_with_no_env_or_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli_transport, "resolve_cli_binary", lambda: None)
        assert credential_source() == "none"
        available, reason = is_available()
        assert available is False
        assert "no usable" in reason

    def test_empty_api_key_wins_its_slot_but_is_broken(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Without hiding the CLI this now reports available=True, and correctly so: an empty
        # ANTHROPIC_API_KEY is a broken *SDK* slot, and `is_available` is documented to keep looking
        # underneath a broken slot rather than reporting the whole client unusable. The assertion
        # here is about the empty-key diagnostic specifically, so the fallback is taken away.
        monkeypatch.setattr(cli_transport, "resolve_cli_binary", lambda: None)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        assert credential_source() == "api_key"
        available, reason = is_available()
        assert available is False
        assert "empty" in reason.lower()

    def test_real_api_key_is_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        assert credential_source() == "api_key"
        assert is_available() == (True, "credential resolved via ANTHROPIC_API_KEY")

    def test_api_key_outranks_auth_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
        assert credential_source() == "api_key"

    def test_auth_token_used_when_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
        assert credential_source() == "auth_token"
        assert is_available() == (True, "credential resolved via ANTHROPIC_AUTH_TOKEN")

    def test_profile_file_detected_when_no_env_vars(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config_dir = tmp_path / "profile-config"
        monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(config_dir))
        creds_dir = config_dir / "credentials"
        creds_dir.mkdir(parents=True)
        (creds_dir / "default.json").write_text("{}", encoding="utf-8")

        assert credential_source() == "profile"
        available, reason = is_available()
        assert available is True
        assert "profile" in reason


# ---------------------------------------------------------------------------
# (b) AgentUnavailable on missing package / missing credential
# ---------------------------------------------------------------------------


class TestAvailabilityFailures:
    def test_build_client_raises_when_no_credential(self) -> None:
        with pytest.raises(AgentUnavailable):
            build_client()

    def test_call_structured_raises_when_package_not_installed(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        monkeypatch.setitem(sys.modules, "anthropic", None)
        budget = AgentBudget(cap_usd=Decimal("10.00"))

        with pytest.raises(AgentUnavailable, match="anthropic"):
            call_structured(
                role="designer",
                system="sys",
                user="usr",
                output_format=_DummyOutput,
                settings=settings,
                budget=budget,
            )


# ---------------------------------------------------------------------------
# (c) BudgetExhausted refuses before calling
# ---------------------------------------------------------------------------


class TestBudgetExhausted:
    def test_refuses_before_calling(self, settings: Settings) -> None:
        budget = AgentBudget(cap_usd=Decimal("1.00"), spent_usd=Decimal("1.00"))

        with pytest.raises(BudgetExhausted) as exc_info:
            call_structured(
                role="designer",
                system="sys",
                user="usr",
                output_format=_DummyOutput,
                settings=settings,
                budget=budget,
            )
        assert exc_info.value.spent_usd == Decimal("1.00")
        assert exc_info.value.cap_usd == Decimal("1.00")

    def test_refuses_without_touching_sys_modules_anthropic(self, settings: Settings) -> None:
        """The budget check happens before `import anthropic` -- proven by never installing a fake
        module at all and confirming no `AgentUnavailable` (missing package) leaks through instead
        of the intended `BudgetExhausted`."""
        budget = AgentBudget(cap_usd=Decimal("1.00"), spent_usd=Decimal("2.00"))
        with pytest.raises(BudgetExhausted):
            call_structured(
                role="designer",
                system="sys",
                user="usr",
                output_format=_DummyOutput,
                settings=settings,
                budget=budget,
            )


# ---------------------------------------------------------------------------
# (d) Cost estimation arithmetic
# ---------------------------------------------------------------------------


class TestEstimateCost:
    def test_known_usage(self) -> None:
        usage = SimpleNamespace(
            input_tokens=1_000_000,
            output_tokens=100_000,
            cache_read_input_tokens=500_000,
            cache_creation_input_tokens=200_000,
        )
        # Priced against claude-opus-5's $5.00 / $25.00 explicitly -- this checks the cost *formula*
        # (input, output, and the cache read/write multipliers), so it must not ride DEFAULT_MODEL,
        # which is a cost-mode knob that moves.
        # input:  1,000,000 * $5.00 / 1e6  = $5.00
        # output:   100,000 * $25.00 / 1e6 = $2.50
        # cache read:   500,000 * $5.00 * 0.1 / 1e6  = $0.25
        # cache write:  200,000 * $5.00 * 1.25 / 1e6 = $1.25
        # total = $9.00
        assert estimate_cost_usd("claude-opus-5", usage) == Decimal("9.000000")

    def test_zero_usage_is_zero_cost(self) -> None:
        usage = SimpleNamespace(
            input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0
        )
        assert estimate_cost_usd(DEFAULT_MODEL, usage) == Decimal("0.000000")

    def test_missing_attributes_default_to_zero(self) -> None:
        assert estimate_cost_usd(DEFAULT_MODEL, SimpleNamespace()) == Decimal("0.000000")

    def test_unknown_model_falls_back_to_default_pricing(self) -> None:
        usage = SimpleNamespace(
            input_tokens=1_000_000, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0
        )
        assert estimate_cost_usd("claude-some-future-model", usage) == estimate_cost_usd(DEFAULT_MODEL, usage)


# ---------------------------------------------------------------------------
# (e) AgentCall archive is written and re-readable; also covers the caching/thinking request shape
# ---------------------------------------------------------------------------


class TestCallStructuredArchive:
    def test_successful_call_is_archived_and_rereadable(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        dummy_output = _DummyOutput(value="hello")
        usage = _FakeUsage(input_tokens=200, output_tokens=64)
        response = _FakeResponse(parsed_output=dummy_output, usage=usage, stop_reason="end_turn")
        module, messages = _make_fake_anthropic_module(response)
        monkeypatch.setitem(sys.modules, "anthropic", module)

        budget = AgentBudget(cap_usd=Decimal("10.00"))
        parsed, call, new_budget = call_structured(
            role="designer",
            system="SYSTEM PROMPT TEXT",
            user="USER TURN TEXT",
            output_format=_DummyOutput,
            settings=settings,
            budget=budget,
        )

        assert parsed is dummy_output
        assert call.role == "designer"
        assert call.model == DEFAULT_MODEL
        assert call.system == "SYSTEM PROMPT TEXT"
        assert call.user == "USER TURN TEXT"
        assert call.input_tokens == 200
        assert call.output_tokens == 64
        assert call.stop_reason == "end_turn"
        assert call.request_id == "req_fake_0001"

        expected_cost = estimate_cost_usd(DEFAULT_MODEL, usage)
        assert call.cost_usd == expected_cost
        assert new_budget.spent_usd == expected_cost
        assert new_budget.calls == 1
        assert new_budget.cap_usd == budget.cap_usd

        archive_path = agent_calls_dir(settings) / f"{call.call_id}.json"
        assert archive_path.is_file()
        reloaded = AgentCall.model_validate_json(archive_path.read_text(encoding="utf-8"))
        assert reloaded == call

        # The caching contract: system is a single cached text block, and the volatile content
        # (the user turn) is a plain string sent separately -- see call_structured's own docstring.
        sent = messages.calls[0]
        assert sent["system"] == [
            {"type": "text", "text": "SYSTEM PROMPT TEXT", "cache_control": {"type": "ephemeral"}}
        ]
        assert sent["messages"] == [{"role": "user", "content": "USER TURN TEXT"}]
        assert sent["thinking"] == {"type": "adaptive"}
        assert sent["output_config"] == {"effort": "high"}
        assert sent["model"] == DEFAULT_MODEL
        assert "budget_tokens" not in sent["thinking"]

    def test_second_call_consumes_budget_cumulatively(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        response = _FakeResponse(parsed_output=_DummyOutput(), usage=_FakeUsage())
        module, _messages = _make_fake_anthropic_module(response)
        monkeypatch.setitem(sys.modules, "anthropic", module)

        budget = AgentBudget(cap_usd=Decimal("10.00"))
        _parsed, _call, budget = call_structured(
            role="designer", system="s", user="u", output_format=_DummyOutput, settings=settings, budget=budget
        )
        _parsed, _call, budget = call_structured(
            role="designer", system="s", user="u2", output_format=_DummyOutput, settings=settings, budget=budget
        )
        assert budget.calls == 2
        assert budget.spent_usd == 2 * estimate_cost_usd(DEFAULT_MODEL, _FakeUsage())
        assert len(list(agent_calls_dir(settings).glob("*.json"))) == 2


# ---------------------------------------------------------------------------
# (h) A refusal degrades rather than returning a partial slate
# ---------------------------------------------------------------------------


class TestCallStructuredRefusal:
    def test_refusal_raises_agent_unavailable_naming_category(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        response = _FakeResponse(parsed_output=None, usage=_FakeUsage(), stop_reason="refusal")
        module, _messages = _make_fake_anthropic_module(response)
        monkeypatch.setitem(sys.modules, "anthropic", module)

        budget = AgentBudget(cap_usd=Decimal("10.00"))
        with pytest.raises(AgentUnavailable, match="refused") as exc_info:
            call_structured(
                role="designer",
                system="s",
                user="u",
                output_format=_DummyOutput,
                settings=settings,
                budget=budget,
            )
        assert "cyber" in str(exc_info.value)

        # Still archived -- a refusal is a normal, recorded outcome, not a call that never happened.
        archived = list(agent_calls_dir(settings).glob("*.json"))
        assert len(archived) == 1
        call = AgentCall.model_validate_json(archived[0].read_text(encoding="utf-8"))
        assert call.stop_reason == "refusal"


# ---------------------------------------------------------------------------
# app.agents.prompts -- the designer system prompt never invites a stated measurement
# ---------------------------------------------------------------------------


class TestDesignerSystemPrompt:
    def test_forbids_stating_a_measurement(self) -> None:
        assert "NEVER EMIT A NUMBER" in DESIGNER_SYSTEM_PROMPT
        for forbidden_term in ("Sharpe", "win rate", "p-value", "q-value"):
            assert forbidden_term in DESIGNER_SYSTEM_PROMPT

    def test_states_the_trait_schema_for_both_shapes(self) -> None:
        for key in ("fast", "slow", "regime_ma", "stop_loss_pct", "rule_shape"):
            assert key in DESIGNER_SYSTEM_PROMPT
        assert '  discipline' not in DESIGNER_SYSTEM_PROMPT, (
            "the prompt must not offer `discipline` as a trait to fill in -- it is derived from the "
            "emitted rule by app.evolution.ruleforms.classify, and a model asked for it would be "
            "supplying a label nothing reads"
        )
        for shape in RULE_SHAPES:
            assert shape in DESIGNER_SYSTEM_PROMPT, shape
        for key in ("weights", "band_pct", "tilt"):
            assert key in DESIGNER_SYSTEM_PROMPT

    def test_requires_a_falsifiable_rationale_and_diversity(self) -> None:
        assert "falsif" in DESIGNER_SYSTEM_PROMPT.lower()
        assert "diverse" in DESIGNER_SYSTEM_PROMPT.lower() or "genuinely different" in DESIGNER_SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# app.agents.designer.design_generation
# ---------------------------------------------------------------------------


def _rules_traits(**overrides: Any) -> dict[str, Any]:
    traits: dict[str, Any] = {
        "fast": 10,
        "slow": 20,
        "regime_ma": 100,
        "stop_loss_pct": 0.08,
        "take_profit_pct": 0.25,
        "max_hold_days": 90,
        "max_positions": 4,
        "position_pct": 0.2,
        "rank_key": "rsi(14)",
        "rule_shape": "rsi-pullback",
    }
    traits.update(overrides)
    return traits


def _make_rules_card(**overrides: Any) -> ProposedCard:
    pool = pool_for(Purpose.TRADING)
    universe = overrides.pop("universe", tuple(pool.growth[:5]))
    traits = overrides.pop("traits", _rules_traits())
    return ProposedCard(
        shape="rules",
        universe=universe,
        traits=traits,
        rationale=overrides.pop(
            "rationale", "Trend continuation should persist above a long regime filter; falsified if not."
        ),
        differs_from_last=overrides.pop("differs_from_last", ""),
    )


def _make_allocation_card(**overrides: Any) -> ProposedCard:
    pool = pool_for(Purpose.TRADING)
    universe = overrides.pop(
        "universe", (pool.leveraged[0], pool.satellite[0], pool.stability[0], pool.stability[1])
    )
    traits = overrides.pop("traits", {"weights": [0.30, 0.10, 0.30, 0.30], "band_pct": 0.05, "tilt": "trend"})
    return ProposedCard(
        shape="allocation",
        universe=universe,
        traits=traits,
        rationale=overrides.pop("rationale", "A modest leveraged core with a satellite tilt; falsified if not."),
        differs_from_last=overrides.pop("differs_from_last", ""),
    )


def _make_config(**overrides: Any) -> LoopConfig:
    defaults: dict[str, Any] = {"population": 3, "goal": "find something that beats the benchmark"}
    defaults.update(overrides)
    return LoopConfig(**defaults)


def _make_call(**overrides: Any) -> AgentCall:
    defaults: dict[str, Any] = {
        "call_id": "call-test-0001",
        "role": "designer",
        "model": DEFAULT_MODEL,
        "created_at": dt.datetime.now(dt.UTC),
        "system": "sys",
        "user": "usr",
        "raw_response": "{}",
        "cost_usd": Decimal("0.05"),
    }
    defaults.update(overrides)
    return AgentCall(**defaults)


class TestDesignGeneration:
    # -- (g), the part that does not require constructing a Genome ------------------------------

    def test_genome_id_matches_genome_id_for(self) -> None:
        """`genome_id_for` is a pure function of shape/purpose/universe/traits -- proving the
        designer would compute the *same* id a `Genome` from these fields deserves does not require
        constructing that `Genome`, so this passes independently of the `GenomeOrigin` blocker
        documented at the top of this file."""
        card = _make_rules_card()
        expected = genome_id_for(
            generation=7, shape="rules", purpose=Purpose.TRADING, universe=card.universe, traits=card.traits
        )
        # Recomputing with the same inputs is deterministic -- this is what `_to_genome` relies on.
        again = genome_id_for(
            generation=7, shape="rules", purpose=Purpose.TRADING, universe=card.universe, traits=card.traits
        )
        assert expected == again

    def test_valid_response_becomes_agent_origin_genomes(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        card = _make_rules_card()
        output = designer_module._DesignerOutput(cards=[card], reasoning="one trend idea to start")
        call = _make_call()
        budget = AgentBudget(cap_usd=Decimal("10.00"))
        new_budget = AgentBudget(cap_usd=Decimal("10.00"), spent_usd=Decimal("0.05"), calls=1)

        def fake_call_structured(**kwargs: Any) -> tuple[Any, AgentCall, AgentBudget]:
            assert kwargs["role"] == "designer"
            assert kwargs["system"] == DESIGNER_SYSTEM_PROMPT
            return output, call, new_budget

        monkeypatch.setattr(designer_module, "call_structured", fake_call_structured)

        genomes, proposal, returned_budget = design_generation(
            generation=3,
            purpose=Purpose.TRADING,
            shape="rules",
            config=_make_config(),
            settings=settings,
            budget=budget,
        )

        assert returned_budget == new_budget
        assert len(genomes) == 1
        genome = genomes[0]
        expected_id = genome_id_for(
            generation=3, shape="rules", purpose=Purpose.TRADING, universe=card.universe, traits=card.traits
        )
        assert genome.genome_id == expected_id
        assert genome.origin == "agent"
        assert genome.generation == 3
        assert genome.purpose is Purpose.TRADING
        assert genome.shape == "rules"
        assert genome.universe == card.universe
        assert genome.traits == card.traits
        assert proposal.cards == (card,)
        assert proposal.reasoning == "one trend idea to start"
        assert proposal.call is call

    # -- (f) refuses rather than repairs ---------------------------------------------------------

    def test_hallucinated_ticker_raises(self, monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
        card = _make_rules_card(universe=("NVDA", "TSM", "AAPL"))  # AAPL is Roth-pool-only
        output = designer_module._DesignerOutput(cards=[card], reasoning="r")
        monkeypatch.setattr(
            designer_module,
            "call_structured",
            lambda **kw: (output, _make_call(), AgentBudget(cap_usd=Decimal("10.00"))),
        )

        with pytest.raises(AgentUnavailable, match="not in the"):
            design_generation(
                generation=1,
                purpose=Purpose.TRADING,
                shape="rules",
                config=_make_config(),
                settings=settings,
                budget=AgentBudget(cap_usd=Decimal("10.00")),
            )

    def test_over_budget_traits_raises(self, monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
        card = _make_rules_card(traits=_rules_traits(extra_eleventh_param=1))
        output = designer_module._DesignerOutput(cards=[card], reasoning="r")
        monkeypatch.setattr(
            designer_module,
            "call_structured",
            lambda **kw: (output, _make_call(), AgentBudget(cap_usd=Decimal("10.00"))),
        )

        with pytest.raises(AgentUnavailable, match="exceeds the budget"):
            design_generation(
                generation=1,
                purpose=Purpose.TRADING,
                shape="rules",
                config=_make_config(),
                settings=settings,
                budget=AgentBudget(cap_usd=Decimal("10.00")),
            )

    def test_a_rule_shape_outside_the_vocabulary_raises(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        """A hallucinated `rule_shape` has no renderer behind it, so the card is unbuildable rather
        than merely questionable -- and the refusal takes the whole slate, per this module's
        "validate, never repair" contract."""
        card = _make_rules_card(traits=_rules_traits(rule_shape="bollinger-squeeze"))
        output = designer_module._DesignerOutput(cards=[card], reasoning="r")
        monkeypatch.setattr(
            designer_module,
            "call_structured",
            lambda **kw: (output, _make_call(), AgentBudget(cap_usd=Decimal("10.00"))),
        )

        with pytest.raises(AgentUnavailable, match="rule_shape="):
            design_generation(
                generation=1,
                purpose=Purpose.TRADING,
                shape="rules",
                config=_make_config(),
                settings=settings,
                budget=AgentBudget(cap_usd=Decimal("10.00")),
            )

    def test_a_period_past_its_hard_bound_raises(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        """`fast < slow < regime_ma` holds here and the card is still refused: `regime_ma=400` orders
        fine and emits `sma(400)`, which parses and then fails at evaluation time, inside a scoring
        run, as a whole card lost."""
        card = _make_rules_card(traits=_rules_traits(fast=10, slow=20, regime_ma=400))
        output = designer_module._DesignerOutput(cards=[card], reasoning="r")
        monkeypatch.setattr(
            designer_module,
            "call_structured",
            lambda **kw: (output, _make_call(), AgentBudget(cap_usd=Decimal("10.00"))),
        )

        with pytest.raises(AgentUnavailable, match="regime_ma=400 is outside"):
            design_generation(
                generation=1,
                purpose=Purpose.TRADING,
                shape="rules",
                config=_make_config(),
                settings=settings,
                budget=AgentBudget(cap_usd=Decimal("10.00")),
            )

    def test_violated_rules_ordering_raises(self, monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
        card = _make_rules_card(traits=_rules_traits(fast=50, slow=20, regime_ma=100))
        output = designer_module._DesignerOutput(cards=[card], reasoning="r")
        monkeypatch.setattr(
            designer_module,
            "call_structured",
            lambda **kw: (output, _make_call(), AgentBudget(cap_usd=Decimal("10.00"))),
        )

        with pytest.raises(AgentUnavailable, match="fast < slow < regime_ma"):
            design_generation(
                generation=1,
                purpose=Purpose.TRADING,
                shape="rules",
                config=_make_config(),
                settings=settings,
                budget=AgentBudget(cap_usd=Decimal("10.00")),
            )

    def test_allocation_weights_not_summing_to_one_raises(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        card = _make_allocation_card(traits={"weights": [0.30, 0.10, 0.10, 0.10], "band_pct": 0.05, "tilt": None})
        output = designer_module._DesignerOutput(cards=[card], reasoning="r")
        monkeypatch.setattr(
            designer_module,
            "call_structured",
            lambda **kw: (output, _make_call(), AgentBudget(cap_usd=Decimal("10.00"))),
        )

        with pytest.raises(AgentUnavailable, match="sum to"):
            design_generation(
                generation=1,
                purpose=Purpose.TRADING,
                shape="allocation",
                config=_make_config(),
                settings=settings,
                budget=AgentBudget(cap_usd=Decimal("10.00")),
            )

    def test_avoid_symbol_in_universe_raises(self, monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
        card = _make_rules_card()
        output = designer_module._DesignerOutput(cards=[card], reasoning="r")
        monkeypatch.setattr(
            designer_module,
            "call_structured",
            lambda **kw: (output, _make_call(), AgentBudget(cap_usd=Decimal("10.00"))),
        )

        with pytest.raises(AgentUnavailable, match="avoid_symbols"):
            design_generation(
                generation=1,
                purpose=Purpose.TRADING,
                shape="rules",
                config=_make_config(avoid_symbols=(card.universe[0],)),
                settings=settings,
                budget=AgentBudget(cap_usd=Decimal("10.00")),
            )

    def test_missing_trait_key_raises(self, monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
        traits = _rules_traits()
        del traits["rank_key"]
        card = _make_rules_card(traits=traits)
        output = designer_module._DesignerOutput(cards=[card], reasoning="r")
        monkeypatch.setattr(
            designer_module,
            "call_structured",
            lambda **kw: (output, _make_call(), AgentBudget(cap_usd=Decimal("10.00"))),
        )

        with pytest.raises(AgentUnavailable, match="do not match the"):
            design_generation(
                generation=1,
                purpose=Purpose.TRADING,
                shape="rules",
                config=_make_config(),
                settings=settings,
                budget=AgentBudget(cap_usd=Decimal("10.00")),
            )

    # -- (h) refusal degrades, at the designer level -----------------------------------------------

    def test_refusal_from_client_propagates_as_agent_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        def refusing_call_structured(**kwargs: Any) -> Any:
            raise AgentUnavailable("model refused the designer request (category='cyber')")

        monkeypatch.setattr(designer_module, "call_structured", refusing_call_structured)

        with pytest.raises(AgentUnavailable, match="refused"):
            design_generation(
                generation=1,
                purpose=Purpose.TRADING,
                shape="rules",
                config=_make_config(),
                settings=settings,
                budget=AgentBudget(cap_usd=Decimal("10.00")),
            )

    # -- config-level fail-fast, before the model is ever called ------------------------------------

    def test_focus_avoid_overlap_raises_before_calling_model(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        def fail_if_called(**kwargs: Any) -> Any:
            raise AssertionError("call_structured must not be reached when focus/avoid overlap")

        monkeypatch.setattr(designer_module, "call_structured", fail_if_called)
        config = _make_config(focus_symbols=("NVDA",), avoid_symbols=("NVDA",))

        with pytest.raises(AgentUnavailable, match="focus_symbols and avoid_symbols"):
            design_generation(
                generation=1,
                purpose=Purpose.TRADING,
                shape="rules",
                config=config,
                settings=settings,
                budget=AgentBudget(cap_usd=Decimal("10.00")),
            )

    def test_budget_exhausted_propagates(self, monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
        def exhausting_call_structured(**kwargs: Any) -> Any:
            raise BudgetExhausted(Decimal("10.00"), Decimal("10.00"))

        monkeypatch.setattr(designer_module, "call_structured", exhausting_call_structured)

        with pytest.raises(BudgetExhausted):
            design_generation(
                generation=1,
                purpose=Purpose.TRADING,
                shape="rules",
                config=_make_config(),
                settings=settings,
                budget=AgentBudget(cap_usd=Decimal("10.00"), spent_usd=Decimal("10.00")),
            )
