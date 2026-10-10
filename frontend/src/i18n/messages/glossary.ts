/**
 * The glossary: one short definition per piece of jargon this app puts on screen.
 *
 * Three audits (UX-19, LANG-10, LANG-11) found the same defect repeatedly: a term of art rendered
 * with no definition anywhere in the product. `q` as a bare column head. `INSUFFICIENT` as a pill.
 * "holdout" as a heading on six tables. A reader who does not already know what a q-value is cannot
 * learn it from this application, and the pages that use those words are exactly the pages where
 * misreading one changes what the reader concludes.
 *
 * So the definition travels with the word: `components/Term.tsx` renders any term below as inline
 * text with a dotted underline and a tooltip that opens on hover **and** on keyboard focus. This
 * shard is its catalog.
 *
 * **Two keys per term, and the slug between them is the component's prop.**
 *
 *   `glossary.<slug>.term`  the short display name, used when `<Term>` is given no children.
 *   `glossary.<slug>.def`   the definition -- 120 characters, the standard note budget.
 *
 * `GlossarySlug` below is derived from the `.term` keys, so `<Term k="qValue">` is a compile error
 * the moment that entry is renamed or removed, and a slug can never exist with only half its pair.
 *
 * **A definition here must agree with docs/DEFINITIONS.md**, which is the register of what every
 * headline statistic actually claims. Where that file states a rule -- independent means
 * non-overlapping; an insufficient cell renders no number, not a zero -- the definition says the
 * same thing in the space a tooltip has.
 *
 * **A definition is not a disclaimer.** Nothing a reader is worse off for not seeing goes in here:
 * "not tax advice", the in-sample warning and the 13F lag keep their visible short form plus a pill
 * (docs/COPY-STYLE.md rule 6). A tooltip explains a word; it never hides a caveat.
 */
import type { MessageShard } from "@/i18n/types";

export const glossary = {
  // --- significance ------------------------------------------------------------------------------
  "glossary.pValue.term": { en: "p-value", ko: "p값" },
  "glossary.pValue.def": {
    en: "How often chance alone would produce a result this big. Not corrected for testing many rules — see q.",
    ko: "우연만으로 이만한 결과가 나올 빈도입니다. 여러 규칙을 검정한 점은 보정되지 않았습니다 — q값 참고.",
  },
  "glossary.qValue.term": { en: "q-value", ko: "q값" },
  "glossary.qValue.def": {
    en: "The p-value after correcting for how many rules were tested (Benjamini–Hochberg). Each study sets its own cutoff.",
    ko: "검정한 규칙 수를 보정한 p값입니다(벤저미니–호크버그). 기준값은 연구마다 따로 정합니다.",
  },
  "glossary.indep.term": { en: "Independent windows", ko: "독립 윈도우" },
  "glossary.indep.def": {
    en: "Non-overlapping triggers only. Overlapping forward windows are not separate draws, so significance uses this count.",
    ko: "겹치지 않는 발생만 셉니다. 겹친 미래 구간은 별개 표본이 아니므로 유의성 판단은 이 수를 씁니다.",
  },
  "glossary.insufficient.term": { en: "INSUFFICIENT", ko: "표본 부족" },
  "glossary.insufficient.def": {
    en: "Too few independent observations to report a figure. No number is shown — not a zero, not a blank.",
    ko: "독립 관측치가 너무 적어 수치를 낼 수 없습니다. 0도 공백도 아닌, 아무 숫자도 표시하지 않습니다.",
  },

  // --- evidence and testing ----------------------------------------------------------------------
  "glossary.outOfSample.term": { en: "Out-of-sample", ko: "표본 외(OOS)" },
  "glossary.outOfSample.def": {
    en: "Measured on data held back after the rule was chosen — the only test that can refute it.",
    ko: "규칙을 고른 뒤 남겨 둔 데이터로 측정합니다 — 규칙을 반증할 수 있는 유일한 검정입니다.",
  },
  "glossary.holdout.term": { en: "Holdout", ko: "홀드아웃" },
  "glossary.holdout.def": {
    en: "Data held back and spent once. Looking at it a second time stops it being a test.",
    ko: "따로 떼어 두고 단 한 번만 쓰는 데이터입니다. 두 번째로 보는 순간 검정이 아니게 됩니다.",
  },

  // --- performance -------------------------------------------------------------------------------
  "glossary.drawdown.term": { en: "Drawdown", ko: "낙폭" },
  "glossary.drawdown.def": {
    en: "How far below its running high a value has fallen. Peak-to-now, or peak-to-trough where the label says so.",
    ko: "값이 직전 고점 대비 얼마나 내려왔는지입니다. 고점 대비 현재, 라벨이 그렇게 말하면 고점 대비 저점입니다.",
  },
  "glossary.exposure.term": { en: "Exposure", ko: "익스포저" },
  "glossary.exposure.def": {
    en: "Fraction of bars holding a position. In the market 4% of the time carries 4% of the risk.",
    ko: "포지션을 보유한 봉의 비율입니다. 시장에 4%의 시간만 있으면 위험도 4%만 집니다.",
  },
  "glossary.bp.term": { en: "Basis point", ko: "베이시스 포인트" },
  "glossary.bp.def": {
    en: "One hundredth of a percentage point. 25 bps is 0.25%.",
    ko: "1퍼센트포인트의 100분의 1입니다. 25bp는 0.25%입니다.",
  },

  // --- rules and runs ----------------------------------------------------------------------------
  "glossary.ruleDsl.term": { en: "Rule DSL", ko: "규칙 DSL" },
  "glossary.ruleDsl.def": {
    en: "The small expression language rules are written in: price fields, indicators, and comparisons.",
    ko: "규칙을 작성하는 작은 표현식 언어입니다: 가격 항목, 지표, 비교 연산자.",
  },
  "glossary.rsi.term": { en: "RSI", ko: "RSI" },
  "glossary.rsi.def": {
    en: "Relative strength index: a 0–100 momentum gauge. rsi(14) reads the last 14 bars.",
    ko: "상대강도지수: 0–100 범위의 모멘텀 지표입니다. rsi(14)는 최근 14개 봉을 읽습니다.",
  },
  "glossary.regime.term": { en: "Regime", ko: "국면" },
  "glossary.regime.def": {
    en: "The market environment a run classifies into — trend, chop, high volatility — before it picks a card.",
    ko: "실행이 카드를 고르기 전에 분류하는 시장 환경입니다 — 추세, 횡보, 고변동성 등.",
  },
  "glossary.degraded.term": { en: "Degraded", ko: "저하됨" },
  "glossary.degraded.def": {
    en: "The stage ran and produced output, but the output failed a grounding check. Not a clean pass, not a failure.",
    ko: "스테이지는 실행되어 결과를 냈지만 그 결과가 근거 검사를 통과하지 못했습니다. 성공도 실패도 아닙니다.",
  },
} as const satisfies MessageShard;

/**
 * Every term's slug -- the `k` prop `components/Term.tsx` takes.
 *
 * Derived from the `.term` keys rather than written out a second time: a hand-maintained union
 * would go stale silently, and the whole point of a typed prop is that a term this shard does not
 * define cannot be rendered.
 */
export type GlossarySlug = {
  [K in keyof typeof glossary]: K extends `glossary.${infer S}.term` ? S : never;
}[keyof typeof glossary];

/** The slugs at runtime, for the test that walks every entry. Same source as the type above. */
export const GLOSSARY_SLUGS: readonly GlossarySlug[] = Object.keys(glossary)
  .filter((key): key is `glossary.${GlossarySlug}.term` => key.endsWith(".term"))
  .map((key) => key.slice("glossary.".length, -".term".length) as GlossarySlug);
