/**
 * The skip link: it exists, it is focusable, and it points at the one id `App` gives `<main>`.
 *
 * The href is asserted as a literal rather than read from a shared constant on purpose -- the whole
 * failure mode this guards is the two halves drifting apart (the link renamed, or the `id` on
 * `<main>` renamed), and a shared constant would make both move together and the test pass through
 * the break. `App.test.tsx` asserts the other half against the real shell.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import SkipLink from "@/components/SkipLink";
import { setLanguage } from "@/i18n/store";

describe("SkipLink", () => {
  it("renders a link to #content", () => {
    render(<SkipLink />);
    const link = screen.getByRole("link", { name: "Skip to content" });
    expect(link.getAttribute("href")).toBe("#content");
  });

  it("is reachable by keyboard -- it is in the DOM, not display:none", async () => {
    const user = userEvent.setup();
    render(<SkipLink />);
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("link", { name: "Skip to content" }));
  });

  it("translates", () => {
    setLanguage("ko");
    try {
      render(<SkipLink />);
      expect(screen.getByRole("link", { name: "본문으로 건너뛰기" })).toBeTruthy();
    } finally {
      setLanguage("en");
    }
  });
});
