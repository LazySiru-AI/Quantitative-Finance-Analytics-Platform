/**
 * The navigation tree's own text: the five section names, every page's label, and the one-phrase
 * blurb `NotFound.tsx` shows beside each destination.
 *
 * **Keyed by route path, not by position.** `nav.ts` orders its sections and items as a tuple and
 * another session adds to it; a key like `nav.section.0.label` would silently point at a different
 * page the moment the order changed. The route (`/paper-desk`) is the one identifier that stays
 * attached to a page across any reordering, so it is what a label is looked up by:
 * `t(\`nav.page.\${item.to}.label\` as MessageKey)` -- with the small cost that this file and
 * `nav.ts` have to agree on the set of routes, which `catalog.test.ts`' key checks and the app's own
 * "every nav item renders" test between them keep honest.
 *
 * Blurbs are full sentences and are translated as such -- several embed an arrow or an em dash, and
 * one names `Form 8949`, which stays in English because it is a form number, not a phrase.
 */
import type { MessageShard } from "@/i18n/types";

export const nav = {
  // --- section rail --------------------------------------------------------
  "nav.section.overview.label": { en: "Overview", ko: "개요" },
  "nav.section.portfolio.label": { en: "Account", ko: "계좌" },
  "nav.section.strategy.label": { en: "Strategy Lab", ko: "전략 실험실" },
  "nav.section.agents.label": { en: "Agent Desk", ko: "에이전트 데스크" },
  "nav.section.market.label": { en: "Market", ko: "시장" },
  "nav.section.data.label": { en: "Data", ko: "데이터" },

  // --- Overview ------------------------------------------------------------
  "nav.page./overview.label": { en: "Overview", ko: "개요" },
  "nav.page./overview.blurb": {
    en: "Today's picture across every section",
    ko: "모든 섹션을 아우르는 오늘의 현황",
  },

  // --- Portfolio -----------------------------------------------------------
  "nav.page./portfolio.label": { en: "Account", ko: "계좌" },
  "nav.page./portfolio.blurb": { en: "Holdings, cash and equity", ko: "보유 종목, 현금, 자산 총액" },
  "nav.page./designer.label": { en: "Planner", ko: "플래너" },
  "nav.page./designer.blurb": {
    en: "Plan holdings per account, wash-sale aware",
    ko: "계좌별 보유 계획, 워시 세일 반영",
  },
  "nav.page./paper-desk.label": { en: "Paper Desk", ko: "페이퍼 데스크" },
  "nav.page./paper-desk.blurb": {
    en: "What each reference agent is holding now",
    ko: "각 참고 에이전트가 현재 보유 중인 종목",
  },
  "nav.page./activity.label": { en: "Activity", ko: "거래 내역" },
  "nav.page./activity.blurb": {
    en: "Every transaction, with its source row",
    ko: "모든 거래와 그 원본 행",
  },
  "nav.page./tax.label": { en: "Tax", ko: "세금" },
  // `Form 8949` is a US form number, not a phrase -- it stays Latin in both languages.
  "nav.page./tax.blurb": { en: "Realized gains, lots and Form 8949", ko: "실현 이익, 세부 매수 단위, Form 8949" },
  // `nav.page./wash-sales.*` removed with the nav entry. Unlike `/backtest` and friends below --
  // which keep their keys because those routes still resolve to their own pages -- `/wash-sales` is
  // now only a redirect, so nothing can ever ask for its label. `favorites.ts` sanitises stored
  // paths through `NAV_ITEMS`, so a stale favourite drops out rather than looking one up.

  // --- Strategy Lab --------------------------------------------------------
  "nav.page./strategy.label": { en: "Overview", ko: "개요" },
  "nav.page./strategy.blurb": {
    en: "What the lab tests, and what it has found so far",
    ko: "실험실이 검증하는 대상과 지금까지의 결과",
  },
  "nav.page./competition.label": { en: "Competition", ko: "컴페티션" },
  "nav.page./competition.blurb": {
    en: "Leaderboard, card library and rounds",
    ko: "리더보드, 카드 라이브러리, 라운드",
  },
  "nav.page./evidence.label": { en: "Evidence", ko: "근거" },
  "nav.page./evidence.blurb": {
    en: "Backtests, interval accuracy and the rule catalogue",
    ko: "백테스트, 간격별 정확도, 규칙 카탈로그",
  },
  // `/backtest`, `/rules` and `/timeframes` folded into `/evidence` above (see `nav.ts`); their keys
  // stay here, unreferenced by `NAV` but harmless, per this repo's convention of never deleting
  // translated copy that other code might still read (the pages' own headings use their own
  // `strategy.*` keys, not these -- but a deep link to one of these routes still renders its page).
  "nav.page./backtest.label": { en: "Backtest", ko: "백테스트" },
  "nav.page./backtest.blurb": { en: "Event studies and drawdowns", ko: "이벤트 스터디와 낙폭" },
  "nav.page./rules.label": { en: "Rules", ko: "규칙" },
  "nav.page./rules.blurb": { en: "Rule catalog and expression tester", ko: "규칙 카탈로그와 식 테스터" },
  "nav.page./timeframes.label": { en: "Timeframes", ko: "타임프레임" },
  "nav.page./timeframes.blurb": {
    en: "Rule accuracy across intervals, drilled down",
    ko: "간격별 규칙 정확도, 상세 분석",
  },
  // `nav.page./thesis.*` removed with the nav entry -- `/thesis/:symbol?` is now a redirect into
  // Evidence's Thesis tab, so nothing renders a label for it. The tab's own label is
  // `strategy.evidence.tab.thesis`.

  // --- Agent Desk ----------------------------------------------------------
  "nav.page./agents.label": { en: "Overview", ko: "개요" },
  "nav.page./agents.blurb": {
    en: "What each desk does, and whether the agent layer is up",
    ko: "각 데스크의 역할과 에이전트 레이어 가동 여부",
  },
  "nav.page./manager.label": { en: "Manager", ko: "매니저" },
  "nav.page./manager.blurb": {
    en: "What changed and what matters, curated across every desk",
    ko: "모든 데스크를 아울러 정리한, 무엇이 바뀌었고 무엇이 중요한지",
  },
  // `/research-desk` folded the two entries below into one nav item (see `nav.ts`); their keys stay
  // here, unreferenced by `NAV` but harmless, per this repo's own convention of never deleting
  // translated copy that other code might still read (`ResearchDesk.tsx` reuses each page's own
  // `agentDesk.trading.*` / `agentDesk.vibe.*` title, not these).
  "nav.page./trading-agents.label": { en: "Trading Agents", ko: "트레이딩 에이전트" },
  "nav.page./trading-agents.blurb": {
    en: "A full analyst-to-portfolio-manager pipeline on one ticker",
    ko: "한 종목에 대한 애널리스트–포트폴리오 매니저 전체 파이프라인",
  },
  "nav.page./vibe-trading.label": { en: "Vibe Trading", ko: "바이브 트레이딩" },
  "nav.page./vibe-trading.blurb": {
    en: "Preset desks of role agents, run as a DAG",
    ko: "역할 에이전트로 구성된 프리셋 데스크, DAG로 실행",
  },
  "nav.page./research-desk.label": { en: "Research Desk", ko: "리서치 데스크" },
  "nav.page./research-desk.blurb": {
    en: "Analyst pipeline or committee desk, on our own data",
    ko: "애널리스트 파이프라인 또는 위원회 데스크, 자체 데이터 기반",
  },
  "nav.page./agent-workflow.label": { en: "Agent Workflow", ko: "에이전트 워크플로" },
  "nav.page./agent-workflow.blurb": {
    en: "Regime → strategy → research → plan → next-open execution, measured against single-tool arms",
    ko: "국면 → 전략 → 리서치 → 계획 → 다음 시가 실행, 단일 도구 그룹과 비교 측정",
  },
  "nav.page./personas.label": { en: "Personas", ko: "페르소나" },
  "nav.page./personas.blurb": {
    en: "What each followed influencer has been saying, from their own words",
    ko: "팔로우 중인 인플루언서가 각자의 말로 최근에 한 이야기",
  },
  // `nav.page./backfill.*` removed with the nav entry -- `/backfill` is now a redirect into the
  // Personas page's backfill panel. That panel's button is `backfill.personasToggle`.

  // --- Market --------------------------------------------------------------
  "nav.page./symbol.label": { en: "Symbol", ko: "종목" },
  "nav.page./symbol.blurb": {
    en: "Chart, decision, report, holders and news for one symbol",
    ko: "한 종목의 차트, 판정, 리포트, 보유 기관, 뉴스",
  },
  "nav.page./filers.label": { en: "Filers", ko: "보고 기관" },
  "nav.page./filers.blurb": { en: "13F holdings and filer consensus", ko: "13F 보유 종목과 기관 컨센서스" },
  // Ticker/Report merged into `/symbol`, Institutions/Consensus into `/filers` (see `nav.ts`); the
  // four keys below stay, unreferenced by `NAV` but harmless, per this file's convention of never
  // deleting translated copy a deep link (now a redirect) might still pass through.
  "nav.page./ticker.label": { en: "Ticker", ko: "종목" },
  "nav.page./ticker.blurb": {
    en: "Charts, indicators and the decision table",
    ko: "차트, 지표, 판정 표",
  },
  "nav.page./report.label": { en: "Report", ko: "리포트" },
  "nav.page./report.blurb": { en: "Grounded per-symbol research", ko: "근거 기반 종목별 리서치" },
  "nav.page./institutions.label": { en: "Institutions", ko: "기관" },
  "nav.page./institutions.blurb": { en: "13F holdings and period deltas", ko: "13F 보유 종목과 기간 변동" },
  "nav.page./consensus.label": { en: "Consensus", ko: "컨센서스" },
  "nav.page./consensus.blurb": {
    en: "What filers are buying and selling together",
    ko: "보고 기관들이 함께 매수·매도하는 종목",
  },
  "nav.page./macro.label": { en: "Macro", ko: "매크로" },
  "nav.page./macro.blurb": {
    en: "Rates, credit, volatility and sentiment",
    ko: "금리, 신용, 변동성, 심리",
  },

  // --- Data ----------------------------------------------------------------
  "nav.page./data.label": { en: "Data", ko: "데이터" },
  "nav.page./data.blurb": {
    en: "Import, reconcile, and administer the data this application runs on",
    ko: "이 애플리케이션이 사용하는 데이터를 가져오고, 대조하고, 관리합니다",
  },
} as const satisfies MessageShard;
