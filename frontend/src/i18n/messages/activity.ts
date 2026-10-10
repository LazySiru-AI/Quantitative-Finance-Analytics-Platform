/**
 * Activity page, import panel and reconciliation.
 *
 * Keys are prefixed `activity.` -- see `catalog.ts` for the convention and for why the prefix
 * is load-bearing rather than cosmetic.
 */
import type { MessageShard } from "@/i18n/types";

export const activity = {
  // --- Activity.tsx: page chrome ------------------------------------------
  "activity.title": { en: "Activity", ko: "거래 내역" },
  "activity.subtitle": {
    en: "Every transaction, with the import and row it came from. Stored, not calculated.",
    ko: "원장에 있는 모든 거래를 가져온 파일과 행 번호까지 함께 보여줍니다. 계산이 아닌 저장된 데이터입니다.",
  },
  "activity.importToggle.hide": { en: "Hide import", ko: "가져오기 숨기기" },
  "activity.importToggle.show": { en: "Import broker exports", ko: "증권사 내보내기 파일 가져오기" },
  "activity.importToggle.hint": {
    en: "Loads the CSVs in the server's data directory. Re-importing is safe.",
    ko: "서버의 데이터 디렉터리에 있는 CSV 파일을 불러옵니다. 다시 가져와도 안전합니다.",
  },
  "activity.filter.symbolPlaceholder": { en: "ALL", ko: "전체" },
  "activity.filter.symbolAriaLabel": { en: "Filter by symbol", ko: "종목으로 필터링" },
  "activity.filter.tradesOnly": { en: "Trades only", ko: "매매만 보기" },
  "activity.loading": { en: "Loading activity…", ko: "거래 내역 불러오는 중…" },
  "activity.error.couldNotLoad": { en: "Could not load activity.", ko: "거래 내역을 불러올 수 없습니다." },
  "activity.empty.filtered": {
    en: "No transactions match these filters.",
    ko: "이 필터와 일치하는 거래가 없습니다.",
  },
  "activity.empty.noLedger": {
    en: "No transactions in the ledger yet — import a broker export above.",
    ko: "원장에 아직 거래가 없습니다 — 위에서 증권사 내보내기 파일을 가져오세요.",
  },

  // --- Activity.tsx: summary tiles -----------------------------------------
  "activity.tile.transactions": { en: "Transactions", ko: "거래 건수" },
  "activity.tile.bought": { en: "Bought", ko: "매수" },
  "activity.tile.grossHint": {
    en: "gross, across all matches",
    ko: "필터와 일치하는 모든 항목의 총액",
  },
  "activity.tile.sold": { en: "Sold", ko: "매도" },
  "activity.tile.netCashFlow": { en: "Net cash flow", ko: "순현금흐름" },
  "activity.tile.netCashFlowHint": {
    en: "includes fees and income — not sold − bought",
    ko: "수수료와 수익 포함 — 매도액에서 매수액을 뺀 값이 아님",
  },

  // --- table chrome shared across this page's tables -----------------------
  "activity.table.regionLabel": { en: "Transactions table", ko: "거래 내역 표" },
  // EXP-15 (WCAG 1.3.1): accessible `<caption>` for the ledger table, rendered through
  // `TableCaption` (`@/components/tableSort`). Two variants, not one key with an always-present page
  // clause: below one page there is no "page 1 of 1" worth announcing, and a screen-reader user
  // should not have to parse a page count that carries no information. `{shown}`/`{total}` mirror
  // this table's own `FilterBar` "Showing N of M" note.
  "activity.table.caption.single": {
    en: "Transactions, {shown} of {total} rows",
    ko: "거래 내역, 전체 {total}행 중 {shown}행",
  },
  "activity.table.caption.paged": {
    en: "Transactions, {shown} of {total} rows, page {page} of {totalPages}",
    ko: "거래 내역, 전체 {total}행 중 {shown}행, {page}/{totalPages}페이지",
  },
  "activity.table.amount": { en: "Amount", ko: "금액" },
  "activity.table.account": { en: "Account", ko: "계좌" },
  "activity.table.importTitle": { en: "import {id}", ko: "가져오기 {id}" },
  "activity.table.file": { en: "File", ko: "파일" },
  "activity.table.format": { en: "Format", ko: "형식" },
  "activity.table.rows": { en: "Rows", ko: "행 수" },
  "activity.table.state": { en: "State", ko: "상태" },
  "activity.table.result": { en: "Result", ko: "결과" },
  "activity.table.added": { en: "Added", ko: "추가됨" },
  "activity.table.alreadyThere": { en: "Already there", ko: "이미 있음" },
  "activity.table.notTransaction": { en: "Not a transaction", ko: "거래 아님" },

  // --- Activity.tsx: pager --------------------------------------------------
  "activity.pager.previous": { en: "Previous", ko: "이전" },
  "activity.pager.next": { en: "Next", ko: "다음" },
  "activity.pager.range": { en: "{first}–{last} of {total}", ko: "{total} 중 {first}–{last}" },

  // --- ImportPanel.tsx: head and load states --------------------------------
  "activity.import.heading": { en: "Import", ko: "가져오기" },
  "activity.import.readingDir": { en: "reading {dir}", ko: "{dir} 읽는 중" },
  "activity.import.looking": {
    en: "Looking for broker exports…",
    ko: "증권사 내보내기 파일 찾는 중…",
  },
  "activity.import.error.generic": {
    en: "Could not reach the import endpoint.",
    ko: "가져오기 엔드포인트에 연결할 수 없습니다.",
  },
  "activity.import.empty.body": {
    en: "No broker exports found in {dir}. Copy the CSVs your brokers export into that directory, then reload this page. Nothing is uploaded — the application reads the files where they sit.",
    ko: "{dir}에서 증권사 내보내기 파일을 찾을 수 없습니다. 증권사가 내보낸 CSV 파일을 해당 디렉터리에 복사한 다음 이 페이지를 새로고침하세요. 업로드되지 않습니다 — 애플리케이션이 파일이 있는 위치에서 그대로 읽습니다.",
  },

  // --- ImportPanel.tsx: per-file decisions header ---------------------------
  "activity.import.decisions.heading": { en: "Where should these go?", ko: "이 파일들은 어디로 가야 하나요?" },
  "activity.import.decisions.intro": {
    en: "A file's header says which broker wrote it, not which account. What the ledger {can} say is whether it already holds these exact transactions — evidence is below each file, exact rather than a guess. Anything you leave alone is not touched.",
    ko: "파일의 헤더는 어떤 증권사가 작성했는지 알려주지만, 어떤 계좌인지는 알려주지 않습니다. 원장이 {can} 있는 것은 이 파일의 거래를 이미 보유하고 있는지 여부입니다 — 그 근거는 각 파일 아래에 있으며, 추측이 아니라 정확합니다. 그대로 둔 파일은 건드리지 않습니다.",
  },
  "activity.import.decisions.canWord": { en: "can", ko: "말할 수" },

  // --- ImportPanel.tsx: run action -------------------------------------------
  "activity.import.action.running": { en: "Importing…", ko: "가져오는 중…" },
  "activity.import.action.file_one": { en: "Import {count} file", ko: "{count}개 파일 가져오기" },
  "activity.import.action.file_other": { en: "Import {count} files", ko: "{count}개 파일 가져오기" },
  "activity.import.action.hint": {
    en: "Re-importing is safe: rows already in the ledger are recognised and left alone.",
    ko: "다시 가져와도 안전합니다: 이미 원장에 있는 행은 인식되어 그대로 남습니다.",
  },

  // --- ImportPanel.tsx: run result --------------------------------------------
  "activity.import.result.rowsAdded_one": { en: "{count} row added", ko: "{count}개 행 추가됨" },
  "activity.import.result.rowsAdded_other": { en: "{count} rows added", ko: "{count}개 행 추가됨" },
  "activity.import.result.ledgerHolds": {
    en: "ledger now holds {count}",
    ko: "현재 원장에 {count}건 보유 중",
  },
  "activity.import.result.conflicts.title": { en: "Nothing was overwritten.", ko: "아무것도 덮어쓰지 않았습니다." },
  "activity.import.result.conflicts.body": {
    en: "These rows are already in the ledger with different values. Either the broker restated them or the adapter changed how it reads them — and the stored figures may already be on a tax form, so they were left as they were.",
    ko: "이 행들은 이미 다른 값으로 원장에 있습니다. 증권사가 값을 재고지했거나 어댑터가 읽는 방식을 변경한 것일 수 있으며 — 저장된 수치는 이미 세금 신고서에 사용되었을 수 있으므로 그대로 두었습니다.",
  },

  // --- ImportPanel.tsx / api/imports.ts: file status labels -------------------
  "activity.import.status.imported": { en: "Imported", ko: "가져옴" },
  "activity.import.status.unchanged": { en: "Already imported", ko: "이미 가져옴" },
  "activity.import.status.conflicts": { en: "Conflicts", ko: "충돌" },
  "activity.import.status.undeclared": { en: "No account declared", ko: "계좌 미지정" },
  "activity.import.status.noAdapter": { en: "Unrecognised format", ko: "인식할 수 없는 형식" },
  "activity.import.status.ambiguous": { en: "Ambiguous format", ko: "모호한 형식" },
  "activity.import.status.failed": { en: "Failed", ko: "실패" },
  "activity.badge.ready": { en: "Ready", ko: "준비됨" },

  // --- ImportPanel.tsx: manifest notice ---------------------------------------
  "activity.import.manifest.readError": {
    en: "{path} could not be read.",
    ko: "{path} 파일을 읽을 수 없습니다.",
  },
  "activity.import.manifest.noneTitle": { en: "No account manifest yet.", ko: "아직 계좌 매니페스트가 없습니다." },
  "activity.import.manifest.noneBody": {
    en: "A file's header names the broker, not the account — taxable and Roth exports look identical. Declare it once in {path}:",
    ko: "파일의 헤더는 어떤 증권사인지 알려주지만 그 증권사의 어떤 계좌인지는 알려주지 않습니다 — 과세 계좌 내보내기와 로스 계좌 내보내기는 동일하게 보입니다. {path}에 한 번만 선언한 다음 가져오세요:",
  },
  "activity.import.manifest.noneHint": {
    en: "Writes a template for the files below, broker filled in. Set {field} — decides tax reporting and wash-sale permanence.",
    ko: "아래 파일용 템플릿을 생성하며 증권사는 이미 채워져 있습니다. 각 항목에 {field}을(를) 설정하세요 — 세금 신고 여부와 워시 세일 영구 소멸 여부를 결정하는, 기본값 없는 필드입니다.",
  },
  "activity.import.manifest.undeclared_one": {
    en: "{count} file is not declared in {path}.",
    ko: "{path}에 선언되지 않은 파일이 {count}개 있습니다.",
  },
  "activity.import.manifest.undeclared_other": {
    en: "{count} files are not declared in {path}.",
    ko: "{path}에 선언되지 않은 파일이 {count}개 있습니다.",
  },
  "activity.import.manifest.undeclaredHint": {
    en: "Add an {entry} entry for each, or leave them out if they are not broker exports. They will not be imported.",
    ko: "각각에 대해 {entry} 항목을 추가하거나, 증권사 내보내기 파일이 아니라면 제외하세요. 가져오지 않습니다.",
  },

  // --- ImportPanel.tsx: skipped-row tooltip -----------------------------------
  "activity.import.skipped.none": {
    en: "every row became a transaction",
    ko: "모든 행이 거래로 변환되었습니다",
  },

  // --- ImportDecisionRow.tsx: select options ----------------------------------
  "activity.decision.treatment.taxable": { en: "Taxable", ko: "과세 계좌" },
  "activity.decision.treatment.rothIra": { en: "Roth IRA", ko: "로스 IRA" },
  "activity.decision.treatment.traditionalIra": { en: "Traditional IRA", ko: "전통 IRA" },
  "activity.decision.accountType.cash": { en: "Cash", ko: "현금" },
  "activity.decision.accountType.margin": { en: "Margin", ko: "마진" },
  "activity.decision.accountType.retirement": { en: "Retirement", ko: "은퇴 계좌" },

  // --- ImportDecisionRow.tsx: modes -------------------------------------------
  "activity.decision.legend": { en: "What to do with {filename}", ko: "{filename}에 대해 무엇을 할지" },
  "activity.decision.mode.skip": { en: "Leave it alone", ko: "건너뛰기" },
  "activity.decision.mode.attach": { en: "Add to an existing account", ko: "기존 계좌에 추가" },
  "activity.decision.mode.create": { en: "Create a new account", ko: "새 계좌 만들기" },
  "activity.decision.noMatches": {
    en: "No account at this broker shares any transaction with this file. That normally means it is a new account.",
    ko: "이 증권사의 어떤 계좌도 이 파일과 거래를 공유하지 않습니다. 일반적으로 새 계좌라는 의미입니다.",
  },

  // --- ImportDecisionRow.tsx: match table --------------------------------------
  "activity.decision.table.select": { en: "Select", ko: "선택" },
  "activity.decision.table.evidence": { en: "Evidence", ko: "근거" },
  "activity.decision.table.wouldAdd": { en: "Would add", ko: "추가될 행" },
  "activity.decision.showFiltered": {
    en: "Show only accounts that share transactions",
    ko: "거래를 공유하는 계좌만 보기",
  },
  "activity.decision.showAll": {
    en: "Show all {count} accounts at this broker",
    ko: "이 증권사의 계좌 {count}개 모두 보기",
  },

  // --- ImportDecisionRow.tsx: create-new-account warning -----------------------
  "activity.decision.shareWarning_one": {
    en: "This file shares {count} transaction with {account}.",
    ko: "이 파일은 {account}와(과) {count}건의 거래를 공유합니다.",
  },
  "activity.decision.shareWarning_other": {
    en: "This file shares {count} transactions with {account}.",
    ko: "이 파일은 {account}와(과) {count}건의 거래를 공유합니다.",
  },
  "activity.decision.shareWarningBody": {
    en: "Creating a new account stores those trades twice. Usually it means a re-export belonging on the existing account.",
    ko: "새 계좌를 만들면 해당 거래가 두 계좌 모두에 다시 저장됩니다. 가끔은 이것이 의도한 결과일 수 있지만, 보통은 재내보내기이며 기존 계좌에 속해야 함을 의미합니다.",
  },

  // --- ImportDecisionRow.tsx: new-account fields --------------------------------
  "activity.decision.field.accountId": { en: "Account id", ko: "계좌 ID" },
  "activity.decision.field.label": { en: "Label", ko: "레이블" },
  "activity.decision.field.taxTreatment": { en: "Tax treatment", ko: "세금 처리" },
  "activity.decision.field.accountType": { en: "Account type", ko: "계좌 유형" },
  "activity.decision.note.taxTreatmentLead": {
    en: "Tax treatment is not a formality.",
    ko: "세금 처리는 형식적인 절차가 아닙니다.",
  },
  "activity.decision.note.accountTypeLead": { en: "Account type", ko: "계좌 유형" },
  "activity.decision.note.body": {
    en: "{taxTreatmentLead} Decides whether gains are reported, and whether a repurchase permanently kills a loss vs deferring it. No safe default. {accountTypeLead} decides whether cash can go negative — a cash account cannot, a margin account can.",
    ko: "{taxTreatmentLead} 이는 이 계좌의 이익이 신고되는지 여부와, 계좌 내에서 동일한 종목을 재매수할 때 손실이 이연되지 않고 영구적으로 소멸되는지를 결정합니다. 자동으로 추론되지 않으며 안전하게 둘 수 있는 기본값이 없습니다. {accountTypeLead}은(는) 현금 잔액이 마이너스가 되는지 확인하는 기준을 결정합니다 — 현금 계좌는 마이너스가 될 수 없고, 마진 계좌는 될 수 있습니다.",
  },

  // --- ImportDecisionRow.tsx: ambiguous match warning ----------------------------
  "activity.decision.ambiguous.title": {
    en: "This file shares transactions with more than one account.",
    ko: "이 파일은 여러 계좌와 거래를 공유합니다.",
  },
  "activity.decision.ambiguous.body": {
    en: "Nothing has been preselected. Two accounts holding identical trades is either a real cross-account duplicate worth looking at or an identity collision worth investigating — either way, choosing for you would bury it.",
    ko: "아무것도 미리 선택되지 않았습니다. 두 계좌가 동일한 거래를 보유하고 있다는 것은 살펴볼 가치가 있는 실제 교차 계좌 중복이거나 조사할 가치가 있는 식별 충돌 중 하나입니다 — 어느 쪽이든 대신 선택하면 그 사실이 묻히게 됩니다.",
  },

  // --- ImportDecisionRow.tsx: MatchRow evidence -----------------------------------
  "activity.decision.match.contains": {
    en: "Contains {overlapping} of this account’s {total} transactions ({pct})",
    ko: "이 계좌의 거래 {total}건 중 {overlapping}건 포함 ({pct})",
  },
  "activity.decision.match.storedHere": {
    en: "{pct} of this file is already stored here",
    ko: "이 파일의 {pct}가 이미 여기 저장되어 있음",
  },
  "activity.decision.match.none": { en: "No transactions in common", ko: "공통 거래 없음" },
  "activity.decision.match.sharedSymbols": {
    en: "{shared} of {incoming} symbols also traded here",
    ko: "{incoming}개 종목 중 {shared}개도 여기서 거래됨",
  },

  // --- ReconcilePanel.tsx: head ----------------------------------------------------
  "activity.reconcile.heading": { en: "Reconcile against your 1099-B", ko: "1099-B와 대사" },
  "activity.reconcile.hide": { en: "Hide", ko: "숨기기" },
  "activity.reconcile.open": { en: "Open", ko: "열기" },
  "activity.reconcile.intro": {
    en: "Everything above comes from replaying broker exports. The 1099-B is what the broker reported to the IRS — the authority. Comparing catches disposals missing from an export.",
    ko: "위의 모든 수치는 증권사 내보내기 파일을 재생하여 계산됩니다. 1099-B는 증권사가 실제로 국세청(IRS)에 신고한 내용입니다. 이 둘을 비교하는 것은 내보내기 파일에서 누락된 매도 건을 잡아내는 단계이며 — 실제 오류를 잡아낼 수 있는 단계이기도 합니다.",
  },
  "activity.reconcile.help": {
    en: "Transcribe 1099-B summary lines below, one per symbol / account / term. Columns: {cols}, optionally {wsd} (box 1g) and {desc}. Term is {short} or {long}; {ex1}/{ex2} both parse. Account must match the disposals table's Account column.",
    ko: "아래에 1099-B의 요약 줄을 종목 / 계좌 / 보유기간별로 한 줄씩 옮겨 적으세요. 열: {cols}, 선택적으로 {wsd}(박스 1g)와 {desc}. 기간(Term)은 {short} 또는 {long}입니다. {ex1}와 {ex2} 모두 인식됩니다. 계좌(Account)는 이 애플리케이션이 사용하는 id여야 합니다 — 위 매도 내역 표의 Account 열을 참고하세요.",
  },
  "activity.reconcile.textareaAriaLabel": { en: "1099-B lines as CSV", ko: "CSV 형식의 1099-B 내역" },

  // --- ReconcilePanel.tsx: run action ------------------------------------------------
  "activity.reconcile.action.running": { en: "Comparing…", ko: "비교하는 중…" },
  "activity.reconcile.action.compare": { en: "Compare against {year}", ko: "{year}년과 비교" },
  "activity.reconcile.action.hint": {
    en: "Nothing is stored. The CSV is compared and discarded.",
    ko: "아무것도 저장되지 않습니다. CSV는 비교 후 버려집니다.",
  },
  "activity.reconcile.error.title": { en: "That CSV could not be read.", ko: "해당 CSV를 읽을 수 없습니다." },
  "activity.reconcile.error.generic": {
    en: "Could not reach the reconcile endpoint.",
    ko: "대사 엔드포인트에 연결할 수 없습니다.",
  },

  // --- ReconcilePanel.tsx: clean result -----------------------------------------------
  "activity.reconcile.clean.title_one": {
    en: "The line you transcribed agrees to the cent.",
    ko: "옮겨 적은 항목이 센트 단위까지 일치합니다.",
  },
  "activity.reconcile.clean.title_other": {
    en: "All {count} lines agree to the cent.",
    ko: "{count}개 항목 모두 센트 단위까지 일치합니다.",
  },
  "activity.reconcile.clean.body_one": {
    en: "That is a result about the {count} line you transcribed, and only those. A disposal absent from both sides — a transaction missing from the export and from what you typed — cannot show up here. Check the line count against the form itself.",
    ko: "이는 옮겨 적은 {count}개 항목에 대한 결과일 뿐입니다. 양쪽 모두에 없는 매도 건 — 내보내기 파일과 입력한 내용 모두에서 누락된 거래 — 은 여기에 나타날 수 없습니다. 항목 수를 서식 자체와 대조해 확인하세요.",
  },
  "activity.reconcile.clean.body_other": {
    en: "That is a result about the {count} lines you transcribed, and only those. A disposal absent from both sides — a transaction missing from the export and from what you typed — cannot show up here. Check the line count against the form itself.",
    ko: "이는 옮겨 적은 {count}개 항목에 대한 결과일 뿐입니다. 양쪽 모두에 없는 매도 건 — 내보내기 파일과 입력한 내용 모두에서 누락된 거래 — 은 여기에 나타날 수 없습니다. 항목 수를 서식 자체와 대조해 확인하세요.",
  },

  // --- ReconcilePanel.tsx: differing result -------------------------------------------
  "activity.reconcile.differ.title_one": {
    en: "{count} line do not agree.",
    ko: "{count}개 항목이 일치하지 않습니다.",
  },
  "activity.reconcile.differ.title_other": {
    en: "{count} lines do not agree.",
    ko: "{count}개 항목이 일치하지 않습니다.",
  },
  "activity.reconcile.differ.body": {
    en: "Total gain difference: {delta} (this application minus the 1099-B). Do not file {year} from the figures above until these are understood.",
    ko: "총 손익 차이: {delta} (이 애플리케이션에서 1099-B를 뺀 값). 이 차이를 이해하기 전에는 위 수치로 {year}년 신고를 하지 마세요.",
  },
  "activity.reconcile.otherMatched_one": {
    en: "{count} other line matched to the cent.",
    ko: "다른 {count}개 항목이 센트 단위까지 일치했습니다.",
  },
  "activity.reconcile.otherMatched_other": {
    en: "{count} other lines matched to the cent.",
    ko: "다른 {count}개 항목이 센트 단위까지 일치했습니다.",
  },

  // --- ReconcilePanel.tsx: result table --------------------------------------------------
  "activity.reconcile.table.term": { en: "Term", ko: "보유기간" },
  "activity.reconcile.table.computedGain": { en: "Computed gain", ko: "계산된 손익" },
  "activity.reconcile.table.formGain": { en: "1099-B gain", ko: "1099-B 손익" },
  "activity.reconcile.table.difference": { en: "Difference", ko: "차이" },
  "activity.reconcile.term.short": { en: "Short", ko: "단기" },
  "activity.reconcile.term.long": { en: "Long", ko: "장기" },

  // --- ReconcilePanel.tsx / api/tax.ts: reconcile status labels ---------------------------
  "activity.reconcile.status.matched": { en: "Matched", ko: "일치" },
  "activity.reconcile.status.amountDiffers": { en: "Amounts differ", ko: "금액 불일치" },
  "activity.reconcile.status.missingFromEngine": { en: "Not in our figures", ko: "우리 계산에 없음" },
  "activity.reconcile.status.missingFrom1099b": { en: "Not on the 1099-B", ko: "1099-B에 없음" },

  // --- api/transactions.ts: action labels not already in common.* ------------------------
  "activity.action.dividend": { en: "Dividend", ko: "배당" },
  "activity.action.interest": { en: "Interest", ko: "이자" },
  "activity.action.lendingIncome": { en: "Lending income", ko: "주식 대여 수익" },
  "activity.action.fee": { en: "Fee", ko: "수수료" },
  "activity.action.subscription": { en: "Subscription", ko: "구독료" },
  "activity.action.transferIn": { en: "Transfer in", ko: "입고" },
  "activity.action.transferOut": { en: "Transfer out", ko: "출고" },
  "activity.action.deposit": { en: "Deposit", ko: "입금" },
  "activity.action.withdrawal": { en: "Withdrawal", ko: "출금" },
  "activity.action.internalTransfer": { en: "Internal transfer", ko: "내부 이체" },
  "activity.action.iraMatch": { en: "IRA match", ko: "IRA 매칭" },
  "activity.action.split": { en: "Split", ko: "분할" },
  "activity.action.spinoff": { en: "Spinoff", ko: "스핀오프" },
  "activity.action.adjustment": { en: "Adjustment", ko: "조정" },
  "activity.action.misc": { en: "Misc", ko: "기타" },

  // --- reconcile note sentences (backend deterministic text; ReconcileLine.note_code maps here) ---
  // The English is byte-identical to the backend's `note` (app/tax/reconcile.py) so English mode
  // reads exactly as before; the code+params contract lets Korean reorder the interpolated symbol
  // and amount. An unmapped code falls back to the raw English `note` in ReconcilePanel.
  "activity.reconcile.note.missingFrom1099b": {
    en: "Computed by the engine but not on the 1099-B for this symbol/account/term -- check it was included on the form.",
    ko: "엔진은 계산했으나 이 종목·계좌·보유 기간에 대해 1099-B에는 없습니다. 양식을 옮겨 적을 때 이 처분이 포함되었는지 확인하세요.",
  },
  "activity.reconcile.note.missingFromEngineGeneric": {
    en: "On the 1099-B but no matching disposal was computed for this symbol/account/term -- likely missing from the import.",
    ko: "1099-B에는 있으나 이 종목·계좌·보유 기간에 대해 일치하는 처분이 계산되지 않았습니다. 이 계좌의 가져온 파일에서 누락된 거래일 가능성이 높습니다.",
  },
  "activity.reconcile.note.missingFromEngineWebull": {
    en: "On the 1099-B but no matching disposal computed for this symbol/account/term. Webull's export is known to omit rows.",
    ko: "1099-B에는 있으나 이 종목·계좌·보유 기간에 대해 일치하는 처분이 계산되지 않았습니다. Webull의 계좌 명세서 내보내기는 일부 거래를 누락하는 것으로 알려져 있습니다.",
  },
  "activity.reconcile.note.amountDiffersWashHigher": {
    en: "Engine basis exceeds 1099-B by the wash-sale disallowed amount (${amount}) for {symbol} -- unapplied or misapplied.",
    ko: "엔진의 취득가가 1099-B보다 양식이 {symbol}에 대해 보고한 워시 세일 불인정 금액(${amount})만큼 정확히 높습니다. 엔진이 이 워시 세일을 적용하지 않았거나 다른 매수 단위에 적용했을 수 있습니다.",
  },
  "activity.reconcile.note.amountDiffersWashLower": {
    en: "Engine basis is below 1099-B by the wash-sale disallowed amount (${amount}) for {symbol} -- unapplied or misapplied.",
    ko: "엔진의 취득가가 1099-B보다 양식이 {symbol}에 대해 보고한 워시 세일 불인정 금액(${amount})만큼 정확히 낮습니다. 엔진이 이 워시 세일을 적용하지 않았거나 다른 매수 단위에 적용했을 수 있습니다.",
  },
} as const satisfies MessageShard;
