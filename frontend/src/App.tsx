import { useEffect, useRef, useState } from "react";
import {
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";

import { AuthProvider, useAuth } from "@/auth";
import ErrorBoundary from "@/components/ErrorBoundary";
import LanguageToggle from "@/components/LanguageToggle";
import NavTelemetry from "@/components/NavTelemetry";
import OwnerOnlyNotice from "@/components/OwnerOnlyNotice";
import PrivacyToggle from "@/components/PrivacyToggle";
import SkipLink from "@/components/SkipLink";
import { TranslatedStatusPill } from "@/components/StatusPill";
import { useFavorites } from "@/favorites";
import { useT } from "@/i18n";
import {
  NAV,
  isOwnerOnlyPath,
  pageLabelKey,
  sectionForPath,
  sectionLabelKey,
  type NavItem,
} from "@/nav";
import Account from "@/pages/Account";
import Activity from "@/pages/Activity";
import AgentDeskLanding from "@/pages/AgentDeskLanding";
import AgentWorkflow from "@/pages/AgentWorkflow";
import Backtest from "@/pages/Backtest";
import Competition from "@/pages/Competition";
import Data from "@/pages/Data";
import Designer from "@/pages/Designer";
import Evidence from "@/pages/Evidence";
import Filers from "@/pages/Filers";
import Macro from "@/pages/Macro";
import Manager from "@/pages/Manager";
import NotFound from "@/pages/NotFound";
import Overview from "@/pages/Overview";
import PaperDesk from "@/pages/PaperDesk";
import Personas from "@/pages/Personas";
import PersonaDetail from "@/pages/personas/PersonaDetail";
import Portfolio from "@/pages/Portfolio";
import ResearchDesk from "@/pages/ResearchDesk";
import Rules from "@/pages/Rules";
import StrategyLanding from "@/pages/StrategyLanding";
import Symbol from "@/pages/Symbol";
import Tax from "@/pages/Tax";
import Timeframes from "@/pages/Timeframes";
import Login from "@/pages/Login";
import TradingAgents from "@/pages/TradingAgents";
import VibeTrading from "@/pages/VibeTrading";

/**
 * The root: authentication wraps everything.
 *
 * `AuthProvider` resolves who the caller is before the dashboard renders, and `AuthGate` chooses
 * what to show for each state -- a brief loading line, the full-screen `Login`, or the dashboard.
 * Nothing below `AuthGate`'s `authed` branch renders until there is a session (or auth is disabled),
 * so no protected page ever flashes on screen for a signed-out visitor.
 */
export default function App() {
  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  );
}

function AuthGate() {
  const { status } = useAuth();
  const { t } = useT();
  if (status === "loading") {
    return <div className="auth-loading">{t("auth.loading")}</div>;
  }
  if (status === "anonymous") {
    return <Login />;
  }
  return <Dashboard />;
}

function Dashboard() {
  return (
    <div className="app">
      {/* First in the DOM, therefore first in the tab order -- the whole point. Everything else in
          the shell (two toggles, the symbol search, three rails, a star per page) sits between the
          top of the document and the page, and a keyboard user met all of it on every navigation
          until this link existed. */}
      <SkipLink />
      {/* Mounted once for every authenticated route: records route/tab hits to the local
          navigation log (no network, no username). Renders nothing. */}
      <NavTelemetry />
      <Sidebar />
      {/* `id` is the skip link's target; `tabIndex={-1}` is what makes the jump move focus rather
          than only scrolling -- without it the next Tab continues from the sidebar link the user
          just left, and the skip link looks broken. */}
      <main className="content" id="content" tabIndex={-1}>
        {/* Keyed on the path so navigating away from a crashed page clears the boundary. Without
            the key, a page that threw stays in its error state for the rest of the session and
            every other route renders the error panel instead of itself. */}
        <RouteBoundary>
          <Route path="/" element={<Navigate to="/overview" replace />} />
          <Route path="/overview" element={<Overview />} />
          <Route path="/portfolio" element={<OwnerGate><Portfolio /></OwnerGate>} />
          <Route path="/designer" element={<OwnerGate><Designer /></OwnerGate>} />
          <Route path="/paper-desk" element={<PaperDesk />} />
          <Route path="/activity" element={<OwnerGate><Activity /></OwnerGate>} />
          <Route path="/symbol" element={<Symbol />} />
          <Route path="/symbol/:symbol" element={<Symbol />} />
          {/* Ticker and Report merged into Symbol. The old routes redirect (preserving the symbol)
              so every existing bare-path link and bookmark still resolves. */}
          <Route path="/ticker" element={<RedirectToSymbol />} />
          <Route path="/ticker/:symbol" element={<RedirectToSymbol />} />
          <Route path="/strategy" element={<StrategyLanding />} />
          <Route path="/evidence" element={<Evidence />} />
          {/* Not in `NAV` any more -- `Evidence` toggles between these three components in place
              (the same pattern `ResearchDesk` uses for `/trading-agents`/`/vibe-trading` below), but
              the routes stay registered so an existing deep link still resolves. */}
          <Route path="/rules" element={<Rules />} />
          <Route path="/timeframes" element={<Timeframes />} />
          <Route path="/backtest" element={<Backtest />} />
          <Route path="/competition" element={<Competition />} />
          <Route path="/report/:symbol?" element={<RedirectToSymbol tab="report" />} />
          {/* Thesis folded into Evidence's fourth tab; Wash Sales folded into the Tax page's Wash
              sales tab. Both old paths redirect rather than 404, so every bookmark, favourite and
              in-app link written against them still resolves -- the same treatment `/ticker` and
              `/institutions` got when their pages merged. */}
          <Route path="/thesis/:symbol?" element={<RedirectToEvidenceThesis />} />
          <Route path="/tax" element={<OwnerGate><Tax /></OwnerGate>} />
          <Route path="/wash-sales" element={<Navigate to="/tax?tab=wash" replace />} />
          <Route path="/filers" element={<Filers />} />
          {/* Institutions and Consensus merged into Filers; old routes redirect to the matching tab. */}
          <Route path="/institutions" element={<RedirectToFilers />} />
          <Route path="/consensus" element={<RedirectToFilers tab="consensus" />} />
          <Route path="/macro" element={<Macro />} />
          <Route path="/data" element={<Data />} />
          <Route path="/agents" element={<AgentDeskLanding />} />
          <Route path="/research-desk" element={<ResearchDesk />} />
          {/* Not in `NAV` any more -- `ResearchDesk` toggles between these two components in place,
              but the routes stay registered so an existing deep link (a bookmark, a link elsewhere
              in the app) still resolves. */}
          <Route path="/trading-agents" element={<TradingAgents />} />
          <Route path="/vibe-trading" element={<VibeTrading />} />
          <Route path="/agent-workflow" element={<AgentWorkflow />} />
          {/* Owner-gated for the same reason `/tax` is: the Manager desk reads across the
              owner-only holdings and tax prefixes, so a member gets a 403 from it with no partial
              content to fall back on. It was ungated while `/portfolio` and `/tax` were not, which
              is a hole rather than a design. */}
          <Route path="/manager" element={<OwnerGate><Manager /></OwnerGate>} />
          <Route path="/personas" element={<Personas />} />
          {/* Backfill folded into the Personas page as an opt-in panel; the old path redirects to it
              with the panel already open. */}
          <Route path="/backfill" element={<Navigate to="/personas?panel=backfill" replace />} />
          {/* Not in `NAV` -- reachable only by following a link off `/personas`, same as
              `/ticker/:symbol` and `/report/:symbol?` above. */}
          <Route path="/personas/:slug" element={<PersonaDetail />} />
          {/* Not in `NAV` -- reachable from the sidebar footer, not the section rail. */}
          <Route path="/account" element={<Account />} />
          {/* A real 404, not a redirect. Silently sending an unknown path to the portfolio makes a
              mistyped or guessed URL indistinguishable from a feature that was never built -- which
              is exactly how a UAT persona concluded the rule engine did not exist. */}
          <Route path="*" element={<NotFound />} />
        </RouteBoundary>
      </main>
    </div>
  );
}

/**
 * The two-level sidebar: a section rail, then the active section's pages.
 *
 * The active section is derived from the pathname rather than held in state. That is what makes a
 * deep link open with the right section already expanded -- someone arriving at `/ticker/AAPL` from
 * a link on the Rules page should see Market, not have to re-find it -- and it means back and
 * forward work without any of this code knowing they exist. State would be a second source of truth
 * to keep in sync with the route, which is the bug `NotFound.tsx` used to demonstrate.
 *
 * Section links are `Link`, not `NavLink`. `NavLink` computes `isActive` against its own `to` only;
 * it cannot know that `/tax` belongs to the section whose first item is `/portfolio`. The page links
 * beneath it are `NavLink`, where matching one path is exactly the question.
 */
/**
 * Legacy per-symbol routes (`/ticker`, `/ticker/:symbol`, `/report/:symbol?`) redirect to the merged
 * Symbol page, preserving the symbol and (for Report) landing on the right tab. A component rather
 * than a bare `<Navigate>` because the destination depends on the route's `:symbol` param.
 */
function RedirectToSymbol({ tab }: { tab?: string }) {
  const { symbol } = useParams();
  const path = symbol ? `/symbol/${symbol}` : "/symbol";
  const query = tab ? `?tab=${tab}` : "";
  return <Navigate to={`${path}${query}`} replace />;
}

/** Legacy filer routes (`/institutions`, `/consensus`) redirect to the merged Filers page's tabs. */
function RedirectToFilers({ tab }: { tab?: string }) {
  return <Navigate to={tab ? `/filers?tab=${tab}` : "/filers"} replace />;
}

/**
 * The legacy Thesis route (`/thesis`, `/thesis/:symbol?`) redirects into Evidence's Thesis tab,
 * carrying the symbol across as `?symbol=` -- the tab reads it from the query string now that it is
 * a tab rather than a route (see `Evidence.tsx`). A component rather than a bare `<Navigate>` for
 * the same reason `RedirectToSymbol` is one: the destination depends on the route's `:symbol` param.
 */
function RedirectToEvidenceThesis() {
  const { symbol } = useParams();
  const query = symbol ? `?tab=thesis&symbol=${encodeURIComponent(symbol.toUpperCase())}` : "?tab=thesis";
  return <Navigate to={`/evidence${query}`} replace />;
}

/**
 * Wraps an owner-only route: renders `children` for the owner, `OwnerOnlyNotice` for a member.
 *
 * A route element rather than a check inside each page, so a member who deep-links to `/tax` (a
 * stale bookmark, a favourite starred before a demotion) never mounts the real page at all -- no
 * fetch fires, no 403 ever reaches that page's own error handling, which was written to describe a
 * *data* problem, not a permissions one. See `@/nav`'s `isOwnerOnlyPath` for which routes this
 * guards and why the list is fixed rather than derived from `NAV`.
 */
function OwnerGate({ children }: { children: React.ReactNode }) {
  const { isOwner } = useAuth();
  return isOwner ? <>{children}</> : <OwnerOnlyNotice />;
}

/**
 * The shell's one search box: type a ticker, Enter opens `/symbol/<SYMBOL>`.
 *
 * `/` focuses it from anywhere on the page -- the shortcut is named in the field's accessible label
 * rather than left for a reader to discover -- but only when focus is not already in a text field,
 * so typing a literal "/" into any other input (a filter, the expression tester) still works. It is
 * a sibling of the nav rails, not a child, for the same reason `LanguageToggle` is: the nav tests
 * count links inside `.nav-sections`/`.nav`/`.nav-favorites`, and a `<form>` here must not perturb
 * those counts. It navigates to the merged Symbol page (`/symbol/<SYMBOL>`), which opens on its
 * Chart tab.
 */
function SymbolJump() {
  const navigate = useNavigate();
  const { t } = useT();
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      const el = document.activeElement as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el?.isContentEditable) return;
      e.preventDefault();
      inputRef.current?.focus();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const symbol = value.trim().toUpperCase();
    if (symbol === "") return;
    setValue("");
    inputRef.current?.blur();
    navigate(`/symbol/${encodeURIComponent(symbol)}`);
  }

  return (
    <form className="symbol-jump" role="search" onSubmit={onSubmit}>
      <input
        ref={inputRef}
        type="text"
        className="symbol-jump-input"
        value={value}
        placeholder={t("shell.symbolJump.placeholder")}
        aria-label={t("shell.symbolJump.label")}
        autoCapitalize="characters"
        autoCorrect="off"
        spellCheck={false}
        onChange={(e) => setValue(e.target.value)}
      />
    </form>
  );
}

function Sidebar() {
  const { pathname } = useLocation();
  const active = sectionForPath(pathname);
  const { favorites } = useFavorites();
  const { t } = useT();
  const { username, authEnabled, isOwner, signOut } = useAuth();
  // Only consulted under the `@media (max-width: 860px)` disclosure in `styles.css`; the toggle
  // button that flips it is itself hidden above that width, so this state has no effect on desktop.
  const [menuOpen, setMenuOpen] = useState(false);

  // A member never sees an owner-only destination in either rail -- not the active section's page
  // list, and not a favourite starred (by this account or, via the shared `localStorage` key, by an
  // owner) before a demotion. `OwnerGate` in `Dashboard` above still stops a stale deep link or a
  // typed URL from reaching the real page; this is what keeps the nav from advertising a page that
  // would show `OwnerOnlyNotice` if clicked.
  const visibleItems = active.items.filter((item) => isOwner || !isOwnerOnlyPath(item.to));
  const visibleFavorites = favorites.filter((item) => isOwner || !isOwnerOnlyPath(item.to));

  return (
    /*
     * A `<div>`, not a `<nav>`. The three rails below are each their own named `<nav>` landmark, and
     * wrapping them in a fourth unnamed one would put a screen reader's landmark list back where it
     * started -- "navigation" containing three more "navigation"s, none of which says which is
     * which. The container is layout; the rails are the navigation.
     */
    <div className="sidebar">
      {/* The brand stays "Investing Dashboard" in both languages -- it is the product's name, not a
          label. The language and privacy switches sit directly beneath it, above the section rail,
          so they are on every page and never scroll out of reach. They are siblings of
          `.nav-sections`/`.nav`/`.nav-favorites`, not children, so the nav tests that count links
          inside those rails are unaffected. */}
      <div className="brand">Investing Dashboard</div>
      {/* Hidden outright above 860px (see `.nav-menu-toggle` in `styles.css`) -- this control and
          the `menuOpen` state above it exist only for the column layout, where the language toggle,
          privacy toggle and favourites rail together were the difference between the fold sitting
          under the page and sitting three phone-screens below it. */}
      <button
        type="button"
        className="nav-menu-toggle"
        aria-expanded={menuOpen}
        aria-controls="sidebar-menu-top sidebar-menu-favorites"
        onClick={() => setMenuOpen((open) => !open)}
      >
        {t("shell.nav.menu")}
      </button>
      <div id="sidebar-menu-top" className={`nav-menu-panel${menuOpen ? " open" : ""}`}>
        <LanguageToggle />
        <PrivacyToggle />
      </div>
      <SymbolJump />
      <nav className="nav-sections" aria-label={t("shell.nav.sections")}>
        {NAV.map((section) => (
          <Link
            key={section.id}
            to={section.items[0].to}
            className={section.id === active.id ? "active" : ""}
            aria-current={section.id === active.id ? "true" : undefined}
          >
            {t(sectionLabelKey(section.id))}
          </Link>
        ))}
      </nav>
      <nav className="nav" aria-label={t("shell.nav.pages")}>
        {visibleItems.map((item) => (
          <NavRow key={item.to} item={item} />
        ))}
      </nav>
      {/*
       * A sibling of `.nav`, not a child of it. Two existing invariants depend on `.nav` holding
       * exactly the active section's page links: the "shows only the active section's pages" test
       * counts `.nav`'s links against `NAV[1].items.length`, and at `/competition` it asserts Tax is
       * absent from `.nav` specifically. A favourite from another section (the whole point of this
       * list -- see `favorites.ts`) would violate both the moment it appeared inside `.nav`, so the
       * favourites section has to live outside it even though the two are visually stacked.
       */}
      <nav
        id="sidebar-menu-favorites"
        className={`nav-favorites${menuOpen ? " open" : ""}`}
        aria-label={t("shell.nav.favorites")}
      >
        <div className="nav-favorites-title">{t("shell.favorites.title")}</div>
        {visibleFavorites.length === 0 ? (
          <p className="nav-favorites-empty">{t("shell.favorites.empty")}</p>
        ) : (
          <div className="nav-favorites-list">
            {visibleFavorites.map((item) => (
              <NavRow key={item.to} item={item} />
            ))}
          </div>
        )}
      </nav>
      {/* The account footer. Only shown when auth is on -- with auth disabled there is no user to
          name and no session to leave, so a "sign out" would strand the viewer on a login screen
          that accepts no one. A sibling of `.nav`/`.nav-favorites` for the same reason they are:
          the nav tests count links inside those rails and must not see these.

          What auth-off gets instead is the pill below. The footer simply vanishing was the whole
          defect: an unauthenticated deployment looked exactly like a signed-in one, so "am I behind
          a login?" had no answer anywhere on screen. */}
      {authEnabled ? (
        <div className="nav-account">
          {/* Blurred by privacy mode along with the money -- a username on a shared screen is the
              one thing on the shell that identifies whose money it is. */}
          {username !== null && <div className="nav-account-user redactable">{username}</div>}
          <NavLink
            to="/account"
            className={({ isActive }) => (isActive ? "active" : "")}
            title={t("shell.profile.blurb")}
          >
            {t("shell.profile.label")}
          </NavLink>
          <button type="button" className="nav-account-signout" onClick={() => void signOut()}>
            {t("auth.footer.signOut")}
          </button>
        </div>
      ) : (
        <div className="nav-account nav-account-gate-off">
          <TranslatedStatusPill
            tone="warn"
            labelKey="auth.gateOff"
            detailKey="auth.gateOff.detail"
            data-testid="auth-gate-off"
          />
        </div>
      )}
    </div>
  );
}

/**
 * One page-rail entry: the destination link plus its favourite toggle.
 *
 * Shared between the page rail and the favourites section, so starring or un-starring a page is
 * the same code and the same button regardless of which list it was clicked from -- the favourites
 * section's own rows get a working un-star button for free rather than needing a second variant.
 *
 * The toggle is a `<button type="button" aria-pressed>`, not a link or a checkbox. It is not a
 * link because it does not navigate -- a link whose activation does something other than go
 * somewhere is the pattern screen reader users are trained to distrust. It is not a bare checkbox
 * because the star also needs a visible glyph and a title tooltip that a checkbox input cannot
 * carry without extra wrapper markup; `aria-pressed` gives the same on/off semantics a checkbox
 * would. `type="button"` is not decoration: this component may end up inside a form somewhere in
 * the app's lifetime, and a bare `<button>` defaults to `type="submit"`, which would submit that
 * form on every star click.
 */
function NavRow({ item }: { item: NavItem }) {
  const { isFavorite, toggleFavorite } = useFavorites();
  const { t } = useT();
  const { to } = item;
  // The display label comes from the catalog, keyed by route, not from `item.label`. The star's
  // accessible name embeds that same translated label, so "Add {label} to favorites" reorders with
  // the sentence in Korean rather than gluing an English word into it.
  const label = t(pageLabelKey(to));
  const fav = isFavorite(to);

  return (
    <div className="nav-row">
      <NavLink to={to} className={({ isActive }) => (isActive ? "active" : "")}>
        {label}
      </NavLink>
      <button
        type="button"
        className={fav ? "fav-toggle is-fav" : "fav-toggle"}
        aria-pressed={fav}
        aria-label={
          fav ? t("shell.favorites.remove", { label }) : t("shell.favorites.add", { label })
        }
        title={fav ? t("shell.favorites.removeShort") : t("shell.favorites.addShort")}
        onClick={() => toggleFavorite(to)}
      >
        <span aria-hidden="true">{fav ? "★" : "☆"}</span>
      </button>
    </div>
  );
}

/** `<Routes>` wrapped in a boundary that resets when the route changes. */
function RouteBoundary({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  return (
    <ErrorBoundary key={location.pathname} area={location.pathname}>
      <Routes>{children}</Routes>
    </ErrorBoundary>
  );
}
