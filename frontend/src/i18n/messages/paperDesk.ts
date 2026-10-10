/**
 * Paper Desk page shell, desk panel, book statistics and paperdesk APIs.
 *
 * Keys are prefixed `paperDesk.` -- see `catalog.ts` for the convention and why the prefix is
 * load-bearing (the duplicate-key guard in `i18n.test.tsx` keys off it).
 */
import type { MessageShard } from "@/i18n/types";

export const paperDesk = {
  // --- PaperDesk.tsx: page shell -------------------------------------------
  "paperDesk.title": { en: "Paper Desk", ko: "페이퍼 데스크" },
  "paperDesk.subtitle_one": {
    en: "{count} strategy, {books} books ({list}), from {date}.",
    ko: "{books}개 북({list}), {date}부터 전략 {count}개.",
  },
  "paperDesk.subtitle_other": {
    en: "{count} strategies, {books} books ({list}), from {date}.",
    ko: "{books}개 북({list}), {date}부터 전략 {count}개.",
  },
  "paperDesk.subtitleLoading": {
    en: "Live paper-trading strategies, each on its own fixed cash, traded on stored daily bars.",
    ko: "실시간 페이퍼 트레이딩 전략들 -- 각각 고정 현금으로 시작해 저장된 일별 바로 거래합니다.",
  },
  "paperDesk.framingNote": {
    en: "Each desk: own simulated capital, own rules -- not a combined portfolio. Book totals aren't comparable across books.",
    ko: "각 데스크는 자체 모의 자본과 규칙으로 운용됩니다 -- 통합 포트폴리오가 아니며, 북 간 합계도 비교할 수 없습니다.",
  },
  "paperDesk.framingNoteLoading": {
    en: "Each desk: its own simulated cash, own rules -- not a combined portfolio. No desk total is a suggested allocation.",
    ko: "각 데스크는 자체 모의 현금과 규칙으로 운용됩니다 -- 통합 포트폴리오가 아니며, 데스크 간 합계도 권장 배분이 아닙니다.",
  },
  "paperDesk.loading": { en: "Loading Paper Desk…", ko: "페이퍼 데스크를 불러오는 중…" },
  "paperDesk.apiError": {
    en: "API returned {status}: {message}",
    ko: "API가 {status} 응답을 반환했습니다: {message}",
  },
  "paperDesk.cannotReachApi": {
    en: "Cannot reach the API. Is uvicorn running on port 8000?",
    ko: "API에 연결할 수 없습니다. 포트 8000에서 uvicorn이 실행 중인가요?",
  },
  "paperDesk.refreshFailedApi": {
    en: "Refresh failed -- API returned {status}: {message}",
    ko: "새로고침 실패 -- API가 {status} 응답을 반환했습니다: {message}",
  },
  "paperDesk.refreshFailedUnreachable": {
    en: "Refresh failed -- cannot reach the API.",
    ko: "새로고침 실패 -- API에 연결할 수 없습니다.",
  },
  "paperDesk.inceptionUnreachable": {
    en: "Could not change the inception date -- cannot reach the API.",
    ko: "개시일을 변경할 수 없습니다 -- API에 연결할 수 없습니다.",
  },

  // --- PaperDesk.tsx: PanelBoundary labels ----------------------------------
  "paperDesk.panel.liveTape": { en: "Live tape", ko: "체결 테이프" },
  "paperDesk.panel.inceptionControl": { en: "Inception control", ko: "개시일 설정" },
  "paperDesk.panel.deskHeader": { en: "Desk header", ko: "데스크 헤더" },
  "paperDesk.panel.inSampleWarning": { en: "In-sample warning", ko: "표본 내 경고" },
  "paperDesk.panel.bookSection": { en: "{label} book", ko: "{label} 북" },
  "paperDesk.panel.afterTax": { en: "{name} after tax", ko: "{name} 세후" },

  // The desk card's long-form disclosure -- book statistics, broker refusals, the live-quote
  // projection and the card's own rules block. Named for what is behind it, not "more".
  "paperDesk.desk.moreDetails": { en: "Statistics & details", ko: "통계 및 상세" },

  "paperDesk.recomputeOverlay": {
    en: "Re-running every agent from {date}…",
    ko: "{date}부터 모든 에이전트를 재실행하는 중…",
  },
  "paperDesk.recomputeDetail": {
    en: "A cold roster costs seconds per card -- this deliberately re-runs every one of them.",
    ko: "콜드 스타트 상태의 로스터는 카드마다 몇 초씩 걸립니다 -- 의도적으로 모든 카드를 재실행합니다.",
  },
  "paperDesk.viewTabsAriaLabel": { en: "Paper desk book", ko: "페이퍼 데스크 북" },

  // --- PaperDesk.tsx: AfterTaxPanel ------------------------------------------
  "paperDesk.afterTax.title": { en: "{name} — after tax", ko: "{name} — 세후" },
  "paperDesk.afterTax.statutoryUpperBoundRate": {
    en: "statutory upper-bound rate",
    ko: "법정 상한 세율",
  },
  "paperDesk.afterTax.rateNote": {
    en: "{start}-{end}: short-term at {shortRate}, long-term at {longRate}. A net loss owes nothing -- never a rebate.",
    ko: "{start}~{end}: 단기 {shortRate}, 장기 {longRate}. 순손실은 세금 0 -- 환급은 없습니다.",
  },
  "paperDesk.afterTax.netRealisedGain": { en: "Net realized gain", ko: "순 실현 손익" },
  "paperDesk.afterTax.shortTermGain": { en: "Short-term gain", ko: "단기 손익" },
  "paperDesk.afterTax.longTermGain": { en: "Long-term gain", ko: "장기 손익" },
  "paperDesk.afterTax.taxOwed": { en: "Tax owed", ko: "납부할 세금" },
  "paperDesk.afterTax.afterTaxRealisedGain": { en: "After-tax realized gain", ko: "세후 실현 손익" },
  "paperDesk.afterTax.washSalesHeading": { en: "Wash sales", ko: "워시세일" },
  "paperDesk.afterTax.noWashSales": {
    en: "No wash sale disallowed over this window.",
    ko: "이 기간 동안 부인된 워시세일이 없습니다.",
  },
  "paperDesk.afterTax.lossDate": { en: "Loss date", ko: "손실일" },
  "paperDesk.afterTax.repurchaseDate": { en: "Repurchase date", ko: "재매수일" },
  "paperDesk.afterTax.disallowedAmount": { en: "Disallowed amount", ko: "부인 금액" },

  // --- PaperDesk.tsx: InSampleWarning -----------------------------------------
  "paperDesk.inSample.strong": {
    en: "{count} of this window’s sessions fall at or before the strategy design cutoff ({cutoff}).",
    ko: "이 기간의 세션 중 {count}개가 전략 설계 기준일({cutoff}) 이전이거나 그 날짜입니다.",
  },
  "paperDesk.inSample.unknown": { en: "unknown", ko: "알 수 없음" },
  "paperDesk.inSample.body": {
    en: "Fitted, not forward -- these cards were designed using data through this date, so returns here don't show real skill yet.",
    ko: "표본 내(피팅된) 결과이며 표본 외(순방향) 결과가 아닙니다 -- 카드는 이 날짜까지의 데이터로 설계되었으므로, 아직 실전 성과를 보여주지 않습니다.",
  },

  // --- PaperDesk.tsx: InceptionControl ----------------------------------------
  "paperDesk.inception.label": { en: "Inception", ko: "개시" },
  "paperDesk.inception.applying": { en: "Applying…", ko: "적용 중…" },
  "paperDesk.inception.resetTitle": {
    en: "Return to the built-in default inception, {date}",
    ko: "내장된 기본 개시일인 {date}로 되돌립니다.",
  },
  "paperDesk.inception.resetLabel": {
    en: "Reset to default ({date})",
    ko: "기본값으로 재설정 ({date})",
  },
  "paperDesk.inception.hint": {
    en: "Changes every book's window and re-runs every agent from this date. Fetches no data; doesn't change seated strategies.",
    ko: "모든 북의 거래 기간을 변경하고 이 날짜부터 모든 에이전트를 재실행합니다. 새 데이터는 가져오지 않으며 배정된 전략도 바뀌지 않습니다.",
  },
  "paperDesk.inception.confirmQuestion": {
    en: "Recompute every book from {date}?",
    ko: "{date}부터 모든 북을 다시 계산할까요?",
  },
  "paperDesk.inception.confirmPreview": {
    en: "Recomputes every book ({books}), {count} in total, from this date. No new data fetched; seated strategies unchanged.",
    ko: "{books}({count}개) 모든 북을 이 날짜부터 다시 계산합니다. 새 데이터는 가져오지 않으며 배정된 전략도 바뀌지 않습니다.",
  },
  "paperDesk.inception.appliedToast": {
    en: "Every book recomputed from {date}.",
    ko: "모든 북이 {date}부터 다시 계산되었습니다.",
  },

  // --- DeskPanel.tsx: badges and dormant states --------------------------------
  "paperDesk.autopilot.universeScreen": { en: "screened universe", ko: "스크리닝 유니버스" },
  "paperDesk.autopilot.universeCard": { en: "card universe", ko: "카드 유니버스" },
  "paperDesk.autopilot.armBadgeTitle": {
    en: 'Study arm "{arm}" -- which of the four Agent Workflow study arms this seat trades.',
    ko: '스터디 암 "{arm}" -- 이 좌석이 거래하는 에이전트 워크플로우 4개 스터디 암 중 하나입니다.',
  },
  "paperDesk.dormant.badgeTitle": {
    en: "No position has been opened and no trade closed since inception.",
    ko: "개시 이후 개설된 포지션도, 청산된 거래도 없습니다.",
  },
  "paperDesk.dormant.badge": { en: "no trades since inception", ko: "개시 이후 거래 없음" },
  "paperDesk.provenance.promoted": { en: "Promoted · gen {generation}", ko: "승격됨 · {generation}세대" },
  "paperDesk.provenance.promotedTitle": {
    en: "Auto-promoted through the evolution loop. Opens the Loop view.",
    ko: "진화 루프를 통해 자동 승격되었습니다. 루프 보기를 엽니다.",
  },
  "paperDesk.provenance.owner": { en: "Owner-selected", ko: "소유자 선정" },
  "paperDesk.provenance.ownerTitle": {
    en: "Seated by an owner decision, not an automated gate.",
    ko: "자동 게이트가 아닌 소유자 결정으로 배치되었습니다.",
  },
  "paperDesk.autopilot.buysOnlyStrong": {
    en: "Buy-only desk -- never sells.",
    ko: "매수 전용 데스크 -- 매도하지 않음.",
  },
  "paperDesk.autopilot.buysOnlyRest": {
    en: "The card's stop, target and hold-cap rules never apply here. Read its return accordingly.",
    ko: "카드의 손절/목표가/보유기간 규칙이 이 체결에는 적용되지 않습니다. 이를 감안해 수익률을 해석하십시오.",
  },
  "paperDesk.autopilot.exitsNoteLabel": {
    en: "How this desk closes positions:",
    ko: "이 데스크가 포지션을 청산하는 방식:",
  },
  "paperDesk.dormant.rulesDeskNote": {
    en: "No trades yet -- entry rule never fired.",
    ko: "거래 없음 -- 진입 규칙이 발동한 적 없음.",
  },
  "paperDesk.dormant.rulesDeskDetail": {
    en: "Full cash held since inception: flat means no trade, not breakeven.",
    ko: "개시 이후 전액 현금 보유: 수익률 0%는 거래 안 함이지 손익분기가 아닙니다.",
  },
  "paperDesk.autopilot.dormantNote": {
    en: "No trades yet -- no staged order has filled.",
    ko: "거래 없음 -- 체결된 주문이 아직 없습니다.",
  },
  "paperDesk.autopilot.dormantDetail": {
    en: "Holding full cash: flat means no trade, not breakeven.",
    ko: "전액 현금 보유 중: 수익률 0%는 거래 안 함이지 손익분기가 아닙니다.",
  },
  "paperDesk.autopilot.lastRunReported": {
    en: "The last run{dateClause} reported:",
    ko: "마지막 실행{dateClause}의 결과:",
  },
  "paperDesk.autopilot.noRunRecorded": {
    en: "No run has been recorded for this seat yet.",
    ko: "이 좌석에 대해 아직 기록된 실행이 없습니다.",
  },

  // --- DeskPanel.tsx: RejectionsCallout / RejectionGroup ------------------------
  "paperDesk.rejections.headline_one": {
    en: "{count} order the broker refused this session:",
    ko: "이번 세션에 브로커가 거부한 주문 {count}건:",
  },
  "paperDesk.rejections.headline_other": {
    en: "{count} orders the broker refused this session:",
    ko: "이번 세션에 브로커가 거부한 주문 {count}건:",
  },
  "paperDesk.rejections.body": {
    en: "a rejected order means the desk did not run exactly as its own rules would have produced.",
    ko: "거부된 주문은 데스크가 자체 규칙대로 정확히 실행되지 않았음을 의미합니다.",
  },
  "paperDesk.rejections.summary_one": {
    en: "{label} — {count} order{symbolsClause}",
    ko: "{label} — 주문 {count}건{symbolsClause}",
  },
  "paperDesk.rejections.summary_other": {
    en: "{label} — {count} orders{symbolsClause}",
    ko: "{label} — 주문 {count}건{symbolsClause}",
  },

  // --- DeskPanel.tsx: UpcomingSignals / UpcomingSignalList / QueueNote ----------
  "paperDesk.upcoming.title": { en: "What it would do next", ko: "다음에 할 일" },
  "paperDesk.upcoming.note": {
    en: "As of the desk's last close ({asOf}): the {next} session's decision, not a trade yet made.",
    ko: "데스크의 마지막 종가({asOf}) 기준: {next} 세션의 결정이며, 아직 이루어진 거래가 아닙니다.",
  },
  "paperDesk.upcoming.nextWord": { en: "next", ko: "다음" },
  "paperDesk.upcoming.empty": {
    en: "No entry or exit signal fired at the last close.",
    ko: "마지막 종가에서 발동한 진입 또는 청산 신호가 없습니다.",
  },
  "paperDesk.upcoming.signalBadge": { en: "{title} signal -- {count}", ko: "{title} 신호 -- {count}" },
  "paperDesk.queue.rankedBy": {
    en: "Ranked by {rankBy}, highest first.",
    ko: "{rankBy} 기준 내림차순으로 정렬되었습니다.",
  },
  "paperDesk.queue.slotsFree_one": {
    en: "{count} slot free, so this queue reaches #{count} if cash allows.",
    ko: "여유 슬롯 {count}개, 자금이 허용하면 이 대기열은 #{count}까지 도달합니다.",
  },
  "paperDesk.queue.slotsFree_other": {
    en: "{count} slots free, so this queue reaches #{count} if cash allows.",
    ko: "여유 슬롯 {count}개, 자금이 허용하면 이 대기열은 #{count}까지 도달합니다.",
  },
  "paperDesk.queue.noSlotFree": {
    en: "No slot is free -- nothing here is bought until a position closes.",
    ko: "여유 슬롯이 없습니다 -- 포지션이 청산되기 전까지는 여기서 아무것도 매수되지 않습니다.",
  },

  // --- DeskPanel.tsx: StagedOrders ------------------------------------------------
  "paperDesk.staged.title": { en: "What it has already committed to", ko: "이미 확정한 사항" },
  "paperDesk.staged.note": {
    en: "Staged, awaiting the next open -- not a prediction. A past {code}: the step hasn't run; orders never silently expire.",
    ko: "이미 등록되어 다음 시가를 기다리는 주문입니다 -- 예측이 아닙니다. {code}가 과거면 일일 단계가 아직 실행되지 않은 것이며, 주문은 조용히 만료되지 않습니다.",
  },
  "paperDesk.staged.side": { en: "Side", ko: "매매 구분" },
  "paperDesk.staged.notional": { en: "Notional", ko: "명목 금액" },
  "paperDesk.staged.decisionDate": { en: "Decision date", ko: "결정일" },
  "paperDesk.staged.fillDate": { en: "Fill date", ko: "체결일" },
  "paperDesk.staged.regime": { en: "Regime", ko: "국면" },

  // --- DeskPanel.tsx: LiveExecution / LiveFillRow ---------------------------------
  "paperDesk.live.badgeTitle": {
    en: "Priced against a real-time quote, recomputed on every refresh -- not the desk's audited trade history.",
    ko: "실시간 시세로 가격이 매겨지며 새로고침할 때마다 다시 계산됩니다 -- 데스크의 감사된 거래 기록이 아닙니다.",
  },
  "paperDesk.live.badge": { en: "Live", ko: "실시간" },
  "paperDesk.live.headline_one": {
    en: "{count} fill at the live quote{rejectionClause}",
    ko: "실시간 시세 기준 체결 {count}건{rejectionClause}",
  },
  "paperDesk.live.headline_other": {
    en: "{count} fills at the live quote{rejectionClause}",
    ko: "실시간 시세 기준 체결 {count}건{rejectionClause}",
  },
  "paperDesk.live.rejectionClause_one": {
    en: ", {count} order the broker would refuse",
    ko: ", 브로커가 거부할 주문 {count}건",
  },
  "paperDesk.live.rejectionClause_other": {
    en: ", {count} orders the broker would refuse",
    ko: ", 브로커가 거부할 주문 {count}건",
  },
  "paperDesk.live.note": {
    en: "Live projection -- not an actual trade.",
    ko: "실시간 예측치 -- 실제 거래가 아닙니다.",
  },
  "paperDesk.live.noteDetail": {
    en: "Recomputed on every refresh; separate from the audited record below.",
    ko: "새로고침마다 재계산되며, 아래 감사된 기록과는 별개입니다.",
  },
  "paperDesk.live.fillDetail": { en: "Fill detail", ko: "체결 상세" },
  "paperDesk.live.quotePrice": { en: " (quote {price})", ko: " (시세 {price})" },
  "paperDesk.asOfLower": { en: "as of {date}", ko: "{date} 기준" },

  // --- DeskPanel.tsx: RecentActivity -----------------------------------------------
  "paperDesk.recent.title": { en: "What it just did", ko: "방금 한 일" },
  "paperDesk.noDecisionsYet": { en: "No decisions recorded yet.", ko: "아직 기록된 결정이 없습니다." },

  // --- DeskPanel.tsx: HoldingsTable -------------------------------------------------
  "paperDesk.holdings.title": { en: "Holdings", ko: "보유 종목" },
  "paperDesk.holdings.empty": { en: "No open positions.", ko: "보유 중인 포지션이 없습니다." },
  "paperDesk.holdings.filterPlaceholder": { en: "Filter by symbol…", ko: "종목으로 필터…" },
  "paperDesk.holdings.filterEmpty": { en: "No holdings match this filter.", ko: "필터와 일치하는 보유 종목이 없습니다." },
  "paperDesk.holdings.entryDate": { en: "Entry date", ko: "진입일" },
  "paperDesk.holdings.entryPrice": { en: "Entry price", ko: "진입가" },
  "paperDesk.holdings.lastPrice": { en: "Last price", ko: "최근가" },
  "paperDesk.holdings.marketValue": { en: "Market value", ko: "평가금액" },
  "paperDesk.holdings.unrealisedPnl": { en: "Unrealized P&L", ko: "미실현 손익" },
  "paperDesk.returnHeader": { en: "Return", ko: "수익률" },
  "paperDesk.holdings.stopPrice": { en: "Stop price", ko: "손절가" },
  "paperDesk.holdings.sessionsToTimeStop": { en: "Sessions to time stop", ko: "타임스탑까지 세션 수" },
  "paperDesk.holdings.sessionsToTimeStopHint": {
    en: "Sessions left before the max-hold rule force-closes this position.",
    ko: "최대 보유기간 규칙이 이 포지션을 강제 청산하기까지 남은 세션 수입니다.",
  },

  // --- BookStatistics.tsx: summary / tiles ------------------------------------------
  "paperDesk.bookStats.summary": { en: "Book statistics", ko: "북 통계" },
  "paperDesk.tiles.positionsValue": { en: "Positions value", ko: "포지션 평가금액" },
  "paperDesk.tiles.totalReturn": { en: "Total return", ko: "총수익률" },
  "paperDesk.tiles.excessVsBenchmark": { en: "Excess vs. benchmark", ko: "벤치마크 대비 초과수익률" },
  "paperDesk.tiles.excessVsBenchmarkHint": {
    en: "Desk return minus the book's benchmark return over the same window.",
    ko: "같은 기간 동안 데스크 수익률에서 북의 벤치마크 수익률을 뺀 값입니다.",
  },
  "paperDesk.tiles.maxDrawdown": { en: "Max drawdown", ko: "최대 낙폭" },
  "paperDesk.tiles.capitalExposure": { en: "Capital exposure", ko: "자본 노출도" },
  "paperDesk.tiles.capitalExposureHint": {
    en: "Share of equity currently held in positions, not cash.",
    ko: "현금이 아닌 포지션으로 보유 중인 자산 비중입니다.",
  },
  "paperDesk.tiles.openPositions": { en: "Open positions", ko: "보유 포지션 수" },
  "paperDesk.tiles.slotsFree_one": { en: "{count} slot free", ko: "여유 슬롯 {count}개" },
  "paperDesk.tiles.slotsFree_other": { en: "{count} slots free", ko: "여유 슬롯 {count}개" },

  "paperDesk.pnl.realised": { en: "Realized P&L", ko: "실현 손익" },
  "paperDesk.pnl.realisedHint": {
    en: "Closed trades -- money actually captured",
    ko: "청산된 거래 -- 실제로 확보한 금액",
  },
  "paperDesk.pnl.unrealisedMark": { en: "Unrealized P&L (mark)", ko: "미실현 손익 (마크)" },
  "paperDesk.pnl.unrealisedHint": {
    en: "A mark against the last stored close, not money taken -- moves with the next price update",
    ko: "마지막 저장 종가 대비 평가액이며 실제로 확보한 금액이 아닙니다 -- 다음 가격 갱신에 따라 변동됩니다",
  },

  // --- BookStatistics.tsx: SignalsTable ---------------------------------------------
  "paperDesk.signals.title": { en: "Signals", ko: "신호" },
  "paperDesk.signals.rankNote": {
    en: "Entry order, ranked by {rankBy}, highest first. No key (warmup or no stored bar) sorts last and shows {dash}.",
    ko: "{rankBy} 기준 내림차순, 진입 시도 순서입니다. 키 없음(워밍업 중 또는 바 없음)은 맨 뒤에 정렬되며 {dash}로 표시됩니다.",
  },
  "paperDesk.signals.empty": {
    en: "No signals for this desk's universe.",
    ko: "이 데스크 유니버스에 대한 신호가 없습니다.",
  },
  "paperDesk.signals.held": { en: "Held", ko: "보유" },
  "paperDesk.signals.entryFires": { en: "Entry fires", ko: "진입 신호" },
  "paperDesk.signals.exitFires": { en: "Exit fires", ko: "청산 신호" },
  "paperDesk.signals.lastClose": { en: "Last close", ko: "최근 종가" },
  "paperDesk.signals.rankKey": { en: "Rank key", ko: "순위 키" },
  "paperDesk.signals.blocked": { en: "Blocked", ko: "차단" },
  "paperDesk.signals.heldFalse": { en: "Not held", ko: "미보유" },
  "paperDesk.signals.firesTrue": { en: "Fires", ko: "발동" },
  "paperDesk.signals.firesFalse": { en: "Quiet", ko: "미발동" },

  // --- BookStatistics.tsx: DecisionsTable / TradesTable -------------------------------
  "paperDesk.decisionsTable.title": { en: "Decisions", ko: "결정" },
  "paperDesk.decisionsTable.reason": { en: "Reason", ko: "사유" },
  "paperDesk.trades.title": { en: "Trades", ko: "거래" },
  "paperDesk.trades.empty": { en: "No closed trades yet.", ko: "아직 청산된 거래가 없습니다." },
  "paperDesk.trades.exitDate": { en: "Exit date", ko: "청산일" },
  "paperDesk.trades.exitPrice": { en: "Exit price", ko: "청산가" },
  "paperDesk.trades.exitReason": { en: "Exit reason", ko: "청산 사유" },
  "paperDesk.trades.pnl": { en: "P&L", ko: "손익" },
  "paperDesk.trades.barsHeld": { en: "Bars held", ko: "보유 봉 수" },

  // --- BookStatistics.tsx: DeskRules ------------------------------------------------
  "paperDesk.rules.heading": { en: "Rules", ko: "규칙" },
  "paperDesk.rules.universe": { en: "universe: ", ko: "유니버스: " },
  "paperDesk.rules.entry": { en: "entry: ", ko: "진입: " },
  "paperDesk.rules.exit": { en: "exit: ", ko: "청산: " },
  "paperDesk.rules.stopLoss": { en: "stop loss: ", ko: "손절: " },
  "paperDesk.rules.noStopLoss": { en: "no stop loss", ko: "손절 없음" },
  "paperDesk.rules.takeProfit": { en: "take profit: ", ko: "익절: " },
  "paperDesk.rules.maxHold": { en: "max hold: ", ko: "최대 보유: " },
  "paperDesk.rules.noHoldCap": { en: "no hold cap", ko: "보유 기간 제한 없음" },
  "paperDesk.rules.maxHoldValue": { en: "{days} sessions", ko: "{days}세션" },
  "paperDesk.rules.maxPositions": { en: "max positions: ", ko: "최대 포지션 수: " },
  "paperDesk.rules.positionSize": { en: "position size: ", ko: "포지션 크기: " },
  "paperDesk.rules.positionSizeValue": { en: "{pct} of equity", ko: "자산 총액의 {pct}" },
  "paperDesk.rules.thesis": { en: "Thesis", ko: "투자 논리" },

  // --- BookStatistics.tsx: DeskLadderDescription --------------------------------------
  "paperDesk.ladder.signal": { en: "signal: ", ko: "신호: " },
  "paperDesk.ladder.signalValue": {
    en: "{symbol}’s drawdown from its own all-time closing high",
    ko: "{symbol}의 자체 사상 최고 종가 대비 낙폭",
  },
  "paperDesk.ladder.baseState": { en: "base state: ", ko: "기본 상태: " },
  "paperDesk.ladder.confirmation": { en: "confirmation: ", ko: "확인 조건: " },
  "paperDesk.ladder.confirmationValue": {
    en: "fires once {signalSymbol} closes back above its own {sessions}-session average",
    ko: "{signalSymbol}이(가) 자체 {sessions}세션 평균을 다시 상회 마감해야 발동",
  },
  "paperDesk.ladder.fundingOrder": { en: "funding order: ", ko: "자금 조달 순서: " },
  "paperDesk.ladder.fundingOrderValue": {
    en: "{leveragedSymbol} is funded from {bondSymbol} first, then {defensiveSymbol}",
    ko: "{leveragedSymbol}은(는) 먼저 {bondSymbol}에서, 다음으로 {defensiveSymbol}에서 자금을 조달합니다",
  },
  "paperDesk.ladder.recovery": { en: "recovery: ", ko: "회복: " },
  "paperDesk.ladder.recoveryValue": {
    en: "halve {leveragedSymbol} on new highs; full exit at {gainPct} gain or {sessions} sessions, whichever is first",
    ko: "신규 고점 시 {leveragedSymbol} 비중 절반 축소; {gainPct} 상회 또는 {sessions}세션 경과 중 먼저 오는 시점에 전량 청산",
  },
  "paperDesk.ladder.rungsCaption": { en: "Rungs", ko: "단계" },
  "paperDesk.ladder.spyDrawdownHeader": { en: "SPY drawdown", ko: "SPY 낙폭" },
  "paperDesk.ladder.leveragedTargetHeader": { en: "{symbol} target", ko: "{symbol} 목표 비중" },

  // --- BookStatistics.tsx: DeskAutopilotDescription -------------------------------------
  "paperDesk.autopilot.provenanceHeading": { en: "Provenance", ko: "출처" },
  "paperDesk.autopilot.tradedSoFar": { en: "traded so far: ", ko: "지금까지 거래한 종목: " },
  "paperDesk.autopilot.tradedSoFarEmpty": {
    en: "nothing yet — no order has been staged into this book",
    ko: "아직 없음 — 이 북에 등록된 주문이 없습니다",
  },
  "paperDesk.autopilot.bookLabel": { en: "book: ", ko: "북: " },
  "paperDesk.autopilot.bookValue": {
    en: "{arm} arm trading {universeSource} -- a book is the arm+universe pair, never the arm alone.",
    ko: "{arm} 암, {universeSource} 거래 -- 북은 암+유니버스 조합으로 식별되며 암만으로는 식별되지 않습니다.",
  },
  "paperDesk.autopilot.universeSourceScreen": { en: "the screened universe", ko: "스크리닝된 유니버스" },
  "paperDesk.autopilot.universeSourceCard": {
    en: "the selected card's own universe",
    ko: "선택된 카드 자체의 유니버스",
  },
  "paperDesk.autopilot.currentCard": { en: "current card: ", ko: "현재 카드: " },
  "paperDesk.autopilot.cardAdopted": { en: "card adopted: ", ko: "카드 도입일: " },
  "paperDesk.autopilot.cardAdoptedSuffix": {
    en: " -- this seat's own inception, not the desk's.",
    ko: " -- 데스크가 아닌 이 좌석 자체의 개시일입니다.",
  },
  "paperDesk.autopilot.cardAdoptedDetail": {
    en: "The date picker above doesn't move it; orders from that day can't be rerun elsewhere.",
    ko: "위의 개시일 선택기는 이 값을 변경하지 않으며, 해당 날짜의 주문은 다른 날짜로 다시 실행할 수 없습니다.",
  },
  "paperDesk.autopilot.orders": { en: "orders: ", ko: "주문: " },
  "paperDesk.autopilot.ordersValue": {
    en: "{total} total -- {filled} filled, {pending} pending, {rejected} rejected.",
    ko: "총 {total}건 -- {filled}건 체결, {pending}건 대기, {rejected}건 거부.",
  },
  "paperDesk.autopilot.ordersFootnote": {
    en: " Filled, pending and rejected need not sum to the total.",
    ko: " 체결, 대기, 거부 건수의 합이 총 건수와 반드시 일치하지는 않습니다.",
  },
  "paperDesk.autopilot.ordersFootnoteDetail": {
    en: "Cancelled and expired are legal statuses nothing sets today.",
    ko: "취소 및 만료는 현재 아무 것도 설정하지 않는 유효한 상태입니다.",
  },
  "paperDesk.autopilot.lastRun": { en: "last run: ", ko: "마지막 실행: " },
  "paperDesk.autopilot.lastRunNone": { en: "no run has been recorded", ko: "기록된 실행이 없습니다" },
  "paperDesk.autopilot.lastRunStateUnknown": { en: "state unknown", ko: "상태 알 수 없음" },
  "paperDesk.autopilot.lastRunTimeUnknown": { en: "time unknown", ko: "시각 알 수 없음" },
  "paperDesk.autopilot.exits": { en: "exits: ", ko: "청산 방식: " },
  "paperDesk.autopilot.exitsNoneValue": {
    en: "only ever buys -- stop, target and hold-cap rules never touch these fills",
    ko: "매수만 수행 -- 손절/익절/보유기간 규칙이 이 체결에는 적용되지 않습니다",
  },
  "paperDesk.autopilot.exitsOtherValue": {
    en: "how this desk closes a position: {exits}",
    ko: "이 데스크가 포지션을 청산하는 방식: {exits}",
  },
  "paperDesk.autopilot.runLink": {
    en: "See the run detail on the Agent Workflow desk",
    ko: "에이전트 워크플로우 데스크에서 실행 상세 보기",
  },

  // --- api/paperdesk.ts: exitReasonLabel / decisionActionLabel -------------------------
  "paperDesk.exitReason.rule": { en: "Exit rule", ko: "청산 규칙" },
  "paperDesk.exitReason.stop": { en: "Stop loss", ko: "손절" },
  "paperDesk.exitReason.target": { en: "Take profit", ko: "익절" },
  "paperDesk.exitReason.time": { en: "Time stop", ko: "타임스탑" },
  "paperDesk.exitReason.openAtEnd": { en: "Open at window end", ko: "기간 종료 시 미청산" },
  "paperDesk.exitReason.rebalanceTrim": { en: "Rebalance trim", ko: "리밸런싱 축소" },
  "paperDesk.decisionAction.enter": { en: "Enter", ko: "진입" },
  "paperDesk.decisionAction.exit": { en: "Exit", ko: "청산" },
} as const satisfies MessageShard;
