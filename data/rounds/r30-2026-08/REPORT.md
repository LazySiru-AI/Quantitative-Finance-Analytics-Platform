# Round 30 — the daily untouched macro series carry no orthogonal forward-return information

Run 2026-08-30 against `ROUND-30-PLAN.md` (`7547ee2`), committed before the measurement. **Not
investment advice.** A regime-conditional forward-return analysis; no card, no engine, no backtest,
nothing promotable.

---

## 1. The result

Three daily untouched FRED series (`DGS10` rate level, `DCOILWTICO` oil, `T10YIE` breakeven inflation)
× two causal state transforms (`level` vs trailing-252 mean, `roc` = 20-session change) × two targets
(SPY, QQQ) × two horizons (21, 63 sessions) = **24 cells.** Each cell splits history by the macro state
and measures the forward-return spread between states, tested with the round-28/29 block bootstrap and
BH-corrected across all 24.

**Zero cells survive Benjamini-Hochberg** (smallest q = 0.288). **Zero survive the orthogonality
control.** Predicton 4 — the pre-registered null — holds. State splits are healthy (every cell 40-60%
each side; no degenerate join), and raw p-values span 0.018-0.942 with spreads on both signs, so the
measurement discriminates — it simply found nothing.

The three lowest *uncorrected* p-values, all dead after correction:

| cell | n | spread | raw p | q |
|---|---:|---:|---:|---:|
| `DCOILWTICO` level SPY h=63 | 130 | -2.65% | 0.018 | 0.288 |
| `DCOILWTICO` level SPY h=21 | 390 | -0.78% | 0.029 | 0.288 |
| `T10YIE` level QQQ h=63 | 89 | -4.29% | 0.036 | 0.288 |

Three marginal hits out of twenty-four is what noise looks like under BH — the expected count at
p<0.05 is 24×0.05 ≈ 1.2, and none clears the correction.

## 2. Predictions: 1 held, 1 partial, 2 refuted — and the refutations are the finding

1. **`DGS10` roc (rising rates) more negative on QQQ than SPY — PARTIAL.** Held at the quarterly
   horizon (QQQ h=63 -2.49% vs SPY h=63 +1.14% — right sign, right ordering, growth punished more) but
   reversed at h=21 (SPY -0.70% more negative than QQQ -0.23%). The economically-expected
   rate-hurts-growth sign appears at 63 sessions, but well inside noise (p=0.289).
2. **`DGS10` spreads shrink after price-residualization — REFUTED, and this is the informative one.**
   The residualized spreads are **nearly identical to raw** (QQQ h=63 -2.49% -> -2.42%; SPY h=21
   -0.70% -> -0.75%). The macro state is **not** trailing 12-1 momentum in disguise — it is orthogonal
   to price momentum. My premise was that any raw spread would be mostly the price signal wearing a
   macro mask; it is not. The catch is decisive: the information that is orthogonal to price is *also
   orthogonal to future returns*. The control was built to strip a hidden price signal and found none
   to strip — not because the macro signal is strong, but because it is independent of both price and
   outcome. This closes the "the control killed a real signal" objection before it can be raised.
3. **`DCOILWTICO` has the smallest mean |spread| — REFUTED.** `DGS10` (rates) is the flattest series
   (mean |spread| 0.0073), oil is in the middle (0.0096), `T10YIE` (breakeven) is the largest (0.0110).
   Rates, not oil, carried the least. Oil's marginal hits are all on the broad market (SPY level), not
   the sector-mixed non-result I expected.
4. **Net orthogonal survivors = 0 — HELD.** The pre-registered null.

## 3. The decision, per the pre-registered rule (§5)

Nothing clears BH, so nothing reaches the residualization gate. **Per the rule, no card.** The three
daily, directly-expressible untouched series carry no forward-return information for equity indices that
survives multiple-testing correction — and the one control that could have rescued a marginal signal
(price-orthogonality) showed the signals are noise independent of price, not price in disguise.

This extends the curve result cleanly. `T10Y2Y` was null 3× as a card (rounds 22/23/25); now the rate
*level*, oil, and breakeven inflation are null as pure statistics, before any card. **Four of the seven
macro series the desk can read are now measured and empty.**

## 4. What this leaves — and the one honest thread

The macro frontier narrows to the three **monthly inflation indices** (`PCEPI`, `PCEPILFE`, `CPILFESL`),
untested here because a level index is non-stationary and must be differenced through the round-23/25
in-process pin swap — a harder and lower-prior follow-up.

There is a thin thread worth stating precisely, because pre-registration lets me: **the two least-dead
cells are both `level` transforms carrying a valuation-drag sign** — expensive oil (SPY) and high
inflation expectations (QQQ) associated with *lower* quarterly-forward equity returns. That is the shape
a slow inflation/valuation headwind would take, and it is exactly what the monthly core-inflation
indices measure directly. It is not a signal — it dies under BH and I am not promoting it — but it is
the reason the inflation-index follow-up is the right next branch rather than a dead end. If that round
is also null, the macro line closes the way the cross-symbol line did.

## 5. What this round cannot settle (plan §6)

- Binary sign-split discards magnitude; only two transforms and two horizons.
- Equity-index targets only — QQQ stands in as the growth proxy; the seated single names were not the
  target.
- The orthogonality control is one axis (the target's own 12-1 momentum), not all price information.
- Daily series only. The monthly inflation indices are untested.
- Return statistic only; **nothing here is a card, and nothing is promotable.**
