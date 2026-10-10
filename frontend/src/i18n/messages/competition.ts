/**
 * The Competition page core: `Competition.tsx` itself, `SummarySection`, `LeaderboardSection`,
 * `GenerationsPanel`, `LoopPanel`, `RoundNarrativeCard`, and the two API helpers they read
 * (`api/competition.ts`, `api/evolution.ts`).
 *
 * Keys are prefixed `competition.` -- see `catalog.ts` for the convention.
 *
 * **Model-written prose stays English, on purpose.** A round's narrative body (`RoundNarrative
 * .outcome`/`.headline`/`.focus`), a genome's review (`GenerationReview.post_mortem`/`direction
 * .headline`/hypotheses/amendment `.reason`), a finding's `.summary`, and a promotion's `.reason` are
 * all written by a model or lifted verbatim off disk -- this shard translates the chrome around them
 * (headings, labels, empty states) and never the prose itself. See the hard rule this task was given.
 *
 * **`PURPOSE_LABELS`/`RANK_BY_OPTIONS`/`FINDING_KIND_LABELS` in `api/competition.ts` and
 * `api/evolution.ts` are left untouched.** They are plain objects/arrays computed once at module load
 * and indexed directly (`PURPOSE_LABELS[p]`, `Object.keys(PURPOSE_LABELS)`, `RANK_BY_OPTIONS.map(...)`)
 * by several components outside this shard's scope fence (`CandidateDossier.tsx`,
 * `PendingSeatsPanel.tsx`, `LibrarySection.tsx`, `candidateName.ts`, `goalDirectives.ts`) -- changing
 * their shape to a translated accessor would break those files' compilation. Instead this file adds
 * new, additive functions (`purposeLabel`, `rankByLabel`, `provenanceConstrainedNote`) that read the
 * catalog fresh on every call, and the five components in this shard's scope call those instead of
 * indexing the static record. The existing display-label *functions* (`jobStatusLabel`,
 * `jobRunResultStatusLabel`, `seatedByLabel`, `findingKindLabel`, `loopStateLabel`, `loopPhaseLabel`)
 * keep their exact signatures -- only their return values move onto the catalog -- since a function
 * call already re-evaluates on every render, unlike a static object literal.
 */
import type { MessageShard } from "@/i18n/types";

export const competition = {
  // =========================================================================================
  // Competition.tsx -- page head, tab rail, error fallbacks
  // =========================================================================================
  "competition.page.title": { en: "Competition", ko: "컴페티션" },
  "competition.page.subtitle": {
    en: "The strategy library, rounds scored vs SPY, each agent’s trades, what’s left open next.",
    ko: "전략 라이브러리, SPY 대비 채점된 라운드, 각 에이전트의 거래 내역, 다음에 남은 과제입니다.",
  },
  "competition.page.runCta": { en: "Plan the next round", ko: "다음 라운드 계획" },
  "competition.page.runCtaHint": {
    en: "Opens the next round's briefing: what it asks, what the last round left for it, and whether it is cleared to run.",
    ko: "다음 라운드의 브리핑을 엽니다: 무엇을 묻는지, 지난 라운드가 무엇을 남겼는지, 실행 승인 여부입니다.",
  },
  "competition.page.tabsAriaLabel": { en: "Competition view", ko: "컴페티션 보기" },
  "competition.page.loopLiveTitle": { en: "The loop is running", ko: "루프가 실행 중입니다" },
  "competition.page.loopLiveLabel": { en: "(live)", ko: "(실시간)" },

  "competition.errors.rounds": { en: "Could not load rounds.", ko: "라운드를 불러오지 못했습니다." },
  "competition.errors.library": {
    en: "Could not load the strategy library.",
    ko: "전략 라이브러리를 불러오지 못했습니다.",
  },
  "competition.errors.windows": {
    en: "Could not load the window catalogue.",
    ko: "윈도우 카탈로그를 불러오지 못했습니다.",
  },
  "competition.errors.leaderboard": {
    en: "Could not load the leaderboard.",
    ko: "리더보드를 불러오지 못했습니다.",
  },
  "competition.errors.agentDetail": {
    en: "Could not load this agent's detail.",
    ko: "이 에이전트의 상세 정보를 불러오지 못했습니다.",
  },
  "competition.errors.narrative": {
    en: "Could not load this round's narrative.",
    ko: "이 라운드의 내러티브를 불러오지 못했습니다.",
  },
  "competition.errors.nextRound": {
    en: "Could not load the next round's briefing.",
    ko: "다음 라운드의 브리핑을 불러오지 못했습니다.",
  },
  "competition.errors.selection": {
    en: "Could not load the selection for this round.",
    ko: "이 라운드의 선정 결과를 불러오지 못했습니다.",
  },
  "competition.errors.findings": {
    en: "Could not load this round's findings.",
    ko: "이 라운드의 조사 결과를 불러오지 못했습니다.",
  },
  "competition.errors.startRound": { en: "Could not start the round.", ko: "라운드를 시작하지 못했습니다." },
  "competition.errors.cancelJob": { en: "Could not cancel the run.", ko: "실행을 취소하지 못했습니다." },
  "competition.errors.loop": {
    en: "Could not load the evolution loop.",
    ko: "진화 루프를 불러오지 못했습니다.",
  },
  "competition.errors.stopLoop": { en: "Could not stop the loop.", ko: "루프를 정지하지 못했습니다." },

  "competition.tabs.summary": { en: "Rounds", ko: "라운드" },
  "competition.tabs.agent": { en: "Card", ko: "카드" },
  "competition.tabs.findings": { en: "Findings", ko: "조사 결과" },
  "competition.tabs.selection": { en: "Selection", ko: "선정" },
  "competition.tabs.library": { en: "Next round", ko: "다음 라운드" },
  "competition.tabs.loop": { en: "Loop", ko: "루프" },
  "competition.tabs.review": { en: "Review", ko: "검토" },

  // =========================================================================================
  // Shared vocabulary -- used by more than one component in this shard.
  // =========================================================================================
  "competition.loop.start": { en: "Start the loop", ko: "루프 시작" },
  "competition.loop.stop": { en: "Stop the loop", ko: "루프 정지" },
  "competition.loop.stopping": { en: "Stopping…", ko: "정지 중…" },
  // The pill beside the header toggle when `GET /loop` failed for a reason that is *not* its
  // ordinary never-started 404 (which reads "Idle"). A page that cannot reach the loop says so
  // rather than showing a confident state it has no evidence for.
  "competition.loop.stateUnknown": { en: "Unknown", ko: "알 수 없음" },
  "competition.loop.toggleHint": {
    en: "Starts or stops the endless competition loop: propose, run, score, promote, cool down, repeat, until you stop it.",
    ko: "끝없는 컴페티션 루프를 시작하거나 정지합니다: 제안, 실행, 채점, 승격, 쿨다운을 정지할 때까지 반복합니다.",
  },
  // The review queue's own skeleton noun. It lives in this shard rather than beside the panel's
  // other `competitionRounds.*` keys because that shard is outside this change's scope fence; the
  // key is prefixed for the shard it is actually in, which is what `i18n.test.tsx` checks.
  "competition.pendingSeats.skeletonWhat": { en: "the review queue", ko: "검토 대기열" },
  "competition.purposeFieldLabel": { en: "Purpose", ko: "용도" },
  "competition.ineligibleBadge": { en: "not eligible", ko: "자격 미달" },
  "competition.provenanceConstrained.chip": { en: "not comparable", ko: "비교 불가" },
  "competition.summary.noiseChip": { en: "noise", ko: "노이즈" },
  "competition.loop.holdoutNeverUsedNote": {
    en: "(never used for selection)",
    ko: "(선정에 사용되지 않음)",
  },

  // =========================================================================================
  // api/competition.ts -- purpose/rank-by/provenance/status labels
  // =========================================================================================
  "competition.purpose.savings": { en: "Savings", ko: "저축" },
  "competition.purpose.trading": { en: "Trading", ko: "트레이딩" },
  "competition.purpose.rothIra": { en: "Roth IRA", ko: "로스 IRA" },

  "competition.rankBy.median": { en: "Median excess", ko: "중앙값 초과수익" },
  "competition.rankBy.worst": { en: "Worst-window excess", ko: "최악 윈도우 초과수익" },
  "competition.rankBy.hitRate": { en: "Hit rate", ko: "적중률" },
  "competition.rankBy.excessPerExposure": { en: "Excess per exposure", ko: "노출 대비 초과수익" },

  "competition.provenanceConstrained.note": {
    en: "Not comparable — this window’s universe was only known from a later 13F filing, so it can’t rank against others.",
    ko: "비교 불가 — 이 윈도우의 유니버스는 이후 13F 신고로만 알 수 있어, 다른 윈도우와 순위를 매길 수 없습니다.",
  },

  "competition.jobRunResult.ok": { en: "OK", ko: "정상" },

  "competition.seatedBy.rule": { en: "Seated by rule", ko: "규칙에 의해 배정" },
  "competition.seatedBy.outsideCompetition": { en: "Outside competition", ko: "컴페티션 외 배정" },
  "competition.seatedBy.ownerOverride": { en: "Owner override", ko: "소유자 재량 배정" },

  "competition.findingKind.finding": { en: "Finding", ko: "발견" },
  "competition.findingKind.followUp": { en: "Follow-up", ko: "후속 과제" },
  "competition.findingKind.defect": { en: "Defect", ko: "결함" },
  "competition.findingKind.decision": { en: "Decision", ko: "결정" },

  // =========================================================================================
  // api/evolution.ts -- finding kind, loop state/phase, field-stat, start-loop error labels
  // =========================================================================================
  "competition.evoFindingKind.winner": { en: "Winner", ko: "승자" },
  "competition.evoFindingKind.failure": { en: "Failure", ko: "실패" },
  "competition.evoFindingKind.regime": { en: "Regime", ko: "국면" },
  "competition.evoFindingKind.universe": { en: "Universe", ko: "유니버스" },
  "competition.evoFindingKind.parameter": { en: "Parameter", ko: "파라미터" },
  "competition.evoFindingKind.gate": { en: "Gate", ko: "게이트" },
  "competition.evoFindingKind.holdout": { en: "Holdout", ko: "홀드아웃" },

  "competition.loopPhase.proposing": { en: "Proposing", ko: "제안 중" },
  "competition.loopPhase.scoring": { en: "Scoring", ko: "채점 중" },
  "competition.loopPhase.promoting": { en: "Promoting", ko: "승격 중" },
  "competition.loopPhase.cooldown": { en: "Cooldown", ko: "쿨다운" },

  "competition.field.none": { en: "no field", ko: "필드 없음" },

  "competition.loop.errors.startFallback": {
    en: "Could not start the loop.",
    ko: "루프를 시작하지 못했습니다.",
  },
  "competition.loop.errors.configRejected": {
    en: "The loop configuration was rejected. Check the must include/must avoid tickers and try again.",
    ko: "루프 설정이 거부되었습니다. 필수 포함/제외 티커를 확인한 뒤 다시 시도하세요.",
  },

  // =========================================================================================
  // RoundNarrativeCard.tsx -- chrome only; narrative prose stays English (see module docstring)
  // =========================================================================================
  "competition.narrative.loading": { en: "Loading round narrative…", ko: "라운드 내러티브 불러오는 중…" },
  "competition.narrative.emptyNotFound": {
    en: "This round has no authored narrative yet.",
    ko: "이 라운드에는 아직 작성된 내러티브가 없습니다.",
  },
  "competition.narrative.askedLabel": { en: "What this round asked", ko: "이 라운드가 물은 것" },
  "competition.narrative.happenedLabel": { en: "What happened", ko: "일어난 일" },
  "competition.narrative.ownerOverride": { en: "Owner override", ko: "소유자 재량 결정" },
  "competition.narrative.seatedLabel": { en: "Seated", ko: "좌석 배정" },
  "competition.narrative.seatedEmpty": {
    en: "This round seated nothing.",
    ko: "이 라운드는 아무것도 좌석 배정하지 않았습니다.",
  },
  "competition.narrative.carriesForwardLabel": {
    en: "What the next round applies",
    ko: "다음 라운드가 적용할 것",
  },

  // =========================================================================================
  // SummarySection.tsx
  // =========================================================================================
  // No repo filename in reader-facing copy: "PROTOCOL.md §7" named a file only a developer can
  // open, in the place where the sentence should have been saying what the number means.
  "competition.summary.noiseFloor.caution": {
    en: "Inside the {pp}pp reordering-noise floor — not evidence of anything.",
    ko: "{pp}pp 재정렬 노이즈 한계 이내 — 아무것도 입증하지 않습니다.",
  },
  "competition.summary.noiseFloor.title": {
    en: "Reordering noise: 12 shuffles of one card spread results 53.9pp (σ 21.2). Smaller gaps may just be array order.",
    ko: "재정렬 노이즈: 카드 순서만 12가지로 바꿔도 결과가 53.9포인트(표준편차 21.2) 흔들렸습니다. 그보다 작은 차이는 배열 순서일 수 있습니다.",
  },
  "competition.summary.noResultsTitle": {
    en: "This round has no scored results.",
    ko: "이 라운드는 채점된 결과가 없습니다.",
  },
  "competition.summary.noResultsChip": { en: "no results", ko: "결과 없음" },
  "competition.summary.roundsError": { en: "Could not load rounds.", ko: "라운드를 불러오지 못했습니다." },
  "competition.summary.noRoundsHint": {
    en: "Nothing to summarise without a round -- head to Next round to launch one.",
    ko: "라운드가 없으면 요약할 것이 없습니다 -- 다음 라운드에서 하나를 시작하세요.",
  },
  "competition.summary.scoredRoundsAria": { en: "Scored rounds", ko: "채점된 라운드" },
  "competition.summary.scoredLabel": { en: "Scored", ko: "채점됨" },
  "competition.summary.recordOnlyAria": {
    en: "Record-only rounds -- a written note, no run files",
    ko: "기록 전용 라운드 -- 작성된 메모만 있고 실행 파일 없음",
  },
  "competition.summary.recordOnlyLabel": { en: "Record only", ko: "기록만 있음" },
  // Beside the round picker, about the round actually selected. This used to be a suffix inside the
  // `<option>` text itself, where it made one option twice the length of its neighbours.
  "competition.summary.noScoredResultsPill": { en: "No scored results", ko: "채점 결과 없음" },
  "competition.summary.thisRoundHeading": { en: "This round", ko: "이 라운드" },
  "competition.summary.pickRoundHint": {
    en: "Pick a round above to see what it asked.",
    ko: "위에서 라운드를 선택하면 무엇을 물었는지 볼 수 있습니다.",
  },
  "competition.summary.recordOnlyExplain": {
    en: "{label} has no scored results — a written record, not a scored round: only a {selectionMd}/{runTxt} note, no run files.",
    ko: "{label}에는 채점된 결과가 없습니다 — 채점된 라운드가 아닌 작성된 기록입니다: {selectionMd}/{runTxt} 메모만 있고 실행 파일은 없습니다.",
  },
  "competition.summary.questionLabel": { en: "This round’s question", ko: "이 라운드의 질문" },
  "competition.summary.windowsRunLabel": { en: "Windows run", ko: "실행된 윈도우" },
  "competition.summary.noWindowsRecorded": {
    en: "No windows recorded for this round.",
    ko: "이 라운드에 기록된 윈도우가 없습니다.",
  },
  "competition.summary.programmeScaleHeading": { en: "Programme scale", ko: "프로그램 규모" },
  "competition.summary.programmeScaleSubtitle": {
    en: 'Every round directory the backend knows, including record-only ones -- why "Rounds run" and "Produced results" differ.',
    ko: '현재 선택된 라운드뿐 아니라 백엔드가 아는 모든 라운드 디렉터리(기록 전용 포함)입니다 -- "실행된 라운드"와 "결과 산출" 수가 다른 이유입니다.',
  },
  "competition.summary.noRoundsRunYet": {
    en: "No rounds have been run yet.",
    ko: "아직 실행된 라운드가 없습니다.",
  },
  "competition.summary.tile.roundsRun": { en: "Rounds run", ko: "실행된 라운드" },
  "competition.summary.tile.producedResults": { en: "Produced results", ko: "결과 산출" },
  "competition.summary.tile.producedResultsHint": {
    en: "of {total} rounds -- the rest are written records only",
    ko: "전체 {total}개 라운드 중 -- 나머지는 기록만 있음",
  },
  "competition.summary.tile.agentsScored": { en: "Agents scored (peak roster)", ko: "채점된 에이전트 (최대 로스터)" },
  "competition.summary.tile.agentsScoredHint": {
    en: "largest single scored round -- not a cross-round dedupe",
    ko: "채점된 라운드 중 가장 큰 값 -- 라운드 간 중복 제거는 아님",
  },
  "competition.summary.tile.windowsCovered": { en: "Windows covered", ko: "다룬 윈도우" },
  "competition.summary.tile.windowsCoveredHint": {
    en: "distinct window keys across scored rounds",
    ko: "채점된 라운드 전체의 고유 윈도우 키",
  },
  "competition.summary.tile.newestWithResults": { en: "Newest round with results", ko: "결과가 있는 최신 라운드" },
  "competition.summary.tile.newestNone": {
    en: "no round has produced results yet",
    ko: "아직 결과를 산출한 라운드가 없습니다",
  },
  "competition.summary.roundNumbersHeading": { en: "This round’s numbers", ko: "이 라운드의 수치" },
  // The noun `Skeleton` announces ("Loading {what}…"), not a whole sentence -- these panels draw a
  // placeholder in the shape of the table or tile grid that is coming rather than collapsing to a
  // one-line "Loading…" and snapping open when the data lands. See `components/Skeleton.tsx`.
  "competition.summary.skeletonWhat.roundNumbers": { en: "round numbers", ko: "라운드 수치" },
  "competition.summary.skeletonWhat.windowDetail": { en: "window detail", ko: "윈도우 상세" },
  "competition.summary.skeletonWhat.rounds": { en: "rounds", ko: "라운드" },
  "competition.summary.roundResultsError": {
    en: "Could not load this round's results.",
    ko: "이 라운드의 결과를 불러오지 못했습니다.",
  },
  "competition.summary.tile.windows": { en: "Windows", ko: "윈도우" },
  "competition.summary.tile.windowsHint": {
    en: "windows this round actually ran",
    ko: "이 라운드가 실제로 실행한 윈도우",
  },
  "competition.summary.tile.agents": { en: "Agents", ko: "에이전트" },
  "competition.summary.tile.agentsHint": { en: "cards entered in this round", ko: "이 라운드에 참가한 카드" },
  "competition.summary.tile.clearedGate": { en: "Cleared eligibility gate", ko: "자격 게이트 통과" },
  "competition.summary.tile.clearedGateHint": {
    en: 'eligible to be ranked (3+ eligible windows), not "cards that qualified" on merit',
    ko: '순위 산정 자격 (윈도우 3개 이상 충족) -- 실력으로 "합격한 카드"를 뜻하지는 않음',
  },
  "competition.summary.tile.bestPerformer": { en: "Best performer", ko: "최고 성과" },
  "competition.summary.tile.bestPerformerHint": {
    en: "median excess vs SPY at that card’s median window, this round’s windows only -- not compared to other rounds.",
    ko: "이 라운드의 윈도우만을 대상으로, 해당 카드의 중앙값 윈도우에서 SPY 대비 중앙값 초과수익 -- 다른 라운드와 비교하지 않습니다.",
  },
  "competition.summary.tile.medianPerformer": { en: "Median performer", ko: "중앙값 성과" },
  "competition.summary.tile.medianPerformerHint": {
    en: "the middle-ranked card’s median excess vs SPY, this round’s windows -- half did better, half worse, by this measure.",
    ko: "순위 중간 카드의 이 라운드 윈도우 기준 SPY 대비 중앙값 초과수익 -- 같은 기준으로 절반은 더 잘했고 절반은 더 못했습니다.",
  },
  "competition.summary.tile.spyMedianReturn": { en: "SPY median return", ko: "SPY 중앙값 수익률" },
  "competition.summary.tile.spyMedianReturnHint": {
    en: "the market’s median return across this round’s windows -- not a card result, what every excess is measured against.",
    ko: "이 라운드의 비교 가능한 윈도우 전체에 대한 시장의 중앙값 수익률 -- 카드 결과가 아니라 위 모든 카드 초과수익의 비교 기준입니다.",
  },
  "competition.summary.windowDetailHeading": { en: "Window detail", ko: "윈도우 상세" },
  "competition.summary.windowDetailError": {
    en: "Could not load window detail.",
    ko: "윈도우 상세를 불러오지 못했습니다.",
  },
  "competition.summary.windowDetailForRound": { en: "Window detail — {roundId}", ko: "윈도우 상세 — {roundId}" },
  "competition.summary.windowTableNote": {
    en: '“Best card excess”: top card return minus SPY’s, same window. Under {pp}pp sits in the noise floor, marked {noiseChip}.',
    ko: '"최고 카드 초과수익"은 같은 윈도우 SPY 수익률을 뺀 최고 카드 수익률입니다. {pp}pp 미만 격차는 노이즈 한계 이내이며 {noiseChip}로 표시됩니다.',
  },
  "competition.summary.col.window": { en: "Window", ko: "윈도우" },
  "competition.summary.col.spyReturn": { en: "SPY return", ko: "SPY 수익률" },
  "competition.summary.col.bestCardExcess": { en: "Best card excess", ko: "최고 카드 초과수익" },
  "competition.summary.col.cardsRun": { en: "Cards run", ko: "실행된 카드" },

  // =========================================================================================
  // LeaderboardSection.tsx
  // =========================================================================================
  "competition.leaderboard.roundFieldLabel": { en: "Round", ko: "라운드" },
  "competition.leaderboard.thisRoundFallback": { en: "This round", ko: "이 라운드" },
  // The accessible name of the rank-cell button that opens one card's drill-down. Carries the rank
  // as well as the name, because the button's visible text *is* the rank and an `aria-label` would
  // otherwise replace it -- a screen-reader user must not lose the number a sighted one reads.
  "competition.leaderboard.rowToggleAria": {
    en: "Rank {rank}: open {name}",
    ko: "{rank}위: {name} 열기",
  },
  "competition.leaderboard.rankByLabel": { en: "Rank by", ko: "정렬 기준" },
  "competition.leaderboard.skeletonWhat": { en: "the leaderboard", ko: "리더보드" },
  "competition.leaderboard.noResultsBold": {
    en: "{label} has no scored results.",
    ko: "{label}에는 채점된 결과가 없습니다.",
  },
  "competition.leaderboard.noResultsCallout": {
    en: "{bold} Nothing has run yet -- no ranking to show. See Findings for a written record, or start a run from Next round.",
    ko: "{bold} 이 라운드는 아직 실행되지 않아 보여줄 순위가 없습니다. 조사 결과에 기록이 있을 수 있으며, 다음 라운드에서 실행을 시작할 수 있습니다.",
  },
  "competition.leaderboard.error": {
    en: "Could not load the leaderboard.",
    ko: "리더보드를 불러오지 못했습니다.",
  },
  "competition.leaderboard.unscoredFallback": {
    en: "No {purpose} cards were scored in this round.",
    ko: "이 라운드에서 채점된 {purpose} 카드가 없습니다.",
  },
  "competition.leaderboard.scoringBasis": {
    en: "{purpose} cards, ranked on {basis}. Figures are not comparable across purposes.",
    ko: "{purpose} 카드, {basis} 기준으로 순위가 매겨졌습니다. 수치는 용도 간 비교할 수 없습니다.",
  },
  "competition.leaderboard.heading": { en: "Leaderboard — {roundId}", ko: "리더보드 — {roundId}" },
  "competition.leaderboard.col.rank": { en: "Rank", ko: "순위" },
  "competition.leaderboard.col.agent": { en: "Card", ko: "카드" },
  "competition.leaderboard.col.discipline": { en: "Discipline", ko: "전략 유형" },
  "competition.leaderboard.col.windowsRun": { en: "Windows run", ko: "실행된 윈도우" },
  "competition.leaderboard.col.medianExcess": { en: "Median excess", ko: "중앙값 초과수익" },
  "competition.leaderboard.col.worstExcess": { en: "Worst excess", ko: "최악 초과수익" },
  "competition.leaderboard.col.hitRate": { en: "Hit rate", ko: "적중률" },
  "competition.leaderboard.col.meanExposure": { en: "Mean exposure", ko: "평균 노출" },
  "competition.leaderboard.spyBenchmark": { en: "SPY (benchmark)", ko: "SPY (벤치마크)" },
  "competition.leaderboard.noAgentsRan": { en: "No agents ran in this round.", ko: "이 라운드에 실행된 에이전트가 없습니다." },
  "competition.leaderboard.provenanceNote_one": {
    en: "{windows} is marked not comparable.",
    ko: "{windows}은(는) 비교 불가로 표시됩니다.",
  },
  "competition.leaderboard.provenanceNote_other": {
    en: "{windows} are marked not comparable.",
    ko: "{windows}은(는) 비교 불가로 표시됩니다.",
  },
  "competition.leaderboard.ranOfWindows": {
    en: "ran {run} of {total} windows",
    ko: "{total}개 중 {run}개 윈도우 실행",
  },

  // =========================================================================================
  // GenerationsPanel.tsx
  // =========================================================================================
  "competition.generations.heading": { en: "Every generation", ko: "모든 세대" },
  "competition.generations.hint": {
    en: "All generations for this purpose, scored field-wide, not just the leader. Same-error streaks collapse to one row.",
    ko: "이 용도의 모든 세대를 선두주자가 아닌 전체 필드 기준으로 보여줍니다. 동일 오류로 연속 실패한 세대는 아래 한 행으로 압축됩니다.",
  },
  "competition.generations.loading": { en: "Loading generations…", ko: "세대 불러오는 중…" },
  "competition.generations.errors.list": {
    en: "Could not load generations.",
    ko: "세대를 불러오지 못했습니다.",
  },
  "competition.generations.errors.streaks": {
    en: "Could not load failure streaks.",
    ko: "실패 연속 구간을 불러오지 못했습니다.",
  },
  "competition.generations.errors.trend": {
    en: "Could not load the trend.",
    ko: "추세를 불러오지 못했습니다.",
  },
  "competition.generations.errors.detail": {
    en: "Could not load this generation's detail.",
    ko: "이 세대의 상세 정보를 불러오지 못했습니다.",
  },
  "competition.generations.unreadable_one": {
    en: "{count} generation record could not be read.",
    ko: "{count}개의 세대 기록을 읽을 수 없었습니다.",
  },
  "competition.generations.unreadable_other": {
    en: "{count} generation records could not be read.",
    ko: "{count}개의 세대 기록을 읽을 수 없었습니다.",
  },
  "competition.generations.empty": {
    en: "No generations recorded for this purpose yet.",
    ko: "이 용도에 대해 기록된 세대가 아직 없습니다.",
  },
  "competition.generations.col.generation": { en: "Generation", ko: "세대" },
  "competition.generations.col.status": { en: "Status", ko: "상태" },
  "competition.generations.col.candidatesRankedEligible": {
    en: "Candidates / ranked / eligible",
    ko: "후보 / 순위매김 / 자격충족",
  },
  "competition.generations.col.fieldSelectionMedian": {
    en: "Field selection median",
    ko: "필드 선정 중앙값",
  },
  "competition.generations.col.fieldHitRate": { en: "Field hit rate", ko: "필드 적중률" },
  "competition.generations.col.holdoutGap": { en: "Holdout gap", ko: "홀드아웃 격차" },
  "competition.generations.col.gateClearedEligible": {
    en: "Gate cleared / eligible",
    ko: "게이트 통과 / 자격충족",
  },
  "competition.generations.col.promoted": { en: "Promoted", ko: "승격됨" },
  "competition.generations.col.review": { en: "Review", ko: "리뷰" },
  "competition.generations.newer": { en: "Newer", ko: "최신" },
  "competition.generations.older": { en: "Older", ko: "이전" },
  "competition.generations.pageRange": { en: "{from}–{to} of {total}", ko: "{total}개 중 {from}–{to}" },
  "competition.generations.pageRangeEmpty": { en: "0 of 0", ko: "0 / 0" },

  "competition.generations.streak.singleGeneration": { en: "Generation {n}", ko: "세대 {n}" },
  "competition.generations.streak.rangeGenerations": {
    en: "Generations {first}–{last}",
    ko: "세대 {first}–{last}",
  },
  "competition.generations.streak.singleFailed": { en: "{span} failed with:", ko: "{span}이(가) 다음 오류로 실패:" },
  "competition.generations.streak.multipleFailed": {
    en: "{count} consecutive generations failed with:",
    ko: "{count}개의 연속된 세대가 다음 오류로 실패:",
  },
  "competition.generations.streak.failedBadge": { en: "Failed", ko: "실패" },
  "competition.generations.streak.allPurposes": { en: "(all purposes)", ko: "(모든 용도)" },
  "competition.generations.streak.count": { en: "{count} generation(s)", ko: "{count}개 세대" },
  "competition.generations.streak.firstFailed": { en: "First failed", ko: "최초 실패" },
  "competition.generations.streak.lastFailed": { en: "Last failed", ko: "최근 실패" },

  "competition.generations.row.genLabel": { en: "Gen {n}", ko: "세대 {n}" },
  "competition.generations.row.reviewed": { en: "Reviewed", ko: "리뷰됨" },
  "competition.generations.row.noReview": { en: "No review", ko: "리뷰 없음" },

  "competition.generations.detail.loading": { en: "Loading generation {n}…", ko: "세대 {n} 불러오는 중…" },
  "competition.generations.detail.findingsByKind": { en: "Findings, by kind", ko: "종류별 조사 결과" },
  "competition.generations.detail.noFindings": {
    en: "No findings recorded for this generation.",
    ko: "이 세대에 기록된 조사 결과가 없습니다.",
  },
  "competition.generations.detail.planSummary": {
    en: "Plan (pre-registration, written before this generation ran)",
    ko: "계획 (사전 등록, 이 세대 실행 전에 작성됨)",
  },

  "competition.generations.standings.empty": {
    en: "No candidates were scored in this generation.",
    ko: "이 세대에서 채점된 후보가 없습니다.",
  },
  "competition.generations.standings.col.rank": { en: "Rank", ko: "순위" },
  "competition.generations.standings.col.name": { en: "Name", ko: "이름" },
  "competition.generations.standings.col.eligible": { en: "Eligible", ko: "자격충족" },
  "competition.generations.standings.col.windowsRun": { en: "Windows run", ko: "실행된 윈도우" },
  "competition.generations.standings.col.selectionMedian": { en: "Selection median", ko: "선정 중앙값" },
  "competition.generations.standings.col.worstWindow": { en: "Worst window", ko: "최악 윈도우" },
  "competition.generations.standings.col.hitRate": { en: "Hit rate", ko: "적중률" },
  "competition.generations.standings.col.holdoutMedian": { en: "Holdout median", ko: "홀드아웃 중앙값" },
  "competition.generations.standings.col.trades": { en: "Trades", ko: "거래" },
  "competition.generations.standings.col.qValue": { en: "Q-value", ko: "Q값" },
  "competition.generations.standings.yes": { en: "Yes", ko: "예" },
  "competition.generations.standings.no": { en: "No", ko: "아니오" },
  "competition.generations.standings.keep": { en: "keep", ko: "유지" },
  "competition.generations.standings.drop": { en: "drop", ko: "탈락" },

  "competition.verdict.promising": { en: "Promising", ko: "유망함" },
  "competition.verdict.inconclusive": { en: "Inconclusive", ko: "결론 없음" },
  "competition.verdict.exhausted": { en: "Exhausted", ko: "소진됨" },
  "competition.verdict.broken": { en: "Broken", ko: "손상됨" },

  "competition.generations.review.heading": { en: "Review", ko: "리뷰" },
  "competition.generations.review.none": {
    en: "No model has reviewed this generation.",
    ko: "이 세대를 리뷰한 모델이 없습니다.",
  },
  "competition.generations.review.direction": {
    en: "Direction for the next generation",
    ko: "다음 세대를 위한 방향",
  },
  "competition.generations.review.focus": { en: "Focus: {list}", ko: "집중: {list}" },
  "competition.generations.review.avoid": { en: "Avoid: {list}", ko: "회피: {list}" },
  "competition.generations.review.emphasise": { en: "Emphasise: {list}", ko: "강조: {list}" },
  "competition.generations.review.retire": { en: "Retire: {list}", ko: "폐기: {list}" },
  "competition.generations.review.amendmentsHeading": {
    en: "Amendments -- the loop changed its own configuration",
    ko: "수정 사항 -- 루프가 스스로 설정을 변경했습니다",
  },

  "competition.generations.trend.notEnough": { en: "Not enough generations yet.", ko: "아직 세대 수가 부족합니다." },
  "competition.generations.trend.ariaLabel": {
    en: "Trend across {count} generations, from generation {first} to {last}",
    ko: "세대 {first}부터 {last}까지, {count}개 세대에 걸친 추세",
  },
  "competition.generations.trend.heading": {
    en: "Trend for {purpose} {note}",
    ko: "{purpose} 추세 {note}",
  },
  "competition.generations.trend.headingNote": {
    en: "(one purpose at a time -- see note)",
    ko: "(한 번에 하나의 용도 -- 안내 참고)",
  },
  "competition.generations.trend.hint": {
    en: "Generations cycle purpose/shape lanes -- cross-lane lines compare un-scored pairs. Sparklines cover only this purpose.",
    ko: "세대는 용도/형태 레인을 순환합니다. 하나 이상의 레인에 걸쳐 그린 선은 서로 채점된 적 없는 세대를 비교하게 됩니다. 아래의 모든 스파크라인은 위에서 선택한 용도로 한정되며, 성공한 세대만 집계합니다.",
  },
  "competition.generations.trend.loading": { en: "Loading trend…", ko: "추세 불러오는 중…" },
  "competition.generations.trend.medianExcess": {
    en: "Field median excess (selection)",
    ko: "필드 중앙값 초과수익 (선정)",
  },
  "competition.generations.trend.holdoutGap": {
    en: "Holdout gap (field median, pp)",
    ko: "홀드아웃 격차 (필드 중앙값, pp)",
  },
  "competition.generations.trend.gateClearance": {
    en: "Gate clearance (cleared / eligible)",
    ko: "게이트 통과율 (통과 / 자격충족)",
  },

  // =========================================================================================
  // LoopPanel.tsx
  // =========================================================================================
  "competition.loop.loadingPanel": { en: "Loading the evolution loop…", ko: "진화 루프 불러오는 중…" },
  "competition.loop.heading": { en: "Evolution loop", ko: "진화 루프" },
  "competition.loop.neverStarted": {
    en: "Never started. Starting it runs generations unattended -- propose, run, score, promote winners -- until you stop it.",
    ko: "아직 시작된 적이 없습니다. 시작하면 유전체를 제안, 실행, 채점, 승격하는 세대를 정지할 때까지 무인으로 반복합니다.",
  },
  "competition.loop.form.setupHeading": { en: "Set up this run", ko: "이번 실행 설정" },
  "competition.loop.form.booksToBreedLegend": { en: "Books to breed for", ko: "육성할 책" },
  "competition.loop.form.booksHint": {
    en: "One generation breeds one book, in turn -- three books means each comes around a third as often. At least one required.",
    ko: "한 세대는 책 하나만 순서대로 육성합니다 -- 책 세 개를 고르면 각 책이 세 배 빠르게가 아니라 세 배 드물게 돌아옵니다. 최소 하나는 필수입니다.",
  },
  "competition.loop.form.populationLabel": { en: "Agents per generation", ko: "세대당 에이전트 수" },
  "competition.loop.form.maxWorkersLabel": { en: "Parallel workers", ko: "병렬 워커" },
  "competition.loop.form.sizingHint": {
    en: "More agents means a longer generation -- a full pass over every window each. Parallel workers speed it up (1 = serial).",
    ko: "에이전트가 많을수록 세대가 길어집니다 -- 모든 윈도우를 한 번씩 통과해야 하기 때문입니다. 세대를 빠르게 하는 것은 병렬 워커, 즉 동시 실행 카드 수입니다 (1 = 순차).",
  },
  "competition.loop.form.goalLabel": { en: "Goal", ko: "목표" },
  "competition.loop.form.goalPlaceholder": {
    en: "What should this run find out? e.g. does a small semiconductor tilt survive a drawdown better than a pure trend book?",
    ko: "이번 실행이 무엇을 알아내야 하나요? 예: 소형 반도체 편중이 순수 추세 책보다 하락장에서 더 잘 버티는가?",
  },
  "competition.loop.form.goalHint": {
    en: "Recorded with each generation, shown beside results -- it doesn’t steer search. Tickers below and ranking metric do.",
    ko: "각 세대와 함께 기록되어 결과 옆에 표시될 뿐, 탐색을 조종하지 않습니다. 아래 티커 필드와 정렬 기준만이 실제로 제안을 제약합니다.",
  },
  "competition.loop.form.focusLabel": { en: "Must include tickers", ko: "필수 포함 티커" },
  "competition.loop.form.focusPlaceholder": { en: "e.g. NVDA, AMD", ko: "예: NVDA, AMD" },
  "competition.loop.form.avoidLabel": { en: "Must avoid tickers", ko: "필수 제외 티커" },
  "competition.loop.form.avoidPlaceholder": { en: "e.g. TSLA", ko: "예: TSLA" },
  "competition.loop.form.tickersHint": {
    en: "Comma-separated tickers -- what actually constrains proposals: hold the include list, not the avoid list.",
    ko: "쉼표로 구분한 티커입니다. 실제로 제안을 제약하는 부분입니다: 모든 후보는 포함 목록을 보유해야 하고 제외 목록은 보유할 수 없습니다.",
  },
  "competition.loop.goalWarnings.label_one": {
    en: "This goal names a setting the goal field cannot change",
    ko: "이 목표는 목표 입력란이 바꿀 수 없는 설정 1개를 지정하고 있습니다",
  },
  "competition.loop.goalWarnings.label_other": {
    en: "This goal names {count} settings the goal field cannot change",
    ko: "이 목표는 목표 입력란이 바꿀 수 없는 설정 {count}개를 지정하고 있습니다",
  },
  "competition.loop.goalWarnings.footer": {
    en: "Starting is still fine -- the goal is recorded verbatim either way. This is a warning, not a check to clear.",
    ko: "그래도 시작해도 괜찮습니다 -- 목표는 어느 쪽이든 그대로 기록됩니다. 이는 반드시 해결해야 할 검사가 아니라 경고일 뿐입니다.",
  },
  "competition.loop.runningConfigHeading": { en: "This run was started with", ko: "이번 실행의 시작 설정" },
  "competition.loop.config.mustInclude": { en: "Must include", ko: "필수 포함" },
  "competition.loop.config.mustAvoid": { en: "Must avoid", ko: "필수 제외" },
  "competition.loop.status.generation": { en: "Generation", ko: "세대" },
  "competition.loop.status.completedGenerations": { en: "Completed generations", ko: "완료된 세대" },
  "competition.loop.status.candidatesTested": { en: "Candidates tested", ko: "테스트된 후보" },
  "competition.loop.status.currentPurpose": { en: "Current purpose", ko: "현재 용도" },
  "competition.loop.status.currentRound": { en: "Current round", ko: "현재 라운드" },
  "competition.loop.best.heading": { en: "Best standing so far", ko: "현재까지 최고 순위" },
  "competition.loop.best.empty": { en: "No candidate has been scored yet.", ko: "아직 채점된 후보가 없습니다." },
  "competition.loop.best.idAndRank": { en: "{agentId} · rank {rank}", ko: "{agentId} · 순위 {rank}" },
  "competition.loop.best.selectionMedian": { en: "Selection median excess", ko: "선정 중앙값 초과수익" },
  "competition.loop.best.holdoutMedian": { en: "Holdout median excess", ko: "홀드아웃 중앙값 초과수익" },
  "competition.loop.best.worstExcess": { en: "Worst-window excess", ko: "최악 윈도우 초과수익" },
  "competition.loop.best.hitRate": { en: "Hit rate", ko: "적중률" },
  "competition.loop.best.windowsRun": { en: "Windows run", ko: "실행된 윈도우" },
  "competition.loop.best.totalTrades": { en: "Total trades", ko: "총 거래" },
  "competition.loop.promotions.heading": { en: "Promotions", ko: "승격" },
  "competition.loop.promotions.empty": { en: "Nothing has been promoted yet.", ko: "아직 승격된 것이 없습니다." },
  "competition.loop.promotions.idAndDate": {
    en: "{genomeId} · promoted {date}",
    ko: "{genomeId} · {date}에 승격",
  },
  "competition.loop.promotions.seated": { en: "Seated on paper desk", ko: "페이퍼 데스크에 좌석 배정됨" },
  "competition.loop.promotions.notSeated": { en: "Not seated", ko: "좌석 미배정" },
  "competition.loop.promotions.median": { en: "Median {value}", ko: "중앙값 {value}" },
  "competition.loop.promotions.holdout": { en: "Holdout {value}", ko: "홀드아웃 {value}" },
  "competition.loop.findings.heading": { en: "Findings", ko: "조사 결과" },
  "competition.loop.findings.headingWithGeneration": {
    en: "Findings — generation {generation}",
    ko: "조사 결과 — 세대 {generation}",
  },
  "competition.loop.findings.statedGoalLabel": { en: "Stated goal for this run", ko: "이번 실행의 명시된 목표" },
  "competition.loop.findings.statedGoalNote": { en: "(intent, not a finding)", ko: "(의도이며 조사 결과 아님)" },
  "competition.loop.findings.empty": {
    en: "No findings recorded for the last generation.",
    ko: "마지막 세대에 기록된 조사 결과가 없습니다.",
  },
  "competition.loop.log.heading": { en: "Supervisor log", ko: "감독 로그" },
  "competition.loop.log.empty": { en: "No log output yet.", ko: "아직 로그 출력이 없습니다." },

  // --- horizon group headings (the translated counterpart to HORIZON_LABELS in api/competition.ts,
  //     consumed by LibrarySection via horizonLabel()) --------------------------------------------
  "competition.horizon.6m": { en: "6 months", ko: "6개월" },
  "competition.horizon.1y": { en: "1 year", ko: "1년" },
  "competition.horizon.3y": { en: "3 years", ko: "3년" },
  "competition.horizon.5y": { en: "5 years", ko: "5년" },
  "competition.horizon.10y": { en: "10 years", ko: "10년" },

  // --- JournalPanel.tsx (the loop's rolling per-generation digest) --------------------------------
  "competition.journal.heading": { en: "Generation journal", ko: "세대 저널" },
  "competition.journal.subtitle": {
    en: "What each generation taught, newest first — the loop's own running digest.",
    ko: "각 세대가 무엇을 배웠는지 최신순으로 — 루프가 스스로 남긴 요약입니다.",
  },
  "competition.journal.loading": { en: "Loading the journal…", ko: "저널 불러오는 중…" },
  "competition.journal.error": {
    en: "Could not load the generation journal.",
    ko: "세대 저널을 불러오지 못했습니다.",
  },
  "competition.journal.empty": {
    en: "No digests yet — the loop writes one per generation.",
    ko: "아직 요약이 없습니다 — 루프가 세대마다 하나씩 작성합니다.",
  },
  "competition.journal.showingCount": {
    en: "Showing the newest {shown} of {total}.",
    ko: "전체 {total}개 중 최신 {shown}개 표시.",
  },
  "competition.journal.generationLabel": { en: "Generation {n}", ko: "세대 {n}" },
} as const satisfies MessageShard;
