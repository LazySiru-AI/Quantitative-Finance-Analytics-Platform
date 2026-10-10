"""Seat provenance -- `app.paperdesk.desk._seat_provenance` and the `SeatProvenance` model.

Where a desk seat came from, joined cheaply by agent_id: a `PromotionRecord` in `promotions.jsonl`
makes it `"promoted"` with the latest generation the genome cleared; anything the loop's promotion
record does not name is `"owner"` -- which is every seat on the current hand-authored roster. The
end-to-end "the wire actually carries provenance" assertion lives beside the other `state()` tests in
`tests/test_paperdesk.py`, which owns the desk-building harness.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.evolution.models import PromotionRecord
from app.paperdesk.desk import _seat_provenance
from app.paperdesk.models import SeatProvenance
from app.tournament.purposes import Purpose


def _record(agent_id: str, generations: tuple[int, ...]) -> PromotionRecord:
    return PromotionRecord(
        genome_id=f"g-{agent_id}",
        agent_id=agent_id,
        purpose=Purpose.TRADING,
        promoted_at=dt.datetime(2026, 8, 1, tzinfo=dt.UTC),
        generations=generations,
        window_sets=(("gfc",),),
        median_excess=Decimal("0.1"),
        holdout_median_excess=Decimal("0.05"),
        q_value=0.01,
        library_path="candidates/g.json",
        seated=False,
        reason="cleared the gate",
    )


class TestSeatProvenance:
    def test_a_promoted_seat_reports_the_latest_generation_it_cleared(self) -> None:
        promotions = {"g-alpha": _record("g-alpha", (7, 8, 9))}
        prov = _seat_provenance(promotions, "g-alpha")
        assert prov == SeatProvenance(source="promoted", generation=9)

    def test_a_seat_with_no_promotion_record_is_owner_seated(self) -> None:
        prov = _seat_provenance({}, "A-rotation")
        assert prov == SeatProvenance(source="owner", generation=None)

    def test_a_record_with_no_generations_falls_back_to_owner(self) -> None:
        # Defensive: a record can only reach here with >= promotion_consecutive generations, but an
        # empty tuple must never render as "promoted · gen None".
        promotions = {"weird": _record("weird", ())}
        assert _seat_provenance(promotions, "weird").source == "owner"

    def test_only_the_matching_agent_id_is_promoted(self) -> None:
        promotions = {"g-alpha": _record("g-alpha", (3,))}
        assert _seat_provenance(promotions, "g-beta").source == "owner"
        assert _seat_provenance(promotions, "g-alpha").source == "promoted"
