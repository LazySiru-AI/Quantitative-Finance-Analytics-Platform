# Refactor plan — tabs, Overview↔Manager, phone notifications, aligned cards

Date: 2026-09-10. Status: **analysis + plan, awaiting owner decisions (§6). Nothing built.**
Branch context: analysed on `strategy-program`; `beta` (origin `0d5c3af`) differs only in TSX density polish on six pages — no layout CSS differs, so every finding below holds on both.

How this was measured: four read-only recon passes (nav inventory + cross-link/recency proxies, Overview↔Manager section-by-section overlap, notification event-source catalogue, card/scroll primitive + grid audit). Every `file:line` cited was read, not inferred. Where a claim is inference it says so.

---

## 0. Summary

| Thread | Finding | Recommendation |
|---|---|---|
| Rarely-used tabs | **The app has zero usage telemetry** — no request log, no page-hit ledger. "Rarely used" can only be inferred from inbound cross-links + commit recency. | Demote three tabs to buttons inside a parent tab (Wash Sales→Tax, Backfill→Personas, Thesis→Evidence), sweep stale legacy links, and add a tiny local route-hit logger so the *next* pass is measured. |
| Overview ↔ Manager | They share data but not the question: Overview = **standing state** (member-visible, works with no snapshots and with the model down); Manager = **what changed since a snapshot** (owner-only, 34 typed rules + brief/chat/commissions). 12 figures appear on both; only 1 is a true duplicate. Both have a panel titled "Attention" and there are **zero links between the pages**. | Keep both. Codify the split, bridge them (cross-links, rename Manager's panel). Reject a tab-merge. Fix two real defects found on the way. |
| Phone notifications | The Manager change feed already *is* a unified event feed (severity + dedupe id) but it is daily + snapshot-diff, with no `since` cursor; paper-desk fills are not persisted; **no outbound channel of any kind exists**; auth is cookie-only. | Add a small append-only `notify` event log + `since` endpoint fed by the Manager feed and direct intraday hooks; a pluggable sender (ntfy first); a read-only service token; the Claude-composed digest on a scheduled task on top. |
| Aligned cards | **No card has a height.** Grids use `align-items:start` (ragged by design) or stretch the box while the inner `ScrollRegion` never fills it (`flex:1` nowhere). `grid-auto-rows` appears nowhere. | A `Card` + `CardGrid` primitive composed from the existing `.panel` head + `ScrollRegion` body + `Collapsible` long form; `grid-auto-rows` per size token; in-place full-row expansion; migrate Manager → Overview → Paper Desk → Personas → drilldowns. |

---

## 1. Tabs: grouping and demotion

### 1.1 Evidence (proxies, not usage)

Inbound = `<Link>`/`navigate()` targets from other pages (nav rail excluded). Commits = touches on `strategy-program` (young history, 2026-08-09→09-09).

| Destination | Route | Inbound | Last commit | Commits | Verdict |
|---|---|---|---|---|---|
| Wash Sales | `/wash-sales` | **0** | 09-02 | 4 | **Demote → tab/button inside Tax** (same tax-lot mechanics; Tax has 23 commits and is the worked page) |
| Backfill Tasks | `/backfill` | **0** | 09-07 | 3 | **Demote → button/panel inside Personas** (`nav.ts` already says it "feeds the same per-influencer notes, not a desk of its own") |
| Thesis | `/thesis` | 0 (nav only) | 09-02 | 5 | **Fold into Evidence as a tab** — the one prior-decision (§C.3 of the 2026-09-05 UX analysis) still unimplemented |
| Manager | `/manager` | **0** | 09-09 | 2 | Keep as tab — too new to call rarely-used; it is an *island* (no links in or out). See §2. |
| Rules / Timeframes / Backtest | `/rules` `/timeframes` `/backtest` | 0 each | — | — | Already only reachable inside Evidence; retire the standalone routes' docs/tests that imply independence |
| `/ticker` `/institutions` `/consensus` `/report` | legacy redirects | 12 / 1 / 2 / 2 stale call sites | — | — | **Sweep the literals** to `/symbol` and `/filers`, keep redirects one release, then delete `RedirectToSymbol`/`RedirectToFilers` |
| Macro | `/macro` (6 sub-tabs) | 1 | 09-07 | 8 | Keep; measure which of Sentiment/Indicators/Rates/Oil/Movers/News are opened before collapsing any into "More" |
| Data | `/data` (6 sub-tabs, 4 owner-gated) | 0 | 09-07 | 2 | Keep top-level. Candidate: primary row Imports · Reconcile · Health; secondary "Maintenance" row Sectors · Inception · Users. **Defer until telemetry.** |
| Overview, Account, Paper Desk, Activity, Tax, `/strategy`, `/agents`, Research Desk, Agent Workflow, Personas, Symbol, Filers, Competition | — | — | — | — | Keep (load-bearing or section entry points; low inbound links are expected for entry points) |

Already implemented since the 2026-09-05 proposal (do not redo): `/strategy` + `/agents` landings, Evidence wrapper (Backtest/Timeframes/Rules), Research Desk toggle (Trading Agents/Vibe Trading), Competition Summary+Leaderboard merge + Review tab, `/personas/:slug`.

### 1.2 The "button inside a tab" pattern

For each demotion: (a) the child page renders inside the parent as a tab panel or behind a button in the parent's `Card` `actions` slot (§4); (b) the old route becomes `<Navigate to="/parent?tab=child" replace>` — the exact pattern `App.tsx` already uses for `/ticker` and `/consensus`; (c) the nav entry is removed; (d) `nav.page./child.*` keys are deleted, one new tab label key added (en+ko); (e) the child's test file is re-rooted under the parent shell (assertions unchanged where possible).

| Demotion | Parent surface | Route after | Files | Tests | i18n |
|---|---|---|---|---|---|
| Wash Sales → Tax | Tax gets a third tab "Wash sales" (Tax already tabs by year/section) | `/wash-sales` → `/tax?tab=wash` | `Tax.tsx`, `WashSales.tsx` (becomes a section component), `App.tsx`, `nav.ts` | `WashSales.test.tsx` re-root; `Tax.test.tsx` +1 | −2 nav keys, +1 tab key |
| Backfill → Personas | Personas header gets a "Backfill tasks" button opening the queue as a `Collapsible` panel below the grid | `/backfill` → `/personas?panel=backfill` | `Personas.tsx`, `BackfillTasks.tsx` (becomes a panel), `App.tsx`, `nav.ts` | `BackfillTasks.test.tsx` re-root; `Personas.test.tsx` +1 | −2, +1 |
| Thesis → Evidence | Evidence adds a fourth tab "Thesis" | `/thesis[/:symbol]` → `/evidence?tab=thesis&symbol=` | `Evidence.tsx`, `Thesis.tsx`, `App.tsx`, `nav.ts` | `Thesis.test.tsx` re-root; `Evidence.test.tsx` +1 | −2, +1 |

Caveat carried from the prior analysis: Thesis runs have permanent side effects (registration). Keep its own confirm step inside the tab; the tab move changes placement, not semantics.

### 1.3 Measure next time: local nav telemetry (tiny)

The backend only sees API calls, not SPA routes, so record navigations from the client:
- Frontend: a `useNavTelemetry()` hook on route change → `POST /api/telemetry/nav` `{path, tab?, ts}` batched (≤1 req / 10 s), fire-and-forget.
- Backend: `app/telemetry/nav.py` appends to `data/telemetry/nav.jsonl` (path, role, ts — no username); `GET /api/telemetry/nav/summary?days=30` (owner-only) → counts per route/tab.
- Surface: one small table in Data › Health ("Navigation, last 30 days").
- Setting `nav_telemetry_enabled` default **on** (local file only, no network). ~1 router, 1 hook, 1 panel, 3 tests.

---

## 2. Overview ↔ Manager

### 2.1 What actually overlaps

Both pages read the same six services in-process (`sources_owner.py` calls `portfolio_api._build_report()`, `tax_api._build()`, `paperdesk_desk.state()`… — the same functions the Overview endpoints run). The figures that appear on both: agent-layer up/down + reason (the one true duplicate — `Overview.tsx:831-835` vs `Manager.tsx:753-757`), cash, unpriced count, portfolio warnings, open wash windows + soonest safe date, YTD net gain, disallowed amounts, per-seat return, paper-desk staleness, Fear&Greed, macro day/week change, upcoming FOMC/earnings. Every pair except the first is **level (Overview) vs delta over the same source (Manager)** — the two pages doing their respective jobs.

Neither Attention panel can absorb the other: Manager's diff rules produce nothing without a previous snapshot (`rules.py:1089-1090`), it has no paper-desk staleness rule, and `wash_window_closing` fires only on the transition into the ≤3-day band. Overview alone can say "42 windows are open right now"; Manager alone can say "MU's window closes in 2 days (it didn't yesterday)". The merge that looks cleanest loses data.

### 2.2 Options

| | A — contract split + bridge (**recommended**) | B — merge Manager into Overview as tabs | C — Overview absorbs the deterministic change feed; Manager keeps the model layer |
|---|---|---|---|
| Pages | 2 (unchanged) | 1 | 2, Manager becomes model-only |
| Moves | none; add links both ways; retitle Manager §6 "Needs a look — new since {since}" | all of Manager → tabs Today/Changed/Brief/Chat; `/manager` redirects | `ChangesView`+`AttentionRow`+`AreaPanel`+window toggle → new owner-gated Overview section; Overview's 3 standing rows merge into that list as `attention` items |
| i18n keys touched | ≈6 | ≈6 (+102 change owning page) | ≈49 |
| Tests touched | ≈6 (`Overview.test.tsx` attention block + `Manager.test.tsx` attention block) | ≈55+ (both suites re-root; `App.test.tsx`, `i18n.test.tsx`) | ≈18 (backend `test_manager_*` untouched) |
| Risk | low | **high — rejected**: puts model-written synthesis, chat and money-spending Approve buttons on the member-visible landing page; the separate route *is* part of the structural not-advice boundary (`MANAGER-DESK-PLAN.md:20-26`); 3 of 4 tabs 403 for members; +4 fetches + a 2 s poll on a page that already fires 11 | medium: Overview gains a hard dependency on an owner-only endpoint and on snapshots existing (must render empty-and-explained for a member and on day one); dense rows beside tile rhythm; `/manager` collapses in value when the model is down — the opposite of what `Manager.tsx:5-11` was built for |

Recommendation: **A now; C only if the owner wants one fewer daily destination and accepts the day-one/member empty state.**

### 2.3 Must-fix defects surfaced (do regardless of option)

1. **`/manager` is not owner-gated in the UI** while its whole API is owner-only: not in `OWNER_ONLY_NAV_PATHS` (`nav.ts:224`), no `OwnerGate` (`App.tsx:132`), but `/api/manager` is in `OWNER_ONLY_PREFIXES` (`gate.py:59`). A member sees the tab and gets a page of 403 callouts. Add to both, matching `/portfolio`, `/tax`, `/wash-sales`, `/activity`.
2. **Two areas can never render**: `news` and `activity` are in `AREA_ORDER` (`Manager.tsx:98,101`) and the `Area` union (`models.py:73-76`) but have no rule in `rules.py:1014-1057`. Add rules or drop them from the render order.
3. Cross-link the pages (zero links exist today) and rename Manager's "Attention" so two panels in one app don't share a heading for two different questions.

---

## 3. Phone notifications

### 3.1 Constraints (from the real tool contracts and the code)

- `PushNotification` (Claude Code) reaches the **phone only while Remote Control is connected**; otherwise it is a desktop notification, and it is skipped if you are at the terminal. It only fires from a running Claude session.
- Claude **scheduled tasks** run locally (they can reach `localhost`; a cloud routine cannot), each as a fresh self-contained run, **only while the desktop app is open** (missed runs fire on next launch). One already exists and works here (`fomc-schedule-refresh`).
- In the app: the Manager feed is the unified event source (27 rules, `severity ∈ {attention,notable,fyi}`, id `{rule}:{area}:{item_id}`) but is **daily, snapshot-diff, no `since=` cursor**. Paper-desk fills are **recomputed, never persisted** (only the workflow/autopilot ledger keeps `filled_at`). Two append-only logs exist: `promotions.jsonl`, `data/agentdesk/live_decisions/*.jsonl`. **No outbound channel exists.** Auth is session-cookie only; `/api/manager` is owner-only.

Consequence: anything "instant" (a fill, a signal) must be pushed **by the backend itself** to a phone service, or it depends on the desktop app being open. Claude is the right *composer* for the daily digest, not the right *transport* for intraday alerts.

### 3.2 Architecture — three layers

**Layer 1 — event log** (`backend/app/notify/`)
- `events.py`: `NotifyEvent{id, ts, kind, severity, title, body, refs[], source}` appended to `data/notify/events.jsonl`; `seen.json` dedupe set keyed by `id`. `GET /api/notify/events?since=<id|ts>&limit=` (owner), `GET /api/notify/status`, `POST /api/notify/test`.
- `hooks.py` adapters (each a few lines at the producer):
  | Source | Hook point | Event kind | Default severity |
  |---|---|---|---|
  | Manager change feed | after `POST /api/manager/snapshot` / scheduled brief: emit each `ChangeItem` (reuse its id) | `manager.change` | as the rule says |
  | Daily brief | `run_manager_brief` completion: `Brief.attention` bullets | `manager.brief` | attention |
  | Workflow/autopilot fills | `workflow.book.execute_pending` when status→filled/rejected | `paper.fill` | notable |
  | Rule-desk fills | **needs a fill journal**: on `paperdesk.refresh` diff holdings vs last refresh, persist deltas to `data/paperdesk/fills.jsonl` | `paper.fill` | notable |
  | Live decisions | `live_loop.decide` when stance ∈ {buy, sell} | `signal.live` | attention |
  | Evolution promotions | `promotion` writer | `research.promotion` | notable |
  | Persona notes | `VaultStore.save_note` (new `note_id`) | `persona.note` | fyi |
  | Data freshness | periodic check (piggyback the livefeed tick) on transition fresh→stale | `data.stale` | notable |

**Layer 2 — sender** (`backend/app/notify/sender.py`)
- Channel protocol `send(event) -> bool`; implementations: `ntfy` (one HTTP POST; free phone app; works with the desktop app closed), `pushover`, `telegram`, `log` (dry-run). Policy: `min_severity`, quiet hours (ET), rate cap/hour, 60 s batch window collapsing same-kind events, retry with backoff.
- Settings (all default **off**, matching "money-spending daemons default off"): `notify_enabled`, `notify_channel`, `notify_ntfy_url`, `notify_ntfy_topic`, `notify_min_severity=notable`, `notify_quiet_hours=22:00-07:00`, `notify_kinds` allowlist.
- Auth for a poller: `notify_service_token` bearer accepted by `app.auth.gate` for a **read-only allowlist** (`/api/notify/*`, `/api/manager/changes`, `/api/manager/briefs/latest`), owner-scoped. Keeps the cookie model intact for humans.

**Layer 3 — Claude digest** (scheduled task, local)
- `invdash-morning-digest`, weekdays 09:55 ET (10 min after the 09:45 manager brief): read `briefs/latest` + `notify/events?since=yesterday` with the service token; compose ≤200 chars, lead with what to act on; call `PushNotification` (phone if Remote Control) **and** `POST /api/notify/test`-style send through the same ntfy channel so delivery does not depend on Remote Control. Self-contained prompt, no memory of this conversation.
- Optional: an on-demand "what changed" task and a Friday weekly digest.

### 3.3 Delivery options compared

| Channel | Instant intraday | Works with desktop app closed | Setup | Cost | Verdict |
|---|---|---|---|---|---|
| **ntfy** (ntfy.sh or self-hosted) | yes | yes | install app, pick a private topic | free | **first** |
| Pushover | yes | yes | app + API token | one-time $5 | alt |
| Telegram bot | yes | yes | bot token + chat id | free | alt (richer formatting) |
| `PushNotification` via scheduled task | no (task cadence) | no | none | included | digest layer only; needs Remote Control for phone |
| Cloud routine | — | cannot reach `localhost` | — | — | not viable unless the API is exposed |

### 3.4 Phases

1. Event log + `since` endpoint + `log` channel + service token + Manager/brief hooks (+ tests: dedupe, since-cursor, gate allowlist).
2. `ntfy` channel + policy (min severity, quiet hours, batching) + `POST /api/notify/test` + Data › Health status row.
3. Intraday hooks: workflow fills, live decisions, promotions, persona notes, freshness flips. Fill journal for rule desks (owner decision §6.5).
4. Claude digest scheduled task + runbook (`docs/NOTIFY-RUNBOOK.md`).

---

## 4. Aligned cards ("fixed size on top of an expandable tab")

### 4.1 What exists

`ScrollRegion` (96 sites; `sm` 256 px, `md` clamp(320px,55vh,640px), `lg` clamp(400px,75vh,900px)) — **caps only** (`max-height`), never a height. `ScrollPanel` (10 sites) is the only expand affordance. `Collapsible` (7 sites; on `beta` already composed over `ScrollRegion` in `LoopPanel`/`GenerationsPanel` — literally "expandable tab over a bounded body"). No `Card`, `.card` or `.grid` exists; `.panel` (309 sites) carries `margin-bottom:1rem` that also applies inside grid cells (rows double-gap). `.scroll-region` has `flex:1` nowhere; `grid-auto-rows` appears nowhere.

Misaligned grids (all `file:line` verified): Overview's three rows (`Overview.css:73-77` `align-items:start`, documented as deliberate), Manager `.mgr-area-grid` (boxes stretch, bodies don't fill), Paper Desk `.desk-grid` (worst: a card = sum of up to six sibling scroll regions + unbounded blocks, kind-dependent content, per-card `<details>` growth), `.desk-upcoming-grid` (no bounding at all), AfterTax table (unbounded, full-width below a ⅓-width desk), Personas grids, Institutions/Timeframes drilldowns, `TimeframeGrid` placeholder branches. Already correct (reference, don't migrate): `StrategyLanding` `.sl-cards`, `AgentDeskLanding` `.adl-cards`, `LiveTape` grid inside one `ScrollRegion`.

Latent defect to browser-verify: `.scroll-region table thead th {position:sticky}` cannot work at the 31 sites that nest `.table-wrap` between the region and the table (sticky resolves against the nearest scrollport = the unbounded `.table-wrap`).

### 4.2 The `Card` contract (composition, not replacement)

```tsx
<Card title={<h3 …/>} status={<StatusPill …/>} actions={…} height="md" label={t(…)}
      expandable expanded onExpandedChange footer={<InfoNote …/>}>…</Card>
<CardGrid height="md" min="320px">…</CardGrid>   // owns the token so cards can't disagree
```
- `Card` = `.panel` + fixed head (lifted from `ScrollPanel.tsx:161-179`) + `ScrollRegion` as a **filling** body + pinned foot. `ScrollPanel` becomes `Card height="auto"`; its 10 call sites keep working.
- CSS that makes "fixed" fixed: `.card-grid{display:grid; align-items:stretch; grid-auto-rows:var(--card-h)}`, `.card-grid > .panel{margin-bottom:0}`, `.card{display:flex;flex-direction:column;height:100%;min-height:0}`, `.card-head{flex:0 0 auto;min-height:1.9rem}` (so a card with a pill and one without keep the same body top edge), `.card-body{flex:1 1 auto;min-height:0;overflow:auto}` — **the missing declaration**, `.card-foot{flex:0 0 auto}`. Size classes reuse the ScrollRegion values verbatim.
- **Expansion: in place, full-row span, one at a time** (`.card.expanded{grid-column:1/-1;height:auto}`); state lives on the grid in `useUrlState` `?card=<id>` (shareable, clean URL by default). No modal — the app has no card-modal precedent and `Collapsible.tsx:1-27` argues for native in-place disclosure.
- The demoted tabs from §1.2 live in the parent card's `actions` slot — this is where "move tabs as buttons inside another tab" lands visually.
- A11y: keep `aria-expanded`/`aria-controls` wiring and `ui.scroll.expand/collapse`; **gate the tab stop** — `ScrollRegion` is `tabIndex={0}` unconditionally (`ScrollPanel.tsx:118`), so a 12-card grid is 12 tab stops; use `tabIndex={more || expanded ? 0 : -1}` (it already measures overflow). No height transition under `prefers-reduced-motion`. `.card-body` owns both axes; do not nest `.table-wrap` inside it (restores sticky headers).
- Document the split: `Collapsible` = "this section folds to a title"; `Card expandable` = "this fixed tile can grow in place". Don't nest one in the other.

### 4.3 Migration order

| Step | Target | Files | Tests | Note |
|---|---|---|---|---|
| 0 | `Card`, `CardGrid`, `ScrollPanel`→`Card height="auto"`, tabIndex gate | `components/Card.tsx|.css` (new), `ScrollPanel.tsx|.css` | new `Card.test.tsx`; `ScrollPanel.test.tsx:34` ("is a tab stop") changes | prerequisite |
| 1 | Manager `.mgr-area-grid` | `Manager.tsx:912-926`, `Manager.css:53-57` | `Manager.test.tsx` | ~15 lines; already stretch; gains the expand button it can't reach today |
| 2 | Overview (3 ragged rows) | `Overview.tsx:438,455,973,990-1039,1107,1192,1486`, `Overview.css:73-143` | `Overview.test.tsx` | landing page; also collapses Attention's two `sm` regions into one |
| 3 | Paper Desk `.desk-grid` + `.desk-upcoming-grid` + AfterTax table | `paperdesk/BookSection.tsx:351`, `DeskPanel.tsx:103-200,373`, `BookStatistics.tsx:35-90`, `PaperDesk.tsx:747`, `PaperDesk.css:64-77` | `PaperDesk.test.tsx` (23 `.desk-panel` + 9 `.desk-panel-title` selectors — keep both classes on the Card root), `DeskPanel.test.tsx`, `LiveTape.test.tsx` | biggest payoff and risk: six regions per card → one body + one `Collapsible` long form |
| 4 | Personas grids | `Personas.tsx:184,216`, `components/PersonaCard.tsx:93-117`, `Personas.css:19-38` | `Personas.test.tsx` | wrapper swap |
| 5 | Institutions + Timeframes drilldowns, `TimeframeGrid` placeholders (land on `beta` versions) | `Institutions.tsx:405`, `Timeframes.tsx:595`, `components/TimeframeGrid.tsx:28` + css | respective | two-column drilldowns |
| 6 | opportunistic: `.wf-book-grid`, `.ta-analyst-grid`, `.thesis-evidence-columns` | — | — | same shape, lower traffic |

Test caveat: jsdom performs no layout, so **equal height cannot be asserted in vitest**; tests assert the contract (head outside the region, exactly one `.scroll-region` per card, `aria-*` wiring, `.card-grid` present) and equal rendering is a browser smoke. i18n: zero new keys for the control; card copy is under the enforced 120-char budget.

---

## 5. Sequencing, parallelism, estimates

| Phase | Content | Depends on | Parallel with | Rough size |
|---|---|---|---|---|
| **P0 fixes** | `/manager` owner gate; dead `news`/`activity` areas; Overview↔Manager cross-links + rename; legacy-link sweep; `ScrollRegion` tabIndex gate; nav telemetry | — | everything | 1 worker-day |
| **P1 cards core** | Card/CardGrid + Manager + Overview (§4.3 steps 0-2) | P0 tabIndex gate | P3 (file-disjoint: frontend components vs backend `notify/`) | 2 worker-days |
| **P2 nav demotions** | Wash Sales→Tax, Backfill→Personas, Thesis→Evidence, redirects, tests, i18n | — | P1 (touches Tax/Personas/Evidence, not Manager/Overview) | 1.5 worker-days |
| **P3 notify** | §3.4 phases 1-3 (log, token, ntfy, hooks, fill journal) | owner decisions §6.3-6.5 | P1, P2 | 3 worker-days |
| **P4 cards rest** | Paper Desk, Personas, drilldowns (§4.3 steps 3-6) | P1 | P3 | 3 worker-days |
| **P5 digest** | Claude scheduled task + runbook | P3 | — | 0.5 |

Gates per phase (from `pytest-green-is-not-gate-green`): backend `pytest` + `ruff` + `mypy` (from `backend/`), frontend `vitest` + `tsc` + `proseBudget`, pre-commit PII gate, and a browser smoke for P1/P4 (jsdom can't see height). Run the frontend suite with `--testTimeout=30000` to separate load flakiness from real failures.

---

## 6. Owner decisions needed before building

1. **Demotions** — approve Wash Sales→Tax tab, Backfill→Personas button, Thesis→Evidence tab? (rec: all three)
2. **Overview↔Manager** — Option A (rec) or C?
3. **Notification channel** — ntfy (rec) / Pushover / Telegram? Self-hosted ntfy or ntfy.sh with a private topic?
4. **What notifies, at what severity** — default proposal: `attention`+`notable` push; `fyi` digest-only; live decisions only for buy/sell; quiet hours 22:00-07:00 ET.
5. **Rule-desk fills** — add the fill journal (rec; only way to notify per fill) or workflow-ledger fills only?
6. **Claude digest** — on (weekdays 09:55 ET) or off? Accept that phone delivery of the *Claude* push needs Remote Control; the ntfy copy does not.
7. **Card expansion** — in-place full-row (rec) vs modal.
8. **Nav telemetry** — ok to log route hits to a local file (no username)? (rec: yes)
9. **Data tab split** (primary/maintenance) — defer until 30 days of telemetry (rec) or do now?
