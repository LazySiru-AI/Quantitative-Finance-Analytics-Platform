# Strategy tournament — 26 strategies, 127 blind sessions

Thirteen analysts each designed a strategy on data through **2026-02-13**, then designed a second
under an open universe. All 26 were traded from **2026-02-17 to 2026-08-18** — 127 sessions none of
them could see — through the same mock broker, with cash, settlement, whole-share and fee rules
enforced and fills at the next session's open with deterministic adverse slippage.

**Benchmark over the same sessions: SPY buy-and-hold, +12.84%.**

## What happened

| | agent | trades | return | max DD | win |
|---|---|---|---|---|---|
| r1 | a07-rotation | 32 | **+40.71%** | −17.38% | 41% |
| r1 | a12-13f-newbuys | 21 | **+33.81%** | −13.10% | 28% |
| r1 | a03-momentum | 11 | **+31.97%** | −25.23% | 0% |
| r1 | a09-fastrev | 20 | **+22.84%** | **−1.85%** | 95% |
| r1 | a05-volatility | 38 | **+19.20%** | −11.47% | 38% |
| r2 | a13-13f-crowding | 15 | +10.50% | −4.58% | 38% |
| r1 | a04-breakout | 3 | +9.14% | −6.58% | 33% |
| r2 | a03-momentum | 6 | +6.40% | −5.54% | 0% |
| r2 | a11-13f-conviction | 14 | +5.21% | −2.27% | 42% |
| r2 | a09-fastrev | 32 | +2.96% | −3.89% | 62% |
| r1 | a11-13f-conviction | 45 | +2.19% | −11.06% | 32% |
| r1 | a10-asymmetric | 32 | +2.01% | −9.89% | 24% |
| r1 | a01-trend | 10 | +1.87% | −17.39% | 33% |
| r1 | a02-meanrev | 1 | +1.76% | −0.27% | 100% |
| r2 | a07-rotation | 19 | +1.48% | −6.54% | 19% |
| r2 | a05-volatility | 30 | +1.22% | −2.59% | 43% |
| r2 | a02-meanrev | 1 | +0.35% | −0.98% | 100% |
| r1 | a08-slowtrend | 0 | 0.00% | 0.00% | — |
| r2 | a08-slowtrend | 0 | 0.00% | 0.00% | — |
| r2 | a12-13f-newbuys | 34 | −0.40% | −7.06% | 13% |
| r2 | a06-riskmanaged | 8 | −0.40% | −2.20% | 43% |
| r1 | a06-riskmanaged | 6 | −0.45% | −3.67% | 20% |
| r2 | a04-breakout | 15 | −0.63% | −3.24% | 33% |
| r2 | a10-asymmetric | 25 | −0.64% | −4.83% | 29% |
| r1 | a13-13f-crowding | 46 | −2.12% | −17.04% | 24% |
| r2 | a01-trend | 7 | −3.14% | −5.21% | 0% |

**Five strategies beat the benchmark. All five are round one.** No round-two strategy did.

## Read the statistics before the returns

**Six agents survive Benjamini-Hochberg at α=0.10, and five of them were flagged for being bad.**

| agent | win rate | q | direction |
|---|---|---|---|
| a09-fastrev (r1) | 95% | 0.0010 | above 50% |
| a13-13f-crowding (r1) | 24% | 0.0070 | **below** |
| a12-13f-newbuys (r2) | 13% | 0.0071 | **below** |
| a10-asymmetric (r1) | 24% | 0.0455 | **below** |
| a11-13f-conviction (r1) | 32% | 0.0832 | **below** |
| a07-rotation (r2) | 19% | 0.0832 | **below** |

The binomial test is two-sided against a fair coin, so a win rate far *below* 50% is as
"significant" as one far above. For `a10-asymmetric` — tight stop, distant target — a 24% win rate
is the design working, not a defect. **These q-values cannot be read as evidence of skill.** They
test whether a win rate is unlikely from a coin flip, which is a much weaker claim than beating the
market, and a long-only strategy in a market that rose 12.84% clears or fails that null for reasons
having nothing to do with edge.

One strategy — `a09-fastrev` in round one — is flagged in the favourable direction: 19 wins from 20
trades, +22.84% against the benchmark's +12.84%, on a −1.85% maximum drawdown. That is the single
result in this tournament worth a second look, and it is one result out of 26 in one regime.

## The concentration result

Round one confined every analyst to 43 tickers the user has traded — a semiconductor- and AI-heavy
set. `MU` appeared in 8 of 10 universes, `NVDA`/`AVGO`/`TSM` in 7. Round two opened the universe to
93 symbols across bonds, commodities, international, factor and sector funds, and analysts
diversified hard: mean pairwise correlation fell from ~0.50–0.59 to 0.23–0.27 in several books.

**The concentrated round won every top position and the diversified round won none.** Three
analysts priced that trade in advance, before seeing any result:

* `a01-trend` measured correlation 0.501 → 0.274 at a cost of expectancy 12.7% → 9.7%.
* `a04-breakout` found its diversified version survived 2022 (54.2% win over 24 signals, against 0%
  over 5 for the concentrated version) at a cost of profit factor 1.35 → 1.02.
* `a03-momentum` tested bonds against its own rule, found no edge (TLT −0.7% mean, 26% win), and
  declined to add them despite round two making them available.

Diversification is insurance. This window did not have the accident it insures against. **That is
not evidence it was the wrong trade** — it is one observation of a payoff that is supposed to look
like this most of the time.

## What the analysts established before anything traded

**13F is not usable here, established three independent ways and then again on a second universe.**

* Conviction basket: **−3.93%** from filing date to cutoff, against +10.13% for the roster and
  −1.13% for QQQM. Only 3 of 8 names beat the index.
* Fresh initiations: **934 NEW rows across fourteen managers mapped to 22 tradeable names**, a 52%
  beat-benchmark rate — a coin flip, with the mean inflated by two outliers.
* Crowding: Spearman ρ +0.17 to +0.25 against forward returns, none significant at n≈24. The
  analyst declined to pick between the "validation" and "fragility" stories rather than assert one.
* On round two's roster: **4 of 5,071 holdings resolve at all**, every one from Renaissance or
  Bridgewater — books holding 51% and 63% of the roster respectively, where a position is not a
  decision. **All twelve selective managers contribute zero.**

**Scion's four largest holdings — 95% of the disclosed book — are PUT and CALL lines.** Michael
Burry's "largest position" was a bet *against* Palantir. Anyone copying that book long would have
taken the opposite of the trade.

## Two defects in the harness, found by running it

**Five of 26 cards could not fill a single order.** The broker enforces a 25% single-name cap from
the persona mandate; `StrategyCard` validates only that `position_pct * max_positions <= 1.0`.
Analysts were shown the second rule and never the first, so `a06` (40%), `a07` (30%) and `a13` (33%)
designed books the broker refused wholesale — `a06` took zero trades against 9 rejections, `a07`
filled 6 orders against 449. The tournament now runs with that cap raised to what the card contract
itself permits, which is a deliberate loosening of a real risk control and is disclosed on every
report. The difference is not marginal: `a07-rotation` went from −6.52% on 6 trades to **+40.71% on
32**. The first run's numbers were discarded.

**Thirteen PDFs were written for 26 strategies.** Agent ids repeat across rounds, so keying the
filename on id alone had every round-two report overwrite its round-one namesake, and the same
collision in the scoring lookup handed round-one reports round-two's numbers. Reports now live in
`results/pdf/r1/` and `results/pdf/r2/`.

## What this does not show

* **One regime.** 127 sessions is a single draw, not a sample of market conditions. Every analyst
  named the regime their strategy hates; none of those regimes occurred.
* **Twenty-six draws.** The best of 26 noisy results is a large number whether or not any strategy
  has an edge. That is what the correction is for, and the correction says one strategy deviates
  favourably from a coin flip.
* **A quirk worth knowing when reading the table.** `a03-momentum` shows a 0% win rate beside
  +31.97%. Five closed trades all lost; six positions were still open at the window's end and carry
  the gain. Win rate and profit factor are computed on closed trades, return on the equity curve.
* **Simulated fills.** Next-session open with deterministic adverse slippage, stops evaluated
  against the previous close because the decision-maker cannot see the session's low. Real fills
  differ, and `a04` judged its own diversified edge (profit factor ~1.02) unlikely to survive real
  costs.
* **A selected universe.** Round one's tickers were chosen because the user already traded them.

None of this is advice, and none of these strategies has been shown to work.

## Artifacts

* `docs/tournament/cards/` — 13 round-one cards; `cards/round2/` — 13 round-two cards
* `docs/tournament/results/runs/` — 26 full runs, every trade and rejection
* `docs/tournament/results/pdf/r1/`, `pdf/r2/` — 26 per-agent PDF reports
* `docs/tournament/results/tournament.json` — scored, corrected across all 26
