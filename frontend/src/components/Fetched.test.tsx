/**
 * `<Fetched>`: renders exactly one of loading/error/empty/ready for a `useFetch`-shaped state, mirroring
 * the four-way branch every migrated page used to write out by hand.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import Fetched from "@/components/Fetched";

afterEach(cleanup);

describe("phase gating", () => {
  it("renders the loading slot while loading", () => {
    render(
      <Fetched state={{ phase: "loading", data: null }} loading={<p>Loading…</p>} error="Failed">
        {() => <p>Ready</p>}
      </Fetched>,
    );
    expect(screen.getByText("Loading…")).toBeTruthy();
    expect(screen.queryByText("Ready")).toBeNull();
  });

  it("renders a static error node", () => {
    render(
      <Fetched
        state={{ phase: "error", data: null, error: "boom" }}
        loading="Loading"
        error={<p>Something broke</p>}
      >
        {() => <p>Ready</p>}
      </Fetched>,
    );
    expect(screen.getByText("Something broke")).toBeTruthy();
  });

  it("passes the state's error message to a function error slot", () => {
    render(
      <Fetched
        state={{ phase: "error", data: null, error: "server said no" }}
        loading="Loading"
        error={(message) => <p>Failed: {message}</p>}
      >
        {() => <p>Ready</p>}
      </Fetched>,
    );
    expect(screen.getByText("Failed: server said no")).toBeTruthy();
  });

  it("passes null to a function error slot when the state carries no error message", () => {
    render(
      <Fetched state={{ phase: "error", data: null }} loading="Loading" error={(message) => <p>{String(message)}</p>}>
        {() => <p>Ready</p>}
      </Fetched>,
    );
    expect(screen.getByText("null")).toBeTruthy();
  });

  it("renders children with the loaded data when there is no empty check", () => {
    render(
      <Fetched state={{ phase: "loaded", data: { name: "AAPL" } }} loading="Loading" error="Failed">
        {(data) => <p>{data.name}</p>}
      </Fetched>,
    );
    expect(screen.getByText("AAPL")).toBeTruthy();
  });

  it("renders nothing for a loaded phase with null data", () => {
    const { container } = render(
      <Fetched state={{ phase: "loaded", data: null }} loading="Loading" error="Failed">
        {() => <p>Ready</p>}
      </Fetched>,
    );
    expect(container.textContent).toBe("");
  });
});

describe("empty handling", () => {
  it("renders the empty slot when isEmpty(data) is true", () => {
    render(
      <Fetched
        state={{ phase: "loaded", data: { items: [] as string[] } }}
        loading="Loading"
        error="Failed"
        isEmpty={(d) => d.items.length === 0}
        empty={<p>Nothing here</p>}
      >
        {(d) => <p>{d.items.length} items</p>}
      </Fetched>,
    );
    expect(screen.getByText("Nothing here")).toBeTruthy();
  });

  it("renders children when isEmpty(data) is false", () => {
    render(
      <Fetched
        state={{ phase: "loaded", data: { items: ["a", "b"] } }}
        loading="Loading"
        error="Failed"
        isEmpty={(d) => d.items.length === 0}
        empty={<p>Nothing here</p>}
      >
        {(d) => <p>{d.items.length} items</p>}
      </Fetched>,
    );
    expect(screen.getByText("2 items")).toBeTruthy();
  });

  it("passes data to a function empty slot", () => {
    render(
      <Fetched
        state={{ phase: "loaded", data: { label: "Q3 filers", items: [] as string[] } }}
        loading="Loading"
        error="Failed"
        isEmpty={(d) => d.items.length === 0}
        empty={(d) => <p>Nothing for {d.label}</p>}
      >
        {(d) => <p>{d.items.length} items</p>}
      </Fetched>,
    );
    expect(screen.getByText("Nothing for Q3 filers")).toBeTruthy();
  });

  it("ignores isEmpty when no empty slot is supplied", () => {
    render(
      <Fetched
        state={{ phase: "loaded", data: { items: [] as string[] } }}
        loading="Loading"
        error="Failed"
        isEmpty={(d) => d.items.length === 0}
      >
        {(d) => <p>{d.items.length} items</p>}
      </Fetched>,
    );
    expect(screen.getByText("0 items")).toBeTruthy();
  });
});
