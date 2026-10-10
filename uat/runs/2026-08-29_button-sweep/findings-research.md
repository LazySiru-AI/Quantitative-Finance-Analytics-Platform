# UAT Button Sweep — research pages — 2026-08-29

Routes tested against `http://localhost:5192` (Vite dev server proxying `/api` to the sandbox
backend on port 8012).

> Written by the sweep worker, saved here by the orchestrator: the worker's own Write call was
> refused by harness policy ("Subagents should return findings as text"), so it returned the content
> and this file is that content with its HTML entities decoded. Nothing else was edited.

## Methodology note (tooling caveat, not an app defect)

In this session, `computer` `left_click` was unreliable for focusing text inputs and for navigating
`<a>` links (including the app's own sidebar nav — clicking "Overview" did not change
`window.location.href`). It did fire real state changes on plain `<button>` elements. This looks like
a quirk of the shared multi-tab CDP session, not a page bug. All subsequent control exercising used
`javascript_tool` to call `element.click()` / dispatch native `input`/`change` events (which React
treats identically to a trusted user click for state purposes), cross-checked against `window.fetch`
spies, `read_network_requests`, and rendered text. Where this could have produced a false negative it
was independently re-verified — the /backtest Load and quick-pick buttons were first found "broken",
then confirmed fully working once tested via `element.click()`.

`read_page`'s accessibility-tree walker also stopped short partway down `/backtest` (cut off after
the basis tabs, never reaching the Event Study / Scan / reverse-conditioning controls) even at high
`max_chars`/`depth`. Direct DOM enumeration via `javascript_tool` was used wherever this happened.

## Coverage

### /backtest
- Symbol textbox + interval select (5m…Weekly) + Load — works. "SPY" + Load fires
  `GET /api/backtest/drawdowns?symbol=SPY&interval=1d&basis=close&top=10` (200) and renders the
  Drawdown Profile section.
- Quick-pick symbol buttons (SOXL, QQQ, NVDA, SPY, TLT) — each fills the symbol textbox with its own
  ticker (verified for SOXL, SPY, NVDA); does not auto-submit, matching the page's two-step design.
- Basis tabs (Close / Adj close / Intraday) — each re-fetches with `&basis=<value>` and updates
  "Episodes considered" and the episode table (367 → 437 → 340 episodes for SPY). Working.
- Event Study: condition (base) input accepts text and persists. "+ add second arm" adds a
  "Condition (Arm B)" input with a "remove" button; "remove" removes it again. Entry select
  (next open / same close) changes value correctly.
- Scan: expression textarea (6 prefilled sample rules) editable; horizons input ("5, 20, 60")
  editable and live-recalculates the "N expressions × M horizons = X tests" count and the Run
  button's label; Target FDR select (0.05/0.10/0.20) changes value. Non-numeric horizons
  ("abc, xyz") correctly drops the count to 0, relabels the button "Run 0 tests" and disables it.
- Reverse conditioning: "move measured over" / "select top" / "profile the prior" selects all change
  value correctly.
- Favorites star toggle — toggles `aria-pressed`, label text, and
  `localStorage['investing-dashboard.favorites.v1']` (add and remove both confirmed).
- No console errors on this route.

### /rules
- "Test a rule expression" input — `rsi(14) < 30 and close > sma(200)` renders `VALID`,
  `UNDERSTOOD AS (rsi(14) < 30) and (close > sma(200))`, `INDICATORS NEEDED rsi:14, sma:200`.
  Deliberate nonsense `close >>> sma(` renders `NOT VALID` / `expected a value, found '>'` — clean,
  non-crashing parse-error reporting. Clearing the field returns to the neutral prompt.
- Catalog table (12 built-in rules) — static reference table, no sort/filter controls.
- In-app link "SPY" (→ `/ticker/SPY`) — followed, loaded, navigated back.
- No console errors.

### /thesis
- Symbol textbox + interval select + Go, and quick-pick buttons (QQQ, SOXL, NVDA, SPY) — quick-pick
  SPY fetches `/api/thesis/ledger?symbol=SPY` and `/api/thesis/holdout?symbol=SPY` (200/200) and
  renders the ledger ("No thesis has ever been registered for SPY… first run here is trial #1") and
  the holdout panel. Correct empty-sandbox state, not a defect.
- Interval select changes value and does not itself refetch (expected — it only affects a future
  run). Go with an unchanged symbol correctly no-ops; Go with a new symbol (QQQ) refetches.
- Iteration budget select (6/12/20/30) changes value and is reflected live in the
  "Run thesis loop (budget N)" button label.
- No console errors.

### /report
- Empty route `/report` — shows "No symbol yet. Try one of these: QQQ SOXL NVDA SPY", no error.
- `/report/SPY` — loads a full narrative report (Overview, Drawdown History, Rule Evidence, Drawdown
  Profile table, Decision Table Summary, Strategy Backtest form, Facts table) via
  `GET /api/report?symbol=SPY&interval=1d` (200). All figures cite a `FIGURES THIS LEANED ON` line.
- Strategy Backtest form: Entry rule / Exit rule / Max holding / Stop loss / Slippage all editable.
  "Run strategy" is disabled while Entry rule is empty and enables once non-empty.
- Favorites star toggle present and functional.
- No console errors.

### /paper-desk
- Book tabs (Savings / Trading / Roth IRA) — each switches book client-side with no new network
  request; correct data per book (opening capital $20,000 / $100,000 / $30,000).
- Inception date input + "Apply" — Apply starts disabled; changing the date to 2026-08-20 enables it
  (not clicked, per instructions). Reset back to 2026-08-15 afterwards.
- "Fetch latest data" — present, enabled; not clicked.
- Per-desk visibility checkboxes — toggle correctly (verified on the Roth IRA checkbox; confirmed
  default mixed-checked state on the 5 Trading-book checkboxes).
- "Book statistics" `<details>`/`<summary>` disclosure per desk — expands correctly, showing
  Equity / Cash / Positions / Total return / Excess vs benchmark / Max drawdown / Capital exposure /
  Open positions / Realised & unrealised P&L / Signals table.
- Searched all three books' rendered text for approve/seat/shelve/reject/retire controls — none exist
  in this sandbox (the single "seat" hit was static explanatory copy, not a control).
- One transient `net::ERR_ABORTED` on `GET /api/paperdesk/state`, immediately followed by a
  successful `200 OK` retry of the same URL, while rapid-switching book tabs. Consistent with a
  self-inflicted in-flight-request cancellation. No user-visible effect. Not filed as a finding.
- No console errors.

## Findings

All three findings are the same defect at three sites: the rule-DSL validator that `/rules` runs
live is not applied to rule inputs elsewhere, so a malformed expression is accepted silently and the
run button stays enabled.

### 1. Event Study condition field accepts an invalid rule expression with no feedback
- **Route**: /backtest
- **Control**: Event Study → "Condition (Base)" text input
- **Expected**: `/rules` reports `NOT VALID` / `expected a value, found '>'` for the same string, so
  a malformed expression here should surface similar feedback, or at least disable "Run event study".
- **Observed**: Typing `close >>> sma(` produces no validation message anywhere in the Event Study
  section and "Run event study" remains enabled. The only way to discover the error is to run it.
- **Evidence**: after setting the value and dispatching an `input` event, the Event Study section's
  `innerText` was unchanged from the no-error baseline — `"EVENT STUDY\nCONDITION (BASE)\n+ add
  second arm\nENTRY\nnext open\nsame close (upper bound)\nRUN EVENT STUDY\nEnter at least one
  condition and run the study."` — and the button's `.disabled` read `false`.
- **Severity**: minor

### 2. Scan textarea does not validate individual expression lines
- **Route**: /backtest
- **Control**: Scan → "One expression per line" textarea
- **Observed**: appending a 7th line `close >>> sma(` to the 6 valid samples updates the trial count
  correctly (6→7 expressions, "RUN 21 TESTS") but shows no line-level error, and Run stays enabled.
- **Evidence**: `"…ONE EXPRESSION PER LINE\nHORIZONS (BARS)\nTARGET FDR (ALPHA)\n0.05\n0.10\n0.20\n
  RUN 21 TESTS\n\n7 expressions × 3 horizons = 21 simultaneous tests…"` with no error text;
  `.disabled === false`. By contrast a non-numeric horizons value **does** disable the button
  ("Run 0 tests", `disabled: true`) — the page can gate this button, it just does not do so for
  per-line rule syntax.
- **Severity**: minor

### 3. Report page's Strategy Backtest entry/exit rule fields accept invalid expressions silently
- **Route**: /report
- **Control**: Strategy Backtest → "Entry rule" (same applies to "Exit rule")
- **Observed**: on `/report/SPY`, setting Entry rule to `close >>> sma(` leaves "Run strategy"
  enabled with no error text near the field, before or after `blur`.
- **Evidence**: `entryVal: "close >>> sma("`, `btnDisabled: false`; the rendered section after blur
  carried no validation message.
- **Severity**: minor

No blocker, major or cosmetic-only issues were found on these five routes. All five render
correctly, handle sparse/empty sandbox data gracefully, and every tested control behaved sensibly
apart from the three validation gaps above.

## Could not test

Job-launching buttons deliberately left unpressed, with observed enabled/disabled state:

- **/backtest** — "Run event study": enabled, with a valid base condition entered.
- **/backtest** — "Run N tests" (Scan): enabled with the 6 default expressions and horizons `5, 20, 60`.
- **/backtest** — "Profile" (reverse conditioning): enabled. Treated as job-launching because it runs
  a computation over the bar store, even though its label does not say Run/Scan/Execute/Start.
- **/thesis** — "Run thesis loop (budget 12)": enabled (label updates with the selected budget,
  tested up to "budget 30").
- **/report** — "Run strategy": observed both disabled (empty Entry rule, the default) and enabled
  (once a non-empty Entry rule is entered). Not named in the exclusion list, but it launches a
  rule-driven backtest against the same bar store, so it was treated with the same caution.
- **/paper-desk** — "Apply" (inception date): disabled by default, enabled once the date changes. Its
  own label says it "re-runs every agent from this date forward" — a job-launching action.
- **/paper-desk** — "Fetch latest data": enabled. Fetches external market data.
- **/paper-desk** — no approve/seat/shelve/reject/retire queue-transition controls exist in this
  sandbox on any of the three books.
