/**
 * The Fear & Greed card, rendered in both languages.
 *
 * The card's chrome (headings, band labels, rating words) was translated long ago; the seven rows
 * inside it were not, because their names and one-phrase descriptions come off the wire from CNN.
 * These tests pin the rule that fixed that and the rule that keeps it safe:
 *
 *  - a known component id renders its Korean name and description under 한국어;
 *  - an **unknown** id renders the server's own label and description rather than throwing or
 *    blanking -- a closed union over a server-supplied string is how a page goes down;
 *  - English is unchanged, so the existing English assertions elsewhere keep meaning what they did.
 *
 * `FearGreedHistoryChart` is mocked: it draws to a canvas via lightweight-charts, which is more than
 * this file needs and nothing here asserts on.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FearGreed, FearGreedComponent } from "@/api/macro";
import FearGreedGauge from "@/components/FearGreedGauge";
import { LANGUAGE_STORAGE_KEY, refreshLanguageFromStorage, setLanguage } from "@/i18n/store";

vi.mock("@/components/FearGreedHistoryChart", () => ({ default: () => <div /> }));

function component(overrides: Partial<FearGreedComponent> = {}): FearGreedComponent {
  return {
    key: "market_momentum_sp500",
    label: "Market Momentum",
    raw_value: 6842.13,
    raw_unit: "index",
    raw_description: "S&P 500 index level, against its 125-day moving average",
    score: null,
    rating: "fear",
    as_of: "2026-09-09",
    ...overrides,
  };
}

function fearGreed(overrides: Partial<FearGreed> = {}): FearGreed {
  return {
    score: 39,
    rating: "fear",
    source: "cnn",
    as_of: "2026-09-09",
    components: [component()],
    previous_close: 41,
    previous_week: 44,
    previous_month: 52,
    previous_year: 60,
    history: [],
    warnings: [],
    ...overrides,
  };
}

afterEach(() => {
  window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
  refreshLanguageFromStorage();
});

describe("component vocabulary in English", () => {
  it("renders CNN's own component name and description", () => {
    render(<FearGreedGauge data={fearGreed()} />);

    expect(screen.getByText("Market Momentum")).toBeTruthy();
    expect(screen.getByText(/125-day moving average/)).toBeTruthy();
  });

  it("keeps the raw unit as its English suffix", () => {
    render(<FearGreedGauge data={fearGreed()} />);

    expect(screen.getByText("6,842.13 index")).toBeTruthy();
  });
});

describe("component vocabulary in Korean", () => {
  beforeEach(() => setLanguage("ko"));

  it("translates the component name and the phrase under it", () => {
    render(<FearGreedGauge data={fearGreed()} />);

    expect(screen.getByText("시장 모멘텀")).toBeTruthy();
    expect(screen.getByText("S&P 500 지수를 125일 이동평균과 비교합니다.")).toBeTruthy();
    // The English the server sent is gone from the card, not merely appended to.
    expect(screen.queryByText("Market Momentum")).toBeNull();
  });

  it("translates every one of the seven components CNN publishes", () => {
    render(
      <FearGreedGauge
        data={fearGreed({
          components: [
            component({ key: "market_momentum_sp500", label: "Market Momentum" }),
            component({ key: "stock_price_strength", label: "Stock Price Strength" }),
            component({ key: "stock_price_breadth", label: "Stock Price Breadth" }),
            component({ key: "put_call_options", label: "Put and Call Options" }),
            component({ key: "market_volatility_vix", label: "Market Volatility" }),
            component({ key: "junk_bond_demand", label: "Junk Bond Demand" }),
            component({ key: "safe_haven_demand", label: "Safe Haven Demand" }),
          ],
        })}
      />,
    );

    for (const name of [
      "시장 모멘텀",
      "주가 강도",
      "주가 폭",
      "풋·콜 옵션",
      "시장 변동성",
      "정크본드 수요",
      "안전자산 수요",
    ]) {
      expect(screen.getByText(name)).toBeTruthy();
    }
  });

  it("translates the raw unit suffix", () => {
    render(<FearGreedGauge data={fearGreed()} />);

    expect(screen.getByText("6,842.13 지수")).toBeTruthy();
  });

  /**
   * The rule the whole shard exists for. CNN adding an eighth component, or renaming a key, must
   * cost one untranslated row -- not the card, and not the Overview page around it.
   */
  it("falls back to the server's own name and description for an id it has never seen", () => {
    render(
      <FearGreedGauge
        data={fearGreed({
          components: [
            component({
              key: "insider_conviction",
              label: "Insider Conviction",
              raw_unit: "bp",
              raw_description: "net insider buying against a trailing baseline",
            }),
          ],
        })}
      />,
    );

    expect(screen.getByText("Insider Conviction")).toBeTruthy();
    expect(screen.getByText("net insider buying against a trailing baseline")).toBeTruthy();
    expect(screen.getByText("6,842.13 bp")).toBeTruthy();
    // Still a rendered card, which is the point of the fallback.
    expect(screen.getByText("공포·탐욕 지수")).toBeTruthy();
  });

  /** An absent unit renders as no suffix at all -- a guessed one is worse than none, since the seven
   *  numbers are in seven different units. */
  it("prints no unit suffix when the backend has none on record", () => {
    render(<FearGreedGauge data={fearGreed({ components: [component({ raw_unit: null })] })} />);

    expect(screen.getByText("6,842.13")).toBeTruthy();
  });
});
