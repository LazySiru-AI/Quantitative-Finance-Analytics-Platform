/**
 * Page-level chrome for `/personas`: section headings, tab labels and the copy that
 * wires the individual persona panels together.
 *
 * Prefix `personasPage.` -- see `catalog.ts` for the convention.
 */
import type { MessageShard } from "@/i18n/types";

export const personasPage = {
  /** `PanelBoundary` labels for the two page-level cross-persona panels (`PersonaWatchlist.tsx` /
   * `PersonaRegime.tsx`) -- only shown inline if one of them crashes; each panel already renders
   * its own visible heading. */
  "personasPage.watchlistPanel": { en: "Influencer watchlist", ko: "인플루언서 관심종목" },
  "personasPage.regimePanel": { en: "Regime consensus", ko: "레짐 컨센서스" },

  /** UX-04: what the card-grid `Skeleton` says it is waiting for. Deliberately the same rendered
   * sentence the bare "Loading personas…" placeholder produced -- only the shape around it changed,
   * so the announcement a screen reader hears is unchanged. */
  "personasPage.skeleton.what": { en: "personas", ko: "페르소나" },

  // EXP-24: removing a persona destroys its notes, so it confirms first -- the rule
  // `pages/data/UsersPanel.tsx` states: confirm what spends or destroys, never what recomputes.
  "personasPage.removeConfirm.title": { en: "Remove {name}?", ko: "{name}(을/를) 삭제할까요?" },
  "personasPage.removeConfirm.body": {
    en: "Removes this persona and the notes ingested for it. It cannot be undone.",
    ko: "이 페르소나와 수집된 노트를 삭제합니다. 되돌릴 수 없습니다.",
  },
  // Not the same words as `misc.personas.card.removeButton` -- the sheet's confirm and the row
  // control that opened it must be tellable apart by accessible name.
  "personasPage.removeConfirm.confirm": { en: "Yes, remove", ko: "예, 삭제" },
} as const satisfies MessageShard;
