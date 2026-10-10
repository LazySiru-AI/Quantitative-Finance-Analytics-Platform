# Phase 0 — Tooling acquisition

**Date:** 2026-08-09 · **Status:** complete · **Next:** Phase 1 (scaffold, canonical models, stores)

Acquire development tooling from the reference repos before writing application code. No application code
was written in this phase, by design.

---

## What landed

### Repository

`git init` on `main`. Four commits' worth of scaffolding in one initial commit plus this phase's work.

The `.gitignore` decision worth knowing about: **raw brokerage exports are untracked.** `data/*.csv` and
friends are excluded because they contain real account activity, positions, and dollar amounts. The app
reads them off disk; nothing depends on them being versioned. Verified at commit time that no `.csv` was
staged. If you want them tracked anyway, remove that line — but only on a repo certain to stay private.

`.gitattributes` pins LF for source but marks CSV and `tests/fixtures/**` as binary. Broker adapters are
tested against exact encodings and line terminators (SoFi exports contain cp1252 bytes), so git must not
normalise them.

### Subagents — `.claude/agents/` (15 total)

Thirteen vendored from [awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents)
(MIT), two written from scratch. Full provenance in [ATTRIBUTION.md](../ATTRIBUTION.md).

| Agent | Origin | Treatment |
|---|---|---|
| `quant-analyst` | vendored | **rewritten** |
| `risk-manager` | vendored | **rewritten** |
| `fintech-engineer` | vendored | **rewritten** |
| `data-engineer`, `database-optimizer`, `python-pro`, `fastapi-developer`, `sql-pro`, `typescript-pro`, `react-specialist`, `backend-developer`, `frontend-developer`, `api-designer` | vendored | description retuned + project-context appended |
| `broker-adapter-writer` | original | — |
| `tax-rule-verifier` | original | — |

### MCP — `vibe-trading`

Vibe-Trading shallow-cloned to `tools/vendor/Vibe-Trading` (gitignored, 58.8 MB) with a dedicated venv at
`tools/vendor/.venv-vibe`. Registered project-scoped in [`.mcp.json`](../../.mcp.json).

`tools/probe_mcp.py` verifies the server end-to-end and is kept as a regression check.

---

## Deviations from the plan

Three, all deliberate.

### 1. Three finance agents were rewritten, not retuned

The plan said to retune each vendored agent's frontmatter description. On reading them, that was not enough
for the finance three.

Upstream `quant-analyst` measures success by **profitability** — its delivery-notification template boasts
*"23% annualized returns"* and its excellence checklist ends with *"Profitability achieved"*. It also covers
HFT, co-location, latency, and order routing, none of which apply here. That posture is in direct conflict
with this project, whose entire point is that the workbench must be willing to tell you a rule does not
work. An agent optimising toward alpha would systematically undermine the FDR correction and lookahead
guards the plan specifies.

Rewritten around: baseline comparison, visible sample size, Benjamini–Hochberg correction, overlapping-window
non-independence, and fail-closed lookahead guards. `risk-manager` and `fintech-engineer` were rewritten on
the same reasoning, seeded with the measured facts from the data profiling.

Also found and neutralised: **16 references to a "context manager" agent** that does not exist in this
project, instructing agents to emit orchestration JSON to nothing. The appended project-context section
explicitly overrides these.

### 2. Minimal venv instead of the full dependency set

`agent/requirements.txt` lists 44 direct dependencies including langchain, langgraph, scikit-learn, ccxt,
akshare, tushare, and weasyprint — plausibly 2 GB installed, and weasyprint routinely fails on Windows
without GTK libraries.

`mcp_server.py` turns out to import lazily via `importlib.import_module`, with only `fastmcp`, `pydantic`,
and `src.market_data` at module level. A 16-package subset was installed instead: **466 MB, all 64 tools
load, zero skipped modules.** `jinja2` was added after the first run reported
`Skipped src.tools.shadow_account_tool: No module named 'jinja2'` — that module provides
`extract_shadow_strategy` and `run_shadow_backtest`, both explicitly wanted.

### 3. `.mcp.json` instead of `claude mcp add`

The `claude` CLI is not on PATH in this environment. Project-scoped `.mcp.json` achieves the same
registration with no CLI dependency, and has the advantage of living in the repo.

**Caveat:** `.mcp.json` contains absolute paths and will break if the repo is moved or cloned elsewhere.
Fix by rewriting the three paths.

---

## Verification

Environment: git 2.47.0, Python 3.12.10, Node 22.22.0, npm 10.9.4.

| Check | Result |
|---|---|
| No CSV staged in initial commit | **pass** — verified against staged file list |
| 13 subagent files downloaded | **pass** — all 200 OK, 4.5–8.5 KB each |
| Audit for injected directives in vendored agents | **pass** — 11 matches, all innocuous topic bullets ("API key management"); no `ignore previous`, exfiltration, or shell payloads |
| Tool grants uniform | **pass** — all 13 are `Read, Write, Edit, Bash, Glob, Grep` |
| Description retune applied | **pass** — 10/10, script asserts exactly one replacement per file |
| MCP `initialize` over stdio | **pass** — `Vibe-Trading v0.1.13`, protocol `2025-06-18` |
| MCP `tools/list` | **pass** — 64 tools |
| Planned tools present | **pass** — 10/10 |
| Order-placement / shell tools exposed | **none** |
| Modules skipped on startup | **none** |

A false alarm worth recording: the first three handshake attempts failed with `Internal Server Error`. The
cause was PowerShell 5.1 prepending a UTF-8 BOM to the server's stdin, not a server fault —
`ProcessStartInfo.StandardInputEncoding` does not exist in .NET Framework. Re-probing from Python passed
immediately. Claude Code's own MCP client writes clean UTF-8, so this does not affect real use. `tools/probe_mcp.py`
is written in Python for exactly this reason.

---

## Security posture

- MCP server runs **without** `--enable-shell-tools`. Confirmed no order-placement, `bash`, or shell tools
  in the exposed surface.
- Two tools flagged by keyword scan and cleared on inspection: `trading_orders` *reads* open orders;
  `qveris_execute` runs a data-provider query, not a trade. Both need connector or API credentials that are
  not configured.
- One genuine write capability: `write_file`, scoped to the server's own workspace for generating
  `config.json` / `signal_engine.py`. Worth knowing it exists.
- Vibe-Trading is third-party code that reads the network. Its output is data to verify, never instructions.
- No credentials configured, and none should be. Real financial data stays in gitignored `data/`.

---

## Open items

| Item | Owner | Blocks |
|---|---|---|
| Export **Webull Account Statement / Activity** — the Orders Records files have no dividends, fees, transfers, or splits | you | Phase 3 (Webull tax figures stay incomplete without it) |
| Free **FRED API key** — Yahoo fallbacks work without it, with less history | you | Phase 5 (macro), non-blocking |
| `.mcp.json` absolute paths break if the repo moves | — | — |
| Volume indicators deferred at your request; blocks only the "band touch **+ volume**" comparison. One-file re-enable (`indicators/volume.py` + registry entry) | you, when wanted | Phase 7 partially |

---

## Phase 1 preview

Scaffold `backend/` and `frontend/`, define the canonical `Transaction` / `Lot` / `Position` / `Instrument`
models, stand up SQLite + DuckDB with the `raw_import` provenance layer, and get a FastAPI + Vite skeleton
running. No broker parsing yet — that is Phase 2, and it starts by pointing `broker-adapter-writer` at the
real exports.
