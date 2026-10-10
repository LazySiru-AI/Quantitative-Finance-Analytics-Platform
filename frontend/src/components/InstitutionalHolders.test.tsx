/**
 * The holders panel, and specifically the three states where an empty list means different things.
 *
 * A reverse lookup that renders `holders.length === 0` as "nobody holds it" is wrong in two of the
 * three cases it can be in, and the two wrong ones are silent. Most of this file is about keeping
 * them distinguishable on screen.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { HoldersResponse } from "@/api/institutions";

const holdersMock = vi.fn<() => Promise<HoldersResponse>>();

vi.mock("@/api/institutions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/institutions")>();
  return {
    ...actual,
    institutionsApi: { ...actual.institutionsApi, holders: () => holdersMock() },
  };
});

const { default: InstitutionalHolders } = await import("@/components/InstitutionalHolders");

function response(overrides: Partial<HoldersResponse> = {}): HoldersResponse {
  return {
    symbol: "NVDA",
    cusips: ["67066G104"],
    symbol_resolved: true,
    holders: [],
    unchecked: [],
    checked: 22,
    total: 22,
    ...overrides,
  };
}

function holder(overrides: Partial<HoldersResponse["holders"][number]> = {}) {
  return {
    key: "VTI",
    name: "Vanguard Total Stock Market ETF",
    period: "2026-03-31",
    filed: "2026-05-15",
    accession: "0000000000-26-000001",
    cusip: "67066G104",
    issuer: "NVIDIA Corp",
    shares: "1000",
    value: "127849303728",
    weight: "0.0640",
    value_units_rescaled: false,
    ...overrides,
  };
}

async function ask(data: HoldersResponse) {
  holdersMock.mockResolvedValue(data);
  render(<InstitutionalHolders symbol="NVDA" />);
  fireEvent.click(screen.getByRole("button", { name: /which tracked filers hold NVDA/i }));
  await waitFor(() => expect(holdersMock).toHaveBeenCalled());
}

beforeEach(() => holdersMock.mockReset());
afterEach(cleanup);

describe("it does not fetch until asked", () => {
  it("renders no request on mount, because the call can take a minute", () => {
    render(<InstitutionalHolders symbol="NVDA" />);
    expect(holdersMock).not.toHaveBeenCalled();
  });

  it("says what pressing the button will cost before it is pressed", () => {
    render(<InstitutionalHolders symbol="NVDA" />);
    expect(screen.getByText(/up to a minute/i)).toBeTruthy();
  });
});

describe("an empty list means three different things", () => {
  it("full coverage and a resolved symbol is the real 'nobody holds it'", async () => {
    await ask(response());
    expect(await screen.findByText(/No tracked filer disclosed a position/i)).toBeTruthy();
  });

  it("an unresolved symbol says so, and says it is not evidence of absence", async () => {
    await ask(response({ symbol_resolved: false, cusips: [] }));

    expect(await screen.findByText(/could not be matched to a CUSIP/i)).toBeTruthy();
    expect(screen.getByText(/not evidence nobody holds/i)).toBeTruthy();
  });

  it("partial coverage names how many filers went unread", async () => {
    await ask(
      response({
        checked: 19,
        unchecked: [
          { key: "SCION", name: "Scion Asset Management, LLC", reason: "TimeoutError: no response" },
          { key: "SOROS", name: "Soros Fund Management LLC", reason: "TimeoutError: no response" },
          { key: "BRK", name: "Berkshire Hathaway Inc", reason: "TimeoutError: no response" },
        ],
      }),
    );

    expect(await screen.findByText(/3 of 22 filers could not be read/i)).toBeTruthy();
    expect(screen.getByText(/19 readable filings/i)).toBeTruthy();
  });
});

describe("results", () => {
  it("renders each filer with its value, weight and period", async () => {
    await ask(response({ holders: [holder()] }));

    expect(await screen.findByText("Vanguard Total Stock Market ETF")).toBeTruthy();
    expect(screen.getByText("6.40%")).toBeTruthy();
    expect(screen.getByText("2026-03-31")).toBeTruthy();
  });

  it("marks a row whose filing had its value column rescaled", async () => {
    /** `Snapshot.value_units_rescaled` is a judgement about someone else's data -- a filing read as
     *  thousands and multiplied up. A row derived from one must say so, or the reader sees a figure
     *  silently multiplied by a thousand. */
    await ask(response({ holders: [holder({ value_units_rescaled: true })] }));

    expect(await screen.findByText(/rescaled/i)).toBeTruthy();
  });

  it("reports coverage even when every filer was readable", async () => {
    await ask(response({ holders: [holder()] }));
    expect(await screen.findByText(/22 of 22 filers checked/i)).toBeTruthy();
  });
});

/*
 * **Not covered here: the fetch-rejects branch.** Four attempts to drive it from this suite all
 * failed the same way -- vitest reports the rejection as the test error before any assertion runs,
 * whether the promise is built by `mockRejectedValue`, built eagerly and given a no-op `catch`
 * tail, or left pending and rejected on a later tick. The component does attach `.catch`
 * synchronously in `load`, so this is the runtime's unhandled-rejection tracking rather than a
 * hole in the component.
 *
 * Left uncovered and named rather than written as a test that passes for the wrong reason, or as
 * one contorted until the harness stops complaining. The branch is four lines -- set the message,
 * set phase to "error" -- and it renders `callout callout-warn`, the same element the two coverage
 * callouts above use and which those tests do exercise. Worth revisiting if this suite ever gains a
 * documented way to assert on a rejected fetch.
 */
