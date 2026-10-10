"""Round 39: does a *style* tilt survive where a *sector* tilt did not?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round39.py --write

`strategy-program/ROUND-39-PLAN.md` is the pre-registration this file executes. Read it first; this
module authors the field and nothing else. The cards are then gated by
`strategy-program/tools/disjoint_field.py`, run by `strategy-program/tools/run_round.sh` and scored
by `score.py`, exactly like every other card round.

**The question, and why it is not a re-run.** Rounds 34, 35 and 36 varied the *rotation mechanism* --
rule form, slot cap, fill order -- across industry and country ETFs, and returned three nulls
(`strategy-program/DISJOINT-SECTOR-FAMILY.md` section 5a: form marginal 4.21pp, best rotation cell
minus control +0.08pp, strongest-first minus weakest-first +1.2pp, every margin inside the 21.2pp
ordering-noise floor, minimum BH q 0.40). Round 17 varied form on sectors and found the same. What
**no round in this programme has ever varied is the style/factor axis**: value against growth,
equal-weight against cap-weight, mid-cap against large-cap. `ROTH-MOMENTUM.md` and
`ROTH-VOLTARGET.md` vary *timing and sizing rules* on a fixed QLD/SCHD/IEF sleeve set;
`ROTH-DISJOINT-LADDER.md` varies *which tickers express one fixed ladder*. None of them varies the
style of the basket. This round holds the rule constant and varies the basket's style instead, which
is the mirror image of every round before it.

**The hypothesis came from the app's own influencer vault and no influencer is endorsed.**
`data/vault/influencers/creator-b/` (persona "creator-b", 40 notes) carries two repeated theses: a relative-
valuation method built on P/E and P/B comparables normalised for one-offs, and a ten-year
structural-stagnation view -- its consolidated profile states "Ten years of US equity stagnation
similar to the 1966-1982 Dow period is likely, driven by structural reversal of four post-1982
tailwinds", with capital rotating "from expensive mega-cap technology toward commodities, emerging
markets, semiconductor infrastructure, and energy". **Neither thesis is expressible as stated.** This
repository has no fundamentals store: there is no P/E, no P/B, no book value, no normalisation for
one-off charges anywhere in the bar store, and no round here can test a valuation claim. What *is*
expressible is the **portfolio expression** of the second thesis -- a value / equal-weight / mid-cap
tilt measured against a growth tilt, plus an inflation-linked sleeve. That is a proxy for a
fundamental claim, **not a test of it**, and the plan says so at length. The corpus supplied the
hypothesis; nothing here endorses the persona, and the persona's own stated positioning disagrees
with parts of this field (its profile lists "Bonds and fixed income" under `sectors_avoided`, which
is an argument against the `TIP` sleeve this round nonetheless carries).

**A factor ETF is a bundle whose construction rules this round does not control.** `VTV` is value
because MSCI/CRSP says it is; `SPYG` is growth because S&P's growth screen says so; `RSP` is
equal-weight by rule and `MDY` is mid-cap by a size cutoff. Every one of those definitions was set by
an index provider, is revised on the provider's own schedule, and is not observable in the bars this
round reads. A result here is a result about *these eight funds*, not about the value premium.

**The Roth constraint, and why this round exists on this universe.** These cards carry
`purpose = Purpose.ROTH`, and no ticker they trade may appear in any `savings`- or `trading`-purpose
card's universe -- `app.tournament.purposes.find_disjointness_violations` is the invariant, because
Rev. Rul. 2008-5 does not *defer* a wash-sale loss when the replacement is bought inside an IRA, it
**destroys** it outright with no basis adjustment anywhere. The taxable set is recomputed from the
live library on every run through `app.evolution.promotion._library_cards`, which walks all six tiers
including the `allocation/` and `ladder/` directories `app.tournament.results.load_library` misses --
five taxable tickers (AGG, BIL, QLD, SCHD, SGOV) are claimed *only* there. This module **refuses
`--write`** on any intersection and on anything `find_disjointness_violations` reports against one of
its own cards.

**Ticker disjointness is necessary and not sufficient under IRC section 1091**, and nothing here is a
section 1091-safety claim. That is why `IAU` is in the pinned pool and is **not traded** -- see
`EXCLUDED_SUBSTANTIAL_IDENTITY` below.

**Not investment advice.** Every number this round will produce is a backtest on price-only bars with
no dividends, measured against SPY -- which is the wrong benchmark for a value/mid-cap book and is
pre-registered as this round's known confound. The honest prior, in the plan's section 6, is that
every tilt-minus-control margin lands inside the 21.2pp floor.
"""

from __future__ import annotations

import argparse
import pathlib
import re
from decimal import Decimal
from typing import Any

from app.config import get_settings
from app.evolution.promotion import _library_cards
from app.rules import grammar
from app.tournament.models import DESIGN_THROUGH, StrategyCard
from app.tournament.purposes import Purpose, find_disjointness_violations

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r39-2026-09" / "cards"

# ---------------------------------------------------------------------------
# The universe: pinned before anything was measured, and one name held out of it
# ---------------------------------------------------------------------------

#: The pinned pool, fixed before a single figure was looked at and not to be changed: Vanguard Value,
#: S&P 500 Growth, S&P 500 Equal Weight, S&P MidCap 400, Vanguard Total Stock Market, Nasdaq Biotech,
#: iShares TIPS and iShares Gold. First stored daily bars: `VTV` 2004-01-30, `SPYG` 2000-10-02, `RSP`
#: 2003-05-01, `MDY` 1995-05-04, `VTI` 2001-06-15, `IBB` 2001-02-12, `TIP` 2003-12-05, `IAU`
#: 2005-01-28 -- all before the `gfc` window's 2007-10-09 start with room for a 200-day indicator to
#: warm up. That is checked by `strategy-program/tools/windows.py --cards`, which is the run this
#: round's definition of done requires rather than an assertion made here.
UNIVERSE: tuple[str, ...] = ("VTV", "SPYG", "RSP", "MDY", "VTI", "IBB", "TIP", "IAU")

#: **`IAU` is in the pool and is traded by no card in this round.** It is physical gold; the taxable
#: book holds `GLD`, which is also physical gold. Different ticker, different sponsor, different
#: expense ratio -- and the same underlying asset, which makes the pair the textbook example of two
#: funds that may well be *substantially identical* under IRC section 1091. Ticker disjointness does
#: not reach a case this obvious. `strategy-program/DISJOINT-SECTOR-FAMILY.md` section 4 already made
#: exactly this call when it built the family's ETF pool ("EXCLUDED from this pool ... a family whose
#: whole premise is avoiding section 1091 exposure should not open with its cleanest example of it"),
#: and round 34's card was seated on the live Roth paper book the same day it was measured -- so a
#: roster authored here is a roster that can end up holding real attention, not a thought experiment.
#: The cost is stated rather than hidden: without `IAU` this round carries no hard-asset sleeve, so
#: the commodity/gold limb of the hypothesis in this module's docstring is **not tested at all** and
#: only the style limb is. See `ROUND-39-PLAN.md` section 2b.
EXCLUDED_SUBSTANTIAL_IDENTITY: tuple[str, ...] = ("IAU",)

#: What the cards actually trade: the pool minus the held-out name, in the pool's own order.
TRADED: tuple[str, ...] = tuple(s for s in UNIVERSE if s not in EXCLUDED_SUBSTANTIAL_IDENTITY)

#: The three style slices plus the whole book. Every ticker is classified once, on what the fund *is*
#: rather than on anything measured, and no ticker is stretched to balance the arms:
#:
#: * `value`  -- `VTV` (large-cap value), `RSP` (S&P 500 equal-weight, a deliberate tilt away from the
#:   mega-cap concentration of the cap-weighted index) and `MDY` (S&P MidCap 400). These are the three
#:   funds that express "capital rotates away from US-dollar growth assets" as a long book.
#: * `growth` -- `SPYG` (the S&P 500's own growth half) and `IBB` (Nasdaq biotech, the longest-duration
#:   equity sleeve in the pool). This is the side the thesis says loses.
#: * `core`   -- `VTI` (cap-weighted total US market: the neutral position a tilt is a tilt *away
#:   from*) and `TIP` (inflation-linked Treasuries: the "inflation is inevitable" limb). Neither is a
#:   style, which is exactly why neither is put on a tilt arm -- classifying `VTI` as "growth" because
#:   its top weights are mega-cap growth would confound the style axis with market beta, and putting
#:   `TIP` on either side would confound style with asset class.
#: * `full`   -- all seven, the undivided book.
#:
#: The two tilt slices are 3 and 2 names. That asymmetry is real and is left in rather than papered
#: over by promoting `VTI` to the growth arm: see `ROUND-39-PLAN.md` section 3a for what it costs.
SLICES: dict[str, tuple[str, ...]] = {
    "value": ("VTV", "RSP", "MDY"),
    "growth": ("SPYG", "IBB"),
    "core": ("VTI", "TIP"),
    "full": TRADED,
}

#: Every card in this field targets the same **84%** maximum deployed capital, tilt arm and control
#: arm alike, across slices of three, two and seven names. 0.84 is the one budget under 1.0 that
#: divides exactly by all three slice sizes (0.28 x 3, 0.42 x 2, 0.12 x 7), so no cell has to be
#: rounded to a different book size than its neighbours. This is what makes a cross-slice comparison a
#: question about *style* rather than about how much money is in the market, and it keeps every cell
#: clear of `PROTOCOL.md` section 4's 2x exposure-divergence flag by construction rather than by luck.
CAPITAL_BUDGET = Decimal("0.84")

# ---------------------------------------------------------------------------
# The one rule, held constant across every tilt cell
# ---------------------------------------------------------------------------

#: The evolution loop's own vocabulary at the periods rounds 17, 18, 34 and 35 all used. Rendered
#: through `app.evolution.ruleforms` rather than typed here, so this round holds the form constant
#: **as the loop actually emits it**: generations 1-1915 ran this one template and all 28 of the
#: loop's promotions came from it, which makes it the only form in the vocabulary with an evidentiary
#: record behind it. Nothing about it was chosen by looking at a result on this universe.
FAST, SLOW, REGIME = 10, 30, 200

#: The within-slice passive control's expressions. `close > 0` is true on every bar and `close < 0` on
#: none, so a card carrying them buys its whole slice at the window's open and holds to its close.
#: Round 35 ran both through `app.backtest.guards.check` against real bars before authoring its own
#: control, and its nine cards then ran 8 of 8 main windows with zero `FAILED` lines
#: (`DISJOINT-SECTOR-FAMILY.md` section 5a) -- which is stronger evidence that the shape is viable
#: than a fresh guard call would be. The expressions here are those, character for character.
CONTROL_ENTRY = "close > 0"
CONTROL_EXIT = "close < 0"

#: `app.evolution.ruleforms.classify` returns `None` for the control (no indicator, so nothing to read
#: a discipline off) and `Discipline` has no member meaning "passive". `trend` is the least wrong of
#: seven wrong options; it is a forced label, not a claim, and each control card's own thesis says so.
CONTROL_DISCIPLINE = "trend"

#: Matches every numeric literal in a rule expression, for the `PROTOCOL.md` section 3 budget.
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def claimed_symbols() -> tuple[frozenset[str], list[Any]]:
    """`(tickers claimed by the taxable book, the non-roth cards that claim them)`, from the **live**
    library on disk.

    Read through `app.evolution.promotion._library_cards`, which is the function the application
    itself uses at promotion time to answer this exact question -- so this round's gate and the app's
    gate cannot drift apart. It walks all six tiers: the four `StrategyCard` tiers
    `app.tournament.results.load_library` covers, plus `allocation/` and `ladder/`, which that
    function does not walk at all and which are the only place five taxable tickers (AGG, BIL, QLD,
    SCHD, SGOV) are claimed.

    Recomputed rather than hardcoded, deliberately: this repository is edited by several concurrent
    sessions and a ticker list pasted into a constant is correct exactly until the next commit. The
    returned card list is **only** the non-roth half, so that a pre-existing roth-vs-taxable violation
    elsewhere in the library cannot be reported as though this round caused it -- and cannot mask one
    either, since every roth card in the comparison is then ours.
    """
    others = [
        card
        for card in _library_cards(get_settings())
        if card.purpose in (Purpose.SAVINGS, Purpose.TRADING)
    ]
    symbols = frozenset(symbol for card in others for symbol in card.universe)
    return symbols, others


def free_numbers(card: StrategyCard) -> int:
    """`PROTOCOL.md` section 3's parameter count for one card: ten free numbers, "counted across
    `entry`, `exit`, the two brackets, the hold cap, slot count and position size".

    Distinct numeric *values* across the expressions, not occurrences: `ema(10)` appearing in both the
    entry and the exit is one number an author chose once, and counting it twice would inflate the
    budget with a fact about text rather than about the hypothesis. `rank_by` is included even though
    section 3's list predates that field existing; every card in this round leaves it unset. The
    derivation is `strategy-program/tools/round35.py`'s, unchanged, so the two rounds' reported budgets
    are directly comparable.
    """
    text = " ".join(part for part in (card.entry, card.exit, card.rank_by or "") if part)
    values = {match.group(0) for match in _NUMBER.finditer(text)}
    brackets = sum(
        1
        for field in (card.stop_loss_pct, card.take_profit_pct, card.max_hold_days)
        if field is not None
    )
    return len(values) + brackets + 2  # + max_positions + position_pct


_SHARED_THESIS_TAIL = (
    "The programme has never varied the style/factor axis: rounds 17 and 18 varied rule form on "
    "sectors, rounds 34-36 varied form, slot cap and fill order on industries and countries, and all "
    "of them returned margins inside the 21.2pp ordering-noise floor. This round holds the rule "
    "constant and varies the basket's style instead, which is the mirror image of every round before "
    "it. The hypothesis is the portfolio expression of a claim taken from this app's own influencer "
    "vault (persona wsaj: a ten-year US structural-stagnation view in which post-1982 tailwinds "
    "reverse and capital rotates away from mega-cap growth) -- a PROXY for a fundamental claim, not "
    "a test of it, because this repository has no fundamentals store and the persona's actual method "
    "is P/E and P/B relative valuation, which is unreachable here. No influencer is endorsed and the "
    "persona's own stated positioning disagrees with parts of this field. A factor ETF is also a "
    "bundle whose construction rules this round does not control: VTV is value because an index "
    "provider's screen says so, on a revision schedule invisible in these bars. This card is "
    "purpose=roth and every ticker it trades is absent from every savings- and trading-purpose card "
    "in the library, because Rev. Rul. 2008-5 destroys rather than defers a wash-sale loss whose "
    "replacement is bought inside an IRA. IAU sits in the pinned pool and is traded by nothing here: "
    "it is physical gold and the taxable book holds GLD, the textbook substantially-identical pair, "
    "and ticker disjointness is necessary but NOT sufficient under IRC section 1091 -- nothing here "
    "is a 1091-safety claim. VTI, RSP and SPYG all overlap the S&P 500 the taxable book trades "
    "through SPY: economically close, mechanically disjoint, and said out loud rather than left to be "
    "noticed. The benchmark is SPY, price-only, in USD, which is the wrong yardstick for a value and "
    "mid-cap book measured across a decade of large-cap-growth leadership -- that confound is "
    "pre-registered, and it is the entire reason each slice carries its own passive control so the "
    "round can report tilt-minus-control rather than tilt-versus-SPY. Not a proposal to trade "
    "anything. See strategy-program/ROUND-39-PLAN.md."
)

#: Per-slice prose: what the slice is, and the regime its arm is predicted to fail in. Both halves are
#: carried into every card's `thesis`/`falsification` so a per-card reporter (`PROTOCOL.md` section 2
#: phase 6), who sees only its own card, reads the same pre-registration a scorer does.
SLICE_PROSE: dict[str, tuple[str, str]] = {
    "value": (
        "large-cap value (VTV), the S&P 500 equal-weighted away from its mega-cap concentration "
        "(RSP), and the S&P MidCap 400 (MDY) -- the long side of the structural-stagnation claim",
        "bull-2024 and recent. A value/equal-weight/mid-cap book is on the losing side of the "
        "mega-cap-growth leadership that dominates both windows, so this is where the tilt should "
        "look worst against SPY and where its own passive control should carry most of the damage",
    ),
    "growth": (
        "the S&P 500's own growth half (SPYG) and Nasdaq biotech (IBB), the longest-duration equity "
        "sleeve in the pool -- the side the thesis says loses over a decade",
        "bear-2022. A long-duration growth book is exactly what a rate shock repriced hardest, and "
        "the 10/30 crossover cannot exit fast enough in the first leg of it",
    ),
    "core": (
        "the cap-weighted total US market (VTI), which is the neutral position a style tilt is a tilt "
        "away from, and inflation-linked Treasuries (TIP), the one instrument in the pool that "
        "expresses the 'inflation is inevitable' limb of the same thesis",
        "covid. A V-shaped crash and snapback is where a 200-day regime filter is slowest, and TIP's "
        "price-only bars strip the coupon and the inflation accrual that are most of what a TIPS fund "
        "actually pays -- so this slice is measured on the least representative series in the field",
    ),
    "full": (
        "all seven traded names at once -- value, growth, core and the inflation-linked sleeve "
        "undivided",
        "chop-2015 and chop-2011. Seven names into seven slots means every whipsaw the crossover "
        "suffers is paid seven times over, and both chop windows were cut precisely to expose a "
        "crossover that trades constantly and arrives nowhere",
    ),
}


def build() -> list[StrategyCard]:
    """Round 39's field, in a fixed order: for each of the four slices, one rule-driven tilt card and
    one within-slice passive control -- eight cards.

    Deterministic: no clock, no filesystem read, no randomness, so calling this twice returns two
    field-identical lists. `tests/test_round39_field.py::TestDeterminism` pins that, because a
    generated field that moved between the dry run and the `--write` would mean the frozen cards are
    not the ones whose properties were checked.
    """
    from app.evolution import ruleforms  # local: keeps import cost off `--help`

    entry, exit_rule = ruleforms.render("ma-crossover", fast=FAST, slow=SLOW, regime_ma=REGIME)
    phrase = ruleforms.describe("ma-crossover", fast=FAST, slow=SLOW, regime_ma=REGIME)
    discipline = ruleforms.classify(entry, exit_rule)
    if discipline is None:  # pragma: no cover -- ma-crossover classifies; see the test
        raise RuntimeError("ruleforms.classify does not recognise the ma-crossover form")

    cards: list[StrategyCard] = []
    for slice_name, symbols in SLICES.items():
        slots = len(symbols)
        position_pct = CAPITAL_BUDGET / slots
        what, failure_regime = SLICE_PROSE[slice_name]

        cards.append(
            StrategyCard(
                agent_id=f"r39-{slice_name}-ma",
                display_name=f"R39 style tilt / {slice_name} / {phrase}",
                discipline=discipline,
                purpose=Purpose.ROTH,
                thesis=(
                    f"Round 39 tilt cell. Slice: {what}. One fixed, well-evidenced rule -- "
                    f"{phrase}, rendered by app.evolution.ruleforms rather than retyped -- applied "
                    f"identically to all {slots} name(s) in the slice, with a slot for every name "
                    f"and {position_pct} of the book per slot, so 84% of capital is deployed when "
                    "the rule is fully invested. That is the same budget every card in this field "
                    "carries, tilt arm and control arm alike, so a cross-slice comparison is a "
                    "question about style rather than about book size. There is a slot for every "
                    "name, which means this field has NO slot contention anywhere: no name is ever "
                    "chosen over another, rank_by is unset on every card because there is nothing "
                    "to rank, and the ordering artifact PROTOCOL section 7 measures at sigma = 21.2 "
                    "points cannot operate in this round at all. The only thing separating this "
                    "card from its own passive control (r39-" + slice_name + "-passive) is the "
                    "timing rule -- same names, same slots, same capital, no stop, no target, no "
                    "time stop on either arm -- which is what makes tilt-minus-control an "
                    "attribution to the rule under PROTOCOL section 7's one-decision requirement. "
                    "The style question is answered by the four passive controls compared against "
                    "each other; this arm answers only whether the timing rule adds anything on top "
                    "of the tilt. " + _SHARED_THESIS_TAIL
                ),
                falsification=(
                    "Four conditions, fixed before any bar was read. (1) Wrong about the rule if "
                    f"this card's median exposure-adjusted excess over the eight main windows fails "
                    f"to beat r39-{slice_name}-passive by more than 21.2 percentage points, the "
                    "programme's measured ordering-noise floor -- a margin inside the floor is a "
                    "null whichever side of the control it lands on. (2) Wrong about the style if "
                    "the passive value slice fails to beat the passive growth slice by more than "
                    "21.2pp, which is the claim taken from the vault and the one this round exists "
                    "to test. (3) Beating SPY is NOT the test and failing to beat SPY is NOT the "
                    "falsification: a value/mid-cap book measured against a US large-cap price index "
                    "over 2011-2026 inherits a style headwind no rule inside this engine can close, "
                    "which is the whole reason the control arm exists. (4) The pre-registered "
                    f"failure regime for this slice is {failure_regime}. If this card's worst window "
                    "is somewhere else, the mechanism claimed here is not the mechanism operating, "
                    "and the result needs a different explanation before it needs a promotion -- "
                    "and nothing is promoted from this round regardless."
                ),
                universe=symbols,
                entry=entry,
                exit=exit_rule,
                stop_loss_pct=None,
                take_profit_pct=None,
                max_hold_days=None,
                max_positions=slots,
                position_pct=position_pct,
                rank_by=None,
                designed_through=DESIGN_THROUGH,
            )
        )

        cards.append(
            StrategyCard(
                agent_id=f"r39-{slice_name}-passive",
                display_name=f"R39 style tilt / {slice_name} / passive control",
                discipline=CONTROL_DISCIPLINE,
                purpose=Purpose.ROTH,
                thesis=(
                    f"Round 39's passive control for the {slice_name} slice, and the reason the "
                    f"matching tilt cell can be read at all. Slice: {what}. Entry 'close > 0' is "
                    "true on every bar and exit 'close < 0' on none, with no stop, no target and no "
                    f"time stop, so this card buys all {slots} name(s) at the window's open and "
                    f"holds them to its close at {position_pct} each -- the same 84% capital budget "
                    "every card in this field carries. It is a position, not a strategy, and it is "
                    "in the field to be subtracted, never ranked or promoted. It does two jobs. "
                    "Against its own tilt cell it isolates the timing rule, because the two differ "
                    "in exactly one thing. Against the other three controls it measures the STYLE "
                    "TILT ITSELF, which is this round's actual question and which no rule-driven "
                    "cell can answer: value-passive minus growth-passive is the style spread, "
                    "measured on identical windows through the identical engine. That quantity is "
                    "what the scorecard cannot compute, because this harness scores every card "
                    "against SPY, price-only and in USD -- and a value and mid-cap book measured "
                    "that way over 2011-2026 inherits a decade of large-cap-growth leadership that "
                    "no rule can overcome. Its discipline label is forced: ruleforms.classify "
                    "returns None for a rule with no indicator in it and the Discipline enum has no "
                    "member meaning 'passive', so 'trend' is the least wrong of seven wrong options "
                    "and is not a claim about what this card does. It is a buy-and-hold proxy, not "
                    "an index: it never rebalances, so it drifts away from equal weight across a "
                    "long window, and it deploys 84% rather than 100%. " + _SHARED_THESIS_TAIL
                ),
                falsification=(
                    "This card makes no claim about a rule that can be falsified -- that is what "
                    "makes it a control. It carries one claim that can, and one way to fail. The "
                    "claim: the passive value slice beats the passive growth slice by more than "
                    "21.2 percentage points on median exposure-adjusted excess over the eight main "
                    "windows. That is the vault-derived style thesis stated as a number, it is "
                    "falsified by any margin inside the floor or by the opposite sign, and it is "
                    "predicted here to FAIL -- the honest prior is the programme's rounds 1-33 "
                    "record plus a window mix dominated by large-cap-growth leadership. The way to "
                    f"fail: if this card does not hold all {slots} name(s) on essentially every "
                    "session of every window (session exposure at or near 1.0, one trade per name "
                    "per window), it is not the passive baseline it is being used as, and every "
                    "comparison drawn against it in this round is void. Its own worst window is "
                    "gfc, trivially and by construction."
                ),
                universe=symbols,
                entry=CONTROL_ENTRY,
                exit=CONTROL_EXIT,
                stop_loss_pct=None,
                take_profit_pct=None,
                max_hold_days=None,
                max_positions=slots,
                position_pct=position_pct,
                rank_by=None,
                designed_through=DESIGN_THROUGH,
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
    print(f"built {len(cards)} cards on {len(TRADED)} traded names: {' '.join(TRADED)}")
    print(
        f"  pinned pool is {len(UNIVERSE)} names; held out of every card: "
        + " ".join(EXCLUDED_SUBSTANTIAL_IDENTITY)
        + " (physical gold against the taxable book's GLD -- see the module docstring)"
    )
    print()
    print(
        f"{'agent_id':<20}  {'discipline':<12}  {'slots':>5}  {'pct':>6}  {'budget':>6}  "
        f"{'free#':>5}  universe"
    )
    print("-" * 104)
    for card in cards:
        budget = card.position_pct * card.max_positions
        print(
            f"{card.agent_id:<20}  {card.discipline!s:<12}  {card.max_positions:>5}  "
            f"{card.position_pct:>6}  {budget:>6}  {free_numbers(card):>5}  "
            f"{' '.join(card.universe)}"
        )

    over_budget = [c.agent_id for c in cards if free_numbers(c) > 10]
    print()
    print(
        f"parameter budget: max {max(free_numbers(c) for c in cards)} free numbers per card "
        f"(PROTOCOL section 3 allows 10)"
        + (f" -- OVER BUDGET: {over_budget}" if over_budget else "")
    )
    budgets = {card.position_pct * card.max_positions for card in cards}
    print(
        f"capital budget: {sorted(str(b) for b in budgets)} across all {len(cards)} cells "
        "(identical by construction, so no cell trips PROTOCOL section 4's 2x exposure flag)"
    )
    print(
        "slot contention: none anywhere -- every card has a slot for every name it holds, so "
        "rank_by is unset on all "
        f"{sum(1 for c in cards if c.rank_by is None)} cards and the section 7 ordering artifact "
        "cannot operate in this field"
    )

    # Every expression the runner will guard, parsed here so a syntax error is a build failure rather
    # than a mid-round card failure the runner walks past (PROTOCOL section 8).
    for card in cards:
        grammar.parse(card.entry)
        grammar.parse(card.exit)
        if card.rank_by is not None:
            grammar.parse_ranking(card.rank_by)
    print("grammar: every entry and exit parses")

    taxable, other_cards = claimed_symbols()
    print(
        f"library: {len(taxable)} tickers claimed by {len(other_cards)} savings/trading cards "
        "(recomputed live through app.evolution.promotion._library_cards -- all six tiers)"
    )
    overlap = sorted(set(TRADED) & taxable)
    pool_overlap = sorted(set(UNIVERSE) & taxable)
    violations = find_disjointness_violations([*cards, *other_cards])
    ours = {card.agent_id for card in cards}
    violations = tuple(v for v in violations if v.roth_agent_id in ours)
    if overlap or violations:
        print()
        print("DISJOINTNESS FAILURE -- refusing to author this field.")
        for symbol in overlap:
            print(f"  {symbol} is traded by this round and claimed by the taxable book")
        for violation in violations:
            print(
                f"  {violation.symbol}: {violation.roth_agent_id} (roth) vs "
                f"{violation.other_agent_id} ({violation.other_purpose})"
            )
        return 1
    print(
        "disjointness: no ticker traded by this round is claimed by any savings- or trading-purpose "
        "card, and find_disjointness_violations reports nothing naming one of this round's cards"
    )
    if pool_overlap:  # pragma: no cover -- would mean the pinned pool itself collided
        print(f"  NOTE: pinned-pool names claimed by the taxable book: {' '.join(pool_overlap)}")
    print(
        "  ticker disjointness is NECESSARY, NOT SUFFICIENT under IRC 1091. IAU/GLD is held out "
        "for exactly that reason; VTI, RSP and SPYG all overlap the S&P 500 the taxable book trades "
        "through SPY -- economically close, mechanically disjoint. This is not a 1091-safety claim."
    )

    if not args.write:
        print()
        print("(dry run -- pass --write to author the field)")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    for card in cards:
        path = OUT / f"{card.agent_id}.json"
        path.write_text(
            card.model_dump_json(indent=2, exclude_none=False) + "\n", encoding="utf-8"
        )
    print()
    print(f"wrote {len(cards)} cards to {OUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
