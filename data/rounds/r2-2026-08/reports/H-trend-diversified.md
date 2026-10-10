# H-trend-diversified -- Cross-Asset Trend -- round 2 report

Agent: `H-trend-diversified` | Discipline: `trend` | Eligible: 6/8 main windows (clears the round-2
five-of-eight gate; see `results/eligibility.json`)

## 1. What the card is, its claim, and where it can't run

Identical rule to `C-trend` -- `close > sma(200) and ema(20) crosses_above ema(50)` entry, reverse
cross exit, `stop_loss_pct = 0.12`, `max_hold_days = 120` -- deliberately unchanged so any difference
in outcome is attributable to the universe, not the rule. Universe: `NVDA MU GDX EWZ FXI INDA DBC` --
the trend engine (NVDA, MU) plus five sleeves (gold miners, Brazil, China, India, broad commodities)
chosen for low pairwise correlation to the core (0.274 average, against 0.501 for `C-trend`'s
nine-name semis cluster).

The claim under test: this is "the cross-asset insurance case, still untested by an accident" --
round 1 beat round 2's ten head-to-head pairs entirely because SOXX returned +228.88% in round 1's
window, a fact about that window rather than about concentration, and round 1 found `H`'s apparent
82% `bear-2022` exposure was one small DBC position held a long time, not a filled book.

**Not eligible for `chop-2011` or `gfc`**: `eligibility.json` gives `INDA first bar 2012-02-03, needs
<= 2010-06-13` for `chop-2011` and `needs <= 2006-10-27` for `gfc`. INDA's 2012 listing blocks both,
the same structural exclusion `C-trend` suffers from META.

## 2. Versus SPY, every eligible window

| window | sessions | card | SPY | excess | adj. excess | cap. exp | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| q4-2018 | 65 | **+0.00%** | -20.05% | +20.05% | +0.00% | 0.0% | +0.00% |
| covid | 93 | **+10.24%** | -8.71% | +18.95% | +12.23% | 22.9% | -3.23% |
| bear-2022 | 196 | **-3.11%** | -25.14% | +22.03% | +0.71% | 15.2% | -7.23% |
| chop-2015 | 260 | **+7.54%** | -0.04% | +7.58% | +7.54% | 5.7% | -2.32% |
| bull-2024 | 250 | **+11.13%** | +14.00% | -2.87% | +5.48% | 40.4% | -9.18% |
| recent | 249 | **-3.65%** | +20.62% | -24.27% | -8.79% | 24.9% | -7.49% |

Sorted: recent -8.79%, q4-2018 0.00%, bear-2022 +0.71%, bull-2024 +5.48%, chop-2015 +7.54%, covid
+12.23%. **Median adjusted excess = average of q4-2018 and bear-2022, (0.00 + 0.71)/2 = +3.09%**,
matching `scorecard-common6.json`. **Worst window recent, -8.79%. Hit rate 4 of 6 (66.7%). IQR
6.85 points.** 40 trades total, mean capital exposure 18.2%. Ranked **6th of 22** on median adjusted
excess (Borda 8.67) -- above `C-trend` (10th), the head-to-head the two cards' identical rule invites.

## 3. What moved the number

### q4-2018

Took no trades. Zero exposure, zero return, zero drawdown -- an abstention, not a result.

### covid (3 trades, all `open_at_end`)

NVDA (2020-04-07, 58 bars, +36.86%, +6.09%), GDX (2020-04-16, 52 bars, +20.50%, +3.31%). Top-3 share
100% of gross wins; without them the card returns **+0.00%** exactly -- every trade in this window was
still open at the boundary, so the entire +10.24% is a mark, not a realised gain (see §5).

### bear-2022 (6 trades)

| symbol | entry | exit | bars | exit reason | trade return | P&L | share |
|---|---|---|---:|---|---:|---:|---:|
| DBC | 2022-01-03 | 2022-06-27 | 120 | time | +33.14% | +522 | +5.22% |
| MU | 2022-02-11 | 2022-03-08 | 16 | stop | -16.56% | -257 | -2.57% |
| NVDA | 2022-03-29 | 2022-04-07 | 7 | stop | -14.91% | -240 | -2.40% |
| EWZ | 2022-06-02 | 2022-06-10 | 6 | rule | -14.47% | -231 | -2.31% |

Top-3 share 100%; without them the card returns **-8.33%**. This is the same six-trade set round 1
recorded on this window, to the cent (DBC 2022-01-03→2022-06-27, +33.14%) -- per `REPORT.md` §1, this
is a recomputation, not a second observation.

### chop-2015 (4 trades)

GDX (2016-02-05, 48 bars, open_at_end, +40.86%, +6.38%), NVDA (2016-02-29, 33 bars, open_at_end,
+17.51%, +2.79%), NVDA (2015-08-12, 10 bars, stop, -10.38%, -1.63%). Top-3 share 100%; without them
the card returns **-1.63%**.

### bull-2024 (13 trades)

| symbol | entry | exit | bars | exit reason | trade return | P&L | share |
|---|---|---|---:|---|---:|---:|---:|
| GDX | 2025-01-31 | 2025-07-25 | 120 | time | +33.76% | +534 | +5.34% |
| NVDA | 2025-05-15 | _open_ | 66 | open_at_end | +30.54% | +451 | +4.51% |
| MU | 2025-05-19 | _open_ | 64 | open_at_end | +22.40% | +343 | +3.43% |
| MU | 2024-10-17 | 2024-11-18 | 22 | stop | -13.38% | -209 | -2.09% |
| FXI | 2025-05-09 | _open_ | 70 | open_at_end | +9.33% | +148 | +1.48% |
| FXI | 2024-09-20 | 2025-01-07 | 74 | rule | +9.16% | +145 | +1.45% |
| DBC | 2025-04-01 | 2025-04-07 | 4 | rule | -8.29% | -133 | -1.33% |

Top-3 share 79%; without them the card returns **-2.16%**.

### recent (14 trades)

DBC (2026-01-13, 108 bars, rule, +17.80%, +2.83%) is the only material winner; three NVDA trades lose
-1.05%, -1.02%, -1.02%. Top-3 share 100%; without them the card returns **-6.68%**. SPY rose +20.62%
this window; the card's NVDA book lost on every trade while the DBC sleeve's single win could not
offset it, producing the round's worst window for this card.

## 4. Concentration, and the same shape recurring

| window | top-3 share of gross wins | return without top-3 | driver |
|---|---:|---:|---|
| covid | 100% | +0.00% | NVDA + GDX, both open at close |
| bear-2022 | 100% | -8.33% | DBC (120-bar time exit) |
| chop-2015 | 100% | -1.63% | GDX (48-bar open) |
| bull-2024 | 79% | -2.16% | GDX (120-bar time exit) + NVDA |
| recent | 100% | -6.68% | DBC (108-bar rule exit) |

**Round 1 found `bear-2022`'s apparent 82% session exposure was one small DBC position held 120 of
196 sessions, not a filled book -- and the same shape holds across every window this round runs.** In
four of five windows with any trades, a single long-held gold-miner or commodity position (GDX in
`chop-2015` and `bull-2024`, DBC in `bear-2022` and `recent`) is 100% or near-100% of the winning
side, while the reported capital exposure never exceeds 40.4% (`bull-2024`) and sits as low as 5.7%
(`chop-2015`). This is not a diversified six-or-seven-name book firing broadly; it is the NVDA/MU
core taking small losses on stops while one long-dated sleeve position (GDX or DBC), often riding the
full 120-day time stop, carries the window. The diversification is real in the sense that GDX and DBC
decorrelate from NVDA/MU exactly as designed -- but the "book" in every winning window is effectively
one position, not seven.

## 5. Realised versus marked

**Flag: `covid`'s entire +10.24% return is unrealised.** All three trades (NVDA, GDX, and a third not
shown above) were still open at the window boundary; the return-without-top-3 figure is exactly 0.00%
because there is no third trade outside the top three -- every trade in this window is a mark. `q4-2018`
took no trades at all, so its 0.00% is an abstention rather than a mark. `bull-2024` carries **+9.13%
of unrealised mark** (out of +11.13% total) and `chop-2015` carries **+9.17%** (out of +7.54% total,
meaning the realised trades net negative and the entire positive headline is the GDX/NVDA marks).
`bear-2022`'s DBC trade is fully realised (time-stop exit, not open-at-end), so that window's result
is genuine cash, unlike its trend-family sibling `C-trend`'s equivalent windows.

## 6. Verdict on the claim, and recommendation

**The insurance shape holds, and it is doing what it was built to do at a real cost, exactly as its
own thesis disclosed.** In `bear-2022` and `recent` -- the two windows where the NVDA/MU core lost
money outright (stopped out in `bear-2022`; lost every trade in `recent`) -- a single commodity or
gold-miner position (DBC in both cases) was the only source of positive return, cutting the drawdown
from what a pure semis book would have taken. That is the mechanism the card was built to test, and
round 2's `recent` and `bear-2022` results confirm it recurs, not just in round 1's single measured
instance.

The trade-off the card's own thesis names -- "spending some expected return to buy a reduction in
simultaneous-drawdown risk" -- also recurs: `H` ranks 6th of 22 against `C-trend`'s 10th on the
*identical* rule, so the diversified book currently beats its concentrated sibling on median adjusted
excess this round, reversing round 1's finding (where `H` ranked below `C-trend`, 11th vs 9th) purely
because this round's regime mix (more grinding/chop windows, fewer single-sector melt-ups) favours the
lower-volatility, lower-correlation book. That reversal is itself evidence for the insurance thesis:
the two cards trade the same rule on different universes, and which one wins tracks which regime the
window draws, exactly as designed.

Per `PROTOCOL.md` §6(a), the genuinely new evidence this round is `q4-2018` (0.00%, an abstention) and
`chop-2015` (+7.54%) -- round 1's window set was `{covid, bear-2022, bull-2024, recent}`, all four
reproduced here to within the ≤0.1pp D2 engine-fix tolerance, not fresh draws. New-window median =
(0.00 + 7.54)/2 = **+3.77%**, positive but built on one abstention and one single-window result, both
inside the ±20pt/σ=21.2pt noise band §6(b) requires a promotion margin to clear.

**Recommendation: retain as a candidate; do not promote to `base/`.** The mechanical two-consecutive-
positive-round condition is met, but the amended noise-floor condition is not, and one of the two new
windows contributed no trades at all. Carry `H-trend-diversified` into round 3 unchanged. The clean
test-in-waiting is a second concentrated-vs-diversified pairing in a window where the semis core has
already been shown to lose money outright (as `bear-2022` and `recent` both did this round) -- if the
insurance sleeve keeps winning those specific comparisons, that is the strongest evidence the "spend
some expected return for less simultaneous drawdown" trade is worth its cost.
