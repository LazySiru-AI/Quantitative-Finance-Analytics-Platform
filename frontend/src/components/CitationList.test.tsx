/**
 * CitationList: an empty array renders nothing, citations are always visible (never behind a
 * disclosure), and supplying `onSelect` turns each citation into a clickable button wired to its
 * note_id.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import CitationList from "@/components/CitationList";

afterEach(cleanup);

describe("empty citations", () => {
  it("renders nothing for an empty array", () => {
    const { container } = render(<CitationList citations={[]} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("without onSelect", () => {
  it("renders each citation as plain, always-visible text", () => {
    render(<CitationList citations={["note-1", "note-2"]} data-testid="citations" />);
    const list = screen.getByTestId("citations");
    expect(list.textContent).toContain("note-1");
    expect(list.textContent).toContain("note-2");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("exposes an accessible label on the list", () => {
    render(<CitationList citations={["note-1"]} />);
    expect(screen.getByRole("list", { name: "Citations" })).toBeTruthy();
  });
});

describe("with onSelect", () => {
  it("renders each citation as a button", () => {
    render(<CitationList citations={["note-1", "note-2"]} onSelect={() => {}} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(2);
    expect(buttons[0]?.textContent).toBe("note-1");
    expect(buttons[1]?.textContent).toBe("note-2");
  });

  it("calls onSelect with the clicked note_id", () => {
    const onSelect = vi.fn();
    render(<CitationList citations={["note-1", "note-2"]} onSelect={onSelect} />);
    fireEvent.click(screen.getByText("note-2"));
    expect(onSelect).toHaveBeenCalledWith("note-2");
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("uses type=button so it never submits a surrounding form", () => {
    render(<CitationList citations={["note-1"]} onSelect={() => {}} />);
    expect(screen.getByRole("button").getAttribute("type")).toBe("button");
  });
});
