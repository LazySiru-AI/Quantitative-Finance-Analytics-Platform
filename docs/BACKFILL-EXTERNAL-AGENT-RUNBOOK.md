# External-agent backfill — operator runbook

How to run persona backfill on an external agent you already subscribe to (Gemini Pro / ChatGPT)
instead of the in-house Claude budget, when there is **no API** to automate it. This is the
operational companion to the code (`app.personas.backfill`, `app.personas.backfill_ingest`,
`app/api/backfill.py`, the `/backfill` page, and `tools/backfill_task_bundler.py` /
`tools/ingest_backfill_results.py`). It records what was verified end-to-end driving Gemini Pro in a
real browser on 2026-09-06/07, so the operational gotchas survive for the next person.

## Why manual (no automation)

A consumer Gemini Pro / ChatGPT subscription has **no API**, and since June 2026 the consumer tiers
can no longer drive the Gemini CLI / Code Assist either. So the subscription can only be used
*interactively* in the web app, which means a human (or a browser-automation session) ferries
copy-paste. Automating Gemini would require a separate AI Studio API key (a different path), never the
subscription. That is the whole reason the feature is a paste-out / paste-back loop rather than a
service call.

## The loop

1. **Generate packets.** `POST /api/backfill/generate` (or `tools/backfill_task_bundler.py`) writes one
   self-contained markdown task packet per un-ingested video into `INVDASH_BACKFILL_TASKS_DIR`
   (default `.backfill-tasks/`, gitignored). Each packet carries the job, the JSON output contract
   (mirroring `NoteDraft`), the guardrails, and the **full transcript** the agent must summarise.
2. **Run it through the external agent** (see the browser recipe below) → get back exactly one fenced
   ```json block per packet.
3. **Paste the reply back.** `POST /api/backfill/tasks/{id}/result` (or
   `tools/ingest_backfill_results.py`, which splits a whole-file batch on `## <video_id>` headings).
   The reply is parsed, validated, and — if it passes — written as an immutable `EpisodicNote` tagged
   `summary_source="external"`.

## Validation policy (what a reply must survive)

Enforced in `backfill_ingest.validate_result` / `ingest_result`:

- **Numbers → HARD-REJECT the whole reply.** Every numeric token in the reply's *prose* (`summary`,
  each theme, each mention's `reasoning`) must trace to the transcript's `grounded_values`
  (`summarize._build_evidence_pack` + `agentdesk.grounding.grounded_values` — the same gate the
  in-house summariser uses, which admits rounding, pairwise differences and ratios). A fabricated
  figure fails the reply; the operator re-pastes. `numeric_tokens` already drops years, whole dates,
  ordinals, indicator windows (RSI(14)) and small integers, so "the 2024 filing" never trips it.
- **Quotes are EXCLUDED from the number check** (matches `summarize._draft_prose`): a verbatim quote
  can only restate a number already in the source, and re-checking it re-adds false rejects from
  caption spacing. So a quote containing "2023년 3월 ... 11월" is fine.
- **Tickers → DROP-and-keep.** A `mention.symbol` the layered validator
  (`tickers.build_symbol_validator`, `allow_network=True`) cannot confirm is dropped from that one
  note, never a reason to reject the reply — a mangled caption word or a real future/index the
  provider omits (`GC`, `^GSPC`) must not discard an otherwise-faithful note.

A note written this way is `summary_source="external"`, `degraded=False`. Those two together mean "the
guardrails this path runs passed, and the in-house grounding gate never ran" — `degraded=False` here
is **not** "our gate passed".

## Browser recipe (driving Gemini Pro in a real browser)

Verified 2026-09-06/07 with Gemini **Pro Extended** in the owner's real Chrome. Two independent
sessions reproduced every step.

### INPUT — paste the whole packet via the OS clipboard

Gemini's prompt box is a **contenteditable DIV**: `form_input` and the synthetic
clipboard-read/`document.execCommand` paths do not work, and synthetic *typing* freezes past ~10k
chars. The path that works is the **OS-level clipboard paste**:

```powershell
Set-Clipboard -Value (Get-Content -Raw -Encoding UTF8 .backfill-tasks\<persona>__<video_id>.md)
```

then click the input box and press **Ctrl+V** (a real key event, not a synthetic one).

- **There is no ~9–16k size cap.** Full **24k-char packets** (complete 20–21k-char Korean transcripts)
  land whole (verified 24,321 chars). The earlier "condense to <9k and type it" advice was a limit of
  *synthetic typing*, never a Gemini limit — do not condense; condensing is what produced
  near-verbatim (not exact) quotes and had to be redone.

### GOTCHAS (each one silently produces a wrong or empty submission)

1. **First click after navigating to `/app` often fails to focus** (page still settling); the paste
   then no-ops and the editor stays empty. Fix: click the input a **second time** and re-paste.
2. **The clipboard is flaky on this machine** — it silently swapped one packet's contents for another
   between `Set-Clipboard` and Ctrl+V at least once (Windows Clipboard History / a clipboard manager).
   **Before submitting, verify the editor's `contenteditable` innerText both (a) has the expected
   length and (b) contains the right `Task id`** — not just that it is non-empty. Re-set and re-paste
   if wrong. (The ingest side is a second belt: it validates each reply against the packet read from
   disk *by `video_id`*, so a swapped transcript fails grounding rather than ingesting silently — but
   that only catches replies that contain numbers, so the task-id check is the primary guard.)
3. **PowerShell `Out-File -Encoding UTF8` writes a BOM.** Read pasted-back reply files with
   `utf-8-sig`, not `utf-8`, or `parse_result` sees no leading `{` and rejects the reply. (Or write
   replies with `[System.Text.UTF8Encoding]::new($false)` to avoid the BOM.)

### SUBMIT

A real **CDP coordinate click** on the Submit arrow is the only reliable trigger (sometimes it takes a
**double_click**); JS `.click()`, keydown-Enter and pointer-event dispatch are unreliable. The arrow's
coordinate **shifts with the sidebar state** (input centre ≈ 806px sidebar-collapsed, ≈ 925px
sidebar-open) — screenshot to locate it. Pro **Extended** shows a reasoning trace first, then emits the
```json block; allow ~30–40s.

### OUTPUT

The rendered ```json block is **virtualised** — `querySelector(...).innerText` comes back empty. Click
Gemini's **copy button** (top-right of the code block), then `Get-Clipboard -Raw` in PowerShell for the
full JSON. A "Supercharge Gemini" modal intermittently pops on a fresh `/app` and eats the prompt —
dismiss **"Not now"** first.

## Correcting a note (there is no `delete_note` API)

Episodic notes are immutable; `VaultStore` has `delete_persona` but no per-note delete. To re-do a note
(e.g. the 2026-09-07 exact-quote redo of the 3 condensed creator-a notes), do it **validate-first so
nothing is deleted on failure**:

1. Parse the new reply; get the **full transcript** from the packet via `backfill.find_task_packet`.
2. `validate_result` the reply against that transcript — **abort without deleting** if any number is
   ungrounded.
3. Delete the note file (`notes/<date>-<id>.md`) and its `transcripts/<id>.md` directly.
4. Recompute `persona.note_count = len(list_notes(slug))` and rebuild `tickers` from the remaining
   notes (there is no inverse of `_record_note`), then `save_persona`.
5. `ingest_result` with the full transcript and the **old note's preserved** `published` / `title` /
   `source_id` / `url` / `lang` / `transcript_source`.

Two sessions doing this on the same shared vault at once is safe: `ingest_result` converts a lost
`has_note`-then-`write_note` race into the same `PersonaError(409)`, and the recompute-from-disk makes
`note_count` self-correct — last-writer-won leaves a consistent vault (verified: 6 files, no dupes, no
`.tmp`, `note_count` correct, quotes verbatim). Still, **coordinate** to avoid duplicating the work.

## Known upstream limit

`youtube-transcript-api` and yt-dlp subtitle download are **IP-throttled (HTTP 429)** on the dev
machine (yt-dlp listing/metadata still works), so new packets can only be built from cached
transcripts until the block clears. A 2-hour Windows scheduled task (`InvDash-Backfill-Retry`, model-
free `tools/backfill_retry.cmd`) rebuilds packets once captions unblock; remove with
`schtasks /delete /tn InvDash-Backfill-Retry /f`.
