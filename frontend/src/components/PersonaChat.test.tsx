/**
 * PersonaChat: the always-visible caveat, the stale-profile note's two variants, suggested-question
 * chips, a turn's degraded fact-check warning and stance chip, citation clicks, and the composer's
 * submit/disable/Enter-to-send behaviour.
 *
 * Fetch-free component -- no API mocking needed, just the props `PersonaDetail.tsx` would otherwise
 * produce. Same idiom as `PersonaAsk.test.tsx`.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatContext, ChatThread, ChatTurn, GroundingVerdict } from "@/api/personas";
import PersonaChat, { type ChatViewState } from "@/components/PersonaChat";

afterEach(cleanup);

function grounding(overrides: Partial<GroundingVerdict> = {}): GroundingVerdict {
  return { ok: true, issues: [], attempts: 1, degraded: false, checked_tokens: 42, ...overrides };
}

function turn(overrides: Partial<ChatTurn> = {}): ChatTurn {
  return {
    turn_id: "turn-1",
    asked_at: "2026-09-05T00:01:00Z",
    question: "What do you think of NVDA?",
    symbol: null,
    lang: "en",
    answer: "This is the model's impression of what they'd say.",
    citations: ["note-1", "note-2"],
    retrieved: ["note-1", "note-2"],
    stance: null,
    grounding: grounding(),
    degraded: false,
    cost_usd: "0.01",
    ...overrides,
  };
}

function thread(overrides: Partial<ChatThread> = {}): ChatThread {
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

function chatContext(overrides: Partial<ChatContext> = {}): ChatContext {
  return { profile_version: 1, profile_note_count: 3, note_count: 5, stale: true, ...overrides };
}

const idle: ChatViewState = { phase: "idle" };

function baseProps() {
  return {
    displayName: "TestName",
    threads: [] as ChatThread[],
    activeThread: null as ChatThread | null,
    context: null as ChatContext | null,
    turnState: idle,
    consolidating: false,
    onSelectThread: vi.fn(),
    onNewThread: vi.fn(),
    onDeleteThread: vi.fn(),
    onSend: vi.fn(),
    onConsolidate: vi.fn(),
  };
}

describe("the always-visible caveat", () => {
  it("renders even with zero threads and no active thread", () => {
    render(<PersonaChat {...baseProps()} />);
    // LANG-03 canonical wording: a model's impression, not the person, not advice.
    expect(screen.getByText(/model's impression from cited notes/i)).toBeTruthy();
    expect(screen.getByText(/not TestName, not advice/i)).toBeTruthy();
  });
});

describe("the data-egress line (EXP-04)", () => {
  it("says what is sent to the model provider, before anything is typed", () => {
    render(<PersonaChat {...baseProps()} />);
    const note = screen.getByTestId("persona-chat-egress");
    expect(note.textContent).toContain("sent to the model provider");
  });

  it("is not behind a disclosure -- no <details> to open", () => {
    render(<PersonaChat {...baseProps()} />);
    expect(screen.getByTestId("persona-chat-egress").tagName.toLowerCase()).toBe("p");
  });
});

describe("the stale-profile note", () => {
  it("renders the 'never consolidated' variant when profile_version is 0", () => {
    render(
      <PersonaChat
        {...baseProps()}
        context={chatContext({ profile_version: 0 })}
      />,
    );
    expect(screen.getByText(/consolidate TestName's notes/i)).toBeTruthy();
  });

  it("renders the 'built from N of M' variant when a profile exists but is behind", () => {
    render(
      <PersonaChat
        {...baseProps()}
        context={chatContext({ profile_version: 2, profile_note_count: 3, note_count: 7 })}
      />,
    );
    expect(screen.getByText("Profile built from 3 of 7 videos.")).toBeTruthy();
  });

  it("does not render when context is null or not stale", () => {
    const { rerender } = render(<PersonaChat {...baseProps()} context={null} />);
    expect(screen.queryByRole("button", { name: "Consolidate" })).toBeNull();

    rerender(<PersonaChat {...baseProps()} context={chatContext({ stale: false })} />);
    expect(screen.queryByRole("button", { name: "Consolidate" })).toBeNull();
  });

  it("fires onConsolidate and disables the button while consolidating", () => {
    const onConsolidate = vi.fn();
    const { rerender } = render(
      <PersonaChat {...baseProps()} context={chatContext()} onConsolidate={onConsolidate} />,
    );

    const button = screen.getByRole("button", { name: "Consolidate" });
    fireEvent.click(button);
    expect(onConsolidate).toHaveBeenCalledTimes(1);

    rerender(
      <PersonaChat {...baseProps()} context={chatContext()} onConsolidate={onConsolidate} consolidating />,
    );
    const pendingButton = screen.getByRole("button", { name: "Consolidating…" });
    expect(pendingButton.hasAttribute("disabled")).toBe(true);
  });
});

describe("suggested questions", () => {
  it("render only when the active thread has no turns, and clicking one sends it", () => {
    const onSend = vi.fn();
    render(<PersonaChat {...baseProps()} activeThread={thread()} onSend={onSend} />);

    const chip = screen.getByRole("button", { name: "What's their overall strategy?" });
    fireEvent.click(chip);

    expect(onSend).toHaveBeenCalledWith("What's their overall strategy?", undefined, "en");
  });

  it("do not render once the active thread has turns", () => {
    render(<PersonaChat {...baseProps()} activeThread={thread({ turns: [turn()] })} />);
    expect(screen.queryByRole("button", { name: "What's their overall strategy?" })).toBeNull();
  });
});

describe("a turn's degraded fact-check warning", () => {
  it("shows the warn pill and detail when degraded", () => {
    render(
      <PersonaChat
        {...baseProps()}
        activeThread={thread({
          turns: [turn({ degraded: true, grounding: grounding({ degraded: true, attempts: 2 }) })],
        })}
      />,
    );
    expect(screen.getByText("Fact-check failed")).toBeTruthy();
    expect(screen.getByText(/after 2 attempts/)).toBeTruthy();
  });

  it("shows no warning when not degraded", () => {
    render(<PersonaChat {...baseProps()} activeThread={thread({ turns: [turn({ degraded: false })] })} />);
    expect(screen.queryByText("Fact-check failed")).toBeNull();
  });
});

describe("citations", () => {
  it("render and clicking one calls onSelectCitation with the note id", () => {
    const onSelectCitation = vi.fn();
    render(
      <PersonaChat
        {...baseProps()}
        activeThread={thread({ turns: [turn({ citations: ["note-1", "note-2"] })] })}
        onSelectCitation={onSelectCitation}
      />,
    );

    expect(screen.getByText("note-1")).toBeTruthy();
    fireEvent.click(screen.getByText("note-1"));
    expect(onSelectCitation).toHaveBeenCalledWith("note-1");
  });
});

describe("a turn's stance chip", () => {
  it("renders only when stance is non-null", () => {
    const { unmount } = render(
      <PersonaChat {...baseProps()} activeThread={thread({ turns: [turn({ stance: "bullish" })] })} />,
    );
    expect(screen.getByTestId("persona-chat-stance")).toBeTruthy();
    unmount();

    render(<PersonaChat {...baseProps()} activeThread={thread({ turns: [turn({ stance: null })] })} />);
    expect(screen.queryByTestId("persona-chat-stance")).toBeNull();
  });
});

describe("the composer", () => {
  it("disables Send when the question is empty", () => {
    render(<PersonaChat {...baseProps()} />);
    expect(screen.getByRole("button", { name: "Send" }).hasAttribute("disabled")).toBe(true);
  });

  it("enables Send once a non-empty question is typed, and calls onSend with the trimmed text", () => {
    const onSend = vi.fn();
    render(<PersonaChat {...baseProps()} onSend={onSend} />);

    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "  hi there  " } });
    const button = screen.getByRole("button", { name: "Send" });
    expect(button.hasAttribute("disabled")).toBe(false);

    fireEvent.click(button);
    expect(onSend).toHaveBeenCalledWith("hi there", undefined, "en");
  });

  it("uppercases and forwards a supplied ticker as the optional symbol", () => {
    const onSend = vi.fn();
    render(<PersonaChat {...baseProps()} onSend={onSend} />);

    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "What about NVDA?" } });
    fireEvent.change(screen.getByLabelText("Ticker (optional)"), { target: { value: "nvda" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(onSend).toHaveBeenCalledWith("What about NVDA?", "NVDA", "en");
  });

  it("disables Send while a turn is pending, even with text typed", () => {
    render(<PersonaChat {...baseProps()} turnState={{ phase: "pending" }} />);
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "hi" } });
    expect(screen.getByRole("button", { name: "Send" }).hasAttribute("disabled")).toBe(true);
  });

  it("submits on Enter and inserts a newline on Shift+Enter", () => {
    const onSend = vi.fn();
    render(<PersonaChat {...baseProps()} onSend={onSend} />);

    const textarea = screen.getByLabelText("Question");
    fireEvent.change(textarea, { target: { value: "What about NVDA?" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();

    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("What about NVDA?", undefined, "en");
  });

  it("does not call onSend when Enter is pressed with an empty question", () => {
    const onSend = vi.fn();
    render(<PersonaChat {...baseProps()} onSend={onSend} />);

    const textarea = screen.getByLabelText("Question");
    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
  });
});

describe("the error phase", () => {
  it("renders the error message inside a role=alert element", () => {
    const state: ChatViewState = { phase: "error", message: "the chat endpoint is down" };
    render(<PersonaChat {...baseProps()} turnState={state} />);
    expect(screen.getByRole("alert").textContent).toContain("the chat endpoint is down");
  });
});

describe("deleting a chat (EXP-24)", () => {
  it("does not delete on the click -- it opens a confirm sheet", () => {
    const onDeleteThread = vi.fn();
    render(
      <PersonaChat {...baseProps()} activeThread={thread()} onDeleteThread={onDeleteThread} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete chat" }));

    expect(onDeleteThread).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("Delete this chat?");
    expect(dialog.textContent).toContain("cannot be undone");
  });

  it("deletes the active thread once confirmed", () => {
    const onDeleteThread = vi.fn();
    render(
      <PersonaChat {...baseProps()} activeThread={thread()} onDeleteThread={onDeleteThread} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete chat" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, delete" }));

    expect(onDeleteThread).toHaveBeenCalledWith("thread-1");
  });

  it("deletes nothing when the sheet is cancelled", () => {
    const onDeleteThread = vi.fn();
    render(
      <PersonaChat {...baseProps()} activeThread={thread()} onDeleteThread={onDeleteThread} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete chat" }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    expect(onDeleteThread).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
