/**
 * `Data`: the operator page's tab rail. Each of the seven tabs mounts exactly one thing -- the two
 * reused panels (`ImportPanel`, `ReconcilePanel`) verbatim, and this page's own five other panels
 * (Sectors, Desk inception, Users, Data health, About) -- and only the active tab's panel is in the
 * DOM at a time, matching `Tax.tsx`'s own convention.
 *
 * Every API module a mounted panel could call is stubbed here so switching to any tab never hits a
 * real `fetch`; the panels' own mutation/confirmation behaviour (a sector PUT, a user POST, the
 * disable/inception confirm sheets) is covered in depth by their own tests under `pages/data/*` --
 * this file only proves the seven tabs wire to the right seven panels and that a URL round-trips the
 * selection, the same split `Tax.test.tsx` draws between the page shell and its section content.
 *
 * **About is the last tab and visible to everyone** -- `GET /api/data/retention` is not owner-only
 * (see `AboutPanel.tsx`'s own docstring), so unlike Imports/Reconcile/Sectors/Users it is not in
 * `OWNER_ONLY_DATA_TABS` and stays in the rail for the member describe block below too.
 *
 * `@/auth` is mocked the same way `App.test.tsx` mocks it (`mockUseAuth`, owner by default) rather
 * than rendering a real `AuthProvider` -- `Data` calls `useAuth()` directly now (see `Data.tsx`'s
 * module docstring on the four owner-only tabs), and this file renders `<Data />` on its own, with
 * no provider above it. The "member" describe block below is what exercises the non-default branch.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImportPlan } from "@/api/imports";
import type { PaperDeskState } from "@/api/paperdesk";
import type { SectorVocabulary } from "@/api/portfolio";
import type { RefreshStatus, RetentionReport, SocialStatus } from "@/api/dataAdmin";
import type { AdminUser } from "@/api/users";
import type { AuthValue } from "@/auth";

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
const MEMBER_AUTH: AuthValue = { ...OWNER_AUTH, username: "member", role: "member", isOwner: false };
const mockUseAuth = vi.fn<() => AuthValue>(() => OWNER_AUTH);

vi.mock("@/auth", () => ({ useAuth: () => mockUseAuth() }));

const importPreviewMock = vi.fn<() => Promise<ImportPlan>>();
vi.mock("@/api/imports", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/imports")>();
  return { ...actual, importApi: { ...actual.importApi, preview: () => importPreviewMock() } };
});

const sectorsMock = vi.fn<() => Promise<SectorVocabulary>>();
vi.mock("@/api/portfolio", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/portfolio")>();
  return { ...actual, portfolioApi: { ...actual.portfolioApi, sectors: () => sectorsMock() } };
});

const paperdeskStateMock = vi.fn<() => Promise<PaperDeskState>>();
vi.mock("@/api/paperdesk", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/paperdesk")>();
  return { ...actual, paperdeskApi: { ...actual.paperdeskApi, state: () => paperdeskStateMock() } };
});

const usersListMock = vi.fn<() => Promise<{ users: AdminUser[] }>>();
vi.mock("@/api/users", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/users")>();
  return { ...actual, usersApi: { ...actual.usersApi, list: () => usersListMock() } };
});

const refreshStatusMock = vi.fn<() => Promise<RefreshStatus>>();
const socialStatusMock = vi.fn<() => Promise<SocialStatus>>();
const retentionMock = vi.fn<() => Promise<RetentionReport>>();
vi.mock("@/api/dataAdmin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/dataAdmin")>();
  return {
    ...actual,
    dataAdminApi: {
      ...actual.dataAdminApi,
      refreshStatus: () => refreshStatusMock(),
      socialStatus: () => socialStatusMock(),
      retention: () => retentionMock(),
    },
  };
});

const { default: Data } = await import("@/pages/Data");

function paperDeskState(overrides: Partial<PaperDeskState> = {}): PaperDeskState {
  return {
    inception: "2024-01-02",
    inception_default: "2023-06-01",
    inception_is_custom: false,
    design_cutoff: "2025-01-01",
    in_sample_sessions: 0,
    earliest_inception: "2019-01-01",
    latest_inception: "2026-01-01",
    as_of: "2026-09-01",
    latest_bar: "2026-09-01",
    stale_days: 0,
    first_session: "2024-01-02",
    sessions: 10,
    notes: [],
    books: [],
    ...overrides,
  };
}

function refreshStatus(): RefreshStatus {
  return {
    running: false,
    queued: 0,
    refreshed: 0,
    skipped_fresh: 0,
    failed: 0,
    failed_symbols: [],
    processed: 0,
    complete: true,
    stopped_reason: null,
    macro_snapshot: null,
    social_snapshots: "pending",
    started_at: null,
    finished_at: null,
    error: null,
  };
}

function socialStatus(): SocialStatus {
  return {
    healthy: true,
    total_ticks: 0,
    last_tick_at: null,
    last_written: 0,
    last_failed: 0,
    consecutive_all_failed_ticks: 0,
    max_consecutive_all_failed_ticks: 5,
    last_error: null,
  };
}

function retentionReport(): RetentionReport {
  return {
    ledger: { exists: true, transactions: 0 },
    auth: { users: 1 },
    manager_briefs: { count: 0, oldest: null, newest: null },
    manager_chats: { count: 0 },
    persona_chats: { count: 0 },
    persona_vault_notes: { count: 0 },
    desk_runs: { tradingagents: 0, vibedesk: 0, workflow: 0, manager: 0 },
    paperdesk_books: { count: 0 },
    i18n_cache: { present: false },
    retention_policy: "manual",
    purge_endpoints: [],
  };
}

beforeEach(() => {
  mockUseAuth.mockImplementation(() => OWNER_AUTH);
  importPreviewMock.mockReset().mockResolvedValue({
    data_dir: "data/",
    manifest: { path: "data/accounts.toml", present: true, entries: 1, error: null },
    files: [],
    importable: 0,
  });
  sectorsMock.mockReset().mockResolvedValue({ vocabulary: ["SEMI"], map: {} });
  paperdeskStateMock.mockReset().mockResolvedValue(paperDeskState());
  usersListMock.mockReset().mockResolvedValue({ users: [] });
  refreshStatusMock.mockReset().mockResolvedValue(refreshStatus());
  socialStatusMock.mockReset().mockResolvedValue(socialStatus());
  retentionMock.mockReset().mockResolvedValue(retentionReport());
});

function renderData(initialPath = "/data") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Data />
    </MemoryRouter>,
  );
}

describe("Data page", () => {
  it("renders the title and opens on the Imports tab by default", async () => {
    renderData();

    expect(screen.getByRole("heading", { name: "Data" }).textContent).toBe("Data");
    expect(await screen.findByText("reading data/")).toBeTruthy();
    // Only the active tab's panel is mounted -- Sectors' own heading is absent on the default tab.
    expect(screen.queryByText("Sector classification")).toBeNull();
  });

  it("switches to the Reconcile tab and mounts ReconcilePanel", async () => {
    const user = userEvent.setup();
    renderData();

    await user.click(screen.getByRole("tab", { name: "Reconcile" }));
    expect(await screen.findByText("Reconcile against your 1099-B")).toBeTruthy();
  });

  it("switches to the Sectors tab and mounts SectorsPanel", async () => {
    const user = userEvent.setup();
    renderData();

    await user.click(screen.getByRole("tab", { name: "Sectors" }));
    expect(await screen.findByText("Sector classification")).toBeTruthy();
    expect(sectorsMock).toHaveBeenCalled();
  });

  it("switches to the Desk inception tab and mounts InceptionPanel", async () => {
    const user = userEvent.setup();
    renderData();

    await user.click(screen.getByRole("tab", { name: "Desk inception" }));
    expect(await screen.findByText("Paper Desk inception")).toBeTruthy();
    expect(paperdeskStateMock).toHaveBeenCalled();
  });

  it("switches to the Users tab and mounts UsersPanel", async () => {
    const user = userEvent.setup();
    renderData();

    await user.click(screen.getByRole("tab", { name: "Users" }));
    expect(await screen.findByText("No users yet.")).toBeTruthy();
    expect(usersListMock).toHaveBeenCalled();
  });

  it("switches to the Data health tab and mounts DataHealthPanel", async () => {
    const user = userEvent.setup();
    renderData();

    await user.click(screen.getByRole("tab", { name: "Data health" }));
    expect(await screen.findByText("No sweep has run yet.")).toBeTruthy();
    expect(refreshStatusMock).toHaveBeenCalled();
    expect(socialStatusMock).toHaveBeenCalled();
  });

  it("opens directly on the tab named in the URL", async () => {
    renderData("/data?tab=users");

    expect(await screen.findByText("No users yet.")).toBeTruthy();
  });

  it("renders About as the last tab and mounts AboutPanel when selected", async () => {
    const user = userEvent.setup();
    renderData();

    const tabs = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(tabs[tabs.length - 1]).toBe("About");

    await user.click(screen.getByRole("tab", { name: "About" }));
    expect(await screen.findByText("About your data")).toBeTruthy();
    expect(retentionMock).toHaveBeenCalled();
  });

  it("opens directly on the About tab for ?tab=about", async () => {
    renderData("/data?tab=about");

    expect(await screen.findByText("About your data")).toBeTruthy();
  });
});

describe("Data page for a member", () => {
  beforeEach(() => {
    mockUseAuth.mockImplementation(() => MEMBER_AUTH);
  });

  it("hides Imports, Reconcile, Sectors and Users; keeps Desk inception, Data health and About", async () => {
    renderData();

    expect(screen.queryByRole("tab", { name: "Imports" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Reconcile" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Sectors" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Users" })).toBeNull();
    expect(screen.getByRole("tab", { name: "Desk inception" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Data health" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "About" })).toBeTruthy();
  });

  it("falls back to Desk inception rather than the default Imports tab, and never fetches imports", async () => {
    renderData();

    expect(await screen.findByText("Paper Desk inception")).toBeTruthy();
    expect(importPreviewMock).not.toHaveBeenCalled();
  });

  it("falls back to the first visible tab when the URL names a hidden one, without fetching it", async () => {
    renderData("/data?tab=users");

    expect(await screen.findByText("Paper Desk inception")).toBeTruthy();
    expect(screen.queryByText("No users yet.")).toBeNull();
    expect(usersListMock).not.toHaveBeenCalled();
  });

  it("can still switch to Data health, the other tab open to everyone", async () => {
    const user = userEvent.setup();
    renderData();

    await user.click(screen.getByRole("tab", { name: "Data health" }));
    expect(await screen.findByText("No sweep has run yet.")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// The tab in the URL (finding UX-11). This page already kept its tab in `?tab=`; what these pin is
// that it still does after moving onto the shared `useTabParam` hook -- both directions (URL to
// view, and view back to URL) plus the merge that keeps any other param alive.
// ---------------------------------------------------------------------------

/** Shows the current route's path + query, so a test can assert the tab landed in the URL. */
function DataLocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname + location.search}</div>;
}

function renderDataWithProbe(initialPath = "/data") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <DataLocationProbe />
      <Data />
    </MemoryRouter>,
  );
}

describe("Data tab in the URL", () => {
  beforeEach(() => {
    // Owner, so all six tabs are in the rail -- the member case has its own describe block above.
    mockUseAuth.mockReturnValue(OWNER_AUTH);
  });

  it("opens directly on Sectors for /data?tab=sectors", async () => {
    renderDataWithProbe("/data?tab=sectors");

    expect(await screen.findByText("Sector classification")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Sectors" }).getAttribute("aria-selected")).toBe("true");
  });

  it("clicking a tab puts it in the URL, so the panel can be linked to", async () => {
    const user = userEvent.setup();
    renderDataWithProbe();

    await user.click(await screen.findByRole("tab", { name: "Sectors" }));

    expect(screen.getByTestId("location-probe").textContent).toContain("tab=sectors");
  });

  it("falls back to Imports for an unrecognised ?tab= value rather than mounting no panel", async () => {
    renderDataWithProbe("/data?tab=not-a-real-tab");

    expect(await screen.findByText("reading data/")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Imports" }).getAttribute("aria-selected")).toBe("true");
  });
});
