"""Tests for `app.evolution.promotion` (the promotion gate and the paper-desk roster overlay) and the
narrow `app.paperdesk.desk.rosters` edit that reads the overlay it writes.

Every test builds its own `Settings` pointed at `tmp_path` -- `library_dir`, `data_dir` and
`cache_dir` are all redirected there, so nothing here ever touches the real
`backend/app/paper/library/` or `data/`. Builders below are small and local, in this repo's own
"duplicated fakes rather than a cross-file import" style (see `tests/test_paperdesk.py`'s module
docstring for the precedent).
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.evolution import loop as loop_module
from app.evolution import promotion
from app.evolution.models import (
    GenerationOutcome,
    Genome,
    LoopConfig,
    Standing,
    UnreachablePromotionCeiling,
    generated_tier_dir,
    loop_root,
    roster_overlay_path,
)
from app.paperdesk import desk
from app.tournament import jobs
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from app.tournament.purposes import Purpose

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _settings(tmp_path) -> Settings:
    return Settings(
        repo_root=tmp_path,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        library_dir=tmp_path / "library",
    )


def _card(
    agent_id: str,
    *,
    purpose: Purpose = Purpose.TRADING,
    universe: tuple[str, ...] = ("AAA", "BBB"),
) -> StrategyCard:
    return StrategyCard(
        agent_id=agent_id,
        display_name=agent_id,
        discipline=Discipline.MOMENTUM,
        purpose=purpose,
        thesis="a test thesis, written before the trading window ran",
        universe=universe,
        entry="close > 0",
        exit="close < 0",
        stop_loss_pct=Decimal("0.10"),
        take_profit_pct=None,
        max_hold_days=180,
        max_positions=len(universe),
        position_pct=Decimal("1") / len(universe),
        designed_through=DESIGN_THROUGH,
    )


def _write_generated_card(settings: Settings, card: StrategyCard) -> None:
    tier_dir = generated_tier_dir(settings)
    tier_dir.mkdir(parents=True, exist_ok=True)
    (tier_dir / f"{card.agent_id}.json").write_text(card.model_dump_json(), encoding="utf-8")


def _write_library_card(settings: Settings, tier: str, card: StrategyCard) -> None:
    tier_dir = settings.library_dir / tier
    tier_dir.mkdir(parents=True, exist_ok=True)
    (tier_dir / f"{card.agent_id}.json").write_text(card.model_dump_json(), encoding="utf-8")


def _genome(
    genome_id: str,
    *,
    generation: int = 1,
    purpose: Purpose = Purpose.TRADING,
    universe: tuple[str, ...] = ("AAA", "BBB"),
) -> Genome:
    return Genome(
        genome_id=genome_id,
        generation=generation,
        parents=(),
        origin="founder",
        shape="rules",
        purpose=purpose,
        universe=universe,
        traits={},
        seed=0,
        notes="a test genome",
    )


def _standing(
    genome_id: str,
    *,
    eligible: bool = True,
    median_excess: Decimal | None = Decimal("30"),
    holdout_median_excess: Decimal | None = None,
    total_trades: int = 5,
    rank: int = 1,
) -> Standing:
    return Standing(
        genome_id=genome_id,
        agent_id=genome_id,
        display_name=genome_id,
        rank=rank,
        eligible=eligible,
        windows_run=8,
        median_excess=median_excess,
        worst_excess=Decimal("1"),
        hit_rate=0.6,
        total_trades=total_trades,
        holdout_median_excess=holdout_median_excess,
        q_value=None,
    )


def _outcome(
    generation: int,
    windows: tuple[str, ...],
    standings: tuple[Standing, ...],
    *,
    purpose: Purpose = Purpose.TRADING,
) -> GenerationOutcome:
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    return GenerationOutcome(
        generation=generation,
        round_id=f"r-auto-{generation}",
        purpose=purpose,
        status="succeeded",
        started_at=now,
        finished_at=now,
        windows=windows,
        genome_ids=tuple(s.genome_id for s in standings),
        standings=standings,
    )


_CONFIG = LoopConfig(promotion_margin_pp=Decimal("5"))


# ---------------------------------------------------------------------------
# (a) clears_gate
# ---------------------------------------------------------------------------


class TestClearsGate:
    def test_refuses_negative_holdout_however_good_the_selection_median(self) -> None:
        """A card with an excellent selection median and a negative holdout median must never clear
        the gate -- this is the single failure mode the whole loop is most likely to manufacture."""
        standing = _standing(
            "g001-a", median_excess=Decimal("0.95"), holdout_median_excess=Decimal("-0.01")
        )
        assert promotion.clears_gate(standing, config=_CONFIG) is False

    def test_accepts_a_none_holdout(self) -> None:
        """`None` means no holdout was configured or run -- a real weakening, not evidence of
        failure, so it must not block an otherwise-qualifying standing."""
        standing = _standing("g001-a", median_excess=Decimal("0.30"), holdout_median_excess=None)
        assert promotion.clears_gate(standing, config=_CONFIG) is True

    def test_accepts_a_zero_holdout(self) -> None:
        """Zero is not negative -- the gate only refuses a strictly negative holdout median."""
        standing = _standing(
            "g001-a", median_excess=Decimal("0.30"), holdout_median_excess=Decimal("0")
        )
        assert promotion.clears_gate(standing, config=_CONFIG) is True

    def test_refuses_ineligible(self) -> None:
        standing = _standing("g001-a", eligible=False, median_excess=Decimal("0.30"))
        assert promotion.clears_gate(standing, config=_CONFIG) is False

    def test_refuses_median_at_or_below_the_margin(self) -> None:
        standing = _standing("g001-a", median_excess=Decimal("0.05"))  # equal to the margin
        assert promotion.clears_gate(standing, config=_CONFIG) is False

    def test_refuses_none_median(self) -> None:
        standing = _standing("g001-a", median_excess=None)
        assert promotion.clears_gate(standing, config=_CONFIG) is False

    def test_refuses_zero_trades(self) -> None:
        standing = _standing("g001-a", median_excess=Decimal("0.30"), total_trades=0)
        assert promotion.clears_gate(standing, config=_CONFIG) is False

    def test_median_excess_is_a_fraction_and_the_margin_is_percentage_points(self) -> None:
        """The units of the two sides of the gate comparison, pinned.

        This is the regression guard for a defect that had no symptom. `median_excess` arrives from
        `app.tournament.results.LeaderboardRowData` as a **fraction** -- round 15's top card posted
        `0.0675939...`, meaning +6.76 points -- while `promotion_margin_pp` holds **percentage
        points**. Comparing them without the `* 100` asks for a median excess of +2120 points against
        the default 21.2 floor, so the gate is not mis-tuned but closed, and closed invisibly: the
        loop searches forever, reports standings that look entirely reasonable, and silently never
        promotes anything.

        A fraction just over the margin/100 must clear; one just under must not. Anything that
        re-introduces the raw comparison fails both halves.
        """
        margin_pp = _CONFIG.promotion_margin_pp  # 5 points
        just_over = _standing("g001-a", median_excess=(margin_pp + Decimal("0.5")) / 100)
        just_under = _standing("g001-b", median_excess=(margin_pp - Decimal("0.5")) / 100)
        assert promotion.clears_gate(just_over, config=_CONFIG) is True
        assert promotion.clears_gate(just_under, config=_CONFIG) is False

        # And the real-world magnitude: r15's best committed card would NOT clear the default
        # 21.2-point floor. That is the intended behaviour of a floor set at the measured
        # ordering-noise level, and it is worth stating in a test so nobody "fixes" the gate by
        # loosening it when promotions turn out to be rare.
        r15_best = _standing("g001-c", median_excess=Decimal("0.0675939605255457229840544991"))
        assert promotion.clears_gate(r15_best, config=LoopConfig()) is False

    def test_feedback_and_promotion_agree_on_the_gate(self) -> None:
        """The panel must never report a candidate as having cleared a bar promotion then refuses.

        `app.evolution.feedback`'s gate finding counts candidates over `promotion_margin_pp`, and
        this module decides who is actually promoted. They are separate implementations of one rule,
        so they are checked against each other rather than each against its own idea of the units.
        """
        from app.evolution import feedback

        config = LoopConfig(promotion_margin_pp=Decimal("5"))
        standings = tuple(
            _standing(f"g001-{i}", median_excess=Decimal(str(value)))
            for i, value in enumerate(("0.01", "0.049", "0.051", "0.30", "0.95"))
        )
        gate = next(
            f
            for f in feedback.derive_findings(
                standings,
                config=config,
                purpose=Purpose.TRADING,
                selection_windows=("w1", "w2"),
                holdout_windows=(),
                genomes={},
            )
            if f.kind == "gate"
        )
        promoted_by_gate = sum(1 for s in standings if promotion.clears_gate(s, config=config))
        assert gate.evidence["cleared"] == promoted_by_gate == 3


# ---------------------------------------------------------------------------
# (b), (c) consecutive-generation evidence
# ---------------------------------------------------------------------------


class TestEvaluatePromotions:
    def test_one_qualifying_generation_is_not_enough(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        genome = _genome("g001-a")
        card = _card(genome.genome_id)
        _write_generated_card(settings, card)
        standing = _standing(genome.genome_id, median_excess=Decimal("0.30"))

        records = promotion.evaluate_promotions(
            standings=(standing,),
            genomes={genome.genome_id: genome},
            history=(),
            config=_CONFIG,
            generation=1,
            selection_windows=("w1", "w2"),
            settings=settings,
        )
        assert records == ()
        assert promotion.load_promotions(settings) == ()
        assert not (settings.library_dir / "candidates" / f"{genome.genome_id}.json").exists()

    def test_two_generations_on_the_same_window_set_is_not_enough(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        genome = _genome("g001-a")
        card = _card(genome.genome_id)
        _write_generated_card(settings, card)

        prior_standing = _standing(genome.genome_id, median_excess=Decimal("0.30"))
        history = (_outcome(1, ("w1", "w2"), (prior_standing,)),)

        current_standing = _standing(genome.genome_id, median_excess=Decimal("0.30"))
        records = promotion.evaluate_promotions(
            standings=(current_standing,),
            genomes={genome.genome_id: genome},
            history=history,
            config=_CONFIG,
            generation=2,
            selection_windows=("w1", "w2"),  # identical set to generation 1's
            settings=settings,
        )
        assert records == ()
        assert promotion.load_promotions(settings) == ()

    def test_two_generations_on_differing_window_sets_promotes(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        genome = _genome("g001-a")
        card = _card(genome.genome_id)
        _write_generated_card(settings, card)

        prior_standing = _standing(genome.genome_id, median_excess=Decimal("0.30"))
        history = (_outcome(1, ("w3", "w4"), (prior_standing,)),)

        current_standing = _standing(genome.genome_id, median_excess=Decimal("0.30"))
        records = promotion.evaluate_promotions(
            standings=(current_standing,),
            genomes={genome.genome_id: genome},
            history=history,
            config=_CONFIG,
            generation=2,
            selection_windows=("w1", "w2"),  # differs from generation 1's ("w3", "w4")
            settings=settings,
        )
        assert len(records) == 1
        record = records[0]
        assert record.genome_id == genome.genome_id
        assert record.generations == (1, 2)
        assert set(record.window_sets) == {("w3", "w4"), ("w1", "w2")}

    def test_a_negative_result_breaks_the_consecutive_streak(self, tmp_path) -> None:
        """A generation where the genome ran and *failed* to clear the gate ends the streak -- an
        earlier qualifying generation beyond that point must not be stitched across it."""
        settings = _settings(tmp_path)
        genome = _genome("g001-a")
        card = _card(genome.genome_id)
        _write_generated_card(settings, card)

        # Generation 1 qualifies, generation 2 does not (median at the margin), generation 3 (current)
        # qualifies again on yet another window set. The streak walking back from 3 stops at 2.
        gen1 = _standing(genome.genome_id, median_excess=Decimal("0.30"))
        gen2 = _standing(genome.genome_id, median_excess=Decimal("0.01"))  # fails the margin
        history = (
            _outcome(1, ("w5", "w6"), (gen1,)),
            _outcome(2, ("w3", "w4"), (gen2,)),
        )
        current_standing = _standing(genome.genome_id, median_excess=Decimal("0.30"))
        records = promotion.evaluate_promotions(
            standings=(current_standing,),
            genomes={genome.genome_id: genome},
            history=history,
            config=_CONFIG,
            generation=3,
            selection_windows=("w1", "w2"),
            settings=settings,
        )
        assert records == ()

    # -----------------------------------------------------------------
    # (d) lands in candidates/ and validates on reload
    # -----------------------------------------------------------------

    def test_promoted_card_lands_in_candidates_and_reloads(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        genome = _genome("g001-a")
        card = _card(genome.genome_id)
        _write_generated_card(settings, card)

        history = (_outcome(1, ("w3", "w4"), (_standing(genome.genome_id),)),)
        promotion.evaluate_promotions(
            standings=(_standing(genome.genome_id),),
            genomes={genome.genome_id: genome},
            history=history,
            config=_CONFIG,
            generation=2,
            selection_windows=("w1", "w2"),
            settings=settings,
        )

        dest = settings.library_dir / "candidates" / f"{genome.genome_id}.json"
        assert dest.is_file()
        reloaded = StrategyCard.model_validate_json(dest.read_text(encoding="utf-8"))
        assert reloaded == card
        # Never written straight into base/ -- section 6 requires a second, differently-evidenced step.
        assert not (settings.library_dir / "base" / f"{genome.genome_id}.json").exists()

    def test_promotion_source_is_data_loop_generated_not_under_library_dir(self, tmp_path) -> None:
        """The path-layering regression guard: the card promotion copies out of must be
        `settings.data_dir / "loop" / "generated"` -- exactly `generated_tier_dir(settings)` -- and
        never a `generated/` directory nested under `library_dir`. `library_dir` is only ever the
        *destination* (`candidates/`), never involved in resolving the source any more; see this
        module's own docstring on why the old, library-nested location broke in a container."""
        settings = _settings(tmp_path)
        genome = _genome("g001-a")
        card = _card(genome.genome_id)
        _write_generated_card(settings, card)

        source_dir = generated_tier_dir(settings)
        assert source_dir == settings.data_dir / "loop" / "generated"
        assert not source_dir.is_relative_to(settings.library_dir)
        assert (source_dir / f"{genome.genome_id}.json").is_file()

        history = (_outcome(1, ("w3", "w4"), (_standing(genome.genome_id),)),)
        records = promotion.evaluate_promotions(
            standings=(_standing(genome.genome_id),),
            genomes={genome.genome_id: genome},
            history=history,
            config=_CONFIG,
            generation=2,
            selection_windows=("w1", "w2"),
            settings=settings,
        )
        assert len(records) == 1
        dest = settings.library_dir / "candidates" / f"{genome.genome_id}.json"
        assert dest.is_file()

    # -----------------------------------------------------------------
    # (e) Roth disjointness refusal
    # -----------------------------------------------------------------

    def test_roth_candidate_sharing_a_ticker_with_a_taxable_card_is_refused(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        # An existing taxable card already holding AAA.
        _write_library_card(
            settings, "base", _card("existing-taxable", purpose=Purpose.TRADING, universe=("AAA", "ZZZ"))
        )

        genome = _genome("g001-roth", purpose=Purpose.ROTH, universe=("AAA", "CCC"))
        card = _card(genome.genome_id, purpose=Purpose.ROTH, universe=("AAA", "CCC"))
        _write_generated_card(settings, card)

        history = (_outcome(1, ("w3", "w4"), (_standing(genome.genome_id),), purpose=Purpose.ROTH),)
        records = promotion.evaluate_promotions(
            standings=(_standing(genome.genome_id),),
            genomes={genome.genome_id: genome},
            history=history,
            config=_CONFIG,
            generation=2,
            selection_windows=("w1", "w2"),
            settings=settings,
        )
        assert records == ()
        assert promotion.load_promotions(settings) == ()
        assert not (settings.library_dir / "candidates" / f"{genome.genome_id}.json").exists()

    def test_roth_candidate_with_no_overlap_promotes_normally(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        _write_library_card(
            settings, "base", _card("existing-taxable", purpose=Purpose.TRADING, universe=("ZZZ", "YYY"))
        )
        genome = _genome("g001-roth", purpose=Purpose.ROTH, universe=("AAA", "CCC"))
        card = _card(genome.genome_id, purpose=Purpose.ROTH, universe=("AAA", "CCC"))
        _write_generated_card(settings, card)

        history = (_outcome(1, ("w3", "w4"), (_standing(genome.genome_id),), purpose=Purpose.ROTH),)
        records = promotion.evaluate_promotions(
            standings=(_standing(genome.genome_id),),
            genomes={genome.genome_id: genome},
            history=history,
            config=_CONFIG,
            generation=2,
            selection_windows=("w1", "w2"),
            settings=settings,
        )
        assert len(records) == 1
        assert records[0].purpose is Purpose.ROTH

    # -----------------------------------------------------------------
    # (f) idempotence
    # -----------------------------------------------------------------

    def test_promotion_is_idempotent(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        genome = _genome("g001-a")
        card = _card(genome.genome_id)
        _write_generated_card(settings, card)
        history = (_outcome(1, ("w3", "w4"), (_standing(genome.genome_id),)),)

        first = promotion.evaluate_promotions(
            standings=(_standing(genome.genome_id),),
            genomes={genome.genome_id: genome},
            history=history,
            config=_CONFIG,
            generation=2,
            selection_windows=("w1", "w2"),
            settings=settings,
        )
        assert len(first) == 1

        second = promotion.evaluate_promotions(
            standings=(_standing(genome.genome_id),),
            genomes={genome.genome_id: genome},
            history=history,
            config=_CONFIG,
            generation=2,
            selection_windows=("w1", "w2"),
            settings=settings,
        )
        assert second == ()
        assert len(promotion.load_promotions(settings)) == 1

    def test_load_promotions_tolerates_a_truncated_last_line(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        genome = _genome("g001-a")
        card = _card(genome.genome_id)
        _write_generated_card(settings, card)
        history = (_outcome(1, ("w3", "w4"), (_standing(genome.genome_id),)),)
        promotion.evaluate_promotions(
            standings=(_standing(genome.genome_id),),
            genomes={genome.genome_id: genome},
            history=history,
            config=_CONFIG,
            generation=2,
            selection_windows=("w1", "w2"),
            settings=settings,
        )
        path = loop_root(settings) / "promotions.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write('{"genome_id": "truncated-partial-lin')  # no trailing newline, invalid JSON

        records = promotion.load_promotions(settings)
        assert len(records) == 1
        assert records[0].genome_id == genome.genome_id

    # -----------------------------------------------------------------
    # seat_on_paper_desk wiring
    # -----------------------------------------------------------------

    def test_requests_a_seat_when_configured_but_does_not_take_one(self, tmp_path) -> None:
        """**This test asserted the opposite until the approval gate landed, and the change is the
        point rather than a detail.** `seat_on_paper_desk=True` used to mean "seat it"; a promotion
        wrote the roster overlay itself and `PromotionRecord.seated` came back `True`. Left running,
        that seated 25 cards (18 roth, 7 trading) that no person had looked at -- the flag is a
        property of the whole run, chosen before any candidate existed, so it was never a judgement
        about any particular card.

        It now means "this loop may *ask*". The promotion is still recorded and the card is still
        copied into `candidates/`; only the desk waits for a person -- and since the two-stage review
        landed, for *two* separate decisions. Clearing the gate files a `"pending"` request;
        `shelve_pending_seat` accepts the card onto the review shelf, which deliberately writes no
        overlay at all; `seat_pending_seat` is the second, independent decision that actually seats
        it. Collapsing those two into one is what put 22 unreviewed cards on the desk on
        2026-08-26."""
        settings = _settings(tmp_path)
        genome = _genome("g001-a", purpose=Purpose.TRADING)
        card = _card(genome.genome_id)
        _write_generated_card(settings, card)
        history = (_outcome(1, ("w3", "w4"), (_standing(genome.genome_id),)),)

        config = LoopConfig(promotion_margin_pp=Decimal("5"), seat_on_paper_desk=True)
        records = promotion.evaluate_promotions(
            standings=(_standing(genome.genome_id),),
            genomes={genome.genome_id: genome},
            history=history,
            config=config,
            generation=2,
            selection_windows=("w1", "w2"),
            settings=settings,
        )

        assert records[0].seated is False, "a promotion must no longer seat anything by itself"
        assert genome.genome_id not in promotion.read_overlay(settings).get("trading", ())

        (request,) = promotion.read_pending_seats(settings)
        assert request.genome_id == genome.genome_id
        assert request.status == "pending"
        assert request.reason == records[0].reason

        # ...and the desk changes only once a person has made BOTH decisions. Shelving is not
        # seating: the first decision says the card is worth keeping, and must leave the desk alone.
        promotion.shelve_pending_seat(genome.genome_id, note="worth a look", settings=settings)
        assert genome.genome_id not in promotion.read_overlay(settings).get("trading", ()), (
            "shelving must not write the roster overlay -- that is the whole point of the stage"
        )

        promotion.seat_pending_seat(genome.genome_id, note="looks fine", settings=settings)
        assert genome.genome_id in promotion.read_overlay(settings)["trading"]

    def test_does_not_seat_when_disabled(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        genome = _genome("g001-a", purpose=Purpose.TRADING)
        card = _card(genome.genome_id)
        _write_generated_card(settings, card)
        history = (_outcome(1, ("w3", "w4"), (_standing(genome.genome_id),)),)

        config = LoopConfig(promotion_margin_pp=Decimal("5"), seat_on_paper_desk=False)
        records = promotion.evaluate_promotions(
            standings=(_standing(genome.genome_id),),
            genomes={genome.genome_id: genome},
            history=history,
            config=config,
            generation=2,
            selection_windows=("w1", "w2"),
            settings=settings,
        )
        assert records[0].seated is False
        overlay = promotion.read_overlay(settings)
        assert overlay["trading"] == ()


# ---------------------------------------------------------------------------
# seat_on_desk / read_overlay
# ---------------------------------------------------------------------------


class TestOverlay:
    def test_read_overlay_missing_file_is_all_empty(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        overlay = promotion.read_overlay(settings)
        assert overlay == {"savings": (), "trading": (), "roth": ()}

    def test_seat_on_desk_is_additive_and_idempotent(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        assert promotion.seat_on_desk("g001-a", Purpose.TRADING, settings=settings) is True
        assert promotion.seat_on_desk("g002-b", Purpose.TRADING, settings=settings) is True
        assert promotion.seat_on_desk("g001-a", Purpose.TRADING, settings=settings) is True  # no dupe

        overlay = promotion.read_overlay(settings)
        assert overlay["trading"] == ("g001-a", "g002-b")
        assert overlay["roth"] == ()
        assert overlay["savings"] == ()

    def test_overlay_file_is_written_atomically_no_stray_temp_file(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        promotion.seat_on_desk("g001-a", Purpose.ROTH, settings=settings)
        path = roster_overlay_path(settings)
        assert path.is_file()
        leftovers = list(path.parent.glob("*.tmp-*"))
        assert leftovers == []


# ---------------------------------------------------------------------------
# (g), (h) app.paperdesk.desk.rosters reading the overlay
# ---------------------------------------------------------------------------


class TestDeskRostersOverlay:
    def test_missing_overlay_matches_todays_hand_authored_desk(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        settings = settings.model_copy(update={"paperdesk_agent_ids": ("T1", "T2")})
        result = desk.rosters(settings)
        assert result == {
            Purpose.SAVINGS: desk.SAVINGS_AGENT_IDS,
            Purpose.TRADING: ("T1", "T2"),
            Purpose.ROTH: desk.ROTH_AGENT_IDS,
        }

    def test_malformed_overlay_leaves_the_desk_unchanged_and_does_not_raise(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        settings = settings.model_copy(update={"paperdesk_agent_ids": ("T1",)})
        overlay_path = roster_overlay_path(settings)
        overlay_path.parent.mkdir(parents=True, exist_ok=True)
        overlay_path.write_text("{not valid json", encoding="utf-8")

        result = desk.rosters(settings)  # must not raise
        assert result == {
            Purpose.SAVINGS: desk.SAVINGS_AGENT_IDS,
            Purpose.TRADING: ("T1",),
            Purpose.ROTH: desk.ROTH_AGENT_IDS,
        }

    def test_malformed_seats_entry_leaves_that_purpose_unchanged(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        settings = settings.model_copy(update={"paperdesk_agent_ids": ("T1",)})
        overlay_path = roster_overlay_path(settings)
        overlay_path.parent.mkdir(parents=True, exist_ok=True)
        overlay_path.write_text(
            json.dumps({"version": 1, "seats": {"trading": "not-a-list"}}), encoding="utf-8"
        )
        result = desk.rosters(settings)
        assert result[Purpose.TRADING] == ("T1",)

    def test_overlay_is_additive(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        settings = settings.model_copy(update={"paperdesk_agent_ids": ("T1",)})
        # Give the overlay's id a real card to resolve against.
        card = _card("auto-promoted-1")
        _write_library_card(settings, "candidates", card)
        promotion.seat_on_desk("auto-promoted-1", Purpose.TRADING, settings=settings)

        result = desk.rosters(settings)
        assert result[Purpose.TRADING] == ("T1", "auto-promoted-1")
        # The other two books are untouched.
        assert result[Purpose.SAVINGS] == desk.SAVINGS_AGENT_IDS
        assert result[Purpose.ROTH] == desk.ROTH_AGENT_IDS

    def test_overlay_id_naming_a_nonexistent_card_is_skipped_not_raised(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        settings = settings.model_copy(update={"paperdesk_agent_ids": ("T1",)})
        promotion.seat_on_desk("ghost-card-no-such-file", Purpose.TRADING, settings=settings)

        result = desk.rosters(settings)  # must not raise
        assert result[Purpose.TRADING] == ("T1",)

    def test_deleting_the_overlay_restores_exactly_todays_desk(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        settings = settings.model_copy(update={"paperdesk_agent_ids": ("T1",)})
        card = _card("auto-promoted-1")
        _write_library_card(settings, "candidates", card)
        promotion.seat_on_desk("auto-promoted-1", Purpose.TRADING, settings=settings)
        assert desk.rosters(settings)[Purpose.TRADING] == ("T1", "auto-promoted-1")

        roster_overlay_path(settings).unlink()
        assert desk.rosters(settings)[Purpose.TRADING] == ("T1",)

    def test_overlay_never_removes_or_reorders_hand_authored_ids(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        settings = settings.model_copy(update={"paperdesk_agent_ids": ("T1", "T2", "T3")})
        card = _card("auto-promoted-1")
        _write_library_card(settings, "candidates", card)
        promotion.seat_on_desk("auto-promoted-1", Purpose.TRADING, settings=settings)

        result = desk.rosters(settings)
        assert result[Purpose.TRADING][:3] == ("T1", "T2", "T3")
        assert result[Purpose.TRADING][3] == "auto-promoted-1"


# ---------------------------------------------------------------------------
# (d) app.tournament.jobs._load_library_index's malformed-payload tolerance, re-checked against the
# new `data/loop/generated/` location -- the `generated` tier stays lenient (an `AllocationCard`
# payload is real content, not a defect, see that function's own docstring), while `base/` stays
# strict (a malformed payload there is a genuine defect this index must not silently swallow).
# ---------------------------------------------------------------------------


class TestJobsIndexToleratesOnlyTheGeneratedTier:
    def test_malformed_json_in_generated_tier_is_skipped(self, tmp_path, monkeypatch) -> None:
        settings = _settings(tmp_path)
        monkeypatch.setattr(jobs, "get_settings", lambda: settings)

        generated_dir = generated_tier_dir(settings)
        generated_dir.mkdir(parents=True, exist_ok=True)
        (generated_dir / "not-a-card.json").write_text('{"this": "is not a StrategyCard"}', encoding="utf-8")

        # A real, valid card alongside the malformed one must still be found.
        genome = _genome("g001-a")
        card = _card(genome.genome_id)
        _write_generated_card(settings, card)

        index = jobs._load_library_index()
        assert genome.genome_id in index
        assert "not-a-card" not in index

    def test_malformed_json_in_base_tier_raises(self, tmp_path, monkeypatch) -> None:
        settings = _settings(tmp_path)
        monkeypatch.setattr(jobs, "get_settings", lambda: settings)

        base_dir = settings.library_dir / "base"
        base_dir.mkdir(parents=True, exist_ok=True)
        (base_dir / "not-a-card.json").write_text('{"this": "is not a StrategyCard"}', encoding="utf-8")

        with pytest.raises(ValidationError):
            jobs._load_library_index()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


class TestGatePrefersTheExposureCorrectedMedian:
    """`clears_gate` ranks on `median_adjusted_excess` when it exists.

    Plain `excess` measured at Pearson r = -0.978 against a window's own median benchmark across 749
    runs -- so on the uncorrected figure a card is largely scored on which way the market went. The
    correction subtracts `capital_exposure * benchmark_return` and asks PROTOCOL.md section 4's real
    question: whether the rules beat being invested the same fraction of the time.
    """

    def _standing(self, **kw):
        base = dict(
            genome_id="g1",
            agent_id="g1",
            display_name="g1",
            rank=1,
            eligible=True,
            windows_run=5,
            median_excess=Decimal("0.30"),
            worst_excess=Decimal("0.10"),
            hit_rate=0.8,
            total_trades=40,
        )
        base.update(kw)
        return Standing(**base)

    def test_a_card_that_only_looks_good_uncorrected_is_refused(self) -> None:
        """+30pp of plain excess, -19pp once its exposure is accounted for: the measured `gfc`
        shape. The uncorrected number would clear a 21.2pp margin comfortably."""
        config = LoopConfig(promotion_margin_pp=Decimal("21.2"))
        standing = self._standing(median_adjusted_excess=Decimal("-0.19"))
        assert promotion.clears_gate(standing, config=config) is False

    def test_the_corrected_number_can_also_let_a_card_through(self) -> None:
        config = LoopConfig(promotion_margin_pp=Decimal("21.2"))
        standing = self._standing(
            median_excess=Decimal("0.05"), median_adjusted_excess=Decimal("0.25")
        )
        assert promotion.clears_gate(standing, config=config) is True

    def test_falls_back_to_plain_excess_on_a_standing_from_before_the_correction(self) -> None:
        """Every generation already on disk was scored on plain excess and PROTOCOL.md section 2
        forbids restating them. The gate keeps working on the weaker number rather than refusing to
        promote anything from an older round."""
        config = LoopConfig(promotion_margin_pp=Decimal("21.2"))
        assert promotion.clears_gate(self._standing(), config=config) is True

    def test_a_negative_corrected_holdout_disqualifies_even_with_a_positive_raw_one(self) -> None:
        """With an all-drawdown holdout the uncorrected clause was nearly free: 86.8% of
        candidate-windows posted a non-negative excess because a falling benchmark hands one out.
        Corrected, that falls to 40%."""
        config = LoopConfig(promotion_margin_pp=Decimal("21.2"))
        standing = self._standing(
            median_adjusted_excess=Decimal("0.30"),
            holdout_median_excess=Decimal("0.12"),
            holdout_median_adjusted_excess=Decimal("-0.02"),
        )
        assert promotion.clears_gate(standing, config=config) is False


class TestHoldoutDefaultIsNotRegimeMonotone:
    def test_pairs_a_drawdown_with_a_rally(self) -> None:
        """An all-drawdown holdout was measurably *easier* than the selection set, not harder --
        both windows falling, and `excess` pays for not being fully invested in a falling market."""
        from app.tournament.jobs import MAIN_WINDOWS

        holdout = LoopConfig().holdout_windows
        assert set(holdout) == {"q4-2018", "bull-2024"}
        assert all(w in MAIN_WINDOWS for w in holdout)

    def test_leaves_a_pool_big_enough_to_still_rotate(self) -> None:
        """**A 3-window holdout would have made promotion impossible rather than stricter.**
        `MAIN_WINDOWS` (8) minus a 3-window holdout leaves 5 = `MIN_ELIGIBLE_MAIN_WINDOWS`, and
        `_resolve_selection_windows` returns a pool at or under that floor whole and unrotated. With
        no rotation every generation of a lane runs the same window set, and `evaluate_promotions`
        requires clearances on window sets that *differ* -- so nothing could ever be promoted, with
        no symptom saying why. Swapping keeps the pool at 6."""
        from app.tournament.jobs import MAIN_WINDOWS, MIN_ELIGIBLE_MAIN_WINDOWS

        pool = set(MAIN_WINDOWS) - set(LoopConfig().holdout_windows)
        assert len(pool) > MIN_ELIGIBLE_MAIN_WINDOWS, (
            f"a {len(pool)}-window pool cannot drop one and stay at the {MIN_ELIGIBLE_MAIN_WINDOWS} "
            "floor, so rotation would stop and promotion would become impossible"
        )


class TestPromotionOverlapCeiling:
    """`LoopConfig.promotion_max_shared_windows` -- how much two evidence sets may have in common.

    The rule this tightens (`PROTOCOL.md` section 6(a): a *differing* window set is a second piece of
    evidence) is satisfied by one window in five, and the loop's own rotation drops exactly one window
    per appearance, so every promotion it has ever made cleared the gate twice on sets that shared 80%
    of their windows. `docs/research/loop/01-what-the-search-found.md` point 2 is the write-up.
    """

    def _promote(self, settings, *, config, prior_windows, current_windows):
        genome = _genome("g001-a")
        _write_generated_card(settings, _card(genome.genome_id))
        standing = _standing(genome.genome_id, median_excess=Decimal("0.30"))
        history = (_outcome(1, prior_windows, (standing,)),)
        return promotion.evaluate_promotions(
            standings=(_standing(genome.genome_id, median_excess=Decimal("0.30")),),
            genomes={genome.genome_id: genome},
            history=history,
            config=config,
            generation=2,
            selection_windows=current_windows,
            settings=settings,
        )

    def test_default_is_none_so_behaviour_is_unchanged(self) -> None:
        """The shipped default must not silently re-gate a running loop -- amendments are
        non-retroactive, and a config nobody edited has to keep meaning what it meant."""
        assert LoopConfig().promotion_max_shared_windows is None

    def test_one_window_of_difference_still_promotes_with_no_ceiling(self, tmp_path) -> None:
        records = self._promote(
            _settings(tmp_path),
            config=_CONFIG,
            prior_windows=("w1", "w2", "w3", "w4", "w5"),
            current_windows=("w1", "w2", "w3", "w4", "w6"),
        )
        assert len(records) == 1

    def test_the_same_pair_is_refused_once_a_ceiling_is_set(self, tmp_path) -> None:
        """Four shared windows against a ceiling of two: the sets differ, so the old rule counted them,
        and the new one does not."""
        records = self._promote(
            _settings(tmp_path),
            config=_CONFIG.model_copy(update={"promotion_max_shared_windows": 2}),
            prior_windows=("w1", "w2", "w3", "w4", "w5"),
            current_windows=("w1", "w2", "w3", "w4", "w6"),
        )
        assert records == ()

    def test_a_genuine_swap_clears_the_ceiling(self, tmp_path) -> None:
        records = self._promote(
            _settings(tmp_path),
            config=_CONFIG.model_copy(update={"promotion_max_shared_windows": 2}),
            prior_windows=("w1", "w2", "w3", "w4", "w5"),
            current_windows=("w1", "w2", "w6", "w7", "w8"),
        )
        assert len(records) == 1

    def test_a_ceiling_equal_to_the_overlap_is_met(self, tmp_path) -> None:
        """`<=`, not `<`: a ceiling of four permits four shared windows. Stated as a test because an
        off-by-one here closes the gate on every promotion the shipped rotation can produce."""
        records = self._promote(
            _settings(tmp_path),
            config=_CONFIG.model_copy(update={"promotion_max_shared_windows": 4}),
            prior_windows=("w1", "w2", "w3", "w4", "w5"),
            current_windows=("w1", "w2", "w3", "w4", "w6"),
        )
        assert len(records) == 1

    def test_the_reason_states_the_overlap_even_with_no_ceiling(self, tmp_path) -> None:
        """The point of the change that is not a gate: the number is written down. Recovering it from
        `promotions.jsonl` afterwards is what made the finding an archaeology exercise."""
        records = self._promote(
            _settings(tmp_path),
            config=_CONFIG,
            prior_windows=("w1", "w2", "w3", "w4", "w5"),
            current_windows=("w1", "w2", "w3", "w4", "w6"),
        )
        assert "sharing at most 4 window(s)" in records[0].reason
        assert "no overlap ceiling set" in records[0].reason

    def test_the_reason_names_the_ceiling_when_one_is_set(self, tmp_path) -> None:
        records = self._promote(
            _settings(tmp_path),
            config=_CONFIG.model_copy(update={"promotion_max_shared_windows": 2}),
            prior_windows=("w1", "w2", "w3", "w4", "w5"),
            current_windows=("w1", "w2", "w6", "w7", "w8"),
        )
        assert "sharing at most 2 window(s), within the 2-window overlap ceiling" in records[0].reason

    def test_a_third_set_is_compared_against_every_counted_set_not_just_the_last(
        self, tmp_path
    ) -> None:
        """Three generations, `promotion_consecutive=3`. Generation 2 swaps away from generation 1 and
        generation 3 swaps back onto generation 1's windows: each set differs from its immediate
        predecessor by enough, and generation 3 is nonetheless a repeat of a measurement already
        counted. Comparing only against the newest set would promote on two readings of one window
        set plus one other."""
        settings = _settings(tmp_path)
        genome = _genome("g001-a")
        _write_generated_card(settings, _card(genome.genome_id))
        config = _CONFIG.model_copy(
            update={"promotion_consecutive": 3, "promotion_max_shared_windows": 2}
        )
        standing = _standing(genome.genome_id, median_excess=Decimal("0.30"))
        history = (
            _outcome(1, ("w1", "w2", "w3", "w4", "w5"), (standing,)),
            _outcome(2, ("w6", "w7", "w8", "w9", "wa"), (standing,)),
        )
        records = promotion.evaluate_promotions(
            standings=(_standing(genome.genome_id, median_excess=Decimal("0.30")),),
            genomes={genome.genome_id: genome},
            history=history,
            config=config,
            generation=3,
            selection_windows=("w1", "w2", "w3", "w4", "w5"),  # generation 1's set, verbatim
            settings=settings,
        )
        assert records == ()


class TestAchievableSharedWindows:
    """The floor `start_loop` refuses a ceiling against -- one branch per branch of
    `_resolve_selection_windows`, because the two functions have to keep agreeing."""

    def test_the_rotating_default_floor_is_the_pool_minus_two(self) -> None:
        floor, detail = loop_module.achievable_shared_windows(LoopConfig())
        assert floor == 4
        assert "6 window(s)" in detail

    def test_explicit_windows_never_rotate_so_the_floor_is_the_whole_set(self) -> None:
        floor, detail = loop_module.achievable_shared_windows(
            LoopConfig(windows=("gfc", "covid", "recent"))
        )
        assert floor == 3
        assert "never rotated" in detail

    def test_a_pool_at_the_eligibility_floor_is_returned_whole(self) -> None:
        """The trap `holdout_windows`' docstring records: a three-window holdout leaves five, which
        `_resolve_selection_windows` returns unrotated, so no two sets ever differ at all."""
        floor, detail = loop_module.achievable_shared_windows(
            LoopConfig(holdout_windows=("covid", "q4-2018", "bull-2024"))
        )
        assert floor == 5
        assert "MIN_ELIGIBLE_MAIN_WINDOWS" in detail

    def test_start_loop_refuses_an_unreachable_ceiling_before_starting_anything(self) -> None:
        with pytest.raises(UnreachablePromotionCeiling) as excinfo:
            loop_module.start_loop(LoopConfig(promotion_max_shared_windows=2))
        assert excinfo.value.achievable == 4
        assert "Raise the ceiling to 4 or more" in str(excinfo.value)
        # Refused before the singleton was claimed, so the next caller is not met with a 409.
        assert loop_module.get_status() is None or loop_module.get_status().state != "running"

    def test_a_reachable_ceiling_is_not_refused(self, monkeypatch) -> None:
        """Only the guard is under test here -- `start_loop` would otherwise spawn a real supervisor,
        so the reachability check is called directly on the same config."""
        config = LoopConfig(promotion_max_shared_windows=4)
        floor, _ = loop_module.achievable_shared_windows(config)
        assert config.promotion_max_shared_windows is not None
        assert config.promotion_max_shared_windows >= floor
