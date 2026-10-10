# Round 26 — running the seated cards' own falsification conditions

Pre-registered 2026-08-30, before any card in this round is authored and before any cell's result
exists. **Not investment advice.**

---

## 1. What this executes

`docs/research/programme/thesis-audit.md` found that eleven of thirteen quantitative claims on the
seated cards had never been measured outside the window they were fitted on. Falsification clauses
were then written into the four trading cards (`d51c67f`), and two of them were found to name
measurements that had **already** been run and were corrected (`358df33`, audit §9).

This round runs what genuinely remains. **The clauses are the pre-registration** — they are committed,
they predate every cell here, and this document adds only the exact card specifications and the
decision rule.

**Nothing in this round is promotable.** It measures whether seated cards' stated rationales survive
contact with a regime matrix. A card whose thesis fails here is not thereby demoted; that is an
owner decision under `PROTOCOL.md` §9, and the trading purpose has no promotion rule at all.

## 2. What is *not* askable, established before running

**`C-trend`'s universe-exclusion condition cannot be tested on this matrix.** The clause asks for the
five names excluded on measured evidence (IREN, OKLO, APLD, BE, KORU) to be run as an arm. Their bar
histories:

| symbol | first bar |
|---|---|
| `KORU` | 2013-04-09 |
| `BE` | 2018-07-24 |
| `OKLO` | 2021-07-07 |
| `IREN` | 2021-11-16 |
| `APLD` | 2022-04-12 |

All five co-exist only from **2022-04-12**, which covers `bull-2024` and `recent` and **nothing else in
the eight-window matrix**. A zero-bar symbol fails the whole card at the lookahead guard (round 17's
amendment), and two windows is below `R2_MATRIX`'s five-window minimum.

**So this is round 21's category, not a null:** the question is asked with an instrument that cannot
answer it. Recorded here rather than discovered in the results, and no two-window arm will be run and
presented as if it were a matrix result. What would settle it is a purpose-built window set inside
those names' own history — a different round, pre-registered separately, and one whose windows would
be selected on symbol availability rather than on regime.

## 3. Arms

Seven cards on `R2_MATRIX`'s eight windows, via `strategy-program/tools/run_round.sh` (serial, with
its own D3 guard) and scored by `score.py`. **Controls are re-run rather than quoted from round 24**,
so every figure in this round comes from one code version.

| card | derived from | the single change |
|---|---|---|
| `r26-ctrend-base` | `C-trend` | none — control |
| `r26-ctrend-stop08` | `C-trend` | `stop_loss_pct` 0.12 → **0.08** |
| `r26-b3-base` | `B3-concentrated` | none — control |
| `r26-b3-tp20` | `B3-concentrated` | `take_profit_pct` None → **0.20** |
| `r26-b3-fastexit` | `B3-concentrated` | `exit` → **`close crosses_below ema(20)`** |
| `r26-arot-base` | `A-rotation` | none — control |
| `r26-arot-rankby` | `A-rotation` | `rank_by` None → **`close / sma(50)`** |

Each isolates exactly one decision (`PROTOCOL.md` §7). Nothing else differs, field for field.

**Two parameter choices are conventions, fixed here before any result exists.** The thesis says
"capping gains at 8-30%", a range; **0.20** is its midpoint and no other value will be tried. The
fast-exit arm uses `ema(20)` **without** the 3-day confirmation filter the thesis also mentions,
because the confirmation is a second decision and this round changes one at a time. `close / sma(50)`
is chosen as the ranking key because `sma(50)` is already the card's own entry filter, so the arm adds
no indicator the card does not already compute.

## 4. The breadth measurement, which needs no backtest

`A-rotation`'s first condition asks how often its 3-of-9 cap binds. That is a property of the entry
condition over bars, not of a run, so it is measured directly: for every session in each of the eight
windows, count how many of the nine names satisfy `close > sma(50) and rsi(14) > 55 and rsi(14) < 80`.

Reported as median names qualifying, and the share of sessions with ≥4 and ≥6 — the same three
statistics the thesis states for its design window (median 4, 50.6%, 21.3%).

## 5. Falsifiable predictions

1. **`r26-arot-rankby` differs from `r26-arot-base` by more than the 21.2pp floor** on median adjusted
   excess. The clause's second horn: the card fills alphabetically today, and the programme measured a
   53.9-point spread across twelve orderings on this card's predecessor. If ordering is that
   consequential, imposing a stated ranking should move the result. **If it does not, the cap does not
   bind often enough for fill order to matter**, and prediction 2 should show the same thing.
2. **Breadth out of sample is lower than the thesis's design-window figures** — median below 4 names
   qualifying, and ≥4 on fewer than 50.6% of sessions, in at least 5 of 8 windows. The design window
   was a single trailing year in a semiconductor bull run.
3. **`r26-b3-tp20` and `r26-b3-fastexit` both post a lower median than `r26-b3-base`.** This is the
   thesis's own claim, tested for the first time. It says uncapped ran "roughly triple" either capped
   variant, so the predicted gaps are large — but the floor still binds, and a gap inside 21.2pp
   supports nothing in either direction.
4. **The "roughly triple" magnitude is not reproduced.** Distinct from 3: the direction may hold while
   the size does not. Falsified if either capped arm's median is below one third of the control's.
5. **`r26-ctrend-stop08` posts a lower median than `r26-ctrend-base`.** The thesis says widening 8% →
   12% cut stop-outs 12/77 → 7/77 while leaving mean trade return unmoved at 0.093, which claims the
   wider stop is free. If the tighter stop is *not* worse, that claim is unsupported and the stop
   width is a free parameter — which on this programme's record is what an unfalsifiable parameter
   looks like.

## 6. What this round cannot settle

- **Nothing about the exclusion claim** (§2), which is unaskable here.
- **Nothing about hold durations**, already measured from round 24's committed trades: winners held a
  median 82 sessions against 12 for losers, against the thesis's 118 and 16 — the shape survives, the
  magnitude does not, and the win rate collapses from 49.4% to 19.5%. That is recorded in the audit,
  not re-run here.
- **One matrix, eight windows, one economy.** Round 4's lesson stands: conclusions are properties of
  their windows.
- **No promotion or demotion, in either direction**, on any margin — the trading purpose has no
  promotion rule, and every margin here is subject to the 21.2pp floor.
