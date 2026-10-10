/**
 * `/manager` (Phase 1) page tests.
 *
 * What this pins, matching the task's definition of done:
 *  - the not-advice line renders unconditionally -- even while both fetches are still pending, and
 *    even when `agent_available: false` (the key guarantee: the deterministic feed must not depend
 *    on the model layer being up);
 *  - the change feed itself still renders with `agent_available: false`;
 *  - `severity === "attention"` items appear in the attention panel, and only there -- not repeated
 *    in the per-area grid below it, and that panel's heading names the delta it shows (`new since
 *    {since}`) rather than the bare word Overview's own different-question panel already uses;
 *  - each area renders as a `Card` in the shared `CardGrid` (head, expand control, bounded body),
 *    and the two areas no backend rule can produce are not in `AREA_ORDER` at all;
 *  - the header links across to Overview, which holds the standing state this page is the delta on;
 *  - `sections_missing`/`warnings` are always visible, never hidden behind a disclosure;
 *  - `since === null` renders the "activity only, no prior snapshot" note, never a "no changes"
 *    claim, and coexists correctly with a non-empty item list;
 *  - an empty item list renders the empty-state placeholder naming the window and `since`;
 *  - the window toggle refetches `changes` with the new window;
 *  - "Snapshot now" calls the snapshot endpoint, then refetches `changes`.
 *
 * `@/api/manager` is stubbed at the module boundary, same seam as `personas.test.ts`. Every render
 * wraps the page in a `MemoryRouter` because `RefChips` renders real `<Link>`s for `symbol`/`persona`
 * source refs.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  Brief,
  ChangeItem,
  ChangeSet,
  Commission,
  DeskRun,
  ManagerChatThread,
  ManagerChatTurn,
  ManagerConfig,
  ManagerRunSummary,
  SnapshotResult,
} from "@/api/manager";

const configMock = vi.fn<() => Promise<ManagerConfig>>();
const changesMock = vi.fn<(params: { window: string; date?: string }) => Promise<ChangeSet>>();
const snapshotMock = vi.fn<() => Promise<SnapshotResult>>();
const runsMock = vi.fn<() => Promise<{ runs: ManagerRunSummary[] }>>();
const runMock = vi.fn<(id: string) => Promise<DeskRun>>();
const startBriefMock = vi.fn<(body: unknown) => Promise<DeskRun>>();
const cancelRunMock = vi.fn<(id: string) => Promise<DeskRun>>();
const latestBriefMock = vi.fn<() => Promise<Brief>>();
const briefMock = vi.fn<(id: string) => Promise<Brief>>();
const chatsMock = vi.fn<() => Promise<ManagerChatThread[]>>();
const createChatMock = vi.fn<() => Promise<ManagerChatThread>>();
const chatMock = vi.fn<(id: string) => Promise<ManagerChatThread>>();
const deleteChatMock = vi.fn<(id: string) => Promise<void>>();
const sendTurnMock = vi.fn<(id: string, body: unknown) => Promise<ManagerChatTurn>>();
const approveCommissionMock = vi.fn<(id: string) => Promise<Commission>>();
const declineCommissionMock = vi.fn<(id: string) => Promise<Commission>>();

vi.mock("@/api/manager", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/manager")>();
  return {
    ...actual,
    managerApi: {
      config: () => configMock(),
      changes: (params: { window: string; date?: string }) => changesMock(params),
      snapshot: () => snapshotMock(),
      runs: () => runsMock(),
      run: (id: string) => runMock(id),
      startBrief: (body: unknown) => startBriefMock(body),
      cancelRun: (id: string) => cancelRunMock(id),
      latestBrief: () => latestBriefMock(),
      brief: (id: string) => briefMock(id),
      chats: () => chatsMock(),
      createChat: () => createChatMock(),
      chat: (id: string) => chatMock(id),
      deleteChat: (id: string) => deleteChatMock(id),
      sendTurn: (id: string, body: unknown) => sendTurnMock(id, body),
      approveCommission: (id: string) => approveCommissionMock(id),
      declineCommission: (id: string) => declineCommissionMock(id),
    },
  };
});

/** Benign defaults for the layer-C fetches the page fires on mount, so the Phase 1 tests (which only
 * drive config/changes) render without a "not a function"/unhandled-rejection error. Individual
 * layer-C tests override these. */
function _briefFixture(): Brief {
  return {
    brief_id: "brief-1", run_id: "run-1", scope: "owner", window: "yesterday", as_of: "2026-09-09",
    generated_at: "2026-09-09T07:00:00Z", attention: [], changes: changeSet(),
    synthesis: { assessment: [], agreements: [], conflicts: [], risks: [], open_questions: [],
      caveat: "A model's synthesis -- descriptive, not advice." },
    commissions: [], data_health: { stale: [], unknown: [] }, degraded: false,
    grounding: { ok: true, issues: [], attempts: 1, degraded: false, checked_tokens: 1 },
    cost_usd: "0.20", final_md: "",
  };
}

const { default: Manager, AREA_ORDER } = await import("@/pages/Manager");

function managerConfig(overrides: Partial<ManagerConfig> = {}): ManagerConfig {
  return {
    agent_available: true,
    agent_reason: "",
    autonomy: "supervised",
    unattended_kinds: [],
    autopilot_enabled: false,
    brief_time_et: "07:00",
    caps: { brief_usd: "1.00", commission_usd: "0.50", chat_usd: "0.25", daily_usd: "5.00" },
    last_brief_at: null,
    last_snapshot_at: "2026-09-09T07:00:00Z",
    spent_today_usd: "0.42",
    ...overrides,
  };
}

function changeItem(overrides: Partial<ChangeItem> = {}): ChangeItem {
  return {
    id: "chg-1",
    area: "account",
    rule: "balance_delta",
    severity: "fyi",
    headline: "Cash balance rose $500",
    detail: "Deposit posted overnight.",
    as_of: "2026-09-09",
    observed_at: "2026-09-09T07:00:00Z",
    figures: { delta_usd: "500.00" },
    source_refs: [{ kind: "txn", id: "txn-1", label: "Deposit" }],
    ...overrides,
  };
}

function changeSet(overrides: Partial<ChangeSet> = {}): ChangeSet {
  return {
    window: "yesterday",
    since: "2026-09-08T07:00:00Z",
    until: "2026-09-09T07:00:00Z",
    scope: "owner",
    items: [],
    sections_missing: [],
    prior_snapshot: "2026-09-08T07:00:00Z",
    warnings: [],
    ...overrides,
  };
}

function renderManager() {
  render(
    <MemoryRouter>
      <Manager />
    </MemoryRouter>,
  );
}

/** A promise that never settles, for asserting behaviour while a fetch is still in flight. */
function pendingForever<T>(): Promise<T> {
  return new Promise<T>(() => {});
}

beforeEach(() => {
  configMock.mockReset();
  changesMock.mockReset();
  snapshotMock.mockReset();
  // Layer-C fetches the page fires on mount -- benign defaults so Phase 1 tests render cleanly.
  for (const m of [runsMock, runMock, startBriefMock, cancelRunMock, latestBriefMock, briefMock,
    chatsMock, createChatMock, chatMock, deleteChatMock, sendTurnMock, approveCommissionMock,
    declineCommissionMock]) {
    m.mockReset();
  }
  runsMock.mockResolvedValue({ runs: [] });
  chatsMock.mockResolvedValue([]);
  latestBriefMock.mockRejectedValue(new Error("no brief yet"));
});

describe("not-advice line", () => {
  it("renders even while both fetches are still loading", () => {
    configMock.mockReturnValue(pendingForever());
    changesMock.mockReturnValue(pendingForever());

    renderManager();

    expect(screen.getByTestId("manager-not-advice").textContent).toMatch(/not advice/i);
  });

  it("renders, and the change feed still renders, when agent_available is false", async () => {
    configMock.mockResolvedValue(managerConfig({ agent_available: false, agent_reason: "budget exhausted" }));
    changesMock.mockResolvedValue(
      changeSet({ items: [changeItem({ headline: "Realized loss booked on TSLA" })] }),
    );

    renderManager();

    expect(screen.getByTestId("manager-not-advice").textContent).toMatch(/not advice/i);
    expect(await screen.findByText(/model down/i)).toBeTruthy();
    // The key guarantee: the deterministic feed renders regardless.
    expect(await screen.findByText("Realized loss booked on TSLA")).toBeTruthy();
  });
});

describe("attention panel", () => {
  it("shows severity=attention items there, and not repeated in the area grid", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(
      changeSet({
        items: [
          changeItem({
            id: "a1",
            severity: "attention",
            area: "tax",
            headline: "Wash sale window closes today",
          }),
          changeItem({ id: "n1", severity: "notable", area: "account", headline: "Cash rose $500" }),
        ],
      }),
    );

    renderManager();

    expect(await screen.findByText("Wash sale window closes today")).toBeTruthy();
    // Only one occurrence anywhere on the page -- not duplicated into the area grid below.
    expect(screen.getAllByText("Wash sale window closes today")).toHaveLength(1);
    expect(await screen.findByText("Cash rose $500")).toBeTruthy();
  });

  it("shows the empty-attention placeholder when nothing is severity=attention", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(
      changeSet({ items: [changeItem({ severity: "fyi" })] }),
    );

    renderManager();

    expect(await screen.findByText(/nothing needs attention/i)).toBeTruthy();
  });

  // The heading must not be the bare word "Attention": Overview has a panel by that name answering
  // a different question (standing state, not what is new), and the two read as one list.
  it("heads the panel with the delta it shows, naming since", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet({ since: "2026-09-08T07:00:00Z", items: [changeItem()] }));

    renderManager();

    const heading = await screen.findByRole("heading", { name: /new since/i });
    expect(heading.textContent).toContain("2026-09-08T07:00:00Z");
    expect(screen.queryByRole("heading", { name: /^Attention$/ })).toBeNull();
  });

  it("falls back to the window label in the heading when there is no prior snapshot", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet({ since: null, items: [changeItem()] }));

    renderManager();

    const heading = await screen.findByRole("heading", { name: /new since/i });
    expect(heading.textContent).toMatch(/yesterday/i);
  });
});

describe("area cards", () => {
  it("renders each area as an expandable card in the shared grid", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(
      changeSet({
        items: [changeItem({ id: "n1", severity: "notable", area: "tax", headline: "Wash window opened" })],
      }),
    );

    const { container } = render(
      <MemoryRouter>
        <Manager />
      </MemoryRouter>,
    );

    await screen.findByText("Wash window opened");
    const card = container.querySelector('[data-card-id="area-tax"]');
    expect(card).toBeTruthy();
    expect(card?.classList.contains("card-md")).toBe(true);
    // Head and expand control, which the old content-sized `.panel` had neither of.
    expect(card?.querySelector(".card-head")).toBeTruthy();
    expect(within(card as HTMLElement).getByRole("button", { name: /expand/i })).toBeTruthy();
    expect(container.querySelector(".mgr-area-grid")).toBeNull();
  });

  // No rule in `app.manager.rules` emits either area, so a card for them could never have content.
  it("drops the areas no backend rule can produce", () => {
    expect(AREA_ORDER).not.toContain("news");
    expect(AREA_ORDER).not.toContain("activity");
  });

  it("renders no card for an area that is not in the order, even with items for it", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(
      changeSet({
        items: [
          changeItem({ id: "k1", severity: "notable", area: "account", headline: "Cash rose $500" }),
          changeItem({ id: "k2", severity: "notable", area: "news", headline: "Headline that has no rule" }),
        ],
      }),
    );

    renderManager();

    await screen.findByText("Cash rose $500");
    expect(screen.queryByText("Headline that has no rule")).toBeNull();
  });
});

describe("cross-links", () => {
  it("links back to Overview, which holds the standing state this page reports the delta from", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet());

    renderManager();

    const link = await screen.findByRole("link", { name: /standing state/i });
    expect(link.getAttribute("href")).toBe("/overview");
  });
});

describe("gaps", () => {
  it("always shows sections_missing and warnings", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(
      changeSet({
        items: [changeItem()],
        sections_missing: ["persona_traders"],
        warnings: ["Live feed unavailable for 2026-09-08"],
      }),
    );

    renderManager();

    const gaps = await screen.findByTestId("manager-gaps");
    expect(within(gaps).getByText("persona_traders")).toBeTruthy();
    expect(within(gaps).getByText("Live feed unavailable for 2026-09-08")).toBeTruthy();
  });

  it("renders no gaps panel when there is nothing missing and no warnings", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet({ items: [changeItem()] }));

    renderManager();

    await screen.findByText(changeItem().headline);
    expect(screen.queryByTestId("manager-gaps")).toBeNull();
  });
});

describe("since === null", () => {
  it("renders the activity-only note, never a 'no changes' claim, alongside real items", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(
      changeSet({ since: null, items: [changeItem({ headline: "First-ever snapshot recorded" })] }),
    );

    renderManager();

    const note = await screen.findByTestId("manager-since-none");
    expect(note.textContent).toMatch(/no prior snapshot/i);
    expect(note.textContent).not.toMatch(/no changes/i);
    expect(screen.getByText("First-ever snapshot recorded")).toBeTruthy();
    // Not also rendering the empty-state placeholder -- there are items.
    expect(screen.queryByTestId("manager-empty")).toBeNull();
  });
});

describe("empty state", () => {
  it("names the window and since when there are no items at all", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet({ window: "yesterday", since: "2026-09-08T07:00:00Z", items: [] }));

    renderManager();

    const empty = await screen.findByTestId("manager-empty");
    expect(empty.textContent).toMatch(/yesterday/i);
    expect(empty.textContent).toContain("2026-09-08T07:00:00Z");
  });
});

describe("window toggle", () => {
  it("refetches changes with the new window on click", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet());

    renderManager();

    await waitFor(() => expect(changesMock).toHaveBeenCalledWith({ window: "yesterday" }));

    fireEvent.click(screen.getByRole("tab", { name: /week/i }));

    await waitFor(() => expect(changesMock).toHaveBeenCalledWith({ window: "week" }));
  });
});

describe("snapshot now", () => {
  it("calls the snapshot endpoint, then refetches changes", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet());
    snapshotMock.mockResolvedValue({
      as_of: "2026-09-09",
      scope: "owner",
      generated_at: "2026-09-09T12:00:00Z",
    });

    renderManager();

    await waitFor(() => expect(changesMock).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: /snapshot now/i }));

    await waitFor(() => expect(snapshotMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(changesMock).toHaveBeenCalledTimes(2));
  });
});

describe("layer C — brief runner, synthesis, commissions", () => {
  it("disables Run brief when the agent layer is down", async () => {
    configMock.mockResolvedValue(managerConfig({ agent_available: false, agent_reason: "no credential" }));
    changesMock.mockResolvedValue(changeSet());
    render(<MemoryRouter><Manager /></MemoryRouter>);
    const runButton = await screen.findByRole("button", { name: /Run brief/i });
    expect((runButton as HTMLButtonElement).disabled).toBe(true);
  });

  it("renders the brief's synthesis caveat unconditionally once a brief is loaded", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet());
    latestBriefMock.mockResolvedValue(_briefFixture());
    render(<MemoryRouter><Manager /></MemoryRouter>);
    const caveat = await screen.findByTestId("manager-synthesis-caveat");
    expect(caveat.textContent).toMatch(/not advice/i);
  });

  it("shows Approve/Decline on a proposed commission and fires approve on click", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet());
    const brief = _briefFixture();
    latestBriefMock.mockResolvedValue({
      ...brief,
      commissions: [{
        commission_id: "com-9", kind: "persona_chat", params: {}, rationale: "Ask Creator C about MU.",
        budget_usd: "0.05", state: "proposed", child_run_id: null, child_summary: "", source_refs: [],
      }],
    });
    approveCommissionMock.mockResolvedValue({
      commission_id: "com-9", kind: "persona_chat", params: {}, rationale: "Ask Creator C about MU.",
      budget_usd: "0.05", state: "approved", child_run_id: null, child_summary: "", source_refs: [],
    });
    render(<MemoryRouter><Manager /></MemoryRouter>);
    const approve = await screen.findByRole("button", { name: /Approve/i });
    fireEvent.click(approve);
    await waitFor(() => expect(approveCommissionMock).toHaveBeenCalledWith("com-9"));
  });
});

describe("no raw internals on screen (UX-05)", () => {
  it("labels data-health source keys instead of printing the wire names", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet());
    latestBriefMock.mockResolvedValue({
      ..._briefFixture(),
      data_health: {
        stale: ["macro_snapshot", "calendar_events"],
        // `sweep:refresh` is the manager's own id on top of the freshness catalog; `brand_new_feed`
        // is a key this build has never seen -- it must humanise, not throw and not render raw.
        unknown: ["fundamentals_edgar", "news", "sweep:refresh", "brand_new_feed"],
      },
    });

    renderManager();

    const health = await screen.findByTestId("manager-data-health");
    expect(health.textContent).toContain("Macro snapshot");
    expect(health.textContent).toContain("Calendar events");
    expect(health.textContent).toContain("Fundamentals (EDGAR)");
    expect(health.textContent).toContain("Refresh sweep");
    expect(health.textContent).toContain("Brand new feed");
    expect(health.textContent).not.toContain("macro_snapshot");
    expect(health.textContent).not.toContain("calendar_events");
    expect(health.textContent).not.toContain("fundamentals_edgar");
  });

  it("renders a change row's unpriced count as a sentence, not as a variable name", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(
      changeSet({
        items: [
          changeItem({
            headline: "Equity is a partial figure",
            figures: { unpriced_count: "3", weight_pct: "0.041" },
          }),
        ],
      }),
    );

    renderManager();

    expect(await screen.findByText("3 position(s) unpriced")).toBeTruthy();
    expect(screen.getByText("Weight %: 0.041")).toBeTruthy();
    expect(screen.queryByText(/unpriced_count/)).toBeNull();
    expect(screen.queryByText(/weight_pct/)).toBeNull();
  });

  it("reduces a failed commission to one line and hides its payload, session id stripped", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet());
    const brief = _briefFixture();
    latestBriefMock.mockResolvedValue({
      ...brief,
      commissions: [
        {
          commission_id: "com-7",
          kind: "workflow",
          params: {},
          rationale: "Check the regime call against the desk.",
          budget_usd: "0.05",
          state: "failed",
          child_run_id: null,
          child_summary:
            '{"error": "rate limited by the provider", "session_id": "sess_9f3a2b71c4", '
            + '"req_8812aa9f01": true, "trace": "at app.workflow.run',
          source_refs: [],
        },
      ],
    });

    renderManager();

    const failure = await screen.findByTestId("manager-commission-failure");
    // The one line a reader can act on, in the always-visible summary.
    const summary = failure.querySelector("summary");
    expect(summary?.textContent).toContain("Commission failed: rate limited by the provider");
    // The payload is kept, not deleted -- but no session/request id survives into either half.
    expect(failure.textContent).toContain("at app.workflow.run");
    expect(failure.textContent).not.toContain("sess_9f3a2b71c4");
    expect(failure.textContent).not.toContain("req_8812aa9f01");
  });

  it("still renders a non-failed commission's child summary plainly", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet());
    const brief = _briefFixture();
    latestBriefMock.mockResolvedValue({
      ...brief,
      commissions: [
        {
          commission_id: "com-8",
          kind: "workflow",
          params: {},
          rationale: "Check the regime call against the desk.",
          budget_usd: "0.05",
          state: "succeeded",
          child_run_id: "run-3",
          child_summary: "The desk agreed with the brief on two of three names.",
          source_refs: [],
        },
      ],
    });

    renderManager();

    expect(
      await screen.findByText("The desk agreed with the brief on two of three names."),
    ).toBeTruthy();
    expect(screen.queryByTestId("manager-commission-failure")).toBeNull();
  });
});

describe("brief snapshot date (UX-03)", () => {
  it("stamps the brief's own as_of beside its figures", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet());
    latestBriefMock.mockResolvedValue({ ..._briefFixture(), as_of: "2026-09-08" });

    renderManager();

    const stamp = await screen.findByTestId("manager-brief-asof");
    // The snapshot's own date, not the time the model wrote about it -- the whole point is that
    // this can be older than the live Tax/Wash Sales pages.
    expect(stamp.textContent).toBe("As of 2026-09-08");
  });
});

describe("synthesis density", () => {
  const longParagraph = (n: number) => `Paragraph ${n}. ${"x".repeat(210)}`;

  it("keeps the first paragraph visible and folds the rest behind Read more", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet());
    const brief = _briefFixture();
    latestBriefMock.mockResolvedValue({
      ...brief,
      synthesis: {
        ...brief.synthesis,
        assessment: [1, 2, 3].map((n) => ({ text: longParagraph(n), source_refs: [] })),
      },
    });

    renderManager();

    const more = await screen.findByTestId("manager-synthesis-more");
    expect(more.textContent).toContain("Read more");
    // Nothing is deleted -- paragraphs two and three are in the DOM, inside the disclosure.
    expect(within(more).getByText(longParagraph(2))).toBeTruthy();
    expect(within(more).getByText(longParagraph(3))).toBeTruthy();
    // ...and the first one is not.
    expect(within(more).queryByText(longParagraph(1))).toBeNull();
    expect(screen.getByText(longParagraph(1))).toBeTruthy();
    // The caveat is never folded away (COPY-STYLE rule 6).
    const caveat = screen.getByTestId("manager-synthesis-caveat");
    expect(caveat.textContent).toMatch(/not advice/i);
    expect(more.contains(caveat)).toBe(false);
  });

  it("leaves a short group whole -- there is no wall to fold", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet());
    const brief = _briefFixture();
    latestBriefMock.mockResolvedValue({
      ...brief,
      synthesis: {
        ...brief.synthesis,
        risks: [
          { text: "Concentration is up.", source_refs: [] },
          { text: "One name carries the book.", source_refs: [] },
        ],
      },
    });

    renderManager();

    expect(await screen.findByText("One name carries the book.")).toBeTruthy();
    expect(screen.queryByTestId("manager-synthesis-more")).toBeNull();
  });
});

describe("data-egress notice (EXP-04)", () => {
  it("names what leaves this machine, in the header, without opening anything", async () => {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet());

    renderManager();

    const note = await screen.findByTestId("manager-egress");
    expect(note.textContent).toContain("sent to the model provider");
    expect(note.textContent).toMatch(/account, tax and activity figures/i);
  });

  it("still renders when the config fetch fails -- egress is not conditional on it", async () => {
    configMock.mockRejectedValue(new Error("config is down"));
    changesMock.mockResolvedValue(changeSet());

    renderManager();

    const note = await screen.findByTestId("manager-egress");
    expect(note.textContent).toContain("sent to the model provider");
  });
});

describe("chat thread deletion (EXP-24)", () => {
  const thread: ManagerChatThread = {
    thread_id: "th-1",
    title: "Tax questions",
    created_at: "2026-09-09T07:00:00Z",
    updated_at: "2026-09-09T07:05:00Z",
    turn_count: 0,
    spent_usd: "0.00",
    turns: [],
  };

  async function openThread() {
    configMock.mockResolvedValue(managerConfig());
    changesMock.mockResolvedValue(changeSet());
    chatsMock.mockResolvedValue([thread]);
    chatMock.mockResolvedValue(thread);

    renderManager();

    const select = await screen.findByLabelText("Thread");
    fireEvent.change(select, { target: { value: "th-1" } });
    return await screen.findByRole("button", { name: "Delete thread" });
  }

  it("does not delete on the click -- it opens a confirm sheet", async () => {
    deleteChatMock.mockResolvedValue(undefined);

    fireEvent.click(await openThread());

    expect(deleteChatMock).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("Delete this thread?");
    expect(dialog.textContent).toContain("cannot be undone");
  });

  it("deletes once the sheet is confirmed", async () => {
    deleteChatMock.mockResolvedValue(undefined);

    fireEvent.click(await openThread());
    fireEvent.click(screen.getByRole("button", { name: "Yes, delete" }));

    await waitFor(() => expect(deleteChatMock).toHaveBeenCalledWith("th-1"));
  });

  it("deletes nothing when the sheet is cancelled", async () => {
    deleteChatMock.mockResolvedValue(undefined);

    fireEvent.click(await openThread());
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    expect(deleteChatMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
