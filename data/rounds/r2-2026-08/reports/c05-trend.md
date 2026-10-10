# c05-trend — round 2 report: benchmark comparison and trade attribution

## 1. What the card is

`c05-trend` ("Cross-Asset 200dma Trend") is the simplest card in the field: go long a symbol on
`close crosses_above sma(200)`, exit on `close crosses_below sma(200)`, applied independently to
three symbols — `SPY`, `TLT`, `GLD` — with no cross-sectional logic (the engine has none to offer).
Five parameters total against the round's budget of ten: the two `200`-period SMA literals, a 12%
stop, `max_positions = 3`, `position_pct = 0.33`. The memo measured correlation across a 15-symbol
candidate set before choosing this universe and found equities of every flavour (international,
emerging, sector, dividend-tilt) correlate 0.4–0.87 with SPY, while only rates (`TLT`, ~−0.31) and
gold (`GLD`, ~0.05) are genuine diversifiers — the same discipline `c04-riskmanaged` applied to a
four-leg version of the same idea. Pre-registered failure regime: **COVID** — a 200-day average
reacts on the order of weeks, so the memo expected the rule to confirm both the crash and the
snapback only after most of each had already happened. `bear-2022` was named as the window the design
should defend best, on the same slow-signal logic run in reverse.

## 2. Versus SPY, all eight windows

| window | sessions | card | SPY | excess | adj. excess | capital exposure | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `q4-2018` | 65 | −1.98% | −20.05% | **+18.06%** | −0.52% | 7.3% | −2.78% |
| `covid` | 93 | +2.51% | −8.71% | **+11.22%** | +5.37% | 32.9% | −2.80% |
| `bear-2022` | 196 | −3.94% | −25.14% | **+21.20%** | +0.84% | 19.0% | −6.22% |
| `chop-2015` | 260 | −2.47% | −0.04% | **−2.43%** | −2.46% | 23.3% | −6.92% |
| `chop-2011` | 260 | +4.44% | −0.05% | **+4.48%** | +4.46% | 49.3% | −6.02% |
| `bull-2024` | 250 | +0.30% | +14.00% | **−13.69%** | −1.00% | 9.3% | −2.65% |
| `recent` | 249 | +1.71% | +20.62% | **−18.90%** | −2.72% | 21.5% | −3.00% |
| `gfc` | 356 | −1.15% | −56.23% | **+55.08%** | +9.72% | 19.3% | −6.65% |

Adjusted excess is positive in exactly the four windows with a real, sustained trend somewhere in the
book outside SPY (`bear-2022`, `covid`, `chop-2011`, `gfc`) and negative in the other four
(`chop-2015`, `bull-2024`, `recent`, `q4-2018`) — a clean split, examined in §6.

## 3. What moved the number — verified leg by leg

Every leg's contribution sums exactly to the window's total return (`pnl / starting_equity` per trade):

| window | SPY | TLT | GLD | total return |
|---|---:|---:|---:|---:|
| `q4-2018` | −2.60% (3 trades) | +0.55% (2) | +0.07% (1) | −1.98% |
| `covid` | −0.52% (5) | — (0) | +3.03% (1) | +2.51% |
| `bear-2022` | −2.10% (5) | — (0) | −1.84% (8) | −3.94% |
| `chop-2015` | −3.88% (6) | −0.10% (6) | +1.51% (3) | −2.47% |
| `chop-2011` | −1.07% (7) | **+6.31%** (8) | −0.80% (3) | +4.44% |
| `bull-2024` | +2.29% (2) | −1.98% (4) | — (0) | +0.30% |
| `recent` | +3.69% (1) | −1.98% (4) | — (0) | +1.71% |
| `gfc` | −0.47% (5) | **+1.60%** (8) | −2.28% (7) | −1.15% |

**GFC and chop-2011 are earned by TLT, not GLD** — a genuine difference from `c04-riskmanaged`'s GFC
result, worth stating plainly since the two cards share three of four symbols and the same SMA
period. `c04` uses a plain-inequality entry (`close > sma(200)`, re-entering as soon as the condition
holds again after a stop), while `c05` uses a crossing event (`close crosses_above sma(200)`, firing
only at the crossing moment); on GLD in `gfc` the two produce entirely different trade logs — `c04`
holds one 208-bar GLD position from Oct 2007 to Aug 2008 for +19.95%, while `c05`'s crossing-based GLD
entries are seven separate, mostly whipsawed trades in the same window netting −2.28%. The two cards
looking similar on paper (same universe, same 200-day filter, same 12% stop) does not mean they
booked the same trades — the entry semantics matter as much as the symbols.

Material trades: `chop-2011`'s TLT leg is dominated by one position, entered 2011-07-11 and exited
2012-03-15 (172 bars, rule, **+15.35%**, +5.01% of the card's return) — the 2011 debt-ceiling-crisis
flight to duration. `gfc`'s TLT leg carries a 2008-11-05 entry still open at the window's close (83
bars, +9.17%, +2.96%). `covid`'s entire positive result is one GLD trade, entered 2020-03-24 and still
open at the close (68 bars, +8.98%, +3.03% — effectively the whole +2.51% return, since SPY's five
trades in that window net to −0.52%). `bull-2024` and `recent` are each carried by a single open SPY
position (entered 2025-05-13, +9.32%, contributing +2.72% and +3.69% respectively) against TLT
whipsaw losses of −1.98% in both windows.

## 4. Concentration

| window | top-3 share of gross winning P&L | return without top 3 |
|---|---:|---:|
| `q4-2018` | 100% | −2.77% |
| `covid` | 92% | −1.27% |
| `bear-2022` | 100% | −4.55% |
| `chop-2015` | 100% | −6.85% |
| `chop-2011` | 86% | −3.97% |
| `bull-2024` | 100% | −2.42% |
| `recent` | 100% | −1.98% |
| `gfc` | 99% | −7.14% |

Every window's positive result rests almost entirely on one to three trades — structurally expected
from a 3-slot, low-turnover book, not a distinct fragility beyond what the five-parameter design
already discloses.

## 5. Realised versus marked

`chop-2011` +3.23% of +4.44% return, `chop-2015` +4.38% of −2.47%, `bull-2024` +2.72% of +0.30% (the
entire positive return), `covid` +3.46% of +2.51% (more than the entire return), `gfc` +5.49% of
−1.15%, `q4-2018` +0.72% of −1.98%, `recent` +3.69% of +1.71% (more than the entire return) sit in
positions open at each window's close. **`bull-2024`, `covid` and `recent` in particular have realised
results that would be negative or near-zero without the single open mark carrying them** — the card's
apparent gains in these three windows lean heavily on a position not yet closed rather than money
already taken.

## 6. Earning in crises, bleeding in bulls — coherent, with one break

The pattern holds on adjusted excess in four of the eight windows without qualification: `bear-2022`
(+0.84%), `covid` (+5.37%), `chop-2011` (+4.46%, on TLT's 2011 flight-to-quality rather than a crisis
window proper), and `gfc` (+9.72%) are all positive; `bull-2024` (−1.00%), `recent` (−2.72%) and
`chop-2015` (−2.46%) are all negative. The mechanism is coherent, not coincidental: a crossing-based
200dma rule structurally lags a market's early move in either direction, which costs it in a bull
market it must confirm before entering (`bull-2024`, `recent`, both carried mostly by one late SPY
entry) and can pay off in a decline where TLT or GLD are independently trending while SPY is not
(`bear-2022`, `covid`, `gfc`).

**`q4-2018` is the break in the pattern, and it is instructive.** The memo pre-registered COVID — a
fast crash-and-snapback — as the design's worst case, on the logic that the 200dma "will confirm the
crash only after most of the initial drop has already happened." That prediction did not come true:
`covid` was one of the card's best windows (+5.37% adjusted excess), because GLD's late-March 2020
crossing caught the metal's own strong recovery leg. **`q4-2018` — a similarly fast, sharp equity
selloff, never named in the pre-registration — is where the predicted mechanism actually shows up**:
adjusted excess −0.52%, on a book at only 7.3% exposure (SPY down −2.60% from three whipsawed trades,
TLT and GLD each contributing under a point). The failure mode the memo described is real; it simply
attached to the wrong named window. `bear-2022`, named as the design's best case, delivered a modest
positive (+0.84%) rather than a standout one — TLT never triggered a single entry in that window at
all (the bond bear meant TLT's own price never crossed back above its 200dma), so the "defend via
duration" half of the thesis had nothing to work with in the one window built to showcase it.

## 7. The new evidence, and what it changes

`gfc`'s trade log is byte-identical to `r1-2026-08/results/gfc/runs/r1-c05-trend.json`; `covid`,
`bear-2022`, `bull-2024` and `recent` are unchanged recomputations of round 1's own runs. **The only
windows genuinely new to this card are `q4-2018`, `chop-2015` and `chop-2011`** — adjusted excess
−0.52%, −2.46% and +4.46%, median **−0.52%, negative**. The one new window with a large positive
result, `chop-2011`, is carried almost entirely by TLT's single 172-bar debt-ceiling trade (+5.01% of
the card's return on its own) — a real trend, correctly caught, but a single trade rather than a
demonstrated edge across many.

## 8. Verdict

`c05-trend` is the simplest, most legible card in the field, and its behaviour is mechanistically
coherent rather than a lucky pattern-match to the eight-window matrix: it earns where a trend exists
somewhere in a three-symbol book while SPY is flat or falling, and it lags where SPY's own uptrend
must be confirmed after the fact. The one place its own pre-registration missed is informative in
itself — the fast-crash failure mode was real, but it manifested in `q4-2018`, a window the memo never
named, while `covid`, the window it did name, was a clean win. That is a caution about naming failure
regimes by label (`covid`) rather than by mechanism (fast, unconfirmed moves) — the mechanism showed
up on schedule, just wearing a different window's name.

**Recommendation: no promotion.** The card is not currently in `library/candidates/` or `base/`. On
the three windows genuinely new this round, the median adjusted excess is negative (−0.52%), so there
is no fresh case for promotion under `PROTOCOL.md` §6 as amended, which requires the positive median
to rest on windows the previous round did not use. This is a real second data point, not a repeat of
round 1's — the new windows are genuinely new draws — and it argues against advancing the card, though
not for retiring it (it took trades in every window of both rounds). The clearest open question for a
future variant is whether TLT should carry a shorter or crossing-tolerant re-entry rule: `bear-2022`,
the window the memo expected this design to defend best on, produced zero TLT trades at all because
the bond's own price never re-crossed its average during that window.
