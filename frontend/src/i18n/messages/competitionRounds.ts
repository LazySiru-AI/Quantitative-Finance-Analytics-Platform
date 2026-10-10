/**
 * Competition round detail — dossier, selection, library, agents, findings, seats.
 *
 * Keys are prefixed `competitionRounds.` -- see `catalog.ts` for the convention and why the prefix is
 * load-bearing (the duplicate-key guard in `i18n.test.tsx` keys off it).
 *
 * Backend prose (dossier narrative fields, finding titles/bodies, caution text, decision-note text,
 * etc.) is never translated here -- it is model-written or hand-written English lifted off disk or
 * composed server-side, and this shard only covers the literal chrome around it. See the module
 * docstrings on `CandidateDossier.tsx`/`FindingsSection.tsx` for the specific fields left alone.
 */
import type { MessageShard } from "@/i18n/types";

export const competitionRounds = {
  // --- shared across this shard's files --------------------------------------
  "competitionRounds.roundLabel": { en: "Round", ko: "라운드" },
  "competitionRounds.noRoundsYet": { en: "No rounds yet", ko: "아직 라운드가 없습니다" },
  "competitionRounds.sourceLine": { en: "Source: {source}", ko: "출처: {source}" },
  "competitionRounds.label.entry": { en: "Entry", ko: "진입" },
  "competitionRounds.label.exit": { en: "Exit", ko: "청산" },
  "competitionRounds.label.risk": { en: "Risk", ko: "리스크" },
  "competitionRounds.label.sizing": { en: "Sizing", ko: "포지션 크기" },
  "competitionRounds.action.seatOnPaperDesk": { en: "Seat on the paper desk", ko: "페이퍼 데스크에 배치" },
  "competitionRounds.action.retire": { en: "Retire", ko: "은퇴" },
  "competitionRounds.table.agent": { en: "Card", ko: "카드" },

  // --- CandidateDossier.tsx ---------------------------------------------------
  "competitionRounds.dossier.loading": { en: "Loading the dossier…", ko: "후보 상세 불러오는 중…" },
  "competitionRounds.dossier.error": {
    en: "Could not load the dossier: {error}",
    ko: "후보 상세를 불러오지 못했습니다: {error}",
  },
  "competitionRounds.dossier.unknownError": { en: "unknown error", ko: "알 수 없는 오류" },
  "competitionRounds.dossier.heading.whatItDoes": { en: "What it does", ko: "무엇을 하는가" },
  "competitionRounds.dossier.universeLabel": { en: "Universe:", ko: "유니버스:" },
  "competitionRounds.dossier.selfDeclaredLabel": { en: "Self-declared label:", ko: "자체 신고 라벨:" },
  "competitionRounds.dossier.heading.whyHere": { en: "Why it’s here", ko: "여기 있는 이유" },
  "competitionRounds.dossier.originLine": {
    en: "Generation {generation} · {originKind}",
    ko: "{generation}세대 · {originKind}",
  },
  "competitionRounds.dossier.originLineWithParents": {
    en: "Generation {generation} · {originKind} from {parents}",
    ko: "{generation}세대 · {originKind} (부모: {parents})",
  },
  "competitionRounds.dossier.origin.random": { en: "Founder", ko: "시조" },
  "competitionRounds.dossier.origin.mutation": { en: "Mutation", ko: "돌연변이" },
  "competitionRounds.dossier.origin.crossover": { en: "Crossover", ko: "교차" },
  "competitionRounds.dossier.origin.agent": { en: "Agent-proposed", ko: "에이전트 제안" },
  "competitionRounds.dossier.heading.evidence": { en: "The evidence", ko: "근거" },
  "competitionRounds.dossier.holdoutCheck.allPurposes": {
    en: "All-purpose baseline: {positiveFraction} of {measurements} holdouts positive (median {median}) -- most clear it.",
    ko: "전체 목적 기준선: 홀드아웃 측정 {measurements}건 중 {positiveFraction}이(가) 양(+)이었습니다(중앙값 {median}). 거의 모든 후보가 이를 넘습니다.",
  },
  "competitionRounds.dossier.holdoutCheck.samePurpose": {
    en: "Same purpose only: {measurements} measurements, {positiveFraction} positive, field median {median}, card {cardHoldout}.",
    ko: "동일 목적만 보면: 측정 {measurements}건 중 {positiveFraction} 양(+), 필드 중앙값 {median} 대 카드 {cardHoldout}. 노이즈 여부는 “무엇이 문제인가” 참고.",
  },
  "competitionRounds.dossier.noEvidence": {
    en: "No scored generation is on record for this genome.",
    ko: "이 게놈에 대해 채점된 세대 기록이 없습니다.",
  },
  "competitionRounds.dossier.table.generation": { en: "Generation", ko: "세대" },
  "competitionRounds.dossier.table.rankField": { en: "Rank / field", ko: "순위 / 필드" },
  "competitionRounds.dossier.table.windows": { en: "Windows", ko: "기간" },
  "competitionRounds.dossier.table.selectionMedian": { en: "Selection median", ko: "선정 중앙값" },
  "competitionRounds.dossier.table.holdoutMedian": { en: "Holdout median", ko: "홀드아웃 중앙값" },
  "competitionRounds.dossier.table.hitRate": { en: "Hit rate", ko: "적중률" },
  "competitionRounds.dossier.table.trades": { en: "Trades", ko: "거래" },
  "competitionRounds.dossier.evidenceRow.fieldSamePurpose": {
    en: "field (same purpose): {value}",
    ko: "필드 (동일 목적): {value}",
  },
  "competitionRounds.dossier.evidenceRow.fieldThisGeneration": {
    en: "field (this generation): {value}",
    ko: "필드 (이 세대): {value}",
  },
  "competitionRounds.dossier.evidenceRow.thisCard": { en: "this card: {value}", ko: "이 카드: {value}" },
  "competitionRounds.dossier.contextGrid.medianSamePurpose": {
    en: "Field median excess, same purpose (all-time)",
    ko: "필드 초과수익 중앙값, 동일 목적 (전체 기간)",
  },
  "competitionRounds.dossier.contextGrid.medianAllPurposes": {
    en: "Field median excess, all purposes (all-time)",
    ko: "필드 초과수익 중앙값, 전체 목적 (전체 기간)",
  },
  "competitionRounds.dossier.contextGrid.holdoutMedianSamePurpose": {
    en: "Field holdout median, same purpose",
    ko: "필드 홀드아웃 중앙값, 동일 목적",
  },
  "competitionRounds.dossier.contextGrid.holdoutMedianAllPurposes": {
    en: "Field holdout median, all purposes",
    ko: "필드 홀드아웃 중앙값, 전체 목적",
  },
  "competitionRounds.dossier.contextGrid.holdoutPositiveSamePurpose": {
    en: "Field holdout positive, same purpose (n)",
    ko: "필드 홀드아웃 양(+) 비율, 동일 목적 (n)",
  },
  "competitionRounds.dossier.contextGrid.holdoutPositiveAllPurposes": {
    en: "Field holdout positive, all purposes (n)",
    ko: "필드 홀드아웃 양(+) 비율, 전체 목적 (n)",
  },
  "competitionRounds.dossier.contextGrid.ratioWithN": { en: "{ratio} (n={count})", ko: "{ratio} (n={count})" },
  "competitionRounds.dossier.contextGrid.percentile": {
    en: "Percentile, all-time (this purpose)",
    ko: "백분위, 전체 기간 (이 목적)",
  },
  "competitionRounds.dossier.contextGrid.noiseFloor": { en: "Noise floor", ko: "노이즈 한계" },
  "competitionRounds.dossier.contextGrid.marginOverNoise": { en: "Margin over noise", ko: "노이즈 대비 여유" },
  "competitionRounds.dossier.contextGrid.candidatesEverRun": {
    en: "Candidates ever run",
    ko: "지금까지 실행된 후보 수",
  },
  "competitionRounds.dossier.contextGrid.generationsWithOutcomes": {
    en: "Generations with outcomes on record",
    ko: "결과가 기록된 세대 수",
  },
  "competitionRounds.dossier.heading.wrong": { en: "What’s wrong with it", ko: "무엇이 문제인가" },
  "competitionRounds.dossier.noCautions": {
    en: "No deterministic caution rule fired for this card.",
    ko: "이 카드에 대해 발동된 결정론적 주의 규칙이 없습니다.",
  },
  "competitionRounds.dossier.severity.blocking": { en: "Blocking", ko: "차단" },
  "competitionRounds.dossier.severity.serious": { en: "Serious", ko: "심각" },
  "competitionRounds.dossier.severity.note": { en: "Note", ko: "참고" },
  "competitionRounds.dossier.heading.decisions": { en: "What each button does", ko: "각 버튼의 동작" },
  "competitionRounds.dossier.decision.shelve": {
    en: "Keep for review (shelve)",
    ko: "검토 보류 (선반에 보관)",
  },
  "competitionRounds.dossier.decision.reject": { en: "Decline (reject)", ko: "거절 (거부)" },
  "competitionRounds.dossier.filedFor": { en: "Filed for {purpose}.", ko: "{purpose} 목적으로 등록되었습니다." },

  // --- SelectionSection.tsx ---------------------------------------------------
  "competitionRounds.selection.pickRound": {
    en: "Pick a round to see the selection it produces.",
    ko: "라운드를 선택하면 해당 라운드가 만든 선정 결과를 볼 수 있습니다.",
  },
  "competitionRounds.selection.loadingRound": {
    en: "Loading the selection for {roundId}…",
    ko: "{roundId}의 선정 결과 불러오는 중…",
  },
  "competitionRounds.selection.loadError": {
    en: "Could not load the selection for this round.",
    ko: "이 라운드의 선정 결과를 불러오지 못했습니다.",
  },
  "competitionRounds.selection.notFound": {
    en: "No selection for {roundId} -- the rule ranks on a round’s live out-of-sample matrix, which this round lacks.",
    ko: "{roundId}에는 선정 결과가 없습니다. 규칙은 라운드 자체의 실거래 표본외 매트릭스로 순위를 매기는데, 이 라운드에는 없습니다 — 다른 라운드를 선택하세요.",
  },
  "competitionRounds.selection.heading": { en: "Selection — {roundId}", ko: "선정 — {roundId}" },
  "competitionRounds.selection.rulesBadge": { en: "rules {version}", ko: "규칙 {version}" },
  "competitionRounds.selection.notesHeading": { en: "Notes", ko: "메모" },
  "competitionRounds.selection.rosterHeading": { en: "Desk roster", ko: "데스크 명단" },
  "competitionRounds.selection.noSeats": {
    en: "No seats filled for this round.",
    ko: "이 라운드에 채워진 좌석이 없습니다.",
  },
  "competitionRounds.selection.rankingHeading": { en: "Full ranking", ko: "전체 순위" },
  "competitionRounds.selection.noRanking": {
    en: "No agents were ranked for this round.",
    ko: "이 라운드에 순위가 매겨진 에이전트가 없습니다.",
  },
  "competitionRounds.selection.table.rank": { en: "Rank", ko: "순위" },
  "competitionRounds.selection.table.liveMedian": { en: "Live median", ko: "실거래 중앙값" },
  "competitionRounds.selection.table.hits": { en: "Hits", ko: "적중" },
  "competitionRounds.selection.table.novelNames": { en: "Novel names", ko: "신규 종목명" },
  "competitionRounds.selection.table.seated": { en: "Seated", ko: "배치됨" },
  "competitionRounds.selection.table.seatedBy": { en: "Seated by", ko: "배치 주체" },
  "competitionRounds.selection.table.note": { en: "Note", ko: "메모" },
  "competitionRounds.selection.notSeated": { en: "Not seated", ko: "미배치" },
  "competitionRounds.selection.gates.noResults": {
    en: "No gate results recorded for this round.",
    ko: "이 라운드에 기록된 게이트 결과가 없습니다.",
  },
  "competitionRounds.selection.gates.heading": { en: "Gate {gateKey}", ko: "게이트 {gateKey}" },
  "competitionRounds.selection.gates.noAgents": {
    en: "No agents evaluated at this gate.",
    ko: "이 게이트에서 평가된 에이전트가 없습니다.",
  },
  "competitionRounds.selection.gates.result": { en: "Result", ko: "결과" },
  "competitionRounds.selection.gates.reason": { en: "Reason", ko: "사유" },
  "competitionRounds.selection.gates.pass": { en: "Pass", ko: "통과" },
  "competitionRounds.selection.gates.fail": { en: "Fail", ko: "실패" },

  // --- LibrarySection.tsx ------------------------------------------------------
  "competitionRounds.library.loading": {
    en: "Loading the strategy library…",
    ko: "전략 라이브러리 불러오는 중…",
  },
  "competitionRounds.library.loadError": {
    en: "Could not load the strategy library.",
    ko: "전략 라이브러리를 불러오지 못했습니다.",
  },
  "competitionRounds.library.noCardsInTier": { en: "No cards in this tier.", ko: "이 등급에 카드가 없습니다." },
  "competitionRounds.library.designedThrough": {
    en: "{agentId} · designed through {designedThrough}",
    ko: "{agentId} · {designedThrough}까지 설계됨",
  },
  "competitionRounds.library.universe": { en: "Universe: {universe}", ko: "유니버스: {universe}" },
  "competitionRounds.library.universeHeader": { en: "Universe", ko: "유니버스" },
  "competitionRounds.library.paramsHeader": { en: "Stop / target / hold / size", ko: "손절/익절/보유/크기" },
  "competitionRounds.library.detail": { en: "Detail", ko: "상세" },
  "competitionRounds.library.stopLoss": { en: "Stop loss {value}", ko: "손절 {value}" },
  "competitionRounds.library.takeProfit": { en: "Take profit {value}", ko: "익절 {value}" },
  "competitionRounds.library.maxHold": { en: "Max hold {days}d", ko: "최대 보유 {days}일" },
  "competitionRounds.library.maxPositions": { en: "Max positions {count}", ko: "최대 포지션 수 {count}" },
  "competitionRounds.library.positionSize": { en: "Position size {value}", ko: "포지션 크기 {value}" },
  "competitionRounds.library.windowCount_one": { en: "({count} window)", ko: "({count}개 기간)" },
  "competitionRounds.library.windowCount_other": { en: "({count} windows)", ko: "({count}개 기간)" },
  "competitionRounds.library.bearBadge": { en: "bear", ko: "약세" },
  "competitionRounds.library.bearBadgeTitle": {
    en: "Selected deliberately for a falling benchmark -- unlike this horizon's calendar-sampled ladder windows.",
    ko: "이 기간대의 달력 표본 래더 구간과 달리, 하락 벤치마크를 위해 의도적으로 선택되었습니다.",
  },
  "competitionRounds.library.notRegimeWindow": { en: "not a regime window", ko: "국면 구간 아님" },
  "competitionRounds.library.runHeading": { en: "Run a new round", ko: "새 라운드 실행" },
  "competitionRounds.library.roundIdLabel": { en: "Round id", ko: "라운드 ID" },
  "competitionRounds.library.tierLabel": { en: "Tier (optional)", ko: "등급 (선택)" },
  "competitionRounds.library.anyTier": { en: "Any tier", ko: "모든 등급" },
  "competitionRounds.library.cardsLegend": { en: "Cards", ko: "카드" },
  "competitionRounds.library.noCardsInLibrary": {
    en: "No cards in the library yet.",
    ko: "아직 라이브러리에 카드가 없습니다.",
  },
  "competitionRounds.library.windowsLegend": { en: "Windows", ko: "기간" },
  "competitionRounds.library.loadingWindows": {
    en: "Loading the window catalogue…",
    ko: "기간 목록 불러오는 중…",
  },
  "competitionRounds.library.windowsLoadError": {
    en: "Could not load the window catalogue.",
    ko: "기간 목록을 불러오지 못했습니다.",
  },
  "competitionRounds.library.noWindowsDefined": {
    en: "No windows are defined yet.",
    ko: "아직 정의된 기간이 없습니다.",
  },
  "competitionRounds.library.provenanceNote": {
    en: "{term} exists only for cards whose universe came from a 13F filing. It sits outside the gate, unchecked by default. ",
    ko: "{term}은(는) 13F 신고 유래 유니버스를 가진 카드에만 있습니다. 적격성 게이트 밖이며 기본적으로 선택 해제되어 있습니다. ",
  },
  "competitionRounds.library.starting": { en: "Starting…", ko: "시작하는 중…" },
  "competitionRounds.library.runRound": { en: "Run round", ko: "라운드 실행" },
  "competitionRounds.library.runsComplete": {
    en: "{completed} / {total} runs complete",
    ko: "실행 {completed} / {total}건 완료",
  },
  "competitionRounds.library.runsFailed": { en: "{count} failed", ko: "{count}건 실패" },
  "competitionRounds.library.cancel": { en: "Cancel", ko: "취소" },
  "competitionRounds.library.progressLabel": { en: "Round progress", ko: "라운드 진행률" },
  "competitionRounds.library.running": {
    en: "Running {agentId} on {window}…",
    ko: "{window}에서 {agentId} 실행 중…",
  },
  "competitionRounds.library.resultsTable.window": { en: "Window", ko: "기간" },
  "competitionRounds.library.resultsTable.excess": { en: "Excess", ko: "초과수익" },
  "competitionRounds.library.resultsTable.seconds": { en: "Seconds", ko: "초" },

  // --- AgentSection.tsx --------------------------------------------------------
  "competitionRounds.agent.selectPrompt": {
    en: "Select an agent from the Leaderboard to see its trades.",
    ko: "리더보드에서 에이전트를 선택하면 거래 내역을 볼 수 있습니다.",
  },
  "competitionRounds.agent.loading": { en: "Loading {agentId}…", ko: "{agentId} 불러오는 중…" },
  "competitionRounds.agent.loadError": {
    en: "Could not load this agent's detail.",
    ko: "이 에이전트의 상세 정보를 불러오지 못했습니다.",
  },
  "competitionRounds.agent.heading": { en: "{name} — {roundId}", ko: "{name} — {roundId}" },
  "competitionRounds.agent.noWindows": {
    en: "This agent has not run in any window for this round.",
    ko: "이 에이전트는 이 라운드의 어떤 기간에서도 실행되지 않았습니다.",
  },
  "competitionRounds.agent.stat.totalReturn": { en: "Total return", ko: "총 수익률" },
  "competitionRounds.agent.stat.spyBenchmark": { en: "SPY benchmark", ko: "SPY 벤치마크" },
  "competitionRounds.agent.stat.excess": { en: "Excess", ko: "초과수익" },
  "competitionRounds.agent.stat.adjustedExcess": { en: "Adjusted excess", ko: "조정 초과수익" },
  "competitionRounds.agent.stat.capitalExposure": { en: "Capital exposure", ko: "자본 노출도" },
  "competitionRounds.agent.stat.maxDrawdown": { en: "Max drawdown", ko: "최대 낙폭" },
  "competitionRounds.agent.stat.winRate": { en: "Win rate", ko: "승률" },
  "competitionRounds.agent.stat.profitFactor": { en: "Profit factor", ko: "손익비" },
  "competitionRounds.agent.stat.unrealisedShare": { en: "Unrealized share", ko: "미실현 비중" },
  "competitionRounds.agent.concentration": {
    en: "Top 3 trades captured {ratio} of gross winning P&L; without them, return is {strongReturn}, not {totalReturn}.",
    ko: "상위 3건의 수익 거래가 이 기간 총수익 P&L의 {ratio}을(를) 차지했습니다. 제외 시 수익률은 {totalReturn}이 아닌 {strongReturn}이었을 것입니다.",
  },
  "competitionRounds.agent.table.barsHeld": { en: "Bars held", ko: "보유 봉 수" },
  "competitionRounds.agent.table.exitReason": { en: "Exit reason", ko: "청산 사유" },
  "competitionRounds.agent.table.return": { en: "Return", ko: "수익률" },
  "competitionRounds.agent.table.shareOfReturn": { en: "Share of return", ko: "수익 기여도" },
  "competitionRounds.agent.noTrades": {
    en: "No trades recorded for this window.",
    ko: "이 기간에 기록된 거래가 없습니다.",
  },
  "competitionRounds.agent.markBadgeTitle": {
    en: "A mark against the last price the window saw -- not money actually taken.",
    ko: "실제로 확보한 금액이 아니라, 이 기간에 관측된 마지막 가격 기준 평가액입니다.",
  },
  "competitionRounds.agent.markBadge": { en: "mark, not realized", ko: "평가, 미실현" },

  // --- NextRoundPanel.tsx -------------------------------------------------------
  "competitionRounds.nextRound.loading": {
    en: "Loading next-round briefing…",
    ko: "다음 라운드 브리핑 불러오는 중…",
  },
  "competitionRounds.nextRound.loadError": {
    en: "Could not load the next-round briefing.",
    ko: "다음 라운드 브리핑을 불러오지 못했습니다.",
  },
  "competitionRounds.nextRound.empty": {
    en: "No next-round briefing is available yet.",
    ko: "아직 다음 라운드 브리핑이 없습니다.",
  },
  "competitionRounds.nextRound.heading": { en: "Next round — {roundId}", ko: "다음 라운드 — {roundId}" },
  "competitionRounds.nextRound.planCommitted": { en: "Plan committed", ko: "계획 확정됨" },
  "competitionRounds.nextRound.noCommittedPlanTitle": { en: "No committed plan", ko: "확정된 계획 없음" },
  "competitionRounds.nextRound.noCommittedPlanBody": {
    en: "No committed plan. This programme requires a plan committed before any run exists -- running without one isn’t accepted.",
    ko: "확정된 계획이 없습니다. 이 프로그램은 실행 전에 계획이 먼저 확정되어야 하므로, 계획 없이 실행하면 프로토콜이 인정하지 않는 결과가 됩니다.",
  },
  "competitionRounds.nextRound.focusLabel": {
    en: "What the next round asks",
    ko: "다음 라운드가 묻는 것",
  },
  "competitionRounds.nextRound.focusUnsetRegistered": {
    en: "No focus recorded for this round.",
    ko: "이 라운드에 기록된 초점이 없습니다.",
  },
  "competitionRounds.nextRound.focusUnsetUnregistered": {
    en: "Focus is unset -- no plan is committed yet.",
    ko: "초점이 설정되지 않았습니다 -- 아직 확정된 계획이 없습니다.",
  },
  "competitionRounds.nextRound.carriesLabel": {
    en: "What the previous round recorded for this one",
    ko: "이전 라운드가 이번 라운드를 위해 남긴 기록",
  },
  "competitionRounds.nextRound.nothingCarried": {
    en: "Nothing recorded as carrying forward.",
    ko: "이월할 항목으로 기록된 것이 없습니다.",
  },
  "competitionRounds.nextRound.thePreviousRound": { en: "The previous round", ko: "이전 라운드" },
  "competitionRounds.nextRound.authoredEmpty": {
    en: "{previousRoundId} recorded nothing explicit as carrying forward.",
    ko: "{previousRoundId}은(는) 이월할 항목을 명시적으로 기록하지 않았습니다.",
  },
  "competitionRounds.nextRound.fromRound": { en: "From {previousRoundId}", ko: "{previousRoundId}에서" },
  "competitionRounds.nextRound.heuristicLabel": {
    en: "Also flagged by the findings parser (a keyword read over prose, not a curated list)",
    ko: "발견 사항 파서에서도 표시됨 (텍스트에 대한 키워드 검색이며, 정리된 목록이 아닙니다)",
  },
  "competitionRounds.nextRound.blockersLabel": { en: "Blockers", ko: "차단 요소" },
  "competitionRounds.nextRound.goToRunForm": { en: "Go to run form →", ko: "실행 양식으로 이동 →" },

  // --- PendingSeatsPanel.tsx -----------------------------------------------------
  "competitionRounds.pendingSeats.heading": { en: "Paper desk review queue", ko: "페이퍼 데스크 검토 대기열" },
  "competitionRounds.pendingSeats.loadError": {
    en: "Could not load the review queue: {error}",
    ko: "검토 대기열을 불러오지 못했습니다: {error}",
  },
  "competitionRounds.pendingSeats.waitingHeading": { en: "Waiting for review", ko: "검토 대기 중" },
  "competitionRounds.pendingSeats.waitingBlurb": {
    en: "Clearing the gate is statistical, not an endorsement: excess beat the noise floor twice on other windows; luck can too.",
    ko: "게이트 통과는 통계적 결과일 뿐 보증이 아닙니다 -- 서로 다른 윈도우에서 중앙값 초과수익이 노이즈 한계를 두 번 넘었다는 뜻이며, 순전히 운으로도 가능합니다. “검토 보류”는 선반에 옮길 뿐입니다.",
  },
  "competitionRounds.pendingSeats.noneWaiting": {
    en: "Nothing is waiting for review. Promoted cards appear here when the loop files a seat request.",
    ko: "검토 대기 중인 항목이 없습니다. 루프가 좌석 요청을 제출하면 승격된 카드가 여기에 나타납니다.",
  },
  "competitionRounds.pendingSeats.shelfHeading": { en: "Review shelf", ko: "검토 선반" },
  "competitionRounds.pendingSeats.shelfBlurb": {
    en: "Paper desk: simulated, no real money. A shelved card is kept, observable, not trading. Seating adds it; places no order.",
    ko: "페이퍼 데스크는 모의 거래이며 실제 자금이 없습니다. 선반의 카드는 보관되고 관찰되지만 거래하지 않습니다. “페이퍼 데스크에 배치”는 명단에 추가하는 별도의 결정이며, 배치 자체는 주문을 내지 않습니다.",
  },
  "competitionRounds.pendingSeats.shelfEmpty": {
    en: "Nothing is on the shelf yet.",
    ko: "아직 선반에 아무것도 없습니다.",
  },
  "competitionRounds.pendingSeats.alreadyDecided": {
    en: "{count} already decided",
    ko: "{count}개 이미 결정됨",
  },
  "competitionRounds.pendingSeats.selectionMedian": {
    en: "{value} selection median",
    ko: "선정 중앙값 {value}",
  },
  "competitionRounds.pendingSeats.fullDossier": { en: "Full dossier", ko: "전체 후보 상세" },
  "competitionRounds.pendingSeats.hideDossier": { en: "Hide dossier", ko: "후보 상세 숨기기" },
  "competitionRounds.pendingSeats.working": { en: "Working…", ko: "처리 중…" },
  "competitionRounds.pendingSeats.summaryPlaceholder": {
    en: "Universe and strategy details load when you expand this card.",
    ko: "이 카드를 펼치면 유니버스와 전략 상세 정보가 표시됩니다.",
  },
  "competitionRounds.pendingSeats.action.keepForReview": { en: "Keep for review", ko: "검토 보류" },
  "competitionRounds.pendingSeats.action.decline": { en: "Decline", ko: "거절" },
  "competitionRounds.pendingSeats.status.seated": { en: "Seated", ko: "배치됨" },
  "competitionRounds.pendingSeats.status.rejected": { en: "Rejected", ko: "거부됨" },
  "competitionRounds.pendingSeats.status.retired": { en: "Retired", ko: "은퇴됨" },
  "competitionRounds.pendingSeats.status.pending": { en: "Pending", ko: "대기" },
  "competitionRounds.pendingSeats.status.shelved": { en: "Shelved", ko: "보류됨" },

  // --- FindingsSection.tsx --------------------------------------------------------
  "competitionRounds.findings.pickRound": {
    en: "Pick a round to see what it left open for the next one.",
    ko: "라운드를 선택하면 다음 라운드로 남긴 항목을 볼 수 있습니다.",
  },
  "competitionRounds.findings.loadingRound": {
    en: "Loading findings for {roundId}…",
    ko: "{roundId}의 발견 사항 불러오는 중…",
  },
  "competitionRounds.findings.loadError": {
    en: "Could not load the findings for this round.",
    ko: "이 라운드의 발견 사항을 불러오지 못했습니다.",
  },
  "competitionRounds.findings.notFound": {
    en: "No written record for {roundId} yet. Rounds legitimately have no findings until someone writes them down.",
    ko: "{roundId}에는 아직 기록된 문서가 없습니다. 누군가 직접 기록하기 전까지 라운드에 발견 사항이 없는 것은 정상입니다.",
  },
  "competitionRounds.findings.nothingWritten": {
    en: "{roundId} wrote nothing down -- no findings files were found for this round.",
    ko: "{roundId}는 아무것도 기록하지 않았습니다 -- 이 라운드에 대한 발견 사항 파일을 찾을 수 없습니다.",
  },
  "competitionRounds.findings.filesUnparseable": {
    en: "{roundId}’s files were read but nothing parseable was found -- unlike writing nothing. Check these files by hand:",
    ko: "{roundId}의 파일을 읽었지만 파싱할 내용을 찾지 못했습니다 -- 아무것도 기록하지 않은 것과는 다릅니다. 다음 파일을 직접 확인하세요:",
  },
  "competitionRounds.findings.sourcesReadHeading": { en: "Sources read", ko: "읽은 출처" },
  "competitionRounds.findings.loadingRoundsNote": { en: "Loading rounds…", ko: "라운드 불러오는 중…" },
  "competitionRounds.findings.roundsLoadErrorNote": {
    en: "Could not load rounds.",
    ko: "라운드를 불러오지 못했습니다.",
  },
  "competitionRounds.findings.carriedForwardHeading": { en: "Carried forward", ko: "이월됨" },
  "competitionRounds.findings.carriedForwardSubtitle": {
    en: "Everything this round left open for the next one to settle -- the agenda for round N+1.",
    ko: "이 라운드가 다음 라운드에서 해결하도록 남겨둔 모든 항목입니다 -- 다음 라운드(N+1)의 의제입니다.",
  },
  "competitionRounds.findings.carriedForwardEmpty": {
    en: "Nothing was left open. This round settled everything it wrote down.",
    ko: "남겨진 항목이 없습니다. 이 라운드는 기록한 모든 항목을 해결했습니다.",
  },
  "competitionRounds.findings.fullRecordHeading": { en: "Full record", ko: "전체 기록" },
  "competitionRounds.findings.fullRecordSubtitle": {
    en: "Every entry this round wrote, `carries_forward` or not. Entries also above in Carried forward are marked -- same record.",
    ko: "이 라운드가 기록한 모든 항목입니다, `carries_forward` 여부와 무관합니다. 위 이월됨에도 나온 항목은 표시됩니다 -- 별개가 아닌 동일한 기록입니다.",
  },
  "competitionRounds.findings.filterByKind": { en: "Filter by kind", ko: "종류별 필터" },
  "competitionRounds.findings.entryCount_one": { en: "({count} entry)", ko: "({count}개 항목)" },
  "competitionRounds.findings.entryCount_other": { en: "({count} entries)", ko: "({count}개 항목)" },
  "competitionRounds.findings.noEntriesOfKind": {
    en: "No entries of this kind.",
    ko: "이 종류의 항목이 없습니다.",
  },
  "competitionRounds.findings.carriesForwardBadge": { en: "carries forward", ko: "이월됨" },
  "competitionRounds.findings.carriesForwardTitle": {
    en: "Left open for the next round to settle",
    ko: "다음 라운드에서 해결하도록 남겨둠",
  },

  // --- goalDirectives.ts -------------------------------------------------------
  "competitionRounds.goalDirective.fieldNoun.purposes": { en: "purposes", ko: "목적" },
  "competitionRounds.goalDirective.fieldNoun.rankBy": { en: "ranking metric", ko: "순위 지표" },
  "competitionRounds.goalDirective.fieldNoun.focusSymbols": {
    en: "must-include tickers",
    ko: "필수 포함 종목",
  },
  "competitionRounds.goalDirective.fieldNoun.avoidSymbols": {
    en: "must-avoid tickers",
    ko: "필수 제외 종목",
  },
  "competitionRounds.goalDirective.valueNoun.purposesOne": { en: "a purpose", ko: "목적" },
  "competitionRounds.goalDirective.valueNoun.purposesMany": { en: "purposes", ko: "목적" },
  "competitionRounds.goalDirective.valueNoun.rankByOne": { en: "a ranking metric", ko: "순위 지표" },
  "competitionRounds.goalDirective.valueNoun.rankByMany": { en: "ranking metrics", ko: "순위 지표" },
  "competitionRounds.goalDirective.valueNoun.tickerOne": { en: "a ticker", ko: "종목" },
  "competitionRounds.goalDirective.valueNoun.tickerMany": { en: "tickers", ko: "종목" },
  "competitionRounds.goalDirective.control.purposes": {
    en: '"Books to breed for"',
    ko: '"어떤 책을 위해 교배할지"',
  },
  "competitionRounds.goalDirective.control.focusSymbols": {
    en: '"Must include tickers"',
    ko: '"필수 포함 종목"',
  },
  "competitionRounds.goalDirective.control.avoidSymbols": {
    en: '"Must avoid tickers"',
    ko: '"필수 제외 종목"',
  },
  "competitionRounds.goalDirective.messageNoControl": {
    en: "Doesn’t steer the search -- this form has no {fieldNoun} field, so it uses the default; only tickers below change it.",
    ko: "이 텍스트는 기록되지만 검색 방향을 바꾸지 않으며, 이 양식에는 {fieldNoun} 필드가 없습니다 -- 목표에 무엇이 적혀 있든 루프는 자체 기본값을 사용합니다. 아래의 종목 필드만 실제로 제안 대상을 바꿉니다.",
  },
  "competitionRounds.goalDirective.messageWithControl": {
    en: "This text is recorded but does not steer the search; set {values} in {control} below to actually change it.",
    ko: "이 텍스트는 기록되지만 검색 방향을 바꾸지 않습니다. 실제로 바꾸려면 아래 {control}에 {values}을(를) 설정하세요.",
  },
  "competitionRounds.goalDirective.illegalValues_one": {
    en: "{illegalQuoted} is not {noun}. The legal values are {legalValues}.",
    ko: "{illegalQuoted}은(는) {noun}이(가) 아닙니다. 사용 가능한 값은 {legalValues}입니다.",
  },
  "competitionRounds.goalDirective.illegalValues_other": {
    en: "{illegalQuoted} are not {noun}. The legal values are {legalValues}.",
    ko: "{illegalQuoted}은(는) {noun}이(가) 아닙니다. 사용 가능한 값은 {legalValues}입니다.",
  },

  // --- candidateName.ts ---------------------------------------------------------
  "competitionRounds.candidateName.placeholder": {
    en: "{purpose} candidate — expand for what it trades",
    ko: "{purpose} 후보 — 무엇을 거래하는지 보려면 펼치세요",
  },
  "competitionRounds.candidateName.headline": {
    en: "{rule} · {tickers} · {purpose}",
    ko: "{rule} · {tickers} · {purpose}",
  },
  "competitionRounds.candidateName.noTickers": { en: "no tickers on file", ko: "등록된 종목 없음" },
  "competitionRounds.candidateName.purpose.savings": { en: "Savings", ko: "저축" },
  "competitionRounds.candidateName.purpose.trading": { en: "Trading", ko: "트레이딩" },
  "competitionRounds.candidateName.purpose.roth": { en: "Roth", ko: "로스" },
} as const satisfies MessageShard;
