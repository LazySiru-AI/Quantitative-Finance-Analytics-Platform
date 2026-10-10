"""Promote a `Thesis` survivor onto the strategy-competition library shelf as a reference card.

This is the write half of `POST /api/thesis/promote`. Its whole reason to exist is a translation
between two unrelated models that happen to share a name: a survivor is an
`app.thesis.models.StrategyCard` (one instrument, rich evidence, a `verdict`), and the library shelf
holds `app.tournament.models.StrategyCard` (a pure specification -- rules and risk knobs, no scores).

**Everything the destination card needs is rebuilt from the ledger record, server-side.** The caller
supplies only which survivor (`symbol` + `thesis_hash`) and two validated risk numerics; it never
sends rule text. A library card's `entry`/`exit` are Rule-DSL expressions that get *executed* in
every backtest and on every desk, so accepting them from a request body would be an
arbitrary-expression injection path. Instead `build_card` reads the frozen `Thesis` off the
`ThesisRecord` -- a thesis that was pre-registered (hashed before any test ran) and cleared
in-sample, holdout and Benjamini-Hochberg correction -- and every executable string on the resulting
card therefore originates here, from that record, not from the request.

**The card is written `reference_only`** (`app.tournament.models.StrategyCard.reference_only`). A
survivor is designed "through ~now" -- validated on a holdout running to its registration date -- so
it is designed past every scored window's opening, and the design-cutoff validator would reject any
honest `designed_through` for a tournament or desk card. `reference_only` is the honest resolution:
the card is scored on no window, so the cutoff does not apply, and `app.tournament.jobs` /
`app.paperdesk.desk` both refuse to score it. See that field's docstring, and
`docs/THESIS-PROMOTION-CONTRACT.md` §0, for the full argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from app.config import Settings, get_settings
from app.db.duck import Interval
from app.thesis.models import Thesis, ThesisRecord, Verdict
from app.tournament.models import Discipline, StrategyCard
from app.tournament.purposes import Purpose

__all__ = [
    "CANDIDATES_TIER",
    "DEFAULT_POSITION_PCT",
    "NotASurvivor",
    "NotPromotable",
    "PromotionError",
    "PromotionResult",
    "build_card",
    "discipline_for",
    "promote",
]

#: A promoted survivor lands here -- the same shelf hand-authored and evolution candidates sit on.
#: The `reference_only` flag, not the directory, carries "scored nowhere"; a dedicated tier would be
#: a wider change (new `TIERS` entry, new directory, UI grouping) for no extra guarantee.
CANDIDATES_TIER = "candidates"

#: Fraction of the book a single-name reference card is written to commit, when the caller does not
#: say. A conservative default: the owner chose it in the accepted contract (§9-B), and a single
#: instrument concentrated too heavily is a risk decision, not a translation default.
DEFAULT_POSITION_PCT = Decimal("0.15")

#: The card's own `max_hold_days` bound (`Field(ge=1, le=252)`). Duplicated as a constant so this
#: module can refuse an out-of-range time stop with a clear message before the model would.
_MAX_HOLD_DAYS = 252

#: Each of the six `app.thesis.author` templates onto an existing `Discipline`. No new enum member
#: is needed. Discipline is the label the tournament's multiple-testing correction uses to tell
#: genuinely different ideas apart, so it is derived from the template that produced the thesis, not
#: guessed -- see `discipline_for`.
_DISCIPLINE_BY_TEMPLATE: dict[str, Discipline] = {
    "band_reversion": Discipline.MEAN_REVERSION,
    "oversold_bounce": Discipline.MEAN_REVERSION,
    "trend_following": Discipline.TREND,
    "momentum_persistence": Discipline.MOMENTUM,
    "volatility_contraction": Discipline.VOLATILITY,
    "decay_avoidance": Discipline.RISK_MANAGED,
}

#: For a survivor that matches no catalogue template (a reverse-conditioned thesis via
#: `propose_from_candidate`, or one whose template text was later edited). `RISK_MANAGED` is the most
#: conservative honest label for correction purposes -- it does not assert kinship with any family.
_FALLBACK_DISCIPLINE = Discipline.RISK_MANAGED


class _TemplateLike(Protocol):
    """The three fields `discipline_for` matches on. Structural, so this module does not import
    `app.thesis.author.Template` (and its instrument-lookup dependencies) merely to read them, and a
    test can pass a plain stand-in catalogue."""

    @property
    def key(self) -> str: ...
    @property
    def hypothesis(self) -> str: ...
    @property
    def entry(self) -> str: ...


class PromotionError(Exception):
    """Base for a promotion the endpoint should turn into a 4xx, not a 500."""


class NotASurvivor(PromotionError):
    """The identified record exists but did not survive. The load-bearing refusal: a card is written
    only for a thesis that cleared the gate, and the verdict is read from the ledger, never the
    request."""


class NotPromotable(PromotionError):
    """The record survived but cannot be expressed as a library card -- a non-daily interval, an
    out-of-range time stop, or no way to ever close a position."""


@dataclass(frozen=True, slots=True)
class PromotionResult:
    """`created` is `False` when an identical card was already on the shelf (idempotent re-promote);
    the endpoint turns that into a `409` carrying `card`. `True` means this call wrote it."""

    card: StrategyCard
    path: Path
    created: bool


def discipline_for(
    thesis: Thesis, catalogue: tuple[_TemplateLike, ...]
) -> tuple[Discipline, str | None]:
    """`(discipline, matched_template_key)` for a survivor thesis.

    `app.thesis.author.propose` copies a template's `hypothesis` and `entry` **verbatim** into the
    thesis it mints -- no parameterisation -- so a survivor's text is an exact match for its source
    template's, and the key is recoverable here without persisting it through the loop. A thesis that
    matches nothing (reverse-conditioned, or a since-edited template) falls back to `RISK_MANAGED`
    with `None`, the same graceful degradation an absent key would give.
    """
    for template in catalogue:
        if template.hypothesis == thesis.hypothesis and template.entry == thesis.entry:
            return _DISCIPLINE_BY_TEMPLATE.get(template.key, _FALLBACK_DISCIPLINE), template.key
    return _FALLBACK_DISCIPLINE, None


def build_card(
    record: ThesisRecord,
    *,
    position_pct: Decimal = DEFAULT_POSITION_PCT,
    purpose: Purpose = Purpose.TRADING,
    catalogue: tuple[_TemplateLike, ...],
) -> StrategyCard:
    """The pure translation: a survivor `ThesisRecord` to a `reference_only` library card. No disk.

    Raises `NotASurvivor` if the record did not survive, and `NotPromotable` if it survived but its
    thesis cannot be a valid card. Every executable field comes from `record.thesis`, never from a
    caller.
    """
    if record.verdict is not Verdict.SURVIVED:
        verdict = record.verdict.value if record.verdict is not None else "none"
        raise NotASurvivor(
            f"thesis {record.thesis_hash[:12]} has verdict {verdict!r}, not 'survived'; only a "
            "survivor may be promoted"
        )

    thesis = record.thesis
    if thesis.interval is not Interval.DAY:
        raise NotPromotable(
            f"thesis {record.thesis_hash[:12]} was tested on the {thesis.interval.value!r} "
            "interval; only daily-interval survivors can be promoted, because the library card and "
            "the tournament run it feeds are daily-only (the card carries no interval, and "
            "max_holding_bars would not equal max_hold_days off a daily bar)"
        )

    max_hold = thesis.max_holding_bars
    if max_hold is not None and not (1 <= max_hold <= _MAX_HOLD_DAYS):
        raise NotPromotable(
            f"thesis max_holding_bars={max_hold} is outside the card's supported 1..{_MAX_HOLD_DAYS} "
            "day time-stop range"
        )

    exit_rule = (thesis.exit or "").strip()
    # An empty exit is the codebase's sanctioned "no discretionary exit" -- the runner skips it and
    # the card validator permits it -- but only alongside a time stop. A stop-loss alone does not
    # count: it closes losers, never winners, so the position can still be held forever, which is the
    # exact case `StrategyCard`'s own validator rejects. So exit-less requires `max_holding_bars`.
    if not exit_rule and max_hold is None:
        raise NotPromotable(
            f"thesis {record.thesis_hash[:12]} has no exit rule and no time stop (max_holding_bars); "
            "its card would have no way to close a position, which the library model forbids"
        )

    stop = Decimal(str(thesis.stop_loss_pct)) if thesis.stop_loss_pct is not None else None
    discipline, _key = discipline_for(thesis, catalogue)
    symbol = thesis.symbol.upper()

    return StrategyCard(
        agent_id=_agent_id(symbol, record.thesis_hash),
        display_name=_display_name(thesis),
        discipline=discipline,
        purpose=purpose,
        desk_only=False,
        reference_only=True,
        thesis=_thesis_prose(thesis),
        falsification=thesis.falsifies_if,
        universe=(symbol,),
        entry=thesis.entry,
        exit=exit_rule,
        stop_loss_pct=stop,
        take_profit_pct=None,
        max_hold_days=max_hold,
        max_positions=1,
        position_pct=position_pct,
        rank_by=None,
        # The pre-registration date: the thesis's rules were frozen here, so the card may be *read* as
        # designed through this date honestly. It is after every scored window's opening, which is why
        # the card is reference_only and scored on none of them.
        designed_through=record.registered_at.date(),
        source_thesis_hash=record.thesis_hash,
    )


def promote(
    record: ThesisRecord,
    *,
    position_pct: Decimal = DEFAULT_POSITION_PCT,
    purpose: Purpose = Purpose.TRADING,
    settings: Settings | None = None,
    catalogue: tuple[_TemplateLike, ...] | None = None,
) -> PromotionResult:
    """Build the card and write it to `library/candidates/{agent_id}.json`, idempotently.

    `agent_id` is a pure function of `(symbol, thesis_hash)`, so a survivor's rules -- immutable by
    hash -- always map to the same filename. If it already exists this is a no-op returning
    `created=False` and the on-disk card, never an overwrite.
    """
    cfg = settings if settings is not None else get_settings()
    cat = catalogue if catalogue is not None else _default_catalogue()
    card = build_card(record, position_pct=position_pct, purpose=purpose, catalogue=cat)

    dest_dir = cfg.library_dir / CANDIDATES_TIER
    dest = dest_dir / f"{card.agent_id}.json"
    if dest.exists():
        existing = StrategyCard.model_validate_json(dest.read_text(encoding="utf-8"))
        return PromotionResult(card=existing, path=dest, created=False)

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest.write_text(card.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return PromotionResult(card=card, path=dest, created=True)


def _agent_id(symbol: str, thesis_hash: str) -> str:
    """`T-<SYMBOL>-<hash8>`: stable, unique, and the key idempotency turns on. Consistent with the
    existing `A-rotation` / `{genome_id}` naming without colliding with either."""
    return f"T-{symbol.upper()}-{thesis_hash[:8]}"


def _display_name(thesis: Thesis) -> str:
    return f"Thesis — {thesis.symbol.upper()}: {_first_sentence(thesis.hypothesis)}"


def _thesis_prose(thesis: Thesis) -> str:
    """The card's free-prose `thesis` field: the hypothesis, plus the rationale when one was given."""
    prose = thesis.hypothesis.strip()
    rationale = thesis.rationale.strip()
    if rationale:
        prose = f"{prose}\n\n{rationale}"
    return prose


def _first_sentence(text: str, *, limit: int = 100) -> str:
    """First sentence of the hypothesis, for a readable display name. Trimmed, never mid-word."""
    stripped = text.strip()
    head = stripped.split(". ", 1)[0].rstrip(".")
    if len(head) <= limit:
        return head
    return head[:limit].rsplit(" ", 1)[0] + "…"


def _default_catalogue() -> tuple[_TemplateLike, ...]:
    from app.thesis.author import CATALOGUE

    return CATALOGUE
