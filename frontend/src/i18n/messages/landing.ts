/**
 * Copy for the two section landing pages, `pages/StrategyLanding.tsx` and
 * `pages/AgentDeskLanding.tsx` -- the "front door" each rail section opens on now that
 * `section.items[0]` points at a landing rather than straight at a working page.
 *
 * Both pages share one shard because neither is big enough to earn its own file, and splitting a
 * ~20-key page into its own module would run against this file's actual job: giving each landing a
 * place to keep its subtitle, funnel labels and "try this" cards next to each other for review.
 */
import type { MessageShard } from "@/i18n/types";

export const landing = {
  // --- Strategy Lab landing --------------------------------------------------------------------
  "landing.strategy.subtitle": {
    en: "Where trading ideas are tested against history before any money follows them",
    ko: "실제 자금을 투입하기 전에 매매 아이디어를 과거 데이터로 검증하는 곳",
  },
  "landing.strategy.verdictPill": { en: "No durable edge", ko: "지속적 우위 없음" },
  "landing.strategy.verdict": {
    en: "No durable out-of-sample edge across 33 rounds, a 9,480-cell timeframe sweep and 291 loop generations.",
    ko: "33개 라운드, 9,480칸 타임프레임 스윕, 291세대 루프 전반에서 검증 표본 밖 지속적 우위는 발견되지 않았습니다.",
  },
  "landing.strategy.funnel.heading": { en: "How an idea moves through the lab", ko: "아이디어가 실험실을 통과하는 과정" },
  "landing.strategy.funnel.rules": { en: "Rules", ko: "규칙" },
  "landing.strategy.funnel.evidence": { en: "Evidence", ko: "근거" },
  "landing.strategy.funnel.competition": { en: "Competition", ko: "컴페티션" },
  "landing.strategy.funnel.paperDesk": { en: "Paper Desk", ko: "페이퍼 데스크" },
  "landing.strategy.counts.rules": { en: "Rules in catalog", ko: "카탈로그 규칙 수" },
  "landing.strategy.counts.rounds": { en: "Rounds run", ko: "실행된 라운드 수" },
  "landing.strategy.tryThis.heading": { en: "Try this", ko: "먼저 해볼 것" },
  "landing.strategy.card.testRule.title": { en: "Test one rule on one symbol", ko: "종목 하나에 규칙 하나 테스트하기" },
  "landing.strategy.card.testRule.blurb": {
    en: "Run a rule's evidence against a single ticker's own history.",
    ko: "한 종목의 과거 데이터로 규칙의 근거를 확인합니다.",
  },
  "landing.strategy.card.lastRound.title": {
    en: "Read the last round's findings",
    ko: "지난 라운드 결과 확인하기",
  },
  "landing.strategy.card.lastRound.blurb": {
    en: "Open the leaderboard and see what the most recent round actually showed.",
    ko: "리더보드를 열어 가장 최근 라운드의 실제 결과를 확인합니다.",
  },
  "landing.strategy.card.promotedCard.title": { en: "Review a promoted card", ko: "승격된 카드 검토하기" },
  "landing.strategy.card.promotedCard.blurb": {
    en: "Check a promoted strategy card against the record before trusting it.",
    ko: "승격된 전략 카드를 신뢰하기 전에 기록과 대조해 봅니다.",
  },

  // --- Agent Desk landing -----------------------------------------------------------------------
  "landing.agents.subtitle": {
    en: "Model-run research desks, checked against our own data, not taken on faith",
    ko: "우리 데이터로 검증하는 모델 기반 리서치 데스크, 그대로 믿지 않습니다",
  },
  "landing.agents.pill.available": { en: "Agents online", ko: "에이전트 온라인" },
  "landing.agents.pill.unavailable": { en: "Agents offline", ko: "에이전트 오프라인" },
  "landing.agents.pill.unknown": { en: "Unknown", ko: "알 수 없음" },
  "landing.agents.line.available": {
    en: "The agent layer is reachable — a run can start now.",
    ko: "에이전트 레이어에 연결되어 있습니다 — 지금 실행을 시작할 수 있습니다.",
  },
  "landing.agents.line.unavailable": { en: "Agent layer unavailable: {reason}", ko: "에이전트 레이어 사용 불가: {reason}" },
  "landing.agents.line.unknown": {
    en: "Could not check whether the agent layer is available.",
    ko: "에이전트 레이어 사용 가능 여부를 확인하지 못했습니다.",
  },
  "landing.agents.funnel.heading": { en: "How a run moves through a desk", ko: "실행이 데스크를 통과하는 과정" },
  "landing.agents.funnel.ask": { en: "Ask", ko: "질문" },
  "landing.agents.funnel.orchestrate": { en: "Orchestrate", ko: "오케스트레이션" },
  "landing.agents.funnel.measure": { en: "Measure", ko: "측정" },
  "landing.agents.funnel.follow": { en: "Follow", ko: "추적" },
  "landing.agents.tryThis.heading": { en: "Try this", ko: "먼저 해볼 것" },
  "landing.agents.card.researchTicker.title": { en: "Research one ticker", ko: "종목 하나 리서치하기" },
  "landing.agents.card.researchTicker.blurb": {
    en: "Run the full analyst-to-portfolio-manager pipeline on a single symbol.",
    ko: "한 종목에 대해 애널리스트–포트폴리오 매니저 전체 파이프라인을 실행합니다.",
  },
  "landing.agents.card.askCommittee.title": { en: "Ask a committee", ko: "위원회에 질문하기" },
  "landing.agents.card.askCommittee.blurb": {
    en: "Run a preset desk of role agents on a question, as a DAG.",
    ko: "역할 에이전트로 구성된 프리셋 데스크에 질문을 DAG로 실행합니다.",
  },
  "landing.agents.card.runWorkflow.title": { en: "Run the workflow", ko: "워크플로 실행하기" },
  "landing.agents.card.runWorkflow.blurb": {
    en: "Regime through next-open execution, measured against single-tool arms.",
    ko: "국면 판단부터 다음 시가 실행까지, 단일 도구 그룹과 비교 측정합니다.",
  },
} as const satisfies MessageShard;
