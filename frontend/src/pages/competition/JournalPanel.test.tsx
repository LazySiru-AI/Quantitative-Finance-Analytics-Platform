import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { JournalResponse } from "@/api/evolution";

// --- module mock -------------------------------------------------------------------------------------

const journalMock = vi.fn<(params: { limit?: number; offset?: number }) => Promise<JournalResponse>>();

vi.mock("@/api/evolution", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/evolution")>();
  return {
    ...actual,
    evolutionApi: {
      ...actual.evolutionApi,
      journal: (params: { limit?: number; offset?: number }) => journalMock(params),
    },
  };
});

const { default: JournalPanel } = await import("@/pages/competition/JournalPanel");

describe("JournalPanel", () => {
  it("renders generation digests newest-first from the journal", async () => {
    journalMock.mockResolvedValue({
      total: 2,
      entries: [
        { generation: 12, markdown: "Gen 12 tilted into semis; drawdown held." },
        { generation: 11, markdown: "Gen 11 tried a pure trend book; underperformed." },
      ],
    });

    render(<JournalPanel />);

    expect(await screen.findByText("Generation 12")).toBeTruthy();
    expect(screen.getByText("Generation 11")).toBeTruthy();
    expect(screen.getByText(/tilted into semis/)).toBeTruthy();
    expect(screen.getByText(/pure trend book/)).toBeTruthy();
    // Newest first: Generation 12's heading precedes Generation 11's in document order.
    const headings = screen.getAllByRole("heading", { name: /Generation \d+/ });
    expect(headings.map((h) => h.textContent)).toEqual([
      expect.stringContaining("12"),
      expect.stringContaining("11"),
    ]);
  });

  it("shows a designed empty state when the loop has written no digests", async () => {
    journalMock.mockResolvedValue({ total: 0, entries: [] });

    render(<JournalPanel />);

    expect(await screen.findByText(/No digests yet/)).toBeTruthy();
  });

  it("shows an error state when the journal fetch fails", async () => {
    journalMock.mockRejectedValue(new Error("boom"));

    render(<JournalPanel />);

    await waitFor(() =>
      expect(screen.getByText(/Could not load the generation journal/)).toBeTruthy(),
    );
  });
});
