/**
 * CountdownBar: date mode derives the right days-remaining caption and urgency tone as the deadline
 * approaches (and past it), fraction mode uses the caller's own caption and escalates by fraction
 * thresholds, and -- the colour-blind requirement this component exists to satisfy -- the remaining
 * time is always readable as text, in every tone, never conveyed by colour alone.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import CountdownBar from "@/components/CountdownBar";

afterEach(cleanup);

// A fixed "now" so every test is deterministic regardless of when it runs.
const TODAY = new Date("2026-09-06T12:00:00Z");

function daysFromToday(days: number): string {
  const d = new Date(TODAY);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

describe("date mode: caption text", () => {
  it("shows plural days-left text well before the deadline", () => {
    render(<CountdownBar label="Tax year-end" deadlineDate={daysFromToday(120)} today={TODAY} />);
    expect(screen.getByText("120 days left")).toBeTruthy();
  });

  it("uses the singular for exactly one day left", () => {
    render(<CountdownBar label="Tax year-end" deadlineDate={daysFromToday(1)} today={TODAY} />);
    expect(screen.getByText("1 day left")).toBeTruthy();
  });

  it("shows 'Due today' on the deadline itself", () => {
    render(<CountdownBar label="Tax year-end" deadlineDate={daysFromToday(0)} today={TODAY} />);
    expect(screen.getByText("Due today")).toBeTruthy();
  });

  it("shows overdue text, pluralized, once the deadline has passed", () => {
    render(<CountdownBar label="Tax year-end" deadlineDate={daysFromToday(-1)} today={TODAY} />);
    expect(screen.getByText("1 day overdue")).toBeTruthy();

    cleanup();
    render(<CountdownBar label="Tax year-end" deadlineDate={daysFromToday(-5)} today={TODAY} />);
    expect(screen.getByText("5 days overdue")).toBeTruthy();
  });
});

describe("date mode: urgency tone escalates as the deadline nears", () => {
  it("is 'ok' well outside the warn/danger windows", () => {
    const { container } = render(
      <CountdownBar label="Tax year-end" deadlineDate={daysFromToday(120)} today={TODAY} />,
    );
    expect(container.querySelector(".countdown-bar")?.getAttribute("data-tone")).toBe("ok");
  });

  it("escalates to 'warn' at/under the warn threshold (default 30 days)", () => {
    const { container } = render(
      <CountdownBar label="Tax year-end" deadlineDate={daysFromToday(20)} today={TODAY} />,
    );
    expect(container.querySelector(".countdown-bar")?.getAttribute("data-tone")).toBe("warn");
  });

  it("escalates to 'danger' at/under the danger threshold (default 7 days)", () => {
    const { container } = render(
      <CountdownBar label="Tax year-end" deadlineDate={daysFromToday(3)} today={TODAY} />,
    );
    expect(container.querySelector(".countdown-bar")?.getAttribute("data-tone")).toBe("danger");
  });

  it("stays 'danger' once overdue", () => {
    const { container } = render(
      <CountdownBar label="Tax year-end" deadlineDate={daysFromToday(-3)} today={TODAY} />,
    );
    expect(container.querySelector(".countdown-bar")?.getAttribute("data-tone")).toBe("danger");
  });

  it("respects custom warnAtDays/dangerAtDays thresholds", () => {
    const { container } = render(
      <CountdownBar
        label="Custom"
        deadlineDate={daysFromToday(50)}
        today={TODAY}
        warnAtDays={60}
        dangerAtDays={45}
      />,
    );
    // 50 days remaining is under the custom 60-day warn threshold but above the 45-day danger one.
    expect(container.querySelector(".countdown-bar")?.getAttribute("data-tone")).toBe("warn");
  });
});

describe("fraction mode", () => {
  it("renders the caller's own caption verbatim", () => {
    render(<CountdownBar label="Agent spend" fraction={0.4} remainingCaption="$200 of $500 used" />);
    expect(screen.getByText("$200 of $500 used")).toBeTruthy();
  });

  it("is 'ok' below the warn fraction threshold (default 0.75)", () => {
    const { container } = render(
      <CountdownBar label="Agent spend" fraction={0.5} remainingCaption="half used" />,
    );
    expect(container.querySelector(".countdown-bar")?.getAttribute("data-tone")).toBe("ok");
  });

  it("escalates to 'warn' at/above the warn fraction threshold", () => {
    const { container } = render(
      <CountdownBar label="Agent spend" fraction={0.8} remainingCaption="mostly used" />,
    );
    expect(container.querySelector(".countdown-bar")?.getAttribute("data-tone")).toBe("warn");
  });

  it("escalates to 'danger' at/above the danger fraction threshold (default 0.9)", () => {
    const { container } = render(
      <CountdownBar label="Agent spend" fraction={0.95} remainingCaption="nearly exhausted" />,
    );
    expect(container.querySelector(".countdown-bar")?.getAttribute("data-tone")).toBe("danger");
  });

  it("ignores a deadlineDate-less fraction of 0 or missing gracefully (no NaN width)", () => {
    const { container } = render(<CountdownBar label="Agent spend" remainingCaption="not started" />);
    const fill = container.querySelector(".countdown-bar-fill") as HTMLElement;
    expect(fill.style.width).toBe("0%");
  });
});

describe("accessibility: the remaining time is always exposed as text, never colour alone", () => {
  it("exposes a progressbar with numeric value and a text aria-label naming the remaining time", () => {
    render(<CountdownBar label="Tax year-end" deadlineDate={daysFromToday(3)} today={TODAY} />);
    const bar = screen.getByRole("progressbar");
    expect(bar.getAttribute("aria-valuenow")).not.toBeNull();
    expect(bar.getAttribute("aria-valuemin")).toBe("0");
    expect(bar.getAttribute("aria-valuemax")).toBe("100");
    expect(bar.getAttribute("aria-label")).toContain("3 days left");
  });

  it("the danger-tone caption is still readable as literal text content", () => {
    render(<CountdownBar label="Tax year-end" deadlineDate={daysFromToday(-2)} today={TODAY} />);
    // Not just present in the DOM -- visible text a colour-blind reader can read regardless of the
    // tone class applied alongside it.
    expect(screen.getByText("2 days overdue").textContent).toBe("2 days overdue");
  });
});

describe("deadlineDate takes precedence over fraction when both are given", () => {
  it("renders the date-mode caption, not the fraction one", () => {
    render(
      <CountdownBar
        label="Tax year-end"
        deadlineDate={daysFromToday(10)}
        today={TODAY}
        fraction={0.99}
        remainingCaption="should not appear"
      />,
    );
    expect(screen.getByText("10 days left")).toBeTruthy();
    expect(screen.queryByText("should not appear")).toBeNull();
  });
});
