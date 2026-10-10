# Agent gap analysis — TradingAgents and Vibe-Trading, read against this codebase

Written 2026-08-30, from a full read of:

- `C:\Users\<user>\repos\externalProjects\TradingAgents` — an extended fork of TauricResearch/TradingAgents, v0.3.1. **Assume upstream documentation does not describe it**; the fork adds FRED macro, Polymarket, StockTwits/Reddit sentiment, a deterministic market-data verifier, structured Pydantic outputs, a markdown memory log with alpha-based reflection, multi-provider LLM clients and checkpoint/resume, and it *removes* upstream's ChromaDB vector memory and every Finnhub tool.
- `C:\Users\<user>\repos\externalProjects\Vibe-Trading` — HKUDS/Vibe-Trading v0.1.14. ~130 tools, 90 skills, 462 alphas, 31 swarm presets, 25 data loaders, 13 broker connectors.

Both are already present locally, and Vibe-Trading is additionally vendored at `tools/vendor/Vibe-Trading` and wired into `.mcp.json` as an MCP server **for Claude Code**, not for this application. Its `place_order` / `submit_order` capability is deliberately not re-exposed through this repo's own MCP server.

The purpose of this document is to record what those two systems have that we do not, so the knowledge survives the session that produced it. It is a reference, not a plan. What is actually being built is in [`AGENT-DESK-CONTRACT.md`](AGENT-DESK-CONTRACT.md).

---

## 1. How each system makes a decision

### TradingAgents — a fixed pipeline with two bounded debates

LangGraph `StateGraph`, 12 agent nodes plus 4 message-clear nodes, built in `tradingagents/graph/setup.py`.

```
4 analysts, sequential, each with its own ReAct tool loop and a message wipe between them
    Market · Sentiment · News · Fundamentals   →  four *_report fields
Bull ⇄ Bear debate, 2 × max_debate_rounds turns, over those four reports
Research Manager (deep model) judges          →  investment_plan, 5-tier rating
Trader                                        →  3-tier Buy/Hold/Sell + entry / stop / sizing
Aggressive → Conservative → Neutral, 3 × max_risk_discuss_rounds turns
Portfolio Manager (deep model)                →  final_trade_decision
```

Three details worth stealing outright:

1. **The final rating is extracted by regex, not by a second model call.** `agents/utils/rating.py::parse_rating` — two passes then a `"Hold"` default. Upstream used an LLM for this; the fork deliberately replaced it. A model in the parsing path is a model in the scoring path.
2. **Every conditional edge carries a *complete* path map.** `setup.py:28-42` documents why: a router falling through to a key that isn't in the map crashes LangGraph mid-run. All three risk edges and both debate edges name every possible destination.
3. **The message-clear node injects an instrument-anchored placeholder**, not a bare `"Continue"`. A bare continuation let the next analyst drift onto a different company.

The debate arithmetic is worth stating precisely because it is easy to get wrong: research terminates at `count >= 2 * max_debate_rounds`, risk at `count >= 3 * max_risk_discuss_rounds`, and Bull always speaks first because `current_response` starts empty and the router tests `startswith("Bull")`.

### Vibe-Trading — a ReAct loop, plus a swarm invoked as a tool

Tier 1 is `AgentLoop` (`agent/src/agent/loop.py`, 2776 lines) over ~130 auto-discovered tools. Tier 2 is the swarm, reachable **only** through the `run_swarm` tool.

A swarm preset is a YAML file: `agents:` (id, role, system prompt, tool whitelist, skills, iteration and timeout caps) and `tasks:` (id, agent_id, prompt template, `depends_on`, `input_from`). `SwarmRuntime._execute_run` validates the DAG, computes topological layers, and runs each layer's tasks in parallel on a thread pool. The final report is the last layer's summary.

The 31 presets are almost all the same shape — 2–5 specialists in parallel feeding one synthesiser:

> `investment_committee`: bull_advocate, bear_advocate ∥ → risk_officer → portfolio_manager
> `technical_analysis_panel`: classic_ta, ichimoku, harmonic, wave, smc ∥ → signal_aggregator
> `risk_committee`: drawdown_analyst, tail_risk_analyst, regime_detector ∥ → aggregator

Three details worth stealing:

1. **Downstream agents receive summaries, never full text.** `SwarmTask.input_from` maps `{context_key: upstream_task_id}` and splices the upstream `summary` into `{upstream_context}`. Artifacts pass by file path. This is what stops a ten-stage run from growing quadratically.
2. **`blocked` is a distinct terminal state.** A failed upstream marks its dependents blocked; they are never silently completed. So is `incomplete` — a worker that produced a plan-only stub, or fabricated numbers, or never called a tool, is not `failed` and is not `succeeded`.
3. **Grounding data is pre-fetched before any worker runs.** `_prefetch_grounding_data` scans the run variables for symbols, fetches real OHLCV, and renders a "Ground Truth" markdown block into every worker prompt.

---

## 2. The single most transferable idea: mechanical grounding

Vibe-Trading's `GroundingLedger` (`agent/src/agent/grounding.py`, 2649 lines) is a validator wrapped around the loop, not prompt text. Three hooks:

| Hook | When | What it does |
|---|---|---|
| `authorize_tool_call` | before execution | Blocks market/news/fundamentals/trading calls for symbols whose identity was never resolved; detects venue mismatch; refuses to silently pick from an ambiguous shortlist |
| `ingest_tool_result` | after execution | Records `EvidenceRecord`s — symbol, price fields, timestamps, currency, venue. Also ingests OHLC CSVs the model wrote to disk |
| `validate_final_answer` | after generation | Identity, unsourced symbols, price claims, price provenance, price tables, numbers without dates, and an AST-evaluated arithmetic check on explicit derivations |

On failure **the answer never reaches the user**: it emits `answer_rejected`, appends a correction prompt as a `<system>` turn, and retries up to a `revision_cap` of 3–4. Out of budget, it releases `safe_fallback()` and marks the result `degraded: true`. `should_buffer_output` suppresses streaming until validation passes.

TradingAgents attacks the same problem from the other end, with data rather than validation: `get_verified_market_snapshot` bypasses the vendor router entirely, computes 11 indicators deterministically, and the market analyst's prompt mandates calling it and treating it as source of truth.

**Our position.** We solved this by prohibition — `app.agents.reviewer._reject_measurement` scans agent prose for any Unicode digit and rejects it, and `app.report.narrative.verify` gates report prose. That is correct for the evolution loop, where agent prose sits beside a scoreboard the engine computed. It is unworkable for a research desk whose job is to read a price series and argue about it. The Agent Desk feature replaces prohibition with grounding: numbers are allowed, every one is checked against the evidence pack the stage was given, and a stage that fails three times is shown marked ungrounded rather than hidden. The loop's strict rule is untouched.

---

## 3. Tools and data we do not have

Ordered by how much they would change what our agents can say.

| Gap | Where it exists | What it gives | Cost to us |
|---|---|---|---|
| **Assembled financial statements** (balance sheet / income / cash flow, quarterly and annual) | Both. TradingAgents `get_balance_sheet` / `get_cashflow` / `get_income_statement`; Vibe `get_financial_statements` | A fundamentals agent can currently reason about ratios but cannot read a statement | Medium — we have raw XBRL facts from `SecEdgarProvider`; this is assembly and date-filtering, not a new provider |
| **Insider transactions (Form 4)** | TradingAgents `get_insider_transactions` | Who inside the company bought or sold, and when | Small — SEC EDGAR, and we already run an EDGAR client for 13F |
| **Options chain, pricing, payoff** | Vibe `get_options_chain`, `options_pricing` (Black-Scholes + Greeks), `options_payoff` (multi-leg, breakevens, spot×IV scenario matrix) | Entirely absent here. Also the only way to price a hedge | Medium-large |
| **Portfolio risk x-ray** | Vibe `portfolio_risk_xray` | HHI / effective-N concentration, annualised vol, historical VaR and ES, diversification ratio, correlation and beta | Medium — we have drawdown and CAGR; no VaR, no concentration measure |
| **Market screener** | Vibe `screen_market` | Top-N movers by change / volume / turnover | Small — `app.market.macro` has only a fixed `_MOVERS` watchlist |
| **Verified market snapshot** | TradingAgents `get_verified_market_snapshot` | A deterministic, provenance-carrying block the model is told to treat as truth | Small — being built as part of the Agent Desk evidence layer |
| **Factor / alpha research** | Vibe `alpha_zoo` (462 alphas: alpha101, gtja191, qlib158, academic), `alpha_bench`, `alpha_compare`, `factor_analysis` (IC/IR, layered NAV) | A whole research modality we lack | Large, and genuinely adjacent to our rule-evidence machinery |
| **Trade-journal behavioural analytics** | Vibe `analyze_trade_journal` | Disposition effect, overtrading, momentum-chasing, anchoring — each with numeric evidence and a severity | Medium, and it could run against our own paper-desk realised trades today |
| **Cashflow-aware performance** | Vibe `cashflow_performance` | TWR vs Modified Dietz vs money-weighted XIRR — the distinction between manager skill and timing luck | Small-medium; relevant to the real portfolio, not the paper desk |
| **Statistical test battery** | Vibe `quantlib_call` over 16 modules | ADF, cointegration, Granger, Ljung-Box, GARCH, regime switching, event study CAR/CAAR, Kupiec/Christoffersen VaR backtests, multiple-testing correction | Large. We have Benjamini-Hochberg in `evolution/ledger.py` and nothing else |
| **Prediction markets** | Both (Polymarket) | We *have* `PolymarketProvider`; it is not surfaced to any agent | Trivial — wiring only |
| **Indicators `mfi` and `vwma`** | TradingAgents | Two more registry entries | Trivial |
| **Multi-market symbol normalisation** | Both. TradingAgents `normalize_symbol` (~35 aliases + crypto and forex rules) | `GOLD`→`GC=F`, `BTCUSDT`→`BTC-USD`, `EURUSD`→`EURUSD=X`, `SPX500`→`^GSPC` | Small, and only matters if we go beyond US equities |
| **Research-paper ingestion** | Vibe `research_papers` (arXiv q-fin + OpenAlex) with a `factor_brief` extracting the proposed signal and its required inputs | A pipeline from literature to testable hypothesis | Medium |
| **Web search / read-URL** | Vibe | Open-ended retrieval | Deliberately declined. Our news layer's contract is that it "may only report what it counted, never what it concluded"; unbounded web text breaks that at the source |

### Things *they* lack that we have

Worth recording, because it bounds how much to copy:

- Neither has anything like our **rule DSL with per-horizon evidence** — `hit_rate` beside `baseline_hit_rate`, `edge`, `independent_sample_size`, significance. Vibe's `strategy_discovery` is the nearest and it is coarser.
- Neither has a **tax engine** (wash sales, Form 8949, lot accounting).
- Neither has **13F institutional consensus and period deltas**.
- Neither has our **pre-registration and holdout discipline** (`thesis/preregister.py`, `holdout_windows`, the FDR ledger).
- TradingAgents has no execution layer at all, and no position or cash field anywhere in `AgentState`; sizing exists only as free text.

---

## 4. Architecture and logic worth adopting beyond these two tabs

These are the findings that generalise past the Agent Desk feature.

**4.1 A grounding gate as a system-wide facility.** Section 2. `app.report.narrative.verify` already does a narrow version for one page. Generalised — extract numeric claims, check against a provenance-carrying evidence set, retry with the failure quoted, degrade visibly — it becomes the thing that lets a model write user-facing prose anywhere in this application without the no-digits prohibition.

**4.2 Decision memory with outcome-resolved reflection.** TradingAgents writes a `pending` entry at decision time with **no model call**, and resolves it at the *start* of the next run for that ticker: fetch realised return, compute alpha against an exchange-matched benchmark, generate a 2–4 sentence lesson, batch-write atomically. Only the Portfolio Manager reads the lessons. This is directly applicable to the evolution loop's reviewer, and it is the mechanism the owner's "score the live matrix rather than add a fourth gate" instinct has been reaching for — a record of what was decided, what happened, and what was learned, that accumulates without anyone maintaining it.

**4.3 A typed vendor-failure taxonomy with no silent fallback.** TradingAgents' `route_to_vendor` distinguishes `VendorRateLimitError`, `VendorNotConfiguredError` and `NoMarketDataError`; the configured vendor string **is** the chain, so nothing silently falls through to a vendor the operator did not choose; optional categories degrade to a `DATA_UNAVAILABLE:` sentinel while core categories raise. And when every vendor reports no data it returns a sentence written *at the model*: `NO_DATA_AVAILABLE: ... Do not estimate or fabricate values`. Our `ProviderRegistry._walk` already has typed failures; it does not have the model-facing sentinel, and that is the cheap half.

**4.4 Three terminal states, not two.** `blocked` ≠ `failed` ≠ `incomplete` (Vibe), and `degraded` ≠ `succeeded`. We have paid for eliding this: a loop reported "running" while failing 1,644 times consecutively, because per-iteration resilience hid the aggregate. Any fan-out we build should carry the distinction into its data model, not just its logs.

**4.5 A run manifest.** Vibe writes `run_manifest.json` per run: a **hash** of the system prompt (never the prompt itself), the tool names available, and the versions of key packages. Cheap, and it answers "why did this run behave differently from that one" without keeping every prompt.

**4.6 Staleness as a refusal, not a warning.** `stockstats_utils._assert_ohlcv_not_stale` raises `NoMarketDataError` when a frame is present but older than `MAX_OHLCV_STALE_DAYS = 10`. We warn on stale bars and serve them. For a page a human reads, warning is right; for a model that will quote the number, refusing is better.

**4.7 Look-ahead prevention in news windows.** `yfinance_news._in_news_window` uses a half-open UTC-normalised `[start, end+1day)` and keeps undated articles **only** in live runs, excluding them from historical windows. Three separate upstream issues produced that rule. Anything we build that replays news against a past date needs the same.

**4.8 Identity resolution as an enforced turn.** Vibe requires `search_symbol` to run in its own turn before any market-sensitive tool for an unresolved symbol, and blocks the call otherwise. Our symbol handling is looser; this matters the moment a user can type a free-text company name.

**4.9 Prompt-cache-aware prompt assembly.** Both systems order the prompt frozen-part-first so the cached prefix is stable. We already do this in `app.agents.client` (frozen `prompts.py` constants in `system`, everything volatile in `user`) — worth keeping in mind as the prompt count grows, because a single volatile byte early in the request defeats caching for the whole call.

**4.10 The mandate pattern, if live execution is ever considered.** Vibe's `src/live/` is the most careful part of either repo: frozen hard caps read once at boot with **no write path from the agent loop**; a consent token hash binding to explicit human approval; a **30-day default expiry that fails closed**; a fixed-order pre-trade gate where first failure wins and any unparseable input denies; a file-locked UTC daily counter; a global and per-broker kill switch; and cancel-only-on-halt as the default with flatten as explicit opt-in. Two eToro write operations are paper-only and fail closed on live. This is the template. It is recorded here so that if the question ever arises, the answer starts from a known-good design rather than a blank page.

---

## 5. Two things to be careful about when copying

**5.1 Rating tiers differ within TradingAgents itself.** The Research Manager and Portfolio Manager emit 5 tiers (Buy / Overweight / Hold / Underweight / Sell); the Trader emits 3 (Buy / Hold / Sell). Mixing them silently produces a decision surface that looks more precise than it is.

**5.2 Dead machinery exists in the source.** TradingAgents registers a `tools_social` ToolNode for the Sentiment Analyst that can never fire — the node pre-fetches and never emits `tool_calls`, so its router always routes to the message-clear node. Copying the graph faithfully would copy the dead edge. Read what runs, not what is registered.
