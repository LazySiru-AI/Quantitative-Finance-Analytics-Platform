/**
 * Typed client for the auth routes (`backend/app/api/auth.py`).
 *
 * Unlike the data modules, this one does *not* raise `ApiRequestError` on a 4xx. A wrong password
 * is an expected, in-band outcome of `login`, not a failure to surface through the app's generic
 * error path -- and routing it through `ApiRequestError` would fire the global
 * `UNAUTHENTICATED_EVENT` (see `@/api/client`) on every mistyped password, making the provider
 * re-check the session for no reason. So it reads the JSON `detail` itself and throws a small typed
 * error the Login and Account pages can branch on.
 *
 * Field names mirror the wire (snake_case), the same convention every other module here follows.
 */

/**
 * The two roles the server knows about. An owner may reach every owner-only prefix (`/api/tax`,
 * `/api/portfolio`, `/api/import`, `/api/users`, `/api/health/stores`); a member gets a 403 with
 * `{"detail": "owner_only"}` from those. `null` only ever means "no session" -- see `AuthState`.
 */
export type UserRole = "owner" | "member";

/**
 * The shape of `GET /api/auth/me`. `auth_enabled: false` means the whole feature is off, and the
 * server reports `role: "owner"` in that case too -- single-user local dev, everything allowed.
 * `role` is `null` exactly when `authenticated` is `false` (no session, nobody to have a role).
 */
export interface AuthState {
  auth_enabled: boolean;
  authenticated: boolean;
  username: string | null;
  role: UserRole | null;
}

export type LoginErrorKind = "invalid_credentials" | "locked" | "unknown";

export class LoginError extends Error {
  readonly kind: LoginErrorKind;
  readonly retryAfterSeconds?: number;

  constructor(kind: LoginErrorKind, retryAfterSeconds?: number) {
    super(kind);
    this.name = "LoginError";
    this.kind = kind;
    // Assigned conditionally rather than unconditionally: `exactOptionalPropertyTypes` forbids
    // writing an explicit `undefined` into an optional `number` property.
    if (retryAfterSeconds !== undefined) {
      this.retryAfterSeconds = retryAfterSeconds;
    }
  }
}

export type ChangePasswordErrorKind =
  | "invalid_credentials"
  | "too_short"
  | "not_authenticated"
  | "unknown";

export class ChangePasswordError extends Error {
  readonly kind: ChangePasswordErrorKind;

  constructor(kind: ChangePasswordErrorKind) {
    super(kind);
    this.name = "ChangePasswordError";
    this.kind = kind;
  }
}

const JSON_HEADERS = { "Content-Type": "application/json", Accept: "application/json" };

async function readDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : "";
  } catch {
    return "";
  }
}

/** Who the caller is, and whether auth is even enabled. Never throws for an anonymous caller. */
export async function fetchAuthState(): Promise<AuthState> {
  const response = await fetch("/api/auth/me", { headers: { Accept: "application/json" } });
  if (!response.ok) {
    // `/me` is designed never to 401; a non-OK here is a real server problem. Treat it as
    // "auth on, not authenticated" so the app shows the login screen rather than a blank crash.
    return { auth_enabled: true, authenticated: false, username: null, role: null };
  }
  return (await response.json()) as AuthState;
}

/** Attempt a login. Resolves with the username on success; throws `LoginError` otherwise. */
export async function login(username: string, password: string): Promise<{ username: string }> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ username, password }),
  });
  if (response.ok) {
    return (await response.json()) as { username: string };
  }
  if (response.status === 429) {
    let retry: number | undefined;
    try {
      const body = (await response.json()) as { retry_after_seconds?: number };
      retry = body.retry_after_seconds;
    } catch {
      retry = undefined;
    }
    throw new LoginError("locked", retry);
  }
  if (response.status === 401) {
    throw new LoginError("invalid_credentials");
  }
  throw new LoginError("unknown");
}

/** End the current session. Always resolves -- logout is best-effort on the client. */
export async function logout(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST", headers: { Accept: "application/json" } }).catch(
    () => undefined,
  );
}

/** Change the signed-in user's own password. Throws `ChangePasswordError` on any rejection. */
export async function changePassword(current: string, next: string): Promise<void> {
  const response = await fetch("/api/auth/password", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ current, new: next }),
  });
  if (response.ok) return;
  const detail = await readDetail(response);
  if (response.status === 401) {
    throw new ChangePasswordError(
      detail === "not_authenticated" ? "not_authenticated" : "invalid_credentials",
    );
  }
  if (response.status === 422) {
    throw new ChangePasswordError("too_short");
  }
  throw new ChangePasswordError("unknown");
}
