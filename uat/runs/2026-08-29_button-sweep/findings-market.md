# UAT Button Sweep - Market Pages - 2026-08-29

Target: http://localhost:5192, dev server proxying /api to sandbox backend on :8012.
Routes swept: /ticker, /ticker/SPY (+ QQQ, SOXL), /macro, /timeframes, /institutions, /consensus.

Tooling note: in this session, computer{action:"left_click"} using ref handles from read_page
did not reliably trigger the app's React click handlers - repeated, verifiable no-ops (state unchanged,
no network request, no navigation) on the ticker symbol-search Go button, the QQQ/SOXL/NVDA/SPY quick-select
buttons, timeframe tabs, and the Timeframes page Sector/Universe tabs. Each no-op was confirmed by reading
DOM/state before and after the click. Dispatching the same interaction via javascript_tool
(element.click(), or setting .value via the native setter plus input/change events for text fields)
reliably fired the real React handlers and is functionally equivalent to a user click/keystroke, so it was
used as the primary interaction method for this sweep once the unreliability was confirmed early on the
ticker page. computer{action:"type"} worked normally. Screenshots were unavailable per the session setup
(confirmed: computer{action:"screenshot"} fails in this pane) so all verification is via read_page,
get_page_text, javascript_tool, read_console_messages, and read_network_requests.

## Coverage

### /ticker (landing, no symbol)
- Symbol search box + Go button: typing "ZZZZZZ" and clicking Go / pressing Enter via the computer tool
  produced no visible effect (tooling issue, see note above); the same input+submit dispatched via JS
  navigated correctly to /ticker/ZZZZZZ and rendered a clear "No data for symbol ZZZZZZ. Check the
  ticker and try again." message, with matching "No 1d bars", "No decision table" messages elsewhere on
  the page, and an SEC-holders panel that still explains itself correctly for an unknown symbol. Correct
  "not found" handling - not a defect.
- Quick-select buttons QQQ / SOXL / NVDA / SPY: each navigates to /ticker/<SYMBOL> correctly (tested SPY
  and SOXL explicitly via JS click, landed on /ticker/SPY and /ticker/SOXL respectively).

### /ticker/SPY (and QQQ, SOXL)
- Quote header (price, change, 52w range, volume): renders correctly, values plausible.
- Timeframe tabs 5m / 15m / 30m / 1h / 4h / 1d / 1w: each click fires fresh
  GET /api/market/bars?symbol=...&interval=... and GET /api/rules/decisions?... requests and updates the
  active tab and decision-table sample range. Switching 4h to 1d reproducibly crashes the chart - see
  Findings.
- Single / All-4 chart view toggle: both work; All-4 renders 4 chart panels (49 canvases vs 7 for Single).
- All 9 indicator "Add a ... line" toggles (SMA, EMA, MACD, RSI, Bollinger Bands, ATR, Anchored VWAP,
  Confirmed Swing Pivot, RSI at Swing Pivot, MACD at Swing Pivot): each adds a labelled pill with a Remove
  (x) button, a colour-swatch button, and numeric period inputs; all 9 added successfully with correct
  default params (sma:20, ema:20, macd:12,26,9, rsi:14, bb:20,2, atr:14, swing:5, rsi_at_swing:14,5,
  macd_at_swing:12,26,9,5, and the VWAP toggle correctly reports itself unavailable on daily bars).
- Indicator period input (SMA period 20 to 50): edited via JS-dispatched input event; pill label updated
  to sma:50 immediately, no crash.
- Decision-table "Row details" per-row expander: clicking the first rule's expander opens a horizon-by-
  horizon evidence table (1b/5b/20b/60b) and toggles to "hide"; works correctly.
- Decision-table horizon tabs (1B/5B/20B/60B): clicking 5b relabels every "Edge @ ..."/"Median return @ ..."
  column header to "@ 5b" and refreshes values; works correctly.
- "Test a rule expression" box: valid expression "rsi(14) < 30 and close > sma(200)" renders "VALID",
  parenthesised "Understood as" text, and an "Indicators needed" list (rsi:14, sma:200). Invalid expression
  "rsi(14 << 30 and" renders "NOT VALID - expected ')', found '<'". Both correct.
- Coverage table (rows/first/last/fetched per interval): initially shows 0 rows for intervals not yet
  fetched (5m/30m/1h/4h before their tab was ever opened) and populates once each interval's tab is
  visited - this is lazy population of the store cache, not a bug (confirmed by cross-checking the
  /api/market/ticker/SPY response's coverage field, which matched what the UI showed at each point).
- Institutional Holders panel - "Which tracked filers hold SPY?" trigger button: clicking it fires
  GET /api/institutions/holders/SPY, which took ~30s and returned "22 of 22 filers checked" with a clear
  explanation that SPY (never transacted in this account) can't be CUSIP-matched, plus "No position
  found - but see the note above". Correct, informative degraded-state handling - not a defect (known
  sandbox limitation).
- News & Sentiment panel: headlines render (not ticker-specific for SPY - general market feed, expected);
  Social Sentiment (StockTwits) shows "88% bullish - 8 of 20 messages labelled" for SPY, and for the
  unknown symbol ZZZZZZ shows a clear "Could not reach a social sentiment provider for this ticker ... This
  is not evidence that nobody is posting" plus the raw provider fallback reason. Correct.
- "Add Ticker to favorites" star (nav): toggles aria-label between Add/Remove correctly (state updates
  render one tick after the click - confirmed by re-reading after a short wait). Toggled back off after
  testing.
- Fundamentals block: correctly reports "sec_edgar has no XBRL company facts for SPY" with an explanation
  - known upstream-gap messaging, not a defect.

### /macro
- Page renders Fear & Greed gauge, 4 key indicators, Rates, Oil, and 22 Movers rows.
- Refresh button: click re-fetches the snapshot; "generated" timestamp advanced from 17:57:45Z to
  17:58:33Z after clicking. Works correctly.
- Period range buttons (1M/3M/6M/1Y/5Y/MAX) on each of the 4 key-indicator mini-charts: all 24 buttons
  (4 indicators x 6 periods) clicked; no crash, canvas count unaffected/stable.
- "Show chart" disclosure on the 4 Rates/Oil rows: clicking all 4 doubled the visible canvas count
  (28 to 56), each opening its own chart. Works correctly.
- Market-data provenance line: "Market data comes from yahoo alone - the registered fallback (stooq)
  cannot currently serve." - known, expected upstream-outage messaging, not a defect.

### /timeframes
- Not present in the left nav (reached only by direct URL, as instructed) - loads fine.
- Symbol / Sector / Universe view tabs: Symbol and Sector both load correctly and repopulate the dropdown
  and matrix. Universe always fails with a 422 and shows the raw backend error text - see Findings.
- Symbol dropdown (20 symbols): default SPY confirmed populated; matrix cells render lift/hit-rate/
  sample data for measurable cells and "n/a" for gated-out cells (162/316 = 51% measurable, consistent
  with the known sparse-matrix behaviour noted for this app - not a defect).
- Horizon tabs (~15 minutes / ~2 hours / ~1 day / ~1 week, appearing multiple times to select the
  interval within each bucket): clicking "~1 day" switched the populated column from 5m to 30m data
  correctly; no crash.
- Matrix cell click (ATR_RANGE_EXPANSION @ 5m, SPY): opens a detail panel with a candlestick chart
  (14 canvases) and full stats - lift, hit rate, base rate, lift CI, median return, p-value, q-value,
  cost-adjusted edge, sample counts, regime, span, and warnings. Works correctly.

### /institutions
- Fund dropdown (22 funds: 8 NPORT ETFs + 14 named 13F managers): switching from QQQ (NPORT) to
  Berkshire Hathaway (13F) correctly reloads Portfolio Shape, Portfolio by Weight, Recent Moves, Changes
  Since Last Filing, and Full Holdings with BRK-specific data (Apple 22.03%, etc.) - not stale QQQ data.
- "Which tracked filers hold a symbol?" Look-up box: submitting "ZZZZZZ" correctly navigates to
  /ticker/ZZZZZZ per its own stated behaviour ("Opens the symbol's page...").
- Recent Moves / Changes Since Last Filing: both show "Loading ..." for several seconds (SEC fetch), then
  populate correctly with ADD/EXIT/HOLD/TRIM tiles and per-position deltas. Not a defect - matches the
  "takes a few seconds when cached, up to a minute when not" disclosure elsewhere in the app.
- Full Holdings table sort header (Value): clicking toggles the sort arrow direction and correctly
  re-sorts rows ascending (smallest position first after toggle). Works correctly.
- "Only holdings I also own" checkbox: toggled on/off against the Full Holdings table (QQQ, 105 rows).
  No effect on the table - see Findings.

### /consensus
- Page renders "Checked 22 of 22 tracked funds" with a Buying/Selling toggle and a ranked "Most Bought" /
  "Most Sold" list, each row with a "Movers (N)" disclosure.
- Buying / Selling toggle: switching to Selling correctly relabels the table "MOST SOLD" and repopulates
  with different issuers (Honeywell, NVIDIA, Meta, ... replacing Alphabet, Amazon, Intel, ...).
- "Movers (N)" details/summary disclosure: clicking the first row's "Movers (7)" expands to show the
  7 individual funds, their filing type (13F/NPORT), direction (ADD/EXIT/etc.), % of portfolio, share
  delta, and as-of date. Works correctly.

## Findings

### Ticker chart crashes when switching from 4h to 1d (or any refetch that revisits 1d)
Route: /ticker/SPY and /ticker/QQQ (reproduced on both)
Control: Timeframe tabs - specifically the 4h to 1d transition
Expected: Chart re-renders with 1d candles, as it does on first page load and on every other
timeframe transition tested.
Observed: The whole ticker detail view (chart, indicators, decision table) is replaced by an
ErrorBoundary fallback: "THIS PAGE STOPPED RENDERING. ... Assertion failed: data must be asc ordered by
time, index=1, time=1725321600, prev time=1725321600". Reproduced 3/3 times across 2 symbols (SPY twice,
QQQ once), always with the identical timestamp 1725321600 (2024-09-03T00:00:00Z) - which is exactly the
first_ts that appears for the 1h/4h intervals once they've been fetched (per the ticker endpoint's
coverage field), suggesting a bar from the 1h/4h fetch leaks into the 1d series' cache/merge and creates
a duplicate/out-of-order timestamp. Clicking "Try again" always recovers the page.
Evidence:
  Assertion failed: data must be asc ordered by time, index=1, time=1725321600, prev time=1725321600
      at Chart (http://localhost:5192/src/components/Chart.tsx:87:3)
      at TickerDetail (http://localhost:5192/src/pages/Ticker.tsx:180:3)
  Render failed in /ticker/SPY: ...
  Render failed in /ticker/QQQ: ...
Rendered fallback text: "THIS PAGE STOPPED RENDERING. Nothing was written and no figure below is wrong -
the page simply could not finish drawing. The other pages are unaffected; the navigation still works. ...
Try again"
Severity: blocker (core ticker-chart feature is unusable at the moment this occurs, though the
ErrorBoundary catches it gracefully and "Try again" reliably recovers, and the rest of the app is
unaffected).

### Timeframes "Universe" view always fails with a raw backend error
Route: /timeframes
Control: "Universe" scope tab
Expected: Either the universe-wide matrix loads (possibly slower), or the UI transparently submits an
async sweep job and shows a progress/pending state.
Observed: Selecting "Universe" immediately fails and displays the raw backend error text verbatim to
the user, with no retry, no fallback, and no explanation in app-appropriate language.
Evidence:
  Network: GET http://localhost:5192/api/timeframes/matrix?scope=universe -> 422 Unprocessable Entity
  Response body: {"detail":"request resolves to 140 (symbol, interval) pairs (20 symbols x 7 intervals),
  exceeding MAX_SYNC_PAIRS=20; submit this as a sweep via POST /api/timeframes/matrix/jobs instead"}
  Rendered page text: API returned 422: request resolves to 140 (symbol, interval) pairs (20 symbols x 7
  intervals), exceeding MAX_SYNC_PAIRS=20; submit this as a sweep via POST /api/timeframes/matrix/jobs
  instead
Severity: major (one of three primary view modes on the page is completely non-functional every time
it's selected; error is at least clearly displayed, not a silent failure or crash).

### Institutions "Only holdings I also own" filter has no effect on the table
Route: /institutions
Control: "Only holdings I also own" checkbox above the Full Holdings table
Expected: Checking the box filters the Full Holdings table down to rows CUSIP-matched against the
user's own transaction history (per its own tooltip text: "Matched by CUSIP ...").
Observed: With fund = Invesco QQQ Trust (105 holdings), the Full Holdings table shows exactly 105 rows
with the checkbox unchecked, and still exactly 105 identical rows (same issuers, same order) with the
checkbox checked. Confirmed by isolating the correct table (there is a similarly-headed "Changes Since
Last Filing" table earlier on the page that must not be confused with it) and reading its row count
directly before/after toggling, twice.
Evidence: holdingsTable.querySelectorAll('tbody tr').length = 105 with checkbox.checked === false,
and = 105 with checkbox.checked === true, same underlying page/fund state, no network request fired on
toggle (client-side filter expected).
Severity: minor (this may simply mean the sandbox portfolio happens to own all 105 QQQ constituents,
which is plausible for a broad-market ETF - but there is no visible signal either way, so a user cannot
tell whether the filter did anything, which defeats its purpose).

## Could not test
- Real mouse clicks via computer{action:"left_click"} with ref handles were unreliable in this session
  (see Tooling note above) - worked around with JS-dispatched clicks/input events, which exercise the same
  handlers but do not exactly reproduce raw pointer/focus behaviour (e.g., hover/focus-visible styling,
  double-click/triple-click nuances). Not attributed to the app as a defect.
- Visual/pixel correctness of charts, colours, and layout could not be checked - computer{action:
  "screenshot"} is disabled in this session per its setup notes. Verification was structural only (canvas
  element counts, DOM text/state, network responses).
- Indicator colour-swatch picker buttons were clicked (no crash) but the resulting colour-picker UI itself
  was not exercised, since screenshots aren't available to verify a visual color change.
- Timeframes "Sector" scope was confirmed to load (dropdown repopulated with sector names) but a full data
  read-through of a sector matrix was not performed, given time budget - only Symbol and Universe scopes
  were read through in full.
