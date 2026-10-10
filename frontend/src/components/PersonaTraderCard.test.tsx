/**
 * `PersonaTraderCard` -- the model-driven persona paper trader card (Phase 10).
 *
 * What this pins, matching the task's definition of done:
 *  - both pinned caveats (point-in-time data / distilled method, no measured edge) are always
 *    visible -- never behind a disclosure;
 *  - equity and return_pct (a 0-1 fraction) render through the money/percent helpers;
 *  - holdings render, with "No open positions" for an empty book;
 *  - a `degraded` decision shows the warn pill;
 *  - the decide button is disabled while pending;
 *  - the backfill button passes the date-input string to `onBackfill`;
 *  - **each of decide / backfill / reset opens a `ConfirmSheet` and fires its callback only after
 *    the sheet is confirmed** (EXP-07): one click on a paid model call, or on a destructive reset,
 *    is never the action itself. Each sheet names what it spends or destroys and shows the book's
 *    own `spent_usd`, never a projected cost.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  TraderBook,
  TraderDecisionRec,
  TraderPosition,
} from "@/api/personas";

import PersonaTraderCard, { type BackfillState, type DecideState } from "./PersonaTraderCard";

afterEach(cleanup);

const IDLE_DECIDE: DecideState = { phase: "idle" };
const IDLE_BACKFILL: BackfillState = { phase: "idle" };

function position(overrides: Partial<TraderPosition> = {}): TraderPosition {
  return {
    symbol: "NVDA",
    quantity: "10",
    last_price: "1300.75",
    market_value: "13007.50",
    weight: 0.42,
    ...overrides,
  };
}

function decision(overrides: Partial<TraderDecisionRec> = {}): TraderDecisionRec {
  return {
    decided_on: "2026-08-25",
    fill_date: "2026-08-26",
    commentary: "Staying long the semis theme.",
    degraded: false,
    cost_usd: "0.12",
    trades: [
      { decided_on: "2026-08-25", fill_date: "2026-08-26", symbol: "NVDA", side: "buy", quantity: "10", price: "1300.75", thesis: "AI capex cycle" },
    ],
    rejections: [],
    ...overrides,
  };
}

function book(overrides: Partial<TraderBook> = {}): TraderBook {
  return {
    persona: "creator-a",
    display_name: "Creator A",
    inception: "2026-01-01",
    as_of: "2026-08-26",
    starting_cash: "100000.00",
    cash: "86992.50",
    equity: "100850.25",
    return_pct: "0.0085",
    benchmark: "SPY",
    benchmark_return_pct: "0.0500",
    excess_pct: "-0.0415",
    positions: [position()],
    equity_curve: [
      { date: "2026-01-01", equity: "100000.00" },
      { date: "2026-08-26", equity: "100850.25" },
    ],
    decisions: [decision()],
    spent_usd: "0.12",
    warnings: [],
    ...overrides,
  };
}

function renderCard(overrides: Partial<TraderBook> = {}, props: Partial<{
  decideState: DecideState;
  backfillState: BackfillState;
  onDecide: () => void;
  onBackfill: (inception: string) => void;
  onReset: () => void;
}> = {}) {
  const onDecide = props.onDecide ?? vi.fn();
  const onBackfill = props.onBackfill ?? vi.fn();
  const onReset = props.onReset ?? vi.fn();
  render(
    <PersonaTraderCard
      book={book(overrides)}
      decideState={props.decideState ?? IDLE_DECIDE}
      backfillState={props.backfillState ?? IDLE_BACKFILL}
      onDecide={onDecide}
      onBackfill={onBackfill}
      onReset={onReset}
    />,
  );
  return { onDecide, onBackfill, onReset };
}

describe("caveats", () => {
  it("always renders both pinned caveats, not behind a disclosure", () => {
    renderCard();
    expect(screen.getByText(/point-in-time/i)).toBeTruthy();
    expect(screen.getByText(/no measured edge/i)).toBeTruthy();
    // Neither caveat is inside a <details> -- InfoNote with no children renders a plain <p>.
    expect(document.querySelector("details.persona-trader-caveat")).toBeNull();
  });
});

describe("header and figures", () => {
  it("names the persona in the heading", () => {
    renderCard({ display_name: "Example Persona" });
    expect(screen.getByRole("heading", { name: /Example Persona/ })).toBeTruthy();
  });

  it("renders equity through formatMoney and return_pct as a scaled percent", () => {
    renderCard({ equity: "100850.25", return_pct: "0.0085" });
    expect(screen.getByText("$100,850.25")).toBeTruthy();
    expect(screen.getByText("+0.85%")).toBeTruthy();
    expect(screen.queryByText("+85.00%")).toBeNull();
  });

  it("renders the excess vs the SPY benchmark", () => {
    renderCard({ return_pct: "0.0085", benchmark: "SPY", benchmark_return_pct: "0.0500", excess_pct: "-0.0415" });
    expect(screen.getByText("vs SPY")).toBeTruthy();
    expect(screen.getByText("-4.15%")).toBeTruthy(); // the excess
    expect(screen.getByText("SPY +5.0%")).toBeTruthy(); // the benchmark's own return
  });

  it("shows 'No benchmark' when the benchmark could not be priced", () => {
    renderCard({ benchmark: "SPY", benchmark_return_pct: null, excess_pct: null });
    expect(screen.getByText("No benchmark")).toBeTruthy();
  });
});

describe("holdings", () => {
  it("renders a row per open position", () => {
    renderCard({ positions: [position({ symbol: "NVDA" })] });
    expect(screen.getByText("NVDA")).toBeTruthy();
    expect(screen.getByText("$1,300.75")).toBeTruthy();
  });

  it("shows 'No open positions' for an empty book", () => {
    renderCard({ positions: [] });
    expect(screen.getByText(/no open positions/i)).toBeTruthy();
  });
});

describe("equity curve", () => {
  it("renders the empty-state copy, not a broken chart, when equity_curve is empty", () => {
    renderCard({ equity_curve: [] });
    expect(screen.getByText(/no equity history/i)).toBeTruthy();
    expect(document.querySelector("svg.persona-trader-sparkline")).toBeNull();
  });

  it("renders an svg sparkline when equity_curve has points", () => {
    renderCard({
      equity_curve: [
        { date: "2026-01-01", equity: "100000.00" },
        { date: "2026-08-26", equity: "100850.25" },
      ],
    });
    expect(document.querySelector("svg.persona-trader-sparkline")).toBeTruthy();
  });
});

describe("decision log", () => {
  it("shows 'No decisions yet' for an empty log", () => {
    renderCard({ decisions: [] });
    expect(screen.getByText(/no decisions yet/i)).toBeTruthy();
  });

  it("renders a decision's commentary and trade line", () => {
    renderCard({ decisions: [decision()] });
    expect(screen.getByText(/staying long the semis theme/i)).toBeTruthy();
    expect(screen.getByText(/buy 10 NVDA @ \$1,300\.75/)).toBeTruthy();
  });

  it("shows a degraded warn pill when a decision is degraded", () => {
    renderCard({ decisions: [decision({ degraded: true })] });
    expect(screen.getByText(/degraded/i, { selector: ".status-pill" })).toBeTruthy();
  });

  it("does not show the degraded pill for a non-degraded decision", () => {
    renderCard({ decisions: [decision({ degraded: false })] });
    expect(screen.queryByText(/degraded/i, { selector: ".status-pill" })).toBeNull();
  });

  it("renders a rejection line", () => {
    renderCard({
      decisions: [
        decision({
          trades: [],
          rejections: [{ decided_on: "2026-08-25", symbol: "TSLA", side: "buy", reason: "position cap" }],
        }),
      ],
    });
    expect(screen.getByText(/TSLA: position cap/)).toBeTruthy();
  });
});

describe("decide control", () => {
  it("does not fire onDecide on the click -- it opens the confirm sheet first", () => {
    const { onDecide } = renderCard();
    fireEvent.click(screen.getByRole("button", { name: /run this week's decision/i }));
    expect(onDecide).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("Run this week's decision?");
  });

  it("names the model provider and the daily cap in the confirm sheet", () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /run this week's decision/i }));
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("model provider");
    expect(dialog.textContent).toContain("daily cap");
  });

  it("shows the book's own spend figure rather than inventing a projection", () => {
    renderCard({ spent_usd: "1.23" });
    fireEvent.click(screen.getByRole("button", { name: /run this week's decision/i }));
    expect(screen.getByRole("dialog").textContent).toContain("Spent on this book so far: $1.23");
  });

  it("fires onDecide once the sheet is confirmed", () => {
    const { onDecide } = renderCard();
    fireEvent.click(screen.getByRole("button", { name: /run this week's decision/i }));
    fireEvent.click(screen.getByRole("button", { name: "Run decision" }));
    expect(onDecide).toHaveBeenCalledTimes(1);
  });

  it("does not fire onDecide when the sheet is cancelled", () => {
    const { onDecide } = renderCard();
    fireEvent.click(screen.getByRole("button", { name: /run this week's decision/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onDecide).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("is disabled while pending, showing the pending label", () => {
    renderCard({}, { decideState: { phase: "pending" } });
    const button = screen.getByRole("button", { name: /deciding/i });
    expect(button.hasAttribute("disabled")).toBe(true);
  });

  it("shows the error message when decideState is an error", () => {
    renderCard({}, { decideState: { phase: "error", message: "budget cap exceeded" } });
    expect(screen.getByText("budget cap exceeded")).toBeTruthy();
  });
});

describe("backfill control", () => {
  it("defaults the date input to the book's inception", () => {
    renderCard({ inception: "2026-02-01" });
    const input = screen.getByDisplayValue("2026-02-01") as HTMLInputElement;
    expect(input.type).toBe("date");
  });

  it("does not fire onBackfill on the click -- it opens the confirm sheet first", () => {
    const { onBackfill } = renderCard();
    fireEvent.click(screen.getByRole("button", { name: /backfill from inception/i }));
    expect(onBackfill).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("states that backfill is one model call per week since inception", () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /backfill from inception/i }));
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("one call per week since inception");
    expect(dialog.textContent).toContain("daily cap");
  });

  it("passes the (possibly edited) date string to onBackfill once confirmed", () => {
    const { onBackfill } = renderCard({ inception: "2026-01-01" });
    const input = screen.getByDisplayValue("2026-01-01") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "2026-03-15" } });
    fireEvent.click(screen.getByRole("button", { name: /backfill from inception/i }));
    // The sheet quotes the date it is about to backfill from, not the book's inception.
    expect(screen.getByRole("dialog").textContent).toContain("2026-03-15");
    fireEvent.click(screen.getByRole("button", { name: "Start backfill" }));
    expect(onBackfill).toHaveBeenCalledWith("2026-03-15");
  });

  it("does not fire onBackfill when the sheet is cancelled", () => {
    const { onBackfill } = renderCard();
    fireEvent.click(screen.getByRole("button", { name: /backfill from inception/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onBackfill).not.toHaveBeenCalled();
  });

  it("shows the running state with the decided count and disables the button", () => {
    renderCard({}, { backfillState: { phase: "running", decided: 3 } });
    const button = screen.getByRole("button", { name: /3 decided/i });
    expect(button.hasAttribute("disabled")).toBe(true);
  });

  it("shows the error message when backfillState is an error", () => {
    renderCard({}, { backfillState: { phase: "error", message: "could not start the backfill" } });
    expect(screen.getByText("could not start the backfill")).toBeTruthy();
  });
});

describe("reset control", () => {
  it("does not fire onReset on the first click -- it opens the confirm sheet", () => {
    const { onReset } = renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Reset book" }));
    expect(onReset).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("Reset this trader book?");
    expect(dialog.textContent).toContain("cannot be undone");
  });

  it("fires onReset once the sheet is confirmed", () => {
    const { onReset } = renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Reset book" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, reset" }));
    expect(onReset).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("cancels the sheet without firing onReset", () => {
    const { onReset } = renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Reset book" }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onReset).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Reset book" })).toBeTruthy();
  });
});
