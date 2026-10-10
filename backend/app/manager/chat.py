"""Multi-turn conversation with the manager -- Phase 3 of the manager desk. See
`docs/MANAGER-DESK-PLAN.md` section 2.3 ("Chat") for the pinned wire contract this module implements;
the semantics below restate it, they do not vary it.

**Why this is a fork of `app.personas.chat`, not a shared module.** The two chats share the same
*shape* of problem (a persisted thread, a per-turn call that folds prior turns into the prompt, a
citation-filtering discipline), which is why this module mirrors `ChatStore`/`chat_turn`/
`MAX_HISTORY_TURNS` structurally. But the *evidence* is entirely different: persona chat grounds in one
influencer's own profile and notes; this grounds in the whole app's own state
(`app.manager.evidence.build_pack` over a `ManagerSnapshot` + `ChangeSet`), and citations here are typed
`SourceRef`s (`"kind:id"`) rather than bare `note_id` strings. A shared module would have to abstract
over both differences at once for no real reuse -- the same reasoning `app.personas.chat`'s own
docstring gives for not folding into `app.personas.ask`.

**The no-advice guarantee is structural, not just a prompt clause.** `_AnswerDraft`, the model's output
shape for this call, carries only `answer` and `citations` -- there is no field an instruction, a
stance, or a recommendation could land in, mirroring `app.manager.models.Synthesis`'s own "no field for
what the owner should do" design. The system prompt is the second half of the guarantee, restating the
same rule in words a model can act on; neither half is trusted alone.

**Why a degraded prior answer's text is excluded from the evidence pack, not just its numbers.** Exactly
`app.personas.chat`'s own reasoning: a number that failed the gate once must not launder itself into a
later turn's grounded set by riding along inside "earlier turns in this thread". The history block in
the *user prompt* still shows every prior turn, degraded or not (the model needs to know what it
actually said, in order, to hold a coherent conversation) -- only the evidence pack excludes a degraded
turn's answer, because only the evidence pack is what a later number gets checked against.

**Focus retrieval is deliberately simple, not a search index** -- same reasoning
`app.personas.ask`/`app.personas.chat` give for their own note retrieval: a lexical check ("does the
question name this area, or a term that appears in this area's own text") answers the question this
feature actually needs ("which parts of a fourteen-area snapshot is this question plausibly about") far
more predictably than a ranking model would, and keeps the narrowing auditable from the question text
alone.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.agentdesk.evidence import render_pack
from app.agentdesk.grounding import numeric_tokens, run_grounded
from app.agentdesk.models import EvidenceItem, EvidencePack, EvidenceSection
from app.agents.models import DEFAULT_MODEL, AgentBudget, AgentCall, AgentRole
from app.config import Settings
from app.manager.evidence import build_pack
from app.manager.models import (
    AREAS,
    ChangeSet,
    ManagerChatThread,
    ManagerChatTurn,
    ManagerSnapshot,
    SnapshotSection,
    SourceRef,
    chats_dir,
)

__all__ = [
    "MAX_HISTORY_TURNS",
    "ChatTurnResult",
    "ManagerChatStore",
    "chat_turn",
]

_log = logging.getLogger(__name__)

#: How many of a thread's most recent turns are folded into the prompt (both the visible history block
#: and, for the non-degraded ones, the evidence pack). Older turns are simply dropped, never
#: summarised -- see the module docstring, and `app.personas.chat.MAX_HISTORY_TURNS`'s own docstring for
#: why a summary would be uncited prose, exactly what this feature's citation discipline exists to avoid.
MAX_HISTORY_TURNS = 8


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class _AnswerDraft(_Frozen):
    """What the model returns for one chat call, before citation filtering is applied.

    Deliberately only `answer` and `citations` -- see the module docstring's "no-advice guarantee": there
    is no field on this schema an instruction, stance, or recommendation could occupy, which is the
    structural half of `chat_turn` never producing account advice.
    """

    answer: str
    """The manager's answer, grounded only in the snapshot/changes/history handed to the model."""

    citations: tuple[str, ...] = ()
    """`"kind:id"` `SourceRef` keys the answer drew on, unfiltered as returned -- `chat_turn` checks
    these against the refs actually placed in front of the model this turn before they ever reach the
    caller; see `_filter_citations`."""


@dataclass(frozen=True)
class ChatTurnResult:
    """What `chat_turn` hands back: the wire-ready `ManagerChatTurn` plus every `AgentCall` the (single,
    at most `MAX_GROUNDING_ATTEMPTS`-times-retried) grounded call made, for the caller's own cost
    accounting -- mirrors `app.personas.chat.ChatTurnResult`'s own shape."""

    turn: ManagerChatTurn
    calls: tuple[AgentCall, ...]


# ---------------------------------------------------------------------------
# ManagerChatStore -- threads under data/agentdesk/manager/chats/
# ---------------------------------------------------------------------------


class ManagerChatStore:
    """Reads and writes `ManagerChatThread`s under `chats_dir(settings)/<thread_id>.json`.

    Stateless beyond `settings`, mirroring `app.personas.chat.ChatStore` -- every method resolves its
    own path from `chats_dir` on every call. Writes go through the same temp-file-then-`os.replace`
    technique that class uses, for the same reason: a same-directory staging file makes the replace
    atomic on both POSIX and Windows, so a concurrent reader (an HTTP handler serving
    `GET /api/manager/chats/{thread_id}` while a turn is being saved) never observes a half-written file.

    There is exactly one manager, so -- unlike the persona store, which is keyed by `slug` -- every
    thread lives in one flat directory; `thread_id` alone is enough to name a file.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _chats_dir(self) -> Path:
        return chats_dir(self._settings)

    def _thread_path(self, thread_id: str) -> Path:
        """`chats/<thread_id>.json`, or `ValueError` if that would not sit *directly* in the chats
        directory.

        The HTTP boundary (`app.api.manager.IdPath`) already refuses ids with separators or dot
        segments, so this is the defence-in-depth half -- the same shape
        `app.evolution.dossier._card_path_under` uses for genome ids and
        `app.agentdesk.models.run_dir` for run ids. It matters most for `delete_thread`, which
        unlinks whatever this names: before the boundary was constrained, a `thread_id` built from
        parent-directory segments named a `.json` file outside the chats tree. `resolve()` on both sides so
        `..`, a Windows backslash and a symlinked chats directory all collapse to a real location
        before the containment check.
        """
        directory = self._chats_dir()
        candidate = (directory / f"{thread_id}.json").resolve()
        if candidate.parent != directory.resolve():
            raise ValueError(f"thread id does not name a thread in this store: {thread_id!r}")
        return candidate

    def list_threads(self) -> tuple[ManagerChatThread, ...]:
        """Every readable thread, `turns=()` (the list endpoint's contract -- a thread's full content is
        a separate `load_thread` away), newest `updated_at` first.

        An unreadable file is logged and skipped, not raised -- the same choice
        `app.personas.chat.ChatStore.list_threads` makes for a bad thread file: one corrupt thread must
        not take down the whole chat list.
        """
        directory = self._chats_dir()
        if not directory.is_dir():
            return ()

        threads: list[ManagerChatThread] = []
        for path in sorted(directory.glob("*.json")):
            try:
                thread = ManagerChatThread.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                _log.warning("manager chat store: skipping unreadable thread %s: %s", path, exc)
                continue
            threads.append(thread.model_copy(update={"turns": ()}))

        threads.sort(key=lambda thread: thread.updated_at, reverse=True)
        return tuple(threads)

    def load_thread(self, thread_id: str) -> ManagerChatThread | None:
        """One thread by id, full turns included, or `None` if it does not exist or cannot be parsed --
        a direct lookup is allowed to say "not found" for a corrupt file, unlike `list_threads`, which
        has other threads to show and logs a warning instead.

        An id `_thread_path` rejects is "not found" too: a lookup that could never name a thread in
        this store has no other answer to give."""
        try:
            path = self._thread_path(thread_id)
        except ValueError:
            return None
        if not path.is_file():
            return None
        try:
            return ManagerChatThread.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _log.warning("manager chat store: could not read thread %r: %s", thread_id, exc)
            return None

    def save_thread(self, thread: ManagerChatThread) -> None:
        """Write the thread atomically, `model_dump_json` end to end -- the wire shape and the on-disk
        shape are the same shape, by construction, matching `app.personas.chat.ChatStore.save_thread`."""
        path = self._thread_path(thread.thread_id)
        _write_atomic(path, thread.model_dump_json(indent=2))

    def delete_thread(self, thread_id: str) -> bool:
        """Remove the thread's file. Returns whether it existed, rather than raising, for a `thread_id`
        that was never saved -- the same choice `app.personas.chat.ChatStore.delete_thread` makes.
        An id `_thread_path` rejects reads as "did not exist" for the same reason, and unlinks
        nothing."""
        try:
            path = self._thread_path(thread_id)
        except ValueError:
            return False
        if not path.is_file():
            return False
        path.unlink()
        return True


def _write_atomic(path: Path, content: str) -> None:
    """Copied from `app.personas.chat._write_atomic` (kept as a local copy rather than an import so this
    module does not reach into a sibling shard's private name -- the same reasoning that module's own
    docstring gives for its own local copy of `app.personas.store._write_atomic`). See that function's
    docstring for why a uuid-suffixed staging file plus `os.replace`, not a direct `Path.write_text`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f"{path.name}.{uuid.uuid4().hex}.tmp"
    staging.write_text(content, encoding="utf-8")
    os.replace(staging, path)


# ---------------------------------------------------------------------------
# Focus retrieval -- lexical, over the snapshot's own sections
# ---------------------------------------------------------------------------

#: Words too common to count as a meaningful term match on their own -- without this, a question like
#: "what is going on with my account" would match every section whose text happens to contain "with" or
#: "what". Area names and any word actually distinctive to a section (a ticker, a rule id, a persona
#: slug) survive this filter; this list exists only to suppress noise, not to be exhaustive.
_STOPWORDS: frozenset[str] = frozenset([
    "the", "a", "an", "is", "are", "was", "were", "do", "does", "did", "what", "how", "why", "when",
    "where", "who", "which", "should", "would", "could", "will", "can", "my", "me", "mine", "i", "in",
    "on", "at", "to", "of", "for", "and", "or", "it", "its", "this", "that", "with", "about", "any",
    "there", "here", "going", "happening", "tell", "show", "explain", "please", "you", "your", "yours",
    "we", "our", "ours", "has", "have", "had", "be", "been", "being", "not", "no", "yes", "so", "than",
    "then", "just", "like", "get", "gets", "got", "need", "needs",
])

#: Minimum word length counted as a candidate term match -- below this a word is either a stopword-sized
#: function word or too short to be distinctive (see `_STOPWORDS`'s own docstring).
_MIN_TERM_LEN = 3


def _section_haystack(section: SnapshotSection) -> str:
    """The lower-cased text of one `SnapshotSection` a term match is checked against: the section's own
    summary plus every row's label, id, and one-line text -- the same fields
    `app.manager.evidence._section_text` reads for the model's own prompt, so "a term appearing in that
    area's text" means exactly what the model itself is shown."""
    bits = [section.text]
    for item in section.items:
        bits.append(item.label)
        bits.append(item.id)
        bits.append(item.text)
    return " ".join(bits).lower()


def _focus_areas(question: str, snapshot: ManagerSnapshot) -> tuple[str, ...] | None:
    """The snapshot areas `question` is plausibly about, in `AREAS` order, or `None` when nothing
    matches (the caller then passes the whole snapshot to `build_pack`).

    An area matches when either is true:
      1. The question names the area -- its own key (`"paperdesk"`) or a space-separated reading of it
         (`"persona_books"` -> `"persona books"`) appears in the question, case-insensitively.
      2. The question contains a term of at least `_MIN_TERM_LEN` characters, not a stopword, that also
         appears in that section's own rendered text (`_section_haystack`) -- a ticker, a rule name, a
         persona slug, or any other word distinctive enough to name what the section is about.

    Only areas the snapshot actually collected (`section.ok`) can match -- there is nothing to narrow to
    in a section that failed to collect.
    """
    q_lower = question.lower()
    words = {w for w in re.findall(r"[A-Za-z0-9]+", question) if len(w) >= _MIN_TERM_LEN}
    candidate_words = {w.lower() for w in words if w.lower() not in _STOPWORDS}

    matched: list[str] = []
    for section in snapshot.sections:
        if not section.ok:
            continue
        area = section.key
        area_label = area.replace("_", " ")
        if area in q_lower or area_label in q_lower:
            matched.append(area)
            continue

        haystack = _section_haystack(section)
        if any(term in haystack for term in candidate_words):
            matched.append(area)

    if not matched:
        return None

    order = {area: i for i, area in enumerate(AREAS)}
    matched.sort(key=lambda area: order.get(area, len(AREAS)))
    return tuple(matched)


# ---------------------------------------------------------------------------
# Citations -- typed SourceRefs, keyed "kind:id"
# ---------------------------------------------------------------------------


def _collect_source_refs(
    snapshot: ManagerSnapshot, changes: ChangeSet, *, focus_areas: tuple[str, ...] | None,
) -> dict[str, SourceRef]:
    """Every `SourceRef` actually placed in front of the model this turn, keyed `"{kind}:{id}"` -- the
    exact citation-string shape `docs/MANAGER-DESK-PLAN.md` pins for the whole manager feature
    (`"run:<run_id>"`, `"note:<note_id>"`, ...). Drawn from precisely the same inputs `build_pack` turns
    into evidence -- the snapshot sections `focus_areas` keeps (`ok=True` only) and every `ChangeItem` --
    so a citation the model returns is valid exactly when it points at something the model was actually
    shown, never a ref narrowed away from this turn's pack or on a section that failed to collect.
    """
    refs: dict[str, SourceRef] = {}
    for section in snapshot.sections:
        if focus_areas is not None and section.key not in focus_areas:
            continue
        if not section.ok:
            continue
        for item in section.items:
            for ref in item.refs:
                refs[f"{ref.kind}:{ref.id}"] = ref
    for change in changes.items:
        for ref in change.source_refs:
            refs[f"{ref.kind}:{ref.id}"] = ref
    return refs


def _render_citation_catalog(refs: dict[str, SourceRef]) -> str:
    """The catalogue of citable ids rendered for the prompt -- one line per ref, its exact citation key
    followed by its own human label, so the model can both copy the id verbatim and understand what it
    names."""
    if not refs:
        return "(no citable source refs available this turn)"
    return "\n".join(f"- {key}: {ref.label}" for key, ref in refs.items())


def _filter_citations(citations: tuple[str, ...], refs: dict[str, SourceRef]) -> tuple[SourceRef, ...]:
    """`citations`, with every entry outside `refs` dropped -- never repaired, there being nothing to
    repair a bare id into. Mirrors `app.personas.chat._filter_citations`'s own reasoning: the check runs
    against the *actual* input ref set built this turn, never trusting the model's own list, because
    nothing stops a model from citing an id it invented outright. Returns the resolved `SourceRef`s
    themselves (deduplicated, first-seen order), the shape `ManagerChatTurn.source_refs` actually wants.

    Every drop is logged, not silently discarded, for the same reason `app.personas.chat._filter_citations`
    logs: there is no `GroundingIssue.kind` for "the model cited a ref it never saw" on the pinned
    `app.agentdesk.models`, so a module-level logger is the record of what was dropped and why.
    """
    dropped = [c for c in citations if c not in refs]
    if dropped:
        _log.warning(
            "manager chat_turn: dropped %d citation(s) outside this turn's source-ref catalog: %s",
            len(dropped), ", ".join(dropped),
        )

    kept: list[SourceRef] = []
    seen: set[str] = set()
    for c in citations:
        if c in refs and c not in seen:
            seen.add(c)
            kept.append(refs[c])
    return tuple(kept)


# ---------------------------------------------------------------------------
# History rendering -- mirrors app.personas.chat exactly
# ---------------------------------------------------------------------------


def _recent_history(thread: ManagerChatThread) -> tuple[ManagerChatTurn, ...]:
    """The last `MAX_HISTORY_TURNS` turns of `thread`, oldest of that window first -- the order a reader
    (and the model) replays a conversation in. Older turns are simply dropped; see the module docstring
    on why they are never summarised instead."""
    return thread.turns[-MAX_HISTORY_TURNS:]


def _render_history_block(history: Sequence[ManagerChatTurn]) -> str:
    """The visible "earlier turns" block for the user prompt: every turn in `history`, degraded or not,
    as `Q: ...` / `A: ...` pairs -- the model needs to know what it actually said, in order, to hold a
    coherent conversation, even a turn whose numbers did not pass the gate. Contrast
    `_render_history_evidence`, which is deliberately *not* symmetric with this."""
    if not history:
        return "(no earlier turns in this thread)"
    return "\n\n".join(f"Q: {turn.question}\nA: {turn.answer}" for turn in history)


def _render_history_evidence(history: Sequence[ManagerChatTurn]) -> str:
    """The evidence-pack text for "earlier in this thread": the concatenated `answer` text of every
    **non-degraded** turn in `history`, and nothing from a degraded one.

    This is the guardrail the module docstring names explicitly: a number that failed the grounding gate
    once (`turn.degraded=True`) must not become citable evidence for a *later* turn just because it sits
    in the thread's own history. Excluding it here, before `_numeric_evidence_items` ever mints a token
    out of it, is what makes that true. Empty when there is no non-degraded turn to draw on (including an
    empty thread), which the caller treats as "no earlier-in-thread section" (see `chat_turn` below).
    """
    kept = [turn.answer for turn in history if not turn.degraded]
    return "\n\n".join(kept)


def _numeric_evidence_items(text: str, *, key_prefix: str, label: str) -> tuple[EvidenceItem, ...]:
    """One `EvidenceItem` per distinct numeric token `text` contains -- the same trick
    `app.personas.ask._numeric_evidence_items` / `app.personas.chat` use to make a prose section
    symmetric with what the gate checks the model's own answer against: a number already stated in an
    earlier, non-degraded answer is legitimately citable evidence for this turn."""
    tokens = sorted(set(numeric_tokens(text)))
    return tuple(
        EvidenceItem(key=f"{key_prefix}_{i}", label=label, value=token) for i, token in enumerate(tokens)
    )


_HISTORY_SECTION_TITLE = "Earlier in this thread"


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

#: See `app.personas.chat._ROLE`'s own docstring for why every call this feature makes archives under
#: `AgentRole`'s `"swarm_worker"` member rather than a manager-specific one -- unchanged here.
_ROLE: AgentRole = "swarm_worker"

_SYSTEM_PROMPT = """You are the Manager Desk's assistant, answering a question about this investor's own \
whole application state -- account, tax, paper desk, persona books and traders, research pipeline, model \
desks, live decisions, personas, market, upcoming events, news, and data health -- using only the \
snapshot, the changes since the prior snapshot, and the earlier turns of this conversation handed to you \
below. You describe the current situation across these lenses. You are not a licensed financial advisor \
and nothing you write is financial advice: you never tell the reader what to buy, sell, hold, rebalance, \
or otherwise do with their account, you never give a price target, and you never offer a personal \
recommendation -- describe what the state and the changes actually show, and let the reader draw their \
own conclusions.

GROUNDING. Answer using ONLY the state, the changes, and the earlier turns of this conversation given to \
you below -- never your own outside knowledge of markets, companies, prices, or current events. Every \
number you state must appear in that material, or be a straightforward difference or percentage change \
computed directly from two figures that do; never estimate, round to a plausible-sounding figure, or \
otherwise invent one. If the material below simply does not address the question, say so plainly in \
`answer` rather than inventing an answer to fill the gap.

CITATIONS. Below is a catalogue of citable source refs, each tagged with an exact id in the form \
"kind:id". Your `citations` field must list every id whose content you actually drew on to write \
`answer`, copied verbatim from the catalogue. Never invent an id that is not shown to you, and never cite \
a ref whose content is unrelated to what you wrote. If nothing below actually bears on the question, \
leave `citations` empty rather than citing something unrelated.

NO ADVICE. Never phrase `answer` as an instruction, recommendation, or piece of advice about what the \
reader should do with their account or their money -- describe the situation only.

CONTINUITY. This is one turn in an ongoing conversation with the same reader. You may build on your own \
earlier answers in this thread, shown below, for tone and continuity -- but never contradict what you \
already said on the record there, and never treat an earlier turn as licence to invent a view or a number \
the state, changes, and earlier evidence do not themselves support.

Respond with only the fields the schema asks for -- no extra commentary before or after."""


def _build_user_prompt(
    *,
    question: str,
    history_text: str,
    pack: EvidencePack,
    citation_catalog: str,
    focus_areas: tuple[str, ...] | None,
) -> str:
    """The user turn: history, then the rendered evidence pack (state + changes + earlier-in-thread,
    exactly what `run_grounded` checks the answer against, via the shared
    `app.agentdesk.evidence.render_pack`), then the citation catalogue, then the new question."""
    parts = [
        f"--- EARLIER TURNS START ---\n{history_text}\n--- EARLIER TURNS END ---",
        f"--- APP STATE AND CHANGES START ---\n{render_pack(pack)}--- APP STATE AND CHANGES END ---",
        f"--- CITABLE SOURCE REFS START ---\n{citation_catalog}\n--- CITABLE SOURCE REFS END ---",
    ]
    if focus_areas:
        parts.append("Areas most relevant to this question: " + ", ".join(focus_areas))

    parts.append(f"New question: {question}")
    parts.append(
        "Answer the new question above per your instructions. Cite ONLY the exact \"kind:id\" values "
        "listed in the citable source refs section above."
    )
    return "\n\n".join(parts)


def _draft_prose(draft: _AnswerDraft) -> str:
    """The text `run_grounded` checks for ungrounded numbers: `answer` alone. `citations` is a list of
    ids, not prose, and can carry no numeric token worth checking, so including it would only risk a
    false rejection over structure the gate was never meant to read."""
    return draft.answer


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def chat_turn(
    *,
    thread: ManagerChatThread,
    question: str,
    snapshot: ManagerSnapshot,
    changes: ChangeSet,
    settings: Settings,
    budget: AgentBudget,
    model: str = DEFAULT_MODEL,
) -> ChatTurnResult:
    """Answer `question` as the next turn in `thread`, grounded in `snapshot`/`changes` (narrowed to the
    areas the question is plausibly about, see `_focus_areas`) plus the thread's own recent, non-degraded
    history.

    **Never raises for a grounding failure**, exactly as `app.personas.chat.chat_turn` documents for the
    same reason: `run_grounded` returns `verdict.ok=False, verdict.degraded=True` on a call that still
    fails its check on the last attempt, and that is passed through on the returned `ManagerChatTurn`
    unchanged. `AgentUnavailable`/`BudgetExhausted` are not grounding outcomes -- `run_grounded` raises
    both unchanged, and this function does not catch either.

    Does not itself check `thread`'s turn cap or spend cap, decide whether to re-collect a stale
    snapshot, propose a commission, or persist anything -- that policy is the service layer's job,
    matching how `app.personas.service.chat_turn` layers policy over `app.personas.chat.chat_turn`'s pure
    computation. `ManagerChatTurn.refreshed` is therefore always `False` here; a caller that re-collected
    before calling this function copies the returned turn with `refreshed=True` itself.
    """
    focus_areas = _focus_areas(question, snapshot)

    history = _recent_history(thread)
    history_text = _render_history_block(history)
    history_evidence_text = _render_history_evidence(history)

    pack = build_pack(snapshot, changes, focus_areas=focus_areas)
    if history_evidence_text:
        history_items = _numeric_evidence_items(
            history_evidence_text, key_prefix="history_figure",
            label="Number stated in an earlier answer this thread",
        )
        pack = pack.model_copy(
            update={
                "sections": (
                    *pack.sections,
                    EvidenceSection(
                        title=_HISTORY_SECTION_TITLE, items=history_items, text=history_evidence_text,
                    ),
                ),
            }
        )

    refs = _collect_source_refs(snapshot, changes, focus_areas=focus_areas)
    citation_catalog = _render_citation_catalog(refs)

    user = _build_user_prompt(
        question=question, history_text=history_text, pack=pack, citation_catalog=citation_catalog,
        focus_areas=focus_areas,
    )

    grounded = run_grounded(
        role=_ROLE,
        system=_SYSTEM_PROMPT,
        user=user,
        output_format=_AnswerDraft,
        prose_of=_draft_prose,
        pack=pack,
        settings=settings,
        budget=budget,
        model=model,
    )

    source_refs = _filter_citations(grounded.value.citations, refs)

    turn = ManagerChatTurn(
        turn_id=uuid.uuid4().hex,
        asked_at=dt.datetime.now(dt.UTC).isoformat(),
        question=question,
        answer=grounded.value.answer,
        source_refs=source_refs,
        commissions=(),
        refreshed=False,
        grounding=grounded.verdict,
        degraded=grounded.verdict.degraded,
        cost_usd=str(grounded.budget.spent_usd),
    )
    return ChatTurnResult(turn=turn, calls=grounded.calls)
