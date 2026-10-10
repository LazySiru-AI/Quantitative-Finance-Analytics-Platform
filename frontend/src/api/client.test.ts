/**
 * `DecimalString` parsing contract shared by the display and ordering helpers across the app --
 * `expandScientific`, `parseDecimalString`, `compareDecimalStrings`.
 *
 * The bug these exist to close: Python's `Decimal` serialises a small magnitude in scientific
 * notation, and every hand-rolled parser downstream of the wire (there used to be five separate
 * copies -- see the docstrings in `client.ts`) split on `"."` and never looked for an exponent.
 * Fed ARK's real Moog Inc weight, `"6.5385669523052923658747931E-7"`, the old
 * `compareDecimalStrings` in `frontend/src/pages/Institutions.tsx` built
 * `BigInt("65385669523052923658747931E-7000")` -- the exponent text pasted straight onto the
 * zero-padded fraction -- which throws `Cannot convert ... to a BigInt` and took down the whole
 * page behind an error boundary for four of the twenty-two tracked funds. The other four call
 * sites did not throw; they silently truncated (`formatShares("1E+3")` rendered `"1"` instead of
 * `"1000"`), which is the more dangerous half of the defect.
 */
import { describe, expect, it } from "vitest";

import {
  centsToDecimalString,
  compareDecimalStrings,
  decimalStringToCents,
  expandScientific,
  parseDecimalString,
} from "@/api/client";
import { formatSharesPctChange, formatShares, formatWeight } from "@/api/institutions";

describe("expandScientific", () => {
  it("expands the real value that crashed the Institutions page (ARK / Moog Inc weight_delta)", () => {
    expect(expandScientific("6.5385669523052923658747931E-7")).toBe(
      "0.00000065385669523052923658747931",
    );
  });

  it("expands a positive exponent", () => {
    expect(expandScientific("1E+3")).toBe("1000");
    expect(expandScientific("1.5E+2")).toBe("150");
  });

  it("expands a negative exponent that needs leading zeros", () => {
    expect(expandScientific("1E-7")).toBe("0.0000001");
  });

  it("keeps a leading sign", () => {
    expect(expandScientific("-2.5E-3")).toBe("-0.0025");
  });

  it("accepts lowercase e as well as uppercase E", () => {
    expect(expandScientific("1e-7")).toBe("0.0000001");
    expect(expandScientific("-2.5e-3")).toBe("-0.0025");
  });

  it("passes a plain decimal through completely unchanged -- the case that must not regress", () => {
    // Every fund whose weights never cross into scientific notation (BRK, SCION, QQQ, and the vast
    // majority of every other fund's rows) must render exactly as before this fix.
    expect(expandScientific("1234.56")).toBe("1234.56");
    expect(expandScientific("0")).toBe("0");
    expect(expandScientific("-0.01")).toBe("-0.01");
  });

  it("never produces a signed zero", () => {
    expect(expandScientific("-0E+5")).toBe("0");
    expect(expandScientific("0E+5")).toBe("0");
  });

  it("handles an exponent large enough to matter without hanging", () => {
    const result = expandScientific("1.23E+50");
    expect(result.startsWith("123")).toBe(true);
    expect(result.endsWith("0")).toBe(true);
    expect(result).not.toContain(".");
    expect(result).not.toContain("E");

    const small = expandScientific("1E-50");
    expect(small.startsWith("0.")).toBe(true);
    expect(small.endsWith("1")).toBe(true);
    expect(small.length).toBe(52); // "0." + 49 zeros + "1"
  });
});

describe("parseDecimalString", () => {
  it("splits a plain decimal into sign/whole/fraction", () => {
    expect(parseDecimalString("1234.56")).toEqual({ negative: false, wholeRaw: "1234", fracRaw: "56" });
    expect(parseDecimalString("-0.01")).toEqual({ negative: true, wholeRaw: "0", fracRaw: "01" });
  });

  it("splits a scientific-notation value only after expanding it", () => {
    expect(parseDecimalString("1E+3")).toEqual({ negative: false, wholeRaw: "1000", fracRaw: "" });
    expect(parseDecimalString("1E-7")).toEqual({
      negative: false,
      wholeRaw: "0",
      fracRaw: "0000001",
    });
  });
});

describe("compareDecimalStrings", () => {
  it("does not throw on the real value that crashed the Institutions page", () => {
    expect(() => compareDecimalStrings("6.5385669523052923658747931E-7", "0")).not.toThrow();
  });

  it("orders the real crashing value correctly against plain decimals", () => {
    const tiny = "6.5385669523052923658747931E-7"; // ~0.00000065
    expect(compareDecimalStrings(tiny, "0")).toBe(1);
    expect(compareDecimalStrings(tiny, "1")).toBe(-1);
    expect(compareDecimalStrings("0", tiny)).toBe(-1);
  });

  it("orders scientific notation against scientific notation", () => {
    expect(compareDecimalStrings("1E+3", "1E+2")).toBe(1);
    expect(compareDecimalStrings("1E-7", "1E-6")).toBe(-1);
  });

  it("keeps ordering plain decimals unchanged from before this fix", () => {
    expect(compareDecimalStrings("100", "99")).toBe(1);
    expect(compareDecimalStrings("-5", "5")).toBe(-1);
    expect(compareDecimalStrings("1.50", "1.5")).toBe(0);
  });
});

describe("the real crashing value through the actual page-facing helpers", () => {
  it("compareDecimalStrings: never throws and orders it correctly", () => {
    const weightDelta = "6.5385669523052923658747931E-7";
    expect(() => compareDecimalStrings(weightDelta, "0.01")).not.toThrow();
    // 0.00000065... is smaller than 0.01.
    expect(compareDecimalStrings(weightDelta, "0.01")).toBe(-1);
  });

  it("formatSharesPctChange: renders the tiny value as the under-threshold marker, not a crash", () => {
    const weightDelta = "6.5385669523052923658747931E-7";
    expect(() => formatSharesPctChange(weightDelta)).not.toThrow();
    expect(formatSharesPctChange(weightDelta)).toBe("<0.01%");
  });

  it("formatWeight: renders the tiny value without throwing", () => {
    const weightDelta = "6.5385669523052923658747931E-7";
    expect(() => formatWeight(weightDelta)).not.toThrow();
    expect(formatWeight(weightDelta)).toBe("<0.01%");
  });

  it("formatShares: expands scientific notation instead of silently truncating", () => {
    // This is the more dangerous half of the defect -- these four call sites never threw, they
    // just quietly rendered the wrong number.
    expect(formatShares("1E+3")).toBe("1,000");
    expect(formatShares("1.5E+2")).toBe("150");
  });
});

describe("decimalStringToCents / centsToDecimalString", () => {
  it("round-trips a value already at cents precision unchanged", () => {
    expect(centsToDecimalString(decimalStringToCents("42.50"))).toBe("42.50");
    expect(centsToDecimalString(decimalStringToCents("0.00"))).toBe("0.00");
    expect(centsToDecimalString(decimalStringToCents("-7.05"))).toBe("-7.05");
  });

  it("rounds half-up (ties away from zero), matching quantize_money -- never truncates", () => {
    // The whole reason this pair exists: `subtractMoney`/`compareMoneyDesc` (api/portfolio.ts) and
    // `addMoney` (api/tax.ts) used to truncate a value with more than two fractional digits instead
    // of rounding it, disagreeing by a cent with `sumMoney`, which always rounded half-up.
    expect(decimalStringToCents("0.005")).toBe(1n);
    expect(decimalStringToCents("-0.005")).toBe(-1n);
    expect(decimalStringToCents("1.999")).toBe(200n);
    expect(decimalStringToCents("4159.2533333333333")).toBe(415925n);
  });

  it("a negative value that rounds to zero cents renders as an unsigned zero", () => {
    // "-0.001" rounds half-up to zero cents; a signed "-0.00" would read as a loss that does not
    // exist, the same rule `formatMoney`'s own "never render a negative zero" test pins.
    expect(centsToDecimalString(decimalStringToCents("-0.001"))).toBe("0.00");
  });
});
