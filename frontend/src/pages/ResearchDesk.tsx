/**
 * Research Desk: one nav entry, one page, over the two existing model-run research desks.
 *
 * `docs/STRATEGY-AGENT-UX-ANALYSIS.md`'s A4 flags Trading Agents and Vibe Trading as the same page
 * shape built twice -- a run form, a progress board, per-stage output, a final report, and a
 * recent-runs list, both returning a `DeskRun` (see `docs/AGENT-DESK-CONTRACT.md`) -- sitting behind
 * two separate nav entries. This is the safe first cut of that finding: fold the entry point into
 * one page with a toggle, and reuse `TradingAgents`/`VibeTrading` verbatim underneath it.
 *
 * A deeper dedup -- one shared recent-runs list, one shared explainer, instead of each desk carrying
 * its own -- is explicitly out of scope here. Each desk still renders its own `<h1>` and its own
 * static explainer below this page's toggle; nothing inside either component was touched.
 *
 * `/trading-agents` and `/vibe-trading` stay registered as routes in `App.tsx` (just not in
 * `nav.ts` any more), so an existing deep link -- a run's own bookmark, a link from somewhere else in
 * the app -- still resolves to the same page it always did.
 */
import { useState } from "react";

import { useT } from "@/i18n";
import TradingAgents from "@/pages/TradingAgents";
import VibeTrading from "@/pages/VibeTrading";

type Desk = "analyst" | "committee";

export default function ResearchDesk() {
  const { t } = useT();
  const [desk, setDesk] = useState<Desk>("analyst");

  return (
    <>
      <div
        className="view-tabs"
        role="tablist"
        aria-label={t("agentDesk.researchDesk.tabsAriaLabel")}
      >
        <button
          type="button"
          role="tab"
          aria-selected={desk === "analyst"}
          className={`timeframe-tab${desk === "analyst" ? " active" : ""}`}
          onClick={() => setDesk("analyst")}
        >
          {t("agentDesk.researchDesk.tab.analyst")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={desk === "committee"}
          className={`timeframe-tab${desk === "committee" ? " active" : ""}`}
          onClick={() => setDesk("committee")}
        >
          {t("agentDesk.researchDesk.tab.committee")}
        </button>
      </div>

      {desk === "analyst" ? <TradingAgents embedded /> : <VibeTrading embedded />}
    </>
  );
}
