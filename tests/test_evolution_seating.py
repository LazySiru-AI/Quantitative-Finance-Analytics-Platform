"""The paper-desk seat approval queue: `app.evolution.promotion`'s pending-seat functions, the HTTP
routes in `app.api.evolution` that front them, and `tools/migrate_seat_pipeline.py`'s one-shot fix for
the day the collapsed decision let 22 cards get seated with nobody reviewing them.

These cover the gate the owner asked for after finding that the loop had seated **25 cards** (18
roth, 7 trading) on the paper desk with no person involved, and the second gate the owner asked for
after finding that the *first* gate's single yes/no still let **22 cards** get auto-approved straight
onto the desk on 2026-08-26. `LoopConfig.seat_on_paper_desk` was the only control for the first, and
a single-step `approve` was the only control for the second -- both are properties of something other
than the particular card in front of a reviewer, which is exactly why neither one held.

The behaviours worth testing hardest are the ones that are easy to get subtly wrong:

* **A decided request is never re-opened**, whichever of the four decided `SeatStatus` values it
  landed in. `request_seat` is called every time a genome clears the gate, and a genome can clear it
  again in a later generation. If a decided row could quietly return to `"pending"`, a tireless
  searcher would re-ask until somebody clicked something, which defeats the gate rather than
  implementing it.
* **Only `seat_pending_seat` writes the roster overlay.** `shelve_pending_seat` keeps and names a
  card without ever touching `roster_overlay.json` -- that is the entire point of splitting one
  decision into two.
* **The queue is written before the overlay.** If seating fails, the record must already say the
  decision happened; the opposite order can seat a card whose decision was never recorded.
* **Every illegal transition is refused with a message a person can act on**, naming the row's actual
  status and what is legal from it -- not a generic failure.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import tools.migrate_seat_pipeline as migrate_seat_pipeline
from app.api import evolution as evolution_api
from app.config import Settings
from app.evolution import loop as loop_module
from app.evolution import promotion
from app.evolution.models import PendingSeat, pending_seats_path, roster_overlay_path
from app.tournament.purposes import Purpose


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A `Settings` whose `data_dir` is empty, so `loop_root` and both queue/overlay files start
    absent -- the state a first-ever request has to cope with."""
    return Settings(repo_root=tmp_path, data_dir=tmp_path / "data")


def _seat(genome_id: str = "g0001-abc", purpose: Purpose = Purpose.ROTH) -> PendingSeat:
    return PendingSeat(
        genome_id=genome_id,
        agent_id=genome_id,
        purpose=purpose,
        requested_at=dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC),
        generations=(4, 5),
        window_sets=(("gfc", "recent"), ("gfc", "chop-2015")),
        median_excess=Decimal("0.3051"),
        holdout_median_excess=Decimal("0.2031"),
        q_value=0.0004,
        library_path="backend/app/paper/library/candidates/g0001-abc.json",
        reason="cleared generation 5's gate",
    )


class TestReadPendingSeats:
    def test_absent_file_is_an_empty_queue_not_an_error(self, settings: Settings) -> None:
        assert promotion.read_pending_seats(settings) == ()

    def test_unparseable_file_degrades_to_empty(self, settings: Settings) -> None:
        path = pending_seats_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        assert promotion.read_pending_seats(settings) == ()

    def test_one_malformed_row_does_not_discard_the_others(self, settings: Settings) -> None:
        """A single bad record must not hide every other pending approval. Dropping the whole file
        would silently conceal work waiting on a person, which is worse than dropping one row."""
        promotion.request_seat(_seat("g0001-abc"), settings=settings)
        path = pending_seats_path(settings)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["requests"].append({"genome_id": "broken"})  # missing every required field
        path.write_text(json.dumps(raw), encoding="utf-8")

        seats = promotion.read_pending_seats(settings)
        assert [s.genome_id for s in seats] == ["g0001-abc"]

    def test_newest_first(self, settings: Settings) -> None:
        old = _seat("g-old").model_copy(
            update={"requested_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC)}
        )
        new = _seat("g-new").model_copy(
            update={"requested_at": dt.datetime(2026, 8, 1, tzinfo=dt.UTC)}
        )
        promotion.request_seat(old, settings=settings)
        promotion.request_seat(new, settings=settings)
        assert [s.genome_id for s in promotion.read_pending_seats(settings)] == ["g-new", "g-old"]


class TestRequestSeat:
    def test_a_request_starts_pending_and_seats_nothing(self, settings: Settings) -> None:
        promotion.request_seat(_seat(), settings=settings)
        (row,) = promotion.read_pending_seats(settings)
        assert row.status == "pending"
        assert row.decided_at is None
        assert not roster_overlay_path(settings).exists(), "filing a request must not touch the desk"

    def test_is_idempotent(self, settings: Settings) -> None:
        promotion.request_seat(_seat(), settings=settings)
        promotion.request_seat(_seat(), settings=settings)
        assert len(promotion.read_pending_seats(settings)) == 1

    def test_never_reopens_a_rejected_genome(self, settings: Settings) -> None:
        """The searcher must not be able to wear a reviewer down by re-asking. A genome that clears
        the gate again after rejection stays rejected until a person deliberately changes it."""
        promotion.request_seat(_seat(), settings=settings)
        promotion.reject_pending_seat("g0001-abc", note="too concentrated", settings=settings)

        returned = promotion.request_seat(_seat(), settings=settings)

        assert returned.status == "rejected"
        (row,) = promotion.read_pending_seats(settings)
        assert row.status == "rejected"
        assert row.decided_note == "too concentrated"

    @pytest.mark.parametrize("terminal_status", ["shelved", "seated", "rejected", "retired"])
    def test_never_reopens_any_decided_genome(
        self, settings: Settings, terminal_status: str
    ) -> None:
        """`SeatStatus` has four decided values, not one -- `shelved`, `seated`, `rejected` and
        `retired` all count as decided, and `request_seat` must refuse to re-open every one of them,
        not just the historical `rejected` case."""
        promotion.request_seat(_seat(), settings=settings)
        _seed_status(settings, "g0001-abc", terminal_status, note="already decided")

        returned = promotion.request_seat(_seat(), settings=settings)

        assert returned.status == terminal_status
        assert len(promotion.read_pending_seats(settings)) == 1


class TestLegalTransitions:
    """Every legal edge in the state machine:

    ```
    [pending] --shelve--> [shelved] --seat--> [seated]
        |                     |
        +--reject-->          +--retire-->
     [rejected]             [retired]
    ```
    """

    def test_shelve_from_pending(self, settings: Settings) -> None:
        promotion.request_seat(_seat(), settings=settings)
        decided = promotion.shelve_pending_seat("g0001-abc", note="worth keeping", settings=settings)

        assert decided.status == "shelved"
        assert decided.decided_at is not None
        assert decided.decided_note == "worth keeping"

    def test_reject_from_pending(self, settings: Settings) -> None:
        promotion.request_seat(_seat(), settings=settings)
        decided = promotion.reject_pending_seat("g0001-abc", note="no", settings=settings)

        assert decided.status == "rejected"
        assert decided.decided_note == "no"

    def test_seat_from_shelved(self, settings: Settings) -> None:
        promotion.request_seat(_seat(), settings=settings)
        promotion.shelve_pending_seat("g0001-abc", settings=settings)

        decided = promotion.seat_pending_seat("g0001-abc", note="seat it", settings=settings)

        assert decided.status == "seated"
        assert decided.decided_note == "seat it"

    def test_retire_from_shelved(self, settings: Settings) -> None:
        promotion.request_seat(_seat(), settings=settings)
        promotion.shelve_pending_seat("g0001-abc", settings=settings)

        decided = promotion.retire_pending_seat("g0001-abc", note="taking it off", settings=settings)

        assert decided.status == "retired"
        assert decided.decided_note == "taking it off"

    def test_seat_writes_the_overlay_and_shelve_does_not(self, settings: Settings) -> None:
        promotion.request_seat(_seat(), settings=settings)

        promotion.shelve_pending_seat("g0001-abc", settings=settings)
        assert not roster_overlay_path(settings).exists(), "shelving must not touch the desk"
        assert "g0001-abc" not in promotion.read_overlay(settings).get("roth", ())

        promotion.seat_pending_seat("g0001-abc", settings=settings)
        assert "g0001-abc" in promotion.read_overlay(settings)["roth"]

    def test_retire_does_not_write_the_overlay(self, settings: Settings) -> None:
        promotion.request_seat(_seat(), settings=settings)
        promotion.shelve_pending_seat("g0001-abc", settings=settings)
        promotion.retire_pending_seat("g0001-abc", settings=settings)

        assert "g0001-abc" not in promotion.read_overlay(settings).get("roth", ())

    def test_seat_records_the_decision_before_seating(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If `seat_on_desk` blows up, the decision must already be on record -- a state a person can
        see and retry. The other order seats a card whose decision was never written down."""
        promotion.request_seat(_seat(), settings=settings)
        promotion.shelve_pending_seat("g0001-abc", settings=settings)

        def boom(*_args: object, **_kwargs: object) -> bool:
            raise OSError("disk full")

        monkeypatch.setattr(promotion, "seat_on_desk", boom)
        with pytest.raises(OSError):
            promotion.seat_pending_seat("g0001-abc", settings=settings)

        assert promotion.read_pending_seats(settings)[0].status == "seated"

    def test_shelving_is_additive_to_a_hand_authored_overlay(self, settings: Settings) -> None:
        promotion.seat_on_desk("hand-authored", Purpose.ROTH, settings=settings)
        promotion.request_seat(_seat(), settings=settings)
        promotion.shelve_pending_seat("g0001-abc", settings=settings)
        promotion.seat_pending_seat("g0001-abc", settings=settings)

        assert set(promotion.read_overlay(settings)["roth"]) == {"hand-authored", "g0001-abc"}

    def test_other_rows_survive_a_decision(self, settings: Settings) -> None:
        promotion.request_seat(_seat("g-a"), settings=settings)
        promotion.request_seat(_seat("g-b", Purpose.TRADING), settings=settings)
        promotion.shelve_pending_seat("g-a", settings=settings)

        by_id = {s.genome_id: s for s in promotion.read_pending_seats(settings)}
        assert by_id["g-a"].status == "shelved"
        assert by_id["g-b"].status == "pending"
        assert "g-b" not in promotion.read_overlay(settings).get("trading", ())


def _seed_status(
    settings: Settings, genome_id: str, status: str, *, note: str = ""
) -> None:
    """Force a row straight to `status`, bypassing the legality table -- for illegal-transition tests
    that need to start from a status the state machine would not let a legal call reach directly
    (e.g. `"seated"` without first shelving), and for `TestRequestSeat`'s decided-status coverage."""
    seats = list(promotion.read_pending_seats(settings))
    updated = [
        s.model_copy(
            update={
                "status": status,
                "decided_at": dt.datetime(2026, 8, 26, 13, 0, tzinfo=dt.UTC),
                "decided_note": note,
            }
        )
        if s.genome_id == genome_id
        else s
        for s in seats
    ]
    path = pending_seats_path(settings)
    payload = {"version": 1, "requests": [json.loads(s.model_dump_json()) for s in updated]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


#: `to_status -> (function, required "from" status, sibling verbs shown in the error message)`.
#: Mirrors `app.evolution.promotion._REQUIRED_FROM` / `_TRANSITIONS_FROM` exactly -- if this table and
#: the module's own table ever disagree, these tests catch it rather than the message format doing so
#: silently.
_TRANSITION_TABLE: dict[str, tuple[object, str, str]] = {
    "shelved": (promotion.shelve_pending_seat, "pending", "shelved or rejected"),
    "rejected": (promotion.reject_pending_seat, "pending", "shelved or rejected"),
    "seated": (promotion.seat_pending_seat, "shelved", "seated or retired"),
    "retired": (promotion.retire_pending_seat, "shelved", "seated or retired"),
}

_ALL_STATUSES = ("pending", "shelved", "seated", "rejected", "retired")

_ILLEGAL_CASES = [
    (current, to)
    for to, (_fn, required_from, _verbs) in _TRANSITION_TABLE.items()
    for current in _ALL_STATUSES
    if current != required_from
]


class TestIllegalTransitions:
    @pytest.mark.parametrize("current_status,to_status", _ILLEGAL_CASES)
    def test_illegal_transition_raises_with_a_message_naming_state_and_legal_moves(
        self, settings: Settings, current_status: str, to_status: str
    ) -> None:
        promotion.request_seat(_seat(), settings=settings)
        if current_status != "pending":
            _seed_status(settings, "g0001-abc", current_status)
        fn, required_from, verbs = _TRANSITION_TABLE[to_status]

        with pytest.raises(promotion.PendingSeatIllegalTransition) as exc_info:
            fn("g0001-abc", settings=settings)  # type: ignore[operator]

        message = str(exc_info.value)
        assert f"g0001-abc is '{current_status}'" in message
        assert f"only '{required_from}' may be {verbs}" in message

        # The row itself is untouched by a refused transition.
        row = promotion.read_pending_seats(settings)[0]
        assert row.status == current_status

    @pytest.mark.parametrize(
        "fn",
        [
            promotion.shelve_pending_seat,
            promotion.reject_pending_seat,
            promotion.seat_pending_seat,
            promotion.retire_pending_seat,
        ],
    )
    def test_deciding_an_unknown_genome_raises_not_found(
        self, settings: Settings, fn: object
    ) -> None:
        with pytest.raises(promotion.PendingSeatNotFound):
            fn("nobody", settings=settings)  # type: ignore[operator]

    def test_already_decided_is_a_pending_seat_already_decided(self, settings: Settings) -> None:
        """`PendingSeatAlreadyDecided` is kept as an alias of `PendingSeatIllegalTransition` so any
        existing `except PendingSeatAlreadyDecided` still catches this -- see the alias's own comment
        in `app.evolution.promotion`."""
        promotion.request_seat(_seat(), settings=settings)
        promotion.reject_pending_seat("g0001-abc", note="first call", settings=settings)

        with pytest.raises(promotion.PendingSeatAlreadyDecided):
            promotion.reject_pending_seat("g0001-abc", note="second call", settings=settings)

        assert promotion.PendingSeatAlreadyDecided is promotion.PendingSeatIllegalTransition
        row = promotion.read_pending_seats(settings)[0]
        assert row.status == "rejected"
        assert row.decided_note == "first call"


class TestMigrateSeatedToPending:
    """Cards the loop seated before the gate existed must end up in the queue, not grandfathered.

    Grandfathering would have meant the rule applied only to cards promoted after an arbitrary
    moment -- not something anyone could state later without checking a commit timestamp.
    """

    def _promotion_line(self, settings: Settings, agent_id: str, purpose: Purpose) -> None:
        path = settings.data_dir / "loop" / "promotions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "genome_id": agent_id,
            "agent_id": agent_id,
            "purpose": purpose.value,
            "promoted_at": "2026-08-25T04:30:53.650130Z",
            "generations": [9, 13],
            "window_sets": [["gfc", "recent"], ["gfc", "chop-2015"]],
            "median_excess": "0.3051",
            "holdout_median_excess": "0.2031",
            "q_value": 0.00004,
            "library_path": f"backend/app/paper/library/candidates/{agent_id}.json",
            "seated": True,
            "reason": "cleared generation 13's gate",
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    def test_moves_every_seated_card_off_the_desk_and_into_the_queue(
        self, settings: Settings
    ) -> None:
        promotion.seat_on_desk("g-a", Purpose.ROTH, settings=settings)
        promotion.seat_on_desk("g-b", Purpose.TRADING, settings=settings)
        self._promotion_line(settings, "g-a", Purpose.ROTH)
        self._promotion_line(settings, "g-b", Purpose.TRADING)

        created = promotion.migrate_seated_to_pending(settings=settings)

        assert {s.genome_id for s in created} == {"g-a", "g-b"}
        assert all(s.status == "pending" for s in promotion.read_pending_seats(settings))
        overlay = promotion.read_overlay(settings)
        assert overlay["roth"] == () and overlay["trading"] == (), "the desk must be cleared"

    def test_carries_the_real_evidence_from_the_promotion_record(self, settings: Settings) -> None:
        promotion.seat_on_desk("g-a", Purpose.ROTH, settings=settings)
        self._promotion_line(settings, "g-a", Purpose.ROTH)

        (row,) = promotion.migrate_seated_to_pending(settings=settings)

        assert row.median_excess == Decimal("0.3051")
        assert row.holdout_median_excess == Decimal("0.2031")
        assert row.generations == (9, 13)
        assert "seated automatically before approval was required" in row.reason

    def test_a_seat_with_no_promotion_record_is_still_migrated_and_says_so(
        self, settings: Settings
    ) -> None:
        """An unexplained seat is the *most* important one for a person to look at, so it must not be
        the one case that silently stays on the desk."""
        promotion.seat_on_desk("mystery", Purpose.ROTH, settings=settings)

        (row,) = promotion.migrate_seated_to_pending(settings=settings)

        assert row.status == "pending"
        assert "no promotion record" in row.reason
        assert promotion.read_overlay(settings)["roth"] == ()

    def test_is_idempotent_and_does_not_resurrect_a_rejection(self, settings: Settings) -> None:
        promotion.seat_on_desk("g-a", Purpose.ROTH, settings=settings)
        self._promotion_line(settings, "g-a", Purpose.ROTH)
        promotion.migrate_seated_to_pending(settings=settings)
        promotion.reject_pending_seat("g-a", note="no", settings=settings)

        assert promotion.migrate_seated_to_pending(settings=settings) == ()
        assert promotion.read_pending_seats(settings)[0].status == "rejected"
        assert "g-a" not in promotion.read_overlay(settings).get("roth", ())

    def test_an_empty_desk_is_a_no_op(self, settings: Settings) -> None:
        assert promotion.migrate_seated_to_pending(settings=settings) == ()


class TestSeatOnDeskHasOneCaller:
    def test_only_the_seat_transition_seats_a_card(self) -> None:
        """**The structural half of "nothing reaches the paper desk without both decisions".**

        `seat_on_desk` is the only writer of the roster overlay, so the guarantee holds exactly as
        long as `seat_pending_seat` is its only caller -- `shelve_pending_seat`,
        `reject_pending_seat` and `retire_pending_seat` must never reach it. That is true today by
        construction rather than by any check, which is precisely the kind of invariant that decays
        silently -- someone adds a second call site for a good local reason and the queue quietly
        stops being the only door. This test fails the moment that happens.

        Parsed rather than grepped so a mention in a docstring or a comment (there are several) does
        not count as a call.
        """
        import ast
        from pathlib import Path

        backend = Path(__file__).resolve().parents[1] / "backend" / "app"
        callers: list[str] = []
        for path in backend.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = (
                    func.id
                    if isinstance(func, ast.Name)
                    else func.attr
                    if isinstance(func, ast.Attribute)
                    else None
                )
                if name != "seat_on_desk":
                    continue
                enclosing = next(
                    (
                        n.name
                        for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef)
                        and n.lineno <= node.lineno
                        and (n.end_lineno or n.lineno) >= node.lineno
                    ),
                    "<module>",
                )
                callers.append(f"{path.name}:{enclosing}")

        assert callers == ["promotion.py:seat_pending_seat"], (
            "seat_on_desk must be reachable only through seat_pending_seat; found: " + str(callers)
        )


# ---------------------------------------------------------------------------
# The same card under two ids -- found in the live queue, not by a test
# ---------------------------------------------------------------------------


class TestSameCardUnderTwoIds:
    """`genome_id_for` mints `g{generation}-{content_digest}`, hashing only the content. A card the
    loop rediscovers at a later generation therefore arrives with a **different id and an identical
    digest**, and anything keyed on `genome_id` alone reads it as an unrelated candidate.

    That is not a hypothetical. A browser pass over the live queue found **25 requests holding 22
    distinct strategies**: three pairs of byte-identical cards whose rows agreed on every field,
    including the generations that promoted them. Nothing on screen distinguished them, so approving
    both would have double-weighted one strategy on the desk. Measured across the whole loop, **47 of
    1,701 distinct card contents have been minted under more than one id**, three of them under three.
    """

    def test_a_rediscovered_card_does_not_file_a_second_request(self, settings: Settings) -> None:
        first = _seat("g1809-145d2d5dbfeb")
        promotion.request_seat(first, settings=settings)

        # Same content, later generation -- what the loop actually produced.
        returned = promotion.request_seat(_seat("g1817-145d2d5dbfeb"), settings=settings)

        seats = promotion.read_pending_seats(settings)
        assert [s.genome_id for s in seats] == ["g1809-145d2d5dbfeb"]
        assert returned.genome_id == "g1809-145d2d5dbfeb", "must return the row already on file"

    def test_a_rejection_cannot_be_re_asked_under_a_new_generation(self, settings: Settings) -> None:
        """The rejection guard's back door.

        `request_seat` already refused to re-open a decided row, but only by id -- so rejecting
        `g1809-<digest>` left the loop free to rediscover the same traits and ask again as
        `g1817-<digest>`. That is exactly the "wear the reviewer down by re-asking" failure the
        original guard exists to prevent, reached by a different route.
        """
        promotion.request_seat(_seat("g1809-145d2d5dbfeb"), settings=settings)
        promotion.reject_pending_seat("g1809-145d2d5dbfeb", settings=settings, note="no")

        promotion.request_seat(_seat("g1817-145d2d5dbfeb"), settings=settings)

        seats = promotion.read_pending_seats(settings)
        assert [s.genome_id for s in seats] == ["g1809-145d2d5dbfeb"]
        assert seats[0].status == "rejected"

    def test_a_genuinely_different_card_still_files(self, settings: Settings) -> None:
        """The guard must key on content, not on the generation prefix -- otherwise it would collapse
        every card minted in the same generation."""
        promotion.request_seat(_seat("g1809-145d2d5dbfeb"), settings=settings)
        promotion.request_seat(_seat("g1809-ffffffffffff"), settings=settings)

        assert len(promotion.read_pending_seats(settings)) == 2


class TestRepairPendingSeats:
    def test_collapses_duplicates_keeping_the_earliest(self, settings: Settings) -> None:
        early = _seat("g1809-145d2d5dbfeb").model_copy(
            update={"requested_at": dt.datetime(2026, 8, 1, tzinfo=dt.UTC)}
        )
        late = _seat("g1817-145d2d5dbfeb").model_copy(
            update={"requested_at": dt.datetime(2026, 8, 20, tzinfo=dt.UTC)}
        )
        _write_raw(settings, [early, late])

        repair = promotion.repair_pending_seats(settings)

        assert repair.collapsed == (("g1817-145d2d5dbfeb", "g1809-145d2d5dbfeb"),)
        assert [s.genome_id for s in promotion.read_pending_seats(settings)] == [
            "g1809-145d2d5dbfeb"
        ]

    def test_a_decided_row_outranks_an_earlier_pending_one(self, settings: Settings) -> None:
        """A decision is the only thing in this file a person made, and the only thing that cannot be
        recreated by re-running the loop. It survives even when it is the newer row."""
        pending_early = _seat("g1809-145d2d5dbfeb").model_copy(
            update={"requested_at": dt.datetime(2026, 8, 1, tzinfo=dt.UTC)}
        )
        decided_late = _seat("g1817-145d2d5dbfeb").model_copy(
            update={
                "requested_at": dt.datetime(2026, 8, 20, tzinfo=dt.UTC),
                "status": "rejected",
                "decided_at": dt.datetime(2026, 8, 21, tzinfo=dt.UTC),
                "decided_note": "too concentrated",
            }
        )
        _write_raw(settings, [pending_early, decided_late])

        promotion.repair_pending_seats(settings)

        (row,) = promotion.read_pending_seats(settings)
        assert row.genome_id == "g1817-145d2d5dbfeb"
        assert row.status == "rejected"
        assert row.decided_note == "too concentrated"

    def test_relabels_a_fraction_printed_under_a_pp_label(self, settings: Settings) -> None:
        """The units bug, as it reached the screen.

        `clears_gate` compares a fraction against a margin in points and converts for it; the sentence
        describing that comparison did not. Every record written before the fix reads as a card
        *failing* the gate it just passed -- printed directly beneath a correct "+25.72%"."""
        stale = _seat("g1809-145d2d5dbfeb").model_copy(
            update={
                "median_excess": Decimal("0.2572208744347156740113537958"),
                "reason": (
                    "cleared generation 1833's gate (median excess "
                    "0.2572208744347156740113537958pp > 21.2pp margin) with 2 distinct window sets"
                ),
            }
        )
        _write_raw(settings, [stale])

        repair = promotion.repair_pending_seats(settings)

        assert repair.relabelled == ("g1809-145d2d5dbfeb",)
        (row,) = promotion.read_pending_seats(settings)
        assert "median excess 25.72pp > 21.2pp margin" in row.reason
        assert "0.2572208744347156740113537958pp" not in row.reason
        assert row.median_excess == Decimal("0.2572208744347156740113537958"), (
            "the authoritative field is not touched -- only the sentence describing it"
        )

    def test_leaves_a_reason_alone_when_the_number_does_not_match_the_stored_median(
        self, settings: Settings
    ) -> None:
        """The guard against rewriting anything but the known bug: a hand-written note, or a reason
        already in points, must survive untouched."""
        handwritten = _seat("g1809-145d2d5dbfeb").model_copy(
            update={
                "median_excess": Decimal("0.2572"),
                "reason": "cleared generation 1833's gate (median excess 25.72pp > 21.2pp margin)",
            }
        )
        _write_raw(settings, [handwritten])

        repair = promotion.repair_pending_seats(settings)

        assert repair.relabelled == ()
        (row,) = promotion.read_pending_seats(settings)
        assert row.reason == handwritten.reason

    def test_is_idempotent_and_writes_nothing_when_clean(self, settings: Settings) -> None:
        promotion.request_seat(_seat("g0001-abc"), settings=settings)
        before = pending_seats_path(settings).read_text(encoding="utf-8")

        repair = promotion.repair_pending_seats(settings)

        assert repair.changed is False
        assert pending_seats_path(settings).read_text(encoding="utf-8") == before

    def test_an_empty_queue_is_not_an_error(self, settings: Settings) -> None:
        assert promotion.repair_pending_seats(settings).changed is False


def _write_raw(settings: Settings, seats: list[PendingSeat]) -> None:
    """Write rows straight to disk, bypassing `request_seat`.

    Necessary because `request_seat` now *prevents* the duplicate these tests repair -- the file
    under repair is one written before that guard existed, which is exactly the migration's job.
    """
    path = pending_seats_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"requests": [json.loads(s.model_dump_json()) for s in seats]}),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# The HTTP layer: app.api.evolution's five pending-seat decision routes.
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """A bare app around just the evolution router, the same minimal shape
    `tests/test_api_evolution.py` uses for its own `app` fixture -- `app.main` is not exercised here."""
    fastapi_app = FastAPI()
    fastapi_app.include_router(evolution_api.router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """`_settings()` in `app.api.evolution` reads `loop_module.get_settings()` at call time (see that
    function's own docstring for why), so patching it there -- not importing a separate `Settings` --
    is what makes every route in this file operate against the same `tmp_path`-backed `settings`
    fixture the promotion-layer tests above use."""
    monkeypatch.setattr(loop_module, "get_settings", lambda: settings)
    return TestClient(app)


class TestPendingSeatRoutes:
    def test_shelve_then_seat_end_to_end(self, client: TestClient, settings: Settings) -> None:
        promotion.request_seat(_seat(), settings=settings)

        shelved = client.post("/api/competition/loop/pending-seats/g0001-abc/shelve", json={"note": "keep"})
        assert shelved.status_code == 200
        assert shelved.json()["status"] == "shelved"
        assert "g0001-abc" not in promotion.read_overlay(settings).get("roth", ())

        seated = client.post("/api/competition/loop/pending-seats/g0001-abc/seat", json={"note": "go"})
        assert seated.status_code == 200
        assert seated.json()["status"] == "seated"
        assert "g0001-abc" in promotion.read_overlay(settings)["roth"]

    def test_reject_from_pending(self, client: TestClient, settings: Settings) -> None:
        promotion.request_seat(_seat(), settings=settings)
        response = client.post("/api/competition/loop/pending-seats/g0001-abc/reject")
        assert response.status_code == 200
        assert response.json()["status"] == "rejected"

    def test_retire_from_shelved(self, client: TestClient, settings: Settings) -> None:
        promotion.request_seat(_seat(), settings=settings)
        promotion.shelve_pending_seat("g0001-abc", settings=settings)
        response = client.post("/api/competition/loop/pending-seats/g0001-abc/retire")
        assert response.status_code == 200
        assert response.json()["status"] == "retired"

    def test_unknown_genome_is_404_on_every_route(self, client: TestClient) -> None:
        for action in ("shelve", "reject", "seat", "retire", "approve"):
            response = client.post(f"/api/competition/loop/pending-seats/nobody/{action}")
            assert response.status_code == 404, action

    def test_illegal_transition_is_409_naming_the_state(
        self, client: TestClient, settings: Settings
    ) -> None:
        promotion.request_seat(_seat(), settings=settings)
        # `seat` is legal only from "shelved"; the row is still "pending".
        response = client.post("/api/competition/loop/pending-seats/g0001-abc/seat")
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "g0001-abc is 'pending'" in detail
        assert "only 'shelved' may be seated or retired" in detail

    def test_redeciding_is_409(self, client: TestClient, settings: Settings) -> None:
        promotion.request_seat(_seat(), settings=settings)
        promotion.reject_pending_seat("g0001-abc", settings=settings)
        response = client.post("/api/competition/loop/pending-seats/g0001-abc/reject")
        assert response.status_code == 409

    def test_deprecated_approve_alias_lands_in_shelved_not_seated(
        self, client: TestClient, settings: Settings
    ) -> None:
        """The alias exists so an old client cannot seat a card in one step -- it must resolve to the
        *safer* of the two stages."""
        promotion.request_seat(_seat(), settings=settings)

        response = client.post("/api/competition/loop/pending-seats/g0001-abc/approve")

        assert response.status_code == 200
        assert response.json()["status"] == "shelved"
        assert response.headers.get("deprecation") == "true"
        assert "g0001-abc" not in promotion.read_overlay(settings).get("roth", ())

    def test_get_pending_seats_reflects_the_five_value_enum(
        self, client: TestClient, settings: Settings
    ) -> None:
        promotion.request_seat(_seat(), settings=settings)
        promotion.shelve_pending_seat("g0001-abc", settings=settings)

        response = client.get("/api/competition/loop/pending-seats")
        assert response.status_code == 200
        (row,) = response.json()["requests"]
        assert row["status"] == "shelved"


# ---------------------------------------------------------------------------
# tools/migrate_seat_pipeline.py -- approved -> shelved, and the overlay ids that came from it.
# ---------------------------------------------------------------------------


class TestMigrateSeatPipelineScript:
    def _seed_approved_row(
        self, settings: Settings, genome_id: str, purpose: Purpose, *, note: str = ""
    ) -> None:
        """Write a raw `"approved"` row -- the retired status this script exists to find. Written by
        hand rather than through `PendingSeat`/`request_seat`: `SeatStatus` no longer accepts
        `"approved"`, so the model this script has to migrate *away from* cannot be constructed
        through the typed API any more than the script itself can read it that way."""
        path = pending_seats_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict = {"version": 1, "requests": []}
        if path.is_file():
            existing = json.loads(path.read_text(encoding="utf-8"))
        row = json.loads(_seat(genome_id, purpose).model_dump_json())
        row["status"] = "approved"
        row["decided_at"] = "2026-08-26T09:00:49Z"
        row["decided_note"] = note
        existing["requests"].append(row)
        path.write_text(json.dumps(existing), encoding="utf-8")

    def test_dry_run_reports_but_writes_nothing(self, settings: Settings) -> None:
        self._seed_approved_row(settings, "g0001-abc", Purpose.ROTH)
        promotion.seat_on_desk("g0001-abc", Purpose.ROTH, settings=settings)
        before_pending = pending_seats_path(settings).read_text(encoding="utf-8")
        before_overlay = roster_overlay_path(settings).read_text(encoding="utf-8")

        report = migrate_seat_pipeline.run_migration(settings=settings, apply=False)

        assert report.shelved == [("g0001-abc", "g0001-abc")]
        assert report.overlay_removed == [("roth", "g0001-abc")]
        assert pending_seats_path(settings).read_text(encoding="utf-8") == before_pending
        assert roster_overlay_path(settings).read_text(encoding="utf-8") == before_overlay

    def test_apply_shelves_the_row_and_removes_it_from_the_overlay(
        self, settings: Settings
    ) -> None:
        self._seed_approved_row(settings, "g0001-abc", Purpose.ROTH, note="looked fine at the time")
        promotion.seat_on_desk("g0001-abc", Purpose.ROTH, settings=settings)

        migrate_seat_pipeline.run_migration(settings=settings, apply=True)

        (row,) = promotion.read_pending_seats(settings)
        assert row.status == "shelved"
        assert row.decided_note.startswith(
            "un-seated 2026-08-26 by owner (seated without review); see docs/research/loop/"
        )
        assert row.decided_note.endswith("looked fine at the time")
        assert "g0001-abc" not in promotion.read_overlay(settings).get("roth", ())

    def test_leaves_an_overlay_id_alone_when_it_has_no_approved_request(
        self, settings: Settings
    ) -> None:
        self._seed_approved_row(settings, "g0001-abc", Purpose.ROTH)
        promotion.seat_on_desk("g0001-abc", Purpose.ROTH, settings=settings)
        promotion.seat_on_desk("hand-authored-not-from-a-request", Purpose.ROTH, settings=settings)

        report = migrate_seat_pipeline.run_migration(settings=settings, apply=True)

        assert ("roth", "hand-authored-not-from-a-request") in report.overlay_left_alone
        assert "hand-authored-not-from-a-request" in promotion.read_overlay(settings)["roth"]
        assert "g0001-abc" not in promotion.read_overlay(settings)["roth"]

    def test_writes_backups_before_applying(self, settings: Settings) -> None:
        self._seed_approved_row(settings, "g0001-abc", Purpose.ROTH)
        promotion.seat_on_desk("g0001-abc", Purpose.ROTH, settings=settings)

        migrate_seat_pipeline.run_migration(settings=settings, apply=True)

        loop_dir = settings.data_dir / "loop"
        backups = list(loop_dir.glob("*.pre-migration-*"))
        backup_names = {p.name.split(".pre-migration-")[0] for p in backups}
        assert backup_names == {"pending_seats", "roster_overlay"}

    def test_is_idempotent_the_second_apply_changes_nothing(self, settings: Settings) -> None:
        self._seed_approved_row(settings, "g0001-abc", Purpose.ROTH)
        promotion.seat_on_desk("g0001-abc", Purpose.ROTH, settings=settings)

        migrate_seat_pipeline.run_migration(settings=settings, apply=True)
        after_first_pending = pending_seats_path(settings).read_text(encoding="utf-8")
        after_first_overlay = roster_overlay_path(settings).read_text(encoding="utf-8")

        second_report = migrate_seat_pipeline.run_migration(settings=settings, apply=True)

        assert second_report.already_migrated is True
        assert second_report.changed is False
        assert pending_seats_path(settings).read_text(encoding="utf-8") == after_first_pending
        assert roster_overlay_path(settings).read_text(encoding="utf-8") == after_first_overlay

    def test_a_queue_with_no_approved_rows_is_a_no_op(self, settings: Settings) -> None:
        promotion.request_seat(_seat(), settings=settings)  # still "pending", nothing to migrate

        report = migrate_seat_pipeline.run_migration(settings=settings, apply=True)

        assert report.already_migrated is True
        assert report.changed is False
        loop_dir = settings.data_dir / "loop"
        assert list(loop_dir.glob("*.pre-migration-*")) == []
