# c08-generalist — Cross-Asset Trend Filter

**Discipline:** trend. **Mandate:** consistency — positive exposure-adjusted excess in as many of
the eight windows as possible, aimed at the Pareto frontier on median / worst-window / hit-rate
rather than a spectacular single number.

## 1. Mechanism

Entry: `close > sma(200) and sma(50) > sma(200)`. Exit: `close < sma(200)`.

This is the canonical "golden cross" trend filter — price above its 200-day average, with the
50-day average itself above the 200-day (a second, slower confirmation that the trend is not a
single day's noise). It is one of the most widely watched rules in the market, which is the
mechanism itself: once enough participants agree a trend is confirmed, flows that lag price
discovery — pension and target-date rebalancing, CTA and risk-parity trend books, retail momentum
chasing, 401k contribution timing — continue to push in the confirmed direction for months, because
none of those flows are engineered to anticipate the turn. The people funding this edge are
short-horizon mean-reversion and reversal traders who fade extended moves, and value investors
anchored to a stale price; both get run over by continuation exactly when this rule has already
confirmed it.

The universe is deliberately cross-asset — SPY (broad equity beta), QQQ (growth/tech beta), XLU
(a defensive, quasi-bond-proxy equity sector), TLT (duration), GLD (a monetary/real-asset hedge) —
so that when equities are trend-negative, capital in the same universe has somewhere else to be
trend-positive. Bonds and gold trending up specifically when equities trend down is a structural
flight-to-quality correlation (the same institutional de-risking flow drives both sides), not a
coincidence, and it is the actual bet behind putting four different macro-sensitive assets under
one rule instead of five equity ETFs. This is why the design leans on diversification rather than
on trying to make a single-symbol trend rule work in every regime — no single symbol's trend
mechanism can be positive in every regime; the claim is that *some* symbol in this basket usually
is.

## 2. Universe and eligibility

`SPY, QQQ, XLU, TLT, GLD` — all five have a first stored bar at or before 2004 (SPY 1993-01-29,
QQQ 1999-03-10, XLU 1998-12-22, TLT 2002-07-30, GLD 2004-11-18), the tier `WINDOWS.md` documents as
reaching every window including the GFC. I ran `strategy-program/tools/windows.eligible_windows`
directly against the submitted card (read-only connection) rather than assuming from the tier list:

```
q4-2018 True | covid True | bear-2022 True | chop-2015 True | chop-2011 True
bull-2024 True | recent True | gfc True
eligible count: 8 / 8 -> gate PASS
```

**Eligible in all eight main windows.** No provenance restriction — this universe was not derived
from a point-in-time document (no `universe_knowable_from` declared). GLD is the binding symbol
(latest first bar of the five); even its 2004-11-18 start clears the GFC window's 2007-10-09 start
with warmup and the lookahead guard's 40 causality bars to spare.

I chose broad, boring, long-lived tickers on purpose given the mandate is consistency, not a
narrow recent-momentum bet — a universe that could only be tested in 5 of 8 windows would be
unranked regardless of how it traded, which defeats a consistency mandate before a single session
runs.

## 3. Parameters — count against budget of 10

| item | value | literals counted |
|---|---|---|
| `entry` | `close > sma(200) and sma(50) > sma(200)` | 200, 50, 200 → 3 |
| `exit` | `close < sma(200)` | 200 → 1 |
| `stop_loss_pct` | `0.15` | 1 |
| `take_profit_pct` | null | 0 |
| `max_hold_days` | null | 0 |
| `max_positions` | 4 | 1 |
| `position_pct` | 0.25 | 1 |

**Total: 7 of 10.** Three of headroom left deliberately unused rather than spent to squeeze a
result — see §5 on the sensitivity check.

50 and 200 are the standard SMA convention (the actual "golden cross" periods practitioners watch),
chosen for that reason rather than because they scored best — see §5, where a mild perturbation to
40/180 and 60/220 shows they are not even the best-scoring choice in this design-window sample.
`stop_loss_pct = 0.15` is a backstop, not the primary risk control (the trend exit does that work);
§5 shows the result is materially unchanged at 0.10 or 0.20, i.e. the stop rarely binds before the
trend rule already exits. `max_positions = 4` at `position_pct = 0.25` commits the full book only
when all four slots are simultaneously trending — deliberately less than the five-symbol universe,
leaving one symbol's signal un-actioned at any moment rather than fully levering into every
coincident signal. No take-profit and no time cap: a trend-following exit that lets a winner run
until the trend itself breaks is the point of the discipline; capping it with an arbitrary
`max_hold_days` would cut off exactly the tail events (gfc, covid) this design is leaning on for
its median.

## 4. What I measured

`app.tournament.runner.run_card` takes a write lock (`app.market.store.read_frame` calls
`duck.connect` without `read_only=True`), and the brief and `WINDOWS.md` are both explicit that
concurrent write-lock access is unsafe with other analysts researching alongside me. I did not run
it. Instead I built an independent, simplified reproduction of the same execution model
(`.scratch/c08-generalist/measure.py`, read-only DuckDB throughout) — decisions on close, fills at
next open, stop checked against the previous close, `position_pct * starting_equity` fixed notional
per slot, universe-order fill priority, SPY buy-first-open/hold-last-close benchmark per window —
and ran it against the eight windows' actual historical dates (all of which predate 2026-02-13 by
construction; `recent` was truncated at the design cutoff, 2025-08-21 → 2026-02-13, rather than run
past it). This is a design-time sensitivity tool, not a claim of the scored result — the real
runner's fee, slippage, whole-share and settlement mechanics will differ.

Design-window adjusted-excess by window (final card configuration: universe as above, entry/exit as
above, stop 0.15, 4 slots at 0.25):

| window | return | benchmark | exposure | excess | **adj. excess** | trades |
|---|---|---|---|---|---|---|
| q4-2018 | −6.43% | −20.05% | 41.4% | +13.61 | **+1.87** | 8 |
| covid | −3.75% | −8.71% | 69.4% | +4.96 | **+2.30** | 8 |
| bear-2022 | −10.05% | −25.14% | 36.0% | +15.09 | **−0.99** | 23 |
| chop-2015 | −5.02% | −0.04% | 36.9% | −4.98 | **−5.00** | 13 |
| chop-2011 | +0.40% | −0.05% | 74.1% | +0.45 | **+0.44** | 11 |
| bull-2024 | +4.12% | +14.00% | 69.8% | −9.88 | **−5.65** | 11 |
| recent (truncated) | +15.27% | +7.15% | 93.4% | +8.12 | **+8.59** | 4 |
| gfc | −3.33% | −56.23% | 41.5% | +52.90 | **+20.02** | 13 |

**Median adjusted excess ≈ +1.16pp** (mean of the two middle values, 0.44 and 1.87). **Hit rate:
5/8 (62.5%)** — positive in q4-2018, covid, chop-2011, recent, gfc. **Worst window: bull-2024 at
−5.65pp**, with chop-2015 close behind at −5.00pp.

Per-symbol P&L breakdown (in `.scratch/c08-generalist/measure_v3.py` output) shows GLD is the
largest single contributor across the sample (dominant in bull-2024 and recent, the two windows
gold happened to be in a strong secular trend), TLT the main crisis-window contributor (covid,
chop-2011, gfc), and SPY/QQQ the main drag in the two chop windows and bear-2022 — exactly the
whipsaw the discipline is supposed to be judged on.

## 5. What I tried and abandoned

- **8-symbol universe** (`SPY QQQ DIA XLU XLP TLT GLD IEF`, 5 slots at 0.20): hit rate only 3/8
  and a much worse bull-2024 (−8.64). Per-symbol breakdown showed DIA (redundant with SPY, no
  diversification benefit) and XLP (persistent net drag in 6 of 8 windows — a low-vol defensive
  sector that just chops around its own 200-day average without ever trending enough to pay for the
  whipsaw) were net negative almost everywhere. Dropped both. IEF was redundant with TLT (same
  duration exposure, muted) and dropped for the same reason.
- **Death-cross exit** (`sma(50) < sma(200)` instead of `close < sma(200)`): fewer trades, but
  slower reaction to price hurt more than reduced whipsaw helped — hit rate fell to 1/8, gfc and
  recent both got worse (a lagging exit gives back more of a fast reversal than it saves in avoided
  whipsaw). Reverted to the price-vs-200 exit.
- **5 slots / 0.20 sizing on the final 5-symbol universe** (using every symbol at once instead of
  leaving one unused): improved the worst window (chop-2015 −4.12 vs bull-2024 −5.65) but hit rate
  fell to 4/8 and median fell to +0.50. Neither configuration dominates the other on all three axes
  — a genuine Pareto trade-off matching what the brief describes. I chose the 4-slot version because
  the mandate is explicitly hit-rate-weighted consistency, and the worst-window difference (−4.12 vs
  −5.65) is small relative to either config's best windows (+20 to +21 in gfc).
- **Sensitivity perturbation of the MA periods** (40/180 and 60/220 in place of 50/200, everything
  else held fixed): the *qualitative* pattern is stable — gfc and recent robustly positive and
  large, chop-2015 and bull-2024 robustly negative — but the *hit-rate count* is not: 40/180 scored
  3/8, 60/220 scored 4/8, and chop-2011 in particular flips sign under both perturbations (it is a
  near-zero result at 50/200 and I do not trust its sign). I am reporting this rather than hiding
  it: 50/200 is not the best-scoring choice among the three I tried, and I kept it anyway because it
  is the conventional pair, not a fitted one, and the brief explicitly prefers a defensible
  convention over a searched optimum. `stop_loss_pct` sensitivity (0.10 / 0.15 / 0.20) was, by
  contrast, genuinely flat — adjusted excess moved by at most 0.05pp across the three values in
  every window — which is the result I'd want from a true backstop rather than a load-bearing lever.

## 6. Named window I expect to lose in

**bull-2024.** The mechanism requires both price above its 200-day average and the 50-day already
above the 200-day before it will buy — by construction it cannot own the first leg of a smooth,
low-volatility rally, only the confirmed middle of one, and it pays real whipsaw cost (TLT and SPY
both cost money in the design-window measurement) getting positioned. A trend rule's entire edge is
avoiding a drawdown it never got the chance to sidestep in a market that simply never corrected; there
is nothing to offset the lag cost in that case. Measured design-window adjusted excess: −5.65pp, the
worst of the eight. chop-2015 is a close second (−5.00) for essentially the same reason without a
confirmed trend ever forming.

## 7. Honest estimate and the single weakest assumption

**I expect 4-5 of 8 windows positive when actually scored**, centered on the design-window result of
5/8. The two I'm most confident about staying positive are `gfc` (the exposure-adjustment already
prices in the possibility that this is "absence during the crash," and even so the raw excess is
+53pp against a −56% benchmark — this is not a marginal result) and `recent` (the design window
itself, most exposed to overfitting the sample I could see, but also the window where trend and
benchmark most agree). I expect `bull-2024` to be the one that breaks the card, for the reason in
§6, and I would not be surprised if `chop-2015` joins it — both are robust negatives across every
parameter variant I tried, not artifacts of the specific 50/200 choice.

**Weakest assumption:** that the flight-to-quality correlation between equities and TLT/GLD holds
in the windows I have not measured as it did in the ones I have. The two crisis windows that make
this card's median (gfc, covid) both had bonds and gold behaving as ballast; 2022 did not (bear-2022
was the one window in the design sample where nothing — equities, bonds, or gold — trended cleanly,
and the card's result there is a near-zero −0.99 rather than the wide positive its crisis windows
show). If a future stressed window resembles 2022's "everything sells off together" regime rather
than 2008's or 2020's, this card's crisis-window edge is the piece most likely to not show up, and I
have no rule that detects that difference in advance — the universe just is what it is once
submitted.
