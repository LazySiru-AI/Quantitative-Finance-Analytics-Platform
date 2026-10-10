# c09-convex -- Flight-to-Quality Insurance

`discipline: volatility` | `agent_id: c09-convex`

## 1. What kind of card this is (per the brief's two traps)

This is **not** an abstention card. Its entry rule fires on `close crosses_above bb_upper(20,2)`
evaluated on TLT and GLD's *own* bars -- there is no way to write "buy TLT when SPY falls" in this
DSL (no cross-symbol gating), so the payoff has to come, and does come, from a volatility breakout in
the instrument I actually hold. When the card is not triggered it holds nothing and that time is
scored as flat, exactly like every other card's idle time -- it does not claim credit for SPY falling
while empty, because it is never long SPY or short anything.

It is also not "sit in cash and call it insurance." At most 30% of the book (two slots x 15%) is ever
committed, so on a time-weighted basis roughly 85-90% of the book is uninvested cash throughout every
window (measured `capital_exposure` below is 4-10% per window). The engine scores that idle cash as
free. A real portfolio running this as a hedging *sleeve* alongside a core equity book would have that
majority-cash figure either earning the risk-free rate or invested in the core book itself -- so every
cost number below is a sleeve-only cost, understated relative to what carrying this insurance would
really cost a fully invested portfolio. I am stating this explicitly rather than letting the card's
low exposure read as cheap insurance in the report.

## 2. Mechanism

In a systemic equity selloff, capital does not vanish, it rotates. Institutional and retail investors
de-risk out of equities into US Treasury duration and, in uncertainty-driven episodes, into gold. That
rotation shows up first as a **volatility breakout** in the receiving instrument's own price -- a
forced, non-price-sensitive buying wave widens the instrument's own price bands and pushes it above
its 20-day Bollinger upper band before any slower trend filter (a moving-average cross) would confirm
anything. The seller on the other side of a TLT or GLD trade at that moment is whoever was still
willing to hold the pre-rotation price -- in ordinary times that seller is trading on yield curve
views or a jewelry-demand model, has no connection to equity risk, and keeps taking the trade because
a 20-day band breakout in a duration or gold ETF is, on an ordinary day, a weak and cheap signal (see
the whipsaw cost below). It becomes a strong, well-paid signal exactly when equity holders are forced
sellers, because that is the one condition under which the other side of a TLT/GLD trade stops being a
considered view and becomes a stampede with nowhere else to go.

**Discipline fit:** the entry condition is a volatility-expansion signal (Bollinger breakout), not a
trend or momentum filter -- the card is designed to be fast enough to catch the acceleration at the
start of a rotation, at the cost of firing on ordinary noise the rest of the time. That trade-off is
the volatility discipline's whole content.

## 3. Universe, and why

`["TLT", "GLD"]`. Both are in the WINDOWS.md tier that reaches every window including the GFC (first
bar 2002-07-30 and 2004-11-18 respectively, both well before `gfc` starts 2007-10-09), so this card is
**eligible for all 8 of 8 main windows**, clearing the 5-of-8 gate with no margin risk. I deliberately
did not reach for an inverse/leveraged instrument (SQQQ, SOXS) to build convexity, even though a short
Nasdaq or short semis exposure is the more obvious way to get a crash payoff long-only: both only have
history from 2010-2014 onward, which would have made the card eligible for at most `chop-2015`,
`bear-2022`, `bull-2024`, `recent` -- 4 of 8, under the gate, and specifically absent from every
crisis window except `bear-2022`. A convex card that cannot be tested against the GFC or covid has not
demonstrated the thing it claims. TLT and GLD trade the payoff up through a long position instead of
a short one, which is the only way this long-only DSL can express "profit when equities are sold."

Two symbols, not one, because they catch different flavors of dislocation: TLT catches rate-cut,
flight-to-duration crises (gfc, covid, q4-2018); GLD catches inflation/uncertainty-driven ones and
also caught the 2011 European-debt-crisis flight inside `chop-2011`. Neither alone is reliable across
all four crisis-type windows (see the trade log below: TLT lost money outright in `bear-2022`, a
rate-*hike* decline where duration does not get a flight-to-quality bid).

## 4. Parameters and budget (limit 10)

| where | value | why | count |
|---|---|---|---|
| `bb_upper(20,2)` in entry | period 20, stddev 2 | the standard Bollinger convention -- the same `(20,2)` the repo's own rule catalog uses for `bb_upper_touch`/`bb_lower_touch`. Not a search result. | 2 |
| `sma(20)` in exit | period 20 | matches the entry's own lookback (it is literally the midline the entry's bands are built from) rather than introducing a second, independently-chosen period | 1 |
| `stop_loss_pct` | 0.10 | a round, conventional 10% hard stop as a backstop against a bad fill; see §6 -- it never actually bound in the design-window trade log, so it is disclosed as untested rather than claimed as load-bearing | 1 |
| `take_profit_pct` | null | deliberately unset -- capping the upside is the one thing a convex payoff cannot afford; the exit rule and time stop are the only ways out | 0 |
| `max_hold_days` | 180 | a backstop against a position that never mean-reverts back below its own 20-day average; did not bind in any design-window trade either | 1 |
| `max_positions` | 2 | one slot per symbol, both can be held at once | 1 |
| `position_pct` | 0.15 | 15% per slot, 30% of the book fully deployed -- small and bounded by design; also sits under the persona's *real* 25% single-name cap, so this card does not rely on round 2's raised-to-100% relaxation at all | 1 |

**Total: 7 of 10.** `take_profit_pct` costs nothing because it is unset.

## 5. What I measured in the design window, and the code I ran

I did not use the tournament's own `run_card` for this because it opens `duck.connect()` without
`read_only=True` per symbol-read (confirmed in `backend/app/market/store.py`), which would take a
write lock against four other analysts' concurrent DuckDB access -- exactly the failure mode
WINDOWS.md warns about. Instead I wrote a read-only reconstruction of the same entry/exit/stop/
time-stop/sizing logic against bars pulled with `duck.connect(path, read_only=True)`, in
`.scratch/c09-convex/sim4.py` (fee-free and slippage-free, so it is a *design-window estimate*, not a
claim about what the engine will report). For each of the 8 windows I computed the card's own
`capital_exposure` the same way `AgentResult` defines it (entry notional summed over open sessions,
over `sessions * starting_equity`) and used the exact SPY benchmark returns published in WINDOWS.md to
compute `adjusted_excess = return - capital_exposure * benchmark_return`.

Result, at the card's actual parameters (bb(20,2), exit sma(20), stop 10%, max_hold 180, 15%/slot):

| window | card return | capital_exposure | SPY benchmark | adjusted_excess |
|---|---|---|---|---|
| gfc | +1.18% | 10.1% | -56.23% | **+6.87%** |
| q4-2018 | +0.78% | 9.2% | -20.05% | **+2.62%** |
| covid | +0.97% | 4.5% | -8.71% | **+1.36%** |
| bear-2022 | -0.64% | 4.3% | -25.14% | +0.45% (raw loss -- see §1/§6) |
| chop-2011 | +4.07% | 9.8% | -0.05% | +4.07% (a real 2011 flight-to-quality episode, not noise) |
| recent | +2.92% | 7.4% | +20.62% | +1.39% |
| chop-2015 | -1.09% | 8.7% | -0.04% | **-1.09%** |
| bull-2024 | -1.94% | 9.1% | +14.00% | **-3.22% (worst)** |

**Premium (cost in ordinary windows):** the two windows with no real crisis to catch,
`chop-2015` and `bull-2024`, cost -1.09 and -3.22 points of adjusted excess. I quote **roughly 1 to 3
points of adjusted excess per ordinary window** as the premium -- `chop-2011` is excluded from that
estimate because, despite being classified as a directionless SPY year, it contains a genuine 2011
European-debt/US-downgrade flight-to-quality episode that this card is supposed to catch and did
(+4.07%), so calling that a "cost" would misdescribe what happened.

**Payoff (crisis windows):** +1.4 to +6.9 points of adjusted excess, scaling with the depth and
duration of the selloff -- largest in `gfc` (the deepest, longest drawdown in the matrix), smallest in
`covid` (fastest single shock, and the entry needs a handful of sessions of realized volatility to
push a close through the upper band, so it caught the back half of the crash and the recovery rather
than the first violent leg down).

## 6. Sensitivity check

Per §2 of the brief, I did not grid-search for a best setting -- I swept the parameters to confirm the
*qualitative* convex shape (small ordinary-window cost, larger crisis-window payoff) is not an
artifact of one lucky combination.

- **`stop_loss_pct` at 8% / 10% / 12%:** identical results at all three settings, across every window.
  The stop never actually fired in the design-window trade log -- every exit was `rule` or `time`. I
  am disclosing this rather than presenting it as evidence of robustness: the stop is a backstop for a
  bad fill this history did not happen to produce, not a tested control.
- **`position_pct` at 12% / 15% / 18%:** scaled the P&L close to linearly and left every window's sign
  unchanged, as expected for a fixed-fraction sizing rule.
- **Full 3x3x3 grid over `bb_n` in {15,20,25}, `bb_k` in {1.5,2.0,2.5}, exit `sma` period in
  {15,20,25}** (27 combinations, `.scratch/c09-convex/sim5.py`): the average adjusted excess across
  the three crisis windows (gfc, covid, q4-2018) was positive in **all 27** combinations, ranging
  +1.3% to +5.3%; the average across the four non-crisis windows ranged -0.08% to +1.4%, i.e. never
  the large, one-sided cost a fitted parameter set would show if nudged. The single worst-scoring
  window was `bull-2024` in 24 of 27 combinations and `bear-2022` in the remaining 3 -- both are
  candidates I name below, and neither result depends on the specific `(20,2)` choice I shipped.

## 7. The named window I expect to lose in

**`bull-2024`.** Across every parameter combination I tested it is overwhelmingly the numerically
worst window on `adjusted_excess` (-3.22% at the shipped parameters): a strong, low-volatility equity
year gives TLT and GLD nothing to rotate into, the entry still fires on ordinary band-breakout noise,
gets stopped out against `sma(20)` repeatedly, and pays its premium against a benchmark that is
itself up 14% -- the worst combination for a card whose whole value proposition is showing up only
when equities are in trouble.

I want to flag one thing separately, because it would be dishonest to bury it under the number above:
**`bear-2022` is where the underlying *mechanism* fails**, even though it does not score as the worst
window. 2022 was a rate-hike-driven decline that hurt equities and duration together -- there was no
flight-to-quality rotation into TLT to catch, and the card's raw return there is a real loss (-0.64%).
The positive `adjusted_excess` shown for that window is an artifact of the low exposure denominator
against a benchmark that also fell hard, not evidence the trade worked. If the report shows
`bear-2022` and `bull-2024` both underperforming, that is two different failure modes, not one, and
only one of them was mispredicted.

## 8. What I tried and abandoned

- **SQQQ / SOXS (inverse-leveraged) crash-catchers.** More directly convex on paper, but both only
  have price history from 2010-2014 onward (WINDOWS.md tier), which caps eligibility at 4 of 8 main
  windows and specifically excludes `gfc`, `covid`, `q4-2018`, `chop-2011` -- exactly the windows a
  convex insurance card most needs to demonstrate itself against. Mixing them into a universe with
  TLT/GLD would have dragged every window's eligibility down to the shortest-history symbol's floor,
  not helped it. Abandoned for the eligibility math, not for the mechanism.
- **`sma(50)` trend-confirmation entry/exit (golden-cross style) on TLT+GLD.** Tested first; too slow.
  It caught only the tail of `gfc` (a single trade entering 2008-11-18, well after the sharp part of
  the crash, netting the window to **-2.05%** overall once whipsaw losses elsewhere in the window were
  included) and generated 20-36 small losing round-trips per chop window. A confirmation-based entry
  is the wrong tool for a payoff that needs to be *fast*, not *sure* -- I switched to the Bollinger
  breakout specifically because it reacts to the volatility expansion itself rather than waiting for a
  trend to be confirmed.
- **`sma(100)` / `sma(150)` / `sma(200)` variants of the same idea.** Same problem, worse: `sma(200)`
  netted `gfc` to essentially flat (-0.11%) because the 200-day filter takes months to turn during a
  crash that resolves in weeks. Confirmed the whole moving-average-cross family is the wrong shape for
  this card's job before moving to bands.
- **Single-symbol TLT-only version.** Eligible everywhere, simpler, but weaker: no payoff in
  `chop-2011`'s European-crisis episode and a real loss in any window (like `bear-2022`) where rates
  rise instead of fall. GLD's presence is what keeps the card from being a pure rates bet.

## 9. Weakest assumption (for the report-back)

Everything in §5-§6 is a **design-window** measurement -- fee-free, slippage-free, and reusing the
tournament's own historical windows I was told about in advance (WINDOWS.md names them explicitly).
Round 2 is not out-of-sample per §4 of the brief, and I am not claiming otherwise.
