# Round 31 — the monthly inflation indices, the last untested macro series

Pre-registered 2026-08-30, before any measurement in this round exists. **Not investment advice.**

Round 30 measured the three daily untouched macro series (rate level, oil, breakeven) and found nothing
that survives correction — but left one honest thread: the two least-dead cells were both `level`
transforms carrying a quarterly *valuation-drag* sign (expensive oil / high inflation expectations ->
weaker forward equity). This round tests that thread on the series that measure inflation directly, the
**three monthly indices** — `PCEPI`, `PCEPILFE`, `CPILFESL` — the last of the seven macro series the
desk can read that have never been touched.

---

## 1. Why this is the last macro round, and why it comes before any card

Of the seven FRED series reachable through `macro()`: the curve was null 3× as a card (rounds 22/23/25);
the rate level, oil and breakeven were null as statistics (round 30). That leaves the three inflation
indices. This round closes the macro line by measuring them the same way round 30 did — a
regime-conditional forward-return spread on SPY and QQQ, as a pure statistic, before any card.

**These three need differencing, and that is the round-23/25 substitution trick's original purpose.** A
price *index* (`CPILFESL` = 336) is non-stationary and rises monotonically; its level carries no state.
The economically meaningful quantity is the **inflation rate** derived from it. For a card, the engine
would read a substituted series (the round-23/25 `active_pin` swap). For a *measurement* the swap is
unnecessary — this round differences the index directly in numpy, exactly as round 30 computed macro
states directly. The substitution trick only becomes relevant if a card is later justified.

## 2. The load-bearing caveat, stated before any number

**Inflation regimes are extremely persistent, and over the SPY era there was essentially one.** Core
inflation was low and stable from 1993 through 2020, with one large regime change (the 2021-2023 spike)
and its unwind. So a "high vs low inflation regime" split over this sample is dominated by a single
episode: the test is close to asking *"did equities do worse in 2022?"* — to which the answer is yes,
but from one observation, not a repeatable edge.

This cuts precisely. **A null here does not prove inflation is irrelevant to equities in general** — it
says the desk's tradeable history contains too few independent inflation regimes to establish it as a
signal. And a *survivor* would be **suspect for the same reason**: driven by one episode, it would be
the inflation analogue of round 29's beta premium — a real historical fact, not a durable edge. The
block bootstrap (block >= horizon) partly accounts for the autocorrelation, but it cannot manufacture
regime changes the sample does not contain. This is the inflation counterpart of round 28's
"concentrated universe is the worst case" honesty.

## 3. The measurement

### 3a. Release-date binding (the causal core)

Monthly inflation for reference month M is **published ~six weeks later** — July's core CPI carries the
date `2026-07-01` and is released in mid-August. `app.rules.macro_binding` binds these series by
**release date = reference_date + RELEASE_LAG**, and `RELEASE_LAG` is **45 days** for all three indices
(the module refuses to default to zero — "a zero lag reads a value on the day it refers to rather than
the day it was published"). This round applies the **identical 45-day shift**, so a state is usable only
from `reference_date + 45d` and carries forward until the next release — mirroring exactly what a card
would see. As-of joining on the reference date would be a six-week lookahead and is the one bug this
round is built to avoid.

### 3b. The stationary inflation series and two causal state transforms

From each index, derive **year-over-year inflation** at reference month m: `YoY(m) = index(m)/index(m-12) - 1`.
Both terms are on or before m, so YoY is knowable at m's release. On the YoY series, two states, fixed
before any result (the monthly counterparts of round 30's `level` and `roc`):

| transform | definition | state |
|---|---|---|
| `level` | `sign( YoY(m) - mean(YoY over trailing 60 months) )` | +1 inflation hot vs its norm / -1 cool |
| `accel` | `sign( YoY(m) - YoY(m-3) )` | +1 accelerating / -1 decelerating |

The 60-month regime window and 3-month acceleration window are fixed here, before any return is looked
at; no other window is evaluated against an outcome. Every state is stamped with its eligibility date
(`reference_date + 45d`) and as-of joined to the equity rebalance date.

### 3c. Targets, horizons, grid, statistic

Identical to round 30, for direct comparability: targets **SPY** and **QQQ**; horizons **21 and 63
sessions**, rebalance dates **non-overlapping at the horizon** (`cal[::h]`); 3 series × 2 transforms ×
2 targets × 2 horizons = **24 cells**. Per cell: **spread** = `mean(fwd | +1) - mean(fwd | -1)`;
significance via the round-28/29 block bootstrap on `g(d) = state(d)·(fwd(d) - grand_mean)`;
**BH-corrected across all 24**, survivor threshold **q < 0.10**.

### 3d. The orthogonality control (round 30 §2), on every cell

Residualize forward return on the target's trailing 12-1 momentum (terciles), recompute spread and
bootstrap p on the residual. Reported raw and residualized side by side. Same crux: a macro state that
only works because it proxies price momentum is not a new input.

## 4. Predictions (falsifiable, fixed before the run)

1. **The `level` transform (hot inflation) gives a negative spread on QQQ, more negative than on SPY** —
   round 30's valuation-drag thread, on the direct measure. *Refuted if* the QQQ level spread is
   non-negative or not more negative than SPY's.
2. **`accel` carries less than `level`** (|spread| smaller) — a persistent regime effect should beat a
   3-month change. *Refuted if* mean |accel spread| > mean |level spread|.
3. **The core measures (`PCEPILFE`, `CPILFESL`) carry more sign than headline `PCEPI`** — core is what
   markets watch; headline is noisier through energy. *Refuted if* `PCEPI` is the strongest series.
4. **Net survivors — q < 0.10 AND sign + >= half spread after residualization — is 0.** Thirty rounds of
   nulls, T10YIE (daily inflation expectations) already null in round 30, and §2's single-regime
   limitation. *Refuted by* any such surviving cell.

## 5. Decision rule (pre-registered)

- A cell clearing **BH q < 0.10 AND keeping sign + >= half its spread after residualization** is an
  inflation signal with orthogonal forward-return content. The response is to **pre-register a card
  round** — which here genuinely needs the round-23/25 substitution trick, since the engine cannot
  difference an index — and to stress-test it against §2 first (is it one episode?), exactly as round 29
  split its survivor by market direction.
- A cell clearing BH but collapsing under residualization is a price signal wearing an inflation mask —
  **no card.**
- **Nothing surviving** -> all seven macro series are now measured and empty, and **the macro line
  closes** the way the cross-symbol line closed in rounds 28-29. The frontier moves off macro entirely,
  to the collected-but-unreachable feeds (Fear & Greed, the event calendar, the unconsumed 13F engine).

## 6. Determinism and honesty about scope

- `SEED = 31`, fixed; never the clock. Release lag = 45 days, mirroring `macro_binding.RELEASE_LAG`
  exactly. YoY differencing and the eligibility shift are causal by construction; non-overlapping
  windows and the block bootstrap are in from the first run.
- **What this cannot settle:** the 45-day lag is the engine's own placeholder, not a real BLS/BEA
  release calendar (the code says so); the **revision leak is not closed** — a YoY computed on the
  pinned (possibly-revised) index is not strict point-in-time, the same caveat the binding module
  carries; the binary sign-split discards magnitude; two transforms, two fixed windows; equity-index
  targets, not the seated single names; and above all §2 — too few independent inflation regimes in the
  tradeable sample to establish inflation as a signal even in principle.
- Return statistic only. **No card, no engine, no backtest, nothing promotable.**
