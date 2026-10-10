# Round 4 — report

**Field:** 14 cards (10 returning, 4 new). **Matrix:** six windows, none used in rounds 1–3.
**Gate:** 4 of 6. **Headline metric:** adjusted excess (`total_return − capital_exposure × benchmark_return`).

Round 4 was a confirmation round. It set out to settle four things: promote or reject `B2-hold-90`,
confirm or reject `c14-riskmanaged-wide`, measure whether four newly-submitted cards are actually
uncorrelated with the incumbents, and score the combined book rather than only the cards.

**All four came back negative, and the fourth explains the other three.**

---

## 1. The finding: round 3's conclusions were properties of round 3's windows

Round 3 promoted `c14-riskmanaged-wide` to the Pareto frontier and produced this programme's
strongest result to date — that combining `B-momentum`, `C-trend` and `c14` in equal thirds roughly
halves the worst window, because `c14` is uncorrelated with the equity legs. Round 4 ran the same
cards, unchanged, on six windows they had never seen. Every part of that result inverted.

The reason is not subtle once the two matrices are put side by side:

| | round 3 matrix (8 windows) | round 4 matrix (6 windows) |
|---|---|---|
| mean benchmark return | **−9.45%** | **+17.13%** |
| median benchmark return | −4.38% | +5.62% |
| windows with a negative benchmark | **6 of 8** | **2 of 6** |
| deepest window | `gfc` −56.2% | — |
| strongest window | `recent` +20.6% | `recovery-2009` **+75.2%** |

Round 3 measured on a bear-weighted matrix. Round 4 measured on a bull-weighted one. A low-exposure,
flight-to-quality leg wins the first and loses the second **mechanically** — nothing about the card
changed between the two rounds, and nothing needed to.

This is the D2 asymmetry, seen from the other side. The programme has spent three rounds catching
cards flattered by raw excess for not participating in a crash. `recovery-2009` is the mirror: a
+75.2% benchmark, where adjusted excess measures *how little capital you had deployed into a rally*
and punishes it exactly as hard. Both directions are the same artifact of the same correction, and
neither window matrix is a sample of the future.

---

## 2. Leaderboard (all six windows, ranked by Borda composite)

| rank | card | median adj. excess | worst | hit | windows run/elig | mean exposure | Pareto |
|---|---|---|---|---|---|---|---|
| 1 | `B3-concentrated` | **+8.60%** | **+0.16%** | **100%** | 5/4 | 37.4% | **yes** |
| 2 | `B-momentum` | +5.82% | +0.04% | 100% | 5/4 | 29.9% | no |
| 3 | `B4-tight-stop` | +5.23% | +0.04% | 100% | 5/4 | 29.3% | no |
| 4 | `c07-chop` | +2.00% | −0.28% | 83% | 6/6 | 12.4% | no |
| 5 | `C-trend` | +1.70% | −1.89% | 60% | 5/5 | 36.8% | no |
| 6 | `B2-hold-90` | +0.75% | −4.96% | 80% | 5/4 | 26.8% | no |
| 7 | `c19-volatility` | +1.54% | −7.91% | 67% | 6/6 | 15.8% | no |
| 8 | `H-trend-diversified` | +0.03% | −6.36% | 60% | 5/5 | 18.2% | no |
| 9 | `c09-convex` | −0.66% | −4.77% | 17% | 6/6 | 8.1% | no |
| 10 | `c11-breakout` | −1.01% | −20.68% | 17% | 6/6 | 19.2% | no |
| 11 | `c18-meanrev` | −3.24% | −4.47% | **0%** | 6/6 | 19.0% | no |
| 12 | `c20-rotation` | −0.73% | −23.19% | 17% | 6/6 | 34.6% | no |
| 13 | `c14-riskmanaged-wide` | −2.32% | −19.78% | 17% | 6/6 | 22.4% | no |
| 14 | `c21-uncorrelated` | −1.46% | −26.55% | 17% | 6/6 | 23.1% | no |

`B3-concentrated` is the **only** card on the Pareto frontier — no other card matches it on median,
worst-window and hit rate together.

**The ranking is robust to how the matrix is cut.** Three scorings were run and the top of the table
does not move:

| | 6 windows | 5 windows (no `recovery-2009`) | 4 windows (common to every card) |
|---|---|---|---|
| 1st | `B3-concentrated` | `B3-concentrated` | `B3-concentrated` |
| 2nd | `B-momentum` | `B-momentum` | `c07-chop` (frontier) |
| 3rd | `B4-tight-stop` | `B4-tight-stop` | `B-momentum` |
| `c14` | 13th | 13th | 12th |
| `B2-hold-90` | 6th | 7th | 7th |

The 4-window column is the like-with-like comparison `ROUND-4-PLAN.md` §4 asked for. It is the only
column where every card ran every window, and it is where `c07-chop` joins `B3-concentrated` on the
frontier (+3.86% median, +1.42% worst, 100% hit).

### One eligibility disagreement, disclosed

The four `B*` cards have run files for `taper-2013`, which the eligibility map marks ineligible:
`NOW`'s first stored bar is 2012-06-29 and the map wants it on or before 2012-06-09. The runner's
lookahead guard is bar-count based and passed; the map's rule demands a fixed calendar warmup margin
and failed, by twenty days on one symbol of twelve. The scorer includes the window and flags the
disagreement on every affected row.

It does not change any verdict: the `B*` family is map-eligible for exactly 4 of 6 windows, which
clears the gate on its own, and the 4-window column above excludes `taper-2013` entirely.

---

## 3. Question 1 — promote `B2-hold-90`? **No.**

`PROTOCOL.md` §6 requires a variant to beat its base on a second round of windows the card has not
seen. It did not.

| | round 3 (8 windows) | round 4 (6 windows) |
|---|---|---|
| `B2-hold-90` median adj. excess | **+16.3%** | **+0.75%** |
| `B-momentum` median adj. excess | +12.2% | +5.82% |
| `B2` worst / hit | −5.1% / 67% | −4.96% / 80% |
| `B-momentum` worst / hit | −5.1% / 67% | **+0.04% / 100%** |

`B2` loses to its own base on all three axes in round 4, and it is the *only* B-family card with a
negative worst window. `B2` differs from `B-momentum` in exactly one decision — a 90-day maximum hold
— and the trade log attributes the loss to it directly. In `inflation-2021`, a 252-session window,
both cards take the same 16 trades; the base holds its longest for 180 sessions and returns
**+25.20%**, while `B2`'s cap fires **four** time-exits against the base's one and it returns
**+5.24%**. Twenty points of the difference sit in that one rule. Round 3's matrix had one window
long enough for the cap to bind on a working trade; round 4's has two.

**Verdict: `B2-hold-90` is not promoted.** The take-profit/max-hold axis has now been tested three
ways (`B1-with-target`, `B2-hold-90`, and `B-momentum`'s own memo) and no version has beaten the base
twice. Recommend retiring it and closing the axis.

## 4. Question 2 — confirm `c14-riskmanaged-wide`? **No, as a card. Yes, as a leg.**

| | round 3 | round 4 |
|---|---|---|
| median adj. excess | +2.3% | **−2.32%** |
| worst window | **−1.0%** (best in round) | **−19.78%** |
| hit rate | **75%** (best in round) | 17% |
| rank | Pareto frontier | 13th of 14 |

The entire reversal is one window. `c14` deployed 28.0% of capital into `recovery-2009` and returned
+1.29% against a +75.24% benchmark — a −19.78% adjusted excess. Strip that window out and `c14`'s
worst becomes −4.34%, which is an ordinary result, not a collapse.

That is not a defence of the card. It is the finding: **`c14`'s value is entirely conditional on the
benchmark falling**, and the round-3 matrix supplied that condition six times in eight.

But the correlation claim it was promoted for **replicated, and strengthened**:

| pair | round 3 ρ | round 4 ρ (n=5) |
|---|---|---|
| `B-momentum` / `C-trend` | +0.57 | **+0.889** |
| `C-trend` / `c14` | +0.04 | **−0.554** |
| `B-momentum` / `c14` | — | **−0.652** |

`c14` is not merely uncorrelated with the equity legs — on these windows it is *negatively*
correlated. And `B` and `C` are more redundant than round 3 measured, not less.

**Verdict: `c14` is not confirmed as a standalone card and does not rank.** It is kept in the library
as a hedging leg only, with its conditionality written on it. It should never again be scored on
median adjusted excess as if that were the thing it is for.

## 5. Question 3 — are the four new cards uncorrelated with the incumbents? **No. All four failed.**

Correlation of per-window returns to `B-momentum`, whole field (n = 5 shared windows):

| card | predicted ρ | measured ρ | verdict |
|---|---|---|---|
| `c14-riskmanaged-wide` | — | **−0.652** | the field's genuine diversifier |
| `c09-convex` | — | −0.466 | genuinely uncorrelated |
| `c11-breakout` | — | −0.382 | genuinely uncorrelated |
| `c07-chop` | — | +0.169 | genuinely uncorrelated |
| `c19-volatility` | 0.1–0.2 | **+0.259** | closest call in the round |
| `c21-uncorrelated` | 0.1–0.3 | **+0.907** | **falsified** |
| `c20-rotation` | 0.25–0.40 | **+0.917** | **falsified** |
| `c18-meanrev` | 0.10–0.25 | **+0.918** | **falsified** |
| `B4-tight-stop` | — | +1.000 | (variant of B, as expected) |

The two cards submitted **specifically** to be the uncorrelated leg — `c20-rotation` and
`c21-uncorrelated` — are the two most correlated cards in the field with `B-momentum`, above even
`C-trend`. The cards that are actually uncorrelated are ones nobody submitted for that purpose.

**Why, and the methodological point that matters.** Window-level return correlation over six windows
is dominated by whether the window was a bull or a bear regime, so it is close to a measure of equity
beta. `c20` and `c21` are long-only trend books on sector ETFs, commodities and EM equities; they
carry real beta and go up when the market goes up. `c14` holds Treasuries and gold and does not.

Both analysts anticipated part of this and both got it wrong in the same direction. Their memos
measured *daily-return* correlation to a QQQ or B-momentum composite (0.36 and 0.41 respectively)
over hundreds of observations, and predicted the window-level figure would come in **lower**.
It came in at 0.91. `c21`'s memo pre-registered the exact test and the exact consequence — *"If the
realized number lands well above 0.3 … the correlation argument in this memo is wrong and should be
read as such, not explained away"* — and that is how it is recorded here.

Daily-return correlation and window-return correlation are different statistics, and only the second
one is what the combined-book scorer uses. **Round 5's brief must say so explicitly**; three of four
analysts optimised against the wrong one.

## 6. Question 4 — score the combined book

Equal weight, rebalanced per window, a member that cannot run a window held as cash:

| book | windows | median adj. | worst adj. | hit |
|---|---|---|---|---|
| `B3-concentrated` alone | 5 | **+8.60%** | +0.16% | 100% |
| `B-momentum` alone | 5 | +5.82% | +0.04% | 100% |
| **`B3` + `c07`** | **6** | **+4.46%** | **+0.19%** | **100%** |
| **`B` + `c07`** | **6** | **+3.30%** | **+0.19%** | **100%** |
| `B` + `C` | 5 | +5.70% | −0.93% | 60% |
| `B` + `c19` | 6 | +2.84% | −1.04% | 67% |
| `B` + `c07` + `c09` | 6 | +2.05% | −1.46% | 83% |
| `B` + `c07` + `c14` | 6 | +1.76% | −6.47% | 83% |
| **`B` + `C` + `c14` (round 3's book)** | 6 | **+1.06%** | **−6.59%** | **50%** |
| `B` + `c20` | 6 | +0.58% | −11.59% | 67% |
| `B` + `c21` | 6 | +0.50% | −13.28% | 50% |

**Round 3's combined book does not replicate.** It is beaten by `B-momentum` alone on every axis.
Adding the two cards designed as diversifiers (`c20`, `c21`) makes the worst window three to four
times deeper than holding `B` on its own.

**What did work:** `B` + `c07-chop` and `B3` + `c07-chop`. Both cover all six windows at a 100% hit
rate with a positive worst window, and `c07` is one of the three genuinely uncorrelated cards.

**The honest caveat on that result, which is large.** `c07`'s `recovery-2009` cell is **one trade at
0.8% capital exposure**. Its +0.19% adjusted excess there is non-participation in a +75% rally, not a
hedge — the exact pattern that got `c12-meanrev-wide` retired last round. The `B`+`c07` book's
perfect hit rate is therefore built partly on a spectator cell in the one window `B` cannot run at
all. Read it as *"coverage without damage"*, not as *"the pair earns in a recovery"*.

**The generalisable claim from all of this is narrow:** on six windows against a ±21-point noise
floor, no combination beat its strongest single leg on median. Combination bought window coverage and
worst-case protection when — and only when — the matrix contained drawdowns to protect against.

---

## 7. Control arm: the round-4 trim was regime-conditional, and it was written up as structural

This was not pre-registered. It was run after the leaderboard, because §1 implied it.

`ROUND-4-PLAN.md` §3 retired the five-card A family together, on this reasoning: *"Every one posts a
negative median adjusted excess … and the highest capital exposure in the field (≈0.48). That
combination is the specific thing this programme was built to detect: they look acceptable on raw
return because they are heavily invested in a rising market, and they lose once that exposure is paid
for."*

The five retired A cards were re-run, unchanged, on round 4's six windows:

| card | median adj. excess | worst | hit | mean exposure | would rank |
|---|---|---|---|---|---|
| `A-rotation` | **+4.20%** | **+0.20%** | **100%** | 76.5% | **2nd of 19** |
| `A4-tight-stop` | +4.20% | +0.20% | 100% | 76.4% | 3rd |
| `A3-no-target` | +3.02% | −0.74% | 80% | 77.0% | 6th |
| `A2-cash-headroom` | +2.58% | −0.97% | 80% | 72.0% | 8th |
| `A1-alpha-order` | +0.40% | −6.50% | 60% | 76.5% | 12th |

(`recovery-2009` is structurally ineligible for all five — `AVGO`'s first bar is 2009-08-06 — so
these are five windows, and the rank column is against the round-4 field scored over the same five.)

`A-rotation` and `A4-tight-stop` finish **ahead of `B-momentum`** on the Borda composite, on the
strength of the best worst-window in the merged field (+0.20%). The scorer flags all five A cards
`incommensurable_exposure = yes` — at 72–77% mean capital exposure they sit far outside the rest of
the field's band, and the flag exists precisely so a number like this is not read as like-for-like.
It qualifies the comparison. It does not rescue the sentence in §3 of the plan, which made a claim
about what happens *after* that exposure is paid for.

**The specific claim in the retirement note is falsified.** After the exposure correction is applied,
at 76.5% mean capital exposure, `A-rotation` posts a positive median and a positive worst window and
finishes ahead of `B-momentum`, `C-trend`, `B2-hold-90` and all five surviving candidates.

What survives of the retirement reasoning: the A family really does run at more than twice the
capital exposure of any card kept, it really did lose badly on a bear-weighted matrix, and the four
variants really are dominated by their own base here as they were there — `A1`, `A2`, `A3` add
nothing to `A-rotation` and their retirement stands on that ground alone.

What does not survive: *"they lose once that exposure is paid for"*, stated without a regime
condition. It should have read *"they lose once that exposure is paid for, on a matrix where six of
eight benchmarks fall."*

**Action taken.** `backend/app/paper/library/retired/README.md` now carries a dated amendment with
these numbers, saying which half of the original reasoning survives and which does not. `A-rotation`
stays on disk and is available as a **high-exposure comparator** — not as a recommended card, and
labelled as measured on two matrices and nothing else. The four A variants stay retired on their own
numbers: they are dominated by their own base on both matrices.

---

## 8. What this round changed in the harness

- **`strategy-program/tools/score.py` now takes the window matrix as a parameter** (`Matrix`,
  `R2_MATRIX`, `R4_MATRIX`, `--matrix`, `detect_matrix`). Every gate computation previously
  intersected against the hardcoded round-2 tuple, so scoring round 4 would have printed a
  well-formed, **empty** leaderboard with no error anywhere — "ran too few main windows" is an
  ordinary unranked verdict. `tests/test_score_matrix.py` pins that failure directly, along with the
  4-of-6 boundary and a regression guard that rounds 2–3 still score at 5-of-8.
- **`app.tournament.jobs` and `GET /competition/windows`** gained round 4's matrix, and `main` on the
  windows endpoint was reconciled to mean *comparable* (`tag not in PROVENANCE_CONSTRAINED_WINDOWS`)
  rather than *in round 2's matrix*, which had briefly rendered all six round-4 regimes as
  not-comparable in the run form. A `matrix` field now says which set a window belongs to.

## 9. Recommendations for round 5

1. **Fix the matrix, not the cards.** Round 3 was 75% bear windows, round 4 was 67% bull. Neither is
   a sample of anything. Round 5's matrix should be **balanced by construction and declared as such**
   — three windows with a falling benchmark, three with a rising one — and every card's result should
   be reported split by that half. Every reversal in this report is explained by a matrix that was
   not.
2. **Retire `B2-hold-90`** and close the take-profit/max-hold axis. Three tests, no promotion.
3. **Keep `c14-riskmanaged-wide` as a labelled hedging leg**, unranked, and stop scoring it on median.
4. **Brief analysts on window-return correlation explicitly.** Three of four optimised against
   daily-return correlation, which is a different statistic and not the one the book is scored on.
5. **Amend `library/retired/README.md`** with §7's numbers, and reinstate `A-rotation` as a
   comparator. A drop reason that turns out to be regime-conditional is a finding, not an
   embarrassment, and the log is the place it belongs.
6. **The standing limitation is unchanged.** No calendar time has passed since round 3, so the design
   cutoff has not moved and no genuinely unseen data exists. Round 4 brought windows the *cards* had
   not seen — which is what §6(a) requires for a promotion — but not data the *analysts* could not
   have studied. Six windows against a ±21-point noise floor is a small sample, and margins inside
   that band have demonstrated nothing. The walk-forward begins when real time has elapsed.

---

## Appendix — reproduction

```
python -m app.tournament --cards <field> --out data/rounds/r4-2026-08/results/<tag> \
  --persona uat/personas/pro-investor-01.setup.json --skip-pdf --start <start> --end <end>

python strategy-program/tools/windows.py --cards <field> --json data/rounds/r4-2026-08/eligibility.json

python strategy-program/tools/score.py --results data/rounds/r4-2026-08/results \
  --eligibility data/rounds/r4-2026-08/eligibility.json \
  --json data/rounds/r4-2026-08/scorecard.json --rank-by borda

python strategy-program/tools/portfolio.py --results data/rounds/r4-2026-08/results \
  --cards B-momentum --cards c07-chop
```

78 run files: 14 cards × 6 windows, less the six the eligibility map and the runner's lookahead guard
agree are unreachable in `recovery-2009` (`AVGO` first bar 2009-08-06, `META` 2012-05-18,
`INDA` 2012-02-03). Control arm: 25 run files under `control-a-family/`, 5 cards × 5 windows.
