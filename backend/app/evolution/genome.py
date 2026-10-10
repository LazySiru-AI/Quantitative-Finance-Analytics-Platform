"""The genetic operators: `random_genome`, `mutate`, `crossover` -- everything that turns an RNG
draw (or a pair of existing candidates) into a new `Genome`, and nothing past that.

**What this module deliberately does not know.** A `Genome` here is inert data -- it names a universe
and a flat `traits` dict, and it is `app.evolution.proposer.card_for` that turns those into an actual
`StrategyCard`/`AllocationCard` and validates the emitted rule text against `app.rules.grammar`. This
module never imports `app.rules.grammar` or either card model: an operator that constructed a card
directly could not be tested for genetic behaviour (does `mutate` touch 1-3 traits? does `crossover`
refuse mismatched purposes?) without also exercising the rule parser and every card validator on every
call, and a bug in either would then be indistinguishable from a bug in the operator itself.

**Determinism is the whole point of taking `rng: random.Random` as a parameter instead of reaching
for the module-global `random` functions.** Two calls with separately constructed `random.Random`
instances seeded identically, given identical other arguments, draw the identical sequence of values
and therefore produce the identical `Genome` -- including its `genome_id`, since
`app.evolution.models.genome_id_for` hashes only `shape`/`purpose`/`universe`/`traits`, all of which
are fully determined by that draw sequence. This is what lets a generation be replayed from its seed
rather than merely logged.

**`rule_shape` is a trait here and nothing more.** The vocabulary it is drawn from lives in
`app.evolution.models.RULE_SHAPES`, deliberately not in `app.evolution.ruleforms`, so drawing and
perturbing it costs this module nothing but a tuple lookup and the promise above -- that no operator here
imports the grammar or a card model -- survives. What each name renders to is `ruleforms`' business and
`app.evolution.proposer.card_for`'s, exactly as the emitted rule text always was. It replaces `discipline`,
which was drawn from `Discipline` at random, mutated to another random member, and then reached nothing but
the card's display: 26 of the completed run's 673 single-parent mutations produced a child behaviourally
identical to its parent, 15 of them differing in nothing but that label. A trait that cannot change
behaviour is a mutation the search spends a generation on and learns nothing from.

**Every ticker these operators ever touch comes from `app.evolution.universe.pool_for(purpose)`.**
`mutate`'s ticker swap looks up a replacement from the same `Pool` sleeve (`Pool.category_of`) the
outgoing symbol belongs to, drawn from the same purpose's pool the parent already carries -- there is
no code path here that can hand a genome a symbol its purpose's pool does not contain, which is what
makes `universe.py`'s structural Roth/taxable disjointness a property every genome inherits for free
rather than something this module has to separately remember to check.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.evolution.models import (
    LEGACY_RULE_SHAPE,
    RULE_SHAPES,
    RULES_PERIOD_BOUNDS,
    CardShape,
    Genome,
    GenomeOrigin,
    ProposalRejected,
    genome_id_for,
)
from app.evolution.universe import Pool, pool_for
from app.tournament.purposes import Purpose

__all__ = ["crossover", "mutate", "random_genome"]

_CENT = Decimal("0.01")

#: The small, fixed vocabulary a `traits["tilt"]` value is drawn from. Not an actual `TiltRule` --
#: the allocation `traits` budget (`weights`, `band_pct`, `tilt` -- three keys) has no room to carry
#: a real rule's `condition`/`on_symbol`/`from_symbol`/`to_symbol`/`shift_pct`. `tilt` is a label a
#: reader (and `proposer.card_for`'s thesis text) uses to describe the candidate's flavour; every
#: allocation card this package proposes is, mechanically, constant-weight and band-rebalanced only
#: -- see `proposer.py`'s own docstring for why that is a deliberate simplification, not an omission.
_TILT_VOCAB: tuple[str | None, ...] = (None, "mean-reversion", "trend", "volatility")

#: Ranking-key expressions `_random_rules_traits` may draw `rank_key` from, alongside `None`. Every
#: one of these must parse under `app.rules.grammar.parse_ranking` -- `proposer.card_for` re-checks
#: this at card-build time regardless, but drawing only from known-good text here means a generated
#: genome practically never gets rejected for a reason this module could have avoided.
_RANK_KEY_VOCAB: tuple[str | None, ...] = (
    None,
    "rsi(14)",
    "close / sma(50)",
    "close / sma(200)",
)


def _cents(value: float | Decimal) -> Decimal:
    """`value` rounded to the nearest cent, as a `Decimal` -- the one place this module touches
    money-shaped fractions, so every allocation weight downstream of this function already carries
    the 2-decimal-place precision `proposer.card_for` needs to build exact `Sleeve.target_weight`
    values from (see that function's own docstring on why weights are strings, not floats, by the
    time they reach a card)."""
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Universe helpers -- shared by random_genome, mutate and crossover
# ---------------------------------------------------------------------------


def _eligible_news(pool: Pool, news_symbols: Sequence[str]) -> tuple[str, ...]:
    """`news_symbols` narrowed to the ones this purpose's pool actually contains, order preserved,
    duplicates dropped.

    A news provider has no notion of "which purpose's book" a hot ticker belongs to -- it is just a
    list of symbols the market is talking about. Narrowing here, rather than trusting the caller to
    have already filtered, is what keeps the "every ticker comes from the pool" guarantee this
    module's own docstring makes true even when `use_news=True`: a headline about a symbol neither
    pool holds influences nothing.
    """
    seen: dict[str, None] = {}
    for symbol in news_symbols:
        if symbol in pool.all_symbols():
            seen.setdefault(symbol, None)
    return tuple(seen)


def _swap_ticker(rng: random.Random, universe: tuple[str, ...], pool: Pool) -> tuple[str, ...]:
    """Replace one symbol in `universe` with another from the identical sleeve of the identical pool,
    or return `universe` unchanged if there is no alternative to swap in (the pool's `leveraged`
    sleeve is always a single symbol, so a leveraged slot is never swappable -- by design, see
    `Pool.leveraged`'s own docstring on why a book carries exactly one amplifier).

    This is the one function in the whole package that performs `mutate`'s ticker-level change, and
    it is deliberately narrow: `pool.category_of(symbol)` is looked up from the *outgoing* symbol, so
    the replacement is drawn from that same sleeve of that same purpose's pool -- never a different
    sleeve, never a different purpose's pool. A genome that entered this function already respecting
    the Roth/taxable wall leaves it still respecting the wall.
    """
    if not universe:
        return universe
    index = rng.randrange(len(universe))
    symbol = universe[index]
    try:
        category = pool.category_of(symbol)
    except KeyError:
        return universe
    candidates = [s for s in getattr(pool, category) if s not in universe]
    if not candidates:
        return universe
    replacement = rng.choice(candidates)
    return (*universe[:index], replacement, *universe[index + 1 :])


# ---------------------------------------------------------------------------
# "rules" shape: universe and traits
# ---------------------------------------------------------------------------


def _random_rules_universe(
    rng: random.Random, pool: Pool, eligible_news: tuple[str, ...]
) -> tuple[tuple[str, ...], bool]:
    """A subset of `pool.growth`, usually topped up with one `pool.satellite` symbol -- the same
    "mostly trend names, a satellite tilt" shape `backend/app/paper/library/base/C-trend.json`
    already has (NVDA/AVGO/TSM/... plus SOXX). Returns the universe and whether a news symbol ended
    up in it, so the caller can decide `origin`.
    """
    size = rng.randint(4, min(9, len(pool.growth)))
    universe = list(rng.sample(pool.growth, size))
    if pool.satellite and rng.random() < 0.5 and len(universe) < 12:
        candidate = rng.choice(pool.satellite)
        if candidate not in universe:
            universe.append(candidate)
    contributed_news = False
    if eligible_news:
        pick = rng.choice(eligible_news)
        if pick in universe:
            contributed_news = True
        elif len(universe) < 12:
            universe.append(pick)
            contributed_news = True
        else:
            universe[-1] = pick
            contributed_news = True
    return tuple(dict.fromkeys(universe)), contributed_news


def _random_rules_traits(rng: random.Random) -> dict[str, Any]:
    """Draw all ten `"rules"`-shape traits at once, already satisfying `fast < slow < regime_ma`
    and `position_pct * max_positions <= 1` by construction -- the same two invariants
    `proposer.card_for` re-checks defensively before it ever calls `StrategyCard(...)`.

    The three period draws stay well inside `RULES_PERIOD_BOUNDS` (`fast` 8-15, `slow` 16-40,
    `regime_ma` 56-160 against bands of 3-40, 10-90 and 50-250), so a fresh genome is never clamped;
    the bounds bind only after a long enough chain of mutations, which is what they are for.
    """
    fast = rng.randint(8, 15)
    slow = rng.randint(fast + 8, fast + 25)
    regime_ma = rng.randint(slow + 40, slow + 120)
    stop_loss_pct = round(rng.uniform(0.05, 0.15), 2)
    take_profit_pct = round(rng.uniform(0.15, 0.40), 2) if rng.random() < 0.5 else None
    max_hold_days = rng.randint(60, 180)
    max_positions = rng.randint(3, 6)
    cap = math.floor((1.0 / max_positions) * 100) / 100
    position_pct = round(rng.uniform(0.10, cap), 2)
    rank_key = rng.choice(_RANK_KEY_VOCAB)
    rule_shape = rng.choice(RULE_SHAPES)
    return {
        "fast": fast,
        "slow": slow,
        "regime_ma": regime_ma,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
        "max_hold_days": max_hold_days,
        "max_positions": max_positions,
        "position_pct": position_pct,
        "rank_key": rank_key,
        "rule_shape": rule_shape,
    }


def _fix_rules_ordering(traits: dict[str, Any]) -> dict[str, Any]:
    """Force `fast < slow < regime_ma`, and force all three inside `RULES_PERIOD_BOUNDS`, after a
    mutation or crossover may have broken either.

    Ordering first, by sorting the three values -- simpler, and just as correct, as re-deriving each
    value's individually valid range and re-drawing until it happens to sort: the *labels*
    `fast`/`slow`/`regime_ma` are what a reader of the emitted rule text cares about, not which specific
    integer started out under which label.

    Then bounds, from the bottom up, each one's floor raised to keep it strictly above the value below
    it. That direction matters: clamping downward from the top would let `regime_ma`'s ceiling push
    `slow` and `fast` back into a collision it had just resolved, where raising each floor to
    `previous + 1` cannot, since every band's ceiling is comfortably above the band below it
    (`fast` ends at 40 against a `slow` band running to 90, and `slow` at 90 against `regime_ma`'s 250).

    **Why bounds exist here at all, which they did not before `rule_shape`.** `app.rules.grammar` does
    not range-check an indicator's parameters -- `sma(600)` and `swing_high(300)` both parse -- so an
    out-of-range period surfaces only when the rule is evaluated, inside a scoring run, as a whole card
    lost. `_perturb_rules_trait` walks these three upward with no ceiling, and with eight rule shapes
    drawing on them the tightest limit any of them needs (`swing`'s 250-bar lookback) now binds all
    three. `regime_ma`'s 250 additionally keeps the largest warmup a genome can demand under
    `app.evolution.universe.MIN_WARMUP_BARS`, whose own docstring assumed exactly this kind of ceiling
    without there being one.
    """
    values = sorted((int(traits["fast"]), int(traits["slow"]), int(traits["regime_ma"])))
    for i in range(1, 3):
        if values[i] <= values[i - 1]:
            values[i] = values[i - 1] + 1

    bounded: list[int] = []
    for key, value in zip(("fast", "slow", "regime_ma"), values, strict=True):
        low, high = RULES_PERIOD_BOUNDS[key]
        if bounded:
            low = max(low, bounded[-1] + 1)
        bounded.append(min(max(value, low), high))

    traits = dict(traits)
    traits["fast"], traits["slow"], traits["regime_ma"] = bounded
    return traits


def _adopt_rules_vocabulary(traits: dict[str, Any]) -> dict[str, Any]:
    """`traits` translated from the pre-`rule_shape` vocabulary, if that is what it is.

    A parent genome is not always something these operators just drew: `proposer.load_seen_genomes` and
    the loop's elite selection both reload genomes written by earlier runs, and every `"rules"` genome
    the completed 231-generation run wrote carries a `discipline` key and no `rule_shape`. Left alone,
    such a parent breaks both operators -- `mutate` would eventually pick `"discipline"` to perturb and
    hit `_perturb_rules_trait`'s "unknown trait" guard, and any child would reach `card_for` with no
    shape to render. Translating instead of refusing is what lets the finished run's elites keep breeding
    across this change.

    The translation is a statement of fact, not a default: those genomes emitted the `"ma-crossover"`
    template and nothing else (see `app.evolution.models.LEGACY_RULE_SHAPE`), and their `discipline`
    was a random draw that described nothing, so it is dropped rather than carried. One key out, one key
    in -- the ten-key budget is unchanged.
    """
    if "rule_shape" in traits and "discipline" not in traits:
        return traits
    translated = {key: value for key, value in traits.items() if key != "discipline"}
    translated.setdefault("rule_shape", LEGACY_RULE_SHAPE)
    return translated


def _fix_rules_sizing(traits: dict[str, Any]) -> dict[str, Any]:
    """Clamp `position_pct` so `position_pct * max_positions` never exceeds one whole book --
    `StrategyCard._position_sizing_is_a_fraction_of_one` would otherwise reject the card outright at
    `proposer.card_for` time for a combination a mutation is free to produce (e.g. `max_positions`
    perturbed up without `position_pct` perturbed down in the same step)."""
    traits = dict(traits)
    max_positions = int(traits["max_positions"])
    cap = math.floor((1.0 / max_positions) * 100) / 100
    position_pct = min(float(traits["position_pct"]), cap)
    traits["position_pct"] = round(max(position_pct, 0.01), 2)
    return traits


def _perturb_rules_trait(rng: random.Random, key: str, traits: dict[str, Any]) -> Any:
    """One trait's new value, nudged from its current one rather than redrawn from scratch -- a
    mutation that could land anywhere in the trait's whole range would be indistinguishable from a
    fresh random genome, and the ladder's whole premise is that a *neighbour* of a good candidate is
    worth testing, not an unrelated one wearing the same parent's other nine traits.
    """
    if key == "fast":
        return max(3, int(traits["fast"]) + rng.choice((-3, -2, -1, 1, 2, 3)))
    if key == "slow":
        return max(10, int(traits["slow"]) + rng.choice((-8, -5, -3, 3, 5, 8)))
    if key == "regime_ma":
        return max(50, int(traits["regime_ma"]) + rng.choice((-30, -15, 15, 30)))
    if key == "stop_loss_pct":
        current = float(traits["stop_loss_pct"])
        return round(min(0.25, max(0.03, current + rng.uniform(-0.03, 0.03))), 2)
    if key == "take_profit_pct":
        current = traits["take_profit_pct"]
        if current is None:
            return round(rng.uniform(0.15, 0.40), 2)
        return None if rng.random() < 0.3 else round(min(0.60, max(0.10, float(current) + rng.uniform(-0.05, 0.05))), 2)
    if key == "max_hold_days":
        return max(20, min(252, int(traits["max_hold_days"]) + rng.choice((-30, -15, 15, 30))))
    if key == "max_positions":
        return max(1, min(8, int(traits["max_positions"]) + rng.choice((-1, 1))))
    if key == "position_pct":
        current = float(traits["position_pct"])
        return round(max(0.01, min(1.0, current + rng.uniform(-0.05, 0.05))), 2)
    if key == "rank_key":
        options = [o for o in _RANK_KEY_VOCAB if o != traits["rank_key"]]
        return rng.choice(options)
    if key == "rule_shape":
        options = [shape for shape in RULE_SHAPES if shape != traits["rule_shape"]]
        return rng.choice(options)
    raise ValueError(f"unknown 'rules' trait {key!r}")  # pragma: no cover -- defensive


# ---------------------------------------------------------------------------
# "allocation" shape: universe and traits
# ---------------------------------------------------------------------------


def _draw_allocation_weights(rng: random.Random, n_satellite: int, n_stability: int) -> list[float]:
    """A weight per sleeve, in `[leveraged, *satellites, *stabilities]` order, quantised to cents and
    summing to *exactly* `1.00` -- `AllocationCard._weights_are_a_complete_partition` refuses anything
    else, and refuses to normalise a near-miss rather than accept it (see that validator's own
    docstring), so this function has to get the arithmetic exactly right rather than merely close.

    The leveraged sleeve draws from `[0.0, 0.35]` and each satellite from `[0.03, 0.12]` -- "a few
    percent SOXX or SMH", per the owner's own framing, not a fourth core holding. Both draws are
    quantised to cents *before* anything downstream sums them, so every later step -- including the
    final subtraction below -- is exact `Decimal` arithmetic with no binary-float rounding anywhere
    in the chain. The stability sleeves split whatever is left: an even share for every stability
    sleeve but the last, and the last absorbs the running remainder (including any accumulated cent
    of rounding drift), which is what guarantees the whole vector sums to `1.00` rather than merely
    approximating it. With the leveraged sleeve capped at 0.35 and at most two satellites capped at
    0.12 each, the worst case leaves at least `1.00 - 0.35 - 0.24 = 0.41` for stability, comfortably
    enough that the final stability sleeve is never at risk of going non-positive.
    """
    weights: list[Decimal] = [_cents(rng.uniform(0.0, 0.35))]
    for _ in range(n_satellite):
        weights.append(_cents(rng.uniform(0.03, 0.12)))
    used = sum(weights, Decimal(0))
    remaining = Decimal("1.00") - used
    if n_stability <= 1:
        weights.append(remaining)
    else:
        share = _cents(remaining / n_stability)
        for _ in range(n_stability - 1):
            weights.append(share)
        weights.append(remaining - share * (n_stability - 1))
    return [float(w) for w in weights]


def _random_allocation_universe(
    rng: random.Random, pool: Pool, eligible_news: tuple[str, ...]
) -> tuple[tuple[str, ...], int, int, bool]:
    """`(universe, n_satellite, n_stability, contributed_news)` -- the leveraged sleeve is always
    `pool.leveraged`'s single symbol, followed by 1-2 satellites and 2-4 stability sleeves (bounded
    by however many the pool actually has, for a pool ever shipped smaller than that).
    """
    n_satellite = rng.randint(1, min(2, len(pool.satellite))) if pool.satellite else 0
    n_stability = rng.randint(min(2, len(pool.stability)), min(4, len(pool.stability)))
    satellites = list(rng.sample(pool.satellite, n_satellite)) if n_satellite else []
    stabilities = list(rng.sample(pool.stability, n_stability))

    contributed_news = False
    if eligible_news:
        pick = rng.choice(eligible_news)
        category = pool.category_of(pick)
        if category == "satellite" and satellites:
            if pick not in satellites:
                satellites[rng.randrange(len(satellites))] = pick
            contributed_news = True
        elif category == "stability" and stabilities:
            if pick not in stabilities:
                stabilities[rng.randrange(len(stabilities))] = pick
            contributed_news = True
        elif category == "leveraged":
            contributed_news = True

    satellites = list(dict.fromkeys(satellites))
    stabilities = list(dict.fromkeys(stabilities))
    universe = pool.leveraged + tuple(satellites) + tuple(stabilities)
    return universe, len(satellites), len(stabilities), contributed_news


def _random_allocation_traits(rng: random.Random, n_satellite: int, n_stability: int) -> dict[str, Any]:
    return {
        "weights": _draw_allocation_weights(rng, n_satellite, n_stability),
        "band_pct": round(rng.uniform(0.03, 0.08), 2),
        "tilt": rng.choice(_TILT_VOCAB),
    }


def _perturb_allocation_weights(rng: random.Random, weights: Sequence[float]) -> list[float]:
    """Move a small, cent-quantised amount from one sleeve to another. A transfer, not a resample --
    the sum is invariant by construction (what one sleeve loses, another gains, to the same cent),
    which is what lets `mutate` touch `"weights"` without having to re-run the whole
    remainder-absorption dance `_draw_allocation_weights` uses for a fresh genome.
    """
    decimals = [_cents(w) for w in weights]
    if len(decimals) < 2:
        return [float(d) for d in decimals]
    i, j = rng.sample(range(len(decimals)), 2)
    headroom = decimals[i] - _CENT
    if headroom <= 0:
        i, j = j, i
        headroom = decimals[i] - _CENT
    if headroom <= 0:
        return [float(d) for d in decimals]
    delta = min(headroom, Decimal("0.05"))
    if delta > _CENT:
        delta = _cents(rng.uniform(float(_CENT), float(delta)))
    decimals[i] -= delta
    decimals[j] += delta
    return [float(d) for d in decimals]


def _perturb_allocation_trait(rng: random.Random, key: str, traits: dict[str, Any]) -> Any:
    if key == "weights":
        return _perturb_allocation_weights(rng, traits["weights"])
    if key == "band_pct":
        current = float(traits["band_pct"])
        return round(min(0.15, max(0.01, current + rng.uniform(-0.02, 0.02))), 2)
    if key == "tilt":
        options = [t for t in _TILT_VOCAB if t != traits["tilt"]]
        return rng.choice(options)
    raise ValueError(f"unknown 'allocation' trait {key!r}")  # pragma: no cover -- defensive


# ---------------------------------------------------------------------------
# The three public operators
# ---------------------------------------------------------------------------


def random_genome(
    rng: random.Random,
    *,
    generation: int,
    purpose: Purpose,
    shape: CardShape,
    news_symbols: Sequence[str] = (),
) -> Genome:
    """A fresh genome with no parents, drawn from `purpose`'s pool.

    `origin` is `"news"` only when a symbol from `news_symbols` -- narrowed to this purpose's own
    pool first, see `_eligible_news` -- actually ends up in the genome's `universe`; an empty
    `news_symbols`, or one containing nothing this pool holds, always yields `"random"`.
    """
    pool = pool_for(purpose)
    seed = rng.getrandbits(63)
    eligible_news = _eligible_news(pool, news_symbols)

    if shape == "rules":
        universe, contributed_news = _random_rules_universe(rng, pool, eligible_news)
        traits = _random_rules_traits(rng)
    elif shape == "allocation":
        universe, n_satellite, n_stability, contributed_news = _random_allocation_universe(
            rng, pool, eligible_news
        )
        traits = _random_allocation_traits(rng, n_satellite, n_stability)
    else:  # pragma: no cover -- CardShape is a closed Literal; defensive only
        raise ValueError(f"unknown shape {shape!r}")

    origin: GenomeOrigin = "news" if contributed_news else "random"
    genome_id = genome_id_for(generation=generation, shape=shape, purpose=purpose, universe=universe, traits=traits)
    return Genome(
        genome_id=genome_id,
        generation=generation,
        parents=(),
        origin=origin,
        shape=shape,
        purpose=purpose,
        universe=universe,
        traits=traits,
        seed=seed,
        notes=f"random {shape} candidate for {purpose.value}" + (" (news-biased)" if origin == "news" else ""),
    )


def mutate(parent: Genome, rng: random.Random, *, generation: int) -> Genome:
    """One offspring of `parent`: 1-3 of its traits perturbed, and -- with 40% probability -- one
    ticker swapped for another in the same sleeve of the same purpose's pool (see `_swap_ticker`).

    Never re-draws every trait: a mutation that touched all ten `"rules"` keys (or all three
    `"allocation"` keys) in one step would just be a random genome that happened to share its
    parent's `shape` and `purpose`, defeating the reason a search breeds from elites at all -- that a
    small step from something that scored well is worth testing before a large one is.

    `"rule_shape"` is the one `"rules"` trait whose perturbation is *not* a small step: it swaps the
    rule's whole form (`app.evolution.ruleforms.RENDERERS`) for another, keeping the periods, brackets,
    sizing and universe the parent earned its score with. That is deliberate and it is what the trait it
    replaced could not do -- `discipline` was equally free to flip and changed nothing at all, so 15 of
    the completed run's mutations spent a generation relabelling a card. A shape flip is a real
    hypothesis about the same instruments; a label flip was a coin toss recorded as one.
    """
    pool = pool_for(parent.purpose)
    traits = dict(parent.traits)
    if parent.shape == "rules":
        traits = _adopt_rules_vocabulary(traits)
    keys = list(traits.keys())
    touch_count = rng.randint(1, min(3, len(keys)))
    for key in rng.sample(keys, touch_count):
        if parent.shape == "rules":
            traits[key] = _perturb_rules_trait(rng, key, traits)
        else:
            traits[key] = _perturb_allocation_trait(rng, key, traits)

    if parent.shape == "rules":
        traits = _fix_rules_ordering(traits)
        traits = _fix_rules_sizing(traits)

    universe = parent.universe
    if rng.random() < 0.4:
        universe = _swap_ticker(rng, universe, pool)

    seed = rng.getrandbits(63)
    genome_id = genome_id_for(
        generation=generation, shape=parent.shape, purpose=parent.purpose, universe=universe, traits=traits
    )
    return Genome(
        genome_id=genome_id,
        generation=generation,
        parents=(parent.genome_id,),
        origin="mutation",
        shape=parent.shape,
        purpose=parent.purpose,
        universe=universe,
        traits=traits,
        seed=seed,
        notes=f"mutated from {parent.genome_id}",
    )


def crossover(a: Genome, b: Genome, rng: random.Random, *, generation: int) -> Genome:
    """One offspring combining `a` and `b`: each trait key inherited from one parent or the other by
    an independent coin flip, and a universe recombined from both parents' sleeves.

    Refuses -- raises `ProposalRejected` -- if `a.purpose is not b.purpose`: crossing a Roth parent
    with a taxable one would need to pick a universe from *some* pool, and any choice either strands
    half the traits' ticker context or reaches into the other parent's pool, which is exactly the
    cross-purpose contamination `universe.py`'s structural partition exists to make impossible. Also
    refuses on a shape mismatch (`a.shape is not b.shape`) for the analogous reason: a `"rules"`
    parent's traits (`fast`/`slow`/...) and an `"allocation"` parent's traits (`weights`/...) share no
    keys to recombine, so "crossing" them would only ever mean discarding one parent's traits
    entirely -- which is not a crossover, it is a mutation wearing two parents' names.

    Both `"rules"` parents are put through `_adopt_rules_vocabulary` before their keys are matched up,
    so a pre-`rule_shape` elite reloaded off disk can still be crossed with one drawn since. Without it
    the coin flip would iterate `a`'s keys and index `b`'s, and a cross-vintage pair would raise `KeyError`
    on whichever key only one of them carries.
    """
    if a.purpose is not b.purpose:
        raise ProposalRejected(a.genome_id, f"cannot cross purposes {a.purpose.value!r} and {b.purpose.value!r}")
    if a.shape != b.shape:
        raise ProposalRejected(a.genome_id, f"cannot cross shapes {a.shape!r} and {b.shape!r}")

    pool = pool_for(a.purpose)
    shape = a.shape

    if shape == "rules":
        a_traits, b_traits = _adopt_rules_vocabulary(a.traits), _adopt_rules_vocabulary(b.traits)
        traits = {
            key: (a_traits[key] if rng.random() < 0.5 else b_traits.get(key, a_traits[key]))
            for key in a_traits
        }
        traits = _fix_rules_ordering(traits)
        traits = _fix_rules_sizing(traits)
        combined = list(dict.fromkeys((*a.universe, *b.universe)))
        if len(combined) > 12:
            combined = rng.sample(combined, rng.randint(4, 12))
        universe = tuple(combined)
    else:
        sat_pool = list(dict.fromkeys(s for s in (*a.universe, *b.universe) if s in pool.satellite))
        stab_pool = list(dict.fromkeys(s for s in (*a.universe, *b.universe) if s in pool.stability))
        if not sat_pool:
            sat_pool = list(pool.satellite)
        if not stab_pool:
            stab_pool = list(pool.stability)
        n_satellite = rng.randint(min(1, len(sat_pool)), min(2, len(sat_pool)))
        n_stability = rng.randint(min(1, len(stab_pool)), min(4, len(stab_pool)))
        satellites = tuple(rng.sample(sat_pool, n_satellite))
        stabilities = tuple(rng.sample(stab_pool, n_stability))
        universe = pool.leveraged + satellites + stabilities
        traits = {
            "weights": _draw_allocation_weights(rng, len(satellites), len(stabilities)),
            "band_pct": a.traits["band_pct"] if rng.random() < 0.5 else b.traits["band_pct"],
            "tilt": a.traits["tilt"] if rng.random() < 0.5 else b.traits["tilt"],
        }

    seed = rng.getrandbits(63)
    genome_id = genome_id_for(generation=generation, shape=shape, purpose=a.purpose, universe=universe, traits=traits)
    return Genome(
        genome_id=genome_id,
        generation=generation,
        parents=(a.genome_id, b.genome_id),
        origin="crossover",
        shape=shape,
        purpose=a.purpose,
        universe=universe,
        traits=traits,
        seed=seed,
        notes=f"crossed {a.genome_id} x {b.genome_id}",
    )
