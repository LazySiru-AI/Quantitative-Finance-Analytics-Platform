/**
 * Tax and Wash Sales pages and their API helpers.
 *
 * Keys are prefixed `tax.` -- see `catalog.ts` for the convention and why the prefix is
 * load-bearing (the duplicate-key guard in `i18n.test.tsx` keys off it).
 *
 * A handful of sentences here vary along an English grammar axis Korean does not have
 * (singular/plural "disposal(s)", a below/above word choice, a loss/gain word choice). Per this
 * project's rule against reassembling a sentence from fragments at the call site, each shape gets
 * its own full-sentence key rather than a template with a raw-English fragment spliced in. The
 * Korean side of every plural variant reads identically, because Korean has no plural inflection.
 *
 * The "Activity" link text inside the empty-year messages is deliberately left in English -- it is
 * a nav label owned by `nav.ts`, out of this shard's scope, matching `portfolio.empty.noLedger`'s
 * own note for the identical link in `Portfolio.tsx`.
 *
 * Identifiers are left untranslated per this project's rule: "Box A"..."Box F" (Form 8949 box
 * designators), "Form 8949" itself, and lot-method tokens like `FIFO`.
 */
import type { MessageShard } from "@/i18n/types";

export const tax = {
  // --- Tax page: header -----------------------------------------------------------------------
  "tax.title": { en: "Tax", ko: "세금" },
  "tax.subtitle": {
    en: "US cost basis across every account. Wash-sale rule applies across all, even other brokers.",
    ko: "모든 계좌에 걸친 미국 취득가 계산. 워시 세일 규정은 다른 증권사를 포함한 모든 계좌에 함께 적용됩니다.",
  },

  // --- shared disclaimer (bold lead sentence + rest, two catalog entries because Korean cannot
  //     glue a second sentence onto the end of the first the way English can) -------------------
  //
  // ONE body for both the Tax page and the Wash Sales page. The Wash Sales page carried its own
  // near-copy (`tax.washSales.disclaimerBody`) that differed in a single word -- "Detection
  // replays…" against "The engine replays…" -- which is COPY-STYLE.md rule 2's "one explanation per
  // fact, app-wide" broken in the least visible way possible: two sentences a reader cannot tell
  // apart, that can now drift apart. Deleted in favour of this key. The visible short form is
  // `tax.disclaimer.title`, and both pages render it behind the same `ui.pill.notAdvice` pill --
  // COPY-STYLE.md rule 6: "not tax advice" is shortened, never hidden.
  "tax.disclaimer.title": {
    en: "Calculation only, not tax advice.",
    ko: "계산 결과이며 세무 자문이 아닙니다.",
  },
  "tax.disclaimer.body": {
    en: "Reconcile every figure below against your actual 1099-B forms before filing. The engine replays your brokerage history from transaction exports; it does not see what your broker actually reported to the IRS.",
    ko: "제출 전에 아래의 모든 수치를 실제 1099-B 서식과 대조하세요. 이 엔진은 거래 내역 내보내기 파일로부터 증권사 이력을 재구성한 것이며, 증권사가 실제로 국세청(IRS)에 보고한 내용을 확인하지는 않습니다.",
  },

  // --- Tax page: loading / year selector -------------------------------------------------------
  "tax.loading.initial": {
    en: "Loading tax report…",
    ko: "세금 보고서 불러오는 중…",
  },
  "tax.loading.year": {
    en: "Loading {year} tax report…",
    ko: "{year}년 세금 보고서 불러오는 중…",
  },
  "tax.yearSelect.label": { en: "Tax year", ko: "과세 연도" },

  // --- tab rail (Tax page) -- Summary / Disposals / Wash sales / Form 8949 ---------------------
  "tax.tabs.label": { en: "Tax report sections", ko: "세금 보고서 섹션" },
  "tax.tabs.summary": { en: "Summary", ko: "요약" },
  "tax.tabs.disposals": { en: "Disposals", ko: "처분 내역" },
  "tax.tabs.wash": { en: "Wash sales", ko: "워시 세일" },
  "tax.tabs.f8949": { en: "Form 8949", ko: "Form 8949" },

  // --- shared API-failure strings ---------------------------------------------------------------
  "tax.error.apiError": {
    en: "API returned {status}: {message}",
    ko: "API가 {status}을(를) 반환했습니다: {message}",
  },
  "tax.error.cannotReachApi": {
    en: "Cannot reach the API. Is uvicorn running on port 8000?",
    ko: "API에 연결할 수 없습니다. 8000번 포트에서 uvicorn이 실행 중인가요?",
  },

  // --- empty-year messages ------------------------------------------------------------------
  // `{dataDir}`/`{activityLink}` carry the literal `data/` path and the (still-English, out of this
  // shard's scope) Activity nav link -- see the module docstring above.
  "tax.empty.notImported": {
    en: "Nothing imported. Copy broker exports into {dataDir} and import from {activityLink}. Absence of data, not zero gains.",
    ko: "아직 아무것도 가져오지 않았습니다. 증권사 내보내기 파일을 {dataDir}에 복사한 뒤 {activityLink}에서 가져오세요. 데이터 부재이지 이익 0의 보고가 아닙니다.",
  },
  "tax.empty.noYearActivity": {
    en: "No {year} activity — {count} transactions, none this tax year. Absence of data, not zero gains; pick another year.",
    ko: "{year}년 활동 없음 — 원장의 거래 {count}건 중 이 연도에 해당하는 건 없습니다. 데이터 부재이지 이익 0의 보고가 아닙니다. 다른 연도를 선택하세요.",
  },
  "tax.empty.nothingDisposed_one": {
    en: "Nothing disposed in {year}. {count} transaction, no lot sold — no gain/loss, no Form 8949. See {activityLink}.",
    ko: "{year}년 처분 내역 없음. 이 연도 거래 {count}건 중 매도된 매수 단위가 없어 — {activityLink} 참고 — 보고할 손익도, 제출할 Form 8949도 없습니다.",
  },
  "tax.empty.nothingDisposed_other": {
    en: "Nothing disposed in {year}. {count} transactions, no lot sold — no gain/loss, no Form 8949. See {activityLink}.",
    ko: "{year}년 처분 내역 없음. 이 연도 거래 {count}건 중 매도된 매수 단위가 없어 — {activityLink} 참고 — 보고할 손익도, 제출할 Form 8949도 없습니다.",
  },

  // --- panel labels/headings (PanelBoundary `label` and the panel's own <h2>, deliberately the
  //     same key: the two must always name the panel the same way) -----------------------------
  "tax.panel.uncertainBasisCaveat": {
    en: "Uncertain-basis caveat",
    ko: "취득가 불확실성 주의",
  },
  "tax.panel.summary": { en: "Summary", ko: "요약" },
  "tax.panel.warnings": { en: "Warnings", ko: "경고" },
  "tax.panel.disposals": { en: "Disposals", ko: "처분 내역" },
  "tax.panel.washSalesBySymbol": {
    en: "Wash sales by symbol",
    ko: "종목별 워시 세일",
  },
  "tax.panel.washSales": { en: "Wash sales", ko: "워시 세일" },
  "tax.panel.unsettledClassifications": {
    en: "Unsettled classifications",
    ko: "미확정 분류",
  },
  "tax.panel.form8949": { en: "Form 8949", ko: "Form 8949" },
  "tax.panel.reconcile": { en: "Reconcile", ko: "대조" },

  // --- shared table headers (reused wherever the same English word labels a column) -------------
  "tax.header.sold": { en: "Sold", ko: "매도" },
  "tax.header.acquired": { en: "Acquired", ko: "취득" },
  "tax.header.qty": { en: "Qty", ko: "수량" },
  "tax.header.lotMethod": { en: "Lot / method", ko: "매수 단위 / 방식" },
  "tax.header.term": { en: "Term", ko: "구분" },
  "tax.header.proceeds": { en: "Proceeds", ko: "매도 금액" },
  "tax.header.costBasis": { en: "Cost basis", ko: "취득가" },
  "tax.header.gainLoss": { en: "Gain/loss", ko: "손익" },
  "tax.header.account": { en: "Account", ko: "계좌" },
  "tax.header.kind": { en: "Kind", ko: "유형" },
  "tax.header.example": { en: "Example", ko: "예시" },
  "tax.header.deferred": { en: "Deferred", ko: "이연" },
  "tax.header.permanentlyDisallowed": {
    en: "Permanently disallowed",
    ko: "영구 불인정",
  },
  "tax.header.lossSales": { en: "Loss sales", ko: "손실 매도" },
  "tax.header.lastLossSale": { en: "Last loss sale", ko: "최근 손실 매도일" },
  "tax.header.repurchaseStatus": { en: "Repurchase status", ko: "재매수 상태" },
  "tax.header.accounts": { en: "Accounts", ko: "계좌" },
  "tax.header.qtyReplacedSold": {
    en: "Qty replaced / sold",
    ko: "재매수 / 매도 수량",
  },
  "tax.header.loss": { en: "Loss", ko: "손실" },
  "tax.header.disallowed": { en: "Disallowed", ko: "불인정" },
  "tax.header.treatment": { en: "Treatment", ko: "처리" },
  "tax.header.saleDate": { en: "Sale date", ko: "매도일" },
  "tax.header.replacement": { en: "Replacement", ko: "대체 종목" },
  "tax.header.lossAtStake": { en: "Loss at stake", ko: "관련 손실액" },
  "tax.header.ifIdentical": {
    en: "If substantially identical",
    ko: "실질적으로 동일한 경우",
  },
  "tax.header.ifDistinct": { en: "If distinct", ko: "별개인 경우" },
  "tax.header.rationale": { en: "Rationale", ko: "근거" },
  "tax.header.description": { en: "Description", ko: "설명" },
  "tax.header.code": { en: "Code", ko: "코드" },
  "tax.header.adjustment": { en: "Adjustment", ko: "조정액" },
  "tax.header.qtySold": { en: "Qty sold", ko: "매도 수량" },
  "tax.header.qtyReplaced": { en: "Qty replaced", ko: "재매수 수량" },
  "tax.header.replacementAccounts": {
    en: "Replacement account(s)",
    ko: "재매수 계좌",
  },
  "tax.header.windowCloses": { en: "Window closes", ko: "기간 종료일" },

  // --- shared badges -------------------------------------------------------------------------
  "tax.badge.permanent": {
    en: "PERMANENT — no basis add-back",
    ko: "영구 불인정 — 취득가 환원 없음",
  },
  "tax.badge.deferred": {
    en: "deferred to replacement basis",
    ko: "재매수 취득가에 이연",
  },

  // --- shared §1091 window-state titles (identical wording on both pages) -----------------------
  "tax.window.openTitle": {
    en: "§1091 window open on the sale dated {date}",
    ko: "{date}에 매도된 건에 대해 §1091 기간이 열려 있습니다",
  },
  "tax.window.closedTitle": {
    en: "§1091 window closed on the sale dated {date}",
    ko: "{date}에 매도된 건에 대해 §1091 기간이 마감되었습니다",
  },

  // --- Disposals table -------------------------------------------------------------------------
  "tax.disposals.subtitle": {
    en: "Every lot relieved this year, in disposal order. A multi-lot sale is one row per lot.",
    ko: "올해 처분된 모든 매수 단위를 처분 순서대로 표시합니다. 여러 매수 단위에 걸친 매도는 단위별로 한 행씩 나타납니다.",
  },
  "tax.disposals.filterPlaceholder": {
    en: "Filter by symbol",
    ko: "종목으로 필터",
  },
  "tax.disposals.filteredEmpty": {
    en: "No disposals match this filter.",
    ko: "이 필터에 해당하는 처분 내역이 없습니다.",
  },
  // One InfoNote near the table header, replacing four per-cell `title=` tooltips (lot id, "no
  // lot", basis-uncertain "?", holding-tolled note) that a touch or keyboard user could never reach.
  "tax.disposals.columnsNote.summary": {
    en: "Lot, method, and basis-flag columns explained",
    ko: "매수 단위·방식·취득가 표시 열 설명",
  },
  "tax.disposals.columnsNote.lotId": {
    en: "Lot/method: first 8 characters of the lot id, plus the method (FIFO, etc.) used to select it.",
    ko: "매수 단위/방식: 매수 단위 ID의 앞 8자와, 이를 선택한 방식(FIFO 등)을 함께 표시합니다.",
  },
  "tax.disposals.columnsNote.noLot": {
    en: '"no lot" means shares sold with no matching acquisition in the import -- an oversold shortfall.',
    ko: '"매수 단위 없음"은 가져온 데이터에 일치하는 취득 내역이 없는 매도, 즉 초과 매도 부족분을 뜻합니다.',
  },
  "tax.disposals.columnsNote.basisUncertain": {
    en: 'A "?" after cost basis means the replay could not establish that lot\'s basis from the import.',
    ko: '취득가 뒤의 "?"는 가져온 데이터로 해당 매수 단위의 취득가를 확정할 수 없었음을 뜻합니다.',
  },
  "tax.disposals.columnsNote.tolled": {
    en: "A holding-from note means a wash sale tolled this lot's holding period.",
    ko: "보유 시작일 표시는 워시 세일로 인해 이 매수 단위의 보유 기간이 유예되었음을 뜻합니다.",
  },
  "tax.disposals.holdingTolledTitle": {
    en: "Wash sale tolled the holding period",
    ko: "워시 세일로 보유 기간이 유예되었습니다",
  },
  "tax.disposals.holdingFrom": {
    en: "(holding from {date})",
    ko: "({date}부터 보유)",
  },
  "tax.disposals.lotIdTitle": { en: "lot {lotId}", ko: "매수 단위 {lotId}" },
  "tax.disposals.noLotTitle": {
    en: "No lot was available to consume — an oversold shortfall.",
    ko: "소비할 매수 단위가 없습니다 — 초과 매도 부족분입니다.",
  },
  "tax.disposals.noLot": { en: "no lot", ko: "매수 단위 없음" },
  "tax.disposals.basisUncertainTitle": {
    en: "Basis could not be established from the import",
    ko: "가져온 데이터로는 취득가를 확정할 수 없습니다",
  },
  "tax.term.short": { en: "Short", ko: "단기" },
  "tax.term.long": { en: "Long", ko: "장기" },
  "tax.disposals.footer_one": {
    en: "{count} disposal. Gain/loss shown is reportable — after any §1091 disallowance itemized below.",
    ko: "{count}건의 처분입니다. 표시된 손익은 신고 대상 금액입니다 — §1091에 따른 불인정이 있다면 반영된 이후 값이며, 그 내역은 아래 워시 세일 표에 항목별로 정리되어 있습니다.",
  },
  "tax.disposals.footer_other": {
    en: "{count} disposals. Gain/loss shown is reportable — after any §1091 disallowance itemized below.",
    ko: "{count}건의 처분입니다. 표시된 손익은 신고 대상 금액입니다 — §1091에 따른 불인정이 있다면 반영된 이후 값이며, 그 내역은 아래 워시 세일 표에 항목별로 정리되어 있습니다.",
  },

  // --- shared pager -- server-side paging for the Disposals and Wash sales tables, mirroring
  //     `activity.pager.*` in `messages/activity.ts` verbatim so the two pages read identically.
  "tax.pager.previous": { en: "Previous", ko: "이전" },
  "tax.pager.next": { en: "Next", ko: "다음" },
  "tax.pager.range": {
    en: "{first}–{last} of {total}",
    ko: "{total} 중 {first}–{last}",
  },

  // --- uncertain-basis magnitude caveat (headline sentence, fully enumerated: plural on total ×
  //     presence of the ratio clause × below/above) ------------------------------------------------
  "tax.uncertainBasis.headline_one": {
    en: "{uncertain} of {total} disposal used a cost basis the replay could not establish.",
    ko: "{total}건의 처분 중 {uncertain}건이 재구성 과정에서 확정할 수 없는 취득가를 사용했습니다.",
  },
  "tax.uncertainBasis.headline_other": {
    en: "{uncertain} of {total} disposals used a cost basis the replay could not establish.",
    ko: "{total}건의 처분 중 {uncertain}건이 재구성 과정에서 확정할 수 없는 취득가를 사용했습니다.",
  },
  "tax.uncertainBasis.headlineRatio_one_below": {
    en: "{uncertain}/{total} disposal has unestablished cost basis — {gainOnUncertain} ({pct}%) of {netGain} gain reported below.",
    ko: "{total}건 중 {uncertain}건은 취득가가 확정되지 않았습니다 — 아래 보고된 {netGain} 이익 중 {gainOnUncertain}({pct}%)에 해당합니다.",
  },
  "tax.uncertainBasis.headlineRatio_one_above": {
    en: "{uncertain}/{total} disposal has unestablished cost basis — {gainOnUncertain} ({pct}%) of {netGain} gain reported above.",
    ko: "{total}건 중 {uncertain}건은 취득가가 확정되지 않았습니다 — 위 보고된 {netGain} 이익 중 {gainOnUncertain}({pct}%)에 해당합니다.",
  },
  "tax.uncertainBasis.headlineRatio_other_below": {
    en: "{uncertain}/{total} disposals lack cost basis — {gainOnUncertain} ({pct}%) of {netGain} gain reported below.",
    ko: "{total}건 중 {uncertain}건은 취득가가 확정되지 않았습니다 — 아래 보고된 {netGain} 이익 중 {gainOnUncertain}({pct}%)에 해당합니다.",
  },
  "tax.uncertainBasis.headlineRatio_other_above": {
    en: "{uncertain}/{total} disposals lack cost basis — {gainOnUncertain} ({pct}%) of {netGain} gain reported above.",
    ko: "{total}건 중 {uncertain}건은 취득가가 확정되지 않았습니다 — 위 보고된 {netGain} 이익 중 {gainOnUncertain}({pct}%)에 해당합니다.",
  },

  // --- uncertain-basis magnitude caveat (remainder sentence, fully enumerated: plural on the
  //     remaining count × exactly-zero / loss / gain) ------------------------------------------
  "tax.uncertainBasis.remainder_one_zero": {
    en: "The remaining {count} disposal net to exactly zero.",
    ko: "나머지 {count}건의 처분은 합산하면 정확히 0입니다.",
  },
  "tax.uncertainBasis.remainder_other_zero": {
    en: "The remaining {count} disposals net to exactly zero.",
    ko: "나머지 {count}건의 처분은 합산하면 정확히 0입니다.",
  },
  "tax.uncertainBasis.remainder_one_loss": {
    en: "The remaining {count} disposal net to a loss of {amount}.",
    ko: "나머지 {count}건의 처분은 합산하면 {amount}의 손실입니다.",
  },
  "tax.uncertainBasis.remainder_other_loss": {
    en: "The remaining {count} disposals net to a loss of {amount}.",
    ko: "나머지 {count}건의 처분은 합산하면 {amount}의 손실입니다.",
  },
  "tax.uncertainBasis.remainder_one_gain": {
    en: "The remaining {count} disposal net to a gain of {amount}.",
    ko: "나머지 {count}건의 처분은 합산하면 {amount}의 이익입니다.",
  },
  "tax.uncertainBasis.remainder_other_gain": {
    en: "The remaining {count} disposals net to a gain of {amount}.",
    ko: "나머지 {count}건의 처분은 합산하면 {amount}의 이익입니다.",
  },

  "tax.uncertainBasis.proceedsVsBasis": {
    en: "{proceeds} of proceeds on those rows have only {basis} of established cost behind them.",
    ko: "해당 항목들의 매도 금액 {proceeds} 중 확정된 취득가는 {basis}뿐입니다.",
  },
  // `{openingPosition}`/`{costBasisCode}`/`{accountsToml}` carry the literal, untranslated
  // `[[opening_position]]`, `cost_basis` and `data/accounts.toml` tokens -- identifiers, not prose.
  "tax.uncertainBasis.fixIt": {
    en: "Bound, not estimate — gain may be lower; records confirm it. Add {openingPosition}/{costBasisCode} to {accountsToml}.",
    ko: "추정치가 아닌 상한값입니다 — 실제 이익은 더 낮을 수 있으며 본인 기록으로만 확인됩니다. {accountsToml}에 {openingPosition}/{costBasisCode}를 추가하세요.",
  },

  // --- summary tiles (Tax page) -----------------------------------------------------------------
  //
  // Every tile in this row carries its tax year, because every one of them is year-scoped and the
  // reader has no way to know that from the figure: `GainsReport` is built from the disposals whose
  // `disposed_date` falls inside `[start, end]` (`app/tax/gains.py`), totals included -- the two
  // wash-sale tiles as much as the three gain tiles. The Wash Sales page's own tiles below are the
  // whole connected ledger as of today and are labelled "(all years)" for the same reason, so the
  // pair a reader is most likely to compare -- deferred here, deferred there -- says on its face
  // why the two numbers differ instead of leaving that to a hint under one of them.
  // DEFINITIONS.md standing rule 6: two statistics shown together were computed over the same
  // window, or they are not shown together.
  "tax.tile.shortTermGain": { en: "Short-term gain ({year})", ko: "단기 이익 ({year})" },
  "tax.tile.longTermGain": { en: "Long-term gain ({year})", ko: "장기 이익 ({year})" },
  "tax.tile.netGain": { en: "Net gain ({year})", ko: "순이익 ({year})" },
  "tax.tile.washSaleDisallowedDeferred": {
    en: "Wash-sale disallowed, deferred ({year})",
    ko: "워시 세일 불인정, 이연 ({year})",
  },
  "tax.tile.washSaleDisallowedHint": {
    en: "Added to replacement lot basis. Not lost — recovered on a future sale.",
    ko: "재매수 매수 단위의 취득가에 더해집니다. 손실된 것이 아니라 향후 매도 시 회수됩니다.",
  },
  // The link out to the Wash Sales page, rendered under this tile row rather than inside the
  // deferred tile's own `hint` -- `StatTile.hint` is typed `string`, and widening it to a node is a
  // change to a component five other pages share. COPY-STYLE.md rule 3 ("do not cross-reference
  // pages in body text -- link the page") is what this satisfies; the arrow is the affordance.
  "tax.tile.deferred.seeWashSales": { en: "Open windows →", ko: "열린 창 보기 →" },
  // Tax page only -- the Wash Sales page's equivalent tile is whole-ledger and has its own label
  // (`tax.wsale.tile.permanentlyDisallowed`). The *hint* below stays shared: it explains the rule,
  // which is the same on both pages, not the window.
  "tax.tile.permanentlyDisallowedIra": {
    en: "Permanently disallowed, IRA ({year})",
    ko: "영구 불인정, IRA ({year})",
  },
  "tax.tile.permanentlyDisallowedHint": {
    en: "Rev. Rul. 2008-5. No basis add-back anywhere. Gone.",
    ko: "Rev. Rul. 2008-5. 어디에도 취득가 환원이 없습니다. 완전히 소멸됩니다.",
  },
  "tax.summary.permanentCallout.lead": {
    en: "Permanently disallowed loss detected — never sum this with the deferred figure.",
    ko: "영구 불인정 손실이 발견되었습니다 — 이연 금액과 절대 합산하지 마세요.",
  },
  "tax.summary.permanentCallout.rest": {
    en: "{amount} replaced in an IRA — destroyed under Rev. Rul. 2008-5. Never added to basis; never reduces a future gain.",
    ko: "IRA 내 재매수로 대체된 {amount}의 손실은 Rev. Rul. 2008-5에 따라 완전히 소멸됩니다. 어떤 취득가에도 더해지지 않으며 향후 이익을 절대 줄이지 않습니다.",
  },

  // --- warnings section ------------------------------------------------------------------------
  "tax.warnings.headline_one": {
    en: "Figures are overstated and must be corrected before filing — {count} basis/fee gap below, by kind and account:",
    ko: "이 수치들은 과대 계상되어 있으며 제출 전에 수정되어야 합니다 — 재구성 과정에서 해소하지 못한 취득가/수수료 공백 {count}건을 아래에 유형과 계좌별로 정리했습니다:",
  },
  "tax.warnings.headline_other": {
    en: "Figures are overstated and must be corrected before filing — {count} basis/fee gaps below, by kind and account:",
    ko: "이 수치들은 과대 계상되어 있으며 제출 전에 수정되어야 합니다 — 재구성 과정에서 해소하지 못한 취득가/수수료 공백 {count}건을 아래에 유형과 계좌별로 정리했습니다:",
  },
  "tax.warnings.showGaps": {
    en: "Show the breakdown by kind and account",
    ko: "유형·계좌별 내역 보기",
  },
  "tax.warnings.showAll": {
    en: "Show all {count} individual warnings",
    ko: "개별 경고 {count}건 모두 보기",
  },
  "tax.uncertainBasis.showDetail": {
    en: "Show the breakdown",
    ko: "세부 내역 보기",
  },

  // --- warning-kind vocabulary (api/tax.ts's `warningKindLabel`, mirrored from
  //     `app.core.lots.WarningKind` on the backend) --------------------------------------------
  "tax.warningKind.oversold": {
    en: "Oversold — shares sold with no matching acquisition in the export",
    ko: "초과 매도 — 내보내기 파일에 일치하는 취득 내역이 없는 매도",
  },
  "tax.warningKind.missingBasis": {
    en: "Missing basis — matched a lot whose basis was never established",
    ko: "취득가 없음 — 취득가가 한 번도 확정된 적 없는 매수 단위와 매칭됨",
  },
  "tax.warningKind.unmatchedTransferIn": {
    en: "Unmatched transfer in — arrived by ACAT with no basis or date",
    ko: "미매칭 계좌 이전 입고 — ACAT로 들어왔으나 취득가나 날짜가 없음",
  },
  "tax.warningKind.feesUnknown": {
    en: "Fees unknown — source export has no fee column",
    ko: "수수료 미상 — 원본 내보내기 파일에 수수료 열이 없음",
  },
  "tax.warningKind.feesEstimated": {
    en: "Regulatory fee estimated from the SEC/FINRA schedule (export had no fee column)",
    ko: "규제 수수료를 SEC/FINRA 요율표로 추정함 (내보내기 파일에 수수료 열 없음)",
  },
  "tax.warningKind.unsupportedAction": {
    en: "Unsupported action (e.g. an unimplemented spinoff)",
    ko: "지원되지 않는 처리 (예: 아직 구현되지 않은 스핀오프)",
  },
  "tax.warningKind.splitWithoutRatio": {
    en: "Split with no parseable ratio",
    ko: "비율을 해석할 수 없는 액면 분할",
  },
  "tax.warningKind.ambiguousTransferDirection": {
    en: "Transfer direction guessed — quantity is right, which account sent the shares is not",
    ko: "이전 방향 추정 — 수량은 정확하지만 어느 계좌에서 보냈는지는 확실하지 않음",
  },
  "tax.warningKind.backwardBasisAttachment": {
    en: "Wash-sale basis attached to an earlier disposal — unsettled under Pub 550",
    ko: "워시 세일 취득가가 이전 처분에 결부됨 — Pub 550 기준으로 미확정",
  },

  // --- wash-sale symbol panel (Tax page) --------------------------------------------------------
  "tax.washSymbolPanel.isWord": { en: "is", ko: "실제로" },
  "tax.washSymbolPanel.scopeLine": {
    en: "Scope: every wash sale in your full history, not just {year} — deliberate; repurchase safety is a today question.",
    ko: "범위: {year}년만이 아닌 전체 계좌 이력의 모든 워시 세일입니다 — 재매수 안전 여부는 오늘 시점의 질문이라 의도적으로 그렇습니다.",
  },
  "tax.washSymbolPanel.empty": {
    en: "No wash-sale activity to summarize by symbol across your connected account history.",
    ko: "연결된 계좌 이력 전체에서 종목별로 요약할 워시 세일 내역이 없습니다.",
  },
  "tax.washSymbolPanel.columnNote": {
    en: "Deferred and Permanently disallowed columns answer different questions and are never added together — see totals below.",
    ko: "아래의 이연 및 영구 불인정 열은 서로 다른 질문에 답하며 절대 합산되지 않습니다 -- 표 아래에서 설명하는 합계를 참고하세요.",
  },
  "tax.washSymbolPanel.filterPlaceholder": {
    en: "Filter by symbol",
    ko: "종목으로 필터",
  },
  "tax.washSymbolPanel.filterAll": {
    en: "All windows",
    ko: "모든 기간",
  },
  "tax.washSymbolPanel.filterOpen": {
    en: "Open windows",
    ko: "진행 중",
  },
  "tax.washSymbolPanel.filterCompleted": {
    en: "Completed",
    ko: "완료됨",
  },
  "tax.washSymbolPanel.filteredEmpty": {
    en: "No symbols match this filter.",
    ko: "이 필터에 해당하는 종목이 없습니다.",
  },
  "tax.washSymbolPanel.tolledTitle": {
    en: "Wash sale tolled the holding period on a replacement lot not shown as disposed in this year's Disposals table",
    ko: "워시 세일로 인해, 올해 처분 표에는 처분된 것으로 표시되지 않은 재매수 매수 단위의 보유 기간이 유예되었습니다",
  },
  "tax.washSymbolPanel.tolledText": {
    en: "(holding tolled to {dates})",
    ko: "({dates}로 유예됨)",
  },
  "tax.washSymbolPanel.daysLeft_one": {
    en: "{days} day — safe from {date}",
    ko: "{days}일 — {date}부터 안전",
  },
  "tax.washSymbolPanel.daysLeft_other": {
    en: "{days} days — safe from {date}",
    ko: "{days}일 — {date}부터 안전",
  },
  "tax.washSymbolPanel.safeToRepurchase": {
    en: "safe to repurchase — window closed {date}",
    ko: "재매수 안전 — {date}에 기간 마감",
  },
  "tax.washSymbolPanel.noRepurchaseYet": {
    en: "— no repurchase yet; buying back before the date above creates a wash sale",
    ko: "— 아직 재매수 없음; 위 날짜 이전에 재매수하면 워시 세일이 발생합니다",
  },
  "tax.washSymbolPanel.repurchaseNote": {
    en: "Date a new purchase stops triggering a wash sale on the latest loss sale. Doesn't affect money already deferred.",
    ko: "이 날짜는 이 종목의 가장 최근 손실 매도에 대해 새 매수가 더 이상 새로운 워시 세일을 만들지 않게 되는 시점을 알려줍니다. 위에 이미 이연된 금액에는 영향을 주지 않습니다.",
  },
  "tax.washSymbolPanel.totalDeferredLead": {
    en: "{amount} deferred.",
    ko: "{amount} 이연.",
  },
  "tax.washSymbolPanel.totalDeferredRest": {
    en: "Deferred, not released — added to the replacement shares' basis. Recovered when sold, if that sale isn't a wash sale.",
    ko: "이연된 것이지 해제된 것이 아닙니다. 이 손실은 이미 재매수 주식의 취득가에 더해져 있습니다. 해당 주식이 결국 매도될 때만 돌려받으며 — 그 매도 자체가 또 다른 워시 세일이 아닐 때만 그렇습니다.",
  },
  "tax.washSymbolPanel.totalPermanentLead": {
    en: "{amount} permanently disallowed.",
    ko: "{amount} 영구 불인정.",
  },
  "tax.washSymbolPanel.totalPermanentRest": {
    en: "Gone, not deferred — replacement was bought in an IRA. No basis added anywhere; waiting won't recover it.",
    ko: "이연이 아니라 완전히 소멸된 것입니다. 이 부분은 재매수가 IRA 안에서 이루어졌기 때문에 불인정되었습니다. 어디에도 취득가가 더해지지 않았습니다. 기다려도 회복되지 않습니다.",
  },
  "tax.washSymbolPanel.openCount_one": {
    en: "{openCount} of {total} symbol still inside the 30-day window as of {asOf}.",
    ko: "{asOf} 기준으로 전체 {total}개 종목 중 {openCount}개가 아직 30일 기간 이내입니다.",
  },
  "tax.washSymbolPanel.openCount_other": {
    en: "{openCount} of {total} symbols still inside the 30-day window as of {asOf}.",
    ko: "{asOf} 기준으로 전체 {total}개 종목 중 {openCount}개가 아직 30일 기간 이내입니다.",
  },
  "tax.washSymbolPanel.footer": {
    en: "Connected accounts only; excludes options and unconnected purchases. Calculation only — reconcile with your 1099-B.",
    ko: "연결된 계좌만 기준입니다. 옵션과 미연결 계좌의 매수는 제외됩니다. 계산 결과일 뿐 세무 자문이 아니니 1099-B와 대조하세요.",
  },
  "tax.washSymbolPanel.footer.more": {
    en: "The rule also reaches substantially identical securities, not just identical ones, and contracts or options to acquire them — none of which this panel detects. A repurchase in a spouse's account or a controlled entity can trigger it too.",
    ko: "이 규칙은 동일한 증권뿐 아니라 실질적으로 동일한 증권, 이를 취득할 계약이나 옵션에도 적용되며, 이 패널은 이를 탐지하지 못합니다. 배우자 계좌나 지배 법인의 재매수도 규칙을 유발할 수 있습니다.",
  },

  // --- wash-sale table (Tax page) ---------------------------------------------------------------
  "tax.washSaleTable.empty": {
    en: "No wash sales detected for this year.",
    ko: "올해 감지된 워시 세일이 없습니다.",
  },
  // Cross-link (UX refactor 3.3): this event's own sale is one of the year's disposals -- its full
  // per-lot detail lives on the Disposals tab, not on this table.
  "tax.washSaleTable.viewDisposals": {
    en: "see disposals",
    ko: "처분 내역 보기",
  },
  "tax.washSaleTable.viewDisposalsTitle": {
    en: "See this year's disposals for this sale's full detail",
    ko: "이 매도 건의 상세 내역을 올해 처분 내역에서 확인하세요",
  },

  // --- unsettled classifications -----------------------------------------------------------------
  "tax.unsettled.intro": {
    en: 'The IRS has not ruled on whether these pairs are "substantially identical" under §1091. The engine does not decide — you must. Both outcomes are priced below; neither is applied until you record a decision.',
    ko: '이 종목 쌍들이 §1091에 따라 "실질적으로 동일"한지에 대해 국세청(IRS)은 판단을 내리지 않았습니다. 이 엔진은 결정하지 않습니다 — 본인이 결정해야 합니다. 두 결과 모두 아래에 금액으로 제시되며, 본인이 결정을 기록하기 전까지는 어느 쪽도 적용되지 않습니다.',
  },
  "tax.unsettled.disallowedAmount": {
    en: "{amount} disallowed",
    ko: "{amount} 불인정",
  },

  // --- Form 8949 --------------------------------------------------------------------------------
  "tax.box.a": {
    en: "Box A — short-term, basis reported to the IRS",
    ko: "Box A — 단기, 국세청에 보고된 취득가",
  },
  "tax.box.b": {
    en: "Box B — short-term, basis not reported to the IRS",
    ko: "Box B — 단기, 국세청에 보고되지 않은 취득가",
  },
  "tax.box.c": {
    en: "Box C — short-term, not on any 1099-B",
    ko: "Box C — 단기, 1099-B에 없음",
  },
  "tax.box.d": {
    en: "Box D — long-term, basis reported to the IRS",
    ko: "Box D — 장기, 국세청에 보고된 취득가",
  },
  "tax.box.e": {
    en: "Box E — long-term, basis not reported to the IRS",
    ko: "Box E — 장기, 국세청에 보고되지 않은 취득가",
  },
  "tax.box.f": {
    en: "Box F — long-term, not on any 1099-B",
    ko: "Box F — 장기, 1099-B에 없음",
  },
  "tax.form8949.downloadCsv": { en: "Download CSV", ko: "CSV 다운로드" },

  // --- reconciliation pack (Form 8949 tab) ------------------------------------------------------
  //
  // Three downloads and a Print button, on the tab a filer is on when the numbers leave this app.
  // The hint says what the files are (the tables above, verbatim) and repeats the one caveat
  // COPY-STYLE.md rule 6 says may never be hidden -- a file that outlives this page must not be
  // the one copy of these figures that lost the "not advice" line.
  "tax.export.pack.title": { en: "Reconciliation pack", ko: "대사 자료 묶음" },
  "tax.export.pack.hint": {
    en: "The three tables above, as CSV for {year}. A calculation to check against a 1099-B — not tax advice.",
    ko: "위 세 표를 {year}년 CSV로 내려받습니다. 1099-B와 대조할 계산 자료이며 세무 자문이 아닙니다.",
  },
  "tax.export.pack.form8949": { en: "Form 8949 (CSV)", ko: "Form 8949 (CSV)" },
  "tax.export.pack.disposals": { en: "Disposals (CSV)", ko: "처분 내역 (CSV)" },
  "tax.export.pack.washSales": { en: "Wash sales (CSV)", ko: "워시 세일 (CSV)" },
  "tax.export.print": { en: "Print", ko: "인쇄" },
  "tax.export.printTitle": {
    en: "Prints this tab as a working paper, disclaimer on every page.",
    ko: "이 탭을 작업 문서로 인쇄합니다. 모든 페이지에 면책 문구가 표시됩니다.",
  },
  "tax.form8949.empty": {
    en: "No disposals to report for this year.",
    ko: "올해 보고할 처분 내역이 없습니다.",
  },
  "tax.subtotal.shortTerm": { en: "Short-term subtotal", ko: "단기 소계" },
  "tax.subtotal.longTerm": { en: "Long-term subtotal", ko: "장기 소계" },
  "tax.subtotal.detail": {
    en: "proceeds {proceeds}, basis {basis}, adjustment {adjustment}, gain/loss {gain}",
    ko: "매도 금액 {proceeds}, 취득가 {basis}, 조정액 {adjustment}, 손익 {gain}",
  },

  // === Wash Sales -- now a section of the Tax page's Wash sales tab ==============================
  /** The subheading this section is folded in under. Deliberately NOT "Wash sales": that tab already
   *  carries two panels with that name, and a third heading repeating it would say nothing about
   *  what makes this one different -- it is whole-ledger and present-tense, not year-scoped. */
  "tax.washSales.openWindowsHeading": {
    en: "Open repurchase windows, whole ledger",
    ko: "전체 원장 기준, 열려 있는 재매수 기간",
  },
  "tax.washSales.title": { en: "Wash Sales", ko: "워시 세일" },
  // "wash-sale", not "§1091": in the page-subtitle slot the section sign renders in the same mono
  // palette the money figures below it use, and a browser walk read "§1091" as a dollar amount. The
  // citation itself is not lost -- it stays in the per-sale window tooltips
  // (`tax.wsale.windowOpenTitle`) and in the ambiguous-pairs disclosure body, which is the slot
  // COPY-STYLE.md reserves for worked reasoning. The "never summed" caveat that used to ride along
  // here is stated where it can act on something: `tax.wsale.permanentCallout.lead`, next to the
  // figure it warns about.
  "tax.washSales.subtitle": {
    en: "Open wash-sale windows by ticker",
    ko: "종목별 열린 워시 세일 창",
  },
  "tax.washSales.loading": {
    en: "Loading wash-sale tracker…",
    ko: "워시 세일 추적 정보 불러오는 중…",
  },
  // (`tax.washSales.disclaimerBody` lived here. It said the same thing as `tax.disclaimer.body`
  //  in different words; both pages now render that one key.)
  "tax.washSales.emptyState": {
    en: "No wash sales in your connected history. Absence of data, not zero risk elsewhere — reflects only what's connected.",
    ko: "기록된 워시 세일이 없습니다. 데이터 부재이지 다른 곳의 위험이 0이라는 뜻은 아닙니다 — 이 앱에 연결된 정보만 반영합니다.",
  },
  "tax.washSales.footer": {
    en: "Based only on accounts connected here. Excludes options and purchases in unconnected accounts, including a spouse's.",
    ko: "이 앱에 연결된 계좌만을 기준으로 합니다. 옵션이나 취득 계약은 포함하지 않으며, 배우자 계좌를 포함해 이 앱에 연결되지 않은 계좌의 매수도 포함하지 않습니다.",
  },
  "tax.washSales.scopeLine": {
    en: "Scope: your entire connected history, not one tax year. Window state and days-remaining computed as of {asOf}.",
    ko: "범위: 하나의 과세 연도가 아닌, 연결된 계좌의 전체 이력입니다. 기간 상태와 남은 일수는 오늘 {asOf} 기준으로 계산됩니다.",
  },

  // --- scope switch + cross-links (Wash Sales page) ---------------------------------------------
  //
  // `GET /api/tax/wash-sales` takes no `year` and is not going to grow one (see its docstring: a
  // replacement lot can sit years from the sale that deferred a loss into it). So the year filter
  // here is applied in the browser, over sale dates, and `.clientSide` says so rather than letting
  // the reader assume the server re-scoped anything.
  //
  // The tiles do NOT follow this switch. They are whole-ledger sums the response carries
  // pre-computed, and the only year-scoped figure derivable in the browser would be a sum over
  // `sales`, a list the API is explicitly allowed to leave empty -- a silently-understated tax
  // figure. They keep their "(all years)" labels in both scopes and `.tilesStayAllYears` states
  // that where the two scopes meet, which is DEFINITIONS.md standing rule 6: two windows are never
  // mixed inside one sentence.
  "tax.washSales.scope.label": { en: "Scope", ko: "범위" },
  "tax.washSales.scope.allYears": { en: "All years", ko: "전체 연도" },
  "tax.washSales.scope.year": { en: "{year} only", ko: "{year}만" },
  "tax.washSales.scope.clientSide": {
    en: "Filtered in the browser by sale date. The tracker itself has no year — a window can outlive one.",
    ko: "매도일 기준으로 브라우저에서 걸러낸 목록입니다. 추적 자체에는 연도가 없습니다 — 기간은 한 해를 넘길 수 있습니다.",
  },
  "tax.washSales.scope.tilesStayAllYears": {
    en: "Tiles above stay whole-ledger. Only the lists below are {year}.",
    ko: "위 타일은 전체 원장 기준을 유지합니다. 아래 목록만 {year}년입니다.",
  },
  "tax.washSales.scope.emptyYear": {
    en: "No loss sale in {year}. Switch to All years to see the rest of the ledger.",
    ko: "{year}년에는 손실 매도가 없습니다. 전체 연도로 바꾸면 나머지 원장을 볼 수 있습니다.",
  },
  "tax.washSales.toTax": { en: "This year's gains and Form 8949", ko: "올해 손익과 Form 8949" },
  "tax.washSales.openSymbolPage": { en: "Open {symbol} page", ko: "{symbol} 페이지 열기" },
  "tax.washSales.seeDisposals": { en: "See in Disposals", ko: "처분 내역에서 보기" },
  "tax.washSales.seeDisposalsTitle": {
    en: "Opens the Tax page's Disposals tab for {symbol}, tax year {year}.",
    ko: "세금 페이지의 {year}년 처분 내역 탭을 {symbol} 기준으로 엽니다.",
  },

  // --- table captions -----------------------------------------------------------------------
  //
  // Every data table on these two pages carries a `<caption>`, visually hidden. A screen reader
  // announces a table by its caption; without one, nine numeric columns inside a scroll region
  // inside a `<details>` are reached with no statement of what they are or what window they cover.
  // Each caption therefore names the table AND its scope -- the same discipline the visible tile
  // labels follow, since the scope is exactly what a reader cannot recover from the cells.
  "tax.caption.disposals": {
    en: "Disposals, tax year {year}, {count} rows",
    ko: "처분 내역, {year} 과세 연도, {count}행",
  },
  "tax.caption.warningGroups": {
    en: "Basis and fee gaps by kind and account, tax year {year}",
    ko: "유형·계좌별 취득가 및 수수료 공백, {year} 과세 연도",
  },
  "tax.caption.washBySymbol": {
    en: "Wash-sale exposure by symbol, whole ledger as of {asOf}, {count} rows",
    ko: "종목별 워시 세일 노출, {asOf} 기준 전체 원장, {count}행",
  },
  "tax.caption.washEvents": {
    en: "Triggered wash-sale events, tax year {year}, {count} rows",
    ko: "발생한 워시 세일 이벤트, {year} 과세 연도, {count}행",
  },
  "tax.caption.unsettled": {
    en: "Unsettled substantially-identical pairs, tax year {year}, {count} rows",
    ko: "판정 보류된 실질 동일 종목 쌍, {year} 과세 연도, {count}행",
  },
  "tax.caption.form8949": {
    en: "{box}, tax year {year}, {count} rows",
    ko: "{box}, {year} 과세 연도, {count}행",
  },
  "tax.caption.wsaleSales": {
    en: "Loss sales for {symbol}, whole ledger, {count} rows",
    ko: "{symbol}의 손실 매도, 전체 원장, {count}행",
  },
  "tax.caption.wsaleSalesYear": {
    en: "Loss sales for {symbol}, {year} only, {count} rows",
    ko: "{symbol}의 손실 매도, {year}년만, {count}행",
  },

  // --- headline tiles (Wash Sales page) -----------------------------------------------------------
  // "(all years)", not "(open + closed windows)": the window state is the *other* axis this page
  // already renders per symbol, while the axis a reader confuses with the Tax page's own deferred
  // tile is the time span. See the summary-tile block above.
  "tax.wsale.tile.deferred": {
    en: "Deferred wash-sale loss (all years)",
    ko: "이연 워시 세일 손실 (전체 연도)",
  },
  "tax.wsale.tile.permanentlyDisallowed": {
    en: "Permanently disallowed, IRA (all years)",
    ko: "영구 불인정, IRA (전체 연도)",
  },
  "tax.wsale.tile.deferredHint": {
    en: "Added to replacement lot basis. Not lost -- recovered when that lot eventually sells.",
    ko: "재매수 매수 단위의 취득가에 더해집니다. 손실된 것이 아니라 해당 매수 단위가 매도될 때 회수됩니다.",
  },
  "tax.wsale.tile.openWindowSymbols": {
    en: "Open-window symbols",
    ko: "기간이 열린 종목 수",
  },
  "tax.wsale.tile.symbolsTracked": {
    en: "Symbols tracked",
    ko: "추적 중인 종목 수",
  },
  "tax.wsale.permanentCallout.lead": {
    en: "Permanently disallowed loss on record -- never sum this with the deferred figure.",
    ko: "영구 불인정 손실이 기록되어 있습니다 -- 이연 금액과 절대 합산하지 마세요.",
  },
  "tax.wsale.permanentCallout.rest": {
    en: "{amount} disallowed under Rev. Rul. 2008-5 — bought in an IRA. Never added to basis; never reduces a future gain.",
    ko: "재매수가 IRA 안에서 이루어져 Rev. Rul. 2008-5에 따라 {amount}이 불인정되었습니다. IRA를 포함해 어떤 매수 단위의 취득가에도 더해지지 않으며, 향후 이익을 절대 줄이지 않습니다.",
  },

  // --- open windows section ------------------------------------------------------------------
  "tax.wsale.openWindows.title": { en: "Open windows", ko: "열린 기간" },
  "tax.wsale.openWindows.subtitle": {
    en: "Symbols with an open wash-sale window, soonest to close first. Expand for sale detail.",
    ko: "워시 세일 기간이 열려 있는 종목을 마감 임박 순으로 표시합니다. 펼치면 매도 상세를 볼 수 있습니다.",
  },
  "tax.wsale.openWindows.empty": {
    en: "No wash-sale window is currently open. Nothing on your ledger restricts a repurchase today.",
    ko: "현재 열려 있는 워시 세일 기간이 없습니다. 원장상 오늘 재매수를 제한하는 내역이 없습니다.",
  },

  // --- open windows: sortable table headers ---------------------------------------------------
  "tax.wsale.openTable.daysLeftHeader": {
    en: "Days left",
    ko: "남은 일수",
  },
  "tax.wsale.openTable.safeFromHeader": {
    en: "Safe from",
    ko: "안전 시점",
  },

  // --- symbol card (open windows) ------------------------------------------------------------
  "tax.wsale.symbolCard.notYetTriggered": {
    en: "not yet triggered",
    ko: "아직 발생하지 않음",
  },
  "tax.wsale.symbolCard.notYetTriggeredTitle": {
    en: "This symbol has an open-window loss sale, not yet disallowed — a repurchase now still creates the wash sale.",
    ko: "이 종목에는 기간이 아직 열려 있고 아직 불인정되지 않은 손실 매도가 있습니다 -- 지금 재매수하면 여전히 워시 세일이 발생합니다.",
  },
  "tax.wsale.daysLeft_one": { en: "{days} day left", ko: "{days}일 남음" },
  "tax.wsale.daysLeft_other": { en: "{days} days left", ko: "{days}일 남음" },
  "tax.wsale.safeFrom": { en: "safe from {date}", ko: "{date}부터 안전" },
  "tax.wsale.figureLabel.permanent": { en: "Permanent", ko: "영구" },

  // --- closed windows section -----------------------------------------------------------------
  "tax.wsale.closed.summary_one": {
    en: "{count} closed-window symbol still carrying deferred loss on a replacement lot",
    ko: "재매수 매수 단위에 이연 손실이 남아 있는 기간 마감 종목 {count}개",
  },
  "tax.wsale.closed.summary_other": {
    en: "{count} closed-window symbols still carrying deferred loss on a replacement lot",
    ko: "재매수 매수 단위에 이연 손실이 남아 있는 기간 마감 종목 {count}개",
  },
  "tax.wsale.closed.note": {
    en: "Window passed — repurchase won't create a wash sale. Deferred loss stays in the replacement lot's basis, unrecovered.",
    ko: "기간은 지났습니다 — 오늘 재매수해도 새 워시 세일은 발생하지 않습니다. 다만 이연 손실은 여전히 재매수 매수 단위 취득가에 남아 있으며 아직 회수되지 않았습니다.",
  },
  "tax.wsale.closed.otherSettled_one": {
    en: "{count} other closed-window symbol carries no outstanding deferred loss and is not listed here.",
    ko: "그 외 기간 마감 종목 {count}개는 남아 있는 이연 손실이 없어 여기에 표시되지 않습니다.",
  },
  "tax.wsale.closed.otherSettled_other": {
    en: "{count} other closed-window symbols carry no outstanding deferred loss and are not listed here.",
    ko: "그 외 기간 마감 종목 {count}개는 남아 있는 이연 손실이 없어 여기에 표시되지 않습니다.",
  },
  "tax.wsale.closed.windowClosedBadge": {
    en: "window closed {date}",
    ko: "{date}에 기간 마감",
  },

  // --- per-symbol drill-down ---------------------------------------------------------------------
  "tax.wsale.drilldown.meta_1_1": {
    en: "{lossCount} loss sale · {eventCount} wash-sale event · accounts: {accounts} · first {first} · last {last}",
    ko: "손실 매도 {lossCount}건 · 워시 세일 이벤트 {eventCount}건 · 계좌: {accounts} · 최초 {first} · 최근 {last}",
  },
  "tax.wsale.drilldown.meta_1_n": {
    en: "{lossCount} loss sale · {eventCount} wash-sale events · accounts: {accounts} · first {first} · last {last}",
    ko: "손실 매도 {lossCount}건 · 워시 세일 이벤트 {eventCount}건 · 계좌: {accounts} · 최초 {first} · 최근 {last}",
  },
  "tax.wsale.drilldown.meta_n_1": {
    en: "{lossCount} loss sales · {eventCount} wash-sale event · accounts: {accounts} · first {first} · last {last}",
    ko: "손실 매도 {lossCount}건 · 워시 세일 이벤트 {eventCount}건 · 계좌: {accounts} · 최초 {first} · 최근 {last}",
  },
  "tax.wsale.drilldown.meta_n_n": {
    en: "{lossCount} loss sales · {eventCount} wash-sale events · accounts: {accounts} · first {first} · last {last}",
    ko: "손실 매도 {lossCount}건 · 워시 세일 이벤트 {eventCount}건 · 계좌: {accounts} · 최초 {first} · 최근 {last}",
  },
  // Names the nine-column sale table for the `role="region"` its horizontal scroller now carries --
  // a screen reader announcing an unnamed "region" tells the reader nothing about what they just
  // entered, and this page can have dozens of them expanded at once.
  "tax.wsale.drilldown.tableAriaLabel": {
    en: "Wash-sale detail for {symbol}",
    ko: "{symbol}의 워시 세일 상세",
  },
  "tax.wsale.drilldown.noDetail": {
    en: "No per-sale detail available for this symbol yet -- only the aggregate totals above.",
    ko: "이 종목에 대한 매도별 상세 내역은 아직 없습니다 -- 위의 집계 합계만 제공됩니다.",
  },

  // --- sale row -------------------------------------------------------------------------------
  "tax.wsale.saleRow.notYetTriggered": {
    en: "not yet triggered — repurchase now creates a wash sale",
    ko: "아직 발생하지 않음 — 지금 재매수하면 워시 세일이 발생합니다",
  },
  "tax.wsale.saleRow.notYetTriggeredTitle": {
    en: "This sale's window is still open; nothing disallowed yet. A repurchase before it closes creates the wash sale.",
    ko: "이 매도의 기간은 아직 열려 있으며 아직 아무것도 불인정되지 않았습니다 -- 기간이 마감되기 전에 재매수하면 워시 세일이 발생합니다.",
  },
  "tax.wsale.saleRow.noWashSale": {
    en: "no wash sale — window closed",
    ko: "워시 세일 없음 — 기간 마감",
  },
} as const satisfies MessageShard;
