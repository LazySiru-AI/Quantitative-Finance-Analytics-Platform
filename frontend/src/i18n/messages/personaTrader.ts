/**
 * The persona MODEL-DRIVEN paper trader (Phase 10) -- the counterpart to `personaBook.ts` (Phase
 * 6's deterministic call-replay book). Asks the persona's model what to buy/sell at each weekly
 * decision using its consolidated method and a point-in-time market snapshot. Never a real position,
 * never advice, no measured edge -- see `personaTrader.caveatPointInTime`/`caveatNoEdge`, both
 * rendered unconditionally by `PersonaTraderCard.tsx`, never behind a disclosure.
 *
 * Prefix `personaTrader.` -- see `catalog.ts` for the convention.
 */
import type { MessageShard } from "@/i18n/types";

export const personaTrader = {
  "personaTrader.heading": { en: "{name}'s paper trader", ko: "{name}의 페이퍼 트레이더" },
  "personaTrader.experimentalPill": { en: "Experimental", ko: "실험적" },

  // Two caveats, pinned in docs/INFLUENCER-CONTRACT.md's Phase 10 section -- always visible, never
  // collapsed behind an InfoNote disclosure. Keep both distinct; never merge into one sentence.
  "personaTrader.caveatPointInTime": {
    en: "Market data is point-in-time, but the method is distilled from the whole corpus -- this shows how their stated approach would have traded, not a real-time record.",
    ko: "시장 데이터는 시점 기준이지만, 방법론은 전체 자료에서 추출한 것입니다 -- 이는 실시간 기록이 아니라 그들의 방식이 어떻게 거래했을지를 보여줍니다.",
  },
  // LANG-03: the one canonical wording of the "no measured edge / never advice" family. Shorter than
  // the paragraph it replaces, and still always visible -- COPY-STYLE.md rule 6.
  "personaTrader.caveatNoEdge": {
    en: "No measured edge found. Experimental, never advice.",
    ko: "측정된 우위 없음. 실험적 용도이며 조언이 아닙니다.",
  },

  "personaTrader.equity": { en: "Equity", ko: "평가자산" },
  "personaTrader.cash": { en: "Cash", ko: "현금" },
  "personaTrader.returnPct": { en: "Return", ko: "수익률" },
  "personaTrader.vsBenchmark": { en: "vs {benchmark}", ko: "{benchmark} 대비" },
  "personaTrader.benchmarkReturn": { en: "{benchmark} {pct}", ko: "{benchmark} {pct}" },
  "personaTrader.noBenchmark": { en: "No benchmark", ko: "벤치마크 없음" },
  "personaTrader.inception": { en: "Inception", ko: "개시일" },
  "personaTrader.asOfLabel": { en: "As of", ko: "기준일" },
  "personaTrader.notYetDecided": { en: "No decisions yet", ko: "아직 결정 없음" },

  "personaTrader.equityCurveHeading": { en: "Equity curve", ko: "평가자산 추이" },
  "personaTrader.equityCurveEmpty": { en: "No equity history yet.", ko: "아직 평가자산 기록이 없습니다." },
  "personaTrader.equityCurveAriaLabel": {
    en: "Equity from {start} on {startDate} to {end} on {endDate}",
    ko: "{startDate}의 {start}에서 {endDate}의 {end}까지 평가자산 추이",
  },

  "personaTrader.holdingsHeading": { en: "Holdings", ko: "보유 종목" },
  "personaTrader.holdingsEmpty": { en: "No open positions.", ko: "보유 중인 포지션이 없습니다." },
  "personaTrader.lastPrice": { en: "Last price", ko: "최근가" },
  "personaTrader.marketValue": { en: "Market value", ko: "평가금액" },

  "personaTrader.decisionsHeading": { en: "Decision log", ko: "결정 기록" },
  "personaTrader.decisionsEmpty": { en: "No decisions yet.", ko: "아직 결정이 없습니다." },
  "personaTrader.decidedFilled": { en: "{decidedOn} → filled {fillDate}", ko: "{decidedOn} → {fillDate} 체결" },
  "personaTrader.degradedPill": { en: "Degraded", ko: "저하됨" },
  "personaTrader.sideBuy": { en: "buy", ko: "매수" },
  "personaTrader.sideSell": { en: "sell", ko: "매도" },
  "personaTrader.tradeLine": {
    en: "{side} {quantity} {symbol} @ {price}",
    ko: "{symbol} {quantity}주 {price} {side}",
  },
  "personaTrader.rejectionsHeading": { en: "Not filled", ko: "미체결" },
  "personaTrader.rejectionLine": { en: "{symbol}: {reason}", ko: "{symbol}: {reason}" },
  "personaTrader.showAllDecisions": { en: "Show all {count} decisions", ko: "결정 {count}건 모두 보기" },
  "personaTrader.showFewerDecisions": { en: "Show fewer decisions", ko: "간략히 보기" },

  "personaTrader.decideButton": { en: "Run this week's decision", ko: "이번 주 결정 실행" },
  "personaTrader.decidePending": { en: "Deciding…", ko: "결정 중…" },
  "personaTrader.decideErrorFallback": {
    en: "Could not run this week's decision.",
    ko: "이번 주 결정을 실행할 수 없습니다.",
  },

  "personaTrader.backfillDateLabel": { en: "Backfill from", ko: "백필 시작일" },
  "personaTrader.backfillButton": { en: "Backfill from inception", ko: "개시일부터 백필" },
  "personaTrader.backfillRunning": { en: "Backfilling… {decided} decided", ko: "백필 중… {decided}건 결정" },
  "personaTrader.backfillErrorFallback": {
    en: "Could not start the backfill.",
    ko: "백필을 시작할 수 없습니다.",
  },

  "personaTrader.resetButton": { en: "Reset book", ko: "북 초기화" },

  // --- confirmations (EXP-07) --------------------------------------------------------------------
  // Decide and Backfill each put a paid model call behind one click; Reset destroys the book. All
  // three go through `ConfirmSheet`, and every body names what is spent or destroyed -- the rule
  // `pages/data/UsersPanel.tsx` states: confirm what spends or destroys, never what merely
  // recomputes.
  "personaTrader.decideConfirm.title": {
    en: "Run this week's decision?",
    ko: "이번 주 결정을 실행할까요?",
  },
  "personaTrader.decideConfirm.body": {
    en: "Calls the model provider once and spends from the daily cap.",
    ko: "모델 제공자를 1회 호출하며 일일 한도에서 비용이 차감됩니다.",
  },
  "personaTrader.decideConfirm.confirm": { en: "Run decision", ko: "결정 실행" },

  "personaTrader.backfillConfirm.title": {
    en: "Backfill this book from {date}?",
    ko: "{date}부터 이 북을 백필할까요?",
  },
  "personaTrader.backfillConfirm.body": {
    en: "Calls the model provider one call per week since inception, spending from the daily cap.",
    ko: "개시일 이후 매주 1회씩 모델 제공자를 호출하며 일일 한도에서 비용이 차감됩니다.",
  },
  "personaTrader.backfillConfirm.confirm": { en: "Start backfill", ko: "백필 시작" },

  "personaTrader.resetConfirm.title": {
    en: "Reset this trader book?",
    ko: "이 트레이더 북을 초기화할까요?",
  },
  "personaTrader.resetConfirm.body": {
    en: "Deletes every decision, trade and equity point in this book. It cannot be undone.",
    ko: "이 북의 모든 결정·거래·평가자산 기록을 삭제합니다. 되돌릴 수 없습니다.",
  },
  // Deliberately not the same words as `resetButton` -- the sheet's confirm and the control that
  // opened it must be tellable apart, by a screen reader and by a test's accessible-name query.
  "personaTrader.resetConfirm.confirm": { en: "Yes, reset", ko: "예, 초기화" },

  /** The one spend figure this card actually has -- `TraderBook.spent_usd`. Never a projection. */
  "personaTrader.confirmSpentSoFar": {
    en: "Spent on this book so far: {spent}",
    ko: "이 북에 지금까지 지출: {spent}",
  },

  // Paper Desk section -- lists every followed influencer's model-driven trader book beside the
  // reference-agent books and the Phase-6 replay books, fetched independently of both.
  "personaTrader.deskSection.heading": { en: "Persona paper traders", ko: "페르소나 모델 트레이더" },
  "personaTrader.deskSection.caveat": {
    en: "Model-driven, descriptive, experimental -- see each card's own caveats. Not real positions, not advice.",
    ko: "모델 기반의 서술적·실험적 트레이더입니다 -- 각 카드의 안내를 참고하세요. 실제 포지션이 아니며 투자 조언도 아닙니다.",
  },
  "personaTrader.deskSection.loading": {
    en: "Loading persona paper traders...",
    ko: "페르소나 모델 트레이더를 불러오는 중...",
  },
  "personaTrader.deskSection.empty": {
    en: "No persona paper traders yet.",
    ko: "아직 페르소나 모델 트레이더가 없습니다.",
  },
  "personaTrader.deskSection.error": {
    en: "Could not load persona paper traders right now.",
    ko: "지금은 페르소나 모델 트레이더를 불러올 수 없습니다.",
  },
} as const satisfies MessageShard;
