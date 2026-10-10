/**
 * Skeleton: draws the requested row count, announces what is loading via a live region, and folds
 * in the progress fragment when the caller knows how far along it is.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import Skeleton from "@/components/Skeleton";

afterEach(cleanup);

describe("row count", () => {
  it("draws the default of 3 placeholder blocks when rows is omitted", () => {
    const { container } = render(<Skeleton />);
    expect(container.querySelectorAll(".skeleton-block")).toHaveLength(3);
  });

  it("draws the requested number of rows", () => {
    const { container } = render(<Skeleton rows={7} />);
    expect(container.querySelectorAll(".skeleton-block")).toHaveLength(7);
  });

  it("clamps a non-positive row count to one placeholder rather than rendering none", () => {
    const { container } = render(<Skeleton rows={0} />);
    expect(container.querySelectorAll(".skeleton-block")).toHaveLength(1);
  });
});

describe("live region", () => {
  it("announces the generic loading message when `what` is omitted", () => {
    render(<Skeleton />);
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("Loading…");
  });

  it("announces what is loading when `what` is given", () => {
    render(<Skeleton what="filers" />);
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("Loading filers…");
  });

  it("includes the progress fragment when progress is given", () => {
    render(<Skeleton what="filers" progress={{ done: 3, total: 10 }} />);
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("Loading filers… 3 of 10");
  });

  it("is politely live, not assertive", () => {
    render(<Skeleton />);
    const status = screen.getByRole("status");
    expect(status.getAttribute("aria-live")).toBe("polite");
  });
});

describe("variant", () => {
  it("defaults to the rows silhouette", () => {
    const { container } = render(<Skeleton />);
    expect(container.querySelector(".skeleton-rows")).toBeTruthy();
  });

  it("switches silhouette class per variant", () => {
    const { container } = render(<Skeleton variant="tiles" />);
    expect(container.querySelector(".skeleton-tiles")).toBeTruthy();
  });
});
