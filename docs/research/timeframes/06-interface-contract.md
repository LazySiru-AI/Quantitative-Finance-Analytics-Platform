# Interface contract — multi-timeframe rule research

**Status: frozen.** This is the agreed boundary between the service layer, the HTTP
layer, and the UI. It exists so those three can be built in parallel instead of
serially. Any change to a shape here must be raised with the orchestrator, not made
unilaterally — a worker that "improves" a field name in isolation breaks two other
workers silently.

Derived from [04-accuracy-methodology.md](04-accuracy-methodology.md) (metric
definitions) and [05-feature-surface-design.md](05-feature-surface-design.md)
(endpoints). Read those for the *why*; this document is only the *what*.

---

## 0. Intervals

Seven, finest to coarsest:

    5m, 15m, 30m, 1h, 4h, 1d, 1w

Bars per session and retention (live-verified 2026-08-25):

| interval | bars/session | retention | bars/year |
|---|---:|---|---:|
| 5m | 78 | 60 days | 19656 |
| 15m | 26 | 60 days | 6552 |
| 30m | 13 | 60 days | 3276 |
| 1h | 7 (last is a 30-min stub) | 730 days | 1764 |
| 4h | 2 (4h + a 2.5h remainder) | 730 days | 504 |
| 1d | 1 | unbounded | 252 |
| 1w | — | unbounded (derived from daily) | 52 |

---

## 1. Universe — the 20 liquid names

Frozen for the first sweep. Chosen for liquidity (so intraday bars are dense and
spreads are realistic) and for sector spread (so the per-sector view has something
to say). Four already have intraday history stored.

```python
RESEARCH_UNIVERSE: Final[tuple[tuple[str, str], ...]] = (
    ("SPY",   "Broad Market"),
    ("QQQ",   "Broad Market"),
    ("AAPL",  "Technology"),
    ("MSFT",  "Technology"),
    ("NVDA",  "Technology"),
    ("AMD",   "Technology"),
    ("SOXX",  "Technology"),
    ("GOOGL", "Communication Services"),
    ("META",  "Communication Services"),
    ("AMZN",  "Consumer Discretionary"),
    ("TSLA",  "Consumer Discretionary"),
    ("KO",    "Consumer Staples"),
    ("WMT",   "Consumer Staples"),
    ("JPM",   "Financials"),
    ("BAC",   "Financials"),
    ("JNJ",   "Health Care"),
    ("UNH",   "Health Care"),
    ("XOM",   "Energy"),
    ("CVX",   "Energy"),
    ("CAT",   "Industrials"),
)
```

Sector strings above are the contract's own labels. If `app.discovery` already
exposes a sector taxonomy, prefer it and map onto these labels — **report the
mismatch rather than silently using two vocabularies.**

---

## 2. `RuleAccuracyCell` — the atom

One rule, one interval, one scope, one horizon. Every field is required unless
marked optional. **`lift` is the headline; `hit_rate` must never be displayed
alone.**

```python
class RuleAccuracyCell(BaseModel):
    model_config = ConfigDict(frozen=True)

    # identity
    rule_id: str
    interval: Interval
    scope: Literal["symbol", "sector", "universe"]
    scope_key: str                    # "AAPL" | "Technology" | "ALL"
    horizon_bars: int                 # native to the interval
    horizon_minutes: int              # horizon_bars * interval minutes; the cross-interval key
    horizon_label: str                # human bucket, e.g. "~1 day", "~1 week"

    # sample
    n_raw: int                        # bars where the rule was True
    n_episodes: int                   # after rising-edge dedup
    n_independent: int                # after non-overlap scan -- the gate is applied to THIS
    sufficient: bool                  # n_independent >= MIN_INDEPENDENT (20)

    # measurement
    hit_rate: float | None            # P(fwd return > 0 | fired); None when not sufficient
    base_rate: float | None           # same measure over every evaluable bar, same window
    lift: float | None                # hit_rate - base_rate  <- THE headline number
    lift_ci_low: float | None
    lift_ci_high: float | None
    median_return: float | None
    baseline_median_return: float | None

    # significance
    p_value: float | None
    q_value: float | None             # Benjamini-Hochberg, computed across the whole grid

    # costs
    cost_bps_assumed: float
    cost_adjusted_edge: float | None  # None when not sufficient

    # provenance
    regime: Literal["all", "rising", "falling", "flat"]
    first_bar: dt.datetime
    last_bar: dt.datetime
    warnings: tuple[str, ...]         # e.g. "4h bars alternate 4h/2.5h"
```

### Invariants the service must guarantee

1. `sufficient is False` implies `hit_rate`, `base_rate`, `lift`, both CI bounds,
   `p_value`, `q_value` and `cost_adjusted_edge` are **all `None`**. Never emit a
   number the gate rejected — the UI must be unable to render an ungated figure
   even by accident.
2. `lift == hit_rate - base_rate` whenever all three are non-None.
3. `n_independent <= n_episodes <= n_raw`.
4. `horizon_minutes` is the ONLY field the UI may use to align cells across
   intervals. `horizon_bars` is comparable within one interval only.
5. `warnings` is never `None`; empty tuple when clean.

### Constants

```python
MIN_INDEPENDENT: Final[int] = 20      # the sufficiency gate
DEFAULT_COST_BPS: Final[float] = 5.0  # round-trip; overridable per request
FDR_ALPHA: Final[float] = 0.10
```

---

## 3. Service layer — `backend/app/timeframes/`

Pure computation. No FastAPI imports. **Does not touch `backtest.strategy`,
`backtest.metrics`, or `BARS_PER_YEAR`** — the whole point of this path is to
bypass the annualization stack.

```python
# backend/app/timeframes/service.py

def compute_cells(
    *,
    symbols: Sequence[str],
    intervals: Sequence[Interval],
    rule_ids: Sequence[str] | None = None,   # None = whole catalog
    horizons: Sequence[int] = HORIZONS,      # bar-native, from app.rules.models
    cost_bps: float = DEFAULT_COST_BPS,
    regimes: bool = False,
    settings: Settings,
) -> list[RuleAccuracyCell]: ...

def aggregate(
    cells: Sequence[RuleAccuracyCell],
    *,
    to: Literal["sector", "universe"],
) -> list[RuleAccuracyCell]: ...
```

`aggregate` must **pool the underlying counts**, never average the per-symbol
rates — averaging rates across symbols with unequal sample sizes is the
Simpson's-paradox trap that makes a rare rule look decisive. Pooling is also what
makes rules like `ema_golden_cross` measurable at all: it fails the n>=20 gate on
every interval for any single symbol, and only clears it pooled across the
universe.

FDR (`q_value`) is computed **once over the entire returned grid**, after gating —
so it must run at the end of `compute_cells`, not per-symbol.

### Signal trace, for chart markers

```python
def signal_trace(
    *, symbol: str, interval: Interval, rule_id: str, settings: Settings,
) -> SignalTrace: ...

class SignalTrace(BaseModel):
    symbol: str
    interval: Interval
    rule_id: str
    expression: str
    bars: list[Bar]                        # the window charted
    indicators: list[IndicatorSeries]      # SMA/EMA/BB etc. the rule references
    fired_at: list[dt.datetime]            # rising edges only, ascending
    warmup_until: dt.datetime | None       # bars before this are NA, not False
```

`fired_at` carries **rising edges only** — the same de-duplication the accuracy
path uses, so the markers on screen match the n the table reports. Showing every
True bar would draw 77 markers a day for `bb_squeeze` and contradict its own
`n_episodes`.

---

## 4. HTTP layer — `backend/app/api/timeframes.py`

`APIRouter(prefix="/api/timeframes")`, registered in `backend/app/main.py`
alongside the existing routers.

| method | path | sync? | purpose |
|---|---|---|---|
| GET | `/intervals` | sync | the seven intervals + retention + bars/session |
| GET | `/universe` | sync | the 20 symbols with sectors |
| GET | `/matrix` | sync | small on-demand slice |
| POST | `/matrix/jobs` | async | full sweep, returns `{job_id}` |
| GET | `/matrix/jobs/{job_id}` | sync | poll status/result |
| GET | `/signal` | sync | one `SignalTrace` for the drill-down chart |

`GET /matrix` query params: `symbols` (csv, optional), `sectors` (csv, optional),
`intervals` (csv, default all seven), `rule_ids` (csv, optional),
`horizon_minutes` (int, optional), `scope` (`symbol|sector|universe`, default
`sector`), `cost_bps` (float, default 5.0).

Response:

```jsonc
{
  "cells": [ /* RuleAccuracyCell */ ],
  "generated_at": "2026-08-25T23:40:00Z",
  "coverage": { "symbols": 20, "intervals": 7, "rules": 24,
                "cells_total": 3360, "cells_sufficient": 2104 },
  "warnings": ["SPY 5m: 41 days stored, 60 requested"]
}
```

`cells_sufficient` vs `cells_total` is deliberately surfaced: the honest headline
for this feature is how much of the grid is actually measurable.

**Guard:** `GET /matrix` must 422 — never 500 — when asked for more than
`MAX_SYNC_PAIRS = 20` `(symbol, interval)` pairs, directing the caller to the job
endpoint. The unit of work is one `(symbol, interval)` pair; all rules and horizons
for that pair compute together off shared caches.

Jobs mirror `app.tournament.jobs`' submit/poll pattern but **must use their own
lock** — the tournament's process-wide lock is held by real tournament rounds and
must not be contended by research sweeps.

---

## 5. Frontend — `frontend/src/api/timeframes.ts`

Follows the existing per-module convention: local `requestJson<T>` over `fetch`,
throwing `ApiRequestError`, unwrapping FastAPI's `{"detail": ...}`. Mirror the
types above field-for-field.

All the numeric fields here are **statistics, not money** — plain JSON `number` is
correct. The `DecimalString` rule applies to money and quantities and does not
apply to this module.

```ts
export type Interval = "5m" | "15m" | "30m" | "1h" | "4h" | "1d" | "1w";
export type Scope = "symbol" | "sector" | "universe";
export type Regime = "all" | "rising" | "falling" | "flat";

export interface RuleAccuracyCell { /* mirrors section 2 exactly */ }

export const timeframesApi = {
  intervals: (signal?: AbortSignal) => ...,
  universe:  (signal?: AbortSignal) => ...,
  matrix:    (params: MatrixQuery, signal?: AbortSignal) => ...,
  signal:    (params: SignalQuery, signal?: AbortSignal) => ...,
  startSweep: (params: MatrixQuery) => ...,
  sweepStatus: (jobId: string, signal?: AbortSignal) => ...,
};
```

### UI rules that are part of the contract, not styling preferences

1. A cell with `sufficient === false` renders as a distinct
   insufficient-sample treatment — **never** as a number, never as `0%`, never as
   an empty cell that reads as zero.
2. `lift` is the value that drives cell colour and the large figure. `hit_rate` may
   appear only as secondary text, always beside its `base_rate`.
3. Cross-interval columns align on `horizon_minutes`, never `horizon_bars`.
4. `warnings` on a cell must be reachable from the UI (tooltip or drill-down).
5. The 4h column carries a persistent low-confidence marker: alternating bar
   durations, ~73 independent windows/symbol against daily's ~250.
