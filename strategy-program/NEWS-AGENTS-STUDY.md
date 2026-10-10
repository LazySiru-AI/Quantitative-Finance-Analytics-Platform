# News + Sentiment Agent Architectures: A Study of TradingAgents and Vibe-Trading

*Written 2026-08-24.* This document is a source-grounded architecture study of two open-source
multi-agent trading-research projects, produced to inform a later phase of work that will build an
analogous "news + sentiment analysis" agent pipeline inside a different application (a Python
FastAPI backend + React frontend with its own market-bar store, indicator library, and rules-DSL
strategy engine). Both repositories were cloned shallow (`git clone --depth 1`) into a scratch
directory and read directly as source — no README-only summarization. Every claim below cites a
`repo/path/to/file.py` (or `.yaml`) location; anything I could not confirm from source is called out
explicitly rather than guessed. The two projects turned out to be architecturally very different:
TradingAgents is a LangGraph state machine with iterative bull/bear and risk debates; Vibe-Trading is
a custom (non-LangGraph) ReAct agent loop plus a from-scratch DAG "swarm" orchestrator with dozens of
YAML-defined agent-team presets, one of which is a sentiment-intelligence pipeline.

**Research method used**: both repositories were cloned with `git clone --depth 1` into
`C:\Users\<user>\AppData\Local\Temp\claude\...\scratchpad\ext\{TradingAgents,Vibe-Trading}` and read
with the local file-reading tool (not WebFetch/GitHub API — cloning succeeded for both, so the
fallback methods were not needed). Line numbers are omitted from citations because both repos change
frequently; the cited files were read in full or in the specific sections quoted.

---

# Part 1 — TauricResearch/TradingAgents

## 1.1 Agent inventory

TradingAgents wires every agent as a LangGraph node built by a `create_*` factory function. The
table below lists every distinct agent/role, its exact node name as registered in the graph, a
one-sentence summary of its system prompt's job, and its source file.

| Agent (node name in graph) | Factory function | File | Job (one sentence) |
|---|---|---|---|
| Market Analyst | `create_market_analyst` | `tradingagents/agents/analysts/market_analyst.py` | Picks up to 8 complementary technical indicators, calls `get_stock_data`/`get_indicators`/`get_verified_market_snapshot`, and writes a technical-analysis report. |
| Sentiment Analyst (node label `Sentiment Analyst`; wire key stays `social`) | `create_sentiment_analyst` (alias `create_social_media_analyst` deprecated) | `tradingagents/agents/analysts/sentiment_analyst.py` | Pre-fetches Yahoo news + StockTwits + Reddit into the prompt (no tool-calling) and produces a structured `SentimentReport` (band, 0-10 score, confidence, narrative). |
| News Analyst | `create_news_analyst` | `tradingagents/agents/analysts/news_analyst.py` | Calls `get_news`, `get_global_news`, `get_macro_indicators` (FRED), and `get_prediction_markets` (Polymarket) to write a macro/news report with a markdown summary table. |
| Fundamentals Analyst | `create_fundamentals_analyst` | `tradingagents/agents/analysts/fundamentals_analyst.py` | Calls `get_fundamentals`/`get_balance_sheet`/`get_cashflow`/`get_income_statement` and writes a fundamentals report. |
| Bull Researcher | `create_bull_researcher` | `tradingagents/agents/researchers/bull_researcher.py` | Argues the long case, explicitly rebutting the last bear argument, reading all four analyst reports plus debate history. |
| Bear Researcher | `create_bear_researcher` | `tradingagents/agents/researchers/bear_researcher.py` | Argues the short case, explicitly rebutting the last bull argument. |
| Research Manager | `create_research_manager` | `tradingagents/agents/managers/research_manager.py` | Judges the bull/bear debate and emits a structured `ResearchPlan` (5-tier rating + rationale + strategic actions) for the trader. |
| Trader | `create_trader` | `tradingagents/agents/trader/trader.py` | Turns the Research Manager's plan into a structured `TraderProposal` (Buy/Hold/Sell + reasoning + optional entry/stop/sizing). |
| Aggressive (Risk) Analyst | `create_aggressive_debator` | `tradingagents/agents/risk_mgmt/aggressive_debator.py` | Champions high-reward, high-risk execution of the trader's plan, rebutting the conservative and neutral analysts. |
| Conservative (Risk) Analyst | `create_conservative_debator` | `tradingagents/agents/risk_mgmt/conservative_debator.py` | Champions capital preservation, rebutting the aggressive and neutral analysts. |
| Neutral (Risk) Analyst | `create_neutral_debator` | `tradingagents/agents/risk_mgmt/neutral_debator.py` | Balances the two extremes, rebutting both. |
| Portfolio Manager | `create_portfolio_manager` | `tradingagents/agents/managers/portfolio_manager.py` | Synthesizes the risk debate into a structured `PortfolioDecision` (5-tier rating, executive summary, investment thesis, optional price target/time horizon) — the final output. |
| Msg Clear {Market,Sentiment,News,Fundamentals} | `create_msg_delete` | `tradingagents/agents/__init__.py` (imported into `setup.py`) | Utility node that clears the tool-call scratch messages between an analyst and the next graph stage. |

Which analysts run depends on `selected_analysts` (default `("market", "social", "news",
"fundamentals")`, set in `TradingAgentsGraph.__init__`, `tradingagents/graph/trading_graph.py`). The
Bull/Bear Researchers, Research Manager, Trader, three Risk Analysts, and Portfolio Manager are
always present regardless of analyst selection (`tradingagents/graph/setup.py`).

## 1.2 Orchestration graph

TradingAgents is confirmed to use **LangGraph** — `tradingagents/graph/setup.py` imports
`from langgraph.graph import END, START, StateGraph` and `from langgraph.prebuilt import ToolNode`,
and `TradingAgentsGraph.__init__` (`tradingagents/graph/trading_graph.py`) calls
`self.workflow = self.graph_setup.setup_graph(selected_analysts)` then `self.graph =
self.workflow.compile()`.

**Node registration** (`tradingagents/graph/setup.py`, `GraphSetup.setup_graph`):

```python
workflow = StateGraph(AgentState)

# Add analyst nodes to the graph
for spec in plan.specs:
    workflow.add_node(spec.agent_node, analyst_factories[spec.key]())
    workflow.add_node(spec.clear_node, create_msg_delete())
    workflow.add_node(spec.tool_node, self.tool_nodes[spec.key])

# Add other nodes
workflow.add_node("Bull Researcher", bull_researcher_node)
workflow.add_node("Bear Researcher", bear_researcher_node)
workflow.add_node("Research Manager", research_manager_node)
workflow.add_node("Trader", trader_node)
workflow.add_node("Aggressive Analyst", aggressive_analyst)
workflow.add_node("Neutral Analyst", neutral_analyst)
workflow.add_node("Conservative Analyst", conservative_analyst)
workflow.add_node("Portfolio Manager", portfolio_manager_node)
```

**Edge wiring** (same file):

```python
workflow.add_edge(START, plan.specs[0].agent_node)

for i, spec in enumerate(plan.specs):
    workflow.add_conditional_edges(
        spec.agent_node,
        getattr(self.conditional_logic, f"should_continue_{spec.key}"),
        [spec.tool_node, spec.clear_node],
    )
    workflow.add_edge(spec.tool_node, spec.agent_node)
    if i < len(plan.specs) - 1:
        workflow.add_edge(spec.clear_node, plan.specs[i + 1].agent_node)
    else:
        workflow.add_edge(spec.clear_node, "Bull Researcher")

for debate_node in ("Bull Researcher", "Bear Researcher"):
    workflow.add_conditional_edges(
        debate_node, self.conditional_logic.should_continue_debate, DEBATE_PATH_MAP,
    )
workflow.add_edge("Research Manager", "Trader")
workflow.add_edge("Trader", "Aggressive Analyst")
for risk_node in ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"):
    workflow.add_conditional_edges(
        risk_node, self.conditional_logic.should_continue_risk_analysis, RISK_ANALYSIS_PATH_MAP,
    )
workflow.add_edge("Portfolio Manager", END)
```

**This is the single most important architectural fact to get right: the four analysts (Market,
Sentiment, News, Fundamentals) run strictly in SEQUENCE, not in parallel.** Each analyst is a
tool-calling ReAct loop (`should_continue_market`/`should_continue_social`/`should_continue_news`/
`should_continue_fundamentals` in `tradingagents/graph/conditional_logic.py` route back to the
analyst's own `ToolNode` until it stops calling tools, then to a "Msg Clear" node), and only after
one analyst's `Msg Clear` node fires does the graph edge to the *next* analyst. The order is whatever
order `selected_analysts` lists them in (default market → social → news → fundamentals, per
`AnalystExecutionPlan` in `tradingagents/graph/analyst_execution.py`). There is no fan-out/fan-in for
the analyst stage. Parallelism only exists implicitly in the sense that within one analyst's own
ReAct loop, LangGraph's `ToolNode` can execute multiple tool calls from a single LLM turn, but that
is not cross-analyst parallelism.

After the last analyst's `Msg Clear` node, the graph moves to **Bull Researcher**, which begins the
debate loop (§1.3), then **Research Manager → Trader → Aggressive Analyst**, which begins the risk
debate loop, ending at **Portfolio Manager → END**.

**Hand-off payload between stages** is the shared `AgentState` (a `TypedDict` extending LangGraph's
`MessagesState` — see `tradingagents/agents/utils/agent_states.py`): each analyst writes its own
report field (`market_report`, `sentiment_report`, `news_report`, `fundamentals_report`); the debate
stage reads all four report fields plus `instrument_context` and writes `investment_plan`; the Trader
reads `investment_plan` and writes `trader_investment_plan`; the risk debate reads
`trader_investment_plan` plus all four analyst reports and writes `final_trade_decision`.

**ASCII diagram of the compiled graph** (sequential analyst chain shown collapsed since its internal
shape is identical per analyst):

```
START
  |
  v
[Market Analyst] <-> tools_market  --clear-->  [Sentiment Analyst] <-> tools_social  --clear-->
  [News Analyst] <-> tools_news  --clear-->  [Fundamentals Analyst] <-> tools_fundamentals  --clear-->
  |
  v
[Bull Researcher] <==> [Bear Researcher]   (loop until count >= 2*max_debate_rounds)
  |
  v
[Research Manager] --> [Trader] --> [Aggressive Analyst] -> [Conservative Analyst] -> [Neutral Analyst]
  ^                                        (loop until count >= 3*max_risk_discuss_rounds)  |
  |________________________________________________________________________________________|
  |
  v
[Portfolio Manager] --> END
```

## 1.3 The debate/reflection mechanism

There are two independent, structurally identical round-robin debate loops, both driven by counters
in the shared state and both routed by `ConditionalLogic` methods
(`tradingagents/graph/conditional_logic.py`):

**Research debate (bull/bear).** `should_continue_debate`:

```python
def should_continue_debate(self, state: AgentState) -> str:
    if state["investment_debate_state"]["count"] >= 2 * self.max_debate_rounds:
        return "Research Manager"
    if state["investment_debate_state"]["current_response"].startswith("Bull"):
        return "Bear Researcher"
    return "Bull Researcher"
```

`max_debate_rounds` defaults to `1` (`tradingagents/default_config.py`), so the loop terminates after
`count >= 2` — i.e. one bull turn + one bear turn constitutes "1 round"; each turn increments `count`
by 1 in the returned state (`bull_node`/`bear_node` in the respective files: `"count":
investment_debate_state["count"] + 1`). The termination condition is a **fixed round budget**, not a
consensus/convergence check — there is no LLM adjudicating "is the debate settled," only a counter.
Who speaks next alternates strictly by inspecting whether `current_response` starts with `"Bull"` or
not (bear always follows bull and vice versa). After the round budget is exhausted, control passes
to the **Research Manager**, which is the adjudicator: it reads the full `history` string (the
concatenation of every bull/bear turn) and emits a `ResearchPlan` — this is a single LLM call, not
another loop.

**Risk debate (aggressive/conservative/neutral).** `should_continue_risk_analysis`:

```python
def should_continue_risk_analysis(self, state: AgentState) -> str:
    if state["risk_debate_state"]["count"] >= 3 * self.max_risk_discuss_rounds:
        return "Portfolio Manager"
    if state["risk_debate_state"]["latest_speaker"].startswith("Aggressive"):
        return "Conservative Analyst"
    if state["risk_debate_state"]["latest_speaker"].startswith("Conservative"):
        return "Neutral Analyst"
    return "Aggressive Analyst"
```

`max_risk_discuss_rounds` also defaults to `1`, so the loop terminates after `count >= 3` (one full
Aggressive → Conservative → Neutral cycle = "1 round"). Speaking order is a fixed rotation
(Aggressive → Conservative → Neutral → Aggressive → …), gated purely by `latest_speaker`, again a
counter-based budget with no convergence check. After the budget the graph routes to **Portfolio
Manager**, the adjudicator, which reads `risk_debate_state["history"]` (the full risk-debate
transcript) plus the Research Manager's plan and the Trader's proposal and emits the final
`PortfolioDecision`.

**State accumulation.** Both debates accumulate in dedicated `TypedDict` sub-states inside
`AgentState` (`tradingagents/agents/utils/agent_states.py`):

```python
class InvestDebateState(TypedDict):
    bull_history: Annotated[str, "Bullish Conversation history"]
    bear_history: Annotated[str, "Bearish Conversation history"]
    history: Annotated[str, "Conversation history"]
    current_response: Annotated[str, "Latest response"]
    judge_decision: Annotated[str, "Final judge decision"]
    count: Annotated[int, "Length of the current conversation"]

class RiskDebateState(TypedDict):
    aggressive_history: Annotated[str, "..."]
    conservative_history: Annotated[str, "..."]
    neutral_history: Annotated[str, "..."]
    history: Annotated[str, "Conversation history"]
    latest_speaker: Annotated[str, "Analyst that spoke last"]
    current_aggressive_response: Annotated[str, "..."]
    current_conservative_response: Annotated[str, "..."]
    current_neutral_response: Annotated[str, "..."]
    judge_decision: Annotated[str, "Judge's decision"]
    count: Annotated[int, "Length of the current conversation"]
```

Every speaker's node function does a plain string-concatenation append to `history` and its own
per-role `*_history` field, then returns the updated dict as its LangGraph node output (LangGraph
merges dict-returning node outputs into state by key, no reducer needed since each field is fully
overwritten each turn). Both debates are pure text accumulation — there is no vector store, no
message-array, no summarization.

**A third, separate "reflection" mechanism** exists outside the graph: `tradingagents/graph/
reflection.py`'s `Reflector.reflect_on_final_decision` is called *after* a run, once the realized
market return is known (`TradingAgentsGraph._resolve_pending_entries`, called at the start of the
*next* `propagate()` call for the same ticker — see `trading_graph.py`). It is a single LLM call that
writes a 2-4 sentence lesson into an append-only markdown decision log
(`tradingagents/agents/utils/memory.py`, `TradingMemoryLog`), which is then re-injected as
`past_context` into the Portfolio Manager's prompt on future runs (`get_past_context`, same file).
This is not iterative and is not in-graph; it is a deferred, outcome-conditioned journal, not a
debate.

## 1.4 Tool inventory

Every tool is a `@tool`-decorated thin wrapper in `tradingagents/agents/utils/*_tools.py` that calls
`route_to_vendor(method_name, *args)` (`tradingagents/dataflows/interface.py`), which resolves the
configured vendor chain per method/category and tries each vendor in order, degrading to a sentinel
string (`NO_DATA_AVAILABLE: ...` or `DATA_UNAVAILABLE: ...`) rather than raising, for
`OPTIONAL_CATEGORIES = {"macro_data", "prediction_markets"}`.

| Tool (function name) | Source data | Live/cached | Signature | File |
|---|---|---|---|---|
| `get_stock_data` | yfinance (default) or Alpha Vantage | Live HTTP, no local cache layer visible | `(symbol, start_date, end_date) -> str` (OHLCV as formatted text) | `tradingagents/agents/utils/core_stock_tools.py` → `tradingagents/dataflows/y_finance.py` / `alpha_vantage_stock.py` |
| `get_indicators` | yfinance-derived (`stockstats`) or Alpha Vantage | Live | `(symbol, indicator, curr_date, look_back_days=30) -> str`; splits comma-separated indicator lists and calls the vendor once per indicator | `tradingagents/agents/utils/technical_indicators_tools.py` |
| `get_verified_market_snapshot` | yfinance, via `market_data_validator.py` | Live, deterministic (non-LLM) computation over fetched OHLCV | `(symbol, curr_date, look_back_days=30) -> str`; returns latest OHLCV row + indicators as ground truth to prevent hallucinated exact numbers | `tradingagents/agents/utils/market_data_validation_tools.py` → `tradingagents/dataflows/market_data_validator.py` |
| `get_news` | yfinance news (default) or Alpha Vantage | Live | `(ticker, start_date, end_date) -> str`; look-ahead-safe window filter on `pub_date` | `tradingagents/agents/utils/news_data_tools.py` → `tradingagents/dataflows/yfinance_news.py` |
| `get_global_news` | yfinance `Search` across a configured list of macro queries, or Alpha Vantage | Live | `(curr_date, look_back_days=None, limit=None) -> str`; defaults from `global_news_lookback_days`/`global_news_article_limit` config | same files |
| `get_insider_transactions` | yfinance or Alpha Vantage | Live | `(ticker) -> str` | `tradingagents/agents/utils/news_data_tools.py` |
| `get_macro_indicators` | **FRED** (St. Louis Fed API) | Live, requires `FRED_API_KEY` env var (free key); optional category — degrades gracefully if unset | `(indicator, curr_date, look_back_days=None) -> str`; `indicator` accepts curated aliases (`cpi`, `fed_funds_rate`, `10y_treasury`, `unemployment`, `vix`, etc., mapped in `MACRO_SERIES`) or a raw FRED series ID | `tradingagents/agents/utils/macro_data_tools.py` → `tradingagents/dataflows/fred.py` |
| `get_prediction_markets` | **Polymarket** public Gamma API (`gamma-api.polymarket.com`) | Live, no key required (keyless) | `(topic, limit=None) -> str`; searches open markets by keyword, ranks by traded volume, returns implied probability, volume, resolution date, 1-week move | `tradingagents/agents/utils/prediction_markets_tools.py` → `tradingagents/dataflows/polymarket.py` |
| `get_fundamentals` / `get_balance_sheet` / `get_cashflow` / `get_income_statement` | yfinance or Alpha Vantage | Live | `(ticker, curr_date)` or `(ticker, freq="quarterly", curr_date=None)` | `tradingagents/agents/utils/fundamental_data_tools.py` |
| **StockTwits fetcher** (not a `@tool`, called directly by the Sentiment Analyst) | `api.stocktwits.com/api/2/streams/symbol/{ticker}.json` public per-symbol stream | Live, no API key/OAuth | `fetch_stocktwits_messages(ticker, limit=30, timeout=10.0) -> str`; returns bullish/bearish/unlabeled counts + message list, degrades to a placeholder string on failure | `tradingagents/dataflows/stocktwits.py` |
| **Reddit fetcher** (not a `@tool`, called directly by the Sentiment Analyst) | Reddit's public Atom/RSS search feed (`reddit.com/r/{sub}/search.rss`) — the richer JSON `search.json` endpoint is WAF-blocked (403) for public clients per issue #862, so RSS is the default path | Live, no key; scores/comments unavailable via RSS (only via the blocked JSON path) | `fetch_reddit_posts(ticker, subreddits=("wallstreetbets","stocks","investing"), limit_per_sub=5) -> str` | `tradingagents/dataflows/reddit.py` |

The Sentiment Analyst (`tradingagents/agents/analysts/sentiment_analyst.py`) is the one agent that
does **not** use LangChain tool-calling for its data: it pre-fetches all three sources
(`get_news.func(...)`, `fetch_stocktwits_messages(...)`, `fetch_reddit_posts(...)`) synchronously
before the single LLM call, and its prompt explicitly instructs `NO_EXTERNAL_TOOLS` — "the model
sometimes reaches for a search tool when structured-output binding leaves only the schema tool
available, discarding the structured call" is the documented reason
(`tradingagents/agents/utils/structured.py`, comment on `NO_EXTERNAL_TOOLS`).

Vendor routing is fully explicit and never silently substitutes an unconfigured vendor
(`tradingagents/dataflows/interface.py`, `route_to_vendor`): "The configured vendor list IS the
chain: we do NOT silently fall back to vendors the user did not choose (#988/#289)." Default vendor
config (`tradingagents/default_config.py`, `data_vendors`): `core_stock_apis: yfinance`,
`technical_indicators: yfinance`, `fundamental_data: yfinance`, `news_data: yfinance`, `macro_data:
fred`, `prediction_markets: polymarket`.

## 1.5 LLM usage

Two model tiers, both instantiated in `TradingAgentsGraph.__init__` (`tradingagents/graph/
trading_graph.py`):

```python
deep_client = create_llm_client(provider=self.config["llm_provider"], model=self.config["deep_think_llm"], ...)
quick_client = create_llm_client(provider=self.config["llm_provider"], model=self.config["quick_think_llm"], ...)
self.deep_thinking_llm = deep_client.get_llm()
self.quick_thinking_llm = quick_client.get_llm()
```

- **Quick-thinking model** (`quick_think_llm`, default `"gpt-5.4-mini"`) powers all four analysts, both
  researchers, the Trader, all three risk debators, the `Reflector`, and the `SignalProcessor`.
- **Deep-thinking model** (`deep_think_llm`, default `"gpt-5.5"`) powers only the two adjudicators:
  Research Manager and Portfolio Manager (`GraphSetup.setup_graph`,
  `tradingagents/graph/setup.py`: `create_research_manager(self.deep_thinking_llm)`,
  `create_portfolio_manager(self.deep_thinking_llm)`).

Provider is pluggable via `tradingagents/llm_clients/factory.py`
(`create_llm_client`) — dedicated clients for `anthropic`, `google`, `azure`, `bedrock`, and a
catch-all `openai`-compatible path (`is_openai_compatible`) that covers OpenAI, DeepSeek, GLM,
Qwen, Kimi, MiniMax, Ollama, OpenRouter, etc. (enumerated in `tradingagents/llm_clients/
model_catalog.py`, not fully re-read here). Provider-specific reasoning knobs (`google_thinking_level`,
`openai_reasoning_effort`, `anthropic_effort`) are forwarded conditionally in
`TradingAgentsGraph._get_provider_kwargs`.

**Output parsing** is a hybrid: most analysts (Market, News, Fundamentals) and both researchers use
free-text generation gated by a `FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**` stop-signal
convention checked by string-matching. The four decision-shaping agents (Sentiment Analyst, Research
Manager, Trader, Portfolio Manager) use **structured output** via
`tradingagents/agents/utils/structured.py`: `bind_structured(llm, PydanticSchema, agent_name)` wraps
`llm.with_structured_output(schema)` (LangChain's native structured-output — `json_schema` for
OpenAI/xAI, `response_schema` for Gemini, tool-use for Anthropic, per the module docstring), and
`invoke_structured_or_freetext` runs the structured call, falling back to plain `llm.invoke(...)` on
any exception (including a `None` parse result). The Pydantic schemas
(`tradingagents/agents/schemas.py`) are: `SentimentReport` (band/score/confidence/narrative),
`ResearchPlan` (recommendation/rationale/strategic_actions), `TraderProposal`
(action/reasoning/entry_price/stop_loss/position_sizing), `PortfolioDecision`
(rating/executive_summary/investment_thesis/price_target/time_horizon). Each has a `render_*`
function that turns the parsed object back into the same markdown shape the rest of the pipeline
(memory log, CLI, saved reports) already expects, so structured output is layered on top of a
prose-first system rather than replacing it.

## 1.6 Configuration surface

`tradingagents/default_config.py` defines `DEFAULT_CONFIG`, a dict with (env-overridable via a
`_ENV_OVERRIDES` mapping of `TRADINGAGENTS_*` variables to config keys):

| Key | Default | Notes |
|---|---|---|
| `results_dir` | `~/.tradingagents/logs` | |
| `data_cache_dir` | `~/.tradingagents/cache` | |
| `memory_log_path` | `~/.tradingagents/memory/trading_memory.md` | append-only decision log |
| `memory_log_max_entries` | `None` | optional rotation cap on resolved entries |
| `llm_provider` | `"openai"` | |
| `deep_think_llm` | `"gpt-5.5"` | |
| `quick_think_llm` | `"gpt-5.4-mini"` | |
| `backend_url` | `None` | provider default endpoint unless overridden |
| `google_thinking_level` / `openai_reasoning_effort` / `anthropic_effort` | `None` | provider-specific reasoning knobs |
| `temperature` | `None` | forwarded to every provider when set |
| `llm_max_retries` | `None` | SDK retry budget |
| `checkpoint_enabled` | `False` | LangGraph SqliteSaver checkpoint/resume |
| `output_language` | `"English"` | agent debate stays English regardless; only final reports translate |
| `max_debate_rounds` | `1` | bull/bear round budget |
| `max_risk_discuss_rounds` | `1` | risk debate round budget |
| `max_recur_limit` | `100` | LangGraph recursion limit |
| `news_article_limit` | `20` | per-ticker news cap |
| `global_news_article_limit` | `10` | macro news cap |
| `global_news_lookback_days` | `7` | |
| `global_news_queries` | 5 hardcoded macro search strings (Fed rates, S&P earnings/GDP, geopolitical risk, ECB/BOJ/BOE, oil/commodities) | used by `get_global_news_yfinance` |
| `data_vendors` | see §1.4 | category → vendor chain |
| `tool_vendors` | `{}` | per-tool override, takes precedence over category |
| `benchmark_ticker` | `None` | overrides `benchmark_map` when set |
| `benchmark_map` | suffix → index map (`.T`→`^N225`, `.HK`→`^HSI`, `""`→`SPY`, etc.) | used for alpha calculation in reflection |

## 1.7 How a run is invoked

**Programmatic** (`main.py` at repo root):

```python
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

config = DEFAULT_CONFIG.copy()
ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("NVDA", "2024-05-10")
print(decision)
```

`TradingAgentsGraph.propagate(company_name, trade_date, asset_type="stock")` resolves pending
memory-log reflections, optionally recompiles the graph with a checkpointer, then calls
`self.graph.invoke(init_agent_state, **args)` (or `.stream(...)` in debug mode) and returns
`(final_state, self.process_signal(final_state["final_trade_decision"]))` — the second element is
one of `Buy/Overweight/Hold/Underweight/Sell` extracted deterministically from the rendered
`PortfolioDecision` markdown (`tradingagents/graph/signal_processing.py`).

**CLI**: `pyproject.toml` registers `tradingagents = "cli.main:app"` (a Typer app in `cli/main.py`).
Running `tradingagents` (after `pip install -e .`) launches an interactive prompt (ticker, date,
analyst selection via `select_analysts`, provider/model selection) that ultimately calls the same
`TradingAgentsGraph`/`propagate` path and streams progress via a Rich `Live` layout
(`cli/main.py`, `MessageBuffer`, `run_analysis`).

---

# Part 2 — HKUDS/Vibe-Trading

Vibe-Trading is a much larger, differently-shaped project than TradingAgents: it is a general-purpose
"vibe coding for trading research" CLI agent (a ReAct loop with ~90 tools and ~85 markdown "skills"),
plus a separately-built **swarm** subsystem that runs YAML-defined multi-agent team presets as a DAG.
The sentiment/news-relevant material lives almost entirely in the swarm subsystem, specifically the
`sentiment_intelligence_team` and `investment_committee` presets, so this section focuses there while
still covering the single-agent ReAct core that every swarm worker is built from.

## 2.1 Agent inventory

Vibe-Trading defines agents in two ways: (a) one ad-hoc single agent per interactive/CLI session
(no fixed roster — one ReAct loop, `agent/src/agent/loop.py`, `AgentLoop`), and (b) **swarm presets**,
YAML files under `agent/src/swarm/presets/*.yaml`, each declaring a small team of named agents with
system prompts, tool whitelists, and skill whitelists, parsed into `SwarmAgentSpec`
(`agent/src/swarm/models.py`). There is no LangGraph or other framework class per role — a
`SwarmAgentSpec` is a plain Pydantic model (`id`, `role`, `system_prompt`, `tools`, `skills`,
`max_iterations=25`, `timeout_seconds=300`, `model_name=None`, `max_retries=2`).

There are 32 swarm presets (`agent/src/swarm/presets/*.yaml`); the two most relevant to
"news + sentiment":

**`sentiment_intelligence_team`** (`agent/src/swarm/presets/sentiment_intelligence_team.yaml`,
title "Market Sentiment Intelligence Unit"):

| Agent id | Role | Job (one sentence) | Tools | Skills |
|---|---|---|---|---|
| `news_analyst` | News Intelligence Analyst | Extracts a -100..+100 news sentiment score, key events, and a policy-phase call (loose/neutral/tight) from finance news, policy, and sell-side research summaries. | `bash, read_file, write_file, load_skill, read_url` | `web-reader, sentiment-analysis, social-media-intelligence` |
| `social_analyst` | Social Sentiment Analyst | Extracts a -100..+100 social sentiment score, retail positioning, and a fear/greed dashboard from discussion-heat and behavioral-bias signals. | `bash, read_file, write_file, load_skill, read_url` | `behavioral-finance, sentiment-analysis, social-media-intelligence` |
| `flow_analyst` | Capital Flow Analyst | Extracts a -100..+100 flow sentiment score from block trades, Northbound (Stock Connect), margin balances, and dragon-tiger board data. | `bash, read_file, write_file, load_skill, get_market_data` | `tushare, sentiment-analysis` |
| `signal_synthesizer` | Sentiment Signal Synthesizer | Blends the three upstream scores (news 25% / social 35% / flow 40%) into one composite sentiment score with percentile calibration and a reversal call. | `bash, read_file, write_file, load_skill` | `behavioral-finance, risk-analysis` |

**`investment_committee`** (`agent/src/swarm/presets/investment_committee.yaml`, "Long–short debate
→ risk review → PM final call"):

| Agent id | Role | Job |
|---|---|---|
| `bull_advocate` | Bull-side Researcher | Builds the long thesis from technicals/fundamentals/sentiment (confirmed via `grep` of the file — full system prompt read). |
| `bear_advocate` | Bear-side Researcher | Builds the short thesis (file lists it as a task target `task-bear`; not fully re-read line-by-line, but present as agent `bear_advocate` per `tasks:` section). |
| `risk_officer` | (risk synthesis role) | Consumes both bull and bear outputs (`depends_on: [task-bull, task-bear]`). |
| `portfolio_manager` | (final decision role) | Consumes the risk officer's output (`depends_on: [task-risk]`) and issues the committee's final call. |

Every swarm worker — regardless of preset — is executed by the same generic runner,
`run_worker` in `agent/src/swarm/worker.py`, which builds a system prompt from the `SwarmAgentSpec`
(role, task, upstream summaries, whitelisted skill descriptions, optional "grounding" block of
pre-fetched OHLCV) and drives a **lightweight ReAct loop written inline in `worker.py`** — explicitly
*not* an instantiated `AgentLoop`, per the module docstring: "Uses ChatLLM.chat + manual for-loop
directly (without instantiating AgentLoop), keeping the worker self-contained and the agent core
unchanged."

## 2.2 Orchestration graph

Vibe-Trading's swarm orchestrator is **not built on LangGraph**. `langgraph` *is* listed as a
dependency in `pyproject.toml` (`"langgraph>=1.2.5,<1.3"`), but a repo-wide search
(`grep -rl "langgraph" agent/`) found it imported nowhere under `agent/src` — the only hit is the
dependency line itself in `agent/requirements.txt`. **Not verified**: why `langgraph` is declared as
a dependency when it is not imported; possibly a transitive requirement of `langchain-core`/
`langchain-openai`, or vestigial. The actual orchestrator is hand-written:

- **DAG validation and layering**: `agent/src/swarm/task_store.py`. `validate_dag(tasks)` does a
  DFS cycle check; `topological_layers(tasks)` is a textbook **Kahn's algorithm** implementation that
  groups tasks with satisfied dependencies into layers — "tasks in the same layer can run in
  parallel":

```python
def topological_layers(tasks: list[SwarmTask]) -> list[list[str]]:
    in_degree: dict[str, int] = {t.id: 0 for t in tasks}
    dependents: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        in_degree[task.id] = len(task.depends_on)
        for dep in task.depends_on:
            dependents[dep].append(task.id)
    queue: deque[str] = deque(tid for tid, deg in in_degree.items() if deg == 0)
    layers: list[list[str]] = []
    while queue:
        layer = list(queue); queue.clear(); layers.append(layer)
        for tid in layer:
            for downstream in dependents[tid]:
                in_degree[downstream] -= 1
                if in_degree[downstream] == 0:
                    queue.append(downstream)
    return layers
```

- **Execution**: `agent/src/swarm/runtime.py`, class `SwarmRuntime`. The module docstring states
  the model precisely: "schedules workers by topological layer, parallel within each layer and serial
  between layers." `_execute_run` iterates `layers = topological_layers(run.tasks)`; for each layer it
  calls `_execute_layer`, which submits every task in that layer to a
  `concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers)` (default `max_workers=4`,
  from `SWARM_MAX_WORKERS` env, `agent/src/config/env_schema.py`) and collects results via
  `as_completed(futures, timeout=layer_deadline)`. A task whose `depends_on` is not yet `completed` is
  marked `blocked` and never dispatched (dependency-aware gating, so "a failed upstream silently
  produces an empty... entry" is explicitly guarded against for safety-critical chains like
  `risk_officer`). Each task carries its own retry budget
  (`agent_spec.max_retries`, default 2) via `_run_worker_with_retries`.

**Hand-off payload between stages**: each `SwarmTask` (`agent/src/swarm/models.py`) declares
`input_from: dict[str, str]` mapping a context key to an upstream task id, e.g. (from
`sentiment_intelligence_team.yaml`):

```yaml
- id: task-signal-synthesis
  agent_id: signal_synthesizer
  depends_on: [task-news-intel, task-social-sentiment, task-flow-analysis]
  input_from:
    news_sentiment: task-news-intel
    social_sentiment: task-social-sentiment
    flow_sentiment: task-flow-analysis
```

At runtime, `_execute_layer` builds `upstream: dict[str, str]` from `task_summaries` (a plain
`dict[str, str]` accumulated across layers, keyed by task id, holding each completed worker's text
`summary`) and passes it into the downstream worker's prompt via `build_worker_prompt`
(`agent/src/swarm/worker.py`) as an `{upstream_context}` template substitution. The hand-off unit is
therefore a **single summary string per upstream task**, not the full transcript (contrast
TradingAgents, where the full debate `history` string is passed).

**ASCII diagram of `sentiment_intelligence_team`** (a genuine parallel fan-out, unlike TradingAgents'
sequential analyst chain):

```
                 ┌── news_analyst      (task-news-intel)     ──┐
Layer 0 (parallel) ├── social_analyst   (task-social-sentiment)─┤──► Layer 1
                 └── flow_analyst      (task-flow-analysis)  ──┘
                                                                     |
                                                                     v
                                              signal_synthesizer (task-signal-synthesis)
                                              (depends_on all three; input_from maps each)
```

**ASCII diagram of `investment_committee`**:

```
Layer 0 (parallel): bull_advocate (task-bull)   bear_advocate (task-bear)
                            \                        /
                             v                      v
Layer 1:                       risk_officer (task-risk)
                                      |
                                      v
Layer 2:                   portfolio_manager (task-decision)
```

## 2.3 The debate/reflection mechanism

**Vibe-Trading has no iterative debate loop.** Where TradingAgents' bull/bear and risk debates are
genuine round-robin loops with a counter-based termination condition (`count >= 2*max_debate_rounds`)
gated by a LangGraph conditional edge, Vibe-Trading's closest analogue —
`investment_committee`'s `bull_advocate`/`bear_advocate` — run **once each, in parallel, with no
visibility into each other's output** (both are `depends_on: []`, Layer 0). Only the downstream
`risk_officer` (Layer 1) reads both summaries via `input_from`, and it does so in a single LLM call,
not a back-and-forth. There is no round counter, no "current_response" alternation, and no adjudicator
loop — the DAG *is* the entire mechanism, and it is strictly single-pass per task. The same is true
of `sentiment_intelligence_team`'s three parallel analysts feeding one synthesizer. **This is the
central structural contrast between the two projects**: TradingAgents implements adversarial debate
as a stateful graph loop; Vibe-Trading implements it (to the extent it exists at all) as a one-shot
fan-out/fan-in DAG with no rebuttal round.

Vibe-Trading does have a **cross-run** persistence mechanism analogous in spirit to TradingAgents'
reflection log, but structurally different: `agent/src/agent/memory.py`'s `WorkspaceMemory` (used by
the single-agent `AgentLoop`, not by swarm workers directly) and a separate `persistent_memory`
object passed into `AgentLoop.__init__`. **Not verified in depth**: I read `agent/src/agent/memory.py`
only by reference (imported name), not its full body, so I cannot state its exact schema or whether
it performs outcome-conditioned reflection the way TradingAgents' `Reflector` does. The swarm system
itself has no equivalent of TradingAgents' deferred, alpha-conditioned reflection call.

## 2.4 Tool inventory

Vibe-Trading's tool surface is far larger than TradingAgents' (~90 tool names found via
`grep -n "name = \"" agent/src/tools/*.py`, spanning market data, backtesting, options, on-chain,
SEC filings, and more). Restricting to the tools actually available to the
`sentiment_intelligence_team`/`investment_committee` presets (their `tools:` whitelists) and the two
most directly news/sentiment-relevant tools regardless of preset:

| Tool (`name` attr) | What it hits | Live/offline | Signature (`execute(**kwargs)` args) | File |
|---|---|---|---|---|
| `get_stock_news` | China A-share (SH/SZ/BJ): Eastmoney free `search-api` news-list endpoint via a frozen, IP-throttled client. US/HK: Yahoo Finance public v1 search-news via a frozen, IP-throttled client. | Live, no auth for either upstream | `code` (e.g. `"600519.SH"`, required for `scope="stock"`), `scope` (`"stock"`\|`"global"`, default `"stock"`), `limit` (1-50, default 20) | `agent/src/tools/stock_news_tool.py` (routes to `backtest.loaders.eastmoney_client` / `backtest.loaders.yahoo_client`) |
| `sentiment` (class `SentimentTool`) | Two modes: (1) a **local, pure-Python lexicon scorer** (hardcoded positive/negative word sets, no network call) scoring arbitrary text on [-1, 1]; (2) the free, no-auth **alternative.me** Crypto Fear & Greed Index API. | Mode 1 fully offline/deterministic; mode 2 live HTTP | `mode` (`"sentiment_score"`\|`"fear_greed_index"`), `text` (required for mode 1) | `agent/src/tools/sentiment_tool.py` |
| `get_market_data` | Routed through the shared `backtest/loaders/registry.py` — dozens of loader backends (yfinance, ccxt, akshare, tushare, binance, okx, longbridge, futu, mootdx, stooq, tiingo, fmp, alphavantage, sec_edgar, and more; `VALID_SOURCES` enumerates the allow-list). | Live (some loaders support a local on-disk cache via `VIBE_TRADING_DATA_CACHE`/`VIBE_TRADING_DATA_CACHE_ROOT`, per `agent/src/config/env_schema.py`) | Normalized OHLCV fetch; validates `interval` against `_VALID_INTERVALS` and dates as strict ISO `YYYY-MM-DD` | `agent/src/tools/market_data_tool.py` → `src/market_data.py` → `backtest/loaders/*` |
| `get_northbound_flow`, `get_margin_trading`, `get_block_trades`, `get_dragon_tiger`, `get_fund_flow` | China-market capital-flow data (used by `flow_analyst`); exact vendor **not verified** — not read in this pass beyond the tool name list. | **Not verified** | **Not verified** | `agent/src/tools/*.py` (file names not individually confirmed) |
| `load_skill` | Local filesystem read of a markdown skill file under `agent/src/skills/<name>/SKILL.md` (e.g. `sentiment-analysis`, `social-media-intelligence`, `web-reader`, `behavioral-finance`, `tushare`) — these are reference/methodology documents injected into context, not data-fetching tools. | Offline, local files | `skill_name` | `agent/src/agent/skills.py` (`SkillsLoader`, referenced from `worker.py`) |
| `read_url` | Jina Reader (`r.jina.ai`) — converts an arbitrary URL to clean markdown text. | Live, third-party proxy service, no local key documented in the skill file | URL string | `agent/src/skills/web-reader/SKILL.md` describes it; underlying tool implementation **not individually re-read**, referenced as a registered tool name. |
| `financial_rigor` | Deterministic calculator/verifier (`calc`, `verify_market_cap`, `verify_valuation`, `cross_validate`, `benford` commands per `agent/src/agent/loop.py`'s `_verification_ledger` parser) — pure computation, no network. | Offline, deterministic | Not individually read; behavior inferred from `_verification_ledger` in `agent/src/agent/loop.py`, which is the closest analogue to TradingAgents' `get_verified_market_snapshot`. | `agent/src/tools/financial_rigor_tool.py` (file located, not opened) |

The `sentiment-analysis` skill (`agent/src/skills/sentiment-analysis/SKILL.md`, written in Chinese) is
a reference document, not a tool: it gives the agent a scoring methodology (Crypto Fear & Greed
tiers, Put-Call Ratio bands, China margin-financing signals, Northbound-flow signals, a weighted
composite formula `0.25×fear_greed + 0.20×PCR + 0.20×margin + 0.20×northbound + 0.15×social`, and a
position-sizing mapping from composite score to recommended exposure). It is loaded into an agent's
context on demand via the `load_skill` tool call named in each agent's `system_prompt` (e.g. "Use
`load_skill("web-reader")`, `load_skill("sentiment-analysis")`, `read_url`.").

## 2.5 LLM usage

Unlike TradingAgents' fixed two-tier deep/quick split, Vibe-Trading configures **one provider/model
pair globally** via env vars (`agent/src/config/env_schema.py`, class `LLMConfig`):
`LANGCHAIN_PROVIDER` (default `"openai"`), `LANGCHAIN_MODEL_NAME` (default `""`, i.e. provider
default), `LANGCHAIN_TEMPERATURE` (default `0.0`), `LANGCHAIN_REASONING_EFFORT` (default `""`), plus
`LANGCHAIN_USE_RESPONSES_API`. `SwarmRuntime.start_run` captures this at run-creation time into
`run.provider`/`run.model`/`run.reasoning_effort` for audit purposes
(`agent/src/swarm/runtime.py`). **Per-agent override** is supported: `SwarmAgentSpec.model_name:
str | None = None` lets a specific preset agent pin a different model than the run-level default
(`agent/src/swarm/models.py`); none of the sentiment/committee presets read in this pass set
`model_name` explicitly, so they all use the run-level default model — there is no analyst-vs-judge
tiering the way TradingAgents splits quick/deep thinking.

`public_provider_metadata` (`agent/src/swarm/models.py`) enumerates a large allow-list of supported
provider labels for public run metadata: `anthropic, dashscope, deepseek, gemini, glm, groq, iflytek,
kimi, kimi-coding, mimo, minimax, modelscope, moonshot, nvidia, nvidia-nim, ollama, openai,
openai-codex, opencode-go, opencode-zen, openrouter, qwen, requesty, siliconflow-cn,
siliconflow-global, spark, zai, zhipu` — a much broader provider roster than TradingAgents'
`anthropic`/`google`/`azure`/`bedrock`/openai-compatible split, though the actual `ChatLLM` client
implementation (`agent/src/providers/chat.py`) was not individually re-read line-by-line in this pass.

**Output parsing**: the worker loop (`agent/src/swarm/worker.py`) is a plain ReAct tool-call loop
using `ChatLLM.stream_chat`/`.chat`, not LangChain's `with_structured_output`. Each agent's system
prompt spells out the exact markdown "Required outputs" section it must produce (e.g. the sentiment
agents' "News sentiment score — −100 to +100 with methodology and drivers"), and the worker's final
answer (free text) becomes the task's `summary` field, consumed downstream as opaque text via
`input_from` — there is no Pydantic schema layer analogous to TradingAgents'
`agents/schemas.py`. **Not verified**: whether any swarm agent anywhere in the repo uses structured/
JSON-mode output — the four presets and worker code read in this pass all show free-text markdown
output only.

## 2.6 Configuration surface

Configuration is a set of `pydantic`-validated env-var classes in `agent/src/config/env_schema.py`
(class `EnvConfig` aggregates `LLMConfig`, `DataConfig`, `OcrConfig`, `APIConfig`, `SwarmConfig`,
`AgentTuningConfig`, `PathConfig`, `MemoryConfig`). Selected keys relevant to a news/sentiment
pipeline (all with `Field(alias=ENV_VAR_NAME, default=...)`):

| Key (env var) | Default | Class |
|---|---|---|
| `LANGCHAIN_PROVIDER` | `"openai"` | `LLMConfig` |
| `LANGCHAIN_MODEL_NAME` | `""` | `LLMConfig` |
| `LANGCHAIN_TEMPERATURE` | `0.0` | `LLMConfig` |
| `LANGCHAIN_REASONING_EFFORT` | `""` | `LLMConfig` |
| `TIMEOUT_SECONDS` | `120` | `LLMConfig` |
| `MAX_RETRIES` | `2` | `LLMConfig` |
| `TUSHARE_TOKEN`, `FINNHUB_API_KEY`, `ALPHAVANTAGE_API_KEY`, `TIINGO_API_KEY`, `FMP_API_KEY`, `FRED_API_KEY`, `DASHSCOPE_API_KEY` (and many more) | `""` | `DataConfig` — most data vendors require a paid or free-tier key |
| `CCXT_EXCHANGE` | `"binance"` | `DataConfig` |
| `VIBE_TRADING_DATA_CACHE` | `False` | `DataConfig` — opt-in local cache |
| `SWARM_WORKER_TIMEOUT` | `300` (seconds) | `SwarmConfig` — per-worker timeout |
| `SWARM_WORKER_MAX_ITER` | `50` | `SwarmConfig` — matches preset `max_iterations` default seen in YAML |
| `SWARM_MAX_WORKERS` | `4` | `SwarmConfig` — `ThreadPoolExecutor` size, i.e. max concurrency within one DAG layer |
| `SWARM_TIMEOUT` | `1800` (seconds) | `SwarmConfig` — whole-run timeout |
| `SWARM_HEARTBEAT_INTERVAL_S` | `3.0` | `SwarmConfig` |
| `SWARM_GROUNDING_MAX_SYMBOLS` | `8` | `SwarmConfig` — caps how many tickers get pre-fetched OHLCV "grounding" data per run |
| `TOKEN_THRESHOLD` | `40000` | `AgentTuningConfig` — triggers the ReAct loop's context-compaction layers |
| `VIBE_TRADING_TOOL_TIMEOUT_SECONDS` | `1800.0` | `AgentTuningConfig` |
| `VIBE_TRADING_LLM_TIMEOUT_SECONDS` | `300.0` | `AgentTuningConfig` |
| `VIBE_TRADING_RUN_STALL_TIMEOUT_SECONDS` | `1800.0` | `AgentTuningConfig` — zombie-run watchdog |

Individual `SwarmAgentSpec` fields (`max_iterations=25`, `timeout_seconds=300`, `max_retries=2`) are
per-agent overrides of the `SwarmConfig` defaults, set directly in each preset YAML (both presets read
here use `max_iterations: 50, timeout_seconds: 1800, max_retries: 1`).

## 2.7 How a run is invoked

The package entry point (`pyproject.toml`, `[project.scripts]`): `vibe-trading = "cli:main"`
(package root `agent/`, so this is `agent/cli/__main__.py`/`agent/cli/main.py`'s `main()`). Running
`vibe-trading` with no subcommand drops into an interactive REPL
(`agent/cli/_legacy.py`, `cmd_interactive`) that supports slash commands including `/swarm`.

**Swarm invocation is a slash command inside that REPL**, dispatched by `agent/cli/_legacy.py`,
`_handle_swarm_command`:

```
/swarm run <preset> [vars_json]
```

e.g. (constructed from the preset's declared `variables:` — `market: str`, `timeframe: str` — per
`sentiment_intelligence_team.yaml`; exact example invocation **not directly observed** in a README or
test, so the vars_json shape below is inferred from the `variables:` block, not quoted from a working
example):

```
/swarm run sentiment_intelligence_team {"market": "US", "timeframe": "daily"}
```

This calls `cmd_swarm_run_live(preset, vars_json)` → ultimately `SwarmRuntime.start_run(preset_name,
user_vars, ...)` (`agent/src/swarm/runtime.py`), which validates the DAG, launches a background daemon
thread (`self._execute_run`), and returns immediately; progress streams via `SwarmEvent`s. Non-
interactive flags also exist for run management: `--swarm-list`, `--swarm-show RUN_ID`,
`--swarm-cancel RUN_ID` (`agent/cli/_legacy.py` argparse setup, not the run-starting path itself).
There is also a FastAPI server (`agent/api_server.py`, `vibe-trading serve` per `agent/cli/main.py`'s
`@app.command("serve", ...)`) that presumably exposes the same swarm runtime over HTTP/SSE for the
bundled React frontend (`frontend/` directory) — **not verified in depth**; the API route definitions
were not read in this pass.

---

# Part 3 — Comparison and what transfers

## 3.1 Where the two projects agree

- **Both decompose "analysis" into narrow, single-purpose agents with a whitelisted tool set and a
  prompt that names an explicit output contract.** TradingAgents' analysts and Vibe-Trading's swarm
  agents both read like "you are a senior X analyst; call these specific tools; produce these specific
  output fields."
- **Both separate data-gathering agents from a judging/synthesizing agent** that reads the
  gatherers' output and commits to a decision (TradingAgents: Research Manager, Portfolio Manager;
  Vibe-Trading: `signal_synthesizer`, `risk_officer`/`portfolio_manager`).
- **Both treat "no data" as a first-class, agent-visible outcome rather than an exception that
  aborts the run.** TradingAgents' `route_to_vendor` returns an explicit `NO_DATA_AVAILABLE:` /
  `DATA_UNAVAILABLE:` sentinel string with instructions not to fabricate a value
  (`tradingagents/dataflows/interface.py`); Vibe-Trading's tools return a JSON envelope with
  `{"ok": false, "error": "..."}` (e.g. `stock_news_tool.py`'s `_error`) and the sentiment analyst's
  prompt explicitly requires flagging low confidence when a source returns a placeholder.
- **Both favor free, keyless, or low-friction public data surfaces for social/news sentiment
  specifically** (StockTwits and Reddit RSS in TradingAgents; Eastmoney/Yahoo search-news, the
  alternative.me Fear & Greed index, and a local lexicon scorer in Vibe-Trading) — neither project's
  sentiment layer depends on a paid social-listening API.
- **Both persist a decision/summary record for reuse in a later run**, though structurally
  differently (TradingAgents' outcome-conditioned reflection log vs. Vibe-Trading's swarm
  `task_summaries`/run.json artifacts and separate `WorkspaceMemory`).

## 3.2 Where they disagree architecturally

- **Sequential vs. parallel by default.** TradingAgents' four analysts run one after another in a
  fixed chain (§1.2); Vibe-Trading's swarm explicitly fans out independent agents in the same
  topological layer via a thread pool (§2.2). This is the single biggest structural difference and the
  one most likely to matter for a rebuild: TradingAgents' design is *not* "run news + sentiment +
  fundamentals + market in parallel," despite that being an intuitive read of a "multi-agent" system.
- **Iterative adversarial debate vs. one-shot fan-out.** TradingAgents' bull/bear and risk debates are
  genuine round-robin loops with LangGraph conditional edges and a counter-based termination
  condition (§1.3); Vibe-Trading's closest analogue is two independent single-pass analyses merged by
  one downstream synthesizer, with no rebuttal round (§2.3).
- **Framework-driven vs. hand-rolled orchestration.** TradingAgents is a `StateGraph` compiled and
  invoked through LangGraph's runtime, with LangGraph's `ToolNode`, conditional-edge routing, and
  optional `SqliteSaver` checkpointing doing real work. Vibe-Trading declares `langgraph` as a
  dependency but does not appear to use it anywhere in `agent/src`; its orchestrator is ~1,100 lines
  of hand-written Python (`ThreadPoolExecutor` + Kahn's-algorithm layering + a Pydantic run/task model
  + JSON-file persistence per task).
- **Structured output vs. prompted markdown contract.** TradingAgents' decision-shaping agents use
  LangChain's native `with_structured_output` against Pydantic schemas with a free-text fallback
  (§1.5); Vibe-Trading's swarm workers rely entirely on the system prompt's "Required outputs" section
  and free-text parsing downstream (§2.5) — no schema validation layer was found.
- **Fixed two-tier LLM budget vs. one global model with optional per-agent override.** TradingAgents
  hard-splits "quick" (all data/debate agents) vs. "deep" (only the two adjudicators) (§1.5).
  Vibe-Trading uses one configured model for an entire run unless an individual `SwarmAgentSpec`
  overrides it (§2.5); none of the presets examined here exercise that override for a cost/quality
  tier split.
- **Scope.** TradingAgents is a single, focused pipeline (one ticker, one date, one decision).
  Vibe-Trading is a general research agent with 32 swarm presets spanning options, credit, ETFs,
  geopolitics, factor research, etc., of which sentiment/committee analysis is one preset family among
  many; it also ships a large single-agent ReAct core (`agent/src/agent/loop.py`, ~2,800 lines) used
  outside the swarm system entirely, with sophisticated context-compaction machinery (five layers:
  microcompact, context-collapse, LLM auto-compact, an explicit compact tool, iterative summary
  update) that TradingAgents has no equivalent of, because TradingAgents' agents never run long enough
  to need it.

## 3.3 What is portable to a FastAPI + React app with an existing market-bar store, indicator
library, and rules-DSL strategy engine

**Portable, and probably the highest-value transfer:**

- **The `SwarmTask`/`SwarmAgentSpec`/topological-layer execution model** (Vibe-Trading,
  §2.2) is close to a textbook fit for a FastAPI backend: `SwarmTask` and `SwarmAgentSpec` are plain
  Pydantic models, DAG validation is a ~20-line DFS, and layer execution is a `ThreadPoolExecutor`
  loop — no LangGraph dependency required despite the two projects both nominally listing it. This is
  directly reusable as a design pattern (not necessarily the code, given the license question below):
  YAML-declared agent teams with `depends_on`/`input_from` wiring, one JSON file per task for
  resumability, and a background thread per run reporting `SwarmEvent`s that a FastAPI SSE endpoint
  can stream straight to a React frontend — this is architecturally very close to what a "news +
  sentiment" pipeline inside a FastAPI/React app would need, and is simpler to reason about than a
  LangGraph `StateGraph` for a team that has genuinely independent parallel branches.
- **The vendor-routing-with-explicit-fallback pattern** (TradingAgents, §1.4,
  `route_to_vendor`): a category → ordered-vendor-chain config, tried in order, returning a typed
  "no data" sentinel instead of raising or silently degrading — this maps cleanly onto an app that
  already has its own market-bar store as one more "vendor" in the chain (e.g. `internal_bar_store`
  before `yfinance`).
- **The deterministic verification-snapshot pattern** (TradingAgents' `get_verified_market_snapshot`,
  §1.4; Vibe-Trading's `financial_rigor` ledger, §2.4): a non-LLM tool call that returns exact
  numbers as ground truth, explicitly instructed to override any LLM-recalled figure. This is a good
  fit for an app with its own indicator library — the indicator engine itself can be exposed as this
  "verified snapshot" tool, closing the same hallucination gap.
- **The sentiment-scoring rubric in Vibe-Trading's `sentiment-analysis` skill** (§2.4) — the weighted
  composite formula and the tiered percentile→position-sizing mapping — is a reusable *idea*
  (prompting/rubric content, not code) that could seed the prompt for a news+sentiment agent's judge
  step, independent of Vibe-Trading's execution machinery.
- **TradingAgents' three-source sentiment fan-in inside a single agent** (pre-fetch news + StockTwits
  + Reddit into one prompt, no tool-calling, structured output) is a directly reusable pattern for
  a "sentiment analyst" node regardless of which orchestration framework wraps it — it sidesteps the
  tool-calling-vs-structured-output conflict noted in `structured.py`'s `NO_EXTERNAL_TOOLS` comment.

**Not portable, or only partially so, and why:**

- **TradingAgents' iterative bull/bear and risk debate loops depend on LangGraph's conditional-edge
  routing and its `MessagesState`-derived `AgentState`.** Reimplementing an equivalent round-robin
  loop outside LangGraph is possible but is meaningfully more work than the DAG pattern above — it
  needs a mutable "who speaks next" router, a round counter threaded through state, and careful
  handling of what happens when a round budget is hit mid-turn. If a rules-DSL engine already exists
  for signal generation, an iterative LLM debate over trade direction may be redundant with what the
  DSL already encodes deterministically — this is a genuine design question, not just a portability
  one.
- **Most of Vibe-Trading's tool inventory is paid-API-gated.** `DataConfig` in
  `agent/src/config/env_schema.py` lists `TUSHARE_TOKEN`, `FINNHUB_API_KEY`, `ALPHAVANTAGE_API_KEY`,
  `TIINGO_API_KEY`, `FMP_API_KEY`, `LONGBRIDGE_APP_KEY/SECRET`, `ETORO_API_KEY`, and more — a
  meaningful fraction of `get_market_data`'s vendor registry (`backtest/loaders/registry.py`,
  `VALID_SOURCES`) is not usable without paid accounts. Only `get_stock_news` (Eastmoney/Yahoo,
  keyless), the `sentiment` tool's lexicon mode and Fear & Greed index (keyless), and yfinance-backed
  `get_market_data` sources are free out of the box; the rest (Northbound flow, margin/block-trade
  data, most of `flow_analyst`'s inputs) either require paid China-market data vendors or were not
  verified to be free in this pass.
- **TradingAgents' FRED integration also requires a (free) API key** (`FRED_API_KEY`) — keyless but
  not zero-setup; a rebuild should budget for a signup step if macro-series grounding is wanted.
- **Vibe-Trading's five-layer context-compaction machinery in `agent/src/agent/loop.py`** is built
  for a long-running, many-iteration single agent (up to 50 iterations per swarm worker,
  potentially hundreds in the interactive CLI). A news+sentiment pipeline with a handful of
  short, tool-light agent calls per run (closer to TradingAgents' shape) is unlikely to need this;
  porting it would be solving a problem the target app may not have.
- **Vibe-Trading's Reddit/StockTwits equivalents were not found** — Vibe-Trading's social-sentiment
  agent (`social_analyst` in `sentiment_intelligence_team.yaml`) relies on `read_url` (Jina Reader,
  a third-party proxy) plus the `sentiment-analysis` and `social-media-intelligence` skills rather
  than a dedicated Reddit/StockTwits fetcher tool the way TradingAgents has; if the target app wants
  the specific StockTwits-bullish-ratio / Reddit-engagement-weighted pattern, TradingAgents'
  `agent_utils`/`dataflows/reddit.py` and `dataflows/stocktwits.py` are the more directly transferable
  source, both keyless and standalone (~250 lines each, no framework dependency), so their *logic*
  (not verbatim code, per the license note below) is easy to reimplement.
- **License-driven code reuse.** See §3.4 — TradingAgents is Apache-2.0 (code may be vendored with
  attribution and a NOTICE); Vibe-Trading is MIT (code may also be vendored with attribution). Neither
  license blocks reuse, but a from-scratch reimplementation should still be preferred for the
  DAG-orchestrator idea specifically because the target app's existing rules-DSL engine and market-bar
  store are different enough in shape that a direct port (rather than a rewrite following the pattern)
  would fight the existing code more than it would save.

## 3.4 Licenses

- **TradingAgents**: **Apache License 2.0**, confirmed by reading the `LICENSE` file at the repo root
  (`TradingAgents/LICENSE`, first lines: `Apache License / Version 2.0, January 2004`). Apache-2.0
  permits vendoring the code (including modification and redistribution) provided attribution and the
  license text are preserved and any changes are noted; it also grants an express patent license. Safe
  to vendor specific modules (e.g. `dataflows/reddit.py`, `dataflows/stocktwits.py`,
  `dataflows/fred.py`, `dataflows/polymarket.py`) directly with attribution, not just borrow the ideas.
- **Vibe-Trading**: **MIT License**, confirmed by reading the `LICENSE` file at the repo root
  (`Vibe-Trading/LICENSE`, first lines: `MIT License / Copyright (c) 2026 Vibe-Trading Contributors`).
  MIT is at least as permissive as Apache-2.0 (no explicit patent grant, otherwise similar
  attribution-only requirement). A `NOTICE` file also exists at the repo root
  (`Vibe-Trading/NOTICE`) but its contents were not read in this pass — **not verified**: whether it
  imposes any additional third-party attribution obligations beyond the MIT license itself (the skill
  file `agent/src/skills/social-media-intelligence/SKILL.md` does note it is "Inspired by
  `himself65/finance-skills`," which may be relevant to that NOTICE file's contents).

---

## What I could not verify

- **Vibe-Trading's `ChatLLM` provider client** (`agent/src/providers/chat.py`) — not read in full;
  claims about `stream_chat`, `usage_metadata`, and reasoning-effort plumbing are inferred from how
  `agent/src/agent/loop.py` and `agent/src/swarm/worker.py` call it, not from the client's own
  implementation.
- **Vibe-Trading's full tool implementations** for `get_northbound_flow`, `get_margin_trading`,
  `get_block_trades`, `get_dragon_tiger`, `get_fund_flow`, `read_url`, and `financial_rigor` — their
  file locations and tool names were confirmed (via `grep`), and `financial_rigor`'s *output shape*
  was inferred indirectly from `agent/src/agent/loop.py`'s `_verification_ledger` parser, but the tool
  source files themselves were not opened. Their exact data source, signature, and live-vs-cached
  status are therefore not verified beyond what the parser and preset YAML imply.
- **Vibe-Trading's `investment_committee.yaml`** was read only via `grep`/partial view for its
  `bear_advocate`, `risk_officer`, and `portfolio_manager` system prompts — only `bull_advocate`'s
  full system prompt was read verbatim. Their one-sentence job descriptions in §2.1 are inferred from
  role names, the `tasks:`/`depends_on` wiring, and the preset's top-level `description:` field, not
  from their own prompt text.
- **Vibe-Trading's `agent/src/agent/memory.py` (`WorkspaceMemory`) and the separate
  `persistent_memory` object** — only referenced by import name in `agent/src/agent/loop.py` and
  `agent/src/swarm/worker.py`; its internal schema and whether it performs any outcome-conditioned
  reflection were not confirmed.
- **Why Vibe-Trading declares `langgraph` as a dependency while apparently not importing it anywhere
  under `agent/src`.** Confirmed absent via `grep -rl "langgraph" agent/` (only the requirements-file
  line matched), but the reason (transitive requirement vs. vestigial vs. used in a directory not
  searched, e.g. `desktop/` or `tools/`) was not investigated further.
- **Vibe-Trading's FastAPI server routes** (`agent/api_server.py`) and how the bundled React
  `frontend/` consumes swarm runs over HTTP/SSE — the file was located but not opened; §2.7's
  statement that it "presumably exposes the same swarm runtime" is a plausible inference from the
  `@app.command("serve", ...)` CLI wiring and `SwarmEvent`/live-callback plumb0ing in
  `runtime.py`, not a confirmed reading of the route handlers.
- **Vibe-Trading `NOTICE` file contents** — located at the repo root but not read; may carry
  additional third-party attributions beyond the MIT `LICENSE`.
- **An actual worked example of `/swarm run <preset> vars_json`** — the exact JSON shape in §2.7's
  example command was constructed from the preset's declared `variables:` block, not copied from a
  README, test, or transcript that shows a real invocation and its output.
- **TradingAgents' `tradingagents/llm_clients/model_catalog.py`** — referenced as the place that
  enumerates OpenAI-compatible provider aliases (DeepSeek, GLM, Qwen, etc.) but not opened; the
  provider list in §1.5 is taken from `factory.py`'s explicit branches only.
- **Full byte-for-byte configuration surfaces.** Both `tradingagents/default_config.py` and
  `agent/src/config/env_schema.py` were read in full for the sections quoted, but Vibe-Trading's
  `env_schema.py` continues past `AgentTuningConfig` into `PathConfig`, `_MemoryPreset`,
  `MemoryConfig`, and `EnvConfig` (lines beyond what was paged in this pass) — §2.6's table is
  restricted to the classes and keys actually read, not the complete file.

**Not investment advice.** This is a study of two open-source codebases, not a recommendation about real capital.
