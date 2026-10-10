"""Take an external agent's pasted-back JSON reply, prove it against the transcript it was written
from, and persist it as an episodic note -- the second half of the manual backfill loop whose first
half is `app.personas.backfill`.

**Two guardrails, two dispositions on failure.** The in-house summariser (`app.personas.summarize`)
gets both for free: `run_grounded` re-prompts and finally degrades a model whose prose states numbers
the source never contained, and `_validate_mentions` drops any symbol the instrument table cannot
confirm. A reply pasted in from Gemini or ChatGPT has had neither applied -- it is untrusted input in
exactly the way a data provider's payload is. This module re-imposes both, matching the in-house
*shape* of each while treating the reply as untrusted:

* **Numbers -> HARD-REJECT.** A number in the reply's prose that is not grounded in the transcript is
  a fabrication, and an episodic note is immutable once written -- a fabricated price target can never
  be corrected, only deleted. There is nothing spent to salvage (unlike the in-house path, which
  degrades rather than pay for its verdict twice): the owner still has the packet, so the whole reply
  is refused and one more paste re-runs it. This is the one thing that fails a reply.
* **Tickers -> DROP-and-keep.** A `mention.symbol` the instrument table cannot confirm costs that one
  mention, exactly as `summarize._validate_mentions` drops it in-house -- never the whole note. A
  mangled caption word, or a real future/index the provider layer does not list (`GC`, `^GSPC`),
  must not discard an otherwise-faithful summary, themes, quotes and other mentions. `validate_result`
  names the dropped symbols; `ingest_result` writes the note without them. (This reverses an earlier,
  stricter reading: a live Gemini run showed real instruments dropped by the offline layers and real
  futures/indices the provider omits, so reject-the-whole-note punished faithful replies.)

**The number check is the in-house gate's own machinery, not a re-derivation.** `validate_result`
builds the transcript's `EvidencePack` with `summarize._build_evidence_pack` -- the same pack the
in-house call is grounded against -- and admits every figure in `app.agentdesk.grounding.
grounded_values(pack)`, which expands the stated figures with the differences, ratios and rounding the
real gate allows. A naive "every digit run in the reply must appear verbatim in the transcript" subset
would false-reject a faithful reply that restates a figure rounded, gives a `70/30` split, or a
`1% to 2%` range -- exactly the class `grounding-gate-false-rejections` documents. `numeric_tokens`
(the same extractor) already drops years, whole dates, ordinals, indicator windows and small integers,
so a reply is never rejected for saying "the 2024 filing" or "RSI(14)". Quotes are excluded from the
check (see `_result_prose`), matching `summarize._draft_prose`: a verbatim quote can only restate a
number already in the source, and re-checking it re-adds false rejects from caption spacing.

**What is deliberately NOT re-derived here.** The transcript is read back from the packet on disk
(`backfill.find_task_packet`), never re-fetched from YouTube: the packet holds the exact text the
external agent was actually shown, and a re-fetch could return a differently-segmented caption track,
which would have the grounding check answering a question about text nobody read. The note this
module writes records `summary_source="external"` so a reader can always tell it from one this
project produced and fact-checked itself -- `degraded=False` on such a note means "our gate never
ran", not "our gate passed".
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.agentdesk.grounding import grounded_values, numeric_tokens
from app.config import Settings
from app.personas.models import EpisodicNote, Horizon, Persona, Stance, TickerMention

__all__ = [
    "BackfillMention",
    "BackfillResult",
    "BackfillResultInvalid",
    "BackfillValidationFailed",
    "ValidationReport",
    "ingest_result",
    "parse_result",
    "validate_result",
]

logger = logging.getLogger(__name__)


class BackfillResultInvalid(ValueError):
    """The reply could not be read as the shape the packet asked for -- no JSON, unparseable JSON, or
    JSON whose fields are not what `BackfillResult` declares. A *shape* failure, distinct from
    `BackfillValidationFailed`: nothing about the content has been judged yet."""


class BackfillValidationFailed(ValueError):
    """The reply parsed fine and then stated a number the transcript never contained -- the one
    guardrail that fails a whole reply (an unvalidatable ticker is dropped, not rejected; see
    `validate_result`). `reasons` carries one human-readable line per failure so a CLI or an API can
    show the owner exactly what to fix without re-running the check."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__("; ".join(reasons) or "validation failed")
        self.reasons = reasons


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class BackfillMention(_Frozen):
    """One ticker the external agent says the speaker named, in the packet's own wire shape.

    Deliberately not `app.personas.models.TickerMention`: that model is what goes *into* the vault,
    and constructing one straight from untrusted JSON would put the validated type on unvalidated
    data. `ingest_result` converts to it only after `validate_result` has passed. `instrument` is
    absent here on purpose -- the packet never asks an external agent to classify an instrument, and
    `TickerMention`'s own default plus the deterministic `app.personas.instruments` pass are a better
    answer than a guess typed by a model that was not asked the question.
    """

    symbol: str
    stance: Stance
    horizon: Horizon = "unclear"
    reasoning: str = ""

    @field_validator("stance", "horizon", mode="before")
    @classmethod
    def _lower(cls, value: object) -> object:
        """Accept `"Bullish"`/`"LONG_TERM"`. Case is a presentational choice an external agent is
        free to make -- rejecting a reply over it would cost the owner a re-paste for nothing, and
        the value's *meaning* is unambiguous either way. Anything that is not a string is left alone
        so pydantic reports the real type error rather than an `AttributeError` from here."""
        if isinstance(value, str):
            return value.strip().lower()
        return value


class BackfillResult(_Frozen):
    """The whole reply: the `NoteDraft`-shaped object the packet's expected-output block asks for.

    `extra="forbid"` (inherited from `_Frozen`, the convention every model in this package follows) is
    what makes a reply that answered a *different* question a loud parse error rather than a note with
    silently-dropped content.
    """

    summary: str
    themes: tuple[str, ...]
    quotes: tuple[str, ...]
    mentions: tuple[BackfillMention, ...]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

#: A fenced ```json block, which is what the packet asks for verbatim ("exactly one fenced `json`
#: code block"). The fence may sit anywhere in the reply: agents routinely wrap it in a sentence of
#: preamble ("Here is the JSON you asked for:") and a sign-off, and refusing those would fail a reply
#: whose actual content is perfectly correct. Non-greedy so the *first* complete fence wins rather
#: than everything between the first opening and the last closing one.
_JSON_FENCE_RE = re.compile(r"```json\s*\n(?P<body>.*?)\n?```", re.DOTALL | re.IGNORECASE)

#: A bare fence with no language tag, tried only after the tagged one -- some agents drop the `json`
#: label. Same reasoning; still strictly a fenced block, so prose around it stays out of the JSON.
_BARE_FENCE_RE = re.compile(r"```\s*\n(?P<body>\{.*?\})\s*\n?```", re.DOTALL)


def parse_result(text: str) -> BackfillResult:
    """Read one external agent's reply into a `BackfillResult`.

    Accepts either a fenced ```json block anywhere in `text` (what the packet asks for, prose around
    it allowed) or bare JSON as the whole reply (what an agent set to "JSON mode" returns). Raises
    `BackfillResultInvalid`, with a reason a human can act on, for anything else: no JSON found,
    malformed JSON, or JSON whose shape is not the one the packet specified.

    Leniency is confined to presentation -- surrounding prose, trailing whitespace, the case of
    `stance`/`horizon`. It never extends to *content*: a missing field or an unexpected one is an
    error here, because the alternative is writing a note whose summary or mentions silently came
    from somewhere other than where the caller thinks.
    """
    payload = _extract_json_text(text)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise BackfillResultInvalid(
            f"the reply's JSON could not be parsed: {exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from exc
    if not isinstance(data, dict):
        raise BackfillResultInvalid(
            f"the reply's JSON is a {type(data).__name__}, not the object the packet asks for"
        )
    # An agent shown a "Task id: <id>" line in the packet will very often echo that id back INSIDE the
    # JSON object, which `extra="forbid"` would otherwise reject as an unexpected field -- rejecting a
    # reply whose actual content is perfectly correct. The id is carried by the packet/heading the
    # reply is matched against, never needed from the body, so a top-level id echo is dropped rather
    # than failed. `extra="forbid"` still catches every OTHER unexpected key, which is the real signal
    # that a reply answered a different question.
    for echoed in ("task_id", "video_id", "id"):
        data.pop(echoed, None)
    try:
        return BackfillResult.model_validate(data)
    except ValidationError as exc:
        raise BackfillResultInvalid(f"the reply's JSON is not the shape the packet asks for: {_errors(exc)}") from exc


def _extract_json_text(text: str) -> str:
    """The JSON substring of a reply: a fenced block if there is one, else the whole (stripped) text
    when it plausibly *is* JSON. A reply that is neither is rejected here rather than handed to
    `json.loads` for a decode error whose message ("Expecting value: line 1 column 1") tells the owner
    nothing about what went wrong."""
    fenced = _JSON_FENCE_RE.search(text) or _BARE_FENCE_RE.search(text)
    if fenced is not None:
        return fenced["body"].strip()
    stripped = text.strip()
    if stripped.startswith("{"):
        return stripped
    raise BackfillResultInvalid(
        "no JSON found in the reply: the packet asks for exactly one fenced ```json block "
        "(or bare JSON), and this reply contains neither"
    )


def _errors(exc: ValidationError) -> str:
    """Pydantic's error list as one short line naming the offending fields -- enough for the owner to
    fix the paste, without dumping the whole reply back at them."""
    parts = []
    for error in exc.errors()[:5]:
        location = ".".join(str(item) for item in error["loc"]) or "(root)"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """The outcome of both guardrails, whole, rather than a bare bool.

    Both lists are always populated when non-empty even though either one alone is enough to fail --
    a `--dry-run` exists so the owner can fix *everything* in one pass, and reporting only the first
    failure would make that an iterative game.
    """

    ok: bool
    reasons: tuple[str, ...]
    dropped_symbols: tuple[str, ...]
    ungrounded_numbers: tuple[str, ...]


def validate_result(
    result: BackfillResult,
    *,
    transcript: str,
    symbol_validator: Callable[[str], bool],
) -> ValidationReport:
    """Run both guardrails over a parsed reply. Never raises; the caller decides what a failure means.

    **Tickers drop, they do not reject.** Every `mention.symbol` is checked against `symbol_validator`
    (in practice `app.personas.tickers.build_symbol_validator`, the layered ledger/universe/provider
    check). A symbol that fails is named in `dropped_symbols` -- informational, NOT a reason the report
    fails -- and `ingest_result` writes the note without that mention, exactly as the in-house
    `summarize._validate_mentions` does. A symbol no exchange lists is far more often a mangled caption
    word or a real future/index the provider layer omits (`GC`, `^GSPC`) than evidence the whole reply
    is invented, so discarding a faithful note over one such mention is the worse error.

    **Numbers reject.** Every numeric token in the reply's prose -- `summary`, each theme, and each
    mention's `reasoning` (NOT quotes; see `_result_prose`) -- must trace back to the transcript's
    `grounded_values`: the in-house gate's own grounded set, expanded with rounding, pairwise
    differences and ratios, so a faithful restatement passes and only a fabricated figure fails. `ok`
    is true iff no number is ungrounded; dropped tickers never affect it.
    """
    from app.personas.summarize import _build_evidence_pack

    dropped = tuple(
        mention.symbol for mention in result.mentions if not symbol_validator(mention.symbol)
    )

    grounded = grounded_values(_build_evidence_pack(transcript))
    ungrounded = tuple(
        dict.fromkeys(
            token for token in numeric_tokens(_result_prose(result)) if token not in grounded
        )
    )
    reasons: tuple[str, ...] = (
        (
            f"{len(ungrounded)} number(s) do not appear in the transcript (and are not a difference "
            f"or ratio of figures that do): {', '.join(ungrounded)}",
        )
        if ungrounded
        else ()
    )

    return ValidationReport(
        ok=not ungrounded,
        reasons=reasons,
        dropped_symbols=dropped,
        ungrounded_numbers=ungrounded,
    )


def _result_prose(result: BackfillResult) -> str:
    """The reply text whose numbers are grounded: `summary`, each theme, and each mention's
    `reasoning`. EXCLUDES `quotes`, matching `summarize._draft_prose` -- a quote is verbatim source
    text by construction, so it can only restate a number already present, and re-checking it adds
    nothing but a chance for a caption artefact to false-reject an otherwise-faithful reply."""
    parts = [result.summary, *result.themes, *(mention.reasoning for mention in result.mentions)]
    return "\n".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def ingest_result(
    settings: Settings,
    *,
    persona_slug: str,
    video_id: str,
    result: BackfillResult,
    transcript: str,
    source_id: str | None = None,
    url: str | None = None,
    title: str | None = None,
    published: dt.datetime | None = None,
    lang: str = "",
    transcript_source: Literal["auto", "manual"] = "auto",
) -> EpisodicNote:
    """Validate one parsed reply and, if it passes every guardrail, write it into the vault as an
    immutable episodic note. Returns the written note, with its vault-relative `path` filled in.

    Raises, and writes nothing at all, for each of the three ways this can legitimately fail:
    `PersonaError(404)` for a slug with no persona, `PersonaError(409)` for a video that already has a
    note (episodic notes are immutable -- re-pasting a reply must not produce a second note or
    overwrite the first), and `BackfillValidationFailed` when the reply states an ungrounded number.
    An unvalidatable ticker does NOT raise -- that mention is dropped and the rest of the note is
    written (see `validate_result`). The order matters: the two cheap identity checks run before
    validation, so a duplicate paste is not charged the ticker validator's provider lookups.

    The note records `summary_source="external"` and `degraded=False`. Those two together are the
    honest statement of what happened: the guardrails this module *does* run passed (or nothing would
    have been written), and the in-house grounding gate -- which produces `degraded` -- never ran at
    all, which is what `summary_source` is there to say.
    """
    # Imported at call time, like every ingest-path import in `service.py` itself: this module is
    # imported by an API router at startup, and `tickers`/`store` pull in the ledger and the market
    # registry, which have no business being loaded to serve an unrelated route.
    from app.personas.service import PersonaError, _record_note, _vault_relative
    from app.personas.store import VaultStore
    from app.personas.tickers import build_symbol_validator

    store = VaultStore(settings)
    persona = store.load_persona(persona_slug)
    if persona is None:
        raise PersonaError(f"no persona {persona_slug!r}", status_code=404)
    if store.has_note(persona_slug, video_id):
        raise PersonaError(
            f"persona {persona_slug!r} already has a note for {video_id!r}; episodic notes are "
            f"immutable and are never re-ingested",
            status_code=409,
        )

    validator = build_symbol_validator(settings)
    report = validate_result(result, transcript=transcript, symbol_validator=validator)
    if not report.ok:
        logger.warning(
            "backfill_ingest: rejected external result for %s/%s: %s",
            persona_slug, video_id, "; ".join(report.reasons),
        )
        raise BackfillValidationFailed(report.reasons)

    # Drop the mentions whose symbol the validator could not confirm, keeping the rest -- the same
    # policy `summarize._validate_mentions` applies in-house. `validate_result` already named these in
    # `report.dropped_symbols`; re-using the one validator it was handed keeps this a cached lookup,
    # not a second round of provider calls.
    kept_mentions = tuple(m for m in result.mentions if validator(m.symbol))
    if report.dropped_symbols:
        logger.info(
            "backfill_ingest: dropped %d unvalidated ticker(s) from %s/%s: %s",
            len(report.dropped_symbols), persona_slug, video_id, ", ".join(report.dropped_symbols),
        )

    note = EpisodicNote(
        note_id=video_id,
        persona=persona_slug,
        source_id=source_id or _default_source_id(persona),
        published=published,
        ingested_at=dt.datetime.now(dt.UTC),
        url=url or f"https://www.youtube.com/watch?v={video_id}",
        title=title,
        kind="video_transcript",
        transcript_source=transcript_source,
        lang=lang,
        summary=result.summary,
        themes=tuple(result.themes),
        quotes=tuple(result.quotes),
        mentions=tuple(
            TickerMention(
                symbol=mention.symbol.strip().upper(),
                stance=mention.stance,
                reasoning=mention.reasoning,
                horizon=mention.horizon,
            )
            for mention in kept_mentions
        ),
        path="",  # filled in below from the path the store actually wrote
        degraded=False,
        summary_source="external",
    )

    try:
        written = store.write_note(note, transcript_text=transcript)
    except ValueError as exc:
        # Lost the has_note()-then-write_note() race: another writer created this note between the
        # duplicate check above and here (two ingests of the same shared vault at once -- observed
        # when two sessions ran the batch CLI on the same persona at the same moment). `write_note`
        # raises a bare ValueError for an already-existing note; convert it to the SAME 409 the
        # pre-check raises, so a batch CLI reports it as a duplicate and continues rather than aborting
        # non-zero mid-batch, and the API returns 409 rather than 500. Guarded on `has_note` so a
        # genuinely malformed-note ValueError is re-raised, never masked as a duplicate.
        if store.has_note(persona_slug, video_id):
            raise PersonaError(
                f"persona {persona_slug!r} already has a note for {video_id!r}; episodic notes are "
                f"immutable and are never re-ingested (lost a concurrent-write race)",
                status_code=409,
            ) from exc
        raise
    note = note.model_copy(update={"path": _vault_relative(settings, written)})
    _record_note(store, persona, note)
    store.append_log(
        persona_slug,
        f"ingested {video_id} from external agent ({len(note.mentions)} tickers)",
    )
    return note


def _default_source_id(persona: Persona) -> str:
    """The persona's first enabled YouTube source, or `"manual:adhoc"`.

    A packet is generated *from* a followed source, so the caller normally passes the real
    `source_id` through; this fallback exists for the case where a reply is ingested without one (a
    hand-edited paste, a packet regenerated after a source was removed). `"manual:adhoc"` matches the
    `manual:<...>` shape `FollowedSource` documents, so a note ingested this way still says truthfully
    where it came from rather than borrowing an unrelated channel's id.
    """
    for source in persona.sources:
        if source.platform == "youtube" and source.enabled:
            return source.source_id
    return "manual:adhoc"
