# Phase 5 — Macro dashboard, and a QA pass over everything before it

Commit `07115b7`. 776 tests pass, `ruff` and `mypy --strict` clean, frontend typechecks and builds.

This phase delivered the macro page and, at the same time, ran a dedicated QA pass over Phases 1–4.
The QA pass is the more important half of the report: it found a critical numerical defect that
599 green tests had been reporting as correct for two phases.

## What shipped

**Rates, oil, sentiment, movers** — one `GET /api/macro/snapshot` rather than six endpoints, so no
two panels can disagree about what "now" means. A dead upstream empties its own tile with a warning
and the page still returns 200.

**Fear & Greed** — CNN's index while it is reachable, and a local composite when it is not, clearly
labelled as an approximation.

**Movers** — 19 ETFs and indices read from the existing Parquet bar store, not a new fetch path.

## Three findings that changed the design

**FRED needs no API key.** The plan said an unset key degrades the page to Yahoo with less history.
It does not: the keyless CSV endpoint at `fred.stlouisfed.org/graph/fredgraph.csv` serves the same
full history as the keyed JSON API — `DGS10` back to 1962 either way. The Yahoo proxies are a
FRED-is-down fallback, not a no-key one.

**The two FRED endpoints spell a gap differently.** JSON sends the string `"."`; CSV sends an empty
field. `DGS10` contains 719 of them. Either one coerced to `0.0` draws the 10-year yield collapsing
to zero on every market holiday — a financial event rather than a parsing bug.

**FRED tarpits spoofed browser User-Agents.** A request carrying a Chrome UA hangs until timeout and
never returns; an honest UA gets the same payload in ~0.7s. Measured 3/3 against 9/9, interleaved.
This was originally misdiagnosed as "FRED is slow under repeated requests" — the fixture script's
own UA spoofing was the cause.

**The F&G composite cannot reproduce CNN's number.** CNN publishes each component's *raw underlying
value* — the S&P level, the VIX level, the put/call ratio — but never the normalisation onto 0–100,
nor the weights. The composite therefore derives its own scoring and says so. CNN-sourced components
leave `score` null rather than invent one.

## Defects found and fixed

### Critical — RSI and ATR were not Wilder-smoothed

A single `ewm(alpha=1/n, adjust=False)` call seeds the recursion from the *first observation*.
Wilder seeds from the simple mean of the first `n`. With `alpha = 1/n` the two do not converge for a
long time.

Against the canonical published worked example:

| bar | shipped | fixed | published |
|----:|--------:|------:|----------:|
| 14 | 50.66 | 70.46 | 70.53 |
| 15 | 47.27 | 66.25 | 66.32 |
| 16 | 47.68 | 66.48 | 66.55 |

Wrong by ~20 RSI points — the distance between "neutral" and "approaching overbought". On real QQQ
daily bars the error averaged 0.80 points and peaked at 3.86.

**Why 63 passing tests did not catch it.** The test's reference implementation claimed in its
docstring to be "Wilder's RSI via an explicit Python loop — independent of the pandas `.ewm` call
under test", and then seeded itself from the first observation too. It was written by reading the
implementation rather than the definition, so it could only ever confirm whatever the code did. Both
references are now written from the definition, and a test pins the published example.

### Critical — a concurrent reader crashed the bar store

DuckDB holds the Parquet file handle open past the query, through a buffer-manager cache not scoped
to the connection. Windows refuses to replace a file with an open handle, so the writer's atomic
`staging.replace(target)` threw. With **one** writer and no writer-vs-writer contention at all,
62 of 96 writes failed. The per-target lock guarded writers against each other only; readers now
take it too.

### Critical — ATR fabricated a true range from missing data

`max(axis=1)` used pandas' default `skipna=True`, correct for bar 0 where there is no previous
close, but applied to every row. A `NaN` high mid-series yielded TR = 0.0 where the true value was
29.0, and the output carried only the ordinary warmup NaNs — the corruption was invisible.

### High — SQL text ordering reintroduced the DST bug the adapter prevents

The Webull adapter pins UTC offsets precisely so the repeated November hour sequences correctly.
`fetch_transactions` then ordered on the serialized ISO *string*, where
`2026-11-01T01:15:00-05:00` sorts before `2026-11-01T01:30:00-04:00` despite being 45 minutes later.
FIFO lot selection trusts that order, so basis and realized gain go wrong. Fixed with a
UTC-normalized sort key and a re-runnable backfill migration.

Reachability: no crypto rows exist in the current exports, so this is latent today — but the Webull
adapter detects files by column headers, never by instrument kind, and crypto trades 24/7, so a fill
between 01:00–01:59 ET on the fall-back Sunday would hit it.

### High — Form 8949 column (d) double-rounded

Proceeds and fees were each rounded to cents and then subtracted, instead of rounding the net once.
When the raw values round in opposite directions the result is off by a cent and it propagates into
column (h) — breaking an identity the module's own docstring says holds *exactly*. Not exotic:
Webull carries 10-decimal prices and fractional shares are pervasive.

The tests guarding that identity asserted `gain_loss == proceeds - cost_basis + adjustment`, which
re-derives the formula under test and passes regardless.

### High — the test suite could not run from its documented location

`pythonpath` held only `backend/`, but eight test modules import `from tests.conftest`. From the
repo root, pytest instead collected a vendored third-party checkout and aborted on a conflicting
`conftest`. There was no working invocation at all.

### Medium and below

- `basis_uncertain` was keyed by `(account, instrument)`, so one oversell warning pushed every later
  clean disposal of that symbol into Box B on a filed form. Now lot-scoped, with genuinely
  position-scoped warnings kept deliberately broad.
- A missing `close` made EMA/RSI silently repeat the previous value and drift for many bars after.
- `parse_spec` dropped blank positional fields, so `macd:,26,9` silently became `fast=26, slow=9` —
  an inverted MACD labelled with the user's own parameters.
- Weekly resampling served the still-forming week as settled, so its close and volume mutated
  between reads. Now excluded until the ISO week is over.
- The intraday staleness gate hardcoded `America/New_York`, defeating refresh for any non-US venue
  during its actual session.
- `_write_meta` reused a fixed staging filename — the same race already fixed twice elsewhere in the
  codebase, one function away.
- SEC EDGAR's shared ticker-map 404 was reported as `SymbolNotFound` for whatever symbol was asked
  for, implying a real filing company does not exist.
- The registry discarded accumulated warnings when a later provider terminated the walk.
- Yahoo sent a spoofed browser UA; now honest, with the FRED evidence recorded so nobody reverts it.

## Live verification

The macro page rendered against real upstreams: US 10-year 4.65% from FRED with changes in **basis
points** (−4 bp 1D, +47 bp YTD), oil and the 19 movers in **percent**, Fear & Greed at 64 ("greed",
CNN-sourced) with all seven components showing raw values and a null score. Of 24 sparklines, **4
were broken into multiple segments** — the null-gap handling correctly breaking the line at real
FRED holiday gaps rather than bridging them. No `NaN` and no `undefined` anywhere in the DOM.

## A note on method

Seven of the defects above lived in seams — between modules, between code and a live upstream, or
between a test and the definition it claimed to encode. None were reachable by making a single
function more correct in isolation. The RSI defect is the sharpest case: the implementation and its
test agreed with each other perfectly, and both were wrong, because the test was derived from the
code instead of from Wilder.

## Known judgement call, not fixed

A completely flat price series yields RSI = 100. It follows from the formula (`avg_loss == 0` → 100)
and is pinned by an existing test, but a static instrument reading "maximally overbought" would
trigger any `rsi > 70` rule. Left as-is because it is pre-existing, deliberate and tested; worth
revisiting when Phase 6 attaches rules to thresholds.
