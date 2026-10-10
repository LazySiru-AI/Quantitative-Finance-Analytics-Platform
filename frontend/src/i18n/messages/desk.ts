/**
 * Paper Desk book and tape, plus the shared display components.
 *
 * Keys are prefixed `desk.` -- see `catalog.ts` for the convention and for why the prefix
 * is load-bearing rather than cosmetic.
 */
import type { MessageShard } from "@/i18n/types";

export const desk = {
  // --- BookSection.tsx: DeskVisibilityChooser ------------------------------
  "desk.book.desksShownTitle": { en: "Desks shown", ko: "표시된 데스크" },

  // --- BookSection.tsx: DeskHeader / FetchReport ---------------------------
  "desk.header.inceptionLabel": { en: "Inception", ko: "개시일" },
  "desk.header.asOfLabel": { en: "As of", ko: "기준일" },
  "desk.header.sessionsLabel": { en: "Sessions", ko: "세션 수" },
  "desk.header.firstSessionLabel": { en: "First session", ko: "첫 세션" },
  "desk.header.fetching": { en: "Fetching…", ko: "가져오는 중…" },
  "desk.header.fetchLatest": { en: "Fetch latest data", ko: "최신 데이터 가져오기" },
  "desk.header.fetchingProgress": {
    en: "Fetching daily bars for every book's roster and benchmarks -- forty paced requests. Recomputes every book when done.",
    ko: "모든 북의 종목과 벤치마크의 일별 바를 가져오는 중입니다 -- 약 40건의 순차 요청이라 시간이 걸립니다. 완료되면 모든 북이 다시 계산됩니다.",
  },
  "desk.header.markNoteLead": {
    en: "Figures below are marked to {asOf}'s close, not a live price. The latest stored bar is ",
    ko: "아래 수치는 {asOf} 종가 기준이며, 실시간 가격이 아닙니다. 최신 저장 바는 ",
  },
  "desk.header.staleSuffix_one": {
    en: ", itself {days} calendar day behind today",
    ko: ", 오늘보다 {days}일 뒤처져 있습니다",
  },
  "desk.header.staleSuffix_other": {
    en: ", itself {days} calendar days behind today",
    ko: ", 오늘보다 {days}일 뒤처져 있습니다",
  },
  "desk.header.staleCalloutStrong": {
    en: "The mark is {days} days behind -- treat every figure on this page as that many days stale.",
    ko: "마감 기준일이 {days}일 뒤처져 있습니다 -- 이 페이지의 모든 수치를 그만큼 오래된 것으로 간주하십시오.",
  },
  "desk.header.staleCalloutBody": {
    en: "The store has not been refreshed recently enough for {asOf} to be a current price.",
    ko: "저장소가 최근에 갱신되지 않아 {asOf}가 현재 가격이 아닙니다.",
  },
  "desk.header.fetchSummary": {
    en: "{requested} symbols in {duration}s: {advanced} adv, {unchanged} cur{failedClause}. {rowsMerged} {barsWord} merged.",
    ko: "{duration}초에 {requested}개 종목 -- {advanced}개 갱신, {unchanged}개 최신{failedClause}. {rowsMerged}{barsWord} 병합(재전송 중복 포함).",
  },
  "desk.header.failedClause": { en: ", {failed} failed", ko: ", {failed}건 실패" },
  "desk.header.barWord_one": { en: "bar", ko: "개 바" },
  "desk.header.barWord_other": { en: "bars", ko: "개 바" },
  "desk.header.fetchMarkMoved": {
    en: "The newest stored session moved from {before} to {after}; every figure below is now marked to {asOf}.",
    ko: "최신 저장 세션이 {before}에서 {after}로 이동했습니다. 아래 모든 수치는 이제 {asOf} 기준입니다.",
  },
  "desk.header.fetchMarkUnchanged": {
    en: "Still {after} -- the provider had no later session, so the mark is unchanged. New bars can arrive without a new session.",
    ko: "여전히 {after}입니다 -- 제공처에 더 최신 세션이 없어 마감 기준이 그대로입니다. 새 세션 없이도 새 바는 들어올 수 있습니다.",
  },
  "desk.header.noStoredBars": { en: "no stored bars", ko: "저장된 바 없음" },
  "desk.header.unavailable": { en: "unavailable", ko: "확인 불가" },
  "desk.header.failuresHeading": {
    en: "{failed} of {requested} symbols could not be fetched.",
    ko: "{requested}개 종목 중 {failed}개를 가져오지 못했습니다.",
  },
  "desk.header.failuresBody": {
    en: "Every other symbol is current; the desk recomputed anyway. Failed symbols show whatever they last had stored.",
    ko: "나머지 종목은 최신 상태이며 데스크는 그대로 다시 계산되었습니다. 실패한 종목은 마지막 저장값을 기준으로 합니다.",
  },

  // --- BookSection.tsx: fundingSummary / BookSection component -------------
  "desk.book.openingCapitalLabel": { en: "Opening capital", ko: "초기 자본" },
  "desk.book.benchmarkLabel": { en: "{symbol} benchmark", ko: "{symbol} 벤치마크" },
  "desk.book.horizonNone": { en: "no fixed horizon", ko: "정해진 기간 없음" },
  "desk.book.horizonRange": { en: "{min}-{max} years", ko: "{min}~{max}년" },
  "desk.book.cadenceLumpSum": { en: "once, with no additions", ko: "1회 납입, 추가 납입 없음" },
  "desk.book.cadenceMonthly": { en: "then {amount} every month", ko: "이후 매월 {amount}" },
  "desk.book.cadenceAnnual": { en: "then {amount} once a year", ko: "이후 연 1회 {amount}" },
  "desk.book.fundingSummary": {
    en: "{starting} {cadence} - {horizon} - {taxTreatment}",
    ko: "{starting} {cadence} - {horizon} - {taxTreatment}",
  },
  "desk.book.sectionAriaLabel": { en: "{label} book", ko: "{label} 북" },
  "desk.book.noCards": {
    en: "No cards are seated for this purpose yet. The book is funded and defined; nothing has been designed to trade it.",
    ko: "이 목적에 아직 배정된 카드가 없습니다. 북은 자금이 배정되고 정의되어 있지만, 이를 거래하도록 설계된 것은 아직 없습니다.",
  },
  "desk.book.noDesksSelected": {
    en: "No desks are selected in this book. Tick a desk above to bring its panel back.",
    ko: "이 북에서 선택된 데스크가 없습니다. 위에서 데스크를 선택하면 해당 패널이 다시 표시됩니다.",
  },

  // --- LiveTape.tsx / liveTapeModel.ts --------------------------------------
  "desk.tape.sectionAriaLabel": { en: "Live tape", ko: "실시간 체결 테이프" },
  "desk.tape.title": { en: "Live Tape", ko: "실시간 체결 테이프" },
  "desk.tape.viaTransport": { en: "via {transport}", ko: "{transport} 경유" },
  "desk.tape.asOfLower": { en: "as of {date}", ko: "{date} 기준" },
  "desk.tape.subtitle": {
    en: "Held, signalling this session, or traded last session -- not every desk's universe below.",
    ko: "보유 중이거나 이번 세션 신호 또는 최근 거래 종목만 표시합니다 -- 전체 유니버스가 아닙니다.",
  },
  "desk.tape.accountsLegend": { en: "Accounts", ko: "계좌" },
  "desk.tape.tagHeld": { en: "Held", ko: "보유" },
  "desk.tape.tagSignal": { en: "Signal", ko: "신호" },
  "desk.tape.tagTraded": { en: "Traded", ko: "거래됨" },
  "desk.tape.unhealthy": {
    en: "The live price feed is reporting unhealthy. Prices below may be stale or missing.",
    ko: "실시간 시세 피드가 비정상 상태를 보고했습니다. 아래 가격은 지연되었거나 누락되었을 수 있습니다.",
  },
  "desk.tape.emptyAll": {
    en: "No symbol is currently held, signalling, or was traded in the most recent session -- nothing is in play right now.",
    ko: "현재 보유 중이거나 신호가 발생했거나 가장 최근 세션에 거래된 종목이 없습니다 -- 현재 진행 중인 것이 없습니다.",
  },
  "desk.tape.emptyFiltered": {
    en: "No symbol matches the current account and status filters.",
    ko: "현재 계좌 및 상태 필터와 일치하는 종목이 없습니다.",
  },
  "desk.tape.sellWithQty": { en: "Sell {price} × {qty}", ko: "매도 {price} × {qty}" },
  "desk.tape.sellNoQty": { en: "Sell {price}", ko: "매도 {price}" },
  "desk.tape.buyWithQty": { en: "Buy {price} × {qty}", ko: "매수 {price} × {qty}" },
  "desk.tape.buyNoQty": { en: "Buy {price}", ko: "매수 {price}" },
  "desk.tape.actionTitle": { en: "{deskName} — {bookLabel}", ko: "{deskName} — {bookLabel}" },
  "desk.tape.actionTitleSignal": {
    en: "{deskName} — {bookLabel} (signal, not yet filled)",
    ko: "{deskName} — {bookLabel} (신호, 아직 체결 안 됨)",
  },
  "desk.tape.staleBadge": { en: "stale", ko: "지연됨" },
  "desk.tape.staleTitle": { en: "Last updated {ts}", ko: "마지막 업데이트: {ts}" },
  "desk.tape.noQuoteYet": { en: "No live quote yet", ko: "아직 실시간 시세 없음" },
  "desk.tape.pricesUnavailable": { en: "Live prices are unavailable right now.", ko: "지금은 실시간 가격을 이용할 수 없습니다." },

  // --- HoldingsPieChart.tsx --------------------------------------------------
  "desk.holdingsPie.title": { en: "Portfolio by weight", ko: "비중별 포트폴리오" },
  "desk.holdingsPie.noHoldings": {
    en: "No holdings on record for {fundName}.",
    ko: "{fundName}에 대해 기록된 보유 종목이 없습니다.",
  },
  "desk.holdingsPie.caption13f": {
    en: "13F: weights cover this filing's US equities -- no bonds, cash, foreign listings -- not {fundName}'s whole portfolio.",
    ko: "13F: 표시된 비중은 이 신고서의 미국 상장 주식만 포함합니다 — 채권, 현금, 해외 상장 제외 — {fundName}의 전체 포트폴리오가 아닙니다.",
  },
  "desk.holdingsPie.captionNport": {
    en: "NPORT-P: weights cover {fundName}'s whole portfolio -- ETFs skip 13F, so it's everything owned, not a US-equities slice.",
    ko: "NPORT-P: 표시된 비중은 {fundName}의 전체 신고 포트폴리오입니다 — ETF는 13F를 제출하지 않으므로 미국 주식만이 아닌 보유 전체입니다.",
  },
  "desk.holdingsPie.donutLabel_one": {
    en: "Donut chart of {fundName}'s portfolio by weight, {count} slice; exact weights are in the legend below",
    ko: "{fundName}의 비중별 포트폴리오 도넛 차트, {count}개 조각; 정확한 비중은 아래 범례에 있습니다",
  },
  "desk.holdingsPie.donutLabel_other": {
    en: "Donut chart of {fundName}'s portfolio by weight, {count} slices; exact weights are in the legend below",
    ko: "{fundName}의 비중별 포트폴리오 도넛 차트, {count}개 조각; 정확한 비중은 아래 범례에 있습니다",
  },
  "desk.holdingsPie.legendButtonLabel": {
    en: "{label} ({ticker}), {weight} of the filing",
    ko: "{label} ({ticker}), 신고서 기준 비중 {weight}",
  },
  "desk.holdingsPie.otherLabel_one": { en: "Other ({count} position)", ko: "기타 ({count}개 포지션)" },
  "desk.holdingsPie.otherLabel_other": { en: "Other ({count} positions)", ko: "기타 ({count}개 포지션)" },
  "desk.holdingsPie.total": {
    en: "Holdings shown total {weight} of the filing’s reported weight.",
    ko: "표시된 보유 종목은 신고서 기준 비중의 {weight}를 차지합니다.",
  },

  // --- RecentMoves.tsx ---------------------------------------------------------
  "desk.recentMoves.title": { en: "Recent moves", ko: "최근 변동" },
  "desk.recentMoves.loading": { en: "Loading recent moves…", ko: "최근 변동을 불러오는 중…" },
  "desk.recentMoves.errorFallback": { en: "Could not load recent moves.", ko: "최근 변동을 불러올 수 없습니다." },
  "desk.recentMoves.emptyState": {
    en: "Only one filing is on record -- nothing to compare yet. Expected for a filer just started tracking, not a failure.",
    ko: "기록된 신고서가 하나뿐이라 아직 비교할 대상이 없습니다. 막 추적을 시작한 신고자에게 정상적인 상태이며 오류가 아닙니다.",
  },
  "desk.recentMoves.noComparisonData": {
    en: "No comparison data is available for this fund right now.",
    ko: "현재 이 펀드에 대한 비교 데이터가 없습니다.",
  },
  "desk.recentMoves.actionNew": { en: "New", ko: "신규" },
  "desk.recentMoves.actionExit": { en: "Exit", ko: "청산" },
  "desk.recentMoves.actionAdd": { en: "Add", ko: "추가" },
  "desk.recentMoves.actionTrim": { en: "Trim", ko: "축소" },
  "desk.recentMoves.actionHold": { en: "Hold", ko: "유지" },
  "desk.recentMoves.periodLabel": { en: "Comparing {from} to {to}.", ko: "{from}부터 {to}까지 비교합니다." },
  "desk.recentMoves.noChanges": {
    en: "No position changes were reported between these two filings.",
    ko: "두 신고서 사이에 보고된 포지션 변동이 없습니다.",
  },
  "desk.recentMoves.sharesContext": { en: "{shares} shares ({pct})", ko: "{shares}주 ({pct})" },
  "desk.recentMoves.ofPortfolio": { en: "of portfolio", ko: "포트폴리오 대비" },
  "desk.recentMoves.rowAriaLabel": {
    en: "{issuer} ({ticker}), {action}, {weight} of portfolio",
    ko: "{issuer} ({ticker}), {action}, 포트폴리오 대비 {weight}",
  },

  // --- Sparkline.tsx -------------------------------------------------------
  "desk.sparkline.noData": { en: "{label}: no data", ko: "{label}: 데이터 없음" },

  // --- FactTable.tsx ---------------------------------------------------------
  "desk.factTable.title": { en: "Facts", ko: "근거 데이터" },
  "desk.factTable.subtitle": {
    en: "Every figure this report drew on -- its engine, and when it was current.",
    ko: "이 보고서가 근거로 삼은 모든 계산값, 산출 엔진, 기준 시점입니다.",
  },
  "desk.factTable.empty": { en: "No facts were computed for this report.", ko: "이 보고서에 대해 계산된 근거 데이터가 없습니다." },
  "desk.factTable.tableAriaLabel": { en: "Facts for {symbol}", ko: "{symbol}의 근거 데이터" },
  "desk.factTable.labelHeader": { en: "Label", ko: "항목" },
  "desk.factTable.asOfHeader": { en: "As of", ko: "기준일" },

  // --- NarrativeSection.tsx --------------------------------------------------
  "desk.narrative.citationsLabel": { en: "Figures this leaned on", ko: "이 서술이 근거로 삼은 수치" },
  "desk.narrative.factNotResolved": { en: "{id} (fact not resolved)", ko: "{id} (근거 확인 불가)" },

  // --- ProviderNote.tsx --------------------------------------------------------
  "desk.providerNote.main": { en: "Market data comes from {single} alone", ko: "시세 데이터는 {single} 한 곳에서만 제공됩니다" },
  "desk.providerNote.degraded_one": {
    en: " — the registered fallback ({names}) cannot currently serve",
    ko: " — 등록된 대체 제공처({names})가 현재 서비스를 제공할 수 없습니다",
  },
  "desk.providerNote.degraded_other": {
    en: " — the registered fallbacks ({names}) cannot currently serve",
    ko: " — 등록된 대체 제공처({names})가 현재 서비스를 제공할 수 없습니다",
  },
  "desk.providerNote.outage": {
    en: ". An outage upstream is an outage here; it will be reported as one rather than as missing history.",
    ko: ". 상류에서 장애가 발생하면 이곳에서도 장애로 나타나며, 데이터 누락이 아니라 장애로 보고됩니다.",
  },
} as const satisfies MessageShard;
