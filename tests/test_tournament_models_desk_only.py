"""`StrategyCard.desk_only` -- the cutoff a card is held to, and the constant that decides it.

No bars, no store, no network: every assertion here is about model validation and the two dates the
validator picks between. The one test that reaches outside this module (`test_desk_inception_mirror`)
reads a constant, not a file.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.tournament.models import (
    DESIGN_THROUGH,
    DESK_INCEPTION,
    Discipline,
    StrategyCard,
)


def _card(**overrides: object) -> StrategyCard:
    fields: dict[str, object] = {
        "agent_id": "agent-1",
        "display_name": "Agent One",
        "discipline": Discipline.TREND,
        "thesis": "a test thesis, written before the trading window ran",
        "universe": ("TEST",),
        "entry": "close > 0",
        "exit": "",
        "max_hold_days": 50,
        "max_positions": 1,
        "position_pct": Decimal("1.0"),
        "designed_through": DESIGN_THROUGH,
    }
    fields.update(overrides)
    return StrategyCard(**fields)  # type: ignore[arg-type]


class TestDeskInceptionConstant:
    def test_desk_inception_mirror(self) -> None:
        """`models.DESK_INCEPTION` must equal `paperdesk.desk.INCEPTION`.

        The two are separate literals because `app.paperdesk.desk` imports `app.tournament.models`,
        so the dependency cannot run the other way -- see `DESK_INCEPTION`'s own docstring. This
        assertion is the thing that makes the duplication safe: move one and this fails immediately,
        rather than a `desk_only` card silently being validated against a cutoff the desk no longer
        uses.
        """
        from app.paperdesk.desk import INCEPTION

        assert DESK_INCEPTION == INCEPTION

    def test_desk_inception_is_after_the_tournament_cutoff(self) -> None:
        """The whole point of the field: the desk's window opens long after the tournament's."""
        assert DESK_INCEPTION > DESIGN_THROUGH


class TestTournamentCardsAreUnchanged:
    """The default path must behave exactly as it did before `desk_only` existed."""

    def test_design_cutoff_itself_is_allowed(self) -> None:
        assert _card(designed_through=DESIGN_THROUGH).designed_through == DESIGN_THROUGH

    def test_one_day_past_the_cutoff_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="after the design cutoff"):
            _card(designed_through=DESIGN_THROUGH + dt.timedelta(days=1))

    def test_desk_only_defaults_to_false(self) -> None:
        assert _card().desk_only is False

    def test_the_rejection_points_at_the_alternative(self) -> None:
        """A card author who hit this wall should be told the flag exists, and that it is a
        different window rather than a way around this one."""
        with pytest.raises(ValidationError, match="desk_only=true"):
            _card(designed_through=DESIGN_THROUGH + dt.timedelta(days=1))


class TestDeskOnlyCards:
    def test_a_date_after_the_tournament_cutoff_is_allowed(self) -> None:
        """The case the field exists for: a signal that only became public in August."""
        card = _card(desk_only=True, designed_through=dt.date(2026, 8, 14))
        assert card.desk_only is True
        assert card.designed_through == dt.date(2026, 8, 14)

    def test_the_day_before_inception_is_the_last_allowed_day(self) -> None:
        card = _card(desk_only=True, designed_through=DESK_INCEPTION - dt.timedelta(days=1))
        assert card.designed_through < DESK_INCEPTION

    def test_inception_itself_is_rejected(self) -> None:
        """Strictly before, not on: an author who saw the desk's first session saw a session the
        desk is about to score them on."""
        with pytest.raises(ValidationError, match="not before the paper desk's inception"):
            _card(desk_only=True, designed_through=DESK_INCEPTION)

    def test_after_inception_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="not before the paper desk's inception"):
            _card(desk_only=True, designed_through=DESK_INCEPTION + dt.timedelta(days=30))

    def test_the_flag_does_not_loosen_the_rule_it_only_moves_it(self) -> None:
        """`desk_only` is not an escape hatch: it swaps one cutoff for another, and the later
        cutoff still binds. A card designed today is rejected either way."""
        far_future = dt.date(2027, 1, 1)
        with pytest.raises(ValidationError):
            _card(desk_only=True, designed_through=far_future)
        with pytest.raises(ValidationError):
            _card(desk_only=False, designed_through=far_future)


class TestTheSeatedCard:
    """The first real `desk_only` card, read off disk as the desk itself reads it."""

    def test_the_duquesne_card_loads_and_is_desk_only(self) -> None:
        from pathlib import Path

        from app.config import get_settings

        path = Path(get_settings().library_dir) / "candidates" / "I-13f-duquesne-2026q2.json"
        card = StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))

        assert card.desk_only is True
        # The filing this card's universe came from was public on 2026-08-14; the desk's default
        # window opens the next day. That one-day gap is the entire reason the card is legal.
        assert card.designed_through == dt.date(2026, 8, 14)
        assert card.designed_through < DESK_INCEPTION
        # Eight names, not nine: LRCX resolved from the filing but sits below the roster's
        # min_txns floor. If that floor or the ledger changes, this card should be revisited
        # rather than silently trading a universe its thesis does not describe.
        assert len(card.universe) == 8
        assert "LRCX" not in card.universe
        assert "SPCX" not in card.universe


class TestTheTournamentRefusesDeskOnlyCards:
    """The other half of the contract: `desk_only` buys a later cutoff by giving up the tournament.

    Run against the real library rather than a fixture, because the thing worth protecting is that
    the actually-seated card cannot reach a round -- not that a synthetic one cannot.
    """

    def test_naming_it_explicitly_raises(self) -> None:
        from app.tournament.jobs import DeskOnlyCard, _resolve_cards

        with pytest.raises(DeskOnlyCard, match="I-13f-duquesne-2026q2"):
            _resolve_cards(["I-13f-duquesne-2026q2"], "candidates")

    def test_the_message_says_why_rather_than_just_no(self) -> None:
        from app.tournament.jobs import DeskOnlyCard, _resolve_cards

        with pytest.raises(DeskOnlyCard, match="already had sight of"):
            _resolve_cards(["I-13f-duquesne-2026q2"], "candidates")

    def test_a_defaulted_tier_excludes_it_instead_of_failing(self) -> None:
        """ "every card in `candidates`" must not become unrunnable because one desk card lives
        there -- but the desk card must not be in the field either."""
        from app.tournament.jobs import _resolve_cards

        cards = _resolve_cards([], "candidates")

        assert cards, "the candidates tier should still resolve to a non-empty field"
        assert "I-13f-duquesne-2026q2" not in {card.agent_id for card in cards}
        assert all(not card.desk_only for card in cards)

    def test_ordinary_candidates_still_resolve_by_name(self) -> None:
        """The refusal is scoped to desk_only, not to the tier it happens to sit in."""
        from app.tournament.jobs import _resolve_cards

        cards = _resolve_cards(["A-rotation"], "candidates")

        assert [card.agent_id for card in cards] == ["A-rotation"]
