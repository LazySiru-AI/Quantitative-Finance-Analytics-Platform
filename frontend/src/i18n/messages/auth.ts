/**
 * The login screen and the account (change-password / sign-out) page.
 *
 * Keys are prefixed `auth.` -- see `catalog.ts` for why the prefix is load-bearing (the
 * duplicate-key guard in `i18n.test.tsx` keys off it).
 */
import type { MessageShard } from "@/i18n/types";

export const auth = {
  // --- login ---------------------------------------------------------------
  "auth.login.title": { en: "Sign in", ko: "로그인" },
  "auth.login.subtitle": {
    en: "Investing Dashboard",
    ko: "Investing Dashboard",
  },
  "auth.login.username": { en: "Username", ko: "사용자 이름" },
  "auth.login.password": { en: "Password", ko: "비밀번호" },
  "auth.login.submit": { en: "Sign in", ko: "로그인" },
  "auth.login.submitting": { en: "Signing in…", ko: "로그인 중…" },
  "auth.login.invalid": {
    en: "Incorrect username or password.",
    ko: "사용자 이름 또는 비밀번호가 올바르지 않습니다.",
  },
  "auth.login.locked": {
    en: "Too many attempts. Try again in {seconds} seconds.",
    ko: "시도가 너무 많습니다. {seconds}초 후에 다시 시도하세요.",
  },
  "auth.login.error": {
    en: "Could not sign in. Please try again.",
    ko: "로그인할 수 없습니다. 다시 시도하세요.",
  },
  // Shown only after a session that *was* signed in expired mid-use (see `@/auth`'s `expired`).
  // Without it the app swaps the page for the login screen with no explanation, which reads as the
  // app having lost the work rather than the session having timed out.
  "auth.login.expired": {
    en: "You were signed out. Sign in again to continue.",
    ko: "로그아웃되었습니다. 계속하려면 다시 로그인하세요.",
  },

  // --- account -------------------------------------------------------------
  "auth.account.title": { en: "Account", ko: "계정" },
  "auth.account.signedInAs": { en: "Signed in as {username}", ko: "{username}(으)로 로그인됨" },
  "auth.account.changePassword": { en: "Change password", ko: "비밀번호 변경" },
  "auth.account.current": { en: "Current password", ko: "현재 비밀번호" },
  "auth.account.new": { en: "New password", ko: "새 비밀번호" },
  "auth.account.confirm": { en: "Confirm new password", ko: "새 비밀번호 확인" },
  "auth.account.save": { en: "Update password", ko: "비밀번호 업데이트" },
  "auth.account.saving": { en: "Updating…", ko: "업데이트 중…" },
  "auth.account.saved": {
    en: "Password updated. Other sessions were signed out.",
    ko: "비밀번호가 업데이트되었습니다. 다른 세션은 로그아웃되었습니다.",
  },
  "auth.account.mismatch": {
    en: "The new passwords do not match.",
    ko: "새 비밀번호가 일치하지 않습니다.",
  },
  "auth.account.tooShort": {
    en: "New password must be at least 4 characters.",
    ko: "새 비밀번호는 4자 이상이어야 합니다.",
  },
  "auth.account.wrongCurrent": {
    en: "Current password is incorrect.",
    ko: "현재 비밀번호가 올바르지 않습니다.",
  },
  "auth.account.error": {
    en: "Could not update the password. Please try again.",
    ko: "비밀번호를 업데이트할 수 없습니다. 다시 시도하세요.",
  },
  "auth.account.back": { en: "Back to dashboard", ko: "대시보드로 돌아가기" },

  // --- sidebar footer ------------------------------------------------------
  "auth.footer.account": { en: "Account", ko: "계정" },
  "auth.footer.signOut": { en: "Sign out", ko: "로그아웃" },

  // --- auth disabled -------------------------------------------------------
  // With `INVDASH_AUTH_ENABLED=0` the account footer has nothing to render, so the shell used to go
  // silent -- indistinguishable from being signed in. The pill says which of the two it is.
  "auth.gateOff": { en: "Login off", ko: "로그인 꺼짐" },
  "auth.gateOff.detail": {
    en: "Every route is open; the server must stay on loopback.",
    ko: "모든 경로가 열려 있습니다. 서버는 로컬 루프백에만 두어야 합니다.",
  },

  // --- loading -------------------------------------------------------------
  "auth.loading": { en: "Loading…", ko: "불러오는 중…" },

  // --- owner-only gating -----------------------------------------------------
  // Shown in place of a page or Data tab restricted to the owner account. See
  // `@/components/OwnerOnlyNotice` and `@/nav`'s `isOwnerOnlyPath`.
  "auth.ownerOnly.notice": {
    en: "This section is available to the owner account only.",
    ko: "이 섹션은 소유자 계정만 이용할 수 있습니다.",
  },
  "auth.ownerOnly.backLink": { en: "Back to Overview", ko: "개요로 돌아가기" },
} as const satisfies MessageShard;
