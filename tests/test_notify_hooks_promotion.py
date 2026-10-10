"""The promotion notification hook in `backend/app/evolution/promotion.py`.

Driven through `_append_promotion` -- the one function every promotion goes through, and the point
after which the record is durably on disk -- rather than through the whole gate, which needs a full
tournament's standings to reach a promotion at all.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

import app.notify as notify_pkg
from app.config import Settings
from app.evolution import promotion
from app.evolution.models import PromotionRecord
from app.notify import events as notify_events
from app.tournament.purposes import Purpose

_PROMOTED_AT = dt.datetime(2026, 9, 9, 18, 30, tzinfo=dt.UTC)


def _record(
    *,
    genome_id: str = "g-alpha",
    library_path: str = "library/candidates/g-alpha.json",
    seated: bool = False,
) -> PromotionRecord:
    return PromotionRecord(
        genome_id=genome_id,
        agent_id="A-mom",
        purpose=Purpose.TRADING,
        promoted_at=_PROMOTED_AT,
        generations=(7, 8),
        window_sets=(("gfc",), ("covid",)),
        median_excess=Decimal("0.1"),
        holdout_median_excess=Decimal("0.05"),
        q_value=0.01,
        library_path=library_path,
        seated=seated,
        reason="cleared the gate twice",
    )


class TestEmit:
    def test_appending_a_promotion_emits_one_research_promotion_event(
        self, settings: Settings
    ) -> None:
        promotion._append_promotion(_record(), settings=settings)
        emitted = notify_events.list_since(settings)
        assert len(emitted) == 1
        event = emitted[0]
        assert event.kind == "research.promotion"
        assert event.severity == "notable"
        assert event.headline == "Promoted g-alpha to candidates"
        assert event.refs == ("genome:g-alpha",)
        assert event.source == "evolution.promotion"
        assert event.id == f"research.promotion:g-alpha:{_PROMOTED_AT.isoformat()}"

    def test_the_detail_says_whether_a_seat_was_already_approved(
        self, settings: Settings
    ) -> None:
        promotion._append_promotion(_record(seated=False), settings=settings)
        promotion._append_promotion(_record(genome_id="g-beta", seated=True), settings=settings)
        details = {event.headline: event.detail for event in notify_events.list_since(settings)}
        assert "awaiting a seat decision" in details["Promoted g-alpha to candidates"]
        assert "already seated" in details["Promoted g-beta to candidates"]

    def test_the_tier_comes_from_the_library_path_on_either_separator(self) -> None:
        assert promotion._promotion_tier(_record(library_path="library/generated/g.json")) == (
            "generated"
        )
        assert promotion._promotion_tier(
            _record(library_path="library\\candidates\\g.json")
        ) == "candidates"
        assert promotion._promotion_tier(_record(library_path="g.json")) == "the library"

    def test_the_record_is_still_appended_when_emit_raises(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("notify is broken")

        monkeypatch.setattr(notify_pkg, "emit", _boom)
        promotion._append_promotion(_record(), settings=settings)

        loaded = promotion.load_promotions(settings)
        assert [record.genome_id for record in loaded] == ["g-alpha"]
        assert notify_events.list_since(settings) == []
