# B1-with-target — 25% Take-Profit Added

Eligible in the same 6 of 8 main windows as the rest of the B family (`q4-2018`, `covid`, `bear-2022`,
`chop-2015`, `bull-2024`, `recent`); blocked from `gfc` and `chop-2011` on the NOW-history floor
(first bar 2012-06-29).

## 1. What this card isolates

Identical to `B-momentum` in universe, entry, exit, stop, hold cap and position sizing. The **only**
change: a 25% take-profit bracket is added (`take_profit_pct = 0.25`), where the base card has none.

This is the most direct test the B family runs, because it contradicts the base card's own author on
a measured, stated position: the author tested fixed take-profits at design time and found they cut
mean per-signal return from roughly triple the uncapped figure down to 2–9%, concluding "this
strategy's edge is concentrated in a minority of large winners, which is exactly what a take-profit
would have amputated." B1 asks, on real trades this round: does a 25% target in fact amputate
B-momentum's winners, or does letting a position run past 25% just as often give the gain back before
the trend-break rule or hold cap eventually exits it?

## 2. Versus SPY, every window

| window | sessions | card return | SPY return | excess | adj. excess | capital exposure | max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|
| `q4-2018` | 65 | -0.88% | -20.05% | **+19.16%** | -0.79% | 0.4% | -1.03% |
| `covid` | 93 | +19.51% | -8.71% | **+28.22%** | +23.22% | 42.7% | -4.58% |
| `bear-2022` | 196 | -6.77% | -25.14% | **+18.37%** | -5.15% | 6.4% | -7.77% |
| `chop-2015` | 260 | +10.03% | -0.04% | **+10.07%** | +10.05% | 41.2% | -10.77% |
| `bull-2024` | 250 | +25.26% | +14.00% | **+11.26%** | +19.56% | 40.7% | -6.31% |
| `recent` | 249 | +2.38% | +20.62% | **-18.24%** | -3.08% | 26.4% | -8.93% |

Median adjusted excess **+4.63%**, hit rate 3 of 6 (50%, the lowest of any B-family card), IQR 19.69
points. `q4-2018` and `bear-2022` are byte-identical to `B-momentum`'s rows — the target never fires
in either window, because `q4-2018` has one trade (a loss) and every `bear-2022` signal loses money
before any target could be reached. `recent` is the one window where this card actually trails SPY:
+2.38% against +20.62%, a -18.24% raw excess and the family's only negative excess outside `bear-2022`.

**On the windows this round genuinely adds** (`q4-2018`, `chop-2015`) the two-window median is also
**+4.63%** (adj. excess of -0.79% and +10.05% averaged) — positive on its own, but 7.28 points *below*
`B-momentum`'s own new-window median of +11.91%. The take-profit does not lead the base card even on
the fresh evidence this round supplies.

## 3. What moved the number

`q4-2018` and `bear-2022` reproduce `B-momentum`'s report exactly (§3 there) — the target never fires
in either window, so nothing about this card's own trades differs. The four windows where the target
actually bound:

### `covid` — 8 trades

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| AMZN | 2020-04-08 | 2020-06-10 | 43 | target | +30.74% | +435 | +4.35% |
| MRVL | 2020-04-16 | 2020-06-01 | 31 | target | +27.98% | +417 | +4.17% |
| NVDA | 2020-04-07 | 2020-05-19 | 29 | target | +26.65% | +412 | +4.12% |
| NFLX | 2020-03-30 | 2020-05-18 | 34 | target | +24.14% | +368 | +3.68% |
| MSFT | 2020-04-16 | _open_ | 52 | open_at_end | +16.70% | +233 | +2.33% |

Four of the base card's five open `covid` positions are closed here via target instead. The fifth
(MSFT) never reached 25% inside the window and remains open in both cards, identically.

### `chop-2015` — 26 trades

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| NFLX | 2015-04-09 | 2015-04-17 | 6 | target | +26.50% | +396 | +3.96% |
| AMD | 2016-03-09 | 2016-03-21 | 8 | target | +24.99% | +378 | +3.78% |
| GOOGL | 2015-07-14 | 2015-10-26 | 73 | target | +25.19% | +376 | +3.76% |
| META | 2015-06-04 | 2015-10-27 | 101 | target | +25.20% | +373 | +3.73% |
| MSFT | 2015-10-08 | _open_ | 130 | open_at_end | +19.47% | +290 | +2.90% |
| NVDA | 2016-02-29 | _open_ | 33 | open_at_end | +17.51% | +262 | +2.62% |
| META | 2016-02-02 | 2016-02-09 | 5 | stop | -15.47% | -231 | -2.31% |
| NFLX | 2015-10-09 | 2015-10-19 | 6 | stop | -14.19% | -211 | -2.11% |
| AVGO | 2016-03-03 | _open_ | 30 | open_at_end | +12.84% | +193 | +1.93% |
| NOW | 2015-05-22 | 2015-08-21 | 63 | rule | -11.71% | -175 | -1.75% |

This is the window with the family's freshest evidence on the take-profit question (§4). Where
`B-momentum` rode NFLX, GOOGL and META to the 180-day backstop, this card exits all four target
positions in 6–101 bars.

### `bull-2024` — 20 trades

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| AVGO | 2024-09-13 | 2024-12-16 | 65 | target | +38.87% | +584 | +5.84% |
| NFLX | 2025-04-22 | 2025-06-25 | 44 | target | +27.87% | +421 | +4.21% |
| NVDA | 2025-05-15 | 2025-07-16 | 41 | target | +27.24% | +403 | +4.03% |
| TSM | 2024-09-13 | 2025-01-07 | 79 | target | +28.31% | +390 | +3.90% |
| AVGO | 2025-05-08 | 2025-06-05 | 19 | target | +26.29% | +383 | +3.83% |
| AMZN | 2024-09-18 | 2025-01-23 | 86 | target | +25.43% | +379 | +3.79% |
| TSM | 2025-05-15 | 2025-07-18 | 43 | target | +26.91% | +364 | +3.64% |
| MSFT | 2025-05-06 | _open_ | 73 | open_at_end | +16.95% | +220 | +2.20% |

Seven target exits here — the most of any window — against `B-momentum`'s five still-open positions on
the same names. This window and `recent` carry the family's clearest evidence either way; see §4.

### `recent` — 19 trades

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| MRVL | 2026-03-11 | 2026-04-10 | 21 | target | +31.98% | +479 | +4.79% |
| AMD | 2026-04-09 | 2026-04-23 | 10 | target | +29.48% | +412 | +4.12% |
| AVGO | 2026-04-14 | 2026-06-03 | 35 | target | +30.79% | +349 | +3.49% |
| TSM | 2026-04-08 | 2026-06-23 | 52 | target | +18.48% | +274 | +2.74% |
| AMZN | 2025-11-03 | 2025-11-19 | 12 | stop | -12.47% | -191 | -1.91% |
| AMZN | 2025-12-29 | 2026-02-06 | 27 | rule | -12.70% | -177 | -1.77% |
| AMD | 2026-01-05 | 2026-02-05 | 22 | stop | -12.42% | -172 | -1.72% |
| AVGO | 2026-08-06 | _open_ | 8 | open_at_end | -9.69% | -122 | -1.22% |

This is the window where the family's headline unrealised trade lives, and where this card takes the
opposite side of it: `B-momentum` still holds MRVL and AMD, marked +130.65% and +107.78% at window
close; this card closed both via target at +31.98% and +29.48% weeks earlier.

## 4. The take-profit question, at the trade level, across all six windows

Nineteen target exits fire across four windows (zero in `q4-2018` and `bear-2022` — the target cannot
fire where every trade loses money before reaching it). Each matches a `B-momentum` position on the
same symbol and entry date. Round 1 had this comparison across four windows; round 2 adds `chop-2015`,
and it changes the picture.

**Both cards fully closed the position — the only apples-to-apples comparisons:**

| window | symbol | entry | B1 target exit | B-momentum's eventual exit | gap (base − target) |
|---|---|---|---:|---:|---:|
| `bull-2024` | AVGO | 2024-09-13 | +38.87% (65 bars) | rule, +12.48% (119 bars) | **-26.39pp** |
| `bull-2024` | TSM | 2024-09-13 | +28.31% (79 bars) | rule, +4.00% (114 bars) | **-24.31pp** |
| `bull-2024` | AMZN | 2024-09-18 | +25.43% (86 bars) | rule, +3.89% (118 bars) | **-21.54pp** |
| `recent` | AVGO | 2026-04-14 | +30.79% (35 bars) | rule, -1.24% (56 bars) | **-32.03pp** |
| `chop-2015` | NFLX | 2015-04-09 | +26.50% (6 bars) | time, +85.55% (180 bars) | **+59.05pp** |
| `chop-2015` | GOOGL | 2015-07-14 | +25.19% (73 bars) | time, +33.61% (180 bars) | **+8.42pp** |
| `chop-2015` | META | 2015-06-04 | +25.20% (101 bars) | time, +28.30% (180 bars) | **+3.10pp** |

Negative gap means the target protected a gain the base card gave back; positive means letting it run
paid off. **Round 1 found the target winning all four of its closed-vs-closed comparisons.** Adding
`chop-2015`'s three new pairs makes it **4 wins for the target against 3 for letting it run** — and the
single largest gap in either direction, in the whole comparison, now belongs to letting it run: NFLX
ran to the 180-day backstop for +85.55%, more than triple what a 25% target would have banked, the
cleanest available demonstration of the base author's original thesis. The three `bull-2024`/`recent`
cases are just as clean the other way — real, closed, completed trades where the position kept running
past 25% under `B-momentum`'s rules and gave nearly all of it back (one, AVGO in `recent`, all the way
into a loss) before the trend-break rule finally fired.

**Matches against a `B-momentum` position still open at its window's close** — a locked-in gain
against a paper mark, not a completed trade:

| window | symbol | entry | B1 target exit | B-momentum mark at window close | gap (base − target) |
|---|---|---|---:|---:|---:|
| `bull-2024` | NFLX | 2025-04-22 | +27.87% (44 bars) | open, +20.69% (83 bars) | -7.18pp |
| `bull-2024` | TSM | 2025-05-15 | +26.91% (43 bars) | open, +18.32% (66 bars) | -8.59pp |
| `chop-2015` | AMD | 2016-03-09 | +24.99% (8 bars) | open, +16.38% (26 bars) | -8.61pp |
| `recent` | TSM | 2026-04-08 | +18.48% (52 bars) | open, +11.59% (91 bars) | -6.89pp |
| `bull-2024` | NVDA | 2025-05-15 | +27.24% (41 bars) | open, +30.54% (66 bars) | +3.30pp |
| `bull-2024` | AVGO | 2025-05-08 | +26.29% (19 bars) | open, +39.92% (71 bars) | +13.63pp |
| `covid` | NFLX | 2020-03-30 | +24.14% (34 bars) | open, +25.29% (64 bars) | +1.15pp |
| `covid` | AMZN | 2020-04-08 | +30.74% (43 bars) | open, +36.44% (57 bars) | +5.70pp |
| `covid` | NVDA | 2020-04-07 | +26.65% (29 bars) | open, +36.86% (58 bars) | +10.21pp |
| `covid` | MRVL | 2020-04-16 | +27.98% (31 bars) | open, +38.80% (52 bars) | +10.82pp |
| `recent` | MRVL | 2026-03-11 | +31.98% (21 bars) | **open, +130.65%** (110 bars) | **+98.67pp** |
| `recent` | AMD | 2026-04-09 | +29.48% (10 bars) | **open, +107.78%** (90 bars) | **+78.30pp** |

Of these twelve, the target is ahead in 4 (all recovered by `chop-2015`'s new AMD case, plus three
already found in round 1) and behind in 8 — including the two largest gaps in this entire report, the
`recent`-window MRVL and AMD positions, unchanged from round 1 because `recent` is the same window in
both rounds. Both are marks on positions still open as of 2026-08-18, not finished trades.

**Verdict on the take-profit question: round 2's larger window set does not resolve it, and sharpens
the tension rather than settling it.** Round 1's clean 4-for-4 sweep on completed trades is now 4-for-7
— the take-profit still wins every completed comparison from `bull-2024` and `recent`, by an average of
about 26 points, but `chop-2015` supplies three new completed comparisons where letting it run wins,
one of them (NFLX, +59.05pp) the single largest gap of either sign this comparison has produced. Among
positions still open, letting it run remains ahead more often than not, and by the largest margins in
the whole dataset — but those are marks on unresolved positions, not settled outcomes, and the
`bull-2024`/`recent` completed cases show exactly how far such a mark can round-trip before it exits.
The author's original claim — that a cap amputates the winners carrying this book — is neither
confirmed nor refuted by this round's evidence. That remains the honest and, on this data, the correct
answer.

## 5. Concentration

| window | top-3-winner share of gross wins | return without top 3 |
|---|---|---|
| `q4-2018` | n/a — no winning trades | -0.88% (unchanged) |
| `covid` | 64.8% | +6.86% |
| `bear-2022` | n/a — no winning trades | -6.77% (unchanged) |
| `chop-2015` | 48.6% | -1.47% |
| `bull-2024` | 44.8% | +11.19% |
| `recent` | 81.1% | -10.03% |

Concentration is materially lower than `B-momentum`'s in every window with winners — 44.8%/48.6%/64.8%
here against the base card's 63.6%/66.8%/72.6% — because the target caps each individual winner's size
before it can dominate the book, exactly the mechanical effect the take-profit is supposed to have.
`recent` is the exception: even with four target exits, 81.1% of gross wins still concentrate in three
names, and the card's return without its top 3 still turns negative (-10.03%).

## 6. Realised versus marked

| window | share of return that is unrealised |
|---|---|
| `q4-2018` | 0% |
| `covid` | +2.76% (of +19.51% total) |
| `bear-2022` | 0% |
| `chop-2015` | +8.20% (of +10.03% total) |
| `bull-2024` | +1.95% (of +25.26% total) |
| `recent` | -2.50% (of +2.38% total) |

This is the family's least mark-dependent card, and materially so: `bull-2024`'s unrealised share is
1.95% against `B-momentum`'s 18.13%, and `covid`'s is 2.76% against 22.93% — the target converts marks
into realised P&L in exactly the windows where the base card's result is still a paper number. The
remaining open position each window (MSFT in `covid`/`bull-2024`, an isolated AVGO stub in `recent`) is
one the target never reached, not an artifact of this card's own construction. `chop-2015`'s +8.20% is
the highest unrealised share this card carries, from two positions (MSFT, NVDA) that had not yet hit
25% by the window's close.

## 7. Verdict

Median adjusted excess **+4.63%**, the lowest of the five B-family cards, on the lowest hit rate (3 of
6) and a wide IQR (19.69 points). Against `B-momentum`, the margin is -7.53 points on the full
six-window median and -7.28 points on the two windows this round actually adds — negative both ways,
the only B-family variant for which that is true in both directions.

**Recommendation: retain as a variant under `PROTOCOL.md` §6 as amended; no promotion.** Neither
condition for a variant to replace its base is met: the margin runs against this card on both the full
set and the new-window set, so §6(a)'s requirement of a positive new-window median advantage fails
outright, independent of §6(b)'s noise-floor test. But this remains the one variant in the family whose
trade-level evidence is worth more than its ranking. §4's comparison is the most carefully matched
result this round produced on the base card's own pre-registered claim, and round 2 made it *more*
informative, not less: what was a clean sweep for the target in round 1 is now a genuine split, with
the round's single largest trade-level effect (NFLX, chop-2015, +59.05pp for letting it run) sitting
directly beside the round's second-largest (AVGO, recent, -32.03pp for the target). Round 3, if it adds
further windows, should keep tracking whether the still-open `recent`-window MRVL and AMD positions
finally resolve — they alone still account for the largest gaps in either direction, and remain
exactly as unresolved as they were in round 1.
