# c02-volatility — Squeeze-Break Gamma Unwind

Rank: **16th of 18** on the common four-window ranking. Ranked and eligible in all five windows.

## 1. What the card was

The card buys the session after a close crosses above the 20-day, 2-standard-deviation Bollinger
upper band while 14-day ATR is still below 50-day ATR — a volatility-squeeze breakout across six of
the most liquid, most heavily-optioned index and sector ETFs (`SPY QQQ DIA IWM XLF XLE`). The thesis
mechanism is dealer and options-writer gamma hedging: range compression accompanies net-short-gamma
positioning from covered-call and options-income sellers, and a breakout that arrives while realised
volatility is still compressed catches that flow before it has repriced, so short-call writers being
tested have to buy into the move and mechanically extend it for a period afterward.

## 2. Results across all five windows

All figures use the corrected metrics from `DEFECTS.md`: `corrected_return = ending_equity /
starting_equity − 1`, `capital_exposure = Σ(quantity × entry_price × bars_held) / (sessions ×
starting_equity)`, `adjusted_excess = corrected_return − capital_exposure × benchmark_return`.
`session_exposure` is the runner's raw (defective) exposure figure, shown for comparison.

| window | trades | corrected return | benchmark | excess | adjusted excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gfc | 10 | −20.78% | −56.23% | +35.44% | **−11.89%** | 15.82% | 33.43% | −21.18% | 10.00% |
| covid | 4 | +2.05% | −8.71% | +10.76% | **+4.44%** | 27.38% | 38.71% | −7.98% | n/a — all 4 trades still open at window end |
| bear-2022 | 4 | −6.71% | −25.14% | +18.43% | **−0.57%** | 24.45% | 30.61% | −15.36% | 0.00% |
| bull-2024 | 9 | +1.13% | +14.00% | −12.87% | **−4.41%** | 39.59% | 55.60% | −6.39% | 40.00% |
| recent | 12 | +10.47% | +20.62% | −10.15% | **−1.27%** | 56.94% | 79.52% | −4.66% | 44.44% |

Median adjusted excess **−1.27%** (recent), worst **−11.89%** (gfc), best **+4.44%** (covid), IQR
**3.84 points**, hit rate 1 of 5 windows positive. `bull-2024` and `recent` overlap the design window
(BRIEF.md §4); the card is negative in one of the two overlapping windows and only marginal in the
other.

## 3. The pre-registered failure regime versus what happened

The memo's call, verbatim, had two parts. First: **"I expect `bear-2022` to be the window I do worst
in, precisely because it is the regime this rule is least built for: a slow bleed rather than a
compression/release."** Second, on COVID specifically: **"I also expect a full crash (COVID's opening
days) to be missed on the way down by construction... the squeeze filter correctly refuses the entry
and the strategy does not attempt to catch the initial plunge. It should be positioned to catch the
post-crash breakout recovery instead, if one occurs inside a squeeze."**

**The primary call was wrong; the secondary call was right.** `bear-2022` was not the worst window —
it finished at −0.57% adjusted excess, close to flat and consistent with the memo's own fallback
description ("it will score fine on `adjusted_excess` if exposure is low"). The actual worst window
by a wide margin is `gfc` (−11.89%), a window the memo did not name as its expected weak point. The
`gfc` trade log shows why: this is not "few or no setups," it is ten trades spread across Oct 2007
through Feb 2009 — repeated squeeze-breakout entries through a multi-leg decline, most of them
stopped out. Eight of ten trades exit on `stop`, only one is a clean winner (XLE, time exit, +0.36%).
This is a different failure mode than the one pre-registered: not "sits in cash and does nothing
distinctive," but "keeps finding technically valid squeeze setups inside a bear market and keeps
losing on them."

The secondary, COVID-specific call held up well. All four `covid` trades enter in May 2020 — QQQ,
DIA, SPY and XLF, all after the crash — exactly the "missed the plunge by construction, positioned
for the post-crash breakout" mechanism described in the memo. `covid` is in fact the card's best
window (+4.44% adjusted excess), carried by a single QQQ trade entered 2020-05-11 that was still open
and up +10.73% at the window's end.

## 4. Trade-level detail

**Exit-reason distribution per window:**

| window | rule | stop | target | time | open_at_end |
|---|---:|---:|---:|---:|---:|
| gfc | — | 8 | — | 2 | — |
| covid | — | — | — | — | 4 |
| bear-2022 | — | 3 | — | — | 1 |
| bull-2024 | — | 1 | — | 4 | 4 |
| recent | — | — | 1 | 8 | 3 |

There is no `rule` exit anywhere for this card — by design, `exit` is empty and every position closes
on the stop, the target, the time cap, or still-open at window end.

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| gfc | XLE, 2008-04-17→2008-07-14, time, +0.36% | XLF, 2008-09-09→2008-09-16, stop, **−18.22%** |
| covid | QQQ, 2020-05-11→open at end, +10.73% | XLF, 2020-05-28→open at end, −4.93% |
| bear-2022 | XLF, 2022-07-20→open at end, −6.97% (best of four, all losses) | DIA, 2022-07-20→2022-09-27, stop, −7.47% |
| bull-2024 | QQQ, 2025-06-11→open at end, +5.60% | QQQ, 2025-02-18→2025-03-05, stop, −8.16% |
| recent | XLE, 2026-01-06→2026-03-03, target, +21.99% | DIA, 2026-01-06→2026-04-02, time, −6.06% |

**Stop-outs against the nominal 8% stop.** Every stopped trade, realised loss vs. `stop_loss_pct =
0.08`:

| window | symbol | entry → exit | realised loss | gap vs. 8% nominal |
|---|---|---|---:|---:|
| gfc | XLE | 2007-10-16 → 2007-11-13 | −8.13% | +0.13pp |
| gfc | XLE | 2007-12-27 → 2008-01-16 | −8.91% | +0.91pp |
| gfc | IWM | 2008-05-14 → 2008-07-03 | −9.26% | +1.26pp |
| gfc | XLF | 2008-09-09 → 2008-09-16 | **−18.22%** | **+10.22pp** |
| gfc | SPY | 2009-01-05 → 2009-01-15 | −9.28% | +1.28pp |
| gfc | DIA | 2009-01-05 → 2009-01-15 | −8.77% | +0.77pp |
| gfc | QQQ | 2009-01-05 → 2009-01-21 | −7.88% | −0.12pp |
| gfc | QQQ | 2009-02-09 → 2009-02-20 | −9.40% | +1.40pp |
| bear-2022 | QQQ | 2022-07-20 → 2022-09-27 | −7.10% | −0.90pp |
| bear-2022 | DIA | 2022-07-20 → 2022-09-27 | −7.47% | −0.53pp |
| bear-2022 | IWM | 2022-07-20 → 2022-09-27 | −7.00% | −1.00pp |
| bull-2024 | QQQ | 2025-02-18 → 2025-03-05 | −8.16% | +0.16pp |

**The largest stop-slippage gap found in either card is this one.** XLF, entered 2008-09-09, held one
week, exited 2008-09-16 — the week of the Lehman Brothers failure (2008-09-15). Realised loss
**−18.22%** against an 8% nominal stop: the stop was checked against the previous close, which was
already gapping down session over session, and by the time the rule fired the position had lost more
than double its nominal risk unit in a single week. This is the same shape of event the brief's own
worked example describes (a 19.9% loss against a 12% stop) and confirms it at a comparable magnitude
against a tighter stop.

## 5. Did it trade enough to be judged, and did it defend or abstain?

39 trades across five windows, but only 4 in `covid` and 4 in `bear-2022` — thin enough that a single
trade materially moves the window's result. In `covid`, one QQQ trade (+10.73%, still open) is most of
the window's positive excess; in `bear-2022`, three of the four trades entered on the same day
(2022-07-20) and were stopped together, which is one correlated bet dressed as three, not three
independent signals.

Capital exposure is meaningfully higher than a purely defensive posture: 15.8% in `gfc` rising to
39.6% and 56.9% in the two most recent windows, driven by the 60-day hold and 25%-per-slot sizing.
This card **traded, and lost, rather than abstained** — it is not sitting in cash waiting for a
squeeze; it takes the signal when the rule fires and rides it through the stop, the target, or the
time cap. The `gfc` result in particular is a real defeat, not a non-event: eight of ten trades
stopped out, exposure over 15%, and a −21.18% max drawdown, the worst of any window for this card.

## 6. Verdict

The card ranks 16th of 18 on a negative median (−1.27% adjusted excess), and its own pre-registered
worst-case window was wrong about *which* window would hurt most — `bear-2022` came in close to flat,
while `gfc` produced the round's clearest stop-slippage failure (XLF, −18.22% against an 8% stop,
Lehman week) and the card's only genuinely bad quarter. The COVID-specific half of the pre-
registration — missing the crash by construction, catching the recovery instead — held up and
produced the card's best window. That is a real, if partial, vindication of the mechanism's logic:
the squeeze filter behaves as designed around a shock, but the card was not built for, and did not
anticipate, a grinding multi-leg decline that keeps producing technically valid squeeze setups that
fail one after another. Cross-window spread is tighter than the poor median suggests — IQR of 3.84
points against a field where incumbents range 12–47 points — so this is a consistently mediocre-to-
poor card rather than a volatile one, but consistency in the wrong direction does not offset the
negative median.

**Not recommended for promotion to the library as submitted.** The mechanism (dealer/writer gamma
hedging around a compressed range) is well-argued and the memo's own weakest-assumption section
correctly flags that `atr(14) < atr(50)` is a price-only proxy with no link to actual dealer
positioning — this round's `gfc` result is consistent with that proxy failing exactly where it
matters most, misreading a bear-market rally's temporary compression as a genuine squeeze release.

**Single change most worth testing as a variant:** a regime filter that suppresses entries when the
broader trend is down (e.g., requiring `close > sma(200)` on the traded symbol itself, the same
convention c01 uses), rather than relying on the ATR-compression proxy alone to distinguish a real
volatility-release breakout from a bear-market whipsaw. The `gfc` trade log shows the squeeze
condition firing repeatedly through a declining trend and getting stopped out nearly every time;
a trend filter is the more testable next step than tightening the stop, since the brief's own
evidence (and the XLF trade here) argues against a tighter stop, not for one.
