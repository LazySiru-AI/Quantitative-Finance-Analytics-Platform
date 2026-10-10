/**
 * /personas/:slug (detail) page tests.
 *
 * Split out of the old monolithic `pages/Personas.test.tsx` when that page's nine-panel-per-persona
 * stack moved to this route (see `PersonaDetail.tsx`'s own docstring). Everything here that used to
 * assert against the list page's rendering of a single persona's full panel stack now asserts
 * against this route instead -- same fixtures, same guardrails, same contract
 * (`docs/INFLUENCER-CONTRACT.md`), just reached via `/personas/{slug}` rather than inline on the
 * list:
 *  - each ticker mention/thesis/call-score symbol links to `/symbol/{symbol}`, honestly labelling
 *    `unclear` as "no clear stance", never folded into "neutral";
 *  - the ingest panel offers three mutually-exclusive request shapes (`{limit}`, `{video_urls}`,
 *    `{drop}}`), never submits an empty `video_urls` list or a `drop` missing `text`, and always
 *    surfaces the server's own rejection detail -- including a 422 and a 409 -- rather than a
 *    generic failure;
 *  - (Phase 2) a consolidated profile renders with every claim's citations visible, a never-
 *    consolidated persona (`GET /profile` -> `404`) renders the empty state rather than an error, a
 *    `degraded` profile shows its fact-check-failed badge, the Consolidate button shows a pending
 *    state and disables itself in flight, a rejection's `detail` renders verbatim;
 *  - (Phase 3a) the scorecard aggregate renders hit rate and median return, `null` fields render as
 *    "not enough" copy rather than as `0`, per-call badges and `return_pct` colouring are correct,
 *    and `GET /scorecard` answering `404` renders as a genuine error (unlike the profile fetch's
 *    `404`, which is an empty state);
 *  - (Phase 6/7) timeline, backtest, ask, strategy-card drafting, critique and profile-diff panels
 *    each fetch, render, and surface a visible `role=alert` on rejection.
 *
 * New to this file (not carried over): a slug with no matching digest card renders a "not found"
 * state with a link back to `/personas`, rather than indexing into `undefined`.
 *
 * `@/api/personas` is stubbed at the module boundary, same seam as the list page's own test file.
 * Every render wraps the route in a real two-route `<Routes>` inside a `MemoryRouter` (rather than
 * just rendering `<PersonaDetail />` bare) so `useParams` resolves a real `:slug` and the "back to
 * personas" link has a real destination to prove it points at.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api/client";
import type {
  CallScore,
  CardCritique,
  ChatContext,
  ChatThread,
  ChatTurn,
  DigestCard,
  EpisodicNote,
  IngestJob,
  Persona,
  PersonaBacktest,
  PersonaProfile,
  PersonaScorecard,
  PersonaTimeline as PersonaTimelineWire,
  ProfileDiff,
  SavedStrategyDraft,
  StrategyCardDraft,
  TickerThesis,
} from "@/api/personas";

const cardsMock = vi.fn<() => Promise<DigestCard[]>>();
const removeMock = vi.fn<(slug: string) => Promise<void>>();
const startIngestMock = vi.fn<(slug: string, body: unknown) => Promise<IngestJob>>();
const getIngestJobMock = vi.fn<(slug: string, jobId: string) => Promise<IngestJob>>();
const getProfileMock = vi.fn<(slug: string) => Promise<PersonaProfile>>();
const thesesMock = vi.fn<(slug: string) => Promise<TickerThesis[]>>();
const consolidateMock = vi.fn<(slug: string) => Promise<PersonaProfile>>();
const scorecardMock = vi.fn<(slug: string) => Promise<PersonaScorecard>>();
const timelineMock = vi.fn<(slug: string) => Promise<PersonaTimelineWire>>();
const backtestMock = vi.fn<(slug: string) => Promise<PersonaBacktest>>();
const strategyCardMock = vi.fn<(slug: string) => Promise<StrategyCardDraft>>();
const strategyCardsMock = vi.fn<(slug: string) => Promise<SavedStrategyDraft[]>>();
const critiqueMock = vi.fn<(slug: string, body: unknown) => Promise<CardCritique>>();
const profileDiffMock = vi.fn<(slug: string, options: unknown) => Promise<ProfileDiff>>();
const chatsMock = vi.fn<(slug: string) => Promise<ChatThread[]>>();
const createChatMock = vi.fn<(slug: string) => Promise<ChatThread>>();
const chatMock = vi.fn<(slug: string, threadId: string) => Promise<ChatThread>>();
const deleteChatMock = vi.fn<(slug: string, threadId: string) => Promise<void>>();
const sendTurnMock = vi.fn<(slug: string, threadId: string, body: unknown) => Promise<ChatTurn>>();
const chatContextMock = vi.fn<(slug: string) => Promise<ChatContext>>();

vi.mock("@/api/personas", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/personas")>();
  return {
    ...actual,
    personasApi: {
      ...actual.personasApi,
      cards: () => cardsMock(),
      remove: (slug: string) => removeMock(slug),
      startIngest: (slug: string, body: unknown) => startIngestMock(slug, body),
      getIngestJob: (slug: string, jobId: string) => getIngestJobMock(slug, jobId),
      getProfile: (slug: string) => getProfileMock(slug),
      theses: (slug: string) => thesesMock(slug),
      consolidate: (slug: string) => consolidateMock(slug),
      scorecard: (slug: string) => scorecardMock(slug),
      timeline: (slug: string) => timelineMock(slug),
      backtest: (slug: string) => backtestMock(slug),
      strategyCard: (slug: string) => strategyCardMock(slug),
      strategyCards: (slug: string) => strategyCardsMock(slug),
      critique: (slug: string, body: unknown) => critiqueMock(slug, body),
      profileDiff: (slug: string, options: unknown) => profileDiffMock(slug, options),
      chats: (slug: string) => chatsMock(slug),
      createChat: (slug: string) => createChatMock(slug),
      chat: (slug: string, threadId: string) => chatMock(slug, threadId),
      deleteChat: (slug: string, threadId: string) => deleteChatMock(slug, threadId),
      sendTurn: (slug: string, threadId: string, body: unknown) => sendTurnMock(slug, threadId, body),
      chatContext: (slug: string) => chatContextMock(slug),
    },
  };
});

const { default: PersonaDetail } = await import("@/pages/personas/PersonaDetail");

// ---------------------------------------------------------------------------
// Fixtures -- mirror docs/INFLUENCER-CONTRACT.md field for field. Same shapes the list page's own
// test file uses for the digest card; duplicated here (rather than shared) since the two test files
// stub disjoint slices of `@/api/personas` and have no other reason to import from each other.
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

function episodicNote(overrides: Partial<EpisodicNote> = {}): EpisodicNote {
  return {
    note_id: "vidExample01",
    persona: "creator-a",
    source_id: "yt:UCexample0000000000000000",
    published: "2026-09-01T00:00:00Z",
    ingested_at: "2026-09-01T23:40:00Z",
    url: "https://www.youtube.com/watch?v=vidExample01",
    title: "36 1 September Market Headwinds",
    kind: "video_transcript",
    transcript_source: "auto",
    lang: "ko",
    summary: "They discussed NVDA and TSLA.",
    themes: ["AI capex cycle"],
    quotes: ["some verbatim quote"],
    mentions: [
      {
        symbol: "NVDA",
        stance: "bullish",
        reasoning: "expects continued AI capex",
        instrument: "equity",
        horizon: "unclear",
      },
      {
        symbol: "TSLA",
        stance: "unclear",
        reasoning: "no clear directional call made",
        instrument: "equity",
        horizon: "unclear",
      },
    ],
    path: "influencers/creator-a/notes/2026-09-01-vidExample01.md",
    degraded: false,
    ...overrides,
  };
}

function groundingVerdict(overrides: Partial<DigestCard["grounding"]> = {}): DigestCard["grounding"] {
  return { ok: true, issues: [], attempts: 0, degraded: false, checked_tokens: 0, ...overrides };
}

function digestCard(overrides: Partial<DigestCard> = {}): DigestCard {
  const latestNote = episodicNote();
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

function personaProfile(overrides: Partial<PersonaProfile> = {}): PersonaProfile {
  return {
    persona: "creator-a",
    version: 1,
    consolidated_at: "2026-09-01T00:00:00Z",
    note_count: 3,
    summary: "A Korean retail-focused investor who trades AI capex themes.",
    beliefs: [
      { text: "AI capex spending keeps accelerating into next year.", citations: ["vidExample01"] },
    ],
    playbook: [
      { text: "Scales into positions on pullbacks rather than chasing breakouts.", citations: ["vidExample01", "otherNoteId1"] },
    ],
    methodology: [],
    regime: null,
    vocabulary: ["capex cycle", "물타기"],
    degraded: false,
    path: "influencers/creator-a/profile.md",
    ...overrides,
  };
}

function tickerThesis(overrides: Partial<TickerThesis> = {}): TickerThesis {
  return {
    persona: "creator-a",
    symbol: "NVDA",
    stance: "bullish",
    updated_at: "2026-09-01T00:00:00Z",
    claims: [{ text: "Expects continued AI capex tailwinds for NVDA.", citations: ["vidExample01"] }],
    path: "influencers/creator-a/theses/NVDA.md",
    ...overrides,
  };
}

function callScore(overrides: Partial<CallScore> = {}): CallScore {
  return {
    symbol: "NVDA",
    stance: "bullish",
    note_id: "vidExample01",
    said_on: "2026-08-01T00:00:00Z",
    entry_date: "2026-08-03T00:00:00Z",
    entry_price: 100,
    latest_date: "2026-09-01T00:00:00Z",
    latest_price: 104.32,
    return_pct: 4.32,
    basis: "adjusted",
    outcome: "played_out",
    horizons: [],
    ...overrides,
  };
}

function personaScorecard(overrides: Partial<PersonaScorecard> = {}): PersonaScorecard {
  return {
    persona: "creator-a",
    as_of: "2026-09-01T00:00:00Z",
    scored_calls: [callScore()],
    directional_count: 1,
    played_out: 1,
    hit_rate: 1,
    median_return_pct: 4.32,
    hit_rate_ci: null,
    horizon_stats: [],
    warnings: [],
    ...overrides,
  };
}

function chatThread(overrides: Partial<ChatThread> = {}): ChatThread {
  return {
    thread_id: "thread-1",
    persona: "creator-a",
    title: "",
    created_at: "2026-09-05T00:00:00Z",
    updated_at: "2026-09-05T00:00:00Z",
    turn_count: 0,
    spent_usd: "0.00",
    turns: [],
    ...overrides,
  };
}

function chatTurn(overrides: Partial<ChatTurn> = {}): ChatTurn {
  return {
    turn_id: "turn-1",
    asked_at: "2026-09-05T00:01:00Z",
    question: "What do you think of NVDA?",
    symbol: null,
    lang: "en",
    answer: "They remain bullish on continued AI capex.",
    citations: ["vidExample01"],
    retrieved: ["vidExample01"],
    stance: null,
    grounding: { ok: true, issues: [], attempts: 1, degraded: false, checked_tokens: 10 },
    degraded: false,
    cost_usd: "0.01",
    ...overrides,
  };
}

function chatContext(overrides: Partial<ChatContext> = {}): ChatContext {
  return { profile_version: 1, profile_note_count: 3, note_count: 3, stale: false, ...overrides };
}

function ingestJob(overrides: Partial<IngestJob> = {}): IngestJob {
  return {
    job_id: "job-1",
    persona: "creator-a",
    state: "running",
    items_total: 5,
    items_done: 0,
    items_failed: 0,
    started_at: "2026-09-01T23:41:00Z",
    finished_at: null,
    spent_usd: "0.00",
    error: null,
    ...overrides,
  };
}

async function renderDetail(slug: string) {
  render(
    <MemoryRouter initialEntries={[`/personas/${slug}`]}>
      <Routes>
        <Route path="/personas" element={<div data-testid="personas-list-stub">Personas list</div>} />
        <Route path="/personas/:slug" element={<PersonaDetail />} />
      </Routes>
    </MemoryRouter>,
  );
  // Waits past the "Loading personas…" placeholder before assertions run.
  await waitFor(() => expect(screen.queryByText("Loading personas…")).toBeNull());
}

beforeEach(() => {
  cardsMock.mockReset();
  removeMock.mockReset();
  startIngestMock.mockReset();
  getIngestJobMock.mockReset();
  getProfileMock.mockReset();
  thesesMock.mockReset();
  consolidateMock.mockReset();
  scorecardMock.mockReset();
  timelineMock.mockReset();
  backtestMock.mockReset();
  strategyCardMock.mockReset();
  strategyCardsMock.mockReset();
  critiqueMock.mockReset();
  profileDiffMock.mockReset();
  chatsMock.mockReset();
  createChatMock.mockReset();
  chatMock.mockReset();
  deleteChatMock.mockReset();
  sendTurnMock.mockReset();
  chatContextMock.mockReset();
  // Default: the persona reads as "never consolidated yet" with no theses, matching a fresh
  // Phase 1-only deployment -- individual tests below override this per-case.
  getProfileMock.mockRejectedValue(new ApiRequestError(404, JSON.stringify({ detail: "Not consolidated yet." })));
  thesesMock.mockResolvedValue([]);
  // Default: an empty scorecard (the ordinary "no dated calls yet" state) -- individual tests below
  // override this per-case.
  scorecardMock.mockResolvedValue(
    personaScorecard({ scored_calls: [], directional_count: 0, played_out: 0, hit_rate: null, median_return_pct: null }),
  );
  // Defaults for the Phase 6/7 panels this route also wires in -- minimal valid empty shapes, since
  // most tests below are not about these panels at all; individual tests override per-case.
  timelineMock.mockResolvedValue({ persona: "creator-a", entries: [], stance_timelines: [] });
  backtestMock.mockResolvedValue({
    persona: "creator-a",
    as_of: "2026-01-01",
    benchmark: "SPY",
    call_count: 0,
    horizons: [],
    caveat: "",
    warnings: [],
  });
  strategyCardsMock.mockResolvedValue([]);
  // Defaults for the Phase 9 chat panel this route also wires in -- no threads yet, and a current
  // (non-stale) profile so the stale-profile note does not render by default; individual tests below
  // override per-case.
  chatsMock.mockResolvedValue([]);
  chatContextMock.mockResolvedValue(chatContext());
});

describe("a slug with no matching persona", () => {
  it("renders a not-found state with a link back to /personas, not a crash", async () => {
    cardsMock.mockResolvedValue([digestCard()]);

    await renderDetail("no-such-persona");

    expect(await screen.findByText("Persona not found")).toBeTruthy();
    expect(screen.getByText(/no-such-persona/)).toBeTruthy();
    const backLink = screen.getByRole("link", { name: /Back to personas/ });
    expect(backLink.getAttribute("href")).toBe("/personas");
  });
});

describe("page heading and framing (A11Y-02 / UX-14)", () => {
  it("names the persona in the page's single h1", async () => {
    cardsMock.mockResolvedValue([digestCard()]);

    await renderDetail("creator-a");

    const h1s = screen.getAllByRole("heading", { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]?.textContent).toBe("Creator A");
  });

  it("shows a NOT ADVICE pill above the panels that state bullish/bearish calls", async () => {
    cardsMock.mockResolvedValue([digestCard()]);

    await renderDetail("creator-a");

    // "Not advice" in the DOM; `StatusPill`'s own CSS is what uppercases it on screen.
    const pill = screen.getByText("Not advice");
    expect(pill).toBeTruthy();
    // Above the calls, not buried under them: the pill precedes the first ticker chip in document
    // order, which is what "read this before you read those" means in a linear reading of the page.
    const nvda = screen.getByRole("link", { name: /NVDA/ });
    // `compareDocumentPosition` returns a bitmask; FOLLOWING means `nvda` comes after `pill`.
    expect(pill.compareDocumentPosition(nvda) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("the persona's own digest card", () => {
  it("renders the headline, themes, note count and a back link", async () => {
    cardsMock.mockResolvedValue([digestCard()]);

    await renderDetail("creator-a");

    // The name appears twice by design (A11Y-02): once as the page's own `<h1>`, once as the
    // digest card's `<h2>` -- a page heading plus the panel's heading one level below it, not a
    // duplicate. Queried by role so the outline itself is what is pinned.
    expect(screen.getByRole("heading", { level: 1, name: "Creator A" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Creator A" })).toBeTruthy();
    expect(screen.getByText("3 notes")).toBeTruthy();
    expect(screen.getByText(/bullish on NVDA and unsure about TSLA/)).toBeTruthy();
    const backLink = screen.getByRole("link", { name: /Back to personas/ });
    expect(backLink.getAttribute("href")).toBe("/personas");
  });
});

describe("ticker chips", () => {
  it("link to /symbol/{symbol} and show the influencer's stance, honestly labelling 'unclear'", async () => {
    cardsMock.mockResolvedValue([digestCard()]);

    await renderDetail("creator-a");

    const nvdaLink = screen.getByRole("link", { name: /NVDA/ });
    expect(nvdaLink.getAttribute("href")).toBe("/symbol/NVDA");
    expect(within(nvdaLink as HTMLElement).getByText("bullish")).toBeTruthy();

    const tslaLink = screen.getByRole("link", { name: /TSLA/ });
    expect(tslaLink.getAttribute("href")).toBe("/symbol/TSLA");
    // unclear must read as "no clear stance", never silently folded into "neutral".
    expect(within(tslaLink as HTMLElement).getByText("no clear stance")).toBeTruthy();
    expect(within(tslaLink as HTMLElement).queryByText("neutral")).toBeNull();
  });
});

describe("starting an ingest -- recent videos (default mode)", () => {
  it("defaults to a 20-video backfill and polls until the job settles", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    startIngestMock.mockResolvedValue(ingestJob());
    getIngestJobMock.mockResolvedValue(
      ingestJob({ state: "succeeded", items_done: 5, finished_at: "2026-09-01T23:42:00Z", spent_usd: "0.42" }),
    );

    await renderDetail("creator-a");

    fireEvent.click(screen.getByRole("button", { name: "Start ingest" }));

    expect(await screen.findByRole("button", { name: "Ingesting…" })).toBeTruthy();
    expect(startIngestMock).toHaveBeenCalledWith("creator-a", { limit: 20 });

    await waitFor(() => expect(getIngestJobMock).toHaveBeenCalled(), { timeout: 3000 });
    // Once the job settles, the button returns to its idle label.
    await waitFor(
      () => expect(screen.queryByRole("button", { name: "Ingesting…" })).toBeNull(),
      { timeout: 3000 },
    );
  });

  it("clamps a custom limit into the server's 1..50 range", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    startIngestMock.mockResolvedValue(ingestJob());

    await renderDetail("creator-a");

    const limitInput = screen.getByLabelText("How many recent videos") as HTMLInputElement;
    fireEvent.change(limitInput, { target: { value: "500" } });
    fireEvent.click(screen.getByRole("button", { name: "Start ingest" }));

    expect(startIngestMock).toHaveBeenCalledWith("creator-a", { limit: 50 });
  });

  it("shows the server's 409 detail when an ingest is already running for this persona", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    startIngestMock.mockRejectedValue(
      new ApiRequestError(
        409,
        JSON.stringify({ detail: "An ingest is already running for creator-a." }),
      ),
    );

    await renderDetail("creator-a");
    fireEvent.click(screen.getByRole("button", { name: "Start ingest" }));

    expect(await screen.findByText("An ingest is already running for creator-a.")).toBeTruthy();
  });
});

describe("starting an ingest -- specific videos", () => {
  it("sends parsed, blank-line-filtered video_urls", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    startIngestMock.mockResolvedValue(ingestJob({ items_total: 2 }));

    await renderDetail("creator-a");

    fireEvent.click(screen.getByRole("tab", { name: "Specific videos" }));
    fireEvent.change(screen.getByLabelText("Video URLs or ids, one per line"), {
      target: { value: "https://youtu.be/dQw4w9WgXcQ\n\n   vidExample01   \n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start ingest" }));

    expect(startIngestMock).toHaveBeenCalledWith("creator-a", {
      video_urls: ["https://youtu.be/dQw4w9WgXcQ", "vidExample01"],
    });
  });

  it("disables submit when only blank lines have been entered", async () => {
    cardsMock.mockResolvedValue([digestCard()]);

    await renderDetail("creator-a");

    fireEvent.click(screen.getByRole("tab", { name: "Specific videos" }));
    fireEvent.change(screen.getByLabelText("Video URLs or ids, one per line"), {
      target: { value: "   \n\n" },
    });

    expect((screen.getByRole("button", { name: "Start ingest" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(startIngestMock).not.toHaveBeenCalled();
  });

  it("shows the server's 422 detail naming the video url it could not resolve", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    startIngestMock.mockRejectedValue(
      new ApiRequestError(
        422,
        JSON.stringify({ detail: "Could not read a video id from 'not-a-real-url'." }),
      ),
    );

    await renderDetail("creator-a");

    fireEvent.click(screen.getByRole("tab", { name: "Specific videos" }));
    fireEvent.change(screen.getByLabelText("Video URLs or ids, one per line"), {
      target: { value: "not-a-real-url" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start ingest" }));

    expect(await screen.findByText("Could not read a video id from 'not-a-real-url'.")).toBeTruthy();
  });
});

describe("starting an ingest -- paste text (drop)", () => {
  it("disables submit while the text is empty, even with a title and url filled in", async () => {
    cardsMock.mockResolvedValue([digestCard()]);

    await renderDetail("creator-a");

    fireEvent.click(screen.getByRole("tab", { name: "Paste text" }));
    fireEvent.change(screen.getByLabelText("Title (optional)"), { target: { value: "A title" } });
    fireEvent.change(screen.getByLabelText("Source URL (optional)"), {
      target: { value: "https://example.com/post" },
    });

    expect((screen.getByRole("button", { name: "Start ingest" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(startIngestMock).not.toHaveBeenCalled();
  });

  it("sends drop.text alone, omitting title/url when left blank", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    startIngestMock.mockResolvedValue(ingestJob({ items_total: 1 }));

    await renderDetail("creator-a");

    fireEvent.click(screen.getByRole("tab", { name: "Paste text" }));
    fireEvent.change(screen.getByLabelText("Paste the text"), {
      target: { value: "They said NVDA looks strong here." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start ingest" }));

    expect(startIngestMock).toHaveBeenCalledWith("creator-a", {
      drop: { text: "They said NVDA looks strong here." },
    });
  });

  it("sends drop.title and drop.url when provided", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    startIngestMock.mockResolvedValue(ingestJob({ items_total: 1 }));

    await renderDetail("creator-a");

    fireEvent.click(screen.getByRole("tab", { name: "Paste text" }));
    fireEvent.change(screen.getByLabelText("Title (optional)"), { target: { value: "A title" } });
    fireEvent.change(screen.getByLabelText("Source URL (optional)"), {
      target: { value: "https://example.com/post" },
    });
    fireEvent.change(screen.getByLabelText("Paste the text"), {
      target: { value: "The full pasted text." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start ingest" }));

    expect(startIngestMock).toHaveBeenCalledWith("creator-a", {
      drop: { text: "The full pasted text.", title: "A title", url: "https://example.com/post" },
    });
  });

  it("shows the server's 422 detail when a drop carries only a url (no pasted text)", async () => {
    // This test types text so the client-side guard allows submission, then simulates the server
    // still rejecting the drop -- covering "the server remains the authority" even though this
    // exact shape (url with no text) is also blocked client-side by the disabled-submit guard above.
    cardsMock.mockResolvedValue([digestCard()]);
    startIngestMock.mockRejectedValue(
      new ApiRequestError(
        422,
        JSON.stringify({ detail: "Pasting the text is required for a drop." }),
      ),
    );

    await renderDetail("creator-a");

    fireEvent.click(screen.getByRole("tab", { name: "Paste text" }));
    fireEvent.change(screen.getByLabelText("Source URL (optional)"), {
      target: { value: "https://example.com/post" },
    });
    fireEvent.change(screen.getByLabelText("Paste the text"), { target: { value: "placeholder" } });
    fireEvent.click(screen.getByRole("button", { name: "Start ingest" }));

    expect(await screen.findByText("Pasting the text is required for a drop.")).toBeTruthy();
  });
});

describe("deleting from the detail page", () => {
  it("navigates back to /personas on a successful delete", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    removeMock.mockResolvedValue(undefined);

    await renderDetail("creator-a");

    fireEvent.click(screen.getByRole("button", { name: "Remove persona" }));

    expect(removeMock).toHaveBeenCalledWith("creator-a");
    expect(await screen.findByTestId("personas-list-stub")).toBeTruthy();
  });

  it("renders the server's rejection detail and stays on the page on a failed delete", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    removeMock.mockRejectedValue(
      new ApiRequestError(500, JSON.stringify({ detail: "Could not remove this persona right now." })),
    );

    await renderDetail("creator-a");

    fireEvent.click(screen.getByRole("button", { name: "Remove persona" }));

    expect(await screen.findByText("Could not remove this persona right now.")).toBeTruthy();
    expect(screen.queryByTestId("personas-list-stub")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Phase 2 -- persona consolidation (docs/INFLUENCER-CONTRACT.md, "Phase 2").
// ---------------------------------------------------------------------------

describe("persona profile -- never consolidated (404)", () => {
  it("renders the empty-state invitation, not an error or a spinner", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    // getProfileMock already defaults to a 404 rejection in beforeEach.

    await renderDetail("creator-a");

    expect(await screen.findByText("Creator A has not been consolidated yet.")).toBeTruthy();
    expect(screen.queryByText(/Could not load this persona's profile/)).toBeNull();
    expect(screen.getByRole("button", { name: "Consolidate" })).toBeTruthy();
  });

  it("disables the Consolidate button and states why for a persona with no notes", async () => {
    cardsMock.mockResolvedValue([
      digestCard({
        persona: persona({ slug: "freshface", display_name: "Fresh Face", note_count: 0, tickers: [] }),
        as_of: null,
        window_start: null,
        note_count: 0,
        headline: "",
        themes: [],
        mentions: [],
        latest_note: null,
      }),
    ]);

    await renderDetail("freshface");

    expect(
      await screen.findByText("Add notes for Fresh Face before consolidating -- there is nothing yet to fold into a profile."),
    ).toBeTruthy();
    const button = screen.getByRole("button", { name: "Consolidate" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });
});

describe("persona profile -- loaded", () => {
  it("renders the summary, version, note count and every claim's citations, never hidden", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    getProfileMock.mockResolvedValue(personaProfile());
    thesesMock.mockResolvedValue([tickerThesis()]);

    await renderDetail("creator-a");

    await screen.findByText("A Korean retail-focused investor who trades AI capex themes.");
    // Scoped to the profile panel itself -- the profile-diff panel added alongside it also lists
    // "v1" as a version-select option once this persona's profile has loaded.
    const profilePanel = document.querySelector(".persona-profile") as HTMLElement;
    expect(within(profilePanel).getByText("v1")).toBeTruthy();
    expect(within(profilePanel).getByText("built from 3 notes")).toBeTruthy();

    // Beliefs and playbook claims render with their citation chips visible in the DOM, not hidden
    // behind a hover/title -- the whole point of a profile per the contract.
    expect(screen.getByText("AI capex spending keeps accelerating into next year.")).toBeTruthy();
    expect(screen.getAllByText("vidExample01").length).toBeGreaterThan(0);
    expect(screen.getByText("Scales into positions on pullbacks rather than chasing breakouts.")).toBeTruthy();
    expect(screen.getByText("otherNoteId1")).toBeTruthy();

    // Re-consolidate label once a profile already exists.
    expect(screen.getByRole("button", { name: "Re-consolidate" })).toBeTruthy();
  });

  it("shows the degraded badge when the profile was released despite failing its fact-check", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    getProfileMock.mockResolvedValue(personaProfile({ degraded: true }));

    await renderDetail("creator-a");

    expect(await screen.findByText("Fact-check failed.")).toBeTruthy();
    expect(document.querySelector(".persona-profile-degraded")).not.toBeNull();
  });

  it("renders no degraded callout when the profile is not degraded", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    getProfileMock.mockResolvedValue(personaProfile({ degraded: false }));

    await renderDetail("creator-a");

    await screen.findByText("A Korean retail-focused investor who trades AI capex themes.");
    expect(document.querySelector(".persona-profile-degraded")).toBeNull();
  });
});

describe("persona profile -- theses link to /symbol/{symbol}", () => {
  it("renders each thesis symbol, its stance, and a link to the ticker page", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    getProfileMock.mockResolvedValue(personaProfile());
    thesesMock.mockResolvedValue([
      tickerThesis({ symbol: "NVDA", stance: "bullish" }),
      tickerThesis({ symbol: "TSLA", stance: "unclear", claims: [] }),
    ]);

    await renderDetail("creator-a");
    await screen.findByText("A Korean retail-focused investor who trades AI capex themes.");

    const links = screen.getAllByRole("link", { name: /NVDA|TSLA/ });
    const nvdaLink = links.find((el) => el.textContent?.includes("NVDA"));
    const tslaLink = links.find((el) => el.textContent?.includes("TSLA"));
    expect(nvdaLink?.getAttribute("href")).toBe("/symbol/NVDA");
    expect(tslaLink?.getAttribute("href")).toBe("/symbol/TSLA");
    expect(within(tslaLink as HTMLElement).getByText("no clear stance")).toBeTruthy();
  });
});

describe("consolidate button -- pending and error paths", () => {
  it("shows a pending label and disables the button while consolidation is in flight", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    let resolveConsolidate: (profile: PersonaProfile) => void = () => {};
    consolidateMock.mockReturnValue(
      new Promise<PersonaProfile>((resolve) => {
        resolveConsolidate = resolve;
      }),
    );

    await renderDetail("creator-a");
    await screen.findByText("Creator A has not been consolidated yet.");

    fireEvent.click(screen.getByRole("button", { name: "Consolidate" }));

    const pendingButton = await screen.findByRole("button", { name: "Consolidating…" });
    expect((pendingButton as HTMLButtonElement).disabled).toBe(true);
    expect(consolidateMock).toHaveBeenCalledWith("creator-a");

    resolveConsolidate(personaProfile());

    expect(await screen.findByText("A Korean retail-focused investor who trades AI capex themes.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Re-consolidate" })).toBeTruthy();
  });

  it("renders the server's own error detail verbatim on a failed consolidation", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    consolidateMock.mockRejectedValue(
      new ApiRequestError(
        422,
        JSON.stringify({ detail: "The persona has no notes recent enough to consolidate." }),
      ),
    );

    await renderDetail("creator-a");
    await screen.findByText("Creator A has not been consolidated yet.");

    fireEvent.click(screen.getByRole("button", { name: "Consolidate" }));

    expect(
      await screen.findByText("The persona has no notes recent enough to consolidate."),
    ).toBeTruthy();
    // The button returns to its idle, enabled state after the failure.
    expect((screen.getByRole("button", { name: "Consolidate" }) as HTMLButtonElement).disabled).toBe(
      false,
    );
  });
});

// ---------------------------------------------------------------------------
// Phase 3a -- call scoring (docs/INFLUENCER-CONTRACT.md, "Phase 3a").
// ---------------------------------------------------------------------------

describe("call scorecard -- aggregate", () => {
  it("renders hit rate and median return for a scored persona", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    scorecardMock.mockResolvedValue(
      personaScorecard({
        scored_calls: [callScore()],
        directional_count: 4,
        played_out: 3,
        hit_rate: 0.75,
        median_return_pct: 2.5,
      }),
    );

    await renderDetail("creator-a");

    expect(await screen.findByText("3/4 (75%)")).toBeTruthy();
    expect(screen.getByText("+2.50%")).toBeTruthy();
    // The mandatory descriptive, backward-looking, non-advice caption.
    expect(
      screen.getByText(/past ticker calls would have looked if acted on that day/i),
    ).toBeTruthy();
    expect(screen.getByText(/not a claim or advice/i)).toBeTruthy();
  });

  it("renders hit_rate: null and median_return_pct: null as 'not enough' copy, not as 0", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    scorecardMock.mockResolvedValue(
      personaScorecard({ scored_calls: [], directional_count: 0, played_out: 0, hit_rate: null, median_return_pct: null }),
    );

    await renderDetail("creator-a");

    expect(await screen.findByText("Not enough scored calls yet")).toBeTruthy();
    expect(screen.getByText("Not enough data yet")).toBeTruthy();
    expect(screen.queryByText("0/0 (0%)")).toBeNull();
    expect(screen.getByText("No dated calls to score yet.")).toBeTruthy();
  });

  it("renders hit_rate: 0 and median_return_pct: 0 as real zero measurements, not the null copy", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    scorecardMock.mockResolvedValue(
      personaScorecard({
        scored_calls: [callScore({ outcome: "went_against", return_pct: -1.5 })],
        directional_count: 2,
        played_out: 0,
        hit_rate: 0,
        median_return_pct: 0,
      }),
    );

    await renderDetail("creator-a");

    const aggregate = (await screen.findByText("0/2 (0%)")).closest(
      ".persona-scorecard-aggregate",
    ) as HTMLElement;
    expect(within(aggregate).getByText("+0.00%")).toBeTruthy();
    expect(screen.queryByText("Not enough scored calls yet")).toBeNull();
    expect(screen.queryByText("Not enough data yet")).toBeNull();
  });

  it("renders non-empty warnings visibly rather than swallowing them", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    scorecardMock.mockResolvedValue(
      personaScorecard({ warnings: [{ source: "TSLA", reason: "no usable bars for this window" }] }),
    );

    await renderDetail("creator-a");

    expect(await screen.findByText(/no usable bars for this window/)).toBeTruthy();
  });
});

describe("call scorecard -- per-call rows", () => {
  it("shows a played_out call and a went_against call with distinct badges", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    scorecardMock.mockResolvedValue(
      personaScorecard({
        scored_calls: [
          callScore({ symbol: "NVDA", outcome: "played_out", return_pct: 4.32 }),
          callScore({ symbol: "TSLA", note_id: "otherNote", outcome: "went_against", return_pct: -3.1, stance: "bullish" }),
        ],
      }),
    );

    await renderDetail("creator-a");

    expect(await screen.findByText("played out")).toBeTruthy();
    expect(screen.getByText("went against")).toBeTruthy();
  });

  it("renders a pending call and a no_data call as '—' with their own badge, not a fabricated return", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    scorecardMock.mockResolvedValue(
      personaScorecard({
        scored_calls: [
          callScore({
            symbol: "NVDA",
            note_id: "pendingNote",
            outcome: "pending",
            return_pct: null,
            entry_date: null,
            entry_price: null,
            latest_date: null,
            latest_price: null,
            basis: null,
          }),
          callScore({
            symbol: "TSLA",
            note_id: "noDataNote",
            outcome: "no_data",
            return_pct: null,
            entry_date: null,
            entry_price: null,
            latest_date: null,
            latest_price: null,
            basis: null,
          }),
        ],
      }),
    );

    await renderDetail("creator-a");

    expect(await screen.findByText("too recent")).toBeTruthy();
    expect(screen.getByText("no price data")).toBeTruthy();
    const emDashes = screen.getAllByText("—");
    expect(emDashes.length).toBeGreaterThanOrEqual(2);
  });

  it("colors return_pct by its own sign, not by whether the call played out", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    scorecardMock.mockResolvedValue(
      personaScorecard({
        scored_calls: [
          // A bearish call that "played out" (price fell) still shows a *negative*, red return --
          // the sign is the actual price move, not a verdict.
          callScore({ symbol: "NVDA", stance: "bearish", outcome: "played_out", return_pct: -5.2 }),
        ],
      }),
    );

    await renderDetail("creator-a");

    const returnEl = await screen.findByText("-5.20%");
    expect(returnEl.className).toContain("persona-scorecard-return-neg");
    expect(returnEl.className).not.toContain("persona-scorecard-return-pos");
  });

  it("links each call's symbol to /symbol/{symbol}", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    scorecardMock.mockResolvedValue(personaScorecard({ scored_calls: [callScore({ symbol: "NVDA" })] }));

    await renderDetail("creator-a");

    // The digest card above also links NVDA to its ticker page (same href), so scope the lookup to
    // the scorecard row specifically rather than asserting on a single page-wide match.
    const row = (await screen.findByText("played out")).closest(".persona-scorecard-row") as HTMLElement;
    const link = within(row).getByRole("link", { name: /NVDA/ });
    expect(link.getAttribute("href")).toBe("/symbol/NVDA");
  });
});

describe("call scorecard -- 404 is an error, not the profile's 'not consolidated' empty state", () => {
  it("renders a genuine error when GET /scorecard answers 404", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    scorecardMock.mockRejectedValue(
      new ApiRequestError(404, JSON.stringify({ detail: "Unknown persona." })),
    );

    await renderDetail("creator-a");

    const scorecardPanel = await screen.findByText("Call scorecard");
    const panel = scorecardPanel.closest(".persona-scorecard") as HTMLElement;
    expect(within(panel).getByRole("alert")).toBeTruthy();
    expect(within(panel).queryByText("No dated calls to score yet.")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Phase 6/7 -- the timeline, backtest, ask, strategy card, critique and profile-diff panels. These
// panels are presentational and already covered by their own component tests; here we only pin that
// this route actually fetches for and renders each of them, for the one slug it owns.
// ---------------------------------------------------------------------------

describe("timeline and backtest panels", () => {
  it("fetches and renders the persona's timeline", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    timelineMock.mockResolvedValue({
      persona: "creator-a",
      entries: [
        {
          note_id: "vidExample01",
          published: "2026-09-01T00:00:00Z",
          title: "36 1 September Market Headwinds",
          summary: "They discussed NVDA and TSLA.",
          themes: ["AI capex cycle"],
          symbols: ["NVDA"],
          url: "https://www.youtube.com/watch?v=vidExample01",
        },
      ],
      stance_timelines: [],
    });

    await renderDetail("creator-a");

    expect(timelineMock).toHaveBeenCalledWith("creator-a");
    expect(await screen.findByText("36 1 September Market Headwinds")).toBeTruthy();
  });

  it("fetches and renders the persona's benchmarked backtest", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    backtestMock.mockResolvedValue({
      persona: "creator-a",
      as_of: "2026-09-01",
      benchmark: "SPY",
      call_count: 3,
      horizons: [],
      caveat: "Small samples over a single window are not evidence of skill.",
      warnings: [],
    });

    await renderDetail("creator-a");

    expect(backtestMock).toHaveBeenCalledWith("creator-a");
    const caveat = await screen.findByTestId("backtest-caveat");
    expect(caveat.textContent).toContain("Small samples over a single window are not evidence of skill.");
  });
});

describe("chat, strategy card and critique", () => {
  it("sends a chat turn (creating a thread first) and renders the cited answer", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    // No thread exists yet -- sending must create one before sending the turn.
    createChatMock.mockResolvedValue(chatThread({ thread_id: "thread-new" }));
    sendTurnMock.mockResolvedValue(
      chatTurn({
        question: "What do you think of NVDA?",
        symbol: "NVDA",
        stance: "bullish",
        answer: "They remain bullish on continued AI capex.",
      }),
    );

    await renderDetail("creator-a");

    fireEvent.change(screen.getByLabelText("Question"), {
      target: { value: "What do you think of NVDA?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("They remain bullish on continued AI capex.")).toBeTruthy();
    expect(createChatMock).toHaveBeenCalledWith("creator-a");
    expect(sendTurnMock).toHaveBeenCalledWith("creator-a", "thread-new", {
      question: "What do you think of NVDA?",
      lang: "en",
    });
  });

  it("drafts a strategy card, then critiques it once one is drafted", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    strategyCardMock.mockResolvedValue({
      persona: "creator-a",
      mapped: true,
      reason: "",
      rule_shape: "momentum",
      card: { entry: "breakout" },
      rationale: "Mirrors their pullback-scaling playbook.",
      citations: ["vidExample01"],
      caveat: "An exploration lens, never a recommendation.",
      degraded: false,
      cost_usd: "0.02",
      version: 1,
      fidelity: 0.5,
      techniques_total: 2,
      techniques_represented: 1,
      unrepresentable: [],
    });
    critiqueMock.mockResolvedValue({
      persona: "creator-a",
      verdict: "aligned",
      assessment: "This matches how they actually trade.",
      citations: ["vidExample01"],
      caveat: "An impression of their view, not advice.",
      degraded: false,
      cost_usd: "0.01",
    });

    await renderDetail("creator-a");

    fireEvent.click(await screen.findByRole("button", { name: "Draft a strategy from their method" }));
    await screen.findByText(/Mirrors their pullback-scaling playbook\./);

    const critiqueButton = screen.getByRole("button", { name: "Ask for a critique" });
    expect((critiqueButton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(critiqueButton);

    expect(await screen.findByText("This matches how they actually trade.")).toBeTruthy();
    expect(critiqueMock).toHaveBeenCalledWith("creator-a", { card: { entry: "breakout" } });
  });
});

describe("profile diff", () => {
  it("lists versions 1..current and compares once from/to are both chosen", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    getProfileMock.mockResolvedValue(personaProfile({ version: 3 }));
    profileDiffMock.mockResolvedValue({
      persona: "creator-a",
      from_version: 1,
      to_version: 3,
      changes: [{ kind: "added", section: "belief", text: "A new belief.", citations: ["vidExample01"] }],
      added: 1,
      removed: 0,
      recited: 0,
    });

    await renderDetail("creator-a");
    await screen.findByText("A Korean retail-focused investor who trades AI capex themes.");

    const fromSelect = screen.getByLabelText("From version") as HTMLSelectElement;
    const toSelect = screen.getByLabelText("To version") as HTMLSelectElement;
    fireEvent.change(fromSelect, { target: { value: "1" } });
    fireEvent.change(toSelect, { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));

    expect(await screen.findByText("A new belief.")).toBeTruthy();
    expect(profileDiffMock).toHaveBeenCalledWith("creator-a", { from: 1, to: 3 });
  });
});

// ---------------------------------------------------------------------------
// Regression: each of the four persona *mutation* endpoints (ask, strategy-card draft, critique,
// profile diff) must render a visible, accessible error on rejection -- never silently fall back to
// an idle/empty state. Each panel renders its own error as
// `<div className="callout callout-danger ..." role="alert">{state.message}</div>` (see
// `PersonaAsk.tsx`, `PersonaStrategyCard.tsx`, `PersonaCritique.tsx`, `PersonaProfileDiff.tsx`), and
// `describePersonaActionError` unwraps the server's own `detail` string as that message -- so the
// text asserted here is exactly the `detail` each mock rejects with.
// ---------------------------------------------------------------------------

describe("persona mutation rejections render a visible, accessible error", () => {
  it("chat turn -- renders the rejection detail inside a role=alert element", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    createChatMock.mockResolvedValue(chatThread({ thread_id: "thread-new" }));
    sendTurnMock.mockRejectedValue(
      new ApiRequestError(500, JSON.stringify({ detail: "the chat engine crashed" })),
    );

    await renderDetail("creator-a");

    const chatPanel = document.querySelector(".persona-chat") as HTMLElement;
    fireEvent.change(within(chatPanel).getByLabelText("Question"), {
      target: { value: "What do you think of NVDA?" },
    });
    fireEvent.click(within(chatPanel).getByRole("button", { name: "Send" }));

    const alert = await within(chatPanel).findByRole("alert");
    expect(alert.textContent).toContain("the chat engine crashed");
  });

  it("strategy card draft -- renders the rejection detail inside a role=alert element", async () => {
    // A `mapped: false` RESOLVE is a valid, non-error answer (see `PersonaStrategyCard.tsx`'s own
    // docstring, rule 1) -- this test instead rejects the promise itself, the actual failure path.
    cardsMock.mockResolvedValue([digestCard()]);
    strategyCardMock.mockRejectedValue(
      new ApiRequestError(500, JSON.stringify({ detail: "drafting failed" })),
    );

    await renderDetail("creator-a");

    fireEvent.click(screen.getByRole("button", { name: "Draft a strategy from their method" }));

    const strategyPanel = document.querySelector(".persona-strategy-card") as HTMLElement;
    const alert = await within(strategyPanel).findByRole("alert");
    expect(alert.textContent).toContain("drafting failed");
  });

  it("critique -- renders the rejection detail inside a role=alert element, once a card is drafted", async () => {
    // The critique trigger stays disabled until a strategy card has been drafted (`canCritique`), so
    // this test first drives a successful draft (mirroring "drafts a strategy card, then critiques it
    // once one is drafted" above) before rejecting the critique call itself.
    cardsMock.mockResolvedValue([digestCard()]);
    strategyCardMock.mockResolvedValue({
      persona: "creator-a",
      mapped: true,
      reason: "",
      rule_shape: "momentum",
      card: { entry: "breakout" },
      rationale: "Mirrors their pullback-scaling playbook.",
      citations: ["vidExample01"],
      caveat: "An exploration lens, never a recommendation.",
      degraded: false,
      cost_usd: "0.02",
      version: 1,
      fidelity: 0.5,
      techniques_total: 2,
      techniques_represented: 1,
      unrepresentable: [],
    });
    critiqueMock.mockRejectedValue(
      new ApiRequestError(500, JSON.stringify({ detail: "critique failed" })),
    );

    await renderDetail("creator-a");

    fireEvent.click(await screen.findByRole("button", { name: "Draft a strategy from their method" }));
    await screen.findByText(/Mirrors their pullback-scaling playbook\./);

    const critiqueButton = screen.getByRole("button", { name: "Ask for a critique" });
    expect((critiqueButton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(critiqueButton);

    const critiquePanel = document.querySelector(".persona-critique") as HTMLElement;
    const alert = await within(critiquePanel).findByRole("alert");
    expect(alert.textContent).toContain("critique failed");
  });

  it("profile diff -- renders the rejection detail inside a role=alert element", async () => {
    cardsMock.mockResolvedValue([digestCard()]);
    getProfileMock.mockResolvedValue(personaProfile({ version: 3 }));
    profileDiffMock.mockRejectedValue(
      new ApiRequestError(500, JSON.stringify({ detail: "diff failed" })),
    );

    await renderDetail("creator-a");
    await screen.findByText("A Korean retail-focused investor who trades AI capex themes.");

    const fromSelect = screen.getByLabelText("From version") as HTMLSelectElement;
    const toSelect = screen.getByLabelText("To version") as HTMLSelectElement;
    fireEvent.change(fromSelect, { target: { value: "1" } });
    fireEvent.change(toSelect, { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));

    const diffPanel = document.querySelector(".persona-profile-diff") as HTMLElement;
    const alert = await within(diffPanel).findByRole("alert");
    expect(alert.textContent).toContain("diff failed");
  });
});
