"""Tests for `app.evolution.universe`, `app.evolution.genome` and `app.evolution.proposer` --
the candidate-generation half of the evolution loop.

Every test here pins one concrete guarantee this trio makes, rather than asserting against whatever
the code under test happens to produce:

* `TestPoolDisjointness` -- `universe.py`'s central promise: the Roth pool and the taxable pools share
  no ticker, structurally, and neither pool collides with a taxable-purpose card already committed to
  `backend/app/paper/library/` (see `universe.py`'s own docstring on the XLV/TLT/SMH substitutions
  this required).
* `TestBarAvailability` -- every symbol either pool ships has a stored daily bar, checked against the
  real `data/store/bars/` tree (there is nothing to fake here: a symbol with no bars is a real defect
  regardless of what a synthetic fixture says).
* `TestGenomeDeterminism` -- the same `random.Random` seed and the same other arguments produce the
  same `genome_id`, for both card shapes.
* `TestCardFor` -- `card_for` builds a real, validating card for both shapes, the emitted rule text
  parses under `app.rules.grammar`, and an allocation card's sleeve weights sum to *exactly*
  `Decimal(1)`.
* `TestMutate` -- never crosses the purpose boundary, and never exceeds the ten-parameter budget.
* `TestWriteCards` -- round-trips a card off disk through `StrategyCard.model_validate_json` /
  `AllocationCard.model_validate_json`.
* `TestProposeGeneration` -- the Roth safety gate, the incumbent-carry-forward contract
  `propose_generation` needs so `app.evolution.promotion`'s two-consecutive-generations gate has
  anything to actually measure twice, and shape-homogeneity: every genome a call returns shares the
  requested `shape`, and an elite of a different shape is dropped rather than carried forward.
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from app.config import Settings
from app.evolution import ruleforms
from app.evolution.genome import crossover, mutate, random_genome
from app.evolution.models import (
    MAX_FREE_PARAMETERS,
    RULE_SHAPES,
    RULES_PERIOD_BOUNDS,
    Genome,
    LoopConfig,
    ProposalRejected,
    content_digest,
    generated_tier_dir,
    loop_root,
)
from app.evolution.proposer import (
    card_for,
    load_seen_genomes,
    propose_generation,
    write_cards,
)
from app.evolution.universe import (
    MIN_WARMUP_BARS,
    coverage_gaps,
    filter_to_available,
    pool_for,
    symbols_with_bars,
)
from app.rules import grammar
from app.tournament import jobs
from app.tournament.allocation import AllocationCard
from app.tournament.jobs import MAIN_WINDOWS
from app.tournament.models import Discipline, StrategyCard
from app.tournament.purposes import Purpose, find_disjointness_violations
from app.tournament.results import load_library
from tests.conftest import requires_real_store

# ---------------------------------------------------------------------------
# (a) Roth/taxable pool disjointness
# ---------------------------------------------------------------------------


class TestPoolDisjointness:
    def test_roth_and_taxable_pools_share_no_ticker(self) -> None:
        roth = set(pool_for(Purpose.ROTH).all_symbols())
        trading = set(pool_for(Purpose.TRADING).all_symbols())
        savings = set(pool_for(Purpose.SAVINGS).all_symbols())
        assert trading == savings, "TRADING and SAVINGS must share the identical taxable ticker set"
        assert roth.isdisjoint(trading), roth & trading
        assert roth.isdisjoint(savings), roth & savings

    def test_roth_pool_is_disjoint_from_the_real_committed_library(self) -> None:
        """The structural guarantee above is necessary but not sufficient: a Roth pool ticker that
        happens to already be traded by an existing taxable-purpose card (in any tier, including
        `retired/`) would make `propose_generation`'s safety gate fail every single Roth generation.
        This is exactly the check that caught the originally suggested SMH/XLV/TLT before they shipped
        -- see `universe.py`'s own docstring for the full story -- kept here as a regression guard.
        """
        library = load_library()
        existing_cards = [card for tier_cards in library.values() for card in tier_cards]
        roth_symbols = pool_for(Purpose.ROTH).all_symbols()

        class _FakeRothCard:
            agent_id = "pool-check"
            purpose = Purpose.ROTH
            universe = roth_symbols

        violations = find_disjointness_violations([_FakeRothCard(), *existing_cards])
        assert violations == (), [v.message for v in violations]


# ---------------------------------------------------------------------------
# (b) every pool symbol has bars
# ---------------------------------------------------------------------------


@requires_real_store
class TestBarAvailability:
    @pytest.mark.parametrize("purpose", [Purpose.TRADING, Purpose.SAVINGS, Purpose.ROTH])
    def test_every_pool_symbol_has_stored_bars(self, purpose: Purpose) -> None:
        settings = Settings()  # the real, repo-rooted settings -- this checks the real bars tree
        pool = pool_for(purpose)
        available = symbols_with_bars(settings)
        missing = set(pool.all_symbols()) - available
        assert not missing, f"{purpose.value} pool ships symbols with no stored bars: {sorted(missing)}"

    def test_filter_to_available_preserves_order_and_drops_nothing_today(self) -> None:
        settings = Settings()
        pool = pool_for(Purpose.TRADING)
        filtered = filter_to_available(pool.growth, settings)
        assert filtered == pool.growth

    def test_every_pool_symbol_has_warmup_history_for_every_main_window(self) -> None:
        """The regression guard for the defect that made the first live loop unable to score anything.

        "Has stored bars" is not the property that matters; "has enough bars *before each window*"
        is. An entry rule carries an indicator warmup, and `app.backtest.guards` fails a whole card
        for a window when one of its symbols has no post-warmup region to demonstrate causality over.
        The refusal is recorded as an ordinary card failure, so the symptom is not an error anyone
        sees -- it is a window quietly producing nothing.

        Measured, before the pools were corrected: META and SCHD had **zero** bars before both `gfc`
        and `chop-2011`; SGOV had zero before five of the eight main windows; BIL had 93 before `gfc`
        and BND 128, both real first bars that are nowhere near the 200 an `sma(200)` rank key needs.
        A live round recorded `chop-2011: 0 run file(s) written, 6 run(s) attempted`, every candidate
        came back below the five-window eligibility floor, and the generation reported
        `0 of 0 eligible candidate(s) cleared the margin` -- the loop could not have promoted anything
        no matter how long it ran.

        If this fails, substitute the ticker. Do not lower `MIN_WARMUP_BARS` to make it pass: the
        threshold is derived from the genome's own indicator vocabulary, so lowering it re-admits
        exactly the cards the engine will refuse.
        """
        settings = Settings()  # the real repo-rooted settings -- this checks the real bars tree
        gaps = coverage_gaps({tag: bounds[0] for tag, bounds in MAIN_WINDOWS.items()}, settings)
        assert not gaps, (
            "these pool symbols cannot cover every main window's indicator warmup "
            f"(need {MIN_WARMUP_BARS} bars before the window opens): "
            + "; ".join(f"{sym} misses {', '.join(tags)}" for sym, tags in sorted(gaps.items()))
        )


# ---------------------------------------------------------------------------
# (c) genome determinism
# ---------------------------------------------------------------------------


class TestGenomeDeterminism:
    @pytest.mark.parametrize("shape", ["rules", "allocation"])
    def test_same_seed_same_inputs_same_genome_id(self, shape: str) -> None:
        g1 = random_genome(random.Random(42), generation=3, purpose=Purpose.ROTH, shape=shape)
        g2 = random_genome(random.Random(42), generation=3, purpose=Purpose.ROTH, shape=shape)
        assert g1.genome_id == g2.genome_id
        assert g1.universe == g2.universe
        assert g1.traits == g2.traits

    def test_different_seed_usually_different_genome_id(self) -> None:
        g1 = random_genome(random.Random(1), generation=0, purpose=Purpose.TRADING, shape="rules")
        g2 = random_genome(random.Random(2), generation=0, purpose=Purpose.TRADING, shape="rules")
        assert g1.genome_id != g2.genome_id


# ---------------------------------------------------------------------------
# (d) card_for validates both shapes; (e) emitted rules parse; (f) allocation weights sum to 1
# ---------------------------------------------------------------------------


class TestCardFor:
    @pytest.mark.parametrize("purpose", [Purpose.TRADING, Purpose.ROTH])
    def test_rules_shape_produces_a_validating_strategy_card(self, purpose: Purpose) -> None:
        for seed in range(15):
            genome = random_genome(random.Random(seed), generation=0, purpose=purpose, shape="rules")
            card = card_for(genome)
            assert isinstance(card, StrategyCard)
            assert card.agent_id == genome.genome_id
            assert card.purpose is purpose
            assert card.thesis.startswith("Machine-proposed candidate (app.evolution). ")

    @pytest.mark.parametrize("purpose", [Purpose.TRADING, Purpose.ROTH])
    def test_allocation_shape_produces_a_validating_allocation_card(self, purpose: Purpose) -> None:
        for seed in range(15):
            genome = random_genome(random.Random(seed), generation=0, purpose=purpose, shape="allocation")
            card = card_for(genome)
            assert isinstance(card, AllocationCard)
            assert card.agent_id == genome.genome_id
            assert card.purpose is purpose
            assert card.thesis.startswith("Machine-proposed candidate (app.evolution). ")

    def test_emitted_entry_and_exit_parse_under_the_rule_grammar(self) -> None:
        for seed in range(20):
            genome = random_genome(random.Random(seed), generation=0, purpose=Purpose.TRADING, shape="rules")
            card = card_for(genome)
            assert isinstance(card, StrategyCard)
            grammar.parse(card.entry)
            grammar.parse(card.exit)
            if card.rank_by is not None:
                grammar.parse_ranking(card.rank_by)

    def test_allocation_weights_sum_to_exactly_decimal_one(self) -> None:
        for seed in range(20):
            genome = random_genome(random.Random(seed), generation=0, purpose=Purpose.ROTH, shape="allocation")
            card = card_for(genome)
            assert isinstance(card, AllocationCard)
            total = sum((sleeve.target_weight for sleeve in card.sleeves), Decimal(0))
            assert total == Decimal(1), (genome.genome_id, [str(s.target_weight) for s in card.sleeves])

    def test_allocation_weights_still_sum_to_one_after_mutation_and_crossover(self) -> None:
        rng = random.Random(99)
        parent = random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="allocation")
        for _ in range(20):
            child = mutate(parent, rng, generation=1)
            card = card_for(child)
            assert isinstance(card, AllocationCard)
            total = sum((sleeve.target_weight for sleeve in card.sleeves), Decimal(0))
            assert total == Decimal(1), [str(s.target_weight) for s in card.sleeves]
            parent = child

    def test_crossover_offspring_weights_sum_to_one(self) -> None:
        rng = random.Random(17)
        a = random_genome(rng, generation=0, purpose=Purpose.ROTH, shape="allocation")
        b = random_genome(rng, generation=0, purpose=Purpose.ROTH, shape="allocation")
        for _ in range(20):
            child = crossover(a, b, rng, generation=1)
            card = card_for(child)
            assert isinstance(card, AllocationCard)
            total = sum((sleeve.target_weight for sleeve in card.sleeves), Decimal(0))
            assert total == Decimal(1)


# ---------------------------------------------------------------------------
# The search space is a space -- `rule_shape` is an evolvable trait, and `discipline` is read off the
# rule rather than drawn beside it.
#
# Both halves of the defect `docs/research/loop/01-what-the-search-found.md` records: 2,374 evaluations
# of one hardcoded entry template, and a label so free of the rule it decorated that two of the 25
# outstanding seat requests are byte-identical cards under different discipline names.
# ---------------------------------------------------------------------------


def _legacy_rules_genome(**overrides: object) -> Genome:
    """A genome in the pre-`rule_shape` vocabulary -- `discipline`, no `rule_shape` -- shaped like the
    ones the completed 231-generation run actually wrote to disk and that `load_seen_genomes` and the
    loop's elite selection both reload."""
    traits: dict[str, object] = {
        "fast": 13,
        "slow": 21,
        "regime_ma": 135,
        "stop_loss_pct": 0.08,
        "take_profit_pct": 0.25,
        "max_hold_days": 120,
        "max_positions": 4,
        "position_pct": 0.2,
        "rank_key": "rsi(14)",
        "discipline": "pairs-rotation",
    }
    traits.update(overrides)
    return Genome(
        genome_id="g1815-d05786e4c611",
        generation=1815,
        parents=(),
        origin="mutation",
        shape="rules",
        purpose=Purpose.TRADING,
        universe=("NVDA", "TSM", "MU"),
        traits=traits,
        seed=1,
        notes="legacy",
    )


class TestRuleShapeIsSearched:
    def test_a_generation_of_random_genomes_spans_more_than_one_rule_form(self) -> None:
        """The finding this replaces, stated as its inverse: masking the numbers out of all 25 seat
        requests of the completed run yielded exactly one entry/exit template, because there was only
        one to yield."""
        entries = set()
        rng = random.Random(4)
        for generation in range(60):
            genome = random_genome(rng, generation=generation, purpose=Purpose.TRADING, shape="rules")
            card = card_for(genome)
            assert isinstance(card, StrategyCard)
            entries.add(card.entry.replace(str(genome.traits["fast"]), "F"))
        # Not "all eight" -- 60 draws over 8 shapes leaves a real chance of missing one, and a test that
        # depends on which is not testing the thing it names.
        assert len({e.split(" and ")[-1] for e in entries}) > 1, entries

    def test_every_declared_shape_builds_a_card_that_validates(self) -> None:
        rng = random.Random(8)
        base = random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="rules")
        for shape in RULE_SHAPES:
            traits = dict(base.traits) | {"rule_shape": shape}
            genome = base.model_copy(update={"traits": traits})
            card = card_for(genome)
            assert isinstance(card, StrategyCard)
            grammar.parse(card.entry)
            grammar.parse(card.exit)
            assert shape in card.display_name
            assert shape in card.thesis

    def test_mutating_the_shape_changes_the_rule(self) -> None:
        """The property `discipline` did not have. 26 of the completed run's 673 single-parent mutations
        produced a child behaviourally identical to its parent, 15 of them because the only trait touched
        was a label nothing read."""
        rng = random.Random(21)
        base = random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="rules")
        rules = set()
        for shape in RULE_SHAPES:
            genome = base.model_copy(update={"traits": dict(base.traits) | {"rule_shape": shape}})
            card = card_for(genome)
            assert isinstance(card, StrategyCard)
            rules.add((card.entry, card.exit))
        assert len(rules) == len(RULE_SHAPES)

    def test_an_unknown_shape_is_rejected_not_rendered(self) -> None:
        rng = random.Random(5)
        base = random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="rules")
        genome = base.model_copy(
            update={"traits": dict(base.traits) | {"rule_shape": "bollinger-squeeze"}}
        )
        with pytest.raises(ProposalRejected, match="rule_shape="):
            card_for(genome)


class TestDisciplineDescribesTheRule:
    def test_discipline_matches_what_the_emitted_rule_does(self) -> None:
        rng = random.Random(31)
        base = random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="rules")
        for shape in RULE_SHAPES:
            genome = base.model_copy(update={"traits": dict(base.traits) | {"rule_shape": shape}})
            card = card_for(genome)
            assert isinstance(card, StrategyCard)
            assert card.discipline is ruleforms.classify(card.entry, card.exit)

    def test_two_cards_with_the_same_rule_cannot_carry_different_disciplines(self) -> None:
        """The `g1815`/`g1823` and `g1763`/`g1767` pairs, as a property. Two genomes differing only in
        `genome_id` and `generation` produce two cards with identical rules -- and now, necessarily,
        identical disciplines."""
        rng = random.Random(12)
        a = random_genome(rng, generation=1815, purpose=Purpose.TRADING, shape="rules")
        b = a.model_copy(update={"genome_id": "g1823-e2a3d5060b09", "generation": 1823})
        card_a, card_b = card_for(a), card_for(b)
        assert isinstance(card_a, StrategyCard) and isinstance(card_b, StrategyCard)
        assert (card_a.entry, card_a.exit) == (card_b.entry, card_b.exit)
        assert card_a.discipline is card_b.discipline

    def test_discipline_is_not_a_trait_and_a_stale_one_is_ignored(self) -> None:
        """A genome carrying the old label -- reloaded off disk -- gets the discipline its rule earns,
        not the one it was drawn with. `"pairs-rotation"` is the label 348 of 934 rules genomes carried
        and that this engine cannot express at all: `entry` is evaluated per symbol."""
        card = card_for(_legacy_rules_genome())
        assert isinstance(card, StrategyCard)
        assert card.discipline is not Discipline.PAIRS_ROTATION
        assert card.discipline is Discipline.TREND

    def test_a_fresh_genome_carries_no_discipline_trait(self) -> None:
        genome = random_genome(random.Random(2), generation=0, purpose=Purpose.ROTH, shape="rules")
        assert "discipline" not in genome.traits
        assert "rule_shape" in genome.traits


class TestLegacyGenomesKeepBreeding:
    def test_a_pre_rule_shape_genome_still_builds_the_card_it_was_scored_as(self) -> None:
        card = card_for(_legacy_rules_genome())
        assert isinstance(card, StrategyCard)
        assert card.entry == "close > sma(135) and ema(13) crosses_above ema(21)"
        assert card.exit == "ema(13) crosses_below ema(21)"

    def test_mutating_a_pre_rule_shape_genome_adopts_the_new_vocabulary(self) -> None:
        """Without the translation, `mutate` would eventually draw `"discipline"` to perturb and hit
        `_perturb_rules_trait`'s unknown-trait guard, and any child would reach `card_for` with no shape
        to render -- so the completed run's elites would stop breeding at this change."""
        rng = random.Random(3)
        child = _legacy_rules_genome()
        for generation in range(40):
            child = mutate(child, rng, generation=1900 + generation)
            assert "discipline" not in child.traits
            assert child.traits["rule_shape"] in RULE_SHAPES
            assert len(child.traits) == MAX_FREE_PARAMETERS
            assert isinstance(card_for(child), StrategyCard)

    def test_crossing_a_legacy_parent_with_a_modern_one_works(self) -> None:
        rng = random.Random(6)
        modern = random_genome(rng, generation=1, purpose=Purpose.TRADING, shape="rules")
        for _ in range(20):
            child = crossover(_legacy_rules_genome(), modern, rng, generation=2)
            assert set(child.traits) == set(modern.traits)
            assert isinstance(card_for(child), StrategyCard)


class TestPeriodBoundsHoldUnderMutation:
    def test_a_long_mutation_chain_never_leaves_the_declared_bands(self) -> None:
        """`app.rules.grammar` does not range-check indicator parameters -- `sma(600)` parses -- so an
        unbounded upward random walk on these three used to be able to emit a rule that only failed
        later, at evaluation time, as a whole card lost inside a scoring run."""
        rng = random.Random(77)
        child = random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="rules")
        for generation in range(500):
            child = mutate(child, rng, generation=generation + 1)
            fast = int(child.traits["fast"])
            slow = int(child.traits["slow"])
            regime_ma = int(child.traits["regime_ma"])
            assert fast < slow < regime_ma, child.traits
            for key, value in (("fast", fast), ("slow", slow), ("regime_ma", regime_ma)):
                low, high = RULES_PERIOD_BOUNDS[key]
                assert low <= value <= high, (key, value, child.traits)
            assert isinstance(card_for(child), StrategyCard)

    def test_card_for_refuses_a_period_past_its_bound(self) -> None:
        genome = _legacy_rules_genome(regime_ma=400)
        with pytest.raises(ProposalRejected, match="regime_ma=400 is outside"):
            card_for(genome)


# ---------------------------------------------------------------------------
# (g) mutate never crosses the purpose boundary; (h) traits stay within the 10-parameter budget
# ---------------------------------------------------------------------------


class TestMutate:
    @pytest.mark.parametrize("purpose", [Purpose.TRADING, Purpose.ROTH])
    @pytest.mark.parametrize("shape", ["rules", "allocation"])
    def test_mutate_never_crosses_the_purpose_boundary(self, purpose: Purpose, shape: str) -> None:
        pool_symbols = set(pool_for(purpose).all_symbols())
        rng = random.Random(11)
        parent = random_genome(rng, generation=0, purpose=purpose, shape=shape)
        for _ in range(50):
            child = mutate(parent, rng, generation=1)
            assert child.purpose is purpose
            assert set(child.universe) <= pool_symbols, set(child.universe) - pool_symbols
            parent = child

    def test_mutate_touches_at_most_three_traits(self) -> None:
        rng = random.Random(23)
        parent = random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="rules")
        for _ in range(30):
            child = mutate(parent, rng, generation=1)
            changed = sum(
                1 for key in parent.traits if parent.traits.get(key) != child.traits.get(key)
            )
            assert 0 <= changed <= 3, (parent.traits, child.traits)


class TestTraitBudget:
    @pytest.mark.parametrize("shape", ["rules", "allocation"])
    def test_random_genome_traits_stay_within_budget(self, shape: str) -> None:
        for seed in range(10):
            genome = random_genome(random.Random(seed), generation=0, purpose=Purpose.ROTH, shape=shape)
            assert len(genome.traits) <= MAX_FREE_PARAMETERS

    def test_rules_shape_uses_exactly_the_ten_key_budget(self) -> None:
        genome = random_genome(random.Random(1), generation=0, purpose=Purpose.TRADING, shape="rules")
        assert len(genome.traits) == MAX_FREE_PARAMETERS
        assert set(genome.traits) == {
            "fast", "slow", "regime_ma", "stop_loss_pct", "take_profit_pct",
            "max_hold_days", "max_positions", "position_pct", "rank_key", "rule_shape",
        }

    def test_allocation_shape_uses_exactly_three_keys(self) -> None:
        genome = random_genome(random.Random(1), generation=0, purpose=Purpose.TRADING, shape="allocation")
        assert set(genome.traits) == {"weights", "band_pct", "tilt"}

    @pytest.mark.parametrize("shape", ["rules", "allocation"])
    def test_mutate_and_crossover_stay_within_budget(self, shape: str) -> None:
        rng = random.Random(55)
        a = random_genome(rng, generation=0, purpose=Purpose.ROTH, shape=shape)
        b = random_genome(rng, generation=0, purpose=Purpose.ROTH, shape=shape)
        m = mutate(a, rng, generation=1)
        c = crossover(a, b, rng, generation=1)
        assert len(m.traits) <= MAX_FREE_PARAMETERS
        assert len(c.traits) <= MAX_FREE_PARAMETERS


class TestCrossover:
    def test_crossover_rejects_mismatched_purposes(self) -> None:
        rng = random.Random(3)
        a = random_genome(rng, generation=0, purpose=Purpose.ROTH, shape="rules")
        b = random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="rules")
        with pytest.raises(ProposalRejected):
            crossover(a, b, rng, generation=1)

    def test_crossover_rejects_mismatched_shapes(self) -> None:
        rng = random.Random(4)
        a = random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="rules")
        b = random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="allocation")
        with pytest.raises(ProposalRejected):
            crossover(a, b, rng, generation=1)

    def test_crossover_names_both_parents(self) -> None:
        rng = random.Random(6)
        a = random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="rules")
        b = random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="rules")
        child = crossover(a, b, rng, generation=1)
        assert child.parents == (a.genome_id, b.genome_id)
        assert child.origin == "crossover"


# ---------------------------------------------------------------------------
# (i) write_cards round-trips through StrategyCard.model_validate_json / AllocationCard
# ---------------------------------------------------------------------------


class TestWriteCards:
    def _isolated_settings(self, tmp_path) -> Settings:
        return Settings(
            repo_root=tmp_path,
            data_dir=tmp_path / "data",
            store_dir=tmp_path / "store",
            cache_dir=tmp_path / "cache",
            library_dir=tmp_path / "library",
        )

    def test_write_cards_round_trips_both_shapes(self, tmp_path) -> None:
        settings = self._isolated_settings(tmp_path)
        rng = random.Random(31)
        genomes = [
            random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="rules"),
            random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="allocation"),
        ]
        paths = write_cards(genomes, settings=settings)
        assert set(paths) == {g.genome_id for g in genomes}

        for genome, path in zip(genomes, [paths[g.genome_id] for g in genomes], strict=True):
            assert path.exists()
            text = path.read_text(encoding="utf-8")
            assert text.endswith("\n")
            if genome.shape == "rules":
                reloaded = StrategyCard.model_validate_json(text)
            else:
                reloaded = AllocationCard.model_validate_json(text)
            assert reloaded.agent_id == genome.genome_id

    def test_write_cards_also_writes_the_genome_for_traceability(self, tmp_path) -> None:
        from app.evolution.models import loop_root

        settings = self._isolated_settings(tmp_path)
        genome = random_genome(random.Random(2), generation=0, purpose=Purpose.TRADING, shape="rules")
        write_cards([genome], settings=settings)

        genome_path = loop_root(settings) / "genomes" / f"{genome.genome_id}.json"
        assert genome_path.exists()
        reloaded = Genome.model_validate_json(genome_path.read_text(encoding="utf-8"))
        assert reloaded == genome

    def test_write_cards_is_a_no_op_overwrite_for_an_incumbent(self, tmp_path) -> None:
        """An incumbent genome carried forward by `propose_generation` has already been written in an
        earlier generation. `write_cards` must not raise when handed it again."""
        settings = self._isolated_settings(tmp_path)
        genome = random_genome(random.Random(9), generation=0, purpose=Purpose.TRADING, shape="allocation")
        first = write_cards([genome], settings=settings)
        second = write_cards([genome], settings=settings)
        assert first[genome.genome_id] == second[genome.genome_id]
        assert first[genome.genome_id].read_text(encoding="utf-8") == second[genome.genome_id].read_text(
            encoding="utf-8"
        )

    def test_write_cards_writes_under_data_loop_generated_not_library_dir(self, tmp_path) -> None:
        """The path-layering regression guard for the container failure this move was made to fix:
        1,644 of 1,673 real generations failed with `OSError: [Errno 30] Read-only file system`
        because `generated/` used to sit under `library_dir` (inside the read-only image layer, since
        `docker-compose.yml` bind-mounts only `./data`). `write_cards` must land its cards under
        `settings.data_dir / "loop" / "generated"` -- exactly `generated_tier_dir(settings)` -- and
        nowhere under `settings.library_dir`, which is a different, independently-configured directory
        in this test (see `_isolated_settings`).
        """
        settings = self._isolated_settings(tmp_path)
        genome = random_genome(random.Random(5), generation=0, purpose=Purpose.TRADING, shape="rules")
        paths = write_cards([genome], settings=settings)
        card_path = paths[genome.genome_id]

        expected_dir = settings.data_dir / "loop" / "generated"
        assert card_path.parent == expected_dir
        assert card_path.parent == generated_tier_dir(settings)
        assert not card_path.is_relative_to(settings.library_dir)


# ---------------------------------------------------------------------------
# (b) a card write_cards writes under the new location is still addressable by
# app.tournament.jobs._load_library_index -- the whole point of the move: a card proposed by the loop
# must stay resolvable by `agent_id` from `POST /api/competition/jobs`, even though it no longer sits
# under `library_dir`.
# ---------------------------------------------------------------------------


class TestJobsIndexFindsWrittenCards:
    def _isolated_settings(self, tmp_path) -> Settings:
        return Settings(
            repo_root=tmp_path,
            data_dir=tmp_path / "data",
            store_dir=tmp_path / "store",
            cache_dir=tmp_path / "cache",
            library_dir=tmp_path / "library",
        )

    def test_load_library_index_finds_a_card_written_by_write_cards(self, tmp_path, monkeypatch) -> None:
        settings = self._isolated_settings(tmp_path)
        monkeypatch.setattr(jobs, "get_settings", lambda: settings)

        genome = random_genome(random.Random(13), generation=0, purpose=Purpose.TRADING, shape="rules")
        card = card_for(genome)
        write_cards([genome], settings=settings)

        index = jobs._load_library_index()
        assert genome.genome_id in index
        tier, resolved_card = index[genome.genome_id]
        assert tier == "generated"
        assert resolved_card.agent_id == card.agent_id

    def test_resolve_cards_by_agent_id_finds_a_generated_card(self, tmp_path, monkeypatch) -> None:
        """The end-to-end resolution path `POST /api/competition/jobs` actually uses: naming a
        generated card's `agent_id` in the request's `cards` list."""
        settings = self._isolated_settings(tmp_path)
        monkeypatch.setattr(jobs, "get_settings", lambda: settings)

        genome = random_genome(random.Random(14), generation=0, purpose=Purpose.TRADING, shape="rules")
        write_cards([genome], settings=settings)

        resolved = jobs._resolve_cards([genome.genome_id], "base")
        assert len(resolved) == 1
        assert resolved[0].agent_id == genome.genome_id


# ---------------------------------------------------------------------------
# propose_generation: Roth safety gate, and incumbent carry-forward
# ---------------------------------------------------------------------------


class TestProposeGeneration:
    def test_roth_generation_does_not_violate_disjointness(self) -> None:
        config = LoopConfig(population=6)
        genomes = propose_generation(
            generation=0, purpose=Purpose.ROTH, config=config, rng=random.Random(123)
        )
        assert len(genomes) == 6
        assert all(g.purpose is Purpose.ROTH for g in genomes)
        assert all(g.generation == 0 for g in genomes)

        cards = [card_for(g) for g in genomes]
        library = load_library()
        other_cards = [card for tier_cards in library.values() for card in tier_cards]
        violations = find_disjointness_violations((*cards, *other_cards))
        assert violations == (), [v.message for v in violations]

    @pytest.mark.parametrize("shape", ["rules", "allocation"])
    def test_generation_is_shape_homogeneous(self, shape: str) -> None:
        """The defect this module used to have: a generation that alternated `"rules"` and
        `"allocation"` shape scored on two different exposure bases, and
        `app.tournament.results.build_leaderboard` ranked only the larger group -- silently excluding
        the other shape's candidates from `rows` after they had already burned a full pass over every
        window. `propose_generation` must now return a population that is entirely one shape.
        """
        config = LoopConfig(population=6)
        genomes = propose_generation(
            generation=0, purpose=Purpose.TRADING, config=config, rng=random.Random(2), shape=shape
        )
        assert len(genomes) == 6
        assert all(g.shape == shape for g in genomes), {g.shape for g in genomes}

    def test_elite_of_wrong_shape_is_silently_dropped_not_carried_forward(self) -> None:
        """A caller cycling `shape` per generation legitimately holds elites of both shapes in one
        list (one lineage per shape) -- `propose_generation` must filter out the non-matching ones
        rather than raising, and must not let them reappear in its output (that would reintroduce the
        exact mixed-shape defect this parameter exists to prevent).
        """
        rng = random.Random(70)
        rules_elite = random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="rules")
        alloc_elite = random_genome(rng, generation=0, purpose=Purpose.TRADING, shape="allocation")
        config = LoopConfig(population=4)

        genomes = propose_generation(
            generation=1,
            purpose=Purpose.TRADING,
            config=config,
            rng=random.Random(71),
            shape="allocation",
            elites=(rules_elite, alloc_elite),
        )
        genome_ids = {g.genome_id for g in genomes}
        assert rules_elite.genome_id not in genome_ids
        assert all(g.shape == "allocation" for g in genomes), {g.shape for g in genomes}

    def test_elite_of_matching_shape_is_carried_forward_unchanged(self) -> None:
        """The right-shape counterpart of the test above: an elite whose shape matches the requested
        generation must still reappear with its original `genome_id` and `generation` -- the
        shape filter must not collaterally break the existing incumbent-carry-forward contract.
        """
        config = LoopConfig(population=6)
        gen0 = propose_generation(
            generation=0,
            purpose=Purpose.TRADING,
            config=config,
            rng=random.Random(80),
            shape="allocation",
        )
        elite = gen0[0]

        gen1 = propose_generation(
            generation=1,
            purpose=Purpose.TRADING,
            config=config,
            rng=random.Random(81),
            shape="allocation",
            elites=(elite,),
        )
        gen1_by_id = {g.genome_id: g for g in gen1}
        assert elite.genome_id in gen1_by_id
        assert gen1_by_id[elite.genome_id] == elite
        assert gen1_by_id[elite.genome_id].generation == 0

    def test_new_candidate_still_proposed_when_allocation_elites_nearly_fill_population(self) -> None:
        """Requirement 4 (at least one new candidate per generation) must keep holding once elites are
        filtered by shape -- exercised here against `"allocation"`, not just the `"rules"` default.
        """
        config = LoopConfig(population=3, elite_count=3)
        rng = random.Random(90)
        gen0 = propose_generation(
            generation=0, purpose=Purpose.TRADING, config=config, rng=rng, shape="allocation"
        )
        assert len(gen0) == 3
        gen1 = propose_generation(
            generation=1,
            purpose=Purpose.TRADING,
            config=config,
            rng=random.Random(91),
            shape="allocation",
            elites=gen0,
        )
        assert any(g.generation == 1 for g in gen1), "no room was left for a new candidate"
        assert all(g.shape == "allocation" for g in gen1), {g.shape for g in gen1}

    def test_deduplicates_by_genome_id(self) -> None:
        config = LoopConfig(population=6)
        genomes = propose_generation(
            generation=0, purpose=Purpose.TRADING, config=config, rng=random.Random(2)
        )
        assert len(genomes) == len({g.genome_id for g in genomes})

    def test_elite_purpose_mismatch_is_rejected(self) -> None:
        rng = random.Random(8)
        elite = random_genome(rng, generation=0, purpose=Purpose.ROTH, shape="rules")
        config = LoopConfig(population=4)
        with pytest.raises(ProposalRejected):
            propose_generation(
                generation=1, purpose=Purpose.TRADING, config=config, rng=rng, elites=(elite,)
            )

    def test_incumbents_carry_forward_with_unchanged_genome_id_and_generation(self) -> None:
        """The manager's promotion-path correction: an elite handed in as `elites` must reappear in
        the output with its *original* `genome_id` and `generation`, not re-minted at the current
        generation -- otherwise `app.evolution.promotion`'s "same genome_id twice" gate could never
        fire, because a bred/random offspring always carries a fresh id.
        """
        config = LoopConfig(population=6)
        gen0 = propose_generation(
            generation=0, purpose=Purpose.TRADING, config=config, rng=random.Random(41)
        )
        elites = gen0[:2]
        elite_ids = {e.genome_id: e.generation for e in elites}

        gen1 = propose_generation(
            generation=1, purpose=Purpose.TRADING, config=config, rng=random.Random(42), elites=elites
        )
        gen1_by_id = {g.genome_id: g for g in gen1}

        for genome_id, original_generation in elite_ids.items():
            assert genome_id in gen1_by_id, f"incumbent {genome_id} missing from next generation"
            assert gen1_by_id[genome_id].generation == original_generation
            assert gen1_by_id[genome_id] == elites[[e.genome_id for e in elites].index(genome_id)]

        # At least one genome in gen1 must be new work, not a re-run incumbent.
        assert any(g.generation == 1 for g in gen1)

    def test_incumbents_leave_room_for_at_least_one_new_candidate(self) -> None:
        """Even if `elites` alone would fill the whole population, at least one slot must go to new
        work -- a generation that is nothing but re-run incumbents is a re-measurement, not a search.
        """
        config = LoopConfig(population=3, elite_count=3)
        rng = random.Random(50)
        gen0 = propose_generation(generation=0, purpose=Purpose.TRADING, config=config, rng=rng)
        assert len(gen0) == 3
        gen1 = propose_generation(
            generation=1, purpose=Purpose.TRADING, config=config, rng=random.Random(51), elites=gen0
        )
        assert any(g.generation == 1 for g in gen1), "no room was left for a new candidate"

    def test_write_cards_accepts_a_generation_with_carried_forward_incumbents(self, tmp_path) -> None:
        settings = Settings(
            repo_root=tmp_path,
            data_dir=tmp_path / "data",
            store_dir=tmp_path / "store",
            cache_dir=tmp_path / "cache",
            library_dir=tmp_path / "library",
        )
        config = LoopConfig(population=4)
        gen0 = propose_generation(generation=0, purpose=Purpose.TRADING, config=config, rng=random.Random(60))
        write_cards(gen0, settings=settings)
        gen1 = propose_generation(
            generation=1, purpose=Purpose.TRADING, config=config, rng=random.Random(61), elites=gen0[:1]
        )
        # Must not raise even though gen1 contains a genome already written in generation 0.
        paths = write_cards(gen1, settings=settings)
        assert len(paths) == len(gen1)


# ---------------------------------------------------------------------------
# Rediscovery is the same candidate, not a new one
# ---------------------------------------------------------------------------


class TestRediscoveryIsNotReMinted:
    """`genome_id_for` hashes only the content and puts the generation in the *prefix*, so a draw
    that lands on traits already tried arrives with a brand-new id and an identical digest.

    Left alone that card becomes two candidates, and `genome_id_for`'s own docstring says why this
    is load-bearing: `app.evolution.promotion` accumulates evidence by matching `genome_id` across
    generations, so a re-minted card reads as two that each cleared the gate once, and "twice on
    differing window sets" gets *harder* the longer the loop runs. The ledger's multiple-comparison
    denominator counts it twice as well, correcting against hypotheses nobody newly proposed.

    Measured on this repo's own loop before the fix: **47 of 1,701 distinct card contents had been
    minted under more than one id**, three under three ids, and three pairs reached the paper-desk
    approval queue as separately approvable rows carrying identical statistics.
    """

    @staticmethod
    def _seen_from(genomes) -> dict:
        return {content_digest(g.genome_id): g for g in genomes}

    def test_a_rediscovered_draw_takes_the_original_id_and_generation(self) -> None:
        first = propose_generation(
            generation=3,
            purpose=Purpose.TRADING,
            config=LoopConfig(population=4, seed=11),
            rng=random.Random(11),
        )
        seen = self._seen_from(first)

        # Same seed, later generation: every draw reproduces generation 3's content exactly.
        again = propose_generation(
            generation=15,
            purpose=Purpose.TRADING,
            config=LoopConfig(population=4, seed=11),
            rng=random.Random(11),
            seen=seen,
        )

        assert [g.genome_id for g in again] == [g.genome_id for g in first]
        assert all(g.generation == 3 for g in again), (
            "a rediscovery is another measurement of the candidate born in generation 3"
        )

    def test_without_the_index_the_same_content_mints_a_second_id(self) -> None:
        """The defect, pinned. Same call, no `seen` -- every id changes while every digest does not,
        which is exactly the shape that made one card look like two."""
        first = propose_generation(
            generation=3,
            purpose=Purpose.TRADING,
            config=LoopConfig(population=4, seed=11),
            rng=random.Random(11),
        )
        again = propose_generation(
            generation=15,
            purpose=Purpose.TRADING,
            config=LoopConfig(population=4, seed=11),
            rng=random.Random(11),
        )

        assert [g.genome_id for g in again] != [g.genome_id for g in first]
        assert [content_digest(g.genome_id) for g in again] == [
            content_digest(g.genome_id) for g in first
        ]

    def test_a_genuinely_new_draw_is_untouched_by_the_index(self) -> None:
        seen = self._seen_from(
            propose_generation(
                generation=3,
                purpose=Purpose.TRADING,
                config=LoopConfig(population=4, seed=11),
                rng=random.Random(11),
            )
        )

        fresh = propose_generation(
            generation=15,
            purpose=Purpose.TRADING,
            config=LoopConfig(population=4, seed=999),
            rng=random.Random(999),
            seen=seen,
        )

        assert all(g.generation == 15 for g in fresh)

    def test_the_slate_still_holds_population_distinct_cards(self) -> None:
        """Substituting must not collapse the generation: `accepted` is keyed on the *resolved* id,
        so a slate rediscovering several old cards still holds one row each."""
        seen = self._seen_from(
            propose_generation(
                generation=3,
                purpose=Purpose.TRADING,
                config=LoopConfig(population=6, seed=11),
                rng=random.Random(11),
            )
        )

        again = propose_generation(
            generation=15,
            purpose=Purpose.TRADING,
            config=LoopConfig(population=6, seed=11),
            rng=random.Random(11),
            seen=seen,
        )

        assert len(again) == 6
        assert len({g.genome_id for g in again}) == 6


class TestLoadSeenGenomes:
    def test_indexes_what_write_cards_wrote(self, settings: Settings) -> None:
        genomes = propose_generation(
            generation=3,
            purpose=Purpose.TRADING,
            config=LoopConfig(population=3, seed=11),
            rng=random.Random(11),
        )
        write_cards(genomes, settings=settings)

        seen = load_seen_genomes(settings)

        assert len(seen) == 3
        for genome in genomes:
            assert seen[content_digest(genome.genome_id)].genome_id == genome.genome_id

    def test_the_earliest_generation_wins_a_digest(self, settings: Settings) -> None:
        """The id a candidate was born under is what every ledger entry, promotion record and seat
        request already refers to; electing a later mint as canonical would orphan all of them."""
        early = propose_generation(
            generation=3,
            purpose=Purpose.TRADING,
            config=LoopConfig(population=2, seed=11),
            rng=random.Random(11),
        )
        late = propose_generation(
            generation=15,
            purpose=Purpose.TRADING,
            config=LoopConfig(population=2, seed=11),
            rng=random.Random(11),
        )
        # Written newest-first on purpose, so a filesystem-order bug picks the wrong one.
        write_cards(late, settings=settings)
        write_cards(early, settings=settings)

        seen = load_seen_genomes(settings)

        for genome in early:
            assert seen[content_digest(genome.genome_id)].generation == 3

    def test_an_absent_directory_is_an_empty_index_not_an_error(self, settings: Settings) -> None:
        assert len(load_seen_genomes(settings)) == 0

    def test_a_malformed_genome_file_is_a_miss_not_a_crash(self, settings: Settings) -> None:
        genomes = propose_generation(
            generation=3,
            purpose=Purpose.TRADING,
            config=LoopConfig(population=2, seed=11),
            rng=random.Random(11),
        )
        write_cards(genomes, settings=settings)
        digest = content_digest(genomes[0].genome_id)
        (loop_root(settings) / "genomes" / f"{genomes[0].genome_id}.json").write_text(
            "{not json", encoding="utf-8"
        )

        seen = load_seen_genomes(settings)

        assert seen.get(digest) is None, "a bad historical file must not take the generation down"

    def test_a_stray_file_is_ignored(self, settings: Settings) -> None:
        genomes_dir = loop_root(settings) / "genomes"
        genomes_dir.mkdir(parents=True, exist_ok=True)
        (genomes_dir / "notes.json").write_text("{}", encoding="utf-8")

        assert len(load_seen_genomes(settings)) == 0
