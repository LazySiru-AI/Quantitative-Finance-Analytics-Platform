/**
 * Agent Workflow page and its workflow API helper.
 *
 * Keys are prefixed `agentWorkflow.` -- see `catalog.ts` for the convention and why the prefix is
 * load-bearing (the duplicate-key guard in `i18n.test.tsx` keys off it).
 *
 * `api/workflow.ts` carries no hardcoded UI strings of its own -- it is types, doc comments and a
 * thin `requestJson` wrapper with no user-facing text -- so every key below belongs to
 * `AgentWorkflow.tsx`.
 *
 * A handful of values are left identical in both languages on purpose: `agentWorkflow.universe.*`
 * feed both the toggle buttons and `universeSourceLabel`'s badge text, and
 * `agentWorkflow.runForm.screenEntryRulePlaceholder` is a rules-DSL example
 * (`close > sma(200) and ema(20) > ema(50)`), not English prose -- translating its keywords would
 * turn it into invalid syntax, exactly like a formula or a ticker.
 *
 * Left untranslated by design, per the module's own "don't translate identifiers" rule and this
 * repo's `docs/closed-unions-over-server-data-kill-pages` lesson: arm ids (`book.arm`,
 * `metrics.arm`, `row.arm`), `order.status`/`order.fill.price_source` (the "filled"/"stored_open"
 * wire values -- `AgentWorkflow.test.tsx` asserts them verbatim), `row.gate`/`gate.gate`,
 * `obs.state`/`obs.regime`/`obs.agent_card_id`/`obs.skip_reason`, `gate.verdict_source`, and
 * `issue.kind` -- all server-supplied identifiers or enum values rendered as-is, not display
 * labels. `study.note`, `run.final_md`, `selectedStage.output_md`, `run.error`/`selectedStage.error`,
 * `gate.detail` and `obs.skip_detail` are backend/model-written free text (the directional-study
 * caveat, the entry-plan and stage narratives, gate verdict rationale) and stay English per the
 * "model-written prose" rule; a `common.sourceEnglish` badge sits next to the three block-level ones
 * (the study note, the entry plan, and a stage's output) where it reads cleanly -- the shorter
 * inline ones (gate tooltips, skip-detail tooltips) do not get a badge of their own.
 */
import type { MessageShard } from "@/i18n/types";

export const agentWorkflow = {
  // --- page header -----------------------------------------------------------
  "agentWorkflow.title": { en: "Agent Workflow", ko: "에이전트 워크플로" },
  "agentWorkflow.subtitle": {
    en: "Regime → strategy → research → plan → next-open execution, vs single-tool arms.",
    ko: "국면 → 전략 → 리서치 → 계획 → 다음 시가 실행, 단일 도구 그룹 대비 측정합니다.",
  },

  // --- view tabs (Run / Measure split, docs/STRATEGY-AGENT-UX-ANALYSIS.md §A5/C4) -----------------
  "agentWorkflow.tabs.run": { en: "Run", ko: "실행" },
  "agentWorkflow.tabs.measure": { en: "Measure", ko: "측정" },
  "agentWorkflow.tabs.ariaLabel": { en: "Agent Workflow view", ko: "에이전트 워크플로 보기" },

  // --- static explainer --------------------------------------------------------
  "agentWorkflow.explainer.heading": { en: "How this desk works", ko: "이 데스크의 작동 방식" },
  "agentWorkflow.explainer.summary": {
    en: "One staged run classifies the regime, researches candidates, and stages orders onto four measured books.",
    ko: "한 번의 실행이 국면을 분류하고 후보를 조사한 뒤, 측정용 북 네 개에 주문을 스테이징합니다.",
  },
  "agentWorkflow.explainer.step1": {
    en: "A regime call reads current market data and classifies the environment the run is trading into.",
    ko: "국면 판단은 현재 시장 데이터를 읽어 이 실행이 거래할 환경을 분류합니다.",
  },
  "agentWorkflow.explainer.step2": {
    en: "A strategy card is selected for that regime -- either the one you pick, or an auto-selected card that fits it.",
    ko: "해당 국면에 맞는 전략 카드가 선택됩니다 -- 직접 고른 카드이거나, 국면에 맞게 자동으로 선택된 카드입니다.",
  },
  "agentWorkflow.explainer.step3": {
    en: "The card scans for entry candidates: a short list of symbols worth researching further.",
    ko: "카드는 진입 후보를 스캔합니다: 추가로 조사할 가치가 있는 짧은 종목 목록입니다.",
  },
  "agentWorkflow.explainer.step4": {
    en: "Each candidate gets its own child Trading Agents run and Vibe Trading review, in parallel.",
    ko: "각 후보는 병렬로 자체 하위 Trading Agents 실행과 Vibe Trading 검토를 받습니다.",
  },
  "agentWorkflow.explainer.step5": {
    en: "An entry plan synthesises the research into orders, which stage onto the paper book at the next open.",
    ko: "진입 계획은 리서치를 주문으로 종합하며, 이 주문은 다음 시가에 페이퍼 북에 스테이징됩니다.",
  },
  "agentWorkflow.explainer.step6": {
    en: "The same plan stages onto four books at once -- raw, TA-gated, vibe-gated, full -- to measure each gate's value.",
    ko: "동일한 계획이 원시 신호, TA 게이트, Vibe 게이트, 전체 워크플로 네 개의 북에 동시에 스테이징되어, 스터디가 각 리서치 게이트가 실제로 도움이 되는지 측정할 수 있습니다.",
  },

  // --- errors (client-side fallback text; the API's own message wins when present) --------
  "agentWorkflow.errors.config": {
    en: "Could not load the workflow config.",
    ko: "워크플로 설정을 불러올 수 없습니다.",
  },
  "agentWorkflow.errors.recentRuns": {
    en: "Could not load recent runs.",
    ko: "최근 실행을 불러올 수 없습니다.",
  },
  "agentWorkflow.errors.startRun": {
    en: "Could not start the run.",
    ko: "실행을 시작할 수 없습니다.",
  },
  "agentWorkflow.errors.getRun": {
    en: "Could not load this run.",
    ko: "이 실행을 불러올 수 없습니다.",
  },
  "agentWorkflow.errors.books": {
    en: "Could not load the paper book.",
    ko: "페이퍼 북을 불러올 수 없습니다.",
  },
  "agentWorkflow.errors.execute": {
    en: "Could not execute the pending orders.",
    ko: "대기 주문을 실행할 수 없습니다.",
  },
  "agentWorkflow.errors.study": {
    en: "Could not load the effectiveness study.",
    ko: "효과성 스터디를 불러올 수 없습니다.",
  },
  "agentWorkflow.errors.candidates": {
    en: "Could not load candidates.",
    ko: "후보를 불러올 수 없습니다.",
  },

  // --- run configuration panel -------------------------------------------------
  "agentWorkflow.runConfig.heading": { en: "Run configuration", ko: "실행 설정" },
  "agentWorkflow.runConfig.loading": {
    en: "Loading configuration…",
    ko: "설정 불러오는 중…",
  },

  // --- run form fields -----------------------------------------------------------
  "agentWorkflow.runForm.strategyCard": { en: "Strategy card", ko: "전략 카드" },
  "agentWorkflow.runForm.autoSelect": {
    en: "Auto-select from regime",
    ko: "국면에서 자동 선택",
  },
  "agentWorkflow.runForm.maxResearchSymbols": {
    en: "Max research symbols",
    ko: "최대 리서치 종목 수",
  },
  "agentWorkflow.runForm.universe": { en: "Universe", ko: "유니버스" },
  "agentWorkflow.runForm.universeCardOption": {
    en: "Card (the strategy card's own universe)",
    ko: "카드 (전략 카드 자체의 유니버스)",
  },
  "agentWorkflow.runForm.universeScreenOption": {
    en: "Screened (a dynamic discovery-selector shortlist)",
    ko: "스크리닝 (동적 발굴 셀렉터 숏리스트)",
  },
  "agentWorkflow.runForm.weeklyBudget": {
    en: "Weekly research budget (USD)",
    ko: "주간 리서치 예산 (USD)",
  },
  "agentWorkflow.runForm.weeklyBudgetPlaceholder": {
    en: "100.00 (backend default)",
    ko: "100.00 (백엔드 기본값)",
  },
  "agentWorkflow.runForm.selector": { en: "Selector", ko: "셀렉터" },
  "agentWorkflow.runForm.rawSelectorOption": {
    en: "Raw pool + rank key",
    ko: "원시 풀 + 순위 키",
  },
  "agentWorkflow.runForm.candidatePool": { en: "Candidate pool", ko: "후보 풀" },
  "agentWorkflow.runForm.rankKey": { en: "Rank key", ko: "순위 키" },
  "agentWorkflow.runForm.screenTopN": {
    en: "Screen top N (optional)",
    ko: "스크리닝 상위 N (선택)",
  },
  "agentWorkflow.runForm.screenTopNPlaceholderDefault": {
    en: "backend default",
    ko: "백엔드 기본값",
  },
  "agentWorkflow.runForm.screenEntryRule": {
    en: "Screen entry rule (optional)",
    ko: "스크리닝 진입 규칙 (선택)",
  },
  // A rules-DSL example, not English prose -- kept identical in both languages, same treatment as a
  // formula or a ticker symbol. See the module docstring.
  "agentWorkflow.runForm.screenEntryRulePlaceholder": {
    en: "close > sma(200) and ema(20) > ema(50)",
    ko: "close > sma(200) and ema(20) > ema(50)",
  },
  "agentWorkflow.runForm.armsEnabled": { en: "Arms enabled", ko: "활성화된 그룹" },
  "agentWorkflow.runForm.agentUnavailable": {
    en: "Agent layer unavailable: {reason}",
    ko: "에이전트 계층을 사용할 수 없음: {reason}",
  },
  "agentWorkflow.runForm.starting": { en: "Starting…", ko: "시작하는 중…" },
  "agentWorkflow.runForm.startRun": { en: "Start run", ko: "실행 시작" },

  // --- run progress panel --------------------------------------------------------
  "agentWorkflow.run.heading": { en: "Run progress", ko: "실행 진행 상황" },
  "agentWorkflow.run.stateCostLine": {
    en: "State: {state} · Cost: {spent} / {cap} cap · {calls} calls",
    ko: "상태: {state} · 비용: {spent} / 상한 {cap} · 호출 {calls}회",
  },
  "agentWorkflow.run.layerLabel": { en: "Layer {layer}", ko: "레이어 {layer}" },
  "agentWorkflow.run.stageDetailLine": {
    en: "Seat: {seat} · State: {state} · Cost: {cost}",
    ko: "시트: {seat} · 상태: {state} · 비용: {cost}",
  },
  "agentWorkflow.run.groundingDegraded": { en: "Grounding degraded", ko: "근거 확인 저하" },
  "agentWorkflow.run.noOutputYet": { en: "(no output yet)", ko: "(아직 출력 없음)" },
  "agentWorkflow.run.entryPlan": { en: "Entry plan", ko: "진입 계획" },

  // --- stage states not already covered by `common`'s `status.*` (pending/running/succeeded/
  // failed are reused directly from there) ----------------------------------------------------
  "agentWorkflow.stageState.degraded": { en: "Degraded", ko: "저하됨" },
  "agentWorkflow.stageState.blocked": { en: "Blocked", ko: "차단됨" },
  "agentWorkflow.stageState.skipped": { en: "Skipped", ko: "건너뜀" },

  // --- recent runs panel ----------------------------------------------------------
  "agentWorkflow.recentRuns.loading": {
    en: "Loading recent runs…",
    ko: "최근 실행 불러오는 중…",
  },
  "agentWorkflow.recentRuns.empty": { en: "No runs yet.", ko: "아직 실행 내역이 없습니다." },
  "agentWorkflow.recentRuns.stagesLine": {
    en: "{done}/{total} stages",
    ko: "{done}/{total} 단계",
  },

  // --- universe filter (toggle buttons + `universeSourceLabel`'s badge text) ---------------
  "agentWorkflow.universe.card": { en: "Card", ko: "카드" },
  "agentWorkflow.universe.screened": { en: "Screened", ko: "스크리닝됨" },

  // --- paper book panel ------------------------------------------------------------
  "agentWorkflow.book.heading": { en: "Paper book", ko: "페이퍼 북" },
  "agentWorkflow.book.universeFilterAriaLabel": {
    en: "Universe filter",
    ko: "유니버스 필터",
  },
  "agentWorkflow.book.filterNote": {
    en: "Also filters the effectiveness study and candidates panels below.",
    ko: "아래의 효과성 스터디 및 후보 패널에도 동일하게 필터가 적용됩니다.",
  },
  "agentWorkflow.book.executing": { en: "Executing…", ko: "실행하는 중…" },
  "agentWorkflow.book.executeButton": {
    en: "Execute pending (next open)",
    ko: "대기 주문 실행 (다음 시가)",
  },
  "agentWorkflow.book.loading": { en: "Loading the paper book…", ko: "페이퍼 북 불러오는 중…" },
  "agentWorkflow.book.empty": {
    en: "No books yet -- start a run to stage the first orders.",
    ko: "아직 북이 없습니다 -- 첫 주문을 스테이징하려면 실행을 시작하세요.",
  },
  "agentWorkflow.book.cardAdoptedLine": {
    en: "Card: {cardId} · Adopted {date}",
    ko: "카드: {cardId} · 도입일 {date}",
  },
  "agentWorkflow.book.cardAdoptedLineWithAsOf": {
    en: "Card: {cardId} · Adopted {date} · As of {asOf}",
    ko: "카드: {cardId} · 도입일 {date} · {asOf} 기준",
  },
  "agentWorkflow.book.cashEquityLine": {
    en: "Cash: {cash} · Equity: {equity} · Starting cash: {startingCash}",
    ko: "현금: {cash} · 자산 총액: {equity} · 시작 현금: {startingCash}",
  },
  "agentWorkflow.book.positionsHeading": { en: "Positions", ko: "포지션" },
  "agentWorkflow.book.noPositions": { en: "No open positions.", ko: "보유 중인 포지션이 없습니다." },
  "agentWorkflow.book.ordersHeading": { en: "Orders", ko: "주문" },
  "agentWorkflow.book.noOrders": { en: "No orders staged.", ko: "스테이징된 주문이 없습니다." },
  "agentWorkflow.book.taxHeading": { en: "Tax", ko: "세금" },
  "agentWorkflow.book.taxLine": {
    en: "Short-term: {shortTerm} · Long-term: {longTerm} · Net: {net}",
    ko: "단기: {shortTerm} · 장기: {longTerm} · 순액: {net}",
  },
  "agentWorkflow.book.executeResult": {
    en: "{filled}/{rejected}/{stillPending} filled/rejected/pending {asOf}, {storedOpen}/{liveQuote} stored/live, {universeLabel}",
    ko: "{filled}/{rejected}/{stillPending}건 체결/거부/대기 · {asOf} · 저장시가/실시간 {storedOpen}/{liveQuote}건 · {universeLabel}",
  },

  // --- effectiveness study panel -----------------------------------------------------
  "agentWorkflow.study.heading": { en: "Effectiveness study", ko: "효과성 스터디" },
  "agentWorkflow.study.loading": { en: "Loading the study…", ko: "스터디 불러오는 중…" },
  "agentWorkflow.study.benchmarkLine": {
    en: "Benchmark: {benchmark} ({benchmarkReturn})",
    ko: "벤치마크: {benchmark} ({benchmarkReturn})",
  },
  "agentWorkflow.study.benchmarkLineWithWindow": {
    en: "Benchmark: {benchmark} ({benchmarkReturn}) · Window {start} – {end}",
    ko: "벤치마크: {benchmark} ({benchmarkReturn}) · 기간 {start} – {end}",
  },
  "agentWorkflow.study.noArmMetrics": { en: "No arm metrics yet.", ko: "아직 그룹 지표가 없습니다." },
  "agentWorkflow.study.pairedHeading": {
    en: "Paired significance vs raw signal",
    ko: "원시 신호 대비 페어드 유의성",
  },
  "agentWorkflow.study.noPaired": {
    en: "No paired comparisons yet.",
    ko: "아직 페어드 비교가 없습니다.",
  },
  // The minimum detectable effect, rendered next to the significance heading so a p-value above
  // 0.05 is never read as "no effect". `{n}` is the gated-candidate count the page already has;
  // `{mde}` is the pre-registered 35pp figure from docs/reports/workflow-study-power-analysis.md --
  // see `PRE_REGISTERED_MDE_PP` in `AgentWorkflow.tsx` for why it is quoted, not recomputed.
  "agentWorkflow.study.power": {
    en: "At n={n} gated candidates this test only detects gaps of about {mde}pp or larger.",
    ko: "게이트 판정 후보 n={n}건에서는 약 {mde}포인트 이상의 격차만 탐지됩니다.",
  },
  "agentWorkflow.study.powerNoN": {
    en: "No gated candidates yet. The pre-registered bar detects gaps of about {mde}pp or larger.",
    ko: "아직 게이트 판정 후보가 없습니다. 사전 등록 기준으로는 약 {mde}포인트 이상만 탐지됩니다.",
  },
  "agentWorkflow.study.power.more": {
    en: "Pre-registered power analysis: at the 40-candidate bar, 80% power needs a true hit-rate gap near {mde}pp. Effects this programme has measured run 2-10pp, so a null here is expected, not informative.",
    ko: "사전 등록 검정력 분석: 후보 40건 기준에서 80% 검정력을 얻으려면 실제 적중률 격차가 약 {mde}포인트여야 합니다. 이 프로그램이 측정해 온 효과는 2~10포인트이므로, 여기서의 무효 결과는 예상된 것이며 정보 가치가 없습니다.",
  },
  "agentWorkflow.study.vibeVerdictCompliance": {
    en: "Vibe verdict compliance: {value}",
    ko: "Vibe 판정 준수율: {value}",
  },
  "agentWorkflow.study.discriminationHeading": {
    en: "Gate discrimination",
    ko: "게이트 판별력",
  },
  "agentWorkflow.study.notMeasurable": {
    en: "No gated candidates yet — gate effectiveness not measurable",
    ko: "아직 게이트를 통과한 후보가 없어 게이트 효과성을 측정할 수 없습니다",
  },

  // --- candidates panel -------------------------------------------------------------
  "agentWorkflow.candidates.heading": { en: "Candidates", ko: "후보" },
  "agentWorkflow.candidates.loading": { en: "Loading candidates…", ko: "후보 불러오는 중…" },
  "agentWorkflow.candidates.empty": {
    en: "No candidate observations yet.",
    ko: "아직 후보 관측 기록이 없습니다.",
  },
  "agentWorkflow.candidates.summaryLine": {
    en: "{total} observations · avoided {avoidedCost} · skips: {skipReasons} · fresh {fresh} / cached {cached} / mixed {mixed}",
    ko: "관측 {total}건 · 회피 비용 {avoidedCost} · 건너뛴 이유: {skipReasons} · 판정 신선 {fresh} / 캐시됨 {cached} / 혼합 {mixed}",
  },
  // The "no skip reasons" fallback inside `summaryLine`'s `{skipReasons}` slot -- lowercase to match
  // the sentence it sits in, so it is its own key rather than a reuse of `common.none` (which is
  // capitalized for a standalone label, not a mid-sentence word).
  "agentWorkflow.candidates.noneWord": { en: "none", ko: "없음" },

  // --- shared table headers (this page's own tables; `common.*` covers Symbol/Date/Status/Source) --
  "agentWorkflow.table.qty": { en: "Qty", ko: "수량" },
  "agentWorkflow.table.avgCost": { en: "Avg cost", ko: "평균 단가" },
  "agentWorkflow.table.marketValue": { en: "Market value", ko: "평가 금액" },
  "agentWorkflow.table.notional": { en: "Notional", ko: "명목 금액" },
  "agentWorkflow.table.fillPrice": { en: "Fill price", ko: "체결가" },
  "agentWorkflow.table.arm": { en: "Arm", ko: "그룹" },
  "agentWorkflow.table.universe": { en: "Universe", ko: "유니버스" },
  "agentWorkflow.table.totalReturn": { en: "Total return", ko: "총 수익률" },
  "agentWorkflow.table.maxDrawdown": { en: "Max drawdown", ko: "최대 낙폭" },
  "agentWorkflow.table.realizedVol": { en: "Realized vol", ko: "실현 변동성" },
  "agentWorkflow.table.exposure": { en: "Exposure", ko: "익스포저" },
  "agentWorkflow.table.adjustedExcess": { en: "Adjusted excess", ko: "조정 초과수익" },
  "agentWorkflow.table.trades": { en: "Trades", ko: "거래 수" },
  "agentWorkflow.table.liveFillFraction": { en: "Live fill fraction", ko: "실시간 체결 비율" },
  "agentWorkflow.table.meanDailyDiff": { en: "Mean daily diff", ko: "평균 일간 차이" },
  "agentWorkflow.table.bootstrapP": { en: "Bootstrap p", ko: "부트스트랩 p" },
  "agentWorkflow.table.gate": { en: "Gate", ko: "게이트" },
  "agentWorkflow.table.passedN": { en: "Passed n", ko: "통과 n" },
  "agentWorkflow.table.refusedN": { en: "Refused n", ko: "거부 n" },
  "agentWorkflow.table.passedHitRate": { en: "Passed hit rate", ko: "통과 적중률" },
  "agentWorkflow.table.refusedHitRate": { en: "Refused hit rate", ko: "거부 적중률" },
  "agentWorkflow.table.meanDiff": { en: "Mean diff", ko: "평균 차이" },
  // Statistical notation, not English words -- identical in both languages, same as `p`/`q` in any
  // stats package.
  "agentWorkflow.table.pValue": { en: "p", ko: "p" },
  "agentWorkflow.table.qValue": { en: "q", ko: "q" },
  "agentWorkflow.table.card": { en: "Card", ko: "카드" },
  "agentWorkflow.table.regime": { en: "Regime", ko: "국면" },
  "agentWorkflow.table.rank": { en: "Rank", ko: "순위" },
  "agentWorkflow.table.gatesColumn": { en: "Gates", ko: "게이트" },
  "agentWorkflow.table.skipReason": { en: "Skip reason", ko: "건너뛴 이유" },
  "agentWorkflow.table.state": { en: "State", ko: "상태" },
  "agentWorkflow.table.forwardReturn": { en: "Forward return", ko: "선행 수익률" },
  "agentWorkflow.table.alpha": { en: "Alpha", ko: "알파" },

  // --- PanelBoundary labels (rendered inside a Korean sentence by PanelBoundary) ------------------
  "agentWorkflow.panel.runConfig": { en: "Run configuration", ko: "실행 설정" },
  "agentWorkflow.panel.runProgress": { en: "Run progress", ko: "실행 진행 상황" },
  "agentWorkflow.panel.paperBook": { en: "Paper book", ko: "페이퍼 북" },
  "agentWorkflow.panel.study": { en: "Effectiveness study", ko: "효과성 스터디" },
  "agentWorkflow.panel.candidates": { en: "Candidates", ko: "후보" },
} as const satisfies MessageShard;
