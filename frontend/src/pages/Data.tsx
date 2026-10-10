/**
 * Data: the operator section gathering everything that manages the application's own data --
 * previously scattered across the Activity and Tax pages (Imports, Reconcile) with no home at all
 * for sector edits, the Paper Desk inception override, user administration, or background-job
 * health. UX refactor 2.3 (`docs/APP-UX-REFACTOR-ANALYSIS.md`) calls for one page, six panels
 * behind a `FolderTabs` rail, rather than a seventh nav entry per panel.
 *
 * **Imports and Reconcile are the existing components, reused verbatim.** `ImportPanel` and
 * `ReconcilePanel` already own their full behaviour (including their own copy, under
 * `activity.*`); this page only decides which tab mounts them. `Activity.tsx`/`Tax.tsx` keep their
 * own copies of both panels for this pass -- relocating those call sites is a separate, later
 * cleanup, not part of adding this page.
 *
 * **Reconcile needs a tax year and this page has no report loaded to read one from** (unlike
 * `Tax.tsx`, which already has `year` in state for its own report fetch). A small local year
 * picker below stands in for that -- same `currentYear - 1` "most recent filed year" default
 * `Tax.tsx`'s own `resolveDefaultYear` falls back to when there is nothing to anchor on, without
 * this page duplicating that function's ledger probe for a tab that has no report to be empty.
 *
 * **Only the active tab is mounted**, same convention `Tax.tsx` established for exactly this
 * reason: six panels, each with its own fetch, must not all fire at once every time this page
 * opens.
 *
 * **One `ToastRegion` for the whole page**, not one per panel. `PaperDesk.tsx` already establishes
 * the pattern of a page-level `useToasts()` + `<ToastRegion>` rather than one wired into the app
 * shell (that remains a later worker's job, per `Toast.tsx`'s own module docstring) -- three of
 * this page's panels mutate something and report back, and a shared queue means an operator
 * flipping between tabs still sees every confirmation in one place instead of three independent
 * stacks.
 *
 * **Four of the six tabs are owner-only.** Imports (`/api/import`), Reconcile (`/api/tax/reconcile`),
 * Sectors (`/api/portfolio/sectors`) and Users (`/api/users`) each call an owner-only API prefix --
 * see `@/nav`'s `isOwnerOnlyPath` docstring and `@/auth`'s module docstring for the full list. A
 * member gets a 403 from every one of them, so those four tab entries are hidden from `FolderTabs`
 * for a member (`OWNER_ONLY_DATA_TABS`) rather than left to render a panel that can only ever show
 * an error. Inception (`/api/paperdesk`) and Data health (`/api/market/*`) call no owner-only prefix
 * and stay visible for everyone. If the URL names a hidden tab -- a bookmark saved while signed in
 * as the owner, or a hand-edited query string -- `effectiveTab` below falls back to the first
 * visible one instead of rendering nothing.
 */
import { useCallback, useState } from "react";

import { useAuth } from "@/auth";
import { FolderTabs, type FolderTabItem } from "@/components/FolderTabs";
import ImportPanel from "@/components/ImportPanel";
import ReconcilePanel from "@/components/ReconcilePanel";
import { ToastRegion, useToasts } from "@/components/Toast";
import { useTabParam } from "@/hooks/useTabParam";
import { useT } from "@/i18n";

import AboutPanel from "./data/AboutPanel";
import DataHealthPanel from "./data/DataHealthPanel";
import InceptionPanel from "./data/InceptionPanel";
import SectorsPanel from "./data/SectorsPanel";
import UsersPanel from "./data/UsersPanel";

import "./Data.css";

type DataTab = "imports" | "reconcile" | "sectors" | "inception" | "users" | "health" | "about";
const DATA_TABS: readonly DataTab[] = [
  "imports",
  "reconcile",
  "sectors",
  "inception",
  "users",
  "health",
  "about",
];

/** See this module's docstring above. */
const OWNER_ONLY_DATA_TABS: readonly DataTab[] = ["imports", "reconcile", "sectors", "users"];

export default function Data() {
  const { t } = useT();
  const { isOwner } = useAuth();
  const [tab, setTab] = useTabParam<DataTab>("tab", DATA_TABS, "imports");
  const { toasts, push: pushToast, dismiss: dismissToast } = useToasts();

  const visibleTabs = isOwner ? DATA_TABS : DATA_TABS.filter((id) => !OWNER_ONLY_DATA_TABS.includes(id));
  // The tab actually shown. Owner: always equal to `tab`. Member on a hidden tab (a stale bookmark,
  // a hand-edited `?tab=`): the first tab a member can see, rather than a blank page or a panel that
  // would only 403. `visibleTabs` always has at least Inception and Health, so the fallback is safe.
  const effectiveTab: DataTab = visibleTabs.includes(tab) ? tab : (visibleTabs[0] ?? "inception");

  // Reconcile is the one reused panel that needs input this page does not otherwise carry -- see
  // the module docstring. Defaults to the most recently completed calendar year, same fallback
  // `Tax.tsx`'s `resolveDefaultYear` uses when it has no ledger activity to anchor on.
  const currentYear = new Date().getFullYear();
  const [reconcileYear, setReconcileYear] = useState(currentYear - 1);
  const reconcileYearOptions = Array.from({ length: 9 }, (_, i) => currentYear - i);

  const onToast = useCallback(
    (spec: Parameters<typeof pushToast>[0]) => pushToast(spec),
    [pushToast],
  );

  const allTabItems: readonly FolderTabItem[] = [
    { id: "imports", label: t("data.tabs.imports") },
    { id: "reconcile", label: t("data.tabs.reconcile") },
    { id: "sectors", label: t("data.tabs.sectors") },
    { id: "inception", label: t("data.tabs.inception") },
    { id: "users", label: t("data.tabs.users") },
    { id: "health", label: t("data.tabs.health") },
    { id: "about", label: t("data.tabs.about") },
  ];
  const tabItems = allTabItems.filter((item) => visibleTabs.includes(item.id as DataTab));

  return (
    <>
      <h1>{t("data.title")}</h1>
      <p className="subtitle">{t("data.subtitle")}</p>

      <FolderTabs
        label={t("data.tabs.label")}
        active={effectiveTab}
        onChange={(id) => setTab(id as DataTab)}
        items={tabItems}
      />

      {effectiveTab === "imports" && <ImportPanel />}

      {effectiveTab === "reconcile" && (
        <>
          <div className="panel">
            <label className="year-select">
              {t("common.date")}
              <select
                value={reconcileYear}
                onChange={(e) => setReconcileYear(Number(e.target.value))}
              >
                {reconcileYearOptions.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <ReconcilePanel year={reconcileYear} />
        </>
      )}

      {effectiveTab === "sectors" && <SectorsPanel onToast={onToast} />}

      {effectiveTab === "inception" && <InceptionPanel onToast={onToast} />}

      {effectiveTab === "users" && <UsersPanel onToast={onToast} />}

      {effectiveTab === "health" && <DataHealthPanel />}

      {effectiveTab === "about" && <AboutPanel />}

      <ToastRegion toasts={toasts} onDismiss={dismissToast} />
    </>
  );
}
