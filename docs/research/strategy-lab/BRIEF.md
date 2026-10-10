# Strategy Lab — standing brief for every analyst on this study

Run date **2026-08-11**. Read this in full before writing a line of code. Every analyst on this
study works to the same universe, the same harness, and the same statistical discipline, so that
five parallel workstreams produce one comparable body of evidence instead of five incompatible ones.

Source of the hypotheses: the user's chart-analysis note (`[MAIN] Chart Analysis
(Indicator/Strategy)`). Your assignment names which sections of that note you own. The note is a set
of **claims to be tested**, not a set of facts to be implemented. "MACD crossover is faster but more
falsy than MA crossover" is a testable proposition; your job is to test it, and reporting that it is
false is as valuable as reporting that it holds.

---

## 1. Where things live

| Path | What |
|---|---|
| `docs/research/strategy-lab/lib/quantlab.py` | The shared harness. Read its docstring. |
| `docs/research/strategy-lab/scripts/` | Your script goes here, named `<stream>_<topic>.py` |
| `docs/research/strategy-lab/data/` | JSON output (written by `quantlab.write`) |
| `docs/research/strategy-lab/reports/` | Your markdown report, `<stream>.md` |
| `docs/research/2026-08-11-qqq-soxx-igv-dram-fono.md` | A prior study on this app. Read it. Do not repeat it. |

Python is `.venv/Scripts/python.exe` at the repo root. Run scripts from
`docs/research/strategy-lab/` with `sys.path.insert(0, 'lib')`, e.g.

```
cd "<repo>/docs/research/strategy-lab"
../../../.venv/Scripts/python.exe scripts/your_script.py
```

---

## 2. The universe — fixed, do not substitute

**Primary universe (5 symbols).** Every hypothesis is tested on all five. This is your correction
family: `len(ideas) x 5`.

```
SPY   broad large cap, 1993-  (8438 bars)
QQQ   large-cap growth,  1999-  (6897 bars)
IWM   small cap,         2000-
XLK   technology sector, 1998-
XLV   healthcare sector, 1998-   <- deliberately not a tech proxy
```

XLV is in the primary set on purpose. SPY/QQQ/XLK are three views of the same large-cap growth
complex; if a rule only works there, the primary family should show you that by failing on IWM and
XLV rather than letting you conclude "it replicated on five instruments."

**Replication universe (13 symbols).** Run these **only** for ideas that survived the primary
family, and report them as a *separate* replication section with their own correction. Never fold
them into the primary family — that is how a 40-test family quietly becomes a 150-test one.

```
DIA SOXX IGV XLF XLE XLP XLU XLY XLI XLB XLC TLT GLD
```

Singles available in cache: `NVDA`, `AMZN`. `^VIX` and `DX-Y.NYB` are cached as *signals*, not as
tradable instruments — never run a strategy backtest that "buys" `^VIX`.

Any symbol not listed here must be declared in your report before you run it, with a reason.

---

## 3. The harness — use it, do not reimplement it

```python
import sys; sys.path.insert(0, 'lib')
from quantlab import Idea, run_family, horizon_sweep, write, bars_frame, strategy_backtest

IDEAS = [
    Idea(
        key="golden_alignment",
        entry="ema(20) > sma(50) and close > sma(200)",
        exit="ema(10) crosses_below ema(20)",
        horizon=20,                 # THE one horizon this idea is judged at. Declare before running.
        direction="up",
        max_holding_bars=None,
        stop_loss_pct=None,
        rationale="note p.4: 20EMA > 50SMA > 10EMA > 200MA is the 'ideal entry setup'",
        falsifies_if="20-bar forward hit rate does not exceed the same-bars baseline",
        source="note p.4 'Ideal Entry setup'",
    ),
]
PRIMARY = ["SPY", "QQQ", "IWM", "XLK", "XLV"]
WINDOWS = [
    ("dotcom_2000_2002", "2000-01-01", "2002-12-31"),
    ("bull_2003_2007",   "2003-01-01", "2007-10-31"),
    ("gfc_2007_2009",    "2007-11-01", "2009-03-31"),   # see the correction note below
    ("qe_bull_2009_2019","2009-04-01", "2019-12-31"),
    ("covid_2020_2021",  "2020-01-01", "2021-12-31"),
    ("bear_2022",        "2022-01-01", "2022-12-31"),
    ("recent_2023_now",  "2023-01-01", None),
]
```

> **Correction, 2026-08-11, mid-study.** The first version of this brief omitted `gfc_2007_2009`,
> leaving 2007-11-01 to 2009-03-31 — SPY's single worst drawdown in the entire history, −56.5% — in
> no labelled window at all. The gap was found by the `mean-reversion` analyst, not by the author of
> this brief. It never touched any p-value or q-value: regime windows are descriptive strategy
> mechanics only and are excluded from every correction family by design, and the crisis bars were
> always present in the full-history aggregates. But every regime table produced before this
> correction is missing the most punishing regime in the sample, which is precisely the window a
> reader would most want to see a mean-reversion rule's behaviour in. Streams that ran before this
> edit have their GFC window backfilled by `meta/backfill_gfc_window.py` rather than by re-running
> the whole study.

```

result = run_family(IDEAS, PRIMARY, family="ma-trend", windows=WINDOWS)
write(result, "ma_trend_primary")
```

`run_family` gives you, per idea per symbol: lookahead guard status, hit rate, same-bars baseline,
edge, raw and independent sample size, exact binomial p, BH-corrected q across the whole declared
family, a verdict, the full strategy backtest against buy-and-hold at non-zero costs, and per-regime
strategy mechanics. `horizon_sweep` is the exploratory all-horizons table in its own separate BH
ledger — descriptive only.

**Cap yourself at 6–9 ideas.** A 9-idea family is 45 primary tests; beyond that BH will bury
everything and you will have learned nothing. Pick the ideas that most directly encode the note.

---

## 4. The rule DSL — what you can actually express

Indicators: `sma(period)`, `ema(period)`, `rsi(period)`, `atr(period)`, `bb_upper(p,sd)`,
`bb_mid(p,sd)`, `bb_lower(p,sd)`, `macd_macd(f,s,sig)`, `macd_signal(f,s,sig)`, `macd_hist(f,s,sig)`.
Price fields: `open high low close volume`. Operators: `< <= > >= == !=`, `crosses_above`,
`crosses_below`, `and`, `or`, `not`, `+ - * /`, parentheses. Comparisons do not chain
(`1 < rsi(14) < 2` is a syntax error — write it as two `and`-ed comparisons).

Things the note asks for that the DSL **cannot** express — say so in your report rather than
substituting something else silently:

- **ADX, Stochastic, Ichimoku, Volume Profile, Fibonacci, order flow** — not in the registry.
- **Volume indicators** — deliberately deferred by the user; `volume` the raw field exists, derived
  volume indicators do not.
- **VWAP** — registered but restricted to 5m/1h intervals, and this study is **daily bars only**
  (Yahoo caps 5-minute history at 60 days; settled decision, do not reopen).
- **Divergence** (price makes a lower low while MACD/RSI makes a higher low) — not expressible: the
  DSL has no lookback-extremum operator. Do not fake it with a crossover.
- **Multi-timeframe confluence** — one expression sees one interval. A weekly filter on a daily
  entry is not expressible.

Two useful derivations that **are** expressible:

```
z-score(20)     (close - bb_mid(20,2)) / ((bb_upper(20,2) - bb_mid(20,2)) / 2)
BB bandwidth    (bb_upper(20,2) - bb_lower(20,2)) / bb_mid(20,2)
ATR as % price  atr(14) / close
```

---

## 5. Statistical discipline — non-negotiable

These are the house rules of this repository (`HANDOFF.md`, "Standing decisions") and the reason the
prior study is trustworthy.

1. **Declare the family before you run it.** All ideas, all symbols, one BH ledger. If you add an
   idea after seeing results, re-run the whole family with the larger `m` and say you did.
2. **One horizon per idea, declared up front.** The all-horizon sweep is exploratory and lives in a
   separate ledger. Reading the best horizon off a sweep and reporting it as a finding is the
   failure mode this study exists to avoid.
3. **Every claim carries n (independent, not raw), a baseline, and a corrected q.** `n_independent`
   below 30 is `underpowered` — the harness marks it; do not argue past it.
4. **Direction is checked before significance.** An edge running opposite the pre-declared direction
   is `rejected`, not `inconclusive`.
5. **Buy-and-hold on the identical window is not optional.** A strategy that returns 400% over 25
   years while buy-and-hold returned 1300% is a losing strategy, and your report must say so in
   those words.
6. **Costs are the harness default and stay there**: 5 bps slippage each way. `cost_drag` is
   reported, never assumed away. Several rules in the prior study lost more to cost drag than they
   made in total return.
7. **The lookahead guard must pass.** `UNVERIFIED` is a failure state, not a shrug. Report the
   status for every expression.
8. **Never touch the production thesis ledger.** `data/store/thesis.sqlite` holds one out-of-sample
   look per ticker and spending it is irreversible. `run_family` does not touch it. If you want
   `app.thesis.loop`, construct `Settings(store_dir=<fresh temp dir>)` and pass `bars=` directly —
   see the prior study's isolation note.
9. **Read-only with respect to money and to the ledger.** No brokerage CSV, no `ledger.sqlite`, no
   order placement, nothing that writes to `data/store/runs`.
10. **Do not modify application source.** If you find a bug, document it with a reproduction and
    report it; do not fix it inside this study.

---

## 6. What your report must contain

Write `reports/<your-stream>.md`. Required sections:

1. **What was tested** — the full declared family as a table: key, entry, exit, horizon, direction,
   holding cap, stop, and which line of the note it encodes.
2. **What the note claims vs. what the data says** — one row per claim, with the verdict. This is
   the section the user actually wants; it is the point of the study.
3. **Primary family results** — the full grid, with edge, n_indep, p, q, verdict per symbol.
4. **Strategy mechanics vs buy-and-hold** — total return, CAGR, Sharpe, max DD, exposure, trades,
   win rate, cost drag, and whether it beat buy-and-hold, per idea per symbol.
5. **Regime breakdown** — the window table. Call out any idea whose aggregate result is carried by
   one regime.
6. **Replication** — only for primary survivors, on the replication universe, separately corrected.
7. **What this cannot tell you** — be specific to your stream, not boilerplate. Overlapping windows,
   one historical path, survivorship in ETF constituents, correlation between your symbols, and any
   note concept you could not express.
8. **Anything you could not express, and what you did instead.**

Numbers in the report must be copy-pasteable from the JSON in `data/`. If a number is in your
report, the script that produced it is in `scripts/`.

---

## 7. Tone and honesty

The prior study on this repo found **zero survivors across three tickers and 75 tests** and said so
plainly. That is a good outcome, not a failed study. The house style is that a flattering result is
guilty until proven innocent, and the QA reviewer on this study is briefed to attack whatever you
produce. Write the report you would be comfortable defending against someone trying to break it.

**Nothing in this study is investment advice**, and no report may frame an instrument as one to buy
or sell. You are describing what conditions did historically, with sample sizes and corrections
attached. The user's own repository states this convention in `README.md`; keep to it.
