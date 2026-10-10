/**
 * PersonaProfileDiff: `changes[]` group by `kind` (added/removed/recited), each item tagged with its
 * `section`; the `added`/`removed`/`recited` counts summarise the diff; an empty `changes` array
 * renders a plain "no changes" note instead of empty section groups; the version selectors and
 * Compare button wire through to the caller's handlers.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PersonaProfileDiff, { type ProfileDiffState } from "@/components/PersonaProfileDiff";
import type { ClaimChange, ProfileDiff } from "@/api/personas";

afterEach(cleanup);

function change(overrides: Partial<ClaimChange> = {}): ClaimChange {
  return {
    kind: "added",
    section: "belief",
    text: "Now expects two rate cuts this year.",
    citations: ["note-9"],
    ...overrides,
  };
}

function diff(overrides: Partial<ProfileDiff> = {}): ProfileDiff {
  return {
    persona: "creator-a",
    from_version: 2,
    to_version: 3,
    changes: [],
    added: 0,
    removed: 0,
    recited: 0,
    ...overrides,
  };
}

function renderDiff(
  state: ProfileDiffState,
  overrides: Partial<{
    versions: number[];
    from: number | null;
    to: number | null;
    onFromChange: (v: number) => void;
    onToChange: (v: number) => void;
    onCompare: () => void;
  }> = {},
) {
  const onFromChange = overrides.onFromChange ?? vi.fn();
  const onToChange = overrides.onToChange ?? vi.fn();
  const onCompare = overrides.onCompare ?? vi.fn();
  render(
    <PersonaProfileDiff
      state={state}
      versions={overrides.versions ?? [1, 2, 3]}
      from={overrides.from ?? null}
      to={overrides.to ?? null}
      onFromChange={onFromChange}
      onToChange={onToChange}
      onCompare={onCompare}
    />,
  );
  return { onFromChange, onToChange, onCompare };
}

describe("version selectors", () => {
  it("calls onFromChange/onToChange with the selected version as a number", () => {
    const { onFromChange, onToChange } = renderDiff({ phase: "idle" });
    fireEvent.change(screen.getByLabelText("From version"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("To version"), { target: { value: "3" } });
    expect(onFromChange).toHaveBeenCalledWith(1);
    expect(onToChange).toHaveBeenCalledWith(3);
  });

  it("disables Compare until both versions are chosen", () => {
    renderDiff({ phase: "idle" }, { from: null, to: null });
    expect((screen.getByText("Compare") as HTMLButtonElement).disabled).toBe(true);
  });

  it("enables Compare and fires onCompare once both are chosen", () => {
    const { onCompare } = renderDiff({ phase: "idle" }, { from: 1, to: 3 });
    const button = screen.getByText("Compare") as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    expect(onCompare).toHaveBeenCalledTimes(1);
  });
});

describe("fetch states", () => {
  it("shows the loading placeholder", () => {
    renderDiff({ phase: "loading" });
    expect(screen.getByText("Loading diff…")).toBeTruthy();
  });

  it("shows the error message as an alert", () => {
    renderDiff({ phase: "error", message: "unknown persona" });
    expect(screen.getByRole("alert").textContent).toContain("unknown persona");
  });
});

describe("loaded: empty changes", () => {
  it("renders a plain note instead of empty section groups", () => {
    renderDiff({ phase: "loaded", diff: diff() });
    expect(screen.getByText("No changes between these versions")).toBeTruthy();
  });
});

describe("loaded: grouped changes", () => {
  it("shows the added/removed/recited counts", () => {
    renderDiff({
      phase: "loaded",
      diff: diff({
        changes: [change()],
        added: 1,
        removed: 2,
        recited: 3,
      }),
    });
    expect(screen.getByText("1 added, 2 removed, 3 recited")).toBeTruthy();
  });

  it("groups changes under their kind and tags each with its section", () => {
    renderDiff({
      phase: "loaded",
      diff: diff({
        changes: [
          change({ kind: "added", section: "belief", text: "belief-added-text" }),
          change({ kind: "removed", section: "playbook", text: "playbook-removed-text" }),
          change({ kind: "recited", section: "methodology", text: "methodology-recited-text" }),
        ],
        added: 1,
        removed: 1,
        recited: 1,
      }),
    });

    expect(screen.getByText("Added")).toBeTruthy();
    expect(screen.getByText("Removed")).toBeTruthy();
    expect(screen.getByText("Recited")).toBeTruthy();

    expect(screen.getByText("belief-added-text")).toBeTruthy();
    expect(screen.getByText("playbook-removed-text")).toBeTruthy();
    expect(screen.getByText("methodology-recited-text")).toBeTruthy();

    expect(screen.getByText("Belief")).toBeTruthy();
    expect(screen.getByText("Playbook")).toBeTruthy();
    expect(screen.getByText("Methodology")).toBeTruthy();
  });

  it("renders each change's citations verbatim", () => {
    renderDiff({
      phase: "loaded",
      diff: diff({ changes: [change({ citations: ["note-a", "note-b"] })], added: 1 }),
    });
    expect(screen.getByText("note-a")).toBeTruthy();
    expect(screen.getByText("note-b")).toBeTruthy();
  });

  it("does not render a group heading for a kind with no changes", () => {
    renderDiff({
      phase: "loaded",
      diff: diff({ changes: [change({ kind: "added" })], added: 1 }),
    });
    expect(screen.getByText("Added")).toBeTruthy();
    expect(screen.queryByText("Removed")).toBeNull();
    expect(screen.queryByText("Recited")).toBeNull();
  });
});
