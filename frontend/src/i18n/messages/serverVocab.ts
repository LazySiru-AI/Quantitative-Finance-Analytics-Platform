/**
 * Vocabulary the **server** owns, translated by id rather than by extraction.
 *
 * Every other shard in this folder holds strings the frontend wrote. This one holds strings the
 * backend sends — Fear & Greed component names and their one-phrase descriptions, the six scheduled
 * economic releases and the FOMC row, session timings, the macro tile / mover labels, FRED series
 * ids. Under 한국어 these were the last English on `/overview`: the chrome translated, the words
 * inside the cards did not.
 *
 * **The rule this shard exists to keep: a server string is data, not an enum.** Every lookup below
 * *falls back to the string the server sent* when it does not recognise the id. There is no
 * exhaustiveness check, no `assertNever`, no throw — a backend that adds an eighth Fear & Greed
 * component or a seventh release must produce one untranslated row, never a blank page. (This app
 * has already taken a page down exactly that way; see `EventCalendar.tsx`'s `kindLabel` note.)
 *
 * **Two lookup shapes, because the server supplies two kinds of handle.**
 *
 *  - *Id-keyed* — `resolveVocab`. The wire carries a stable token (`market_momentum_sp500`,
 *    `before_open`, `us10y`, `DGS10`, `SPY`), so the key is exact and the `en` entry is the label
 *    this app renders in English. It is copied verbatim from the backend, so English output is
 *    unchanged.
 *  - *Text-keyed* — `resolveCalendarProse`. A calendar row carries no release id on the wire, only
 *    the title and detail prose. Matching is therefore on the normalised text, and **English always
 *    renders the server's own string verbatim** rather than our copy of it: the backend owns that
 *    English (`app/market/releases.py`), and a capitalisation drift must show up as an untranslated
 *    Korean row, never as English text this app quietly rewrote.
 *
 * Not here on purpose:
 *  - Calendar *kinds* (`fomc` / `earnings` / `economic_release`) — already translated as
 *    `misc.eventCalendar.kind.*`. One key per fact, app-wide (docs/COPY-STYLE.md rule 2).
 *  - Tickers, FRED series ids, fund brand tokens (`SPDR`, `iShares`, `QQQ`). Identifiers are never
 *    translated (docs/I18N-PLAN.md).
 *  - Free model prose — the Manager brief body, a calendar row's free detail. Nothing keys it, so it
 *    is *labelled* rather than translated: `misc.pill.englishOnly`.
 */
import type { MessageKey } from "@/i18n/catalog";
import type { Language, MessageShard } from "@/i18n/types";
import type { Translator } from "@/i18n/useT";

export const serverVocab = {
  // =====================================================================================================
  // Fear & Greed components -- `FearGreedComponent.key`, from `/api/macro/fear-greed`.
  // `en` is CNN's own component name; `description` is the backend's `raw_description`, the phrase
  // that says what the raw number on that row actually measures.
  // =====================================================================================================
  "serverVocab.fearGreed.market_momentum_sp500.name": { en: "Market Momentum", ko: "시장 모멘텀" },
  "serverVocab.fearGreed.market_momentum_sp500.description": {
    en: "S&P 500 index level, against its 125-day moving average",
    ko: "S&P 500 지수를 125일 이동평균과 비교합니다.",
  },
  "serverVocab.fearGreed.stock_price_strength.name": { en: "Stock Price Strength", ko: "주가 강도" },
  "serverVocab.fearGreed.stock_price_strength.description": {
    en: "stocks at 52-week highs relative to those at 52-week lows",
    ko: "52주 신고가 종목 수를 신저가 종목 수와 비교합니다.",
  },
  "serverVocab.fearGreed.stock_price_breadth.name": { en: "Stock Price Breadth", ko: "주가 폭" },
  "serverVocab.fearGreed.stock_price_breadth.description": {
    en: "summation of volume in advancing versus declining stocks",
    ko: "상승 종목과 하락 종목의 거래량을 누적해 비교합니다.",
  },
  "serverVocab.fearGreed.put_call_options.name": { en: "Put and Call Options", ko: "풋·콜 옵션" },
  "serverVocab.fearGreed.put_call_options.description": {
    en: "put volume divided by call volume",
    ko: "풋 거래량을 콜 거래량으로 나눈 값입니다.",
  },
  "serverVocab.fearGreed.market_volatility_vix.name": { en: "Market Volatility", ko: "시장 변동성" },
  "serverVocab.fearGreed.market_volatility_vix.description": {
    en: "VIX level",
    ko: "VIX 지수 수준입니다.",
  },
  "serverVocab.fearGreed.junk_bond_demand.name": { en: "Junk Bond Demand", ko: "정크본드 수요" },
  "serverVocab.fearGreed.junk_bond_demand.description": {
    en: "yield spread between junk and investment-grade bonds, in percentage points",
    ko: "정크본드와 투자등급 채권의 금리 스프레드입니다(%p).",
  },
  "serverVocab.fearGreed.safe_haven_demand.name": { en: "Safe Haven Demand", ko: "안전자산 수요" },
  "serverVocab.fearGreed.safe_haven_demand.description": {
    en: "20-day stock return minus 20-day Treasury return, in percentage points",
    ko: "20일 주식 수익률에서 20일 국채 수익률을 뺀 값입니다(%p).",
  },

  // --- `FearGreedComponent.raw_unit`: the suffix after the raw number ---------------------------------
  // Absent on a component the backend has no unit for, which renders as *no suffix* rather than a
  // guessed one -- see `formatComponentRaw`'s note in `api/macro.ts`.
  "serverVocab.fearGreed.unit.index": { en: "index", ko: "지수" },
  "serverVocab.fearGreed.unit.ratio": { en: "ratio", ko: "배" },
  "serverVocab.fearGreed.unit.pp": { en: "pp", ko: "%p" },

  // =====================================================================================================
  // Calendar -- the scheduled releases (`app/market/releases.py`), the FOMC row, and session timing.
  // Titles and details are text-keyed; see `resolveCalendarProse`.
  // =====================================================================================================
  "serverVocab.calendar.event.pceInflation.title": {
    en: "PCE inflation (Personal Income and Outlays)",
    ko: "PCE 물가 (개인소득·지출)",
  },
  "serverVocab.calendar.event.pceInflation.detail": {
    en: "BEA -- the Fed's preferred inflation gauge, headline and core PCE",
    ko: "BEA — 연준이 선호하는 물가 지표로, 헤드라인과 근원 PCE를 함께 발표합니다.",
  },
  "serverVocab.calendar.event.cpi.title": { en: "CPI", ko: "소비자물가지수 (CPI)" },
  "serverVocab.calendar.event.cpi.detail": {
    en: "BLS -- consumer price index, headline and core",
    ko: "BLS — 소비자물가지수로, 헤드라인과 근원을 함께 발표합니다.",
  },
  "serverVocab.calendar.event.jobsReport.title": {
    en: "Jobs report (Employment Situation)",
    ko: "고용보고서 (Employment Situation)",
  },
  "serverVocab.calendar.event.jobsReport.detail": {
    en: "BLS -- non-farm payrolls, unemployment rate, average hourly earnings",
    ko: "BLS — 비농업 부문 고용, 실업률, 시간당 평균임금을 발표합니다.",
  },
  "serverVocab.calendar.event.gdp.title": { en: "GDP", ko: "국내총생산 (GDP)" },
  "serverVocab.calendar.event.gdp.detail": {
    en: "BEA -- quarterly output, advance/second/third estimates in successive months",
    ko: "BEA — 분기 생산으로, 속보·잠정·확정치가 매달 차례로 발표됩니다.",
  },
  "serverVocab.calendar.event.ppi.title": { en: "PPI", ko: "생산자물가지수 (PPI)" },
  "serverVocab.calendar.event.ppi.detail": {
    en: "BLS -- producer prices, an early read on the goods side of CPI",
    ko: "BLS — 생산자물가로, CPI 재화 부문을 앞서 가늠하는 지표입니다.",
  },
  "serverVocab.calendar.event.retailSales.title": { en: "Retail sales", ko: "소매판매" },
  "serverVocab.calendar.event.retailSales.detail": {
    en: "Census -- advance monthly retail and food services sales",
    ko: "Census — 월간 소매·요식업 매출 속보치입니다.",
  },
  "serverVocab.calendar.event.fomcMeeting.title": { en: "FOMC meeting", ko: "FOMC 회의" },
  "serverVocab.calendar.event.fomcMeeting.detail": {
    en: "press conference and projections",
    ko: "기자회견과 경제전망이 함께 발표됩니다.",
  },

  // Earnings rows are templated, not enumerable -- one per held symbol. The pattern is matched and
  // the ticker carried through as a placeholder, so the symbol is never translated.
  "serverVocab.calendar.event.earnings.title": { en: "{symbol} earnings", ko: "{symbol} 실적 발표" },
  "serverVocab.calendar.event.earnings.detail": {
    en: "consensus EPS {value}",
    ko: "컨센서스 EPS {value}",
  },

  // --- `SessionTiming` ------------------------------------------------------------------------------
  // `unknown` is deliberately absent: `describeTiming` answers `null` for it so the field is omitted
  // rather than printing the word "unknown".
  "serverVocab.calendar.timing.before_open": { en: "before open", ko: "장 시작 전" },
  "serverVocab.calendar.timing.after_close": { en: "after close", ko: "장 마감 후" },
  "serverVocab.calendar.timing.during_session": { en: "14:00 ET", ko: "동부시간 14:00" },

  // =====================================================================================================
  // Macro tiles (`MacroTile.key`) and the FRED series behind them (`/api/macro/series/{id}`).
  // The series id itself stays verbatim -- `DGS10` is an identifier, not a word.
  // =====================================================================================================
  "serverVocab.macroTile.us10y.label": { en: "US 10-Year Treasury", ko: "미국 10년 국채" },
  "serverVocab.macroTile.2s10s.label": { en: "10Y-2Y Spread", ko: "10년-2년 스프레드" },
  "serverVocab.macroTile.wti.label": { en: "WTI Crude", ko: "WTI 원유" },
  "serverVocab.macroTile.brent.label": { en: "Brent Crude", ko: "브렌트유" },

  "serverVocab.fred.DGS10.title": { en: "US 10-Year Treasury", ko: "미국 10년 국채" },
  "serverVocab.fred.T10Y2Y.title": { en: "10Y-2Y Spread", ko: "10년-2년 스프레드" },
  "serverVocab.fred.DCOILWTICO.title": { en: "WTI Crude", ko: "WTI 원유" },
  "serverVocab.fred.DCOILBRENTEU.title": { en: "Brent Crude", ko: "브렌트유" },

  // =====================================================================================================
  // Movers (`MoverTile.symbol`). Fund brand tokens are kept -- "SPDR", "iShares" and "QQQ" are names,
  // not words -- and only the descriptive half is translated.
  // =====================================================================================================
  "serverVocab.mover.SPY.label": { en: "SPDR S&P 500 ETF", ko: "SPDR S&P 500 ETF" },
  "serverVocab.mover.QQQ.label": { en: "Invesco QQQ Trust", ko: "인베스코 QQQ" },
  "serverVocab.mover.DIA.label": {
    en: "SPDR Dow Jones Industrial Average ETF",
    ko: "SPDR 다우존스 산업평균 ETF",
  },
  "serverVocab.mover.IWM.label": { en: "iShares Russell 2000 ETF", ko: "iShares 러셀 2000 ETF" },
  "serverVocab.mover.XLK.label": { en: "Technology Select Sector SPDR", ko: "기술 섹터 SPDR" },
  "serverVocab.mover.XLF.label": { en: "Financial Select Sector SPDR", ko: "금융 섹터 SPDR" },
  "serverVocab.mover.XLE.label": { en: "Energy Select Sector SPDR", ko: "에너지 섹터 SPDR" },
  "serverVocab.mover.XLV.label": { en: "Health Care Select Sector SPDR", ko: "헬스케어 섹터 SPDR" },
  "serverVocab.mover.XLI.label": { en: "Industrial Select Sector SPDR", ko: "산업재 섹터 SPDR" },
  "serverVocab.mover.XLY.label": {
    en: "Consumer Discretionary Select Sector SPDR",
    ko: "경기소비재 섹터 SPDR",
  },
  "serverVocab.mover.XLP.label": {
    en: "Consumer Staples Select Sector SPDR",
    ko: "필수소비재 섹터 SPDR",
  },
  "serverVocab.mover.XLU.label": { en: "Utilities Select Sector SPDR", ko: "유틸리티 섹터 SPDR" },
  "serverVocab.mover.XLB.label": { en: "Materials Select Sector SPDR", ko: "소재 섹터 SPDR" },
  "serverVocab.mover.XLRE.label": { en: "Real Estate Select Sector SPDR", ko: "부동산 섹터 SPDR" },
  "serverVocab.mover.XLC.label": {
    en: "Communication Services Select Sector SPDR",
    ko: "커뮤니케이션 섹터 SPDR",
  },
  "serverVocab.mover.^VIX.label": { en: "CBOE Volatility Index", ko: "CBOE 변동성 지수" },
  "serverVocab.mover.DX-Y.NYB.label": { en: "US Dollar Index", ko: "미국 달러 지수" },
  "serverVocab.mover.GLD.label": { en: "SPDR Gold Shares", ko: "SPDR 금 현물 ETF" },
  "serverVocab.mover.TLT.label": {
    en: "iShares 20+ Year Treasury Bond ETF",
    ko: "iShares 20년 이상 미국 국채 ETF",
  },
  "serverVocab.mover.BTC-USD.label": { en: "Bitcoin", ko: "비트코인" },
} as const satisfies MessageShard;

// ---------------------------------------------------------------------------------------------------
// Lookups. Every one of them degrades to the server's own string.
// ---------------------------------------------------------------------------------------------------

/** Every key this shard defines, as a runtime set -- what makes "do we know this id?" answerable. */
const KNOWN: ReadonlySet<string> = new Set(Object.keys(serverVocab));

/** `true` when this build has a translation for `key`. Exported for tests and for callers that need
 *  to branch (e.g. render a description element at all). */
export function hasVocab(key: string): boolean {
  return KNOWN.has(key);
}

/**
 * Translate an id-keyed server string, or hand back what the server sent.
 *
 * `fallback` is not decoration: an id this build has never seen renders the backend's own English,
 * which is a cosmetic gap in a Korean page and nothing worse. The alternative -- a closed union over
 * a server-supplied string -- is how a page goes blank.
 */
export function resolveVocab(t: Translator, key: string, fallback: string): string {
  return KNOWN.has(key) ? t(key as MessageKey) : fallback;
}

/** The same, for a nullable field: `null` in, `null` out, so a caller can omit the element. */
export function resolveVocabOrNull(
  t: Translator,
  key: string,
  fallback: string | null,
): string | null {
  if (KNOWN.has(key)) return t(key as MessageKey);
  return fallback;
}

// --- calendar prose (text-keyed) -------------------------------------------------------------------

/** Normalised server text -> the key that translates it. Normalisation is case- and space-insensitive
 *  so a backend capitalisation edit degrades to "untranslated", not to "mismatched". */
const CALENDAR_PROSE: Readonly<Record<string, MessageKey>> = {
  "pce inflation (personal income and outlays)": "serverVocab.calendar.event.pceInflation.title",
  "bea -- the fed's preferred inflation gauge, headline and core pce":
    "serverVocab.calendar.event.pceInflation.detail",
  cpi: "serverVocab.calendar.event.cpi.title",
  "bls -- consumer price index, headline and core": "serverVocab.calendar.event.cpi.detail",
  "jobs report (employment situation)": "serverVocab.calendar.event.jobsReport.title",
  "bls -- non-farm payrolls, unemployment rate, average hourly earnings":
    "serverVocab.calendar.event.jobsReport.detail",
  gdp: "serverVocab.calendar.event.gdp.title",
  "bea -- quarterly output, advance/second/third estimates in successive months":
    "serverVocab.calendar.event.gdp.detail",
  ppi: "serverVocab.calendar.event.ppi.title",
  "bls -- producer prices, an early read on the goods side of cpi":
    "serverVocab.calendar.event.ppi.detail",
  "retail sales": "serverVocab.calendar.event.retailSales.title",
  "census -- advance monthly retail and food services sales":
    "serverVocab.calendar.event.retailSales.detail",
  "fomc meeting": "serverVocab.calendar.event.fomcMeeting.title",
  "press conference and projections": "serverVocab.calendar.event.fomcMeeting.detail",
};

/** `SYMBOL earnings`. The ticker is carried through untranslated. */
const EARNINGS_TITLE = /^([A-Za-z0-9.^-]{1,12}) earnings$/;
/** `consensus EPS $1.39`. The figure is carried through verbatim -- it is a number, not a word. */
const EARNINGS_DETAIL = /^consensus EPS (.+)$/;

function normalise(text: string): string {
  return text.trim().replace(/\s+/g, " ").toLowerCase();
}

/**
 * Translate one calendar row's title or detail.
 *
 * **English is the server's own string, returned untouched.** The backend owns this copy
 * (`app/market/releases.py`, `app/market/fomc.py`); rendering our `en` entry instead would let a
 * drift between the two show up as text this app silently rewrote. In Korean a recognised phrase is
 * translated and everything else -- a new release, a hand-written detail, anything free-form -- comes
 * back verbatim in English, which is what `misc.pill.englishOnly` on the panel discloses.
 */
export function resolveCalendarProse(
  t: Translator,
  lang: Language,
  text: string | null,
): string | null {
  if (text === null || text === "") return text;
  if (lang === "en") return text;

  const key = CALENDAR_PROSE[normalise(text)];
  if (key) return t(key);

  const title = EARNINGS_TITLE.exec(text.trim());
  if (title?.[1]) return t("serverVocab.calendar.event.earnings.title", { symbol: title[1] });

  const detail = EARNINGS_DETAIL.exec(text.trim());
  if (detail?.[1]) return t("serverVocab.calendar.event.earnings.detail", { value: detail[1] });

  return text;
}

/**
 * `true` when a calendar row carries prose this build cannot translate -- the signal behind the
 * panel's "English only" pill. Always `false` in English, where there is nothing to disclose.
 */
export function hasUntranslatedCalendarProse(
  lang: Language,
  texts: readonly (string | null)[],
): boolean {
  if (lang === "en") return false;
  return texts.some((text) => {
    if (text === null || text === "") return false;
    const trimmed = text.trim();
    if (CALENDAR_PROSE[normalise(trimmed)]) return false;
    if (EARNINGS_TITLE.test(trimmed)) return false;
    if (EARNINGS_DETAIL.test(trimmed)) return false;
    return true;
  });
}
