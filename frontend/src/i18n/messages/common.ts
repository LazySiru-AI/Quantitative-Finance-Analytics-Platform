/**
 * Strings that more than one page needs: loading and empty states, generic table chrome, the verbs
 * on buttons, and the status vocabularies the backend sends as bare enum values.
 *
 * Anything used by exactly one page belongs in that page's shard instead. A `common` key that only
 * one caller reads is a key nobody will remember to update when that caller's wording changes.
 */
import type { MessageShard } from "@/i18n/types";

export const common = {
  // --- state ---------------------------------------------------------------
  "common.loading": { en: "Loading…", ko: "불러오는 중…" },
  "common.error": { en: "Error", ko: "오류" },
  "common.retry": { en: "Retry", ko: "다시 시도" },
  // --- the four sentences every page was writing for itself ------------------
  // Measured 2026-09-05: "Could not load ..." existed 53 times across 9 shards, the API-status
  // sentence 9 times, the unreachable-API sentence 8 times. They are not per-page facts -- a
  // fetch that fails on the Tax page fails for the same reason it fails on Macro, and a reader who
  // has learned one wording should not have to learn eight. `{what}` carries the page's noun so
  // the sentence stays one key; the Korean takes the same particle-agnostic `을(를)` shape the
  // account and status sentences already use.
  "common.apiError": {
    en: "API returned {status}: {message}",
    ko: "API가 {status}을(를) 반환했습니다: {message}",
  },
  "common.cannotReachApi": {
    en: "Cannot reach the API. Is uvicorn running on port 8000?",
    ko: "API에 연결할 수 없습니다. 8000번 포트에서 uvicorn이 실행 중인가요?",
  },
  "common.couldNotLoad": {
    en: "Could not load {what}.",
    ko: "{what}을(를) 불러오지 못했습니다.",
  },
  "common.couldNotLoadThis": { en: "Could not load this.", ko: "불러오지 못했습니다." },
  "common.loadingWhat": { en: "Loading {what}…", ko: "{what} 불러오는 중…" },
  "common.refresh": { en: "Refresh", ko: "새로고침" },
  "common.empty": { en: "Nothing to show", ko: "표시할 항목이 없습니다" },
  "common.notFound": { en: "Not found", ko: "찾을 수 없음" },
  "common.none": { en: "None", ko: "없음" },
  "common.unknown": { en: "Unknown", ko: "알 수 없음" },
  "common.all": { en: "All", ko: "전체" },
  "common.total": { en: "Total", ko: "합계" },
  "common.showMore": { en: "Show more", ko: "더 보기" },
  "common.showLess": { en: "Show less", ko: "간략히 보기" },
  "common.close": { en: "Close", ko: "닫기" },
  "common.cancel": { en: "Cancel", ko: "취소" },
  "common.save": { en: "Save", ko: "저장" },
  "common.apply": { en: "Apply", ko: "적용" },
  "common.run": { en: "Run", ko: "실행" },
  "common.search": { en: "Search", ko: "검색" },
  "common.copy": { en: "Copy", ko: "복사" },
  "common.copied": { en: "Copied", ko: "복사됨" },
  "common.export": { en: "Export", ko: "내보내기" },
  "common.download": { en: "Download", ko: "다운로드" },
  "common.recentRuns": { en: "Recent runs", ko: "최근 실행" },
  "common.finalReport": { en: "Final report", ko: "최종 리포트" },
  "common.budgetCapUsd": { en: "Budget cap (USD)", ko: "예산 상한 (USD)" },

  // --- generic table and figure chrome -------------------------------------
  "common.symbol": { en: "Symbol", ko: "종목" },
  "common.date": { en: "Date", ko: "날짜" },
  "common.time": { en: "Time", ko: "시각" },
  "common.price": { en: "Price", ko: "가격" },
  "common.quantity": { en: "Quantity", ko: "수량" },
  "common.value": { en: "Value", ko: "금액" },
  "common.weight": { en: "Weight", ko: "비중" },
  "common.change": { en: "Change", ko: "변동" },
  "common.status": { en: "Status", ko: "상태" },
  "common.source": { en: "Source", ko: "출처" },
  "common.notes": { en: "Notes", ko: "메모" },
  "common.action": { en: "Action", ko: "작업" },
  "common.name": { en: "Name", ko: "이름" },
  "common.count": { en: "Count", ko: "개수" },
  "common.asOf": { en: "As of {date}", ko: "{date} 기준" },
  "common.updated": { en: "Updated {when}", ko: "{when} 업데이트" },

  // --- trading vocabulary --------------------------------------------------
  "common.buy": { en: "Buy", ko: "매수" },
  "common.sell": { en: "Sell", ko: "매도" },
  "common.long": { en: "Long", ko: "롱" },
  "common.short": { en: "Short", ko: "숏" },
  "common.cash": { en: "Cash", ko: "현금" },
  "common.equity": { en: "Equity", ko: "자산 총액" },
  "common.shares": { en: "Shares", ko: "주식 수" },
  "common.realised": { en: "Realized", ko: "실현" },
  "common.unrealised": { en: "Unrealized", ko: "미실현" },
  "common.gainLoss": { en: "Gain / loss", ko: "손익" },

  // --- backend enum vocabularies (tier A: translated on the frontend) -------
  "status.pending": { en: "Pending", ko: "대기" },
  "status.filled": { en: "Filled", ko: "체결됨" },
  "status.rejected": { en: "Rejected", ko: "거부됨" },
  "status.cancelled": { en: "Cancelled", ko: "취소됨" },
  "status.expired": { en: "Expired", ko: "만료됨" },
  "status.queued": { en: "Queued", ko: "대기열" },
  "status.running": { en: "Running", ko: "실행 중" },
  "status.succeeded": { en: "Succeeded", ko: "성공" },
  "status.failed": { en: "Failed", ko: "실패" },
  "status.idle": { en: "Idle", ko: "대기 중" },
  "status.stopped": { en: "Stopped", ko: "중지됨" },

  // --- provenance ----------------------------------------------------------
  // Shown beside model-written text that is still stored and displayed in English. Phase 4 of the
  // plan may translate that text; until then the badge marks the boundary honestly rather than
  // leaving a reader to wonder why one paragraph stayed in English.
  "common.sourceEnglish": { en: "Original (English)", ko: "원문 (영어)" },
  "common.sourceEnglishTitle": {
    en: "Written by a model in English and shown unchanged.",
    ko: "모델이 영어로 작성한 원문을 그대로 표시합니다.",
  },
  // Phase 4: shown instead of the badge above when the backend did supply a Korean translation of
  // the same model-written English prose -- see `@/i18n/TranslatedProse`.
  "common.sourceMachineTranslated": { en: "Machine-translated", ko: "기계 번역" },
  "common.sourceMachineTranslatedTitle": {
    en: "Translated by a model from the English original; numbers are preserved but wording may differ.",
    ko: "영어 원문을 모델이 번역했습니다. 숫자는 보존되지만 표현은 다를 수 있습니다.",
  },
} as const satisfies MessageShard;
