/**
 * Strings owned by the interaction primitives -- `FolderTabs`, `Skeleton`, `ConfirmSheet`, `Toast`.
 *
 * These sit beside `ui.ts` rather than inside it for one reason: `ui.ts` is the vocabulary of
 * *display* primitives (a pill's word, a scroll panel's expand affordance), and this shard is the
 * vocabulary of *interaction* -- what the application says back when a person picks, waits,
 * changes something, or undoes it. `docs/APP-UX-REFACTOR-ANALYSIS.md` §3.6 is the contract these
 * implement; keeping their strings together is what makes "one action, one reaction" checkable by
 * reading a single file.
 *
 * A page never picks these strings. It renders a primitive, and the primitive picks. Anything a
 * *page* needs to say about its own selection ("Closed ({count})" on the Account page's account
 * rail) belongs in that page's shard, not here.
 */
import type { MessageShard } from "@/i18n/types";

export const interaction = {
  // --- FolderTabs ----------------------------------------------------------
  // The rail itself is labelled by its caller (`label` prop, spoken as the tablist's accessible
  // name). What lives here is only what the component says on its own behalf.
  "interaction.tabs.overflowLabel": { en: "More", ko: "더 보기" },
  // Rendered visually-hidden inside a tab that carries a badge, so a screen reader hears
  // "Roth IRA, 12 positions" rather than "Roth IRA 12".
  "interaction.tabs.badgeLabel": { en: "{badge}", ko: "{badge}" },

  // --- Skeleton ------------------------------------------------------------
  // A skeleton is not silent: it says what is being waited for, and how far along when the caller
  // knows. `common.loading` covers the unqualified case.
  "interaction.skeleton.progress": { en: "{done} of {total}", ko: "{total}개 중 {done}개" },
  "interaction.skeleton.label": { en: "Loading {what}…", ko: "{what} 불러오는 중…" },

  // --- ConfirmSheet --------------------------------------------------------
  // Rule 19 of the refactor plan: a mutation previews, confirms, and re-fetches only what it
  // changed. The preview heading is the primitive's, the preview *content* is the caller's.
  "interaction.confirm.title": { en: "Confirm", ko: "확인" },
  "interaction.confirm.previewTitle": { en: "What will change", ko: "변경되는 항목" },
  "interaction.confirm.confirm": { en: "Confirm", ko: "확인" },
  "interaction.confirm.working": { en: "Working…", ko: "처리 중…" },

  // --- Toast ---------------------------------------------------------------
  "interaction.toast.undo": { en: "Undo", ko: "실행 취소" },
  "interaction.toast.dismiss": { en: "Dismiss", ko: "닫기" },
  "interaction.toast.undone": { en: "Undone", ko: "취소됨" },
  "interaction.toast.region": { en: "Notifications", ko: "알림" },
} as const satisfies MessageShard;
