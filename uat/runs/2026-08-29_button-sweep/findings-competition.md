# Competition page - UAT button sweep - 2026-08-29

Target: http://localhost:5192/competition (Vite dev server, proxying /api to sandbox backend on :8012)
Also checked: http://localhost:5192/this-route-does-not-exist

## Methodology note

`computer` left_click (CDP-driven mouse click) did not register on this page in this session - clicking
a tab's `ref` landed on the correct element (confirmed via `document.elementFromPoint`) but the app's
`aria-selected` state never changed. This matches the session's other known limitation (screenshots
disabled, "Browser pane is not displayed", initial `read_page` returned a 0x0 viewport until the tab was
explicitly resized with `resize_window`). All interactions below were therefore performed by dispatching
real DOM events from `javascript_tool` (`element.click()` for buttons/checkboxes/rows, and the native
HTMLInputElement/HTMLSelectElement/HTMLTextAreaElement value setter + dispatchEvent(new Event(...,
{bubbles:true})) for text/select inputs) and then reading the resulting state back from the DOM
(aria-selected, checked, disabled, value, rendered text). This reaches the same React event handlers a
trusted click/keystroke would and is reflected in real network requests, so the results below are
load-bearing, but flagging it since it is a deviation from the prescribed ref-click method.

## Coverage

### Summary tab
- Loads by default at /competition. Heading "Competition", Round 15 narrative, "Programme scale" and
  "This round's numbers" stat blocks, and the 8-row window-detail table all render with real data. No
  interactive controls beyond the shared tab strip and the two header CTAs. No blank body, no raw error
  text, no console errors specific to this tab.

### Leaderboard tab
- Purpose select (Savings / Trading / Roth IRA): cycled Trading -> Savings -> Roth -> Trading. Trading
  shows the 3-row r15 table. Savings and Roth both render a graceful, backend-sourced empty message
  ("No round has run any savings-purpose card yet... - see strategy-program/THREE-PURPOSES-PLAN.md
  section 7") rather than a blank panel or error. GET /api/competition/rounds/r15-2026-08/leaderboard?
  rank_by=worst&purpose=savings -> 200 OK with unscored_reason populated - this is a backend-authored
  message rendered as-is, not a frontend defect.
- Round select (17 options): exercised r15 -> r14 -> r13 -> r11 -> back to r15. r14 (large 22-row
  momentum/trend field) and r11 render full tables. r13 ("no scored results") renders "Round 13 ...
  has no scored results. Nothing has been run for this round yet..." - graceful.
- Rank by select (Median excess / Worst-window excess / Hit rate / Excess per exposure): confirmed
  it actually re-sorts the table, not just cosmetic - switching to "Worst-window excess" reordered the
  3 r15 rows from [Ladder, Static, ATR] to [ATR, Static, Ladder], correct for worst-excess values
  -16.11%, -0.02%, -0.02%.
- Agent rows (3 clickable tr role="button" rows for r15; row for r14 also tried): clicking a row
  switches to the Agent tab and fetches /api/competition/rounds/<round>/agents/<id>. r14's row
  (B3-concentrated) rendered a full trade-by-window breakdown correctly. All three r15 rows
  (ladder-qld-schd, qqq-ief-gld-static, qqq-ief-gld-atr-tilt) returned 500 and rendered the raw
  string "Internal Server Error" in the Agent panel - see Findings.

### Agent tab
- Direct visit (no row selected) shows the placeholder "Select an agent from the Leaderboard to see its
  trades." - sensible empty state.
- Via a Leaderboard row click: r14 agent renders a full per-window trade table (entries, exits, P&L,
  share of return) correctly. r15 agents render "Internal Server Error" - see Findings.

### Findings tab
- Round select: r15 (rich findings with numbered Decision entries, a correction note from round 16,
  "Sources read" footer) renders correctly. r13 renders the graceful "r13-2026-08 wrote nothing down --
  no findings files were found for this round." message.
- All / Decision filter buttons: both clickable, no crash; only one entry type ("Decision") exists in
  the sandbox data so the filter has nothing visibly different to show, but it does not error.

### Selection tab
- Round select: r15, r14 (both have no selection artifact) render the documented graceful message
  "No selection for r15-2026-08 [/r14-2026-08]. The rule ranks on a round's own live out-of-sample
  matrix, and this round has none - pick another round above." r11 (does have a selection artifact, per
  a direct fetch probe returning 200) renders a full "Desk roster" table with rank/live-median/hits/
  seated-by columns. This is the documented 404 non-defect case, confirmed rendering correctly on both
  the empty and populated sides.

### Next round tab
- Renders "Next round - R17-2026-08 / No committed plan" with the explanatory sentence, plus "What the
  previous round recorded for this one" carried over from round 16/15's findings. No unique controls
  besides the shared tab strip; content is read-only. No blank body, no error text.

### Loop tab
- Idle state confirmed: GET /api/competition/loop -> 404 (documented non-defect), rendered as "The loop
  has never been started."
- Form controls (checkboxes, selects, textarea, ticker inputs) all exercised - see "Loop start form"
  below.
- Generations-list purpose select (Trading / Savings / Roth IRA, separate from the form's book
  checkboxes): switching it updates the "Trend for <purpose>" heading correctly (verified "Trend
  for savings" appeared after selecting Savings) and re-fetches
  /api/competition/loop/generations?...&purpose=savings. All three purposes show "Not enough
  generations yet." / "No generations recorded for this purpose yet." - sandbox has none.
- Newer / Older pagination buttons: present, both disabled=true (0 of 0 generations) - correct
  given no data.
- Paper desk review queue: "Nothing is waiting for review." - no per-item Approve/Keep-for-review
  buttons render because the queue is empty (verified no button text matching approve/seat/shelve/
  reject/retire/keep exists anywhere in the DOM).
- Review shelf: "Nothing on the shelf yet." - same, no per-item Seat/Retire buttons render.

### 404 route
- http://localhost:5192/this-route-does-not-exist renders a proper "Not found" page: "Nothing is
  routed at /this-route-does-not-exist." plus a "Where you might have meant" list of every real page in
  the app grouped by section (Overview, Portfolio, Strategy Lab, Market...). Not blank, not a crash, no
  React error boundary. window.location.href confirms the SPA router kept the attempted path in the
  URL rather than silently redirecting.

## Loop start form

(a) Trading and Roth IRA start ticked, Savings unticked. PASS.
Evidence: {"comp-loop-purpose-trading":{checked:true,disabled:false},"comp-loop-purpose-roth":
{checked:true,disabled:false},"comp-loop-purpose-savings":{checked:false,disabled:false}} read
immediately after the Loop tab first rendered.

(b) Ticking Savings works; unticking books works. PASS.
Evidence: clicking #comp-loop-purpose-savings produced {trading:true, roth:true, savings:true}
(all three ticked). Then clicking #comp-loop-purpose-trading and #comp-loop-purpose-roth in turn
produced {trading:false, roth:false, savings:true} - both untick successfully down to one.

(c) With only one book ticked, that checkbox becomes disabled and cannot be unticked further. PASS.
Evidence: with only Savings ticked, document.getElementById('comp-loop-purpose-savings') read
{checked:true, disabled:true}. Dispatching another .click() on it left it at
{checked:true, disabled:true} - unchanged, confirming the disabled control absorbs the click and the
selection can never reach zero.

(d) Typing purposes=['trading', 'roth', 'saving'] into Goal raises an inline, non-blocking warning
naming "Books to breed for" and flagging "saving". PASS.
Evidence, rendered text under the Goal label after setting the textarea value and dispatching an
input event: "This goal names a setting the goal field cannot change / purposes=['trading', 'roth',
'saving'] This text is recorded but does not steer the search; set trading, roth, saving in Books to
breed for below to actually change it. saving is not a purpose. The legal values are savings,
trading, roth. / Starting the loop is still fine -- the goal is recorded verbatim either way, and this
is a warning, not a check you have to clear." Both "Start the loop" buttons remained disabled:false
throughout, confirming the warning does not block anything.

(e) An ordinary question raises no warning. PASS.
Evidence: after setting the Goal textarea to "does a semiconductor tilt survive a drawdown?", the
rendered text contains neither "cannot change" nor "is not a purpose"; the text immediately following
the "GOAL" label reverts to the static helper copy ("Recorded with every generation and shown here
beside the results...").

(f) focus=NVDA,AMD in Goal warns and points at "Must include tickers"; entering NVDA, AMD there
clears the warning. PASS.
Evidence: after setting Goal to focus=NVDA,AMD, rendered text: "This goal names a setting the goal
field cannot change / focus=NVDA,AMD This text is recorded but does not steer the search; set NVDA, AMD
in Must include tickers below to actually change it." After then setting the "Must include tickers"
input (placeholder "e.g. NVDA, AMD") to "NVDA, AMD" and dispatching an input event, the rendered text
no longer contains "cannot change" anywhere on the page, and the Goal section reverts to the static
helper copy.

Other Loop-form controls exercised beyond (a)-(f): Agents-per-generation select (4/6/8/10/12/16/20/24,
changed to 20, value stuck), Parallel-workers select (1/2/4/6/8, changed to 8, value stuck), Must-avoid
tickers input (set to TSLA, value stuck). All held their values correctly with no cross-field
interference.

## Findings

### Round 15 agent-detail lookup returns 500 for every card and is rendered as raw, unstyled backend text
- Tab: Agent (reached via Leaderboard row click, round r15-2026-08)
- Control: Any Leaderboard row for round 15 ("Drawdown Ladder - QLD/SCHD/IEF", "QQQ/IEF/GLD Static
  Core-Satellite (Trading, No Tilt)", "QQQ/IEF/GLD ATR Vol-Tilt Core (Trading)")
- Expected: Clicking a leaderboard row switches to the Agent tab and shows that card's per-window
  trade detail, the way it does for round 14 and round 11.
- Observed: The Agent tab shows only the plain text "Internal Server Error", inside the same
  generic <div class="placeholder"> element the app also uses for legitimate empty states (e.g. "Select
  an agent from the Leaderboard to see its trades."). There is no error styling, no indication a request
  failed, no retry affordance, and no way to distinguish this from a normal empty state by appearance
  alone. Reproduced for all three r15 cards, and also for a stale round-14 agent id (B3-concentrated)
  re-queried under round 15 - i.e. the failure is round-scoped, not agent-specific: every agent lookup
  under r15-2026-08 fails, while the identical endpoint shape works for r14 and r11.
- Evidence:
  - GET http://localhost:5192/api/competition/rounds/r15-2026-08/agents/ladder-qld-schd -> 500
  - GET http://localhost:5192/api/competition/rounds/r15-2026-08/agents/qqq-ief-gld-static -> 500
  - GET http://localhost:5192/api/competition/rounds/r15-2026-08/agents/qqq-ief-gld-atr-tilt -> 500
  - GET http://localhost:5192/api/competition/rounds/r15-2026-08/agents/B3-concentrated -> 500
  - Direct fetch() of the first URL returns {"status":500,"body":"Internal Server Error"} verbatim -
    the backend itself returns no structured error, just that literal string.
  - Rendered DOM: <div class="panel"><div class="placeholder">Internal Server Error</div></div>
  - Contrast: GET .../rounds/r14-2026-08/agents/B3-concentrated -> 200 OK, renders full trade detail;
    GET .../rounds/r11-2026-08/... (via Selection tab) also loads correctly.
- Severity: major. This is not the LoopConfig/promotion_max_shared_windows schema caveat the brief
  called out (that's specific to starting the loop) - this is the agent-detail endpoint for the newest
  results-bearing round failing outright, which makes the Agent tab unusable for round 15's own cards
  (the round the Summary tab highlights as "Newest round with results"), and the frontend gives the user
  no signal that anything went wrong versus a normal empty state.

No other problems were found. Every other tab, filter, selector, and the 404 route behaved as documented
in the brief's "known non-defects" list or rendered gracefully.

## Could not test

- "Start the loop" (two instances: header CTA and the Loop tab's own form-attached button, class
  comp-run-cta) - both confirmed disabled:false (enabled) but deliberately not pressed, per
  instruction, to avoid taking the process-wide DuckDB bar-store lock while four other agents are
  sweeping other pages against the same backend. Reason: excluded from the parallel pass by instruction.
- "Plan the next round" (header CTA, class comp-run-cta) - confirmed disabled:false (enabled) but
  not pressed through to actually starting a round; its target content was instead verified safely via
  the "Next round" tab button, which reads the same briefing without side effects. Reason: excluded from
  the parallel pass by instruction.
- Paper-desk review queue actions (Approve / Keep for review) and review shelf actions (Seat on
  the paper desk / Retire) - no such buttons are present in the DOM at all, because both the queue and
  the shelf are empty in this sandbox ("Nothing is waiting for review." / "Nothing is on the shelf yet.").
  Could not exercise or even locate these controls; per instruction they were not to be actioned even if
  present.
- LoopConfig promotion_max_shared_windows / minimum-one-purpose enforcement - not reachable without
  submitting the start form, which was deliberately not done. No 422 was observed since the form was
  never submitted.
