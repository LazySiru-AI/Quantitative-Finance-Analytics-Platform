"""Round 37: does the double Bollinger band's band-within-band structure survive on daily bars?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round37.py --write

`strategy-program/ROUND-37-PLAN.md` is the pre-registration this executes. Read it first. **The round
has not been run**; this tool only authors its field, which `strategy-program/tools/run_round.sh`
then runs and `score.py` scores, exactly like every other card round.

**Where the hypothesis comes from, and why that matters.** This programme ingests investing YouTubers
into persona notes under `data/vault/influencers/<slug>/notes/` (loader:
`app.personas.service.list_notes`). The persona `creator-e` -- "Creator E", 20 notes -- runs
a system he calls "Double B": two Bollinger Bands at once, an outer 20-period 2-sigma band and an
inner 4-period 4-sigma band, entries taken when price clears both, 1% risk per trade, stops moved to
break-even. Note `VIDEOID002` ("The 1 Minute Scalping Strategy That Made Me $660,000") states the
parameters outright; note `-VIDEOID001` says of the pair "There are the only indicators I've used for
over 10 years" and claims a backtested win rate of 78% against 55% for a single band; note
`VIDEOID003` adds the higher-timeframe rule, "The signal must come from the band that matches the
higher time frame direction." **Every one of those claims is intraday** -- 1-minute and 2-minute
candles, inside the first two hours after a session open. This round does not test them and cannot.

**What this round does ask.** The band-within-band *structure* -- an outer band setting the bias, an
inner band timing the entry inside it -- is a rule form none of this programme's measured rounds
contained. Rounds 17, 18 and 34 between them measured eight forms
(`app.evolution.ruleforms.RULE_SHAPES`) and found every marginal inside the 21.2pp noise floor;
round 34's own report puts the form marginal at 4.21pp with a minimum BH q of 0.81 over sixteen
cells. The nearest existing form is `band-breakout`, and it is a **single** band:
`close crosses_above bb_upper(30, 2) and close > sma(200)`. So the question this round can honestly
ask on daily bars is: **on the programme's own taxable growth names, does adding the second band buy
anything the single band does not?** The pre-registered answer, stated in the plan before any
measurement, is that it does not.

**Why the field is written out here rather than generated from `ruleforms`.** Round 34 generated its
cards from `app.evolution.ruleforms` precisely because the eight forms already exist in code. This
round's entry structure does **not** exist in that vocabulary -- that is the whole point of running it
-- so there is nothing to import. The three entry strings and two exit strings are therefore literals
in this module, every one of them parsed by the real `app.rules.grammar` at build time
(`_validated`), so a typo cannot reach a card.

**The universe is pinned and it is not thesis-picked by the author.** It is
`app.evolution.universe._TAXABLE_GROWTH` verbatim: the twelve-name taxable growth pool the evolution
loop already searches. Using the loop's own pool is the point -- this is a rule form the loop's
template vocabulary cannot emit, tested on the names the loop already trades, so a difference is
attributable to the form rather than to a universe somebody chose after looking at returns.

**The disjointness check runs in the opposite direction from round 34's, and that is not cosmetic.**
These cards carry `purpose = Purpose.TRADING`, so in a `find_disjointness_violations` result they are
the `other_agent_id` side, never the `roth_agent_id` side. Round 34's filter (`v.roth_agent_id in
mine_ids`) copied here would match nothing and would pass vacuously on a field that collided with
every Roth card in the library. `check_disjointness` below filters on `other_agent_id` for exactly
that reason, and `tests/test_round37_field.py` plants a Roth ticker to prove the guard fires.

**Nothing here is tuned.** 20/2 and 4/4 are the persona's own published constants, quoted from his
notes and not searched over. 200 is the regime period every card in rounds 17/18/34 used. 0.12 is
round 17's middle bracket level, published as indistinguishable from its neighbours at 0.14pp across
a 48-cell field. 150 is a hold cap chosen to sit inside the trading mandate's nine months
(`PurposeSpec.horizon_months_max`), not chosen by looking at an outcome. 4 x 0.20 is round 34's
sizing. No grid was searched to arrive at any of them.

**What this tool touches.** The library JSON (read-only, for the disjointness check) and the round's
own cards directory. Nothing here reads `data/accounts.toml`, `data/sectors.toml`,
`data/store/ledger.sqlite` or anything under `app.tax`; the cards it writes read only the Parquet /
DuckDB bar store, like every other card in this programme.

**Not investment advice**, and in particular this round is not a test of the persona's system, does
not endorse it, and cannot evaluate the win rates his notes claim.
"""

from __future__ import annotations

import argparse
import pathlib
from collections.abc import Sequence
from decimal import Decimal

from app.indicators.volatility import BB_SPEC
from app.rules import grammar
from app.tournament.allocation import AllocationCard
from app.tournament.ladder import LadderCard
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from app.tournament.purposes import (
    DisjointnessViolation,
    Purpose,
    find_disjointness_violations,
)
from app.tournament.results import LIBRARY_ROOT, load_library

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r37-2026-09" / "cards"

#: `app.evolution.universe._TAXABLE_GROWTH`, verbatim and in its own write order.
#:
#: **Not chosen by this round's author.** It is the twelve-name pool the evolution loop already
#: searches for `trading`-purpose candidates, which is the property that makes it the right universe
#: for a question about *form*: a form the loop's template vocabulary cannot emit, run on the names
#: the loop already trades. A universe assembled by the author to suit a band strategy would be the
#: single most obvious confound in a round about band structure.
#:
#: **Copied rather than imported, deliberately.** `_TAXABLE_GROWTH` is a private name in a module this
#: round does not own and which other work in this programme edits; importing it would mean a later
#: edit there silently rewrote a frozen field's universe, which is the immutability boundary
#: `PROTOCOL.md` section 2 draws. The copy is pinned here and `tests/test_round37_field.py` asserts
#: this tuple equals `app.evolution.universe._TAXABLE_GROWTH` today, so a divergence is a loud test
#: failure rather than a silent drift.
#:
#: First stored daily bars are all at or before `GOOGL`'s 2004-08-19, which is the binding symbol
#: against the `gfc` window's deadline for a 200-day indicator. All twelve cells should therefore
#: clear all eight main windows -- verified with `strategy-program/tools/windows.py --cards
#: data/rounds/r37-2026-09/cards` before the field was frozen, not assumed. Round 17's Amendment 1 is
#: why that check is run rather than reasoned about: there, two young ETFs did not merely contribute
#: nothing to a window, they failed the whole card, and the round lost three windows to it.
UNIVERSE: tuple[str, ...] = (
    "NVDA", "TSM", "MU", "AMD", "QCOM", "MSFT", "GOOGL", "AMZN", "NFLX", "ORCL", "INTC", "TXN",
)

#: The persona's own two bands, quoted from `data/vault/influencers/creator-e/notes/`.
#:
#: Note `VIDEOID002` states them as "two separate Bollinger Bands (lengths 20 and 4)"; note
#: `-VIDEOID001` gives the full configuration -- "the first with period 4, standard deviation 4,
#: source set to open, colored red; the second with period 20, standard deviation 2, colored white".
#: They are his numbers, not this round's, and they were not searched over. **The `source = open`
#: detail is not modelled**: `bb_upper(p, k)` is built on closes, and the plan's section 7 says so.
OUTER_PERIOD, OUTER_SIGMA = 20, 2
INNER_PERIOD, INNER_SIGMA = 4, 4

#: The programme's regime period, unchanged from rounds 17, 18 and 34 so the marginal is comparable.
REGIME_MA = 200
REGIME_CLAUSE = f"close > sma({REGIME_MA})"


def _validated(rule: str) -> str:
    """`rule`, after `app.rules.grammar.parse` has accepted it. Raises otherwise.

    Every rule string in this module goes through here at import time, so a misspelled indicator or
    a broken expression is a hard failure when the tool is loaded rather than a card that validates
    structurally and then dies at run time in the seventh window of a four-hour round.

    **What this does not catch, measured rather than assumed.** `grammar.parse` accepts
    `close crosses_above bb_upper(4)`, `bb_upper(4, 4, 4)` and `bb_upper(1, 4)` -- it validates the
    indicator *name* and the expression shape, not the argument count and not the argument ranges.
    Those live one layer down, in `app.indicators.volatility.BB_SPEC`'s `ParamSpec`s (period 2-500,
    stddev 0.1-10). So `_check_band_params` below asserts this round's four band constants against
    that spec directly, because a rule that parses and then fails at indicator-request time would
    fail *per window inside the runner*, which is the expensive place to find out.
    """
    grammar.parse(rule)
    return rule


def _check_band_params() -> None:
    """This round's band constants, against `app.indicators.volatility.BB_SPEC`'s own bounds.

    Read off the spec rather than restated as literals here, so a future change to the indicator's
    accepted range is a failure at import time instead of a silent divergence between what this
    round says it measures and what the engine will compute.
    """
    period_spec, stddev_spec = BB_SPEC.params
    for period, stddev in ((OUTER_PERIOD, OUTER_SIGMA), (INNER_PERIOD, INNER_SIGMA)):
        if not (period_spec.minimum <= period <= period_spec.maximum):
            raise ValueError(f"bb period {period} is outside {BB_SPEC.name}'s accepted range")
        if not (stddev_spec.minimum <= stddev <= stddev_spec.maximum):
            raise ValueError(f"bb stddev {stddev} is outside {BB_SPEC.name}'s accepted range")


_check_band_params()


#: The round's one real factor: how many bands the entry names.
#:
#: `double` is the persona's structure -- the outer band's midline as the bias filter, the inner band's
#: upper edge as the trigger. `outer` and `inner` are its two halves, each on its own, and they are
#: the controls that make the double cell interpretable: without them, a result for `double` is a
#: statement about Bollinger bands in general and not about the band-within-band structure at all.
ENTRIES: dict[str, str] = {
    "double": _validated(
        f"close > bb_mid({OUTER_PERIOD}, {OUTER_SIGMA}) and "
        f"close crosses_above bb_upper({INNER_PERIOD}, {INNER_SIGMA})"
    ),
    "outer": _validated(f"close crosses_above bb_upper({OUTER_PERIOD}, {OUTER_SIGMA})"),
    "inner": _validated(f"close crosses_above bb_upper({INNER_PERIOD}, {INNER_SIGMA})"),
}

#: The second factor: which of the two bands is allowed to end the trade.
#:
#: `midcross` is the exit `app.evolution.ruleforms`' own `band-breakout` form uses (on its own period)
#: and reads as "the outer-band regime is lost". `innerfail` is the fast band's own failure, and it is
#: the closer analogue of the persona's structural stop -- he moves a stop to break-even and exits on
#: the opposing setup, neither of which this engine can express, so `innerfail` is an approximation
#: and the plan says so rather than claiming a match.
EXITS: dict[str, str] = {
    "midcross": _validated(f"close crosses_below bb_mid({OUTER_PERIOD}, {OUTER_SIGMA})"),
    "innerfail": _validated(f"close < bb_lower({INNER_PERIOD}, {INNER_SIGMA})"),
}

#: The third factor, carried because rounds 17 and 34 both measured it and both found it inside the
#: floor (round 34: 0.88pp of median while cutting held capital from 41% to 26%). It is here as a
#: replication on a third universe and as this field's cheapest control, not as a new question.
REGIME_ARMS: tuple[str, ...] = ("on", "off")

#: Round 17's middle bracket level -- **except the hold cap, which is 150 and not round 17's 180.**
#:
#: `StrategyCard.max_hold_days` counts *sessions* (`app.tournament.runner._decide_exit`), and 180
#: sessions is roughly 8.6 calendar months. The `trading` mandate is bounded at nine months
#: (`PurposeSpec.horizon_months_max`), and round 24 found two seated cards at 180 sessions could not
#: honour the *six*-month bound the owner had set at the time; the bound moved to nine rather than the
#: cards being capped, and that history is written into `horizon_months_max`'s own docstring. 150
#: sessions is ~7.1 calendar months, inside the mandate with room to spare and not at its edge. It is
#: a constraint, not a tuned parameter: no outcome was consulted to pick it.
#:
#: No take-profit. Round 17 measured `none`, `stop` and `stop-tp` as differing by **0.14pp** across a
#: 48-cell field, so carrying a bracket factor here would spend runtime re-measuring a contrast
#: already published as empty and would inflate this round's Benjamini-Hochberg denominator for
#: nothing. `stop` is round 17's own middle level; picking its *best* level would be selecting on an
#: outcome.
BRACKET: dict[str, object] = {
    "stop_loss_pct": Decimal("0.12"),
    "take_profit_pct": None,
    "max_hold_days": 150,
}

#: Four slots at 20%, identical to round 34, so the two fields' books are of comparable size --
#: `adjusted_excess`'s exposure term is not commensurable across differently-sized books
#: (`PROTOCOL.md` section 4).
#:
#: **The cost, stated so it is not discovered later.** Four slots over twelve names is a third of the
#: roster, so the cap binds harder here than in any previous round of this family, and `rank_by` is
#: unset like every card this programme has published -- which means the `UNIVERSE` write order
#: decides more ties. This field therefore carries *more* ordering exposure than round 34 did, not
#: less, and the 21.2pp floor is not lowered on the strength of round 17's ~1pp ordering replication.
MAX_POSITIONS = 4
POSITION_PCT = Decimal("0.20")

#: Every cell is labelled `breakout`, and this is a decision rather than a default.
#:
#: All three entry structures fire on price clearing the upper edge of a volatility band, which is
#: what `Discipline.BREAKOUT` names and what round 17's `band-breakout` cells carried. The `midcross`
#: exit is trend-shaped and the `innerfail` exit is a volatility stop, but `Discipline` labels the
#: school the *card* is working in, and a single label across the field is what keeps the correction
#: arithmetic honest: twelve cells of one entry family are one hypothesis tested twelve ways, and
#: `Discipline`'s own docstring says that is exactly what the label exists to make visible.
DISCIPLINE = Discipline.BREAKOUT


def entry_for(structure: str, regime_state: str) -> str:
    """The entry rule for one cell, with the regime conjunct prepended on the `on` arm.

    Built by composition rather than by string surgery -- the opposite of `round34.strip_regime`,
    which had to *remove* a conjunct because `ruleforms.render` always emits one. Here the base
    entries carry no regime clause, so the `off` arm is the literal and the `on` arm is the literal
    plus a prefix. Composition cannot produce the class of failure surgery can (a rule that parses
    but no longer means what the round says it means), and the result is validated anyway.
    """
    base = ENTRIES[structure]
    if regime_state == "off":
        return base
    return _validated(f"{REGIME_CLAUSE} and {base}")


def library_purposed_cards() -> list[StrategyCard | AllocationCard | LadderCard]:
    """Every purposed card in the live library, across all six tiers on disk.

    `app.tournament.results.load_library` covers `base`/`variants`/`candidates`/`retired`, which are
    the four tiers holding `StrategyCard`s. It does **not** cover `allocation/` and `ladder/`, whose
    files are `AllocationCard`s and `LadderCard`s and would fail `StrategyCard` validation -- and
    those two tiers are where `AGG`, `BIL`, `QLD`, `SCHD`, `SGOV`, `IEF` and the shipped Roth ladder
    live. Checking disjointness against `load_library()` alone would miss five taxable tickers and,
    more to the point for *this* round, would miss any Roth ladder or allocation card whose universe
    my twelve names might collide with. Both are read here, the same way
    `strategy-program/tools/round36.py::library_cards` and `app.evolution.promotion._library_cards`
    do.
    """
    cards: list[StrategyCard | AllocationCard | LadderCard] = [
        card for tier_cards in load_library().values() for card in tier_cards
    ]
    for tier, model in (("allocation", AllocationCard), ("ladder", LadderCard)):
        tier_dir = LIBRARY_ROOT / tier
        if not tier_dir.is_dir():
            continue
        for path in sorted(tier_dir.glob("*.json")):
            cards.append(model.model_validate_json(path.read_text(encoding="utf-8")))
    return cards


def roth_symbols(
    library: Sequence[StrategyCard | AllocationCard | LadderCard],
) -> frozenset[str]:
    """Every symbol any `roth`-purpose card in `library` can own a position in.

    **The mirror image of `round34.taxable_symbols`, because this round's cards are on the other side
    of the wall.** Round 34 authored Roth cards and had to avoid the taxable roster; round 37 authors
    `trading` cards and has to avoid the Roth roster. Recomputed from the library on every call rather
    than pinned as a literal, because the library is edited concurrently by other work in this
    programme and a hardcoded list would pass this check against a book that no longer exists.
    """
    return frozenset(
        symbol
        for card in library
        if card.purpose is Purpose.ROTH
        for symbol in card.universe
    )


def check_disjointness(
    cards: Sequence[StrategyCard],
    library: Sequence[StrategyCard | AllocationCard | LadderCard],
) -> tuple[tuple[DisjointnessViolation, ...], tuple[DisjointnessViolation, ...]]:
    """`(mine, pre_existing)` -- violations this round's cards cause, and everyone else's.

    Both come from one `find_disjointness_violations` call over the library and this round's cards
    together, which is the only way to see a collision between a new card and an old one.

    **The filter is `other_agent_id`, not `roth_agent_id`, and getting this backwards would make the
    whole guard vacuous.** A `DisjointnessViolation` always names the Roth card as `roth_agent_id` and
    the `savings`/`trading` card as `other_agent_id` (see that class's field docs). This round's cards
    are `purpose = trading`, so they can only ever appear as `other_agent_id`. Round 34's filter tests
    `roth_agent_id` because round 34 authored Roth cards; copied verbatim into this module it would
    match nothing and report a clean field no matter what it collided with.
    """
    mine_ids = {card.agent_id for card in cards}
    violations = find_disjointness_violations([*library, *cards])
    return (
        tuple(v for v in violations if v.other_agent_id in mine_ids),
        tuple(v for v in violations if v.other_agent_id not in mine_ids),
    )


def _falsification(structure: str, exit_name: str, regime_state: str) -> str:
    """The pre-registered failure regime for one cell, per `PROTOCOL.md` section 3 rule 5.

    Named per entry structure rather than once for the round, because the three structures have
    different exposure to whipsaw and a single sentence covering all three would be a slogan rather
    than a prediction. Each names an observation somebody other than the author could make from this
    round's own trade logs.
    """
    if structure == "inner":
        specific = (
            "This cell's thesis is that the fast 4-period, 4-sigma band alone is a usable "
            "entry trigger on daily bars. It is falsified if this cell does NOT take the most "
            "trades of the three entry structures at its own exit and regime setting -- a "
            "4-period band re-forms around price within a week, so an unfiltered break of it "
            "should fire constantly, and if it does not, the trigger is not doing what its "
            "period says it does. As a strategy it is falsified if its worst adjusted excess "
            "is not in `chop-2011` or `chop-2015` -- a fast, unfiltered breakout trigger in a "
            "directionless market is supposed to buy the failed break over and over, and if "
            "that is not where it hurts, its exposure is not what its form claims."
        )
    elif structure == "outer":
        specific = (
            "This cell is the single-band control and its thesis is that the 20-period, "
            "2-sigma break is the whole of whatever a band entry earns. It is falsified if "
            "this cell's worst adjusted excess is not in `chop-2011` or `chop-2015` -- a "
            "breakout rule in a directionless market is supposed to buy the failed break "
            "repeatedly, and if that is not where it hurts, the form's exposure is not what "
            "it claims."
        )
    else:
        specific = (
            "This cell's thesis is that the band-within-band structure -- the outer band's "
            "midline as bias, the inner band's upper edge as trigger -- earns something the "
            "single band does not. It is falsified if this cell's worst adjusted excess is in "
            "`bull-2024`, because the outer-band bias filter exists precisely to keep the fast "
            "trigger out of a V-shaped correction inside an up-year, which is where round 34 "
            "found seven of its sixteen cells lost most."
        )
    exit_clause = (
        "This cell exits on the outer band's midline, so a losing trade is one the outer-band "
        "regime survived while the position bled."
        if exit_name == "midcross"
        else "This cell exits on the inner band's lower edge, so it should hold shorter and "
        "stop out faster than its `midcross` pair; if it does not, the two exits are not "
        "distinguishable on daily bars and the exit factor measured nothing."
    )
    regime_clause = (
        "This cell is the regime-filter-removed half of its pair, so it also falsifies the "
        "claim that the 200-day filter is load-bearing: if the two regime marginals differ by "
        "less than 21.2pp while the filter halves held capital, the filter is a position sizer "
        "spelled as an entry condition -- round 34's finding, replicating on a third universe."
        if regime_state == "off"
        else "This cell is the regime-filter-on half of its pair."
    )
    return (
        specific
        + " "
        + exit_clause
        + " "
        + regime_clause
        + " The round-level falsification, which this cell contributes one observation to, is in "
        "`strategy-program/ROUND-37-PLAN.md` section 5: the two-band structure is declared to "
        "matter only if the `double` marginal beats the `outer` marginal by more than 21.2 "
        "percentage points, with the same sign in at least five of the eight main windows, AND "
        "the contrast survives Benjamini-Hochberg at q < 0.10 over every one of the twelve cells "
        "run. Anything less is the null."
    )


def _thesis(structure: str, exit_name: str, regime_state: str) -> str:
    """One cell's thesis: what it is a cell of, where the hypothesis came from, and its limits."""
    role = {
        "double": (
            "the band-within-band cell -- the outer 20-period, 2-sigma midline as the trend bias "
            "and the inner 4-period, 4-sigma upper edge as the trigger inside it"
        ),
        "outer": "the single-band control, outer band only",
        "inner": "the single-band control, inner band only",
    }[structure]
    exit_role = {
        "midcross": "exits when the outer band's midline is lost",
        "innerfail": "exits when price closes below the inner band's lower edge",
    }[exit_name]
    return (
        f"Round 37 cell: {role}; it {exit_role}; the 200-day regime filter is "
        f"{'ON' if regime_state == 'on' else 'OFF'}. One cell of a pre-registered 3 x 2 x 2 "
        "factorial asking a single question: on daily bars, does the two-band structure earn "
        "anything the single band does not? The hypothesis is taken from this programme's own "
        "persona corpus -- the influencer `creator-e` ('Creator E') describes a 'Double "
        "B' system across several notes (`VIDEOID002`, `-VIDEOID001`, `VIDEOID003`) using exactly "
        "these two band configurations, 1% risk per trade and stops moved to break-even. HIS CLAIM "
        "IS INTRADAY -- 1-minute and 2-minute candles in the first two hours after a session open -- "
        "AND THIS ROUND DOES NOT TEST IT AND CANNOT. It asks the only question this programme's "
        "daily-bar engine can ask of the idea: whether the band-within-band structure carries "
        "anything at daily frequency against the programme's own trend-form family, which rounds "
        "17, 18 and 34 measured as entirely inside a 21.2 percentage point noise floor. The nearest "
        "existing form is `band-breakout`, a SINGLE band. The universe is "
        f"{' '.join(UNIVERSE)} -- `app.evolution.universe._TAXABLE_GROWTH` verbatim, the pool the "
        "evolution loop already searches, so this is a form the loop cannot emit tested on names it "
        "already trades, and not a universe picked by the author to suit a band strategy. Every "
        "parameter is quoted rather than tuned: 20/2 and 4/4 are the persona's own published "
        "numbers, 200 is rounds 17/18/34's regime period, the 12% stop is round 17's middle bracket "
        "level (published as differing from its neighbours by 0.14pp across 48 cells), and the "
        "150-session hold cap sits inside the nine-month trading mandate rather than at its edge. "
        "Nothing will be promoted from this round: it is a measurement study, and `PROTOCOL.md` "
        "section 9's r21 amendment already removes the `trading` purpose from section 6's promotion "
        "rule -- these medians are reported and never promoted on. Not investment advice; this is "
        "not an endorsement of the persona's system and produces no evidence about the win rates "
        "his notes claim. See `strategy-program/ROUND-37-PLAN.md` for the pre-registration, the "
        "decision rule and the six falsifiable predictions."
    )


def build() -> list[StrategyCard]:
    """The round's twelve cards, in a fixed order.

    Deterministic: same inputs, same order, byte-identical model dumps. `ENTRIES`, `EXITS` and
    `REGIME_ARMS` are fixed and ordered, and nothing here reads a clock, a random source, the bar
    store or the filesystem.
    """
    cards: list[StrategyCard] = []
    for structure in ENTRIES:
        for exit_name, exit_rule in EXITS.items():
            for regime_state in REGIME_ARMS:
                cards.append(
                    StrategyCard(
                        agent_id=f"r37-{structure}-{exit_name}-{regime_state}",
                        display_name=(
                            f"{structure} band / exit {exit_name} / regime {regime_state}"
                        ),
                        discipline=DISCIPLINE,
                        purpose=Purpose.TRADING,
                        thesis=_thesis(structure, exit_name, regime_state),
                        falsification=_falsification(structure, exit_name, regime_state),
                        universe=UNIVERSE,
                        entry=entry_for(structure, regime_state),
                        exit=exit_rule,
                        max_positions=MAX_POSITIONS,
                        position_pct=POSITION_PCT,
                        designed_through=DESIGN_THROUGH,
                        **BRACKET,  # type: ignore[arg-type]
                    )
                )
    return cards


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="write the cards to the round directory"
    )
    args = parser.parse_args(argv)

    cards = build()

    print(
        f"built {len(cards)} cards over {len(ENTRIES)} entry structures x {len(EXITS)} exits "
        f"x {len(REGIME_ARMS)} regime arms"
    )
    for card in cards:
        print(f"  {card.agent_id:34s} entry: {card.entry}")
    print(f"  exits: {' | '.join(f'{k} = {v}' for k, v in EXITS.items())}")
    print(f"  universe ({len(UNIVERSE)}):", " ".join(UNIVERSE))
    print(
        f"  fixed: stop {BRACKET['stop_loss_pct']}, no target, max_hold "
        f"{BRACKET['max_hold_days']} sessions, {MAX_POSITIONS} x {POSITION_PCT}, "
        f"purpose {Purpose.TRADING.value}, designed_through {DESIGN_THROUGH.isoformat()}"
    )

    library = library_purposed_cards()
    roth = roth_symbols(library)
    overlap = sorted(set(UNIVERSE) & roth)
    mine, pre_existing = check_disjointness(cards, library)

    print(
        f"  disjointness: {len(library)} purposed cards in the library, "
        f"{len(roth)} distinct roth symbols"
    )
    print(f"  universe overlap with the roth book: {overlap or 'none'}")
    for violation in pre_existing:
        print(f"  PRE-EXISTING (not this round): {violation.message}")

    if mine or overlap:
        print()
        print("REFUSING to author this field -- it intersects the Roth research:")
        for violation in mine:
            print(f"  {violation.message}")
        for symbol in overlap:
            print(f"  {symbol} is in this round's universe and in a roth card's")
        print(
            "  Rev. Rul. 2008-5: a replacement purchase inside an IRA destroys the taxable loss "
            "outright. Fix the universe, do not waive this."
        )
        return 1

    if not args.write:
        print("\n(dry run -- pass --write to author the field)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    for card in cards:
        path = OUT / f"{card.agent_id}.json"
        path.write_text(
            card.model_dump_json(indent=2, exclude_none=False) + "\n", encoding="utf-8"
        )
    print(f"\nwrote {len(cards)} cards to {OUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
