/**
 * Filers: institutional 13F/NPORT-P filings, merged into one page (UX refactor 2.2).
 *
 * Before this page existed, "one filer's own book" (`Institutions.tsx`, `/institutions`) and "what
 * many filers are doing together" (`Consensus.tsx`, `/consensus`) were two separate destinations,
 * findable from each other only via a one-directional cross-link. This page puts both under one
 * banner and a two-item `FolderTabs` rail instead, with `useTabParam` keeping the choice (and
 * therefore the URL) shareable and Back-able -- the same pattern `Tax.tsx` already uses for its own
 * four-tab rail.
 *
 * `InstitutionsView`/`ConsensusView` (exported from `Institutions.tsx`/`Consensus.tsx`) are this
 * page's two tab bodies, unchanged from what those files' own default exports already render below
 * their own `<h1>`/subtitle -- this page supplies that banner once instead of twice. What moved into
 * a genuinely shared spot is `frontend/src/pages/filers/shared.tsx`'s `IssuerCell` and action-label
 * map, which the two view components both import; this file renders neither directly, only the
 * banner and the tab rail around the views that do. The old `/institutions` and `/consensus` routes,
 * and their own `<h1>`/subtitle wrappers, stay live until the orchestrator (out of this file's scope
 * fence: `App.tsx`, `nav.ts`) points those paths at this page instead.
 *
 * **No new catalog strings.** `i18n/catalog.ts` assembles `MessageKey` as `keyof typeof CATALOG`
 * (see that file), so a key invented here could never satisfy `t()`'s type without also editing a
 * file this task's scope fence puts off limits. Every string below is therefore an EXISTING catalog
 * entry -- `nav.page./filers.label` for the heading, `market.institutions.*` /
 * `market.consensus.*` for the rest -- reused rather than duplicated; see
 * the comment at each call site for which piece of copy it stands in for. A later pass that adds a
 * dedicated `filers.*` shard (title, "By filer"/"Consensus" tab labels, one merged disclaimer) can
 * replace them one at a time without touching this file's structure.
 */
import { FolderTabs } from "@/components/FolderTabs";
import { useTabParam } from "@/hooks/useTabParam";
import { useT } from "@/i18n";
import { ConsensusView } from "@/pages/Consensus";
import { InstitutionsView } from "@/pages/Institutions";

import "./Filers.css";

export type FilersTab = "institutions" | "consensus";
export const FILERS_TABS: readonly FilersTab[] = ["institutions", "consensus"];

export default function Filers() {
  const { t } = useT();
  // `tab` lives in the URL, not a plain `useState` -- a reload on `/filers?tab=consensus` opens
  // directly on Consensus, and Back restores the previous tab. Matches `Tax.tsx`'s own `?tab=` key
  // exactly (same hook, same option shape) so the two merged pages behave identically. A stale or
  // hostile `?tab=` value falls back to `institutions` via `valid` rather than reaching a component
  // that switches on it -- see `useTabParam`'s own docstring for the failure this prevents.
  const [tab, setTab] = useTabParam<FilersTab>("tab", FILERS_TABS, "institutions");

  // The `<h1>` is the SAME string the sidebar entry uses (`nav.page./filers.label`), not a
  // "Institutions · Consensus" join of the two tab titles. A browser walk clicked "Filers" in the
  // nav and landed on a page headed something else, which reads as a mis-navigation rather than as
  // arrival -- the one job a page title has is to confirm the click worked. The two old titles are
  // still on screen, as the two tab names, which is where they now do their work: they name the
  // choice, not the destination. `nav.ts` is not edited to do this; the key is only referenced.
  const pageTitle = t("nav.page./filers.label");

  return (
    <div className="filers-page">
      <h1>{pageTitle}</h1>
      {/* Reuses Institutions' own subtitle -- both tabs describe the same underlying 13F/NPORT-P
          filings, one per filer and one across filers, so the sentence still holds as a banner for
          either. */}
      <p className="subtitle">{t("market.institutions.subtitle")}</p>

      <FolderTabs
        label={pageTitle}
        active={tab}
        // `FolderTabs` is generic over plain `string` ids; the cast is safe because every `id` below
        // is drawn from `FILERS_TABS`, the same union `useTabParam`'s `allowed` list enforces.
        onChange={(id) => setTab(id as FilersTab)}
        items={[
          { id: "institutions", label: t("market.institutions.title") },
          { id: "consensus", label: t("market.consensus.title") },
        ]}
      >
        {/* Passed as `children`, so `FolderTabs` renders these inside its own `role="tabpanel"`
            wired back to the selected tab. Before that existed the rail promised a panel
            (`role="tab"` always does) and there was nothing on the page carrying the role.

            Only the active tab's subtree mounts -- `ConsensusView`'s own cold-load walk over every
            tracked filer has no reason to run while a reader is looking at one filer's own book, and
            `InstitutionsView`'s funds fetch has no reason to run the other way around. */}
        {tab === "institutions" && <InstitutionsView />}
        {tab === "consensus" && <ConsensusView />}
      </FolderTabs>
    </div>
  );
}
