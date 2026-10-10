/**
 * Label/predicate helpers over `LoopState`/`LoopPhase`, the two server-supplied unions this module's
 * poll loop switches on. Same contract as `competition.test.ts`'s helpers and for the same reason:
 * these used to close their `switch` with a throwing `assertNever`, which would take the loop panel
 * down the moment the backend reported a state or phase this build had not been updated for.
 */
import { describe, expect, it } from "vitest";

import { isLoopActive, loopPhaseLabel, loopStateLabel, type LoopPhase, type LoopState } from "@/api/evolution";

describe("loopStateLabel", () => {
  it("labels every state the backend can emit", () => {
    const states: LoopState[] = ["idle", "running", "stopping", "stopped", "failed"];
    for (const state of states) {
      const label = loopStateLabel(state);
      expect(label).toBeTruthy();
      expect(label).not.toBe(state);
    }
  });

  it("renders an unknown server value instead of throwing", () => {
    const fromAFutureBackend = "paused" as LoopState;
    expect(() => loopStateLabel(fromAFutureBackend)).not.toThrow();
    expect(loopStateLabel(fromAFutureBackend)).toBe("paused");
  });
});

describe("loopPhaseLabel", () => {
  it("labels every phase the backend can emit", () => {
    const phases: LoopPhase[] = ["idle", "proposing", "running", "scoring", "promoting", "cooldown"];
    for (const phase of phases) {
      const label = loopPhaseLabel(phase);
      expect(label).toBeTruthy();
      expect(label).not.toBe(phase);
    }
  });

  it("renders an unknown server value instead of throwing", () => {
    const fromAFutureBackend = "archiving" as LoopPhase;
    expect(() => loopPhaseLabel(fromAFutureBackend)).not.toThrow();
    expect(loopPhaseLabel(fromAFutureBackend)).toBe("archiving");
  });
});

describe("isLoopActive", () => {
  it("keeps the poll alive for running/stopping, ends it for everything else", () => {
    expect(isLoopActive("running")).toBe(true);
    expect(isLoopActive("stopping")).toBe(true);
    expect(isLoopActive("idle")).toBe(false);
    expect(isLoopActive("stopped")).toBe(false);
    expect(isLoopActive("failed")).toBe(false);
  });

  it("treats an unknown state as active rather than throwing", () => {
    // Mirrors `isTerminalJobStatus`'s own conservative choice in `api/competition.ts`: keep polling
    // rather than silently drop a live loop's updates over a state this build has not been taught to
    // end on.
    const fromAFutureBackend = "paused" as LoopState;
    expect(() => isLoopActive(fromAFutureBackend)).not.toThrow();
    expect(isLoopActive(fromAFutureBackend)).toBe(true);
  });
});
