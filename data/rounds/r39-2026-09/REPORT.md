# Round 39 — report: the style tilt is null, and the timing rule loses to holding the slice

Run 2026-09-09, eight main windows, 8 cards, 64 runs, zero `FAILED` lines. Pre-registration:
`strategy-program/ROUND-39-PLAN.md` (2026-09-09). Computed tables: `ANALYSIS.md`, from
`strategy-program/tools/round34_36_report.py --round 39`, mirrored in `analysis.json`. Scorecard:
`scorecard.json` (`score.py --pin-store`). All cards `purpose = roth`, universe disjoint from the
taxable book.

**Not investment advice.** Price-only bars, no dividends, SPY benchmark for a Roth book, a synthetic
paper book. From `creator-b`'s valuation / structural-stagnation theses, given a fair test — a portfolio
proxy for a fundamental claim this repo cannot reach, not an endorsement of the influencer.

---

## 1. Result — null on both pre-registered questions

| question | quantity | result | verdict |
|---|---|---|---|
| does the timing rule beat holding the slice? | ma − passive, per slice | value +0.93pp, growth −5.36pp, core −3.45pp, full −2.28pp | all inside the 21.2pp floor |
| does value beat growth (the style spread)? | value-passive − growth-passive | **−5.43pp** | inside the floor; growth won |
| BH over all 8 cells | minimum q | **0.33** | nothing survives q<0.10 |

**Decision rule (plan §7), applied:** a style edge required the tilt-minus-control and the
value-minus-growth spread to exceed 21.2pp and survive BH. Neither does. **The null is the result.**

## 2. The rule arms lose to their own passive controls, and that is the real finding

Every moving-average arm posted a *lower* median adjusted excess than simply holding its slice:

| slice | rule (ma) | passive | mean exposure ma vs passive |
|---|---|---|---|
| value | −1.34pp | −2.27pp | 0.12 vs 0.82 |
| growth | −2.20pp | **+3.16pp** | 0.17 vs 0.83 |
| core | −0.66pp | **+2.79pp** | 0.18 vs 0.83 |
| full | −1.04pp | **+1.24pp** | 0.14 vs 0.80 |

The `close > sma(200)` regime filter keeps the rule arms in cash ~85% of the time; over a window mix
that is mostly rising, the passive arm's ~80% exposure simply captures more. On this book the timing
rule is a cost, not an edge. Three of the four *passive* baskets (growth, core, full) beat SPY on
adjusted excess — but that is the asset class, not a strategy, and a `close > 0` baseline is not a
seatable card.

## 3. The benchmark confound the plan pre-registered

The Roth benchmark is SPY (US large-cap, growth-led). Measured over 2007-2026, value trailed growth by
5.43pp of median adjusted excess — exactly the decade-long style headwind plan §2 named. The passive
control exists precisely so this shows up as "value lost to growth" rather than "the rule failed." It
did its job.

## 4. Disposition

- **Nothing promoted.** Null by the rule; and the results argue *against* seating any rule card, since
  each loses to holding its slice. No r39 cell reaches the paper desk.
- Style/factor is now measured on the Roth book and joins the programme's null record (rounds 17/34/35/36):
  neither the timing rule nor the value-vs-growth axis clears the floor here.
- Files: `cards/`, `results/<window>/runs/`, `scorecard.json`, `ANALYSIS.md`, `analysis.json`.
