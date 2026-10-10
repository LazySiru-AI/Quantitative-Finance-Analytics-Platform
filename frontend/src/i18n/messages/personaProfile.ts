/**
 * The consolidated persona profile surfaces: methodology ("how they trade"), the regime
 * view, profile drift between versions, and the drafted strategy card.
 *
 * Prefix `personaProfile.` -- see `catalog.ts` for the convention.
 */
import type { MessageShard } from "@/i18n/types";

export const personaProfile = {
  // --- methodology ("how they trade") -- PersonaProfile.tsx -----------------------------------
  // NOTE: not "How they trade" -- `misc.personas.profile.playbook` already owns that exact copy for
  // the strategic what-they-do section. "Methodology" is the mechanical HOW (named indicators,
  // timeframes, entry/exit triggers) -- see `PersonaProfile` (@/api/personas)'s own docstring on the
  // playbook/methodology split.
  "personaProfile.methodology.heading": { en: "Methodology", ko: "방법론" },

  // --- regime view -- PersonaProfile.tsx -------------------------------------------------------
  "personaProfile.regime.heading": { en: "Regime view", ko: "국면 진단" },
  "personaProfile.regime.riskPosture": { en: "Risk posture: {risk}", ko: "리스크 태도: {risk}" },
  "personaProfile.regime.risk.on": { en: "Risk-on", ko: "리스크 온" },
  "personaProfile.regime.risk.off": { en: "Risk-off", ko: "리스크 오프" },
  "personaProfile.regime.risk.mixed": { en: "Mixed", ko: "혼재" },
  "personaProfile.regime.risk.unclear": { en: "No clear stance", ko: "명확한 입장 없음" },
  "personaProfile.regime.rates": { en: "Rates: {rates}", ko: "금리: {rates}" },
  "personaProfile.regime.sectorsFavoured": { en: "Sectors favoured", ko: "선호 섹터" },
  "personaProfile.regime.sectorsAvoided": { en: "Sectors avoided", ko: "회피 섹터" },

  // --- strategy card draft -- PersonaStrategyCard.tsx ------------------------------------------
  "personaProfile.strategyCard.heading": { en: "Drafted strategy", ko: "초안 전략 카드" },
  "personaProfile.strategyCard.idleHint": {
    en: "Maps {name}'s methodology onto a rule-based strategy card, as an exploration lens.",
    ko: "{name}의 매매 방식을 규칙 기반 전략 카드로 옮겨보는 탐색용 렌즈입니다.",
  },
  "personaProfile.strategyCard.draftButton": {
    en: "Draft a strategy from their method",
    ko: "매매 방식으로 전략 초안 만들기",
  },
  "personaProfile.strategyCard.drafting": { en: "Drafting…", ko: "초안 작성 중…" },
  "personaProfile.strategyCard.promote.button": { en: "Promote to library", ko: "라이브러리에 추가" },
  "personaProfile.strategyCard.promote.promoting": { en: "Promoting…", ko: "추가 중…" },
  "personaProfile.strategyCard.promote.done": { en: "Added to the library", ko: "라이브러리에 추가됨" },
  "personaProfile.strategyCard.promote.exists": { en: "Already on the shelf", ko: "이미 라이브러리에 있음" },
  "personaProfile.strategyCard.promote.errorLabel": { en: "Could not promote", ko: "추가하지 못함" },
  "personaProfile.strategyCard.versionBadge": { en: "v{version}", ko: "v{version}" },
  "personaProfile.strategyCard.degradedTitle": { en: "Fact-check failed", ko: "사실 확인 실패" },
  "personaProfile.strategyCard.degradedBody": {
    en: "This draft was released despite failing the grounding check.",
    ko: "이 초안은 근거 확인을 통과하지 못했지만 그대로 공개되었습니다.",
  },
  "personaProfile.strategyCard.reasonLabel": { en: "Reason", ko: "사유" },
  "personaProfile.strategyCard.ruleShapeLabel": { en: "Rule shape", ko: "규칙 형태" },
  "personaProfile.strategyCard.cardHeading": { en: "Strategy card", ko: "전략 카드" },
  "personaProfile.strategyCard.rationaleLabel": { en: "Rationale", ko: "근거 설명" },
  "personaProfile.strategyCard.caveatLabel": { en: "Caveat", ko: "유의사항" },
  "personaProfile.strategyCard.fidelitySummary": {
    en: "Expresses {represented} of {total} techniques",
    ko: "기법 {total}개 중 {represented}개를 표현함",
  },
  "personaProfile.strategyCard.unrepresentableLabel": {
    en: "Not captured by the rule DSL",
    ko: "규칙 언어로 표현하지 못한 기법",
  },
  "personaProfile.strategyCard.historyHeading": { en: "Prior drafts", ko: "이전 초안" },
  "personaProfile.strategyCard.historyEmpty": { en: "No saved drafts yet", ko: "저장된 초안이 아직 없습니다" },

  // --- profile drift diff -- PersonaProfileDiff.tsx ----------------------------------------------
  "personaProfile.diff.heading": { en: "Profile drift", ko: "프로필 변화" },
  "personaProfile.diff.fromLabel": { en: "From version", ko: "시작 버전" },
  "personaProfile.diff.toLabel": { en: "To version", ko: "종료 버전" },
  "personaProfile.diff.selectPlaceholder": { en: "Select a version", ko: "버전 선택" },
  "personaProfile.diff.versionOption": { en: "v{version}", ko: "v{version}" },
  "personaProfile.diff.compareButton": { en: "Compare", ko: "비교" },
  "personaProfile.diff.idleHint": {
    en: "Pick two versions to see what changed between them.",
    ko: "두 버전을 선택하면 그 사이의 변화를 볼 수 있습니다.",
  },
  "personaProfile.diff.loading": { en: "Loading diff…", ko: "변화 내역 불러오는 중…" },
  "personaProfile.diff.versionRange": { en: "v{from} → v{to}", ko: "v{from} → v{to}" },
  "personaProfile.diff.counts": {
    en: "{added} added, {removed} removed, {recited} recited",
    ko: "추가 {added}건, 삭제 {removed}건, 재인용 {recited}건",
  },
  "personaProfile.diff.empty": {
    en: "No changes between these versions",
    ko: "두 버전 사이에 변화가 없습니다",
  },
  "personaProfile.diff.kind.added": { en: "Added", ko: "추가됨" },
  "personaProfile.diff.kind.removed": { en: "Removed", ko: "삭제됨" },
  "personaProfile.diff.kind.recited": { en: "Recited", ko: "재인용됨" },
  "personaProfile.diff.section.belief": { en: "Belief", ko: "믿음" },
  "personaProfile.diff.section.playbook": { en: "Playbook", ko: "실행 방식" },
  "personaProfile.diff.section.methodology": { en: "Methodology", ko: "매매 방식" },

  // --- PersonaDetail.tsx -- generic fetch/action error fallbacks -------------------------------
  // These are the `describePersonaActionError` fallback shown only when the server rejection
  // carries no usable `detail` string of its own (e.g. a network failure) -- the happy path always
  // prefers the server's own message. See `PersonaDetail.tsx`'s own fetch/handler effects.
  "personaProfile.detail.error.profileLoadFailed": {
    en: "Could not load this persona's profile.",
    ko: "이 페르소나의 프로필을 불러올 수 없습니다.",
  },
  "personaProfile.detail.error.unknownPersona": { en: "Unknown persona.", ko: "알 수 없는 페르소나입니다." },
  "personaProfile.detail.error.scorecardLoadFailed": {
    en: "Could not load this persona's scorecard.",
    ko: "이 페르소나의 스코어카드를 불러올 수 없습니다.",
  },
  "personaProfile.detail.error.timelineLoadFailed": {
    en: "Could not load this persona's timeline.",
    ko: "이 페르소나의 타임라인을 불러올 수 없습니다.",
  },
  "personaProfile.detail.error.backtestLoadFailed": {
    en: "Could not load this persona's backtest.",
    ko: "이 페르소나의 백테스트를 불러올 수 없습니다.",
  },
  "personaProfile.detail.error.consolidateFailed": {
    en: "Could not consolidate this persona.",
    ko: "이 페르소나를 통합할 수 없습니다.",
  },
  "personaProfile.detail.error.newChatFailed": {
    en: "Could not start a new chat.",
    ko: "새 대화를 시작할 수 없습니다.",
  },
  "personaProfile.detail.error.deleteChatFailed": {
    en: "Could not delete this chat.",
    ko: "이 대화를 삭제할 수 없습니다.",
  },
  "personaProfile.detail.error.chatTurnFailed": {
    en: "Could not get an answer from this persona.",
    ko: "이 페르소나로부터 답변을 받을 수 없습니다.",
  },
  "personaProfile.detail.error.draftStrategyFailed": {
    en: "Could not draft a strategy card for this persona.",
    ko: "이 페르소나의 전략 카드 초안을 작성할 수 없습니다.",
  },
  "personaProfile.detail.error.promoteFailed": {
    en: "Could not promote this card to the library.",
    ko: "이 카드를 라이브러리에 추가할 수 없습니다.",
  },
  "personaProfile.detail.error.critiqueFailed": {
    en: "Could not get this persona's critique.",
    ko: "이 페르소나의 평가를 받을 수 없습니다.",
  },
  "personaProfile.detail.error.profileDiffFailed": {
    en: "Could not compare these profile versions.",
    ko: "이 프로필 버전을 비교할 수 없습니다.",
  },
} as const satisfies MessageShard;
