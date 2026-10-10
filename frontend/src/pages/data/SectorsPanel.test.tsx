/**
 * `SectorsPanel`: loads the sector map, lets an operator pick a new sector from the vocabulary, and
 * saves via `PUT /api/portfolio/sectors/{symbol}` -- through the existing `portfolioApi` client
 * (`@/api/portfolio`), not a new fetch. `portfolioApi` is stubbed at the module boundary, matching
 * `Tax.test.tsx`'s approach for its own API modules.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { SectorVocabulary } from "@/api/portfolio";

const sectorsMock = vi.fn<() => Promise<SectorVocabulary>>();
const setSectorMock = vi.fn<(symbol: string, sector: string) => Promise<{ symbol: string; sector: string }>>();

vi.mock("@/api/portfolio", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/portfolio")>();
  return {
    ...actual,
    portfolioApi: {
      ...actual.portfolioApi,
      sectors: () => sectorsMock(),
      setSector: (symbol: string, sector: string) => setSectorMock(symbol, sector),
    },
  };
});

const { default: SectorsPanel } = await import("./SectorsPanel");

function vocabulary(overrides: Partial<SectorVocabulary> = {}): SectorVocabulary {
  return {
    vocabulary: ["SEMI", "BIG TECH", "Unclassified"],
    map: { NVDA: "SEMI", AMZN: "BIG TECH" },
    ...overrides,
  };
}

describe("SectorsPanel", () => {
  it("renders the sector map once loaded", async () => {
    sectorsMock.mockResolvedValue(vocabulary());
    render(<SectorsPanel onToast={vi.fn()} />);

    expect(await screen.findByText("NVDA")).toBeTruthy();
    expect(screen.getByText("AMZN")).toBeTruthy();
  });

  it("saves a changed sector via PUT and reports success", async () => {
    sectorsMock.mockResolvedValue(vocabulary());
    setSectorMock.mockResolvedValue({ symbol: "NVDA", sector: "BIG TECH" });
    const onToast = vi.fn();
    const user = userEvent.setup();
    render(<SectorsPanel onToast={onToast} />);

    await screen.findByText("NVDA");
    const select = screen.getByLabelText("Sector for NVDA");
    await user.selectOptions(select, "BIG TECH");

    const saveButtons = screen.getAllByRole("button", { name: "Save" });
    // NVDA is the first row (sorted symbols) and the only one with a dirty draft, so its Save
    // button is the only one enabled -- click whichever one is not disabled.
    const enabled = saveButtons.find((btn) => !(btn as HTMLButtonElement).disabled);
    expect(enabled).toBeTruthy();
    await user.click(enabled as HTMLButtonElement);

    await waitFor(() => expect(setSectorMock).toHaveBeenCalledWith("NVDA", "BIG TECH"));
    await waitFor(() =>
      expect(onToast).toHaveBeenCalledWith(
        expect.objectContaining({ message: "NVDA reclassified to BIG TECH.", tone: "ok" }),
      ),
    );
  });

  it("shows the empty state when the map has no symbols", async () => {
    sectorsMock.mockResolvedValue(vocabulary({ map: {} }));
    render(<SectorsPanel onToast={vi.fn()} />);

    expect(await screen.findByText("No symbols classified yet.")).toBeTruthy();
  });
});
