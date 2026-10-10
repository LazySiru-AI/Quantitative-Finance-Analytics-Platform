"""Reader for a round's hand-authored narrative -- `data/rounds/<round_id>/NARRATIVE.json` -- and the
naming logic for whichever round would run next.

**This is a reader over hand-written prose, not a re-derivation.** Unlike `app.tournament.results`,
which recomputes every figure it serves from typed JSON trade logs, `NARRATIVE.json` is not computed
from anything -- it is a person's account of what a round asked, what happened, and what the owner
overrode, written once and read back verbatim. There is nothing here to recompute and check against a
stored value the way `results.corrected_return` checks `total_return`; the file's prose *is* the
record. What this module *can* enforce is shape: :class:`RoundNarrative` is `extra="forbid"` and
`frozen=True` (this codebase's convention for every response-adjacent model -- see
`app.api.competition_findings.RoundFindingModel`), so a `NARRATIVE.json` with a typo'd or stray key
fails loudly at load time rather than silently dropping the field or being accepted as if the schema
had grown to include it.

**Why a malformed file raises instead of returning `None`.** `load_narrative` returning `None` means
one specific thing: no `NARRATIVE.json` exists for this round, which is a normal, expected state (most
rounds will not have one authored yet). A file that exists but fails to parse -- bad JSON, a missing
required field, an extra key -- is a different condition entirely: something is *wrong* with an
artifact that is supposed to exist, and collapsing that into the same `None` a caller already reads as
"nothing written yet" would hide a real defect behind a state nobody would think to investigate. See
:class:`MalformedNarrativeError`.

**The honesty requirement on `next_round_id`, and why it matters here specifically.**
`strategy-program/PROTOCOL.md` §2 (phase 0/2, "Freeze") states the programme's actual integrity rule:
cards -- and, by the same logic this module's caller extends to the round as a whole -- are committed
*before* any result exists; phase 2 is described there as "the integrity boundary", and a plan edited
after a run starts is not treated as a plan at all: **"A card edited after any result exists is not a
strategy, it is a memory of one."** `next_round_id` below computes the id the next round *would* have
by finding a free directory name -- nothing more. That a name is available says nothing about whether
starting a round under it right now would satisfy phase 0's pre-registration requirement; it only says
the directory does not already exist. A caller must not treat `next_round_id`'s return value as
license to run anything. This is exactly why `app.api.competition_narrative`'s `/next-round` endpoint
exists as a *briefing*, not a launcher: it names the id, then separately reports (via `pre_registered`
and `blockers`) whether a plan has actually been committed for it, so a UI reading this endpoint can
say "not ready" rather than implying readiness merely because a name was computed.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import get_settings
from app.tournament.results import list_round_ids, round_sequence

__all__ = [
    "ROUNDS_ROOT",
    "STRATEGY_ROOT",
    "MalformedNarrativeError",
    "RoundNarrative",
    "load_narrative",
    "next_round_id",
    "plan_path_for",
]

#: Root of the round-record tree -- the same resolution `app.tournament.results.ROUNDS_ROOT` and
#: `app.tournament.findings.ROUNDS_ROOT` use (`app.config.Settings.rounds_dir`, overridable via
#: `INVDASH_ROUNDS_DIR`), read fresh from this module's own namespace on every call (never captured
#: at `def`-time) so a test can `monkeypatch.setattr(narrative, "ROUNDS_ROOT", tmp_path)` the same way
#: the sibling modules are already patched.
ROUNDS_ROOT: Path = get_settings().rounds_dir

#: Where `strategy-program/` lives, for :func:`plan_path_for` and any caller checking whether a round's
#: plan has been committed. Not one of `app.config.Settings`' own fields -- `strategy-program/` is a
#: research directory, not application data, and (per `app.tournament.findings.DEFECTS_PATH`'s own
#: docstring) is not even shipped in the Docker image -- so this resolves relative to
#: `get_settings().repo_root` rather than adding a new setting for a single fixed subdirectory. Same
#: patchable-module-attribute convention as `ROUNDS_ROOT` above.
STRATEGY_ROOT: Path = get_settings().repo_root / "strategy-program"

_NARRATIVE_FILENAME = "NARRATIVE.json"


class MalformedNarrativeError(ValueError):
    """`NARRATIVE.json` exists for a round but does not parse as a :class:`RoundNarrative` -- invalid
    JSON, a missing required field, or (since the model is `extra="forbid"`) an unexpected key.

    Raised with a short, human-readable message rather than letting a bare `pydantic.ValidationError`
    (whose default `str` is a multi-paragraph, field-by-field dump meant for a developer reading a
    traceback) propagate to a caller that just needs to know a round's narrative is broken and why.
    The original `pydantic.ValidationError` is always chained via `__cause__` for anyone who does want
    the full detail.
    """

    def __init__(self, round_id: str, path: Path, reason: str) -> None:
        self.round_id = round_id
        self.path = path
        super().__init__(f"round {round_id!r}'s narrative at {path} is malformed: {reason}")


class RoundNarrative(BaseModel):
    """One round's hand-authored account, verbatim from `NARRATIVE.json` -- no field here is
    recomputed or re-worded by this module; see the module docstring."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    round_id: str
    title: str
    """E.g. `"Round 14 - naming the chooser"`."""
    focus: str
    """One or two sentences: the question the round asked."""
    headline: str
    """One sentence: how it turned out."""
    outcome: str
    """Five to ten lines of plain prose, paragraphs separated by a blank line (`\\n\\n`)."""
    seated: list[str]
    """`agent_id`s seated by this round; `[]` when the round seated nothing."""
    owner_override: str | None
    """What the owner overrode and why, or `None` when there was no override."""
    carries_forward: list[str]
    """What the next round must apply."""
    sources: list[str]
    """Repo-relative file paths the prose above is drawn from."""


def load_narrative(round_id: str, *, rounds_root: Path | None = None) -> RoundNarrative | None:
    """`data/rounds/<round_id>/NARRATIVE.json`, parsed -- `None` when that file does not exist.

    Does not distinguish "the round itself is unknown" from "the round exists but has no narrative
    authored yet" -- both read `None` here, on purpose: this function's only job is to load one file,
    and a `pathlib.Path.is_file()` check cannot tell those two states apart from a missing file alone.
    A caller that needs the distinction (see `app.api.competition_narrative`'s 404 handling) makes its
    own `round_dir.is_dir()` check first.

    Raises :class:`MalformedNarrativeError` -- never a bare `pydantic.ValidationError` -- when the file
    exists but fails to parse as :class:`RoundNarrative`.
    """
    root = rounds_root if rounds_root is not None else ROUNDS_ROOT
    path = root / round_id / _NARRATIVE_FILENAME
    if not path.is_file():
        return None

    text = path.read_text(encoding="utf-8")
    try:
        return RoundNarrative.model_validate_json(text)
    except ValidationError as exc:
        raise MalformedNarrativeError(round_id, path, str(exc)) from exc


def next_round_id(*, rounds_root: Path | None = None) -> str:
    """The round id the next round *would* have: one past the highest existing round number, dated
    with the current year-month, in this programme's `r<N>-<YYYY>-<MM>` shape.

    Reuses `app.tournament.results.round_sequence` for the ordinal (never re-implemented here) --
    see that function's own docstring for why sorting round ids as plain strings is wrong (`"r9-..."
    > "r13-..."` lexicographically) and why it returns the sentinel `-1` for a directory name it
    cannot parse; that sentinel is filtered out below so a stray non-numbered directory under
    `rounds_root` cannot make this function invent a bogus "next" number. With no parseable rounds at
    all, returns `"r1-<current year-month>"`.

    **A free name is not a green light.** See this module's docstring: this function only reports
    which directory name is not yet taken. It says nothing about whether a plan for that round has
    been pre-registered, which is what `strategy-program/PROTOCOL.md` §2 actually requires before a
    round may run. Check :func:`plan_path_for` (or read `/api/competition/next-round`'s
    `pre_registered` field) for that.
    """
    root = rounds_root if rounds_root is not None else ROUNDS_ROOT
    sequences = [n for n in (round_sequence(rid) for rid in list_round_ids(root)) if n >= 1]
    today = dt.date.today()
    year_month = f"{today.year:04d}-{today.month:02d}"
    next_number = (max(sequences) + 1) if sequences else 1
    return f"r{next_number}-{year_month}"


def plan_path_for(round_id: str) -> Path:
    """`strategy-program/ROUND-<N>-PLAN.md` for round `r<N>-...`, resolved under :data:`STRATEGY_ROOT`
    (module-level, patchable the same way :data:`ROUNDS_ROOT` is).

    `N` comes from `app.tournament.results.round_sequence`, reused rather than re-parsed here. This
    function only *names* where a round's plan would live -- it does not check whether the file
    exists; a caller does that itself (`plan_path_for(round_id).is_file()`), which is what
    `/api/competition/next-round`'s `pre_registered` field reports.
    """
    n = round_sequence(round_id)
    return STRATEGY_ROOT / f"ROUND-{n}-PLAN.md"
