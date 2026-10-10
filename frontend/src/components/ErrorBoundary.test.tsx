/**
 * The boundary is the answer to a crash that actually happened: an undefined money field took the
 * whole application down to a white screen, navigation included, with the reason only in the
 * console. What is worth asserting is not that React catches errors — it does — but the three
 * decisions made around it.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ErrorBoundary from "@/components/ErrorBoundary";

function Boom({ message }: { message: string }): never {
  throw new Error(message);
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // React logs every caught error itself, and the boundary logs the component stack on purpose.
    // Both are noise here; silencing them keeps a passing run readable.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the failure instead of unmounting the tree", () => {
    render(
      <ErrorBoundary>
        <Boom message="Cannot read properties of undefined (reading 'trim')" />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/stopped rendering/i)).toBeTruthy();
  });

  it("shows the error text", () => {
    /**
     * A deliberate choice, not an oversight. This is a local single-user developer tool: the person
     * reading the screen is the person who can fix it, and "something went wrong" would cost them
     * the only useful fact on the page.
     */
    render(
      <ErrorBoundary>
        <Boom message="Cannot read properties of undefined (reading 'trim')" />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/reading 'trim'/)).toBeTruthy();
  });

  it("says plainly that nothing was written", () => {
    // The user's first question after a crash in an application that computes tax figures is
    // whether it broke something. It did not — a render failure is downstream of every write.
    render(
      <ErrorBoundary>
        <Boom message="boom" />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/nothing was written/i)).toBeTruthy();
  });

  it("renders children untouched when nothing throws", () => {
    render(
      <ErrorBoundary>
        <p>the actual page</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("the actual page")).toBeTruthy();
    expect(screen.queryByText(/stopped rendering/i)).toBeNull();
  });
});
