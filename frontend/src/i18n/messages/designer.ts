/**
 * Portfolio Planner page (`Designer.tsx`) and its API helpers.
 *
 * Keys are prefixed `designer.` -- see `catalog.ts` for why the prefix is load-bearing. Long tooltip
 * copy is keyed with a `.detail` suffix so it gets the 240-character prose budget rather than the
 * 120-character default; the visible one-line labels stay under 120.
 *
 * The wash-sale sentences are deliberately full sentences with a date or amount placeholder, never
 * assembled from fragments -- the same rule the `tax`/`portfolio` shards follow, because the money
 * these describe is real and a mistranslated clause is worse than a long key. Counts that vary an
 * English plural get `_one`/`_other` variants whose Korean side reads identically (Korean has no
 * plural inflection); the call site picks the variant.
 */
import type { MessageShard } from "@/i18n/types";

export const designer = {
  // --- page header / status -------------------------------------------------
  "designer.title": { en: "Planner", ko: "플래너" },
  "designer.subtitle": {
    en: "Plan holdings across your accounts, with live wash-sale status on every ticker.",
    ko: "모든 종목의 실시간 워시 세일 상태와 함께 계좌별로 보유 구성을 계획하세요.",
  },
  "designer.pull": { en: "Pull current holdings", ko: "현재 보유 종목 불러오기" },
  "designer.pull.title": {
    en: "Add each account's current holdings to its column",
    ko: "각 계좌의 현재 보유 종목을 해당 열에 추가합니다",
  },
  "designer.clear": { en: "Empty board", ko: "보드 비우기" },
  "designer.clear.confirm": {
    en: "Remove every ticker from every column? Your notes are kept.",
    ko: "모든 열에서 모든 종목을 제거할까요? 메모는 유지됩니다.",
  },
  "designer.saved": { en: "Saved", ko: "저장됨" },
  "designer.saving": { en: "Saving…", ko: "저장 중…" },
  "designer.saveFailed": { en: "Save failed", ko: "저장 실패" },
  "designer.updatedAt": { en: "Last saved {time}", ko: "마지막 저장 {time}" },
  "designer.loading": { en: "Loading planner…", ko: "플래너 불러오는 중…" },
  "designer.apiError": {
    en: "API returned {status}: {message}",
    ko: "API가 {status}을(를) 반환했습니다: {message}",
  },
  "designer.cannotReachApi": {
    en: "Cannot reach the API. Is uvicorn running on port 8000?",
    ko: "API에 연결할 수 없습니다. 8000번 포트에서 uvicorn이 실행 중인가요?",
  },

  // --- legend --------------------------------------------------------------
  "designer.legend.ok": { en: "OK to buy", ko: "매수 가능" },
  "designer.legend.washOpen": { en: "Wash window open", ko: "워시 기간 열림" },
  "designer.legend.ira": { en: "IRA / caution", ko: "IRA / 주의" },
  "designer.legend.deferred": { en: "Deferred loss in basis", ko: "취득가에 이연 손실" },

  // --- search / palette -----------------------------------------------------
  "designer.search.placeholder": {
    en: "Search any ticker…  (e.g. NVDA)",
    ko: "종목 검색…  (예: NVDA)",
  },
  "designer.search.clear": { en: "Clear", ko: "지우기" },
  "designer.palette.held": { en: "Held", ko: "보유" },
  "designer.palette.all": { en: "All", ko: "전체" },
  "designer.palette.results": { en: "Results", ko: "검색 결과" },
  "designer.palette.empty": { en: "No current holdings found.", ko: "현재 보유 종목이 없습니다." },
  "designer.palette.noMatch": { en: "No match for “{q}”.", ko: "“{q}”에 대한 결과가 없습니다." },
  "designer.palette.useAnyway": { en: "Use “{q}” anyway →", ko: "그래도 “{q}” 추가 →" },
  "designer.palette.heldTag": { en: "held", ko: "보유" },

  // --- columns & notes ------------------------------------------------------
  "designer.column.count_one": { en: "{n} ticker", ko: "{n}개 종목" },
  "designer.column.count_other": { en: "{n} tickers", ko: "{n}개 종목" },
  "designer.note.placeholder": { en: "Notes for {account}…", ko: "{account} 메모…" },
  "designer.column.dropHint": { en: "Drag tickers here", ko: "여기로 종목을 끌어다 놓으세요" },

  // --- cards ---------------------------------------------------------------
  "designer.card.remove": { en: "Remove", ko: "제거" },
  "designer.card.qty": { en: "{qty} sh", ko: "{qty}주" },
  "designer.lock.title": {
    en: "Deferred wash-sale loss in basis",
    ko: "취득가에 포함된 워시 세일 이연 손실",
  },

  // --- wash-sale labels (one line) -----------------------------------------
  "designer.wash.ok": { en: "OK to buy", ko: "매수 가능" },
  "designer.wash.wait": { en: "Wait {days}d", ko: "{days}일 대기" },
  "designer.wash.iraOk": { en: "OK — IRA caution", ko: "매수 가능 — IRA 주의" },
  "designer.wash.iraBadge": { en: "IRA", ko: "IRA" },
  "designer.wash.safeOn": { en: "Safe to buy {date}", ko: "{date} 매수 가능" },
  "designer.wash.cleared": { en: "Wash window cleared {date}", ko: "워시 기간 종료 {date}" },
  "designer.wash.noWindow": { en: "No open wash-sale window", ko: "열려 있는 워시 세일 기간 없음" },

  // --- wash-sale tooltips (.detail: 240-char budget) -----------------------
  "designer.wash.tip.none.detail": {
    en: "No loss sale on record that a repurchase could defer a loss into.",
    ko: "재매수 시 손실을 이연시킬 매도 손실 기록이 없습니다.",
  },
  "designer.wash.tip.open.detail": {
    en: "A loss was sold in the last 30 days. Buying before {date} would defer that loss into the new shares.",
    ko: "최근 30일 내 손실 매도가 있었습니다. {date} 이전에 매수하면 그 손실이 새 주식으로 이연됩니다.",
  },
  "designer.wash.tip.cleared.detail": {
    en: "The last loss sale's 30-day window closed on {date}.",
    ko: "마지막 손실 매도의 30일 기간이 {date}에 종료되었습니다.",
  },
  "designer.wash.tip.ira.detail": {
    en: "A repurchase inside an IRA permanently disallows a matched loss (Rev. Rul. 2008-5) — no basis is added back.",
    ko: "IRA 내 재매수는 대응 손실을 영구적으로 불인정합니다(Rev. Rul. 2008-5). 취득가에 가산되지 않습니다.",
  },
  "designer.wash.tip.allTime.detail": {
    en: "All-time total ever deferred on this ticker, in old already-resold lots: {amount}. Separate from the 🔒 lock.",
    ko: "이 종목에서 지금까지 이연된 누적 총액(이미 재매도된 과거 로트): {amount}. 🔒 잠금과는 별개입니다.",
  },

  // --- holding / deferred detail (.detail) ---------------------------------
  "designer.card.tip.held.detail": {
    en: "Held here: {qty} sh, about {value}. Unrealized {unrealized}.",
    ko: "이 계좌 보유: {qty}주, 약 {value}. 미실현 {unrealized}.",
  },
  "designer.card.tip.notHeld.detail": {
    en: "Not held in this account.",
    ko: "이 계좌에는 보유하고 있지 않습니다.",
  },
  "designer.card.tip.deferred.detail": {
    en: "{amount} of deferred wash-sale loss is embedded in these shares' basis — realized only when you sell them.",
    ko: "이 주식들의 취득가에 {amount}의 워시 세일 이연 손실이 포함되어 있으며, 매도할 때에만 실현됩니다.",
  },

  // --- toasts & pull result -------------------------------------------------
  "designer.pull.added_one": { en: "Added {n} holding", ko: "보유 종목 {n}개 추가됨" },
  "designer.pull.added_other": { en: "Added {n} holdings", ko: "보유 종목 {n}개 추가됨" },
  "designer.pull.none": {
    en: "Columns already match your holdings",
    ko: "열이 이미 보유 종목과 일치합니다",
  },
  "designer.toast.duplicate": {
    en: "{symbol} is already in {account}",
    ko: "{symbol}은(는) 이미 {account}에 있습니다",
  },

  // --- empty state ---------------------------------------------------------
  "designer.empty.title": { en: "No accounts yet", ko: "아직 계좌가 없습니다" },
  "designer.empty.body": {
    en: "Import broker data first — the planner builds one column per open account.",
    ko: "먼저 증권사 데이터를 가져오세요. 플래너는 사용 중인 계좌마다 열을 하나씩 만듭니다.",
  },
} as const satisfies MessageShard;
