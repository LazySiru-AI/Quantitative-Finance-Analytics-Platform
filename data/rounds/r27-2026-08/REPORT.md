# Round 27 — the last three thesis claims, measured

Run 2026-08-30 against `ROUND-27-PLAN.md`, committed at `b51b163` before any measurement existed.
**Not investment advice.** These are signal statistics, not backtests; nothing here is promotable and
nothing here demotes a card.

**Every headline was recomputed independently of the tool that produced it** — the orchestrator re-ran
the pooled figures for all three measurements from scratch, and all three matched to the digit. What
follows is verified, not reported.

---

## 1. Pairwise correlation (`A-rotation`) — prediction 1 HELD

The thesis: *"mean 0.589, range 0.286 (INTC vs AVGO) to 0.824 (SOXX vs TSM)"*, on a trailing year to
2026-02-13. Measured across all eight R2 windows:

| window | mean | vs 0.589 | min pair | max pair |
|---|---:|---|---|---|
| `q4-2018` | 0.633 | +0.044 | INTC-AMD 0.350 | MU-SOXX 0.874 |
| `covid` | **0.834** | +0.245 | AMD-AVGO 0.724 | MU-SOXX 0.934 |
| `bear-2022` | **0.795** | +0.206 | INTC-TSM 0.625 | SOXX-MRVL 0.943 |
| `chop-2015` | 0.459 | −0.130 | AMD-MRVL 0.208 | SOXX-AVGO 0.823 |
| `chop-2011` | 0.646 | +0.057 | MU-AVGO 0.470 | SOXX-NVDA 0.829 |
| `bull-2024` | 0.611 | +0.022 | INTC-TSM 0.274 | SOXX-QCOM 0.836 |
| `recent` | 0.520 | −0.069 | NVDA-QCOM 0.191 | MU-SOXX 0.813 |
| `gfc` | 0.599 | +0.010 | AMD-QCOM 0.433 | INTC-SOXX 0.871 |

**Mean is higher than the thesis's 0.589 in 6 of 8 windows** (prediction 1 asked for ≥5), and highest
exactly where predicted — the two most stressed regimes, `covid` and `bear-2022`, at 0.83 and 0.80.
The thesis's design-window figure understates cross-name correlation in most regimes, which supports
rather than undermines its own conclusion: *"this is a concentrated sector bet dressed as a 3-of-9
rotation."* If anything, more concentrated than the thesis admitted.

**Two details the thesis got wrong at the pair level.** The specific min pair it named (INTC-AVGO)
was the min in **zero** of eight windows; the max pair it named (SOXX-TSM) was the max in **zero**.
`SOXX` dominates the max slot as claimed, but paired with MU, MRVL, NVDA or QCOM, never TSM. The
mean claim holds; the two named extremes do not reproduce. Only 7 of 8 windows used all 36 pairs —
`gfc` used 28, because AVGO has no bars before its 2009 IPO.

## 2. Move duration (`B3-concentrated` / `B-momentum`) — prediction 2 REFUTED, prediction 3 HELD

The thesis: *"median duration of roughly 3-4 weeks … past two months at the 75th percentile (NVDA
256, MSFT 169, TSM 189)."* Measured over the twelve shared names, signal (golden cross above the
200-day) to the ema(20)/ema(50) cross back down, censored moves excluded:

| statistic | measured | thesis | reference |
|---|---:|---|---|
| median duration | **47.5 sessions** | "3-4 weeks" | 15–20 sessions |
| 75th percentile | 108.0 sessions | "past two months" | ≥42 sessions |
| n completed / censored | 472 / 6 | — | — |

**Prediction 2 is refuted, and in the opposite direction from every earlier duration figure in this
family.** I predicted the median would come in *below* the claimed band, citing round 26's finding
that `C-trend`'s hold durations ran short (82 vs 118, 12 vs 16). It came in at **47.5 sessions —
two and a half times the top of the thesis's own 3–4 week band.** The move lasts far longer than the
card claims for it.

**That prediction was mine and it was wrong because I conflated two different measurements**, which is
the same source-checking error this programme keeps catching in smaller forms. Round 26 measured a
*book's* winner and loser hold times — bounded by the card's stops, target and 180-session backstop.
This measures the *raw indicator move* with no exits at all. The raw golden-cross-to-death-cross span
is naturally longer than any held position inside it, so the two numbers were never comparable, and my
prediction borrowed round 26's direction without checking that the quantities matched.

**Prediction 3 held:** the 75th percentile is 108 sessions, well past the ≥42 the thesis claims. So
the distribution is right-skewed as the thesis says, just centred more than twice as high.

**The named maxima all exceed their claimed values on full history:**

| name | measured max | thesis |
|---|---:|---:|
| NVDA | 260 | 256 |
| TSM | 224 | 189 |
| MSFT | **576** | 169 |

NVDA and TSM land just above their cited figures; MSFT is 3.4× its claim, because full history
includes multi-year uptrends the thesis's design window never saw. **This is a re-measurement on a
wider sample, not an out-of-sample test** (plan §2b): most history predates `DESIGN_THROUGH`, and the
15-signal post-cutoff split (median 51.5, p75 74.0) points the same way but is too thin for a verdict.

## 3. The excluded names' forward returns (`C-trend`) — predictions 4 and 5 both REFUTED

The thesis: the five excluded names (IREN, OKLO, APLD, BE, KORU) *"produced negative average 60-day
forward returns after the signal fired … the entries do not sustain here."* Measured on those five and
on `C-trend`'s nine kept names as a control:

| group | signals | pooled mean | pooled median |
|---|---:|---:|---:|
| **excluded (5)** | 44 | **+19.89%** | +5.82% |
| included / control (9) | 374 | +6.93% | +4.72% |

**The five excluded names' pooled mean 60-session forward return is not negative — it is +19.89%, and
every one of the five is individually positive.** The thesis's stated, measured reason for excluding
them does not reproduce in the store.

- **Prediction 4 (excluded mean negative) — REFUTED.** It is strongly positive.
- **Prediction 5 (the two groups within 10pp) — REFUTED**, and in the direction that makes the
  exclusion look worse rather than better: the excluded group's mean is **12.96pp higher** than the
  control's, not roughly equal. The names the card dropped for "not sustaining" outperformed the names
  it kept, on the card's own signal.

**The honest caveat, which the plan required and which matters here.** The five excluded names carry
only **44 signals** between them (OKLO just 2, IREN and APLD 8 each), against the control's 374, and
they are recent listings in a period that favoured speculative names. So this refutes the *stated
claim* — a negative average — without establishing the names are good. A mean of five thin, recent
samples is not a durable edge. **But that cuts against the thesis, not for it:** a claim resting on
"the measured data showed the entries do not sustain" cannot survive the measured data showing a large
positive average, whatever the sample size, and the small sample is if anything a second reason the
original exclusion was not the settled empirical call the thesis presents it as.

**This does not overturn round 26's "unaskable" finding** (plan §1). Round 26 asked whether a *card
holding these names* underperforms on the regime matrix, which their 2022 start dates make
unanswerable. This measured the 60-session forward-return statistic the thesis actually cites. Both
are true: the backtest is unaskable, and the cited statistic is refuted.

## 4. The scoreboard, closed

With this round, every quantitative claim on the four seated trading cards has been measured or
established as unmeasurable. Combining round 26 and round 27:

| card | claim | verdict |
|---|---|---|
| `A-rotation` | 3-of-9 cap binds often enough to matter | **no** (r26) |
| `A-rotation` | pairwise correlation ~0.589 | **holds, understated** (r27) |
| `B3` / `B-momentum` | uncapped beats capped variants | **direction holds** (r26) |
| `B3` / `B-momentum` | concentration matters | **no — one idea, two seats** (audit §9) |
| `B3` / `B-momentum` | move duration 3–4 weeks / past two months | **p75 holds, median 2.5× too low a claim** (r27) |
| `C-trend` | 49.4% win, 4.1× asymmetry, 118d/16d holds | **asymmetry holds, win rate 19.5%** (r26 / audit §9) |
| `C-trend` | the 12% stop is justified | **not supported** (r26) |
| `C-trend` | excluded names show negative forward returns | **refuted — +19.89%** (r27) |

**The pattern is not that the cards are wrong.** It is that a thesis is prose written before a live
record, and prose drifts from measurement in both directions: `A-rotation` and `B3`'s duration claim
**understate** what the data shows, `C-trend`'s exclusion claim asserts a number that is the wrong
sign, and most of the magnitudes that survive sit inside the noise floor anyway. What the
`falsification` field bought is that the next card's claims will be measurable by construction rather
than three rounds after the fact.

## 5. What this round cannot settle

- **Nothing about the cards' returns** — these are signal statistics.
- **§2b is a re-measurement, not an out-of-sample test**; no verdict from the post-cutoff split.
- **§3 does not overturn round 26's "unaskable"** — different question, both true.
- **Nothing is promotable, and nothing here demotes a card.**
