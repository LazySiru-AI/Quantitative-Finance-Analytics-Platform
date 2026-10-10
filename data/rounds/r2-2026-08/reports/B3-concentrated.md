# B3-concentrated — 4 Slots at 22%

Eligible in the same 6 of 8 main windows as the rest of the B family (`q4-2018`, `covid`, `bear-2022`,
`chop-2015`, `bull-2024`, `recent`); blocked from `gfc` and `chop-2011` on the NOW-history floor (first
bar 2012-06-29).

## 1. What this card isolates

Identical to `B-momentum` in universe, entry, exit, stop and hold cap. The **only** change: 4
concurrent slots at 22% each (88% maximum deployed) where the base card runs 6 slots at 15% (90%
maximum deployed) — a similar capital ceiling, reached through fewer, larger positions.
`library/README.md` frames the question as whether B's edge concentrates in its best signals or needs
breadth to show up. This card takes the fewest trades of any B-family card in every window it runs —
40 total against the base card's 55 across the same six windows — and the shortfall is not visible as
explicit broker rejections in the trade log: with only 4 slots, a qualifying signal that arrives with
the book full simply generates no order, rather than an order the broker refuses. At 22% × 4 the book
never approaches its own capital ceiling, so this is not a cash-headroom effect; it is this card
silently passing on signals a 6-slot book would have taken.

## 2. Versus SPY, every window

| window | sessions | card return | SPY return | excess | adj. excess | capital exposure | max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|
| `q4-2018` | 65 | -1.31% | -20.05% | **+18.73%** | -1.18% | 0.7% | -1.53% |
| `covid` | 93 | +21.85% | -8.71% | **+30.56%** | +26.76% | 56.4% | -6.03% |
| `bear-2022` | 196 | -10.17% | -25.14% | **+14.97%** | -7.75% | 9.6% | -11.61% |
| `chop-2015` | 260 | +23.26% | -0.04% | **+23.30%** | +23.29% | 65.4% | -14.57% |
| `bull-2024` | 250 | +12.52% | +14.00% | **-1.47%** | +4.50% | 57.3% | -15.83% |
| `recent` | 249 | +40.05% | +20.62% | **+19.43%** | +31.52% | 41.4% | -30.41% |

Median adjusted excess **+13.89%**, hit rate 4 of 6 (66.7%), IQR **25.66 points — the widest in the
entire B family**, wider than `B1-with-target`'s 19.69. This card carries both the family's best
single window (`recent`, +31.52%) and its worst (`bear-2022`, -7.75%, also the deepest drawdown of any
B-family card at -11.61%) — concentration cuts both ways, plainly, in the same six windows.

This card's median leads `B-momentum`'s by **+1.73 points** (13.89 vs 12.16) — narrower than round 1's
+3.40-point lead on four shared windows, and, per `REPORT.md` §5, already flagged as **far inside** the
noise floor `PROTOCOL.md` §7 sets (a 53.9-point spread at σ = 21.2 measured on an identical card
reordered twelve ways). **On the two windows this round adds** (`q4-2018`, `chop-2015`), this card's own
median is +11.06% — positive, but 0.85 points *below* `B-momentum`'s new-window median of +11.91%. Even
this card's narrow full-set lead does not survive when restricted to the round's genuinely new
evidence.

## 3. What moved the number

### `q4-2018` — 1 trade

NOW, 2018-12-14→2018-12-18 (2 bars, rule), -6.12%, -$131, **-1.31% of the card's return** — the whole
of it, sized larger here (22% vs the base card's 15%) so the same loss costs more of the book.

### `covid` — 4 trades, all still open

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| NVDA | 2020-04-07 | _open_ | 58 | open_at_end | +36.86% | +836 | +8.36% |
| AMZN | 2020-04-08 | _open_ | 57 | open_at_end | +36.44% | +774 | +7.74% |
| NFLX | 2020-03-30 | _open_ | 64 | open_at_end | +25.29% | +560 | +5.60% |

A fourth position (sub-1% share) rounds the window's return to +21.85%. With only 4 slots and the same
2020-03-30 earliest entry the whole family shows, this window is **entirely unrealised** — every
material position is still open at the window's close.

### `bear-2022` — 5 trades, zero winners

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| MU | 2022-02-11 | 2022-03-08 | 16 | stop | -16.56% | -363 | -3.63% |
| NVDA | 2022-03-29 | 2022-04-07 | 7 | stop | -14.91% | -330 | -3.30% |
| AVGO | 2022-02-11 | 2022-05-02 | 54 | rule | -5.88% | -129 | -1.29% |

Two smaller trades (GOOGL, MSFT, each just under the 1% materiality threshold) complete the window.
Same five signals, same dates as `B-momentum`, sized larger (22% vs 15%): capital exposure of 9.6% is
the highest of any B-family card in this window, because the same losing book costs more per slot. This
is the family's worst window on every axis — worst adjusted excess, deepest drawdown — a direct
consequence of concentrating a bad signal set into fewer, bigger positions.

### `chop-2015` — 19 trades

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| NFLX | 2015-04-09 | 2015-12-23 | 180 | time | +85.55% | +1,876 | +18.76% |
| GOOGL | 2015-07-14 | 2016-03-31 | 180 | time | +33.61% | +734 | +7.34% |
| MSFT | 2015-10-08 | _open_ | 130 | open_at_end | +19.47% | +426 | +4.26% |
| NVDA | 2016-02-29 | _open_ | 33 | open_at_end | +17.51% | +384 | +3.84% |
| META | 2016-02-02 | 2016-02-09 | 5 | stop | -15.47% | -338 | -3.38% |
| AVGO | 2016-03-03 | _open_ | 30 | open_at_end | +12.84% | +283 | +2.83% |
| NOW | 2015-05-22 | 2015-08-21 | 63 | rule | -11.71% | -256 | -2.56% |
| TSM | 2015-04-27 | 2015-06-09 | 30 | rule | -8.20% | -180 | -1.80% |

Same NFLX and GOOGL time-stop winners as `B-momentum`, sized 22% instead of 15% — NFLX alone is 18.76
points of this card's 23.26% return, against 12.77 points of the base card's. Concentration amplifies
the same winner into a larger share of a smaller book.

### `bull-2024` — 15 trades

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| AVGO | 2025-05-08 | _open_ | 71 | open_at_end | +39.92% | +831 | +8.31% |
| NFLX | 2025-04-22 | _open_ | 83 | open_at_end | +20.69% | +458 | +4.58% |
| MSFT | 2025-05-06 | _open_ | 73 | open_at_end | +16.95% | +366 | +3.66% |
| AVGO | 2024-09-13 | 2025-03-07 | 119 | rule | +12.48% | +271 | +2.71% |
| MRVL | 2024-09-03 | 2024-09-09 | 4 | rule | -9.13% | -191 | -1.91% |
| MSFT | 2024-10-30 | 2024-11-01 | 2 | rule | -6.59% | -144 | -1.44% |
| NOW | 2025-07-29 | 2025-08-01 | 3 | rule | -5.57% | -122 | -1.22% |

The only window where this card's raw excess is negative (-1.47%): fewer slots means missing several
of `B-momentum`'s modest winners entirely (that card takes 19 trades here against this one's 15), and
what's left does not offset the losses as cleanly.

### `recent` — 12 trades, the family's most concentrated result

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of card return |
|---|---|---|---|---|---|---|---|
| MRVL | 2026-03-11 | _open_ | 110 | **open_at_end** | +130.65% | +2,814 | **+28.14%** |
| AMD | 2026-04-09 | _open_ | 90 | **open_at_end** | +107.78% | +2,261 | **+22.61%** |
| AMZN | 2025-11-03 | 2025-11-19 | 12 | stop | -12.47% | -287 | -2.87% |
| AMZN | 2025-12-29 | 2026-02-06 | 27 | rule | -12.70% | -265 | -2.65% |
| TSM | 2026-04-08 | _open_ | 91 | open_at_end | +11.59% | +258 | +2.58% |
| AMD | 2026-01-05 | 2026-02-05 | 22 | stop | -12.42% | -258 | -2.58% |
| META | 2026-07-15 | 2026-07-23 | 6 | rule | -8.41% | -168 | -1.68% |
| META | 2026-02-02 | 2026-02-05 | 3 | rule | -7.24% | -155 | -1.55% |
| NVDA | 2025-12-31 | 2026-03-23 | 55 | rule | -6.59% | -137 | -1.37% |

This is the family's headline window and its headline risk in one place. MRVL and AMD alone are
**50.75 points of this card's 40.05% return** — more than the entire reported number — both **still
open at the window's close**. See §6.

## 4. Concentration

| window | top-3-winner share of gross wins | return without top 3 |
|---|---|---|
| `q4-2018` | n/a — no winning trades | -1.31% (unchanged) |
| `covid` | 99.3% | +0.15% |
| `bear-2022` | n/a — no winning trades | -10.17% (unchanged) |
| `chop-2015` | 78.9% | -7.10% |
| `bull-2024` | 79.3% | -4.03% |
| `recent` | 99.6% | -13.28% |

This card is the most concentrated in the family on every axis that measures it, which is exactly the
mechanical consequence of "fewer, larger positions" — four of six windows show 79% or more of gross
wins in the top three names, and remove them and the card turns negative in three of the four. `covid`
is the extreme: 99.3% of gross wins in the top 3 (of only 4 trades total), and the card's return
without them is essentially zero (+0.15%).

## 5. What moved the number, and the concentration question directly

Concentration is a double-edged mechanism, visible within these same six windows without needing a
second round: `bear-2022`'s -7.75% adjusted excess and -11.61% drawdown are both the worst any B-family
card posted, because the same five losing signals were sized 22% instead of 15%; `recent`'s +31.52%
adjusted excess is the best any B-family card posted, because the same two winning signals were sized
the same way. Both effects are consistent with nothing more than "fewer, larger positions have more of
each individual trade's outcome in them" — true of concentration whether or not the underlying edge is
real, and this round's wide IQR (25.66 points, the widest in the family) is itself evidence that the
mechanism is amplifying variance at least as much as it is amplifying any edge.

## 6. Realised versus marked — this card carries the family's largest exposure to the finding

| window | share of return that is unrealised |
|---|---|
| `q4-2018` | 0% |
| `covid` | +21.85% (of +21.85% — the entire window) |
| `bear-2022` | 0% |
| `chop-2015` | +12.23% (of +23.26%) |
| `bull-2024` | +16.55% (of +12.52% — more than the entire return) |
| `recent` | **+53.54%** (of +40.05% — more than the entire return) |

**`recent` is the sharpest instance of this family's central finding.** This card's largest position,
MRVL (entered 2026-03-11), is marked **+130.65%, contributing +28.14% of the card's entire +40.05%
return — and it is still open at the window's close** (`exit_reason: open_at_end`), a mark against the
last session's close, not money taken. AMD, entered 2026-04-09, is the second-largest at **+107.78%
(+22.61% of the card)**, also still open. Between the two, unrealised marks are 50.75 points against a
total return of 40.05% — the realised book, on its own, is net negative and both of this card's largest
winners have not yet demonstrated anything beyond "currently worth more than they cost." Because this
card holds only 4 slots against the base card's 6, the same MRVL and AMD positions occupy a larger
fraction of this book than of `B-momentum`'s (+28.14%/+22.61% here versus +19.58%/+15.08% there) — narrower
breadth means concentration risk and unrealised-mark risk compound rather than offset. `B2-hold-90`'s
report gives the one real counter-example available in this family: its 90-day cap forces the identical
MRVL position closed at +119.4% a month before this window ends, converting what this card is still
carrying as a paper number into cash.

## 7. Verdict

Median adjusted excess **+13.89%**, the widest IQR in the family (25.66 points), a 4-of-6 hit rate.
Against `B-momentum`, the full-set margin (+1.73 points) is the family's smallest positive lead and the
new-window-only margin (-0.85 points) is negative — under either reading, well inside the ~20-point
noise floor `PROTOCOL.md` §7 sets, and `REPORT.md` §5 already names this exact pairing as a margin the
protocol elsewhere calls meaningless.

**Recommendation: do not promote to replace `B-momentum`.** Neither §6(a)'s new-window-median
requirement nor §6(b)'s noise-floor requirement is met — the new-window margin runs slightly negative,
and even the full-set margin under 2 points is far short of any floor this program has measured. **The
concentration question `library/README.md` poses — does the edge concentrate in the best signals, or
does the strategy need breadth — is not resolved by this round either.** The evidence still points both
ways within the same six windows: `recent` and `chop-2015` look like concentration paying off,
`bear-2022` and `bull-2024` look like it amplifying a bad book, and the persistently wide IQR (25.66
points, wider than round 1's 26.45 only by coincidence of a different window set) is itself evidence
against a clean "concentrates the edge" reading — a real edge concentrated correctly should show a
higher median with comparable, not wider, spread than the base card's own 21.42-point IQR.
