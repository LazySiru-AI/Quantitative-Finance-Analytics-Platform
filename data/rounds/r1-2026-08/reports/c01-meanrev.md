# c01-meanrev — Band Reversion, Broad Market & Sector ETFs

Rank: **13th of 18** on the common four-window ranking. Ranked and eligible in all five windows.

## 1. What the card was

The card buys a close below the 20-day, 2-standard-deviation Bollinger lower band while price is
still above its own 200-day SMA, and sells back out at the middle band or a 20-day time cap,
whichever comes first — a trend-filtered mean-reversion rule across ten unleveraged broad-market and
sector ETFs (`SPY QQQ IWM XLF XLE XLI XLK XLV EEM DIA`). The thesis mechanism is that a band-touch
inside an intact uptrend is disproportionately forced, price-insensitive selling — stop-loss
cascades, vol-target de-risking, and redemption-driven basket sales — rather than a repricing, and
that the 200-day filter is a proxy for "nothing structural has changed yet."

## 2. Results across all five windows

All figures use the corrected metrics from `DEFECTS.md`: `corrected_return = ending_equity /
starting_equity − 1`, `capital_exposure = Σ(quantity × entry_price × bars_held) / (sessions ×
starting_equity)`, `adjusted_excess = corrected_return − capital_exposure × benchmark_return`.
`session_exposure` is the runner's raw (defective) exposure figure, shown for comparison.

| window | trades | corrected return | benchmark | excess | adjusted excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gfc | 11 | +0.83% | −56.23% | +57.06% | **+4.00%** | 5.64% | 16.85% | −4.22% | 63.64% |
| covid | 7 | −7.21% | −8.71% | +1.50% | **−6.46%** | 8.66% | 27.96% | −8.27% | 0.00% |
| bear-2022 | 8 | −0.60% | −25.14% | +24.54% | **+0.95%** | 6.17% | 24.49% | −3.11% | 37.50% |
| bull-2024 | 22 | +2.22% | +14.00% | −11.78% | **+0.30%** | 13.72% | 42.40% | −3.99% | 72.73% |
| recent | 36 | +8.92% | +20.62% | −11.70% | **+5.52%** | 16.49% | 44.58% | −5.05% | 80.56% |

Median adjusted excess **+0.95%** (bear-2022), worst **−6.46%** (covid), best **+5.52%** (recent),
IQR **3.71 points**, hit rate 4 of 5 windows positive. `bull-2024` and `recent` overlap the design
window (BRIEF.md §4); `gfc`, `covid` and `bear-2022` are the closer test of generalisation, and two
of those three are positive.

## 3. The pre-registered failure regime versus what happened

The memo's call, verbatim: *"a fast, deep, sustained decline where the 200-day SMA — slow by
construction — has not yet turned down before the crash accelerates. GFC's Sep–Oct 2008 leg and
COVID's Feb–Mar 2020 leg are the two candidates I expect this to hurt on... I expect this card to
lose to its benchmark, and possibly to show its worst adjusted-excess, in `gfc` and/or `covid`."**

**Half right.** `covid` is exactly as predicted, and vividly so: six of the card's seven trades in
that window are DIA, XLF, SPY, QQQ, XLK and XLV, all entered 2020-02-25/26 as the market broke down,
all six stopped out for losses ranging −7.29% to −10.88%, before a seventh trade (XLV, entered
2020-06-12) closed the window still open. That is the memo's mechanism playing out trade for trade:
the entry fired repeatedly on what turned out to be the first leg of a much larger decline, and the
20-day reversion never arrived before the stop did. `covid` is, as predicted, the card's single worst
window on adjusted excess.

`gfc` did **not** hurt the card — it is the card's second-best window (+4.00% adjusted excess). The
trade log explains why the prediction missed: nine of the eleven `gfc` trades cluster in Oct–Dec 2007
(mostly winners), one more sits in January 2008, and one stops out in July 2008 at −9.66%. After that
single July stop, **the card takes no further trades for the rest of the window** — no entries fire
during the Sep–Oct 2008 leg the memo specifically named. The 200-day SMA filter shut the strategy off
*before* that leg, not "after most of the damage," as the memo hedged it might. The result is a
corrected return of essentially flat (+0.83%) against a benchmark that fell 56%, which scores well
under `adjusted_excess` — but this is the card sitting out the regime it feared, not surviving it.
The author's own mechanism was directionally right (the filter is slow and reactive), but the timing
in this particular window worked in the card's favor rather than against it.

## 4. Trade-level detail

**Exit-reason distribution per window:**

| window | rule | stop | target | time | open_at_end |
|---|---:|---:|---:|---:|---:|
| gfc | 10 | 1 | — | — | — |
| covid | — | 6 | — | — | 1 |
| bear-2022 | 7 | 1 | — | — | — |
| bull-2024 | 20 | 1 | — | 1 | — |
| recent | 32 | — | — | 4 | — |

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| gfc | XLK, 2007-11-09→2007-12-06, rule, +4.12% | XLE, 2008-07-08→2008-07-24, stop, −9.66% |
| covid | XLV, 2020-06-12→open at end, +1.03% | DIA, 2020-02-25→2020-02-28, stop, −10.88% |
| bear-2022 | XLE, 2022-04-26→2022-05-04, rule, +7.67% | XLE, 2022-06-17→2022-06-24, stop, −6.99% |
| bull-2024 | XLK, 2024-11-01→2024-11-07, rule, +5.50% | XLE, 2024-12-05→2024-12-19, stop, −8.34% |
| recent | XLK, 2026-07-29→2026-08-05, rule, +9.37% | XLV, 2026-03-06→2026-04-06, time, −4.35% |

**Stop-outs against the nominal 8% stop.** Every stopped trade, realised loss vs. `stop_loss_pct =
0.08`, since stops evaluate against the *previous close* rather than the intraday low and therefore
fill late:

| window | symbol | entry → exit | realised loss | gap vs. 8% nominal |
|---|---|---|---:|---:|
| gfc | XLE | 2008-07-08 → 2008-07-24 | −9.66% | +1.66pp |
| covid | DIA | 2020-02-25 → 2020-02-28 | −10.88% | **+2.88pp** |
| covid | XLF | 2020-02-26 → 2020-03-02 | −8.05% | +0.05pp |
| covid | SPY | 2020-02-26 → 2020-03-10 | −9.50% | +1.50pp |
| covid | QQQ | 2020-02-26 → 2020-03-10 | −7.29% | −0.71pp |
| covid | XLK | 2020-02-26 → 2020-03-10 | −7.60% | −0.40pp |
| covid | XLV | 2020-02-26 → 2020-03-13 | −9.25% | +1.25pp |
| bear-2022 | XLE | 2022-06-17 → 2022-06-24 | −6.99% | −1.01pp |
| bull-2024 | XLE | 2024-12-05 → 2024-12-19 | −8.34% | +0.34pp |

Nine stop-outs total, five of them worse than the nominal 8%. The largest gap for this card is the
DIA trade in `covid`: entered 2020-02-25 as the crash began, held one session, stopped at a realised
**−10.88%** against an 8% nominal stop — a 2.88-point slippage from the previous-close evaluation
rule, on a one-day hold. Two of the nine (QQQ and XLK in `covid`) actually landed *inside* the
nominal stop, so the effect is not uniform, but the pattern skews adverse, consistent with the
brief's warning.

## 5. Did it trade enough to be judged, and did it defend or abstain?

84 trades across five windows (11, 7, 8, 22, 36) — the two design-overlapping windows carry more than
two-thirds of the total. In the three generalisation windows the counts are thin (7–11 trades each),
which is enough to see the mechanism operate but not enough to make the per-window win rate load-
bearing on its own.

Capital exposure never exceeds 16.5% in any window, and sits at 5.6–8.7% in the two bear windows.
This is closer to **abstention than defense**: the card is not taking positions and managing them
down through a decline, it is mostly not participating. In `covid` it did trade into the crash and
lost on nearly every position before the filter shut it off; in `gfc` it stopped trading before the
crash's worst leg arrived and was simply elsewhere. The two bear windows produce a similar flat-ish
corrected return (+0.83%, −0.60%) by two different mechanisms — one accidental avoidance, one real
loss followed by shutdown — and `adjusted_excess` cannot tell them apart, which is worth stating
plainly rather than crediting the card with a defense it did not actively execute in `gfc`.

## 6. Verdict

The card ranks 13th of 18 on a poor but not catastrophic median (+0.95% adjusted excess), with one
clearly bad window (`covid`, −6.46%) that matches its own pre-registered failure mode almost exactly,
and a decent window (`gfc`) that the memo predicted would hurt but that the card mostly sat out
instead. Cross-window spread is real and worth noting on its own terms: an IQR of 3.71 points against
a field where incumbents range 12–47 points is a genuinely tighter, more consistent result — the card
is not swinging between a great year and a disaster, it is mediocre-to-flat in nearly every regime.
That consistency does not rescue the ranking; a card that is reliably close to zero adjusted excess is
still a card that adds little.

**Not recommended for promotion to the library as submitted.** The mechanism is coherent and the
memo's own honesty about correlated symbols (ten cap-weighted slices of the same equity complex,
breaching together in a selloff rather than independently) is the right self-critique — it shows up
directly in `covid`, where six positions entered on the same two days and failed the same way. The
one clear, testable finding from this round is that the 20-day time cap and the 20-day band-touch
exit rarely coincide with a genuine reversion once a decline is underway; the stop does the exiting
instead, late, against the previous close.

**Single change most worth testing as a variant:** widen the stop, or replace it with a shorter time-
based circuit breaker (e.g., exit after 3–5 sessions if the position is down more than X%, evaluated
at the next open rather than waiting for the previous-close stop check). The `covid` cluster shows six
positions stopped out within 1–2 weeks at losses averaging worse than the nominal 8%; a rule that
exits faster on a failed reversion, rather than waiting for an 8%-against-previous-close breach, is
the more testable hypothesis than re-tuning the entry, which the sensitivity check already showed is
not perched on a knife-edge.
