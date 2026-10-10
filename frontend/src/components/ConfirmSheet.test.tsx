/**
 * ConfirmSheet: renders nothing when closed, is a properly labelled dialog when open with focus
 * landing inside it, Escape and the backdrop both cancel, confirm confirms, and `busy` disables
 * both buttons and swaps the confirm label.
 */
import { useState } from "react";

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ConfirmSheet from "@/components/ConfirmSheet";

afterEach(cleanup);

describe("closed", () => {
  it("renders nothing when open is false", () => {
    const { container } = render(
      <ConfirmSheet
        open={false}
        question="Recompute every book from 2026-01-02?"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(container.innerHTML).toBe("");
  });
});

describe("open", () => {
  it("renders a dialog labelled by the question", () => {
    render(
      <ConfirmSheet
        open
        question="Recompute every book from 2026-01-02?"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(screen.getByText("Recompute every book from 2026-01-02?")).toBeTruthy();
  });

  it("renders the preview under a 'What will change' heading", () => {
    render(
      <ConfirmSheet
        open
        question="Recompute every book?"
        preview={<p>3 lots reclassified</p>}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText("What will change")).toBeTruthy();
    expect(screen.getByText("3 lots reclassified")).toBeTruthy();
  });

  it("moves focus inside the sheet on open, onto the cancel button", () => {
    render(
      <ConfirmSheet open question="Recompute every book?" onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).toBe(screen.getByText("Cancel"));
  });

  it("returns focus to the previously focused element on close", () => {
    function Harness() {
      const [open, setOpen] = useState(true);
      return (
        <div>
          <button
            onClick={() => {
              /* not used; button just needs to have held focus before opening */
            }}
          >
            trigger
          </button>
          <ConfirmSheet
            open={open}
            question="Recompute every book?"
            onConfirm={vi.fn()}
            onCancel={() => setOpen(false)}
          />
        </div>
      );
    }
    const trigger = document.createElement("button");
    trigger.textContent = "outside trigger";
    document.body.appendChild(trigger);
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    const { unmount } = render(<Harness />);
    // Opening moved focus into the sheet.
    expect(document.activeElement).not.toBe(trigger);
    unmount();
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });
});

describe("Escape", () => {
  it("calls onCancel", () => {
    const onCancel = vi.fn();
    render(
      <ConfirmSheet open question="Recompute every book?" onConfirm={vi.fn()} onCancel={onCancel} />,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});

describe("backdrop", () => {
  it("clicking the backdrop calls onCancel", () => {
    const onCancel = vi.fn();
    const { container } = render(
      <ConfirmSheet open question="Recompute every book?" onConfirm={vi.fn()} onCancel={onCancel} />,
    );
    const backdrop = container.querySelector(".confirm-sheet-backdrop");
    expect(backdrop).toBeTruthy();
    fireEvent.click(backdrop as Element);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("clicking inside the sheet does not call onCancel", () => {
    const onCancel = vi.fn();
    render(
      <ConfirmSheet open question="Recompute every book?" onConfirm={vi.fn()} onCancel={onCancel} />,
    );
    fireEvent.click(screen.getByRole("dialog"));
    expect(onCancel).not.toHaveBeenCalled();
  });
});

describe("confirm", () => {
  it("calls onConfirm when clicked", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmSheet open question="Recompute every book?" onConfirm={onConfirm} onCancel={vi.fn()} />,
    );
    fireEvent.click(screen.getByText("Confirm"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("uses a custom confirmLabel when given", () => {
    render(
      <ConfirmSheet
        open
        question="Recompute every book?"
        confirmLabel="Recompute"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText("Recompute")).toBeTruthy();
  });
});

describe("busy", () => {
  it("disables both buttons and shows the working label", () => {
    render(
      <ConfirmSheet open question="Recompute every book?" busy onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    const cancelButton = screen.getByText("Cancel") as HTMLButtonElement;
    const confirmButton = screen.getByText("Working…") as HTMLButtonElement;
    expect(cancelButton.disabled).toBe(true);
    expect(confirmButton.disabled).toBe(true);
  });
});
