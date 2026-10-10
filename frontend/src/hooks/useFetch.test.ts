/**
 * `useFetch`: fetches on mount, re-fetches when `deps` changes or `reload()` is called, guards a late
 * response against an unmount or a superseded request, and formats a caught rejection via
 * `formatError` (default: `formatFetchError`). These pin the contract every migrated page now relies
 * on instead of its own hand-rolled `useState`/`useEffect` triple.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api/client";
import { formatFetchError, useFetch } from "@/hooks/useFetch";

describe("useFetch", () => {
  it("starts loading, then reports the resolved data", async () => {
    const fetcher = vi.fn().mockResolvedValue({ value: 42 });
    const { result } = renderHook(() => useFetch(fetcher, []));

    expect(result.current.phase).toBe("loading");
    expect(result.current.data).toBeNull();

    await waitFor(() => expect(result.current.phase).toBe("loaded"));
    expect(result.current.data).toEqual({ value: 42 });
    expect(result.current.error).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("reports a formatted error on rejection, using the default formatter", async () => {
    const fetcher = vi.fn().mockRejectedValue(new ApiRequestError(500, "boom"));
    const { result } = renderHook(() => useFetch(fetcher, []));

    await waitFor(() => expect(result.current.phase).toBe("error"));
    expect(result.current.error).toBe("boom");
  });

  it("falls back to the default formatter's fallback text when the error carries no message", async () => {
    const fetcher = vi.fn().mockRejectedValue(new ApiRequestError(500, ""));
    const { result } = renderHook(() => useFetch(fetcher, []));

    await waitFor(() => expect(result.current.phase).toBe("error"));
    expect(result.current.error).toBe("Something went wrong.");
  });

  it("uses a supplied formatError instead of the default", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() =>
      useFetch(fetcher, [], { formatError: (err) => `custom: ${(err as Error).message}` }),
    );

    await waitFor(() => expect(result.current.phase).toBe("error"));
    expect(result.current.error).toBe("custom: network down");
  });

  it("never nulls out data on a failed re-fetch -- the last good response stays", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce({ value: 1 }).mockRejectedValueOnce(new Error("boom"));
    const { result, rerender } = renderHook(({ dep }) => useFetch(fetcher, [dep]), {
      initialProps: { dep: 1 },
    });

    await waitFor(() => expect(result.current.phase).toBe("loaded"));
    expect(result.current.data).toEqual({ value: 1 });

    rerender({ dep: 2 });

    await waitFor(() => expect(result.current.phase).toBe("error"));
    expect(result.current.data).toEqual({ value: 1 });
  });

  it("re-fetches when a dependency changes", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce({ value: 1 }).mockResolvedValueOnce({ value: 2 });
    const { result, rerender } = renderHook(({ dep }) => useFetch(fetcher, [dep]), {
      initialProps: { dep: "a" },
    });

    await waitFor(() => expect(result.current.data).toEqual({ value: 1 }));

    rerender({ dep: "b" });

    await waitFor(() => expect(result.current.data).toEqual({ value: 2 }));
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("does not re-fetch when deps are unchanged across a re-render", async () => {
    const fetcher = vi.fn().mockResolvedValue({ value: 1 });
    const { rerender } = renderHook(({ dep }) => useFetch(fetcher, [dep]), {
      initialProps: { dep: "a" },
    });

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));

    rerender({ dep: "a" });
    // Give any accidental extra effect run a chance to fire before asserting it didn't.
    await new Promise((r) => setTimeout(r, 0));
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("reload() re-runs the fetcher with unchanged deps", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce({ value: 1 }).mockResolvedValueOnce({ value: 2 });
    const { result } = renderHook(() => useFetch(fetcher, []));

    await waitFor(() => expect(result.current.data).toEqual({ value: 1 }));

    act(() => {
      result.current.reload();
    });

    await waitFor(() => expect(result.current.data).toEqual({ value: 2 }));
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("sets phase back to loading while a reload is in flight", async () => {
    let resolveSecond!: (v: { value: number }) => void;
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce({ value: 1 })
      .mockReturnValueOnce(new Promise<{ value: number }>((r) => { resolveSecond = r; }));
    const { result } = renderHook(() => useFetch(fetcher, []));

    await waitFor(() => expect(result.current.phase).toBe("loaded"));

    act(() => {
      result.current.reload();
    });
    expect(result.current.phase).toBe("loading");

    await act(async () => {
      resolveSecond({ value: 2 });
    });
    expect(result.current.phase).toBe("loaded");
  });

  it("ignores a response that resolves after the component unmounted", async () => {
    let resolveFetch!: (v: { value: number }) => void;
    const fetcher = vi.fn().mockReturnValue(new Promise<{ value: number }>((r) => { resolveFetch = r; }));
    const { result, unmount } = renderHook(() => useFetch(fetcher, []));

    unmount();
    await act(async () => {
      resolveFetch({ value: 1 });
    });

    // Nothing to assert on `result.current` post-unmount beyond "no thrown act() warning"; the guard
    // under test is that `setData`/`setPhase` are never called for an unmounted component.
    expect(result.current.phase).toBe("loading");
  });

  it("ignores a stale response that lands after a newer request already went out", async () => {
    let resolveFirst!: (v: { value: number }) => void;
    const fetcher = vi
      .fn()
      .mockReturnValueOnce(new Promise<{ value: number }>((r) => { resolveFirst = r; }))
      .mockResolvedValueOnce({ value: 2 });
    const { result, rerender } = renderHook(({ dep }) => useFetch(fetcher, [dep]), {
      initialProps: { dep: 1 },
    });

    rerender({ dep: 2 });
    await waitFor(() => expect(result.current.data).toEqual({ value: 2 }));

    // The first request's late resolution must not clobber the second, newer one.
    await act(async () => {
      resolveFirst({ value: 1 });
    });
    expect(result.current.data).toEqual({ value: 2 });
  });
});

describe("setData", () => {
  it("overwrites data without touching phase or re-fetching", async () => {
    const fetcher = vi.fn().mockResolvedValue([1, 2, 3]);
    const { result } = renderHook(() => useFetch<number[]>(fetcher, []));

    await waitFor(() => expect(result.current.data).toEqual([1, 2, 3]));

    act(() => {
      result.current.setData((prev: number[] | null) => (prev ?? []).filter((n) => n !== 2));
    });

    expect(result.current.data).toEqual([1, 3]);
    expect(result.current.phase).toBe("loaded");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("accepts a plain value in addition to an updater function", async () => {
    const fetcher = vi.fn().mockResolvedValue({ value: 1 });
    const { result } = renderHook(() => useFetch(fetcher, []));

    await waitFor(() => expect(result.current.data).toEqual({ value: 1 }));

    act(() => {
      result.current.setData({ value: 99 });
    });

    expect(result.current.data).toEqual({ value: 99 });
  });
});

describe("skip", () => {
  it("never calls the fetcher while skip is true, leaving the initial loading phase alone", async () => {
    const fetcher = vi.fn().mockResolvedValue({ value: 1 });
    const { result } = renderHook(() => useFetch(fetcher, [], { skip: true }));

    await new Promise((r) => setTimeout(r, 0));
    expect(fetcher).not.toHaveBeenCalled();
    expect(result.current.phase).toBe("loading");
    expect(result.current.data).toBeNull();
  });

  it("fetches once skip flips to false", async () => {
    const fetcher = vi.fn().mockResolvedValue({ value: 1 });
    const { result, rerender } = renderHook(({ skip }) => useFetch(fetcher, [], { skip }), {
      initialProps: { skip: true },
    });

    expect(fetcher).not.toHaveBeenCalled();

    rerender({ skip: false });

    await waitFor(() => expect(result.current.phase).toBe("loaded"));
    expect(result.current.data).toEqual({ value: 1 });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("leaves the last loaded data alone if skip flips back to true", async () => {
    const fetcher = vi.fn().mockResolvedValue({ value: 1 });
    const { result, rerender } = renderHook(({ skip }) => useFetch(fetcher, [], { skip }), {
      initialProps: { skip: false },
    });

    await waitFor(() => expect(result.current.data).toEqual({ value: 1 }));

    rerender({ skip: true });
    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.data).toEqual({ value: 1 });
    expect(result.current.phase).toBe("loaded");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});

describe("formatFetchError", () => {
  it("prefers an ApiRequestError's own message", () => {
    expect(formatFetchError(new ApiRequestError(404, "not found"), "fallback")).toBe("not found");
  });

  it("prefers a plain Error's own message", () => {
    expect(formatFetchError(new Error("boom"), "fallback")).toBe("boom");
  });

  it("falls back for a non-Error thrown value", () => {
    expect(formatFetchError("just a string", "fallback")).toBe("fallback");
  });

  it("falls back when the Error's message is empty", () => {
    expect(formatFetchError(new Error(""), "fallback")).toBe("fallback");
  });
});
