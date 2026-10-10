# H-trend-diversified — competition report

`H-trend-diversified`, "H - Trend, cross-asset: lowest drawdown of the trend family" (discipline:
`trend`), ranked **11th of 18** ranked cards on median `adjusted_excess` (**+3.10%**). It is the
round's cross-asset insurance case, and it is also the clearest worked example in this round's data of
why the capital-exposure correction (DEFECTS.md D2) mattered: its `bear-2022` result falls from an
apparent +17.32% raw-exposure adjusted excess to **+0.71%** once exposure is measured from the trade
log rather than session presence.

## 1. What the card is, and why it could run in only four windows

Identical rule to `C-trend` — `close > sma(200) and ema(20) crosses_above ema(50)` entry, reverse
cross exit, `stop_loss_pct = 0.12`, `max_hold_days = 120` — deliberately unchanged so any difference in
outcome is attributable to the universe, not the rule. Universe: `NVDA MU GDX EWZ FXI INDA DBC` — the
trend engine (NVDA, MU) plus five sleeves (gold miners, Brazil, China, India, broad commodities) chosen
for low pairwise correlation to the core (trailing 2y correlation averaging 0.274 across the round-2
roster, against 0.501 for `C-trend`'s nine-name semis cluster) after the card's own thesis tested and
rejected several "obvious" diversifiers (bonds, utilities, regional banks, biotech, copper, defence) as
flat-to-negative under the identical rule.

**Not eligible for `gfc`**: `eligibility.json` gives `INDA first bar 2012-02-03, needs <=
2006-10-27`. INDA is the binding symbol; its 2012 listing blocks the deepest drawdown in the matrix,
the same structural exclusion `C-trend` suffers from META. It ran the other four main windows —
`covid`, `bear-2022`, `bull-2024`, `recent`.

## 2. Results across eligible windows

| window | trades | corrected return | benchmark | excess | adj. excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| covid | 3 | +10.24% | −8.71% | +18.95% | **+12.19%** | 22.35% | 63.44% | −3.23% | n/a |
| bear-2022 | 6 | −3.11% | −25.14% | +22.03% | **+0.69%** | 15.10% | 81.63% | −7.23% | 20.00% |
| bull-2024 | 13 | +11.13% | +14.00% | −2.87% | **+5.51%** | 40.12% | 93.60% | −9.18% | 33.33% |
| recent | 14 | −3.65% | +20.62% | −24.27% | **−8.75%** | 24.73% | 92.77% | −7.49% | 9.09% |

**Median adjusted excess +3.10% (midpoint of +0.69% and +5.51%), hit rate 75% (3 of 4 positive), IQR
9.65 points, 36 trades total.** `covid`'s win rate is `n/a`: all three of its trades were still open
at the window boundary (`open_at_end`), so none had resolved to a win/loss outcome yet.

## 3. The exposure correction, verified

**Confirmed from the trade log.** `bear-2022`'s six trades:

| symbol | entry→exit | bars held | notional (entry × qty) | exit reason | return |
|---|---|---:|---:|---|---:|
| MU | 2022-02-11→2022-03-08 | 16 | $1,552.61 | stop | −16.56% |
| NVDA | 2022-03-29→2022-04-07 | 7 | $1,607.76 | stop | −14.91% |
| EWZ | 2022-06-02→2022-06-10 | 6 | $1,595.70 | rule | −14.47% |
| **DBC** | **2022-01-03→2022-06-27** | **120** | **$1,575.48** | **time** | **+33.14%** |
| EWZ | 2022-08-16→2022-10-03 | 33 | $1,559.67 | rule | −1.04% |
| EWZ | 2022-10-04→open | 6 | $1,626.31 | open_at_end | −5.48% |

Session-presence `exposure` for this window is **81.63%** — the fraction of the window's 196 sessions
on which *any* position was open. But summing `quantity × entry_price × bars_held` and dividing by
`sessions × starting_equity` gives **capital_exposure = 15.10%**, because one position — DBC, a single
~$1,575 commodity-ETF stake (15.8% of starting equity) — was held for 120 of the window's 196 sessions
(the full `max_hold_days` cap, exiting on the time stop) and, being the only position open across large
stretches of the window, drove the session-presence figure to 82% almost single-handedly: DBC alone
accounts for `120 / 196 = 61.2%` of all sessions with any position open, and its $1,575 notional is
9.65 points of the 15.10% total capital exposure by itself. The "82% exposure" the raw field reports
describes one small, long-held commodity position, not a filled six- or seven-name book.

Recomputing `adjusted_excess` with each exposure figure: `corrected_return − session_exposure ×
benchmark_return` = −0.0311 − (0.8163 × −0.2514) = **+17.41%**; `corrected_return − capital_exposure ×
benchmark_return` = −0.0311 − (0.1510 × −0.2514) = **+0.69%**. The gap — roughly 16.7 points, from a
headline-grade result to a near-breakeven one — is produced entirely by which exposure figure is used,
not by any change to the trades themselves. This is the same mechanism DEFECTS.md D2 documents for
`c04-riskmanaged`'s `gfc` result (+55.45% → +25.45%), reproduced here on a smaller book: a thin, long-
held position that happens to be the only thing open across many sessions manufactures a session-
presence exposure figure far above the capital genuinely at risk, and any calculation that multiplies
that figure by a large-magnitude benchmark return (here, `bear-2022`'s −25.14%) inflates the adjusted
result by exactly the amount the exposure figure is overstated.

## 4. Trade-level detail (all windows)

**Exit-reason distribution:**

| window | rule | stop | time | open_at_end |
|---|---:|---:|---:|---:|
| covid | 0 | 0 | 0 | 3 |
| bear-2022 | 2 | 2 | 1 | 1 |
| bull-2024 | 7 | 1 | 1 | 4 |
| recent | 11 | 0 | 0 | 3 |

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| covid | NVDA, 2020-04-07→open, +36.86% | MU, 2020-06-04→open, +5.40% |
| bear-2022 | DBC, 2022-01-03→2022-06-27, +33.14% (time) | MU, 2022-02-11→2022-03-08, −16.56% (stop) |
| bull-2024 | GDX, 2025-01-31→2025-07-25, +33.76% (open at report time) | MU, 2024-10-17→2024-11-18, −13.38% (stop) |
| recent | DBC, 2026-01-13→2026-06-18, +17.80% (rule) | NVDA, 2026-07-16→2026-07-29, −6.91% (rule) |

Every trade in `covid` was still open at the window boundary — even the "worst" (MU, +5.40%) was
profitable, unusual for this report's six cards but consistent with a genuinely favourable regime for
this rule. DBC produced the best trade in two of four windows (`bear-2022`, `recent`) — the sleeve the
card added specifically to decorrelate from the NVDA/MU trend engine earned its keep in exactly the
windows where the core semis trade struggled (`bear-2022`: NVDA and MU both stopped out; `recent`: NVDA
lost money on its only trade).

**3 stop-outs across all four windows, nominal `stop_loss_pct = 0.12`:** MU (bear-2022, 16 bars,
−16.56%), NVDA (bear-2022, 7 bars, −14.91%), MU (bull-2024, 22 bars, −13.38%) — the same three trades
`C-trend` recorded on its shared NVDA/MU core, since both cards run the identical rule on overlapping
symbols. Mean realised stop-out loss **−14.95%** against the nominal 12% level, a gap of **2.95
percentage points**, in line with the same previous-close mechanic documented for `C-trend` above.

## 5. Rankable, and where it stands

Yes. Four of five main windows run (only `gfc` is blocked, by INDA's 2012 first bar), clearing the
gate. Ranked 11th of 18, below `C-trend` (9th, +4.99%) despite `H`'s lower per-trade concentration —
consistent with the card's own thesis, which frames diversification explicitly as "spending some
expected return to buy a reduction in simultaneous-drawdown risk": its measured design-window per-trade
expectancy (9.7%) trails the concentrated book's (12.7%) on the identical rule and sample, and that
trade-off shows up again here in the median-adjusted-excess comparison.

## 6. Recommendation

**Retain as a candidate; do not promote to base.** PROTOCOL.md §6's two-consecutive-round bar applies
here as it does to `C-trend`: one positive-median round (+3.10%) is not sufficient on its own. The
more consequential finding for this round is not the ranking position but the exposure correction
itself — `bear-2022`'s near-total swing from +17.32% to +0.69% is the clean worked example this
program's DEFECTS.md D2 entry needed, and it should be cited directly whenever the report or the
orchestrator explains why `capital_exposure` replaced the runner's raw `exposure` field in the ranking
key. Carry `H-trend-diversified` into round 2 unchanged; its correlation-driven design (five sleeves
tested and pared to the least-correlated) is exactly the kind of pre-registered, non-fitted choice the
program is built to reward if it holds up on a second window set.
