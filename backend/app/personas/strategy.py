"""Persona methodology -> the repo's fixed rule vocabulary -> a real, validated `StrategyCard`.

Phase 7c of `docs/INFLUENCER-CONTRACT.md` ("persona -> strategy card", direction b of Phase 7's
cross-pollination): a persona's extracted METHODOLOGY (`app.personas.models.PersonaProfile.
methodology`, Phase 7a) is mapped, by one model call, onto `app.evolution.models.RuleShape` and its
trait grammar, then rendered and validated through the exact same machinery the evolution loop's own
agent-designed genomes go through (`app.evolution.proposer.card_for`) -- never free-form DSL, never a
hand-rolled validator living beside this one. Honest by construction, per the contract:

1. Only a persona WITH a described methodology can be mapped -- an empty methodology (a pure macro
   commentator) is refused before any model call, never invented around.
2. It is "inspired by", never faithful: the model chooses a shape and period/risk traits informed by
   the methodology's prose, not a reproduction of what the persona literally does tick for tick.
3. A mapping the real card validators reject is reported (`mapped=False, reason=...`), never patched
   into validity -- the same "validate, never repair" line `app.agents.designer` draws for the
   evolution loop's own agent path.
4. Every mapped draft carries a fixed `caveat`: an exploration lens, not expected to beat this
   programme's own null result, never advice.

**There is no `app.evolution.models.make_genome`.** The task brief that shaped this module named one
at "models.py:~348" with the signature `make_genome(origin=..., purpose=..., universe=..., traits=
{...}) -> Genome`; that function does not exist anywhere in this repository (verified by search), and
line ~348 of `app.evolution.models` is `genome_id_for`, not a genome constructor. What DOES exist, and
is the precedent this module follows instead, is `app.agents.designer._to_genome`: the evolution
loop's own agent-origin path builds a `Genome` by calling the public, pinned `Genome` model directly
(`app.evolution.models.Genome`) with an id minted by the equally public `genome_id_for`, and a
content-derived pseudo-seed standing in for the RNG state an agent-designed candidate never had. This
module does the same thing for the same reason -- an agent-proposed, `origin="agent"` genome that was
never drawn from a seeded `random.Random` -- rather than inventing a second, competing way to build a
`Genome`. See `_build_genome` below and `_pseudo_seed`'s own docstring, copied from `designer.py`'s
reasoning almost verbatim because the situation is identical.

**Why a model call and not a deterministic heuristic.** Reading free-form methodology prose ("uses a
14-day RSI on the daily chart, cuts losers at -8%, holds a few weeks") and choosing which of eight
structurally different rule shapes it resembles, and what period/risk numbers are consistent with what
was described, is exactly the kind of judgement call `app.agents.designer`'s own module docstring
already draws the line at for the evolution loop's agent path: a model may "propose, name, argue and
select" (never emit a *measurement* -- see `app.agents.models`'s module docstring), and choosing a
`rule_shape` plus stop/target/hold/sizing traits from a description is a proposal, not a measurement.
No deterministic function in this codebase does that mapping, and inventing a bespoke heuristic parser
for influencer prose would only be a worse, unaudited version of the same judgement call.

**`desk_only`/`designed_through` need no special handling here, and that is worth stating explicitly**
because the task brief anticipated having to set them. `app.evolution.proposer._rules_card` hardcodes
`designed_through=app.tournament.models.DESIGN_THROUGH` (2026-02-13) on every card it builds, with no
parameter to override it, and leaves `desk_only` at its model default of `False`. `StrategyCard.
_cannot_claim_to_have_seen_the_trading_window`'s non-`desk_only` branch only rejects a `designed_through`
*after* `DESIGN_THROUGH` -- and `DESIGN_THROUGH` itself trivially satisfies "not after `DESIGN_THROUGH`"
-- so every card `card_for` returns already clears the anti-look-ahead validator unconditionally, for
any genome, `origin="agent"` included. There is nothing for this module to set, and no seam in
`card_for` to set it through even if there were; see the module's own docstring on why nothing in
`app.evolution`/`app.tournament` is edited to add one.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agents.client import call_structured
from app.agents.models import DEFAULT_MODEL, AgentBudget, AgentCall, AgentRole
from app.config import Settings
from app.evolution.models import (
    RULE_SHAPES,
    RULES_PERIOD_BOUNDS,
    Genome,
    ProposalRejected,
    RuleShape,
    genome_id_for,
)
from app.evolution.proposer import card_for
from app.personas.instruments import classify, is_tradeable, suggest_proxy
from app.personas.models import (
    PersonaProfile,
    ProfileClaim,
    SavedStrategyDraft,
    StrategyCardDraft,
    persona_dir,
)
from app.tournament.purposes import Purpose

__all__ = [
    "DraftResult",
    "draft_strategy_card",
    "list_saved_drafts",
    "save_draft",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixed vocabulary this module speaks in
# ---------------------------------------------------------------------------

#: `app.evolution.models.RULE_SHAPES`' own vocabulary restated as one line each, for the prompt. Kept
#: here rather than reused from `app.evolution.ruleforms.describe` (which needs concrete fast/slow/
#: regime_ma numbers the model has not chosen yet) -- this is a *description of the shape*, not a
#: rendering of one instance of it.
_RULE_SHAPE_GUIDE: dict[RuleShape, str] = {
    "ma-crossover": (
        "a fast EMA crossing above a slower EMA while price sits above a long-horizon SMA regime "
        "filter -- a classic same-family moving-average crossover"
    ),
    "momentum-state": (
        "staying in an already-established uptrend (fast EMA above slow EMA, RSI over 55) rather than "
        "trading an edge -- enters later than a crossover, holds through more whipsaw"
    ),
    "rsi-pullback": (
        "buying a short-term dip (RSI under 40) while price still holds above its long-run SMA, exiting "
        "once RSI recovers past 60 -- mean reversion inside an uptrend"
    ),
    "band-reversion": (
        "buying a dip below the lower Bollinger Band while still above the long-run SMA, exiting back at "
        "the band's own midline -- the same pullback idea stated in price rather than an oscillator"
    ),
    "channel-breakout": (
        "buying a breakout above the recent confirmed swing high, exiting on a break of the matching "
        "swing low -- a structural, price-level breakout"
    ),
    "band-breakout": (
        "buying a breakout above the upper Bollinger Band inside a trend filter -- breakout stated as "
        "volatility expansion rather than a swing-high price level"
    ),
    "macd-cross": (
        "a MACD line crossing above its own signal line inside a long-horizon SMA trend filter -- the "
        "oscillator counterpart of a moving-average crossover"
    ),
    "vol-compression": (
        "buying an established uptrend while realised volatility (ATR relative to price) is unusually "
        "low, exiting when volatility expands or the trend filter breaks"
    ),
}

if set(_RULE_SHAPE_GUIDE) != set(RULE_SHAPES):  # pragma: no cover -- import-time invariant
    raise RuntimeError(
        "_RULE_SHAPE_GUIDE and app.evolution.models.RULE_SHAPES disagree: "
        f"only in the guide {sorted(set(_RULE_SHAPE_GUIDE) - set(RULE_SHAPES))}, "
        f"only in RULE_SHAPES {sorted(set(RULE_SHAPES) - set(_RULE_SHAPE_GUIDE))}. Mirrors the same "
        "check app.evolution.ruleforms runs between its own RENDERERS table and this vocabulary, so "
        "a shape added to one cannot silently leave the prompt describing only the old seven."
    )

#: `Genome.universe`'s own cap, restated here for the same reason every other module in this codebase
#: that builds a universe restates it rather than importing a private constant from `app.evolution.
#: proposer` -- see that module's own `_MAX_UNIVERSE_SIZE` docstring for the precedent.
_MAX_UNIVERSE_SIZE = 12

#: How much of the model's own `rationale` survives into `Genome.notes` -- the same bound
#: `app.agents.designer._NOTES_LIMIT` applies to an agent-designed genome's notes, for the same
#: reason: long enough to keep the substance, short enough that a log line does not become a
#: paragraph.
_NOTES_LIMIT = 480

_CAVEAT = (
    "Inspired by this persona's described methodology, not a faithful reproduction of what they "
    "actually trade -- the model chose a rule shape and parameters consistent with the technique they "
    "described, mapped onto this programme's own fixed rule vocabulary. Per this repo's own multi-round "
    "search record, a card built this way is not expected to beat the null. This is an exploration "
    "lens over the persona's stated methodology, never investment advice."
)

#: See `app.personas.summarize._ROLE`/`app.personas.consolidate._ROLE`'s own docstrings for why every
#: model call this feature makes archives under the `AgentRole` Literal's shared `"swarm_worker"`
#: member rather than a persona-specific one.
_ROLE: AgentRole = "swarm_worker"


# ---------------------------------------------------------------------------
# The model's output shape
# ---------------------------------------------------------------------------


class _CardMapping(BaseModel):
    """What the model returns for one persona -> strategy-card mapping call.

    Deliberately does not carry a `universe` field: per the contract, the universe is the persona's
    own current-bullish tickers, supplied by the caller and never chosen by the model (see the module
    docstring's point 2 -- the model's job is the rule shape and its parameters, not which tickers to
    trade). Every field here becomes one `Genome.traits` key for a `"rules"`-shape genome, in exactly
    the layout `app.evolution.proposer._rules_card` reads (see that function's `traits[...]` lookups)
    and `app.agents.designer._RULES_TRAIT_KEYS` already names for the evolution loop's own agent path
    -- ten keys, exactly `app.evolution.models.MAX_FREE_PARAMETERS`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    rule_shape: RuleShape
    """Which of the eight shapes (`app.evolution.models.RULE_SHAPES`) best matches the described
    technique -- see `_RULE_SHAPE_GUIDE` for what each one tests."""

    fast: int
    slow: int
    regime_ma: int
    """The three period traits every shape renders from. Must satisfy `fast < slow < regime_ma`,
    each inside `app.evolution.models.RULES_PERIOD_BOUNDS` -- not enforced here (this schema only
    checks the wire types), but re-checked, and refused as a rejected mapping rather than repaired,
    by `app.evolution.proposer.card_for` -- see `draft_strategy_card`'s own docstring for why a bad
    mapping is reported, never patched."""

    stop_loss_pct: Decimal
    """Hard stop as a fraction of one below entry, e.g. `Decimal("0.08")` for an 8% stop -- informed
    by any stop/risk rule the methodology described."""

    take_profit_pct: Decimal | None = None
    """Target as a fraction of one above entry, or `None` when the methodology describes no fixed
    target (a time-stop-only or discretionary-exit style)."""

    max_hold_days: int = Field(ge=1, le=252)
    """Time stop in trading sessions, informed by any stated holding-period habit."""

    max_positions: int = Field(ge=1, le=8)
    position_pct: Decimal
    """Fraction of starting equity committed per position -- `position_pct * max_positions` must not
    exceed one whole book (re-checked, not enforced here, by `StrategyCard`'s own validator)."""

    rank_key: str | None = None
    """Optional ranking-key expression (`app.rules.grammar.parse_ranking` syntax, e.g. `"rsi(14)"`)
    deciding which qualifying names take the scarce slots when more names qualify than there is room
    for. `None` leaves the tiebreak at universe order, exactly as an unset `StrategyCard.rank_by`
    already does for every card that predates this field."""

    rationale: str
    """How the methodology informed this specific shape and these specific parameters, in the model's
    own words -- becomes `StrategyCardDraft.rationale` verbatim."""

    citations: tuple[str, ...] = ()
    """The methodology claims' own `note_id`s this mapping actually drew on. Filtered against the
    real citation set by `draft_strategy_card`, exactly as `app.personas.consolidate._filter_claims`
    filters a profile claim's citations -- except here a mismatched id is dropped from the list
    itself rather than voiding a whole claim, since `StrategyCardDraft.citations` is a flat list of
    ids, not a list of cited claims."""

    techniques_total: int = Field(ge=0)
    """How many distinct techniques the model identifies in the persona's described methodology
    (entry/exit triggers, sizing habits, timeframe conventions, and the like) -- the denominator for
    `StrategyCardDraft.fidelity`. `techniques_represented` is not a separate field: it is derived by
    `draft_strategy_card` as `techniques_total - len(unrepresentable)`, so the model cannot report
    numbers that disagree with the list it actually names below."""

    unrepresentable: tuple[str, ...] = ()
    """Short descriptions of methodology techniques the CHOSEN rule shape cannot express -- e.g.
    "opening-range box", "multi-timeframe confirmation", "options-based hedging" -- named explicitly
    so a low fidelity score is legible rather than a bare fraction. An empty tuple means the model
    judges the chosen shape as expressing everything it identified; that is a claim about this
    fixed 8-shape DSL's limits, never invented to pad the count, and never a request to add DSL
    support."""


# ---------------------------------------------------------------------------
# What this module hands back
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DraftResult:
    """What `draft_strategy_card` returns: the draft the `/strategy-card` endpoint serves, plus the
    model call(s) that produced it for the caller's own cost/audit accounting -- the same split
    `app.personas.consolidate.ConsolidationResult` makes between its persisted draft and its calls.

    `calls` is empty exactly when `draft.mapped is False` for a reason that needed no model call at
    all (no methodology, or no bullish tickers) -- see `draft_strategy_card`'s own docstring. A mapping
    the card validators went on to reject still made one real, billed call, so `calls` has one entry
    even though `draft.mapped` ends up `False`.
    """

    draft: StrategyCardDraft
    calls: tuple[AgentCall, ...]


# ---------------------------------------------------------------------------
# Universe -- the caller's bullish tickers, never the model's choice
# ---------------------------------------------------------------------------


def _universe_from_bullish(bullish_tickers: Sequence[str]) -> tuple[str, ...]:
    """`bullish_tickers` uppercased, stripped, deduplicated (first occurrence wins), and capped at
    `_MAX_UNIVERSE_SIZE` -- the rest dropped, per the contract's own "capped at 12 (drop the rest)"
    instruction. An empty or blank-only input yields an empty tuple, which `draft_strategy_card`
    checks before ever building a prompt."""
    seen: dict[str, None] = {}
    for raw in bullish_tickers:
        symbol = raw.strip().upper()
        if not symbol:
            continue
        seen.setdefault(symbol, None)
    return tuple(seen)[:_MAX_UNIVERSE_SIZE]


def _split_tradeable(universe: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """`universe` split into `(tradeable, dropped)` per `app.personas.instruments.is_tradeable` --
    only `"equity"`/`"etf"` symbols are something a reader could act on through an ordinary equities
    broker, per that module's own docstring. Order is preserved within each half."""
    tradeable: list[str] = []
    dropped: list[str] = []
    for symbol in universe:
        (tradeable if is_tradeable(classify(symbol)) else dropped).append(symbol)
    return tuple(tradeable), tuple(dropped)


def _non_tradeable_reason(dropped: Sequence[str]) -> str:
    """A `mapped=False` reason naming every symbol in `dropped` (already known non-tradeable), its
    real instrument kind, and a tradeable proxy when `app.personas.instruments.suggest_proxy` has
    one -- e.g. "GC is a future; try GLD" -- so the caller sees exactly why nothing was mapped and
    what an equities broker could hold instead, rather than a bare "could not map" message."""
    parts = []
    for symbol in dropped:
        kind = classify(symbol)
        article = "an" if kind[:1] in "aeiou" else "a"
        proxy = suggest_proxy(symbol)
        detail = f"try {proxy}" if proxy else "no tradeable proxy available"
        parts.append(f"{symbol} is {article} {kind}; {detail}")
    return "no tradeable tickers in this persona's bullish universe -- " + "; ".join(parts)


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a quantitative strategy translator. You are given one financial-market \
influencer's own described trading METHODOLOGY -- named indicators, timeframes, entry/exit triggers, \
stop-loss / take-profit / position-sizing / risk habits -- extracted from things they actually said. \
Your job is to map that description onto ONE rule shape from a FIXED vocabulary this trading research \
programme already uses, choosing the shape and its numeric parameters so they are CONSISTENT with what \
was described. You are not designing a new strategy from scratch and you are not reproducing the \
persona's trading tick for tick -- you are translating their described technique into this programme's \
own vocabulary, as an exploration, honestly labelled as "inspired by" rather than faithful.

RULE SHAPES. Choose exactly one `rule_shape` from:
{shape_guide}

PERIOD TRAITS. `fast`, `slow`, `regime_ma` are trading-session periods every shape is built from. They \
MUST satisfy fast < slow < regime_ma, and each must fall inside its own bound: fast in [{fast_lo}, \
{fast_hi}], slow in [{slow_lo}, {slow_hi}], regime_ma in [{regime_lo}, {regime_hi}]. Choose values \
consistent with any timeframe the methodology actually names (a "daily chart" swing style calls for \
different periods than an "intraday" or "weekly" one); when the methodology names no timeframe, use \
reasonable mid-range defaults for the chosen shape.

RISK AND SIZING. `stop_loss_pct` and `take_profit_pct` (optional) are fractions of one, e.g. 0.08 for \
an 8% stop -- informed by any stop, target, or reward:risk ratio the methodology states; leave \
`take_profit_pct` null when no target discipline was described. `max_hold_days` is a time stop in \
trading sessions, informed by any stated holding-period habit. `max_positions` (1-8) and `position_pct` \
(a fraction of one, `position_pct * max_positions` must not exceed 1) describe how many names are held \
at once and how much of the book each one gets -- informed by any stated position-sizing or \
diversification habit; use conservative, moderate defaults (a handful of positions, position_pct well \
under the one-name maximum) when the methodology says nothing about sizing.

`rank_key` is optional rule-DSL text (e.g. "rsi(14)", "close / sma(200)") naming which qualifying names \
get priority when more names qualify than there is room for -- leave it null unless the methodology \
clearly implies a ranking preference.

CITATIONS. `citations` must be drawn only from the exact note_id values given to you below, and only \
those that actually informed your choice of shape and parameters -- never invent one, and never cite \
one whose content you did not actually use.

FIDELITY. `techniques_total` is how many distinct techniques you can identify in the methodology \
below (an indicator, a timeframe convention, an entry/exit trigger, a sizing or risk habit each count \
separately). `unrepresentable` lists, in a few words each, the ones the rule shape you chose CANNOT \
express -- this fixed 8-shape vocabulary has no opening-range box, no multi-timeframe confirmation, no \
options overlay, and no discretionary judgement call, so name whatever you had to drop rather than \
silently ignore. Leave `unrepresentable` empty only when the chosen shape genuinely covers everything \
you identified -- do not pad `techniques_total` to manufacture a gap, and do not omit a real one to \
avoid reporting it.

RATIONALE. Explain, in a few sentences, how the methodology described below led to this specific shape \
and these specific parameters. Never claim this card will perform well, and never state a number \
(a return, a win rate, a backtest result) -- you are proposing a hypothesis to test, not reporting a \
measurement.

Respond with only the fields the schema asks for -- no extra commentary before or after."""


def _format_shape_guide() -> str:
    return "\n".join(f"- {shape}: {desc}" for shape, desc in _RULE_SHAPE_GUIDE.items())


def _build_system_prompt() -> str:
    fast_lo, fast_hi = RULES_PERIOD_BOUNDS["fast"]
    slow_lo, slow_hi = RULES_PERIOD_BOUNDS["slow"]
    regime_lo, regime_hi = RULES_PERIOD_BOUNDS["regime_ma"]
    return _SYSTEM_PROMPT.format(
        shape_guide=_format_shape_guide(),
        fast_lo=fast_lo, fast_hi=fast_hi,
        slow_lo=slow_lo, slow_hi=slow_hi,
        regime_lo=regime_lo, regime_hi=regime_hi,
    )


def _render_methodology(methodology: Sequence[ProfileClaim]) -> str:
    lines = []
    for claim in methodology:
        note_ids = ", ".join(claim.citations)
        lines.append(f"- {claim.text} [note_id(s): {note_ids}]")
    return "\n".join(lines)


def _build_user_prompt(
    *, persona_slug: str, methodology: Sequence[ProfileClaim], universe: Sequence[str],
) -> str:
    return (
        f"Persona: {persona_slug}\n"
        "Below is this persona's own extracted trading methodology, each claim tagged with the "
        "note_id(s) it was drawn from. Cite ONLY these exact note_id values in your `citations` "
        "field, and only the ones you actually used.\n"
        "\n"
        "--- METHODOLOGY START ---\n"
        f"{_render_methodology(methodology)}\n"
        "--- METHODOLOGY END ---\n"
        "\n"
        f"This persona is currently bullish on: {', '.join(universe)}. This is context only -- the "
        "universe of tickers this card trades is fixed by the caller and is not something you choose "
        "or need to restate.\n"
        "\n"
        "Map this methodology onto one rule shape and its parameters, per the rules above."
    )


# ---------------------------------------------------------------------------
# _CardMapping -> Genome -- see the module docstring on why this is `Genome(...)` + `genome_id_for`
# directly (the `app.agents.designer._to_genome` precedent) rather than a nonexistent `make_genome`.
# ---------------------------------------------------------------------------


def _pseudo_seed(genome_id: str) -> int:
    """A deterministic, content-derived stand-in for `Genome.seed`, identical in method to
    `app.agents.designer._pseudo_seed` and for the identical reason: a persona-mapped genome was never
    drawn from a `random.Random` stream, but `Genome.seed` is a required, non-negative int
    (`Field(ge=0)`). Deriving it from `genome_id`'s own content keeps the field meaningful in the one
    sense it still can be: the same mapping always gets the same seed."""
    digest = sha256(genome_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def _traits_from_mapping(mapping: _CardMapping) -> dict[str, Any]:
    """`mapping`'s fields, in the exact `Genome.traits` layout `app.evolution.proposer._rules_card`
    reads (see that function's `traits[...]`/`traits.get(...)` lookups) -- ten keys, matching
    `app.evolution.models.MAX_FREE_PARAMETERS` and `app.agents.designer._RULES_TRAIT_KEYS` exactly.

    Money-shaped fields are converted from `_CardMapping`'s `Decimal` to plain `float` here, matching
    every other writer of a `"rules"`-shape genome's traits (`app.evolution.genome._random_rules_traits`
    draws `stop_loss_pct`/`take_profit_pct`/`position_pct` as floats) -- `_rules_card` itself re-wraps
    whatever it finds back into `Decimal(str(...))`, so a float here round-trips exactly, and keeping
    `Genome.traits` in the same shape every other genome uses (rather than the one this module happens
    to introduce Decimals into) is what lets this genome be reloaded and bred from by the same code
    that reloads any other, unchanged.
    """
    return {
        "fast": mapping.fast,
        "slow": mapping.slow,
        "regime_ma": mapping.regime_ma,
        "stop_loss_pct": float(mapping.stop_loss_pct),
        "take_profit_pct": float(mapping.take_profit_pct) if mapping.take_profit_pct is not None else None,
        "max_hold_days": mapping.max_hold_days,
        "max_positions": mapping.max_positions,
        "position_pct": float(mapping.position_pct),
        "rank_key": mapping.rank_key,
        "rule_shape": mapping.rule_shape,
    }


def _format_notes(persona_slug: str, mapping: _CardMapping) -> str:
    text = f"persona {persona_slug}: {mapping.rationale}"
    if len(text) > _NOTES_LIMIT:
        text = text[: _NOTES_LIMIT - 1].rstrip() + "…"
    return text


def _build_genome(*, persona_slug: str, universe: tuple[str, ...], mapping: _CardMapping) -> Genome:
    """`mapping` (plus the caller-supplied `universe`) as a fresh, `origin="agent"` `Genome` --
    `generation=0` because a persona-mapped card is not part of any evolution-loop generation
    sequence; it is a standalone proposal, numbered the same way a founder genome with no lineage
    would be. See the module docstring for why this is a direct `Genome(...)` construction (the
    `app.agents.designer._to_genome` precedent) rather than a call to a `make_genome` helper that does
    not exist in this codebase.
    """
    traits = _traits_from_mapping(mapping)
    genome_id = genome_id_for(
        generation=0, shape="rules", purpose=Purpose.TRADING, universe=universe, traits=traits,
    )
    return Genome(
        genome_id=genome_id,
        generation=0,
        parents=(),
        origin="agent",
        shape="rules",
        purpose=Purpose.TRADING,
        universe=universe,
        traits=traits,
        seed=_pseudo_seed(genome_id),
        notes=_format_notes(persona_slug, mapping),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def draft_strategy_card(
    *,
    persona_slug: str,
    profile: PersonaProfile | None,
    bullish_tickers: Sequence[str],
    settings: Settings,
    budget: AgentBudget,
    model: str = DEFAULT_MODEL,
) -> DraftResult:
    """Map `profile.methodology` onto the repo's rule vocabulary and realise it as a validated
    `StrategyCard`, per `docs/INFLUENCER-CONTRACT.md` Phase 7c.

    **No methodology -> unmapped, no model call.** `profile is None` or `profile.methodology == ()`
    (a pure macro commentator, or a persona never consolidated) returns `mapped=False` with the
    contract's own fixed reason string, and `DraftResult.calls` is empty -- there is nothing to ask a
    model to map. This check runs before `bullish_tickers` is even inspected, matching the contract's
    own ordering: a persona with no methodology is refused for that reason specifically, not folded
    into a generic "nothing to map" message.

    **No bullish tickers -> unmapped, no model call.** A methodology with nothing to trade is equally
    unmappable -- `app.evolution.models.Genome.universe` requires at least one symbol, so this is
    refused before a call is made rather than discovered as a `Genome` construction failure after
    paying for one.

    **A universe of nothing but non-equity/ETF symbols -> unmapped, no model call.**
    `app.personas.instruments.classify`/`is_tradeable` decide, symbol by symbol, whether a name is
    something a reader could hold through an ordinary equities broker; a future, index, crypto, or fx
    mention is dropped before any model call is made. When that empties the universe entirely, the
    reason names every dropped symbol, its real instrument kind, and a tradeable proxy when
    `suggest_proxy` has one (e.g. "GC is a future; try GLD") -- see `_non_tradeable_reason`. When only
    some symbols are dropped, the mapping proceeds on the tradeable subset alone.

    **Otherwise, exactly one model call**, via `app.agents.client.call_structured` under the
    `"swarm_worker"` role (see `_ROLE`'s own docstring for why this feature never uses a
    persona-specific role), asking the model to choose a `rule_shape` and its trait parameters
    consistent with the described methodology. The universe is never asked of the model -- it is
    `bullish_tickers`, capped and normalised by `_universe_from_bullish`, exactly as the contract
    specifies.

    **The mapping is validated by realising it, never by a second, competing validator here.** The
    mapping becomes a `Genome` (`_build_genome`) and then a real `StrategyCard` via
    `app.evolution.proposer.card_for` -- the exact function and exact card models the evolution loop's
    own agent-designed genomes are built and validated through. A `ProposalRejected` or `ValueError`
    (pydantic's `ValidationError` is a `ValueError` subclass, so a malformed `Genome` construction is
    caught by the same clause) is reported as `mapped=False, reason=f"mapping rejected: {{exc}}"` --
    never patched, clamped, or retried into validity, the same "validate, never repair" line
    `app.agents.designer`'s own module docstring draws for the evolution loop's agent path.

    **Citations are filtered, never trusted verbatim.** `StrategyCardDraft.citations` is the model's
    own `_CardMapping.citations` narrowed to the `note_id`s that actually appear in
    `profile.methodology`'s claims -- the same "drop what the model could not have seen" discipline
    `app.personas.consolidate._filter_claims` applies to a profile claim's citations, adapted to a flat
    id list rather than a list of claims (there is no whole claim to drop here, only ids to keep or
    discard).

    **`AgentUnavailable`/`BudgetExhausted` propagate unchanged** -- this function does not catch
    either, exactly as `app.personas.consolidate.consolidate_notes` documents for the identical reason:
    they mean the call could not be attempted or completed at all, which is a caller-visible failure
    mode distinct from a mapping the card validators went on to reject.
    """
    if profile is None or not profile.methodology:
        return DraftResult(
            draft=StrategyCardDraft(
                persona=persona_slug,
                mapped=False,
                reason="this persona describes no mechanical methodology to translate",
                caveat=_CAVEAT,
            ),
            calls=(),
        )

    universe = _universe_from_bullish(bullish_tickers)
    if not universe:
        return DraftResult(
            draft=StrategyCardDraft(
                persona=persona_slug,
                mapped=False,
                reason="no current-bullish tickers to trade",
                caveat=_CAVEAT,
            ),
            calls=(),
        )

    tradeable, dropped = _split_tradeable(universe)
    if not tradeable:
        return DraftResult(
            draft=StrategyCardDraft(
                persona=persona_slug,
                mapped=False,
                reason=_non_tradeable_reason(dropped),
                caveat=_CAVEAT,
            ),
            calls=(),
        )
    universe = tradeable

    system = _build_system_prompt()
    user = _build_user_prompt(
        persona_slug=persona_slug, methodology=profile.methodology, universe=universe,
    )

    mapping, call, new_budget = call_structured(
        role=_ROLE,
        system=system,
        user=user,
        output_format=_CardMapping,
        model=model,
        settings=settings,
        budget=budget,
        effort="high",
    )

    valid_note_ids = frozenset(
        note_id for claim in profile.methodology for note_id in claim.citations
    )
    citations = tuple(note_id for note_id in mapping.citations if note_id in valid_note_ids)
    cost_usd = str(new_budget.spent_usd)

    # `techniques_represented` is derived, never a second number the model reports independently of
    # `unrepresentable` -- see `_CardMapping.techniques_total`'s own docstring for why. Clamped at 0
    # so a model that (against instructions) names more unrepresentable techniques than its own
    # `techniques_total` cannot drive `fidelity` negative.
    techniques_total = mapping.techniques_total
    techniques_represented = max(0, techniques_total - len(mapping.unrepresentable))
    fidelity = (techniques_represented / techniques_total) if techniques_total else None

    genome = _build_genome(persona_slug=persona_slug, universe=universe, mapping=mapping)
    try:
        card = card_for(genome)
    except (ProposalRejected, ValueError) as exc:
        return DraftResult(
            draft=StrategyCardDraft(
                persona=persona_slug,
                mapped=False,
                reason=f"mapping rejected: {exc}",
                caveat=_CAVEAT,
                cost_usd=cost_usd,
                fidelity=fidelity,
                techniques_total=techniques_total,
                techniques_represented=techniques_represented,
                unrepresentable=mapping.unrepresentable,
            ),
            calls=(call,),
        )

    return DraftResult(
        draft=StrategyCardDraft(
            persona=persona_slug,
            mapped=True,
            rule_shape=mapping.rule_shape,
            card=card.model_dump(mode="json"),
            rationale=mapping.rationale,
            citations=citations,
            caveat=_CAVEAT,
            degraded=False,
            cost_usd=cost_usd,
            fidelity=fidelity,
            techniques_total=techniques_total,
            techniques_represented=techniques_represented,
            unrepresentable=mapping.unrepresentable,
        ),
        calls=(call,),
    )


# ---------------------------------------------------------------------------
# Persistence -- strategy/<version>.json under the persona dir, so a mapped draft can be re-opened
# exactly. `draft_strategy_card` above never writes a file itself (see its own module-level framing
# in the docstring at the top of this file): mapping and saving are two different decisions, and a
# caller previewing a draft before deciding whether it is worth keeping must be able to call
# `draft_strategy_card` any number of times with no filesystem side effect.
# ---------------------------------------------------------------------------

_STRATEGY_DIRNAME = "strategy"


def _strategy_dir(settings: Settings, persona_slug: str) -> Path:
    return persona_dir(settings, persona_slug) / _STRATEGY_DIRNAME


def _write_atomic(path: Path, content: str) -> None:
    """Write `content` to `path` atomically: a uuid-suffixed staging file in `path`'s own directory,
    then a single `os.replace` onto the real name. Identical technique to
    `app.personas.profile_store._write_atomic`, for the identical reason -- `os.replace` is atomic on
    both POSIX and Windows only for files on the same volume, which a same-directory staging file
    always is, and a uuid suffix means two writers racing a staging name can never collide on the
    final replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f"{path.name}.{uuid.uuid4().hex}.tmp"
    staging.write_text(content, encoding="utf-8")
    os.replace(staging, path)


def _existing_versions(directory: Path) -> list[int]:
    """Every `<n>.json` file's own `<n>` already under `directory`, unordered -- `save_draft` takes
    `max(..., default=0) + 1` of this to number the next version. A filename that is not a bare
    integer stem (never written by this module, but a directory a person could still hand-edit) is
    skipped rather than raised, the same "an external hand-edit degrades gracefully" choice
    `app.personas.profile_store`/`app.personas.store` make for their own listings."""
    if not directory.is_dir():
        return []
    versions: list[int] = []
    for path in directory.glob("*.json"):
        try:
            versions.append(int(path.stem))
        except ValueError:
            continue
    return versions


def save_draft(persona_slug: str, draft: StrategyCardDraft, settings: Settings) -> SavedStrategyDraft:
    """Persist `draft` as the next version under `strategy/<version>.json` in `persona_slug`'s persona
    directory, atomically, and return the `SavedStrategyDraft` that was written.

    `version` is `max(existing versions, default=0) + 1` -- append-only, like `profile.md`'s own
    `profile.history/` archive, so an owner can reopen exactly the card they looked at even after a
    later re-draft. The version number is stamped onto the returned/persisted draft itself
    (`StrategyCardDraft.version`), overriding whatever `draft.version` was on the way in -- the store,
    not the caller, owns the version sequence, the same "store owns the path" rule
    `ProfileStore.save_profile`/`save_thesis` already follow for their own targets.
    """
    directory = _strategy_dir(settings, persona_slug)
    version = max(_existing_versions(directory), default=0) + 1
    stamped = draft.model_copy(update={"version": version})
    saved = SavedStrategyDraft(
        draft=stamped, saved_at=dt.datetime.now(dt.UTC), filename=f"{version}.json",
    )
    _write_atomic(directory / saved.filename, saved.model_dump_json())
    return saved


def list_saved_drafts(persona_slug: str, settings: Settings) -> tuple[SavedStrategyDraft, ...]:
    """Every readable saved draft for `persona_slug`, newest version first.

    A `strategy/<n>.json` file that cannot be parsed is logged and skipped, not raised -- the same
    choice `ProfileStore.list_theses` makes for a bad thesis file, so one hand-corrupted version
    cannot hide every other, readable one from the listing."""
    directory = _strategy_dir(settings, persona_slug)
    if not directory.is_dir():
        return ()

    saved: list[SavedStrategyDraft] = []
    for path in directory.glob("*.json"):
        try:
            saved.append(SavedStrategyDraft.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            logger.warning("strategy store: skipping unreadable draft %s: %s", path, exc)
            continue

    saved.sort(key=lambda item: item.draft.version, reverse=True)
    return tuple(saved)
