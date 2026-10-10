# Indicator & rule-evaluation behavior on intraday bars — empirical results

Everything in this document was produced by executing real code in this repository against real
parquet data already on disk, via throwaway probe scripts run through the repo venv. No claim below
is inferred; anything not actually run is marked NOT VERIFIED.

Probe scripts (not part of the repo, kept for reference only):
`C:\Users\<user>\AppData\Local\Temp\claude\C--Users--user--repos-Investing-dashboard\4db09223-8ac4-4f98-867a-07dcc45c688a\scratchpad\probe{1..5}_*.py`

## 1. Import setup that actually worked

```
cd "<repo>"
PYTHONPATH=".;backend" .venv/Scripts/python.exe -c "import app.indicators; print('OK', app.indicators.__file__)"
# -> OK C:\...\backend\app\indicators\__init__.py
```

Two things mattered:
- Must use `.venv/Scripts/python.exe` directly (the repo venv), not a bare `python`.
- `PYTHONPATH` needs **both** the repo root and `backend/`, joined with `;` (Windows path
  separator, not `:`). This mirrors `pytest.ini`'s `pythonpath = . backend` line exactly — the repo
  root is needed for anything doing `from tests.conftest import ...`-style imports elsewhere in the
  project, and `backend` is what makes `app.*` importable at all. All five probe scripts were run
  as `PYTHONPATH=".;backend" .venv/Scripts/python.exe <script>.py` from the repo root, no `cd`
  into `backend` needed.

`app.market.store.read_frame(symbol, interval)` was used as the real data-read path (backed by
`app.db.duck.read_bars`) rather than raw pandas/parquet reads — it did not attempt any network
sync, since it only reads what's already in `data/store/bars/` (the default `Settings.bars_dir`
already resolves to that path).

## 2. Rule catalog and indicator registry inventory

`backend/app/rules/catalog.py` — **12 rules total**, enumerated via `catalog()`:

| rule_id | expression | intervals |
|---|---|---|
| rsi_oversold | `rsi(14) < 30` | ANY |
| rsi_overbought | `rsi(14) > 70` | ANY |
| bb_lower_touch | `close < bb_lower(20,2)` | ANY |
| bb_upper_touch | `close > bb_upper(20,2)` | ANY |
| bb_squeeze | `bb_upper(20,2) - bb_lower(20,2) < close * 0.04` | ANY |
| ema_golden_cross | `ema(50) crosses_above ema(200)` | ANY |
| ema_death_cross | `ema(50) crosses_below ema(200)` | ANY |
| macd_bullish_flip | `macd_hist(12,26,9) crosses_above 0` | ANY |
| macd_bearish_flip | `macd_hist(12,26,9) crosses_below 0` | ANY |
| price_above_sma200 | `close > sma(200)` | ANY |
| atr_range_expansion | `high - low > atr(14) * 1.5` | ANY |
| vwap_reclaim | `close crosses_above vwap()` | **INTRADAY-only** (5m, 1h) |

**11 of 12 rules declare "any interval"; 0 rules declare "daily-only"; 1 rule (vwap_reclaim) is
restricted to intraday-only.** This contradicts nothing in the brief, but is worth stating plainly:
there is no daily-only rule in this catalog to compare against — the asymmetry runs the other way.

`backend/app/indicators/registry.py` — **10 registered indicators** (`REGISTRY`):

| name | intervals | outputs |
|---|---|---|
| sma | ALL | (single) |
| ema | ALL | (single) |
| macd | ALL | macd, signal, hist |
| rsi | ALL | (single) |
| bb | ALL | upper, mid, lower |
| atr | ALL | (single) |
| vwap | **{5m, 1h} only** | (single) |
| swing | ALL (data_dependent_warmup=True) | high, low |
| rsi_at_swing | ALL (data_dependent_warmup=True) | high, low |
| macd_at_swing | ALL (data_dependent_warmup=True) | high, low |

Only `vwap` carries an interval restriction; every other indicator in the registry is
`intervals=None` (registered for all four `Interval` values, including `1w`, though weekly bars
are resampled rather than stored).

`Interval` enum (`backend/app/db/duck.py`): `5m`, `1h` both have `.is_intraday=True` and
`.backtestable=False`; `1d`, `1w` both have `.is_intraday=False` and `.backtestable=True`. **This is
a load-bearing fact for task 9/evidence** below — backtests are explicitly restricted to daily/
weekly by this property, even though nothing in `evidence.py` itself enforces it (see §9).

## 3. Actual data inventory (from `read_frame`, live)

`bars_dir` resolved to `data/store/bars` (the repo default).

| interval | symbols present | example: QQQ row count | example: QQQ ts range |
|---|---|---|---|
| 5m | AMZN, DRAM, NVDA, QQQ, SOXL, SOXX (6) | 3822 | 2026-06-15 13:30 UTC .. 2026-08-24 19:55 UTC |
| 1h | AMZN, DRAM, NVDA, QQQ, SOXL (5) | 3548 | 2024-08-13 13:30 UTC .. 2026-08-24 19:30 UTC |
| 1d | 689 symbols (full universe) | 6907 | 1999-03-10 .. 2026-08-24 |

All 5m symbols had exactly 3822 rows (identical range) except none dropped. 1h row counts varied
(AMZN/QQQ 3548, NVDA/SOXL 3555, DRAM only 693 — DRAM's stored history starts 2026-04-02, evidently
a much more recently-added symbol). `adj_close` is `NaN` for 100% of intraday rows for every symbol
checked — consistent with the documented "no provider supplies an adjusted series intraday" note in
`duck.py`. `ts` dtype is `datetime64[us, UTC]` (timezone-aware) in all cases, satisfying
`evidence.rule_state`'s explicit tz-aware assertion.

QQQ was used as the representative symbol for tasks 4–9 below (present at all three intervals: 5m,
1h, 1d).

## 4 & 5. `evaluate()` run for real — full results table

Every catalog rule plus 6 hand-written expressions (SMA cross, EMA cross, BB touch/breach, RSI
thresholds) run against QQQ bars at 5m, 1h, and 1d via `app.rules.evaluate.evaluate()`. **Nothing
raised in any of the 46 (rule × interval) combinations actually executed** (vwap_reclaim correctly
skipped on 1d — the catalog's own `intervals` restriction, not a runtime failure).

`fires/day` = `n_true / distinct_calendar_days_in_the_series` — the empirical "signal density per
unit of calendar time" the brief asked for.

| rule | interval | bars | true | false | NA | warmup ends (idx) | cal days | fires/day |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| rsi_oversold | 5m | 3822 | 229 | 3579 | 14 | 14 | 49 | **4.673** |
| rsi_oversold | 1h | 3548 | 175 | 3359 | 14 | 14 | 509 | 0.344 |
| rsi_oversold | 1d | 6907 | 108 | 6785 | 14 | 14 | 6907 | 0.016 |
| rsi_overbought | 5m | 3822 | 210 | 3598 | 14 | 14 | 49 | **4.286** |
| rsi_overbought | 1h | 3548 | 434 | 3100 | 14 | 14 | 509 | 0.853 |
| rsi_overbought | 1d | 6907 | 652 | 6241 | 14 | 14 | 6907 | 0.094 |
| bb_lower_touch | 5m | 3822 | 267 | 3536 | 19 | 19 | 49 | **5.449** |
| bb_lower_touch | 1h | 3548 | 216 | 3313 | 19 | 19 | 509 | 0.424 |
| bb_lower_touch | 1d | 6907 | 342 | 6546 | 19 | 19 | 6907 | 0.050 |
| bb_upper_touch | 5m | 3822 | 172 | 3631 | 19 | 19 | 49 | **3.510** |
| bb_upper_touch | 1h | 3548 | 192 | 3337 | 19 | 19 | 509 | 0.377 |
| bb_upper_touch | 1d | 6907 | 409 | 6479 | 19 | 19 | 6907 | 0.059 |
| bb_squeeze | 5m | 3822 | 3783 | 20 | 19 | 19 | 49 | **77.204** |
| bb_squeeze | 1h | 3548 | 2776 | 753 | 19 | 19 | 509 | 5.454 |
| bb_squeeze | 1d | 6907 | 763 | 6125 | 19 | 19 | 6907 | 0.110 |
| ema_golden_cross | 5m | 3822 | 8 | 3615 | 199 | 199 | 49 | 0.163 |
| ema_golden_cross | 1h | 3548 | 8 | 3340 | 200 | 200 | 509 | 0.016 |
| ema_golden_cross | 1d | 6907 | 14 | 6693 | 200 | 200 | 6907 | 0.002 |
| ema_death_cross | 5m | 3822 | 8 | 3614 | 200 | 200 | 49 | 0.163 |
| ema_death_cross | 1h | 3548 | 8 | 3341 | 199 | 199 | 509 | 0.016 |
| ema_death_cross | 1d | 6907 | 14 | 6694 | 199 | 199 | 6907 | 0.002 |
| macd_bullish_flip | 5m | 3822 | 154 | 3634 | 34 | 34 | 49 | 3.143 |
| macd_bullish_flip | 1h | 3548 | 129 | 3386 | 33 | 33 | 509 | 0.253 |
| macd_bullish_flip | 1d | 6907 | 278 | 6595 | 34 | 34 | 6907 | 0.040 |
| macd_bearish_flip | 5m | 3822 | 155 | 3634 | 33 | 33 | 49 | 3.163 |
| macd_bearish_flip | 1h | 3548 | 128 | 3386 | 34 | 34 | 509 | 0.251 |
| macd_bearish_flip | 1d | 6907 | 279 | 6595 | 33 | 33 | 6907 | 0.040 |
| price_above_sma200 | 5m | 3822 | 1706 | 1917 | 199 | 199 | 49 | **34.816** |
| price_above_sma200 | 1h | 3548 | 2262 | 1087 | 199 | 199 | 509 | 4.444 |
| price_above_sma200 | 1d | 6907 | 4907 | 1801 | 199 | 199 | 6907 | 0.710 |
| atr_range_expansion | 5m | 3822 | 340 | 3469 | 13 | 13 | 49 | 6.939 |
| atr_range_expansion | 1h | 3548 | 394 | 3141 | 13 | 13 | 509 | 0.774 |
| atr_range_expansion | 1d | 6907 | 463 | 6431 | 13 | 13 | 6907 | 0.067 |
| vwap_reclaim | 5m | 3822 | 174 | 3647 | 1 | 1 | 49 | 3.551 |
| vwap_reclaim | 1h | 3548 | 473 | 3074 | 1 | 1 | 509 | 0.929 |
| vwap_reclaim | 1d | — | — | — | — | — | — | SKIPPED (rule declares intervals={5m,1h}) |
| sma_cross_10_30 (hand) | 5m | 3822 | 70 | 3722 | 30 | 30 | 49 | 1.429 |
| sma_cross_10_30 (hand) | 1h | 3548 | 60 | 3458 | 30 | 30 | 509 | 0.118 |
| sma_cross_10_30 (hand) | 1d | 6907 | 116 | 6761 | 30 | 30 | 6907 | 0.017 |
| ema_cross_12_26 (hand) | 5m | 3822 | 57 | 3739 | 26 | 26 | 49 | 1.163 |
| ema_cross_12_26 (hand) | 1h | 3548 | 55 | 3467 | 26 | 26 | 509 | 0.108 |
| ema_cross_12_26 (hand) | 1d | 6907 | 108 | 6773 | 26 | 26 | 6907 | 0.016 |
| bb_touch_lower_20_2 (hand, =bb_lower_touch) | 5m/1h/1d | — | — | — | — | — | — | identical to bb_lower_touch row above |
| bb_breach_upper_20_2 (hand, =bb_upper_touch) | 5m/1h/1d | — | — | — | — | — | — | identical to bb_upper_touch row above |
| rsi_thresh_14_30 (hand, =rsi_oversold) | 5m/1h/1d | — | — | — | — | — | — | identical to rsi_oversold row above |
| rsi_thresh_14_70 (hand, =rsi_overbought) | 5m/1h/1d | — | — | — | — | — | — | identical to rsi_overbought row above |

**Core research question, answered empirically:** for every single rule/expression tested, the
firing rate per calendar day is dramatically higher at 5m than at 1d — typically 40–300x, and as
high as **~700x** for `bb_squeeze` (77.2/day at 5m vs 0.110/day at 1d) and **~49x** for
`price_above_sma200` (34.8/day at 5m vs 0.710/day at 1d). This is exactly the phenomenon the brief
predicted: `sma(200)` on 5m bars settles after ~2.5 trading days of data and then evaluates a
"trend filter" on a rolling 100-minute-to-few-day window, not the multi-quarter trend the same
expression means on daily bars — a completely different indicator riding under an identical name
and threshold.

## 6. Warmup correctness at period=200 on 5m

```
5m: sma(200) warmup = 199 bars. Total bars available = 3822 over 49 distinct trading days.
    warmup in session-days terms: 199 bars / ~78 bars-per-session = ~2.55 trading days
    consumed just to settle sma(200), vs a DAILY sma(200) which consumes 200 calendar
    trading days (~9.5 months).
    warmup consumes 5.2% of the entire available 5m history for QQQ.

1h: sma(200) warmup = 199 bars. Total bars available = 3548 over 509 distinct trading days.
    warmup in session-days terms: 199 bars / ~7 bars-per-session = ~28.43 trading days
    consumed just to settle sma(200).
    warmup consumes 5.6% of the entire available 1h history for QQQ.
```

`IndicatorSpec.warmup` returns a **bar count**, exactly as documented, and behaves mechanically
correctly at intraday scale (199 leading NaNs for a 200-period SMA is right; matches what was
independently observed in the `evaluate()` NA counts above — `price_above_sma200`'s NA column reads
199 at every interval). It does not misbehave. But the count is not *sane in the sense the brief
asks about*: 199 bars is ~2.5 trading days on 5m data (given the 60-day retention window on 5m per
`Interval`'s own docstring, warmup eats roughly 1/24th of the entire retainable history) versus
~28 trading days on 1h data (against a 730-day retention window, a much smaller fraction). Nothing
in `warmup`'s contract adjusts for what "200" is supposed to represent at a given interval — it is
purely `Callable[[params], int]` returning a bar count, deaf to the interval it's being asked about.
This is not a bug in the warmup mechanism; it is the same "same expression, different meaning at
different intervals" problem from §5, restated as an availability constraint: a `period=200`
indicator is comfortably affordable on 5m's 60-day retention window (only 5.2% of history spent
settling) but represents a far shorter *look-back* than the same parameter on daily bars.

## 7. Overnight gaps and session boundaries — worked example

Checked directly against the stored 5m parquet for QQQ:

- **78 distinct times-of-day** are present across the whole file, running exactly `13:30:00` to
  `19:55:00` (UTC). This is precisely the regular NYSE session (9:30–16:00 ET = 13:30–20:00 UTC
  during DST) at 5-minute spacing (`78 = 6.5h × 60 / 5`). **No pre-market or post-market bars are
  present** in the stored 5m data for QQQ.
- Gaps are represented as **missing rows**, not NaN-filled placeholders: scanning consecutive `ts`
  deltas found 48 gaps larger than 6 minutes across the 5m series — one per overnight boundary, plus
  wider ones across weekends (example: `2026-06-18 19:55 UTC -> 2026-06-22 13:30 UTC`, a
  `3 days 17:35:00` gap spanning a weekend).

**Concrete worked example, real timestamps:** the bar at index 3744 (`ts=2026-08-24 13:30:00 UTC`,
a Monday) follows a `2 days 17:35:00` gap since the prior stored bar (`ts=2026-08-21 19:55:00 UTC`,
the preceding Friday). A 20-bar rolling window ending at that Monday-open bar spans indices
`[3725, 3744]` — 19 bars of Friday-afternoon closes (`2026-08-21 18:25` through `19:55` UTC) plus
the single new Monday bar. The registry's actual `sma(20)` value at index 3744 was computed and
compared against the manual mean of that exact 20-row window:

```
Library sma(20) at idx 3744: 712.9929901123047
Manual mean of the 20 bars shown above (spanning the gap): 712.9929901123047
Match: True
```

**Verdict (session-gap):** The rolling window is a pure position-count window with no session or
calendar awareness whatsoever — confirmed by direct reproduction, not inference. At 09:30 ET on
Monday 2026-08-24, QQQ's `sma(20)` on 5m bars is silently a blend of 19 Friday-afternoon closing
prices and 1 fresh Monday price, averaged as if they were continuous. Whether that is "acceptable"
depends entirely on what the indicator is meant to answer: for a short-horizon mean-reversion or
band-width read that already accepts the overnight gap as part of "recent price action," this is
probably fine and arguably intended; for anything meant to represent *intraday session* structure
(e.g., "today's opening range," or comparing today's first hour to a pure-intraday baseline) it is
wrong by construction and would need explicit session-aware handling (a per-session reset or a
`groupby(session_date)` rolling window) that nothing in this codebase currently provides — `vwap`
is the only indicator in the registry with any session concept at all (`anchor="session"`), and even
that is opt-in per request, not a property every window respects.

## 8. `backend/app/backtest/guards.py` against intraday

Ran `guards.check(expr, bars, interval=interval)` for 4 representative expressions (RSI threshold,
EMA cross, Bollinger touch, VWAP reclaim) against both 5m and 1h QQQ bars — **8 calls total, all
passed with zero failed findings**:

```
[5m] 'rsi(14) < 30': status=passed (3 findings, 0 failed)
[5m] 'ema(50) crosses_above ema(200)': status=passed (4 findings, 0 failed)
[5m] 'close < bb_lower(20,2)': status=passed (3 findings, 0 failed)
[5m] 'close crosses_above vwap()': status=passed (3 findings, 0 failed)
[1h] 'rsi(14) < 30': status=passed (3 findings, 0 failed)
[1h] 'ema(50) crosses_above ema(200)': status=passed (4 findings, 0 failed)
[1h] 'close < bb_lower(20,2)': status=passed (3 findings, 0 failed)
[1h] 'close crosses_above vwap()': status=passed (3 findings, 0 failed)
```

Drilling into one causality finding directly (`ema(50) crosses_above ema(200)` on 5m QQQ, 3822
bars) confirmed the guard actually performed its real tail-truncation test, not a trivial pass:

```
ast_whitelist True :: every node in the tree is on the allowlist...
causality True :: ema_50: identical at every position across 8 leading slices of 3822 bars
causality True :: ema_200: identical at every position across 8 leading slices of 3822 bars
point_in_time True :: scope note: ...
```

**The lookahead guard passes cleanly on intraday data** — it is interval-agnostic by construction
(it only ever calls `request.compute(bars)` and slices `bars.iloc[:cut]`, neither of which cares
what `Interval` produced the frame), and 3822/3548-bar intraday series comfortably clear
`_MIN_BARS_FOR_CAUSALITY = 40`, so the 8 causality cuts always had a real post-warmup region to
truncate. No error, no silent misbehavior observed.

## 9. `backend/app/rules/evidence.py` on intraday — does it run today, unmodified?

**Yes.** Called `compute_evidence(signal, bars)` directly (no modification, default `horizons=(1,
5, 20, 60)` bars and `entry=Entry.NEXT_OPEN`) against `rsi(14) < 30` evaluated on both 5m and 1h QQQ
bars. Both succeeded with no traceback:

```
[5m] compute_evidence('rsi(14) < 30') SUCCEEDED: 4 horizon rows
    horizon=1  hit_rate=0.568 baseline=0.494 sample_size=229 independent=229 sig=insufficient
    horizon=5  hit_rate=0.568 baseline=0.496 sample_size=229 independent=73  sig=insufficient
    horizon=20 hit_rate=0.624 baseline=0.478 sample_size=229 independent=41  sig=suggestive
    horizon=60 hit_rate=0.485 baseline=0.441 sample_size=229 independent=29  sig=insufficient
    rule_state: TriState.FALSE as_of=2026-08-24 last_trigger=2026-08-24 bars_since_trigger=66 triggers=229

[1h] compute_evidence('rsi(14) < 30') SUCCEEDED: 4 horizon rows
    horizon=1  hit_rate=0.486 baseline=0.524 sample_size=175 independent=175 sig=insufficient
    horizon=5  hit_rate=0.566 baseline=0.553 sample_size=175 independent=63  sig=insufficient
    horizon=20 hit_rate=0.698 baseline=0.584 sample_size=169 independent=33  sig=suggestive
    horizon=60 hit_rate=0.669 baseline=0.607 sample_size=166 independent=23  sig=insufficient
    rule_state: TriState.FALSE as_of=2026-08-24 last_trigger=2026-08-24 bars_since_trigger=6 triggers=175
```

`rule_state`'s explicit `bars["ts"].dt.tz is None` guard did not trip — the stored intraday
`ts` column is already tz-aware UTC (`datetime64[us, UTC]`), so that particular safety check is
satisfied by the data as stored.

**Important caveat, backed by §2 and §5-6:** "runs without raising" is not the same as "the numbers
mean the same thing as they do on daily bars." `Evidence.horizon` is a bar count, shared verbatim
between intervals via the module-level `HORIZONS = (1, 5, 20, 60)` constant in
`app.rules.models`. On 5m bars, `horizon=20` is a **100-minute** forward return; on daily bars the
identical `horizon=20` is a **20-trading-day (~1 month)** forward return. `evidence.py` computes both
without complaint or any interval-aware relabeling — nothing here enforces `Interval.backtestable`
(that property exists on `Interval` in `duck.py` but `compute_evidence`/`rule_state` never reference
it or reject on it). The module's own docstring warns generally about overlapping windows and
warmup dilution, but it carries no code path that treats "bars" as anything other than an
interval-agnostic unit — which is exactly what makes it silently runnable on 5m/1h data today
despite `Interval.backtestable` being `False` for both.

## Corrections to the task brief

- The brief's line numbers for `evaluate()` (~496) and `parse()` (~634) in `evaluate.py`/`grammar.py`
  matched exactly at the time this was run — no drift found there.
- `IndicatorSpec.intervals` restriction in this codebase is **VWAP-only** (one indicator, one rule).
  The brief's framing ("daily-only vs. any-interval") implicitly expects some daily-only rules to
  exist to contrast against; there are **none** — the only interval restriction anywhere in the
  catalog or registry runs in the intraday-only direction. This is worth flagging because a reader
  skimming for "daily-only count" will find zero and might assume a probe failure; it is not one.
- Everything else in the brief's "Context" section (file locations, `Interval` StrEnum values,
  `BAR_COLUMNS`, the store's partition layout, the intraday symbol counts) was independently
  confirmed by direct inspection and is accurate.
