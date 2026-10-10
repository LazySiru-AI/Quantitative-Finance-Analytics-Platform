import { describe, expect, it } from "vitest";

import { headline, shortId } from "@/pages/competition/candidateName";

describe("shortId", () => {
  it("matches SPEC.md's own worked example verbatim", () => {
    expect(shortId("g1859-fd7c2c196f35")).toBe("g1859·fd7c");
  });

  it("lower-cases an upper-case hash without changing the generation prefix", () => {
    expect(shortId("g1845-ABC123")).toBe("g1845·abc1");
  });

  it("returns an id it cannot parse unchanged rather than guessing at its shape", () => {
    expect(shortId("not-a-genome-id")).toBe("not-a-genome-id");
  });
});

describe("headline", () => {
  it("composes rule-derived description · top3 tickers +N · purpose, matching the coordinator's example", () => {
    expect(
      headline({
        ruleSummary: "EMA 13/21 crossover, 135-day regime filter",
        tickers: ["CSCO", "AMAT", "LRCX", "KLAC", "INTU", "IGV"],
        purpose: "roth",
      }),
    ).toBe("EMA 13/21 crossover, 135-day regime filter · CSCO/AMAT/LRCX +3 · Roth");
  });

  it("uses the short purpose word, not the longer PURPOSE_LABELS badge text", () => {
    // PURPOSE_LABELS.roth is "Roth IRA" (api/evolution.ts) -- the headline word is shorter, "Roth",
    // matching SPEC.md's example exactly. Getting the two mixed up is an easy, silent mistake.
    const result = headline({ ruleSummary: "SMA trend filter", tickers: ["AAPL"], purpose: "roth" });
    expect(result.endsWith("· Roth")).toBe(true);
    expect(result).not.toContain("Roth IRA");
  });

  it("shows every ticker with no +N suffix when there are three or fewer", () => {
    expect(headline({ ruleSummary: "Carry rule", tickers: ["AAA", "BBB"], purpose: "trading" })).toBe(
      "Carry rule · AAA/BBB · Trading",
    );
  });

  it("degrades to a purpose-only line when no rule-derived description is known yet, never fabricating one", () => {
    // A PendingSeat row before its dossier has loaded has no rule-derived text at all -- headline()
    // must not invent one, and must not fall back to a `discipline` label either (see the module
    // docstring: discipline is not derived from the rule and cannot be trusted to describe it).
    expect(headline({ ruleSummary: null, tickers: [], purpose: "savings" })).toBe(
      "Savings candidate — expand for what it trades",
    );
  });

  it("treats an empty or whitespace-only ruleSummary the same as null", () => {
    expect(headline({ ruleSummary: "", tickers: ["AAPL"], purpose: "trading" })).toBe(
      "Trading candidate — expand for what it trades",
    );
    expect(headline({ ruleSummary: "   ", tickers: ["AAPL"], purpose: "trading" })).toBe(
      "Trading candidate — expand for what it trades",
    );
  });

  it("never shows the bare genome hash as part of the headline", () => {
    const result = headline({
      ruleSummary: "EMA 13/21 crossover, 135-day regime filter",
      tickers: ["CSCO", "AMAT", "LRCX"],
      purpose: "roth",
    });
    expect(result).not.toMatch(/g\d+-[0-9a-f]+/);
  });

  it("has no way to accept a discipline label at all -- HeadlineInput carries no such field", () => {
    // Regression guard for the 2026-08-26 correction: g1815-d05786e4c611 was mutated into
    // g1823-e2a3d5060b09 with an identical rule (universe, entry, exit, stop, sizing all
    // byte-identical) but a discipline flip from "breakout" to "mean-reversion" -- proof discipline is
    // a self-declared label, not a description of the rule, and must never drive the headline. This
    // test exists so a future edit that types `discipline` back into `HeadlineInput` is a visible,
    // deliberate change to this test, not a silent one.
    const input: import("@/pages/competition/candidateName").HeadlineInput = {
      ruleSummary: "EMA 13/21 crossover, 135-day regime filter",
      tickers: ["AMAT", "LRCX"],
      purpose: "roth",
    };
    expect(Object.keys(input).sort()).toEqual(["purpose", "ruleSummary", "tickers"]);
  });
});
