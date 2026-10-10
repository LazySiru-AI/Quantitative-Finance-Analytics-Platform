# Discovery: can a rule find the next sector, using only what it knew at the time?

Every backtest in this programme so far has been handed a universe. This document covers the first
machinery that is handed a *rule* instead and asked whether the rule would have found the universe.

Code: `backend/app/discovery/`. Tests: `tests/test_discovery.py`, `tests/test_discovery_tools.py`
(39 tests).

> **Result in one line.** A momentum rule running only on contemporaneous data *does* surface the big
> themes — semiconductors, solar, uranium, rare earths — several years before they finished running.
> It also has **no measurable ranking skill**: IC = −0.007 across 272 monthly cross-sections
> (bootstrap p = 0.892), the sign flips between eras, and the apparent edge sits an order of magnitude
> inside this programme's own documented noise floor. The finding is real and it is negative — naive
> momentum rotation is not the mechanism that will find the next semiconductors — and §5 argues from
> the measured distribution that the missing piece is exits, not a better rank key.

## 1. Why the existing architecture could not answer this

The programme's own report already states the problem (`data/rounds/PROGRAMME-REPORT.md` §14): *"Every
card's universe was chosen by an analyst writing in 2026."* Three measurements make it concrete.

- **All 29 cards in `backend/app/paper/library/` declare `universe_knowable_from = None`.** The
  provenance gate exists (`strategy-program/tools/windows.py:507`) and has never fired on a library
  card. `WINDOWS.md` scopes it deliberately to *mechanically* index-derived baskets and says so: "A
  card that selects on its own reasoning is not gated." A thesis-picked semiconductor basket is exempt
  by design.
- **The backend engine has no such field at all.** `app.tournament.models.StrategyCard.universe` is a
  bare `tuple[str, ...]`. The engine's only provenance concept is
  `jobs.PROVENANCE_CONSTRAINED_WINDOWS = frozenset({"13f-legal"})` — a property of one window, not of
  any card.
- **The bar store contains no delisted names.** Across 688 stored symbols: `LEH`, `BSC`, `WAMU`,
  `YHOO`, `SIVB`, `FRC` are all absent, and `GM`'s first stored bar is **2010-11-17** — the
  post-bankruptcy relisting, not the company that failed. `data/universe/index-constituents.json`
  actively prunes names as they die (`CTRA`, `HOLX`, `EA` under `delisted_since_period`), so the
  pruning is ongoing rather than historical.

The third point binds differently by question. For **validation** — "did this strategy work" — a
survivor-only store inflates returns: bad, boundable, disclosable. For **discovery** — "would this
rule have found the winner" — it destroys the measurement outright, because the quantity being
measured is a hit rate against a false-positive rate, and a candidate set containing only things that
rose scores any selector near-perfectly by construction. Not an inflated number: a meaningless one.

## 2. The design

| module | responsibility | may see the future? |
|---|---|---|
| `candidates.py` | what could have been chosen on day T | no |
| `selector.py` | which of those to choose | no — routed through `AsOfMarket` |
| `clusters.py` | which candidates were the same bet on day T | no |
| `costs.py` | what the decision cost to implement | n/a |
| `stats.py` | how to grade it without fooling yourself | n/a |
| `exam.py` | how the choice turned out | **yes, on purpose** |

**The candidate set is a protocol, not a constant.** `CandidateSet.symbols_as_of(t)` is the seam that
lets today's survivor-only roster be swapped for a survivorship-free constituent list without touching
the selector or the exam. That swap is the single-ticker track (§7).

**The benchmark is the equal-weight candidate set, never SPY.** A selector graded against SPY in a
bull market looks brilliant for picking anything at all.
`app.tournament.runner._BENCHMARK = "SPY"` is right for the question that module asks and wrong for
this one — against SPY, an entire sector's move is booked as skill, which is exactly how a
hindsight-picked semiconductor basket comes to look like a strategy.

**The as-of guarantee is structural.** The selector never opens a parquet file and never takes an end
date; it reads only through `app.paper.marketdata.AsOfMarket`, which cannot slice past its own
`as_of`. `test_selection_ignores_everything_after_as_of` enforces it as a reversal — through the
decision date `FALLER` is worst and `RISER` best, then the future is rewritten so `FALLER` explodes
and `RISER` collapses, and the whole `Selection` must come back identical. A selector that leaked
would still produce a plausible hit rate and a plausible p-value.

**Near-duplicates are collapsed by measured correlation, never by a declared table.** A hand-written
"SMH ≈ SOXX" list would be a 2026 judgement applied to 2004 — the exact error this package exists to
stop making — and would silently miss every pair nobody thought of. `clusters.py` partitions the
candidates by trailing correlation at each decision date, through the same `AsOfMarket`.

## 3. Did it find semiconductors? Yes.

23 annual decision dates, 2003-01-02 → 2025-01-02, `mom12_1` (twelve-month return skipping the most
recent month), top 3, collapsed, 10bp costs, **theme roster** (39 candidates by 2025).

| date | picks | net excess | best available |
|---|---|---|---|
| 2010-01-02 | XRT, SLV, GDX | **+33.72%** | SLV +82% |
| 2013-01-02 | XHB, XBI, IBB | **+24.27%** | TAN +134% |
| 2014-01-02 | TAN, IBB, ITA | +8.97% | XBI +46% |
| 2015-01-02 | XBI, IBB, SMH | +16.56% | IGV +13% |
| 2017-01-02 | GDXJ, XOP, SOXX | −12.10% | ARKK +95% |
| 2018-01-02 | ARKK, ARKW, REMX | −5.11% | IGV +11% |
| 2020-01-02 | **SMH, TAN, XLK** | **+68.20%** | TAN +222% |
| 2021-01-02 | TAN, ARKG, ARKW | **−44.64%** | REMX +80% |
| 2022-01-02 | REMX, XOP, URA | +15.30% | XLE +64% |
| 2024-01-02 | ARKW, SMH, IGV | **+28.81%** | ARKW +48% |

Semiconductors were picked in 2004, 2006, 2015, 2017, 2020, 2024 and 2025. Solar (TAN) in 2014, 2020
and 2021. Uranium (URA) in 2022, rare earths (REMX) in 2018 and 2022, homebuilders (XHB) in 2013.

**So the mechanism works in the sense you asked about**: a stated rule, running on contemporaneous
data, put the eventual winners in front of you before they finished winning. 2020 in particular is the
whole thesis — SMH and TAN together, +68% net of the sector average, in the year both ran.

On the **sector roster**, with the collapse in force so each date carries at most one semiconductor
fund, the rule put semis in the top three on eleven of twenty-three dates:

| | | | | |
|---|---|---|---|---|
| 2004 −9.77% | 2006 +0.09% | 2010 +3.98% | 2015 +10.39% | 2017 −4.60% |
| 2018 +4.04% | **2020 +34.22%** | 2021 −15.52% | **2022 +34.35%** | 2024 +17.40% |
| 2025 +5.66% | | | | |

Seven of eleven positive, net of costs. The two largest hits are 2020 and 2022, and the two largest
misses are 2021 and 2004 — the same fund, the same rule, adjacent years, opposite outcomes. §5 is
about that pattern, which is the useful part of this whole exercise.

## 4. Is it skill? No.

**4.1 The information coefficient says the ranking carries nothing.** A hit rate reduces each date —
a full cross-section of up to 39 ranked candidates and 39 realized returns — to a single bit. The
information coefficient keeps the whole cross-section (`stats.information_coefficient`).

| dates | key | n | IC | IC > 0 | bootstrap p |
|---|---|---|---|---|---|
| 272 monthly | **`mom12_1`** | 272 | **−0.0073** | 51.5% | **0.892** |
| 272 monthly | `mom6` | 272 | +0.0144 | 51.5% | 0.722 |
| 272 monthly | `trend` | 272 | +0.0176 | 52.6% | 0.688 |
| 23 annual | `mom12_1` | 23 | +0.021 | 60.9% | t = +0.23 |
| 23 annual | `mom6` | 23 | +0.010 | 43.5% | t = +0.14 |
| 23 annual | `trend` | 23 | +0.013 | 47.8% | t = +0.16 |

Every one of them is indistinguishable from zero, and the headline key is *negative* on the larger
sample. Across 272 monthly cross-sections the rule's ranking had no relationship to what followed. The stationary block bootstrap (`block=12`) is what
makes that p-value honest — monthly dates on annual horizons overlap eleven twelfths, and a naive
t-statistic would have overstated the sample size and the significance with it.

**4.2 Nothing survives multiple-comparison correction.** Six roster × rank-key combinations:

| roster | key | hit rate | median net excess | p | **q (BH)** |
|---|---|---|---|---|---|
| sector | `mom12_1` | 60.9% | +3.02% | 0.405 | 0.608 |
| sector | `mom6` | 47.8% | −0.42% | 1.000 | 1.000 |
| sector | `trend` | 30.4% | −3.23% | 0.093 | 0.186 |
| theme | `mom12_1` | 52.2% | +0.09% | 1.000 | 1.000 |
| theme | `mom6` | 26.1% | −5.11% | **0.035** | 0.186 |
| theme | `trend` | 30.4% | −3.66% | 0.093 | 0.186 |

`theme/mom6` at p = 0.035 would have looked publishable in isolation. It is q = 0.186 once the six
tests actually run are counted, and it is a hit rate *below* half in any case.

**4.3 The edge is inside this programme's own noise floor.** Net excess across the 23 theme-roster
trials: **mean +3.98%, median +0.09%, standard deviation 22.39%.** Twelve wins averaging +19.25%,
eleven losses averaging −12.68%. A fat-tailed coin flip.

`strategy-program/PROTOCOL.md` §7 measured a **±21.2-point** noise floor from universe *ordering*
alone. A mean excess of +3.98% against a 22.4% dispersion is not merely insignificant — it is an order
of magnitude smaller than the noise floor this programme already established for itself, and every
promotion decision here is required to be checked against that floor.

**4.4 The original 65.2% headline was an artifact, and both causes are now measured.**

| variant | hit rate | median net excess |
|---|---|---|
| raw (sector roster, no collapse, no costs) | 65.2% | +3.22% |
| collapsed | 60.9% | +3.22% |
| collapsed + 10bp | 60.9% | +3.02% |
| collapsed + 25bp | 56.5% | +2.72% |

Collapsing near-duplicates cost 4.3 points of hit rate on its own: SMH and SOXX were occupying two of
three slots, and this document's earlier semiconductor table counted those as two independent findings
when they are very nearly one. Mean turnover is 1.38 per decision, so costs are real but not decisive.

**4.5 The sign flips between eras.** Splitting the 23 annual trials in half:

| era | n | hit rate | median net excess | IC | t |
|---|---|---|---|---|---|
| 2003-2013 | 11 | 63.6% | +0.68% | **−0.064** | −0.54 |
| 2014-2025 | 12 | 58.3% | +4.85% | **+0.099** | +0.74 |

The information coefficient is *negative* in the first half and positive in the second, and neither
is significant. An effect that reverses sign across an arbitrary midpoint split, on the same rule and
the same candidate set, is noise being read as signal. This is also the sharpest available answer to
"is the result just the post-2014 era?" — it is not even reliably that.

**4.6 The correlation collapse found a pair nobody would have written down.** At 2024-01-02 the
measured partition returned two multi-member groups: `[SMH, SOXX]` — the expected one — and
`[VNQ, XLRE]`, the Vanguard and SPDR real-estate funds. Nothing in this repository ever declared those
two equivalent, and a hand-written duplicate table of the kind `clusters.py` deliberately refuses to
be would have missed it and quietly let a two-slot real-estate bet count as two independent picks.
That is the design argument for measuring rather than declaring, confirmed by the measurement.

## 5. What this says about the actual goal

The goal is to find the next semiconductors. The research says the *selection* half of that is not
where the difficulty lives.

The rule already finds the themes. What it does not do is distinguish the 2020 TAN pick (+68% net)
from the 2021 TAN pick (−44.6% net) — the same fund, the same rule, consecutive years, opposite
outcomes. With IC ≈ 0 there is no evidence a better rank key fixes that, and three were tried.

The distribution points somewhere specific: wins average +19.25% and losses −12.68% on near-equal
counts. **The asymmetry a discovery system needs has to come from exits and risk control, not from
better ranking.** That is a testable next step rather than a slogan — `app.tournament.runner` and the
card grammar already carry stop and exit machinery, and the exam here can grade a selector with an
exit rule attached exactly as it grades one without.

## 6. What changes for the programme

The existing sector-rotation cards — `c20-rotation`, `c07-chop`, `c10-momentum` — all failed the
selection gates while competing against hindsight-picked semiconductor baskets on excess-versus-SPY.
They were graded against the wrong benchmark for what they are. Re-scoring them against the
equal-weight sector basket is cheap and should happen before concluding rotation does not work.

## 7. Known limitations

- **Both rosters are chosen in 2026.** For the sector roster the bias is second-order: a fund closes
  for failing to gather assets, a company delists for failing, and XLE survived 2014-2020 while XLF
  and KRE survived 2008. **For the theme roster it is materially worse** — thematic ETFs close far
  more often and their closures correlate with the theme having failed. Every fund in
  `THEME_ETF_ROSTER` launched, gathered assets and survived to 2026; the cohort it was drawn from
  includes a long tail that did not, and this repository has no record of them. The two rosters are
  kept separate for exactly this reason, and a result appearing only on the theme roster should be
  read as the more suspect one.
- **In-sample era.** These dates overlap the same era as every other figure in the programme.
- **Costs are charged to the selector and not to the benchmark**, which biases against the selector.
  That is the intended direction, but it is not neutral.
- **Single-ticker discovery is not implemented**, and cannot be until a survivorship-free price
  history exists. `stooq` is not the route: as of 2026-08-24 it gates every request — including live
  tickers — behind a JavaScript proof-of-work bot check, so it serves no CSV at all. It was not
  bypassed and should not be. That leaves a paid dataset (CRSP, Norgate, Sharadar, EODHD); the
  `CandidateSet` protocol is the shape the answer plugs into.
- **No slippage or market impact beyond the flat basis-point charge**, and no tax.
