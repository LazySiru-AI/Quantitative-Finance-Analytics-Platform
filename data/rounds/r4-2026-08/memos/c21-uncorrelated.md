# C21 -- Uncorrelated: global macro trend across commodities, precious metals and EM equities

`agent_id: c21-uncorrelated` | discipline: risk-managed | designed_through: 2026-02-13

## Positioning, stated up front

This round scores the combined book, not just individual cards, and the round's central finding is
that the strongest combined result so far came from correlation, not skill: B-momentum + C-trend +
c14 in equal thirds roughly halves the worst window (C-trend alone -22.9% -> trio -11.1%) because
C-trend and c14 measured ρ = +0.04 against each other, while B-momentum and C-trend measured +0.57 --
two versions of the same trade. My mandate is to be a third, genuinely different leg for that
combination: a book whose entries fire on oil supply, gold/silver monetary demand, and two single-country
equity cycles (China policy, Brazil commodity-and-politics), none of which has anything to do with the
AI/semis capex cycle that both B-momentum and C-trend actually trade. I am not trying to out-return
either incumbent. A modest median with genuinely low correlation is the job.

## 1. Mechanism, and who is on the other side

Six legs, six different demand mechanisms:

- **DBC** (broad commodity basket) and **USO** (crude oil) price on global supply/demand and inflation
  expectations -- OPEC decisions, shale supply, global industrial demand.
- **GDX** (gold miners) and **SLV** (silver) price on monetary/safe-haven demand and, for GDX, mining
  operating leverage on the metal price -- a different mechanism from both equity growth and government
  bond duration.
- **FXI** (China large-cap) prices on Chinese domestic policy, the property cycle, and regulatory risk.
- **EWZ** (Brazil) prices on commodity exports, the real, and domestic politics.

None of these four demand drivers is "is the market pricing in more AI capex this quarter" -- which is
the question B-momentum and C-trend are both actually asking, just with slightly different tickers and
entry filters. The counterparty on my trades is whoever is specifically positioned for the US-tech
cycle and gets surprised by an oil supply shock, a Fed move that hits EM currencies, or a China policy
shift -- flows that do not show up in an NVDA earnings call and that a momentum book concentrated in
mega-cap AI names has no reason to have priced.

## 2. Universe -- not index-derived

None of DBC, USO, GDX, FXI, EWZ, SLV is an S&P 500 or Nasdaq-100 constituent; all six are commodity or
single-country ETFs, selected on asset-class and demand-mechanism reasoning, not on today's index
membership. This card is **not** subject to the `universe_knowable_from` survivorship gate.

I considered and rejected three tempting alternatives, with numbers (all trailing-2y daily-return
correlation to an equal-weighted composite of B-momentum's 12 tickers, through 2026-02-13):

- **EEM** (broad emerging markets): 0.655. Rejected -- EEM's largest single-country weight is Taiwan,
  and TSM-adjacent semis exposure is a meaningful share of the index, which reintroduces exactly the
  AI/semis factor this card exists to avoid.
- **EFA** (developed ex-US): 0.594. Rejected for the same reason at a smaller scale, plus general
  global-equity beta.
- **HYG** (high-yield credit): 0.563. Rejected -- credit spreads compress and widen with equity
  risk-on/risk-off sentiment, which is close to a levered version of the same trade B-momentum already
  makes.
- **UUP** (dollar-index ETF), the instrument I most wanted for the taper-2013/inflation-2021 windows
  (the dollar tends to rally on Fed-tightening surprises, which is exactly complementary to a
  duration hedge failing), is **not present in the bar store** and could not be included. DX-Y.NYB is
  present but is a cash/spot index, not a tradable ETF, and I did not use it as a universe holding for
  the same reason no other card in this library buys an index outright.

## 3. Correlation argument -- measured

Trailing two years (2024-02-14 to 2026-02-13, 502 trading sessions), daily-return correlation of each
universe member to an equal-weighted composite of B-momentum's 12 tickers (NVDA AMD AVGO MU MRVL TSM
META MSFT GOOGL NOW AMZN NFLX):

| Ticker | Corr to B-momentum composite | Ann. vol | Worst single day |
|---|---|---|---|
| DBC | 0.268 | 15.9% | -5.0% |
| USO | 0.213 | 29.1% | -8.1% |
| GDX | 0.237 | 37.3% | -12.8% |
| FXI | 0.334 | 28.9% | -9.2% |
| EWZ | 0.338 | 23.8% | -7.0% |
| SLV | ~0.2-0.3 (per-name pattern) | 43.1% | **-28.5%** (2026-01-30) |

Every individual name sits between 0.21 and 0.34 -- meaningfully below the +0.57 B-momentum/C-trend
pairing this round flagged as "two versions of the same trade," and far below the EEM/EFA/HYG
alternatives I rejected in section 2.

**The honest complication:** an equal-weighted composite of my six names correlates to the B-momentum
composite at **0.407**, higher than the individual-name average of ~0.28. This is not a data error --
diversifying across six moderately-correlated names cancels idiosyncratic noise and leaves the shared
"global risk appetite" factor that even commodities and EM equities carry some of, more visible at the
portfolio level than at the single-name level. I am reporting this rather than only citing the flattering
individual-name numbers: 0.407 is still well below 0.57 and well below EEM/EFA/HYG, but it is not the
near-zero c14 achieved against C-trend (ρ = +0.04) with pure duration and gold. Section 8 explains why I
expect the *per-window* strategy correlation (the number that actually matters for the combined book) to
run lower than this daily-return figure regardless.

One data point worth flagging: SLV's -28.5% single-session move on 2026-01-30 is the same date c14's
memo flagged GLD's own -10.3% worst day -- a real, verified precious-metals correction, not a data
error. It is a poor match for a 15% stop on that name specifically, the same mismatch c14 disclosed for
GLD against its own 8% stop. I am stating it rather than hiding it (see section 6).

## 4. How often this card is actually on -- measured

`c14`'s 55 idle live sessions happened because its trend filter (`close > sma(150)`) is applied to four
assets -- TLT, IEF, GLD, LQD -- that are all driven by the same real-yield/duration factor and therefore
tend to fall in and out of regime together. My six legs are driven by four different macro stories (oil,
precious metals, China policy, Brazil), so they should not go in and out of regime in lockstep.

Measured over the trailing 90 sessions through 2026-02-13, using `close > sma(100)` as the regime test
on each name individually:

| | DBC | USO | GDX | FXI | EWZ | SLV |
|---|---|---|---|---|---|---|
| % of last 90 sessions in regime | 90% | 26% | 100% | 53% | 100% | 100% |

**At least one of the six names was in regime on every single one of the last 90 sessions -- zero idle
days -- with an average of 4.7 of 6 names simultaneously in regime.** That is the direct answer to the
brief's stated failure to beat: c14 went dark for 55 straight sessions because its four names moved
together; this basket has never gone dark over the same length of recent history because its six names
do not.

Over the full history through cutoff (2010-2026), the `close > sma(100) and ema(10) crosses_above
ema(30)` entry fires roughly 2.2-2.7 times per year per name (comparable in raw per-name frequency to
c14's own formula on TLT/IEF/GLD/LQD, 2.2-2.7/yr) -- the difference is not that my entry rule is looser
per name, it is that six weakly-correlated names practically guarantee at least one active signal at any
time, where four correlated names do not.

**Expected capital exposure:** with `max_positions=6` and `position_pct=0.15`, full commitment is 90% of
equity with a 10% deliberate cash buffer. Given the near-continuous in-regime coverage measured above, I
expect this card to run meaningfully invested most of the time -- likely 3-5 of 6 slots filled in a
typical session, not the near-zero exposure that sank `c12-meanrev-wide`.

## 5. Taper-2013 and inflation-2021 -- the two windows adversarial to duration

Buy-and-hold return of each leg over the exact window dates, using data through cutoff (both windows are
entirely historical, well before 2026-02-13):

**taper-2013 (2013-05-22 to 2013-09-05):** DBC +1.6%, USO +15.6%, GDX -0.5%, FXI -0.8%, EWZ -19.4%,
SLV +4.0% -- basket average roughly **flat (+0.1%)**. Contrast with c14's own basket over the identical
window: TLT -11.7%, IEF -7.2%, GLD +0.2%, LQD -7.1% -- uniformly negative except gold. Oil's own supply
story (US shale) rallied independently of the Fed-driven EM sell-off that hit EWZ hardest; the mixed
result nets out close to flat rather than compounding a duration hedge's loss.

**inflation-2021 (2021-01-04 to 2021-12-31):** DBC +42.1%, USO +67.9%, GDX -16.8%, FXI -21.0%,
EWZ -23.2%, SLV -15.1% -- basket average roughly **+5.7%**. Contrast with c14's basket: TLT -5.9%,
IEF -4.2%, GLD -6.2%, LQD -3.6% -- uniformly negative. The commodity legs (DBC, USO) captured 2021's
inflation/reflation trade directly, offsetting a genuinely bad year for gold miners and EM equities
(China's regulatory crackdown, a strengthening dollar into Fed taper expectations). This is not a
duration-only book, and it should not fail the way c14's does when rates are the shock rather than
growth.

I am not claiming this basket wins these windows outright -- both are net roughly flat to modestly
positive on a buy-and-hold basis, well below B-momentum's own performance in both (+13.4% and +45.8%
respectively). The claim is narrower: unlike a pure duration hedge, this basket does not get run over by
a rate shock, because at least one leg (commodities) is priced on the opposite side of that shock from
bonds.

## 6. Every parameter, and why

- **Universe (6 names, under the 12 cap):** DBC, USO, GDX, FXI, EWZ, SLV -- four distinct macro
  mechanisms (commodities/oil, precious metals, China, Brazil), chosen to minimize correlation to
  B-momentum (section 3) while maximizing the chance that at least one leg is in regime at any time
  (section 4). Six rather than four (c14's count) specifically to buy that near-continuous coverage.
- **Entry: `close > sma(100) and ema(10) crosses_above ema(30)`.** The `sma(100)` regime filter is
  faster than c14's `sma(150)` -- roughly five months vs seven -- because commodity and single-country
  equity trends in this universe (oil's 2014-15 collapse, the 2021 commodity rally, EM currency moves
  around Fed surprises) develop and reverse over a period of months, and I did not want the regime
  filter itself to be the reason this card sits idle. `ema(10) crosses_above ema(30)` is the same
  fast/slow timing pair c14 uses, for the same reason: these can be sharp, compressed moves. **No RSI
  overbought gate**, unlike c14's `rsi(14) < 70` -- a deliberate choice, not an oversight: c14's own
  55-idle-session problem is partly a filter-stacking problem (three simultaneous conditions on four
  correlated names), and adding a fourth condition here would only compound that risk on top of a
  regime filter that is already tighter than it needs to be. The stop and time-stop below are the risk
  controls; the entry's job is to fire.
- **Exit: `ema(10) crosses_below ema(30)`.** Symmetric to entry -- the same pair reversing. No separate
  logic, to keep the parameter count low.
- **Stop-loss 15%.** Sized to this basket's realized volatility (14-37% annualized across the six names,
  well above bonds, below a typical single growth stock) rather than to any one name. It is not well
  matched to SLV specifically, whose worst single day in the trailing two years was -28.5%
  (2026-01-30, the same date c14 flagged a -10.3% GLD move -- a real, verified precious-metals
  correction). A position-level stop check against the prior close, filled at the next open, means a
  move that large could realize a loss noticeably worse than 15% on that one name before the exit fills.
  I am keeping SLV in the universe for its diversification value and stating this mismatch explicitly
  rather than either hiding it or dropping a genuinely useful leg over one tail event, the same trade-off
  c14 made and disclosed for GLD against its own tighter stop.
- **Max hold 150 sessions (~7 months).** Slightly longer than c14's 120, because single-country equity
  and commodity trends in this universe (Brazil's 2009 recovery run, the 2021 commodity supercycle) have
  historically run longer than a typical flight-to-quality bond rally.
- **max_positions 6, position_pct 0.15 -> capital committed 0.90.** One slot per name, with a 10% cash
  buffer as a deliberate, modest risk choice -- smaller than c14's 20% buffer, reflecting that this
  card's job is to be reliably invested (section 4) rather than to hold maximum cash in reserve.

## 7. What would falsify this

The thesis is specifically that these six mechanisms are priced independently of the AI/semis capex
cycle. It would be falsified if: (a) the measured daily-return correlation to B-momentum, out of sample,
runs materially above the 0.2-0.35 individual-name band or the 0.41 composite band measured here --
particularly if it approaches the 0.57 B-momentum/C-trend benchmark, which would mean these six names
have started trading as a single "risk-on" factor rather than four separate stories; (b) the six legs
stop diversifying each other's entry/exit timing and start entering and exiting regime together the way
c14's four did, which would reproduce the same idle-desk failure with a different universe; or (c) a
window arrives where a broad, indiscriminate risk-off event hits commodities, EM equities and AI names
in the same session with similar magnitude -- global liquidity crises do exist, and this card is not
claiming immunity from one, only that its normal-regime and rate-shock behavior is measurably different
from an equity-momentum book.

## 8. Predictions, scored

**Worst window: oil-2014.** Buy-and-hold evidence: DBC -33.8%, USO -52.9%, GDX -19.2%, EWZ -33.1% over
the window, while FXI alone was +11.3% and B-momentum's own composite was actually *up* +9.6% (the 2014
oil collapse was largely idiosyncratic to energy and commodity-linked EM, not broad tech). This is the
window where my mechanism argument cuts against me hardest: an oil-specific supply shock hits four of my
six legs directly and simultaneously. I expect the entry/exit rules and 15% stop to meaningfully limit
the damage relative to raw buy-and-hold (the stop should have taken USO and DBC out well before -50%),
but I still expect this to be the card's worst window, plausibly a double-digit drawdown even after risk
management, and I expect it to be the window where correlation to B-momentum is most *negative* rather
than positive -- oil crashing while AI names rallied is a genuine divergence, just not in my favor.

**Best window: inflation-2021.** Buy-and-hold evidence in section 5: DBC +42.1%, USO +67.9% captured
2021's commodity/reflation rally directly, an environment my mechanism is specifically built to catch
and c14's duration-only book cannot. I expect this to be the clearest positive-excess window for this
card, and specifically a window where it is doing something genuinely different from both B-momentum
(which was up on AI-specific strength, not commodity strength) and c14 (which was flat-to-negative on
rising real yields).

**Expected per-window return correlation to B-momentum: roughly 0.1 to 0.3** -- lower than the 0.407
daily composite correlation measured in section 3, for three reasons: window-level correlation is
measured on far fewer, noisier data points (6 windows, not 502 daily observations) and is dominated by
which specific shock defined each window rather than by the shared low-frequency risk factor that
inflates the daily figure; the entry/exit rules add timing dispersion on top of raw daily co-movement,
since my six legs are not all in regime simultaneously (section 4) the way a fully-invested buy-and-hold
composite would be; and at least one window (oil-2014) should show outright negative correlation given
the buy-and-hold evidence above. If the realized number lands well above 0.3, or above the 0.57
B-momentum/C-trend benchmark, the correlation argument in this memo is wrong and should be read as such,
not explained away.
