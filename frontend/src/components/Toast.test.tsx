/**
 * ToastRegion: renders one node per toast, Undo calls the caller's handler then dismisses, an
 * auto-dismiss timer fires after its own duration and only its own, and a manual dismiss cancels
 * the pending timer so it can never later fire against a slot some other toast has since reused.
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastRegion, useToasts } from "@/components/Toast";
import type { ToastSpec } from "@/components/Toast";

afterEach(cleanup);

function toast(overrides: Partial<ToastSpec> = {}): ToastSpec {
  return {
    id: "t1",
    message: "Saved.",
    ...overrides,
  };
}

describe("rendering", () => {
  it("renders one node per toast", () => {
    render(
      <ToastRegion
        toasts={[toast({ id: "a", message: "First" }), toast({ id: "b", message: "Second" })]}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByText("First")).toBeTruthy();
    expect(screen.getByText("Second")).toBeTruthy();
  });

  it("is an aria-live polite region labelled for notifications", () => {
    render(<ToastRegion toasts={[]} onDismiss={vi.fn()} />);
    const region = screen.getByRole("region", { name: "Notifications" });
    expect(region.getAttribute("aria-live")).toBe("polite");
  });

  it("every toast has a dismiss control", () => {
    render(<ToastRegion toasts={[toast()]} onDismiss={vi.fn()} />);
    expect(screen.getByLabelText("Dismiss")).toBeTruthy();
  });

  it("renders an Undo button only when onUndo is given", () => {
    const { rerender } = render(<ToastRegion toasts={[toast()]} onDismiss={vi.fn()} />);
    expect(screen.queryByText("Undo")).toBeNull();

    rerender(<ToastRegion toasts={[toast({ onUndo: vi.fn() })]} onDismiss={vi.fn()} />);
    expect(screen.getByText("Undo")).toBeTruthy();
  });
});

describe("Undo", () => {
  it("calls onUndo and then dismisses the toast", () => {
    const onUndo = vi.fn();
    const onDismiss = vi.fn();
    render(<ToastRegion toasts={[toast({ onUndo })]} onDismiss={onDismiss} />);

    fireEvent.click(screen.getByText("Undo"));

    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(onDismiss).toHaveBeenCalledWith("t1");
  });
});

describe("manual dismiss", () => {
  it("clicking dismiss calls onDismiss with the toast's id", () => {
    const onDismiss = vi.fn();
    render(<ToastRegion toasts={[toast({ id: "xyz" })]} onDismiss={onDismiss} />);

    fireEvent.click(screen.getByLabelText("Dismiss"));

    expect(onDismiss).toHaveBeenCalledWith("xyz");
  });
});

describe("auto-dismiss", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("fires onDismiss after the given duration", () => {
    const onDismiss = vi.fn();
    render(<ToastRegion toasts={[toast({ durationMs: 1000 })]} onDismiss={onDismiss} />);

    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(onDismiss).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onDismiss).toHaveBeenCalledWith("t1");
  });

  it("defaults to 6000ms when durationMs is omitted", () => {
    const onDismiss = vi.fn();
    render(<ToastRegion toasts={[toast()]} onDismiss={onDismiss} />);

    act(() => {
      vi.advanceTimersByTime(5999);
    });
    expect(onDismiss).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onDismiss).toHaveBeenCalledWith("t1");
  });

  it("never auto-dismisses when durationMs is 0", () => {
    const onDismiss = vi.fn();
    render(<ToastRegion toasts={[toast({ durationMs: 0 })]} onDismiss={onDismiss} />);

    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("a manual dismiss cancels the pending timer so it cannot later fire against a reused id", () => {
    const onDismiss = vi.fn();
    const { rerender } = render(
      <ToastRegion toasts={[toast({ id: "a", durationMs: 1000 })]} onDismiss={onDismiss} />,
    );

    // Simulate the parent removing "a" in response to a manual dismiss, then reusing the same
    // array slot for a brand new toast "b" before "a"'s original timer would have fired.
    rerender(<ToastRegion toasts={[toast({ id: "b", durationMs: 1000 })]} onDismiss={onDismiss} />);

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    // Only "b" should have fired, exactly once -- a stale timer for "a" must not also fire and
    // dismiss whatever now occupies that slot.
    expect(onDismiss).toHaveBeenCalledTimes(1);
    expect(onDismiss).toHaveBeenCalledWith("b");
  });
});

describe("useToasts", () => {
  it("push adds a toast and returns its id; dismiss removes it", () => {
    let api!: ReturnType<typeof useToasts>;
    function Harness() {
      api = useToasts();
      return <ToastRegion toasts={api.toasts} onDismiss={api.dismiss} />;
    }
    render(<Harness />);

    let id = "";
    act(() => {
      id = api.push({ message: "Hello" });
    });
    expect(screen.getByText("Hello")).toBeTruthy();

    act(() => {
      api.dismiss(id);
    });
    expect(screen.queryByText("Hello")).toBeNull();
  });

  it("generates distinct ids for successive pushes", () => {
    let api!: ReturnType<typeof useToasts>;
    function Harness() {
      api = useToasts();
      return null;
    }
    render(<Harness />);

    let idA = "";
    let idB = "";
    act(() => {
      idA = api.push({ message: "A" });
      idB = api.push({ message: "B" });
    });
    expect(idA).not.toBe(idB);
  });
});
