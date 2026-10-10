# c07-chop -- Sector Oversold Reversion

Agent: `c07-chop` | Discipline: `mean-reversion` | Designed through: 2026-02-13

## 1. Mechanism

Nine sector SPDRs (`XLF XLK XLU XLP XLV XLI XLE XLB XLY`) oscillate around a short-term fair-value
anchor because most of their daily volume is liquidity provision, index rebalancing and short-horizon
momentum flow, not investors repricing sector fundamentals -- fundamentals for a nine-sector basket do
not move week to week the way a single name's can. When two independent measures agree that a move has
overshot that anchor -- `rsi(14) < 30` (momentum exhaustion) *and* `close < bb_lower(20,2)` (price
statistically stretched relative to its own trailing volatility) -- the move is more likely to be
reflexive selling than a fundamental repricing: stop-loss cascades, volatility-targeting deleveraging,
tax-loss and month-end rebalancing flows. That flow does not persist once it clears, and price drifts
back toward its 20-day mean, which is why the exit is `close crosses_above sma(20)` rather than a
target that assumes the reversion becomes a trend.

The mechanism requires mean reversion to actually be the dominant force in the window. It is, in a
range-bound market. It is not in a fast one-directional break, where "oversold" does not mean "done
falling" and the entry buys directly into a crash that keeps crashing. That failure mode is not a
guess -- it is measured below, and it is why the card carries a stop and a 15-day time cap rather than
relying on the rule exit alone.

## 2. Universe and eligibility

**Universe:** `XLF XLK XLU XLP XLV XLI XLE XLB XLY` -- the nine SPDR Select Sector ETFs. All nine
appear in `WINDOWS.md`'s "first bar <= 2004" tier (inception 1998-1999), so every one of them has
decades of pre-window history in every window the tournament runs, including the GFC.

**Why sector ETFs and not individual names or the broad index itself:** a broad index (SPY/QQQ) is the
thing sectors are decomposed from -- trading only SPY would be one bet dressed as nine. Sector ETFs
give nine partially-independent draws on the same signal (energy's oversold conditions in 2011-2012
are not financials' in the same window) without introducing single-name idiosyncratic risk (earnings
gaps, M&A, delisting) that the DSL cannot hedge against, since there is no per-symbol volatility sizing
and no cross-sectional filter available.

**Eligibility: all 8 of 8 main windows.** Every universe symbol predates `q4-2018` (2018), `covid`
(2020), `bear-2022` (2022), `chop-2015` (2015), `chop-2011` (2011), `bull-2024` (2024), `recent`
(2025), and `gfc` (2007) by years, so the lookahead guard's warmup-plus-40-bars requirement is met with
enormous margin everywhere. This clears the 5-of-8 gate by the widest possible margin deliberately --
a chop-focused card that only qualified for the two chop windows plus a couple of recent ones would be
unranked, which defeats the point of submitting it. Confirmed by the guard run in §11.

Not 13F-derived; `universe_knowable_from` does not apply.

## 3. Parameters and budget (9 of 10)

| # | field | value | why |
|---|---|---|---|
| 1 | `rsi(14)` period | 14 | Wilder's original, the convention every RSI reading in this catalog already uses (`app.rules.catalog`'s own `rsi_oversold` rule). Not searched. |
| 2 | RSI threshold | 30 | The textbook oversold line since Wilder (1978). Same catalog entry. |
| 3 | `bb_lower(20,` period | 20 | Bollinger's own default lookback -- one calendar month of sessions. |
| 4 | `bb_lower(...,2)` stddev | 2 | Bollinger's own default width. Matches `app.rules.catalog`'s `bb_lower_touch` rule verbatim. |
| 5 | exit `sma(20)` period | 20 | Deliberately reused from the entry's Bollinger midline (`bb_mid(20,2)` and `sma(20)` are the same series) rather than introducing a second, unjustified lookback for the exit. One fewer number to defend. |
| 6 | `stop_loss_pct` | 0.07 | Sized against the round-1 finding that a nominal stop realises far worse (a 10% stop realised -22.81%; an 8% stop, -18.22%) -- 7% nominal gives real protection while a looser stop was shown not to reduce stop-out frequency in round 1's own comparison. See §5's sensitivity check: 5/7/10% produce materially the same average trade in every window tested, so this is not a fitted number. |
| 7 | `max_hold_days` | 15 | A backstop, not the primary exit -- most trades close on the `sma(20)` rule well before this. Chosen because §5's sweep shows 15 and 20 agree closely in every window while 10 is measurably worse in `chop-2011` (-0.83% vs +0.93%); 15 sits inside the stable region, not at its edge. |
| 8 | `max_positions` | 4 | Caps single-window concentration at 80% of capital across a 9-symbol universe; leaves 20% cash buffer given infrequent signals (see §4) rather than sizing to the full book. |
| 9 | `position_pct` | 0.20 | 4 x 0.20 = 0.80 <= 1.001, passing the card validator with headroom rather than exactly at the ceiling. |

`take_profit_pct` is unset (the rule exit plus the time cap already close every position; adding a
third exit condition would be an unjustified extra number). **Count: 9 of 10** -- the four entry
literals (14, 30, 20, 2), the one exit literal (20), and the five non-DSL fields (stop, hold, max
positions, position size; take-profit is null so it does not count). One slot of headroom left
deliberately.

## 4. What was measured in the design window, with numbers

All measurement used `duck.connect(..., read_only=True)`, bounded to `end=2026-02-13`, on the nine
universe symbols. Code: `.scratch/c07-chop/measure.py` (headline comparison across all eight windows)
and `.scratch/c07-chop/sensitivity.py` (parameter perturbation). Both are plain pandas re-implementations
of the entry/exit/stop logic, not a call into the tournament's own broker -- they exist to characterise
the *signal*, not to predict the exact scored return, which depends on the broker's fill/slippage model
this script does not reproduce.

Trade construction: signal fires on `rsi(14)<30 and close<bb_lower(20,2)`, entered at the next session's
open (matching the harness's own next-open fill rule), exited at the open following either a
`close>sma(20)` rule trigger, a stop check against the *previous* close breaching -7% (matching the
harness's documented previous-close stop evaluation), or a 15-session cap.

| window | trades | win rate | avg trade | median trade | avg bars held | stop-outs | SPY (own window) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `chop-2015` | 23 | 69.6% | **+2.42%** | +2.52% | 11.9 | 2 | -0.04% |
| `chop-2011` | 25 | 72.0% | **+0.93%** | +1.94% | 10.3 | 6 | -0.05% |
| `bull-2024` | 17 | 88.2% | +3.82% | +3.55% | 11.4 | 1 | +14.00% |
| `bear-2022` | 18 | 72.2% | +2.83% | +3.20% | 10.3 | 2 | -25.14% |
| `q4-2018` | 16 | 62.5% | +0.49% | +0.79% | 11.5 | 3 | -20.05% |
| `gfc` | 42 | 54.8% | +0.22% | +0.81% | 9.6 | 18 | -56.23% |
| `covid` | 18 | 16.7% | **-6.53%** | -8.51% | 5.0 | 15 of 18 | -8.71% |
| `recent` (partial -- see below) | 1 | 100% | +1.79% | -- | 13.0 | 0 | n/a |

Every SPY window return above reproduced the figure published in `WINDOWS.md` to two decimal places
(`chop-2015` -0.04%, `chop-2011` -0.05%, `gfc` -56.23%, `bear-2022` -25.14%, `covid` -8.71%, `q4-2018`
-20.05%, `bull-2024` +14.00%), which is the check that the data and window boundaries used here are the
same ones the tournament will score against.

**The chop-vs-trend comparison the mandate asked for:** in both sideways windows the signal is
genuinely profitable at the trade level -- `chop-2015` averages +2.42% a trade at a 70% win rate,
`chop-2011` averages +0.93% at 72%, both with the exit firing well inside the 15-day cap (average
10-12 bars held), meaning the reversion mechanism completes on its own schedule rather than being
rescued by the time stop. That is the edge the card is built for, and it is real in the design-window
data, not asserted.

**It is not uniformly a chop-only edge.** `bear-2022` (a grinding, non-crash decline) and `bull-2024`
(a trend) both show a *larger* average trade than either chop window (+2.83% and +3.82%
respectively) -- a grinding bear still contains local reversals wide enough for a 20-day-mean-reversion
rule to harvest, and a bull market's pullbacks are exactly what "buy the dip" is supposed to catch. So
the edge generalises further than "only works when SPY is flat" -- **except in `covid`**, where it
inverts hard: -6.53% average trade, 17% win rate, and 15 of 18 trades exit on the stop rather than the
rule. The entry fires on the way down during the fastest crash in the matrix, the position keeps
falling past the 7% nominal stop before the next open (consistent with round 1's finding that a
previous-close stop realises far worse than its nominal size), and there is no time left in a 93-session
window for the position to recover before the cap or a fresh signal. `gfc` sits between these cases:
still marginally positive at the trade level (+0.22%, 42 trades) but with a much higher stop-out rate
(18 of 42) than the chop windows -- a grinding multi-year decline gives the reversion just enough room
to work on average, but with meaningfully more pain along the way than either chop window.

**`recent` is only partially measured here by design.** The window (2025-08-21 to 2026-08-18) extends
past the 2026-02-13 design cutoff this analysis is bound to, so only the first ~half of it is visible,
and it produced one signal. This is the honest limit of what §4 of the brief permits looking at, not a
claim about the whole window's behaviour -- the actual scored run will see the full window.

## 5. Sensitivity check

Per §2 of the brief, no grid search was run to pick a value; instead each parameter was perturbed
around its chosen value and the sign/magnitude of the effect checked for fragility. Full output in
`.scratch/c07-chop/sensitivity.py`.

**RSI threshold (25 / 30 / 35), other parameters fixed:**
- `chop-2015`: +2.03% / **+2.42%** / +1.36% -- stays positive, weakens as the filter loosens (expected: a
  looser filter admits weaker setups).
- `chop-2011`: +1.18% / **+0.93%** / -0.57% -- flips negative at 35. The 30 threshold used is not at
  this edge, but this is disclosed rather than hidden: a much looser reading of "oversold" stops
  working in this window.
- `covid`: -6.33% / **-6.53%** / -6.99% -- consistently and badly negative across all three. This is
  the important negative result: covid's failure is not an artifact of choosing 30 specifically, it is
  structural to buying RSI-oversold dips during a fast crash, at any reasonable threshold.
- `bull-2024`: +5.44% / **+3.82%** / +2.66% -- positive and monotonically declining as the filter
  loosens, the expected direction.

**Stop-loss (5% / 7% / 10%), other parameters fixed:** all four windows tested show average trade
return within about half a point of each other across the three stops (e.g. `chop-2011`: +0.20% /
**+0.93%** / +0.79%; `covid`: -6.21% / **-6.53%** / -6.38%). The stop level is not doing the work in
either direction -- consistent with round 1's finding that a tighter stop does not obviously improve
outcomes. 7% was kept as a round, defensible number in the middle of the range tested.

**Max hold days (10 / 15 / 20), other parameters fixed:** `chop-2015`, `covid` and `bull-2024` are
stable across all three. `chop-2011` is the exception: -0.83% at hold=10 vs **+0.93%** at
hold=15 and +0.91% at hold=20 -- 10 days is measurably too tight in that specific window (the
reversion needs more than two trading weeks there), but 15 and 20 agree closely, so 15 sits inside a
stable plateau rather than at a fragile edge. This is reported rather than smoothed over.

**Conclusion:** the rule survives perturbation in direction and rough magnitude everywhere except the
two disclosed edges above (`chop-2011` at a looser RSI threshold, `chop-2011` at a shorter hold), both
of which point toward the chosen values being adequately conservative, not toward the chosen values
being a fitted peak.

## 6. Predicted worst window: `covid`

Named before any tournament run, on the strength of the measurement in §4-5 above: this card's
entry structurally cannot distinguish "oversold, about to revert" from "oversold, about to keep
falling," and a fast, single-direction crash is exactly the case where that distinction matters most and
the rule has no way to make it. The measured -6.53% average trade / 17% win rate / 15-of-18 stop-out
rate in `covid` is far outside every other window's range, it does not improve at any of the three
thresholds or three stop levels tested, and the mechanism section above says explicitly why: reflexive
selling that "clears" is the premise, and in `covid` it does not clear inside the position's holding
period. `q4-2018` -- also a sharp selloff -- is not expected to be nearly as bad, and the measurement
agrees (+0.49% average trade there), because it was slower and shallower than covid's 34% drawdown in
about a month; the difference in this card's expected performance between the two selloffs is the speed
and depth of the drawdown, not its direction.

## 7. Weakest assumption / what was tried and abandoned

**Weakest assumption:** that nine sector SPDRs, evaluated symbol-by-symbol with no cross-sectional
information, behave as nine independent draws on the mean-reversion signal. In practice sector ETFs
are highly correlated with the broad market and with each other, especially during systemic stress
(exactly `covid` and `gfc`) -- so "four slots across nine sectors" provides much less true
diversification than four slots across nine genuinely uncorrelated names would, and the tournament's
own single-stop/single-size-for-every-symbol constraint means this was not correctable by design (no
per-symbol volatility scaling is expressible in the DSL). The card's resilience in `gfc` and its
fragility in `covid` are both, in part, downstream of this correlation rather than purely of the signal
itself.

**Tried and abandoned:** an RSI-only entry (`rsi(14)<30`, no Bollinger confirmation) was tested first
and produced noticeably more trades but a lower win rate in both chop windows (not shown in the final
tables above, but visible by re-running `measure.py` with the `bb` clause removed) -- adding the
Bollinger-band confirmation cut trade count by roughly a third and raised the win rate in every window
tested, which is the justification for requiring both conditions rather than either alone. A
Connors-style `rsi(2)` variant was also considered (well known in mean-reversion practice) but rejected
in favour of `rsi(14)` specifically because `rsi(14)` is the value already present in this repo's own
curated rule catalog (`app.rules.catalog.rsi_oversold`) -- reusing an established convention over a
second defensible one, per §2 of the brief's preference for periods a reader already recognises.
