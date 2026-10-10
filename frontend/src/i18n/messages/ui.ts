/**
 * Strings owned by the shared UI primitives -- `ScrollPanel`, `InfoNote`, `StatusPill`, `PillLegend`
 * -- plus the small set of status words that turned out to mean the same thing on every page.
 *
 * These live together rather than in `common` because they belong to components, not to pages: a
 * page never picks these strings, it picks a tone and a component renders the word. Keeping them
 * here is what stops six pages from each inventing their own "STALE".
 *
 * Every label obeys docs/COPY-STYLE.md: pills are three words at most, and read as a state, not as a
 * sentence about a state.
 */
import type { MessageShard } from "@/i18n/types";

export const ui = {
  // --- ScrollPanel ---------------------------------------------------------
  "ui.scroll.expand": { en: "Expand", ko: "펼치기" },
  "ui.scroll.collapse": { en: "Collapse", ko: "접기" },

  // --- InfoNote ------------------------------------------------------------
  "ui.info.more": { en: "Show details", ko: "자세히 보기" },

  // --- shared pill vocabulary ---------------------------------------------
  // The six-state run vocabulary three pages currently duplicate between them.
  "ui.pill.pending": { en: "Pending", ko: "대기" },
  "ui.pill.running": { en: "Running", ko: "실행 중" },
  "ui.pill.succeeded": { en: "Done", ko: "완료" },
  "ui.pill.degraded": { en: "Degraded", ko: "부분 성공" },
  "ui.pill.failed": { en: "Failed", ko: "실패" },
  "ui.pill.blocked": { en: "Blocked", ko: "차단됨" },
  "ui.pill.skipped": { en: "Skipped", ko: "건너뜀" },

  // Data-condition states that appear on many pages.
  "ui.pill.stale": { en: "Stale", ko: "지연" },
  "ui.pill.staleDays": { en: "Stale {days}d", ko: "{days}일 지연" },
  "ui.pill.live": { en: "Live", ko: "실시간" },
  "ui.pill.dormant": { en: "Dormant", ko: "미거래" },
  "ui.pill.noTrades": { en: "No trades", ko: "거래 없음" },
  "ui.pill.inSample": { en: "In-sample", ko: "표본 내" },
  "ui.pill.simulated": { en: "Simulated", ko: "모의" },
  "ui.pill.estimated": { en: "Estimated", ko: "추정" },
  "ui.pill.unverified": { en: "Unverified", ko: "미검증" },
  "ui.pill.notAdvice": { en: "Not advice", ko: "조언 아님" },
  "ui.pill.filingLag": { en: "Filing lag", ko: "공시 지연" },

  // --- legend --------------------------------------------------------------
  "ui.legend.label": { en: "Status legend", ko: "상태 범례" },

  // --- tableSort.tsx: sortable header + filter bar --------------------------
  // Words a screen reader needs for a `SortHeader`'s current state -- both spoken via `aria-sort`
  // on the `<th>` and restated as a visually-hidden word inside the button itself, for whichever
  // of the two a given screen reader announces when the button gets focus directly.
  "ui.table.sortAscending": { en: "Ascending", ko: "오름차순" },
  "ui.table.sortDescending": { en: "Descending", ko: "내림차순" },
  "ui.table.sortNone": { en: "Not sorted", ko: "정렬 안 됨" },
  // A `SortHeader` button's `title=` hint (namespace-neutral so any table can reuse it).
  "ui.table.sortBy": { en: "Sort by {column}", ko: "{column} 기준 정렬" },
  // `FilterBar`'s clear button and its "showing N of M" note.
  "ui.table.filterClear": { en: "Clear", ko: "지우기" },
  "ui.table.filterShowing": { en: "Showing {shown} of {total}", ko: "{total}개 중 {shown}개 표시" },
} as const satisfies MessageShard;
