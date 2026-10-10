"""The harness/engine gap for the savings card `spy-schd-agg-gld-bil-atr-tilt`.

    PYTHONPATH="backend;strategy-program/tools;." .venv/Scripts/python.exe \
        strategy-program/tools/savings_gap.py

`ALLOCATION-FAMILY.md`'s headline preservation numbers -- CAGR 7.89%, max drawdown -19.9%, MAR 0.40 --
came from `allocation_family.simulate`, a lump-sum harness that is *not* the execution path the paper
desk uses. The desk runs `app.tournament.allocation.run_allocation`. Until this tool existed the two
had never been compared on this card, because round 15 excluded it from the savings arm entirely
(`data/rounds/r15-2026-08/SELECTION.md` section 4: both its rules gate on `atr(14)`, ATR needs high and
low, and `contributions.simulate` passes closes only). So the number the deployment plan rests on was a
harness number the desk had never reproduced.

**Four arms, so the gap decomposes instead of conflating two unrelated things.**

    A  harness + harness ATR (simple mean)      the published figure
    B  harness + engine  ATR (Wilder)           A -> B is the SIGNAL DEFINITION difference
    C  engine, fractional shares                B -> C is the INSTRUMENT difference
    D  engine, `desk._mandate(SAVINGS)`         what the live book would actually have done

`allocation_family.atr_pct` is a simple equal-weight rolling mean of true range; the engine's
`atr(14)` is Wilder-smoothed, and the 1.8% threshold was calibrated against the former. A straight
harness-vs-engine diff would therefore mix a different *signal* with a different *instrument*. Arm B
keeps the harness's own timing, funding and axis and changes only which sessions the tilt fires on.

**Arm B calls the engine's own `atr()`**, not a reimplementation of Wilder smoothing, so the signal is
identical to the engine's by construction. It is computed on SPY's *full* stored history -- the
smoothing is recursive, so the seed matters -- and then sampled onto the harness's session axis.

**Arm D calls `desk._mandate(Purpose.SAVINGS)` itself** rather than reconstructing it, so it cannot
drift from the live book's mandate. Arm C's three overrides beyond fractional shares
(`slippage_bps=5`, `commission_per_trade=0`, `max_single_name_weight=1`) all turned out to be what
that mandate already produces, so C and D differ in exactly one setting.

**The result, 2026-08-30.** The published figure survives the real execution path: A -> D is -0.06pp
of CAGR and +0.2pp of drawdown, with MAR 0.40 in all four arms.

**And the decomposition is below its own resolution, which is the part worth not overreading.** The
A->B and B->C terms came out 0.1pp and 0.2pp of drawdown -- but arm D differs from arm C only in
whole-vs-fractional shares, a change that should be nearly inert, and it moves CAGR 0.09pp and
drawdown 0.1pp. Configuration noise is therefore the same size as the terms being attributed, so the
*total* gap is real and the split between "signal" and "instrument" cannot be ranked in either
direction. Everything here also sits far under the programme's own 21.2pp noise floor.

**Not investment advice.** Price-only bars, one window, in-sample. AGG, SCHD and BIL all pay
distributions this harness does not model, so every return below is understated; the drawdown column
is the trustworthy half.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import pathlib
import sys
from collections import Counter
from collections.abc import Callable
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import allocation_family as fam
import pandas as pd

from app.config import get_settings
from app.db import duck
from app.indicators.volatility import atr as engine_atr
from app.paper.mandate import default_mandate
from app.paperdesk.desk import _mandate as desk_mandate
from app.tournament.allocation import AllocationCard, run_allocation
from app.tournament.purposes import Purpose

REPO = pathlib.Path(__file__).resolve().parents[2]
CARD_PATH = REPO / "backend" / "app" / "paper" / "library" / "allocation" / (
    "spy-schd-agg-gld-bil-atr-tilt.json"
)

#: Everything about the window comes from `allocation_family`'s own published definition rather than
#: being restated here, so this tool cannot silently measure a different window than the report does.
WINDOW = fam.WINDOW_PRIMARY
BASE = fam.BASE_PRIMARY
MOVES = (("SPY", "BIL"), ("SCHD", "GLD"))
PERIOD = 14

#: The savings book's own capital. Arm A is additionally run at the report's own $10,000 as a scale
#: check: holdings are fully fractional in the harness, so every ratio must be identical. If that
#: check ever fails, this comparison is measuring capital rather than the instrument.
CAPITAL = 100_000.0

#: `ALLOCATION-FAMILY.md`'s committed PRIMARY figures for variant 2, as a drift check on the
#: instrument -- the same role round 16's constants play in `round19.py`. **CAGR is deliberately not
#: asserted:** the report ran when the store's last bar was 2026-08-11 and `fam.END` is 2026-08-21, so
#: CAGR moves as bars are added (SPY buy-and-hold moved 13.32% -> 13.24% over the same interval).
#: Max drawdown and MAR were stable across that extension, so those are the ones worth watching.
PUBLISHED_MAX_DD = -0.199
PUBLISHED_MAR = 0.40
DRIFT_TOLERANCE = 0.005

#: Float-rounding headroom for the scale check. The measured residue is ~1e-15; a genuine divergence
#: (share quantisation, a cash floor biting at one size and not the other) would be 1e-4 or larger, so
#: this sits nine orders of magnitude clear of the noise and four clear of anything worth reporting.
SCALE_TOLERANCE = 1e-9


def check_card_matches_harness(card: AllocationCard) -> None:
    """Fail loudly if the card and the harness no longer encode the same strategy.

    Without this the "gap" measured below could be a card-versus-harness *definition* drift wearing
    the costume of an instrument difference -- which is precisely the confusion the four arms exist to
    prevent, so leaving it to inspection would undo the point of the design.
    """
    sleeves = {s.symbol: float(s.target_weight) for s in card.sleeves}
    if sleeves != BASE:
        raise SystemExit(f"card sleeves {sleeves} != harness base {BASE}")
    if len(card.rules) != len(MOVES):
        raise SystemExit(f"card has {len(card.rules)} rules, harness makes {len(MOVES)} moves")
    expected_condition = f"atr({PERIOD}) > close * {fam.ATR_ENTER_PCT}"
    for rule, (from_symbol, to_symbol) in zip(card.rules, MOVES, strict=True):
        actual = (rule.condition, rule.from_symbol, rule.to_symbol, float(rule.shift_pct))
        expected = (expected_condition, from_symbol, to_symbol, fam.ATR_SHIFT_PCT)
        if actual != expected:
            raise SystemExit(f"card rule {actual} != harness move {expected}")
        if rule.on_symbol != "SPY":
            raise SystemExit(f"card rule reads {rule.on_symbol}, harness reads SPY")


def wilder_atr_pct_by_date() -> dict[dt.date, float]:
    """`atr(14) / close` per session from the engine's own indicator, on SPY's full stored history."""
    settings = get_settings()
    with duck.connect() as conn:
        frame = duck.read_bars(conn, settings.bars_dir, "SPY", duck.Interval.DAY)
    bars = pd.DataFrame(
        {
            "high": frame["high"].astype(float),
            "low": frame["low"].astype(float),
            "close": frame["close"].astype(float),
        }
    )
    out = engine_atr(bars, period=PERIOD)
    column = out.columns[0]
    return {
        date: float(value) / float(close)
        for date, value, close in zip(
            frame["ts"].dt.date, out[column], bars["close"], strict=True
        )
        if pd.notna(value) and float(close) > 0
    }


def make_tilt(
    is_hot: Callable[[int, fam.Frames], bool],
) -> tuple[fam.WeightFn, list[int]]:
    """Variant 2's weight function with the hot/not decision delegated to `is_hot`.

    Identical to `allocation_family.make_atr_tilt` in every other respect -- same base, same two
    moves, same clamp -- so swapping the ATR definition is the only thing that changes between arms A
    and B. The returned list accumulates the session indices on which the tilt fired, which is what
    makes "how much do the two definitions actually disagree" answerable rather than assumed.
    """
    fired: list[int] = []

    def weight_fn(i: int, frames: fam.Frames) -> dict[str, float]:
        weights = dict(BASE)
        if is_hot(i, frames):
            fired.append(i)
            for from_symbol, to_symbol in MOVES:
                shift = min(fam.ATR_SHIFT_PCT, weights[from_symbol])
                weights[from_symbol] -= shift
                weights[to_symbol] += shift
        return weights

    return weight_fn, fired


def harness_row(name: str, result: fam.Result, fires: int | None) -> str:
    shown = "    -" if fires is None else f"{fires:>5d}"
    return (
        f"{name:38} {result.cagr * 100:>7.2f}%  {result.max_drawdown * 100:>7.1f}%  "
        f"{result.volatility * 100:>6.1f}%  {result.mar:>5.2f}  {result.rebalances:>5d}  {shown}"
    )


def engine_row(name: str, result: object, capital: float) -> tuple[str, float, float]:
    drawdown = float(result.max_drawdown)  # type: ignore[attr-defined]
    sessions = result.sessions  # type: ignore[attr-defined]
    ending = float(result.ending_equity)  # type: ignore[attr-defined]
    cagr = (ending / capital) ** (fam.TRADING_DAYS / sessions) - 1
    mar = cagr / abs(drawdown) if drawdown else 0.0
    volatility = (result.volatility or 0.0) * 100  # type: ignore[attr-defined]
    rejections = len(result.rejections)  # type: ignore[attr-defined]
    return (
        f"{name:38} {cagr * 100:>7.2f}%  {drawdown * 100:>7.1f}%  {volatility:>6.1f}%  "
        f"{mar:>5.2f}  {'-':>5}  {'-':>5}   sessions {sessions}, rejections {rejections}",
        cagr,
        drawdown,
    )


def main() -> int:
    settings = get_settings()
    card = AllocationCard.model_validate_json(CARD_PATH.read_text(encoding="utf-8"))
    check_card_matches_harness(card)

    dates, frames = fam.load_frames(WINDOW.symbols, WINDOW.start, WINDOW.end)
    print(f"card    : {card.agent_id}  ({len(card.sleeves)} sleeves, band {card.band_pct})")
    print(f"window  : {dates[0]} .. {dates[-1]}  ({len(dates)} harness sessions)")
    print(f"capital : ${CAPITAL:,.0f}   card and harness verified to encode the same strategy\n")

    def hot_simple(i: int, frames_: fam.Frames) -> bool:
        value = fam.atr_pct(frames_["SPY"], i, PERIOD)
        return value is not None and value > fam.ATR_ENTER_PCT

    wilder = wilder_atr_pct_by_date()

    def hot_wilder(i: int, _frames: fam.Frames) -> bool:
        return wilder.get(dates[i], 0.0) > fam.ATR_ENTER_PCT

    fn_a, fired_a = make_tilt(hot_simple)
    res_a = fam.simulate(dates, frames, fn_a, starting_equity=CAPITAL)
    fn_scale, _ = make_tilt(hot_simple)
    res_scale = fam.simulate(dates, frames, fn_scale, starting_equity=10_000.0)
    fn_b, fired_b = make_tilt(hot_wilder)
    res_b = fam.simulate(dates, frames, fn_b, starting_equity=CAPITAL)

    mandate_c = dataclasses.replace(
        default_mandate(starting_cash=Decimal(str(CAPITAL))),
        max_single_name_weight=Decimal(1),
        allow_fractional_shares=True,
        slippage_bps=Decimal(5),
        commission_per_trade=Decimal(0),
    )
    res_c = run_allocation(card, settings=settings, mandate=mandate_c, start=WINDOW.start,
                           end=WINDOW.end)
    mandate_d = desk_mandate(Purpose.SAVINGS)
    res_d = run_allocation(card, settings=settings, mandate=mandate_d, start=WINDOW.start,
                           end=WINDOW.end)

    header = f"{'':38} {'CAGR':>8}  {'maxDD':>7}  {'vol':>6}  {'MAR':>5}  {'rebal':>5}  {'fires':>5}"
    print(header)
    print(harness_row("A  harness, simple-mean ATR (pub.)", res_a, len(fired_a)))
    print(harness_row("   .. same at $10,000 (scale check)", res_scale, None))
    print(harness_row("B  harness, engine Wilder ATR", res_b, len(fired_b)))
    line_c, cagr_c, dd_c = engine_row("C  engine, fractional shares", res_c, CAPITAL)
    print(line_c)
    capital_d = float(mandate_d.starting_cash)
    line_d, cagr_d, dd_d = engine_row("D  engine, live desk mandate", res_d, capital_d)
    print(line_d)

    # Compared against a tolerance, not with `==`. The harness is linear in capital -- holdings,
    # moves and slippage all scale together -- so in exact arithmetic these ratios are *equal*, and
    # the residue is float rounding at the last bits: measured at 1.1e-16 (maxDD) and 1.4e-15 (MAR).
    # An `==` here reports FAIL on a run that is bit-for-bit correct, which is worse than no check.
    dd_delta = abs(res_scale.max_drawdown - res_a.max_drawdown)
    mar_delta = abs(res_scale.mar - res_a.mar)
    if dd_delta > SCALE_TOLERANCE or mar_delta > SCALE_TOLERANCE:
        print(f"\n  FAIL: the $10,000 scale check diverged (maxDD {dd_delta:.2e}, MAR "
              f"{mar_delta:.2e}) -- this is measuring capital, not the instrument")

    overlap = len(set(fired_a) & set(fired_b)) / max(1, len(set(fired_a) | set(fired_b))) * 100
    print(f"\nending equity   A ${res_a.equity[-1]:>12,.2f}   B ${res_b.equity[-1]:>12,.2f}   "
          f"C ${float(res_c.ending_equity):>12,.2f}   D ${float(res_d.ending_equity):>12,.2f}")
    print(f"tilt fires      A {len(fired_a):>5d} of {len(dates)} sessions   B {len(fired_b):>5d}"
          f"   (agreement {overlap:.1f}%)")

    print("\n-- the gap, decomposed (see this module's docstring on its resolution) --")
    print(f"  A -> B  signal definition  maxDD {res_a.max_drawdown * 100:>6.1f}% -> "
          f"{res_b.max_drawdown * 100:>6.1f}%  ({(res_b.max_drawdown - res_a.max_drawdown) * 100:+.1f}pp)"
          f"   CAGR {(res_b.cagr - res_a.cagr) * 100:+.2f}pp")
    print(f"  B -> C  instrument         maxDD {res_b.max_drawdown * 100:>6.1f}% -> "
          f"{dd_c * 100:>6.1f}%  ({(dd_c - res_b.max_drawdown) * 100:+.1f}pp)"
          f"   CAGR {(cagr_c - res_b.cagr) * 100:+.2f}pp")
    print(f"  C -> D  whole shares       maxDD {dd_c * 100:>6.1f}% -> "
          f"{dd_d * 100:>6.1f}%  ({(dd_d - dd_c) * 100:+.1f}pp)"
          f"   CAGR {(cagr_d - cagr_c) * 100:+.2f}pp")
    print(f"  A -> D  published to desk  maxDD {res_a.max_drawdown * 100:>6.1f}% -> "
          f"{dd_d * 100:>6.1f}%  ({(dd_d - res_a.max_drawdown) * 100:+.1f}pp)"
          f"   CAGR {(cagr_d - res_a.cagr) * 100:+.2f}pp")

    drift = abs(res_a.max_drawdown - PUBLISHED_MAX_DD)
    status = "ok" if drift <= DRIFT_TOLERANCE else "DRIFTED"
    print(f"\ndrift check     arm A maxDD {res_a.max_drawdown * 100:.1f}% vs committed "
          f"{PUBLISHED_MAX_DD * 100:.1f}%, MAR {res_a.mar:.2f} vs {PUBLISHED_MAR:.2f}  [{status}]")

    for label, result in (("C", res_c), ("D", res_d)):
        if not result.rejections:
            continue
        kinds = Counter(d.reason.split("(")[0].strip()[:64] for d in result.rejection_details)
        settled = sum(n for reason, n in kinds.items() if "settled cash" in reason)
        print(f"arm {label} rejections  {len(result.rejections)} total, {settled} settled-cash "
              f"(D8's unfundable-buy signature would show as a buy with no sell to fund it)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
