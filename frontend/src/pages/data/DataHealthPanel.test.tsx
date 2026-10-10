/**
 * `DataHealthPanel`: a render of `GET /api/market/refresh/status`, `GET /api/market/social/status`
 * and `GET /api/data/freshness`, plus the `POST /api/market/refresh` trigger, all via `dataAdminApi`
 * (stubbed at the module boundary).
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FreshnessReport, RefreshStatus, RefreshTriggerResult, SocialStatus } from "@/api/dataAdmin";
import type { NavSummary } from "@/api/telemetry";

const refreshStatusMock = vi.fn<() => Promise<RefreshStatus>>();
const socialStatusMock = vi.fn<() => Promise<SocialStatus>>();
const freshnessMock = vi.fn<() => Promise<FreshnessReport>>();
const triggerRefreshMock = vi.fn<() => Promise<RefreshTriggerResult>>();
const navSummaryMock = vi.fn<(days: number) => Promise<NavSummary>>();

vi.mock("@/api/dataAdmin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/dataAdmin")>();
  return {
    ...actual,
    dataAdminApi: {
      ...actual.dataAdminApi,
      refreshStatus: () => refreshStatusMock(),
      socialStatus: () => socialStatusMock(),
      freshness: () => freshnessMock(),
      triggerRefresh: () => triggerRefreshMock(),
    },
  };
});

vi.mock("@/api/telemetry", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/telemetry")>();
  return {
    ...actual,
    telemetryApi: {
      ...actual.telemetryApi,
      summary: (days: number) => navSummaryMock(days),
    },
  };
});

const { default: DataHealthPanel } = await import("./DataHealthPanel");

function navSummary(overrides: Partial<NavSummary> = {}): NavSummary {
  return {
    days: 30,
    since: "2026-08-11T00:00:00+00:00",
    total: 2,
    routes: [
      { path: "/tax", tab: "lots", hits: 12, last_ts: "2026-09-08T09:00:00+00:00" },
      { path: "/overview", tab: null, hits: 5, last_ts: "2026-09-07T09:00:00+00:00" },
    ],
    ...overrides,
  };
}

function refreshStatus(overrides: Partial<RefreshStatus> = {}): RefreshStatus {
  return {
    running: false,
    queued: 40,
    refreshed: 38,
    skipped_fresh: 0,
    failed: 2,
    failed_symbols: ["XYZ:1d"],
    processed: 40,
    complete: true,
    stopped_reason: null,
    macro_snapshot: "ok",
    social_snapshots: "12 written, 0 failed",
    started_at: "2026-09-06T09:00:00+00:00",
    finished_at: "2026-09-06T09:02:00+00:00",
    error: null,
    ...overrides,
  };
}

function socialStatus(overrides: Partial<SocialStatus> = {}): SocialStatus {
  return {
    healthy: true,
    total_ticks: 100,
    last_tick_at: "2026-09-06T09:00:00+00:00",
    last_written: 5,
    last_failed: 0,
    consecutive_all_failed_ticks: 0,
    max_consecutive_all_failed_ticks: 5,
    last_error: null,
    ...overrides,
  };
}

function freshnessReport(overrides: Partial<FreshnessReport> = {}): FreshnessReport {
  return {
    as_of: "2026-09-08T12:00:00+00:00",
    sources: [
      {
        key: "bars_daily",
        freshness_class: "day_frame",
        policy: "startup_sweep",
        provider: "polygon",
        last_updated: "2026-09-08T09:00:00+00:00",
        age_seconds: 180,
        status: "fresh",
        detail: "Updated by the last sweep.",
        refreshable: true,
        enabled: true,
      },
      {
        key: "live_quotes",
        freshness_class: "intraday",
        policy: "streaming",
        provider: "polygon",
        last_updated: null,
        age_seconds: null,
        status: "live",
        detail: "Streaming feed.",
        refreshable: false,
        enabled: true,
      },
    ],
    refresh: refreshStatus(),
    live: {
      enabled: true,
      transport: "stream",
      running: true,
      healthy: true,
      watched: 3,
      symbols: ["AAA", "BBB"],
      market_state: "regular",
      last_snapshot_at: "2026-09-08T11:59:00+00:00",
      started_at: "2026-09-08T09:00:00+00:00",
    },
    ...overrides,
  };
}

describe("DataHealthPanel", () => {
  beforeEach(() => {
    refreshStatusMock.mockReset();
    socialStatusMock.mockReset();
    freshnessMock.mockReset();
    triggerRefreshMock.mockReset();
    navSummaryMock.mockReset();
    // Every pre-existing test below is exercising the refresh/social/freshness panels, not this one
    // -- give it an empty-but-resolved default so it never dangles a promise those tests don't await.
    navSummaryMock.mockResolvedValue(navSummary({ total: 0, routes: [] }));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the refresh sweep and social scheduler status once both load", async () => {
    refreshStatusMock.mockResolvedValue(refreshStatus());
    socialStatusMock.mockResolvedValue(socialStatus());
    freshnessMock.mockResolvedValue(freshnessReport());
    render(<DataHealthPanel />);

    expect(await screen.findByText("Complete")).toBeTruthy();
    expect(screen.getByText("40 / 40")).toBeTruthy();
    expect(screen.getByText("Healthy")).toBeTruthy();
    expect(screen.getByText("100")).toBeTruthy();
  });

  it("shows Unhealthy and the last error when the social scheduler is failing", async () => {
    refreshStatusMock.mockResolvedValue(refreshStatus());
    socialStatusMock.mockResolvedValue(
      socialStatus({ healthy: false, consecutive_all_failed_ticks: 5, last_error: "disk full" }),
    );
    freshnessMock.mockResolvedValue(freshnessReport());
    render(<DataHealthPanel />);

    expect(await screen.findByText("Unhealthy")).toBeTruthy();
    expect(screen.getByText("Last error: disk full")).toBeTruthy();
  });

  it("shows the never-run / never-ticked empty states", async () => {
    refreshStatusMock.mockResolvedValue(refreshStatus({ started_at: null, finished_at: null }));
    socialStatusMock.mockResolvedValue(socialStatus({ total_ticks: 0, last_tick_at: null }));
    freshnessMock.mockResolvedValue(freshnessReport());
    render(<DataHealthPanel />);

    expect(await screen.findByText("No sweep has run yet.")).toBeTruthy();
    expect(screen.getByText("Has not ticked yet.")).toBeTruthy();
  });

  it("shows the generic error message when a status fetch rejects", async () => {
    refreshStatusMock.mockRejectedValue(new Error("network down"));
    socialStatusMock.mockResolvedValue(socialStatus());
    freshnessMock.mockResolvedValue(freshnessReport());
    render(<DataHealthPanel />);

    expect(await screen.findByText("network down")).toBeTruthy();
  });

  it("renders the freshness table rows with mapped labels, including an unknown status", async () => {
    refreshStatusMock.mockResolvedValue(refreshStatus());
    socialStatusMock.mockResolvedValue(socialStatus());
    freshnessMock.mockResolvedValue(
      freshnessReport({
        sources: [
          {
            key: "bars_daily",
            freshness_class: "day_frame",
            policy: "startup_sweep",
            provider: "polygon",
            last_updated: "2026-09-08T09:00:00+00:00",
            age_seconds: 180,
            status: "fresh",
            detail: "Updated by the last sweep.",
            refreshable: true,
            enabled: true,
          },
          {
            // Cast past the closed union on purpose: proves an unknown key/status renders as a
            // neutral fallback instead of throwing (the exhaustiveness-check failure mode this repo
            // has hit before).
            key: "brand_new_source" as unknown as "bars_daily",
            freshness_class: "local",
            policy: "manual",
            provider: "carbon",
            last_updated: null,
            age_seconds: null,
            status: "quarantined" as unknown as "unknown",
            detail: "Not yet classified.",
            refreshable: false,
            enabled: true,
          },
        ],
      }),
    );

    expect(() => render(<DataHealthPanel />)).not.toThrow();

    expect(await screen.findByText("Daily bars")).toBeTruthy();
    expect(screen.getByText("Day frame")).toBeTruthy();
    expect(screen.getByText("Startup sweep")).toBeTruthy();
    expect(screen.getByText("Fresh")).toBeTruthy();
    // Unknown key/status both fall back to the raw server value, not a thrown error or blank cell.
    expect(screen.getByText("brand_new_source")).toBeTruthy();
    expect(screen.getByText("quarantined")).toBeTruthy();
  });

  it("clicking Fetch data now calls triggerRefresh and shows the fetching pill", async () => {
    refreshStatusMock.mockResolvedValue(refreshStatus({ running: false }));
    socialStatusMock.mockResolvedValue(socialStatus());
    freshnessMock.mockResolvedValue(freshnessReport());
    triggerRefreshMock.mockResolvedValue({
      started: true,
      reason: null,
      status: refreshStatus({ running: true, processed: 5, queued: 40 }),
    });
    render(<DataHealthPanel />);

    const button = await screen.findByRole("button", { name: "Fetch data now" });
    fireEvent.click(button);

    expect(await screen.findByText("Fetching…")).toBeTruthy();
    expect(triggerRefreshMock).toHaveBeenCalledTimes(1);
  });

  it("shows the already-running note when started is false", async () => {
    refreshStatusMock.mockResolvedValue(refreshStatus({ running: false }));
    socialStatusMock.mockResolvedValue(socialStatus());
    freshnessMock.mockResolvedValue(freshnessReport());
    triggerRefreshMock.mockResolvedValue({
      started: false,
      reason: "already_running",
      status: refreshStatus({ running: true }),
    });
    render(<DataHealthPanel />);

    const button = await screen.findByRole("button", { name: "Fetch data now" });
    fireEvent.click(button);

    expect(
      await screen.findByText("A sweep is already running -- watching its progress below."),
    ).toBeTruthy();
  });

  it("shows a callout when triggering the sweep fails", async () => {
    refreshStatusMock.mockResolvedValue(refreshStatus({ running: false }));
    socialStatusMock.mockResolvedValue(socialStatus());
    freshnessMock.mockResolvedValue(freshnessReport());
    triggerRefreshMock.mockRejectedValue(new Error("boom"));
    render(<DataHealthPanel />);

    const button = await screen.findByRole("button", { name: "Fetch data now" });
    fireEvent.click(button);

    expect(await screen.findByText("boom")).toBeTruthy();
  });

  it("polls refreshStatus every 2s while running and stops once it flips false", async () => {
    vi.useFakeTimers();
    refreshStatusMock.mockResolvedValueOnce(refreshStatus({ running: true, processed: 1, queued: 40 }));
    socialStatusMock.mockResolvedValue(socialStatus());
    freshnessMock.mockResolvedValue(freshnessReport());

    render(<DataHealthPanel />);
    // Flush the initial Promise.all load (real promises, no timer involved) before touching the
    // clock. Wrapped in `act` because the state update lands from a resolved promise, outside any
    // React event -- without it, React has no chance to run the polling effect before the next
    // `advanceTimersByTimeAsync` call, and the interval it installs is what the rest of this test
    // depends on existing.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(refreshStatusMock).toHaveBeenCalledTimes(1);
    expect(freshnessMock).toHaveBeenCalledTimes(1);

    refreshStatusMock.mockResolvedValueOnce(refreshStatus({ running: true, processed: 20, queued: 40 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(refreshStatusMock).toHaveBeenCalledTimes(2);
    // Still running -- the freshness table has not been re-fetched again.
    expect(freshnessMock).toHaveBeenCalledTimes(1);

    refreshStatusMock.mockResolvedValueOnce(refreshStatus({ running: false, processed: 40, queued: 40 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(refreshStatusMock).toHaveBeenCalledTimes(3);
    // The freshness table is re-fetched once, now that the sweep is done.
    expect(freshnessMock).toHaveBeenCalledTimes(2);

    // Running is now false -- no further polling.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(refreshStatusMock).toHaveBeenCalledTimes(3);
  });

  it("still renders the refresh and social panels when the freshness endpoint fails", async () => {
    refreshStatusMock.mockResolvedValue(refreshStatus());
    socialStatusMock.mockResolvedValue(socialStatus());
    freshnessMock.mockRejectedValue(new Error("freshness down"));
    render(<DataHealthPanel />);

    expect(await screen.findByText("Complete")).toBeTruthy();
    expect(screen.getByText("Healthy")).toBeTruthy();
    // `describeError` prefers the thrown Error's own message over the generic fallback -- see
    // `@/api/client`'s `describeError`.
    expect(screen.getByText("freshness down")).toBeTruthy();
  });

  it("renders the navigation-telemetry table once the owner-only summary loads", async () => {
    refreshStatusMock.mockResolvedValue(refreshStatus());
    socialStatusMock.mockResolvedValue(socialStatus());
    freshnessMock.mockResolvedValue(freshnessReport());
    navSummaryMock.mockResolvedValue(navSummary());
    render(<DataHealthPanel />);

    expect(await screen.findByText("Navigation, last 30 days")).toBeTruthy();
    expect(screen.getByText("/tax")).toBeTruthy();
    expect(screen.getByText("lots")).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getByText("/overview")).toBeTruthy();
    expect(navSummaryMock).toHaveBeenCalledWith(30);
  });

  it("renders nothing for the navigation-telemetry panel when the summary call rejects (a member's 403)", async () => {
    refreshStatusMock.mockResolvedValue(refreshStatus());
    socialStatusMock.mockResolvedValue(socialStatus());
    freshnessMock.mockResolvedValue(freshnessReport());
    navSummaryMock.mockRejectedValue(new Error("owner_only"));
    render(<DataHealthPanel />);

    // The rest of the page still renders -- only the nav-telemetry sub-panel is absent.
    expect(await screen.findByText("Complete")).toBeTruthy();
    expect(screen.queryByText("Navigation, last 30 days")).toBeNull();
  });
});
