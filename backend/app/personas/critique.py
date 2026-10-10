"""A persona reads a strategy card and says, in their own voice, how well it fits how THEY trade --
the reverse of the persona -> card mapping (`app.personas.strategy.draft_strategy_card`). See
`docs/AGENT-DESK-CONTRACT.md` for the shared grounding/evidence layer this module sits on, and
`app.personas.models.CardCritique` for the wire shape this module fills in.

**A reading lens, never advice.** `app.personas.strategy` takes a persona's methodology and invents a
new card *inspired by* it. This module runs the opposite direction: someone else's card already
exists, and the question is only ever "does this look like something {persona} would actually do",
never "should the reader trade this". The guardrail is the same one `app.personas.ask` draws for the
identical reason -- this is a model's *impression* of the persona, built from their own recorded words,
never the person themselves and never a recommendation.

**Grounding follows `app.personas.ask` and `app.personas.strategy`'s own precedent for prose.** The
profile and the card are both prose/structured text, not a live provider's measured figures, so exactly
as those modules do, every numeric token already present in each is minted into its own `EvidenceItem`
via `app.agentdesk.grounding.numeric_tokens` -- the same function `run_grounded`'s own check runs over
the model's `assessment`, making both sides of the gate symmetric by construction.

**Citations are ours to enforce, never the model's to self-police.** The valid `note_id` set is not the
notes themselves (this module is never handed the raw episodic notes -- only the consolidated
`PersonaProfile`) but the union of every citation already attached to `profile.beliefs`,
`profile.playbook`, `profile.methodology`, and `profile.regime` -- precisely the citations rendered into
the prompt in `_render_profile`. A citation outside that set is dropped, not repaired, and logged,
mirroring `app.personas.ask._filter_citations` exactly.

**No profile, or a profile with nothing to judge from -> `cannot_say`, no model call.** A profile that
has never been consolidated (`None`), or one that carries no beliefs, no playbook, no methodology, and
no regime signal (a profile from before any of those existed, or one that failed to extract anything
usable), gives the model nothing to compare the card against -- asking it anyway would be inviting
exactly the fabrication this module exists to prevent. `_is_empty_profile` names that case explicitly
rather than leaving it to an accidentally-empty prompt to discover.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agentdesk.grounding import numeric_tokens, run_grounded
from app.agentdesk.models import EvidenceItem, EvidencePack, EvidenceSection
from app.agents.models import DEFAULT_MODEL, AgentBudget, AgentCall, AgentRole
from app.config import Settings
from app.personas.models import CardCritique, PersonaProfile, ProfileClaim, RegimeView

__all__ = ["CritiqueResult", "critique_card"]

_log = logging.getLogger(__name__)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# The model's output shape
# ---------------------------------------------------------------------------


class _CritiqueDraft(_Frozen):
    """What the model returns for one critique call, before citation filtering is applied.

    Not `app.personas.models.CardCritique` itself -- it carries no `persona`/`caveat`/`degraded`/
    `cost_usd`, the bookkeeping `critique_card` attaches once the call is graded and costed, mirroring
    `app.personas.ask._AnswerDraft` one level up."""

    verdict: Literal["aligned", "mixed", "misaligned", "cannot_say"]
    """How well the card fits how the persona is on record trading -- read off `profile` alone, never
    a fresh judgement about whether the card is a good idea."""

    assessment: str
    """The persona's voice, grounded only in the profile handed to the model."""

    citations: tuple[str, ...] = ()
    """`note_id` values the assessment drew on, unfiltered as returned -- `critique_card` checks these
    against the real profile citation set before they ever reach the caller; see `_filter_citations`."""


@dataclass(frozen=True)
class CritiqueResult:
    """What `critique_card` hands back: the wire-ready `CardCritique` plus every `AgentCall` the
    (single, at most `MAX_GROUNDING_ATTEMPTS`-times-retried) grounded call made, for the caller's own
    cost accounting -- mirroring `app.personas.ask.AskResult`'s own shape."""

    critique: CardCritique
    calls: tuple[AgentCall, ...]


# ---------------------------------------------------------------------------
# Rendering the profile into the prompt, with citations attached
# ---------------------------------------------------------------------------


def _render_claims(label: str, claims: Sequence[ProfileClaim]) -> list[str]:
    """One labelled block per non-empty claim group, each claim tagged with the exact `note_id`(s) it
    was drawn from -- the same `[note_id(s): ...]` tagging `app.personas.strategy._render_methodology`
    uses, so the valid citation set (`_valid_note_ids`) matches exactly what the model was shown."""
    if not claims:
        return []
    lines = [f"{label}:"]
    for claim in claims:
        note_ids = ", ".join(claim.citations)
        lines.append(f"- {claim.text} [note_id(s): {note_ids}]")
    return lines


def _render_regime(regime: RegimeView | None) -> list[str]:
    """The persona's macro/regime posture, tagged with its own citations -- the counterpart to
    `_render_claims` for a commentator with no mechanical toolkit. Omitted entirely when `regime` is
    `None` or carries no signal, the same honest-empty discipline `RegimeView.has_signal` documents."""
    if regime is None or not regime.has_signal:
        return []
    lines = ["Regime view:"]
    lines.append(f"- risk posture: {regime.risk}")
    if regime.rates:
        lines.append(f"- rates view: {regime.rates}")
    if regime.summary:
        lines.append(f"- summary: {regime.summary}")
    if regime.sectors_favoured:
        lines.append(f"- sectors favoured: {', '.join(regime.sectors_favoured)}")
    if regime.sectors_avoided:
        lines.append(f"- sectors avoided: {', '.join(regime.sectors_avoided)}")
    lines.append(f"  [note_id(s): {', '.join(regime.citations)}]")
    return lines


def _render_profile(profile: PersonaProfile) -> str:
    """The consolidated profile's beliefs/playbook/methodology/regime, rendered into plain labelled
    prose with each claim's own citations attached -- unlike `app.personas.ask._render_profile`, which
    deliberately omits citations (that module is also handed the raw notes and re-establishes its own
    provenance over them), this module is handed nothing but `profile`, so the profile's own citations
    are the only provenance there is."""
    lines = [f"Summary: {profile.summary}"]
    lines.extend(_render_claims("Beliefs", profile.beliefs))
    lines.extend(_render_claims("Playbook", profile.playbook))
    lines.extend(_render_claims("Methodology", profile.methodology))
    lines.extend(_render_regime(profile.regime))
    return "\n".join(lines)


def _valid_note_ids(profile: PersonaProfile) -> frozenset[str]:
    """Every `note_id` actually shown to the model in `_render_profile` -- the union of `beliefs`,
    `playbook`, and `methodology` claim citations plus `regime.citations` when present. The set
    `_filter_citations` checks the model's own citations against."""
    ids: set[str] = set()
    for claim in (*profile.beliefs, *profile.playbook, *profile.methodology):
        ids.update(claim.citations)
    if profile.regime is not None:
        ids.update(profile.regime.citations)
    return frozenset(ids)


def _is_empty_profile(profile: PersonaProfile) -> bool:
    """`True` when `profile` carries no belief, no playbook claim, no methodology claim, and no regime
    signal -- nothing here to judge a card against. See the module docstring for why this short-circuits
    to `cannot_say` before any model call rather than handing the model an empty prompt."""
    has_regime_signal = profile.regime is not None and profile.regime.has_signal
    return not profile.beliefs and not profile.playbook and not profile.methodology and not has_regime_signal


# ---------------------------------------------------------------------------
# Rendering the card into the prompt
# ---------------------------------------------------------------------------

#: The `StrategyCard` (`app.tournament.models.StrategyCard`) fields worth showing the persona --
#: `card` arrives as a plain `dict[str, object]` (the caller's own `card.model_dump(mode="json")` or
#: equivalent), so this module reads it defensively by key rather than assuming every key is present.
_CARD_FIELDS: tuple[tuple[str, str], ...] = (
    ("display_name", "Name"),
    ("discipline", "Discipline"),
    ("purpose", "Purpose"),
    ("universe", "Universe"),
    ("entry", "Entry rule"),
    ("exit", "Exit rule"),
    ("stop_loss_pct", "Stop loss"),
    ("take_profit_pct", "Take profit"),
    ("max_hold_days", "Max hold (days)"),
    ("max_positions", "Max positions"),
    ("position_pct", "Position size"),
    ("rank_by", "Ranking key"),
    ("thesis", "Thesis"),
)


def _render_card(card: dict[str, object]) -> str:
    """`card`'s recognised fields (`_CARD_FIELDS`), one per line, skipping any key that is absent,
    `None`, or an empty string -- a card is never rejected here for missing a field this module does
    not itself require; that is `app.tournament.models.StrategyCard`'s own job, upstream of this call."""
    lines: list[str] = []
    for key, label in _CARD_FIELDS:
        if key not in card:
            continue
        value = card[key]
        if value is None or value == "":
            continue
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value)
        lines.append(f"{label}: {value}")
    if not lines:
        return "(no recognised strategy-card fields were given)"
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Evidence pack
# ---------------------------------------------------------------------------

#: See `app.personas.summarize._ROLE`/`app.personas.ask._ROLE`'s own docstrings for why every model
#: call this feature makes archives under `AgentRole`'s shared `"swarm_worker"` member rather than a
#: persona-specific one -- the same reasoning applies unchanged here.
_ROLE: AgentRole = "swarm_worker"


def _numeric_evidence_items(text: str, *, key_prefix: str, label: str) -> tuple[EvidenceItem, ...]:
    """One `EvidenceItem` per distinct numeric token `text` contains -- see the module docstring for
    why this makes the profile and card sections symmetric with what the gate checks the model's own
    `assessment` against, the same trick `app.personas.ask._numeric_evidence_items` already uses."""
    tokens = sorted(set(numeric_tokens(text)))
    return tuple(EvidenceItem(key=f"{key_prefix}_{i}", label=label, value=token) for i, token in enumerate(tokens))


def _build_evidence_pack(*, profile_text: str, card_text: str) -> EvidencePack:
    """One section per input the model was actually given: the persona profile, then the strategy
    card -- `symbol=""` because a critique is about a card (which may name several tickers in its
    `universe`), not one instrument, the same "not about one instrument" case
    `app.agentdesk.models.EvidencePack.symbol`'s own docstring documents."""
    profile_items = _numeric_evidence_items(
        profile_text, key_prefix="profile_figure", label="Number stated in the persona profile",
    )
    card_items = _numeric_evidence_items(
        card_text, key_prefix="card_figure", label="Number stated in the strategy card",
    )
    sections = (
        EvidenceSection(title="Persona profile", items=profile_items, text=profile_text),
        EvidenceSection(title="Strategy card", items=card_items, text=card_text),
    )
    return EvidencePack(symbol="", sections=sections)


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a model's impression of a financial-market influencer named {persona}, built \
entirely from their own recorded persona profile, given to you below. You have been shown a strategy \
card someone else designed, and your job is to judge how well it fits how {persona} ACTUALLY trades -- \
NOT whether it is a good strategy, and NOT whether the reader should trade it. You are NOT {persona} -- \
you are a best-effort reconstruction of how they would likely react to seeing this card, based only on \
what they are actually on record believing and doing. You never add your own market opinion, forecast, \
or recommendation, and you never invent a belief, habit, or rule {persona} did not actually express in \
the profile below. You are not a licensed financial advisor and nothing you write is financial advice: \
never tell the reader whether to trade this card -- describe how it does or does not fit what {persona} \
is on record doing, and let the reader draw their own conclusions.

GROUNDING. Judge the card using ONLY the persona profile and the strategy card given to you below -- \
never your own outside knowledge of {persona}, markets, or trading in general. Every number you state \
must appear in the profile or the card, or be a straightforward difference or percentage change computed \
directly from two figures that do; never estimate, round to a plausible-sounding figure, or otherwise \
invent one.

VERDICT. Set `verdict` to exactly one of "aligned" (the card's rules are consistent with how {persona} is \
on record trading), "mixed" (some parts fit, some clash), "misaligned" (the card contradicts how \
{persona} is on record trading), or "cannot_say" (the profile below simply does not say enough to judge \
this card either way). Never default to "aligned" to be agreeable, and never call a card "misaligned" \
over a detail the profile never actually addressed -- use "cannot_say" for that instead.

CITATIONS. Every claim in the persona profile below is tagged with the exact note_id(s) it was drawn \
from. Your `citations` field must list every note_id whose content you actually drew on to write \
`assessment`, copied verbatim from the tags below. Never invent a note_id that is not shown to you, and \
never cite one whose content is unrelated to what you wrote. If nothing below actually bears on the \
card, leave `citations` empty rather than citing something unrelated.

VOICE. Write `assessment` in {persona}'s own voice, in a few sentences, reacting to seeing this card -- \
e.g. "this looks like..." / "I wouldn't...". Never tell the reader what to do with their money.

LANGUAGE. Write `assessment` in {lang}.

Respond with only the fields the schema asks for -- no extra commentary before or after."""


def _build_user_prompt(*, persona_slug: str, profile_text: str, card_text: str) -> str:
    return (
        f"Persona: {persona_slug}\n\n"
        f"--- PERSONA PROFILE START ---\n{profile_text}\n--- PERSONA PROFILE END ---\n\n"
        f"--- STRATEGY CARD START ---\n{card_text}\n--- STRATEGY CARD END ---\n\n"
        f"Judge how well this card fits how {persona_slug} actually trades, per your instructions. Cite "
        "ONLY the exact note_id values tagged in the persona profile section above."
    )


def _draft_prose(draft: _CritiqueDraft) -> str:
    """The text `run_grounded` checks for ungrounded numbers: `assessment` alone. `citations` is a list
    of ids, not prose, and `verdict` is a closed enum value -- neither can carry a numeric token worth
    checking, mirroring `app.personas.ask._draft_prose`'s own reasoning exactly."""
    return draft.assessment


# ---------------------------------------------------------------------------
# Citation filtering -- ours to enforce, never the model's to self-police
# ---------------------------------------------------------------------------


def _filter_citations(
    citations: tuple[str, ...], valid_note_ids: frozenset[str], *, persona_slug: str,
) -> tuple[str, ...]:
    """`citations`, with every entry outside `valid_note_ids` dropped -- never repaired, there being
    nothing to repair a bare id into. Mirrors `app.personas.ask._filter_citations` exactly, applied to
    the profile's own claim citations (`_valid_note_ids`) rather than a set of episodic notes."""
    kept = tuple(citation for citation in citations if citation in valid_note_ids)
    dropped = [citation for citation in citations if citation not in valid_note_ids]
    if dropped:
        _log.warning(
            "critique_card(%s): dropped %d citation(s) outside the profile's own citation set: %s",
            persona_slug, len(dropped), ", ".join(dropped),
        )
    return kept


# ---------------------------------------------------------------------------
# The "nothing to judge from" case -- no model call, never raised
# ---------------------------------------------------------------------------

_CAVEAT = (
    "An impression of how this persona might read this card, built from their own recorded words -- "
    "not the person, and not investment advice."
)


def _no_profile_critique(*, persona_slug: str, budget: AgentBudget) -> CardCritique:
    """The critique `critique_card` returns when there is no profile, or nothing in it to judge a card
    against -- calling the model here would hand it an empty comparison and ask it to say something
    anyway, exactly the fabrication risk this feature exists to prevent. `cost_usd` still reflects
    `budget` as handed in, unspent, since no call was made -- mirroring
    `app.personas.ask._nothing_on_record_answer`'s own reasoning."""
    return CardCritique(
        persona=persona_slug,
        verdict="cannot_say",
        assessment=(
            f"I don't have a consolidated profile for {persona_slug} on record yet -- there's nothing "
            "here to judge this card against."
        ),
        citations=(),
        caveat=_CAVEAT,
        degraded=False,
        cost_usd=str(budget.spent_usd),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def critique_card(
    *,
    persona_slug: str,
    profile: PersonaProfile | None,
    card: dict[str, object],
    settings: Settings,
    budget: AgentBudget,
    model: str = DEFAULT_MODEL,
) -> CritiqueResult:
    """Have `persona_slug` read `card` and judge, in their own voice, how well it fits how they are on
    record trading -- grounded in `profile` (`beliefs`/`playbook`/`methodology`/`regime`) alone. The
    reverse of `app.personas.strategy.draft_strategy_card`: that module invents a card from a
    methodology; this one reacts to a card that already exists.

    **Total, per the contract: never raises for having nothing to judge from.** When `profile` is
    `None`, or carries no belief, playbook claim, methodology claim, or regime signal
    (`_is_empty_profile`), this returns `_no_profile_critique` -- `verdict="cannot_say"` -- without ever
    calling the model.

    **Never raises for a grounding failure**, exactly as `app.personas.ask.ask_persona` and
    `app.personas.consolidate.consolidate_notes` both document for the same reason:
    `app.agentdesk.grounding.run_grounded` returns `verdict.ok=False, verdict.degraded=True` on a call
    that still fails its check on the last attempt, carrying whatever the model actually produced, and
    that is passed through on `CardCritique.degraded` unchanged. `AgentUnavailable` (no credential, a
    refusal) and `BudgetExhausted` (the run's spend ceiling) are not grounding outcomes -- they mean the
    call could not be attempted or completed at all -- and `run_grounded` raises both unchanged; this
    function does not catch either, so they propagate to the caller exactly as documented there.

    Citation filtering (`_filter_citations`) always runs, even on a degraded critique: a critique
    released with unverified prose is still not licence to carry a fabricated citation out to the
    reader.
    """
    if profile is None or _is_empty_profile(profile):
        return CritiqueResult(
            critique=_no_profile_critique(persona_slug=persona_slug, budget=budget), calls=(),
        )

    lang = settings.persona_summary_lang or "en"
    profile_text = _render_profile(profile)
    card_text = _render_card(card)
    pack = _build_evidence_pack(profile_text=profile_text, card_text=card_text)

    system = _SYSTEM_PROMPT.format(persona=persona_slug, lang=lang)
    user = _build_user_prompt(persona_slug=persona_slug, profile_text=profile_text, card_text=card_text)

    grounded = run_grounded(
        role=_ROLE,
        system=system,
        user=user,
        output_format=_CritiqueDraft,
        prose_of=_draft_prose,
        pack=pack,
        settings=settings,
        budget=budget,
        model=model,
    )

    valid_note_ids = _valid_note_ids(profile)
    citations = _filter_citations(grounded.value.citations, valid_note_ids, persona_slug=persona_slug)

    critique = CardCritique(
        persona=persona_slug,
        verdict=grounded.value.verdict,
        assessment=grounded.value.assessment,
        citations=citations,
        caveat=_CAVEAT,
        degraded=grounded.verdict.degraded,
        cost_usd=str(grounded.budget.spent_usd),
    )
    return CritiqueResult(critique=critique, calls=grounded.calls)
