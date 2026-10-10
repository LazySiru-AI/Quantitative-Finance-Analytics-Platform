/**
 * PersonaScorecard: the fixed-horizon extension (horizon_stats, hit_rate_ci, per-call horizons).
 * Existing aggregate/row behaviour (sign coloring, outcome badges, warnings) is covered by
 * `pages/Personas.test.tsx`; this file focuses on what Round 2 added on top of it -- see that
 * file's own docstring for the split. Every "null must not render as zero" case mirrors the
 * discipline `StatValue.test.tsx` already pins for the shared CI renderer.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import type {
  CallScore,
  HorizonReturn,
  HorizonStat,
  PersonaScorecard as Scorecard,
  StatEstimate,
} from "@/api/personas";
import PersonaScorecard from "@/components/PersonaScorecard";

afterEach(cleanup);

function estimate(overrides: Partial<StatEstimate> = {}): StatEstimate {
  return { n: 40, point: 0.55, low: 0.4, high: 0.7, confidence: 0.9, method: "wilson", ...overrides };
}

function horizonStat(overrides: Partial<HorizonStat> = {}): HorizonStat {
  return {
    days: 5,
    directional_count: 40,
    played_out: 22,
    hit_rate: 0.55,
    median_return_pct: 2.1,
    mean_return_pct: 1.8,
    hit_rate_ci: estimate(),
    return_ci: estimate({ point: 0.018, low: -0.01, high: 0.05, method: "bootstrap" }),
    ...overrides,
  };
}

function callScore(overrides: Partial<CallScore> = {}): CallScore {
  return {
    symbol: "NVDA",
    stance: "bullish",
    note_id: "note-1",
    said_on: "2026-01-01",
    entry_date: "2026-01-02",
    entry_price: 100,
    latest_date: "2026-02-01",
    latest_price: 110,
    return_pct: 10,
    basis: "close",
    outcome: "played_out",
    horizons: [],
    ...overrides,
  };
}

function scorecard(overrides: Partial<Scorecard> = {}): Scorecard {
  return {
    persona: "creator-a",
    as_of: "2026-02-01",
    scored_calls: [],
    directional_count: 40,
    played_out: 22,
    hit_rate: 0.55,
    median_return_pct: 2.0,
    hit_rate_ci: estimate(),
    horizon_stats: [],
    warnings: [],
    ...overrides,
  };
}

function renderLoaded(sc: Scorecard) {
  render(
    <MemoryRouter>
      <PersonaScorecard displayName="Creator A" state={{ phase: "loaded", scorecard: sc }} />
    </MemoryRouter>,
  );
}

describe("fixed-horizon summary", () => {
  it("renders a full horizon_stat's hit-rate CI, with n and the interval bounds", () => {
    renderLoaded(scorecard({ horizon_stats: [horizonStat({ days: 5 })] }));
    const text = screen.getByTestId("horizon-hit-rate-5").textContent ?? "";
    expect(text).toContain("n=40");
    expect(text).toContain("CI");
    expect(text).not.toBe("no data");
  });

  it("renders a full horizon_stat's mean-return CI as an already-scaled percent (7.84 -> 7.84%)", () => {
    // return_ci arrives already scaled to percent (backend _pct_return is *100), like every *_pct
    // field -- so 7.84 must render "7.84%", never "784%".
    renderLoaded(
      scorecard({
        horizon_stats: [
          horizonStat({ days: 20, return_ci: estimate({ point: 7.84, low: 1.0, high: 15.0, method: "bootstrap" }) }),
        ],
      }),
    );
    const text = screen.getByTestId("horizon-mean-20").textContent ?? "";
    expect(text).toContain("7.84%");
    expect(text).not.toContain("784");
  });

  it("renders one row per horizon_stat, keyed by days", () => {
    renderLoaded(
      scorecard({
        horizon_stats: [horizonStat({ days: 5 }), horizonStat({ days: 20 }), horizonStat({ days: 60 })],
      }),
    );
    expect(screen.getByTestId("horizon-row-5")).toBeTruthy();
    expect(screen.getByTestId("horizon-row-20")).toBeTruthy();
    expect(screen.getByTestId("horizon-row-60")).toBeTruthy();
  });

  it("renders 'no data' for a null hit_rate_ci at a horizon, never a fabricated zero", () => {
    renderLoaded(
      scorecard({
        horizon_stats: [
          horizonStat({
            days: 60,
            directional_count: 0,
            played_out: 0,
            hit_rate: null,
            median_return_pct: null,
            mean_return_pct: null,
            hit_rate_ci: null,
            return_ci: null,
          }),
        ],
      }),
    );
    const hitRate = screen.getByTestId("horizon-hit-rate-60");
    expect(hitRate.textContent).toBe("no data");
    expect(hitRate.textContent).not.toContain("0");
  });

  it("renders 'not enough data yet' for a null median_return_pct at a horizon, distinct from 0%", () => {
    renderLoaded(
      scorecard({
        horizon_stats: [horizonStat({ days: 60, median_return_pct: null })],
      }),
    );
    const median = screen.getByTestId("horizon-median-60");
    expect(median.textContent).toBe("Not enough data yet");
    expect(median.textContent).not.toContain("0%");
  });

  it("renders a real zero median_return_pct as a signed zero, not the null copy", () => {
    renderLoaded(scorecard({ horizon_stats: [horizonStat({ days: 5, median_return_pct: 0 })] }));
    expect(screen.getByTestId("horizon-median-5").textContent).toBe("+0.00%");
  });

  it("renders no horizon section at all when horizon_stats is empty", () => {
    renderLoaded(scorecard({ horizon_stats: [] }));
    expect(screen.queryByText("By horizon")).toBeNull();
  });

  it("renders 'no data' for the top-level aggregate hit_rate_ci when null", () => {
    renderLoaded(scorecard({ hit_rate_ci: null }));
    expect(screen.getByTestId("scorecard-hit-rate-ci").textContent).toBe("no data");
  });

  it("renders the top-level aggregate hit_rate_ci with its CI when present", () => {
    renderLoaded(scorecard({ hit_rate_ci: estimate({ n: 192, point: 0.16, low: 0.11, high: 0.22 }) }));
    const text = screen.getByTestId("scorecard-hit-rate-ci").textContent ?? "";
    expect(text).toContain("n=192");
    expect(text).toContain("CI");
  });
});

describe("per-call fixed-horizon returns", () => {
  function horizonReturn(overrides: Partial<HorizonReturn> = {}): HorizonReturn {
    return { days: 5, return_pct: 4.32, complete: true, ...overrides };
  }

  it("renders a complete horizon return with its sign, via formatReturnPct", () => {
    const call = callScore({ note_id: "n1", symbol: "AAPL", horizons: [horizonReturn({ days: 5, return_pct: 4.32 })] });
    renderLoaded(scorecard({ scored_calls: [call] }));
    const el = screen.getByTestId("call-horizons-n1-AAPL");
    expect(el.textContent).toContain("+4.32%");
  });

  it("renders an incomplete (complete: false) horizon as 'too recent', NEVER as 0%", () => {
    const call = callScore({
      note_id: "n2",
      symbol: "TSLA",
      horizons: [horizonReturn({ days: 5, return_pct: null, complete: false })],
    });
    renderLoaded(scorecard({ scored_calls: [call] }));
    const el = screen.getByTestId("call-horizons-n2-TSLA");
    expect(el.textContent).toContain("too recent");
    expect(el.textContent).not.toContain("0%");
  });

  it("renders multiple per-call horizons, each independently complete or not", () => {
    const call = callScore({
      note_id: "n3",
      symbol: "MSFT",
      horizons: [
        horizonReturn({ days: 5, return_pct: 1.2, complete: true }),
        horizonReturn({ days: 20, return_pct: null, complete: false }),
      ],
    });
    renderLoaded(scorecard({ scored_calls: [call] }));
    const el = screen.getByTestId("call-horizons-n3-MSFT");
    expect(el.textContent).toContain("+1.20%");
    expect(el.textContent).toContain("too recent");
  });

  it("renders nothing extra for a call with no horizons", () => {
    const call = callScore({ note_id: "n4", symbol: "GOOG", horizons: [] });
    renderLoaded(scorecard({ scored_calls: [call] }));
    expect(screen.queryByTestId("call-horizons-n4-GOOG")).toBeNull();
  });
});
