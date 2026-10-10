# Multi-timeframe rule research — feature surface design

Design document only. No application code changed by this document; every claim below was checked
against the current tree (paths and line numbers as of this read — the tree is dirty with other
sessions' edits, re-check before implementing).

Placement is explicitly **not decided** by this document, per the brief: the user said "I really
prefer to add this as a feature in the investing dashboard; it doesn't have to belong to the rules
tab" and that folding it into Rules is a later call. Section 3 makes a recommendation with an
argument; it is a recommendation, not a foregone conclusion.

---

## 1. What already exists (read before designing anything)

### 1.1 `Chart.tsx` — full capability assessment

File: `frontend/src/components/Chart.tsx` (lightweight-charts v4).

**Signature** (line 169):

```ts
export default function Chart({
  bars,
  series,
  ts,
  interval,
  colors,
  height,
  compact = false,
}: ChartProps)
```

```ts
interface ChartProps {
  bars: Bar[];
  series: IndicatorSeries[];
  ts: string[];
  interval: Interval;
  colors?: Record<string, string>;
  height?: number;
  compact?: boolean;
}
```

**`IndicatorSeries` type, verbatim** (from `frontend/src/api/market.ts:141-151`):

```ts
export interface IndicatorSeries {
  /** Round-trips to the spec string that produced it: `sma_50`, `bb_20_2`. */
  key: string;
  name: string;
  title: string;
  pane: Pane;                                   // "price" | "oscillator"
  /** Column name -> aligned values. Keys are `bb_20_2_upper` etc.; one key when single-output. */
  columns: Record<string, (number | null)[]>;
  /** Leading values that are `null` by definition. Studies drop this region; charts just gap it. */
  warmup: number;
}
```

**What it already does, confirmed by reading the whole file:**

- Candlesticks via `addCandlestickSeries` (line 229), themed from CSS vars, no gaps in support.
- Volume histogram (line 246-265), suppressed in `compact` mode (used by the four-up grid).
- **Price-pane overlays** — SMA, EMA, Bollinger Bands, anchored VWAP, anything server-tagged
  `pane: "price"` — drawn via `addLineSeries` per column (line 267-280), one line per output column
  (a 3-output Bollinger Band becomes 3 `addLineSeries` calls with dash-style differentiation between
  the midline and the envelope — `lineStyleFor`, line 52).
- **Oscillator overlays** (RSI, MACD) get a second stacked `IChartApi` instance (line 282-334) with
  its own histogram-for-`hist`-columns handling and a synced time-scale (line 336-355).
- Null-safe rendering: a `null` value becomes a lightweight-charts *whitespace* point rather than
  being dropped or coerced to 0 (`buildLinePoints`, line 99-118) — a Bollinger Band's warmup window
  gaps the line instead of drawing a false spike to zero.
- Per-instance colour assignment via the `colors` prop, keyed by `series[i].key` (so `sma:50` and
  `sma:200` stay visually distinct and stable across re-renders).
- Interval-aware time axis (`toTime`, line 72-77): `1d`/`1w` render as business-day strings, intraday
  renders as UTC-seconds timestamps.

**Conclusion: yes, `Chart.tsx` can already render SMA/EMA/Bollinger Band overlays at any interval its
`Interval` type carries, with zero changes.** It is driven entirely by whatever `IndicatorSeries[]`
the server hands it — there is no per-indicator special-casing to extend. Feeding it a 15m or 4h
bar series with an indicator response computed at that interval would render correctly *today*,
**if** the backend could produce bars and indicators at that interval (it currently cannot — see
§1.2).

**What is genuinely missing** for this feature, found by grepping the whole frontend tree for
`setMarkers` (zero hits — it is not called anywhere):

- **No way to mark a rule's firing bars on the candles.** lightweight-charts v4 exposes
  `ISeriesApi.setMarkers(markers: SeriesMarker<Time>[])` on the series object returned by
  `addCandlestickSeries`, but `Chart.tsx` never calls it and never exposes a prop for it. The
  `candleSeries` handle exists only as a local `const` inside the effect (line 229) and is discarded
  when the effect re-runs.
- This is a small, precise addition, not a rewrite: add an optional `markers?: ChartMarker[]` prop,
  convert each marker's timestamp through the same `toTime()` helper already used for bars/lines, and
  call `candleSeries.setMarkers(converted)` once after `candleSeries.setData(...)` (line 244). Add
  a stable JSON key for `markers` to the effect's dependency array (line 373), the same trick already
  used for `colors` via `colorKey` (line 182) — `useEffect` cannot dependency-compare an array by
  reference across renders. No other part of the component needs to change; the oscillator pane
  does not need markers (a rule fires against price action, not against RSI's own scale).

### 1.2 Interval reality check

**Backend** (`backend/app/db/duck.py:50-64`, `class Interval(StrEnum)`):

| Interval | Available history | Use |
|---|---|---|
| `1w` | unbounded | charts; derived locally from daily |
| `1d` | unbounded | **the only interval backtests may use** |
| `1h` | 730 days | charts |
| `5m` | 60 days | charts |

That is the complete enum. **There is no `15m` and no `4h` today, anywhere in the stack.**
`/api/rules/decisions?symbol=&interval=` (`backend/app/api/rules.py:135`) takes `interval:
Interval = Interval.DAY`, validated by FastAPI against this exact enum before the handler runs
(a malformed value is a 4xx, per that endpoint's own docstring) — so today it accepts only `5m`,
`1h`, `1d`, `1w`.

**Frontend** (`frontend/src/api/market.ts:23,25`):

```ts
export type Interval = "5m" | "1h" | "1d" | "1w";
export const INTERVALS: readonly Interval[] = ["5m", "1h", "1d", "1w"] as const;
```

This mirrors the backend enum field-for-field, as the module docstring promises elsewhere in this
codebase's client files. It already carries intraday values — `5m` and `1h` are not new — but **not**
the two the user explicitly asked for (15 minute, 4 hour).

**This corrects one line in the task brief I was given**, which described `/api/rules/decisions` as
"already tak[ing] an interval param — check what intervals it accepts today" without asserting what
they were. To be precise for whoever implements this: `5m`/`1h`/`1d`/`1w` exist end-to-end today;
`15m` and `4h` do not exist at any layer (enum, store, provider fetch, retention policy) and are new
backend work, not a plumbing change. They are not equally cheap to add, either:

- **`15m` is a native Yahoo interval** (Yahoo's own set is `1m,2m,5m,15m,30m,60m/1h,1d,5d,1wk,1mo,3mo`)
  — adding it is the same shape of work as `5m`/`1h` already are: a new enum member, a retention
  policy (guess: similar few-months window Yahoo actually serves at that granularity), a provider
  fetch path.
- **`4h` has no native Yahoo interval.** The existing precedent for this exact situation is `1w`,
  which the enum's own docstring says is "derived locally from daily" rather than fetched — `4h`
  would need the equivalent: derived by resampling stored `1h` bars (4 rolled up into 1), not fetched
  from a provider directly. This is real design work in `app.market.store`, not a one-line enum
  addition, and is out of scope for this document.

I flag this prominently because the user's exact list — "15 minute, 1 hour, 4 hour, 5 minute
candle... also we can track the accuracy of week candle as well" — spans six intervals, four of which
already exist (`5m`, `1h`, `1d`, `1w`) and two of which (`15m`, `4h`) require new backend work before
any of what follows can show real numbers for them. The feature design below assumes all six
eventually exist and is written to degrade honestly (an empty/greyed column, not a fabricated number)
for any interval not yet backed by data — the same "insufficient" vocabulary the decision table
already uses for sparse samples applies just as well to "this interval doesn't exist yet."

### 1.3 The existing Rules/Ticker split, and why it constrains this feature

`frontend/src/pages/Rules.tsx`'s own docstring (line 10-18) states the existing architectural line
explicitly:

> **Rule *definitions* are symbol-independent.** ... **Rule *evaluation* is not.** A decision table
> is a rule applied to one symbol's bars, so it stays on the ticker page where the symbol already is.

Rules.tsx today calls only `rulesApi.catalog()` (symbol-free) and embeds `<RuleEditor />` (also
symbol-free); the page is 137 lines and has no test file. `Ticker.tsx` (505 lines) owns
`<DecisionTable symbol interval />` — a rule *evaluated* against one already-chosen symbol.

The feature this document designs is **neither**. A rule × interval × symbol accuracy matrix is not
a rule definition (it needs bars), and it is not a single symbol's evaluation (it needs many symbols
or a comparison across them) — it is a third thing this app does not have a home for yet, which is
exactly why the user's own instinct ("it doesn't have to belong to the rules tab") is worth taking
at face value rather than resolving by default onto whichever existing page is closest.

### 1.4 Backend compute shape (for §7's estimate)

`backend/app/rules/service.py`'s `build_decision_table(cfg, symbol, interval, ...)` (line 151):

- Reads the bar store **once** per `(symbol, interval)` via `store.ensure_series` (line 179) — not
  once per rule.
- Shares one `IndicatorCache` (line 214) across every rule in the catalog, so N rules that reference
  the same indicator (e.g. two RSI-based rules) compute that indicator once, not N times.
- Shares one `signal_cache` keyed by the rule's canonical rendered expression, so textually-identical
  conditions evaluate once.
- All four `HORIZONS` (`[1, 5, 20, 60]`, `frontend/src/api/rules.ts:29`) come back from **one**
  `evidence_mod.compute_evidence(signal, bars)` call per rule (line 260) — horizons are not a
  separate fetch/compute axis, they are columns of the same call.

**The real unit of expensive work is one `(symbol, interval)` pair**, not one `(rule, interval,
symbol, horizon)` cell. The catalog currently holds **24 rules** (`backend/app/rules/catalog.py`,
grep count). A full accuracy matrix computation for one symbol across 6 intervals is therefore *not*
24 × 6 = 144 expensive calls, it is **6** — one `build_decision_table`-shaped call per interval,
each producing all 24 rules' rows at once. This materially changes the sync/async calculus in §8.

---

## 2. What does NOT exist that this feature needs

- **No sector taxonomy anywhere in the backend.** Grepped `sector` across `backend/app`: every hit is
  either a comment in a strategy-card JSON file (`app/paper/library/**`, describing a *card's* tilt,
  e.g. "semiconductors and sector/style funds") or unrelated (`institutions/catalog.py`,
  `discovery/*`). `Profile` (`frontend/src/api/market.ts:79-89`) carries `exchange`,
  `instrument_type` (`EQUITY`/`ETF`/`INDEX`/`CRYPTOCURRENCY`), and `currency` — no GICS sector, no
  industry. `backend/app/api/portfolio.py`'s `Position` model has no sector field either.
- **No per-bar signal trace crosses the wire today.** `evaluate()` produces a `pd.Series` of
  true/false/unknown per bar internally (`app.rules.evaluate`), but the only things that leave the
  process are the aggregate `RuleState` (current state, last trigger) and `Evidence` (aggregate
  hit-rate/median-return per horizon). Nothing today returns "which of these N bars did the rule fire
  on" as a list — that is exactly what chart markers need, and it is new backend surface, not a
  reshaping of existing output.

Both gaps are addressed concretely in §6 (markers) and §7 (sector/group dimension, API contract).

---

## 3. Placement recommendation

**Recommendation: a new top-level page, not an extension of Rules or Ticker, for the matrix and the
drill-down alike. Slice 1 (§9) makes zero changes to `Rules.tsx`, `Ticker.tsx`, `App.tsx`, or
`nav.ts` beyond the two files a brand-new page always requires.**

Argument, working through the options the brief poses:

- **(a) Extend the Rules tab — reject for now.** Rules.tsx is deliberately symbol-independent (its
  own docstring, §1.3); a matrix needs bars for every symbol in scope. Bolting a
  symbol/interval-dependent, potentially slow (§8) view onto a page whose entire reason for existing
  is "you don't have to pick a symbol first" inverts its stated purpose. This is also the option the
  user explicitly flagged as undecided — building toward it as the default would quietly resolve a
  question they asked to keep open.
- **(c) Extend Ticker.tsx — reject.** Ticker is already 505 lines and the repo has a recent, visible
  history of *splitting* pages that grew past this size rather than adding to them (per the brief's
  own framing). More importantly, Ticker's whole shape is "one symbol, at length" — profile,
  fundamentals, four-timeframe grid, decision table, news, institutional holders. A cross-symbol
  accuracy matrix is the one thing on this feature's wishlist Ticker structurally cannot host without
  becoming two pages wearing one URL. The user asked for cross-ticker and cross-sector comparison —
  that is multi-symbol by definition, and Ticker's whole reason for being is single-symbol.
- **(b) New top-level page — accept.** Call it **"Rule Lab"** (fits the existing "Strategy Lab"
  section's naming register better than "Timeframes," which describes the axis, not the question
  being answered) or "Timeframes" if the user prefers the literal name; either is a five-minute
  rename in `nav.ts` and doesn't affect anything else in this design. It sits in the existing
  **Strategy Lab** section of `nav.ts` (`frontend/src/nav.ts:69-79`), alongside Competition, Backtest,
  and Rules — that section's own blurb, "Testing ideas that are not yet mine," already describes this
  feature better than Portfolio or Market would. This costs exactly the two files the brief's own recon
  identified: one `<Route>` in `App.tsx` and one `NavItem` in `nav.ts`. Nothing else moves.
- **(d) Combination — accepted, but minimal.** The matrix (§4) and the drill-down (§5) both live on
  this one new page — a drill-down is a detail view *of* a matrix cell, not an independent
  destination, and giving it a separate route would be a fourth page for one feature with no reader
  who wants the second without the first. The only place the *existing* pages are touched, and it is
  optional even at that: Rules.tsx's catalog table could grow a single new "See accuracy" link per
  row pointing into Rule Lab pre-filtered to that rule, and Ticker.tsx's `DecisionTable` could
  similarly grow a link out to "see this rule across timeframes." Both are additive, one-line links —
  not edits to either page's actual content — and neither is required for Rule Lab to be useful on
  its own. **Slice 1 (§9) skips both links entirely**, so the placement question stays genuinely open
  after slice 1 ships: nothing about Rules.tsx or Ticker.tsx needs to be touched, reverted, or
  redesigned no matter which way the "should this live in Rules" question is eventually answered.

---

## 4. Primary view: the rule × interval accuracy matrix

### 4.1 Layout

One symbol (or one symbol-group — see §6) in scope at a time, chosen by a picker at the top; rules
as rows (grouped by the same informal category the catalog's `description` field already implies —
trend, mean-reversion, breakout, volatility — or left flat if the catalog has no formal category
field, which it currently does not); intervals as columns, in a fixed canonical order
(`5m, 15m, 1h, 4h, 1d, 1w`) so a reader's eye always finds daily in the same place. A horizon
selector (`1b / 5b / 20b / 60b`, matching `HORIZONS` and the existing tab styling in
`DecisionTable.tsx`) sits above the grid — the matrix shows one horizon at a time, exactly the
"compact view, one click to the rest" pattern `DecisionTable.tsx`'s own docstring already commits to
(reusing that decision rather than inventing a second one).

```
Rule Lab                                                          [ Rule×Interval ▾ ] [ Sym×Interval ]
────────────────────────────────────────────────────────────────────────────────────────────────────
Symbol/Group: [ AAPL            ▾ ]      Horizon: [ 1b ] [ 5b ] [●20b] [ 60b ]      [ Recompute ▸ ]

                     5m        15m        1h         4h         1d         1w
                  ┌────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
  sma_cross       │ +2.1pp │  +3.4pp  │  +1.2pp  │   n/a †  │  +6.8pp  │  +9.0pp  │
  (trend)         │ weak   │ suggest. │ insuff.  │  no data │ suggest. │ suggest. │
                  ├────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
  bb_squeeze      │ ░░░░░░ │  +0.8pp  │  +4.4pp  │   n/a †  │  −1.1pp  │  ░░░░░░  │
  (volatility)    │ insuff.│ insuff.  │ weak     │  no data │ weak     │ insuff.  │
                  ├────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
  rsi_oversold    │ +5.9pp │  +6.1pp  │  +5.0pp  │   n/a †  │  +2.0pp  │ ░░░░░░   │
  (mean-rev)      │ suggest│ suggest. │ suggest. │  no data │ weak     │ insuff.  │
                  └────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
                                                       ↑
                                          † 4h not yet available — see §1.2

  Legend: cell = edge (hit rate − baseline) at the selected horizon, colour = sign & magnitude.
  ░░░░░░ = insufficient independent sample (never a number). n/a = interval not computed for this rule
  (rule.intervals restricts it) or not yet backed by data at all.
  Click a cell → drill-down (§5).
```

### 4.2 Cell semantics and colour encoding

Each cell shows exactly what `DecisionTable.tsx`'s `EdgeCell` already shows for one `(rule, interval)`
at the selected horizon — **the edge, never the raw hit rate alone**, per `api/rules.ts`'s own module
docstring rule ("a hit rate must never be shown without its baseline... rendering the hit rate alone
is the single easiest way to make noise look like a strategy"). Concretely, per cell:

- **Primary number**: `edgeOf(evidence)` (existing helper, `api/rules.ts:180-183`), signed percentage
  points, formatted with the existing `formatSignedRate`.
- **Colour**: a diverging scale on the edge's sign and magnitude (green toward positive, red toward
  negative, saturation scaled by `|edge|` capped at some reasonable max like 15pp) — reusing the same
  `pos`/`neg` class convention `EdgeCell` already applies (`edge > 0 ? "pos" : edge < 0 ? "neg" :
  ""`), not a new colour vocabulary.
- **Significance badge**: the existing three-word vocabulary (`insufficient` / `weak` / `suggestive`)
  as a small label or dot under the number, using the existing `SignificanceBadge` component
  unchanged.
- **Insufficient-sample cells are visually distinct from a real number, not just labelled distinct.**
  A cell whose `significance === "insufficient"` (today's threshold: below both
  `weak_min_independent` and `weak_min_edge`, from the response's own `criteria` object — never
  hard-coded, per `DecisionTable.tsx`'s `SignificanceLegend` docstring) renders as a muted/hatched
  block with **no coloured number at all**, only the word "insuff." — the same principle
  `formatRate`/`formatSignedRate` already apply to `null` (em dash, never `0.0%`) extended to the
  whole cell: a low-confidence number is not a weak version of a real one, it is a different kind of
  answer and must not share a colour scale with real numbers a reader could compare it against by
  eye.
- **`n/a` cells** (interval not defined for this rule, via `rule.intervals`, or interval not backed by
  data at all — the `15m`/`4h` gap from §1.2) render as plain grey text, distinct again from both a
  real number and an insufficient-sample cell — three visually distinct "not a number" states for
  three different reasons, matching the three-valued `TriState` precedent already in this codebase
  (`state: "unknown"` must not be styled like `state: "false"`, `api/rules.ts`'s own docstring).

### 4.3 Drilling from a cell

Clicking any non-`n/a` cell opens the drill-down (§5) for that exact `(rule, interval, symbol,
horizon)`, either as an expandable row beneath the matrix (same interaction `DecisionTable.tsx`
already uses for "all horizons") or a side panel — either is a small implementation choice, not a
design one; an expandable row is more consistent with the row-expander pattern already established
by `DecisionTableRow`.

---

## 5. Drill-down view: one rule, one interval, one symbol

### 5.1 Layout

```
┌─ sma_cross @ 1h — AAPL ───────────────────────────────────────── [ × close ] ─┐
│                                                                                │
│  ┌──────────────────────────────────────────────────────────┐  Evidence       │
│  │  candles + sma:20 + sma:50 overlay, ▲/▼ markers on fires  │  @ 20b horizon: │
│  │  (Chart.tsx, unchanged component, + markers prop)         │   edge  +1.2pp  │
│  │                                                            │   hit  54.1%   │
│  │                                                            │   base 52.9%   │
│  │                                                            │   sample 812   │
│  │                                                            │   indep  61    │
│  │                                                            │   sig  insuff. │
│  └──────────────────────────────────────────────────────────┘                 │
│  Horizon: [ 1b ][ 5b ][●20b][ 60b ]      Entry: next-open                     │
│  State now: Firing · last fired 2026-08-24 14:00 (3 bars ago)                 │
└────────────────────────────────────────────────────────────────────────────────┘
```

This is deliberately close to what `Ticker.tsx` already assembles (`Chart` + `DecisionTable`'s own
per-row detail), reusing the same components and the same horizon-tab idiom rather than inventing a
fourth visual language for the same numbers.

### 5.2 Getting signal markers onto the chart — precise, not hand-waved

**Yes, `setMarkers` needs exposing, and it currently is not.** Confirmed by the grep in §1.1: zero
calls to `setMarkers` anywhere in `frontend/src`. The exact change:

1. Add to `ChartProps`:
   ```ts
   interface ChartMarker {
     ts: string;                          // same ISO string shape as Bar.ts / IndicatorSeries index
     position: "aboveBar" | "belowBar" | "inBar";
     color: string;
     shape: "circle" | "arrowUp" | "arrowDown";
     text?: string;
   }
   // ChartProps gains:
   markers?: ChartMarker[];
   ```
2. Inside the existing effect (line ~244, right after `candleSeries.setData(candleData)`), add:
   ```ts
   if (markers && markers.length > 0) {
     candleSeries.setMarkers(
       markers.map((m) => ({
         time: toTime(m.ts, interval),
         position: m.position,
         color: m.color,
         shape: m.shape,
         text: m.text,
       })),
     );
   }
   ```
   `toTime` already exists (line 72) and already handles the `1d`/`1w` business-day-string vs.
   intraday-UTC-seconds split correctly — markers reuse it rather than reimplementing time
   conversion.
3. Add a stable dependency key for `markers` to the effect's dependency array (line 373), the same
   way `colorKey` already exists purely to give `colors` (an object, compared by reference otherwise)
   a stable primitive to depend on.

No other part of `Chart.tsx` changes. `TimeframeGrid.tsx` and `Ticker.tsx`'s existing calls to
`<Chart ... />` simply omit the new optional prop and are unaffected.

**Where do the marker timestamps come from?** Not from anything the wire currently returns — see
§2's second gap. The drill-down needs a new backend response shape carrying the per-bar boolean (or
tri-state) trace, aligned to the same `ts[]` index `IndicatorResponse` already uses. See §7's
`/api/timeframes/signal` endpoint.

### 5.3 What's reused vs. new here

- **Reused, unchanged**: `Chart.tsx` (plus the one additive prop above), `IndicatorPicker`-style
  overlay selection (or a fixed, rule-implied overlay set — see below), the horizon-tab component
  pattern from `DecisionTable.tsx`, `formatSignedRate`/`formatRate`/`edgeOf`.
- **New**: the marker prop/logic (§5.2), and a way to know *which* indicators to overlay for a given
  rule. `RuleValidation.indicators` (`api/rules.ts:138`, "indicator specs the expression needs, e.g.
  `["rsi:14","bb:20,2"]`") already exists and is exactly the right shape for this — `/api/rules/
  validate` returns it for an arbitrary expression today, so the drill-down can call it (or the
  catalog can carry it precomputed per rule, avoiding a second network round-trip) to know which
  overlays to auto-select rather than asking the user to pick them by hand.

---

## 6. The ticker/sector dimension

**Honest framing given §2's finding: there is no sector taxonomy in this codebase today.** Designing
a "sector" axis as if `Profile.sector` already existed would be designing against data that does not
exist. Two honest paths, and a recommendation:

- **Path A (recommended for slice 1): symbol-group, not sector.** A "group" is just a named list of
  symbols the user defines — starting with the trivial free-text case (comma-separated symbols typed
  into the same picker used for the single-symbol case) and growing, if wanted, into named presets
  ("my portfolio," "my watchlist," a hand-typed "semis" list) persisted the same way `favorites.ts`
  already persists starred nav items client-side (this codebase already has a working precedent for
  small user-defined lists living in browser storage rather than a new backend table). This ships
  the *comparison* the user asked for — "how does this rule work across these tickers" — without
  inventing sector metadata the backend has no source for.
- **Path B (future, not slice 1): real sector metadata.** Would require a new field on `Profile`
  populated from a provider (Yahoo's `quoteType`/`summaryProfile.sector` if available, or a static
  ticker→sector lookup table analogous to `app/rules/catalog.py`'s static rule list) and is a
  meaningfully larger, separate piece of backend work — out of scope here, and not blocking Path A.

**The switch the user asked for** ("this rule across all sectors" vs. "this sector across all
rules") is implemented as an **axis swap on the same matrix component**, not two separate screens:

```
[ Rule × Interval ▾ ]   →  rows = rules,   columns = intervals,  filter = one symbol/group
[ Symbol × Interval  ]  →  rows = symbols, columns = intervals,  filter = one rule
```

Both are the same `MatrixResponse` shape from the wire (§7); the frontend just chooses which field
becomes the row key. This is the toggle sketched at the top-right of the wireframe in §4.1.

---

## 7. API contract

New router: **`backend/app/api/timeframes.py`**, not an extension of `rules.py`. Reasoning:
`rules.py`'s own module docstring commits it to being "thin," matching `app.api.macro`, with nearly
every endpoint a direct pass-through to one `service.py` function; a multi-symbol, multi-interval
matrix endpoint and a per-bar signal-trace endpoint are a different shape of concern (spanning
symbols, not evaluating one) and belong in their own router the same way `competition_jobs.py` is
its own file next to `competition.py` rather than folded into it. `rules.py` and its `service.py`
are still the thing this router calls into — `app.rules.service.build_decision_table` and a new,
small sibling function are the actual compute, this router is the multi-symbol/interval fan-out and
wire shape on top.

```python
# backend/app/api/timeframes.py
router = APIRouter(prefix="/api/timeframes", tags=["timeframes"])
```

### 7.1 `GET /api/timeframes/intervals`

Catalog of intervals this feature covers, distinct from `Interval` the enum, so the frontend can
render `4h`/`15m` columns as "not available yet" (§1.2, §4.2's `n/a`) rather than omitting them or
lying about coverage.

```jsonc
// response: list[TimeframeCatalogEntry]
[
  { "interval": "5m",  "available": true,  "note": null },
  { "interval": "15m", "available": false, "note": "not yet stored — needs a new provider fetch path" },
  { "interval": "1h",  "available": true,  "note": null },
  { "interval": "4h",  "available": false, "note": "not a native provider interval — needs derivation from 1h" },
  { "interval": "1d",  "available": true,  "note": null },
  { "interval": "1w",  "available": true,  "note": null }
]
```

### 7.2 `GET /api/timeframes/matrix` (synchronous, small requests)

```
GET /api/timeframes/matrix?symbols=AAPL&symbols=MSFT&intervals=1h&intervals=1d
                           &rule_ids=sma_cross&horizon=20
```

- `symbols`: repeated, 1..N (see §8 for the sync/async cutover).
- `intervals`: repeated, subset of the 6; defaults to every `available: true` interval from §7.1.
- `rule_ids`: repeated, optional; empty means the whole catalog (matches `/api/rules/decisions`'
  existing "empty means everything" convention).
- `horizon`: single value from `HORIZONS`, default 20 (matches `DecisionTable.tsx`'s own default).

```jsonc
// response: MatrixResponse
{
  "generated_at": "2026-08-25T12:00:00Z",
  "horizon": 20,
  "cells": [
    {
      "rule_id": "sma_cross",
      "symbol": "AAPL",
      "interval": "1h",
      "edge": 0.012,
      "hit_rate": 0.541,
      "baseline_hit_rate": 0.529,
      "sample_size": 812,
      "independent_sample_size": 61,
      "significance": "insufficient",
      "state": "true"
    }
    // ... one entry per (rule_id × symbol × interval) actually computed
  ],
  "skipped": [
    { "symbol": "AAPL", "interval": "4h", "reason": "interval_unavailable" }
  ],
  "criteria": { "weak_min_independent": 20, "weak_min_edge": 0.05,
                "suggestive_min_independent": 50, "suggestive_min_edge": 0.08 }
}
```

Each cell is a flattened, single-horizon `Evidence` plus its identifying keys — a reshaping of the
existing `DecisionRow`/`Evidence` shapes already returned by `/api/rules/decisions`, not a new
statistical concept. `criteria` is passed through unchanged from `app.rules.evidence` exactly as
`DecisionTable.criteria` already is, for the same "never hard-code the legend" reason
`DecisionTable.tsx`'s own `SignificanceLegend` docstring gives.

### 7.3 `POST /api/timeframes/matrix/jobs` + `GET .../jobs/{job_id}` (async, full sweeps)

Only for requests too large for §7.2's synchronous path (see §8's cutover). Mirrors
`app.tournament.jobs`'s `start_job`/`get_job` idiom — in-process daemon worker thread, immediate
`202`, poll for status — **but with its own registry, not the tournament module's global one-job
lock**. This feature does not touch the paper-trading mandate or the DuckDB contention
`tournament/jobs.py`'s lock exists for (bars are read, never written, by this feature), so sharing
that specific global lock would block an unrelated round for no reason; a scan of stored bars is
read-only and does not need mutual exclusion with a strategy round. A lighter, feature-local lock
(refusing a second concurrent *scan* job, not a second concurrent *anything*) is enough to keep two
sweeps from double-fetching the same symbol/interval from a rate-limited provider at once.

```python
class MatrixJobRequest(BaseModel):
    symbols: list[str]                 # empty = every symbol in the user's portfolio+watchlist
    intervals: list[str] = []          # empty = every available interval
    rule_ids: list[str] = []           # empty = whole catalog
    horizon: int = 20

class MatrixJobAccepted(BaseModel):
    job_id: str
    status: Literal["queued", "running"]
    total_cells: int                   # len(symbols) * len(intervals), the real compute unit (§1.4)
    created_at: dt.datetime

class MatrixJobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    completed_cells: int
    total_cells: int
    current: dict | None               # {"symbol": ..., "interval": ...}
    result: MatrixResponse | None      # populated once status == "succeeded"
    error: str | None
```

`POST /api/timeframes/matrix/jobs` → `202 MatrixJobAccepted`. `GET
/api/timeframes/matrix/jobs/{job_id}` → `MatrixJobStatus`, polled by the frontend the same way
`Competition.tsx` (824 lines, so read the polling hook it uses rather than reinventing one) already
polls competition jobs.

### 7.4 `GET /api/timeframes/signal` (per-bar trace, for drill-down markers)

The genuinely new capability from §2 — exposing the per-bar boolean trace `evaluate()` already
computes internally but never returns today.

```
GET /api/timeframes/signal?symbol=AAPL&interval=1h&rule_id=sma_cross
```

```jsonc
// response: SignalTrace
{
  "symbol": "AAPL",
  "interval": "1h",
  "rule_id": "sma_cross",
  "ts": ["2026-08-20T13:00:00Z", "2026-08-20T14:00:00Z", ...],   // same aligned index as IndicatorResponse.ts
  "state": ["unknown", "false", "true", "true", "false", ...]    // TriState, one per ts entry — same three values already defined in api/rules.ts
}
```

Frontend derives markers client-side: every index where `state[i] === "true"` and `state[i-1] !==
"true"` (a fresh firing, not every bar of a sustained condition) becomes one `ChartMarker` at
`ts[i]`. This endpoint is a thin new function in `app.rules.service` (evaluate once, same
grammar/evaluator path `build_decision_table` already uses, return the signal series instead of
folding it into `Evidence`) plus a thin router handler — not new statistical machinery.

---

## 8. Sync vs. async — decision and compute estimate

**Decision: both, cut over by request size.**

- **§7.2 (`GET /matrix`) and §7.4 (`GET /signal`) are synchronous**, with the same shape of
  guarantee `/api/rules/decisions` already gives (bars already stored → fast; a bad rule degrades its
  own cell, never 500s the whole response). Fine for: the drill-down (always exactly one
  `(symbol, interval, rule)` triple — trivially cheap, same cost as one existing `/api/rules/decisions`
  call already paid on every Ticker page load), and small on-demand matrix requests (a handful of
  symbols the user is actively looking at).
- **§7.3 (job-based) is required for a full-universe sweep** (§6's "every symbol in my
  portfolio+watchlist × every interval").

**Compute estimate, assumptions stated explicitly:**

- `N` = 24 rules (current catalog size, §1.4 — a real count, not a round-number guess).
- 6 intervals in the target design (`5m, 15m, 1h, 4h, 1d, 1w`); **4 exist today** (§1.2).
- `M` = 20 symbols, assumed as a generous single-user portfolio+watchlist size — this codebase has no
  enforced cap on watchlist/portfolio size I could find, so this is a working assumption to size the
  estimate, not a measured fact; adjust if the real number is known to be larger.
- Per §1.4, the expensive unit is **one `build_decision_table`-equivalent call per `(symbol,
  interval)`**, which internally computes all 24 rules × all 4 horizons in one pass via the shared
  `IndicatorCache`/`signal_cache`. A full sweep is therefore **M × intervals = 20 × 6 = 120** such
  calls, not 20 × 6 × 24 × 4 = 11,520.
- **If bars are already synced** (the common case for symbols the user already views on Ticker), each
  call is dominated by pandas indicator/rule evaluation over an in-memory frame — no network I/O.
  Order-of-magnitude guess (not measured): 0.2–1s per call for daily/weekly (few thousand rows), more
  for 5m/15m (60-day intraday history is still many thousand rows at 5-15 minute granularity). Call
  it **0.3–2s per cell** → **120 cells ≈ 36s–4 minutes** for a warm-store full sweep.
  **This alone is already too slow for a comfortable synchronous HTTP request** (most reverse
  proxies/browsers get uneasy well before 4 minutes), which is the real justification for §7.3, even
  before considering cold-store cost.
- **If bars are not yet synced** — guaranteed true the first time for `15m`/`4h` once those intervals
  exist at all, and possible for any symbol/interval the user hasn't looked at recently — each
  `(symbol, interval)` pair additionally pays a provider fetch (network round-trip, provider rate
  limiting, `5m`'s 60-day retention meaning a fresh symbol needs its whole available window pulled).
  That is seconds-to tens-of-seconds per pair on a cold cache, which for 20 symbols × 2 brand-new
  intervals alone (40 cold pairs) could add several more minutes on top of the warm-cache estimate
  above.
- **Conclusion: a full sweep is minutes, not seconds, dominated by cold-cache network I/O rather than
  the actual rule computation** — squarely the shape of work `app.tournament.jobs` already exists to
  handle for exactly this reason (long-running, best run once in the background, pollable, safely
  cancellable). A single cell or a handful of already-synced symbols stays comfortably synchronous.

---

## 9. Incremental delivery slices

Ordered so slice 1 is genuinely useful standalone and **commits to nothing about final placement** —
per the brief, that question stays open past slice 1.

**Slice 1 — walking skeleton, existing intervals only, single symbol, synchronous.**
- New page (route + nav entry only — the two files any new page needs, nothing else touched).
- Matrix for the 4 *already-existing* intervals (`5m, 1h, 1d, 1w`) only — no 15m/4h work yet, so no
  new provider/store work blocks this slice. `4h`/`15m` columns can render immediately as the `n/a`
  state from §4.2/§7.1 with an honest "not yet available" note, so the UI shape is already right when
  those intervals do land.
- One symbol at a time (Path A's trivial case from §6: a single text input, no group persistence
  yet).
- `GET /api/timeframes/matrix` (§7.2) only — no job endpoint, no `/signal` endpoint yet. The matrix
  reuses `build_decision_table` directly, called once per interval, with results reshaped into
  `MatrixResponse` — this is almost entirely a wire-shape and UI exercise over logic that already
  exists and is already proven correct on Ticker's `DecisionTable`.
- No drill-down chart yet — a matrix cell click can, for this slice, just deep-link to the existing
  `/ticker/:symbol` with the interval pre-selected (reusing the existing `DecisionTable` the reader
  already knows how to read) rather than building the new drill-down view. This ships the core
  "compare a rule across timeframes" value with the smallest possible new surface.

**Slice 2 — the real drill-down.**
- Add `markers` to `Chart.tsx` (§5.2), add `/api/timeframes/signal` (§7.4), build the dedicated
  drill-down panel (§5.1) in place of slice 1's deep-link-to-Ticker shortcut.

**Slice 3 — the group/sector dimension and the axis swap.**
- Path A groups (§6): free-text symbol lists, then named/persisted presets.
- The Rule×Interval ⇄ Symbol×Interval toggle (§6).

**Slice 4 — scale out.**
- The async job endpoints (§7.3), once slice 1's usage shows real appetite for "sweep my whole
  universe" rather than "check the one or two symbols I'm looking at" — building the job
  infrastructure before anyone has asked to run a 120-cell sweep would be solving a problem slice 1's
  own usage should confirm exists first.

**Slice 5 — 15m/4h backend work.**
- Independent of everything above and gated on its own backend design (new enum member + provider
  fetch path for `15m`; resample-from-`1h` derivation for `4h`, following the `1w`-derived-from-daily
  precedent already in the codebase). Slices 1-4 are all written to degrade honestly in this
  interval's absence and to light up automatically once it exists — no frontend rework needed when
  it lands, since the `n/a`/`available: false` handling from §4.2/§7.1 is the same code path either
  way.

**Only after slice 1-3 ship, with real usage data, does "should this move into (or link from) Rules"
become answerable** — which is the question the user explicitly deferred, and which this document
deliberately does not resolve on their behalf.
