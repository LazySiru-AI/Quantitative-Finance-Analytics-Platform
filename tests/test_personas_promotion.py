"""Promoting a persona strategy-card draft onto the library shelf -- `app.personas.promotion` and
`service.promote_strategy_card`.

A persona draft already carries a fully validated `app.tournament.models.StrategyCard` (built through
`card_for`), so promotion is a load-restamp-write, not a rebuild. Two layers:

* `promote_draft` / `build_card` -- the write, into a *temporary* library so the real shelf under
  `backend/app/paper/library/` is never touched. Identity (`P-<slug>-v<version>`), provenance
  (`source_persona`), scorable-not-reference_only, and idempotency are pinned here.
* `service.promote_strategy_card` -- the persona-existence / version-lookup / error mapping, against a
  real (temp) vault.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import Settings
from app.personas import promotion, service
from app.personas import strategy as strategy_mod
from app.personas.models import Persona, SavedStrategyDraft, StrategyCardDraft
from app.personas.store import VaultStore
from app.tournament.models import Discipline, StrategyCard


def _card(**overrides: object) -> StrategyCard:
    base: dict[str, object] = {
        "agent_id": "g1-fromgenome",  # a card_for-style id; promotion overrides it with a stable one
        "display_name": "Persona trend card",
        "discipline": Discipline.TREND,
        "thesis": "rides the persona's trend methodology",
        "universe": ("SPY",),
        "entry": "close > sma(50)",
        "exit": "close < sma(50)",
        "max_positions": 1,
        "position_pct": Decimal("0.2"),
        "designed_through": dt.date(2026, 2, 1),  # honestly before DESIGN_THROUGH, like card_for stamps
    }
    base.update(overrides)
    return StrategyCard(**base)  # type: ignore[arg-type]


def _draft(
    card: StrategyCard | None, *, persona: str = "warren", version: int = 1, mapped: bool = True
) -> StrategyCardDraft:
    return StrategyCardDraft(
        persona=persona,
        mapped=mapped,
        card=card.model_dump(mode="json") if card is not None else None,
        version=version,
    )


def _saved(draft: StrategyCardDraft) -> SavedStrategyDraft:
    return SavedStrategyDraft(
        draft=draft, saved_at=dt.datetime.now(dt.UTC), filename=f"{draft.version}.json"
    )


@pytest.fixture
def tmp_settings(settings: Settings, tmp_path: Path) -> Settings:
    """`settings` (temp vault/store from the fixture) with `library_dir` also redirected into
    `tmp_path`, so a promote writes to a temp shelf, never `backend/app/paper/library/`."""
    return settings.model_copy(update={"library_dir": tmp_path / "library"})


class TestPromoteDraft:
    def test_writes_a_scorable_candidate_with_stable_identity_and_provenance(
        self, tmp_settings: Settings
    ) -> None:
        result = promotion.promote_draft(_saved(_draft(_card())), settings=tmp_settings)

        assert result.created is True
        assert result.card.agent_id == "P-warren-v1"  # stable, from (slug, version) -- not the genome id
        assert result.card.source_persona == "warren@v1"
        # Scorable, NOT reference_only -- a persona card is honestly designed before the cutoff.
        assert result.card.reference_only is False
        assert result.card.desk_only is False
        assert result.path == tmp_settings.library_dir / "candidates" / "P-warren-v1.json"
        reloaded = StrategyCard.model_validate_json(result.path.read_text(encoding="utf-8"))
        assert reloaded == result.card

    def test_leaves_the_rule_and_cutoff_untouched(self, tmp_settings: Settings) -> None:
        result = promotion.promote_draft(_saved(_draft(_card())), settings=tmp_settings)
        assert result.card.entry == "close > sma(50)"
        assert result.card.exit == "close < sma(50)"
        assert result.card.designed_through == dt.date(2026, 2, 1)

    def test_is_idempotent_for_the_same_saved_version(self, tmp_settings: Settings) -> None:
        saved = _saved(_draft(_card()))
        first = promotion.promote_draft(saved, settings=tmp_settings)
        second = promotion.promote_draft(saved, settings=tmp_settings)

        assert first.created is True
        assert second.created is False
        assert second.card == first.card
        assert list((tmp_settings.library_dir / "candidates").glob("*.json")) == [first.path]

    def test_an_unmapped_draft_has_nothing_to_promote(self, tmp_settings: Settings) -> None:
        with pytest.raises(promotion.NotPromotable):
            promotion.promote_draft(_saved(_draft(None, mapped=False)), settings=tmp_settings)


class TestServicePromoteStrategyCard:
    def _seed_persona(self, settings: Settings, slug: str = "warren") -> None:
        VaultStore(settings).save_persona(
            Persona(slug=slug, display_name=slug.title(), created_at=dt.datetime.now(dt.UTC))
        )

    def test_happy_path_returns_the_written_card(self, tmp_settings: Settings) -> None:
        self._seed_persona(tmp_settings)
        strategy_mod.save_draft("warren", _draft(_card()), tmp_settings)  # store stamps version 1

        card = service.promote_strategy_card(tmp_settings, "warren", 1)

        assert card.agent_id == "P-warren-v1"
        assert card.source_persona == "warren@v1"
        assert (tmp_settings.library_dir / "candidates" / "P-warren-v1.json").is_file()

    def test_unknown_persona_is_404(self, tmp_settings: Settings) -> None:
        with pytest.raises(service.PersonaError) as exc:
            service.promote_strategy_card(tmp_settings, "nobody", 1)
        assert exc.value.status_code == 404

    def test_unknown_version_is_404(self, tmp_settings: Settings) -> None:
        self._seed_persona(tmp_settings)  # persona exists, but no saved draft at v1
        with pytest.raises(service.PersonaError) as exc:
            service.promote_strategy_card(tmp_settings, "warren", 1)
        assert exc.value.status_code == 404

    def test_already_promoted_is_409(self, tmp_settings: Settings) -> None:
        self._seed_persona(tmp_settings)
        strategy_mod.save_draft("warren", _draft(_card()), tmp_settings)

        service.promote_strategy_card(tmp_settings, "warren", 1)
        with pytest.raises(service.PersonaError) as exc:
            service.promote_strategy_card(tmp_settings, "warren", 1)
        assert exc.value.status_code == 409
