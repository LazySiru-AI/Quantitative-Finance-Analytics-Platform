/**
 * The application frame: the language toggle itself, the favourites rail, the error boundaries and
 * the 404.
 *
 * Nav section and page labels are *not* here. They live in `nav.ts`, which is the single list every
 * other part of the app enumerates destinations from, and translating it means changing that
 * module's shape -- so it is scheduled with the rest of the shell edits rather than extracted here.
 */
import type { MessageShard } from "@/i18n/types";

export const shell = {
  // --- language toggle -----------------------------------------------------
  "shell.language.group": { en: "Language", ko: "언어" },
  "shell.language.en": { en: "EN", ko: "EN" },
  "shell.language.ko": { en: "한국어", ko: "한국어" },
  "shell.language.selectEn": { en: "Display in English", ko: "영어로 표시" },
  "shell.language.selectKo": { en: "Display in Korean", ko: "한국어로 표시" },

  // --- privacy toggle ------------------------------------------------------
  // The switch that blurs money on screen (see `@/privacy`). The label names the action about to
  // happen, not the current state -- `aria-pressed` carries the state.
  "shell.privacy.on": { en: "Hide amounts", ko: "금액 숨기기" },
  "shell.privacy.off": { en: "Show amounts", ko: "금액 보기" },

  // --- skip link -----------------------------------------------------------
  // The first focusable element in the shell: one Tab past ~20 sidebar controls to the page itself.
  "shell.skipToContent": { en: "Skip to content", ko: "본문으로 건너뛰기" },

  // --- nav rail landmarks --------------------------------------------------
  // The three rails are separate `<nav>` landmarks, so each needs a name -- a screen reader's
  // landmark list showing "navigation, navigation, navigation" is the same as showing nothing.
  "shell.nav.sections": { en: "Sections", ko: "섹션" },
  "shell.nav.pages": { en: "Pages", ko: "페이지" },
  "shell.nav.favorites": { en: "Favorites", ko: "즐겨찾기" },

  // --- favourites rail -----------------------------------------------------
  "shell.favorites.title": { en: "Favorites", ko: "즐겨찾기" },
  "shell.favorites.empty": {
    en: "Star a page to pin it here.",
    ko: "페이지에 별을 누르면 여기에 고정됩니다.",
  },
  "shell.favorites.add": { en: "Add {label} to favorites", ko: "{label}을(를) 즐겨찾기에 추가" },
  "shell.favorites.remove": {
    en: "Remove {label} from favorites",
    ko: "{label}을(를) 즐겨찾기에서 제거",
  },
  "shell.favorites.addShort": { en: "Add to favorites", ko: "즐겨찾기에 추가" },
  "shell.favorites.removeShort": { en: "Remove from favorites", ko: "즐겨찾기에서 제거" },

  // --- ErrorBoundary (whole page) ------------------------------------------
  // English is byte-identical to what the JSX rendered before extraction, including the em dash and
  // the semicolon: `App.test.tsx` and several page tests match this copy exactly.
  "shell.errorBoundary.title": {
    en: "This page stopped rendering.",
    ko: "이 페이지의 렌더링이 중단되었습니다.",
  },
  "shell.errorBoundary.body": {
    en: "Nothing was written and no figure below is wrong — the page simply could not finish drawing. The other pages are unaffected; the navigation still works.",
    ko: "저장된 내용은 없으며 아래 수치가 틀린 것도 아닙니다. 페이지가 그리기를 끝내지 못했을 뿐입니다. 다른 페이지는 영향을 받지 않으며 내비게이션도 정상 동작합니다.",
  },
  "shell.errorBoundary.hint": {
    en: "If this followed a backend change, a response field the UI expects is the likely cause. Stack trace: browser console.",
    ko: "백엔드 변경 직후라면, UI가 아직 기대하고 있는 응답 필드가 원인일 가능성이 가장 큽니다. 전체 컴포넌트 스택은 브라우저 콘솔에 있습니다.",
  },
  "shell.errorBoundary.retry": { en: "Try again", ko: "다시 시도" },

  // --- PanelBoundary (one panel) -------------------------------------------
  // Two keys rather than one with an optional slot, because the labelled form embeds the label
  // mid-sentence. Korean puts the qualifier before the verb, so a translator needs the whole
  // sentence to reorder -- gluing " — " + label onto a translated stem would pin English word order
  // onto both languages, which is precisely what the catalog exists to prevent.
  "shell.panelBoundary.title": {
    en: "This panel could not be displayed.",
    ko: "이 패널을 표시할 수 없습니다.",
  },
  "shell.panelBoundary.titleLabeled": {
    en: "This panel could not be displayed — {label}.",
    ko: "{label} 패널을 표시할 수 없습니다.",
  },
  "shell.panelBoundary.rest": {
    en: "The rest of this page is unaffected.",
    ko: "이 페이지의 나머지 부분은 영향을 받지 않습니다.",
  },

  // --- symbol jump ---------------------------------------------------------
  // The one search box in the shell: type a ticker, Enter opens its page. `/` focuses it from
  // anywhere, the shortcut screen-reader users are told about via the label. It replaces walking to
  // the Ticker page just to change symbol, and is the shell's answer to "there are five per-symbol
  // forms and no global one".
  "shell.symbolJump.label": { en: "Go to a symbol (press / to focus)", ko: "종목으로 이동 (/ 키로 포커스)" },
  "shell.symbolJump.placeholder": { en: "Symbol…", ko: "종목…" },

  // --- 404 -----------------------------------------------------------------
  "shell.notFound.title": { en: "Not found", ko: "찾을 수 없음" },
  "shell.notFound.path": { en: "Nothing is routed at {path}.", ko: "{path} 경로에 연결된 페이지가 없습니다." },
  "shell.notFound.destinations": { en: "Where you might have meant", ko: "찾으시던 페이지" },

  // --- mobile nav disclosure ------------------------------------------------
  // Under `@media (max-width: 860px)` the sidebar becomes a top bar, and the language toggle,
  // privacy toggle and favourites rail alone pushed the page below the fold on a phone. This button
  // (`.nav-menu-toggle` in `styles.css`) discloses/hides that block; on desktop it never renders.
  "shell.nav.menu": { en: "Menu", ko: "메뉴" },

  // --- profile page (`/account`) --------------------------------------------
  // `/account` is the sign-in/out + change-password stub, not a data page -- it used to share the
  // literal string "Account" with `/portfolio` (the real holdings page, see `nav.ts`), which read as
  // two pages with the same name in the sidebar. Renamed here rather than in `auth.ts` so that
  // module's `auth.account.*`/`auth.footer.account` keys stay put, unreferenced but harmless, per
  // this repo's convention of never deleting translated copy other code might still read;
  // `pages/Account.tsx` and the footer link in `App.tsx` read these two instead.
  "shell.profile.label": { en: "Profile", ko: "프로필" },
  "shell.profile.blurb": { en: "Sign in, sign out, password", ko: "로그인, 로그아웃, 비밀번호" },
} as const satisfies MessageShard;
