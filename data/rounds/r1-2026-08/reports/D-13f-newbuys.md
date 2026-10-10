# D-13f-newbuys — competition report

`D-13f-newbuys`, "D - 13F fresh initiations: best out-of-sample result" (discipline: `momentum`),
**took zero trades in round 1, in every window, including the special `13f-legal` window built for
it.** There is no results table to present. This report is a complete account of why, because the
"why" is itself the finding.

## 1. What the card is, and why it could not run anywhere

The entry rule is `close > sma(50) and close > sma(200) and rsi(14) > 50` — confirmation that a fresh
13F position the market has already started to validate with price action is worth following.
Universe: `GOOGL AMD AMZN META SNDK NFLX SNOW AVGO`, the eight names with a tradeable "NEW" row in a
concentrated manager's 13F filing covering Q3 2025, filed 2025-11-13/14.

`sma(200)`'s warmup is `period − 1 = 199` bars; the lookahead guard needs 40 more post-warmup bars to
establish causality (`app.backtest.guards._MIN_BARS_FOR_CAUSALITY`). Together that is **239 bars** of
prior history, converted to a conservative 347 calendar-day lead (`_bars_to_calendar_days`, 252/365
trading-to-calendar convention, rounded up). Every symbol in the universe must clear that deadline
before a window's start date — the guard blocks on whichever symbol's history is shortest, and here
that symbol is `SNDK`, first bar **2025-02-13**.

`eligibility.json` gives the exact reason for every window:

| window | window start | deadline (239 bars back) | verdict |
|---|---|---|---|
| gfc | 2007-10-09 | 2006-10-27 | `SNDK first bar 2025-02-13, needs <= 2006-10-27` |
| covid | 2020-02-19 | 2019-03-09 | same |
| bear-2022 | 2022-01-03 | 2021-01-21 | same |
| bull-2024 | 2024-08-21 | 2023-09-09 | same |
| recent | 2025-08-21 | 2024-09-08 | same |
| **13f-legal** | **2025-11-17** | **2024-12-05** | `SNDK first bar 2025-02-13, needs <= 2024-12-05` |

The last row is the one that matters. `13f-legal` is the window `tools/windows.py` constructed
specifically for 13F-derived universes — it starts 2025-11-17, three days after the filing this
card's universe was derived from became public, precisely to give a 13F card a legal window to trade
in at all. SNDK's first bar (2025-02-13) still falls **about ten weeks** after the 2024-12-05
deadline that window requires. The card fails eligibility even in the one window designed to admit
it. `D-13f-newbuys` produced no `AgentResult` file in any of the six window directories under
`rounds/r1-2026-08/results/`; `scorecard-full.json` records it with `total_trades: 0`,
`n_windows_run: 0`, `mean_exposure: null`, `ranked: false`.

## 2. Results table

Not applicable. Zero windows produced a run; there is no corrected return, benchmark comparison,
exposure, drawdown, or win rate to report. Per DEFECTS.md's own standard (never substitute zero for a
null), none of these fields should be read as "0%" — they are unmeasured, not measured-and-flat.

## 3. Verdict on the claim

The card's provenance in `library/README.md` is specific: it was promoted on the strength of
**+56.93% against a +11.99% benchmark**, described there as "the most genuinely blind result in the
project" because the window it ran in the prior tournament was ~72% out-of-sample relative to the
card's design cutoff. That result **cannot be reproduced or falsified in this round's matrix**. The
card did not lose this round — it never traded. The claim under test (that price-confirmed 13F
fresh-initiation names outperform) remains exactly where the prior tournament left it: one genuinely
out-of-sample result, un-replicated, now structurally unreachable by the current window set and the
current universe. Round 1 neither vindicates nor undermines it; round 1 simply could not ask it the
question.

## 4. Trade-level detail

None. No trades were taken in any window, so there is no exit-reason distribution, no best or worst
trade, and no stop-out to measure against `stop_loss_pct = 0.12`.

## 5. Rankable, and what would make it so

**Not rankable**, and not merely by a thin margin — it cleared zero of the five main windows and the
13F-legal window, against a three-window gate. `scorecard-full.json` lists it under `unranked` with
every numeric field null. Three concrete changes would make it testable again, none of which requires
relaxing the eligibility guard itself:

1. **A shorter moving average.** The entry rule's binding constraint is `sma(200)`'s 199-bar warmup.
   Dropping to `sma(50)` alone (already present in the rule) or a shorter regime filter such as
   `sma(100)` would cut the required lead from 239 bars (~347 calendar days) to roughly 89 bars
   (~130 days) for a `sma(50)`-only version — comfortably inside SNDK's available history before
   `13f-legal`'s 2025-11-17 start (SNDK has traded since 2025-02-13, over 190 sessions by then).
2. **A universe without SNDK.** SNDK is the binding symbol in every window by a wide margin — the
   other seven names (GOOGL, AMD, AMZN, META, NFLX, SNOW, AVGO) all have first-bar dates in or before
   2004–2013, per WINDOWS.md's symbol tiers, and would individually clear every main window's
   `sma(200)` deadline including `gfc`. SNDK is in the universe because it is one of the eight names
   with a genuinely tradeable "NEW" 13F row this cycle (per the card's own thesis, only 9 of 69
   disclosed NEW rows across six concentrated managers mapped to a roster ticker at all) — dropping
   it trades the card's already-thin, curated universe for one name thinner still, which is a real
   cost, not a free fix.
3. **Retirement**, if neither of the above is taken. PROTOCOL.md §6 retires a card that "takes zero
   trades in every window of two consecutive rounds." This round is the first such round on record
   for `D-13f-newbuys`; one more round with the same universe and the same indicator will meet that
   bar mechanically, regardless of the strength of the prior result that put it in the library.

Retirement is not a step to take yet, but it is one round away by rule, not by argument, unless the
card is amended between rounds per PROTOCOL.md's phase-2 integrity boundary (amendments happen
between rounds, never during one).

## 6. Recommendation

**Demote from `candidates/` toward retirement risk, conditional on the next round.** Under PROTOCOL.md
§6, `D-13f-newbuys` is not eligible for promotion (it posted no result to promote on) and is not yet
eligible for mechanical retirement (that requires two consecutive zero-trade rounds; this is the
first). The recommendation is to keep it in `candidates/` for round 2 **only if** one of the two
concrete fixes above (shorter moving average, or a universe that drops SNDK) is applied between
rounds — a like-for-like re-run of the identical, untestable card would simply consume a second round
to arrive at the same mechanical retirement this report already forecasts. If no fix is applied,
flag it now for retirement at the end of round 2.
