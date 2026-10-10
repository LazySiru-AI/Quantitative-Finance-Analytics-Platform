/**
 * The persona paper book -- a descriptive, cash-constrained paper account following an influencer's
 * live bullish calls. Never a real position, never advice.
 *
 * Prefix `personaBook.` -- see `catalog.ts` for the convention.
 */
import type { MessageShard } from "@/i18n/types";

export const personaBook = {
  "personaBook.heading": { en: "{name}'s paper book", ko: "{name}의 페이퍼 북" },
  "personaBook.caveat": {
    en: "Paper book · {startingCash} from {inception} · {notional} per call · sells on a bearish or neutral flip · not advice.",
    ko: "페이퍼 북 · {inception}부터 {startingCash} · 콜당 {notional} · 약세/중립 전환 시 매도 · 투자 조언 아님.",
  },
  "personaBook.caveatDetail": {
    en: "When cash is fully committed, a fresh bullish call may replace the stalest open position rather than being skipped. Every entry and exit is priced using only the data available as of that date -- no look-ahead.",
    ko: "현금이 모두 투입된 상태에서 새로운 강세 의견이 나오면, 건너뛰는 대신 가장 오래된 보유 포지션을 매도하고 교체할 수 있습니다. 모든 진입과 청산 가격은 해당 시점에 알 수 있었던 데이터만으로 계산되며, 미래 데이터를 미리 반영하지 않습니다.",
  },
  "personaBook.empty": {
    en: "No open positions.",
    ko: "보유 중인 포지션이 없습니다.",
  },
  "personaBook.equity": { en: "Equity", ko: "평가자산" },
  "personaBook.equityInfo": {
    en: "Cash plus the market value of open positions.",
    ko: "현금과 보유 포지션 평가금액의 합계입니다.",
  },
  "personaBook.cash": { en: "Cash", ko: "현금" },
  "personaBook.cashInfo": {
    en: "Uninvested paper cash available for new calls.",
    ko: "새로운 콜에 사용할 수 있는 투자되지 않은 페이퍼 현금입니다.",
  },
  "personaBook.marketValue": { en: "Market value", ko: "평가금액" },
  "personaBook.unrealisedPnl": { en: "Unrealized P&L", ko: "미실현 손익" },
  "personaBook.unrealisedPnlInfo": {
    en: "Market value minus cost basis on open positions.",
    ko: "보유 포지션의 평가금액에서 매입원가를 뺀 값입니다.",
  },
  "personaBook.realisedPnl": { en: "Realized P&L", ko: "실현 손익" },
  "personaBook.realisedPnlInfo": {
    en: "Total profit or loss booked on closed trades.",
    ko: "청산된 거래에서 확정된 손익의 합계입니다.",
  },
  "personaBook.returnPct": { en: "Return", ko: "수익률" },
  "personaBook.returnInfo": {
    en: "Equity versus starting cash, since inception.",
    ko: "개시 시점 이후 시작 현금 대비 평가자산의 변화율입니다.",
  },
  "personaBook.entryDate": { en: "Entry date", ko: "진입일" },
  "personaBook.entryPrice": { en: "Entry price", ko: "진입가" },
  "personaBook.lastPrice": { en: "Last price", ko: "최근가" },
  "personaBook.asOfLower": { en: "as of {date}", ko: "{date} 기준" },
  "personaBook.exitDate": { en: "Exit date", ko: "청산일" },
  "personaBook.exitPrice": { en: "Exit price", ko: "청산가" },
  "personaBook.reason": { en: "Reason", ko: "사유" },
  "personaBook.saidOn": { en: "Date", ko: "날짜" },

  "personaBook.holdingsHeading": { en: "Holdings", ko: "보유 종목" },
  "personaBook.tradesHeading": { en: "Closed trades", ko: "청산 거래" },
  "personaBook.tradesEmpty": { en: "No closed trades yet.", ko: "아직 청산된 거래가 없습니다." },
  "personaBook.skippedHeading": { en: "Skipped calls", ko: "건너뛴 의견" },
  "personaBook.skippedEmpty": { en: "No skipped calls.", ko: "건너뛴 의견이 없습니다." },

  "personaBook.trade.reason.flipBearish": { en: "sold: turned bearish", ko: "매도: 약세로 전환" },
  "personaBook.trade.reason.flipNeutral": { en: "sold: turned neutral", ko: "매도: 중립으로 전환" },
  "personaBook.trade.reason.replaced": {
    en: "sold to fund another call",
    ko: "다른 콜 자금 마련을 위해 매도",
  },

  "personaBook.skipped.reason.noCash": { en: "no cash free", ko: "여유 현금 없음" },
  "personaBook.skipped.reason.noMarketData": { en: "no market data", ko: "시장 데이터 없음" },
  "personaBook.skipped.reason.noBarSince": { en: "no price yet", ko: "아직 가격 없음" },

  // Paper Desk section -- lists every followed influencer's paper book beside the reference-agent
  // books, fetched independently of the desk's own state.
  "personaBook.deskSection.heading": {
    en: "Persona paper books",
    ko: "페르소나 페이퍼 북",
  },
  "personaBook.deskSection.caveat": {
    en: "Simulated capital. Not real positions, not advice.",
    ko: "모의 자본입니다. 실제 포지션이 아니며 조언도 아닙니다.",
  },
  "personaBook.deskSection.loading": {
    en: "Loading persona paper books...",
    ko: "페르소나 페이퍼 북 불러오는 중...",
  },
  "personaBook.deskSection.empty": {
    en: "No persona paper books yet.",
    ko: "아직 페르소나 페이퍼 북이 없습니다.",
  },
  "personaBook.deskSection.error": {
    en: "Could not load persona paper books right now.",
    ko: "지금은 페르소나 페이퍼 북을 불러올 수 없습니다.",
  },
} as const satisfies MessageShard;
