"""The evolution loop's shared vocabulary.

Every other module in `app.evolution` imports from here, and none of them import each other's
internals, so this file is the package's contract: change a type here and the whole loop's shape
changes; change one anywhere else and it does not.

Nothing in this module computes anything. It holds the types, the on-disk path conventions, and the
exceptions -- deliberately, so that the supervisor thread, the HTTP layer and the tests can all agree
on what a generation *is* without any of them having to import the machinery that produces one.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import Settings
from app.tournament.purposes import Purpose

__all__ = [
    "GENERATED_TIER",
    "LEGACY_RULE_SHAPE",
    "MAX_FREE_PARAMETERS",
    "NOISE_FLOOR_PP",
    "RULES_PERIOD_BOUNDS",
    "RULE_SHAPES",
    "AmendmentOutcome",
    "AmendmentRecord",
    "CardShape",
    "Finding",
    "FindingKind",
    "GenerationOutcome",
    "Genome",
    "GenomeOrigin",
    "LoopAlreadyRunning",
    "LoopConfig",
    "LoopNotRunning",
    "LoopPhase",
    "LoopState",
    "LoopStatus",
    "PendingSeat",
    "PromotionRecord",
    "ProposalRejected",
    "RefusedAmendment",
    "RuleShape",
    "SeatStatus",
    "Standing",
    "amendments_path",
    "content_digest",
    "generated_tier_dir",
    "generation_review_path",
    "genome_id_for",
    "loop_root",
    "next_round_sequence",
    "pending_seats_path",
    "roster_overlay_path",
]


# ---------------------------------------------------------------------------
# Constants the whole package agrees on
# ---------------------------------------------------------------------------

#: The library tier auto-generated cards are written to.
#:
#: Deliberately *not* one of `base`/`variants`/`candidates`. Those three are the human programme's
#: shelves and `strategy-program/PROTOCOL.md` section 6 governs what moves between them; a searcher
#: that wrote into them directly would make that rule unenforceable within a single generation. A
#: card leaves `generated/` only through `app.evolution.promotion`, which applies section 6's own
#: two-round rule.
GENERATED_TIER = "generated"

#: `strategy-program/PROTOCOL.md` section 3's free-parameter budget, applied to a `Genome`'s `traits`.
#:
#: The protocol imposes this on a human analyst per card. A generative proposer has no incentive to
#: respect it on its own -- more knobs is strictly more search -- so it is enforced by the type
#: instead of by a reader.
MAX_FREE_PARAMETERS = 10

#: The measured ordering-noise floor, in percentage points, from `strategy-program/PROTOCOL.md` s7.
#:
#: One identical card re-run under twelve `universe` orderings moved its three-year return across a
#: 53.9-point spread with sigma = 21.2 points. A margin smaller than this is not evidence of
#: anything, which is why it is the default `LoopConfig.promotion_margin_pp` rather than a number a
#: caller has to know to supply.
NOISE_FLOOR_PP = Decimal("21.2")

CardShape = Literal["rules", "allocation"]
"""Which card model a genome expresses.

`"rules"` is an `app.tournament.models.StrategyCard` -- per-symbol boolean entry/exit, one fixed
`position_pct` per slot. `"allocation"` is an `app.tournament.allocation.AllocationCard` -- continuous
target weights with drift-band rebalancing, which is the only one of the two shapes that can express
"mostly trend, a few per cent semiconductors, the rest stability".

Ladder cards are readable by the scorer but the loop does not generate them: their parameter space is
a rung schedule, and mutating a rung schedule under a search that never stops is the most direct
route to an overfit this package has.
"""

RuleShape = Literal[
    "ma-crossover",
    "momentum-state",
    "rsi-pullback",
    "band-reversion",
    "channel-breakout",
    "band-breakout",
    "macd-cross",
    "vol-compression",
]
"""Which *form* a `"rules"` genome's entry/exit text takes -- the trait that replaced `discipline`.

Until this existed, `app.evolution.proposer._rules_card` composed every candidate's rule from one
hardcoded f-string (`close > sma(regime_ma) and ema(fast) crosses_above ema(slow)`), so all 2,374
evaluations of the completed 231-generation run explored exactly one strategy form and varied only its
numbers -- see `docs/research/loop/01-what-the-search-found.md`'s "the search never searched strategy
form". This literal is the search space that replaces it: eight structurally different rule shapes, each
rendered by `app.evolution.ruleforms` from the same three period traits, each parsed by
`app.rules.grammar` before a card is built.

`"ma-crossover"` is first and is the incumbent template, unchanged. It stays in the vocabulary, and is
what `LEGACY_RULE_SHAPE` below names, because every genome written before this change
*was* that template: a parent reloaded off disk with no `rule_shape` key is not shapeless, it is an
`ma-crossover`, and saying so is what lets the completed run's elites keep breeding across this change
instead of being refused by `card_for`.

Kept here rather than in `ruleforms.py` so `app.evolution.genome` can draw and perturb the trait
without importing `app.rules.grammar` -- the one import that module's own docstring promises never to
take, so its genetic operators stay testable without exercising the rule parser. `ruleforms.py` asserts
at import that its renderer table covers exactly these names, so the two cannot drift apart silently.
"""

RULE_SHAPES: tuple[RuleShape, ...] = get_args(RuleShape)
"""`RuleShape`'s members as a tuple, for drawing and iterating. Derived from the `Literal` rather than
restated beside it, so adding a shape to one cannot leave the other behind."""

LEGACY_RULE_SHAPE: RuleShape = "ma-crossover"
"""What a `"rules"` genome carrying no `rule_shape` key is.

Not a default in the "had to pick something" sense. Every `"rules"` genome written before this trait
existed emitted the one hardcoded `close > sma(regime_ma) and ema(fast) crosses_above ema(slow)` template
and nothing else, so reading a missing key as this shape is a statement of fact about those genomes rather
than a guess -- and it is what lets the completed run's 1,887 genomes be reloaded, bred from and re-carded
across this change instead of being refused by `app.evolution.proposer.card_for`."""

#: Inclusive `(minimum, maximum)` bounds for the three period traits every `RuleShape` renders from.
#:
#: The minima are what `app.evolution.genome._perturb_rules_trait` already enforced. The maxima are new,
#: and they are what makes a *shape* safe to evolve: `app.rules.grammar` does not range-check an
#: indicator's parameters (`sma(600)` parses fine), so an unbounded upward random walk on `regime_ma`
#: used to be able to emit a rule that only failed later, at evaluation time, inside a scoring run. With
#: eight shapes drawing on these same three numbers the exposure is wider -- `swing(lookback)` caps at
#: 250 where `sma(period)` caps at 500 -- so the tightest cap any shape needs is applied to all of them.
#:
#: `regime_ma`'s 250 is the one with a second reason: `app.evolution.universe.MIN_WARMUP_BARS` is 300,
#: and that constant's own docstring justifies 300 as "200 (the largest fixed warmup in the genome's
#: vocabulary) plus room for `regime_ma` to mutate above its initial ceiling". A hard 250 is what makes
#: "room" a bounded quantity rather than a hope.
RULES_PERIOD_BOUNDS: dict[str, tuple[int, int]] = {
    "fast": (3, 40),
    "slow": (10, 90),
    "regime_ma": (50, 250),
}

GenomeOrigin = Literal["founder", "mutation", "crossover", "random", "news", "agent"]
"""How a candidate came to exist.

The first five are `app.evolution.genome`'s own operators. `"agent"` is `app.agents.designer` -- a
candidate Claude designed from the previous generation's findings rather than one the seeded RNG
perturbed into being, and it is recorded separately for a reason that outlives the run: an
agent-designed generation is **auditable but not replayable**, where every other origin is both. A
reader who cannot tell the two apart cannot tell which of a loop's generations they could reproduce.
"""
LoopState = Literal["idle", "running", "stopping", "stopped", "failed"]
LoopPhase = Literal["idle", "proposing", "running", "scoring", "promoting", "cooldown"]
FindingKind = Literal["winner", "failure", "regime", "universe", "parameter", "gate", "holdout"]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LoopAlreadyRunning(RuntimeError):
    """A second loop was requested while one is running. Carries the running loop's id."""

    def __init__(self, loop_id: str) -> None:
        super().__init__(f"an evolution loop is already running: {loop_id}")
        self.loop_id = loop_id


class LoopNotRunning(RuntimeError):
    """Stop was requested with no loop running."""


class UnreachablePromotionCeiling(ValueError):
    """`LoopConfig.promotion_max_shared_windows` is set below what this config's windows can produce.

    Raised by `app.evolution.loop.start_loop` **before** the supervisor thread exists, so the caller
    gets a refusal instead of a loop. Carries both numbers, because the useful message is not "that is
    too strict" but "the smallest overlap these windows can produce is N".

    This is the one failure mode the gate cannot report on its own: a promotion requirement nothing can
    satisfy does not look like an error from the inside. The loop proposes, runs, scores and ranks
    exactly as it should, prints entirely reasonable standings, and simply never promotes -- for as
    long as it is left running. `LoopConfig.holdout_windows`' docstring records the same trap reached
    from the other direction (a three-window holdout leaving an unrotatable five-window pool), which is
    why that widening was refused. Both are the same bug: a silently impossible gate.
    """

    def __init__(self, *, ceiling: int, achievable: int, detail: str) -> None:
        super().__init__(
            f"promotion_max_shared_windows={ceiling} can never be met: {detail}, so two evidence "
            f"sets always share at least {achievable} window(s). Raise the ceiling to "
            f"{achievable} or more, or widen the selection window pool."
        )
        self.ceiling = ceiling
        self.achievable = achievable


class ProposalRejected(ValueError):
    """A genome could not be turned into a card this programme's rules permit.

    Raised rather than repaired. A proposer that silently fixes an illegal candidate -- clamping a
    weight, dropping a ticker that breaks Roth disjointness -- produces a card whose genome no longer
    describes it, and the whole loop's reproducibility rests on the genome describing the card.
    """

    def __init__(self, genome_id: str, reason: str) -> None:
        super().__init__(f"genome {genome_id}: {reason}")
        self.genome_id = genome_id
        self.reason = reason


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# The candidate
# ---------------------------------------------------------------------------


class Genome(_Frozen):
    """The heritable description of one candidate: enough to rebuild its card byte-for-byte.

    A `Genome` is what the loop breeds; a `StrategyCard` / `AllocationCard` is what the engine runs.
    Keeping them separate is what makes a generation reproducible -- the card on disk records what
    was tested, and the genome records *why that card and not a neighbouring one*, which a card alone
    cannot say.
    """

    genome_id: str
    """Content hash, from :func:`genome_id_for`. Also the card's `agent_id`, so a run file names its
    own genome and no separate mapping has to be kept in step with the results tree."""

    generation: int = Field(ge=0)

    parents: tuple[str, ...] = ()
    """Parent `genome_id`s. Empty for a founder or a random injection."""

    origin: GenomeOrigin

    shape: CardShape

    purpose: Purpose

    universe: tuple[str, ...] = Field(min_length=1, max_length=12)
    """The tickers this candidate may hold. For an allocation card these are its sleeve symbols, in
    the order `traits["weights"]` gives their weights."""

    traits: dict[str, Any]
    """The free parameters, flat and JSON-serialisable.

    Capped at :data:`MAX_FREE_PARAMETERS` keys. `universe` is not counted against the budget (it is a
    choice of instruments, not a fitted knob) and neither is anything the shape fixes by
    construction.
    """

    seed: int = Field(ge=0)
    """The RNG stream that produced this genome. Recorded so a generation can be replayed."""

    notes: str = ""
    """One line on what this candidate is *for* -- the searcher's stand-in for an analyst's thesis.
    Never a claim about how it did; it is written before the run."""

    @field_validator("traits")
    @classmethod
    def _within_the_parameter_budget(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > MAX_FREE_PARAMETERS:
            raise ValueError(
                f"{len(value)} free parameters exceeds the budget of {MAX_FREE_PARAMETERS} "
                f"(strategy-program/PROTOCOL.md section 3): {sorted(value)}"
            )
        try:
            json.dumps(value, default=str)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError(f"traits must be JSON-serialisable: {exc}") from exc
        return value

    @model_validator(mode="after")
    def _universe_has_no_duplicates(self) -> Genome:
        if len(set(self.universe)) != len(self.universe):
            raise ValueError(f"universe repeats a symbol: {self.universe}")
        return self


def content_digest(genome_id: str) -> str:
    """The content-addressed half of a `genome_id` -- everything after the `g<generation>-` prefix.

    :func:`genome_id_for` mints `g{generation:03d}-{digest}` where the digest covers *only* shape,
    purpose, universe and traits. Two ids sharing a digest are therefore the same card by
    construction, minted at different generations; two ids differing in it are different cards.

    **This exists because the full id cannot answer "is this the same strategy".** That function's
    own docstring says content-addressing makes "a genome the loop rediscovers in generation 40
    recognisably the same candidate it already ran in generation 3" -- but the generation sits in the
    prefix, so the *full* id differs and every consumer keyed on `genome_id` sees two unrelated
    candidates. Measured on this repo's own loop: **47 of 1,701 distinct card contents have been
    minted under more than one id**, three of them under three ids. Anything asking "same strategy?"
    rather than "same run?" must compare this, not the whole id.

    A `genome_id` with no `-` is returned unchanged rather than raising: the queue this is used by
    must survive a malformed row without discarding the rows around it.
    """
    _, separator, digest = genome_id.partition("-")
    return digest if separator else genome_id


def genome_id_for(
    *,
    generation: int,
    shape: CardShape,
    purpose: Purpose,
    universe: tuple[str, ...],
    traits: dict[str, Any],
) -> str:
    """A stable, content-addressed id: the same content in, the same id out, across processes.

    Content-addressed rather than sequential so that a genome the loop rediscovers in generation 40
    is recognisably the same candidate it already ran in generation 3 -- the cheapest way to stop a
    search from spending its budget re-testing its own history, and the only way the ledger's
    correction denominator can count distinct hypotheses rather than distinct runs.

    The prefix is `g` + generation so a directory listing sorts by generation, and the digest is
    truncated to 12 hex characters: 48 bits over a search that will realistically test thousands, not
    billions, of candidates.

    **An incumbent is never re-minted, and that rule is load-bearing.** The generation lives in the
    prefix while the digest covers only content, so calling this function again for the same content
    at a later generation returns a *different* id. A candidate carried forward to run a second time
    must therefore keep the `genome_id` and the `Genome.generation` it was born with, and
    `app.evolution.proposer.propose_generation` returns the previous generation's elites unchanged
    for exactly this reason.

    The alternative -- re-minting each time a candidate runs -- was tried first and is what makes the
    promotion gate dead code: `app.evolution.promotion` accumulates evidence by matching `genome_id`
    across generations, so a re-minted incumbent reads as two unrelated candidates that each cleared
    the gate once, and "twice on differing window sets" becomes unreachable. A genome is identified by
    its content and its first appearance; running it again is another measurement of the same
    candidate, not a new one -- the same sense in which `strategy-program/PROTOCOL.md` treats a frozen
    card.
    """
    payload = json.dumps(
        {
            "shape": shape,
            "purpose": str(purpose),
            "universe": list(universe),
            "traits": traits,
        },
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"g{generation:03d}-{digest}"


# ---------------------------------------------------------------------------
# What a generation produced
# ---------------------------------------------------------------------------


class Standing(_Frozen):
    """One candidate's place in one generation's leaderboard.

    Every number here is copied from `app.tournament.results.LeaderboardRowData`, never recomputed --
    the loop reads the same board the Competition page renders, so a standing and the page can never
    disagree about how a card did.
    """

    genome_id: str
    agent_id: str
    display_name: str
    rank: int
    eligible: bool
    windows_run: int
    median_excess: Decimal | None
    worst_excess: Decimal | None
    hit_rate: float | None
    total_trades: int

    holdout_median_excess: Decimal | None = None
    """Median excess over `LoopConfig.holdout_windows`, which selection never saw.

    `None` when no holdout was configured or the card ran none of it. Reported beside the selection
    number rather than blended into it: a holdout that feeds back into ranking has stopped being one.
    """

    median_adjusted_excess: Decimal | None = None
    """Median `corrected_return - capital_exposure * benchmark_return` over the selection windows --
    the exposure-corrected figure, and the one `app.evolution.promotion.clears_gate` prefers.

    **Why a second median rather than replacing the first.** `median_excess` is
    `strategy_return - benchmark_return`, which across 749 measured runs turned out to be very nearly
    a function of which way the market went rather than of anything the card did: Pearson **r =
    -0.978** between a window's median benchmark and its median excess, slope -0.46. These cards
    capture roughly half the move in either direction, so a falling window hands out excess and a
    rising one takes it away. In `gfc` a card holding 19% of capital and losing 29.69% posts
    `excess = +26.53%` against a -56.23% benchmark -- it reads as beating the market by 26 points
    while actually doing worse than a passive position of its own size, which the adjusted figure
    states plainly at -19.01%.

    `PROTOCOL.md` section 4 introduced this correction for exactly that reason and made it the human
    programme's ranking key. `app.tournament.results` deliberately does not use it (its own module
    docstring records the divergence: the HTTP contract calls for uncorrected `excess`), so the loop
    inherited the bias the protocol was written to remove. This field is where it is removed again.

    **Both figures are kept, and the old one is not restated.** Every generation already on disk was
    scored on plain `excess`; `PROTOCOL.md` section 2's integrity rule forbids re-reporting a finished
    round's numbers under a metric it was not run on. So this is `None` for every historical standing
    and populated going forward, and a reader can always see which number a decision was made on.

    Computed by `app.evolution.feedback._adjusted_value`, which reads `capital_exposure` only and
    never falls back to `exposure` -- see that function for why the fallback is the hazard the
    `ScoredRun.adjusted_excess` shape gate exists to block.
    """

    holdout_median_adjusted_excess: Decimal | None = None
    """The same correction over the holdout windows. Reported beside
    `holdout_median_excess` for the same reason `median_adjusted_excess` sits beside `median_excess`:
    the uncorrected holdout figure is the one that made the gate's "not negative" clause nearly free
    (86.8% of candidate-windows cleared it) when both holdout windows were drawdowns."""

    q_value: float | None = None
    """Benjamini-Hochberg q-value against the whole loop's ledger, not this generation.

    `None` when the card took too few closed trades to test. See `app.evolution.ledger`.
    """


class Finding(_Frozen):
    """One thing the last generation established, in a form the next one can act on.

    Findings are the loop's answer to a round report. They are derived from the leaderboard by
    `app.evolution.feedback` under fixed rules -- no model writes one -- so two passes over the same
    results produce the same findings.
    """

    kind: FindingKind

    summary: str
    """One sentence, stating what was measured. Never a recommendation."""

    evidence: dict[str, Any] = Field(default_factory=dict)
    """The numbers behind `summary`, so a reader never has to take the sentence's word for it."""


class GenerationOutcome(_Frozen):
    """One full iteration of the loop: what was proposed, what it did, what was concluded."""

    generation: int = Field(ge=0)
    round_id: str
    purpose: Purpose
    job_id: str | None = None
    status: Literal["succeeded", "failed", "cancelled"]
    started_at: dt.datetime
    finished_at: dt.datetime
    windows: tuple[str, ...]
    holdout_windows: tuple[str, ...] = ()
    genome_ids: tuple[str, ...]
    standings: tuple[Standing, ...] = ()
    findings: tuple[Finding, ...] = ()

    promoted: tuple[str, ...] = ()
    """`genome_id`s that cleared the promotion gate in this generation."""

    error: str | None = None


class PromotionRecord(_Frozen):
    """A candidate that earned a seat, and the evidence that earned it.

    Written whenever `app.evolution.promotion` moves a card out of `generated/`. The record is the
    audit trail: it names every generation the card cleared, both the selection and the holdout
    number, and whether the paper desk actually seated it -- so a card on the desk can always be
    traced back to the measurements that put it there.
    """

    genome_id: str
    agent_id: str
    purpose: Purpose
    promoted_at: dt.datetime

    generations: tuple[int, ...]
    """Every generation this genome cleared the gate in. Length >= `LoopConfig.promotion_consecutive`."""

    window_sets: tuple[tuple[str, ...], ...]
    """The window set used in each of those generations. Two identical sets do not count as two
    pieces of evidence -- see `PROTOCOL.md` section 6 and this package's `__init__` docstring."""

    median_excess: Decimal
    holdout_median_excess: Decimal | None
    q_value: float | None

    library_path: str
    """Where the card was written, relative to the repo root."""

    seated: bool
    """Whether the paper-desk roster overlay now names this card.

    **This is no longer "the loop seated it"; it is "a person had already approved it".** Promotion
    now files a `PendingSeat` instead of writing the overlay directly (see `pending_seats_path`), so
    this is `False` for every newly promoted card and only becomes `True` on a genome whose seat had
    already been approved before this promotion ran. The field is kept, rather than removed, because
    every `promotions.jsonl` row ever written carries it and a reader must be able to load them."""

    reason: str


SeatStatus = Literal["pending", "shelved", "seated", "rejected", "retired"]
"""Five states, two human decisions -- see `PendingSeat` for why one approval step was not enough.

```
loop promotes ──> [pending] ──decision 1──> [shelved] ──decision 2──> [seated]
                      │                         │
                      └──> [rejected]           └──> [retired]
```

`"pending"` is the only state a person has not yet acted on. Every other state is a human decision
and none of them re-open: `request_seat` refuses to re-file a genome already in any of the other
four, and `app.evolution.promotion._transition`'s legality table admits `shelved`/`rejected` only
from `pending` and `seated`/`retired` only from `shelved` -- there is no path back to `pending` and
no path between the two terminal branches.
"""


class PendingSeat(_Frozen):
    """One request from the loop for a person to decide what happens to a promoted card, resolved
    through the two-stage pipeline `SeatStatus` describes.

    Filed by `app.evolution.promotion` when a genome clears the gate; resolved only by explicit human
    decisions through `POST /api/competition/loop/pending-seats/{genome_id}/shelve`, `/seat`,
    `/retire` or `/reject`. See `pending_seats_path` for why this queue exists at all and why decided
    rows are kept rather than deleted.

    **Why two decisions and not one.** The queue used to have a single terminal step --
    `"approved"` meant "on the desk" -- and collapsing "worth keeping" into "commit it to the desk"
    was itself a defect: with only one yes/no to make, a reviewer working through a backlog either
    seats a card they only meant to keep an eye on, or lets a card that deserves attention sit
    unreviewed because the only "yes" on offer feels too big to click. That is exactly what happened
    on 2026-08-26 -- **22 cards were auto-approved onto the paper desk at 09:00:49 that day with no
    person ever having looked at them.** Splitting the decision in two gives a reviewer a place to put
    "I want to keep this, name it, watch it" that commits to nothing: `"shelved"` is the **review
    shelf** -- kept, named, observable, and it places no orders and is not on the desk. `"seated"` is
    the separate, second decision that a card should actually trade on the simulated paper desk, and
    it is the only state that writes `roster_overlay.json` (see `app.evolution.promotion.
    seat_pending_seat`). A card can sit on the shelf indefinitely, or leave it two ways: `"retired"`
    (never seated) or promoted on to `"seated"` -- both final, exactly as `"rejected"` at stage one is
    final. This is the second reason the two-stage split matters, not only the first: it makes "worth
    keeping" and "committed to the desk" two different, individually reversible-only-in-one-direction
    claims instead of one click that has to mean both at once.

    Every numeric field here is copied from the `Standing` the deterministic scorer already computed
    -- nothing in this model is re-derived, and nothing in it is a judgement. The judgement is the
    `status`, and only a person may move it out of `"pending"`.
    """

    genome_id: str
    agent_id: str
    purpose: Purpose

    requested_at: dt.datetime
    generations: tuple[int, ...]
    window_sets: tuple[tuple[str, ...], ...]

    median_excess: Decimal
    holdout_median_excess: Decimal | None
    q_value: float | None
    """Copied from the standing. Worth showing an approver beside the median: it is the
    multiple-comparison correction over *every* candidate the loop has ever run, so it is the number
    that says how much of this card's showing is explained by how many things were tried."""

    library_path: str
    reason: str
    """The promotion reason, verbatim -- which gate it cleared, on which window sets."""

    status: SeatStatus = "pending"
    decided_at: dt.datetime | None = None
    decided_note: str = ""
    """Free text from whoever approved or rejected it. Empty when still pending."""


# ---------------------------------------------------------------------------
# Configuration and status
# ---------------------------------------------------------------------------


class LoopConfig(_Frozen):
    """What the user chose when they pressed the button.

    Every default here is the conservative one. A caller that supplies nothing gets a loop that
    searches both the taxable and the Roth book, reserves two regimes as a holdout, and refuses to
    promote anything whose margin does not clear the measured noise floor twice.
    """

    purposes: tuple[Purpose, ...] = Field(default=(Purpose.TRADING, Purpose.ROTH), min_length=1)
    """Which books the loop breeds for, cycled round-robin -- one purpose per generation.

    One at a time rather than all at once because a generation is a round, a round holds the engine's
    single execution slot, and a card is only ever ranked against cards of its own purpose anyway
    (`app.tournament.results.build_leaderboard` takes a `purpose`).

    **`min_length=1`, because empty was accepted and produced a loop that could only die.**
    `app.evolution.loop._lanes_for` builds one lane per `(purpose, shape)` pair, so an empty tuple
    yields an empty lane list, and `_run` then indexes `lanes[(generation_number - 1) % len(lanes)]`
    -- a `ZeroDivisionError` on the first generation, surfacing as a loop that reports `"failed"` with
    a modulo error rather than as the request being wrong. Nothing sent this value while the start
    form had no purposes control; the control that now exists is a set of checkboxes, and every
    checkbox group can be emptied.

    **Savings is not in the default, and that is a decision rather than an oversight.**
    `docs/research/loop/01-what-the-search-found.md` point 6 found the savings purpose at zero
    coverage across 231 generations and asked which of the two it was. It was neither, exactly: the
    default here has always been trading and Roth, and until the purposes control landed there was no
    way to send anything else -- `buildLoopConfigFromDraft` did not carry the field, so every run the
    UI ever started took this default whatever the person intended (which is what
    `gen1873`/`gen1877`'s `purposes=['trading', 'roth', 'saving']` in the *goal* box was trying to
    say). The default stays as it is: savings cards are the sleeve-and-band shape the allocation lane
    breeds, they are the least developed of the three families
    (`strategy-program/SAVINGS-FAMILY.md`), and a purpose added to the default silently lengthens
    every lane cycle for every existing user of the button. It is now selectable, which is the part
    that was missing.
    """

    population: int = Field(default=10, ge=2, le=24)
    """Candidates per generation. Each one costs a full pass over every window, so this is the
    dominant term in how long an iteration takes.

    Ten rather than six because six is a thin field to correct across: the Benjamini-Hochberg step-up
    in `app.evolution.ledger` gets its power from the number of hypotheses actually tested, and a
    six-card generation spends most of its runtime on fixed per-window costs either way. The ceiling
    is 24, not unbounded -- a generation is one round holding the engine's execution slot, and a
    hundred-card generation would mean hours before the loop learns anything it can breed from."""

    max_workers: int = Field(default=4, ge=1, le=16)
    """How many cards run at once, in separate processes. 1 is fully serial.

    **Processes, not threads, and that is a measured choice rather than a stylistic one.** A card's
    runtime is thousands of small pandas operations inside a Python-level loop -- `AsOfMarket.close`
    alone is called ~1400 times per card -- which holds the GIL almost continuously. Measured on this
    machine over four cards on `chop-2015`: serial 9.7s, four threads 10.0s, a **0.97x** "speedup".
    The same eight cards under a process pool: 22.3s serial, 16.1s at 2 workers, 12.4s at 4, 10.8s at
    6 -- 2.06x, and that figure is a floor, measured on a batch short enough that interpreter startup
    dominated.

    This does **not** relax `strategy-program/DEFECTS.md` D3. That defect was two concurrent
    *rounds* writing a shared bar store, and `PROTOCOL.md` section 8 records it as closed at source,
    leaving concurrency "a resource decision, not a correctness one". What is parallel here is cards
    *within* one generation, all read-only against the bar store, while `app.tournament.jobs`'
    process-wide single-slot lock still admits exactly one generation at a time. Two loops still
    cannot run at once, and neither can a loop and a manually launched round.

    The default is 4 rather than the 6 that measured fastest: the host has 8 logical cores and 16 GB,
    each worker holds its own bar frames, and `PROTOCOL.md` section 8 already records a case where
    running several bar-loading processes alongside a round exhausted memory."""

    elite_count: int = Field(default=2, ge=1)
    """How many of a generation's standings breed into the next one."""

    windows: tuple[str, ...] = ()
    """Selection windows. Empty means `app.tournament.jobs.MAIN_WINDOWS` minus `holdout_windows`."""

    holdout_windows: tuple[str, ...] = ("q4-2018", "bull-2024")
    """Regimes selection never sees. Reported per candidate, consulted only by the promotion gate.

    **One drawdown and one rally, because the original all-drawdown holdout was measurably easier
    than the selection set rather than harder.** The default used to be `("covid", "q4-2018")` -- the
    two sharpest drawdowns in the main matrix -- on the reasoning that the failure a searcher most
    reliably manufactures is a card that is excellent right up until the market falls. That reasoning
    is sound; the implementation inverted it, and measuring 749 runs across twelve generations showed
    why:

    | window     | role      | median benchmark | median excess |
    |------------|-----------|-----------------:|--------------:|
    | gfc        | selection |          -56.23% |       +26.53% |
    | bear-2022  | selection |          -25.14% |        +9.61% |
    | chop-2011  | selection |           -0.05% |        +2.31% |
    | chop-2015  | selection |           -0.04% |        -0.08% |
    | bull-2024  | selection |          +14.00% |        -7.87% |
    | recent     | selection |          +20.62% |        -5.52% |
    | covid      | HOLDOUT   |           -8.71% |        +7.74% |
    | q4-2018    | HOLDOUT   |          -20.05% |       +11.83% |

    `excess = strategy_return - benchmark_return`, and these cards systematically capture about half
    the move in either direction, so excess is very nearly a linear function of which way the market
    went: **Pearson r = -0.978** between a window's median benchmark and its median excess, slope
    -0.46. A falling window hands out excess; a rising one takes it away. With both holdout windows
    falling and the selection set mixed (median benchmark -0.05%), holdout medians came in *above*
    selection medians -- the exact reverse of `EVOLUTION-LOOP.md` section 5's prediction 2, and for a
    reason that has nothing to do with whether the searcher is overfitting. It also made the gate's
    "holdout median is not negative" clause nearly free: **86.8%** of candidate-windows cleared it.

    Pairing one drawdown with one rally makes the holdout non-monotone in regime, so a card has to
    survive both directions rather than just benefit from one.

    **Swapped rather than widened, and that is load-bearing.** Adding `bull-2024` to the existing two
    would leave `MAIN_WINDOWS` (8) minus a 3-window holdout = a 5-window selection pool, which is
    exactly `MIN_ELIGIBLE_MAIN_WINDOWS`. `app.evolution.loop._resolve_selection_windows` documents
    what happens there: a pool at or under the floor "cannot drop a window without falling under it,
    so it is returned whole, unrotated, every time". Without rotation every generation of a lane runs
    the identical window set, and `app.evolution.promotion.evaluate_promotions` requires
    `promotion_consecutive` clearances on window sets that **differ** -- so a 3-window holdout would
    not have made promotion stricter, it would have made promotion impossible, silently. `covid`
    returns to the selection pool, keeping it at 6 and the rotation intact.
    """

    max_generations: int | None = Field(default=None, ge=1)
    """`None` -- the default, and what the button sends -- means run until stopped."""

    rank_by: str = "median"
    """Passed through to `build_leaderboard`. One of its `RANK_BY_CHOICES`."""

    promotion_margin_pp: Decimal = NOISE_FLOOR_PP
    """Median excess, in percentage points, a candidate must beat to have cleared the gate."""

    promotion_consecutive: int = Field(default=2, ge=1)
    """How many consecutive qualifying generations, on differing window sets, promotion requires."""

    promotion_max_shared_windows: int | None = Field(default=None, ge=0)
    """The most windows two of a promotion's evidence sets may have in common, or `None` for no ceiling.

    **What `None` means, stated plainly, because it is the shipped default and it is weaker than it
    reads.** `app.evolution.promotion._consecutive_evidence` counts a second qualifying generation as
    a second piece of evidence when its window set *differs as a set* from the first. That rule comes
    from `PROTOCOL.md` section 6(a) and it is the right rule for the failure it was written against --
    re-running a frozen, deterministic card on an already-seen window recomputes the same number, and
    `A-rotation` returned an identical +95.2786% twice under exactly that mistake. But "differs" is
    satisfied by one window in five. Measured over the loop's own generations: `app.evolution.loop.
    _resolve_selection_windows` builds each selection set by dropping exactly one window from a
    six-window pool, so **every** pair of consecutive appearances of a lane shares four of five
    windows, by construction rather than by accident. `docs/research/loop/01-what-the-search-found.md`
    point 2 is the write-up: every promotion this loop has ever made cleared a 21.2-point gate twice on
    window sets that were 80% the same measurement.

    Setting an integer here makes that explicit: a later generation's window set counts as new
    evidence only when it overlaps **every** set already counted by at most this many windows. `0`
    demands a complete swap.

    **A ceiling the configured rotation cannot reach is refused at `start_loop`, not discovered
    later.** `app.evolution.loop.achievable_shared_windows` computes the smallest overlap this config
    can actually produce, and `start_loop` raises `UnreachablePromotionCeiling` when the ceiling sits
    below it. That guard exists because this exact class of mistake has already been made once here in
    the other direction: `holdout_windows`' own docstring records that widening the holdout to three
    windows would have left a five-window pool at `MIN_ELIGIBLE_MAIN_WINDOWS`, which
    `_resolve_selection_windows` returns whole and unrotated, so every generation of a lane would run
    the identical set and promotion would have become impossible **silently** -- the loop searching
    forever, printing entirely reasonable standings, and never promoting anything. A gate that cannot
    be cleared must say so when it is set, not be inferred months later from an empty
    `promotions.jsonl`.

    With the shipped defaults (eight main windows, a two-window holdout, one dropped per appearance)
    the achievable floor is **4**, so `4` is the only value that changes nothing and `3` or less is
    refused until the window pool grows. That is not a reason to leave this `None`; it is the finding.
    """

    seat_on_paper_desk: bool = True
    """Whether a promoted card is also written into the paper-desk roster overlay.

    The desk is simulated and holds no real money, so this is on by default. It remains a switch
    because a promotion is a claim about a strategy and a seat is a claim about a portfolio, and the
    two are worth being able to separate.
    """

    use_news: bool = True
    """Whether `app.evolution.news_signal` may bias a fraction of each generation's universes.

    Off makes the loop a pure function of stored bars and its seed. On makes it depend on what the
    news providers returned at proposal time, which is not reproducible later -- so a news-derived
    genome records the tickers it was handed and why, and the loop's determinism claim is scoped to
    `use_news=False`.
    """

    news_fraction: float = Field(default=0.25, ge=0.0, le=1.0)
    """Share of each generation drawn from the news-biased pool, when `use_news`."""

    seed: int = Field(default=0, ge=0)
    """Root RNG seed. Two loops with the same seed and `use_news=False` propose the same candidates."""

    goal: str = ""
    """What the person starting this loop is trying to find out, in their own words.

    Recorded verbatim in every generation's `PLAN.md` and shown on the loop panel, so a run months
    later can be read against the question it was started to answer -- the same job a round's
    `BRIEF.md` does for a hand-designed round.

    **This text does not steer the search, and saying so plainly matters.** No model is wired into
    the backend, and `AGENTS-INTEGRATION-PLAN.md` section 0 would keep one out of the scoring path
    anyway; a deterministic proposer cannot act on a sentence. What *does* steer the search is
    `focus_symbols`, `avoid_symbols` and `rank_by`, which are the machine-readable half of the same
    intent. The loop reports on the goal by checking whether the quantity `rank_by` names improved
    against the previous generation in the same lane -- see `app.evolution.feedback`'s `"goal"`
    finding -- which is a real verification of a measurable claim, not an interpretation of the
    prose."""

    focus_symbols: tuple[str, ...] = ()
    """Tickers every proposed candidate must hold.

    The machine-readable half of `goal`: "test ideas built around SMH and QLD" is a sentence a
    proposer cannot act on, and this is the same instruction in a form it can. Validated at proposal
    time against the lane's own pool -- a symbol that is not in the pool for the purpose being bred,
    or that would break Roth disjointness, is refused with `ProposalRejected` rather than dropped,
    because silently ignoring half of what someone asked for is worse than saying no.

    Counts against a candidate's 12-symbol universe limit, so a long list leaves the searcher little
    room to actually search."""

    avoid_symbols: tuple[str, ...] = ()
    """Tickers no proposed candidate may hold. Applied after `focus_symbols`; naming the same symbol
    in both is refused rather than resolved in either direction."""

    use_agent: bool = False
    """Whether `app.agents` designs each generation instead of the seeded RNG.

    Off by default, and that is a deliberate default rather than caution about quality: with it on, a
    generation is no longer replayable from `seed`, and it costs money on every iteration of a loop
    that runs forever. Turning it on is a choice to trade reproducibility and spend for a proposer that
    can actually read the previous generation's findings and the stated `goal`.

    When on, the agent is still never load-bearing. Missing credentials, an exhausted budget, a
    refusal, or a malformed response all fall back to the deterministic proposer for that generation
    and are recorded in the loop log -- the search gets worse, it does not stop."""

    agent_budget_usd: Decimal = Decimal("10.00")
    """Hard ceiling on model spend for one loop run, across every agent call it makes.

    The loop has no natural end, so an uncapped per-generation model call is an uncapped bill. Once
    this is reached the loop keeps running on the deterministic proposer and logs that it has stopped
    calling the model; it never stalls and never silently keeps spending. Estimated from
    `app.agents`' own price table, which is an accounting aid rather than a billing figure."""

    agent_model: str = ""
    """Override `app.agents.models.DEFAULT_MODEL`. Empty means the default."""

    use_reviewer: bool = False
    """Whether `app.agents.reviewer` writes a `GenerationReview` after each generation is scored, and
    its `ProposedAmendment`s and elite-carve-out notes are folded into the *next* generation of the
    same lane -- see `app.evolution.amend.apply_amendments` and `app.evolution.loop`'s wiring for
    exactly how.

    Off by default, for the same reason `use_agent` is off by default: a review is a model call, so it
    costs money on every generation it runs. It spends against `agent_budget_usd`, not a second budget
    -- that field is documented as a ceiling on "model spend for one loop run, across every agent call
    it makes," designer and reviewer alike, because the loop has one bill, not one per collaborator.
    With this off, a generation is scored, promoted and logged exactly as it was before this field
    existed: no review is requested, no `gen{N:04d}/REVIEW.json` is written, and `LoopConfig` never
    changes out from under a running lane.

    When on, the reviewer is never load-bearing, exactly like the designer: `AgentUnavailable`,
    `BudgetExhausted`, or any other exception it raises is caught, logged, and the generation's own
    already-computed outcome is unaffected -- see `app.evolution.loop`'s wiring for why a failed review
    is also deliberately kept out of the consecutive-failure circuit breaker."""

    cooldown_seconds: float = Field(default=0.0, ge=0.0)
    """Pause between generations. Exists so a long-running loop can be throttled without stopping it;
    the engine's own single-slot lock is what prevents overlap, not this."""


class LoopStatus(_Frozen):
    """The whole loop, as the button's panel renders it and `GET /api/competition/loop` returns it.

    A snapshot taken under the supervisor's lock, never a live view of mutable state -- the same
    contract `app.tournament.jobs.JobStatus` has, and for the same reason.
    """

    loop_id: str
    state: LoopState
    phase: LoopPhase
    config: LoopConfig

    generation: int
    """The generation currently being worked on, or the last one completed when not running."""

    completed_generations: int

    candidates_tested: int
    """Distinct genomes the loop has run, ever -- the multiple-comparison denominator."""

    started_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None
    stopped_at: dt.datetime | None = None

    current_round_id: str | None = None
    current_job_id: str | None = None
    current_purpose: Purpose | None = None

    best: Standing | None = None
    """The best standing seen across every generation, by selection median excess."""

    promotions: tuple[PromotionRecord, ...] = ()

    history: tuple[GenerationOutcome, ...] = ()
    """Most recent first, bounded. The full history is on disk under :func:`loop_root`."""

    log: tuple[str, ...] = ()
    """Last lines of the supervisor's own log, newest last."""

    error: str | None = None
    """Set only when the supervisor itself died. A single generation failing is recorded on that
    generation's `GenerationOutcome` and the loop continues."""

    latest_review_headline: str | None = None
    """The most recent `GenerationReview.direction.headline` this loop has produced, or `None` when
    `LoopConfig.use_reviewer` is off or no review has landed yet. The full review is never inlined
    here -- it is on disk at `generation_review_path(settings, generation)` -- this is only enough for
    the loop panel to show that a review happened and roughly what it said."""

    latest_review_verdict: str | None = None
    """`GenerationReview.verdict` alongside `latest_review_headline`, same lifetime and same reason
    for being a plain string rather than the full review object."""

    amendments_applied: tuple[AmendmentRecord, ...] = ()
    """Every amendment actually applied so far this loop run, across every lane -- accumulated the
    same way `LoopStatus.promotions` accumulates, and for the same reason: the full audit trail is
    `data/loop/amendments.jsonl` (append-only, survives a restart), this is a bounded-by-the-run
    in-memory echo of it for the panel."""


# ---------------------------------------------------------------------------
# Amendments -- a reviewer's proposed changes to the next generation's LoopConfig
# ---------------------------------------------------------------------------


class AmendmentRecord(_Frozen):
    """One amendment attempt against a `LoopConfig`, applied or refused -- one row of the append-only
    audit trail at `amendments_path(settings)` (`data/loop/amendments.jsonl`). Written only by
    `app.evolution.amend.apply_amendments`, which is the sole writer of that file.

    Every attempt is recorded, not only the ones that succeeded -- a refused amendment is exactly as
    much a part of the record as an applied one, the same "record everything, not just the wins" rule
    `app.evolution.loop._write_outcome_file` already applies to a failed generation's
    `GenerationOutcome`. `old_value`/`new_value` are recorded as strings rather than the field's native
    type: `LoopConfig` holds `Decimal`-, `tuple[str, ...]`- and enum-valued fields with no native JSON
    representation, the same reason `app.evolution.ledger._entry_to_json` stringifies `Decimal` rather
    than leaving it typed.
    """

    generation: int = Field(ge=0)
    """The generation this amendment was proposed *for* -- the reviewer that produced it reviewed this
    generation's own outcome. Its effect, if applied, starts the *next* generation of the same lane;
    see `app.evolution.amend`'s module docstring for why nothing about this record is retroactive."""

    purpose: Purpose
    field: str
    old_value: str
    new_value: str

    reason: str
    """The reviewer's own stated reason for proposing this amendment, copied from
    `ProposedAmendment.reason` verbatim -- never rewritten, so a reader of the audit trail sees the
    model's own justification rather than this package's paraphrase of it."""

    applied_at: dt.datetime

    applied: bool
    """`True` if this amendment was accepted and folded into the next generation's `LoopConfig` for
    its lane, `False` if `app.evolution.amend.apply_amendments` refused it -- see that module's own
    docstring for the two distinct ways a refusal happens (the amended `LoopConfig` itself failing
    validation, or the holdout/selection window overlap invariant)."""


class RefusedAmendment(_Frozen):
    """A proposed amendment `app.evolution.amend.apply_amendments` refused, in the smaller shape a
    caller needs to explain the refusal without the full audit record -- see `AmendmentRecord` for
    that. Every `RefusedAmendment` returned from one call also has a matching `AmendmentRecord`
    (`applied=False`) written to `amendments_path(settings)`; this type is the in-memory echo of that
    write for the caller, not a second source of truth."""

    field: str
    value: str
    reason: str


class AmendmentOutcome(_Frozen):
    """What one call to `app.evolution.amend.apply_amendments` did: which amendments landed, which
    were refused and why, and the `LoopConfig` the next generation of that lane should actually run
    with.

    `config` is never the input `LoopConfig` left unchanged by the refusals -- it is that config with
    every amendment that *did* apply folded on top, in order. A caller that ignores
    `applied`/`refused` and reads only `config` still gets the right next-generation configuration; the
    two tuples exist so a reader (the loop's own log, or `amendments.jsonl` on disk) can say what
    changed and why, not because `config` alone would be missing anything a search needs.
    """

    applied: tuple[AmendmentRecord, ...] = ()
    refused: tuple[RefusedAmendment, ...] = ()
    config: LoopConfig


# ---------------------------------------------------------------------------
# On-disk conventions
# ---------------------------------------------------------------------------


def loop_root(settings: Settings) -> Path:
    """Where the loop keeps its own state: `data/loop/`.

    A sibling of `data/rounds/`, not a child: the rounds tree is the programme's record of what was
    run and is read by the Competition page, while this tree is the searcher's record of *why* -- the
    genomes, the ledger, the per-generation plans. Derived from `settings.data_dir` rather than added
    to `Settings` because nothing outside this package needs to configure it.
    """
    return settings.data_dir / "loop"


def generated_tier_dir(settings: Settings) -> Path:
    """`data/loop/generated/` -- where proposed cards are written.

    **Under `data/`, not under `backend/app/paper/library/`, and that move was forced by a real
    failure rather than chosen on tidiness.** The first draft put generated cards in the library
    beside the hand-authored tiers, which works on a developer's checkout and cannot work in the
    container: `docker-compose.yml` bind-mounts `./data` and nothing else, so the library path lives
    inside the read-only image layer. A loop started in Docker proposed cards, failed to write them,
    and recorded the generation as failed -- **1,644 times out of 1,673**, every one of them
    `OSError: [Errno 30] Read-only file system`, while the supervisor dutifully carried on because a
    failed generation is not supposed to stop the loop.

    Putting them here also makes the tree honest about what they are: every other piece of the
    searcher's working state (genomes, plans, per-generation outcomes, the news cache, the loop's own
    rounds) is already under `data/loop/`, and `.gitignore` excludes that whole directory bar three
    audit files. A card only becomes a library member by being promoted into `candidates/`, which
    `app.evolution.promotion` still does and which is a tracked, reviewable move.

    `app.tournament.jobs` resolves the `generated` tier from here too, so a card proposed by the loop
    is still addressable by `agent_id` from `POST /api/competition/jobs`.
    """
    return settings.data_dir / "loop" / GENERATED_TIER


def roster_overlay_path(settings: Settings) -> Path:
    """The paper desk's loop-owned roster overlay: `data/loop/roster_overlay.json`.

    A file rather than an edit to `app.paperdesk.desk`'s module constants. Those constants are the
    human roster, and a running loop must not rewrite Python that is already imported; the overlay is
    additive, read at request time, and deleting it restores exactly the hand-authored desk.
    """
    return loop_root(settings) / "roster_overlay.json"


def pending_seats_path(settings: Settings) -> Path:
    """The approval queue standing between a promotion and a paper-desk seat:
    `data/loop/pending_seats.json`.

    **Why an approval queue exists at all.** Promotion used to seat a card on the paper desk the
    moment it cleared the gate twice, with `LoopConfig.seat_on_paper_desk` as the only control -- and
    that control is a property of the *run*, decided before any candidate existed, not a judgement
    about any particular card. Left running, the loop seated **25 cards** (18 roth, 7 trading) that
    no person ever looked at. The gate is a statistical floor, not an endorsement: it says a card's
    median excess cleared a measured noise threshold twice on differing window sets, which is exactly
    what `EVOLUTION-LOOP.md` section 5 predicts will happen by luck alone often enough to matter once
    a searcher is proposing without limit.

    So the loop now *requests* a seat and a person grants it. The desk is simulated and holds no real
    money, but it is the surface this programme treats as "what we would actually run", and an
    unattended search writing into it directly makes that surface mean less than it should.

    **The file keeps decided requests, not just undecided ones.** An approval queue that deletes
    rejected rows cannot answer "did anyone consider this card, and what did they decide" -- the
    question a reader has six months later is not what is pending now. Rows carry a `status` and
    stay, which also makes a re-request of a previously rejected genome visible as a re-request.
    Tracked in git for the same reason `promotions.jsonl` and `amendments.jsonl` are: it records a
    decision that outlived the run that produced it.
    """
    return loop_root(settings) / "pending_seats.json"


def amendments_path(settings: Settings) -> Path:
    """`data/loop/amendments.jsonl` -- the append-only record of every amendment a reviewer has ever
    proposed, applied or refused. Written only by `app.evolution.amend.apply_amendments`; see that
    module's own docstring for why this file exists at all (a self-modifying loop with no durable
    record of what it changed, and why, is not auditable) and `.gitignore`'s `data/loop/*` block for
    why this is one of the tracked exceptions to that directory's own working-tree rule.
    """
    return loop_root(settings) / "amendments.jsonl"


def generation_review_path(settings: Settings, generation: int) -> Path:
    """`gen{N:04d}/REVIEW.json` -- this generation's reviewer output, written beside its `PLAN.md` and
    `OUTCOME.json` under the same generation directory.

    **Deliberately not a field on `GenerationOutcome`.** `GenerationOutcome` (this module) is read by
    a third worker's history API and by the existing frontend, and a `GenerationReview`-typed field
    would force `app.evolution.models` to import `app.agents.review_models` unconditionally --
    exactly the hard dependency `app.evolution.loop.default_collaborators` deliberately avoids for the
    designer, guarding that import in a `try/except ModuleNotFoundError` so a missing `app.agents`
    package degrades the loop rather than breaking it. `app.evolution.models` importing `app.agents`
    at module scope would make that guard pointless -- the package would already be required just to
    import this one. So the review is its own file instead, written and read independently of
    `GenerationOutcome`, and `app.evolution.models` never imports anything from `app.agents`.
    """
    return loop_root(settings) / f"gen{generation:04d}" / "REVIEW.json"


_ROUND_SEQUENCE_RE = re.compile(r"^r(\d+)")


def next_round_sequence(rounds_root: Path) -> int:
    """One past the highest `r<N>` ordinal already present in the rounds tree.

    The loop mints `r{N}-auto-{timestamp}` ids so that `app.tournament.results.round_sequence` orders
    its rounds against the human programme's on the same axis, and so that a glance at a round id
    says whether a person or the searcher designed it. Returns 1 for an empty tree.
    """
    highest = 0
    if rounds_root.is_dir():
        for child in rounds_root.iterdir():
            if not child.is_dir():
                continue
            match = _ROUND_SEQUENCE_RE.match(child.name)
            if match is not None:
                highest = max(highest, int(match.group(1)))
    return highest + 1
