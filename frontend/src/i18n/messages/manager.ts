/**
 * The Manager tab (`pages/Manager.tsx`) -- Phase 1's deterministic "what changed" feed plus the
 * Phase C model-driven surfaces (brief runner, synthesis, data health, commissions, chat).
 *
 * `manager.notAdvice` is pinned, verbatim, by the brief that commissioned this page and is rendered
 * unconditionally -- never behind a disclosure, never gated on a fetch resolving. `manager.since.none`
 * carries the same weight: when there is no prior snapshot the page must read as "activity only", not
 * as "nothing changed" (those are different claims about different amounts of missing information).
 * A brief's own not-advice line (`Synthesis.caveat`) is server-supplied prose, not a catalog key --
 * `manager.chat.caveat` below is this shard's own equivalent for the chat panel, same "always
 * visible, never behind a disclosure" rule.
 *
 * Prefix `manager.` -- see `catalog.ts` for the convention.
 */
import type { MessageShard } from "@/i18n/types";

export const manager = {
  "manager.title": { en: "Manager", ko: "매니저" },
  "manager.subtitle": {
    en: "What changed since yesterday or last week, curated across every desk.",
    ko: "어제 또는 지난주 이후 무엇이 바뀌었는지, 모든 데스크를 아울러 정리합니다.",
  },
  // Pinned by the brief. Always visible -- see this shard's own docstring. LANG-03 shortened the
  // wording; the claim it makes is unchanged.
  "manager.notAdvice": {
    en: "Not advice. A grounded daily brief, not a recommendation.",
    ko: "조언 아님. 근거 기반 일일 브리프이며 추천이 아닙니다.",
  },

  // EXP-04: the header states spend and autonomy but never said what leaves the machine. Visible
  // one-liner in the header panel; the long form is the `InfoNote` body below it.
  "manager.egress": {
    en: "Account, tax and activity figures are sent to the model provider for this brief.",
    ko: "이 브리프를 위해 계좌·세금·활동 수치가 모델 제공자에게 전송됩니다.",
  },
  "manager.egress.detail": {
    en: "Threads, briefs and snapshots are stored on this machine; only what a brief or a question cites is sent out.",
    ko: "대화·브리프·스냅샷은 이 컴퓨터에 저장되며, 브리프나 질문이 인용하는 내용만 외부로 전송됩니다.",
  },

  "manager.config.loading": { en: "Loading desk status...", ko: "데스크 상태를 불러오는 중..." },
  "manager.config.errorFallback": {
    en: "Could not load desk status.",
    ko: "데스크 상태를 불러올 수 없습니다.",
  },

  "manager.header.agentConnected": { en: "Connected", ko: "연결됨" },
  "manager.header.agentDown": { en: "Model down", ko: "모델 중단" },
  "manager.header.lastSnapshot": { en: "Last snapshot", ko: "최근 스냅샷" },
  "manager.header.never": { en: "Never", ko: "없음" },
  "manager.header.spentToday": { en: "Spent today", ko: "오늘 지출" },
  "manager.header.spentTodayValue": { en: "{spent} / {cap}", ko: "{spent} / {cap}" },
  "manager.header.autonomy": { en: "Autonomy", ko: "자율성" },
  // The way across to Overview, which holds the standing state this page reports the delta from.
  "manager.header.overviewLink": { en: "Standing state →", ko: "현재 상태 →" },

  "manager.window.ariaLabel": { en: "Change window", ko: "기간 변경" },
  "manager.window.yesterday": { en: "Yesterday", ko: "어제" },
  "manager.window.week": { en: "Week", ko: "이번 주" },

  "manager.snapshot.button": { en: "Snapshot now", ko: "지금 스냅샷" },
  "manager.snapshot.pending": { en: "Snapshotting...", ko: "스냅샷 중..." },
  "manager.snapshot.errorFallback": {
    en: "Could not snapshot right now.",
    ko: "지금은 스냅샷을 실행할 수 없습니다.",
  },

  "manager.changes.loading": { en: "Loading changes...", ko: "변경 사항을 불러오는 중..." },
  "manager.changes.errorFallback": {
    en: "Could not load the change feed.",
    ko: "변경 피드를 불러올 수 없습니다.",
  },

  // Severity pill labels -- rendered on every area-grid row so a mixed "notable"/"fyi" list stays
  // legible without opening each item; not shown in the Attention panel, whose own heading already
  // says every row there is `"attention"`.
  "manager.severity.attention": { en: "Attention", ko: "주의" },
  "manager.severity.notable": { en: "Notable", ko: "주목" },
  "manager.severity.fyi": { en: "FYI", ko: "참고" },

  // Delta-shaped on purpose. Overview has its own "Attention" panel answering a different question
  // (what the standing portfolio looks like now); this one is only what is NEW since `since`, and
  // one shared word made two different lists read as the same one.
  "manager.attention.heading": {
    en: "Needs a look — new since {since}",
    ko: "확인 필요 — {since} 이후 새 항목",
  },
  "manager.attention.empty": {
    en: "Nothing needs attention right now.",
    ko: "지금은 주의가 필요한 항목이 없습니다.",
  },

  "manager.byArea.heading": { en: "Changes by area", ko: "영역별 변경 사항" },
  "manager.area.heading": { en: "{label} ({count})", ko: "{label} ({count})" },
  "manager.area.account": { en: "Account", ko: "계좌" },
  "manager.area.tax": { en: "Tax", ko: "세금" },
  "manager.area.paperdesk": { en: "Paper Desk", ko: "페이퍼 데스크" },
  "manager.area.personaBooks": { en: "Persona Books", ko: "페르소나 북" },
  "manager.area.personaTraders": { en: "Persona Traders", ko: "페르소나 트레이더" },
  "manager.area.research": { en: "Research", ko: "리서치" },
  "manager.area.desks": { en: "Desks", ko: "데스크" },
  "manager.area.live": { en: "Live", ko: "라이브" },
  "manager.area.personas": { en: "Personas", ko: "페르소나" },
  "manager.area.market": { en: "Market", ko: "시장" },
  "manager.area.events": { en: "Events", ko: "이벤트" },
  "manager.area.news": { en: "News", ko: "뉴스" },
  "manager.area.data": { en: "Data", ko: "데이터" },
  "manager.area.activity": { en: "Activity", ko: "거래 내역" },

  "manager.gaps.heading": { en: "Gaps", ko: "빈틈" },
  "manager.gaps.sectionsMissing": { en: "Sections missing", ko: "누락된 항목" },
  "manager.gaps.warnings": { en: "Warnings", ko: "경고" },

  // The "no prior snapshot" case. Deliberately not phrased as "nothing changed" -- that is a claim
  // about a comparison that did not happen, not about an absence of change.
  "manager.since.none": {
    en: "No prior snapshot yet -- everything below is activity only, not a change comparison.",
    ko: "아직 이전 스냅샷이 없습니다 -- 아래 내용은 비교가 아닌 활동 기록일 뿐입니다.",
  },

  "manager.empty": {
    en: "No changes for the {window} window (since {since}).",
    ko: "{window} 기간 동안 변경 사항이 없습니다 (기준: {since}).",
  },

  // --- Brief runner --------------------------------------------------------------------------

  "manager.brief.heading": { en: "Brief", ko: "브리핑" },
  "manager.brief.run": { en: "Run brief", ko: "브리핑 실행" },
  "manager.brief.running": { en: "Running...", ko: "실행 중..." },
  "manager.brief.progress": { en: "{done}/{total} stages", ko: "{done}/{total} 단계" },
  "manager.brief.loading": { en: "Loading brief...", ko: "브리핑을 불러오는 중..." },
  "manager.brief.errorFallback": { en: "Could not load the brief.", ko: "브리핑을 불러올 수 없습니다." },
  "manager.brief.startErrorFallback": {
    en: "Could not start the brief.",
    ko: "브리핑을 시작할 수 없습니다.",
  },
  "manager.brief.empty": {
    en: "No brief has run yet -- run one above.",
    ko: "아직 실행된 브리핑이 없습니다 -- 위에서 실행하세요.",
  },
  "manager.brief.grounded": { en: "Grounded", ko: "근거 확인됨" },
  "manager.brief.degraded": { en: "Degraded", ko: "성능 저하" },
  "manager.brief.generatedAt": { en: "Generated {at}", ko: "생성 시각 {at}" },
  "manager.brief.cost": { en: "Cost {cost}", ko: "비용 {cost}" },
  // UX-03: every figure in a brief is read off ONE snapshot, which can be older than the live Tax /
  // Wash Sales pages -- two counts that disagree are two dates, not a bug, and only this stamp says so.
  "manager.brief.asOf": { en: "As of {date}", ko: "{date} 기준" },
  // Density: a synthesis group of several 200+ character paragraphs renders as one wall. The first
  // paragraph stays visible; the rest sit behind this. The caveat line is never inside it.
  "manager.brief.readMore": { en: "Read more", ko: "더 보기" },

  // Stage-state labels for the brief run's own progress list (`MANAGER_STAGES`).
  "manager.stage.pending": { en: "Pending", ko: "대기" },
  "manager.stage.running": { en: "Running", ko: "실행 중" },
  "manager.stage.succeeded": { en: "Done", ko: "완료" },
  "manager.stage.degraded": { en: "Degraded", ko: "성능 저하" },
  "manager.stage.failed": { en: "Failed", ko: "실패" },
  "manager.stage.blocked": { en: "Blocked", ko: "차단됨" },
  "manager.stage.skipped": { en: "Skipped", ko: "건너뜀" },

  // --- Synthesis -------------------------------------------------------------------------------

  "manager.synthesis.heading": { en: "Synthesis", ko: "종합 분석" },
  "manager.synthesis.assessment": { en: "Assessment", ko: "평가" },
  "manager.synthesis.agreements": { en: "Agreements", ko: "일치하는 의견" },
  "manager.synthesis.conflicts": { en: "Conflicts", ko: "상충하는 의견" },
  "manager.synthesis.risks": { en: "Risks", ko: "위험 요인" },
  "manager.synthesis.openQuestions": { en: "Open questions", ko: "미결 질문" },

  // --- Data health -------------------------------------------------------------------------------

  "manager.dataHealth.heading": { en: "Data health", ko: "데이터 상태" },
  "manager.dataHealth.stale": { en: "Stale: {list}", ko: "오래됨: {list}" },
  "manager.dataHealth.unknown": { en: "Unknown: {list}", ko: "알 수 없음: {list}" },

  // UX-05. `DataHealth.stale`/`.unknown` carry the freshness catalog's own source keys, which used
  // to render raw ("macro_snapshot, calendar_events"). The eleven catalog sources already have
  // labels in `messages/data.ts` and are reused verbatim (COPY-STYLE rule 2, one key, reused); only
  // the two ids the manager's own data section adds on top of the catalog live here.
  "manager.source.sweep_refresh": { en: "Refresh sweep", ko: "새로고침 스윕" },
  "manager.source.daemon_social": { en: "Social daemon", ko: "소셜 데몬" },

  // --- Change-row figures ------------------------------------------------------------------------
  // UX-05. `ChangeItem.figures` is an open map of wire names (`unpriced_count`, `weight_pct`) --
  // a variable name is not a label, so keys render humanised and the one that reads as a claim
  // about the book gets a real sentence.
  "manager.figure.generic": { en: "{label}: {value}", ko: "{label}: {value}" },
  "manager.figure.unpricedCount": {
    en: "{value} position(s) unpriced",
    ko: "가격 없는 종목 {value}개",
  },

  // --- Commissions -----------------------------------------------------------------------------

  "manager.commissions.heading": { en: "Commissions", ko: "위임 조사" },
  "manager.commissions.note": {
    en: "Research the manager proposes -- approving spends its own budget.",
    ko: "매니저가 제안하는 추가 조사입니다 -- 승인하면 별도 예산이 사용됩니다.",
  },
  "manager.commissions.approve": { en: "Approve", ko: "승인" },
  "manager.commissions.decline": { en: "Decline", ko: "거절" },
  "manager.commissions.errorFallback": {
    en: "Could not update the commission.",
    ko: "위임 조사를 업데이트할 수 없습니다.",
  },
  // UX-05: a failed commission used to render the child's raw (often truncated) JSON payload,
  // session id and all, straight into the row. One readable line now; the payload is one click away
  // and stripped of anything that looks like a session/request id first.
  "manager.commission.failed": {
    en: "Commission failed: {reason}",
    ko: "커미션 실패: {reason}",
  },
  "manager.commission.redacted": { en: "[id removed]", ko: "[ID 제거됨]" },
  "manager.commission.state.proposed": { en: "Proposed", ko: "제안됨" },
  "manager.commission.state.approved": { en: "Approved", ko: "승인됨" },
  "manager.commission.state.running": { en: "Running", ko: "실행 중" },
  "manager.commission.state.succeeded": { en: "Done", ko: "완료" },
  "manager.commission.state.failed": { en: "Failed", ko: "실패" },
  "manager.commission.state.cancelled": { en: "Cancelled", ko: "취소됨" },
  "manager.commission.state.declined": { en: "Declined", ko: "거절됨" },

  // --- Chat ------------------------------------------------------------------------------------

  "manager.chat.heading": { en: "Ask the manager", ko: "매니저에게 질문" },
  // Always visible, never behind a disclosure -- same rule as `manager.notAdvice`.
  "manager.chat.caveat": {
    en: "A model's synthesis of this app's own lenses -- descriptive, not advice.",
    ko: "이 앱 자체 렌즈를 모델이 종합한 것입니다 -- 서술적일 뿐, 투자 조언이 아닙니다.",
  },
  "manager.chat.agentDown": { en: "Model down: {reason}", ko: "모델 중단: {reason}" },
  "manager.chat.errorFallback": { en: "Something went wrong.", ko: "문제가 발생했습니다." },
  "manager.chat.newThread": { en: "New thread", ko: "새 대화" },
  "manager.chat.deleteThread": { en: "Delete thread", ko: "대화 삭제" },
  // EXP-24: deleting a thread destroys its transcript, so it confirms first (UsersPanel's rule).
  "manager.thread.deleteConfirm.title": { en: "Delete this thread?", ko: "이 대화를 삭제할까요?" },
  "manager.thread.deleteConfirm.body": {
    en: "Removes the whole transcript from this machine. It cannot be undone.",
    ko: "이 컴퓨터에서 대화 전체를 삭제합니다. 되돌릴 수 없습니다.",
  },
  // Not the same words as `manager.chat.deleteThread` -- the sheet's confirm and the control that
  // opened it must be tellable apart by accessible name.
  "manager.thread.deleteConfirm.confirm": { en: "Yes, delete", ko: "예, 삭제" },
  "manager.chat.threadSelectLabel": { en: "Thread", ko: "대화 목록" },
  "manager.chat.untitledThread": { en: "Untitled", ko: "제목 없음" },
  "manager.chat.pending": { en: "Thinking...", ko: "생각 중..." },
  "manager.chat.youAsked": { en: "You asked", ko: "질문" },
  "manager.chat.factCheckFailed": {
    en: "Fact-check failed -- shown as written, verify before relying on it.",
    ko: "사실 확인 실패 -- 작성된 그대로 표시되며, 신뢰하기 전에 확인하세요.",
  },
  "manager.chat.questionLabel": { en: "Question", ko: "질문" },
  "manager.chat.questionPlaceholder": {
    en: "Ask about anything the manager tracks...",
    ko: "매니저가 추적하는 항목에 대해 질문하세요...",
  },
  "manager.chat.refreshFirst": { en: "Refresh data first", ko: "먼저 데이터 새로고침" },
  "manager.chat.send": { en: "Send", ko: "전송" },
  "manager.chat.turnCost": { en: "Cost {cost}", ko: "비용 {cost}" },
} as const satisfies MessageShard;
