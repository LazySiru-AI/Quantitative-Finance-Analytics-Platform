/**
 * The shell, rendered in Korean, scanned for English that survived.
 *
 * This is the pattern every page test should follow once its strings are extracted, and it is here
 * first because the shell is the part a Korean reader sees on every route. The existing suite runs
 * in English and asserts on exactly that English, so it can never notice a string that was left
 * behind -- only a render in the other language can.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ErrorBoundary from "@/components/ErrorBoundary";
import PanelBoundary from "@/components/PanelBoundary";
import { LANGUAGE_STORAGE_KEY, refreshLanguageFromStorage, setLanguage } from "@/i18n/store";
import NotFound from "@/pages/NotFound";
import { englishLeftovers } from "@/test/koScan";

function Boom(): never {
  throw new Error("Cannot read properties of undefined (reading 'weight')");
}

describe("shell in Korean", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    setLanguage("ko");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
    refreshLanguageFromStorage();
  });

  it("leaves no English in the page-level crash fallback", () => {
    const { container } = render(
      <ErrorBoundary area="/portfolio">
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("이 페이지의 렌더링이 중단되었습니다.")).toBeTruthy();
    // The thrown message sits in a `<pre>`, which the scanner skips on purpose: a runtime error
    // string is wanted verbatim, in whatever language the runtime produced it.
    expect(englishLeftovers(container)).toEqual([]);
  });

  it("leaves no English in the panel-level crash fallback, labelled or not", () => {
    const labelled = render(
      <PanelBoundary label="보유 종목">
        <Boom />
      </PanelBoundary>,
    );
    expect(englishLeftovers(labelled.container)).toEqual([]);

    const bare = render(
      <PanelBoundary>
        <Boom />
      </PanelBoundary>,
    );
    expect(englishLeftovers(bare.container)).toEqual([]);
  });

  it("puts the Korean panel label in front of the verb rather than appended to it", () => {
    render(
      <PanelBoundary label="보유 종목">
        <Boom />
      </PanelBoundary>,
    );
    // English says "This panel could not be displayed — Holdings."; Korean puts the qualifier first.
    // Asserting the order is what proves the two forms are separate catalog entries rather than one
    // English stem with a label glued on.
    expect(screen.getByText("보유 종목 패널을 표시할 수 없습니다.")).toBeTruthy();
  });

  it("leaves no English in the 404's own chrome", () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/nope"]}>
        <NotFound />
      </MemoryRouter>,
    );
    expect(screen.getByText("찾을 수 없음")).toBeTruthy();
    expect(screen.getByText("/nope")).toBeTruthy();
    // The destination list is now translated too (labels and blurbs route through the catalog), so
    // it is scanned rather than skipped. `Form 8949` is an allowed identifier: the Tax blurb keeps
    // the US form number in Latin in both languages.
    expect(englishLeftovers(container, { allow: ["Form"] })).toEqual([]);
  });
});
