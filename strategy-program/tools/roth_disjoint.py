"""Re-express the drawdown ladder (`strategy-program/DRAWDOWN-LADDER.md`,
`backend/app/paper/library/ladder/qld-schd-ief.json`) on tickers that share nothing with a taxable
account, and price what that substitution costs.

**Why disjointness matters more than it sounds like it should.** An ordinary wash sale merely
*defers* a disallowed loss into the replacement lot's basis -- annoying, not destructive. Rev. Rul.
2008-5 makes the IRA case strictly worse: if the replacement is bought inside a traditional or Roth
IRA, the loss is disallowed **with no basis adjustment anywhere**. It is not deferred, it is
destroyed. `backend/app/tax/washsale.py`'s own module docstring states this at length and separates
`permanently_disallowed` from `deferred_disallowed` for exactly this reason. That machinery is
detective -- it reports the damage after a trade already happened. The cheaper fix is preventive:
never let a Roth card and a taxable card name the same ticker in the first place
(`strategy-program/THREE-PURPOSES-PLAN.md` §6). The ladder as shipped trades QLD, SCHD and IEF --
three tickers a taxable momentum or income strategy would also reach for first. This module asks
whether the ladder survives losing all three.

**What this module does not claim.** Ticker disjointness is a *necessary* condition, easy to check
mechanically, and is not a *sufficient* one. IRC §1091 turns on "substantially identical"
securities, a term the statute leaves undefined, and the IRS has never ruled on ETF pairs of the
kind swapped in here. Two 2x funds tracking the *same* index would satisfy ticker disjointness and
almost certainly still fail the actual statute -- that is a relabelling, not a substitution. This
module's own choices are argued, sleeve by sleeve, in `strategy-program/ROTH-DISJOINT-LADDER.md`,
and every one of them is a *different-index* change: a different underlying benchmark, not the same
benchmark wearing a different ticker. That argument is a judgement about economic substance, not a
fact this code can verify, and the document says so plainly rather than implying the backtest
below settles it.

**Why a standalone script, not `app.tournament.ladder.run_ladder_card`.** Two independent reasons,
both already established by sibling modules in this directory (`drawdown_ladder.py`,
`roth_voltarget.py`, `allocation_family.py`): first, `strategy-program/DEFECTS.md` D3 -- the bar
store is one on-disk DuckDB/Parquet target, and a concurrent write from `app.tournament`'s runner
racing this script's reads is a silent corruption risk, not a crash; reading bars directly through
`app.db.duck.read_bars` against a fresh in-memory connection avoids the runner entirely. Second, the
comparison this task asks for -- contribution-funded, money-weighted IRR *and* time-weighted CAGR,
against a strategy that differs from the shipped card only in which three tickers it trades -- is
exactly what `strategy-program/tools/contributions.py` already built, and re-deriving it against
`app.tournament`'s lump-sum-at-inception machinery would answer a different question than the one
asked.

**The ladder's state machine, ported a second time.** `backend/app/tournament/ladder.py`'s own
docstring already ports this mechanism once, from `strategy-program/tools/drawdown_ladder.py`'s
two-sleeve `run_ladder` to a three-sleeve, `PaperBroker`-executed card. This module ports it a
*third* time, to a three-sleeve `contributions.WeightFn` closure, because none of the three existing
homes fit: `drawdown_ladder.run_ladder` only knows one defensive sleeve, not a defensive/bond split;
`ladder.run_ladder_card` is `app.tournament`-shaped machinery this module is told to stay clear of
(see above); and `contributions.simulate` needs a plain `(session_index, closes) -> weights`
function, not a stateful object. `_weight_for` (the rung scan) and `_sleeve_targets` (bond funded
before defensive) below are therefore duplicated, not imported, from `drawdown_ladder.py` and
`ladder.py` respectively -- the identical choice both of those modules already made about each
other, for the identical reason each gives: two independently-evolving pieces of code that happen
to need the same small mechanism today should not be coupled to each other's internals for that
coincidence alone. If either upstream implementation changes its rung-scan or fund-order rule, that
is a decision about that module specifically, and this script silently inheriting it through an
import would be exactly the cross-module coupling those modules were written to avoid.

Run as a plain script, not ``-m`` -- ``strategy-program`` is not a legal Python package name (the
hyphen):

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/roth_disjoint.py

Every window below is in-sample: no price bar used here postdates the bar store's own latest common
session across the seven symbols this module touches, and every number is a description of what
already happened, not a forecast.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.db import duck

# `contributions.py` lives in this same hyphenated directory, which is not a legal Python package
# name, so it is loaded by file path -- the identical mechanism `roth_voltarget.py` already uses to
# reach the same module, for the same reason (see that module's own comment at the equivalent
# point).
_contrib_spec = importlib.util.spec_from_file_location(
    "contributions", str(Path(__file__).with_name("contributions.py"))
)
contrib = importlib.util.module_from_spec(_contrib_spec)
sys.modules["contributions"] = contrib
_contrib_spec.loader.exec_module(contrib)

#: Sessions per year, matching `contributions.py`, `drawdown_ladder.py`, `roth_voltarget.py` and
#: `score.py`.
TRADING_DAYS = 252

#: Charged on every dollar traded, one way. An ETF's stored close is already net of its own expense
#: ratio (a published NAV is, by construction), so subtracting that a second time would double-count
#: it -- `drawdown_ladder.py`'s own module docstring makes this point at length and every backtest
#: tool in this programme has kept the same convention since. The only real, un-modelled cost of
#: running this strategy is the cost of the rotation trades themselves, and that is what this number
#: represents: 5 basis points of the dollar amount moved, each time a rebalance actually trades.
SLIPPAGE_BPS = 5.0

#: `contributions.simulate`'s own drift band -- rebalance a sleeve only once it has drifted this far
#: from its target, exactly as `drawdown_ladder.py`'s own state machine only trades on a state
#: transition, never on ordinary day-to-day drift within a state.
BAND_PCT = 0.05


# ---------------------------------------------------------------------------
# The two ticker sets under comparison
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sleeves:
    """One ladder's three traded tickers plus its read-only signal. `label` is what every printed
    table calls this variant."""

    label: str
    signal: str
    leveraged: str
    defensive: str
    bond: str

    @property
    def traded(self) -> tuple[str, ...]:
        return (self.leveraged, self.defensive, self.bond)

    @property
    def universe(self) -> tuple[str, ...]:
        """Every symbol this variant's backtest needs a price for, signal included -- the signal is
        read every session (`_confirmed`'s bounce check, the drawdown calculation itself) but never
        bought or sold, matched by `_weight_fn`'s own `{signal: 0.0}` entry below."""
        return (self.signal, *self.traded)


#: The card as shipped -- `backend/app/paper/library/ladder/qld-schd-ief.json`.
ORIGINAL = Sleeves(label="original (QLD/SCHD/IEF)", signal="SPY", leveraged="QLD", defensive="SCHD", bond="IEF")

#: The disjoint substitute this module argues for. See `strategy-program/ROTH-DISJOINT-LADDER.md`
#: for the per-sleeve reasoning -- summarised here only as *which* symbol replaces which:
#:   QLD  (2x Nasdaq-100, ProShares)        -> SSO (2x S&P 500, ProShares)
#:   SCHD (Dow Jones U.S. Dividend 100)      -> VIG (S&P U.S. Dividend Growers, Vanguard)
#:   IEF  (ICE 7-10yr U.S. Treasury)         -> BND (Bloomberg U.S. Aggregate, Vanguard)
#: The signal stays SPY in both variants: it is never traded (see `Sleeves.universe`'s own note), so
#: it carries no wash-sale exposure regardless of which account reads it, and changing it would
#: change the strategy's trigger, not its tax exposure.
SUBSTITUTE = Sleeves(label="disjoint (SSO/VIG/BND)", signal="SPY", leveraged="SSO", defensive="VIG", bond="BND")


def check_disjoint(original: Sleeves, substitute: Sleeves) -> None:
    """The one property this whole exercise exists to buy: no ticker `substitute` trades is a ticker
    `original` trades. Raises rather than warns -- a disjointness check that only prints a warning is
    exactly the "detective, not preventive" failure mode this module's own docstring opens with."""
    overlap = set(original.traded) & set(substitute.traded)
    if overlap:
        raise SystemExit(
            f"substitution failed: {sorted(overlap)} traded by both {original.label} and "
            f"{substitute.label} -- a Roth card sharing a ticker with a taxable one is exactly the "
            "Rev. Rul. 2008-5 exposure this module exists to eliminate."
        )
    print(f"disjointness check: PASS -- {substitute.traded} shares no ticker with {original.traded}")


# ---------------------------------------------------------------------------
# Bars, read once via app.db.duck directly (matching `allocation_family.py`'s own established
# pattern for this task brief's required read path)
# ---------------------------------------------------------------------------


def load_closes(
    symbols: Sequence[str], start: dt.date, end: dt.date
) -> tuple[list[dt.date], dict[str, list[float]]]:
    """Aligned closes for every symbol over their common sessions, intersected rather than
    forward-filled -- a synthetic bar on a day a fund did not trade would let the backtest rebalance
    at a price nobody could actually have got, the same reasoning every other loader in this
    programme (`drawdown_ladder.load_closes`, `roth_voltarget.load_closes`,
    `allocation_family.load_frames`) already states for itself.
    """
    settings = get_settings()
    raw: dict[str, dict[dt.date, float]] = {}
    with duck.connect() as conn:
        for symbol in symbols:
            frame = duck.read_bars(conn, settings.bars_dir, symbol, duck.Interval.DAY)
            if frame.empty:
                raise SystemExit(f"no bars stored for {symbol}")
            raw[symbol] = dict(zip(frame["ts"].dt.date, frame["close"].astype(float), strict=True))

    common = sorted(set.intersection(*(set(v) for v in raw.values())))
    dates = [d for d in common if start <= d <= end]
    if len(dates) < TRADING_DAYS:
        raise SystemExit(
            f"only {len(dates)} common sessions for {sorted(symbols)} in {start}..{end} -- check "
            "the narrowest symbol's first bar before widening the window"
        )
    return dates, {s: [raw[s][d] for d in dates] for s in symbols}


def coverage(symbols: Sequence[str]) -> dict[str, tuple[dt.date, dt.date]]:
    """Each symbol's own first and last stored session, unfiltered by any window -- used only to
    print the coverage table this task's report is required to include, not to drive the backtest
    itself (`load_closes` re-derives the intersection it actually needs)."""
    settings = get_settings()
    out: dict[str, tuple[dt.date, dt.date]] = {}
    with duck.connect() as conn:
        for symbol in symbols:
            frame = duck.read_bars(conn, settings.bars_dir, symbol, duck.Interval.DAY)
            if frame.empty:
                continue
            out[symbol] = (frame["ts"].min().date(), frame["ts"].max().date())
    return out


# ---------------------------------------------------------------------------
# The ladder state machine, as a `contributions.WeightFn` over three sleeves plus a read-only signal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rung:
    """One step of the ladder -- identical shape and identical validity contract to
    `drawdown_ladder.Rung` and `app.tournament.ladder.Rung`, redeclared here (not imported) for the
    same "independently frozen, small enough to duplicate" reasoning this module's own docstring
    gives for `_weight_for`/`_sleeve_targets`."""

    drawdown: float
    leveraged_weight: float


#: The rungs, confirmation window and recovery rule the shipped card uses
#: (`backend/app/paper/library/ladder/qld-schd-ief.json`) -- held identical between `ORIGINAL` and
#: `SUBSTITUTE` on purpose. The whole point of this backtest is to isolate the cost of changing
#: *tickers*; changing the rule at the same time would confound that with the cost of changing the
#: *strategy*, which is a different question this module is not asking.
RUNGS: tuple[Rung, ...] = (Rung(-0.10, 0.20), Rung(-0.20, 0.60), Rung(-0.30, 0.80))
CONFIRM_MA = 50
ATH_HAIRCUT = 0.5
RECOVERY_GAIN = 0.10
RECOVERY_SESSIONS = 60
BASE_BOND_WEIGHT = 0.40
BASE_DEFENSIVE_WEIGHT = 0.60


def _weight_for(rungs: tuple[Rung, ...], drawdown: float) -> float:
    """The deepest rung `drawdown` has reached, or 0 above the first trigger -- a scan, not a sort,
    exactly `drawdown_ladder.Ladder.weight_for` and `app.tournament.ladder._weight_for`."""
    weight = 0.0
    for rung in rungs:
        if drawdown <= rung.drawdown:
            weight = rung.leveraged_weight
    return weight


def _confirmed(signal: Sequence[float], i: int, confirm_ma: int) -> bool:
    """Has the signal closed back above its own `confirm_ma`-session average, as of session `i`?
    Ported verbatim from `drawdown_ladder.run_ladder`'s own inner `confirmed` closure -- see that
    module's docstring (and `app.tournament.ladder`'s, at greater length) for why this single gate is
    the difference between a ladder that survives a crash and one that reaches maximum leverage at
    its bottom."""
    if i < confirm_ma:
        return False
    window = signal[i - confirm_ma + 1 : i + 1]
    return signal[i] > sum(window) / len(window)


def _sleeve_targets(
    leveraged_weight: float, bond_symbol: str, defensive_symbol: str, leveraged_symbol: str
) -> dict[str, float]:
    """Turn one scalar -- how much leveraged exposure the ladder wants right now -- into three sleeve
    weights summing to exactly 1. The bond sleeve absorbs the first `BASE_BOND_WEIGHT` fraction of
    whatever the leveraged sleeve needs; only once it is drawn to zero does the defensive sleeve give
    up any of its own weight. A `min`/`max` clamp, not a proportional split, matching
    `app.tournament.ladder._sleeve_targets`'s own reasoning verbatim: the card's specification states
    an order ("first ... then ..."), not a blend."""
    bond = max(0.0, BASE_BOND_WEIGHT - leveraged_weight)
    defensive = 1.0 - leveraged_weight - bond
    return {leveraged_symbol: leveraged_weight, bond_symbol: bond, defensive_symbol: defensive}


def make_ladder_weight_fn(sleeves: Sleeves) -> contrib.WeightFn:
    """Build a `contributions.WeightFn` for `sleeves`, closing over its own mutable ladder state --
    the same closure-with-a-state-dict shape `roth_voltarget.make_circuit_breaker` already uses for
    its own arm/re-arm hysteresis, for the identical reason: `contributions.simulate` calls a plain
    `(session_index, closes) -> weights` function, so anything the strategy needs to remember between
    sessions has to live in a closure rather than in `simulate`'s own state.

    State mirrors `drawdown_ladder.run_ladder`'s own local variables one-for-one (`peak`, `cycle_peak`,
    `armed_depth`, `new_high_at`), because this *is* that state machine -- ported to a `WeightFn`
    instead of a standalone loop, and to three sleeves instead of `run_ladder`'s two, via
    `_sleeve_targets`. Every rule (arming, gap-through, the confirmation gate, the recovery clock) is
    `run_ladder`'s own rule, not a reinterpretation -- see this module's docstring for why it is
    ported a third time rather than imported from either of the two existing homes.
    """
    state: dict[str, float | int | None] = {
        "leveraged_weight": 0.0,
        "peak": None,
        "cycle_peak": 0.0,
        "armed_depth": 0.0,
        "new_high_at": None,
    }

    def weight_fn(i: int, closes: Mapping[str, Sequence[float]]) -> dict[str, float]:
        signal = closes[sleeves.signal]
        price = signal[i]

        if state["peak"] is None:
            state["peak"] = price
            state["cycle_peak"] = price

        # A new high while leveraged starts the recovery clock, checked against the weight as it
        # stood at the end of the *previous* session -- `run_ladder`'s own ordering, preserved here.
        if price > state["peak"]:
            if state["leveraged_weight"] > 0 and state["new_high_at"] is None:
                state["new_high_at"] = i
            state["peak"] = price

        drawdown = price / state["peak"] - 1.0
        confirmed = _confirmed(signal, i, CONFIRM_MA)
        target = state["leveraged_weight"]

        if state["leveraged_weight"] == 0.0:
            # Base state: arm on the deepest rung this drawdown has reached, in one trade -- the
            # gap-through fix.
            reached = _weight_for(RUNGS, drawdown)
            if reached > 0 and confirmed:
                target = reached
                state["armed_depth"] = reached
                state["cycle_peak"] = state["peak"]
                state["new_high_at"] = None
        else:
            deeper = _weight_for(RUNGS, drawdown)
            if deeper > state["armed_depth"] and confirmed:
                # Ladder down. Fires once per level per cycle -- `armed_depth` only ever rises until
                # a full reset.
                target = deeper
                state["armed_depth"] = deeper
            elif state["new_high_at"] is not None:
                sessions_since = i - state["new_high_at"]
                recovered = price >= state["cycle_peak"] * (1.0 + RECOVERY_GAIN)
                if recovered or sessions_since >= RECOVERY_SESSIONS:
                    target = 0.0
                    state["armed_depth"] = 0.0
                    state["new_high_at"] = None
                elif sessions_since == 0:
                    target = state["leveraged_weight"] * ATH_HAIRCUT

        state["leveraged_weight"] = target
        targets = _sleeve_targets(target, sleeves.bond, sleeves.defensive, sleeves.leveraged)
        targets[sleeves.signal] = 0.0  # read every session, never held -- see `Sleeves.universe`
        return targets

    return weight_fn


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Slice:
    """One reporting sub-period inside the main run -- not a separate backtest. Statistics for a
    `Slice` are read off the *main* run's own equity/contribution history, restricted to
    `[start, end]`, with the running high-water mark carried in from before the slice began. A cold
    restart at the slice boundary would understate the drawdown: the ladder's armed state going into
    2020 or 2022 is itself a consequence of what happened before either year, and resetting it would
    answer "how would a strategy that had just been switched on behave here", not "how did this
    strategy behave here"."""

    label: str
    start: dt.date
    end: dt.date


#: 2008 is out of reach for a same-tickers-both-sides comparison: SCHD's own first stored session is
#: 2011-10-20 (verified below against the live store), which binds the *original* ladder in this
#: comparison regardless of how far back the substitute's own tickers go. Per this task's own
#: instruction ("2008 if the symbols reach it, otherwise 2020 and 2022"), both of those sit inside
#: the main window and are reported as slices of it rather than as separate runs.
SLICES = (
    Slice("2020 (COVID crash and recovery)", dt.date(2020, 1, 1), dt.date(2020, 12, 31)),
    Slice("2022 (rate-driven bear market)", dt.date(2022, 1, 1), dt.date(2022, 12, 31)),
)


def slice_stats(result: contrib.ContributionResult, start: dt.date, end: dt.date) -> dict[str, float]:
    """Peak-to-trough within `[start, end]`, measured against the account's own contribution-adjusted
    high-water mark carried in from the full run -- see `Slice`'s own docstring for why this is not a
    fresh `max_drawdown` computed on a truncated series. Mirrors
    `contrib.ContributionResult.max_drawdown`'s own algorithm exactly, restricted to only *recording*
    a new worst value while inside the window."""
    peak_excess = 0.0
    worst = 0.0
    start_equity: float | None = None
    end_equity: float | None = None
    for day, equity, contributed in zip(result.dates, result.equity, result.contributed, strict=True):
        if contributed > 0:
            peak_excess = max(peak_excess, equity / contributed)
        if start <= day <= end:
            if start_equity is None:
                start_equity = equity
            end_equity = equity
            if contributed > 0 and peak_excess > 0:
                worst = min(worst, (equity / contributed) / peak_excess - 1.0)
    if start_equity is None or end_equity is None:
        raise SystemExit(f"no sessions in {start}..{end} -- window does not overlap the run")
    return {
        "start_equity": start_equity,
        "end_equity": end_equity,
        "period_return": end_equity / start_equity - 1.0,
        "max_drawdown": worst,
    }


# ---------------------------------------------------------------------------
# The card, validated
# ---------------------------------------------------------------------------


def validate_card() -> None:
    """Load `backend/app/paper/library/ladder/sso-vig-bnd.json` through
    `app.tournament.ladder.LadderCard.model_validate_json` and report whether it validates. Imported
    lazily, inside this function, rather than at module top: every other symbol this module needs
    comes from a plain bar read or a hand-rolled backtest specifically to stay clear of
    `app.tournament`'s runner (see this module's own docstring); `LadderCard` itself is a frozen
    pydantic model with no runner attached, so importing only the model -- never `run_ladder_card`,
    never anything that touches the live bar store through the tournament package -- does not cross
    that line."""
    from app.tournament.ladder import LadderCard

    path = (
        Path(__file__).resolve().parents[2]
        / "backend"
        / "app"
        / "paper"
        / "library"
        / "ladder"
        / "sso-vig-bnd.json"
    )
    raw = path.read_text(encoding="utf-8")
    try:
        card = LadderCard.model_validate_json(raw)
    except Exception as exc:  # reported to the operator, not swallowed
        print(f"card validation: FAIL -- {path}\n  {exc}")
        return
    print(
        f"card validation: PASS -- {path.name} ({card.agent_id}), universe={card.universe}, "
        f"rungs={len(card.rungs)}"
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def summarise(name: str, r: contrib.ContributionResult) -> str:
    return contrib.summarise(name, r)


def main() -> int:
    check_disjoint(ORIGINAL, SUBSTITUTE)

    print("\nbar coverage (unfiltered, from the live store):")
    all_symbols = sorted(set(ORIGINAL.universe) | set(SUBSTITUTE.universe))
    coverage_map = coverage(all_symbols)
    for symbol in all_symbols:
        if symbol in coverage_map:
            first, last = coverage_map[symbol]
            print(f"  {symbol:6} {first} .. {last}")
        else:
            print(f"  {symbol:6} wanted but not found in the store")

    # Deliberately wide, unfiltered bounds: `load_closes` intersects every symbol's own sessions and
    # then clips to this range, so the *actual* window reported below is whatever that intersection
    # produces -- bound in practice by SCHD's own first stored session (the latest-starting symbol on
    # either side) and by SSO's own last stored session (the earliest-ending one). A future bar sync
    # that extends either edge tightens the printed window on its own; nothing here needs to change.
    dates, closes = load_closes(all_symbols, dt.date(2000, 1, 1), dt.date(2030, 1, 1))
    print(
        f"\nmain window: {dates[0]} .. {dates[-1]}  ({len(dates)} sessions, "
        f"{len(dates) / TRADING_DAYS:.2f}y)"
    )
    print(f"slippage: {SLIPPAGE_BPS:.0f}bp one-way; contribution: ${contrib.ANNUAL_CONTRIBUTION:,.0f}/yr\n")

    print(contrib.HEADER)
    results: dict[str, contrib.ContributionResult] = {}
    for sleeves in (ORIGINAL, SUBSTITUTE):
        weight_fn = make_ladder_weight_fn(sleeves)
        result = contrib.simulate(
            dates,
            closes,
            weight_fn,
            band_pct=BAND_PCT,
            slippage_bps=SLIPPAGE_BPS,
        )
        results[sleeves.label] = result
        print(summarise(sleeves.label, result))

    original_r = results[ORIGINAL.label]
    substitute_r = results[SUBSTITUTE.label]

    print("\nboth return measures (contribution funding inverts sequence risk -- see `contributions.py`):")
    for label, r in results.items():
        irr = "n/a" if r.irr is None else f"{r.irr * 100:.2f}%"
        print(f"  {label:24} money-weighted IRR {irr:>8}   time-weighted CAGR {r.time_weighted_cagr * 100:6.2f}%")

    print("\nseverity slices (peak-to-trough within the window, against the running high-water mark):")
    for sl in SLICES:
        print(f"  {sl.label}")
        for label, r in results.items():
            s = slice_stats(r, sl.start, sl.end)
            print(
                f"    {label:24} period return {s['period_return'] * 100:7.2f}%   "
                f"max drawdown {s['max_drawdown'] * 100:7.2f}%"
            )

    print("\nthe cost of the substitution:")
    dollar_cost = substitute_r.final_balance - original_r.final_balance
    irr_cost = (
        None
        if original_r.irr is None or substitute_r.irr is None
        else (substitute_r.irr - original_r.irr) * 100
    )
    cagr_cost = (substitute_r.time_weighted_cagr - original_r.time_weighted_cagr) * 100
    dd_cost = (substitute_r.max_drawdown - original_r.max_drawdown) * 100
    mar_cost = substitute_r.mar - original_r.mar
    irr_str = "n/a" if irr_cost is None else f"{irr_cost:+.2f}pp"
    print(f"  final balance:        {dollar_cost:+,.0f} ({substitute_r.final_balance:,.0f} vs {original_r.final_balance:,.0f})")
    print(f"  money-weighted IRR:   {irr_str}")
    print(f"  time-weighted CAGR:   {cagr_cost:+.2f}pp")
    print(f"  max drawdown:         {dd_cost:+.2f}pp (negative = the disjoint version falls further)")
    print(f"  MAR:                  {mar_cost:+.2f}")

    print()
    validate_card()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
