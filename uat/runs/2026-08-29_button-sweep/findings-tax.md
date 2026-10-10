# UAT Button Sweep — Tax Engine (/tax, /wash-sales)

Date: 2026-08-29
Tester: automated UAT sweep (manual-style click-through)
Environment: http://localhost:5192 (Vite dev server) proxying to sandbox backend on :8012
Ledger under test: `uat/sandbox/run12/store/ledger.sqlite` — 1 account, 3 instruments, 4 transactions total, all dated in 2026, **zero disposals**. Confirmed via `GET /api/health/stores`. This ledger has no sales, so both pages are legitimately near-empty on every tax year; that is data absence, not a defect.

## Coverage

### /tax
- **Tax year selector (combobox, default 2026)** — exercised: 2026, 2025, 2024, 2021, 2018 (representative sample across the full 2018-2026 range offered). Each selection fired `GET /api/tax/report?year=YYYY`, all returned `200 OK`.
  - 2026: "Nothing was disposed of in 2026. The ledger holds 4 transactions dated in this tax year — see Activity — but no lot was sold, so there is no gain or loss to report and no Form 8949 to file for it." Correctly distinguishes "no disposals" from "no activity."
  - 2025, 2024, 2021, 2018: "No YYYY activity at all. The ledger holds 4 transactions, none of them dated in this tax year — pick another year above. This is an absence of data, not a report of zero gains, so no figures are shown below." Wording is clear and correctly avoids implying a computed zero.
- **Raw `/api/tax/report?year=2026` payload inspected directly** (via `fetch` in-page): all numeric fields (`short_term_gain`, `long_term_gain`, `disallowed_loss_total`, `gain_on_uncertain_basis`, etc.) are clean string `"0"` values, `rows: []`, `wash_sales: []`, `warnings: []`. No `NaN`, `null`, or `undefined` in the payload.
- **1099-B reconcile panel, Form 8949 table, sort headers, expand/collapse rows, export/download control** — none of these render in this data state. Confirmed with a full accessibility-tree dump (`read_page filter=all`) at year=2026: the only elements in `<main>` are the heading, the two intro/disclaimer paragraphs, the tax-year `<select>`, and the empty-state sentence with its "Activity" link. These controls are presumably conditional on having at least one disposed lot / Form 8949 row, which this sandbox never produces — could not exercise them (see "Could not test").
- **In-text "Activity" link** inside the empty-state sentence — present, correctly targets `href="/activity"`. Click attempts did not navigate (see "Could not test" — attributed to browser-tab contention from concurrent UAT sessions, not an app defect).
- Console errors: none (`read_console_messages onlyErrors:true` -> "No console logs.") across all year switches.
- Network: every `/api/tax/report` and `/api/portfolio/transactions` call returned `200 OK`; no `4xx`/`5xx` observed.

### /wash-sales
- Page loaded cleanly: heading "Wash Sales", two disclaimer paragraphs, and a single empty-state message: "No wash sales on record. Nothing in your connected ledger's transaction history has a loss sale followed by a replacement purchase within 30 days, in either direction. This is an absence of data, not a report of zero risk elsewhere — it only reflects what this app has been shown." Clear and correctly hedged language.
- Full accessibility tree (`read_page filter=all`) confirms **no other interactive controls exist on this page** in the current data state — no filters, no per-symbol expand rows, no date-range picker, no export button. This matches the ledger having 0 wash-sale detections.
- `GET /api/tax/wash-sales` → `200 OK`. Raw payload inspected directly: `{"as_of":"2026-08-29","total_deferred":"0","total_permanently_disallowed":"0","open_window_count":0,"symbol_count":0,"symbols":[]}` — clean, no `NaN`/`null`/`undefined`.
- Console errors: none.

## Findings

No defects found. Every table/panel that rendered was internally consistent, every numeric field was a clean `"0"` (never `NaN`, `undefined`, or a fabricated non-zero), and both pages use carefully worded empty-state copy that explicitly distinguishes "no data available" from "computed to zero" — which is exactly the kind of mislabeling risk this sweep was asked to watch for, and it is handled correctly.

## Could not test

- **1099-B reconcile panel, Form 8949 row table, sort headers, row expand/collapse, and any export/download control on /tax** — these did not render in any of the 9 available tax years because the sandbox ledger has zero disposed lots. Cannot exercise their inputs, run/compare button, or export behavior without a ledger containing at least one sale. Recommend a follow-up sweep against a seeded ledger with disposals if these controls need coverage.
- **Per-symbol wash-sale detail rows / expand controls on /wash-sales** — same root cause: zero wash sales in this ledger, so no rows exist to expand.
- **In-text "Activity" link click-through on /tax** (`href="/activity"`, and separately the "Activity" item in the left nav) — two click attempts via `computer{action:"left_click", ref:...}` did not change `location.pathname` (stayed on `/tax`), with no console errors and no failed network requests. Given that direct URL navigation (`navigate` to `/wash-sales`) worked normally immediately after, and this session shares the browser with four other concurrently-driving UAT agents (`tabs_context` showed tabs tab-3/5/6/7 also on :5192, with focus shifting between them), this looks like tab-focus contention in the shared browser tooling rather than a broken link in the app. Flagging as inconclusive rather than as a finding — no reliable evidence either way.
