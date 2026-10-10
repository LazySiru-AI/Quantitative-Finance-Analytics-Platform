# Manager Desk — design

_Written 2026-09-08. Status: **design only, not started.** Execution begins on the owner's go, after
the decisions in §9. Companions: `AGENT-DESK-CONTRACT.md` (desk conventions), `PERSONA-CHAT-PLAN.md`
(the chat this forks), `INFLUENCER-CONTRACT.md` Phases 9–10._

## 0. The ask, restated

A new tab under **Agent Desk**: a **manager agent** that reads across the whole application —
personal account and tax, the Paper Desk (reference agents, persona replay books, persona traders),
the research program, the three agent desks, the influencer personas, market feeds and data health —
and produces a **second, agent-curated Overview**: what changed and what matters **since yesterday /
last week**, in a very dense layout, plus a **chat** with the manager and the ability for it to
**spawn its own research** (commission a Trading Agents run, a Vibe run, a Workflow run, a persona
chat) when a question needs it. Model calls run only when the agent layer is up (Claude CLI
connected), like the other desks.

**One boundary, stated once and built in.** The owner asked for the manager to "come up with
strategy across all information including my personal tax." The manager will produce a **situation
assessment**: where the lenses agree and disagree, exposures, risks, contradictions, open questions,
and research it recommends commissioning. It will **not** produce buy/sell/hold instructions or price
targets for the owner's account. That is the same line every other desk and the persona feature
already hold, and it is what keeps the output honest — the app's own research has found no edge, and
a manager that dressed synthesis up as trade orders would be the exact failure the repo guards
against. The tab renders this framing permanently, not behind a disclosure.

## 1. What exists (verified 2026-09-08)

| Fact | Where | Consequence for the design |
|---|---|---|
| `DeskKind` is a closed literal `"tradingagents" \| "vibedesk" \| "workflow"` | `app.agentdesk.models:57` | Adding `"manager"` gives the desk its own single-slot registry entry, `data/agentdesk/manager/runs/`, `RunStore` persistence, and the `DeskRun`/`StageRecord` wire shape for free. |
| The registry is single-slot **per kind**; the Workflow desk already spawns TA/Vibe children in-process and awaits them | `app.agentdesk.jobs`, `app.workflow.pipeline:_launch_ta/_launch_vibe/_await_child` (25-min timeout, 2 s poll, cancel-aware) | The manager's "spawn own research" is this exact template one level up. No new concurrency machinery. |
| Spawning children from a **detached** scheduled process crashes (`PyEval_SaveThread`/SSL) | `strategy-program/tools/phase_b_daily.cmd` comments | Any manager daemon runs **inside the server process** like `app.workflow.loop`, never as a Task-Scheduler script. |
| `build_pack(symbol, as_of, sections)` is single-symbol with a closed section vocabulary | `app.agentdesk.evidence:677` | The manager needs its **own** evidence assembler that mints `EvidenceItem`s from portfolio/tax/desk/persona/feed figures. `EvidencePack`/`render_pack`/`run_grounded`/`grounded_values` are reused unchanged (a `symbol=""` pack is already a supported shape). |
| **No delta engine.** Portfolio, tax and Paper Desk state are computed live per request; nothing persists yesterday's copy | Overview recon; `app.paperdesk` docstrings ("a deterministic replay, not a ledger") | "Since yesterday" needs (a) a **manager-owned daily snapshot** to diff, plus (b) the append-only streams that already exist. |
| Append-only, timestamped streams that already exist | evolution `ledger.jsonl` / `promotions.jsonl` / `amendments.jsonl`; desk `runs/` (TA, Vibe, Workflow); live decisions; persona notes + `DigestCard.as_of/window_start`; transactions; `MacroTile.change.{day,week,month,ytd}` | These are the honest "what happened" material; the model never has to infer them. |
| The `agent_calls` archive has **no listing endpoint** | `app.agentdesk.telemetry` (point lookups only) | A "recent agent activity" aggregator is new. |
| Freshness catalog: 11 sources with `last_updated/age/status`; 4 are structurally `unknown` | `app.market.freshness:report` | The brief can say "stale" honestly and must never claim to know when news last changed. |
| "Agent layer up" gate + UI | `app.agents.client.is_available()/credential_source()`; `tradingAgentsApi.config().agent_available/agent_reason` used by `AgentDeskLanding` | Reuse. The **deterministic** half of this tab (changes feed) works with the model down; only triage/synthesis/chat need it. |
| Chat precedent | `app.personas.chat` (ChatStore, `chat_turn`, `MAX_HISTORY_TURNS=8`, only non-degraded prior turns enter evidence) + `PersonaChat.tsx` | Fork, swapping persona evidence for the manager's cross-source evidence. |
| Density vocabulary + budgets | `ScrollRegion`/`StatusPill`/`InfoNote`/`Glyph`/`CountdownBar`, `tile-grid`, `docs/COPY-STYLE.md`; `DigestCard{headline, themes, as_of, grounding}` | The feed row = a DigestCard-shaped line. |
| **Owner-only** data | `auth/gate.py OWNER_ONLY_PREFIXES`: `/api/portfolio`, `/api/tax` | The manager reads services in-process (not through the HTTP gate), so its **output** must be scoped: a brief containing account/tax must only be served to an owner session. |
| Nav | Agent Desk = Overview / Research Desk / Agent Workflow / Personas / Backfill Tasks | The tab lives here. The contract's "Item 1/2/3" table is stale (pre-merge); place by the live `nav.ts`. |
| Cost gates | `LEDGER.check(model_spend_daily_cap_usd)` (persona routes), per-desk caps, all money-spending daemons default off | Same three hooks, same opt-in shape. |

## 2. Architecture — three layers, model only in the third

```
┌──────────────────────────────────────────────────────────────────────────┐
│ A. INFORMATION BUS  (deterministic, no model, fail-soft per source)      │
│    app.manager.sources.collect(settings, scope) -> ManagerSnapshot        │
│    portfolio+tax [owner] · paper desk · persona books · trader books ·   │
│    research program · desk runs · live decisions · persona cards/       │
│    watchlist/regime/timeline · macro (+deltas) · calendar · news ·       │
│    freshness · evolution streams · transactions                          │
├──────────────────────────────────────────────────────────────────────────┤
│ B. SNAPSHOT + DIFF  (deterministic)                                       │
│    app.manager.snapshots: persist ManagerSnapshot daily;                  │
│    diff(today, T-1 | T-7) + stream filters -> ChangeSet (typed, severity) │
│    ==> GET /api/manager/changes?window=   works with the model DOWN       │
├──────────────────────────────────────────────────────────────────────────┤
│ C. THE MANAGER  (model, grounded, DeskKind "manager")                     │
│    DeskRun stages: collect -> triage -> synthesis -> research_plan ->     │
│    [commission children] -> brief.   Chat threads.  Opt-in daily loop.    │
└──────────────────────────────────────────────────────────────────────────┘
```

The split is the whole design. Layers A and B are the "filter and massage" the owner asked for, done
by rules so they are cheap, reproducible, and available when the CLI is not connected. Layer C only
**ranks, narrates, synthesises and commissions** over facts it was handed — every number it states is
an `EvidenceItem` minted from the snapshot, so the existing grounding gate rejects anything invented.

### 2.1 Layer A — the information bus

`app.manager.sources` — one `collect(settings, *, scope: "owner"|"member", as_of=None) ->
ManagerSnapshot`. Each source is its own function returning `(section, warnings)` and **never raises
past the module** (the `app.agentdesk.evidence` idiom and the Overview's eight-independent-fetches
idiom, server-side). Sources and what they read (all existing services, called in-process):

| Section | Reads | Owner-only |
|---|---|---|
| `account` | `app.api.portfolio._build_report()` → positions (symbol, weight, day change, sector, unrealised), totals with the partial-total gap lists, cash, `AccountSummary` realised | yes |
| `tax` | `/api/tax/report` (YTD short/long, deferred vs permanently disallowed — never summed), `/api/tax/wash-sales` (open windows, `days_until_safe`) | yes |
| `paperdesk` | `PaperDeskState` books/desks (equity, total_return, excess_return, drawdown, open positions, provenance) | no |
| `persona_books` / `persona_traders` | `persona_books()`, `list_trader_books()` (return, benchmark, excess, latest decision) | no |
| `research` | `/api/competition/next-round` (carry-forwards, blockers), latest `GenerationDetail.digest_markdown`, `pending-seats`, promotions since T | no |
| `desks` | `DeskRunSummary` lists for TA/Vibe/Workflow since T (state, degraded, rating, cost) | no |
| `live` | `LiveDecisionRecord`s since T | no |
| `personas` | `DigestCard`s (`as_of`, headline, themes, mentions), `watchlist`, `regime`, `timeline` stance points since T, `chat_context.stale` | no |
| `market` | `MacroSnapshot` tiles with `change.day/week`, fear/greed, movers | no |
| `events` | `EventCalendar` next 7 days, `holdings_covered` | no |
| `news` | macro news + news for held symbols (titles/published only) | mixed (holdings list is owner) |
| `data` | `FreshnessReport` (status per source), refresh/social status | no |
| `activity` | transactions since T | yes |

`ManagerSnapshot` is a frozen model of typed sections + a `warnings` list + `as_of` + `scope`. Money
is decimal strings, rates carry `n`, partial totals keep their gap lists — the manager inherits every
honesty convention because it never re-derives a figure.

### 2.2 Layer B — snapshot + diff (the "since yesterday / last week" engine)

`app.manager.snapshots`:
- `save(snapshot)` → `data/agentdesk/manager/snapshots/<YYYY-MM-DD>.<scope>.json` (atomic write; one
  per day per scope; the daily loop or any brief writes it).
- `diff(current, previous) -> ChangeSet` — rule-based change detectors, one per section, each
  emitting typed `ChangeItem`s with a **severity** and a **source ref**. Examples of rules (the
  initial catalogue; each is a small pure function with a fixture test):
  - account: position weight moved ≥ 2 pts; day change ≤ −3% or ≥ +3% on a ≥ 2% weight; a symbol
    became unpriced; equity incomplete; new tax warning group; cash below N.
  - tax: wash-sale window **opened** or **closes within 3 days**; YTD net gain crossed a threshold;
    new permanently-disallowed loss.
  - paperdesk: a seat's excess vs benchmark moved ≥ 2 pts; a new promoted seat; a seat rejected
    orders; persona-trader decision produced trades; a book's drawdown deepened.
  - research: a new generation finished (digest present); a new pending seat; a blocker added; a
    promotion recorded.
  - desks: any run finished since T (with rating/degraded/cost); a run failed or was cancelled.
  - personas: a stance **flip** on a held symbol; a new note on a persona; consensus watchlist
    entrants/leavers; regime tally changed; profile stale.
  - market/events: a macro tile moved beyond its week range; fear/greed regime change; an event
    (FOMC/earnings on a holding) entering the 7-day window.
  - data: any source flipped `fresh → stale`; refresh sweep failed; social daemon unhealthy.
- Streams that are append-only (desk runs, live decisions, evolution jsonl, persona notes,
  transactions) are **filtered by timestamp** into the ChangeSet directly — no diff needed and no
  risk of a missed day.
- `window`: `"yesterday"` (diff vs the most recent prior snapshot, plus streams since that
  snapshot's `as_of`), `"week"` (vs the snapshot 7 days back, streams since), `"custom"` (a date).
  When no prior snapshot exists the diff is empty and the tab says so; the streams still populate.

This layer is what makes the tab useful on day one and with the model down.

### 2.3 Layer C — the manager desk

`DeskKind` gains `"manager"`. One **brief** = one `DeskRun` (kind `manager`) with fixed stages:

| stage_id | kind | what it does | grounded |
|---|---|---|---|
| `collect` | deterministic | `collect()` + `save()` + `diff()` → snapshot, ChangeSet | — |
| `triage` | model | Rank the ChangeSet: `attention` (act/look today) / `notable` / `fyi`; write one dense headline (≤ 120 chars) per item **in the owner's terms**; cite the `source_ref` of every item; may merge related items | yes |
| `synthesis` | model | The situation assessment across sources: where lenses agree/disagree (e.g. three personas bullish NVDA vs Creator D bearish vs the portfolio's 3% weight vs a desk's Underweight), concentration/regime/tax-timing observations (e.g. "an open wash-sale window on MU sits under a persona-trader buy"), risks, open questions. Structured output, every figure cited. **Schema has no field for account instructions.** | yes |
| `research_plan` | model | 0–3 proposed **commissions** with rationale, kind, params, budget: TA on a symbol; a Vibe question; a Workflow run; a persona chat question. | yes (rationale) |
| `commission` | deterministic | Per the autonomy setting: `propose` → stop, surface for approval; `auto_bounded` → spawn approved kinds within the per-brief cap via the workflow spawn template, await, attach each child's `DeskRunSummary` + final one-liner. | — |
| `brief` | model | The final dense `Brief`: attention list, per-area changes, synthesis, research status, caveats, data health. Markdown + structured. | yes |

Every model stage runs `run_grounded` over a **manager EvidencePack** built by
`app.manager.evidence.build(snapshot, changeset)`: one `EvidenceSection` per snapshot section, every
numeric figure minted as an `EvidenceItem` (with `as_of` and `source`), the ChangeSet rendered as
text. The gate therefore checks the manager's prose against exactly the facts it was handed; a
number not in the snapshot degrades the stage (never 5xx, never silently kept).

**Citations.** Every `ChangeItem`, brief bullet and chat answer carries `source_refs` — typed ids the
UI can link: `run:<run_id>`, `note:<note_id>`, `symbol:<SYM>`, `event:<id>`, `gen:<n>`,
`snapshot:<section.path>`, `txn:<id>`. The UI renders them as jump chips (to the Symbol page, the
run, the persona, the tax row). Refs outside the evidence set are dropped, not repaired (the persona
chat rule).

**Chat** (`app.manager.chat`, forked from `app.personas.chat`): threads at
`data/agentdesk/manager/chats/<thread_id>.json`; a turn's evidence = the latest `Brief` + snapshot
sections relevant to the question (lexical relevance over section text, the persona retriever's
idea) + prior non-degraded turns; grounded; citations as above. Two extra verbs the persona chat
lacks: **`commission`** (the manager proposes a child run in its answer and, if the autonomy setting
allows, starts it and returns the `run_id`; a later turn or the Research panel folds the result) and
**`refresh`** (re-collect before answering when the snapshot is older than N minutes). The chat never
answers with account instructions; the system prompt forbids it and the schema has no slot for it.

**Spawning research** reuses `app.workflow.pipeline`'s structural-request + `service.start_run` +
`_await_child` pattern, with the manager's own `_CHILD_TIMEOUT_S`. Children claim their own slots, so
a manager brief can run one TA + one Vibe + one persona chat concurrently; two manager briefs cannot
overlap (single manager slot), which is also the natural cost guard.

**Daily loop** (`app.manager.loop`, opt-in `manager_autopilot_enabled=False`): copies
`app.workflow.loop` — in-process daemon, wakes at `manager_brief_time_et` (default 09:45 ET, after
the data sweep and the workflow fill), runs one brief with `window="yesterday"`, honours the caps,
escalates log level after N consecutive failures, never dies. In-process only (§1).

### 2.4 "Only when the service is up and connected"

The page reads `tradingAgentsApi.config()` like `AgentDeskLanding`. When `agent_available` is
false: the **Changes** panel still renders (layer B), the last persisted brief renders read-only with
a "stale · model unavailable · <reason>" pill, and Run brief / Chat / Commission are disabled with the
reason as the tooltip. Nothing is hidden; nothing pretends to be live.

## 3. Wire contract (draft, to be pinned into `AGENT-DESK-CONTRACT.md` as "Manager Desk" before Phase 1)

```ts
type DeskKind = "tradingagents" | "vibedesk" | "workflow" | "manager";   // models.py gains the literal
type Window = "yesterday" | "week" | "custom";
type Severity = "attention" | "notable" | "fyi";
type Scope = "owner" | "member";

interface SourceRef { kind: "run"|"note"|"symbol"|"event"|"gen"|"snapshot"|"txn"|"persona"|"seat"; id: string; label: string; }

interface ChangeItem {
  id: string; area: "account"|"tax"|"paperdesk"|"research"|"desks"|"live"|"personas"|"market"|"events"|"data"|"activity";
  rule: string;              // the detector that fired, e.g. "wash_window_closing"
  severity: Severity;        // rule default; triage may re-rank
  headline: string;          // ≤120 chars, dense
  detail: string;            // ≤240 chars, the "why"
  as_of: string; observed_at: string;
  figures: Record<string, string>;   // decimal strings, the numbers behind the headline
  source_refs: SourceRef[];
}
interface ChangeSet { window: Window; from: string | null; to: string; scope: Scope; items: ChangeItem[];
  sections_missing: string[];       // sources that failed to collect (fail-soft), named
  prior_snapshot: string | null;    // null => no diff possible yet, streams only
  warnings: string[]; }

interface Commission {
  commission_id: string; kind: "tradingagents"|"vibedesk"|"workflow"|"persona_chat";
  params: Record<string, unknown>; rationale: string; budget_usd: string;
  state: "proposed"|"approved"|"running"|"succeeded"|"failed"|"cancelled"|"declined";
  child_run_id: string | null; child_summary: string; source_refs: SourceRef[];
}

interface BriefBullet { text: string; source_refs: SourceRef[]; }
interface Synthesis {
  assessment: BriefBullet[];   // the situation, dense
  agreements: BriefBullet[];   // where lenses agree
  conflicts: BriefBullet[];    // where they disagree
  risks: BriefBullet[];
  open_questions: BriefBullet[];
  caveat: string;              // fixed: descriptive, no edge measured, not advice
}
interface Brief {
  brief_id: string; run_id: string; scope: Scope; window: Window; as_of: string; generated_at: string;
  attention: ChangeItem[]; changes: ChangeSet;
  synthesis: Synthesis; commissions: Commission[];
  data_health: { stale: string[]; unknown: string[]; };
  degraded: boolean; grounding: GroundingVerdict; cost_usd: string; final_md: string;
}

interface ManagerConfig { agent_available: boolean; agent_reason: string; autonomy: "propose"|"auto_bounded";
  autopilot_enabled: boolean; brief_time_et: string; caps: { brief_usd: string; commission_usd: string; chat_usd: string; daily_usd: string; };
  last_brief_at: string | null; spent_today_usd: string; }

interface ManagerChatTurn { turn_id: string; asked_at: string; question: string; answer: string;
  source_refs: SourceRef[]; commissions: Commission[]; refreshed: boolean;
  grounding: GroundingVerdict; degraded: boolean; cost_usd: string; }
interface ManagerChatThread { thread_id: string; title: string; created_at: string; updated_at: string;
  turn_count: number; spent_usd: string; turns: ManagerChatTurn[]; }
```

```
GET    /api/manager/config                                  -> ManagerConfig
GET    /api/manager/changes?window=&date=                   -> ChangeSet        (deterministic; works with model down)
POST   /api/manager/snapshot                                -> {as_of, scope}   (collect + save now)
POST   /api/manager/briefs {window?, date?}                 -> DeskRun (202)    (kind "manager"; poll /runs/{id})
GET    /api/manager/runs, /runs/{run_id}, /runs/{run_id}/telemetry  (the standard desk trio)
GET    /api/manager/briefs/latest, /briefs/{brief_id}       -> Brief
POST   /api/manager/commissions/{commission_id}/approve|decline -> Commission   (propose mode)
GET/POST /api/manager/chats, /chats/{id}, DELETE /chats/{id}, POST /chats/{id}/turns {question, refresh?} -> ManagerChatTurn
```
Errors: the desk table (404 / 409 slot-or-budget / 422 / 503 agent unavailable) + 429 daily cap.
**Auth:** `/api/manager` is added to `OWNER_ONLY_PREFIXES` for v1 (the brief carries account/tax). A
member-scoped brief (`scope="member"`, sections `account/tax/activity` omitted) is a Phase 6 option,
not v1 — see §9.1.

## 4. The tab

Agent Desk › **Manager** (`/manager`, `frontend/src/pages/Manager.tsx`, `frontend/src/api/manager.ts`,
i18n shard `messages/manager.ts` en+ko). Desk-page layout convention: a static explainer strip on
top, working surface below. Density is the brief: every panel is a `ScrollRegion`, every row a
DigestCard-shaped line, every state a `StatusPill`, every "why" an `InfoNote`, all copy inside
`COPY-STYLE.md` budgets.

```
┌ Manager ─────────────────────────────────────────────────────────────────────────────┐
│ [agent: connected · CLI] [last brief 09:45 · 7m ago] [today $0.42 / $25] [propose ▾] │
│ Window: (● yesterday) ( week ) ( custom ▾ )     [Run brief now]  [Snapshot now]        │
│ ‹not advice · descriptive · model's synthesis of the app's own lenses›  (always visible)│
├─ ATTENTION (ranked) ─────────────────────────────── ScrollRegion sm ──────────────────┤
│ ▲ MU wash-sale window closes in 2d; persona-trader Creator C bought MU Fri   [tax][run] │
│ ▲ NVDA: 3 personas bullish, Creator D bearish, desk TA Underweight; 3.0% wt   [sym][run] │
│ ● Gen 41 finished: 0 promoted, 1 pending seat awaiting you                  [gen]      │
│ ○ Fear/Greed 71→64 (week); 10y −9bp                                         [macro]    │
├─ CHANGES BY AREA (tile-grid, each ScrollRegion md) ──────────────────────────────────┤
│ Account & Tax │ Paper Desk (ref vs personas) │ Research │ Desks (runs) │ Personas │ … │
├─ SYNTHESIS ─────────────────── ScrollRegion md ── [caveat pinned] ───────────────────┤
│ assessment · agreements · conflicts · risks · open questions  (bullets, cited chips)  │
├─ RESEARCH ──────────────────────────────────────────────────────────────────────────┤
│ proposed: [TA · NVDA · $5 · rationale…] (Run) (Decline) │ running: Vibe·MU 3/7 stages │
│ done: TA·NVDA → Underweight (degraded) $4.90  [open run]                             │
├─ CHAT ───────────────────────── PersonaChat pattern ─────────────────────────────────┤
│ threads ▾ │ transcript with cited answers, commission chips │ composer [refresh ☐]   │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

Rules the page enforces (tests): the not-advice line renders unconditionally; `degraded` and `stale`
pills always visible; `sections_missing` named in the header, never silently dropped; partial totals
shown as partial; `n`/as-of on every rate; the Changes panel renders with `agent_available=false`;
Run/Chat/Commission disabled with the reason when unavailable; commission approval is a click, never
implied; citations render as jump chips.

## 5. Cost model and controls

Settings (all mirroring existing names/shapes): `manager_brief_cap_usd="3"` (per brief, all model
stages), `manager_commission_cap_usd="6"` (per child; a TA run is ~$5), `manager_chat_cap_usd="2"`
(per thread), `manager_autonomy="propose"`, `manager_autopilot_enabled=False`,
`manager_brief_time_et="09:45"`, `manager_model` (default `DEFAULT_MODEL`; the owner may set Sonnet
for `synthesis` only via `manager_synthesis_model`). Every model call: `LEDGER.check(daily cap)` first;
each brief mints its own `AgentBudget`; each child run gets its own per-child budget; all
`AgentCall`s archived; a manager telemetry endpoint sums own stages + children (the workflow
`ChildRunTelemetry` recursion).

Estimate: layers A+B are free. A brief = triage + synthesis + research_plan + brief ≈ 4 calls on a
~15–25k-char evidence text ≈ $0.10–0.20 (Haiku) / $0.40–0.80 (Sonnet synthesis). Commissions are
the real spend (TA ≈ $5, Vibe ≈ $1–3, persona chat ≈ $0.05) and are therefore gated by autonomy
and capped per brief. A daily propose-mode brief costs well under a dollar a day.

## 6. Data readiness and honest limits

- **Day one has no prior snapshot**, so `changes` is streams-only until the second day; the tab says
  "no prior snapshot; showing activity streams since <as_of>". Running `POST /snapshot` tonight makes
  tomorrow's "yesterday" real.
- **Four feeds are structurally `unknown` freshness** (macro snapshot, calendar, EDGAR, news share a
  URL-less cache). The brief labels them "age unknown" and never claims "new since yesterday" for
  them; news deltas come from `published` timestamps on items, not cache age.
- **Personas' notes carry no upload dates** (known); persona "since yesterday" therefore means notes
  *ingested* since, and stance flips are dated by `ingested_at`. Stated in the persona area's note.
- **Research findings are prose** (`REPORT.md` heuristics); the manager quotes `next-round`'s
  authored carry-forwards as authoritative and the parsed findings as heuristic, labelled.
- **No edge has been measured anywhere**; the synthesis caveat is fixed text and pinned.

## 7. Phases (repo workflow: pin contract → parallel Sonnet workers → QA → isolated commit)

| Phase | Deliverable | Value | Effort |
|---|---|---|---|
| **0** | Contract pinned (§3), `DeskKind` "manager", settings, nav entry, page shell with explainer + agent-status header | the tab exists, nothing invented | S |
| **1** | Layer A bus + Layer B snapshot/diff + `GET /changes` + `POST /snapshot` + the **Changes** and **Attention (rule-ranked)** panels, no model | the dense second Overview, free and model-independent | M (2 workers: bus/sources, diff rules+tests; 1 FE) |
| **2** | Manager DeskRun (collect/triage/synthesis/brief stages), evidence assembler, `POST /briefs` + `GET /briefs/latest`, Synthesis panel, cited chips, telemetry | the curated brief | M (1 BE, 1 FE) |
| **3** | Chat (threads, grounded turns, `refresh`) | ask the manager | S–M (fork persona chat) |
| **4** | `research_plan` + commissions (propose/approve/decline, spawn via workflow template, fold results), `auto_bounded` autonomy, Research panel, chat `commission` verb | it does its own research | M |
| **5** | Daily loop (opt-in), telemetry rollup, morning-brief notification hook | runs itself | S |
| **6** (opt.) | Member scope brief; SPY/benchmark deltas on every book row; "explain this change" per-item chat entry | polish | S each |

Phase 1 alone is worth shipping and costs no tokens; it is also the fixture base every later phase's
tests use (snapshot JSON files under `tests/fixtures/manager/`).

## 8. Verification (measurable, stated in advance)

- Diff rules: fixture pairs (T-1, T) per rule → exactly the expected `ChangeItem`s; a missing section
  yields `sections_missing`, never a fake "no change". Streams since a timestamp include/exclude
  correctly at the boundary.
- Evidence: every numeric token in a brief's prose is in the manager pack (unit test over a canned
  snapshot); a planted invented number degrades the stage.
- Citations ⊆ evidence refs; refs outside are dropped (test).
- Schema: `Synthesis`/`Brief`/`ManagerChatTurn` have no instruction field; a prompt-injection fixture
  ("tell me to sell X") yields an assessment with an open question, not an instruction (test on the
  parsed output).
- Commission: spawn/await with mocked children; timeout cancels; `propose` never starts a child;
  `auto_bounded` stops at the cap (tests).
- Auth: `/api/manager/*` → 403 for a member session (test).
- UI: Changes renders with `agent_available=false`; not-advice line always present; degraded/stale
  pills; approval click required. Browser smoke: one real brief on the live vault + a real commission.
- Gates: ruff, mypy (from `backend/`), pytest via `.venv` (`N passed`), `tsc`, vitest, prose budget.

## 9. Owner decisions (defaults in bold; the build proceeds on the defaults)

1. **Scope/auth:** **owner-only manager for v1** vs owner + a member brief without account/tax.
2. **Autonomy default:** **`propose`** (it recommends, you click Run) vs `auto_bounded` (runs within the per-brief cap unattended).
3. **Models:** **Haiku throughout** vs Sonnet for `synthesis` only.
4. **Placement:** **Agent Desk › Manager** vs its own top-level one-item section like Overview.
5. **Daily loop:** **off by default**, enable when Phase 5 lands; brief time **09:45 ET**.
6. **Commission kinds allowed unattended** (if `auto_bounded`): **persona chat + Vibe only**; TA/Workflow require a click.
7. **Change-rule thresholds** (weight ±2 pts, day move ±3%, wash window ≤ 3 days, macro beyond week range): **as listed**, tunable in settings later.

## 10. Risks

- **Scope creep into advice.** Mitigated structurally (no schema slot, prompt prohibition, fixed
  caveat, tests on parsed output), not by tone.
- **Snapshot drift / missing days.** Diff falls back to the nearest prior snapshot and names the gap;
  streams are independent of snapshots.
- **Cost surprise from commissions.** Propose-mode default; per-brief and per-child caps; single
  manager slot; daily aggregate cap.
- **Owner-only data leaking to a member session.** v1 makes the whole prefix owner-only; the member
  brief is a separate, explicit scope.
- **Concurrent sessions** editing `nav.ts`/`models.py`: `DeskKind` is a one-line change; commit it
  alone in Phase 0 and check for other sessions' hunks before every commit.
