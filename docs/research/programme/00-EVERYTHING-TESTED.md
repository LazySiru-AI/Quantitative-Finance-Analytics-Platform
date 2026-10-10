# Everything this programme has tested — and everything it has not

Consolidated 2026-08-30. Covers rounds 1–32, the five strategy families, the 1,935-generation
evolution loop, six studies outside the round sequence, and the method that bounds all of it.

Not investment advice. Every figure below is a backtest on price-only bars with no dividends.

**Why this document exists.** `data/rounds/PROGRAMME-REPORT.md` is titled "rounds 1–11" and stops
there. Rounds 12–16, the evolution loop, the timeframe sweeps, the thesis loop and the discovery
module had never been consolidated anywhere. This roughly doubles the covered ground and adds the
half nobody had written down: what was *skipped*.

**How to read it.** The six inventories beside this file are the evidence, plus a thesis audit of
what the seated cards claim; this is the synthesis.
Each is independently sourced and quotes figures with attribution, because this programme has a
documented history of the same number being stated inconsistently across documents.

| inventory | covers |
|---|---|
| [`inventory-rounds-1-8.md`](inventory-rounds-1-8.md) | rounds 1–8, 20 concepts, the D1–D4 defects |
| [`inventory-rounds-9-16.md`](inventory-rounds-9-16.md) | rounds 9–16, 15 concepts, the round 13 and 16 anomalies |
| [`inventory-families.md`](inventory-families.md) | 5 families, 21 concepts (A–U), 18 never measured |
| [`inventory-evolution-loop.md`](inventory-evolution-loop.md) | 291 generations, 2,944 evaluations, the 5 predictions |
| [`inventory-studies.md`](inventory-studies.md) | 6 studies outside the rounds, capability-vs-use |
| [`inventory-method.md`](inventory-method.md) | 4 window matrices, the noise floor, D1–D6 |
| [`thesis-audit.md`](thesis-audit.md) | the 6 seated cards, 11 distinct claims, all now resolved |

---

## 1. The headline: enormous scale, almost no yield

This is the single most important fact about the programme, and it is not visible from any one
document.

| study | scale | survived correction |
|---|---|---|
| Strategy Lab | 150 primary + ~625 exploratory + 75 seasonality + 15 VIX cells | **0** |
| Timeframe rule-accuracy sweep | 9,480 cells | **3** |
| Discovery — 23y sector/theme rotation | 6 roster×key combos | **0** (IC −0.0073, bootstrap p=0.892) |
| Thesis loop | QQQ / SOXL / SPY | **0** (best: in-sample p=0.0616, n=110 → holdout p=0.856, n=34) |
| Evolution loop | 2,944 evaluations, 2,371 genomes | bred beats random by ~6–7pp — **below the 21.2pp noise floor** |
| **Round 17** (new) | 48-cell factorial over 8 rule forms | **0** — every marginal inside the floor |
| **Round 18** (new) | 16-cell exit discrimination | **0** — exit marginal 3.58pp |
| **Round 21** | 8-cell macro-gate factorial | **not askable** — the matrix held the treatment constant |
| **Round 22** | the same cards, in windows where the curve moves | **0** — inside the null in 3 of 3 |
| **Round 23** | 3 arms × 3 windows, the curve as a *sizing* term | **0** — inside the null in 3 of 3 |
| **Round 24** | 2 seated cards × 2 hold-caps, 6 regime windows | **0** — both costs inside the floor, and confined to one chop window |
| **Round 25** | 3 arms × 3 windows, the curve as a *rate of change* | **0** — inside the null in 3 of 3, on a null with no untreated replicates |
| **Round 26** | 7 arms × 8 windows, the seated cards' own falsification conditions | **0** — every margin inside the floor; 3 of 5 predictions refuted |
| **Round 27** | 3 signal-statistic measurements, no backtest | **n/a** — thesis claims, not strategies; 3 of 5 predictions refuted |
| **Round 28** | cross-sectional rank IC, 5 signals × 2 horizons × 2 universes | **0** — no cell survives BH; the class the engine blocks is empty here |
| **Round 29** | the same IC test on a diversified universe (the fair test) | **1 effect** — the only survivor is the beta premium, not an alpha |
| **Round 30** | 3 daily untouched macro series × level/roc × SPY/QQQ × 2 horizons, forward-return spread | **0** — none survives BH; the price-orthogonality control shows the states are noise, not price in disguise |
| **Round 31** | 3 monthly inflation indices × level/accel × SPY/QQQ × 2 horizons, release-date bound | **0** — none clears BH (min q=0.139), but the inflation-level effect is a genuine near-miss, not noise |
| **Round 32** | the near-miss's dedicated OOS + confound test on a 1970 portfolio | **0** — passes the rule by the letter, but collapses to p=0.51 out-of-sample; no card |
| **Round 34** | round 17's 8-form × regime factorial replicated on 8 taxable-disjoint industry ETFs (16 cells, `purpose = roth`) | **0** — form marginal 4.21pp, regime 0.88pp; the field is *tighter* than round 17's (6.40pp vs 9.47pp); min q 0.81 |
| **Round 35** | country rotation on 8 taxable-disjoint country ETFs, 2 forms × 2 caps × 2 fill orders + a passive control | **0** — every rotation cell negative vs SPY; best rotation-minus-control +0.08pp; the −2.28pp control *is* the result (asset-class/FX gap) |
| **Round 36** | `rank_by` (the engine's one cross-symbol operator): 5 orderings × 2 caps on the round-34 universe | **0** — strong − weak +1.2pp / +1.0pp, q 0.40 / 0.52; measured ordering noise on this universe **0.13–0.26pp**, five-ordering spread ~2pp |

**That is not a failure of the programme. It is the programme working.** An apparatus this careful
about multiple comparisons, lookahead and out-of-sample discipline is *supposed* to return mostly
nulls. The thing worth noticing is that the nulls are now numerous and consistent enough to be
evidence in their own right: on price-only OHLCV data, over these universes, with these window
matrices, this repository has not found a durable edge.

## 2. A–Z of what has been tested

~50 distinct strategy concepts, deduplicated across sources. Grouped by what they are, not by which
document they came from.

**Trend and momentum.** MA crossover (the loop's sole template for generations 1–1915, and round 17's
`ma-crossover`); confirmed acceleration (`B-momentum`, EMA 20/50 inside a 200-day regime); persistent
momentum state; MACD signal-line crossover; absolute momentum; dual momentum with cash fallback;
momentum rotation; four momentum attribution variants.

**Mean reversion.** RSI pullback inside a regime filter; Bollinger band reversion; three further
mean-reversion variants from rounds 1–8.

**Breakout.** Swing-high channel breakout; Bollinger upper-band breakout; a third breakout variant.

**Volatility.** ATR compression entry; vol targeting (QLD/IEF); inverse-vol weighting; a vol
circuit-breaker at 45%/30%; a risk-budgeted core; vol-trimmed savings core; two convex/volatility
variants from rounds 1–8.

**Allocation.** Static core-satellite (SPY/SCHD/AGG/GLD/BIL); ATR-tilt core-satellite; continuous
vol-target core; continuous inverse-vol risk parity; broad-market 80/20; diversified multi-asset core;
horizon glidepath 90→60 over 20 years.

**Laddered leverage.** The drawdown ladder as originally specified (refuted — GFC max drawdown
−72.7%); with bounce confirmation; with a time stop (refuted — it *hurts*, GFC MAR −0.05 to −0.07);
with a reserve sleeve (seated, GFC MAR 0.25, max DD −55.0%); re-expressed on Roth-disjoint tickers.

**Regime and structure.** MA regime switch on SPY's 200-day; confirmed dual-signal regime;
breadth/concentration as its own axis; universe width; purpose-built uncorrelated diversifiers; a
generalist mandate; combined-book portfolio scoring.

**External-data.** Two 13F-derived cards (a manager's fresh position plus a trend confirmation) —
the only concepts in this list that ever consumed non-price data, and both did so through **manual
universe selection**, never through the guarded statistical engines.

**Methodological controls.** SPY/QQQ buy-and-hold benchmarks; universe-ordering noise as a control
(the study that produced the 21.2pp floor); four promotion-gate redesigns; ranking-key studies;
cash-constrained vs unconstrained contribution simulation.

## 3. What has never been tested — three distinct classes

The distinction matters. "Measured and found nothing" is a result. These are not that.

### 3a. Inexpressible by the engine — an entire strategy class is foreclosed

Not skipped. **Impossible**, on the current engine.

- **No cross-sectional ranking and no cross-symbol regime gate.** A rule is evaluated per symbol
  against that symbol's own bars. An analyst's VIX-gating attempt was abandoned for exactly this.
  This forecloses relative-strength, pairs, dispersion and market-regime overlays as a class — and
  `pairs-rotation`, the evolution loop's single most common discipline label (348 of 934 legacy
  genomes), is permanently unreachable by the grammar that was labelling it.
- **~~No volatility-scaled sizing.~~ Half-fixed on 2026-08-30, and the half that remains is the
  cross-symbol one.** `TiltRule` now carries `shift_expr`, a rule-DSL numeric expression evaluated
  per session on `on_symbol`'s own bars, so a tilt can be **sized** by an indicator rather than only
  **triggered** by one. It is parsed and guarded as a *ranking* key, not a condition — a non-causal
  magnitude is lookahead in the sizing step, which is harder to spot than lookahead in an entry
  because the condition beside it stays clean.

  **Continuous vol-targeting on a two-sleeve core (concept C) is now expressible.** **Continuous
  inverse-vol risk parity (concept D) is not**, and it is the family's best risk-adjusted result:
  `ALLOCATION-FAMILY` named *two* blockers, the fixed shift and that neither variant is a two-sleeve
  shift. Only the first is gone. Parity weights each sleeve against every *other* sleeve's
  volatility, which is the cross-symbol comparison the bullet above forecloses as a class — so
  concept D is blocked by the same limitation as `pairs-rotation`, not by a sizing one.
- No shorting, leverage or options; no 13F option-line replication; no mid-window universe rotation;
  no Bollinger-squeeze-relative-to-own-history; **no dividends anywhere.**

### 3b. Data that exists, is collected, and cannot reach a strategy

The rules DSL's `PriceField` enum exposes open/high/low/close/volume — **and, since round 21, one
named macro series.** That row is struck through below; the rest still stands.

| data | status |
|---|---|
| FRED macro series (rates, curve, energy) | ~~unreachable~~ — **reachable since round 21** (2026-08-30) |
| Fear & Greed | collected, displayed, **unreachable** |
| Event calendar (FOMC, releases, earnings) | collected, displayed, **unreachable** |
| Cross-institution 13F consensus | built, API-only, **never consumed by a card** |
| `reverse_conditioning` | built, wired to API and UI, **no recorded finding ever produced through it** |
| Analyst consensus / price targets | does not appear to exist in the codebase |

### 3c. Designed, reasoned about, never run — 18 items with stated reasons

Mostly missing bars or unswept thresholds. The highest-value ones, in the repo's own words:

- ~~**A cash-aware contribution harness.**~~ **Measured 2026-08-30 — and it inverted the caveat.**
  See §5c. The cash cap is worth 0.000pp across 31 cells; settlement is worth −0.17pp and moves the
  harness *away* from the engine; and on the only cell with an engine-side counterpart the harness
  ends **0.70% below** it, not above. The savings/Roth figures are not biased optimistic on this
  evidence — the sign of the bias is a property of the window, not of the harness.
- **Synthetic 2× NDX back to 2000** — "the single most likely source of a result that would change
  the [drawdown ladder] conclusion".
- **A multi-asset glidepath** — "the most direct way to test whether variant 3's weak showing is
  really about the glide horizon".
- **VTI, SGOV and twelve dividend/duration tickers** (VYM, HDV, SPYD, SDY, NOBL, DGRO, IEI, GOVT,
  VGIT, VGLT, EDV, SPXL) — all queried, all returned empty from the bar store. Data availability,
  not choice.
- Slippage never swept above a flat 5bp, in any family.

## 4. What the apparatus can and cannot see

- **There is no single window matrix — there are at least four.** The 8-window round-2/3 set (4
  falling / 2 flat / 2 rising, mean SPY −9.45%); the round-4 set built deliberately disjoint from it
  (2 of 6 falling, mean +17.13%); round 5's 27-window horizon ladder (19 of 21 rising, **no
  decade-length window is ever falling**); and round 11's six live sub-periods, which are one regime
  sliced six ways rather than a regime sample. Round 4's own heading states the consequence:
  *"Round 3's conclusions were properties of round 3's windows."* Between-card correlation flipped
  sign (ρ = +0.04 → −0.554) between the two matrices.
- **The noise floor is 21.2 percentage points** — one identical card re-run under twelve `universe`
  orderings spread 53.9 points of three-year return. It disqualifies every variant margin published
  before `StrategyCard.rank_by` existed. Round 17 has now measured that this floor is **conservative
  for a nine-ETF design** (see §5).
- **Defects D1–D7 are all closed**, and every figure they touched inside this programme's own record
  was re-measured rather than annotated. D7 was catalogued on 2026-08-29 during this work: the
  `LadderCard` closure defect cost a **seated** card up to 16.07pp of CAGR, was corrected in round
  15's record, and had never entered the central log. The only unremediated contamination on record
  is **external** — the prior tournament (the ρ = 0.162 study this programme exists to correct)
  shares D1's rebasing bug and its figures were never restated.
- **The apparatus refuses comparisons it cannot make**, in code: it will not compute `adjusted_excess`
  for an invested-value-basis card, will not rank on a single window, and will not compare a return
  to another window's benchmark.
- **The primary metric structurally credits a small book, and round 22 measured it.**
  `adjusted_excess = total_return − capital_exposure × benchmark_return`, so a book measured against a
  passive position *of its own size* is flattered for being small. `PROTOCOL.md` §4 put the effect at
  Pearson **r = +0.797** across ten cards in round 2. Round 22 is the clean demonstration: its gated
  cards lost on raw return in all four forms while *winning* +0.68pp on `adjusted_excess`, purely
  because gate-on ran at a quarter of gate-off's exposure. Its matched null settles the reading —
  among random masks cutting comparable exposure, the observed +5.65pp sat at the **bottom edge** of
  `[+5.11, +12.37]`. **The credit is real and the gate did not earn it.** Any ranking in this report
  that compares books of very different exposure inherits this.
- **Pre-registration does not check that a pre-registered claim was sourced correctly** — a gap in
  `PROTOCOL.md` §2's guarantee, found in round 24 and named by the session that ran it. That round's
  §5 pre-registered a prediction *attributed to a card's author* — that capping the hold would cost
  return — which the author had never made about that lever: the thesis's "roughly triple" compares a
  take-profit and a fast EMA exit against an uncapped arm whose definition **includes** the 180-session
  backstop the round then shortened. **The claim was mis-sourced before the round ran**, so the round
  carried a borrowed authority it was never entitled to, and every sentence built on top of the
  numbers inherited it.

  **Freezing a claim is not the same as checking it.** §2 protects a prediction from moving *after*
  a result exists and does nothing about one that was wrong *going in* — and a mis-sourced prediction
  is harder to catch than a moved one precisely because the timestamp is clean and the discipline
  looks satisfied. The numbers were never at risk here (frozen arms; the engine does not read prose),
  which is the whole difficulty: nothing in the apparatus fails, and the round reads as sound.
  The check that would have caught it is the cheapest one available — **quote the source and diff it
  against the source** — and it is the same check `thesis-audit.md` §3 had to run to find the error.

## 5. Round 17 — the new evidence

**Question:** does strategy *form* change a result, once universe, parameters, sizing and brackets are
held identical? Never isolated before: rounds 1–16 varied form together with everything else, and the
evolution loop ran generations 1–1915 on one hardcoded template — all 28 promotions and all 25
outstanding seat requests come from that single-form regime.

**Design:** 8 forms × regime filter on/off × 3 bracket policies = 48 cells, nine mechanically chosen
sector ETFs, the full eight-window matrix, run once. Pre-registered in
[`ROUND-17-PLAN.md`](../../../strategy-program/ROUND-17-PLAN.md) and committed before any card ran.

**Result — every marginal inside the noise floor:**

| factor | spread | verdict |
|---|---|---|
| form (8 levels) | 7.56pp | inside 21.2pp floor |
| regime filter | 0.26pp | inside |
| brackets | 0.14pp | inside |

The whole 48-cell field spans **9.47pp**, against a simulated pure-noise expectation of **94.8pp** at
n=48. Form ordering, for the record: `band-reversion` +1.79%, `rsi-pullback` −0.47%, `ma-crossover`
−0.69%, `band-breakout` −1.02%, `channel-breakout` −2.87%, `macd-cross` −2.92%, `momentum-state`
−3.32%, `vol-compression` −5.77%.

**What that buys.** It bounds what the evolution loop's narrowness cost. A searcher that could only
emit `ma-crossover` was not, on this evidence, missing much — `ma-crossover` lands third of eight and
within 2.5pp of the best.

**Three things worth more than the headline:**

1. **Brackets essentially never bind.** `none`, `stop` and `stop-tp` differ by 0.14pp, and many cells
   are byte-identical across bracket policies — the rule's own exit fires first almost every time.
   `B-momentum`'s claim that a take-profit amputates the edge is not refuted so much as rendered
   untestable on this field: a bracket that never triggers cannot hurt.
2. **A prediction refuted by my own reasoning error.** I predicted `vol-compression` would post the
   lowest exposure, because its entry needs ATR under 2% of price. It posts the **highest** (52.95%
   vs `band-reversion`'s 24.23%): its exit waits for ATR to expand past 5%, so it enters seldom and
   then holds *through* the expansion. I predicted from the entry; the exit decided it.
3. **The floor is conservative for this design, and that is measured, not argued.** The
   pre-registered replication re-ran the top and bottom cells under a shuffled universe ordering
   (seed 1717): the gap went 9.47pp → 7.43pp and individual cells moved about **one point**, not
   21.2. Ordering noise on nine sector ETFs is far smaller than on the twelve-name concentrated card
   that produced the floor.

**This does not upgrade the form ordering into a finding.** The rule committed to before the data
existed was a 21.2pp marginal spread; form reached 7.56pp. Ordering is also only one noise source —
window mix and sampling remain unmeasured. What the replication earns is a better-powered follow-up,
not a retroactively lowered bar.

**An amendment, disclosed.** The first attempt used eleven sector ETFs and returned **0 of 48 runs**
in `gfc`, `chop-2011` and `chop-2015` and **21 of 48** in `q4-2018`, because `XLRE` and `XLC` hold zero
bars there and a zero-bar symbol fails the *whole card* at the lookahead guard. The tickers had been
checked against the store and not against the guard. The failed attempt is kept at
`{cards,results}-11etf-INVALID/`. The partial window was the more dangerous half: its 21 survivors
were the shorter-warmup forms, not a random subset, so ranking across it would have compared warmup
lengths wearing form names.

## 5b. Round 18 — the exit does not decide it either

Round 17's brackets result (0.14pp, many cells byte-identical) said the rule's own exit fires first
almost every time. Round 18 tested what that implied: entry pinned to the evolution loop's own
hardcoded template, only the exit varied, 16 cells.

**The central prediction was refuted.** The exit marginal is **3.58pp** — *smaller* than round 17's
7.56pp form marginal. Varying the exit alone moves the result less than varying whole forms did. The
decomposition is the useful part: form varied entry and exit together for 7.56pp, exit alone accounts
for 3.58pp, so the entry carries at least as much. **"The exit closes the position" is not the same
claim as "the exit determines the return"**, and the prediction conflated them.

**Two of the eight exits are provably the same rule.** `ema(10) < ema(30)` (a state) and
`ema(10) crosses_below ema(30)` (a crossing) produced **byte-identical results on every scored
field** — same median, same worst, same 155 trades, same exposure to sixteen digits, same realised
P&L to the cent. Given an entry requiring `ema(10) crosses_above ema(30)`, the first bar the state is
true *is* the bar it crosses. The eight-form vocabulary therefore has fewer independent levels than it
appears to, and any future round drawing on it needs to know which collapse.

**The instrument is verified stable.** Two cells duplicate round 17 by construction and reproduce its
committed figures exactly, so the between-round comparison is checked rather than assumed — the same
regression check round 16 ran against round 15.

Three of five predictions refuted; the two that held were "still inside the noise floor" and the
bracket marginal reproducing at 0.15pp against round 17's 0.14pp on an independent field.

## 5c. Round 19 — ~~the harness is pessimistic, not optimistic~~

> **Headline withdrawn.** Everything below is a correct measurement against a **defective engine**.
> §5d found the defect (D8) and round 20 fixed it (§6 item 1). Against the fixed engine, T+1
> settlement closes **73.9%** of the harness/engine gap rather than widening it by 23.9% — so round
> 16's prediction was right all along and this round's refutation of it does not stand. The
> direction also flips: the harness is **0.06% optimistic**, not 0.70% pessimistic. The section is
> kept as written because the reasoning was sound and the instrument was verified; only the engine
> underneath it was broken, and that is the more useful thing to be able to see.
>
> | | as measured here | against the fixed engine |
> |---|---:|---:|
> | engine rejections | 59 | **3** |
> | harness vs engine, settlement off | −0.6989% | +0.2283% |
> | harness vs engine, both at T+1 | −0.8661% | **+0.0596%** |

The top-ranked follow-up, run. Round 15 called every savings and Roth figure "systematically
optimistic" because the harness affords rebalances a real account cannot; the caveat has ridden on a
dozen concepts across three families ever since, unquantified.

Round 16 had already measured its own cash cap as worth **nothing** — 0 underfunded buys across 31
cells — because that constraint runs every sell before any buy and lets the proceeds fund them in the
same session, so it is settlement-free by construction. It wrote down the next step and the prediction:
*"give `simulate` a settlement lag, not just a cash cap… the gap closes materially."* That sentence is
the pre-registration; it predates this measurement.

**It is refuted.** With T+1 settlement the harness moves from −0.6989% to −0.8661% against the engine
— **23.9% further away**. Settlement genuinely binds (2 underfunded buys at T+1, 4 at T+2, against 0
for the same-session cap) and is still not the term. The engine and the settlement-off harness both
reproduce round 16's committed figures to the cent, asserted rather than eyeballed, so this is a
refutation and not drift.

| term | worth |
|---|---|
| the cash cap | **0.000pp** across 31 cells |
| settlement, T+1 | **−0.17pp** — and in the wrong direction |
| residual harness/engine gap | **−0.70%**, unexplained |

**The harness ends *below* the engine.** The window is 2022-08-23 to 2022-12-30, falling — so the
rebalances the harness could afford lost money, and the engine's 59 rejections helped it. Round 15's
caveat assumed the bias had a direction. **It does not: the sign is a property of the regime.** That
is a materially different caveat from the one carried since round 15.

Scope: one card, one window — the only cell with a validated engine-side counterpart. The
regime-dependence claim predicts the sign flips in a rising window, and that is testable and untested.

**Next suspect, with its evidence: turnover.** 59 engine rejections across 91 sessions against **2**
harness rebalances. Those are not two implementations of one process differing at the margin, and no
refinement of the funding model will close a gap that turnover explains.

## 5d. The turnover gap — reconciled, and it was an engine defect

Round 19 left one term unexplained: 59 engine rejections across 91 sessions against 2 harness
rebalances. Instrumenting the broker settles it, and **it was never a difference in trading
frequency.**

Both processes fire their band on the same schedule — the engine's 59 rejections land on 59 *distinct*
sessions in **two contiguous episodes**, and the harness performs **two** rebalances in the same
window. What differs is that the engine never *completes* one: 65 order attempts, 6 fills, and **59 of
61 band-firing sessions emitting buys with no sell at all.**

`_rebalance_moves` applies `band_pct` per sleeve. That is symmetric per sleeve and asymmetric in
aggregate — the overweight offsetting a breaching underweight can be spread across sleeves that are
each individually inside the band, so a buy is emitted and nothing is sold to pay for it:

| sleeve | target | actual | deviation | |
|---|---:|---:|---:|---|
| QLD | 0.4300 | 0.3781 | **−0.0519** | **outside** |
| SCHD | 0.3200 | 0.3320 | +0.0120 | inside |
| SGOV | 0.2500 | 0.2890 | +0.0390 | inside |

The engine submits $4,469.75 against **$73.69** and is rejected; the rejection leaves QLD underweight,
so it fires again the next session, for weeks. The same underweight *is* fundable when the offset sits
on one sleeve — so whether the book rebalances at all depends on how the overweight happens to be
distributed, which no sleeve's band can see.

**Why it shipped:** every existing test uses two sleeves, where deviations are always equal and
opposite, so a buy always has a matching sell. It needs three or more. Two seated cards have them.

**This closes the chain rounds 15, 16 and 19 were following.** The harness rebalances the whole book
on a breach, so its buys are funded by construction; the engine rebalances per sleeve and can issue a
buy it cannot pay for. **The harness was not being optimistic — it was doing what the engine failed to
do.** Catalogued as `DEFECTS.md` D8, with a strict `xfail` pinning the intended behaviour. ~~Not fixed
in place:~~ **fixed in round 20** (§6 item 1) as its own pre-registered round, because it restates
every allocation figure for a card with ≥3 sleeves and "which sleeves fund a breaching buy" is a
strategy question that belonged in a pre-registration rather than in a patch. Rejections on this card
fell from **59 to 3**, and the `xfail` is now un-marked and passing.

## 5e. Rounds 21 and 22 — the non-price gap closed, and a round that could not ask its question

**Not my work.** A concurrent session built these while this audit was being written, and they change
two of its conclusions. Round 21 is complete and committed; round 22 is pre-registered and running,
and is deliberately not summarised here beyond that — reporting figures from a round that has not been
scored is exactly what this document criticises elsewhere.

### Round 21 closes recommendation #4

§3b of this report listed FRED macro series as "collected, displayed, **unreachable by any card**".
**That is no longer true.** A card can now name a macro series, the guard verifies per session that no
value was read before it was published, and the round's data is pinned and digest-verified so the run
reproduces. The architectural gap that had foreclosed every cross-symbol regime idea is gone.

### But the round could not measure what it was built to measure

`macro(T10Y2Y) > 0` blocked **81 of 1,716 eligible sessions**, in only two of the eight windows, and
**24 of 32 (form, window) pairs came back byte-identical**. The mean gate marginal of **+0.044pp** is
an arithmetic consequence of six identical pairs, not a measurement of macro data being uninformative.

The cause is a selection mismatch: the eight main windows were chosen on **equity** regimes, and the
curve inverts elsewhere. The round's own headline is the right one — *it measured that this window
matrix cannot ask the question*, which is a different finding from "a macro gate does not change a
result", and only the second would have been reportable as a null.

**This is a third category** that this report's §3 framing did not have, and it is worth naming:
neither "measured and found nothing" nor "never measured", but **asked, with an instrument that could
not answer.** Round 21 declined to add curve windows retroactively, on the grounds that selecting
windows after seeing the result is the failure round 4 exists to document. Round 22 supplied them as a
fresh pre-registration — and answered.

### Round 22 answered it, and the answer is no

Same cards, re-used byte-for-byte, scored in three windows where `T10Y2Y` actually crosses zero. **The
design worked**: zero byte-identical pairs in any window, against round 21's 24 of 32. The gate blocks
57.4% / 49.1% / 72.9% of sessions and moves exposure hard.

| window | gate blocks | SPY | mean marginal, 4 forms |
|---|---:|---:|---:|
| `inv-2000` | 57.4% | −14.8% | −0.67pp |
| `inv-2006` | 49.1% | +13.0% | −1.80pp |
| `inv-2022` | 72.9% | +22.7% | +0.68pp |

**Inside the null in 3 of 3 windows, under all three null definitions.** No consistent sign anywhere —
within-window spread across four forms reaches 17pp and between-window means disagree in sign. The
observed `ma-crossover` marginals of +6.27, −5.19 and +5.65pp look large and are ordinary: a circular
shift of the same mask produces that spread routinely.

This is **the programme's first genuine null for the macro class**, and it converts round 21's cell
from "could not ask" into an ordinary null for this particular question. The category still stands —
round 21 remains the worked example of it — but this question has now left it.

What it does not establish, in the round's own words: one threshold (`> 0`), one series, one universe,
four forms, an entry-gate expression. **The curve as a *sizing* input, or as a rate-of-change rather
than a level, is untouched.** And the three windows are three episodes from one economy, so no median
was computed across them "and none should be".

### It also independently corroborates round 17

Round 21's eight-cell field spans **5.35pp** of form effect, against round 17's **7.56pp** on a wider
field — the same magnitude, measured by a different session on a different design. And
`r21-ma-crossover-off` is identical in construction to round 17's `r17-ma-crossover-on-none` and
**reproduces its committed figures to the digit**, across an engine change that added a new AST node,
a binding layer, a pin format and a guard check. The form finding in §5 is not an artefact of one
round's setup.

## 5f. Round 23 — the curve as a *sizing* term, and a flaw in how rounds 22 and 23 built their nulls

Round 22 named the sizing variant as the thing it had not touched, and §6 item 4 below recorded that
the composition — a macro field driving a continuous shift — **had never been run**. It has now.
`ROUND-23-PLAN.md` is the pre-registration; three amendments are recorded in it, all before the cells
they affect produced a usable number.

**The design isolates gradation from magnitude, which is the only way the question is answerable.**
Three arms on one purpose-built 35/40/25 `XLK`/`XLP`/`XLU` allocation, tilting `XLK → XLP` as the
curve inverts: **A** no tilt, **B** a constant `shift_pct` of 0.172, **C** `shift_expr` of
`-0.5 * macro(T10Y2Y)`. B's constant **is C's pooled mean shift over firing sessions**, computed from
the pinned series before any card ran — so the two tilted arms move the same average weight and differ
only in how it is distributed across sessions. Without that calibration a B-vs-C difference would be a
difference in *magnitude* wearing the name of a difference in *gradation*.

| window | A control | B binary | C sized | \|A−B\| | \|A−C\| | \|B−C\| |
|---|---:|---:|---:|---:|---:|---:|
| `inv-2000` | −3.15% | +7.42% | +8.18% | 10.57 | 11.33 | 0.76 |
| `inv-2006` | +24.20% | +23.66% | +24.23% | 0.54 | 0.04 | 0.58 |
| `inv-2022` | +16.24% | +7.96% | +3.62% | 8.28 | 12.61 | 4.33 |

**Predictions 1–4 held; prediction 5 is refuted.** Prediction 2 — *whether* you tilt matters more than
*how* you size it — holds in 2 of 3 windows, as stated. Prediction 5 said arm C must be the busier
arm or "the band is absorbing the gradation"; in `inv-2006` it is not, and the band is. Mean shift
there is 0.0372 against 0.2399 in `inv-2022`, so the shallow-inversion window is exactly where a 0.05
band swallows the difference. That is the round's most transferable result: **a continuous shift and a
constant one are the same card whenever the signal is shallow relative to the rebalance band.**

**The null.** 200 circular shifts of the curve's *values* — not round 22's ±1 mask, which would hold
arm C's treatment constant because arm C reads magnitude rather than a threshold.

| window | observed | pre-registered null | treated-only null | verdict |
|---|---:|---|---|---|
| `inv-2000` | +11.33pp | [−11.94, +19.82] | [−13.74, +20.96] | inside → inside |
| `inv-2006` | +0.04pp | [−3.09, +1.96] | [−5.51, +3.84] | inside → inside |
| `inv-2022` | −12.61pp | [−12.36, +4.04] | [−14.68, +4.74] | ~~outside~~ → **inside** |

**Inside the null in 3 of 3.** The pre-registered rule returned one `outside`, in `inv-2022`, and the
correction below removes it — the verdict was an artefact of how the null was built, not a property of
the curve. Note also which side it fell on: arm C *underperformed* control by more than 97.5% of
phase-randomised replicates, so even taken at face value it was never evidence that sizing works. It
said the real curve's phase carried information and using it to size a tilt through a rising market
destroyed value, which is prediction 3 holding rather than a finding. Nothing here is promotable.

### The null in rounds 22 and 23 is roughly half untreated

`null_median` came back **exactly `0.0`** in all three of round 23's windows. Counting firing sessions
straight from the pinned series explains it: the series spans 1976–2026, the curve is inverted in a
minority of it, and a circular shift lands the window on a non-inverted stretch about half the time.
The tilt then never fires, arm C reproduces arm A exactly, and the replicate contributes a `0.0`.

| window | observed firing | replicates firing **zero** times |
|---|---:|---:|
| `inv-2000` | 227 / 524 (43.3%) | **105 / 200 (52.5%)** |
| `inv-2006` | 215 / 462 (46.5%) | **111 / 200 (55.5%)** |
| `inv-2022` | 541 / 749 (72.2%) | **85 / 200 (42.5%)** |

**So the null is not "this series at a random phase" throughout — about half of it is "no treatment at
all".** The construction preserves the level distribution and autocorrelation *over the whole series*;
it does not preserve the presence of the treatment *inside the window*, which is where the comparison
lives. Round 22 used the same construction and is affected identically (46.0%–62.5% untreated).

The direction of the bias is measured, not argued. Round 22's harness retained `raw_marginals`, so its
intervals can be rebuilt from treated replicates only:

| round 22 window | width, all 200 | width, treated only | verdict |
|---|---:|---:|---|
| `inv-2000` | 0.1025 | **0.1249** (n=75) | unchanged, inside |
| `inv-2006` | 0.0804 | **0.0892** (n=83) | unchanged, inside |
| `inv-2022` | 0.1205 | **0.1277** (n=108) | unchanged, inside |

**The point mass makes the interval too narrow, so `outside` is easier to reach than it should be.**
That cuts in opposite directions for the two rounds:

- **Round 22's null is strengthened.** It concluded "inside in 3 of 3" using a test biased *toward*
  finding an effect, and every verdict survives the correction unchanged. A conservative test that
  finds nothing is better evidence of nothing than a neutral one would be.
- **Round 23's single `outside` did not survive it.** `inv-2022` cleared its boundary by 0.25pp —
  about 1% of the 21.2pp noise floor — on a boundary understated by exactly this mechanism. Corrected,
  the bound moves to −14.68 and the observation falls inside. The round is null in 3 of 3.

**The diagnostic re-run has landed, and the flip happened** (`ROUND-23-PLAN.md` Amendment 3, recorded
before it ran). Every field committed at `7cc352c` reproduces exactly — `observed_marginal`,
`null_p2_5`, `null_p97_5`, `null_median`, `outside_null` and `n`, asserted field-by-field by the tool,
which refuses to write on any drift. Same draw recorded more closely, not a second measurement.
Rebuilding `inv-2022`'s interval from treated replicates moves its lower bound from −12.36 to
**−14.68**, which contains the −12.61 observation. Amendment 3's committed estimate was "roughly
−13.4", so **the prediction held in direction and understated the size** — the correction is larger
than the scaling from round 22 suggested.

**One thing the re-run shows that the firing counts could not.** Untreated replicates counted by
*outcome* are 118 / 128 / 97, against 105 / 111 / 85 counted by *firing*. So 13, 17 and 12 replicates
fired the tilt and still returned exactly the control's number — **the band absorbed the tilt
completely.** That is prediction 5's refutation mechanism appearing a second time, independently,
inside the null itself.

### The metric caveat that dominated round 22 does not arise here

§6 item 4 warned that a sizing term changes exposure continuously, and that `adjusted_excess`
structurally credits a low-exposure book (round 22 §5) — so any such round had to settle the metric in
its pre-registration. It is settled, and by the engine rather than by choice: an `AllocationCard`
carries the `invested-value` exposure basis, and `app.tournament.results` **refuses** to compute
`adjusted_excess` for it rather than emit a same-named, structurally different number. Return, max
drawdown and MAR are the honest scoring here. That follows from the card shape, not from a metric
picked to dodge the caveat.

### What it does not settle

One direction, one sleeve pair, one coefficient, one threshold, three windows from one economy. A
rate-of-change input and the other six series in the round-21 pin are untouched. And the round rests
on a nine-session-wide question mark: `inv-2006`'s near-zero result is a window where the treatment
barely differs from control by construction, so it contributes little either way.

## 5g. Round 24 — the six-month mandate is affordable, and a seated card's own thesis is overstated

**Not my work.** A concurrent session ran this while round 23 was in flight. Figures below were
checked against `data/rounds/r24-2026-08/scorecard.json` and `scorecard-r2.json` rather than
transcribed from its prose; where the two disagree it is noted.

This is the first round in the sequence that is not about a strategy *form* at all. It asks whether
the live ranking that seats two momentum cards survives making them honour the owner's stated horizon
— `max_hold_days` 180 sessions (~8.6 calendar months) cut to 126 (~6 months).

### The live arm was inert, and the pre-registration was wrong about why

Both cards returned **byte-identical medians** across both arms — `B3-concentrated` +7.41% in each,
to twenty-eight decimal places — with zero time-stop exits, so the cap never fired. `inert: true` is
recorded in the scorecard rather than inferred.

The round's own diagnosis is that its §1 read a position's `bars_held` at one date and its §5 asserted
the cap would bind at an earlier one. The cap binds in the *future*, not inside the window measured.
**A round cannot measure a constraint that has not bound yet** — and this is the second time in the
programme that an arm has produced a complete-looking table while measuring nothing, after round 21's
window matrix and round 23's Amendment 2. The round amended and moved to the round-2 regime matrix.

### On the regime matrix the cap binds, and it costs almost nothing

| card | median adjusted excess | with the 6-month cap | cost | trades | time exits |
|---|---:|---:|---:|---:|---:|
| `B3-concentrated` | +13.89% | +8.82% | **−5.07pp** | 56 → 58 | 2 → 3 |
| `B-momentum` | +12.16% | +11.97% | **−0.19pp** | 70 → 74 | 3 → 4 |

**Both costs sit inside the 21.2pp ordering floor**, so neither is a margin this programme acts on.
That cuts one way only: there is **no measured reason to keep holding past the mandate**.

**This round was the first to measure a claim a seated card makes about its own configuration** —
though not, as both that round and an earlier draft of this section said, to refute one. Round 24 §9
quotes `B3-concentrated`'s thesis as saying that capping *the hold* cut per-signal return to 2–9%. The
thesis says capping **gains**, at 8–30%, and its two "capped variants" are a take-profit and a fast
EMA exit. The 180-session backstop is part of the *uncapped* arm it prefers, so cutting it to 126
shortened the preferred arm rather than testing either capped variant. **The measurement is sound; the
mapping onto the thesis is not, and the "roughly triple" claim remains untested.** See
[`thesis-audit.md`](thesis-audit.md) §3, which found this by reading the card rather than the round's
summary of it.

**And the cost lives in exactly one regime.** Five of the six scoring windows are byte-identical
between arms. The whole difference is `chop-2015` (+23.29% → +13.14% and +24.60% → +16.54%): a
directionless market, where a position runs on without ever triggering a trend-break exit and only the
clock gets it out. In every trending window, up or down, the six-month cap was **free**.

### The control reproduces this document's oldest lesson

`A-rotation` and `C-trend` are unchanged between arms, both already inside the cap. `A-rotation` posts
a **−7.16%** median here — last in the field — against **+3.47%** on the live matrix and **+19.92pp/yr**
at round 5's six-month rung. Same frozen card, three window sets, three verdicts. That is §4's
window-mix finding arriving again from a round that was not looking for it.

**One caveat found in checking, which the round's prose states but its table does not show.** The
cards do not share a window set: `A-rotation` has results in **seven** windows and every other card in
**six**, because `chop-2011` lost five of six cards to META's first bar. So `A-rotation`'s −7.16% and
`B3-concentrated`'s +13.89% are medians over *different* window sets and are not a straight ranking.
**The round's headline is unaffected** — each base-vs-cap comparison is within-card over the same six
windows — but the cross-card ordering in that table should not be read as one. Independently
confirmed: no `IOException` appears anywhere in the arm-2 results, so no card was lost to store
contention (D3).

## 5h. Round 25 — the rate of change, and the macro line is now exhausted at the level of shape

The last untouched variant. Round 22 answered the curve as an **entry gate**, round 23 as a **sizing
term**, and both §6 item 4 and round 22's own §6 named the rate of change as the only shape remaining.

**It is not expressible in a card, and the round says so before its first number.** `macro()` takes a
bare series name, `MacroRef` carries no lag, and the indicator registry operates on the OHLCV frame —
`MacroField`'s own docstring records that the transform is *deliberately* not built. So arm C reads a
series **substituted** with its own 20-session change, through the same in-process `active_pin` swap
rounds 22 and 23 use for their nulls: binding, guard and engine run unchanged, and nothing is written
to a pin file, because a file on disk named `T10Y2Y` holding deltas would be a trap for every later
reader. Causality survives by construction — `ROC(d)` depends on `d` and `d−20`, and the later of
those *is* `T10Y2Y(d)`, so the existing release lag already covers it.

**This measures the hypothesis, not a shippable capability**, and the round is worth exactly that much:
a null closes the question, and a non-null would only have justified opening an engine-change
question. Nothing here is promotable under any outcome.

### The design, and the check that makes it trustworthy

Three arms on round 23's `XLK`/`XLP`/`XLU` allocation. **Arm B *is* round 23's `c-sized` card**, so
prediction 1 is an instrument check rather than a hypothesis: it must reproduce that round's ending
equity, return, drawdown and trade count, and `round25.py` refuses to write results if it does not.
**It reproduced in all three windows.**

The two tilted arms are matched on **mean shift across all sessions** (k = 1.748), not on round 23's
firing-session mean — because these arms fire on *different* conditions, so a firing-session match
would have left them moving different total weight and a B-vs-C difference would have been partly dose.

| window | A control | B level | C rate | \|A−B\| | \|A−C\| | trades B/C |
|---|---:|---:|---:|---:|---:|---:|
| `inv-2000` | −3.15% | +8.18% | −1.33% | 11.33 | **1.82** | 62/126 |
| `inv-2006` | +24.20% | +24.23% | +23.88% | 0.04 | **0.32** | 19/111 |
| `inv-2022` | +16.24% | +3.62% | +12.91% | 12.61 | **3.33** | 108/188 |

**The rate arm barely moves the book, on the same dose.** `|A−C|` is 1.82 / 0.32 / 3.33 against
`|A−B|` of 11.33 / 0.04 / 12.61, with the two arms calibrated to move identical total weight. A signal
that oscillates has its tilts cancel; a signal that stays negative for long stretches produces a
sustained deviation. **Same dose, opposite footprint** — and arm C trades roughly twice as often for
the privilege, which held prediction 4 where round 23's equivalent was refuted by the band.

Checked rather than assumed: arm C's 169 rejections against 188 trades in `inv-2022` are all
`insufficient_cash`, the ordinary T+1 settlement behaviour left in place by the D8 fix rather than
D8's unbounded retry. Rejections per trade sit at 0.68–0.90 across both arms and all three windows
with no runaway, and arm C's exposure moves against the control, so its tilts do execute.

### Null in 3 of 3 — and the correction pre-registered for it turned out to be unnecessary

| window | observed | null [2.5%, 97.5%] | untreated | verdict |
|---|---:|---|---:|---|
| `inv-2000` | +1.82pp | [−14.46, +16.83] | **0/200** | inside |
| `inv-2006` | −0.32pp | [−7.09, +5.61] | **0/200** | inside |
| `inv-2022` | −3.33pp | [−16.16, +5.05] | **0/200** | inside |

`ROUND-25-PLAN.md` §6 pre-registered the **treated-only** interval as the primary decision rule, on
round 23's Amendment 3 evidence that 42.5%–55.5% of replicates in this construction apply no treatment
and the resulting interval is too narrow. **Here it is a no-op: zero untreated replicates in all three
windows**, so both intervals are identical to the digit.

**The reason is a property of the treatment and it is the round's most portable methodological
result.** The curve's *level* is inverted in a minority of 1976–2026, so a circular shift lands the
window on a non-inverted stretch about half the time and the card silently reproduces its control.
The curve's *change* is negative on ~51% of sessions at any phase, so no shift can produce an
untreated replicate. **A circular-shift null is only sound when the treatment fires at a rate a phase
shift cannot destroy** — a condition round 23's treatment failed and this one cannot.

That the correction proved unnecessary is knowable only now. Fixing the rule in advance, rather than
after seeing which interval was more convenient, is the entire point of having pre-registered it.

### What this closes

**The macro line is exhausted at the level of shape.** Entry gate, sizing term, rate of change: null
in 3 of 3 windows each, on one series, one universe and one economy's worth of windows. What remains
untested is **other series** — the other six in the round-21 pin — not other forms of this one. That
is a narrower and much less interesting frontier than it looked before round 22.

## 5i. Round 26 — the seated cards' own claims, measured

Recommendation 7 gave every seated card a place to say what would make it wrong. Recommendation 8 ran
what those clauses named. This is that round: seven arms on the eight-window regime matrix, each
isolating one field, pre-registered at `19155dd` before any card was authored.

**The instrument is verified, and nobody planned it.** All three controls were re-run rather than
quoted from round 24, and all three reproduce its committed medians exactly — `B3-concentrated`
+13.89%, `C-trend` +5.03%, `A-rotation` −7.16%. Six windows carried the full field; `chop-2011` and
`gfc` losses are the universe-history wall round 24 already documented, and no `IOException` appears
anywhere, so nothing was lost to contention.

| card | median adj. excess | worst | hit rate | trades |
|---|---:|---:|---:|---:|
| `r26-b3-base` *(control)* | **+13.89%** | −7.75% | 66.7% | 56 |
| `r26-b3-fastexit` | +9.63% | −6.61% | 66.7% | 78 |
| `r26-ctrend-stop08` | +5.75% | −5.95% | 50.0% | 59 |
| `r26-ctrend-base` *(control)* | +5.03% | −7.26% | 50.0% | 59 |
| `r26-b3-tp20` | +3.01% | −7.75% | 50.0% | 72 |
| `r26-arot-rankby` | +0.43% | −27.10% | 57.1% | 183 |
| `r26-arot-base` *(control)* | −7.16% | −27.41% | 42.9% | 189 |

**Every margin is inside the 21.2pp floor**; the largest arm-versus-control gap is 10.88pp. Five
directional findings, zero measurable magnitudes, and nothing promoted or demoted.

**Three of five pre-registered predictions were refuted**, which is a higher yield of surprise than
any round in the macro line returned.

- **A seated card's own argument came back supported, for the first time in this record.**
  `B3-concentrated`'s take-profit arm posts +3.01% against the control's +13.89% — a ratio of **4.6×**,
  *more* than the "roughly triple" its thesis asserts, on a matrix its author never ran. The fast-exit
  arm is 1.44×, so the claim holds for one of the two variants it names.
- **`C-trend`'s stop width is a free parameter.** The thesis argues for widening 8% → 12%; the 8% stop
  is marginally *better*, on a shallower worst window and the same trade count. Not "8% is better" —
  the honest reading is that the card's record does not depend on the parameter its thesis defends.
- **`A-rotation` is closer to "hold everything that qualifies" than to a rotation.** Imposing a ranking
  key moved it only 7.59pp, and the breadth scan says why: median names qualifying is below 4 in **6 of
  8** windows and 0 or 1 in three of them. The cap the thesis defends usually does not bind, so the
  alphabetical fill order it was candid about barely gets consulted. Its two conditions answered each
  other.

**And one question was refused rather than answered.** `C-trend`'s universe-exclusion claim cannot be
tested here: the five excluded names co-exist only from 2022-04-12, covering two of eight windows
against a five-window minimum, and a zero-bar symbol fails the whole card. That is §5e's third
category — asked with an instrument that cannot answer — and it was recorded in the plan before
running rather than discovered in the results.

**The pattern is §1's, again.** The mechanisms are real; the magnitudes sit inside the noise. What is
new is only that the claims under test were the cards' own.

## 5j. Round 27 - the last three thesis claims, measured directly

Recommendation 9's remainder, and it closes the thesis scoreboard. Read literally, `A-rotation`'s
correlation figure, the momentum cards' move-duration claim, and `C-trend`'s exclusion evidence are
all statistics about **bars and signals**, not about a book -- so each was measured as its thesis
states it, not inferred from a card's return. Definitions were pinned in `ROUND-27-PLAN.md` before any
number existed, and **every headline was recomputed independently of the tool that produced it and
matched to the digit.**

- **`A-rotation`'s correlation holds, and is understated.** Mean daily-return correlation across the
  nine names is above the thesis's 0.589 in **6 of 8** windows, peaking at 0.83 in `covid` and 0.80 in
  `bear-2022` -- the two stressed regimes, exactly where prediction 1 expected it. The card's own
  self-description ("a concentrated sector bet dressed as a 3-of-9 rotation") is if anything too
  modest. The two specific min/max *pairs* the thesis named reproduce in zero windows.
- **The momentum move lasts far longer than its own thesis claims.** Median duration from golden
  cross to the death cross that ends it is **47.5 sessions** -- two and a half times the top of the
  "3-4 week" band the thesis states. The 75th percentile (108 sessions) clears the "past two months"
  bar as claimed, so the distribution is right-skewed as advertised, just centred more than twice as
  high. **My own prediction that it would run short was wrong**, because I borrowed round 26's
  hold-duration direction without checking that a book's bounded hold time and a raw indicator move
  are different quantities -- the same source-check failure this report keeps cataloguing, in
  miniature.
- **`C-trend`'s exclusion evidence is refuted.** The five names it dropped for "negative average
  60-day forward returns" have a pooled mean of **+19.89%**, every one individually positive, and
  **12.96pp above** the nine names it kept. The stated, measured reason for the exclusion does not
  reproduce in the store. The sample is thin (44 signals, recent listings), which refutes the *claim*
  without establishing the *names* -- but that cuts against the thesis, whose whole case was that "the
  measured data showed" the exclusion. This does not overturn section 5i's "unaskable" verdict: that
  was the backtest form, and both are true at once.

**The scoreboard is closed.** Every quantitative claim on the four seated trading cards is now
measured or established unmeasurable. The finding is not that the cards are wrong -- it is that **prose
drifts from measurement in both directions**: two claims understate what the data shows, one asserts
the wrong sign, and most surviving magnitudes sit inside the noise floor. The `falsification` field
(section 6 item 7) is what makes the *next* card's claims measurable by construction rather than rounds
after the fact.

## 5k. Round 28 - is the blocked cross-symbol class worth building? Measured: no, here

A new line opens - cross-symbol constructions, the class section 3a forecloses - and it opens with an
*analysis*, not a build. Every blocked strategy (relative strength, pairs, inverse-vol parity) needs
one precondition: a name's past cross-sectional rank must predict its future cross-sectional rank.
Round 28 measured that directly as a rank information coefficient, five signals x two horizons x the
two single-name equity universes the seated cards trade - no card, no engine, no backtest.

**Zero of twenty cells survive Benjamini-Hochberg at q < 0.10**; the lowest q anywhere is 0.215. On
these universes cross-sectional rank carries no measurable information - the same answer the Discovery
module got on ETF baskets (IC -0.0073, q=0.186), now confirmed on single names. So **the engine change
section 3a describes is not justified by measured edge for the book that exists**: it would unlock a
capability with nothing here to capture.

**The run caught an artifact in its own design, which is the more transferable result.** The
pre-registered pass produced one survivor - `U9 reversal_1m` at h=63, q=0.010 - refuting the null
prior. Stress-tested before anything was concluded: robust to the bootstrap's seed and block length,
but it collapsed from p=0.0002 to **p=0.63** when the window overlap was removed. A 63-session horizon
on a 21-session rebalance shares 42 of 63 forward sessions between neighbouring cross-sections, and the
block bootstrap did not fully remove that autocorrelation - the effective sample was a third of the
nominal one. Recorded as Amendment 1 *before* the correction ran, with the corrected outcome (zero
survivors) committed in advance. **This is round 23's null-point-mass failure in a new guise, and it
generalises: any IC or event study whose horizon exceeds its rebalance interval inflates significance
the same way.**

**The honest scope, fixed in the plan before any number.** These universes are concentrated - round 27
put their pairwise correlation at 0.46-0.83 - so they are close to the worst case for cross-sectional
selection, and this null is about the concentrated book, not selection in general. The fair test is a
broader, less-correlated universe, and it is the natural next round: if even a diversified universe
shows null IC, the engine change is dead everywhere relevant.

## 5l. Round 29 - the fair test found a survivor, and it is the beta premium

Round 28's null was on concentrated universes; its §2 named the fair test - a diversified,
low-correlation universe - and warned a concentrated set is the worst case for selection. Round 29 ran
the identical measurement (machinery imported unchanged, windows non-overlapping from the start) on ten
single names, one per GICS sector, pairwise correlation 0.393.

**Two cells survive Benjamini-Hochberg, both `vol_60`** (h=21 q=0.030, h=63 q=0.052) - the first
genuine cross-sectional survivors in the programme, and this time not artifacts: 410 independent
cross-sections, robust to every bootstrap seed, the same sign in both sub-periods, and surviving the
drop of every single name.

**But the sign is positive - high vol predicts high forward relative return - and that is the whole
finding.** Splitting cross-sections by market direction is decisive: UP-market IC +0.167, DOWN-market
IC -0.140, a symmetric flip. The survivor is the **beta premium**: high-vol names amplify the market,
winning when it rises and losing when it falls, and the full-sample +0.057 is arithmetically just the
up-market IC weighted by the fraction of up-months. There is no residual volatility alpha - the low-vol
anomaly, the signal that would justify a build, has the wrong sign on this universe.

**So the pre-registered decision rule declines the build.** A surviving cell was meant to justify the
engine change, but this survivor is directional market exposure - capturable with a high-beta ETF and
no cross-symbol machinery, and carrying crash risk a de-meaned rank IC cannot see. **Cross-sectional
rank carries no alpha on either a concentrated or a diversified universe; the engine change §3a
describes is not justified by measured edge.**

One refutation is worth keeping: mean |IC| was *lower* here (0.0227) than on round 28's concentrated
universes (0.042-0.052). Diversification did not add rankable structure - it removed the spurious
co-movement ICs the tight universes produced, leaving only the one real (beta) effect. What this cannot
settle is breadth: ten names is narrow, and the low-vol anomaly is a hundreds-of-names effect where the
beta premium diversifies away and the residual alpha can be isolated. That universe remains unrun,
limited by the store.

## 5m. Round 30 - the daily untouched macro series carry no orthogonal forward-return information

Rounds 28-29 closed the cross-symbol line; recommendation 11 named the non-price macro series as the
next frontier. Only one of the seven FRED series the desk can read had ever been tested - `T10Y2Y`, the
curve, null 3-of-3 as a card (rounds 22/23/25). Round 30 measured the three **daily, directly-expressible
untouched** series - `DGS10` (rate level), `DCOILWTICO` (oil), `T10YIE` (breakeven inflation) - as
regime-conditional forward-return spreads on SPY and QQQ, before any card. Twenty-four cells (3 series x
level/roc x 2 targets x 2 horizons), the round-28/29 block bootstrap and BH machinery imported unchanged,
non-overlapping windows from the start.

**Zero cells survive Benjamini-Hochberg** (smallest q=0.288), **zero survive the orthogonality control.**
State splits are healthy (40-60% each side, no degenerate join) and raw p-values span 0.018-0.942, so
the measurement discriminates - it found nothing. The three lowest uncorrected hits (oil-level->SPY at
both horizons, breakeven-level->QQQ at h=63) are exactly the ~1.2 false positives BH expects from 24
tests at p<0.05, and none clears correction.

**The informative result is the orthogonality control (pre-registered prediction 2, refuted).** It was
built to catch a macro state that is secretly trailing price momentum; residualizing forward return on
the target's own 12-1 momentum **barely moved any spread** (`DGS10` roc QQQ h=63 -2.49% -> -2.42%). So
the macro states are genuinely orthogonal to price - and *also* orthogonal to future returns. The
information that is not in the price is not information about the outcome either. This closes the "the
control killed a real signal" objection before it can be raised: there was nothing to strip. (Two
predictions also fell: rates, not oil, were the flattest series; and the rate-hurts-growth sign appeared
on QQQ only at the quarterly horizon and well inside noise.)

**Per the pre-registered decision rule, no card.** `T10Y2Y` was null 3x as a card; now the rate level,
oil and breakeven inflation are null as pure statistics before any card. **Four of the seven macro
series are now measured and empty.** The frontier narrows to the three monthly inflation indices
(`PCEPI`, `PCEPILFE`, `CPILFESL`), which are non-stationary and need the round-23/25 substitution trick -
a harder, lower-prior follow-up. One thread is worth stating because pre-registration allows it: the two
least-dead cells are both `level` transforms carrying a valuation-drag sign (expensive oil, high
inflation expectations -> lower quarterly-forward equity), the exact shape the monthly core-inflation
indices measure directly. It is not a signal - it dies under BH - but it is why the inflation-index
round is the right next branch rather than a dead end.

## 5n. Round 31 - the macro line closes on a null, with one genuine near-miss

Round 30 left the three monthly inflation indices as the last untested macro series and one thread: a
quarterly valuation-drag sign the indices measure directly. Round 31 tested them - `PCEPI`, `PCEPILFE`,
`CPILFESL` differenced to year-over-year inflation, **release-date bound at the 45-day lag
`macro_binding.RELEASE_LAG` uses** (inflation for a reference month is not knowable for ~six weeks;
joining on the reference date would be the one lookahead this round exists to avoid), split by `level`
(YoY vs its trailing 60-month mean) and `accel` (3-month change), on SPY and QQQ.

**Zero cells clear Benjamini-Hochberg (min q=0.139), zero survive the orthogonality control - by the
pre-registered rule, null, and all seven macro series are now measured and empty.** The bar was fixed
before the run and is not moved. Five `level` cells all show the effect at p ~ 0.01-0.06, and BH
correctly taxes the 24 looks (at rank 5 the best q is 0.029x24/5=0.139) - the correction working as
designed on a grid of correlated cells each carrying a modest effect.

**But the shape is not round 30's noise, and my own pre-registered premise was wrong.** Every one of the
24 cells is negative (hot/accelerating inflation -> weaker forward equity), the spreads are the largest
in the macro line (to -4.66%/quarter), and the strongest cell (`CPILFESL` level SPY h=63, spread -3.66%,
p=0.009) passes every stress test the plan demanded of a survivor: the `level` state fires across
2000-2024 not just the 2021-2023 spike (**dropping 2021-2023 leaves the spread at -3.83%, essentially
unchanged** - my §2 caveat that a survivor would be one episode is refuted); it is **robust to bootstrap
block length** (p 0.011 -> 0.001 as the block lengthens, the opposite of round 28's overlap artifact);
it is orthogonal to price momentum; and the 45-day lag is conservative, so it is not a lookahead. The
disciplining caveat that keeps it proportionate: this is a **known** macro regularity (inflation above
trend compresses forward equity returns), textbook not proprietary, and the effect is lower *positive*
returns (+0.55%/qtr hot vs +4.21% cool), tradeable only as a tilt against the prevailing cash rate.

So round 31 both **closes the macro line** (no `macro()` card is justified on the desk's tradeable
history) and **names the one thread worth a dedicated round**: the inflation-`level` effect on SPY,
which misses only by paying a 24-cell multiple-testing tax it would not pay alone. The disciplined next
step is a single-hypothesis round - one series, one transform, one target, one horizon, pre-registered
with its own null and out-of-sample split - so p ~ 0.01-0.02 stands or falls without the grid tax. This
is round 29's lesson inverted: there a survivor decomposed into a risk premium and the build was
declined; here a near-miss passed every robustness check, and the honest move is to name it precisely.

## 5o. Round 32 - the near-miss passes its rule by the letter and fails it out of sample

Round 31's inflation-`level` near-miss earned a dedicated single-hypothesis round. The honesty it was
built on: re-running the cell without the 24-cell BH tax is arithmetic (reported as a baseline, p=0.011,
excluded from the decision), so the round's real content is three tests the grid never ran - a
regime-breadth test on a 26-name equal-weight portfolio with **1970 history** (so the **1970-1992 half is
out-of-sample** to round 31's 1993-2026 selection, and spans the 1974/1980 great-inflation regimes); a
**rate-level confound** control; and an **exploitability-vs-cash** check.

**The pre-registered rule fired `CARD CANDIDATE: True` and all four predictions held by their letter -
and the effect fails out of sample anyway.** Round 31's effect is entirely in the 1993-2026 half (-3.52%,
p=0.021); on the 1970-1992 data it was never fit to - when inflation was *most* extreme - the spread
collapses to **-0.82% at p=0.51**. The sign held (all my OOS gate required), but the magnitude fell 77%
and significance vanished. A structural inflation-to-equity effect should have been *strongest* in
1970-1992; it is absent there.

**This is the one place a pre-registered rule can mislead, and the direction matters.** Pre-registration
stops me moving goalposts to manufacture a *win*; it does not oblige me to *declare* one when the decisive
test undercuts it. My OOS gate was a bare sign test, and a sign at p=0.51 is a coin flip - so I decline
the card and record the rule as under-specified, which is following the evidence, not tightening the bar
after the fact. What genuinely held: the **rate-level control passed cleanly** (-2.41% -> -2.29%, p=0.037
- the effect is *not* the rate level in disguise), but it controls a full-sample effect that only exists
in-sample. Exploitability is marginal even in-sample (hot beats the 10Y cash floor by just +0.24%).

**The honest counter-caveat, kept:** the only 1970-history instrument in the store is *inflation-
defensive* by composition (energy/staples/utilities heavy), which mechanically compresses the spread, so
the 1970-1992 null is **inconclusive, not fatal** - and I will not slice the cohort's cyclical names to
chase a cleaner number (that is out-of-sample p-hacking). **Verdict: no card.** The near-miss resolves as
a 1993-2026-specific pattern that does not generalize; reopening the inflation question would need a
broad, non-defensive total-return series reaching to the 1970s that this repository does not hold. The
macro line stays closed.

## 5p. Rounds 34–36 — the sector family moved off the taxable book, and the null moved with it

Designed 2026-09-08, run 2026-09-09 (`strategy-program/DISJOINT-SECTOR-FAMILY.md`). Every card is
`purpose = roth` on a universe sharing no ticker with any savings/trading card — checked against all six
library tiers by `tools/disjoint_field.py` — because the owner asked for sector-style strategies that do
not intersect the taxable research. Before round 34 ran, the frozen `r17-ma-crossover-on-stop` was
re-run as an instrument check and reproduced round 17's committed figures to the digit.

**Round 34 — industries, one level below the sector** (`XME XRT XHB XSD XOP XBI ITA VNQ`, 8 forms ×
regime on/off): form marginal **4.21pp**, regime **0.88pp**, whole field **6.40pp** against a
pure-noise expectation of 74.9pp. Round 17's null replicates out of sample — and the premise that
industries would disperse *more* is refuted: round 17's comparable slice spanned 9.47pp. The forms are
the bottleneck, not the basket. `bull-2024`, not the chop windows, was the worst window for seven of
sixteen cells: a V-shaped correction inside an up-year whipsaws a fast crossover as badly as a flat year.

**Round 35 — countries** (`EWJ EWG EWU EWC EWY ILF EFA VWO`, 2 forms × {2,4} slots × {order, `rank_by`}
plus a passive `close > 0` control holding all eight): every rotation cell negative against SPY (−2.21
to −7.82pp); the best cell beats the control by **+0.08pp**; the control itself is −2.28pp, which is the
pre-registered asset-class/FX gap. The rules add nothing to owning the basket. The `macross` cells never
traded in `covid` — `close > sma(200)` was false for every country ETF for the whole window.

**Round 36 — does `rank_by` decide the slot?** (c20's rule fixed, 5 orderings × 2 caps on the round-34
universe): strong − weak **+1.22pp / +1.01pp**, same sign in 5 of 8 windows, q 0.40 / 0.52 over all ten
cells; canonical − reversed **0.13pp / 0.26pp**; five-ordering spread 2.04pp / 1.60pp. The cap bound in
every window (five distinct results per window at k=2), so the contrasts are real. **Ordering noise on
an eight-name industry universe is ~2pp** — the third datapoint beside round 17's ~1pp on sectors and the
21.2pp floor from twelve semis. The floor is not lowered by this; it is a datapoint for a future round.

**Disposition.** All three plans pre-registered that nothing would be promoted, and by the rule nothing
was. On 2026-09-09 the owner directed that `r34-ma-crossover-on` (+1.24pp, 5 of 8, Pareto frontier) be
promoted to `candidates/` anyway; `PROTOCOL.md` §9 records it as the library's second directed
promotion, beside `C-trend`, and states plainly that its margin is inside the floor.

## 6. What to do next, ranked by expected value

1. ~~Fix D8, as its own pre-registered round.~~ **Done — round 20: funding rule pre-registered at
   `818c07b`, fix at `e516836`, affected figures restated at `0aef76d`.** A breaching buy is now
   funded pro-rata from the overweight sleeves that did not breach, and no donor is sold past its own
   target, so funding one breach cannot create the next. Rejections on the reference card fell from
   **59 to 3**. All five pre-registered predictions held, including the two that could have gone
   either way — every two-sleeve test passed unedited, and ending equity moved *down*, because
   completing a rebalance into a 2× leveraged ETF during a falling window costs money.

   **It also vindicates round 16 and withdraws round 19's headline.** Round 16 predicted settlement
   would close the harness/engine gap materially; round 19 implemented settlement, found it made the
   gap 23.9% *worse*, and recorded a refutation. Against the fixed engine, settlement closes **73.9%**
   of the gap. Round 19 measured correctly and concluded wrongly, because the engine it measured
   against could not rebalance — which makes §5c's "the harness is pessimistic" a 0.06% *optimism*
   rather than a 0.70% pessimism, far too small to be the systematic bias round 15's caveat implied.
2. ~~Make `TiltRule.shift_pct` a function of an indicator.~~ **Done — 2026-08-30, `8c033f1`. It
   unblocked less than this entry claimed it would.** `TiltRule.shift_expr` exists and is guarded as
   a ranking key (§3a). **Continuous vol-targeting is now expressible; inverse-vol risk parity is
   not.** This recommendation asserted one engine change would unblock both, and that was wrong:
   `ALLOCATION-FAMILY` recorded two blockers and this addressed one. Parity needs each sleeve
   weighted against every *other* sleeve's volatility — the cross-symbol comparison §3a forecloses as
   a class — so the family's best risk-adjusted result stays measurable only in its bespoke harness,
   for a different reason than the one written here.

   A demonstration exists and is **not** a finding: SPY/IEF over the GFC slice, a constant 15-point
   de-risk against a vol-proportional one, −25.56%/−25.75%dd against −8.56%/−13.98%dd. Two cards, one
   window, no null, threshold and multiplier picked by hand. On this document's own §1 record that is
   the shape of number that does not survive correction, and it is recorded here as a wiring check.
3. **Widen the window pool before tightening any gate.** The promotion rule's "differing window sets"
   is arithmetically forced to reuse 4 of 5 windows on every promotion made so far. More eligible
   main windows is the only fix; a stricter ceiling on the current pool is unsatisfiable.
4. ~~Give the DSL one non-price field.~~ **Done — round 21, and answered by round 22 (§5e).** The
   macro class is reachable and its first real question came back null. What remains untouched is the
   *shape* of the input, not the access: the curve as a **sizing** term rather than a binary gate, or
   as a rate-of-change rather than a level. Those are new pre-registrations, not a re-run.

   ~~The sizing half of that is now mechanically possible, and this composition has never been
   run.~~ **Run — round 23 (§5f), and it too came back null.** An `AllocationCard` whose
   `TiltRule.shift_expr` reads `macro(T10Y2Y)` shifts weight in proportion to the spread rather than
   on a threshold crossing; **inside the null in 3 of 3 windows**, once the null is corrected for the
   replicates that applied no treatment. The metric warning this entry raised was settled by the engine rather than by
   choice — `app.tournament.results` refuses `adjusted_excess` for an allocation card's
   `invested-value` basis — so round 22 §5's exposure-credit caveat does not arise in this form.

   ~~What remains untouched is now only the rate-of-change input.~~ **Run — round 25 (§5h), null in
   3 of 3.** The macro line is now exhausted at the level of *shape*: entry gate, sizing term and rate
   of change have each returned null in every window they were asked in. **What remains is other
   series, not other forms of this one** — the other six in the round-21 pin. Round 23 and round 25
   each also returned a more useful negative than their headline: a continuous shift and a constant
   one are the same card whenever the signal is shallow relative to the rebalance band, and a signal
   that oscillates leaves the book near its control even at identical dose.
5. **Re-run round 17's form comparison with a proper null.** The measured ~1pp ordering noise means a
   form comparison could be powered far better than the blanket 21.2pp floor assumes — but it needs
   its own pre-registered null (permuted labels, or a bootstrap over windows), not a lowered bar.
6. **Put one real question through `reverse_conditioning`.** It is built, wired to the UI, and has
   never produced a recorded finding.
7. ~~Audit the seated cards' theses against measurement.~~ **Done — [`thesis-audit.md`](thesis-audit.md),
   and it found something worse than an overstated claim.** Across the six seated cards, **eleven of
   thirteen quantitative claims have never been measured outside the window they were fitted on**, and
   the split runs cleanly along card type: both allocation-family cards state in advance what would
   falsify them and then produced the number, and **none of the four trading cards states a
   falsification condition at all**. Two of those four — `B3-concentrated` and `B-momentum`, both
   seated on the same book — carry **byte-identical** 1,890-character theses, so one rationale is
   doing duty for two cards that measurably behave differently.

   The audit also corrected this document: round 24 refuted no thesis claim (§5g). **The finding is
   not that a thesis was wrong — it is that eleven of thirteen claims cannot be wrong yet**, because
   nothing has tested them.

   **The follow-up was structural rather than another round, and it is built.** `falsification` is
   now a field on all three card models, enforced over the seated rosters by
   `tests/test_thesis_falsification.py`. The two documented cards carry their clause verbatim; the
   four missing ones were then written by the audit rather than by the cards' authors
   ([`thesis-audit.md`](thesis-audit.md) §8), which is **not** the same thing and says so — each
   opens by declaring itself retrospective and not a pre-registration, and a test fails if one omits
   that. The `xfail` came off in the same commit and the check is now a ratchet: seating a card with
   no clause fails, at the only moment the requirement is cheap to meet.

8. ~~Run the measurements those clauses name.~~ **Done — round 26 (§5i), and it moved the scoreboard
   from nine of eleven claims never measured to five.** Writing a condition measured nothing; running
   them did. Four claims measured, one established as unaskable, three of five predictions refuted.
   The `B-momentum` concentration question was settled without a run at all — round 24 had already
   measured it, at a 1.74pp gap inside the floor, so **the trading book is seating one idea twice**
   (audit §9).

9. ~~Measure the two claims still standing, and retire what cannot be measured.~~ **Done — round 27
   (section 5j), and it closed the scoreboard.** Correlation holds and is understated; the
   move-duration median is 2.5x higher than the thesis claims; `C-trend`'s exclusion statistic is
   refuted at +19.89%. `C-trend`'s exclusion claim, having now been measured on the cited statistic
   and found false, should be **struck from or corrected in the thesis** — it is the one seated-card
   claim this programme has shown to assert a wrong-signed number, and leaving it stated is the failure
   this item was raised to prevent.

10. ~~The cross-symbol line is measured-before-built and points away from the build.~~ **Closed -
    rounds 28 and 29.** The fair test (5l) found a survivor, but it is the beta premium, not an alpha:
    a high-vol tilt that wins in up markets and loses in down ones, capturable with a high-beta ETF and
    no cross-symbol engine. Cross-sectional rank carries no alpha on a concentrated *or* a diversified
    universe, so the engine change section 3a describes is not justified by measured edge. The only
    unrun thread is a genuinely broad (hundreds-of-names) universe where the low-vol anomaly could be
    isolated from the beta premium - limited by what the store holds, and a larger undertaking than
    the non-price rounds below.

11. **The macro line is fully closed — all seven series null (rounds 22-25, 30, 31) and the one
    near-miss resolved against a card (round 32).** The curve as gate/size/ROC (null), the daily
    rate/oil/breakeven as statistics (§5m, null), and the three inflation indices as statistics (§5n,
    null) exhaust the reachable macro series. Round 31's inflation-`level` near-miss earned its dedicated
    single-hypothesis round (§5o) and **failed out of sample**: the effect is entirely 1993-2026 (-3.52%,
    p=0.021) and collapses to -0.82% at p=0.51 on the 1970-1992 data it was never fit to — the era of the
    *most* extreme inflation, where a structural effect should have been strongest. It survived the
    rate-level confound (not the rate in disguise) but not the out-of-sample test, and the only 1970
    instrument in the store is inflation-defensive, so even that null is inconclusive rather than fatal.
    Either way **no `macro()` card is justified**, and reopening the question needs a broad, non-defensive
    total-return series to the 1970s the repository does not hold. **The remaining frontier is entirely
    off macro:** Fear & Greed and the event calendar remain collected-but-unreachable, and the 13F
    consensus engine is built but unconsumed. Each is a pre-registered round, and each is a cheaper bet
    than building cross-symbol machinery for a class round 28 measured as empty.

   **Building it explained the audit's own headline.** `AllocationCard.thesis`'s docstring has always
   demanded that a thesis "say what result would prove it *wrong*"; `StrategyCard.thesis`'s never did.
   The split does not run along the analysts, it runs along **which shape was asked** — every card
   that was told to state a falsification condition stated one, and no card that was not, did. The
   requirement already worked; it had simply never been written where the other two card shapes could
   see it.
