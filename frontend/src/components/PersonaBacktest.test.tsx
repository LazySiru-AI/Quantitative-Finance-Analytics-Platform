/**
 * PersonaBacktest: the SPY-benchmarked backtest lens. Pins the guardrails this component's own
 * docstring lists -- the caveat always renders (never behind a disclosure), `call_count: 0` /
 * `horizons: []` is a valid empty state (not an error), and every nullable `BenchmarkedHorizon`
 * field renders distinctly from a fabricated zero, mirroring `PersonaScorecard.test.tsx`'s own
 * discipline for `HorizonStat`.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { BenchmarkedHorizon, PersonaBacktest as Backtest, StatEstimate } from "@/api/personas";
import PersonaBacktest, { type BacktestFetchState } from "@/components/PersonaBacktest";

afterEach(cleanup);

function estimate(overrides: Partial<StatEstimate> = {}): StatEstimate {
  return { n: 30, point: 0.007, low: -0.01, high: 0.03, confidence: 0.9, method: "bootstrap", ...overrides };
}

function benchmarkedHorizon(overrides: Partial<BenchmarkedHorizon> = {}): BenchmarkedHorizon {
  return {
    days: 5,
    n: 30,
    mean_return_pct: 1.2,
    mean_benchmark_pct: 0.5,
    excess_pct: 0.7,
    win_rate_vs_benchmark: 0.6,
    excess_ci: estimate(),
    ...overrides,
  };
}

const CAVEAT = "Small samples over a single window are not evidence of skill.";

function backtest(overrides: Partial<Backtest> = {}): Backtest {
  return {
    persona: "creator-a",
    as_of: "2026-02-01",
    benchmark: "SPY",
    call_count: 30,
    horizons: [benchmarkedHorizon()],
    caveat: CAVEAT,
    warnings: [],
    ...overrides,
  };
}

function renderState(state: BacktestFetchState) {
  render(<PersonaBacktest displayName="Creator A" state={state} />);
}

function renderLoaded(bt: Backtest) {
  renderState({ phase: "loaded", backtest: bt });
}

describe("fetch states", () => {
  it("renders a loading placeholder", () => {
    renderState({ phase: "loading" });
    expect(screen.getByText(/loading backtest/i)).toBeTruthy();
  });

  it("renders the error message verbatim on the error phase", () => {
    renderState({ phase: "error", message: "unknown persona slug" });
    expect(screen.getByRole("alert").textContent).toBe("unknown persona slug");
  });
});

describe("the caveat is always visible", () => {
  it("renders the backend caveat verbatim, not behind any disclosure, on a normal loaded state", () => {
    renderLoaded(backtest());
    const el = screen.getByTestId("backtest-caveat");
    expect(el.textContent).toContain(CAVEAT);
    // Not a <details>/<button> disclosure -- the caveat's own container has no toggle.
    expect(el.querySelector("button")).toBeNull();
    expect(el.tagName.toLowerCase()).not.toBe("details");
  });

  it("still renders the caveat even in the empty (call_count: 0) state", () => {
    renderLoaded(backtest({ call_count: 0, horizons: [] }));
    expect(screen.getByTestId("backtest-caveat").textContent).toContain(CAVEAT);
  });
});

describe("empty state", () => {
  it("renders an empty note, not an error, for call_count: 0 / horizons: []", () => {
    renderLoaded(backtest({ call_count: 0, horizons: [] }));
    expect(screen.getByTestId("backtest-empty")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("names the benchmark in the empty-state copy", () => {
    renderLoaded(backtest({ call_count: 0, horizons: [], benchmark: "QQQ" }));
    expect(screen.getByTestId("backtest-empty").textContent).toContain("QQQ");
  });

  it("renders no empty note when there are scored horizons", () => {
    renderLoaded(backtest());
    expect(screen.queryByTestId("backtest-empty")).toBeNull();
  });
});

describe("benchmarked horizons", () => {
  it("renders a full horizon's excess_ci with its confidence interval", () => {
    renderLoaded(backtest({ horizons: [benchmarkedHorizon({ days: 20 })] }));
    const text = screen.getByTestId("backtest-excess-ci-20").textContent ?? "";
    expect(text).toContain("n=30");
    expect(text).toContain("CI");
  });

  it("renders mean/benchmark/excess returns via formatReturnPct, signed", () => {
    renderLoaded(
      backtest({
        horizons: [
          benchmarkedHorizon({ days: 5, mean_return_pct: 3.4, mean_benchmark_pct: -1.1 }),
        ],
      }),
    );
    const row = screen.getByTestId("backtest-row-5");
    expect(row.textContent).toContain("+3.40%");
    expect(row.textContent).toContain("-1.10%");
  });

  it("renders 'no data' for every nullable field when n is 0, never a fabricated zero", () => {
    renderLoaded(
      backtest({
        horizons: [
          benchmarkedHorizon({
            days: 60,
            n: 0,
            mean_return_pct: null,
            mean_benchmark_pct: null,
            excess_pct: null,
            win_rate_vs_benchmark: null,
            excess_ci: null,
          }),
        ],
      }),
    );
    const row = screen.getByTestId("backtest-row-60");
    expect(row.textContent).not.toContain("0%");
    expect(screen.getByTestId("backtest-excess-ci-60").textContent).toBe("no data");
  });

  it("renders one row per horizon, keyed by days", () => {
    renderLoaded(
      backtest({
        horizons: [
          benchmarkedHorizon({ days: 5 }),
          benchmarkedHorizon({ days: 20 }),
          benchmarkedHorizon({ days: 60 }),
        ],
      }),
    );
    expect(screen.getByTestId("backtest-row-5")).toBeTruthy();
    expect(screen.getByTestId("backtest-row-20")).toBeTruthy();
    expect(screen.getByTestId("backtest-row-60")).toBeTruthy();
  });

  it("shows the win rate vs benchmark as a rounded percent of a fraction", () => {
    renderLoaded(backtest({ horizons: [benchmarkedHorizon({ days: 5, win_rate_vs_benchmark: 0.6 })] }));
    expect(screen.getByTestId("backtest-row-5").textContent).toContain("60%");
  });
});

describe("warnings", () => {
  it("renders non-empty warnings, source and reason verbatim", () => {
    renderLoaded(backtest({ warnings: [{ source: "NVDA", reason: "no benchmark bars for that window" }] }));
    expect(screen.getByText(/NVDA: no benchmark bars for that window/)).toBeTruthy();
  });

  it("renders no warning list when warnings is empty", () => {
    renderLoaded(backtest({ warnings: [] }));
    expect(screen.queryByRole("list", { name: /citations/i })).toBeNull();
  });
});

describe("framing", () => {
  it("names the benchmark and the persona's display name in the caption, never claiming outperformance", () => {
    renderLoaded(backtest({ benchmark: "SPY" }));
    const captions = screen.getAllByText(/Creator A/);
    expect(captions.length).toBeGreaterThan(0);
    expect(document.body.textContent).toContain("SPY");
    expect(document.body.textContent?.toLowerCase()).not.toContain("beat the market");
  });
});
