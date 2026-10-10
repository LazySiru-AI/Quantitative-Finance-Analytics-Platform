/**
 * `InceptionPanel`: reads Paper Desk's current/default/earliest/latest inception dates via
 * `paperdeskApi.state()`, and gates `setInception`/`resetInception` behind a `ConfirmSheet` --
 * recomputing every book is not a click a reader should reach without a confirmation step.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { PaperDeskState } from "@/api/paperdesk";

const stateMock = vi.fn<() => Promise<PaperDeskState>>();
const setInceptionMock = vi.fn<(date: string) => Promise<PaperDeskState>>();
const resetInceptionMock = vi.fn<() => Promise<PaperDeskState>>();

vi.mock("@/api/paperdesk", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/paperdesk")>();
  return {
    ...actual,
    paperdeskApi: {
      ...actual.paperdeskApi,
      state: () => stateMock(),
      setInception: (date: string) => setInceptionMock(date),
      resetInception: () => resetInceptionMock(),
    },
  };
});

const { default: InceptionPanel } = await import("./InceptionPanel");

function deskState(overrides: Partial<PaperDeskState> = {}): PaperDeskState {
  return {
    inception: "2024-01-02",
    inception_default: "2023-06-01",
    inception_is_custom: true,
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

describe("InceptionPanel", () => {
  it("renders the current and default inception once loaded", async () => {
    stateMock.mockResolvedValue(deskState());
    render(<InceptionPanel onToast={vi.fn()} />);

    expect(await screen.findByText("2024-01-02")).toBeTruthy();
    expect(screen.getByText("2023-06-01")).toBeTruthy();
  });

  it("requires confirmation before applying a new inception, then calls setInception", async () => {
    stateMock.mockResolvedValue(deskState());
    setInceptionMock.mockResolvedValue(deskState({ inception: "2020-01-02", inception_is_custom: true }));
    const onToast = vi.fn();
    const user = userEvent.setup();
    render(<InceptionPanel onToast={onToast} />);

    await screen.findByText("2024-01-02");
    const dateInput = screen.getByLabelText("New inception date");
    fireEvent.change(dateInput, { target: { value: "2020-01-02" } });

    await user.click(screen.getByRole("button", { name: "Set inception" }));
    // Not called yet -- the confirmation dialog must appear first.
    expect(setInceptionMock).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("dialog");
    const confirmButton = await screen.findByRole("button", { name: "Confirm" });
    expect(dialog.textContent).toContain("2020-01-02");
    await user.click(confirmButton);

    await waitFor(() => expect(setInceptionMock).toHaveBeenCalledWith("2020-01-02"));
    await waitFor(() =>
      expect(onToast).toHaveBeenCalledWith(
        expect.objectContaining({ message: "Inception set to 2020-01-02.", tone: "ok" }),
      ),
    );
  });

  it("cancelling the confirm sheet never calls setInception", async () => {
    stateMock.mockResolvedValue(deskState());
    const user = userEvent.setup();
    render(<InceptionPanel onToast={vi.fn()} />);

    await screen.findByText("2024-01-02");
    await user.click(screen.getByRole("button", { name: "Set inception" }));
    await screen.findByRole("dialog");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(setInceptionMock).not.toHaveBeenCalled();
  });
});
