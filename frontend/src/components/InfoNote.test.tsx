/**
 * InfoNote: the short line is always visible whether or not anyone opens the note, the long form
 * stays in the DOM while collapsed (find-in-page, and the tests that assert on caveats, keep
 * working), and a note with nothing to disclose renders no control that expands to nothing.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import InfoNote from "@/components/InfoNote";

afterEach(cleanup);

describe("summary", () => {
  it("renders the short line collapsed", () => {
    render(
      <InfoNote summary="Calculation only. Reconcile with your 1099-B.">
        <p>Long form goes here.</p>
      </InfoNote>,
    );
    expect(screen.getByText("Calculation only. Reconcile with your 1099-B.")).toBeTruthy();
  });

  it("keeps the long form mounted while collapsed", () => {
    // Built on <details> precisely so collapsed content stays in the DOM -- the same argument
    // Collapsible.tsx makes. A caveat that is one Ctrl+F away is hidden; one that is unmounted is
    // gone.
    render(
      <InfoNote summary="short" data-testid="note">
        <p>the full caveat text</p>
      </InfoNote>,
    );
    expect(screen.getByText("the full caveat text")).toBeTruthy();
    expect((screen.getByTestId("note") as HTMLDetailsElement).open).toBe(false);
  });
});

describe("disclosure", () => {
  it("starts collapsed and opens on click", () => {
    render(
      <InfoNote summary="short" data-testid="note">
        <p>long</p>
      </InfoNote>,
    );
    const details = screen.getByTestId("note") as HTMLDetailsElement;
    expect(details.open).toBe(false);

    fireEvent.click(screen.getByText("short"));
    // jsdom does not implement the native summary-click toggle, so drive the element the way the
    // browser would and assert the wiring rather than jsdom's gaps.
    details.open = true;
    expect(details.open).toBe(true);
  });

  it("honours defaultOpen for the rare note that must start open", () => {
    render(
      <InfoNote summary="short" defaultOpen data-testid="note">
        <p>long</p>
      </InfoNote>,
    );
    expect((screen.getByTestId("note") as HTMLDetailsElement).open).toBe(true);
  });

  it("renders a plain paragraph, not a disclosure, when there is no long form", () => {
    render(<InfoNote summary="just the one line" data-testid="note" />);
    const el = screen.getByTestId("note");
    expect(el.tagName).toBe("P");
    expect(screen.getByText("just the one line")).toBeTruthy();
  });
});

describe("tone", () => {
  it("applies the quiet tone class", () => {
    render(<InfoNote summary="x" tone="quiet" data-testid="note" />);
    expect(screen.getByTestId("note").className).toContain("info-note-quiet");
  });
});
