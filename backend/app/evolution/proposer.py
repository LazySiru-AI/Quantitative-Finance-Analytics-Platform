"""`Genome` -> a real, validating `StrategyCard`/`AllocationCard` on disk, and the generation-level
composition that decides which genomes to build in the first place.

**Why card construction lives behind `ProposalRejected` rather than an assertion.** `genome.py`'s
operators already produce internally-consistent traits (`fast < slow < regime_ma`, weights summing to
exactly one, `position_pct * max_positions <= 1`), but a genome can still reach this module having come
from anywhere -- reloaded off disk, handed in by a caller this package does not control, mutated by a
future edit to `genome.py` that gets one of those invariants wrong. `card_for` re-derives and re-checks
every constraint the card models themselves enforce, and wraps every remaining `ValueError` a card
constructor or `app.rules.grammar.parse`/`parse_ranking` can raise into `ProposalRejected`, so a bad
genome is refused rather than silently repaired -- exactly the contract `ProposalRejected`'s own
docstring in `app.evolution.models` states.

**What a `"rules"` card's entry and exit are now, and were not.** `_rules_card` used to compose both
from one hardcoded f-string, so every card this module has ever written is the same
`close > sma(regime_ma) and ema(fast) crosses_above ema(slow)` template with different numbers in it --
231 generations and 2,374 evaluations of a search that could not, in principle, propose a mean-reversion
or breakout candidate (`docs/research/loop/01-what-the-search-found.md`). The rule text now comes from
`app.evolution.ruleforms.render`, keyed by the genome's own `rule_shape` trait, and the *same*
`grammar.parse` call validates it -- widening what the search can say without widening what this module
is willing to write to disk unchecked.

**Why `discipline` is computed here and never read off the genome.** It used to be a trait, drawn with
`rng.choice(list(Discipline))`, free to mutate on its own, and passed straight through to
`StrategyCard(discipline=...)` as though it described the card. It did not: 15 of the completed run's
mutations changed nothing but that label, and two pairs among the 25 outstanding seat requests are
byte-identical cards wearing different disciplines. `_rules_card` now derives it with
`ruleforms.classify` from the rule text it just emitted, so the label is a function of the strategy
rather than an independent draw beside it -- and a shape the classifier cannot recognise is a
`ProposalRejected`, not a card with an invented category. `app.evolution.dossier` is unchanged and still
treats a card's stored `discipline` as unverified, correctly: the cards already on disk were written
under the old rule, and this module cannot retroactively make their labels true.

**Why `"allocation"`-shape cards never carry `rules`.** A `Genome`'s `traits` budget for that shape is
three keys -- `weights`, `band_pct`, `tilt` -- and `tilt` is a label (`genome._TILT_VOCAB`), not a
serialised `TiltRule`. Building an actual conditional reallocation would need a `condition`,
`on_symbol`, `from_symbol`, `to_symbol` and `shift_pct` on top of the three keys already spent, which
either blows the ten-parameter budget or steals room from `weights` itself. Every allocation card this
module proposes is therefore constant-weight and band-rebalanced only; `tilt` still earns its keep by
shaping the card's `thesis` text, so a reader can see what flavour of candidate this was meant to be
even though the mechanism itself does not yet act on it.

**Why the Roth safety check runs inside `propose_generation`, not `card_for` or `write_cards`.**
`app.tournament.purposes.find_disjointness_violations` needs the *whole* set of cards a Roth candidate
might collide with -- every taxable-purpose card already in the library, not just the other candidates
in this generation -- so it can only run once a generation's cards all exist. Checking per-card would
either miss a collision against the existing library (checking only within the generation) or re-load
the library once per candidate (checking each card in isolation), and `propose_generation` is the one
call site that already has every candidate in hand at once.

**Why a generation is shape-homogeneous.** `propose_generation` used to alternate `"rules"` and
`"allocation"` shape *within* one generation's offspring/random fill. That reads as reasonable --
"a generation should explore both shapes" -- and is exactly why it stayed unnoticed: nothing in this
module or in `app.evolution.execute.run_generation` errors on a mixed-shape population.
`app.tournament.results.build_leaderboard` is where it actually breaks, and it breaks silently. A
`"rules"` card scores on the `"entry-notional"` exposure basis; an `"allocation"` card scores on
`"invested-value"`. Per that function's own docstring (decision 1, on `_agent_exposure_basis`):
"`"entry-notional"` and `"invested-value"` are not the same field ... a single ranked column blending
both would present two different orderings as though they were one," so it "ranks only the larger
group -- ties broken toward `"entry-notional"`" and reports the smaller group's agent ids in
`unscored_reason` -- excluded from the table, not merely down-ranked. A population of 4 that comes
back 2 `"rules"` + 2 `"allocation"` therefore burns a full pass over every window for all 4 candidates,
and then only the 2 `"rules"` candidates are ever ranked, ever eligible as elites, ever promoted --
`"allocation"` is the only shape that can express a blended sleeve portfolio, so mixing shapes made
half the search space dead on arrival, not merely disadvantaged. `propose_generation` now takes an
explicit `shape` and returns a population where every genome -- incumbents included -- carries that
one shape; a caller that wants to search both shapes cycles `shape` across generations (keeping
separate elite lineages per shape) rather than asking this function to blend them in one call.
"""

from __future__ import annotations

import logging
import random
import re
from collections.abc import Iterator, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from pydantic import ValidationError

from app.config import Settings
from app.evolution import ruleforms
from app.evolution.genome import crossover, mutate, random_genome
from app.evolution.models import (
    LEGACY_RULE_SHAPE,
    RULE_SHAPES,
    RULES_PERIOD_BOUNDS,
    CardShape,
    Genome,
    LoopConfig,
    ProposalRejected,
    RuleShape,
    content_digest,
    generated_tier_dir,
    genome_id_for,
    loop_root,
)
from app.evolution.universe import pool_for
from app.rules import grammar
from app.tournament.allocation import AllocationCard, Sleeve
from app.tournament.models import DESIGN_THROUGH, StrategyCard
from app.tournament.purposes import Purpose, find_disjointness_violations
from app.tournament.results import load_library

logger = logging.getLogger(__name__)

__all__ = ["card_for", "load_seen_genomes", "propose_generation", "write_cards"]

#: `Genome.universe`'s own cap (`app.evolution.models.Genome.universe`'s `Field(max_length=12)`),
#: restated here rather than imported so `_validate_focus_avoid` can check a config-level fact (the
#: focus list alone is too long to ever fit) before a single genome is drawn -- a literal copied from
#: a `Field` constraint the same way `app.evolution.universe`'s own `MIN_WARMUP_BARS` docstring notes
#: doing for a different constant.
_MAX_UNIVERSE_SIZE = 12

_CENT = Decimal("0.01")


def _cents(value: float | Decimal) -> Decimal:
    """`value` rounded to the nearest cent, as a `Decimal` -- the same rounding convention
    `app.evolution.genome._cents` uses for the identical reason (an `AllocationCard.sleeves`' weights
    must sum to *exactly* `Decimal(1)`, never merely close). Duplicated rather than imported: that
    helper is private to `genome.py`, which this change does not touch, and two lines of `Decimal`
    quantisation cost nothing to restate -- the same call `app.tournament.allocation._money` makes for
    its own, unrelated reason."""
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Display text -- shared by both card shapes
# ---------------------------------------------------------------------------


def _flavor(genome: Genome) -> str:
    """A short, leaderboard-readable tag for what kind of candidate this is -- the rule shape for a
    `"rules"` genome, or the sleeve mix (plus tilt, if any) for an `"allocation"` one.

    The rule shape, not the discipline, and the difference is the whole point of this change: a shape
    name (`"rsi-pullback"`, `"channel-breakout"`) names the rule the card actually emits, where the
    `discipline` label this used to read was drawn at random and could describe anything. A genome from
    before the trait existed reads as `LEGACY_RULE_SHAPE`, which is what it emitted."""
    if genome.shape == "rules":
        return str(genome.traits.get("rule_shape", LEGACY_RULE_SHAPE))
    tilt = genome.traits.get("tilt")
    return f"growth+stability+{tilt}" if tilt else "growth+stability"


def _display_name(genome: Genome) -> str:
    """`"auto g007 · trend+stability (roth)"` -- the generation-prefixed genome id, the flavour, and
    the purpose, in that order, so a leaderboard row is identifiable without opening the card."""
    short_id = genome.genome_id.split("-", 1)[0]
    return f"auto {short_id} · {_flavor(genome)} ({genome.purpose.value})"


# ---------------------------------------------------------------------------
# "rules" shape
# ---------------------------------------------------------------------------


def _rule_shape(genome: Genome) -> RuleShape:
    """`genome`'s `rule_shape` trait, checked against the declared vocabulary.

    A genome can reach `card_for` from anywhere -- reloaded off disk, handed in by a caller this package
    does not control -- which is the same reason this module re-derives every other constraint rather than
    trusting `genome.py` to have held it (see the module docstring). A missing key is the one case that is
    *not* a defect: every `"rules"` genome the completed run wrote predates this trait and emitted
    `LEGACY_RULE_SHAPE`, so reading it as that is a fact about those genomes, not a repair. A key that is
    present but names a shape no renderer knows is a genuine defect, and raises `ValueError` for
    `_rules_card`'s own `except` clause to turn into `ProposalRejected`.
    """
    raw = genome.traits.get("rule_shape", LEGACY_RULE_SHAPE)
    for shape in RULE_SHAPES:
        if raw == shape:
            return shape
    raise ValueError(f"rule_shape={raw!r} is not one of {list(RULE_SHAPES)}")


def _rules_thesis(
    genome: Genome,
    *,
    shape: RuleShape,
    fast: int,
    slow: int,
    regime_ma: int,
    stop_loss_pct: Decimal,
    take_profit_pct: Decimal | None,
    max_hold_days: int,
) -> str:
    """The card's `thesis`, describing the rule this genome actually emits.

    `app.evolution.ruleforms.describe` supplies the clause naming the form, so the thesis moves with the
    `rule_shape` trait rather than describing an EMA crossover regardless of what was written. That
    matters beyond tidiness: `StrategyCard.thesis`' own docstring calls the rationale the only thing
    separating a hypothesis from a curve fit after the fact, and a thesis describing a different strategy
    than the card runs is worse than none -- it is the same defect as the `discipline` label, one field
    over.
    """
    target_clause = f", a {take_profit_pct:.0%} target" if take_profit_pct is not None else ""
    form = ruleforms.describe(shape, fast=fast, slow=slow, regime_ma=regime_ma)
    return (
        "Machine-proposed candidate (app.evolution). "
        f"Tests {form} on {', '.join(genome.universe)}, with a {stop_loss_pct:.0%} "
        f"stop{target_clause} and a {max_hold_days}-session time stop. Never scored before being "
        f"written -- this is falsified if the {shape} signal fails to beat this purpose's benchmark by "
        "more than the measured ordering-noise floor, across whatever windows it is actually run "
        "against."
    )


def _rules_card(genome: Genome) -> StrategyCard:
    traits = genome.traits
    try:
        fast = int(traits["fast"])
        slow = int(traits["slow"])
        regime_ma = int(traits["regime_ma"])
        max_hold_days = int(traits["max_hold_days"])
        max_positions = int(traits["max_positions"])
        stop_loss_pct = Decimal(str(traits["stop_loss_pct"]))
        position_pct = Decimal(str(traits["position_pct"]))
        take_profit_raw = traits.get("take_profit_pct")
        take_profit_pct = Decimal(str(take_profit_raw)) if take_profit_raw is not None else None
        rank_key = traits.get("rank_key")
        shape = _rule_shape(genome)
    except (KeyError, TypeError, ValueError) as exc:
        raise ProposalRejected(genome.genome_id, f"malformed 'rules' traits: {exc}") from exc

    if not (fast < slow < regime_ma):
        raise ProposalRejected(
            genome.genome_id, f"fast={fast}, slow={slow}, regime_ma={regime_ma} does not satisfy fast < slow < regime_ma"
        )
    for key, value in (("fast", fast), ("slow", slow), ("regime_ma", regime_ma)):
        low, high = RULES_PERIOD_BOUNDS[key]
        if not (low <= value <= high):
            raise ProposalRejected(
                genome.genome_id,
                f"{key}={value} is outside the {low}-{high} band every rule shape is rendered within",
            )

    entry, exit_rule = ruleforms.render(shape, fast=fast, slow=slow, regime_ma=regime_ma)
    try:
        grammar.parse(entry)
        grammar.parse(exit_rule)
        if rank_key is not None:
            grammar.parse_ranking(rank_key)
    except grammar.RuleSyntaxError as exc:
        raise ProposalRejected(genome.genome_id, f"emitted rule text failed to parse: {exc}") from exc

    discipline = ruleforms.classify(entry, exit_rule)
    if discipline is None:
        raise ProposalRejected(
            genome.genome_id,
            f"rule shape {shape!r} emitted {entry!r}, which app.evolution.ruleforms.classify does not "
            "recognise -- a renderer and the classifier have drifted apart, and a card would otherwise "
            "carry a label describing nothing",
        )

    thesis = _rules_thesis(
        genome,
        shape=shape,
        fast=fast,
        slow=slow,
        regime_ma=regime_ma,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        max_hold_days=max_hold_days,
    )

    try:
        return StrategyCard(
            agent_id=genome.genome_id,
            display_name=_display_name(genome),
            discipline=discipline,
            purpose=genome.purpose,
            thesis=thesis,
            universe=genome.universe,
            entry=entry,
            exit=exit_rule,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            max_hold_days=max_hold_days,
            max_positions=max_positions,
            position_pct=position_pct,
            rank_by=rank_key,
            designed_through=DESIGN_THROUGH,
        )
    except ValueError as exc:
        raise ProposalRejected(genome.genome_id, f"card failed to validate: {exc}") from exc


# ---------------------------------------------------------------------------
# "allocation" shape
# ---------------------------------------------------------------------------


def _allocation_thesis(genome: Genome, *, sleeves: tuple[Sleeve, ...], band_pct: Decimal) -> str:
    weight_desc = ", ".join(f"{sleeve.symbol} {sleeve.target_weight:.0%}" for sleeve in sleeves)
    tilt = genome.traits.get("tilt")
    tilt_clause = f" Tagged as a {tilt} tilt candidate, though no conditional reallocation fires yet." if tilt else ""
    return (
        "Machine-proposed candidate (app.evolution). "
        f"Tests a constant-weight, band-rebalanced allocation across {weight_desc}, rebalanced back "
        f"toward target whenever a sleeve drifts more than {band_pct:.0%} from it.{tilt_clause} "
        "Never scored before being written -- this is falsified if the static weighting underperforms "
        "this purpose's benchmark by more than the measured ordering-noise floor, across whatever "
        "windows it is actually run against."
    )


def _allocation_card(genome: Genome) -> AllocationCard:
    traits = genome.traits
    weights = traits.get("weights")
    if not isinstance(weights, list) or len(weights) != len(genome.universe):
        got = len(weights) if isinstance(weights, list) else type(weights).__name__
        raise ProposalRejected(
            genome.genome_id,
            f"traits['weights'] has {got} entries, universe has {len(genome.universe)} -- weights "
            "must be positional against universe",
        )

    try:
        band_pct = Decimal(str(traits["band_pct"]))
        sleeves = tuple(
            Sleeve(symbol=symbol, target_weight=Decimal(str(weight)))
            for symbol, weight in zip(genome.universe, weights, strict=True)
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProposalRejected(genome.genome_id, f"malformed 'allocation' traits: {exc}") from exc

    total = sum((sleeve.target_weight for sleeve in sleeves), Decimal(0))
    if total != Decimal(1):
        raise ProposalRejected(genome.genome_id, f"sleeve target_weight values sum to {total}, not 1")

    thesis = _allocation_thesis(genome, sleeves=sleeves, band_pct=band_pct)

    try:
        return AllocationCard(
            agent_id=genome.genome_id,
            display_name=_display_name(genome),
            purpose=genome.purpose,
            thesis=thesis,
            sleeves=sleeves,
            band_pct=band_pct,
            rules=(),
            designed_through=DESIGN_THROUGH,
        )
    except ValueError as exc:
        raise ProposalRejected(genome.genome_id, f"card failed to validate: {exc}") from exc


# ---------------------------------------------------------------------------
# focus_symbols / avoid_symbols -- the machine-readable half of LoopConfig.goal
#
# See `LoopConfig.focus_symbols`'s own docstring for the division of labour this enforces: `goal` is
# prose nothing here reads, `focus_symbols`/`avoid_symbols` are the two lists that actually constrain
# what `propose_generation` returns.
# ---------------------------------------------------------------------------


def _validate_focus_avoid(config: LoopConfig, purpose: Purpose, generation: int) -> None:
    """The three config-level defects that must fail loudly, before a single genome is drawn, rather
    than being discovered candidate-by-candidate or silently worked around.

    Raises `ProposalRejected` -- not a plain `ValueError` -- for the same reason every other refusal
    in this module does: a caller catching `ProposalRejected` around a `propose_generation` call
    already handles every way this function can say no. There is no genome yet for `ProposalRejected`
    to name (its constructor requires a `genome_id`), so a synthetic id naming the generation and
    config is used instead -- `g{generation:03d}-config` -- which still sorts and reads sensibly
    alongside real `genome_id`s in a log.

    **Order matters least here, but overlap is checked first** because a symbol in both lists is a
    self-contradictory instruction no pool membership check can rescue -- checking pool membership
    first would report a spurious "not in the pool" for a symbol that might well be in it, while
    masking the actual problem (it was also asked to be avoided).
    """
    config_id = f"g{generation:03d}-config"
    focus = set(config.focus_symbols)
    avoid = set(config.avoid_symbols)

    overlap = focus & avoid
    if overlap:
        raise ProposalRejected(
            config_id,
            f"focus_symbols and avoid_symbols both name {sorted(overlap)} -- a symbol asked for and "
            "forbidden at once is refused rather than resolved in either direction "
            "(see LoopConfig.avoid_symbols's own docstring)",
        )

    if len(config.focus_symbols) > _MAX_UNIVERSE_SIZE:
        raise ProposalRejected(
            config_id,
            f"{len(config.focus_symbols)} focus_symbols exceeds Genome.universe's "
            f"{_MAX_UNIVERSE_SIZE}-symbol cap outright -- there is no universe this could ever "
            "produce, for any purpose",
        )

    pool_symbols = set(pool_for(purpose).all_symbols())
    missing = focus - pool_symbols
    if missing:
        raise ProposalRejected(
            config_id,
            f"focus_symbols {sorted(missing)} are not in the {purpose.value!r} lane's pool "
            f"(app.evolution.universe.pool_for({purpose.value!r})) -- a candidate cannot be bred "
            "around a ticker its own purpose's pool does not contain",
        )


def _rebalanced_allocation_weights(
    old_universe: tuple[str, ...], old_weights: Sequence[float], new_universe: tuple[str, ...]
) -> list[float]:
    """`traits["weights"]`, repositioned for `new_universe` after focus/avoid enforcement changed the
    universe out from under it -- positional against `new_universe`, summing to exactly `Decimal(1)`
    (the same invariant `genome.py._draw_allocation_weights` establishes for a freshly drawn genome,
    and `AllocationCard._weights_are_a_complete_partition` refuses to construct without).

    A symbol kept in both universes keeps its old, cent-quantised weight unchanged. A symbol only
    `new_universe` now has (a focus symbol that was missing) is seeded from whatever weight the
    dropped avoid symbols freed up, split evenly across every newly added symbol -- or, if nothing was
    freed (a focus symbol added with no avoid symbol removed), a flat 5-cent seed, the same rough
    "a few percent tactical tilt" magnitude `universe.py`'s own satellite sleeve targets. Whatever cent
    of quantisation drift is left after that (there is almost always one, for the identical reason
    `genome.py._draw_allocation_weights` absorbs its own remainder into a single sleeve) is folded
    into the single largest surviving weight, chosen deterministically by `(weight, symbol)` so two
    calls over the same inputs always pick the same one.
    """
    old_map = {symbol: _cents(weight) for symbol, weight in zip(old_universe, old_weights, strict=True)}
    added = [symbol for symbol in new_universe if symbol not in old_map]
    freed = sum((weight for symbol, weight in old_map.items() if symbol not in new_universe), Decimal(0))

    weights: dict[str, Decimal] = {
        symbol: weight for symbol, weight in old_map.items() if symbol in new_universe
    }
    if added:
        share = _cents(freed / len(added)) if freed > 0 else Decimal("0.05")
        for symbol in added:
            weights[symbol] = share

    total = sum(weights.values(), Decimal(0))
    drift = Decimal("1.00") - total
    if drift != Decimal(0):
        target = max(weights, key=lambda symbol: (weights[symbol], symbol))
        adjusted = weights[target] + drift
        # Defensive only: the inputs are already within a few cents of summing to one, so `adjusted`
        # going non-positive would require a pathological `focus_symbols`/`avoid_symbols` combination
        # this function has not been able to construct in practice. Refusing outright (rather than
        # returning a card `AllocationCard` would reject anyway) keeps the failure at this call site.
        if adjusted <= 0:  # pragma: no cover -- defensive
            raise ProposalRejected(
                "focus-avoid-rebalance", f"could not rebalance weights for {new_universe} without a non-positive sleeve"
            )
        weights[target] = adjusted

    return [float(weights[symbol]) for symbol in new_universe]


def _apply_focus_avoid(genome: Genome, *, config: LoopConfig) -> Genome:
    """Force every `config.focus_symbols` ticker into `genome.universe` and strip every
    `config.avoid_symbols` ticker out of it, rebuilding whatever is positional against the universe
    (an `"allocation"`-shape genome's `traits["weights"]`) and re-deriving `genome_id` because the
    content changed -- `genome_id_for` hashes `universe`/`traits` alongside `shape`/`purpose`, so a
    genome whose universe this function touched must carry a new id or it would silently misdescribe
    its own content.

    A genome that needs no change (`focus_symbols`/`avoid_symbols` both empty, or already satisfied)
    is returned unchanged, by identity -- the common case, and specifically not a `model_copy()` that
    would otherwise mint an unnecessary new object for every single draw.

    **Trims the avoid-cleaned universe before adding missing focus symbols, never the other way
    round**, so a focus symbol is never the one sacrificed to make room for itself. Trimming never
    removes a symbol `config.focus_symbols` already named (whether or not it was already present) --
    `_validate_focus_avoid` already guarantees `len(focus_symbols) <= 12`, so removing every
    non-focus, non-kept symbol is always sufficient to make room, and this function relies on exactly
    that guarantee rather than re-deriving it.

    Can hand back a universe of fewer than one symbol (every symbol was named in `avoid_symbols` and
    `focus_symbols` is empty) or, in principle, an allocation genome whose rebalanced weights cannot be
    made to sum to one -- both surface as a `pydantic.ValidationError` / `ProposalRejected` from
    constructing the returned `Genome`/computing its weights, which `propose_generation`'s draw loop
    already retries a rejected draw against its own attempt budget, exactly as for any other rejected
    genome.
    """
    if not config.focus_symbols and not config.avoid_symbols:
        return genome

    avoid = set(config.avoid_symbols)
    focus_set = set(config.focus_symbols)
    kept = [symbol for symbol in genome.universe if symbol not in avoid]
    missing_focus = [symbol for symbol in config.focus_symbols if symbol not in kept]

    if missing_focus:
        room = _MAX_UNIVERSE_SIZE - len(kept)
        if room < len(missing_focus):
            trim_needed = min(len(missing_focus) - room, len(kept))
            trimmable = [symbol for symbol in kept if symbol not in focus_set]
            for symbol in trimmable[: min(trim_needed, len(trimmable))]:
                kept.remove(symbol)
        kept = [*kept, *missing_focus]

    new_universe = tuple(dict.fromkeys(kept))
    if new_universe == genome.universe:
        return genome

    traits = dict(genome.traits)
    if genome.shape == "allocation":
        traits["weights"] = _rebalanced_allocation_weights(
            genome.universe, genome.traits.get("weights", []), new_universe
        )

    genome_id = genome_id_for(
        generation=genome.generation,
        shape=genome.shape,
        purpose=genome.purpose,
        universe=new_universe,
        traits=traits,
    )
    return genome.model_copy(update={"universe": new_universe, "traits": traits, "genome_id": genome_id})


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def card_for(genome: Genome) -> StrategyCard | AllocationCard:
    """Build and validate the real card `genome` describes -- a `StrategyCard` for `"rules"`, an
    `AllocationCard` for `"allocation"`. Raises `ProposalRejected` rather than returning a repaired or
    partial card; see this module's own docstring for why."""
    if genome.shape == "rules":
        return _rules_card(genome)
    if genome.shape == "allocation":
        return _allocation_card(genome)
    raise ProposalRejected(genome.genome_id, f"unknown shape {genome.shape!r}")  # pragma: no cover


#: `g<generation>-<digest>` as `write_cards` spells it. Anchored so a stray file in `genomes/`
#: cannot be mistaken for a genome, and capturing both halves so the index below never has to open
#: a file to learn what is already in its name.
_GENOME_FILENAME = re.compile(r"^g(\d+)-([0-9a-f]{6,})$")


class _SeenGenomes(Mapping[str, Genome]):
    """Digest -> the genome that first carried it, reading each file only if it is actually asked for.

    **Why lazy.** `propose_generation` needs this to answer one question per draw -- "have I proposed
    this exact card before?" -- and the answer is almost always no. Eagerly validating every stored
    genome to build the index cost **19.2s over 1,818 files** on this machine, paid once per
    generation for a lookup that hits a handful of times across a whole run. The filename already
    encodes everything the *index* needs: `g<generation>-<digest>` gives the digest to key on and the
    generation that decides which mint is canonical, so building it touches no file contents at all.
    A `Genome` is parsed only on a hit, and cached.

    **First appearance wins, chosen by generation.** The id a candidate was born under is what every
    ledger entry, promotion record and seat request already refers to; electing a later mint as
    canonical would orphan all of them. Ties fall back to the smaller id so the choice is stable.

    An unreadable or malformed genome file yields a miss rather than an exception: this index makes
    the loop *more* correct, and losing a generation because one historical file went bad would be a
    far worse trade than re-minting one candidate.
    """

    def __init__(self, paths: dict[str, Path]) -> None:
        self._paths = paths
        self._cache: dict[str, Genome | None] = {}

    def __getitem__(self, digest: str) -> Genome:
        genome = self._load(digest)
        if genome is None:
            raise KeyError(digest)
        return genome

    def __iter__(self) -> Iterator[str]:  # pragma: no cover -- the Mapping contract, unused in the loop
        return iter(self._paths)

    def __len__(self) -> int:
        return len(self._paths)

    def _load(self, digest: str) -> Genome | None:
        if digest in self._cache:
            return self._cache[digest]
        path = self._paths.get(digest)
        genome: Genome | None = None
        if path is not None:
            try:
                genome = Genome.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError):
                logger.debug("proposer: skipping unreadable genome file %s", path)
                genome = None
        self._cache[digest] = genome
        return genome


def load_seen_genomes(settings: Settings) -> Mapping[str, Genome]:
    """Every genome the loop has ever written, keyed by :func:`content_digest`.

    This is the memory :func:`propose_generation` needs to recognise its own history. `write_cards`
    keeps one file per `genome_id` under `loop_root/genomes/`, and because `genome_id_for` puts the
    generation in the *prefix* while hashing only the content, the same card rediscovered later sits
    there under a second filename. Keying on the digest collapses those back to one candidate.

    Returns a lazy mapping -- see :class:`_SeenGenomes` for why, and for how the canonical mint is
    chosen. An absent `genomes/` directory is an empty mapping, which is the correct answer for a
    loop that has never run rather than an error.
    """
    genomes_dir = loop_root(settings) / "genomes"
    if not genomes_dir.is_dir():
        return {}

    best: dict[str, tuple[int, str]] = {}
    paths: dict[str, Path] = {}
    for path in genomes_dir.glob("*.json"):
        match = _GENOME_FILENAME.match(path.stem)
        if match is None:
            continue
        generation, digest = int(match.group(1)), match.group(2)
        key = (generation, path.stem)
        if digest not in best or key < best[digest]:
            best[digest] = key
            paths[digest] = path
    return _SeenGenomes(paths)


def write_cards(genomes: Sequence[Genome], *, settings: Settings) -> dict[str, Path]:
    """Build every genome's card, write it to `generated_tier_dir(settings)/{genome_id}.json`, and
    write the genome itself alongside it under `loop_root(settings)/genomes/{genome_id}.json` -- so
    any card in the generated tier can always be traced back to what proposed it, even after
    `app.evolution.promotion` moves the card out of `generated/` and this file is the only copy of
    the genome left. Returns `{genome_id: card_path}` -- the card path, not the genome path, since
    the card is what a caller of this function (the round machinery, a leaderboard) actually runs.

    Unconditionally overwrites whatever is already at `{genome_id}.json`, in both directories, rather
    than checking for an existing file first. That is deliberate, not an oversight: `genome_id` is
    content-addressed (`app.evolution.models.genome_id_for`), so a genome carried forward as an
    incumbent by `propose_generation` -- same id, same content -- writes byte-for-byte the same JSON
    it already wrote in an earlier generation, and re-running that write is a no-op in effect, never
    a conflict worth raising on.
    """
    cards_dir = generated_tier_dir(settings)
    genomes_dir = loop_root(settings) / "genomes"
    cards_dir.mkdir(parents=True, exist_ok=True)
    genomes_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}
    for genome in genomes:
        card = card_for(genome)
        card_path = cards_dir / f"{genome.genome_id}.json"
        card_path.write_text(card.model_dump_json(indent=2) + "\n", encoding="utf-8")

        genome_path = genomes_dir / f"{genome.genome_id}.json"
        genome_path.write_text(genome.model_dump_json(indent=2) + "\n", encoding="utf-8")

        written[genome.genome_id] = card_path
    return written


def propose_generation(
    *,
    generation: int,
    purpose: Purpose,
    config: LoopConfig,
    rng: random.Random,
    shape: CardShape = "rules",
    elites: Sequence[Genome] = (),
    news_symbols: Sequence[str] = (),
    seen: Mapping[str, Genome] | None = None,
) -> tuple[Genome, ...]:
    """One generation's worth of genomes, all of `shape`: `elites` of that shape carried forward as
    incumbents, offspring bred from them by mutation and crossover, and fresh randoms (a news-biased
    fraction of them, when `config.use_news`) filling whatever is left.

    **Every returned genome has `genome.shape == shape` -- no exceptions, no mixing.** See this
    module's own docstring for why: a mixed-shape generation scores on two different exposure bases,
    and `app.tournament.results.build_leaderboard` ranks only the larger group, silently excluding the
    rest from `rows` (naming them in `unscored_reason` instead). A caller that wants to search both
    shapes calls this function once per shape -- typically cycling `shape` across generations the way
    it already cycles `purpose` -- and keeps separate elite lineages per shape.

    **Elites of the wrong shape are silently dropped, not raised on.** `elites` is filtered to
    `elite.shape == shape` before anything else happens; an elite that fails that filter is simply not
    carried forward, and no error is raised for it. This is deliberate, not a missed check: the
    caller's natural way to search both shapes is to hold one elite lineage per shape and cycle `shape`
    per generation, which means this function is routinely called with `elites` that legitimately
    contain the *other* shape's incumbents (e.g. a `"rules"`-lineage elite passed alongside an
    `"allocation"`-lineage one because the caller keeps them in one list). Raising on that would punish
    the caller for a normal, expected shape of input; the purpose mismatch check just below stays a
    hard `ProposalRejected` because a purpose mismatch has no such legitimate reason to occur --
    `elites` for the wrong `purpose` is always a caller bug, never routine shape-cycling.

    **Incumbents, not just parents.** `app.evolution.promotion`'s gate requires the *same*
    `genome_id` to clear in two consecutive generations on differing window sets -- that is what
    turns one good result into evidence rather than a single lucky draw. A genome that only ever
    seeded a `mutate`/`crossover` call and never ran again itself could never satisfy that gate; every
    offspring carries a *new* `genome_id` (a new digest over its own, different traits), so "breed
    from the elites" alone would make the promotion path permanently unreachable. `elites` are
    therefore returned in this generation's output *unchanged* -- identical `genome_id`, identical
    original `generation` -- rather than re-minted at the current `generation`. Re-minting would be
    wrong, not merely different: `genome_id_for` puts the generation number in the id's own prefix
    while the digest covers only content, so stamping identical content with today's generation would
    produce a *different* id, and promotion would see two unrelated candidates where there is
    actually one candidate being re-measured. Consequently **not every genome this function returns
    has `generation == generation`** -- offspring and randoms do; a carried-forward incumbent keeps
    whatever generation it was first proposed in. A caller that wants "just this generation's new
    work" filters on `origin != "founder"` and `parents == ()` being insufficient -- the correct
    filter is comparing `genome.generation` to the `generation` argument, which is exactly why that
    field is preserved rather than overwritten.

    **Fill order: incumbents, then offspring, then randoms, truncated to `config.population`.**
    Incumbents are capped at `config.population - 1` (or `0` if `elites` is empty) so at least one
    new candidate is always proposed -- a generation that is nothing but re-run incumbents is a
    re-measurement, not a search, and this function's job is to keep proposing. If `elites` is
    already smaller than that cap, every elite is carried forward and the rest of the budget goes to
    offspring/randoms as usual.

    De-duplicates by `genome_id` as it goes, incumbents included -- an offspring or random draw that
    happens to collide with an already-carried-forward incumbent (or with another accepted genome
    this same call) is skipped, bounded by a fixed attempt budget, so a generation that keeps
    colliding comes back shorter than `config.population` rather than looping forever (see the
    module's own approach to `ProposalRejected`: a rejected draw is also simply retried, up to the
    same budget, rather than propagated -- a single unlucky genome should not fail the whole
    generation when another draw would have succeeded).

    Before returning, every genome's card (incumbents included) is built and checked with
    `app.tournament.purposes.find_disjointness_violations` against the whole existing library
    (`app.tournament.results.load_library()`) -- if any Roth-purpose candidate in this generation
    shares a ticker with an existing taxable-purpose card, this raises `ProposalRejected` rather than
    returning a generation this package's own safety rule forbids. `universe.py`'s pool partition
    already makes this structurally unlikely (see that module's docstring on the substitutions it
    required), but the check runs regardless and for every purpose, not only Roth: a defect anywhere
    upstream that let a purpose's pool drift should fail loudly here, not silently ship a card.

    **`config.focus_symbols`/`config.avoid_symbols` are applied to every offspring, random and
    news-biased draw this call produces.** See `LoopConfig.focus_symbols`'s own docstring for the
    division of labour: `config.goal` is prose nothing in this package reads, and these two lists are
    the machine-readable half of the same intent that actually constrains the search. Validated once,
    up front, against this call's own `purpose` (`_validate_focus_avoid`) -- a focus symbol outside
    `purpose`'s pool, a symbol named in both lists, or a focus list too long for `Genome.universe`'s
    12-symbol cap to ever hold, all raise `ProposalRejected` before a single genome is drawn, rather
    than being discovered candidate-by-candidate or silently dropped. Every genome this function
    actually draws is then rewritten (`_apply_focus_avoid`) so its universe contains every focus
    symbol and none of the avoid symbols, and the disjointness check above still runs over the
    rewritten universes -- a focus symbol that would break Roth/taxable disjointness is refused with
    the whole generation, never quietly honoured.

    **Incumbents are exempt.** An elite carried forward keeps the exact universe (and `traits`,
    `genome_id`, `generation`) it was originally proposed with -- see the "Incumbents, not just
    parents" section above for why re-minting an incumbent breaks `app.evolution.promotion`'s gate.
    A mid-run change to `focus_symbols`/`avoid_symbols` therefore applies only to the new candidates a
    generation proposes from that point on; an incumbent whose universe predates a newly-added focus
    symbol is not retroactively rewritten to add it.
    """
    _validate_focus_avoid(config, purpose, generation)

    for elite in elites:
        if elite.purpose is not purpose:
            raise ProposalRejected(
                elite.genome_id,
                f"elite purpose {elite.purpose.value!r} does not match requested purpose {purpose.value!r}",
            )

    # Elites of a different shape are routine input (see the docstring above on shape-cycling
    # callers), not a caller error -- drop them silently rather than raising or carrying them
    # forward, which is exactly the mixed-shape defect this function must not reintroduce.
    shape_elites = tuple(elite for elite in elites if elite.shape == shape)

    news_pool = tuple(news_symbols)
    use_news = bool(config.use_news and news_pool)
    news_slots = round(config.population * config.news_fraction) if use_news else 0

    accepted: dict[str, Genome] = {}
    order: list[Genome] = []

    # Incumbents first, capped so at least one new candidate is always proposed this generation.
    incumbent_budget = max(config.population - 1, 0) if shape_elites else 0
    for elite in shape_elites[:incumbent_budget]:
        if elite.genome_id in accepted or len(order) >= config.population:
            break
        accepted[elite.genome_id] = elite
        order.append(elite)

    max_attempts = max(config.population * 20, 40)
    attempts = 0

    while len(order) < config.population and attempts < max_attempts:
        attempts += 1
        want_news = use_news and len(order) < news_slots

        try:
            if want_news:
                genome = random_genome(
                    rng, generation=generation, purpose=purpose, shape=shape, news_symbols=news_pool
                )
            elif len(shape_elites) >= 2 and rng.random() < 0.4:
                parent_a, parent_b = rng.sample(shape_elites, 2)
                genome = crossover(parent_a, parent_b, rng, generation=generation)
            elif shape_elites and rng.random() < 0.6:
                parent = rng.choice(shape_elites)
                genome = mutate(parent, rng, generation=generation)
            else:
                genome = random_genome(rng, generation=generation, purpose=purpose, shape=shape)
            genome = _apply_focus_avoid(genome, config=config)
        except (ProposalRejected, ValidationError):
            continue

        # **A rediscovery is the same candidate, not a new one.** `genome_id_for` hashes only the
        # content and puts the generation in the prefix, so a draw that lands on traits already tried
        # arrives here with a brand-new id and an identical digest. Left alone it becomes a second
        # candidate: `app.evolution.promotion` accumulates evidence by matching `genome_id` across
        # generations, so one card reads as two that each cleared the gate once, and "twice on
        # differing window sets" gets harder rather than easier the longer the loop runs. The ledger
        # counts it twice too, inflating the multiple-comparison denominator with a hypothesis nobody
        # newly proposed.
        #
        # Substituting the first-seen genome makes the re-run what `genome_id_for`'s docstring already
        # says it is -- another measurement of the same candidate -- which is exactly the evidence the
        # two-generation gate wants. Measured before this landed: 47 of 1,701 distinct card contents
        # had been minted under more than one id, three of them under three, and three pairs reached
        # the paper-desk approval queue as separately approvable rows.
        previous = seen.get(content_digest(genome.genome_id)) if seen else None
        if previous is not None:
            genome = previous

        if genome.genome_id in accepted:
            continue
        accepted[genome.genome_id] = genome
        order.append(genome)

    cards = [card_for(genome) for genome in order]
    library = load_library()
    other_cards = [card for tier_cards in library.values() for card in tier_cards]
    violations = find_disjointness_violations((*cards, *other_cards))
    if violations:
        raise ProposalRejected(
            violations[0].roth_agent_id,
            "roth/taxable disjointness violated: " + "; ".join(v.message for v in violations),
        )

    return tuple(order)
