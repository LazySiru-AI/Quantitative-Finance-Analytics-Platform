# Account page + Paper Desk + persona paper books — plan (2026-09-05)

Status: **PLAN ONLY — nothing below is built.** Owner reviews, then a session executes phase by phase
(commit + report per phase, per the usual Opus-orchestrates / Sonnet-builds / QA-proves workflow).

Source of the asks: owner voice note, 2026-09-05. Five items, restated:

1. Account page: the red "N basis/fee gaps…" box should be collapsed by default (headline only) and
   expand on click into a **chart** of the individual warnings, plus the existing detail.
2. Account page, positions table: **double-click the sector badge to change a symbol's sector**.
3. Account page, "By tax treatment" view: show each symbol's **deferred wash-sale loss**.
4. Paper Desk: less wording, hover-over info icons, two-decimal percentages, shorter empty states
   ("No market data: TICKER", not a sentence).
5. Influencer paper books: numbers are wrong (a "+6027%" return next to a small unrealised gain) and
   the design is unrealistic (unbounded $10k buys). Every book must start with **$100k cash**, buy
   only with cash it has, sell to fund new buys, and report realised P&L and a correct return.

---

## Findings (verified in code before planning)

### F1. The "+6027%" is a unit mismatch between backend and frontend — a real bug, not bad data
- `backend/app/personas/paperbook.py` emits `return_pct` as **percent**: `(last/entry − 1) × 100`,
  quantised to 0.01. Backend tests assert `Decimal("10.00")` for a 10% move.
- `frontend/src/components/PersonaBookCard.tsx` formats it with
  `formatSignedFractionPctString` (`@/api/paperdesk`), which expects a **0–1 fraction** and multiplies
  by 100 again. So 64.27% renders as `+6427.00%`.
- `PersonaBookCard.test.tsx` built its fixture with `return_pct: "0.0300"` and asserted `+3.00%`, so the
  frontend suite is green against a contract the backend never emitted (see memory:
  parallel agents invent each other's contracts). `docs/INFLUENCER-CONTRACT.md` Phase 6 types
  `return_pct: string` without saying which scale.
- Every other consumer of `formatSignedFractionPctString` (Paper Desk `Holding.return_pct`,
  `total_return`, benchmark) is a genuine fraction, so the fix belongs on the **backend**: emit a
  fraction, matching the paper-desk `Holding` the model docstring says `PersonaHolding` mirrors.

### F2. The book design is what makes "market value so various" and "endless buying" true
- Selection = every symbol whose latest stance is bullish since 2026-01-01, each bought with a fresh
  $10,000. No cash, no sells, no realised P&L. Counted from the vault today:

| persona | current-bullish symbols since 2026-01-01 | implied notional |
|---|---|---|
| creator-a | 168 | $1.68M |
| creator-b | 74 | $740k |
| creator-c | 42 | $420k |
| creator-d | 32 | $320k |
| creator-e | 0 | — |

- Bearish/neutral mentions exist in volume (87 / 111 / 124 / 73 per persona), so a stance-driven sell
  rule is feasible from the data already stored.

### F3. Sector is a hand-edited TOML with no write path
- `data/sectors.toml` → `app.market.sectors.sector_for` (lru-cached per path) → `Position.sector`.
  Frozen vocabulary of 20 labels in the file header. No API writes it today.
- `frontend/src/api/sectors.ts` (untracked) is another session's client-side copy for the allocation
  artifact. Leave it alone; the backend TOML stays the single source of truth.

### F4. Deferred wash-sale loss per symbol already exists on the wire
- `GET /api/tax/wash-sales` → `WashSaleTracker.symbols[].deferred_disallowed` (+
  `permanently_disallowed`, `window_is_open`, `repurchase_safe_on`). Frontend client:
  `washSalesApi.tracker()` in `frontend/src/api/washsales.ts`. Nothing new needed on the backend.

### F5. Warnings box
- `Portfolio.tsx` `WarningsSection`: always-open red callout = headline + group table + a `<details>`
  list of all individual warnings. `WarningGroup` = `{kind, account_id, broker, count, sample_detail}`;
  `TaxWarning` = `{kind, account_id, broker, symbol, trade_date, detail}` — enough for a chart by kind ×
  account, and by symbol, with no backend change.

### F6. Paper Desk wording
- 20+ strings in `frontend/src/i18n/messages/paperDesk.ts` exceed 110 characters (full list in
  Phase 1 below). Per-agent empty states are two sentences. Weight percentages use one decimal
  (`formatWeightPct` default `digits = 1`); the owner wants two.

---

## Phases

Order chosen so the cheapest, highest-value fix ships first and the biggest redesign last. Each phase
is independently committable; the shared tree currently holds another session's uncommitted edits
(`backend/app/agentdesk/models.py`, `backend/app/workflow/*`, `data/loop/ledger.jsonl`,
`frontend/src/api/sectors.ts`) — stage by explicit path only.

### Phase 1 — fix the return scale + Paper Desk copy (frontend-heavy, ~half day)

**1a. `return_pct` scale (backend).** In `paperbook.py` emit `return_pct` as a fraction quantised to
4 places (`0.6427`), both per holding and per book. Update `tests/test_personas_paperbook.py`
(`Decimal("10.00")` → `Decimal("0.1000")`, 4 sites) and the Phase 6 section of
`docs/INFLUENCER-CONTRACT.md` ("`return_pct` is a 0–1 fraction, like paperdesk `Holding.return_pct`").
Frontend unchanged; its fixture was already a fraction. Add one frontend test that feeds a
backend-shaped fixture (`"0.6427"` → `+64.27%`) so the two sides are pinned to the same number.

**1b. Warning wording (backend, three files).** `paperbook.py`, `scoring.py`, `backtest.py`:
`"no market data available (…)"` → `"no market data"`; `"no bar at or after {d}"` → `"no bar since {d}"`.
Card renders `SYM: no market data`. Provider detail moves to the log line only.

**1c. Paper Desk copy pass (frontend, i18n en+ko).** Rewrite every `paperDesk.*` string over ~90
characters to a ≤70-character headline, with the explanatory clause moved behind an `InfoNote`
disclosure or an info-icon `title` (the primitives from the density pass). Known targets, by key line
in `paperDesk.ts`: 25, 29, 79, 103, 119, 140, 148, 152, 174, 189, 218, 229, 250, 298, 351, 361, 388,
397, 406. Examples:
- 148 → `No trades yet · 100% cash` (+ info: "entry rule never fired; flat is no trade, not breakeven")
- 140 → `Buy-only desk · never sells` (+ info)
- 103 → `In-sample through {cutoff}` (+ info)
Tile labels on `DeskPanel` / `BookStatistics` get an info icon with the definition on hover
(`Excess vs. benchmark`, `Sessions to time stop`, `Capital exposure`…).

**1d. Two-decimal percentages.** `formatWeightPct(value, 2)` on Paper Desk and persona cards; audit
`toFixed(1)` / `digits = 1` call sites on `PaperDesk.tsx`, `paperdesk/*.tsx`, `PersonaBookCard.tsx`.

QA: vitest for `PersonaBookCard` and i18n completeness (`tsc` enforces en/ko parity); pytest
`tests/test_personas_paperbook.py`, `tests/test_personas_scoring.py`, `tests/test_personas_backtest.py`;
screenshot of the Paper Desk before/after.

### Phase 2 — editable sector + deferred-loss column (Account page, ~1 day)

**2a. Backend sector write path.** In `backend/app/api/portfolio.py`:
- `GET /api/portfolio/sectors` → `{vocabulary: string[], map: {SYMBOL: label}}` (vocabulary = the
  frozen list in the TOML header, lifted into `app.market.sectors.SECTOR_VOCABULARY`).
- `PUT /api/portfolio/sectors/{symbol}` body `{sector: string}` → 422 unless `sector` is in the
  vocabulary; upper-cases the symbol; rewrites `data/sectors.toml` **preserving the header comment**
  and emitting `[sectors]` sorted by symbol; then `_load_map_cached.cache_clear()`. Returns the new map
  entry. `"Unclassified"` is a legal value (removes the entry).
- Tests (`tests/test_sectors_api.py`, tmp `data_dir`): round trip, header preserved, invalid label
  422, cache invalidated so the next `/api/portfolio` shows the new sector. Endpoint tests must run
  with the `settings` fixture or `INVDASH_AUTH_ENABLED=0` (memory: auth gate fails fixtureless tests).

**2b. Frontend inline editor.** New `SectorBadgeEditor` used by both `PositionRow` and
`AccountPositionRowView` (`Portfolio.tsx`): double-click the badge → `<select>` of the vocabulary,
Enter/blur saves, Esc cancels, saving state shown on the badge, error shown inline. On success call
`usePortfolio`'s refetch (add one if it has none) so every view and the sector filter update. Client
in `frontend/src/api/portfolio.ts` (`portfolioApi.sectors()`, `.setSector(symbol, sector)`), i18n keys
`portfolio.sector.edit*`. A `title` on the badge says "Double-click to change sector".

**2c. Deferred loss in "By tax treatment".** `TaxTreatmentView` fetches `washSalesApi.tracker()` once
(own fetch state; a failure degrades to "—" with a one-line caveat, never blanks the view). Build
`Map<symbol, WashSaleTrackerSymbol>`. `AccountPositionsTable` gains an optional `washBySymbol` prop;
when present it renders a sortable **Deferred loss** column (`formatMoney(deferred_disallowed)`,
"—" when the symbol has no wash events; `title` = "window open until {repurchase_safe_on}" when
`window_is_open`). The taxable group also gets a **Deferred loss** `MoneyTile` (sum over its symbols)
with the standing caveat that deferred and permanently-disallowed are never summed. Retirement group:
column shows "—" (losses there are not deductible) — one caveat line, not a column of dashes.

QA: vitest for editor (double-click, save, cancel, error) and for the column/tile; pytest for 2a;
browser check on the Account page with the dev launcher (memory: port 8000 / localhost notes).

### Phase 3 — collapsible warnings box with a chart (Account page, ~half day)

- `WarningsSection` becomes a `<details>`: collapsed shows only
  `632 basis/fee gaps the replay could not resolve` (+ chevron). Nothing else renders until opened.
- Open: new `WarningsChart` (hand-rolled SVG, same pattern as `AllocationPie.tsx`; no new dependency —
  `lightweight-charts` is the only chart lib and is wrong for this). Horizontal bars, one per warning
  kind, segmented by account (colour per account, legend), count label at the bar end, hover tooltip
  "{kind} · {account} · {n}". A second, smaller "top symbols" bar list (from `TaxWarning.symbol`) since
  that is the question the owner actually asks ("which tickers are the gaps in?"). Then the existing
  group table and the "show all" list, unchanged.
- Headline copy trimmed to the count + kind phrase; "grouped below by kind and account:" moves inside.
- Tests: collapsed by default, expands, chart bars = group counts, symbol list sorted desc.

### Phase 4 — cash-constrained persona paper books (backend + frontend, ~2 days)

**Contract first** (pin field names in `docs/INFLUENCER-CONTRACT.md` Phase 6 before any code, then
backend and frontend build in parallel against it).

**4a. Replay rules** (`app/personas/paperbook.py`, keep `build_persona_book` name; old equal-notional
mode removed, not kept as a flag):
- `STARTING_CASH_USD = 100_000`, inception 2026-01-01, `NOTIONAL_PER_POSITION = 10_000` (so at most
  10 open positions; that is the "compare which one is good" constraint made mechanical).
- Walk every mention in `said_on` order (skipping notes before inception). Per mention:
  - `bullish`, not held → **BUY** at first close on/after `said_on`, qty = 10k / price, if cash ≥ 10k.
  - `bullish`, already held → no trade; refresh `last_bullish_on`.
  - `bearish` or `neutral`, held → **SELL** at first close on/after `said_on`; realised P&L booked;
    cash returned. Not held → no-op.
  - `unclear` → no-op. `horizon == "intraday"` → ignored (a scalp is not a holding); the
    `exclude_intraday` query flag goes away, the rule is now the default and documented.
  - Book full / cash < 10k on a new bullish call → **`on_full_book`** rule (owner decision, see below).
- Marks: latest close on a shared basis (adjusted when both ends have it, as today). No look-ahead:
  entry/exit are never earlier than the note.
- A symbol with no bars: excluded and warned (`SYM: no market data`) — and if it was *sold* later,
  the sell is also dropped (nothing to sell).
- Money stays `Decimal`; `return_pct` is a fraction (Phase 1a).

**Owner decision — `on_full_book`.** Recommended default: **`replace_stalest`** — sell the open
holding with the oldest `last_bullish_on` to fund the new call, and record the trade with reason
`"replaced to fund {SYM}"`. The alternative **`skip`** records the call under `skipped` ("no cash")
and buys nothing. `replace_stalest` matches the owner's framing ("they gotta sell something"); `skip`
never invents a sell the persona did not make. Shipping as a module constant, not a query flag.

**4b. Wire shape** (additions to `PersonaBook`; `PersonaHolding` unchanged except `last_bullish_on`):
```
starting_cash: Money            cash: Money             equity: Money   # cash + market_value_total
realised_pnl_total: Money       unrealised_pnl_total    return_pct: Decimal  # equity/starting_cash − 1
trades: PersonaTrade[]          # closed: symbol, entry_date, entry_price, exit_date, exit_price,
                                #   quantity, realised_pnl, return_pct, reason ("stance flipped bearish"
                                #   | "stance flipped neutral" | "replaced to fund X"), note_id
skipped: PersonaSkippedCall[]   # symbol, said_on, reason ("no cash" | "no market data" | "no bar since d")
trade_count: int                open_count: int
```
`notional_per_position` stays. `cost_basis_total`/`market_value_total` now cover open positions only.

**4c. Frontend card** (`PersonaBookCard.tsx`, `personaBook.ts` i18n):
- Tiles: Equity · Cash · Unrealised P&L · Realised P&L · Return (2 dp), each label with an info icon.
- Caveat shortened: `Paper book · $100k from 2026-01-01 · $10k per call · sells on a bearish/neutral
  flip · not advice` with the full rule behind an `InfoNote`.
- Collapsible sections (`ScrollRegion`): Holdings (default open), Closed trades, Skipped calls.
- Warnings as a compact line `SYM: no market data`, not a bulleted list.
- Desk-section heading/caveat on `PaperDesk.tsx` shortened to match.

**4d. Verification (QA, not the builder).** Compute every book offline through `.venv` and check:
`equity == cash + Σ market_value`; `return_pct == equity/100000 − 1`; cash never negative at any step;
every open holding traces to a bullish note; every trade traces to a bearish/neutral note or a
replacement; one holding's return recomputed by hand from stored bars; creator-a holds ≤ 10 names.
Then the Paper Desk in the browser, both languages.

Tests: rewrite `tests/test_personas_paperbook.py` around the replay (buy, no-cash skip/replace, sell
on flip, unclear no-op, intraday ignored, no-look-ahead entry/exit, warnings), `tests/test_api_personas.py`
shape; vitest for the card sections.

---

## Out of scope (say so rather than drift)
- Wash-sale rules on the persona book (paper, untaxed, like the other paper desks).
- Sizing by conviction or by persona horizon; 10k flat is the contract.
- Touching `frontend/src/api/sectors.ts` (another session's file).

## Gates before each commit
`.venv` pytest for the touched suites (a bare `python -m pytest` exits 0 with nothing run), `ruff`,
`mypy` from inside `backend/`, `npm test` + `tsc` in `frontend/`; check for another session's running
pytest first.
