/**
 * `AboutPanel`: a render of `GET /api/data/retention` (`dataAdminApi.retention`, stubbed at the
 * module boundary, matching `DataHealthPanel.test.tsx`'s own approach) plus `useAuth` (mocked the
 * same way `Data.test.tsx` mocks it). `Link` needs a router, so every render here sits inside a
 * `MemoryRouter`.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RetentionReport } from "@/api/dataAdmin";
import type { AuthValue } from "@/auth";

const retentionMock = vi.fn<() => Promise<RetentionReport>>();
vi.mock("@/api/dataAdmin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/dataAdmin")>();
  return {
    ...actual,
    dataAdminApi: { ...actual.dataAdminApi, retention: () => retentionMock() },
  };
});

const OWNER_AUTH: AuthValue = {
  status: "authed",
  username: "owner",
  authEnabled: true,
  role: "owner",
  isOwner: true,
  refresh: async () => {},
  onSignedIn: () => {},
  signOut: async () => {},
};
const mockUseAuth = vi.fn<() => AuthValue>(() => OWNER_AUTH);
vi.mock("@/auth", () => ({ useAuth: () => mockUseAuth() }));

const { default: AboutPanel } = await import("./AboutPanel");

function retentionReport(overrides: Partial<RetentionReport> = {}): RetentionReport {
  return {
    ledger: { exists: true, transactions: 412 },
    auth: { users: 2 },
    manager_briefs: { count: 5, oldest: "2026-08-01T00:00:00+00:00", newest: "2026-09-05T00:00:00+00:00" },
    manager_chats: { count: 3 },
    persona_chats: { count: 7 },
    persona_vault_notes: { count: 162 },
    desk_runs: { tradingagents: 2, vibedesk: 1, workflow: 0, manager: 4 },
    paperdesk_books: { count: 5 },
    i18n_cache: { present: true },
    retention_policy: "manual",
    purge_endpoints: [
      "DELETE /api/manager/chats/{thread_id}",
      "DELETE /api/personas/{slug}",
      "DELETE /api/personas/{slug}/sources/{source_id}",
      "DELETE /api/personas/{slug}/chats/{thread_id}",
      "DELETE /api/personas/{slug}/trader",
    ],
    ...overrides,
  };
}

function renderPanel() {
  return render(
    <MemoryRouter>
      <AboutPanel />
    </MemoryRouter>,
  );
}

describe("AboutPanel", () => {
  beforeEach(() => {
    retentionMock.mockReset();
    mockUseAuth.mockReset();
    mockUseAuth.mockImplementation(() => OWNER_AUTH);
  });

  it("renders the retention counts once loaded", async () => {
    retentionMock.mockResolvedValue(retentionReport());
    renderPanel();

    expect(await screen.findByText("412")).toBeTruthy();
    // manager_chats.count (3) + persona_chats.count (7)
    expect(screen.getByText("10")).toBeTruthy();
    expect(screen.getByText("162")).toBeTruthy();
    expect(screen.getByText("Manager chat threads").closest("a")?.getAttribute("href")).toBe(
      "/manager",
    );
    // "Personas" appears twice -- the retention InfoNote's cross-link and the purge-endpoint list
    // entry for `DELETE /api/personas/{slug}` -- both point at the same page.
    for (const link of screen.getAllByText("Personas")) {
      expect(link.closest("a")?.getAttribute("href")).toBe("/personas");
    }
  });

  it("shows the caller's role and an On login state when auth is enabled", async () => {
    retentionMock.mockResolvedValue(retentionReport());
    renderPanel();

    expect(await screen.findByText("Owner")).toBeTruthy();
    expect(screen.getByText("On")).toBeTruthy();
  });

  it("shows the Login off pill when auth is disabled", async () => {
    mockUseAuth.mockReturnValueOnce({ ...OWNER_AUTH, authEnabled: false });
    retentionMock.mockResolvedValue(retentionReport());
    renderPanel();

    expect(await screen.findByText("Login off")).toBeTruthy();
  });

  it("shows a member's role as Member", async () => {
    mockUseAuth.mockReturnValueOnce({ ...OWNER_AUTH, role: "member", isOwner: false });
    retentionMock.mockResolvedValue(retentionReport());
    renderPanel();

    expect(await screen.findByText("Member")).toBeTruthy();
  });

  it("renders a one-line error note when the retention fetch rejects, and the page stays up", async () => {
    retentionMock.mockRejectedValue(new Error("store unreachable"));
    renderPanel();

    expect(await screen.findByText("store unreachable")).toBeTruthy();
    // Static sections never depend on the fetch -- they render regardless of the error above.
    expect(screen.getByText("Where your data lives")).toBeTruthy();
    expect(screen.getByText("What leaves this machine")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Not advice" })).toBeTruthy();
  });

  it("always renders the not-advice line, reusing the tax disclaimer copy", async () => {
    retentionMock.mockResolvedValue(retentionReport());
    renderPanel();

    expect(await screen.findByRole("heading", { name: "Not advice" })).toBeTruthy();
    expect(screen.getByText("Calculation only, not tax advice.")).toBeTruthy();
  });
});
