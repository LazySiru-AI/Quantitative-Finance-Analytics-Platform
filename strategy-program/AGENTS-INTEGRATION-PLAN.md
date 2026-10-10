# Agents, news and sentiment: what to take from TradingAgents and Vibe-Trading, and how to build it

*Written 2026-08-24.* Companion to [`NEWS-AGENTS-STUDY.md`](NEWS-AGENTS-STUDY.md), which is a
source-grounded architecture study of the two upstream repos. That document answers *what they are*.
This one answers *what we take, what we refuse, and in what order we build it* — grounded in this
application's own code, not in the abstract.

Both clones read for this plan live at `C:/Users/<user>/repos/externalProjects/{TradingAgents,Vibe-Trading}`.
A third, older copy of Vibe-Trading is already vendored at `tools/vendor/Vibe-Trading/` with its own
virtualenv — see §4, Phase A.

---

## 0. The one constraint that decides everything

This application's identity is that **prose may not contain a number nobody computed**.
`app/report/narrative.py` enforces it mechanically: `verify()` refuses a draft that writes a bare
numeral — matched by Unicode category rather than `0-9` — and `render()` will not render a draft that
did not verify. `app/thesis/__init__.py` adds four more refusals: pre-registration by content hash, a
global trial ledger with Benjamini-Hochberg over every thesis ever registered for a ticker, a locked
holdout that burns on a second look, and a declared iteration budget. `strategy-program/PROTOCOL.md`
§3 adds a parameter budget, a no-grid-search rule, and a pre-registered failure regime.

**Both upstream projects violate all of that by design.** TradingAgents' analysts write free prose
full of figures. Vibe-Trading's swarm agents are *asked* for numbers they have no way to compute —
`sentiment_intelligence_team.yaml` requires each agent to emit a score on −100..+100, a "1y/3y
percentile", and "avg excess after similar historical signals", with no verification layer anywhere
in `agent/src/swarm/worker.py`. There is no Pydantic schema and no structured-output path in the
swarm at all: a worker's free text becomes the task `summary` and is consumed downstream as an opaque
string.

So the integration rule, and it is not negotiable:

> **An agent may propose, name, argue and select. An agent may never emit a number.**
> Numbers come from `app/indicators`, `app/backtest`, `app/market` and `app/tax`. Agent output is a
> `NarrativeDraft` of `{{fact:id}}` templates plus the fact ids it cites, and it goes through
> `narrative.verify` against a `FactBundle` exactly as a template-written draft does today.

`app/thesis/author.py` already anticipates precisely this: *"A language model swapped in here changes
who writes the hypothesis and changes nothing about what refuses it."* That sentence is the whole
integration design. Everything below is a consequence of it.

---

## 1. What we already have that a naive port would re-add, worse

| Upstream thing | What we already have | Verdict |
|---|---|---|
| TradingAgents `dataflows/interface.py` `route_to_vendor` — category → ordered vendor chain, degrading to a `NO_DATA_AVAILABLE:` sentinel string | `app/market/registry.py` — the same fallback walk with **typed** outcomes: `SymbolNotFound` terminal, `UnsupportedInterval` skipped silently, `ProviderUnavailable` retried while a `MarketWarning` survives into the response, and one final exception listing what every provider said | **Ours is strictly better.** Do not port. Add news as new providers *inside* our registry. |
| TradingAgents `get_verified_market_snapshot` — a non-LLM tool returning exact OHLCV and indicators as ground truth against hallucinated figures | `app/indicators/`, `app/market/store.py`, and the whole `FactBundle` machinery | Already solved, and solved harder — we refuse the digit rather than offering a correct one beside it. |
| TradingAgents `graph/reflection.py` — a deferred, outcome-conditioned lesson appended to a markdown log and re-injected into later prompts | `app/thesis/ledger.py` (every thesis ever registered, including abandoned ones), the round reports under `strategy-program/`, `app/tournament/findings.py` | Same idea; ours is auditable, has a real denominator, and survives a restart. |
| Vibe-Trading `agent/src/factors/zoo/` — 101 Alpha101 + 191 GTJA + 158 qlib factors | `app/rules/` DSL, `app/backtest/`, the competition protocol | **Actively refuse.** 450 canned factors dropped into a scoring loop is exactly the p-hacking machine `app/thesis/__init__.py` opens by warning about, and PROTOCOL.md §3.3–3.4 (ten free parameters, no grid search) forbids the workflow that makes them useful. |
| Vibe-Trading `agent/backtest/` — 12 market engines, 5 optimizers, walk-forward, Monte Carlo | `app/backtest/` + `app/tournament/` + 16 rounds of recorded results | Ours is measured and reconciled against a real broker statement. Not replacing it. |
| Vibe-Trading's `sentiment` tool, `fear_greed_index` mode — alternative.me, the **crypto** Fear & Greed index | `app/market/providers/cnn.py` (CNN's equity index) **plus** `app/market/fear_greed.py`, our own tanh-calibrated composite from the raw components, which fills in when CNN's undocumented endpoint breaks | Ours is the right index for a US equity book. Theirs measures Bitcoin. |
| Vibe-Trading's five-layer context compaction in `agent/src/agent/loop.py` | — | Not needed. It exists because a VT worker runs up to 50 tool iterations. Our agents will make a handful of short calls, TradingAgents-shaped. Porting it solves a problem we do not have. |
| TradingAgents' LangGraph `StateGraph` runtime | `app/tournament/jobs.py` — an in-process registry with a daemon worker thread, a process-wide single-job lock, a `threading.Event` the worker actually checks for cancellation, per-window reconciliation, and `POST/GET/DELETE /api/competition/jobs` already wired | We have the substrate. See §4, Phase E. Note that Vibe-Trading declares `langgraph` as a dependency and imports it nowhere under `agent/src` — do not read its presence as an endorsement. |

**Conclusion:** the valuable half of both repos, for us, is **data we do not have** and **an
orchestration shape**. Not analytics. We have the analytics.

---

## 2. What we genuinely lack

Confirmed by `grep -ril "stocktwits|reddit|sentiment|news" backend/app` — the only hits are
`market/fear_greed.py`, `market/macro_models.py`, `market/registry.py` and the two `mcp/` files, and
none of them touch news:

1. **No news data of any kind.** Not per-ticker, not macro.
2. **No social sentiment.** No StockTwits, no Reddit, no message-volume signal.
3. **No prediction-market data.** Nothing that prices an event.
4. **No LLM wired anywhere.** By deliberate choice, stated in three separate docstrings — but the
   guards were built assuming one would eventually arrive.
5. **No multi-step agent orchestration.** `tournament/jobs.py` runs one round; it does not run a DAG
   of dependent workers.

Everything in §3 exists to fill those five gaps and nothing else.

---

## 3. The adoption matrix

Licences permit vendoring either way: **TradingAgents is Apache-2.0**, **Vibe-Trading is MIT**. Both
require attribution; `docs/ATTRIBUTION.md` is where it goes. Apache-2.0 additionally requires noting
modifications and carrying the licence text, so vendored TA files keep a header.

### 3a. Vendor the code — small, keyless, standalone

Every endpoint below was **probed live from this machine on 2026-08-24** before being listed here.

| Take | From | LOC | Live probe |
|---|---|---|---|
| `dataflows/stocktwits.py` | TradingAgents | 96 | `api.stocktwits.com/api/2/streams/symbol/AAPL.json` → **HTTP 200**, JSON, keyless |
| `dataflows/reddit.py`, **RSS path only** | TradingAgents | 250 | `reddit.com/r/wallstreetbets/search.rss` → **HTTP 200**, Atom. The richer JSON path `search.json` → **HTTP 403 Blocked**, confirming the repo's own note. Do not implement the JSON path. |
| `dataflows/polymarket.py` | TradingAgents | 139 | `gamma-api.polymarket.com/markets` → **HTTP 200**, keyless |
| `yfinance_news.py` *logic* — not the yfinance dependency | TradingAgents | 232 | `query1.finance.yahoo.com/v1/finance/search?q=NVDA&newsCount=5` → **HTTP 200**, keyless. We already talk to Yahoo in `app/market/providers/yahoo.py`; this is one more path on a provider we own. |

**Plus one that neither repo uses.** **GDELT** — `api.gdeltproject.org/api/v2/doc/doc` → **HTTP 200**,
keyless, no registration, a global news index with article-level timestamps. It is a better macro-news
surface than TradingAgents' `global_news_queries` (five hardcoded search strings run through yfinance
search) and it costs nothing. Recommend it as the macro-news provider.

**A load-bearing lesson, learned during this research.** My first probe of FRED timed out 3-for-3 with
a `Mozilla/5.0` User-Agent and I nearly wrote down "FRED is unreachable". It is not.
`app/market/providers/fred.py`'s docstring already documents that **FRED tarpits a browser-style UA**,
and that an honest one such as `investing-dashboard/0.1` returns in under a second. Re-probed with an
honest UA: **HTTP 200, 268 KB**. Every provider added below inherits that rule — *honest User-Agent,
never a spoofed browser string*. SEC EDGAR (probed, 200) enforces the same thing formally.

### 3b. Adopt the pattern, write our own code

| Pattern | Source | How ours differs |
|---|---|---|
| **Pre-fetch several sources into one prompt; no tool-calling in the sentiment agent** | TradingAgents `agents/analysts/sentiment_analyst.py` — it fetches Yahoo news, StockTwits and Reddit synchronously, and its prompt says `NO_EXTERNAL_TOOLS` because structured-output binding and tool-calling fight each other (`agents/utils/structured.py`) | Adopt wholesale. It is the correct shape and it sidesteps a real bug class. |
| **Structured output with a free-text fallback** | TradingAgents `agents/schemas.py` plus `bind_structured` / `invoke_structured_or_freetext` | Adopt the mechanism, **replace the schemas**. Theirs carry numbers (`score: 0-10`, `entry_price`, `stop_loss`). Ours carry `template: str` of `{{fact:id}}` references and `fact_ids: tuple[str, ...]` — the exact shape `app/thesis/debate.py`'s `DebatePoint` already uses. A schema that *cannot hold a float* cannot leak one. |
| **Two-tier model budget** | TradingAgents: `quick_think_llm` for every analyst and debater, `deep_think_llm` for the two adjudicators only | Adopt. It maps onto the workflow already in use here — parallel Sonnet-class workers, an Opus-class adjudicator. |
| **A DAG of agents: `depends_on` + `input_from`, topological layers, parallel within a layer and serial between** | Vibe-Trading `agent/src/swarm/{models,task_store,runtime}.py` — Kahn's algorithm in `topological_layers`, a `ThreadPoolExecutor` per layer, and a task whose upstream failed marked `blocked` and never dispatched | Adopt the **shape**, not the 1,128-line `runtime.py`. We already own the hard parts. Add roughly 200 lines of layering on top of `tournament/jobs.py`. |
| **The hand-off unit is a summary, not a transcript** | Vibe-Trading `input_from` maps a context key to an upstream task id | Adopt — but our hand-off unit is a `FactBundle` plus a verified draft, not free text. |
| **Round-robin adversarial debate on a counter-based budget** | TradingAgents `graph/conditional_logic.py`: `count >= 2 * max_debate_rounds`, no convergence check | **Adopt the budget discipline; defer the loop.** `app/thesis/debate.py` already produces a bull and a bear case deterministically, and its charter — *the bear case must name the specific condition under which the strategy loses money, and how often that condition occurred historically* — is a higher bar than either upstream debate clears. An LLM debate over trade direction may be redundant with what the rules DSL already encodes deterministically. Revisit only after Phase D measures whether it adds anything. |

### 3c. Refuse

| Refuse | Why |
|---|---|
| Vibe-Trading's `sentiment` tool, lexicon mode | Unigram bag-of-words with no negation handling — "not bullish" scores +1. Its finance vocabulary is directional rather than affective: `long`, `up`, `low` are positive; `short`, `low`, `volatility`, `risk` are negative. **And `"low"` is in both `_POSITIVE` and `_NEGATIVE`** — verified by set intersection. `_score_text` counts it once on each side, so every occurrence adds 2 to `hits` and 0 to the numerator, silently diluting the score of any text containing it. This is not a tool to wrap; it is a tool to not have. |
| Vibe-Trading's `flow_analyst` and its tools — `get_northbound_flow`, `get_dragon_tiger`, `get_margin_trading`, `get_block_trades` | China A-share market plumbing: Stock Connect Northbound, dragon-tiger boards, CNY block-trade thresholds. Unusable for a US book. Note this agent carries **40% of the composite weight** in `sentiment_intelligence_team.yaml`, so adopting that preset verbatim yields a composite dominated by a component we can never populate. |
| The `sentiment_intelligence_team.yaml` preset as written | Beyond the flow problem, it demands invented percentiles and historical excess returns with nothing checking them. We take its *decomposition* — news, social and flow as separate signals fused by a judge — and discard its prompts. |
| Any `place_order` / `submit_order` surface | `app/mcp/server.py` already states this: read-only is structural, and the vendored trading agent's order capability is deliberately not exposed. Unchanged. |
| Containerising Vibe-Trading | **Still don't** — but the environment reason is gone, and only the design reason remains. Run it as a stdio MCP subprocess, which is what Phase A does successfully: the container would buy isolation we do not need for a read-only research tool the owner launches locally, and would cost a build step on every upstream bump. **Docker itself now works** (verified 2026-08-24: engine 29.7.2 up, `wsl --list` shows a `docker-desktop` distribution, and `b35bc4c` built and ran the stack for the first time in this repo's history). |
| *(this row's own history, kept as a warning)* | This cell has been wrong **three times in one day**, each time in a different direction: first "no WSL at all" (true at 12:20, stale by 13:00), then "WSL present but no kernel and no distro" (true at 13:00, stale by 17:00), now "Docker works". The second version's own closing sentence was *"a phase gate resting on a stale environment claim gets re-litigated later from the wrong premise"* — and it then went stale within four hours. **Treat every environment claim in this document as timestamped, not durable.** If a decision depends on one, re-run the check rather than reading the cell. |

---

## 4. The build order

Six phases. Each gate is a command someone can run, not a claim someone can make. Run pytest through
the repo venv (`.venv/Scripts/python.exe -m pytest`) — a bare `python -m pytest` prints "no module"
and still exits 0, which reads as a green suite that never ran.

### Phase A — Repair the MCP wiring — **DONE 2026-08-24**

Executed. What it actually took, and what it found:

1. `.mcp.json` regenerated via `tools/write_mcp_config.py`. The committed-history path
   (`C:/Users/<user>/repos/TEMP_CODE/...`) does not exist on this machine.
2. **The gate then failed anyway** — `initialize FAILED`. Cause: `tools/vendor/.venv-vibe` was a
   corpse from the old machine. Its `pyvenv.cfg` read `home = C:\Python312`, an interpreter that
   does not exist here (local 3.12.10 lives under `AppData/Local/Programs/Python/Python312`). So the
   §6 open question "can the venv run the *newer* clone" resolved worse than asked: it could not run
   the older one either, and this MCP server has never started on this machine.
3. Vendored clone reset `281c877` (0.1.13) → `99e84ab` (0.1.14). It was pristine — no local edits
   lost. A `git pull` refuses ("unrelated histories") because the clone is shallow; `git reset --hard`
   against the fetched head is the working move.
4. `.venv-vibe` rebuilt from the local interpreter, `agent/requirements.txt` reinstalled.

**Gate result:** `initialize OK — server=Vibe-Trading v0.1.14 protocol=2025-06-18` /
`tools/list OK — 74 tools` / `planned tools present: 10/10` / `order-placement / shell tools
exposed: none` / `skipped modules: none`. The 74-tool estimate in this document was right, and the
read-only charter holds on the live surface rather than only in the upstream docstring.

<details><summary>Original plan text for this phase</summary>

`.mcp.json` currently points at
`C:/Users/<user>/repos/TEMP_CODE/Investing dashboard/tools/vendor/...`. **That path does not exist
on this machine** — `ls C:/Users/<user>` returns *No such file or directory* — so the Vibe-Trading
MCP server is not running and has not been. The vendored clone and its virtualenv *do* exist, at
`tools/vendor/Vibe-Trading/` and `tools/vendor/.venv-vibe/Scripts/python.exe`, and
`tools/write_mcp_config.py` exists precisely to regenerate the file with machine-correct paths:

```
.venv/Scripts/python.exe tools/write_mcp_config.py
```

**Refresh the vendored clone first — it is stale, and measurably so.** Verified 2026-08-24:

| | `tools/vendor/Vibe-Trading` | `externalProjects/Vibe-Trading` |
|---|---|---|
| HEAD | `281c877`, 2026-08-09 | `99e84aba`, 2026-08-24 |
| version | 0.1.13 | 0.1.14 |
| `@mcp.tool` count | 60 | 64 |
| skills | 89 | 90 |

So pointing the config at the existing vendor costs four MCP tools and two weeks of fixes. Either
`git pull` inside `tools/vendor/Vibe-Trading` or re-point `tools/write_mcp_config.py` at
`externalProjects/`. Both directories are gitignored, so this is a local decision either way.

What this buys immediately, for free: roughly **74 research tools over MCP** — 64 declared with
`@mcp.tool` plus 10 mirrored through `_MIRRORED_TOOL_SOURCES` — read-only by construction, including
`get_stock_news`, `web_search`, `read_url`, `get_sec_filings`, `get_macro_series`, `prediction_market`,
`research_papers`, `list_swarm_presets` and `run_swarm`. That is a research surface for whoever is
working *in* this repo. It is deliberately **not** a dependency of `backend/`, and `tools/vendor/`
stays gitignored.

**Gate:** `.venv/Scripts/python.exe tools/probe_mcp.py .mcp.json` lists tools without error.

</details>

### Phase B — News and sentiment as data — **BACKEND DONE 2026-08-24**

Five providers, built in parallel against a contract written first so they could not diverge:
`stocktwits.py`, `reddit.py`, `yahoo_news.py`, `gdelt.py`, `polymarket.py`, plus
`app/market/news_models.py` (the `NewsItem`/`SocialSnapshot`/`EventMarket`/`NewsFeed` vocabulary and
the `published_before` look-ahead guard), three new Protocols and an `UnsupportedQuery` exception in
`providers/base.py`, and news/social/event chains in `registry.py` reusing `_walk` unchanged.

**133 new tests. Full suite: 2877 passed, 1 skipped. Ruff clean across `backend` and `tests`.**
mypy reports only the pre-existing `pandas` stubs error, which reproduces on untouched files.

Three things worth recording because they were not obvious before building it:

- **`README.md`'s "2,094 backend tests" is stale** — the suite is at 2877 (this work plus a
  concurrent session's). Re-run the gate; do not quote the file.
- **Caching came free and matters more than expected.** The news providers take the same shared
  `httpx.Client` as the bar providers, so they inherit `CachingTransport`. Verified: two identical
  `fetch_social` calls cost one upstream request. Against GDELT's throttle that is the difference
  between a working page and a 429.
- **One cross-shard inconsistency, found only at integration.** `yahoo_news` dropped a malformed
  row; `gdelt` raised and lost the entire feed for one undateable article. `providers/base.py`
  already draws the right line — a malformed *payload* must raise (the Stooq challenge-page case), a
  malformed *row* inside a good payload is dropped, exactly as `BarProvider` drops a null-OHLC bar.
  GDELT now drops, warns with `partial_parse` naming the count, and still raises when *every* row in
  a non-empty list fails, because that is a schema change rather than a quiet empty answer. Note the
  two tests that asserted the old raising behaviour kept passing after the change — each fed a
  single bad article, so they tripped the all-rows guard instead. Six tests that pair a bad row with
  good ones were added, and were confirmed to discriminate by reverting the policy and watching one
  fail.

<details><summary>Original plan text for this phase</summary>

New providers under `app/market/providers/`, registered in `app/market/registry.py` so they inherit
the typed fallback walk, the `MarketWarning` propagation, and the "one exception listing what every
provider said" contract:

- `stocktwits.py` — per-symbol message stream. Emit **counts**: bullish, bearish, unlabelled, total,
  window. Never a derived "sentiment score" at this layer.
- `reddit.py` — RSS only. Emit post counts and titles per subreddit. RSS carries no scores and no
  comment counts, so any engagement-weighted figure would be fabricated. Say so in the docstring.
- `yahoo_news.py` — per-ticker headlines with publication timestamps.
- `gdelt.py` — macro and global news with article timestamps.
- `polymarket.py` — open markets by keyword: implied probability, volume, resolution date.

Three things this layer must get right, all of them lessons already paid for elsewhere in this repo:

1. **Honest User-Agent on every provider.** See §3a.
2. **Look-ahead safety is not optional.** Every item carries a publication timestamp, and every read
   is filtered against the caller's as-of date *before* it reaches anything else. TradingAgents ships
   a dedicated `tests/test_news_lookahead.py`; we have `app/backtest/guards.py` and must route news
   through it. News leaking one day of hindsight into an event study is undetectable in the output
   and fatal to it.
3. **Cache and rate-limit.** `app/market/cache.py` exists. StockTwits' unauthenticated per-IP quota is
   *not verified* — treat it as tight, cache aggressively, and record the observed limit when we find
   it rather than guessing a number here.

**Gate:** provider tests green against recorded fixtures, redacted and committed to match the
`tests/fixtures/macro/` convention; one live smoke test per provider, skipped when offline.

</details>

### Phase C — Facts, then a panel — **DONE 2026-08-24**

Built in parallel behind a response contract written first (`SocialSummary`, `TickerNewsPanel`,
`MacroNewsPanel` in `news_models.py`), so three workers could not diverge on shape.

- `app/market/news.py` — the service layer, holding the never-raises contract copied from
  `macro.build_snapshot`: a dead StockTwits costs the social section and nothing else.
- `app/api/news.py` + `main.py` — `GET /api/news/ticker/{symbol}` and `GET /api/news/macro`. No 5xx
  path at all; the only error is a 422 for a naive `as_of`, which is the caller's bug, not an outage.
- `app/report/news_facts.py`, merged into `build_bundle` — the facts are citable, verified end to
  end: a populated panel renders *"Bull share 50.0% of 4 labelled, 1 articles"*, a degraded one
  renders *"Bull share — of — labelled"* and **still passes `narrative.verify`**. Absence is an em
  dash, never a fabricated midpoint, and never a silently vanished sentence.
- `frontend/src/api/news.ts`, `components/NewsPanel.tsx`, `hooks/useTickerNews.ts`, mounted on the
  Ticker page.

**`GET /api/news/macro` now has a frontend consumer — closed 2026-08-24, after shipping with none.**
Phase C's plan text below promised the Macro tab "Polymarket event tiles and a GDELT global-news
strip alongside the existing rates, curve, energy and Fear & Greed panels"; that went unbuilt for one
cycle, documented as unfinished scope above this note. It is now built: `frontend/src/api/news.ts`
gained `EventMarket`/`MacroNewsPanel` types and `newsApi.macro` (additive only — the ticker exports
are untouched), `frontend/src/hooks/useMacroNews.ts` fetches it on its own effect for the same reason
`useTickerNews` does (GDELT and Polymarket are slow, keyless, and must not hold up Fear & Greed or
the tiles), and `frontend/src/components/MacroNewsPanel.tsx` renders it — Polymarket tiles first, the
GDELT-fed headline strip second, mounted on `/macro` after Movers and before `ProviderNote`. `/macro`
now renders Fear & Greed, Key indicators, Rates, Oil, Movers, **and this panel**, in that order.

Two honesty gaps this panel closes are worth recording because the wire shape made them non-obvious.
First, `MacroNewsPanel` (the backend model) has a `news_source` field but no `events_source` — a dead
Polymarket chain and a Polymarket chain that answered with zero matches both arrive on the wire as
`events: []`. `MacroNewsPanel.tsx`'s events section is the one place in this codebase that tells those
two states apart by matching a warning's message text (`"prediction markets unavailable"`, the exact
string `build_macro_panel`'s `_fold_provider_error` emits) rather than reading a dedicated null field,
and `MacroNewsPanel.test.tsx` pins that string so a backend wording change breaks the frontend test
instead of silently collapsing "dead provider" into "nothing today." Second, every count on the panel
carries the `MACRO_NEWS_LIMIT` it was actually requested against — "10 of up to 20 requested
headlines," never a bare `10` a reader could mistake for "today's total" — the same discipline the
ticker panel's labelled-message denominator enforces, applied here to a panel with no ratio to guard
but a count that could still mislead alone.

Verified in the running app, not just green tests: with the backend on :8000 and the panel's default
query, Polymarket returned zero matches for the top volume-ranked markets it was asked about (a live,
correctly-rendered "no event markets matching today's query," not a bug) while the GDELT chain had
fallen back to `yahoo_news` and returned ten real headlines, both denominators intact; a broader query
(`?query=market`) confirmed a populated Polymarket response deserialises and renders as intended.

**Full suites: 2,921 backend passed / 1 skipped; 472 frontend passed (458 prior + 14 new for
`MacroNewsPanel.test.tsx`). Ruff clean; typecheck clean.**

Three things worth recording:

- **The bull ratio divides by *labelled*, not total, and is `None` — never `0.5` — when nothing was
  labelled.** On the real fixture that is 4 messages of 12. Both denominators ship side by side and
  the panel is required to render them together, so a reader cannot see "50% bullish" without seeing
  that it rests on four messages.
- **A third case turned up that the contract had not anticipated**: `bull_ratio: null` on a
  *non-empty* window where every message was neutral — `labelled_share` is `0`, not `null`. Distinct
  from an empty window, and the panel says so in different words.
- **Nothing could have caught an unmounted panel.** `App.test.tsx` mocks the Ticker page wholesale,
  `NewsPanel.test.tsx` renders it in isolation, and the backend suite proves the endpoint answers —
  all three stay green if the panel is never placed on a route. `pages/Ticker.test.tsx` closes that,
  and was confirmed to discriminate: removing the mount fails all five of its tests.

<details><summary>Original plan text for this phase</summary>

News and sentiment become **facts in the `FactBundle`**, which is what makes them citable by
`narrative.verify` and visible to `app/report`:

- `app/market/models.py` — `NewsItem`, `SocialSnapshot`, `EventMarket`.
- `app/report/builder.py` — bundle them with ids like `sentiment.stocktwits.bull_ratio`,
  `news.count_7d`, `event.prob.<slug>`.
- **Ticker tab** (`frontend/src/pages/Ticker.tsx`) — a News & Sentiment panel beside the decision
  table: headlines with timestamps and sources, the StockTwits bull/bear split, Reddit post volume.
  Figures only, each with its own `as_of` and provenance, exactly like the macro tiles.
- **Macro tab** — Polymarket event tiles and a GDELT global-news strip beside the existing rates,
  curve, energy and Fear & Greed panels.
- **Report tab** — a sentiment section whose prose is a `NarrativeDraft` of `{{fact:...}}` templates
  and therefore cannot say anything the bundle does not hold.

**Gate:** `narrative.verify` passes on the new drafts; frontend tests green; **and the panel renders
in the running app.** A 200 from the API is not a rendered page, and a green suite cannot see a launch
config — open the page in the browser before calling this done.

</details>

**The browser half of that gate is closed.** `/ticker/AAPL` read live from a running dev server
against a live backend, console clean, no error boundary. Panel order on the page:
`AAPL · Chart · Decision table · Test a rule expression · News & sentiment · Institutional holders`.

The rendered social line was:

> **SOCIAL SENTIMENT (STOCKTWITS) — 100% bullish · 6 of 20 messages labelled · as of just now**

That single line is the design argument made in production. **Fourteen of twenty messages said
nothing at all.** A panel reporting "100% bullish" without its denominator would have been true,
useless, and confidently misleading — precisely the shape of Vibe-Trading's lexicon scorer, which
emits one float and discards the evidence that it rests on almost nothing. Ten live headlines
rendered beneath it with publishers and relative ages.

**True-but-useless is harder to catch than wrong**, and that is the whole reason this codebase spends
so much of its weight on denominators, sample sizes and `None`-over-default. A wrong number can be
checked against something. A number that is arithmetically correct over a sample too thin to mean
anything looks exactly like a number that means something, and nothing downstream of it — no test, no
type, no reviewer reading the prose — can tell the difference once the denominator is gone. That is
why `SocialSnapshot` has no `score` field, why `bull_ratio` divides by `labelled` and publishes
`labelled_share` beside it, and why the panel is forbidden from rendering the ratio alone.

*An earlier draft of this note claimed the backend on :8000 was stale and had never loaded the news
routes. That was wrong — `--reload` had simply not finished when it was probed; re-probed later, both
routes were present on `localhost` and `127.0.0.1` alike. Recorded because "the other process is
stale" is an attractive and hard-to-falsify diagnosis, and it was the wrong one twice in one day
(see the FRED user-agent note in §3a).*

### Phase D — Measure before believing *(the gate on everything after it)*

> **Phase D is blocked by data that does not exist yet, not by effort. This was discovered while
> building Phase B and it changes the schedule.**
>
> The study needs a sentiment *history*. Every free social endpoint serves only a live window:
> StockTwits returns the current tail of a symbol's stream, Reddit's RSS the most recent posts.
> Neither has a historical query — which is why `SocialProvider` deliberately has no `as_of`
> parameter (a provider offering a bound it cannot honour would let a backtest ask for 2019, receive
> today's messages, and never know). **So there is no social series to measure, and no way to
> manufacture one retroactively.** It has to be accumulated forward from stored snapshots, which
> means the earliest an honest social study can run is months after snapshot storage ships.
>
> News is different and better: GDELT's DOC API accepts `startdatetime`/`enddatetime`, so a news
> *volume* series is available historically today. That splits Phase D in two:
>
> - **D-news**, runnable as soon as snapshot storage and the event-study wiring exist. Question:
>   does a news-volume spike carry forward return after correction, across the window matrix?
> - **D-social**, not runnable yet. Needs a snapshot table written on a schedule, and time to pass.
>
> This is worth being pleased about rather than annoyed by: it is the anti-p-hacking constitution
> working as designed. The alternative — a social backtest over a history reconstructed from a live
> endpoint — is precisely the circular, look-ahead-contaminated study the whole program exists to
> refuse, and it would have looked completely normal in the output.

**2026-08-24 — the snapshot table has shipped, the clock has not started.** `app.market.
social_history` (`backend/app/market/social_history.py`, tests in `tests/test_social_history.py`)
is a durable, append-only SQLite store keyed on `(symbol, source)`: `record_snapshot` writes a
`SocialSnapshot`'s counts with `observed_at` (the provider's own clock) and `recorded_at` (this
store's clock) as separate columns, never a ratio — `bullish`/`bearish`/`neutral` are the only
numbers persisted, and `SocialSummary.of` derives `bull_ratio`/`labelled_share` fresh on every read,
exactly as the section above argues for. `read_range` answers a stored time window and reports its
own `coverage_start` plus `requested_start_before_coverage`, so a caller asking for history before
the store began sees that gap named rather than an empty result that reads like "nothing happened."
A write within the same minute for the same `(symbol, source)` collapses into the existing row
rather than creating a second one — see the module docstring for the dedupe rule.

**~~This does not make D-social runnable today.~~ 2026-08-25 — the call site is placed and the clock
has started.** `app.main.lifespan` now calls `app.market.social_history.start_scheduler(settings)`,
following the same daemon-thread pattern `app.market.refresh`'s startup sweep already uses — no new
dependency, no scheduler library. It is gated on `Settings.social_snapshot_scheduler_enabled`
(env `INVDASH_SOCIAL_SNAPSHOT_SCHEDULER_ENABLED`), which **defaults to `False`** so that every other
test file's `TestClient(app)` does not spawn a background thread making live network calls. Cadence is
`Settings.social_snapshot_interval_hours`, default `6.0` — four ticks a day, with a 2-second pause
between symbols within a tick. Those numbers are a politeness constraint on free, keyless endpoints
as much as a sampling choice.

The watchlist is the one `app.market.refresh` already uses (derived from `app.market.macro._MOVERS`),
reused rather than re-derived so the application has exactly one answer to "which symbols get a social
fetch" instead of two that can drift apart.

**Two writers now hit the same table**, and a future reader should not be surprised by it:
`app.market.refresh._record_social_snapshots` writes one snapshot per server restart, and this
scheduler writes on its interval. `record_snapshot`'s per-minute dedupe bucket makes a collision
between them a harmless no-op rather than a double count.

**What is still required before D-social can be answered.** The flag being available is not the same
as the clock running: it must be *on* in a deployment that stays up, and then the "let months pass"
requirement above is unchanged. A table with rows from a single afternoon is not a history any more
than an empty one is. As of 2026-08-25 the flag is set in this machine's local `.env`; that is one
developer machine, not a deployment, and the honest reading is that accumulation has begun here and
nowhere else.

We now have a sentiment time series. **Before it is allowed to influence a single decision**, it goes
through the machinery this repo built for exactly this question: `app/backtest/forward.py` event
studies, `app/backtest/guards.py` lookahead guards, and the multiple-testing correction.

The question, pre-registered before it is run: *does an extreme StockTwits bull ratio, or a
news-volume spike, carry any forward return at any horizon we care about, after correction, across
the windows in `strategy-program/WINDOWS.md`?*

"No" is a complete and valuable answer, and it is the likely one. Round verdicts here are conditional
on the window mix — round 3 was 6-of-8 falling and round 4 was 2-of-6 rising, and identical cards
reversed between them — so this runs across the matrix, never one window. If the answer is no,
**Phase C still stands** (reading the news on the ticker page is useful on its own) and Phases E and F
are cancelled rather than built. That branch must stay genuinely on the table.

**Gate:** a pre-registered study in `strategy-program/`, its result reported with sample sizes and
q-values whichever way it lands.

**2026-08-26 — D-news was probed before it was built, and it cannot be run at the stated scope.**
The claim above that "a news *volume* series is available historically today" is half right: GDELT's
DOC 2.0 API does accept `startdatetime`/`enddatetime`, and a real query returns 95 daily buckets for
`q4-2018` — but **its archive begins 2017-01-01**, established by bisection against the live endpoint
(`2016-12-15` is refused, `2017-01-01` returns JSON). Three of the eight windows in `WINDOWS.md` —
`gfc`, `chop-2011` and `chop-2015` — end entirely before that date, and they are the deepest drawdown
available plus *both* sideways windows. Five remain, which is exactly `MIN_ELIGIBLE_MAIN_WINDOWS`
with no slack, and only three once `covid`/`q4-2018` are held out the way every other study here
holds out.

The fetcher was built regardless (`GdeltProvider.fetch_volume_series`, 16 tests), because it makes
the finding reproducible and every branch needs it. The finding, the window map and the four
branches — including the recommendation — are in `strategy-program/PHASE-D-NEWS-FEASIBILITY.md`.
**Phases E and F stay gated**: this is not the plan's "no" (measured and found absent), it is "not
measurable at the scope pre-registered", which is weaker evidence than a null and must not be
mistaken for one.

### Phase E — The agent runtime

Only if Phase D says there is something there.

- `app/agents/models.py` — `AgentSpec` and `AgentTask` as frozen Pydantic models in Vibe-Trading's
  shape: `id`, `role`, `system_prompt`, `tools`, `depends_on`, `input_from`, `max_iterations`,
  `timeout_seconds`, `max_retries`, optional per-agent `model_name`.
- `app/agents/dag.py` — `validate_dag` (DFS cycle check) and `topological_layers` (Kahn). ~60 lines.
- `app/agents/runner.py` — layers executed on top of `tournament/jobs.py`'s existing daemon thread,
  process-wide lock and `threading.Event` cancellation. **Parallel within a layer, serial between**,
  with a blocked task never dispatched when its upstream failed.
  - **The lock is not a formality.** Two readers of the DuckDB bar store do not queue — they both
    raise `IOException`s that a runner records as ordinary card failures and walks past, producing a
    report that looks complete and is silently missing every card (`strategy-program/DEFECTS.md` D3).
    An agent run must never execute concurrently with a competition round. Extend the existing lock
    to cover both rather than adding a second one.
  - **Watch for stateful closures.** A ladder closure reused across windows once cost 16pp of CAGR,
    and the first cell of a sweep is always right, which is what hides it. Agent specs are frozen;
    anything a worker carries between tasks is explicit state in the task store, never a captured
    closure.
- `app/agents/schemas.py` — the output contract: `template` plus `fact_ids`, never a number.
  Structured output with a free-text fallback, in TradingAgents' `invoke_structured_or_freetext`
  shape.
- `app/api/agents.py` — `POST/GET/DELETE /api/agents/runs`, mirroring `competition_jobs.py`. Polling,
  not SSE: the existing job endpoints poll and the frontend already knows how.
- Two model tiers: Sonnet-class workers, an Opus-class adjudicator.

**Gate:** a run whose workers are stubs completes, cancels mid-flight when asked, and refuses to start
while a competition job holds the lock — expect a `409` naming the live `job_id`.

### Phase F — Put agents where they earn their place

Not a new tab. Into the tabs that already exist, behind the guards that already exist:

- **Thesis** (`/thesis`) — an LLM author replacing `app/thesis/author.py`'s fixed catalogue, arriving
  through `propose_from_candidate` so the rationale records where it came from. Pre-registration, the
  trial ledger, the holdout and the iteration budget are untouched. This is the swap the module
  docstring was written to accommodate.
- **Competition** (`/competition`) — PROTOCOL.md §2 already specifies *"N analyst agents, in parallel,
  one card each"* for phase 1 and *"one agent per card, in parallel, each reading only its own trade
  logs"* for phase 6. Those are the two phases the DAG runner automates, and they are the only two:
  **phases 3–5 stay deterministic and serial.** An LLM must never touch scoring — the protocol's
  value is reproducibility, and a model in the scoring path destroys it. Information quarantine
  (§3.6) becomes a tool whitelist per worker, which is easier to enforce in code than in a human's
  discipline.
- **Report** (`/report`) — an LLM drafting the narrative, gated by `narrative.verify` exactly as the
  template writer is today. The checker does not care who wrote the draft. That is the point of it.

**Gate:** a full round run through the agent path reproduces the deterministic path's scores
bit-for-bit, because only phases 1 and 6 changed hands.

---

## 5. Risks worth naming now

- **Non-reproducibility.** LLM output is not deterministic. The competition protocol freezes cards at
  phase 2 and quotes the commit hash; that is what contains this. Never let a model into a path whose
  output must be re-derivable — and remember that re-running a frozen card is not a new draw, so
  "confirmed twice" can be one measurement counted twice.
- **The p-hacking machine gets a bigger engine.** An agent can propose fifty theses a minute. The
  ledger's denominator is the only thing between that and a confident liar, and it must count *every*
  agent proposal, including the ones the agent discarded mid-iteration. That is hazard (1) in
  `app/thesis/__init__.py`, and an agent loop makes it worse rather than better.
- **The generator sees the data.** Hazard (2). An LLM author with tool access to the bar store is the
  circular case by construction. Its tool whitelist must exclude the sample, or its output must be
  stamped exploratory and consume a trial.
- **Cost and latency.** TradingAgents defaults to one debate round and one risk round *because* the
  budgets are what stop a run being unbounded. Set ours explicitly and log the spend per run.
- **Upstream fragility.** StockTwits, Reddit RSS, Yahoo's v1 search and CNN's Fear & Greed endpoint
  are all undocumented or unofficial, and they break without notice. Each needs the
  `app/market/fear_greed.py` treatment: a defined behaviour for when it is gone, surfaced rather than
  silently zeroed.
- **Sentiment as a signal is weak and crowded.** Phase D exists because the honest prior is that it
  contributes nothing after correction. Building E and F before D would be the fitted-rule mistake the
  whole program was written to avoid.

---

## 6. What is still unverified

Stated rather than glossed, in the same spirit as `NEWS-AGENTS-STUDY.md`'s closing section:

- **StockTwits' unauthenticated rate limit.** The endpoint returns 200; the per-IP quota was not
  probed.
- ~~Whether `tools/vendor/.venv-vibe` can run the newer clone.~~ **Resolved 2026-08-24:** it could not
  run *any* clone — dead interpreter path. Rebuilt; 0.1.14 installs and runs.
- ~~Whether all ~74 Vibe-Trading MCP tools start cleanly.~~ **Resolved 2026-08-24:** 74 tools listed,
  `skipped modules: none`.
- **GDELT's throttle, now measured and worse than advertised.** The endpoint answers keylessly, but
  rate-limits to roughly one request per 5 seconds per IP — and a retry **12 seconds** later was still
  throttled, so the published figure is a floor, not the rule. Two traps go with it, both verified: the
  throttled body arrives with **no `content-type`** and as **plain text** (so `.json()` raises), and
  the HTTP status is unreliable — the same throttle message was observed under both 200 and 429. A
  provider must therefore detect the throttle from the **body**, not the status. Not UA-related: an
  honest UA and a Chrome string were throttled identically. Fixtures for both the good response and
  the throttled one are committed under `tests/fixtures/news/`.
- **The "one live smoke test per provider" line in Phase B was wrong and is withdrawn.** The house
  convention is absolute: every provider test drives an `httpx.MockTransport` and **no test touches the
  network**. `pytest.ini` sets `--strict-markers` and registers no `live`/`network` marker, so a
  network-gated test could not even be written without editing shared config. Real payloads were
  captured once, by hand, into `tests/fixtures/news/` instead.
- **Current backend and frontend test counts.** `README.md` says 2,094 backend and 161 frontend; the
  suite was not run for this document. Status docs in this repo have drifted before — re-run the gates
  rather than quoting them.
- **GDELT's coverage quality for single US tickers.** The endpoint returns 200 and indexes global
  news, but whether its per-company recall beats Yahoo's for our universe is an empirical question
  Phase B should answer with a comparison, not an assumption.
- **The preset count.** `NEWS-AGENTS-STUDY.md` says 32 swarm presets; the clone read today has 30
  (`ls agent/src/swarm/presets/`). Upstream drift, not a contradiction — but it is a reminder that
  both repos move under us.

---

**Not investment advice, and nothing here places an order.** Every surface described above is
read-only with respect to money, unchanged from `app/mcp/server.py`'s existing charter.
