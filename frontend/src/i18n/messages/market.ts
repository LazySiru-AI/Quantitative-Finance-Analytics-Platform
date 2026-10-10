/**
 * Institutions, Consensus and Report pages and their API helpers.
 *
 * Keys are prefixed `market.` -- see `catalog.ts` for the convention and why the prefix is
 * load-bearing (the duplicate-key guard in `i18n.test.tsx` keys off it).
 *
 * Sub-prefixed by page (`market.institutions.*`, `market.consensus.*`, `market.report.*`) plus one
 * shared component (`market.holders.*`, for `InstitutionalHolders.tsx`, the reverse "who holds this
 * symbol" lookup). `Institutions.tsx` and `Consensus.tsx` each keep an *independent* copy of a few
 * concepts that happen to read identically today -- the five-way action vocabulary
 * (new/exit/add/trim/hold) and the "this CUSIP matches your ledger" issuer-cell copy -- because the
 * two pages' components already keep independent copies of that logic in English (see each file's
 * own comments) and are not guaranteed to stay coupled. Duplicating the catalog entries matches that
 * existing decision rather than quietly re-coupling the two pages through a shared string.
 */
import type { MessageShard } from "@/i18n/types";

export const market = {
  // ===========================================================================================
  // Institutions page (`pages/Institutions.tsx`) and its API helper (`api/institutions.ts`)
  // ===========================================================================================

  "market.institutions.title": { en: "Institutions", ko: "기관" },
  "market.institutions.subtitle": {
    en: "What 13F filers and NPORT-P ETFs hold, and what changed since their last filing.",
    ko: "13F 보고 기관과 NPORT-P ETF의 보유 현황과 직전 공시 이후 변동 사항입니다.",
  },
  "market.institutions.disclaimer.lead": {
    en: "These are filings, not live positions.",
    ko: "이는 공시 자료이며, 실시간 포지션이 아닙니다.",
  },
  "market.institutions.disclaimer.body": {
    en: "A 13F covers US-listed equities only, as of quarter end, filed ~45 days later. NPORT-P covers everything an ETF owns, filed ~60 days later. Both are history, not today's holdings.",
    ko: "13F는 미국 상장 주식만 다루며, 분기 말 기준으로 약 45일 후 제출됩니다. NPORT-P는 ETF가 보유한 모든 자산을 다루며, 약 60일 후 제출됩니다. 두 공시 모두 과거 기록이며, 오늘의 보유 현황이 아닙니다.",
  },
  "market.institutions.loadingFunds": {
    en: "Loading tracked funds…",
    ko: "추적 중인 펀드 불러오는 중…",
  },
  "market.institutions.emptyFunds": {
    en: "No institutions or funds tracked yet -- a configuration gap, not a report that nothing changed. Nothing fetched yet.",
    ko: "아직 추적 중인 기관이나 펀드가 없습니다. 이는 설정이 되어 있지 않다는 뜻이며, 변경 사항이 없다는 보고가 아닙니다 — 비교할 데이터를 아직 가져오지 않았습니다.",
  },

  // --- translated equivalent of `api/institutions.ts`'s `SOURCE_NOTE` -- that export stays
  // English-only (see this page's `sourceNote` helper for why) so these are the versions actually
  // rendered on screen. -----------------------------------------------------------------------
  "market.institutions.sourceNote.13F": {
    en: "13F: US-listed equities only, as of quarter end, filed ~45 days later. Weights are of this slice, not the whole book.",
    ko: "13F: 미국 상장 주식만 해당하며, 분기 말 기준으로 약 45일 후 제출됩니다. 비중은 이 슬라이스 기준이며 전체 포트폴리오 기준이 아닙니다.",
  },
  "market.institutions.sourceNote.NPORT": {
    en: "NPORT-P: what this ETF held, as of quarter end, filed ~60 days later, covering everything it owns. ETFs don't file 13F.",
    ko: "NPORT-P: 이 ETF가 분기 말 기준으로 실제 보유한 내역이며, 약 60일 후에 제출되고 펀드가 보유한 모든 자산을 다룹니다. ETF는 13F를 제출하지 않습니다.",
  },

  "market.institutions.lookup.label": {
    en: "Which tracked filers hold a symbol?",
    ko: "어떤 추적 보고 기관이 이 종목을 보유하고 있나요?",
  },
  "market.institutions.lookup.ariaLabel": { en: "Symbol to look up", ko: "조회할 종목" },
  "market.institutions.lookup.submit": { en: "Look up", ko: "조회" },
  "market.institutions.lookup.note": {
    en: "Opens the symbol’s page, where the holders panel reads every tracked filer’s latest filing on request.",
    ko: "해당 종목의 페이지를 열며, 그곳의 보유자 패널에서 요청 시 추적 중인 모든 보고 기관의 최신 공시를 조회할 수 있습니다.",
  },

  // --- fetch errors, shared by the funds/holdings/changes fetches on this page ----------------
  "market.institutions.error.upstreamUnreachable": {
    en: "SEC endpoint unreachable ({status}). This is a live fetch, not stored data -- nothing lost. Try again shortly.",
    ko: "SEC 엔드포인트에 연결할 수 없습니다 ({status}). 실시간 조회이며 저장된 데이터가 아니므로 손실은 없습니다 — 잠시 후 다시 시도하세요.",
  },
  "market.institutions.error.apiError": {
    en: "API returned {status}: {message}",
    ko: "API가 {status}을(를) 반환했습니다: {message}",
  },
  "market.institutions.error.cannotReachApi": {
    en: "Cannot reach the API. Is uvicorn running on port 8000? (expected {emptyNoun} data)",
    ko: "API에 연결할 수 없습니다. 8000번 포트에서 uvicorn이 실행 중인가요? ({emptyNoun} 데이터 예상)",
  },
  "market.institutions.noun.noFunds": { en: "no funds", ko: "펀드 없음" },
  "market.institutions.noun.holdings": { en: "holdings", ko: "보유 종목" },
  "market.institutions.noun.changes": { en: "changes", ko: "변동 내역" },

  // --- cross-link to /consensus, the "what are all filers doing" view of the same data ---------
  "market.institutions.crossLink": {
    en: "Want the cross-fund view instead? {link}",
    ko: "전체 기관 동향이 궁금하신가요? {link}",
  },
  "market.institutions.crossLink.linkText": {
    en: "What are all filers doing?",
    ko: "모든 보고 기관은 지금 무엇을 하나요?",
  },

  "market.institutions.fundLabel": { en: "Fund", ko: "펀드" },

  "market.institutions.shape.title": { en: "Portfolio shape", ko: "포트폴리오 구성" },
  "market.institutions.loadingHoldings": {
    en: "Loading holdings…",
    ko: "보유 종목 불러오는 중…",
  },
  "market.institutions.shape.emptyChart": {
    en: "Nothing to chart -- no holdings on record for this fund yet.",
    ko: "차트로 표시할 내용이 없습니다 — 이 펀드의 보유 종목 기록이 아직 없습니다.",
  },

  "market.institutions.changes.title": {
    en: "Changes since last filing",
    ko: "직전 공시 이후 변동 사항",
  },
  "market.institutions.loadingChanges": {
    en: "Loading changes…",
    ko: "변동 내역 불러오는 중…",
  },
  "market.institutions.changes.empty": {
    en: "No comparison yet -- only one filing on record, or this filing added no holdings. Not a report that nothing changed.",
    ko: "아직 비교할 자료가 없습니다 — 공시가 하나뿐이거나 이번 공시에 추가된 보유 종목이 없기 때문입니다. 변동이 없었다는 뜻은 아닙니다.",
  },
  "market.institutions.filter.ownedOnly": {
    en: "Only holdings I also own",
    ko: "내가 보유한 종목만",
  },
  "market.institutions.changes.hideHold": {
    en: "Hide unchanged (hold) positions",
    ko: "변동 없는(유지) 포지션 숨기기",
  },
  "market.institutions.changes.noRowsMatch": {
    en: "No rows match the current filters.",
    ko: "현재 필터와 일치하는 행이 없습니다.",
  },
  // EXP-15 (WCAG 1.3.1): accessible `<caption>` for the Changes table, rendered through
  // `TableCaption` (`@/components/tableSort`). `{count}` is the rows actually rendered right now,
  // after both the owned-only and hide-hold filters -- the same number `CountsStrip`'s own
  // `visible.length` already reflects, not `delta.changes.length`.
  "market.institutions.table.caption.changes": {
    en: "Changes since last filing for {fund}, {count} rows",
    ko: "{fund}의 직전 공시 이후 변동 사항, {count}행",
  },

  // --- table headers, shared by the Changes and Full holdings tables ---------------------------
  "market.institutions.header.issuer": { en: "Issuer", ko: "발행자" },
  "market.institutions.header.identifier": { en: "Identifier", ko: "식별자" },
  "market.institutions.header.action": { en: "Action", ko: "포지션 변동" },
  "market.institutions.header.sharesBefore": { en: "Shares before", ko: "이전 보유 주식 수" },
  "market.institutions.header.sharesAfter": { en: "Shares after", ko: "이후 보유 주식 수" },
  "market.institutions.header.sharesDelta": { en: "Shares Δ", ko: "주식 수 Δ" },
  "market.institutions.header.sharesPctChg": { en: "Shares % chg", ko: "주식 수 변동률" },
  "market.institutions.header.valueDelta": {
    en: "Value Δ (incl. price)",
    ko: "가치 Δ (가격 변동 포함)",
  },
  "market.institutions.header.weightInFiling": { en: "Weight in filing", ko: "공시 내 비중" },
  "market.institutions.weightTooltip.13F": {
    en: "Share of the value disclosed in this 13F -- US-listed equities only, not the manager's whole book or their AUM.",
    ko: "이 13F에 공시된 가치 중 차지하는 비중입니다 -- 미국 상장 주식만 해당하며, 매니저의 전체 포트폴리오나 운용 자산(AUM) 기준이 아닙니다.",
  },
  "market.institutions.weightTooltip.NPORT": {
    en: "Share of the total value disclosed in this filing.",
    ko: "이 공시에 신고된 총 가치 중 차지하는 비중입니다.",
  },

  // Split into an always-visible summary plus an `InfoNote` detail (rather than one long standing
  // paragraph) -- see `OwnershipCaveat` in `Institutions.tsx`.
  "market.institutions.ownershipCaveat.summary": {
    en: "Matched by CUSIP -- an unflagged row may still be one you own.",
    ko: "CUSIP으로 매칭됩니다 — 표시되지 않은 행도 보유 중일 수 있습니다.",
  },
  "market.institutions.ownershipCaveat.detail": {
    en: "Only one of three broker imports carries CUSIPs, so an unflagged row means {noCusipMatch}, not non-ownership.",
    ko: "세 증권사 가져오기 중 한 곳만 CUSIP을 제공하므로, 표시되지 않은 행은 {noCusipMatch}을(를) 의미할 뿐 미보유를 뜻하지 않습니다.",
  },
  "market.institutions.noCusipMatch": { en: "no CUSIP match", ko: "CUSIP 불일치" },

  "market.institutions.changes.filterNote": {
    en: "Filters hide {hidden} of {total} positions; {shown} shown. Each tile's second number is the filer's own total.",
    ko: "필터로 인해 전체 {total}개 포지션 중 {hidden}개가 숨겨져 있으며, {shown}개가 표시됩니다. 각 타일의 두 번째 숫자는 보고 기관 자체의 합계입니다.",
  },

  // --- the five-way action vocabulary, an independent copy of Consensus's own below -------------
  "market.institutions.action.new": { en: "New", ko: "신규 편입" },
  "market.institutions.action.exit": { en: "Exit", ko: "전량 매도" },
  "market.institutions.action.add": { en: "Add", ko: "추가 매수" },
  "market.institutions.action.trim": { en: "Trim", ko: "축소" },
  "market.institutions.action.hold": { en: "Hold", ko: "유지" },

  // The `InfoNote` summary line (renamed from `.intro`) -- see `TradedTogetherNote`.
  "market.institutions.tradedNote.summary": {
    en: "Across the {traded} positions this filer traded, the median share change was {median}.",
    ko: "이 보고 기관이 거래한 {traded}개 포지션 전체에서, 주식 수 변동의 중앙값은 {median}이었습니다.",
  },
  "market.institutions.tradedNote.nport": {
    en: "Uniform moves reflect fund size or index changes, not a view on any name. {weight} moves only relative to the book.",
    ko: "포지션이 함께 움직이면 규모 변화나 지수 재구성이지 종목에 대한 견해가 아닙니다. {weight}만 나머지 대비 상대적으로 움직입니다.",
  },
  "market.institutions.tradedNote.13F": {
    en: "Scattered changes mean the manager acted on individual names; a cluster means the whole book was scaled at once.",
    ko: "이를 표에 나타난 분포와 비교해 보세요 — 매니저가 개별 종목에 대해 판단해 움직이면 변화가 흩어져 나타나고, 하나의 수치 주변에 몰려 있다면 전체 포트폴리오가 한 번에 조정되었다는 뜻입니다.",
  },

  "market.institutions.provenance": {
    en: "{fromPeriod} (accession {fromAccession}) vs {toPeriod} (accession {toAccession}). Total value {before} → {after}.",
    ko: "{fromPeriod} (accession {fromAccession})와(과) {toPeriod} (accession {toAccession})를 비교합니다. 보고된 총 가치 {before} → {after}.",
  },

  "market.institutions.issuerCell.title": {
    en: "This CUSIP matches something in your own ledger. Opens this symbol's page.",
    ko: "이 CUSIP은 회원님의 원장에 있는 항목과 일치합니다. 이 종목의 페이지를 엽니다.",
  },
  "market.institutions.issuerCell.ariaLabel": {
    en: "{ticker}, a position you also own — open {ticker}'s page",
    ko: "{ticker}, 회원님이 보유한 포지션입니다 — {ticker} 페이지 열기",
  },
  "market.institutions.issuerCell.badge": {
    en: "{ticker} · you own this",
    ko: "{ticker} · 보유 중",
  },

  "market.institutions.holdings.title": { en: "Full holdings", ko: "전체 보유 종목" },
  "market.institutions.holdings.provenance_one": {
    en: "As of {period}, filed {filed} (accession {accession}). Total reported value {value} across {count} holding.",
    ko: "{period} 기준, {filed} 제출 (accession {accession}). 보고된 총 가치 {value}, 보유 종목 {count}개.",
  },
  "market.institutions.holdings.provenance_other": {
    en: "As of {period}, filed {filed} (accession {accession}). Total reported value {value} across {count} holdings.",
    ko: "{period} 기준, {filed} 제출 (accession {accession}). 보고된 총 가치 {value}, 보유 종목 {count}개.",
  },
  "market.institutions.holdings.rescaledLead": {
    en: "Values rescaled ×1,000.",
    ko: "가치를 ×1,000으로 환산했습니다.",
  },
  "market.institutions.holdings.rescaledBody": {
    en: "Filer stated values in thousands despite 2023's whole-dollar rule -- this app's correction, not the filer's disclosure.",
    ko: "이 보고 기관은 2023년 전체 달러 표기 규정에도 값을 천 단위로 기재했습니다 — 이는 앱의 보정이며 보고 기관의 공시가 아닙니다.",
  },
  // EXP-15 (WCAG 1.3.1): accessible `<caption>` for the Full holdings table -- `{count}` is the rows
  // actually rendered right now, after the owned-only and issuer-text filters, matching
  // `FilterBar`'s own `shown` count for this table.
  "market.institutions.table.caption.holdings": {
    en: "Full holdings for {fund}, {count} rows",
    ko: "{fund}의 전체 보유 종목, {count}행",
  },
  "market.institutions.holdings.empty": {
    en: "No holdings on record for this fund yet.",
    ko: "이 펀드의 보유 종목 기록이 아직 없습니다.",
  },
  "market.institutions.holdings.filterNote": {
    en: "Filter hides {hidden} of {total} holdings; {shown} shown. Provenance above describes the whole filing, not this view.",
    ko: "필터로 인해 전체 {total}개 보유 종목 중 {hidden}개가 숨겨져 있으며, {shown}개가 표시됩니다. 위의 근거 정보 줄은 필터가 적용된 이 화면이 아니라 공시 전체를 설명합니다.",
  },
  "market.institutions.holdings.noMatch": {
    en: "No holdings match the current filter.",
    ko: "현재 필터와 일치하는 보유 종목이 없습니다.",
  },

  // ===========================================================================================
  // Consensus page (`pages/Consensus.tsx`) and its API helper (`api/consensus.ts`)
  // ===========================================================================================

  // --- the five-way action vocabulary, kept independent of Institutions's copy above -----------
  "market.consensus.action.new": { en: "New", ko: "신규 편입" },
  "market.consensus.action.exit": { en: "Exit", ko: "전량 매도" },
  "market.consensus.action.add": { en: "Add", ko: "추가 매수" },
  "market.consensus.action.trim": { en: "Trim", ko: "축소" },
  "market.consensus.action.hold": { en: "Hold", ko: "유지" },

  "market.consensus.error.upstreamUnreachable": {
    en: "SEC endpoint unreachable ({status}). This is a live fetch, not stored data -- nothing lost. Try again shortly.",
    ko: "SEC 엔드포인트에 연결할 수 없습니다 ({status}). 실시간 조회이며 저장된 데이터가 아니므로 손실은 없습니다 — 잠시 후 다시 시도하세요.",
  },
  "market.consensus.error.apiError": {
    en: "API returned {status}: {message}",
    ko: "API가 {status}을(를) 반환했습니다: {message}",
  },
  "market.consensus.error.cannotReachApi": {
    en: "Cannot reach the API. Is uvicorn running on port 8000?",
    ko: "API에 연결할 수 없습니다. 8000번 포트에서 uvicorn이 실행 중인가요?",
  },

  "market.consensus.title": { en: "Consensus", ko: "컨센서스" },
  "market.consensus.subtitle": {
    en: "Who's buying and selling now, ranked by how many tracked funds agree.",
    ko: "지금 매수·매도 중인 대상을, 같은 방향으로 움직인 추적 펀드 수 기준으로 순위 매김.",
  },
  "market.consensus.disclaimer.lead": {
    en: "These are filings, not live trading activity.",
    ko: "이는 공시 자료이며, 실시간 거래 활동이 아닙니다.",
  },
  "market.consensus.disclaimer.body": {
    en: "A 13F covers US-listed equities only, as of quarter end, filed ~45 days later. NPORT-P covers everything an ETF owns, filed ~60 days later. Both are history, not today's activity.",
    ko: "13F는 미국 상장 주식만 다루며, 분기 말 기준으로 약 45일 후 제출됩니다. NPORT-P는 ETF가 보유한 모든 자산을 다루며, 약 60일 후 제출됩니다. 두 공시 모두 과거 기록이며, 오늘의 거래 활동이 아닙니다.",
  },
  "market.consensus.loading": { en: "Loading consensus…", ko: "컨센서스 불러오는 중…" },
  "market.consensus.noun.filers": { en: "filers", ko: "보고 기관" },
  "market.consensus.empty": {
    en: "No consensus moves this run -- every checked fund held steady or couldn't be compared. See counts above.",
    ko: "이번 실행에서는 컨센서스 움직임이 없습니다 — 확인된 펀드가 모두 유지되었거나 비교할 수 없었습니다. 위의 수치를 참고하세요.",
  },

  "market.consensus.tabs.ariaLabel": { en: "Consensus direction", ko: "컨센서스 방향" },
  "market.consensus.tabs.buying": { en: "Buying", ko: "매수" },
  "market.consensus.tabs.selling": { en: "Selling", ko: "매도" },

  // --- provenance strip: one full sentence per (as_of present?) x (unchecked present?) combo ----
  "market.consensus.provenance.base": {
    en: "Generated {generatedAt}. Checked {checkedOfTotal} tracked funds.",
    ko: "{generatedAt}에 생성됨. 추적 대상 펀드 중 {checkedOfTotal}개 확인함.",
  },
  "market.consensus.provenance.withAsOf": {
    en: "Generated {generatedAt} as of {asOf}. Checked {checkedOfTotal} tracked funds.",
    ko: "{generatedAt}에 생성됨 ({asOf} 기준). 추적 대상 펀드 중 {checkedOfTotal}개 확인함.",
  },
  "market.consensus.provenance.withUnchecked": {
    en: "Generated {generatedAt}. Checked {checkedOfTotal} funds; {uncheckedCount} not comparable, excluded below.",
    ko: "{generatedAt}에 생성됨. {checkedOfTotal}개 펀드 확인, {uncheckedCount}개는 비교 불가로 아래에서 제외됨.",
  },
  "market.consensus.provenance.withAsOfAndUnchecked": {
    en: "Generated {generatedAt}, as of {asOf}. Checked {checkedOfTotal} funds; {uncheckedCount} not comparable, excluded below.",
    ko: "{generatedAt}에 생성됨 ({asOf} 기준). {checkedOfTotal}개 펀드 확인, {uncheckedCount}개는 비교 불가로 아래에서 제외됨.",
  },

  "market.consensus.uncheckedTitle": {
    en: "Unchecked funds ({count})",
    ko: "미확인 펀드 ({count}개)",
  },

  "market.consensus.table.mostBought": { en: "Most bought", ko: "가장 많이 매수됨" },
  "market.consensus.table.mostSold": { en: "Most sold", ko: "가장 많이 매도됨" },
  "market.consensus.table.denominator": {
    en: "Counts are out of {checkedCount} funds checked this run, not the full universe. See provenance for who was skipped.",
    ko: "아래 수치는 이번 실행에서 확인된 {checkedCount}개 펀드 기준이며, 전체 추적 대상이 아닙니다. 제외된 펀드는 위의 근거 정보를 참고하세요.",
  },
  // EXP-15 (WCAG 1.3.1): accessible `<caption>` for the buys/sells ranked table -- `{heading}` is
  // already `market.consensus.table.mostBought`/`mostSold` (whichever this render is), so the
  // caption and the on-screen `<h2>` never disagree about which ranking this table shows.
  // `{count}` is the rows actually rendered right now, after the issuer/ticker text filter.
  "market.consensus.table.caption": {
    en: "{heading}, {count} rows",
    ko: "{heading}, {count}행",
  },
  "market.consensus.table.noBuyConsensus": {
    en: "No buy consensus this run.",
    ko: "이번 실행에서는 매수 컨센서스가 없습니다.",
  },
  "market.consensus.table.noSellConsensus": {
    en: "No sell consensus this run.",
    ko: "이번 실행에서는 매도 컨센서스가 없습니다.",
  },
  "market.consensus.header.rank": { en: "Rank", ko: "순위" },
  "market.consensus.header.issuer": { en: "Issuer", ko: "발행자" },
  "market.consensus.header.fundsBuying": { en: "Funds buying", ko: "매수 기관 수" },
  "market.consensus.header.fundsSelling": { en: "Funds selling", ko: "매도 기관 수" },
  "market.consensus.header.weightDeltaSummed": {
    en: "Weight Δ (summed)",
    ko: "비중 Δ (합산)",
  },

  "market.consensus.moversTitle": { en: "Movers ({count})", ko: "움직인 기관 ({count}개)" },
  "market.consensus.mover.tooltip13F": {
    en: "13F: US-listed equities only, filed ~45 days after quarter end.",
    ko: "13F: 미국 상장 주식만 해당하며, 분기 말 이후 약 45일 후에 제출됩니다.",
  },
  "market.consensus.mover.tooltipNport": {
    en: "NPORT-P: the fund's whole book, filed ~60 days after quarter end.",
    ko: "NPORT-P: 펀드의 전체 포트폴리오이며, 분기 말 이후 약 60일 후에 제출됩니다.",
  },
  "market.consensus.mover.asOf": { en: "as of {period}", ko: "{period} 기준" },

  "market.consensus.issuerCell.title": {
    en: "This CUSIP matches something in your own ledger. Opens this symbol's page.",
    ko: "이 CUSIP은 회원님의 원장에 있는 항목과 일치합니다. 이 종목의 페이지를 엽니다.",
  },
  "market.consensus.issuerCell.ariaLabel": {
    en: "{ticker} — open {ticker}'s page",
    ko: "{ticker} — {ticker} 페이지 열기",
  },

  // --- cross-link to /institutions, for a reader who wants one filer instead of the cross-fund
  // ranking this page shows -----------------------------------------------------------------
  "market.consensus.crossLink": {
    en: "Looking for one filer instead? {link}",
    ko: "특정 보고 기관을 찾으시나요? {link}",
  },
  "market.consensus.crossLink.linkText": {
    en: "Look up a filer",
    ko: "보고 기관 조회",
  },

  // ===========================================================================================
  // Institutional holders panel (`components/InstitutionalHolders.tsx`) -- the reverse "who
  // holds this symbol" lookup, embedded on the ticker page but out of this shard's own page split.
  // ===========================================================================================

  "market.holders.title": { en: "Institutional holders", ko: "기관 보유자" },
  "market.holders.askButton": {
    en: "Which tracked filers hold {symbol}?",
    ko: "어떤 추적 보고 기관이 {symbol}을(를) 보유하고 있나요?",
  },
  "market.holders.coverage": {
    en: "{checked} of {total} filers checked",
    ko: "전체 {total}개 중 {checked}개 보고 기관 확인함",
  },
  "market.holders.costNote": {
    en: "Reads each filer's latest 13F or N-PORT from SEC -- seconds if cached, up to a minute if not. Runs only on request.",
    ko: "SEC에서 추적 중인 모든 보고 기관의 최신 13F 또는 N-PORT를 조회합니다. 캐시된 경우 몇 초, 그렇지 않으면 최대 1분까지 걸릴 수 있습니다 — 그래서 요청할 때만 실행됩니다.",
  },
  "market.holders.loadingFor": {
    en: "Reading every tracked filer’s latest filing for {symbol}. This can take up to a minute the first time.",
    ko: "{symbol}에 대한 추적 중인 모든 보고 기관의 최신 공시를 조회하는 중입니다. 처음에는 최대 1분까지 걸릴 수 있습니다.",
  },

  "market.holders.unresolved.lead": {
    en: "{symbol} could not be matched to a CUSIP.",
    ko: "{symbol}을(를) CUSIP과 매칭할 수 없습니다.",
  },
  "market.holders.unresolved.body": {
    en: "Filings identify positions by CUSIP; this app maps CUSIPs to tickers from your own transaction history — a symbol you've never traded won't appear here even if filers hold it. Not evidence nobody holds {symbol}.",
    ko: "공시는 포지션을 CUSIP으로 식별하며, 이 앱은 회원님의 거래 내역을 기준으로 CUSIP을 종목 코드에 매핑합니다 — 따라서 한 번도 거래하지 않은 종목은 보고 기관이 실제로 보유하고 있어도 여기서 찾을 수 없습니다. 이는 아무도 {symbol}을(를) 보유하고 있지 않다는 증거가 아닙니다.",
  },

  "market.holders.partial.lead": {
    en: "{unreadable} of {total} filers could not be read.",
    ko: "전체 {total}개 중 {unreadable}개 보고 기관을 읽을 수 없었습니다.",
  },
  "market.holders.partial.body": {
    en: "Anything below is only what the {checked} readable filings say.",
    ko: "아래 내용은 읽을 수 있었던 {checked}건의 공시에 나온 내용일 뿐입니다.",
  },

  "market.holders.empty.resolved": {
    en: "No tracked filer disclosed a position in {symbol} in its latest filing.",
    ko: "최신 공시에서 {symbol}에 대한 포지션을 신고한 추적 보고 기관이 없습니다.",
  },
  "market.holders.empty.unresolved": {
    en: 'No position found — but see the note above before reading that as "nobody holds it".',
    ko: '포지션을 찾을 수 없습니다 — 다만 이를 "아무도 보유하고 있지 않다"는 뜻으로 읽기 전에 위의 안내를 확인하세요.',
  },

  "market.holders.header.filer": { en: "Filer", ko: "보고 기관" },
  "market.holders.header.disclosedAs": { en: "Disclosed as", ko: "공시명" },
  "market.holders.header.period": { en: "Period", ko: "기간" },

  "market.holders.rescaledBadge.label": { en: "rescaled", ko: "단위 환산됨" },
  "market.holders.rescaledBadge.title": {
    en: "Reported in thousands and scaled up here -- this app's judgement, not a figure the filer disclosed.",
    ko: "이 공시는 값을 천 단위로 보고했으며 이를 확대 환산했습니다 — 이는 보고 기관의 데이터에 대한 판단이며, 그들이 공시한 수치가 아닙니다.",
  },

  "market.holders.uncheckedSummary": {
    en: "{count} filer(s) could not be read",
    ko: "{count}개 보고 기관을 읽을 수 없었습니다",
  },

  "market.holders.error.unreachable": {
    en: "Could not reach the filings service.",
    ko: "공시 서비스에 연결할 수 없습니다.",
  },
  "market.holders.error.invalidSymbol": {
    en: "{symbol} is not a symbol this lookup accepts. Check the ticker and try again.",
    ko: "{symbol}은(는) 이 조회에서 허용하는 종목이 아닙니다. 종목 코드를 확인한 뒤 다시 시도하세요.",
  },
  "market.holders.error.missingEndpoint": {
    en: "This build is asking for an endpoint the running backend does not have — the server may need restarting.",
    ko: "이 빌드는 실행 중인 백엔드에 존재하지 않는 엔드포인트를 요청하고 있습니다 — 서버를 재시작해야 할 수 있습니다.",
  },
  "market.holders.error.serviceFailed": {
    en: "The filings service failed while reading SEC. It may be rate-limited or temporarily down; try again shortly.",
    ko: "공시 서비스가 SEC를 읽는 도중 실패했습니다. 요청 제한에 걸렸거나 일시적으로 다운되었을 수 있습니다 — 잠시 후 다시 시도하세요.",
  },
  "market.holders.error.otherStatus": {
    en: "The filings service returned {status}.",
    ko: "공시 서비스가 {status}을(를) 반환했습니다.",
  },

  // ===========================================================================================
  // Report page (`pages/Report.tsx`) and its API helper (`api/report.ts`)
  // ===========================================================================================

  "market.report.title": { en: "Report", ko: "리포트" },
  "market.report.subtitle": {
    en: "Narrative case for one holding: prose, drawdown, decisions, backtest vs buy-and-hold.",
    ko: "한 종목에 대한 서술형 근거: 검증된 서술, 낙폭·의사결정, 매수 후 보유 대비 백테스트.",
  },
  "market.report.symbolPlaceholder": { en: "SYMBOL", ko: "종목 코드" },
  "market.report.go": { en: "Go", ko: "이동" },
  "market.report.noSymbolYet": {
    en: "No symbol yet. Try one of these:",
    ko: "아직 종목이 없습니다. 다음 중 하나를 시도해 보세요:",
  },
  "market.report.intervalAriaLabel": { en: "Interval", ko: "봉 간격" },
  "market.report.loadingFor": {
    en: "Loading report for {symbol}…",
    ko: "{symbol}의 리포트 불러오는 중…",
  },
  "market.report.exportMarkdown": { en: "Export Markdown", ko: "마크다운 내보내기" },
  "market.report.nameUnavailable": { en: "Name unavailable", ko: "이름 확인 불가" },
  "market.report.warningsTitle": { en: "Warnings", ko: "경고" },

  // --- `MarketWarning.kind` pill labels (`ReportWarnings` / `DrawdownPanel` in Report.tsx) --------
  // `stale` reuses the shared `ui.pill.stale` label rather than a copy of the same word here.
  // Duplicated from `Macro.tsx`/`Ticker.tsx`'s own copies of this same mapping rather than shared --
  // see either shard's comment for why.
  "market.warningKind.providerFallback": { en: "Provider fallback", ko: "대체 공급자 사용" },
  "market.warningKind.clamped": { en: "Clamped", ko: "값 보정됨" },
  "market.warningKind.shortHistory": { en: "Short history", ko: "짧은 이력" },
  "market.warningKind.partialBar": { en: "Partial bar", ko: "미완성 봉" },
  "market.warningKind.gap": { en: "Data gap", ko: "데이터 공백" },
  "market.warningKind.other": { en: "Notice", ko: "알림" },

  "market.report.sampleLabel": { en: "Sample", ko: "표본" },

  "market.report.drawdown.title": {
    en: "Drawdown profile ({basis} basis)",
    ko: "낙폭 프로필 ({basis} 기준)",
  },
  "market.report.drawdown.bars": { en: "Bars", ko: "봉 수" },
  "market.report.drawdown.episodesConsidered": {
    en: "Episodes considered",
    ko: "검토된 구간 수",
  },
  "market.report.drawdown.noEpisodes": {
    en: "No drawdown episodes found for {symbol}.",
    ko: "{symbol}에 대한 낙폭 구간을 찾을 수 없습니다.",
  },
  "market.report.drawdown.header.peak": { en: "Peak", ko: "고점" },
  "market.report.drawdown.header.trough": { en: "Trough", ko: "저점" },
  "market.report.drawdown.header.depth": { en: "Depth", ko: "낙폭" },
  "market.report.drawdown.header.barsToTrough": { en: "Bars to trough", ko: "저점까지 봉 수" },
  "market.report.drawdown.header.recovery": { en: "Recovery", ko: "회복" },
  "market.report.drawdown.header.underwater": { en: "Underwater", ko: "미회복 상태" },
  "market.report.drawdown.barsCount": { en: "{count} bars", ko: "{count}봉" },

  "market.report.decisions.title": { en: "Decision table summary", ko: "의사결정 표 요약" },
  "market.report.decisions.subtitle": {
    en: "Current rule states with their 20-bar edge over the unconditional baseline.",
    ko: "현재 규칙 상태와 무조건부 기준선 대비 20봉 엣지입니다.",
  },
  "market.report.decisions.barsEvaluated": { en: "Bars evaluated", ko: "평가된 봉 수" },
  "market.report.decisions.rulesFiringNow": { en: "Rules firing now", ko: "현재 발동 중인 규칙" },
  "market.report.decisions.noRules": {
    en: "No rules evaluated for this symbol.",
    ko: "이 종목에 대해 평가된 규칙이 없습니다.",
  },
  "market.report.decisions.header.rule": { en: "Rule", ko: "규칙" },
  "market.report.decisions.header.state": { en: "State", ko: "상태" },
  "market.report.decisions.header.edge20b": { en: "20b edge", ko: "20봉 엣지" },
  "market.report.decisions.hitRateVsBaseline": {
    en: "{hitRate} vs {baseline}",
    ko: "{hitRate} 대 {baseline}",
  },

  // --- useReport.ts fetch-failure fallbacks (shown on the Report page's error/empty state) --------
  "market.report.noReport": {
    en: 'No report for "{symbol}" at {interval}.',
    ko: "{symbol}의 {interval} 리포트가 없습니다.",
  },
  "market.report.noStrategyResult": {
    en: 'No strategy result for "{symbol}".',
    ko: "{symbol}의 전략 결과가 없습니다.",
  },
} as const satisfies MessageShard;
