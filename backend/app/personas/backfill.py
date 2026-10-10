"""Turn each not-yet-ingested influencer video into a self-contained *task packet* a person can hand to
an external agent (Gemini, ChatGPT, another Claude), then paste the structured result back.

**Why this exists, and how it differs from `app.personas.service.start_ingest`.** The normal ingest
path fetches a transcript and summarises it *itself*, on this project's Claude budget, through
`app.personas.summarize.summarize_item` and its grounding gate. This module is the manual, zero-model
alternative the owner asked for: it does the deterministic half (discover what is new, fetch the
transcript, write a packet) and stops at the model call, leaving a Markdown file whose whole content is
meant to be pasted into whatever agent the owner already pays a subscription for. The agent's answer
comes back through the *separate* result-ingest path (`app.personas.backfill_ingest`, Phase 1b), which
re-imposes the same guardrails the in-house summariser gets for free -- ticker validation and a
numeric-grounding check against this very transcript -- because an external agent's prose is untrusted
input, exactly like a data provider's, until those two checks have passed. Nothing here writes a note
or spends a cent; it only reads and renders.

**Discovery is "what's new", newest-first, per the same rule the live ingest uses.** For each persona,
each of its enabled YouTube sources is listed newest-first and filtered against
`VaultStore.has_note(slug, video_id)` -- the identical already-ingested check
`app.personas.service._plan_items` applies -- so a packet is only ever produced for a video that has no
note yet. A video whose transcript cannot be fetched (captions disabled, region-blocked, a transient
YouTube error) is skipped with a log line rather than emitted as a broken packet, the same per-item
resilience the live ingest worker has: one dead video must not sink the batch.

**The packet's expected-output block is a contract, not a suggestion.** It asks the external agent for a
single fenced ``json`` object with exactly the fields `app.personas.summarize.NoteDraft` carries
(`summary`, `themes`, `quotes`, `mentions[{symbol, stance, horizon, reasoning}]`), so the result-ingest
parser has a deterministic shape to read and the owner never has to hand-transcribe anything. The
guardrails restated in every packet -- quotes verbatim in the source language, summary in the
configured target language, only symbols the speaker actually named, only numbers actually stated --
are the same ones `summarize.py` enforces, written where the external agent will actually read them so
its answer can survive the grounding check on the way back in.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import Settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.personas.models import Persona
    from app.personas.store import VaultStore

logger = logging.getLogger(__name__)

__all__ = [
    "BackfillTask",
    "TaskPacket",
    "TaskPacketRef",
    "discover_tasks",
    "find_task_packet",
    "list_task_packets",
    "packet_path",
    "read_task_packet",
    "render_index_markdown",
    "render_task_markdown",
    "task_from_transcript",
    "write_task_files",
]


@dataclass(frozen=True, slots=True)
class BackfillTask:
    """One not-yet-ingested video, everything a packet needs, and nothing that requires a model call.

    `video_id` is also the `note_id` the eventual note will carry (the live ingest uses the video id as
    the note id, so the result-ingest path can re-use `VaultStore.has_note`/`write_note` unchanged). It
    is the single value that ties an outbound packet to the note a pasted-back result will become.
    """

    persona_slug: str
    persona_name: str
    source_id: str
    video_id: str
    url: str
    title: str
    published: dt.datetime | None
    lang: str
    transcript: str
    generated: bool
    """True when the transcript is auto-generated (ASR) captions rather than a human-authored track --
    surfaced in the packet so the external agent knows the source may contain transcription errors."""


def discover_tasks(
    settings: Settings,
    *,
    limit_per_persona: int | None = None,
    slugs: Sequence[str] | None = None,
) -> list[BackfillTask]:
    """Every new (un-ingested) video across the followed influencers, as ready-to-render tasks.

    Mirrors `app.personas.service._plan_items`' discovery exactly -- list a channel newest-first, keep
    only videos with no note yet -- then does the one extra thing the live planner defers: fetch each
    kept video's transcript (and metadata for its title/date) up front, because a packet is useless
    without the transcript in it. `limit_per_persona` is clamped by `Settings.persona_backfill_max`, the
    same ceiling the live ingest respects. `slugs`, when given, restricts discovery to those personas.

    Transcript/listing failures degrade, they do not raise: an unreachable channel or a caption-less
    video is logged and skipped so the rest of the batch still produces packets -- the same rule the
    live ingest worker follows. Import of the YouTube adapter is deferred to call time (not module
    scope) for the reason `app.personas.service` documents: a machine without `yt-dlp` should lose
    ingesting, not the whole application.
    """
    from app.personas.sources import youtube
    from app.personas.sources.base import SourceError, TranscriptUnavailable
    from app.personas.store import VaultStore

    store = VaultStore(settings)
    cap = min(limit_per_persona or settings.persona_backfill_max, settings.persona_backfill_max)

    wanted = set(slugs) if slugs is not None else None
    tasks: list[BackfillTask] = []
    for persona in store.list_personas():
        if wanted is not None and persona.slug not in wanted:
            continue
        tasks.extend(_tasks_for_persona(persona, store=store, cap=cap, youtube=youtube,
                                        source_error=SourceError, transcript_unavailable=TranscriptUnavailable))
    return tasks


def _tasks_for_persona(
    persona: Persona,
    *,
    store: VaultStore,
    cap: int,
    youtube: object,
    source_error: type[Exception],
    transcript_unavailable: type[Exception],
) -> list[BackfillTask]:
    """The per-persona half of `discover_tasks`, split out so one persona's dead channel is contained
    to that persona rather than aborting the whole sweep."""
    out: list[BackfillTask] = []
    for source in persona.sources:
        if source.platform != "youtube" or not source.enabled:
            continue
        if len(out) >= cap:
            break
        key = source.channel_id or source.handle
        try:
            refs = youtube.list_videos(key, limit=cap)  # type: ignore[attr-defined]
        except source_error as exc:
            logger.warning("backfill: could not list videos for %s (%s); skipping source", source.handle, exc)
            continue

        for ref in refs:
            if len(out) >= cap:
                break
            if store.has_note(persona.slug, ref.video_id):
                continue
            try:
                fetched = youtube.fetch_transcript(ref.video_id)  # type: ignore[attr-defined]
            except transcript_unavailable as exc:
                logger.info("backfill: no transcript for %s (%s); skipping", ref.video_id, exc)
                continue
            except source_error as exc:
                logger.warning("backfill: transcript fetch failed for %s (%s); skipping", ref.video_id, exc)
                continue

            title = ref.title or ""
            published: dt.datetime | None = None
            try:
                meta = youtube.fetch_video_meta(ref.video_id)  # type: ignore[attr-defined]
                published = meta.published
                title = title or meta.title
            except Exception:  # best-effort: the flat listing carries no date, and this is optional
                logger.info("backfill: no metadata for %s; leaving title/date as listed", ref.video_id)

            out.append(
                BackfillTask(
                    persona_slug=persona.slug,
                    persona_name=persona.display_name,
                    source_id=source.source_id,
                    video_id=ref.video_id,
                    url=ref.url,
                    title=title,
                    published=published,
                    lang=fetched.lang,
                    transcript=fetched.text,
                    generated=fetched.generated,
                )
            )
    return out


def task_from_transcript(
    persona: Persona,
    *,
    video_id: str,
    transcript: str,
    title: str = "",
    lang: str = "",
    generated: bool = True,
    url: str | None = None,
) -> BackfillTask:
    """Build a `BackfillTask` from a transcript supplied by hand, with NO YouTube call.

    The automated path (`discover_tasks`) fetches each transcript from YouTube, which is exactly what
    gets an IP caption-blocked. This is the escape hatch the owner asked for: when the transcript is
    already in hand -- copied from YouTube's own "Show transcript" panel, a caption file, or anywhere
    else -- a packet can be rendered from it directly, so the block is bypassed entirely. Attribution
    (`persona_name`, `source_id`) is read off the persona the caller already loaded, not re-resolved.
    """
    source_id = next(
        (s.source_id for s in persona.sources if s.platform == "youtube" and s.enabled),
        "manual:adhoc",
    )
    return BackfillTask(
        persona_slug=persona.slug,
        persona_name=persona.display_name,
        source_id=source_id,
        video_id=video_id,
        url=url or f"https://www.youtube.com/watch?v={video_id}",
        title=title,
        published=None,
        lang=lang,
        transcript=transcript,
        generated=generated,
    )


def _expected_output_block(summary_lang: str) -> str:
    """The fenced-JSON contract the external agent must return, plus the guardrails that let its answer
    survive the result-ingest grounding check. Kept identical in spirit to what `summarize.py` asks the
    in-house model for, so a packet run through Gemini yields the same shape a Claude ingest would."""
    return (
        "## What to produce\n\n"
        "Read the transcript below and reply with **exactly one fenced `json` code block** containing "
        "one JSON object in this shape -- and nothing else outside it:\n\n"
        "```json\n"
        "{\n"
        f'  "summary": "2-4 sentences in {summary_lang!r} (the target language), what this video says",\n'
        f'  "themes": ["2-5 short bullets in {summary_lang!r}: what the speaker is trading/watching"],\n'
        '  "quotes": ["1-4 VERBATIM quotes copied exactly from the transcript, in the SOURCE language '
        '-- never translated or paraphrased; copy the exact characters, caption typos and all"],\n'
        '  "mentions": [\n'
        '    {\n'
        '      "symbol": "TICKER the speaker named, uppercase (e.g. TSLA, NVDA, BTC)",\n'
        '      "stance": "one of: bullish | bearish | neutral | unclear",\n'
        '      "horizon": "one of: intraday | swing | position | long_term | unclear",\n'
        '      "reasoning": "why the speaker took that stance, in their words"\n'
        '    }\n'
        '  ]\n'
        "}\n"
        "```\n\n"
        "### Rules\n\n"
        "- **Return the JSON as literal text in the one code block above. Do NOT write a script, a "
        "program, or a zip/file generator -- no `import`, no code that *produces* the JSON. Just the "
        "object itself.**\n"
        f"- `summary` and `themes` in {summary_lang!r}; `quotes` verbatim in the source language.\n"
        "- **Capture every directional call** -- buys AND sells, bullish AND bearish, plus secondary "
        "names mentioned in passing (a portfolio they cite, a name they compare to). Do not keep only "
        "the headline pick.\n"
        "- **Symbol accuracy over caution.** Auto-captions mangle tickers into ordinary words; give your "
        "best reading of the actual listing symbol anyway (map the spoken company name to its ticker, "
        "e.g. 'TSMC' -> `TSM`). Two different companies are two different symbols -- do not collapse a "
        "distinct name onto a better-known one. A downstream check validates every symbol and silently "
        "drops any that is not a real instrument, so a wrong guess is far safer than dropping the call "
        "-- never omit a named company for want of certainty about its ticker.\n"
        "- **Stance is the speaker's, and hedged is not bullish.** A conditional or two-sided view "
        "('if rates hold, maybe...') is `neutral` or `unclear`, never `bullish`; use `unclear` when they "
        "name a company without committing to a direction.\n"
        "- **Only state numbers that appear in the transcript.** Do not invent a price target or round "
        "to a figure the speaker did not say (you may restate a figure the source gives). Every number "
        "in `summary`/`themes`/`reasoning` is checked against the transcript.\n"
        "- If the video names no tickers, return `\"mentions\": []` -- an empty list, not invented ones.\n"
    )


def render_task_markdown(task: BackfillTask, *, summary_lang: str) -> str:
    """One self-contained packet: everything an external agent needs, in the order it should read it.

    Job + contract first (so the agent reads the instructions before the transcript scrolls them off),
    then the transcript. The `task id` line is the `video_id`; the result-ingest path keys on it, so the
    owner should paste it back with the result (the packet says so)."""
    published = task.published.date().isoformat() if task.published else "unknown"
    caption = "auto-generated (ASR -- may contain errors)" if task.generated else "human-authored"
    header = [
        f"# Backfill task · {task.persona_name}",
        "",
        f"- **Task id (paste back with the result):** `{task.video_id}`",
        f"- **Persona:** {task.persona_name} (`{task.persona_slug}`)",
        f"- **Video:** {task.title or '(untitled)'}",
        f"- **URL:** {task.url}",
        f"- **Published:** {published}  ·  **Transcript language:** {task.lang or 'unknown'}  ·  "
        f"**Captions:** {caption}",
        "",
        "You are extracting one influencer's own views from the transcript of their video, for a "
        "read-only research dashboard. Summarise what THEY said and the stance THEY took -- never your "
        "own opinion, and never investment advice.",
        "",
    ]
    body = [
        _expected_output_block(summary_lang),
        "---",
        "",
        "## Transcript",
        "",
        "```text",
        task.transcript.strip(),
        "```",
        "",
    ]
    return "\n".join([*header, *body])


def render_index_markdown(tasks: Sequence[BackfillTask]) -> str:
    """A one-line-per-task index so the owner can see the whole batch at a glance and grab all of it."""
    lines = [
        "# Backfill tasks",
        "",
        f"{len(tasks)} task(s) ready to hand to an external agent. One `.md` file each in this folder; "
        "paste a file's contents into the agent, then paste its JSON reply back through the "
        "result-ingest step (keep the task id).",
        "",
    ]
    if not tasks:
        lines.append("_(none -- every followed video already has a note)_")
        return "\n".join(lines) + "\n"
    for task in tasks:
        published = task.published.date().isoformat() if task.published else "unknown"
        lines.append(
            f"- `{task.persona_slug}__{task.video_id}.md` — **{task.persona_name}** · "
            f"{task.title or '(untitled)'} · {published}"
        )
    return "\n".join(lines) + "\n"


def write_task_files(tasks: Sequence[BackfillTask], out_dir: Path, *, summary_lang: str) -> list[Path]:
    """Write one packet per task plus an `index.md` into `out_dir`, returning the packet paths.

    File name is `<persona_slug>__<video_id>.md` -- stable and collision-free (a video id is unique, and
    the slug prefix keeps one persona's tasks together when the owner sorts the folder). Creates
    `out_dir` if needed; overwrites an existing packet for the same video (regenerating a task is
    idempotent, not an error)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for task in tasks:
        path = out_dir / f"{task.persona_slug}__{task.video_id}.md"
        path.write_text(render_task_markdown(task, summary_lang=summary_lang), encoding="utf-8")
        written.append(path)
    (out_dir / "index.md").write_text(render_index_markdown(tasks), encoding="utf-8")
    return written


# ---------------------------------------------------------------------------
# Reading a packet back
# ---------------------------------------------------------------------------
#
# `render_task_markdown` above is the writer; everything below is its inverse, and the two are
# developed as one symmetric pair for the same reason `app.personas.store`'s frontmatter writer and
# parser are. The result-ingest path (`app.personas.backfill_ingest`) needs three things a pasted
# JSON reply does not itself carry -- which persona the task belonged to, the video's url/title, and
# above all *the transcript*, which is what the numeric-grounding check validates the reply against.
# The packet on disk is the only place all three still exist together after the packet has been
# handed to an external agent, so it is read back rather than re-fetched: re-fetching would hit
# YouTube again, and (worse) could return a different transcript than the agent was actually shown,
# which would make the grounding check answer a question nobody asked.

_PACKET_INDEX_NAME = "index.md"

_TASK_ID_RE = re.compile(r"^- \*\*Task id[^:]*:\*\* `(?P<video_id>[^`]+)`", re.MULTILINE)
_PERSONA_RE = re.compile(r"^- \*\*Persona:\*\* (?P<name>.*?) \(`(?P<slug>[^`]+)`\)\s*$", re.MULTILINE)
_VIDEO_RE = re.compile(r"^- \*\*Video:\*\* (?P<title>.*?)\s*$", re.MULTILINE)
_URL_RE = re.compile(r"^- \*\*URL:\*\* (?P<url>.*?)\s*$", re.MULTILINE)
_META_RE = re.compile(
    r"^- \*\*Published:\*\* (?P<published>.*?)\s+·\s+"
    r"\*\*Transcript language:\*\* (?P<lang>.*?)\s+·\s+"
    r"\*\*Captions:\*\* (?P<captions>.*?)\s*$",
    re.MULTILINE,
)
_TRANSCRIPT_RE = re.compile(r"## Transcript\s*\n+```text\n(?P<body>.*?)\n```", re.DOTALL)

#: What `render_task_markdown` writes when the value is not known. Parsed back to `""` rather than
#: kept as the literal word, so a caller never mistakes the placeholder for a real language code.
_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TaskPacketRef:
    """One packet on disk, identified without reading its (potentially 60k-character) transcript.

    This is what a listing hands back: enough to show the owner a row and to key an incoming reply,
    with the bulk left on disk until `read_task_packet` is actually asked for it.
    """

    persona_slug: str
    persona_name: str
    video_id: str
    title: str
    url: str
    published: str
    """ISO date `"YYYY-MM-DD"`, or `""` when the packet says `unknown` -- the same "we genuinely do
    not know" that `EpisodicNote.published is None` means, never a stand-in date."""
    filename: str
    path: Path


@dataclass(frozen=True, slots=True)
class TaskPacket:
    """A fully-read packet: its `ref`, the transcript the external agent was shown, and the raw
    markdown. `generated` mirrors the task's own ASR flag, recovered from the `**Captions:**` header
    line, so the result-ingest can record the right `transcript_source` on the note it writes."""

    ref: TaskPacketRef
    transcript: str
    markdown: str
    lang: str
    generated: bool


def packet_path(tasks_dir: Path, persona_slug: str, video_id: str) -> Path:
    """Where `write_task_files` would have put this task's packet. The single place the
    `<persona_slug>__<video_id>.md` convention is spelled out for readers, so a caller never
    hand-builds the name."""
    return tasks_dir / f"{persona_slug}__{video_id}.md"


def list_task_packets(tasks_dir: Path) -> list[TaskPacketRef]:
    """Every packet in `tasks_dir`, newest-published first (then by filename, for determinism).

    A missing directory answers `[]`, not an error: no packets have been generated yet is a normal
    state for the page and the CLI to render. A file that does not parse as a packet is logged and
    skipped rather than raised -- the same choice `VaultStore.list_notes` makes, and for the same
    reason: one file an external editor mangled must not hide every other pending task. `index.md`
    is skipped by name; it is the human-facing table of contents, not a task.
    """
    if not tasks_dir.is_dir():
        return []
    refs: list[TaskPacketRef] = []
    for path in sorted(tasks_dir.glob("*.md")):
        if path.name == _PACKET_INDEX_NAME:
            continue
        try:
            refs.append(_parse_packet_ref(path, path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            logger.warning("backfill: skipping unreadable task packet %s: %s", path, exc)
            continue
    refs.sort(key=lambda ref: ref.filename)
    refs.sort(key=lambda ref: ref.published, reverse=True)
    return refs


def read_task_packet(path: Path) -> TaskPacket:
    """Parse one packet file back into its header fields and transcript.

    Raises `ValueError` when the file is not a packet this module wrote -- a missing task-id/persona
    header or no ```text transcript fence. That is deliberately strict: the transcript is the
    reference text the result-ingest's grounding check runs against, so a packet whose transcript
    could not be recovered must fail loudly rather than validate a reply against an empty string,
    which would reject every number the influencer actually said.
    """
    raw = path.read_text(encoding="utf-8")
    ref = _parse_packet_ref(path, raw)
    transcript_match = _TRANSCRIPT_RE.search(raw)
    if transcript_match is None:
        raise ValueError(f"{path.name}: no '## Transcript' ```text block found")
    meta = _META_RE.search(raw)
    lang = ""
    generated = False
    if meta is not None:
        lang_raw = meta["lang"].strip()
        lang = "" if lang_raw == _UNKNOWN else lang_raw
        generated = meta["captions"].strip().startswith("auto-generated")
    return TaskPacket(
        ref=ref,
        transcript=transcript_match["body"].strip(),
        markdown=raw,
        lang=lang,
        generated=generated,
    )


#: `Path.glob`'s own wildcard alphabet. A real YouTube video id (and the API boundary's own
#: `VideoIdPath`/`ValidateRequest.video_id` pattern -- `^[A-Za-z0-9_-]{1,64}$`) never contains any of
#: these, so a `video_id` carrying one did not come through that boundary -- a direct caller of this
#: function, or a boundary that changes underneath it later. Checked here too, defensively, so this
#: function's own contract ("the packet for exactly this id, or nothing") holds regardless of what
#: validates its caller -- a `video_id` of `"*"` must never turn into "every packet in the directory."
_GLOB_METACHARACTERS = frozenset("*?[]")


def find_task_packet(tasks_dir: Path, video_id: str) -> TaskPacket | None:
    """The packet for one video id, or `None` when no packet for it exists (or it is unreadable).

    Globs on the `__<video_id>.md` suffix rather than requiring the persona slug, because a pasted
    reply carries the task id and nothing else -- the slug is one of the things the packet is being
    read to recover. The anchored `__` separator is what keeps this from matching a longer id that
    merely ends with the one asked for.

    `video_id` is rejected up front if it contains any glob metacharacter (`*`, `?`, `[`, `]`) --
    see `_GLOB_METACHARACTERS` -- rather than passed straight into `Path.glob`, which would treat it
    as a pattern instead of a literal id and could match packets that have nothing to do with the
    id actually asked for.
    """
    if not tasks_dir.is_dir() or not video_id or any(ch in _GLOB_METACHARACTERS for ch in video_id):
        return None
    for path in sorted(tasks_dir.glob(f"*__{video_id}.md")):
        try:
            return read_task_packet(path)
        except (OSError, ValueError) as exc:
            logger.warning("backfill: task packet %s for %s is unreadable: %s", path, video_id, exc)
            return None
    return None


def _parse_packet_ref(path: Path, raw: str) -> TaskPacketRef:
    """The header half of `read_task_packet`, shared with `list_task_packets` so a listing and a full
    read can never disagree about what a packet says it is."""
    task_id = _TASK_ID_RE.search(raw)
    persona = _PERSONA_RE.search(raw)
    if task_id is None or persona is None:
        raise ValueError(f"{path.name}: missing the 'Task id'/'Persona' packet header lines")
    video = _VIDEO_RE.search(raw)
    url = _URL_RE.search(raw)
    meta = _META_RE.search(raw)
    published = ""
    if meta is not None:
        published_raw = meta["published"].strip()
        published = "" if published_raw == _UNKNOWN else published_raw
    title = video["title"].strip() if video is not None else ""
    return TaskPacketRef(
        persona_slug=persona["slug"].strip(),
        persona_name=persona["name"].strip(),
        video_id=task_id["video_id"].strip(),
        # `render_task_markdown` writes the literal "(untitled)" for a task with no title; map it
        # back to the empty string it came from rather than putting a display placeholder into a
        # note's `title` field.
        title="" if title == "(untitled)" else title,
        url=url["url"].strip() if url is not None else "",
        published=published,
        filename=path.name,
        path=path,
    )
