# Influencer Personas — Implementation Plan

Status: **planned 2026-09-01 (revised same day), not started.** Execution begins on the owner's go.

## What it is

A new page under the **Agent Desk** section. Each followed influencer becomes **one persona agent with
its own growing memory**. The owner feeds it that person's content (YouTube videos first; pasted posts,
links or text for anything else). Every item is summarised and logged as a dated note in an
Obsidian-compatible vault. A consolidation step maintains a persona profile from those notes. The
persona can then (a) show what the person said recently, (b) answer "what would they say about X
now" against our own market data, and (c) be distilled into a strategy card and backtested through the
existing Competition machinery.

Everything a persona says is labelled as **a model's impression of the person, built from cited
notes**. Nothing here is a signal or advice, and nothing republishes the influencer's content.

## Design decisions

| Decision | Choice | Why |
|---|---|---|
| Memory store | Markdown files in an Obsidian vault folder (`INVDASH_VAULT_DIR`, default `data/vault/`) | No integration needed; the owner reads and edits notes in Obsidian and the agent reads the edits back |
| Memory layers | **Episodic** notes (immutable, one per video/post) and one **persona** `profile.md` (rewritten by consolidation) | Blending them lets the persona drift toward whatever was read last with no audit trail |
| Grounding | Reuse `app.agentdesk.grounding` with the notes as the `EvidencePack`; every persona claim cites a note | Same gate the desks already use; a belief with no cited note is rejected |
| First source | YouTube (RSS + transcript, keyless) plus a **manual drop** (URL or text) | Most text per source; the drop covers X/Instagram/Threads without any API key |
| Ticker safety | Every extracted symbol validated against the instrument table before it reaches a note or card | Auto-captions mangle tickers ("light path" for LITE) |
| LLM transport | `app.agents.client.call_structured` (SDK or Claude Code CLI) | No new credential; Haiku for per-item notes, Sonnet/Opus for consolidation and persona runs, spend-capped |
| Nav | Agent Desk section, `/personas` | It is a model-run desk with memory, not a market feed |

## Verified platform access (2026-09-01)

| Platform | Keyless path | Status |
|---|---|---|
| YouTube video list | channel RSS (`feeds/videos.xml?channel_id=`), last 15 videos; `yt-dlp --flat-playlist` for full back-catalogue | Phase 1 |
| YouTube transcript | `youtube-transcript-api` from a home IP (cloud IPs are blocked); `yt-dlp --write-auto-sub --skip-download` fallback | Phase 1 |
| YouTube official captions API | needs OAuth from the **video owner** | not used |
| Telegram public channel | `t.me/s/<channel>` preview, no login (fetched live) | Phase 5 |
| X | no free tier since 2026-02-06; pay-per-use, bearer token | Phase 5, or via manual drop |
| Instagram / Threads | official APIs cannot read other users without a Meta business app + App Review | manual drop only |

## Vault layout (pinned in `docs/INFLUENCER-CONTRACT.md` at Phase 0)

```
<vault>/influencers/<slug>/
  profile.md                 persona: beliefs, playbook, setups, risk habits, vocabulary. Every
                             bullet ends with [[note-link]] citations. Frontmatter: version,
                             consolidated_at, note_count, tickers.
  profile.history/<ts>.md    previous versions, so drift is visible
  notes/<YYYY-MM-DD>-<id>.md episodic: frontmatter {source, url, published, kind, tickers,
                             stances, transcript_source}; body = summary, quotes, links
  transcripts/<id>.md        raw transcript / post text, linked from the note
  theses/<SYMBOL>.md         running per-ticker view, each entry cites its note
  log.md                     append-only ingest + consolidation log with costs
```

## Wire contract (pinned at Phase 0)

```ts
type Platform = "youtube" | "telegram" | "x" | "manual";

interface Persona {
  slug: string; display_name: string; platforms: Platform[]; sources: FollowedSource[];
  note_count: number; profile_version: number; consolidated_at: string | null;
  tickers: string[];                      // validated symbols across notes
}
interface FollowedSource { source_id: string; platform: Platform; handle: string; url: string;
  enabled: boolean; added_at: string; }
interface EpisodicNote { note_id: string; persona: string; source_id: string; published: string;
  url: string; title: string | null; kind: "video_transcript" | "message" | "post" | "manual";
  transcript_source: "manual" | "auto" | null; summary: string; quotes: string[];
  mentions: TickerMention[]; path: string; }
interface TickerMention { symbol: string; stance: "bullish" | "bearish" | "neutral" | "unclear";
  reasoning: string; }
interface DigestCard { persona: Persona; as_of: string | null; window_start: string | null;
  headline: string; themes: string[]; mentions: TickerMention[]; latest_note: EpisodicNote | null;
  grounding: GroundingVerdict; warnings: { source: string; reason: string }[]; }
interface IngestJob { job_id: string; persona: string; state: RunState; items_total: number;
  items_done: number; started_at: string | null; finished_at: string | null; spent_usd: string;
  error: string | null; }
// Phase 3 persona runs reuse DeskRun with DeskKind "persona".
```

```
GET/POST/DELETE /api/personas, /api/personas/{slug}/sources
POST /api/personas/{slug}/ingest   {video_urls? | channel_backfill? | drop: {url?, text?}} -> IngestJob
GET  /api/personas/{slug}/ingest/{job_id}
GET  /api/personas/cards                          -> DigestCard[]   (always 200)
GET  /api/personas/{slug}/notes, /profile, /theses/{symbol}
POST /api/personas/{slug}/consolidate             -> IngestJob (profile rewrite)
POST /api/personas/{slug}/ask   {question, symbol?} -> DeskRun    (Phase 3)
POST /api/personas/{slug}/card                    -> strategy card draft (Phase 4)
```

## Phases

Each phase: contract first, Sonnet workers in parallel, QA pass, commit, report.

**Phase 0 — Contract + skeleton.** `docs/INFLUENCER-CONTRACT.md` (wire types + vault note
schema), `app/personas/models.py`, settings (`INVDASH_VAULT_DIR`, `INVDASH_PERSONA_INGEST_CAP_USD`),
router registered, `app.openapi()` route test.

**Phase 1 — Ingest + digest.** YouTube channel/video → transcript → episodic note + transcript file;
manual drop; ticker validation; digest card per persona; page with cards, add-persona form, ingest
form, job polling, note timeline. Fixtures captured from real responses. Verified in the browser
against the owner's channels. Owner opens `data/vault/` in Obsidian.

**Phase 2 — Persona consolidation.** `profile.md` rewrite with cited claims, history + diff in the
log, per-ticker `theses/`, profile view on the page. Owner edits in Obsidian survive (the model is
handed the current file and told which sections are owner-authored).

**Phase 3 — Ask the persona.** `DeskKind "persona"`: system prompt from `profile.md` + retrieved notes
(frontmatter index by ticker/date; embeddings only if the vault outgrows that), evidence pack from our
bars/indicators, grounding on, citations required. Renders through the existing DeskRun UI pattern.

**Phase 4 — Persona → strategy card → backtest.** Distil the playbook into the rule DSL, hand the
card to Competition. The card argues against the programme's null record, not the reverse.

**Phase 5 — Automation + keyed sources.** Scheduler flag (default off) polling followed channels;
Telegram public channels; X only if `INVDASH_X_BEARER_TOKEN` is ever provided.

## Guardrails

- Persona output is labelled "model's impression of <name>, from N cited notes"; never "signal".
- Episodic notes are never edited by the model; only `profile.md` and `theses/` are rewritten, with
  history kept.
- Transcripts stay in the private vault; no endpoint serves them outside the local app, and nothing
  is published (see `BEFORE-PUBLISHING.md`).
- Honest `User-Agent`, polite cadence, 15-minute cache through `CachingTransport`.

## Credentials and inputs

| Item | Needed for | Required? |
|---|---|---|
| Follow list: an example channel/handle, other YouTube channel URLs | Phase 1 | **yes** |
| Existing Obsidian vault path, if any (else `data/vault/`) | Phase 1 | optional |
| Anthropic access | all phases | already have (Claude Code login via CLI transport) |
| `INVDASH_YOUTUBE_API_KEY` | `@handle` resolution, durations | optional |
| `INVDASH_X_BEARER_TOKEN` | Phase 5 X source | only if wanted |
| Telegram `API_ID`/`API_HASH` + owner-run login | private groups | only if wanted |

## Sources
- https://developers.google.com/youtube/v3/guides/implementation/captions
- https://pypi.org/project/youtube-transcript-api/
- https://barseghyanartur.github.io/gistblog/posts/2026/06/grab-youtube-subtitles-with-yt-dlp/
- https://postproxy.dev/blog/x-api-pricing-2026/
- https://docs.telethon.dev/en/stable/concepts/botapi-vs-mtproto.html
- https://gist.github.com/jameschapman2c/65eff9f54a2d350b17a6ce5127b9fe42
- https://developers.facebook.com/docs/threads/keyword-search/
