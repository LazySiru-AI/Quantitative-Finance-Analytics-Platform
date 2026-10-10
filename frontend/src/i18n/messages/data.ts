/**
 * The Data operator page (`pages/Data.tsx`) and its seven tab panels (`pages/data/*`).
 *
 * Keys are prefixed `data.` -- see `catalog.ts` for the convention. The Imports and Reconcile tabs
 * render the existing `ImportPanel`/`ReconcilePanel` components unchanged and read their copy from
 * `activity.*` (their existing shard); nothing here duplicates that copy. This shard covers only the
 * page chrome and the five new panels: Sectors, Inception, Users, Data health, About.
 *
 * Reuses `common.save`/`common.cancel`/`common.apply`/`common.status`/`common.action`/
 * `common.symbol`/`common.date` and `interaction.confirm.*` rather than repeating them here -- see
 * those shards' own docstrings for why a key used by more than one page belongs there instead. The
 * About panel (`data.about.*`, EXP-18/EXP-04) reuses further: `data.users.role.owner`/`.member` for
 * the caller's role, `ui.pill.notAdvice` + `tax.disclaimer.title` for the canonical not-advice line
 * (COPY-STYLE.md rule 2 -- one explanation per fact, app-wide), and `nav.page./manager.label` /
 * `nav.page./personas.label` for its two cross-links (rule 3: link the page, do not re-describe it).
 */
import type { MessageShard } from "@/i18n/types";

export const data = {
  // --- Data page: header + tab rail -------------------------------------------------------------
  "data.title": { en: "Data", ko: "데이터" },
  "data.subtitle": {
    en: "Import, reconcile, and administer the data this application runs on.",
    ko: "이 애플리케이션이 사용하는 데이터를 가져오고 대조하고 관리합니다.",
  },
  "data.tabs.label": { en: "Data sections", ko: "데이터 섹션" },
  "data.tabs.imports": { en: "Imports", ko: "가져오기" },
  "data.tabs.reconcile": { en: "Reconcile", ko: "대조" },
  "data.tabs.sectors": { en: "Sectors", ko: "섹터" },
  "data.tabs.inception": { en: "Desk inception", ko: "데스크 개시일" },
  "data.tabs.users": { en: "Users", ko: "사용자" },
  "data.tabs.health": { en: "Data health", ko: "데이터 상태" },
  "data.tabs.about": { en: "About", ko: "정보" },

  // --- Sectors panel -----------------------------------------------------------------------------
  "data.sectors.heading": { en: "Sector classification", ko: "섹터 분류" },
  "data.sectors.subtitle": {
    en: "Manual symbol → sector map behind the allocation views.",
    ko: "배분 화면이 사용하는 종목 → 섹터 수동 매핑입니다.",
  },
  "data.sectors.loading": { en: "Loading sector map…", ko: "섹터 매핑 불러오는 중…" },
  "data.sectors.error.generic": {
    en: "Could not load the sector map.",
    ko: "섹터 매핑을 불러오지 못했습니다.",
  },
  "data.sectors.empty": { en: "No symbols classified yet.", ko: "아직 분류된 종목이 없습니다." },
  "data.sectors.filterPlaceholder": { en: "Filter by symbol…", ko: "종목으로 필터링…" },
  "data.sectors.table.sector": { en: "Sector", ko: "섹터" },
  "data.sectors.selectLabel": { en: "Sector for {symbol}", ko: "{symbol}의 섹터" },
  "data.sectors.save": { en: "Save", ko: "저장" },
  "data.sectors.saving": { en: "Saving…", ko: "저장 중…" },
  "data.sectors.saveError": {
    en: "Could not save this sector.",
    ko: "섹터를 저장하지 못했습니다.",
  },
  "data.sectors.savedToast": {
    en: "{symbol} reclassified to {sector}.",
    ko: "{symbol}이(가) {sector}(으)로 재분류되었습니다.",
  },

  // --- Inception panel ---------------------------------------------------------------------------
  "data.inception.heading": { en: "Paper Desk inception", ko: "페이퍼 데스크 개시일" },
  "data.inception.subtitle": {
    en: "The window every paper book trades over. Changing it re-runs every book.",
    ko: "모든 페이퍼 북이 거래되는 기간입니다. 변경하면 모든 북이 다시 계산됩니다.",
  },
  "data.inception.loading": { en: "Loading inception state…", ko: "개시일 상태 불러오는 중…" },
  "data.inception.error.generic": {
    en: "Could not reach the Paper Desk API.",
    ko: "페이퍼 데스크 API에 연결할 수 없습니다.",
  },
  "data.inception.current": { en: "Current inception", ko: "현재 개시일" },
  "data.inception.default": { en: "Built-in default", ko: "기본 개시일" },
  "data.inception.customBadge": { en: "override", ko: "재정의됨" },
  "data.inception.dateLabel": { en: "New inception date", ko: "새 개시일" },
  "data.inception.range": {
    en: "Choose a date between {earliest} and {latest}.",
    ko: "{earliest}에서 {latest} 사이의 날짜를 선택하세요.",
  },
  "data.inception.apply": { en: "Set inception", ko: "개시일 설정" },
  "data.inception.applying": { en: "Applying…", ko: "적용 중…" },
  "data.inception.reset": { en: "Reset to default", ko: "기본값으로 재설정" },
  "data.inception.confirmQuestion": {
    en: "Set inception to {date}?",
    ko: "개시일을 {date}(으)로 설정할까요?",
  },
  "data.inception.confirmPreview": {
    en: "Every book on Paper Desk is recomputed from this date. Nothing is fetched from the market.",
    ko: "페이퍼 데스크의 모든 북이 이 날짜부터 다시 계산됩니다. 시장 데이터는 새로 가져오지 않습니다.",
  },
  "data.inception.resetConfirmQuestion": {
    en: "Reset inception to the built-in default, {date}?",
    ko: "개시일을 기본값인 {date}(으)로 재설정할까요?",
  },
  "data.inception.appliedToast": { en: "Inception set to {date}.", ko: "개시일이 {date}(으)로 설정되었습니다." },
  "data.inception.resetToast": {
    en: "Inception reset to the default, {date}.",
    ko: "개시일이 기본값 {date}(으)로 재설정되었습니다.",
  },

  // --- Users panel ---------------------------------------------------------------------------------
  "data.users.heading": { en: "Users", ko: "사용자" },
  "data.users.subtitle": {
    en: "Accounts that can sign in to this application.",
    ko: "이 애플리케이션에 로그인할 수 있는 계정입니다.",
  },
  "data.users.loading": { en: "Loading users…", ko: "사용자 불러오는 중…" },
  "data.users.error.generic": { en: "Could not load users.", ko: "사용자를 불러오지 못했습니다." },
  "data.users.empty": { en: "No users yet.", ko: "아직 사용자가 없습니다." },
  "data.users.table.username": { en: "Username", ko: "사용자명" },
  "data.users.table.role": { en: "Role", ko: "역할" },
  "data.users.table.created": { en: "Created", ko: "생성일" },
  "data.users.status.active": { en: "Active", ko: "활성" },
  "data.users.status.disabled": { en: "Disabled", ko: "비활성화됨" },
  // The two roles the backend knows about (`/api/auth/me`, `/api/users`): "owner" may reach every
  // owner-only API prefix (Tax, Portfolio, Import, Users, the store-health check); "member" cannot.
  "data.users.role.owner": { en: "Owner", ko: "소유자" },
  "data.users.role.member": { en: "Member", ko: "멤버" },
  "data.users.action.disable": { en: "Disable", ko: "비활성화" },
  "data.users.action.enable": { en: "Enable", ko: "활성화" },
  "data.users.action.resetPassword": { en: "Reset password", ko: "비밀번호 재설정" },
  "data.users.action.revokeSessions": { en: "Revoke sessions", ko: "세션 종료" },
  "data.users.action.error.generic": {
    en: "That action did not go through.",
    ko: "작업을 완료하지 못했습니다.",
  },
  // Role change (`POST /api/users/{username}/role`). No confirmation sheet -- unlike Disable/Revoke,
  // a role change does not end anyone's access, and `last_owner` below is the one outcome worth a
  // distinct message rather than the generic action error.
  "data.users.role.makeOwner": { en: "Make owner", ko: "소유자로 지정" },
  "data.users.role.makeMember": { en: "Make member", ko: "멤버로 지정" },
  "data.users.role.makeOwnerToast": {
    en: "{username} is now an owner.",
    ko: "{username} 계정이 이제 소유자입니다.",
  },
  "data.users.role.makeMemberToast": {
    en: "{username} is now a member.",
    ko: "{username} 계정이 이제 멤버입니다.",
  },
  // The server refuses to demote the last remaining owner (409 `{"detail": "last_owner"}`) -- this
  // is that response, worded as an explanation rather than a raw error code.
  "data.users.role.lastOwnerError": {
    en: "Cannot change {username}'s role: at least one owner must remain.",
    ko: "{username}의 역할을 변경할 수 없습니다. 소유자는 최소 한 명 있어야 합니다.",
  },
  "data.users.action.enabledToast": { en: "{username} enabled.", ko: "{username} 계정이 활성화되었습니다." },
  "data.users.action.disabledToast": { en: "{username} disabled.", ko: "{username} 계정이 비활성화되었습니다." },
  "data.users.action.revokedToast_one": {
    en: "{count} session ended for {username}.",
    ko: "{username}의 세션 {count}개가 종료되었습니다.",
  },
  "data.users.action.revokedToast_other": {
    en: "{count} sessions ended for {username}.",
    ko: "{username}의 세션 {count}개가 종료되었습니다.",
  },
  "data.users.disable.confirmQuestion": { en: "Disable {username}?", ko: "{username} 계정을 비활성화할까요?" },
  "data.users.disable.confirmPreview": {
    en: "{username} will no longer be able to sign in. Sessions already open stay open -- revoke separately.",
    ko: "{username}은(는) 더 이상 로그인할 수 없습니다. 이미 열려 있는 세션은 유지되며 별도로 종료해야 합니다.",
  },
  "data.users.revoke.confirmQuestion": {
    en: "End every session for {username}?",
    ko: "{username}의 모든 세션을 종료할까요?",
  },
  "data.users.revoke.confirmPreview": {
    en: "{username} is signed out everywhere immediately. The account itself is left untouched.",
    ko: "{username}은(는) 즉시 모든 곳에서 로그아웃됩니다. 계정 자체는 변경되지 않습니다.",
  },
  "data.users.create.heading": { en: "Create a user", ko: "사용자 생성" },
  "data.users.create.usernameLabel": { en: "Username", ko: "사용자명" },
  "data.users.create.passwordLabel": { en: "Password", ko: "비밀번호" },
  "data.users.create.roleLabel": { en: "Role", ko: "역할" },
  "data.users.create.submit": { en: "Create user", ko: "사용자 생성" },
  "data.users.create.submitting": { en: "Creating…", ko: "생성 중…" },
  "data.users.create.error.generic": {
    en: "Could not create that user.",
    ko: "해당 사용자를 생성하지 못했습니다.",
  },
  "data.users.create.successToast": { en: "{username} created.", ko: "{username} 계정이 생성되었습니다." },
  "data.users.resetPassword.heading": {
    en: "Reset password for {username}",
    ko: "{username}의 비밀번호 재설정",
  },
  "data.users.resetPassword.passwordLabel": { en: "New password", ko: "새 비밀번호" },
  "data.users.resetPassword.submit": { en: "Set password", ko: "비밀번호 설정" },
  "data.users.resetPassword.submitting": { en: "Setting…", ko: "설정 중…" },
  "data.users.resetPassword.error.generic": {
    en: "Could not set that password.",
    ko: "비밀번호를 설정하지 못했습니다.",
  },
  "data.users.resetPassword.successToast": {
    en: "Password reset for {username}.",
    ko: "{username}의 비밀번호가 재설정되었습니다.",
  },
  "data.users.resetPassword.cancel": { en: "Cancel", ko: "취소" },

  // --- Data health panel -------------------------------------------------------------------------
  "data.health.heading": { en: "Data health", ko: "데이터 상태" },
  "data.health.subtitle": {
    en: "Read-only status of the background market-data jobs.",
    ko: "백그라운드 시장 데이터 작업의 읽기 전용 상태입니다.",
  },
  "data.health.loading": { en: "Loading status…", ko: "상태 불러오는 중…" },
  "data.health.error.generic": { en: "Could not load data health.", ko: "데이터 상태를 불러오지 못했습니다." },
  "data.health.refresh.heading": { en: "Market-data refresh sweep", ko: "시장 데이터 새로고침" },
  "data.health.refresh.running": { en: "Running", ko: "실행 중" },
  "data.health.refresh.idle": { en: "Idle", ko: "대기 중" },
  "data.health.refresh.incomplete": { en: "Stopped early", ko: "조기 종료됨" },
  "data.health.refresh.complete": { en: "Complete", ko: "완료" },
  "data.health.refresh.processed": { en: "Processed", ko: "처리됨" },
  "data.health.refresh.queued": { en: "Queued", ko: "대기열" },
  "data.health.refresh.failed": { en: "Failed", ko: "실패" },
  "data.health.refresh.macroSnapshot": { en: "Macro snapshot", ko: "매크로 스냅샷" },
  "data.health.refresh.socialSnapshots": { en: "Social snapshots", ko: "소셜 스냅샷" },
  "data.health.refresh.lastRun": {
    en: "Last run {started} → {finished}",
    ko: "최근 실행 {started} → {finished}",
  },
  "data.health.refresh.neverRun": { en: "No sweep has run yet.", ko: "아직 실행된 스윕이 없습니다." },
  "data.health.refresh.failedSymbols": { en: "Failed symbols", ko: "실패한 종목" },
  "data.health.social.heading": { en: "Social snapshot scheduler", ko: "소셜 스냅샷 스케줄러" },
  "data.health.social.healthy": { en: "Healthy", ko: "정상" },
  "data.health.social.unhealthy": { en: "Unhealthy", ko: "비정상" },
  "data.health.social.totalTicks": { en: "Ticks so far", ko: "지금까지 틱 수" },
  "data.health.social.failureStreak": { en: "Failure streak", ko: "연속 실패" },
  "data.health.social.lastTick": { en: "Last tick {when}", ko: "최근 틱 {when}" },
  "data.health.social.neverTicked": { en: "Has not ticked yet.", ko: "아직 실행된 적이 없습니다." },
  "data.health.social.lastError": { en: "Last error: {error}", ko: "최근 오류: {error}" },
  "data.health.social.consecutiveFailures": {
    en: "{count} of {max} consecutive failed ticks before unhealthy",
    ko: "비정상 판정까지 연속 실패 틱 {count}/{max}",
  },

  // --- Data health: fetch-now + freshness table --------------------------------------------------
  "data.health.fetch.action": { en: "Fetch data now", ko: "지금 데이터 가져오기" },
  "data.health.fetch.fetching": { en: "Fetching…", ko: "가져오는 중…" },
  "data.health.fetch.alreadyRunning": {
    en: "A sweep is already running -- watching its progress below.",
    ko: "이미 스윕이 실행 중입니다. 아래에서 진행 상황을 확인하세요.",
  },
  "data.health.fetch.error": {
    en: "Could not start the data sweep.",
    ko: "데이터 스윕을 시작하지 못했습니다.",
  },
  "data.freshness.heading": { en: "Data freshness", ko: "데이터 최신성" },
  "data.freshness.loading.error": {
    en: "Could not load the freshness table.",
    ko: "최신성 표를 불러오지 못했습니다.",
  },
  "data.freshness.table.label": { en: "Per-source data freshness", ko: "소스별 데이터 최신성" },
  "data.freshness.table.source": { en: "Source", ko: "소스" },
  "data.freshness.table.class": { en: "Class", ko: "분류" },
  "data.freshness.table.policy": { en: "Policy", ko: "정책" },
  "data.freshness.table.lastUpdated": { en: "Last updated", ko: "최근 업데이트" },
  "data.freshness.table.age": { en: "Age", ko: "경과 시간" },
  "data.freshness.table.status": { en: "Status", ko: "상태" },
  "data.freshness.table.refreshable": { en: "Covered by fetch", ko: "가져오기 대상" },
  "data.freshness.age.none": { en: "--", ko: "--" },
  "data.freshness.age.minutes": { en: "{n}m", ko: "{n}분" },
  "data.freshness.age.hours": { en: "{n}h", ko: "{n}시간" },
  "data.freshness.age.days": { en: "{n}d", ko: "{n}일" },
  "data.freshness.source.bars_daily": { en: "Daily bars", ko: "일봉" },
  "data.freshness.source.bars_intraday": { en: "Intraday bars", ko: "분봉" },
  "data.freshness.source.macro_snapshot": { en: "Macro snapshot", ko: "매크로 스냅샷" },
  "data.freshness.source.calendar_events": { en: "Calendar events", ko: "이벤트 캘린더" },
  "data.freshness.source.fundamentals_edgar": { en: "Fundamentals (EDGAR)", ko: "재무 데이터 (EDGAR)" },
  "data.freshness.source.institutions_filings": { en: "Institution filings", ko: "기관 공시" },
  "data.freshness.source.news": { en: "News", ko: "뉴스" },
  "data.freshness.source.social_snapshots": { en: "Social snapshots", ko: "소셜 스냅샷" },
  "data.freshness.source.live_quotes": { en: "Live quotes", ko: "실시간 시세" },
  "data.freshness.source.ledger": { en: "Ledger", ko: "원장" },
  "data.freshness.source.persona_corpus": { en: "Persona corpus", ko: "페르소나 코퍼스" },
  "data.freshness.class.day_frame": { en: "Day frame", ko: "일 단위" },
  "data.freshness.class.intraday": { en: "Intraday", ko: "장중" },
  "data.freshness.class.local": { en: "Local", ko: "로컬" },
  "data.freshness.policy.on_demand": { en: "On demand", ko: "수요 발생 시" },
  "data.freshness.policy.startup_sweep": { en: "Startup sweep", ko: "시작 시 스윕" },
  "data.freshness.policy.scheduled": { en: "Scheduled", ko: "예약됨" },
  "data.freshness.policy.streaming": { en: "Streaming", ko: "스트리밍" },
  "data.freshness.policy.computed": { en: "Computed", ko: "계산됨" },
  "data.freshness.policy.manual": { en: "Manual", ko: "수동" },
  "data.freshness.status.fresh": { en: "Fresh", ko: "최신" },
  "data.freshness.status.live": { en: "Live", ko: "실시간" },
  "data.freshness.status.stale": { en: "Stale", ko: "지연됨" },
  "data.freshness.status.disabled": { en: "Disabled", ko: "비활성화됨" },
  "data.freshness.status.unknown": { en: "Unknown", ko: "알 수 없음" },
  "data.freshness.refreshable.yes": { en: "Yes", ko: "예" },
  "data.freshness.refreshable.no": { en: "No", ko: "아니요" },
  "data.freshness.note.summary": {
    en: "Sources refresh on three different rhythms -- day frame, intraday, and local.",
    ko: "소스는 일 단위, 장중, 로컬이라는 세 가지 주기로 각기 다르게 갱신됩니다.",
  },
  "data.freshness.note.dayFrame": {
    en: "Day-frame sources (daily bars, fundamentals, filings) update once the sweep runs and stay valid until the next one.",
    ko: "일 단위 소스(일봉, 재무 데이터, 공시)는 스윕이 실행될 때 갱신되고 다음 스윕까지 그대로 유효합니다.",
  },
  "data.freshness.note.intraday": {
    en: "Intraday sources (intraday bars, live quotes) go stale within the same trading day if nothing refreshes them.",
    ko: "장중 소스(분봉, 실시간 시세)는 갱신되지 않으면 같은 거래일 안에서도 지연될 수 있습니다.",
  },
  "data.freshness.note.local": {
    en: "Local sources (the ledger, the persona corpus) are computed from data already on disk, not fetched from a provider.",
    ko: "로컬 소스(원장, 페르소나 코퍼스)는 외부 제공자가 아니라 이미 디스크에 있는 데이터로부터 계산됩니다.",
  },

  // --- Data health: navigation telemetry (owner-only; hidden entirely for a member) ---------------
  "data.health.nav.heading": { en: "Navigation, last 30 days", ko: "탐색 현황, 최근 30일" },
  "data.health.nav.page": { en: "Page", ko: "페이지" },
  "data.health.nav.tab": { en: "Tab", ko: "탭" },
  "data.health.nav.hits": { en: "Hits", ko: "조회 수" },
  "data.health.nav.lastSeen": { en: "Last seen", ko: "최근 방문" },
  "data.health.nav.empty": { en: "No navigation recorded yet.", ko: "아직 기록된 탐색이 없습니다." },
  // --- About panel (EXP-18/EXP-04): where data lives, what leaves the machine, how long it's kept -
  "data.about.heading": { en: "About your data", ko: "내 데이터 정보" },
  "data.about.subtitle": {
    en: "Where it lives, what leaves this machine, and how long it's kept.",
    ko: "저장 위치, 외부로 나가는 항목, 보관 기간을 정리했습니다.",
  },
  "data.about.loading": { en: "Loading data counts…", ko: "데이터 수치 불러오는 중…" },
  "data.about.error.generic": {
    en: "Could not reach the retention endpoint -- the notes above still apply.",
    ko: "보관 정보를 불러오지 못했습니다. 위 설명은 그대로 유효합니다.",
  },

  "data.about.location.heading": { en: "Where your data lives", ko: "데이터 저장 위치" },
  "data.about.location.summary": {
    en: "Ledger, exports and the persona vault: on this machine, under this app's data folder. Nothing is synced.",
    ko: "원장, 내보내기, 페르소나 자료실: 이 기기의 앱 데이터 폴더 안에 있습니다. 어디에도 동기화되지 않습니다.",
  },
  "data.about.location.detail": {
    en: "Every store below -- the ledger, imported broker exports, the persona vault, Paper Desk books, and Manager briefs and chats -- is a file or a SQLite database under this app's own data directory, never a cloud service.",
    ko: "아래의 모든 저장소 -- 원장, 가져온 증권사 내보내기, 페르소나 자료실, 페이퍼 데스크 북, 매니저 브리프와 대화 -- 는 클라우드가 아니라 이 앱의 데이터 폴더 안 파일이나 SQLite 데이터베이스입니다.",
  },

  "data.about.egress.heading": { en: "What leaves this machine", ko: "이 기기 밖으로 나가는 데이터" },
  "data.about.egress.summary": {
    en: "Market/FRED/SEC fetches carry no account data. The model desks send figures and notes to the model provider.",
    ko: "시장·FRED·SEC 조회는 계좌 정보를 담지 않습니다. 모델 데스크는 수치와 노트를 모델 제공자에게 전송합니다.",
  },
  "data.about.egress.detail": {
    en: "Manager briefs, persona chat, persona traders and on-display translation each send only what they cite -- a figure, a note, a question -- to the model provider for that one call. See the Manager page's egress line for what a brief sends.",
    ko: "매니저 브리프, 페르소나 대화, 페르소나 트레이더, 화면 번역은 각 호출마다 인용하는 내용(수치, 노트, 질문)만 모델 제공자에게 전송합니다. 브리프가 전송하는 내용은 매니저 페이지의 안내를 참고하세요.",
  },
  "data.about.egress.managerLink": { en: "Manager's own egress note", ko: "매니저 페이지의 전송 안내" },

  "data.about.retention.heading": { en: "How long history is kept", ko: "보관 기간" },
  "data.about.retention.summary": {
    en: "Kept until you delete it. Nothing here purges on a schedule.",
    ko: "삭제하기 전까지 보관됩니다. 예약된 자동 삭제는 없습니다.",
  },
  "data.about.retention.detail": {
    en: "Every count below comes from this app's own stores, read live. Delete a thread, a persona, or a trader book from the page that owns it -- there is no separate purge control here.",
    ko: "아래 각 수치는 이 앱의 저장소에서 실시간으로 읽어옵니다. 대화, 페르소나, 트레이더 북은 각 기능 페이지에서 삭제하세요. 이 화면에는 별도의 삭제 기능이 없습니다.",
  },
  "data.about.retention.manage": {
    en: "Delete a thread, a persona, or a trader book from {manager} or {personas}.",
    ko: "대화, 페르소나, 트레이더 북은 {manager} 또는 {personas}에서 삭제할 수 있습니다.",
  },
  "data.about.retention.briefRange": {
    en: "Briefs span {oldest} to {newest}.",
    ko: "브리프 기간: {oldest} ~ {newest}",
  },
  "data.about.retention.noBriefs": { en: "No briefs yet.", ko: "아직 브리프가 없습니다." },
  "data.about.stat.ledger": { en: "Ledger transactions", ko: "원장 거래 수" },
  "data.about.stat.users": { en: "User accounts", ko: "사용자 계정" },
  "data.about.stat.managerBriefs": { en: "Manager briefs", ko: "매니저 브리프" },
  "data.about.stat.chatThreads": { en: "Chat threads", ko: "대화 스레드" },
  "data.about.stat.personaNotes": { en: "Persona vault notes", ko: "페르소나 자료실 노트" },
  "data.about.stat.deskRuns": { en: "Agent desk runs", ko: "에이전트 데스크 실행" },
  "data.about.stat.paperdeskBooks": { en: "Paper Desk books", ko: "페이퍼 데스크 북" },
  "data.about.cache.label": { en: "Translation cache", ko: "번역 캐시" },
  "data.about.cache.present": { en: "Cached", ko: "캐시됨" },
  "data.about.cache.absent": { en: "Not cached yet", ko: "아직 캐시 없음" },

  "data.about.auth.heading": { en: "Login and roles", ko: "로그인과 역할" },
  "data.about.auth.roleLabel": { en: "Your role", ko: "내 역할" },
  "data.about.auth.enabledLabel": { en: "Login required", ko: "로그인 필요 여부" },
  "data.about.auth.on": { en: "On", ko: "켜짐" },
  "data.about.auth.off": { en: "Off (local, single-user)", ko: "꺼짐 (로컬 단일 사용자)" },

  "data.about.notAdvice.heading": { en: "Not advice", ko: "조언 아님" },

  // Breakdown hint on the combined "Chat threads" tile -- manager and persona chats are separate
  // stores (`app.manager.service`/`app.personas.service`) summed into one visible count.
  "data.about.stat.chatThreads.hint": {
    en: "{manager} manager, {persona} persona",
    ko: "매니저 {manager}, 페르소나 {persona}",
  },

  // Delete controls: the real `DELETE` routes `purge_endpoints` reports, worded in plain language and
  // linked to the page that hosts each one -- see this endpoint's own docstring for why the panel
  // links out rather than inventing a purge button here.
  "data.about.purge.heading": { en: "Delete controls", ko: "삭제 기능" },
  "data.about.purge.managerChats": { en: "Manager chat threads", ko: "매니저 대화 스레드" },
  "data.about.purge.personas": { en: "Personas", ko: "페르소나" },
  "data.about.purge.personaSources": { en: "Persona vault sources", ko: "페르소나 자료실 출처" },
  "data.about.purge.personaChats": { en: "Persona chat threads", ko: "페르소나 대화 스레드" },
  "data.about.purge.personaTrader": { en: "Persona paper trader", ko: "페르소나 페이퍼 트레이더" },
} as const satisfies MessageShard;
