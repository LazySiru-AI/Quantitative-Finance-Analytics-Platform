/**
 * The privacy switch and the store behind it.
 *
 * The assertions are deliberately on `<html data-redact>` rather than on any blurred element: that
 * attribute is the entire contract between this component and `styles.css`, and it is the only part
 * of the feature jsdom can see -- jsdom parses no stylesheet and computes no `filter`, so a test
 * that "checked the blur" would be checking nothing. What can be proven here is that the switch
 * writes the attribute, remembers the choice, and reads it back.
 *
 * The store is module-level state (see `@/privacy`), so it outlives any one test in this file unless
 * it is reset -- the same reason `App.test.tsx` resets the favourites store.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import PrivacyToggle from "@/components/PrivacyToggle";
import { PRIVACY_STORAGE_KEY, isRedacted, refreshPrivacyFromStorage } from "@/privacy";

beforeEach(() => {
  window.localStorage.clear();
  refreshPrivacyFromStorage();
});

function button() {
  return screen.getByRole("button");
}

describe("PrivacyToggle", () => {
  it("starts showing amounts, and offers to hide them", () => {
    render(<PrivacyToggle />);
    expect(button().textContent).toBe("Hide amounts");
    expect(button().getAttribute("aria-pressed")).toBe("false");
    expect(document.documentElement.dataset["redact"]).not.toBe("on");
  });

  it("sets data-redact on the document element when pressed", async () => {
    const user = userEvent.setup();
    render(<PrivacyToggle />);

    await user.click(button());

    expect(document.documentElement.dataset["redact"]).toBe("on");
    expect(button().getAttribute("aria-pressed")).toBe("true");
    // The label names the next action, not the current state -- `aria-pressed` carries the state.
    expect(button().textContent).toBe("Show amounts");
  });

  it("clears data-redact again when pressed a second time", async () => {
    const user = userEvent.setup();
    render(<PrivacyToggle />);

    await user.click(button());
    await user.click(button());

    expect(document.documentElement.dataset["redact"]).not.toBe("on");
    expect(button().getAttribute("aria-pressed")).toBe("false");
  });

  it("persists the choice", async () => {
    const user = userEvent.setup();
    render(<PrivacyToggle />);

    await user.click(button());

    expect(window.localStorage.getItem(PRIVACY_STORAGE_KEY)).toBe("on");
  });

  it("reads a stored preference back", () => {
    window.localStorage.setItem(PRIVACY_STORAGE_KEY, "on");
    refreshPrivacyFromStorage();

    expect(isRedacted()).toBe(true);
    render(<PrivacyToggle />);
    expect(button().getAttribute("aria-pressed")).toBe("true");
    expect(document.documentElement.dataset["redact"]).toBe("on");
  });

  it("survives a storage read that throws", () => {
    // Safari private mode and some embedded webviews throw on `getItem`. Defaulting off is the
    // deliberate direction: the app must render, showing the figures the owner asked to see.
    const original = window.localStorage.getItem;
    window.localStorage.getItem = () => {
      throw new Error("denied");
    };
    try {
      refreshPrivacyFromStorage();
      expect(isRedacted()).toBe(false);
    } finally {
      window.localStorage.getItem = original;
    }
  });
});
