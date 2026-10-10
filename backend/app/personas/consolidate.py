"""Folds a persona's episodic notes into a consolidated `PersonaProfile` and per-symbol `TickerThesis`
objects.

Phase 1 (`app.personas.summarize`) writes one immutable note per ingested item. This module is Phase
2: given all of a persona's notes (or a recent window of them -- the caller decides which), it asks
one grounded model call to synthesise a `ProfileDraft` -- who this person is, what they believe, how
they trade -- and builds the per-symbol `TickerThesis` objects itself, deterministically, from the
notes' own `TickerMention` records. The two halves are split for a reason: a persona's stance on NVDA
across their last twenty notes is a plain "most recent mention wins" fold that Python can get right
every time, and asking a model to reconstruct it would only add a chance to get it wrong. What a model
*is* good for -- reading twenty notes' worth of prose and finding the beliefs and habits that recur
across them -- is exactly the part with no mechanical substitute, so that is the only part it does.

**Citations are the one hard rule the contract adds for this phase.** An episodic note is immutable
and self-evidently traces to one transcript; a profile claim is synthesised across many notes, so
without the note ids behind it there is no way to tell a thing the influencer actually said from a
thing the model inferred. `app.personas.models.ProfileClaim` already refuses to construct with an
empty `citations` tuple -- that guards against an *empty* citation, but not a *wrong* one, since
nothing stops a model from citing a note_id it never saw or invented outright. This module is the
other half of that guarantee: every claim the model returns is checked against the full set of
`note_id`s actually passed in, and any claim citing so much as one id outside that set is dropped
whole, not repaired -- see `_filter_claims`'s own docstring for why a partially-bad claim is not
worth salvaging. A dropped claim is logged, exactly as `app.personas.summarize` logs a dropped ticker
mention, for the same reason: silent data loss here would look identical to the model simply choosing
not to make a claim.

**Grounding follows `app.personas.summarize`'s own precedent for prose, not measured figures.** The
notes handed in are already structured summaries (Phase 1's own grounded output), not raw transcript,
but the same shape problem applies: there is no `EvidenceItem.value` structure to check a persona
profile against, only prose. So, exactly as `summarize.py` does for a transcript, every numeric token
already present in the assembled notes text is minted into one `EvidenceItem` via
`app.agentdesk.grounding.numeric_tokens` -- the same function `check()` runs over the model's own
prose -- making the two sides of the gate symmetric by construction. See that module's docstring for
the full reasoning; it is not repeated here.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from app.agentdesk.grounding import numeric_tokens, run_grounded
from app.agentdesk.models import EvidenceItem, EvidencePack, EvidenceSection, GroundingVerdict
from app.agents.models import DEFAULT_MODEL, AgentBudget, AgentCall, AgentRole
from app.config import Settings
from app.personas.models import (
    EpisodicNote,
    PersonaProfile,
    ProfileClaim,
    RegimeView,
    TickerMention,
    TickerThesis,
)

__all__ = [
    "MAX_INPUT_CHARS",
    "ConsolidationResult",
    "ProfileDraft",
    "consolidate_notes",
]

_log = logging.getLogger(__name__)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# The model's output shape
# ---------------------------------------------------------------------------


class ProfileDraft(_Frozen):
    """What the model returns for one consolidation call, before citation filtering is applied.

    This is *not* `app.personas.models.PersonaProfile` -- it carries no `persona`/`version`/
    `consolidated_at`/`note_count`/`degraded`/`path`, none of the bookkeeping the caller (the
    `profile_store` module, owned by another worker) attaches once a profile is actually persisted.
    It is the model's structured answer and nothing else, mirroring `app.personas.summarize.NoteDraft`
    one level up the pipeline.
    """

    summary: str
    """Who this person is and what they trade, 2-4 sentences, in `Settings.persona_summary_lang`."""

    beliefs: tuple[ProfileClaim, ...]
    """What they currently think the market -- or a specific theme -- is doing. Each entry cites the
    note_id(s) it was drawn from; see the module docstring for how an uncited or wrongly-cited entry
    is handled. Unfiltered as returned from `run_grounded` -- what `consolidate_notes` hands back on
    `ConsolidationResult.draft` has already had `_filter_claims` applied."""

    playbook: tuple[ProfileClaim, ...]
    """How they actually trade: setups, entries, sizing and risk habits that recur across notes. Same
    citation shape and filtering as `beliefs`. Deliberately not a list of specific ticker calls -- that
    is what the per-symbol `TickerThesis` objects are for, built separately and never by the model."""

    methodology: tuple[ProfileClaim, ...]
    """The mechanical toolkit -- HOW they trade, not what: named technical indicators (RSI, MACD,
    moving averages, Bollinger Bands, VWAP, ATR...), chart timeframes (daily/weekly/intraday), specific
    entry and exit triggers, stop-loss/take-profit/position-sizing/risk rules, and named tools or
    platforms. Distinct from `playbook` -- see `app.personas.models.PersonaProfile.methodology`'s own
    docstring for the exact boundary between the two. Same citation shape and filtering as `beliefs`
    and `playbook`. Empty, not invented, for a persona whose notes never discuss technique (a pure
    macro commentator) -- an empty toolkit is itself an honest signal, not a gap to fill."""

    vocabulary: tuple[str, ...]
    """Recurring terms, nicknames or phrases the speaker uses, kept verbatim in whichever language
    they used them -- never translated, mirroring `NoteDraft.quotes`'s own "never rewritten" rule."""

    regime: RegimeView = RegimeView()
    """The speaker's structured macro/regime posture -- the counterpart to `methodology` for a
    commentator with no mechanical toolkit. Defaulted so every existing caller/test that builds a
    `ProfileDraft` without naming this field keeps working unchanged. `citations` is filtered exactly
    like a `ProfileClaim`'s (see `_filter_claims` and the citation-validation step in
    `consolidate_notes`), and `has_signal` is only ever set True by that same step once the view has
    survived filtering with real content and at least one valid citation -- never trusted verbatim off
    the model, which could otherwise claim a signal with an unfiltered or bogus citation list."""


@dataclass(frozen=True)
class ConsolidationResult:
    """What `consolidate_notes` hands back: the (citation-filtered) draft, the theses built from the
    same notes, the grounding verdict that released the draft, and the full cost accounting."""

    draft: ProfileDraft
    theses: tuple[TickerThesis, ...]
    """`path=""` on every entry -- the caller (`profile_store`, outside this shard) fills in the real
    vault-relative path once it decides where each thesis is written."""
    verdict: GroundingVerdict
    budget: AgentBudget
    calls: tuple[AgentCall, ...]


# ---------------------------------------------------------------------------
# Assembling the notes into one prompt
# ---------------------------------------------------------------------------

#: 20 notes is the owner's stated normal case (see `docs/INFLUENCER-CONTRACT.md`'s ingest default),
#: and each note is already a Phase 1 *summary* -- a few sentences, 2-5 themes, a handful of quotes --
#: not a raw transcript, so 20 of them comfortably fit well under this bound in the ordinary case.
#: 60,000 characters (the same bound `app.personas.summarize.MAX_SOURCE_CHARS` uses for a single raw
#: transcript) is chosen here too, generously oversized for the normal case, so truncation is the
#: exception reserved for a persona with an unusually large note count or unusually long summaries,
#: not something a routine consolidation run hits. A plain module constant, not a `Settings` field,
#: for the same reason `summarize.py`'s bound is: a prompt-engineering limit on one call, not
#: deployment configuration.
MAX_INPUT_CHARS = 60_000


def _note_timestamp(note: EpisodicNote) -> dt.datetime:
    """The instant a note is ordered by: its own `published` date when the upstream supplied one,
    else `ingested_at`. Never the other way around -- see `EpisodicNote.published`'s own docstring on
    why substituting `ingested_at` for a genuinely-unknown publish date would be a fabrication, not a
    fallback. Using it here as a pure *sort key* is different: nothing is written back onto the note,
    it only decides which of two notes this module treats as more recent when `published` cannot."""
    return note.published or note.ingested_at


def _sorted_newest_first(notes: Sequence[EpisodicNote]) -> tuple[EpisodicNote, ...]:
    """`notes`, ordered newest-first by `_note_timestamp`.

    The contract's own endpoints already return notes newest-first, but this module never assumes
    its caller preserved that order -- the task brief is explicit that "newest-stance-wins" and
    "prefer the newest notes when truncating" both require sorting defensively, not trusting the
    input order, and `sorted` is stable so two notes at the exact same timestamp keep their relative
    input order rather than shuffling nondeterministically between runs.
    """
    return tuple(sorted(notes, key=_note_timestamp, reverse=True))


def _render_note(note: EpisodicNote) -> str:
    """One note rendered into the block the model reads, tagged with its `note_id` so a citation can
    name it. Deliberately plain, labelled prose rather than JSON -- the model is asked to *write*
    JSON back (`ProfileDraft`), and mixing JSON-shaped input into a JSON-shaped output turn has no
    benefit and only risks the model echoing input structure into its answer."""
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


def _assemble_notes_text(notes: Sequence[EpisodicNote]) -> str:
    """The notes, newest-first, rendered and joined, capped at `MAX_INPUT_CHARS` with an explicit
    truncation marker -- never a silent drop.

    Truncates by dropping whole *notes* off the tail (the oldest ones), not by cutting mid-note the
    way `summarize._truncate` cuts mid-transcript: a note is already a short, self-contained block, so
    the natural unit to drop is one note at a time, keeping every note that does survive intact rather
    than handing the model a note cut off mid-sentence. At least one note -- the newest -- is always
    included even if it alone exceeds the bound, since a consolidation over zero notes is meaningless
    (and `consolidate_notes` refuses an empty `notes` sequence before this function is ever called).
    """
    ordered = _sorted_newest_first(notes)
    included: list[str] = []
    total = 0
    for note in ordered:
        block = _render_note(note)
        if included and total + len(block) > MAX_INPUT_CHARS:
            break
        included.append(block)
        total += len(block)

    text = "\n\n".join(included)
    omitted = len(ordered) - len(included)
    if omitted:
        text += f"\n\n...[TRUNCATED -- {omitted} older note(s) omitted here]...\n"
    return text


# ---------------------------------------------------------------------------
# Evidence pack -- same shape as `summarize.py`'s, over the assembled notes text
# ---------------------------------------------------------------------------


def _build_evidence_pack(notes_text: str) -> EvidencePack:
    """One `EvidencePack` whose single section carries the assembled (possibly truncated) notes text
    verbatim as free `text`, plus one `EvidenceItem` per distinct numeric token it contains -- see the
    module docstring, and `app.personas.summarize._build_evidence_pack`'s own longer explanation of
    why the items, not the text, are what makes a number "grounded"."""
    tokens = sorted(set(numeric_tokens(notes_text)))
    items = tuple(
        EvidenceItem(key=f"note_figure_{i}", label="Number stated across the notes", value=token)
        for i, token in enumerate(tokens)
    )
    section = EvidenceSection(title="Episodic notes", items=items, text=notes_text)
    return EvidencePack(sections=(section,))


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

#: See `app.personas.summarize._ROLE`'s own docstring for why this feature's calls archive under the
#: `AgentRole` Literal's `"swarm_worker"` member rather than a persona-specific one -- the same
#: reasoning applies unchanged to a consolidation call.
_ROLE: AgentRole = "swarm_worker"

_SYSTEM_PROMPT = """You are a research-notes assistant. You read a financial-market influencer's own \
accumulated episodic notes -- each one a structured summary of a video or post they previously \
published -- and fold them into ONE consolidated persona profile: who this person is, what they \
currently believe about markets, and how they actually trade. You never add your own market opinion, \
forecast, price target, or recommendation anywhere in your output. Your job is to describe what THIS \
PERSON believes and does, never to state a view as ours.

CITATIONS. Every entry of `beliefs`, every entry of `playbook`, and every entry of `methodology` is a \
claim with a `text` and a `citations` list. `citations` MUST contain one or more of the exact \
`note_id` values given to you below, copied verbatim, and MUST NEVER be left empty. Cite every \
note_id whose content actually supports the claim; do not cite a note_id whose content is unrelated \
to it, and never invent a note_id that was not given to you below -- a claim you cannot trace to at \
least one given note_id must simply not appear in your answer, rather than being included with a \
made-up or missing citation.

SUMMARY. 2-4 sentences on who this influencer is and what they trade, in {lang}.

BELIEFS. What they currently think the market -- or a specific theme, sector, or trend -- is doing: \
their macro read, their read on where a trend is headed. Each entry in {lang}, cited per the rule \
above.

PLAYBOOK. Their strategic approach to trading -- WHAT they do: the kinds of setups or opportunities \
they look for, their general philosophy on when to get in or out, and how they think about \
conviction and risk at a strategic level. Each entry in {lang}, cited per the rule above. Do NOT use \
this section to restate individual ticker calls -- those are handled separately, outside your output; \
write about their general trading behaviour instead. Do NOT use this section for the specific \
mechanical toolkit they use -- that belongs in METHODOLOGY below.

METHODOLOGY. Their mechanical toolkit -- HOW they trade, distinct from the strategic PLAYBOOK above: \
named technical indicators they reference (e.g. RSI, MACD, moving averages, Bollinger Bands, VWAP, \
ATR), the chart timeframes they use (daily, weekly, intraday), specific entry and exit triggers, \
stop-loss / take-profit / position-sizing / risk-management rules, and any tools or trading platforms \
they name. Each entry in {lang}, cited per the rule above. If the notes never discuss technique -- a \
pure macro commentator with no described toolkit -- return an empty list rather than inventing one; \
an empty methodology is itself an honest signal, not a gap to fill.

VOCABULARY. Recurring terms, nicknames, or phrases THEY use -- keep every entry verbatim in the \
language they actually used it, never translated and never invented.

REGIME. The speaker's structured macro/regime posture -- their overall market stance, distinct from \
the per-theme BELIEFS above. Fill in: `risk` (one of "on", "off", "mixed", or "unclear" -- their \
overall risk-on/risk-off read), `rates` (a one-line view on interest rates/monetary policy, or empty \
if they never address it), `summary` (a short summary of their macro stance, in {lang}, or empty), \
`sectors_favoured` and `sectors_avoided` (sectors or themes they are positive or negative on, or empty \
tuples), and `citations` (the exact note_id values that support this view, same rule as every other \
section -- non-empty whenever any of the above fields is non-empty). Set `has_signal` to true only \
when you have an actual, citable macro view to report. For a purely technical trader who never offers \
a macro opinion -- someone who only discusses chart setups, indicators, and individual ticker calls -- \
set `has_signal` to false and leave every other REGIME field empty or default; do not invent a macro \
stance to fill this section, the same honest-empty discipline METHODOLOGY uses for a trader with no \
described toolkit.

NUMBERS. State a number -- a price, a level, a percentage, a count, a date -- only when it is \
actually present in the notes below. Never estimate one, round it to a plausible-sounding figure, or \
supply a number the notes do not contain.

If the notes below do not support a whole section (for example, no consistent playbook or \
methodology is visible), return that section as an empty list rather than inventing content to fill \
it.

Respond with only the fields the schema asks for -- no extra commentary before or after."""

#: Appended to `_SYSTEM_PROMPT` only when `consolidate_notes` is given a `prior_profile` -- see that
#: function's own docstring and the module-level "Incremental consolidation" section below for why
#: this is additive rather than a fork of the base prompt: the base instructions (citation discipline,
#: section boundaries, honest-empty rules) apply unchanged either way, this only adds the merge task.
_INCREMENTAL_SYSTEM_ADDENDUM = """

INCREMENTAL UPDATE. This persona already has a STANDING profile, given to you below in the user \
turn, built from notes seen in earlier consolidation runs. Some of those earlier note_ids may not be \
among the notes given to you in THIS call -- they remain valid citations for any standing claim you \
keep, since they were real notes seen previously, just not repeated here. Do not start over from \
scratch: return the UPDATED WHOLE profile (every field, not a diff), folding the new notes into the \
standing view. For every existing belief, playbook entry, methodology entry, and the regime view: \
keep it -- re-citing whichever note_ids (old or new) actually support it -- when the new notes do not \
contradict it; update or drop it when the new notes contradict or supersede it; and add any genuinely \
new claim the new notes introduce. Do the same for `vocabulary`: keep recurring terms still in use, \
add new ones, drop ones that no longer appear. Every citation you return, in every section, must \
still be one of the exact note_id values given to you -- either in the standing profile below or in \
the new notes -- and never one you invent."""


def _prior_cited_ids(profile: PersonaProfile) -> frozenset[str]:
    """Every `note_id` already cited anywhere in `profile` -- beliefs, playbook, methodology, and the
    regime view. Folded into `consolidate_notes`'s valid-id set for an incremental run so a claim the
    model chooses to keep, citing an older note not among this call's `notes`, is not dropped as if it
    were a hallucination -- see that function's own docstring."""
    ids: set[str] = set()
    for claim in (*profile.beliefs, *profile.playbook, *profile.methodology):
        ids.update(claim.citations)
    ids.update(profile.regime.citations if profile.regime is not None else ())
    return frozenset(ids)


def _render_prior_claims(title: str, claims: tuple[ProfileClaim, ...]) -> list[str]:
    if not claims:
        return []
    lines = [f"{title}:"]
    lines.extend(f"- {claim.text} [cites: {', '.join(claim.citations)}]" for claim in claims)
    return lines


def _render_prior_profile(profile: PersonaProfile) -> str:
    """The standing profile, rendered into the block the model reads alongside the new notes, each
    existing claim tagged with the note_id(s) it was previously cited to -- mirroring `_render_note`'s
    own "tag everything the model might need to cite" shape, one level up the pipeline."""
    lines = [f"Existing summary: {profile.summary}"] if profile.summary else []
    lines.extend(_render_prior_claims("Existing beliefs", profile.beliefs))
    lines.extend(_render_prior_claims("Existing playbook", profile.playbook))
    lines.extend(_render_prior_claims("Existing methodology", profile.methodology))
    if profile.regime is not None and profile.regime.citations:
        regime = profile.regime
        lines.append(
            "Existing regime: risk="
            f"{regime.risk}; rates={regime.rates!r}; summary={regime.summary!r}; "
            f"sectors_favoured={list(regime.sectors_favoured)}; "
            f"sectors_avoided={list(regime.sectors_avoided)} [cites: {', '.join(regime.citations)}]"
        )
    if profile.vocabulary:
        lines.append(f"Existing vocabulary: {', '.join(profile.vocabulary)}")
    return "\n".join(lines)


def _build_user_prompt(
    *, persona_slug: str, notes_text: str, summary_lang: str, prior_profile: PersonaProfile | None = None,
) -> str:
    """The user turn: the persona's own notes, newest first, each tagged with its `note_id` for the
    model to cite -- see `_render_note`. When `prior_profile` is given, the standing profile is
    rendered ahead of the new notes (see `_render_prior_profile`) and the closing instruction asks for
    the merged whole rather than a from-scratch consolidation."""
    prior_block = (
        (
            "Below is this persona's EXISTING standing profile from earlier consolidation runs, "
            "followed by the new notes to fold into it.\n"
            "\n"
            "--- STANDING PROFILE START ---\n"
            f"{_render_prior_profile(prior_profile)}\n"
            "--- STANDING PROFILE END ---\n"
            "\n"
        )
        if prior_profile is not None
        else ""
    )
    instruction = (
        "Fold these new notes into the standing profile above, returning the updated whole profile."
        if prior_profile is not None
        else "Consolidate these notes into a persona profile."
    )
    return (
        f"Persona: {persona_slug}\n"
        f"{prior_block}"
        "Below are this persona's own episodic notes, newest first. Each is tagged with its note_id; "
        "cite ONLY these exact note_id values (plus, if a standing profile is given above, any "
        "note_id cited there) in your `citations` fields.\n"
        "\n"
        "--- NOTES START ---\n"
        f"{notes_text}\n"
        "--- NOTES END ---\n"
        "\n"
        f"{instruction} Write `summary` and every `beliefs`/`playbook`/`methodology`/`regime` entry "
        f"in {summary_lang}. Keep every `vocabulary` entry verbatim, in whatever language the speaker "
        "actually used it."
    )


def _draft_prose(draft: ProfileDraft) -> str:
    """The text `run_grounded` checks for ungrounded numbers: `summary` plus every belief's,
    playbook's, and methodology entry's `text`, joined. Methodology is folded in here for the same
    reason beliefs and playbook are: a fabricated price level or size (an invented "stop-loss at
    145.50" or "risks 2.5% of the account per trade") is exactly the kind of confident-sounding number
    this gate exists to catch, and it would slip through untested if this were the one section
    excluded. (An indicator's own window/period, like the `14` in `RSI(14)` or `14-day`, is a labelled
    parameter rather than a measurement and `numeric_tokens` already exempts it everywhere it appears
    -- see that function's own docstring -- so this fold does not change how those are treated; it only
    ensures a genuinely reported figure inside a methodology claim is checked exactly like one inside a
    belief or playbook claim.) Deliberately excludes `citations` (not prose) and `vocabulary` -- a
    vocabulary entry is a verbatim
    recurring term, not a composed sentence, and running it back through the numeric-token check would
    only risk degrading the stage over a term that happens to contain a digit (a fund name, a channel
    handle) rather than a stated fact, the same reasoning `summarize._draft_prose` already applies to
    excluding verbatim `quotes`.

    `regime`'s textual fields (`rates`, `summary`, `sectors_favoured`, `sectors_avoided`) are folded in
    for the same reason `methodology` is: a fabricated rate level or an invented favoured/avoided
    sector is exactly the kind of confident-sounding claim this gate exists to catch, and `regime` is
    otherwise a second, parallel place free-form prose could hide an ungrounded number. `regime.risk`
    (a closed `Literal`) and `regime.citations` are excluded, same as any other section's citations."""
    parts = [
        draft.summary,
        *(c.text for c in draft.beliefs),
        *(c.text for c in draft.playbook),
        *(c.text for c in draft.methodology),
        draft.regime.rates,
        draft.regime.summary,
        *draft.regime.sectors_favoured,
        *draft.regime.sectors_avoided,
    ]
    return "\n".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# Citation filtering -- ours to enforce, never the model's to self-police
# ---------------------------------------------------------------------------


def _filter_claims(
    claims: tuple[ProfileClaim, ...],
    valid_note_ids: frozenset[str],
    *,
    persona_slug: str,
    section: str,
) -> tuple[ProfileClaim, ...]:
    """Drop every claim that cites so much as one `note_id` outside `valid_note_ids`; never repair one.

    A claim is dropped *whole*, not edited down to its valid citations, even when it cites a mix of
    real and invented ids. Silently stripping the bad id and keeping the claim would still publish a
    statement the model partly could not back up, under a citation list that now looks entirely clean
    -- exactly the kind of drift this phase exists to prevent (see the module docstring). A claim with
    at least one bad citation is treated the same as one with none: worse than absent.

    Every drop is logged, not silently discarded, mirroring `app.personas.summarize._validate_mentions`
    -- there is no `GroundingIssue.kind` for "the model cited a note_id it never saw" (that closed
    `Literal` lives on the pinned `app.agentdesk.models` and is not this module's to widen), so a
    module-level logger is the record of what was dropped and why.
    """
    kept: list[ProfileClaim] = []
    dropped: list[ProfileClaim] = []
    for claim in claims:
        if all(note_id in valid_note_ids for note_id in claim.citations):
            kept.append(claim)
        else:
            dropped.append(claim)
    if dropped:
        detail = "; ".join(f"{claim.text!r} cites {claim.citations}" for claim in dropped)
        _log.warning(
            "consolidate_notes(%s): dropped %d %s claim(s) citing a note_id outside the input set: %s",
            persona_slug, len(dropped), section, detail,
        )
    return tuple(kept)


def _filter_regime(
    regime: RegimeView, valid_note_ids: frozenset[str], *, persona_slug: str,
) -> RegimeView:
    """Validate `regime.citations` against `valid_note_ids`, extending `_filter_claims`'s approach to
    the single structured `RegimeView` rather than a list of claims: an individual citation outside the
    valid set is dropped from the tuple (there is no sibling claim to drop *instead*, the way a bad
    citation drops a whole `ProfileClaim`), and every drop is logged for the same reason `_filter_claims`
    logs its drops.

    `has_signal` is never trusted as the model returned it -- it is recomputed here, true only when the
    view still has real content (`risk` set to something other than the "unclear" default, or `rates`/
    `summary`/`sectors_favoured`/`sectors_avoided` non-empty) AND at least one citation survived
    filtering. A view that claims a signal on the strength of a citation this function just dropped is
    exactly the drift the citation-filtering step exists to prevent -- see the module docstring.
    """
    kept_citations = tuple(nid for nid in regime.citations if nid in valid_note_ids)
    dropped = tuple(nid for nid in regime.citations if nid not in valid_note_ids)
    if dropped:
        _log.warning(
            "consolidate_notes(%s): dropped %d regime citation(s) outside the input set: %s",
            persona_slug, len(dropped), dropped,
        )
    has_content = bool(
        regime.risk != "unclear"
        or regime.rates
        or regime.summary
        or regime.sectors_favoured
        or regime.sectors_avoided
    )
    has_signal = bool(has_content and kept_citations)
    return regime.model_copy(update={"citations": kept_citations, "has_signal": has_signal})


# ---------------------------------------------------------------------------
# Per-symbol theses -- built deterministically in Python, never by the model
# ---------------------------------------------------------------------------


def _build_theses(persona_slug: str, notes: Sequence[EpisodicNote]) -> tuple[TickerThesis, ...]:
    """One `TickerThesis` per symbol any note mentions, folded from the notes' own `mentions` --
    never asked of the model. See the module docstring for why: this is a plain fold over structured
    data the notes already carry, and a model has nothing to add to "which mention is newest" that
    Python does not already get right, every time, for free.

    `stance` is the stance from the single most recent note that named the symbol -- notes are sorted
    defensively newest-first here (never assumed to already be in that order, per the task brief), so
    the first mention encountered per symbol is the winner. `claims` is one `ProfileClaim` per note
    that named the symbol with a non-empty `reasoning` (a mention with blank reasoning contributes to
    the stance fold but not to the claim list -- an empty-text claim would carry no information and
    would still need to satisfy the model's non-empty-citations rule for nothing in return), each
    citing that single note -- always a real, non-empty citation, since it is drawn straight from the
    note that produced it and never invented.

    Returned sorted by `symbol`, purely so the result is deterministic and easy to assert on in tests
    and stable to serve from an endpoint; the contract does not otherwise order `TickerThesis[]`.
    """
    ordered = _sorted_newest_first(notes)
    by_symbol: dict[str, list[tuple[EpisodicNote, TickerMention]]] = {}
    for note in ordered:
        for mention in note.mentions:
            by_symbol.setdefault(mention.symbol, []).append((note, mention))

    theses: list[TickerThesis] = []
    for symbol, pairs in by_symbol.items():
        newest_note, newest_mention = pairs[0]
        claims = tuple(
            ProfileClaim(text=mention.reasoning, citations=(note.note_id,))
            for note, mention in pairs
            if mention.reasoning.strip()
        )
        theses.append(
            TickerThesis(
                persona=persona_slug,
                symbol=symbol,
                stance=newest_mention.stance,
                updated_at=_note_timestamp(newest_note),
                claims=claims,
                path="",
            )
        )
    return tuple(sorted(theses, key=lambda thesis: thesis.symbol))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def consolidate_notes(
    *,
    persona_slug: str,
    notes: Sequence[EpisodicNote],
    settings: Settings,
    budget: AgentBudget,
    model: str = DEFAULT_MODEL,
    prior_profile: PersonaProfile | None = None,
) -> ConsolidationResult:
    """Consolidate `notes` into a `ProfileDraft` (one grounded model call) plus per-symbol
    `TickerThesis` objects (built in Python, no model call).

    Raises `ValueError` when `notes` is empty -- there is nothing to consolidate, and a caller (the
    `/consolidate` endpoint, per `docs/INFLUENCER-CONTRACT.md`) is expected to have checked
    `note_count` before ever reaching this function; returning an empty profile instead would let a
    persona with zero ingested items acquire a `profile.md` that describes nothing.

    **Never raises for a grounding failure.** Exactly as `app.personas.summarize.summarize_item`
    documents for the same reason: `run_grounded` returns `verdict.ok=False, verdict.degraded=True`
    on a stage that still fails its check on the last attempt, carrying whatever the model actually
    produced, and that is passed through on `ConsolidationResult.verdict` unchanged.
    `AgentUnavailable` (no credential, a refusal) and `BudgetExhausted` (the run's spend ceiling) are
    not grounding outcomes -- they mean the call could not be attempted or completed at all -- and
    `run_grounded` raises both unchanged; this function does not catch either, so they propagate to
    the caller exactly as documented there.

    Citation filtering (`_filter_claims`/`_filter_regime`) always runs, even on a degraded draft: a
    draft released with unverified prose is still not licence to carry a fabricated citation into the
    vault.

    **Incremental consolidation.** `prior_profile`, when given, is the persona's current standing
    `PersonaProfile` -- its existing beliefs/playbook/methodology/regime are rendered into the prompt
    (see `_render_prior_profile`) and the model is asked to fold `notes` into that standing view and
    return the updated whole, rather than consolidate `notes` alone as if nothing came before. This
    function does not decide which notes `notes` contains (only-new-since-last-run vs the full vault);
    that choice belongs to the caller. When `prior_profile` is `None`, every prompt and the valid-id
    set are exactly what they were before this parameter existed -- no incremental behaviour is
    possible to trigger by accident.

    The valid-citation set for this call is `notes`' own ids UNIONED with every note_id already cited
    anywhere in `prior_profile` (see `_prior_cited_ids`) -- so a claim the model keeps unchanged,
    citing an older note that is not part of THIS call's `notes`, is not misidentified as a
    hallucination and dropped. Without this union, every incremental run would silently erode the
    standing profile: each kept-but-not-rechecked claim would lose its citation and be filtered out,
    regardless of how genuinely it was seen in an earlier run.
    """
    if not notes:
        raise ValueError("consolidate_notes requires at least one note")

    notes_text = _assemble_notes_text(notes)
    pack = _build_evidence_pack(notes_text)
    summary_lang = settings.persona_summary_lang or "en"

    system = _SYSTEM_PROMPT.format(lang=summary_lang)
    if prior_profile is not None:
        system += _INCREMENTAL_SYSTEM_ADDENDUM
    user = _build_user_prompt(
        persona_slug=persona_slug,
        notes_text=notes_text,
        summary_lang=summary_lang,
        prior_profile=prior_profile,
    )

    grounded = run_grounded(
        role=_ROLE,
        system=system,
        user=user,
        output_format=ProfileDraft,
        prose_of=_draft_prose,
        pack=pack,
        settings=settings,
        budget=budget,
        model=model,
    )

    prior_ids = _prior_cited_ids(prior_profile) if prior_profile is not None else frozenset()
    valid_note_ids = frozenset(note.note_id for note in notes) | prior_ids
    filtered_beliefs = _filter_claims(
        grounded.value.beliefs, valid_note_ids, persona_slug=persona_slug, section="belief",
    )
    filtered_playbook = _filter_claims(
        grounded.value.playbook, valid_note_ids, persona_slug=persona_slug, section="playbook",
    )
    filtered_methodology = _filter_claims(
        grounded.value.methodology, valid_note_ids, persona_slug=persona_slug, section="methodology",
    )
    filtered_regime = _filter_regime(grounded.value.regime, valid_note_ids, persona_slug=persona_slug)
    draft = grounded.value.model_copy(
        update={
            "beliefs": filtered_beliefs,
            "playbook": filtered_playbook,
            "methodology": filtered_methodology,
            "regime": filtered_regime,
        }
    )

    theses = _build_theses(persona_slug, notes)

    return ConsolidationResult(
        draft=draft, theses=theses, verdict=grounded.verdict, budget=grounded.budget, calls=grounded.calls,
    )
