/**
 * Rules, Timeframes, Thesis and Backtest pages plus their strategy-lab components.
 *
 * Keys are prefixed `strategy.` -- see `catalog.ts` for the convention and why the prefix is
 * load-bearing (the duplicate-key guard in `i18n.test.tsx` keys off it).
 */
import type { MessageShard } from "@/i18n/types";

export const strategy = {
  // --- Evidence (Backtest + Timeframes + Rules, tabbed under one page) --------------------------
  "strategy.evidence.pageTitle": { en: "Evidence", ko: "근거" },
  "strategy.evidence.subtitle": {
    en: "Backtests, interval accuracy and the rule catalogue, in one place.",
    ko: "백테스트, 간격별 정확도, 규칙 카탈로그를 한 곳에서 확인하세요.",
  },
  "strategy.evidence.tabsAriaLabel": { en: "Evidence view", ko: "근거 보기" },
  "strategy.evidence.tab.backtest": { en: "Backtest", ko: "백테스트" },
  "strategy.evidence.tab.timeframes": { en: "Across intervals", ko: "간격별" },
  "strategy.evidence.tab.rules": { en: "Rules", ko: "규칙" },
  "strategy.evidence.tab.thesis": { en: "Thesis", ko: "투자 논거" },

  // --- shared display-word mappings (raw wire enums -> translated words) -----------------------
  "strategy.ruleState.firing": { en: "Firing", ko: "발동" },
  "strategy.ruleState.quiet": { en: "Quiet", ko: "미발동" },
  "strategy.ruleState.noData": { en: "No data", ko: "데이터 없음" },

  "strategy.guardStatus.passed": { en: "passed", ko: "통과" },
  "strategy.guardStatus.failed": { en: "failed", ko: "실패" },
  "strategy.guardStatus.unverified": { en: "unverified", ko: "미검증" },

  "strategy.direction.up": { en: "up", ko: "상승" },
  "strategy.direction.down": { en: "down", ko: "하락" },

  "strategy.regime.all": { en: "all", ko: "전체" },
  "strategy.regime.rising": { en: "rising", ko: "상승" },
  "strategy.regime.falling": { en: "falling", ko: "하락" },
  "strategy.regime.flat": { en: "flat", ko: "횡보" },

  "strategy.thesisStatus.registered": { en: "registered", ko: "등록됨" },
  "strategy.thesisStatus.inSampleTested": { en: "in-sample tested", ko: "인샘플 검정됨" },
  "strategy.thesisStatus.holdoutTested": { en: "holdout tested", ko: "홀드아웃 검정됨" },
  "strategy.thesisStatus.abandoned": { en: "abandoned", ko: "중단됨" },

  "strategy.thesis.verdict.survived": { en: "Survived", ko: "채택" },
  "strategy.thesis.verdict.rejected": { en: "Rejected", ko: "기각" },
  "strategy.thesis.verdict.inconclusive": { en: "Inconclusive", ko: "판단 불가" },

  "strategy.thesis.outcome.survivorFound": { en: "Survivor found", ko: "채택된 논거 있음" },
  "strategy.thesis.outcome.budgetExhausted": {
    en: "Budget exhausted — no thesis survived",
    ko: "예산 소진 — 채택된 논거 없음",
  },
  "strategy.thesis.outcome.catalogueExhausted": {
    en: "Catalogue exhausted — every available thesis was tried, none survived",
    ko: "카탈로그 소진 — 사용 가능한 모든 논거를 시도했으나 채택된 것이 없음",
  },
  "strategy.thesis.outcome.noData": { en: "No data", ko: "데이터 없음" },
  "strategy.thesis.outcome.holdoutUnavailable": { en: "Holdout unavailable", ko: "홀드아웃 사용 불가" },

  // --- shared error strings ----------------------------------------------------------------------
  "strategy.error.apiStatus": {
    en: "API returned {status}: {message}",
    ko: "API가 {status}을(를) 반환했습니다: {message}",
  },
  "strategy.error.unreachable": {
    en: "Cannot reach the API. Is uvicorn running on port 8000?",
    ko: "API에 연결할 수 없습니다. 8000번 포트에서 uvicorn이 실행 중인가요?",
  },

  // --- shared backtest vocabulary (reused across ScanTable/EventStudy/DrawdownTable/etc.) -------
  "strategy.backtest.underwaterBars": { en: "{count} bars", ko: "{count}봉" },
  "strategy.backtest.underwaterBarsOngoing": { en: "{count} bars+ (ongoing)", ko: "{count}봉+ (진행 중)" },
  "strategy.backtest.smallSampleBadge": { en: "small sample", ko: "소표본" },
  "strategy.backtest.error.noDrawdownProfile": {
    en: 'No drawdown profile for "{symbol}" at {interval}.',
    ko: '"{symbol}"의 {interval} 낙폭 프로필이 없습니다.',
  },
  "strategy.backtest.error.noEventStudyResult": {
    en: 'No event study result for "{symbol}".',
    ko: '"{symbol}"의 이벤트 스터디 결과가 없습니다.',
  },
  "strategy.backtest.error.noReverseProfile": {
    en: 'No reverse conditioning profile for "{symbol}".',
    ko: '"{symbol}"의 역조건부 분석 프로필이 없습니다.',
  },
  "strategy.backtest.error.noScanResult": {
    en: 'No scan result for "{symbol}".',
    ko: '"{symbol}"의 스캔 결과가 없습니다.',
  },

  // --- Backtest page (Backtest.tsx) ---------------------------------------------------------------
  "strategy.backtest.pageTitle": { en: "Backtest", ko: "백테스트" },
  "strategy.backtest.pageSubtitle": {
    en: "Sample size visible. Measured from {nextBarOpen}, since the signal close isn't tradeable, vs. the window's baseline.",
    ko: "표본 크기를 드러낸 채 아이디어를 과거로 검증합니다. {nextBarOpen}부터 측정 — 신호 봉의 종가는 체결 불가 가격입니다 — 같은 기간의 무조건부 기준선과 비교합니다.",
  },
  "strategy.backtest.pageSubtitleNextBarOpenWord": { en: "next bar's open", ko: "다음 봉의 시가" },
  "strategy.backtest.intervalAriaLabel": { en: "Interval", ko: "간격" },
  "strategy.backtest.loadButton": { en: "Load", ko: "불러오기" },
  "strategy.backtest.emptyIntro": {
    en: "Pick a symbol to begin. Four studies run against it:",
    ko: "시작하려면 종목을 선택하세요. 다음 네 가지 스터디가 실행됩니다:",
  },
  "strategy.backtest.emptyDrawdown": {
    en: "{heading} — every decline's depth, time to trough, and time to recover. Purely descriptive — read at face value.",
    ko: "{heading} — 모든 하락의 깊이, 저점까지 걸린 시간, 회복까지 걸린 시간. 순수하게 서술적이며 액면 그대로 읽으면 됩니다.",
  },
  "strategy.backtest.emptyEventStudy": {
    en: "{heading} — trigger dates vs. baseline. 70% hit rate means nothing if baseline is 70%. Add a second condition for A/B.",
    ko: "{heading} — 발동 시점을 항상 무조건부 기준선과 비교합니다. 기준선이 70%면 적중률 70%는 무의미합니다. 두 번째 조건으로 A/B 비교가 가능합니다.",
  },
  "strategy.backtest.emptyScan": {
    en: "{heading} — many conditions at once, with a visible trial counter and correction for testing many rules at once.",
    ko: "{heading} — 여러 조건을 한꺼번에 검정하며, 시행 횟수를 그대로 노출하고 여러 규칙을 한꺼번에 검정한 데 따른 보정을 적용합니다.",
  },
  "strategy.backtest.emptyReverse": {
    en: "{heading} — pick the biggest moves, then profile what preceded them. Exploratory: it generates candidates, not findings.",
    ko: "{heading} — 가장 큰 움직임을 선택한 뒤 그 이전 상황을 프로파일링합니다. 탐색적 분석이며, 결론이 아닌 후보를 생성합니다.",
  },
  "strategy.backtest.reverseConditioningWord": { en: "Reverse conditioning", ko: "역조건부 분석" },

  // --- Rules page (Rules.tsx) ---------------------------------------------------------------------
  "strategy.rules.title": { en: "Rules", ko: "규칙" },
  "strategy.rules.subtitle": {
    en: "Vocabulary plus a scratchpad to test expressions. Open a ticker to see rules {evaluated}.",
    ko: "규칙 어휘와 식 테스트용 스크래치패드입니다. 티커를 열면 규칙이 {evaluated} 상태를 볼 수 있습니다.",
  },
  "strategy.rules.subtitleEvaluatedWord": { en: "evaluated", ko: "평가된" },
  "strategy.rules.testHeading": { en: "Test a rule expression", ko: "규칙 식 테스트" },
  "strategy.rules.dslFieldsNote": {
    en: "Same grammar as the catalog. Fields: {open}, {high}, {low}, {close}, {volume}. Indicators: {sma}, {rsi}, {bbLower}.",
    ko: "카탈로그·판정 표와 동일한 문법입니다. 가격 필드: {open}, {high}, {low}, {close}, {volume}. 지표는 괄호 안에 매개변수 — {sma}, {rsi}, {bbLower}.",
  },
  "strategy.rules.loadingCatalog": { en: "Loading the rule catalog…", ko: "규칙 카탈로그 불러오는 중…" },
  "strategy.rules.catalogLoadError": { en: "Could not load the rule catalog.", ko: "규칙 카탈로그를 불러올 수 없습니다." },
  "strategy.rules.catalogEmpty": { en: "The rule catalog is empty.", ko: "규칙 카탈로그가 비어 있습니다." },
  "strategy.rules.catalogHeading": { en: "Catalog", ko: "카탈로그" },
  "strategy.rules.header.rule": { en: "Rule", ko: "규칙" },
  "strategy.rules.header.expression": { en: "Expression", ko: "식" },
  "strategy.rules.header.intervals": { en: "Intervals", ko: "간격" },
  "strategy.rules.header.description": { en: "Description", ko: "설명" },
  "strategy.rules.anyInterval": { en: "any", ko: "전체" },
  "strategy.rules.catalogCount_one": {
    en: "{count} rule. See any of them evaluated on {link} or another symbol.",
    ko: "규칙 {count}개. {link} 또는 다른 종목에서 평가된 모습을 확인하세요.",
  },
  "strategy.rules.catalogCount_other": {
    en: "{count} rules. See any of them evaluated on {link} or another symbol.",
    ko: "규칙 {count}개. {link} 또는 다른 종목에서 평가된 모습을 확인하세요.",
  },

  // --- RuleEditor.tsx / RuleValidationNote.tsx ----------------------------------------------------
  "strategy.ruleEditor.expressionLabel": { en: "Expression", ko: "식" },
  "strategy.ruleEditor.placeholderExample": { en: "e.g. {expression}", ko: "예: {expression}" },
  "strategy.ruleEditor.idleHint": {
    en: "Type an expression to check it against the rule DSL.",
    ko: "식을 입력하면 규칙 DSL 문법으로 검사합니다.",
  },
  "strategy.ruleEditor.checking": { en: "Checking…", ko: "확인 중…" },
  "strategy.ruleEditor.notValid": { en: "Not valid", ko: "유효하지 않음" },
  "strategy.ruleEditor.parserRejected": {
    en: "The parser rejected this expression.",
    ko: "파서가 이 식을 거부했습니다.",
  },
  "strategy.ruleEditor.valid": { en: "Valid", ko: "유효함" },
  "strategy.ruleEditor.understoodAs": { en: "Understood as", ko: "해석 결과" },
  "strategy.ruleEditor.indicatorsNeeded": { en: "Indicators needed", ko: "필요한 지표" },

  // --- ScanTable.tsx ---------------------------------------------------------------------------
  "strategy.scan.title": { en: "Scan", ko: "스캔" },
  "strategy.scan.subtitle": {
    en: "Many conditions at once manufacture discoveries. Every row is a trial, corrected.",
    ko: "여러 조건을 한꺼번에 검정하면 거짓 발견이 생깁니다. 모든 식은 하나의 시행이며 함께 보정됩니다.",
  },
  "strategy.scan.expressionsLabel": { en: "One expression per line", ko: "줄마다 식 하나씩" },
  "strategy.scan.horizonsLabel": { en: "Horizons (bars)", ko: "기간 (봉)" },
  "strategy.scan.alphaLabel": { en: "Target FDR (alpha)", ko: "목표 FDR (알파)" },
  "strategy.scan.scanningButton": { en: "Scanning…", ko: "스캔 중…" },
  "strategy.scan.runTestsButton": { en: "Run {count} tests", ko: "{count}건 검정 실행" },
  "strategy.scan.invalidLines_one": { en: "Line {line} does not parse", ko: "{line}번째 줄이 파싱되지 않습니다" },
  "strategy.scan.invalidLines_other": {
    en: "{count} lines do not parse",
    ko: "{count}개 줄이 파싱되지 않습니다",
  },
  "strategy.scan.lineLabel": { en: "Line {line}:", ko: "{line}번째 줄:" },
  "strategy.scan.planned_1_1": {
    en: "{exprCount} expression × {horizonCount} horizon = {total} simultaneous tests.",
    ko: "식 {exprCount}개 × 기간 {horizonCount}개 = 동시 검정 {total}건.",
  },
  "strategy.scan.planned_1_n": {
    en: "{exprCount} expression × {horizonCount} horizons = {total} simultaneous tests.",
    ko: "식 {exprCount}개 × 기간 {horizonCount}개 = 동시 검정 {total}건.",
  },
  "strategy.scan.planned_n_1": {
    en: "{exprCount} expressions × {horizonCount} horizon = {total} simultaneous tests.",
    ko: "식 {exprCount}개 × 기간 {horizonCount}개 = 동시 검정 {total}건.",
  },
  "strategy.scan.planned_n_n": {
    en: "{exprCount} expressions × {horizonCount} horizons = {total} simultaneous tests.",
    ko: "식 {exprCount}개 × 기간 {horizonCount}개 = 동시 검정 {total}건.",
  },
  "strategy.scan.stat.trials": { en: "Trials", ko: "시행" },
  "strategy.scan.stat.discoveries": { en: "Discoveries", ko: "발견" },
  "strategy.scan.stat.uncorrectedP05": { en: "Uncorrected p ≤ 0.05", ko: "보정 전 p ≤ 0.05" },
  "strategy.scan.stat.untestable": { en: "Untestable (still counted)", ko: "검정 불가 (그래도 집계됨)" },
  "strategy.scan.stat.targetFdr": { en: "Target FDR", ko: "목표 FDR" },
  "strategy.scan.stat.bars": { en: "Bars", ko: "봉" },
  "strategy.scan.reading.zeroDiscoveries": {
    en: "Nothing survived correction across {trials} tests.",
    ko: "{trials}건의 검정 중 보정을 통과한 것이 없습니다.",
  },
  "strategy.scan.reading.rawAt05_one": {
    en: "{count} row would clear an uncorrected p ≤ 0.05 screen — what running {trials} tests at once does to a p-value.",
    ko: "{count}개 행이 보정 전 p ≤ 0.05 기준은 통과했을 것입니다 — {trials}건을 한꺼번에 검정하면 p값에 바로 이런 일이 벌어집니다.",
  },
  "strategy.scan.reading.rawAt05_other": {
    en: "{count} rows would clear an uncorrected p ≤ 0.05 screen — what running {trials} tests at once does to a p-value.",
    ko: "{count}개 행이 보정 전 p ≤ 0.05 기준은 통과했을 것입니다 — {trials}건을 한꺼번에 검정하면 p값에 바로 이런 일이 벌어집니다.",
  },
  "strategy.scan.reading.discoveries": {
    en: "{discoveries} of {trials} tests cleared q ≤ {alpha} — a set statement, not any one row: ~{percent}% of flags are noise.",
    ko: "{trials}건 중 {discoveries}건이 q ≤ {alpha} 기준을 통과했습니다. 이는 개별 행이 아니라 전체 집합에 대한 진술입니다 — 표시된 행 중 약 {percent}%는 노이즈일 것으로 예상됩니다.",
  },
  "strategy.scan.header.expression": { en: "Expression", ko: "식" },
  "strategy.scan.header.horizon": { en: "Horizon", ko: "기간" },
  "strategy.scan.header.edge": { en: "Edge", ko: "엣지" },
  "strategy.scan.header.indepN": { en: "Indep. n", ko: "독립 표본 n" },
  "strategy.scan.header.p": { en: "p", ko: "p" },
  "strategy.scan.header.q": { en: "q", ko: "q" },
  "strategy.scan.header.verdict": { en: "Verdict", ko: "판정" },
  "strategy.scan.recordedAsRun": { en: "Recorded as run {runId}", ko: "실행 {runId}(으)로 기록됨" },
  "strategy.scan.hitRateVsBaseline": { en: "{hit} vs {baseline}", ko: "{hit} 대 {baseline}" },
  "strategy.scan.guardBadge": { en: "guard {status}", ko: "가드 {status}" },
  "strategy.scan.discoveryBadgeTitle": {
    en: "q ≤ alpha across this scan. An expected-false-discovery-rate statement about the set, not a claim about this row.",
    ko: "이 스캔 전체에서 q ≤ 알파입니다. 이는 전체 집합에 대한 기대 거짓 발견율 진술이며, 이 행 하나에 대한 주장이 아닙니다.",
  },
  "strategy.scan.survivesCorrection": { en: "survives correction", ko: "보정 통과" },
  "strategy.scan.notTestable": { en: "not testable", ko: "검정 불가" },
  "strategy.scan.no": { en: "no", ko: "아니요" },

  // --- EventStudy.tsx ------------------------------------------------------------------------------
  "strategy.eventStudy.title": { en: "Event study", ko: "이벤트 스터디" },
  "strategy.eventStudy.conditionBase": { en: "Condition (base)", ko: "조건 (기준)" },
  "strategy.eventStudy.conditionArmB": { en: "Condition (arm B)", ko: "조건 (B군)" },
  "strategy.eventStudy.removeArm": { en: "remove", ko: "제거" },
  "strategy.eventStudy.addSecondArm": { en: "+ add second arm", ko: "+ 두 번째 조건 추가" },
  "strategy.eventStudy.entryLabel": { en: "Entry", ko: "진입" },
  "strategy.eventStudy.entryNextOpen": { en: "next open", ko: "다음 시가" },
  "strategy.eventStudy.entrySameClose": { en: "same close (upper bound)", ko: "당일 종가 (상한값)" },
  "strategy.eventStudy.runButton": { en: "Run event study", ko: "이벤트 스터디 실행" },
  "strategy.eventStudy.idlePlaceholder": {
    en: "Enter at least one condition and run the study.",
    ko: "조건을 하나 이상 입력하고 스터디를 실행하세요.",
  },
  "strategy.eventStudy.runningPlaceholder": { en: "Running event study…", ko: "이벤트 스터디 실행 중…" },
  "strategy.eventStudy.sampleMeta": {
    en: "Sample {first} → {last} · {bars} bars",
    ko: "표본 {first} → {last} · {bars}개 봉",
  },
  "strategy.eventStudy.baseConditionHeading": { en: "Base condition", ko: "기준 조건" },
  "strategy.eventStudy.armBHeading": { en: "Arm B", ko: "B군" },
  "strategy.eventStudy.armMeta": {
    en: "{triggers} triggers · {evaluable} evaluable bars",
    ko: "발동 {triggers}회 · 평가 가능 봉 {evaluable}개",
  },
  "strategy.eventStudy.totalFires": {
    en: " · {count} total fires (incl. incomplete windows)",
    ko: " · 전체 발동 {count}회 (미완결 구간 포함)",
  },
  "strategy.eventStudy.noHorizonStats": {
    en: "No horizon statistics returned for this condition.",
    ko: "이 조건에 대한 기간별 통계가 없습니다.",
  },
  "strategy.eventStudy.header.horizon": { en: "Horizon", ko: "기간" },
  "strategy.eventStudy.header.edgeHitBase": { en: "Edge / hit rate / base", ko: "엣지 / 적중률 / 기준" },
  "strategy.eventStudy.header.medianDistribution": {
    en: "Median & distribution (p05–p95)",
    ko: "중앙값 및 분포 (p05–p95)",
  },
  "strategy.eventStudy.header.sampleIndependent": {
    en: "Sample (independent)",
    ko: "표본 (독립)",
  },
  "strategy.eventStudy.guardUnverified": {
    en: "Guard unverified — treated as a failure. No statistics computed for this condition.",
    ko: "가드 미검증 — 실패로 처리됩니다. 이 조건에 대한 통계가 계산되지 않았습니다.",
  },
  "strategy.eventStudy.guardFailed": {
    en: "Guard failed. No statistics computed for this condition.",
    ko: "가드 실패. 이 조건에 대한 통계가 계산되지 않았습니다.",
  },
  "strategy.eventStudy.hitVsBaseline": { en: "{hit} vs {baseline} base", ko: "{hit} 대 기준 {baseline}" },
  "strategy.eventStudy.sameCloseTitle": {
    en: "Entry assumed at the same bar's close -- an unrealistic fill, upper bound only",
    ko: "진입가를 해당 봉의 종가로 가정합니다 -- 비현실적인 체결이며 상한값만을 의미합니다",
  },
  "strategy.eventStudy.sameCloseTag": { en: "upper bound (same-close)", ko: "상한값 (당일 종가)" },
  "strategy.eventStudy.medianLabel": { en: "{value} median", ko: "중앙값 {value}" },
  "strategy.eventStudy.indepLabel": { en: "{count} indep", ko: "독립 {count}" },
  "strategy.eventStudy.sampleRawBase": {
    en: "{raw} raw · base {base}",
    ko: "원표본 {raw} · 기준 {base}",
  },
  "strategy.eventStudy.smallSampleTitle": {
    en: "Independent sample below {threshold}",
    ko: "독립 표본이 {threshold} 미만",
  },
  "strategy.eventStudy.deltaHeading": { en: "Arm B vs base", ko: "B군 대 기준" },
  "strategy.eventStudy.deltaHeader.hitRateDelta": { en: "Hit-rate delta", ko: "적중률 변화" },
  "strategy.eventStudy.deltaHeader.medianDelta": { en: "Median delta", ko: "중앙값 변화" },
  "strategy.eventStudy.deltaHeader.sampleSizeDelta": {
    en: "Sample size delta (independent)",
    ko: "표본 크기 변화 (독립)",
  },
  "strategy.eventStudy.deltaSampleCell": {
    en: "{rawSign}{raw} raw ({indepSign}{indep} indep)",
    ko: "원표본 {rawSign}{raw} (독립 {indepSign}{indep})",
  },
  "strategy.eventStudy.deltaCaution": {
    en: "gain built on a shrinking sample",
    ko: "표본이 줄어드는 상태에서 얻은 상승",
  },

  // --- DrawdownTable.tsx -----------------------------------------------------------------------
  "strategy.drawdown.title": { en: "Drawdown profile", ko: "낙폭 프로필" },
  "strategy.drawdown.basisAriaLabel": { en: "Drawdown basis", ko: "낙폭 기준" },
  "strategy.drawdown.basisLabel": { en: "Basis", ko: "기준" },
  "strategy.drawdown.basis.close": { en: "Close", ko: "종가" },
  "strategy.drawdown.basis.adjClose": { en: "Adj close", ko: "수정 종가" },
  "strategy.drawdown.basis.intraday": { en: "Intraday", ko: "장중" },
  "strategy.drawdown.loading": { en: "Loading drawdown profile…", ko: "낙폭 프로필 불러오는 중…" },
  "strategy.drawdown.stat.sample": { en: "Sample", ko: "표본" },
  "strategy.drawdown.stat.bars": { en: "Bars", ko: "봉" },
  "strategy.drawdown.stat.episodesConsidered": { en: "Episodes considered", ko: "검토된 사건 수" },
  "strategy.drawdown.topEpisodesHeading": {
    en: "Top {n} of {total} episodes, deepest first",
    ko: "전체 {total}건 중 상위 {n}건, 낙폭이 큰 순",
  },
  "strategy.drawdown.noEpisodes": {
    en: "No drawdown episodes found for {symbol}.",
    ko: "{symbol}에 대한 낙폭 사건이 없습니다.",
  },
  "strategy.drawdown.tableAriaLabel": {
    en: "Drawdown episodes for {symbol}, basis {basis}",
    ko: "{symbol}의 낙폭 사건, 기준 {basis}",
  },
  "strategy.drawdown.header.peak": { en: "Peak", ko: "고점" },
  "strategy.drawdown.header.trough": { en: "Trough", ko: "저점" },
  "strategy.drawdown.header.depth": { en: "Depth ({basis})", ko: "낙폭 ({basis})" },
  "strategy.drawdown.header.barsToTrough": { en: "Bars to trough", ko: "저점까지 봉 수" },
  "strategy.drawdown.header.recovery": { en: "Recovery", ko: "회복" },
  "strategy.drawdown.header.underwater": { en: "Underwater", ko: "미회복 기간" },
  "strategy.drawdown.currentLabel": {
    en: "Current drawdown ({basis} basis)",
    ko: "현재 낙폭 ({basis} 기준)",
  },
  "strategy.drawdown.notUnderwater": { en: "Not currently underwater.", ko: "현재 낙폭 상태가 아닙니다." },
  "strategy.drawdown.asOf": { en: "as of {date}", ko: "{date} 기준" },
  "strategy.drawdown.peakMeta": { en: "peak {date} ({value})", ko: "고점 {date} ({value})" },
  "strategy.drawdown.fellToLow": {
    en: "fell {depth} to its low on {date}",
    ko: "{date}에 {depth} 하락하며 저점을 기록",
  },
  "strategy.drawdown.underwaterSuffix": { en: "{underwater} underwater", ko: "{underwater} 미회복" },
  "strategy.drawdown.recoveredMeta": { en: "recovered {date}", ko: "{date} 회복" },

  // --- ReverseConditioning.tsx -----------------------------------------------------------------
  "strategy.reverse.exploratoryBadge": { en: "exploratory", ko: "탐색적" },
  "strategy.reverse.banner": {
    en: "Read off the data, not tested. Not findings — candidates, until tested as a declared trial in a scan.",
    ko: "이 조건들은 데이터를 검정한 것이 아니라 데이터에서 읽어낸 것입니다. 여기 있는 것은 결론이 아니라 후보 목록이며, 후보는 스캔에서 공식 시행으로 검정된 뒤에야 결과가 됩니다.",
  },
  "strategy.reverse.title": { en: "What preceded the biggest moves", ko: "가장 큰 움직임 이전의 상황" },
  "strategy.reverse.subtitle": {
    en: "Selects the strongest forward moves, then profiles each indicator in the bars before them.",
    ko: "가장 강한 순방향 움직임을 선택한 뒤, 그 이전 봉에서 각 지표가 어디에 있었는지 살펴봅니다. 직접 추측하는 대신 후보 조건을 생성해 줍니다.",
  },
  "strategy.reverse.moveMeasuredLabel": { en: "Move measured over", ko: "움직임 측정 기간" },
  "strategy.reverse.selectTopLabel": { en: "Select top", ko: "상위 선택" },
  "strategy.reverse.decileOption": { en: "decile (10%)", ko: "십분위 (10%)" },
  "strategy.reverse.quintileOption": { en: "quintile (20%)", ko: "오분위 (20%)" },
  "strategy.reverse.profilePriorLabel": { en: "Profile the prior", ko: "프로파일링할 이전 구간" },
  "strategy.reverse.signalBarOnly": { en: "signal bar only", ko: "신호 봉만" },
  "strategy.reverse.profilingButton": { en: "Profiling…", ko: "프로파일링 중…" },
  "strategy.reverse.profileButton": { en: "Profile", ko: "프로파일링" },
  "strategy.reverse.stat.barsSelected": { en: "Bars selected", ko: "선택된 봉" },
  "strategy.reverse.stat.distinctEpisodes": { en: "Distinct episodes", ko: "고유 사건 수" },
  "strategy.reverse.stat.moveHorizon": { en: "Move horizon", ko: "움직임 기간" },
  "strategy.reverse.stat.priorWindow": { en: "Prior window", ko: "이전 구간" },
  "strategy.reverse.signalBar": { en: "signal bar", ko: "신호 봉" },
  "strategy.reverse.overstatementWarning": {
    en: "{selected} bars are mostly consecutive — about {independent} episodes. Raw count overstates evidence ~{factor}×.",
    ko: "선택된 {selected}개 봉은 대부분 연속적입니다 — 실제로는 약 {independent}개의 고유 사건에 해당하며, 원래 개수는 근거를 약 {factor}배 과장합니다.",
  },
  "strategy.reverse.noProfiles": {
    en: "No indicator profiles for this selection.",
    ko: "이 선택에 대한 지표 프로필이 없습니다.",
  },
  "strategy.reverse.header.indicator": { en: "Indicator", ko: "지표" },
  "strategy.reverse.header.beforeMove": { en: "Before the move", ko: "움직임 이전" },
  "strategy.reverse.header.usually": { en: "Usually", ko: "평소" },
  "strategy.reverse.header.shift": { en: "Shift", ko: "이동" },
  "strategy.reverse.noSpread": { en: "no spread", ko: "산포 없음" },
  "strategy.reverse.noSpreadTitle": {
    en: "This indicator did not move over the sample, so there is no scale to express a shift in.",
    ko: "이 지표는 표본 기간 동안 움직이지 않아 이동을 표현할 척도가 없습니다.",
  },
  "strategy.reverse.iqrsHigher": { en: "IQRs higher", ko: "IQR만큼 높음" },
  "strategy.reverse.iqrsLower": { en: "IQRs lower", ko: "IQR만큼 낮음" },

  // --- StrategyCard.tsx ------------------------------------------------------------------------
  "strategy.strategyCard.title": { en: "Strategy backtest", ko: "전략 백테스트" },
  "strategy.strategyCard.subtitle": {
    en: "Rules vs. buy-and-hold, net of costs. Excess matters, not raw return — read with exposure.",
    ko: "규칙 기반 전략 대 매수 후 보유, 비용 차감 후. 중요한 건 초과분이지 수익률 자체가 아니며, 노출도 없이는 의미가 없습니다.",
  },
  "strategy.strategyCard.entryRuleLabel": { en: "Entry rule", ko: "진입 규칙" },
  "strategy.strategyCard.exitRuleLabel": { en: "Exit rule (optional)", ko: "청산 규칙 (선택)" },
  "strategy.strategyCard.maxHoldingLabel": { en: "Max holding (bars)", ko: "최대 보유 기간 (봉)" },
  "strategy.strategyCard.nonePlaceholder": { en: "none", ko: "없음" },
  "strategy.strategyCard.stopLossLabel": { en: "Stop loss (%)", ko: "손절 (%)" },
  "strategy.strategyCard.slippageLabel": { en: "Slippage (bps)", ko: "슬리피지 (bps)" },
  "strategy.strategyCard.defaultPlaceholder": { en: "default", ko: "기본값" },
  "strategy.strategyCard.runningButton": { en: "Running…", ko: "실행 중…" },
  "strategy.strategyCard.runButton": { en: "Run strategy", ko: "전략 실행" },
  "strategy.strategyCard.idlePlaceholder": {
    en: "Enter an entry rule and run the backtest.",
    ko: "진입 규칙을 입력하고 백테스트를 실행하세요.",
  },
  "strategy.strategyCard.verdictUnderperforms": {
    en: "Trailed buy-and-hold by {excess} over the same window. Frictions cost {drag} of that; the rest is the rules themselves.",
    ko: "이 전략은 같은 기간 단순 보유 대비 {excess}만큼 뒤처졌습니다. 그중 {drag}는 거래 비용 때문이며, 나머지는 규칙 자체의 결과입니다.",
  },
  "strategy.strategyCard.verdictInsideCosts": {
    en: "Edge over buy-and-hold ({excess}) is smaller than this run's costs ({drag}). No edge demonstrated net of own frictions.",
    ko: "매수 후 보유 대비 우위({excess})가 이번 실행의 슬리피지·수수료({drag})보다 작습니다. 자체 비용을 제하면 입증된 우위가 없습니다.",
  },
  "strategy.strategyCard.field.entry": { en: "Entry", ko: "진입" },
  "strategy.strategyCard.field.exit": { en: "Exit", ko: "청산" },
  "strategy.strategyCard.field.maxHolding": { en: "Max holding", ko: "최대 보유 기간" },
  "strategy.strategyCard.field.stopLoss": { en: "Stop loss", ko: "손절" },
  "strategy.strategyCard.field.slippage": { en: "Slippage", ko: "슬리피지" },
  "strategy.strategyCard.field.commissionPerTrade": { en: "Commission / trade", ko: "거래당 수수료" },
  "strategy.strategyCard.field.costDrag": { en: "Cost drag", ko: "비용 손실" },
  "strategy.strategyCard.field.sample": { en: "Sample", ko: "표본" },
  "strategy.strategyCard.field.tradesOpened": { en: "Trades opened", ko: "진입한 거래" },
  "strategy.strategyCard.field.stillOpen": { en: "…of which still open", ko: "…그중 아직 보유 중" },
  "strategy.strategyCard.field.tradesPerYear": { en: "Trades opened / year", ko: "연간 진입 거래 수" },
  "strategy.strategyCard.field.barsPerYear": {
    en: "Bars / year (annualising basis)",
    ko: "연간 봉 수 (연환산 기준)",
  },
  "strategy.strategyCard.guardUnverified": {
    en: "Guard unverified — treated as a failure. No strategy numbers are shown.",
    ko: "가드 미검증 — 실패로 처리됩니다. 전략 수치를 표시하지 않습니다.",
  },
  "strategy.strategyCard.guardFailed": {
    en: "Guard failed. No strategy numbers are shown.",
    ko: "가드 실패. 전략 수치를 표시하지 않습니다.",
  },
  "strategy.strategyCard.header.metric": { en: "Metric", ko: "지표" },
  "strategy.strategyCard.header.strategy": { en: "Strategy", ko: "전략" },
  "strategy.strategyCard.header.buyHold": { en: "Buy & hold", ko: "매수 후 보유" },
  "strategy.strategyCard.header.excess": { en: "Excess", ko: "초과분" },
  "strategy.strategyCard.metric.totalReturn": { en: "Total return", ko: "총수익률" },
  "strategy.strategyCard.metric.cagr": { en: "CAGR", ko: "연평균 성장률 (CAGR)" },
  "strategy.strategyCard.metric.volatility": { en: "Volatility (ann.)", ko: "변동성 (연환산)" },
  "strategy.strategyCard.metric.sharpe": { en: "Sharpe", ko: "샤프 비율" },
  "strategy.strategyCard.metric.sortino": { en: "Sortino", ko: "소르티노 비율" },
  "strategy.strategyCard.metric.maxDrawdown": { en: "Max drawdown", ko: "최대 낙폭" },
  "strategy.strategyCard.metric.exposure": { en: "Exposure", ko: "노출도" },
  "strategy.strategyCard.metric.winRate": { en: "Win rate (closed trades)", ko: "승률 (청산 거래 기준)" },
  "strategy.strategyCard.exposureSub": { en: "exposure {value}", ko: "노출도 {value}" },
  "strategy.strategyCard.rfSub": { en: "rf {value}", ko: "무위험 수익률 {value}" },
  "strategy.strategyCard.tradesHeading": { en: "Trades", ko: "거래" },
  "strategy.strategyCard.openTradesNote_one": {
    en: "{count} trade still open at sample end — marked below as unrealized, excluded from the win rate above.",
    ko: "표본 종료 시점에 아직 보유 중인 거래가 {count}건 있습니다 -- 아래에는 미실현 평가로 표시되며 위 승률에서는 제외됩니다.",
  },
  "strategy.strategyCard.openTradesNote_other": {
    en: "{count} trades still open at sample end — marked below as unrealized, excluded from the win rate above.",
    ko: "표본 종료 시점에 아직 보유 중인 거래가 {count}건 있습니다 -- 아래에는 미실현 평가로 표시되며 위 승률에서는 제외됩니다.",
  },
  "strategy.strategyCard.noTrades": {
    en: "No trades were taken by this strategy over the sample.",
    ko: "이 전략은 표본 기간 동안 거래를 진입하지 않았습니다.",
  },
  "strategy.strategyCard.tradesHeader.entry": { en: "Entry", ko: "진입" },
  "strategy.strategyCard.tradesHeader.exit": { en: "Exit", ko: "청산" },
  "strategy.strategyCard.tradesHeader.barsHeld": { en: "Bars held", ko: "보유 봉 수" },
  "strategy.strategyCard.tradesHeader.return": { en: "Return", ko: "수익률" },
  "strategy.strategyCard.tradesHeader.exitReason": { en: "Exit reason", ko: "청산 사유" },
  "strategy.strategyCard.openBadgeTitle": {
    en: "Unrealized mark at the end of the sample -- excluded from the win rate",
    ko: "표본 종료 시점의 미실현 평가 -- 승률에서 제외됨",
  },
  "strategy.strategyCard.openBadgeText": { en: "open — unrealized", ko: "보유 중 — 미실현" },
  "strategy.strategyCard.equityCurveHeading": { en: "Equity curve", ko: "자산 곡선" },
  "strategy.strategyCard.equityChartAriaLabel": {
    en: "Strategy equity versus buy-and-hold, same axis",
    ko: "전략 자산 대 매수 후 보유, 동일 축",
  },

  // --- Thesis page (Thesis.tsx) -----------------------------------------------------------------
  "strategy.thesis.error.noLedger": {
    en: 'No trial ledger for "{symbol}" yet.',
    ko: '"{symbol}"의 시행 원장이 아직 없습니다.',
  },
  "strategy.thesis.error.noRunResult": {
    en: 'No thesis run result for "{symbol}".',
    ko: '"{symbol}"의 논거 실행 결과가 없습니다.',
  },
  "strategy.thesis.holdout.none": {
    en: "No holdout established for this ticker yet.",
    ko: "이 종목에는 아직 홀드아웃이 설정되지 않았습니다.",
  },
  "strategy.thesis.holdout.unused": {
    en: "Holdout reserved from {date} onward, never evaluated. One evaluation is available.",
    ko: "{date} 이후로 홀드아웃이 예약되어 있으며 아직 평가된 적이 없습니다. 평가 1회를 사용할 수 있습니다.",
  },
  "strategy.thesis.holdout.spent": {
    en: "Holdout from {date} was evaluated once, on {when}. That result stands — no further out-of-sample test remains.",
    ko: "{date}부터의 홀드아웃은 {when}에 한 차례 평가되었습니다. 그 결과가 유효하며, 이 종목에는 더 이상 아웃오브샘플 검정을 사용할 수 없습니다.",
  },
  "strategy.thesis.holdout.earlierRun": { en: "an earlier run", ko: "이전 실행" },
  "strategy.thesis.holdout.burned": {
    en: "Holdout from {date}, evaluated {attempts}× — no longer out-of-sample. In-sample — not validated out of sample.",
    ko: "{date}부터 홀드아웃을 {attempts}회 평가했습니다 — 더 이상 아웃오브샘플이 아닙니다. 인-샘플 — 표본 외 미검증.",
  },
  "strategy.thesis.pageTitle": { en: "Thesis", ko: "투자 논거" },
  "strategy.thesis.promptSubtitle": {
    en: "Theses tested against a locked holdout, corrected over a ticker's history. Most come back inconclusive — expected.",
    ko: "논거를 잠긴 홀드아웃과 시행 원장, 종목의 모든 논거에 대한 거짓 발견 보정으로 검정합니다. 대부분 판단 불가로 돌아오며 이는 예상된 결과입니다.",
  },
  "strategy.thesis.symbolPlaceholder": { en: "SYMBOL", ko: "종목 코드" },
  "strategy.thesis.goButton": { en: "Go", ko: "이동" },
  "strategy.thesis.noSymbolYet": {
    en: "No symbol yet. Try one of these:",
    ko: "아직 선택된 종목이 없습니다. 다음 중 하나를 시도해 보세요:",
  },
  "strategy.thesis.detailSubtitle": {
    en: "Catalogue theses, adversarially tested against a locked holdout with a global trial ledger and a false-discovery correction over every thesis ever registered for {symbol}.",
    ko: "고정된 목록의 논거를 잠긴 홀드아웃으로 적대적으로 검정하며, 전역 시행 원장과 {symbol}에 등록된 모든 논거에 대한 거짓 발견 보정을 함께 적용합니다.",
  },
  "strategy.thesis.runHeading": { en: "Run a thesis loop", ko: "논거 루프 실행" },
  "strategy.thesis.runWarning": {
    en: "Every iteration, even blanks, logs to {symbol}'s ledger permanently and counts toward q-values. May spend its holdout.",
    ko: "결과 없는 반복까지 포함해 모든 반복이 {symbol}의 원장에 영구히 기록되며 향후 모든 q값에 반영됩니다. 유일한 홀드아웃 평가를 소진할 수도 있습니다.",
  },
  "strategy.thesis.iterationBudgetLabel": { en: "Iteration budget", ko: "반복 예산" },
  "strategy.thesis.runningButton": { en: "Running…", ko: "실행 중…" },
  "strategy.thesis.runLoopButton": { en: "Run thesis loop (budget {budget})", ko: "논거 루프 실행 (예산 {budget})" },
  "strategy.thesis.holdoutHeading": { en: "Holdout — {symbol}", ko: "홀드아웃 — {symbol}" },
  "strategy.thesis.warningsHeading": { en: "Warnings", ko: "경고" },
  "strategy.thesis.noCards": {
    en: "No strategy card was produced by this run.",
    ko: "이번 실행에서 생성된 전략 카드가 없습니다.",
  },
  "strategy.thesis.outcomeHeading": { en: "Run outcome", ko: "실행 결과" },
  "strategy.thesis.outcomeMeta": {
    en: "{used} of {budget} iterations used · started {started} · finished {finished}",
    ko: "예산 {budget}회 중 {used}회 사용 · 시작 {started} · 종료 {finished}",
  },
  "strategy.thesis.outcomeText.survivorFound_one": {
    en: "{count} thesis survived the loop's guards on {symbol}.",
    ko: "{symbol}에서 논거 {count}건이 루프의 가드를 통과했습니다.",
  },
  "strategy.thesis.outcomeText.survivorFound_other": {
    en: "{count} theses survived the loop's guards on {symbol}.",
    ko: "{symbol}에서 논거 {count}건이 루프의 가드를 통과했습니다.",
  },
  "strategy.thesis.outcomeText.budgetExhausted_one": {
    en: "No thesis survived {count} attempt on {symbol}. That is real information about the ticker, not a failed run.",
    ko: "{symbol}에서 {count}회 시도했지만 살아남은 논거가 없습니다. 이는 실행 실패가 아니라 이 종목에 대한 실제 정보입니다.",
  },
  "strategy.thesis.outcomeText.budgetExhausted_other": {
    en: "No thesis survived {count} attempts on {symbol}. That is real information about the ticker, not a failed run.",
    ko: "{symbol}에서 {count}회 시도했지만 살아남은 논거가 없습니다. 이는 실행 실패가 아니라 이 종목에 대한 실제 정보입니다.",
  },
  "strategy.thesis.outcomeText.catalogueExhausted": {
    en: "All {symbol} theses tried ({count}); none survived. Hypotheses ran out first — about the catalogue, not the ticker.",
    ko: "{symbol}의 사용 가능한 논거({count}개)를 모두 시도했지만 살아남은 것이 없습니다. 예산보다 가설이 먼저 소진됐습니다 — 종목이 아닌 카탈로그에 대한 정보입니다.",
  },
  "strategy.thesis.outcomeText.noData": {
    en: "No usable price history for {symbol} — the loop could not run.",
    ko: "{symbol}에 사용 가능한 가격 이력이 없어 루프를 실행할 수 없었습니다.",
  },
  "strategy.thesis.outcomeText.holdoutUnavailable": {
    en: "{symbol}'s holdout is already spent or burned — nothing here evaluates out-of-sample. Refused, not in-sample only.",
    ko: "{symbol}의 홀드아웃이 이미 소진되었거나 다 써버려서 아웃오브샘플로 평가할 수 있는 것이 없습니다. 인샘플로만 보고하는 대신 거부되었습니다.",
  },

  // --- ThesisCard.tsx --------------------------------------------------------------------------
  "strategy.thesisCard.unleveredHeading": { en: "Unlevered comparison", ko: "무레버리지 비교" },
  "strategy.thesisCard.headerTitle": { en: "{symbol} — thesis card", ko: "{symbol} — 논거 카드" },
  "strategy.thesisCard.meta": { en: "{interval} · generated {date}", ko: "{interval} · {date} 생성" },
  "strategy.thesisCard.promote.button": { en: "Promote to library", ko: "라이브러리에 추가" },
  "strategy.thesisCard.promote.promoting": { en: "Promoting…", ko: "추가 중…" },
  "strategy.thesisCard.promote.done": { en: "Added to the library", ko: "라이브러리에 추가됨" },
  "strategy.thesisCard.promote.exists": { en: "Already on the shelf", ko: "이미 라이브러리에 있음" },
  "strategy.thesisCard.promote.errorLabel": { en: "Could not promote", ko: "추가하지 못함" },
  "strategy.thesisCard.promote.errorGeneric": {
    en: "Something went wrong.",
    ko: "문제가 발생했습니다.",
  },
  "strategy.thesisCard.ledgerAtEvaluation": {
    en: " · ledger at evaluation: {count} total trials",
    ko: " · 평가 시점 원장: 총 시행 {count}건",
  },
  "strategy.thesisCard.holdoutBurnedHeadline": {
    en: "Holdout burned — {attempts} evaluations.",
    ko: "홀드아웃 소진 — 평가 {attempts}회.",
  },
  "strategy.thesisCard.falsifiesLabel": {
    en: "Falsifies if — declared before any test ran",
    ko: "반증 조건 — 검정 실행 전에 선언됨",
  },
  "strategy.thesisCard.directionHorizon": {
    en: "Predicted direction: {direction} · horizon {horizon} bars",
    ko: "예측 방향: {direction} · 기간 {horizon}봉",
  },
  "strategy.thesisCard.field.entry": { en: "Entry", ko: "진입" },
  "strategy.thesisCard.field.exit": { en: "Exit", ko: "청산" },
  "strategy.thesisCard.field.triggersPerYear": { en: "Triggers / year", ko: "연간 발동 횟수" },
  "strategy.thesisCard.field.holdingPeriodMedian": {
    en: "Holding period (median)",
    ko: "보유 기간 (중앙값)",
  },
  "strategy.thesisCard.field.holdingPeriodIqr": { en: "Holding period IQR", ko: "보유 기간 IQR" },
  "strategy.thesisCard.holdingIqrValue": { en: "{lo} – {hi} bars", ko: "{lo} – {hi}봉" },
  "strategy.thesisCard.field.worstTrade": { en: "Worst trade", ko: "최악의 거래" },
  "strategy.thesisCard.field.maxDrawdownInPosition": {
    en: "Max drawdown in position",
    ko: "보유 중 최대 낙폭",
  },
  "strategy.thesisCard.inSampleLabel": { en: "In-sample", ko: "인샘플" },
  "strategy.thesisCard.holdoutLabel": { en: "Holdout", ko: "홀드아웃" },
  "strategy.thesisCard.notEvaluated": { en: "Not evaluated.", ko: "평가되지 않음." },
  "strategy.thesisCard.returnDistHeading": {
    en: "Expected return vs. baseline",
    ko: "기대 수익률 대 기준선",
  },
  "strategy.thesisCard.distHeader.median": { en: "Median", ko: "중앙값" },
  "strategy.thesisCard.distHeader.p05p95": { en: "p05 – p95", ko: "p05 – p95" },
  "strategy.thesisCard.distHeader.mean": { en: "Mean", ko: "평균" },
  "strategy.thesisCard.distHeader.n": { en: "n", ko: "n" },
  "strategy.thesisCard.expectedRuleLabel": { en: "Expected (this rule)", ko: "기대값 (이 규칙)" },
  "strategy.thesisCard.baselineUnconditionalLabel": {
    en: "Baseline (unconditional)",
    ko: "기준선 (무조건부)",
  },
  "strategy.thesisCard.evidence.hitRateVsBaseline": { en: "Hit rate vs baseline", ko: "적중률 대 기준선" },
  "strategy.thesisCard.evidence.medianReturnVsBaseline": {
    en: "Median return vs baseline",
    ko: "중앙값 수익률 대 기준선",
  },
  "strategy.thesisCard.evidence.pValue": { en: "p-value", ko: "p값" },
  "strategy.thesisCard.evidence.qValueTrialFamily": {
    en: "q-value (trial family)",
    ko: "q값 (시행 집합)",
  },
  "strategy.thesisCard.evidence.independentSample": { en: "Independent sample", ko: "독립 표본" },
  "strategy.thesisCard.vsPattern": { en: "{a} vs {b}", ko: "{a} 대 {b}" },
  "strategy.thesisCard.regimeHeading": { en: "Regime slices", ko: "국면별 분할" },
  "strategy.thesisCard.regimeNote": {
    en: "Same statistics inside one regime. A {conditional} slice departs from the overall figure — any edge held only there.",
    ko: "동일 통계를 한 국면 안에서 측정합니다. {conditional} 구간은 전체 수치와 어긋나며, 엣지는 그 국면에서만 성립할 뿐입니다.",
  },
  "strategy.thesisCard.conditionalBadge": { en: "conditional", ko: "국면 의존" },
  "strategy.thesisCard.regimeHeader.regime": { en: "Regime", ko: "국면" },
  "strategy.thesisCard.regimeHeader.bars": { en: "Bars", ko: "봉" },
  "strategy.thesisCard.regimeHeader.edgeVsBaseline": { en: "Edge vs baseline", ko: "엣지 대 기준선" },
  "strategy.thesisCard.taxHeading": { en: "Tax impact", ko: "세금 영향" },
  "strategy.thesisCard.washSaleHeadline_one": {
    en: "This strategy's own re-entries would have triggered {count} wash sale against itself",
    ko: "이 전략의 재진입만으로도 자체적으로 워시 세일 {count}건이 발생했을 것입니다",
  },
  "strategy.thesisCard.washSaleHeadline_other": {
    en: "This strategy's own re-entries would have triggered {count} wash sales against itself",
    ko: "이 전략의 재진입만으로도 자체적으로 워시 세일 {count}건이 발생했을 것입니다",
  },
  "strategy.thesisCard.washSaleDisallowed": {
    en: " — {loss} of loss disallowed",
    ko: " — 손실 {loss} 부인됨",
  },
  "strategy.thesisCard.washSaleIraClause": {
    en: "Taxable + IRA: a taxable loss replaced in the IRA is {permanently} disallowed under Rev. Rul. 2008-5 — not deferred.",
    ko: "과세 계좌와 IRA 양쪽에 보유 중입니다: 과세 계좌에서 실현한 손실을 IRA에서 재매수로 대체하면 Rev. Rul. 2008-5에 따라 {permanently} 부인되며, 단순히 이연되는 것이 아닙니다.",
  },
  "strategy.thesisCard.permanentlyWord": { en: "permanently", ko: "영구적으로" },
  "strategy.thesisCard.taxUpperBoundNote": {
    en: "No tax rate set — after-tax is an {upperBound}, using top brackets ({shortTerm} short-term, {longTerm} long-term).",
    ko: "개인 세율 미설정 — 세후 수치는 실제 비용이 아닌 {upperBound}이며, 최고 세율({shortTerm} 단기, {longTerm} 장기)을 사용합니다.",
  },
  "strategy.thesisCard.upperBoundWord": { en: "upper bound", ko: "상한값" },
  "strategy.thesisCard.taxConfiguredNote": {
    en: "Computed from your configured rates ({shortTerm} short-term, {longTerm} long-term).",
    ko: "설정하신 세율({shortTerm} 단기, {longTerm} 장기)로 계산되었습니다.",
  },
  "strategy.thesisCard.tax.grossReturn": { en: "Gross return", ko: "세전 수익률" },
  "strategy.thesisCard.tax.afterTaxReturnUpperBound": {
    en: "After-tax return (upper bound)",
    ko: "세후 수익률 (상한값)",
  },
  "strategy.thesisCard.tax.afterTaxReturn": { en: "After-tax return", ko: "세후 수익률" },
  "strategy.thesisCard.tax.statutoryRateNote": {
    en: "statutory rate, not your own",
    ko: "법정 세율이며 실제 개인 세율이 아님",
  },
  "strategy.thesisCard.tax.shortTermGains": { en: "Short-term gains", ko: "단기 이익" },
  "strategy.thesisCard.tax.longTermGains": { en: "Long-term gains", ko: "장기 이익" },
  "strategy.thesisCard.tax.washSalesTriggered": { en: "Wash sales triggered", ko: "발생한 워시 세일" },
  "strategy.thesisCard.tax.disallowedLoss": {
    en: "Disallowed loss (of equity)",
    ko: "부인된 손실 (자산 대비)",
  },
  "strategy.thesisCard.tax.iraExposure": { en: "IRA exposure", ko: "IRA 노출" },
  "strategy.thesisCard.tax.notChecked": { en: "not checked", ko: "확인되지 않음" },
  "strategy.thesisCard.tax.yes": { en: "yes", ko: "예" },
  "strategy.thesisCard.tax.no": { en: "no", ko: "아니요" },
  "strategy.thesisCard.hourlyHeading": { en: "Hourly exit refinement", ko: "시간 단위 청산 정밀화" },
  "strategy.thesisCard.hourlyNote": {
    en: "Shown because it cleared hourly data's minimum independent-event floor. The daily result above is still the headline.",
    ko: "시간 단위 데이터의 최소 독립 사건 기준을 통과했기 때문에 표시됩니다. 위의 일 단위 결과가 여전히 대표 수치입니다.",
  },
  "strategy.thesisCard.hourlyLabel": { en: "Hourly", ko: "시간 단위" },
  "strategy.thesisCard.unleveredNote": {
    en: "{symbol} resets daily, compounding returns rather than tracking the multiple long-term. Below: same thesis, unlevered.",
    ko: "{symbol}은(는) 매일 리셋되어 배수가 아닌 일별 수익률을 복리로 쌓습니다. 아래는 동일한 논거를 무레버리지로 실행한 카드입니다.",
  },

  // --- TrialLedger.tsx -------------------------------------------------------------------------
  "strategy.trialLedger.title": { en: "Trial ledger — {symbol}", ko: "시행 원장 — {symbol}" },
  "strategy.trialLedger.subtitle": {
    en: "All theses for {symbol}, oldest first, incl. abandoned — corrected here as one family.",
    ko: "{symbol}의 모든 논거(중단 포함, 오래된 순) — 이 페이지 모든 q값의 보정 기준이 된 전체 집합입니다.",
  },
  "strategy.trialLedger.loading": { en: "Loading the ledger for {symbol}…", ko: "{symbol}의 원장 불러오는 중…" },
  "strategy.trialLedger.empty": {
    en: "No thesis has ever been registered for {symbol}. The ledger starts empty; the first run here is trial #1.",
    ko: "{symbol}에 등록된 논거가 아직 없습니다. 원장은 비어 있는 상태로 시작하며, 여기서의 첫 실행이 시행 #1이 됩니다.",
  },
  "strategy.trialLedger.header.registered": { en: "Registered", ko: "등록일" },
  "strategy.trialLedger.header.hypothesis": { en: "Hypothesis", ko: "가설" },
  "strategy.trialLedger.header.status": { en: "Status", ko: "상태" },
  "strategy.trialLedger.header.verdict": { en: "Verdict", ko: "판정" },
  "strategy.trialLedger.header.inSampleQ": { en: "In-sample q", ko: "인샘플 q" },
  "strategy.trialLedger.header.holdoutQ": { en: "Holdout q", ko: "홀드아웃 q" },
  "strategy.trialLedger.noStats": { en: "No ledger stats available.", ko: "원장 통계를 사용할 수 없습니다." },
  "strategy.trialLedger.stat.totalTrials": { en: "Total trials", ko: "총 시행" },
  "strategy.trialLedger.stat.survived": { en: "Survived", ko: "채택" },
  "strategy.trialLedger.stat.rejected": { en: "Rejected", ko: "기각" },
  "strategy.trialLedger.stat.inconclusive": { en: "Inconclusive", ko: "판단 불가" },
  "strategy.trialLedger.stat.abandoned": { en: "Abandoned", ko: "중단" },
  "strategy.trialLedger.stat.firstLastRegistered": {
    en: "First / last registered",
    ko: "최초 / 최근 등록",
  },
  "strategy.trialLedger.pendingVerdict": { en: "pending", ko: "대기 중" },
  "strategy.trialLedger.ofTrials": { en: "of {count} trials", ko: "전체 {count}건 중" },

  // --- TimeframeGrid.tsx -----------------------------------------------------------------------
  "strategy.timeframeGrid.loading": { en: "Loading {interval}…", ko: "{interval} 불러오는 중…" },
  "strategy.timeframeGrid.noBars": {
    en: "No {interval} bars stored yet.",
    ko: "저장된 {interval} 봉이 아직 없습니다.",
  },
  "strategy.timeframeGrid.overlaysNotDefined_one": {
    en: "{count} overlay not defined on {interval} bars",
    ko: "{interval} 봉에 정의되지 않은 오버레이 {count}개",
  },
  "strategy.timeframeGrid.overlaysNotDefined_other": {
    en: "{count} overlays not defined on {interval} bars",
    ko: "{interval} 봉에 정의되지 않은 오버레이 {count}개",
  },

  // --- Timeframes.tsx --------------------------------------------------------------------------
  "strategy.timeframes.pageTitle": { en: "Timeframes", ko: "타임프레임" },
  "strategy.timeframes.subtitle": {
    en: "Edge across intervals, as lift over baseline — never raw hit rate, never a rejected cell.",
    ko: "간격별 엣지를 리프트(기준선 대비)로만 표시하며, 표본 기준 미달 셀은 비웁니다.",
  },
  "strategy.timeframes.scopeAriaLabel": { en: "Scope", ko: "범위" },
  "strategy.timeframes.scope.sector": { en: "Sector", ko: "섹터" },
  "strategy.timeframes.scope.universe": { en: "Universe", ko: "유니버스" },
  "strategy.timeframes.horizonAriaLabel": { en: "Horizon", ko: "기간" },
  "strategy.timeframes.loadingMatrix": { en: "Loading the accuracy matrix…", ko: "정확도 매트릭스 불러오는 중…" },
  "strategy.timeframes.matrixLoadError": {
    en: "Could not load the accuracy matrix.",
    ko: "정확도 매트릭스를 불러올 수 없습니다.",
  },
  "strategy.timeframes.emptyScope": {
    en: "No cells computed yet for this scope.",
    ko: "이 범위에 대해 계산된 셀이 아직 없습니다.",
  },
  "strategy.timeframes.coverageHeadline": {
    en: "{sufficient} / {total} cells measurable",
    ko: "{sufficient} / {total}개 셀 측정 가능",
  },
  "strategy.timeframes.coveragePct": { en: " ({pct}% of the grid)", ko: " (전체의 {pct}%)" },
  "strategy.timeframes.generatedLabel": { en: "Generated {date}", ko: "{date} 생성" },
  "strategy.timeframes.tableAriaLabel": {
    en: "Rule by interval accuracy matrix",
    ko: "규칙 x 간격 정확도 매트릭스",
  },
  "strategy.timeframes.matrixScrollLabel": {
    en: "Accuracy matrix",
    ko: "정확도 매트릭스",
  },
  "strategy.timeframes.statsScrollLabel": {
    en: "Cell statistics",
    ko: "셀 통계",
  },
  "strategy.timeframes.blankCellsSummary": {
    en: "\"insufficient\" never means zero -- and 4h (†) always has a thinner sample than other columns.",
    ko: "'표본 부족'은 0%를 뜻하지 않습니다 -- 4시간봉(†)은 다른 열보다 항상 표본이 적습니다.",
  },
  "strategy.timeframes.blankCells.detail": {
    en: "A cell shows \"insufficient\" instead of 0% until its independent-window count clears the minimum — a 0% would read as a real result. The 4h column alternates 4h/2.5h (~73 windows/symbol vs daily's ~250), so every 4h cell keeps the marker.",
    ko: "셀은 독립 구간 수가 최소 기준을 넘어야 수치를 표시하며, 그 전에는 0% 대신 '표본 부족'을 표시합니다 — 0%는 실제 결과처럼 보이기 때문입니다. 4시간봉은 4시간/2.5시간이 번갈아 나타나 종목당 독립 구간이 약 73개(일봉 약 250개)뿐이라 모든 4시간봉 셀에 이 표시가 붙습니다.",
  },
  "strategy.timeframes.lowConfidenceTitle": {
    en: "4h bars alternate 4h/2.5h -- only ~73 independent windows per symbol against daily's ~250",
    ko: "4시간봉은 4시간/2.5시간이 번갈아 나타납니다 -- 종목당 독립 구간이 약 73개로, 일봉의 약 250개에 비해 적습니다",
  },
  "strategy.timeframes.lowConfidenceAriaLabel": { en: "low confidence", ko: "낮은 신뢰도" },
  "strategy.timeframes.notApplicable": { en: "n/a", ko: "n/a" },
  "strategy.timeframes.insufficientTitle": {
    en: "Insufficient independent sample ({count} of the required 20)",
    ko: "독립 표본 부족 (필요한 20개 중 {count}개)",
  },
  "strategy.timeframes.insufficientLabel": { en: "insufficient", ko: "표본 부족" },
  "strategy.timeframes.indepCount": { en: "{count} indep", ko: "독립 {count}" },
  "strategy.timeframes.hitVsBase": { en: "{hit} vs {base} base", ko: "{hit} 대 기준 {base}" },
  "strategy.timeframes.drilldownAriaLabel": {
    en: "Drill-down: {ruleId} at {interval}",
    ko: "상세 보기: {ruleId}, {interval}",
  },
  "strategy.timeframes.closeButton": { en: "close ×", ko: "닫기 ×" },
  "strategy.timeframes.openOnTicker": {
    en: "Open {symbol} on the ticker page →",
    ko: "{symbol} 티커 페이지 열기 →",
  },
  "strategy.timeframes.loadingSignalTrace": { en: "Loading signal trace…", ko: "신호 추적 불러오는 중…" },
  "strategy.timeframes.drilldownUnavailable": {
    en: "The chart drill-down needs a single symbol. Switch to Symbol scope to see candles and fire markers for {scopeKey}.",
    ko: "차트 상세 보기에는 단일 종목이 필요합니다. {scopeKey}의 캔들과 발동 표시를 보려면 종목 범위로 전환하세요.",
  },
  "strategy.timeframes.signalLoadError": {
    en: "Could not load the signal trace.",
    ko: "신호 추적을 불러올 수 없습니다.",
  },
  "strategy.timeframes.noCellStats": {
    en: "No statistics computed for this cell.",
    ko: "이 셀에 대해 계산된 통계가 없습니다.",
  },
  "strategy.timeframes.stat.lift": { en: "Lift", ko: "리프트" },
  "strategy.timeframes.stat.hitRate": { en: "Hit rate", ko: "적중률" },
  "strategy.timeframes.stat.baseRate": { en: "Base rate", ko: "기준 비율" },
  "strategy.timeframes.stat.liftCi": { en: "Lift CI", ko: "리프트 신뢰구간" },
  "strategy.timeframes.liftCiRange": { en: "{low} to {high}", ko: "{low} ~ {high}" },
  "strategy.timeframes.stat.medianReturn": { en: "Median return", ko: "중앙값 수익률" },
  "strategy.timeframes.stat.baselineMedian": { en: "Baseline median", ko: "기준선 중앙값" },
  "strategy.timeframes.stat.pValue": { en: "p-value", ko: "p값" },
  "strategy.timeframes.stat.qValue": { en: "q-value", ko: "q값" },
  "strategy.timeframes.stat.costAdjustedEdge": { en: "Cost-adjusted edge", ko: "비용 반영 엣지" },
  "strategy.timeframes.stat.costAssumed": { en: "Cost assumed", ko: "가정한 비용" },
  "strategy.timeframes.stat.sample": { en: "Sample", ko: "표본" },
  "strategy.timeframes.sampleBreakdown": {
    en: "{raw} raw / {episodes} episodes / {indep} indep",
    ko: "원표본 {raw} / 사건 {episodes} / 독립 {indep}",
  },
  "strategy.timeframes.stat.sufficient": { en: "Sufficient", ko: "표본 충분" },
  "strategy.timeframes.yes": { en: "yes", ko: "예" },
  "strategy.timeframes.no": { en: "no", ko: "아니요" },
  "strategy.timeframes.stat.regime": { en: "Regime", ko: "국면" },
  "strategy.timeframes.stat.span": { en: "Span", ko: "기간" },
  "strategy.timeframes.spanRange": { en: "{first} → {last}", ko: "{first} → {last}" },
  "strategy.timeframes.stat.warnings": { en: "Warnings", ko: "경고" },
} as const satisfies MessageShard;
