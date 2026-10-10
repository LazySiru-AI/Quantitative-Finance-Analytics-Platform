# Personas frontend — handoff (backend is done and committed)

The backend for the persona feature is fully built, tested, and committed on `strategy-program`
(commits `8a4aa6c`, `fc1542a`, `71bae23`, and the ask/scheduler/card commits that follow). Two UI
surfaces are owed and belong to whichever session owns the persona frontend + i18n (the same one that
landed and translated the Phase 2/3a profile/scorecard views in `96cda54` / `807eb64`). They were left
undone deliberately so as not to collide with active i18n work on `frontend/src/pages/Personas.tsx`.

Everything below is already served by the API and pinned field-for-field in
[`docs/INFLUENCER-CONTRACT.md`](INFLUENCER-CONTRACT.md). No backend change is needed — mirror the wire
types and route strings, and route copy through the i18n catalog (do not hardcode English).

## 1. Fixed-horizon columns on the scorecard  (Phase 3b)

`GET /api/personas/{slug}/scorecard` now returns, in addition to the existing return-to-today fields:

- `PersonaScorecard.horizon_stats: HorizonStat[]` — one per horizon (5/20/60 trading days):
  `{ days, directional_count, played_out, hit_rate|null, median_return_pct|null }`.
- Each `CallScore.horizons: HorizonReturn[]` — `{ days, return_pct|null, complete }`.

Render the per-horizon hit-rate/median as the primary, window-independent measure; keep the existing
return-to-today number labelled "so far". `hit_rate: null` / `return_pct: null` (incomplete or zero
directional) must render distinctly from `0`, and `complete: false` as "too recent", never as a zero
return.

## 2. Chronological timeline view  (Phase 3b)

`GET /api/personas/{slug}/timeline` -> `PersonaTimeline`:
- `entries: TimelineEntry[]` (newest first) — `{ note_id, published|null, title, summary, themes[],
  symbols[], url }`. Render as a dated feed of what they said, each linking to `/ticker/{symbol}`.
- `stance_timelines: StanceTimeline[]` — `{ symbol, points: StancePoint[] }`, points OLDEST first so
  a symbol's stance evolution reads forward in time (bullish → bearish and when). Symbols whose stance
  actually changed are listed first — surface those prominently.

## 3. Ask-the-persona  (Phase 4, if landed by the time you read this)

`POST /api/personas/{slug}/ask {question, symbol?}` -> `PersonaAnswer` — see the contract's Phase 4
section. Render the answer plainly labelled as "a model's impression of <name>, from cited notes",
never as advice or as the person speaking; show the `citations` and the `degraded` flag.

## Guardrails (unchanged from the rest of the feature)
- Everything is the influencer's own view / a model's impression of it — never a signal, never advice.
- Citations and degraded flags are always visible. `null` aggregates are never rendered as `0`.

## 4. Persona paper book on the Paper Desk  (Phase 6)

`GET /api/personas/books` -> `PersonaBook[]` (and `/{slug}/book` for one). Render each as a book/seat
on the **Paper Desk page** (`/paper-desk`), beside the reference-agent books, so the owner sees "what
each influencer is currently positioned in" next to the strategy agents. `PersonaHolding` mirrors the
paper desk's `Holding` fields, so the existing holdings-table/row component should render it directly.

- Frame it as a descriptive paper projection following the influencer's live bullish calls (equal
  $10k/position since 2026-01-01), NOT a real position or advice.
- `holdings` empty + `as_of: null` is a valid "nothing currently bullish" state — render an empty
  book, not an error. `warnings` (unpriceable symbols) always shown.
- Money/quantity fields are decimal strings — use the existing `client.ts` money formatter.

## 5. Cross-pollination surfaces  (Phase 7)

- **Methodology on the profile** (7a): `PersonaProfile.methodology: ProfileClaim[]` — render a
  `## Methodology`/"How they trade" section on the profile panel (indicators, timeframes, entry/exit,
  risk rules), citations visible like beliefs/playbook. Empty for macro commentators — show nothing.
- **Consensus watchlist** (7b): `GET /api/personas/watchlist -> InfluencerWatchlist` — a table of
  `entries` (symbol, bullish_count, bearish_count, backers, latest_reasoning), symbols link to
  `/ticker/{symbol}`. Good on the `/personas` page header or a sidebar; render the `caveat`.
- **Persona strategy card** (7c): `POST /api/personas/{slug}/strategy-card -> StrategyCardDraft` — a
  button on the profile ("Draft a strategy from their method"). Render the produced `card` (universe,
  entry/exit, stops) with the `rationale`, `citations`, and the `caveat` prominent. When `mapped:false`
  (or a 409), show the `reason` plainly ("no mechanical methodology to map" / "no current-bullish
  tickers") — it is a valid answer, not an error. Frame the whole thing as an exploration lens, never a
  recommendation.

## 6. Rigor + auditability surfaces (Phase 8)

All additive; every stat now carries a denominator + CI, and the honest point-in-time views exist.

- **Confidence intervals everywhere** (P0.4): `PersonaScorecard.hit_rate_ci`, `HorizonStat.hit_rate_ci`/
  `return_ci`/`mean_return_pct`, `BenchmarkedHorizon.excess_ci` are all `StatEstimate {n, point, low,
  high, method}`. Render as "0.16 (n=192, 90% CI 0.11-0.22)"; when `point` is null show "no data", never
  0%. This is the primary "don't over-read a small sample" signal — give it visual weight.
- **Instrument badges** (P0.2): `WatchlistEntry.instrument` (equity/etf/index/future/crypto/fx). Badge
  non-equities and note they are not directly tradeable by the strategy layer.
- **Point-in-time toggles** (P0.1): `GET /watchlist?as_of=YYYY-MM-DD` and
  `GET /{slug}/book?as_of=&exclude_intraday=` — a date picker on the watchlist/book that removes
  look-ahead. Default (no as_of) is unchanged.
- **Regime panel** (P2.1): `GET /api/personas/regime -> RegimeConsensus` (risk-on/off tally +
  per-persona `RegimeView`); `PersonaProfile.regime` on the profile. This is what the macro commentators
  contribute (they have no methodology). Render risk/rates/sectors with citations; caveat prominent.
- **Strategy-card fidelity + history** (P2.2): `StrategyCardDraft` now has `version`, `fidelity`,
  `techniques_represented/total`, `unrepresentable[]`. Show fidelity as an honesty meter ("expresses
  4 of 15 techniques") and list what the DSL could not capture. `GET /{slug}/strategy-cards ->
  SavedStrategyDraft[]` for the draft history.
- **Profile drift** (P2.3): `GET /{slug}/profile/diff?from=&to= -> ProfileDiff` (added/removed/recited
  claims) — a "what changed in this persona's memory" view between versions.
- **Persona critique** (P3): `POST /{slug}/critique {card} -> CardCritique` — an in-voice verdict on a
  card. Pair it with the strategy-card panel ("what would they think of this?").
- **Incremental consolidate** (P1.1): `POST /{slug}/consolidate?incremental=true` — a cheaper "update"
  button beside the full re-consolidate.
