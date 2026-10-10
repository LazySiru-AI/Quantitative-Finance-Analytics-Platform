/**
 * Shared presentational atoms for the persona surfaces: confidence intervals, instrument
 * badges, citation lists.
 *
 * Owned by the atoms worker. Prefix `personaAtoms.` -- see `catalog.ts` for the convention.
 */
import type { MessageShard } from "@/i18n/types";

export const personaAtoms = {
  "personaAtoms.statValue.noData": { en: "no data", ko: "데이터 없음" },
  "personaAtoms.statValue.pointOnly": { en: "{point} (n={n})", ko: "{point} (n={n})" },
  "personaAtoms.statValue.withCi": {
    en: "{point} (n={n}, {confidence}% CI {low}–{high})",
    ko: "{point} (n={n}, 신뢰구간 {confidence}% {low}–{high})",
  },
  "personaAtoms.instrumentBadge.etf": { en: "ETF", ko: "ETF" },
  "personaAtoms.instrumentBadge.index": { en: "Index", ko: "지수" },
  "personaAtoms.instrumentBadge.future": { en: "Future", ko: "선물" },
  "personaAtoms.instrumentBadge.crypto": { en: "Crypto", ko: "암호화폐" },
  "personaAtoms.instrumentBadge.fx": { en: "FX", ko: "외환" },
  "personaAtoms.instrumentBadge.unknown": { en: "Unknown", ko: "알 수 없음" },
  "personaAtoms.instrumentBadge.detail": {
    en: "Not directly tradeable by the strategy layer",
    ko: "전략 레이어에서 직접 거래할 수 없는 상품입니다",
  },
  "personaAtoms.citationList.ariaLabel": { en: "Citations", ko: "출처" },
  "personaAtoms.citationList.selectAria": {
    en: "Show source {noteId}",
    ko: "출처 {noteId} 보기",
  },
} as const satisfies MessageShard;
