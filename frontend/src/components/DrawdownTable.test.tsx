/**
 * The current-drawdown card.
 *
 * The defect this pins was not arithmetic: `depth` was correct and the card rendered it correctly,
 * under a label asking a different question. It showed the ongoing episode's *worst bar* as
 * "Current drawdown" — 15.6% on a name trading 2.4% off its high — and a UAT persona holding that
 * name caught it only by checking the headline against the quote at the top of the same page.
 *
 * So these assert the distinction rather than the formatting: the headline is the live gap, the low
 * is still shown but phrased as history, and the two never appear as competing estimates of one
 * quantity.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DrawdownEpisode, DrawdownProfile } from "@/api/backtest";

// The card is internal to `DrawdownTable`, which fetches. Stubbing the hook exercises the real
// component and its real markup without exporting an internal for a test's convenience or letting
// a "unit" test reach a live backend.
const state = vi.hoisted(() => ({
  current: null as DrawdownProfile | null,
}));

vi.mock("@/hooks/useBacktest", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useBacktest")>();
  return {
    ...actual,
    useDrawdownProfile: () => ({
      profile: state.current,
      phase: state.current ? "loaded" : "error",
      message: state.current ? null : "no profile",
    }),
  };
});

const { default: DrawdownTable } = await import("@/components/DrawdownTable");

function episode(overrides: Partial<DrawdownEpisode> = {}): DrawdownEpisode {
  return {
    peak_date: "2026-03-27",
    peak_value: 62.56,
    trough_date: "2026-07-01",
    trough_value: 52.81,
    depth: -0.1558,
    bars_to_trough: 66,
    recovery_date: null,
    bars_to_recovery: null,
    bars_underwater: 95,
    still_underwater: true,
    depth_now: -0.024,
    last_value: 61.06,
    last_value_date: "2026-08-13",
    ...overrides,
  };
}

function profile(current: DrawdownEpisode | null): DrawdownProfile {
  return {
    symbol: "XLE",
    interval: "1d",
    basis: "close",
    generated_at: "2026-08-14T00:00:00Z",
    bars: 277,
    first_bar: "2025-01-02",
    last_bar: "2026-08-13",
    episodes: current ? [current] : [],
    episodes_considered: current ? 1 : 0,
    current,
    warnings: [],
  };
}

function renderWith(next: DrawdownProfile) {
  state.current = next;
  render(<DrawdownTable symbol={next.symbol} interval="1d" />);
}

describe("current drawdown card", () => {
  it("leads with the live gap, not the episode's worst bar", () => {
    renderWith(profile(episode()));
    const card = document.querySelector(".bt-current-drawdown");
    const headline = card?.querySelector(".bt-current-drawdown-depth");

    expect(headline?.textContent).toBe("2.4%");
    expect(headline?.textContent).not.toBe("15.6%");
  });

  it("still reports the low, phrased as history rather than as a second estimate", () => {
    /**
     * Both figures matter — "how much risk am I carrying now" and "how bad has this been" — and
     * dropping the low to fix the headline would trade one missing answer for another. It is
     * worded as an event in the past because `formatDepth` drops the sign by convention, and two
     * bare percentages stacked on one card read as a disagreement.
     */
    renderWith(profile(episode()));
    const card = document.querySelector(".bt-current-drawdown");

    expect(card?.textContent).toContain("fell 15.6% to its low on 2026-07-01");
  });

  it("carries an as-of on the live figure", () => {
    renderWith(profile(episode()));
    expect(document.querySelector(".bt-current-drawdown")?.textContent).toContain(
      "as of 2026-08-13",
    );
  });

  it("falls back to the trough depth when the backend sends no live figure", () => {
    /**
     * `depth_now` is null on a recovered episode by design. The card must not render an empty
     * headline for an older backend or an episode that closed — and it must not invent a "0%",
     * which would claim the instrument is sitting exactly at its peak.
     */
    renderWith(profile(episode({ depth_now: null, last_value: null, last_value_date: null })));
    const card = document.querySelector(".bt-current-drawdown");

    expect(card?.querySelector(".bt-current-drawdown-depth")?.textContent).toBe("15.6%");
    expect(card?.textContent).not.toContain("fell 15.6% to its low");
  });

  it("says so plainly when nothing is underwater", () => {
    renderWith(profile(null));
    expect(screen.getByText(/Not currently underwater/i)).toBeTruthy();
  });
});
