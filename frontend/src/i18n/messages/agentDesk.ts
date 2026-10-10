/**
 * Trading Agents and Vibe Trading pages and their API helpers.
 *
 * Keys are prefixed `agentDesk.` -- see `catalog.ts` for the convention and why the prefix is
 * load-bearing (the duplicate-key guard in `i18n.test.tsx` keys off it). Sub-prefixed
 * `agentDesk.trading.*` (Trading Agents) and `agentDesk.vibe.*` (Vibe Trading) keep the two
 * pages' keys apart. A few strings (e.g. "Recent runs", "Final report", "Budget cap (USD)") that
 * read identically across pages live once in `common.ts` instead of once per page, per
 * `docs/COPY-STYLE.md` rule 2 ("one explanation per fact, app-wide") -- see `common.recentRuns`,
 * `common.finalReport` and `common.budgetCapUsd`.
 *
 * Model-written prose -- `final_md`, `output_md`, `decision_md`, `stage.summary`,
 * `entry.reflection`, raw `RunState`/`final_rating`/rating values echoed straight off the wire --
 * is deliberately left untranslated at the call site per the task brief; see the pages' own
 * comments at each call site for why.
 */
import type { MessageShard } from "@/i18n/types";

export const agentDesk = {
  // ============================================================================================
  // Shared (Trading Agents + Vibe Trading)
  // ============================================================================================

  // Client-derived display state for a recent-run row whose server `state` is still `"running"`
  // long after it can plausibly still be running (UX-15) -- the row's raw state is kept verbatim
  // in its `title`, this is a display-only demotion. Tone: neutral, per docs/COPY-STYLE.md (an
  // unclear/likely-stalled state, not a failure).
  "agentDesk.status.stale": { en: "Stale", ko: "오래됨" },

  // ============================================================================================
  // Trading Agents
  // ============================================================================================

  "agentDesk.trading.title": { en: "Trading Agents", ko: "트레이딩 에이전트" },
  "agentDesk.trading.subtitle": {
    en: "Full analyst-to-PM pipeline on one ticker, on our own data.",
    ko: "한 종목에 대한 애널리스트-PM 전체 파이프라인, 자체 데이터 기반.",
  },

  // --- static explainer ------------------------------------------------------------------------
  "agentDesk.trading.explainerPanel.title": { en: "How the desk works", ko: "데스크 작동 방식" },
  "agentDesk.trading.explainerPanel.summary": {
    en: "A twelve-stage pipeline turns evidence into a rated call; every number is grounded.",
    ko: "12단계 파이프라인이 근거 자료를 등급 평가로 전환하며, 모든 수치는 근거와 대조 확인됩니다.",
  },
  "agentDesk.trading.explainer.analysts.title": {
    en: "Four analysts write grounded reports",
    ko: "네 명의 애널리스트가 근거 기반 보고서를 작성합니다",
  },
  "agentDesk.trading.explainer.analysts.body": {
    en: "A market, sentiment, news and fundamentals analyst each write a report from evidence fetched ahead of time -- prices, filings, headlines, positioning. Every number they write is checked against that evidence before the report is accepted.",
    ko: "마켓, 센티먼트, 뉴스, 펀더멘털 애널리스트가 각각 미리 수집한 근거 자료 -- 가격, 공시, 헤드라인, 포지셔닝 -- 를 바탕으로 보고서를 작성합니다. 이들이 작성한 모든 수치는 보고서가 채택되기 전에 해당 근거와 대조 확인됩니다.",
  },
  "agentDesk.trading.explainer.debate.title": {
    en: "Bull and bear researchers debate",
    ko: "강세론자와 약세론자 리서처가 토론합니다",
  },
  "agentDesk.trading.explainer.debate.body": {
    en: "A bull researcher and a bear researcher argue the case for and against the position over one or more rounds, each responding to the other's last point rather than restating their own case in isolation.",
    ko: "강세론자 리서처와 약세론자 리서처가 한 차례 이상의 라운드에 걸쳐 포지션에 대한 찬반 논거를 주고받습니다. 각자 자신의 입장만 반복하는 대신 상대의 직전 발언에 응답합니다.",
  },
  "agentDesk.trading.explainer.researchManager.title": {
    en: "A research manager judges the debate",
    ko: "리서치 매니저가 토론을 판단합니다",
  },
  "agentDesk.trading.explainer.researchManager.body": {
    en: "The research manager reads the whole debate and the four analyst reports and renders a rating -- the debate's own verdict, not a vote count.",
    ko: "리서치 매니저는 토론 전체와 네 애널리스트의 보고서를 읽고 평가를 내립니다 -- 이는 표결 결과가 아니라 토론 자체의 결론입니다.",
  },
  "agentDesk.trading.explainer.trader.title": {
    en: "A trader turns the rating into a proposal",
    ko: "트레이더가 평가를 제안으로 전환합니다",
  },
  "agentDesk.trading.explainer.trader.body": {
    en: "The trader converts the research manager's rating into a concrete proposal: an entry, a stop, and a position size -- something a desk could actually place.",
    ko: "트레이더는 리서치 매니저의 평가를 진입가, 손절가, 포지션 규모를 갖춘 구체적인 제안으로 전환합니다 -- 데스크가 실제로 실행할 수 있는 형태입니다.",
  },
  "agentDesk.trading.explainer.risk.title": {
    en: "Three risk analysts stress the proposal",
    ko: "세 명의 리스크 애널리스트가 제안을 검증합니다",
  },
  "agentDesk.trading.explainer.risk.body": {
    en: "An aggressive, a conservative and a neutral risk analyst each stress-test the trader's proposal from their own stance, over one or more rounds, surfacing what each stance would object to before anything is finalised.",
    ko: "공격적, 보수적, 중립적 리스크 애널리스트가 각자의 관점에서 한 차례 이상의 라운드에 걸쳐 트레이더의 제안을 검증하며, 최종 확정 전에 각 입장에서 나올 수 있는 이의를 드러냅니다.",
  },
  "agentDesk.trading.explainer.pm.title": {
    en: "A portfolio manager issues the final rating",
    ko: "포트폴리오 매니저가 최종 평가를 내립니다",
  },
  "agentDesk.trading.explainer.pm.body": {
    en: "The portfolio manager weighs the risk review against the original proposal and issues the run's final rating -- informed by lessons from the desk's own past decisions whose outcomes are now known, not only by this run's own evidence.",
    ko: "포트폴리오 매니저는 리스크 검토와 원래 제안을 함께 고려해 실행의 최종 평가를 내립니다 -- 이번 실행의 근거뿐 아니라 결과가 이미 확인된 데스크의 과거 의사결정에서 얻은 교훈도 반영합니다.",
  },
  "agentDesk.trading.explainerPanel.footer": {
    en: "Every number an agent writes is checked against the evidence it was given. A stage that fails that check three times is shown marked “ungrounded” rather than hidden -- see the progress board below.",
    ko: "에이전트가 작성하는 모든 수치는 주어진 근거와 대조 확인됩니다. 이 확인을 세 번 연속 통과하지 못한 단계는 숨기지 않고 “근거 미확인”으로 표시됩니다 -- 아래 진행 보드를 참고하세요.",
  },

  // --- layers (progress board section headings) -------------------------------------------------
  "agentDesk.trading.layer.analysts": { en: "Analysts", ko: "애널리스트" },
  "agentDesk.trading.layer.debate": { en: "Bull / Bear debate", ko: "강세/약세 토론" },
  "agentDesk.trading.layer.researchManager": { en: "Research Manager", ko: "리서치 매니저" },
  "agentDesk.trading.layer.trader": { en: "Trader", ko: "트레이더" },
  "agentDesk.trading.layer.risk": { en: "Risk review", ko: "리스크 검토" },
  "agentDesk.trading.layer.pm": { en: "Portfolio Manager", ko: "포트폴리오 매니저" },
  "agentDesk.trading.layer.fallback": { en: "Layer {layer}", ko: "레이어 {layer}" },

  // --- stage-state labels not already covered by common.status.* --------------------------------
  "agentDesk.trading.stageState.running": { en: "Running…", ko: "실행 중…" },
  "agentDesk.trading.stageState.degraded": {
    en: "Degraded (ungrounded)",
    ko: "성능 저하 (근거 미확인)",
  },
  "agentDesk.trading.stageState.blocked": { en: "Blocked", ko: "차단됨" },
  "agentDesk.trading.stageState.skipped": { en: "Skipped", ko: "건너뜀" },

  // --- fetch-error fallbacks ----------------------------------------------------------------------
  "agentDesk.trading.error.configLoad": {
    en: "Could not load the Trading Agents configuration.",
    ko: "트레이딩 에이전트 설정을 불러올 수 없습니다.",
  },
  "agentDesk.trading.error.runsLoad": {
    en: "Could not load recent runs.",
    ko: "최근 실행 내역을 불러올 수 없습니다.",
  },
  "agentDesk.trading.error.memoryLoad": {
    en: "Could not load decision memory.",
    ko: "의사결정 메모리를 불러올 수 없습니다.",
  },
  "agentDesk.trading.error.runLoad": {
    en: "Could not load this run.",
    ko: "이 실행을 불러올 수 없습니다.",
  },
  "agentDesk.trading.error.cancelRun": {
    en: "Could not cancel this run.",
    ko: "이 실행을 취소할 수 없습니다.",
  },

  // --- start-run errors (shared between the page and api/tradingagents.ts's describeStartRunError) --
  "agentDesk.trading.startError.symbolRequired": {
    en: "A symbol is required.",
    ko: "종목 기호를 입력해야 합니다.",
  },
  "agentDesk.trading.startError.generic": {
    en: "Could not start the run.",
    ko: "실행을 시작할 수 없습니다.",
  },
  "agentDesk.trading.startError.rejected": {
    en: "The run request was rejected. Check the symbol and analyst selection and try again.",
    ko: "실행 요청이 거부되었습니다. 종목 기호와 애널리스트 선택을 확인한 뒤 다시 시도하세요.",
  },
  "agentDesk.trading.startError.runInFlight": {
    en: "A run is already in flight -- only one run can be active at a time.",
    ko: "이미 실행 중인 작업이 있습니다 -- 한 번에 하나의 실행만 진행할 수 있습니다.",
  },
  "agentDesk.trading.agentUnavailable": {
    en: "The agent layer is unavailable.",
    ko: "에이전트 레이어를 사용할 수 없습니다.",
  },

  // --- run form ---------------------------------------------------------------------------------
  "agentDesk.trading.runForm.title": { en: "Start a run", ko: "실행 시작" },
  "agentDesk.trading.runForm.loadingConfig": {
    en: "Loading configuration…",
    ko: "설정 불러오는 중…",
  },
  "agentDesk.trading.runForm.tradeDate": {
    en: "Trade date (optional)",
    ko: "거래일 (선택 사항)",
  },
  "agentDesk.trading.runForm.debateRounds": {
    en: "Debate rounds (max {max})",
    ko: "토론 라운드 (최대 {max})",
  },
  "agentDesk.trading.runForm.riskRounds": {
    en: "Risk rounds (max {max})",
    ko: "리스크 라운드 (최대 {max})",
  },
  "agentDesk.trading.runForm.model": { en: "Model", ko: "모델" },
  "agentDesk.trading.runForm.live": { en: "Live (today's quote)", ko: "실시간 (오늘 시세)" },
  "agentDesk.trading.runForm.liveHint": {
    en: "Uses today's live quote and 5-minute bars; the as-of date must be today.",
    ko: "오늘의 실시간 시세와 5분봉을 사용합니다. 기준일은 오늘이어야 합니다.",
  },
  "agentDesk.trading.runForm.starting": { en: "Starting…", ko: "시작하는 중…" },
  "agentDesk.trading.runForm.start": { en: "Start", ko: "시작" },

  // --- recent runs --------------------------------------------------------------------------------
  "agentDesk.trading.recentRuns.loading": {
    en: "Loading recent runs…",
    ko: "최근 실행 불러오는 중…",
  },
  "agentDesk.trading.recentRuns.empty": {
    en: "No runs yet -- start one above.",
    ko: "아직 실행 내역이 없습니다 -- 위에서 실행을 시작하세요.",
  },
  "agentDesk.trading.recentRuns.stagesCount": {
    en: "{done}/{total} stages",
    ko: "{total}개 중 {done}개 단계",
  },
  "agentDesk.trading.recentRuns.degradedBadge": { en: "degraded", ko: "성능 저하" },

  // --- selected run -------------------------------------------------------------------------------
  "agentDesk.trading.run.loading": { en: "Loading run…", ko: "실행 불러오는 중…" },

  // --- progress board -----------------------------------------------------------------------------
  "agentDesk.trading.progressBoard.heading": {
    en: "Progress -- {state}",
    ko: "진행 상황 -- {state}",
  },
  "agentDesk.trading.progressBoard.cancelRun": { en: "Cancel run", ko: "실행 취소" },
  "agentDesk.trading.budget.summary": {
    en: "{spent} spent of {cap} cap ({calls} calls)",
    ko: "{cap} 상한 중 {spent} 사용 ({calls}회 호출)",
  },

  // --- stage row -----------------------------------------------------------------------------------
  "agentDesk.trading.stage.noOutput": { en: "No output yet.", ko: "아직 출력이 없습니다." },
  "agentDesk.trading.stage.costSoFar": {
    en: "Cost so far: {cost}",
    ko: "지금까지 비용: {cost}",
  },

  // --- final report --------------------------------------------------------------------------------
  "agentDesk.trading.finalReport.empty": {
    en: "No final report yet.",
    ko: "아직 최종 리포트가 없습니다.",
  },
  "agentDesk.trading.openReport": {
    en: "Open the research report for {symbol} →",
    ko: "{symbol} 리서치 리포트 열기 →",
  },

  // --- decision memory -----------------------------------------------------------------------------
  "agentDesk.trading.memory.title": { en: "Decision memory", ko: "의사결정 메모리" },
  "agentDesk.trading.memory.description": {
    en: "Past decisions this desk has recorded, some still awaiting an outcome. Resolved entries feed later ratings.",
    ko: "결과를 기다리고 있는 항목을 포함해 이 데스크가 기록한 과거 의사결정입니다. 완료된 각 항목은 이후 실행에서 포트폴리오 매니저의 최종 평가에 반영됩니다.",
  },
  "agentDesk.trading.memory.loading": {
    en: "Loading decision memory…",
    ko: "의사결정 메모리 불러오는 중…",
  },
  "agentDesk.trading.memory.empty": {
    en: "No decisions recorded yet.",
    ko: "아직 기록된 의사결정이 없습니다.",
  },
  "agentDesk.trading.memory.resolved": { en: "Resolved", ko: "완료됨" },
  "agentDesk.trading.memory.alphaVs": { en: "Alpha vs {benchmark}", ko: "{benchmark} 대비 알파" },
  "agentDesk.trading.memory.rawReturn": { en: "Raw return", ko: "원 수익률" },
  "agentDesk.trading.memory.holding": { en: "Holding", ko: "보유 기간" },
  "agentDesk.trading.memory.holdingDays": { en: "{days}d", ko: "{days}일" },
  "agentDesk.trading.memory.showDecision": { en: "Show decision", ko: "의사결정 보기" },
  "agentDesk.trading.memory.hideDecision": { en: "Hide decision", ko: "의사결정 숨기기" },
  "agentDesk.trading.memory.noDecisionText": {
    en: "No decision text recorded.",
    ko: "기록된 의사결정 텍스트가 없습니다.",
  },

  // --- grounding panel -----------------------------------------------------------------------------
  "agentDesk.trading.grounding.label": { en: "Ungrounded", ko: "근거 미확인" },
  "agentDesk.trading.grounding.detail_one": {
    en: "-- this stage’s output failed the grounding check {attempts} time. It is shown as written, not hidden, but its numbers should not be trusted without checking the underlying evidence.",
    ko: "-- 이 단계의 출력이 근거 확인을 {attempts}회 통과하지 못했습니다. 작성된 그대로 표시되며 숨기지 않지만, 근거 자료를 확인하기 전까지 수치를 신뢰해서는 안 됩니다.",
  },
  "agentDesk.trading.grounding.detail_other": {
    en: "-- this stage’s output failed the grounding check {attempts} times. It is shown as written, not hidden, but its numbers should not be trusted without checking the underlying evidence.",
    ko: "-- 이 단계의 출력이 근거 확인을 {attempts}회 통과하지 못했습니다. 작성된 그대로 표시되며 숨기지 않지만, 근거 자료를 확인하기 전까지 수치를 신뢰해서는 안 됩니다.",
  },

  // ============================================================================================
  // Vibe Trading
  // ============================================================================================

  "agentDesk.vibe.title": { en: "Vibe Trading", ko: "바이브 트레이딩" },
  "agentDesk.vibe.subtitle": {
    en: "Preset desks of role agents, run as a DAG on our own data.",
    ko: "역할 에이전트로 구성된 프리셋 데스크가 우리 자체 데이터를 바탕으로 DAG 형태로 실행됩니다.",
  },

  // --- static explainer ------------------------------------------------------------------------
  "agentDesk.vibe.explainerPanel.title": { en: "How this desk works", ko: "이 데스크의 작동 방식" },
  "agentDesk.vibe.explainerPanel.summary": {
    en: "A committee of role agents runs as a dependency graph on pre-fetched market data.",
    ko: "역할 에이전트로 구성된 위원회가 미리 수집한 시장 데이터를 바탕으로 의존성 그래프 형태로 실행됩니다.",
  },
  "agentDesk.vibe.explainer.step1": {
    en: "You pick a preset desk: a committee of role agents, defined as data, not code.",
    ko: "프리셋 데스크를 선택합니다: 코드가 아니라 데이터로 정의된 역할 에이전트 위원회입니다.",
  },
  "agentDesk.vibe.explainer.step2": {
    en: "The desk's tasks form a dependency graph. Every task in the same layer runs in parallel with the others in that layer.",
    ko: "데스크의 작업들은 의존성 그래프를 이룹니다. 같은 레이어의 모든 작업은 그 레이어의 다른 작업들과 병렬로 실행됩니다.",
  },
  "agentDesk.vibe.explainer.step3": {
    en: "Each downstream agent receives only its upstream's short summary, never the full output text.",
    ko: "각 하위 에이전트는 상위 에이전트의 전체 출력 텍스트가 아니라 짧은 요약만 전달받습니다.",
  },
  "agentDesk.vibe.explainer.step4": {
    en: "Real market data is pre-fetched and injected into every agent's prompt as ground truth, before any agent runs.",
    ko: "실제 시장 데이터는 어떤 에이전트가 실행되기 전에 미리 수집되어 모든 에이전트의 프롬프트에 근거 자료로 주입됩니다.",
  },
  "agentDesk.vibe.explainer.step5": {
    en: "A task whose upstream failed is marked blocked, never quietly completed on missing input — that is deliberate.",
    ko: "상위 작업이 실패한 작업은 차단됨으로 표시되며, 입력이 없는 상태로 조용히 완료 처리되지 않습니다 — 이는 의도된 동작입니다.",
  },

  // --- stage-state labels not already covered by common.status.* --------------------------------
  "agentDesk.vibe.stageState.degraded": { en: "Degraded", ko: "성능 저하" },
  "agentDesk.vibe.stageState.blocked": { en: "Blocked", ko: "차단됨" },
  "agentDesk.vibe.stageState.skipped": { en: "Skipped", ko: "건너뜀" },

  // --- worker model picker --------------------------------------------------------------------------
  // The selectable models' own labels (Haiku/Sonnet/Opus/Fable) come from `GET /api/vibedesk/config`
  // now, not from a local i18n key -- see `VibeConfig.available_models` in `api/vibedesk.ts` and
  // `VibeTrading.tsx`'s `<select>`, which renders `m.label` straight off the wire, same as
  // `TradingAgents.tsx` already does for its own identical picker.
  "agentDesk.vibe.model.custom": { en: "Custom version…", ko: "사용자 지정 버전…" },
  "agentDesk.vibe.model.configError": {
    en: "Could not load the model list -- use Custom version… to name one directly.",
    ko: "모델 목록을 불러오지 못했습니다 -- 사용자 지정 버전…으로 직접 입력하세요.",
  },

  // --- preset picker ---------------------------------------------------------------------------------
  "agentDesk.vibe.presetPicker.title": { en: "Choose a preset", ko: "프리셋 선택" },
  "agentDesk.vibe.presetPicker.loading": {
    en: "Loading presets…",
    ko: "프리셋 불러오는 중…",
  },
  "agentDesk.vibe.presetPicker.empty": {
    en: "No presets are configured.",
    ko: "설정된 프리셋이 없습니다.",
  },
  "agentDesk.vibe.presetPicker.meta": {
    en: "{agents} agents · {layers} layers",
    ko: "{agents}개 에이전트 · {layers}개 레이어",
  },

  // --- fetch-error fallbacks ----------------------------------------------------------------------
  "agentDesk.vibe.error.presetsLoad": {
    en: "Could not load presets.",
    ko: "프리셋을 불러올 수 없습니다.",
  },
  "agentDesk.vibe.error.presetLoad": {
    en: "Could not load this preset.",
    ko: "이 프리셋을 불러올 수 없습니다.",
  },
  "agentDesk.vibe.error.startRun": {
    en: "Could not start the run.",
    ko: "실행을 시작할 수 없습니다.",
  },
  "agentDesk.vibe.error.runLoad": {
    en: "Could not load this run.",
    ko: "이 실행을 불러올 수 없습니다.",
  },
  "agentDesk.vibe.error.recentRunsLoad": {
    en: "Could not load recent runs.",
    ko: "최근 실행 내역을 불러올 수 없습니다.",
  },
  "agentDesk.vibe.error.agentAvailability": {
    en: "Could not check agent availability.",
    ko: "에이전트 사용 가능 여부를 확인할 수 없습니다.",
  },

  // --- run configuration form -----------------------------------------------------------------------
  "agentDesk.vibe.runConfig.title": { en: "Run configuration", ko: "실행 설정" },
  "agentDesk.vibe.runConfig.loadingDetail": {
    en: "Loading preset detail…",
    ko: "프리셋 상세 정보 불러오는 중…",
  },
  "agentDesk.vibe.runConfig.agentsSummary": {
    en: "{agents} agents across {layers} layers.",
    ko: "{layers}개 레이어에 걸쳐 {agents}개 에이전트.",
  },
  "agentDesk.vibe.runConfig.symbolPlaceholder": { en: "e.g. NVDA", ko: "예: NVDA" },
  "agentDesk.vibe.runConfig.question": { en: "Question", ko: "질문" },
  "agentDesk.vibe.runConfig.questionPlaceholder": {
    en: "What should the desk investigate?",
    ko: "데스크가 무엇을 조사해야 합니까?",
  },
  "agentDesk.vibe.runConfig.live": { en: "Live (today's quote)", ko: "실시간 (오늘 시세)" },
  "agentDesk.vibe.runConfig.liveHint": {
    en: "Uses today's live quote and 5-minute bars.",
    ko: "오늘의 실시간 시세와 5분봉을 사용합니다.",
  },
  "agentDesk.vibe.runConfig.workerModel": { en: "Worker model", ko: "작업 모델" },
  "agentDesk.vibe.runConfig.customModelId": { en: "Custom model id", ko: "사용자 지정 모델 ID" },
  "agentDesk.vibe.runConfig.customModelPlaceholder": {
    en: "e.g. claude-sonnet-5-20250930",
    ko: "예: claude-sonnet-5-20250930",
  },
  "agentDesk.vibe.runConfig.agentUnavailable": {
    en: "Agent layer unavailable: {reason}",
    ko: "에이전트 레이어를 사용할 수 없음: {reason}",
  },
  "agentDesk.vibe.runConfig.starting": { en: "Starting…", ko: "시작하는 중…" },
  "agentDesk.vibe.runConfig.startRun": { en: "Start run", ko: "실행 시작" },

  // --- run progress ------------------------------------------------------------------------------
  "agentDesk.vibe.runProgress.title": { en: "Run progress", ko: "실행 진행 상황" },
  "agentDesk.vibe.runProgress.summary": {
    en: "State: {state} · Cost: {spent} / {cap} cap · {calls} calls",
    ko: "상태: {state} · 비용: {spent} / {cap} 상한 · {calls}회 호출",
  },
  "agentDesk.vibe.dag.layer": { en: "Layer {layer}", ko: "레이어 {layer}" },

  // --- stage detail ------------------------------------------------------------------------------
  "agentDesk.vibe.stageDetail.meta": {
    en: "Seat: {seat} · State: {state} · Cost: {cost}",
    ko: "좌석: {seat} · 상태: {state} · 비용: {cost}",
  },
  "agentDesk.vibe.stageDetail.groundingDegraded": {
    en: "Grounding degraded",
    ko: "근거 확인 저하",
  },
  "agentDesk.vibe.stageDetail.noOutputYet": { en: "(no output yet)", ko: "(아직 출력 없음)" },

  // --- final report --------------------------------------------------------------------------------
  "agentDesk.vibe.openReport": {
    en: "Open the research report for {symbol} →",
    ko: "{symbol} 리서치 리포트 열기 →",
  },

  // --- recent runs --------------------------------------------------------------------------------
  "agentDesk.vibe.recentRuns.loading": {
    en: "Loading recent runs…",
    ko: "최근 실행 불러오는 중…",
  },
  "agentDesk.vibe.recentRuns.empty": { en: "No runs yet.", ko: "아직 실행 내역이 없습니다." },
  "agentDesk.vibe.recentRuns.stagesCount": {
    en: "{done}/{total} stages",
    ko: "{total}개 중 {done}개 단계",
  },
  "agentDesk.vibe.recentRuns.degradedBadge": { en: "degraded", ko: "성능 저하" },

  // --- PanelBoundary labels (rendered inside a Korean sentence by PanelBoundary) ------------------
  "agentDesk.trading.panel.howItWorks": { en: "How the desk works", ko: "데스크 작동 방식" },
  "agentDesk.trading.panel.runForm": { en: "Run form", ko: "실행 폼" },
  "agentDesk.trading.panel.progressBoard": { en: "Progress board", ko: "진행 보드" },
  "agentDesk.trading.panel.decisionMemory": { en: "Decision memory", ko: "의사결정 메모리" },
  "agentDesk.vibe.panel.presetPicker": { en: "Preset picker", ko: "프리셋 선택" },
  "agentDesk.vibe.panel.runConfig": { en: "Run configuration", ko: "실행 설정" },
  "agentDesk.vibe.panel.runProgress": { en: "Run progress", ko: "실행 진행 상황" },

  // ============================================================================================
  // Live Decisions -- the daemon status/decisions/manual-decide panel mounted at the bottom of
  // Trading Agents (`pages/agentdesk/LiveDecisionsPanel.tsx`). Shared prefix, not sub-split by
  // page, since only Trading Agents mounts this panel today.
  // ============================================================================================

  "agentDesk.live.heading": { en: "Live decisions", ko: "실시간 결정" },
  "agentDesk.live.loading": { en: "Loading live status…", ko: "실시간 상태 불러오는 중…" },
  "agentDesk.live.unavailable": {
    en: "Live decisions are not available yet.",
    ko: "실시간 결정 기능을 아직 사용할 수 없습니다.",
  },
  "agentDesk.live.note": {
    en: "Research only. No trade placed, no advice given.",
    ko: "리서치 전용입니다. 거래를 실행하지 않으며 조언도 아닙니다.",
  },

  "agentDesk.live.status.enabled": { en: "Enabled", ko: "활성화됨" },
  "agentDesk.live.status.disabled": { en: "Disabled", ko: "비활성화됨" },
  "agentDesk.live.status.running": { en: "Running", ko: "실행 중" },
  "agentDesk.live.status.stopped": { en: "Stopped", ko: "중지됨" },
  "agentDesk.live.status.healthy": { en: "Healthy", ko: "정상" },
  "agentDesk.live.status.unhealthy": { en: "Unhealthy", ko: "비정상" },
  "agentDesk.live.status.healthUnknown": { en: "Health unknown", ko: "상태 확인 안 됨" },

  "agentDesk.live.stat.marketState": { en: "Market state", ko: "시장 상태" },
  "agentDesk.live.stat.lastTick": { en: "Last tick", ko: "마지막 실행" },
  "agentDesk.live.stat.nextWake": { en: "Next wake", ko: "다음 실행 예정" },
  "agentDesk.live.stat.ticks": { en: "Ticks", ko: "실행 횟수" },
  "agentDesk.live.stat.decisionsToday": { en: "Decisions today", ko: "오늘 결정 수" },
  "agentDesk.live.stat.failures": { en: "Consecutive failures", ko: "연속 실패 횟수" },
  "agentDesk.live.stat.interval": { en: "Interval", ko: "주기" },
  "agentDesk.live.stat.intervalValue": { en: "{n} min", ko: "{n}분" },
  "agentDesk.live.stat.cap": { en: "Spend cap", ko: "지출 한도" },
  "agentDesk.live.stat.symbols": { en: "Watched: {symbols}", ko: "감시 종목: {symbols}" },

  "agentDesk.live.decideNow.action": { en: "Decide now", ko: "지금 결정" },
  "agentDesk.live.decideNow.deciding": { en: "Deciding…", ko: "결정하는 중…" },
  "agentDesk.live.decideNow.error": {
    en: "Could not get a decision for this symbol.",
    ko: "이 종목에 대한 결정을 가져올 수 없습니다.",
  },

  "agentDesk.live.decisions.title": { en: "Recent decisions", ko: "최근 결정" },
  "agentDesk.live.decisions.empty": {
    en: "No live decisions recorded yet.",
    ko: "아직 기록된 실시간 결정이 없습니다.",
  },
  "agentDesk.live.decisions.col.time": { en: "Time", ko: "시각" },
  "agentDesk.live.decisions.col.symbol": { en: "Symbol", ko: "종목" },
  "agentDesk.live.decisions.col.stance": { en: "Stance", ko: "의견" },
  "agentDesk.live.decisions.col.confidence": { en: "Confidence", ko: "확신도" },
  "agentDesk.live.decisions.col.price": { en: "Price", ko: "가격" },
  "agentDesk.live.decisions.col.source": { en: "Source", ko: "출처" },
  "agentDesk.live.decisions.col.model": { en: "Model", ko: "모델" },
  "agentDesk.live.decisions.col.cost": { en: "Cost", ko: "비용" },
  "agentDesk.live.decisions.degraded": { en: "Ungrounded", ko: "근거 미확인" },

  "agentDesk.live.stance.buy": { en: "Buy", ko: "매수" },
  "agentDesk.live.stance.sell": { en: "Sell", ko: "매도" },
  "agentDesk.live.stance.hold": { en: "Hold", ko: "보유" },
  "agentDesk.live.stance.noAction": { en: "No action", ko: "조치 없음" },

  "agentDesk.live.source.daemon": { en: "Daemon", ko: "데몬" },
  "agentDesk.live.source.manual": { en: "Manual", ko: "수동" },

  // ============================================================================================
  // Research Desk -- the toggle page over Trading Agents and Vibe Trading (see
  // `pages/ResearchDesk.tsx`). Each desk still shows its own `agentDesk.trading.*` /
  // `agentDesk.vibe.*` title and subtitle beneath this page's toggle -- these keys are only the
  // toggle itself.
  // ============================================================================================

  "agentDesk.researchDesk.title": { en: "Research Desk", ko: "리서치 데스크" },
  "agentDesk.researchDesk.subtitle": {
    en: "Analyst pipeline or committee desk, on our own data.",
    ko: "애널리스트 파이프라인 또는 위원회 데스크, 자체 데이터 기반.",
  },
  "agentDesk.researchDesk.tabsAriaLabel": { en: "Research desk view", ko: "리서치 데스크 보기" },
  "agentDesk.researchDesk.tab.analyst": { en: "Analyst pipeline", ko: "애널리스트 파이프라인" },
  "agentDesk.researchDesk.tab.committee": { en: "Committee", ko: "위원회" },
} as const satisfies MessageShard;
