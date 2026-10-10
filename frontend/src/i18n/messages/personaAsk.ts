/**
 * Ask-the-persona and the persona's critique of a strategy card. Both are a model's
 * impression of the influencer, never the person speaking and never advice.
 *
 * Prefix `personaAsk.` -- see `catalog.ts` for the convention.
 */
import type { MessageShard } from "@/i18n/types";

export const personaAsk = {
  // --- ask panel -------------------------------------------------------------------------------
  "personaAsk.ask.heading": { en: "Ask {name}", ko: "{name}에게 묻기" },
  "personaAsk.ask.caveatLabel": {
    en: "A model's impression of {name}, from cited notes -- not {name} speaking, and never investment advice.",
    ko: "인용된 노트를 바탕으로 한 모델의 {name} 인상입니다 -- {name} 본인의 발언이 아니며, 투자 조언도 아닙니다.",
  },
  "personaAsk.ask.questionLabel": { en: "Question", ko: "질문" },
  "personaAsk.ask.questionPlaceholder": {
    en: "What would {name} think about...",
    ko: "{name}은(는) 어떻게 생각할까요...",
  },
  "personaAsk.ask.symbolLabel": { en: "Ticker (optional)", ko: "티커 (선택)" },
  "personaAsk.ask.symbolPlaceholder": { en: "e.g. AAPL", ko: "예: AAPL" },
  "personaAsk.ask.submit": { en: "Ask", ko: "질문하기" },
  "personaAsk.ask.pending": { en: "Asking {name}...", ko: "{name}에게 묻는 중..." },
  "personaAsk.ask.idleHint": {
    en: "Ask a question to see {name}'s cited impression here.",
    ko: "질문을 입력하면 {name}의 인용 기반 인상이 여기에 표시됩니다.",
  },
  "personaAsk.ask.stanceLabel": { en: "Stance", ko: "입장" },
  "personaAsk.ask.groundingWarning": { en: "Fact-check failed", ko: "사실 확인 실패" },
  "personaAsk.ask.groundingDetail_one": {
    en: "Shown despite failing its fact-check after {attempts} attempt.",
    ko: "{attempts}번 시도 후 사실 확인에 실패했지만 그대로 표시합니다.",
  },
  "personaAsk.ask.groundingDetail_other": {
    en: "Shown despite failing its fact-check after {attempts} attempts.",
    ko: "{attempts}번 시도 후 사실 확인에 실패했지만 그대로 표시합니다.",
  },

  // --- critique panel ----------------------------------------------------------------------------
  "personaAsk.critique.heading": { en: "Ask {name} to critique this card", ko: "{name}에게 카드 평가 요청" },
  "personaAsk.critique.caveatLabel": {
    en: "A model's impression of how {name} would critique this card, from cited notes -- not them speaking, and never advice.",
    ko: "인용된 노트를 바탕으로 {name}이(가) 이 카드를 어떻게 평가할지에 대한 모델의 인상입니다 -- 본인의 발언이 아니며 조언이 아닙니다.",
  },
  "personaAsk.critique.trigger": { en: "Ask for a critique", ko: "평가 요청하기" },
  "personaAsk.critique.pending": { en: "Asking {name}...", ko: "{name}에게 묻는 중..." },
  "personaAsk.critique.disabledExplain": { en: "No card to critique yet.", ko: "아직 평가할 카드가 없습니다." },
  "personaAsk.critique.idleHint": {
    en: "Ask for a critique to see {name}'s cited take on this card.",
    ko: "평가를 요청하면 이 카드에 대한 {name}의 인용 기반 의견이 표시됩니다.",
  },
  "personaAsk.critique.verdictHeading": { en: "Verdict", ko: "평가 결과" },
  "personaAsk.critique.verdict.aligned": { en: "Aligned", ko: "부합" },
  "personaAsk.critique.verdict.mixed": { en: "Mixed", ko: "혼재" },
  "personaAsk.critique.verdict.misaligned": { en: "Misaligned", ko: "불일치" },
  "personaAsk.critique.verdict.cannotSay": { en: "Cannot say", ko: "판단 불가" },
} as const satisfies MessageShard;
