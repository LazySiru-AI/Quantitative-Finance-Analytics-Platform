/**
 * `LiveDecisionsPanel`: daemon status, recent live decisions, and a manual "Decide now" for one
 * symbol -- `@/api/liveDecisions` stubbed at the module boundary, the same pattern
 * `@/pages/data/DataHealthPanel.test.tsx` already uses for `@/api/dataAdmin`.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DecideNowResponse,
  LiveDecisionRecord,
  LiveDecisionsResponse,
  LiveStatus,
} from "@/api/liveDecisions";

const statusMock = vi.fn<() => Promise<LiveStatus>>();
const decisionsMock = vi.fn<(symbol?: string, limit?: number) => Promise<LiveDecisionsResponse>>();
const decideNowMock = vi.fn<(symbol: string) => Promise<DecideNowResponse>>();

vi.mock("@/api/liveDecisions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/liveDecisions")>();
  return {
    ...actual,
    liveDecisionsApi: {
      ...actual.liveDecisionsApi,
      status: () => statusMock(),
      decisions: (symbol?: string, limit?: number) => decisionsMock(symbol, limit),
      decideNow: (symbol: string) => decideNowMock(symbol),
    },
  };
});

const { default: LiveDecisionsPanel } = await import("./LiveDecisionsPanel");

function liveStatus(overrides: Partial<LiveStatus> = {}): LiveStatus {
  return {
    enabled: true,
    running: true,
    healthy: true,
    market_state: "regular",
    last_tick_at: "2026-09-08T13:55:00+00:00",
    next_wake_at: "2026-09-08T14:00:00+00:00",
    ticks: 42,
    decisions_today: 3,
    consecutive_failures: 0,
    symbols: ["NVDA", "AAPL"],
    interval_minutes: 5,
    cap_usd: "10.00",
    ...overrides,
  };
}

function decisionRecord(overrides: Partial<LiveDecisionRecord> = {}): LiveDecisionRecord {
  return {
    decided_at: "2026-09-08T13:55:00+00:00",
    symbol: "NVDA",
    stance: "buy",
    confidence: 0.82,
    rationale: "Momentum plus a clean breakout.",
    horizon: "intraday",
    price: "482.10",
    quoted_at: "2026-09-08T13:54:50+00:00",
    market_state: "regular",
    grounded: true,
    degraded: false,
    cost_usd: "0.03",
    model: "claude-haiku-4-5-20251001",
    source: "daemon",
    call_ids: ["call-1"],
    ...overrides,
  };
}

describe("LiveDecisionsPanel", () => {
  beforeEach(() => {
    statusMock.mockReset();
    decisionsMock.mockReset();
    decideNowMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the daemon status pills once loaded", async () => {
    statusMock.mockResolvedValue(liveStatus());
    decisionsMock.mockResolvedValue({ decisions: [decisionRecord()] });
    render(<LiveDecisionsPanel />);

    expect(await screen.findByText("Enabled")).toBeTruthy();
    expect(screen.getByText("Running")).toBeTruthy();
    expect(screen.getByText("Healthy")).toBeTruthy();
    expect(screen.getByText("regular")).toBeTruthy();
  });

  it("renders decisions rows with mapped stance labels and tones", async () => {
    statusMock.mockResolvedValue(liveStatus());
    decisionsMock.mockResolvedValue({
      decisions: [
        decisionRecord({ stance: "buy", symbol: "NVDA" }),
        decisionRecord({ stance: "sell", symbol: "TSLA" }),
        decisionRecord({ stance: "hold", symbol: "AAPL" }),
        decisionRecord({ stance: "no_action", symbol: "MSFT" }),
      ],
    });
    render(<LiveDecisionsPanel />);

    expect(await screen.findByText("Buy")).toBeTruthy();
    expect(screen.getByText("Sell")).toBeTruthy();
    expect(screen.getByText("Hold")).toBeTruthy();
    expect(screen.getByText("No action")).toBeTruthy();
  });

  it("renders an unknown stance and source as a neutral fallback instead of throwing", async () => {
    statusMock.mockResolvedValue(liveStatus());
    decisionsMock.mockResolvedValue({
      decisions: [
        decisionRecord({
          // Cast past the closed union on purpose -- proves an unknown wire value renders as a
          // neutral fallback labelled with the raw string, not a thrown exhaustiveness error (the
          // failure mode this repo has already hit once; see `closed-unions-over-server-data-kill-
          // pages` in this repo's own history).
          stance: "trim" as unknown as "hold",
          source: "backtest" as unknown as "daemon",
        }),
      ],
    });

    expect(() => render(<LiveDecisionsPanel />)).not.toThrow();

    expect(await screen.findByText("trim")).toBeTruthy();
    expect(screen.getByText("backtest")).toBeTruthy();
  });

  it("shows an extra Ungrounded pill for a degraded decision", async () => {
    statusMock.mockResolvedValue(liveStatus());
    decisionsMock.mockResolvedValue({ decisions: [decisionRecord({ degraded: true })] });
    render(<LiveDecisionsPanel />);

    expect(await screen.findByText("Ungrounded")).toBeTruthy();
  });

  it("Decide now calls the client with the uppercased symbol and prepends the result", async () => {
    statusMock.mockResolvedValue(liveStatus());
    decisionsMock.mockResolvedValue({ decisions: [] });
    decideNowMock.mockResolvedValue({ decision: decisionRecord({ symbol: "MSFT", stance: "hold" }) });
    render(<LiveDecisionsPanel />);

    expect(await screen.findByText("No live decisions recorded yet.")).toBeTruthy();

    const input = screen.getByLabelText("Symbol") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "msft" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Decide now" }));
    });

    expect(decideNowMock).toHaveBeenCalledWith("MSFT");
    expect(await screen.findByText("MSFT")).toBeTruthy();
    expect(screen.getByText("Hold")).toBeTruthy();
  });

  it("shows a callout when Decide now fails", async () => {
    statusMock.mockResolvedValue(liveStatus());
    decisionsMock.mockResolvedValue({ decisions: [] });
    decideNowMock.mockRejectedValue(new Error("spend cap reached"));
    render(<LiveDecisionsPanel />);

    const input = await screen.findByLabelText("Symbol");
    fireEvent.change(input, { target: { value: "NVDA" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Decide now" }));
    });

    expect(await screen.findByText("spend cap reached")).toBeTruthy();
  });

  it("renders the unavailable line when the initial load fails (e.g. a 404 before restart)", async () => {
    statusMock.mockRejectedValue(new Error("Not Found"));
    decisionsMock.mockResolvedValue({ decisions: [] });
    render(<LiveDecisionsPanel />);

    expect(await screen.findByText("Live decisions are not available yet.")).toBeTruthy();
  });

  it("polls status every 60s while mounted and stops on unmount", async () => {
    vi.useFakeTimers();
    statusMock.mockResolvedValue(liveStatus({ decisions_today: 1 }));
    decisionsMock.mockResolvedValue({ decisions: [] });

    const { unmount } = render(<LiveDecisionsPanel />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(statusMock).toHaveBeenCalledTimes(1);

    statusMock.mockResolvedValue(liveStatus({ decisions_today: 2 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(statusMock).toHaveBeenCalledTimes(2);

    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(statusMock).toHaveBeenCalledTimes(2);
  });
});
