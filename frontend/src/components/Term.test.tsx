/**
 * Term: the definition has to be reachable by every reader, not just the one holding a mouse.
 *
 * The three properties worth asserting are the three the native `title` attribute this component
 * replaces does not have: the tip opens from the keyboard, it can be dismissed without moving
 * focus, and it is wired to the word by `aria-describedby` so a screen reader reads the definition
 * as the word's description rather than as a stray fragment of the page.
 *
 * The last block walks the whole glossary. `tsc` already proves every entry has both languages
 * (`MessagePair` makes a key impossible without them) and `proseBudget.test.ts` proves the lengths,
 * so what is left is what neither can see: that every slug the `k` prop accepts actually resolves
 * to a rendered definition in both languages, rather than to a key that was renamed on one side.
 */
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import Term from "@/components/Term";
import { CATALOG } from "@/i18n/catalog";
import { GLOSSARY_SLUGS } from "@/i18n/messages/glossary";
import { budgetFor } from "@/i18n/proseBudget";
import { LANGUAGE_STORAGE_KEY, refreshLanguageFromStorage, setLanguage } from "@/i18n/store";

function resetLanguage(): void {
  window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  refreshLanguageFromStorage();
}

beforeEach(resetLanguage);
afterEach(() => {
  cleanup();
  resetLanguage();
});

const Q_DEF = CATALOG["glossary.qValue.def"].en;

describe("the word", () => {
  it("renders its children unchanged, so applying it does not rewrite a label", () => {
    render(<Term k="qValue">q</Term>);
    expect(screen.getByText("q")).toBeTruthy();
  });

  it("falls back to the term's own display name when given no children", () => {
    render(<Term k="qValue" />);
    expect(screen.getByText(CATALOG["glossary.qValue.term"].en)).toBeTruthy();
  });

  it("is reachable from the keyboard", async () => {
    const user = userEvent.setup();
    render(<Term k="qValue" data-testid="term">q</Term>);

    await user.tab();

    expect(document.activeElement).toBe(screen.getByTestId("term"));
  });
});

describe("the tip", () => {
  it("describes the word through aria-describedby", () => {
    render(<Term k="qValue" data-testid="term">q</Term>);

    const term = screen.getByTestId("term");
    const tip = screen.getByRole("tooltip");

    expect(tip.id).toBeTruthy();
    expect(term.getAttribute("aria-describedby")).toBe(tip.id);
    expect(tip.textContent).toBe(Q_DEF);
  });

  it("stays mounted while closed, so the description resolves and find-in-page reaches it", () => {
    render(<Term k="qValue" data-testid="term">q</Term>);

    expect(screen.getByTestId("term").getAttribute("data-open")).toBe("false");
    // Closed is a visual state, not an unmounted one -- an `aria-describedby` pointing at a node
    // that is not there describes nothing at all.
    expect(screen.getByRole("tooltip").textContent).toBe(Q_DEF);
  });

  it("opens on keyboard focus and closes again on blur", () => {
    render(<Term k="qValue" data-testid="term">q</Term>);
    const term = screen.getByTestId("term") as HTMLSpanElement;

    // `.focus()` rather than `fireEvent.focus`: React listens for `focusin`, which only a real DOM
    // focus emits -- a synthetic non-bubbling `focus` event never reaches the handler. `act` flushes
    // the state update the handler schedules.
    act(() => term.focus());
    expect(term.getAttribute("data-open")).toBe("true");

    act(() => term.blur());
    expect(term.getAttribute("data-open")).toBe("false");
  });

  it("opens on hover, for the reader who never leaves the mouse", async () => {
    const user = userEvent.setup();
    render(<Term k="qValue" data-testid="term">q</Term>);
    const term = screen.getByTestId("term");

    await user.hover(term);
    expect(term.getAttribute("data-open")).toBe("true");

    await user.unhover(term);
    expect(term.getAttribute("data-open")).toBe("false");
  });

  it("is dismissed by Escape without moving focus", async () => {
    const user = userEvent.setup();
    render(<Term k="qValue" data-testid="term">q</Term>);
    const term = screen.getByTestId("term") as HTMLSpanElement;

    act(() => term.focus());
    expect(term.getAttribute("data-open")).toBe("true");

    await user.keyboard("{Escape}");

    expect(term.getAttribute("data-open")).toBe("false");
    // Dismissing a tooltip must not cost the reader their place in the tab order.
    expect(document.activeElement).toBe(term);
  });
});

describe("the glossary", () => {
  it("defines at least the terms these pages render", () => {
    // A floor, not an inventory: the point is that the shard is not empty and that the slugs the
    // pages import are the ones it exports.
    expect(GLOSSARY_SLUGS.length).toBeGreaterThanOrEqual(13);
    expect(GLOSSARY_SLUGS).toContain("qValue");
    expect(GLOSSARY_SLUGS).toContain("insufficient");
  });

  it("resolves every slug to a term and a definition in both languages", () => {
    const broken: string[] = [];
    for (const slug of GLOSSARY_SLUGS) {
      for (const half of ["term", "def"] as const) {
        const key = `glossary.${slug}.${half}` as keyof typeof CATALOG;
        const pair = CATALOG[key];
        if (!pair) {
          broken.push(`${key}: missing`);
          continue;
        }
        if (pair.en.trim() === "") broken.push(`${key}: empty en`);
        if (pair.ko.trim() === "") broken.push(`${key}: empty ko`);
      }
    }
    expect(broken).toEqual([]);
  });

  it("keeps every definition inside the note budget, in both languages", () => {
    // `proseBudget.test.ts` enforces this across the whole catalog; asserted here as well because
    // a definition is written to fit a tooltip, and 120 characters is the reason it reads at all.
    const over: string[] = [];
    for (const slug of GLOSSARY_SLUGS) {
      const key = `glossary.${slug}.def` as keyof typeof CATALOG;
      const budget = budgetFor(key);
      for (const lang of ["en", "ko"] as const) {
        const text = CATALOG[key][lang];
        if (text.length > budget) over.push(`${key} [${lang}] ${text.length} > ${budget}`);
      }
    }
    expect(over).toEqual([]);
  });

  it("renders every slug's definition in Korean too", () => {
    setLanguage("ko");
    for (const slug of GLOSSARY_SLUGS) {
      const { unmount } = render(<Term k={slug}>x</Term>);
      const key = `glossary.${slug}.def` as keyof typeof CATALOG;
      expect(screen.getByRole("tooltip").textContent).toBe(CATALOG[key].ko);
      unmount();
    }
  });
});
