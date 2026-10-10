"""Findings + pool + goal -> a generation of candidate genomes.

`design_generation` is the one function this module exports. It plays the same role for the agent
path that `app.evolution.proposer.propose_generation` plays for the seeded path: given everything the
loop knows about a lane so far, produce a slate of `Genome`s for that lane's next generation. The two
are meant to be interchangeable from the caller's side -- same lane, same `LoopConfig`, a tuple of
`Genome`s back -- and everything past this module (card construction, disjointness checking, writing
to disk) is `app.evolution.proposer`'s job either way.

**Validate, never repair.** Every `ProposedCard` the model returns is checked against the same rules
`app.evolution.genome`'s operators satisfy by construction (the trait schema, the ten-parameter
budget, `fast < slow < regime_ma` inside `RULES_PERIOD_BOUNDS`, a `rule_shape` `app.evolution.ruleforms`
can render, allocation weights summing to one, every ticker in the lane's own pool). A card that fails any
of them raises `app.agents.models.AgentUnavailable` for the *whole* call
-- there is no per-card salvage. Clamping a stray weight or dropping a hallucinated ticker would leave
a card whose `rationale` describes something other than what actually got tested, which is exactly the
failure `app.evolution.models.ProposalRejected`'s own docstring names for the deterministic path; this
module holds the same line for the agent path, just under a different exception, because this
package's own contract is "degrade to the deterministic proposer," never "repair and continue."

**Numbers flow in, never get reworded.** `findings` and `standings` are already-computed
`app.evolution.models.Finding`/`Standing` records from `app.evolution.feedback` and the leaderboard;
this module passes their own fields straight into the user turn and never recomputes or paraphrases a
number from them -- the same discipline `app.report.narrative` enforces on every other number this
application ever shows a reader.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field

from app.agents.client import call_structured
from app.agents.models import (
    DEFAULT_MODEL,
    AgentBudget,
    AgentProposal,
    AgentUnavailable,
    ProposedCard,
)
from app.agents.prompts import DESIGNER_SYSTEM_PROMPT
from app.config import Settings
from app.evolution.models import (
    MAX_FREE_PARAMETERS,
    RULE_SHAPES,
    RULES_PERIOD_BOUNDS,
    CardShape,
    Finding,
    Genome,
    LoopConfig,
    Standing,
    genome_id_for,
)
from app.evolution.universe import Pool, pool_for
from app.tournament.purposes import Purpose

__all__ = ["design_generation"]

#: Restated from `Genome.universe`'s own `Field(max_length=12)` rather than imported, the same choice
#: `app.evolution.proposer._MAX_UNIVERSE_SIZE` makes for the identical reason: a config-level fact
#: (the focus list alone is already too long) should fail before a single card is drawn, and that
#: check needs the literal, not a reach into another module's private constant.
_MAX_UNIVERSE_SIZE = 12

_CENT = Decimal("0.01")

_RULES_TRAIT_KEYS = frozenset(
    {
        "fast",
        "slow",
        "regime_ma",
        "stop_loss_pct",
        "take_profit_pct",
        "max_hold_days",
        "max_positions",
        "position_pct",
        "rank_key",
        "rule_shape",
    }
)
_ALLOCATION_TRAIT_KEYS = frozenset({"weights", "band_pct", "tilt"})

#: How much of a card's rationale survives into `Genome.notes`. Long enough to keep the falsification
#: clause most rationales end on, short enough that a leaderboard row or a log line showing `notes`
#: does not turn into a paragraph -- the same "one line on what this candidate is for" job
#: `Genome.notes`'s own docstring describes for a mutated or random genome's shorter note.
_NOTES_LIMIT = 480


class _DesignerOutput(BaseModel):
    """The shape `call_structured` parses a designer call's response into.

    Not `AgentProposal` itself -- `AgentProposal.call` is the `AgentCall` record `call_structured`
    builds internally and hands back separately, so the model is never asked to produce it (and
    could not: it has no `call_id` or token usage to report on itself).
    """

    model_config = ConfigDict(extra="forbid")

    cards: list[ProposedCard] = Field(min_length=1)
    reasoning: str = ""


# ---------------------------------------------------------------------------
# User-turn assembly -- every number here is either a config value the caller already set, or copied
# verbatim off a Finding/Standing this package did not compute.
# ---------------------------------------------------------------------------


def _format_pool(pool: Pool) -> str:
    lines = [f"Ticker pool for purpose {pool.purpose.value!r} (every card's universe must draw only "
             "from these, across any sleeve):"]
    for sleeve_name in ("growth", "leveraged", "satellite", "stability"):
        symbols = getattr(pool, sleeve_name)
        lines.append(f"  {sleeve_name}: {', '.join(symbols) if symbols else '(none)'}")
    return "\n".join(lines)


def _format_findings(findings: Sequence[Finding]) -> str:
    if not findings:
        return "(no findings recorded yet -- this is an early generation)"
    lines = ["Findings from the previous generation, stated exactly as computed:"]
    for finding in findings:
        evidence = json.dumps(finding.evidence, sort_keys=True, default=str) if finding.evidence else ""
        suffix = f" [evidence: {evidence}]" if evidence else ""
        lines.append(f"  - ({finding.kind}) {finding.summary}{suffix}")
    return "\n".join(lines)


def _format_standings(standings: Sequence[Standing]) -> str:
    if not standings:
        return "(no standings recorded yet -- this is an early generation)"
    lines = ["Previous generation's leaderboard, stated exactly as computed (never restate these "
             "numbers as your own claim -- they describe what already ran, not what you are proposing):"]
    for standing in standings:
        lines.append(
            f"  - rank {standing.rank} {standing.display_name!r} (genome {standing.genome_id}): "
            f"eligible={standing.eligible}, windows_run={standing.windows_run}, "
            f"median_excess={standing.median_excess}, worst_excess={standing.worst_excess}, "
            f"hit_rate={standing.hit_rate}, total_trades={standing.total_trades}, "
            f"holdout_median_excess={standing.holdout_median_excess}, q_value={standing.q_value}"
        )
    return "\n".join(lines)


def _format_previous_cards(previous_cards: Sequence[Genome]) -> str:
    if not previous_cards:
        return "(no previous slate -- this is the first generation for this lane)"
    lines = ["Previous generation's slate, for context on what has already been tried -- do not "
             "propose near-duplicates of these:"]
    for genome in previous_cards:
        short_id = genome.genome_id.split("-", 1)[0]
        note = genome.notes[:200]
        lines.append(f"  - {short_id} ({genome.origin}): universe={list(genome.universe)}; {note}")
    return "\n".join(lines)


def _build_user_turn(
    *,
    generation: int,
    purpose: Purpose,
    shape: CardShape,
    pool: Pool,
    config: LoopConfig,
    findings: Sequence[Finding],
    standings: Sequence[Standing],
    previous_cards: Sequence[Genome],
    focus: frozenset[str],
    avoid: frozenset[str],
) -> str:
    sections = [
        f"Generation: {generation}",
        f"Purpose (book): {purpose.value}",
        f"Card shape to design: {shape!r}",
        f"How many candidates to propose: {config.population}",
        f"Owner's stated goal (their own words -- context only, never a source of numbers): "
        f"{config.goal or '(none given)'}",
        f"Focus tickers (must appear in every card's universe): "
        f"{', '.join(sorted(focus)) if focus else '(none)'}",
        f"Avoid tickers (must not appear in any card's universe): "
        f"{', '.join(sorted(avoid)) if avoid else '(none)'}",
        _format_pool(pool),
        _format_findings(findings),
        _format_standings(standings),
        _format_previous_cards(previous_cards),
    ]
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Validation -- raises AgentUnavailable on any violation, for the whole call at once
# ---------------------------------------------------------------------------


def _validate_focus_avoid(*, purpose: Purpose, pool: Pool, focus: frozenset[str], avoid: frozenset[str]) -> None:
    overlap = focus & avoid
    if overlap:
        raise AgentUnavailable(
            f"focus_symbols and avoid_symbols both name {sorted(overlap)} for purpose "
            f"{purpose.value!r} -- a symbol asked for and forbidden at once cannot be resolved"
        )
    if len(focus) > _MAX_UNIVERSE_SIZE:
        raise AgentUnavailable(
            f"{len(focus)} focus_symbols exceeds the {_MAX_UNIVERSE_SIZE}-symbol universe cap "
            "outright -- there is no universe this could ever produce"
        )
    pool_symbols = set(pool.all_symbols())
    missing = focus - pool_symbols
    if missing:
        raise AgentUnavailable(
            f"focus_symbols {sorted(missing)} are not in the {purpose.value!r} lane's pool"
        )


def _validate_card(
    card: ProposedCard,
    *,
    index: int,
    pool: Pool,
    shape: CardShape,
    focus: frozenset[str],
    avoid: frozenset[str],
) -> None:
    """Raise `AgentUnavailable` naming exactly what is wrong with `card`, or return silently.

    Called once per card, before any `Genome` is built for any of them -- see this module's own
    docstring on why a single bad card refuses the whole slate rather than being dropped or repaired.
    """
    where = f"designer card #{index}"

    if card.shape != shape:
        raise AgentUnavailable(
            f"{where}: proposed shape {card.shape!r} does not match the requested shape {shape!r}"
        )

    universe = card.universe
    universe_set = set(universe)
    if len(universe_set) != len(universe):
        raise AgentUnavailable(f"{where}: universe repeats a symbol: {list(universe)}")

    pool_symbols = set(pool.all_symbols())
    hallucinated = universe_set - pool_symbols
    if hallucinated:
        raise AgentUnavailable(
            f"{where}: universe names ticker(s) {sorted(hallucinated)} that are not in the "
            f"{pool.purpose.value!r} lane's pool -- every ticker must come from the supplied pool"
        )

    avoided = universe_set & avoid
    if avoided:
        raise AgentUnavailable(f"{where}: universe names avoid_symbols {sorted(avoided)}")

    missing_focus = focus - universe_set
    if missing_focus:
        raise AgentUnavailable(f"{where}: universe is missing focus_symbols {sorted(missing_focus)}")

    if len(card.traits) > MAX_FREE_PARAMETERS:
        raise AgentUnavailable(
            f"{where}: {len(card.traits)} free parameters exceeds the budget of "
            f"{MAX_FREE_PARAMETERS}: {sorted(card.traits)}"
        )

    expected_keys = _RULES_TRAIT_KEYS if shape == "rules" else _ALLOCATION_TRAIT_KEYS
    got_keys = set(card.traits)
    if got_keys != expected_keys:
        missing_keys = expected_keys - got_keys
        extra_keys = got_keys - expected_keys
        detail = []
        if missing_keys:
            detail.append(f"missing {sorted(missing_keys)}")
        if extra_keys:
            detail.append(f"unexpected {sorted(extra_keys)}")
        raise AgentUnavailable(f"{where}: traits do not match the {shape!r} schema ({'; '.join(detail)})")

    if shape == "rules":
        _validate_rules_ordering(card, where=where)
        _validate_rule_shape(card, where=where)
    else:
        _validate_allocation_weights(card, where=where)


def _validate_rules_ordering(card: ProposedCard, *, where: str) -> None:
    try:
        fast = int(card.traits["fast"])
        slow = int(card.traits["slow"])
        regime_ma = int(card.traits["regime_ma"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AgentUnavailable(f"{where}: malformed 'rules' traits: {exc}") from exc
    if not (fast < slow < regime_ma):
        raise AgentUnavailable(
            f"{where}: fast={fast}, slow={slow}, regime_ma={regime_ma} does not satisfy "
            "fast < slow < regime_ma"
        )
    for key, value in (("fast", fast), ("slow", slow), ("regime_ma", regime_ma)):
        low, high = RULES_PERIOD_BOUNDS[key]
        if not (low <= value <= high):
            raise AgentUnavailable(
                f"{where}: {key}={value} is outside the {low}-{high} band every rule shape renders "
                "within -- a period past it emits an indicator call the engine refuses at evaluation "
                "time, which costs a whole card mid-run rather than failing here"
            )


def _validate_rule_shape(card: ProposedCard, *, where: str) -> None:
    """`rule_shape` must name a form `app.evolution.ruleforms` can actually render.

    The one trait whose wrong value is not merely a bad card but an unbuildable one: it selects the
    entry/exit text `app.evolution.proposer._rules_card` emits, so a hallucinated shape name ("bollinger",
    "swing-trade") has no rule behind it at all. Refusing the whole slate here, rather than letting
    `card_for` reject that one candidate later, is the same "validate, never repair" line this module's
    own docstring draws -- and it names the vocabulary in the error, since a model that guessed the name
    can use the list.
    """
    shape = card.traits.get("rule_shape")
    if shape not in RULE_SHAPES:
        raise AgentUnavailable(
            f"{where}: rule_shape={shape!r} is not one of {list(RULE_SHAPES)}"
        )


def _validate_allocation_weights(card: ProposedCard, *, where: str) -> None:
    weights = card.traits.get("weights")
    if not isinstance(weights, list) or len(weights) != len(card.universe):
        got = len(weights) if isinstance(weights, list) else type(weights).__name__
        raise AgentUnavailable(
            f"{where}: traits['weights'] has {got} entries, universe has {len(card.universe)} -- "
            "weights must be positional against universe"
        )
    try:
        cents = [Decimal(str(weight)).quantize(_CENT, rounding=ROUND_HALF_UP) for weight in weights]
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AgentUnavailable(f"{where}: malformed 'allocation' weights: {exc}") from exc
    total = sum(cents, Decimal(0))
    if total != Decimal("1.00"):
        raise AgentUnavailable(f"{where}: allocation weights sum to {total}, not 1")


# ---------------------------------------------------------------------------
# ProposedCard -> Genome
# ---------------------------------------------------------------------------


def _pseudo_seed(genome_id: str) -> int:
    """A deterministic, content-derived stand-in for `Genome.seed`.

    An agent-designed genome was never drawn from an RNG stream -- there is no `random.Random` call
    behind it to record the state of -- but `Genome.seed` is a required, non-negative int field
    (`Field(ge=0)`). Deriving it from `genome_id`'s own content, rather than from `os.urandom` or a
    constant, keeps the field meaningful in the one sense it still can be for this origin: the same
    proposed card always gets the same `seed`, so nothing downstream that happens to read this field
    sees it change across an otherwise-identical re-run.
    """
    digest = hashlib.sha256(genome_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def _format_notes(card: ProposedCard) -> str:
    text = card.rationale
    if card.differs_from_last:
        text = f"{text} Differs from last: {card.differs_from_last}"
    text = f"agent: {text}"
    if len(text) > _NOTES_LIMIT:
        text = text[: _NOTES_LIMIT - 1].rstrip() + "…"
    return text


def _to_genome(card: ProposedCard, *, generation: int, purpose: Purpose, shape: CardShape) -> Genome:
    genome_id = genome_id_for(
        generation=generation, shape=shape, purpose=purpose, universe=card.universe, traits=card.traits
    )
    return Genome(
        genome_id=genome_id,
        generation=generation,
        parents=(),
        origin="agent",
        shape=shape,
        purpose=purpose,
        universe=card.universe,
        traits=card.traits,
        seed=_pseudo_seed(genome_id),
        notes=_format_notes(card),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def design_generation(
    *,
    generation: int,
    purpose: Purpose,
    shape: CardShape,
    config: LoopConfig,
    settings: Settings,
    budget: AgentBudget,
    findings: Sequence[Finding] = (),
    standings: Sequence[Standing] = (),
    previous_cards: Sequence[Genome] = (),
    focus_symbols: Sequence[str] = (),
    avoid_symbols: Sequence[str] = (),
) -> tuple[tuple[Genome, ...], AgentProposal, AgentBudget]:
    """One generation's worth of agent-designed genomes for one lane, plus the proposal that produced
    them and the budget after paying for the call.

    `focus_symbols`/`avoid_symbols` here are unioned with `config.focus_symbols`/`config.avoid_symbols`
    rather than replacing them -- a caller (the loop, or a scout's picks once `app.agents.scout`
    lands) may want to add this generation's own constraints on top of the run-wide ones `LoopConfig`
    already carries, and this function has no way to tell "the caller forgot to pass config's list
    again" apart from "the caller deliberately wants a narrower set," so it never drops either source.

    Raises `app.agents.models.AgentUnavailable` or `BudgetExhausted` on any failure -- missing
    credentials, an exhausted budget, a refusal, or a model response that fails validation. This
    function never falls back to the deterministic proposer itself; that is the caller's job, exactly
    as `app.evolution.models.LoopConfig.use_agent`'s own docstring describes, and every exception this
    function can raise is one the caller is already expected to catch for that fallback.
    """
    pool = pool_for(purpose)
    focus = frozenset((*config.focus_symbols, *focus_symbols))
    avoid = frozenset((*config.avoid_symbols, *avoid_symbols))
    _validate_focus_avoid(purpose=purpose, pool=pool, focus=focus, avoid=avoid)

    user_text = _build_user_turn(
        generation=generation,
        purpose=purpose,
        shape=shape,
        pool=pool,
        config=config,
        findings=findings,
        standings=standings,
        previous_cards=previous_cards,
        focus=focus,
        avoid=avoid,
    )

    model = config.agent_model or DEFAULT_MODEL
    parsed, call, new_budget = call_structured(
        role="designer",
        system=DESIGNER_SYSTEM_PROMPT,
        user=user_text,
        output_format=_DesignerOutput,
        model=model,
        settings=settings,
        budget=budget,
        effort="high",
    )

    for index, card in enumerate(parsed.cards):
        _validate_card(card, index=index, pool=pool, shape=shape, focus=focus, avoid=avoid)

    genomes: dict[str, Genome] = {}
    for card in parsed.cards:
        genome = _to_genome(card, generation=generation, purpose=purpose, shape=shape)
        genomes.setdefault(genome.genome_id, genome)

    proposal = AgentProposal(cards=tuple(parsed.cards), reasoning=parsed.reasoning, call=call)
    return tuple(genomes.values()), proposal, new_budget
