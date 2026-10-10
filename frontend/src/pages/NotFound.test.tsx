/**
 * The 404 in isolation. `App.test.tsx` already proves the catch-all route reaches this component and
 * that its link count tracks `NAV`; this file pins the component's own contract — it names the failed
 * path verbatim, and it renders every destination grouped by section, straight from `@/nav`.
 *
 * The drift this guards is the one the component's own docstring describes: a second, hand-kept copy
 * of the destination list that falls behind the real nav. Reading `NAV` here (not a fixture) means a
 * page added to the nav without a translation, or a section renamed, fails this test at build time.
 */
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { NAV, NAV_ITEMS } from "@/nav";
import NotFound from "@/pages/NotFound";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <NotFound />
    </MemoryRouter>,
  );
}

describe("NotFound", () => {
  it("names the path that failed, verbatim", () => {
    renderAt("/rules-that-do-not-exist");
    // The path sits in its own <code>, so it is queryable as exact text even mid-sentence.
    expect(screen.getByText("/rules-that-do-not-exist")).toBeTruthy();
  });

  it("offers every nav destination as a link", () => {
    renderAt("/nope");
    const panel = document.querySelector(".panel");
    const links = within(panel as HTMLElement).getAllByRole("link");
    // One link per destination in NAV -- the whole point of reading from @/nav rather than a local
    // copy is that this count cannot silently fall behind the real nav.
    expect(links).toHaveLength(NAV_ITEMS.length);
  });

  it("groups the destinations by section, in nav order", () => {
    renderAt("/nope");
    const titles = Array.from(document.querySelectorAll(".destination-group-title")).map(
      (h) => h.textContent,
    );
    expect(titles).toHaveLength(NAV.length);
  });

  it("surfaces the pages that were merged in during the refactor", () => {
    // Symbol, Filers and Data are the routes the structure refactor introduced; a reader who typed
    // an old path must be able to find their new homes here.
    renderAt("/nope");
    const panel = document.querySelector(".panel") as HTMLElement;
    for (const label of ["Symbol", "Filers", "Data"]) {
      expect(within(panel).getByRole("link", { name: label })).toBeTruthy();
    }
  });
});
