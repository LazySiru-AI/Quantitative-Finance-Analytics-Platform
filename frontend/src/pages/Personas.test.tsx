/**
 * /personas (list) page tests.
 *
 * Pins the product guardrails from `docs/INFLUENCER-CONTRACT.md` and the task brief that apply to
 * the *list* page specifically -- the compact per-persona summary row, the add-persona form, and
 * the two page-level cross-persona consensus panels:
 *  - one row renders per digest card the API returns;
 *  - a persona with no notes yet renders its empty-state invitation, not an error and not a
 *    spinner;
 *  - the mutating routes answer `501` today (Phase 1 backend lands in parallel) -- the add-persona
 *    form must show that response's own `detail` text, not a generic failure;
 *  - `grounding.degraded` is always visible, worded as a fact-check failure, never hidden;
 *  - non-empty `warnings` are always rendered, never swallowed;
 *  - each row links onward to `/personas/{slug}`;
 *  - removing a persona from a row calls `DELETE` and refreshes the list, surfacing the server's
 *    own rejection detail on failure;
 *  - the cross-persona watchlist and regime-consensus panels fetch and render, always showing
 *    their own `caveat`.
 *
 * The per-persona detail stack (profile, scorecard, timeline, backtest, ask, strategy card,
 * critique, profile diff, and the full ingest-capable `PersonaCard`) moved to
 * `pages/personas/PersonaDetail.test.tsx` along with this page's old tests for them -- this file no
 * longer wires any of that up, so it has nothing left to assert about it.
 *
 * `@/api/personas` is stubbed at the module boundary, the same seam `PaperDesk.test.tsx`/
 * `Timeframes.test.tsx` use for their own API clients, so these tests are about rendering the
 * contract's rules correctly, not about JSON parsing. `MemoryRouter` wraps every render because
 * this page's compact rows render a react-router `Link` to each persona's detail page.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api/client";
import type { TaskRef } from "@/api/backfill";
import type {
  DigestCard,
  InfluencerWatchlist,
  Persona,
  RegimeConsensus,
} from "@/api/personas";

const cardsMock = vi.fn<() => Promise<DigestCard[]>>();
const createMock = vi.fn<(body: { handle: string; platform?: string }) => Promise<Persona>>();
const removeMock = vi.fn<(slug: string) => Promise<void>>();
const watchlistMock = vi.fn<(options?: unknown) => Promise<InfluencerWatchlist>>();
const regimeMock = vi.fn<() => Promise<RegimeConsensus>>();

vi.mock("@/api/personas", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/personas")>();
  return {
    ...actual,
    personasApi: {
      ...actual.personasApi,
      cards: () => cardsMock(),
      create: (body: { handle: string; platform?: string }) => createMock(body),
      remove: (slug: string) => removeMock(slug),
      watchlist: (options?: unknown) => watchlistMock(options),
      regime: () => regimeMock(),
    },
  };
});

/**
 * The backfill queue, folded in from the former `/backfill` page, is an opt-in panel on this page
 * now -- so this file mounts it too. Its own behaviour has its own test file
 * (`BackfillTasks.test.tsx`); `@/api/backfill` is stubbed here at the same module boundary as the
 * personas client so that the panel resolves deterministically rather than reaching the setup's
 * throwing `fetch` the moment a test opens it.
 */
const listTasksMock = vi.fn<() => Promise<{ tasks: TaskRef[] }>>();

vi.mock("@/api/backfill", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/backfill")>();
  return {
    ...actual,
    backfillApi: { ...actual.backfillApi, listTasks: () => listTasksMock() },
  };
});

const { default: Personas } = await import("@/pages/Personas");

// ---------------------------------------------------------------------------
// Fixtures -- mirror docs/INFLUENCER-CONTRACT.md field for field.
// ---------------------------------------------------------------------------

function persona(overrides: Partial<Persona> = {}): Persona {
  return {
    slug: "creator-a",
    display_name: "Creator A",
    sources: [
      {
        source_id: "yt:UCexample0000000000000000",
        platform: "youtube",
        handle: "@creator-a",
        channel_id: "UCexample0000000000000000",
        url: "https://www.youtube.com/@creator-a",
        enabled: true,
        added_at: "2026-08-01T00:00:00Z",
      },
    ],
    note_count: 3,
    tickers: ["NVDA", "TSLA"],
    profile_version: 0,
    consolidated_at: null,
    created_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

function groundingVerdict(overrides: Partial<DigestCard["grounding"]> = {}): DigestCard["grounding"] {
  return { ok: true, issues: [], attempts: 0, degraded: false, checked_tokens: 0, ...overrides };
}

function digestCard(overrides: Partial<DigestCard> = {}): DigestCard {
  const latestNote = {
    note_id: "vidExample01",
    persona: "creator-a",
    source_id: "yt:UCexample0000000000000000",
    published: "2026-09-01T00:00:00Z",
    ingested_at: "2026-09-01T23:40:00Z",
    url: "https://www.youtube.com/watch?v=vidExample01",
    title: "36 1 September Market Headwinds",
    kind: "video_transcript" as const,
    transcript_source: "auto" as const,
    lang: "ko",
    summary: "They discussed NVDA and TSLA.",
    themes: ["AI capex cycle"],
    quotes: ["some verbatim quote"],
    mentions: [
      {
        symbol: "NVDA",
        stance: "bullish" as const,
        reasoning: "expects continued AI capex",
        instrument: "equity" as const,
        horizon: "unclear" as const,
      },
      {
        symbol: "TSLA",
        stance: "unclear" as const,
        reasoning: "no clear directional call made",
        instrument: "equity" as const,
        horizon: "unclear" as const,
      },
    ],
    path: "influencers/creator-a/notes/2026-09-01-vidExample01.md",
    degraded: false,
  };
  return {
    persona: persona(),
    as_of: "2026-09-01T23:40:00Z",
    window_start: "2026-08-25T00:00:00Z",
    note_count: 3,
    headline: "They are bullish on NVDA and unsure about TSLA.",
    themes: ["AI capex cycle", "Korean retail flows"],
    mentions: latestNote.mentions,
    latest_note: latestNote,
    grounding: groundingVerdict(),
    warnings: [],
    ...overrides,
  };
}

function emptyPersonaCard(overrides: Partial<DigestCard> = {}): DigestCard {
  return digestCard({
    persona: persona({ slug: "freshface", display_name: "Fresh Face", note_count: 0, tickers: [] }),
    as_of: null,
    window_start: null,
    note_count: 0,
    headline: "",
    themes: [],
    mentions: [],
    latest_note: null,
    ...overrides,
  });
}

async function renderPersonas(initialPath = "/personas") {
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Personas />
    </MemoryRouter>,
  );
  // Waits past the "Loading personas…" placeholder before assertions run.
  await waitFor(() => expect(screen.queryByText("Loading personas…")).toBeNull());
}

beforeEach(() => {
  cardsMock.mockReset();
  listTasksMock.mockReset();
  createMock.mockReset();
  removeMock.mockReset();
  watchlistMock.mockReset();
  regimeMock.mockReset();
  // Defaults for the page-level cross-persona panels this page always fetches on mount -- most
  // tests below are not about these panels at all; the dedicated describe block overrides per-case.
  watchlistMock.mockResolvedValue({ as_of: "2026-01-01", entries: [], caveat: "" });
  regimeMock.mockResolvedValue({
    as_of: "2026-01-01",
    personas: [],
    risk_on: 0,
    risk_off: 0,
    mixed: 0,
    caveat: "",
  });
});

describe("loading state (UX-04)", () => {
  it("draws a card-grid skeleton, not a bare line of text, while the list is in flight", async () => {
    // Never settles: the page stays in its loading state for the whole assertion.
    cardsMock.mockReturnValue(new Promise<DigestCard[]>(() => {}));

    render(
      <MemoryRouter>
        <Personas />
      </MemoryRouter>,
    );

    const skeleton = await screen.findByTestId("personas-loading-skeleton");
    // The silhouette itself: several placeholder blocks, laid out where the cards will be.
    expect(skeleton.querySelectorAll(".skeleton-block").length).toBeGreaterThan(1);
    // ...and the same sentence a screen reader used to hear from the bare placeholder, in a polite
    // live region rather than as an unannounced graphic.
    const status = within(skeleton).getByRole("status");
    expect(status.textContent).toBe("Loading personas…");
  });
});

describe("digest rows", () => {
  it("renders one row per persona the API returns", async () => {
    cardsMock.mockResolvedValue([
      digestCard(),
      digestCard({
        persona: persona({ slug: "another-voice", display_name: "Another Voice" }),
      }),
    ]);

    await renderPersonas();

    expect(screen.getByText("Creator A")).toBeTruthy();
    expect(screen.getByText("Another Voice")).toBeTruthy();
    expect(document.querySelectorAll(".persona-list-card").length).toBe(2);
    // The rows now render through the `Card`/`CardGrid` primitive: each row is a `.card-grid` item
    // (equal-height row layout) with exactly one `.scroll-region` for its own scrolling body.
    const grid = document.querySelector(".persona-grid");
    expect(grid?.classList.contains("card-grid")).toBe(true);
    const rows = document.querySelectorAll(".persona-grid > .persona-list-card");
    expect(rows.length).toBe(2);
    for (const row of Array.from(rows)) {
      expect(row.querySelectorAll(".scroll-region").length).toBe(1);
    }
  });

  it("renders the headline, themes and note count for a persona with notes", async () => {
    cardsMock.mockResolvedValue([digestCard()]);

    await renderPersonas();

    expect(screen.getByText("3 notes")).toBeTruthy();
    expect(screen.getByText(/bullish on NVDA and unsure about TSLA/)).toBeTruthy();
    expect(screen.getByText("AI capex cycle")).toBeTruthy();
    expect(screen.getByText("Korean retail flows")).toBeTruthy();
  });
});

describe("a persona with no notes yet", () => {
  it("renders an empty-state invitation, not an error or a spinner", async () => {
    cardsMock.mockResolvedValue([emptyPersonaCard()]);

    await renderPersonas();

    expect(screen.getByText(/No notes ingested yet for Fresh Face/)).toBeTruthy();
    expect(screen.getByText("no notes yet")).toBeTruthy();
    // No stray "0 notes" headline/themes content renders for the empty row.
    const row = document.querySelector(".persona-list-card") as HTMLElement;
    expect(within(row).queryByText(/Their recent take/)).toBeNull();
  });
});

describe("adding a persona", () => {
  it("shows the 501 response's own detail text, not a generic failure", async () => {
    cardsMock.mockResolvedValue([]);
    createMock.mockRejectedValue(
      new ApiRequestError(
        501,
        JSON.stringify({ detail: "Persona creation lands in Phase 1 -- not implemented yet." }),
      ),
    );

    await renderPersonas();

    fireEvent.change(screen.getByPlaceholderText("@creator-a"), {
      target: { value: "@newvoice" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add persona" }));

    expect(
      await screen.findByText("Persona creation lands in Phase 1 -- not implemented yet."),
    ).toBeTruthy();
    expect(createMock).toHaveBeenCalledWith({ handle: "@newvoice", platform: "youtube" });
  });

  it("does not submit a whitespace-only handle", async () => {
    // The native `required` attribute already blocks a truly empty submit before any JS runs;
    // whitespace passes that HTML-level check but must still fail this page's own `.trim()` guard.
    cardsMock.mockResolvedValue([]);
    await renderPersonas();

    fireEvent.change(screen.getByPlaceholderText("@creator-a"), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Add persona" }));

    expect(createMock).not.toHaveBeenCalled();
    expect(screen.getByText("A handle is required.")).toBeTruthy();
  });
});

describe("grounding degraded badge", () => {
  it("shows a fact-check-failed note when card.grounding.degraded is true", async () => {
    cardsMock.mockResolvedValue([digestCard({ grounding: groundingVerdict({ degraded: true, ok: false }) })]);

    await renderPersonas();

    expect(screen.getByText("Fact-check failed.")).toBeTruthy();
    expect(document.querySelector(".persona-list-card-degraded")).not.toBeNull();
    expect(screen.getByText("Unverified")).toBeTruthy();
    expect(document.querySelector(".persona-list-card-degraded .status-pill-warn")).not.toBeNull();
  });

  it("renders no degraded note when grounding.degraded is false", async () => {
    cardsMock.mockResolvedValue([digestCard()]);

    await renderPersonas();

    expect(screen.queryByText("Fact-check failed.")).toBeNull();
  });

  it("does not render the aggregate's non-meaningful fields (attempts/checked_tokens)", async () => {
    // Per the contract amendment, card.grounding is an aggregate: only ok/degraded are meaningful,
    // and issues/attempts/checked_tokens sit at defaults that must never be presented as real
    // measurements (e.g. "0 tokens checked" reading like a genuine figure).
    cardsMock.mockResolvedValue([
      digestCard({ grounding: groundingVerdict({ degraded: true, ok: false, attempts: 0, checked_tokens: 0 }) }),
    ]);

    await renderPersonas();

    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/checked_tokens|tokens checked/i);
    expect(body).not.toMatch(/0 attempts|attempts: 0/i);
  });
});

describe("warnings", () => {
  it("renders non-empty warnings visibly rather than swallowing them", async () => {
    cardsMock.mockResolvedValue([
      digestCard({ warnings: [{ source: "yt:UCexample0000000000000000", reason: "transcript fetch failed for 1 video" }] }),
    ]);

    await renderPersonas();

    expect(screen.getByText(/transcript fetch failed for 1 video/)).toBeTruthy();
  });
});

describe("each row links to its detail page", () => {
  it("links to /personas/{slug} for each persona", async () => {
    cardsMock.mockResolvedValue([
      digestCard(),
      digestCard({ persona: persona({ slug: "another-voice", display_name: "Another Voice" }) }),
    ]);

    await renderPersonas();

    const creatorALink = screen.getByRole("link", { name: /Creator A/ });
    expect(creatorALink.getAttribute("href")).toBe("/personas/creator-a");

    const anotherLink = screen.getByRole("link", { name: /Another Voice/ });
    expect(anotherLink.getAttribute("href")).toBe("/personas/another-voice");
  });
});

describe("removing a persona from the list", () => {
  it("does not call remove on the click -- it opens a confirm sheet naming the persona", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    removeMock.mockResolvedValue(undefined);

    await renderPersonas();

    fireEvent.click(screen.getByRole("button", { name: "Remove persona" }));

    expect(removeMock).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("Remove Creator A?");
    expect(dialog.textContent).toContain("cannot be undone");
  });

  it("calls remove with the slug and refreshes the list once confirmed", async () => {
    cardsMock.mockResolvedValueOnce([digestCard()]);
    cardsMock.mockResolvedValueOnce([]);
    removeMock.mockResolvedValue(undefined);

    await renderPersonas();

    fireEvent.click(screen.getByRole("button", { name: "Remove persona" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, remove" }));

    expect(removeMock).toHaveBeenCalledWith("creator-a");
    expect(
      await screen.findByText("No personas followed yet -- add one above."),
    ).toBeTruthy();
  });

  it("removes nothing when the sheet is cancelled", async () => {
    cardsMock.mockResolvedValue([digestCard()]);

    await renderPersonas();

    fireEvent.click(screen.getByRole("button", { name: "Remove persona" }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    expect(removeMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows the server's rejection detail on a failed removal", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    removeMock.mockRejectedValue(
      new ApiRequestError(500, JSON.stringify({ detail: "Could not remove this one." })),
    );

    await renderPersonas();

    fireEvent.click(screen.getByRole("button", { name: "Remove persona" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, remove" }));

    expect(await screen.findByText("Could not remove this one.")).toBeTruthy();
    // The button returns to its idle, enabled state after the failure.
    expect((screen.getByRole("button", { name: "Remove persona" }) as HTMLButtonElement).disabled).toBe(
      false,
    );
  });
});

describe("page-level cross-persona panels", () => {
  it("fetches and renders the influencer watchlist, always showing its caveat", async () => {
    cardsMock.mockResolvedValue([]);
    watchlistMock.mockResolvedValue({
      as_of: "2026-09-01",
      entries: [
        {
          symbol: "NVDA",
          bullish_count: 2,
          bearish_count: 0,
          personas: ["creator-a", "another-voice"],
          latest_reasoning: "AI capex keeps accelerating.",
          as_of: "2026-09-01",
          instrument: "equity",
        },
      ],
      caveat: "A descriptive reference, never a buy list.",
    });

    await renderPersonas();

    expect(await screen.findByText("Bullish Watchlist")).toBeTruthy();
    expect(watchlistMock).toHaveBeenCalled();
    const nvdaLink = await screen.findByRole("link", { name: /NVDA/ });
    expect(nvdaLink.getAttribute("href")).toBe("/symbol/NVDA");
    expect(screen.getByText("A descriptive reference, never a buy list.")).toBeTruthy();
  });

  it("hands the watchlist its persona display names, so backers are not raw handles (EXP-08)", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    watchlistMock.mockResolvedValue({
      as_of: "2026-09-01",
      entries: [
        {
          symbol: "NVDA",
          bullish_count: 1,
          bearish_count: 0,
          // "creator-a" is in `cards` and resolves; "unknown-handle" is not and stays verbatim.
          personas: ["creator-a", "unknown-handle"],
          latest_reasoning: "AI capex keeps accelerating.",
          as_of: "2026-09-01",
          instrument: "equity",
        },
      ],
      caveat: "A descriptive reference, never a buy list.",
    });

    await renderPersonas();

    const backers = await screen.findByText("Creator A, unknown-handle");
    expect(backers).toBeTruthy();
  });

  it("fetches and renders the regime consensus panel", async () => {
    cardsMock.mockResolvedValue([]);
    regimeMock.mockResolvedValue({
      as_of: "2026-09-01",
      personas: [],
      risk_on: 2,
      risk_off: 1,
      mixed: 0,
      caveat: "A reference input, never a signal.",
    });

    await renderPersonas();

    expect(await screen.findByText("Risk Regime Consensus")).toBeTruthy();
    expect(regimeMock).toHaveBeenCalled();
    expect(screen.getByText("A reference input, never a signal.")).toBeTruthy();
  });
});

describe("the backfill panel", () => {
  it("is closed by default, and fetches no tasks until it is opened", async () => {
    cardsMock.mockResolvedValue([]);

    await renderPersonas();

    expect(screen.queryByTestId("personas-backfill-panel")).toBeNull();
    expect(listTasksMock).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Backfill tasks" }).getAttribute("aria-expanded"),
    ).toBe("false");
  });

  it("opens directly from ?panel=backfill -- the redirect target for the old /backfill route", async () => {
    cardsMock.mockResolvedValue([]);
    listTasksMock.mockResolvedValue({ tasks: [] });

    await renderPersonas("/personas?panel=backfill");

    expect(screen.getByTestId("personas-backfill-panel")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Backfill tasks" }).getAttribute("aria-expanded"),
    ).toBe("true");
    await waitFor(() => expect(listTasksMock).toHaveBeenCalled());
  });

  it("opens and closes from the button beside the heading", async () => {
    cardsMock.mockResolvedValue([]);
    listTasksMock.mockResolvedValue({ tasks: [] });

    await renderPersonas();

    const toggle = screen.getByRole("button", { name: "Backfill tasks" });
    fireEvent.click(toggle);
    expect(screen.getByTestId("personas-backfill-panel")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Backfill tasks" }));
    expect(screen.queryByTestId("personas-backfill-panel")).toBeNull();
  });

  it("keeps exactly one <h1> on the page once the panel is open", async () => {
    // The whole reason `BackfillSection` exists: the page it now sits inside already has a title,
    // and a second `<h1>` in the body is both a document-outline error and the tell that a page got
    // pasted in rather than folded in.
    cardsMock.mockResolvedValue([]);
    listTasksMock.mockResolvedValue({ tasks: [] });

    await renderPersonas("/personas?panel=backfill");

    const h1s = screen.getAllByRole("heading", { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]?.textContent).toBe("Personas");
  });
});
