# Wiring Claude into the evolution loop

`app.agents` lets Claude design the competition loop's candidates instead of the seeded RNG. This
document covers what it is allowed to do, how to give the backend credentials, and what you give up by
turning it on.

## What it does, and what it is not allowed to do

`strategy-program/AGENTS-INTEGRATION-PLAN.md` Phase F is the governing rule: of the competition
protocol's seven phases, only **phase 1 (proposal)** and **phase 6 (post-mortem)** may involve a model.
Phases 3–5 — eligibility, running, scoring — stay deterministic and serial, because "the protocol's
value is reproducibility, and a model in the scoring path destroys it."

Everything in `app.agents` is phase 1. Nothing in it reads a run file, computes a metric, or ranks
anything; the numbers still come from `app.tournament.results` over files the existing engine wrote.

§0 of the same plan says an agent "may propose, name, argue and select" but "may never emit a number".
A card carries numbers — `fast=12`, `stop_loss_pct=0.08`, a sleeve weight — and the distinction that
makes this legal is that those are **hypotheses**, in exactly the sense the seeded RNG's numbers already
are: a claim about what is worth testing, which the backtest then judges. What is forbidden is a model
emitting a **measurement** — a return, a Sharpe, a win rate, a q-value. No type in the package can carry
one, and the designer's system prompt states the prohibition in as many words.

Two agents exist today:

- **`designer`** — reads the lane's ticker pool, the previous generation's findings and standings, and
  your stated `goal`, then designs the next generation's candidates with a written rationale per card.
- **`scout`** — reads the news panel's *counted* facts and suggests which pool tickers this generation
  should bias toward. It never emits a sentiment score; `app.market.news`'s own rule is that a provider
  "may only report what it counted, never what it concluded", and a scout that scored would break that
  one layer up.

## Giving the backend credentials

The backend builds a zero-argument `anthropic.Anthropic()`, so it accepts any credential the SDK
resolves, in this order: `ANTHROPIC_API_KEY`, then `ANTHROPIC_AUTH_TOKEN`, then an `ant auth login`
profile on disk. Pick whichever suits where you are running it.

Check what actually resolved, at any time, without spending anything:

```bash
curl -s http://localhost:8002/api/agents/health
```

That endpoint never makes a model call and never echoes the credential — it reports which *source* won
and why, so a page load can never cost money and a screenshot can never leak a key.

### Option A — API key (the one that works in Docker)

Add to the gitignored `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

`docker-compose.yml` already passes `.env` into the backend container via `env_file:`, so this works
identically inside and outside Docker with no further change.

### Option B — `ant auth login` (interactive, local only)

```bash
ant auth login
```

The profile lands in `%APPDATA%\Anthropic` on Windows and the SDK picks it up with no environment
variable set. `ant` is not installed on this machine and has no first-party Windows installer; the
documented routes are Homebrew (macOS), a release tarball (Linux/WSL), or `go install
github.com/anthropics/anthropic-cli/cmd/ant@latest` with Go 1.22+.

**This option does not work in the container as-is**, for two reasons worth stating plainly rather than
discovering at 3am:

1. The profile lives in your home directory, which the container does not mount.
2. The CLI's own documentation says interactive login "is for development on your own machine" and
   directs containers to Workload Identity Federation instead. OAuth refresh tokens hard-expire —
   they do not slide with use — so a loop left running for days would eventually fail auth mid-run.

If you want the login path anyway, run the backend directly (`.venv/Scripts/python.exe -m uvicorn
app.main:app --port 8000 --app-dir backend`) rather than in Docker.

### The trap that costs people an afternoon

A set `ANTHROPIC_API_KEY` **silently shadows a logged-in profile** — including an empty one, which still
wins its precedence slot and then authenticates with an empty key. `GET /api/agents/health` names this
case specifically rather than reporting a generic failure. Unset the variable entirely; do not set it
to `""`.

## Turning it on

`LoopConfig.use_agent` defaults to **`False`**, and that is a considered default rather than caution
about quality:

- **Reproducibility is lost.** A seeded generation replays to the same bytes. An agent-designed one
  cannot, because the model is not a pure function of its prompt. What replaces replay is audit: every
  call archives its system prompt, user turn, response, token usage, cost and request id under
  `data/loop/agent_calls/`, and the genome records `origin="agent"` so a reader can always tell which
  generations were reproducible and which were not.
- **It costs money on an infinite loop.** `LoopConfig.agent_budget_usd` (default **$10**) is a hard
  ceiling across the whole run. When it is reached the loop keeps going on the deterministic proposer
  and logs that it has stopped calling the model — once, not every generation. It never stalls and
  never silently keeps spending.

## The agent is never load-bearing

Every failure degrades to `app.evolution.proposer`'s deterministic path for that generation and is
recorded in the loop log: missing credentials, an exhausted budget, a rate limit, a refusal
(`stop_reason="refusal"` arrives as HTTP 200, not an exception), a malformed response, a hallucinated
ticker, or an over-budget trait dict. Three of those paths are covered by real tests in
`tests/test_evolution_loop.py::TestAgentDesignerFallback` that assert the generation *succeeded on the
deterministic proposer* — not merely that the process did not crash.

A proposal is refused rather than repaired. A card whose ticker was quietly swapped, or whose eleventh
parameter was quietly dropped, is a card whose rationale no longer describes it — and the rationale is
the entire reason to have an agent rather than an RNG.

## The honest caveat about quarantine

`PROTOCOL.md` §3 quarantines an analyst from prior rounds' results; they see only the brief. The
evolution loop already breaks that by design — inheritance is the whole mechanism, and
`strategy-program/EVOLUTION-LOOP.md` §2 says so. An agent designer is the sharpest form of it: unlike a
mutation operator, it can reason about *which specific window* a card failed in and design around that
window. The archived prompt is what makes this reviewable — you can read exactly what the designer was
shown. Treat agent-designed generations' margins with the same suspicion as any other in-sample result,
and let the holdout and the whole-loop q-values do their job.

## Agent Desk: Trading Agents and Vibe Trading

Two more features route through the same `app.agents.client` this document has been about all
along, but shaped differently from the designer and scout above: many calls per run, arranged into a
pipeline or a dependency graph, and every word rendered to a person rather than consumed by
machinery. `backend/app/agentdesk/__init__.py` is the design rationale; the wire contract — routes,
request/response shapes, fixed stage ids — is pinned in
[`AGENT-DESK-CONTRACT.md`](AGENT-DESK-CONTRACT.md).

- **Trading Agents** — `/trading-agents` in the UI, `/api/tradingagents` in the API. A fixed
  pipeline over one instrument: four analysts, a bull/bear debate, a research manager, a trader, a
  three-way risk debate, and a portfolio manager — see "Cost and budget" below for the stage/call
  count at default settings. Modelled on `externalProjects/TradingAgents` — see
  [`AGENT-GAP-ANALYSIS.md`](AGENT-GAP-ANALYSIS.md) for what was kept and what deliberately was not.
- **Vibe Trading** — `/vibe-trading` in the UI, `/api/vibedesk` in the API. A preset desk of role
  agents run as a DAG: the runtime computes topological layers and runs each layer's agents in
  parallel, with every downstream agent receiving only upstream summaries. Modelled on
  `externalProjects/Vibe-Trading`.

### Credentials

Both desks call through `app.agents.client` — the exact module, the exact functions — that the
evolution loop's designer and scout use above. Nothing new to configure: whichever credential option
you already set up under "Giving the backend credentials" (#giving-the-backend-credentials) covers
these desks too, `.env` API key or `ant auth login` alike.

One thing to know that does not come up above: when neither of those resolves,
`app.agents.client.is_available()` falls through to a locally installed Claude Code CLI binary that
is already logged in, rather than failing. That fallback rides the CLI's own login rather than any
`anthropic`-SDK credential slot, and it is tried last because it is the slower path — it shells out
to a subprocess instead of calling the SDK directly. `GET /api/agents/health` reports which source
actually won, same as it does today.

### Cost and budget

Every run takes a `budget_usd` cap; the default for both desks is **$5.00**
(`TradingAgentsConfig.default_budget_usd`, `StartSwarmRequest.budget_usd` — both in
[`AGENT-DESK-CONTRACT.md`](AGENT-DESK-CONTRACT.md)). The default model is `claude-opus-5`
(`app.agents.models.DEFAULT_MODEL`).

A Trading Agents run at the default settings (one debate round, one risk round) walks the fixed
pipeline's twelve stages — four analysts, a two-turn bull/bear debate, the research manager, the
trader, a three-turn risk debate, and the portfolio manager — so twelve model calls in the ordinary
case. Add one more whenever the run resolves a prior pending decision for the same ticker (see
"Decision memory" below), and up to two more per stage that fails the grounding gate and has to be
retried (`MAX_GROUNDING_ATTEMPTS` allows three attempts total per stage). A Vibe Trading run has no
debate/risk-round arithmetic to multiply — its call count scales with the chosen preset's task
count instead (`PresetDetail.tasks`, from `GET /api/vibedesk/presets/{name}`), plus the same
grounding-retry allowance per task.

The cost figure a run shows is an accounting estimate from this repo's own hand-maintained price
table (`app.agents.client._PRICE_TABLE_PER_MILLION`), not a billing figure — the same caveat that
already applies to every `AgentCall.cost_usd` in the evolution loop. It exists only to keep spend
under the cap. The authoritative number for what a run actually cost is always the Anthropic
console.

### The grounding gate

The desks do not ask analysts, researchers, the trader or the risk panel to avoid numbers — reading
a price series and arguing about it without citing a figure is not a job a research desk can do.
Instead every numeric token a stage writes is checked against the `EvidencePack` that stage was
given. A stage whose prose fails that check is retried with the offending figures quoted back to it
verbatim, up to `MAX_GROUNDING_ATTEMPTS` (3) attempts total. A stage that still fails on the third
attempt is not hidden and not silently passed — it is released marked `degraded`, with its
`GroundingVerdict.issues` attached and shown in the run.

If you see a degraded stage, it usually means the evidence pack did not contain what the stage
needed to support its claim, not that the model fabricated something unprompted. Check that stage's
`EvidencePack.warnings` first — a stale data source, a provider that failed, an empty section — before
assuming the model is the problem.

### Reading a run's states

A stage's `state` is one of `pending | running | succeeded | degraded | failed | blocked | skipped`.
The distinctions are load-bearing, not decorative — this codebase has paid for eliding similar ones
before:

- **`degraded` ≠ `succeeded`.** The stage produced prose, but its numbers never passed the grounding
  gate. Read it as *unverified*, not *wrong* — but do not repeat its figures as confirmed.
- **`blocked` ≠ `failed`.** An upstream stage failed, so this one never ran at all. A blocked stage
  is evidence about its *upstream*, not about itself; go look at the stage(s) it `depends_on`.
- **`skipped` is a configuration outcome, not a failure.** An analyst was deselected, or the debate
  or risk round count meant this turn never happened. Nothing went wrong.

The same distinction holds one level up: `DeskRun.state == "succeeded"` means every stage reached a
terminal non-failed state and a final report exists — it does **not** mean nothing degraded. Check
`DeskRun.degraded` separately before treating every number in the final report as confirmed.

### Where runs are stored on disk

Everything a run writes lives under `data/agentdesk/` (`app.agentdesk.models.agentdesk_dir`):
`data/agentdesk/<kind>/runs/<run_id>/` holds that run's `run.json` snapshot plus per-stage markdown
(`runs_dir` / `run_dir`), and Trading Agents' decision log is
`data/agentdesk/tradingagents/decisions.jsonl` (`memory_log_path`). `data/agentdesk/` is gitignored
— it is working evidence of a model run, not part of the programme's committed record.

The per-call audit trail — the archived prompt, response, token usage and cost for every model call
this application makes, both desks included — lives under `data/loop/agent_calls/`
(`app.agents.models.agent_calls_dir`), already covered by this repo's `data/loop/*` gitignore rule.
Each stage's `call_ids` list is the pointer from that stage into the archive.

### Decision memory

A Trading Agents run logs its decision to `decisions.jsonl` as a `pending` entry, with no model call
at write time. On a later run of the *same ticker*, that pending entry is resolved: realised return
is fetched, alpha is computed against SPY, a short reflection is written, and the entry is rewritten
atomically. Only the **portfolio manager** stage reads past lessons — the four analysts, the two
researchers, the trader and the three risk analysts never see them, so the desk's history informs
the final judgement without biasing the reads that feed it.

### Concurrency

Each desk kind gets one active run at a time — a second `POST /runs` for a kind that already has one
in flight comes back `409`. The lock (`backend/app/agentdesk/jobs.py::DeskRegistry`) is keyed per
`DeskKind`, not global, so a Trading Agents run and a Vibe Trading run never block each other; each
only contends with a second run of its *own* kind.
