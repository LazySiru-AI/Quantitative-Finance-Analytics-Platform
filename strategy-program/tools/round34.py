"""Round 34: does round 17's form null replicate one level below the sector?

    PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round34.py --write

`ROUND-34-PLAN.md` is the pre-registration this executes. Read it first. **The round has not been
run**; this tool only authors its field, which `strategy-program/tools/run_round.sh` then runs and
`score.py` scores, exactly like every other card round.

**The question.** Round 17 ran an 8-form x regime x 3-bracket factorial on the nine full-history GICS
sector SPDRs and found every marginal inside this programme's 21.2pp noise floor: form 7.56pp, the
regime filter inside the floor, brackets 0.14pp and effectively never binding. That is one universe.
Sector ETFs are cap-weighted aggregates of many industries, so a rule's signal is averaged over the
dispersion the sector contains before the rule ever sees it. **Industries disperse more than sectors**
-- and a null measured on the smoother of the two universes is the weaker null. If strategy form ever
changes a result, it should change it here first. So this round re-asks round 17's question on a
universe that shares not one ticker with it: a pre-registered replication with a pre-registered
"form matters after all" alternative, stated in `ROUND-34-PLAN.md` section 5 before any measurement.

**Why the field is generated rather than hand-written**, unchanged from round 17: the eight forms are
already defined in code, in `app.evolution.ruleforms.RENDERERS`, and re-typing them into JSON would
create a second, drifting copy of a vocabulary that already exists. Entry and exit text come from
`ruleforms.render`, the discipline label from `ruleforms.classify` and the thesis clause from
`ruleforms.describe` -- the same derivation the evolution loop uses -- so this round compares the
eight forms **as the loop actually emits them**, and compares them to round 17 on identical rendering.

**The field is 8 forms x regime on/off = 16 cells, and the bracket factor is gone.** Round 17
measured `none`, `stop` and `stop-tp` as differing by 0.14pp across its whole 48-cell field, with many
cells byte-identical between bracket policies because the rule's own exit fires first almost every
time. Carrying that factor here would spend three times the runtime on a contrast already published as
empty. Dropping levels from a *published* result before any round-34 card exists is a design decision
taken in the open, not a mid-round narrowing -- the identical move `ROUND-18-PLAN.md` section 2 made
for the same reason, from the same finding. The surviving level is `stop` (0.12 stop, 180-day hold
cap, no target), round 17's own middle level.

**The universe is the eight SPDR/iShares/Vanguard industry baskets one level below the GICS sectors**,
pinned in `UNIVERSE` and identical to round 36's so the two rounds stay comparable. It is
mechanically defined, was not chosen by looking at returns, and -- the binding constraint of this
round -- shares no ticker with any `savings`- or `trading`-purpose card in the live library. See
`_taxable_symbols` and `check_disjointness`: that is verified against the library **at build time**,
and `--write` refuses on a violation rather than authoring a card that would have to be withdrawn.

**Why disjointness is the constraint.** These cards carry `purpose = Purpose.ROTH`. Rev. Rul. 2008-5
holds that a loss realised in a taxable account and replaced inside an IRA within 30 days is
disallowed outright, with no basis adjustment anywhere -- strictly worse than an ordinary wash sale,
which only defers. `app.tournament.purposes.find_disjointness_violations` is the check;
`backend/app/tax/washsale.py` models what it prevents. **Ticker disjointness is necessary, not
sufficient**: IRC 1091's substantially-identical test is about the securities, not the symbols, the
IRS has never ruled on ETF pairs of this kind, and nothing here claims this roster is 1091-safe.
`XSD` tracks the equal-weight S&P Semiconductor Select Industry index -- not `SOXX`'s PHLX SOX, not
`SMH`'s MVIS index -- and `XOP` is equal-weight E&P rather than `XLE`'s cap-weighted sector; those are
real differences in what is held, offered as the honest description they are and not as a legal
opinion.

**Nothing here is tuned.** `fast`/`slow`/`regime_ma` are 10/30/200, the same three periods round 17
used, and every threshold inside a form (RSI 40/55/60, Bollinger 2 sigma, MACD's 9-bar signal, the
2%/5% ATR band) is the textbook constant frozen in `ruleforms.py` on 2026-08-26, before either round
was conceived. `designed_through` is the programme's own `DESIGN_THROUGH`. No parameter in this field
was chosen by looking at an outcome, and no grid was searched to arrive at one.

**What this tool touches.** The library JSON (read-only, for the disjointness check) and the round's
own cards directory. Nothing here reads `data/accounts.toml`, `data/sectors.toml`,
`data/store/ledger.sqlite` or anything under `app.tax`; the cards it writes read only the Parquet /
DuckDB bar store, like every other card in this programme.

**Not investment advice.**
"""

from __future__ import annotations

import argparse
import pathlib
from collections.abc import Sequence
from decimal import Decimal

from app.evolution import ruleforms
from app.evolution.models import RULE_SHAPES
from app.rules import grammar
from app.tournament.allocation import AllocationCard
from app.tournament.ladder import LadderCard
from app.tournament.models import DESIGN_THROUGH, StrategyCard
from app.tournament.purposes import (
    DisjointnessViolation,
    Purpose,
    find_disjointness_violations,
)
from app.tournament.results import LIBRARY_ROOT, load_library

REPO = pathlib.Path(__file__).resolve().parents[2]

OUT = REPO / "data" / "rounds" / "r34-2026-09" / "cards"

#: The eight industry baskets one level below the GICS sectors: SPDR's S&P Select Industry funds for
#: metals & mining, retail, homebuilders, semiconductors and oil & gas E&P, SPDR's biotech basket,
#: iShares aerospace & defense, and Vanguard's REIT fund. Mechanically defined by the index each
#: tracks, not assembled from a thesis, and not chosen by looking at returns.
#:
#: **Pinned. Round 36 uses this identical tuple**, so the two rounds stay comparable name for name;
#: changing it here silently decouples them.
#:
#: First stored daily bars: `XHB`/`XSD`/`XBI` 2006-02-06, `ITA` 2006-05-05, `XME`/`XRT`/`XOP`
#: 2006-06-22, `VNQ` 2004-09-29. The binding symbol is therefore 2006-06-22 against the `gfc`
#: window's deadline of 2006-10-26 for a 200-day indicator (200 warmup + 40 causality bars, converted
#: to calendar days by `windows._bars_to_calendar_days`), so **all eight windows are eligible for all
#: sixteen cells** -- verified with `strategy-program/tools/windows.py --cards <this round's cards>`
#: before the field was frozen, not assumed. Round 17's Amendment 1 is the reason that check is run
#: rather than reasoned about: there, two ETFs with zero bars in a window did not merely contribute
#: nothing, they failed the whole card, and the round lost three windows to it.
UNIVERSE: tuple[str, ...] = (
    "XME", "XRT", "XHB", "XSD", "XOP", "XBI", "ITA", "VNQ",
)

#: `IBB` was considered and deliberately excluded, and the reason is recorded here rather than left
#: to be rediscovered: it is a second biotech basket duplicating `XBI`'s exposure. Two baskets of the
#: same industry inside an eight-name universe would give that industry a quarter of the roster and
#: two of four slots, so a form that happens to suit biotech would be credited twice -- and under
#: this programme's Benjamini-Hochberg correction (`PROTOCOL.md` section 3 rule 8) a redundant name
#: costs every other cell without buying any independent evidence. This is the exclusion
#: `c20-rotation`'s thesis makes in prose ("building the same basket again under a different label
#: would be one hypothesis wearing two names"), applied to a universe instead of to a card.
EXCLUDED_FOR_DUPLICATION: tuple[str, ...] = ("IBB",)

FAST, SLOW, REGIME = 10, 30, 200

#: The regime conjunct every form carries, in the exact text `render` emits.
REGIME_CLAUSE = f"close > sma({REGIME})"

#: Round 17's middle bracket level, and the only one this round runs. See the module docstring.
BRACKET: dict[str, object] = {
    "stop_loss_pct": Decimal("0.12"),
    "take_profit_pct": None,
    "max_hold_days": 180,
}

#: Four slots at 20% -- **round 17 used six at 15%, and the change is deliberate and is a cost.**
#:
#: Maximum commitment is 0.80 against round 17's 0.90, so the two rounds' books are of comparable
#: size for `adjusted_excess`, whose exposure term is not commensurable across differently-sized books
#: (`PROTOCOL.md` section 4). What changes is how often the cap binds: six slots over eight names is
#: 75% of the roster, so the cap would almost never bind and every form would converge on holding the
#: whole basket whenever it was invested -- which would confirm this round's null *by construction*
#: rather than by measurement, and would be the fairest possible criticism of a null result here.
#: Four of eight makes the entry rule select.
#:
#: The cost, stated so it cannot be discovered later: a harder-binding cap means the `universe` write
#: order decides more ties, and this field leaves `rank_by` unset like every card this programme has
#: published. So round 34 carries *more* ordering exposure than round 17 did, not less, and the
#: 21.2pp floor is not lowered on the strength of round 17's ~1pp ordering replication (which was
#: measured on a different universe with a different cap).
MAX_POSITIONS = 4
POSITION_PCT = Decimal("0.20")


def strip_regime(entry: str) -> str | None:
    """`entry` with its `close > sma(200)` conjunct removed, or `None` if it has none.

    String surgery on a rendered rule, then re-parsed -- never a hand-written second copy of the
    rule. `render` emits the conjunct in one of two positions depending on the form (leading for
    `ma-crossover`, trailing for `channel-breakout`), so both are handled and the result is validated
    by the real grammar before it is allowed into a card. A form whose regime clause cannot be
    removed cleanly is dropped from the `off` arm and reported, rather than being approximated.

    **This is a deliberate copy of `round17.strip_regime`, not an import.** Round 17's field is frozen
    and its cards are committed; a shared helper would mean a later edit here could silently change
    what round 17's tool would regenerate, which is exactly the "cards are immutable after phase 2"
    boundary `PROTOCOL.md` section 2 draws. Two rounds, two copies, and this note so the duplication
    reads as a decision.

    **Only the entry is stripped, matching round 17.** `vol-compression`'s *exit* also names
    `close crosses_below sma(200)`; it is left alone in both arms, so the `off` cell of that one form
    removes the regime filter from the entry and not from the exit. That is round 17's behaviour
    reproduced exactly, which is what makes the two rounds' regime marginals comparable, and it is
    stated here because it is the one place the factor is not perfectly clean.
    """
    for candidate in (
        entry.replace(f"{REGIME_CLAUSE} and ", "", 1),
        entry.replace(f" and {REGIME_CLAUSE}", "", 1),
    ):
        if candidate != entry:
            grammar.parse(candidate)  # raises if the surgery produced nonsense
            return candidate
    return None


def library_purposed_cards() -> list[StrategyCard | AllocationCard | LadderCard]:
    """Every purposed card in the live library, across all six tiers on disk.

    `app.tournament.results.load_library` covers `base`/`variants`/`candidates`/`retired`, which are
    the four tiers holding `StrategyCard`s. It does **not** cover `allocation/` and `ladder/`, whose
    files are `AllocationCard`s and `LadderCard`s and would fail `StrategyCard` validation -- and
    those two tiers are where `AGG`, `BIL`, `QLD`, `SCHD`, `SGOV`, `IEF` and the shipped Roth ladder
    live. Checking disjointness against `load_library()` alone would therefore miss five taxable
    tickers and quietly weaken the invariant this round exists under, so both are read here.

    All three shapes expose `.agent_id`, `.purpose` and `.universe`, which is exactly the structural
    contract `app.tournament.purposes._PurposedCard` states and `find_disjointness_violations`
    consumes -- see that function's docstring for why `.universe` (what a card can own a lot in) is
    the right field and a ladder's `signal_symbol` is deliberately not checked.
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


def taxable_symbols(
    library: Sequence[StrategyCard | AllocationCard | LadderCard],
) -> frozenset[str]:
    """Every symbol any `savings`- or `trading`-purpose card in `library` can own a position in.

    Recomputed from the library on every call rather than pinned as a literal, because the library is
    edited concurrently by other work in this programme (`load_library`'s own docstring says so) and a
    hardcoded roster would pass this check against a list that no longer describes the taxable book.
    """
    return frozenset(
        symbol
        for card in library
        if card.purpose in (Purpose.SAVINGS, Purpose.TRADING)
        for symbol in card.universe
    )


def check_disjointness(
    cards: Sequence[StrategyCard],
    library: Sequence[StrategyCard | AllocationCard | LadderCard],
) -> tuple[tuple[DisjointnessViolation, ...], tuple[DisjointnessViolation, ...]]:
    """`(mine, pre_existing)` -- disjointness violations this round's cards cause, and everyone else's.

    Both come from one `find_disjointness_violations` call over the library and this round's cards
    together, which is the only way to see a collision between a new card and an old one. They are
    split because they mean different things and warrant different actions: a violation naming one of
    `cards` is this round's fault and blocks `--write`; a violation between two cards already on disk
    is a real finding about the library that this tool should surface rather than swallow, but it is
    not a reason to refuse to author a field that does not participate in it.
    """
    mine_ids = {card.agent_id for card in cards}
    violations = find_disjointness_violations([*library, *cards])
    return (
        tuple(v for v in violations if v.roth_agent_id in mine_ids),
        tuple(v for v in violations if v.roth_agent_id not in mine_ids),
    )


def _falsification(shape: str, regime_state: str) -> str:
    """The pre-registered failure regime for one cell, per `PROTOCOL.md` section 3 rule 5.

    Named per form rather than once for the round, because the forms fail in different regimes and a
    single sentence covering all eight would be a slogan rather than a prediction. Each names an
    observation somebody other than the author could make from the round's own trade logs.
    """
    trend_family = {"ma-crossover", "momentum-state", "macd-cross", "vol-compression"}
    if shape in trend_family:
        specific = (
            "This cell's thesis is that a trend/momentum trigger earns something on an "
            "industry basket. It is falsified if this cell's worst adjusted excess is not in "
            "`chop-2011` or `chop-2015` -- the two directionless windows a trend rule is "
            "supposed to hate -- because then whatever it earned or lost was not the "
            "whipsaw mechanism its form claims to be exposed to."
        )
    elif shape in {"rsi-pullback", "band-reversion"}:
        specific = (
            "This cell's thesis is that buying weakness inside strength earns something on an "
            "industry basket. It is falsified if this cell's worst adjusted excess is not in "
            "`gfc`, `covid` or `bear-2022` -- a mean-reversion rule that buys every dip is "
            "supposed to be worst in a sustained decline, and if it is not, the form is not "
            "doing what its label says."
        )
    else:
        specific = (
            "This cell's thesis is that a breakout trigger earns something on an industry "
            "basket. It is falsified if this cell's worst adjusted excess is not in "
            "`chop-2011` or `chop-2015` -- a breakout rule in a directionless market is "
            "supposed to buy the failed break repeatedly, and if that is not where it hurts, "
            "the form's exposure is not what it claims."
        )
    return (
        specific
        + " The round-level falsification, which this cell contributes one observation to, is "
        "in `strategy-program/ROUND-34-PLAN.md` section 5: round 17's null replicates unless "
        "the eight form-marginals span more than 21.2 percentage points AND the best-versus-"
        "worst contrast survives Benjamini-Hochberg over all sixteen cells run. "
        + (
            "This cell is the regime-filter-removed half of its pair, so it also falsifies "
            "the claim that the 200-day filter is load-bearing: if the two regime marginals "
            "differ by less than 21.2pp, six of eight forms carry that conjunct on convention "
            "alone, on industries as well as on sectors."
            if regime_state == "off"
            else "This cell is the regime-filter-on half of its pair."
        )
    )


def build() -> tuple[list[StrategyCard], list[str]]:
    """The round's sixteen cards, and a note for every cell that could not be authored.

    Deterministic: same inputs, same order, byte-identical model dumps. `RULE_SHAPES` is a fixed
    tuple, the regime arm order is fixed, and nothing here reads a clock, a random source, the bar
    store or the filesystem.
    """
    cards: list[StrategyCard] = []
    skipped: list[str] = []

    for shape in RULE_SHAPES:
        entry_on, exit_rule = ruleforms.render(shape, fast=FAST, slow=SLOW, regime_ma=REGIME)
        entry_off = strip_regime(entry_on)
        described = ruleforms.describe(shape, fast=FAST, slow=SLOW, regime_ma=REGIME)

        for regime_state in ("on", "off"):
            entry = entry_on if regime_state == "on" else entry_off
            if entry is None:
                skipped.append(f"{shape}/regime-off: form carries no {REGIME_CLAUSE!r} conjunct")
                continue

            discipline = ruleforms.classify(entry, exit_rule)
            if discipline is None:
                skipped.append(
                    f"{shape}/regime-{regime_state}: classifier does not recognise the rule"
                )
                continue

            cards.append(
                StrategyCard(
                    agent_id=f"r34-{shape}-{regime_state}",
                    display_name=f"{shape} / regime {regime_state} / industries",
                    discipline=discipline,
                    purpose=Purpose.ROTH,
                    thesis=(
                        f"Round 34 replication cell. Form: {described}"
                        # `describe` always names the regime filter, because the canonical form
                        # carries one. On the `off` arm that would make the card's own prose
                        # contradict its own entry rule, so the removal is stated explicitly rather
                        # than left to a reader to notice.
                        + (
                            " -- but with the 200-day SMA regime filter REMOVED from the entry for "
                            "this cell, which is the paired half of this round's second factor."
                            if regime_state == "off"
                            else "."
                        )
                        + " Brackets: stop only (12% stop, 180-day hold cap, no target), because "
                        "round 17 measured the three bracket policies as differing by 0.14pp "
                        "across its whole 48-cell field. This card is one cell of a pre-registered "
                        "8x2 grid asking a single question: does round 17's finding -- that form, "
                        "the regime filter and brackets all sit inside this programme's 21.2 "
                        "percentage point noise floor -- replicate out of sample on a universe one "
                        "level below the sector? Sector ETFs average a rule's signal over the "
                        "dispersion the sector already contains; industry baskets do not, so if "
                        "form ever changes a result it should change it here first, and a null "
                        "measured here is a stronger null than round 17's. It is not a proposal to "
                        "trade anything and nothing in this round will be promoted. The universe is "
                        f"the eight industry baskets {' '.join(UNIVERSE)} -- mechanically defined by "
                        "the index each tracks, not thesis-picked, and sharing no ticker with any "
                        "savings- or trading-purpose card in the library, which is the condition "
                        "this card's roth purpose imposes (Rev. Rul. 2008-5 destroys a wash-sale "
                        "loss outright when an IRA buys the replacement). Ticker disjointness is "
                        "necessary and not sufficient under IRC 1091, and no claim is made here "
                        "that the roster is substantially different from anything the taxable book "
                        "holds. Every parameter is the textbook constant frozen in "
                        "app.evolution.ruleforms before either round was conceived; nothing here "
                        "was tuned. See strategy-program/ROUND-34-PLAN.md for the pre-registration, "
                        "the decision rule and the six falsifiable predictions."
                    ),
                    falsification=_falsification(shape, regime_state),
                    universe=UNIVERSE,
                    entry=entry,
                    exit=exit_rule,
                    max_positions=MAX_POSITIONS,
                    position_pct=POSITION_PCT,
                    designed_through=DESIGN_THROUGH,
                    **BRACKET,  # type: ignore[arg-type]
                )
            )
    return cards, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the cards to the round directory")
    args = parser.parse_args(argv)

    cards, skipped = build()

    print(f"built {len(cards)} cards over {len(RULE_SHAPES)} forms x 2 regime arms")
    for note in skipped:
        print(f"  skipped: {note}")

    by_discipline: dict[str, int] = {}
    for card in cards:
        by_discipline[str(card.discipline)] = by_discipline.get(str(card.discipline), 0) + 1
    print("  derived disciplines:", by_discipline)
    print(f"  universe ({len(UNIVERSE)}):", " ".join(UNIVERSE))
    print("  excluded as a duplicate basket:", " ".join(EXCLUDED_FOR_DUPLICATION))

    library = library_purposed_cards()
    taxable = taxable_symbols(library)
    overlap = sorted(set(UNIVERSE) & taxable)
    mine, pre_existing = check_disjointness(cards, library)

    print(
        f"  disjointness: {len(library)} purposed cards in the library, "
        f"{len(taxable)} distinct savings/trading symbols"
    )
    print(f"  universe overlap with the taxable book: {overlap or 'none'}")
    for violation in pre_existing:
        print(f"  PRE-EXISTING (not this round): {violation.message}")

    if mine or overlap:
        print()
        print("REFUSING to author this field -- it intersects the taxable research:")
        for violation in mine:
            print(f"  {violation.message}")
        for symbol in overlap:
            print(f"  {symbol} is in this round's universe and in a savings/trading card's")
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
        path.write_text(card.model_dump_json(indent=2, exclude_none=False) + "\n", encoding="utf-8")
    print(f"\nwrote {len(cards)} cards to {OUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
