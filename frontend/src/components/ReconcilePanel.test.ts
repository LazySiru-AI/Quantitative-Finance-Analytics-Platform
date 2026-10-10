/**
 * `ReconcilePanel`'s `statusLabel`, over `ReconcileStatus` -- data this panel receives from `POST
 * /api/tax/reconcile`, not a value it constructs itself. This panel renders inside the Tax page
 * alongside 8949, disposals and wash sales, so a throwing default here would take all of it down
 * over one unrecognised status in one reconciliation row -- exactly the failure `exitReasonLabel`'s
 * docstring (`@/api/paperdesk`) records happening for real on Paper Desk. `statusLabel` used to throw
 * via a private `assertNever`; it is exported here specifically so this regression can be pinned
 * without mounting the whole component.
 */
import { describe, expect, it } from "vitest";

import { statusLabel } from "@/components/ReconcilePanel";
import type { ReconcileStatus } from "@/api/tax";

describe("statusLabel", () => {
  it("labels every status the backend can emit", () => {
    const statuses: ReconcileStatus[] = [
      "matched",
      "amount_differs",
      "missing_from_engine",
      "missing_from_1099b",
    ];
    for (const status of statuses) {
      const label = statusLabel(status);
      expect(label).toBeTruthy();
      expect(label).not.toBe(status);
    }
  });

  it("renders an unknown server value instead of throwing", () => {
    const fromAFutureBackend = "basis_disputed" as ReconcileStatus;
    expect(() => statusLabel(fromAFutureBackend)).not.toThrow();
    expect(statusLabel(fromAFutureBackend)).toBe("basis_disputed");
  });
});
