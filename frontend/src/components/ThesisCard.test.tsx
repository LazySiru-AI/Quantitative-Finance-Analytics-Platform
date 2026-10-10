import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api/client";
import type { PromotedCard, PromoteRequest, StrategyCard } from "@/api/thesis";

// --- module mock: override only thesisApi.promote, keep the real label helpers/types ------------

const promoteMock = vi.fn<(req: PromoteRequest) => Promise<PromotedCard>>();

vi.mock("@/api/thesis", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/thesis")>();
  return {
    ...actual,
    thesisApi: { ...actual.thesisApi, promote: (req: PromoteRequest) => promoteMock(req) },
  };
});

const { PromoteButton } = await import("@/components/ThesisCard");

/** A card carrying only the three fields `PromoteButton` reads. Cast because the button never
 *  touches the rest of `StrategyCard`, so a full fixture would be noise. */
function card(overrides: Partial<StrategyCard> = {}): StrategyCard {
  return { symbol: "QQQ", thesis_hash: "abcd1234ef56", verdict: "survived", ...overrides } as StrategyCard;  // pragma: allowlist secret
}

describe("PromoteButton", () => {
  it("renders nothing for a verdict other than survived", () => {
    const { container } = render(<PromoteButton card={card({ verdict: "rejected" })} nested={false} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing on a nested (unlevered) card, even a surviving one", () => {
    const { container } = render(<PromoteButton card={card()} nested={true} />);
    expect(container.firstChild).toBeNull();
  });

  it("promotes the survivor by (symbol, thesis_hash) and shows the added state on success", async () => {
    promoteMock.mockResolvedValue({
      agent_id: "T-QQQ-abcd1234",
      display_name: "Thesis — QQQ: …",
      reference_only: true,
    });

    render(<PromoteButton card={card()} nested={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Promote to library" }));

    expect(promoteMock).toHaveBeenCalledWith({ symbol: "QQQ", thesis_hash: "abcd1234ef56" });  // pragma: allowlist secret
    expect(await screen.findByText("Added to the library")).toBeTruthy();
    // The button disables itself once done so a second click cannot re-fire the request.
    expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(true);
  });

  it("treats a 409 as 'already on the shelf', not an error -- a hash-pinned re-promote is a no-op", async () => {
    promoteMock.mockRejectedValue(new ApiRequestError(409, "already on the shelf"));

    render(<PromoteButton card={card()} nested={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Promote to library" }));

    expect(await screen.findByText("Already on the shelf")).toBeTruthy();
    // Not disabled forever: 409 is terminal-but-fine, the button returns to its idle label.
    expect(screen.queryByText("Could not promote")).toBeNull();
  });

  it("surfaces a real failure (422) with the backend's message", async () => {
    promoteMock.mockRejectedValue(new ApiRequestError(422, "thesis has verdict 'rejected', not survived"));

    render(<PromoteButton card={card()} nested={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Promote to library" }));

    await waitFor(() => expect(screen.getByText("Could not promote")).toBeTruthy());
  });
});
