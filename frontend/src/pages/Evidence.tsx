/**
 * Evidence: Backtest, Rules and Timeframes, grouped under one nav entry and switched with a tab.
 *
 * The safe first cut of `docs/STRATEGY-AGENT-UX-ANALYSIS.md` §A3 -- three of the lab's four
 * symbol/rule evidence tools were separate nav entries with no relationship stated between them,
 * even though all three answer the same underlying question ("does this rule show anything, and on
 * what evidence") from three different angles: an event study on one symbol, a rule x interval
 * accuracy grid, and the rule catalogue itself. Grouping them costs nothing structurally -- each tab
 * renders its existing page component completely unchanged, so none of their own state, fetches or
 * tests are touched by this file.
 *
 * **Thesis joined them in the nav demotion.** It was excluded from the first cut on the grounds that
 * running it has permanent side effects (`backend/app/thesis/__init__.py` calls its package "mostly
 * machinery for saying no"), so putting it one tab-click from three tabs that have none looked like a
 * hazard. It is not: a tab click mounts the panel, it does not press Run. The run control still sits
 * behind its own button, still under the warning that names both costs -- a trial spent permanently,
 * and possibly the ticker's one holdout evaluation -- and the trial ledger still renders above it
 * before any run. Nothing about that changed here; only where the panel is mounted did.
 *
 * A shared symbol/scope bar across the four tabs is also out of scope for this first cut -- each
 * page keeps its own symbol input (`Backtest`), scope picker (`Timeframes`) or none at all (`Rules`,
 * which is symbol-independent by design). Unifying that input is a follow-on, not a prerequisite:
 * these three tools were reachable at all before this page, just from three unrelated places.
 *
 * The four routes this page's tabs render (`/backtest`, `/rules`, `/timeframes`, `/thesis/:symbol?`)
 * stay resolvable in `App.tsx` so existing bookmarks and any in-app link to one of them still works
 * -- the first three as their own routes, `/thesis/:symbol?` as a redirect that carries its symbol
 * into this page's Thesis tab.
 *
 * **The active tab lives in the URL, not in a `useState`.** Which tab is showing is navigation state
 * (see `useUrlState`'s own module docstring), and the redirect above depends on it: `/thesis/NVDA`
 * can only land on the right tab if that tab is addressable as `?tab=thesis`. The same applies to
 * `?symbol=`, which is the Thesis tab's own parameter -- the two are independent `useUrlState` keys,
 * so switching tabs never clobbers a symbol and vice versa.
 */
import { useT } from "@/i18n";
import { useUrlState } from "@/hooks/useUrlState";
import Backtest from "@/pages/Backtest";
import Rules from "@/pages/Rules";
import { ThesisSection } from "@/pages/Thesis";
import Timeframes from "@/pages/Timeframes";

type Tab = "backtest" | "timeframes" | "rules" | "thesis";
const TABS: readonly Tab[] = ["backtest", "timeframes", "rules", "thesis"];

const TAB_LABEL_KEYS = {
  backtest: "strategy.evidence.tab.backtest",
  timeframes: "strategy.evidence.tab.timeframes",
  rules: "strategy.evidence.tab.rules",
  thesis: "strategy.evidence.tab.thesis",
} as const;

export default function Evidence() {
  const { t } = useT();
  // `valid: TABS` is what makes a stale or hand-edited `?tab=` land on Backtest instead of matching
  // none of the branches below and rendering an empty page.
  const [tab, setTab] = useUrlState<Tab>("tab", "backtest", { valid: TABS });
  // The Thesis tab's own symbol. `""` (the fallback) means "no symbol yet" and keeps the key out of
  // the URL entirely, so `/evidence` and `/evidence?tab=backtest&symbol=` are not two different
  // addresses for the same view.
  // Explicitly `<string>`: without it `T` infers from the `""` literal and the setter would only
  // accept the empty string back.
  const [thesisSymbol, setThesisSymbol] = useUrlState<string>("symbol", "");

  return (
    <>
      <div className="view-tabs" role="tablist" aria-label={t("strategy.evidence.tabsAriaLabel")}>
        {TABS.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={`timeframe-tab${tab === id ? " active" : ""}`}
            onClick={() => setTab(id)}
          >
            {t(TAB_LABEL_KEYS[id])}
          </button>
        ))}
      </div>

      {/* `embedded` demotes each tab body's own page heading from `<h1>` to `<h2>`. This page
          already renders the document's `<h1>` above, and the tab bodies were written as standalone
          routes (`/backtest`, `/timeframes`, `/rules`) that still exist, so each carries an `<h1>`
          of its own -- two `<h1>`s on one document, which a screen reader's heading list then
          offers as two top-level documents (A11Y-02). The prop is optional on all three, so those
          routes keep their `<h1>`. */}
      {tab === "backtest" && <Backtest embedded />}
      {tab === "timeframes" && <Timeframes embedded />}
      {tab === "rules" && <Rules embedded />}
      {tab === "thesis" && (
        <ThesisSection
          symbol={thesisSymbol === "" ? null : thesisSymbol.toUpperCase()}
          onSymbolChange={setThesisSymbol}
        />
      )}
    </>
  );
}
