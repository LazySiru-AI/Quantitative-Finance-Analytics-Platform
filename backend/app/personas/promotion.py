"""Promote a persona strategy-card draft onto the competition library shelf as a scorable candidate.

The write half of `POST /api/personas/{slug}/strategy-cards/{version}/promote`. Much lighter than the
thesis equivalent (`app.thesis.promotion`), because a persona draft **already contains a fully
validated `app.tournament.models.StrategyCard`**: `app.personas.strategy.draft_strategy_card` builds
it through `app.evolution.proposer.card_for` -- the same constructor and validators the evolution
loop's own agent-designed genomes pass -- and stores it as JSON on the `StrategyCardDraft`. So there
is nothing to translate or rebuild here; promotion loads that saved card, re-stamps it with a stable
identity and its provenance, and writes it to `library/candidates/`.

**Scorable, not `reference_only`.** `card_for` stamps every persona card with the real
`DESIGN_THROUGH` (`app.evolution.proposer._rules_card`), because a persona card is mapped from
described *methodology*, never from live data past that cutoff. It is therefore honestly designed
before every scored window and competes as an ordinary candidate -- the opposite of a promoted thesis
survivor, whose honest design date is too late and which must be `reference_only`. A persona card is
written `reference_only=False`, and the next competition round the owner runs will score it.

**The card comes from the server's own store, never the request.** The endpoint carries only
`(slug, version)`; the card content is read from the persona's saved `strategy/<version>.json`. A
caller points at a draft, it never describes one -- the same safety property `app.thesis.promotion`
holds, for the same reason (a library card's `entry`/`exit` are executed DSL).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.personas.models import SavedStrategyDraft
from app.tournament.models import StrategyCard

__all__ = [
    "CANDIDATES_TIER",
    "NotPromotable",
    "PromotionError",
    "PromotionResult",
    "build_card",
    "promote_draft",
]

#: The review shelf: cards awaiting inclusion in a round sit here, the same tier hand-authored and
#: evolution candidates land on. A persona card competes the next time the owner runs a round.
CANDIDATES_TIER = "candidates"


class PromotionError(Exception):
    """Base for a promotion the caller should turn into a 4xx."""


class NotPromotable(PromotionError):
    """The draft produced no card -- a persona that describes no mechanical methodology, or whose
    mapping the card validators rejected (`mapped is False`, `card is None`). There is nothing to
    promote; the endpoint returns 422."""


@dataclass(frozen=True, slots=True)
class PromotionResult:
    """`created` is `False` when the card was already on the shelf (idempotent re-promote of the same
    saved version); the caller turns that into a 409."""

    card: StrategyCard
    path: Path
    created: bool


def build_card(card_json: dict[str, object], *, slug: str, version: int) -> StrategyCard:
    """Re-validate the draft's saved card and stamp it with a stable identity and its provenance.

    The card is validated (it already passed `card_for`, but a persisted file is re-checked on the way
    out), then given a deterministic `agent_id` -- `P-<slug>-v<version>` -- so re-promoting the same
    saved draft maps to the same shelf file, and `source_persona` so the shelved card is traceable to
    the draft it came from. Nothing else is touched: entry/exit/universe/discipline/purpose and the
    `DESIGN_THROUGH` cutoff are all as `card_for` set them.
    """
    card = StrategyCard.model_validate(card_json)
    return card.model_copy(
        update={"agent_id": _agent_id(slug, version), "source_persona": f"{slug}@v{version}"}
    )


def promote_draft(saved: SavedStrategyDraft, *, settings: Settings) -> PromotionResult:
    """Write the saved draft's card to `library/candidates/{agent_id}.json`, idempotently.

    Raises `NotPromotable` when the draft carries no card. Because `agent_id` is a pure function of
    `(slug, version)`, a second promotion of the same saved version is a no-op returning the on-disk
    card with `created=False`, never an overwrite.
    """
    draft = saved.draft
    if not draft.mapped or draft.card is None:
        raise NotPromotable(
            f"persona {draft.persona!r} draft v{draft.version} has no card to promote "
            f"(mapped={draft.mapped}); a draft that mapped no methodology cannot be shelved"
        )

    card = build_card(draft.card, slug=draft.persona, version=draft.version)
    dest_dir = settings.library_dir / CANDIDATES_TIER
    dest = dest_dir / f"{card.agent_id}.json"
    if dest.exists():
        existing = StrategyCard.model_validate_json(dest.read_text(encoding="utf-8"))
        return PromotionResult(card=existing, path=dest, created=False)

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest.write_text(card.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return PromotionResult(card=card, path=dest, created=True)


def _agent_id(slug: str, version: int) -> str:
    return f"P-{slug}-v{version}"
