/**
 * `RejectionsCallout`/`RejectionGroup`, the compact broker-refusal summary that replaced a flat
 * `<ul>` of duplicate strings (eight repeats of `"insufficient_cash"` for one card was the reported
 * problem).
 *
 * What these tests pin, matching the task's definition of done:
 *  - the per-rule summary line (label, order count, affected symbols) renders as the group's own
 *    headline rather than being buried among the per-order sentences. Since the card refactor the
 *    callout as a whole sits inside the desk card's "Statistics & details" disclosure -- see
 *    `RejectionsCallout`'s own note on that trade -- but the summary line is still what a reader
 *    sees the moment the callout is on screen, with no second click per group;
 *  - the per-order detail sentences are reachable only once the group's own `<details>` is expanded.
 *    Checked via the `<details>` element's `open` property, the same technique
 *    `WashSales.test.tsx`/`Institutions.test.tsx`/`Portfolio.test.tsx` use for their own disclosures:
 *    jsdom does not natively hide a closed `<details>`'s content the way a real browser does, so
 *    asserting on that DOM property is the reliable signal, not `queryByText` returning null;
 *  - a group with an empty server-sent `label` falls back to the machine `rule` slug and renders
 *    without throwing -- `rule` is an open string, and a page that crashes on one unrecognised value
 *    has already taken itself down once in this codebase (see `exitReasonLabel`'s docstring in
 *    `@/api/paperdesk`).
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import type {
  AutopilotDescription,
  AutopilotOrder,
  Decision,
  Desk,
  DeskRejection,
  Holding,
  LiveFill,
  Signal,
  Trade,
} from "@/api/paperdesk";

import DeskPanel from "./DeskPanel";

afterEach(cleanup);

/**
 * `BookStatistics`'s `kind === "autopilot"` branch (`DeskAutopilotDescription`, owned by that
 * sibling file, not this one) links out to the Agent Workflow desk via `react-router-dom`'s `Link`,
 * which throws outside a Router context. `DeskPanel` renders `BookStatistics` unconditionally, so
 * any test exercising an autopilot desk needs the same `<MemoryRouter>` wrapper
 * `Portfolio.test.tsx`/`Tax.test.tsx` already use for their own `Link`-rendering pages. Every
 * non-autopilot fixture in this file renders fine without it, so this wrapper is only reached for
 * by the autopilot test cases below. */
function renderAutopilotDesk(desk: Desk, asOf: string) {
  return render(
    <MemoryRouter>
      <DeskPanel desk={desk} asOf={asOf} />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Fixtures -- mirror the contract in @/api/paperdesk field for field, independent of
// PaperDesk.test.tsx's own fixtures (out of this file's scope fence).
// ---------------------------------------------------------------------------

function holding(overrides: Partial<Holding> = {}): Holding {
  return {
    symbol: "NVDA",
    quantity: "120",
    entry_date: "2026-08-05",
    entry_price: "185.20",
    cost_basis: "22224.00",
    last_price: "191.40",
    last_price_date: "2026-08-19",
    market_value: "22968.00",
    unrealised_pnl: "744.00",
    return_pct: "0.0335",
    bars_held: 9,
    weight: 0.227,
    stop_price: "162.98",
    target_price: null,
    sessions_to_time_stop: 171,
    ...overrides,
  };
}

function trade(overrides: Partial<Trade> = {}): Trade {
  return {
    symbol: "MU",
    entry_date: "2026-08-04",
    entry_price: "50.00",
    exit_date: "2026-08-12",
    exit_price: "45.00",
    quantity: "20",
    exit_reason: "stop",
    pnl: "-1200.00",
    return_pct: "-0.084",
    bars_held: 6,
    ...overrides,
  };
}

function decision(overrides: Partial<Decision> = {}): Decision {
  return {
    date: "2026-08-05",
    symbol: "NVDA",
    action: "enter",
    reason: "entry rule fired",
    price: "185.20",
    quantity: "120",
    notional: "22224.00",
    ...overrides,
  };
}

function signal(overrides: Partial<Signal> = {}): Signal {
  return {
    symbol: "NVDA",
    held: true,
    entry_fires: false,
    exit_fires: false,
    last_close: "191.40",
    blocked: null,
    rank_value: null,
    entry_rank: null,
    ...overrides,
  };
}

function rejection(overrides: Partial<DeskRejection> = {}): DeskRejection {
  return {
    rule: "insufficient_cash",
    label: "Insufficient settled cash",
    count: 8,
    symbols: ["AAPL", "MSFT", "NVDA"],
    detail: [
      "Order for AAPL rejected: insufficient settled cash of $1,204.50 (session 8)",
      "Order for MSFT rejected: insufficient settled cash of $980.00 (session 7)",
      "Order for NVDA rejected: insufficient settled cash of $2,410.75 (session 7)",
      "Order for AAPL rejected: insufficient settled cash of $1,150.00 (session 6)",
      "Order for MSFT rejected: insufficient settled cash of $890.25 (session 5)",
      "Order for NVDA rejected: insufficient settled cash of $2,100.00 (session 4)",
      "Order for AAPL rejected: insufficient settled cash of $1,300.00 (session 3)",
      "Order for MSFT rejected: insufficient settled cash of $1,020.00 (session 2)",
    ],
    ...overrides,
  };
}

function liveFill(overrides: Partial<LiveFill> = {}): LiveFill {
  return {
    symbol: "NVDA",
    side: "buy",
    quantity: "10",
    price: "191.55",
    quote_price: "191.40",
    quote_ts: "2026-08-28T14:32:07Z",
    notional: "1915.50",
    ...overrides,
  };
}

function autopilotDescription(overrides: Partial<AutopilotDescription> = {}): AutopilotDescription {
  return {
    arm: "full_workflow",
    universe_source: "screen",
    current_card_id: "card-2026-07-01",
    card_adopted_date: "2026-07-01",
    orders_total: 0,
    orders_filled: 0,
    orders_pending: 0,
    orders_rejected: 0,
    last_run_id: null,
    last_run_state: null,
    last_run_at: null,
    last_run_outcome: null,
    exits: "none",
    ...overrides,
  };
}

function autopilotOrder(overrides: Partial<AutopilotOrder> = {}): AutopilotOrder {
  return {
    symbol: "MSFT",
    side: "buy",
    notional: "5000.00",
    decision_date: "2026-08-27",
    fill_date: "2026-08-28",
    regime: "risk_on",
    ...overrides,
  };
}

function desk(overrides: Partial<Desk> = {}): Desk {
  return {
    agent_id: "B-momentum",
    display_name: "B-momentum",
    discipline: "momentum",
    thesis: "Ride established uptrends confirmed by a long-term moving average.",
    kind: "rules",
    universe: ["NVDA", "AMD"],
    entry: "ema(20) crosses_above ema(50) and close > sma(200)",
    exit: "close crosses_below sma(200)",
    rank_by: null,
    stop_loss_pct: "0.12",
    take_profit_pct: null,
    max_hold_days: 180,
    max_positions: 6,
    position_pct: "0.15",
    ladder: null,
    starting_equity: "100000.00",
    cash: "63000.00",
    positions_value: "38200.00",
    equity: "101200.00",
    total_return: "0.0120",
    excess_return: "-0.0003",
    max_drawdown: "0.0210",
    capital_exposure: 0.37,
    realised_pnl: "400.00",
    unrealised_pnl: "800.00",
    open_positions: 2,
    slots_free: 4,
    holdings: [holding()],
    trades: [trade()],
    decisions: [decision()],
    signals: [signal(), signal({ symbol: "AMD", held: false })],
    rejections: [],
    rejection_count: 0,
    live_fills: [],
    live_rejections: [],
    live_as_of: null,
    ...overrides,
  };
}

describe("rejection summary line -- visible without interaction", () => {
  it("renders label, order count, and symbols for an unopened group", () => {
    render(
      <DeskPanel
        desk={desk({
          rejections: [rejection()],
          rejection_count: 8,
        })}
        asOf="2026-08-28"
      />,
    );

    // The exact headline the task brief asks for: "Insufficient settled cash — 8 orders · AAPL, MSFT, NVDA".
    expect(
      screen.getByText("Insufficient settled cash — 8 orders · AAPL, MSFT, NVDA"),
    ).toBeTruthy();

    // role="alert" stays on the summary callout itself -- it now lives inside the card's
    // "Statistics & details" disclosure (see `RejectionsCallout`'s own note about that trade),
    // but the alert semantics and the summary line belong to this element either way.
    const alert = screen.getByRole("alert");
    expect(alert.className).toContain("desk-rejections");
    expect(alert.className).toContain("callout-warn");

    // The total-orders headline uses `rejection_count` (8), not `rejections.length` (1 group).
    expect(screen.getByText(/8 orders the broker refused this session/)).toBeTruthy();
  });

  it("omits the symbol clause when a group's symbols array is empty", () => {
    render(
      <DeskPanel
        desk={desk({
          rejections: [rejection({ symbols: [], count: 3 })],
          rejection_count: 3,
        })}
        asOf="2026-08-28"
      />,
    );

    expect(screen.getByText("Insufficient settled cash — 3 orders")).toBeTruthy();
  });
});

describe("per-order detail -- collapsed until the group is expanded", () => {
  it("keeps the disclosure closed by default, then opens it on click", () => {
    const detailSentence = "Order for AAPL rejected: insufficient settled cash of $1,204.50 (session 8)";
    render(
      <DeskPanel
        desk={desk({
          rejections: [rejection({ detail: [detailSentence] })],
          rejection_count: 8,
        })}
        asOf="2026-08-28"
      />,
    );

    const summary = screen
      .getByText("Insufficient settled cash — 8 orders · AAPL, MSFT, NVDA")
      .closest("summary") as HTMLElement;
    const disclosure = summary.closest("details") as HTMLDetailsElement;

    // Closed by default -- design requirement 2: per-order sentences must not be visible until
    // expanded.
    expect(disclosure.open).toBe(false);

    fireEvent.click(summary);
    expect(disclosure.open).toBe(true);

    // Reachable once expanded.
    expect(screen.getByText(detailSentence)).toBeTruthy();
  });
});

describe("a rule with an empty label falls back to the slug", () => {
  it("renders the machine rule instead of a blank heading, and does not throw", () => {
    expect(() =>
      render(
        <DeskPanel
          desk={desk({
            rejections: [
              rejection({
                rule: "some_new_rule_this_build_has_never_seen",
                label: "",
                count: 1,
                symbols: [],
                detail: ["Order for XOM rejected: some_new_rule_this_build_has_never_seen"],
              }),
            ],
            rejection_count: 1,
          })}
          asOf="2026-08-28"
        />,
      ),
    ).not.toThrow();

    expect(
      screen.getByText("some_new_rule_this_build_has_never_seen — 1 order"),
    ).toBeTruthy();
  });
});

describe("no rejections", () => {
  it("renders no callout when the array is empty", () => {
    render(<DeskPanel desk={desk({ rejections: [], rejection_count: 0 })} asOf="2026-08-28" />);
    expect(document.querySelector(".desk-rejections")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Live execution -- what the desk would trade RIGHT NOW against a real-time quote, distinct from
// the audited historical record (`RecentActivity`, `HoldingsTable`, the trades table).
// ---------------------------------------------------------------------------

describe("live execution -- absent when the feature is off", () => {
  it("renders nothing at all when live_as_of is null, even with live data present", () => {
    render(
      <DeskPanel
        desk={desk({
          live_as_of: null,
          // Should never happen from a well-formed server response, but the panel must key off
          // `live_as_of` alone -- not "trust" a non-empty array when the as-of clock says off.
          live_fills: [liveFill()],
        })}
        asOf="2026-08-28"
      />,
    );
    expect(document.querySelector(".desk-live-section")).toBeNull();
  });

  it("renders nothing when live_as_of is set but nothing qualifies", () => {
    render(
      <DeskPanel
        desk={desk({ live_as_of: "2026-08-28T14:32:07Z", live_fills: [], live_rejections: [] })}
        asOf="2026-08-28"
      />,
    );
    expect(document.querySelector(".desk-live-section")).toBeNull();
  });
});

describe("live execution -- a fill renders", () => {
  it("shows the headline, as-of time, and each fill's symbol, price and quote_price", () => {
    render(
      <DeskPanel
        desk={desk({
          live_as_of: "2026-08-28T14:32:07Z",
          live_fills: [liveFill(), liveFill({ symbol: "AMD", side: "sell", price: "142.10", quote_price: "142.25" })],
        })}
        asOf="2026-08-28"
      />,
    );

    const section = document.querySelector(".desk-live-section");
    expect(section).not.toBeNull();

    // Headline (fill count) is visible without any interaction -- no `<details>` around it.
    expect(screen.getByText(/2 fills at the live quote/)).toBeTruthy();
    // The as-of timestamp says how fresh the projection is.
    expect(screen.getByText(/2026-08-28T14:32:07Z/)).toBeTruthy();
    // It is stated in words that this is not the audited history.
    expect(section?.textContent).toMatch(/not an actual trade/);

    expect(within(section as HTMLElement).getByText("NVDA")).toBeTruthy();
    expect(within(section as HTMLElement).getByText("AMD")).toBeTruthy();
    // Fill price and the unslipped quote price both render so slippage is visible.
    expect(within(section as HTMLElement).getByText("$191.55")).toBeTruthy();
    expect(within(section as HTMLElement).getByText(/\$191\.40/)).toBeTruthy();
    expect(within(section as HTMLElement).getByText("$142.10")).toBeTruthy();
    expect(within(section as HTMLElement).getByText(/\$142\.25/)).toBeTruthy();
  });

  it("does not render a live section confused with the historical activity list", () => {
    render(
      <DeskPanel
        desk={desk({ live_as_of: "2026-08-28T14:32:07Z", live_fills: [liveFill()] })}
        asOf="2026-08-28"
      />,
    );
    const liveSection = document.querySelector(".desk-live-section") as HTMLElement;
    // The live section is its own element, never a `<li>` appended to `.desk-recent-list`.
    expect(liveSection.closest(".desk-recent-section")).toBeNull();
    expect(liveSection.querySelector(".desk-recent-list")).toBeNull();
  });
});

describe("live execution -- rejections reuse RejectionGroup", () => {
  it("renders live_rejections through the same group summary line as the historical callout", () => {
    render(
      <DeskPanel
        desk={desk({
          live_as_of: "2026-08-28T14:32:07Z",
          live_fills: [],
          live_rejections: [rejection({ count: 2, symbols: ["TSLA"] })],
        })}
        asOf="2026-08-28"
      />,
    );

    const section = document.querySelector(".desk-live-section") as HTMLElement;
    expect(section).not.toBeNull();
    expect(
      within(section).getByText("Insufficient settled cash — 2 orders · TSLA"),
    ).toBeTruthy();
  });
});

describe("live execution -- an unrecognised side string", () => {
  it("renders without crashing", () => {
    expect(() =>
      render(
        <DeskPanel
          desk={desk({
            live_as_of: "2026-08-28T14:32:07Z",
            live_fills: [liveFill({ side: "short_cover" })],
          })}
          asOf="2026-08-28"
        />,
      ),
    ).not.toThrow();

    expect(screen.getByText("short_cover")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Autopilot seat -- `kind === "autopilot"`, the workflow-driven book. No `entry`/`exit` rule, no
// `Signal[]` projection (`signals` is always `[]`), and its own provenance block (`autopilot`) plus
// pending orders (`staged_orders`) instead.
// ---------------------------------------------------------------------------

describe("autopilot -- provenance badge and buys-only callout", () => {
  it("renders the arm/universe badge and states plainly that the desk only ever buys", () => {
    renderAutopilotDesk(
      desk({
        kind: "autopilot",
        signals: [],
        autopilot: autopilotDescription({ arm: "full_workflow", universe_source: "screen" }),
      }),
      "2026-08-28",
    );

    // Badge names both halves of the (arm, universe_source) pair, in the reader's own words for the
    // universe source -- not the raw "screen" token. Scoped to the badge itself: `BookStatistics`'
    // own autopilot description block (out of this file's scope fence) also mentions the arm by name
    // in its prose, so an unscoped query would match two elements.
    const badge = document.querySelector(".desk-autopilot-badge") as HTMLElement;
    expect(badge).not.toBeNull();
    expect(badge.textContent).toContain("full_workflow");
    expect(badge.textContent).toContain("screened universe");

    // The single most important fact for reading this seat's return: nothing is ever sold, and the
    // card's stop/target/hold-cap rules never touch these fills.
    expect(screen.getByText("Buy-only desk -- never sells.")).toBeTruthy();
    expect(
      screen.getByText(/stop, target and hold-cap rules never apply here/),
    ).toBeTruthy();
  });

  it("renders a card universe as 'card universe', not the raw token", () => {
    renderAutopilotDesk(
      desk({
        kind: "autopilot",
        signals: [],
        autopilot: autopilotDescription({ universe_source: "card" }),
      }),
      "2026-08-28",
    );
    const badge = document.querySelector(".desk-autopilot-badge") as HTMLElement;
    expect(badge.textContent).toContain("card universe");
  });

  // Regression guard: the buys-only callout must keep rendering, unchanged, for a seat whose
  // selected card genuinely has no exit rule at all -- the strongest statement on the panel and
  // the one case where a reader must not be able to miss it.
  it("still renders the buys-only callout for exits: 'none', and not the exits-policy line", () => {
    renderAutopilotDesk(
      desk({
        kind: "autopilot",
        signals: [],
        autopilot: autopilotDescription({ exits: "none" }),
      }),
      "2026-08-28",
    );

    expect(document.querySelector(".desk-autopilot-buys-only")).not.toBeNull();
    expect(screen.getByText("Buy-only desk -- never sells.")).toBeTruthy();
    expect(document.querySelector(".desk-autopilot-exits-note")).toBeNull();
  });
});

describe("autopilot -- exits now derived from the selected card's real rules", () => {
  it("renders the server's policy sentence and not the buys-only callout", () => {
    const policy =
      "12% stop, 120-session hold cap, and exit rule ema(20) crosses_below ema(50)";
    renderAutopilotDesk(
      desk({
        kind: "autopilot",
        signals: [],
        autopilot: autopilotDescription({ exits: policy }),
      }),
      "2026-08-28",
    );

    // The server's own sentence is quoted verbatim, not re-derived from the card's fields.
    // Scoped to this panel's own note -- `BookStatistics` (a sibling file, out of this file's
    // scope fence) separately surfaces the raw `exits` value in its own provenance block, so an
    // unscoped `screen.getByText` would match twice and fail on that ground alone.
    const note = document.querySelector(".desk-autopilot-exits-note") as HTMLElement;
    expect(note).not.toBeNull();
    expect(within(note).getByText(new RegExp(policy.replace(/[()]/g, "\\$&")))).toBeTruthy();

    // The buys-only warning is specific to `exits === "none"` and must not also appear here --
    // this seat's positions do close, so the strongest statement on the panel would be false.
    expect(document.querySelector(".desk-autopilot-buys-only")).toBeNull();
    expect(screen.queryByText("Buy-only desk -- never sells.")).toBeNull();

    // Informational, not the warning/danger callout treatment -- `.callout`/`.callout-warn` is
    // reserved for something the reader needs to be cautious about, and a desk that closes its
    // own positions per the card's rules is the ordinary case.
    expect(note.className).not.toContain("callout");
  });

  it("degrades an unrecognised or unusual policy string to showing it, without throwing", () => {
    // `exits` is an open string, not a closed union of known policies -- a future rule combination
    // (or a typo'd backend value) must still render rather than crash the panel the way a closed
    // `switch` did once before in this codebase.
    const oddPolicy = "some_new_exit_shape_this_build_has_never_seen(??)";
    expect(() =>
      renderAutopilotDesk(
        desk({
          kind: "autopilot",
          signals: [],
          autopilot: autopilotDescription({ exits: oddPolicy }),
        }),
        "2026-08-28",
      ),
    ).not.toThrow();

    // Scoped to this panel's own note, for the same reason as the test above -- `BookStatistics`
    // surfaces the raw `exits` string too, and an unscoped query would match both.
    const note = document.querySelector(".desk-autopilot-exits-note") as HTMLElement;
    expect(note).not.toBeNull();
    expect(
      within(note).getByText(new RegExp(oddPolicy.replace(/[().?]/g, "\\$&"))),
    ).toBeTruthy();
    expect(document.querySelector(".desk-autopilot-buys-only")).toBeNull();
  });
});

describe("autopilot -- flat seat with no fills", () => {
  it("renders the last-run outcome, not the rules-card 'entry rule has not fired' sentence", () => {
    renderAutopilotDesk(
      desk({
        kind: "autopilot",
        holdings: [],
        trades: [],
        signals: [],
        staged_orders: [],
        autopilot: autopilotDescription({
          last_run_at: "2026-08-28T13:05:00Z",
          last_run_outcome: "no entry candidates fired",
        }),
      }),
      "2026-08-28",
    );

    // The autopilot variant, including the last run's outcome and when it ran.
    expect(screen.getByText(/no staged order has filled/)).toBeTruthy();
    expect(screen.getByText(/no entry candidates fired/)).toBeTruthy();
    // Rendered through `formatInstant`, not raw: the wire value carries microseconds and a `T`
    // separator, and six digits of audit precision between a reader and the minute they wanted is
    // the reason that helper exists. Still UTC, deliberately -- this is a real instant that already
    // carries its zone, and it is compared against the same run's record on the Agent Workflow desk,
    // which is stamped in UTC too. Shifting it to the reader's zone would make two views of one run
    // appear to disagree.
    expect(screen.getByText(/2026-08-28 13:05 UTC/)).toBeTruthy();

    // Never the rules-desk sentence -- this desk has no entry rule to have not fired.
    expect(screen.queryByText(/Its entry rule has not fired/)).toBeNull();
  });

  it("says plainly that no run has been recorded when last_run_outcome is null", () => {
    renderAutopilotDesk(
      desk({
        kind: "autopilot",
        holdings: [],
        trades: [],
        signals: [],
        staged_orders: [],
        autopilot: autopilotDescription({ last_run_at: null, last_run_outcome: null }),
      }),
      "2026-08-28",
    );

    expect(screen.getByText(/No run has been recorded for this seat yet/)).toBeTruthy();
    expect(screen.queryByText(/Its entry rule has not fired/)).toBeNull();
  });
});

describe("autopilot -- staged orders", () => {
  it("renders a table row with symbol, notional and fill date, and is not treated as dormant", () => {
    renderAutopilotDesk(
      desk({
        kind: "autopilot",
        holdings: [],
        trades: [],
        signals: [],
        staged_orders: [
          autopilotOrder({
            symbol: "MSFT",
            notional: "5000.00",
            decision_date: "2026-08-27",
            fill_date: "2026-08-28",
          }),
        ],
        autopilot: autopilotDescription(),
      }),
      "2026-08-28",
    );

    expect(screen.getByText("MSFT")).toBeTruthy();
    expect(screen.getByText("$5,000.00")).toBeTruthy();
    expect(screen.getByText("2026-08-27")).toBeTruthy();
    expect(screen.getByText("2026-08-28")).toBeTruthy();

    // A pending staged order is real activity -- an autopilot desk with one is not dormant even
    // though it has no holdings and no closed trades.
    expect(document.querySelector(".desk-panel-dormant")).toBeNull();
    expect(screen.queryByText(/no trades since inception/)).toBeNull();
  });

  it("does not render the rules-desk 'What it would do next' empty signals block", () => {
    renderAutopilotDesk(
      desk({
        kind: "autopilot",
        signals: [],
        staged_orders: [autopilotOrder()],
        autopilot: autopilotDescription(),
      }),
      "2026-08-28",
    );

    // `UpcomingSignals`' own empty-state placeholder must not appear alongside the staged-orders
    // table for this kind.
    expect(screen.queryByText("No entry or exit signal fired at the last close.")).toBeNull();
    expect(screen.getByText("What it has already committed to")).toBeTruthy();
  });
});

describe("autopilot -- an older server response with no autopilot/staged_orders keys", () => {
  it("renders exactly as a rules desk would -- the regression guard for the optional fields", () => {
    // No `autopilot` and no `staged_orders` override at all -- mirrors a server response that
    // predates this feature and never sends either key.
    render(<DeskPanel desk={desk({ kind: "rules" })} asOf="2026-08-28" />);

    expect(document.querySelector(".desk-autopilot-badge")).toBeNull();
    expect(document.querySelector(".desk-autopilot-buys-only")).toBeNull();
    expect(screen.queryByText("Buy-only desk -- never sells.")).toBeNull();
    expect(screen.getByText("What it would do next")).toBeTruthy();
    expect(screen.queryByText("What it has already committed to")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// The card shape: one bounded body, plus one disclosure holding the long form.
// ---------------------------------------------------------------------------

describe("the desk card's long-form disclosure", () => {
  it("is closed by default and holds the book statistics and live projection, with refusals kept above it", () => {
    render(
      <DeskPanel
        desk={desk({
          rejections: [rejection()],
          rejection_count: 8,
          live_as_of: "2026-08-28T14:32:07Z",
          live_fills: [liveFill()],
        })}
        asOf="2026-08-28"
      />,
    );

    const details = screen.getByTestId("desk-panel-details") as HTMLDetailsElement;
    // Closed on first paint: a reader comparing a row of desks must not pay for this in height.
    // Asserted on the `open` property rather than on visibility -- jsdom does not hide a closed
    // `<details>`'s content the way a real browser does, which is also why the queries below work.
    expect(details.open).toBe(false);
    expect(details.querySelector(".desk-book-stats")).not.toBeNull();
    expect(details.querySelector(".desk-live-section")).not.toBeNull();
    // Broker refusals are a caveat, and this page never hides a caveat behind a click: they render
    // in the card body ABOVE the disclosure, not inside it.
    expect(details.querySelector(".desk-rejections")).toBeNull();
    const body = document.querySelector(".desk-panel-body") as HTMLElement;
    expect(body.querySelector(".desk-rejections")).not.toBeNull();

    fireEvent.click(details.querySelector("summary") as HTMLElement);
    expect(details.open).toBe(true);
    expect(within(details).getByText("Statistics & details")).toBeTruthy();
  });

  it("keeps the acted-on material -- holdings, recent activity, what's next -- out of it", () => {
    render(<DeskPanel desk={desk()} asOf="2026-08-28" />);

    const details = screen.getByTestId("desk-panel-details") as HTMLDetailsElement;
    const body = document.querySelector(".desk-panel-body") as HTMLElement;

    for (const selector of [
      ".desk-panel-headline-tiles",
      ".desk-recent-section",
      ".desk-holdings-table",
      ".desk-upcoming-section",
    ]) {
      const el = body.querySelector(selector);
      expect(el).not.toBeNull();
      expect(details.contains(el)).toBe(false);
    }
  });

  it("renders one scrolling body for the whole card, not one per block", () => {
    render(<DeskPanel desk={desk()} asOf="2026-08-28" />);

    const card = document.querySelector(".desk-panel.card") as HTMLElement;
    const bodies = Array.from(card.children).filter((el) => el.classList.contains("card-body"));
    expect(bodies).toHaveLength(1);
    expect(bodies[0]?.classList.contains("scroll-region")).toBe(true);
    // The holdings and staged-orders tables no longer carry a scroller (or a `.table-wrap`) of
    // their own -- a scroller nested inside a scroller traps the wheel, and the sum of six of them
    // is what made these cards impossible to line up in the first place.
    const holdings = card.querySelector(".desk-holdings-table") as HTMLElement;
    expect(holdings.closest(".scroll-region")).toBe(bodies[0]);
    expect(holdings.closest(".table-wrap")).toBeNull();
  });
});

describe("seat provenance", () => {
  it("renders an owner-seated pill, unlinked", () => {
    render(<DeskPanel desk={desk({ provenance: { source: "owner", generation: null } })} asOf="2026-08-20" />);
    expect(screen.getByText("Owner-selected")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Owner-selected/ })).toBeNull();
  });

  it("renders a promoted pill that links to the Loop view", () => {
    render(
      <MemoryRouter>
        <DeskPanel desk={desk({ provenance: { source: "promoted", generation: 9 } })} asOf="2026-08-20" />
      </MemoryRouter>,
    );
    expect(screen.getByText("Promoted · gen 9")).toBeTruthy();
    const link = screen.getByRole("link", { name: /Promoted · gen 9/ });
    expect(link.getAttribute("href")).toBe("/competition?tab=loop");
  });

  it("shows no provenance pill when the server sends none", () => {
    render(<DeskPanel desk={desk()} asOf="2026-08-20" />);
    expect(screen.queryByText("Owner-selected")).toBeNull();
    expect(screen.queryByText(/^Promoted/)).toBeNull();
  });
});
