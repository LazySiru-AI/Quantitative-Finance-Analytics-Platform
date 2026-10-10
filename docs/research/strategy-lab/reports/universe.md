# Universe characterisation — stream `universe`

Run 2026-08-11 (re-run after a serial retry recovered four symbols that failed on the first,
concurrent pass — see Part A). This stream does not test a hypothesis and reports no p-value, no
q-value, no verdict. It answers "what is worth researching right now, for short-term swing and for
long-term holding" the only way this study is allowed to: by measuring a broad candidate universe on
its own stored history and handing back a characterisation, never a recommendation. **Every table
below is a description of what an instrument's price series did historically. None of it is a
forecast, and nothing in this report should be read as advice to buy, sell, or hold anything.**

All numbers came from `docs/research/strategy-lab/scripts/universe.py` (fetch + compute) and
`scripts/universe_tables.py` (formatting/ranking of the same numbers — no new statistics). Raw output
is `docs/research/strategy-lab/data/universe.json`. Bars were read via `quantlab.bars_frame` →
`app.market.store.ensure_series` against the production cache (`data/store/bars` /
`data/store/analytics.duckdb`) — the same call the chart endpoint makes, and the app working
normally. Nothing in this stream wrote a run card or touched `thesis.sqlite`, `ledger.sqlite`, or any
brokerage CSV.

---

## Part A — candidate universe

### Selection, declared before fetching

| category | symbols | why these |
|---|---|---|
| core | SPY VOO VTI QQQ QQQM IWM DIA RSP | broad market exposures at different weighting schemes (cap, equal, price) and share classes; QQQM/SOXX/SPY are the note's own p.11 list |
| sectors | XLK XLF XLE XLV XLY XLP XLU XLI XLB XLC XLRE | all eleven SPDR sector funds |
| themes | SOXX SMH IGV XBI ITA ARKK | note's semiconductor pick (SOXX) plus a near-duplicate to test that claim (SMH), software (IGV), equal-weight biotech (XBI), defense (ITA), and an actively-managed theme with a structurally different turnover/concentration profile (ARKK), kept deliberately small |
| factor/defensive | USMV SPLV VIG SCHD QUAL MTUM VLUE | brief's exact list |
| non-equity | TLT IEF SHY GLD SLV DBC BIL VEA VWO EFA BND AGG | rates curve (TLT/IEF/SHY), metals (GLD/SLV), broad commodities (DBC), cash proxy (BIL), international developed/emerging (VEA/VWO/EFA), broad bond (BND/AGG — kept as a pair deliberately, to test the near-duplicate claim rather than assert it) |
| leveraged | QLD TQQQ SOXL SSO UPRO | note's own pick (QLD) plus the 3x cousin of each underlying it and SOXX/SPY have (TQQQ/SOXL/UPRO) and the 2x SPY product (SSO), for a factor-2 vs factor-3 comparison |
| singles | NVDA AMZN AAPL MSFT GOOGL META TSLA | **selection rule, stated before fetching**: the largest US-listed companies by well-known mega-cap index (QQQ/SPY) membership as of this run date, per the analyst's general knowledge of index composition — not fetched or verified against a live holdings file. NVDA and AMZN were already cached; the other five were added to make the single-stock category more than two points while staying modest (7 of 56 candidates). **This list is today's survivors by construction — see Part C.** |

56 candidates declared, 0 substituted after the fact.

### Coverage — all 56 resolved

| symbol | category | first | last | bars |
|---|---|---|---|---|
| SPY | core | 1993-01-29 | 2026-08-11 | 8440 |
| VOO | core | 2010-09-09 | 2026-08-11 | 4004 |
| VTI | core | 2001-06-15 | 2026-08-11 | 6325 |
| QQQ | core | 1999-03-10 | 2026-08-11 | 6898 |
| QQQM | core | 2020-10-13 | 2026-08-11 | 1463 |
| IWM | core | 2000-05-26 | 2026-08-11 | 6590 |
| DIA | core | 1998-01-20 | 2026-08-11 | 7184 |
| RSP | core | 2003-05-01 | 2026-08-11 | 5857 |
| XLK | sectors | 1998-12-22 | 2026-08-11 | 6950 |
| XLF | sectors | 1998-12-22 | 2026-08-11 | 6950 |
| XLE | sectors | 1998-12-22 | 2026-08-11 | 6950 |
| XLV | sectors | 1998-12-22 | 2026-08-11 | 6950 |
| XLY | sectors | 1998-12-22 | 2026-08-11 | 6950 |
| XLP | sectors | 1998-12-22 | 2026-08-11 | 6950 |
| XLU | sectors | 1998-12-22 | 2026-08-11 | 6950 |
| XLI | sectors | 1998-12-22 | 2026-08-11 | 6950 |
| XLB | sectors | 1998-12-22 | 2026-08-11 | 6950 |
| XLC | sectors | 2018-06-19 | 2026-08-11 | 2047 |
| XLRE | sectors | 2015-10-08 | 2026-08-11 | 2725 |
| SOXX | themes | 2001-07-13 | **2026-08-10** | 6305 |
| SMH | themes | 2000-06-05 | 2026-08-11 | 6585 |
| IGV | themes | 2001-07-17 | **2026-08-10** | 6303 |
| XBI | themes | 2006-02-06 | 2026-08-11 | 5160 |
| ITA | themes | 2006-05-05 | 2026-08-11 | 5098 |
| ARKK | themes | 2014-10-31 | 2026-08-11 | 2960 |
| USMV | factor_defensive | 2011-10-20 | 2026-08-11 | 3722 |
| SPLV | factor_defensive | 2011-05-05 | 2026-08-11 | 3839 |
| VIG | factor_defensive | 2006-05-02 | 2026-08-11 | 5101 |
| SCHD | factor_defensive | 2011-10-20 | 2026-08-11 | 3722 |
| QUAL | factor_defensive | 2013-07-18 | 2026-08-11 | 3286 |
| MTUM | factor_defensive | 2013-04-18 | 2026-08-11 | 3349 |
| VLUE | factor_defensive | 2013-04-18 | 2026-08-11 | 3349 |
| TLT | non_equity | 2002-07-30 | 2026-08-11 | 6047 |
| IEF | non_equity | 2002-07-30 | 2026-08-11 | 6047 |
| SHY | non_equity | 2002-07-30 | 2026-08-11 | 6047 |
| GLD | non_equity | 2004-11-18 | 2026-08-11 | 5465 |
| SLV | non_equity | 2006-04-28 | 2026-08-11 | 5103 |
| DBC | non_equity | 2006-02-06 | 2026-08-11 | 5160 |
| BIL | non_equity | 2007-05-30 | 2026-08-11 | 4831 |
| VEA | non_equity | 2007-07-26 | 2026-08-11 | 4791 |
| VWO | non_equity | 2005-03-10 | 2026-08-11 | 5389 |
| EFA | non_equity | 2001-08-27 | 2026-08-11 | 6275 |
| BND | non_equity | 2007-04-10 | 2026-08-11 | 4866 |
| AGG | non_equity | 2003-09-29 | 2026-08-11 | 5753 |
| QLD | leveraged | 2006-06-21 | 2026-08-11 | 5066 |
| TQQQ | leveraged | 2010-02-11 | 2026-08-11 | 4149 |
| SOXL | leveraged | 2010-03-11 | **2026-08-10** | 4129 |
| SSO | leveraged | 2006-06-21 | 2026-08-11 | 5066 |
| UPRO | leveraged | 2009-06-25 | 2026-08-11 | 4308 |
| NVDA | singles | 1999-01-22 | **2026-08-10** | 6929 |
| AMZN | singles | 1997-05-15 | **2026-08-10** | 7354 |
| AAPL | singles | 1980-12-12 | 2026-08-11 | 11507 |
| MSFT | singles | 1986-03-13 | 2026-08-11 | 10181 |
| GOOGL | singles | 2004-08-19 | 2026-08-11 | 5529 |
| META | singles | 2012-05-18 | 2026-08-11 | 3577 |
| TSLA | singles | 2010-06-29 | 2026-08-11 | 4054 |

**Short-history check.** This study's floor for supporting the holdout math at all is ~1,000 daily
bars. The thinnest candidate in the full 56-symbol universe is **QQQM at 1,463 bars** — comfortably
above the floor. **No candidate in this universe needed a DRAM-style refusal.**

**Resolved: 56 / 56. Refused: 0 / 56.**

### The four refusals from the first pass — transient infrastructure failures, not data-existence refusals

The first pass through this universe (52/56 resolved) reported four symbols — QUAL, MTUM, VLUE, VWO —
as refused, each with:

```
IOException: IO Error: Cannot open file "...\data\store\analytics.duckdb": The process cannot
access the file because it is being used by another process.
```

one instance additionally naming a second PID holding the file open. At the time, this report
correctly identified the cause as Windows file-lock contention on the shared production
`analytics.duckdb` — this study runs five analyst streams in parallel against the same cache, and
DuckDB's file lock is exclusive per writer — and explicitly declined to treat it as a data-existence
refusal (FONO's `SymbolNotFoundWithContext`) or a short-history refusal (DRAM's `HoldoutUnavailable`).

**That diagnosis has since been confirmed.** With the parallel streams finished, a serial re-fetch of
the same four symbols resolved all of them without incident:

```
QUAL: 3286 bars, 2013-07-18 -> 2026-08-11
MTUM: 3349 bars, 2013-04-18 -> 2026-08-11
VLUE: 3349 bars, 2013-04-18 -> 2026-08-11
VWO:  5389 bars, 2005-03-10 -> 2026-08-11
```

All four clear the ~1,000-bar study floor comfortably (thinnest: QUAL at 3,286 bars). This report's
tables below now include all 56 candidates.

**The finding worth keeping, stated plainly:** for the roughly twenty minutes this study's five
parallel streams were all hitting the shared production DuckDB store, **a symbol that genuinely
exists and has ten-plus years of history was indistinguishable, from this script's point of view, from
a symbol that does not exist at all.** Both surface as a raised exception from `bars_frame` with no
partial data returned. The exception *type* differs — `IOException` (a DuckDB engine error wrapped by
whatever layer raises it) versus `SymbolNotFoundWithContext` (a typed, documented, terminal provider
error) — so a caller that branches on exception type rather than string-matching the message could in
principle tell them apart. But a caller — or a person — reading only the printed message, as this
script did on the first pass, cannot: both read as "this script could not get bars for this symbol,"
full stop. **A concurrency failure inside the app's own storage layer can masquerade as "this ticker
doesn't exist" to anything downstream that doesn't specifically check for it**, which is a materially
different, and worse, failure mode than either of the two refusal types this study's house style
(FONO, DRAM) had names for going in. This is reported here rather than fixed, per the study's standing
instruction not to modify application source; it is a finding about the app's concurrent-access
behaviour under this study's own five-parallel-stream design, surfaced by running the study the way it
was designed to run.

### Data staleness: a one-session offset inside the 56-symbol panel — and a correction to the premise it was flagged under

The coordinator asked whether the four just-recovered symbols (QUAL, MTUM, VLUE, VWO) carry a last bar
of 2026-08-11 while the rest of the cache sits at 2026-08-10, and whether that affects any trailing-
window number. **Checked directly against `data/universe.json`'s coverage block, the premise is
backwards.** All four recovered symbols are current — `last: "2026-08-11"` — matching 51 of the 56
symbols in the panel. It is a *different* set of five symbols that lag one session behind at
`2026-08-10`: **SOXX, IGV, SOXL, NVDA, AMZN** (unrelated to the refusal incident; these five were
never refused, on either pass — they simply had not been re-synced to the newest session at whatever
moment each was last fetched). Restated precisely: 51/56 symbols end 2026-08-11, 5/56
(SOXX, IGV, SOXL, NVDA, AMZN) end 2026-08-10.

**Does it affect any computed number?** Checked against what each figure actually uses:

- **CAGR (full and 10y), annualised volatility, Sharpe, max drawdown, worst-episode depth/dates,
  recovery time** — all computed from full multi-thousand-bar histories. One missing session at the
  tail of a 2,725–11,507-bar series is not detectable at the reported precision. No effect.
- **ATR%, 20-day realised vol, average absolute daily move, autocorrelation, variance ratio (both k=5
  and k=20, trailing 3y)** — trailing-3y windows hold ~750 bars; one symbol running one session behind
  its peers means its own trailing-3y window is bars `[t-751, t-1]` instead of `[t-750, t]` relative to
  the panel's newest date — a one-bar shift with no material effect on a 750-observation rolling
  statistic. No effect worth reporting on any ranked-table position (checked: none of the five lagged
  symbols' ranks in either ranked table are close enough to a neighbour for a one-bar shift to matter).
- **Correlation matrix** — this is the one place the offset is mechanically real: any pair involving
  one of the five lagged symbols (SOXX, IGV, SOXL, NVDA, AMZN) loses the 2026-08-11 row on the pairwise
  `dropna` `.corr()` computation (749 paired observations instead of 750 for those columns; the
  `correlation_n_rows: 750` reported above is the panel-wide row count before pairwise dropna, not the
  realised n for every pair). A one-row difference out of ~750 moves a Pearson correlation coefficient
  by a magnitude far below the precision reported (3 decimal places) — not large enough to have created
  or erased any pair in the |corr| > 0.90 near-duplicate list below.
- **Leveraged decay comparison (Part C)** — SOXL is one of the five lagged symbols, and its decay
  windows compare it against SOXX (also lagged, to the same 2026-08-10 date). The comparison method
  deliberately queries the underlying over the *leveraged fund's own realised end date*
  (`leveraged_decay()` in `scripts/universe.py`), not a fixed calendar date — so SOXL vs. SOXX is
  internally consistent (both end 2026-08-10) and unaffected by the offset. QLD/TQQQ/SSO/UPRO and
  their underlyings (QQQ, SPY) all sit at 2026-08-11 — also consistent. No cross-day mismatch exists
  anywhere in the decay table.
- **The "current drawdown" column** in the long-horizon table below is the one figure that is genuinely
  one session stale for SOXX, IGV, SOXL, NVDA, and AMZN relative to the other 51 symbols — each is
  reported honestly as of its own last stored session, but a reader comparing "current DD" across the
  full panel should know five of those readings are dated one trading day earlier than the rest.

**In short: the coordinator's specific premise (the four recovered symbols being the stale ones) does
not hold — checked and corrected above — but the underlying question was worth asking, and the actual
one-day-lagged set (a different five symbols) has a real, if minor and fully bounded, effect on one
column (current drawdown, for those five) and a negligible one on the correlation matrix's realised
per-pair sample size. It does not change any ranking, any near-duplicate pair, or any decay-table
figure.**

---

## Part B — characterisation, not recommendation

### Methodology (what was reused from the app vs. computed here)

- **CAGR, annualised volatility, Sharpe(rf=0), total return** — the frictionless buy-and-hold half of
  `app.backtest.strategy.backtest` (`app.backtest.strategy._buy_hold` + `app.backtest.metrics.compute`),
  reached via `quantlab.strategy_backtest` with a dummy always-true-entry/never-true-exit idea whose
  own "strategy" half is discarded. This is the identical function the app itself uses for
  buy-and-hold anywhere in the codebase — not reimplemented here.
- **Max drawdown, worst episode, recovery, current drawdown** — `quantlab.drawdown_profile` →
  `app.backtest.drawdown.profile`, close basis, identical to the prior study's usage. "Recovery" below
  is **calendar days from the episode's trough to its recovery date** (not peak-to-recovery, which is
  what the prior QQQ/SOXX/IGV report quoted in years — the two are not the same number, though they
  are close for episodes with a short peak-to-trough leg).
- **% days above 200-day SMA** — plain `close.rolling(200).mean()` comparison, same SMA the rule DSL's
  `sma(200)` computes.
- **ATR%** — `app.indicators.volatility.atr(bars, period=14) / close`, the identical function the DSL's
  `atr(14)` calls.
- **20-day realised volatility, average absolute daily move, 1-day autocorrelation** — plain pandas on
  daily log returns (`autocorr(lag=1)`, rolling 20-day std annualised by `sqrt(252)`). Not in the app;
  computed here and documented in `scripts/universe.py`.
- **Variance ratio at k=5, k=20** — Var(k-day return) / (k × Var(1-day return)), on **non-overlapping**
  k-day blocks (not the more common overlapping-window estimator). Non-overlapping blocks avoid the
  bias overlapping sums introduce (each pair of adjacent overlapping windows shares k-1 of k
  observations, biasing the ratio toward 1) at the cost of fewer independent blocks — reported
  alongside every ratio as `n_blocks`. No p-value is attached to any variance ratio or autocorrelation
  figure — these are descriptive, not hypothesis tests.
- **Correlation matrix** — Pearson correlation of trailing-3y daily log returns, pairwise, `min_periods=200`.

### Long-horizon character (full history)

| symbol | first bar | bars | CAGR full | CAGR 10y | vol (ann) | Sharpe(rf=0) | max DD | worst episode | recovery | current DD | %days>SMA200 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY | 1993-01-29 | 8440 | 8.9% | 13.5% | 18.6% | 0.55 | -56.5% | 2007-10-09→2009-03-09 | 1466d | -0.3% (2d) | 74.9% |
| VOO | 2010-09-09 | 4004 | 13.0% | 13.5% | 17.0% | 0.80 | -34.3% | 2020-02-19→2020-03-23 | 148d | -0.3% (2d) | 82.6% |
| VTI | 2001-06-15 | 6325 | 8.0% | 13.0% | 19.1% | 0.50 | -56.7% | 2007-10-09→2009-03-09 | 1425d | -0.3% (2d) | 75.1% |
| QQQ | 1999-03-10 | 6898 | 10.1% | 19.9% | 26.9% | 0.49 | -83.0% | 2000-03-27→2002-10-09 | 5081d | -11.3% (48d) | 73.1% |
| QQQM | 2020-10-13 | 1463 | 16.6% | 16.6% | 22.3% | 0.80 | -35.6% | 2021-11-19→2022-12-28 | 350d | -11.3% (48d) | 75.4% |
| IWM | 2000-05-26 | 6590 | 7.4% | 9.4% | 23.9% | 0.42 | -59.5% | 2007-07-13→2009-03-09 | 757d | -1.1% (5d) | 67.3% |
| DIA | 1998-01-20 | 7184 | 7.0% | 11.2% | 18.5% | 0.46 | -53.8% | 2007-10-09→2009-03-09 | 1457d | -1.0% (4d) | 73.0% |
| RSP | 2003-05-01 | 5857 | 9.7% | 10.2% | 19.8% | 0.57 | -60.9% | 2007-06-04→2009-03-09 | 1283d | at high | 76.7% |
| XLK | 1998-12-22 | 6950 | 9.2% | 23.0% | 26.0% | 0.47 | -82.0% | 2000-03-27→2002-10-09 | 5525d | -16.0% (48d) | 71.8% |
| XLF | 1998-12-22 | 6950 | 4.1% | 11.5% | 28.3% | 0.28 | -83.7% | 2007-06-01→2009-03-06 | 3938d | -0.7% (4d) | 65.4% |
| XLE | 1998-12-22 | 6950 | 6.2% | 5.9% | 28.6% | 0.35 | -76.7% | 2014-06-23→2020-03-23 | 2139d | -15.6% (93d) | 62.6% |
| XLV | 1998-12-22 | 6950 | 7.1% | 8.5% | 17.9% | 0.47 | -40.6% | 2007-12-10→2009-03-09 | 1100d | -0.3% (1d) | 68.5% |
| XLY | 1998-12-22 | 6950 | 8.4% | 11.3% | 22.7% | 0.47 | -60.1% | 2007-06-04→2009-03-09 | 779d | -15.1% (145d) | 72.4% |
| XLP | 1998-12-22 | 6950 | 4.3% | 4.5% | 15.3% | 0.35 | -37.8% | 2000-12-28→2003-03-10 | 1724d | -9.9% (113d) | 71.2% |
| XLU | 1998-12-22 | 6950 | 4.0% | 5.8% | 19.3% | 0.30 | -55.7% | 2000-12-13→2002-10-09 | 1412d | -9.7% (113d) | 67.6% |
| XLI | 1998-12-22 | 6950 | 7.8% | 12.2% | 21.1% | 0.46 | -63.3% | 2007-10-09→2009-03-09 | 1463d | -1.0% (5d) | 71.6% |
| XLB | 1998-12-22 | 6950 | 6.1% | 8.1% | 23.6% | 0.37 | -60.7% | 2008-05-20→2009-03-02 | 1761d | -12.4% (124d) | 67.3% |
| XLC | 2018-06-19 | 2047 | 10.2% | 10.2% | 22.2% | 0.55 | -47.2% | 2021-09-01→2022-11-03 | 602d | -12.2% (132d) | 77.0% |
| XLRE | 2015-10-08 | 2725 | 3.6% | 2.8% | 20.4% | 0.27 | -39.3% | 2020-02-21→2020-03-23 | 393d | -37.9% (1155d) | 59.3% |
| SOXX† | 2001-07-13 | 6305 | 13.2% | 31.1% | 33.6% | 0.54 | -70.5% | 2001-08-02→2008-11-20 | 1946d | -29.0% (34d) | 67.6% |
| SMH | 2000-06-05 | 6585 | 9.8% | 33.3% | 35.0% | 0.44 | -85.9% | 2000-06-21→2008-11-20 | 3283d | -24.6% (35d) | 67.2% |
| IGV† | 2001-07-17 | 6303 | 10.0% | 16.8% | 26.5% | 0.49 | -61.5% | 2001-07-17→2002-10-07 | 1823d | -36.6% (221d) | 74.7% |
| XBI | 2006-02-06 | 5160 | 11.7% | 9.6% | 30.6% | 0.51 | -63.9% | 2021-02-08→2022-05-11 | still underwater | -63.9% (1382d) | 67.0% |
| ITA | 2006-05-05 | 5098 | 11.9% | 14.4% | 22.8% | 0.61 | -60.2% | 2007-10-09→2009-03-09 | 1458d | -0.9% (4d) | 75.8% |
| ARKK | 2014-10-31 | 2960 | 12.4% | 14.2% | 38.3% | 0.50 | -81.1% | 2021-02-12→2022-12-28 | still underwater | -81.1% (1378d) | 61.8% |
| USMV | 2011-10-20 | 3722 | 9.7% | 8.1% | 13.5% | 0.76 | -33.1% | 2020-02-14→2020-03-23 | 371d | -0.1% (1d) | 85.3% |
| SPLV | 2011-05-05 | 3839 | 7.5% | 6.0% | 14.5% | 0.57 | -36.6% | 2020-02-14→2020-03-23 | 471d | -3.0% (10d) | 81.4% |
| VIG | 2006-05-02 | 5101 | 8.2% | 11.1% | 17.0% | 0.55 | -48.2% | 2007-10-09→2009-03-09 | 1256d | -0.1% (1d) | 77.4% |
| SCHD | 2011-10-20 | 3722 | 10.0% | 9.2% | 15.5% | 0.69 | -33.4% | 2020-01-23→2020-03-23 | 231d | at high | 78.1% |
| **QUAL** | 2013-07-18 | 3286 | 12.1% | 12.7% | 17.1% | 0.75 | -34.1% | 2020-02-19→2020-03-23 | 154d | -0.3% (1d) | 82.2% |
| **MTUM** | 2013-04-18 | 3349 | 14.5% | 14.8% | 20.2% | 0.77 | -34.1% | 2020-02-19→2020-03-23 | 107d | -18.0% (35d) | 80.8% |
| **VLUE** | 2013-04-18 | 3349 | 11.0% | 11.8% | 18.8% | 0.65 | -39.5% | 2020-02-12→2020-03-23 | 295d | -8.0% (32d) | 69.9% |
| TLT | 2002-07-30 | 6047 | 0.0% | -5.1% | 14.3% | 0.07 | -52.2% | 2020-08-04→2026-08-10 | still underwater | -52.2% (1511d) | 49.0% |
| IEF | 2002-07-30 | 6047 | 0.5% | -1.9% | 6.9% | 0.11 | -27.7% | 2020-08-04→2023-10-19 | still underwater | -27.7% (1511d) | 51.8% |
| SHY | 2002-07-30 | 6047 | 0.0% | -0.4% | 1.6% | 0.03 | -7.2% | 2020-04-30→2023-03-08 | still underwater | -7.2% (1577d) | 50.6% |
| GLD | 2004-11-18 | 5465 | 10.7% | 12.1% | 18.2% | 0.65 | -45.6% | 2011-08-22→2015-12-17 | 1686d | -26.4% (133d) | 68.7% |
| SLV | 2006-04-28 | 5103 | 7.4% | 12.1% | 33.3% | 0.38 | -76.3% | 2011-04-28→2020-03-18 | 2035d | -52.3% (134d) | 55.1% |
| DBC | 2006-02-06 | 5160 | 1.1% | 7.3% | 19.4% | 0.15 | -77.4% | 2008-07-02→2020-04-27 | still underwater | -77.4% (4554d) | 52.4% |
| BIL | 2007-05-30 | 4831 | -0.0% | 0.0% | 0.8% | -0.00 | -1.4% | 2008-09-29→2023-12-18 | still underwater | -1.4% (4493d) | 38.1% |
| VEA | 2007-07-26 | 4791 | 2.2% | 6.9% | 21.6% | 0.21 | -62.9% | 2007-10-31→2009-03-09 | 4463d | -0.5% (2d) | 63.6% |
| **VWO** | 2005-03-10 | 5389 | 4.2% | 4.6% | 26.2% | 0.29 | -68.3% | 2007-10-31→2008-11-20 | 6305d | -7.1% (35d) | 62.3% |
| EFA | 2001-08-27 | 6275 | 3.8% | 6.3% | 20.9% | 0.28 | -63.2% | 2007-10-31→2009-03-09 | 5898d | -0.5% (2d) | 66.6% |
| BND | 2007-04-10 | 4866 | -0.2% | -1.5% | 5.3% | -0.01 | -24.0% | 2020-08-06→2023-10-19 | still underwater | -24.0% (1509d) | 56.2% |
| AGG | 2003-09-29 | 5753 | -0.2% | -1.4% | 5.3% | -0.02 | -23.4% | 2020-08-04→2023-10-19 | still underwater | -23.4% (1511d) | 55.7% |
| QLD * | 2006-06-21 | 5066 | 24.4% | 33.0% | 44.0% | 0.72 | -84.0% | 2007-10-31→2009-03-09 | 1277d | -22.8% (48d) | 76.4% |
| TQQQ * | 2010-02-11 | 4149 | 42.7% | 39.8% | 61.2% | 0.89 | -81.8% | 2021-11-19→2022-12-28 | 714d | -33.8% (48d) | 78.3% |
| SOXL *† | 2010-03-11 | 4129 | 38.0% | 47.4% | 91.6% | 0.81 | -90.5% | 2021-12-27→2022-10-14 | 1274d | -69.4% (34d) | 66.7% |
| SSO * | 2006-06-21 | 5066 | 14.8% | 23.1% | 38.2% | 0.55 | -85.5% | 2007-07-13→2009-03-09 | 1750d | -0.7% (2d) | 73.8% |
| UPRO * | 2009-06-25 | 4308 | 32.8% | 28.6% | 51.2% | 0.82 | -76.8% | 2020-02-19→2020-03-23 | 291d | -1.1% (2d) | 76.9% |
| NVDA† | 1999-01-22 | 6929 | 36.2% | 64.1% | 59.2% | 0.82 | -89.7% | 2002-01-03→2002-10-09 | 1496d | -19.4% (59d) | 71.6% |
| AMZN† | 1997-05-15 | 7354 | 31.3% | 22.0% | 55.0% | 0.77 | -94.4% | 1999-12-10→2001-09-28 | 2947d | -4.1% (5d) | 68.2% |
| AAPL | 1980-12-12 | 11507 | 18.7% | 27.4% | 43.7% | 0.61 | -82.2% | 1991-04-02→1997-12-23 | 619d | -10.8% (10d) | 65.8% |
| MSFT | 1986-03-13 | 10181 | 23.6% | 24.3% | 33.3% | 0.80 | -74.6% | 1999-12-27→2009-03-09 | 2783d | -34.9% (196d) | 71.4% |
| GOOGL | 2004-08-19 | 5529 | 25.1% | 24.1% | 30.8% | 0.88 | -65.3% | 2007-11-06→2008-11-24 | 1400d | -21.1% (61d) | 75.6% |
| META | 2012-05-18 | 3577 | 21.8% | 17.2% | 39.8% | 0.69 | -76.7% | 2021-09-07→2022-11-03 | 442d | -33.5% (250d) | 77.3% |
| TSLA | 2010-06-29 | 4054 | 38.7% | 36.5% | 57.4% | 0.86 | -73.6% | 2021-11-04→2023-01-03 | 708d | -39.1% (162d) | 63.4% |

`*` = daily-reset leveraged product — see Part C before reading its CAGR/vol/Sharpe as if it were an
unlevered instrument's. `†` = one of the five symbols whose stored history ends 2026-08-10, one
session behind the panel's other 51 symbols (2026-08-11) — see the staleness note in Part A; only the
**current DD** column for these five should be read as dated one session earlier than the rest of the
table. **Bold** symbols are the three newly recovered in this re-run.

**Cross-check against the prior study.** QQQ's worst episode here (2000-03-27→2002-10-09, -83.0%,
recovery 5081 calendar days from trough) matches the prior QQQ/SOXX/IGV study's finding of the same
episode, same depth, "recovered 2016-09-06" (2002-10-09 + 5081 days ≈ 2016-09-04, the small gap is the
peak-to-recovery vs. trough-to-recovery framing difference noted above) — the same
`app.backtest.drawdown.profile` call, same answer, different framing.

### Swing character (full history vs. trailing 3 years)

| symbol | ATR%/close (3y) | ATR%/close (full) | 20d realised vol (3y, ann) | avg\|daily move\| (3y) | autocorr 1d (3y) | VR-5 (3y) | VR-20 (3y) | VR-5 n_blocks | VR-20 n_blocks |
|---|---|---|---|---|---|---|---|---|---|
| SPY | 1.16% | 1.39% | 13.7% | 0.66% | -0.064 | 0.751 | 0.762 | 150 | 37 |
| VOO | 1.15% | 1.21% | 13.6% | 0.66% | -0.033 | 0.793 | 0.801 | 150 | 37 |
| VTI | 1.18% | 1.39% | 14.0% | 0.68% | -0.046 | 0.769 | 0.761 | 150 | 37 |
| QQQ | 1.59% | 2.06% | 18.8% | 0.92% | -0.058 | 0.790 | 0.843 | 150 | 37 |
| QQQM | 1.57% | 1.75% | 18.7% | 0.92% | -0.051 | 0.800 | 0.854 | 150 | 37 |
| IWM | 1.81% | 1.91% | 20.5% | 1.01% | -0.032 | 0.836 | 0.682 | 150 | 37 |
| DIA | 1.11% | 1.37% | 12.6% | 0.61% | -0.009 | 0.785 | 0.583 | 150 | 37 |
| RSP | 1.14% | 1.40% | 12.9% | 0.63% | -0.033 | 0.807 | 0.767 | 150 | 37 |
| XLK | 1.92% | 1.99% | 23.0% | 1.13% | -0.051 | 0.842 | 0.923 | 150 | 37 |
| XLF | 1.34% | 1.98% | 15.0% | 0.72% | 0.028 | 0.892 | 0.773 | 150 | 37 |
| XLE | 1.90% | 2.25% | 20.6% | 1.02% | 0.039 | 0.898 | 0.886 | 150 | 37 |
| XLV | 1.25% | 1.44% | 13.8% | 0.68% | -0.006 | 0.910 | 0.760 | 150 | 37 |
| XLY | 1.69% | 1.75% | 19.8% | 0.98% | -0.046 | 0.787 | 0.726 | 150 | 37 |
| XLP | 1.14% | 1.27% | 12.4% | 0.62% | -0.036 | 0.816 | 0.805 | 150 | 37 |
| XLU | 1.51% | 1.61% | 16.1% | 0.78% | -0.028 | 0.872 | 0.859 | 150 | 37 |
| XLI | 1.38% | 1.64% | 15.5% | 0.77% | -0.023 | 0.666 | 0.761 | 150 | 37 |
| XLB | 1.44% | 1.87% | 16.3% | 0.81% | -0.027 | 0.751 | 0.719 | 150 | 37 |
| XLC | 1.39% | 1.70% | 15.6% | 0.77% | -0.032 | 0.774 | 0.836 | 150 | 37 |
| XLRE | 1.48% | 1.58% | 16.3% | 0.79% | -0.029 | 0.898 | 0.767 | 150 | 37 |
| SOXX | 2.93% | 2.55% | 36.2% | 1.78% | -0.098 | 0.742 | 0.891 | 149 | 37 |
| SMH | 2.80% | 2.74% | 34.4% | 1.69% | -0.084 | 0.753 | 0.844 | 150 | 37 |
| IGV | 2.12% | 2.01% | 24.4% | 1.21% | 0.071 | 1.042 | 1.073 | 149 | 37 |
| XBI | 2.48% | 2.60% | 26.9% | 1.35% | -0.052 | 0.801 | 0.738 | 150 | 37 |
| ITA | 1.65% | 1.70% | 18.6% | 0.90% | 0.019 | 0.720 | 0.717 | 150 | 37 |
| ARKK | 3.28% | 2.95% | 37.9% | 1.91% | -0.042 | 0.875 | 0.816 | 150 | 37 |
| USMV | 0.86% | 0.98% | 9.8% | 0.48% | -0.005 | 0.886 | 0.560 | 150 | 37 |
| SPLV | 0.97% | 1.05% | 10.8% | 0.53% | -0.022 | 0.896 | 0.588 | 150 | 37 |
| VIG | 0.97% | 1.22% | 11.2% | 0.55% | -0.030 | 0.779 | 0.660 | 150 | 37 |
| SCHD | 1.11% | 1.13% | 12.5% | 0.61% | -0.021 | 0.841 | 0.959 | 150 | 37 |
| **QUAL** | 1.14% | 1.22% | 13.4% | 0.65% | -0.045 | 0.780 | 0.748 | 150 | 37 |
| **MTUM** | 1.69% | 1.46% | 20.5% | 1.01% | -0.026 | 0.786 | 0.928 | 150 | 37 |
| **VLUE** | 1.38% | 1.29% | 16.4% | 0.82% | -0.020 | 0.833 | 1.078 | 150 | 37 |
| TLT | 1.06% | 1.09% | 13.1% | 0.66% | -0.027 | 0.872 | 0.656 | 150 | 37 |
| IEF | 0.50% | 0.52% | 6.3% | 0.32% | -0.019 | 0.854 | 0.634 | 150 | 37 |
| SHY | 0.13% | 0.12% | 1.9% | 0.09% | -0.126 | 0.766 | 0.506 | 150 | 37 |
| GLD | 1.42% | 1.34% | 19.0% | 0.93% | -0.023 | 0.734 | 0.714 | 150 | 37 |
| SLV | 2.84% | 2.41% | 37.0% | 1.79% | -0.012 | 0.821 | 0.609 | 150 | 37 |
| DBC | 1.29% | 1.55% | 16.4% | 0.82% | 0.031 | 0.928 | 0.822 | 150 | 37 |
| BIL | 0.04% | 0.05% | 1.3% | 0.03% | -0.071 | 0.789 | 0.058 | 150 | 37 |
| VEA | 1.14% | 1.44% | 14.9% | 0.73% | -0.072 | 0.739 | 0.461 | 150 | 37 |
| **VWO** | 1.17% | 1.72% | 15.7% | 0.76% | -0.047 | 0.803 | 0.516 | 150 | 37 |
| EFA | 1.12% | 1.40% | 14.6% | 0.71% | -0.043 | 0.795 | 0.473 | 150 | 37 |
| BND | 0.41% | 0.39% | 5.0% | 0.25% | -0.024 | 0.865 | 0.638 | 150 | 37 |
| AGG | 0.41% | 0.38% | 5.2% | 0.26% | -0.021 | 0.875 | 0.637 | 150 | 37 |
| QLD * | 3.14% | 3.36% | 37.5% | 1.84% | -0.051 | 0.805 | 0.875 | 150 | 37 |
| TQQQ * | 4.72% | 4.70% | 56.1% | 2.74% | -0.044 | 0.820 | 0.913 | 150 | 37 |
| SOXL * | 9.02% | 7.13% | 107.6% | 5.24% | -0.070 | 0.789 | 1.000 | 149 | 37 |
| SSO * | 2.28% | 2.72% | 27.0% | 1.30% | -0.031 | 0.802 | 0.821 | 150 | 37 |
| UPRO * | 3.41% | 3.73% | 40.5% | 1.96% | -0.024 | 0.822 | 0.855 | 150 | 37 |
| NVDA | 3.80% | 4.57% | 44.2% | 2.17% | -0.082 | 0.829 | 0.773 | 149 | 37 |
| AMZN | 2.60% | 3.97% | 30.0% | 1.45% | 0.026 | 0.879 | 0.821 | 149 | 37 |
| AAPL | 2.17% | 3.39% | 24.4% | 1.15% | 0.052 | 1.045 | 1.023 | 150 | 37 |
| MSFT | 2.04% | 2.62% | 23.4% | 1.11% | 0.019 | 1.124 | 1.023 | 150 | 37 |
| GOOGL | 2.52% | 2.38% | 29.1% | 1.39% | 0.017 | 0.955 | 0.913 | 150 | 37 |
| META | 2.91% | 2.94% | 34.5% | 1.59% | -0.036 | 0.792 | 0.919 | 150 | 37 |
| TSLA | 4.70% | 4.57% | 55.4% | 2.66% | -0.008 | 0.903 | 1.051 | 150 | 37 |

The three newly recovered factor funds sit in the unremarkable middle of this table: QUAL and VLUE
both show VR-20 near or above 1.0 (0.748 and **1.078**, the highest of any non-leveraged, non-single
instrument in the panel) — VLUE is, by this measure, trending rather than mean-reverting at the 20-day
scale over the trailing 3 years, alongside IGV, TSLA, AAPL and MSFT. MTUM's VR-20 (0.928) is close to a
random walk. VWO's numbers are unremarkable relative to the other broad-international fund, EFA — the
two are close on every column here, foreshadowing the correlation result below.

### Correlation — trailing 3 years, daily log returns

56×56 matrix (750 calendar rows in the panel; 749 for any pair including one of the five session-
lagged symbols — see Part A) is in `data/universe.json` under `correlation_matrix_3y`. **80 pairs
exceed |corr| > 0.90** (up from 65 with the 52-symbol panel — 15 new pairs, all involving QUAL or
MTUM, none involving VLUE or VWO):

| a | b | corr | why |
|---|---|---|---|
| QQQ | QQQM | +1.000 | same index, different share class |
| QLD | TQQQ | +1.000 | same underlying (QQQ), different leverage factor |
| SSO | UPRO | +1.000 | same underlying (SPY), different leverage factor |
| QQQM | QLD | +1.000 | — |
| QQQ | QLD | +0.999 | — |
| QQQM | TQQQ | +0.999 | — |
| QQQ | TQQQ | +0.999 | — |
| VOO | SSO | +0.999 | — |
| VOO | UPRO | +0.998 | — |
| SOXX | SOXL | +0.997 | leveraged/unlevered pair |
| SPY | SSO | +0.997 | — |
| SPY | VOO | +0.997 | — |
| SPY | UPRO | +0.996 | — |
| VOO | VTI | +0.995 | S&P 500 vs. total market — almost the same fund |
| VTI | SSO | +0.995 | — |
| SPY | VTI | +0.995 | — |
| VTI | UPRO | +0.994 | — |
| BND | AGG | +0.993 | the pair kept specifically to test this claim — confirmed near-identical |
| SOXX | SMH | +0.981 | both semiconductor-theme, different index construction |
| SMH | SOXL | +0.980 | — |
| IEF | BND | +0.979 | — |
| IEF | AGG | +0.978 | — |
| VEA | EFA | +0.970 | both developed-ex-US, different index vendor — near-duplicates |
| **QUAL** | **SSO** | **+0.970** | **new** — quality factor and 2x S&P 500 |
| **QUAL** | **UPRO** | **+0.969** | **new** — quality factor and 3x S&P 500 |
| **VOO** | **QUAL** | **+0.969** | **new** |
| **SPY** | **QUAL** | **+0.968** | **new** |
| QQQM | XLK | +0.966 | Nasdaq-100 vs. tech sector |
| QQQ | XLK | +0.966 | — |
| XLK | QLD | +0.966 | — |
| **VTI** | **QUAL** | **+0.966** | **new** |
| XLK | TQQQ | +0.965 | — |
| TQQQ | UPRO | +0.950 | different underlyings (QQQ vs SPY), still ~0.95 through shared mega-cap-tech beta once levered |
| QLD | UPRO | +0.949 | — |
| TQQQ | SSO | +0.949 | — |
| VOO / QQQ / QQQM / SPY / VTI cross-pairs | | 0.938–0.949 | the whole cap-weighted large/mega-cap family, unlevered and 2–3x levered, moves as essentially one factor over 3y |
| RSP | VIG | +0.935 | — |
| DIA | VIG | +0.934 | — |
| TLT | BND | +0.934 | — |
| XLK | SMH | +0.931 | — |
| TLT | AGG | +0.930 | — |
| TLT | IEF | +0.919 | — |
| VTI | VIG | +0.912 | — |
| **QQQM** | **QUAL** | **+0.911** | **new** |
| **QQQ** | **QUAL** | **+0.911** | **new** |
| **QUAL** | **QLD** | **+0.911** | **new** |
| **QUAL** | **TQQQ** | **+0.910** | **new** |
| XLK | SOXX | +0.909 | — |
| DIA | RSP | +0.907 | — |
| XLK | SOXL | +0.907 | — |
| **VIG** | **QUAL** | **+0.907** | **new** |
| **MTUM** | **QLD** | **+0.903** | **new** |
| VOO | VIG | +0.903 | — |
| **MTUM** | **TQQQ** | **+0.903** | **new** |
| **XLK** | **MTUM** | **+0.902** | **new** |
| **QQQ** | **MTUM** | **+0.902** | **new** |
| **QQQM** | **MTUM** | **+0.902** | **new** |
| VIG | SSO | +0.902 | — |
| SPY | VIG | +0.902 | — |
| SMH | QLD | +0.901 | — |
| QQQ | SMH | +0.901 | — |
| SMH | TQQQ | +0.901 | — |
| VIG | UPRO | +0.901 | — |
| QQQM | SMH | +0.901 | — |

(Full 80-pair list, all thresholded at |corr| > 0.90, is in `data/universe.json`.) **New finding from
this re-run:** QUAL (quality factor) is a near-duplicate of the broad cap-weighted large-cap family at
the 0.91–0.97 level — closer to SPY/VOO/VTI/QQQ than to VIG, the dividend-growth factor it sits next to
in the "factor/defensive" category. MTUM (momentum factor) is a milder but still real near-duplicate at
0.90–0.93. **VLUE (value factor) and VWO (emerging markets) do not appear anywhere in the >0.90 list** —
value is, in this trailing-3y window, the one factor tested here that is not simply a relabelled
large-cap-growth bet, and VWO's nearest neighbour in the panel, EFA, correlates at 0.970 (in the table
above) but nothing else reaches 0.90 with it. **Read this as:** a list that includes SPY, QQQ, QUAL and
a leveraged product together is one large-cap-growth-and-quality bet at several different sizes and
labels, not four independent ideas — the correlation result the coordinator anticipated.

### RANKED TABLE 1 — short-term swing character

**Ranking criterion, stated in full:** composite score = average of two cross-sectional ranks, computed
only over symbols with ≥1,000 bars (all 56 candidates qualify): **(a)** rank by trailing-3y mean
ATR%/close, descending — more measured daily range relative to this study's 5bps-each-way (10bps
round-trip) assumed cost; **(b)** rank by trailing-3y 20-day variance ratio, ascending — further below
1.0 is more mean-reverting, the behaviour this study's mean-reversion templates (`band_reversion`,
`oversold_bounce`) are built to exploit. Lower composite = ranks higher. This is a **characterisation
ranking of measured properties, not a suitability score for trading** — no cost model, no execution
simulation, and no p-value sits behind it.

| rank | symbol | ATR%(3y) | rank(ATR) | VR-20(3y) | rank(VR) | composite |
|---|---|---|---|---|---|---|
| 1 | SLV | 2.84% | 10 | 0.609 | 9 | 9.5 |
| 2 | NVDA | 3.80% | 4 | 0.773 | 29 | 16.5 |
| 3 | XBI | 2.48% | 14 | 0.738 | 20 | 17.0 |
| 4 | IWM | 1.81% | 21 | 0.682 | 15 | 18.0 |
| 5 | ARKK | 3.28% | 6 | 0.816 | 32 | 19.0 |
| 6 | ITA | 1.65% | 24 | 0.717 | 17 | 20.5 |
| 7 | XLY | 1.69% | 23 | 0.726 | 19 | 21.0 |
| 8 | VEA | 1.14% | 41 | 0.461 | 2 | 21.5 |
| 9 | VWO | 1.17% | 38 | 0.516 | 5 | 21.5 |
| 10 | UPRO * | 3.41% | 5 | 0.855 | 40 | 22.5 |
| 11 | AMZN | 2.60% | 12 | 0.821 | 33 | 22.5 |
| 12 | GLD | 1.42% | 30 | 0.714 | 16 | 23.0 |
| 13 | XLB | 1.44% | 29 | 0.719 | 18 | 23.5 |
| 14 | TQQQ * | 4.72% | 2 | 0.913 | 45 | 23.5 |
| 15 | EFA | 1.12% | 45 | 0.473 | 3 | 24.0 |
| 16 | SMH | 2.80% | 11 | 0.844 | 38 | 24.5 |
| 17 | QLD * | 3.14% | 7 | 0.875 | 42 | 24.5 |
| 18 | SSO * | 2.28% | 15 | 0.821 | 34 | 24.5 |
| 19 | SOXX | 2.93% | 8 | 0.891 | 44 | 26.0 |
| 20 | SOXL * | 9.02% | 1 | 1.000 | 51 | 26.0 |
| 21 | DIA | 1.11% | 47 | 0.583 | 7 | 27.0 |
| 22 | XLRE | 1.48% | 28 | 0.767 | 26 | 27.0 |
| 23 | XLI | 1.38% | 32 | 0.761 | 24 | 28.0 |
| 24 | META | 2.91% | 9 | 0.919 | 47 | 28.0 |
| 25 | USMV | 0.86% | 51 | 0.560 | 6 | 28.5 |
| 26 | BIL | 0.04% | 56 | 0.058 | 1 | 28.5 |
| 27 | TSLA | 4.70% | 3 | 1.051 | 54 | 28.5 |
| 28 | XLV | 1.25% | 36 | 0.760 | 22 | 29.0 |
| 29 | SPLV | 0.97% | 50 | 0.588 | 8 | 29.0 |
| 30 | SHY | 0.13% | 55 | 0.506 | 4 | 29.5 |
| 31 | GOOGL | 2.52% | 13 | 0.913 | 46 | 29.5 |
| 32 | VTI | 1.18% | 37 | 0.761 | 23 | 30.0 |
| 33 | TLT | 1.06% | 48 | 0.656 | 13 | 30.5 |
| 34 | QQQ | 1.59% | 25 | 0.843 | 37 | 31.0 |
| 35 | XLF | 1.34% | 34 | 0.773 | 28 | 31.0 |
| 36 | IEF | 0.50% | 52 | 0.634 | 10 | 31.0 |
| 37 | XLE | 1.90% | 20 | 0.886 | 43 | 31.5 |
| 38 | VIG | 0.97% | 49 | 0.660 | 14 | 31.5 |
| 39 | SPY | 1.16% | 39 | 0.762 | 25 | 32.0 |
| 40 | QUAL | 1.14% | 43 | 0.748 | 21 | 32.0 |
| 41 | AGG | 0.41% | 53 | 0.637 | 11 | 32.0 |
| 42 | QQQM | 1.57% | 26 | 0.854 | 39 | 32.5 |
| 43 | BND | 0.41% | 54 | 0.638 | 12 | 33.0 |
| 44 | XLK | 1.92% | 19 | 0.923 | 48 | 33.5 |
| 45 | XLC | 1.39% | 31 | 0.836 | 36 | 33.5 |
| 46 | XLU | 1.51% | 27 | 0.859 | 41 | 34.0 |
| 47 | AAPL | 2.17% | 16 | 1.023 | 53 | 34.5 |
| 48 | VOO | 1.15% | 40 | 0.801 | 30 | 35.0 |
| 49 | DBC | 1.29% | 35 | 0.822 | 35 | 35.0 |
| 50 | MSFT | 2.04% | 18 | 1.023 | 52 | 35.0 |
| 51 | RSP | 1.14% | 44 | 0.767 | 27 | 35.5 |
| 52 | MTUM | 1.69% | 22 | 0.928 | 49 | 35.5 |
| 53 | IGV | 2.12% | 17 | 1.073 | 55 | 36.0 |
| 54 | XLP | 1.14% | 42 | 0.805 | 31 | 36.5 |
| 55 | VLUE | 1.38% | 33 | 1.078 | 56 | 44.5 |
| 56 | SCHD | 1.11% | 46 | 0.959 | 50 | 48.0 |

**The top 5 are unchanged from the 52-symbol panel**: SLV, NVDA, XBI, IWM, ARKK. VWO enters at rank 9,
immediately behind VEA (rank 8) — the two broad-international funds land next to each other, consistent
with their near-duplicate correlation. QUAL, MTUM and VLUE settle at ranks 40, 52 and 55 respectively —
all three factor funds rank in the bottom third by this criterion, VLUE dead last but one: its VR-20 of
1.078 is the single highest (least mean-reverting) reading of any non-leveraged instrument in the
panel, which is what pins it there despite unremarkable ATR%.

### RANKED TABLE 2 — long-term holding character

**Ranking criterion, stated in full:** composite score = average of three cross-sectional ranks,
computed only over symbols with ≥1,000 bars (all 56): **(a)** rank by full-history max drawdown,
descending — shallowest drawdown first; **(b)** rank by the worst episode's trough-to-recovery time in
calendar days, ascending — fastest recovery first, a still-underwater episode ranked last of all;
**(c)** rank by full-history CAGR, descending. Lower composite = ranks higher. **This ranks by what an
investor would have had to sit through, not by what they would have earned** — CAGR is one of three
equally-weighted components, not the sort key.

| rank | symbol | max DD | rank(DD) | recovery | rank(rec) | CAGR full | rank(CAGR) | composite |
|---|---|---|---|---|---|---|---|---|
| 1 | **MTUM** | -34.1% | 9 | 107d | 1 | 14.5% | 14 | **8.00** |
| 2 | VOO | -34.3% | 10 | 148d | 2 | 13.0% | 16 | 9.33 |
| 3 | **QUAL** | -34.1% | 8 | 154d | 3 | 12.1% | 18 | **9.67** |
| 4 | QQQM | -35.6% | 11 | 350d | 7 | 16.6% | 12 | 10.00 |
| 5 | SCHD | -33.4% | 7 | 231d | 4 | 10.0% | 26 | 12.33 |
| 6 | **VLUE** | -39.5% | 15 | 295d | 6 | 11.0% | 21 | **14.00** |
| 7 | USMV | -33.1% | 6 | 371d | 8 | 9.7% | 29 | 14.33 |
| 8 | XLC | -47.2% | 18 | 602d | 12 | 10.2% | 23 | 17.67 |
| 9 | UPRO * | -76.8% | 43 | 291d | 5 | 32.8% | 5 | 17.67 |
| 10 | TSLA | -73.6% | 38 | 708d | 14 | 38.7% | 2 | 18.00 |
| 11 | SPLV | -36.6% | 12 | 471d | 11 | 7.5% | 36 | 19.67 |
| 12 | TQQQ * | -81.8% | 46 | 714d | 15 | 42.7% | 1 | 20.67 |
| 13 | META | -76.7% | 42 | 442d | 10 | 21.8% | 10 | 20.67 |
| 14 | GOOGL | -65.3% | 35 | 1400d | 23 | 25.1% | 7 | 21.67 |
| 15 | GLD | -45.6% | 17 | 1686d | 31 | 10.7% | 22 | 23.33 |
| 16 | XLRE | -39.3% | 14 | 393d | 9 | 3.6% | 48 | 23.67 |
| 17 | VIG | -48.2% | 19 | 1256d | 19 | 8.2% | 33 | 23.67 |
| 18 | AAPL | -82.2% | 48 | 619d | 13 | 18.7% | 11 | 24.00 |
| 19 | XLV | -40.6% | 16 | 1100d | 18 | 7.1% | 39 | 24.33 |
| 20 | ITA | -60.2% | 27 | 1458d | 27 | 11.9% | 19 | 24.33 |
| ... | (36 more rows, full ranking in `data/universe.json`) | | | | | | | |
| 56 | DBC | -77.4% | 44 | still underwater | 53 | 1.1% | 50 | 49.00 |

**This is the headline change from the 52-symbol panel.** The previous top 5 (VOO, QQQM, SCHD, USMV,
XLC) is now displaced at the very top: **MTUM ranks 1st, QUAL 3rd, and VLUE 6th** — all three
newly-recovered factor funds land in the new top 6, exactly the outcome the coordinator anticipated.
USMV drops from 4th to 7th and XLC from 5th to 8th, not because either got worse (their own figures are
unchanged) but because three funds with shallower max drawdowns and/or faster recoveries and
competitive CAGRs pushed in ahead of them. **Why MTUM and QUAL rank where they do, mechanically**: both
share the 2011–2013-era inception the rest of this "shallow drawdown" cluster (VOO, QQQM, SCHD, USMV)
also has — none of MTUM/QUAL/VLUE/VOO/QQQM/SCHD/USMV have a stored bar during either the dot-com crash
or the 2008 financial crisis, this universe's two deepest broad-market drawdowns. Their COVID-crash
depth (all four factor funds: -33% to -40%) and fast recovery (107–371 days) is a real, correctly
measured property of their *stored* history — but that stored history simply does not include the two
episodes that make QQQ (43rd of 56) and the sector ETFs with pre-2008 histories rank so far down this
table. A reader using this table to compare "how bad could it get" across symbols needs to know some
entries have 25+ years of exposure to test that question and others have 13–16.

---

## Part C — the caveats that make this honest

### Leveraged decay, quantified rather than asserted

`app.thesis.author.CATALOGUE` has one leveraged-only template, `decay_avoidance`
(`close > sma(200)` entry, `close < sma(200)` exit, horizon 60, `leveraged_only=True`), which the loop
would propose automatically for any symbol in `app.thesis.instruments.REGISTRY`. **That registry maps
TQQQ→QQQ (3x), SOXL→SOXX (3x), and UPRO→SPY (3x), but it does not contain QLD or SSO** (the 2x
products) — confirmed directly against `instruments.lookup()`:

| symbol | factor | in `instruments.REGISTRY` | app's mapped underlying |
|---|---|---|---|
| QLD | 2.0x QQQ | **No** | — |
| TQQQ | 3.0x QQQ | Yes | QQQ |
| SOXL | 3.0x SOXX | Yes | SOXX |
| SSO | 2.0x SPY | **No** | — |
| UPRO | 3.0x SPY | Yes | SPY |

**This means the note's own named leveraged pick, QLD, is invisible to the app's automatic
decay-avoidance guard** (`app.thesis.instruments`'s own docstring: "the person most likely to forget
is the one most likely to be fooled" — the guard cannot fire for a symbol it does not know is
leveraged). This is an application gap, reported per instruction, not fixed. (Unaffected by this
re-run — none of the five leveraged products or their underlyings were among the four recovered
symbols.)

**The measured comparison** (leveraged fund's realised return vs. `k ×` the underlying's, identical
calendar window, both read from this app's own bars — SOXL's own history ends 2026-08-10, one session
behind SSO/UPRO/QLD/TQQQ; the comparison method queries each underlying over the leveraged fund's own
realised end date, so SOXL vs. SOXX stays internally consistent despite the offset, see Part A):

| symbol | window | leveraged return | underlying return | k × underlying | gap |
|---|---|---|---|---|---|
| QLD (2x QQQ) | trailing 1y | +44.6% | +25.4% | +50.8% | -6.2pp |
| QLD | trailing 3y | +184.1% | +94.0% | +188.0% | -3.8pp |
| QLD | trailing 5y | +136.3% | +95.5% | +191.0% | **-54.7pp** |
| QLD | since inception (2006-06-21) | +7959.1% | +1757.4% | +3514.8% | **+4444.3pp** |
| TQQQ (3x QQQ) | trailing 1y | +60.0% | +25.4% | +76.3% | -16.3pp |
| TQQQ | trailing 3y | +261.8% | +94.0% | +282.0% | -20.2pp |
| TQQQ | trailing 5y | +115.2% | +95.5% | +286.4% | **-171.2pp** |
| TQQQ | since inception (2010-02-11) | +33680.9% | +1545.2% | +4635.5% | **+29045.4pp** |
| SOXL (3x SOXX) | trailing 1y | +407.6% | +118.4% | +355.2% | +52.5pp |
| SOXL | trailing 3y | +466.9% | +217.2% | +651.5% | **-184.6pp** |
| SOXL | trailing 5y | +205.0% | +251.1% | +753.3% | **-548.3pp** |
| SOXL | since inception (2010-03-11) | +19582.1% | +3192.2% | +9576.7% | +10005.4pp |
| SSO (2x SPY) | trailing 1y | +38.6% | +21.2% | +42.3% | -3.7pp |
| SSO | trailing 3y | +141.5% | +72.0% | +143.9% | -2.4pp |
| SSO | trailing 5y | +121.4% | +73.1% | +146.2% | -24.8pp |
| SSO | since inception (2006-06-21) | +1492.4% | +516.4% | +1032.8% | +459.6pp |
| UPRO (3x SPY) | trailing 1y | +56.4% | +21.2% | +63.5% | -7.1pp |
| UPRO | trailing 3y | +219.1% | +72.0% | +215.9% | +3.2pp |
| UPRO | trailing 5y | +142.2% | +73.1% | +219.4% | -77.1pp |
| UPRO | since inception (2009-06-25) | +12621.1% | +736.8% | +2210.5% | -10410.6pp |

**Read this carefully — the gap runs both directions, and "decay" alone is the wrong single word for
it.** Over the shorter, choppier windows (1y, 3y, and especially 5y — a window that includes 2022's
sideways/declining semiconductor and tech markets), every leveraged product here fell short of `k ×`
its underlying's cumulative return, by tens to hundreds of percentage points (SOXL trailing-5y: realised
+205.0% against a naive expectation of +753.3%, a 548-point gap). This is the decay the app's
`instruments.py` docstring describes. But over the multi-decade "since inception" windows, several of
these products **exceeded** `k ×` the underlying by an enormous margin (QLD: +7959% realised vs.
+3515% naive; TQQQ: +33681% vs. +4636%) — daily-reset compounding is convex in a sustained uptrend, so
a leveraged product can out-compound the naive multiple over a long enough one-directional run, not
only decay against it. **Both directions are the same mechanism** (path-dependent daily compounding),
and the sign of the gap depends entirely on the shape of the path the underlying happened to take
during that specific window — not on anything about the leveraged product being under- or
over-performing "as expected."

**The worst-drawdown-episode comparison makes the mechanism visible in a way percentages can hide.**
Over each leveraged product's own worst historical episode, the "`k × underlying`" arithmetic baseline
frequently falls **below -100%** — a mathematically impossible fund return (SOXL's worst episode,
2021-12-27→2022-10-14: SOXX itself fell -46.2%, so the naive 3x expectation is -138.7%, which no fund
can actually register, since a daily-reset product's NAV compounds toward zero and cannot go negative).
SOXL's *actual* loss over those same dates was -90.5% — catastrophic, and consistent with the fund's
own recorded max drawdown (-90.5%, matching the long-horizon table above), but not the same statement
as "-138.7%," which cannot happen to any fund. Comparing a leveraged product's real drawdown against
the linear-scaling arithmetic during its worst episode understates how badly it actually did (because
the arithmetic baseline is unphysical, not because the fund somehow beat expectations) — this is the
single clearest illustration in this dataset of why "`k×` the index" is the wrong mental model for a
daily-reset product's multi-day behaviour, in either direction.

Full per-window detail for all five products (including exact start/end dates used) is in
`data/universe.json` under `leveraged_decay`.

### Survivorship

The 7 single names in this universe (NVDA, AMZN, AAPL, MSFT, GOOGL, META, TSLA) were chosen by the
declared rule — "largest US-listed companies by well-known mega-cap index membership as of this run
date" — which is, concretely, **a list of today's winners assembled with the benefit of knowing they
are today's winners.** A single-stock universe built this way cannot show what a typical, or a failed,
large-cap holding looked like, because a name that fell out of the index (or out of business) since its
2000s or 2010s peak was never a candidate for this list in the first place. The sector and theme ETFs
carry a milder version of the same bias: SOXX, IGV, SMH, XBI, ARKK etc. are each measured on their
*current* constituents' combined history, and constituent turnover inside each fund over its multi-year
life is not adjusted for or visible in this report. **The factor funds (QUAL, MTUM, VLUE) recovered in
this re-run carry a related but distinct bias worth naming explicitly**: their entire stored history
(2013-04 onward, 13 years) sits inside one long secular bull market for US large-cap equity — none of
the three, nor USMV, VOO, QQQM, or SCHD, has ever been tested by this app's stored data against a
2000-2002 or 2008-2009-style event. Their strong showing in Ranked Table 2 is a measurement of "how did
this fund do in the market regime it has actually existed in," not "how would this fund do in a repeat
of 2008" — this study's data cannot answer the second question for any of these seven symbols.

### Fees, liquidity, tracking — not in this dataset

Expense ratios, bid-ask spreads, and index-tracking error are not fields this app's bar store carries,
and none of the return or CAGR figures above are fee-adjusted (they are computed directly from stored
close prices, which for these funds are typically NAV-tracking closes, not fee-netted total-return
series in every case). **For a swing strategy assessed at this study's 5bps-each-way (10bps round-trip)
assumed cost, a real bid-ask spread wider than that assumption — plausible for lower-volume names such
as ITA, XLRE, QUAL, or VLUE relative to SPY or QQQ, though this dataset has no volume/liquidity field to
confirm it — could exceed the entire modelled edge on its own**, before a single dollar of expense
ratio is counted. This report cannot rank instruments by liquidity because it has no liquidity data;
that is a gap, not a zero.

### Short history

Confirmed above: **all 56 candidates clear the ~1,000-bar floor** this study's holdout math needs
(thinnest: QQQM at 1,463 bars, holdout of 366 sessions against a 250-session minimum; the three
newly-recovered factor funds are all above 3,000 bars). No DRAM-style refusal applies anywhere in this
universe. The refusal incident affecting QUAL/MTUM/VLUE/VWO on the first pass was a transient
infrastructure failure, not a short-history or data-existence one — see Part A, including the finding
that it was indistinguishable from a genuine missing-ticker refusal without inspecting the exception
type.

---

## What this cannot tell you

- **This is not a rule-testing study.** No hypothesis was pre-registered, no BH correction family was
  declared, and nothing here carries a p-value or a q-value. The two ranked tables are composite
  rankings of measured descriptive statistics, stated in full in each table's caption — they answer
  "what did this instrument's history look like," not "does a rule work on it." Whether any of the
  swing-shaped properties above (variance ratio, ATR%, autocorrelation) actually translate into an
  edge net of costs is exactly what the family-tested streams of this study (using `run_family`) exist
  to check, on the fixed primary/replication universe — this stream does not repeat that work and does
  not extend its conclusions to the wider candidate list here.
- **One historical path, overlapping regimes.** Every statistic above, including the trailing-3y ones,
  is drawn from one realised sequence of macro events. "Trailing 3y" for all 56 symbols is the *same*
  3 years (2023-08 to 2026-08) — not 56 independent 3-year samples, one shared one. A finding that
  many symbols show a mean-reverting variance ratio over this specific trailing 3 years is one
  observation about one recent regime, not 56.
- **Correlation is trailing-3y only.** The near-duplicate pairs listed are a property of the last
  three years' co-movement; two funds that correlate at 0.95 now could diverge in a future regime
  where their underlying construction differences (equal- vs. cap-weight, price- vs. cap-weight,
  index-vendor differences) matter more than they have recently.
- **Survivorship, stated concretely above** for the single-name list, the ETFs' constituent turnover,
  and — new in this re-run — the factor funds' and several core funds' shared blind spot for
  2000-2002 and 2008-2009.
- **No fee, spread, or liquidity data**, stated concretely above — this is a genuine blind spot in the
  underlying dataset, not a decision to omit it.
- **Ranking artifacts from unequal history length**, illustrated concretely in Ranked Table 2's
  discussion: seven of the top eight symbols on that table share a post-2011 inception and have never
  been measured against this universe's two deepest drawdowns.
- **A drawdown episode "recovered" on a close basis** can still mean an investor holding through it
  needed years; "time-to-recovery" in this report is calendar days from trough to recovery date, which
  is not the same framing the prior study used (peak to recovery).
- **A concurrency failure inside the app's storage layer can look exactly like a missing ticker**,
  demonstrated concretely in Part A — a caller (or reader) that does not check exception *type* rather
  than exception *message* cannot tell "this ticker doesn't exist" from "another process on this
  machine had the database file locked five minutes ago" without a retry.
- **A backtest, or in this stream's case a historical characterisation, is not a forecast.** Nothing
  above predicts what any instrument will do next; it describes what its stored price history did.

## Anything not expressible, and what was done instead

- The brief asks for "adequate daily range to clear 5bps-each-way costs" as one swing-suitability
  input. This report does not simulate that clearance directly (no strategy was backtested here); it
  reports ATR%/close as the measured proxy for daily range and states the 10bps round-trip cost
  assumption alongside it, leaving the comparison to the reader rather than asserting a pass/fail cutoff
  that would itself be a kind of recommendation.
- The Lo–MacKinlay heteroskedasticity-robust variance-ratio test (the standard formal version of this
  statistic, with its own test statistic and p-value) was not implemented; this report uses a plain
  non-overlapping-block variance ratio with no significance test attached, documented in
  `scripts/universe.py`'s `variance_ratio()` docstring, specifically so it is not mistaken for a
  hypothesis test this stream did not run.
- Four candidates (QUAL, MTUM, VLUE, VWO) failed on the first, concurrent fetch pass due to a
  shared-database lock from another parallel analyst stream — not a data-existence or short-history
  problem. A serial re-fetch, run once the parallel streams finished, recovered all four with
  comfortable history (3,286–5,389 bars each); this report's tables now include them, and the incident
  itself is documented in Part A as a finding rather than erased.
