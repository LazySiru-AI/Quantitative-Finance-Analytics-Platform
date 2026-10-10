# Strategy Lab & Agent Desk — UX analysis and refactor proposal

Status: **ANALYSIS — no code changed.** Written 2026-09-05 against the working tree at `87ecfd3`
(plus uncommitted edits from other sessions), measured on the live app at `localhost:5174` with a
populated ledger, English, 1280×720 viewport.

Scope asked for: the Strategy Lab and Agent Desk sections first — grouping, duplication, wordiness,
density, user-friendliness — then what generalises to the rest of the app.

---

## 0. Bottom line

The two sections are not disorganised because the pages are bad. Each page is individually careful.
They are disorganised because **nine pages plus seven Competition sub-tabs were added one feature at
a time, each with its own explainer, its own vocabulary and its own end state, and nothing tells the
reader which page comes after which.** Half of the application's on-screen copy now lives in these
two sections, and almost none of it links to the page a reader would go to next.

Six numbers that carry the argument:

| Measure | Value |
|---|---|
| Destinations in the two sections | 9 pages + 7 Competition tabs = **16**, with no landing page for either section |
| Share of all catalog strings owned by these sections | **1,072 of 2,167 keys (49%)**, ~24k English characters |
| Cross-links between the 16 destinations | **2** (Rules → Ticker/SPY, Paper Desk → Agent Workflow). Overview links to none of them |
| Tallest surfaces at 720px | Personas **13.3 screens**, Agent Workflow **6.2**, Competition › Next round **5.9** (17,456 words, 108 checkboxes) |
| Same fact explained more than once | **77 duplicate-text groups** across shards; "How this desk works" ×3, "Recent runs" ×3, "Could not load…" ×9 |
| Density primitives adopted (StatusPill / InfoNote) in these pages | **0 / 0** in every Strategy Lab file and all three desk pages (ScrollRegion: yes) |

The research record matters for the redesign: 33 rounds, a 9,480-cell timeframe sweep, the evolution
loop and the Agent Workflow study have all returned **null or unmeasurable** (see
`docs/reports/EVERYTHING-INVESTIGATED-2026-09-01.md`). The sections are honest instruments for
saying "no". The UI should present them as **one research funnel with a verdict at the top**, not as
sixteen peers.

---

## 1. What exists today

### Strategy Lab ("Testing ideas that are not yet mine")

| Page | What it is | Sub-surfaces | Backend routes | Page tests |
|---|---|---|---|---|
| Competition | Dashboard over the round programme + the endless evolution loop | 7 tabs: Summary, Leaderboard, Agent, Findings, Selection, Next round, Loop (Loop nests Generations, Review queue, Dossier) | 6+1+4+2+1 competition, 13+1+1 evolution | 23 + 129 in sub-panels |
| Backtest | One-symbol workbench: Drawdown, Event study, Scan, Reverse conditioning | 4 stacked panels | 5 | **0** |
| Rules | Rule catalogue + expression tester (tester also mounted on Ticker) | 2 panels | 3 | **0** |
| Timeframes | Rule × interval lift matrix + drill-down chart | scope tabs, horizon tabs, 7×12 grid | 7 | 20 |
| Thesis | Pre-registered thesis loop against a locked holdout | run panel, ledger, holdout, results | 4 | 2 |

### Agent Desk ("Model-run research desks, on our own data")

| Page | What it is | Panels (top→bottom) | Routes | Tests |
|---|---|---|---|---|
| Trading Agents | Fixed 12-stage analyst→PM pipeline on one ticker | Explainer · Run form · Recent runs · Progress · Final report · Decision memory | 6 | 10 |
| Vibe Trading | Preset committee run as a DAG | Explainer · Presets · Run config · Progress · Recent runs | 6 | 7 |
| Agent Workflow | Orchestrator: regime → card → candidates → child TA/Vibe → plan → 4 paper books + study | Explainer · Run config · Progress · Recent runs · Paper book (6 books) · Effectiveness study (3 tables) · Candidates (100 rows) | 10 | 18 |
| Personas | Per-influencer agent with memory, from YouTube transcripts | Add form · Watchlist + Regime consensus · then **9 panels per persona** | 27 | 48 |

Downstream of both sections sits **Paper Desk** (Portfolio section): it hosts the competition roster,
the workflow's autopilot seat and the persona books. It is the consumer of everything the two
sections produce, and it is in a third section.

### Copy volume by shard (English)

| Shard | Keys | EN chars | ≥80 chars | ≥110 chars | Avg |
|---|---|---|---|---|---|
| strategy | 302 | 5,411 | 11 | 3 | 18 |
| competition | 250 | 6,303 | 20 | 14 | 25 |
| competitionRounds | 174 | 3,926 | 8 | 4 | 23 |
| agentDesk | 116 | 4,029 | 13 | 10 | **35** |
| agentWorkflow | 112 | 2,393 | 6 | 2 | 21 |
| persona* (8 shards) + misc.personas | ~140 | ~2,100 | 1 | 1 | ~17 |

Every string is within the prose budget (`proseBudget.allowlist.ts` is empty). The wordiness problem
is no longer individual strings — it is **how many of them are on screen at once**, and how many say
the same thing.

---

## 2. Live measurements (2026-09-05, 1280×720, English, populated data)

| Surface | Screens | Words | Panels | Controls | Note |
|---|---|---|---|---|---|
| Competition › Summary (default tab) | 3.1 | 659 | 5 | 39 round buttons | First panel is "no authored narrative yet"; 22 of 39 round buttons carry a `NO RESULTS` chip |
| Competition › Leaderboard | 1.0 | 560 | 2 | 3 | Good: one table, three pickers |
| Competition › Agent | 1.0 | 80 | 1 | 0 | A tab whose only content is "select an agent from the Leaderboard" |
| Competition › Findings | 1.6 | 1,535 | 5 | 1 | All five disclosures open by default |
| Competition › Selection | 1.0 | 313 | 2 | 1 | Placeholder for the default round (no selection exists for it) |
| Competition › Next round | **5.9** | **17,456** | 6 | **110 inputs (108 checkboxes)** | Every library card rendered as a full prose card in 4 tiers, then a cards × windows checkbox matrix |
| Competition › Loop | 3.1 | 1,117 | 1 | 9 | Form, running config, generations browser, review queue, shelf — one tab |
| Backtest (empty → SPY) | 1.0 → 2.5 | 121 → 339 | 2 → 5 | 2 → 10 | Good empty state; four studies stack once loaded |
| Rules | 1.3 | 410 | 2 | 1 | Tester duplicated on Ticker |
| Timeframes | 1.9 | 310 | 3 | 27 tabs | 169/316 cells measurable; `n/a` fills most of the grid |
| Thesis (QQQ) | 1.0 | 135 | 4 | 3 | Compact, but the run warning is the loudest thing on the page |
| Trading Agents (initial → run opened) | 2.9 → 4.1 | 1,907 → 1,994 | 4 → 6 | 10 | 1,444-char explainer; first control at **y=756px** (below the fold) |
| Vibe Trading | 2.4 | 433 | 4 | 4 | First control at y=394px; 25 recent runs |
| Agent Workflow | **6.2** | 1,465 | 6 | 9 | 6 books, 7 tables, 127 rows; results start 4 screens below the form |
| Personas (5 influencers) | **13.3** | 164,546 | 48 | 28 | 9 panels per persona, **72 "not advice" caveat lines**, 29 pills; grows linearly per persona |
| Overview (for contrast) | 2.7 | 384 | 6 | — | Links to /portfolio, /macro, /paper-desk only |

---

## 3. Findings

Severity: **H** blocks the reader's task or misleads · **M** costs time or trust · **L** polish.

### A. Structure and grouping

- **A1 (H) No section has a front door.** Clicking "Strategy Lab" lands on Competition › Summary; clicking "Agent Desk" lands on Trading Agents' explainer. Nothing states what the section is for, which page to start on, or what the programme has found. The nav blurbs that would do this ("Testing ideas that are not yet mine") render only on the 404 page.
- **A2 (H) Competition is three products in one page.** The manual round programme (Summary, Leaderboard, Agent, Findings, Selection, Next round), the endless loop (Loop, Generations), and the human review queue (Pending seats, Shelf, Dossier) share one tab rail. A reader planning a round and a reader reviewing a promoted card have nothing in common yet see the same seven tabs.
- **A3 (M) Four surfaces evaluate a rule, in two sections.** Ticker (Market) has the Decision table + Rule editor; Report (Market) has the Strategy backtest card; Backtest (Lab) has Event study/Scan/Reverse; Timeframes (Lab) has the rule × interval matrix; Rules (Lab) has the catalogue + a second copy of the editor. The "definition vs evaluation" split argued in `Rules.tsx` is sound, but the evaluation half is scattered across four pages and two sections.
- **A4 (M) Trading Agents and Vibe Trading are the same shape.** Both return `DeskRun`, both render layers of `StageRecord`s, both have Run form → Progress → Final report → Recent runs. Trading Agents is one fixed preset with extra knobs (analysts, debate/risk rounds, trade date, decision memory). Two pages, two explainers, two "Recent runs" lists, two model pickers, two copies of `groupByLayer`/`stageStateLabel`/`errorMessage`.
- **A5 (M) Agent Workflow mixes an operator console with a measurement dashboard.** The run form and progress board belong with the other desks; the 4-arm books, the study and the 100-row candidate log are a research readout that the autopilot seat on Paper Desk already links to. Together they make the page 6.2 screens with results four screens down.
- **A6 (M) Personas is a list page carrying nine detail panels per row.** Digest, Profile, Scorecard, Timeline, Backtest, Ask, Strategy card, Critique, Profile diff — all mounted for every persona at once. No per-persona route exists.
- **A7 (M) The Competition › Agent tab is a dead tab.** It renders a placeholder until a leaderboard row is clicked; it is a drill-in, not a peer view.
- **A8 (L) Thesis is per-symbol like Backtest but lives as a separate page** with its own symbol form; Backtest and Thesis never mention each other.
- **A9 (L) Paper Desk — the consumer of both sections — sits in Portfolio**, one click and one section away. The only link into it from either section is none; the only link out of it is Paper Desk → Agent Workflow.

### B. Wordiness and copy

- **B1 (H) Three explainers open on every visit.** Trading Agents (1,444 chars, six numbered steps + footer), Vibe Trading (533), Agent Workflow (620). They never collapse, are not remembered as read, and push the first control below the fold on Trading Agents. The UI-density plan proposed a stepper with each step's sentence behind ⓘ; that was not done for these pages.
- **B2 (H) One caveat, 72 times.** On Personas, every panel of every persona carries its own "descriptive, not advice / never a signal" line. Five personas produce 72 caveat lines. The copy-style rule ("one explanation per fact, app-wide") is violated by design, not by drift.
- **B3 (M) Stale copy names a tab that no longer exists.** Three strings say "head to Library & Run" (`competition.summary.noRoundsHint`, `competition.leaderboard.noRoundsYet`, `competition.leaderboard.noResultsCallout`); the tab is labelled "Next round". The same flow has three names on one screen: header button "Plan the next round", tab "Next round", panel heading "Run a new round".
- **B4 (M) Duplicated strings across shards: 77 groups.** Within these sections: "Could not load recent runs/this run/configuration" ×3 each, "Budget cap (USD)" ×3, "Final report" ×3, "How this/the desk works" ×3, "Recent runs" ×3 (each page owns a copy on purpose per the shard docstring — which is the policy to change).
- **B5 (M) Tooltips still carry explanations.** `title=` is used 4× on Trading Agents, 5× on Agent Workflow, 4× on SummarySection, 2× on Timeframes — invisible on touch, unreachable by keyboard; the app's own primitive for this (`InfoNote`) is unused in both sections.
- **B6 (L) Hint sentences under every Loop form field.** Books hint (119 chars), sizing hint (119), goal hint (116), tickers hint (115), goal placeholder (117): five paragraphs of help for six controls. Each is within budget; together they are the tallest part of a 3.1-screen tab.
- **B7 (L) Summary tiles repeat their own headings in the hint.** "Best performer — median excess vs SPY at that card's median window, this round's windows only -- not compared to other rounds" (116 chars) under a tile already labelled "Best performer".

### C. Density

- **C1 (H) Competition › Next round renders the whole library as prose.** Four tiers of cards, each with universe, entry/exit rules, stop/target/hold/size and a paragraph of thesis: 17,456 words. Then the run form lists cards × windows as 108 checkboxes.
- **C2 (H) Personas scales linearly and is already 13 screens at five personas.** ScrollRegion bounded each panel (37 regions on the page), but nine bounded panels per persona is still nine panels.
- **C3 (M) Competition › Summary opens on a wall of 39 round buttons**, 22 marked `NO RESULTS`, above an empty "no authored narrative yet" panel. The orientation view needs orientation.
- **C4 (M) Agent Workflow shows six books × (positions table + orders table) + three study tables + candidates** on first load, before any run has been started in the session.
- **C5 (M) Timeframes grid is mostly `n/a`.** 169 of 316 cells measurable, and the visible grid at the default scope shows one populated column; the coverage line explains it but the grid still costs the space.
- **C6 (L) Trading Agents decision memory and recent runs each list 25 entries** with a per-entry expand; there is no filter by symbol or by outcome.

### D. Vocabulary and honesty

- **D1 (H) "Agent" means five things.** A competition strategy card (`agent_id`, "Agents scored", the Agent tab); a Claude role agent (Trading Agents, Vibe); the agent layer (credentials/health); a reference agent (Paper Desk blurb); a proposal agent (loop designer/scout). A reader who has just left Trading Agents reads Competition's "Agent" tab as a model.
- **D2 (H) Thesis is labelled "Agent-proposed" but no model is involved.** `app/thesis/__init__.py`: "No model is wired up here"; proposals come from a fixed five-template catalogue. The nav blurb ("Agent-proposed theses against a holdout") and both page subtitles say otherwise.
- **D3 (M) "Card" means four things:** competition strategy card, thesis card, persona digest card, persona strategy-card draft.
- **D4 (M) Model lists disagree.** Vibe Trading hardcodes four models in the frontend (including a `claude-fable-5` id); Trading Agents reads `available_models` from `/config`; Agent Workflow has no model choice at all.
- **D5 (L) Raw wire enums render as text** (`run.state`, `order.status`, `obs.state`, `arm` ids like `ta_gated`) where a pill would read; the six-tone `StatusPill` exists for exactly this and is unused here.

### E. Duplication in code

- **E1** `groupByLayer`, `stageStateLabel`, `errorMessage`, `POLL_INTERVAL_MS` are copied into each of the three desk pages (and `errorMessage`/poll into Competition). The shard docstrings call this "per-module convention".
- **E2** `formatMoney` exists in `api/tax.ts`, `api/tradingagents.ts`, `api/personas.ts`; `formatReturnPct` is a local copy in `TradingAgents.tsx` of `formatPctFraction` in `api/competition.ts`; `formatFractionPctString` in `api/paperdesk.ts` is a fourth.
- **E3** Page CSS: `Competition.css` 1,586 lines, `AgentWorkflow.css` 420, `TradingAgents.css` 414, `VibeTrading.css` 270 — each with its own stage-state badge classes (`ta-state-*`, `wf-stage-*`, `vibe-stage-*`) that `StatusPill` was built to replace.
- **E4** Two round pickers (`SelectionRoundPicker`, Leaderboard's), plus the Summary picker and the Findings picker, all over the same `selectedRoundId`.

### F. Dead ends (research produces an output nothing consumes)

| Output | Produced on | Where it can go today | Gap |
|---|---|---|---|
| Thesis survivor card | Thesis | Nowhere (no seat, no library entry) | No "promote to card" path; `tournament/` never reads a thesis record |
| Scan discovery / Reverse candidate | Backtest | Nowhere; the banner says "test as a declared trial in a scan" but offers no button | No handoff to Thesis (which is exactly a declared trial) |
| Timeframes cell | Timeframes | Drill-down chart on the same page | No link to Ticker (same symbol/interval) or to Backtest |
| Persona strategy-card draft | Personas | Critique on the same page | Not runnable in Competition; not listed as a candidate |
| Competition promotion | Loop › review queue | Seat on Paper Desk | Works, but Paper Desk is a different section and the seat is not linked back |
| Desk final report / rating | Trading Agents, Vibe | Decision memory (TA only) | No link to the ticker's Report/Ticker page; Vibe has no track record at all |
| Evolution journal | backend `/journal` | Not surfaced | Endpoint exists, no UI |

### G. Beyond the two sections (what generalises)

- **G1** Overview links to Portfolio, Macro and Paper Desk only. Nothing on the home screen says whether the loop is running, whether the agent layer is available, or what the last round found.
- **G2** Ticker and Report are two per-symbol pages with the same symbol form and overlapping content (drawdown, decision table); Report's Strategy backtest card is Strategy Lab content living in Market.
- **G3** Every page owns its own fetch/phase/error scaffolding (`FetchPhase`, `errorMessage`) — the pattern is consistent, which is good, but it is copied, not shared; a `useFetchPhase` hook or a `<Fetched>` wrapper would remove ~40 near-identical blocks app-wide.
- **G4** The two-level nav has no per-section landing; favourites are the only escape hatch. The section blurbs in `nav.ts` are the seed of the landing pages that do not exist.
- **G5** `title=` tooltips app-wide (~110 sites at the last count) remain the only hover help; `InfoNote` adoption is partial.

---

## 4. Proposal: two funnels with a front door each

The user's idea — an overview under each big tab that states what the section does and which flows to
try, then the user picks a flow — is the right shape. Concretely:

### 4.1 Strategy Lab → "Rule · Evidence · Competition · Desk"

**Landing `/strategy` (new, one screen):**
- The verdict, as a pill and one sentence: `NO OOS EDGE · 33 ROUNDS` — "Nothing has beaten SPY out of sample across 33 rounds, 9,480 interval cells and 291 loop generations." (from the research report; a fact the lab exists to state).
- The funnel as four steps with live counts: **Rules** (12 in catalogue) → **Evidence** (169/316 cells measurable · N theses registered) → **Competition** (17 scored rounds · loop idle/running · N cards awaiting review) → **Paper Desk** (N seated).
- Three "try this" flow cards with a concrete starting point each, e.g. "Test one rule on one symbol" (Evidence › SPY › `rsi(14) < 30`), "Read what the last round concluded" (Competition › r26 › Findings), "Review a card the loop promoted" (Competition › Review queue).

**Evidence workbench = Backtest + Timeframes + Rules catalogue + Thesis, one symbol bar.** One
symbol/interval control at the top (as Backtest, Thesis, Ticker and Report each have today), then
tabs: Drawdown · Event study · Scan · Reverse · **Across intervals** (the Timeframes matrix, scoped to
the symbol; sector/universe scope stays as a scope switch) · **Pre-registered test** (the Thesis
loop, renamed — see D2) · **Catalogue** (the Rules table, each row with "run event study" / "see
across intervals" actions). The expression tester stays where a symbol is (Ticker) and in the Scan
tab; the standalone Rules page is folded in. Result: 5 pages → 2 (landing + workbench), Competition
untouched.

**Competition split into two pages:**
- **Rounds** — Summary and Leaderboard merged (the Summary's window strip and the Leaderboard are the same round's tables; one round picker, rendered as a dropdown grouped Scored / Record-only, not 39 buttons); Agent becomes a drawer opened from a leaderboard row; Findings + Narrative + Selection become one "Round record" tab; Next round becomes "Plan & run" with the library as a compact table (one row per card, thesis behind expand) and a two-list picker (cards, windows) instead of a 108-checkbox matrix.
- **Loop** — status + running config, Generations browser, and the **Review queue** promoted to its own tab (it is the one place a human decision is made; today it is at the bottom of the Loop tab).

### 4.2 Agent Desk → "Ask · Orchestrate · Follow"

**Landing `/agents` (new, one screen):**
- Availability at the top: `AGENT LAYER READY · sonnet-5 · $x spent this week` or `UNAVAILABLE · reason` (from `/api/agents/health`, today shown only as a form warning three screens down).
- The desks as three cards: **Research Desk** (Trading Agents + Vibe presets) · **Workflow** · **Personas**, each with what it answers, typical cost, last run and outcome.
- Flow cards: "Research one ticker" · "Ask a committee a question" · "Run the workflow and measure the gates" · "What the influencers are saying".

**Research Desk = Trading Agents + Vibe Trading, one page.** Preset picker first (the Trading Agents
pipeline is the first preset; Vibe's four are the others), then one run form whose preset-specific
fields (analyst toggles, debate/risk rounds, trade date) appear only for that preset, one progress
board, one output viewer, **one Recent runs list across desk kinds** (they already share `DeskRun`),
and **Track record** (decision memory) extended to every desk kind rather than TA only. Explainers
become a one-line summary + ⓘ per preset. One model picker fed by `/config`. Result: two pages, two
explainers, two run lists → one of each.

**Workflow split: Run vs Books & study.** The run page keeps form + progress + recent runs (short).
Books, Effectiveness study and Candidates move to a **Workflow study** page — or, better, to a tab on
Paper Desk beside the autopilot seat they describe, since that is where the reader already compares
books. The universe toggle stays with the tables it filters.

**Personas gets a detail route.** `/personas` lists compact cards (name, platform, note count,
freshness, stance chips) plus the two consensus panels and one caveat banner; `/personas/:slug` shows
Digest · Profile · Calls (scorecard + backtest) · Timeline · Ask & critique · Strategy card · Versions
as tabs. 72 caveat lines → 2.

### 4.3 Today → proposed, at a glance

| Today | Proposed | Change |
|---|---|---|
| (none) | Strategy Lab landing | new |
| Backtest, Timeframes, Rules, Thesis | Evidence workbench (tabs) | merge 4 → 1 |
| Competition (7 tabs) | Rounds (4 tabs) + Loop (3 tabs) | split, and 7 → 7 with Agent tab removed and Review queue promoted |
| (none) | Agent Desk landing | new |
| Trading Agents, Vibe Trading | Research Desk (presets) | merge 2 → 1 |
| Agent Workflow | Workflow run + Workflow study (or a Paper Desk tab) | split |
| Personas | Personas list + `/personas/:slug` | split |
| Paper Desk (Portfolio) | unchanged, plus back-links and "seated from" provenance | link |

Net: 9 pages → 8 pages + 2 landings, with every research output pointing at the page that consumes it.

### 4.4 Cross-cutting rules for the rebuild

1. **One name per flow.** "Plan & run" everywhere the next round is meant; fix the three stale "Library & Run" strings today.
2. **One vocabulary.** "Card" = strategy card only; "thesis" = a pre-registered test; "desk run" = a model run; "persona" = an influencer agent. Competition stops using "Agent" for a card (`agent_id` stays on the wire; the label becomes "Card").
3. **Explainers collapse.** Every "How this desk works" becomes a one-sentence summary + ⓘ (`InfoNote`), remembered as opened per page in `localStorage` like favourites.
4. **One caveat per page.** A page-level banner carries "descriptive, not advice"; panels stop repeating it.
5. **State is a pill.** Stage/run/order states through `StatusPill`; delete `ta-state-*`, `wf-stage-*`, `vibe-stage-*` classes.
6. **Shared desk shell.** `groupByLayer`, `stageStateLabel`, polling, the stage board and the output viewer become `components/deskrun/*`; `formatMoney` gets one home in `api/client.ts`.
7. **Every output has a next step.** Thesis survivor → "Add to library as candidate"; Scan discovery → "Pre-register as a test"; Timeframes cell → "Open on Ticker"; Persona draft → "Add to review shelf"; Desk final report → "Open Report for {symbol}".

---

## 5. Enhancement backlog, phased

| # | Item | Findings | Effort | Risk | Tests touched |
|---|---|---|---|---|---|
| **Phase 0 — copy and vocabulary (no layout change)** | | | | | |
| 0.1 | Fix three "Library & Run" strings; one name for the run flow | B3 | XS | none | Competition.test text asserts |
| 0.2 | Rename Thesis wording: "Catalogue theses" / "Pre-registered test"; nav blurb | D2 | XS | none | nav i18n test |
| 0.3 | Collapse the three desk explainers into summary + `InfoNote` | B1 | S | low | TA/Vibe/Workflow tests that `getByText` a step |
| 0.4 | One page-level caveat banner on Personas; remove per-panel copies | B2 | S | low | Persona component tests asserting caveat text |
| 0.5 | `StatusPill` for stage/run/order states on the three desks and Competition badges | D5, E3 | M | low | snapshot-ish assertions on badge text |
| 0.6 | Dedupe shared strings into `common.*` ("Recent runs", "Budget cap", load errors) | B4 | S | none | none expected |
| 0.7 | Vibe model list from `/config` (add a `/config` route mirroring TA's) | D4 | S | low | Vibe test |
| **Phase 1 — restructure inside existing pages** | | | | | |
| 1.1 | Competition: round picker → grouped dropdown; Agent tab → drawer; Summary+Leaderboard merge | A2, A7, C3 | M | medium | 23 page + Summary/Leaderboard tests |
| 1.2 | Competition › Plan & run: library as table rows; cards/windows as two lists | C1 | M | medium | LibrarySection tests |
| 1.3 | Competition: promote Review queue to its own tab | A2 | S | low | LoopPanel/PendingSeats tests |
| 1.4 | Agent Workflow: move Books/Study/Candidates behind a second tab or page | A5, C4 | M | medium | 18 tests |
| 1.5 | Personas: `/personas/:slug` route; list page compact | A6, C2 | L | medium | 48 page tests + component tests |
| **Phase 2 — landings and merges** | | | | | |
| 2.1 | `/strategy` and `/agents` landing pages (counts from existing endpoints; verdict from a small `programme/verdict` endpoint or a static JSON) | A1, G1 | M | low | new tests; nav tests (section first item changes) |
| 2.2 | Evidence workbench: Backtest + Timeframes + Rules + Thesis under one symbol bar | A3, A8 | L | medium | Timeframes 20, Thesis 2; Backtest/Rules have none — write them first |
| 2.3 | Research Desk: TA + Vibe as presets on one shell; shared Recent runs and Track record | A4, E1 | L | medium | TA 10 + Vibe 7 |
| 2.4 | Overview strip: loop state, agent-layer state, last round verdict, cards awaiting review | G1 | S | low | Overview tests |
| **Phase 3 — close the dead ends** | | | | | |
| 3.1 | Thesis survivor → library candidate (backend: write a card into the candidates tier) | F | M | medium | backend + Thesis |
| 3.2 | Scan/Reverse row → "Pre-register as a test" (prefills the Thesis form) | F | S | low | Backtest (no tests today) |
| 3.3 | Timeframes cell → Ticker link; desk report → Report link; Paper Desk seat → "seated from round r / generation g" back-link | F, A9 | S | none | minor |
| 3.4 | Persona strategy-card draft → review shelf | F | M | medium | backend + Personas |
| 3.5 | Surface `/journal` on the Loop page (or delete the endpoint) | F | S | low | — |

Effort: XS < 1h, S half day, M 1–2 days, L 3–5 days (Sonnet workers in parallel where file-disjoint,
per the project's usual split). Phase 0 is safe to run in one session; Phases 1–2 want the page tests
green first and `--only` commits because the tree is shared.

---

## 6. Decisions for the owner

1. **Merge Trading Agents into a preset of one Research Desk page, or keep it as its own page** with the shared shell underneath? (Recommendation: merge; the contract already makes it one `DeskKind` among three.)
2. **Where do Workflow books/study live** — a second Agent Desk page, or a Paper Desk tab beside the autopilot seat? (Recommendation: Paper Desk tab; that is where books are compared.)
3. **Evidence workbench: fold Thesis in as a tab, or keep Thesis standalone** because its run has permanent side effects? (Recommendation: fold in, keep the warning; a tab is not less visible than a page.)
4. **Landing pages: static copy + live counts, or a proper "verdict" endpoint** summarising the programme? (Recommendation: start static + counts; the verdict sentence changes rarely and is already written in the research report.)
5. **Rename Competition's "Agent" to "Card" on screen**, leaving `agent_id` on the wire? (Recommendation: yes.)

---

## 7. Method and evidence

- Read every page in both sections, the shared components (`InfoNote`, `ScrollPanel`, `StatusPill`, `Collapsible`), `nav.ts`, `App.tsx`, all seven message shards, `docs/COPY-STYLE.md`, `docs/UI-DENSITY-PLAN.md`, `docs/AGENT-DESK-CONTRACT.md`, `docs/AGENT-GAP-ANALYSIS.md`, `docs/reports/EVERYTHING-INVESTIGATED-2026-09-01.md`, the 2026-08-29 UAT button sweep on Competition, and the backend packages `thesis`, `workflow`, `paperdesk`, `personas` for the data flows in §3F.
- Measured each surface in the running app (`localhost:5174`, backend `:8000`, auth off on this instance) with one script per page: `main.content` scroll height ÷ 720, word count, panel/heading/control/table counts, `.scroll-region`/`.status-pill`/`details`/`[title]` counts. Competition tabs were switched by dispatching clicks on the tab rail.
- Copy statistics from `frontend/src/i18n/messages/*.ts` with a small Node script (keys, EN/KO characters, strings ≥80/≥110, exact-text duplicates across shards).
- Not measured: Korean-mode heights (the browser pane collapsed to a zero-height viewport during that check; the numbers were discarded), Paper Desk (still loading at 5s), and the Competition › Agent tab with a selection.
