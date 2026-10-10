/**
 * Cross-persona consensus views: the aggregated bullish watchlist and the risk-on/off
 * regime tally the macro commentators contribute.
 *
 * Prefix `personaConsensus.` -- see `catalog.ts` for the convention.
 */
import type { MessageShard } from "@/i18n/types";

export const personaConsensus = {
  "personaConsensus.watchlist.heading": { en: "Bullish Watchlist", ko: "강세 관심종목" },
  "personaConsensus.watchlist.subtitle": {
    en: "Symbols the followed influencers are currently bullish on.",
    ko: "팔로우한 인플루언서들이 현재 강세로 보는 종목입니다.",
  },
  "personaConsensus.watchlist.asOfInputLabel": { en: "As of", ko: "기준일" },
  "personaConsensus.watchlist.asOfNote": {
    en: "Showing the consensus as of {asOf}.",
    ko: "{asOf} 기준 컨센서스를 표시합니다.",
  },
  "personaConsensus.watchlist.loading": { en: "Loading the watchlist…", ko: "관심종목을 불러오는 중…" },
  "personaConsensus.watchlist.empty": {
    en: "No symbol has bullish backing from a followed influencer right now.",
    ko: "현재 팔로우한 인플루언서가 강세로 보는 종목이 없습니다.",
  },
  "personaConsensus.watchlist.filterPlaceholder": { en: "Filter by symbol", ko: "종목으로 필터링" },
  "personaConsensus.watchlist.noMatch": {
    en: "No symbol matches this filter.",
    ko: "이 필터와 일치하는 종목이 없습니다.",
  },
  "personaConsensus.watchlist.columnSymbol": { en: "Symbol", ko: "종목" },
  "personaConsensus.watchlist.columnBullish": { en: "Bullish", ko: "강세" },
  "personaConsensus.watchlist.columnBearish": { en: "Bearish", ko: "약세" },
  "personaConsensus.watchlist.columnBackers": { en: "Backers", ko: "지지 인플루언서" },
  "personaConsensus.watchlist.columnReasoning": { en: "Latest reasoning", ko: "최근 근거" },

  // --- EXP-08 provenance --------------------------------------------------------------------------
  // The reasoning column is model-written prose about named real people. It gets a marker saying so,
  // and each row carries the date of the note it came from. The wire has no source URL or video id
  // on a watchlist entry, so no link is offered -- an invented one would be worse than none.
  "personaConsensus.pill.modelSummary": { en: "Model summary", ko: "모델 요약" },
  "personaConsensus.watchlist.summaryNote": {
    en: "Summarised by a model from each backer's dated note — not a quote, not their position.",
    ko: "각 지지자의 날짜별 노트를 모델이 요약한 것입니다 — 인용문도, 실제 포지션도 아닙니다.",
  },
  "personaConsensus.watchlist.noteDated": { en: "Note dated {date}", ko: "{date} 노트" },
  "personaConsensus.watchlist.noteUndated": { en: "No note date", ko: "노트 날짜 없음" },
  "personaConsensus.watchlist.asOfUnknown": { en: "Unknown", ko: "알 수 없음" },

  "personaConsensus.regime.heading": { en: "Risk Regime Consensus", ko: "리스크 레짐 컨센서스" },
  "personaConsensus.regime.subtitle": {
    en: "How many followed macro commentators lean risk-on vs. risk-off.",
    ko: "팔로우한 매크로 해설자들의 리스크 온/오프 성향 집계입니다.",
  },
  "personaConsensus.regime.loading": { en: "Loading the regime consensus…", ko: "레짐 컨센서스를 불러오는 중…" },
  "personaConsensus.regime.empty": {
    en: "No persona has offered a regime view yet.",
    ko: "아직 레짐 견해를 제시한 페르소나가 없습니다.",
  },
  "personaConsensus.regime.riskOn": { en: "Leaning risk-on", ko: "리스크 온 성향" },
  "personaConsensus.regime.riskOff": { en: "Leaning risk-off", ko: "리스크 오프 성향" },
  "personaConsensus.regime.mixed": { en: "Mixed signals", ko: "혼재 신호" },
  "personaConsensus.regime.postureOn": { en: "Risk-on", ko: "리스크 온" },
  "personaConsensus.regime.postureOff": { en: "Risk-off", ko: "리스크 오프" },
  "personaConsensus.regime.postureMixed": { en: "Mixed", ko: "혼재" },
  "personaConsensus.regime.postureUnclear": { en: "Unclear", ko: "불분명" },
  "personaConsensus.regime.ratesLabel": { en: "Rates:", ko: "금리:" },
  "personaConsensus.regime.favoured": { en: "Sectors favoured:", ko: "선호 섹터:" },
  "personaConsensus.regime.avoided": { en: "Sectors avoided:", ko: "회피 섹터:" },
  "personaConsensus.regime.noView": {
    en: "No regime view from this persona.",
    ko: "이 페르소나의 레짐 견해가 없습니다.",
  },
} as const satisfies MessageShard;
