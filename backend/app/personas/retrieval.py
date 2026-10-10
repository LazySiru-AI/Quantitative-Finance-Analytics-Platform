"""Selects the episodic notes most relevant to a chat/ask question -- Phase 9 of the persona
feature. See `docs/INFLUENCER-CONTRACT.md`, "Phase 9 -- persona chat (pinned)", for the pinned
`select_notes` signature this module implements.

**Why relevance, not recency.** `app.personas.ask._select_notes` orders by recency (symbol-matching
notes first, then newest), which answers "what has this persona said lately". A chat question like
"which indicators do you use" or "how do you read the macro" needs the notes that actually discuss
that, wherever they fall in time. This module ranks by lexical overlap between the question and each
note's own text, so the strategy notes surface for a strategy question even when they are not the
most recent.

**Bilingual by construction.** Four of five seed channels are Korean. Latin text is tokenised as
lower-cased words with light stemming; Hangul is tokenised as character bigrams, so a question about
"볼린저밴드" overlaps a note that wrote "볼린저 밴드". Scoring is tf-idf over the persona's own notes --
no external dependency, no model call.

The ranker below implements exactly that: tf-idf over each note's own title/themes/summary/quotes/
mention-reasoning text, idf computed over the persona's own note set, a large additive boost for a
symbol match (preserving `app.personas.ask`'s symbol-first rule), and a moderate additive boost for
notes a profile claim cites when that claim's text overlaps the question. Recency breaks ties and is
the whole ranking when the question carries no informative tokens and no boost applies -- a tf-idf
score of 0 for every note, sorted with a recency tiebreak, is indistinguishable from pure recency.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from collections import Counter
from collections.abc import Sequence

from app.personas.models import EpisodicNote, PersonaProfile

__all__ = ["select_notes"]

#: Default cap on notes returned into one prompt (the contract names this bound).
DEFAULT_CAP = 16

#: Default character budget: the assembled sum of returned notes' summaries, a proxy for prompt size.
DEFAULT_CHAR_BUDGET = 40_000

#: Additive score boost for a note that mentions the asked-about symbol -- large enough that a
#: symbol-matching note always outranks a non-matching one, whatever its lexical score.
_SYMBOL_BOOST = 1_000_000.0

#: A run of Latin letters/digits -- tokenised as lower-cased, lightly-stemmed words.
_LATIN_RUN_RE = re.compile(r"[A-Za-z0-9]+")

#: A run of Hangul syllables/jamo -- tokenised as character bigrams (plus whole-word unigrams below).
_HANGUL_RUN_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]+")

_WORD_RE = re.compile(r"\S+")

#: Suffixes stripped for light English stemming, longest first so "reading" loses "ing" (not "s"
#: falsely from some other match). Only stripped when the remaining stem is still >= 3 chars.
_STEM_SUFFIXES = ("ing", "ed", "s")


def _note_timestamp(note: EpisodicNote) -> dt.datetime:
    """The instant a note is ordered by -- `published` when known, else `ingested_at`. Purely a sort
    key here (see `app.personas.ask._note_timestamp` for why substituting one for the other as *data*
    would be a fabrication but as an ordering key is not)."""
    return note.published or note.ingested_at


def _stem(word: str) -> str:
    for suffix in _STEM_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _is_hangul(ch: str) -> bool:
    code = ord(ch)
    return 0xAC00 <= code <= 0xD7A3 or 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F


def _tokenize(text: str) -> list[str]:
    """Bilingual tokeniser. Latin/ASCII runs become lower-cased, lightly-stemmed words (dropped below
    2 chars); Hangul runs become character bigrams AND whitespace-split whole-word unigrams, so a
    3-char query word overlaps a note that wrote the same word inside a longer phrase. Latin and
    Hangul runs inside the same string are tokenised independently, so mixed-language text loses
    nothing from either side."""
    if not text:
        return []
    tokens: list[str] = []
    for match in _LATIN_RUN_RE.finditer(text):
        word = match.group().lower()
        if len(word) < 2:
            continue
        tokens.append(_stem(word))
    for word_match in _WORD_RE.finditer(text):
        hangul_only = "".join(ch for ch in word_match.group() if _is_hangul(ch))
        if hangul_only:
            tokens.append(hangul_only)
    for run_match in _HANGUL_RUN_RE.finditer(text):
        run = run_match.group()
        for i in range(len(run) - 1):
            tokens.append(run[i : i + 2])
    return tokens


def _document_text(note: EpisodicNote) -> str:
    """Everything about a note that carries meaning for relevance ranking: title, themes, summary,
    quotes, and every ticker mention's reasoning. Excludes structural/identity fields (note_id, url,
    persona, ...) which say nothing about what the note is *about*."""
    parts: list[str] = []
    if note.title:
        parts.append(note.title)
    parts.extend(note.themes)
    parts.append(note.summary)
    parts.extend(note.quotes)
    parts.extend(mention.reasoning for mention in note.mentions)
    return "\n".join(parts)


def _profile_boost_note_ids(profile: PersonaProfile, question_terms: set[str]) -> set[str]:
    """note_ids cited by a profile claim (belief/playbook/methodology) or the regime view, but only
    when that claim's own text shares at least one token with the question -- an uncited-by-relevance
    claim citing half the vault would otherwise boost everything indiscriminately."""
    if not question_terms:
        return set()
    boosted: set[str] = set()
    claims = (*profile.beliefs, *profile.playbook, *profile.methodology)
    pairs: list[tuple[str, tuple[str, ...]]] = [(claim.text, claim.citations) for claim in claims]
    if profile.regime is not None:
        pairs.append((profile.regime.summary, profile.regime.citations))
    for text, citations in pairs:
        if question_terms & set(_tokenize(text)):
            boosted.update(citations)
    return boosted


def select_notes(
    notes: Sequence[EpisodicNote],
    question: str,
    *,
    symbol: str | None,
    profile: PersonaProfile | None,
    cap: int = DEFAULT_CAP,
    char_budget: int = DEFAULT_CHAR_BUDGET,
) -> tuple[EpisodicNote, ...]:
    """Notes most relevant to `question`, newest-as-tiebreak, capped by count AND assembled char
    budget. Never raises; falls back to pure recency when the question has no informative tokens (or
    every note scores 0 and neither boost applies -- a tf-idf tie sorted with a recency tiebreak reads
    identically to recency alone, so no separate fallback branch is needed). `symbol` is expected
    upper-cased by the caller (matching `TickerMention.symbol`).

    Scoring is tf-idf: idf is computed over this persona's own `notes`, tf is the raw count of a
    question term in a note's title+themes+summary+quotes+mention-reasoning text, and a note's score is
    the sum of `tf * idf` over the question's distinct terms. A symbol match adds a large constant
    (always wins); a profile-claim citation whose own claim text overlaps the question adds a moderate
    constant (`2 * max possible idf`).

    The `char_budget` is the running sum of `len(note.summary)` over the returned notes; once adding
    the next note would exceed it, selection stops -- but at least one note is always returned when
    any exist, so a single very long note never yields an empty context.
    """
    if not notes:
        return ()

    n = len(notes)
    doc_tokens: dict[str, Counter[str]] = {
        note.note_id: Counter(_tokenize(_document_text(note))) for note in notes
    }
    df: Counter[str] = Counter()
    for tokens in doc_tokens.values():
        df.update(tokens.keys())
    idf = {term: math.log((1 + n) / (1 + count)) + 1.0 for term, count in df.items()}
    #: The idf a term with df=0 (absent from every note) would get -- the theoretical ceiling, used to
    #: size the profile-citation boost without depending on any one term actually being present.
    max_idf = math.log(n + 1) + 1.0

    question_terms = set(_tokenize(question))

    symbol_matches: set[str] = set()
    if symbol is not None:
        symbol_matches = {
            note.note_id for note in notes if any(m.symbol == symbol for m in note.mentions)
        }

    profile_boosted: set[str] = set(_profile_boost_note_ids(profile, question_terms)) if profile else set()

    def _score(note: EpisodicNote) -> float:
        tokens = doc_tokens[note.note_id]
        total = sum(tokens.get(term, 0) * idf.get(term, 0.0) for term in question_terms)
        if note.note_id in symbol_matches:
            total += _SYMBOL_BOOST
        if note.note_id in profile_boosted:
            total += max_idf * 2
        return total

    ordered = sorted(notes, key=lambda note: (_score(note), _note_timestamp(note)), reverse=True)

    selected: list[EpisodicNote] = []
    used = 0
    for note in ordered[:cap]:
        cost = len(note.summary)
        if selected and used + cost > char_budget:
            break
        selected.append(note)
        used += cost
    return tuple(selected)
