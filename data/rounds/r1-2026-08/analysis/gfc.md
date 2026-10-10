# GFC window analysis — round 1, `gfc` (2007-10-09 → 2009-03-09, 356 sessions)

SPY fell **−56.23%** price-only over the window (first open to last close), by my own independent
calculation. The runner's own `benchmark_return` field, present in all five result files, is
`-0.5622750642673521850899742931`, i.e. **−56.2275%**, which rounds to the same −56.23%. No
discrepancy — the two figures agree to the precision that matters.

Of the 22 cards fielded this round, only five could even run this window: every inherited card from
the predecessor tournament was blocked by the lookahead guard, because its universe contains a stock
that did not exist yet in 2007 (AVGO listed 2009; NOW and META 2012; INDA 2012). The whole inherited
field was built on a semiconductor/AI universe that postdates the crisis. The five cards below are
the only ones whose analysts chose universes that reach back far enough to be judged here at all —
`c01-meanrev`, `c02-volatility`, `c03-breakout`, `c04-riskmanaged`, `c05-trend`.

## Correction: the `exposure` metric was mis-specified (found and fixed during this analysis)

The first draft of this document reported c04-riskmanaged's `exposure` field (97.19%) alongside its
own memo's estimate of ~45% average blended exposure, and flagged the gap as an open question rather
than asserting which side was wrong. The round coordinator traced it into the runner source:
`runner.py:517` appends `bool(open_lots)` once per session, and `metrics.py:90` averages that boolean
series. So the `exposure` field the runner reports is **the fraction of sessions on which the card
held at least one position of any size — not the fraction of capital actually deployed.** A card with
four 25%-sized slots that keeps exactly one slot filled on almost every session reads as ~97%
"exposed," even though only ~25% of capital is ever at risk at a time. c04's author was measuring a
different quantity (a capital-weighted average across four legs) and got ~45%; both figures were
correct measurements of different things, and the mismatch flagged above was the symptom that the
runner's metric — not either analyst's arithmetic — needed fixing.

Because `adjusted_excess = total_return − exposure × benchmark_return` is defined directly on this
field, every `adjusted_excess` figure computed from the runner's `exposure` **over-credits any card
whose trades are spread thin across many sessions relative to how much capital each trade actually
commits** — a boolean-occupancy measure conflates "was any capital deployed that day" with "how much."
That shape describes c04 most (28 trades, four symbols, usually one slot filled), and to a lesser
degree c03 and c05.

The session-based figures from the original draft are kept below, labeled `session_exposure` /
`adj_excess (session)`, alongside a capital-weighted reconstruction built directly from the trade
logs: for each trade, `quantity × entry_price × bars_held`, summed across all of a card's trades and
divided by `sessions × starting_equity` (356 × $10,000.00 for every card in this window — confirmed
directly in each result file). `bars_held` is the exact number of trading sessions each trade was
open, taken straight from the trade record, so this is **not a calendar-day approximation** — it uses
the same session count the runner itself used to build `exposure`, just weighted by the dollar size of
each position instead of by a yes/no flag.

This defect is round-wide, not specific to `gfc`: any adjusted-excess figure computed the same way for
`bull-2024`, `covid`, `bear-2022`, or `recent` inherits the same inflation, in proportion to how
concentrated each window's trades were relative to session count, and should be treated as directional
rather than exact until recomputed the same way those windows' own analyses would need to.

## 1. Results table

| card | trades | total return | benchmark | excess | session_exposure | capital_exposure | adj_excess (session) | adj_excess (capital) | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| c01-meanrev | 11 | +0.835% | −56.227% | +57.062% | 16.85% | 5.64% | +10.311% | +4.005% | −4.216% | 63.64% |
| c02-volatility | 10 | −20.783% | −56.227% | +35.445% | 33.43% | 15.82% | −1.988% | **−11.889%** | −21.177% | 10.00% |
| c03-breakout | 11 | −13.896% | −56.227% | +42.332% | 48.60% | 21.68% | +13.428% | **−1.706%** | −14.290% | 9.09% |
| c04-riskmanaged | 28 | +0.803% | −56.227% | +57.031% | 97.19% | 43.83% | +55.451% | **+25.449%** | −8.812% | 19.23% |
| c05-trend | 20 | −1.152% | −56.227% | +55.076% | 46.07% | 19.16% | +24.751% | +9.621% | −6.652% | 11.11% |

`profit_factor` is `null` for all five cards in the source files — not reported here as zero, because
it isn't zero, it's absent. `notes` is an empty list for all five. `sharpe`/`sortino` for the record:
c01 +0.136/+0.062, c02 −2.122/−1.041, c03 −1.350/−0.876, c04 +0.110/+0.106, c05 −0.081/−0.058.

Every card posted a large positive `excess` — trivially true when the benchmark fell 56%, and not the
number to read. `adj_excess (capital)` — the corrected figure — is now the one to read, and it moves
two cards across zero relative to the flawed session-based version: **c03 flips from +13.43% to
−1.71%**, and **c02 drops further, from −1.99% to −11.89%**. Only c01, c04, and c05 remain positive on
capital-weighted terms, and c04's margin — while still the largest in the field — is roughly half of
what the flawed metric implied (+25.45% vs. +55.45%). c05 is the clear second (+9.62%), c01 a small
positive earned at very little capital risk (+4.01% on just 5.64% average capital committed), c03 and
c02 both net negative once weighted by actual capital rather than session occupancy.

## 2. Defended vs. abstained

The instruction to separate these is the point of this document, so here is the case-by-case read,
using capital-weighted exposure, trade count, and *when* the trades happened as the tell — not the
headline adjusted-excess number alone. This section is revised from the original draft: the
capital-weighted correction above changes the verdict for c03 and tones down the magnitude (though
not the direction) of the c04 verdict.

**c01-meanrev — mostly abstained, and correctly so; the correction reinforces this.** 5.64%
capital-weighted exposure is the lowest of the five, even lower than the already-low 16.85%
session-based figure suggested. The trade log shows why: 9 of its 11 trades cluster in Oct–Dec 2007,
when GFC's opening months still looked like an ordinary tradeable dip-and-bounce, not a crisis. One
more trade opens in Jan 2008 and the last position (XLE) is stopped out in July 2008. After that — the
entire Lehman-to-TARP collapse (Sep–Oct 2008) and the slide to the March 2009 bottom, roughly 60% of
the window by session count — the card places zero new trades. The 200-day SMA trend filter rolled
over and shut entries off, which is exactly the mechanism the memo pre-registered. The corrected
+4.01% adjusted_excess is real in the sense that the 11 trades it did take were net profitable (63.6%
win rate), but it is a small edge earned on a small sliver of capital — the story is still, predominantly,
*not being present* for the worst leg of the crash.

**c02-volatility — engaged, and lost; the correction makes this starker.** 15.82% capital-weighted
exposure, 10 trades spread across the full window (Oct 2007 through Feb 2009, including one entered
the week of the Lehman bankruptcy), 8 of 10 exits were stop-losses. This is not a no-show: it showed
up repeatedly and was wrong repeatedly (10% win rate). Under the flawed session-based metric it looked
only mildly bad (−1.99% adjusted_excess); capital-weighted, at −11.89%, it is unambiguously the
field's worst performer relative to the capital it actually put at risk. This remains the clearest
case of a card that defended nothing.

**c03-breakout — the correction reverses this verdict.** The original draft called this card
"partially defended," reasoning that its 48.6% *session* exposure against a −13.90% loss beat the
−27.3% a passive book at that exposure level would have taken. That comparison used the wrong
exposure figure. At 21.68% *capital-weighted* exposure, the same −13.90% loss compares against an
implied passive loss of about −12.2% (21.68% × −56.23%) — worse than passive, not better —
and the corrected adj_excess (capital) is **−1.71%**, not +13.43%. c03's 48.6% session-occupancy came
from a relatively small number of longer-held positions (11 trades, several held 20–60+ bars) rather
than continuous, capital-heavy participation, so the boolean metric overstated how much was actually
at stake. Restated plainly: c03 engaged, took real losses (9% win rate, a −15.45% stop against a 10%
nominal), and on the metric that reflects capital actually deployed, did not outperform its own
capital-scaled benchmark. It belongs closer to c02's "engaged and lost" bucket than to c04/c05's
"defended" bucket — a materially different read from the original draft.

**c04-riskmanaged — still clearly defended, not abstained, but by a smaller margin than first
reported.** 43.83% capital-weighted exposure — the highest of any card, and it now lines up closely
with the memo's own ~45% estimate, which the original draft could not reconcile with the runner's
97.19% figure. 28 trades, total return +0.80% against a benchmark of −56.23%, and adj_excess (capital)
of +25.45%. This is still the strongest case in the field against "low exposure produced this number":
the card carried close to half its capital in the market on the average session and still finished
flat. The two `insufficient_cash` rejections in its result file (it tried to add exposure and
occasionally couldn't) reinforce that this was an active, meaningfully-committed book, not a
bystander. The mechanism (SPY/EFA excluded once each broke its own 200dma, TLT and GLD carrying the
exposure while trending up) worked as designed — the qualitative case survives; only the size of the
number describing it changes, from spectacular to solidly good.

**c05-trend — defended, moderate scale, correction tones this down too.** 19.16% capital-weighted
exposure, 20 trades, near-flat −1.15% return, adj_excess (capital) +9.62% (down from the flawed
+24.75%). Smaller than c04 in every dimension (three legs vs. four, and its SPY leg spent most of the
window outside a position after an early exit), but the same qualitative story: real, sustained
engagement at a real if modest capital commitment, contained losses, no reliance on sitting in cash.

**Bottom line, corrected:** only c04 and c05 clear a genuinely positive capital-weighted
adjusted_excess by a real margin, and c04's margin — while still the field's best — is about half of
what the flawed session-based metric implied. c01 earned a small positive edge on a very small capital
commitment; call it a defensible but minor result, not a defense of the crash. c03 and c02 are both
net negative once weighted by actual capital risk: c03 is a genuine reversal from the original draft
(it does *not* get credit for a positive adjusted_excess any longer), and c02 remains the field's clear
worst case, now more starkly so.

## 3. Exit-reason distribution and stop slippage

| card | rule | stop | time | target | open_at_end | total |
|---|---:|---:|---:|---:|---:|---:|
| c01-meanrev | 10 | 1 | 0 | 0 | 0 | 11 |
| c02-volatility | 0 | 8 | 2 | 0 | 0 | 10 |
| c03-breakout | 9 | 2 | 0 | 0 | 0 | 11 |
| c04-riskmanaged | 26 | 0 | 0 | 0 | 2 | 28 |
| c05-trend | 18 | 0 | 0 | 0 | 2 | 20 |

Not one `target` exit fired anywhere in the field in this window — unsurprising when the benchmark
fell 56%, nobody's take-profit was in reach. More interesting: **the two trend-style cards (c04, c05)
never hit a stop at all** — every close was either the rule itself (the sma(200) cross reversing) or
the position was still open at the window's end. For those two disciplines, in this window, the
signal did the defending; the stop-loss backstop was never needed. For c01, c02, and c03 — the
shorter-horizon disciplines — the stop did real work, and where it fired it filled worse than its
nominal size, because (per the brief) stops are checked against the *previous close*, not the
intraday low:

- **c01-meanrev** (nominal `stop_loss_pct = 0.08`): one stop, XLE 2008-07-08→2008-07-24, realized
  −9.657%. Gap vs. nominal: **+1.66 points worse**.
- **c02-volatility** (nominal `0.08`): eight stops. Seven of eight realized worse than 8%: −8.13%,
  −8.91%, −9.26%, −9.28%, −8.77%, −9.40%, and one dramatic outlier at **−18.22%** (XLF, discussed in
  §5). One (QQQ, Jan 2009, −7.88%) came in slightly *inside* nominal. Average gap across the eight:
  **+1.98 points worse than nominal**, pulled hard by the XLF trade — the median gap, excluding that
  trade, is closer to 1 point.
- **c03-breakout** (nominal `0.10`): two stops. One realized inside nominal (XLE, −9.45%, i.e. 0.55
  points *better*); one realized well outside it (XLP, 2008-08-13→2008-10-08, −15.45%, **+5.45 points
  worse**).

The pattern: when the stop was tested during an orderly decline, the previous-close mechanic cost on
the order of 1–2 points. When it was tested during a genuine dislocation (Lehman week for c02's XLF
trade, the Aug–Oct 2008 TARP period for c03's XLP trade), the gap widened to 5–10+ points. The stop's
nominal size is a reasonable guide in calm markets and a poor one in the specific weeks that mattered
most in this window.

## 4. Pre-registered failure regime vs. what happened

| card | pre-registered failure regime (memo) | what happened in `gfc` | called it? |
|---|---|---|---|
| c01-meanrev | "GFC's Sep–Oct 2008 leg and COVID's Feb–Mar 2020 leg" — expected to lose to benchmark, possibly worst adjusted-excess, in `gfc` and/or `covid`. | Trend filter rolled over and shut entries off by mid-2008 exactly as predicted, but the damage before shutoff was mild: +0.835% total return, 63.6% win rate, +10.31% adjusted_excess — a mild positive result, not the loss the memo braced for. | **Half right.** The shutoff mechanism fired as described; the severity was overestimated. |
| c02-volatility | `bear-2022` explicitly named as the worst window ("a slow bleed rather than a compression/release"); for a full crash, expected the squeeze filter to "correctly refuse the entry" and sit out the initial plunge. | The filter did **not** stay out — 10 trades fired across the window, 8 stopped out, total return −20.78%, the only negative adjusted_excess (−1.99%) in the field. | **Missed.** `gfc` turned out to be the harder window, not `bear-2022`, and the filter engaged rather than refusing. |
| c03-breakout | `bear-2022`, "secondarily `gfc`" — expected entries to keep firing on staggered sector tops, get overrun once the broader decline caught up, and stop out "at −10% (worse in practice, since the stop checks the prior close)". | Total return −13.90%, 9% win rate, one stop at −15.45% against a 10% nominal stop — materially worse in practice, exactly as pre-registered. | **Called it.** |
| c04-riskmanaged | Sideways/choppy markets, and a *simultaneous* multi-asset bear (like 2022) — explicitly **not** `gfc`; the memo predicted ~45% blended exposure with equities excluded and bonds/gold carrying real, trending exposure, expecting "real positive or flat performance... not a flat line produced by inactivity." | Total return +0.80%, flat-to-positive exactly as predicted directionally. On exposure specifically: the runner's raw `exposure` field (97.19%) looked like a large miss against the memo's ~45% estimate, but that gap turned out to be a defect in the runner's metric, not in the memo — see the correction section above. The capital-weighted reconstruction gives 43.83%, essentially matching the memo's own ~45% estimate. | **Called it — directionally and quantitatively**, once measured on a comparable basis. |
| c05-trend | `covid` — fast crash-and-snapback — pre-registered as the worst window; `bear-2022` (a slow grind) expected to be defended best, on the logic that a slow decline gives the slow 200dma signal time to work before most of the damage happens. | `gfc`, at 356 sessions (~17 months), is itself a grinding decline rather than a V-shape. Result: near-flat −1.15%, zero stops fired, all exits via the rule itself — consistent with the "slow decline, slow signal has time" logic even though `gfc` wasn't the window explicitly discussed. | **Called it** (by extension of the stated logic, not by an explicit `gfc` prediction). |

**Scorecard: 3 of 5 called it, 1 partial, 1 missed.** c03, c04, and c05 each got the *shape* of the
`gfc` outcome right, even where (c04, c05) `gfc` wasn't their named failure regime — and c04's call is
now confirmed quantitatively as well as directionally, once its exposure estimate is compared against
the corrected capital-weighted figure rather than the flawed session-based one. c01 got the mechanism
right but overestimated the damage. c02 is the clean miss: it named a different window as its worst
case and `gfc` turned out to be worse than that named case, via a channel (an idiosyncratic,
crisis-specific gap in a single symbol) the memo didn't anticipate. This scorecard is about the
direction and mechanism of each memo's prediction, which the metric defect above does not touch — c03
still correctly predicted stop-outs worse than nominal, independent of how its overall adjusted_excess
nets out on either exposure basis.

## 5. The worst single trade in the window

**c02-volatility, XLF, entered 2008-09-09, exited 2008-09-16, exit reason `stop`.** Entry price
$18.06, exit price $14.77, quantity 135, P&L −$444.23, return **−18.22%** — against a nominal
`stop_loss_pct` of 8%. That is more than double the intended risk budget on this single trade, a
10.22-point gap between nominal and realized.

The dates are not a coincidence: Lehman Brothers filed for bankruptcy on 2008-09-15, inside this
exact holding window, and XLF is the financial-sector SPDR — the single instrument most directly
exposed to that event. The card entered on a squeeze-breakout signal (a bet that a volatility
compression had just released upward) in the sector about to experience the defining event of the
entire crisis, and the stop — checked against the previous close, not the intraday level — could not
protect against an overnight/intraday move of that violence. This is the sharpest illustration in the
whole window of the brief's own warning about stop mechanics: a "nominal" risk unit is a floor under
ordinary volatility, not a ceiling under a genuine crisis gap.

## 6. Honest limitations

- **Five cards is a small field.** Statements like "3 of 5 called it" describe this specific field,
  not a base rate for how often analysts correctly anticipate crisis behavior in general. A different
  five cards, even from the same designers, could easily produce a different ratio.
- **One window is one draw.** `gfc` is 356 sessions of one specific historical crisis. Every number in
  this document — the adjusted-excess rankings, the stop-slippage gaps, the exit-reason mix — is a
  single realized path through 2007–2009, not a distribution. The XLF trade in particular is one
  entry, in one symbol, in one nine-day window around one specific macro event; it is illustrative of
  a mechanism (previous-close stop checking under a crisis gap), not a statistically estimated
  frequency of how often that mechanism bites.
- **These five were not designed against 2008 — they were designed by analysts who knew a crisis
  window existed in the matrix.** That is a materially weaker claim than "these cards were built to
  survive the GFC." Every memo above cites GFC eligibility as a universe-construction constraint
  (first-bar dates, correlation checks) that the analysts satisfied by choosing older, more liquid
  instruments — not as a target they tuned entry/exit rules or stop sizes against. The pre-registration
  exercise in §4 is informative precisely because the analysts had to state, in advance and without
  running the `gfc` backtest themselves (c05's memo is explicit that it never computed a return figure
  in the design window), what they expected — but "we expected roughly this" from five people who knew
  a crisis window was coming is a different and easier task than genuinely out-of-sample crisis
  robustness.
- **The c04 exposure discrepancy is resolved, not open.** It was a defect in the runner's `exposure`
  metric (boolean session-occupancy, not capital weight) — see the correction section above. It is
  recorded here as a limitation of the *original draft*, not of this revised one.
- **The capital-weighted reconstruction has its own simplifying assumption.** `quantity × entry_price`
  is used as each trade's notional for every session it was held, rather than a daily mark-to-market
  value that would drift with price. This is a standard reading of "capital committed" (the cash laid
  out at entry, sized against `starting_equity`), but it is not identical to "current market value of
  the open position," which would run higher on winning trades and lower on losing ones as they age.
  The gap between the two is small for short-dated trades and largest for the longest holds in the
  window (e.g. c04's TLT position held 145 bars, or the two `open_at_end` positions held 83 and 32
  bars) — a caveat worth naming even though it does not change the qualitative rankings above.
