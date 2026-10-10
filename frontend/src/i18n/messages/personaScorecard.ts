/**
 * Persona call scorecard: fixed-horizon columns (5/20/60 trading days), confidence
 * intervals, and the SPY-benchmarked backtest lens.
 *
 * Prefix `personaScorecard.` -- see `catalog.ts` for the convention. Existing scorecard copy
 * (heading, caption, aggregate hit-rate/median-return labels, empty state) stays in the
 * `misc.personas.scorecard.*` shard -- only the NEW fixed-horizon and backtest-lens strings live
 * here.
 */
import type { MessageShard } from "@/i18n/types";

export const personaScorecard = {
  // --- fixed-horizon summary (PersonaScorecard.tsx) -------------------------------------------
  "personaScorecard.horizon.heading": { en: "By horizon", ko: "기간별" },
  "personaScorecard.horizon.caption": {
    en: "Fixed windows after entry, so calls made on different days are comparable.",
    ko: "진입 후 고정된 기간이라 서로 다른 날짜의 콜도 비교할 수 있습니다.",
  },
  "personaScorecard.horizon.label": { en: "{days}d", ko: "{days}일" },
  "personaScorecard.horizon.hitRate": { en: "Hit rate", ko: "적중률" },
  "personaScorecard.horizon.medianReturn": { en: "Median return", ko: "수익률 중앙값" },
  "personaScorecard.horizon.meanReturn": { en: "Mean return", ko: "평균 수익률" },
  "personaScorecard.horizon.noData": { en: "Not enough data yet", ko: "데이터가 아직 충분하지 않습니다" },
  "personaScorecard.horizon.tooRecent": { en: "too recent", ko: "너무 최근" },
  "personaScorecard.aggregate.hitRateCiLabel": { en: "Confidence interval", ko: "신뢰구간" },

  // --- backtest lens (PersonaBacktest.tsx) ----------------------------------------------------
  "personaScorecard.backtest.heading": { en: "Backtest lens", ko: "백테스트 렌즈" },
  "personaScorecard.backtest.caption": {
    en: "{name}'s calls vs {benchmark} — descriptive only, not a performance claim or advice.",
    ko: "{name}의 콜을 {benchmark}와 비교한 서술적 기록일 뿐, 성과 주장이나 조언이 아닙니다.",
  },
  "personaScorecard.backtest.loading": { en: "Loading backtest…", ko: "백테스트 불러오는 중…" },
  "personaScorecard.backtest.empty": {
    en: "No scored calls yet to benchmark against {benchmark}.",
    ko: "{benchmark}와 비교할 채점된 콜이 아직 없습니다.",
  },
  "personaScorecard.backtest.callCount": { en: "{count} calls scored", ko: "채점된 콜 {count}건" },
  "personaScorecard.backtest.caveatLabel": { en: "Caveat", ko: "유의사항" },
  "personaScorecard.backtest.excessReturn": { en: "Excess vs {benchmark}", ko: "{benchmark} 대비 초과수익" },
  "personaScorecard.backtest.meanReturn": { en: "Mean call return", ko: "콜 평균 수익률" },
  "personaScorecard.backtest.meanBenchmark": { en: "Mean {benchmark} return", ko: "{benchmark} 평균 수익률" },
  "personaScorecard.backtest.winRate": { en: "Win rate vs {benchmark}", ko: "{benchmark} 대비 승률" },
  "personaScorecard.backtest.sampleSize": { en: "n={n} calls", ko: "n={n}건" },
  "personaScorecard.backtest.noData": { en: "no data", ko: "데이터 없음" },
} as const satisfies MessageShard;
