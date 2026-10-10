# Persona Chat — plan

_Written 2026-09-07. Status: **planned, not started.** Companion to `INFLUENCER-CONTRACT.md` (wire
shapes), `INFLUENCER-IMPROVEMENTS-PLAN.md` (rigor work) and `PERSONAS-FRONTEND-TODO.md`._

## 0. The ask

On the Personas tab, pick one influencer and **talk to them**: "what's your trading strategy?",
"which indicators do you watch?", "what do you warn people about?". The answer must come from
**everything we have backfilled for that person** (all their video notes, ~40 and growing), name the
rules and tools they actually use (e.g. Creator C's 10-year yield lens, Creator E's two Bollinger
bands), and cite the videos it drew on. Model calls run on the Claude Code login the server already
uses ("your token while the server is running"), not a new credential.

Everything a persona says stays **a model's impression of the person, built from cited notes** —
never the person, never advice. That framing is already enforced across the feature and carries over
unchanged.

## 1. What exists today (measured 2026-09-07, this checkout)

| Fact | Where | Why it matters for chat |
|---|---|---|
| Single-shot **ask** endpoint + panel exist | `POST /api/personas/{slug}/ask` → `app.personas.ask.ask_persona`; `components/PersonaAsk.tsx` (slot 6 of 9 on `/personas/:slug`) | The grounded "in-voice" call, citation filter, stance rule and UI framing are done. Chat is an extension, not a new pipeline. |
| Ask retrieval = **12 most-recent notes** (symbol-matching first when a ticker is given) | `ask.py:_select_notes`, `MAX_CONTEXT_NOTES = 12` | A strategy question is answered from whatever was ingested last, not from the notes that talk about strategy. |
| Ask renders the profile's **summary / beliefs / playbook / vocabulary only** | `ask.py:_render_profile` | `methodology` (indicators, timeframes, stops — Phase 7a) and `regime` (Phase 8.4) are consolidated but **never shown to the ask model**. This is a defect and the cheapest fix in the plan. |
| **Consolidated profile** = beliefs + playbook + methodology + regime + vocabulary, every claim cites note_ids; incremental mode exists | `app.personas.consolidate`, `POST /{slug}/consolidate?incremental=` | This IS the "strategy memory" the owner describes. |
| **No persona has ever been consolidated** in this vault | `persona.json` `profile_version: 0` for all 5; no `profile.md` anywhere | The memory layer is empty. Prerequisite step, not a build step. |
| Vault: **5 personas, 70 notes** (Creator C 20, Creator E 5, Creator A 6, Creator D 19, Creator B 20); 11 notes are `summary_source: external` (Gemini paste-back); **0 notes carry `published`** | `data/vault/influencers/*` | Ordering falls back to `ingested_at`. Fine for chat; timeline/scoring stay dateless until backfill packets carry upload dates. |
| Vocabulary probe | grep over notes | "Bollinger/볼린저" in 2 Creator E notes; "10-year / 10년물 / 국채 금리" in 4 Creator C, 1 Creator D, 2 Creator B notes. The facts the owner wants are on disk; retrieval just has to find them. |
| Full transcripts are kept (1.67 MB total, ~24 KB per note) | `transcripts/<note_id>.md`, `VaultStore.read_transcript` | Too big to hand over whole; usable as targeted excerpts (Phase 3). |
| LLM transport: **Claude Code CLI**, `credential_source() == "cli"`, binary 2.1.255 | `app.agents.client.call_structured` → `app.agents.cli_transport` | Synchronous `--print --output-format json`, 300 s timeout, cost read from the CLI envelope. No streaming on this path. |
| Default model `claude-haiku-4-5-20251001` | `app.agents.models.DEFAULT_MODEL` | Cheap; voice quality is an owner choice (see §7). |
| Grounding gate + retry | `app.agentdesk.grounding.run_grounded` | Numbers must trace to the evidence pack; degraded answers are released and flagged, never raised. |
| Spend controls | `LEDGER.check(model_spend_daily_cap_usd=$25)` before each call; per-call `AgentBudget(cap=persona_ingest_cap_usd=$5)`; every `AgentCall` archived to `data/loop/agent_calls/` | Chat plugs into the same three hooks. |
| No multi-turn state anywhere; no SSE consumer in the frontend; one SSE producer (`/api/paperlive/stream`) behind a raw-ASGI auth gate | `auth/gate.py`, `api/paperlive.py` | Threads and a transcript UI are new. Streaming is optional and must not be wrapped in buffering middleware. |
| Auth: personas are open to any signed-in user, not owner-only | `auth/gate.py` `OWNER_ONLY_PREFIXES` | New routes under `/api/personas` need no auth code. |
| i18n: `messages/<area>.ts` with `{en, ko}`, `tsc` enforces both; prose budgets (`COPY-STYLE.md`) enforced by `proseBudget.test.ts` | `frontend/src/i18n` | Every new string ships in both languages inside budget. |

## 2. Gap → design

| Gap | Fix |
|---|---|
| The persona's "strategy memory" is empty | Consolidate all five personas (prerequisite). Surface a **stale-profile** state in the UI (`profile.note_count < persona.note_count`, or never consolidated) with a one-click consolidate. |
| Ask hides methodology/regime from the model | Render both in `_render_profile` (+ unit test). Ships in Phase 0. |
| Retrieval is recency-only | New `app.personas.retrieval`: lexical relevance over **all** notes, bilingual, with symbol and profile-citation boosts. |
| No conversation | `ChatThread` persisted in the vault; each turn = history + fresh retrieval + one grounded call. |
| No chat UI | `PersonaChat` panel replaces `PersonaAsk` on the detail page; suggested questions; per-message citations and grounding flags. |
| Answers always in `persona_summary_lang` | Turn carries `lang` (en/ko) from the UI toggle. Quotes stay verbatim in source language. |

## 3. Design

### 3.1 What the persona knows (four layers, assembled per turn)

**A. Profile (long-term memory).** The consolidated `PersonaProfile`, rendered in full: summary,
beliefs, playbook, **methodology**, **regime**, vocabulary. Same text used both as prompt context and
as a numeric-evidence section (existing symmetric-gate trick).

**B. Episodic notes (retrieved, not recent).** `app.personas.retrieval.select_notes(notes, question,
*, symbol, profile, cap, char_budget)`:
- Score = lexical overlap between the question and each note's `title + themes + summary + quotes +
  mention reasoning`. Tokenise Latin as lower-cased words (light stemming: strip plural/ing/ed),
  Hangul as character bigrams (so "볼린저밴드" matches "볼린저"). Weight by inverse note frequency
  (tf-idf over the persona's own notes; no external dependency).
- **Symbol boost**: notes mentioning the asked symbol first (existing rule preserved).
- **Profile-citation boost**: any profile claim whose text overlaps the question lends its
  `citations` a boost. So "what indicators do you use" pulls the notes the methodology claims cite,
  even when the note summary itself uses different words.
- **Recency tiebreak** on `published or ingested_at`.
- Cap: raise `MAX_CONTEXT_NOTES` 12 → 16 **and** add a character budget (~40k chars) so five long
  notes don't blow the prompt. Every selected note is tagged with its `note_id` exactly as today.
- Fallback: when the question has no informative tokens (e.g. "and then?"), fall back to the previous
  turn's retrieval set so a follow-up keeps its context.

**C. Transcript excerpts (Phase 3, optional).** Up to 6 windows of ±400 chars around keyword hits in
the transcripts of the top-scored notes, as an "Transcript excerpts" evidence section tagged with
`note_id`. Lets the persona quote "두 개의 볼린저 밴드" precisely when the summary elided it.

**D. Market snapshot.** Unchanged: one latest-close `EvidenceItem` when a symbol is given.

### 3.2 Conversation

- **Thread** = `<vault>/influencers/<slug>/chats/<thread_id>.json` (source of truth; an Obsidian `.md`
  mirror is Phase 3). Threads are listable, reloadable, deletable. Title = first question, trimmed.
- **Turn assembly**: system prompt = the existing ask prompt plus conversational rules (continuity
  with earlier turns is allowed; still no advice, still nothing off-record). User turn = the last
  `MAX_HISTORY_TURNS = 8` question/answer pairs (text only) → profile → retrieved notes → snapshot →
  the new question. Older turns are dropped, not summarised (a summary is uncited prose).
- **Evidence pack** = profile + notes + snapshot + one "Earlier answers in this thread" section that
  includes **only non-degraded prior answers**, so a number that failed the gate once cannot launder
  itself into the next turn.
- **Citations** filtered to the notes actually handed to this turn (existing `_filter_citations`).
- **Stance** only when a symbol was asked about (existing rule).
- **Limits**: `persona_chat_cap_usd` per thread (default `"2"`); `LEDGER.check` per turn; `MAX_TURNS
  = 40` per thread → 409 "start a new thread". Every turn's `AgentCall`s are archived like ask's.
- **Language**: `lang` on the request (`"en" | "ko"`), default `persona_summary_lang`. The frontend
  sends the active UI language.
- **Model**: new setting `persona_chat_model` (default `DEFAULT_MODEL`); the owner can set Sonnet for
  voice quality without touching ingest cost.
- **Sync, not streamed.** The CLI path is non-streaming and one turn is one call (tens of seconds).
  Same UX as consolidate/ask today. Streaming is Phase 3 and SDK-only.
- `/ask` stays as-is for API compatibility (it is the one-turn special case).

### 3.3 Wire contract (to be pinned as "Phase 9 — persona chat" in `INFLUENCER-CONTRACT.md` before any worker starts)

```ts
type ChatLang = "en" | "ko";

interface ChatTurn {
  turn_id: string;            // uuid
  asked_at: string;           // ISO-8601
  question: string;
  symbol: string | null;
  lang: ChatLang;
  answer: string;             // in the persona's voice, grounded
  citations: string[];        // note_ids used, ⊆ retrieved note_ids
  retrieved: string[];        // note_ids handed to the model this turn (audit)
  stance: Stance | null;
  grounding: GroundingVerdict;
  degraded: boolean;
  cost_usd: string;           // decimal string
}

interface ChatThread {
  thread_id: string;
  persona: string;            // slug
  title: string;              // first question, ≤ 80 chars
  created_at: string;
  updated_at: string;
  turn_count: number;
  spent_usd: string;          // decimal string, sum of turns
  turns: ChatTurn[];          // oldest first; [] on the list endpoint
}

interface ChatContext {       // what the persona would answer from right now
  profile_version: number;    // 0 = never consolidated
  profile_note_count: number; // notes the profile was built from
  note_count: number;         // notes on disk
  stale: boolean;             // never consolidated, or note_count > profile_note_count
}
```

```
GET    /api/personas/{slug}/chats                         -> ChatThread[]   (turns: [], newest first)
POST   /api/personas/{slug}/chats                         -> ChatThread     (201, empty thread)
GET    /api/personas/{slug}/chats/{thread_id}             -> ChatThread     (404)
DELETE /api/personas/{slug}/chats/{thread_id}             -> 204
POST   /api/personas/{slug}/chats/{thread_id}/turns
         {question: string (1-2000), symbol?: string, lang?: ChatLang} -> ChatTurn
GET    /api/personas/{slug}/chat-context                  -> ChatContext
```
Errors on `POST …/turns`: 404 unknown persona/thread; 409 no notes, thread turn cap, or thread budget
cap; 429 daily spend cap (existing handler); 503 model unavailable. Synchronous.

### 3.4 Frontend

- `components/PersonaChat.tsx` replaces `PersonaAsk` in `PersonaDetail` (same presentational split:
  the page owns fetches and passes state down).
  - Header: "Chat with `<name>`" + the unconditional caveat line ("a model's impression of `<name>`,
    from cited notes — not advice"). Stays visible above the transcript, not inside a disclosure.
  - **Stale-profile note** (`InfoNote`, tone quiet) when `ChatContext.stale`: "Profile built from N of
    M videos" / "Never consolidated" + a `Consolidate` button (reuses `personasApi.consolidate`,
    incremental when a profile exists). The chat still works while stale; the note just says so.
  - Thread picker (existing threads by title/date) + "New thread"; delete with confirm.
  - Transcript in `ScrollRegion size="lg"`: each turn shows the question, the answer, a stance chip
    when present, `CitationList` (clicking a citation scrolls the timeline to that note), a
    `StatusPill tone="warn"` "unverified" when `degraded`, and the turn cost muted. Pending turn shows
    an inline placeholder in the persona's slot.
  - **Suggested questions** as chips when the thread is empty: strategy, indicators, caution points,
    macro lens, recent view, "what changed in your view lately". Chips send immediately.
  - Composer: textarea (Enter sends, Shift+Enter newline), optional symbol input, Send disabled while
    pending or empty. Sends `lang` from the i18n store.
- `api/personas.ts`: mirror the types above; `personasApi.chats/createChat/chat/deleteChat/sendTurn/
  chatContext`.
- i18n shard `messages/personaChat.ts` (`en`+`ko`, within `COPY-STYLE.md` budgets); registered in
  `catalog.ts` `CATALOG` **and** `SHARDS`.
- Tests: `PersonaChat.test.tsx` (caveat always visible; degraded pill; citations; chip sends; stale note
  + consolidate; pending disables send), `PersonaDetail.test.tsx` additions, `api/personas.test.ts`.
- Placement: keep the detail-page slot by default (see §7).

### 3.5 Prerequisite data step (operator, before Phase 1 ships)

1. Consolidate each persona once (`POST /{slug}/consolidate`, five calls). After every backfill
   batch: `?incremental=true`. Expected: methodology non-empty for Creator C and Creator E, mostly
   empty for the macro trio (honest, not a gap).
2. The `published` gap: external backfill packets do not carry the upload date, so every note in this
   checkout is undated. Not a chat blocker; log it against the backfill runbook.

## 4. Phases and workers (repo workflow: pin contract → parallel Sonnet workers → QA → isolated commit)

**Phase 0 — quick wins (orchestrator, ≤ half a session).**
1. Pin §3.3 into `INFLUENCER-CONTRACT.md`.
2. Fix `_render_profile` to include methodology + regime; add a test that the rendered text contains
   a methodology claim. Commit alone.
3. Consolidate the five personas; then ask Creator E "which indicators do you use?" through the
   existing panel and confirm the answer cites a Bollinger note. This alone delivers a large share of
   the value and validates the data before any new code.

**Phase 1 — backend (two workers in parallel, then QA; M).**
- W1 `app.personas.retrieval` + `tests/test_personas_retrieval.py`. Probe with **real vault
  sentences**, not synthetic ones (per the grounding-gate lesson): "Bollinger bands" for
  `creator-e` must rank both Bollinger notes in the top 3; "10-year yield" for `creator-c`
  must rank ≥3 of the 4 notes in the top 5; a Korean question must hit the same notes.
- W2 `app.personas.chat` (models, `ChatStore` in the vault, `chat_turn` service, routes, settings
  `persona_chat_cap_usd` / `persona_chat_model`) + `tests/test_personas_chat.py`,
  `tests/test_api_personas_chat.py`. W2 imports W1 by the pinned name
  `select_notes(...)`; the orchestrator writes that signature into both briefs verbatim.
- QA worker: thread persists and reloads; degraded prior answer excluded from evidence; citations ⊆
  `retrieved`; turn cap → 409; spend cap → 429; `LEDGER.check` called before each turn; `AgentCall`s
  archived; ruff + mypy (from `backend/`) + pytest via `.venv` all green, with the `N passed` line.

**Phase 2 — frontend (two workers in parallel, then browser QA; M).**
- W3 `PersonaChat.tsx` + css + `personaChat.ts` i18n + component tests.
- W4 `api/personas.ts` types + client + tests; `PersonaDetail.tsx` wiring (state, thread fetches,
  consolidate hook-up, citation → timeline scroll); remove `PersonaAsk` from the page (keep the file
  until W3 lands, then delete with its test).
- QA: `tsc`, vitest, prose budget test; browser smoke on `localhost` (not `127.0.0.1`) via the outer
  folder's launch config; one real three-turn conversation with Creator C and one with Creator E,
  screenshots kept.

**Phase 3 — optional polish (each S–M, separate commits).**
- Transcript excerpts (layer C) behind `persona_chat_transcript_excerpts: bool` (default off).
- Obsidian `.md` mirror of each thread.
- Auto-`incremental` consolidate on ingest-job success (hook in `app.personas.jobs`) — only if the
  owner accepts the recurring cost; otherwise the stale note + button stays the mechanism.
- Streaming turns via the SDK path (`StreamingResponse`, `text/event-stream`, raw-ASGI gate
  untouched); CLI path keeps sync.

## 5. Verification (stated up front so "done" is measurable)

| Check | Pass condition |
|---|---|
| Ask fix | Unit test: rendered profile text contains a methodology claim and the regime line |
| Retrieval | The three probes in Phase 1 W1 pass against the real vault fixture copied into `tests/fixtures/personas/vault_sample/` |
| Thread | 3-turn thread → restart server → `GET /chats/{id}` returns 3 turns with identical content |
| Evidence hygiene | Turn 2's pack excludes turn 1's answer when turn 1 was degraded (test) |
| Caps | Turn 41 → 409; thread `spent_usd` ≥ cap → 409; ledger over daily cap → 429 |
| Frontend | Caveat visible with zero turns; degraded pill on a degraded turn; chip click sends; stale note shows N of M |
| Live | Creator E answers "which indicators do you use?" citing a Bollinger note; Creator C answers "how do you read macro?" citing a 10-year-yield note; both archived under `agent_calls/` |
| Gates | ruff, mypy (from `backend/`), pytest (`.venv`, `N passed`), `tsc`, vitest, prose budget |

## 6. Cost (estimate, CLI reports the true figure)

Per turn ≈ profile 3k + 16 notes × ~1.5k + history 4k ≈ 32k chars ≈ 9k input tokens. Haiku ≈ $0.01
per turn; Sonnet ≈ $0.03–0.05. Consolidation ≈ one 60k-char call per persona. A 20-turn conversation
stays under the default $2 thread cap on either model.

## 7. Owner decisions (defaults in bold; the plan proceeds on the defaults)

1. Chat model: **Haiku (current default)** vs Sonnet for voice.
2. Placement: **replace the Ask panel in its slot on `/personas/:slug`** vs move chat to the top of the
   page vs its own `/personas/:slug/chat` route.
3. Answer language: **follow the UI EN/KO toggle** vs fixed English.
4. Transcript excerpts: **Phase 3** vs Phase 1.
5. Re-consolidation: **stale note + manual button** vs auto after every ingest/backfill.

## 8. Risks

- **Thin data for two personas** (Creator E 5 notes, Creator A 6). Their persona will often say
  "I haven't said anything on record about that". That is the correct behaviour; more backfill is the
  fix, not a looser prompt.
- **Grounding false rejections on trader vocabulary** ("20-day MA", "two Bollinger bands", "3%
  stop"). Small integers ≤10 and `RSI(14)`-style params are already exempt; "20-day" is not. Phase 1
  QA must probe the gate with real answer sentences and extend `_INDICATOR_PARAM_RE` if needed —
  never widen the exemption blindly.
- **CLI latency**: one turn is one 10–60 s process; the 300 s timeout is fine, but the UI must show a
  pending state and block double-sends.
- **External notes** (`summary_source: external`) never passed the in-house gate. They are evidence
  like any note; the answer's own gate still runs. Acceptable, stated here so nobody re-audits it.
- **Concurrent sessions** edit `Personas`/`PersonaDetail` and commit mid-task. Check `git status` for
  another session's hunks before every commit; isolate each phase's commit.
