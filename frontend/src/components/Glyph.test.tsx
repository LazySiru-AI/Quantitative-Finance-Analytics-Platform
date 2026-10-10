/**
 * Glyph: every glyph in the §3.3 vocabulary renders its exact Unicode character, is decorative
 * (`aria-hidden`, no role) by default, and switches to `role="img"` + `aria-label` only when a
 * caller supplies `label` -- the one prop this component reads for accessibility, since it has no
 * i18n dependency of its own (see the file's own docstring).
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Glyph, type GlyphName } from "@/components/Glyph";

afterEach(cleanup);

const EXPECTED: Record<GlyphName, string> = {
  up: "▲",
  down: "▼",
  live: "●",
  partial: "◐",
  idle: "○",
  warn: "⚠",
  pass: "✓",
  fail: "✗",
  age: "⏱",
  seat: "◆",
  info: "ⓘ",
  star: "★",
};

describe("vocabulary", () => {
  for (const name of Object.keys(EXPECTED) as GlyphName[]) {
    it(`renders the "${name}" glyph as ${EXPECTED[name]}`, () => {
      render(<Glyph name={name} data-testid="g" />);
      expect(screen.getByTestId("g").textContent).toBe(EXPECTED[name]);
    });
  }
});

describe("decorative by default", () => {
  it("is aria-hidden with no role when no label is given", () => {
    render(<Glyph name="up" data-testid="g" />);
    const el = screen.getByTestId("g");
    expect(el.getAttribute("aria-hidden")).toBe("true");
    expect(el.getAttribute("role")).toBeNull();
    expect(el.getAttribute("aria-label")).toBeNull();
  });

  it("carries the glyph-<name> class for tone styling", () => {
    render(<Glyph name="down" data-testid="g" />);
    expect(screen.getByTestId("g").className).toContain("glyph-down");
  });

  it("appends a caller-supplied className alongside the base classes", () => {
    render(<Glyph name="warn" className="stat-value-direction" data-testid="g" />);
    const el = screen.getByTestId("g");
    expect(el.className).toContain("glyph");
    expect(el.className).toContain("glyph-warn");
    expect(el.className).toContain("stat-value-direction");
  });
});

describe("labelled", () => {
  it("switches to role=img and aria-label when label is supplied, and drops aria-hidden", () => {
    render(<Glyph name="live" label="live" data-testid="g" />);
    const el = screen.getByTestId("g");
    expect(el.getAttribute("role")).toBe("img");
    expect(el.getAttribute("aria-label")).toBe("live");
    expect(el.getAttribute("aria-hidden")).toBeNull();
    expect(el.textContent).toBe("●");
  });
});
