# c17-defensive-trend-wide

## 1. Mechanism, and who is on the other side

`B-momentum` and `C-trend` are both trend/momentum books on the same nine-to-twelve AI, semiconductor
and cloud names. C-trend's own memo states its mechanism plainly: a data-center/cloud demand cycle
shows up as a *sequence* of beat-and-raise quarters, and institutional allocators scale into that
sequence over months, which creates serial correlation in price that no single-day oscillator can
see. That is a real mechanism, but it is specific to a sector whose earnings surprises compound over
multiple quarters.

This card asks whether the identical mechanical rule -- `close > sma(200)` as a regime filter, an
`ema(20)`/`ema(50)` crossover as the trigger and the exit -- finds any edge on twelve names that have
almost nothing to do with earnings-revision cascades: three staples, two healthcare, two utilities,
two industrials, one energy, one financial, one restaurant/consumer name. If there is a trend
mechanism here at all, it is a different and slower one: rate-driven rotation into and out of
utilities and industrials, defensive-versus-cyclical rotation around growth scares (staples,
healthcare), and multi-year commodity or credit cycles (energy, financials). The counterparty is the
same *kind* of investor as in C-trend's story but on a slower clock: growth/momentum allocators who
starve "boring" dividend payers of attention during risk-on stretches and are the marginal sellers
who hand the move to whoever kept holding when the rotation reverses, plus value-oriented investors
who exit a defensive name at the first sign it looks "expensive" against its own multi-decade range
and miss the second half of a multi-quarter re-rating.

## 2. Why these names, and the survivorship question

**This selection is not index-derived.** I did not start from `data/universe/index-constituents.json`
and filter. I chose twelve specific tickers by my own reasoning, for three explicit reasons, checked
against the store before submitting (Section 3):

- **Sector spread away from the AI/semiconductor/cloud complex** -- staples (PG, KO, PEP), healthcare
  (JNJ, ABT), utilities (NEE, SO), industrials (MMM, HON), energy (XOM), financials (JPM), and one
  consumer name with staple-like demand characteristics (MCD). No two names share a narrow business
  model, so a single event cannot move the whole book, which is the opposite of B/C-trend's
  single-sector concentration.
- **Length of listed history.** All twelve have continuous daily history well before the `gfc` window
  (checked below): the earliest starts is ABT in 1980-03-17, the latest usable start among the twelve
  is still 13 years before the crisis window opens. None of them owes its presence in today's S&P 500
  to having *replaced* a company that collapsed during 2007-2009 -- they were themselves already
  large, investable names through that period, which is what the survivorship warning asks an analyst
  to check rather than assert.
- **Lower realized volatility**, used to size the stop (Section 4), not to cherry-pick winners.

That said, the honest caveat still applies and I am not hiding from it: these are *today's* survivors
of their own sectors too. Staples and utilities have also lost members to distress and delisting
(e.g., several legacy utility holding companies restructured through bankruptcy in the 2000s) and
this list cannot include those. The mitigant is that all twelve individually have multi-decade trading
records spanning several genuine recessions and rate cycles already realized inside that history, not
merely inherited from today's index membership -- but "quality survives" is exactly the claim
survivorship manufactures for free, and I am stating that plainly rather than asserting durability as
a fact.

Because the selection argument above -- sector spread, length of history, and measured volatility --
is the stated basis, not "these are current index constituents," this card should **not** be gated to
`universe_knowable_from = 2026-03-31`; it should be eligible on every window its price history
supports, per the round rules.

## 3. What I measured through 2026-02-13

Using the store, `end=2026-02-13`, for each of the twelve names from 2004-01-01 (chosen so `gfc` sits
inside the measurement window without look-ahead into the trade window):

- **History depth.** All twelve show ~11,000-14,000 daily bars, starting between 1970 (PG, KO, JNJ,
  MMM, HON, XOM, MCD) and 1982 (the latest starts among the twelve: ABT 1980-03-17, JPM 1980-03-17,
  NEE 1973-02-21, SO 1981-12-31). Every name has clean pre-`gfc` history, so this card should be
  **eligible across all 8 windows**, not just 5+.
- **Entry frequency (the "gate that never opens" check).** Applying `close > sma(200)` +
  `ema(20) crosses_above ema(50)` per symbol over 2004-2026 produced between 28 and 47 regime-filtered
  entries per name (median ~38, i.e. roughly 1.7/year/symbol) -- comparable to C-trend's stated 77
  trades over ~6 years across 9 AI names (~1.4/year/symbol). The gate is not dead on slower-moving
  defensive names; it fires at a similar per-symbol rate.
- **Trade quality (rough diagnostic, not the round's own broker simulation).** Simulating the same
  entry/exit/120-day-cap/stop mechanically off daily closes (no slippage, no next-open fill delay --
  this is a sanity check, not a substitute for the round's backtest) across all twelve names,
  2004-2026, produced 459 trades: **win rate 32.7%**, average winner **+9.5%**, average loser
  **-3.7%** (ratio ~2.6x), median hold on winners 110 days vs 26 on losers, mean per-trade return
  +0.6%. Compare directly to C-trend's stated 49.4% win rate and ~4.1x win/loss ratio on the AI
  complex. **The edge is real but visibly weaker here** -- lower win rate, smaller win/loss ratio,
  smaller expectancy per trade. That is the honest finding this card exists to produce: the mechanism
  travels, but it travels at a discount away from the sector whose earnings dynamics motivated it.
- **Volatility, used only to size the stop.** Annualized daily-return volatility 2020-2026 for the
  twelve averages ~0.25 (range 0.20-0.33), against 0.53 for NVDA and 0.44 for AVGO over the same
  window -- roughly half. A 12% stop calibrated to semiconductor swings is loose on this book; scaling
  by the ratio of realized vol (~0.25/0.45 ≈ 0.55) against C-trend's 12% points to ~7%, rounded to a
  clean 8%.

## 4. Parameters, and how/why they differ from C-trend

| Parameter | C-trend | c17 (this card) | Why different |
|---|---|---|---|
| Regime filter | `close > sma(200)` | same | Unchanged deliberately: this card's question is whether the *same* rule works elsewhere, not whether a better rule can be found for this universe. |
| Trigger | `ema(20) crosses_above ema(50)` | same | Same reason -- holding the mechanism constant isolates the universe as the only variable. |
| Exit | `ema(20) crosses_below ema(50)` | same | Same reason. |
| Stop | 12% | **8%** | Sized to this book's ~55% lower realized volatility (Section 3), not fitted to trade outcomes. |
| Max hold | 120 days | same | Measured median winning hold here (110 days) is close enough to C-trend's own 118 that changing it would be tuning to a coincidence, not a real difference. |
| Max positions / size | 5 @ 18% | **6 @ 15%** | Twelve-name universe (vs. 9) supports one more concurrent slot without materially concentrating the book; 6×15%=90% deployed, same margin of unused cash as C-trend's 5×18%=90%. |
| Universe size | 9 | 12 (the round's cap) | Wider sector spread needs more names to represent six sectors without over-weighting any one. |

Every number above traces to either "held constant to isolate the variable under test" or a specific
measured figure (volatility ratio, observed hold time) -- no parameter was chosen by looking at how it
would have performed over the trading window, which I have not seen.

## 5. What would falsify this

- If, over the actual 2026-02-17 to 2026-08-18 window, the strategy's win rate and win/loss ratio come
  in *at or below* the noise floor implied by 459 historical trades (i.e., indistinguishable from a
  coin flip with small, symmetric wins and losses), that falsifies "the mechanism travels, just
  weaker" -- it would mean the mechanism does not travel at all and C-trend's edge really is
  AI-earnings-cascade-specific.
- If the entry fails to open a position at all in more than 2-3 of the 8 regime windows, that would
  mean the regime filter is too conservative for this book despite the 2004-2026 measurement above,
  and the "eligible in all 8 windows" claim in Section 3 would be wrong.
- If median excess is negative in every single window including the defensive-favoring ones (bear
  markets), that would mean this isn't "trend, but slower" -- it would mean the book is simply a
  low-beta drag with no trend signal doing any work at all, i.e., the entry/exit timing adds nothing
  over passively holding the same twelve names.

## 6. Predictions (scored)

**Worst window on excess: `bull-2024`.** This is the beta warning made concrete. 2024 was a
narrow, cap-weighted, AI/growth-driven rally; a low-beta, ex-AI defensive book will very likely make
money in absolute terms while trailing SPY by a wide margin on excess, because SPY's return in that
window is disproportionately carried by the exact complex this card was built to exclude. I expect
this to be the single worst excess window, and expect it to be a real loss on excess, not a rounding
error.

**Best window on excess: `bear-2022`.** 2022 was a genuine broad equity bear market (rate-driven, not
AI-specific), and a defensive, lower-beta, ex-growth book should decline less than SPY while trend
exits (the `ema(20) crosses_below ema(50)` rule) get the book out of decaying positions rather than
holding through the full drawdown. I expect this to be the strongest excess window, ahead of `gfc`
(where I still expect defensive names to fall, just less than the index, given financial-sector
exposure via JPM during a banking crisis is a genuine headwind inside this specific book).
