/**
 * `exitReasonLabel`'s two jobs: label the reasons this build knows, and never take the page down
 * over one it does not.
 *
 * Written after a live UAT pass turned `/paper-desk` into a permanently broken page. Allocation and
 * ladder cards emit `rebalance_trim` when a drift-band rebalance sells part of a sleeve, but only
 * over a window long enough to rebalance -- the default six-session inception never reached it. The
 * moment inception became user-settable, one click made a previously-unreachable value reachable, the
 * union did not contain it, the label function threw, and the route's `ErrorBoundary` replaced every
 * book and every figure with an error card. The inception override is persisted server-side, so it
 * crashed again on every reload, and the control that would have undone it was inside the subtree
 * that no longer rendered.
 */
import { describe, expect, it } from "vitest";

import { type DecisionAction, decisionActionLabel, type ExitReason, exitReasonLabel } from "@/api/paperdesk";

describe("exitReasonLabel", () => {
  it("labels every reason the backend can emit", () => {
    // The full set produced by app.tournament's runners, verified against the backend source:
    // rule | stop | target | time | open_at_end | rebalance_trim.
    const reasons: ExitReason[] = [
      "rule",
      "stop",
      "target",
      "time",
      "open_at_end",
      "rebalance_trim",
    ];
    for (const reason of reasons) {
      const label = exitReasonLabel(reason);
      expect(label).toBeTruthy();
      // A label, not the raw wire value echoed back.
      expect(label).not.toBe(reason);
    }
  });

  it("labels rebalance_trim, the one whose absence crashed the page", () => {
    expect(exitReasonLabel("rebalance_trim")).toBe("Rebalance trim");
  });

  it("renders an unknown server value instead of throwing", () => {
    // The regression guard. `exit_reason` is typed `str` on the backend, so a value this build has
    // never heard of can always arrive. Rendering it raw is a cosmetic problem; throwing here is an
    // unrecoverable page, because the throw escapes render into the route's ErrorBoundary.
    const fromAFutureBackend = "some_new_reason" as ExitReason;
    expect(() => exitReasonLabel(fromAFutureBackend)).not.toThrow();
    expect(exitReasonLabel(fromAFutureBackend)).toBe("some_new_reason");
  });
});

describe("decisionActionLabel", () => {
  it("labels every action the backend can emit", () => {
    const actions: DecisionAction[] = ["enter", "exit"];
    for (const action of actions) {
      const label = decisionActionLabel(action);
      expect(label).toBeTruthy();
      expect(label).not.toBe(action);
    }
  });

  it("renders an unknown server value instead of throwing", () => {
    // `Decision.action` is typed `str` on the backend, same as `exit_reason` above -- this function
    // used to throw via `assertNeverDecisionAction`, which would take the whole Paper Desk page down
    // over one unrecognised action the moment the backend added one.
    const fromAFutureBackend = "rebalance" as DecisionAction;
    expect(() => decisionActionLabel(fromAFutureBackend)).not.toThrow();
    expect(decisionActionLabel(fromAFutureBackend)).toBe("rebalance");
  });
});
