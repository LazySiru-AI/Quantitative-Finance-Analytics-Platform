/**
 * The auth provider: it resolves `/me` on mount, treats disabled-auth as signed in, re-checks the
 * session when a 401 fires `UNAUTHENTICATED_EVENT` -- flipping the app back to anonymous when a
 * session expires mid-use -- and exposes the caller's `role`/`isOwner`. `@/api/auth` is mocked so no
 * request is made; the real event name from `@/api/client` is used.
 */
import { render, screen, waitFor, act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UNAUTHENTICATED_EVENT } from "@/api/client";
import * as authApi from "@/api/auth";
import { AuthProvider, useAuth } from "@/auth";

vi.mock("@/api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/auth")>();
  return { ...actual, fetchAuthState: vi.fn(), logout: vi.fn() };
});

const mockedFetch = vi.mocked(authApi.fetchAuthState);

function Probe() {
  const { status, username, authEnabled, role, isOwner, expired, onSignedIn } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="expired">{String(expired === true)}</span>
      <span data-testid="username">{username ?? "(none)"}</span>
      <span data-testid="enabled">{String(authEnabled)}</span>
      <span data-testid="role">{role ?? "(none)"}</span>
      <span data-testid="isOwner">{String(isOwner)}</span>
      <button type="button" onClick={() => onSignedIn("bob")}>
        sign in
      </button>
    </div>
  );
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("AuthProvider", () => {
  it("resolves an authenticated owner session on mount", async () => {
    mockedFetch.mockResolvedValue({
      auth_enabled: true,
      authenticated: true,
      username: "alice",
      role: "owner",
    });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authed"));
    expect(screen.getByTestId("username").textContent).toBe("alice");
    expect(screen.getByTestId("role").textContent).toBe("owner");
    expect(screen.getByTestId("isOwner").textContent).toBe("true");
  });

  it("resolves an authenticated member session with isOwner false", async () => {
    mockedFetch.mockResolvedValue({
      auth_enabled: true,
      authenticated: true,
      username: "bob",
      role: "member",
    });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authed"));
    expect(screen.getByTestId("role").textContent).toBe("member");
    expect(screen.getByTestId("isOwner").textContent).toBe("false");
  });

  it("is anonymous when auth is on and there is no session, with role null", async () => {
    mockedFetch.mockResolvedValue({
      auth_enabled: true,
      authenticated: false,
      username: null,
      role: null,
    });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anonymous"));
    expect(screen.getByTestId("role").textContent).toBe("(none)");
    expect(screen.getByTestId("isOwner").textContent).toBe("false");
  });

  it("counts disabled auth as signed in, as owner", async () => {
    mockedFetch.mockResolvedValue({
      auth_enabled: false,
      authenticated: false,
      username: null,
      role: "owner",
    });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authed"));
    expect(screen.getByTestId("enabled").textContent).toBe("false");
    expect(screen.getByTestId("username").textContent).toBe("(none)");
    expect(screen.getByTestId("isOwner").textContent).toBe("true");
  });

  it("flips to anonymous when a 401 event fires after the session expires", async () => {
    mockedFetch.mockResolvedValueOnce({
      auth_enabled: true,
      authenticated: true,
      username: "alice",
      role: "owner",
    });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authed"));

    // The session has since expired: the next /me says so.
    mockedFetch.mockResolvedValueOnce({
      auth_enabled: true,
      authenticated: false,
      username: null,
      role: null,
    });
    act(() => {
      window.dispatchEvent(new CustomEvent(UNAUTHENTICATED_EVENT));
    });
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anonymous"));
    expect(screen.getByTestId("isOwner").textContent).toBe("false");
  });

  it("records an expiry when the 401 event follows an authenticated session", async () => {
    // The distinction the notice on the login screen depends on: this session *was* signed in, so
    // "you were signed out" is true.
    mockedFetch.mockResolvedValueOnce({
      auth_enabled: true,
      authenticated: true,
      username: "alice",
      role: "owner",
    });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authed"));
    expect(screen.getByTestId("expired").textContent).toBe("false");

    mockedFetch.mockResolvedValueOnce({
      auth_enabled: true,
      authenticated: false,
      username: null,
      role: null,
    });
    act(() => {
      window.dispatchEvent(new CustomEvent(UNAUTHENTICATED_EVENT));
    });

    await waitFor(() => expect(screen.getByTestId("expired").textContent).toBe("true"));
  });

  it("does not record an expiry for a 401 while already anonymous", async () => {
    // A background poll 401ing on a visitor who was never signed in is the ordinary "not signed in"
    // answer. Telling them they were signed out would be a lie on the first screen they see.
    mockedFetch.mockResolvedValue({
      auth_enabled: true,
      authenticated: false,
      username: null,
      role: null,
    });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anonymous"));

    act(() => {
      window.dispatchEvent(new CustomEvent(UNAUTHENTICATED_EVENT));
    });

    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("expired").textContent).toBe("false");
  });

  it("clears the expiry once a session comes back", async () => {
    mockedFetch.mockResolvedValueOnce({
      auth_enabled: true,
      authenticated: true,
      username: "alice",
      role: "owner",
    });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authed"));

    mockedFetch.mockResolvedValueOnce({
      auth_enabled: true,
      authenticated: false,
      username: null,
      role: null,
    });
    act(() => {
      window.dispatchEvent(new CustomEvent(UNAUTHENTICATED_EVENT));
    });
    await waitFor(() => expect(screen.getByTestId("expired").textContent).toBe("true"));

    // Signing back in must take the notice with it -- it describes a session that is over.
    mockedFetch.mockResolvedValueOnce({
      auth_enabled: true,
      authenticated: true,
      username: "alice",
      role: "owner",
    });
    act(() => {
      screen.getByText("sign in").click();
    });

    await waitFor(() => expect(screen.getByTestId("expired").textContent).toBe("false"));
  });

  it("re-checks /me after onSignedIn so isOwner reflects the real role, not a stale one", async () => {
    // `login()`'s own response carries no `role` (see `@/api/auth`); `onSignedIn` has to trigger a
    // fresh `/me` for `isOwner` to ever become true post-login rather than staying at its initial
    // `false`.
    mockedFetch.mockResolvedValueOnce({
      auth_enabled: true,
      authenticated: false,
      username: null,
      role: null,
    });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anonymous"));

    mockedFetch.mockResolvedValueOnce({
      auth_enabled: true,
      authenticated: true,
      username: "bob",
      role: "owner",
    });
    act(() => {
      screen.getByText("sign in").click();
    });

    // Optimistic: authed immediately, before the re-check resolves.
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authed"));
    // Then corrected: role/isOwner catch up once the background `/me` resolves.
    await waitFor(() => expect(screen.getByTestId("isOwner").textContent).toBe("true"));
    expect(screen.getByTestId("role").textContent).toBe("owner");
  });
});
