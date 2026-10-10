# Round 26 — the seated cards' own falsification conditions, run

Run 2026-08-30 against `ROUND-26-PLAN.md`, committed at `19155dd` before any card was authored.
**Not investment advice.** Nothing here is promotable, and nothing here demotes a card either.

---

## 1. The instrument check nobody asked for, and it passed

All three controls were re-run rather than quoted from round 24, so that every figure came from one
code version. **All three reproduce round 24's committed medians exactly:**

| control | round 24 | round 26 |
|---|---:|---:|
| `B3-concentrated` | +13.89% | **+13.89%** |
| `C-trend` | +5.03% | **+5.03%** |
| `A-rotation` | −7.16% | **−7.16%** |

Six windows carried the full field; `chop-2011` lost five of seven cards to META's 2012 first bar and
`gfc` lost all of them to AVGO's 2009 one — the same universe-history wall round 24 documented, not a
new failure. Six eligible windows clears `R2_MATRIX`'s five-window gate. **No `IOException` in any
result**, so no card was lost to store contention (D3).

## 2. The field

| card | median adj. excess | worst | hit rate | trades |
|---|---:|---:|---:|---:|
| `r26-b3-base` *(control)* | **+13.89%** | −7.75% | 66.7% | 56 |
| `r26-b3-fastexit` | +9.63% | −6.61% | 66.7% | 78 |
| `r26-ctrend-stop08` | +5.75% | −5.95% | 50.0% | 59 |
| `r26-ctrend-base` *(control)* | +5.03% | −7.26% | 50.0% | 59 |
| `r26-b3-tp20` | +3.01% | −7.75% | 50.0% | 72 |
| `r26-arot-rankby` | +0.43% | −27.10% | 57.1% | 183 |
| `r26-arot-base` *(control)* | −7.16% | −27.41% | 42.9% | 189 |

**Every margin in this table is inside the 21.2-point floor.** The largest gap between any arm and its
own control is 10.88pp. So the *directions* below are the findings; the *magnitudes* decide nothing,
and no card is promoted or demoted on any of it.

## 3. Predictions: one held, one held, three refuted

### Prediction 3 — HELD. Both capped `B3` arms cost return.

`r26-b3-tp20` +3.01% and `r26-b3-fastexit` +9.63%, against the control's +13.89%. **This is the first
time the thesis's central claim has been tested at all**, and its direction survives: capping gains
and exiting fast both reduce the result.

### Prediction 4 — REFUTED, and this is the surprise: the "roughly triple" magnitude *is* reproduced

The prediction was that the direction might hold while the size did not, falsified if either capped
arm fell below one third of the control. **`r26-b3-tp20` did: 3.01% against a one-third threshold of
4.63%.** The uncapped control produced **4.6×** the take-profit arm's median — more than the thesis's
"roughly triple", on a matrix its author never ran.

The fast-exit arm is a different story at 1.44×, so the claim holds for one named variant and not the
other. And the caveat that governs both: 10.88pp is inside the floor.

### Prediction 5 — REFUTED. The tighter stop is *better*.

`r26-ctrend-stop08` +5.75% against `r26-ctrend-base` +5.03%. The thesis justifies widening the stop
from 8% to 12% on the grounds that it cut stop-outs without moving mean trade return. On eight regime
windows the 8% stop is not worse — it is marginally better, on a shallower worst window (−5.95% vs
−7.26%) and with the same trade count.

**So the stop width is a free parameter**, which is what the clause predicted an unfalsifiable
parameter would look like. 0.72pp is deep inside the floor: the honest statement is not "8% is better"
but "this card's record does not depend on the stop width its thesis argues for."

### Prediction 1 — REFUTED. Imposing a ranking does not move `A-rotation` past the floor.

`r26-arot-rankby` +0.43% against `r26-arot-base` −7.16%: better by 7.59pp, inside the floor. The
clause's second horn — that a card filling alphabetically might owe a material part of its record to
alphabetical order — is **not** supported here.

### Prediction 2 — HELD, and it explains prediction 1

| window | median names qualifying | ≥4 | ≥6 |
|---|---:|---:|---:|
| *thesis, design window* | *4.0* | *50.6%* | *21.3%* |
| `q4-2018` | **0.0** | 10.9% | 0.0% |
| `covid` | 4.0 | 50.5% | 34.4% |
| `bear-2022` | **0.0** | 15.3% | 9.2% |
| `chop-2015` | **2.0** | 39.0% | 23.6% |
| `chop-2011` | **2.0** | 36.5% | 24.2% |
| `bull-2024` | **3.0** | 46.4% | 30.8% |
| `recent` | 4.0 | 59.4% | 33.3% |
| `gfc` | **1.0** | 16.3% | 7.9% |

Median below 4 in **6 of 8** windows; `≥4` on fewer than 50.6% of sessions in **7 of 8**. In three
windows the median is 0 or 1, meaning **the 3-of-9 cap essentially never binds there.**

**The two `A-rotation` predictions explain each other.** The thesis defends its cap by arguing that
breadth "genuinely varies session to session… so the cap binds and actually forces a choice often
enough to matter". Out of sample it usually does not. And a cap that rarely binds is a cap whose fill
order rarely matters — which is exactly why imposing a ranking moved nothing past the floor.

**So the card is closer to "hold everything that qualifies" than to a rotation**, in six of eight
regimes, and the thesis's own defence of the cap does not survive its design window. Its honesty about
the alphabetical tiebreak turns out to have been a smaller problem than it feared, for a reason it did
not anticipate.

## 4. What this round did not settle

- **`C-trend`'s universe-exclusion claim is unaskable on this matrix**, established in the plan §2
  before running: the five excluded names co-exist only from 2022-04-12, covering two of the eight
  windows against a five-window minimum. That is round 21's category, not a null.
- **Every margin is inside the noise floor.** Five directional findings, zero measurable magnitudes.
  A reader who takes "the take-profit arm is 4.6× worse" as a number rather than a direction has
  drawn more from this round than it can support.
- **One matrix, one economy.** Round 4's lesson stands.
- **No promotion or demotion.** The trading purpose has no promotion rule, and nothing here changes a
  seated card's committed record.

## 5. What it did settle

Three of the four seated trading cards have now had a thesis claim measured out of sample for the
first time:

| card | claim | verdict |
|---|---|---|
| `B3-concentrated` / `B-momentum` | uncapped beats capped variants | **direction holds**, magnitude inside the floor |
| `B3-concentrated` vs `B-momentum` | concentration matters | **no** — 1.74pp, one idea holding two seats (audit §9) |
| `C-trend` | the 12% stop is justified | **not supported** — the 8% stop is marginally better |
| `C-trend` | right less than half the time, still profitable | **right one fifth of the time** (audit §9) |
| `A-rotation` | the 3-of-9 cap binds often enough to matter | **no** — median breadth below 4 in 6 of 8 windows |

The pattern across all of them is the same one this programme's §1 has been recording for twenty-five
rounds: **the mechanisms are real and the magnitudes are inside the noise.** What is new is that the
claims being tested are the cards' own.
