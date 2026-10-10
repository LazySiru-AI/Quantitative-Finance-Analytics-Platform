"""Tests for `app.personas.drift` -- the pure `PersonaProfile` -> `PersonaProfile` diff that answers
whether a persona's consolidated memory is improving or just churning.

`_claim`/`_profile` build the minimal `ProfileClaim`/`PersonaProfile` wire models `diff_profiles`
consumes; fixtures are constructed inline per the module's own convention (no store, no I/O).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from datetime import UTC

from app.personas.drift import diff_profiles
from app.personas.models import PersonaProfile, ProfileClaim

_CONSOLIDATED_AT = dt.datetime(2026, 1, 1, tzinfo=UTC)


def _claim(text: str, *citations: str) -> ProfileClaim:
    return ProfileClaim(text=text, citations=citations)


def _profile(
    *,
    version: int,
    beliefs: Sequence[ProfileClaim] = (),
    playbook: Sequence[ProfileClaim] = (),
    methodology: Sequence[ProfileClaim] = (),
) -> PersonaProfile:
    return PersonaProfile(
        persona="testpersona",
        version=version,
        consolidated_at=_CONSOLIDATED_AT,
        note_count=version * 3,
        summary="a summary",
        beliefs=tuple(beliefs),
        playbook=tuple(playbook),
        methodology=tuple(methodology),
        vocabulary=(),
        degraded=False,
        path=f"profile.history/{version}.json",
    )


def test_diff_profiles_added_removed_recited_and_unchanged() -> None:
    """One of each kind, across all three sections, plus two claims that must produce NO change:
    an exact match (same text, same citations) and a claim reworded only by case/trailing period
    with its citations untouched -- normalisation must treat that as the same claim, never a
    spurious add+remove."""
    from_profile = _profile(
        version=1,
        beliefs=[
            _claim("Rates will fall.", "n1"),  # unchanged after normalisation (reworded in `to`)
            _claim("Gold is a safe haven.", "n2"),  # removed
            _claim("Tech leads the market.", "n3"),  # recited (re-grounded in `to`)
        ],
        playbook=[
            _claim("Trim winners at 20%.", "n6"),  # unchanged, byte-identical in `to`
        ],
        methodology=[
            _claim("Uses RSI(14) for entries.", "n7"),  # unchanged, byte-identical in `to`
        ],
    )
    to_profile = _profile(
        version=2,
        beliefs=[
            _claim("rates will fall", "n1"),  # same normalised text + same citations -> no change
            _claim("Tech leads the market", "n4", "n5"),  # same claim, re-cited -> recited
            _claim("Inflation is peaking.", "n8"),  # new -> added
        ],
        playbook=[
            _claim("Trim winners at 20%.", "n6"),
            _claim("Add on breakouts above the 50-day.", "n9"),  # new -> added
        ],
        methodology=[
            _claim("Uses RSI(14) for entries.", "n7"),
            _claim("Uses MACD crossover for exits.", "n10"),  # new -> added
        ],
    )

    diff = diff_profiles(from_profile, to_profile)

    assert diff.persona == "testpersona"
    assert diff.from_version == 1
    assert diff.to_version == 2

    # Exactly 5 changes: nothing spurious from the two unchanged-after-normalisation belief claims,
    # nor from the two byte-identical playbook/methodology claims.
    assert len(diff.changes) == 5
    assert diff.added == 3
    assert diff.removed == 1
    assert diff.recited == 1
    assert diff.added + diff.removed + diff.recited == len(diff.changes)

    # Ordering: by section (belief, playbook, methodology), then added/removed/recited, then text.
    got = [(c.section, c.kind, c.text, c.citations) for c in diff.changes]
    assert got == [
        ("belief", "added", "Inflation is peaking.", ("n8",)),
        ("belief", "removed", "Gold is a safe haven.", ("n2",)),
        ("belief", "recited", "Tech leads the market", ("n4", "n5")),
        ("playbook", "added", "Add on breakouts above the 50-day.", ("n9",)),
        ("methodology", "added", "Uses MACD crossover for exits.", ("n10",)),
    ]

    # No change texts leaked for either unchanged claim.
    changed_texts = {c.text for c in diff.changes}
    assert "Rates will fall." not in changed_texts
    assert "rates will fall" not in changed_texts
    assert "Trim winners at 20%." not in changed_texts
    assert "Uses RSI(14) for entries." not in changed_texts


def test_diff_profiles_no_changes_is_empty() -> None:
    """Two identical profiles (different versions only) produce no changes and all-zero counts."""
    claims = [_claim("Buys the dip on RSI oversold.", "n1", "n2")]
    from_profile = _profile(version=3, beliefs=claims, playbook=claims, methodology=claims)
    to_profile = _profile(version=4, beliefs=claims, playbook=claims, methodology=claims)

    diff = diff_profiles(from_profile, to_profile)

    assert diff.from_version == 3
    assert diff.to_version == 4
    assert diff.changes == ()
    assert (diff.added, diff.removed, diff.recited) == (0, 0, 0)


def test_diff_profiles_citation_order_does_not_trigger_recited() -> None:
    """Citations are compared as a SET: the same citations in a different order (or with a
    duplicate) must not be read as a recite."""
    from_profile = _profile(version=1, beliefs=[_claim("Oil prices matter.", "n1", "n2")])
    to_profile = _profile(version=2, beliefs=[_claim("Oil prices matter.", "n2", "n1", "n1")])

    diff = diff_profiles(from_profile, to_profile)

    assert diff.changes == ()
    assert (diff.added, diff.removed, diff.recited) == (0, 0, 0)
