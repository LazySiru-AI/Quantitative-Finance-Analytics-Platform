# Influencer Personas — analysis and improvements plan

_Written 2026-09-03 after Phase 7 (cross-pollination) landed and the point-in-time round ran._
_Companion to `INFLUENCER-TAB-PLAN.md` (what was built) and `INFLUENCER-CONTRACT.md` (wire shapes)._

## 1. What the evidence says

Everything below is measured, not assumed. Commits: 7d7dbe5 (7a/7b), a461792 (7c), fabd184 (handoff).

| Measurement | Result | What it means |
|---|---|---|
| Vault | 216 notes across 5 personas (50/50/50/47/19) | Enough for profiles; **thin for statistics** — calls span ~Mar–Aug 2026 only |
| Methodology extraction (7a) | Creator E 15 techniques, Creator C 13; Creator A/Creator D/Creator B **0** | Works, and is honest: only the two technical traders describe a mechanical toolkit |
| Consensus watchlist (7b) | NVDA/PANW/PLTR top (3 backers), ~20 names with 2 | Descriptive reference; **"as of now" by construction** |
| Persona → card (7c) | Creator C → valid card; Creator E 409 (no current-bullish); macro trio 409 (no methodology) | Mapping works; refuses rather than invents |
| Round, hindsight universe | Creator C method × Sept-consensus: **+20.2%** vs SPY +12.4% (Feb–Aug) | Looks like edge |
| Round, same rule, May–Aug | biased universe **+11.7%**, point-in-time universe **−6.7%**, SPY +6.5% | **The edge was hindsight — an 18pp swing from universe selection alone** |
| Scorecard / backtest lens / paper books | trail SPY; Creator A hit-rate 0.16 | Consistent with the above and with the repo's 33-round record |

**Conclusion (unchanged, now proven rather than argued):** the personas are a reference tool — digest,
ask-in-voice, timeline, methodology, watchlist — with the scorecard/backtest as the "don't blindly follow"
guardrail. There is no discovered edge, and the one number that suggested one was survivorship bias.

## 2. Weaknesses the evidence exposes

Ordered by how much they distort what the feature *tells* the owner.

1. **Point-in-time is not a first-class primitive.** `watchlist`, `persona_book`, `_current_bullish_tickers`
   and 7c all use "latest stance as of now". Any backtest or lens built on them is biased the moment it looks
   backward. The PIT round had to hand-roll `consensus_bullish(as_of)` in a script. This is the root cause of
   the fake +20%.
2. **Instruments are untyped.** GC, CL, BZ (futures), BTC/ETH (crypto), NDX/SOX (indices) pass ticker
   validation and land in card universes, where they fail the causality guard (round A) or trade as if they
   were equities. The watchlist shows them beside NVDA with no distinction.
3. **Stance has no horizon.** `TickerMention` is `{symbol, stance, reasoning}`. A day-trader's "bullish" is
   an intraday view; treating it as a holding is why Creator E has methodology but zero "current-bullish"
   names, and why return-to-today scoring is window-dependent.
4. **Statistical power is near zero.** ~3.5 months of calls, one window, ~20 trades per card. Nothing here
   can distinguish skill from noise, and the UI does not say so numerically.
5. **Card drafting is non-reproducible.** Two drafts of Creator C produced `rsi-pullback` and `momentum-state`.
   Nothing persists a draft, so a card the owner looked at cannot be re-derived, and there is no measure of
   how much of a 15-technique methodology the 8-shape DSL could actually represent.
6. **The macro personas' value is unused.** Three of five personas are regime/macro commentators. 7c
   correctly refuses them, but nothing captures the thing they *are* good for — a structured macro/regime
   view — for the Agent Workflow desk's regime step or the owner.
7. **Backend-only surfaces.** Horizons, timeline, ask, backtest, book, watchlist, methodology and strategy
   card all lack UI (handed to the concurrent session via `PERSONAS-FRONTEND-TODO.md`).

## 3. Improvements, prioritised

Effort is rough: **S** ≤ half a session, **M** a session, **L** multi-session. Each item names its
verification so "done" is measurable, per the repo's rules.

### P0 — methodological rigor (cheap, removes the distortions)

**P0.1 Point-in-time stances as a primitive.** `app.personas.stances.bullish_as_of(notes, as_of) ->
tuple[str,...]` and `consensus_as_of(personas, as_of) -> InfluencerWatchlist(as_of=…)`; watchlist gets
`?as_of=`; `persona_book`/`backtest` take an `as_of`. Then a **walk-forward** mode for the paper book: the
universe is re-derived monthly from stances known on that date, so the persona book becomes a legitimate
out-of-sample record instead of a hindsight one. _Verify:_ unit tests that a note published after `as_of`
never influences the universe; the PIT round re-run through the endpoint reproduces −6.7%. **Effort M.**

**P0.2 Instrument typing + proxies.** Classify at mention time (`equity | etf | index | future | crypto |
fx`) via the existing profile lookup; `TickerMention.instrument` (additive, default `"equity"` for legacy
notes). Cards accept only `equity|etf`; the watchlist shows a type badge; an explicit, labelled proxy table
(GC→GLD, CL→USO, BTC→IBIT, NDX→QQQ) is offered — never applied silently. _Verify:_ round A no longer fails
the guard; a future in a card universe is a 422 with the proxy suggestion. **Effort S–M.**

**P0.3 Horizon on stances.** `TickerMention.horizon: intraday | swing | position | long_term | unclear`,
extracted by the summariser (the transcript usually says it). Scorecard scores each call at its own
horizon; paper book holds `swing`+ only; the timeline colours by horizon. Fixes the Creator E
category error and most of the window-dependence. _Verify:_ Creator E's book distinguishes "no
position-horizon calls" from "no calls". **Effort M.**

**P0.4 Say the sample size out loud.** Every stat (hit-rate, horizon returns, excess vs SPY) carries `n`
and a bootstrap 90% interval; the UI renders "n=23, CI −9%…+4%" beside the number. Cheap and it is the
single most honest change for a reader. _Verify:_ intervals widen as `n` shrinks; `n=0` renders as "no
data", never 0%. **Effort S.**

### P1 — more data, and the surfaces that carry the accepted value

**P1.1 Deep backfill.** Channels have years of content; we took the newest 50. Page the flat listing
(yt-dlp `playliststart`/`playlistend`) back to 2024 where captions exist. Turns ~5 months of calls into
~2 years, which is what P0.1/P0.4 need to say anything. Cost: ≈$0.01/note → ~$5–10 for 500–1000 more
notes, inside the $5 cap per run. **Incremental consolidation** alongside it (consolidate only notes newer
than `profile.consolidated_at`, merge into the standing profile) so re-consolidation stops scaling with
vault size. _Verify:_ note counts + date range per persona; consolidation cost per run flat as notes grow.
**Effort M (backfill) + M (incremental).**

**P1.2 Frontend for the reference surfaces** — in this order, because this is where the value was
accepted: ask-in-voice, methodology on the profile, timeline, watchlist (with type badges and
`as_of`), then scorecard/backtest with P0.4 intervals, then the strategy-card panel (with its caveat and the
fidelity score from P2.2). Owned by the concurrent frontend session per `PERSONAS-FRONTEND-TODO.md`.
**Effort L, other session.**

### P2 — make the speculative parts auditable

**P2.1 Structured macro/regime view from the commentator personas.** Consolidation extracts
`regime_view: {risk: on|off|mixed, rates, sectors_favoured, sectors_avoided, citations}` alongside
methodology — the counterpart for personas that have no mechanical method. Exposed as
`GET /api/personas/regime` (consensus + per-persona), descriptive, and offered to the Agent Workflow desk's
regime step as a *reference input it may cite, never a signal*. _Verify:_ macro trio populate it, technical
duo mostly don't; claims cite notes. **Effort M.**

**P2.2 Persist card drafts + fidelity score.** Drafts written to `strategy/<n>.json` (versioned like
profile history) so the owner can re-open the exact card they saw. The mapper also reports
`fidelity = techniques_representable / techniques_total` with the unrepresentable ones listed ("opening-range
box, multi-timeframe confirmation — not expressible in the DSL"). Optionally draft `k=3` candidates and show
all, so the shape choice is visibly a choice. _Verify:_ re-loading a draft yields the identical card;
fidelity for Creator E is low and says why. **Effort S–M.**

**P2.3 Profile drift.** `GET /{slug}/profile/diff?from=v1&to=v2`: claims added/removed/re-cited between
versions. Answers "is this persona's memory improving or churning?" — the one question the growing-memory
design raises and nothing currently answers. **Effort S.**

### P3 — optional, and blocked items

- **Persona critiques a card** (the reverse of 7c): `POST /{slug}/critique` with a `StrategyCard` → in-voice
  assessment grounded in their methodology. A reading lens, cheap on top of `ask`. **S.**
- **X / Telegram sources** — blocked on owner credentials; the manual-drop path already covers them
  keylessly.
- **Scheduled refresh on** (`persona_refresh_enabled`) once P1.1's incremental consolidation exists,
  otherwise daily re-consolidation is the dominant cost.

## 4. What not to do

- **Do not seat a persona card in the live tournament or Paper Desk as a competing agent.** The PIT round
  is the evidence: the same card swings 18pp on universe selection alone.
- **Do not turn the watchlist into a buy list or add a "follow" action.** It is what they said, ranked by how
  many said it.
- **Do not add another promotion gate for this.** The owner has weighted the live record over backtest
  gates twice already; the right fix is P0.1 — make the live record honest — not a new gate.
- **Do not report a return without `n` and the window** (P0.4). Every misleading number in this feature's
  history was a correct number missing its denominator.

## 5. Suggested sequence

1. **P0.1 + P0.2 + P0.4** together (one session, backend, ~40 tests) — they share the stance/instrument
   plumbing and immediately make every existing number trustworthy.
2. **P1.1** deep backfill in the background of (1) — it is mostly wall-clock, and P0.4's intervals only
   become informative once it lands.
3. **P0.3** horizon (needs a re-summarise pass over the vault to populate — fold into the backfill run).
4. **P2.1 → P2.2 → P2.3**, then P3 as appetite allows.
5. Frontend (P1.2) proceeds in parallel in the other session as each backend piece pins its contract.

Expected outcome, stated in advance so it can be checked: the reference surfaces get materially better;
the statistical surfaces get *honest* (wide intervals, walk-forward books trailing SPY); no alpha appears.
If step 1 changes that last sentence, that is the finding worth a dedicated OOS test — not a reason to skip it.
