/**
 * Shown in place of an owner-only page or panel when the signed-in caller is a member.
 *
 * Every owner-only destination -- Portfolio ("Account"), Tax, Wash Sales, Activity, and the
 * Imports/Reconcile/Sectors/Users tabs on the Data page -- is backed by one of the owner-only API
 * prefixes (`/api/tax`, `/api/portfolio`, `/api/import`, `/api/users`, `/api/health/stores`; see
 * `@/auth`'s module docstring and `@/nav`'s `isOwnerOnlyPath`). Rendering the real page for a member
 * would only ever produce a 403 that page's own fetch was never written to render nicely -- this
 * renders instead, so a member who navigates there (from a stale bookmark, a favourite starred
 * before a demotion, or by hand-editing a Data tab's URL) sees a plain explanation, never a panel
 * stuck on an error banner.
 *
 * Deliberately unalarming (`.callout-info`, the same treatment `styles.css` reserves for "this is
 * not a warning, just a fact") -- a member seeing this has not done anything wrong.
 */
import { Link } from "react-router-dom";

import { useT } from "@/i18n";

export default function OwnerOnlyNotice() {
  const { t } = useT();
  return (
    <div className="panel callout callout-info owner-only-notice">
      <p>{t("auth.ownerOnly.notice")}</p>
      <Link to="/overview">{t("auth.ownerOnly.backLink")}</Link>
    </div>
  );
}
