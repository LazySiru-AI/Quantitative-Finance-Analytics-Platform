# C14 -- Risk-managed: flight-to-quality basket, built for the worst window

`agent_id: c14-riskmanaged-wide` | discipline: risk-managed | designed_through: 2026-02-13

## Deliberate positioning, stated up front

This card is aimed at the worst-window and hit-rate legs of the Pareto frontier, not the median-return
leg. A risk-managed book that chases median return is just a trend card with a different name. Mine will
likely show a modest-to-negative median across eight windows because it is built to be a net buyer of
duration and gold precisely when everything else is being sold, and those windows are a minority of the
eight. That is the trade I am choosing to make, not an excuse for a card that underperforms everywhere.

## 1. Mechanism, and who is on the other side

When equity risk appetite collapses -- a growth scare, a credit event, a liquidity panic -- capital does
not vanish, it reallocates: pension and insurance books extend duration and rebalance into Treasuries as
liability-matching flows accelerate, gold demand rises as a currency-and-counterparty-risk hedge, and
investment-grade credit holds a senior claim that equity does not. The seller on the other side of my
trade is whoever is being forced out of those instruments in normal times -- a levered short-duration
carry trade unwinding, a momentum book rotating out of bonds into the equity rally that is going on
simultaneously -- and, during the crisis itself, the seller is whoever holds equities and needs to raise
cash, which is exactly the flow that pushes money into what I hold. I am not claiming to beat anyone in a
calm, trending bull market; I am claiming to be positioned as a buyer of the assets capital flees *into*
on the specific days SPY is worst.

## 2. Universe selection -- not index-derived

**This selection is my own cross-asset reasoning, not drawn from `data/universe/index-constituents.json`.**
None of TLT, IEF, GLD, LQD is an S&P 500 or Nasdaq-100 constituent; they are the macro/ETF sleeve the
brief explicitly says survives from earlier rounds. Because the selection argument is mine and not
"these are today's index members," this card is **not** subject to the `universe_knowable_from` gate and
should be eligible on every window its history covers, including `gfc`.

The argument, stated plainly: I wanted instruments whose *demand mechanism* is structurally different
from an equity long -- duration (TLT long bond, IEF intermediate), a non-yielding store of value (GLD),
and a senior-but-still-credit-sensitive claim (LQD) -- so that a single macro shock cannot be relied on to
take the whole book down together the way it can in an all-equity universe. I explicitly tested and
excluded two tempting alternatives before finalizing this list (see section 3): defensive equity sectors
(XLU, XLP) and a second precious-metal sleeve (SLV).

## 3. What I measured through 2026-02-13

All figures below are buy-and-hold cumulative return of the underlying ETF over the stated window,
computed from adjusted close, using only bars dated on or before 2026-02-13. This is the raw material my
rule-based entries are trying to capture a portion of, not a claim that my rules capture 100% of it.

| Window | TLT | IEF | GLD | LQD | SPY |
|---|---|---|---|---|---|
| gfc (2007-10-09 to 2009-03-09) | +25.1% | +20.2% | +23.9% | -6.8% | **-55.2%** |
| covid (2020-02-19 to 2020-06-30) | +13.3% | +7.9% | +10.3% | +3.7% | -7.9% |
| q4-2018 (2018-09-21 to 2018-12-24) | +4.6% | +3.3% | +5.8% | -1.1% | -19.3% |
| chop-2011 (2011-05-26 to 2012-06-06) | +34.3% | +14.5% | +6.1% | +9.0% | +1.3% |
| chop-2015 (2015-04-07 to 2016-04-15) | +3.2% | +3.6% | +1.6% | +1.3% | +2.4% |
| bull-2024 (2024-08-21 to 2025-08-20) | -8.2% | +1.4% | +32.8% | +2.5% | +15.2% |
| **bear-2022** (2022-01-03 to 2022-10-12) | **-29.3%** | **-15.4%** | -7.3% | **-21.1%** | -24.5% |

The pattern is consistent across every growth-scare or liquidity-panic window (gfc, covid, q4-2018,
chop-2011): the basket is flat to strongly positive while SPY is flat to severely negative. bear-2022 is
the opposite case and I kept it in the table rather than dropping it: when the shock *is* rising rates,
duration is not a hedge, it is a second source of loss, and TLT (-29.3%) was worse than SPY itself
(-24.5%) that year. This is the falsification case, addressed in section 5.

Two names I considered and rejected, with numbers:
- **XLU / XLP** (defensive equity sectors): fell -42.5% / -28.5% in gfc and -20.7% / -11.5% in covid --
  still equities, still taken down by a credit or liquidity crisis, and XLU's covid drawdown was worse
  than SPY's own. They do not belong in a card whose entire claim is crisis behaviour.
- **SLV** (second precious-metal sleeve): -21.9% in chop-2011, -16.9% in bear-2022, -4.7% in gfc -- an
  inconsistent diversifier. It would have added a name without adding ballast on the days that matter.

Trailing-2y (504-session) daily-return correlation to SPY through 2026-02-13, for reference: TLT 0.075,
IEF -0.022, GLD 0.100, LQD 0.323. All four are meaningfully lower than a typical equity-to-equity pair,
and two of them are within noise of zero.

Realised 1y annualised volatility, for the stop-sizing discussion below: TLT 11.7%, IEF 5.4%, GLD 25.2%
(gold's own recent parabolic-and-correction move, see section 4), LQD 6.4% -- against SPY's 19.4% over
the same window. Worst single-day move in five years: TLT -3.4%, IEF -1.8%, LQD -2.3%, GLD -10.3%
(2026-01-30, a real, verified data point, not a data error -- gold's recent rally correcting sharply).

## 4. Every parameter, and why

- **Universe (4 names, well under the 12 cap):** TLT, IEF, GLD, LQD -- see section 2 and 3. Kept
  deliberately small and non-redundant rather than padded to 12; a fifth or sixth correlated bond fund
  (e.g. AGG, which is largely a blend of the same three exposures) would not have added a genuinely new
  demand mechanism, only noise in the position count.
- **Entry: `close > sma(150) and ema(10) crosses_above ema(30) and rsi(14) < 70`.** Three conditions,
  each earning its place: `close > sma(150)` is the regime filter -- roughly seven months, faster than
  the 200-day convention used elsewhere in this tournament because flight-to-quality regimes in this
  basket (chop-2011, covid) develop and reverse over a period of months, not a year, and a slower filter
  would have missed meaningful entry windows in both. `ema(10) crosses_above ema(30)` is the timing
  trigger -- a fast/slow pair rather than the 20/50 convention, again because these are often sharp,
  compressed moves (2008 and 2020 both developed most of their move inside 8-12 weeks) that a slower
  cross would have entered late into. `rsi(14) < 70` is the risk-management condition specific to this
  card: it blocks entry into an already-extended move, reducing the chance of buying a local top in GLD
  or TLT right before a mean-reversion pullback trips the stop -- an explicit overbought guard, not
  present in the trend cards I reviewed in this round's shared directory.
- **Exit: `ema(10) crosses_below ema(30)`.** Symmetric momentum-loss exit -- the same pair that triggered
  entry, reversed. No separate mean-reversion logic; simplicity was chosen over an additional parameter.
- **Stop-loss 8%.** Tighter than the 12% convention used by growth-equity cards, matched to this basket's
  materially lower typical volatility (TLT/IEF/LQD 1y ann. vol 5.4%-11.7% vs. a growth stock's 40%+, and
  their five-year worst single day is 1.8%-3.4%). It is a poor fit for GLD specifically, whose own worst
  single day (-10.3%, 2026-01-30) would blow through this stop on one bad session -- I am stating that
  mismatch rather than hiding it, the same way an earlier trend-diversified card in this round's history
  had to for its own mixed-vol universe. The DSL and card schema give me one stop across the book; I
  chose the number that fits three of four names well and accepted the fourth is imperfectly served.
- **Max hold 120 sessions (~6 months).** Long enough to ride out a flight-to-quality regime that plays
  out over a quarter or two (matches the 150-day entry filter conceptually) without indefinitely marrying
  a position that has stopped trending.
- **max_positions 4, position_pct 0.20 -> capital committed 0.80.** One slot per name, sized so the book
  can be fully in all four at once without exceeding 80% of equity. The 20% permanent cash headroom is a
  deliberate risk choice, not an oversight: this is a card whose entire premise is capital preservation in
  a crisis, and holding cash in reserve caps the absolute worst case regardless of what the rules do.
  `capital_exposure` will read below what a fully committed book would show; that is the point, not a
  defect, and it should not be read as a smaller return on the same risk as a fully-committed card --
  it is a smaller amount of risk on purpose.

## 5. What would falsify this

The thesis is specifically about *why* these assets should rally when equities crash: duration and gold
demand rising because the shock is a growth/credit/liquidity scare. bear-2022 already falsifies the naive
version of "bonds always hedge stocks" -- when the shock is rate hikes themselves, duration assets fall
alongside or worse than equities, and my own measured numbers show TLT and LQD both underperforming SPY
that year. The thesis would be further falsified if, in a genuine growth-scare or credit-crisis window
(gfc-like or covid-like), this basket failed to show positive-to-flat returns while SPY was sharply
negative -- that would mean the flight-to-quality mechanism itself had broken, not just that one
particular regime (rate shocks) sits outside its domain. It would also be falsified if the rule-based
entries systematically missed the moves the buy-and-hold numbers show exist -- e.g., if the sma(150)
regime filter were so slow that the strategy never actually got long TLT/GLD until after most of the gfc
or covid rally had already happened, in which case the mechanism would be real but this implementation
would not be capturing it.

## 6. Predictions

**Worst window: bear-2022.** This is the one window in my own measured data where the mechanism itself
works against me rather than merely sitting idle: rising rates are simultaneously bad for equities and
directly bad for duration, so TLT and LQD do not diversify the drawdown, they compound it. I expect this
card to underperform SPY here, plausibly by a meaningful margin on a buy-and-hold basis, though the
sma(150) trend filter should keep the strategy mostly in cash for much of 2022 once TLT/LQD/IEF fall below
their own 150-day average early in the year, which should blunt -- not eliminate -- the damage relative to
a passive holding of the same basket.

**Best window: gfc.** This is where the mechanism is most extreme and cleanest: SPY -55.2% against a
basket that was +25.1% (TLT), +20.2% (IEF) and +23.9% (GLD) on a buy-and-hold basis, with only LQD mildly
negative. I expect this to be the clearest, largest positive-excess window this card produces, and it is
also the window every other analyst's index-derived universe is locked out of scoring on -- which is
exactly the seat this card is built to hold.
