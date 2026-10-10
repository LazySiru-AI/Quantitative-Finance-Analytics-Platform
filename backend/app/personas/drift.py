"""Pure diff between two consolidated persona profiles -- so the owner can tell whether a persona's
growing memory is IMPROVING (new claims backed by fresh notes) or just CHURNING (the same handful of
claims getting reworded or re-cited every consolidation, with nothing actually learned).

**No I/O, no store dependency.** The caller loads the two `PersonaProfile` versions (from
`profile_store` / `profile.history/`) and hands both to `diff_profiles`; this module only compares
the objects it is given.

**Matching claims across versions.** A profile is regenerated wholesale on every consolidation, so a
claim's identity is its TEXT, not its position in the tuple. Claims are matched by normalised text
(`_normalise`: lowercased, internal whitespace collapsed to single spaces, leading/trailing
whitespace stripped, then a single pass of trailing punctuation trimmed) so a claim that was merely
reworded -- a trailing period added, casing changed -- is not read as one claim being removed and an
unrelated one being added. Two claims that normalise identically are the "same claim" for diffing
purposes, however differently their surface text reads.

**What counts as a change**, per section (`beliefs` -> "belief", `playbook` -> "playbook",
`methodology` -> "methodology"), independently:

- A normalised text present only in `to` -> `ClaimChange(kind="added")`, carrying `to`'s own text
  and citations (the claim as it now reads).
- A normalised text present only in `from` -> `kind="removed"`, carrying `from`'s text and citations
  (the claim as it read before -- there is no "now" for a claim that no longer exists).
- A normalised text present in BOTH, but the two claims' citation SETS differ -> `kind="recited"`:
  the claim survived but was re-grounded to a different set of notes. Carries `to`'s text and
  citations, since that is the claim's current grounding going forward. Citation comparison is by
  set, not by order or duplicates -- `("n1", "n2")` and `("n2", "n1")` are the same citation set.
- Same normalised text AND the same citation set -> NOT a change; omitted entirely. This is what
  keeps a trailing-period/casing-only rewording (with its grounding untouched) from ever showing up
  as churn.

A claim can therefore never appear as both "added" and "removed" for the same normalised text within
one section -- at most one `ClaimChange` is emitted per normalised text per section.

**Ordering.** `changes` is ordered by section first (`belief`, `playbook`, `methodology`, in that
fixed order regardless of dict/tuple iteration order), then within a section by kind
(`added`, `removed`, `recited`, in that order), then by `text` ascending within a
section+kind group. `added`/`removed`/`recited` are tallies over the final `changes` tuple, so they
always sum to `len(changes)`.
"""

from __future__ import annotations

from typing import Literal

from app.personas.models import ClaimChange, PersonaProfile, ProfileClaim, ProfileDiff

_Section = Literal["belief", "playbook", "methodology"]

#: (attribute on PersonaProfile, section label on ClaimChange), in the fixed order `changes` sorts by.
_SECTIONS: tuple[tuple[str, _Section], ...] = (
    ("beliefs", "belief"),
    ("playbook", "playbook"),
    ("methodology", "methodology"),
)

#: Trimmed from the end of a normalised claim only -- interior punctuation is left alone, this is
#: purely about a trailing "." (or similar) added/dropped between consolidations.
_TRAILING_PUNCT = ".,;:!?"

_KIND_ORDER: dict[str, int] = {"added": 0, "removed": 1, "recited": 2}
_SECTION_ORDER: dict[_Section, int] = {"belief": 0, "playbook": 1, "methodology": 2}


def _normalise(text: str) -> str:
    """Case-insensitive, whitespace-collapsed, trailing-punctuation-trimmed key for matching a claim
    across two profile versions. `"Rates will fall."` and `"  rates   will fall"` normalise to the
    identical `"rates will fall"`."""
    collapsed = " ".join(text.split()).lower()
    return collapsed.rstrip(_TRAILING_PUNCT)


def _section_changes(
    section: _Section,
    from_claims: tuple[ProfileClaim, ...],
    to_claims: tuple[ProfileClaim, ...],
) -> list[ClaimChange]:
    """Every `ClaimChange` for one section, unordered (sorted later once every section has been
    folded together). Claims are keyed by normalised text; when a normalised text repeats within one
    profile's own claims, the last claim in iteration order wins that key -- the same last-wins
    discipline `stances.py` uses for its own dict folds."""
    from_by_norm: dict[str, ProfileClaim] = {_normalise(c.text): c for c in from_claims}
    to_by_norm: dict[str, ProfileClaim] = {_normalise(c.text): c for c in to_claims}

    changes: list[ClaimChange] = []
    for norm_text in from_by_norm.keys() | to_by_norm.keys():
        from_claim = from_by_norm.get(norm_text)
        to_claim = to_by_norm.get(norm_text)

        if from_claim is None and to_claim is not None:
            changes.append(
                ClaimChange(
                    kind="added", section=section, text=to_claim.text, citations=to_claim.citations
                )
            )
        elif to_claim is None and from_claim is not None:
            changes.append(
                ClaimChange(
                    kind="removed",
                    section=section,
                    text=from_claim.text,
                    citations=from_claim.citations,
                )
            )
        elif (
            from_claim is not None
            and to_claim is not None
            and set(from_claim.citations) != set(to_claim.citations)
        ):
            changes.append(
                ClaimChange(
                    kind="recited", section=section, text=to_claim.text, citations=to_claim.citations
                )
            )
        # Both present with an identical citation set falls through here -- not a change.

    return changes


def diff_profiles(from_profile: PersonaProfile, to_profile: PersonaProfile) -> ProfileDiff:
    """What changed in a persona's memory between `from_profile` and `to_profile`. Pure and
    synchronous -- no I/O, no store access; both profiles are assumed already loaded by the caller.
    `persona` is taken from `to_profile.persona` (the two are expected to name the same persona;
    this function does not itself check that they match)."""
    changes: list[ClaimChange] = []
    for attr, section in _SECTIONS:
        changes.extend(
            _section_changes(section, getattr(from_profile, attr), getattr(to_profile, attr))
        )

    changes.sort(key=lambda c: (_SECTION_ORDER[c.section], _KIND_ORDER[c.kind], c.text))

    added = sum(1 for c in changes if c.kind == "added")
    removed = sum(1 for c in changes if c.kind == "removed")
    recited = sum(1 for c in changes if c.kind == "recited")

    return ProfileDiff(
        persona=to_profile.persona,
        from_version=from_profile.version,
        to_version=to_profile.version,
        changes=tuple(changes),
        added=added,
        removed=removed,
        recited=recited,
    )
