/**
 * StatValue: a null estimate must never look like a real zero, a point-only estimate omits the CI
 * parenthetical, a full estimate renders `n=` and the CI together, and `format="percent"` treats
 * the underlying number as an ALREADY-SCALED percent (4.32 -> "4.32%"), not as a fraction to be
 * multiplied by 100 -- the exact bug this component exists to prevent from recurring (a fraction
 * premise would render 4.32% as "432%").
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import StatValue, { type StatEstimateLike } from "@/components/StatValue";

afterEach(cleanup);

function estimate(overrides: Partial<StatEstimateLike>): StatEstimateLike {
  return { n: 192, point: 0.16, low: 0.11, high: 0.22, confidence: 0.9, method: "bootstrap", ...overrides };
}

describe("empty states", () => {
  it("renders the empty label for a null estimate, not a zero", () => {
    render(<StatValue estimate={null} data-testid="sv" />);
    const el = screen.getByTestId("sv");
    expect(el.textContent).toBe("no data");
    expect(el.textContent).not.toContain("0");
  });

  it("renders the empty label for an undefined estimate", () => {
    render(<StatValue estimate={undefined} data-testid="sv" />);
    expect(screen.getByTestId("sv").textContent).toBe("no data");
  });

  it("renders the empty label when point is null, even if n is present", () => {
    render(<StatValue estimate={estimate({ point: null })} data-testid="sv" />);
    expect(screen.getByTestId("sv").textContent).toBe("no data");
  });

  it("honours a caller-supplied empty label", () => {
    render(<StatValue estimate={null} emptyLabel="not enough calls" data-testid="sv" />);
    expect(screen.getByTestId("sv").textContent).toBe("not enough calls");
  });
});

describe("point without a confidence interval", () => {
  it("renders the point and denominator with no CI when low/high are null", () => {
    render(
      <StatValue
        estimate={estimate({ point: 0.16, low: null, high: null, method: "none" })}
        format="rate"
        data-testid="sv"
      />,
    );
    expect(screen.getByTestId("sv").textContent).toBe("0.16 (n=192)");
  });

  it("omits the CI when method is 'none' even if low/high happen to be present", () => {
    render(
      <StatValue estimate={estimate({ point: 0.16, method: "none" })} format="rate" data-testid="sv" />,
    );
    expect(screen.getByTestId("sv").textContent).toBe("0.16 (n=192)");
  });
});

describe("full estimate", () => {
  it("renders the point, n, and the CI together", () => {
    render(<StatValue estimate={estimate({})} format="rate" data-testid="sv" />);
    expect(screen.getByTestId("sv").textContent).toBe("0.16 (n=192, 90% CI 0.11–0.22)");
  });

  it("exposes the long form via title and aria-label for screen readers", () => {
    render(<StatValue estimate={estimate({})} format="rate" data-testid="sv" />);
    const el = screen.getByTestId("sv");
    expect(el.getAttribute("title")).toBe("0.16 (n=192, 90% CI 0.11–0.22)");
    expect(el.getAttribute("aria-label")).toBe("0.16 (n=192, 90% CI 0.11–0.22)");
  });
});

describe("format", () => {
  it("treats the value as an ALREADY-SCALED percent under format=\"percent\" (4.32 -> 4.32%)", () => {
    render(
      <StatValue
        estimate={estimate({ point: 4.32, low: 1.1, high: 7.54 })}
        format="percent"
        data-testid="sv"
      />,
    );
    const text = screen.getByTestId("sv").textContent ?? "";
    expect(text).toContain("4.32%");
    // The fraction-premise bug would have rendered this as "432.00%".
    expect(text).not.toContain("432");
    expect(text).toContain("1.10%");
    expect(text).toContain("7.54%");
  });

  it("renders the raw fraction to 2dp under format=\"rate\"", () => {
    render(<StatValue estimate={estimate({ point: 0.16 })} format="rate" data-testid="sv" />);
    expect(screen.getByTestId("sv").textContent).toContain("0.16");
  });

  it("renders a plain 2dp number under format=\"number\" with no unit", () => {
    // The confidence percent ("90%") is part of the CI phrase and always renders regardless of
    // `format` -- only the point/low/high magnitudes are affected by the format choice, so this
    // asserts on the magnitude values specifically rather than on the absence of "%" anywhere.
    render(
      <StatValue
        estimate={estimate({ point: 1.5, low: 1.1, high: 1.9 })}
        format="number"
        data-testid="sv"
      />,
    );
    const text = screen.getByTestId("sv").textContent ?? "";
    expect(text).toBe("1.50 (n=192, 90% CI 1.10–1.90)");
  });

  it("omits any % on the magnitudes themselves under format=\"number\" with no CI", () => {
    render(
      <StatValue
        estimate={estimate({ point: 1.5, low: null, high: null, method: "none" })}
        format="number"
        data-testid="sv"
      />,
    );
    expect(screen.getByTestId("sv").textContent).toBe("1.50 (n=192)");
  });

  it("defaults to percent formatting (already-scaled) when no format is given", () => {
    render(<StatValue estimate={estimate({ point: 0.5, low: 0.4, high: 0.6 })} data-testid="sv" />);
    expect(screen.getByTestId("sv").textContent).toContain("0.50%");
  });
});

describe("n is always shown", () => {
  it("shows n alongside the point even without a CI", () => {
    render(
      <StatValue
        estimate={estimate({ n: 6, point: 1, low: null, high: null, method: "none" })}
        format="rate"
        data-testid="sv"
      />,
    );
    expect(screen.getByTestId("sv").textContent).toContain("n=6");
  });

  it("shows a small-n estimate distinctly from a large-n one with the same point", () => {
    render(<StatValue estimate={estimate({ n: 6, point: 1 })} format="rate" data-testid="sv-small" />);
    render(<StatValue estimate={estimate({ n: 192, point: 1 })} format="rate" data-testid="sv-large" />);
    const small = screen.getByTestId("sv-small").textContent;
    const large = screen.getByTestId("sv-large").textContent;
    expect(small).not.toBe(large);
    expect(small).toContain("n=6");
    expect(large).toContain("n=192");
  });
});
