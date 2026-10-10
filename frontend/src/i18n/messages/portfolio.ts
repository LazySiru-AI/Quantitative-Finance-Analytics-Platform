/**
 * Portfolio page, holdings table and portfolio API helpers.
 *
 * Keys are prefixed `portfolio.` -- see `catalog.ts` for the convention and for why the prefix
 * is load-bearing rather than cosmetic.
 *
 * A handful of sentences here vary along an English grammar axis (singular/plural "position(s)",
 * "has/have", "is/are") that Korean does not have. Rather than reassembling those sentences from
 * word fragments at the call site -- which is exactly the concatenation this system exists to
 * forbid -- each grammatical shape gets its own full-sentence key (`_one`/`_other`, or a small
 * enumerated set like `_1_1`/`_n_1`/`_n_n` where two independent counts are both in play). The
 * Korean side of every variant reads identically, because Korean has no plural inflection to vary.
 */
import type { MessageShard } from "@/i18n/types";

export const portfolio = {
  // --- page header / status -------------------------------------------------
  // `Account` -- not `Portfolio` -- per the accounts-status shard: the section rail now says
  // "Account" too (`nav.section.portfolio.label`; the section id stays `portfolio`), and the page
  // item and this page's own `<h1>` were renamed once "account status" (open/closed) became a real
  // concept the page has to show.
  "portfolio.title": { en: "Account", ko: "계좌" },
  "portfolio.subtitle": {
    en: "Holdings reconstructed from brokerage transaction history.",
    ko: "증권사 거래 내역을 바탕으로 재구성한 보유 종목입니다.",
  },
  "portfolio.stat.accounts": { en: "Accounts", ko: "계좌" },
  "portfolio.stat.accountsHint": { en: "{open} open", ko: "{open}개 사용 중" },
  "portfolio.stat.instruments": { en: "Instruments", ko: "종목" },
  "portfolio.stat.imports": { en: "Imports", ko: "가져오기" },
  "portfolio.stat.transactions": { en: "Transactions", ko: "거래" },
  "portfolio.stat.accountsFunded": { en: "Accounts funded", ko: "자금이 있는 계좌" },
  "portfolio.loadingPortfolio": { en: "Loading portfolio…", ko: "포트폴리오 불러오는 중…" },
  "portfolio.apiError": {
    en: "API returned {status}: {message}",
    ko: "API가 {status}을(를) 반환했습니다: {message}",
  },
  "portfolio.cannotReachApi": {
    en: "Cannot reach the API. Is uvicorn running on port 8000?",
    ko: "API에 연결할 수 없습니다. 8000번 포트에서 uvicorn이 실행 중인가요?",
  },

  // --- empty state -----------------------------------------------------------
  "portfolio.empty.noOpenPositions": {
    en: "No open positions as of {asOf}. Every lot in the ledger has been fully disposed of.",
    ko: "{asOf} 기준으로 보유 중인 포지션이 없습니다. 원장의 모든 매수 단위가 전량 처분되었습니다.",
  },
  // `{dataDir}`/`{activityLink}` carry the literal `data/` path and the (still-English, out of this
  // shard's scope) Activity nav link -- see the module docstring in `Portfolio.tsx`.
  "portfolio.empty.noLedger": {
    en: "No positions yet. Copy exports into {dataDir}; import from {activityLink} — Robinhood, Webull, SoFi auto-detect.",
    ko: "보유 종목이 없습니다. 내보내기 파일을 {dataDir}에 복사한 뒤 {activityLink}에서 가져오세요 — Robinhood, Webull, SoFi 자동 인식.",
  },

  // --- partial-totals caveat --------------------------------------------------
  // Two independent counts (total positions, unpriced positions) drive English grammar; the only
  // valid combinations are both-one, total-many/unpriced-one, and both-many (unpriced <= total).
  "portfolio.partialCaveat.headline_1_1": {
    en: "Totals below are PARTIAL — {unpriced} of {total} position has no price and is excluded: {list}.",
    ko: "아래 합계는 부분 합계입니다 — 전체 {total}개 종목 중 {unpriced}개에 가격이 없어 제외되었습니다: {list}.",
  },
  "portfolio.partialCaveat.headline_n_1": {
    en: "Totals below are PARTIAL — {unpriced} of {total} positions has no price and is excluded: {list}.",
    ko: "아래 합계는 부분 합계입니다 — 전체 {total}개 종목 중 {unpriced}개에 가격이 없어 제외되었습니다: {list}.",
  },
  "portfolio.partialCaveat.headline_n_n": {
    en: "Totals below are PARTIAL — {unpriced} of {total} positions have no price and are excluded: {list}.",
    ko: "아래 합계는 부분 합계입니다 — 전체 {total}개 종목 중 {unpriced}개에 가격이 없어 제외되었습니다: {list}.",
  },
  "portfolio.partialCaveat.detail": {
    en: "Those positions still hold real shares with a real cost basis — listed separately at the bottom of the table below — but contribute nothing to the market value or unrealized gain/loss above until priced.",
    ko: "해당 종목들도 실제 보유 주식과 실제 취득가를 가지고 있습니다 — 아래 포지션 표 맨 아래에 별도로 나열되어 있습니다 — 다만 가격이 확인되기 전까지는 위의 평가 금액이나 미실현 손익 수치에 전혀 반영되지 않습니다.",
  },

  // --- settlement clause (summary tile and per-account cash tile) -----------
  "portfolio.cash.clearsOne": { en: "clears {date}", ko: "{date}에 정산" },
  "portfolio.cash.clearsRange": { en: "clears {next} → {full}", ko: "{next} → {full}에 정산" },
  "portfolio.cash.settledUnsettled": {
    en: "{settled} settled · {unsettled} unsettled",
    ko: "{settled} 정산 완료 · {unsettled} 미정산",
  },
  "portfolio.cash.declaredAsOf": { en: "declared as of {date}", ko: "{date} 기준 신고" },
  "portfolio.cash.accountsExcluded_one": {
    en: "{count} account excluded",
    ko: "{count}개 계좌 제외",
  },
  "portfolio.cash.accountsExcluded_other": {
    en: "{count} accounts excluded",
    ko: "{count}개 계좌 제외",
  },

  // --- totals panel ------------------------------------------------------------
  "portfolio.totals.asOfNothingPriced": {
    en: "Positions as of {asOf} — nothing is priced, so no market value is stated.",
    ko: "{asOf} 기준 포지션입니다 — 가격이 확인된 종목이 없어 평가 금액을 표시하지 않습니다.",
  },
  "portfolio.totals.asOfSingle": {
    en: "Ledger as of {asOf} · priced at the close of {latest}",
    ko: "{asOf} 기준 원장 · {latest} 종가 기준",
  },
  "portfolio.totals.asOfRange": {
    en: "Ledger as of {asOf} · prices span {range} — totals below mix {distinct} different pricing dates",
    ko: "{asOf} 기준 원장 · {range} 종가 기준으로 혼재 · 아래 평가 금액과 미실현 손익 합계는 서로 다른 {distinct}개의 기준일이 섞여 있습니다",
  },
  "portfolio.totals.downloadStatement": { en: "Download statement", ko: "명세서 다운로드" },

  // --- tiles (Totals panel, AccountCard, TaxGroupSection all reuse these) ----
  "portfolio.tile.costBasis": { en: "Cost basis", ko: "취득가" },
  "portfolio.tile.marketValue": { en: "Market value", ko: "평가 금액" },
  "portfolio.tile.marketValuePartial": { en: "Market value (partial)", ko: "평가 금액 (부분)" },
  "portfolio.tile.cashPartial": { en: "Cash (partial)", ko: "현금 (부분)" },
  "portfolio.tile.totalEquity": { en: "Total equity", ko: "자산 총액" },
  "portfolio.tile.unrealizedGainLoss": { en: "Unrealized gain/loss", ko: "미실현 손익" },
  "portfolio.tile.unrealizedGainLossPartial": {
    en: "Unrealized gain/loss (partial)",
    ko: "미실현 손익 (부분)",
  },
  "portfolio.tile.unrealized": { en: "Unrealized", ko: "미실현" },
  "portfolio.tile.unrealizedPartial": { en: "Unrealized (partial)", ko: "미실현 (부분)" },
  "portfolio.tile.pricedHint": { en: "{count} priced", ko: "{count}개 가격 확인" },
  "portfolio.tile.pricedOfHint": {
    en: "{priced} of {total} priced",
    ko: "전체 {total}개 중 {priced}개 가격 확인",
  },
  "portfolio.tile.accountsOfHint": {
    en: "{n} of {total} accounts",
    ko: "전체 {total}개 중 {n}개 계좌",
  },
  "portfolio.tile.totalEquityHintComplete": { en: "positions + cash", ko: "포지션 + 현금" },
  "portfolio.tile.totalEquityHintIncomplete": {
    en: "unavailable — see the caveats above",
    ko: "표시할 수 없음 — 위의 주의 사항을 확인하세요",
  },

  // --- small shared counters (reused across totals, cards and groups) --------
  "portfolio.count.position_one": { en: "{count} position", ko: "{count}개 종목" },
  "portfolio.count.position_other": { en: "{count} positions", ko: "{count}개 종목" },
  "portfolio.count.account_one": { en: "{count} account", ko: "{count}개 계좌" },
  "portfolio.count.account_other": { en: "{count} accounts", ko: "{count}개 계좌" },

  // --- totals detail row -------------------------------------------------------
  "portfolio.summary.positionCount": { en: "Position count", ko: "포지션 수" },
  "portfolio.summary.positionCountDetail": {
    en: "{total} ({unpriced} unpriced)",
    ko: "{total}개 ({unpriced}개 미가격)",
  },
  "portfolio.summary.largestPosition": { en: "Largest position", ko: "최대 비중 종목" },

  // --- cash caveat --------------------------------------------------------------
  "portfolio.cashCaveat.headline_singularNull": {
    en: "Cash is unavailable for {excluded} of {total} account, so no cash total and no equity figure can be shown.",
    ko: "전체 {total}개 계좌 중 {excluded}개 계좌의 현금을 확인할 수 없어, 현금 합계와 자산 총액을 표시할 수 없습니다.",
  },
  "portfolio.cashCaveat.headline_singularPartial": {
    en: "Cash is unavailable for {excluded} of {total} account, so the cash total is PARTIAL and no equity figure can be shown.",
    ko: "전체 {total}개 계좌 중 {excluded}개 계좌의 현금을 확인할 수 없어, 현금 합계가 부분 합계이며 자산 총액을 표시할 수 없습니다.",
  },
  "portfolio.cashCaveat.headline_pluralNull": {
    en: "Cash is unavailable for {excluded} of {total} accounts, so no cash total and no equity figure can be shown.",
    ko: "전체 {total}개 계좌 중 {excluded}개 계좌의 현금을 확인할 수 없어, 현금 합계와 자산 총액을 표시할 수 없습니다.",
  },
  "portfolio.cashCaveat.headline_pluralPartial": {
    en: "Cash is unavailable for {excluded} of {total} accounts, so the cash total is PARTIAL and no equity figure can be shown.",
    ko: "전체 {total}개 계좌 중 {excluded}개 계좌의 현금을 확인할 수 없어, 현금 합계가 부분 합계이며 자산 총액을 표시할 수 없습니다.",
  },
  "portfolio.cashCaveat.footer": {
    en: "Withheld, not estimated — a guess would look just as confident as a real balance, with no way to tell them apart.",
    ko: "잔액은 추정하지 않고 보류합니다 — 이를 뒷받침하지 못하는 내보내기 파일로 억지로 계산하면 구체적이고 확신에 찬, 그러나 틀린 숫자가 나올 수 있고, 화면상으로는 실제 값과 구분할 방법이 없기 때문입니다.",
  },
  // Density UAT: each row used to render its full (backend-generated, often long) `reason`
  // sentence inline. Now a short visible tag with the sentence itself moved into the row's own
  // InfoNote disclosure -- see `CashCaveat` in `Portfolio.tsx`.
  "portfolio.cashCaveat.reasonTag": { en: "cash withheld", ko: "현금 보류" },

  // --- cash by account -----------------------------------------------------------
  "portfolio.cashByAccount.title": { en: "Cash by account", ko: "계좌별 현금" },
  "portfolio.cashByAccount.derivedWord": { en: "derived", ko: "산출된" },
  "portfolio.cashByAccount.declaredWord": { en: "declared", ko: "신고된" },
  // Density UAT: these were two permanent `<p>` paragraphs under the table; now both live as the
  // `children` of one InfoNote whose visible summary is `.notesSummary`.
  "portfolio.cashByAccount.notesSummary": { en: "What derived / declared mean", ko: "산출 / 신고의 의미" },
  "portfolio.cashByAccount.derivedNote": {
    en: "{derived}: summed from ledger cash movements over the window shown — may not span the account's whole history.",
    ko: "{derived} 잔액: 표시된 기간의 원장 현금 변동 합산값입니다 — 계좌 개설 이후 전체 기간이 아닐 수 있습니다.",
  },
  "portfolio.cashByAccount.declaredNote": {
    en: "{declared}: read off the broker on the date shown, not computed. Frozen — never updates or flags staleness. In {code}.",
    ko: "{declared} 잔액: 표시된 날짜에 증권사에서 확인한 값으로, 계산되지 않습니다. 스냅샷이라 갱신되지 않으며 {code}에 저장됩니다.",
  },

  // --- cash source (per-row "where this figure came from") -----------------------
  "portfolio.cashSource.declared": { en: "declared {date}", ko: "신고일 {date}" },
  "portfolio.cashSource.noDate": { en: "(no date)", ko: "(날짜 없음)" },
  "portfolio.cashSource.disagreeTitle": {
    en: "The ledger and the declared figure disagree.",
    ko: "원장과 신고된 수치가 일치하지 않습니다.",
  },
  "portfolio.cashSource.ledgerDerives": { en: "ledger derives {amount}", ko: "원장 산출값 {amount}" },
  "portfolio.cashSource.derivedRange": {
    en: "derived {start} → {end}",
    ko: "산출 기간 {start} → {end}",
  },
  "portfolio.accountCash.noData": {
    en: "no cash data for this account",
    ko: "이 계좌의 현금 데이터 없음",
  },

  // --- table headers, reused across the positions/cash/breakdown tables ----------
  "portfolio.header.account": { en: "Account", ko: "계좌" },
  "portfolio.header.broker": { en: "Broker", ko: "증권사" },
  "portfolio.header.settled": { en: "Settled", ko: "정산 완료" },
  "portfolio.header.unsettled": { en: "Unsettled", ko: "미정산" },
  "portfolio.header.balance": { en: "Balance", ko: "잔액" },
  "portfolio.header.lots": { en: "Lots", ko: "매수 단위" },
  "portfolio.header.flags": { en: "Flags", ko: "플래그" },
  "portfolio.header.kind": { en: "Kind", ko: "유형" },
  "portfolio.header.example": { en: "Example", ko: "예시" },
  "portfolio.header.quantityStLt": { en: "Quantity (ST / LT)", ko: "수량 (단기/장기)" },
  "portfolio.header.accountBreakdown": { en: "Account breakdown", ko: "계좌별 내역" },
  "portfolio.header.deferredLoss": { en: "Deferred loss", ko: "이연 손실" },

  // --- sector badge editor (double-click a sector badge to change it) ----------------------------
  "portfolio.sectorEditor.doubleClickHint": {
    en: "Double-click to change sector",
    ko: "더블클릭하면 섹터를 변경할 수 있습니다",
  },
  "portfolio.sectorEditor.selectLabel": { en: "Sector for {symbol}", ko: "{symbol}의 섹터" },
  "portfolio.sectorEditor.saving": { en: "Saving…", ko: "저장 중…" },
  "portfolio.sectorEditor.saveError": {
    en: "Could not save — try again.",
    ko: "저장하지 못했습니다 — 다시 시도하세요.",
  },

  // --- deferred wash-sale loss (By tax treatment view only) -------------------------------------
  // `deferred_disallowed` and `permanently_disallowed` (`@/api/washsales`) must never be summed --
  // see that module's docstring. This column and tile render `deferred_disallowed` alone; the
  // permanent figure has no home on this page.
  "portfolio.tile.deferredLoss": { en: "Deferred loss", ko: "이연 손실" },
  "portfolio.tile.deferredLoss.hint": {
    en: "Sum across this group's held symbols",
    ko: "이 그룹이 보유한 종목 합계",
  },
  "portfolio.washCaveat.unavailable": {
    en: "Wash-sale data unavailable — the deferred-loss figures above could not be loaded.",
    ko: "워시 세일 데이터를 불러올 수 없어 위의 이연 손실 수치를 표시할 수 없습니다.",
  },
  "portfolio.washCaveat.neverSummedSummary": {
    en: "Deferred vs. permanently disallowed — never summed",
    ko: "이연 손실과 영구 불인정 손실 — 합산하지 않음",
  },
  "portfolio.washCaveat.neverSummed.detail": {
    en: "Deferred loss is added to a replacement lot's basis and comes back when that lot is sold. Permanently disallowed loss (an IRA replacement) never comes back, on any sale or date. They answer different questions, so they are never summed.",
    ko: "이연 손실은 대체 매수 단위의 취득가에 더해져 그 단위를 매도하면 돌아옵니다. 영구 불인정 손실(IRA 대체 매수)은 어떤 매도나 날짜로도 돌아오지 않습니다. 서로 다른 질문에 답하므로 하나로 합산하지 않습니다.",
  },
  "portfolio.washCaveat.retirementNotDeductible": {
    en: "Capital losses in a retirement account aren't deductible at all, so no deferred-loss column applies here.",
    ko: "은퇴 계좌의 자본 손실은 애초에 공제 대상이 아니므로 이연 손실 열이 적용되지 않습니다.",
  },
  "portfolio.washColumn.windowOpenTitle": {
    en: "Repurchase window open until {date}",
    ko: "{date}까지 재매수 제한 기간",
  },

  // --- badges and their titles (positions table, account rows, breakdown) --------
  "portfolio.badge.uncertainBasis": { en: "uncertain basis", ko: "취득가 불확실" },
  "portfolio.badge.feesUnknown": { en: "fees unknown", ko: "수수료 미상" },
  "portfolio.badge.boundNotExact": { en: "bound, not exact", ko: "상한값, 정확한 값 아님" },
  "portfolio.badge.boundNotExactTitle": {
    en: "Basis uncertain -- this figure is a bound, never understating a loss or overstating a gain, not an exact estimate.",
    ko: "이 포지션은 취득가가 불확실합니다 -- 이 수치는 상한값이며(손실을 과소평가하거나 반대로 이익을 과대평가하는 일은 없습니다), 정확한 추정치가 아닙니다.",
  },
  // Cross-link (UX refactor 3.3): the basis-uncertain badge above states the problem; this one is a
  // real navigation link to where the gap actually shows up as a dollar figure -- the Tax page's
  // Disposals tab. Same badge class, same warn colour, no new CSS.
  "portfolio.badge.uncertainBasisLink": { en: "see disposals", ko: "처분 내역 보기" },
  "portfolio.badge.uncertainBasisLinkTitle": {
    en: "See this position's disposals on the Tax page for basis detail",
    ko: "이 포지션의 취득가 관련 처분 내역을 세금 페이지에서 확인하세요",
  },

  // --- positions table -------------------------------------------------------------
  "portfolio.positions.title": { en: "Positions", ko: "포지션" },
  "portfolio.positions.none": { en: "No positions.", ko: "보유 종목이 없습니다." },
  // Plain text now (a `SortHeader` label is a string, not JSX) -- the "(of invested)" gloss that used
  // to be inlined via `<Trans>` moved to `weightNote`, now used as the header's hover `title` instead.
  "portfolio.positions.header.weight": { en: "Weight", ko: "비중" },
  "portfolio.positions.header.weightNote": { en: "Share of invested (priced) market value", ko: "투자(가격 확인) 자산 대비 비중" },
  "portfolio.header.sector": { en: "Sector", ko: "섹터" },
  "portfolio.header.dayChange": { en: "Today", ko: "당일" },
  "portfolio.header.dayChangePct": { en: "Today %", ko: "당일 %" },
  "portfolio.header.unrealizedPct": { en: "Unrealized %", ko: "미실현 %" },
  "portfolio.positions.asOf": { en: "as of {date}", ko: "{date} 기준" },
  "portfolio.positions.unpricedSeparator": {
    en: "Unpriced — no market data, excluded from the totals above",
    ko: "가격 미확인 — 시세 데이터 없음, 위 합계에서 제외됨",
  },
  "portfolio.positions.unpricedSeparatorAccount": {
    en: "Unpriced — no market data, excluded from this account's totals above",
    ko: "가격 미확인 — 시세 데이터 없음, 이 계좌의 합계에서 제외됨",
  },
  "portfolio.positions.unpricedSeparatorGroup": {
    en: "Unpriced — no market data, excluded from this group's totals above",
    ko: "가격 미확인 — 시세 데이터 없음, 이 그룹의 합계에서 제외됨",
  },
  "portfolio.positions.hideBreakdown": {
    en: "Hide account breakdown for {symbol}",
    ko: "{symbol}의 계좌별 내역 숨기기",
  },
  "portfolio.positions.showBreakdown": {
    en: "Show account breakdown for {symbol}",
    ko: "{symbol}의 계좌별 내역 보기",
  },
  "portfolio.positions.hideLabel": { en: "hide", ko: "숨기기" },
  "portfolio.positions.acctCount_one": { en: "{count} acct", ko: "{count}개 계좌" },
  "portfolio.positions.acctCount_other": { en: "{count} accts", ko: "{count}개 계좌" },
  "portfolio.accountsBreakdown.caption": {
    en: "Per-account breakdown for {symbol}",
    ko: "{symbol}의 계좌별 내역",
  },
  // EXP-15 (WCAG 1.3.1): accessible `<caption>`s for this page's three positions tables, rendered
  // through `TableCaption` (`@/components/tableSort`). `{count}` is always the rows actually
  // rendered right now (after the table's own filter), never the unfiltered total -- a caption that
  // announced a stale count would mislead a screen-reader user exactly the way a stale "showing N of
  // M" note would a sighted one.
  "portfolio.table.caption.byInstrument": {
    en: "Positions by instrument, {count} rows, across all accounts",
    ko: "종목별 포지션, {count}행, 전체 계좌 기준",
  },
  // Shared by the By-account panel and each By-tax-treatment group's table
  // (`AccountPositionsTable.tsx`) -- `{label}` is the same already-translated "{account or group} —
  // Positions" string each caller builds for that table's `ScrollRegion` name, so the caption and the
  // scroll region agree on what to call the table rather than keeping two independent descriptions.
  "portfolio.table.caption.scoped": {
    en: "{label}, {count} rows",
    ko: "{label}, {count}행",
  },
  "portfolio.table.caption.closedAccounts": {
    en: "Closed accounts, {count} rows",
    ko: "해지된 계좌, {count}행",
  },

  // --- warnings section --------------------------------------------------------------
  // Trimmed for the collapsed-by-default box (`WarningsSection` in `Portfolio.tsx`): this is now
  // the ONLY text visible before the reader expands the box, so the "grouped below by kind and
  // account" clause -- which described content that no longer renders until expanded anyway -- was
  // cut rather than carried into a headline that has to justify its own length at a glance.
  "portfolio.warnings.headline_one": {
    en: "{count} basis/fee gap the replay could not resolve.",
    ko: "재구성 과정에서 해소하지 못한 취득가/수수료 공백 {count}건.",
  },
  "portfolio.warnings.headline_other": {
    en: "{count} basis/fee gaps the replay could not resolve.",
    ko: "재구성 과정에서 해소하지 못한 취득가/수수료 공백 {count}건.",
  },
  "portfolio.warnings.showAll": {
    en: "Show all {count} individual warnings",
    ko: "개별 경고 {count}건 모두 보기",
  },
  "portfolio.warnings.toggleAriaLabel": {
    en: "Show or hide the warnings breakdown and chart",
    ko: "경고 세부 내역과 차트 표시/숨기기",
  },
  // A11Y-03: accessible name for the warning-groups table's own scroll region (not wrapped in the
  // shared `ScrollRegion` component -- see that div's own comment in `WarningsSection.tsx`).
  "portfolio.warnings.groupsTableRegionLabel": {
    en: "Warnings by kind and account",
    ko: "유형 및 계좌별 경고",
  },

  // --- warnings chart (WarningsChart.tsx, mounted only while the warnings box is expanded) -------
  "portfolio.warningsChart.ariaLabel_one": {
    en: "Warning counts by kind and account, {count} kind",
    ko: "유형 및 계좌별 경고 건수, {count}개 유형",
  },
  "portfolio.warningsChart.ariaLabel_other": {
    en: "Warning counts by kind and account, {count} kinds",
    ko: "유형 및 계좌별 경고 건수, {count}개 유형",
  },
  "portfolio.warningsChart.empty": { en: "No warnings to chart.", ko: "차트로 표시할 경고가 없습니다." },
  "portfolio.warningsChart.topSymbolsTitle": { en: "Most-flagged symbols", ko: "가장 많이 표시된 종목" },
  "portfolio.warningsChart.noSymbols": {
    en: "None of these warnings name a specific symbol.",
    ko: "특정 종목을 지목한 경고가 없습니다.",
  },

  // --- positions view toggle ----------------------------------------------------------
  "portfolio.positionsView.ariaLabel": { en: "Positions view", ko: "포지션 보기" },
  "portfolio.tabs.byInstrument": { en: "By instrument", ko: "종목별" },
  "portfolio.tabs.byAccount": { en: "By account", ko: "계좌별" },
  "portfolio.tabs.byTaxTreatment": { en: "By tax treatment", ko: "과세 구분별" },
  // Shortened for the density UAT (prose-budget pass): the visible summary is now a label, and
  // the full "why" -- including the wash-sale/concentration clause that used to be the visible
  // sentence -- lives behind the InfoNote's disclosure in `.note.more`.
  "portfolio.positionsView.note": {
    en: "By instrument = risk view",
    ko: "종목별 = 리스크 보기",
  },
  "portfolio.positionsView.note.more": {
    en: 'Wash-sale rules and concentration apply across every account, not one. "By account" shows which broker\'s cash and tax figures to trust. "By tax treatment" splits taxable vs. retirement — how much is never taxed on exit.',
    ko: '워시 세일과 집중도는 특정 계좌가 아니라 보유한 모든 계좌에 걸쳐 적용됩니다. "계좌별"은 어느 증권사의 현금·과세 수치를 신뢰할지 답합니다. "과세 구분별"은 과세 대상과 은퇴 계좌로 나눠, 인출 시점까지 과세되지 않는 비중을 보여줍니다.',
  },

  // --- by-account view -------------------------------------------------------------------
  "portfolio.accountsView.noneSelected": {
    en: "No accounts are selected. Tick an account above to bring its card back.",
    ko: "선택된 계좌가 없습니다. 위에서 계좌를 체크하면 카드가 다시 표시됩니다.",
  },
  "portfolio.accountsView.chooserTitle": { en: "Accounts shown", ko: "표시할 계좌" },
  "portfolio.accountCard.empty": {
    en: "No positions in this account.",
    ko: "이 계좌에는 보유 종목이 없습니다.",
  },
  "portfolio.warningCount_one": { en: "{count} warning", ko: "경고 {count}건" },
  "portfolio.warningCount_other": { en: "{count} warnings", ko: "경고 {count}건" },

  // --- tax treatment (account badge) and tax group (view heading) ------------------------
  "portfolio.taxTreatment.taxable": { en: "Taxable", ko: "과세 대상" },
  "portfolio.taxTreatment.rothIra": {
    en: "Roth IRA — gains never taxed",
    ko: "로스 IRA — 이익 비과세",
  },
  "portfolio.taxTreatment.traditionalIra": {
    en: "Traditional IRA — tax-deferred",
    ko: "전통 IRA — 과세 이연",
  },
  "portfolio.taxTreatment.unknown": { en: "Tax treatment unknown", ko: "과세 구분 알 수 없음" },
  "portfolio.taxGroup.taxable": { en: "Taxable", ko: "과세 대상" },
  "portfolio.taxGroup.retirement": { en: "Retirement (IRA)", ko: "은퇴 계좌 (IRA)" },
  "portfolio.taxGroup.empty": {
    en: "No positions in this group.",
    ko: "이 그룹에는 보유 종목이 없습니다.",
  },
  // Short visible label for the InfoNote wrapping `.note` below (density UAT: this used to be a
  // bare always-on `<p>`) -- `.note` itself is unchanged in content, now rendered as the note's
  // `children` instead.
  // --- tax-treatment scope control (allocation pie above the two groups) -----------------
  "portfolio.taxTreatment.scope.ariaLabel": { en: "Scope", ko: "범위" },
  "portfolio.taxTreatment.scope.all": { en: "All", ko: "전체" },
  "portfolio.taxTreatment.scope.allAccounts": { en: "All accounts", ko: "전체 계좌" },
  "portfolio.taxTreatment.summary": { en: "Taxable vs. retirement — kept apart", ko: "과세 대상과 은퇴 계좌 — 구분 유지" },
  "portfolio.taxTreatment.note": {
    en: "IRA gains aren't taxed (or not yet) — merging them with taxable gain misstates both, so this view keeps them apart.",
    ko: "IRA 이익은 (아직) 과세되지 않아 과세 대상 이익과 합치면 둘 다 잘못 표시됩니다 — 실제 세금 경계이므로 이 보기는 둘을 구분합니다.",
  },
  "portfolio.taxTreatment.unknownAccounts_one": {
    en: "{countLabel} has no matching cash-by-account entry, so tax treatment is unknown — excluded below: {list}.",
    ko: "{countLabel}는 포지션은 있지만 계좌별 현금에 일치하는 항목이 없어 과세 구분을 알 수 없으므로, 추측해서 넣는 대신 아래 두 그룹 모두에서 제외했습니다: {list}.",
  },
  "portfolio.taxTreatment.unknownAccounts_other": {
    en: "{countLabel} have no matching cash-by-account entry, so tax treatment is unknown — excluded below: {list}.",
    ko: "{countLabel}는 포지션은 있지만 계좌별 현금에 일치하는 항목이 없어 과세 구분을 알 수 없으므로, 추측해서 넣는 대신 아래 두 그룹 모두에서 제외했습니다: {list}.",
  },

  // --- uncertainty summary ----------------------------------------------------------------
  // Density UAT: these used to render as always-on full sentences. Now a short visible headline
  // (count stays visible) plus the explanatory clause behind an InfoNote's disclosure.
  "portfolio.uncertainty.basis.headline": { en: "{countBold} basis uncertain", ko: "{countBold}개 취득가 불확실" },
  "portfolio.uncertainty.basis.detail": {
    en: "Gain/loss is a bound, only overstated, never understated. See badges below.",
    ko: "손익은 상한값이라 과대평가만 가능하고 과소평가는 없습니다. 아래 배지를 참고하세요.",
  },
  "portfolio.uncertainty.feesUnknown.headline": { en: "{countBold} fees unknown", ko: "{countBold}개 수수료 미상" },
  "portfolio.uncertainty.feesUnknown.detail": {
    en: 'Source export has no fee column, independent of basis. See "fees unknown" badges below.',
    ko: '수수료 열이 없는 내보내기 파일에서 비롯되었으며, 이는 취득가 문제와는 별개입니다. 아래 "수수료 미상" 배지를 참고하세요.',
  },

  // --- PanelBoundary labels --------------------------------------------------------
  // Passed to `PanelBoundary`, which now renders them *inside* a Korean sentence ("… 패널을 표시할
  // 수 없습니다"). An English label there would read as a mixed-language fragment, so the label is
  // translated at the call site -- the "prop stays a prop, translate at the caller" rule.
  "portfolio.panel.partialTotals": { en: "Partial-totals caveat", ko: "부분 합계 주의" },
  "portfolio.panel.cashCaveat": { en: "Cash caveat", ko: "현금 주의" },
  // The four caveat panels above (`portfolio.panel.partialTotals`, `.cashCaveat`, `.uncertainty`,
  // `.closedAccounts`) folded into one `CaveatStrip` panel -- this is that panel's own
  // `PanelBoundary` label. The four keys above stay: nothing was deleted, and `.closedAccounts`
  // still names the account-rail Closed tab's own heading (see `ByAccountView.tsx`).
  "portfolio.panel.caveats": { en: "Caveats", ko: "주의 사항" },
  "portfolio.panel.totals": { en: "Totals", ko: "합계" },
  "portfolio.panel.uncertainty": { en: "Uncertainty summary", ko: "불확실성 요약" },
  "portfolio.panel.warnings": { en: "Warnings", ko: "경고" },
  "portfolio.panel.positions": { en: "Positions", ko: "포지션" },
  "portfolio.panel.cashByAccount": { en: "Cash by account", ko: "계좌별 현금" },
  "portfolio.panel.closedAccounts": { en: "Closed accounts", ko: "해지된 계좌" },

  // --- account status (new concept: open/closed) ------------------------------------
  "portfolio.status.closed": { en: "Closed", ko: "해지됨" },

  // --- account picker (By account view) ----------------------------------------------
  "portfolio.accountPicker.label": { en: "Account", ko: "계좌" },
  "portfolio.accountPicker.openGroup": { en: "Open", ko: "사용 중" },
  "portfolio.accountPicker.closedGroup": { en: "Closed", ko: "해지됨" },
  "portfolio.accountPicker.allOption": { en: "All open accounts", ko: "사용 중 계좌 전체" },
  // The account rail's trailing tab, shown only when at least one account is closed -- see
  // `ByAccountView.tsx`'s `FOLDER_TAB_MAX` branch and its `ClosedAccountsPanel`.
  "portfolio.accountPicker.closedTab": { en: "Closed ({count})", ko: "해지됨 ({count})" },

  // --- closed-account exclusion note (positions dropped because their account closed) ----
  // Pluralization fix (density UAT): the lazy "(s)" form is gone, one full-sentence key per
  // grammatical shape, matching this file's `_one`/`_other` convention elsewhere.
  "portfolio.closed.note_one": {
    en: "{count} position excluded — closed account: {list}",
    ko: "해지된 계좌로 제외된 포지션 {count}개: {list}",
  },
  "portfolio.closed.note_other": {
    en: "{count} positions excluded — closed account: {list}",
    ko: "해지된 계좌로 제외된 포지션 {count}개: {list}",
  },
  // Reworded (functional fix): the picker no longer lists closed accounts at all (they have no
  // positions to show -- the backend never sends a closed account's holdings), so the old "select
  // the account by name in 'By account' to see them" was a false promise. Realized history for a
  // closed account is still real and still visible, just not through this page's positions view.
  "portfolio.closed.note.more": {
    en: "Closed accounts' holdings are excluded from current holdings because the account is closed. Their realized history remains on the Tax and Activity pages.",
    ko: "해지된 계좌의 보유 종목은 계좌가 해지되었기 때문에 현재 보유 종목에서 제외됩니다. 실현 손익 이력은 세금 및 거래 내역 페이지에 남아 있습니다.",
  },

  // --- allocation pie (By account view) ------------------------------------------------
  "portfolio.alloc.title": { en: "Allocation", ko: "자산 배분" },
  // Used as an aria-label on the pie's wrapper, naming whichever mode is active -- the visible mode
  // toggle already reads "By ticker"/"By sector" (`misc.alloc.modeTicker`/`modeSector`, owned by
  // `AllocationPie.tsx` itself), so these two exist for the region's accessible name, not as new
  // visible prose.
  "portfolio.alloc.byTicker": { en: "By ticker", ko: "종목별" },
  "portfolio.alloc.bySector": { en: "By sector", ko: "섹터별" },
  "portfolio.alloc.cashSlice": { en: "Cash", ko: "현금" },
  // Pluralization fix (density UAT): dropped the lazy "(s)" form.
  "portfolio.alloc.unpricedNote_one": {
    en: "{count} unpriced position excluded",
    ko: "가격 미확인 포지션 {count}개 제외",
  },
  "portfolio.alloc.unpricedNote_other": {
    en: "{count} unpriced positions excluded",
    ko: "가격 미확인 포지션 {count}개 제외",
  },

  // --- Today / Accumulated totals tiles ------------------------------------------------
  "portfolio.tile.dayChange": { en: "Today", ko: "당일" },
  "portfolio.tile.accumulated": { en: "Accumulated", ko: "누적 손익" },
  "portfolio.tile.accumulated.hint": { en: "Realized + unrealized", ko: "실현 + 미실현" },
  // Per-account panel gains a Realized tile (functional fix 2) -- the account's all-time
  // `AccountSummary.realized_gain`, distinct from the page-level Accumulated tile above.
  "portfolio.tile.realized": { en: "Realized", ko: "실현 손익" },
  "portfolio.tile.realized.hint": { en: "All-time", ko: "전체 기간" },

  // --- positions table filter bar (By instrument / By account / By tax treatment) ------
  "portfolio.filter.symbolPlaceholder": { en: "Filter symbol", ko: "종목 검색" },
  "portfolio.filter.sectorAll": { en: "All sectors", ko: "전체 섹터" },
  // Accessible name for the sector `<select>` itself (A11Y-05) -- distinct from the "All sectors"
  // option label above, which is the in-list choice, not the control's own name.
  "portfolio.filter.sectorLabel": { en: "Filter by sector", ko: "섹터로 필터" },
  // Region aria-label for the scrollable table wrapper -- `FilterBar` itself already renders a
  // visible "Showing N of M" note (`ui.table.filterShowing`), so this is not duplicate visible prose,
  // only the accessible name for the scroll region around the table.
  "portfolio.filter.note": { en: "Showing {shown} of {total}", ko: "{total}개 중 {shown}개 표시" },
  "portfolio.sort.ariaLabel": { en: "Sort by {column}", ko: "{column} 기준 정렬" },
} as const satisfies MessageShard;
