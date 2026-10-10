/**
 * "Chat with the persona" -- the multi-turn successor to the old single-shot `PersonaAsk.tsx`. Same
 * guardrails, extended for threads and turns: a model's cited impression of what an influencer would
 * say, in their voice, grounded in their own notes. NEVER the person literally speaking and NEVER
 * investment advice -- see `personaChat.caveat` below, rendered always-visible above the composer so
 * a reader cannot land on an answer without seeing the framing first.
 *
 * **Presentational only -- this component fetches nothing.** It takes `threads`/`activeThread`/
 * `context`/`turnState` and a set of callbacks; `PersonaDetail.tsx` owns every fetch against
 * `personasApi.chats`/`createChat`/`chat`/`deleteChat`/`sendTurn`/`chatContext` and feeds the results
 * back in as props, the same fetch-free split `PersonaAsk.tsx` established.
 *
 * Product guardrails this file enforces (mirrors `PersonaAsk.tsx`'s own list, extended for chat):
 *
 * 1. The "model's impression, from cited notes" caveat renders unconditionally, never behind a
 *    disclosure -- a reader sees the framing before they type anything.
 * 2. A stale consolidated profile is informational, not blocking: the chat still answers while
 *    `context.stale`, the note just says so (and offers a Consolidate button) -- see
 *    `personaChat.staleNever`/`personaChat.staleBehind`.
 * 3. Every turn's `citations` (via `CitationList`) and `degraded` flag are always visible; a
 *    `degraded` turn renders the same fact-check-failure callout idiom `PersonaAsk.tsx`'s
 *    `AnswerBody` uses (attempts + issue list) -- `ChatTurn.grounding` is one model call's own
 *    verdict, so `attempts`/`issues` are real measurements, not aggregate defaults.
 * 4. A stance chip renders only when `turn.stance !== null` -- a stance only exists when a symbol was
 *    asked about and the record supports one.
 * 5. Send is disabled while `turnState.phase === "pending"` and whenever the trimmed question is
 *    empty; an optional ticker is uppercased and passed only when non-empty, matching `PersonaAsk`'s
 *    own `onAsk` contract.
 * 6. Suggested-question chips render only while the active thread has no turns yet (or no thread has
 *    been started at all) -- once a conversation has turns, the chips make way for the transcript.
 * 7. A data-egress line (`personaChat.egress`) renders beside the caveat, above the composer, saying
 *    that the question and the cited notes go to the model provider. Like the caveat it is never
 *    behind a disclosure: a reader must see it before typing, not after sending.
 * 8. Deleting a chat goes through `ConfirmSheet` -- it destroys a transcript, and `pages/data/
 *    UsersPanel.tsx` draws the line there: confirm what spends or destroys, never what recomputes.
 */
import { useState, type KeyboardEvent } from "react";

import { stanceLabel, type ChatContext, type ChatLang, type ChatThread, type ChatTurn } from "@/api/personas";
import { CitationList } from "@/components/CitationList";
import { ConfirmSheet } from "@/components/ConfirmSheet";
import { InfoNote } from "@/components/InfoNote";
import { ScrollRegion } from "@/components/ScrollPanel";
import StatusPill from "@/components/StatusPill";
import { useT, type MessageKey } from "@/i18n";

import "./PersonaChat.css";

export type ChatViewState =
  | { phase: "idle" }
  | { phase: "pending" }
  | { phase: "error"; message: string };

export interface PersonaChatProps {
  displayName: string;
  /** Thread list (turns empty), newest first. */
  threads: ChatThread[];
  /** The currently-open thread WITH turns, or null when no thread has been opened yet. */
  activeThread: ChatThread | null;
  context: ChatContext | null;
  turnState: ChatViewState;
  consolidating: boolean;
  onSelectThread: (threadId: string) => void;
  onNewThread: () => void;
  onDeleteThread: (threadId: string) => void;
  /** `symbol` is optional (a stance is only returned with one supplied), same contract `PersonaAsk`'s
   * `onAsk` established. */
  onSend: (question: string, symbol: string | undefined, lang: ChatLang) => void;
  onConsolidate: () => void;
  /** Scroll the timeline to a cited note, when the caller has a mechanism for it. */
  onSelectCitation?: ((noteId: string) => void) | undefined;
}

const SUGGESTED_KEYS: readonly MessageKey[] = [
  "personaChat.suggest.strategy",
  "personaChat.suggest.indicators",
  "personaChat.suggest.caution",
  "personaChat.suggest.macro",
  "personaChat.suggest.recent",
  "personaChat.suggest.changed",
];

export default function PersonaChat({
  displayName,
  threads,
  activeThread,
  context,
  turnState,
  consolidating,
  onSelectThread,
  onNewThread,
  onDeleteThread,
  onSend,
  onConsolidate,
  onSelectCitation,
}: PersonaChatProps) {
  const { t, lang } = useT();
  const [question, setQuestion] = useState("");
  const [symbol, setSymbol] = useState("");
  // Guardrail 8: the thread a `ConfirmSheet` is asking about, or null.
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);

  const pending = turnState.phase === "pending";
  const turns = activeThread?.turns ?? [];
  const showSuggestions = turns.length === 0;

  const send = (text: string, tickerSymbol?: string) => {
    onSend(text, tickerSymbol, lang);
  };

  const canSend = question.trim().length > 0 && !pending;

  const handleSend = () => {
    if (!canSend) return;
    const trimmedSymbol = symbol.trim();
    send(question.trim(), trimmedSymbol.length > 0 ? trimmedSymbol.toUpperCase() : undefined);
    setQuestion("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <section className="panel persona-chat">
      <h3 className="persona-chat-heading">{t("personaChat.heading", { name: displayName })}</h3>
      <p className="muted persona-chat-caveat">{t("personaChat.caveat", { name: displayName })}</p>
      {/* Guardrail 7 (EXP-04): what leaves this machine when a turn is sent, stated before the
          composer rather than left to be inferred from the per-turn cost line. No `children` -- an
          egress notice is one of the things COPY-STYLE.md rule 6 forbids putting behind a ⓘ. */}
      <InfoNote
        tone="quiet"
        className="persona-chat-egress"
        data-testid="persona-chat-egress"
        summary={t("personaChat.egress")}
      />

      {context !== null && context.stale && (
        <InfoNote
          tone="quiet"
          className="persona-chat-stale-note"
          summary={
            context.profile_version === 0
              ? t("personaChat.staleNever", { name: displayName })
              : t("personaChat.staleBehind", {
                  built: context.profile_note_count,
                  total: context.note_count,
                })
          }
        >
          <div className="persona-chat-consolidate-row">
            <button type="button" onClick={onConsolidate} disabled={consolidating}>
              {consolidating ? t("personaChat.consolidating") : t("personaChat.consolidate")}
            </button>
          </div>
        </InfoNote>
      )}

      <div className="persona-chat-thread-bar">
        <button type="button" onClick={onNewThread}>
          {t("personaChat.newThread")}
        </button>
        {threads.length > 0 && (
          <select
            className="persona-chat-thread-select"
            aria-label={t("personaChat.threadSelectLabel")}
            value={activeThread?.thread_id ?? ""}
            onChange={(e) => {
              if (e.target.value) onSelectThread(e.target.value);
            }}
          >
            <option value="" disabled>
              {t("personaChat.threadSelectLabel")}
            </option>
            {threads.map((thread) => (
              <option key={thread.thread_id} value={thread.thread_id}>
                {thread.title || t("personaChat.untitledThread")}
              </option>
            ))}
          </select>
        )}
        {activeThread !== null && (
          <button type="button" onClick={() => setConfirmingDelete(activeThread.thread_id)}>
            {t("personaChat.deleteThread")}
          </button>
        )}
      </div>

      <ConfirmSheet
        open={confirmingDelete !== null}
        question={t("personaChat.deleteConfirm.title")}
        preview={t("personaChat.deleteConfirm.body")}
        confirmLabel={t("personaChat.deleteConfirm.confirm")}
        tone="bad"
        onConfirm={() => {
          const threadId = confirmingDelete;
          setConfirmingDelete(null);
          if (threadId !== null) onDeleteThread(threadId);
        }}
        onCancel={() => setConfirmingDelete(null)}
      />

      <ScrollRegion size="lg" label={t("personaChat.heading", { name: displayName })}>
        {turns.map((turn) => (
          <ChatTurnView key={turn.turn_id} turn={turn} onSelectCitation={onSelectCitation} />
        ))}

        {pending && (
          <div className="placeholder persona-chat-pending" data-testid="persona-chat-pending">
            {t("personaChat.pending", { name: displayName })}
          </div>
        )}

        {turnState.phase === "error" && (
          <div className="callout callout-danger persona-chat-error" role="alert">
            {turnState.message}
          </div>
        )}
      </ScrollRegion>

      {showSuggestions && (
        <div className="persona-chat-suggestions">
          {SUGGESTED_KEYS.map((key) => (
            <button
              key={key}
              type="button"
              className="persona-chat-suggestion-chip"
              onClick={() => send(t(key))}
            >
              {t(key)}
            </button>
          ))}
        </div>
      )}

      <div className="persona-chat-composer">
        <label className="persona-chat-field">
          <span>{t("personaChat.questionLabel")}</span>
          <textarea
            rows={2}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("personaChat.questionPlaceholder", { name: displayName })}
            disabled={pending}
          />
        </label>
        <label className="persona-chat-field">
          <span>{t("personaChat.symbolLabel")}</span>
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder={t("personaChat.symbolPlaceholder")}
            disabled={pending}
          />
        </label>
        <div className="persona-chat-send-row">
          <button type="button" onClick={handleSend} disabled={!canSend}>
            {t("personaChat.send")}
          </button>
        </div>
      </div>
    </section>
  );
}

const VERDICT_DETAIL_KEY = (attempts: number): MessageKey =>
  attempts === 1 ? "personaChat.groundingDetail_one" : "personaChat.groundingDetail_other";

/** One question/answer exchange. `turn.degraded` and `turn.grounding.degraded` are the same fact
 * denormalised twice on the wire (one model call, one verdict) -- see `PersonaAsk.tsx`'s
 * `AnswerBody` docstring for why this reads `degraded` for the gate and `grounding` for the detail. */
function ChatTurnView({
  turn,
  onSelectCitation,
}: {
  turn: ChatTurn;
  onSelectCitation?: ((noteId: string) => void) | undefined;
}) {
  const { t } = useT();
  return (
    <div className="persona-chat-turn" data-testid="persona-chat-turn">
      <p className="persona-chat-question">
        <span className="muted">{t("personaChat.youAsked")}:</span> {turn.question}
      </p>

      {turn.degraded && (
        <div className="callout callout-warn persona-chat-degraded" role="alert">
          <StatusPill tone="warn" label={t("ui.pill.unverified")} />{" "}
          <strong>{t("personaChat.factCheckFailed")}</strong>{" "}
          {t(VERDICT_DETAIL_KEY(turn.grounding.attempts), { attempts: turn.grounding.attempts })}
          {turn.grounding.issues.length > 0 && (
            <ul className="persona-chat-grounding-issues">
              {turn.grounding.issues.map((issue, i) => (
                <li key={i}>{issue.detail}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <p className="persona-chat-answer-text">{turn.answer}</p>

      {turn.stance !== null && (
        <span className="persona-chat-stance-chip" data-testid="persona-chat-stance">
          <span className="muted">{t("personaChat.stanceLabel")}:</span>{" "}
          <span className={`badge persona-chat-stance-${turn.stance}`}>{stanceLabel(turn.stance)}</span>
        </span>
      )}

      <CitationList citations={turn.citations} onSelect={onSelectCitation} />

      <p className="muted persona-chat-turn-cost">{t("personaChat.turnCost", { cost: turn.cost_usd })}</p>
    </div>
  );
}
