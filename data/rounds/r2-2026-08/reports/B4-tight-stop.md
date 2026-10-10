# B4-tight-stop — 8% Stop

Eligible in the same 6 of 8 main windows as the rest of the B family (`q4-2018`, `covid`, `bear-2022`,
`chop-2015`, `bull-2024`, `recent`); blocked from `gfc` and `chop-2011` on the NOW-history floor (first
bar 2012-06-29).

## 1. What this card isolates

Identical to `B-momentum` in universe, entry, exit, hold cap and position sizing. The **only** change:
the stop tightens from 12% to 8%. `library/README.md` poses the same question asked of the A family's
equivalent variant, `A4-tight-stop`, on a slower book: does a tighter stop help, or does it just harvest
noise — cutting positions on ordinary volatility before the trend has actually broken, without reducing
how badly the fills themselves land, since stops evaluate against the previous close and fill at the
next open?

## 2. Versus SPY, every window

| window | sessions | card return | SPY return | excess | adj. excess | capital exposure | max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|
| `q4-2018` | 65 | -0.88% | -20.05% | **+19.16%** | -0.79% | 0.4% | -1.03% |
| `covid` | 93 | +22.93% | -8.71% | **+31.64%** | +27.70% | 54.7% | -4.58% |
| `bear-2022` | 196 | -5.63% | -25.14% | **+19.51%** | -4.05% | 6.3% | -6.65% |
| `chop-2015` | 260 | +24.58% | -0.04% | **+24.62%** | +24.60% | 56.3% | -12.17% |
| `bull-2024` | 250 | +14.49% | +14.00% | **+0.49%** | +7.18% | 52.2% | -13.94% |
| `recent` | 249 | +22.18% | +20.62% | **+1.56%** | +14.95% | 35.0% | -26.88% |

Median adjusted excess **+11.06%**, hit rate 4 of 6 (66.7%), IQR 20.99 points. `q4-2018` is
byte-identical to `B-momentum`'s row. `chop-2015` returns the *same* +24.58% total, though three exits
that read `rule` in the base card's log (NOW, TSM, NVDA) read `stop` here at effectively the same
prices and dates — the tighter threshold and the trend-break condition land on the same session for
all three, so the label differs but no fill does. This is the same pattern round 1 found for
`A4-tight-stop`: a tighter stop that happens to coincide with an independent exit condition changes
nothing about the trade, only its recorded reason.

Against `B-momentum`, this card's median trails by **-1.10 points** (11.06 vs 12.16) — essentially
identical to round 1's -1.09-point gap on four shared windows. **On the two windows this round adds**
(`q4-2018`, `chop-2015`), this card's median is **+11.91% — exactly equal to `B-momentum`'s own
new-window median**, because both new windows are unchanged or near-unchanged by the tighter stop.
Tightening the stop is indistinguishable from doing nothing on the round's only genuinely new evidence.

## 3. What moved the number

`q4-2018` reproduces `B-momentum`'s report exactly — one trade, no stop involved.

### `covid` — 6 trades, identical to `B-momentum`

No stop fires in this window for either card (positions are 52–64 bars old, none reaching either
threshold before the window ends); the book is byte-identical to the base card's.

### `bear-2022` — 5 trades, the one window the tighter stop clearly cut losses

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| NVDA | 2022-03-29 | 2022-04-06 | 6 | stop | -13.20% | -201 | -2.01% |
| MU | 2022-02-11 | 2022-03-07 | 15 | stop | -10.53% | -154 | -1.54% |

Compare directly to `B-momentum`'s same two positions: MU exits one session earlier here at -10.53%
against the base card's -16.56% (a real, +6.03-point smaller loss); NVDA exits one session earlier at
-13.20% against -14.91% (+1.71 points smaller). **This is the one clean case in the whole B family
where the tighter stop demonstrably cut a loss smaller**, not merely earlier — both fills still gap
past their own nominal threshold (8% nominal, -10.53%/-13.20% realised), consistent with the
previous-close mechanism, but the realised loss itself is smaller than the wider stop's.

### `chop-2015` — 22 trades, unchanged in aggregate

Same trades, same prices, same +24.58% total as `B-momentum` — see §2. The three relabelled exits
(NOW, TSM, NVDA) are the only visible difference, and it is cosmetic.

### `bull-2024` — 19 trades, one new position the base card never took

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| AVGO | 2025-05-08 | _open_ | 71 | open_at_end | +39.92% | +581 | +5.81% |
| NVDA | 2025-05-15 | _open_ | 66 | open_at_end | +30.54% | +451 | +4.51% |
| NFLX | 2025-04-22 | _open_ | 83 | open_at_end | +20.69% | +312 | +3.12% |
| TSM | 2025-05-15 | _open_ | 66 | open_at_end | +18.32% | +248 | +2.48% |
| MSFT | 2025-05-06 | _open_ | 73 | open_at_end | +16.95% | +220 | +2.20% |
| AVGO | 2024-09-13 | 2025-03-07 | 119 | rule | +12.48% | +187 | +1.87% |
| MRVL | 2024-09-03 | 2024-09-09 | 4 | stop | -9.13% | -129 | -1.29% |
| GOOGL | 2024-10-30 | 2024-11-25 | 18 | stop | -8.17% | -118 | -1.18% |

GOOGL exists only in this card's log — the tighter stop's earlier exits elsewhere freed a slot the
180-day-hold, 12%-stop base card's fully-committed book never had, and this new signal lost money
(-8.17%). The five open positions and the AVGO rule exit are identical to `B-momentum`'s.

### `recent` — 19 trades, this family's clearest case of added churn

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| MRVL | 2026-03-11 | _open_ | 110 | **open_at_end** | +130.65% | +1,958 | +19.58% |
| AMD | 2026-04-09 | _open_ | 90 | **open_at_end** | +107.78% | +1,508 | +15.08% |
| AMD | 2026-01-16 | 2026-02-05 | 13 | stop | -13.93% | -196 | -1.96% |
| AMZN | 2025-12-29 | 2026-02-06 | 27 | rule | -12.70% | -177 | -1.77% |
| TSM | 2026-04-08 | _open_ | 91 | open_at_end | +11.59% | +172 | +1.72% |
| AMZN | 2025-11-03 | 2025-11-17 | 10 | stop | -8.75% | -134 | -1.34% |
| NVDA | 2026-07-16 | 2026-07-30 | 10 | stop | -8.05% | -119 | -1.19% |
| AMD | 2026-01-05 | 2026-01-08 | 3 | stop | -8.50% | -118 | -1.18% |
| META | 2026-07-15 | 2026-07-23 | 6 | rule | -8.41% | -112 | -1.12% |
| NVDA | 2026-02-11 | 2026-03-23 | 27 | stop | -7.99% | -108 | -1.08% |
| NVDA | 2025-12-31 | 2026-02-05 | 24 | stop | -7.82% | -104 | -1.04% |
| META | 2026-02-02 | 2026-02-05 | 3 | rule | -7.24% | -103 | -1.03% |

Where `B-momentum` holds one AMD position (entered 2026-01-05, stopped 2026-02-05 at -12.42%), this
card's tighter stop closes that entry early on 2026-01-08 at -8.50% — then, with the slot freed,
re-enters AMD on 2026-01-16 and is stopped out again on 2026-02-05 at -13.93%: two losing trades
(combined loss larger than the base card's single -12.42%) where the base card took one. The same
mechanism produces a new NVDA entry (2026-02-11, stopped 2026-03-23 at -7.99%) with no counterpart in
`B-momentum`'s book. And the base card's other NVDA position (2025-12-31→2026-03-23, `rule`, -0.87%,
sub-threshold) is a case where the wider stop's patience paid off: this card's tighter stop on the same
entry exits at 2026-02-05, -7.82%, a materially worse outcome than letting the position run to its
eventual small loss. AMZN is the one clean improvement, echoing `bear-2022`: exits two sessions earlier
here at -8.75% against the base card's -12.47%. None of this window's extra churn produced a winning
trade.

## 4. Concentration

| window | top-3-winner share of gross wins | return without top 3 |
|---|---|---|
| `q4-2018` | n/a — no winning trades | -0.88% (unchanged) |
| `covid` | 72.6% | +6.29% |
| `bear-2022` | n/a — no winning trades | -5.63% (unchanged) |
| `chop-2015` | 66.8% | +2.60% |
| `bull-2024` | 63.6% | +1.04% |
| `recent` | 99.6% | -14.19% |

Materially identical to `B-momentum`'s concentration profile — the tighter stop changes exits on
losing positions, not the winners that drive concentration.

## 5. Realised versus marked

| window | share of return that is unrealised |
|---|---|
| `q4-2018` | 0% |
| `covid` | +22.93% (of +22.93% — the entire window) |
| `bear-2022` | 0% |
| `chop-2015` | +10.80% (of +24.58%) |
| `bull-2024` | +18.13% (of +14.49% — more than the entire return) |
| `recent` | +35.58% (of +22.18% — more than the entire return) |

Unchanged from `B-momentum` in every window: the stop threshold affects how losing positions exit, not
whether winning ones stay open. **`recent`'s +35.58% unrealised share is carried by the same MRVL
(+130.65%, +19.58% of the card) and AMD (+107.78%, +15.08%) positions this card holds exactly as
`B-momentum` does — both still open at the window's close, both marks, not money taken.** A tighter
stop does nothing to convert a winner into cash; it only changes how a loser exits, so this card
inherits the base's full exposure to the family's central finding.

## 6. Verdict

Median adjusted excess **+11.06%**, second-lowest in the family, IQR 20.99 points. Against
`B-momentum`, the margin is essentially flat in both directions this round has measured (-1.09 in
round 1, -1.10 in round 2), and exactly zero on the two genuinely new windows. On medians alone,
tightening the stop is indistinguishable from doing nothing — consistent across two rounds now.

But the trade-level detail says more than the medians do, and it is mixed rather than uniformly
negative this round. `bear-2022` is a genuine improvement: both matched stop-outs realised smaller
losses under the tighter threshold, not just earlier ones. `recent` is the opposite: the tighter stop
more than doubled churn on AMD and manufactured a new NVDA entry the base card never took, one of which
(the 2025-12-31 NVDA position) would have recovered to a much smaller loss under the wider stop. Net,
across the two windows where the tighter stop actually produced different fills, the evidence still
leans mildly negative — more turnover, not reliably better fills — but `bear-2022`'s result means this
is no longer a clean "no benefit anywhere" story.

**Recommendation: do not promote to replace `B-momentum`.** `PROTOCOL.md` §6 as amended requires a
positive median on the round's new windows before a margin is even considered, and clearing the noise
floor besides; this card's new-window margin is exactly zero and its full-set margin has been
negative in both rounds run so far. Round 3 should track whether `bear-2022`'s improvement or
`recent`'s added churn is the more representative behaviour of an 8% stop on this book — one round of
each, in opposite directions, is not yet a pattern.
