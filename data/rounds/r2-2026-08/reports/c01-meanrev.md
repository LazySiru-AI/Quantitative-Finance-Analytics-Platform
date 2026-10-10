# c01-meanrev — round 2 report: benchmark comparison and trade attribution

## 1. What the card is

`c01-meanrev` buys a close below the 20-day, 2-stdev Bollinger lower band while price still sits
above its own 200-day SMA — a bet that the dip is forced, price-insensitive selling (stop-loss
cascades, vol-target de-risking, redemption flow) inside an intact uptrend, not a repricing. It
exits at the 20-day middle band, or on an 8% stop, or after a 20-day hold. Ten-symbol universe
(`SPY QQQ IWM XLF XLE XLI XLK XLV EEM DIA`), 6 slots, 15% per position — 9 of 10 parameters spent.
Pre-registered failure regime: *"a fast, deep, sustained decline where the 200-day SMA... has not
yet turned down before the crash accelerates"* — GFC's Sep–Oct 2008 leg and COVID's Feb–Mar 2020 leg
named explicitly as candidates.

## 2. Versus SPY, all eight windows

| window | sessions | card | SPY | excess | adj. excess | capital exposure | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `q4-2018` | 65 | −3.70% | −20.05% | **+16.35%** | +0.46% | 20.8% | −5.44% |
| `covid` | 93 | −7.21% | −8.71% | **+1.50%** | −6.44% | 8.8% | −8.27% |
| `bear-2022` | 196 | −0.60% | −25.14% | **+24.54%** | +0.95% | 6.2% | −3.11% |
| `chop-2015` | 260 | −2.19% | −0.04% | **−2.15%** | −2.19% | 9.9% | −4.85% |
| `chop-2011` | 260 | −5.17% | −0.05% | **−5.13%** | −5.17% | 16.3% | −7.30% |
| `bull-2024` | 250 | +2.22% | +14.00% | **−11.78%** | +0.30% | 13.7% | −3.99% |
| `recent` | 249 | +8.92% | +20.62% | **−11.70%** | +5.52% | 16.5% | −5.05% |
| `gfc` | 356 | +0.83% | −56.23% | **+57.06%** | +4.00% | 5.6% | −4.22% |

Raw excess is dominated by capital exposure: the card "beats SPY" by 16–57 points in every falling
window simply by holding under 21% of the book while the benchmark holds 100%. Adjusted excess —
return against a passive position of the card's *own* size — is a much smaller, mixed number: positive
in five of eight windows, negative in `covid`, `chop-2015`, `chop-2011`. **Mean exposure across the
common six-window set is 12.6%, against a field median of 34.1% — more than 2× below it, so the
scorer's `incommensurable_exposure` flag is set.** Its adjusted-excess figures are correct statements
about a book this size and are not on the same scale as a 40%-exposure card's; see §6.

## 3. What moved the number

Only trades moving at least 1% of the book are itemised below (`tools/attribution.py`'s
`MATERIAL_CONTRIBUTION` threshold); smaller trades are captured in the concentration and total-return
figures.

**`q4-2018`** — 6 trades, −3.70% against −20.05%.
| symbol | entry | exit | bars | exit reason | trade return | P&L | share |
|---|---|---|---|---|---|---|---|
| QQQ | 2018-10-08 | 2018-10-30 | 16 | stop | −9.43% | −136 | −1.36% |
| XLK | 2018-10-09 | 2018-10-30 | 15 | stop | −8.19% | −122 | −1.22% |
| IWM | 2018-09-27 | 2018-10-12 | 11 | stop | −7.70% | −104 | −1.04% |

Three of six trades were stopped out inside the October 2018 selloff, for a combined −3.62 points —
essentially the whole card return. The card was small and short-lived here, not defensive.

**`chop-2015`** — 15 trades, −2.19% against −0.04%. IWM stopped-out on a time exit (−9.68%, −1.41%)
and QQQ on a hard stop (−7.21%, −1.03%) account for the bulk of the loss; SPY's own +0.04% benchmark
means there is effectively no passive return to beat, so this window is a near-direct read of the
rule's cost.

**`chop-2011`** — 30 trades, −5.17% against −0.05%, the card's single worst window. Five trades stop
out in the first two weeks of August 2011 (the US debt-ceiling downgrade selloff): DIA −9.52%
(−1.38%), QQQ −8.96% (−1.31%), XLF −8.55% (−1.29%), IWM −8.15% (−1.17%), XLV −7.40% (−1.09%) — five
stops totalling −6.24 points against a card return of −5.17%, meaning the rest of the book's 25 other
trades netted slightly positive. **−0.59%** of the return sits in a position still open at the
window's close — a mark, not money taken, though small next to the loss.

**`covid`** — 7 trades, −7.21% against −8.71% (adjusted excess −6.44%, the card's worst on that
measure). Five stops fire in the last week of February and first two of March 2020 — DIA −10.88%
(−1.53%), XLV −9.25% (−1.36%), XLF −8.05% (−1.21%), SPY −9.50% (−1.19%), XLK −7.60% (−1.13%) —
together −6.42 points, almost the entire card return. **This is the memo's own pre-registered failure
mechanism firing exactly as described**: the band kept signalling "dip" through the fastest opening
leg of the crash, each entry got stopped, and the SMA(200) filter only shut new entries off once the
trend had already broken.

**`bear-2022`** — 8 trades, −0.60% against −25.14%. One XLE round-trip (+7.67% then a −6.99% stop)
essentially nets to flat; the rest of the book barely traded.

**`bull-2024`** — 22 trades, +2.22% against +14.00%. A single XLE stop (−8.34%, −1.24%) is the only
material line; the other 21 trades are individually below the 1% threshold and net to a small gain.

**`recent`** — 36 trades, +8.92% against +20.62%. XLK (+9.37%, rule exit, +1.28%) and XLE (+6.77%,
rule exit, +1.02%) are the two material winners; without its three largest winners the card still
returns +5.80% (see concentration below), so this window's gain is broad-based, not concentrated.

**`gfc`** — 11 trades, +0.83% against −56.23%. Only one trade clears the material threshold, an XLE
stop (−9.66%, −1.43%); the rest of the return is scattered across the other ten small trades. All 11
trades occurred between 2007-10-22 and 2008-07-24 — every single one before the Lehman collapse. The
book took no positions at all for the remaining roughly nine months of the 356-session window,
including the entire Sep 2008–Mar 2009 leg the memo named as its expected failure case.

## 4. Concentration

| window | top-3 share of gross winning P&L | return without top 3 |
|---|---:|---:|
| `q4-2018` | 100% | −3.72% |
| `covid` | 100% | −7.37% |
| `bear-2022` | 100% | −2.01% |
| `chop-2015` | 59% | −3.24% |
| `chop-2011` | 38% | −6.78% |
| `bull-2024` | 38% | +0.38% |
| `recent` | 28% | +5.80% |
| `gfc` | 59% | −0.61% |

In the three windows where the card lost to its own passive size (`covid`, `chop-2015`, `chop-2011`),
removing the top three winners still leaves a loss no shallower than the reported one — the winners
are cushioning a rule that was net-losing underneath them, not driving an otherwise-flat book. `gfc`'s
positive result also does not survive removing its handful of winners: without the top three, the
window would have returned −0.61%. The reported +0.83% gfc gain is a thin, few-trade artifact of when
the ten-symbol book happened to be active, not a broad-based defence.

## 5. Realised versus marked

Unrealised marks are small throughout and never material to the headline sign: `chop-2011` −0.59%,
`covid` +0.15% of return sits in a position open at the window's close; every other window's return is
fully realised. Nothing here rests on a favourable close-of-window snapshot.

## 6. Defending versus absent, in the crisis windows

**`gfc`: absent, not defending.** The trade log shows the last position closing 2008-07-24. The card
took zero further trades through the actual collapse — Lehman (Sep 2008), the trough (Mar 2009) — not
because a risk rule recognised danger and stepped aside, but because the entry condition
(`close < bb_lower and close > sma(200)`) requires price to still be *above* its own 200-day average,
and by autumn 2008 SPY and its peers had fallen well below theirs. The gate that let the strategy in
during the earlier, gentler leg of the decline is the same gate that shut it out of the worst of it.
The +0.83% return and +4.00% adjusted excess are a small, largely coincidental residue of ten trades
taken before the real crash, at 5.6% exposure — the lowest of any window this card ran. This is the
`incommensurable_exposure` flag in concrete form: a passive position of 5.6% of this book could not
have lost much either, so beating it by four points is a low bar, not evidence of a hedge.

**`covid`: the pre-registered failure, confirmed.** Here the card was in the market (7 trades, 8.8%
exposure) when the crash hit, kept re-entering on "dips" that were the first leg of a much larger
decline, and was stopped out repeatedly — the exact mechanism the memo described before any of this
ran. Adjusted excess of −6.44% is the card's worst result of the eight windows.

## 7. The new evidence, and what it changes

`gfc` was already run for this card in round 1 — the trade log here is byte-identical (same 11
trades, same dates, same P&L) to `r1-2026-08/results/gfc/runs/r1-c01-meanrev.json`. `covid`,
`bear-2022`, `bull-2024` and `recent` are likewise unchanged recomputations of round 1's own numbers.
**The only windows genuinely new to this card are `q4-2018`, `chop-2015` and `chop-2011`.** Their
adjusted excess is +0.46%, −2.19% and −5.17% respectively — median **−2.19%, negative**, and `chop-2011`
is the card's single worst window of the eight. On the only evidence this round actually added, the
card did not clear the bar.

## 8. Verdict

`c01-meanrev` is already sitting in `library/candidates/`, promoted on round 1's result and
explicitly *held* there rather than advanced to `base/`, because that promotion rested on evidence
that (per `REPORT.md` §1) largely overlaps this round's re-run. The three genuinely new windows this
round contributes post a negative median, and the card's own exposure (12.6% mean, flagged
`incommensurable_exposure` against the field's 34.1%) means its positive-looking `gfc` and
`bear-2022` numbers describe a much smaller passive comparison than the rest of the field's. Its
crisis-window strength is largely an artefact of trading before the crisis rather than through it
(§6), which is the opposite of what a defensive claim would need to show.

**Recommendation: hold as `candidates/`, promote no further.** Nothing in this round's new-window
evidence supports advancing it to `base/`, and nothing in it justifies demoting it back to
challenger either — nothing here is evidence of a repeatable edge (the `chop` windows are negative)
or evidence the round-1 promotion was wrong (it wasn't re-tested on comparable ground). Per
`PROTOCOL.md` §6 as amended, a promotion decision requires a positive median on windows the *previous*
round did not use; this round's new windows for this card do not clear that bar, so status quo is the
correct call, not a fresh promotion.
