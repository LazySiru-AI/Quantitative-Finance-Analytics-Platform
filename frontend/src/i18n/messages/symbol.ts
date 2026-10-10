/**
 * Symbol.tsx -- the merged Ticker + Report page (UX refactor 2.1).
 *
 * Only the strings unique to this page's own chrome (title, subtitle, tab labels) live here. The
 * mounted views (`TickerChartView`, `TickerDecisionView`, `ReportView`, `TickerHoldersView`,
 * `TickerNewsView`) and this page's symbol-bar form reuse the `ticker.*`/`market.report.*`/
 * `common.*` keys already shipped for them -- duplicating those here would only give the two pages
 * a chance to drift apart in wording.
 *
 * Keys are prefixed `symbol.` -- see `catalog.ts` for the convention.
 */
import type { MessageShard } from "@/i18n/types";

export const symbol = {
  "symbol.title": { en: "Symbol", ko: "종목" },
  "symbol.subtitle": {
    en: "Chart, decision table, report, holders and news for one symbol.",
    ko: "한 종목의 차트, 판정 표, 리포트, 보유자, 뉴스를 한 곳에서 확인합니다.",
  },

  // --- Tab rail ---------------------------------------------------------------
  "symbol.tabs.label": { en: "Symbol sections", ko: "종목 섹션" },
  "symbol.tabs.chart": { en: "Chart", ko: "차트" },
  "symbol.tabs.decision": { en: "Decision", ko: "판정" },
  "symbol.tabs.report": { en: "Report", ko: "리포트" },
  "symbol.tabs.holders": { en: "Holders", ko: "보유자" },
  "symbol.tabs.news": { en: "News", ko: "뉴스" },

  // --- Cross-links row (UX refactor 3.3) ---------------------------------------
  "symbol.quickLinks.researchDesk": { en: "Research Desk", ko: "리서치 데스크" },
  "symbol.quickLinks.paperDesk": { en: "Paper Desk", ko: "페이퍼 데스크" },
  "symbol.quickLinks.filers": { en: "Filers", ko: "공시 기관" },
} as const satisfies MessageShard;
