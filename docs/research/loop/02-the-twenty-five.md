# The twenty-five: dossiers for every pending paper-desk seat request

Source: the frozen snapshot at `scratchpad/freeze-20260826T0900Z/`, taken 2026-08-26 09:00Z. Read-only analysis; nothing in this document ran a backtest, started the loop, or touched `data/` or `roster_overlay.json`. Every figure below was either copied verbatim from a snapshot file or derived by a plain arithmetic operation (median, fraction, percentile, Jaccard overlap) over rows another module already owns (`ledger.jsonl`, generation `OUTCOME.json` standings, `promotions.jsonl`). The script that produced this document and its companion `dossiers.json` is deterministic: re-run against the same snapshot, it reproduces the same file byte-for-byte.

**Scope.** `pending_seats.json` holds 25 seat requests. 22 carry `status: "approved"` -- these were auto-seated onto the simulated paper desk at 09:00:49 on 2026-08-26 without a human reading anything about them, and they are the ones the owner has decided to pull back to a review shelf. 3 still carry `status: "pending"` and have never been decided at all. This document treats all 25 identically: every one gets a full dossier and a recommendation, because "already on the desk without review" is not evidence of quality any more than "still waiting" is evidence against it.

> **Since this was written, the migration has run.** `tools/migrate_seat_pipeline.py --apply` moved all 22 `"approved"` rows to `"shelved"` and removed their genome ids from `roster_overlay.json`, so the simulated desk is back to its human-selected roster (5 trading, 2 savings, 1 Roth) and the overlay is empty. The queue on disk now reads 22 `shelved` / 3 `pending`. `"approved"` is no longer a legal `SeatStatus` at all — the five values are `pending`, `shelved`, `seated`, `rejected`, `retired`, and only `seated` writes the roster. Backups of both files were written alongside them before the change. The dossiers below are unaffected: they describe the cards, not their queue state.

**Generation records.** `generations/` holds 233 directories (`gen0001`..`gen0028`, a gap, then `gen1673`..`gen1877`; the gap is the 1,644-generation `OSError` hot-fail streak described in the last repo commit, since fixed). Of those 233, **231 carry a valid, non-empty `OUTCOME.json`.** `gen1673` -- the first attempt after the gap -- is a genuine 0-byte file with no `PLAN.md` either: still a failure, not a recovery. `gen1849` has a `PLAN.md` but no `OUTCOME.json` at all: a generation that was planned and never finished (or never reported). Neither is counted as a scored generation anywhere in this document, and neither contributes an evidence row to any of the 25 dossiers below. Quoting "1,877 generations" or even "233 generations" as a search effort would overstate it; the honest count of generations that actually produced a scored result is **231**.

## The number that must not be softened

Reproduced independently here from all **2,374** rows in `ledger.jsonl` -- every candidate this program has ever scored, including pure random ones, not just these 25:

- Selection-window median excess, median of medians across all rows: **+5.65pp**, positive in **82.0%** of rows.
- Holdout median excess, median across all rows: **+15.02pp**, positive in **94.3%** of rows.

These match the figures already on record for this program to four significant figures. **A card reporting a positive holdout median, even a double-digit one, is not by itself evidence of an edge.** Just over 19 in 20 candidates ever run clear that bar, including candidates built from random parameters with no thesis at all. Every dossier below states this caution by name (`holdout-does-not-discriminate`) wherever it applies -- and it applies to all 25 of them.

## What these 25 have in common

**25 of 25 cards run the exact same rule, character for character.** Every entry rule in this batch parses to the identical shape (`backend/app/rules/grammar.py` defines the grammar; the check below is a literal string match against every card's stored `entry`/`exit` text):

```
entry: close > sma(N) and ema(fast) crosses_above ema(slow)
exit:  ema(fast) crosses_below ema(slow)
```

The only things that differ from card to card are the three numbers (`N`, `fast`, `slow`), the ticker universe, the stop/target/hold/sizing block, and a `discipline` label (13 × pairs-rotation, 5 × mean-reversion, 4 × breakout, 2 × momentum, 1 × trend) that this batch's own lineage data shows does not track any real change in the rule -- see the `g1815-d05786e4c611` / `g1823-e2a3d5060b09` pair in the dossiers below, where a "mutation" changed the discipline label from `breakout` to `mean-reversion` and left every single numeric trait, the universe, and the thesis text byte-identical.

**Ticker concentration.** 24 distinct tickers appear across all 25 universes combined. The top ten by how many cards trade them:

| ticker | appears in |
|---|---|
| LRCX | 20 / 25 cards |
| INTU | 19 / 25 cards |
| CSCO | 19 / 25 cards |
| AMAT | 19 / 25 cards |
| KLAC | 19 / 25 cards |
| AAPL | 18 / 25 cards |
| CRM | 18 / 25 cards |
| ADBE | 17 / 25 cards |
| TSM | 5 / 25 cards |
| AMZN | 5 / 25 cards |

**145 of the 300 possible pairs among these 25 (48%) are close relatives** -- sharing a parent genome, or trading a universe with 60% or more ticker overlap. 93 of those 145 close pairs (64%) trade the *identical* universe (Jaccard = 1.0).

**Twenty of the 25 `roth`-purpose cards trace back through one unbroken chain of mutations and crossovers to a random ancestor pair at generation 1679** (`g1679-12eaf5c6bd56` and `g1679-944a6f327542`), walking forward to generation 1823 -- 14 generations of lineage depth at the far end, almost entirely on the same eight tickers (AMAT, CRM, INTU, AAPL, LRCX, KLAC, ADBE, CSCO), with the `discipline` label flipping between `breakout`, `mean-reversion`, `pairs-rotation` and `momentum` along the way while the entry/exit rule shape never changes. Separately, the five `trading`-purpose cards form their own lineage on a semiconductor-heavy 11-12 ticker universe (AMD, TXN, TSM, INTC, MU, SOXX, NVDA, MSFT, ORCL, NFLX, AMZN, QCOM) -- same rule shape again.

**Read plainly: this is not 25 independent ideas clearing a bar. It is two lineages -- one per purpose -- re-walking the same EMA-crossover-inside-SMA-regime rule over largely the same twenty-odd tickers, with cosmetic re-labeling along the way, each of the 25 stopping points filed as its own seat request.** The comparison table below is sorted by how far each card's best result cleared the 21.2pp noise floor, which is close to the only axis on which these 25 meaningfully differ from each other -- the strategy underneath barely differs at all.

## Comparison table

Sorted by margin over the 21.2pp noise floor (best selection-window median excess across every generation the card was scored in, minus the floor) -- descending, so the most-differentiated cards are at the top and the two cards that barely clear the floor are at the bottom. "Percentile (purpose, all-time)" is this card's qualifying selection median ranked against every ledger row of the same purpose (roth: n=1,206; trading: n=1,168) -- **a high percentile here still sits inside a distribution whose median-of-medians is only +5.65pp**, so a 95th-percentile card is not the same thing as a proven edge; it is a card that is unusually far from a low bar.

| # | card | discipline | purpose | best selection median | latest holdout median | latest q | latest trades | gens scored | window sets | percentile (purpose) | margin over floor | ≥60% overlap with seated | recommendation |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | [`g009·30c4`](#card-g009-30c484221799) | trend | trading | +30.51pp | +20.32pp | 0.000002 | 110 | 3 | 3 | 99.9% | +9.31pp | 0 card(s) | **shelve** |
| 2 | [`g1809·145d`](#card-g1809-145d2d5dbfeb) | pairs-rotation | trading | +25.72pp | +22.13pp | 0.000000 | 149 | 8 | 6 | 99.7% | +4.52pp | 3 card(s) | **shelve** |
| 3 | [`g1769·3491`](#card-g1769-349119b209d7) | pairs-rotation | trading | +25.04pp | +22.05pp | 0.000003 | 142 | 11 | 6 | 98.5% | +3.84pp | 3 card(s) | **shelve** |
| 4 | [`g1725·0a9f`](#card-g1725-0a9fcd74b740) | pairs-rotation | trading | +25.04pp | +22.05pp | 0.000001 | 166 | 13 | 6 | 98.5% | +3.84pp | 3 card(s) | **shelve** |
| 5 | [`g1859·fd7c`](#card-g1859-fd7c2c196f35) | mean-reversion | roth | +24.65pp | +14.88pp | 0.005 | 46 | 3 | 3 | 99.9% | +3.45pp | 0 card(s) | **shelve** |
| 6 | [`g1679·944a`](#card-g1679-944a6f327542) | pairs-rotation | roth | +24.26pp | +11.56pp | 0.009 | 44 | 4 | 4 | 99.7% | +3.06pp | 0 card(s) | **shelve** |
| 7 | [`g1855·2ff5`](#card-g1855-2ff5b8e319dd) | pairs-rotation | roth | +23.34pp | +17.68pp | 0.000045 | 80 | 4 | 4 | 99.3% | +2.14pp | 16 card(s) | **shelve** |
| 8 | [`g1755·c30d`](#card-g1755-c30de399e7f4) | pairs-rotation | roth | +23.31pp | +17.58pp | 0.009 | 81 | 2 | 2 | 98.9% | +2.11pp | 15 card(s) | **shelve** |
| 9 | [`g1755·60b2`](#card-g1755-60b22dc5f630) | pairs-rotation | roth | +23.31pp | +17.32pp | 0.014 | 65 | 3 | 3 | 98.9% | +2.11pp | 15 card(s) | **shelve** |
| 10 | [`g1855·4a8d`](#card-g1855-4a8d06c30426) | mean-reversion | roth | +22.90pp | +18.64pp | 0.019 | 54 | 2 | 2 | 97.9% | +1.70pp | 0 card(s) | **shelve** |
| 11 | [`g1767·775b`](#card-g1767-775be2277569) | mean-reversion | roth | +22.90pp | +16.47pp | 0.005 | 81 | 5 | 5 | 97.9% | +1.70pp | 15 card(s) | **shelve** |
| 12 | [`g1763·b315`](#card-g1763-b3154a945165) | pairs-rotation | roth | +22.90pp | +16.47pp | 0.006 | 92 | 9 | 6 | 97.9% | +1.70pp | 15 card(s) | **shelve** |
| 13 | [`g1751·051d`](#card-g1751-051dec45a041) | pairs-rotation | roth | +22.90pp | +15.86pp | 0.004 | 77 | 2 | 2 | 97.9% | +1.70pp | 15 card(s) | **shelve** |
| 14 | [`g1751·9b45`](#card-g1751-9b4544bf2556) | pairs-rotation | roth | +22.83pp | +18.34pp | 0.012 | 68 | 2 | 2 | 96.4% | +1.63pp | 15 card(s) | **shelve** |
| 15 | [`g1703·7dd0`](#card-g1703-7dd05b30f905) | breakout | roth | +22.82pp | +18.36pp | 0.008 | 62 | 4 | 4 | 96.1% | +1.62pp | 15 card(s) | **shelve** |
| 16 | [`g1823·e2a3`](#card-g1823-e2a3d5060b09) | mean-reversion | roth | +22.68pp | +14.87pp | 0.050 | 92 | 5 | 5 | 95.5% | +1.48pp | 15 card(s) | **shelve** |
| 17 | [`g1815·d057`](#card-g1815-d05786e4c611) | breakout | roth | +22.68pp | +14.87pp | 0.010 | 111 | 8 | 6 | 95.5% | +1.48pp | 15 card(s) | **shelve** |
| 18 | [`g1803·655c`](#card-g1803-655c39d83d8b) | pairs-rotation | roth | +22.68pp | +14.87pp | 0.006 | 111 | 5 | 5 | 95.5% | +1.48pp | 15 card(s) | **shelve** |
| 19 | [`g1731·6d28`](#card-g1731-6d28de7a5e4c) | momentum | roth | +22.66pp | +17.96pp | 0.002 | 67 | 3 | 3 | 94.4% | +1.46pp | 15 card(s) | **shelve** |
| 20 | [`g1683·ce27`](#card-g1683-ce27fe274c98) | breakout | roth | +22.34pp | +18.05pp | 0.000174 | 77 | 2 | 2 | 93.7% | +1.14pp | 15 card(s) | **shelve** |
| 21 | [`g1679·12ea`](#card-g1679-12eaf5c6bd56) | breakout | roth | +22.34pp | +18.05pp | 0.002 | 65 | 2 | 2 | 93.7% | +1.14pp | 15 card(s) | **shelve** |
| 22 | [`g1707·6b24`](#card-g1707-6b248c4b849d) | mean-reversion | roth | +22.28pp | +15.50pp | 0.001 | 70 | 2 | 2 | 92.7% | +1.08pp | 15 card(s) | **shelve** |
| 23 | [`g1791·c29f`](#card-g1791-c29fafa19c2b) | pairs-rotation | roth | +22.21pp | +14.49pp | 0.004 | 84 | 5 | 5 | 92.4% | +1.01pp | 15 card(s) | **shelve** |
| 24 | [`g1805·5919`](#card-g1805-5919222d57c5) | pairs-rotation | trading | +21.92pp | +21.94pp | 0.000001 | 145 | 2 | 2 | 95.6% | +0.72pp | 3 card(s) | **decline** |
| 25 | [`g1731·8532`](#card-g1731-85327a6b6a50) | momentum | roth | +21.50pp | +19.33pp | 0.009 | 67 | 2 | 2 | 90.2% | +0.30pp | 15 card(s) | **decline** |

## How to read a dossier, and the caution rules applied

Every dossier below has the same shape: a readable name (never a bare hash), what the rule does in plain English, where the card came from, every generation it was scored in with the field's own figures alongside each of its own, what's wrong with it, and a one-line recommendation. `what_a_decision_does` is reproduced in every dossier's underlying JSON record but omitted from the prose below since it is identical across all 25 -- it is quoted once, here:

- **shelve** -- keeps the card, names it, and tracks it. It places no orders and does not join the desk.
- **reject** -- declines it permanently. The loop will not re-file this genome even if it clears the gate again.
- **seat** -- adds it to the simulated paper desk's roster. The desk holds no real money and approving places no order.
- **retire** -- removes it from the shelf without ever seating it. Also permanent.

Caution rules, all deterministic, all computed from the frozen ledger and each card's own record:

| code | fires when | severity |
|---|---|---|
| `holdout-does-not-discriminate` | field holdout-positive fraction > 0.80 | serious |
| `q-above-5pct` | `q_value` is null or > 0.05 | serious |
| `margin-inside-noise` | best selection median − 21.2pp margin ≤ 0 | blocking |
| `thin-trades` | any evidence row with `total_trades` < 30 | serious |
| `narrow-universe` | fewer than 5 tickers | note |
| `worst-window-deep` | `worst_excess` < −20% | note |
| `single-window-set` | fewer than 2 distinct window sets scored | blocking |
| `shelf-crowding` | ≥60% ticker overlap with an already-seated card | note |
| `never-saw-a-crash` | neither `covid` nor `gfc` nor `q4-2018` in any window set actually run | serious |

Across all 25: `holdout-does-not-discriminate` fired 25/25, `shelf-crowding` 21/25, `q-above-5pct` 6/25, `worst-window-deep` 5/25. `margin-inside-noise`, `thin-trades`, `narrow-universe`, `single-window-set`, `never-saw-a-crash` never fired for any of the 25 -- not omitted, checked and negative. That is structural, not a coincidence: `margin-inside-noise` and `single-window-set` are close to impossible for a card that reached `pending_seats.json` at all, since filing requires clearing the margin on two distinct window sets by the same mechanism this caution checks. `thin-trades` and `narrow-universe` reflect that every one of these 25 trades a multi-name universe over many months, and `never-saw-a-crash` reflects that `gfc` is in the default selection-window set almost every generation drew from.

**Recommendation rule, stated in full so it can be checked rather than trusted:** a blocking caution (`margin-inside-noise` or `single-window-set`) means **decline**. A margin over the noise floor under 1.0pp -- close enough to the floor that the next re-measurement could put it under -- also means **decline**. Otherwise the recommendation is **shelve**: nothing here clears its own field by enough, on the evidence filed, to justify seating over the other 24 cards in this same batch. No card in this batch earns **seat** by this rule, because none of the 25 is a clear outlier against its own siblings -- see "What these 25 have in common" above for why that is close to true by construction.

## Dossiers

<a id="card-g009-30c484221799"></a>
### 1. Trend · QCOM/TSM/AMZN +7 · Trading

`g009-30c484221799` · short id `g009·30c4` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-25T04:30:53.650130Z

**What it does.**

- Universe: 10 names: 8 single-name stock(s) and 2 sector ETF(s) (SMH, DVY).
- Entry: Buys when the price is above its 50-day average (a rising-market filter) and the 9-day average crosses above the 20-day average.
- Exit: Sells when the 9-day average crosses back below the 20-day average.
- Risk: Cuts a losing position at −14%. No profit target. Force-closes any position still open after 92 trading days.
- Sizing: At most 3 positions at once, 29% of the book each -- so at most 87% invested, the rest in cash. When more names qualify than there are open slots, the strongest by current price divided by its 50-day average (a shorter-horizon relative-strength ranking) takes the slot.

Raw rule text: `entry = close > sma(50) and ema(9) crosses_above ema(20)`, `exit = ema(9) crosses_below ema(20)`, `rank_by = 'close / sma(50)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 9/20-day EMA crossover trigger inside a 50-day SMA regime filter on QCOM, TSM, AMZN, ORCL, SMH, DVY, NFLX, INTC, MSFT, NVDA, with a 14% stop and a 92-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 9 as a **crossover**. Parents: `g005-75326868cba4`, `g001-6ac015cae61c`. Lineage depth 2 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "crossed g005-75326868cba4 x g001-6ac015cae61c".

**The evidence.** Scored in 3 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 9 | 1 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +30.51pp (+13.08pp) | -16.49pp | 80% | 107 | +20.32pp (+15.02pp all-time) | 0.000120 |
| 13 | 1 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +30.51pp (+18.42pp) | -13.87pp | 80% | 103 | +20.32pp (+15.02pp all-time) | 0.000049 |
| 17 | 4 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | +8.92pp (+8.92pp) | -16.49pp | 60% | 110 | +20.32pp (+15.02pp all-time) | 0.000002 |

Context: 99.9 percentile among all 1,168 `trading`-purpose rows ever run (purpose median-of-medians +9.21pp, purpose holdout median +17.88pp). Best selection median across every generation scored: +30.51pp, which clears the 21.2pp noise floor by +9.31pp.
Promotion record (`promotions.jsonl`): cleared generation 13's gate (median excess 0.3051306201043565725781102659pp > 21.2pp margin) with 2 distinct window sets across generations (9, 13), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +20.32pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.

**Overlap with the currently-seated desk.** 4 currently-seated card(s) share at least one ticker; none reach the 60% crowding threshold.

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1805-5919222d57c5` -- Pairs-rotation · AMD/TXN/TSM +9 · Trading | AMZN, INTC, MSFT, NFLX, NVDA, ORCL, QCOM, TSM | 0.57 |
| `g1809-145d2d5dbfeb` -- Pairs-rotation · AMD/TXN/TSM +9 · Trading | AMZN, INTC, MSFT, NFLX, NVDA, ORCL, QCOM, TSM | 0.57 |
| `g1725-0a9fcd74b740` -- Pairs-rotation · AMD/TXN/TSM +8 · Trading | AMZN, INTC, MSFT, NFLX, NVDA, ORCL, TSM | 0.50 |
| `g1769-349119b209d7` -- Pairs-rotation · AMD/TXN/TSM +8 · Trading | AMZN, INTC, MSFT, NFLX, NVDA, ORCL, TSM | 0.50 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1809-145d2d5dbfeb"></a>
### 2. Pairs-rotation · AMD/TXN/TSM +9 · Trading

`g1809-145d2d5dbfeb` · short id `g1809·145d` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T10:45:33.638880Z

**What it does.**

- Universe: 12 names: 11 single-name stock(s) and 1 sector ETF(s) (SOXX).
- Entry: Buys when the price is above its 67-day average (a rising-market filter) and the 7-day average crosses above the 17-day average.
- Exit: Sells when the 7-day average crosses back below the 17-day average.
- Risk: Cuts a losing position at −14%. No profit target. Force-closes any position still open after 180 trading days.
- Sizing: At most 5 positions at once, 20% of the book each -- fully invested with no cash buffer when all slots are filled. When more names qualify than there are open slots, the strongest by current price divided by its 200-day average (a long-horizon relative-strength ranking) takes the slot.

Raw rule text: `entry = close > sma(67) and ema(7) crosses_above ema(17)`, `exit = ema(7) crosses_below ema(17)`, `rank_by = 'close / sma(200)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 7/17-day EMA crossover trigger inside a 67-day SMA regime filter on AMD, TXN, TSM, INTC, MU, SOXX, NVDA, MSFT, ORCL, NFLX, AMZN, QCOM, with a 14% stop and a 180-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1809 as a **crossover**. Parents: `g1769-349119b209d7`, `g1805-5919222d57c5`. Lineage depth 11 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "crossed g1769-349119b209d7 x g1805-5919222d57c5".

**The evidence.** Scored in 8 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1809 | 1 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +25.72pp (+22.00pp) | -8.15pp | 80% | 154 | +22.13pp (+15.02pp all-time) | 0.000000 |
| 1813 | 1 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | +19.20pp (+19.20pp) | -27.51pp | 60% | 149 | +22.13pp (+15.02pp all-time) | 0.000000 |
| 1817 | 1 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, recent | covid, q4-2018 | +19.20pp (+6.19pp) | -27.51pp | 60% | 143 | +22.13pp (+15.02pp all-time) | 0.000002 |
| 1821 | 1 / 10 | chop-2015, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +25.72pp (+5.52pp) | -27.51pp | 60% | 177 | +22.13pp (+15.02pp all-time) | 0.000000 |
| 1825 | 1 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +19.20pp (+17.18pp) | -27.51pp | 60% | 159 | +22.13pp (+15.02pp all-time) | 0.000000 |
| 1829 | 1 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +25.72pp (+21.47pp) | -27.51pp | 80% | 153 | +22.13pp (+15.02pp all-time) | 0.000003 |
| 1833 | 1 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +25.72pp (+22.99pp) | -8.15pp | 80% | 154 | +22.13pp (+15.02pp all-time) | 0.000000 |
| 1837 | 1 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | +19.20pp (+19.20pp) | -27.51pp | 60% | 149 | +22.13pp (+15.02pp all-time) | 0.000000 |

Context: 99.7 percentile among all 1,168 `trading`-purpose rows ever run (purpose median-of-medians +9.21pp, purpose holdout median +17.88pp). Best selection median across every generation scored: +25.72pp, which clears the 21.2pp noise floor by +4.52pp.
Promotion record (`promotions.jsonl`): cleared generation 1833's gate (median excess 0.2572208744347156740113537958pp > 21.2pp margin) with 2 distinct window sets across generations (1829, 1833), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +22.13pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `worst-window-deep`** -- Worst single-window excess was -27.51pp (generation 1813) -- a deep single-window drawdown relative to benchmark.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 3 already-seated card(s): g1805-5919222d57c5, g1725-0a9fcd74b740, g1769-349119b209d7.

**Overlap with the currently-seated desk.** 3 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1805-5919222d57c5, g1725-0a9fcd74b740, g1769-349119b209d7.

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1805-5919222d57c5` -- Pairs-rotation · AMD/TXN/TSM +9 · Trading | AMD, AMZN, INTC, MSFT, MU, NFLX, NVDA, ORCL, QCOM, SOXX, TSM, TXN | 1.00 |
| `g1725-0a9fcd74b740` -- Pairs-rotation · AMD/TXN/TSM +8 · Trading | AMD, AMZN, INTC, MSFT, MU, NFLX, NVDA, ORCL, SOXX, TSM, TXN | 0.92 |
| `g1769-349119b209d7` -- Pairs-rotation · AMD/TXN/TSM +8 · Trading | AMD, AMZN, INTC, MSFT, MU, NFLX, NVDA, ORCL, SOXX, TSM, TXN | 0.92 |
| `g009-30c484221799` -- Trend · QCOM/TSM/AMZN +7 · Trading | AMZN, INTC, MSFT, NFLX, NVDA, ORCL, QCOM, TSM | 0.57 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1769-349119b209d7"></a>
### 3. Pairs-rotation · AMD/TXN/TSM +8 · Trading

`g1769-349119b209d7` · short id `g1769·3491` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T10:01:56.277305Z

**What it does.**

- Universe: 11 names: 10 single-name stock(s) and 1 sector ETF(s) (SOXX).
- Entry: Buys when the price is above its 67-day average (a rising-market filter) and the 7-day average crosses above the 17-day average.
- Exit: Sells when the 7-day average crosses back below the 17-day average.
- Risk: Cuts a losing position at −14%. No profit target. Force-closes any position still open after 180 trading days.
- Sizing: At most 5 positions at once, 20% of the book each -- fully invested with no cash buffer when all slots are filled. When more names qualify than there are open slots, the strongest by current price divided by its 200-day average (a long-horizon relative-strength ranking) takes the slot.

Raw rule text: `entry = close > sma(67) and ema(7) crosses_above ema(17)`, `exit = ema(7) crosses_below ema(17)`, `rank_by = 'close / sma(200)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 7/17-day EMA crossover trigger inside a 67-day SMA regime filter on AMD, TXN, TSM, INTC, MU, SOXX, NVDA, MSFT, ORCL, NFLX, AMZN, with a 14% stop and a 180-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1769 as a **mutation**. Parents: `g1729-0a9fcd74b740`. Lineage depth 10 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "mutated from g1729-0a9fcd74b740".

**The evidence.** Scored in 11 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1769 | 4 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, recent | covid, q4-2018 | +19.60pp (+16.92pp) | -26.74pp | 60% | 136 | +22.05pp (+15.02pp all-time) | 0.000010 |
| 1773 | 2 / 10 | chop-2015, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +25.04pp (+7.81pp) | -26.74pp | 60% | 165 | +22.05pp (+15.02pp all-time) | 0.000001 |
| 1777 | 2 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +19.60pp (+19.60pp) | -26.74pp | 60% | 147 | +22.05pp (+15.02pp all-time) | 0.000000 |
| 1781 | 1 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +25.04pp (+20.38pp) | -26.74pp | 80% | 140 | +22.05pp (+15.02pp all-time) | 0.000007 |
| 1785 | 1 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +25.04pp (+18.81pp) | -5.56pp | 80% | 142 | +22.05pp (+15.02pp all-time) | 0.000004 |
| 1789 | 1 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | +19.60pp (+14.92pp) | -26.74pp | 60% | 135 | +22.05pp (+15.02pp all-time) | 0.000001 |
| 1793 | 2 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, recent | covid, q4-2018 | +19.60pp (+16.85pp) | -26.74pp | 60% | 136 | +22.05pp (+15.02pp all-time) | 0.000010 |
| 1797 | 1 / 10 | chop-2015, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +25.04pp (+18.84pp) | -26.74pp | 60% | 165 | +22.05pp (+15.02pp all-time) | 0.000001 |
| 1801 | 2 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +19.60pp (+8.22pp) | -26.74pp | 60% | 147 | +22.05pp (+15.02pp all-time) | 0.000000 |
| 1805 | 1 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +25.04pp (+19.20pp) | -26.74pp | 80% | 140 | +22.05pp (+15.02pp all-time) | 0.000006 |
| 1809 | 3 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +25.04pp (+22.00pp) | -5.56pp | 80% | 142 | +22.05pp (+15.02pp all-time) | 0.000003 |

Context: 98.5 percentile among all 1,168 `trading`-purpose rows ever run (purpose median-of-medians +9.21pp, purpose holdout median +17.88pp). Best selection median across every generation scored: +25.04pp, which clears the 21.2pp noise floor by +3.84pp.
Promotion record (`promotions.jsonl`): cleared generation 1785's gate (median excess 0.2504498744347156740113537958pp > 21.2pp margin) with 2 distinct window sets across generations (1781, 1785), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +22.05pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `worst-window-deep`** -- Worst single-window excess was -26.74pp (generation 1769) -- a deep single-window drawdown relative to benchmark.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 3 already-seated card(s): g1725-0a9fcd74b740, g1805-5919222d57c5, g1809-145d2d5dbfeb.

**Overlap with the currently-seated desk.** 3 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1725-0a9fcd74b740, g1805-5919222d57c5, g1809-145d2d5dbfeb.

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1725-0a9fcd74b740` -- Pairs-rotation · AMD/TXN/TSM +8 · Trading | AMD, AMZN, INTC, MSFT, MU, NFLX, NVDA, ORCL, SOXX, TSM, TXN | 1.00 |
| `g1805-5919222d57c5` -- Pairs-rotation · AMD/TXN/TSM +9 · Trading | AMD, AMZN, INTC, MSFT, MU, NFLX, NVDA, ORCL, SOXX, TSM, TXN | 0.92 |
| `g1809-145d2d5dbfeb` -- Pairs-rotation · AMD/TXN/TSM +9 · Trading | AMD, AMZN, INTC, MSFT, MU, NFLX, NVDA, ORCL, SOXX, TSM, TXN | 0.92 |
| `g009-30c484221799` -- Trend · QCOM/TSM/AMZN +7 · Trading | AMZN, INTC, MSFT, NFLX, NVDA, ORCL, TSM | 0.50 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1725-0a9fcd74b740"></a>
### 4. Pairs-rotation · AMD/TXN/TSM +8 · Trading

`g1725-0a9fcd74b740` · short id `g1725·0a9f` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T09:18:28.740354Z

**What it does.**

- Universe: 11 names: 10 single-name stock(s) and 1 sector ETF(s) (SOXX).
- Entry: Buys when the price is above its 67-day average (a rising-market filter) and the 7-day average crosses above the 17-day average.
- Exit: Sells when the 7-day average crosses back below the 17-day average.
- Risk: Cuts a losing position at −11%. No profit target. Force-closes any position still open after 180 trading days.
- Sizing: At most 5 positions at once, 20% of the book each -- fully invested with no cash buffer when all slots are filled. When more names qualify than there are open slots, the strongest by current price divided by its 200-day average (a long-horizon relative-strength ranking) takes the slot.

Raw rule text: `entry = close > sma(67) and ema(7) crosses_above ema(17)`, `exit = ema(7) crosses_below ema(17)`, `rank_by = 'close / sma(200)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 7/17-day EMA crossover trigger inside a 67-day SMA regime filter on AMD, TXN, TSM, INTC, MU, SOXX, NVDA, MSFT, ORCL, NFLX, AMZN, with a 11% stop and a 180-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1725 as a **crossover**. Parents: `g1721-d4791e312eee`, `g1717-93cb176b0544`. Lineage depth 9 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "crossed g1721-d4791e312eee x g1717-93cb176b0544".

**The evidence.** Scored in 13 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1725 | 1 / 10 | chop-2015, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +25.04pp (+5.63pp) | -26.91pp | 60% | 166 | +22.05pp (+15.02pp all-time) | 0.000001 |
| 1729 | 1 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +19.60pp (+9.07pp) | -26.91pp | 60% | 148 | +22.05pp (+15.02pp all-time) | 0.000000 |
| 1733 | 1 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +25.04pp (+17.43pp) | -26.91pp | 80% | 141 | +22.05pp (+15.02pp all-time) | 0.000005 |
| 1737 | 1 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +25.04pp (+18.29pp) | -4.38pp | 80% | 143 | +22.05pp (+15.02pp all-time) | 0.000003 |
| 1741 | 1 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | +19.60pp (+17.22pp) | -26.91pp | 60% | 135 | +22.05pp (+15.02pp all-time) | 0.000001 |
| 1745 | 1 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, recent | covid, q4-2018 | +19.60pp (+16.55pp) | -26.91pp | 60% | 137 | +22.05pp (+15.02pp all-time) | 0.000008 |
| 1749 | 1 / 10 | chop-2015, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +25.04pp (+17.66pp) | -26.91pp | 60% | 166 | +22.05pp (+15.02pp all-time) | 0.000001 |
| 1753 | 1 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +19.60pp (+13.32pp) | -26.91pp | 60% | 148 | +22.05pp (+15.02pp all-time) | 0.000000 |
| 1757 | 1 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +25.04pp (+15.70pp) | -26.91pp | 80% | 141 | +22.05pp (+15.02pp all-time) | 0.000005 |
| 1761 | 1 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +25.04pp (+21.33pp) | -4.38pp | 80% | 143 | +22.05pp (+15.02pp all-time) | 0.000003 |
| 1765 | 1 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | +19.60pp (+13.70pp) | -26.91pp | 60% | 135 | +22.05pp (+15.02pp all-time) | 0.000001 |
| 1769 | 1 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, recent | covid, q4-2018 | +19.60pp (+16.92pp) | -26.91pp | 60% | 137 | +22.05pp (+15.02pp all-time) | 0.000008 |
| 1773 | 1 / 10 | chop-2015, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +25.04pp (+7.81pp) | -26.91pp | 60% | 166 | +22.05pp (+15.02pp all-time) | 0.000001 |

Context: 98.5 percentile among all 1,168 `trading`-purpose rows ever run (purpose median-of-medians +9.21pp, purpose holdout median +17.88pp). Best selection median across every generation scored: +25.04pp, which clears the 21.2pp noise floor by +3.84pp.
Promotion record (`promotions.jsonl`): cleared generation 1737's gate (median excess 0.2504498744347156740113537958pp > 21.2pp margin) with 2 distinct window sets across generations (1733, 1737), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +22.05pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `worst-window-deep`** -- Worst single-window excess was -26.91pp (generation 1725) -- a deep single-window drawdown relative to benchmark.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 3 already-seated card(s): g1769-349119b209d7, g1805-5919222d57c5, g1809-145d2d5dbfeb.

**Overlap with the currently-seated desk.** 3 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1769-349119b209d7, g1805-5919222d57c5, g1809-145d2d5dbfeb.

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1769-349119b209d7` -- Pairs-rotation · AMD/TXN/TSM +8 · Trading | AMD, AMZN, INTC, MSFT, MU, NFLX, NVDA, ORCL, SOXX, TSM, TXN | 1.00 |
| `g1805-5919222d57c5` -- Pairs-rotation · AMD/TXN/TSM +9 · Trading | AMD, AMZN, INTC, MSFT, MU, NFLX, NVDA, ORCL, SOXX, TSM, TXN | 0.92 |
| `g1809-145d2d5dbfeb` -- Pairs-rotation · AMD/TXN/TSM +9 · Trading | AMD, AMZN, INTC, MSFT, MU, NFLX, NVDA, ORCL, SOXX, TSM, TXN | 0.92 |
| `g009-30c484221799` -- Trend · QCOM/TSM/AMZN +7 · Trading | AMZN, INTC, MSFT, NFLX, NVDA, ORCL, TSM | 0.50 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1859-fd7c2c196f35"></a>
### 5. Mean-reversion · CSCO/AMAT/LRCX +3 · Roth

`g1859-fd7c2c196f35` · short id `g1859·fd7c` · stage on the frozen snapshot: `pending` · filed 2026-08-26T15:42:17.852832Z

**What it does.**

- Universe: 6 names: 5 single-name stock(s) and 1 sector ETF(s) (IGV).
- Entry: Buys when the price is above its 135-day average (a rising-market filter) and the 13-day average crosses above the 21-day average.
- Exit: Sells when the 13-day average crosses back below the 21-day average.
- Risk: Cuts a losing position at −8%. No profit target. Force-closes any position still open after 93 trading days.
- Sizing: At most 3 positions at once, 20% of the book each -- so at most 60% invested, the rest in cash.

Raw rule text: `entry = close > sma(135) and ema(13) crosses_above ema(21)`, `exit = ema(13) crosses_below ema(21)`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 13/21-day EMA crossover trigger inside a 135-day SMA regime filter on CSCO, AMAT, LRCX, KLAC, INTU, IGV, with a 8% stop and a 93-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1859 as a **mutation**. Parents: `g1855-4a8d06c30426`. Lineage depth 1 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "mutated from g1855-4a8d06c30426".

**The evidence.** Scored in 3 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1859 | 1 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +24.65pp (+19.42pp) | -10.94pp | 60% | 51 | +14.88pp (+15.02pp all-time) | 0.011 |
| 1863 | 1 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +24.65pp (+22.91pp) | -1.25pp | 80% | 54 | +14.88pp (+15.02pp all-time) | 0.069 |
| 1867 | 8 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | +0.31pp (+4.16pp) | -10.94pp | 60% | 46 | +14.88pp (+15.02pp all-time) | 0.005 |

Context: 99.9 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +24.65pp, which clears the 21.2pp noise floor by +3.45pp.
Promotion record (`promotions.jsonl`): cleared generation 1863's gate (median excess 24.65pp > 21.2pp margin) with 2 distinct window sets across generations (1859, 1863), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +14.88pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[serious] `q-above-5pct`** -- q = 0.069 (generation 1863) -- after correcting for the 2,374 hypotheses this search has tested, roughly 6.9 in 100 cards clearing this bar would be expected to be false positives.

**Overlap with the currently-seated desk.** 17 currently-seated card(s) share at least one ticker; none reach the 60% crowding threshold.

Top 5 of 17 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AMAT, CSCO, INTU, KLAC, LRCX | 0.56 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AMAT, CSCO, INTU, KLAC, LRCX | 0.56 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AMAT, CSCO, INTU, KLAC, LRCX | 0.56 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AMAT, CSCO, INTU, KLAC, LRCX | 0.56 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AMAT, CSCO, INTU, KLAC, LRCX | 0.56 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1679-944a6f327542"></a>
### 6. Pairs-rotation · CSCO/LRCX/CRM +2 · Roth

`g1679-944a6f327542` · short id `g1679·944a` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T08:28:24.790059Z

**What it does.**

- Universe: 5 names: 4 single-name stock(s) and 1 sector ETF(s) (VUG).
- Entry: Buys when the price is above its 126-day average (a rising-market filter) and the 12-day average crosses above the 21-day average.
- Exit: Sells when the 12-day average crosses back below the 21-day average.
- Risk: Cuts a losing position at −8%. Takes profit at +34%. Force-closes any position still open after 154 trading days.
- Sizing: At most 3 positions at once, 30% of the book each -- so at most 90% invested, the rest in cash. When more names qualify than there are open slots, the strongest by 14-day RSI (a short-term momentum reading) takes the slot.

Raw rule text: `entry = close > sma(126) and ema(12) crosses_above ema(21)`, `exit = ema(12) crosses_below ema(21)`, `rank_by = 'rsi(14)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 12/21-day EMA crossover trigger inside a 126-day SMA regime filter on CSCO, LRCX, CRM, AMAT, VUG, with a 8% stop, a 34% target and a 154-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1679 as a **random**. Parents: none -- a random candidate. Lineage depth 0 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "random rules candidate for roth".

**The evidence.** Scored in 4 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1679 | 1 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +24.26pp (+13.59pp) | -5.11pp | 60% | 50 | +11.56pp (+15.02pp all-time) | 0.016 |
| 1683 | 1 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +24.26pp (+20.71pp) | -5.11pp | 80% | 49 | +11.56pp (+15.02pp all-time) | 0.005 |
| 1687 | 2 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +24.26pp (+21.89pp) | -0.32pp | 80% | 59 | +11.56pp (+15.02pp all-time) | 0.005 |
| 1691 | 4 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | +3.32pp (+2.28pp) | -5.11pp | 60% | 44 | +11.56pp (+15.02pp all-time) | 0.009 |

Context: 99.7 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +24.26pp, which clears the 21.2pp noise floor by +3.06pp.
Promotion record (`promotions.jsonl`): cleared generation 1683's gate (median excess 0.2426356201043565725781102659pp > 21.2pp margin) with 2 distinct window sets across generations (1679, 1683), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +11.56pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.

**Overlap with the currently-seated desk.** 16 currently-seated card(s) share at least one ticker; none reach the 60% crowding threshold.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1683-ce27fe274c98` -- Breakout · CSCO/LRCX/CRM +6 · Roth | AMAT, CRM, CSCO, LRCX, VUG | 0.56 |
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AMAT, CRM, CSCO, LRCX | 0.44 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AMAT, CRM, CSCO, LRCX | 0.44 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AMAT, CRM, CSCO, LRCX | 0.44 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AMAT, CRM, CSCO, LRCX | 0.44 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1855-2ff5b8e319dd"></a>
### 7. Pairs-rotation · AAPL/ADBE/INTU +7 · Roth

`g1855-2ff5b8e319dd` · short id `g1855·2ff5` · stage on the frozen snapshot: `pending` · filed 2026-08-26T15:37:25.575795Z

**What it does.**

- Universe: 10 names: 8 single-name stock(s) and 2 sector ETF(s) (VUG, IGV).
- Entry: Buys when the price is above its 110-day average (a rising-market filter) and the 8-day average crosses above the 32-day average.
- Exit: Sells when the 8-day average crosses back below the 32-day average.
- Risk: Cuts a losing position at −10%. No profit target. Force-closes any position still open after 119 trading days.
- Sizing: At most 3 positions at once, 25% of the book each -- so at most 75% invested, the rest in cash. When more names qualify than there are open slots, the strongest by current price divided by its 200-day average (a long-horizon relative-strength ranking) takes the slot.

Raw rule text: `entry = close > sma(110) and ema(8) crosses_above ema(32)`, `exit = ema(8) crosses_below ema(32)`, `rank_by = 'close / sma(200)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 8/32-day EMA crossover trigger inside a 110-day SMA regime filter on AAPL, ADBE, INTU, LRCX, CSCO, KLAC, AMAT, CRM, VUG, IGV, with a 10% stop and a 119-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1855 as a **crossover**. Parents: `g1851-b8ca2480eb2d`, `g1851-30072d8ab5f6`. Lineage depth 1 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "crossed g1851-b8ca2480eb2d x g1851-30072d8ab5f6".

**The evidence.** Scored in 4 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1855 | 1 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +23.34pp (+10.37pp) | -8.92pp | 60% | 70 | +17.68pp (+15.02pp all-time) | 0.013 |
| 1859 | 2 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +23.34pp (+19.42pp) | -8.92pp | 60% | 76 | +17.68pp (+15.02pp all-time) | 0.002 |
| 1863 | 2 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +23.34pp (+22.91pp) | -5.97pp | 60% | 83 | +17.68pp (+15.02pp all-time) | 0.000259 |
| 1867 | 10 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | -3.40pp (+4.16pp) | -8.92pp | 40% | 80 | +17.68pp (+15.02pp all-time) | 0.000045 |

Context: 99.3 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +23.34pp, which clears the 21.2pp noise floor by +2.14pp.
Promotion record (`promotions.jsonl`): cleared generation 1859's gate (median excess 23.34pp > 21.2pp margin) with 2 distinct window sets across generations (1855, 1859), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +17.68pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 16 already-seated card(s): g1683-ce27fe274c98, g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 16 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1683-ce27fe274c98, g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1703-7dd05b30f905.

Top 5 of 17 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1683-ce27fe274c98` -- Breakout · CSCO/LRCX/CRM +6 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX, VUG | 0.90 |
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 0.80 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 0.80 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 0.80 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 0.80 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1755-c30de399e7f4"></a>
### 8. Pairs-rotation · AMAT/CRM/INTU +5 · Roth

`g1755-c30de399e7f4` · short id `g1755·c30d` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T09:38:45.183542Z

**What it does.**

- Universe: 8 names, all single-name stocks.
- Entry: Buys when the price is above its 122-day average (a rising-market filter) and the 12-day average crosses above the 24-day average.
- Exit: Sells when the 12-day average crosses back below the 24-day average.
- Risk: Cuts a losing position at −10%. No profit target. Force-closes any position still open after 63 trading days.
- Sizing: At most 4 positions at once, 20% of the book each -- so at most 80% invested, the rest in cash.

Raw rule text: `entry = close > sma(122) and ema(12) crosses_above ema(24)`, `exit = ema(12) crosses_below ema(24)`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 12/24-day EMA crossover trigger inside a 122-day SMA regime filter on AMAT, CRM, INTU, AAPL, LRCX, KLAC, ADBE, CSCO, with a 10% stop and a 63-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1755 as a **mutation**. Parents: `g1751-051dec45a041`. Lineage depth 8 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "mutated from g1751-051dec45a041".

**The evidence.** Scored in 2 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1755 | 2 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +23.31pp (+22.56pp) | -10.51pp | 80% | 77 | +17.58pp (+15.02pp all-time) | 0.004 |
| 1759 | 2 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +23.31pp (+23.31pp) | +0.07pp | 100% | 81 | +17.58pp (+15.02pp all-time) | 0.009 |

Context: 98.9 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +23.31pp, which clears the 21.2pp noise floor by +2.11pp.
Promotion record (`promotions.jsonl`): cleared generation 1759's gate (median excess 0.2331321788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1755, 1759), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +17.58pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1755-60b22dc5f630"></a>
### 9. Pairs-rotation · AMAT/CRM/INTU +5 · Roth

`g1755-60b22dc5f630` · short id `g1755·60b2` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T09:38:45.145683Z

**What it does.**

- Universe: 8 names, all single-name stocks.
- Entry: Buys when the price is above its 122-day average (a rising-market filter) and the 12-day average crosses above the 26-day average.
- Exit: Sells when the 12-day average crosses back below the 26-day average.
- Risk: Cuts a losing position at −10%. No profit target. Force-closes any position still open after 63 trading days.
- Sizing: At most 4 positions at once, 20% of the book each -- so at most 80% invested, the rest in cash. When more names qualify than there are open slots, the strongest by 14-day RSI (a short-term momentum reading) takes the slot.

Raw rule text: `entry = close > sma(122) and ema(12) crosses_above ema(26)`, `exit = ema(12) crosses_below ema(26)`, `rank_by = 'rsi(14)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 12/26-day EMA crossover trigger inside a 122-day SMA regime filter on AMAT, CRM, INTU, AAPL, LRCX, KLAC, ADBE, CSCO, with a 10% stop and a 63-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1755 as a **crossover**. Parents: `g1751-051dec45a041`, `g1751-9b4544bf2556`. Lineage depth 8 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "crossed g1751-051dec45a041 x g1751-9b4544bf2556".

**The evidence.** Scored in 3 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1755 | 1 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +23.31pp (+22.56pp) | -10.46pp | 80% | 70 | +17.32pp (+15.02pp all-time) | 0.013 |
| 1759 | 1 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +23.31pp (+23.31pp) | +2.83pp | 100% | 70 | +17.32pp (+15.02pp all-time) | 0.072 |
| 1763 | 6 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | +4.18pp (+4.27pp) | -10.46pp | 80% | 65 | +17.32pp (+15.02pp all-time) | 0.014 |

Context: 98.9 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +23.31pp, which clears the 21.2pp noise floor by +2.11pp.
Promotion record (`promotions.jsonl`): cleared generation 1759's gate (median excess 0.2331321788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1755, 1759), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +17.32pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[serious] `q-above-5pct`** -- q = 0.072 (generation 1759) -- after correcting for the 2,374 hypotheses this search has tested, roughly 7.2 in 100 cards clearing this bar would be expected to be false positives.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1855-4a8d06c30426"></a>
### 10. Mean-reversion · AAPL/AMAT/LRCX +3 · Roth

`g1855-4a8d06c30426` · short id `g1855·4a8d` · stage on the frozen snapshot: `pending` · filed 2026-08-26T15:37:25.611147Z

**What it does.**

- Universe: 6 names: 5 single-name stock(s) and 1 sector ETF(s) (IGV).
- Entry: Buys when the price is above its 135-day average (a rising-market filter) and the 13-day average crosses above the 21-day average.
- Exit: Sells when the 13-day average crosses back below the 21-day average.
- Risk: Cuts a losing position at −8%. No profit target. Force-closes any position still open after 123 trading days.
- Sizing: At most 3 positions at once, 20% of the book each -- so at most 60% invested, the rest in cash.

Raw rule text: `entry = close > sma(135) and ema(13) crosses_above ema(21)`, `exit = ema(13) crosses_below ema(21)`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 13/21-day EMA crossover trigger inside a 135-day SMA regime filter on AAPL, AMAT, LRCX, KLAC, INTU, IGV, with a 8% stop and a 123-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1855 as a **random**. Parents: none -- a random candidate. Lineage depth 0 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "random rules candidate for roth".

**The evidence.** Scored in 2 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1855 | 2 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +22.90pp (+10.37pp) | -12.44pp | 80% | 55 | +18.64pp (+15.02pp all-time) | 0.015 |
| 1859 | 4 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +22.90pp (+19.42pp) | -12.44pp | 60% | 54 | +18.64pp (+15.02pp all-time) | 0.019 |

Context: 97.9 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +22.90pp, which clears the 21.2pp noise floor by +1.70pp.
Promotion record (`promotions.jsonl`): cleared generation 1859's gate (median excess 22.90pp > 21.2pp margin) with 2 distinct window sets across generations (1855, 1859), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +18.64pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.

**Overlap with the currently-seated desk.** 17 currently-seated card(s) share at least one ticker; none reach the 60% crowding threshold.

Top 5 of 17 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, AMAT, INTU, KLAC, LRCX | 0.56 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, AMAT, INTU, KLAC, LRCX | 0.56 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, AMAT, INTU, KLAC, LRCX | 0.56 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, AMAT, INTU, KLAC, LRCX | 0.56 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, AMAT, INTU, KLAC, LRCX | 0.56 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1767-775be2277569"></a>
### 11. Mean-reversion · AMAT/CRM/INTU +5 · Roth

`g1767-775be2277569` · short id `g1767·775b` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T09:56:11.153033Z

**What it does.**

- Universe: 8 names, all single-name stocks.
- Entry: Buys when the price is above its 122-day average (a rising-market filter) and the 12-day average crosses above the 23-day average.
- Exit: Sells when the 12-day average crosses back below the 23-day average.
- Risk: Cuts a losing position at −10%. No profit target. Force-closes any position still open after 63 trading days.
- Sizing: At most 4 positions at once, 20% of the book each -- so at most 80% invested, the rest in cash.

Raw rule text: `entry = close > sma(122) and ema(12) crosses_above ema(23)`, `exit = ema(12) crosses_below ema(23)`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 12/23-day EMA crossover trigger inside a 122-day SMA regime filter on AMAT, CRM, INTU, AAPL, LRCX, KLAC, ADBE, CSCO, with a 10% stop and a 63-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1767 as a **mutation**. Parents: `g1763-b3154a945165`. Lineage depth 11 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "mutated from g1763-b3154a945165".

**The evidence.** Scored in 5 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1767 | 2 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, recent | covid, q4-2018 | +11.75pp (+1.46pp) | -10.89pp | 80% | 77 | +16.47pp (+15.02pp all-time) | 0.108 |
| 1771 | 2 / 10 | chop-2015, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +11.75pp (+8.99pp) | -10.89pp | 80% | 92 | +16.47pp (+15.02pp all-time) | 0.007 |
| 1775 | 2 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +22.90pp (+22.49pp) | -10.89pp | 80% | 72 | +16.47pp (+15.02pp all-time) | 0.008 |
| 1779 | 2 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +22.90pp (+19.98pp) | -10.89pp | 80% | 78 | +16.47pp (+15.02pp all-time) | 0.003 |
| 1783 | 3 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +22.90pp (+22.90pp) | +0.41pp | 100% | 81 | +16.47pp (+15.02pp all-time) | 0.005 |

Context: 97.9 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +22.90pp, which clears the 21.2pp noise floor by +1.70pp.
Promotion record (`promotions.jsonl`): cleared generation 1779's gate (median excess 0.2290181788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1775, 1779), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +16.47pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[serious] `q-above-5pct`** -- q = 0.108 (generation 1767) -- after correcting for the 2,374 hypotheses this search has tested, roughly 10.8 in 100 cards clearing this bar would be expected to be false positives.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1763-b3154a945165"></a>
### 12. Pairs-rotation · AMAT/CRM/INTU +5 · Roth

`g1763-b3154a945165` · short id `g1763·b315` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T09:56:11.114339Z

**What it does.**

- Universe: 8 names, all single-name stocks.
- Entry: Buys when the price is above its 122-day average (a rising-market filter) and the 12-day average crosses above the 23-day average.
- Exit: Sells when the 12-day average crosses back below the 23-day average.
- Risk: Cuts a losing position at −10%. No profit target. Force-closes any position still open after 63 trading days.
- Sizing: At most 4 positions at once, 20% of the book each -- so at most 80% invested, the rest in cash.

Raw rule text: `entry = close > sma(122) and ema(12) crosses_above ema(23)`, `exit = ema(12) crosses_below ema(23)`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 12/23-day EMA crossover trigger inside a 122-day SMA regime filter on AMAT, CRM, INTU, AAPL, LRCX, KLAC, ADBE, CSCO, with a 10% stop and a 63-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1763 as a **mutation**. Parents: `g1759-60b22dc5f630`. Lineage depth 10 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "mutated from g1759-60b22dc5f630".

**The evidence.** Scored in 9 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1763 | 1 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | +11.75pp (+4.27pp) | -10.89pp | 80% | 75 | +16.47pp (+15.02pp all-time) | 0.001 |
| 1767 | 1 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, recent | covid, q4-2018 | +11.75pp (+1.46pp) | -10.89pp | 80% | 77 | +16.47pp (+15.02pp all-time) | 0.108 |
| 1771 | 1 / 10 | chop-2015, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +11.75pp (+8.99pp) | -10.89pp | 80% | 92 | +16.47pp (+15.02pp all-time) | 0.007 |
| 1775 | 1 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +22.90pp (+22.49pp) | -10.89pp | 80% | 72 | +16.47pp (+15.02pp all-time) | 0.008 |
| 1779 | 1 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +22.90pp (+19.98pp) | -10.89pp | 80% | 78 | +16.47pp (+15.02pp all-time) | 0.003 |
| 1783 | 2 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +22.90pp (+22.90pp) | +0.41pp | 100% | 81 | +16.47pp (+15.02pp all-time) | 0.005 |
| 1787 | 1 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | +11.75pp (+8.46pp) | -10.89pp | 80% | 75 | +16.47pp (+15.02pp all-time) | 0.001 |
| 1791 | 2 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, recent | covid, q4-2018 | +11.75pp (+10.94pp) | -10.89pp | 80% | 77 | +16.47pp (+15.02pp all-time) | 0.108 |
| 1795 | 4 / 10 | chop-2015, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +11.75pp (+11.32pp) | -10.89pp | 80% | 92 | +16.47pp (+15.02pp all-time) | 0.006 |

Context: 97.9 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +22.90pp, which clears the 21.2pp noise floor by +1.70pp.
Promotion record (`promotions.jsonl`): cleared generation 1779's gate (median excess 0.2290181788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1775, 1779), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +16.47pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[serious] `q-above-5pct`** -- q = 0.108 (generation 1791) -- after correcting for the 2,374 hypotheses this search has tested, roughly 10.8 in 100 cards clearing this bar would be expected to be false positives.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1751-051dec45a041"></a>
### 13. Pairs-rotation · AMAT/CRM/INTU +5 · Roth

`g1751-051dec45a041` · short id `g1751·051d` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T09:35:08.809783Z

**What it does.**

- Universe: 8 names, all single-name stocks.
- Entry: Buys when the price is above its 122-day average (a rising-market filter) and the 12-day average crosses above the 21-day average.
- Exit: Sells when the 12-day average crosses back below the 21-day average.
- Risk: Cuts a losing position at −10%. No profit target. Force-closes any position still open after 63 trading days.
- Sizing: At most 4 positions at once, 20% of the book each -- so at most 80% invested, the rest in cash. When more names qualify than there are open slots, the strongest by 14-day RSI (a short-term momentum reading) takes the slot.

Raw rule text: `entry = close > sma(122) and ema(12) crosses_above ema(21)`, `exit = ema(12) crosses_below ema(21)`, `rank_by = 'rsi(14)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 12/21-day EMA crossover trigger inside a 122-day SMA regime filter on AMAT, CRM, INTU, AAPL, LRCX, KLAC, ADBE, CSCO, with a 10% stop and a 63-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1751 as a **mutation**. Parents: `g1739-5fb34f91391e`. Lineage depth 7 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "mutated from g1739-5fb34f91391e".

**The evidence.** Scored in 2 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1751 | 1 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +22.90pp (+22.30pp) | -8.36pp | 80% | 72 | +15.86pp (+15.02pp all-time) | 0.015 |
| 1755 | 3 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +22.90pp (+22.56pp) | -8.36pp | 80% | 77 | +15.86pp (+15.02pp all-time) | 0.004 |

Context: 97.9 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +22.90pp, which clears the 21.2pp noise floor by +1.70pp.
Promotion record (`promotions.jsonl`): cleared generation 1755's gate (median excess 0.2290181788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1751, 1755), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +15.86pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-9b4544bf2556` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1751-9b4544bf2556"></a>
### 14. Pairs-rotation · AMAT/CRM/INTU +5 · Roth

`g1751-9b4544bf2556` · short id `g1751·9b45` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T09:35:08.839425Z

**What it does.**

- Universe: 8 names, all single-name stocks.
- Entry: Buys when the price is above its 122-day average (a rising-market filter) and the 12-day average crosses above the 26-day average.
- Exit: Sells when the 12-day average crosses back below the 26-day average.
- Risk: Cuts a losing position at −10%. No profit target. Force-closes any position still open after 63 trading days.
- Sizing: At most 4 positions at once, 25% of the book each -- fully invested with no cash buffer when all slots are filled. When more names qualify than there are open slots, the strongest by 14-day RSI (a short-term momentum reading) takes the slot.

Raw rule text: `entry = close > sma(122) and ema(12) crosses_above ema(26)`, `exit = ema(12) crosses_below ema(26)`, `rank_by = 'rsi(14)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 12/26-day EMA crossover trigger inside a 122-day SMA regime filter on AMAT, CRM, INTU, AAPL, LRCX, KLAC, ADBE, CSCO, with a 10% stop and a 63-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1751 as a **mutation**. Parents: `g1743-5fb34f91391e`. Lineage depth 8 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "mutated from g1743-5fb34f91391e".

**The evidence.** Scored in 2 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1751 | 2 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +22.83pp (+22.30pp) | -8.74pp | 80% | 65 | +18.34pp (+15.02pp all-time) | 0.047 |
| 1755 | 4 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +22.83pp (+22.56pp) | -8.74pp | 80% | 68 | +18.34pp (+15.02pp all-time) | 0.012 |

Context: 96.4 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +22.83pp, which clears the 21.2pp noise floor by +1.63pp.
Promotion record (`promotions.jsonl`): cleared generation 1755's gate (median excess 0.2282601788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1751, 1755), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +18.34pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1703-7dd05b30f905"></a>
### 15. Breakout · INTU/LRCX/CRM +4 · Roth

`g1703-7dd05b30f905` · short id `g1703·7dd0` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T08:51:36.100915Z

**What it does.**

- Universe: 7 names, all single-name stocks.
- Entry: Buys when the price is above its 122-day average (a rising-market filter) and the 8-day average crosses above the 29-day average.
- Exit: Sells when the 8-day average crosses back below the 29-day average.
- Risk: Cuts a losing position at −9%. Takes profit at +28%. Force-closes any position still open after 141 trading days.
- Sizing: At most 3 positions at once, 32% of the book each -- so at most 96% invested, the rest in cash.

Raw rule text: `entry = close > sma(122) and ema(8) crosses_above ema(29)`, `exit = ema(8) crosses_below ema(29)`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 8/29-day EMA crossover trigger inside a 122-day SMA regime filter on INTU, LRCX, CRM, CSCO, AAPL, KLAC, ADBE, with a 9% stop, a 28% target and a 141-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1703 as a **random**. Parents: none -- a random candidate. Lineage depth 0 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "random rules candidate for roth".

**The evidence.** Scored in 4 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1703 | 1 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +22.82pp (+17.03pp) | -6.39pp | 60% | 63 | +18.36pp (+15.02pp all-time) | 0.013 |
| 1707 | 1 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +22.82pp (+19.09pp) | -7.71pp | 60% | 66 | +18.36pp (+15.02pp all-time) | 0.011 |
| 1711 | 1 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +22.82pp (+22.25pp) | -7.71pp | 60% | 72 | +18.36pp (+15.02pp all-time) | 0.008 |
| 1715 | 7 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | -2.14pp (-0.25pp) | -7.71pp | 40% | 62 | +18.36pp (+15.02pp all-time) | 0.008 |

Context: 96.1 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +22.82pp, which clears the 21.2pp noise floor by +1.62pp.
Promotion record (`promotions.jsonl`): cleared generation 1707's gate (median excess 0.2282121788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1703, 1707), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +18.36pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, CRM, CSCO, INTU, KLAC, LRCX | 0.88 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, CRM, CSCO, INTU, KLAC, LRCX | 0.88 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, CRM, CSCO, INTU, KLAC, LRCX | 0.88 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, CRM, CSCO, INTU, KLAC, LRCX | 0.88 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, CRM, CSCO, INTU, KLAC, LRCX | 0.88 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1823-e2a3d5060b09"></a>
### 16. Mean-reversion · AMAT/CRM/INTU +5 · Roth

`g1823-e2a3d5060b09` · short id `g1823·e2a3` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T10:39:56.162402Z

**What it does.**

- Universe: 8 names, all single-name stocks.
- Entry: Buys when the price is above its 92-day average (a rising-market filter) and the 12-day average crosses above the 15-day average.
- Exit: Sells when the 12-day average crosses back below the 15-day average.
- Risk: Cuts a losing position at −10%. No profit target. Force-closes any position still open after 63 trading days.
- Sizing: At most 4 positions at once, 20% of the book each -- so at most 80% invested, the rest in cash. When more names qualify than there are open slots, the strongest by current price divided by its 200-day average (a long-horizon relative-strength ranking) takes the slot.

Raw rule text: `entry = close > sma(92) and ema(12) crosses_above ema(15)`, `exit = ema(12) crosses_below ema(15)`, `rank_by = 'close / sma(200)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 12/15-day EMA crossover trigger inside a 92-day SMA regime filter on AMAT, CRM, INTU, AAPL, LRCX, KLAC, ADBE, CSCO, with a 10% stop and a 63-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1823 as a **mutation**. Parents: `g1815-d05786e4c611`. Lineage depth 14 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "mutated from g1815-d05786e4c611".

**The evidence.** Scored in 5 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1823 | 2 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +22.68pp (+21.86pp) | -14.63pp | 80% | 91 | +14.87pp (+15.02pp all-time) | 0.014 |
| 1827 | 2 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +22.68pp (+21.91pp) | -14.63pp | 60% | 95 | +14.87pp (+15.02pp all-time) | 0.005 |
| 1831 | 2 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +22.68pp (+21.33pp) | -0.58pp | 80% | 97 | +14.87pp (+15.02pp all-time) | 0.017 |
| 1835 | 2 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | +12.02pp (+9.95pp) | -14.63pp | 60% | 94 | +14.87pp (+15.02pp all-time) | 0.004 |
| 1839 | 3 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, recent | covid, q4-2018 | +12.02pp (+9.97pp) | -14.63pp | 60% | 92 | +14.87pp (+15.02pp all-time) | 0.050 |

Context: 95.5 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +22.68pp, which clears the 21.2pp noise floor by +1.48pp.
Promotion record (`promotions.jsonl`): cleared generation 1827's gate (median excess 0.2267801788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1823, 1827), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +14.87pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1683-ce27fe274c98, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1683-ce27fe274c98, g1703-7dd05b30f905.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1815-d05786e4c611"></a>
### 17. Breakout · AMAT/CRM/INTU +5 · Roth

`g1815-d05786e4c611` · short id `g1815·d057` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T10:39:56.116566Z

**What it does.**

- Universe: 8 names, all single-name stocks.
- Entry: Buys when the price is above its 92-day average (a rising-market filter) and the 12-day average crosses above the 15-day average.
- Exit: Sells when the 12-day average crosses back below the 15-day average.
- Risk: Cuts a losing position at −10%. No profit target. Force-closes any position still open after 63 trading days.
- Sizing: At most 4 positions at once, 20% of the book each -- so at most 80% invested, the rest in cash. When more names qualify than there are open slots, the strongest by current price divided by its 200-day average (a long-horizon relative-strength ranking) takes the slot.

Raw rule text: `entry = close > sma(92) and ema(12) crosses_above ema(15)`, `exit = ema(12) crosses_below ema(15)`, `rank_by = 'close / sma(200)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 12/15-day EMA crossover trigger inside a 92-day SMA regime filter on AMAT, CRM, INTU, AAPL, LRCX, KLAC, ADBE, CSCO, with a 10% stop and a 63-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1815 as a **mutation**. Parents: `g1807-655c39d83d8b`. Lineage depth 13 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "mutated from g1807-655c39d83d8b".

**The evidence.** Scored in 8 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1815 | 1 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, recent | covid, q4-2018 | +12.02pp (+9.76pp) | -14.63pp | 60% | 92 | +14.87pp (+15.02pp all-time) | 0.051 |
| 1819 | 2 / 10 | chop-2015, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +12.02pp (+10.85pp) | -14.63pp | 60% | 111 | +14.87pp (+15.02pp all-time) | 0.010 |
| 1823 | 1 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +22.68pp (+21.86pp) | -14.63pp | 80% | 91 | +14.87pp (+15.02pp all-time) | 0.014 |
| 1827 | 1 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +22.68pp (+21.91pp) | -14.63pp | 60% | 95 | +14.87pp (+15.02pp all-time) | 0.005 |
| 1831 | 1 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +22.68pp (+21.33pp) | -0.58pp | 80% | 97 | +14.87pp (+15.02pp all-time) | 0.017 |
| 1835 | 1 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | +12.02pp (+9.95pp) | -14.63pp | 60% | 94 | +14.87pp (+15.02pp all-time) | 0.004 |
| 1839 | 2 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, recent | covid, q4-2018 | +12.02pp (+9.97pp) | -14.63pp | 60% | 92 | +14.87pp (+15.02pp all-time) | 0.050 |
| 1843 | 4 / 10 | chop-2015, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +12.02pp (+12.02pp) | -14.63pp | 60% | 111 | +14.87pp (+15.02pp all-time) | 0.010 |

Context: 95.5 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +22.68pp, which clears the 21.2pp noise floor by +1.48pp.
Promotion record (`promotions.jsonl`): cleared generation 1827's gate (median excess 0.2267801788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1823, 1827), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +14.87pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[serious] `q-above-5pct`** -- q = 0.051 (generation 1815) -- after correcting for the 2,374 hypotheses this search has tested, roughly 5.1 in 100 cards clearing this bar would be expected to be false positives.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1803-655c39d83d8b"></a>
### 18. Pairs-rotation · AMAT/CRM/INTU +5 · Roth

`g1803-655c39d83d8b` · short id `g1803·655c` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T10:21:33.731192Z

**What it does.**

- Universe: 8 names, all single-name stocks.
- Entry: Buys when the price is above its 92-day average (a rising-market filter) and the 12-day average crosses above the 15-day average.
- Exit: Sells when the 12-day average crosses back below the 15-day average.
- Risk: Cuts a losing position at −10%. No profit target. Force-closes any position still open after 63 trading days.
- Sizing: At most 4 positions at once, 20% of the book each -- so at most 80% invested, the rest in cash.

Raw rule text: `entry = close > sma(92) and ema(12) crosses_above ema(15)`, `exit = ema(12) crosses_below ema(15)`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 12/15-day EMA crossover trigger inside a 92-day SMA regime filter on AMAT, CRM, INTU, AAPL, LRCX, KLAC, ADBE, CSCO, with a 10% stop and a 63-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1803 as a **mutation**. Parents: `g1795-c29fafa19c2b`. Lineage depth 12 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "mutated from g1795-c29fafa19c2b".

**The evidence.** Scored in 5 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1803 | 1 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +22.68pp (+22.21pp) | -14.63pp | 60% | 95 | +14.87pp (+15.02pp all-time) | 0.005 |
| 1807 | 1 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +22.68pp (+21.71pp) | -0.58pp | 80% | 97 | +14.87pp (+15.02pp all-time) | 0.010 |
| 1811 | 1 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | +10.85pp (+8.12pp) | -14.63pp | 60% | 94 | +14.87pp (+15.02pp all-time) | 0.002 |
| 1815 | 2 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, recent | covid, q4-2018 | +10.85pp (+9.76pp) | -14.63pp | 60% | 92 | +14.87pp (+15.02pp all-time) | 0.031 |
| 1819 | 5 / 10 | chop-2015, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +10.85pp (+10.85pp) | -14.63pp | 60% | 111 | +14.87pp (+15.02pp all-time) | 0.006 |

Context: 95.5 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +22.68pp, which clears the 21.2pp noise floor by +1.48pp.
Promotion record (`promotions.jsonl`): cleared generation 1807's gate (median excess 0.2267801788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1803, 1807), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +14.87pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1731-6d28de7a5e4c"></a>
### 19. Momentum · AMAT/CRM/INTU +5 · Roth

`g1731-6d28de7a5e4c` · short id `g1731·6d28` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T09:16:41.985569Z

**What it does.**

- Universe: 8 names, all single-name stocks.
- Entry: Buys when the price is above its 122-day average (a rising-market filter) and the 14-day average crosses above the 21-day average.
- Exit: Sells when the 14-day average crosses back below the 21-day average.
- Risk: Cuts a losing position at −9%. No profit target. Force-closes any position still open after 63 trading days.
- Sizing: At most 4 positions at once, 25% of the book each -- fully invested with no cash buffer when all slots are filled. When more names qualify than there are open slots, the strongest by current price divided by its 50-day average (a shorter-horizon relative-strength ranking) takes the slot.

Raw rule text: `entry = close > sma(122) and ema(14) crosses_above ema(21)`, `exit = ema(14) crosses_below ema(21)`, `rank_by = 'close / sma(50)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 14/21-day EMA crossover trigger inside a 122-day SMA regime filter on AMAT, CRM, INTU, AAPL, LRCX, KLAC, ADBE, CSCO, with a 9% stop and a 63-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1731 as a **mutation**. Parents: `g1727-468953b4c5cf`. Lineage depth 4 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "mutated from g1727-468953b4c5cf".

**The evidence.** Scored in 3 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1731 | 1 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +22.66pp (+19.17pp) | -5.36pp | 80% | 72 | +17.96pp (+15.02pp all-time) | 0.008 |
| 1735 | 1 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +22.66pp (+21.50pp) | +0.10pp | 100% | 72 | +17.96pp (+15.02pp all-time) | 0.015 |
| 1739 | 5 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, gfc | covid, q4-2018 | +2.22pp (+2.22pp) | -5.36pp | 80% | 67 | +17.96pp (+15.02pp all-time) | 0.002 |

Context: 94.4 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +22.66pp, which clears the 21.2pp noise floor by +1.46pp.
Promotion record (`promotions.jsonl`): cleared generation 1735's gate (median excess 0.2266081788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1731, 1735), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +17.96pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-9b4544bf2556` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1683-ce27fe274c98"></a>
### 20. Breakout · CSCO/LRCX/CRM +6 · Roth

`g1683-ce27fe274c98` · short id `g1683·ce27` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T08:32:46.609820Z

**What it does.**

- Universe: 9 names: 8 single-name stock(s) and 1 sector ETF(s) (VUG).
- Entry: Buys when the price is above its 119-day average (a rising-market filter) and the 13-day average crosses above the 23-day average.
- Exit: Sells when the 13-day average crosses back below the 23-day average.
- Risk: Cuts a losing position at −7%. Takes profit at +34%. Force-closes any position still open after 102 trading days.
- Sizing: At most 3 positions at once, 30% of the book each -- so at most 90% invested, the rest in cash. When more names qualify than there are open slots, the strongest by 14-day RSI (a short-term momentum reading) takes the slot.

Raw rule text: `entry = close > sma(119) and ema(13) crosses_above ema(23)`, `exit = ema(13) crosses_below ema(23)`, `rank_by = 'rsi(14)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 13/23-day EMA crossover trigger inside a 119-day SMA regime filter on CSCO, LRCX, CRM, AMAT, VUG, INTU, AAPL, ADBE, KLAC, with a 7% stop, a 34% target and a 102-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1683 as a **crossover**. Parents: `g1679-944a6f327542`, `g1679-12eaf5c6bd56`. Lineage depth 1 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "crossed g1679-944a6f327542 x g1679-12eaf5c6bd56".

**The evidence.** Scored in 2 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1683 | 3 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +22.34pp (+20.71pp) | -2.41pp | 60% | 76 | +18.05pp (+15.02pp all-time) | 0.000101 |
| 1687 | 3 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +22.34pp (+21.89pp) | -1.58pp | 80% | 77 | +18.05pp (+15.02pp all-time) | 0.000174 |

Context: 93.7 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +22.34pp, which clears the 21.2pp noise floor by +1.14pp.
Promotion record (`promotions.jsonl`): cleared generation 1687's gate (median excess 0.2233901788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1683, 1687), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +18.05pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1703-7dd05b30f905.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 0.89 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 0.89 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 0.89 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 0.89 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 0.89 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1679-12eaf5c6bd56"></a>
### 21. Breakout · INTU/LRCX/CSCO +5 · Roth

`g1679-12eaf5c6bd56` · short id `g1679·12ea` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T08:28:24.839499Z

**What it does.**

- Universe: 8 names, all single-name stocks.
- Entry: Buys when the price is above its 119-day average (a rising-market filter) and the 13-day average crosses above the 23-day average.
- Exit: Sells when the 13-day average crosses back below the 23-day average.
- Risk: Cuts a losing position at −7%. No profit target. Force-closes any position still open after 102 trading days.
- Sizing: At most 3 positions at once, 30% of the book each -- so at most 90% invested, the rest in cash. When more names qualify than there are open slots, the strongest by 14-day RSI (a short-term momentum reading) takes the slot.

Raw rule text: `entry = close > sma(119) and ema(13) crosses_above ema(23)`, `exit = ema(13) crosses_below ema(23)`, `rank_by = 'rsi(14)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 13/23-day EMA crossover trigger inside a 119-day SMA regime filter on INTU, LRCX, CSCO, AAPL, ADBE, AMAT, KLAC, CRM, with a 7% stop and a 102-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1679 as a **random**. Parents: none -- a random candidate. Lineage depth 0 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "random rules candidate for roth".

**The evidence.** Scored in 2 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1679 | 2 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +22.34pp (+13.59pp) | -10.33pp | 80% | 60 | +18.05pp (+15.02pp all-time) | 0.008 |
| 1683 | 2 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +22.34pp (+20.71pp) | -10.33pp | 60% | 65 | +18.05pp (+15.02pp all-time) | 0.002 |

Context: 93.7 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +22.34pp, which clears the 21.2pp noise floor by +1.14pp.
Promotion record (`promotions.jsonl`): cleared generation 1683's gate (median excess 0.2233901788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1679, 1683), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +18.05pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-9b4544bf2556` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1707-6b248c4b849d"></a>
### 22. Mean-reversion · INTU/LRCX/CRM +5 · Roth

`g1707-6b248c4b849d` · short id `g1707·6b24` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T08:55:18.494644Z

**What it does.**

- Universe: 8 names, all single-name stocks.
- Entry: Buys when the price is above its 170-day average (a rising-market filter) and the 8-day average crosses above the 31-day average.
- Exit: Sells when the 8-day average crosses back below the 31-day average.
- Risk: Cuts a losing position at −13%. No profit target. Force-closes any position still open after 90 trading days.
- Sizing: At most 3 positions at once, 32% of the book each -- so at most 96% invested, the rest in cash.

Raw rule text: `entry = close > sma(170) and ema(8) crosses_above ema(31)`, `exit = ema(8) crosses_below ema(31)`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 8/31-day EMA crossover trigger inside a 170-day SMA regime filter on INTU, LRCX, CRM, CSCO, AAPL, KLAC, ADBE, AMAT, with a 13% stop and a 90-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1707 as a **crossover**. Parents: `g1703-7dd05b30f905`, `g1703-30ce98ff824f`. Lineage depth 3 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "crossed g1703-7dd05b30f905 x g1703-30ce98ff824f".

**The evidence.** Scored in 2 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1707 | 2 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +22.28pp (+19.09pp) | -24.53pp | 60% | 65 | +15.50pp (+15.02pp all-time) | 0.000251 |
| 1711 | 4 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +22.28pp (+22.25pp) | -4.03pp | 60% | 70 | +15.50pp (+15.02pp all-time) | 0.001 |

Context: 92.7 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +22.28pp, which clears the 21.2pp noise floor by +1.08pp.
Promotion record (`promotions.jsonl`): cleared generation 1711's gate (median excess 0.2227941788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1707, 1711), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +15.50pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `worst-window-deep`** -- Worst single-window excess was -24.53pp (generation 1707) -- a deep single-window drawdown relative to benchmark.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1679-12eaf5c6bd56, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1679-12eaf5c6bd56, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-9b4544bf2556` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1791-c29fafa19c2b"></a>
### 23. Pairs-rotation · AMAT/CRM/INTU +5 · Roth

`g1791-c29fafa19c2b` · short id `g1791·c29f` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T10:17:53.809952Z

**What it does.**

- Universe: 8 names, all single-name stocks.
- Entry: Buys when the price is above its 92-day average (a rising-market filter) and the 12-day average crosses above the 23-day average.
- Exit: Sells when the 12-day average crosses back below the 23-day average.
- Risk: Cuts a losing position at −10%. No profit target. Force-closes any position still open after 63 trading days.
- Sizing: At most 4 positions at once, 20% of the book each -- so at most 80% invested, the rest in cash.

Raw rule text: `entry = close > sma(92) and ema(12) crosses_above ema(23)`, `exit = ema(12) crosses_below ema(23)`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 12/23-day EMA crossover trigger inside a 92-day SMA regime filter on AMAT, CRM, INTU, AAPL, LRCX, KLAC, ADBE, CSCO, with a 10% stop and a 63-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1791 as a **mutation**. Parents: `g1763-b3154a945165`. Lineage depth 11 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "mutated from g1763-b3154a945165".

**The evidence.** Scored in 5 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1791 | 1 / 10 | bear-2022, chop-2015, chop-2011, bull-2024, recent | covid, q4-2018 | +12.69pp (+10.94pp) | -9.55pp | 60% | 77 | +14.49pp (+15.02pp all-time) | 0.069 |
| 1795 | 1 / 10 | chop-2015, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +12.69pp (+11.32pp) | -9.55pp | 60% | 94 | +14.49pp (+15.02pp all-time) | 0.007 |
| 1799 | 1 / 10 | bear-2022, chop-2011, bull-2024, recent, gfc | covid, q4-2018 | +22.21pp (+20.79pp) | -9.55pp | 80% | 75 | +14.49pp (+15.02pp all-time) | 0.012 |
| 1803 | 2 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +22.21pp (+22.21pp) | -9.55pp | 60% | 83 | +14.49pp (+15.02pp all-time) | 0.001 |
| 1807 | 4 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +22.21pp (+21.71pp) | -1.63pp | 80% | 84 | +14.49pp (+15.02pp all-time) | 0.004 |

Context: 92.4 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +22.21pp, which clears the 21.2pp noise floor by +1.01pp.
Promotion record (`promotions.jsonl`): cleared generation 1803's gate (median excess 0.2221331788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1799, 1803), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +14.49pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[serious] `q-above-5pct`** -- q = 0.069 (generation 1791) -- after correcting for the 2,374 hypotheses this search has tested, roughly 6.9 in 100 cards clearing this bar would be expected to be false positives.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1731-85327a6b6a50, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-85327a6b6a50` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |

**Recommendation: shelve.** holdout-does-not-discriminate fired; the case for seating rests on figures that don't discriminate from the field.

---

<a id="card-g1805-5919222d57c5"></a>
### 24. Pairs-rotation · AMD/TXN/TSM +9 · Trading

`g1805-5919222d57c5` · short id `g1805·5919` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T10:23:28.969170Z

**What it does.**

- Universe: 12 names: 11 single-name stock(s) and 1 sector ETF(s) (SOXX).
- Entry: Buys when the price is above its 67-day average (a rising-market filter) and the 7-day average crosses above the 17-day average.
- Exit: Sells when the 7-day average crosses back below the 17-day average.
- Risk: Cuts a losing position at −14%. No profit target. Force-closes any position still open after 180 trading days.
- Sizing: At most 4 positions at once, 20% of the book each -- so at most 80% invested, the rest in cash. When more names qualify than there are open slots, the strongest by current price divided by its 200-day average (a long-horizon relative-strength ranking) takes the slot.

Raw rule text: `entry = close > sma(67) and ema(7) crosses_above ema(17)`, `exit = ema(7) crosses_below ema(17)`, `rank_by = 'close / sma(200)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 7/17-day EMA crossover trigger inside a 67-day SMA regime filter on AMD, TXN, TSM, INTC, MU, SOXX, QCOM, MSFT, ORCL, NFLX, AMZN, NVDA, with a 14% stop and a 180-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1805 as a **crossover**. Parents: `g1801-b17872e8312b`, `g1769-349119b209d7`. Lineage depth 12 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "crossed g1801-b17872e8312b x g1769-349119b209d7".

**The evidence.** Scored in 2 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1805 | 2 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +21.92pp (+19.20pp) | -20.27pp | 80% | 140 | +21.94pp (+15.02pp all-time) | 0.000014 |
| 1809 | 6 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +21.92pp (+22.00pp) | -8.15pp | 80% | 145 | +21.94pp (+15.02pp all-time) | 0.000001 |

Context: 95.6 percentile among all 1,168 `trading`-purpose rows ever run (purpose median-of-medians +9.21pp, purpose holdout median +17.88pp). Best selection median across every generation scored: +21.92pp, which clears the 21.2pp noise floor by +0.72pp.
Promotion record (`promotions.jsonl`): cleared generation 1809's gate (median excess 0.2191886201043565725781102659pp > 21.2pp margin) with 2 distinct window sets across generations (1805, 1809), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +21.94pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `worst-window-deep`** -- Worst single-window excess was -20.27pp (generation 1805) -- a deep single-window drawdown relative to benchmark.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 3 already-seated card(s): g1809-145d2d5dbfeb, g1725-0a9fcd74b740, g1769-349119b209d7.

**Overlap with the currently-seated desk.** 3 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1809-145d2d5dbfeb, g1725-0a9fcd74b740, g1769-349119b209d7.

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1809-145d2d5dbfeb` -- Pairs-rotation · AMD/TXN/TSM +9 · Trading | AMD, AMZN, INTC, MSFT, MU, NFLX, NVDA, ORCL, QCOM, SOXX, TSM, TXN | 1.00 |
| `g1725-0a9fcd74b740` -- Pairs-rotation · AMD/TXN/TSM +8 · Trading | AMD, AMZN, INTC, MSFT, MU, NFLX, NVDA, ORCL, SOXX, TSM, TXN | 0.92 |
| `g1769-349119b209d7` -- Pairs-rotation · AMD/TXN/TSM +8 · Trading | AMD, AMZN, INTC, MSFT, MU, NFLX, NVDA, ORCL, SOXX, TSM, TXN | 0.92 |
| `g009-30c484221799` -- Trend · QCOM/TSM/AMZN +7 · Trading | AMZN, INTC, MSFT, NFLX, NVDA, ORCL, QCOM, TSM | 0.57 |

**Recommendation: decline.** Best selection median clears the 21.2pp noise floor by only 0.72pp -- inside rounding distance of failing the gate this card was filed on.

---

<a id="card-g1731-85327a6b6a50"></a>
### 25. Momentum · AMAT/CRM/INTU +5 · Roth

`g1731-85327a6b6a50` · short id `g1731·8532` · stage on the frozen snapshot: `approved` (currently seated in roster_overlay.json) · filed 2026-08-26T09:16:42.024903Z

**What it does.**

- Universe: 8 names, all single-name stocks.
- Entry: Buys when the price is above its 122-day average (a rising-market filter) and the 11-day average crosses above the 26-day average.
- Exit: Sells when the 11-day average crosses back below the 26-day average.
- Risk: Cuts a losing position at −9%. No profit target. Force-closes any position still open after 63 trading days.
- Sizing: At most 3 positions at once, 32% of the book each -- so at most 96% invested, the rest in cash. When more names qualify than there are open slots, the strongest by current price divided by its 50-day average (a shorter-horizon relative-strength ranking) takes the slot.

Raw rule text: `entry = close > sma(122) and ema(11) crosses_above ema(26)`, `exit = ema(11) crosses_below ema(26)`, `rank_by = 'close / sma(50)'`.

**Thesis, as filed (verbatim):** Machine-proposed candidate (app.evolution). Tests a 11/26-day EMA crossover trigger inside a 122-day SMA regime filter on AMAT, CRM, INTU, AAPL, LRCX, KLAC, ADBE, CSCO, with a 9% stop and a 63-session time stop. Never scored before being written -- this is falsified if the crossover-inside-regime signal fails to beat this purpose's benchmark by more than the measured ordering-noise floor, across whatever windows it is actually run against.

**Where it came from.**

Created in generation 1731 as a **mutation**. Parents: `g1727-468953b4c5cf`. Lineage depth 4 (the number of mutation/crossover steps back to the nearest random-candidate ancestor). PLAN.md's own note: "mutated from g1727-468953b4c5cf".

**The evidence.** Scored in 2 generation(s):

| generation | rank / field | windows | holdout windows | selection median (field median) | worst window | hit rate | closed trades | holdout median (field median) | q |
|---|---|---|---|---|---|---|---|---|---|
| 1731 | 2 / 10 | bear-2022, chop-2015, bull-2024, recent, gfc | covid, q4-2018 | +21.50pp (+19.17pp) | -6.79pp | 60% | 66 | +19.33pp (+15.02pp all-time) | 0.003 |
| 1735 | 4 / 10 | bear-2022, chop-2015, chop-2011, recent, gfc | covid, q4-2018 | +21.50pp (+21.50pp) | -6.79pp | 80% | 67 | +19.33pp (+15.02pp all-time) | 0.009 |

Context: 90.2 percentile among all 1,206 `roth`-purpose rows ever run (purpose median-of-medians +2.24pp, purpose holdout median +12.88pp). Best selection median across every generation scored: +21.50pp, which clears the 21.2pp noise floor by +0.30pp.
Promotion record (`promotions.jsonl`): cleared generation 1735's gate (median excess 0.2150051788788578626915809364pp > 21.2pp margin) with 2 distinct window sets across generations (1731, 1735), meeting the 2-generation requirement

**What's wrong with it.**

- **[serious] `holdout-does-not-discriminate`** -- 94.3% of all 2,374 candidates ever run also posted a positive holdout median. This card's holdout median excess is +19.33pp, against an all-time field holdout median of +15.02pp -- inside the field's ordinary range, so the holdout number alone is not evidence this card beats a coin flip from the same generator.
- **[note] `shelf-crowding`** -- ≥ 60% ticker overlap with 15 already-seated card(s): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

**Overlap with the currently-seated desk.** 15 currently-seated card(s) already trade a majority-overlapping universe (≥60% ticker overlap): g1679-12eaf5c6bd56, g1707-6b248c4b849d, g1731-6d28de7a5e4c, g1751-051dec45a041, g1751-9b4544bf2556, g1755-60b22dc5f630, g1755-c30de399e7f4, g1763-b3154a945165, g1767-775be2277569, g1791-c29fafa19c2b, g1803-655c39d83d8b, g1815-d05786e4c611, g1823-e2a3d5060b09, g1683-ce27fe274c98, g1703-7dd05b30f905.

Top 5 of 16 by Jaccard shown:

| seated card | shared tickers | Jaccard |
|---|---|---|
| `g1679-12eaf5c6bd56` -- Breakout · INTU/LRCX/CSCO +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1707-6b248c4b849d` -- Mean-reversion · INTU/LRCX/CRM +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1731-6d28de7a5e4c` -- Momentum · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-051dec45a041` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |
| `g1751-9b4544bf2556` -- Pairs-rotation · AMAT/CRM/INTU +5 · Roth | AAPL, ADBE, AMAT, CRM, CSCO, INTU, KLAC, LRCX | 1.00 |

**Recommendation: decline.** Best selection median clears the 21.2pp noise floor by only 0.30pp -- inside rounding distance of failing the gate this card was filed on.

---

