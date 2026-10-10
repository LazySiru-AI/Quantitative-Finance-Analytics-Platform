# B-momentum — Strategy B, Confirmed Acceleration

Eligible in **6 of 8** main windows (`q4-2018`, `covid`, `bear-2022`, `chop-2015`, `bull-2024`,
`recent`), clearing the round's 5-of-8 gate. Blocked from `gfc` and `chop-2011`: the universe holds
NOW, first bar 2012-06-29, which post-dates `chop-2011`'s own end (2012-06-06) and the whole of `gfc`
outright. This eligibility floor is shared by all five B-family cards, since the universe is identical
across the base and every variant.

## 1. What the card is

One entry condition, applied identically across a 12-name AI/cloud-infrastructure universe (`NVDA AMD
AVGO MU MRVL TSM META MSFT GOOGL NOW AMZN NFLX`): `ema(20) crosses_above ema(50) and close >
sma(200)` — a fresh medium-term acceleration inside an already-standing long-term uptrend, not a
bottom-pick. Exit is a trend break (`close crosses_below sma(200)`), backstopped by a 12% stop, no
take-profit, a 180-day hold cap, 6 concurrent slots at 15% each.

The author's design-time case against a take-profit is explicit and measured: testing a fixed
take-profit and a fast EMA exit against simply riding to a stop or trend break, on the same entry,
found that capping gains at 8–30% cut mean per-signal return to 2–9%, against roughly triple the
aggregate return for the uncapped exit — "this strategy's edge is concentrated in a minority of large
winners, which is exactly what a take-profit would have amputated." Four variants each isolate one
decision against this card: `B1-with-target` adds the 25% take-profit back; `B2-hold-90` halves the
hold cap; `B3-concentrated` trades 4 slots at 22% instead of 6 at 15%; `B4-tight-stop` cuts the stop
to 8%. Their reports carry the head-to-head detail; this report is anchor and reference for all four.

## 2. Versus SPY, every window

| window | sessions | card return | SPY return | excess | adj. excess | capital exposure | max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|
| `q4-2018` | 65 | -0.88% | -20.05% | **+19.16%** | -0.79% | 0.4% | -1.03% |
| `covid` | 93 | +22.93% | -8.71% | **+31.64%** | +27.70% | 54.7% | -4.58% |
| `bear-2022` | 196 | -6.77% | -25.14% | **+18.37%** | -5.15% | 6.4% | -7.77% |
| `chop-2015` | 260 | +24.58% | -0.04% | **+24.62%** | +24.60% | 56.3% | -12.17% |
| `bull-2024` | 250 | +15.20% | +14.00% | **+1.21%** | +7.40% | 55.8% | -15.22% |
| `recent` | 249 | +24.27% | +20.62% | **+3.65%** | +16.91% | 35.7% | -26.51% |

Median adjusted excess (the scorecard's rank key, over these six windows) **+12.16%**, hit rate 4 of 6
(66.7%), IQR 21.42 points. Round 1 measured +12.21% over four windows (`covid`, `bear-2022`,
`bull-2024`, `recent`) — per `REPORT.md` §1, that is the *same* number recomputed, not a second draw,
since all four windows are byte-identical between rounds. The only genuinely new evidence this round
adds is `q4-2018` and `chop-2015`; their own two-window median is **+11.91%**, close to the six-window
figure and positive on its own.

Every excess figure is large and positive except `bull-2024`'s modest +1.21%; four of six raw excess
figures exceed +18 points. But raw excess and adjusted excess diverge sharply and in both directions:
`q4-2018` shows +19.16% raw excess collapsing to -0.79% adjusted, because the card held one position
for two sessions in a 65-session window — 0.4% capital exposure — so almost none of SPY's -20.05% fall
was avoided by rule, only by absence. `chop-2015` and `covid` show the opposite: raw and adjusted
excess sit within half a point of each other because capital exposure (56.3% and 54.7%) is close to
the field's normal range, so the adjustment barely moves the number.

## 3. What moved the number

### `q4-2018` — 1 trade, entirely absence

The window's only trade: **NOW**, entered 2018-12-14, exited 2018-12-18 (2 bars, `rule`), -6.12%,
-$88, **-0.88% of the card's return** — the whole of it. SPY fell -20.05% over the full 65-session
window; the card was flat cash before this trade and after it. No winners exist in this window at all.

### `covid` — 6 trades, none closed

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| MRVL | 2020-04-16 | _open_ | 52 | open_at_end | +38.80% | +578 | +5.78% |
| NVDA | 2020-04-07 | _open_ | 58 | open_at_end | +36.86% | +570 | +5.70% |
| AMZN | 2020-04-08 | _open_ | 57 | open_at_end | +36.44% | +516 | +5.16% |
| NFLX | 2020-03-30 | _open_ | 64 | open_at_end | +25.29% | +386 | +3.86% |
| MSFT | 2020-04-16 | _open_ | 52 | open_at_end | +16.70% | +233 | +2.33% |
| AMD | 2020-04-14 | _open_ | 54 | open_at_end | +0.65% | +10 | +0.10% |

All six positions are still open at the window's close (2020-06-30) — none closed inside the window at
all. The earliest entry is 2020-03-30, one week after SPY's 2020-03-23 bottom: the entry rule requires
`ema(20)` to have already crossed above `ema(50)` with price back above `sma(200)`, a condition that
physically cannot fire mid-crash. The card was never asked to hold through the crash; it was absent
from it by construction, then bought six names already recovering. The +27.70% adjusted excess here is
arithmetic on that absence, not a demonstrated defensive call.

### `bear-2022` — 5 trades, zero winners

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| MU | 2022-02-11 | 2022-03-08 | 16 | stop | -16.56% | -242 | -2.42% |
| NVDA | 2022-03-29 | 2022-04-07 | 7 | stop | -14.91% | -227 | -2.27% |
| AVGO | 2022-02-11 | 2022-05-02 | 54 | rule | -3.61% | -87 | -0.87% |
| GOOGL | 2022-03-30 | 2022-04-07 | 6 | rule | — | -66 | -0.66% |
| MSFT | 2022-04-04 | 2022-04-07 | 3 | rule | -4.43% | -55 | -0.55% |

Every one of the five signals this window took was wrong; win rate is a real, not a null-substituted,
0%. The card still beat SPY by 18.37 points raw, but only because it deployed 6.4% of capital while
the benchmark was fully invested through a -25.14% grind — the adjusted excess (-5.15%) is negative
once that difference is priced in. Less wrong than the market here is a function of how little was at
risk, not of anything the rules identified.

### `chop-2015` — 22 trades, dominated by three time-stop exits

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| NFLX | 2015-04-09 | 2015-12-23 | 180 | time | +85.55% | +1,277 | +12.77% |
| GOOGL | 2015-07-14 | 2016-03-31 | 180 | time | +33.61% | +502 | +5.02% |
| META | 2015-06-04 | 2016-02-22 | 180 | time | +28.30% | +419 | +4.19% |
| MSFT | 2015-10-08 | _open_ | 130 | open_at_end | +19.47% | +290 | +2.90% |
| NVDA | 2016-02-29 | _open_ | 33 | open_at_end | +17.51% | +262 | +2.62% |
| AMD | 2016-03-09 | _open_ | 26 | open_at_end | +16.38% | +248 | +2.48% |
| AVGO | 2016-03-03 | _open_ | 30 | open_at_end | +12.84% | +193 | +1.93% |
| NOW | 2015-05-22 | 2015-08-21 | 63 | rule | -11.71% | -175 | -1.75% |
| TSM | 2015-04-27 | 2015-06-09 | 30 | rule | -8.20% | -122 | -1.22% |
| NVDA | 2015-08-12 | 2015-08-25 | 9 | rule | -6.93% | -102 | -1.02% |

The three biggest winners are all 180-day backstop exits, not trend-break exits — in a sideways year
the SMA(200) trend break rarely fires cleanly, so the position simply rides to the hold cap. NFLX alone
is 12.77 points of the card's 24.58% return. Four more positions (MSFT, NVDA, AMD, AVGO) are still open
at the window's close, contributing another 9.93 points that are marks, not money taken. This is the
window the two variants that touch the hold cap and the take-profit (`B2`, `B1`) are built to test —
see their reports.

### `bull-2024` — 19 trades, entirely carried by open positions

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| AVGO | 2025-05-08 | _open_ | 71 | open_at_end | +39.92% | +581 | +5.81% |
| NVDA | 2025-05-15 | _open_ | 66 | open_at_end | +30.54% | +451 | +4.51% |
| NFLX | 2025-04-22 | _open_ | 83 | open_at_end | +20.69% | +312 | +3.12% |
| TSM | 2025-05-15 | _open_ | 66 | open_at_end | +18.32% | +248 | +2.48% |
| MSFT | 2025-05-06 | _open_ | 73 | open_at_end | +16.95% | +220 | +2.20% |
| AVGO | 2024-09-13 | 2025-03-07 | 119 | rule | +12.48% | +187 | +1.87% |
| MRVL | 2024-09-03 | 2024-09-09 | 4 | rule | -9.13% | -129 | -1.29% |

Card +15.20% against SPY's +14.00% — a thin +1.21% raw excess that becomes +7.40% adjusted, because
capital exposure (55.8%) trails the benchmark's implicit 100%. Every one of the five largest winners is
still open at window close; **+18.13% of the card's +15.20% return sits in marks, not realised P&L** —
more than the entire return. The one closed winner in the list, AVGO entered 2024-09-13, is a
cautionary tale for what the still-open ones may yet do: it ran to a much larger paper gain before the
trend-break rule finally exited it 119 bars later at only +12.48%. See `B1-with-target`'s report §4 for
the full trade-by-trade version of this comparison.

### `recent` — 17 trades, two open positions carry the entire result

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| MRVL | 2026-03-11 | _open_ | 110 | **open_at_end** | +130.65% | +1,958 | +19.58% |
| AMD | 2026-04-09 | _open_ | 90 | **open_at_end** | +107.78% | +1,508 | +15.08% |
| AMZN | 2025-11-03 | 2025-11-19 | 12 | stop | -12.47% | -191 | -1.91% |
| AMZN | 2025-12-29 | 2026-02-06 | 27 | rule | -12.70% | -177 | -1.77% |
| TSM | 2026-04-08 | _open_ | 91 | open_at_end | +11.59% | +172 | +1.72% |
| AMD | 2026-01-05 | 2026-02-05 | 22 | stop | -12.42% | -172 | -1.72% |
| NVDA | 2026-07-16 | 2026-07-30 | 10 | rule | -8.05% | -119 | -1.19% |
| META | 2026-07-15 | 2026-07-23 | 6 | rule | -8.41% | -112 | -1.12% |
| META | 2026-02-02 | 2026-02-05 | 3 | rule | -7.24% | -103 | -1.03% |

Of 11 *closed* trades in this window, every one lost money — win rate 0% on closed trades. The card's
positive +24.27% return rests entirely on three still-open positions, and almost entirely on two of
them: MRVL (+130.65%, +19.58% of the card) and AMD (+107.78%, +15.08%). Between them these two open
marks are **34.66% of the card's return against a total return of 24.27%** — the closed book, taken on
its own, is net negative and the open marks are carrying more than the whole result.

## 4. Concentration

| window | top-3-winner share of gross wins | return without top 3 |
|---|---|---|
| `q4-2018` | n/a — no winning trades this window | -0.88% (unchanged; there is nothing to remove) |
| `covid` | 72.6% | +6.29% |
| `bear-2022` | n/a — no winning trades this window | -6.77% (unchanged) |
| `chop-2015` | 66.8% | +2.60% |
| `bull-2024` | 63.6% | +1.75% |
| `recent` | 99.6% | -12.10% |

`recent` is the extreme case: with the top 3 winners removed (MRVL, AMD, and the third-largest, TSM),
the card's return flips from +24.27% to **-12.10%**. Every other window's positive result also
concentrates in a handful of names — in no window does the card's return survive removing its three
best trades and stay positive except `chop-2015` and `bull-2024`, and there only barely.

## 5. Realised versus marked

| window | share of return that is unrealised (open at window close) |
|---|---|
| `q4-2018` | 0% |
| `covid` | +22.93% (of +22.93% total — effectively the whole window) |
| `bear-2022` | 0% |
| `chop-2015` | +10.80% (of +24.58% total) |
| `bull-2024` | +18.13% (of +15.20% total — more than the entire return) |
| `recent` | +35.58% (of +24.27% total — more than the entire return) |

Three of the card's six windows show unrealised marks exceeding or equal to the entire reported return.
`bear-2022` and `q4-2018` are genuinely, verifiably 0% unrealised — every trade in both windows closed
before the window ended, and both had no winners to mark in any case. But in `covid`, `bull-2024`,
`recent` and to a real extent `chop-2015`, a large share of what looks like a strong number is a mark
against the last session's close, not money the card has taken. `recent` is the sharpest instance in
this whole family: **MRVL, still open at +130.65% (+19.58% of the card), and AMD, still open at
+107.78% (+15.08% of the card), are unrealised.** Had the window closed a month earlier or later, this
number could look very different in either direction. A marked gain of this size has demonstrated that
a position is currently worth more, not that the strategy has successfully converted a large move into
cash — those are different claims, and only one of them is settled. `B2-hold-90`'s report gives the one
genuine counter-example in this family: its 90-day cap forces the same MRVL position to close at
+119.4% a month before this window ends, converting the mark this card is still carrying into a
realised number instead.

## 6. Verdict

Positive median adjusted excess in both rounds run so far (+12.21% on four windows in round 1, +12.16%
on six windows in round 2), a 4-of-6 hit rate, full eligibility on every window the universe can reach.
Under `PROTOCOL.md` §6, demotion to `candidates/` requires failing the gate or a negative median in
**two consecutive rounds** — neither condition is close to being met. The card's own new-window
evidence (`q4-2018`, `chop-2015`) posts a positive +11.91% median on its own, so nothing in this round's
genuinely new data argues against the card either.

Two qualifications belong beside the headline number regardless. First, `covid`'s result is a
structural artifact of an entry rule that cannot fire mid-crash, not a demonstrated defensive skill.
Second — and this is the finding this round's larger window set sharpens rather than resolves — three
of six windows now show unrealised marks equal to or larger than the card's entire reported return,
`recent` and `bull-2024` chief among them. A settled comparison of this card's true edge would need
those positions to actually close.

**Recommendation: retain in `library/base/`. No demotion, no change.** None of the four variants beats
this card on median adjusted excess by a margin that clears the noise floor in either round (see each
variant's own report and `REPORT.md` §5); the base card's position is unchallenged this round.
