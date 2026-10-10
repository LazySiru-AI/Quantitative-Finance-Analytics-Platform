"""Every card seated to a book should say what would make its thesis wrong.

`docs/research/programme/thesis-audit.md` read all six seated cards and found that **eleven of
thirteen quantitative thesis claims had never been measured outside the window they were fitted on**,
and that the split ran cleanly along card shape: both allocation-family cards state a falsification
condition in prose, name the document that will hold the number, and the number exists; none of the
four seated `StrategyCard`s states one at all.

The cause is visible in the models themselves. `AllocationCard.thesis`'s docstring has always demanded
that a thesis "say what result would prove it *wrong*". `StrategyCard.thesis`'s never did. The roster
simply reflects which shape was asked.

`falsification` gives that requirement somewhere a test can read it. It carried a strict `xfail` --
the device `test_allocation_card.py` used to pin D8's intended behaviour before the fix existed --
until the four missing clauses were written on 2026-08-30, and the marker came off in the same commit.

**The four written then are retrospective and say so.** They were authored after their cards had live
records, so they are not pre-registrations; each names a measurement that has *not* been run, and each
is traceable to a claim its own thesis already makes rather than inventing new ones. A clause written
with the answer already in hand would be the failure this field exists to prevent, which is why
`test_retrospective_clauses_say_that_they_are_retrospective` enforces the disclosure.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.paperdesk.desk import AGENT_IDS, ROTH_AGENT_IDS, SAVINGS_AGENT_IDS

LIBRARY = pathlib.Path(__file__).resolve().parents[1] / "backend" / "app" / "paper" / "library"

#: Every card the paper desk seats to a real book, across all three purposes. These are the cards a
#: reader sees beside live money, which is why the expectation is enforced here and not over the whole
#: library -- roughly 35 committed JSONs plus the evolution loop's genome population validate against
#: the same models and none of them carries a clause.
SEATED: tuple[str, ...] = (*AGENT_IDS, *SAVINGS_AGENT_IDS, *ROTH_AGENT_IDS)

#: The two that already stated one in prose, before the field existed. Both are allocation-family
#: shapes, and both went on to produce the measured number their clause asked for.
DOCUMENTED: frozenset[str] = frozenset(
    {"spy-schd-agg-gld-bil-atr-tilt", "ladder-sso-vig-bnd"}
)


def _library_cards() -> dict[str, dict[str, object]]:
    """Every card in the library, keyed by `agent_id`.

    Read as JSON rather than validated into a model because the three card shapes have no shared
    base: this test is about a field all three now carry, not about any one of them.
    """
    found: dict[str, dict[str, object]] = {}
    for path in LIBRARY.rglob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):  # pragma: no cover - a malformed card is its own bug
            continue
        agent_id = payload.get("agent_id")
        if isinstance(agent_id, str):
            found[agent_id] = payload
    return found


def _seated_cards() -> dict[str, dict[str, object]]:
    """Just the cards the desk currently seats, keyed by `agent_id`.

    **Resolved live from the roster, never from a list written down here**, because the roster moves:
    on 2026-08-30 alone the trading book seated two `cap126` variants, reverted them when
    `PurposeSpec.horizon_months_max` went 6 -> 9, and unseated `ladder-qld-schd` on a measured
    62.5-month horizon -- three changes in one day. A hard-coded roster in a test would have been
    stale by the afternoon and would fail for a reason that has nothing to do with what it checks.
    """
    return {k: v for k, v in _library_cards().items() if k in SEATED}


def test_every_seated_card_is_found_in_the_library() -> None:
    """Guards the two tests below: a rename would otherwise make them vacuously pass."""
    found = _seated_cards()
    missing = sorted(set(SEATED) - set(found))
    assert not missing, f"seated cards not found in the library: {missing}"
    assert len(SEATED) == len(set(SEATED)), "a card is seated twice"


@pytest.mark.parametrize("agent_id", sorted(DOCUMENTED))
def test_documented_cards_carry_a_falsification_clause(agent_id: str) -> None:
    """The two cards whose thesis already stated one now carry it in the field.

    Asserted separately from the strict `xfail` so that a regression on these two -- the only two
    that have ever met the bar -- fails loudly rather than being absorbed into an expected failure.

    Looked up in the **library**, not the seated roster, deliberately: a card that loses its seat
    should not quietly stop being checked, and with the roster moving several times a day a seat is
    the wrong thing to hang this on. `ladder-qld-schd` was unseated on the day this test was written.
    """
    card = _library_cards()[agent_id]
    clause = card.get("falsification")
    assert isinstance(clause, str) and clause.strip(), (
        f"{agent_id} lost its falsification clause"
    )
    # Long enough to be a condition rather than a gesture. Both real clauses run past 850 characters;
    # the bar is set well under that so it tests for presence, not for a house style.
    assert len(clause) > 120, f"{agent_id}'s falsification clause is too short to be a condition"


def test_every_seated_card_carries_a_falsification_clause() -> None:
    """Carried `xfail(strict=True)` from the thesis audit until the four missing clauses were
    written on 2026-08-30; un-marked in the same commit that wrote them, as its own reason required.

    **This is now a ratchet.** Seating a card without a falsification clause fails here, which is the
    only point at which the requirement is cheap to meet -- before the card has a live record to
    write the clause around.
    """
    found = _seated_cards()
    without = sorted(
        agent_id
        for agent_id, card in found.items()
        if not (isinstance(card.get("falsification"), str) and str(card["falsification"]).strip())
    )
    assert not without, f"seated cards with no falsification clause: {without}"


@pytest.mark.parametrize("agent_id", sorted(SEATED))
def test_retrospective_clauses_say_that_they_are_retrospective(agent_id: str) -> None:
    """The four clauses written by the audit were written **after** their cards had live records, so
    they are not pre-registrations and each says so in its own first sentence.

    That disclosure is the whole reason they are admissible. A falsification condition written with
    the answer already in hand is the failure `PROTOCOL.md` §2 exists to prevent, and §4 of the
    consolidated report records the sharper version: pre-registration protects a claim from moving
    afterwards and does nothing about one that was wrong going in. A retrospective clause that did
    not announce itself would be exactly that failure wearing the field's authority.
    """
    clause = str(_seated_cards()[agent_id].get("falsification") or "")
    if not clause.startswith("Added "):
        return  # written by the card's own author, in its thesis, before any result existed
    assert "NOT a pre-registration" in clause, (
        f"{agent_id}'s clause was added retrospectively but does not say so"
    )


def test_falsification_round_trips_through_the_strategy_card_model() -> None:
    """The field survives validate -> dump -> validate, which is how a card crosses a process
    boundary in `app.evolution.execute`."""
    from app.tournament.models import StrategyCard

    card = _library_cards()["C-trend"]
    parsed = StrategyCard.model_validate({**card, "falsification": "wrong if X does not follow Y."})
    assert parsed.falsification == "wrong if X does not follow Y."
    again = StrategyCard.model_validate_json(parsed.model_dump_json())
    assert again.falsification == parsed.falsification


def test_falsification_defaults_to_none_so_existing_cards_still_validate() -> None:
    """Roughly 35 committed cards carry no such key. Adding the field must not be a migration."""
    from app.tournament.models import StrategyCard

    card = dict(_library_cards()["C-trend"])
    card.pop("falsification", None)
    assert StrategyCard.model_validate(card).falsification is None
