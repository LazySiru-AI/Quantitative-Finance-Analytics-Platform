/**
 * `SectorBadgeEditor`'s double-click-to-edit contract, at render level.
 *
 * `portfolioApi.setSector` is stubbed at the module boundary -- the same pattern
 * `Portfolio.test.tsx` uses for `portfolioApi.report` -- rather than stubbing `fetch`, since the
 * component depends on the typed client, not the transport.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const setSectorMock = vi.fn<(symbol: string, sector: string) => Promise<{ symbol: string; sector: string }>>();

vi.mock("@/api/portfolio", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/portfolio")>();
  return {
    ...actual,
    portfolioApi: { ...actual.portfolioApi, setSector: (symbol: string, sector: string) => setSectorMock(symbol, sector) },
  };
});

const { default: SectorBadgeEditor } = await import("@/components/SectorBadgeEditor");

const VOCAB = ["Semiconductors", "Software", "Energy"];

beforeEach(() => {
  setSectorMock.mockReset();
});

describe("SectorBadgeEditor", () => {
  it("renders a plain badge that hints at the double-click affordance", () => {
    render(
      <SectorBadgeEditor symbol="NVDA" sector="Semiconductors" vocabulary={VOCAB} onChanged={vi.fn()} />,
    );
    const badge = screen.getByText("Semiconductors");
    expect(badge.getAttribute("title")).toMatch(/double-click/i);
    // No select control until the badge is double-clicked.
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("double-click reveals a <select> of the vocabulary", () => {
    render(
      <SectorBadgeEditor symbol="NVDA" sector="Semiconductors" vocabulary={VOCAB} onChanged={vi.fn()} />,
    );
    fireEvent.doubleClick(screen.getByText("Semiconductors"));

    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select).toBeTruthy();
    const optionLabels = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
    expect(optionLabels).toEqual(VOCAB);
    expect(select.value).toBe("Semiconductors");
  });

  it("choosing a new sector and pressing Enter saves it and calls onChanged", async () => {
    setSectorMock.mockResolvedValue({ symbol: "NVDA", sector: "Software" });
    const onChanged = vi.fn();
    render(
      <SectorBadgeEditor symbol="NVDA" sector="Semiconductors" vocabulary={VOCAB} onChanged={onChanged} />,
    );
    fireEvent.doubleClick(screen.getByText("Semiconductors"));

    const select = screen.getByRole("combobox") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "Software" } });
    fireEvent.keyDown(select, { key: "Enter" });

    await vi.waitFor(() => {
      expect(setSectorMock).toHaveBeenCalledWith("NVDA", "Software");
    });
    await vi.waitFor(() => {
      expect(onChanged).toHaveBeenCalledTimes(1);
    });
    // Editing mode closes on a successful save -- the select is gone (the parent's `onChanged` is
    // expected to refresh the report and flow the new sector back down through props). Polled rather
    // than asserted synchronously: `onChanged()` fires in the same synchronous continuation as the
    // `setEditing(false)` call that unmounts the select, but React has not necessarily flushed that
    // state update to the DOM by the exact microtask `onChanged` was observed in.
    await vi.waitFor(() => {
      expect(screen.queryByRole("combobox")).toBeNull();
    });
  });

  it("Escape cancels without saving", () => {
    render(
      <SectorBadgeEditor symbol="NVDA" sector="Semiconductors" vocabulary={VOCAB} onChanged={vi.fn()} />,
    );
    fireEvent.doubleClick(screen.getByText("Semiconductors"));

    const select = screen.getByRole("combobox") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "Software" } });
    fireEvent.keyDown(select, { key: "Escape" });

    expect(screen.queryByRole("combobox")).toBeNull();
    expect(setSectorMock).not.toHaveBeenCalled();
    // Restored to the original badge, not the discarded in-progress selection.
    expect(screen.getByText("Semiconductors")).toBeTruthy();
  });

  it("shows an inline error when the save is rejected, without closing the editor", async () => {
    setSectorMock.mockRejectedValue(new Error("422"));
    render(
      <SectorBadgeEditor symbol="NVDA" sector="Semiconductors" vocabulary={VOCAB} onChanged={vi.fn()} />,
    );
    fireEvent.doubleClick(screen.getByText("Semiconductors"));

    const select = screen.getByRole("combobox") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "Energy" } });
    fireEvent.keyDown(select, { key: "Enter" });

    await screen.findByText(/could not save/i);
    // The select stays open so the reader can retry or pick something else.
    expect(screen.getByRole("combobox")).toBeTruthy();
  });
});
