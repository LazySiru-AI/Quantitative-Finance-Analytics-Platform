/**
 * Persona Chat -- the multi-turn successor to the old single-shot "Ask the persona" panel
 * (`personaAsk.ask.*`, still in `messages/personaAsk.ts` for `PersonaCritique.tsx`'s own critique
 * keys). Same guardrails as that panel, extended for multiple threads and turns: a model's cited
 * impression of the influencer, never the person speaking and never investment advice -- see
 * `personaChat.caveat`, rendered always-visible, never behind a disclosure.
 *
 * Prefix `personaChat.` -- see `catalog.ts` for the convention.
 */
import type { MessageShard } from "@/i18n/types";

export const personaChat = {
  // --- header / caveat --------------------------------------------------------------------------
  "personaChat.heading": { en: "Chat with {name}", ko: "{name}(와/과) 채팅" },
  // LANG-03: the canonical "not them speaking / not advice" wording, shared with the manager and
  // trader surfaces. Always visible, never behind a disclosure -- COPY-STYLE.md rule 6.
  "personaChat.caveat": {
    en: "A model's impression from cited notes — not {name}, not advice.",
    ko: "인용된 노트를 바탕으로 한 모델의 추정입니다 — {name} 본인이 아니며 조언도 아닙니다.",
  },

  // EXP-04: what leaves this machine when a turn is sent. Visible one-liner, not a disclosure.
  "personaChat.egress": {
    en: "Your message and the cited notes are sent to the model provider.",
    ko: "메시지와 인용된 노트가 모델 제공자에게 전송됩니다.",
  },

  // --- stale-profile note ------------------------------------------------------------------------
  "personaChat.staleNever": {
    en: "No strategy profile yet -- consolidate {name}'s notes so the chat can draw on them.",
    ko: "아직 전략 프로필이 없습니다 -- {name}의 노트를 통합하면 채팅이 이를 참고할 수 있습니다.",
  },
  "personaChat.staleBehind": {
    en: "Profile built from {built} of {total} videos.",
    ko: "프로필은 영상 {total}개 중 {built}개로 작성되었습니다.",
  },
  "personaChat.consolidate": { en: "Consolidate", ko: "통합하기" },
  "personaChat.consolidating": { en: "Consolidating…", ko: "통합 중…" },

  // --- thread bar ----------------------------------------------------------------------------------
  "personaChat.newThread": { en: "New chat", ko: "새 대화" },
  "personaChat.untitledThread": { en: "Untitled chat", ko: "제목 없는 대화" },
  "personaChat.deleteThread": { en: "Delete chat", ko: "대화 삭제" },
  // Same rule as `manager.thread.deleteConfirm.*` (EXP-24): a one-click destroy confirms first, and
  // the sheet's confirm is worded differently from the control that opened it.
  "personaChat.deleteConfirm.title": { en: "Delete this chat?", ko: "이 대화를 삭제할까요?" },
  "personaChat.deleteConfirm.body": {
    en: "Removes the whole transcript from this machine. It cannot be undone.",
    ko: "이 컴퓨터에서 대화 전체를 삭제합니다. 되돌릴 수 없습니다.",
  },
  "personaChat.deleteConfirm.confirm": { en: "Yes, delete", ko: "예, 삭제" },
  "personaChat.threadSelectLabel": { en: "Conversation", ko: "대화 선택" },

  // --- transcript ------------------------------------------------------------------------------------
  "personaChat.youAsked": { en: "You asked", ko: "질문" },
  "personaChat.factCheckFailed": { en: "Fact-check failed", ko: "사실 확인 실패" },
  "personaChat.groundingDetail_one": {
    en: "Shown despite failing its fact-check after {attempts} attempt.",
    ko: "{attempts}번 시도 후 사실 확인에 실패했지만 그대로 표시합니다.",
  },
  "personaChat.groundingDetail_other": {
    en: "Shown despite failing its fact-check after {attempts} attempts.",
    ko: "{attempts}번 시도 후 사실 확인에 실패했지만 그대로 표시합니다.",
  },
  "personaChat.stanceLabel": { en: "Stance", ko: "입장" },
  "personaChat.turnCost": { en: "Cost: ${cost}", ko: "비용: ${cost}" },
  "personaChat.pending": { en: "{name} is thinking…", ko: "{name}(이)가 생각하는 중…" },

  // --- suggested questions (empty thread) --------------------------------------------------------
  "personaChat.suggest.strategy": { en: "What's their overall strategy?", ko: "전반적인 전략은 무엇인가요?" },
  "personaChat.suggest.indicators": {
    en: "Which indicators do they rely on?",
    ko: "어떤 지표를 활용하나요?",
  },
  "personaChat.suggest.caution": {
    en: "What would make them cautious right now?",
    ko: "지금 조심스러워질 만한 요인은 무엇인가요?",
  },
  "personaChat.suggest.macro": { en: "What's their macro view?", ko: "매크로 관점은 무엇인가요?" },
  "personaChat.suggest.recent": { en: "What have they said recently?", ko: "최근에 어떤 이야기를 했나요?" },
  "personaChat.suggest.changed": {
    en: "What's changed in their thinking?",
    ko: "생각이 어떻게 바뀌었나요?",
  },

  // --- composer --------------------------------------------------------------------------------------
  "personaChat.send": { en: "Send", ko: "보내기" },
  "personaChat.questionLabel": { en: "Question", ko: "질문" },
  "personaChat.questionPlaceholder": {
    en: "Ask {name} something…",
    ko: "{name}에게 궁금한 점을 물어보세요…",
  },
  "personaChat.symbolLabel": { en: "Ticker (optional)", ko: "티커 (선택)" },
  "personaChat.symbolPlaceholder": { en: "e.g. AAPL", ko: "예: AAPL" },
} as const satisfies MessageShard;
