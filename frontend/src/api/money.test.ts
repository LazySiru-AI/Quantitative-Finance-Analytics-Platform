/**
 * The money-formatting contract.
 *
 * These are display functions, and the temptation is to treat them as too simple to test. They are
 * not: every figure this application shows a user passes through them, they are the last place a
 * precision loss could be introduced after the backend went to the trouble of sending decimal
 * *strings*, and one of the standing rules of this codebase — an absent figure renders `—`, never
 * `$0.00` — is enforced entirely at this layer.
 */
import { describe, expect, it } from "vitest";

import { compareMoneyDesc, subtractMoney, sumMoney } from "@/api/portfolio";
import { addMoney, formatMoney } from "@/api/tax";
import { formatMoneyOrDash } from "@/api/portfolio";

describe("formatMoney", () => {
  it("renders a decimal string with thousands separators", () => {
    expect(formatMoney("1234567.89")).toBe("$1,234,567.89");
  });

  it("keeps the sign on the outside of the currency symbol", () => {
    expect(formatMoney("-42.50")).toBe("-$42.50");
  });

  it("does not round: the server already did", () => {
    // A figure with more precision than cents arrives only if the backend sent it, and truncating
    // is the honest response — rounding here would silently disagree with the stored value.
    expect(formatMoney("10.999")).toBe("$10.99");
  });

  it("survives precision a double could not hold", () => {
    // 1234567.89012345 is why money crosses the wire as a string in the first place. Passing it
    // through Number() loses the tail; this must not.
    expect(formatMoney("1234567.89012345")).toBe("$1,234,567.89");
    expect(formatMoney("99999999999999999.99")).toBe("$99,999,999,999,999,999.99");
  });

  it("normalises the widths brokers actually emit", () => {
    expect(formatMoney("50")).toBe("$50.00");
    expect(formatMoney("50.5")).toBe("$50.50");
    expect(formatMoney("0")).toBe("$0.00");
  });

  it("never renders a negative zero", () => {
    // "-0.00" is arithmetically zero and reads as a loss. It arises whenever a delta is exactly
    // zero and the subtraction happened to carry a sign.
    expect(formatMoney("-0.00")).toBe("$0.00");
    expect(formatMoney("-0")).toBe("$0.00");
  });
});

describe("formatMoneyOrDash", () => {
  /**
   * The rule this function exists to make convenient, stated in `app.core.cash`'s docstring and
   * broken twice before it existed: a withheld figure is not zero. Cash that could not be derived,
   * an equity total with a missing half, a price that does not exist — rendering any of them as
   * `$0.00` states a number the application does not have.
   */
  it("renders an absent figure as an em dash, not zero", () => {
    expect(formatMoneyOrDash(null)).toBe("—");
    expect(formatMoneyOrDash(undefined)).toBe("—");
  });

  it("still renders a genuine zero as zero", () => {
    // The distinction only works in both directions. A real $0.00 balance is a fact.
    expect(formatMoneyOrDash("0.00")).toBe("$0.00");
  });
});

describe("addMoney", () => {
  it("adds exactly, in cents, not in floating point", () => {
    // 0.1 + 0.2 !== 0.3 in IEEE doubles. This is the whole reason the function exists.
    expect(addMoney("0.10", "0.20")).toBe("0.30");
  });

  it("handles mixed signs and carries", () => {
    expect(addMoney("-1500.75", "1500.75")).toBe("0.00");
    expect(addMoney("0.99", "0.01")).toBe("1.00");
    expect(addMoney("-2.88", "-3.60")).toBe("-6.48");
  });

  it("stays exact past double precision", () => {
    expect(addMoney("9007199254740993.01", "0.01")).toBe("9007199254740993.02");
  });

  it("round-trips through formatMoney", () => {
    expect(formatMoney(addMoney("1234.56", "8765.44"))).toBe("$10,000.00");
  });

  it("rounds each operand half-up to cents rather than truncating", () => {
    // `addMoney` used to truncate via its own `toCents`, unlike `sumMoney`/`multiplyMoneyByQuantity`
    // in `api/portfolio.ts`, which round half-up. A value with more precision than cents is real
    // precision the server sent (a cost basis like `4159.2533333333333`) -- truncating it instead of
    // rounding it is the same one-cent-drift hazard `sumMoney`'s own docstring documents.
    expect(addMoney("0.005", "0.00")).toBe("0.01");
    expect(addMoney("-0.005", "0.00")).toBe("-0.01");
    expect(addMoney("1.999", "0.00")).toBe("2.00");
  });
});

describe("subtractMoney", () => {
  it("subtracts exactly, in cents", () => {
    expect(subtractMoney("100.00", "42.50")).toBe("57.50");
    expect(subtractMoney("0.00", "0.00")).toBe("0.00");
  });

  it("rounds each operand half-up to cents rather than truncating", () => {
    // Same rounding-consistency fix as `addMoney` above: this function used to truncate its own
    // `toCents` parse, disagreeing by a cent with `sumMoney`/`multiplyMoneyByQuantity` in the same
    // module on a value with more than two fractional digits.
    expect(subtractMoney("1.005", "0.00")).toBe("1.01");
    expect(subtractMoney("0.00", "0.005")).toBe("-0.01");
  });
});

describe("compareMoneyDesc", () => {
  it("orders descending by cents", () => {
    expect(compareMoneyDesc("10.00", "5.00")).toBeLessThan(0);
    expect(compareMoneyDesc("5.00", "10.00")).toBeGreaterThan(0);
    expect(compareMoneyDesc("5.00", "5.00")).toBe(0);
  });

  it("rounds half-up to cents before comparing, rather than truncating", () => {
    // Truncation used to make "1.009" and "1.00" compare equal (both floor to `1.00`); rounded
    // half-up, "1.009" rounds to "1.01" and is correctly ordered ahead of "1.00".
    expect(compareMoneyDesc("1.009", "1.00")).toBeLessThan(0);
    expect(compareMoneyDesc("1.00", "1.009")).toBeGreaterThan(0);
  });
});

describe("sumMoney rounds once, not per term", () => {
  it("does not lose a fraction of a cent per term", () => {
    /**
     * The server sends per-account figures unrounded -- a real cost basis arrives as
     * `4159.2533333333333`. Truncating each term to cents before adding loses up to a cent per
     * term, and on a portfolio of a few dozen positions that put the by-tax-treatment subtotals two
     * cents below the headline they partition.
     */
    const thirds = Array.from({ length: 3 }, () => "0.333333333333");
    expect(sumMoney(thirds)).toBe("1.00");

    // Three terms that each truncate down: 0.99 each under the old rule, 3.00 under this one.
    expect(sumMoney(["0.999", "0.999", "0.999"])).toBe("3.00");
  });

  it("still sums exact cents exactly", () => {
    expect(sumMoney(["1205.00", "18311.00", "-500.25"])).toBe("19015.75");
    expect(sumMoney([])).toBe("0.00");
    expect(sumMoney(["-0.01", "0.01"])).toBe("0.00");
  });

  it("rounds ties away from zero, matching quantize_money", () => {
    expect(sumMoney(["0.005"])).toBe("0.01");
    expect(sumMoney(["-0.005"])).toBe("-0.01");
  });
});
