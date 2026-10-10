# Round 29 — the fair test found a survivor, and it is the beta premium

Run 2026-08-30 against `ROUND-29-PLAN.md` (`471a7f9`), committed before the measurement. **Not
investment advice.** A rank-statistic analysis; no card, no engine, no backtest, nothing promotable.

---

## 1. The result, and why it is not a licence to build

Round 28 found no cross-sectional edge on the concentrated seated universes and named the fair test: a
diversified, low-correlation universe (mean pairwise correlation 0.393 vs the semis' 0.6–0.8). This ran
the identical measurement — imported unchanged from `round28.py`, non-overlapping windows from the
start — on ten single names, one per GICS sector, from 1992.

**Two cells survive Benjamini-Hochberg, both `vol_60`:** h=21 IC +0.057 (q=0.030) and h=63 IC +0.075
(q=0.052). After twenty-eight nulls, these are **the first genuine cross-sectional survivors in the
programme** — and, unlike round 28's, they are not artifacts: the overlap defect is fixed in advance,
the h=21 cell has 410 independent cross-sections, and the effect is robust (below).

**But the sign is positive, and that is the whole story.** High trailing volatility predicts *high*
forward relative return — the opposite of the low-volatility anomaly. Over a bull-heavy 34 years, that
is the signature of the **beta premium**: high-vol names amplify the market. The decisive test —
splitting cross-sections by market direction:

| horizon | UP-market IC | DOWN-market IC |
|---|---:|---:|
| h=21 | **+0.167** (n=263) | **−0.140** (n=147) |
| h=63 | **+0.144** (n=104) | **−0.148** (n=32) |

**The effect flips sign with the market, symmetrically.** High-vol names win when the market rises and
lose when it falls, exactly as beta does. The full-sample +0.057 is arithmetically just the net:
0.64 × (+0.167) + 0.36 × (−0.140) ≈ +0.057, the up-market IC weighted by the fraction of up-months.
**There is essentially no residual cross-sectional volatility alpha** — the survivor decomposes
completely into directional market exposure.

## 2. It is robust, which is what makes the decomposition worth trusting

The h=21 survivor was stress-tested the same way round 28's false survivor was, and it passed every
test round 28's failed:

| test | result |
|---|---|
| bootstrap seed 28 → 99 | p 0.0055 → 0.0025 (robust) |
| sub-period 1992–2009 / 2009–2026 | IC +0.047 / +0.069 — **same sign both eras** |
| drop-one jackknife (all 10 names) | p 0.001–0.021 — **survives removing every name, MSFT included** |

So the signal is real and stable — it is genuinely there. The stress tests confirm it is a *durable*
beta premium, not that it is an alpha. (The h=63 survivor is weaker: its 1992–2009 half is
insignificant, p=0.28, and it concentrates in 2009–2026. The h=21 result is the solid one.)

## 3. The decision, per the pre-registered rule (§5)

The rule said a surviving cell justifies the engine change for that signal. **It does not, and the
reason is what §2 of round 28 called a licence to build being distinct from a strategy.** The surviving
signal is the beta premium, and the beta premium is:

- **not an alpha** — it is directional market exposure, positive in aggregate only because the market
  rose more than it fell;
- **capturable without any cross-symbol engine** — tilting toward high-vol names is a high-beta bet you
  can take with a single high-beta ETF or more market exposure, no cross-sectional ranking machinery
  required;
- **risk the rank IC cannot see** — de-meaning hides that a high-vol tilt is severely punished in
  crashes (the −0.14 down-market IC), so the "edge" is leverage, not skill.

**So the honest verdict is: cross-sectional rank does carry information on a diversified universe — but
the only signal that survives is the beta premium, which does not justify building cross-symbol
machinery, because what it captures is available more cheaply and is a risk exposure rather than an
edge.** The low-volatility anomaly, the signal that *would* justify the build, has the wrong sign here:
on this narrow universe over this period the beta premium dominates it.

## 4. Predictions: 2 held; 1, 3, 4 refuted — and the refutations are informative

1. **Mean |IC| higher than round 28 — REFUTED, informatively.** This round's mean |IC| is **0.0227**,
   *below* round 28's 0.042–0.052. Diversification did not add rankable structure; it *removed* the
   spurious momentum-ish ICs that co-movement produced on the tight universes, leaving only the one
   real (beta) effect. The intuition that more dispersion means more to rank was wrong — more
   dispersion meant less spurious signal.
2. **`vol_60` strongest — HELD.** 0.0660, far above the next (reversal 0.0184). The one signal carrying
   anything is the one that proxies beta.
3. **`reversal_1m` negative at h=21 — REFUTED.** +0.0073, indistinguishable from zero. No short-term
   reversal on these names.
4. **Zero cells survive — REFUTED, and genuinely so.** Two survive, they are real, and this is the
   round the plan said a survivor was most plausible. The refutation stands — with the interpretation
   that the survivor is a risk premium, not an edge.

## 5. What this closes, and what it leaves

**The cross-symbol line closes for the purpose it was opened.** Across rounds 28 and 29, cross-sectional
rank carries no *alpha* on either the concentrated seated universes or a diversified one — the only
diversified survivor is the beta premium, which needs no cross-symbol engine to harvest. **The engine
change §3a describes is not justified by measured edge.** Recommendation 11's non-price inputs are the
remaining frontier, and each is a cheaper bet than building machinery for a class these two rounds
measured as containing only a known risk premium.

## 6. What this round cannot settle

- **Breadth, not correlation** (plan §6). Ten names is narrow; the low-vol anomaly is measured on
  hundreds of names, where the beta premium can be diversified away and the residual alpha isolated.
  A genuinely broad universe (hundreds of names with long history) could still carry low-vol alpha this
  narrow set cannot show, and remains unrun — limited by the store.
- **One representative per sector**, chosen by history length.
- **Rank IC, not return; nothing promotable; nothing here is a card.**
