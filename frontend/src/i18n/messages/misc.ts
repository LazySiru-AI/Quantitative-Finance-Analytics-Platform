/**
 * Overview, the Macro key-indicator and fear-greed components, and the Personas page.
 *
 * Keys are prefixed `misc.` -- see `catalog.ts` for the convention and why the prefix is
 * load-bearing (the duplicate-key guard in `i18n.test.tsx` keys off it).
 */
import type { MessageShard } from "@/i18n/types";

export const misc = {
  // --- shared fetch-error strings (Overview.tsx's local hooks, useEventCalendar.ts, usePersonas.ts) ---
  // Identical wording to `portfolio.apiError`/`portfolio.cannotReachApi` and `macro.api.*`, kept as a
  // local duplicate per this codebase's one-shard-per-area convention -- reused across every fetch
  // hook this shard owns rather than one copy per file.
  "misc.fetch.apiError": { en: "API returned {status}: {message}", ko: "API 오류 {status}: {message}" },
  "misc.fetch.unreachable": {
    en: "Cannot reach the API. Is uvicorn running on port 8000?",
    ko: "API에 연결할 수 없습니다. 포트 8000에서 uvicorn이 실행 중인가요?",
  },

  // --- PanelBoundary labels ------------------------------------------------------------------------
  "misc.panel.addPersona": { en: "Add a persona", ko: "페르소나 추가" },

  // --- honest labelling of server prose this app cannot translate ------------------------------------
  // Rendered only under 한국어, and only where the words in the card came from the server and nothing
  // keys them: a calendar row's free-form detail, the Manager brief body the model wrote. The pill is
  // the disclosure, not an apology -- a Korean reader is told which block is still English instead of
  // finding out by reading it. Machine translation is a separate, flag-gated path (`TranslatedProse`,
  // INVDASH_TRANSLATE_NARRATIVES); this key is what the page says when that path is not in use.
  "misc.pill.englishOnly": { en: "English only", ko: "영어만" },
  "misc.pill.englishOnlyDetail": {
    en: "Written by the data source or the model, in English. Not translated.",
    ko: "데이터 출처 또는 모델이 영어로 작성한 내용이며, 번역되지 않았습니다.",
  },

  // =====================================================================================================
  // pages/Overview.tsx
  // =====================================================================================================

  // --- section heads ---------------------------------------------------------------------------------
  // "Account", not "Portfolio": the page this heading summarises and links to (`/portfolio`) is
  // titled "Account" -- a section head naming a page by a name that page no longer uses sends the
  // reader looking for something that is not in the rail.
  "misc.overview.section.portfolio": { en: "Account", ko: "계좌" },
  "misc.overview.link.portfolio": { en: "Full account →", ko: "전체 계좌 보기 →" },
  "misc.overview.section.market": { en: "Market context", ko: "시장 현황" },
  "misc.overview.link.market": { en: "Full macro page →", ko: "전체 매크로 페이지 보기 →" },
  "misc.overview.section.desk": { en: "Reference desk", ko: "레퍼런스 데스크" },
  "misc.overview.link.desk": { en: "Full paper desk →", ko: "전체 페이퍼 데스크 보기 →" },

  // --- fetch-data toolbar ------------------------------------------------------------------------------
  // The manual "force everything from source" button. An ordinary page load reads the cache the
  // startup warm primed; this is the one control that bypasses it across every card at once.
  "misc.overview.fetchData.label": { en: "Fetch latest data", ko: "최신 데이터 가져오기" },
  "misc.overview.fetchData.loading": { en: "Fetching…", ko: "가져오는 중…" },
  "misc.overview.fetchData.ariaLabel": {
    en: "Fetch the latest data from source for every card, bypassing the cache",
    ko: "캐시를 무시하고 모든 카드의 최신 데이터를 소스에서 가져옵니다",
  },

  // --- portfolio section -------------------------------------------------------------------------------
  // The noun `Skeleton` announces ("Loading {what}…"), not a whole sentence -- every panel on this
  // page now draws a shaped placeholder instead of a bare loading line. See `Skeleton.tsx`.
  "misc.overview.portfolio.skeletonWhat": { en: "account", ko: "계좌" },
  "misc.overview.portfolio.failed": { en: "Portfolio failed to load.", ko: "포트폴리오를 불러오지 못했습니다." },
  "misc.overview.portfolio.failedWithMessage": {
    en: "Portfolio failed to load: {message}",
    ko: "포트폴리오를 불러오지 못했습니다: {message}",
  },
  "misc.overview.portfolio.empty": {
    en: "No positions on the ledger yet.",
    ko: "아직 원장에 보유 종목이 없습니다.",
  },

  // --- portfolio mark note -----------------------------------------------------------------------------
  "misc.overview.mark.nothingPriced": {
    en: "Ledger as of {asOf} — nothing is priced, so no market value is stated below.",
    ko: "{asOf} 기준 원장 — 가격이 확인된 종목이 없어 아래에 평가 금액을 표시하지 않습니다.",
  },
  "misc.overview.mark.pricedSingle": { en: "priced at the close of {date}", ko: "{date} 종가 기준" },
  "misc.overview.mark.pricedRange": {
    en: "priced at closes ranging {range} — a mix of {distinct} pricing dates",
    ko: "{range} 종가 기준으로 혼재 — 서로 다른 {distinct}개의 기준일이 섞여 있음",
  },
  "misc.overview.mark.staleHeadline": {
    en: "The newest price behind these figures is {behind} days old ({date}).",
    ko: "이 수치들의 최신 가격은 {behind}일 전 것입니다 ({date}).",
  },
  "misc.overview.mark.staleFooter": {
    en: "Ledger as of {asOf} — treat every figure below as that many days stale.",
    ko: "{asOf} 기준 원장 — 아래 모든 수치를 그만큼 오래된 것으로 간주하세요.",
  },
  "misc.overview.mark.today": {
    en: "Ledger as of {asOf} · {priced} · today",
    ko: "{asOf} 기준 원장 · {priced} · 오늘",
  },
  "misc.overview.mark.behind_one": {
    en: "Ledger as of {asOf} · {priced} · {days} calendar day behind today",
    ko: "{asOf} 기준 원장 · {priced} · 오늘보다 {days}일 지남",
  },
  "misc.overview.mark.behind_other": {
    en: "Ledger as of {asOf} · {priced} · {days} calendar days behind today",
    ko: "{asOf} 기준 원장 · {priced} · 오늘보다 {days}일 지남",
  },
  "misc.overview.mark.noBehind": { en: "Ledger as of {asOf} · {priced}", ko: "{asOf} 기준 원장 · {priced}" },

  // --- portfolio tiles -----------------------------------------------------------------------------
  "misc.overview.tile.totalEquity": { en: "Total equity", ko: "자산 총액" },
  "misc.overview.tile.totalEquityHintComplete": { en: "positions + cash", ko: "포지션 + 현금" },
  "misc.overview.tile.totalEquityHintIncomplete": {
    en: "incomplete — see caveats below",
    ko: "불완전함 — 아래 주의 사항 참고",
  },
  "misc.overview.tile.cash": { en: "Cash", ko: "현금" },
  "misc.overview.tile.cashPartial": { en: "Cash (partial)", ko: "현금 (부분)" },
  "misc.overview.cash.accountsExcluded_one": { en: "{count} account excluded", ko: "{count}개 계좌 제외" },
  "misc.overview.cash.accountsExcluded_other": { en: "{count} accounts excluded", ko: "{count}개 계좌 제외" },
  "misc.overview.tile.unrealizedPnl": { en: "Unrealized P&L", ko: "미실현 손익" },
  "misc.overview.tile.unrealizedPnlPartial": { en: "Unrealized P&L (partial)", ko: "미실현 손익 (부분)" },
  "misc.overview.tile.pricedOfHint": {
    en: "{priced} of {total} positions priced",
    ko: "전체 {total}개 중 {priced}개 가격 확인",
  },
  "misc.overview.tile.pricedOfHintWithPct": {
    en: "{priced} of {total} positions priced · {pct}",
    ko: "전체 {total}개 중 {priced}개 가격 확인 · {pct}",
  },
  "misc.overview.tile.positions": { en: "Positions", ko: "포지션" },
  "misc.overview.tile.unpricedHint": { en: "{count} unpriced", ko: "{count}개 미가격" },

  // --- market section ------------------------------------------------------------------------------
  "misc.overview.market.skeletonWhat": { en: "market context", ko: "시장 현황" },
  "misc.overview.market.failed": { en: "Market context failed to load.", ko: "시장 현황을 불러오지 못했습니다." },
  "misc.overview.market.failedWithMessage": {
    en: "Market context failed to load: {message}",
    ko: "시장 현황을 불러오지 못했습니다: {message}",
  },

  // --- Fear & Greed column (Overview-local placeholders) --------------------------------------------
  "misc.overview.fearGreed.unavailable": {
    en: "Fear & Greed unavailable — see market context above.",
    ko: "공포·탐욕 지수를 사용할 수 없음 — 위 시장 현황을 참고하세요.",
  },
  "misc.overview.fearGreed.skeletonWhat": { en: "Fear & Greed", ko: "공포·탐욕 지수" },

  // --- reference desk section -------------------------------------------------------------------------
  // The visible half of the simulated-money marking (docs/COPY-STYLE.md rule 6): a `SIMULATED` pill
  // in the section head, and this line above the cards. The panel prints a RETURN % per agent
  // directly under the real-money equity tiles, so the distinction may never live behind a
  // disclosure -- and "not a portfolio" is the second half of it, since no total across these desks
  // is a figure anyone holds.
  "misc.overview.referenceDesk.caveat": {
    en: "Paper money. Own capital per desk, not a portfolio.",
    ko: "모의 자본입니다. 데스크별 자체 자본이며 포트폴리오가 아닙니다.",
  },
  "misc.overview.desk.tableLabel": { en: "{book} desks", ko: "{book} 데스크" },
  "misc.overview.desk.skeletonWhat": { en: "reference desk", ko: "레퍼런스 데스크" },
  "misc.overview.desk.failed": { en: "Reference desk failed to load.", ko: "레퍼런스 데스크를 불러오지 못했습니다." },
  "misc.overview.desk.failedWithMessage": {
    en: "Reference desk failed to load: {message}",
    ko: "레퍼런스 데스크를 불러오지 못했습니다: {message}",
  },
  "misc.overview.desk.staleCallout": {
    en: "The desk mark is {days} days behind the latest session ({bar}) — treat every figure below as that many days stale.",
    ko: "데스크 마크가 최신 세션({bar})보다 {days}일 지났습니다 — 아래 모든 수치를 그만큼 오래된 것으로 간주하세요.",
  },
  "misc.overview.desk.seated_one": { en: "{count} desk seated", ko: "{count}개 데스크 배치됨" },
  "misc.overview.desk.seated_other": { en: "{count} desks seated", ko: "{count}개 데스크 배치됨" },
  "misc.overview.desk.benchmarkLabel": { en: "Benchmark {name}:", ko: "벤치마크 {name}:" },
  "misc.overview.desk.noCardsSeated": { en: "No cards seated yet.", ko: "아직 배치된 카드가 없습니다." },
  // The scroll region's aria-label on one book card. Names the book, because all three cards in the
  // row are otherwise the same region with the same label.
  "misc.overview.desk.cardLabel": { en: "{name} desks", ko: "{name} 데스크" },
  "misc.overview.desk.header.agent": { en: "Agent", ko: "에이전트" },
  "misc.overview.desk.header.return": { en: "Return", ko: "수익률" },
  "misc.overview.desk.header.openPositions": { en: "Open positions", ko: "보유 포지션" },

  // --- calendar section (Overview's EventCalendarCard) -------------------------------------------
  "misc.overview.calendar.loading": { en: "Loading calendar…", ko: "캘린더 불러오는 중…" },
  "misc.overview.calendar.skeletonWhat": { en: "calendar", ko: "캘린더" },
  "misc.overview.calendar.slowNote": {
    en: "Still working. The day's first load fetches the exchange calendar upstream before caching it; later loads are quick.",
    ko: "계속 진행 중입니다. 오늘 첫 로드는 거래소 캘린더를 가져와 캐싱하는 데 몇 초가 걸리며, 이후 로드는 빠릅니다.",
  },
  "misc.overview.calendar.failed": { en: "Calendar failed to load.", ko: "캘린더를 불러오지 못했습니다." },
  "misc.overview.calendar.failedWithMessage": {
    en: "Calendar failed to load: {message}",
    ko: "캘린더를 불러오지 못했습니다: {message}",
  },
  "misc.overview.calendar.tryAgain": { en: "Try again", ko: "다시 시도" },

  // --- attention section -----------------------------------------------------------------------------
  "misc.overview.attention.heading": { en: "Attention", ko: "주의사항" },
  "misc.overview.attention.checking": {
    en: "Checking for anything that needs attention…",
    ko: "확인이 필요한 항목이 있는지 검사하는 중…",
  },
  "misc.overview.attention.allClear": {
    en: "Nothing needs attention — no open wash-sale windows, no portfolio warnings, and the paper desk mark is current.",
    ko: "지금은 확인이 필요한 항목이 없습니다 — 열려 있는 워시 세일 기간이 없고, 포트폴리오 경고가 없으며, 페이퍼 데스크 마크가 최신 상태입니다.",
  },
  // Two independent counts (open wash-sale windows, symbols) drive English grammar independently, so
  // all four singular/plural combinations are real (unlike `portfolio.partialCaveat`'s three, where
  // unpriced <= total rules one combination out).
  "misc.overview.attention.washOpen_1_1": {
    en: "{windows} open wash-sale window across {symbols} symbol",
    ko: "{symbols}개 종목에 걸쳐 열려 있는 워시 세일 기간 {windows}건",
  },
  "misc.overview.attention.washOpen_1_n": {
    en: "{windows} open wash-sale window across {symbols} symbols",
    ko: "{symbols}개 종목에 걸쳐 열려 있는 워시 세일 기간 {windows}건",
  },
  "misc.overview.attention.washOpen_n_1": {
    en: "{windows} open wash-sale windows across {symbols} symbol",
    ko: "{symbols}개 종목에 걸쳐 열려 있는 워시 세일 기간 {windows}건",
  },
  "misc.overview.attention.washOpen_n_n": {
    en: "{windows} open wash-sale windows across {symbols} symbols",
    ko: "{symbols}개 종목에 걸쳐 열려 있는 워시 세일 기간 {windows}건",
  },
  // `repurchase_safe_on` rides on every `WashSaleTrackerSymbol`, so the open-window line can name
  // the date the exposure clears instead of leaving the reader to open another page to find it.
  // It is the *repurchase* date only -- deferred money comes back on a lot sale, never on a
  // calendar date (see `@/api/washsales`).
  "misc.overview.attention.soonest": {
    en: "Soonest repurchase safe on {date}",
    ko: "가장 이른 재매수 안전일: {date}",
  },
  "misc.overview.attention.openWashSales": { en: "Open Wash Sales", ko: "워시세일 보기" },
  "misc.overview.attention.washUnavailable": {
    en: "Wash-sale window status could not be checked.",
    ko: "워시 세일 기간 상태를 확인할 수 없습니다.",
  },
  "misc.overview.attention.washUnavailableWithMessage": {
    en: "Wash-sale window status could not be checked — {message}",
    ko: "워시 세일 기간 상태를 확인할 수 없습니다 — {message}",
  },
  "misc.overview.attention.portfolioWarning_one": {
    en: "{count} portfolio warning — basis or fee gaps the replay could not fully establish",
    ko: "재구성 과정에서 완전히 확정하지 못한 취득가/수수료 공백 {count}건",
  },
  "misc.overview.attention.portfolioWarning_other": {
    en: "{count} portfolio warnings — basis or fee gaps the replay could not fully establish",
    ko: "재구성 과정에서 완전히 확정하지 못한 취득가/수수료 공백 {count}건",
  },
  "misc.overview.attention.deskStale": {
    en: "Paper desk mark is {days} days behind the latest session ({bar})",
    ko: "페이퍼 데스크 마크가 최신 세션({bar})보다 {days}일 지났습니다",
  },
  "misc.overview.attention.deskUnavailable": {
    en: "Paper desk staleness could not be checked — the fetch failed.",
    ko: "페이퍼 데스크 최신성 여부를 확인할 수 없습니다 — 데이터를 가져오지 못했습니다.",
  },
  "misc.overview.attention.noIssuesFound": {
    en: "No issues found in the data that did load.",
    ko: "불러온 데이터에서는 문제가 발견되지 않았습니다.",
  },
  // The bridge to the Manager desk. This card is standing state; Manager's feed is the diff against
  // yesterday's snapshot, so the link names the question Manager answers, not the page it opens.
  "misc.overview.attention.managerLink": {
    en: "What changed since yesterday →",
    ko: "어제 이후 달라진 점 →",
  },

  // --- section: programme status (loop / agent layer / newest round) -------------------------------
  "misc.overview.programme.heading": { en: "Programme", ko: "프로그램" },
  "misc.overview.link.programme": { en: "Full competition page →", ko: "전체 경쟁 페이지 보기 →" },
  "misc.overview.programme.loopLabel": { en: "Strategy loop", ko: "전략 루프" },
  "misc.overview.programme.agentLabel": { en: "Agent layer", ko: "에이전트 레이어" },
  "misc.overview.programme.newestRoundLabel": { en: "Newest round", ko: "최신 라운드" },
  "misc.overview.programme.loopRunning": { en: "Running", ko: "실행 중" },
  "misc.overview.programme.loopStopping": { en: "Stopping", ko: "정지 중" },
  "misc.overview.programme.loopIdle": { en: "Idle", ko: "대기 중" },
  "misc.overview.programme.agentReady": { en: "Ready", ko: "준비됨" },
  "misc.overview.programme.agentUnavailable": { en: "Unavailable", ko: "사용 불가" },
  "misc.overview.programme.roundNone": { en: "None yet", ko: "아직 없음" },
  "misc.overview.programme.unavailable": {
    en: "Unavailable — the fetch failed.",
    ko: "사용할 수 없음 — 데이터를 가져오지 못했습니다.",
  },

  // --- section: tax ---------------------------------------------------------------------------------
  "misc.overview.section.tax": { en: "Tax", ko: "세금" },
  "misc.overview.link.tax": { en: "Full tax page →", ko: "전체 세금 페이지 보기 →" },
  "misc.overview.tax.skeletonWhat": { en: "tax", ko: "세금 정보" },
  "misc.overview.tax.failed": { en: "Tax summary failed to load.", ko: "세금 요약을 불러오지 못했습니다." },
  "misc.overview.tax.failedWithMessage": {
    en: "Tax summary failed to load: {message}",
    ko: "세금 요약을 불러오지 못했습니다: {message}",
  },
  "misc.overview.tax.tile.ytdGain": { en: "YTD realized gain", ko: "연초 이후 실현 손익" },
  "misc.overview.tax.tile.ytdGainHint": { en: "{year} disposals", ko: "{year}년 처분분" },
  "misc.overview.tax.tile.deferredWash": { en: "Deferred wash sales", ko: "이연된 워시세일" },
  "misc.overview.tax.tile.openWindows": { en: "Open wash windows", ko: "열린 워시세일 기간" },
  "misc.overview.tax.tile.soonestClose": { en: "soonest closes {date}", ko: "가장 빠른 마감 {date}" },
  "misc.overview.tax.tile.washUnavailable": {
    en: "wash data unavailable",
    ko: "워시세일 데이터 없음",
  },
  "misc.overview.tax.yearEndLabel": { en: "Tax year-end", ko: "과세연도 마감" },

  // --- CountdownBar (components/CountdownBar.tsx) -----------------------------------------------------
  // Owned by the component, not by any one page that embeds it -- Overview's tax tile is the first
  // caller. See the component's own docstring for date mode vs. fraction mode.
  "misc.countdownBar.daysLeft_one": { en: "{days} day left", ko: "{days}일 남음" },
  "misc.countdownBar.daysLeft_other": { en: "{days} days left", ko: "{days}일 남음" },
  "misc.countdownBar.dueToday": { en: "Due today", ko: "오늘 마감" },
  "misc.countdownBar.overdue_one": { en: "{days} day overdue", ko: "{days}일 지남" },
  "misc.countdownBar.overdue_other": { en: "{days} days overdue", ko: "{days}일 지남" },
  "misc.countdownBar.ariaLabel": { en: "{label}: {caption}", ko: "{label}: {caption}" },

  // --- section: activity -----------------------------------------------------------------------------
  "misc.overview.section.activity": { en: "Activity", ko: "거래 내역" },
  "misc.overview.link.activity": { en: "Full activity log →", ko: "전체 거래 내역 보기 →" },
  "misc.overview.activity.skeletonWhat": { en: "activity", ko: "거래 내역" },
  "misc.overview.activity.failed": { en: "Activity failed to load.", ko: "거래 내역을 불러오지 못했습니다." },
  "misc.overview.activity.failedWithMessage": {
    en: "Activity failed to load: {message}",
    ko: "거래 내역을 불러오지 못했습니다: {message}",
  },
  "misc.overview.activity.tile.lastTransaction": { en: "Last transaction", ko: "최근 거래" },
  "misc.overview.activity.tile.lastTransactionHint": { en: "{action} {symbol}", ko: "{action} {symbol}" },
  "misc.overview.activity.tile.none": { en: "No transactions yet", ko: "아직 거래 내역 없음" },
  "misc.overview.activity.tile.total": { en: "Transactions", ko: "거래 건수" },
  "misc.overview.activity.tile.asOf": { en: "ledger as of {date}", ko: "{date} 기준 원장" },

  // --- section: filer consensus ----------------------------------------------------------------------
  "misc.overview.section.consensus": { en: "Filer consensus", ko: "제출인 컨센서스" },
  "misc.overview.link.consensus": { en: "Full consensus page →", ko: "전체 컨센서스 페이지 보기 →" },
  "misc.overview.consensus.skeletonWhat": { en: "filer consensus", ko: "제출인 컨센서스" },
  "misc.overview.consensus.tile.topBuy": { en: "Top consensus buy", ko: "최다 매수 컨센서스" },
  "misc.overview.consensus.tile.topSell": { en: "Top consensus sell", ko: "최다 매도 컨센서스" },
  "misc.overview.consensus.tile.buyerHint": {
    en: "{count} of {checked} filers buying",
    ko: "{checked}개 중 {count}개 제출인 매수",
  },
  "misc.overview.consensus.tile.sellerHint": {
    en: "{count} of {checked} filers selling",
    ko: "{checked}개 중 {count}개 제출인 매도",
  },
  "misc.overview.consensus.tile.none": { en: "No movers yet", ko: "아직 움직임 없음" },

  // --- cross-links to sibling systems (Strategy Lab, Market/Ticker) ----------------------------------
  "misc.overview.link.strategy": { en: "Strategy Lab →", ko: "전략 랩 보기 →" },
  "misc.overview.link.ticker": { en: "Ticker research →", ko: "티커 리서치 보기 →" },

  // =====================================================================================================
  // components/MacroKeyIndicators.tsx
  // =====================================================================================================
  "misc.keyIndicators.title": { en: "Key indicators", ko: "핵심 지표" },
  "misc.keyIndicators.notYetAvailable": { en: "Not yet available", ko: "아직 제공되지 않음" },
  "misc.keyIndicators.asOf": { en: "as of {date}", ko: "{date} 기준" },

  // =====================================================================================================
  // components/FearGreedGauge.tsx + components/FearGreedHistoryChart.tsx
  // =====================================================================================================
  "misc.fearGreed.title": { en: "Fear & Greed", ko: "공포·탐욕 지수" },
  "misc.fearGreed.unavailable": {
    en: "No reading available. The CNN endpoint is unreachable and the local composite could not be computed either.",
    ko: "표시할 값이 없습니다. CNN 엔드포인트에 연결할 수 없고 로컬 합성값도 계산할 수 없습니다.",
  },
  // `CNN` itself is an untranslated source name (rule 4); only the composite-methodology gloss is
  // translated, matching `macro.source.computed` translating "Computed" while `macro.source.cnn`
  // leaves "CNN" as-is.
  "misc.fearGreed.badge.composite": { en: "Composite (approximation)", ko: "합성값 (근사치)" },
  "misc.fearGreed.compositeNote": {
    en: "CNN’s index is unavailable. Computed locally from the same seven components — an approximation, not CNN’s number.",
    ko: "CNN 자체 지수를 현재 사용할 수 없습니다. 이 점수는 동일한 7개 공개 구성 요소를 바탕으로 로컬에서 계산되며 방향과 대략적인 수준은 반영하지만, CNN이 발표한 수치가 아닌 근사치입니다.",
  },

  // Rating words, Title Case -- `ratingLabel()`'s output in both FearGreedGauge.tsx and
  // FearGreedHistoryChart.tsx, and FearGreedGauge.tsx's own `BAND_LABELS` meter legend.
  "misc.fearGreed.rating.extremeFear": { en: "Extreme Fear", ko: "극단적 공포" },
  "misc.fearGreed.rating.fear": { en: "Fear", ko: "공포" },
  "misc.fearGreed.rating.neutral": { en: "Neutral", ko: "중립" },
  "misc.fearGreed.rating.greed": { en: "Greed", ko: "탐욕" },
  "misc.fearGreed.rating.extremeGreed": { en: "Extreme Greed", ko: "극단적 탐욕" },

  "misc.fearGreed.meterAriaLabel": { en: "Score {score} of 100, {rating}", ko: "점수 100점 중 {score}점, {rating}" },
  "misc.fearGreed.scoreDelta": { en: "{arrow} {sign}{delta} vs yesterday", ko: "{arrow} {sign}{delta} (전일 대비)" },
  "misc.fearGreed.prev.close": { en: "Previous close", ko: "전일 종가" },
  "misc.fearGreed.prev.week": { en: "1 week ago", ko: "1주 전" },
  "misc.fearGreed.prev.month": { en: "1 month ago", ko: "1개월 전" },
  "misc.fearGreed.prev.year": { en: "1 year ago", ko: "1년 전" },
  "misc.fearGreed.asOf": { en: "as of {date}", ko: "{date} 기준" },

  "misc.fearGreed.table.component": { en: "Component", ko: "구성 요소" },
  "misc.fearGreed.table.raw": { en: "Raw", ko: "원값" },
  "misc.fearGreed.table.score": { en: "Score", ko: "점수" },
  "misc.fearGreed.table.rating": { en: "Rating", ko: "등급" },
  "misc.fearGreed.table.asOf": { en: "As of", ko: "기준일" },
  "misc.fearGreed.table.scoreComputedHere": { en: "computed here", ko: "여기서 계산됨" },
  "misc.fearGreed.table.scoreNotPublished": { en: "not published by CNN", ko: "CNN이 공개하지 않음" },
  "misc.fearGreed.table.scoreTitleComposite": {
    en: "Each component's 0-100 contribution, computed locally by the fallback composite.",
    ko: "각 구성 요소의 0-100 기여도로, 폴백 합성값이 로컬에서 계산합니다.",
  },
  "misc.fearGreed.table.scoreTitleCnn": {
    en: "CNN publishes each raw value and rating, not the 0-100 score. Filled in only when the local composite is the source.",
    ko: "CNN은 각 구성 요소의 원값과 등급은 공개하지만 이를 0-100으로 정규화한 값은 공개하지 않습니다. 이 열은 로컬 합성값이 출처일 때만 채워집니다.",
  },

  // Band-line labels drawn on FearGreedHistoryChart's plot and legend -- sentence case, distinct
  // literal strings from the Title Case rating words above (rule 1: byte-identical per call site).
  // `Fear`/`Greed` alone read the same either way, so those two price lines reuse `rating.fear` /
  // `rating.greed` rather than duplicating an identical string under a second key.
  "misc.fearGreed.band.extremeFear": { en: "Extreme fear", ko: "극단적 공포" },
  "misc.fearGreed.band.extremeGreed": { en: "Extreme greed", ko: "극단적 탐욕" },

  "misc.fearGreed.history.rangeAriaLabel": { en: "Fear & Greed history range", ko: "공포·탐욕 지수 기간 범위" },
  "misc.fearGreed.history.chartAriaLabel": { en: "Fear & Greed history chart, {span}", ko: "공포·탐욕 지수 추이 차트, {span}" },
  "misc.fearGreed.history.hoverPrompt": {
    en: "Hover the line to read any day",
    ko: "선 위에 마우스를 올리면 날짜별 값을 볼 수 있습니다",
  },
  "misc.fearGreed.history.noHistory": {
    en: "No history available. The local composite fallback carries none, so a composite-sourced reading has no line to draw.",
    ko: "이력 데이터가 없습니다. CNN은 공포·탐욕 지수 이력을 제공하지만 로컬 합성값 폴백에는 이력이 없어, 이 값이 합성값에서 나온 경우 그릴 선이 없습니다.",
  },
  "misc.fearGreed.history.noObservationsInRange": {
    en: "No observations in this range.",
    ko: "이 기간에는 관측치가 없습니다.",
  },

  // =====================================================================================================
  // components/EventCalendar.tsx (+ Overview.tsx's EventCalendarCard, which shares the empty-state
  // and heading strings below)
  // =====================================================================================================
  "misc.eventCalendar.heading": { en: "Calendar", ko: "경제 캘린더" },
  "misc.eventCalendar.collapseButton": { en: "Collapse ▴", ko: "접기 ▴" },
  "misc.eventCalendar.expandButton": { en: "Expand ▾", ko: "펼치기 ▾" },
  "misc.eventCalendar.coverage": {
    en: "Earnings dates for {covered} of {total} holdings",
    ko: "전체 보유 종목 {total}개 중 {covered}개의 실적 발표일",
  },
  "misc.eventCalendar.snapshotProvenance": {
    en: "Rows badged “snapshot” come from a committed FOMC schedule, not a live Federal Reserve feed.",
    ko: "“snapshot” 배지가 붙은 행은 실시간 연준 피드가 아니라 커밋된 FOMC 일정에서 가져온 것입니다.",
  },
  "misc.eventCalendar.noEvents": {
    en: "No scheduled events in the next 60 days.",
    ko: "향후 60일 이내 예정된 이벤트가 없습니다.",
  },
  "misc.eventCalendar.badge.estimated": { en: "est.", ko: "추정" },
  "misc.eventCalendar.badge.snapshot": { en: "snapshot", ko: "스냅샷" },

  // `fomc` stays the untranslated institution acronym (rule 4), same as `CNN`/`FRED` elsewhere.
  "misc.eventCalendar.kind.fomc": { en: "FOMC", ko: "FOMC" },
  "misc.eventCalendar.kind.earnings": { en: "Earnings", ko: "실적" },
  "misc.eventCalendar.kind.economicRelease": { en: "Release", ko: "발표" },

  "misc.eventCalendar.relative.today": { en: "today", ko: "오늘" },
  "misc.eventCalendar.relative.tomorrow": { en: "tomorrow", ko: "내일" },
  "misc.eventCalendar.relative.inDays": { en: "in {days} days", ko: "{days}일 후" },
  "misc.eventCalendar.relative.yesterday": { en: "yesterday", ko: "어제" },
  "misc.eventCalendar.relative.daysAgo": { en: "{days} days ago", ko: "{days}일 전" },

  // =====================================================================================================
  // pages/Personas.tsx + components/PersonaCard.tsx + api/personas.ts
  // =====================================================================================================
  "misc.personas.title": { en: "Personas", ko: "페르소나" },
  "misc.personas.subtitle": {
    en: "Per followed influencer: their recent takes — never a signal or recommendation.",
    ko: "팔로우한 인플루언서의 최근 발언 요약 -- 그들의 견해일 뿐, 시그널이나 추천이 아닙니다.",
  },
  "misc.personas.form.handle": { en: "Handle", ko: "핸들" },
  "misc.personas.form.platform": { en: "Platform", ko: "플랫폼" },
  // `YouTube` is a brand/platform identifier and stays untranslated, same as `CNN`/`FRED` (rule 4).
  "misc.personas.form.platformYoutube": { en: "YouTube", ko: "YouTube" },
  "misc.personas.form.platformManual": { en: "Manual", ko: "수동" },
  "misc.personas.form.adding": { en: "Adding…", ko: "추가하는 중…" },
  "misc.personas.form.submit": { en: "Add persona", ko: "페르소나 추가" },
  "misc.personas.form.handleRequired": { en: "A handle is required.", ko: "핸들을 입력해야 합니다." },
  "misc.personas.loading": { en: "Loading personas…", ko: "페르소나 불러오는 중…" },
  "misc.personas.empty": {
    en: "No personas followed yet -- add one above.",
    ko: "아직 팔로우한 페르소나가 없습니다 -- 위에서 추가하세요.",
  },

  // --- PersonaCard.tsx --------------------------------------------------------------------------------
  "misc.personas.card.noSourceConfigured": { en: "no source configured yet", ko: "아직 소스가 설정되지 않음" },
  "misc.personas.card.noteCount_one": { en: "{count} note", ko: "{count}개 노트" },
  "misc.personas.card.noteCount_other": { en: "{count} notes", ko: "{count}개 노트" },
  "misc.personas.card.updatedAge": { en: "updated {age}", ko: "{age} 업데이트됨" },
  "misc.personas.card.noNotesYet": { en: "no notes yet", ko: "아직 노트 없음" },
  "misc.personas.card.factCheckFailed": { en: "Fact-check failed.", ko: "팩트체크 실패." },
  "misc.personas.card.factCheckDetail": {
    en: "Some of {name}’s summaries failed grounding and are shown anyway — treat the specifics as unverified, not hidden.",
    ko: "{name}의 요약 중 일부는 근거 확인을 통과하지 못했지만 그대로 표시됩니다 -- 세부 내용은 숨기지 않되 검증되지 않은 것으로 간주하세요.",
  },
  "misc.personas.card.noNotesEmpty": {
    en: "No notes ingested yet for {name}. Run an ingest below to pull in what they have said recently.",
    ko: "{name}에 대해 아직 수집된 노트가 없습니다. 아래에서 수집을 실행해 최근 발언을 가져오세요.",
  },
  "misc.personas.card.recentTakeLabel": { en: "Their recent take:", ko: "최근 견해:" },
  "misc.personas.card.focusedOnHeader": { en: "What they’re focused on", ko: "주목하고 있는 주제" },
  "misc.personas.card.viewByTickerHeader": { en: "Their view, by ticker", ko: "종목별 견해" },
  "misc.personas.card.noteDegraded": {
    en: "Their latest note specifically failed its fact-check too.",
    ko: "가장 최근 노트도 팩트체크를 통과하지 못했습니다.",
  },
  "misc.personas.card.removing": { en: "Removing…", ko: "제거하는 중…" },
  "misc.personas.card.removeButton": { en: "Remove persona", ko: "페르소나 제거" },

  // --- stance labels (api/personas.ts, read by PersonaCard.tsx) ---------------------------------------
  // `unclear` reads as "no clear stance", deliberately not folded into "neutral" -- see this module's
  // own docstring on copy discipline.
  "misc.personas.stance.bullish": { en: "bullish", ko: "강세" },
  "misc.personas.stance.bearish": { en: "bearish", ko: "약세" },
  "misc.personas.stance.neutral": { en: "neutral", ko: "중립" },
  "misc.personas.stance.unclear": { en: "no clear stance", ko: "명확한 입장 없음" },

  // --- ingest panel ------------------------------------------------------------------------------------
  "misc.personas.ingest.modeAriaLabel": { en: "Ingest mode", ko: "수집 모드" },
  "misc.personas.ingest.tabRecent": { en: "Recent videos", ko: "최근 영상" },
  "misc.personas.ingest.tabSpecific": { en: "Specific videos", ko: "특정 영상" },
  "misc.personas.ingest.tabDrop": { en: "Paste text", ko: "텍스트 붙여넣기" },
  "misc.personas.ingest.limitLabel": { en: "How many recent videos", ko: "최근 영상 개수" },
  "misc.personas.ingest.urlsLabel": {
    en: "Video URLs or ids, one per line",
    ko: "영상 URL 또는 ID, 한 줄에 하나씩",
  },
  "misc.personas.ingest.urlsPlaceholder": {
    en: "https://www.youtube.com/watch?v=...\nor a bare 11-character video id",
    ko: "https://www.youtube.com/watch?v=...\n또는 11자리 영상 ID",
  },
  "misc.personas.ingest.titleLabel": { en: "Title (optional)", ko: "제목 (선택)" },
  "misc.personas.ingest.urlLabel": { en: "Source URL (optional)", ko: "출처 URL (선택)" },
  "misc.personas.ingest.textLabel": { en: "Paste the text", ko: "텍스트 붙여넣기" },
  "misc.personas.ingest.textPlaceholder": {
    en: "Paste the post or transcript text here",
    ko: "게시물이나 자막 텍스트를 여기에 붙여넣으세요",
  },
  "misc.personas.ingest.starting": { en: "Starting ingest…", ko: "수집 시작하는 중…" },
  "misc.personas.ingest.active": { en: "Ingesting…", ko: "수집하는 중…" },
  "misc.personas.ingest.submit": { en: "Start ingest", ko: "수집 시작" },
  "misc.personas.ingest.progress": { en: "{state} -- {done}/{total} items", ko: "{state} -- {done}/{total}개 항목" },
  "misc.personas.ingest.progressFailed": {
    en: "{state} -- {done}/{total} items, {failed} failed",
    ko: "{state} -- {done}/{total}개 항목, {failed}개 실패",
  },
  "misc.personas.ingest.spent": { en: "{amount} spent", ko: "{amount} 사용" },

  // --- mutation fallback errors (Personas.tsx call sites into describePersonaActionError) -------------
  "misc.personas.error.addFailed": { en: "Could not add this persona.", ko: "이 페르소나를 추가할 수 없습니다." },
  "misc.personas.error.ingestFailed": {
    en: "Could not start an ingest for this persona.",
    ko: "이 페르소나의 수집을 시작할 수 없습니다.",
  },
  "misc.personas.error.removeFailed": {
    en: "Could not remove this persona.",
    ko: "이 페르소나를 제거할 수 없습니다.",
  },

  // --- api/personas.ts: formatRelativeAge -------------------------------------------------------------
  // Local copy of the same relative-age shape as `macro.news.age.*` (that key lives in a different
  // shard backing a different `formatRelativeAge` copy in `api/news.ts` -- see this file's own
  // docstring on the "one copy per module" convention).
  "misc.personas.age.justNow": { en: "just now", ko: "방금 전" },
  "misc.personas.age.minutes": { en: "{count}m ago", ko: "{count}분 전" },
  "misc.personas.age.hours": { en: "{count}h ago", ko: "{count}시간 전" },
  "misc.personas.age.days": { en: "{count}d ago", ko: "{count}일 전" },

  // --- Phase 2: consolidated profile (PersonaProfile.tsx) --------------------------------------
  "misc.personas.profile.heading": { en: "Persona profile", ko: "페르소나 프로필" },
  "misc.personas.profile.loading": { en: "Loading profile…", ko: "프로필 불러오는 중…" },
  "misc.personas.profile.notConsolidated": {
    en: "{name} has not been consolidated yet.",
    ko: "{name}은(는) 아직 통합되지 않았습니다.",
  },
  "misc.personas.profile.noNotesReason": {
    en: "Add notes for {name} before consolidating -- there is nothing yet to fold into a profile.",
    ko: "통합하기 전에 {name}의 노트를 추가하세요. 아직 프로필로 정리할 내용이 없습니다.",
  },
  "misc.personas.profile.consolidate": { en: "Consolidate", ko: "통합" },
  "misc.personas.profile.reconsolidate": { en: "Re-consolidate", ko: "다시 통합" },
  "misc.personas.profile.consolidating": { en: "Consolidating…", ko: "통합하는 중…" },
  "misc.personas.profile.version": { en: "v{version}", ko: "v{version}" },
  "misc.personas.profile.builtFrom_one": {
    en: "built from {count} note",
    ko: "노트 {count}개로 작성",
  },
  "misc.personas.profile.builtFrom_other": {
    en: "built from {count} notes",
    ko: "노트 {count}개로 작성",
  },
  "misc.personas.profile.consolidatedAge": { en: "consolidated {age}", ko: "{age} 통합됨" },
  "misc.personas.profile.degradedTitle": { en: "Fact-check failed.", ko: "사실 확인 실패." },
  "misc.personas.profile.degradedBody": {
    en: "This profile was released despite failing its grounding check -- treat it with extra caution.",
    ko: "이 프로필은 근거 확인에 실패했음에도 공개되었습니다. 각별히 주의해서 보세요.",
  },
  "misc.personas.profile.beliefs": { en: "What they believe", ko: "그들의 생각" },
  "misc.personas.profile.playbook": { en: "How they trade", ko: "그들의 매매 방식" },
  "misc.personas.profile.vocabulary": { en: "Words they use", ko: "자주 쓰는 표현" },
  "misc.personas.profile.theses": { en: "Their view, by ticker", ko: "종목별 견해" },
  "misc.personas.profile.citationsLabel": { en: "citations", ko: "인용" },
  "misc.personas.profile.citationTitle": { en: "note: {noteId}", ko: "노트: {noteId}" },

  // --- Phase 3a: call scorecard (PersonaScorecard.tsx) ----------------------------------------
  "misc.personas.scorecard.heading": { en: "Call scorecard", ko: "콜 스코어카드" },
  "misc.personas.scorecard.caption": {
    en: "How {name}'s past ticker calls would have looked if acted on that day — descriptive, not a claim or advice.",
    ko: "{name}이(가) 과거에 언급한 종목 콜을 그 발언 당일에 실행했다면 어땠을지 보여줍니다. 이는 사후적·서술적 기록이며, 시장을 이겼다는 주장도 투자 조언도 아닙니다.",
  },
  "misc.personas.scorecard.loading": { en: "Loading scorecard…", ko: "스코어카드 불러오는 중…" },
  "misc.personas.scorecard.hitRate": { en: "Hit rate", ko: "적중률" },
  "misc.personas.scorecard.hitRateNone": {
    en: "Not enough scored calls yet",
    ko: "채점된 콜이 아직 충분하지 않습니다",
  },
  "misc.personas.scorecard.medianReturn": { en: "Median return", ko: "수익률 중앙값" },
  "misc.personas.scorecard.medianNone": { en: "Not enough data yet", ko: "데이터가 아직 충분하지 않습니다" },
  "misc.personas.scorecard.empty": { en: "No dated calls to score yet.", ko: "채점할 날짜별 콜이 아직 없습니다." },

  // --- call outcome badges (api/personas.ts outcomeLabel) --------------------------------------
  "misc.personas.outcome.playedOut": { en: "played out", ko: "적중" },
  "misc.personas.outcome.wentAgainst": { en: "went against", ko: "빗나감" },
  "misc.personas.outcome.flat": { en: "flat", ko: "보합" },
  "misc.personas.outcome.notDirectional": { en: "no clear call", ko: "방향성 없음" },
  "misc.personas.outcome.pending": { en: "too recent", ko: "너무 최근" },
  "misc.personas.outcome.noData": { en: "no price data", ko: "가격 데이터 없음" },

  // --- price-basis footnote (api/personas.ts callBasisNote) ------------------------------------
  "misc.personas.basis.adjusted": {
    en: "Return uses adjusted close (dividends/splits included).",
    ko: "수익률은 수정 종가 기준입니다(배당·분할 반영).",
  },
  "misc.personas.basis.close": {
    en: "Return uses raw close price (adjusted close was not available for this call).",
    ko: "수익률은 원 종가 기준입니다(이 콜에는 수정 종가를 사용할 수 없었습니다).",
  },

  // --- list page (Personas.tsx): compact per-persona row linking to /personas/{slug} -----------------
  "misc.personas.list.viewDetail": { en: "View full desk", ko: "전체 데스크 보기" },
  "misc.personas.list.viewDetailAria": {
    en: "View {name}'s full desk",
    ko: "{name}의 전체 데스크 보기",
  },

  // --- detail page (pages/personas/PersonaDetail.tsx) -------------------------------------------------
  "misc.personas.detail.backLink": { en: "← Back to personas", ko: "← 페르소나로 돌아가기" },
  "misc.personas.detail.notFoundTitle": { en: "Persona not found", ko: "페르소나를 찾을 수 없습니다" },
  "misc.personas.detail.notFoundBody": {
    en: "No followed persona matches “{slug}”.",
    ko: "“{slug}”와 일치하는 팔로우한 페르소나가 없습니다.",
  },

  // =====================================================================================================
  // components/AllocationPie.tsx
  // =====================================================================================================

  "misc.alloc.modeAriaLabel": { en: "Allocation view", ko: "배분 보기" },
  "misc.alloc.modeTicker": { en: "By ticker", ko: "종목별" },
  "misc.alloc.modeSector": { en: "By sector", ko: "섹터별" },
  "misc.alloc.other": { en: "Other", ko: "기타" },
  "misc.alloc.empty": { en: "No allocation data", ko: "배분 데이터 없음" },
  "misc.alloc.donutLabel_one": {
    en: "{title}, {count} slice",
    ko: "{title}, {count}개 항목",
  },
  "misc.alloc.donutLabel_other": {
    en: "{title}, {count} slices",
    ko: "{title}, {count}개 항목",
  },
  "misc.alloc.legendButtonLabel": {
    en: "{label}, {value}, {percent}",
    ko: "{label}, {value}, {percent}",
  },
} as const satisfies MessageShard;
