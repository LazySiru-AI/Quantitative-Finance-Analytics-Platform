# Window analysis — `covid` (2020-02-19 → 2020-06-30, 93 sessions)

Benchmark (SPY, price-only, first open to last close): **−8.7125%** (given figure −8.71%; every
runner's own `benchmark_return` reads −0.08712513691938778… — same figure to the digit shown, no
discrepancy). 18 cards ran in this window: 12 incumbents, 5 challengers, and `c06-13f-momentum`,
unranked by construction and reported separately below.

The defining fact about this window: SPY fell roughly 34% peak-to-trough between 2020-02-19 and
2020-03-23, then recovered almost all of it by 2020-06-30, landing the whole-window number at only
−8.71%. A card can therefore post a benchmark-beating number two different ways — genuinely trading
both the crash and the snapback, or simply never being invested — and those two outcomes look similar
on `total_return` alone. Nulls are reported as `n/a`, never as 0.

## A note on `exposure`, corrected mid-task

The `exposure` field in the run JSON (`runner.py:517` / `metrics.py:90`) is **the fraction of
sessions on which the card held at least one open lot, not the fraction of capital deployed.** A
4-slot card holding one small slot every session reports `exposure = 1.0` while only a quarter of
its capital was ever at risk. `adjusted_excess = total_return − exposure × benchmark_return` therefore
**over-credits multi-slot, low-fill cards** in a falling-benchmark window — the more sessions a card
merely "touches" the market, the more benchmark credit the formula hands it, independent of how much
money was actually exposed.

To answer "how much was at risk," this analysis reconstructs a **capital-weighted exposure** directly
from the trade logs: for each session in the window, sum `quantity × entry_price` over every position
open that session (`entry_date` through `exit_date` inclusive, or through window-end for
`open_at_end`), divide by `starting_equity` (10000.00 for every card), and average across all 93
sessions (business days minus 2020-04-10 and 2020-05-25, cross-checked against the reported session
count). Both figures are reported below — `session_exp` (the raw JSON field, treated as an **upper
bound**) and `capital_exp` (the reconstructed figure, used for the defended-vs-abstained verdict).
Where the two diverge by more than 20 points, that is flagged explicitly — it is the most misleading
part of the raw data.

## 1. Full results table

Sorted by `total_return`. `adj(sess)` uses the raw JSON `exposure` (upper bound); `adj(cap)` uses the
reconstructed capital-weighted exposure and is the figure this analysis treats as real.
`win_rate` is `n/a` where the card had zero *closed* trades — the metric is undefined there, not zero.

| card | group | trades | return | benchmark | excess | session_exp | capital_exp | adj(sess) | adj(cap) | max DD | win rate |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| B-momentum | incumbent | 6 | +22.93% | −8.71% | +31.64% | 69.89% | 54.72% | +29.02% | +27.70% | −4.58% | n/a |
| B2-hold-90 | incumbent | 6 | +22.93% | −8.71% | +31.64% | 69.89% | 54.72% | +29.02% | +27.70% | −4.58% | n/a |
| B4-tight-stop | incumbent | 6 | +22.93% | −8.71% | +31.64% | 69.89% | 54.72% | +29.02% | +27.70% | −4.58% | n/a |
| B3-concentrated | incumbent | 4 | +21.85% | −8.71% | +30.56% | 69.89% | 56.42% | +27.94% | +26.76% | −6.03% | n/a |
| B1-with-target | incumbent | 8 | +19.51% | −8.71% | +28.22% | 69.89% | 43.48% | +25.59% | +23.29% | −4.58% | 100.00% |
| c06-13f-momentum | **unranked** | 21 | +18.97% | −8.71% | +27.68% | 79.57% | 59.13% | +25.90% | +24.12% | −7.06% | 29.41% |
| C-trend | incumbent | 7 | +15.83% | −8.71% | +24.55% | 69.89% | 44.94% | +21.92% | +19.75% | −4.88% | 50.00% |
| H-trend-diversified | incumbent | 3 | +10.24% | −8.71% | +18.95% | 63.44% | 22.87% | +15.77% | +12.23% | −3.23% | n/a |
| A2-cash-headroom | incumbent | 16 | +4.36% | −8.71% | +13.07% | 74.19% | 55.51% | +10.82% | +9.19% | −16.20% | 33.33% |
| c05-trend | challenger | 6 | +2.51% | −8.71% | +11.22% | 76.34% | 34.18% | +9.16% | +5.49% | −2.80% | 50.00% |
| c02-volatility | challenger | 4 | +2.05% | −8.71% | +10.76% | 38.71% | 28.43% | +5.42% | +4.53% | −7.98% | n/a |
| A-rotation | incumbent | 13 | −0.65% | −8.71% | +8.06% | 73.12% | 54.56% | +5.72% | +4.10% | −17.85% | 30.00% |
| A1-alpha-order | incumbent | 12 | −0.97% | −8.71% | +7.74% | 74.19% | 53.77% | +5.49% | +3.71% | −18.07% | 22.22% |
| c04-riskmanaged | challenger | 10 | −1.50% | −8.71% | +7.21% | 100.00% | 60.36% | +7.21% | +3.76% | −8.01% | 28.57% |
| A4-tight-stop | incumbent | 13 | −2.17% | −8.71% | +6.54% | 73.12% | 54.24% | +4.20% | +2.56% | −19.37% | 30.00% |
| A3-no-target | incumbent | 10 | −3.46% | −8.71% | +5.25% | 73.12% | 45.44% | +2.91% | +0.50% | −17.85% | 12.50% |
| c03-breakout | challenger | 7 | −5.76% | −8.71% | +2.96% | 23.66% | 14.74% | −3.70% | −4.47% | −8.17% | 0.00% |
| c01-meanrev | challenger | 7 | −7.21% | −8.71% | +1.50% | 27.96% | 9.72% | −4.78% | −6.37% | −8.27% | 0.00% |

`sharpe`, `sortino`, `volatility` and `profit_factor` are `None` for every card in this window's run
files — not reported, not assumed zero.

**Divergences over 20 points** (session_exp vs capital_exp): c05-trend (76.34% → 34.18%, 42.2pp),
H-trend-diversified (63.44% → 22.87%, 40.6pp), c04-riskmanaged (100.00% → 60.36%, 39.6pp), C-trend
(69.89% → 44.94%, 25.0pp), B1-with-target (69.89% → 43.48%, 26.4pp), A3-no-target (73.12% → 45.44%,
27.7pp), A1-alpha-order (74.19% → 53.77%, 20.4pp), c06-13f-momentum (79.57% → 59.13%, 20.4pp). In
every one of these the capital genuinely at risk was smaller — sometimes much smaller — than "always
had a position on" implies; c04-riskmanaged's headline "100% exposure" in particular describes a
single continuously-held TLT lot, not a fully-deployed book.

## 2. Incumbents vs. challengers

| group | n | mean return | median return | mean capital_exp | mean session_exp | mean adj(cap) | mean trades |
|---|--:|--:|--:|--:|--:|--:|--:|
| incumbents (12) | 12 | +11.11% | +13.04% | 49.61% | 70.88% | +15.43% | 8.7 |
| challengers (5) | 5 | −1.98% | −1.50% | 29.49% | 53.33% | +0.59% | 6.8 |

Incumbents dominate this table on both the raw and the capital-weighted view, and the caveat has to
sit right next to that sentence: this is not a fair fight. The incumbents' universes are
semiconductor/AI-cycle names (NVDA, AMD, TSM, AVGO, SOXX…) that happened to lead the 2020 snapback
harder than the market as a whole — MRVL +30%, NVDA +26% to +37%, AMZN +30–36% on individual trades.
The challengers were built against a broader, more defensive design brief (ETF sleeves, mean-reversion,
volatility-gated entries) and several of them (c01, c03) are the cards that most visibly missed the
recovery — see §5. The incumbents' edge here is largely "their universe was the thing that snapped
back hardest," not evidence their rules generalize better; the challengers' shortfall is largely
"several of them structurally could not re-enter fast enough," which is exactly the failure mode this
window is designed to expose. Neither result should be read as "the incumbents are better designed"
or "the challengers failed" — one window, one draw, and the groups were not optimized for the same
target. Under the capital-weighted view the challenger group's edge nearly vanishes (+0.59% mean,
against a background where several individual challenger cards are close to zero once you strip out
the mechanical exposure credit — see §6), which sharpens rather than reverses this caveat.

## 3. Do the A/B variants separate from their bases?

Each variant isolates one change. Per the brief, treat any gap under **~20 percentage points of
return** as noise (a prior universe-ordering study moved one identical card's return by 53.9 points,
σ = 21.2, from reordering alone — nothing else). This section is unaffected by the exposure
correction, since it compares `total_return` directly.

| base → variant | change isolated | base return | variant return | Δ (pp) | clears 20pp? |
|---|---|--:|--:|--:|--:|
| A-rotation → A1-alpha-order | universe reorder only (control) | −0.65% | −0.97% | −0.32 | no |
| A-rotation → A2-cash-headroom | 4 slots @ 22% vs 3 @ 30% | −0.65% | +4.36% | +5.01 | no |
| A-rotation → A3-no-target | remove 20% take-profit | −0.65% | −3.46% | −2.81 | no |
| A-rotation → A4-tight-stop | stop 12% → 8% | −0.65% | −2.17% | −1.52 | no |
| B-momentum → B1-with-target | add 25% take-profit | +22.93% | +19.51% | −3.42 | no |
| B-momentum → B2-hold-90 | max hold 180d → 90d | +22.93% | +22.93% | 0.00 | no |
| B-momentum → B3-concentrated | 4 slots @ 22% vs 6 @ 15% | +22.93% | +21.85% | −1.08 | no |
| B-momentum → B4-tight-stop | stop 12% → 8% | +22.93% | +22.93% | 0.00 | no |

**None of the eight variant differences clear the 20pp bar in this window.** The largest gap
(A2-cash-headroom, +5.01pp) is a quarter of the noise floor from the ordering study. B2 and B4 are
bit-for-bit identical to B-momentum in this window because neither the 90-day hold cap nor the 8%
stop ever bound on these six trades — the "variant" made zero live decisions differently. That A1
(a pure reordering control with no rule change) moves the base by −0.32pp, and A2 (an actual slot/size
change) moves it by +5.01pp, in the same window, is itself informative: reordering noise and a real
parameter change produced results of comparable magnitude, both well inside the noise band. This
window offers no evidence that any of these eight isolated changes matters.

## 4. Exit reasons and stop-fill slippage

| card | rule | stop | target | time | open_at_end |
|---|--:|--:|--:|--:|--:|
| B-momentum / B2-hold-90 / B4-tight-stop | — | — | — | — | 6 |
| B3-concentrated | — | — | — | — | 4 |
| B1-with-target | 1 | — | 4 | — | 3 |
| c06-13f-momentum | 17 | — | — | — | 4 |
| C-trend | 2 | — | — | — | 5 |
| H-trend-diversified | — | — | — | — | 3 |
| A2-cash-headroom | 8 | 2 | 2 | — | 4 |
| c05-trend | 4 | — | — | — | 2 |
| c02-volatility | — | — | — | — | 4 |
| A-rotation | 8 | 1 | 1 | — | 3 |
| A1-alpha-order | 6 | 2 | 1 | — | 3 |
| c04-riskmanaged | 7 | — | — | — | 3 |
| A4-tight-stop | 6 | 3 | 1 | — | 3 |
| A3-no-target | 7 | 1 | — | — | 2 |
| c03-breakout | 3 | 1 | — | — | 3 |
| c01-meanrev | — | 6 | — | — | 1 |

`rule` did essentially all the closing work in this window; `stop` fired on only 5 cards and never
more than 3 times each, and `time` never fired at all (no card in this window used `max_hold_days`
as its binding constraint). The window's headline number is dominated by `open_at_end` positions that
were still running the snapback when the clock ran out — meaning realised performance understates
what several cards were still capturing on 2020-06-30.

**Stop-fill slippage** (stops evaluate against the previous close, not the intraday low, so they land
worse than the nominal `stop_loss_pct`):

| card | nominal stop | n stops | avg realised | worst realised | gap (worst vs nominal) |
|---|--:|--:|--:|--:|--:|
| A2-cash-headroom | −12.0% | 2 | −12.52% | −13.13% | 1.13pp |
| A-rotation | −12.0% | 1 | −11.91% | −11.91% | −0.09pp (better than nominal) |
| A1-alpha-order | −12.0% | 2 | −12.52% | −13.13% | 1.13pp |
| A4-tight-stop | −8.0% | 3 | −11.02% | −17.00% | 9.00pp |
| A3-no-target | −12.0% | 1 | −11.91% | −11.91% | −0.09pp |
| c03-breakout | −10.0% | 1 | −10.66% | −10.66% | 0.66pp |
| c01-meanrev | −8.0% | 6 | −8.76% | −10.88% | 2.88pp |

A4-tight-stop's single worst fill (AMD, entered 2020-02-19, stopped 2020-02-24) realised **−17.00%
against an 8% nominal stop** — more than double, on the single day the crash was accelerating fastest
in the window. That is the mechanism the brief warns about (fills evaluated against the prior close,
not the low) doing real, visible damage on exactly the session it would matter most. The other cards'
gaps are smaller (roughly 1–3pp) and consistent with normal overnight-gap slippage rather than a
crash-specific event.

## 5. Did any card manage both halves — crash and snapback, in the same window?

Reading entry/exit dates against the 2020-03-23 index bottom:

- **A-rotation and its four variants** are the clearest both-halves story among ranked cards. They
  entered on day one (2020-02-19, INTC/AMD/SOXX/NVDA), took real crash losses through the last week
  of February (−6.7% to −13.1%), kept trading through the decline (more small losses on 2020-03-05 and
  2020-03-31 entries), and then rotated into the recovery from 2020-04-07 onward, banking real gains
  (NVDA +26.22% to target, MRVL +30.15% to target). Capital exposure of 45–56% across this family
  confirms this was real money at risk in both directions, not a session-count artifact. The net
  result (−3.46% to +4.36%) reflects that mix rather than a clean win.
- **c04-riskmanaged and c05-trend** also traded both halves directly: c04 took the single worst
  individual crash loss in this window (SPY, entered 2020-02-19, exited 2020-02-28, **−14.62%**), but
  held TLT the entire window (open at end, +12.91% over 92 of 93 sessions) as a running hedge, then
  re-entered SPY on 2020-03-03 (still losing, before the bottom) and again on 2020-05-28 and
  2020-06-15 for real recovery gains (+1.08%, +1.03%). Capital exposure of 60.36% (not the raw
  session figure of 100%, which reflects only "at least one lot open," but still the highest
  capital-weighted figure in the table) supports calling this a genuine both-halves trade, with the
  net result carried mostly by the hedge rather than by market timing.
- **B-momentum and its variants, C-trend, and H-trend-diversified never entered before 2020-03-30**
  (B-family) or 2020-04-07 (C-trend, H). None of them held a single position during the 2020-02-19 to
  2020-03-23 decline. This is not a risk decision — these are trend/momentum entry rules that require
  price to already be confirmed above a moving average, which mechanically cannot fire during a
  crash. They then traded the recovery hard and for real gains (NFLX +25%, NVDA +37%, AMZN +36%,
  MRVL +39%), at real capital exposure (43–57% for the B-family; a lower 22.87% for
  H-trend-diversified, whose gain was carried by a single NVDA position). Read narrowly, they
  "avoided the crash and caught the snapback" — but the avoidance was a structural side effect of the
  entry filter, not a stop-out or a defensive call, and it is worth naming as such rather than
  crediting it as foresight.
- **c01-meanrev is the case the window is built to catch.** It entered into the crash on 2020-02-25
  and 2020-02-26 (six positions), all six were stopped out between 2020-02-28 and 2020-03-13
  (−7.3% to −10.9%), and then it placed **no new trade for the next three months** — nothing between
  2020-03-13 and 2020-06-12, which is essentially the entire snapback. Capital exposure for the whole
  window is 9.72%, the lowest in the table by a wide margin, and win rate on closed trades is 0.00%.
  It ended −7.21%, only 1.5pp better than the benchmark, entirely because it was in cash for the
  recovery, not because it defended capital well.
- **c03-breakout** shows the same pattern in a milder form: three trades inside the crash decline
  itself (2020-03-03 to 2020-03-12, small losses), then flat from 2020-03-12 to 2020-06-09 — missing
  essentially the entire recovery — before re-entering only in the window's final three weeks, where
  one of the four new positions was stopped out (XLU, −10.66%). Capital exposure 14.74%, second-lowest
  in the table. It ended −5.76%.
- **c06-13f-momentum (unranked, reported separately)** is the sharpest both-halves execution in the
  whole window, ranked or not: small, quickly-cut losses through the crash via one-to-few-bar rule
  exits (many trades under −5%, cut within 1–6 bars), combined with aggressive entries within one to
  two sessions of the actual bottom — NVDA entered 2020-03-25 and held to the end of the window for
  **+49.57%**, AMZN entered 2020-03-24 for +21.16%, MSFT entered 2020-03-31 for +13.27%. Because this
  card is unranked by construction (13F-derived universe), it does not compete against the field on
  this metric, but its trade log is the closest the window produced to "controlled losses on the way
  down, aggressive and correctly-timed re-entry at the bottom" — and its 59.13% capital exposure, the
  second-highest in the field, confirms this was substantial real money, not a low-commitment lucky
  strike.

**Answer:** among ranked cards, no card demonstrates active crash-loss control *and* a deliberate,
signal-driven re-entry at the bottom the way c06 does. The closest ranked analogues split into two
different mechanisms — A-rotation's family genuinely traded through both halves and took real losses
on the way down, while the B-family/C-trend/H-trend-diversified group's "avoidance" of the crash was
a structural property of a trend-confirmation entry rule that cannot fire during a crash, not a
defensive decision. Both are worth distinguishing from c01-meanrev and c03-breakout, which took real
crash losses and then sat out the recovery entirely — the exact failure mode this window exists to
surface.

## 6. Defended vs. abstained, per card

Low exposure in a *negative*-benchmark window inflates `adjusted_excess` almost mechanically. This
window's net benchmark is only mildly negative (−8.71%), so the mechanical effect is smaller here than
in `bear-2022`, but it is still present, and the verdict below is based on **capital-weighted
exposure**, not the raw session field:

- **Defended (real capital committed in both regimes, real trades):** A-rotation, A1-alpha-order,
  A2-cash-headroom, A3-no-target, A4-tight-stop (45–56% capital exposure, 10–16 trades, real crash
  losses and real recovery gains); c04-riskmanaged (60.36% capital exposure via a continuous TLT hedge
  plus repeated SPY re-entries, 10 trades, real losses and real gains); c06-13f-momentum (unranked;
  59.13% capital exposure, 21 trades, most active card in the window).
- **Engaged only in the recovery, structurally absent from the crash (not a risk call), moderate real
  capital committed:** B-momentum, B1-with-target, B2-hold-90, B3-concentrated, B4-tight-stop
  (43–56% capital exposure), C-trend (44.94%) — all real trading, but only after the entry filter
  could first fire post-bottom. H-trend-diversified sits in the same behavioral bucket but with much
  less capital actually committed (22.87%) than its session count implies — a single NVDA/GDX/MU lot
  at a time, not a filled book.
- **Abstained (missed the recovery after early losses, low capital exposure, low trade count):**
  c01-meanrev (9.72% capital exposure — the lowest in the table — flat for 3 months through the
  entire snapback), c03-breakout (14.74% capital exposure, flat for 3 months). c02-volatility sits
  close to this bucket too: 28.43% capital exposure, but its first trade is 2020-05-11, so it missed
  the crash *and* the first two-thirds of the recovery, catching only the tail; its positive
  adjusted-excess (+4.53% capital-weighted) is modest and mostly reflects that tail, not sustained
  engagement.

## 7. Limitations

This is one draw from one historical crash-and-recovery. The specific shape of this window — a
34%-plus intraday peak-to-trough drawdown that mostly reverses inside three months — rewards any
entry rule that requires "already confirmed uptrend" almost by construction, because the recovery
itself hands that signal back quickly; a slower-recovering crash would tell a different story about
the same B-family/C-trend cards. `sharpe`, `sortino`, `volatility` and `profit_factor` are null for
every card in this run and are not reported. Several cards' headline return is carried by
`open_at_end` positions still in progress on 2020-06-30 — the reported number is a snapshot at an
arbitrary cutoff, not a realised, closed-out result. `win_rate` is undefined (`n/a`) wherever a card
had zero closed trades; it is not zero, and treating it as zero would penalize cards that happened to
still be holding winners when the window ended. Finally, the capital-weighted exposure figures in
this file are a reconstruction from trade logs against an inferred NYSE session calendar (business
days minus 2020-04-10 Good Friday and 2020-05-25 Memorial Day), cross-checked to reproduce the
reported 93-session count exactly — not a value read from the harness itself.
