/**
 * The institutions client's parsing contract and its display helpers.
 *
 * Matches the idiom in `washsales.test.ts` / `money.test.ts`: exercise the actual exported shape
 * rather than trusting the type annotations alone, and stub `fetch` directly since this file tests
 * the API layer itself, not a page consuming it.
 */
import { describe, expect, it, vi } from "vitest";

import {
  formatShares,
  formatSharesPctChange,
  formatSignedShares,
  formatWeight,
  institutionsApi,
  SOURCE_NOTE,
  type FundRef,
  type Holding,
  type HoldingChange,
  type PortfolioDelta,
  type Snapshot,
} from "@/api/institutions";

function stubFetchOnce(body: unknown, ok = true, status = 200): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok,
      status,
      statusText: ok ? "OK" : "Error",
      json: async () => body,
      text: async () => JSON.stringify(body),
    })),
  );
}

function wellFormedFund(overrides: Partial<FundRef> = {}): FundRef {
  return {
    key: "BRK",
    name: "Berkshire Hathaway Inc",
    source: "13F",
    cik: "0001067983",
    series_id: null,
    ticker: null,
    principal: null,
    ...overrides,
  };
}

function wellFormedHolding(overrides: Partial<Holding> = {}): Holding {
  return {
    cusip: "166764100",
    issuer: "CHEVRON CORP NEW",
    value: "13990000000",
    shares: "118610534",
    weight: "0.0491",
    ticker: "CVX",
    ...overrides,
  };
}

function wellFormedSnapshot(overrides: Partial<Snapshot> = {}): Snapshot {
  return {
    fund: wellFormedFund(),
    period: "2026-06-30",
    filed: "2026-08-14",
    accession: "0000950123-26-007654",
    total_value: "285000000000",
    holdings: [wellFormedHolding()],
    value_units_rescaled: false,
    ...overrides,
  };
}

function wellFormedChange(overrides: Partial<HoldingChange> = {}): HoldingChange {
  return {
    cusip: "166764100",
    issuer: "CHEVRON CORP NEW",
    ticker: "CVX",
    action: "hold",
    shares_before: "118610534",
    shares_after: "118610534",
    shares_delta: "0",
    shares_pct_change: "0.00",
    value_before: "17460000000",
    value_after: "13990000000",
    value_delta: "-3470000000",
    weight_before: "0.0523",
    weight_after: "0.0491",
    weight_delta: "-0.0032",
    ...overrides,
  };
}

function wellFormedDelta(overrides: Partial<PortfolioDelta> = {}): PortfolioDelta {
  return {
    fund: wellFormedFund(),
    from_period: "2026-03-31",
    to_period: "2026-06-30",
    from_accession: "0000950123-26-004321",
    to_accession: "0000950123-26-007654",
    total_value_before: "290000000000",
    total_value_after: "285000000000",
    changes: [wellFormedChange()],
    counts: { new: 0, exit: 0, add: 0, trim: 0, hold: 1 },
    median_shares_pct_change: null,
    ...overrides,
  };
}

describe("institutionsApi.funds", () => {
  it("fetches the fund list with no parameters", async () => {
    const payload = { funds: [wellFormedFund()] };
    stubFetchOnce(payload);

    const result = await institutionsApi.funds();

    expect(fetch).toHaveBeenCalledTimes(1);
    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/institutions/funds");
    expect(result).toEqual(payload);
  });
});

describe("institutionsApi.holdings", () => {
  it("fetches without a period query when none is given", async () => {
    stubFetchOnce(wellFormedSnapshot());
    await institutionsApi.holdings("BRK");

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/institutions/BRK/holdings");
  });

  it("appends an encoded period query when one is given", async () => {
    stubFetchOnce(wellFormedSnapshot());
    await institutionsApi.holdings("BRK", "2026-06-30");

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/institutions/BRK/holdings?period=2026-06-30");
  });

  it("URL-encodes a fund key that is not already URL-safe", async () => {
    stubFetchOnce(wellFormedSnapshot());
    await institutionsApi.holdings("BRK/A B&C");

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe(
      `/api/institutions/${encodeURIComponent("BRK/A B&C")}/holdings`,
    );
  });

  it("parses a well-formed snapshot, keeping every money/share/weight field a string", async () => {
    const payload = wellFormedSnapshot();
    stubFetchOnce(payload);

    const result = await institutionsApi.holdings("BRK");

    expect(result.fund.key).toBe("BRK");
    expect(result.period).toBe("2026-06-30");
    expect(result.filed).toBe("2026-08-14");
    expect(result.accession).toBe("0000950123-26-007654");
    expect(typeof result.total_value).toBe("string");
    const holding = result.holdings[0];
    if (!holding) throw new Error("expected one holding");
    expect(typeof holding.value).toBe("string");
    expect(typeof holding.shares).toBe("string");
    expect(typeof holding.weight).toBe("string");
    // Most holdings carry no ticker at all -- this fixture's is deliberately non-null to prove the
    // field round-trips, but `null` is the common, correct case; see `institutions.ts`'s docstring.
    expect(holding.ticker).toBe("CVX");
  });

  it("handles a holding with a null ticker without dropping or fabricating one", async () => {
    stubFetchOnce(wellFormedSnapshot({ holdings: [wellFormedHolding({ ticker: null })] }));

    const result = await institutionsApi.holdings("BRK");

    expect(result.holdings[0]?.ticker).toBeNull();
  });
});

describe("institutionsApi.changes", () => {
  it("fetches the changes endpoint with an encoded key", async () => {
    stubFetchOnce(wellFormedDelta());
    await institutionsApi.changes("BRK");

    const call = vi.mocked(fetch).mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    expect(String(call[0])).toBe("/api/institutions/BRK/changes");
  });

  it("parses counts as a server-provided tally, not something this client computes", async () => {
    const payload = wellFormedDelta({
      changes: [wellFormedChange(), wellFormedChange({ cusip: "037833100", action: "new" })],
      counts: { new: 1, exit: 0, add: 0, trim: 0, hold: 1 },
    });
    stubFetchOnce(payload);

    const result = await institutionsApi.changes("BRK");

    expect(result.counts).toEqual({ new: 1, exit: 0, add: 0, trim: 0, hold: 1 });
    expect(result.changes).toHaveLength(2);
  });

  it("keeps shares_pct_change null for a brand-new position rather than coercing it", async () => {
    stubFetchOnce(
      wellFormedDelta({
        changes: [
          wellFormedChange({
            action: "new",
            shares_before: "0",
            shares_after: "5000",
            shares_delta: "5000",
            shares_pct_change: null,
          }),
        ],
      }),
    );

    const result = await institutionsApi.changes("BRK");
    expect(result.changes[0]?.shares_pct_change).toBeNull();
  });

  it("throws ApiRequestError on a non-ok response", async () => {
    stubFetchOnce({ detail: "boom" }, false, 500);

    await expect(institutionsApi.changes("BRK")).rejects.toMatchObject({
      name: "ApiRequestError",
      status: 500,
    });
  });
});

describe("formatWeight", () => {
  it("renders a fraction of one as a percentage with two decimal places", () => {
    expect(formatWeight("0.0914")).toBe("9.14%");
    expect(formatWeight("0.09")).toBe("9.00%");
    expect(formatWeight("1")).toBe("100.00%");
    expect(formatWeight("0")).toBe("0.00%");
  });

  it("truncates rather than rounds past two decimal places, matching formatMoney", () => {
    expect(formatWeight("0.099999")).toBe("9.99%");
  });

  it("renders a negative weight delta with a leading minus", () => {
    expect(formatWeight("-0.0032")).toBe("-0.32%");
  });

  it("never renders a non-zero weight as -0.00%, the QQQ NQM6 case", () => {
    // Live NPORT-P: QQQ held a CME E-Mini NASDAQ 100 future at -$12,012,436.80 against a fund
    // total of $372,066,640,823.76. The wire `weight` is that exact ratio, computed here by
    // scaling both figures to integer cents and doing BigInt division out to 20 fractional
    // digits -- not `value / total` through a float -- so the fixture is the real quotient, not
    // a number typed by hand and trusted.
    const value = "-1201243680"; // cents
    const total = "37206664082376"; // cents
    const scale = 20n;
    const valueScaled = BigInt(value) * 10n ** scale;
    const weightScaled = valueScaled / BigInt(total); // truncating integer division, sign preserved
    const negative = weightScaled < 0n;
    const abs = (negative ? -weightScaled : weightScaled).toString().padStart(Number(scale) + 1, "0");
    const whole = abs.slice(0, abs.length - Number(scale)) || "0";
    const frac = abs.slice(abs.length - Number(scale));
    const wireWeight = `${negative ? "-" : ""}${whole}.${frac}`;

    // Sanity-check the fixture itself lands where the bug report says it should before asserting
    // on the fix: a small negative fraction, on the order of -0.0032% once rendered.
    expect(wireWeight.startsWith("-0.0000322")).toBe(true);

    const rendered = formatWeight(wireWeight);
    expect(rendered).not.toBe("-0.00%");
    expect(rendered).toBe(">-0.01%");
    expect(rendered.startsWith(">")).toBe(true);
  });

  it("renders an exact zero plainly, with no sign and no under-threshold marker", () => {
    expect(formatWeight("0.0000")).toBe("0.00%");
    expect(formatWeight("-0.0000")).toBe("0.00%");
    expect(formatWeight("+0")).toBe("0.00%");
  });

  it("renders a tiny positive weight as the positive under-threshold marker", () => {
    expect(formatWeight("0.00003228571304700771")).toBe("<0.01%");
  });

  it("treats 0.01% as the boundary: exactly at it is shown, just below it is not", () => {
    expect(formatWeight("0.0001")).toBe("0.01%");
    expect(formatWeight("0.00009999")).toBe("<0.01%");
    expect(formatWeight("-0.0001")).toBe("-0.01%");
    expect(formatWeight("-0.00009999")).toBe(">-0.01%");
  });
});

describe("formatShares / formatSignedShares", () => {
  it("comma-groups a whole share count", () => {
    expect(formatShares("118610534")).toBe("118,610,534");
  });

  it("keeps a fractional share exactly as given", () => {
    expect(formatShares("12.345")).toBe("12.345");
  });

  it("drops the wire format's trailing zeros without touching real precision", () => {
    // Verbatim balances from a live QQQ NPORT-P filing. Every one of the fund's ~100 rows arrives
    // padded to eight decimal places, and rendering that padding put `.00000000` in every cell.
    expect(formatShares("102954591.00000000")).toBe("102,954,591");
    expect(formatShares("16718185.00000000")).toBe("16,718,185");
    // A genuine fraction keeps every significant digit; only the padding after it goes.
    expect(formatShares("1234.50000000")).toBe("1,234.5");
    expect(formatShares("0.00000001")).toBe("0.00000001");
    expect(formatSignedShares("-1156434.00000000")).toBe("-1,156,434");
  });

  it("signs a positive delta with a leading plus and a negative one with a minus", () => {
    expect(formatSignedShares("5000")).toBe("+5,000");
    expect(formatSignedShares("-2500")).toBe("-2,500");
    expect(formatSignedShares("0")).toBe("0");
  });
});

describe("formatSharesPctChange", () => {
  it("renders null as the word 'new', never 0% or Infinity", () => {
    expect(formatSharesPctChange(null)).toBe("new");
  });

  it("treats the wire value as a fraction of one, not an already-scaled percent", () => {
    // The server sends `shares_delta / shares_before`. Reading it as a percent is off by a
    // hundred, and the real figure it would have hidden is this one: Berkshire took Capital One
    // from 7,150,000 shares to 3,000,000 in a single quarter. Rendered as `-0.58%`, a majority
    // liquidation reads as noise.
    expect(formatSharesPctChange("-0.5804895104895105")).toBe("-58.04%");
    expect(formatSharesPctChange("0.4250")).toBe("+42.50%");
    expect(formatSharesPctChange("-1.00")).toBe("-100.00%");
  });

  it("signs increases explicitly but leaves a flat position unsigned", () => {
    expect(formatSharesPctChange("0.0000")).toBe("0.00%");
  });

  it("does not mangle a tiny share-count change in either direction", () => {
    // A tiny positive change must read as the under-threshold marker itself, not "+<0.01%" --
    // the leading "<" already says "grew, but too little to size", so a "+" on top is noise.
    expect(formatSharesPctChange("0.00003228571304700771")).toBe("<0.01%");
    // A tiny negative change must keep its sign, carried by the ">" marker, not get a "+" glued
    // in front of it.
    expect(formatSharesPctChange("-0.00003228571304700771")).toBe(">-0.01%");
  });
});

describe("SOURCE_NOTE", () => {
  it("has distinct copy for 13F and NPORT explaining what each filing actually covers", () => {
    expect(SOURCE_NOTE["13F"]).toMatch(/US-listed equities/);
    expect(SOURCE_NOTE["13F"]).not.toBe(SOURCE_NOTE.NPORT);
    expect(SOURCE_NOTE.NPORT).toMatch(/does not file a 13F/);
  });
});
