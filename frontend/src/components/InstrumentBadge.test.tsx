/**
 * InstrumentBadge: a plain equity is the unremarkable default and renders nothing; everything else
 * gets a `StatusPill` whose detail says it is not directly tradeable by the strategy layer.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import InstrumentBadge, { type InstrumentKindLike } from "@/components/InstrumentBadge";

afterEach(cleanup);

describe("equity", () => {
  it("renders nothing for a plain equity", () => {
    const { container } = render(<InstrumentBadge instrument="equity" />);
    expect(container.firstChild).toBeNull();
  });
});

describe("non-equity instruments", () => {
  it("renders a pill for crypto with the not-tradeable detail", () => {
    render(<InstrumentBadge instrument="crypto" data-testid="badge" />);
    const el = screen.getByTestId("badge");
    expect(el.textContent).toBe("Crypto");
    expect(el.getAttribute("title")).toBe("Not directly tradeable by the strategy layer");
  });

  it("uses info tone for etf and index", () => {
    render(<InstrumentBadge instrument="etf" data-testid="etf" />);
    render(<InstrumentBadge instrument="index" data-testid="index" />);
    expect(screen.getByTestId("etf").className).toContain("status-pill-info");
    expect(screen.getByTestId("index").className).toContain("status-pill-info");
  });

  it("uses special tone for future, crypto and fx", () => {
    render(<InstrumentBadge instrument="future" data-testid="future" />);
    render(<InstrumentBadge instrument="crypto" data-testid="crypto" />);
    render(<InstrumentBadge instrument="fx" data-testid="fx" />);
    expect(screen.getByTestId("future").className).toContain("status-pill-special");
    expect(screen.getByTestId("crypto").className).toContain("status-pill-special");
    expect(screen.getByTestId("fx").className).toContain("status-pill-special");
  });

  it("uses neutral tone for an unclassified instrument", () => {
    render(<InstrumentBadge instrument="unknown" data-testid="unknown" />);
    expect(screen.getByTestId("unknown").className).toContain("status-pill-neutral");
  });

  it("renders every non-equity kind with a visible label", () => {
    const kinds: Exclude<InstrumentKindLike, "equity">[] = ["etf", "index", "future", "crypto", "fx", "unknown"];
    for (const kind of kinds) {
      cleanup();
      render(<InstrumentBadge instrument={kind} data-testid="badge" />);
      expect(screen.getByTestId("badge").textContent).not.toBe("");
    }
  });
});
