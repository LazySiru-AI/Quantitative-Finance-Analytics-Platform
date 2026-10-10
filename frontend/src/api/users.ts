/**
 * Typed client for the user-admin API (`backend/app/api/users.py`).
 *
 * Backs the Users panel on the Data page. This is an operator surface, not the self-service
 * `@/api/auth` module (login/logout/change-own-password): every call here acts on *another*
 * account by username, and every mutating one requires the caller to already be signed in as an
 * operator -- the backend enforces that, this client only shapes the requests.
 *
 * Field names mirror the wire (snake_case), matching every other module in this folder. Contract
 * pinned for this build:
 *
 *   GET    /api/users                        -> { users: AdminUser[] }
 *   POST   /api/users               { username, password, role? } -> 201 AdminUser; 409 exists; 422 weak
 *   POST   /api/users/{username}/password    { password } -> 200 { username }; 404; 422 weak
 *   POST   /api/users/{username}/disable     -> 200 { username, disabled }; 404
 *   POST   /api/users/{username}/enable      -> 200 { username, disabled }; 404
 *   POST   /api/users/{username}/revoke-sessions -> 200 { revoked }; 404
 *   POST   /api/users/{username}/role        { role } -> 200 AdminUser; 404;
 *                                             409 {"detail": "last_owner"} demoting the only owner
 *
 * `role` is `"owner" | "member"` throughout -- see `@/auth`'s module docstring for what an owner can
 * reach that a member cannot (the owner-only API prefixes: `/api/tax`, `/api/portfolio`,
 * `/api/import`, `/api/users`, `/api/health/stores`).
 *
 * Every non-OK response throws `ApiRequestError` (`@/api/client`) with the server's own `detail`
 * message unwrapped -- same `detailOf` unwrapping `@/api/paperdesk` and `@/api/imports` use, so a
 * 409 "username already exists" (or "last_owner") or a 422 weak-password reason reaches the panel
 * verbatim instead of a generic failure string.
 */

import { ApiRequestError } from "@/api/client";
import type { UserRole } from "@/api/auth";

// Re-exported so callers of this module (the Users panel) do not also need to import from
// `@/api/auth` for a type that describes a field on `AdminUser` -- one source of truth for the
// literal union, per this module's own docstring on `role`.
export type { UserRole };

export interface AdminUser {
  username: string;
  role: UserRole;
  disabled: boolean;
  created_at: string;
}

const JSON_HEADERS = { "Content-Type": "application/json", Accept: "application/json" };

/**
 * FastAPI wraps an `HTTPException` message in `{"detail": ...}`. Unwrapping it here is what lets a
 * rejected username ("already exists") or password ("too weak") reach the screen instead of a raw
 * JSON blob or the bare status text. Same small parse as `@/api/paperdesk`'s `detailOf` and
 * `@/api/imports`'s own copy -- kept local per this codebase's stated preference for one clear
 * implementation per contract over a shared cross-module utility for a three-line parse.
 */
function detailOf(body: string): string {
  if (!body) return "";
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const detail = (parsed as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      return JSON.stringify(detail);
    }
  } catch {
    // Not JSON. The raw body is still the best thing to show.
  }
  return body;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiRequestError(response.status, detailOf(body) || response.statusText);
  }
  return (await response.json()) as T;
}

export const usersApi = {
  /** Every account this application knows about, operator + everyone they created. */
  list: (signal?: AbortSignal) =>
    requestJson<{ users: AdminUser[] }>("/api/users", { signal: signal ?? null }),

  /** Creates a new account. `role` defaults to `"member"` -- matching the server's own default --
   *  when the caller does not pass one. 409 if `username` already exists; 422 if `password` is too
   *  weak; both surface via `ApiRequestError.message` (see `detailOf` above). */
  create: (username: string, password: string, role: UserRole = "member") =>
    requestJson<AdminUser>("/api/users", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ username, password, role }),
    }),

  /** Resets `username`'s password to a new operator-chosen value -- not the self-service
   *  "current password" flow `@/api/auth`'s `changePassword` covers. */
  setPassword: (username: string, password: string) =>
    requestJson<{ username: string }>(`/api/users/${encodeURIComponent(username)}/password`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ password }),
    }),

  /** Disables `username`'s account. A disabled account cannot sign in; existing sessions are left
   *  alone here -- pair with `revokeSessions` to also end any session already open. */
  disable: (username: string) =>
    requestJson<{ username: string; disabled: boolean }>(
      `/api/users/${encodeURIComponent(username)}/disable`,
      { method: "POST" },
    ),

  enable: (username: string) =>
    requestJson<{ username: string; disabled: boolean }>(
      `/api/users/${encodeURIComponent(username)}/enable`,
      { method: "POST" },
    ),

  /** Ends every session currently open for `username`, without touching the account itself. */
  revokeSessions: (username: string) =>
    requestJson<{ revoked: number }>(`/api/users/${encodeURIComponent(username)}/revoke-sessions`, {
      method: "POST",
    }),

  /** Promotes or demotes `username`. 409 with `detail: "last_owner"` when this would leave the
   *  application with no owner at all -- the panel renders that case as a specific, readable
   *  message rather than the generic action-failed toast (see `UsersPanel.tsx`). */
  setRole: (username: string, role: UserRole) =>
    requestJson<AdminUser>(`/api/users/${encodeURIComponent(username)}/role`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ role }),
    }),
};
