# Round 3 — does a wider universe change the result?

**Answer: no, not measurably.** The store grew from 173 symbols to 633, the stocks available grew
from about 60 to 513, and the number of symbols reaching the GFC grew from 86 to 380. Across a
controlled arm and a six-card open arm, none of that produced a field better than round 2's, and the
single best new card in the round used **no new symbol at all**.

Ten cards over eight windows, 78 run files, every window reconciled against attempts.

## 1. The controlled arm

`B-wide` and `C-wide` are `B-momentum` and `C-trend` with every field asserted byte-identical at
build time except the universe, which is a pre-registered mechanical draw from the wider store — top
N index constituents by median dollar volume, restricted to history back to 2004, ranked once and
frozen.

Median excess over the windows each pair shares:

| pair | base | wide | delta |
|---|---|---|---|
| `B-momentum` → `B-wide` | +18.8% | +14.5% | **−4.3 pts** |
| `C-trend` → `C-wide` | +14.6% | +13.8% | **−0.8 pts** |
| `C-trend` → `c17-defensive-trend-wide` | +14.6% | +5.6% | **−9.0 pts** |

The third row is a bonus comparison the round did not plan: `c17`'s analyst independently kept
C-trend's exact entry rule and changed only the universe, to a twelve-name defensive book.

**Every one of these margins is inside the noise floor.** `PROTOCOL.md` §7 records that re-running a
single identical card under twelve different universe *orderings* moved its three-year return across
a 53.9-point spread with σ = 21.2 points. A −4.3, −0.8 or −9.0 point difference is well inside that
band. The correct reading is **no detectable effect**, not "wider is worse" — and stating it the
second way would be exactly the noise-laundering the protocol was written to prevent.

## 2. The open arm

Six analyst-designed cards, free choice across the whole store, one per discipline.

| | round 2 field | round 3 open arm |
|---|---|---|
| cards | 26 | 6 |
| median of median excess | +5.7% | +6.2% |
| best card's median | **+19.3%** (`B4-tight-stop`) | +10.4% (`c13-breakout-wide`) |

The centre of the distribution is unchanged and the best card is materially worse. Six analysts
searching a 513-name space did not out-produce round 2's field searching a 60-name one.

## 3. The GFC numbers are an artifact, and they are an artifact twice over

Raw excess in the `gfc` window looks spectacular for the whole field — every card beats SPY's −56.2%
by between 17 and 70 points. Almost none of it survives inspection.

| card | return | excess | capital exposure | **adjusted excess** | trades |
|---|---|---|---|---|---|
| `c15-volatility-wide` | +13.3% | +69.6% | 9.0% | **+18.4%** | 39 |
| `c12-meanrev-wide` | −0.9% | +55.3% | **0.6%** | **−0.5%** | **1** |
| `c14-riskmanaged-wide` | −3.4% | +52.8% | 23.8% | **+10.0%** | 20 |
| `C-wide` | −10.1% | +46.1% | 15.1% | −1.6% | 11 |
| `B-wide` | −16.1% | +40.2% | 13.5% | −8.5% | 15 |
| `c17-defensive-trend-wide` | −17.1% | +39.2% | 28.1% | −1.3% | 22 |
| `c13-breakout-wide` | −24.9% | +31.3% | 23.7% | −11.6% | 16 |
| `c16-dispersion-wide` | −39.5% | +16.8% | 53.1% | −9.6% | 55 |

**First artifact: cash.** `c12-meanrev-wide` posts a +55.3% excess on **one trade** and 0.6% capital
exposure. It did not beat the crisis; it declined to attend. Correct for exposure and its edge is
−0.5%. Six of the eight cards go to roughly zero or negative under the same correction. This is
`DEFECTS.md` D2 in live action, and it is why the ranking below uses adjusted excess.

**Second artifact: survivorship.** The two cards that *do* survive the exposure correction are the
two whose universes are most exposed to it. `c15` trades 2008's financials — C, BAC, AIG, WFC, GS,
MS, COF, F. Those names lost 90-99% and lived. Lehman Brothers, Bear Stearns, Washington Mutual and
Countrywide are not in the universe, because they are not in today's index, because they died. A
dip-buying strategy that can only buy the banks that survived is running an experiment the 2008
investor could not have run.

The cleanest evidence is the analyst's own prediction. `c15`'s memo named **`gfc` as its worst
window**, reasoning that these banks had genuinely impaired balance sheets and dead-cat bounces
would be run over. That reasoning is correct about the world. `gfc` came back as its **best** window,
+69.6% raw and +18.4% adjusted, while its actual worst was `recent` at −16.9%.

The analyst was right and the backtest was wrong. Nothing in this project has demonstrated
survivorship more plainly, and it is worth keeping precisely because it was a prediction made in
advance rather than a caveat added afterwards.

## 4. Ranking on adjusted excess

| rank | card | median | worst | hit | windows |
|---|---|---|---|---|---|
| 1 | `B-momentum` | **+12.2%** | −5.1% | 67% | 6 |
| 2 | `C-trend` | +5.0% | −7.3% | 50% | 6 |
| 3 | `c14-riskmanaged-wide` | +2.3% | **−1.0%** | **75%** | 8 |
| 4 | `c13-breakout-wide` | +1.4% | −17.0% | 50% | 8 |
| 5 | `B-wide` | +0.7% | −8.5% | 62% | 8 |
| 6 | `C-wide` | +0.6% | −5.8% | 50% | 8 |
| 7 | `c16-dispersion-wide` | +0.3% | −9.6% | 62% | 8 |
| 8 | `c12-meanrev-wide` | −0.1% | −1.9% | 38% | 8 |
| 9 | `c17-defensive-trend-wide` | −0.6% | −7.8% | 38% | 8 |
| 10 | `c15-volatility-wide` | −1.2% | −20.8% | 38% | 8 |

**Pareto frontier: `B-momentum` and `c14-riskmanaged-wide`.**

Read the incumbents' rank with care: they ran **six** windows, not eight. `B-momentum` and `C-trend`
hold META (2012) and AVGO (2009) and are structurally ineligible for `gfc` and `chop-2011` — the two
hardest windows in the matrix. Their medians are computed over an easier subset, and are flattered by
an unknown amount relative to the eight-window cards below them. That is not a small caveat; it may
be the whole gap.

## 5. The finding that actually matters

`c14-riskmanaged-wide` is the round's one genuinely useful new card — best worst-window, best hit
rate, on the Pareto frontier, and the only new card whose crisis performance survives exposure
correction with real participation behind it (23.8% exposure, 20 trades).

Its universe is **TLT, IEF, GLD, LQD**.

All four were in the store before this round. Not one of the 460 symbols added by the universe
expansion appears in it. The best idea of the round came from a cross-asset argument, not from
breadth — and the analyst arrived at it by asking what hedges an equity book, which is a question the
old 173-symbol store could already answer.

## 6. What changed, and what to do about it

- **The library is unchanged.** No card met §6's bar. `c14` is a candidate on one round's evidence and
  is promoted to `candidates/` pending a second round on new windows.
- **The universe expansion is kept.** It cost nothing, it lets 380 symbols reach the GFC instead of
  86, and its value is optionality for future rounds rather than a result in this one. But it is now
  measured rather than assumed: *this* round says breadth alone bought nothing.
- **Determinism verified.** `B-momentum` and `C-trend` reproduced their round-2 numbers to the last
  decimal across all six shared windows, confirming the store growing from 177 to 633 symbols
  perturbed no existing result.
- **Adjusted excess should be the headline metric, not raw excess.** Round 3 is the third time raw
  excess has told a flattering story that exposure correction dissolved. The leaderboard at
  `/competition` ranks on plain excess by default and should be read with the per-window capital
  exposure column beside it.

## 7. What this round cannot settle

No calendar time passed between rounds 2 and 3, so the design cutoff did not advance and no genuinely
unseen data exists. This round widened the choice set; it did not add data. It also ran six new cards
against a matrix eight windows wide, which is a small sample against a noise floor of ±21 points —
the "no detectable effect" conclusion is a statement about what this round could resolve, not proof
that breadth is worthless.

The one thing it does establish firmly is negative and useful: **the thin universe was not what was
holding the field back.**

---

## Restated 2026-08-21 — `DEFECTS.md` D4

Every run file in this round was **re-run and overwritten** after `DEFECTS.md` D4 was fixed. Rule
evaluation previously read a 400-day trailing window, an undocumented default parameter value, which
left recursive indicators (`ema`, Wilder `rsi`) carrying a seed error of roughly 1.8e-5; it now reads
full history.

**Across all three rounds, 330 runs were restated and 3 results moved** — the same card in the same
window in each round, `C-trend` in `covid`, by **0.065 percentage points** of starting equity. One
signal flipped: `TSM` on 2020-05-14, where `ema(20)` and `ema(50)` were crossing and 1.8e-5 decided
which was above the other. `C-trend`'s covid excess moves from +24.5% to +24.6%.

**No ranking, promotion, frontier or conclusion in this report changes.** The figures below are the
restated ones. The scoring aggregates (`tournament*.json`) were regenerated at the same time so they
cannot describe the pre-restatement field.
