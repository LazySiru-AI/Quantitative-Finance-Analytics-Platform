# Analyst brief — Strategy Program, round 4

Round 4 changes what is being scored. The first three rounds asked *which card is best*. This one
asks **which cards belong together**, because that is where the evidence went.

## 0. What is different from round 3

| | round 3 | round 4 |
|---|---|---|
| field | 10 cards + 6 new | **10 returning + 4 new** |
| windows | the 8 regime matrix | **6 windows, all of them new** |
| gate | 5 of 8 | **4 of 6** |
| scored on | median / worst / hit per card | the same, **plus the combined book** |

The field was trimmed from 35 measured cards to 10. Every drop is logged with its numbers in
`backend/app/paper/library/retired/README.md`, and the reasoning is in
`strategy-program/ROUND-4-PLAN.md` §3. Three disciplines — mean-reversion, volatility and
pairs-rotation — were emptied entirely and are being re-opened by this round's new submissions.

## 1. Why every window is new

`PROTOCOL.md` §6(a): cards are frozen, windows are fixed date ranges, and the engine is
deterministic. Re-running a card on a window it has already run **recomputes the same number rather
than sampling anything** — round 2 verified this on twenty of twenty pairs, to four decimal places.
A promotion resting on "two consecutive rounds" that share windows is one measurement counted twice.

Round 4 exists to confirm `B2-hold-90` and `c14-riskmanaged-wide`, so it must bring windows neither
has seen:

| window | period | sessions | regime |
|---|---|---|---|
| `recovery-2009` | 2009-03-10 → 2010-04-23 | 284 | post-crisis recovery rally |
| `taper-2013` | 2013-05-22 → 2013-09-05 | 74 | rate shock, taper tantrum |
| `oil-2014` | 2014-06-20 → 2015-02-11 | 163 | oil collapse and dollar surge |
| `volmageddon-2018` | 2018-01-26 → 2018-04-02 | 45 | volatility shock |
| `inflation-2021` | 2021-01-04 → 2021-12-31 | 252 | inflation onset and rotation |
| `banks-2023` | 2023-03-01 → 2023-05-31 | 64 | regional banking crisis |

None appears in rounds 1-3. The round 1-3 windows are untouched and their results stay readable.

**The gate is 4 of 6** — the same ~65% proportion as round 1's 3-of-5 and round 2's 5-of-8. Only
four of these windows are reachable by all ten returning cards; `recovery-2009` and `taper-2013`
need universes listed well before 2009, which most AI and semiconductor books are not.

## 2. What is scored, and the new part

Ranked on **median adjusted excess, worst-window excess and hit rate together**, with a Borda
composite and an explicit Pareto frontier — unchanged.

**Adjusted excess** is `total_return − capital_exposure × benchmark_return`. Three rounds running,
raw excess has told a flattering story that exposure correction dissolved, so it is the headline
metric here. A book that sits in cash gets no credit for "beating" a falling benchmark:
`c12-meanrev-wide` posted +55.3% raw excess in a crisis window on **one trade at 0.6% capital
exposure**, which adjusted to −0.5%. It was retired for it.

**New: the combined book.** Round 3's strongest result was not about any card. Combining
`B-momentum`, `C-trend` and `c14-riskmanaged-wide` in equal thirds roughly **halves the worst
window** — `C-trend` alone posts −22.9%, the trio −11.1% — because `C-trend` and `c14` are
effectively uncorrelated (ρ = +0.04) while `B` and `C` are two versions of the same trade (ρ = +0.57).

So a card that is **uncorrelated with the incumbents is valuable at a modest median**, and every new
submission is asked to predict its own correlation to `B-momentum`. `strategy-program/tools/portfolio.py`
scores this; the correlation matrix is reported beside the leaderboard, with pair counts, because
six windows is a small sample and a bare ρ would overstate what is known.

## 3. The concentration finding this round is built on

Measured on what the live desks actually hold:

| desk | held | share of equity | mean pairwise ρ |
|---|---|---|---|
| `C-trend` | NVDA, AVGO, TSM, SOXX | 73.6% | **0.765** |
| `B-momentum` | MSFT, AMZN, NVDA, AVGO, TSM | 75.1% | 0.586 |

`SOXX` is a semiconductor ETF holding the other three, so one of C-trend's four positions is a basket
of the rest. More slots would not fix this — across 55 sessions neither book ever filled its last
slot, and not one entry signal was ever turned away for lack of room. Nor does breadth inside a card:
round 3's `c16-dispersion-wide` was built for it at ρ = 0.245 and finished 7th of 10, while four-name
`c14` took the best worst-window in the round.

**Diversification by payoff beat diversification by count.** That is the finding round 4 is testing
at portfolio level.

## 4. Unchanged from round 3

The universe (633 stored symbols, 513 current S&P 500 and Nasdaq-100 constituents, price-validated
against the SEC N-PORT filings they came from); the survivorship rule and its provenance gate (see
`strategy-program/WINDOWS.md` — a card selecting names *because they are index constituents* inherits
`universe_knowable_from = 2026-03-31` and is unranked on every window here); the design cutoff of
**2026-02-13**; the rule DSL and its traps; next-open fills and prior-close stop checks; the card
contract in `backend/app/tournament/models.py`, including the 12-symbol universe cap.

## 5. What this round still cannot settle

No calendar time has passed since round 3, so the design cutoff has not advanced and no genuinely
unseen data exists. Round 4 brings windows the *cards* have not seen, which is what §6(a) requires
for a promotion — it does not bring data the *analysts* could not have studied. The walk-forward
begins when real time has elapsed.

Six windows against a noise floor of ±21 points is also a small sample. A margin inside that band has
demonstrated nothing, whatever the ranking says.
