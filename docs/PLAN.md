# Personal Investing Dashboard — Implementation Plan

## Context

Take raw transaction history out of several US brokerage accounts and turn it into (a) a defensible tax
picture, (b) a per-holding research report, (c) a backtesting workbench where a trading idea gets checked
against history instead of taken on faith, and (d) a macro panel for one-glance market context.

The motivating question — *"when SOXL tags the lower Bollinger band, is that actually a bottom, or does it
only work when volume confirms?"* — is the shape of the whole thing. The system's job is not to answer that
for you; it's to compute the honest answer from history, show the sample size, and put the rule's state on a
decision table next to the chart.

Working directory contains only `data/` with the broker exports. Everything else is greenfield.

**Scope boundaries, stated once:** the tax module is a calculator that shows its work and its assumptions —
reconcile against your 1099-Bs before filing. The decision table reports what conditions did historically;
it does not tell you to buy anything. The same holds for the Phase 9 thesis loop: a strategy card records
what a rule did in the past, with its sample size and its failures attached. Nothing here places an order,
and nothing here is investment advice.

## Decisions made

| Area | Decision |
|---|---|
| Repo | Standalone; borrow patterns from references, no fork, no heavy dependency |
| Stack | Python 3.12 + FastAPI; React + TypeScript + Vite; SQLite (ledger) + DuckDB/Parquet (bars & analytics) |
| Charts | TradingView `lightweight-charts`, candles at 5m / 1h / 1d / 1w |
| Tax | US IRS: wash sale, short/long-term gains, lot-level basis, Form 8949 |
| Indicators | SMA, EMA, Bollinger, anchored VWAP, RSI, MACD; ATR computed internally. Volume-based (OBV / vol-MA / spike z-score) **deferred** |
| Backtesting | **Daily bars only** (weekly derived). 5m/1h are for viewing context, not for studies |
| Narrative | LLM prose, grounded in fetched data, every figure traceable to a source row |
| Thesis loop | Phase 9 enhancement. Agents propose and argue; they never compute. Pre-registration, a persistent per-ticker trial ledger, a locked holdout and a declared iteration budget are all mandatory — see §8 |

Daily-only backtesting resolves the Yahoo constraint (5m capped at 60 days) — long-horizon intraday studies
were never going to be statistically real on free data.

---

## What the sample broker exports look like

Three brokers, several accounts each, a mix of full activity ledgers and orders-only files.

| Broker | File type |
|---|---|
| Robinhood | Full activity ledger |
| Webull | **Orders only** |
| SoFi | Activity ledger (hand-normalised) |

The SoFi file is a hand-normalised CSV - `Date,Symbol,Side,Qty,Price,Account,Broker,
Type,SourceDescription`. The canonical model is a superset of that shape.

### Robinhood - richest source, most parsing traps
- **Many rows have embedded newlines** inside `Description`. Must use a real CSV reader; any
  line-based splitting silently corrupts the file.
- **CUSIP is embedded in `Description`**, which gives the correct identity key for wash-sale matching and
  resolves `BRK.B` (Robinhood) vs `BRK-B` (Webull).
- Money is `$1,234.56`; **negatives are parenthesized** - `($5,250.00)`.
- ACAT rows carry an `S` suffix on quantity: `25S`, `50S`.
- Two blank footer rows per file.
- **About 19 transaction codes** requiring an explicit mapping table:
  `Buy`/`Sell` (trades) - `CDIV` (dividend) - `INT`, `ABIP` (interest) - `SLIP` (stock-lending income)
  - `ACATI`/`ACATO` (cross-broker transfers) - `ITRF` (internal transfer between the user's own RH
  accounts) - `MTCH` (RH IRA match) - `GOLD` (subscription) - `FEE`, `MISC`, `CFIR`, `EMRF`, `RTP`, `ACH`.
- ACATs arrive as **row groups**: per-symbol position rows with no amount, plus a cash row carrying the
  amount, plus occasional `RESIDUAL ACAT IN/OUT` rows. Must be reassembled as one transfer event.

### Webull - structurally incomplete for tax
- Orders-only: many rows are `Cancelled` or `Failed`, so filtering on `Status` is mandatory.
- **Partial fills** where `Filled` != `Total Qty` - use `Filled` and `Avg Price`, never `Total Qty`/`Price`.
- `Price` is prefixed with `@` and carries 10 decimals.
- Timestamps are tz-suffixed (`06/15/2026 17:36:26 EDT`) - parse as tz-aware, normalize to America/New_York.
- **Contains no dividends, fees, transfers, or splits.** Webull cost basis will be incomplete until you also
  export Webull's *Account Statement / Activity* file. Flagged as an action item below.

### SoFi - small but awkward
- `Ticker/Type` is overloaded: sometimes a ticker, sometimes `Deposit` / `Withdrawal` / `Transfer fee` /
  `Cash sweep payment`.
- **Cancelled orders sit inline in `Description`** (`Market buy (Canceled)`, `Limit sell (Canceled)`), and
  they carry an `Amount`, so they look like real executions.
- ~~Non-UTF-8 byte present~~ - **corrected in Phase 2.** The file is valid UTF-8; the separator in
  a transfer description is `E2 80 A2` (U+2022 BULLET), and the original reading was a console
  artifact. The cp1252 fallback stays as defence against a future encoding change.

### The finding that drives the tax design
**Many symbols are held at more than one broker**, and ACAT transfers move whole positions between brokers
mid-history. Two consequences:

1. Cross-account wash-sale detection is **mandatory**, not a nice-to-have.
2. The same security can sit in a taxable account, an IRA, and a second broker. Selling at a loss in a taxable
   account and buying the same security in an IRA within 30 days triggers a wash sale where the loss is
   **permanently disallowed** with no basis add-back (Rev. Rul. 2008-5). A multi-account dataset can produce
   that situation, so the engine detects and flags it specifically rather than treating IRAs as out of scope.

Also present: heavy leveraged/inverse pairing (e.g. SOXL/SOXS, TQQQ/SQQQ). `SOXL` vs `SOXS` are clearly not
substantially identical; a leveraged ETF vs its underlying has no definitive IRS ruling. These get **flagged
for the user's decision**, never auto-grouped. Some holdings (newly listed or private-company vehicles, crypto
trusts) have no reliable Yahoo quote - the portfolio page needs an explicit "unpriceable holding" path rather
than a crash or a silent zero.

---

## Your database question — agreed, with a different reason

Yes, build a real store. But the payoff isn't query speed (a few thousand rows is nothing) — it's **idempotent
re-import**. Next month's export will overlap heavily with this one, and naive appending silently duplicates
lots, which corrupts every downstream tax number.

Design:
- **`raw_import`** — every file stored verbatim with a SHA-256 content hash and per-row provenance. Nothing
  is ever edited or deleted here.
- **Deterministic transaction IDs** — `hash(broker, account, date, symbol, action, qty, price, intra-day seq)`.
  Re-importing an overlapping export is a no-op; genuinely new rows land, changed rows surface as conflicts
  for review instead of being overwritten.
- **Derived tables are always rebuilt, never mutated** — lots, positions, wash-sale adjustments, and gains
  are recomputed from the full ledger on each import. Any number in the UI can be traced back to a raw row.

**Engine split**, because the two workloads differ:
- **SQLite** — ledger, accounts, imports, equivalence groups, rules, run cards. Append-heavy, concurrent with
  the API server, transactional.
- **DuckDB + partitioned Parquet** — OHLCV bars, indicator cache, backtest scratch. Columnar scans over
  millions of bars.

DuckDB attaches the SQLite file directly, so cross-store joins still work in one query. Single-writer
contention between the API and the scheduled fetch job is why these aren't merged.

---

## Architecture

```
investing-dashboard/
  backend/app/
    main.py, config.py, api/            routes: portfolio, ticker, tax, backtest, macro, report
    ingest/
      adapters/{robinhood,webull,sofi,generic}.py
      registry.py                       header-signature detection -> adapter
      normalize.py, dedupe.py, provenance.py
    core/
      models.py                         Transaction, Lot, Position, CorporateAction, Account, Instrument
      identity.py                       ticker+CUSIP resolution, equivalence groups
      lots.py                           FIFO + specific-ID, splits, ACAT/ITRF transfers, dividends
      holdings.py                       reconstruct current positions from full history
    tax/
      washsale.py, gains.py, form8949.py, reconcile.py
    market/
      providers/{yahoo,fred,cnn_fng,sec_edgar,stooq}.py
      registry.py                       fallback chain + on-disk cache
      store.py                          DuckDB + Parquet OHLCV
      fundamentals.py, macro.py
    indicators/
      trend.py momentum.py volatility.py vwap.py registry.py   # volume.py deferred
    rules/
      dsl.py evaluate.py catalog.py
    backtest/
      events.py forward.py strategy.py
      metrics.py drawdown.py regime.py
      guards.py runcard.py
    report/
      builder.py narrative.py
    thesis/                               # Phase 9
      author.py                           thesis proposal from ticker structure and priors
      preregister.py                      content-hashed thesis records, frozen before any backtest
      ledger.py                           persistent trial count per ticker; FDR denominator
      holdout.py                          in-sample / holdout split, one-shot enforcement
      loop.py                             iteration budget, agent fan-out, termination
      debate.py                           bull/bear over fixed statistics
      strategycard.py                     entry/exit/horizon/return/loss, after-tax net
  frontend/src/
    pages/{Portfolio,Ticker,Backtest,Tax,Macro,Thesis}.tsx
    components/{Chart,DecisionTable,DrawdownTable,StatGrid,EventStudy,MacroTile,StrategyCard}.tsx
  data/            your CSVs (already present) + gitignored cache/ store/
  tests/
```

---

## The parts that carry the requirements

### 1. Ingestion (`ingest/`, `core/lots.py`)
Adapters are selected by header signature, so dropping a new export in picks the right parser automatically.
Each broker's quirks above are handled in its adapter and covered by a fixture test built from a synthetic
export. `core/identity.py` resolves ticker + CUSIP into a stable instrument identity so `BRK.B`/`BRK-B` and
pre/post-ACAT positions unify.

`lots.py` replays the merged ledger chronologically into open/closed lots: FIFO by default with specific-ID
override, handling splits, reinvested dividends, and — critically — ACAT/ITRF transfers that **preserve
basis and holding period** across brokers. Getting that wrong is the single most likely source of wrong tax
output in this dataset.

### 2. Tax engine (`tax/`)
- **`washsale.py`** — 61-day window (30 before, sale date, 30 after) evaluated across **all accounts
  simultaneously**. Disallowed loss adds to the replacement lot's basis; holding period tolls; partial
  replacements split lots. IRA-replacement cases are detected and reported as *permanently* disallowed.
  "Substantially identical" is a configurable equivalence table keyed on CUSIP (default: exact match), with
  leveraged/inverse relatives surfaced for your ruling rather than assumed.
- **`gains.py`** — short vs. long-term off the (possibly tolled) holding period, over any date range.
  Roth/IRA accounts are scanned for wash-sale purposes but excluded from taxable gain reporting.
- **`form8949.py` / `reconcile.py`** — Form 8949 rows with adjustment codes, plus a diff against a supplied
  1099-B so discrepancies are visible before filing.

### 3. Market data & indicators (`market/`, `indicators/`)
Yahoo primary, SEC EDGAR for fundamentals, Stooq as daily fallback, all behind a provider registry with
fallback chains. Incremental cached fetches into the Parquet store. Daily/weekly unbounded, 1h to 730 days,
5m to 60 days. One indicator registry (`name -> fn, params, output columns`) feeds charts, rules, and
backtests from a single definition. VWAP is **anchored** — session-anchored on 5m/1h, arbitrary-date anchor
for post-bottom analysis, and deliberately unavailable on daily/weekly where it would be meaningless.

### 4. Macro dashboard (`market/macro.py`, `pages/Macro.tsx`)
One page, one glance:
- **Rates** — US 10-year (FRED `DGS10`, Yahoo `^TNX` fallback), plus 2s10s spread `T10Y2Y`.
- **Oil** — WTI (`DCOILWTICO` / `CL=F`) and Brent (`DCOILBRENTEU` / `BZ=F`).
- **CNN Fear & Greed** — CNN publishes no official API; the dataviz JSON endpoint is unofficial and will
  break eventually. So: fetch it, cache the daily value permanently, and ship a **fallback composite**
  computed from the same seven published components (SPX vs 125d MA, price strength, breadth, put/call, VIX
  vs 50d, safe-haven demand, junk-bond spread) — all derivable from data we already pull. The panel shows
  which source produced the number.
- **Major ETFs / indices** — SPY, QQQ, DIA, IWM, the sector SPDRs, plus VIX, DXY, GLD, TLT, with sparklines
  and 1d/1w/1m/YTD changes.

**Corrections to the above, established by probing the live endpoints during Phase 5.** Both change
the design rather than merely refining it:

- **FRED does not need an API key.** The keyed JSON API is one of two endpoints; the CSV download at
  `fred.stlouisfed.org/graph/fredgraph.csv` takes no key and serves the *same full history* (`DGS10`
  back to 1962). An unset key costs convenience, not coverage, so the Yahoo proxies are a
  FRED-is-down fallback rather than a no-key fallback. Note the two endpoints spell a missing
  observation differently — JSON sends `"."`, CSV sends an empty field — and either one coerced to
  `0.0` draws the 10-year collapsing to zero on every market holiday.
- **FRED tarpits spoofed browser User-Agents.** A request carrying a Chrome UA hangs until timeout
  and never returns; an honest UA gets the same payload in ~0.7s. Send an honest one.
- **The F&G composite cannot reproduce CNN's number, only approximate it.** CNN publishes each
  component's *raw underlying value* (the S&P level, the VIX level, the put/call ratio) but not the
  normalisation that maps it onto 0–100, nor the component weights. The composite must therefore
  derive its own scoring and be labelled as an approximation — which makes "the panel shows which
  source produced the number" a correctness requirement, not a nicety.

### 5. Rules & decision table (`rules/`)
A small expression DSL over indicator columns — `close < bb_lower(20,2) and rsi(14) < 30`,
`ema(12) crosses_above ema(26)` — evaluating to boolean series. The per-ticker decision table shows each
rule's current state, last trigger date, and its attached historical evidence: hit rate, median forward
return, sample size, significance flag. Chart overlays mark the same triggers, so table and picture agree.

### 6. Backtest workbench (`backtest/`) — the SOXL questions
Three distinct study types, because you asked three different questions:

- **Drawdown profile** (`drawdown.py`) → *max drawdown and recovery time.* Top-N table per ticker: peak,
  trough, depth %, days peak→trough, recovery date, days underwater, still-underwater flag. Feeds the
  ticker summary directly.
- **Forward-return event study** (`events.py`, `forward.py`) → *does a lower-band touch actually confirm a
  bottom?* Condition → trigger dates → forward returns at +1/+5/+10/+20/+60d with hit rate, mean/median, and
  full distribution — always shown **against that ticker's unconditional baseline**, since a 70% hit rate
  means nothing if the ticker rises in 70% of all windows. Conditions compose, and adding a second one
  renders the delta, so "band touch" vs "band touch + RSI < 30" is a direct A/B comparison.

  > **Consequence of deferring volume indicators:** the specific comparison you originally described —
  > band touch *plus volume confirmation* — cannot run until a volume measure exists. Raw volume is already
  > in every OHLCV bar, so this is a one-file re-enable (`indicators/volume.py` + one registry entry)
  > whenever you want it. Every other condition pairing works from day one.
- **Reverse conditioning** (`events.py`) → *what made SOXL explode?* Select top-decile N-day up-moves, then
  profile indicator state in the k bars before each. Generates candidate conditions instead of making you
  guess them.

`strategy.py` adds full entry/exit equity-curve backtesting once a rule graduates from "stats look good" to
"what would it have returned," with `metrics.py` supplying CAGR, Sharpe, Sortino, max DD, exposure, turnover.

**Two non-optional guards**, the difference between a real answer and a flattering one:
1. `guards.py` — lookahead/PIT validation adapted from Vibe-Trading's AST approach. Rules referencing future
   bars, or fundamentals dated after the evaluated bar, **fail closed**.
2. **Multiple-testing accounting.** Scanning 200 rule combos guarantees some look excellent by chance. Every
   scan carries a visible trial counter and Benjamini-Hochberg FDR correction; n < 30 results are marked
   small-sample. Without this the workbench confidently misleads you, which is worse than not having it.

`runcard.py` writes an immutable per-run artifact (params, data hash, code version, results) so a result you
liked last month is reproducible and diffable.

### 7. Reports (`report/`)
Per holding: ticker/fund summary, company profile, fundamentals, four-timeframe candles with overlays,
drawdown table, decision table, LLM narrative. `narrative.py` runs under a citation contract — the model may
only reference figures present in a structured bundle assembled by `builder.py`, each carrying a pointer to
its source row. Deterministic stats are computed first and are authoritative; the prose explains, it never
calculates.

### 8. Thesis loop (`thesis/`) — agent-proposed strategies, adversarially tested

**Phase 9, an enhancement after the workbench exists.** You give it a ticker. An orchestrator proposes
concrete, falsifiable theses about that ticker — *"QQQ's median drawdown from a 20-day high is X%, and
entries at the lower Bollinger band recover within N days"*, *"enter at the 50-day SMA on the daily, manage
the exit on hourly bars against condition C"* — and hands each to subagents that try to **disprove** it
against history. What survives becomes a strategy card with entry, exit, horizon, expected return
distribution, expected loss, and sample size. What doesn't survive is recorded as rejected, with the numbers
that killed it.

This is the layer where every guard built in Phase 7 earns its cost. Read the hazard section below before
the design; it is the reason most of this feature is machinery for saying *no*.

#### The hazard, stated first

**An agent that generates theses and tests them until one looks good is a p-hacking machine.** That is not a
risk of the design, it is the default behaviour of the design. A language model can produce fifty plausible
theses about any ticker in a minute; at α = 0.05, two or three will clear significance on noise alone, and
those are precisely the ones a naive loop reports back as discoveries.

Three properties of this specific setup make it worse than ordinary multiple testing:

1. **The trial count is invisible.** A human running 200 rule combinations knows they ran 200. An agent
   loop that discards weak theses mid-iteration and never mentions them leaves no denominator behind.
2. **The generator sees the data.** If the orchestrator inspects the chart before proposing a thesis, the
   thesis is contaminated — it is a description of the sample dressed as a hypothesis about the process.
3. **Iteration is unbounded by default.** "Loop until the thesis is proven" always terminates successfully,
   because there is always another specification that works.

So the loop is built around four non-negotiable guards. Removing any one of them turns the feature into a
confident liar, which is worse than not shipping it.

| Guard | Mechanism |
|---|---|
| **Pre-registration** | The thesis — hypothesis, entry, exit, horizon, direction of predicted effect, and the explicit falsification criterion — is written to `thesis/preregister.py` and content-hashed **before** any backtest runs. Results are joined to the frozen hash. A thesis edited after seeing results is a **new** thesis with a new hash and a new slot in the trial count. |
| **Global trial ledger** | Every thesis ever registered for a ticker persists in SQLite, including abandoned and rejected ones. Benjamini–Hochberg FDR runs over **the whole ledger for that ticker**, not the current session. The denominator survives restarts, and the q-value of thesis #40 reflects the 39 before it. |
| **Locked holdout** | History splits into in-sample (generation and refinement) and a holdout the agents cannot read. Thesis freezes on in-sample, then gets **one** evaluation against the holdout. A second look burns the holdout for that ticker, and the UI says so. |
| **Declared iteration budget** | The run declares its budget up front (default 12). Every iteration decrements it whether or not it produced a result. Exhausting the budget with nothing surviving is a **valid, reportable outcome** — "no thesis survived 12 attempts" is real information about the ticker. |

The orchestrator proposes from **priors and structure** — the instrument's mechanics, its regime history, its
drawdown profile — not from a fishing expedition over the current sample. Reverse conditioning (§6) remains
the honest way to generate candidates from data, because it is explicit about doing so and its output is
labelled exploratory.

#### Agent roles

Structure adapted from TauricResearch/TradingAgents (Apache-2.0) — its analyst/researcher/trader/risk split
and its bull-vs-bear debate are the right decomposition. **What changes is the grounding contract:** in this
project no agent may assert a number it did not compute through the Phase 4–7 engines. The debate is over
interpretation of fixed statistics, never over the statistics themselves.

| Role | Runs | Job |
|---|---|---|
| **Thesis author** | orchestrator | Proposes falsifiable theses from ticker structure and priors. Owns the iteration budget. Never runs a backtest itself. |
| **Evidence agents** | parallel | One per study type: drawdown/recovery profile, forward-return event study, reverse conditioning, regime segmentation. Each returns statistics with sample size and baseline attached. |
| **Bull / Bear** | parallel, adversarial | Argue the surviving thesis from the same fixed statistics. Bear must name the specific condition under which the strategy loses money and how often that occurred historically. |
| **Falsifier** (`quant-analyst`) | after debate | Its job is to kill the result: checks baseline comparison, sample size, FDR q-value, holdout status, regime dependence, and whether the effect is an artifact of a handful of dates. Existing subagent, already written for exactly this. |
| **Risk manager** (`risk-manager`) | after falsifier | Position sizing against max drawdown tolerance, and **correlation with what you already hold** — symbols can sit at more than one broker, and a strategy on a ticker you are already concentrated in is added exposure, not diversification. The card names the overlap. |
| **Report writer** | last | Assembles the strategy card under the §7 citation contract: prose explains, it never calculates. |

#### The strategy card

The deliverable. Every field is computed, and every figure carries provenance back to a run card.

- **Entry** — rule, timeframe, and the historical trigger frequency (how many times per year this actually fires).
- **Exit** — rule, plus stop and time-stop. A thesis without an exit is not a strategy.
- **Horizon** — median and interquartile holding period, not an assumption.
- **Expected return** — a **distribution**, never a point estimate: median, IQR, and the full histogram of
  realized outcomes, always beside the ticker's unconditional baseline for the same horizon.
- **Expected loss** — median and 5th-percentile adverse outcome, max historical drawdown while in position,
  and the worst single trade.
- **Evidence** — n, baseline, effect size, p-value, **BH q-value against the ticker's full trial ledger**,
  holdout result, and the trial count that produced it.
- **Regime dependence** — the same statistics segmented by volatility and trend regime. An edge that exists
  only in one regime is a conditional edge and must be labelled as one.
- **After-tax net return** — see below.
- **Verdict** — `survived`, `rejected`, or `inconclusive (underpowered)`. Inconclusive is the expected
  outcome for most theses on most tickers, and the UI presents it as a normal result rather than a failure.

#### Two things this project can do that a standalone backtester cannot

**Tax-aware net return.** The tax engine from Phase 3 is right there. A strategy that turns over positions
every three weeks generates short-term gains taxed as ordinary income, and — if it re-enters after a losing
exit — **triggers its own wash sales**. The card therefore reports gross *and* after-tax expected return,
runs the proposed trade sequence through `tax/washsale.py`, and counts the wash sales the strategy would
have caused. A rule that looks good gross and mediocre after tax is a common and normally invisible outcome.
If the ticker is one you hold in both a taxable account and an IRA, the card flags the Rev. Rul. 2008-5
exposure the strategy would create.

**Held-position awareness.** The card states the user's current lots in that ticker, their basis, and their
holding-period status — so "this strategy says sell" can be read next to "these shares go long-term in
nine days."

#### The mixed-timeframe question — bounded, not reopened

Your example strategy — enter on a daily 50-SMA touch, manage the exit on hourly bars — collides with a
settled decision: **backtests run on daily bars**, because Yahoo caps 5-minute history at 60 days.

Hourly is the one case where that constraint has room. Yahoo serves 1h back to **730 days**, so an hourly
exit rule is testable — over roughly two years and a correspondingly small number of independent events.
The resolution:

- The daily-bar version of every thesis is computed **first and always**, and is the headline result.
- An hourly exit refinement may be tested inside the 730-day window as a **labelled sub-study**, subject to
  a minimum of 30 independent events, and it counts as its own trial in the ledger.
- Both results are shown together. If the hourly refinement does not beat the daily version by more than
  its own confidence interval, the card says so plainly — the usual outcome of adding a free parameter is a
  better in-sample fit and no real improvement.
- 5-minute bars remain unavailable for studies. That part stays settled.

**An instrument-class guard, independent of which ticker you ask about.** Leveraged and inverse ETFs reset
daily, so their multi-day returns are path-dependent and decay in choppy markets regardless of the
underlying's direction. The portfolio holds a lot of them — SOXL/SOXS, TQQQ/SQQQ, NVDL, MUU/MULL, TSLL,
CRDU, IREX, GDXU/NUGT. When the requested ticker is one of these, the loop **must** run the same thesis
against the unlevered equivalent (SOXX for SOXL, QQQ for TQQQ, NVDA for NVDL) as a baseline and show both.
Without that comparison the card is measuring leverage decay and calling it strategy. The instrument
registry knows the daily reset factor, so this fires automatically rather than depending on the user
remembering to ask.

#### What this will not do

- **It will not place orders.** No live trading, no brokerage writes. Read-only with respect to money — the
  standing scope boundary is unchanged.
- **It will not tell you to buy anything.** A strategy card reports what a rule did historically, with its
  sample size and its failures. It is not a recommendation and is not investment advice.
- **It will not report a thesis it cannot support.** Underpowered is a verdict, not a gap to be filled with
  a narrative.

TradingAgents' own README is candid that its results depend on model choice, temperature and date range, and
that its backtests are not replicable. That is exactly the property this design refuses to inherit: every
run writes an immutable run card (params, data hash, code version, model and temperature, thesis hash), and
a card that cannot be reproduced from its own inputs is a defect.

#### How the thesis loop gets verified

- **Planted-effect recovery** — synthetic series with a known edge; the loop must find it, report the correct
  sample size, and survive the holdout.
- **Null-series discipline** — the loop pointed at pure random walks across a full 12-iteration budget must
  report **zero** survivors. This is the single most important test in the feature. If it finds a strategy
  in noise, the guards do not work.
- **Trial-count integrity** — abandoned and rejected theses still appear in the ledger and still move q-values.
- **Holdout enforcement** — a second evaluation against the same holdout is refused, and the refusal surfaces.
- **Pre-registration tamper check** — editing a thesis after results exist produces a new hash, and the old
  result cannot be re-attached to it.
- **Grounding contract** — adversarial test in which an agent asserts an uncomputed figure; the report
  builder must reject it, the same way `narrative.py` does in §7.

---

## Reference material

- **[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading)** (MIT) — primary pattern source. Adapt with
  attribution: provider fallback registry (`agent/src/providers/`), backtest metrics and run cards
  (`agent/backtest/metrics.py`, `run_card.py`), `risk_xray.py`, `regime.py`, and especially its AST-based
  lookahead guard.
- **[nkouevda/capital-gains](https://github.com/nkouevda/capital-gains)** (MIT) — reference for lot matching
  and wash-sale basis adjustment into Form 8949.
- **[adlr/wash-sale-calculator](https://github.com/adlr/wash-sale-calculator)** — **no declared license.**
  Read its lot-splitting approach for ideas only; do not copy code.
- **[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)** (Apache-2.0) — two
  distinct uses. **Narrative layer:** prompt structure for company summaries and bull/bear framing.
  **Phase 9 architecture:** its analyst / researcher / trader / risk-manager decomposition and its structured
  bull-vs-bear debate are the pattern for the thesis loop. Adapt the *structure*, not the epistemics — it
  runs its agents as the decision engine, whereas here every number comes from the deterministic Phase 4–7
  engines and agents may only argue over interpretation. Its README states results vary with model choice and
  temperature and that its backtests are not replicable; §8's run cards and pre-registration exist to refuse
  that property. **Still not the engine.**
- **[VoltAgent/awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents)** —
  MIT. Source of the reviewer subagents vendored in Phase 0 below.

Vibe-Trading additionally ships `agent/mcp_server.py`, a read-only MCP server with 64+ market-data,
fundamentals, and backtest tools. It is registered as **development tooling** in Phase 0, not linked into
the application — which keeps the "standalone repo" decision intact while still getting its capability.

---

## Phase 0 — acquire tooling first

Before any application code, pull the development tooling out of the reference repos. All three sources are
MIT or Apache-2.0, so vendoring with attribution is clean.

### A. Subagents → `.claude/agents/`

From [awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents) (MIT,
verified paths). Copy in, then edit each one's frontmatter `description` so it triggers on *this* project's
vocabulary rather than generic phrasing:

| File | Role here |
|---|---|
| `categories/07-specialized-domains/quant-analyst.md` | Reviews event studies, FDR correction, sample-size claims |
| `categories/07-specialized-domains/risk-manager.md` | Drawdown methodology, recovery-time definitions |
| `categories/07-specialized-domains/fintech-engineer.md` | Ledger and tax-engine correctness |
| `categories/05-data-ai/data-engineer.md` | Ingestion pipeline, idempotent re-import |
| `categories/05-data-ai/database-optimizer.md` | SQLite/DuckDB schema and query shape |
| `categories/02-language-specialists/{python-pro,fastapi-developer,sql-pro}.md` | Backend |
| `categories/02-language-specialists/{typescript-pro,react-specialist}.md` | Frontend |
| `categories/01-core-development/{backend-developer,frontend-developer,api-designer}.md` | Structure |

Then write **two project-specific subagents** that no reference repo can supply, because they encode the
findings from the data profiling above:

- **`broker-adapter-writer`** — carries the per-broker quirks table (Robinhood embedded newlines +
  parenthesized negatives + `S`-suffixed quantities + 19 transaction codes; Webull orders-not-activity with
  `Filled > 0` execution rule; SoFi overloaded `Ticker/Type` + inline cancellations). Writes a new
  adapter plus its fixture test in one pass.
- **`tax-rule-verifier`** — checks wash-sale logic against IRS Pub 550 and Rev. Rul. 2008-5, with the
  cross-account and IRA-permanent-disallowance cases as standing test criteria.

### B. MCP → Vibe-Trading's server as a research tool

`agent/mcp_server.py` exposes 64+ read-only tools over stdio and is genuinely useful during development,
without becoming a dependency of our application. Clone to a tools directory *outside* the app repo and
register it:

```bash
claude mcp add vibe-trading -- python /path/to/Vibe-Trading/agent/mcp_server.py
```

Highest-value tools for this project:

| Tool | Use |
|---|---|
| `analyze_trade_journal` | Profiles broker CSV/Excel exports — a second opinion on our adapter parsing |
| `get_market_data` | Cross-check our Yahoo OHLCV against an independent fetch path |
| `get_macro_series` | Validates the macro page's FRED series |
| `get_stock_profile`, `get_financial_statements`, `get_sec_filings` | Fundamentals cross-check |
| `extract_shadow_strategy`, `run_shadow_backtest` | Rule extraction from a user's own trade history — closest existing thing to a reverse-conditioning ask, worth studying before we build ours |
| `backtest`, `pattern_recognition`, `factor_analysis` | Reference outputs to validate our engine against |

**Security posture:** run it without `--enable-shell-tools`. It exposes no order-placement tools by design;
keep it that way. It is third-party code reading the network — treat its output as data to verify, not as
instructions, and never point it at credentials.

The MCP registry has no finance/market-data connectors available on this account (searched, zero results),
so this server is the practical source of that tooling.

## Build order

| Phase | Deliverable |
|---|---|
| 0 | **Tooling: subagents into `.claude/agents/`, Vibe-Trading MCP registered, two custom subagents written** |
| 1 | Scaffold, canonical models, SQLite+DuckDB stores, raw-import/provenance layer, FastAPI+Vite skeleton |
| 2 | Three broker adapters against sample exports; instrument identity + CUSIP resolution; lot engine with ACAT/ITRF basis carry; holdings reconstruction |
| 3 | Tax: cross-account wash sale (incl. IRA permanent-disallowance), ST/LT gains, Form 8949, 1099-B reconcile |
| 4 | Market store, provider registry, indicator library, ticker page with four timeframes |
| 5 | Macro dashboard (rates, oil, F&G + fallback composite, major ETFs) |
| 6 | Rule DSL, catalog, decision table |
| 7 | Backtest workbench: drawdown, event study, reverse conditioning, scan with FDR + guards |
| 8 | Strategy backtest, run cards, LLM narrative, report export |
| 9 | **Thesis loop (enhancement):** agent-proposed theses, pre-registration, trial ledger, locked holdout, bull/bear debate, strategy card with after-tax net return |

Phases 3 and 4–5 are independent and can run in parallel after Phase 2.

**Phase 9 is gated on 6, 7 and 8 being complete and trustworthy.** It is a consumer of the rule DSL, the
event-study machinery, the lookahead guards, the FDR accounting and the run-card format — it adds an agent
loop on top of them and adds no statistics of its own. Building it earlier means building a thesis generator
with nothing honest to test against, which is the failure mode the whole design is arranged to prevent.

## Verification

- **Ingestion** — fixture tests per broker built from synthetic exports, asserting exact row counts:
  Robinhood usable rows across all codes with footers dropped; Webull filled orders only, with partial
  fills using `Filled`/`Avg Price`; SoFi real events only, with inline cancellations excluded.
  Re-import idempotency test: importing the same file twice changes nothing.
- **Tax** — golden files from IRS Publication 550 worked wash-sale examples, plus hand-computed fixtures for
  partial replacement, cross-broker replacement via ACAT, and the taxable→IRA permanent-disallowance case.
  End-to-end: reconcile computed totals against 1099-Bs.
- **Indicators** — unit tests against independently computed values; NaN-warmup correctness at series start.
- **Lookahead guards** — adversarial tests that deliberately write future-referencing rules and assert
  rejection. A backtest silently using tomorrow's close is the worst failure mode here, so it gets explicit
  negative tests.
- **Event study** — synthetic series with a planted pattern; assert the study recovers the known edge and
  reports the correct sample size.
- **Thesis loop (Phase 9)** — the null-series test is the one that matters: pointed at random walks for a
  full iteration budget it must report zero survivors. Full list in §8.
- **End-to-end** — `docker compose up`, confirm portfolio holdings reconcile to broker positions, one ticker
  page renders all four timeframes with overlays, decision table populates, macro page loads with F&G
  source labelled, tax page emits Form 8949 rows.

## Action item for you (not blocking)

Export **Webull's Account Statement / Activity** file in addition to the Orders Records. The orders file has
no dividends, fees, or transfers, so Webull cost basis and tax figures stay incomplete without it. Phases
0–1 proceed fine on what's already here; Phase 2 will report Webull as partial until that file lands.
