/**
 * `tableSort.tsx`: the sort-header/filter-bar primitives shared by both positions tables on the
 * Account page.
 *
 * Covers, per the extraction brief: clicking the active header flips direction; clicking a
 * different header switches key and starts at THAT key's own default direction (mirroring
 * `nextSortState` in `frontend/src/pages/Institutions.tsx`); `aria-sort` reflects state on the
 * active header and reads "none" everywhere else; `sortRows` returns a new array without mutating
 * its input and is stable across ties; `FilterBar` calls its change handlers and renders the
 * shown/total note.
 */
import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  FilterBar,
  SortHeader,
  sortRows,
  TableCaption,
  useTableSort,
  type SortState,
} from "@/components/tableSort";

type Key = "name" | "value";

const DEFAULT_DIRS: Record<Key, "asc" | "desc"> = { name: "asc", value: "desc" };

describe("useTableSort", () => {
  it("starts at the initial key's own default direction", () => {
    const { result } = renderHook(() => useTableSort<Key>("name", DEFAULT_DIRS));
    expect(result.current.sort).toEqual({ key: "name", dir: "asc" });
  });

  it("flips direction when the active column is clicked again", () => {
    const { result } = renderHook(() => useTableSort<Key>("name", DEFAULT_DIRS));
    act(() => result.current.toggle("name"));
    expect(result.current.sort).toEqual({ key: "name", dir: "desc" });
    act(() => result.current.toggle("name"));
    expect(result.current.sort).toEqual({ key: "name", dir: "asc" });
  });

  it("switches key and uses that key's own default direction when a different column is clicked", () => {
    const { result } = renderHook(() => useTableSort<Key>("name", DEFAULT_DIRS));
    act(() => result.current.toggle("value"));
    // "value"'s own default is "desc", not a copy of whatever "name" was showing.
    expect(result.current.sort).toEqual({ key: "value", dir: "desc" });
  });

  it("keeps toggle referentially stable across renders", () => {
    const { result, rerender } = renderHook(() => useTableSort<Key>("name", DEFAULT_DIRS));
    const first = result.current.toggle;
    rerender();
    expect(result.current.toggle).toBe(first);
  });
});

describe("SortHeader", () => {
  function Table({ sort, onSort }: { sort: SortState<Key>; onSort: (k: Key) => void }) {
    return (
      <table>
        <thead>
          <tr>
            <SortHeader label="Name" sortKey="name" sort={sort} onSort={onSort} />
            <SortHeader label="Value" sortKey="value" sort={sort} onSort={onSort} numeric title="Value" />
          </tr>
        </thead>
      </table>
    );
  }

  it("marks the active header's aria-sort and leaves the others 'none'", () => {
    render(<Table sort={{ key: "value", dir: "desc" }} onSort={vi.fn()} />);
    expect(screen.getByRole("columnheader", { name: /Name/ }).getAttribute("aria-sort")).toBe("none");
    expect(screen.getByRole("columnheader", { name: /Value/ }).getAttribute("aria-sort")).toBe(
      "descending",
    );
  });

  it("reflects ascending state too", () => {
    render(<Table sort={{ key: "name", dir: "asc" }} onSort={vi.fn()} />);
    expect(screen.getByRole("columnheader", { name: /Name/ }).getAttribute("aria-sort")).toBe(
      "ascending",
    );
  });

  it("calls onSort with the clicked column's key", () => {
    const onSort = vi.fn();
    render(<Table sort={{ key: "name", dir: "asc" }} onSort={onSort} />);
    fireEvent.click(screen.getByRole("button", { name: /Value/ }));
    expect(onSort).toHaveBeenCalledWith("value");
  });

  it("applies the numeric column class and the title attribute", () => {
    render(<Table sort={{ key: "name", dir: "asc" }} onSort={vi.fn()} />);
    const valueHeader = screen.getByRole("columnheader", { name: /Value/ });
    expect(valueHeader.className).toBe("num");
    expect(valueHeader.getAttribute("title")).toBe("Value");
  });
});

describe("sortRows", () => {
  type Row = { id: string; n: number };
  const byN: Record<"n", (a: Row, b: Row) => number> = { n: (a, b) => a.n - b.n };

  it("returns a new array and leaves the input untouched", () => {
    const rows: Row[] = [{ id: "a", n: 2 }, { id: "b", n: 1 }];
    const sorted = sortRows(rows, { key: "n", dir: "asc" }, byN);
    expect(sorted).not.toBe(rows);
    expect(rows.map((r) => r.id)).toEqual(["a", "b"]);
    expect(sorted.map((r) => r.id)).toEqual(["b", "a"]);
  });

  it("sorts descending when asked", () => {
    const rows: Row[] = [{ id: "a", n: 1 }, { id: "b", n: 2 }];
    const sorted = sortRows(rows, { key: "n", dir: "desc" }, byN);
    expect(sorted.map((r) => r.id)).toEqual(["b", "a"]);
  });

  it("is stable across ties -- equal rows keep their input order", () => {
    const rows: Row[] = [
      { id: "first", n: 1 },
      { id: "second", n: 1 },
      { id: "third", n: 1 },
    ];
    const sorted = sortRows(rows, { key: "n", dir: "asc" }, byN);
    expect(sorted.map((r) => r.id)).toEqual(["first", "second", "third"]);
    // Re-sorting again must not reshuffle the tie.
    const sortedAgain = sortRows(sorted, { key: "n", dir: "asc" }, byN);
    expect(sortedAgain.map((r) => r.id)).toEqual(["first", "second", "third"]);
  });
});

describe("TableCaption (EXP-15)", () => {
  it("renders a <caption> with the given text", () => {
    render(
      <table>
        <TableCaption caption="Positions by instrument, 3 rows, across all accounts" />
      </table>,
    );
    const caption = screen.getByText("Positions by instrument, 3 rows, across all accounts");
    expect(caption.tagName).toBe("CAPTION");
  });

  it("is visually-hidden by default", () => {
    render(
      <table>
        <TableCaption caption="Hidden caption" />
      </table>,
    );
    expect(screen.getByText("Hidden caption").className).toBe("visually-hidden");
  });

  it("renders visibly (not visually-hidden) when captionVisible is true", () => {
    render(
      <table>
        <TableCaption caption="Shown caption" captionVisible />
      </table>,
    );
    const caption = screen.getByText("Shown caption");
    expect(caption.className).not.toContain("visually-hidden");
  });
});

describe("FilterBar", () => {
  const choices = [
    { value: "SEMI", label: "Semiconductors" },
    { value: "CRYPTO", label: "Crypto" },
  ];

  it("calls onQueryChange as the search field is typed into", () => {
    const onQueryChange = vi.fn();
    render(
      <FilterBar
        query=""
        onQueryChange={onQueryChange}
        queryPlaceholder="Filter symbol"
        shown={3}
        total={10}
      />,
    );
    fireEvent.change(screen.getByRole("searchbox", { name: "Filter symbol" }), {
      target: { value: "NVDA" },
    });
    expect(onQueryChange).toHaveBeenCalledWith("NVDA");
  });

  it("renders the shown-of-total note", () => {
    render(
      <FilterBar
        query=""
        onQueryChange={vi.fn()}
        queryPlaceholder="Filter symbol"
        shown={3}
        total={10}
      />,
    );
    expect(screen.getByText("Showing 3 of 10")).toBeTruthy();
  });

  it("renders the choice select with an all option and calls onChoiceChange", () => {
    const onChoiceChange = vi.fn();
    render(
      <FilterBar
        query=""
        onQueryChange={vi.fn()}
        queryPlaceholder="Filter symbol"
        choices={choices}
        choice=""
        onChoiceChange={onChoiceChange}
        choiceAllLabel="All sectors"
        shown={10}
        total={10}
      />,
    );
    expect(screen.getByText("All sectors")).toBeTruthy();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "SEMI" } });
    expect(onChoiceChange).toHaveBeenCalledWith("SEMI");
  });

  it("gives the choice select an accessible name from choiceLabel (A11Y-05)", () => {
    render(
      <FilterBar
        query=""
        onQueryChange={vi.fn()}
        queryPlaceholder="Filter symbol"
        choices={choices}
        choice=""
        onChoiceChange={vi.fn()}
        choiceAllLabel="All sectors"
        choiceLabel="Filter by sector"
        shown={10}
        total={10}
      />,
    );
    expect(screen.getByRole("combobox", { name: "Filter by sector" })).toBeTruthy();
  });

  it("falls back to choiceAllLabel for the select's accessible name when choiceLabel is omitted", () => {
    render(
      <FilterBar
        query=""
        onQueryChange={vi.fn()}
        queryPlaceholder="Filter symbol"
        choices={choices}
        choice=""
        onChoiceChange={vi.fn()}
        choiceAllLabel="All sectors"
        shown={10}
        total={10}
      />,
    );
    expect(screen.getByRole("combobox", { name: "All sectors" })).toBeTruthy();
  });

  it("omits the select entirely when no choices are supplied", () => {
    render(
      <FilterBar
        query=""
        onQueryChange={vi.fn()}
        queryPlaceholder="Filter symbol"
        shown={1}
        total={1}
      />,
    );
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("clears both query and choice when the clear button is clicked", () => {
    const onQueryChange = vi.fn();
    const onChoiceChange = vi.fn();
    render(
      <FilterBar
        query="NVDA"
        onQueryChange={onQueryChange}
        queryPlaceholder="Filter symbol"
        choices={choices}
        choice="SEMI"
        onChoiceChange={onChoiceChange}
        choiceAllLabel="All sectors"
        shown={1}
        total={10}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(onQueryChange).toHaveBeenCalledWith("");
    expect(onChoiceChange).toHaveBeenCalledWith("");
  });
});
