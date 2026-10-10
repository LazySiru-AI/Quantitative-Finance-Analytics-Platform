/**
 * StatusPill / PillLegend: every tone renders its words (colour is never the only signal), the
 * detail reaches assistive tech rather than only a hover tooltip, and the legend suppresses itself
 * when it would explain a single pill to nobody.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import PillLegend from "@/components/PillLegend";
import StatusPill, { TranslatedStatusPill, type PillTone } from "@/components/StatusPill";

afterEach(cleanup);

const TONES: PillTone[] = ["ok", "warn", "bad", "info", "special", "neutral"];

describe("StatusPill", () => {
  it("always renders its label, in every tone", () => {
    // The structural half of "colour is never the only signal": there is no way to render a pill
    // that is colour alone, because the label is required and always painted.
    for (const tone of TONES) {
      cleanup();
      render(<StatusPill tone={tone} label={`state ${tone}`} />);
      expect(screen.getByText(`state ${tone}`)).toBeTruthy();
    }
  });

  it("applies the tone class rather than an inline colour", () => {
    render(<StatusPill tone="warn" label="Stale" data-testid="pill" />);
    const pill = screen.getByTestId("pill");
    expect(pill.className).toContain("status-pill-warn");
    expect(pill.getAttribute("style")).toBeNull();
  });

  it("exposes the detail to assistive tech, not only to a mouse hover", () => {
    render(<StatusPill tone="warn" label="Stale 3d" detail="Mark is 3 sessions behind." data-testid="pill" />);
    const pill = screen.getByTestId("pill");
    expect(pill.getAttribute("title")).toBe("Mark is 3 sessions behind.");
    expect(pill.getAttribute("aria-description")).toBe("Mark is 3 sessions behind.");
  });

  it("omits the tooltip attributes entirely when there is no detail", () => {
    render(<StatusPill tone="ok" label="Live" data-testid="pill" />);
    expect(screen.getByTestId("pill").hasAttribute("title")).toBe(false);
  });
});

describe("TranslatedStatusPill", () => {
  it("resolves a catalog key to the active language", () => {
    render(<TranslatedStatusPill tone="warn" labelKey="ui.pill.dormant" />);
    expect(screen.getByText("Dormant")).toBeTruthy();
  });

  it("interpolates params", () => {
    render(<TranslatedStatusPill tone="warn" labelKey="ui.pill.staleDays" params={{ days: 3 }} />);
    expect(screen.getByText("Stale 3d")).toBeTruthy();
  });
});

describe("PillLegend", () => {
  it("renders nothing for fewer than two tones", () => {
    const { container } = render(
      <PillLegend label="Status legend" entries={[{ tone: "ok", label: "Live" }]} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("lists each entry with its words and gloss", () => {
    render(
      <PillLegend
        label="Status legend"
        entries={[
          { tone: "ok", label: "Live", gloss: "trading now" },
          { tone: "warn", label: "Stale", gloss: "mark behind" },
        ]}
      />,
    );
    expect(screen.getByRole("list", { name: "Status legend" })).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("trading now")).toBeTruthy();
    expect(screen.getByText("Stale")).toBeTruthy();
  });
});
