# UAT button sweep — 2026-08-29

A five-way parallel click-through of every route in the app, run by five subagents against
`http://localhost:5192` (current frontend source via Vite HMR) proxying `/api` to the isolated
`run12` sandbox backend on port 8012. No real financial data was touched.

**This is not a persona trading run.** `uat/README.md` describes the weekly `pro-investor-01` run
that trades the dashboard and files findings. This is the other kind: one pass over every control on
every page, asking only "does this do what it says". It shares the README's isolation guarantees and
its verification rule, and nothing else.

> **A persona finding is a report, not a fact.** Every finding below carries a verdict from the
> orchestrator, reproduced independently before being believed. Four of the five confirmed findings
> are now fixed; the fifth is a feature, and is named as one rather than left looking pending. That rule earns its keep here: of the
> nine findings filed, **three did not survive verification**, and one of those three was filed as a
> `major`. `uat/README.md` records the same ratio from the first-ever run (three of four reported
> blockers did not reproduce).

## Coverage

| Worker | Routes | Controls | Filed | Confirmed |
|---|---|---|---:|---:|
| money | `/overview`, `/portfolio`, `/activity` | ~35 | 2 | 1 |
| tax | `/tax`, `/wash-sales` | 1 + full DOM audit | 0 | 0 |
| market | `/ticker`, `/ticker/:symbol`, `/macro`, `/timeframes`, `/institutions`, `/consensus` | ~70 | 3 | 2 |
| research | `/backtest`, `/rules`, `/thesis`, `/report`, `/paper-desk` | ~45 | 3 | 3 |
| competition | `/competition` × 7 tabs, 404 route | ~30 | 1 | 1 |

All 17 routes in `App.tsx` were visited. Per-route detail is in the `findings-*.md` files beside this
one.

## Confirmed and fixed

### 1. The ticker chart crashed on every 4h → 1d switch — `blocker`
Reproduced 3/3 by the worker on SPY and QQQ; React error boundary, lightweight-charts'
`Assertion failed: data must be asc ordered by time`.

Not bad data — the API is clean at every interval (checked: ascending, zero duplicate timestamps).
`Chart.toTime` renders a daily bar as a `"YYYY-MM-DD"` business-day string and an intraday bar as
epoch seconds. `Ticker` passed its own `interval` state next to `single.bars`, and on an interval
change React re-renders with the **new** interval one render before the fetch effect has run — so the
chart received the old 4h bars labelled `1d`, sliced every intraday timestamp to its date, and
produced **499 duplicate date strings out of 998 bars**. `barsPhase === "loaded"` cannot guard it: the
phase is set inside the very effect that has not run yet.

That also explains the asymmetry the worker noticed: daily bars rendered as intraday stay strictly
ascending, so 1d → 4h never crashed.

**Fixed** by publishing `barsInterval` from `useChartSeries` — the interval the bars were actually
fetched with — and pairing the chart with that instead of the selection, making the mismatch
unrepresentable rather than merely unlikely. Verified in the browser: 3/3 cycles clean, no console
errors. 4 regression tests in `frontend/src/hooks/useChartSeries.test.ts`.

### 2. Every card on round 15's Agent tab returned a bare 500 — `major`
Confirmed against **current** code, not only the sandbox.

`load_round_results` validates every run file in a round as an `AgentResult`, whose `card` is a
`StrategyCard`. Round 15 is entirely allocation and ladder cards, which validate against neither, so
one file raised out of the loader and took the whole request with it.

The limitation was already documented — `load_round_scored_runs`'s docstring says outright that
`load_round_results` "cannot read [them] at all" and "still backs `build_leaderboard`/
`build_agent_detail`". What nobody had recorded is that the user-visible consequence is an unhandled
500. It stayed hidden because **the leaderboard was correct the whole time**: that path uses the
newer shape-aware loader, so the round ranked perfectly while its Agent tab could not open a single
card.

**Fixed** with a tolerant reader used only by `build_agent_detail` (`load_round_results` is left
alone — it backs scoring, and loosening a scoring reader to fix a display bug is how a leaderboard
silently loses a card, DEFECTS.md D3), plus a new `AgentShapeUnsupportedError` → **422**, deliberately
not 404: "did not run" and "ran, and this view cannot render it" are different facts, and round 15
exists precisely to have measured those shapes for the first time.

`AgentSection` also rendered errors with `className="placeholder"` — identical styling to a
legitimate empty state, which is why "Internal Server Error" read as "nothing here". Now
`callout-danger` with `role="alert"`.

**Not fixed, and not a defect:** the Agent tab still cannot *render* allocation/ladder cards. That
view shows entry/exit trades and a sleeve-weight card has none. That is a feature.

### 3. Rule-DSL inputs accept malformed expressions with no feedback — `minor` × 3
`/rules` validates live and reports `NOT VALID` / `expected a value, found '>'`. The same DSL inputs
elsewhere accept `close >>> sma(` silently and leave the run button enabled:
`/backtest` Event Study condition, `/backtest` Scan textarea (per line), `/report` Strategy Backtest
entry/exit. Notably the Scan **does** correctly disable its button for non-numeric horizons — the page
can gate this control, it just does not do so for rule syntax. One defect, three sites.

**Fixed 2026-08-29** with one shared `useRuleValidation` hook rather than three copies of
`RuleEditor`'s effect. All three now show the parser's own message inline and disable their run
button. The part worth reading is what does *not* disable it: a check that is merely slow, or a
validate endpoint that is down, never takes the control away -- it falls open, and the reader gets
the server's own error instead of being locked out. Verified in a browser with
`/api/rules/validate` stubbed to reject.

### 5. Overview's calendar panel hangs ~8s on a cold cache — `minor`
Confirmed as cold-start only: warm, `/api/calendar/events` answers in **0.60s** and **0.54s** on
consecutive calls, consistent with the documented once-a-day Nasdaq sweep. The worker's UX point
stands regardless — an 8-second wait with no progress or timeout affordance deserves a loading state.

**Fixed 2026-08-29.** `useEventCalendar` now exposes `slow`, true once its own fetch outlasts 2.5s --
above the warm response so an ordinary load never trips it, below the cold one so this case always
does. The card uses it to explain the wait rather than to show a busier spinner, in an
`aria-live="polite"` region so the second line reaches a screen reader too. The error branch also
gains the **Try again** noted as missing; `refresh()` already existed and nothing called it.

## Confirmed, not fixed

### 4. The Timeframes "Universe" scope tab can never succeed — `major`, reclassified
`GET /api/timeframes/matrix?scope=universe` → 422:
`request resolves to 140 (symbol, interval) pairs (20 symbols x 7 intervals), exceeding
MAX_SYNC_PAIRS=20; submit this as a sweep via POST /api/timeframes/matrix/jobs instead`.

The **backend is correct and deliberate** — it refuses an oversized synchronous request and names the
async route to use. The defect is the UI: it offers a scope tab that is guaranteed to fail, then
prints raw backend prose to the reader. The real fix is wiring the sweep-job endpoint and polling,
which is a feature, not a repair; a cheap interim fix is a human message naming the async route.

## Filed but not reproduced

### 6. "MAX range button looks inert for US Dollar Index and Bitcoin" — `works-as-designed`
`/api/macro/series/{id}` takes **no range parameter at all** (only `series_id` and `as_of`); the range
tabs filter client-side. Every series in this sandbox holds ~8.5 months (2025-12-15 → 2026-08-27), so
`1Y` already contains everything and `MAX` is identical — **for all twenty tiles, not two**. The
differing counts quoted (176 for DXY vs 256 for BTC over the same dates) are Bitcoin trading seven
days a week. An artefact of sandbox data extent.

### 7. "Only holdings I also own" checkbox has no effect — `not-reproduced`
It works. Driven with the native setter plus a bubbling event, the Full Holdings table goes
**105 → 0 → 105** rows. It filters to zero because no sandbox holding matches the book, which is the
long-documented CUSIP caveat in `Institutions.tsx` — a note that already records *"Two independent UAT
runs filed that on the same day."* This is the third. The worker most likely set `.checked` directly,
which React does not observe.

### 8. A `/tax` in-page link did not navigate on two clicks — `inconclusive`, correctly self-filed
The worker declined to call it a defect; direct navigation worked immediately after. Tab-focus
contention, see below.

## Two things that limit what this sweep proves

**The sandbox ledger is nearly empty.** 4 transactions, 3 instruments, 1 account, **zero disposals**.
So the reconcile panel, the Form 8949 table and the wash-sale detail rows never rendered at all.
"0 findings" on `/tax` and `/wash-sales` means *the empty state is correct*, not *the tax engine is
correct*. A seeded-ledger pass is the obvious follow-up and would be worth more than re-running this
one.

**Coordinate clicks do not reliably reach React's handlers in this harness.** Four of the five workers
hit this independently and worked around it with JS-dispatched events. It is a property of the shared
multi-tab CDP session, not of the app — and it is exactly the failure `uat/README.md` warns about. It
is also, directly, the cause of finding 7 and probably of finding 8.

## Deliberately out of scope

Job-launching controls were excluded from the parallel pass: they take a process-wide lock on the
DuckDB bar store, and concurrent runs would have manufactured false failures across the other four
workers. Left unpressed, all observed enabled unless noted:

- `/competition` — "Start the loop", "Plan the next round"
- `/backtest` — "Run event study", "Run N tests" (Scan), "Profile" (reverse conditioning)
- `/thesis` — "Run thesis loop (budget N)"
- `/report` — "Run strategy" (disabled while the entry rule is empty, as designed)
- `/paper-desk` — "Apply" (re-runs every agent from the chosen inception), "Fetch latest data"

Paper-desk queue transitions (approve / seat / shelve / reject / retire) were also excluded as
decisions a person is meant to make. No such controls exist in this sandbox anyway — all three books'
queues are empty.

These need a serial pass against a sandbox backend, one job at a time.

### The serial pass — complete

Every excluded control was run afterwards, one at a time, nothing else running.

**Through the API, against the `run13` sandbox on port 8013 (current code):**

| Action | Result |
|---|---|
| `POST /api/competition/loop` | `202`, `state=running` |
| second `POST` while running | **409** — the documented single-slot guard |
| `DELETE /api/competition/loop` | `200` → `stopping` → `stopped`/`idle`, without completing a generation |
| `promotion_max_shared_windows=2` | **400**, naming the achievable floor |
| `purposes: []` | **422**, the `min_length=1` guard |

Nothing was promoted; `pending-seats` stayed empty.

**Through the UI on `:5192` → the `run12` sandbox, clicked one at a time:**

| # | Button | Time | Result |
|---:|---|---:|---|
| 1 | `/backtest` Run event study | 14.8s | `200`. Per-horizon edge, hit rate, P05–P95, independent-sample counts. Correctly flags `SMALL SAMPLE` on all horizons (18 triggers). |
| 2 | `/backtest` Run 18 tests (Scan) | 10.0s | `200`. **0 discoveries** — "Nothing survived correction across 18 tests." Best uncorrected p 0.0583 → q 0.826. |
| 3 | `/backtest` Profile (reverse) | ~10s | `200`. Full indicator profile with IQR deltas; recorded a run card. |
| 4 | `/report/SPY` Run strategy | 16.6s | `200`. +717.6% at 74.4% exposure vs +1649.8% buy-and-hold — excess **−932.2%**, cost drag −96.4%, reported leading with the loss. |
| 5 | `/thesis/SPY` Run thesis loop (budget 6) | ~16s | `200`. 5 of 6 iterations, catalogue exhausted, **no card produced**. |
| 6 | `/paper-desk` Fetch latest data | 57s | `200`. Live network sweep; button showed `Fetching…` and disabled itself throughout. |
| 7 | `/paper-desk` Apply (new inception) | 17.7s | `200`. All desks re-ran; page moved from "started on 2026-08-15" to "2026-08-20". Reset afterwards. |

No console errors on any of them. Every one rendered a real result rather than a spinner that never
resolved, and each reported its own null or loss plainly — the scan's zero discoveries, the thesis
loop's empty catalogue, the strategy's −932pp excess.

**Re-run against the current backend.** The seven above went through the UI on `:5192`, which proxies
to the `run12` sandbox — a backend process started 26 Aug, before today's commits. All seven were
therefore replayed against `:8013`, running current code, with the same inputs:

| # | Endpoint | HTTP | Time | Against the UI run |
|---:|---|---:|---:|---|
| 1 | `POST /api/backtest/event-study` | 200 | 0.79s | 8,453 bars, 1 arm |
| 2 | `POST /api/backtest/scan` | 200 | 0.98s | 18 trials, **0 discoveries** — identical |
| 3 | `POST /api/backtest/reverse` | 200 | 0.89s | 844 selected / 124 independent, 12 profiles, `exploratory: true`, run card written |
| 4 | `POST /api/report/strategy` | 200 | 0.81s | `total_return 7.17574`, `buy_hold 16.49765`, `cost_drag −0.96436`, exposure 0.7445, 112 trades — **identical to the decimal** |
| 5 | `POST /api/thesis/run` | 200 | 0.86s | 5 of 6 iterations, `outcome: catalogue_exhausted` — identical |
| 6 | `POST /api/paperdesk/refresh?fetch=true` | 200 | 37.3s | network sweep |
| 7 | `PUT /api/paperdesk/inception` | 200 | 6.1s | inception moved to 2026-08-20; `DELETE` reset → 200 |

Job 4 also reports `guard: {"status": "passed"}` — the lookahead guard ran and cleared, with its
AST-allowlist findings attached.

**The UI half was not re-run, and could not be**: driving the buttons against `:8013` needs a second
dev server and the folder's five-server cap leaves this session exactly one. What can be said instead
is checkable rather than assumed — `git diff --name-only` across all six of today's commits touches
**no** file on any of these seven paths (no `backtest`, `report`, `thesis` or `paperdesk` module,
page or component). Today's changes are confined to the evolution/competition surface and the ticker
chart. So the button wiring exercised above is the current wiring; only the server it talked to was
old, and that half is now covered.

**A timing correction.** The browser-side durations in the first table are wall-clock from click to my
next check and include the fixed `wait` calls I inserted — they are upper bounds, not job durations.
The API timings here are the real ones, and they are roughly an order of magnitude smaller. The one
genuinely slow job is the paper-desk fetch, which is slow because it is a live network sweep.

**Two corrections to this document's own earlier classification, both mine:**

- *"Plan the next round" is not a job.* It fires **no network request**; it switches to the Next
  round tab, which reads `R17-2026-08 — NO COMMITTED PLAN`. It was listed as job-launching on the
  strength of its label. It is navigation.
- *A run id that appeared not to persist, did.* The reverse-conditioning panel reports "Recorded as
  run 1e25007c17718f8e" and `GET /api/backtest/runs/1e25007c17718f8e` returns **404** — because the
  panel displays the first 16 characters of a 64-character sha256. The full id returns `200`. All
  three backtest jobs wrote their run cards. Worth knowing before someone else files it: the
  displayed id cannot be pasted into that endpoint.
