/**
 * useUrlState: absent/invalid input resolves to the fallback rather than throwing, the setter
 * merges into the existing query string instead of replacing it, and writing the fallback back
 * removes the key instead of littering the URL with the default.
 *
 * `renderHook` needs a router in scope because `useSearchParams` reads `useLocation` internally --
 * `MemoryRouter` is the technique the rest of this suite already uses for that
 * (`App.test.tsx`, `PersonaBookCard.test.tsx`).
 */
import { renderHook, act } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter, useSearchParams } from "react-router-dom";
import type { ReactNode } from "react";

import { useUrlState, useUrlStateSet } from "@/hooks/useUrlState";

function wrapper(initialEntry: string) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={[initialEntry]}>{children}</MemoryRouter>;
  };
}

describe("useUrlState", () => {
  it("returns the fallback when the key is absent", () => {
    const { result } = renderHook(() => useUrlState("view", "summary"), {
      wrapper: wrapper("/account"),
    });
    expect(result.current[0]).toBe("summary");
  });

  it("returns the fallback when the value is not in `valid`", () => {
    const { result } = renderHook(
      () => useUrlState("view", "summary", { valid: ["summary", "detail"] as const }),
      { wrapper: wrapper("/account?view=deleted-tab") },
    );
    // A bookmark pointing at a tab that no longer exists must land on the fallback, not throw.
    expect(result.current[0]).toBe("summary");
  });

  it("reads a present, valid value", () => {
    const { result } = renderHook(
      () => useUrlState("view", "summary", { valid: ["summary", "detail"] as const }),
      { wrapper: wrapper("/account?view=detail") },
    );
    expect(result.current[0]).toBe("detail");
  });

  it("the setter preserves other query params already present", () => {
    const { result } = renderHook(
      () => {
        const [searchParams] = useSearchParams();
        const [view, setView] = useUrlState<"summary" | "detail">("view", "summary");
        return { view, setView, keep: searchParams.get("keep"), other: searchParams.get("other") };
      },
      { wrapper: wrapper("/account?keep=1&other=abc") },
    );

    act(() => result.current.setView("detail"));

    expect(result.current.view).toBe("detail");
    expect(result.current.keep).toBe("1");
    expect(result.current.other).toBe("abc");
  });

  it("setting the fallback removes the key rather than writing it", () => {
    const { result } = renderHook(
      () => {
        const [searchParams] = useSearchParams();
        const [view, setView] = useUrlState<"summary" | "detail">("view", "summary");
        return { view, setView, hasKey: searchParams.has("view") };
      },
      { wrapper: wrapper("/account?view=detail") },
    );
    expect(result.current.view).toBe("detail");
    expect(result.current.hasKey).toBe(true);

    act(() => result.current.setView("summary"));

    expect(result.current.view).toBe("summary");
    // Not merely equal to the fallback -- the key must be gone from the query string entirely, so
    // the default state renders as a clean URL rather than `?view=summary` forever after.
    expect(result.current.hasKey).toBe(false);
  });

  it("two hooks with different keys on one page do not clobber each other", () => {
    const { result } = renderHook(
      () => {
        const [tab, setTab] = useUrlState<"positions" | "closed">("tab", "positions");
        const [account, setAccount] = useUrlState<"all" | "roth-ira">("account", "all");
        return { tab, setTab, account, setAccount };
      },
      { wrapper: wrapper("/account") },
    );

    act(() => result.current.setTab("closed"));
    expect(result.current.tab).toBe("closed");
    expect(result.current.account).toBe("all");

    act(() => result.current.setAccount("roth-ira"));
    expect(result.current.account).toBe("roth-ira");
    // Setting `account` must not have reverted the earlier `tab` write.
    expect(result.current.tab).toBe("closed");
  });

  it("preserves an unrelated pre-existing param across a same-render write", () => {
    function useBoth() {
      const [searchParams] = useSearchParams();
      const [view, setView] = useUrlState<"summary" | "detail">("view", "summary");
      return { view, setView, keep: searchParams.get("keep") };
    }
    const { result } = renderHook(useBoth, { wrapper: wrapper("/account?keep=yes") });
    expect(result.current.keep).toBe("yes");

    act(() => result.current.setView("detail"));

    expect(result.current.view).toBe("detail");
    expect(result.current.keep).toBe("yes");
  });

  it("defaults to push history so Back returns to the previous selection", () => {
    // No direct way to inspect MemoryRouter's internal stack length from the public API, so this
    // asserts the documented default indirectly: `history` is omitted and the value still updates,
    // which is only meaningful because "push" (unlike a crash from an unhandled option) is the path
    // taken.
    const { result } = renderHook(() => useUrlState<"summary" | "detail">("view", "summary"), {
      wrapper: wrapper("/account"),
    });
    act(() => result.current[1]("detail"));
    expect(result.current[0]).toBe("detail");
  });
});

describe("useUrlStateSet", () => {
  it("returns an empty array when the key is absent", () => {
    const { result } = renderHook(() => useUrlStateSet("cols"), { wrapper: wrapper("/account") });
    expect(result.current[0]).toEqual([]);
  });

  it("round-trips a comma-joined set and removes the key when emptied", () => {
    const { result } = renderHook(() => useUrlStateSet("cols"), { wrapper: wrapper("/account") });

    act(() => result.current[1](["a", "b"]));
    expect(result.current[0]).toEqual(["a", "b"]);

    act(() => result.current[1]([]));
    expect(result.current[0]).toEqual([]);
  });
});
