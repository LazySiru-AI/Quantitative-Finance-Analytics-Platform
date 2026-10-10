/**
 * `formatMoney`/`formatMoneyOrDash`: the digit-shifting rule and the null-vs-zero distinction.
 *
 * This is the merge point for what used to be three byte-identical `formatMoney` copies
 * (`api/personas.ts`, `api/tax.ts`, `api/tradingagents.ts`) plus `api/portfolio.ts`'s
 * `formatMoneyOrDash` built on top of one of them. The cases below are drawn from what those
 * copies' own docstrings called out as easy to get wrong: thousands separators, negative-vs-zero
 * (`"-0.00"` must not render as `-$0.00`), and `null`/`undefined` must never collapse to `$0.00`.
 */
import { describe, expect, it } from "vitest";

import { formatMoney, formatMoneyOrDash } from "@/format/money";

describe("formatMoney", () => {
  it("renders a plain whole-dollar amount with cents", () => {
    expect(formatMoney("5")).toBe("$5.00");
  });

  it("preserves fractional digits up to two places, padding a single decimal digit", () => {
    expect(formatMoney("12.5")).toBe("$12.50");
    expect(formatMoney("12.34")).toBe("$12.34");
  });

  it("groups the whole part with thousands separators", () => {
    expect(formatMoney("1234567.89")).toBe("$1,234,567.89");
  });

  it("renders a negative amount with a leading minus before the dollar sign", () => {
    expect(formatMoney("-42.10")).toBe("-$42.10");
  });

  it("never renders a signed zero as negative", () => {
    expect(formatMoney("-0")).toBe("$0.00");
    expect(formatMoney("-0.00")).toBe("$0.00");
  });

  it("handles scientific notation via the shared parser", () => {
    expect(formatMoney("1E2")).toBe("$100.00");
  });
});

describe("formatMoneyOrDash", () => {
  it("delegates to formatMoney for a present value", () => {
    expect(formatMoneyOrDash("10.5")).toBe("$10.50");
  });

  it("renders an em dash for null, never $0.00", () => {
    expect(formatMoneyOrDash(null)).toBe("—");
  });

  it("renders an em dash for undefined, never $0.00", () => {
    expect(formatMoneyOrDash(undefined)).toBe("—");
  });
});
