/**
 * Label/tone/predicate helpers over the server-supplied job and selection unions in this module.
 *
 * `JobRunStatus`, `JobRunResultStatus` and `SelectionSeat["seated_by"]` all describe data this page
 * receives from the backend, not values this code constructs itself -- exactly the shape of union
 * `exitReasonLabel` (`@/api/paperdesk`) documents a real page-down failure for. Every helper below
 * used to close its `switch` with a throwing `assertNever`; these tests pin the replacement contract:
 * exhaustive at compile time (`tsc` still fails if a case is dropped), forgiving at runtime (an
 * unrecognised value degrades instead of throwing).
 */
import { describe, expect, it } from "vitest";

import {
  isTerminalJobStatus,
  jobRunResultStatusLabel,
  jobRunResultTone,
  jobStatusLabel,
  seatedByLabel,
  type JobRunResultStatus,
  type JobRunStatus,
  type SelectionSeat,
} from "@/api/competition";

describe("jobStatusLabel", () => {
  it("labels every status the backend can emit", () => {
    const statuses: JobRunStatus[] = ["queued", "running", "succeeded", "failed", "cancelled"];
    for (const status of statuses) {
      const label = jobStatusLabel(status);
      expect(label).toBeTruthy();
      expect(label).not.toBe(status);
    }
  });

  it("renders an unknown server value instead of throwing", () => {
    const fromAFutureBackend = "paused" as JobRunStatus;
    expect(() => jobStatusLabel(fromAFutureBackend)).not.toThrow();
    expect(jobStatusLabel(fromAFutureBackend)).toBe("paused");
  });
});

describe("isTerminalJobStatus", () => {
  it("keeps the poll alive for queued/running, ends it for everything else", () => {
    expect(isTerminalJobStatus("queued")).toBe(false);
    expect(isTerminalJobStatus("running")).toBe(false);
    expect(isTerminalJobStatus("succeeded")).toBe(true);
    expect(isTerminalJobStatus("failed")).toBe(true);
    expect(isTerminalJobStatus("cancelled")).toBe(true);
  });

  it("treats an unknown status as non-terminal rather than throwing", () => {
    // The conservative reading: keep polling rather than silently drop a live job's updates over a
    // status this build has not been taught to end on.
    const fromAFutureBackend = "paused" as JobRunStatus;
    expect(() => isTerminalJobStatus(fromAFutureBackend)).not.toThrow();
    expect(isTerminalJobStatus(fromAFutureBackend)).toBe(false);
  });
});

describe("jobRunResultStatusLabel", () => {
  it("labels both known outcomes", () => {
    expect(jobRunResultStatusLabel("ok")).toBe("OK");
    expect(jobRunResultStatusLabel("failed")).toBe("Failed");
  });

  it("renders an unknown server value instead of throwing", () => {
    const fromAFutureBackend = "skipped" as JobRunResultStatus;
    expect(() => jobRunResultStatusLabel(fromAFutureBackend)).not.toThrow();
    expect(jobRunResultStatusLabel(fromAFutureBackend)).toBe("skipped");
  });
});

describe("jobRunResultTone", () => {
  it("tones both known outcomes", () => {
    expect(jobRunResultTone("ok")).toBe("pos");
    expect(jobRunResultTone("failed")).toBe("neg");
  });

  it("degrades an unknown status to no colour instead of throwing", () => {
    // Neither "pos" nor "neg" is a safe guess about an outcome this function cannot classify.
    const fromAFutureBackend = "skipped" as JobRunResultStatus;
    expect(() => jobRunResultTone(fromAFutureBackend)).not.toThrow();
    expect(jobRunResultTone(fromAFutureBackend)).toBe("");
  });
});

describe("seatedByLabel", () => {
  it("labels every known seating route", () => {
    const routes: SelectionSeat["seated_by"][] = ["rule", "outside-competition", "owner-override"];
    for (const route of routes) {
      const label = seatedByLabel(route);
      expect(label).toBeTruthy();
      expect(label).not.toBe(route);
    }
  });

  it("renders an unknown server value instead of throwing", () => {
    const fromAFutureBackend = "manual-review" as SelectionSeat["seated_by"];
    expect(() => seatedByLabel(fromAFutureBackend)).not.toThrow();
    expect(seatedByLabel(fromAFutureBackend)).toBe("manual-review");
  });
});
