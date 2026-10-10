# Daily-assumption change map: running rule evaluation and backtests on arbitrary intervals

Audit date: 2026-08-25. Read-only analysis; no application code was touched. Line numbers verified
against the working tree at the time of writing — a concurrent worktree
(`.claude/worktrees/serene-ardinghelli-afe21a/`) holds a slightly different copy of several of these
files; if a line number looks off when this doc is read later, that drift (or a further edit since)
is why.

## 0. Headline finding not in the original brief

**`Interval.backtestable` is not a gate. Nothing reads it.** `backend/app/db/duck.py:77-79` defines
the property, and exactly one place in the entire codebase calls it: a parametrized unit test
(`tests/test_stores.py:643-655`) that asserts the property's own truth table. No API route, no
service function, and no call site in `backend/app/backtest/`, `backend/app/report/`, or
`backend/app/thesis/` ever checks `interval.backtestable` before running a backtest. The actual
enforcement — such as it is — is an *accidental* `KeyError` several layers downstream, in
`BARS_PER_YEAR[interval]`. This changes the shape of the problem: there is no protective gate to
"relax," because the gate that was documented as existing was never wired in. See §5.

Confirmed independently: `backend/app/api/backtest.py:74` (`_SymbolBody.interval: Interval =
Interval.DAY`) and `backend/app/backtest/models.py:543` (`RunCard.interval: Interval`) both type the
field as the *full* `Interval` enum, not a `Literal[Interval.DAY, Interval.WEEK]` subset. A client can
call `/api/backtest/...?interval=1h` today and it will pass FastAPI/pydantic validation, reach
`app.backtest.strategy.backtest()`, and raise an unhandled `KeyError` at
`backend/app/backtest/strategy.py:148`. Grepping `tests/` for any test that exercises
`strategy.backtest()` or the report/backtest service at `Interval.HOUR` or `Interval.FIVE_MIN` finds
none — this landmine is completely untested, in either direction.

## 1. Corrected assumption table

| File:line | What assumes daily | Severity |
|---|---|---|
| `backend/app/backtest/models.py:587-589` | `BARS_PER_YEAR: dict[Interval, float] = {Interval.DAY: 252.0, Interval.WEEK: 52.0}` — no entry for `FIVE_MIN`/`HOUR` | BREAKS |
| `backend/app/backtest/strategy.py:148` | `bars_per_year = BARS_PER_YEAR[interval]`, unconditional, no `.get()`/default | BREAKS |
| `backend/app/thesis/strategycard.py:353` | `years = n / BARS_PER_YEAR[interval]` inside `_triggers_per_year` — second independent consumer of the same dict, same `KeyError` exposure | BREAKS |
| `backend/app/tournament/selection.py:309` | `_TRADING_DAYS_PER_YEAR = Decimal(252)` — a second, textually independent annualization constant (not derived from `BARS_PER_YEAR`) | WRONG-NUMBERS (if ever fed non-daily data; today unreachable, see §7) |
| `backend/app/tournament/selection.py:315,401` | `Decimal(result.sessions) / _TRADING_DAYS_PER_YEAR` and `Decimal(len(closes)) / _TRADING_DAYS_PER_YEAR` — annualizes a bar/session count by literal 252 | WRONG-NUMBERS (same scope) |
| `backend/app/db/duck.py:77-79` | `Interval.backtestable` property, documented as "whether a statistical study may be run" but never called by any production code path | MISLEADING-NAME-ONLY (it's dead documentation, not a gate — see §0, §5) |
| `backend/app/api/backtest.py:74` | `_SymbolBody.interval: Interval = Interval.DAY` — accepts any `Interval`, not restricted to backtestable ones | BREAKS (this is the actual reachable entry point for the KeyError above) |
| `backend/app/backtest/models.py:543` | `RunCard.interval: Interval` — same unrestricted typing | BREAKS |
| `backend/app/rules/models.py:60` | `HORIZONS: tuple[int, ...] = (1, 5, 20, 60)` — in bars, not days | MISLEADING-NAME-ONLY (already bar-counted; fine mechanically, but "20" reads as "20 days" to a human choosing horizons for 5m bars) |
| `backend/app/tournament/models.py:142` | `max_hold_days: int | None = Field(default=None, ge=1, le=252)` | MISLEADING-NAME-ONLY (confirmed at `tournament/runner.py:458-460`: compared against `session.index - lot.entry_session_index`, i.e. a bar count, not a calendar day count — the field is already interval-agnostic in behavior, only the name and the `le=252` ceiling assume daily) |
| `backend/app/paperdesk/desk.py:1090` | `max_hold_days - t.bars_held` | MISLEADING-NAME-ONLY (same: it's bars, not days; confirms the pattern above) |
| `backend/app/evolution/genome.py:166,236` | `max_hold_days = rng.randint(60, 180)`, clamped to `min(252, ...)` | MISLEADING-NAME-ONLY (same field, propagated into the genetic search space) |
| `backend/app/tournament/runner.py:209,214,223,254,327,395,822` | Seven hardcoded `interval=Interval.DAY` call sites (`guards.check`, `rule_evaluate.evaluate`, `rule_evaluate.evaluate_num`, `BARS_PER_YEAR[Interval.DAY]`) | Not a bug today (tournament never accepts a caller-supplied interval — see §7), but a hardcode that would need parameterizing if tournament itself were ever made interval-aware |
| `backend/app/tournament/allocation.py:485,895` | `interval=Interval.DAY`, `BARS_PER_YEAR[Interval.DAY]` | same as above |
| `backend/app/tournament/ladder.py:905` | `BARS_PER_YEAR[Interval.DAY]` | same as above |
| `backend/app/tournament/roster.py:297` | `read_bars(conn, bars_dir, symbol, Interval.DAY)` | same as above |
| `backend/app/tournament/weightfn.py:244` | `interval=Interval.DAY` | same as above |
| `backend/app/paperdesk/desk.py:688,874,2023` | `Interval.DAY` hardcoded for benchmark read, rule evaluation, and price lookup | same as above — this is the **live paperdesk** path; see §7 |
| `backend/app/paperdesk/benchmarks.py:232` | `duck.Interval.DAY` hardcoded | same as above |
| `backend/app/paper/marketdata.py:110,115,116,131,208` | `Interval.DAY` hardcoded throughout the as-of market-data view used by paperdesk | same as above |
| `backend/app/evolution/universe.py:359,422` | `Interval.DAY` hardcoded for the tradeable-universe listing and partition path | same as above |
| `backend/app/report/builder.py:439-440` | `unit_label = "Sessions" if interval is Interval.DAY else f"{interval.value} bars"` | **Already correctly interval-aware** — its own comment documents a *past* bug ("a report built at `1h` counted hourly bars and labelled them sessions... a seven-fold overstatement") that was fixed here. Use this as the template for how other modules should label bar counts. |
| `backend/app/rules/evidence.py` (whole file) | None found — no `interval` parameter at all; operates purely on bar position/index | Not a defect. See §6 for the full assessment. |
| `backend/app/backtest/forward.py` (whole file) | None found — `forward_returns`, `independent_count`, `hit_rate` are all pure bar-index arithmetic | Not a defect. |
| `backend/app/rules/evaluate.py`, `backend/app/backtest/guards.py` | `interval` is threaded through, but used only for indicator interval-support validation (`IndicatorSpec.supports`) and as a cache key (`_IndicatorKey`/`IndicatorCache`) — never for day-math | Not a defect. Already correctly generic; confirmed by an existing test at `tests/test_rule_evaluate.py:400` that calls `evaluate(node, bars, interval=Interval.FIVE_MIN)` today. |
| `backend/app/indicators/base.py:188-211` | `IndicatorSpec.intervals: frozenset[Interval] | None`, `warmup: Callable[[params], int]` | Not a defect — already bar-counted and interval-gated per-indicator (e.g. VWAP restricted to `{FIVE_MIN, HOUR}` since a session anchor is meaningless on a bar that *is* a session). Confirmed exercised at `Interval.FIVE_MIN`/`Interval.HOUR` in `tests/test_indicators.py:605-606`. |
| `backend/app/market/store.py:66,86` | `_OVERLAP`/`_STALENESS` dicts keyed by `Interval`, already populated for `DAY`/`HOUR`/`FIVE_MIN` | Not a defect for the four *existing* intervals; would need new entries (§2) for any newly added `Interval` member such as 15m or 4h |
| `backend/app/market/cache.py:48` | TTL dict keyed by `Interval`, same shape as above | Same as above |
| `backend/app/market/providers/yahoo.py:57-64,182,299-303` | `_YAHOO_INTERVAL` map and `supported_intervals = frozenset({FIVE_MIN, HOUR, DAY})` — Yahoo is the only intraday provider and it does not fetch 15m or 4h today | Relevant prerequisite, not a bug: see §2, item 1 |
| `backend/app/discovery/candidates.py:172`, `discovery/clusters.py:58`, `discovery/selector.py:49` | `min_bars: int = 252`, `DEFAULT_LOOKBACK = 252`, `_YEAR: Final = 252` | Out of the rule-evaluation/backtest path proper (cross-sectional candidate screening) but same daily-count assumption; flagged for completeness, not scoped into the sequence below |

### Grep sweep beyond the brief's list

Ran an exhaustive grep for `252`, `_TRADING_DAYS`, `trading_days`, `sqrt(`, `annualiz`, `per_year`,
`Interval.DAY`, `max_hold_days`, `"days"`, `resample`, `bday`, `BDay`, `freq=` across
`backend/app` (excluding `backend/build`, which is a stale packaged copy). Findings not already in
the brief's starting map:

- **A second, fully independent annualization implementation** in `backend/app/tournament/selection.py`
  (`_TRADING_DAYS_PER_YEAR = Decimal(252)`, `_window_years`, `_annualized_return`,
  `_annualized_benchmark`, `_qqq_annualized`) — confirmed, matching the brief's flag, but it is more
  extensive than one constant: it's a parallel `Decimal`-based CAGR-style annualization used for
  tournament promotion gates (Gate A), textually unrelated to `app.backtest.metrics`'s float-based one.
  Both assume `Interval.DAY` today because both are only ever fed daily data (see §7), but if this
  module were ever pointed at another interval it would silently mis-annualize rather than crash,
  because it has no `KeyError`-style trip wire at all — it's a bare constant, not a dict lookup.
- **`max_hold_days` is a bar count wearing a day's name** everywhere it appears
  (`tournament/models.py`, `paperdesk/desk.py`, `paperdesk/models.py:91,270`, `evolution/genome.py`,
  `evolution/proposer.py`, `agents/designer.py`, `agents/prompts.py`, `api/competition.py`,
  `tournament/report_pdf.py`). None of these are computational bugs — every enforcement site compares
  it against a bar/session index, never a `datetime` — but the name, the `le=252` field ceiling, and
  the `rng.randint(60, 180)` evolutionary search range would all read as nonsense once a card runs on
  5-minute bars (a 60-"day" hold would be 60 bars ≈ 5 hours).
- **`resample`/weekly bars**: `_resample_weekly` (`backend/app/market/store.py:461`) is the only
  resampling in the codebase, and it groups by ISO calendar week specifically — not a generic
  `freq=`-driven resample. There is no existing resample-on-read machinery for, say, building 4-hour
  bars from 1-hour bars; that would need to be written fresh (see §2, item 1), most naturally modeled
  after `_resample_weekly`'s pattern (resample from a finer stored interval, on read, never persisted)
  rather than fetched from a provider.
- **No `BDay`/`bday`/pandas business-day-frequency usage anywhere** in `backend/app` — the "252
  trading days" convention is applied as a flat constant everywhere it appears, never derived from an
  actual trading calendar. This means there's also no existing dependency on a trading-calendar
  library to build on or worry about breaking.
- **The `Interval` enum itself has only four members**: `FIVE_MIN`, `HOUR`, `DAY`, `WEEK`
  (`backend/app/db/duck.py:67-70`). **15m and 4h — two of the six intervals named in this task's own
  scope — do not exist as `Interval` values today.** This is the single most consequential correction
  to the starting brief: "supporting 15m/4h" is not a relaxation of an existing restriction, it is
  adding two new enum members and everything that keys off `Interval` (provider mapping, `_OVERLAP`,
  `_STALENESS`, cache TTLs, partition paths, `BARS_PER_YEAR`, indicator `intervals` sets) growing two
  new cases. See §2, item 1.

## 2. Dependency-ordered change sequence

Each step names what changes, which files, what it unblocks, and what breaks silently if skipped.

1. **Decide and wire the two missing `Interval` members (15m, 4h), including where their bars come
   from.** Files: `backend/app/db/duck.py` (enum), `backend/app/market/providers/yahoo.py`
   (`_YAHOO_INTERVAL`, `supported_intervals`, `_BAR_DURATION`), `backend/app/market/store.py`
   (`_OVERLAP`, `_STALENESS`, a new `_resample_*` for 4h if it's derived from 1h rather than fetched),
   `backend/app/market/cache.py` (TTL dict). Yahoo's real chart API does serve 15m directly, so that
   member can follow the existing fetch pattern; **4h has no native Yahoo interval** and would need
   to be resampled from stored 1h bars on read, the same way 1w is resampled from 1d today — a new
   function modeled on `_resample_weekly` (`market/store.py:461`), not a `freq=` one-liner, because 4h
   does not divide a 6.5-hour session evenly (see §4's arithmetic). **Unblocks:** every later step that
   wants to talk about 15m/4h at all. **Silent failure if skipped:** none of the later steps are even
   expressible; this must come first if the full six-interval scope is taken literally. If the near-term
   research feature only needs 5m/1h (both already `Interval` members, already stored, already
   evaluable — see §6), this step can be deferred entirely.

2. **Add `Interval.FIVE_MIN`/`Interval.HOUR` (and, if step 1 is done, `FIFTEEN_MIN`/`FOUR_HOUR`)
   entries to `BARS_PER_YEAR`** (`backend/app/backtest/models.py:587-589`), using the arithmetic in
   §4, with an explicit, documented convention for 4h's non-integer bars-per-session (see §4).
   **Unblocks:** `strategy.backtest()` and `thesis/strategycard._triggers_per_year()` no longer
   `KeyError` on intraday intervals. **Silent failure if skipped:** the API-level bug in §0 stays live
   — any client request at a non-daily interval 500s. **Silent failure if done wrong:** picking the
   wrong 4h convention (§4) doesn't crash, it just annualizes every 4h Sharpe/CAGR by a number that's
   off by up to ~23%, and nothing downstream would flag it.

3. **Decide whether `_annualisation_permitted`'s one-year floor (`backend/app/backtest/metrics.py:110-121`)
   is still the right gate once bars-per-year can be 19,656 (5m) instead of 252.** This is a policy
   decision, not a mechanical change, and it interacts with retention: 5m bars retain only 60 days
   (`duck.py`'s own docstring), which is at most 4,680 bars — **always** below the 19,656-bar,
   one-year threshold. If step 2 is done and nothing else changes, every annualized 5m metric
   (Sharpe, Sortino, volatility, CAGR) will *always* silently return `None` under current retention,
   never once producing a number, which will look like "it didn't crash" rather than "it can't
   currently produce this statistic." See §4 for why that floor should probably stay, and the
   implication that annualized metrics should likely not be surfaced for 5m at all in the research UI
   (a UX/scope decision, not a code fix). **Unblocks:** an honest answer to "should the research page
   even show a Sharpe number at 5m." **Silent failure if skipped:** the feature ships, technically
   works, and confusingly never shows a number for the interval users are most likely to try first.

4. **Restrict (or explicitly widen) the `Interval` type actually accepted at the API boundary**
   (`backend/app/api/backtest.py:74`, `backend/app/backtest/models.py:543`, and the analogous fields
   in `backend/app/api/report.py:50,87,168`, `backend/app/api/thesis.py:105,387`). Today these accept
   any `Interval` unconditionally; once steps 2-3 land, this is the point to either (a) leave it open
   now that `KeyError` can't happen, or (b) narrow it with a `Literal`/explicit check if the product
   decision from step 3 is "don't offer annualized backtest metrics below `HOUR`." **Unblocks:**
   correct 422s instead of 500s for whatever is decided not to support. **Silent failure if skipped:**
   none additional beyond step 2/3's own — this step is about the error being *legible* to a caller,
   not about correctness.

5. **Give `tournament/selection.py`'s second annualization implementation
   (`_TRADING_DAYS_PER_YEAR`, `_window_years`, `_qqq_annualized`, lines 309-401) the same
   interval-awareness as step 2, or explicitly document that this module is DAY-only by contract and
   leave it alone.** Because tournament never accepts a caller-supplied interval today (every call
   site hardcodes `Interval.DAY` — see §7), this step has **no urgency** unless a later phase actually
   wants intraday tournament rounds. Doing it prematurely risks introducing a second place that needs
   to stay in sync with `BARS_PER_YEAR` forever. **Recommendation: explicitly defer, not do.**
   **Silent failure if skipped:** none, as long as tournament stays daily-only (§7's isolation
   argument). **Silent failure if done carelessly:** a `Decimal`-based annualization drifting out of
   sync with `metrics.py`'s float-based one the moment someone edits one but not the other — exactly
   the two-implementations-agree-today-is-not-a-property problem `forward.py`'s own docstring warns
   about for a different pair of functions.

6. **Rename or re-document `max_hold_days` (and its evolutionary search bounds) once any card can
   plausibly run on intraday bars.** Files: `backend/app/tournament/models.py:142`,
   `backend/app/paperdesk/desk.py:1044-1090`, `backend/app/paperdesk/models.py:91,270`,
   `backend/app/evolution/genome.py:166,178,235-236`, `backend/app/evolution/proposer.py`,
   `backend/app/agents/designer.py:75`, `backend/app/agents/prompts.py:52`,
   `backend/app/api/competition.py:80,97`, `backend/app/tournament/report_pdf.py:174`. Purely a naming
   and default-range fix (the field is already correctly bar-counted in behavior — confirmed at
   `tournament/runner.py:458-460`) but touches ten-plus call sites, so it's sequenced last: low risk,
   no computational payoff, but real UI/prompt-text confusion if skipped once intraday cards exist.
   **Silent failure if skipped:** a user building a 5m-bar card via the LLM-driven card designer
   (`agents/prompts.py:52`'s prompt text says "max_hold_days integer, 60-180") gets pushed toward a
   60-180 *bar* hold — about 5-15 hours — while believing they specified 60-180 days. Not a crash;
   a strategy that silently means something completely different from what its own field name says.

7. **Do not touch `backend/app/rules/evidence.py` or `backend/app/backtest/forward.py`.** Both are
   already fully bar-index generic (§1, §6) and already exercised at `Interval.FIVE_MIN` by existing
   tests. They are listed here only to make explicit that they are *not* a step — the temptation, when
   doing an "arbitrary interval" pass, is to touch every file that has the word `interval` in it; these
   two should be left alone.

## 3. bars_per_year arithmetic and the annualization-validity verdict

Given a 6.5-hour regular US equity session and 252 sessions/year:

| Interval | Bars/session | Bars/year | Arithmetic |
|---|---|---|---|
| 1d | 1 | 252 | given |
| 1h | 6.5 | **1,638** | `6.5 × 252` |
| 15m | 26 | **6,552** | `(6.5 × 60 / 15) × 252 = 26 × 252` |
| 5m | 78 | **19,656** | `(6.5 × 60 / 5) × 252 = 78 × 252` — matches the brief's figure exactly |
| 4h | 1.625 | **409.5**, *or* 2 × 252 = 504 if every session is padded to a full second bar, *or* 252 if a partial last bar is dropped entirely | `6.5 / 4 = 1.625` bars/session — **does not divide evenly**, unlike every other interval here |

The 4h case is not a lookup, it's a decision: a 6.5-hour session produces one full 4-hour bar
(9:30-13:30) and one 2.5-hour partial (13:30-16:00). Three conventions are all defensible and give
materially different `bars_per_year`, so this needs to be chosen and documented explicitly wherever
`BARS_PER_YEAR[Interval.FOUR_HOUR]` is defined — it should not be silently picked by whichever
arithmetic the implementer typed first, because a Sharpe ratio would come out ~23% different between
the `409.5` and `504` conventions for identical trades.

**Is annualizing a 5m-bar Sharpe by `sqrt(19656)` (≈140.2) statistically meaningful?** No, for three
independent reasons, two structural and one currently absolute:

1. **The i.i.d. assumption underlying `sqrt(N)` scaling is badly violated at 5-minute frequency.**
   The annualization multiplies a per-bar standard deviation by `sqrt(bars_per_year)`, which is only
   valid if returns are uncorrelated with stable variance across the compounding horizon. 5-minute
   equity returns are known to exhibit strong negative autocorrelation from bid-ask bounce and
   microstructure noise, volatility clustering, and a pronounced intraday U-shape (higher volatility
   at the open and close than midday). None of that is true of daily closes to nearly the same
   degree. The textbook correction for this (Lo, "The Statistics of Sharpe Ratios," 2002) explicitly
   derates the naive `sqrt(N)`-scaled Sharpe by an autocorrelation-dependent factor that gets *larger*
   the higher the sampling frequency — meaning the naive number this codebase would compute is
   systematically biased, not merely noisy.
2. **The stored bar series has no overnight/weekend gap in it** (only regular-session bars are kept),
   so `sqrt(N)` scaling implicitly assumes the trading day's realized variance is fully captured by
   intraday bar-to-bar moves alone — it omits the close-to-next-open jump entirely rather than pricing
   it in either direction. Daily bars sidestep this because each bar already *is* a full session,
   gap included.
3. **Under current data retention, the question is moot in practice: the code would never actually
   produce a number.** 5-minute bars are retained for 60 days (`duck.py`'s own docstring), i.e. at
   most `60 × 78 = 4,680` bars. `metrics._annualisation_permitted` requires `years_elapsed =
   bars_elapsed / bars_per_year >= 1.0`, i.e. `bars_elapsed >= 19,656`. `4,680` never reaches that.
   So even after fixing the `KeyError` (§2, step 2), every annualized 5m statistic — Sharpe, Sortino,
   volatility, CAGR — would return `None` on every request, forever, under the current retention
   policy. That floor is doing its job; it just means 5m annualized metrics are not merely
   "misleading," they are **unreachable** as currently configured.

**Verdict for the research feature:** annualized metrics (Sharpe, Sortino, volatility, CAGR,
`trades_per_year`) should not be reported at 5m or 15m scale at all — not because of a code bug, but
because the statistic is either unreachable (5m, under current retention) or statistically dubious
even where reachable (15m: `6,552` bars/year clears the one-year floor with roughly a month of
history, but the same autocorrelation/microstructure argument still applies, just less severely).
1h is the practical floor where annualized metrics both compute *and* are closer to meaningful —
`1,638` bars/year, comfortably clearable within the 730-day retention window, and hourly bars are
far less dominated by microstructure noise than 5-minute ones. This is exactly why §6's recommended
"smallest viable path" reports hit-rate/evidence statistics instead, which carry no annualization
assumption at all.

## 4. Is `Interval.backtestable` a gate worth relaxing?

Reframed by §0: it's not currently a gate at all, so there's nothing to relax — it's unused, dead
documentation that happens to describe intent accurately (DAY/WEEK are the only intervals where the
*existing* `BARS_PER_YEAR`/tournament-annualization stack works) without anything enforcing that
intent. Two honest paths forward:

- **Wire it in as a real, explicit check** at the API boundary (§2, step 4) once §2's steps 2-3 decide
  what's actually supported, so a caller gets a clean 422 ("5m backtests aren't offered because...")
  instead of either a 500 (today) or a silent `None`-everywhere response (after step 2 alone). This
  is the recommended path if the product decision is "some intervals are backtest-eligible and others
  aren't."
- **Delete it** if the decision instead becomes "let any interval attempt a backtest; `None` metrics
  under the one-year floor are the honest answer already, no separate allowlist needed." Less likely
  to be right, since a caller with only 60 days of 5m history has no way to discover *why* every
  number came back `None` without reading this document.

Either way, the property's current state — accurately named, entirely unenforced, tested only for
its own value — is the actual thing to fix, not a restriction to loosen.

**Tests that would need to change**, found by grepping `tests/` for `backtestable`, `BARS_PER_YEAR`,
and `UnsupportedInterval`:

- `tests/test_stores.py:643-655` (`TestOnlyDailyAndWeeklyAreBacktestable`) — asserts
  `interval.backtestable is backtestable` for all four `Interval` members. Would need a new
  parametrize row for each newly added `Interval` member (§2, step 1) and, if the property is wired
  into an actual gate (option above), a companion test asserting the gate itself is enforced somewhere
  a caller can reach — which does not exist today in any form.
- `tests/test_strategy.py` — the shared `_backtest()` test helper (lines ~50-68) hardcodes
  `interval=Interval.DAY` for literally every test in the file (`grep -c "Interval.DAY"` returns 1,
  all of it in that one helper). None of the ~dozens of tests in this file exercise
  `strategy.backtest()` at any other interval. Adding intraday coverage means either parametrizing
  this helper or adding a second, intraday-specific test class alongside it — the existing
  hand-computed-arithmetic tests are pinned to `pd.date_range(..., freq="D")` bars and would not
  translate directly.
- `tests/test_market_registry.py:192`, `tests/test_providers.py:295-298,458-463` — reference
  `UnsupportedInterval` but only for provider-level interval support (Stooq is daily-only, Yahoo
  doesn't fetch weekly), unrelated to the backtest gate. No change needed for this task unless step 1
  (§2) adds a provider mapping for a new interval, in which case these are the right place to add
  provider-level coverage for it.
- No test anywhere in `tests/` currently exercises `app.backtest.strategy.backtest()` or the
  report/backtest service at `Interval.HOUR` or `Interval.FIVE_MIN` — confirmed by grep. This is the
  gap that let the `KeyError` in §0 go unnoticed; any change in §2 should add exactly this coverage.

## 5. Smallest viable path: rule accuracy (evidence.py) without touching annualization

**`backend/app/rules/evidence.py` already runs on intraday bars today, unmodified, with zero interval
assumptions.** Full read of the file confirms:

- `compute_evidence()` takes `signal: pd.Series`, `bars: pd.DataFrame`, `horizons: Sequence[int]`,
  and `entry: Entry` — **no `interval` parameter at all**.
- Every horizon in `HORIZONS = (1, 5, 20, 60)` (`rules/models.py:60`) is a bar count, consumed as a
  bar count all the way through `backend/app/backtest/forward.py`'s `forward_returns()`,
  `independent_count()`, and `hit_rate()` — all pure `numpy` index arithmetic (`entry_idx = idx + 1`,
  `exit_idx = entry_idx + horizon - 1`), with no date, calendar, or session logic anywhere in that
  file.
- The only place a calendar date appears in `evidence.py` is `rule_state()`'s `as_of`/`last_trigger`
  fields, which read `bars["ts"].dt.date` for display purposes (RuleState is "as of what date is this
  rule true"). On intraday bars this is a real but minor gap, not a blocker: multiple 5m/1h bars per
  day collapse to the same `dt.date`, so `bars_since_trigger` (a bar count, computed correctly
  regardless of interval) remains accurate while `last_trigger`/`as_of` lose intraday granularity —
  showing "triggered today" instead of "triggered at 10:35." Classified MISLEADING-NAME-ONLY /
  cosmetic; would be a good follow-up (add an optional intraday timestamp field) but does not block
  the feature.
- `evaluate()` upstream (`rules/evaluate.py:496`) is exercised at `Interval.FIVE_MIN` by an existing
  test (`tests/test_rule_evaluate.py:400`), and indicator support for intraday intervals (VWAP
  restricted to `{FIVE_MIN, HOUR}`) is exercised at `tests/test_indicators.py:605-606`. Nothing new
  needs to be built for the rule-truth-value layer either.

**Smallest viable path, stated directly:** wire a new (or existing, parameterized) API path that reads
already-stored 5m/1h bars via `app.market.store`, calls `app.rules.evaluate.evaluate(tree, bars,
interval=interval)` to get the signal series, then `app.rules.evidence.compute_evidence(signal, bars,
horizons=..., entry=...)` to get hit-rate/baseline/significance per horizon — entirely bypassing
`app.backtest.strategy`, `app.backtest.metrics`, `BARS_PER_YEAR`, and every annualization concern in
this document. No new `Interval` members are even required if the scope stays to 5m/1h/1d/1w, since
those four already exist, are already stored, and are already evaluable.

## 6. Regression risk against live paperdesk/tournament, and an isolation strategy

**The live paths are structurally already isolated, by omission rather than design.** Every call site
in `backend/app/tournament/` (`runner.py`, `allocation.py`, `ladder.py`, `roster.py`, `weightfn.py`)
and `backend/app/paperdesk/` (`desk.py`, `benchmarks.py`) and `backend/app/paper/marketdata.py` and
`backend/app/evolution/universe.py` hardcodes `Interval.DAY` directly in the function body — none of
them accept `interval` as a parameter sourced from a `StrategyCard`, a `LadderCard`, or any other
caller-supplied input. `StrategyCard` (`tournament/models.py:94`) has no `interval` field at all. This
means: **nothing in §2's change sequence, applied only to `backend/app/rules/`,
`backend/app/backtest/models.py`/`strategy.py`/`metrics.py`, and the `/api/backtest`,`/api/report`,
`/api/thesis` routers, can reach tournament or paperdesk at all** — there is no shared code path that
both reads a caller-supplied interval *and* feeds tournament or paperdesk, because tournament/paperdesk
never read a caller-supplied interval in the first place.

The actual risk is narrower and worth naming precisely: `BARS_PER_YEAR` and `Interval` are *shared*
data structures (`backend/app/backtest/models.py`, `backend/app/db/duck.py`) that both the
research/backtest path and, transitively through `BARS_PER_YEAR[Interval.DAY]`, the tournament path
import. **Adding new dict entries is additive and safe** (nothing currently iterates `BARS_PER_YEAR`
or depends on its size); **changing the value already stored at `Interval.DAY` or `Interval.WEEK`, or
changing what `Interval.backtestable` returns for those two, is the one edit that could regress live
behavior**, because tournament/paperdesk import and rely on exactly those two entries being what they
are today.

**Isolation recommendation:**

1. Treat every change in §2 as additive-only to shared enums/dicts (`Interval`, `BARS_PER_YEAR`,
   `_OVERLAP`, `_STALENESS`, cache TTLs) — new keys, never edited existing ones, and no change to
   `Interval.DAY`'s or `Interval.WEEK`'s existing values anywhere.
2. Build the research/accuracy feature (§6's smallest path) as new functions/routes that call
   `rules.evaluate`/`rules.evidence` directly, rather than routing through `report/service.py` or
   `backtest/service.py`'s existing `backtest()`/`report()` entry points — those existing entry points
   are what tournament's report generation and thesis authoring also call, so a new, separate,
   evidence-only entry point keeps the blast radius to genuinely new code.
3. Add the missing test coverage called out in §5 (`strategy.backtest()` and the report/backtest
   service at `Interval.HOUR`/`Interval.FIVE_MIN`) *before* touching `BARS_PER_YEAR`, so the fix and
   its regression test land together and the currently-silent `KeyError` gap doesn't quietly persist.
4. Explicitly do not touch `tournament/selection.py`'s `_TRADING_DAYS_PER_YEAR` stack (§2, step 5) —
   it has no caller-supplied interval to react to, so there is no product requirement forcing that
   change, and touching it only creates a second place that must be kept in sync with
   `BARS_PER_YEAR` forever.

## Corrections to the prior recon (this task's context block)

- `backend/app/backtest/models.py:585-588` for `BARS_PER_YEAR` was off by two lines; the dict is at
  **587-589** (`models.py:587` opens it, `588`/`589` are the two entries).
- `Interval.backtestable` (`duck.py:77-79`) is not actually functioning as a gate anywhere in the
  application — it is unused outside one self-referential test. The brief's framing ("is this a gate
  that should be relaxed") presupposes an enforcement point that does not exist; see §0 and §4.
- The context's `sqrt(19656)` figure for 5m bars/year is **exactly right** — confirmed independently
  via `6.5h × 60min/h ÷ 5min × 252 = 19,656`.
- **15m and 4h are not currently `Interval` enum members at all** — the enum has exactly four values
  (`FIVE_MIN`, `HOUR`, `DAY`, `WEEK`). The brief's phrasing ("arbitrary candle interval (5m/15m/1h/4h/
  1d/1w)") implies all six already exist as first-class intervals; two of them need to be added from
  scratch, including provider wiring, before anything else in this document applies to them. This is
  the single biggest correction to the starting mental model.
- `backend/app/indicators/base.py:188` — the line number for `class IndicatorSpec` is correct as
  given; confirmed unmodified from the brief.
- `backend/app/rules/evaluate.py:496` for `def evaluate(...)` is exactly correct as given.
- Everything else in the brief's starting map (the seven hardcoded `Interval.DAY` call-site files,
  `rules/models.py:60`'s `HORIZONS`, `backtest/guards.py`'s `check()`) checked out accurately against
  the current tree, modulo the small line-number drift noted inline in §1's table.
