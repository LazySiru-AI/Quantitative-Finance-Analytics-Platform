# UI density plan: bounded cards, concise copy, colour encoding

Status: **PLAN — awaiting owner go-ahead. No code changed.**
Date: 2026-09-02

## 0. What was measured

Live app, English, 720px-tall viewport, 2026-09-02:

| Finding | Evidence |
|---|---|
| Persona profile cards are 9,100px and 19,625px tall; the Personas page is 81,094px | `offsetHeight` of `.panel.persona-profile`; `document.scrollHeight` |
| Paper Desk page is 5.8 screens tall (4,150px) before any desk is expanded | `document.scrollHeight` |
| Tax disposals table renders every row in one unbounded `.table-wrap` | `pages/Tax.tsx:425`; `.table-wrap` is `overflow-x: auto` only (`styles.css:218`) |
| **No shared bounded-card primitive exists.** 8 places hand-roll their own `max-height` + `overflow-y` (Competition ×4, EventCalendar, AgentWorkflow, TradingAgents, VibeTrading); everything else — including the Persona profile — is unbounded | `Personas.css` has zero `overflow-y`/`max-height` rules |
| 349 of 2,537 i18n keys (14%) are prose ≥ 80 chars or multi-sentence: **~62,000 English characters** of on-screen explanation, plus the Korean twins | `i18n/messages/*.ts` scan |
| Longest single strings: 568c (`portfolio.positionsView.note`), 564c (`tax.uncertainBasis.fixIt`), 501c, 463c, 458c (`paperDesk.framingNote`) | same scan |
| Duplicated explanations: 13F disclaimer ×2 (Institutions 349c / Consensus 307c), Tax↔WashSales "Scope:" sentences that cross-reference each other, three near-identical Trading-Agents analyst paragraphs, `paperDesk.subtitle_one/_other` at ~260c each | same scan |
| Only tooltip mechanism is the native `title=` attribute (~110 sites) — invisible on touch, unreachable by keyboard | grep |
| No shared `Badge`/`Pill`/`Legend` React component; ~40 page-prefixed badge CSS classes reimplement the same 6 tones | `styles.css:196-215,1032-1052`, page CSS |
| Two undefined tokens silently fall back to hard-coded greys: `--text-muted` (Competition.css seats block) and `--surface-2` (PaperDesk.css dormant badge) — the real tokens are `--muted` / `--panel-2` | grep for definitions: none |

House rules that the plan must keep (quoted from the stylesheet's own comments):
- *"Colour is never the only signal"* — every tone pairs with a text label; neutral/unknown uses dashed border + italic.
- Monospace-uppercase-letterspaced is the label voice; explanatory prose stays in the sans stack.
- Native `<details>` over hand-rolled ARIA (`Collapsible.tsx` docstring).
- Tax and Institutions pages carry legally relevant caveats ("calculation, not tax advice"; 13F lag) — those must stay **visible**, only shorter.

## 1. Part A — bounded, scrollable cards

### A1. One primitive, `ScrollPanel` (new `components/ScrollPanel.tsx` + rules in `styles.css`)

```tsx
<ScrollPanel
  title={<h2 className="section-heading">…</h2>}   // stays fixed above the scroll region
  actions={<…badges / filters…>}                    // optional, also fixed
  size="md"                                         // "sm" | "md" | "lg"
  expandable                                        // shows ⤢ Expand / ⤡ Collapse (EventCalendar's existing pattern)
  label={t("…")}                                    // aria-label for the scroll region
  className="persona-profile"
>
  …long content…
</ScrollPanel>
```

CSS (single source, no per-page copies):

| Size | `max-height` | Intended for |
|---|---|---|
| `sm` | `16rem` | logs, stage output, recent-activity lists |
| `md` | `clamp(320px, 55vh, 640px)` | tables and lists (holdings, disposals, fills, runs) |
| `lg` | `clamp(400px, 75vh, 900px)` | profile / dossier cards (Persona profile, Candidate dossier) |

- Body: `overflow-y: auto; min-height: 0; overscroll-behavior: contain; scrollbar-gutter: stable; scrollbar-color` themed to `--border-strong`/`--panel`.
- Bottom edge fade (`mask-image`) so a cut-off card reads as "more below", not "ends here".
- `thead th { position: sticky; top: 0 }` inside any `ScrollPanel` table — the Competition leaderboard already does this; it becomes free everywhere.
- Body is `tabIndex=0` + `role="region"` + `aria-label` so keyboard users can scroll it; no motion, nothing to reduce.
- `.expanded` → `max-height: none`. Expand state is component-local (no persistence).
- One scroll region per card. **No nested scrollers** — a sub-list inside a scrolling card does not get its own.

### A2. Where it goes (priority by measured/likely height)

| Pri | Page | Container (file:line) | Size | Note |
|---|---|---|---|---|
| P0 | Personas | `.persona-profile` (`PersonaProfile.tsx:85`), `.persona-scorecard`, `.persona-card` | lg / md / md | 9k–20k px today |
| P0 | Paper Desk | `DeskPanel` holdings `:661`, staged orders `:436`, live fills `:537`; `BookStatistics` signals `:205`, decisions `:305`, trades `:371`; `LiveTape` grid `:219` | md | page = 5.8 screens |
| P0 | Tax | disposals `Tax.tsx:425`; warning list `:738`; wash-sale pairs `:1071`, boxes `:1174` | md | ~1,000+ rows |
| P0 | Wash Sales | per-symbol sales `:469`, symbol list `:265` | md | |
| P1 | Institutions | holdings `:658,1075`, deltas `:728` | md | 13F = hundreds of rows |
| P1 | Portfolio | positions `:860,868,1442,1450`, per-account `:1013,1307`, warnings `:716` | md | |
| P1 | Competition | gens standings `:611` (the one table that missed `comp-gens-scroll`), findings entry lists `:284,371`, dossier evidence `:244`, pending seats `:295-343`, agent trades/rejections `:163,195`, library `:105-526` | md | |
| P1 | Agent Workflow | recent runs `:819`, book positions/orders `:924,958`, candidate gates `:1199` | md / sm | |
| P1 | Trading Agents | runs `:654`, decision memory `:776` | md | memory grows forever |
| P1 | Report | decision rows `:465`, drawdown episodes `:385` | md | |
| P2 | Consensus unchecked `:242`, Overview desk table `:577`, Rules list `:127`, Activity import lists | md | small today |

### A3. Fold the 8 hand-rolled scrollers into the primitive (optional, recommended in the same pass)
`comp-leaderboard-scroll`, `comp-gens-scroll`, `comp-job-log`, `comp-gens-plan-text`, `wf-output-md`, `ta-stage-output`, `vibe-output-md`, `event-calendar-scroll` → `ScrollPanel` sizes. Pure refactor; each already has page tests.

## 2. Part B — concise copy + colour encoding

### B1. Copy rules (goes into `docs/COPY-STYLE.md`, enforced by a test)

| Slot | Budget | Voice |
|---|---|---|
| Page subtitle | ≤ 90 chars, one clause | "US cost basis, all accounts. Wash sales detected across brokers." |
| Card / section note | ≤ 120 chars | fragments allowed; never restate the label above it |
| Pill label | ≤ 3 words, mono-uppercase | `DORMANT`, `NOT TAX ADVICE`, `STALE 3D` |
| Tooltip / disclosure body | ≤ 240 chars | the *why*; only place full sentences are allowed |
| Empty state | ≤ 100 chars | what's missing + the one action |

- No cross-page cross-references in body text — link the page instead.
- One explanation per fact per app: 13F disclaimer, "Scope:", analyst explainers, subtitle plural forms each become one key.
- Korean is rewritten to the same budgets in the same edit (the `as const satisfies MessageShard` type already refuses a key with only `en`).
- Enforced by a new Vitest test scanning every shard: `en.length` over budget fails unless the key ends in `.more` (disclosure bodies). Ships with an allowlist that is emptied as pages are converted, so it can land before the rewrite finishes.

### B2. Three new small components (`components/`)

| Component | Replaces | Contract |
|---|---|---|
| `StatusPill` | ~40 ad-hoc `*-badge` classes | `tone: "ok" \| "warn" \| "bad" \| "info" \| "special" \| "neutral"` → `--up / --warn / --down / --accent / --accent-2 / --muted(dashed+italic)`; `label` (i18n key), optional `detail` (disclosure body). Absorbs the six-state `wf/vibe/ta-stage-*` vocabulary: pending→neutral, running→info, succeeded→ok, degraded→warn, failed→bad, blocked→special. |
| `InfoNote` | long `<p className="muted">` blocks and `title=` tooltips | `summary` (short line, always visible) + `children`/`more` (long form). Built on native `<details>` per house rule — keyboard + touch reachable, unlike `title=`. Renders as `ⓘ short line ▸`. |
| `PillLegend` | nothing (none exists) | one compact mono line per page listing the tones in use; only rendered where ≥ 2 tones appear. |

Token fix bundled here: replace `var(--text-muted, …)` → `var(--muted)`, `var(--surface-2, …)` → `var(--panel-2)` in `Competition.css` and `PaperDesk.css`.

### B3. Target voice — before → after (illustrative; final strings written per page)

| Now | After |
|---|---|
| `paperDesk.framingNote` (458c): "Each desk is an independent reference strategy on its own simulated capital -- not a combined portfolio. No total across desks, and no total across books, is a suggested allocation…" | Note: **"Each desk: own capital, own rules. Not a portfolio — book totals are not comparable."** + ⓘ (long form) |
| `tax.disclaimer.*` bold paragraph | Pill `NOT TAX ADVICE` (warn) + **"Calculation only. Reconcile every figure with your 1099-B before filing."** — stays visible, 70 chars |
| `tax.uncertainBasis.fixIt` (564c) red callout | Callout: **"N of M disposals: basis unknown, booked at $0 → gain shown is an upper bound."** + ⓘ "Fix: add `cost_basis` under `[[opening_position]]` in `data/accounts.toml`." |
| Agent Workflow 6-step `<ol>` explainer | Stepper chips: `REGIME → CARD → CANDIDATES → RESEARCH → PLAN → 4 BOOKS`, each chip's ⓘ holds its sentence |
| `paperDesk.dormant.rulesDeskNote` prose | Pill `DORMANT` (warn) + **"Entry rule never fired since inception."** |
| Institutions + Consensus 13F disclaimers (656c total) | One `market.thirteenF.caveat` key: Pill `13F · 45-DAY LAG` (warn) + **"US equities only, as of quarter end."** + ⓘ |
| `desk.markBehind`: "The mark is {days} days behind -- treat every figure on this page as that many days stale." | Pill `STALE {days}D` (warn) — the pill *is* the sentence |
| Live-tape intro: "Only symbols currently held, signalling this session, or traded in the most recent session -- not the full universe of every desk below." | **"Held · signalling · traded last session. Not the full universe."** (the three filter checkboxes already say it) |

### B4. Rewrite order (by prose volume × visits)

1. Tax + Wash Sales (9.1k chars, legal caveats — done first and reviewed most carefully)
2. Paper Desk (6.5k) + Overview reference-desk strings
3. Competition, all tabs (7.5k)
4. Portfolio + Activity (9.0k)
5. Institutions + Consensus + Ticker (8.0k, dedupe 13F)
6. Thesis + Backtest + Rules + Timeframes (`strategy.ts`, 8.3k)
7. Agent Desk trio + Agent Workflow + Personas + Macro + Report (5.0k)

## 3. Execution shape (for `/distWork` when approved)

| Phase | Who | Content | Gate |
|---|---|---|---|
| 0 | orchestrator alone (sequenced — workers must not invent the contracts) | `ScrollPanel`, `StatusPill`, `InfoNote`, `PillLegend`, `styles.css` rules, prose-budget test with full allowlist, `docs/COPY-STYLE.md`, token fix | `tsc`, `vitest` for the 4 components |
| 1 | 6 parallel Sonnet workers, file-disjoint by page dir | apply `ScrollPanel` per §A2/A3: (1) Personas, (2) `pages/paperdesk/*`, (3) Tax + WashSales, (4) `pages/competition/*` + Competition.css, (5) Institutions + Portfolio + Consensus, (6) AgentWorkflow + TradingAgents + VibeTrading + Report + EventCalendar | each: `tsc`, its page test file, and a browser height probe (`offsetHeight ≤ max`, `scrollHeight > offsetHeight`) |
| 2 | 7 parallel Sonnet workers, one per row of §B4; a worker owns its message file(s) **and** the pages that read them (`misc.ts`, `market.ts`, `strategy.ts` are shared — each is assigned whole to one worker) | rewrite en+ko to budget, swap prose for `StatusPill`/`InfoNote`, shrink the allowlist | `tsc`, page tests, prose-budget test |
| 3 | orchestrator + 1 QA worker | full `vitest`, `tsc`, `eslint`; screenshot every page EN and KO; re-measure the §0 heights; commit per phase with `git commit --only` (shared dirty tree — see memory) | allowlist empty; no page > 3 screens on default tab |

Size: Phase 0 ≈ one session; Phase 1 ≈ 6 workers, Phase 2 ≈ 7 workers (349 strings × 2 languages is the bulk), Phase 3 ≈ half a session.

## 4. Risks

- **Korean quality.** Workers can write budget-length Korean, but native tone should be spot-checked by the owner on Tax and Paper Desk before the rest is rolled.
- **Concurrent sessions.** The personas and i18n sessions have edited `frontend/src` in this tree within the last day. Every phase starts with `git status`, and commits use `--only`.
- **Hidden caveats.** Moving a caveat into ⓘ makes it *findable*, not *seen*. Legally relevant ones (tax, 13F lag, in-sample) keep a visible short form + pill; the plan never hides those fully.
- **Tests that assert on prose.** Page tests that match full sentences (`getByText("…")`) break on rewrite; workers update the assertion to the new short string, never delete the test.

## 5. Decisions needed from the owner

1. Default card height: `clamp(320px, 55vh, 640px)` with an Expand toggle (recommended), or a fixed rem?
2. Long explanations: move behind ⓘ disclosure (recommended) vs delete outright vs move to a docs page.
3. Korean rewritten in the same pass (recommended — the type system requires *a* ko string anyway; the question is quality).
4. Fold the 8 existing hand-rolled scrollers into `ScrollPanel` now (recommended) or leave them.
