/**
 * Persona chronological timeline: the dated feed of what they said, and per-symbol
 * stance evolution.
 *
 * Prefix `personaTimeline.` -- see `catalog.ts` for the convention.
 */
import type { MessageShard } from "@/i18n/types";

export const personaTimeline = {
  "personaTimeline.heading": { en: "Timeline", ko: "타임라인" },
  "personaTimeline.caption": {
    en: "{name}'s notes in the order they were made — descriptive only, not advice.",
    ko: "{name}의 노트를 작성 순서대로 나열합니다 — 서술적 기록일 뿐, 조언이 아닙니다.",
  },
  "personaTimeline.loading": { en: "Loading timeline...", ko: "타임라인을 불러오는 중..." },
  "personaTimeline.empty": {
    en: "Nothing on the timeline yet.",
    ko: "아직 타임라인에 표시할 내용이 없습니다.",
  },
  "personaTimeline.stanceHeading": { en: "Stance evolution", ko: "관점 변화" },
  "personaTimeline.feedHeading": { en: "Dated feed", ko: "일자별 피드" },
  "personaTimeline.stanceChangedBadge": { en: "Stance changed", ko: "관점 변경됨" },
  "personaTimeline.dateUnknown": { en: "date unknown", ko: "날짜 미상" },
  "personaTimeline.untitled": { en: "Untitled note", ko: "제목 없는 노트" },
  "personaTimeline.openSource": { en: "Open source", ko: "원문 보기" },
} as const satisfies MessageShard;
