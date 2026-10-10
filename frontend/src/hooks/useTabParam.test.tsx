/**
 * useTabParam: the three properties every tabbed page now leans on.
 *
 *  - a missing or unrecognised `?tab=` resolves to the fallback and never throws, so a bookmark
 *    saved before a deploy removed a tab still opens the page;
 *  - the setter writes the param, so the tab is linkable;
 *  - the setter MERGES, so a year/round/symbol param already on the URL survives a tab click.
 *
 * The last one is the property a naive `setSearchParams({ tab })` breaks, and it is load-bearing on
 * three of the six call sites -- hence a test per shape rather than one combined case.
 *
 * `renderHook` needs a router in scope because `useSearchParams` reads `useLocation` internally;
 * `MemoryRouter` is how the rest of this suite supplies one (`useUrlState.test.tsx`, `App.test.tsx`).
 */
import { renderHook, act } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { useTabParam } from "@/hooks/useTabParam";

type Tab = "summary" | "disposals" | "wash";
const TABS: readonly Tab[] = ["summary", "disposals", "wash"];

function wrapper(initialEntry: string) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={[initialEntry]}>{children}</MemoryRouter>;
  };
}

describe("useTabParam", () => {
  it("returns the fallback when the param is absent", () => {
    const { result } = renderHook(() => useTabParam<Tab>("tab", TABS, "summary"), {
      wrapper: wrapper("/tax"),
    });
    expect(result.current[0]).toBe("summary");
  });

  it("returns the fallback for a value outside `allowed`, rather than throwing", () => {
    // The failure this prevents: the raw string reaching a caller that union-switches on it and
    // renders nothing (or worse, throws an exhaustiveness error) for a tab id it has never heard
    // of. A hand-edited query string is no more trustworthy than a server field.
    const { result } = renderHook(() => useTabParam<Tab>("tab", TABS, "summary"), {
      wrapper: wrapper("/tax?tab=deleted-in-a-later-deploy"),
    });
    expect(result.current[0]).toBe("summary");
  });

  it("returns the fallback for an empty value", () => {
    const { result } = renderHook(() => useTabParam<Tab>("tab", TABS, "summary"), {
      wrapper: wrapper("/tax?tab="),
    });
    expect(result.current[0]).toBe("summary");
  });

  it("reads a present, allowed value", () => {
    const { result } = renderHook(() => useTabParam<Tab>("tab", TABS, "summary"), {
      wrapper: wrapper("/tax?tab=wash"),
    });
    expect(result.current[0]).toBe("wash");
  });

  it("reads whichever param name the caller asked for, not a hard-coded `tab`", () => {
    // Every current call site happens to use `tab`, but a page with two independent rails would
    // need two names, and a hook that ignored its first argument would pass every other test here.
    const { result } = renderHook(() => useTabParam<Tab>("section", TABS, "summary"), {
      wrapper: wrapper("/tax?section=disposals&tab=wash"),
    });
    expect(result.current[0]).toBe("disposals");
  });

  it("the setter writes the value into the query string", () => {
    const { result } = renderHook(
      () => {
        const [tab, setTab] = useTabParam<Tab>("tab", TABS, "summary");
        const location = useLocation();
        return { tab, setTab, search: location.search };
      },
      { wrapper: wrapper("/tax") },
    );

    act(() => result.current.setTab("wash"));

    expect(result.current.tab).toBe("wash");
    expect(result.current.search).toContain("tab=wash");
  });

  it("the setter preserves other params already on the URL", () => {
    // `Tax.tsx` may carry a year, `Competition.tsx` a round, and `Symbol.tsx` is arrived at from
    // `App.tsx`'s `/report/:symbol` redirect. A `setSearchParams({ tab })` would drop all of them
    // on the first tab click.
    const { result } = renderHook(
      () => {
        const [searchParams] = useSearchParams();
        const [tab, setTab] = useTabParam<Tab>("tab", TABS, "summary");
        return { tab, setTab, year: searchParams.get("year"), round: searchParams.get("round") };
      },
      { wrapper: wrapper("/tax?year=2026&round=r13-2026-08") },
    );

    act(() => result.current.setTab("disposals"));

    expect(result.current.tab).toBe("disposals");
    expect(result.current.year).toBe("2026");
    expect(result.current.round).toBe("r13-2026-08");
  });

  it("pushes rather than replaces, so Back returns to the previous tab", () => {
    // This is the half of finding UX-11 that is about the Back button: six tab clicks that push
    // nothing leave Back pointing at whatever page the reader was on BEFORE this one, so pressing
    // it reads as the button skipping the page entirely.
    const { result } = renderHook(
      () => {
        const [tab, setTab] = useTabParam<Tab>("tab", TABS, "summary");
        const navigate = useNavigate();
        return { tab, setTab, navigate };
      },
      { wrapper: wrapper("/tax") },
    );

    act(() => result.current.setTab("disposals"));
    act(() => result.current.setTab("wash"));
    expect(result.current.tab).toBe("wash");

    // `MemoryRouter` has no window history to click a real Back button against, but `navigate(-1)`
    // pops the same stack the browser's Back button pops -- which only has anything to pop if the
    // setter pushed. Under `replace: true` both clicks would have overwritten one entry and this
    // would still read "wash".
    act(() => result.current.navigate(-1));
    expect(result.current.tab).toBe("disposals");

    act(() => result.current.navigate(-1));
    expect(result.current.tab).toBe("summary");
  });

  it("writing the fallback back clears the param instead of pinning ?tab=<default> forever", () => {
    const { result } = renderHook(
      () => {
        const [tab, setTab] = useTabParam<Tab>("tab", TABS, "summary");
        const location = useLocation();
        return { tab, setTab, search: location.search };
      },
      { wrapper: wrapper("/tax?tab=wash") },
    );

    act(() => result.current.setTab("summary"));

    expect(result.current.tab).toBe("summary");
    expect(result.current.search).not.toContain("tab=");
  });
});
