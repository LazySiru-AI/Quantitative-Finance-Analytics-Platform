"""Answers a question in one influencer's voice, grounded in their own consolidated profile and
episodic notes -- Phase 4 of the persona feature. See `docs/INFLUENCER-CONTRACT.md`, "Phase 4 -- ask
the persona (pinned)", for the exact wire contract this module implements; the semantics below restate
it, they do not vary it.

**The point, and the guardrail that makes it safe.** Every other phase of this feature reports what
the influencer already said. This one is different in kind: it asks a model to project *forward*,
answering as if it were the person, on a question they may never have addressed directly. That is
exactly the shape of request most likely to produce a fabricated opinion or a piece of advice dressed
up as commentary, so the system prompt is explicit on both counts -- this is "a model's impression of
X, built from their own words", never X themselves, and it must never tell the reader what to do with
their money. The grounding gate is the mechanical half of that guardrail: every number the answer
states must trace back to the profile, the notes, or the market snapshot handed to it, exactly as
`app.agentdesk.grounding.run_grounded` already enforces for every other stage in this application.

**Why citations matter more here than anywhere else in the feature.** `app.personas.consolidate`
cites a note because a claim was *synthesised* across many; this module cites a note because the
answer is being offered as this person's view, and a reader has no way to tell "the record actually
supports this" from "the model made it up that sounds plausible" without being pointed at the exact
note it came from. So, following that module's own precedent: every citation the model returns is
checked against the `note_id`s actually handed to it in this call, and anything outside that set is
dropped, not repaired -- see `_filter_citations`'s own docstring for why. `stance` gets the same
treatment in spirit even though it is not a citation: the prompt requires it be read off the record,
never freshly opined, and defaults to `None` whenever no `symbol` was asked about at all.

**Retrieval is deliberately simple, not a search index.** When a `symbol` is given, the notes that
actually mention it are the most relevant evidence there is, so they come first (newest first); the
remaining budget of `MAX_CONTEXT_NOTES` is filled with the persona's most recent notes generally, so a
question about one ticker still gets some sense of what the influencer has been saying lately. With no
`symbol`, it's just the most recent notes. A vector search or ranking model would answer a slightly
different question -- "which notes are semantically similar" -- than the one this feature actually
needs, which is "what would this person plausibly bring up if asked this, given what they track and
what they said recently".

**The market snapshot exists to prevent one specific, common false rejection.** A persona asked "what
do you think of NVDA now" will naturally want to say something like "at 191 it's still expensive" --
but the influencer never said "191" in any note, so without evidence for it that figure is
unconditionally ungrounded and the gate degrades the answer over the most ordinary sentence in the
whole feature. `app.market.store.ensure_series` supplies exactly one figure (the latest daily close,
with its date) as an `EvidenceItem`, admitting the persona to speak to "now" without ever letting it
state a number the market data does not actually support. A provider failure here must never break
the answer -- the question can still be answered from the record alone -- so `_fetch_snapshot` catches
every failure and simply proceeds without the snapshot section.

**Grounding follows `app.personas.consolidate`'s own precedent for prose, not measured figures.** The
profile and notes handed in are themselves prose (a consolidated summary, a set of structured
summaries), not a data provider's numeric readings, so exactly as that module does, every numeric
token already present in the assembled context is minted into its own `EvidenceItem` via
`app.agentdesk.grounding.numeric_tokens` -- the same function `check()` runs over the model's own
answer -- making the two sides of the gate symmetric by construction. The market snapshot is the one
section built differently: it carries one real, provider-sourced `EvidenceItem` rather than a token
mined from prose, because it *is* a measured figure, not free text.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.agentdesk.grounding import numeric_tokens, run_grounded
from app.agentdesk.models import EvidenceItem, EvidencePack, EvidenceSection, GroundingVerdict
from app.agents.models import DEFAULT_MODEL, AgentBudget, AgentCall, AgentRole
from app.config import Settings
from app.db.duck import Interval
from app.market.providers.base import ProviderError
from app.market.store import ensure_series  # patched as `ask.ensure_series` in tests
from app.personas.models import EpisodicNote, PersonaAnswer, PersonaProfile, Stance

__all__ = [
    "MAX_CONTEXT_NOTES",
    "AskResult",
    "ask_persona",
]

_log = logging.getLogger(__name__)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# The model's output shape
# ---------------------------------------------------------------------------


class _AnswerDraft(_Frozen):
    """What the model returns for one ask call, before citation filtering is applied.

    Not `app.personas.models.PersonaAnswer` -- it carries no `persona`/`question`/`symbol`/`grounding`/
    `degraded`/`cost_usd`, the bookkeeping this module attaches itself once the call is graded and
    costed. It is the model's structured answer and nothing else, mirroring
    `app.personas.consolidate.ProfileDraft` and `app.personas.summarize.NoteDraft` one level up.
    """

    answer: str
    """The persona's voice, grounded only in the material handed to the model. In
    `Settings.persona_summary_lang`."""

    citations: tuple[str, ...]
    """`note_id` values the answer drew on, unfiltered as returned -- `ask_persona` checks these
    against the real input set before they ever reach the caller; see `_filter_citations`."""

    stance: Stance | None = None
    """The persona's stance on the asked `symbol`, read off the record -- never a fresh opinion. Left
    `None` when no `symbol` was asked about; `ask_persona` also forces it to `None` in that case
    regardless of what the model returns, since there is nothing for a stance to be *about*."""


@dataclass(frozen=True)
class AskResult:
    """What `ask_persona` hands back: the wire-ready `PersonaAnswer` plus every `AgentCall` the
    (single, at most `MAX_GROUNDING_ATTEMPTS`-times-retried) grounded call made, for the caller's own
    cost accounting -- mirroring `app.personas.consolidate.ConsolidationResult`'s own shape."""

    answer: PersonaAnswer
    calls: tuple[AgentCall, ...]


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

#: Caps how many notes are ever rendered into one ask prompt. The contract names this exact symbol
#: (`app.personas.ask.MAX_CONTEXT_NOTES`); kept as a plain module constant, not a `Settings` field, for
#: the same reason `app.personas.consolidate.MAX_INPUT_CHARS` is: a prompt-engineering bound on one
#: call, not deployment configuration anyone would reasonably want to override per install.
MAX_CONTEXT_NOTES = 12


def _note_timestamp(note: EpisodicNote) -> datetime:
    """The instant a note is ordered by -- `published` when known, else `ingested_at`. See
    `app.personas.consolidate._note_timestamp`'s own docstring (this is the same rule, kept as a local
    copy rather than an import so this module does not reach into a sibling shard's private names) for
    why substituting one for the other would be a fabrication, not a fallback, and why that does not
    apply to using it purely as a sort key."""
    return note.published or note.ingested_at


def _sorted_newest_first(notes: Sequence[EpisodicNote]) -> tuple[EpisodicNote, ...]:
    """`notes`, ordered newest-first by `_note_timestamp`, never trusting the caller already sorted
    them -- the same defensive sort `app.personas.consolidate._sorted_newest_first` applies, for the
    same reason: `sorted` is stable, so two notes at the exact same timestamp keep their relative input
    order rather than shuffling nondeterministically between calls."""
    return tuple(sorted(notes, key=_note_timestamp, reverse=True))


def _select_notes(notes: Sequence[EpisodicNote], *, symbol: str | None) -> tuple[EpisodicNote, ...]:
    """The notes that go into the ask prompt: relevant first, capped at `MAX_CONTEXT_NOTES`.

    With a `symbol`, "relevant" is notes that actually name it -- the influencer's own mentions are the
    most direct evidence for a question about that ticker there is -- newest first, and the remaining
    slots up to the cap are filled with the persona's other notes, newest first, so a question about
    one ticker still carries some sense of what the influencer has been saying lately rather than
    stopping dead the moment their mentions of that symbol run out. Without a `symbol`, there is
    nothing to prioritise by, so it is simply the most recent notes.

    `symbol` is expected pre-normalised (upper-cased) by the caller, matching how
    `app.personas.models.TickerMention.symbol` is always stored -- comparing case-sensitively here
    would silently fail to match on a lower-case argument and is worth calling out precisely because it
    would fail quietly rather than loudly.
    """
    ordered = _sorted_newest_first(notes)
    if symbol is None:
        return ordered[:MAX_CONTEXT_NOTES]

    matching = [note for note in ordered if any(m.symbol == symbol for m in note.mentions)]
    matching_ids = {note.note_id for note in matching}
    rest = [note for note in ordered if note.note_id not in matching_ids]
    return (*matching, *rest)[:MAX_CONTEXT_NOTES]


# ---------------------------------------------------------------------------
# Rendering the profile and notes into the prompt
# ---------------------------------------------------------------------------


def _render_profile(profile: PersonaProfile) -> str:
    """The consolidated profile's own beliefs/playbook/methodology/regime/vocabulary, rendered into
    plain labelled prose -- deliberately not the profile's own `citations`, which point at notes this
    call may not even have selected into `notes`; that provenance is this module's own to re-establish,
    over the notes it actually hands the model, not inherited from a prior consolidation call.

    Methodology and regime are rendered here for the same reason the summary and playbook are: they
    are the persona's *strategy* memory -- the named indicators, timeframes, entry/exit and risk rules
    (`methodology`), and the macro/regime posture (`regime`) -- and a question like "what indicators do
    you use" or "how do you read the macro" cannot be answered in the persona's voice from beliefs and
    playbook alone. Both were consolidated but were previously never shown to the ask model; omitting
    them made the ask model answer strategy questions from raw notes while the distilled answer sat
    unused in the profile. Each is emitted only when populated, matching the honest-empty discipline
    the consolidation step already applies (a pure macro commentator has no methodology; a pure
    technical trader has no regime signal)."""
    lines = [f"Summary: {profile.summary}"]
    if profile.beliefs:
        lines.append("Beliefs:")
        lines.extend(f"- {claim.text}" for claim in profile.beliefs)
    if profile.playbook:
        lines.append("Playbook:")
        lines.extend(f"- {claim.text}" for claim in profile.playbook)
    if profile.methodology:
        lines.append("Methodology (how they trade -- indicators, timeframes, entry/exit, risk):")
        lines.extend(f"- {claim.text}" for claim in profile.methodology)
    regime = profile.regime
    if regime is not None and regime.has_signal:
        regime_bits: list[str] = [f"risk posture {regime.risk}"]
        if regime.rates:
            regime_bits.append(f"rates: {regime.rates}")
        if regime.summary:
            regime_bits.append(regime.summary)
        if regime.sectors_favoured:
            regime_bits.append("favoured sectors: " + ", ".join(regime.sectors_favoured))
        if regime.sectors_avoided:
            regime_bits.append("avoided sectors: " + ", ".join(regime.sectors_avoided))
        lines.append("Macro/regime view: " + "; ".join(regime_bits))
    if profile.vocabulary:
        lines.append("Vocabulary: " + ", ".join(profile.vocabulary))
    return "\n".join(lines)


def _render_note(note: EpisodicNote) -> str:
    """One note rendered into the block the model reads, tagged with its `note_id` so a citation can
    name it -- the same shape `app.personas.consolidate._render_note` uses, kept as a local copy for
    the same reason `_note_timestamp` is."""
    published = note.published.date().isoformat() if note.published else "unknown"
    lines = [
        f"### note_id: {note.note_id}",
        f"Published: {published}",
        f"Title: {note.title or '(untitled)'}",
    ]
    if note.themes:
        lines.append("Themes:")
        lines.extend(f"- {theme}" for theme in note.themes)
    lines.append(f"Summary: {note.summary}")
    if note.quotes:
        lines.append("Quotes:")
        lines.extend(f"- {quote}" for quote in note.quotes)
    if note.mentions:
        lines.append("Mentions:")
        lines.extend(f"- {m.symbol} ({m.stance}): {m.reasoning}" for m in note.mentions)
    return "\n".join(lines)


def _render_notes_text(notes: Sequence[EpisodicNote]) -> str:
    """`notes`, already selected and ordered by the caller, rendered and joined -- or an explicit
    placeholder when there are none, so the model is told plainly that it has nothing here rather than
    being handed an empty section and left to guess why."""
    if not notes:
        return "(no episodic notes on record for this persona yet)"
    return "\n\n".join(_render_note(note) for note in notes)


# ---------------------------------------------------------------------------
# Market snapshot -- one real figure, never a section that can break the answer
# ---------------------------------------------------------------------------


def _fetch_snapshot(symbol: str, settings: Settings) -> tuple[EvidenceItem | None, str]:
    """The persona's "now": the latest stored daily close for `symbol` and its date, as one real
    `EvidenceItem` (not a numeric token mined from prose -- see the module docstring) plus the prose
    line describing it. `(None, "")` on anything that goes wrong, or when the store has nothing at all
    -- a snapshot is a nice-to-have that lets the persona speak to the present, never a dependency the
    answer can fail over. `app.market.providers.base.ProviderError` is the documented failure mode
    (`ensure_series` re-raises it when there is nothing stored to fall back to); a bare `Exception` is
    also caught, deliberately broader than the documented contract, because a market-data fetch is the
    one part of this call reaching outside this feature's own storage and the cost of a wider net here
    is nothing -- the answer proceeds without the snapshot either way -- while the cost of not catching
    one is breaking an otherwise-answerable question over a network hiccup.
    """
    try:
        series = ensure_series(symbol, Interval.DAY, limit=6, settings=settings)
    except ProviderError as exc:
        _log.info("ask_persona: market snapshot unavailable for %s (%s)", symbol, exc)
        return None, ""
    except Exception as exc:  # broad on purpose -- see docstring: a snapshot must never break the answer
        _log.warning("ask_persona: unexpected error fetching market snapshot for %s: %s", symbol, exc)
        return None, ""

    if not series.bars:
        return None, ""

    latest = max(series.bars, key=lambda bar: bar.ts)
    value = f"{latest.close:.2f}"
    as_of = latest.ts.date().isoformat()
    item = EvidenceItem(
        key="latest_close", label="Latest close", value=value, unit="USD", as_of=as_of,
        source="duckdb-store",
    )
    text = f"Most recent stored close for {symbol}: {value} USD, as of {as_of}."
    return item, text


# ---------------------------------------------------------------------------
# Evidence pack
# ---------------------------------------------------------------------------


def _numeric_evidence_items(text: str, *, key_prefix: str, label: str) -> tuple[EvidenceItem, ...]:
    """One `EvidenceItem` per distinct numeric token `text` contains -- see the module docstring for
    why this makes the profile and notes sections symmetric with what the gate checks the model's own
    answer against, the same trick `app.personas.consolidate._build_evidence_pack` and
    `app.personas.summarize._build_evidence_pack` already use."""
    tokens = sorted(set(numeric_tokens(text)))
    return tuple(EvidenceItem(key=f"{key_prefix}_{i}", label=label, value=token) for i, token in enumerate(tokens))


def _build_evidence_pack(
    *,
    symbol: str | None,
    profile_text: str | None,
    notes_text: str,
    snapshot_item: EvidenceItem | None,
    snapshot_text: str,
) -> EvidencePack:
    """One section per input the model was actually given: the profile (only when consolidated), the
    selected notes (always present, even if only as the "nothing on record" placeholder), and the
    market snapshot (only when a `symbol` was asked about and a fetch actually succeeded)."""
    sections: list[EvidenceSection] = []
    if profile_text is not None:
        items = _numeric_evidence_items(
            profile_text, key_prefix="profile_figure", label="Number stated in the persona profile",
        )
        sections.append(EvidenceSection(title="Persona profile", items=items, text=profile_text))

    note_items = _numeric_evidence_items(
        notes_text, key_prefix="note_figure", label="Number stated across the notes",
    )
    sections.append(EvidenceSection(title="Episodic notes", items=note_items, text=notes_text))

    if snapshot_item is not None:
        sections.append(
            EvidenceSection(title="Market snapshot", items=(snapshot_item,), text=snapshot_text)
        )

    return EvidencePack(symbol=symbol or "", sections=tuple(sections))


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

#: See `app.personas.summarize._ROLE`'s own docstring for why every call this feature makes archives
#: under `AgentRole`'s `"swarm_worker"` member rather than a persona-specific one -- the same reasoning
#: applies unchanged here.
_ROLE: AgentRole = "swarm_worker"

_SYSTEM_PROMPT = """You are a model's impression of a financial-market influencer named {persona}, built \
entirely from their own recorded persona profile and episodic notes, given to you below. You are NOT \
{persona} -- you are a best-effort reconstruction of how they would likely respond, based only on what \
they are actually on record as believing and doing. You never add your own market opinion, forecast, \
price target, or recommendation, and you never invent a position, view, or fact {persona} did not \
actually express in the material below. You are not a licensed financial advisor and nothing you write \
is financial advice: never tell the reader what to buy, sell, hold, or otherwise do with their money -- \
describe what {persona} is on record thinking and doing, and let the reader draw their own conclusions.

GROUNDING. Answer using ONLY the persona profile, episodic notes, and market snapshot given to you \
below -- never your own outside knowledge of markets, companies, prices, or current events. Every \
number you state must appear in that material, or be a straightforward difference or percentage change \
computed directly from two figures that do; never estimate, round to a plausible-sounding figure, or \
otherwise invent one. If the material below simply does not address the question, say so plainly in \
`answer` -- in {persona}'s voice, as in "I haven't said anything on record about that" -- rather than \
inventing a view to fill the gap.

CITATIONS. Every episodic note below is tagged with an exact `note_id`. Your `citations` field must \
list every `note_id` whose content you actually drew on to write `answer`, copied verbatim from the \
tags below. Never invent a `note_id` that is not shown to you, and never cite a note whose content is \
unrelated to what you wrote. If no note below actually bears on the question, leave `citations` empty \
rather than citing something unrelated.

{stance_instruction}

LANGUAGE. Write `answer` in {lang}.

Respond with only the fields the schema asks for -- no extra commentary before or after."""

_STANCE_INSTRUCTION_WITH_SYMBOL = (
    "STANCE. The question asks about {symbol}. Set `stance` to \"bullish\", \"bearish\", \"neutral\", or "
    "\"unclear\", based ONLY on what the persona profile and episodic notes below show about {persona}'s "
    "own actual, recorded view of {symbol} -- if the material does not clearly support one direction, or "
    "says nothing about {symbol} at all, use \"unclear\". Never state a stance the material does not "
    "actually support, and never supply your own fresh opinion on {symbol}."
)
_STANCE_INSTRUCTION_NO_SYMBOL = (
    "STANCE. No specific symbol was asked about in this question -- leave `stance` as null."
)


def _build_user_prompt(
    *,
    persona_slug: str,
    question: str,
    symbol: str | None,
    profile_text: str | None,
    notes_text: str,
    snapshot_text: str,
    summary_lang: str,
) -> str:
    """The user turn: the question, then every section of context the model is allowed to draw on, in
    the same order `_build_evidence_pack` assembles them -- profile, notes, snapshot -- each clearly
    delimited so the model (and a reader of the archived `AgentCall.user`) can tell which section a
    given fact came from."""
    parts = [f"Persona: {persona_slug}", f"Question: {question}"]
    if symbol:
        parts.append(f"Symbol asked about: {symbol}")

    if profile_text is not None:
        parts.append(f"--- PERSONA PROFILE START ---\n{profile_text}\n--- PERSONA PROFILE END ---")

    parts.append(f"--- EPISODIC NOTES START ---\n{notes_text}\n--- EPISODIC NOTES END ---")

    if snapshot_text:
        parts.append(f"--- MARKET SNAPSHOT START ---\n{snapshot_text}\n--- MARKET SNAPSHOT END ---")

    parts.append(
        f"Answer the question above in {summary_lang}, in {persona_slug}'s voice, per your instructions. "
        "Cite ONLY the exact note_id values tagged in the episodic notes section above."
    )
    return "\n\n".join(parts)


def _draft_prose(draft: _AnswerDraft) -> str:
    """The text `run_grounded` checks for ungrounded numbers: `answer` alone. `citations` is a list of
    ids, not prose, and `stance` is a closed enum value -- neither can carry a numeric token worth
    checking, so including them would only risk a false rejection over structure the gate was never
    meant to read."""
    return draft.answer


# ---------------------------------------------------------------------------
# Citation filtering -- ours to enforce, never the model's to self-police
# ---------------------------------------------------------------------------


def _filter_citations(
    citations: tuple[str, ...], valid_note_ids: frozenset[str], *, persona_slug: str,
) -> tuple[str, ...]:
    """`citations`, with every entry outside `valid_note_ids` dropped -- never repaired, there being
    nothing to repair a bare id into. Mirrors `app.personas.consolidate._filter_claims`'s own reasoning
    one level down: unlike a `ProfileClaim`, a bare citation string carries no other content to keep,
    so "drop whole" and "drop the one bad entry" are the same operation here -- but the check itself,
    against the *actual* input note_id set rather than trusting the model's own list, is the same
    guarantee for the same reason: nothing stops a model from citing a note_id it invented outright.

    Every drop is logged, not silently discarded, for the same reason `_filter_claims` logs: there is
    no `GroundingIssue.kind` for "the model cited a note_id it never saw" on the pinned
    `app.agentdesk.models`, so a module-level logger is the record of what was dropped and why.
    """
    kept = tuple(citation for citation in citations if citation in valid_note_ids)
    dropped = [citation for citation in citations if citation not in valid_note_ids]
    if dropped:
        _log.warning(
            "ask_persona(%s): dropped %d citation(s) outside the input note_id set: %s",
            persona_slug, len(dropped), ", ".join(dropped),
        )
    return kept


# ---------------------------------------------------------------------------
# The "nothing on record yet" case -- no model call, never raised
# ---------------------------------------------------------------------------


def _nothing_on_record_answer(
    *, persona_slug: str, question: str, symbol: str | None, budget: AgentBudget,
) -> PersonaAnswer:
    """The answer `ask_persona` returns when there is no profile and no note to ground anything in --
    calling the model here would hand it an entirely empty evidence pack and ask it to say something
    anyway, which is exactly the fabrication risk this whole feature exists to prevent. `grounding` is
    a trivial, un-degraded pass (`ok=True`, `checked_tokens=0`): nothing was checked because nothing
    was said that needed checking, which is a legitimate state (see
    `app.agentdesk.models.GroundingVerdict.checked_tokens`'s own docstring), not a failure dressed up
    as a pass. `cost_usd` still reflects `budget` as handed in, unspent, since no call was made."""
    return PersonaAnswer(
        persona=persona_slug,
        question=question,
        symbol=symbol,
        answer=(
            f"I don't have any notes or a consolidated profile for {persona_slug} on record yet, so "
            "I can't answer this the way they actually would -- there's nothing here to draw from."
        ),
        citations=(),
        stance=None,
        grounding=GroundingVerdict(ok=True, checked_tokens=0),
        degraded=False,
        cost_usd=str(budget.spent_usd),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def ask_persona(
    *,
    persona_slug: str,
    question: str,
    symbol: str | None,
    profile: PersonaProfile | None,
    notes: Sequence[EpisodicNote],
    settings: Settings,
    budget: AgentBudget,
    model: str = DEFAULT_MODEL,
) -> AskResult:
    """Answer `question` in `persona_slug`'s voice, grounded in `profile` (when consolidated) plus the
    notes relevant to `question`/`symbol` (see `_select_notes`) plus a market snapshot when `symbol` is
    given (see `_fetch_snapshot`).

    **Total, per the contract: never raises for having nothing to answer from.** When there is no
    profile and no note at all, this returns `_nothing_on_record_answer` without ever calling the
    model -- the caller (the `/ask` endpoint, per `docs/INFLUENCER-CONTRACT.md`) decides whether that
    state deserves a 409 before ever reaching this function; this function's own job is to stay total.

    **Never raises for a grounding failure**, exactly as `app.personas.consolidate.consolidate_notes`
    and `app.personas.summarize.summarize_item` both document for the same reason:
    `app.agentdesk.grounding.run_grounded` returns `verdict.ok=False, verdict.degraded=True` on a call
    that still fails its check on the last attempt, carrying whatever the model actually produced, and
    that is passed through on `PersonaAnswer.grounding`/`.degraded` unchanged. `AgentUnavailable` (no
    credential, a refusal) and `BudgetExhausted` (the run's spend ceiling) are not grounding outcomes --
    they mean the call could not be attempted or completed at all -- and `run_grounded` raises both
    unchanged; this function does not catch either, so they propagate to the caller exactly as
    documented there.

    Citation filtering (`_filter_citations`) always runs, even on a degraded answer: an answer released
    with unverified prose is still not licence to carry a fabricated citation out to the reader.
    `stance` is forced to `None` whenever no `symbol` was asked about, regardless of what the model
    returned -- the prompt already instructs this, but there is nothing a stance could be *about* in
    that case, so it is enforced here rather than trusted to prompt compliance alone.
    """
    symbol_norm = symbol.strip().upper() if symbol else None

    if not notes and profile is None:
        return AskResult(
            answer=_nothing_on_record_answer(
                persona_slug=persona_slug, question=question, symbol=symbol_norm, budget=budget,
            ),
            calls=(),
        )

    summary_lang = settings.persona_summary_lang or "en"

    profile_text = _render_profile(profile) if profile is not None else None
    selected_notes = _select_notes(notes, symbol=symbol_norm)
    notes_text = _render_notes_text(selected_notes)
    snapshot_item, snapshot_text = (
        _fetch_snapshot(symbol_norm, settings) if symbol_norm else (None, "")
    )

    pack = _build_evidence_pack(
        symbol=symbol_norm, profile_text=profile_text, notes_text=notes_text,
        snapshot_item=snapshot_item, snapshot_text=snapshot_text,
    )

    stance_instruction = (
        _STANCE_INSTRUCTION_WITH_SYMBOL.format(symbol=symbol_norm, persona=persona_slug)
        if symbol_norm
        else _STANCE_INSTRUCTION_NO_SYMBOL
    )
    system = _SYSTEM_PROMPT.format(
        persona=persona_slug, stance_instruction=stance_instruction, lang=summary_lang,
    )
    user = _build_user_prompt(
        persona_slug=persona_slug, question=question, symbol=symbol_norm, profile_text=profile_text,
        notes_text=notes_text, snapshot_text=snapshot_text, summary_lang=summary_lang,
    )

    grounded = run_grounded(
        role=_ROLE,
        system=system,
        user=user,
        output_format=_AnswerDraft,
        prose_of=_draft_prose,
        pack=pack,
        settings=settings,
        budget=budget,
        model=model,
    )

    valid_note_ids = frozenset(note.note_id for note in selected_notes)
    citations = _filter_citations(grounded.value.citations, valid_note_ids, persona_slug=persona_slug)
    stance = grounded.value.stance if symbol_norm else None

    answer = PersonaAnswer(
        persona=persona_slug,
        question=question,
        symbol=symbol_norm,
        answer=grounded.value.answer,
        citations=citations,
        stance=stance,
        grounding=grounded.verdict,
        degraded=grounded.verdict.degraded,
        cost_usd=str(grounded.budget.spent_usd),
    )
    return AskResult(answer=answer, calls=grounded.calls)
