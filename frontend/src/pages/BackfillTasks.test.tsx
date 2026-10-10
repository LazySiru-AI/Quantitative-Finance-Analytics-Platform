/**
 * The Backfill Tasks page's honesty rules, at render level.
 *
 * Mirrors `AgentWorkflow.test.tsx`'s approach: `@/api/backfill` is stubbed at the module boundary
 * rather than `fetch`, and fixture factories mirror the wire contract
 * (`docs/AGENT-DESK-CONTRACT.md`'s pinned `/api/backfill` shape) field for field.
 *
 * What these tests pin:
 *  - the task list renders both pending tasks' titles;
 *  - a 422 from ingest renders the backend's own `reasons`, not a generic failure line;
 *  - the copy button fetches the packet and writes its markdown to the clipboard verbatim.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BackfillIngestError } from "@/api/backfill";
import type { GenerateRequest, GenerateResult, IngestResult, TaskDetail, TaskRef, ValidateRequest, ValidateResult } from "@/api/backfill";

const listTasksMock = vi.fn<() => Promise<{ tasks: TaskRef[] }>>();
const getTaskMock = vi.fn<(videoId: string) => Promise<TaskDetail>>();
const generateMock = vi.fn<(body: GenerateRequest) => Promise<GenerateResult>>();
const validateMock = vi.fn<(body: ValidateRequest) => Promise<ValidateResult>>();
const ingestResultMock = vi.fn<(videoId: string, text: string) => Promise<IngestResult>>();

vi.mock("@/api/backfill", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/backfill")>();
  return {
    ...actual,
    backfillApi: {
      listTasks: () => listTasksMock(),
      getTask: (videoId: string) => getTaskMock(videoId),
      generate: (body: GenerateRequest) => generateMock(body),
      validate: (body: ValidateRequest) => validateMock(body),
      ingestResult: (videoId: string, text: string) => ingestResultMock(videoId, text),
    },
  };
});

// The SECTION, not the default-export page. `/backfill` is a redirect now: this surface renders
// inside a panel on `/personas`, which owns the `<h1>` the page form still carries. Every
// assertion below is unchanged -- the heading was the only thing that moved.
const { BackfillSection: BackfillTasks } = await import("@/pages/BackfillTasks");

// --- fixtures ----------------------------------------------------------------------------------

function taskRef(overrides: Partial<TaskRef> = {}): TaskRef {
  return {
    persona_slug: "some-persona",
    persona_name: "Some Persona",
    video_id: "vid-1",
    title: "A great video about markets",
    url: "https://youtube.com/watch?v=vid-1",
    published: "2026-08-01",
    filename: "vid-1.md",
    ...overrides,
  };
}

function taskDetail(overrides: Partial<TaskDetail> = {}): TaskDetail {
  return {
    ...taskRef(),
    markdown: "# Packet\nSummarise this video.",
    ...overrides,
  };
}

beforeEach(() => {
  listTasksMock.mockReset();
  getTaskMock.mockReset();
  generateMock.mockReset();
  validateMock.mockReset();
  ingestResultMock.mockReset();
});

// --- tests -------------------------------------------------------------------------------------

describe("the task list", () => {
  it("renders both pending tasks' titles", async () => {
    listTasksMock.mockResolvedValue({
      tasks: [
        taskRef({ video_id: "vid-1", title: "First video title" }),
        taskRef({ video_id: "vid-2", title: "Second video title" }),
      ],
    });

    render(<BackfillTasks />);

    expect(await screen.findByText("First video title")).toBeTruthy();
    expect(screen.getByText("Second video title")).toBeTruthy();
  });

  it("shows the empty state when there are no pending tasks", async () => {
    listTasksMock.mockResolvedValue({ tasks: [] });

    render(<BackfillTasks />);

    expect(await screen.findByText(/No pending tasks/)).toBeTruthy();
  });

  it("renders a javascript: task URL as plain text, never an anchor", async () => {
    listTasksMock.mockResolvedValue({
      tasks: [taskRef({ video_id: "vid-1", url: "javascript:alert(1)" })],
    });

    render(<BackfillTasks />);

    expect(await screen.findByText("javascript:alert(1)")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("still renders an https task URL as an out-linking anchor", async () => {
    listTasksMock.mockResolvedValue({
      tasks: [taskRef({ video_id: "vid-1", url: "https://youtube.com/watch?v=vid-1" })],
    });

    render(<BackfillTasks />);

    const link = await screen.findByRole("link", { name: "https://youtube.com/watch?v=vid-1" });
    expect(link.getAttribute("href")).toBe("https://youtube.com/watch?v=vid-1");
  });
});

describe("copying a packet", () => {
  it("fetches the packet and writes its markdown to the clipboard", async () => {
    listTasksMock.mockResolvedValue({ tasks: [taskRef({ video_id: "vid-1" })] });
    const detail = taskDetail({ video_id: "vid-1", markdown: "# Packet\nExact text to copy." });
    getTaskMock.mockResolvedValue(detail);

    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(window.navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    render(<BackfillTasks />);

    fireEvent.click(await screen.findByRole("button", { name: /Copy packet/ }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(detail.markdown));
    expect(getTaskMock).toHaveBeenCalledWith("vid-1");
    expect(await screen.findByText("Copied")).toBeTruthy();
  });

  it("falls back to a selectable textarea when the clipboard is unavailable", async () => {
    listTasksMock.mockResolvedValue({ tasks: [taskRef({ video_id: "vid-1" })] });
    const detail = taskDetail({ video_id: "vid-1", markdown: "# Packet\nFallback text." });
    getTaskMock.mockResolvedValue(detail);

    Object.defineProperty(window.navigator, "clipboard", {
      value: undefined,
      configurable: true,
    });

    render(<BackfillTasks />);

    fireEvent.click(await screen.findByRole("button", { name: /Copy packet/ }));

    const fallbackTextarea = (await screen.findByLabelText(
      "Clipboard unavailable — select and copy the text below.",
    )) as HTMLTextAreaElement;
    expect(fallbackTextarea.value).toBe(detail.markdown);
  });
});

describe("ingesting a pasted reply", () => {
  it("renders the backend's reasons on a 422", async () => {
    listTasksMock.mockResolvedValue({ tasks: [taskRef({ video_id: "vid-1" })] });
    ingestResultMock.mockRejectedValue(
      new BackfillIngestError(422, "reply could not be parsed", [
        "missing a ticker section",
        "no summary paragraph found",
      ]),
    );

    render(<BackfillTasks />);

    const pasteBox = (await screen.findByPlaceholderText(
      "Paste the agent's reply here",
    )) as HTMLTextAreaElement;
    fireEvent.change(pasteBox, { target: { value: "some reply text" } });

    fireEvent.click(screen.getByRole("button", { name: /^Ingest$/ }));

    expect(await screen.findByText("reply could not be parsed")).toBeTruthy();
    expect(screen.getByText("missing a ticker section")).toBeTruthy();
    expect(screen.getByText("no summary paragraph found")).toBeTruthy();
  });

  it("removes the task and shows the mention count on success", async () => {
    listTasksMock.mockResolvedValue({ tasks: [taskRef({ video_id: "vid-1", title: "Ingest me" })] });
    ingestResultMock.mockResolvedValue({
      note_id: "note-1",
      persona_slug: "some-persona",
      mention_count: 3,
      summary_source: "external",
    });

    render(<BackfillTasks />);

    const pasteBox = (await screen.findByPlaceholderText(
      "Paste the agent's reply here",
    )) as HTMLTextAreaElement;
    fireEvent.change(pasteBox, { target: { value: "a full reply" } });

    fireEvent.click(screen.getByRole("button", { name: /^Ingest$/ }));

    await waitFor(() => expect(screen.queryByText("Ingest me")).toBeNull());
    expect(await screen.findByText(/Ingested: 3/)).toBeTruthy();
  });

  it("disables Ingest until the reply textarea is non-empty", async () => {
    listTasksMock.mockResolvedValue({ tasks: [taskRef({ video_id: "vid-1" })] });

    render(<BackfillTasks />);

    const ingestButton = (await screen.findByRole("button", {
      name: /^Ingest$/,
    })) as HTMLButtonElement;
    expect(ingestButton.disabled).toBe(true);

    const pasteBox = screen.getByPlaceholderText("Paste the agent's reply here");
    fireEvent.change(pasteBox, { target: { value: "text" } });

    expect(ingestButton.disabled).toBe(false);
  });
});

describe("validating a pasted reply", () => {
  it("renders reasons, dropped symbols and ungrounded numbers", async () => {
    listTasksMock.mockResolvedValue({ tasks: [taskRef({ video_id: "vid-1" })] });
    validateMock.mockResolvedValue({
      ok: false,
      reasons: ["thesis lacked evidence"],
      dropped_symbols: ["NVDA"],
      ungrounded_numbers: ["$4.20"],
    });

    render(<BackfillTasks />);

    const pasteBox = await screen.findByPlaceholderText("Paste the agent's reply here");
    fireEvent.change(pasteBox, { target: { value: "some reply" } });

    fireEvent.click(screen.getByRole("button", { name: /^Validate$/ }));

    expect(await screen.findByText("thesis lacked evidence")).toBeTruthy();
    expect(screen.getByText("NVDA")).toBeTruthy();
    expect(screen.getByText("$4.20")).toBeTruthy();
    expect(validateMock).toHaveBeenCalledWith({ video_id: "vid-1", text: "some reply" });
  });
});

describe("generating new tasks", () => {
  it("posts the limit, shows the written count, and refreshes the list", async () => {
    listTasksMock.mockResolvedValueOnce({ tasks: [] });
    generateMock.mockResolvedValue({ tasks: [taskRef({ video_id: "vid-9" })], written: 1 });
    listTasksMock.mockResolvedValueOnce({ tasks: [taskRef({ video_id: "vid-9" })] });

    render(<BackfillTasks />);

    await screen.findByText(/No pending tasks/);

    // Queried BY ITS ACCESSIBLE NAME, which is the point of the `<label htmlFor>` this replaced a
    // wrapper label with -- and the name now carries the unit, since the field is per-persona.
    const limitInput = screen.getByRole("textbox", {
      name: "Limit (videos per persona)",
    }) as HTMLInputElement;
    fireEvent.change(limitInput, { target: { value: "5" } });

    fireEvent.click(screen.getByRole("button", { name: /Generate new tasks/ }));

    expect(await screen.findByText(/Generated 1 task/)).toBeTruthy();
    expect(generateMock).toHaveBeenCalledWith({ limit: 5 });
    expect(listTasksMock).toHaveBeenCalledTimes(2);
  });

  it("names the unit the limit is counted in", async () => {
    listTasksMock.mockResolvedValue({ tasks: [] });
    render(<BackfillTasks />);
    await screen.findByText(/No pending tasks/);

    // The field is `GenerateRequest.limit`, which the backend forwards as `limit_per_persona`: 5
    // with five personas seated writes 25 packets, not 5. A bare "Limit" invites the other reading.
    const label = screen.getByText("Limit (videos per persona)");
    expect(label.getAttribute("for")).toBe("backfill-limit");
  });
});

describe("field labels sit above their fields", () => {
  it("associates the reply label with its textarea by htmlFor rather than by wrapping it", async () => {
    listTasksMock.mockResolvedValue({ tasks: [taskRef({ video_id: "vid-1" })] });
    render(<BackfillTasks />);
    await screen.findByRole("heading", { level: 3, name: /A great video about markets/ });

    // A `<label>` WRAPPED around a `<span>` and a control leaves both inline in one line box, so
    // the label text lands on the control's baseline -- which for an eight-row textarea is its
    // bottom edge, reading as a caption for whatever follows. The explicit pairing also survives
    // any later CSS that reorders the two, which a wrapper does not.
    const textarea = screen.getByLabelText("Agent reply");
    expect(textarea.tagName).toBe("TEXTAREA");
    const label = screen.getByText("Agent reply");
    expect(label.tagName).toBe("LABEL");
    expect(label.getAttribute("for")).toBe(textarea.getAttribute("id"));
    // Label first in document order -- above the field, not below it.
    expect(label.compareDocumentPosition(textarea) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps per-card ids unique so one label never points at another card's textarea", async () => {
    listTasksMock.mockResolvedValue({
      tasks: [taskRef({ video_id: "vid-1" }), taskRef({ video_id: "vid-2" })],
    });
    render(<BackfillTasks />);
    await screen.findAllByRole("heading", { level: 3 });

    const ids = screen.getAllByRole("textbox").map((el) => el.getAttribute("id"));
    expect(new Set(ids).size).toBe(ids.length);
  });
});
