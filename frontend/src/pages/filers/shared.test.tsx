/**
 * `IssuerCell` (shared by `Institutions.tsx` and `Consensus.tsx`, both now tabs of `Filers.tsx`) --
 * specifically the cross-link (UX refactor 3.3) a holding's ticker badge carries to the Symbol page.
 *
 * `Filers.test.tsx` mocks `InstitutionsView`/`ConsensusView` at the module boundary (see that file's
 * own docstring), so it never actually renders this component -- this file is `IssuerCell`'s own,
 * narrow coverage, exercised directly rather than through either page.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { IssuerCell } from "./shared";

describe("IssuerCell", () => {
  it("renders the issuer name alone when there is no ticker match", () => {
    render(
      <MemoryRouter>
        <IssuerCell issuer="Some Issuer LLC" ticker={null} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Some Issuer LLC")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("links a matched ticker to the Symbol page, not the legacy /ticker route", () => {
    render(
      <MemoryRouter>
        <IssuerCell issuer="Apple Inc" ticker="AAPL" />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("/symbol/AAPL");
  });
});
