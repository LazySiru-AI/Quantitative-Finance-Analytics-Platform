# Round 31 — the macro line closes on a null, with one genuine near-miss

Run 2026-08-30 against `ROUND-31-PLAN.md` (`ec4cb2e`), committed before the measurement. **Not
investment advice.** A regime-conditional forward-return analysis; no card, no engine, no backtest,
nothing promotable.

---

## 1. The result

Three monthly inflation indices (`PCEPI` headline PCE, `PCEPILFE` core PCE, `CPILFESL` core CPI),
differenced to year-over-year inflation and release-date bound (reference + 45 days, mirroring
`macro_binding.RELEASE_LAG`), split by two causal states — `level` (YoY vs its trailing 60-month mean)
and `accel` (3-month change in YoY) — measured as forward-return spreads on SPY and QQQ across two
horizons. 24 cells, the round-28/29 block bootstrap, BH-corrected across all 24.

**Zero cells survive Benjamini-Hochberg** (smallest q = 0.139). **Zero survive the orthogonality
control.** By the pre-registered rule, **null — no card.** With this, **all seven macro series the desk
can read are now measured and empty**, and the macro line closes the way the cross-symbol line closed in
rounds 28-29.

**But the shape of this null is different from round 30's, and the difference is the finding.** Every
one of the 24 cells is **negative** — hot or accelerating inflation preceding weaker forward equity —
and the spreads are the largest in the macro line (up to −4.66% per quarter). The three lowest
uncorrected p-values, all on the `level` transform:

| cell | n | spread | raw p | q |
|---|---:|---:|---:|---:|
| `CPILFESL` level SPY h=63 | 130 | −3.66% | 0.009 | 0.139 |
| `CPILFESL` level SPY h=21 | 390 | −1.02% | 0.013 | 0.139 |
| `PCEPI` level SPY h=21 | 390 | −1.05% | 0.019 | 0.139 |

They do not clear q < 0.10, but they do not look like noise either. §2 below is the disciplined reason
this stays a null; §3 is why it is nonetheless the one macro result worth a dedicated follow-up.

## 2. The pre-registered rule holds, and I honor it

Nothing clears BH q < 0.10, so nothing reaches the residualization gate, so **no card, and the macro
line closes.** The bar was fixed before the run and it is not moved now. The reason the `level` cells
miss is instructive rather than damning: **five cells all show the same effect at p ≈ 0.01–0.06, and BH
correctly taxes the 24 looks** — at rank 5 the best achievable q is 0.029 × 24/5 = 0.139. A grid of
correlated cells each carrying a modest-but-real effect is exactly the configuration where BH holds the
whole family just under the bar. That is the correction working as designed, not a signal being
suppressed.

## 3. Why this is the one macro near-miss, not another round-30 null

Round 30's null was noise orthogonal to price. This one is not noise, on three independent checks — and
my own §2 caveat, that any survivor would be a single-episode artifact, **was wrong**:

- **Not one regime.** The `level` state (`CPILFESL`) fires across 2000-2001, 2005-2008, 2011-2019 and
  2021-2024 — 64 hot vs 66 cool rebalance dates, roughly balanced. **Dropping 2021-2023 entirely leaves
  the strongest spread essentially unchanged** (−3.83% vs −3.66% full). This is not the 2022 inflation
  spike in disguise; it is a broad, recurring relationship. My prediction that a survivor would be one
  episode is refuted.
- **Robust to the autocorrelation concern.** Lengthening the bootstrap block from 12 to 30 rebalance
  dates makes the strongest cell's p *smaller* (0.011 → 0.001), not larger — the exact opposite of
  round 28's overlap artifact, which collapsed from p=0.0002 to 0.63 once made independent. The low
  p-value is not an artifact of under-counted persistence.
- **Not a lookahead.** The 45-day release lag lands just after the true CPI/PCE release, so it is
  conservative; the effect would be marginally *stronger*, not weaker, with the true lag. YoY is causal
  by construction.

And it is **orthogonal to price** — residualizing on the target's 12-1 momentum barely moves any spread
(`CPILFESL` level SPY h=63: −3.66% → −3.17%). So unlike round 30, the orthogonality control here has a
real effect to leave standing.

**The honest caveat that keeps this proportionate:** this is a *known* macro regularity — high inflation
relative to its trend is associated with lower forward equity returns (valuation compression), textbook
rather than proprietary. Finding it validates that the measurement works; it is not a discovery. And the
effect is "lower positive returns," not negative: hot-regime forward SPY is +0.55% per quarter vs cool
+4.21% — a tradeable tilt only if the avoided periods underperform the cash rate that prevails in a
high-inflation environment, which is a card-design question, not something this round establishes.

## 4. Predictions: 1 held, 1 partial, 2 refuted

1. **`level` negative on QQQ, more negative than SPY — PARTIAL.** Negative on QQQ in all 6 cells, and
   more negative than SPY at h=21 (3/3), but *less* negative than SPY at h=63 for the two PCE measures.
   The growth-more-sensitive ordering holds monthly, reverses quarterly for PCE.
2. **`accel` carries less than `level` — HELD.** Mean |spread| level 0.0213 vs accel 0.0116. The
   persistent regime beats the 3-month change, cleanly.
3. **Core beats headline `PCEPI` — REFUTED.** `CPILFESL` (core CPI) is strongest (0.0195), but
   `PCEPILFE` (core PCE) is *weakest* (0.0134), below headline `PCEPI` (0.0165). Core-vs-headline does
   not order the strength; the CPI-vs-PCE construction matters more than the core distinction.
4. **Net orthogonal survivors = 0 — HELD.** The pre-registered null.

## 5. What this closes, and the one thread it leaves open

**The macro line is closed.** Seven series, every shape asked: the curve as gate/size/ROC (null,
rounds 22/23/25); rate level, oil, breakeven as statistics (null, round 30); the three inflation indices
as statistics (null, this round). No `macro()` card is justified by measured edge on the desk's
tradeable history.

**The one thread worth a dedicated round** is the inflation-`level` effect on SPY. It is the only macro
result that survives every stress test the plan's §5 demanded of a survivor, and it misses the bar only
by paying a 24-cell multiple-testing tax it would not pay alone. The disciplined next step — not taken
here, because it must be pre-registered on its own — is a **single-hypothesis round**: one series, one
transform, one target, one horizon, fixed in advance, with its own null and its own out-of-sample split,
so p ≈ 0.01–0.02 stands or falls without the grid tax. If it holds there, it is a card candidate (and
would need the round-23/25 substitution trick to express); if it folds, the macro line closes on this
too. This is round 29's lesson inverted: there a survivor decomposed into a risk premium and I walked
away; here a near-miss passed every robustness check, and the honest move is to name it precisely rather
than promote or dismiss it.

## 6. What this round cannot settle (plan §6)

- The 45-day lag is the engine's placeholder, not a real BLS/BEA calendar (conservative, so it does not
  inflate the effect).
- The **revision leak is not closed** — YoY on a pinned, possibly-revised index is not strict
  point-in-time; the direction of any bias is unknown but revisions are small relative to a 3-4% spread.
- Binary sign-split; two transforms and two fixed windows; equity-index targets, not the seated names.
- **Above all §2's ghost:** even though the effect is broad, 33 years still holds a limited number of
  independent inflation cycles. The dedicated follow-up must treat that as its central power question.
- Return statistic only; **nothing here is a card, and nothing is promotable.**
