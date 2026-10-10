/**
 * The point of `PanelBoundary` is narrower than `ErrorBoundary`'s: a throw in one panel must not
 * take its siblings with it. That is the one thing worth asserting here that `ErrorBoundary.test.tsx`
 * does not already cover -- everything else (shows the error text, does not silently swallow it) is
 * the same behaviour at a different scope.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PanelBoundary from "@/components/PanelBoundary";

function Boom({ message }: { message: string }): never {
  throw new Error(message);
}

describe("PanelBoundary", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the fallback in place of the throwing child while sibling content still renders", () => {
    render(
      <div>
        <p>sibling above</p>
        <PanelBoundary label="Holdings">
          <Boom message="Cannot read properties of undefined (reading 'weight')" />
        </PanelBoundary>
        <p>sibling below</p>
      </div>,
    );
    expect(screen.getByText(/could not be displayed/i)).toBeTruthy();
    expect(screen.getByText(/Holdings/)).toBeTruthy();
    expect(screen.getByText("sibling above")).toBeTruthy();
    expect(screen.getByText("sibling below")).toBeTruthy();
  });

  it("shows the error text", () => {
    render(
      <PanelBoundary>
        <Boom message="Cannot read properties of undefined (reading 'weight')" />
      </PanelBoundary>,
    );
    expect(screen.getByText(/reading 'weight'/)).toBeTruthy();
  });

  it("renders children untouched when nothing throws", () => {
    render(
      <PanelBoundary label="Holdings">
        <p>the actual panel</p>
      </PanelBoundary>,
    );
    expect(screen.getByText("the actual panel")).toBeTruthy();
    expect(screen.queryByText(/could not be displayed/i)).toBeNull();
  });

  it("resets and re-renders children after Try again", () => {
    let shouldThrow = true;
    function Flaky() {
      if (shouldThrow) throw new Error("transient");
      return <p>recovered</p>;
    }

    render(
      <PanelBoundary label="Holdings">
        <Flaky />
      </PanelBoundary>,
    );
    expect(screen.getByText(/could not be displayed/i)).toBeTruthy();

    shouldThrow = false;
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));

    expect(screen.getByText("recovered")).toBeTruthy();
  });
});
