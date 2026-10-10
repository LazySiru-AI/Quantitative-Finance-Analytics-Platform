"""Multi-turn conversation with one persona -- Phase 9 of the persona feature. See
`docs/INFLUENCER-CONTRACT.md`, "Phase 9 -- persona chat (pinned)", for the exact wire contract this
module implements; the semantics below restate it, they do not vary it.

**Why this is a second module, not a bigger `ask.py`.** `app.personas.ask` answers a single question
in isolation, with no persisted state. Chat needs a thread on disk (`ChatStore`) and a per-turn call
that folds prior turns into the prompt (`chat_turn`) -- a different write contract and a materially
different assembly step, the same reasoning `app.personas.profile_store` gives for splitting off from
`app.personas.store`. What this module deliberately does NOT do is re-derive grounding or citation
logic: `_render_profile`, `_render_note`, `_fetch_snapshot`, `_filter_citations`,
`_numeric_evidence_items` and `_draft_prose` are imported straight from `ask.py` and used unchanged,
because a second, slightly-different copy of "which numbers are allowed" is exactly the kind of drift
the grounding gate exists to prevent.

**Why a degraded prior answer's text is excluded from the evidence pack, not just its numbers.** A
number that failed the gate once must not launder itself into a later turn's grounded set by riding
along inside "earlier answers in this thread" -- see the module-level `_render_history_evidence`
docstring for the exact mechanics. The `history` block in the *user prompt* still shows every prior
turn, degraded or not (the model needs to know what it actually said, in order, to hold a coherent
conversation) -- only the *evidence pack* excludes degraded answers, because only the evidence pack
is what a later number gets checked against.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.agentdesk.grounding import run_grounded
from app.agentdesk.models import EvidenceItem, EvidencePack, EvidenceSection
from app.agents.models import DEFAULT_MODEL, AgentBudget, AgentCall, AgentRole
from app.config import Settings
from app.personas.ask import (
    _AnswerDraft,
    _draft_prose,
    _fetch_snapshot,
    _filter_citations,
    _numeric_evidence_items,
    _render_note,
    _render_profile,
)
from app.personas.models import (
    ChatLang,
    ChatThread,
    ChatTurn,
    EpisodicNote,
    PersonaProfile,
    Stance,
    persona_dir,
)
from app.personas.retrieval import select_notes  # patched as `chat.select_notes` in tests

__all__ = [
    "MAX_HISTORY_TURNS",
    "MAX_TURNS",
    "ChatStore",
    "ChatTurnResult",
    "chat_turn",
]

_log = logging.getLogger(__name__)

#: How many of a thread's most recent turns are folded into the prompt (both the visible history
#: block and, for the non-degraded ones, the evidence pack). Older turns are dropped outright, never
#: summarised -- see the module docstring on `ChatThread` in `app.personas.models` and the contract's
#: own "Turn assembly" rule: a summary is uncited prose, which is precisely what this feature's
#: citation discipline exists to avoid producing.
MAX_HISTORY_TURNS = 8

#: Hard ceiling on how many turns one thread may ever hold. `app.personas.service.chat_turn` enforces
#: this as a 409 before ever calling the model -- a thread is meant to be a bounded conversation, not
#: an unbounded log a UI has to page through forever.
MAX_TURNS = 40

_CHATS_DIRNAME = "chats"


@dataclass(frozen=True)
class ChatTurnResult:
    """What `chat_turn` hands back: the wire-ready `ChatTurn` plus every `AgentCall` the (single, at
    most `MAX_GROUNDING_ATTEMPTS`-times-retried) grounded call made, for the caller's own cost
    accounting -- mirrors `app.personas.ask.AskResult`'s own shape one level up."""

    turn: ChatTurn
    calls: tuple[AgentCall, ...]


# ---------------------------------------------------------------------------
# ChatStore -- persisted threads under <vault>/influencers/<slug>/chats/
# ---------------------------------------------------------------------------


class ChatStore:
    """Reads and writes `ChatThread`s under `<vault>/influencers/<slug>/chats/<thread_id>.json`.

    Stateless beyond `settings`, mirroring `app.personas.store.VaultStore` -- every method resolves
    its own path from `persona_dir` on every call. Writes go through the same temp-file-then-
    `os.replace` technique that module's `_write_atomic` uses, for the same reason: a same-directory
    staging file makes the replace atomic on both POSIX and Windows, so a concurrent reader (an HTTP
    handler serving `GET .../chats/{thread_id}` while a turn is being saved) never observes a
    half-written file.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _chats_dir(self, slug: str) -> Path:
        return persona_dir(self._settings, slug) / _CHATS_DIRNAME

    def _thread_path(self, slug: str, thread_id: str) -> Path:
        return self._chats_dir(slug) / f"{thread_id}.json"

    def list_threads(self, slug: str) -> tuple[ChatThread, ...]:
        """Every readable thread for `slug`, `turns=()` (the list endpoint's contract -- a thread's
        full content is a separate `load_thread` away), newest `updated_at` first.

        An unreadable file is logged and skipped, not raised -- the same choice
        `VaultStore.list_notes` makes for a bad note file: one corrupt thread must not take down the
        whole chat list.
        """
        directory = self._chats_dir(slug)
        if not directory.is_dir():
            return ()

        threads: list[ChatThread] = []
        for path in sorted(directory.glob("*.json")):
            try:
                thread = ChatThread.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                _log.warning("chat store: skipping unreadable thread %s: %s", path, exc)
                continue
            threads.append(thread.model_copy(update={"turns": ()}))

        threads.sort(key=lambda thread: thread.updated_at, reverse=True)
        return tuple(threads)

    def load_thread(self, slug: str, thread_id: str) -> ChatThread | None:
        """One thread by id, full turns included, or `None` if it does not exist or cannot be
        parsed -- a direct lookup is allowed to say "not found" for a corrupt file, unlike
        `list_threads`, which has other threads to show and logs a warning instead."""
        path = self._thread_path(slug, thread_id)
        if not path.is_file():
            return None
        try:
            return ChatThread.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _log.warning("chat store: could not read thread %r/%r: %s", slug, thread_id, exc)
            return None

    def save_thread(self, thread: ChatThread) -> None:
        """Write the thread atomically, `model_dump_json` end to end -- the wire shape and the
        on-disk shape are the same shape, by construction, matching `VaultStore.save_persona`."""
        path = self._thread_path(thread.persona, thread.thread_id)
        _write_atomic(path, thread.model_dump_json(indent=2))

    def delete_thread(self, slug: str, thread_id: str) -> bool:
        """Remove the thread's file. Returns whether it existed, rather than raising, for a
        thread_id that was never saved -- the same choice `VaultStore.delete_persona` makes."""
        path = self._thread_path(slug, thread_id)
        if not path.is_file():
            return False
        path.unlink()
        return True


def _write_atomic(path: Path, content: str) -> None:
    """Copied from `app.personas.store._write_atomic` (kept as a local copy rather than an import so
    this module does not reach into a sibling shard's private name -- the same reasoning
    `ask._note_timestamp`'s docstring gives for its own local copy). See that function's docstring
    for why a uuid-suffixed staging file plus `os.replace`, not a direct `Path.write_text`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f"{path.name}.{uuid.uuid4().hex}.tmp"
    staging.write_text(content, encoding="utf-8")
    os.replace(staging, path)


# ---------------------------------------------------------------------------
# History rendering
# ---------------------------------------------------------------------------


def _recent_history(thread: ChatThread) -> tuple[ChatTurn, ...]:
    """The last `MAX_HISTORY_TURNS` turns of `thread`, oldest of that window first -- the order a
    reader (and the model) replays a conversation in. Older turns are simply dropped; see the module
    docstring on why they are never summarised instead."""
    return thread.turns[-MAX_HISTORY_TURNS:]


def _render_history_block(history: Sequence[ChatTurn]) -> str:
    """The visible "earlier turns" block for the user prompt: every turn in `history`, degraded or
    not, as `Q: ...` / `A: ...` pairs -- the model needs to know what it actually said, in order, to
    hold a coherent conversation, even a turn whose numbers did not pass the gate. Contrast
    `_render_history_evidence`, which is deliberately *not* symmetric with this."""
    if not history:
        return "(no earlier turns in this thread)"
    return "\n\n".join(f"Q: {turn.question}\nA: {turn.answer}" for turn in history)


def _render_history_evidence(history: Sequence[ChatTurn]) -> str:
    """The evidence-pack text for "earlier answers in this thread": the concatenated `answer` text of
    every **non-degraded** turn in `history`, and nothing from a degraded one.

    This is the guardrail the contract names explicitly: a number that failed the grounding gate once
    (`turn.degraded=True`) must not become citable evidence for a *later* turn just because it sits in
    the thread's own history. Excluding it here, before `_numeric_evidence_items` ever mints a token
    out of it, is what makes that true -- an item that is never in the pack cannot be matched against a
    later answer's own numbers. Empty when there is no non-degraded turn to draw on (including an
    empty thread), which the caller treats as "no earlier-answers section" (see `chat_turn` below).
    """
    kept = [turn.answer for turn in history if not turn.degraded]
    return "\n\n".join(kept)


# ---------------------------------------------------------------------------
# Prompting -- Phase 4's system prompt plus a continuity clause
# ---------------------------------------------------------------------------

#: See `ask._ROLE`'s own docstring for why every call this feature makes archives under
#: `AgentRole`'s `"swarm_worker"` member rather than a persona-specific one -- unchanged here.
_ROLE: AgentRole = "swarm_worker"

_SYSTEM_PROMPT = """You are a model's impression of a financial-market influencer named {persona}, built \
entirely from their own recorded persona profile and episodic notes, given to you below. You are NOT \
{persona} -- you are a best-effort reconstruction of how they would likely respond, based only on what \
they are actually on record as believing and doing. You never add your own market opinion, forecast, \
price target, or recommendation, and you never invent a position, view, or fact {persona} did not \
actually express in the material below. You are not a licensed financial advisor and nothing you write \
is financial advice: never tell the reader what to buy, sell, hold, or otherwise do with their money -- \
describe what {persona} is on record thinking and doing, and let the reader draw their own conclusions.

GROUNDING. Answer using ONLY the persona profile, episodic notes, market snapshot, and earlier turns of \
this conversation given to you below -- never your own outside knowledge of markets, companies, prices, \
or current events. Every number you state must appear in that material, or be a straightforward \
difference or percentage change computed directly from two figures that do; never estimate, round to a \
plausible-sounding figure, or otherwise invent one. If the material below simply does not address the \
question, say so plainly in `answer` -- in {persona}'s voice, as in "I haven't said anything on record \
about that" -- rather than inventing a view to fill the gap.

CITATIONS. Every episodic note below is tagged with an exact `note_id`. Your `citations` field must \
list every `note_id` whose content you actually drew on to write `answer`, copied verbatim from the \
tags below. Never invent a `note_id` that is not shown to you, and never cite a note whose content is \
unrelated to what you wrote. If no note below actually bears on the question, leave `citations` empty \
rather than citing something unrelated.

{stance_instruction}

CONTINUITY. This is one turn in an ongoing conversation with the same reader. You may build on your own \
earlier answers in this thread, shown below, for tone and continuity -- but never contradict what you \
already said on the record there, and never treat an earlier turn as licence to invent a view or a \
number the profile, notes, and snapshot do not themselves support.

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


def _build_evidence_pack(
    *,
    symbol: str | None,
    profile_text: str | None,
    notes_text: str,
    snapshot_item: EvidenceItem | None,
    snapshot_text: str,
    history_evidence_text: str,
) -> EvidencePack:
    """One section per input the model was actually given, mirroring `ask._build_evidence_pack` plus
    the one section unique to chat: "Earlier answers in this thread", present only when at least one
    non-degraded prior turn exists (see `_render_history_evidence`)."""
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

    if history_evidence_text:
        history_items = _numeric_evidence_items(
            history_evidence_text, key_prefix="history_figure",
            label="Number stated in an earlier answer this thread",
        )
        sections.append(
            EvidenceSection(
                title="Earlier answers in this thread", items=history_items,
                text=history_evidence_text,
            )
        )

    return EvidencePack(symbol=symbol or "", sections=tuple(sections))


def _build_user_prompt(
    *,
    persona_slug: str,
    question: str,
    symbol: str | None,
    history_text: str,
    profile_text: str | None,
    notes_text: str,
    snapshot_text: str,
    summary_lang: str,
) -> str:
    """The user turn: history, then every section of context the model is allowed to draw on, in the
    same relative order `_build_evidence_pack` assembles them -- profile, notes, snapshot -- then the
    new question, mirroring `ask._build_user_prompt`'s own delimiting."""
    parts = [
        f"Persona: {persona_slug}",
        f"--- EARLIER TURNS START ---\n{history_text}\n--- EARLIER TURNS END ---",
    ]

    if profile_text is not None:
        parts.append(f"--- PERSONA PROFILE START ---\n{profile_text}\n--- PERSONA PROFILE END ---")

    parts.append(f"--- EPISODIC NOTES START ---\n{notes_text}\n--- EPISODIC NOTES END ---")

    if snapshot_text:
        parts.append(f"--- MARKET SNAPSHOT START ---\n{snapshot_text}\n--- MARKET SNAPSHOT END ---")

    parts.append(f"New question: {question}")
    if symbol:
        parts.append(f"Symbol asked about: {symbol}")

    parts.append(
        f"Answer the new question above in {summary_lang}, in {persona_slug}'s voice, per your "
        "instructions. Cite ONLY the exact note_id values tagged in the episodic notes section above."
    )
    return "\n\n".join(parts)


def _render_notes_text(notes: Sequence[EpisodicNote]) -> str:
    """Copied from `ask._render_notes_text` (same reasoning as `_write_atomic` above for why this is
    a local copy rather than an import of a private name)."""
    if not notes:
        return "(no episodic notes on record for this persona yet)"
    return "\n\n".join(_render_note(note) for note in notes)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def chat_turn(
    *,
    persona_slug: str,
    thread: ChatThread,
    question: str,
    symbol: str | None,
    lang: str,
    profile: PersonaProfile | None,
    notes: Sequence[EpisodicNote],
    settings: Settings,
    budget: AgentBudget,
    model: str = DEFAULT_MODEL,
) -> ChatTurnResult:
    """Answer `question` as the next turn in `thread`, grounded in `profile` (when consolidated), the
    notes `select_notes` ranks as most relevant to `question`/`symbol`, a market snapshot when
    `symbol` is given, and the thread's own recent, non-degraded history.

    **Never raises for a grounding failure**, exactly as `app.personas.ask.ask_persona` documents for
    the same reason: `run_grounded` returns `verdict.ok=False, verdict.degraded=True` on a call that
    still fails its check on the last attempt, and that is passed through on the returned `ChatTurn`
    unchanged. `AgentUnavailable`/`BudgetExhausted` are not grounding outcomes -- `run_grounded` raises
    both unchanged, and this function does not catch either.

    Does not itself check `thread`'s turn cap or spend cap, or persist anything -- that bookkeeping
    (and the 409s it produces) is `app.personas.service.chat_turn`'s job, matching how
    `app.personas.service.ask` layers policy over `ask_persona`'s pure computation.
    """
    symbol_norm = symbol.strip().upper() if symbol else None
    summary_lang: ChatLang = "ko" if lang == "ko" else "en"

    selected = select_notes(notes, question, symbol=symbol_norm, profile=profile)

    profile_text = _render_profile(profile) if profile is not None else None
    notes_text = _render_notes_text(selected)
    snapshot_item, snapshot_text = (
        _fetch_snapshot(symbol_norm, settings) if symbol_norm else (None, "")
    )

    history = _recent_history(thread)
    history_text = _render_history_block(history)
    history_evidence_text = _render_history_evidence(history)

    pack = _build_evidence_pack(
        symbol=symbol_norm, profile_text=profile_text, notes_text=notes_text,
        snapshot_item=snapshot_item, snapshot_text=snapshot_text,
        history_evidence_text=history_evidence_text,
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
        persona_slug=persona_slug, question=question, symbol=symbol_norm, history_text=history_text,
        profile_text=profile_text, notes_text=notes_text, snapshot_text=snapshot_text,
        summary_lang=summary_lang,
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

    valid_note_ids = frozenset(note.note_id for note in selected)
    citations = _filter_citations(grounded.value.citations, valid_note_ids, persona_slug=persona_slug)
    stance: Stance | None = grounded.value.stance if symbol_norm else None

    turn = ChatTurn(
        turn_id=uuid.uuid4().hex,
        asked_at=dt.datetime.now(dt.UTC),
        question=question,
        symbol=symbol_norm,
        lang=summary_lang,
        answer=grounded.value.answer,
        citations=citations,
        retrieved=tuple(note.note_id for note in selected),
        stance=stance,
        grounding=grounded.verdict,
        degraded=grounded.verdict.degraded,
        cost_usd=str(grounded.budget.spent_usd),
    )
    return ChatTurnResult(turn=turn, calls=grounded.calls)
