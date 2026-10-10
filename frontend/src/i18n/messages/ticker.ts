/**
 * Ticker page, chart, decision table and indicator picker.
 *
 * Keys are prefixed `ticker.` -- see `catalog.ts` for the convention and for why the prefix
 * is load-bearing rather than cosmetic.
 */
import type { MessageShard } from "@/i18n/types";

export const ticker = {
  // --- shared errors (useChartSeries.ts, IndicatorPicker.tsx) --------------
  "ticker.error.apiStatus": { en: "API returned {status}: {message}", ko: "API 응답 코드 {status}: {message}" },
  "ticker.error.unreachable": {
    en: "Cannot reach the API. Is uvicorn running on port 8000?",
    ko: "API에 연결할 수 없습니다. 8000번 포트에서 uvicorn이 실행 중인가요?",
  },

  // --- Ticker.tsx: page chrome -----------------------------------------------
  "ticker.title": { en: "Ticker", ko: "종목" },
  "ticker.subtitle": {
    en: "Company profile, fundamentals, candlestick charts and the decision table.",
    ko: "기업 개요, 재무 정보, 캔들스틱 차트, 판정 표를 제공합니다.",
  },
  "ticker.symbolForm.placeholder": { en: "SYMBOL", ko: "종목코드" },
  "ticker.symbolForm.ariaLabel": { en: "Ticker symbol", ko: "종목 코드" },
  "ticker.symbolForm.submit": { en: "Go", ko: "이동" },
  "ticker.empty.tryThese": {
    en: "No symbol yet. Try one of these:",
    ko: "아직 입력된 종목이 없습니다. 다음 중 하나를 선택해 보세요:",
  },
  "ticker.loadingSymbol": { en: "Loading {symbol}…", ko: "{symbol} 불러오는 중…" },
  "ticker.notFound": {
    en: 'No data for symbol "{symbol}". Check the ticker and try again.',
    ko: '"{symbol}" 종목의 데이터가 없습니다. 종목 코드를 확인한 뒤 다시 시도하세요.',
  },

  // --- Ticker.tsx: chart panel -------------------------------------------------
  "ticker.chart.heading": { en: "Chart", ko: "차트" },
  "ticker.chart.view.single": { en: "single", ko: "단일" },
  "ticker.chart.view.grid": { en: "all 4", ko: "4분할" },
  "ticker.chart.layoutAriaLabel": { en: "Chart layout", ko: "차트 레이아웃" },
  "ticker.chart.timeframeAriaLabel": { en: "Timeframe", ko: "타임프레임" },
  "ticker.chart.source": { en: "source: {source}", ko: "출처: {source}" },
  "ticker.chart.loadingBars": { en: "Loading {interval} bars…", ko: "{interval} 봉 불러오는 중…" },
  "ticker.chart.barsNotFound": {
    en: 'No {interval} bars for "{symbol}".',
    ko: '"{symbol}"의 {interval} 봉이 없습니다.',
  },
  "ticker.chart.noBars": {
    en: "No {interval} bars stored for {symbol} yet.",
    ko: "{symbol}의 {interval} 봉 데이터가 아직 저장되어 있지 않습니다.",
  },
  "ticker.chart.loadingIndicators": { en: "Loading indicators…", ko: "지표 불러오는 중…" },
  "ticker.chart.indicatorsNotFound": {
    en: 'Indicators unavailable for "{symbol}".',
    ko: '"{symbol}"의 지표를 사용할 수 없습니다.',
  },

  // --- Ticker.tsx: rule editor panel ------------------------------------------
  "ticker.ruleEditor.heading": { en: "Test a rule expression", ko: "규칙 표현식 테스트" },

  // --- Ticker.tsx: header -------------------------------------------------
  "ticker.header.nameUnavailable": { en: "Name unavailable", ko: "이름 정보 없음" },
  "ticker.header.range": { en: "52w {low} – {high}", ko: "52주 {low} – {high}" },
  "ticker.header.volume": { en: "Vol {volume}", ko: "거래량 {volume}" },

  // --- Ticker.tsx: warnings ------------------------------------------------
  "ticker.warnings.heading": { en: "Warnings", ko: "경고" },

  // --- `MarketWarning.kind` pill labels (Ticker.tsx's `WarningsStrip`) -------
  // `stale` reuses the shared `ui.pill.stale` label rather than a copy of the same word here.
  // Duplicated from `Macro.tsx`'s own copy of this same mapping rather than shared -- see that
  // shard's comment for why.
  "ticker.warningKind.providerFallback": { en: "Provider fallback", ko: "대체 공급자 사용" },
  "ticker.warningKind.clamped": { en: "Clamped", ko: "값 보정됨" },
  "ticker.warningKind.shortHistory": { en: "Short history", ko: "짧은 이력" },
  "ticker.warningKind.partialBar": { en: "Partial bar", ko: "미완성 봉" },
  "ticker.warningKind.gap": { en: "Data gap", ko: "데이터 공백" },
  "ticker.warningKind.other": { en: "Notice", ko: "알림" },

  // --- Ticker.tsx: coverage -------------------------------------------------
  "ticker.coverage.heading": { en: "Coverage", ko: "데이터 커버리지" },
  "ticker.coverage.empty": {
    en: "No bars stored for this symbol yet.",
    ko: "이 종목의 봉 데이터가 아직 저장되어 있지 않습니다.",
  },
  "ticker.coverage.col.interval": { en: "Interval", ko: "간격" },
  "ticker.coverage.col.rows": { en: "Rows", ko: "행 수" },
  "ticker.coverage.col.first": { en: "First", ko: "최초" },
  "ticker.coverage.col.last": { en: "Last", ko: "최근" },
  "ticker.coverage.col.fetched": { en: "Fetched", ko: "수집 시각" },

  // --- Ticker.tsx: fundamentals ------------------------------------------------
  "ticker.fundamentals.heading": { en: "Fundamentals", ko: "재무 정보" },
  "ticker.fundamentals.notAttempted": {
    en: "No fundamentals lookup was attempted for this symbol.",
    ko: "이 종목에 대해 재무 정보 조회를 시도하지 않았습니다.",
  },
  "ticker.fundamentals.noFacts": {
    en: "No facts returned for this symbol.",
    ko: "이 종목에 대한 재무 항목이 반환되지 않았습니다.",
  },
  "ticker.fundamentals.col.label": { en: "Label", ko: "항목" },
  "ticker.fundamentals.col.unit": { en: "Unit", ko: "단위" },
  "ticker.fundamentals.col.periodEnd": { en: "Period end", ko: "기간 종료일" },
  "ticker.fundamentals.col.fiscalPeriod": { en: "Fiscal period", ko: "회계 기간" },
  "ticker.fundamentals.col.form": { en: "Form", ko: "서식" },

  // The caveat strip `Symbol.tsx` renders above the Decision tab, beside a NOT ADVICE and an
  // IN-SAMPLE pill. COPY-STYLE.md rule 6: in-sample returns are one of the things that may be
  // shortened but never moved behind a disclosure.
  "ticker.decision.caveat": {
    en: "Edge and significance are measured on the same bars they describe.",
    ko: "엣지와 유의성은 그것이 설명하는 바로 그 봉에서 측정됩니다.",
  },

  // --- DecisionTable.tsx: chrome -----------------------------------------------
  "ticker.decision.heading": { en: "Decision table", ko: "판정 표" },
  "ticker.decision.loading": { en: "Loading decision table…", ko: "판정 표 불러오는 중…" },
  "ticker.decision.notFound": {
    en: 'No decision table for "{symbol}" at {interval}.',
    ko: '"{symbol}"의 {interval} 판정 표가 없습니다.',
  },
  "ticker.decision.sampleRange": { en: "Sample {first} → {last}", ko: "표본 {first} → {last}" },
  "ticker.decision.barsEvaluated": { en: "{count} bars evaluated", ko: "{count}개 봉 평가됨" },
  "ticker.decision.horizonAriaLabel": { en: "Evidence horizon", ko: "근거 기간" },
  "ticker.decision.horizonLabel": { en: "Horizon", ko: "기간" },
  "ticker.decision.noRules": {
    en: "No rules evaluated for {symbol} at {interval}.",
    ko: "{symbol}의 {interval}에서 평가된 규칙이 없습니다.",
  },
  "ticker.decision.tableAriaLabel": {
    en: "Decision table for {symbol} at {interval}, {horizon}-bar horizon",
    ko: "{symbol}의 {interval} 판정 표, {horizon}봉 기간",
  },

  // --- DecisionTable.tsx: main table columns --------------------------------
  "ticker.decision.col.rule": { en: "Rule", ko: "규칙" },
  "ticker.decision.col.state": { en: "State", ko: "상태" },
  "ticker.decision.col.lastTrigger": { en: "Last trigger", ko: "최근 발동" },
  "ticker.decision.col.edge": { en: "Edge @ {horizon}b", ko: "엣지 @ {horizon}봉" },
  "ticker.decision.col.medianReturn": { en: "Median return @ {horizon}b", ko: "중앙값 수익률 @ {horizon}봉" },
  "ticker.decision.col.sample": { en: "Sample", ko: "표본" },
  "ticker.decision.col.significance": { en: "Significance", ko: "유의성" },
  "ticker.decision.col.rowDetailsHidden": { en: "Row details", ko: "행 상세정보" },

  // --- DecisionTable.tsx: row -----------------------------------------------
  "ticker.decision.hideBreakdown": { en: "Hide horizon breakdown for {rule}", ko: "{rule}의 기간별 분석 숨기기" },
  "ticker.decision.showBreakdown": { en: "Show horizon breakdown for {rule}", ko: "{rule}의 기간별 분석 보기" },
  "ticker.decision.hideButton": { en: "hide", ko: "숨기기" },
  "ticker.decision.allHorizonsButton": { en: "all horizons", ko: "전체 기간" },
  "ticker.decision.neverFired": { en: "never fired", ko: "발동 이력 없음" },
  "ticker.barsAgo": { en: "{count} bars ago", ko: "{count}봉 전" },

  // --- DecisionTable.tsx: evidence cells --------------------------------------
  "ticker.decision.edge.vsBase": { en: "{hit} vs {base} base", ko: "{hit} vs {base} 기준값" },
  "ticker.decision.edge.upperBoundTag": { en: "upper bound (same-close)", ko: "상한값 (당일 종가 기준)" },
  "ticker.decision.edge.upperBoundTitle": {
    en: "Entry assumed at the same bar's close -- an unrealistic fill, upper bound only",
    ko: "진입가를 해당 봉의 종가로 가정합니다 -- 비현실적인 체결이며 상한값만을 의미합니다",
  },
  "ticker.decision.median.base": { en: "base {value}", ko: "기준 {value}" },
  "ticker.decision.sample.indepSuffix": { en: "{sample} ({indep} indep)", ko: "{sample} (독립 {indep})" },

  // --- DecisionTable.tsx: significance vocabulary -----------------------------
  "ticker.decision.significance.suggestive": { en: "suggestive", ko: "시사적" },
  "ticker.decision.significance.weak": { en: "weak", ko: "약함" },
  "ticker.decision.significance.insufficient": { en: "insufficient", ko: "불충분" },

  // --- DecisionTable.tsx: significance legend ---------------------------------
  "ticker.decision.legend.summary": { en: "How significance is graded", ko: "유의성 평가 방식" },
  "ticker.decision.legend.intro": {
    en: "Both conditions must hold together — a large edge on a handful of observations stays {insufficient}, and so does a tiny edge on hundreds. The sample counted is the {independent} one: overlapping forward windows are not separate draws.",
    ko: "두 조건을 모두 충족해야 합니다 — 소수의 관측치에서 나타난 큰 엣지도 {insufficient} 상태이며, 수백 건에서 나타난 미미한 엣지도 마찬가지입니다. 집계되는 표본은 {independent} 표본입니다: 겹치는 미래 구간은 별개의 관측이 아닙니다.",
  },
  "ticker.decision.legend.independentWord": { en: "independent", ko: "독립적인" },
  "ticker.decision.legend.and": { en: "and", ko: "그리고" },
  "ticker.decision.legend.points": { en: "{n} points", ko: "{n}포인트" },
  "ticker.decision.legend.suggestiveItem": {
    en: "{label} — at least {n} independent triggers {and} a hit rate at least {edge} away from the baseline.",
    ko: "{label} — 독립적인 발동이 최소 {n}회 {and} 적중률이 기준선과 최소 {edge} 차이가 나야 합니다.",
  },
  "ticker.decision.legend.weakItem": {
    en: "{label} — at least {n} independent triggers {and} at least {edge} away from the baseline.",
    ko: "{label} — 독립적인 발동이 최소 {n}회 {and} 기준선과 최소 {edge} 차이가 나야 합니다.",
  },
  "ticker.decision.legend.insufficientItem": {
    en: "{label} — everything else. The honest default, and the expected answer for most rules on most instruments.",
    ko: "{label} — 그 외 모든 경우입니다. 가장 정직한 기본값이며, 대부분의 규칙과 대부분의 종목에서 예상되는 결과입니다.",
  },
  "ticker.decision.legend.footer": {
    en: "Edges are points of {howOften}, not return -- coarser than a p-value, not a significance test. See the Backtest scan.",
    ko: "엣지는 수익률이 아닌 {howOften}의 백분율 포인트입니다 -- p-값보다 거친 기준입니다. 유의성 검정 아님 -- 백테스트 스캔 참고.",
  },
  "ticker.decision.legend.howOften": { en: "how often", ko: "얼마나 자주 발생했는지" },

  // --- DecisionTable.tsx: per-row horizon detail ------------------------------
  "ticker.decision.detail.caption": { en: "Evidence across all horizons for {rule}", ko: "{rule}의 전체 기간별 근거" },
  "ticker.decision.detail.col.entry": { en: "Entry", ko: "진입" },
  "ticker.decision.detail.col.edge": { en: "Edge", ko: "엣지" },
  "ticker.decision.detail.col.hitRateBase": { en: "Hit rate / base", ko: "적중률 / 기준" },
  "ticker.decision.detail.col.medianBase": { en: "Median / base", ko: "중앙값 / 기준" },
  "ticker.decision.detail.col.sampleIndep": { en: "Sample / indep", ko: "표본 / 독립" },
  "ticker.decision.detail.notEvaluated": { en: "not evaluated", ko: "평가되지 않음" },
  "ticker.decision.entry.sameClose": { en: "same-close (upper bound)", ko: "당일 종가 (상한값)" },
  "ticker.decision.entry.nextOpen": { en: "next-open", ko: "다음 시가" },

  // --- IndicatorPicker.tsx -----------------------------------------------------
  // `pickerHeading` is Ticker.tsx's own -- the `Collapsible` summary that hides the picker's dozen-
  // plus indicator cards behind a click so they no longer push the chart down by default.
  "ticker.indicator.pickerHeading": { en: "Indicators", ko: "지표" },
  "ticker.indicator.loadingCatalog": { en: "Loading indicator catalog…", ko: "지표 목록 불러오는 중…" },
  "ticker.indicator.addLine": { en: "Add a {title} line", ko: "{title} 라인 추가" },
  "ticker.indicator.unavailable": {
    en: "Unavailable on {interval} bars — needs {list}.",
    ko: "{interval} 봉에서는 사용할 수 없습니다 — {list}이(가) 필요합니다.",
  },
  "ticker.indicator.orJoiner": { en: "or", ko: "또는" },
  "ticker.indicator.changeColor": { en: "Change colour for {title} {spec}", ko: "{title} {spec}의 색상 변경" },
  "ticker.indicator.remove": { en: "Remove {spec}", ko: "{spec} 제거" },
  "ticker.indicator.lineColorGroup": { en: "Line colour", ko: "선 색상" },
  "ticker.indicator.useColor": { en: "Use {color}", ko: "{color} 사용" },
  "ticker.indicator.fromDate": { en: "from date…", ko: "날짜 지정…" },

  // --- PanelBoundary labels --------------------------------------------------------
  // See the note in `portfolio.ts`: the label is rendered inside a Korean sentence by
  // `PanelBoundary`, so it is translated at the caller rather than left as an English prop.
  "ticker.panel.header": { en: "Header", ko: "헤더" },
  "ticker.panel.warnings": { en: "Warnings", ko: "경고" },
  "ticker.panel.chart": { en: "Chart", ko: "차트" },
  "ticker.panel.decisionTable": { en: "Decision table", ko: "판정 표" },
  "ticker.panel.ruleEditor": { en: "Rule editor", ko: "규칙 편집기" },
  "ticker.panel.coverage": { en: "Coverage", ko: "커버리지" },
  "ticker.panel.fundamentals": { en: "Fundamentals", ko: "재무 지표" },
  "ticker.panel.news": { en: "News", ko: "뉴스" },
  "ticker.panel.institutionalHolders": { en: "Institutional holders", ko: "기관 보유자" },
} as const satisfies MessageShard;
