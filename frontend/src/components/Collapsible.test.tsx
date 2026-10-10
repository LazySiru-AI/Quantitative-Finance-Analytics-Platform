/**
 * Collapsible: the title always renders, children stay in the DOM even while collapsed (the whole
 * point of building this on native `<details>` instead of lazy-mounting), `defaultOpen` controls
 * the initial state, clicking the summary toggles the underlying `<details>` element, a caller's own
 * heading passed via `title` still resolves as a heading, and `data-testid` lands on the root.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import Collapsible from "@/components/Collapsible";

afterEach(cleanup);

describe("title", () => {
  it("renders the title when open (default)", () => {
    render(<Collapsible title="Section title">body content</Collapsible>);
    expect(screen.getByText("Section title")).toBeTruthy();
  });

  it("renders the title when collapsed", () => {
    render(
      <Collapsible title="Section title" defaultOpen={false}>
        body content
      </Collapsible>,
    );
    expect(screen.getByText("Section title")).toBeTruthy();
  });
});

describe("children stay mounted regardless of open state", () => {
  it("keeps children in the DOM while collapsed, under a closed <details>", () => {
    render(
      <Collapsible title="Section title" defaultOpen={false} data-testid="wrapper">
        <p>hidden but present body text</p>
      </Collapsible>,
    );

    expect(screen.getByText("hidden but present body text")).toBeTruthy();

    const details = screen.getByTestId("wrapper") as HTMLDetailsElement;
    expect(details.open).toBe(false);
  });

  it("keeps children in the DOM while open too", () => {
    render(
      <Collapsible title="Section title" data-testid="wrapper">
        <p>visible body text</p>
      </Collapsible>,
    );

    expect(screen.getByText("visible body text")).toBeTruthy();
    const details = screen.getByTestId("wrapper") as HTMLDetailsElement;
    expect(details.open).toBe(true);
  });
});

describe("defaultOpen", () => {
  it("renders closed when defaultOpen={false}", () => {
    render(
      <Collapsible title="t" defaultOpen={false} data-testid="wrapper">
        body
      </Collapsible>,
    );
    const details = screen.getByTestId("wrapper") as HTMLDetailsElement;
    expect(details.open).toBe(false);
  });

  it("renders open when defaultOpen is omitted", () => {
    render(
      <Collapsible title="t" data-testid="wrapper">
        body
      </Collapsible>,
    );
    const details = screen.getByTestId("wrapper") as HTMLDetailsElement;
    expect(details.open).toBe(true);
  });
});

describe("clicking the summary toggles the <details>", () => {
  it("closes an open one on click", () => {
    render(
      <Collapsible title="Toggle me" data-testid="wrapper">
        body
      </Collapsible>,
    );
    const details = screen.getByTestId("wrapper") as HTMLDetailsElement;
    expect(details.open).toBe(true);

    fireEvent.click(screen.getByText("Toggle me"));
    expect(details.open).toBe(false);
  });

  it("opens a closed one on click", () => {
    render(
      <Collapsible title="Toggle me" defaultOpen={false} data-testid="wrapper">
        body
      </Collapsible>,
    );
    const details = screen.getByTestId("wrapper") as HTMLDetailsElement;
    expect(details.open).toBe(false);

    fireEvent.click(screen.getByText("Toggle me"));
    expect(details.open).toBe(true);
  });
});

describe("a caller's own heading passed via title still resolves as a heading", () => {
  it("finds it via getByRole('heading', ...)", () => {
    render(
      <Collapsible title={<h2 className="section-heading">Changes since last filing</h2>}>
        body
      </Collapsible>,
    );
    expect(
      screen.getByRole("heading", { name: "Changes since last filing" }),
    ).toBeTruthy();
  });
});

describe("data-testid", () => {
  it("lands on the root <details> element", () => {
    render(
      <Collapsible title="t" data-testid="my-collapsible">
        body
      </Collapsible>,
    );
    const el = screen.getByTestId("my-collapsible");
    expect(el.tagName).toBe("DETAILS");
  });
});
