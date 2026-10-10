# UAT Button Sweep - findings-money

Date: 2026-08-29
Tester: Claude (automated UAT agent)
Target: http://localhost:5192 (Vite dev server, proxying /api to sandbox backend on :8012)
Sandbox data dir observed: <repo>\uat\sandbox\run12\data

## Method note

The browser-automation `computer` tool's `left_click` action did not reliably dispatch
clicks that the app's React handlers responded to in this session (confirmed on a
canvas-adjacent range-tab button, a nav link, and a favorites-star button - coordinates
were verified correct via `elementFromPoint`, but state never changed after the tool's
click). A JS-dispatched `.click()` on the same element (`el.click()`, or a proper
React-controlled-input update via the native `value` setter + `input` event) reliably
produced the expected state change every time. All controls below were therefore
exercised via `javascript_tool`-driven `.click()` / native-setter input changes rather
than the `computer` tool's coordinate clicks, and verified by reading resulting DOM
state, `aria-*` attributes, network requests, and rendered text. This is flagged as a
tooling limitation of this UAT session, not an app defect - it is not listed as a
finding below.

## Coverage

### /overview
- Top nav links Overview / Portfolio / Strategy Lab / Market - all present with correct hrefs; Strategy Lab -> /competition and Market -> /ticker confirmed to navigate and render.
- "Add Overview to favorites" star (nav) - clicked: star filled, "Overview" appeared under Favorites; clicked again: reverted to empty star, "Star a page to pin it here." restored. Works both directions.
- "Full portfolio ->" link - navigated to /portfolio, content rendered correctly.
- "Full macro page ->" link - navigated to /macro, page rendered ("Macro" heading, Fear & Greed data present after a brief "Loading macro snapshot...").
- "Full paper desk ->" link - navigated to /paper-desk, page rendered ("Paper Desk" heading, strategy descriptions present).
- Range tabs (1M/3M/6M/1Y/5Y/MAX) for all four Key Indicators charts (US 10-Year Treasury, WTI Crude, US Dollar Index, Bitcoin) - clicked every option on all four tab groups; aria-selected state updated correctly each time, and the "as of / date range / observations" caption text updated to match (e.g. MAX on Treasury correctly expanded to "Jan 2, 1962 - Aug 27, 2026 - 16149 observations"; MAX on WTI to "Jan 2, 1986 - 10231 observations"). US Dollar Index and Bitcoin are CACHED-badged sources and their MAX range stayed at "Dec 15, 2025 - Aug 27, 2026" (176/256 observations) for every range button - plausible given the sandbox's cached data only covers that window, not a rendering bug (see Findings for a note on this instead).
- "Charting by TradingView" attribution links (x4, one per chart) - present with correct href to tradingview.com; not clicked (external site, out of scope to navigate away to a 3rd party).
- Fear & Greed gauge and component table - static content, rendered correctly, all 7 components populated with raw values / ratings / dates.
- Reference desk tables (Savings / Trading / Roth IRA) - static tables, all rows rendered with plausible return% and open-position counts.
- Calendar panel - see Findings (slow/hung first load).
- Attention panel - static text only, no controls; correctly reports "Nothing needs your attention right now."

### /portfolio
- "Add Portfolio to favorites" star - add/remove cycle verified, same behavior as Overview's star.
- Sub-nav row (Paper Desk / Activity / Tax / Wash Sales, each with its own favorite star) - clicked through: Paper Desk -> /paper-desk rendered; Tax -> /tax rendered ("US cost basis across every account..."); Wash Sales -> /wash-sales rendered ("Which section 1091 wash-sale windows..."); Activity -> covered under /activity below. Favorite stars for Paper Desk/Tax/Wash Sales not individually toggled (same component already verified working on Overview/Portfolio/Activity).
- "Download statement" link - href verified (/api/portfolio/statement.md); not clicked, per scope rule against triggering downloads without explicit user permission.
- View tabs "By instrument" / "By account" / "By tax treatment" - clicked all three. Each produced a genuinely different table: By instrument shows symbol rows with a WEIGHT/ACCOUNT BREAKDOWN column; By account groups under "UAT Taxable" with a LOTS column; By tax treatment splits into "Taxable" (populated) and "Retirement (IRA)" (correctly empty - "No positions in this group.", since the sandbox ledger has no IRA account) with an explanatory callout about why gains aren't summed across the boundary.
- "Show/Hide account breakdown for QQQ/AAPL/XLE" (x3 expand toggles) - each expands to a "Per-account breakdown for SYMBOL" row with account/broker/quantity/cost basis/lots detail, and aria-expanded + aria-label (Show <-> Hide) toggle correctly; collapsed each back down successfully.
- Symbol links QQQ / AAPL / XLE -> /ticker/SYMBOL - QQQ link followed, navigated to /ticker/QQQ, page rendered (candlestick chart controls, indicator picker, decision table all present); returned to /portfolio.
- Stat tiles (Cost basis, Market value, Cash, Total equity, Unrealized gain/loss, Accounts funded, Position count, Largest position) - static, all populated with plausible values that reconcile with the Overview numbers.
- Cash-by-account table - static, one row (UAT TAXABLE / robinhood), populated.

### /activity
- "Add Activity to favorites" star - add/remove cycle verified.
- "Import broker exports" expand/collapse button - clicked: expands to an inline scan panel, label toggles "Import broker exports" <-> "Hide import"; scan correctly reported "reading C:\...\uat\sandbox\run12\data" and "No broker exports found in ... Copy the CSVs your brokers export into that directory, then reload this page. Nothing is uploaded." (accurate, sandbox has no drop-in CSVs - not a defect). Collapsed back down successfully. No destructive action occurred (nothing to import).
- Symbol filter textbox + "Apply" (submit button) - typed "AAPL", clicked Apply: table correctly filtered to the 1 AAPL transaction, request fired as GET /api/portfolio/transactions?...&symbol=AAPL; repeated with "QQQ": filtered to the 1 QQQ transaction (...&symbol=QQQ). Cleared filter and re-applied: all 4 transactions returned. Works correctly.
- "Trades only" checkbox + Apply - checked, applied: TRANSACTIONS count dropped from 4 to 3, the "Deposit" row (a non-trade) was correctly excluded, and NET CASH FLOW recalculated to -$5,409.36 (bought-only, excludes the $10,000 deposit). Unchecked afterward, reverted to 4 rows. Works correctly.
- Transactions table - static once filtered/unfiltered, all rows show date, action, symbol, quantity, price, amount, account, and a source/import id; content is internally consistent with the Portfolio page's per-symbol cost basis figures.
- Top nav links Strategy Lab (-> /competition) and Market (-> /ticker) re-verified from this route - both navigate and render correctly.

## Findings

### 1. Overview's Calendar panel can be stuck on "Loading calendar..." for well over 8 seconds on first load of the session, with no progress indication or timeout/error state
- **Route**: /overview
- **Control**: Calendar panel (bottom of page, below Reference desk)
- **Expected**: Panel resolves to calendar content (or a visible error) within a few seconds, consistent with the other panels on the same page.
- **Observed**: On the very first navigation to /overview in this session, every other panel on the page loaded within ~4 seconds, but the Calendar panel remained on the literal text "Loading calendar..." indefinitely. A direct `fetch('/api/calendar/events', {signal: AbortSignal.timeout(8000)})` from the page's own JS context threw `TimeoutError: signal timed out` after the full 8000ms with no response at all - i.e., the request was still in flight with no server response after 8+ seconds. On a later revisit to /overview (a few minutes into the session, after other routes had been exercised), the same panel loaded fully and quickly, showing 13 upcoming calendar entries (earnings/FOMC/CPI/PPI/jobs dates). The panel itself documents that "a cold-cache sweep costs one Nasdaq request per day," which is the most likely explanation - the first calendar fetch per day/session appears to trigger a slow (8s+) upstream cold-cache sweep, and the UI gives no indication that this is happening (no spinner distinct from the static "Loading calendar..." text, no elapsed-time or retry messaging) - a user could reasonably believe the page is broken.
- **Evidence**: Page text on first load: `CALENDAR\nLoading calendar...` persisting through 3 separate get_page_text reads spaced ~2-3s apart (~8s+ elapsed). Network log during that window: `GET http://localhost:5192/api/calendar/events [FAILED: net::ERR_ABORTED]` immediately followed by a second `GET http://localhost:5192/api/calendar/events` request that never resolved to a status in the network log while it was being observed. Direct fetch probe result: `{"error":"TimeoutError: signal timed out","ms":8001}`. On the later successful load, the panel showed: `CALENDAR\n\nEarnings dates for 0 of 3 holdings\n\nearnings coverage capped at 45 days (2026-08-29 to 2026-10-13) though 60 days were requested; a cold-cache sweep costs one Nasdaq request per day, so the earnings horizon does not track the wider FOMC/macro window -- see app.market.calendar's module docstring` followed by 13 populated calendar rows.
- **Severity**: minor (self-resolves, and the in-app docstring indicates this cold-cache behavior is an accepted design tradeoff) - but worth a UX pass, since a first-time user hitting the slow path would see no feedback distinguishing "loading" from "stuck," for what was observed to be well over 8 seconds.

### 2. US Dollar Index and Bitcoin "MAX" range does not extend beyond their already-short window
- **Route**: /overview
- **Control**: Range tabs for "US Dollar Index" and "Bitcoin" (Key Indicators)
- **Expected**: "MAX" should show materially more history than "1Y" (as it does for the FRED-sourced Treasury and WTI Crude tiles, which correctly expand from ~1 year to 60+ years of data).
- **Observed**: For both CACHED-badged tiles (US Dollar Index, Bitcoin), the date range and observation count shown are identical across 1Y and MAX: "Dec 15, 2025 - Aug 27, 2026 - 176 observations" (USD Index) and "Dec 15, 2025 - Aug 27, 2026 - 256 observations" (Bitcoin), in both cases. This is plausibly correct - the sandbox's cached data source may genuinely only have ~8 months of history seeded - but it is indistinguishable in the UI from a MAX-range bug, since clicking through 1M/3M/6M/1Y/5Y/MAX produces no visible change at all beyond 1Y for these two tiles.
- **Evidence**: get_page_text after clicking MAX on all four tiles: Treasury -> "Jan 2, 1962 - Aug 27, 2026 - 16149 observations"; WTI -> "Jan 2, 1986 - Aug 25, 2026 - 10231 observations"; US Dollar Index -> "Dec 15, 2025 - Aug 27, 2026 - 176 observations"; Bitcoin -> "Dec 15, 2025 - Aug 27, 2026 - 256 observations" (both CACHED tiles unchanged from their 1Y figures shown at initial page load).
- **Severity**: cosmetic/minor - treated as a non-defect per the sandbox-data caveat (small synthetic ledger/cache), noted only because the identical numbers for 1Y and MAX make the range control look inert for these two tiles specifically.

## Could not test

- The `computer` tool's coordinate-based `left_click` was not usable for verification in this session (see Method note above) - all interaction had to be re-verified via JS-dispatched clicks/input events instead. Functionally this still exercised every control, but it means the sweep does not independently confirm real-mouse-event handling (e.g., any CSS :hover/:active-dependent behavior, or a click handler that specifically requires native PointerEvent properties) - no such gap was observed, but it could not be ruled out through this tool.
- TradingView attribution links (x4 on /overview) were not clicked, since they navigate to an external third-party site (tradingview.com) outside the scope of this sweep; their href values were verified instead.
- "Download statement" (/portfolio) was not clicked, since it triggers a file download, which requires explicit user permission per the operating rules for this session.
- "Import broker exports" (/activity) was exercised only in its "no files present" state (the sandbox data directory is empty) - the actual CSV-import code path (parsing, dedup, error handling for malformed files) could not be exercised without adding files to the sandbox directory, which is outside the observation-only scope of this task.
- Did not attempt to test what happens if the sandbox backend (port 8012) is unreachable - no way to induce that condition without modifying the running stack.
