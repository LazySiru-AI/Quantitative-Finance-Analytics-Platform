"""The agent layer's shared vocabulary.

`app.evolution` searches by mutation: it proposes candidates by perturbing numbers under a seeded RNG,
which is reproducible and completely incurious. This package is the other kind of proposer -- one that
can read the previous generation's findings, the owner's stated goal, and the ticker pool, and design
the next slate on purpose.

**Where a model is allowed to sit, and where it is not.** `strategy-program/AGENTS-INTEGRATION-PLAN.md`
Phase F is explicit: of the competition protocol's seven phases, only phase 1 (an analyst proposing a
card) and phase 6 (a post-mortem written after the fact) may involve a model. Phases 3-5 -- eligibility,
running, scoring -- stay deterministic and serial, "the protocol's value is reproducibility, and a model
in the scoring path destroys it". Everything in this package is phase 1. No module here reads a run
file, computes a metric, or ranks anything; the numbers still come from `app.tournament.results` over
files the existing engine wrote.

**The rule about numbers, and the one distinction that makes this package legal under it.** §0 of that
same plan says an agent "may propose, name, argue and select" but "may never emit a number". A card
carries numbers -- `fast=12`, `stop_loss_pct=0.08`, a sleeve weight. Those are *hypotheses*, in exactly
the sense the seeded RNG's numbers already are: a claim about what is worth testing, which the backtest
then judges. What §0 forbids is a model emitting a *measurement* -- a return, a Sharpe, a q-value, a
count of anything. No type in this package can carry one, which is why :class:`AgentProposal` holds
genome traits and prose and nothing else.

**Reproducibility is lost here, and is replaced rather than papered over.** A seeded generation can be
replayed exactly. An agent-designed one cannot: the model is not a pure function of its prompt. So every
call is archived in full -- prompt, model, response, token usage, request id, cost -- under
`data/loop/agent_calls/`, and the resulting genome records `origin="agent"`. A generation is therefore
*auditable* even though it is not *replayable*, which is the same trade `LoopConfig.use_news` already
makes and is documented under the same terms in `strategy-program/EVOLUTION-LOOP.md`.

**Spend is bounded by construction.** The loop is infinite. A model call per generation with no ceiling
is an open-ended bill, so :class:`AgentBudget` is a hard cap: when it is exhausted the loop does not
stall or error, it falls back to the deterministic proposer and says so in its log. Failure of any kind
-- no credentials, a refusal, a rate limit, a malformed response -- degrades the same way. The agent is
an improvement to the search, never a dependency of it.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings

__all__ = [
    "DEFAULT_MODEL",
    "AgentBudget",
    "AgentCall",
    "AgentDisabled",
    "AgentProposal",
    "AgentResponseInvalid",
    "AgentRole",
    "AgentTransientError",
    "AgentUnavailable",
    "BudgetExhausted",
    "CredentialSource",
    "ProposedCard",
    "ScoutPick",
    "ScoutReport",
    "agent_calls_dir",
]

AgentRole = Literal[
    # The evolution loop's three. Phase 1 design, phase 1 ticker bias, phase 6 post-mortem.
    "designer",
    "scout",
    "reviewer",
    # `app.tradingagents` -- one role per stage of the pipeline. The four analysts write reports from
    # a pre-fetched evidence pack; the two researchers argue; the manager, trader and portfolio
    # manager judge; the three risk debators stress the trader's proposal; the reflector writes a
    # lesson after an outcome is known.
    "market_analyst",
    "sentiment_analyst",
    "news_analyst",
    "fundamentals_analyst",
    "bull_researcher",
    "bear_researcher",
    "research_manager",
    "trader",
    "risk_aggressive",
    "risk_conservative",
    "risk_neutral",
    "portfolio_manager",
    "reflector",
    # `app.vibedesk` -- every preset worker archives under one role. Which *seat* it was
    # (`bull_advocate`, `risk_officer`, ...) is preset data, not a code-level enum, so it is recorded
    # on the run's own task record rather than here; widening this `Literal` per preset would make
    # adding a YAML file a Python edit, which is exactly what presets exist to avoid.
    "swarm_worker",
    # `app.i18n` -- the one role behind `POST /api/i18n/translate`'s model calls, translating
    # narrative prose to Korean. Phase 4 of the i18n rollout.
    "translator",
]
"""Which agent made a call, as a closed set.

Closed rather than a free string so an archived `AgentCall` can be grouped and audited by role --
which means adding an agent is an edit *here*, and forgetting it fails loudly at construction time
rather than filing the call under a role nobody defined. `app.agents.client.call_structured`'s own
`role` parameter is annotated with this same alias; they are two halves of one contract and cannot
drift apart.
"""

#: The model every agent in this package uses unless a caller overrides it.
#:
#: Temporarily Haiku, an owner-directed cost-mode default (2026-08-31): the package-wide default that
#: the workflow desk and the evolution designer/scout/reviewer fall back to when no model is set on the
#: call. The design job argues for a stronger tier -- reading a pool, findings and a goal to produce a
#: slate *different* from the last is design under constraint, and a generation costs minutes of
#: backtesting either way, so the model call is not the loop's expensive part -- so restore
#: "claude-opus-5" here (or set `EvolutionConfig.agent_model`) when the cost mode ends.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

CredentialSource = Literal["api_key", "auth_token", "profile", "cli", "none"]
"""Which credential -- or, since `app.agents.cli_transport` landed, which *transport* -- resolved,
reported by `app.agents.client.credential_source`.

The SDK's own resolution order is `ANTHROPIC_API_KEY`, then `ANTHROPIC_AUTH_TOKEN`, then an
`ant auth login` profile on disk; all three are checked first because that path is lower-latency (no
subprocess spawn). `"cli"` is a fourth, later-checked source: a locally-installed Claude Code CLI
binary, resolved by `app.agents.cli_transport.resolve_cli_binary`, which rides that program's own login
rather than any of the three `anthropic`-SDK credential slots -- it exists for exactly the machine
`app.agents.cli_transport`'s own module docstring describes, where none of the first three is set but
Claude Code is installed and logged in. `"none"` means no usable credential or transport was found and
every agent in this package will decline rather than call, which the loop treats as "use the
deterministic proposer".

Worth knowing when this looks wrong: a set `ANTHROPIC_API_KEY` silently shadows a logged-in profile,
including an *empty* one, which still wins its slot and then authenticates with an empty key. This
function still reports `"api_key"` for that broken case rather than falling through to `"cli"` --
`credential_source` answers "which slot has presence," not "which is usable," the same separation its
own docstring already draws for the first three sources; `app.agents.client.is_available` is the one
that actually falls through to a working CLI when the SDK slot that won this reporting is broken.
"""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Failure modes -- all of them degrade, none of them stop the loop
# ---------------------------------------------------------------------------


class AgentUnavailable(RuntimeError):
    """No usable credential, or the `anthropic` package is not importable.

    Raised at the point of use rather than at import, so the whole application still starts, the
    Competition page still renders, and the loop still runs on its deterministic proposer. Carries the
    reason so `GET /api/agents/health` can say *which* of the several possible causes it is instead of
    reporting a bare "disabled".
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AgentResponseInvalid(AgentUnavailable):
    """A response *was* received from the model but could not be parsed or validated into the
    requested schema -- malformed JSON, trailing prose after the object, or a missing/invalid field.

    A subclass of :class:`AgentUnavailable` so every existing ``except AgentUnavailable`` still
    catches it and the loop still degrades to its deterministic proposer if nothing handles it. The
    distinction matters to a caller that *can* do better than give up: unlike a missing credential or
    a dead transport, a malformed response is a transient formatting lapse the same model will usually
    get right when simply asked again, so `app.agentdesk.grounding.run_grounded` retries it within its
    attempt budget instead of failing the whole pipeline on one bad turn. Reraised unchanged only when
    every attempt was malformed -- there is then no value to return.
    """


class AgentTransientError(AgentUnavailable):
    """The transport reached the model but the call failed in a way a retry may fix -- the Claude Code
    CLI exited non-zero carrying an error envelope, or reported `is_error=true` (a model/API-level
    error), rather than a formatting problem in an otherwise-received response.

    A subclass of :class:`AgentUnavailable` for the same reason as :class:`AgentResponseInvalid`:
    every existing ``except AgentUnavailable`` still catches it, so a caller that cannot retry still
    degrades to its deterministic path. Distinct from a *malformed* response (that is
    `AgentResponseInvalid`) because there is no response to correct -- the right retry re-asks the
    same turn unchanged. Distinct from a bare :class:`AgentUnavailable` (missing binary, no
    credential, an outright refusal) because those are systemic: re-asking a dead transport or a
    refused prompt only wastes time, so those stay the base class and are not retried.
    `app.agentdesk.grounding.run_grounded` retries this within its attempt budget; on the last attempt
    it is reraised unchanged, failing the stage exactly as before this class existed.
    """


class AgentDisabled(RuntimeError):
    """The caller turned the agent off (`LoopConfig.use_agent=False`). Not an error condition."""


class BudgetExhausted(RuntimeError):
    """The run's spend ceiling is reached. Carries what was spent and what the cap was."""

    def __init__(self, spent_usd: Decimal, cap_usd: Decimal) -> None:
        super().__init__(f"agent budget exhausted: ${spent_usd} spent against a ${cap_usd} cap")
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd


# ---------------------------------------------------------------------------
# What an agent produced
# ---------------------------------------------------------------------------


class ProposedCard(_Frozen):
    """One candidate an agent designed, in the shape `app.evolution.genome` speaks.

    Deliberately *not* a `StrategyCard` or an `AllocationCard`. Those are validated, engine-ready
    objects, and letting a model construct one directly would mean a model choosing an `agent_id`, a
    `designed_through`, and a `purpose` -- three fields whose correctness is structural rather than a
    matter of judgement. The agent fills in only the parts that are genuinely a design decision;
    `app.agents.designer` turns this into a real `Genome` through the same
    `app.evolution.models.genome_id_for` every RNG-drawn candidate goes through, so an agent-designed
    card and a mutated one are indistinguishable to everything downstream.
    """

    shape: Literal["rules", "allocation"]

    universe: tuple[str, ...] = Field(min_length=1, max_length=12)
    """Tickers, which must all come from the lane's own pool -- the designer re-checks rather than
    trusting, because a hallucinated ticker would fail far downstream with a confusing error."""

    traits: dict[str, Any]
    """The free parameters, in `Genome.traits` layout. Capped at ten by `Genome`'s own validator; the
    prompt states the budget and the designer refuses an over-budget proposal rather than trimming it,
    since which knob to drop is a design decision the model just made badly."""

    rationale: str
    """Why this candidate, in the model's own words -- what it is testing and what would falsify it.

    This is the thing the deterministic proposer structurally cannot produce, and the reason to have an
    agent at all. It becomes the card's `thesis`, and `strategy-program/PROTOCOL.md` is explicit that a
    rationale written *before* the run is what distinguishes a hypothesis from a curve fit."""

    differs_from_last: str = ""
    """What this slate changes relative to the previous generation, and why. Empty on a first
    generation. Recorded so a reader can see whether the agent is actually exploring or restating."""


class AgentProposal(_Frozen):
    """A full generation's worth of designed candidates, plus the call that produced them."""

    cards: tuple[ProposedCard, ...] = Field(min_length=1)
    reasoning: str = ""
    """The agent's account of the slate as a whole -- how the candidates relate to each other and to
    the stated goal. Never a claim about how any of them will do."""
    call: AgentCall


class ScoutPick(_Frozen):
    """One ticker the idea scout thinks is worth testing, and why.

    `why` is prose about *coverage and narrative*, never a forecast. The scout reads
    `app.market.news`, whose own contract is that a provider "may only report what it counted, never
    what it concluded" -- a scout that emitted a score would break that one layer up.
    """

    symbol: str
    why: str


class ScoutReport(_Frozen):
    """The idea scout's output: which of the lane's pool tickers to bias this generation toward."""

    picks: tuple[ScoutPick, ...] = ()
    theme: str = ""
    """One line on what the picks have in common, if anything. Empty when they do not."""
    call: AgentCall


# ---------------------------------------------------------------------------
# The audit record
# ---------------------------------------------------------------------------


class AgentCall(_Frozen):
    """One model call, recorded in full so an agent-designed generation can be audited later.

    This is what replaces replayability. A seeded generation can be re-run to the same bytes; this one
    cannot, so instead every input and output is kept and the genome points at it. `data/loop/` is
    gitignored apart from the ledger and promotion records, so these accumulate locally and are not
    committed -- they are working evidence, not part of the programme's record.
    """

    call_id: str
    role: AgentRole
    """Which agent made the call -- see :data:`AgentRole` for why the set is closed."""

    model: str
    created_at: dt.datetime

    system: str
    """The system prompt, verbatim. Kept because a prompt change is the most likely explanation for a
    behaviour change, and reconstructing it from a later version of the code would silently reconstruct
    the *wrong* one."""

    user: str
    """The user turn, verbatim -- the findings, pool and goal the model actually saw."""

    raw_response: str
    """The model's response as text. For a structured call this is the JSON it returned."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    cost_usd: Decimal = Decimal(0)
    """Estimated, from this package's own price table -- an accounting aid for the budget cap, not a
    billing figure. The authoritative number is on the Anthropic console."""

    request_id: str | None = None
    """The API's `request-id`, for reporting a failure upstream."""

    stop_reason: str | None = None
    """Checked before the response is read: a `"refusal"` is a normal outcome to degrade on, not an
    exception, and it arrives with HTTP 200."""


class AgentBudget(_Frozen):
    """The spend ceiling for one loop run, and what has been spent against it.

    Immutable; `app.agents.client` returns a new one per call rather than mutating, so a budget can be
    snapshotted into `LoopStatus` without the copy drifting from the live figure.
    """

    cap_usd: Decimal
    spent_usd: Decimal = Decimal(0)
    calls: int = 0

    @property
    def exhausted(self) -> bool:
        return self.spent_usd >= self.cap_usd

    @property
    def remaining_usd(self) -> Decimal:
        return max(Decimal(0), self.cap_usd - self.spent_usd)


def agent_calls_dir(settings: Settings) -> Path:
    """`data/loop/agent_calls/` -- where :class:`AgentCall` records are archived, one JSON per call."""
    return settings.data_dir / "loop" / "agent_calls"
