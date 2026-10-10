# Korean / English Language Toggle — Implementation Plan

Status: **planned 2026-09-01, not started.** Execution begins on the owner's go.

## What it is

A persistent **EN / 한국어** toggle in the sidebar. Selecting 한국어 renders every piece of UI text the
frontend owns in Korean: navigation, page titles, table headers, buttons, tooltips, empty states,
error copy, and the deterministic sentences the frontend composes around numbers. The choice is
remembered across reloads and tabs. English stays the default, so the existing test suite (909
text assertions) keeps passing unchanged.

Text that the **backend** produces (model-written narratives, gate verdict sentences, API error
details) is a separate problem with its own phase and its own owner decision; see "Backend-origin
text" below.

## What was measured (2026-09-01)

| Surface | Count | Where |
|---|---|---|
| JSX text nodes with English words | ~950 | 120 non-test `.tsx` files |
| Template literals with English (`${n} bars ago`) | ~405 | same files |
| Attribute strings (`title=`, `placeholder=`, `aria-label=`) | ~90 | same files |
| Multi-word literals in `.ts` helpers (nav labels/blurbs, formatters, status maps) | ~75 | `nav.ts`, `api/*.ts`, `hooks/*.ts` |
| Existing label maps (`X_LABELS`, `Record<Status, string>`) | 36 | mixed |
| Singular/plural ternaries (`=== 1 ? "bar" : "bars"`) | 12 | mixed |
| Test assertions on English text (`getByText` etc.) | 909 | `*.test.tsx` |
| Backend free-text fields rendered verbatim (`{x.reason}`, `{x.narrative}` …) | 76 sites | 20 files |
| Existing i18n, locale, or `lang` handling | none | `index.html` is `lang="en"`; `formatPrice` is pinned to `en-US` |

Roughly **1,500 strings** move into a dictionary. The largest single files are `Portfolio.tsx`
(1,776 lines), `Tax.tsx`, `AgentWorkflow.tsx`, `Institutions.tsx`, and the `competition/` and
`paperdesk/` folders.

## Design decisions

| Decision | Choice | Why |
|---|---|---|
| Library | **None.** A ~150-line `src/i18n/` module modeled on `favorites.ts` (`useSyncExternalStore`, versioned `localStorage` key, cross-tab `storage` event) | Two locales, four runtime deps today, and the favourites store is already the house pattern for "one preference, read everywhere, agree instantly". `react-i18next` adds two deps, an init/Suspense step, and a runtime-only missing-key check we can do better at compile time. |
| Key style | **Structured ids**, not English-as-key: `t("nav.favorites.add", { label })` | English-as-key breaks the moment English copy is edited, and it cannot be type-checked. |
| Completeness | `en.ts` is canonical; `ko.ts` is typed `Record<MessageKey, string>` via `satisfies` | **`tsc` fails when a Korean string is missing.** CI already runs `tsc --noEmit`, so completeness is a gate, not a hope. |
| Interpolation | `{name}` placeholders; `t(key, params)`. Plurals via `_one` / `_other` key pairs; `ko` supplies only `_other` | Korean word order differs from English, so callers must never concatenate `<strong>{n}</strong> bars evaluated`. A `<Trans>` helper renders a translated string with a rich placeholder for the handful of sites that embed markup. |
| Persistence | `investing-dashboard.language.v1` in `localStorage`; default `en`; first visit does **not** sniff `navigator.language` | Mirrors favourites. Auto-detection would flip a dev machine set to Korean into Korean for the existing tests' authors; an explicit toggle is the request. |
| `<html lang>` | Set `document.documentElement.lang` from the store | Screen readers, hyphenation and font selection all key off it. |
| Fonts | Append Korean fallbacks to `--font-sans` (`"Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR"`) and `--font-mono` (`"D2Coding", "Nanum Gothic Coding"`) | The current stacks have no Hangul glyphs; the browser would fall back to whatever system font it finds, breaking the monospace tables. |
| Numbers and currency | **Unchanged** (`en-US`, USD) | Korean uses the same digit grouping; `ko-KR` currency rendering prints `US$` and breaks tabular alignment. The account is in USD. |
| Dates | Locale-aware: the existing `formatObservationDate` / calendar formatters take the active locale instead of `undefined` | `2026. 9. 1.` is what a Korean reader expects; the code already routes every date through three helpers, so this is a small change. |
| Toggle placement | Sidebar, directly under the brand line, as a two-segment button (`EN` / `한국어`) with `aria-pressed` | Visible on every page, never scrolls away. It sits **outside `.nav`** because `App.test.tsx` counts `.nav` links and page-rail buttons. |
| Tickers, model ids, form numbers, rule expressions | Never translated | `SPY`, `RSI(14)`, `Form 8949`, `mom12_1_hysteresis` are identifiers. |

## Module shape

```
frontend/src/i18n/
  store.ts     language store (read, set, subscribe, useLanguage hook), localStorage + storage event
  en.ts        export const en = { "nav.section.overview": "Overview", ... } as const
  ko.ts        export const ko = { ... } satisfies Record<MessageKey, string>
  t.ts         t(key, params?) with {placeholder} substitution and _one/_other selection
  useT.ts      React hook: subscribes to the store, returns a bound t and the locale
  Trans.tsx    renders a message whose placeholder is a React node
  index.ts     public surface
frontend/src/components/LanguageToggle.tsx
```

Non-React helpers in `api/*.ts` (formatters, status labels) call `t()` directly; it reads the store
synchronously, and components re-render on change because every consumer subscribes through
`useT()`. A formatter's output is therefore always current for the render that asked for it.

Key naming: `<area>.<thing>.<detail>` in lower camel, area = page or component file stem
(`portfolio.holdings.header.symbol`, `paperDesk.book.empty`, `common.loading`). Shared strings live
under `common.*`. This convention is fixed **before** any parallel work starts; see "How it is built".

## Korean glossary (fix once, reuse everywhere)

The owner should review this table before Phase 1. Every parallel worker uses it verbatim.

| English | 한국어 | Note |
|---|---|---|
| Overview | 개요 | |
| Portfolio | 포트폴리오 | |
| Paper Desk | 페이퍼 데스크 | product name, transliterated |
| Activity | 거래 내역 | |
| Tax | 세금 | |
| Wash Sales | 워시 세일 | US tax term; keep transliteration, gloss on first use |
| Strategy Lab | 전략 실험실 | |
| Competition | 컴페티션 | leaderboard / rounds context |
| Backtest | 백테스트 | |
| Rules | 규칙 | |
| Timeframes | 타임프레임 | |
| Thesis | 투자 논거 | |
| Agent Desk | 에이전트 데스크 | |
| Trading Agents / Vibe Trading / Agent Workflow | 트레이딩 에이전트 / 바이브 트레이딩 / 에이전트 워크플로 | product names |
| Market | 시장 | |
| Ticker | 종목 | |
| Report | 리포트 | |
| Institutions | 기관 | 13F context |
| Consensus | 컨센서스 | |
| Macro | 매크로 | |
| Holdings | 보유 종목 | |
| Cash / Equity | 현금 / 자산 총액 | |
| Realised gain / loss | 실현 손익 | |
| Unrealised | 미실현 | |
| Drawdown | 낙폭 | 최대 낙폭 for max drawdown |
| CAGR | 연평균 성장률 (CAGR) | keep the acronym |
| Sharpe | 샤프 비율 | |
| Win rate | 승률 | |
| Fill / Filled / Pending / Rejected / Cancelled / Expired | 체결 / 체결됨 / 대기 / 거부됨 / 취소됨 / 만료됨 | order statuses |
| Buy / Sell | 매수 / 매도 | |
| Long / Short | 롱 / 숏 | |
| Regime | 국면 | |
| Signal | 신호 | |
| Evidence / Grounded / Ungrounded | 근거 / 근거 확인됨 / 근거 없음 | grounding gate |
| Round / Generation / Candidate / Promoted / Retired | 라운드 / 세대 / 후보 / 승격 / 은퇴 | evolution loop |
| Favorites / Add to favorites / Remove from favorites | 즐겨찾기 / 즐겨찾기에 추가 / 즐겨찾기에서 제거 | |
| Loading… / Not found / Retry | 불러오는 중… / 찾을 수 없음 / 다시 시도 | |

## Backend-origin text

Three tiers, decided separately because they cost differently.

| Tier | Example | Plan |
|---|---|---|
| **A. Enum values** | `status: "filled"`, `kind: "ungrounded_number"`, `arm: "full_workflow"` (16 `Literal[...]` unions in the models) | Frontend label maps, translated in the dictionary. Included in Phases 1–2; zero backend change. |
| **B. Deterministic sentences** | gate verdict sentences (`phase_b_report.py`), tax reconcile reasons, rule validation explanations, `ApiRequestError` bodies | **Phase 3.** Add a `code` + `params` alongside the existing `message` on the most-visible response models; the frontend renders `code` through the dictionary and falls back to `message`. Backend keeps the English sentence, so logs, tests and the CLI are untouched. |
| **C. Model-written narrative** | Report narrative, Thesis text, round narrative, Trading Agents / Vibe Trading / Agent Workflow outputs | **Phase 4, owner decision.** Default for Phases 0–3: show as-is with a small `원문 (영어)` badge. |

Phase 4 options for tier C, with a recommendation:

1. **Generate in Korean** by passing a language to the prompts. Rejected as default: outputs are
   stored artifacts (ledgers, dossiers) so the two languages could not coexist, and the grounding
   gate's number extraction was tuned on English sentences and has already produced false rejections
   on tokens like `RSI(14)` and ISO dates. A Korean corpus would need that gate re-validated first.
2. **Translate on display** through `app.agents.client.call_structured` (Haiku), cached per
   `(artifact hash, locale)` in the agentdesk store, with a post-check that every number in the
   source appears in the translation (reusing the grounding extractor). **Recommended** if the owner
   wants tier C at all: the stored English artifact stays canonical and auditable, cost is bounded by
   the cache and a spend cap, and a failed number check falls back to English with the badge.
3. **Leave English.** Cheapest; the badge makes the boundary explicit.

## Phases

| Phase | Scope | Deliverable / gate |
|---|---|---|
| **0. Foundation** | `src/i18n/*`, `LanguageToggle`, fonts, `<html lang>`, extraction of `App.tsx`, `nav.ts`, `NotFound.tsx`, `ErrorBoundary`, `PanelBoundary`, `describeError` fallbacks. Store tests, toggle test, a `ko`-render test for the shell. | Toggle works on every page; sidebar fully Korean; `tsc` + `vitest` green; commit. |
| **1. High-traffic pages** | Overview, Portfolio, Paper Desk (+`paperdesk/*`), Activity, Ticker, Macro, and the shared components they use (`Chart`, `DecisionTable`, `StatGrid`, `Collapsible`, `NewsPanel`, `MacroNewsPanel`, `EventCalendar`, `FearGreed*`, `HoldingsPieChart`, `RecentMoves`, `Sparkline`). Tier A label maps on this path. Date formatters take the locale. | Each page renders in Korean with no English word outside the identifier allowlist (automated, see Testing). Commit per page group. |
| **2. Remaining pages** | Tax, Wash Sales, Competition (+`competition/*`), Backtest, Rules, Timeframes, Thesis, Report, Institutions, Consensus, Trading Agents, Vibe Trading, Agent Workflow, and their components (`ImportPanel`, `ReconcilePanel`, `RuleEditor`, `ScanTable`, `StrategyCard`, `ThesisCard`, `TrialLedger`, `EventStudy`, `DrawdownTable`, `IndicatorPicker`, `TimeframeGrid`). | Same gate. Whole app passes the no-English scan under `ko`. |
| **3. Backend tier B** | `code` + `params` on the top deterministic sentence sources, frontend dictionary entries, fallback to `message`. | Backend tests unchanged in intent; frontend renders Korean for coded messages. |
| **4. Backend tier C** (optional) | Cached on-display translation with number post-check, spend cap, badge fallback. | Only on owner go, with a cap. |

Phase 0 is sequential (it defines the contract). Phases 1 and 2 fan out.

## How it is built

- **Contract first, then fan out.** Phase 0 lands the `t()` signature, key convention, plural rule,
  `Trans` usage and the glossary in the repo before any worker starts. Two prior fan-outs in this
  repo shipped mismatched field names because each side guessed the interface.
- **Workers by file group**, one Sonnet subagent per page-plus-its-components, Opus orchestrating.
  Each worker: extracts strings into `en.ts` under its area prefix, adds `ko.ts` entries from the
  glossary, keeps every English string byte-identical so existing tests pass, and returns the diff
  as text. Only the orchestrator writes `en.ts`/`ko.ts` merges and commits, to avoid two workers
  editing the same dictionary file.
- **Dirty-tree rule.** As of this writing another session has uncommitted work in `Overview.tsx`,
  `PaperDesk.tsx`, `paperdesk/DeskPanel.tsx`, `paperdesk/BookStatistics.tsx`, `App.tsx`, `nav.ts`
  and `styles.css`. Phase 0 touches `App.tsx`, `nav.ts` and `styles.css`; Phase 1 touches the rest.
  Before starting, either that work is committed or those files are scheduled last. Do not extract
  strings from a file another session is mid-edit on.
- **Line endings.** Working-copy files are CRLF; edits preserve that.
- **QA per phase.** A separate QA pass renders each finished page under `ko` and tries to find
  English; it reports defects, the orchestrator fixes, then commit and report.

## Testing

- Existing 909 assertions run under the default `en` and stay untouched.
- `i18n/store.test.ts`: default, set, persist, malformed storage value, cross-tab `storage` event,
  `<html lang>` update.
- `App.test.tsx`: toggle present on every route, `aria-pressed` flips, sidebar text switches, page
  rail link count unchanged.
- **No-English scan** (the regression guard the dictionary cannot give): a vitest per page renders
  it under `ko` with the page's existing fixtures and asserts the DOM text contains no Latin word of
  four or more letters outside an allowlist (tickers, `RSI`, `MACD`, `USD`, `Form 8949`, model ids,
  rule expressions, URLs). This is what catches a hardcoded string that slipped past extraction.
- `tsc` enforces `ko` completeness; CI already runs it.
- Browser check on the dev server after Phases 0, 1 and 2: sidebar width at 200px with Korean
  labels, table header wrapping, monospace fallback rendering Hangul, `lang` attribute, persistence
  across reload.

## Out of scope

- Right-to-left, additional locales, locale-specific number or currency formats.
- Translating stored data (ledgers, dossiers, notes) or anything in `data/`.
- Backend logs, CLI output, Markdown reports under `docs/reports`.
- Translating third-party content (news headlines, filings, FRED series names).

## Owner decisions requested before "execute"

1. **Toggle placement:** sidebar under the brand line (default), or top-right of the content area.
2. **Backend tier C:** badge only (default), or the cached on-display translation in Phase 4.
3. **Glossary:** any term above to change before it is applied ~1,500 times.
4. **Dirty tree:** commit the other session's Paper Desk / Overview work first, or have this plan
   schedule those files last.

---

## Completion status (2026-09-02)

All phases are implemented and committed on branch `strategy-program`.

| Phase | Status | Commit(s) |
|---|---|---|
| 0 — Foundation (store, catalog, toggle, boundaries, 404, fonts) | Done | `84fde46` |
| 1 — High-traffic pages | Done | `84fde46` |
| 2 — Remaining pages + shell wiring + nav + Personas | Done | `84fde46`, `96cda54`, `807eb64` |
| 3 — Backend deterministic sentences (code+params) | Done for feasible scope | `e9112ac` |
| 4 — On-display narrative translation (flag-gated) | Mechanism complete | `6bd7226` |

**The whole interactive UI renders in Korean** via the sidebar EN/한국어 toggle: every page,
component, table header, button, tooltip, empty/loading/error state, the navigation, and the
Personas profile/scorecard. `tsc` gates Korean completeness; the full frontend suite is 958 green.

**Phase 3 — what "feasible scope" means.** The one genuinely enumerable deterministic-sentence
cluster, the 1099-B reconciliation notes, is coded (`code`+`params`, English fallback). The other
candidates named in the original plan turned out not to be message-code material:
- Rule-parser errors, import/manifest errors, and reconcile-adjacent diagnostics are **free-form**
  (arbitrary interpolated paths, tokens, exception text) — English by nature, not enumerable.
- Enum-valued statuses/kinds are **tier A** and were translated as frontend label maps by the page
  work, wherever they are displayed.
- Workflow gate `verdict_detail` is **Markdown-report prose**, not a discrete live-UI sentence, so it
  falls under Phase 4, not Phase 3.

**Phase 4 — mechanism complete, default off.** `POST /api/i18n/translate` translates model prose to
Korean on display behind `INVDASH_TRANSLATE_NARRATIVES` (default false), Haiku via `call_structured`,
per-request budget cap, a number-preservation gate (rejects any translation that drops a source
number), and a per-locale file cache. The frontend `TranslatedProse` renders the translation with a
"기계 번역" badge or the English original with the "원문 (영어)" badge; it is wired into
`NarrativeSection` (the Report narrative). To enable everywhere: set `INVDASH_TRANSLATE_NARRATIVES=1`.

**Adoption path for the remaining prose surfaces.** `TranslatedProse` is exported from `@/i18n` and
ready for other model-prose surfaces to adopt (`PersonaCard` headline, `ThesisCard` hypothesis/
rationale, round narratives, dossier prose). Two caveats guided leaving them for a follow-up: their
current English-origin badges are always-on and coupled to existing tests, and the Agent Desk
Markdown blocks (`final_md`/`output_md`/`decision_md`) should not be machine-translated as raw text
without a Markdown-aware step, or the syntax can be mangled. Free-form backend **diagnostics**
(`InstitutionalHolders`/`Consensus` unchecked-filer reasons, import errors) are intentionally NOT
translation candidates and stay English with the origin badge.
