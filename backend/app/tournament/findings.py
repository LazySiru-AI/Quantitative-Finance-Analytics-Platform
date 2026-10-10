"""One round's own written record -- what it found, what defects it hit, what was decided, and what
it left open for the next round -- read from the hand-written markdown under `data/rounds/<round_id>/`
(`REPORT.md`, `BRIEF.md`, `SELECTION.md`) and from the programme-wide `strategy-program/DEFECTS.md`.

**This is a reading aid, not a schema.** Every file this module parses was written by a person for
another person to read, across thirteen rounds whose format visibly drifted (`REPORT.md` for rounds
1-5, `SELECTION.md` from round 6 on; numbered sections in some, unnumbered ones like `"## The
result"` interleaved in others; `### ` subsections in round 5's report that no other round uses).
Nothing here was authored against this module, and nothing here should be trusted the way
`app.tournament.results` -- which recomputes figures from typed JSON -- is trusted. A heading shape
this module does not recognise is silently skipped, never raised on: nothing recorded here is money
or a ranking a caller acts on automatically, it is prose a caller is being pointed at, and pointing
at nothing is a far smaller failure than crashing the page that lists a round.

**The alternative rejected: a hand-maintained index of what each round said.** Thirteen rounds in,
someone could transcribe "round 11 left the distinctness rule unsettled" into a small YAML file once
per round and this module would not need to exist. That was rejected for the same reason
`app.tournament.results` recomputes `total_return` from `ending_equity`/`starting_equity` instead of
trusting the stored field: a second, hand-maintained copy of a fact that already lives in the round's
own prose is a copy that goes stale the moment someone edits the prose and forgets the index, and
nothing here would catch that the way a re-derivation catches a wrong stored number. Parsing the
prose directly means this module's output is only ever as current as the files it reads -- which are
also each round's authoritative record -- and never a paraphrase of them from further back.

**What splits a document into entries.** Every level-2 (`## `) heading starts one entry; the text up
to the next `## ` heading (including any `### ` subsections inside it) is that entry's `body`. A
document's own H1 title and anything before its first `## ` heading belongs to no entry and is
dropped. This is coarser than "one entry per subsection" on purpose: the wire contract's own example
id, `"r11-selection-8"`, and its own example source, `"SELECTION.md § 8"`, both point at
`data/rounds/r11-2026-08/SELECTION.md`'s section 8 as a whole -- the unit a reader would actually
cite -- not at any of the paragraphs inside it.

**Where `kind` comes from, and the one thing it is not derived from.** `kind` is assigned by which
file an entry came from -- `DEFECTS.md` is always `"defect"`, `SELECTION.md` is always `"decision"`
(that file exists only to record a seating/scope decision -- see
`app.api.competition_selection`'s docstring -- so every section in it, including a caveat like "what
this evidence cannot do", is part of that decision's record, not a separate kind of thing) -- and
`REPORT.md`/`BRIEF.md` sections default to `"finding"` unless their heading reads as addressed to a
future round (`"for round 2"`, `"for whoever runs round 12"`), in which case they are `"follow-up"`.
`kind` is a classification of *what an entry is about*; `carries_forward` (below) is a classification
of *whether it is still open*, and the two are computed independently. A `"follow-up"`-kind section
that a later round's document says it settled would have `carries_forward=False` if that later
section's own heading or opening paragraph does not use open-item language -- `kind` does not force
the flag.

**`carries_forward` is a heuristic over prose, stated as one.** For a `DEFECTS.md` entry it is
mechanical: `True` unless the entry's `**Status:**` line contains the word "fixed" (case-insensitive)
-- see `strategy-program/DEFECTS.md`'s own convention, where "FIXED" is the only status word that
ever appears bolded at the start of that line. For a round-file section there is no such convention,
so :data:`OPEN_ITEM_KEYWORDS` is matched, case-insensitively, against the section's heading plus its
first paragraph. This will both over-trigger (a paragraph that uses "remains" in an unrelated
sentence) and under-trigger (an open item phrased in a way none of the keywords catch) on prose
nobody has written yet -- it is a heuristic, not a schema, and the module docstring says so rather
than letting the field's name imply more precision than the method has.

**Which `DEFECTS.md` entries attach to which round.** A defect is "hit" by the round that found it,
not by every round after it -- the objective this endpoint serves is "what round N found ... and
what it left open for N+1", and a round cannot have found a defect nobody had discovered yet.
Attachment is read from the entry's own `**Found:**` line: it is searched (not merely matched at the
start) for `round <N>` where `N` is `round_id`'s own leading number (`"r11-2026-08"` -> `11`), which
covers both `"Found: round 1, 2026-08-20, ..."` (D1's convention) and `"Found: 2026-08-22, during
round 12's integration."` (D6's -- the phrase is not adjacent to the label, which is exactly the kind
of drift this module is written to survive). One real defect in this repository's own `DEFECTS.md`,
D4, states no round number on its `**Found:**` line at all (only elsewhere in its body) and so is not
attached to any round by this heuristic -- a known gap, recorded here rather than papered over with a
body-wide search that would start attaching defects to every round that happens to mention their
number in passing.

**What a reader could get wrong.** `sources` lists the files this module actually opened and drew at
least one entry from for *this* `round_id`. Two consequences follow that are easy to miss: first, a
round whose files exist but were empty of parseable `## ` sections reports `sources=[]` for that
file, not a bare `["REPORT.md"]` with `findings=[]` -- see `_read_round_file`'s callers. Second,
`DEFECTS.md` can be absent from `sources` for a round that has plenty of other findings, simply
because no defect's `**Found:**` line named that round -- this is not the same thing as the file
failing to read, and does not mean the round's numbers are defect-free, only that no defect claims to
have been *found* during it (an earlier round's still-open defect can still be qualifying the same
numbers; see `strategy-program/DEFECTS.md`'s own "kept after the fix" convention for why a defect's
consequences can outlive the round that found it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings

__all__ = [
    "DEFECTS_PATH",
    "OPEN_ITEM_KEYWORDS",
    "ROUNDS_ROOT",
    "FindingsData",
    "RoundFindingData",
    "RoundNotFoundError",
    "list_findings",
]

#: Root of the round-record tree -- the same resolution `app.tournament.results.ROUNDS_ROOT` uses
#: (`app.config.Settings.rounds_dir`, overridable via `INVDASH_ROUNDS_DIR`), imported by reference
#: rather than reimplemented so the two modules can never resolve a round differently.
ROUNDS_ROOT: Path = get_settings().rounds_dir

#: `strategy-program/DEFECTS.md` sits outside the rounds tree -- it is programme-wide, not one
#: round's record -- so it is not covered by `rounds_dir` at all and gets its own module-level
#: setting. It is **not** shipped in the Docker image: `backend/Dockerfile` copies the application
#: and nothing else, and `strategy-program/` was deliberately removed from it. Its absence is a
#: supported state -- `_read_text` returns `None` for a missing file and the response's `sources`
#: names only what was actually read, so a reader can tell "no defects recorded" from "the defects
#: file was not available". See `app.config.Settings.defects_file` and
#: `tests/test_deployment_paths.py`'s `NOT_COPIED_ON_PURPOSE`. Overridable per deployment via
#: `INVDASH_DEFECTS_FILE`, and overridable
#: per call via `list_findings`'s `defects_path` parameter, the same pattern
#: `app.tournament.results.load_library`'s `library_root` parameter uses, so a test can point it at a
#: `tmp_path` fixture instead of the real file.
DEFECTS_PATH: Path = get_settings().defects_file

#: Matched case-insensitively against a section's heading plus its first paragraph to decide
#: `carries_forward` for anything that is not a `DEFECTS.md` entry (those use their `**Status:**`
#: line instead -- see the module docstring). This is a heuristic over hand-written prose, not a
#: schema: it will both over-trigger on a sentence that merely uses one of these words in passing and
#: under-trigger on an open item phrased in a way nothing here catches. Tuned against the rounds
#: actually committed under `data/rounds/` (`"next round"`, `"for round"`-style headings, "This
#: needs... Deferred to the round after...", "Round 13's job") rather than designed in the abstract.
OPEN_ITEM_KEYWORDS: tuple[str, ...] = (
    "next round",
    "to settle",
    "open",
    "unresolved",
    "follow-up",
    "todo",
    "remains",
    "still",
)

_H2_RE = re.compile(r"^## (.+?)\s*$")
#: A heading's leading `N` or `N.M` numbering, e.g. `"8. Owner override, ..."` -> `("8", "Owner
#: override, ...")`. Sections without one (`"## The result"`, `"## For whoever runs round 12"`) fall
#: back to using the whole heading text as both title and section reference -- see
#: `_title_and_section_ref`.
_NUMBER_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.*)$")
#: A `DEFECTS.md` heading's leading defect id, e.g. `"D1 --  ..."` -> `"D1"`.
_DEFECT_ID_RE = re.compile(r"^(D\d+)\b")
#: A section heading addressed to a future round -- `"What changes for round 2"`, `"For whoever runs
#: round 12"` -- classified `"follow-up"` rather than the `"finding"` default. Deliberately narrower
#: than `OPEN_ITEM_KEYWORDS`: this decides `kind`, not `carries_forward`, and a heading can name a
#: future round without every word in `OPEN_ITEM_KEYWORDS` being satisfied (or vice versa).
_FOLLOWUP_HEADING_RE = re.compile(r"for (?:whoever runs )?round\b", re.IGNORECASE)
_FOUND_LINE_RE = re.compile(r"^\*\*Found:\*\*\s*(.*)$")
_STATUS_LINE_RE = re.compile(r"^\*\*Status:\*\*\s*(.*)$")
_ROUND_NUMBER_RE = re.compile(r"^r(\d+)-")
_ROUND_MENTION_RE = re.compile(r"\bround\s+(\d+)\b", re.IGNORECASE)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class RoundNotFoundError(Exception):
    """No directory exists at `rounds_root / round_id` -- the same "unknown identifier, not a
    crash" condition `app.tournament.results.RoundNotFoundError` reports, kept as a distinct class
    because this module does not import `app.tournament.results` (see that module's own docstring on
    why `strategy-program/tools/` cannot be imported from `backend/app`; this is the same "keep this
    package's dependency graph a strict layer, not a web" reasoning applied one door down)."""

    def __init__(self, round_id: str) -> None:
        self.round_id = round_id
        super().__init__(f"no such round: {round_id!r}")


@dataclass(frozen=True, slots=True)
class RoundFindingData:
    """One entry from one file: a defect, a decision, a finding, or a follow-up. See the module
    docstring for exactly how `kind` and `carries_forward` are derived -- they are independent
    judgements, not two names for the same thing."""

    id: str
    round_id: str
    kind: str
    title: str
    body: str
    source: str
    carries_forward: bool


@dataclass(frozen=True, slots=True)
class FindingsData:
    """`/api/competition/rounds/{round_id}/findings`'s data.

    `follow_ups` is always a subset of `findings` by construction (`tuple(f for f in findings if
    f.carries_forward)`), never assembled from a second pass over the source files -- see the module
    docstring's note on why a second, independently-derived list would be a copy that could drift
    from the first.
    """

    round_id: str
    findings: tuple[RoundFindingData, ...]
    follow_ups: tuple[RoundFindingData, ...]
    sources: tuple[str, ...]


# ---------------------------------------------------------------------------
# Low-level markdown helpers
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str | None:
    """`path`'s text, or `None` if it does not exist or fails to decode as UTF-8. A decode failure is
    skipped rather than raised -- per this module's contract (see the docstring), a reading aid
    degrades to "nothing found here" rather than 500ing a page that lists a round."""
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def _split_h2_sections(text: str) -> list[tuple[str, str]]:
    """`[(heading_text, body_text), ...]` for every level-2 (`## `) heading in `text`, in document
    order. Text before the first `## ` heading (an H1 title, a disclaimer paragraph) belongs to no
    section and is dropped. A `### ` subheading is not a boundary -- its text stays inside its parent
    section's body; see the module docstring for why the granularity stops at `## `."""
    sections: list[tuple[str, list[str]]] = []
    current_body: list[str] | None = None
    for line in text.splitlines():
        match = _H2_RE.match(line)
        if match:
            current_body = []
            sections.append((match.group(1).strip(), current_body))
        elif current_body is not None:
            current_body.append(line)
    return [(heading, "\n".join(body).strip()) for heading, body in sections]


def _first_paragraph(body: str) -> str:
    return body.split("\n\n", 1)[0]


def _slugify(text: str, max_len: int = 40) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "section"


def _title_and_section_ref(heading: str) -> tuple[str, str]:
    """`"8. Owner override, 2026-08-22 ..."` -> `("Owner override, 2026-08-22 ...", "8")`. A heading
    with no leading number (`"The result"`, `"For whoever runs round 12"`) uses its own full text as
    both -- there is no shorter reference a human could use to find it that is not itself the
    heading."""
    match = _NUMBER_PREFIX_RE.match(heading)
    if match:
        title = match.group(2).strip()
        return (title or heading), match.group(1)
    return heading, heading


def _carries_forward_heuristic(heading: str, body: str) -> bool:
    haystack = f"{heading}\n{_first_paragraph(body)}".lower()
    return any(keyword in haystack for keyword in OPEN_ITEM_KEYWORDS)


# ---------------------------------------------------------------------------
# Round-file sections (REPORT.md / BRIEF.md / SELECTION.md)
# ---------------------------------------------------------------------------

#: `(filename, kind-if-not-followup)` in the order they are checked -- `REPORT.md` and `BRIEF.md`
#: default a section to `"finding"`, `SELECTION.md`'s every section is `"decision"` (see the module
#: docstring on why that file's caveats and tables are still part of the decision's record, not a
#: separate kind). Order matches "the data on disk" in this endpoint's brief, and is also the order
#: entries appear in the response and files appear in `sources`.
_ROUND_FILES: tuple[tuple[str, str], ...] = (
    ("REPORT.md", "finding"),
    ("BRIEF.md", "finding"),
    ("SELECTION.md", "decision"),
)


def _round_file_kind(heading: str, default_kind: str) -> str:
    if default_kind == "decision":
        return "decision"
    return "follow-up" if _FOLLOWUP_HEADING_RE.search(heading) else "finding"


def _parse_round_file(
    text: str, round_id: str, filename: str, default_kind: str
) -> list[RoundFindingData]:
    file_stem = filename.rsplit(".", 1)[0].lower()
    tag = _round_tag(round_id)
    out: list[RoundFindingData] = []
    for heading, body in _split_h2_sections(text):
        title, ref = _title_and_section_ref(heading)
        id_suffix = ref if _NUMBER_PREFIX_RE.match(heading) else _slugify(heading)
        out.append(
            RoundFindingData(
                id=f"{tag}-{file_stem}-{id_suffix}",
                round_id=round_id,
                kind=_round_file_kind(heading, default_kind),
                title=title,
                body=body,
                source=f"{filename} § {ref}",
                carries_forward=_carries_forward_heuristic(heading, body),
            )
        )
    return out


# ---------------------------------------------------------------------------
# DEFECTS.md
# ---------------------------------------------------------------------------


def _defect_status_carries_forward(body: str) -> bool:
    for line in body.splitlines():
        match = _STATUS_LINE_RE.match(line.strip())
        if match:
            return "fixed" not in match.group(1).lower()
    # No `**Status:**` line at all -- an entry that does not even claim to have a status is treated
    # as open rather than silently dropped, the same "unmeasurable is not the same as resolved"
    # reasoning `app.tournament.results._capital_exposure` applies to a missing figure.
    return True


def _defect_round_number(body: str) -> int | None:
    for line in body.splitlines():
        match = _FOUND_LINE_RE.match(line.strip())
        if match:
            mention = _ROUND_MENTION_RE.search(match.group(1))
            return int(mention.group(1)) if mention else None
    return None


def _round_number(round_id: str) -> int | None:
    match = _ROUND_NUMBER_RE.match(round_id)
    return int(match.group(1)) if match else None


def _round_tag(round_id: str) -> str:
    """`"r11-2026-08"` -> `"r11"` -- the short tag an id is built from, e.g. `"r11-selection-8"` (see
    the wire contract's own example). Using the full `round_id` here would make every id needlessly
    long without adding uniqueness: ids only need to be stable *within one response*, which is
    already scoped to a single `round_id`. Falls back to `round_id` verbatim when it does not fit the
    `r<N>-...` convention, the same "degrade rather than guess" rule the rest of this module follows."""
    match = _ROUND_NUMBER_RE.match(round_id)
    return f"r{match.group(1)}" if match else round_id


def _parse_defects_file(text: str, round_id: str, target_round_number: int | None) -> list[RoundFindingData]:
    if target_round_number is None:
        return []
    tag = _round_tag(round_id)
    out: list[RoundFindingData] = []
    for heading, body in _split_h2_sections(text):
        if _defect_round_number(body) != target_round_number:
            continue
        defect_id_match = _DEFECT_ID_RE.match(heading)
        ref = defect_id_match.group(1) if defect_id_match else _slugify(heading)
        out.append(
            RoundFindingData(
                id=f"{tag}-defect-{ref.lower()}",
                round_id=round_id,
                kind="defect",
                title=heading,
                body=body,
                source=f"DEFECTS.md § {ref}",
                carries_forward=_defect_status_carries_forward(body),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def list_findings(
    round_id: str,
    rounds_root: Path | None = None,
    defects_path: Path | None = None,
) -> FindingsData:
    """`/api/competition/rounds/{round_id}/findings`'s data.

    Raises :class:`RoundNotFoundError` when `rounds_root / round_id` is not a directory -- an
    existence check on the round itself, not on any file inside it, so a round that exists but wrote
    nothing parseable down (no `REPORT.md`/`BRIEF.md`/`SELECTION.md`, or files present but no `## `
    sections in them) still returns normally with empty `findings`/`follow_ups`, per the module
    docstring's `sources` note.
    """
    root = rounds_root if rounds_root is not None else ROUNDS_ROOT
    round_dir = root / round_id
    if not round_dir.is_dir():
        raise RoundNotFoundError(round_id)

    findings: list[RoundFindingData] = []
    sources: list[str] = []

    for filename, default_kind in _ROUND_FILES:
        text = _read_text(round_dir / filename)
        if text is None:
            continue
        parsed = _parse_round_file(text, round_id, filename, default_kind)
        if parsed:
            sources.append(filename)
            findings.extend(parsed)

    defects_file = defects_path if defects_path is not None else DEFECTS_PATH
    defects_text = _read_text(defects_file)
    if defects_text is not None:
        parsed_defects = _parse_defects_file(defects_text, round_id, _round_number(round_id))
        if parsed_defects:
            sources.append("DEFECTS.md")
            findings.extend(parsed_defects)

    follow_ups = tuple(f for f in findings if f.carries_forward)
    return FindingsData(
        round_id=round_id,
        findings=tuple(findings),
        follow_ups=follow_ups,
        sources=tuple(sources),
    )
