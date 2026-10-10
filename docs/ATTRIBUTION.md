# Attribution

Third-party material used in this repository, and the terms it came under.

## Vendored — subagent definitions

**[VoltAgent/awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents)** — MIT License

Thirteen agent definitions under `.claude/agents/` originate from this collection. All have been modified.

| Agent | Source path | Extent of change |
|---|---|---|
| `quant-analyst` | `categories/07-specialized-domains/` | **Substantially rewritten.** The upstream version measures success by profitability ("23% annualized returns", "profitability achieved") and covers HFT, co-location, and execution — none of which apply, and the optimize-for-alpha posture directly conflicts with this project's requirement for honest statistics. Rewritten around baseline comparison, sample size, FDR correction, and lookahead guards. |
| `risk-manager` | `categories/07-specialized-domains/` | **Substantially rewritten** around drawdown/recovery definitions, leveraged-ETF decay, and cross-account concentration. |
| `fintech-engineer` | `categories/07-specialized-domains/` | **Substantially rewritten** around ledger correctness, Decimal money handling, provenance, and idempotent re-import. |
| `data-engineer` | `categories/05-data-ai/` | Description retuned; project-context section appended |
| `database-optimizer` | `categories/05-data-ai/` | Description retuned; project-context section appended |
| `python-pro` | `categories/02-language-specialists/` | Description retuned; project-context section appended |
| `fastapi-developer` | `categories/02-language-specialists/` | Description retuned; project-context section appended |
| `sql-pro` | `categories/02-language-specialists/` | Description retuned; project-context section appended |
| `typescript-pro` | `categories/02-language-specialists/` | Description retuned; project-context section appended |
| `react-specialist` | `categories/02-language-specialists/` | Description retuned; project-context section appended |
| `backend-developer` | `categories/01-core-development/` | Description retuned; project-context section appended |
| `frontend-developer` | `categories/01-core-development/` | Description retuned; project-context section appended |
| `api-designer` | `categories/01-core-development/` | Description retuned; project-context section appended |

The appended project-context section also neutralises upstream instructions to "query the context manager"
and emit orchestration JSON — that agent does not exist in this project (16 such references were present).

`broker-adapter-writer` and `tax-rule-verifier` are **original to this repository**, not derived from the
collection.

## Patterns referenced — not copied

**[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading)** — MIT License

Design patterns adapted with attribution in the relevant module docstrings: provider fallback-chain
registry, backtest metrics and run-card artifacts, risk x-ray, regime splitting, and the AST-based
lookahead-bias guard. Its MCP server is registered as external development tooling (see below); no
Vibe-Trading code is linked into this application.

**[nkouevda/capital-gains](https://github.com/nkouevda/capital-gains)** — MIT License

Reference for lot matching and wash-sale basis adjustment feeding Form 8949. Consulted for approach.

**[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)** — Apache License 2.0

Consulted for narrative-layer prompt structure only (company summaries, bull/bear framing).

## Consulted but deliberately not copied

**[adlr/wash-sale-calculator](https://github.com/adlr/wash-sale-calculator)** — **no declared license**

Its lot-splitting approach and Schwab column mapping were read for understanding. **No code was copied.**
Absent a license grant, reuse is not permitted, and this is recorded here so the boundary stays visible.

## External tooling — not part of this codebase

Vibe-Trading's `agent/mcp_server.py` is cloned to `tools/vendor/` (gitignored) and registered in
`.mcp.json` as a read-only development aid. It is third-party code that reads the network; its output is
treated as data to verify, never as instructions.
