"""Round 44: do the personas' thematic baskets beat a passive control, held passively -- and does
Creator B's profit-trim beat holding the basket?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round44.py           # dry run
    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round44.py --write   # author

`ROUND-44-PLAN.md` is the pre-registration this module executes. Read it first; this file authors the
field and nothing else. The cards are then gated by `strategy-program/tools/disjoint_field.py`, run by
`run_round.sh` and scored by `score.py`, exactly like every other card round.

**The two axes, one decision each.** Rounds 34/35/36/39 varied the *rotation mechanism* -- rule form,
slot cap, fill order, and (round 39) a value/growth style tilt -- always wrapped in some timing rule,
and round 39 additionally measured a style tilt held passively, finding the timing rule loses to
holding the slice in every one of its four cells. **No round has ever measured a named thematic basket
held passively against a passive control** (axis 1 here), and no round has tested a within-basket
profit-trim -- step a name out to cash when it is extended above its own trend, step it back in when
it is not -- as opposed to a full regime switch (axis 2). Both come from
`PERSONA-DISCUSSION-2026-09-09.md` section 4's own triage: "as passive baskets, yes [expressible] ...
never whether a named thematic basket held passively beats a broad passive control" and "a
price-extension trim is expressible ... never a trim-the-winner exit on a held basket".

**Not investment advice. No influencer is endorsed.** Every basket below is this programme's own
construction, built to the *theme* a persona named and to the eligibility/disjointness rules this file
enforces -- not a transcription of any one persona's literal named tickers (`creator-b`'s own roth answer
named EWZ/TSM/IYR, not the `realassets` basket used here; see `ROUND-44-PLAN.md` section 1 for why).
"""

from __future__ import annotations

import argparse
import pathlib
import re
from decimal import Decimal

from app.config import get_settings
from app.db.duck import Interval
from app.evolution.promotion import _library_cards
from app.market.store import read_frame
from app.rules import evaluate, grammar
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from app.tournament.purposes import Purpose, find_disjointness_violations

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r44-2026-09" / "cards"

# ---------------------------------------------------------------------------
# The universe: five baskets of four, pinned before anything was measured
# ---------------------------------------------------------------------------

#: Creator A / Creator D's electricity-infrastructure-as-AI-bottleneck thesis: two regulated
#: utilities, one merchant/renewable utility, one uranium miner. Proxy for "the grid and its fuel",
#: not a literal transcription -- neither persona named a ticker.
POWER: tuple[str, ...] = ("NEE", "DUK", "SO", "CCJ")

#: Creator A's defense-spending pillar: the four largest US pure-play defense primes.
DEFENSE: tuple[str, ...] = ("LMT", "NOC", "GD", "RTX")

#: Creator C / Creator D's semiconductor super-cycle / AI-memory-demand thesis: the three largest
#: US semi-capital-equipment makers plus the sector's other most-cited super-cycle name. Not `SOXX`
#: (launched 2011, fails `gfc`) and not `EWY` (used in `REALASSETS` instead, to keep baskets disjoint
#: from each other).
SEMICAP: tuple[str, ...] = ("AMAT", "KLAC", "LRCX", "ASML")

#: `creator-b` / Creator C's EM/commodity/energy/Korea rotation thesis, expressed as two energy-sector
#: SPDRs, one Korea-country ETF and one broad emerging-markets ETF -- a proxy for the rotation
#: *destination*, not `creator-b`'s own named EWZ/TSM/IYR (TSM would collide with `SEMICAP`'s theme; EWZ
#: and IYR are not GFC-eligible/disjoint-clean in this field).
REALASSETS: tuple[str, ...] = ("XOP", "XME", "EWY", "VWO")

#: The broad, style-neutral passive control -- round 39's own `value` + `growth` pool collapsed to one
#: four-name basket, so this round's control is not a new object the field has to trust for the first
#: time: Vanguard Value, the S&P 500's growth half, the S&P 500 equal-weighted, S&P MidCap 400.
CONTROL: tuple[str, ...] = ("VTV", "SPYG", "RSP", "MDY")

#: name -> tickers, in the pinned display order. `full 4 x 4 = 20` traded names, zero held out (unlike
#: round 39's `IAU`: none of these twenty forms a substantially-identical pair with anything else in
#: this field or with a known taxable holding -- see `ROUND-44-PLAN.md` section 2a).
BASKETS: dict[str, tuple[str, ...]] = {
    "power": POWER,
    "defense": DEFENSE,
    "semicap": SEMICAP,
    "realassets": REALASSETS,
    "control": CONTROL,
}

#: Every traded ticker, basket order preserved, for the reachability probe and the disjointness check.
TRADED: tuple[str, ...] = tuple(sym for names in BASKETS.values() for sym in names)

# ---------------------------------------------------------------------------
# The two arms
# ---------------------------------------------------------------------------

#: Round 39's control expressions, character for character -- both already passed
#: `app.backtest.guards.check` against real bars in round 35, and round 39's nine cards then ran 8 of 8
#: main windows with zero `FAILED` lines. `close > 0` is true on every bar, `close < 0` on none.
PASSIVE_ENTRY = "close > 0"
PASSIVE_EXIT = "close < 0"

#: The extension threshold: a round-number choice (not an outcome read), disclosed as a
#: support-of-regressor read in `ROUND-44-PLAN.md` section 3. `1.15` -- 15% above the 200-day mean --
#: is reachable in every one of the twenty names (section 3a; minimum support 3.8%, `SO`).
TRIM_THRESHOLD = Decimal("1.15")
_REGIME_MA = 200

#: Trim entry (back in the basket / not extended) and exit (step out / extended). The ONLY difference
#: from the passive arm is these two expressions -- same universe, same slots, same size, same absent
#: brackets -- so `trim - passive` is an attribution to the rule alone (`PROTOCOL.md` section 7's
#: one-decision rule).
TRIM_ENTRY = f"close < sma({_REGIME_MA}) * {TRIM_THRESHOLD}"
TRIM_EXIT = f"close > sma({_REGIME_MA}) * {TRIM_THRESHOLD}"

#: `ruleforms.classify` returns `None` for both arms (neither is one of the loop's eight registered
#: forms) -- verified, not assumed: see the module's own test. `passive` is forced to `trend`, the same
#: least-wrong label round 39's controls carry. `trim` is a genuine fit, not a forced one: it is a
#: profit-taking / exposure-reduction discipline applied to a held position, exactly what
#: `Discipline.RISK_MANAGED` describes -- not a directional entry signal.
PASSIVE_DISCIPLINE = Discipline.TREND
TRIM_DISCIPLINE = Discipline.RISK_MANAGED

#: Every card holds all four names in its basket: no slot contention, no `rank_by`, 100% of capital
#: deployed when fully invested (unlike round 39, every basket here is the same size, so there is no
#: fractional-budget normalisation to do).
MAX_POSITIONS = 4
POSITION_PCT = Decimal("0.25")

#: Matches every numeric literal in a rule expression, for the `PROTOCOL.md` section 3 budget. Same
#: pattern round35/round39/round40 use.
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def free_numbers(card: StrategyCard) -> int:
    """`PROTOCOL.md` section 3's parameter count: distinct numeric *values* across `entry`, `exit`,
    `rank_by`, plus one per present bracket, plus two for `max_positions`/`position_pct`. Identical
    derivation to `round35.py`/`round39.py`/`round40.py`, so budgets are directly comparable.
    """
    text = " ".join(part for part in (card.entry, card.exit, card.rank_by or "") if part)
    values = {match.group(0) for match in _NUMBER.finditer(text)}
    brackets = sum(
        1
        for field in (card.stop_loss_pct, card.take_profit_pct, card.max_hold_days)
        if field is not None
    )
    return len(values) + brackets + 2  # + max_positions + position_pct


def claimed_symbols() -> tuple[frozenset[str], list[object]]:
    """`(tickers claimed by the taxable book, the non-roth cards that claim them)`, from the **live**
    library on disk -- identical derivation to `round39.py::claimed_symbols`, through
    `app.evolution.promotion._library_cards` (all six tiers, including `allocation/` and `ladder/`,
    which `app.tournament.results.load_library` does not walk and which are the only place five
    taxable tickers -- AGG, BIL, QLD, SCHD, SGOV -- are claimed).

    Recomputed rather than hardcoded: this repository is edited by concurrent sessions and a ticker
    list pasted into a constant is correct exactly until the next commit.
    """
    others = [
        card
        for card in _library_cards(get_settings())
        if card.purpose in (Purpose.SAVINGS, Purpose.TRADING)
    ]
    symbols = frozenset(symbol for card in others for symbol in card.universe)
    return symbols, others


# ---------------------------------------------------------------------------
# Reachability / support probe -- read_frame + grammar.parse + evaluate.evaluate, bounded to
# DESIGN_THROUGH. Same method `round40.py`'s reachability gate uses.
# ---------------------------------------------------------------------------


def support_table(settings) -> dict[str, dict[str, object]]:
    """Per-symbol: first bar, session count, extended-condition ("close > sma(200) * 1.15") fires and
    support fraction, over `[first bar, DESIGN_THROUGH]`.

    An in-memory read (`read_frame`, no file lock -- safe alongside other readers) and the real
    evaluator, so a "fire" is exactly a session on which the trim arm's exit condition -- equivalently,
    the passive arm never sees, since the passive arm has no such condition -- would have been true.
    `ROUND-44-PLAN.md` section 3a is this table, computed once here and reproduced there.
    """
    tree = grammar.parse(f"close > sma({_REGIME_MA}) * {TRIM_THRESHOLD}")
    table: dict[str, dict[str, object]] = {}
    for symbol in TRADED:
        frame = read_frame(symbol, Interval.DAY, end=DESIGN_THROUGH, settings=settings)
        if frame.empty:
            table[symbol] = {
                "first_bar": None, "sessions": 0, "fires": 0, "support": None,
            }
            continue
        first_bar = frame["ts"].iloc[0].date()
        sessions = len(frame)
        series = evaluate.evaluate(tree, frame, interval=Interval.DAY)
        fires = int(series.fillna(False).astype(bool).sum())
        table[symbol] = {
            "first_bar": first_bar,
            "sessions": sessions,
            "fires": fires,
            "support": (fires / sessions) if sessions else None,
        }
    return table


def _thesis(basket: str, arm: str, names: tuple[str, ...]) -> str:
    what = {
        "power": (
            "Creator A's and Creator D's electricity-infrastructure-as-AI-bottleneck thesis: two "
            "regulated utilities (NEE, DUK), one merchant/renewable utility (SO), one uranium miner "
            "(CCJ) -- a proxy for 'the grid and its fuel', not a literal transcription of either "
            "persona's named tickers, neither of whom stated one."
        ),
        "defense": (
            "Creator A's defense-spending pillar: the four largest US pure-play defense primes "
            "(LMT, NOC, GD, RTX)."
        ),
        "semicap": (
            "Creator C's and Creator D's semiconductor super-cycle / AI-memory-demand thesis: the "
            "three largest US semiconductor-capital-equipment makers (AMAT, KLAC, LRCX) plus the "
            "sector's other most-cited super-cycle name (ASML) -- not SOXX (launched 2011, fails the "
            "gfc window) and not EWY (used in the realassets basket instead, to keep this round's "
            "baskets disjoint from each other)."
        ),
        "realassets": (
            "wsaj's and Creator C's EM/commodity/energy/Korea rotation thesis, expressed as two "
            "energy-sector SPDRs (XOP, XME), one Korea-country ETF (EWY) and one broad "
            "emerging-markets ETF (VWO) -- a proxy for the rotation DESTINATION, not wsaj's own named "
            "EWZ/TSM/IYR (TSM would collide with the semicap basket's theme; EWZ/IYR are not this "
            "field's GFC-eligible, disjoint-clean instruments)."
        ),
        "control": (
            "The broad, style-neutral passive control: round 39's own value+growth pool (VTV, SPYG, "
            "RSP, MDY) collapsed to one four-name basket, so this round's control is not a new object "
            "the field has to trust for the first time -- round 39 already measured these four "
            "against each other and found the style spread null."
        ),
    }[basket]
    common = (
        f"Round 44 {arm} cell. Basket ({basket}): {what} Universe: {' '.join(names)}. "
        "Purpose ROTH: no ticker this round trades is claimed by any savings- or trading-purpose "
        "card in the live library (app.evolution.promotion._library_cards, all six tiers), because "
        "Rev. Rul. 2008-5 destroys rather than defers a wash-sale loss whose replacement is bought "
        "inside an IRA. Five of these twenty names (AMAT, KLAC, LRCX, XOP, XME) ARE already held by "
        "other roth-purpose cards elsewhere in the library -- legal and disclosed: "
        "find_disjointness_violations only ever compares a roth card against the TAXABLE universe, "
        "and roth-to-roth overlap creates no wash-sale exposure under Rev. Rul. 2008-5, since nothing "
        "is ever repurchased inside the taxable book. Ticker disjointness from the taxable book is "
        "NECESSARY, not sufficient, under IRC section 1091; nothing here is a section 1091-safety "
        "claim. The Roth benchmark is SPY, price-only, no dividends -- none of these five baskets is "
        "a US large-cap-growth book, so a raw adjusted_excess-vs-SPY reading is not this round's "
        "decision quantity for any basket; the decision quantities are basket-minus-control (does "
        "the theme beat a broad passive control, held passively) and trim-minus-passive (does "
        "stepping a name to cash above its own 200-day*1.15 extension beat holding it). Every note "
        "in the persona corpus that produced this hypothesis has published=null "
        "(PERSONA-HYPOTHESES.md), so the bull-2024 and recent windows are IN-SAMPLE to the "
        "hypothesis and any positive result confined to them is hindsight, not a finding -- the fair "
        "test is the six windows ending by 2022-10 (gfc, chop-2011, chop-2015, q4-2018, covid, "
        "bear-2022), reported separately. Pre-registered 2026-09-09, before any card ran. Not "
        "investment advice; no influencer is endorsed. See strategy-program/ROUND-44-PLAN.md."
    )
    return common


def _falsification(basket: str, arm: str) -> str:
    floor = (
        "Pre-registered decision rule (PROTOCOL.md section 7 floor, 21.2pp): a basket edge requires "
        f"median(r44-{basket}-passive) minus median(r44-control-passive) > 21.2pp AND BH q<0.10 over "
        "all 10 cells this round runs; a trim edge requires "
        f"median(r44-{basket}-trim) minus median(r44-{basket}-passive) > 21.2pp AND the same BH "
        "q<0.10. A margin inside the floor is a null whichever side it lands on, and the "
        "pre-registered prediction is null on both axes (39 prior rounds found every basket- and "
        "rule-margin this programme has ever measured inside this floor). "
    )
    if arm == "passive":
        return floor + (
            "This is the basket-question card. Predicted worst window: covid for realassets and "
            "power (both hold a commodity/rate-sensitive name that gapped hardest in the March 2020 "
            "crash); chop-2011/chop-2015 for defense and semicap (trendless whipsaw against a "
            "buy-and-hold-forever position has no mechanism to hurt it, so its own worst window is "
            "structural, not thematic). Nothing is promoted from this round regardless of outcome."
        )
    return floor + (
        f"This is the rule-question card, matched to r44-{basket}-passive by universe, slots, size and "
        "absent brackets -- the two differ in exactly one thing (PROTOCOL.md section 7). Predicted "
        "to UNDERPERFORM its own passive control in bull-2024 and recent (sustained uptrends give "
        "the trim's stop-out nothing to avoid and only cost re-entry lag), and to have its best "
        "chance of beating it in bear-2022 and gfc, where a run-up-then-reversal sequence is most "
        "plausible. Exposure prediction: trim sits out most in this basket if it is semicap "
        "(mean support ~34%, ROUND-44-PLAN.md section 3a) and least if it is power (~11%, driven by "
        "SO's 3.8% and DUK's 4.6%). Nothing is promoted from this round regardless of outcome."
    )


def build() -> list[StrategyCard]:
    """Round 44's field, in a fixed order: for each of the five baskets, one passive control card and
    one trim card -- ten cards.

    Deterministic: no clock, no filesystem read, no randomness, so calling this twice returns two
    field-identical lists (`tests/test_round44_field.py::TestDeterminism`).
    """
    cards: list[StrategyCard] = []
    for basket, names in BASKETS.items():
        cards.append(
            StrategyCard(
                agent_id=f"r44-{basket}-passive",
                display_name=f"R44 basket / {basket} / passive",
                discipline=PASSIVE_DISCIPLINE,
                purpose=Purpose.ROTH,
                thesis=_thesis(basket, "passive", names),
                falsification=_falsification(basket, "passive"),
                universe=names,
                entry=PASSIVE_ENTRY,
                exit=PASSIVE_EXIT,
                stop_loss_pct=None,
                take_profit_pct=None,
                max_hold_days=None,
                max_positions=MAX_POSITIONS,
                position_pct=POSITION_PCT,
                rank_by=None,
                designed_through=DESIGN_THROUGH,
            )
        )
        cards.append(
            StrategyCard(
                agent_id=f"r44-{basket}-trim",
                display_name=f"R44 basket / {basket} / trim above 200dma*1.15",
                discipline=TRIM_DISCIPLINE,
                purpose=Purpose.ROTH,
                thesis=_thesis(basket, "trim", names),
                falsification=_falsification(basket, "trim"),
                universe=names,
                entry=TRIM_ENTRY,
                exit=TRIM_EXIT,
                stop_loss_pct=None,
                take_profit_pct=None,
                max_hold_days=None,
                max_positions=MAX_POSITIONS,
                position_pct=POSITION_PCT,
                rank_by=None,
                designed_through=DESIGN_THROUGH,
            )
        )
    return cards


def _print_support(table: dict[str, dict[str, object]]) -> None:
    print(f"support (fraction of sessions close > sma({_REGIME_MA}) * {TRIM_THRESHOLD}), bounded to "
          f"{DESIGN_THROUGH.isoformat()}:")
    print(f"  {'symbol':<8}{'first_bar':<14}{'sessions':>10}{'fires':>10}{'support':>10}")
    for basket, names in BASKETS.items():
        print(f"  -- {basket} --")
        for symbol in names:
            row = table[symbol]
            support = row["support"]
            support_txt = "n/a" if support is None else f"{support:.1%}"
            print(
                f"  {symbol:<8}{row['first_bar']!s:<14}{row['sessions']:>10}"
                f"{row['fires']:>10}{support_txt:>10}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the cards to the round directory")
    args = parser.parse_args(argv)

    settings = get_settings()
    cards = build()
    print(f"built {len(cards)} cards on {len(TRADED)} traded names across {len(BASKETS)} baskets: "
          + " ".join(TRADED))
    print()
    print(
        f"{'agent_id':<20}  {'discipline':<14}  {'slots':>5}  {'pct':>6}  {'free#':>5}  universe"
    )
    print("-" * 100)
    for card in cards:
        print(
            f"{card.agent_id:<20}  {card.discipline!s:<14}  {card.max_positions:>5}  "
            f"{card.position_pct:>6}  {free_numbers(card):>5}  {' '.join(card.universe)}"
        )

    over_budget = [c.agent_id for c in cards if free_numbers(c) > 10]
    print()
    print(
        f"parameter budget: max {max(free_numbers(c) for c in cards)} free numbers per card "
        "(PROTOCOL section 3 allows 10)"
        + (f" -- OVER BUDGET: {over_budget}" if over_budget else "")
    )

    # Every expression the runner will guard, parsed here so a syntax error is a build failure rather
    # than a mid-round card failure the runner walks past (PROTOCOL.md section 8).
    for card in cards:
        grammar.parse(card.entry)
        grammar.parse(card.exit)
    print("grammar: every entry and exit parses")

    # Reachability / support probe -- printed on both the dry run and the write, and the reason the
    # tool can refuse before anything is written.
    print()
    table = support_table(settings)
    _print_support(table)
    zero_fire = [s for s, row in table.items() if row["fires"] == 0]
    min_support_sym = min(
        (s for s in table if table[s]["support"] is not None), key=lambda s: table[s]["support"]
    )
    print()
    print(
        f"minimum support in the field: {min_support_sym} at "
        f"{table[min_support_sym]['support']:.1%} ({table[min_support_sym]['fires']} fires)"
    )

    refusals: list[str] = []
    if zero_fire:
        refusals.append(
            f"trim condition fires 0 times for: {', '.join(zero_fire)} -- structurally unreachable"
        )
    if over_budget:
        refusals.append(f"parameter budget: over 10 free numbers: {over_budget}")

    taxable, other_cards = claimed_symbols()
    print(
        f"library: {len(taxable)} tickers claimed by {len(other_cards)} savings/trading cards "
        "(recomputed live through app.evolution.promotion._library_cards -- all six tiers)"
    )
    overlap = sorted(set(TRADED) & taxable)
    violations = find_disjointness_violations([*cards, *other_cards])
    ours = {card.agent_id for card in cards}
    violations = [v for v in violations if v.roth_agent_id in ours]
    if overlap:
        refusals.append(f"taxable overlap: {overlap}")
    for violation in violations:
        refusals.append(
            f"find_disjointness_violations: {violation.symbol}: {violation.roth_agent_id} (roth) vs "
            f"{violation.other_agent_id} ({violation.other_purpose})"
        )

    if refusals:
        print()
        print("DISJOINTNESS / REACHABILITY FAILURE -- refusing to author this field.")
        for r in refusals:
            print(f"  {r}")
        return 1
    print(
        "disjointness: no ticker traded by this round is claimed by any savings- or trading-purpose "
        "card, and find_disjointness_violations reports nothing naming one of this round's cards"
    )
    print(
        "  (roth-to-roth overlap on AMAT/KLAC/LRCX/XOP/XME against other roth-purpose cards is real "
        "and legal -- see ROUND-44-PLAN.md section 2a. ticker disjointness is NECESSARY, NOT "
        "SUFFICIENT under IRC 1091; this is not a 1091-safety claim.)"
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
