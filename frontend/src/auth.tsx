/**
 * The client's view of authentication: one provider at the app root, one `useAuth` hook.
 *
 * On mount it asks `GET /api/auth/me` who the caller is and whether auth is even on. Three states
 * follow:
 *
 * - `loading`   -- the first `/me` has not resolved. The app renders nothing but a spinner, so a
 *   protected page never flashes before we know whether the caller may see it.
 * - `anonymous` -- auth is on and there is no valid session. `App` renders only the login screen.
 * - `authed`    -- either a valid session, *or* auth is disabled entirely (`auth_enabled: false`,
 *   the local-dev / single-user case), which counts as signed in so the app renders normally.
 *
 * It also listens for `UNAUTHENTICATED_EVENT` (fired by `@/api/client` on any 401) and re-checks
 * `/me`, so a session that expires mid-use flips the app back to the login screen from whatever page
 * the user was on, with no reload.
 *
 * Alongside `status` it also carries `role`/`isOwner`: `/me` reports one of two roles for any
 * signed-in caller, `"owner"` or `"member"` (a member gets a 403 from the owner-only API prefixes --
 * `/api/tax`, `/api/portfolio`, `/api/import`, `/api/users`, `/api/health/stores` -- and a 403 is
 * *not* treated as `UNAUTHENTICATED_EVENT`, see `@/api/client`). `App`'s sidebar and route table use
 * `isOwner` to hide those destinations and show an inline notice instead of a page that would only
 * ever render an error for a member.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { UNAUTHENTICATED_EVENT } from "@/api/client";
import { fetchAuthState, logout as apiLogout, type UserRole } from "@/api/auth";

export type AuthStatus = "loading" | "anonymous" | "authed";

export interface AuthValue {
  status: AuthStatus;
  /** The signed-in username, or `null` when anonymous or when auth is disabled. */
  username: string | null;
  /** Whether the server has auth turned on at all. */
  authEnabled: boolean;
  /** The signed-in caller's role, or `null` when anonymous. When auth is disabled the server
   *  already reports `"owner"` (single-user local dev), so this is never `null` while `authed`. */
  role: UserRole | null;
  /** `true` exactly when `role === "owner"`. The one thing most call sites actually want -- gating
   *  a nav entry or a route on `role === "owner"` at every call site would work the same, but
   *  spells the check out anew each time and is one string literal away from a silent typo. */
  isOwner: boolean;
  /**
   * `true` when the *last* transition to `anonymous` was a session that expired under the user,
   * rather than a first load that was never signed in. `Login` uses it to say so; without it the app
   * replaces whatever page was open with a bare sign-in form and never explains why, which reads as
   * a crash that lost the work rather than a timeout.
   *
   * Optional on the interface, always supplied by `AuthProvider`: several page tests build an
   * `AuthValue` literal as a test double, and a required field would break files unrelated to auth
   * every time this type grows.
   */
  expired?: boolean;
  /** Re-fetch `/me`. */
  refresh: () => Promise<void>;
  /** Called by the login screen after a successful `login()` to flip the app to `authed`. Sets the
   *  username optimistically from the login response (which carries no `role`) and immediately
   *  re-fetches `/me` in the background so `role`/`isOwner` are correct within one round trip of
   *  landing on the dashboard, rather than staying stale until the next unrelated `refresh()`. */
  onSignedIn: (username: string) => void;
  /** End the session and return to `anonymous` (or stay `authed` when auth is disabled). */
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [username, setUsername] = useState<string | null>(null);
  const [authEnabled, setAuthEnabled] = useState<boolean>(true);
  const [role, setRole] = useState<UserRole | null>(null);
  const [expired, setExpired] = useState(false);

  // Read inside the 401 listener, which is registered once and must not be torn down and rebuilt on
  // every status change just to see the current one. A ref is the whole reason this is not simply
  // `status` in the handler's closure: that closure would capture `"loading"` forever.
  const statusRef = useRef<AuthStatus>("loading");
  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  const refresh = useCallback(async () => {
    const state = await fetchAuthState();
    setAuthEnabled(state.auth_enabled);
    if (!state.auth_enabled || state.authenticated) {
      setUsername(state.username);
      setRole(state.role);
      setStatus("authed");
      // A session that came back (a spurious 401, a re-login in another tab) is not an expiry any
      // more. Clearing here rather than only in `onSignedIn` keeps the notice from outliving the
      // thing it describes.
      setExpired(false);
    } else {
      setUsername(null);
      setRole(null);
      setStatus("anonymous");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const handler = () => {
      // Only a caller who *was* signed in can have expired. A 401 while already anonymous is the
      // ordinary "not signed in" answer to a background poll, and telling that visitor they were
      // signed out would be a lie on the very first screen they see.
      if (statusRef.current === "authed") setExpired(true);
      void refresh();
    };
    window.addEventListener(UNAUTHENTICATED_EVENT, handler);
    return () => window.removeEventListener(UNAUTHENTICATED_EVENT, handler);
  }, [refresh]);

  const onSignedIn = useCallback(
    (name: string) => {
      setUsername(name);
      setStatus("authed");
      setExpired(false);
      // `login()`'s response carries only a username, no `role` (see `@/api/auth`). Re-check `/me`
      // right away rather than leaving `role` at whatever it was before this session (`null`, on a
      // fresh load) until something else happens to call `refresh()`.
      void refresh();
    },
    [refresh],
  );

  const signOut = useCallback(async () => {
    await apiLogout();
    // When auth is disabled there is no session to leave; a "sign out" cannot strand the user on a
    // login screen that will never accept anyone, so stay authed and re-confirm from the server.
    await refresh();
  }, [refresh]);

  const value = useMemo<AuthValue>(
    () => ({
      status,
      username,
      authEnabled,
      role,
      isOwner: role === "owner",
      expired,
      refresh,
      onSignedIn,
      signOut,
    }),
    [status, username, authEnabled, role, expired, refresh, onSignedIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return value;
}
