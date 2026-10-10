# Round 5 — report: the horizon ladder

**Field:** 15 cards. **Matrix:** 27 windows, 6 months to 10 years, none used in rounds 1–4.
**Gate:** 2 windows per horizon. **Headline metric:** *annualized* adjusted excess.
**405 of 405 run files**, zero failed windows, every card eligible for every window.

Round 5 asked one question: **does the ranking depend on how long you hold the competition open?**

**It does, and more than round 4's regime effect did.**

---

## 1. The result

Median annualized adjusted excess per horizon, ladder arm, ordered by the 10-year column. The number
in brackets is the card's rank at that horizon.

| card | 6m | 1y | 3y | 5y | 10y | rank move |
|---|---|---|---|---|---|---|
| `B-momentum` | 3 (+2.8%) | 4 (+7.9%) | 3 (+14.7%) | 2 (+14.9%) | **1 (+7.6%)** | 3 → 1 |
| `B2-hold-90` | 4 (+2.8%) | 2 (+19.4%) | 5 (+13.3%) | 3 (+13.0%) | 2 (+7.6%) | 4 → 2 |
| `B4-tight-stop` | 5 (+2.8%) | 5 (+7.6%) | 2 (+14.7%) | 1 (+15.1%) | 3 (+7.1%) | 5 → 3 |
| `B3-concentrated` | 2 (+3.7%) | 9 (+2.2%) | 1 (+15.4%) | 5 (+8.3%) | 4 (+5.8%) | 2 → 4 |
| `A-rotation` | **1 (+19.9%)** | **1 (+31.6%)** | 4 (+14.5%) | 4 (+10.5%) | 5 (+5.3%) | **1 → 5** |
| `C-trend` | 9 (+0.1%) | 3 (+9.1%) | 6 (+8.8%) | 6 (+7.4%) | 6 (+4.5%) | 9 → 6 |
| `H-trend-diversified` | 14 (−2.3%) | 7 (+4.5%) | 7 (+7.4%) | 7 (+4.8%) | 7 (+3.4%) | **14 → 7** |
| `c07-chop` | 10 (+0.1%) | 8 (+3.4%) | 8 (+2.4%) | 8 (+3.3%) | 8 (+0.8%) | 10 → 8 |
| `c09-convex` | 8 (+0.7%) | 11 (−0.3%) | 11 (−0.7%) | 10 (−0.5%) | 9 (−0.5%) | 8 → 9 |
| `c18-meanrev` | 13 (−2.2%) | 10 (+0.7%) | 12 (−0.8%) | 11 (−1.1%) | 10 (−0.9%) | 13 → 10 |
| `c21-uncorrelated` | 11 (−0.7%) | 14 (−2.4%) | 9 (+1.5%) | 12 (−2.4%) | 11 (−1.4%) | 11 → 11 |
| `c19-volatility` | 6 (+1.5%) | 6 (+5.4%) | 10 (+1.1%) | 9 (+2.9%) | 12 (−1.7%) | **6 → 12** |
| `c14-riskmanaged-wide` | 12 (−0.7%) | 13 (−1.3%) | 13 (−1.3%) | 13 (−2.8%) | 13 (−1.8%) | 12 → 13 |
| `c11-breakout` | 7 (+1.0%) | 12 (−1.3%) | 14 (−2.0%) | 14 (−4.0%) | 14 (−2.4%) | **7 → 14** |
| `c20-rotation` | 15 (−6.4%) | 15 (−4.7%) | 15 (−3.9%) | 15 (−4.3%) | 15 (−3.8%) | 15 → 15 |

Five cards move six or more places between the shortest and longest rung. **The card that wins at
six months and one year finishes fifth at ten years.**

## 2. Three findings

### 2.1 Measured edge shrinks with horizon, and it is not subtle

| horizon | best card | 5th best | field median |
|---|---|---|---|
| 6m | +19.92% | +2.80% | +0.65% |
| 1y | **+31.55%** | +7.65% | +3.45% |
| 3y | +15.36% | +13.32% | +2.38% |
| 5y | +15.12% | +8.33% | +3.28% |
| 10y | **+7.59%** | +5.28% | +0.85% |

The best annualized figure in the field falls from **+31.6% at one year to +7.6% at ten** — the same
cards, the same engine, the same metric, the same calendar. A one-year window is a draw from a
distribution whose spread is wide enough to produce a +31% annualized result; a decade averages that
spread away and leaves something four times smaller.

**Rounds 1–4 measured exclusively in the 45–284 session range**, i.e. entirely inside the two rungs
where the numbers are largest and least stable. Every headline this programme has published is from
that band.

### 2.2 The variant experiments measure nothing at a long hold

This is the most direct consequence for the programme's own history.

| | 1y | 10y |
|---|---|---|
| `B-momentum` | +7.89% | **+7.59%** |
| `B2-hold-90` | +19.43% | **+7.56%** |
| `B4-tight-stop` | +7.65% | **+7.14%** |
| spread | **11.8 points** | **0.45 points** |

`B2-hold-90` differs from its base by one decision — a 90-day maximum hold. At one year that decision
is worth 11.5 points and promoted `B2` in round 3. **At ten years the three variants are within half
a point of each other**, which is to say the decision is invisible. Round 4 already declined to
promote `B2`; round 5 explains why the round-3 result existed at all, and suggests the entire
take-profit / max-hold axis — four cards and three rounds of attribution — was measuring the length
of the window rather than the merit of the rule.

### 2.3 The bear arm inverts the ladder, and identifies the real hedges

Six windows selected for a falling benchmark (−11.6% to −25.3%), reported separately and never
pooled into the ladder's medians. Sorted by the gap between the two arms:

| card | bear median | ladder median | bear − ladder |
|---|---|---|---|
| `c20-rotation` | **+10.07%** | −4.72% | **+14.79 pts** |
| `c18-meanrev` | +3.80% | −1.06% | +4.86 |
| `c14-riskmanaged-wide` | +3.48% | −1.30% | +4.78 |
| `c11-breakout` | +3.12% | −1.26% | +4.38 |
| `c21-uncorrelated` | +2.43% | −1.29% | +3.72 |
| `c09-convex` | +2.30% | −0.49% | +2.79 |
| `H-trend-diversified` | +2.92% | +3.77% | −0.84 |
| `B-momentum` | +5.59% | +10.17% | −4.59 |
| `C-trend` | −0.09% | +4.98% | −5.07 |
| `c19-volatility` | −7.35% | +1.70% | −9.04 |
| `A-rotation` | −0.14% | +10.67% | **−10.81 pts** |

`c20-rotation` is **last of fifteen at every ladder horizon and first in the bear arm.** Round 4
ranked it 12th of 14 and recorded that its analyst's correlation prediction was falsified. Round 5
shows what the card actually is: not a failed strategy but an unlabelled hedge, and the single
clearest bear/bull separation in the field.

`c19-volatility` runs the other way — a "panic-bid" card that is *worse* in panics (−7.35%) than in
ordinary markets (+1.70%). Its round-4 memo predicted `banks-2023` as its best window and `oil-2014`
as its worst, and got both exactly backwards. Round 5's bear arm is the third independent
falsification of that card's mechanism story.

---

## 3. The benchmarks: SPY, and what QQQ does to the result

The engine scores every card against **SPY**. That is the right default for a general-purpose
programme, and it is what every number in sections 1 and 2 uses. It is also, for this particular
field, the flattering choice: the top cards are AI and semiconductor books, and SPY is not what they
are competing with.

QQQ was re-derived here from the bar store for all 27 windows against every card's own capital
exposure. **These figures are a re-derivation, not a re-run** -- the same trades, the same equity
curves, the same exposures, with only the benchmark term of `annualized_adjusted_excess` swapped.

One bookkeeping point, because it would otherwise show up as two different SPY numbers for the same
cell. The SPY columns below are the **engine's own** `benchmark_return`, identical to section 1's
figures; only the QQQ columns are re-derived. The engine measures its benchmark over the session
calendar it actually traded, while the appendix's table measures both indices over the window's
calendar dates, and the two differ by a session or two at the edges -- **a mean of 0.25 and at most
0.85 annualized points** across the 21 ladder windows. That is immaterial to every claim here, but
mixing the two sources within one table would have put `A-rotation`'s 1-year cell at +31.6% in one
section and +31.9% in another for no reason a reader could see.

### 3.1 What the two benchmarks did

Mean annualized return over the ladder's windows, by horizon:

| horizon | SPY | QQQ | gap |
|---|---|---|---|
| 6m | +10.71% | +11.99% | +1.28 pts |
| 1y | +9.98% | +15.35% | +5.36 pts |
| 3y | +11.81% | +17.56% | +5.75 pts |
| 5y | +13.15% | +19.86% | +6.72 pts |
| **10y** | **+12.14%** | **+18.56%** | **+6.41 pts** |

Over the ladder as a whole QQQ compounds at +15.76% a year against SPY's +11.20%, and beats it in 17
of 21 windows. In the bear arm the ordering is not stable: QQQ falls harder in three of the six
(-53.0% annualized in `b6m-2`) and much less in the other three (-20.0% against SPY's -43.9% in
`b6m-1`, the covid crash).

### 3.2 The ladder, scored against each

Median annualized adjusted excess, ladder arm. `SPY` is the figure reported in section 1; `QQQ` is
the same quantity with the benchmark swapped.

| card | 6m SPY | 6m QQQ | 1y SPY | 1y QQQ | 3y SPY | 3y QQQ | 5y SPY | 5y QQQ | 10y SPY | 10y QQQ |
|---|---|---|---|---|---|---|---|---|---|---|
| `B2-hold-90` | +2.8% | +1.4% | +19.4% | +19.1% | +13.3% | +11.7% | +13.0% | +8.4% | **+7.6%** | **+4.6%** |
| `B-momentum` | +2.8% | +1.4% | +7.9% | +6.4% | +14.7% | +11.7% | +14.9% | +9.3% | **+7.6%** | **+3.9%** |
| `B4-tight-stop` | +2.8% | +1.4% | +7.6% | +6.2% | +14.7% | +11.8% | +15.1% | +7.8% | +7.1% | +3.5% |
| `B3-concentrated` | +3.7% | +2.2% | +2.2% | +0.2% | +15.4% | +11.2% | +8.3% | +7.3% | +5.8% | +1.9% |
| `H-trend-diversified` | -2.3% | -2.4% | +4.5% | +3.9% | +7.4% | +6.3% | +4.8% | +1.9% | +3.4% | +1.3% |
| `C-trend` | +0.1% | -2.3% | +9.1% | +6.5% | +8.8% | +7.1% | +7.4% | +2.5% | +4.5% | +1.3% |
| `A-rotation` | **+19.9%** | **+15.3%** | **+31.6%** | **+23.7%** | +14.5% | +11.8% | +10.5% | +3.4% | +5.3% | **+0.6%** |
| `c07-chop` | +0.1% | -0.2% | +3.4% | +3.2% | +2.4% | +1.6% | +3.3% | +2.7% | +0.8% | +0.3% |
| `c09-convex` | +0.7% | +0.7% | -0.3% | -0.9% | -0.7% | -1.4% | -0.5% | -1.4% | -0.5% | -1.0% |
| `c18-meanrev` | -2.2% | -2.4% | +0.7% | +0.3% | -0.8% | -1.5% | -1.1% | -2.6% | -0.9% | -1.8% |
| `c19-volatility` | +1.5% | +1.4% | +5.4% | +5.0% | +1.1% | +0.1% | +2.9% | +1.9% | -1.7% | -2.6% |
| `c21-uncorrelated` | -0.7% | -1.6% | -2.4% | -3.6% | +1.5% | -0.2% | -2.4% | -4.1% | -1.4% | -3.1% |
| `c14-riskmanaged-wide` | -0.7% | -0.8% | -1.3% | -3.5% | -1.3% | -3.1% | -2.8% | -5.4% | -1.8% | -3.2% |
| `c11-breakout` | +1.0% | +1.1% | -1.3% | -3.6% | -2.0% | -4.6% | -4.0% | -7.3% | -2.4% | -4.9% |
| `c20-rotation` | -6.4% | -4.6% | -4.7% | -5.7% | -3.9% | -6.4% | -4.3% | -7.1% | -3.8% | -6.1% |

### 3.3 What changes, and what does not

**The ordering barely moves. The magnitudes roughly halve.**

The same eight cards are positive at ten years against either benchmark, and section 2's horizon
findings survive intact -- they are relative statements across horizons on a fixed field, and
swapping the benchmark moves every card in the same direction.

What does not survive is the *size* of the decade edge:

| | 10y vs SPY | 10y vs QQQ |
|---|---|---|
| `B-momentum` | +7.59% | **+3.9%** |
| `B2-hold-90` | +7.56% | +4.6% |
| `C-trend` | +4.45% | +1.3% |
| `A-rotation` | +5.28% | **+0.6%** |

**`A-rotation`'s ten-year edge over a Nasdaq-100 tracker is +0.6% a year**, at 65.8% mean capital
exposure -- the highest in the field. The card that wins the 6-month rung by 16 points and the 1-year
rung by 12 has, over a decade, done approximately what QQQ did, while taking concentrated
single-name risk to get there. That is the same card round 4's control arm reinstated and round 5's
ladder put first at short horizons; this is the third distinct measurement to qualify it.

This is the quantitative form of the survivorship caveat in section 4. A 2026-chosen semiconductor
basket run from 2013 should be expected to beat a broad-market index; the question is whether it
beats the index holding the same kind of company, and mostly it does not by much.

**SPY remains the reported benchmark**, for continuity with rounds 1-4 and because the field is not
all tech: `c14`, `c20` and `c21` hold Treasuries, gold, commodities and EM equities, for which QQQ is
meaningless as a hurdle. The right reading is that **the two columns bracket the answer**, and for
the AI and semiconductor books the QQQ column is the more demanding and the more relevant one.

---

## 4. The caveat that limits everything above

**Every top-ranked card is a 2026-chosen basket run over the decade its names won.**

`A-rotation` is nine semiconductor names. `B-momentum` holds NVDA, AVGO, TSM, MSFT and eight others.
`C-trend` holds NVDA, AVGO, TSM, SOXX. These universes were selected by analysts writing in 2026,
and round 5 runs them from 2013. The 10-year rung is precisely the window over which knowing which
semiconductor names to hold was worth the most.

The programme's survivorship gate (`universe_knowable_from`) does not catch this: it fires only on a
universe *mechanically derived* from a current index constituent list, and these were picked by
thesis. That distinction was the right call for the regime windows of rounds 2–4, which were mostly
months long. **Over a ten-year hold it is much weaker than it looks**, and the honest reading of the
+7.6% decade figures is that an unknown and probably large share of them is basket selection rather
than rule quality.

This does not undo sections 2.1 or 2.2 — those are *relative* statements across horizons on a fixed field,
and the bias is roughly common to the top cards. It does mean **the absolute level of every long-rung
number should be treated as an upper bound.**

Three further limits, restated from the plan:

- **Not out-of-sample.** Every window ends on or before the 2026-02-13 design cutoff.
- **The long rungs are nearly one sample.** The two 10-year windows share 62% of their sessions.
- **One era.** No decade in the available data has a falling benchmark; the 10y rung has no bear
  sample at all, and the ladder's benchmark rises in 19 of 21 windows.

---

## 5. Why the whole-matrix table in `scorecard.json` is the wrong table

The scorer still prints a single ranking over all 27 windows on raw adjusted excess. Read it as a
demonstration, not a result: it reports `c20-rotation`'s worst window as **−92.94%**, which is a
ten-year raw adjusted excess against a +259% benchmark, not a catastrophe. `c11-breakout` shows
−72.32% the same way.

Those figures are what the metric does when a matrix spans a factor-of-twenty in window length, and
they are exactly why round 5 needed the annualized per-horizon tables. Every number quoted in this
report is annualized and taken within a single horizon.

## 6. Harness changes

- **`score.py` gained annualized metrics and per-horizon aggregation** — `window_years`,
  `annualized_return`, `annualized_adjusted_excess`, an `R5_MATRIX` with a per-horizon gate of 2, and
  separate ladder/bear horizon tables. Rounds 2–4 reproduce byte-identically, guarded by a test.
  `window_years` comes from `sessions / 252` because **an `AgentResult` carries no window dates** —
  they exist only on the sibling `tournament.json`, which the scorer never reads. Checked against the
  real matrix, that lands within 1% of every horizon's true length.
- **`portfolio.py` gained an opt-in `annualized=` for correlations**, plus a `--windows` filter.
  Correlating a decade's return against a half-year's is dominated by which windows are long: on a
  constructed four-window case the raw correlation is **+0.767** and the annualized one is
  **−0.492**, from the same (card, window) pairs. Off by default so rounds 1–4's published figures
  keep reproducing.
- **27 windows registered** in `windows.py`, `jobs.py` and `GET /competition/windows`, which gained a
  `horizon` field and `r5-ladder` / `r5-bear` matrix values, with an anti-drift test pinning all 27
  against `windows.json`.
- **The paper-desk roster is now configuration**, not a source constant — required by round 6.

## 7. Reproduction

```
python -m app.tournament --cards <field> --out data/rounds/r5-2026-08/results/<tag> \
  --persona uat/personas/pro-investor-01.setup.json --skip-pdf --start <start> --end <end>

python strategy-program/tools/score.py --results data/rounds/r5-2026-08/results \
  --eligibility data/rounds/r5-2026-08/eligibility.json \
  --json data/rounds/r5-2026-08/scorecard.json --matrix r5 --rank-by borda
```

Window definitions are in `data/rounds/r5-2026-08/windows.json`, which is the contract the run, the
catalogue and the tests all read.

---

## Appendix -- benchmark returns for all 27 windows

Total and annualized buy-and-hold return of SPY and QQQ over each window. `sess` is trading
sessions; annualization is `(1 + total) ** (252 / sess) - 1`, the convention the scorer uses.

| arm | tag | H | sess | SPY total | QQQ total | SPY ann | QQQ ann |
|---|---|---|---|---|---|---|---|
| ladder | `h10y-1` | 10y | 2517 | +174.0% | +398.0% | +10.62% | +17.44% |
| ladder | `h10y-2` | 10y | 2515 | +259.2% | +500.5% | +13.67% | +19.68% |
| ladder | `h5y-1` | 5y | 1260 | +76.6% | +145.9% | +12.05% | +19.72% |
| ladder | `h5y-2` | 5y | 1259 | +106.9% | +235.7% | +15.66% | +27.43% |
| ladder | `h5y-3` | 5y | 1256 | +73.8% | +79.4% | +11.73% | +12.44% |
| ladder | `h3y-1` | 3y | 756 | +27.5% | +43.3% | +8.44% | +12.73% |
| ladder | `h3y-2` | 3y | 754 | +43.8% | +81.5% | +12.92% | +22.05% |
| ladder | `h3y-3` | 3y | 756 | +22.9% | +31.7% | +7.13% | +9.61% |
| ladder | `h3y-4` | 3y | 751 | +67.0% | +98.5% | +18.77% | +25.86% |
| ladder | `h1y-1` | 1y | 252 | +14.0% | +18.6% | +14.04% | +18.57% |
| ladder | `h1y-2` | 1y | 254 | +23.8% | +29.0% | +23.58% | +28.73% |
| ladder | `h1y-3` | 1y | 251 | +1.6% | +4.2% | +1.57% | +4.25% |
| ladder | `h1y-4` | 1y | 253 | +16.5% | +42.3% | +16.46% | +42.06% |
| ladder | `h1y-5` | 1y | 251 | -7.3% | -13.2% | -7.33% | -13.23% |
| ladder | `h1y-6` | 1y | 250 | +11.5% | +11.6% | +11.59% | +11.69% |
| ladder | `h6m-1` | 6m | 126 | +6.5% | +9.0% | +13.34% | +18.87% |
| ladder | `h6m-2` | 6m | 127 | +7.8% | +10.5% | +16.03% | +21.82% |
| ladder | `h6m-3` | 6m | 126 | -2.4% | -4.4% | -4.65% | -8.57% |
| ladder | `h6m-4` | 6m | 126 | +15.9% | +20.1% | +34.26% | +44.32% |
| ladder | `h6m-5` | 6m | 127 | -3.7% | -7.0% | -7.13% | -13.37% |
| ladder | `h6m-6` | 6m | 125 | +6.0% | +4.3% | +12.42% | +8.86% |
| bear | `b6m-1` | 6m | 127 | -25.3% | -10.7% | -43.87% | -20.04% |
| bear | `b6m-2` | 6m | 127 | -22.1% | -31.6% | -39.06% | -53.00% |
| bear | `b6m-3` | 6m | 127 | -13.5% | -16.3% | -25.05% | -29.68% |
| bear | `b1y-1` | 1y | 253 | -21.0% | -35.2% | -20.94% | -35.12% |
| bear | `b1y-2` | 1y | 253 | -20.2% | -4.5% | -20.09% | -4.52% |
| bear | `b1y-3` | 1y | 253 | -11.6% | -7.9% | -11.59% | -7.82% |

Note `b6m-1` (2019-09-20 to 2020-03-23, into the covid low): SPY -25.3%, QQQ -10.7%. The Nasdaq-100
fell *less* than the broad market there, which is why "QQQ is the harder benchmark" holds across the
ladder but not uniformly in the bear arm.
