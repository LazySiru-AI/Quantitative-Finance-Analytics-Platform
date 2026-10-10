# B2-hold-90 — 90-Day Max Hold

Eligible in the same 6 of 8 main windows as the rest of the B family (`q4-2018`, `covid`, `bear-2022`,
`chop-2015`, `bull-2024`, `recent`); blocked from `gfc` and `chop-2011` on the NOW-history floor
(first bar 2012-06-29).

## 1. What this card isolates

Identical to `B-momentum` in universe, entry, exit, stop and position sizing. The **only** change:
`max_hold_days` is halved from 180 to 90. `library/README.md` frames the question as design-time
context — "ten of B's 41 exits were time-stops" in the author's own design-window backtest — asking
whether the long leash is earning its exposure. That statistic does not reproduce cleanly in this
round's runnable windows: `B-momentum` at 180 days takes zero time-cap exits in `covid`, `bear-2022` or
`q4-2018`, and only reaches the cap via the three `bull-2024` and three `recent`/`chop-2015` positions
this card's own 90-day cap forces early. So the question this round can actually answer is narrower
than the design-time one: not "does the long leash matter" in the abstract, but "in the specific
positions where a 90-day cap forces an exit a 180-day cap would not, what does the extra runway do?"

## 2. Versus SPY, every window

| window | sessions | card return | SPY return | excess | adj. excess | capital exposure | max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|
| `q4-2018` | 65 | -0.88% | -20.05% | **+19.16%** | -0.79% | 0.4% | -1.03% |
| `covid` | 93 | +22.93% | -8.71% | **+31.64%** | +27.70% | 54.7% | -4.58% |
| `bear-2022` | 196 | -6.77% | -25.14% | **+18.37%** | -5.15% | 6.4% | -7.77% |
| `chop-2015` | 260 | +17.57% | -0.04% | **+17.60%** | +17.58% | 46.4% | -9.92% |
| `bull-2024` | 250 | +27.69% | +14.00% | **+13.69%** | +20.55% | 51.0% | -6.31% |
| `recent` | 249 | +22.19% | +20.62% | **+1.57%** | +15.03% | 34.7% | -22.08% |

Median adjusted excess **+16.31%**, hit rate 4 of 6 (66.7%), IQR **16.64 points — the tightest of any
B-family card**. `q4-2018`, `covid` and `bear-2022` are byte-identical to `B-momentum`'s rows: the
90-day cap never binds in any of the three — `covid`'s positions are all under 90 bars old at window
close, `bear-2022`'s five trades all close within 54 bars, and `q4-2018` has one trade lasting 2 bars.

This card's full-window median leads `B-momentum`'s by **+4.15 points** (16.31 vs 12.16) — close to
round 1's +5.62-point lead (17.83 vs 12.21) on the four shared windows. `REPORT.md` §5 already flags
both margins as **far inside the noise floor**: `PROTOCOL.md` §7's twelve-ordering sensitivity study
measured a 53.9-point spread at σ = 21.2 on an *identical* card reordered twelve ways, and a single
window's pure-ordering artifact has separately been measured up to 12.5 points. A ~4-point median gap
does not clear either bar. **On the two windows this round actually adds** (`q4-2018`, `chop-2015`),
this card's own median is +8.40% — positive, but 3.51 points *below* `B-momentum`'s new-window median
of +11.91%. The lead this card shows on the full six-window set does not survive when restricted to
the round's genuinely new evidence.

## 3. What moved the number

`q4-2018`, `covid` and `bear-2022` reproduce `B-momentum`'s report exactly (see that report's §3) — no
trade in any of the three reaches the 90-day cap, so this card's book is identical to the base's.

### `bull-2024` — 19 trades, three forced early by the cap

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| AVGO | 2024-09-13 | 2025-01-24 | 90 | **time** | +46.61% | +700 | +7.00% |
| AVGO | 2025-05-08 | _open_ | 71 | open_at_end | +39.92% | +581 | +5.81% |
| NVDA | 2025-05-15 | _open_ | 66 | open_at_end | +30.54% | +451 | +4.51% |
| TSM | 2024-09-13 | 2025-01-24 | 90 | **time** | +31.20% | +430 | +4.30% |
| AMZN | 2024-09-18 | 2025-01-29 | 90 | **time** | +28.07% | +419 | +4.19% |
| NFLX | 2025-04-22 | _open_ | 83 | open_at_end | +20.69% | +312 | +3.12% |
| TSM | 2025-05-15 | _open_ | 66 | open_at_end | +18.32% | +248 | +2.48% |
| MSFT | 2025-05-06 | _open_ | 73 | open_at_end | +16.95% | +220 | +2.20% |
| MRVL | 2024-09-03 | 2024-09-09 | 4 | rule | -9.13% | -129 | -1.29% |

AVGO, TSM and AMZN — all entered 2024-09-13/18 — hit the 90-day cap here, and all three lock in *more*
than `B-momentum`'s eventual exit on the identical positions (that card's rule exits on these same
three, reported in its §3, land at +12.48%, +4.00% and +3.89%). See §4.

### `chop-2015` — 27 trades, five time-cap exits

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| NFLX | 2015-04-09 | 2015-08-17 | 90 | **time** | +95.39% | +1,424 | +14.24% |
| GOOGL | 2015-07-14 | 2015-11-18 | 90 | **time** | +30.34% | +453 | +4.53% |
| NVDA | 2016-02-29 | _open_ | 33 | open_at_end | +17.51% | +262 | +2.62% |
| AMD | 2016-03-09 | _open_ | 26 | open_at_end | +16.38% | +248 | +2.48% |
| META | 2016-02-02 | 2016-02-09 | 5 | stop | -15.47% | -231 | -2.31% |
| NFLX | 2015-10-09 | 2015-10-19 | 6 | stop | -14.19% | -211 | -2.11% |
| META | 2015-06-04 | 2015-10-12 | 90 | **time** | +13.49% | +200 | +2.00% |
| AVGO | 2016-03-03 | _open_ | 30 | open_at_end | +12.84% | +193 | +1.93% |
| MSFT | 2015-10-08 | 2016-02-18 | 90 | **time** | +12.28% | +183 | +1.83% |
| NOW | 2015-05-22 | 2015-08-21 | 63 | rule | -11.71% | -175 | -1.75% |

Here the cap costs, not helps: `B-momentum` rode NFLX, GOOGL and META to the 180-day backstop for
+85.55%, +33.61% and +28.30% respectively; this card's 90-day cap forces NFLX and GOOGL out early at
+95.39% and +30.34% (NFLX is *higher* here — the position kept climbing past day 90 in this particular
case) but META out at only +13.49% against the base's eventual +28.30%. Three different signs of the
same mechanism in one window: sometimes the shorter leash exits at a local high, sometimes well below
one.

### `recent` — 18 trades, the family's clearest realised-versus-marked contrast

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| MRVL | 2026-03-11 | 2026-07-21 | 90 | **time** | +119.39% | +1,789 | +17.89% |
| AMD | 2026-04-09 | 2026-08-18 | 90 | **time** | +109.03% | +1,525 | +15.25% |
| TSM | 2026-04-08 | 2026-08-17 | 90 | **time** | +16.00% | +237 | +2.37% |
| AMZN | 2025-11-03 | 2025-11-19 | 12 | stop | -12.47% | -191 | -1.91% |
| AMZN | 2025-12-29 | 2026-02-06 | 27 | rule | -12.70% | -177 | -1.77% |
| AMD | 2026-01-05 | 2026-02-05 | 22 | stop | -12.42% | -172 | -1.72% |
| AVGO | 2026-08-06 | _open_ | 8 | open_at_end | -9.69% | -122 | -1.22% |
| NVDA | 2026-07-16 | 2026-07-30 | 10 | rule | -8.05% | -119 | -1.19% |
| META | 2026-07-15 | 2026-07-23 | 6 | rule | -8.41% | -112 | -1.12% |
| META | 2026-02-02 | 2026-02-05 | 3 | rule | -7.24% | -103 | -1.03% |

This window is the direct answer to the family's headline finding — see §5.

## 4. What the 90-day cap actually did, where it bound

The six time-cap exits are the only trades in this card's log that differ mechanically from
`B-momentum`'s. In `bull-2024`, all three matched the base card's still-running position at the point
the cap forced an exit, and in all three the forced exit locked in *more* than the base card eventually
kept:

| symbol | entry | B2 time-cap exit (90 bars) | B-momentum's eventual result | gap (base − B2) |
|---|---|---:|---:|---:|
| AVGO | 2024-09-13 | +46.61% (2025-01-24) | rule, +12.48% (2025-03-07, 119 bars) | **-34.13pp** |
| TSM | 2024-09-13 | +31.20% (2025-01-24) | rule, +4.00% (2025-02-28, 114 bars) | **-27.20pp** |
| AMZN | 2024-09-18 | +28.07% (2025-01-29) | rule, +3.89% (2025-03-11, 118 bars) | **-24.18pp** |

These are the same three positions `B1-with-target`'s 25% target also locked in ahead of
`B-momentum`'s eventual round-trip (see that report's §4). The 90-day cap and the 25% target reached
the same conclusion by two different mechanisms in `bull-2024`: whatever pushed these three back down
from a large paper gain did so before either a target or a 90-day clock could be blamed for missing
more, and after either one would already have exited.

In `recent`, the three time-cap exits are far less one-sided — the cap lands close to where the
window itself ends:

| symbol | entry | B2 time-cap exit (90 bars) | B-momentum's mark at same point | gap (base − B2) |
|---|---|---:|---:|---:|
| MRVL | 2026-03-11 | +119.39% (2026-07-21) | open, +130.65% (2026-08-18, 110 bars) | **+11.26pp** (unrealised) |
| TSM | 2026-04-08 | +16.00% (2026-08-17) | open, +11.59% (2026-08-18, 91 bars) | -4.41pp |
| AMD | 2026-04-09 | +109.03% (2026-08-18) | open, +107.78% (2026-08-18, 90 bars) | -1.25pp |

AMD's 90-day cap and the window's own last session are one day apart — the two cards' figures are
nearly identical by construction, not because the cap did anything distinctive. MRVL is the one case
where the extra 20 days of `B-momentum`'s longer leash shows a further gain, but it is a further gain
in an *unrealised mark*, not a completed trade — see §5.

## 5. Concentration

| window | top-3-winner share of gross wins | return without top 3 |
|---|---|---|
| `q4-2018` | n/a — no winning trades | -0.88% (unchanged) |
| `covid` | 72.6% | +6.29% |
| `bear-2022` | n/a — no winning trades | -6.77% (unchanged) |
| `chop-2015` | 68.6% | -3.83% |
| `bull-2024` | 51.5% | +10.36% |
| `recent` | 99.6% | -13.32% |

`recent` again concentrates almost entirely in three names — but here, unlike the base card, all three
are realised, not marked (§6).

## 6. Realised versus marked — this family's central finding, and this card's answer to it

| window | share of return that is unrealised |
|---|---|
| `q4-2018` | 0% |
| `covid` | +22.93% (of +22.93% — the whole window) |
| `bear-2022` | 0% |
| `chop-2015` | +8.36% (of +17.57%) |
| `bull-2024` | +18.13% (of +27.69%) |
| `recent` | **-2.02%** (of +22.19%) |

`recent` is the one window in the whole B family where the card's result does **not** rest on a large
unrealised mark, and the reason is exactly this card's one changed rule. **`B-momentum`, `B3-concentrated`
and `B4-tight-stop` all hold the same MRVL position, entered 2026-03-11, still open at the window's
close, marked +130.65% (+19.58%–+28.14% of each card's return depending on sizing) — a mark against the
last session's close, not money taken.** This card's 90-day cap forces that identical position closed
on 2026-07-21, 90 bars in, at **+119.39% (+17.89% of the card) — realised**, four weeks before the
window ends. Same trade, same entry, same underlying price path; one rule banks it, three others are
still carrying it as a paper number. That the closed figure (+119.39%) is only 11.26 points below the
still-open mark (+130.65%) is itself informative: the position kept climbing after the cap forced an
exit, so the longer leash *would* have captured more here, on this one occasion — but "would have
captured more, on this occasion, in a mark not yet converted to cash" is a materially weaker claim than
"captured more." AMD tells the opposite story from the same window: this card's 90-day cap and
`B-momentum`'s window-end mark land one day apart (+109.03% realised versus +107.78% still open), so
the cap costs nothing there. The 90-day cap does not have a single direction of effect — it forces
realisation, and whether that costs or protects depends entirely on what the price does after the cap
would have fired, which is exactly the kind of thing a hold-cap parameter cannot know in advance.

## 7. Verdict

Rank position aside, median adjusted excess **+16.31%**, the tightest IQR in the B family (16.64
points) and a 4-of-6 hit rate — read plainly against the field this is a strong result. Read against
its own base card — the only comparison that isolates the one decision this card actually changed —
the full-set margin (+4.15 points) and the new-window-only margin (**-3.51 points, negative**) point in
different directions, and neither clears the ~20-point noise floor `PROTOCOL.md` §7 sets. The card's
only real behavioural difference from `B-momentum` in this round (the three `bull-2024` time-cap exits)
happened to land on the same side as `B1-with-target`'s target exits on the identical three positions,
for reasons that have nothing to do with a 90-day clock specifically — and the `recent`-window MRVL
contrast shows the cap costing 11.26 points on the one occasion it actually forced an early exit.

**Recommendation: do not promote to replace `B-momentum`.** `PROTOCOL.md` §6 as amended requires a
variant to beat its base on median adjusted excess in two consecutive rounds, on windows that differ
between them, by a margin clearing the noise floor. This card's full-set margin has now been measured
twice (+5.62 in round 1, +4.15 in round 2) and both times sits well inside the floor; its new-window-only
margin is negative. **Resist reading this card's strong full-window median as evidence for the 90-day
hypothesis** — the one clean natural experiment this round produced (the MRVL time-stop) shows the
shorter cap costing realised upside relative to the longer one's mark, which argues, if anything,
mildly the other way.
