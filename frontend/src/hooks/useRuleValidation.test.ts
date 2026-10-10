/**
 * `useRuleValidation` — the shared DSL check behind the event study, the scan and the strategy form.
 *
 * The behaviour worth pinning is not "it calls validate". It is the two rules that decide whether a
 * run button is allowed to disappear: a definitive `valid: false` must disable it, and *nothing else
 * may*. A 2026-08-29 UAT sweep found all three forms accepting `close >>> sma(` in silence; the
 * obvious fix — gate on "we have a valid result" — would replace a silent-acceptance bug with a
 * worse one, where an unreachable validate endpoint locks the reader out of running anything.
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useRuleValidation } from "@/hooks/useRuleValidation";

const validate = vi.hoisted(() => vi.fn());

vi.mock("@/api/rules", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/rules")>();
  return { ...actual, rulesApi: { ...actual.rulesApi, validate } };
});

const ok = (normalized: string) => ({ valid: true, error: null, normalized, indicators: [] });
const bad = (error: string) => ({ valid: false, error, normalized: null, indicators: [] });

beforeEach(() => {
  vi.useFakeTimers();
  validate.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});

/** Advance past the debounce and let the validate promises settle. */
async function settle() {
  await act(async () => {
    vi.advanceTimersByTime(400);
  });
}

describe("useRuleValidation", () => {
  it("reports a malformed expression as invalid, with the parser's own message", async () => {
    validate.mockResolvedValue(bad("expected a value, found '>'"));
    const { result } = renderHook(() => useRuleValidation(["close >>> sma("]));

    await settle();

    expect(result.current.invalid).toEqual(["close >>> sma("]);
    expect(result.current.resultFor("close >>> sma(")?.error).toBe("expected a value, found '>'");
  });

  it("reports nothing for a valid expression", async () => {
    validate.mockResolvedValue(ok("(close > sma(200))"));
    const { result } = renderHook(() => useRuleValidation(["close > sma(200)"]));

    await settle();

    expect(result.current.invalid).toEqual([]);
    expect(result.current.resultFor("close > sma(200)")?.valid).toBe(true);
  });

  it("treats a blank expression as absent, not invalid", async () => {
    // The strategy form's exit rule is optional. Sending "" to the parser would report it as a
    // syntax error and disable a button over a field the user is allowed to leave empty.
    const { result } = renderHook(() => useRuleValidation(["", "   "]));
    await settle();

    expect(validate).not.toHaveBeenCalled();
    expect(result.current.invalid).toEqual([]);
    expect(result.current.resultFor("")).toBeNull();
  });

  it("falls OPEN when the validate endpoint is unreachable", async () => {
    // The rule this hook exists to get right. `invalid` must stay empty so the caller's button stays
    // enabled -- a network blip must not become "you may no longer run anything".
    validate.mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useRuleValidation(["close >>> sma("]));

    await settle();

    expect(result.current.unavailable).toBe(true);
    expect(result.current.invalid).toEqual([]);
  });

  it("does not report anything as invalid while a check is still in flight", async () => {
    validate.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useRuleValidation(["close >>> sma("]));

    await settle();

    expect(result.current.checking).toBe(true);
    expect(result.current.invalid).toEqual([]);
  });

  it("debounces, so typing does not fire one request per character", async () => {
    validate.mockResolvedValue(ok("x"));
    const { rerender } = renderHook(({ e }: { e: string[] }) => useRuleValidation(e), {
      initialProps: { e: ["c"] },
    });
    rerender({ e: ["cl"] });
    rerender({ e: ["clo"] });
    rerender({ e: ["close > sma(200)"] });

    await settle();

    expect(validate).toHaveBeenCalledTimes(1);
    expect(validate).toHaveBeenCalledWith("close > sma(200)");
  });

  it("validates only the line that changed in a multi-expression set", async () => {
    // The scan's textarea: editing one of six lines must not re-check the other five.
    validate.mockResolvedValue(ok("x"));
    const { rerender } = renderHook(({ e }: { e: string[] }) => useRuleValidation(e), {
      initialProps: { e: ["rsi(14) < 30", "close > sma(200)"] },
    });
    await settle();
    expect(validate).toHaveBeenCalledTimes(2);

    validate.mockClear();
    rerender({ e: ["rsi(14) < 30", "close > sma(50)"] });
    await settle();

    expect(validate).toHaveBeenCalledTimes(1);
    expect(validate).toHaveBeenCalledWith("close > sma(50)");
  });

  it("keeps the verdicts that did arrive when one call in a batch fails", async () => {
    validate.mockImplementation((expr: string) =>
      expr === "boom" ? Promise.reject(new Error("down")) : Promise.resolve(bad("nope")),
    );
    const { result } = renderHook(() => useRuleValidation(["close >>> sma(", "boom"]));

    await settle();

    expect(result.current.unavailable).toBe(true);
    // The one that answered is still reported; a single failure does not blank the screen.
    expect(result.current.resultFor("close >>> sma(")?.valid).toBe(false);
  });
});
