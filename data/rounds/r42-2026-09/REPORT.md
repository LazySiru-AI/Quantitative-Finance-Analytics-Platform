# Round 42 — report: neither confirmation term pays for itself; family A's own ordering prediction was refuted

Run 2026-09-09, eight main windows, 5 cards (2 families), 40 runs, zero `FAILED` lines. Pre-registration:
`strategy-program/ROUND-42-PLAN.md` (2026-09-09). Computed tables: `ANALYSIS.md`, from
`strategy-program/tools/round42_report.py`, mirrored in `analysis.json`. Scorecard: `scorecard.json`
(`score.py --pin-store`). `13f-legal` does not apply to this round and did not run (0/0, as planned).
All cards `purpose = trading`.

**Not investment advice.** Price-only bars, no dividends, SPY benchmark, a synthetic paper book. Family
A tests Creator E (`creator-e`)'s wick-rejection/full-body-confirmation claim, forced off his
native intraday timeframe into this programme's daily-bar constraint. Family B tests Creator C
(`creator-c`)'s 0.25-range breakout-confirmation claim, its exit-timing and profit-target halves
untestable in this DSL. Both corpora are model-summarised from partly Korean-language video transcripts
with `published = null` — a provenance caveat, not a dating tool (§6). The hypotheses came from the
persona discussion (`strategy-program/PERSONA-DISCUSSION-2026-09-09.md` §3); no influencer is endorsed.

**Ordering note.** The run began minutes before the field-freezing commit `628b5e3` landed; a pre-commit
lint error in another round's in-progress file blocked the hook at the moment the run started. This is
recorded as an ordering fact, not hidden: `tests/test_round42_field.py` proves the on-disk cards under
test equal `round42.build()`'s output byte-for-byte, so the run executed the frozen field regardless of
when the commit itself landed. The run itself used a copy of `run_round.sh` with a stricter
process-liveness guard than the original (the original tripped on two orphaned bash shells from another
session whose command text happened to mention a tournament module; no tournament python process was
actually alive) — no other change to the runner.

---

## 1. Result — null by the decision rule

| family | arm | arm median | control median | arm − control | windows arm>ctrl | clears 21.2pp floor? |
|---|---|---|---|---|---|---|
| reclaim (Creator E) | `r42-reclaim-wick` | +1.85pp | +3.55pp | **−1.70pp** | 4/8 | no |
| reclaim (Creator E) | `r42-reclaim-wick-body` | −2.33pp | +3.55pp | **−5.87pp** | 3/8 | no |
| breakout (Creator C) | `r42-breakout-q25` | +0.11pp | −0.89pp | **+1.00pp** | 3/8 | no |

BH over all 5 cells: minimum q **1.0000** against either family's control as reference (m=5 either
way; the per-family arm-minus-own-control contrasts above are what the decision rule actually reads).

**Decision rule (plan §5), applied:** an arm "earns" something only if arm-minus-own-control median
adjusted excess exceeds the 21.2pp floor **and** survives BH q<0.10. None does; the largest margin in
either direction is −5.87pp, a quarter of the floor. **The null is the result: neither an
intrabar-structure conjunct on a level reclaim, nor a range-confirmation threshold on a breakout, pays
for itself on this book.**

## 2. What the numbers do say, short of a finding

1. **Family A's own trade-count ordering prediction was REFUTED.** The plan predicted
   `wick-body < wick < control` (each added structural term filters further). Measured:
   `r42-reclaim-control` 179 trades, `r42-reclaim-wick` **218** trades, `r42-reclaim-wick-body` 140
   trades — `wick` fires *more* than the control, not fewer. The plan's own §5 honesty note explains
   why: `wick`'s entry (`low < swing_low(20) and close > swing_low(20)`) is not the control's condition
   plus a conjunct — it is a *differently-shaped* condition (a pierce-and-close-back-above) against the
   same level, not a subset of `close crosses_above swing_low(20)`. The reachability table flagged this
   before the round ran (1,245 vs 1,651 fires); the backtest trade counts (179 vs 218) confirm it holds
   after exits and brackets are applied. The ordering that *is* confirmed — `wick-body` (140) < `wick`
   (218), the former being the latter plus strictly more — was never in question; the refuted half was
   the raw comparison against the control.
2. **Family B's trade-count prediction HELD.** `r42-breakout-q25` took 123 trades against
   `r42-breakout-control`'s 145 — the 0.25-range confirmation did filter as predicted, entering later
   and less often. It did not translate into a return edge: the arm's median (+0.11pp) sits only
   +1.00pp above its control's (−0.89pp), both effectively flat and both well inside the floor.
3. **Exposure is asymmetric between the two families, and within-family comparisons are the only fair
   ones.** Reclaim cells run 0.34–0.51 mean exposure; breakout cells run 0.26–0.28. `analysis.json`'s
   own contrasts are all arm-minus-own-family-control for exactly this reason — nothing here compares a
   reclaim cell to a breakout cell, and this report does not either.
4. **No single window carries the family.** `recent` dominates the breakout family's raw numbers
   (control +67.13pp, q25 +41.72pp — by far each cell's largest value) and `covid` dominates the reclaim
   family (control +30.64pp, wick +43.77pp, wick-body +19.81pp). Both families also carry their largest
   *negative* prints in `bear-2022` (reclaim, down to −26.05pp) and `gfc` (breakout, down to −26.05pp).
   A single-window read would flip the sign of either family depending on which window was picked; the
   median across all eight is the only number this report treats as safe to quote, per `PROTOCOL.md`
   §4's ban on ranking on one window.
5. **Sign-flip counts are close to a coin flip.** `wick` beats its control in 4/8 windows (p=0.5547),
   `wick-body` in 3/8 (p=0.3906), `q25` in 3/8 (p=0.4766) — none distinguishable from chance, consistent
   with §4's caution that q-values here are not evidence of skill.

## 3. Predictions vs outcomes (plan §5)

| # | prediction | outcome |
|---|---|---|
| 1 | No arm beats its own control by >21.2pp with BH q<0.10 | **HELD** (null) — max margin −5.87pp |
| 2 | Family A: `wick-body` < `wick` < control (trade count) | **REFUTED** — 140 < 218, but 218 > 179 (control); plan's own honesty note anticipated this half |
| 3 | Family B: `q25` fewer trades than control, later entries | **HELD** — 123 < 145 |
| 4 | Creator E's failure regime (`chop-2015`, `chop-2011`) hurts control and both treatments | see §4 below |
| 5 | Creator C's failure regime (gaps; slow chop `chop-2015`/`chop-2011`) hurts control and q25 | see §4 below |
| 6 | Sign flips by regime; only the 8-window median is safe to read | **HELD** — see §2.4-5 |
| 7 | Degenerate-outcome guard: low fire rate could cause an unranked window without meaning "did not help" | **N/A** — all 5 cells ran 8/8 windows, none unranked (`scorecard.json`) |

## 4. Scoring each persona's own pre-registered failure regime

**Creator E**, on a forced daily-bar version of his method: "consolidation and range-bound sideways
movement, where support and resistance blur" is his named failure regime (discussion §3, "trading"
answer). Read against the per-window table (`ANALYSIS.md`): `chop-2015` gives control +15.06pp, wick
+1.81pp, wick-body −8.01pp; `chop-2011` gives control +6.20pp, wick +3.43pp, wick-body −2.53pp. The
prediction that both treatments underperform the control there partially holds — `wick` and `wick-body`
are both below the control in both chop windows — but the control itself stayed positive in both, not
the "blurred, noisy" collapse his claim implies; `bear-2022`, not either chop window, is where the whole
family bottoms out (control −26.05pp, wick −22.85pp, wick-body −25.75pp).

**Creator C**, on the expressible half of his claim only (the timing clock and profit target could
not be built in this DSL — plan §1): his named failure regimes are "gapping markets where 0.25 is
crossed in a single overnight gap then reverses" and "sideways choppy markets where 0.25 takes 8+ days
to reach" (discussion §3, "trading" answer). This programme has no window labelled by gap frequency, so
only the slow-chop half is scored: `chop-2015` gives control +8.78pp vs q25 +2.85pp, `chop-2011` gives
control −4.93pp vs q25 −12.91pp. The signal-arrives-too-late story holds in `chop-2011` (q25 noticeably
worse than control) but inverts in `chop-2015` (q25 still positive, just smaller). As with the
untested-clock caveat in plan §1, a null on `q25`'s entry condition says nothing about whether his
actual exit and timing rules — inexpressible here — would have changed either reading.

## 5. Disposition

- **Nothing promoted.** `PROTOCOL.md`'s r21 amendment: §6's promotion rule does not apply to the
  `trading` purpose, and this round was pre-registered as a measurement study with no replacement gate
  for either family. No cell here moves to `candidates/` or `base/`; unlike round 40, no directed
  promotion was made for this round either — both families returned margins inside the floor by a
  larger factor than round 40's sole positive cell did.
- **Nothing seated, unseated, or otherwise changed on the trading paper book.** `AGENT_IDS` is
  untouched by this round.
- Files: `cards/`, `results/<window>/runs/`, `scorecard.json`, `ANALYSIS.md`, `analysis.json`,
  `score.log`, `run.log`.

## 6. What this round cannot settle

- **Neither treatment's exact expression was stated by its persona in threshold form**, except
  Creator C's own 0.25. Creator E never wrote `low < swing_low(20)` or `0.5 * (high - low)` — those are
  this programme's translation of his prose, exactly as round 40 noted for its own arms.
- **It is one universe, and not a survivorship-free one** — the same 12-name large-cap tech/
  semiconductor pool round 40 used, mechanically defined by `_TAXABLE_GROWTH`, not chosen for this
  round.
- **Both persona corpora are model-summarised from partly Korean-language transcripts** with
  `published = null` on every note — hindsight is unbounded; this round cannot bound which windows
  were genuinely unseen to either speaker.
- **The inexpressible halves of both claims are untested by construction, not refuted.** Creator E's actual
  intraday execution discipline cannot be expressed on daily bars at all — he said so before offering
  the daily-bar fallback tested here. Creator C's 1.0×-range profit target and "within 5 trading
  days" clock have no DSL primitive; a null on `q25`'s entry says nothing about his exit and timing
  rules.
- **It tests one entry-side operationalisation per persona, not "wick rejection" or "breakout quality"
  in general.** A null here refutes these two expressions on this book, not the claims in full
  generality.
- **It is price-only and dividend-free**, like every backtest in this programme.
