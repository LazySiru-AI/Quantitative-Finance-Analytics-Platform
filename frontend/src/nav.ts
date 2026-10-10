/**
 * The navigation tree, and the single place that knows which section a path belongs to.
 *
 * The app grew to thirteen pages behind one flat sidebar list, and they are not thirteen peers --
 * tax forms sat between the strategy competition and the rule catalog. They do three different
 * jobs, so the nav has two levels: a section rail, and the active section's pages beneath it.
 *
 * **Section membership is derived from the URL, never stored.** No route path encodes its section
 * (`/tax`, not `/portfolio/tax`), because half the app links to the others by bare path --
 * `Rules.tsx` links to `/ticker/SPY`, `Portfolio.tsx` and `Tax.tsx` link to `/activity` -- and
 * nesting would mean rewriting every one of those call sites, plus any bookmark, for no functional
 * gain on an internal tool. `sectionForPath` recovers the section instead.
 *
 * This module is also the only copy of the destination list. `NotFound.tsx` used to keep its own,
 * and it drifted: four pages existed that the 404 never mentioned. Anything that needs to enumerate
 * where a user can go reads it from here.
 */

import type { MessageKey } from "@/i18n/catalog";

export type NavItem = {
  to: string;
  label: string;
  /** One phrase on what the page is for, shown by `NotFound.tsx`. */
  blurb: string;
};

export type NavSection = {
  id: string;
  label: string;
  /** The section's own one-phrase identity, and the test of whether the grouping is honest: a
   *  section you have to caveat to describe is a section holding the wrong pages. */
  blurb: string;
  items: readonly NavItem[];
};

// `satisfies` rather than a `readonly NavSection[]` annotation, and it is load-bearing under this
// project's `noUncheckedIndexedAccess`. An annotation widens the literal to an array, at which point
// `NAV[0]` and `section.items[0]` are `T | undefined` and both `sectionForPath`'s fallback and the
// section rail's "link to this section's first page" need a non-null assertion to compile. Keeping
// the tuple types means the compiler can see that neither is ever empty.
export const NAV = [
  // A one-item section, deliberately. Overview is the only page that reads across all three of the
  // others -- holdings, market context and the reference desk on one screen -- so it belongs to
  // none of them. Filing it under Portfolio would have been the cheaper edit and the wrong one: the
  // section blurbs below are a test of whether a grouping is honest, and "My account, and what to
  // do with it" does not describe a page whose second panel is the yield curve. It sits first
  // because `/` redirects here.
  {
    id: "overview",
    label: "Overview",
    blurb: "The whole application, on one screen",
    items: [{ to: "/overview", label: "Overview", blurb: "Today's picture across every section" }],
  },
  {
    id: "portfolio",
    label: "Account",
    blurb: "My account, and what to do with it",
    items: [
      { to: "/portfolio", label: "Account", blurb: "Holdings, cash and equity" },
      // The planning canvas. Sits beside Account because it plans against the same holdings, but it
      // is intent, not a ledger: what to buy where, decorated with each ticker's live wash-sale
      // status. Owner-only (see `OWNER_ONLY_NAV_PATHS`) -- it names accounts and holdings.
      { to: "/designer", label: "Planner", blurb: "Plan holdings per account, wash-sale aware" },
      // Paper Desk sits here rather than with the competition machinery that produces it. The
      // agents are read as independent references for what to buy in one real account -- not as a
      // portfolio of their own, and not as an experiment result. Its neighbours are the holdings it
      // is consulted against.
      { to: "/paper-desk", label: "Paper Desk", blurb: "What each reference agent is holding now" },
      { to: "/activity", label: "Activity", blurb: "Every transaction, with its source row" },
      // Wash Sales was the sixth entry here until it became a section of the Tax page's own Wash
      // sales tab. It was never a peer of the pages around it: it answers "which repurchase windows
      // are open today", which is the same reader, on the same tab, as "what did wash sales cost me
      // this tax year". `/wash-sales` redirects to `/tax?tab=wash` (see `App.tsx`).
      { to: "/tax", label: "Tax", blurb: "Realized gains, lots and Form 8949" },
    ],
  },
  {
    id: "strategy",
    label: "Strategy Lab",
    blurb: "Testing ideas that are not yet mine",
    items: [
      // First, so the section rail's "link to this section's first page" lands here rather than
      // straight on Competition -- a front door stating what the lab is for and what it has found
      // so far, before any one page's own numbers.
      { to: "/strategy", label: "Overview", blurb: "What the lab tests, and what it has found so far" },
      {
        to: "/evidence",
        label: "Evidence",
        blurb: "Backtests, interval accuracy and the rule catalogue",
      },
      // Thesis was the fourth entry here until it became Evidence's fourth tab. Evidence already
      // grouped the lab's other three symbol/rule evidence tools; a fourth one sitting outside that
      // group was the odd one out, not a separate kind of thing. `/thesis/:symbol?` redirects to
      // `/evidence?tab=thesis&symbol=…` (see `App.tsx`).
      { to: "/competition", label: "Competition", blurb: "Leaderboard, card library and rounds" },
    ],
  },
  {
    id: "agents",
    label: "Agent Desk",
    blurb: "Model-run research desks, on our own data",
    items: [
      // First, for the same reason `/strategy` is first in Strategy Lab above -- the section rail
      // lands here, not on Trading Agents.
      { to: "/agents", label: "Overview", blurb: "What each desk does, and whether the agent layer is up" },
      {
        to: "/manager",
        label: "Manager",
        blurb: "What changed and what matters, curated across every desk",
      },
      {
        to: "/research-desk",
        label: "Research Desk",
        blurb: "Analyst pipeline or committee desk, on our own data",
      },
      {
        to: "/agent-workflow",
        label: "Agent Workflow",
        blurb:
          "Regime → strategy → research → plan → next-open execution, measured against single-tool arms",
      },
      // Personas sits with the other model-run desks rather than under Market, and the distinction
      // is the same one the section blurb draws: this is not a news feed about influencers, it is a
      // per-influencer agent with its own accumulated memory, read from an Obsidian vault. What it
      // shows is one person's stated views, never a measurement of ours.
      {
        to: "/personas",
        label: "Personas",
        blurb: "What each followed influencer has been saying, from their own words",
      },
      // Personas' own manual backfill queue used to sit here, adjacent to Personas because it feeds
      // the same per-influencer notes. "Adjacent to, because it feeds" is the argument for a panel
      // on that page, not for a nav entry of its own -- it is now a button beside the Personas
      // heading, and `/backfill` redirects to `/personas?panel=backfill` (see `App.tsx`).
    ],
  },
  {
    id: "market",
    label: "Market",
    blurb: "The outside world, consulted from either side",
    items: [
      // Ticker and Report merged into one per-symbol page (Chart · Decision · Report · Holders ·
      // News). `/ticker` and `/report` still resolve -- they redirect here in `App.tsx` -- so the
      // many bare-path links across the app (`Rules.tsx` -> `/ticker/SPY`, Overview -> `/report`)
      // keep working without a rewrite.
      { to: "/symbol", label: "Symbol", blurb: "Chart, decision, report, holders and news for one symbol" },
      // Institutions and Consensus merged into Filers (By filer · Consensus). One filer's deltas and
      // "what are all of them doing at once" were always the same reader's two questions; `/institutions`
      // and `/consensus` redirect here.
      { to: "/filers", label: "Filers", blurb: "13F holdings and filer consensus" },
      { to: "/macro", label: "Macro", blurb: "Rates, credit, volatility and sentiment" },
    ],
  },
  // Every operator control in one place, rather than tucked inside a reading page: broker imports,
  // 1099-B reconcile, the sector map, the Paper Desk inception date, user administration, and the
  // data-feed health that previously had no UI at all. It sits last because it is maintenance, not a
  // daily read.
  {
    id: "data",
    label: "Data",
    blurb: "The data this application runs on",
    items: [
      {
        to: "/data",
        label: "Data",
        blurb: "Import, reconcile, and administer the data this application runs on",
      },
    ],
  },
] as const satisfies readonly NavSection[];

/** Every destination, flattened, in nav order. */
// Spread rather than returning `section.items` directly: `flatMap` will not flatten a *readonly*
// array return, so the tuple types `satisfies` preserves above would make this an array of arrays.
export const NAV_ITEMS: readonly NavItem[] = NAV.flatMap((section) => [...section.items]);

/**
 * The section a path belongs to, falling back to the first section.
 *
 * Matches on prefix rather than equality because three routes carry a parameter past their base
 * path -- `/ticker/:symbol`, `/report/:symbol?`, `/thesis/:symbol?`. An equality check would leave
 * `/ticker/AAPL` unmatched, and a deep link into a symbol would open with the wrong section
 * expanded, which is the one case a second nav level has to get right.
 *
 * The `+ "/"` matters: without it `/tax` would prefix-match a hypothetical `/taxonomy`.
 */
export function sectionForPath(pathname: string): NavSection {
  return (
    NAV.find((section) =>
      section.items.some((item) => pathname === item.to || pathname.startsWith(`${item.to}/`)),
    ) ?? NAV[0]
  );
}

/**
 * The i18n keys for a section's or a page's display text.
 *
 * The nav's English lives in this module (the `label`/`blurb` above); its Korean lives in
 * `i18n/messages/nav.ts`, keyed by the stable route (`/paper-desk`) and section id rather than by
 * position, so reordering the tree never repoints a translation. The render sites -- the sidebar in
 * `App.tsx` and the destination list in `NotFound.tsx` -- call these helpers instead of rendering
 * the raw `label`/`blurb`, so both languages flow through one lookup. `i18n.test.tsx` asserts every
 * route here has all three keys, so a page added to `NAV` without translations fails the build
 * rather than throwing a missing-key error into a user's `ErrorBoundary`.
 */
export function sectionLabelKey(id: NavSection["id"]): MessageKey {
  return `nav.section.${id}.label` as MessageKey;
}

export function pageLabelKey(to: NavItem["to"]): MessageKey {
  return `nav.page.${to}.label` as MessageKey;
}

export function pageBlurbKey(to: NavItem["to"]): MessageKey {
  return `nav.page.${to}.blurb` as MessageKey;
}

/**
 * The nav destinations backed entirely by an owner-only API prefix (`/api/tax`, `/api/portfolio` --
 * which covers `/api/portfolio/transactions` -- `/api/import`, `/api/users`, `/api/health/stores`;
 * see `backend/app/api/auth.py` and `@/auth`'s module docstring). A member gets a 403 from every one
 * of these; there is no partial content to show, so the whole route is gated rather than the page
 * being trusted to degrade per-section the way `Overview.tsx` does for its independent panels.
 *
 * Deliberately *not* `/data` itself -- that page mixes owner-only tabs (Imports, Reconcile, Sectors,
 * Users) with ones that are not (Inception reads `/api/paperdesk`, Health reads `/api/market`), so
 * `Data.tsx` gates those four tabs individually rather than this list gating the whole nav entry.
 *
 * `/manager` joined the list when its route was gated: the Manager desk's change feed and daily
 * brief are built from the owner-only holdings and tax prefixes, so a member gets a 403 from it with
 * nothing partial left to show. `/wash-sales` left the list at the same time -- it is no longer a
 * destination at all, only a redirect into `/tax`, which is on the list and does the gating.
 */
const OWNER_ONLY_NAV_PATHS: readonly string[] = [
  "/portfolio",
  "/designer",
  "/tax",
  "/activity",
  "/manager",
];

/** Matches `sectionForPath`'s own prefix rule (`+ "/"` so `/tax` doesn't swallow `/taxonomy`),
 *  applied to the fixed list above rather than to every route in `NAV`. */
export function isOwnerOnlyPath(pathname: string): boolean {
  return OWNER_ONLY_NAV_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}
